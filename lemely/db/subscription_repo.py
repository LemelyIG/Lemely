"""Subscriptions on Paymob: checkout, first payment, renewal, grace, plan changes, drift.

Paymob billing spec §2.6, §4.3, §5.1-§5.3, §6 (Phase 05). This module holds the plan sync and
the service shell; later tasks add the lifecycle to :class:`SubscriptionService`.

* Paymob's subscriptions module charges renewals (spec §3 approach Y). Lemely never trusts a
  subscription webhook's body: the HMAC covers only ``trigger_type`` and the id, so state and
  amounts are re-fetched (``GET subscriptions/{id}``, ``GET .../last-transaction``).
* Every paid period is one ``subscription_periods`` row and one ``period_allowance`` grant,
  issued through :meth:`UsageLedger.issue_grant`, which repays the owner's debt first (§5.8).
* A first payment that lands while another plan is live becomes credits (UD-3, UD-10), through
  the one public :func:`convert_payment_to_credits`, which Phase 06 reuses for the same case.
* Webhook and checkout methods leave the commit to the caller. Sweep methods commit after each
  subscription, so one Paymob failure cannot undo another subscription's change.
* Lock order: subscription row, then ``teacher_members`` rows, then ledger owner locks.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import timedelta
from decimal import ROUND_FLOOR, Decimal
from typing import TYPE_CHECKING, ClassVar, Final

import sqlalchemy as sa
import structlog
from sqlalchemy import event as sa_event
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError

from lemely.core.subscription_rules import (
    AMOUNT_SYNC_WINDOW,
    GRACE_PERIOD,
    MAX_EXTRA_SEATS_AT_CHECKOUT,
    PAYMOB_RETRIAL_DAYS,
    STALE_CHECKOUT_AFTER,
    expected_renewal_amount_minor,
    is_successful_charge,
    parse_paymob_time,
    paymob_frequency,
    period_end,
    renewal_period_start,
    seat_capacity_for,
    subscription_amount_minor,
)
from lemely.db.billing_notices import enqueue_subscription_notice
from lemely.db.billing_repo import (
    INTENTION_EXPIRATION_SECONDS,
    BillingService,
    CheckoutUnavailable,
    UnknownPayer,
    _as_int,
    _outcome_unknown,
    _redact_tokens,
    add_months,
    billing_data_for,
    is_linked_parent,
    register_paid_handler,
)
from lemely.db.models.billing import (
    LIVE_SUBSCRIPTION_STATUSES,
    PLAN_LIVE_STATUSES,
    Payment,
    PaymentPurpose,
    PaymentStatus,
    PaymobEvent,
    PaymobEventKind,
    PlanAudience,
    PlanTier,
    Subscription,
    SubscriptionPeriod,
)
from lemely.db.models.billing_ops import BillingSettings, CreditConversionRate
from lemely.db.models.enums import Role, SubscriptionStatus
from lemely.db.models.team import TeacherMember, TeacherMemberKind, TeacherMemberStatus
from lemely.db.models.usage import GrantKind, UsageGrant
from lemely.db.models.users import User
from lemely.db.teacher_team_repo import TeacherTeamService
from lemely.db.usage_ledger_repo import GrantAlreadyExpired, UsageLedger
from lemely.io.paymob.client import PaymobError

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.orm import Session

    from lemely.db.billing_repo import JsonMap
    from lemely.io.paymob.client import PaymobClient
    from lemely.runtime.config import PaymobSettings

log = structlog.get_logger(__name__)
#: Events the operator alerts on (``alert=True`` survives only in structlog).
alerts = structlog.get_logger("lemely.db.subscription_repo")

#: Path of the subscription webhook route (``lemely/web/routers/paymob_webhooks.py``, prefix
#: ``/api/webhooks/paymob``; the Cloudflare Worker proxies only ``/api/*``).
SUBSCRIPTION_WEBHOOK_PATH: Final = "/api/webhooks/paymob/subscription"

#: The ``trigger_type`` values of a subscription callback, exactly as Paymob sends them (the HMAC
#: is computed over the raw string, so dispatch matches the wire bytes; audit M6).
TRIGGER_CREATED: Final = "Subscription Created"
TRIGGER_SUCCESS: Final = "Successful Transaction"
TRIGGER_FAILED: Final = "Failed Transaction"
TRIGGER_OVERDUE: Final = "Failed Overdue Transaction"
TRIGGER_CANCELED: Final = "canceled"
TRIGGER_SUSPENDED: Final = "suspended"
TRIGGER_RESUMED: Final = "resumed"

#: The most rows one sweep pass takes (DV-15): the rest wait for the next pass, oldest deadline
#: first, so a backlog cannot hold one transaction's worth of Paymob calls open.
SUBSCRIPTION_SWEEP_BATCH: Final = 200

#: How far ahead of ``current_period_end`` a genuine failure can arrive. Paymob bills on a Cairo
#: calendar date while ``current_period_end`` is a UTC instant (about a day of difference), and
#: a renewal paid late on a retry day restarts our period at the charge while Paymob may keep
#: its own schedule (up to ``PAYMOB_RETRIAL_DAYS``): so a failure for an unpaid renewal can land
#: up to roughly 3 days 6 hours before the period end (S13 sandbox checklist to confirm). The
#: window errs wide on purpose: a failure is ignored on the period alone only when the period
#: runs further ahead than this (the renewal is certainly paid); closer than this, it is
#: ignored only when Paymob's last charge confirms the payment (``_confirms_payment``).
EARLY_CHARGE_WINDOW: Final = timedelta(days=3, hours=6)

#: Paymob ids and amounts above this are not Paymob data: the columns are 64-bit and a hostile or
#: corrupt body must not become a database error that makes the webhook fail on every retry.
_MAX_PAYMOB_INT: Final = 10**15


class SubscriptionError(Exception):
    """Base class; ``code`` is the machine-readable reason the API returns."""

    code: ClassVar[str] = "subscription_error"


class PlanNotPurchasable(SubscriptionError):
    code: ClassVar[str] = "plan_not_purchasable"


class PlanModeMismatch(PlanNotPurchasable):
    """The tier's Paymob plan was created under the other key mode (audit I8; 409).

    Paymob answers ``404 invalid subscription plan id`` for a plan id used with keys of the
    other mode, so the tier is refused here, before any row is written or Paymob is called.
    The message is for the user and says nothing about keys; the alert is for the operator.
    """

    code: ClassVar[str] = "plan_mode_mismatch"


class AlreadySubscribed(SubscriptionError):
    code: ClassVar[str] = "already_subscribed"


class NotLinkedParent(SubscriptionError):
    code: ClassVar[str] = "not_linked_parent"


class InvalidExtraSeats(SubscriptionError):
    code: ClassVar[str] = "invalid_extra_seats"


class SubscriptionNotFound(SubscriptionError):
    code: ClassVar[str] = "subscription_not_found"


class InvalidPlanChange(SubscriptionError):
    code: ClassVar[str] = "invalid_plan_change"


class SeatsInsufficient(SubscriptionError):
    """A teacher plan change would leave fewer seats than seated students (spec §2.6)."""

    code: ClassVar[str] = "seats_insufficient"

    def __init__(self, *, in_use: int, capacity: int) -> None:
        super().__init__(f"{in_use} seats are in use but the plan would hold {capacity}")
        self.in_use = in_use
        self.capacity = capacity


class MalformedWebhook(SubscriptionError):
    code: ClassVar[str] = "malformed_webhook"


class DowngradeUnavailable(SubscriptionError):
    """A downgrade would keep renewing at the old price: Paymob cannot lower the amount.

    Raised when ``subscription_amount_updatable`` is false. Same style as Phase 06's
    ``upgrade_unavailable``.
    """

    code: ClassVar[str] = "downgrade_unavailable"


class NoCreditRate(SubscriptionError):
    """No admin-set setting converts this payment, so it cannot be turned into credits (UD-12).

    ``reason`` tells the operator which setting to fix: ``no_rate`` (no rate row for the currency),
    ``no_validity_setting`` (no ``billing_settings`` row), ``below_one_unit`` (the amount is worth
    less than one unit) or ``overflow`` (the units do not fit a ``BIGINT``).
    """

    code: ClassVar[str] = "no_credit_rate"

    def __init__(self, message: str, *, reason: str) -> None:
        super().__init__(message)
        self.reason = reason


class PlanSyncFailed(SubscriptionError):
    """Paymob answered a plan creation without a usable plan id; the tier stays unlinked."""

    code: ClassVar[str] = "plan_sync_failed"


def subscription_webhook_url(settings: PaymobSettings) -> str:
    """The ``webhook_url`` Paymob plans post subscription callbacks to."""
    return f"{settings.notification_base_url.rstrip('/')}{SUBSCRIPTION_WEBHOOK_PATH}"


def _plan_id_of(response: object) -> int | None:
    """The integer ``id`` of a Paymob plan response, or ``None`` (a bool is not an id)."""
    if not isinstance(response, dict):
        return None
    value = response.get("id")
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def sync_paymob_plan(
    session: Session,
    client: PaymobClient,
    settings: PaymobSettings,
    plan_tier_id: uuid.UUID,
    *,
    force_new: bool = False,
) -> int:
    """Create the tier's Paymob subscription plan if it has none (or ``force_new``); link it.

    Plans use the MOTO integration (research 02 §6) and ``use_transaction_amount=true``, so extra
    seats bought at the first checkout are part of every renewal. ``force_new`` creates a new
    Paymob plan and re-links the tier (an admin re-sync, for example after the plan drifted from
    the tier's price or frequency); existing subscriptions keep their plan.

    The tier row is locked ``FOR UPDATE`` and the caller commits. Every refusal happens before
    Paymob is called. Owned by Phase 05 with this exact signature (index R9). Phase 07 calls it
    from the admin catalogue. Beside ``tier.paymob_plan_id`` and ``tier.paymob_plan_mode`` (the
    key mode the plan was created under, audit I8) it stamps the price and frequency it sent
    (``paymob_plan_synced_*``), and it logs ``paymob_plan_linked`` only after the commit.

    Raises:
        PlanNotPurchasable: unknown tier, no interval, a price of zero or less, or no MOTO
            integration id.
        PlanSyncFailed: Paymob answered without an integer plan id (logged as
            ``paymob_plan_response_unusable``); the tier is left as it was.
        PaymobError: the call failed. When the outcome is unknown (no answer, or a 5xx) Paymob may
            hold an orphan plan, which is logged as ``paymob_plan_create_unknown``.
    """
    tier = session.get(PlanTier, plan_tier_id, with_for_update=True)
    if tier is None:
        raise PlanNotPurchasable(f"unknown plan tier {plan_tier_id}")
    if tier.interval is None:
        raise PlanNotPurchasable("a plan tier without an interval cannot renew")
    if tier.price_minor <= 0:
        raise PlanNotPurchasable("a plan tier with no price cannot be billed")
    if tier.paymob_plan_id is not None and not force_new:
        return tier.paymob_plan_id
    if settings.moto_integration_id is None:
        raise PlanNotPurchasable("Paymob subscriptions need a MOTO integration id")
    try:
        created = client.create_plan(
            name=tier.code,
            frequency_days=paymob_frequency(tier.interval.value),
            amount_cents=tier.price_minor,
            integration_id=settings.moto_integration_id,
            webhook_url=subscription_webhook_url(settings),
            retrial_days=PAYMOB_RETRIAL_DAYS,
            use_transaction_amount=True,
        )
    except PaymobError as exc:
        if _outcome_unknown(exc):
            alerts.error(
                "paymob_plan_create_unknown",
                plan_tier_id=str(tier.id),
                error_type=type(exc).__name__,
                alert=True,
            )
        raise
    plan_id = _plan_id_of(created)
    if plan_id is None:
        alerts.error("paymob_plan_response_unusable", plan_tier_id=str(tier.id), alert=True)
        raise PlanSyncFailed(f"Paymob returned no plan id for tier {tier.id}")
    tier.paymob_plan_id = plan_id
    tier.paymob_plan_mode = settings.key_mode
    # What Paymob was just sent, for the admin drift warning. The one place a link is made (checkout
    # refuses an unlinked tier), so the stamp is written with it: same row, lock and transaction.
    tier.paymob_plan_synced_price_minor = tier.price_minor
    tier.paymob_plan_synced_frequency = paymob_frequency(tier.interval.value)
    _log_linked_after_commit(session, tier.id, plan_id)
    return plan_id


#: ``Session.info`` key holding the links whose ``paymob_plan_linked`` line is still undecided.
_PENDING_LINKS_KEY: Final = "lemely.paymob_plan_links"


@dataclass(slots=True)
class _PendingLink:
    plan_tier_id: uuid.UUID
    plan_id: int
    #: The transactions open when the link was made, innermost first. The link is discarded when
    #: any of them is rolled back.
    held_by: list[object]
    committed: bool = False
    discarded: bool = False


def _pending_links(session: Session) -> list[_PendingLink]:
    links: list[_PendingLink] = session.info.get(_PENDING_LINKS_KEY, [])
    return links


def _links_after_commit(session: Session) -> None:
    # SQLAlchemy dispatches this for a savepoint release too; there the session is still inside
    # the (nested) transaction being committed.
    if not session.in_nested_transaction():
        for link in _pending_links(session):
            link.committed = True


def _links_after_soft_rollback(session: Session, rolled_back: object) -> None:
    for link in _pending_links(session):
        if any(rolled_back is held for held in link.held_by):
            link.discarded = True


def _links_after_transaction_end(session: Session, ended: object) -> None:
    """Decide the pending links when the outermost transaction ends.

    However it ended: commit, rollback, or ``close()``, which emits neither.
    """
    if getattr(ended, "parent", None) is not None:
        return
    for link in session.info.pop(_PENDING_LINKS_KEY, []):
        if link.committed and not link.discarded:
            log.info(
                "paymob_plan_linked",
                plan_tier_id=str(link.plan_tier_id),
                paymob_plan_id=link.plan_id,
            )


def _log_linked_after_commit(session: Session, plan_tier_id: uuid.UUID, plan_id: int) -> None:
    """Log ``paymob_plan_linked`` when (and only if) the link commits for good.

    A rolled-back link is not a link: the caller's later failure must not leave this line in the
    log, and a link that did commit must be logged. It is judged on the outermost transaction:
    a savepoint release is not a commit, a savepoint that holds the link and is rolled back
    discards it, and an unrelated savepoint rolled back later does not. The line is written when
    the outermost transaction ends. The three listeners are registered once per session and
    share one pending list in ``session.info``, which each transaction end empties, so a
    long-lived session never accumulates listeners.
    """
    held_by: list[object] = []
    transaction = session.get_nested_transaction() or session.get_transaction()
    while transaction is not None:
        held_by.append(transaction)
        transaction = transaction.parent
    session.info.setdefault(_PENDING_LINKS_KEY, []).append(
        _PendingLink(plan_tier_id=plan_tier_id, plan_id=plan_id, held_by=held_by)
    )
    for name, listener in (
        ("after_commit", _links_after_commit),
        ("after_soft_rollback", _links_after_soft_rollback),
        ("after_transaction_end", _links_after_transaction_end),
    ):
        if not sa_event.contains(session, name, listener):
            sa_event.listen(session, name, listener)


_AUDIENCE_FOR_ROLE: Final = {Role.student: PlanAudience.student, Role.teacher: PlanAudience.teacher}
#: Closed payments: Phase 02 ignores every later callback for them, so they can never be paid.
#: A plain ``failed`` is not here: a card decline leaves the intention open and Phase 02 lets the
#: payment become ``paid`` on a later success (R20b). See :func:`_is_unpayable`.
_CLOSED_PAYMENT: Final = frozenset({PaymentStatus.failed_mismatch, PaymentStatus.voided})
#: How long a payment may still be paid after its intention was created.
_INTENTION_LIFETIME: Final = timedelta(seconds=INTENTION_EXPIRATION_SECONDS)
#: ``Payment.last_callback["source"]`` written when Paymob rejected the intention (no intention).
_NO_INTENTION_SOURCE: Final = "create_intention"
#: The constraint a racing second live checkout violates (``Subscription.__table_args__``).
_ONE_LIVE_INDEX: Final = "uq_subscriptions_one_live_per_user"
#: At most one ``alert=True`` plan-mode-mismatch event per tier per window (audit I8): every click
#: on a mismatched plan is refused, but the operator is paged once. Per process, keyed by tier id,
#: the value is the ``now`` of the last alert. Bounded by the number of tiers.
_MODE_ALERT_EVERY: Final = timedelta(minutes=10)
_MODE_ALERTED: Final[dict[uuid.UUID, datetime]] = {}
_ITEM_NAME_MAX: Final = 50  # Paymob items[].name limit (research 01 §2.1)
#: Shown to the user when a tier was synced under the other key mode; says nothing about keys.
_PLAN_MODE_MESSAGE: Final = "This plan is being set up. Please try again later."


@dataclass(frozen=True, slots=True)
class SubscriptionCheckout:
    """What the checkout route returns: the browser redirects to ``checkout_url``."""

    subscription_id: uuid.UUID
    payment_id: uuid.UUID
    checkout_url: str


def _bump(subscription: Subscription) -> None:
    """Advance ``version`` unless the mapper already does it (``version_id_col``)."""
    if sa.inspect(Subscription).version_id_col is None:
        subscription.version = (subscription.version or 0) + 1


def _has_other_live(session: Session, subscription: Subscription) -> bool:
    """Whether the beneficiary holds another live subscription."""
    return (
        session.scalar(
            select(Subscription.id).where(
                Subscription.user_id == subscription.user_id,
                Subscription.id != subscription.id,
                Subscription.status.in_(LIVE_SUBSCRIPTION_STATUSES),
            )
        )
        is not None
    )


def _line_items(tier: PlanTier, extra_seats: int) -> list[dict[str, object]]:
    """Intention line items; their total equals the payment amount (DV-6).

    Phase 02 refuses any line whose quantity is not 1, because whether Paymob's item ``amount``
    is a unit price or a line total is unconfirmed. The seats are therefore one line carrying
    the total for all of them.
    """
    items: list[dict[str, object]] = [
        {"name": tier.name[:_ITEM_NAME_MAX], "amount": tier.price_minor, "quantity": 1}
    ]
    if extra_seats > 0:
        items.append(
            {
                "name": f"Extra student seats x{extra_seats}",
                "amount": extra_seats * tier.extra_seat_price_minor,
                "quantity": 1,
            }
        )
    return items


def _strict_int(value: object) -> int | None:
    """``value`` when it is a real integer: a bool, a float and a digit string are not."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _seats_in_use(session: Session, teacher_id: uuid.UUID) -> int:
    """The teacher's active student seats: the count a plan's seats must cover (UD-5).

    A seat already ``leaving`` is not counted: the teacher asked for it to go, so removing
    seats lets them subscribe or switch plan at once instead of at month end.
    """
    return int(
        session.scalar(
            select(sa.func.count())
            .select_from(TeacherMember)
            .where(
                TeacherMember.teacher_user_id == teacher_id,
                TeacherMember.kind == TeacherMemberKind.student_seat,
                TeacherMember.status == TeacherMemberStatus.active,
            )
        )
        or 0
    )


def _shed_excess_seats(
    session: Session, subscription: Subscription, tier: PlanTier, *, now: datetime
) -> int:
    """Move the newest active seats over capacity to ``leaving`` (spec §5.4 fallback rule).

    Checkout already refuses a plan with fewer seats than the teacher holds (UD-5), so this only
    acts when a seat was claimed between checkout and payment. A leaving seat keeps working to
    month end and gets no new month's grant. Runs before the grant is issued (lock order,
    DV-13: member rows before ledger owner locks).
    """
    capacity = seat_capacity_for(
        included_seats=tier.included_seats, extra_seats=subscription.extra_seats or 0
    )
    excess = _seats_in_use(session, subscription.user_id) - capacity
    if excess <= 0:
        return 0
    newest = session.scalars(
        select(TeacherMember.id)
        .where(
            TeacherMember.teacher_user_id == subscription.user_id,
            TeacherMember.kind == TeacherMemberKind.student_seat,
            TeacherMember.status == TeacherMemberStatus.active,
        )
        .order_by(TeacherMember.created_at.desc(), TeacherMember.id.desc())
        .limit(excess)
    ).all()
    team = TeacherTeamService(session)
    for member_id in newest:
        team.request_removal(member_id, now=now)
    # A student the teacher did not choose to remove loses the seat at month end: page someone.
    alerts.error(
        "seats_shed_after_plan_change",
        teacher_user_id=str(subscription.user_id),
        subscription_id=str(subscription.id),
        count=len(newest),
        alert=True,
    )
    return len(newest)


# -- payment to credits (UD-3, UD-10; Phase 06 UD-P2) -------------------------------------


#: The largest value ``usage_grants.units`` (a ``BIGINT``) holds.
_BIGINT_MAX: Final = 2**63 - 1


def _credit_units(session: Session, *, amount_minor: int, currency: str) -> int:
    """``floor(amount_minor x rate)`` in exact decimal, or ``NoCreditRate`` with the reason."""
    if amount_minor <= 0:
        raise NoCreditRate("an amount of zero or less converts to nothing", reason="below_one_unit")
    rate = session.scalar(
        select(CreditConversionRate.units_per_minor).where(
            CreditConversionRate.currency == currency
        )
    )
    if rate is None or rate <= 0:
        raise NoCreditRate(f"no credit conversion rate for {currency}", reason="no_rate")
    units = int((Decimal(amount_minor) * rate).to_integral_value(rounding=ROUND_FLOOR))
    if units > _BIGINT_MAX:
        raise NoCreditRate("the converted units do not fit a grant", reason="overflow")
    if units < 1:
        raise NoCreditRate("the amount is worth less than one unit", reason="below_one_unit")
    return units


def credit_units_for_amount(session: Session, *, amount_minor: int, currency: str) -> int | None:
    """Credit units that ``amount_minor`` converts to, or ``None`` when it cannot be converted.

    The one credit rate of the billing code (Phase 05 UD-3, Phase 06 UD-P2) is the fixed,
    admin-set ``credit_conversion_rates.units_per_minor`` of ``currency`` (UD-12): usage units per
    minor currency unit, exact decimal. The result is ``floor(amount_minor x rate)``, so a
    conversion never grants more than was paid. It fails closed: ``None`` when the currency has no
    row (nothing is inferred from credit packs or any constant), when the amount is too small for
    one unit, and when the units would not fit a ``BIGINT``. The read runs in the caller's
    transaction and takes no lock; a rate edited concurrently applies to the next conversion.
    :func:`convert_payment_to_credits` uses the same arithmetic and says why it refused.
    """
    try:
        return _credit_units(session, amount_minor=amount_minor, currency=currency)
    except NoCreditRate:
        return None


def _grant_by_key(session: Session, owner_id: uuid.UUID, idempotency_key: str) -> UsageGrant | None:
    return session.scalars(
        select(UsageGrant).where(
            UsageGrant.owner_user_id == owner_id, UsageGrant.idempotency_key == idempotency_key
        )
    ).one_or_none()


def _credit_validity_months(session: Session) -> int:
    """The admin-set credit validity: ``billing_settings.credit_validity_months`` (``id = 1``).

    Read in the caller's transaction, no lock. Fails closed: a missing row is ``NoCreditRate`` (the
    migration and ``create_all`` both insert it, so its absence is a damaged database, and no
    constant stands in for it).
    """
    months = session.scalar(
        select(BillingSettings.credit_validity_months).where(BillingSettings.id == 1)
    )
    if months is None:
        raise NoCreditRate(
            "no billing settings row: the credit validity is not set", reason="no_validity_setting"
        )
    return months


def convert_payment_to_credits(
    session: Session, payment: Payment, *, subscription: Subscription, now: datetime
) -> UsageGrant:
    """Turn a paid payment that bought nothing into the beneficiary's credits (UD-3, UD-10).

    Issues a visible ``credit_pack`` grant that expires after the admin-set
    ``credit_validity_months`` counted from ``now`` (key ``credited:{payment.id}``), stamps
    ``payment.grant_units`` and queues the "credited" notice to ``subscription``'s payer. Debt is
    repaid first by the ledger. Idempotent: a replay returns the stored grant and queues nothing
    new, and the units and expiry are the first conversion's, not today's. Callers pass
    ``payment.paid_at`` as ``now`` so a replay names the same instant.
    The caller commits and holds the payment row lock; this makes no Paymob call.

    Raises:
        ValueError: the payment is not ``paid``; it is a credit pack payment (it already bought
            its credits); it already paid for a subscription period; or it carries grant units
            that no earlier conversion issued.
        NoCreditRate: no admin-set rate for the payment's currency, the amount is below one unit,
            the units overflow a ``BIGINT``, or the ``billing_settings`` row is missing (fail
            closed, UD-12). ``reason`` names which.
    """
    if payment.status is not PaymentStatus.paid:
        raise ValueError("only a paid payment can be turned into credits")
    if payment.purpose is PaymentPurpose.credit_pack:
        raise ValueError("a credit pack payment already bought its credits")
    if _period_for_payment(session, payment.id) is not None:
        raise ValueError("this payment already paid for a subscription period")
    credited_key = f"credited:{payment.id}"
    stored = _grant_by_key(session, payment.beneficiary_user_id, credited_key)
    if payment.grant_units is not None and stored is None:
        raise ValueError("this payment carries grant units that no conversion issued")
    # A replay keeps the units and the expiry already stamped on the grant, even when the payment
    # lost its ``grant_units``: it reads no rate and no setting, and an edit made since never
    # moves a grant that was issued.
    units = (
        stored.units
        if stored is not None
        else _credit_units(session, amount_minor=payment.amount_minor, currency=payment.currency)
    )
    expires_at = (
        stored.expires_at
        if stored is not None and stored.expires_at is not None
        else add_months(now, _credit_validity_months(session))
    )
    grant = UsageLedger(session).issue_grant(
        owner_user_id=payment.beneficiary_user_id,
        kind=GrantKind.credit_pack,
        units=units,
        idempotency_key=credited_key,
        expires_at=expires_at,
        visible=True,
        effective_at=now,
        payment_id=payment.id,
    )
    payment.grant_units = units
    enqueue_subscription_notice(
        session, subscription=subscription, notice="credited", effective_at=now
    )
    return grant


# -- first payment ----------------------------------------------------------------------


def _issue_period_grant(
    session: Session,
    subscription: Subscription,
    tier: PlanTier,
    period: SubscriptionPeriod,
    payment: Payment,
) -> UsageGrant | None:
    """The period's ``period_allowance`` grant, the one definition (constraints §5.2).

    Owned by the beneficiary, invisible, effective at the period start and expiring at its end;
    the ledger repays the owner's debt first. A tier with no allowance grants nothing (the ledger
    refuses zero units).
    """
    if not tier.allowance_units:
        return None
    return UsageLedger(session).issue_grant(
        owner_user_id=subscription.user_id,
        kind=GrantKind.period_allowance,
        units=tier.allowance_units,
        idempotency_key=f"period:{period.id}",
        expires_at=period.period_end,
        visible=False,
        effective_at=period.period_start,
        payment_id=payment.id,
        subscription_period_id=period.id,
    )


def _period_for_payment(session: Session, payment_id: uuid.UUID) -> uuid.UUID | None:
    """The period this payment already paid for, if any (the handler's replay guard)."""
    return session.scalar(
        select(SubscriptionPeriod.id).where(SubscriptionPeriod.payment_id == payment_id)
    )


#: Stored ``Subscription Created`` events one payment can match; far above what one txn names.
_LINK_EVENT_SCAN: Final = 20


def _link_stored_created_event(
    session: Session, subscription: Subscription, payment: Payment, *, now: datetime
) -> None:
    """Link a ``Subscription Created`` webhook that arrived before the first payment's callback.

    Matches only ``payload["remote"]``, the copy Paymob returned to our own ``GET`` (R26, DV-11):
    the webhook body is unsigned. ``remote.initial_transaction`` must be the integer id of this
    payment's transaction and ``remote.id`` an integer (a string or a bool is neither). A Paymob id
    another subscription already holds is not linked (alert); the event stays unprocessed.
    """
    txn_id = payment.paymob_txn_id
    if subscription.paymob_subscription_id is not None or txn_id is None:
        return
    events = session.scalars(
        select(PaymobEvent)
        .where(
            PaymobEvent.kind == PaymobEventKind.subscription,
            PaymobEvent.processed_at.is_(None),
            PaymobEvent.payload["remote"]["initial_transaction"] == sa.type_coerce(txn_id, JSONB),
        )
        .order_by(PaymobEvent.created_at, PaymobEvent.id)
        .limit(_LINK_EVENT_SCAN)
        .with_for_update()
    ).all()
    for event in events:
        remote = event.payload.get("remote")
        if not isinstance(remote, dict):
            continue
        remote_id = _strict_int(remote.get("id"))
        if (
            remote_id is None
            or remote_id <= 0
            or _strict_int(remote.get("initial_transaction")) != txn_id
        ):
            continue
        holder = session.scalar(
            select(Subscription.id).where(Subscription.paymob_subscription_id == remote_id)
        )
        if holder is not None:
            alerts.error(
                "subscription_created_event_link_conflict",
                subscription_id=str(subscription.id),
                paymob_subscription_id=remote_id,
                alert=True,
            )
            continue
        subscription.paymob_subscription_id = remote_id
        event.processed_at = now
        log.info(
            "paymob_subscription_linked",
            subscription_id=str(subscription.id),
            paymob_subscription_id=remote_id,
        )
        return


def lock_paymob_transaction(session: Session, txn_id: int) -> None:
    """Serialise everything that acts on one Paymob transaction id, until the transaction ends.

    The first-payment handler takes it after the payment row lock and before any subscription
    lock; the subscription webhook (T6 ``_resolve``) takes it before it looks the payment up. Of
    the callback and the ``Subscription Created`` webhook for one first charge, whichever runs
    second then sees the other's commit, so the webhook's event is linked or the payment is found.
    """
    session.execute(
        sa.text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"paymob_txn:{txn_id}"},
    )


def _lock_subscriptions(session: Session, subscription_id: uuid.UUID) -> Subscription | None:
    """Lock ``subscription_id`` and the beneficiary's live rows together, in id order.

    One ordered ``FOR UPDATE`` over the whole set (not "mine, then theirs") is what keeps two late
    payments of one account from deadlocking: both lock the same rows in the same order. The
    returned row is re-read after the lock, so its status is the committed one.
    """
    user_id = session.scalar(select(Subscription.user_id).where(Subscription.id == subscription_id))
    if user_id is None:
        return None
    rows = session.scalars(
        select(Subscription)
        .where(
            sa.or_(
                Subscription.id == subscription_id,
                sa.and_(
                    Subscription.user_id == user_id,
                    Subscription.status.in_(LIVE_SUBSCRIPTION_STATUSES),
                ),
            )
        )
        .order_by(Subscription.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).all()
    return next((row for row in rows if row.id == subscription_id), None)


def _live_others(session: Session, subscription: Subscription) -> list[Subscription]:
    """The beneficiary's other live rows (locked by :func:`_lock_subscriptions`)."""
    return list(
        session.scalars(
            select(Subscription).where(
                Subscription.user_id == subscription.user_id,
                Subscription.id != subscription.id,
                Subscription.status.in_(LIVE_SUBSCRIPTION_STATUSES),
            )
        )
    )


#: A first payment in one of these states moved money that was not returned.
_MONEY_PAID: Final = (PaymentStatus.paid, PaymentStatus.refunded, PaymentStatus.partially_refunded)


def _is_plan_in_force(session: Session, other: Subscription) -> bool:
    """Whether ``other`` is a plan the payer has, not an unpaid checkout waiting for money.

    ``active`` and ``past_due`` are in force. A ``pending_first_payment`` row is not, unless a
    first payment of it already settled (its handler has not finished): then it is treated as in
    force, because expiring it would throw away money.
    """
    if other.status in PLAN_LIVE_STATUSES:
        return True
    return (
        session.scalar(
            select(Payment.id)
            .where(
                Payment.subscription_id == other.id,
                Payment.purpose == PaymentPurpose.subscription_first,
                Payment.status.in_(_MONEY_PAID),
            )
            .limit(1)
        )
        is not None
    )


def _convert_superseded_payment(
    session: Session, payment: Payment, subscription: Subscription, *, paid_at: datetime
) -> None:
    """UD-3: the checkout lost to another live plan, so its payment becomes credits.

    A pending row leaves the live set first: its payment is paid, so no later checkout may
    replace it and it would otherwise block the account for good. The Paymob subscription it
    created is cancelled by the sweeps, not here (DV-15, DV-27). Without a credit rate nothing is
    granted: the payment stays ``paid`` and the alert asks for a manual refund.
    """
    if subscription.status is SubscriptionStatus.pending_first_payment:
        subscription.status = SubscriptionStatus.expired
        _bump(subscription)
        session.flush()
    try:
        convert_payment_to_credits(session, payment, subscription=subscription, now=paid_at)
    except NoCreditRate as exc:
        alerts.error(
            "subscription_first_paid_for_superseded_checkout",
            subscription_id=str(subscription.id),
            payment_id=str(payment.id),
            converted=False,
            reason=exc.reason,
            alert=True,
        )
        return
    log.warning(
        "subscription_first_paid_for_superseded_checkout",
        subscription_id=str(subscription.id),
        payment_id=str(payment.id),
        converted=True,
    )


def handle_subscription_first(session: Session, payment: Payment, obj: JsonMap) -> None:
    """Paid handler for ``subscription_first`` (spec §5.1 step 4), in the callback's transaction.

    Phase 02 has set ``payment.status = paid`` and ``payment.paid_at`` from its injected clock and
    holds the payment row lock; this locks the subscription (lock order: payment, event,
    subscription, member rows, ledger). It activates the subscription, starts the first period at
    ``paid_at``, inserts the period row and its allowance grant, and links the Paymob subscription
    when its ``Subscription Created`` webhook came first. A replay does nothing.

    The checkout may have been superseded: when another plan is live the payment becomes credits
    instead (UD-3). A subscription in any other state raises the alert
    ``subscription_first_paid_in_unexpected_state`` and is left alone.

    Raises:
        RuntimeError: ``payment.paid_at`` is missing (the clock is never guessed).
    """
    del obj  # the callback was verified and matched to ``payment`` by BillingService
    paid_at = payment.paid_at
    if paid_at is None:
        raise RuntimeError(f"subscription payment {payment.id} has no paid_at")
    if payment.subscription_id is None:
        alerts.error(
            "subscription_first_paid_without_subscription", payment_id=str(payment.id), alert=True
        )
        return
    if payment.paymob_txn_id is not None:
        lock_paymob_transaction(session, payment.paymob_txn_id)
    subscription = _lock_subscriptions(session, payment.subscription_id)
    if subscription is None:
        alerts.error(
            "subscription_first_paid_without_subscription", payment_id=str(payment.id), alert=True
        )
        return
    if _period_for_payment(session, payment.id) is not None or payment.grant_units is not None:
        return  # activated, or already turned into credits
    if subscription.status not in (
        SubscriptionStatus.pending_first_payment,
        SubscriptionStatus.expired,
    ):
        alerts.error(
            "subscription_first_paid_in_unexpected_state",
            subscription_id=str(subscription.id),
            payment_id=str(payment.id),
            status=subscription.status.value,
            alert=True,
        )
        return
    _link_stored_created_event(session, subscription, payment, now=paid_at)
    others = _live_others(session, subscription)
    if any(_is_plan_in_force(session, other) for other in others):
        _convert_superseded_payment(session, payment, subscription, paid_at=paid_at)
        return
    tier = session.get(PlanTier, subscription.plan_tier_id)
    if tier is None or tier.interval is None:
        alerts.error(
            "subscription_first_paid_for_unusable_tier",
            subscription_id=str(subscription.id),
            payment_id=str(payment.id),
            alert=True,
        )
        return
    end = period_end(paid_at, tier.interval.value)
    try:
        # A savepoint: a live row committed after the locks were taken (a brand-new checkout
        # is not locked) trips the unique index, and the payment then becomes credits.
        with session.begin_nested():
            for unpaid in others:  # only unpaid pending checkouts reach here: they leave first
                unpaid.status = SubscriptionStatus.expired
                _bump(unpaid)
                log.info(
                    "subscription_unpaid_checkout_expired_by_payment",
                    subscription_id=str(unpaid.id),
                    paid_subscription_id=str(subscription.id),
                )
            session.flush()
            subscription.status = SubscriptionStatus.active
            subscription.activated_at = paid_at
            subscription.current_period_start = paid_at
            subscription.current_period_end = end
            subscription.grace_until = None
            subscription.paymob_amount_minor = payment.amount_minor
            _bump(subscription)
            session.flush()
    except IntegrityError as exc:
        if not _violates_one_live(exc):
            raise
        _convert_superseded_payment(session, payment, subscription, paid_at=paid_at)
        return
    period = SubscriptionPeriod(
        subscription_id=subscription.id,
        period_start=paid_at,
        period_end=end,
        payment_id=payment.id,
    )
    session.add(period)
    session.flush()
    if tier.audience is PlanAudience.teacher:
        _shed_excess_seats(session, subscription, tier, now=paid_at)
    _issue_period_grant(session, subscription, tier, period, payment)
    log.info(
        "subscription_activated",
        subscription_id=str(subscription.id),
        payment_id=str(payment.id),
    )


# -- renewals -----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RemoteState:
    """What Paymob itself returned for a webhook: never read from the (partly unsigned) body.

    ``subscription`` is ``GET subscriptions/{id}``; ``last_transaction`` is the charge, fetched
    for a ``Successful Transaction`` trigger only.
    """

    subscription: JsonMap
    last_transaction: JsonMap | None = None


TriggerHandler = Callable[[Subscription, RemoteState, "datetime"], None]


class _OtherPlanLive(Exception):
    """A renewal could not reactivate a lapsed plan: the account holds another live one."""


def parse_subscription_webhook(body: JsonMap) -> tuple[str, int]:
    """``(trigger_type, subscription id)``, the two fields the HMAC signs.

    ``paymob_request_id`` and every other field are unsigned, so nothing here returns them.

    Raises:
        MalformedWebhook: the trigger is missing or not a string, or the id is not a positive
            integer (a bool, a float and a digit string are not).
    """
    trigger = body.get("trigger_type")
    data = body.get("subscription_data")
    paymob_id = _strict_int(data.get("id")) if isinstance(data, Mapping) else None
    if (
        not isinstance(trigger, str)
        or not trigger
        or paymob_id is None
        or not 0 < paymob_id <= _MAX_PAYMOB_INT
    ):
        raise MalformedWebhook("trigger_type and an integer subscription_data.id are required")
    return trigger, paymob_id


def _period_terms(
    session: Session, subscription: Subscription, *, with_pending: bool
) -> tuple[PlanTier, int]:
    """The tier and extra seats the next period uses, with or without the pending change.

    A tier that sells no extra seats holds none, whatever the row says.
    """
    pending_tier_id = subscription.pending_plan_tier_id if with_pending else None
    tier = session.get(PlanTier, pending_tier_id or subscription.plan_tier_id)
    if tier is None:
        raise RuntimeError(f"subscription {subscription.id} has no plan tier")
    seats = (
        subscription.pending_extra_seats
        if with_pending and subscription.pending_extra_seats is not None
        else subscription.extra_seats or 0
    )
    return tier, seats if tier.extra_seat_price_minor > 0 else 0


def _expected_renewal_amount(
    session: Session, subscription: Subscription, *, amount_updatable: bool = True
) -> int:
    """What Paymob should charge at the next renewal, pending changes included (DV-12, R6).

    The body of :meth:`SubscriptionService.next_renewal_amount`. ``amount_updatable`` is
    ``PaymobSettings.subscription_amount_updatable``; only the paid-handler entry point
    (:func:`handle_subscription_renewal`, which no production path dispatches) leaves it at its
    default.
    """
    tier, seats = _period_terms(session, subscription, with_pending=True)
    return expected_renewal_amount_minor(
        price_minor=tier.price_minor,
        extra_seats=seats,
        extra_seat_price_minor=tier.extra_seat_price_minor,
        paymob_amount_minor=subscription.paymob_amount_minor,
        amount_updatable=amount_updatable,
    )


def _grant_renewal_period(
    session: Session,
    subscription: Subscription,
    payment: Payment,
    *,
    charged_at: datetime,
    now: datetime,
    apply_pending: bool,
) -> SubscriptionPeriod:
    """Start the paid period: move the subscription, insert the period, grant the allowance.

    A plan in force continues from its period end (no gap, no overlap, however early the charge
    landed); a late charge or a reactivated plan starts at the charge. The pending tier and seat
    changes are applied only when ``apply_pending`` (the charge was the amount they set).
    Excess seats are shed before the grant is issued (lock order, DV-13).

    Raises:
        _OtherPlanLive: the plan was ended and the account now holds another live one; nothing
            was changed.
    """
    tier, seats = _period_terms(session, subscription, with_pending=apply_pending)
    assert tier.interval is not None  # noqa: S101 - the caller checked
    live = subscription.status in PLAN_LIVE_STATUSES
    old_period_end = subscription.current_period_end
    start = (
        renewal_period_start(
            current_period_end=subscription.current_period_end, charged_at=charged_at
        )
        if live
        else charged_at
    )
    end = period_end(start, tier.interval.value)
    try:
        # A savepoint: reactivating an ended plan can trip the one-live-per-user index when a
        # checkout committed after the locks were taken, and then nothing may change.
        with session.begin_nested():
            if apply_pending:
                if tier.id != subscription.plan_tier_id:
                    # (plan_tier_id, terms_version) is a composite foreign key: a tier change
                    # moves to the target's current terms, and a pending move to terms only the
                    # old tier has is dropped with it (P07-T1 review M3).
                    subscription.terms_version = tier.terms_version
                    subscription.pending_terms_version = None
                    subscription.pending_terms_effective_at = None
                subscription.plan_tier_id = tier.id
                subscription.pending_plan_tier_id = None
                subscription.extra_seats = seats
                subscription.pending_extra_seats = None
            if not live and subscription.paymob_cancelled_at is not None:
                # A late charge on a plan whose Paymob subscription is already cancelled: the paid
                # period runs, but Paymob never charges again. End it at the period end as a
                # cancellation (UD-4 (b) semantics), so it does not look auto-renewing and never
                # slides into "payment failed" notices the user cannot act on.
                subscription.cancel_at_period_end = True
            subscription.status = SubscriptionStatus.active
            subscription.grace_until = None
            subscription.current_period_start = start
            subscription.current_period_end = end
            subscription.paymob_amount_minor = payment.amount_minor
            _bump(subscription)
            session.flush()
    except IntegrityError as exc:
        if not _violates_one_live(exc):
            raise
        raise _OtherPlanLive from exc
    period = SubscriptionPeriod(
        subscription_id=subscription.id,
        period_start=start,
        period_end=end,
        payment_id=payment.id,
    )
    session.add(period)
    session.flush()
    if tier.audience is PlanAudience.teacher:
        _shed_excess_seats(session, subscription, tier, now=now)
    if live:
        # A renewal paid during grace: the old period's leftover must not stack onto the new one.
        # After the seat shedding: that locks member rows, and no member lock may follow a ledger
        # lock (DV-13). The old period is the one the subscription pointed at before this call.
        _end_period_grants(session, subscription, now=now, period_end=old_period_end)
    _issue_period_grant(session, subscription, tier, period, payment)
    enqueue_subscription_notice(
        session, subscription=subscription, notice="renewed", effective_at=end
    )
    log.info(
        "subscription_renewed",
        subscription_id=str(subscription.id),
        payment_id=str(payment.id),
        period_end=end.isoformat(),
    )
    return period


def _note_charge_kept(subscription: Subscription, payment: Payment, *, reason: str) -> None:
    """A renewal charge moved money but bought no period: an operator must refund it (UD-2)."""
    alerts.error(
        "subscription_charge_on_ended_subscription",
        subscription_id=str(subscription.id),
        payment_id=str(payment.id),
        status=subscription.status.value,
        reason=reason,
        alert=True,
    )


def _settle_renewal(
    session: Session,
    subscription: Subscription,
    payment: Payment,
    *,
    charged_at: datetime,
    now: datetime,
    amount_updatable: bool = True,
) -> bool:
    """Grant the period a paid renewal payment bought, or keep the payment for a refund.

    Returns ``True`` when a period was granted. The caller holds the subscription lock and has
    accepted the payment's amount. A plan in force renews. A plan that lapsed for non-payment
    (``expired``) and ran before (``activated_at``) is reactivated when the account holds no other
    live plan (UD-2): the user is paying to keep it. A user-cancelled plan, a checkout that never
    activated (a credits-converted one included) and a lapse that lost its slot to another plan
    stay ended: the payment stays ``paid``, no period is granted and the alert asks for a refund.
    The Paymob subscription of such a row is cancelled by the sweeps (DV-15, DV-27).
    """
    status = subscription.status
    if status not in PLAN_LIVE_STATUSES:
        if status is not SubscriptionStatus.expired:
            _note_charge_kept(
                subscription,
                payment,
                reason="cancelled" if status is SubscriptionStatus.cancelled else "not_a_plan",
            )
            return False
        if subscription.activated_at is None:
            _note_charge_kept(subscription, payment, reason="never_activated")
            return False
        if _has_other_live(session, subscription):
            _note_charge_kept(subscription, payment, reason="other_plan_live")
            return False
    elif subscription.cancel_at_period_end:
        # The paid period is granted and the flag kept, but the user asked to stop and was charged
        # anyway: our Paymob cancel did not take effect. Page someone.
        alerts.error(
            "subscription_renewal_after_cancel_request",
            subscription_id=str(subscription.id),
            payment_id=str(payment.id),
            alert=True,
        )
    expected = _expected_renewal_amount(session, subscription, amount_updatable=amount_updatable)
    apply_pending = payment.amount_minor == expected
    if not apply_pending and (
        subscription.pending_plan_tier_id is not None
        or subscription.pending_extra_seats is not None
    ):
        log.warning(
            "subscription_pending_change_deferred",
            subscription_id=str(subscription.id),
            charged_minor=payment.amount_minor,
            expected_minor=expected,
        )
    tier, _ = _period_terms(session, subscription, with_pending=apply_pending)
    if tier.interval is None:
        alerts.error(
            "subscription_renewal_for_unusable_tier",
            subscription_id=str(subscription.id),
            payment_id=str(payment.id),
            alert=True,
        )
        return False
    try:
        _grant_renewal_period(
            session,
            subscription,
            payment,
            charged_at=charged_at,
            now=now,
            apply_pending=apply_pending,
        )
    except _OtherPlanLive:
        _note_charge_kept(subscription, payment, reason="other_plan_live")
        return False
    return True


def handle_subscription_renewal(session: Session, payment: Payment, obj: JsonMap) -> None:
    """Paid handler for ``subscription_renewal``, in the callback's transaction (DV-33).

    Renewals reach Lemely through the subscription webhook and the drift check, which record the
    payment already ``paid`` and grant the period themselves; Phase 02 dispatches nothing to this
    handler today, but a renewal payment that is settled by its own callback gets the same
    period here. One period per payment: a replay does nothing. The clock is the payment's
    ``paid_at``, never the wall clock. The amount is NOT re-checked against the DV-12 rule: a
    caller must only pass a payment whose amount was already accepted.

    Raises:
        RuntimeError: ``payment.paid_at`` is missing.
    """
    del obj  # the callback was verified and matched to ``payment`` by BillingService
    paid_at = payment.paid_at
    if paid_at is None:
        raise RuntimeError(f"subscription renewal payment {payment.id} has no paid_at")
    subscription = (
        _lock_subscriptions(session, payment.subscription_id)
        if payment.subscription_id is not None
        else None
    )
    if subscription is None:
        alerts.error(
            "subscription_renewal_paid_without_subscription",
            payment_id=str(payment.id),
            alert=True,
        )
        return
    if _period_for_payment(session, payment.id) is not None:
        return
    _settle_renewal(session, subscription, payment, charged_at=paid_at, now=paid_at)


def _period_grants(
    session: Session, subscription: Subscription, period_end: datetime | None
) -> list[tuple[uuid.UUID, datetime]]:
    """``(grant id, the period's end)`` for the grants of the period ending at ``period_end``."""
    if period_end is None:
        return []
    rows = session.execute(
        select(UsageGrant.id, SubscriptionPeriod.period_end)
        .join(SubscriptionPeriod, SubscriptionPeriod.id == UsageGrant.subscription_period_id)
        .where(
            SubscriptionPeriod.subscription_id == subscription.id,
            SubscriptionPeriod.period_end == period_end,
        )
        .order_by(UsageGrant.id)
    ).all()
    return [(row[0], row[1]) for row in rows]


def _extend_period_grants(
    session: Session, subscription: Subscription, *, until: datetime, now: datetime
) -> None:
    """Keep the current period's grants usable until ``until`` (UD-1 (b)).

    No units are granted and none are lost. A grant whose expiry passed is extended too, while
    the expiry sweep has not taken its leftover (the failure usually arrives at or after the
    period end). One the sweep already took (or a claw-back closed) is skipped with an info log,
    the normal outcome of a failure that lands after the sweep. Any other ledger failure is
    alerted and rolled back alone: the failed renewal itself must still be recorded (a webhook
    that fails here is retried by Paymob for ever).
    """
    ledger = UsageLedger(session)
    for grant_id, issued_end in _period_grants(
        session, subscription, subscription.current_period_end
    ):
        try:
            with session.begin_nested():
                ledger.extend_grant_expiry(
                    grant_id, expires_at=until, now=now, issued_expires_at=issued_end
                )
        except GrantAlreadyExpired:
            log.info(
                "subscription_grace_extension_skipped",
                subscription_id=str(subscription.id),
                grant_id=str(grant_id),
            )
        except Exception as exc:
            alerts.error(
                "subscription_grace_extension_failed",
                subscription_id=str(subscription.id),
                grant_id=str(grant_id),
                error=type(exc).__name__,
                alert=True,
            )


def _end_period_grants(
    session: Session, subscription: Subscription, *, now: datetime, period_end: datetime | None
) -> None:
    """End the grace extension of the period ending at ``period_end``.

    Its grants go back to ``max(period end, now)``.

    Called when the plan expires or a renewal is paid while the old period's leftover is still
    extended, so the leftover neither outlives an expired plan nor stacks onto the new period.
    A grant that was never extended is untouched. Best effort, like the extension.
    """
    ledger = UsageLedger(session)
    for grant_id, ends_at in _period_grants(session, subscription, period_end):
        try:
            with session.begin_nested():
                ledger.shorten_grant_expiry(grant_id, expires_at=max(ends_at, now))
        except Exception as exc:
            alerts.error(
                "subscription_grace_end_failed",
                subscription_id=str(subscription.id),
                grant_id=str(grant_id),
                error=type(exc).__name__,
                alert=True,
            )


class SubscriptionService:
    """The subscription lifecycle, bound to one session (see the module docstring)."""

    def __init__(self, session: Session, client: PaymobClient, settings: PaymobSettings) -> None:
        self._session = session
        self._client = client
        self._settings = settings

    def _billing(self, now: datetime) -> BillingService:
        """A payments service whose clock is the caller's ``now``, never the wall clock (DV-8)."""
        return BillingService(self._session, self._client, self._settings, now=lambda: now)

    # -- checkout ----------------------------------------------------------------------

    def create_subscription_checkout(
        self,
        *,
        payer_user_id: uuid.UUID,
        plan_tier_id: uuid.UUID,
        beneficiary_user_id: uuid.UUID | None = None,
        extra_seats: int = 0,
        now: datetime,
    ) -> SubscriptionCheckout:
        """Start a card subscription (spec §5.1 steps 1-3).

        The price comes from ``plan_tiers`` only. A parent buys for a linked student; anyone else
        buys for themselves. The tier's audience must match the beneficiary's role. Every refusal
        is decided before the first write, so nothing is committed on a refusal. The caller must
        not wrap the call in ``session.begin()``: Phase 02's ``create_intention_checkout``
        commits the pending subscription and its payment before calling Paymob, and again after.

        Raises:
            CheckoutUnavailable: Paymob is not configured (nothing is written), or Paymob failed.
                After a failure the pending subscription and its payment stay committed: a
                definite rejection marks the payment ``failed`` (anyone's next checkout replaces
                it), an unknown outcome leaves it ``created`` (only the same payer's replaces it).
            UnknownPayer: the payer has no ``users`` row.
            NotLinkedParent: a parent without a linked student beneficiary, or anyone else naming
                another account.
            PlanNotPurchasable: unknown, inactive, unsynced or interval-less tier, or one for
                another audience than the beneficiary's role.
            PlanModeMismatch: the tier's plan was created under the other Paymob key mode.
            InvalidExtraSeats: extra seats on a student tier, on a tier with no seat price, or
                outside ``0..MAX_EXTRA_SEATS_AT_CHECKOUT``.
            SeatsInsufficient: a teacher holds more active seats than the plan would cover (UD-5).
            AlreadySubscribed: the beneficiary already has a live subscription.
            PhoneRequired: the payer has no valid phone (UD-11, raised by ``billing_data_for``).
        """
        if not self._settings.checkout_configured:
            raise CheckoutUnavailable("Paymob checkout is not configured")
        session = self._session
        payer = session.get(User, payer_user_id)
        if payer is None:
            raise UnknownPayer(str(payer_user_id))
        beneficiary = self._beneficiary_for(payer, beneficiary_user_id)
        tier = self._sellable_tier(plan_tier_id, beneficiary, now=now)
        if not 0 <= extra_seats <= MAX_EXTRA_SEATS_AT_CHECKOUT or (
            extra_seats > 0
            and (tier.audience is not PlanAudience.teacher or tier.extra_seat_price_minor == 0)
        ):
            raise InvalidExtraSeats("extra seats are only for teacher plans with a seat price")
        if tier.audience is PlanAudience.teacher:
            self._require_seats_covered(beneficiary.id, tier, extra_seats)
        billing_data = billing_data_for(payer)  # PhoneRequired before any row is written
        self._retire_stale_checkout(beneficiary.id, payer_user_id, now=now)
        amount = subscription_amount_minor(
            price_minor=tier.price_minor,
            extra_seats=extra_seats,
            extra_seat_price_minor=tier.extra_seat_price_minor,
        )
        subscription = Subscription(
            id=uuid.uuid4(),
            user_id=beneficiary.id,
            payer_user_id=payer_user_id,
            plan_tier_id=tier.id,
            status=SubscriptionStatus.pending_first_payment,
            extra_seats=extra_seats,
        )
        try:
            with session.begin_nested():
                session.add(subscription)
                session.flush()
        except IntegrityError as exc:
            if not _violates_one_live(exc):
                raise
            # A racing checkout committed a live subscription for this beneficiary first.
            raise AlreadySubscribed("this account already has a live subscription") from exc
        payment_id = uuid.uuid4()
        payment = Payment(
            id=payment_id,
            special_reference=str(payment_id),
            payer_user_id=payer_user_id,
            beneficiary_user_id=beneficiary.id,
            purpose=PaymentPurpose.subscription_first,
            plan_tier_id=tier.id,
            subscription_id=subscription.id,
            seat_quantity=extra_seats or None,  # the CHECK forbids 0
            amount_minor=amount,
            currency=tier.currency,
            status=PaymentStatus.created,
        )
        session.add(payment)
        session.flush()
        assert tier.paymob_plan_id is not None  # _sellable_tier  # noqa: S101
        result = self._billing(now).create_intention_checkout(
            payment=payment,
            items=_line_items(tier, extra_seats),
            billing_data=billing_data,
            subscription_plan_id=tier.paymob_plan_id,
        )
        log.info(
            "subscription_checkout_created",
            subscription_id=str(subscription.id),
            payment_id=str(payment_id),
            amount_minor=amount,
        )
        return SubscriptionCheckout(subscription.id, result.payment_id, result.checkout_url)

    def _beneficiary_for(self, payer: User, requested: uuid.UUID | None) -> User:
        """Who the plan is for: a linked student for a parent, else the payer themselves (DV-7).

        A parent must name a student ``is_linked_parent`` links to them (the same rule as
        Phase 02's ``_may_buy_for``); anyone else may name only themselves.
        """
        if payer.role is Role.parent:
            if requested is None or not is_linked_parent(self._session, payer.id, requested):
                raise NotLinkedParent("a parent can only buy for a linked student")
            beneficiary = self._session.get(User, requested)
            if beneficiary is None or beneficiary.role is not Role.student:
                raise NotLinkedParent("a parent can only buy for a linked student")
            return beneficiary
        if requested is not None and requested != payer.id:
            raise NotLinkedParent("only a linked parent may buy for another account")
        return payer

    def _sellable_tier(
        self, plan_tier_id: uuid.UUID, beneficiary: User, *, now: datetime
    ) -> PlanTier:
        """The tier, when it may be sold to ``beneficiary`` under the configured key mode."""
        tier = self._session.get(PlanTier, plan_tier_id)
        audience = _AUDIENCE_FOR_ROLE.get(beneficiary.role)
        if (
            tier is None
            or audience is None
            or not tier.is_active
            or tier.interval is None
            or tier.paymob_plan_id is None
            or tier.price_minor <= 0
            or tier.audience is not audience
        ):
            raise PlanNotPurchasable("this plan cannot be bought for this account")
        if tier.paymob_plan_mode != self._settings.key_mode:
            self._note_mode_mismatch(tier, now=now)
            raise PlanModeMismatch(_PLAN_MODE_MESSAGE)
        return tier

    def _note_mode_mismatch(self, tier: PlanTier, *, now: datetime) -> None:
        """Log the mismatch; page the operator (``alert=True``) at most once per window and tier."""
        fields = {
            "plan_tier_id": str(tier.id),
            "plan_mode": tier.paymob_plan_mode,
            "key_mode": self._settings.key_mode,
        }
        last = _MODE_ALERTED.get(tier.id)
        if last is not None and last <= now < last + _MODE_ALERT_EVERY:
            log.warning("subscription_plan_mode_mismatch_repeated", **fields)
            return
        _MODE_ALERTED[tier.id] = now
        alerts.error("subscription_plan_mode_mismatch", alert=True, **fields)

    def _require_seats_covered(
        self, teacher_id: uuid.UUID, tier: PlanTier, extra_seats: int
    ) -> None:
        """UD-5: refuse a plan whose seats are fewer than the teacher's active seats.

        Seats the teacher already removed (``leaving``) do not count, so removing students lets
        them subscribe at once instead of at month end. The error carries both numbers so the
        message can say how many to remove.
        """
        in_use = _seats_in_use(self._session, teacher_id)
        capacity = tier.included_seats + extra_seats
        if in_use > capacity:
            raise SeatsInsufficient(in_use=in_use, capacity=capacity)

    def _retire_stale_checkout(
        self, beneficiary_id: uuid.UUID, payer_id: uuid.UUID, *, now: datetime
    ) -> None:
        """Refuse when the beneficiary holds a live plan; expire a checkout a new one may replace.

        The unique index covers only paid-path rows (a manual activation has no payer), so a live
        manual plan is refused here, and the index still guards two racing paid checkouts. A
        pending checkout is replaceable when its newest first payment failed, when it is older
        than ``STALE_CHECKOUT_AFTER``, or when the same payer starts again; a paid one never is
        (its handler is running). All rows are judged before any is changed, so a refusal leaves
        every row as it was. The payment of a superseded checkout stays open: reconcile may still
        settle it, and the first-payment handler deals with a late one.
        """
        live = list(
            self._session.scalars(
                select(Subscription)
                .where(
                    Subscription.user_id == beneficiary_id,
                    Subscription.status.in_(LIVE_SUBSCRIPTION_STATUSES),
                )
                .order_by(Subscription.id)  # a fixed lock order: racing checkouts cannot deadlock
                .with_for_update()
            )
        )
        replaceable = [
            row
            for row in live
            if row.status is SubscriptionStatus.pending_first_payment
            and self._may_replace(row, payer_id, now=now)
        ]
        if len(replaceable) != len(live):
            raise AlreadySubscribed("this account already has a live subscription")
        for pending in replaceable:
            pending.status = SubscriptionStatus.expired
            _bump(pending)
            log.info("subscription_checkout_superseded", subscription_id=str(pending.id))
        self._session.flush()

    def _may_replace(self, pending: Subscription, payer_id: uuid.UUID, *, now: datetime) -> bool:
        """Whether a new checkout by ``payer_id`` may replace the unpaid ``pending`` one.

        A payment that can no longer be paid frees it for anyone; one that still can (open, or
        declined within the intention's lifetime) frees it only for the same payer or once stale.
        """
        first = self._session.scalars(
            select(Payment)
            .where(
                Payment.subscription_id == pending.id,
                Payment.purpose == PaymentPurpose.subscription_first,
            )
            .order_by(Payment.created_at.desc())
            .limit(1)
        ).one_or_none()
        if first is None:
            return True
        if first.status not in (
            PaymentStatus.created,
            PaymentStatus.pending,
            PaymentStatus.failed,
            *_CLOSED_PAYMENT,
        ):
            return False  # paid, refunded: money moved, the activation handler owns it
        return (
            _is_unpayable(first, now=now)
            or first.created_at <= now - STALE_CHECKOUT_AFTER
            or pending.payer_user_id == payer_id
        )

    # -- subscription webhooks (spec §5.2) ---------------------------------------------

    def apply_renewal_webhook(self, body: JsonMap, *, now: datetime) -> None:
        """Apply one HMAC-verified subscription callback, at most once (R26, DV-11).

        The HMAC covers the trigger and the id only, so nothing else in ``body`` is read. Every
        Paymob read comes first with no lock held (``GET subscriptions/{id}``, plus
        ``last-transaction`` for a ``Successful Transaction``); then the subscription is locked,
        the event is stored under a key built from those re-fetched facts, and the handler runs.
        A delivery already processed is a no-op; one stored unprocessed (the plan was not linked
        yet) is applied now. Correctness never rests on the key: each handler is idempotent under
        the subscription lock. An unmatched delivery is stored unprocessed with the remote copy,
        which the first-payment handler and the drift check link later.

        The caller commits. A ``PaymobError`` from a read propagates before any write, so the
        route answers 5xx and Paymob retries.

        Raises:
            MalformedWebhook: no trigger, or no integer subscription id.
            PaymobError: a Paymob read failed.
        """
        trigger, paymob_id = parse_subscription_webhook(body)
        remote = self._client.get_subscription(paymob_id)
        txn: JsonMap | None
        if trigger == TRIGGER_SUCCESS:
            txn = self._client.last_transaction(paymob_id)
        elif trigger in (TRIGGER_FAILED, TRIGGER_OVERDUE):
            txn = self._failure_context(paymob_id)
        else:
            txn = None
        state = RemoteState(remote, txn)
        fingerprint = _fingerprint(trigger, state)
        subscription = self._resolve(paymob_id, remote)
        session = self._session
        event: PaymobEvent | None = None
        if fingerprint is None:
            # Paymob omitted what the key is made of. A placeholder key (``txn:none``,
            # ``active:None``) would swallow every later real delivery, and a random one would
            # dedupe nothing, so nothing is stored: the handler is idempotent under the lock and
            # the drift check is the backstop.
            alerts.error(
                "subscription_webhook_not_deduplicable",
                paymob_subscription_id=paymob_id,
                trigger_type=trigger,
                alert=True,
            )
        else:
            dedupe_key = f"sub:{paymob_id}:{trigger}:{fingerprint}"
            trusted = _strict_int(remote.get("id")) == paymob_id
            payload: dict[str, object] = {
                "body": {"trigger_type": trigger, "subscription_data": {"id": paymob_id}},
                # A copy that names another subscription is not kept where the first-payment
                # linker could act on it.
                "remote": _redact_tokens(remote) if trusted else None,
            }
            event_id = session.execute(
                pg_insert(PaymobEvent)
                .values(kind=PaymobEventKind.subscription, dedupe_key=dedupe_key, payload=payload)
                .on_conflict_do_nothing(index_elements=[PaymobEvent.dedupe_key])
                .returning(PaymobEvent.id)
            ).scalar_one_or_none()
            event = session.scalars(
                select(PaymobEvent)
                .where(PaymobEvent.dedupe_key == dedupe_key)
                .with_for_update()
                .execution_options(populate_existing=True)
            ).one()
            if event_id is None and (event.processed_at is not None or subscription is None):
                log.info("paymob_subscription_webhook_duplicate", trigger_type=trigger)
                return
        if subscription is None:
            log.warning(
                "paymob_subscription_webhook_unmatched",
                paymob_subscription_id=paymob_id,
                trigger_type=trigger,
            )
            return
        handler = self._handlers().get(trigger)
        if handler is not None:
            handler(subscription, state, now)
        if event is not None:
            event.processed_at = now

    def _failure_context(self, paymob_id: int) -> JsonMap | None:
        """Paymob's last charge, read to confirm a failure trigger is not a stale replay.

        Read-only, before any lock. A read that fails (or whose outcome is unknown) is not an
        error: the failure is then judged on the subscription's own period alone.
        """
        try:
            return self._client.last_transaction(paymob_id)
        except PaymobError as exc:
            log.warning(
                "subscription_failure_unconfirmed",
                paymob_subscription_id=paymob_id,
                status_code=exc.status_code,
                outcome_unknown=_outcome_unknown(exc),
            )
            return None

    def _handlers(self) -> dict[str, TriggerHandler]:
        """Trigger to handler.

        A trigger with none (``Subscription Created``, ``updated``, ...) is stored, marked
        processed and answered 200 (DV-29).
        """
        return {
            TRIGGER_SUCCESS: self._on_successful_transaction,
            TRIGGER_FAILED: self._on_failed,
            TRIGGER_OVERDUE: self._on_overdue,
            TRIGGER_CANCELED: self._on_canceled,
            TRIGGER_SUSPENDED: self._on_suspended,
            TRIGGER_RESUMED: self._on_resumed,
        }

    def _resolve(self, paymob_id: int, remote: JsonMap) -> Subscription | None:
        """Our subscription for a Paymob id, locked; linked through its first payment if new.

        ``remote`` must be Paymob's own answer for ``paymob_id``: a copy that names another id is
        unmatched. The transaction-scoped advisory lock on the initial transaction comes first,
        the one the first-payment handler takes, so of the first charge's callback and the
        ``Subscription Created`` webhook the second sees the first's commit (T5-I2). Linking goes
        only through a ``subscription_first`` payment and works for an expired row too: a late
        ``Subscription Created`` for a credits-converted checkout must link, or the extra Paymob
        subscription could never be found and cancelled.
        """
        session = self._session
        if _strict_int(remote.get("id")) != paymob_id:
            log.warning("paymob_subscription_remote_mismatch", paymob_subscription_id=paymob_id)
            return None
        initial = _strict_int(remote.get("initial_transaction"))
        if initial is not None and not 0 < initial <= _MAX_PAYMOB_INT:
            initial = None
        if initial is not None:
            lock_paymob_transaction(session, initial)
        linked_id = session.scalar(
            select(Subscription.id).where(Subscription.paymob_subscription_id == paymob_id)
        )
        if linked_id is not None:
            return _lock_subscriptions(session, linked_id)
        if initial is None:
            return None
        payment = session.scalars(
            select(Payment).where(
                Payment.paymob_txn_id == initial,
                Payment.purpose == PaymentPurpose.subscription_first,
            )
        ).one_or_none()
        if payment is None or payment.subscription_id is None:
            return None
        subscription = _lock_subscriptions(session, payment.subscription_id)
        if subscription is None:
            return None
        if subscription.paymob_subscription_id is None:
            subscription.paymob_subscription_id = paymob_id
            _bump(subscription)
            session.flush()
            log.info(
                "paymob_subscription_linked",
                subscription_id=str(subscription.id),
                paymob_subscription_id=paymob_id,
            )
        elif subscription.paymob_subscription_id != paymob_id:
            alerts.error(
                "subscription_link_conflict",
                subscription_id=str(subscription.id),
                paymob_subscription_id=paymob_id,
                alert=True,
            )
            return None
        return subscription

    def _on_successful_transaction(
        self, subscription: Subscription, state: RemoteState, now: datetime
    ) -> None:
        txn = state.last_transaction
        if txn is None:
            log.warning("subscription_success_without_charge", subscription_id=str(subscription.id))
            return
        self._apply_successful_charge(
            subscription,
            txn,
            now=now,
            initial_transaction=_strict_int(state.subscription.get("initial_transaction")),
        )

    def _apply_successful_charge(
        self,
        subscription: Subscription,
        txn: JsonMap,
        *,
        now: datetime,
        initial_transaction: int | None = None,
    ) -> bool:
        """Record one renewal charge and grant its period. ``True`` when a period was granted.

        The one acceptance rule of renewals (DV-12); the drift check calls it too. Nothing is
        written for a charge that cannot be read (alert), that is not a success, that is Paymob's
        initial transaction (the first payment's, whatever the order of its callback), or that is
        already recorded. A charge that names an integration other than MOTO is refused (alert).
        The charge is accepted only in the subscription's own currency and for the amount Lemely
        last set at Paymob or the one it expects next: any other amount is stored
        ``failed_mismatch`` with no grant. Pending tier and seat changes apply only when
        the charge is the expected (new) amount, so a failed price update never grants the new
        tier for the old price. A charge on an ended plan is handled by :func:`_settle_renewal`.
        The caller holds the subscription lock and commits.
        """
        session = self._session
        txn_id = _strict_int(txn.get("id"))
        amount = _strict_int(txn.get("amount_cents"))
        currency = txn.get("currency")
        if (
            txn_id is None
            or not 0 < txn_id <= _MAX_PAYMOB_INT
            or amount is None
            or not 0 < amount <= _MAX_PAYMOB_INT
            or not isinstance(currency, str)
            or len(currency) != 3
        ):
            alerts.error(
                "subscription_last_transaction_unreadable",
                subscription_id=str(subscription.id),
                alert=True,
            )
            return False
        if not is_successful_charge(txn):
            log.info("subscription_last_transaction_not_successful", txn_id=txn_id)
            return False
        if txn_id == initial_transaction:
            log.info("subscription_charge_is_initial_transaction", txn_id=txn_id)
            return False
        charged_on = _as_int(txn.get("integration_id"))  # Phase 02 reads "123" as 123 too
        moto = self._settings.moto_integration_id
        if charged_on is not None and moto is not None and charged_on != moto:
            # Plans are created on the MOTO integration, so a renewal on another one is not ours
            # to settle (audit I1): nothing is written and an operator looks at it.
            alerts.error(
                "paymob_unexpected_integration",
                path="subscription_webhook",
                subscription_id=str(subscription.id),
                txn_id=txn_id,
                integration_id=str(charged_on)[:20],
                alert=True,
            )
            return False
        if session.scalar(select(Payment.id).where(Payment.paymob_txn_id == txn_id)) is not None:
            return False
        if subscription.payer_user_id is None:
            alerts.error(
                "subscription_renewal_without_payer",
                subscription_id=str(subscription.id),
                alert=True,
            )
            return False
        charged_at = parse_paymob_time(txn.get("created_at"))
        if charged_at is None:
            log.warning("subscription_charge_time_unreadable", txn_id=txn_id)
            charged_at = now
        elif charged_at > now:
            # A skewed or mis-zoned stamp (UD-8, S13): never start a period or an allowance in
            # the future.
            log.warning("subscription_charge_time_in_future", txn_id=txn_id)
            charged_at = now
        current_tier = session.get(PlanTier, subscription.plan_tier_id)
        expected = self.next_renewal_amount(subscription)
        accepted = {expected}
        if subscription.paymob_amount_minor is not None:
            accepted.add(subscription.paymob_amount_minor)
        mismatch = (
            current_tier is None or currency != current_tier.currency or amount not in accepted
        )
        tier, seats = _period_terms(session, subscription, with_pending=amount == expected)
        payment = Payment(
            id=uuid.uuid4(),
            special_reference=f"subscription-renewal:{txn_id}",
            payer_user_id=subscription.payer_user_id,
            beneficiary_user_id=subscription.user_id,
            purpose=PaymentPurpose.subscription_renewal,
            plan_tier_id=tier.id,
            subscription_id=subscription.id,
            seat_quantity=seats or None,  # the CHECK forbids 0
            amount_minor=amount,
            currency=currency,
            status=PaymentStatus.failed_mismatch if mismatch else PaymentStatus.paid,
            paymob_order_id=self._free_order_id(txn),
            paymob_txn_id=txn_id,
            method="card",
            last_callback=_redact_tokens(txn),
            paid_at=None if mismatch else charged_at,
        )
        session.add(payment)
        session.flush()
        if mismatch:
            alerts.error(
                "subscription_renewal_mismatch",
                subscription_id=str(subscription.id),
                payment_id=str(payment.id),
                expected_minor=expected,
                stamped_minor=subscription.paymob_amount_minor,
                received_minor=amount,
                currency=currency,
                alert=True,
            )
            return False
        return _settle_renewal(
            session,
            subscription,
            payment,
            charged_at=charged_at,
            now=now,
            amount_updatable=self._settings.subscription_amount_updatable,
        )

    # -- grace and expiry (spec §2.6, §5.2) --------------------------------------------

    def mark_past_due(self, subscription_id: uuid.UUID, *, now: datetime) -> Subscription:
        """A renewal failed: ``past_due`` with ``grace_until = now + GRACE_PERIOD``.

        A subscription that is not ``active`` is returned unchanged (see :meth:`_mark_past_due`).
        The caller commits.

        Raises:
            SubscriptionNotFound: no such subscription.
        """
        subscription = self._lock(subscription_id)
        self._mark_past_due(subscription, now=now)
        return subscription

    def expire_overdue(self, *, now: datetime, limit: int = SUBSCRIPTION_SWEEP_BATCH) -> int:
        """Expire ``past_due`` subscriptions whose grace has elapsed, and cancel them at Paymob.

        Takes at most ``limit`` rows, oldest ``grace_until`` first; the rest wait for the next
        pass. Each row is its own transaction (:meth:`_sweep_one`), so one Paymob failure cannot
        undo another row's expiry. Returns how many rows were expired. The session must hold no
        uncommitted work: every row commits.

        Raises:
            ValueError: ``limit`` is below 1.
        """
        if limit < 1:
            raise ValueError("limit must be at least 1")
        ids = self._session.scalars(
            select(Subscription.id)
            .where(
                Subscription.status == SubscriptionStatus.past_due,
                Subscription.grace_until <= now,
                # Complimentary rows have no Paymob link; Phase 07 ends those (index R15).
                Subscription.paymob_subscription_id.is_not(None),
            )
            .order_by(Subscription.grace_until, Subscription.id)
            .limit(limit)
        ).all()
        return sum(self._sweep_one(sid, self._expire_if_due, now) for sid in ids)

    # -- plan changes (spec §5.3) ------------------------------------------------------

    def schedule_downgrade(
        self,
        subscription_id: uuid.UUID,
        *,
        actor_user_id: uuid.UUID,
        plan_tier_id: uuid.UUID,
        now: datetime,
    ) -> Subscription:
        """Switch to a cheaper tier at the next renewal. The current tier clears a pending one.

        Nothing is sent to Paymob: the amount sweep (:meth:`apply_period_end_changes`) pushes the
        lower amount, and the renewal applies the tier. The caller commits.

        Raises:
            SubscriptionNotFound: unknown subscription, or the actor is not its payer (the two
                are indistinguishable).
            InvalidPlanChange: not an active card subscription, a cancel is scheduled, or the
                target is not an active, cheaper tier of the same audience, interval and
                currency, or it sells no extra seats while some are held.
            SeatsInsufficient: a teacher tier whose seats the seated students would not fit
                (UD-5: active, non-leaving seats only).
            DowngradeUnavailable: ``subscription_amount_updatable`` is ``False``.
        """
        del now
        subscription = self._payer_lock(subscription_id, actor_user_id)
        if (
            subscription.status is not SubscriptionStatus.active
            or subscription.is_manually_activated
        ):
            raise InvalidPlanChange("only an active card subscription can change plan")
        if subscription.cancel_at_period_end:
            raise InvalidPlanChange("this subscription is cancelled at period end")
        if plan_tier_id == subscription.plan_tier_id:
            if subscription.pending_plan_tier_id is not None:
                subscription.pending_plan_tier_id = None
                _bump(subscription)
            return subscription
        if not self._settings.subscription_amount_updatable:
            # Paymob cannot lower the amount, so the plan would keep renewing at the old price.
            # Clearing (above) and cancelling stay available.
            raise DowngradeUnavailable(
                "Plan downgrades are not available for this subscription yet."
            )
        current = self._session.get(PlanTier, subscription.plan_tier_id)
        target = self._session.get(PlanTier, plan_tier_id)
        if (
            current is None
            or target is None
            or not target.is_active
            or target.audience is not current.audience
            or target.interval is not current.interval
            or target.currency != current.currency
        ):
            raise InvalidPlanChange("choose an active plan for the same audience and interval")
        if target.price_minor >= current.price_minor:
            raise InvalidPlanChange("not a downgrade; upgrades apply immediately")
        extra = (
            subscription.pending_extra_seats
            if subscription.pending_extra_seats is not None
            else subscription.extra_seats or 0
        )
        if extra and target.extra_seat_price_minor == 0:
            raise InvalidPlanChange("the new plan has no extra seats; remove them first")
        if current.audience is PlanAudience.teacher:
            capacity = seat_capacity_for(included_seats=target.included_seats, extra_seats=extra)
            in_use = _seats_in_use(self._session, subscription.user_id)
            if in_use > capacity:
                raise SeatsInsufficient(in_use=in_use, capacity=capacity)
        subscription.pending_plan_tier_id = target.id
        _bump(subscription)
        return subscription

    def schedule_cancel(
        self, subscription_id: uuid.UUID, *, actor_user_id: uuid.UUID | None, now: datetime
    ) -> Subscription:
        """Cancel at period end; access continues until then (spec §5.3).

        Nothing is sent to Paymob: the sweep pushes the cancel and ends the plan at its period
        end. ``actor_user_id=None`` is the system (the fixed-amount terms move); anyone else must
        be the payer. The caller commits.

        Raises:
            SubscriptionNotFound: unknown subscription, or the actor is not its payer.
            InvalidPlanChange: nothing live to cancel, or a manual activation.
        """
        del now
        subscription = self._payer_lock(subscription_id, actor_user_id)
        if subscription.status not in PLAN_LIVE_STATUSES or subscription.is_manually_activated:
            raise InvalidPlanChange("there is no live card subscription to cancel")
        if (
            not subscription.cancel_at_period_end
            or subscription.pending_plan_tier_id is not None
            or subscription.suspended_at is not None
        ):
            subscription.cancel_at_period_end = True
            subscription.pending_plan_tier_id = None
            # The payer now asks for this cancel too, so a resume no longer undoes it.
            subscription.suspended_at = None
            _bump(subscription)
        return subscription

    def _payer_lock(
        self, subscription_id: uuid.UUID, actor_user_id: uuid.UUID | None
    ) -> Subscription:
        """Lock a subscription the actor pays for; a stranger sees "unknown" (no IDOR oracle)."""
        subscription = self._lock(subscription_id)
        if actor_user_id is not None and subscription.payer_user_id != actor_user_id:
            raise SubscriptionNotFound(f"unknown subscription {subscription_id}")
        return subscription

    def next_renewal_amount(self, subscription: Subscription) -> int:
        """What Paymob will charge at the next renewal, pending changes included (index R6).

        The single source of the expected renewal amount: the amount sweep, the renewal
        acceptance (DV-12) and the drift check all use it. On the fixed-amount fallback path it
        is the stamped amount (:func:`expected_renewal_amount_minor`).
        """
        return _expected_renewal_amount(
            self._session,
            subscription,
            amount_updatable=self._settings.subscription_amount_updatable,
        )

    def sync_renewal_amount(self, subscription: Subscription) -> bool:
        """PUT :meth:`next_renewal_amount` to Paymob if it differs from the stamp; ``True`` if sent.

        The one way any phase changes a Paymob subscription amount (index R6). Stamps
        ``paymob_amount_minor`` in the caller's transaction on success. Nothing is sent without a
        Paymob link, when nothing changed, or on the fixed-amount fallback path (Paymob cannot
        change the amount there). An unknown outcome (timeout, transport, 5xx) leaves the stamp
        alone and returns ``False``: the PUT is idempotent and the next pass repeats it, while a
        stamp claiming a PUT that may not have landed would hide the difference for good.

        Raises:
            PaymobError: a definite refusal; the stamp is unchanged and the sweep rolls the row
                back and alerts.
        """
        paymob_id = subscription.paymob_subscription_id
        if paymob_id is None or not self._settings.subscription_amount_updatable:
            return False
        expected = self.next_renewal_amount(subscription)
        if expected == subscription.paymob_amount_minor:
            return False
        try:
            self._client.update_subscription(paymob_id, amount_cents=expected)
        except PaymobError as exc:
            status = exc.status_code
            if not (exc.outcome_unknown or status is None or not 400 <= status < 500):
                raise
            log.warning(
                "paymob_amount_put_unknown",
                subscription_id=str(subscription.id),
                amount_minor=expected,
                exc_info=True,
            )
            return False
        subscription.paymob_amount_minor = expected
        _bump(subscription)
        log.info(
            "paymob_subscription_amount_set",
            subscription_id=str(subscription.id),
            amount_minor=expected,
        )
        return True

    def apply_period_end_changes(
        self, *, now: datetime, limit: int = SUBSCRIPTION_SWEEP_BATCH
    ) -> int:
        """Push amounts and cancels to Paymob, and end cancelled plans at their period end.

        Four candidate sets, each bounded to ``limit`` rows and each row its own skip-locked
        transaction (:meth:`_sweep_one`); returns how many rows changed. The session must hold no
        uncommitted work.

        * **Amount** (DV-16): an active, linked, not-cancelling row with a pending tier or seat
          change, no stamp, or a renewal within ``AMOUNT_SYNC_WINDOW`` (which repairs a stamp
          left behind by a cleared change), read without a lock and pushed only when
          ``next_renewal_amount`` differs from the stamp.
        * **Cancel, live** (DV-15): a live cancel-at-period-end row Paymob has not cancelled yet.
        * **Cancel, ended** (DV-15 fourth set, DV-27): an ``expired`` or ``cancelled`` linked row
          with no cancel stamp. This is the only retry of a cancel that failed at expiry and the
          only cancel for a row an overdue webhook expired or a credits-converted checkout.
          Rows with no period (``NULL`` end) go first.
        * **End**: a live cancel-at-period-end row whose period is over becomes ``cancelled`` and
          the payer gets the ``cancelled`` notice.

        Raises:
            ValueError: ``limit`` is below 1.
        """
        if limit < 1:
            raise ValueError("limit must be at least 1")
        S = Subscription
        linked = S.paymob_subscription_id.is_not(None)  # complimentary rows: Phase 07 (R15)
        amount_ids = self._amount_candidates(now, limit)
        cancel_live = self._session.scalars(
            select(S.id)
            .where(
                S.status.in_(PLAN_LIVE_STATUSES),
                S.cancel_at_period_end.is_(True),
                linked,
                S.paymob_cancelled_at.is_(None),
            )
            .order_by(S.current_period_end.asc().nulls_first(), S.id)
            .limit(limit)
        ).all()
        cancel_ended = self._session.scalars(
            select(S.id)
            .where(
                S.status.in_((SubscriptionStatus.expired, SubscriptionStatus.cancelled)),
                linked,
                S.paymob_cancelled_at.is_(None),
            )
            .order_by(S.current_period_end.asc().nulls_first(), S.id)
            .limit(limit)
        ).all()
        end_ids = self._session.scalars(
            select(S.id)
            .where(
                S.status.in_(PLAN_LIVE_STATUSES),
                S.cancel_at_period_end.is_(True),
                S.current_period_end <= now,
                linked,
            )
            .order_by(S.current_period_end, S.id)
            .limit(limit)
        ).all()
        changed = sum(self._sweep_one(sid, self._push_amount, now) for sid in amount_ids)
        changed += sum(self._sweep_one(sid, self._push_cancel, now) for sid in cancel_live)
        changed += sum(self._sweep_one(sid, self._push_cancel, now) for sid in cancel_ended)
        changed += sum(self._sweep_one(sid, self._end_cancelled, now) for sid in end_ids)
        return changed

    def _amount_candidates(self, now: datetime, limit: int) -> list[uuid.UUID]:
        """Ids of rows whose Paymob amount may be stale (DV-16), oldest renewal first."""
        S = Subscription
        rows = self._session.scalars(
            select(S)
            .where(
                S.status == SubscriptionStatus.active,
                S.paymob_subscription_id.is_not(None),
                S.cancel_at_period_end.is_(False),
                sa.or_(
                    S.pending_plan_tier_id.is_not(None),
                    S.pending_extra_seats.is_not(None),
                    S.paymob_amount_minor.is_(None),
                    S.current_period_end <= now + AMOUNT_SYNC_WINDOW,
                ),
            )
            .order_by(S.current_period_end, S.id)
            .limit(limit)
        ).all()
        return [row.id for row in rows if self.next_renewal_amount(row) != row.paymob_amount_minor]

    def _push_amount(self, subscription: Subscription, now: datetime) -> bool:
        """Sweep step: PUT the amount of a row that is still an active, linked plan."""
        del now
        if (
            subscription.status is not SubscriptionStatus.active
            or subscription.cancel_at_period_end
            or subscription.paymob_subscription_id is None
        ):
            return False
        return self.sync_renewal_amount(subscription)

    def _push_cancel(self, subscription: Subscription, now: datetime) -> bool:
        """Sweep step: cancel the Paymob subscription (a refusal or unknown outcome is retried)."""
        return self._cancel_at_paymob(subscription, now=now)

    def _end_cancelled(self, subscription: Subscription, now: datetime) -> bool:
        """Sweep step: end a cancel-at-period-end plan whose period is over, re-checked locked."""
        if (
            not subscription.cancel_at_period_end
            or subscription.status not in PLAN_LIVE_STATUSES
            or subscription.paymob_subscription_id is None
            or subscription.current_period_end is None
            or subscription.current_period_end > now
        ):
            return False
        subscription.status = SubscriptionStatus.cancelled
        subscription.grace_until = None
        _bump(subscription)
        # Past tense, so it goes out now and names the stored period end (UD-4 (b)).
        enqueue_subscription_notice(
            self._session,
            subscription=subscription,
            notice="cancelled",
            effective_at=subscription.current_period_end,
        )
        log.info("subscription_cancelled_at_period_end", subscription_id=str(subscription.id))
        return True

    def _lock(self, subscription_id: uuid.UUID) -> Subscription:
        """The subscription, locked and re-read, or :class:`SubscriptionNotFound`."""
        subscription = self._session.scalars(
            select(Subscription)
            .where(Subscription.id == subscription_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).one_or_none()
        if subscription is None:
            raise SubscriptionNotFound(f"unknown subscription {subscription_id}")
        return subscription

    def _lock_for_sweep(self, subscription_id: uuid.UUID) -> Subscription | None:
        """Lock one subscription for a sweep, or ``None`` when it is gone or another holds it.

        ``FOR UPDATE SKIP LOCKED``: a row a webhook, a checkout or another replica's sweep is
        working on is left to them, and the sweep never waits on it (DV-15).
        """
        return self._session.scalars(
            select(Subscription)
            .where(Subscription.id == subscription_id)
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        ).one_or_none()

    def _sweep_one(
        self,
        subscription_id: uuid.UUID,
        step: Callable[[Subscription, datetime], bool],
        now: datetime,
    ) -> int:
        """Lock, apply ``step`` to and commit one subscription: ``1`` when it changed, else ``0``.

        A row that is missing or held is skipped and counted as nothing. Any failure rolls back
        this row only and is alerted with the id and the exception type, never its message (a
        Paymob error body can carry account data).
        """
        try:
            subscription = self._lock_for_sweep(subscription_id)
            changed = subscription is not None and step(subscription, now)
            self._session.commit()
        except Exception as exc:
            self._session.rollback()
            alerts.error(
                "subscription_sweep_failed",
                subscription_id=str(subscription_id),
                error=type(exc).__name__,
                alert=True,
            )
            return 0
        return int(changed)

    def _expire_if_due(self, subscription: Subscription, now: datetime) -> bool:
        """Sweep step: expire a ``past_due`` row whose grace has elapsed, re-checked under lock."""
        if (
            subscription.status is not SubscriptionStatus.past_due
            or subscription.grace_until is None
            or subscription.grace_until > now
            or subscription.paymob_subscription_id is None
        ):
            return False
        self._expire(subscription, now=now, push_cancel=True)
        return True

    def _mark_past_due(self, subscription: Subscription, *, now: datetime) -> None:
        """Start the grace period of an ``active`` plan, once.

        Only from ``active``: Paymob retries a failed charge and every retry that fails calls
        this again, and none of them may move the first deadline. The expiring period's leftover
        allowance stays usable until the deadline (UD-1 (b)).
        """
        if subscription.status is not SubscriptionStatus.active:
            return
        grace_until = now + GRACE_PERIOD
        subscription.status = SubscriptionStatus.past_due
        subscription.grace_until = grace_until
        _bump(subscription)
        _extend_period_grants(self._session, subscription, until=grace_until, now=now)
        enqueue_subscription_notice(
            self._session,
            subscription=subscription,
            notice="payment_failed",
            effective_at=grace_until,
        )
        log.info("subscription_past_due", subscription_id=str(subscription.id))

    def _expire(self, subscription: Subscription, *, now: datetime, push_cancel: bool) -> None:
        """Lapse the plan: no new allowance and no new seat allowances (spec §5.2).

        ``push_cancel`` also cancels the Paymob subscription. Only the sweeps pass ``True``: the
        webhook transaction holds the row lock and never calls Paymob (DV-15), and the sweeps
        pick up an expired row whose cancel was never stamped.
        """
        subscription.status = SubscriptionStatus.expired
        # The notice names the date the plan actually ended: the stored deadline when the sweep
        # got to it after the grace, today when Paymob gave up before it.
        deadline = min(subscription.grace_until or subscription.current_period_end or now, now)
        _end_period_grants(
            self._session, subscription, now=now, period_end=subscription.current_period_end
        )
        subscription.grace_until = None
        _bump(subscription)
        enqueue_subscription_notice(
            self._session, subscription=subscription, notice="expired", effective_at=deadline
        )
        if push_cancel:
            self._cancel_at_paymob(subscription, now=now)
        log.info("subscription_expired", subscription_id=str(subscription.id))

    def _cancel_at_paymob(self, subscription: Subscription, *, now: datetime) -> bool:
        """Cancel the Paymob subscription once and stamp ``paymob_cancelled_at``.

        ``True`` when the row is stamped. A refusal (4xx) is read back: Paymob already reporting
        ``canceled`` stamps the row (it stops being retried), anything else is alerted. An
        unknown outcome (timeout, transport failure, 5xx) leaves the row unstamped; a cancel is
        idempotent at Paymob. This module does not retry it: ``expire_overdue`` selects only
        ``past_due`` rows, so the retry is the period-end sweep's candidate set of ``expired`` and
        ``cancelled`` rows that are Paymob-linked with ``paymob_cancelled_at IS NULL`` (DV-15),
        which also covers rows a ``Failed Overdue Transaction`` expired without a cancel.
        """
        paymob_id = subscription.paymob_subscription_id
        if paymob_id is None or subscription.paymob_cancelled_at is not None:
            return False
        try:
            self._client.cancel_subscription(paymob_id)
        except PaymobError as exc:
            status = exc.status_code
            if exc.outcome_unknown or status is None or not 400 <= status < 500:
                log.warning(
                    "paymob_cancel_failed", subscription_id=str(subscription.id), exc_info=True
                )
                return False
            return self._stamp_if_already_cancelled(subscription, now=now, status_code=status)
        subscription.paymob_cancelled_at = now
        return True

    def _stamp_if_already_cancelled(
        self, subscription: Subscription, *, now: datetime, status_code: int
    ) -> bool:
        """After a refused cancel: stamp the row when Paymob says the subscription is gone.

        Two 404s (the cancel and the read-back) also stamp the row and alert
        ``subscription_paymob_missing``. A wrong API key or base URL gives the same pair, so a
        burst of these alerts means a configuration fault, not many deleted subscriptions.
        """
        paymob_id = subscription.paymob_subscription_id
        assert paymob_id is not None  # noqa: S101 - the caller checked
        try:
            remote = self._client.get_subscription(paymob_id)
        except PaymobError as exc:
            if status_code == 404 and exc.status_code == 404:
                # Paymob has no such subscription any more: nothing is left to cancel. Stamping
                # stops the retries; the alert is for whoever has to find out why it is gone.
                alerts.error(
                    "subscription_paymob_missing",
                    subscription_id=str(subscription.id),
                    paymob_subscription_id=paymob_id,
                    alert=True,
                )
                subscription.paymob_cancelled_at = now
                return True
            log.warning("paymob_cancel_failed", subscription_id=str(subscription.id), exc_info=True)
            return False
        if remote.get("state") == "canceled":
            subscription.paymob_cancelled_at = now
            return True
        alerts.error(
            "paymob_cancel_refused",
            subscription_id=str(subscription.id),
            status_code=status_code,
            remote_state=str(remote.get("state"))[:30],
            alert=True,
        )
        return False

    # -- mirrored Paymob states (spec §5.2) --------------------------------------------

    def _disagrees(
        self, subscription: Subscription, remote: RemoteState, *, trigger: str, expected: str
    ) -> bool:
        """Whether Paymob's own state contradicts the trigger (logged): the trigger is ignored."""
        state = remote.subscription.get("state")
        if state == expected:
            return False
        log.warning(
            "paymob_state_disagrees",
            subscription_id=str(subscription.id),
            trigger_type=trigger,
            state=state if isinstance(state, str) else None,
        )
        return True

    def _stale_failure(
        self, subscription: Subscription, remote: RemoteState, *, trigger: str, now: datetime
    ) -> bool:
        """Whether a failure trigger belongs to a renewal that was already paid (logged).

        The HMAC signs no timestamp, and Paymob redelivers after a 5xx, so a failure can arrive
        after the retry that paid. Judged on the subscription's own state: a period running
        further ahead than the early-charge window is paid. Inside that window the charge Paymob
        itself reports is the tie-break: a successful last charge means no failure is open.
        """
        end = subscription.current_period_end
        if end is not None and end > now + EARLY_CHARGE_WINDOW:
            reason = "period_already_paid"
        elif self._confirms_payment(subscription, remote):
            reason = "last_charge_succeeded"
        else:
            return False
        log.warning(
            "subscription_stale_failure_ignored",
            subscription_id=str(subscription.id),
            trigger_type=trigger,
            reason=reason,
        )
        return True

    def _confirms_payment(self, subscription: Subscription, remote: RemoteState) -> bool:
        """Whether Paymob's last charge is a payment this subscription has not recorded yet.

        ``last-transaction`` can return an older success (the first payment, or the charge that
        paid the current period) when the declined attempt left nothing newer, so a success counts
        only if it is not Paymob's ``initial_transaction``, is not already recorded as a payment,
        and is newer than every payment already recorded (or, with none, the period start). Any
        other success proves nothing: the failure then stands.
        """
        txn = remote.last_transaction
        if txn is None or not is_successful_charge(txn):
            return False
        txn_id = _strict_int(txn.get("id"))
        if txn_id is None or txn_id == _strict_int(remote.subscription.get("initial_transaction")):
            return False
        session = self._session
        if session.scalar(select(Payment.id).where(Payment.paymob_txn_id == txn_id)) is not None:
            return False
        charged_at = parse_paymob_time(txn.get("created_at"))
        if charged_at is None:
            return False
        floor = (
            session.scalar(
                select(sa.func.max(Payment.paid_at)).where(
                    Payment.subscription_id == subscription.id, Payment.status == PaymentStatus.paid
                )
            )
            or subscription.current_period_start
        )
        return floor is None or charged_at > floor

    def _on_failed(self, subscription: Subscription, remote: RemoteState, now: datetime) -> None:
        if self._stale_failure(subscription, remote, trigger=TRIGGER_FAILED, now=now):
            return
        self._mark_past_due(subscription, now=now)

    def _on_overdue(self, subscription: Subscription, remote: RemoteState, now: datetime) -> None:
        """Paymob gave up charging: expire at once, but never write to Paymob from here (DV-15)."""
        if self._stale_failure(subscription, remote, trigger=TRIGGER_OVERDUE, now=now):
            return
        if subscription.status in PLAN_LIVE_STATUSES:
            self._expire(subscription, now=now, push_cancel=False)

    def _on_canceled(self, subscription: Subscription, remote: RemoteState, now: datetime) -> None:
        """Paymob reports the subscription cancelled: cancel at period end (UD-4 (b)).

        Whether Lemely's own cancel or someone's in Paymob's dashboard, the paid period is kept
        and the period-end sweep ends it. A pending plan change can no longer apply, so it is
        dropped. No notice is queued here: "cancelled" is past tense and goes out when the
        period ends.
        """
        if self._disagrees(subscription, remote, trigger=TRIGGER_CANCELED, expected="canceled"):
            return
        changed = subscription.paymob_cancelled_at is None
        if changed:
            subscription.paymob_cancelled_at = now
        if subscription.suspended_at is not None:
            subscription.suspended_at = None  # a cancel is a cancel, whatever suspended it first
            changed = True
        if subscription.status in PLAN_LIVE_STATUSES and not subscription.cancel_at_period_end:
            subscription.cancel_at_period_end = True
            subscription.pending_plan_tier_id = None
            changed = True
            log.info("subscription_cancelled_in_paymob", subscription_id=str(subscription.id))
        if changed:
            _bump(subscription)

    def _on_suspended(self, subscription: Subscription, remote: RemoteState, now: datetime) -> None:
        """Paymob reports the subscription suspended: treat it as a cancel at period end.

        The period-end sweep would otherwise expire the row and push a permanent Paymob cancel
        for a plan that was only suspended, and tell the payer nothing. As a cancel, the paid
        period is kept, the sweep pushes the cancel and ends the plan at its period end with the
        ``cancelled`` notice. A pending plan change can no longer apply, so it is dropped.

        ``suspended_at`` marks a cancel that this suspension caused, so a ``resumed`` callback can
        undo that cancel and no other: a cancel the payer already asked for is left as it is and
        carries no marker (:meth:`_on_resumed`).
        """
        if self._disagrees(subscription, remote, trigger=TRIGGER_SUSPENDED, expected="suspended"):
            return
        if subscription.status is not SubscriptionStatus.active:
            return
        if subscription.cancel_at_period_end:
            return
        subscription.cancel_at_period_end = True
        subscription.suspended_at = now
        subscription.pending_plan_tier_id = None
        _bump(subscription)
        log.info("subscription_suspended_in_paymob", subscription_id=str(subscription.id))

    def _on_resumed(self, subscription: Subscription, remote: RemoteState, now: datetime) -> None:
        """Paymob reports the subscription resumed: undo the cancel its suspension caused.

        Paymob bills again after a resume, so a plan Lemely still ends at period end would be
        charged and ended. The undo applies only to a cancel marked by :meth:`_on_suspended`
        (``suspended_at``), and only while the Paymob cancel has not been pushed
        (``paymob_cancelled_at`` is ``NULL``) and the plan is still live. A cancel the payer
        asked for is never undone. When the Paymob cancel was already pushed (or the plan ended)
        the resume cannot be honoured: that is alerted ``subscription_resumed_after_cancel`` and
        the row stays ended. A grace that a failed charge started is not a suspension either, and
        only a paid renewal ends it.
        """
        del now
        if self._disagrees(subscription, remote, trigger=TRIGGER_RESUMED, expected="active"):
            return
        if subscription.suspended_at is None:
            log.info("subscription_resume_ignored", subscription_id=str(subscription.id))
            return
        if (
            subscription.paymob_cancelled_at is not None
            or subscription.status not in PLAN_LIVE_STATUSES
        ):
            alerts.error(
                "subscription_resumed_after_cancel",
                subscription_id=str(subscription.id),
                status=subscription.status.value,
                alert=True,
            )
            return
        subscription.cancel_at_period_end = False
        subscription.suspended_at = None
        _bump(subscription)
        log.info("subscription_resumed_in_paymob", subscription_id=str(subscription.id))

    def _free_order_id(self, txn: JsonMap) -> int | None:
        """The charge's Paymob order id, unless another payment already holds it (DV-14).

        The docs show ``order`` as a bare integer and as an object; a renewal payment that stores
        it lets a later refund or void callback find the payment by its signed order id. The
        column is unique, so an id that is taken is left out rather than failing the renewal.
        """
        order = txn.get("order")
        order_id = _strict_int(order.get("id") if isinstance(order, Mapping) else order)
        if order_id is None or not 0 < order_id <= _MAX_PAYMOB_INT:
            return None
        taken = self._session.scalar(select(Payment.id).where(Payment.paymob_order_id == order_id))
        return None if taken is not None else order_id


def _is_unpayable(payment: Payment, *, now: datetime) -> bool:
    """Whether a first payment can never become ``paid`` (so its checkout is free to replace).

    ``failed_mismatch`` and ``voided`` are closed. A ``failed`` one is dead only when Paymob
    rejected the intention (``create_intention``: no intention exists) or when the intention's
    lifetime has passed. After a card decline the Unified Checkout page stays open for an hour and
    Phase 02 lets that payment become ``paid`` on a later success (R20b), so replacing it
    meanwhile would put a paid first payment on an expired subscription.
    """
    if payment.status in _CLOSED_PAYMENT:
        return True
    if payment.status is not PaymentStatus.failed:
        return False
    if (payment.last_callback or {}).get("source") == _NO_INTENTION_SOURCE:
        return True
    return payment.created_at <= now - _INTENTION_LIFETIME


def _fingerprint(trigger: str, state: RemoteState) -> str | None:
    """The part of a webhook's dedupe key that comes from Paymob's own answers, never the body.

    A success is the charge it carries; anything else is the subscription's remote state and
    last-update stamp, so a replayed signature maps to one key (DV-11). ``None`` when Paymob left
    out what the key is made of: a placeholder would collapse distinct later events into one.
    """
    if trigger == TRIGGER_SUCCESS:
        txn_id = _strict_int(state.last_transaction.get("id")) if state.last_transaction else None
        return f"txn:{txn_id}" if txn_id is not None else None
    remote = state.subscription
    remote_state, updated_at = remote.get("state"), remote.get("updated_at")
    if not (isinstance(remote_state, str) and remote_state):
        return None
    if not (isinstance(updated_at, str) and updated_at):
        return None
    return f"{remote_state}:{updated_at}"[:100]


def _violates_one_live(exc: IntegrityError) -> bool:
    """Whether ``exc`` is the one-live-subscription-per-user unique index (not any other error)."""
    diag = getattr(exc.orig, "diag", None)
    return getattr(diag, "constraint_name", None) == _ONE_LIVE_INDEX


__all__ = [
    "SUBSCRIPTION_SWEEP_BATCH",
    "SUBSCRIPTION_WEBHOOK_PATH",
    "TRIGGER_CANCELED",
    "TRIGGER_CREATED",
    "TRIGGER_FAILED",
    "TRIGGER_OVERDUE",
    "TRIGGER_RESUMED",
    "TRIGGER_SUCCESS",
    "TRIGGER_SUSPENDED",
    "AlreadySubscribed",
    "DowngradeUnavailable",
    "InvalidExtraSeats",
    "InvalidPlanChange",
    "MalformedWebhook",
    "NoCreditRate",
    "NotLinkedParent",
    "PlanModeMismatch",
    "PlanNotPurchasable",
    "PlanSyncFailed",
    "RemoteState",
    "SeatsInsufficient",
    "SubscriptionCheckout",
    "SubscriptionError",
    "SubscriptionNotFound",
    "SubscriptionService",
    "TriggerHandler",
    "convert_payment_to_credits",
    "credit_units_for_amount",
    "handle_subscription_first",
    "handle_subscription_renewal",
    "lock_paymob_transaction",
    "parse_subscription_webhook",
    "subscription_webhook_url",
    "sync_paymob_plan",
]

# Registered at import, so any process that settles a payment reaches the handler. The reconcile
# sweeper gets there through ``lemely/web/billing_jobs.py``, which Task 11 makes import this module
# (DV-10): until then only a process that imported it has the handler.
register_paid_handler(PaymentPurpose.subscription_first, handle_subscription_first)
register_paid_handler(PaymentPurpose.subscription_renewal, handle_subscription_renewal)
