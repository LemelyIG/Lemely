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
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

import sqlalchemy as sa
from sqlalchemy import and_, or_, select

from lemely.core.usage_pricing import usd_to_units
from lemely.db.admin_billing_repo import (
    AdminInvalidError,
    AdminNotFoundError,
    AuditTarget,
    PaymentView,
    payment_views,
)
from lemely.db.models.admin_audit import AdminAuditLog
from lemely.db.models.billing import Payment, PlanTier, Subscription, SubscriptionPeriod
from lemely.db.models.team import TeacherMember, TeacherMemberKind
from lemely.db.models.usage import UsageDebt, UsageGrant, UsageGrantBalance, UsageJob, UsageRate
from lemely.db.models.users import ParentChildLink, User

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable
    from decimal import Decimal

    from sqlalchemy.orm import InstrumentedAttribute, Session, sessionmaker

    from lemely.io.paymob.client import PaymobClient
    from lemely.runtime.config import PaymobSettings

#: Closed (expired) grants shown beside every usable one.
_CLOSED_GRANTS = 100
#: Jobs, payments, audit rows and open debts.
_RECENT_ROWS = 50
_PERIODS_PER_SUBSCRIPTION = 6
_SUBSCRIPTIONS = 50
#: ``payments.paymob_order_id`` is a ``BIGINT``: a longer number cannot be an order id.
_MAX_ORDER_ID = 2**63 - 1


MatchedOn = Literal["user_id", "payment_id", "paymob_order", "email", "name"]


#: What Postgres or psycopg refuse in text: NUL, and a lone surrogate (not encodable as UTF-8);
#: the other control characters are never part of an email, a name or an id.
_REFUSED_CHARACTERS = re.compile("[\x00-\x1f\x7f\ud800-\udfff]")


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
    """Search and read one customer; Tasks 6-7 add the audited money actions."""

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


def _parse_uuid(term: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(term)
    except ValueError:
        return None


__all__ = [
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
]
