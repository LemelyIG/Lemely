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
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, ClassVar, Final

import sqlalchemy as sa
import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError

from lemely.core.subscription_rules import (
    MAX_EXTRA_SEATS_AT_CHECKOUT,
    PAYMOB_RETRIAL_DAYS,
    STALE_CHECKOUT_AFTER,
    paymob_frequency,
    period_end,
    seat_capacity_for,
    subscription_amount_minor,
)
from lemely.db.billing_notices import enqueue_subscription_notice
from lemely.db.billing_repo import (
    CREDIT_EXPIRY_MONTHS,
    INTENTION_EXPIRATION_SECONDS,
    BillingService,
    CheckoutUnavailable,
    UnknownPayer,
    _outcome_unknown,
    add_months,
    billing_data_for,
    is_linked_parent,
    register_paid_handler,
)
from lemely.db.models.billing import (
    LIVE_SUBSCRIPTION_STATUSES,
    CreditPack,
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
from lemely.db.models.enums import Role, SubscriptionStatus
from lemely.db.models.team import TeacherMember, TeacherMemberKind, TeacherMemberStatus
from lemely.db.models.usage import GrantKind
from lemely.db.models.users import User
from lemely.db.teacher_team_repo import TeacherTeamService
from lemely.db.usage_ledger_repo import UsageLedger
from lemely.io.paymob.client import PaymobError

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.orm import Session

    from lemely.db.billing_repo import JsonMap
    from lemely.db.models.usage import UsageGrant
    from lemely.io.paymob.client import PaymobClient
    from lemely.runtime.config import PaymobSettings

log = structlog.get_logger(__name__)
#: Events the operator alerts on (``alert=True`` survives only in structlog).
alerts = structlog.get_logger("lemely.db.subscription_repo")

#: Path of the subscription webhook route (``lemely/web/routers/paymob_webhooks.py``, prefix
#: ``/api/webhooks/paymob``; the Cloudflare Worker proxies only ``/api/*``).
SUBSCRIPTION_WEBHOOK_PATH: Final = "/api/webhooks/paymob/subscription"


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
    """No credit pack gives a rate for this payment, so it cannot be turned into credits."""

    code: ClassVar[str] = "no_credit_rate"


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
    seats bought at the first checkout are part of every renewal. ``force_new`` re-links a tier
    after an admin changes its price or interval; existing subscriptions keep their plan.

    The tier row is locked ``FOR UPDATE`` and the caller commits. Every refusal happens before
    Paymob is called. Owned by Phase 05 with this exact signature (index R9). Phase 07 calls it
    from the admin catalogue and adds its synced-price and synced-frequency stamps inside this
    function, right after ``tier.paymob_plan_id`` and ``tier.paymob_plan_mode`` (the key mode the
    plan was created under, audit I8) are set.

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
    log.info("paymob_plan_linked", plan_tier_id=str(tier.id), paymob_plan_id=plan_id)
    return plan_id


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
    log.warning(
        "seats_shed_after_plan_change",
        teacher_user_id=str(subscription.user_id),
        count=len(newest),
    )
    return len(newest)


# -- payment to credits (UD-3, UD-10; Phase 06 UD-P2) -------------------------------------


def credit_units_for_amount(session: Session, *, amount_minor: int, currency: str) -> int | None:
    """Credit units that ``amount_minor`` buys in the shop, or ``None`` when no pack prices it.

    The one credit rate of the billing code (Phase 05 UD-3, Phase 06 UD-P2): the best
    units-per-price among the active packs in ``currency`` that the same money could buy, or the
    cheapest pack's rate when it buys none. The result is floored, so a conversion never grants
    more than was paid. ``None`` also when the amount is too small for one unit.
    """
    if amount_minor <= 0:
        return None
    packs = session.execute(
        select(CreditPack.units, CreditPack.price_minor)
        .where(
            CreditPack.is_active.is_(True),
            CreditPack.currency == currency,
            CreditPack.price_minor > 0,
            CreditPack.units > 0,
        )
        .order_by(CreditPack.price_minor, CreditPack.code)
    ).all()
    if not packs:
        return None
    affordable = [pack for pack in packs if pack.price_minor <= amount_minor] or packs[:1]
    best = affordable[0]
    for pack in affordable[1:]:
        if pack.units * best.price_minor > best.units * pack.price_minor:
            best = pack
    units = amount_minor * best.units // best.price_minor
    return units if units > 0 else None


def convert_payment_to_credits(
    session: Session, payment: Payment, *, subscription: Subscription, now: datetime
) -> UsageGrant:
    """Turn a paid payment that bought nothing into the beneficiary's credits (UD-3, UD-10).

    Issues a visible ``credit_pack`` grant that expires 12 months after ``now`` (key
    ``credited:{payment.id}``), stamps ``payment.grant_units`` and queues the "credited" notice to
    ``subscription``'s payer. Debt is repaid first by the ledger. Idempotent: a replay returns the
    stored grant and queues nothing new, and the units are the first conversion's, not today's
    rate. Callers pass ``payment.paid_at`` as ``now`` so a replay names the same instant.
    The caller commits and holds the payment row lock; this makes no Paymob call.

    Raises:
        ValueError: the payment is not ``paid``, or ``now`` is naive.
        NoCreditRate: no active credit pack prices the payment's amount in its currency.
    """
    if payment.status is not PaymentStatus.paid:
        raise ValueError("only a paid payment can be turned into credits")
    units = payment.grant_units
    if units is None:
        units = credit_units_for_amount(
            session, amount_minor=payment.amount_minor, currency=payment.currency
        )
    if units is None:
        raise NoCreditRate(f"no credit rate for payment {payment.id}")
    grant = UsageLedger(session).issue_grant(
        owner_user_id=payment.beneficiary_user_id,
        kind=GrantKind.credit_pack,
        units=units,
        idempotency_key=f"credited:{payment.id}",
        expires_at=add_months(now, CREDIT_EXPIRY_MONTHS),
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
    except NoCreditRate:
        alerts.error(
            "subscription_first_paid_for_superseded_checkout",
            subscription_id=str(subscription.id),
            payment_id=str(payment.id),
            converted=False,
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
    subscription = session.get(Subscription, payment.subscription_id, with_for_update=True)
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
    if _has_other_live(session, subscription):
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
    subscription.status = SubscriptionStatus.active
    subscription.activated_at = paid_at
    subscription.current_period_start = paid_at
    subscription.current_period_end = end
    subscription.grace_until = None
    subscription.paymob_amount_minor = payment.amount_minor
    _bump(subscription)
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


def _violates_one_live(exc: IntegrityError) -> bool:
    """Whether ``exc`` is the one-live-subscription-per-user unique index (not any other error)."""
    diag = getattr(exc.orig, "diag", None)
    return getattr(diag, "constraint_name", None) == _ONE_LIVE_INDEX


__all__ = [
    "SUBSCRIPTION_WEBHOOK_PATH",
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
    "SeatsInsufficient",
    "SubscriptionCheckout",
    "SubscriptionError",
    "SubscriptionNotFound",
    "SubscriptionService",
    "convert_payment_to_credits",
    "credit_units_for_amount",
    "handle_subscription_first",
    "subscription_webhook_url",
    "sync_paymob_plan",
]

# Registered at import, so any process that settles a payment reaches the handler. The reconcile
# sweeper gets there through ``lemely/web/billing_jobs.py``, which Task 11 makes import this module
# (DV-10): until then only a process that imported it has the handler.
register_paid_handler(PaymentPurpose.subscription_first, handle_subscription_first)
