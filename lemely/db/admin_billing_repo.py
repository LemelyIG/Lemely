"""Shared pieces of the admin billing surface (spec §8): the audit helper, errors, names.

**Every admin money or catalogue change goes through :func:`audited` in the same
session and transaction as the change.** The audit row and the change commit or roll
back together; a change with no audit row cannot exist.
"""

from __future__ import annotations

import enum
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Final, Literal

import sqlalchemy as sa
import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from lemely.core.metered_actions import MeteredAction
from lemely.core.subscription_rules import paymob_frequency
from lemely.db.models.admin_audit import (
    HAS_IDEMPOTENCY_KEY_SQL,
    IDEMPOTENCY_KEY_SQL,
    AdminAuditLog,
)
from lemely.db.models.billing import CreditPack, PlanAudience, PlanTier, PlanTierTerms
from lemely.db.models.usage import EstimatorInputKind, UsageEstimator, UsageRate
from lemely.db.subscription_repo import PlanNotPurchasable, PlanSyncFailed
from lemely.db.subscription_repo import sync_paymob_plan as link_paymob_plan
from lemely.db.usage_catalogue_repo import (
    SIGNUP_STUDENT_PACK,
    SIGNUP_TEACHER_PACK,
    TEACHER_SIGNUP_VALIDITY,
    ensure_usage_catalogue,
)
from lemely.io.paymob.client import PaymobError, PaymobNotConfigured

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.orm import Session, sessionmaker

    from lemely.db.models.enums import PlanInterval
    from lemely.io.paymob.client import PaymobClient
    from lemely.runtime.config import PaymobSettings

#: Prefix of the advisory-lock key, so an admin key can never equal the usage ledger's
#: ``usage:<owner id>`` keys (DV-12: both hash into the same 64-bit space).
_LOCK_KEY_PREFIX = "admin-billing:"

#: Events the operator alerts on (``alert=True`` survives only in structlog).
alerts = structlog.get_logger("lemely.db.admin_billing_repo")


class AdminBillingError(Exception):
    """Base error; ``code`` is the machine-readable string the API returns."""

    def __init__(self, code: str, message: str | None = None) -> None:
        super().__init__(message or code)
        self.code = code
        self.message = message or code


class AdminNotFoundError(AdminBillingError):
    """The record named in the path does not exist (404)."""


class AdminConflictError(AdminBillingError):
    """The record's state forbids the action (409)."""


class AdminInvalidError(AdminBillingError):
    """The request is well-formed but its values are not acceptable (422)."""


class PaymobCallError(AdminBillingError):
    """Paymob refused or failed a call this action depends on (502)."""


class ReasonRequiredError(AdminInvalidError):
    """An admin change was attempted without a reason."""

    def __init__(self) -> None:
        super().__init__("reason_required", "Every admin change needs a reason.")


class AuditTarget(enum.StrEnum):
    PLAN_TIER = "plan_tier"
    CREDIT_PACK = "credit_pack"
    USAGE_RATE = "usage_rate"
    USAGE_ESTIMATOR = "usage_estimator"
    CONVERSION_RATE = "conversion_rate"
    USER = "user"
    SUBSCRIPTION = "subscription"
    PAYMENT = "payment"


class AuditAction(enum.StrEnum):
    PLAN_TIER_CREATE = "catalogue.plan_tier.create"
    PLAN_TIER_UPDATE = "catalogue.plan_tier.update"
    PLAN_TIER_SYNC = "catalogue.plan_tier.sync_paymob"
    CREDIT_PACK_CREATE = "catalogue.credit_pack.create"
    CREDIT_PACK_UPDATE = "catalogue.credit_pack.update"
    FREE_ALLOWANCE_UPDATE = "catalogue.free_allowance.update"
    USAGE_RATE_VERSION = "catalogue.usage_rate.version"
    USAGE_ESTIMATOR_VERSION = "catalogue.usage_estimator.version"
    CONVERSION_RATE_UPDATE = "catalogue.conversion_rate.update"
    CUSTOMER_GRANT = "customer.grant"
    CUSTOMER_ADJUST = "customer.adjust"
    CUSTOMER_FORGIVE_DEBT = "customer.forgive_debt"
    SUBSCRIPTION_MANUAL_ACTIVATION = "subscription.manual_activation"
    SUBSCRIPTION_ACTIVATION_DECISION = "subscription.activation_decision"
    SUBSCRIPTION_EXTEND = "subscription.extend"
    SUBSCRIPTION_CANCEL = "subscription.cancel"
    PAYMENT_REFUND_REQUESTED = "payment.refund.requested"
    PAYMENT_VOID_REQUESTED = "payment.void.requested"
    PAYMENT_REFUND_SUCCEEDED = "payment.refund.succeeded"
    PAYMENT_REFUND_FAILED = "payment.refund.failed"
    PAYMENT_REFUND_UNKNOWN = "payment.refund.unknown"
    PAYMENT_RECONCILE = "payment.reconcile"


def to_jsonable(value: object) -> object:
    """Convert a snapshot value to JSON-safe data. Unknown types are an error, not ``str()``."""
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, enum.Enum):
        return to_jsonable(value.value)
    if isinstance(value, Mapping):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [to_jsonable(item) for item in value]
    raise TypeError(f"cannot audit a value of type {type(value).__name__}")


def _json_object(values: Mapping[str, object]) -> dict[str, object]:
    """``values`` converted for a JSONB column; unknown value types raise ``TypeError``."""
    return {str(key): to_jsonable(item) for key, item in values.items()}


def snapshot(obj: object, fields: Sequence[str]) -> dict[str, object]:
    """The named attributes of ``obj`` as JSON-safe data, for ``before``/``after``."""
    return {name: to_jsonable(getattr(obj, name)) for name in fields}


def audited(
    session: Session,
    admin_user_id: uuid.UUID,
    action: str,
    target_kind: str,
    target_id: uuid.UUID,
    reason: str,
    before: Mapping[str, object] | None,
    after: Mapping[str, object] | None,
) -> AdminAuditLog:
    """Add one audit row to ``session``'s transaction and flush it.

    Raises:
        ReasonRequiredError: ``reason`` is empty or whitespace. Nothing is added.
    """
    cleaned = (reason or "").strip()
    if not cleaned:
        raise ReasonRequiredError
    row = AdminAuditLog(
        admin_user_id=admin_user_id,
        action=str(action),
        target_kind=str(target_kind),
        target_id=target_id,
        reason=cleaned,
        before=None if before is None else _json_object(before),
        after=None if after is None else _json_object(after),
    )
    session.add(row)
    session.flush()
    return row


def idempotency_lookup(action: str, idempotency_key: str) -> sa.Select[tuple[bool]]:
    """The statement behind :func:`already_applied`.

    It repeats the index expression and predicate of ``ix_admin_audit_log_idempotency``
    verbatim, because Postgres uses a partial expression index only when the query's
    expression equals the index's and its WHERE implies the index predicate.
    """
    return (
        select(sa.literal(True))
        .select_from(AdminAuditLog)
        .where(
            AdminAuditLog.action == str(action),
            sa.text(HAS_IDEMPOTENCY_KEY_SQL),
            sa.literal_column(IDEMPOTENCY_KEY_SQL) == idempotency_key,
        )
        .limit(1)
    )


def already_applied(session: Session, *, action: str, idempotency_key: str) -> bool:
    """True when an audit row for ``action`` already carries ``after.idempotency_key``.

    Callers first take :func:`lock_idempotency_key` so two identical requests serialise on the
    key instead of both passing this check.
    """
    return session.scalar(idempotency_lookup(action, idempotency_key)) is not None


def lock_idempotency_key(session: Session, idempotency_key: str) -> None:
    """Serialise concurrent requests carrying the same key until this transaction ends.

    ``pg_advisory_xact_lock(hashtextextended('admin-billing:' || key, 0))``: a 64-bit hash
    (DV-12; the 32-bit ``hashtext`` would share the ledger's keyspace and collide far more).
    """
    session.execute(
        select(
            sa.func.pg_advisory_xact_lock(
                sa.func.hashtextextended(
                    sa.cast(_LOCK_KEY_PREFIX + idempotency_key, sa.Text),
                    sa.cast(0, sa.BigInteger),
                )
            )
        )
    )


# A version may start a little in the past (clock skew between admin and server), never more.
_BACKDATE_TOLERANCE: Final = timedelta(minutes=5)

#: How a tier compares with its Paymob plan (:func:`paymob_drift`).
DriftState = Literal["in_sync", "not_synced", "unverified", "drifted"]
FreeAudience = Literal["student", "teacher"]

#: The free start is stored as non-sellable credit packs whose code starts with this prefix
#: (Phase 04 deviation 7). The prefix is reserved: such a pack must never become sellable, so
#: only ``PUT /free-allowances`` (units alone) may touch one.
SIGNUP_PREFIX: Final = "signup_"

PLAN_TIER_MUTABLE: Final = (
    "name",
    "price_minor",
    "allowance_units",
    "included_seats",
    "seat_allowance_units",
    "extra_seat_price_minor",
    "features",
    "is_active",
)
_PLAN_TIER_AUDIT: Final = (
    "code",
    "name",
    "audience",
    "interval",
    "price_minor",
    "currency",
    "allowance_units",
    "included_seats",
    "seat_allowance_units",
    "extra_seat_price_minor",
    "features",
    "is_active",
    "paymob_plan_id",
    "paymob_plan_mode",
    "paymob_plan_synced_price_minor",
    "paymob_plan_synced_frequency",
)
#: The columns a ``plan_tier_terms`` row snapshots. Until T13 inserts the next terms version
#: with the tier edit, changing one on a tier that has terms would leave the terms (which
#: upgrade pricing reads) at the old numbers while checkout charges the new ones.
_TERMS_FIELDS: Final = (
    "price_minor",
    "extra_seat_price_minor",
    "allowance_units",
    "included_seats",
    "seat_allowance_units",
)
CREDIT_PACK_MUTABLE: Final = ("name", "units", "price_minor", "is_active")
_CREDIT_PACK_AUDIT: Final = ("code", "name", "units", "price_minor", "currency", "is_active")
_SIGNUP_CODES: Final[dict[FreeAudience, str]] = {
    "student": SIGNUP_STUDENT_PACK,
    "teacher": SIGNUP_TEACHER_PACK,
}
_RATE_AUDIT: Final = ("version", "action", "units_per_usd", "effective_from")
_ESTIMATOR_AUDIT: Final = (
    "version",
    "action",
    "input_kind",
    "base_low",
    "base_high",
    "per_input_low",
    "per_input_high",
    "effective_from",
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class PlanTierFields:
    code: str
    name: str
    audience: PlanAudience
    interval: PlanInterval
    price_minor: int
    currency: str
    allowance_units: int
    included_seats: int
    seat_allowance_units: int
    extra_seat_price_minor: int
    features: dict[str, object]
    is_active: bool


@dataclass(frozen=True, slots=True)
class CreditPackFields:
    code: str
    name: str
    units: int
    price_minor: int
    currency: str
    is_active: bool


@dataclass(frozen=True, slots=True)
class FreeAllowanceView:
    """The student free allowance or teacher signup credits, and the pack that stores it."""

    audience: FreeAudience
    pack: CreditPack
    valid_days: int | None


def _free_allowance_view(audience: FreeAudience, pack: CreditPack) -> FreeAllowanceView:
    days = None if audience == "student" else TEACHER_SIGNUP_VALIDITY.days
    return FreeAllowanceView(audience=audience, pack=pack, valid_days=days)


@dataclass(frozen=True, slots=True)
class CatalogueSnapshot:
    plan_tiers: list[PlanTier]
    credit_packs: list[CreditPack]
    free_allowances: list[FreeAllowanceView]
    usage_rates: list[UsageRate]
    usage_estimators: list[UsageEstimator]


def paymob_drift(tier: PlanTier, key_mode: str) -> DriftState:
    """How the tier compares with the Paymob plan it is linked to.

    ``not_synced`` (no plan), ``drifted`` (the plan was made under the other key mode, which
    cannot be charged with these keys, or the price or frequency changed since the sync),
    ``unverified`` (a plan set outside the admin sync: no stamps to compare) or ``in_sync``.
    """
    if tier.paymob_plan_id is None:
        return "not_synced"
    if tier.paymob_plan_mode != key_mode:
        return "drifted"
    if tier.paymob_plan_synced_price_minor is None or tier.interval is None:
        return "unverified"
    if tier.paymob_plan_synced_price_minor != tier.price_minor or (
        tier.paymob_plan_synced_frequency != paymob_frequency(tier.interval.value)
    ):
        return "drifted"
    return "in_sync"


def _has_terms(session: Session, plan_tier_id: uuid.UUID) -> bool:
    """True when the tier has a ``plan_tier_terms`` row (every tier gets version 1 at insert)."""
    with session.no_autoflush:  # the caller's edited tier must not be written by this read
        return (
            session.scalar(
                select(PlanTierTerms.id).where(PlanTierTerms.plan_tier_id == plan_tier_id).limit(1)
            )
            is not None
        )


def _check_tier_shape(tier: PlanTier) -> None:
    if tier.audience is PlanAudience.student and (
        (tier.included_seats or 0)
        or (tier.seat_allowance_units or 0)
        or (tier.extra_seat_price_minor or 0)
    ):
        raise AdminInvalidError("seat_fields_on_student_tier", "Student tiers carry no seats.")


def require_reason(reason: str) -> None:
    """Refuse a blank reason before anything is read or written."""
    if not (reason or "").strip():
        raise ReasonRequiredError


def _require_not_before(latest: UsageRate | UsageEstimator | None, starts: datetime) -> None:
    """A new version may not start before the latest one.

    The Phase 04 readers take the highest version already in effect, so a version scheduled
    for next month would be silently overridden by a later "fix" that starts today.
    """
    if latest is not None and starts < latest.effective_from:
        raise AdminInvalidError(
            "effective_from_before_latest",
            "A new version cannot start before the latest one "
            f"({latest.effective_from.isoformat()}).",
        )


def _require_metered(action: str) -> None:
    try:
        MeteredAction(action)
    except ValueError as exc:
        raise AdminInvalidError("unknown_action", f"{action} is not a metered action.") from exc


class AdminCatalogueService:
    """Plan tiers, credit packs, free allowances, usage rates and estimators (spec §8 area 1).

    Tiers and packs are edited in place (their history is the audit log). Rates and
    estimators are versioned: every write is a new row with the next version for its
    action, and old rows are never touched. Free allowances are the two signup packs, edited
    only through :meth:`set_free_allowance`.

    Every write checks its input first and adds its audit row last, in the same transaction
    as the change: a refused write leaves neither.
    """

    def __init__(
        self,
        sessionmaker: sessionmaker[Session],
        client: PaymobClient,
        paymob_settings: PaymobSettings,
        *,
        now: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._sm = sessionmaker
        self._client = client
        self._settings = paymob_settings
        self._now = now

    @property
    def key_mode(self) -> str:
        """The Paymob key mode (``test`` or ``live``) plans are created under now."""
        return self._settings.key_mode

    def catalogue(self) -> CatalogueSnapshot:
        with self._sm() as s:
            packs = list(s.scalars(select(CreditPack).order_by(CreditPack.code)))
            signup = {p.code: p for p in packs}
            return CatalogueSnapshot(
                plan_tiers=list(s.scalars(select(PlanTier).order_by(PlanTier.code))),
                credit_packs=[p for p in packs if not p.code.startswith(SIGNUP_PREFIX)],
                free_allowances=[
                    _free_allowance_view(audience, signup[code])
                    for audience, code in _SIGNUP_CODES.items()
                    if code in signup
                ],
                usage_rates=list(
                    s.scalars(
                        select(UsageRate).order_by(UsageRate.action, UsageRate.version.desc())
                    )
                ),
                usage_estimators=list(
                    s.scalars(
                        select(UsageEstimator).order_by(
                            UsageEstimator.action, UsageEstimator.version.desc()
                        )
                    )
                ),
            )

    # -- tiers ---------------------------------------------------------------

    def create_plan_tier(
        self, fields: PlanTierFields, *, admin_user_id: uuid.UUID, reason: str
    ) -> PlanTier:
        """Add a tier. Its terms version 1 is written by ``trg_plan_tiers_seed_terms``."""
        require_reason(reason)
        try:
            with self._sm.begin() as s:
                if s.scalar(select(PlanTier.id).where(PlanTier.code == fields.code)) is not None:
                    raise AdminConflictError(
                        "code_taken", f"A tier with code {fields.code} exists."
                    )
                tier = PlanTier(**asdict(fields))
                _check_tier_shape(tier)
                s.add(tier)
                s.flush()
                audited(
                    s,
                    admin_user_id,
                    AuditAction.PLAN_TIER_CREATE,
                    AuditTarget.PLAN_TIER,
                    tier.id,
                    reason,
                    None,
                    snapshot(tier, _PLAN_TIER_AUDIT),
                )
                return tier
        except IntegrityError as exc:
            raise AdminConflictError(
                "code_taken", f"A tier with code {fields.code} exists."
            ) from exc

    def update_plan_tier(
        self,
        plan_tier_id: uuid.UUID,
        changes: Mapping[str, object],
        *,
        admin_user_id: uuid.UUID,
        reason: str,
    ) -> PlanTier:
        require_reason(reason)
        if set(changes) - set(PLAN_TIER_MUTABLE):
            raise AdminInvalidError(
                "immutable_field", "code, audience, interval and currency are fixed."
            )
        with self._sm.begin() as s:
            tier = s.get(PlanTier, plan_tier_id, with_for_update=True)
            if tier is None:
                raise AdminNotFoundError("plan_tier_not_found")
            before = snapshot(tier, _PLAN_TIER_AUDIT)
            terms_changed = any(
                name in _TERMS_FIELDS and getattr(tier, name) != value
                for name, value in changes.items()
            )
            for name, value in changes.items():
                setattr(tier, name, value)
            _check_tier_shape(tier)
            if terms_changed and _has_terms(s, tier.id):
                # T13 replaces this refusal with the terms version bump.
                raise AdminConflictError(
                    "terms_versioning_pending",
                    "Price, seat and allowance changes are not available yet; name, features "
                    "and active state can be edited.",
                )
            s.flush()
            audited(
                s,
                admin_user_id,
                AuditAction.PLAN_TIER_UPDATE,
                AuditTarget.PLAN_TIER,
                tier.id,
                reason,
                before,
                snapshot(tier, _PLAN_TIER_AUDIT),
            )
            return tier

    def sync_paymob_plan(
        self, plan_tier_id: uuid.UUID, *, admin_user_id: uuid.UUID, reason: str
    ) -> PlanTier:
        """Create a new Paymob plan at the tier's current price and interval, and link it.

        Delegates to Phase 05's ``sync_paymob_plan(..., force_new=True)``, which locks the
        tier, calls Paymob and links the plan with the key mode it was made under. The synced
        price and frequency are stamped here, in the same transaction (DV-11).
        Part B moves that stamp into ``sync_paymob_plan`` so a checkout-created link stamps
        too, and deletes this copy.

        Every Paymob failure rolls the transaction back: no link, no stamp, no audit row.
        """
        require_reason(reason)
        created_plan_id: int | None = None
        try:
            with self._sm.begin() as s:
                tier = s.get(PlanTier, plan_tier_id, with_for_update=True)
                if tier is None:
                    raise AdminNotFoundError("plan_tier_not_found")
                if paymob_drift(tier, self.key_mode) == "in_sync":
                    raise AdminConflictError(
                        "already_in_sync", "This tier already matches its Paymob plan."
                    )
                before = snapshot(tier, _PLAN_TIER_AUDIT)
                created_plan_id = link_paymob_plan(
                    s, self._client, self._settings, plan_tier_id, force_new=True
                )
                if tier.interval is None:  # the helper already refused it; narrows the type
                    raise PlanNotPurchasable("a plan tier without an interval cannot renew")
                tier.paymob_plan_synced_price_minor = tier.price_minor
                tier.paymob_plan_synced_frequency = paymob_frequency(tier.interval.value)
                s.flush()
                audited(
                    s,
                    admin_user_id,
                    AuditAction.PLAN_TIER_SYNC,
                    AuditTarget.PLAN_TIER,
                    tier.id,
                    reason,
                    before,
                    snapshot(tier, _PLAN_TIER_AUDIT),
                )
                return tier
        except PlanNotPurchasable as exc:
            raise AdminInvalidError("not_billable", str(exc)) from exc
        except PlanSyncFailed as exc:
            raise PaymobCallError("paymob_plan_response_unusable", str(exc)) from exc
        except PaymobNotConfigured as exc:
            raise PaymobCallError("paymob_not_configured", str(exc)) from exc
        except PaymobError as exc:
            raise PaymobCallError("paymob_plan_create_failed", str(exc)) from exc
        except Exception:
            if created_plan_id is not None:
                # Paymob holds a plan our database never linked (the stamp, audit insert or
                # commit failed afterwards). It charges no one; the operator should know.
                alerts.error(
                    "paymob_plan_orphaned",
                    plan_tier_id=str(plan_tier_id),
                    paymob_plan_id=created_plan_id,
                    alert=True,
                )
            raise

    # -- packs ---------------------------------------------------------------

    def create_credit_pack(
        self, fields: CreditPackFields, *, admin_user_id: uuid.UUID, reason: str
    ) -> CreditPack:
        require_reason(reason)
        if fields.code.startswith(SIGNUP_PREFIX):
            raise AdminConflictError(
                "reserved_code", "Signup packs are set through free allowances."
            )
        try:
            with self._sm.begin() as s:
                if (
                    s.scalar(select(CreditPack.id).where(CreditPack.code == fields.code))
                    is not None
                ):
                    raise AdminConflictError(
                        "code_taken", f"A pack with code {fields.code} exists."
                    )
                pack = CreditPack(**asdict(fields))
                s.add(pack)
                s.flush()
                audited(
                    s,
                    admin_user_id,
                    AuditAction.CREDIT_PACK_CREATE,
                    AuditTarget.CREDIT_PACK,
                    pack.id,
                    reason,
                    None,
                    snapshot(pack, _CREDIT_PACK_AUDIT),
                )
                return pack
        except IntegrityError as exc:
            raise AdminConflictError(
                "code_taken", f"A pack with code {fields.code} exists."
            ) from exc

    def update_credit_pack(
        self,
        credit_pack_id: uuid.UUID,
        changes: Mapping[str, object],
        *,
        admin_user_id: uuid.UUID,
        reason: str,
    ) -> CreditPack:
        require_reason(reason)
        if set(changes) - set(CREDIT_PACK_MUTABLE):
            raise AdminInvalidError("immutable_field", "code and currency are fixed.")
        with self._sm.begin() as s:
            pack = s.get(CreditPack, credit_pack_id, with_for_update=True)
            if pack is None:
                raise AdminNotFoundError("credit_pack_not_found")
            if pack.code.startswith(SIGNUP_PREFIX):
                raise AdminConflictError(
                    "signup_pack_use_free_allowances", "Edit signup packs through free allowances."
                )
            before = snapshot(pack, _CREDIT_PACK_AUDIT)
            for name, value in changes.items():
                setattr(pack, name, value)
            s.flush()
            audited(
                s,
                admin_user_id,
                AuditAction.CREDIT_PACK_UPDATE,
                AuditTarget.CREDIT_PACK,
                pack.id,
                reason,
                before,
                snapshot(pack, _CREDIT_PACK_AUDIT),
            )
            return pack

    def set_free_allowance(
        self, *, audience: FreeAudience, units: int, admin_user_id: uuid.UUID, reason: str
    ) -> FreeAllowanceView:
        """Set the units of the student free allowance or the teacher signup credits.

        Units alone: the pack stays inactive at price zero, and ``0`` switches the allowance
        off. Phase 04's ``ensure_usage_catalogue`` creates the signup packs on first use, so
        the first edit works on a fresh database too.
        """
        require_reason(reason)
        code = _SIGNUP_CODES[audience]
        with self._sm.begin() as s:
            ensure_usage_catalogue(s, now=self._now())
            pack = s.scalars(
                select(CreditPack).where(CreditPack.code == code).with_for_update()
            ).one()
            before = snapshot(pack, _CREDIT_PACK_AUDIT)
            pack.units = units
            s.flush()
            audited(
                s,
                admin_user_id,
                AuditAction.FREE_ALLOWANCE_UPDATE,
                AuditTarget.CREDIT_PACK,
                pack.id,
                reason,
                before,
                snapshot(pack, _CREDIT_PACK_AUDIT),
            )
            return _free_allowance_view(audience, pack)

    # -- versioned rows ------------------------------------------------------

    def _effective(self, effective_from: datetime | None) -> datetime:
        now = self._now()
        if effective_from is None:
            return now
        if effective_from < now - _BACKDATE_TOLERANCE:
            raise AdminInvalidError(
                "effective_from_in_past", "A new version cannot start in the past."
            )
        return effective_from

    def add_usage_rate(
        self,
        *,
        action: str,
        units_per_usd: int,
        effective_from: datetime | None,
        admin_user_id: uuid.UUID,
        reason: str,
    ) -> UsageRate:
        require_reason(reason)
        _require_metered(action)
        starts = self._effective(effective_from)
        with self._sm.begin() as s:
            lock_idempotency_key(s, f"catalogue-version:usage_rates:{action}")
            latest = s.scalars(
                select(UsageRate)
                .where(UsageRate.action == action)
                .order_by(UsageRate.version.desc())
                .limit(1)
            ).first()
            _require_not_before(latest, starts)
            row = UsageRate(
                version=(latest.version if latest else 0) + 1,
                action=action,
                units_per_usd=units_per_usd,
                effective_from=starts,
            )
            s.add(row)
            s.flush()
            audited(
                s,
                admin_user_id,
                AuditAction.USAGE_RATE_VERSION,
                AuditTarget.USAGE_RATE,
                row.id,
                reason,
                snapshot(latest, _RATE_AUDIT) if latest else None,
                snapshot(row, _RATE_AUDIT),
            )
            return row

    def add_usage_estimator(
        self,
        *,
        action: str,
        input_kind: EstimatorInputKind,
        base_low: int,
        base_high: int,
        per_input_low: int,
        per_input_high: int,
        effective_from: datetime | None,
        admin_user_id: uuid.UUID,
        reason: str,
    ) -> UsageEstimator:
        require_reason(reason)
        _require_metered(action)
        if base_low > base_high or per_input_low > per_input_high:
            raise AdminInvalidError(
                "low_above_high", "Each low bound must not exceed its high bound."
            )
        if input_kind is EstimatorInputKind.none and (per_input_low or per_input_high):
            raise AdminInvalidError("per_input_without_input_kind")
        starts = self._effective(effective_from)
        with self._sm.begin() as s:
            lock_idempotency_key(s, f"catalogue-version:usage_estimators:{action}")
            latest = s.scalars(
                select(UsageEstimator)
                .where(UsageEstimator.action == action)
                .order_by(UsageEstimator.version.desc())
                .limit(1)
            ).first()
            _require_not_before(latest, starts)
            row = UsageEstimator(
                version=(latest.version if latest else 0) + 1,
                action=action,
                input_kind=input_kind,
                base_low=base_low,
                base_high=base_high,
                per_input_low=per_input_low,
                per_input_high=per_input_high,
                effective_from=starts,
            )
            s.add(row)
            s.flush()
            audited(
                s,
                admin_user_id,
                AuditAction.USAGE_ESTIMATOR_VERSION,
                AuditTarget.USAGE_ESTIMATOR,
                row.id,
                reason,
                snapshot(latest, _ESTIMATOR_AUDIT) if latest else None,
                snapshot(row, _ESTIMATOR_AUDIT),
            )
            return row


__all__ = [
    "CREDIT_PACK_MUTABLE",
    "PLAN_TIER_MUTABLE",
    "SIGNUP_PREFIX",
    "AdminBillingError",
    "AdminCatalogueService",
    "AdminConflictError",
    "AdminInvalidError",
    "AdminNotFoundError",
    "AuditAction",
    "AuditTarget",
    "CatalogueSnapshot",
    "CreditPackFields",
    "FreeAllowanceView",
    "PaymobCallError",
    "PlanTierFields",
    "ReasonRequiredError",
    "already_applied",
    "audited",
    "idempotency_lookup",
    "lock_idempotency_key",
    "paymob_drift",
    "require_reason",
    "snapshot",
    "to_jsonable",
]
