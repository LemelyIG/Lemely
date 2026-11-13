"""Subscriptions on Paymob: checkout, first payment, renewal, grace, plan changes, drift.

Paymob billing spec §2.6, §4.3, §5.1-§5.3, §6 (Phase 05). This module holds the plan sync and
the service shell; later tasks add the lifecycle to :class:`SubscriptionService`.

* Paymob's subscriptions module charges renewals (spec §3 approach Y). Lemely never trusts a
  subscription webhook's body: the HMAC covers only ``trigger_type`` and the id, so state and
  amounts are re-fetched (``GET subscriptions/{id}``, ``GET .../last-transaction``).
* Every paid period is one ``subscription_periods`` row and one ``period_allowance`` grant,
  issued through :meth:`UsageLedger.issue_grant`, which repays the owner's debt first (§5.8).
* Webhook and checkout methods leave the commit to the caller. Sweep methods commit after each
  subscription, so one Paymob failure cannot undo another subscription's change.
* Lock order: subscription row, then ``teacher_members`` rows, then ledger owner locks.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Final

import structlog

from lemely.core.subscription_rules import PAYMOB_RETRIAL_DAYS, paymob_frequency
from lemely.db.billing_repo import BillingService, _outcome_unknown
from lemely.db.models.billing import PlanTier
from lemely.io.paymob.client import PaymobError

if TYPE_CHECKING:
    import uuid
    from datetime import datetime

    from sqlalchemy.orm import Session

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
    function, right after ``tier.paymob_plan_id`` is set.

    Raises:
        PlanNotPurchasable: unknown tier, no interval, a price of zero or less, or no MOTO
            integration id.
        PlanSyncFailed: Paymob answered without an integer plan id; the tier is left as it was.
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
        raise PlanSyncFailed(f"Paymob returned no plan id for tier {tier.id}")
    tier.paymob_plan_id = plan_id
    log.info("paymob_plan_linked", plan_tier_id=str(tier.id), paymob_plan_id=plan_id)
    return plan_id


class SubscriptionService:
    """The subscription lifecycle, bound to one session (see the module docstring)."""

    def __init__(self, session: Session, client: PaymobClient, settings: PaymobSettings) -> None:
        self._session = session
        self._client = client
        self._settings = settings

    def _billing(self, now: datetime) -> BillingService:
        """A payments service whose clock is the caller's ``now``, never the wall clock (DV-8)."""
        return BillingService(self._session, self._client, self._settings, now=lambda: now)


__all__ = [
    "SUBSCRIPTION_WEBHOOK_PATH",
    "AlreadySubscribed",
    "DowngradeUnavailable",
    "InvalidExtraSeats",
    "InvalidPlanChange",
    "MalformedWebhook",
    "NotLinkedParent",
    "PlanNotPurchasable",
    "PlanSyncFailed",
    "SeatsInsufficient",
    "SubscriptionError",
    "SubscriptionNotFound",
    "SubscriptionService",
    "subscription_webhook_url",
    "sync_paymob_plan",
]
