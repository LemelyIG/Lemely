"""Admin customer view (spec §8 area 2): search, detail, and (Tasks 6-7) money actions.

The detail is the whole money picture of one account, read in one session so the numbers
agree with each other: subscriptions and periods, grants with balances, debt, recent usage
jobs (estimate against actual), payments with refunds, team relationships, linked parents or
children, and the admin actions taken on them.

Every list is bounded (DV-31) so one busy account cannot make the page unbounded.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal

import sqlalchemy as sa
import structlog
from sqlalchemy import and_, or_, select

from lemely.core.usage_pricing import usd_to_units
from lemely.db.admin_billing_repo import (
    AdminConflictError,
    AdminInvalidError,
    AdminNotFoundError,
    AuditAction,
    AuditTarget,
    PaymentView,
    PaymobCallError,
    audited,
    lock_idempotency_key,
    payment_views,
    require_reason,
    snapshot,
)
from lemely.db.billing_notices import enqueue_subscription_notice
from lemely.db.billing_repo import _outcome_unknown
from lemely.db.models.admin_audit import (
    HAS_IDEMPOTENCY_KEY_SQL,
    IDEMPOTENCY_KEY_SQL,
    AdminAuditLog,
)
from lemely.db.models.billing import (
    LIVE_SUBSCRIPTION_STATUSES,
    Payment,
    PlanAudience,
    PlanTier,
    Subscription,
    SubscriptionPeriod,
)
from lemely.db.models.enums import Role, SubscriptionStatus
from lemely.db.models.team import TeacherMember, TeacherMemberKind
from lemely.db.models.usage import (
    GrantKind,
    UsageDebt,
    UsageGrant,
    UsageGrantBalance,
    UsageJob,
    UsageRate,
)
from lemely.db.models.users import ParentChildLink, User
from lemely.db.subscription_repo import InvalidPlanChange, SubscriptionNotFound, SubscriptionService
from lemely.db.usage_ledger_repo import GrantAlreadyExpired, UsageLedger
from lemely.io.paymob.client import PaymobError

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable
    from decimal import Decimal

    from sqlalchemy.orm import InstrumentedAttribute, Session, sessionmaker

    from lemely.io.paymob.client import PaymobClient
    from lemely.runtime.config import PaymobSettings

alerts = structlog.get_logger("lemely.db.admin_customer_repo")

#: Closed (expired) grants shown beside every usable one.
_CLOSED_GRANTS = 100
#: Jobs, payments, audit rows and open debts.
_RECENT_ROWS = 50
_PERIODS_PER_SUBSCRIPTION = 6
_SUBSCRIPTIONS = 50
#: ``payments.paymob_order_id`` is a ``BIGINT``: a longer number cannot be an order id.
_MAX_ORDER_ID = 2**63 - 1
#: An identical forgive by the same admin inside this window is a double click (DV-15).
_FORGIVE_DEDUPE = timedelta(seconds=120)
#: Recent forgive rows read for the dedupe; a window holds a handful at most.
_FORGIVE_LOOKBACK = 50


#: The role each plan audience is sold to. Parents and admins have no audience.
_AUDIENCE_ROLE = {PlanAudience.student: Role.student, PlanAudience.teacher: Role.teacher}
#: The subscription columns an audit row records.
_SUBSCRIPTION_AUDIT = (
    "status",
    "plan_tier_id",
    "payer_user_id",
    "current_period_start",
    "current_period_end",
    "cancel_at_period_end",
    "is_manually_activated",
    "paymob_subscription_id",
    "paymob_cancelled_at",
)
#: Complimentary rows ended per pass of the expiry job (DV-27).
EXPIRY_BATCH = 200

MatchedOn = Literal["user_id", "payment_id", "paymob_order", "email", "name"]


#: What Postgres or psycopg refuse in text: NUL, and a lone surrogate (not encodable as UTF-8);
#: the other control characters are never part of an email, a name or an id.
_REFUSED_CHARACTERS = re.compile("[\x00-\x1f\x7f\ud800-\udfff]")


def _ledger_request_key(request_id: uuid.UUID) -> str:
    """The audit ``idempotency_key`` of a grant or adjust: one id, once, for any customer."""
    return f"admin-ledger:{request_id}"


def _subscription_request_key(request_id: uuid.UUID) -> str:
    """The audit ``idempotency_key`` of an extend or cancel: one request id, once (like grant)."""
    return f"admin-subscription:{request_id}"


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class BalanceView:
    allowance_available: int
    credits_available: int
    seat_available: int
    outstanding_debt: int


def _split_available(rows: Iterable[tuple[bool, uuid.UUID | None, int]]) -> tuple[int, int, int]:
    """``(allowance, credits, seat)`` from ``(visible, teacher_member_id, available)`` rows."""
    allowance = credits = seat = 0
    for visible, member_id, available in rows:
        if member_id is not None:
            seat += available
        elif visible:
            credits += available
        else:
            allowance += available
    return allowance, credits, seat


def _open_debt(session: Session, user_id: uuid.UUID) -> int:
    debt = session.scalar(
        select(sa.func.coalesce(sa.func.sum(UsageDebt.outstanding), 0)).where(
            UsageDebt.owner_user_id == user_id
        )
    )
    return int(debt or 0)


def balance_for(session: Session, user_id: uuid.UUID, *, now: datetime) -> BalanceView:
    """``remaining - held`` over the owner's usable grants, split by kind, plus open debt.

    Allowance is the owner's hidden grants with no seat, credits the visible ones, seat the
    owner's own seat grants. Only grants *owned* by ``user_id`` count, so a teacher is never
    shown the sum of their students' seat grants.
    """
    rows = session.execute(
        select(
            UsageGrant.visible,
            UsageGrant.teacher_member_id,
            UsageGrantBalance.remaining - UsageGrantBalance.held,
        )
        .join(UsageGrantBalance, UsageGrantBalance.grant_id == UsageGrant.id)
        .where(
            UsageGrant.owner_user_id == user_id,
            UsageGrant.effective_at <= now,
            or_(UsageGrant.expires_at.is_(None), UsageGrant.expires_at > now),
        )
    ).all()
    allowance, credits, seat = _split_available((v, m, int(a)) for v, m, a in rows)
    return BalanceView(allowance, credits, seat, _open_debt(session, user_id))


def balance_from_grants(
    session: Session, user_id: uuid.UUID, usable: Iterable[GrantView], *, now: datetime
) -> BalanceView:
    """The same figures as :func:`balance_for`, from grant rows the caller already read.

    Used by the detail so the balance is the sum of the grants listed beside it. Debt is the
    one extra read (the listed debts are bounded, the total is not).
    """
    allowance, credits, seat = _split_available(
        (g.grant.visible, g.grant.teacher_member_id, g.remaining - g.held)
        for g in usable
        if g.grant.effective_at <= now
    )
    return BalanceView(allowance, credits, seat, _open_debt(session, user_id))


@dataclass(frozen=True, slots=True)
class CustomerHit:
    user_id: uuid.UUID
    email: str
    display_name: str | None
    role: str
    matched_on: MatchedOn


@dataclass(frozen=True, slots=True)
class GrantView:
    grant: UsageGrant
    remaining: int
    held: int


@dataclass(frozen=True, slots=True)
class JobView:
    job: UsageJob
    actual_units: int | None

    @property
    def outside_range(self) -> bool:
        return self.actual_units is not None and not (
            self.job.estimate_low <= self.actual_units <= self.job.estimate_high
        )


@dataclass(frozen=True, slots=True)
class SubscriptionView:
    subscription: Subscription
    plan_code: str
    plan_name: str
    periods: list[SubscriptionPeriod]


@dataclass(frozen=True, slots=True)
class MemberView:
    """A ``teacher_members`` row and the person on the other side of it."""

    member: TeacherMember
    other_user_id: uuid.UUID
    other_email: str


@dataclass(frozen=True, slots=True)
class CustomerDetail:
    user: User
    balance: BalanceView
    subscriptions: list[SubscriptionView]
    grants: list[GrantView]
    debts: list[UsageDebt]
    jobs: list[JobView]
    payments: list[PaymentView]
    seats: list[MemberView]
    assistants: list[MemberView]
    seated_with: list[MemberView]
    parents: list[User]
    children: list[User]
    audit: list[AdminAuditLog]


def escape_like(term: str) -> str:
    """``term`` with the ``LIKE`` wildcards and the escape character made literal."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def actual_units(cost_usd: Decimal | None, units_per_usd: int | None) -> int | None:
    """The units a job's actual cost converts to (the ledger's own ``usd_to_units``)."""
    if cost_usd is None or units_per_usd is None or units_per_usd <= 0 or cost_usd < 0:
        return None
    return usd_to_units(cost_usd, units_per_usd)


class AdminCustomerService:
    """Search and read one customer, and take the audited ledger actions on one."""

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

    # -- search ----------------------------------------------------------------

    def search(self, q: str, *, limit: int = 20) -> list[CustomerHit]:
        """Match a user id, a payment id, a Paymob order id, an email or a display name.

        Exact identifiers first, then email, then name; each user appears once, tagged with
        the first thing that matched. A payment id or order id finds both its payer and its
        beneficiary.
        """
        term = q.strip()
        if len(term) < 2:
            raise AdminInvalidError("query_too_short", "Type at least two characters.")
        if _REFUSED_CHARACTERS.search(term):
            raise AdminInvalidError(
                "query_invalid", "The search text has characters that cannot be searched."
            )
        hits: dict[uuid.UUID, CustomerHit] = {}

        def add(users: list[User], matched_on: MatchedOn) -> None:
            for u in users:
                hits.setdefault(
                    u.id, CustomerHit(u.id, u.email, u.display_name, u.role.value, matched_on)
                )

        with self._sm() as s:

            def payment_parties(condition: sa.ColumnElement[bool]) -> list[User]:
                parties = (
                    select(Payment.payer_user_id)
                    .where(condition)
                    .union(select(Payment.beneficiary_user_id).where(condition))
                )
                return list(
                    s.scalars(
                        select(User).where(User.id.in_(parties)).order_by(User.email).limit(limit)
                    )
                )

            as_uuid = _parse_uuid(term)
            if as_uuid is not None:
                add(list(s.scalars(select(User).where(User.id == as_uuid))), "user_id")
                add(
                    payment_parties(
                        or_(Payment.id == as_uuid, Payment.special_reference == str(as_uuid))
                    ),
                    "payment_id",
                )
            # ``isdigit`` alone accepts superscripts and other digits ``int`` rejects.
            if term.isascii() and term.isdigit() and int(term) <= _MAX_ORDER_ID:
                add(payment_parties(Payment.paymob_order_id == int(term)), "paymob_order")
            pattern = f"%{escape_like(term)}%"
            add(
                list(
                    s.scalars(
                        select(User)
                        .where(User.email.ilike(pattern, escape="\\"))
                        .order_by(User.email)
                        .limit(limit)
                    )
                ),
                "email",
            )
            add(
                list(
                    s.scalars(
                        select(User)
                        .where(User.display_name.ilike(pattern, escape="\\"))
                        .order_by(User.display_name, User.email)
                        .limit(limit)
                    )
                ),
                "name",
            )
        return list(hits.values())[:limit]

    # -- detail ----------------------------------------------------------------

    def detail(self, user_id: uuid.UUID) -> CustomerDetail:
        now = self._now()
        with self._sm() as s:
            user = s.get(User, user_id)
            if user is None:
                raise AdminNotFoundError("customer_not_found")

            subs = list(
                s.scalars(
                    select(Subscription)
                    .where(Subscription.user_id == user_id)
                    .order_by(Subscription.created_at.desc(), Subscription.id)
                    .limit(_SUBSCRIPTIONS)
                )
            )
            tiers = {
                t.id: t
                for t in s.scalars(
                    select(PlanTier).where(PlanTier.id.in_({x.plan_tier_id for x in subs}))
                )
            }
            periods: dict[uuid.UUID, list[SubscriptionPeriod]] = {x.id: [] for x in subs}
            newest = (
                sa.func.row_number()
                .over(
                    partition_by=SubscriptionPeriod.subscription_id,
                    order_by=(SubscriptionPeriod.period_start.desc(), SubscriptionPeriod.id),
                )
                .label("rank")
            )
            ranked = (
                select(SubscriptionPeriod.id, newest)
                .where(SubscriptionPeriod.subscription_id.in_(list(periods)))
                .subquery()
            )
            for period in s.scalars(
                select(SubscriptionPeriod)
                .join(ranked, ranked.c.id == SubscriptionPeriod.id)
                .where(ranked.c.rank <= _PERIODS_PER_SUBSCRIPTION)
                .order_by(SubscriptionPeriod.period_start.desc(), SubscriptionPeriod.id)
            ):
                periods[period.subscription_id].append(period)

            grant_rows = select(
                UsageGrant, UsageGrantBalance.remaining, UsageGrantBalance.held
            ).join(UsageGrantBalance, UsageGrantBalance.grant_id == UsageGrant.id)
            usable = s.execute(
                grant_rows.where(
                    UsageGrant.owner_user_id == user_id,
                    or_(UsageGrant.expires_at.is_(None), UsageGrant.expires_at > now),
                ).order_by(
                    UsageGrant.expires_at.asc().nulls_last(), UsageGrant.created_at, UsageGrant.id
                )
            ).all()
            closed = s.execute(
                grant_rows.where(
                    UsageGrant.owner_user_id == user_id,
                    UsageGrant.expires_at <= now,
                )
                .order_by(UsageGrant.expires_at.desc(), UsageGrant.id)
                .limit(_CLOSED_GRANTS)
            ).all()
            usable_views = [GrantView(g, int(r), int(h)) for g, r, h in usable]
            grants = [*usable_views, *(GrantView(g, int(r), int(h)) for g, r, h in closed)]
            debts = list(
                s.scalars(
                    select(UsageDebt)
                    .where(UsageDebt.owner_user_id == user_id, UsageDebt.outstanding > 0)
                    .order_by(UsageDebt.created_at, UsageDebt.id)
                    .limit(_RECENT_ROWS)
                )
            )
            jobs = [
                JobView(job, actual_units(job.actual_cost_usd, rate))
                for job, rate in s.execute(
                    select(UsageJob, UsageRate.units_per_usd)
                    .outerjoin(
                        UsageRate,
                        and_(
                            UsageRate.version == UsageJob.rate_version,
                            UsageRate.action == UsageJob.action,
                        ),
                    )
                    .where(UsageJob.actor_user_id == user_id)
                    .order_by(UsageJob.created_at.desc(), UsageJob.id)
                    .limit(_RECENT_ROWS)
                )
            ]
            own_payment = or_(
                Payment.payer_user_id == user_id, Payment.beneficiary_user_id == user_id
            )
            payments = payment_views(
                s,
                list(
                    s.scalars(
                        select(Payment)
                        .where(own_payment)
                        .order_by(Payment.created_at.desc(), Payment.id)
                        .limit(_RECENT_ROWS)
                    )
                ),
            )

            def members(
                mine: sa.ColumnElement[bool], other: InstrumentedAttribute[uuid.UUID]
            ) -> list[MemberView]:
                return [
                    MemberView(m, uid, email)
                    for m, uid, email in s.execute(
                        select(TeacherMember, User.id, User.email)
                        .join(User, User.id == other)
                        .where(mine)
                        .order_by(TeacherMember.created_at, TeacherMember.id)
                    )
                ]

            seats = members(
                and_(
                    TeacherMember.teacher_user_id == user_id,
                    TeacherMember.kind == TeacherMemberKind.student_seat,
                ),
                TeacherMember.member_user_id,
            )
            assistants = members(
                and_(
                    TeacherMember.teacher_user_id == user_id,
                    TeacherMember.kind == TeacherMemberKind.assistant,
                ),
                TeacherMember.member_user_id,
            )
            seated_with = members(
                and_(
                    TeacherMember.member_user_id == user_id,
                    TeacherMember.kind == TeacherMemberKind.student_seat,
                ),
                TeacherMember.teacher_user_id,
            )
            parents = list(
                s.scalars(
                    select(User)
                    .join(ParentChildLink, ParentChildLink.parent_id == User.id)
                    .where(ParentChildLink.child_id == user_id)
                    .order_by(User.email)
                )
            )
            children = list(
                s.scalars(
                    select(User)
                    .join(ParentChildLink, ParentChildLink.child_id == User.id)
                    .where(ParentChildLink.parent_id == user_id)
                    .order_by(User.email)
                )
            )
            # Admin actions on the user, on any of their subscriptions and on any of their
            # payments (every payment, not only the 50 listed). Scoped by kind so the
            # (target_kind, target_id) index applies and an id can never match across kinds.
            own_subscriptions = select(Subscription.id).where(Subscription.user_id == user_id)
            own_payments = select(Payment.id).where(own_payment)
            audit = list(
                s.scalars(
                    select(AdminAuditLog)
                    .where(
                        or_(
                            and_(
                                AdminAuditLog.target_kind == AuditTarget.USER.value,
                                AdminAuditLog.target_id == user_id,
                            ),
                            and_(
                                AdminAuditLog.target_kind == AuditTarget.SUBSCRIPTION.value,
                                AdminAuditLog.target_id.in_(own_subscriptions),
                            ),
                            and_(
                                AdminAuditLog.target_kind == AuditTarget.PAYMENT.value,
                                AdminAuditLog.target_id.in_(own_payments),
                            ),
                        )
                    )
                    .order_by(AdminAuditLog.created_at.desc(), AdminAuditLog.id)
                    .limit(_RECENT_ROWS)
                )
            )
            return CustomerDetail(
                user=user,
                balance=balance_from_grants(s, user_id, usable_views, now=now),
                subscriptions=[
                    SubscriptionView(
                        x, tiers[x.plan_tier_id].code, tiers[x.plan_tier_id].name, periods[x.id]
                    )
                    for x in subs
                ],
                grants=grants,
                debts=debts,
                jobs=jobs,
                payments=payments,
                seats=seats,
                assistants=assistants,
                seated_with=seated_with,
                parents=parents,
                children=children,
                audit=audit,
            )

    # -- ledger actions (Task 6) -----------------------------------------------

    @staticmethod
    def _require_user(s: Session, user_id: uuid.UUID) -> None:
        if s.get(User, user_id) is None:
            raise AdminNotFoundError("customer_not_found")

    @staticmethod
    def _prior_request(s: Session, request_id: uuid.UUID) -> AdminAuditLog | None:
        """The ledger action an earlier call with this ``request_id`` wrote, for any customer.

        Grant and adjust both store ``admin-ledger:{request_id}`` as the audit
        ``idempotency_key``, so the unique partial index serves the lookup, one probe per
        action (the index is per action). One request id is single-use across both (DV-14).
        """
        for action in (AuditAction.CUSTOMER_GRANT, AuditAction.CUSTOMER_ADJUST):
            row = s.scalars(
                select(AdminAuditLog)
                .where(
                    AdminAuditLog.action == str(action),
                    sa.text(HAS_IDEMPOTENCY_KEY_SQL),
                    sa.literal_column(IDEMPOTENCY_KEY_SQL) == _ledger_request_key(request_id),
                )
                .limit(1)
            ).first()
            if row is not None:
                return row
        return None

    @staticmethod
    def _same_request(
        prior: AdminAuditLog,
        action: AuditAction,
        user_id: uuid.UUID,
        payload: dict[str, object],
    ) -> bool:
        """True when ``prior`` is this very request; other action, target or payload is a reuse."""
        after = prior.after or {}
        return (
            prior.action == str(action)
            and prior.target_id == user_id
            and all(after.get(k) == v for k, v in payload.items())
        )

    def grant_credits(
        self,
        user_id: uuid.UUID,
        *,
        units: int,
        valid_days: int | None,
        request_id: uuid.UUID,
        admin_user_id: uuid.UUID,
        reason: str,
    ) -> CustomerDetail:
        """Issue visible ``adjustment`` credits; the ledger repays debt first (spec §5.8).

        ``valid_days=None`` never expires (DV-30). The ledger key is
        ``admin-grant:{user_id}:{request_id}`` (DV-14). A replay of the same request changes
        nothing; the same ``request_id`` with another customer, ``units`` or ``valid_days`` is
        ``request_id_reused``.
        """
        require_reason(reason)
        key = f"admin-grant:{user_id}:{request_id}"
        payload: dict[str, object] = {"units": units, "valid_days": valid_days}
        now = self._now()
        with self._sm.begin() as s:
            self._require_user(s, user_id)
            lock_idempotency_key(s, _ledger_request_key(request_id))
            UsageLedger.lock_owner(s, user_id)
            prior = self._prior_request(s, request_id)
            if prior is not None:
                if not self._same_request(prior, AuditAction.CUSTOMER_GRANT, user_id, payload):
                    raise AdminConflictError(
                        "request_id_reused", "This request id was used for a different grant."
                    )
            else:
                before = asdict(balance_for(s, user_id, now=now))
                issued = UsageLedger(s).issue_grant(
                    owner_user_id=user_id,
                    kind=GrantKind.adjustment,
                    units=units,
                    idempotency_key=key,
                    expires_at=None if valid_days is None else now + timedelta(days=valid_days),
                    visible=True,
                    effective_at=now,
                )
                audited(
                    s,
                    admin_user_id,
                    AuditAction.CUSTOMER_GRANT,
                    AuditTarget.USER,
                    user_id,
                    reason,
                    before,
                    {
                        **asdict(balance_for(s, user_id, now=now)),
                        **payload,
                        "grant_id": issued.id,
                        "expires_at": issued.expires_at,
                        "idempotency_key": _ledger_request_key(request_id),
                        "request_id": request_id,
                        "user_id": user_id,
                    },
                )
        return self.detail(user_id)

    def adjust(
        self,
        user_id: uuid.UUID,
        *,
        units: int,
        request_id: uuid.UUID,
        admin_user_id: uuid.UUID,
        reason: str,
    ) -> CustomerDetail:
        """Add (positive) or debit (negative) units; a shortfall becomes debt (Phase 01).

        Keys and replays work as for :meth:`grant_credits`, with ``admin-adjust:``.
        """
        require_reason(reason)
        if units == 0:
            raise AdminInvalidError("zero_adjustment", "An adjustment must change the balance.")
        key = f"admin-adjust:{user_id}:{request_id}"
        payload: dict[str, object] = {"units": units}
        now = self._now()
        with self._sm.begin() as s:
            self._require_user(s, user_id)
            lock_idempotency_key(s, _ledger_request_key(request_id))
            UsageLedger.lock_owner(s, user_id)
            prior = self._prior_request(s, request_id)
            if prior is not None:
                if not self._same_request(prior, AuditAction.CUSTOMER_ADJUST, user_id, payload):
                    raise AdminConflictError(
                        "request_id_reused", "This request id was used for a different adjustment."
                    )
            else:
                before = asdict(balance_for(s, user_id, now=now))
                UsageLedger(s).adjust(
                    owner_user_id=user_id,
                    units=units,
                    reason=reason.strip(),
                    idempotency_key=key,
                    now=now,
                )
                audited(
                    s,
                    admin_user_id,
                    AuditAction.CUSTOMER_ADJUST,
                    AuditTarget.USER,
                    user_id,
                    reason,
                    before,
                    {
                        **asdict(balance_for(s, user_id, now=now)),
                        **payload,
                        "idempotency_key": _ledger_request_key(request_id),
                        "request_id": request_id,
                        "user_id": user_id,
                    },
                )
        return self.detail(user_id)

    def forgive_debt(
        self, user_id: uuid.UUID, *, units: int | None, admin_user_id: uuid.UUID, reason: str
    ) -> CustomerDetail:
        """Forgive ``units`` of outstanding debt, or all of it when ``units`` is None.

        The ledger call has no key, so the dedupe is ours (DV-15): under the advisory lock
        ``admin-forgive:{user_id}``, an identical forgive by the same admin (same
        ``requested_units`` and reason) in the last 120 s is a no-op that returns the detail.
        The lock key is never stored in ``idempotency_key``: that index is unique per action,
        so a second forgive after the window would fail. The row records ``forgiven_at``.
        """
        require_reason(reason)
        cleaned = reason.strip()
        now = self._now()
        with self._sm.begin() as s:
            self._require_user(s, user_id)
            lock_idempotency_key(s, f"admin-forgive:{user_id}")
            UsageLedger.lock_owner(s, user_id)
            if not self._forgiven_recently(s, user_id, admin_user_id, units, cleaned, now):
                self._forgive(s, user_id, admin_user_id, units, cleaned, now)
        return self.detail(user_id)

    @staticmethod
    def _forgive(
        s: Session,
        user_id: uuid.UUID,
        admin_user_id: uuid.UUID,
        units: int | None,
        cleaned: str,
        now: datetime,
    ) -> None:
        before = asdict(balance_for(s, user_id, now=now))
        forgiven = UsageLedger(s).forgive_debt(user_id, units=units, reason=cleaned, now=now)
        if forgiven == 0:
            raise AdminConflictError("no_outstanding_debt", "This account owes nothing.")
        audited(
            s,
            admin_user_id,
            AuditAction.CUSTOMER_FORGIVE_DEBT,
            AuditTarget.USER,
            user_id,
            cleaned,
            before,
            {
                **asdict(balance_for(s, user_id, now=now)),
                "forgiven_units": forgiven,
                "requested_units": units,
                "forgiven_at": now,
            },
        )

    @staticmethod
    def _forgiven_recently(
        s: Session,
        user_id: uuid.UUID,
        admin_user_id: uuid.UUID,
        units: int | None,
        reason: str,
        now: datetime,
    ) -> bool:
        recent = s.scalars(
            select(AdminAuditLog)
            .where(
                AdminAuditLog.action == str(AuditAction.CUSTOMER_FORGIVE_DEBT),
                AdminAuditLog.target_id == user_id,
                AdminAuditLog.admin_user_id == admin_user_id,
            )
            .order_by(AdminAuditLog.created_at.desc())
            .limit(_FORGIVE_LOOKBACK)
        )
        for row in recent:
            after = row.after or {}
            at = after.get("forgiven_at")
            if (
                isinstance(at, str)
                and row.reason == reason
                and after.get("requested_units") == units
                and now - datetime.fromisoformat(at) < _FORGIVE_DEDUPE
            ):
                return True
        return False

    # -- subscription actions (Task 7) -------------------------------------------

    def manual_activation(
        self,
        user_id: uuid.UUID,
        *,
        plan_tier_id: uuid.UUID,
        period_days: int,
        admin_user_id: uuid.UUID,
        reason: str,
    ) -> CustomerDetail:
        """Create a live complimentary subscription with its period and allowance grant.

        Complimentary means no payer (DV-16): ``payer_user_id`` is NULL, so the partial unique
        index of live paid plans does not cover it. The one-live-plan rule rests on the per-user
        row lock ``decide_activation`` takes too, and the check below reads every live plan of
        the user, whoever pays. No payment and no Paymob subscription:
        :func:`expire_manual_subscriptions` ends it. Lock order: user row, then the ledger
        owner lock inside ``issue_grant``.
        """
        require_reason(reason)
        now = self._now()
        with self._sm.begin() as s:
            locked = s.execute(
                select(User.id, User.role).where(User.id == user_id).with_for_update(key_share=True)
            ).one_or_none()
            if locked is None:
                raise AdminNotFoundError("customer_not_found")
            tier = s.get(PlanTier, plan_tier_id)
            if tier is None:
                raise AdminNotFoundError("plan_tier_not_found")
            if not tier.is_active or tier.price_minor <= 0:
                raise AdminInvalidError(
                    "plan_not_activatable", "Only an active, priced plan can be activated."
                )
            if _AUDIENCE_ROLE.get(tier.audience) is not locked.role:
                raise AdminInvalidError("audience_mismatch", "That plan is for another role.")
            live = s.scalar(
                select(Subscription.id)
                .where(
                    Subscription.user_id == user_id,
                    Subscription.status.in_(LIVE_SUBSCRIPTION_STATUSES),
                )
                .limit(1)
            )
            if live is not None:
                raise AdminConflictError("live_subscription_exists", "Cancel the live plan first.")
            end = now + timedelta(days=period_days)
            sub = Subscription(
                user_id=user_id,
                payer_user_id=None,
                plan_tier_id=tier.id,
                terms_version=tier.terms_version,
                status=SubscriptionStatus.active,
                is_manually_activated=True,
                activated_at=now,
                activation_note=reason.strip(),
                current_period_start=now,
                current_period_end=end,
            )
            s.add(sub)
            s.flush()
            period = SubscriptionPeriod(subscription_id=sub.id, period_start=now, period_end=end)
            s.add(period)
            s.flush()
            grant_id: uuid.UUID | None = None
            if tier.allowance_units > 0:
                grant_id = (
                    UsageLedger(s)
                    .issue_grant(
                        owner_user_id=user_id,
                        kind=GrantKind.period_allowance,
                        units=tier.allowance_units,
                        idempotency_key=f"admin-activation:{sub.id}",
                        expires_at=end,
                        visible=False,
                        effective_at=now,
                        subscription_period_id=period.id,
                    )
                    .id
                )
            audited(
                s,
                admin_user_id,
                AuditAction.SUBSCRIPTION_MANUAL_ACTIVATION,
                AuditTarget.SUBSCRIPTION,
                sub.id,
                reason,
                None,
                {**snapshot(sub, _SUBSCRIPTION_AUDIT), "allowance_grant_id": grant_id},
            )
        return self.detail(user_id)

    def extend_subscription(
        self,
        subscription_id: uuid.UUID,
        *,
        days: int,
        admin_user_id: uuid.UUID,
        reason: str,
        request_id: uuid.UUID | None = None,
    ) -> CustomerDetail:
        """Push a complimentary plan's period end, and its allowance expiry, out by ``days``.

        Only a live complimentary plan extends: Paymob owns the date of a billed one. The
        allowance moves through ``UsageLedger.extend_grant_expiry`` (never a direct write), so a
        grant already lapsed but not yet swept is still extended. With a ``request_id`` a replay
        of the same request changes nothing and the same id for another request is 409
        ``request_id_reused``.
        """
        require_reason(reason)
        now = self._now()
        with self._sm.begin() as s:
            sub = s.get(Subscription, subscription_id, with_for_update=True)
            if sub is None:
                raise AdminNotFoundError("subscription_not_found")
            if self._replayed(
                s, request_id, AuditAction.SUBSCRIPTION_EXTEND, subscription_id, {"days": days}
            ):
                user_id = sub.user_id
            else:
                if sub.paymob_subscription_id is not None:
                    raise AdminConflictError(
                        "paymob_billed", "Grant credits instead; Paymob owns the date."
                    )
                if not sub.is_manually_activated or sub.status is not SubscriptionStatus.active:
                    raise AdminConflictError(
                        "not_extendable", "Only live complimentary plans extend."
                    )
                if sub.current_period_end is None:
                    raise AdminConflictError("open_ended", "This plan has no end to extend.")
                new_end = sub.current_period_end + timedelta(days=days)
                if new_end <= now:
                    raise AdminInvalidError(
                        "extension_in_the_past", "The new end would still be in the past."
                    )
                before = snapshot(sub, _SUBSCRIPTION_AUDIT)
                sub.current_period_end = new_end
                latest = self._latest_period(s, sub.id)
                extended: list[uuid.UUID] = []
                if latest is not None:
                    latest.period_end = new_end
                    ledger = UsageLedger(s)
                    for grant in self._period_grants(s, latest.id):
                        try:
                            ledger.extend_grant_expiry(
                                grant.id,
                                expires_at=new_end,
                                now=now,
                                issued_expires_at=grant.expires_at,
                            )
                        except GrantAlreadyExpired as exc:
                            raise AdminConflictError(
                                "grant_expired",
                                "The allowance already expired; grant credits instead.",
                            ) from exc
                        extended.append(grant.id)
                s.flush()
                audited(
                    s,
                    admin_user_id,
                    AuditAction.SUBSCRIPTION_EXTEND,
                    AuditTarget.SUBSCRIPTION,
                    sub.id,
                    reason,
                    before,
                    {
                        **snapshot(sub, _SUBSCRIPTION_AUDIT),
                        "days": days,
                        "extended_grant_ids": extended,
                        **self._request_fields(request_id),
                    },
                )
                user_id = sub.user_id
        return self.detail(user_id)

    @staticmethod
    def _request_fields(request_id: uuid.UUID | None) -> dict[str, object]:
        if request_id is None:
            return {}
        return {"idempotency_key": _subscription_request_key(request_id), "request_id": request_id}

    @staticmethod
    def _replayed(
        s: Session,
        request_id: uuid.UUID | None,
        action: AuditAction,
        subscription_id: uuid.UUID,
        payload: dict[str, object],
    ) -> bool:
        """True when this very request was already applied; another request's id is a 409.

        Takes the request's advisory lock first, so two identical requests serialise on it and
        the second finds the first's audit row. One probe per action: the unique partial index
        on the key is per action. The id is single-use across extend and cancel.
        """
        if request_id is None:
            return False
        key = _subscription_request_key(request_id)
        lock_idempotency_key(s, key)
        for candidate in (AuditAction.SUBSCRIPTION_EXTEND, AuditAction.SUBSCRIPTION_CANCEL):
            prior = s.scalars(
                select(AdminAuditLog)
                .where(
                    AdminAuditLog.action == str(candidate),
                    sa.text(HAS_IDEMPOTENCY_KEY_SQL),
                    sa.literal_column(IDEMPOTENCY_KEY_SQL) == key,
                )
                .limit(1)
            ).first()
            if prior is None:
                continue
            after = prior.after or {}
            if (
                prior.action == str(action)
                and prior.target_id == subscription_id
                and all(after.get(k) == v for k, v in payload.items())
            ):
                return True
            raise AdminConflictError(
                "request_id_reused", "This request id was used for a different request."
            )
        return False

    def cancel_subscription(
        self,
        subscription_id: uuid.UUID,
        *,
        when: Literal["period_end", "now"],
        admin_user_id: uuid.UUID,
        reason: str,
        request_id: uuid.UUID | None = None,
    ) -> CustomerDetail:
        """Cancel a live plan at its period end, or now.

        A complimentary plan is ours alone: ``period_end`` sets ``cancel_at_period_end`` for
        :func:`expire_manual_subscriptions`, ``now`` ends it and cuts the current period's
        allowance (UD-2). A Paymob-billed plan cancels at period end through Phase 05's
        ``schedule_cancel_as_system`` (the sweep tells Paymob; the admin is in the audit row),
        and ``now`` cancels at Paymob first with no transaction open
        (:meth:`_cancel_at_paymob_now`). A ``period_end`` that changes nothing (already
        scheduled) writes no audit row. With a ``request_id`` a replay changes nothing.
        """
        require_reason(reason)
        now = self._now()
        payload: dict[str, object] = {"when": when}
        with self._sm.begin() as s:  # a short read, closed before any Paymob call
            sub = s.get(Subscription, subscription_id)
            if sub is None:
                raise AdminNotFoundError("subscription_not_found")
            if self._replayed(
                s, request_id, AuditAction.SUBSCRIPTION_CANCEL, subscription_id, payload
            ):
                return self.detail(sub.user_id)
            if sub.status not in LIVE_SUBSCRIPTION_STATUSES:
                raise AdminConflictError("not_live", "Only a live plan can be cancelled.")
            paymob_id = sub.paymob_subscription_id
        if paymob_id is not None and when == "now":
            return self._cancel_at_paymob_now(
                subscription_id,
                paymob_id,
                admin_user_id=admin_user_id,
                reason=reason,
                now=now,
                request_id=request_id,
            )
        with self._sm.begin() as s:
            sub = s.get(Subscription, subscription_id, with_for_update=True)
            if sub is None:
                raise AdminNotFoundError("subscription_not_found")
            user_id = sub.user_id
            if self._replayed(
                s, request_id, AuditAction.SUBSCRIPTION_CANCEL, subscription_id, payload
            ):
                pass
            else:
                self._cancel_locked(
                    s,
                    sub,
                    when=when,
                    paymob_id=paymob_id,
                    admin_user_id=admin_user_id,
                    reason=reason,
                    now=now,
                    request_id=request_id,
                )
        return self.detail(user_id)

    def _cancel_locked(
        self,
        s: Session,
        sub: Subscription,
        *,
        when: Literal["period_end", "now"],
        paymob_id: int | None,
        admin_user_id: uuid.UUID,
        reason: str,
        now: datetime,
        request_id: uuid.UUID | None,
    ) -> None:
        """The local cancel (complimentary, or a Paymob plan at period end) under the row lock."""
        if sub.status not in LIVE_SUBSCRIPTION_STATUSES:
            raise AdminConflictError("not_live", "Only a live plan can be cancelled.")
        if (sub.paymob_subscription_id is None) != (paymob_id is None):
            raise AdminConflictError(
                "subscription_changed", "The plan changed while you were looking; reload it."
            )
        before = snapshot(sub, _SUBSCRIPTION_AUDIT)
        marks = (sub.cancel_at_period_end, sub.pending_plan_tier_id, sub.suspended_at)
        extra: dict[str, object] = {"when": when}
        if paymob_id is not None:
            self._schedule_paymob_cancel(s, sub, now)
        elif when == "now":
            sub.status = SubscriptionStatus.cancelled
            sub.cancel_at_period_end = False
            sub.current_period_end = now
            self._end_plan(s, sub, now)
            extra.update(self._end_period_allowance(s, sub.id, now))
        else:
            sub.cancel_at_period_end = True
        s.flush()
        if when == "period_end" and marks == (
            sub.cancel_at_period_end,
            sub.pending_plan_tier_id,
            sub.suspended_at,
        ):
            return  # already scheduled: nothing changed, so nothing to audit
        audited(
            s,
            admin_user_id,
            AuditAction.SUBSCRIPTION_CANCEL,
            AuditTarget.SUBSCRIPTION,
            sub.id,
            reason,
            before,
            {**snapshot(sub, _SUBSCRIPTION_AUDIT), **extra, **self._request_fields(request_id)},
        )

    @staticmethod
    def _end_plan(s: Session, sub: Subscription, now: datetime) -> None:
        """What Phase 05 does when a plan ends: clear its working markers, tell the payer.

        ``grace_until``, ``suspended_at`` and the amount marks mean nothing on an ended row, and
        a resume or a drift check must find none. The ``cancelled`` notice goes to the payer
        (none for a complimentary plan, which has no payer).
        """
        sub.grace_until = None
        sub.suspended_at = None
        sub.previous_amount_minor = None
        sub.amount_replaced_at = None
        sub.amount_sync_uncertain_at = None
        if sa.inspect(Subscription).version_id_col is None:
            sub.version = (sub.version or 0) + 1
        enqueue_subscription_notice(s, subscription=sub, notice="cancelled", effective_at=now)

    def _schedule_paymob_cancel(self, s: Session, sub: Subscription, now: datetime) -> None:
        """Phase 05's period-end cancel on the platform's behalf; the audit row names the admin."""
        try:
            SubscriptionService(s, self._client, self._settings).schedule_cancel_as_system(
                sub.id, now=now
            )
        except (InvalidPlanChange, SubscriptionNotFound) as exc:
            raise AdminConflictError("not_live", "There is no live card plan to cancel.") from exc

    def _cancel_at_paymob_now(
        self,
        subscription_id: uuid.UUID,
        paymob_id: int,
        *,
        admin_user_id: uuid.UUID,
        reason: str,
        now: datetime,
        request_id: uuid.UUID | None,
    ) -> CustomerDetail:
        """Cancel at Paymob with no transaction open, then end the row under its lock.

        Nothing is written when Paymob did not definitely cancel (:meth:`_paymob_cancel`). When
        it did but the row stopped being live meanwhile (a webhook, the sweep), the cancel is
        recorded on the row (``paymob_cancelled_at``) and in an audit row, and the answer is
        409 ``not_live``.
        """
        gone = self._paymob_cancel(subscription_id, paymob_id)
        stale = False
        with self._sm.begin() as s:
            sub = s.get(Subscription, subscription_id, with_for_update=True)
            if sub is None:
                raise AdminNotFoundError("subscription_not_found")
            user_id = sub.user_id
            payload: dict[str, object] = {"when": "now"}
            if self._replayed(
                s, request_id, AuditAction.SUBSCRIPTION_CANCEL, subscription_id, payload
            ):
                return self.detail(user_id)
            before = snapshot(sub, _SUBSCRIPTION_AUDIT)
            fields: dict[str, object] = {"when": "now", "paymob_cancelled": True}
            if gone:
                fields["paymob_missing"] = True
            if sub.status not in LIVE_SUBSCRIPTION_STATUSES:
                if sub.paymob_cancelled_at is None:
                    sub.paymob_cancelled_at = now
                stale = True
                fields["row_changed_meanwhile"] = True
            else:
                sub.status = SubscriptionStatus.cancelled
                sub.cancel_at_period_end = False
                sub.current_period_end = now
                sub.paymob_cancelled_at = now
                self._end_plan(s, sub, now)
                fields.update(self._end_period_allowance(s, sub.id, now))
                fields.update(self._request_fields(request_id))
            s.flush()
            audited(
                s,
                admin_user_id,
                AuditAction.SUBSCRIPTION_CANCEL,
                AuditTarget.SUBSCRIPTION,
                sub.id,
                reason,
                before,
                {**snapshot(sub, _SUBSCRIPTION_AUDIT), **fields},
            )
        if stale:
            raise AdminConflictError(
                "not_live", "The plan ended while Paymob was cancelling it; Paymob is cancelled."
            )
        return self.detail(user_id)

    def _paymob_cancel(self, subscription_id: uuid.UUID, paymob_id: int) -> bool:
        """Cancel at Paymob; return only when the subscription is known to be cancelled there.

        ``True`` means Paymob no longer has the subscription (404 on the cancel and on the
        read-back, as Phase 05 treats it): the row ends and ``subscription_paymob_missing`` is
        alerted. A 5xx, no answer or a timeout may have cancelled it (``_outcome_unknown``), so
        it is refused as unknown with no read-back and no blind retry: the admin refreshes and
        decides. A definite 4xx is read back, and only ``canceled`` counts as done.
        """
        try:
            self._client.cancel_subscription(paymob_id)
            return False
        except PaymobError as exc:
            self._log_cancel_failure(subscription_id, exc)
            if _outcome_unknown(exc):
                raise PaymobCallError(
                    "paymob_cancel_failed",
                    "Paymob did not confirm the cancel. Nothing was changed; check Paymob first.",
                ) from exc
            cancel_status = exc.status_code
        try:
            remote = self._client.get_subscription(paymob_id)
        except PaymobError as exc:
            self._log_cancel_failure(subscription_id, exc)
            if cancel_status == 404 and exc.status_code == 404:
                alerts.error(
                    "subscription_paymob_missing",
                    subscription_id=str(subscription_id),
                    paymob_subscription_id=paymob_id,
                    alert=True,
                )
                return True
            raise PaymobCallError(
                "paymob_cancel_failed", "Paymob refused the cancel. Nothing was changed."
            ) from exc
        if remote.get("state") != "canceled":
            raise PaymobCallError(
                "paymob_cancel_failed", "Paymob refused the cancel. Nothing was changed."
            )
        return False

    @staticmethod
    def _log_cancel_failure(subscription_id: uuid.UUID, exc: PaymobError) -> None:
        alerts.warning(
            "admin_paymob_cancel_failed",
            subscription_id=str(subscription_id),
            status_code=exc.status_code,
            error_type=type(exc).__name__,
        )

    @staticmethod
    def _latest_period(s: Session, subscription_id: uuid.UUID) -> SubscriptionPeriod | None:
        return s.scalars(
            select(SubscriptionPeriod)
            .where(SubscriptionPeriod.subscription_id == subscription_id)
            .order_by(SubscriptionPeriod.period_start.desc())
            .limit(1)
        ).first()

    @staticmethod
    def _period_grants(s: Session, period_id: uuid.UUID) -> list[UsageGrant]:
        """The grants a period issued, by ascending owner: ledger owner locks go in that order."""
        return list(
            s.scalars(
                select(UsageGrant)
                .where(UsageGrant.subscription_period_id == period_id)
                .order_by(UsageGrant.owner_user_id, UsageGrant.id)
            )
        )

    def _end_period_allowance(
        self, s: Session, subscription_id: uuid.UUID, now: datetime
    ) -> dict[str, object]:
        """UD-2: end the current period's grants now; the next expiry sweep takes the unspent part.

        ``shorten_grant_expiry`` makes the leftover unusable at once and leaves the units for
        ``expire_grants`` (no claw-back entry, no balance change here). Returns the audit fields.
        """
        period = self._latest_period(s, subscription_id)
        grants = [] if period is None else self._period_grants(s, period.id)
        ledger = UsageLedger(s)
        unspent = 0
        for grant in grants:
            balance = s.get(UsageGrantBalance, grant.id)
            if balance is not None:
                unspent += max(balance.remaining - balance.held, 0)
            ledger.shorten_grant_expiry(grant.id, expires_at=now)
        return {
            "ended_grant_ids": [g.id for g in grants],
            "unspent_allowance_units": unspent,
            "allowance_ends": "next_expiry_sweep",
        }


def _complimentary_due(now: datetime) -> list[sa.ColumnElement[bool]]:
    """What makes a row one the expiry job ends (admin-created, active, period over)."""
    return [
        Subscription.payer_user_id.is_(None),
        Subscription.paymob_subscription_id.is_(None),
        Subscription.is_manually_activated.is_(True),
        Subscription.status == SubscriptionStatus.active,
        Subscription.current_period_end.is_not(None),
        Subscription.current_period_end <= now,
    ]


def _expire_manual_row(
    factory: sessionmaker[Session], subscription_id: uuid.UUID, now: datetime
) -> bool:
    """End one complimentary row in its own transaction; ``False`` when another holds it."""
    with factory.begin() as session:
        sub = session.scalars(
            select(Subscription)
            .where(Subscription.id == subscription_id, *_complimentary_due(now))
            .with_for_update(skip_locked=True)
        ).one_or_none()
        if sub is None:
            return False
        sub.status = (
            SubscriptionStatus.cancelled if sub.cancel_at_period_end else SubscriptionStatus.expired
        )
        return True


def expire_manual_subscriptions(
    factory: sessionmaker[Session], *, now: datetime, limit: int = EXPIRY_BATCH
) -> int:
    """End complimentary subscriptions whose period has run out (sweeper job, DV-27).

    Only admin-created ones: no payer, no Paymob subscription, manually activated, active, and a
    period end that has passed (a legacy manual row has none and runs until an admin cancels it).
    ``cancel_at_period_end`` ends as ``cancelled``, otherwise ``expired``. At most ``limit`` rows,
    oldest period end first, each in its own transaction under ``FOR UPDATE SKIP LOCKED``: a
    held row waits for the next pass and a failing row alerts (``admin_manual_expiry_failed``)
    without stopping the rest. The allowance itself ends through the ledger's own expiry sweep.
    """
    if limit < 1:
        raise ValueError("limit must be at least 1")
    with factory() as session:
        ids = list(
            session.scalars(
                select(Subscription.id)
                .where(*_complimentary_due(now))
                .order_by(Subscription.current_period_end, Subscription.id)
                .limit(limit)
            )
        )
    ended = 0
    for subscription_id in ids:
        try:
            if _expire_manual_row(factory, subscription_id, now):
                ended += 1
        except Exception as exc:
            alerts.error(
                "admin_manual_expiry_failed",
                alert=True,
                subscription_id=str(subscription_id),
                error_type=type(exc).__name__,
            )
    return ended


def _parse_uuid(term: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(term)
    except ValueError:
        return None


__all__ = [
    "EXPIRY_BATCH",
    "AdminCustomerService",
    "BalanceView",
    "CustomerDetail",
    "CustomerHit",
    "GrantView",
    "JobView",
    "MatchedOn",
    "MemberView",
    "SubscriptionView",
    "actual_units",
    "balance_for",
    "balance_from_grants",
    "escape_like",
    "expire_manual_subscriptions",
]
