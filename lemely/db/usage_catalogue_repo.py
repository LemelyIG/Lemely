"""The usage catalogue's defaults and current-version lookups (billing spec §4.1, §2.1).

Rates and estimators are versioned admin data. This build seeds version 1 for every
:class:`~lemely.core.metered_actions.MeteredAction`, plus two signup packs, with
``INSERT ... ON CONFLICT DO NOTHING``. The seeding runs lazily the first time a lookup
finds no row, and from ``seed_reference_data`` (plan deviation 6). An admin's later
version wins once its ``effective_from`` has passed.

Signup amounts are ``credit_packs`` rows that are never sold (``is_active = false``,
``price_minor = 0``; plan deviation 7). ``units = 0`` turns a signup grant off.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import TYPE_CHECKING, cast

import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from lemely.core.metered_actions import ACTION_SPECS, MeteredAction
from lemely.core.usage_types import EstimatorParams
from lemely.db.models.billing import CreditPack
from lemely.db.models.enums import Role
from lemely.db.models.usage import EstimatorInputKind, GrantKind, UsageEstimator, UsageRate
from lemely.db.usage_ledger_repo import UsageLedger

if TYPE_CHECKING:
    import uuid
    from collections.abc import Mapping

    from sqlalchemy import CursorResult, Executable
    from sqlalchemy.orm import Session

    from lemely.db.models.usage import UsageGrant

log = structlog.get_logger(__name__)

SIGNUP_STUDENT_PACK = "signup_student"
SIGNUP_TEACHER_PACK = "signup_teacher"
#: About two papers at the top of the seeded marking estimate (spec §2.1).
DEFAULT_SIGNUP_UNITS: Mapping[str, int] = MappingProxyType(
    {SIGNUP_STUDENT_PACK: 250, SIGNUP_TEACHER_PACK: 2000}
)
_SIGNUP_NAMES = {
    SIGNUP_STUDENT_PACK: "Student free allowance",
    SIGNUP_TEACHER_PACK: "Teacher signup credits",
}
TEACHER_SIGNUP_VALIDITY = timedelta(days=30)
#: One signup grant per account: ``usage_grants`` is unique on (owner, idempotency_key).
SIGNUP_IDEMPOTENCY_KEY = "signup"
#: Version 1 applies to every job this build can create.
CATALOGUE_EFFECTIVE_FROM = datetime(2026, 1, 1, tzinfo=UTC)


class MeteringUnconfigured(RuntimeError):
    """No rate or estimator row exists for an action, even after seeding the defaults."""


def _inserted(session: Session, statement: Executable) -> int:
    """Run an insert and return how many rows it actually wrote."""
    result = cast("CursorResult[tuple[()]]", session.execute(statement))
    return max(result.rowcount, 0)


def ensure_usage_catalogue(session: Session, *, now: datetime) -> int:
    """Insert every missing version-1 default. Returns the number of rows inserted.

    Idempotent and safe under concurrent callers: every insert is ``ON CONFLICT DO
    NOTHING`` on the table's unique key, so a row that already exists (including one an
    admin has since edited) is never touched.
    """
    inserted = 0
    for action, spec in ACTION_SPECS.items():
        est = spec.default_estimator
        inserted += _inserted(
            session,
            pg_insert(UsageRate)
            .values(
                version=1,
                action=action.value,
                units_per_usd=spec.default_units_per_usd,
                effective_from=CATALOGUE_EFFECTIVE_FROM,
            )
            .on_conflict_do_nothing(index_elements=["version", "action"]),
        )
        inserted += _inserted(
            session,
            pg_insert(UsageEstimator)
            .values(
                version=1,
                action=action.value,
                input_kind=EstimatorInputKind(est.input_kind),
                base_low=est.base_low,
                base_high=est.base_high,
                per_input_low=est.per_input_low,
                per_input_high=est.per_input_high,
                effective_from=CATALOGUE_EFFECTIVE_FROM,
            )
            .on_conflict_do_nothing(index_elements=["version", "action"]),
        )
    for code, units in DEFAULT_SIGNUP_UNITS.items():
        inserted += _inserted(
            session,
            pg_insert(CreditPack)
            .values(
                code=code,
                name=_SIGNUP_NAMES[code],
                units=units,
                price_minor=0,
                currency="EGP",
                is_active=False,
            )
            .on_conflict_do_nothing(index_elements=["code"]),
        )
    if inserted:
        log.info("usage_catalogue_seeded", rows=inserted, at=now.isoformat())
    return inserted


def _latest_estimator(
    session: Session, action: MeteredAction, now: datetime
) -> UsageEstimator | None:
    return session.scalars(
        select(UsageEstimator)
        .where(UsageEstimator.action == action.value, UsageEstimator.effective_from <= now)
        .order_by(UsageEstimator.version.desc())
        .limit(1)
    ).first()


def _latest_rate(session: Session, action: MeteredAction, now: datetime) -> UsageRate | None:
    return session.scalars(
        select(UsageRate)
        .where(UsageRate.action == action.value, UsageRate.effective_from <= now)
        .order_by(UsageRate.version.desc())
        .limit(1)
    ).first()


def current_estimator(session: Session, action: MeteredAction, *, now: datetime) -> EstimatorParams:
    """The newest estimator in effect at ``now``; seeds the defaults if none exists."""
    row = _latest_estimator(session, action, now)
    if row is None:
        ensure_usage_catalogue(session, now=now)
        row = _latest_estimator(session, action, now)
    if row is None:
        raise MeteringUnconfigured(f"no usage estimator for {action.value}")
    return EstimatorParams(
        version=row.version,
        input_kind=EstimatorInputKind(row.input_kind).value,
        base_low=row.base_low,
        base_high=row.base_high,
        per_input_low=row.per_input_low,
        per_input_high=row.per_input_high,
    )


def current_rate_version(session: Session, action: MeteredAction, *, now: datetime) -> int:
    """The newest rate version in effect at ``now``; seeds the defaults if none exists."""
    row = _latest_rate(session, action, now)
    if row is None:
        ensure_usage_catalogue(session, now=now)
        row = _latest_rate(session, action, now)
    if row is None:
        raise MeteringUnconfigured(f"no usage rate for {action.value}")
    return row.version


def grant_signup_allowance(
    session: Session, *, user_id: uuid.UUID, role: Role, now: datetime
) -> UsageGrant | None:
    """Issue the free start (spec §2.1): idempotent per account.

    A student gets a hidden one-time allowance with no expiry; a teacher gets visible
    credits that expire after 30 days. Other roles, or a pack set to 0 units, get none.
    """
    if role is Role.student:
        code, visible, expires_at = SIGNUP_STUDENT_PACK, False, None
    elif role is Role.teacher:
        code, visible, expires_at = SIGNUP_TEACHER_PACK, True, now + TEACHER_SIGNUP_VALIDITY
    else:
        return None
    query = select(CreditPack).where(CreditPack.code == code)
    pack = session.scalars(query).first()
    if pack is None:
        ensure_usage_catalogue(session, now=now)
        pack = session.scalars(query).first()
    if pack is None or pack.units <= 0:
        log.info("signup_grant_disabled", code=code, user_id=str(user_id))
        return None
    return UsageLedger(session).issue_grant(
        owner_user_id=user_id,
        kind=GrantKind.signup,
        units=pack.units,
        idempotency_key=SIGNUP_IDEMPOTENCY_KEY,
        expires_at=expires_at,
        visible=visible,
        effective_at=now,
    )
