"""Admin payments (spec §6 refunds, §8 area 3): refund, void, list, problem queue, reconcile.

**Refunds follow spec §6 "insert our own refund row before calling Paymob".** Transaction 1
locks the payment, refuses while an earlier refund is unresolved, writes a ``requested`` row and
its audit row, and commits. Paymob is then called with no transaction open. Transaction 2 locks
the payment, then the refund row, and records the outcome:

* ``succeeded`` — the payment moves to ``refunded``/``partially_refunded``/``voided`` (never
  down: a Phase 02 parent callback may already have moved it). A fully refunded or voided credit
  pack or auto top-up claws back the unspent units of its grants (spent units stay spent).
* ``failed`` — Paymob refused (a received 4xx, or a body saying ``success: false``). Nothing
  else changes and a new refund is allowed.
* ``unknown`` — timeout, transport error, 5xx, a pending answer or a body that cannot be read:
  Paymob may have refunded. The row blocks any new refund on the payment until reconcile settles
  it by inquiry. A refund or void is never retried (audit I6, spec §6).

A crash between the two transactions leaves ``requested``, which blocks new refunds the same way.

**Reconcile settles what is unresolved** by one inquiry on the parent transaction (the Bearer
inquiry, ``inquire_by_transaction``). A refund that Paymob shows is ``succeeded``. One it does not
show stays pending while the row is younger than 60 minutes (UD-3), then becomes ``failed``. A
``requested`` row is settled only once it is older than the stuck threshold, which sits above the
Paymob client timeout so cleanup cannot race a refund call still in flight.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final

import sqlalchemy as sa
import structlog
from sqlalchemy import func, or_, select, tuple_

from lemely.core.keyset import CursorError, decode_cursor, encode_cursor
from lemely.db.admin_billing_repo import (
    AdminConflictError,
    AdminInvalidError,
    AdminNotFoundError,
    AuditAction,
    AuditTarget,
    PaymentView,
    PaymobCallError,
    alerts,
    audited,
    payment_views,
    require_reason,
)
from lemely.db.billing_repo import (
    BillingService,
    PaymentBusyError,
    PaymentNotFoundError,
    _outcome_unknown,
)
from lemely.db.merchant_charge_repo import (
    RENEWAL_SEAT_DEDUPE_PREFIX,
    MerchantChargeError,
    MerchantChargeService,
    current_period,
    current_terms,
    is_upgrade,
)
from lemely.db.models.admin_audit import AdminAuditLog
from lemely.db.models.billing import (
    Payment,
    PaymentPurpose,
    PaymentStatus,
    PaymobEvent,
    PlanTier,
    PlanTierTerms,
    Subscription,
)
from lemely.db.models.billing_ops import (
    PaymentRefund,
    PaymobWebhookFailure,
    RefundKind,
    RefundStatus,
)
from lemely.db.models.enums import SubscriptionStatus
from lemely.db.models.usage import GrantKind, UsageEntry, UsageEntryKind, UsageGrant
from lemely.db.subscription_repo import (
    SubscriptionError,
    SubscriptionService,
)
from lemely.db.usage_ledger_repo import UsageLedger
from lemely.io.paymob.client import PaymobError

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.orm import Session, sessionmaker
    from sqlalchemy.sql import Select

    from lemely.io.paymob.client import PaymobClient
    from lemely.runtime.config import PaymobSettings

_PAYMENTS_CURSOR: Final = "admin.billing.payments"
#: ``created``/``pending`` for longer than this is a problem (spec §8 "pending over an hour").
STALE_PENDING_AFTER: Final = timedelta(hours=1)
#: A paid payment with no callback after this long is listed as a missing callback (DV-28).
CALLBACK_GRACE: Final = timedelta(minutes=15)
HMAC_WINDOW: Final = timedelta(days=7)
#: An in-flight refund older than this needs attention, and reconcile may settle it. It must stay
#: above the Paymob client timeout; ``AdminPaymentsService.stuck_after`` enforces the margin.
REFUND_STUCK_AFTER: Final = timedelta(minutes=10)
#: UD-3 (b): an unclear refund stays pending this long, then fails.
REFUND_UNCLEAR_FOR: Final = timedelta(minutes=60)
_QUEUE_LIMIT = 100
_REFUNDABLE: Final = frozenset({PaymentStatus.paid, PaymentStatus.partially_refunded})
_IN_FLIGHT: Final = frozenset({RefundStatus.requested, RefundStatus.unknown})
_CLAWBACK_PURPOSES: Final = frozenset({PaymentPurpose.credit_pack, PaymentPurpose.auto_topup})
#: A subscription payment's refund ends the plan through Phase 05 (UD-6 (a)); a proration or an
#: extra-seat payment changes nothing unless the admin asks to reverse it (UD-4).
_SUBSCRIPTION_PURPOSES: Final = frozenset(
    {PaymentPurpose.subscription_first, PaymentPurpose.subscription_renewal}
)
_CLOSE_ACTIONS: Final = {
    RefundStatus.succeeded: AuditAction.PAYMENT_REFUND_SUCCEEDED,
    RefundStatus.failed: AuditAction.PAYMENT_REFUND_FAILED,
    RefundStatus.unknown: AuditAction.PAYMENT_REFUND_UNKNOWN,
}
#: Where a status ranks: a refund total only moves forward, and a void ends the payment.
_RANK: Final = {
    PaymentStatus.paid: 0,
    PaymentStatus.partially_refunded: 1,
    PaymentStatus.refunded: 2,
    PaymentStatus.voided: 3,
}
#: What of Paymob's answer is kept. Nothing else is stored (no card data, no tokens).
_INQUIRY_KEPT: Final = (
    "id",
    "success",
    "pending",
    "is_voided",
    "is_refunded",
    "refunded_amount_cents",
)
_KEPT: Final = ("id", "success", "pending", "amount_cents", "is_refund", "is_void", "created_at")


@dataclass(frozen=True, slots=True)
class PaymentPage:
    items: list[PaymentView]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class ProblemQueue:
    mismatches: list[PaymentView]
    stale_pending: list[PaymentView]
    missing_callbacks: list[PaymentView]
    hmac_failures: list[PaymobWebhookFailure]
    hmac_failures_24h: int
    refunds_needing_attention: list[PaymentRefund]
    refund_currency: dict[uuid.UUID, str]
    """The currency of each such refund's payment, keyed by payment id (R28)."""


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _is_true(value: object) -> bool:
    return value is True


def classify_answer(response: object) -> RefundStatus:
    """What a 2xx answer from Paymob means (DV-18). Anything unclear is ``unknown``."""
    if not isinstance(response, Mapping):
        return RefundStatus.unknown
    if _is_true(response.get("pending")):
        return RefundStatus.unknown
    success = response.get("success")
    if success is True:
        return RefundStatus.succeeded
    if success is False:
        return RefundStatus.failed
    return RefundStatus.unknown


def classify_error(exc: BaseException) -> RefundStatus:
    """A refusal Paymob sent back is final; anything that may have reached it is ``unknown``."""
    if isinstance(exc, PaymobError):
        return RefundStatus.unknown if _outcome_unknown(exc) else RefundStatus.failed
    return RefundStatus.unknown


def redacted_response(response: object) -> dict[str, object]:
    """The few scalar fields of Paymob's answer worth keeping."""
    if not isinstance(response, Mapping):
        return {"unreadable": True}
    return {
        key: response[key]
        for key in _KEPT
        if key in response and isinstance(response[key], str | int | float | bool | None)
    }


def redacted_error(exc: BaseException) -> dict[str, object]:
    """What a failed call leaves in the row: the kind of failure, never Paymob's body."""
    detail: dict[str, object] = {"error": type(exc).__name__}
    if isinstance(exc, PaymobError):
        detail |= {"status_code": exc.status_code, "timeout": exc.timeout}
    return detail


class _ReverseUnavailableError(Exception):
    """The purchase cannot be reversed from stored data or through the public APIs."""


def _grant_ids(
    s: Session, payment_id: uuid.UUID, kinds: frozenset[GrantKind] | None
) -> list[uuid.UUID]:
    """The grants a payment issued (every one when ``kinds`` is ``None``), oldest first."""
    query = select(UsageGrant.id).where(UsageGrant.payment_id == payment_id)
    if kinds is not None:
        query = query.where(UsageGrant.kind.in_(kinds))
    return list(s.scalars(query.order_by(UsageGrant.created_at, UsageGrant.id)))


def _clawed_total(s: Session, payment_id: uuid.UUID) -> int:
    """Units already taken back from the grants of one payment (``refund`` ledger entries)."""
    total = s.scalar(
        select(func.coalesce(-func.sum(UsageEntry.units), 0)).where(
            UsageEntry.kind == UsageEntryKind.refund,
            UsageEntry.grant_id.in_(
                select(UsageGrant.id).where(UsageGrant.payment_id == payment_id)
            ),
        )
    )
    return int(total or 0)


def _committed_refunded(s: Session, view: PaymentView) -> int:
    """Money returned or already on its way back: the refunded total plus the lag Paymob owes us.

    DV-19's ``refunded_minor`` is the larger of our succeeded refunds and Paymob's last reported
    total. Between a console refund and Paymob's parent callback, a dashboard refund made before
    it hides it (7000 in the dashboard plus 3000 here reads as 7000). Each succeeded refund
    therefore also counts as the total we read when it was requested plus its own amount, so the
    same remainder cannot be requested twice.
    """
    refunded = view.refunded_minor
    succeeded = [
        r
        for r in view.refunds
        if r.status is RefundStatus.succeeded and r.kind is RefundKind.refund
    ]
    if not succeeded:
        return refunded
    baselines: dict[str, int] = {}
    for row in s.scalars(
        select(AdminAuditLog).where(
            AdminAuditLog.action == AuditAction.PAYMENT_REFUND_REQUESTED.value,
            AdminAuditLog.target_kind == AuditTarget.PAYMENT.value,
            AdminAuditLog.target_id == view.payment.id,
        )
    ):
        refund_id = (row.after or {}).get("refund_id")
        before = (row.before or {}).get("refunded_minor")
        if isinstance(refund_id, str) and isinstance(before, int) and not isinstance(before, bool):
            baselines[refund_id] = before
    for r in succeeded:
        base = baselines.get(str(r.id))
        if base is not None:
            refunded = max(refunded, base + r.amount_minor)
    return refunded


class AdminPaymentsService:
    """Refund and void, the payment list, the problem queue and manual reconcile."""

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

    def payment_view(self, payment_id: uuid.UUID) -> PaymentView:
        with self._sm() as s:
            payment = s.get(Payment, payment_id)
            if payment is None:
                raise AdminNotFoundError("payment_not_found")
            return payment_views(s, [payment])[0]

    # -- refund and void ---------------------------------------------------------

    def refund(
        self,
        payment_id: uuid.UUID,
        *,
        amount_minor: int | None,
        admin_user_id: uuid.UUID,
        reason: str,
        reverse_change: bool = False,
    ) -> PaymentView:
        """Refund ``amount_minor`` piasters (``None`` = everything not yet refunded).

        ``reverse_change`` asks to undo what the payment bought as well as return the money
        (UD-4); it needs the whole remaining amount, and is refused before any row when the
        purchase cannot be reversed.
        """
        return self._run(
            payment_id, RefundKind.refund, amount_minor, admin_user_id, reason, reverse_change
        )

    def void(
        self,
        payment_id: uuid.UUID,
        *,
        admin_user_id: uuid.UUID,
        reason: str,
        reverse_change: bool = False,
    ) -> PaymentView:
        """Void a paid, never-refunded payment (Paymob allows it until settlement)."""
        return self._run(payment_id, RefundKind.void, None, admin_user_id, reason, reverse_change)

    def _run(
        self,
        payment_id: uuid.UUID,
        kind: RefundKind,
        amount_minor: int | None,
        admin_user_id: uuid.UUID,
        reason: str,
        reverse_change: bool,
    ) -> PaymentView:
        require_reason(reason)
        refund_id, txn_id, amount = self._open_refund(
            payment_id,
            kind=kind,
            amount_minor=amount_minor,
            admin_user_id=admin_user_id,
            reason=reason,
            reverse_change=reverse_change,
        )
        # No transaction is open here: the row is committed and the payment unlocked.
        try:
            if kind is RefundKind.void:
                answer: object = self._client.void(transaction_id=txn_id)
            else:
                answer = self._client.refund(transaction_id=txn_id, amount_cents=amount)
        except Exception as exc:
            outcome = classify_error(exc)
            stored = redacted_error(exc)
        else:
            outcome = classify_answer(answer)
            stored = redacted_response(answer)
        try:
            self._close_refund(
                refund_id,
                outcome=outcome,
                response=stored,
                admin_user_id=admin_user_id,
                reason=reason,
            )
        except Exception:
            # Paymob answered but the answer was not recorded: the row stays ``requested`` and
            # blocks new refunds. Someone settles it by inquiry (Task 9 treats it like ``unknown``).
            alerts.error(
                "admin_refund_outcome_unrecorded",
                alert=True,
                refund_id=str(refund_id),
                payment_id=str(payment_id),
                outcome=outcome.value,
            )
            raise
        return self.payment_view(payment_id)

    def _open_refund(
        self,
        payment_id: uuid.UUID,
        *,
        kind: RefundKind,
        amount_minor: int | None,
        admin_user_id: uuid.UUID,
        reason: str,
        reverse_change: bool,
    ) -> tuple[uuid.UUID, int, int]:
        """Validate, insert the ``requested`` row and its audit row; commit.

        Returns ``(refund id, Paymob transaction id, amount in piasters)``.
        """
        with self._sm.begin() as s:
            payment = s.get(Payment, payment_id, with_for_update=True)
            if payment is None:
                raise AdminNotFoundError("payment_not_found")
            view = payment_views(s, [payment])[0]
            if any(r.status in _IN_FLIGHT for r in view.refunds):
                raise AdminConflictError(
                    "refund_in_flight", "A refund is still unresolved; reconcile the payment first."
                )
            refunded = _committed_refunded(s, view)
            if kind is RefundKind.void:
                if payment.status is not PaymentStatus.paid or refunded:
                    raise AdminConflictError(
                        "not_voidable", "Only a paid, unrefunded payment voids."
                    )
                amount = payment.amount_minor
                full = True
            else:
                if payment.status not in _REFUNDABLE:
                    raise AdminConflictError("not_refundable", "Only paid payments refund.")
                remaining = payment.amount_minor - refunded
                amount = remaining if amount_minor is None else amount_minor
                if amount <= 0 or amount > remaining:
                    raise AdminInvalidError(
                        "refund_amount_out_of_range",
                        f"Refund between 1 and {max(remaining, 0)} piasters.",
                    )
                full = amount == remaining
            if payment.paymob_txn_id is None:
                raise AdminConflictError(
                    "no_paymob_transaction", "Paymob never charged this payment."
                )
            if reverse_change:
                self._check_reversible(s, payment, full=full)
            row = PaymentRefund(
                payment_id=payment.id,
                admin_user_id=admin_user_id,
                kind=kind,
                status=RefundStatus.requested,
                amount_minor=amount,
                reason=reason.strip(),
                reverse_change=reverse_change,
            )
            s.add(row)
            s.flush()
            audited(
                s,
                admin_user_id,
                AuditAction.PAYMENT_VOID_REQUESTED
                if kind is RefundKind.void
                else AuditAction.PAYMENT_REFUND_REQUESTED,
                AuditTarget.PAYMENT,
                payment.id,
                reason,
                {"status": payment.status, "refunded_minor": refunded},
                {
                    "refund_id": row.id,
                    "kind": kind,
                    "amount_minor": amount,
                    "reverse_change": reverse_change,
                },
            )
            return row.id, int(payment.paymob_txn_id), amount

    def _close_refund(
        self,
        refund_id: uuid.UUID,
        *,
        outcome: RefundStatus,
        response: Mapping[str, object],
        admin_user_id: uuid.UUID,
        reason: str,
    ) -> None:
        """Record Paymob's answer (payment locked first, then the refund row) and audit it.

        Reconcile reuses this to settle an ``unknown`` or stale ``requested`` row; a row that is
        no longer in flight is left alone.
        """
        with self._sm.begin() as s:
            payment_id = s.scalars(
                select(PaymentRefund.payment_id).where(PaymentRefund.id == refund_id)
            ).one()
            payment = s.get(Payment, payment_id, with_for_update=True)
            refund = s.get(PaymentRefund, refund_id, with_for_update=True)
            assert payment is not None and refund is not None  # noqa: S101 - rows written by _open_refund
            if refund.status not in _IN_FLIGHT:
                return  # settled meanwhile (a second reconcile): never closed or clawed back twice
            before = {"status": payment.status, "refund_status": refund.status}
            refund.status = outcome
            refund.paymob_response = dict(response)
            s.flush()
            effect: dict[str, object] = {}
            if outcome is RefundStatus.succeeded:
                effect = self._apply_success(s, payment, refund)
            if outcome is RefundStatus.unknown:
                alerts.error(
                    "admin_refund_outcome_unknown",
                    alert=True,
                    refund_id=str(refund.id),
                    payment_id=str(payment.id),
                )
            audited(
                s,
                admin_user_id,
                _CLOSE_ACTIONS[outcome],
                AuditTarget.PAYMENT,
                payment.id,
                reason,
                before,
                {
                    "status": payment.status,
                    "refund_id": refund.id,
                    "refund_status": refund.status,
                    "clawed_back_units": refund.clawed_back_units,
                    **effect,
                },
            )

    # -- list, problem queue, reconcile --------------------------------------------

    def stuck_after(self) -> timedelta:
        """How old an in-flight refund must be before it needs attention or reconcile settles it.

        Never below three Paymob client timeouts, so a refund call still running is left alone.
        """
        return max(REFUND_STUCK_AFTER, timedelta(seconds=3 * self._settings.timeout_seconds))

    def list_payments(
        self,
        *,
        status: PaymentStatus | None,
        purpose: PaymentPurpose | None,
        user_id: uuid.UUID | None,
        start: datetime | None,
        end: datetime | None,
        cursor: str | None,
        limit: int,
    ) -> PaymentPage:
        """Newest first, keyset-paged on ``(created_at, id)`` (a tie never splits a page)."""
        stmt = select(Payment)
        if status is not None:
            stmt = stmt.where(Payment.status == status)
        if purpose is not None:
            stmt = stmt.where(Payment.purpose == purpose)
        if user_id is not None:
            stmt = stmt.where(
                or_(Payment.payer_user_id == user_id, Payment.beneficiary_user_id == user_id)
            )
        if start is not None:
            stmt = stmt.where(Payment.created_at >= start)
        if end is not None:
            stmt = stmt.where(Payment.created_at < end)
        if cursor is not None:
            try:
                created, last_id = decode_cursor(
                    cursor, endpoint=_PAYMENTS_CURSOR, types=(datetime, uuid.UUID)
                )
            except CursorError as exc:
                raise AdminInvalidError("bad_cursor", str(exc)) from exc
            stmt = stmt.where(
                tuple_(Payment.created_at, Payment.id) < tuple_(created, last_id)  # type: ignore[arg-type]
            )
        with self._sm() as s:
            rows = list(
                s.scalars(
                    stmt.order_by(Payment.created_at.desc(), Payment.id.desc()).limit(limit + 1)
                )
            )
            page = rows[:limit]
            next_cursor = (
                encode_cursor(_PAYMENTS_CURSOR, [page[-1].created_at, page[-1].id])
                if len(rows) > limit
                else None
            )
            return PaymentPage(items=payment_views(s, page), next_cursor=next_cursor)

    def problems(self) -> ProblemQueue:
        """Everything an admin should look at today (spec §8 area 3), each list bounded."""
        now = self._now()
        with self._sm() as s:

            def views(stmt: Select[tuple[Payment]]) -> list[PaymentView]:
                return payment_views(s, list(s.scalars(stmt.limit(_QUEUE_LIMIT))))

            mismatches = views(
                select(Payment)
                .where(Payment.status == PaymentStatus.failed_mismatch)
                .order_by(Payment.created_at.desc(), Payment.id)
            )
            stale = views(
                select(Payment)
                .where(
                    Payment.status.in_((PaymentStatus.created, PaymentStatus.pending)),
                    Payment.created_at < now - STALE_PENDING_AFTER,
                )
                .order_by(Payment.created_at, Payment.id)
            )
            # A renewal is charged by Paymob's scheduler and reported on the subscription
            # webhook, so it has no transaction callback of its own. An open payment whose
            # callback was refused for its integration is stamped (T2 M6) yet still waits for a
            # person, so it is listed through the refusal event instead of the stamp.
            refused = (
                select(PaymobEvent.id)
                .where(
                    PaymobEvent.dedupe_key.like("rejected\\_integration:%", escape="\\"),
                    or_(
                        PaymobEvent.payload["order"]["merchant_order_id"].astext
                        == Payment.special_reference,
                        PaymobEvent.payload["order"]["id"].astext
                        == sa.cast(Payment.paymob_order_id, sa.Text),
                    ),
                )
                .exists()
            )
            missing = views(
                select(Payment)
                .where(
                    or_(
                        (Payment.status == PaymentStatus.paid)
                        & (Payment.purpose != PaymentPurpose.subscription_renewal)
                        & (Payment.paid_at < now - CALLBACK_GRACE)
                        & Payment.callback_received_at.is_(None),
                        Payment.status.in_((PaymentStatus.created, PaymentStatus.pending))
                        & refused,
                    )
                )
                .order_by(func.coalesce(Payment.paid_at, Payment.created_at).desc(), Payment.id)
            )
            failures = list(
                s.scalars(
                    select(PaymobWebhookFailure)
                    .where(PaymobWebhookFailure.received_at >= now - HMAC_WINDOW)
                    .order_by(PaymobWebhookFailure.received_at.desc(), PaymobWebhookFailure.id)
                    .limit(_QUEUE_LIMIT)
                )
            )
            failures_24h = int(
                s.scalar(
                    select(func.count())
                    .select_from(PaymobWebhookFailure)
                    .where(PaymobWebhookFailure.received_at >= now - timedelta(hours=24))
                )
                or 0
            )
            stuck = list(
                s.scalars(
                    select(PaymentRefund)
                    .where(
                        PaymentRefund.status.in_(tuple(_IN_FLIGHT)),
                        PaymentRefund.created_at < now - self.stuck_after(),
                    )
                    .order_by(PaymentRefund.created_at, PaymentRefund.id)
                    .limit(_QUEUE_LIMIT)
                )
            )
            currency = {
                pid: cur
                for pid, cur in s.execute(
                    select(Payment.id, Payment.currency).where(
                        Payment.id.in_({r.payment_id for r in stuck})
                    )
                )
            }
            return ProblemQueue(mismatches, stale, missing, failures, failures_24h, stuck, currency)

    def reconcile(
        self, payment_id: uuid.UUID, *, admin_user_id: uuid.UUID, reason: str
    ) -> PaymentView:
        """Inquire Paymob for one payment now, then settle its unresolved refunds by inquiry.

        The payment part commits in its own transaction first. ``reconcile_payment_now`` takes a
        ``NOWAIT`` lock and a busy row aborts the whole transaction, so the audit row is written
        after it, never before (a busy row writes nothing and answers 409). An inquiry failure
        while settling refunds is 502 and leaves them as they were.
        """
        require_reason(reason)
        with self._sm.begin() as s:
            payment = s.get(Payment, payment_id)
            if payment is None:
                raise AdminNotFoundError("payment_not_found")
            before = payment.status
            try:
                status = BillingService(s, self._client, self._settings).reconcile_payment_now(
                    payment_id, now=self._now()
                )
            except PaymentBusyError as exc:
                raise AdminConflictError(
                    "reconcile_in_progress",
                    "Another process is working on this payment; try again in a moment.",
                ) from exc
            except PaymentNotFoundError as exc:
                raise AdminNotFoundError("payment_not_found") from exc
            audited(
                s,
                admin_user_id,
                AuditAction.PAYMENT_RECONCILE,
                AuditTarget.PAYMENT,
                payment_id,
                reason,
                {"status": before},
                {"status": status},
            )
        self._settle_refunds(payment_id, admin_user_id=admin_user_id, reason=reason)
        return self.payment_view(payment_id)

    @staticmethod
    def _kept_inquiry(seen: Mapping[str, object]) -> dict[str, object]:
        """The scalar fields of Paymob's answer worth keeping on the refund row."""
        return {
            key: seen[key]
            for key in _INQUIRY_KEPT
            if key in seen and isinstance(seen[key], str | int | float | bool | None)
        }

    def _settle_refunds(
        self, payment_id: uuid.UUID, *, admin_user_id: uuid.UUID, reason: str
    ) -> int:
        """Settle ``unknown`` and stale ``requested`` refunds from Paymob's view; returns how many.

        One inquiry on the parent transaction answers every row. A refund Paymob shows
        (``refunded_amount_cents`` at least the succeeded total before it plus its amount; a void
        by ``is_voided``) is ``succeeded``. One it does not show waits while the row is younger than
        60 minutes (UD-3) and then fails. A ``requested`` row is a live call until it is stuck.
        """
        now = self._now()
        with self._sm() as s:
            txn = s.scalar(select(Payment.paymob_txn_id).where(Payment.id == payment_id))
            rows = list(
                s.scalars(
                    select(PaymentRefund)
                    .where(PaymentRefund.payment_id == payment_id)
                    .order_by(PaymentRefund.created_at, PaymentRefund.id)
                )
            )
        stuck_before = now - self.stuck_after()
        open_rows = [
            r
            for r in rows
            if r.status is RefundStatus.unknown
            or (r.status is RefundStatus.requested and r.created_at < stuck_before)
        ]
        if not open_rows or txn is None:
            return 0
        try:
            seen = self._client.inquire_by_transaction(int(txn)) or {}
        except PaymobError as exc:
            raise PaymobCallError(
                "paymob_inquiry_failed", "Paymob could not be asked about this payment."
            ) from exc
        settled = 0
        succeeded = sum(
            r.amount_minor
            for r in rows
            if r.status is RefundStatus.succeeded and r.kind is RefundKind.refund
        )
        for refund in open_rows:
            if refund.kind is RefundKind.void:
                visible = seen.get("is_voided") is True
            else:
                reported = seen.get("refunded_amount_cents")
                visible = (
                    isinstance(reported, int)
                    and not isinstance(reported, bool)
                    and reported >= succeeded + refund.amount_minor
                )
            if visible:
                outcome = RefundStatus.succeeded
            elif now - refund.created_at >= REFUND_UNCLEAR_FOR:
                outcome = RefundStatus.failed
            else:
                continue  # UD-3 (b): keep it pending and ask again at the next reconcile
            self._close_refund(
                refund.id,
                outcome=outcome,
                response={"inquiry": self._kept_inquiry(seen)},
                admin_user_id=admin_user_id,
                reason=reason,
            )
            settled += 1
            if outcome is RefundStatus.succeeded and refund.kind is RefundKind.refund:
                succeeded += refund.amount_minor
        return settled

    # -- what a refund undoes ------------------------------------------------------

    def _check_reversible(self, s: Session, payment: Payment, *, full: bool) -> None:
        """Refuse ``reverse_change`` before any row exists when it cannot be honoured (422)."""
        if not full:
            raise AdminInvalidError(
                "reverse_needs_full_refund",
                "Reversing the purchase needs the whole remaining amount refunded.",
            )
        nested = s.begin_nested()
        try:  # a dry run: the public APIs check and write, so the write is rolled back
            with structlog.contextvars.bound_contextvars(dry_run=True):  # their logs are dropped
                self._reverse(s, payment)
        except _ReverseUnavailableError as exc:
            raise AdminInvalidError("reverse_unavailable", str(exc)) from exc
        finally:
            nested.rollback()

    def _reverse(self, s: Session, payment: Payment) -> dict[str, object]:
        """Undo what ``payment`` bought through the public APIs; returns the audit notes.

        Credit packs and subscription payments are reversed by the claw-back and Phase 05's
        ``on_payment_refunded`` that every full refund already runs. Extra seats and a plan
        upgrade are scheduled for the next renewal (the APIs never change a paid period).
        """
        purpose = payment.purpose
        if purpose in _CLAWBACK_PURPOSES:
            return {"reverse_effect": "same_as_full_refund"}
        if _grant_ids(s, payment.id, frozenset({GrantKind.credit_pack})):
            return {"reverse_effect": "credits_clawed_back"}  # the purchase became credits
        if purpose in _SUBSCRIPTION_PURPOSES:
            return {"reverse_effect": "same_as_full_refund"}
        sub = (
            None
            if payment.subscription_id is None
            else s.get(Subscription, payment.subscription_id)
        )
        if sub is None or sub.payer_user_id is None:
            raise _ReverseUnavailableError("The subscription is not billed through a payer.")
        if purpose is PaymentPurpose.extra_seats:
            return self._reverse_seats(s, payment, sub)
        if purpose is PaymentPurpose.upgrade_proration:
            return self._reverse_upgrade(s, payment, sub)
        raise _ReverseUnavailableError("This purchase has nothing to reverse.")

    def _reverse_seats(self, s: Session, payment: Payment, sub: Subscription) -> dict[str, object]:
        """Remove only the seats this payment added, at the next renewal.

        The target is what the teacher would hold without the purchase, ``held - quantity``, and
        never above a reduction already scheduled: that one may already exclude these seats, and
        undoing the purchase must not cut seats an older, unrefunded payment bought.
        """
        if payment.dedupe_key is not None and payment.dedupe_key.startswith(
            RENEWAL_SEAT_DEDUPE_PREFIX
        ):
            raise _ReverseUnavailableError(
                "A renewal seat charge paid for seats that already existed."
            )
        if sub.current_period_start is None or payment.created_at < sub.current_period_start:
            raise _ReverseUnavailableError("The seats were bought in an earlier period.")
        quantity = payment.seat_quantity or 0
        held = sub.extra_seats or 0
        if held <= 0 or quantity <= 0:
            raise _ReverseUnavailableError("No extra seats are held.")
        pending = sub.pending_extra_seats
        # Seats earlier reverses of this period already scheduled away count as gone too.
        target = max(0, held - self._seats_already_reversed(s, sub, payment) - quantity)
        if pending is not None:
            target = min(target, pending)
        if pending is not None and target >= pending:
            return {"reverse_effect": "already_scheduled", "pending_extra_seats": pending}
        try:
            MerchantChargeService(s, self._client, self._settings).schedule_seat_reduction(
                subscription_id=sub.id,
                actor_user_id=sub.payer_user_id,  # type: ignore[arg-type]
                extra_seats=target,
                now=self._now(),
            )
        except (MerchantChargeError, SubscriptionError) as exc:
            raise _ReverseUnavailableError(f"The seats cannot be removed now ({exc}).") from exc
        return {"reverse_effect": "seat_reduction_scheduled", "pending_extra_seats": target}

    @staticmethod
    def _seats_already_reversed(s: Session, sub: Subscription, payment: Payment) -> int:
        """Seats other purchases of this period gave back through a reverse that took effect."""
        applied = (
            select(AdminAuditLog.target_id)
            .where(
                AdminAuditLog.action == AuditAction.PAYMENT_REFUND_SUCCEEDED.value,
                AdminAuditLog.target_kind == AuditTarget.PAYMENT.value,
                AdminAuditLog.after["reverse_effect"].astext.in_(
                    ("seat_reduction_scheduled", "already_scheduled")
                ),
            )
            .scalar_subquery()
        )
        total = s.scalar(
            select(func.coalesce(func.sum(Payment.seat_quantity), 0)).where(
                Payment.subscription_id == sub.id,
                Payment.purpose == PaymentPurpose.extra_seats,
                Payment.id != payment.id,
                Payment.created_at >= sub.current_period_start,
                Payment.id.in_(applied),
            )
        )
        return int(total or 0)

    def _reverse_upgrade(
        self, s: Session, payment: Payment, sub: Subscription
    ) -> dict[str, object]:
        """Go back to the tier this upgrade replaced, at the next renewal.

        That is the target of the latest earlier upgrade of the period, or the tier of the
        period's own payment when there was none. Recoverable only when that tier still has the
        terms the subscriber was billed on (a downgrade applies a tier's current terms): for the
        period's payment, the version stamped on the period; for an earlier upgrade, no newer
        version was written after that upgrade was paid.
        """
        if sub.plan_tier_id != payment.plan_tier_id:
            raise _ReverseUnavailableError("The upgrade is no longer the plan being billed.")
        if sub.cancel_at_period_end:  # the plan ends at renewal anyway: nothing left to undo
            return {"reverse_effect": "plan_ends_at_period_end"}
        period = current_period(s, sub)
        if period is None or payment.created_at < period.period_start:
            raise _ReverseUnavailableError("The upgrade belongs to an earlier period.")
        paying = None if period.payment_id is None else s.get(Payment, period.payment_id)
        base = None if paying is None else paying.plan_tier_id
        if base is None:
            raise _ReverseUnavailableError("The tier billed before the upgrade is not recorded.")
        # Walk the period's upgrades in the order they were paid. Only one that is an upgrade over
        # the tier then billed can have moved the tier: a paid one that was never applied (no
        # credit rate to convert it) does not extend the chain.
        earlier = s.scalars(
            select(Payment)
            .where(
                Payment.subscription_id == sub.id,
                Payment.purpose == PaymentPurpose.upgrade_proration,
                Payment.status.in_(
                    (
                        PaymentStatus.paid,
                        PaymentStatus.partially_refunded,
                        PaymentStatus.refunded,
                        PaymentStatus.voided,
                    )
                ),
                Payment.grant_units.is_(None),
                Payment.id != payment.id,
                Payment.paid_at >= period.period_start,
                Payment.paid_at < payment.paid_at,
            )
            .order_by(Payment.paid_at, Payment.created_at)
        ).all()
        previous: uuid.UUID = base
        applied: Payment | None = None
        for candidate in earlier:
            if candidate.plan_tier_id is not None and self._is_upgrade_over(
                s, previous, candidate.plan_tier_id
            ):
                previous, applied = candidate.plan_tier_id, candidate
        if payment.plan_tier_id is None or not self._is_upgrade_over(
            s, previous, payment.plan_tier_id
        ):
            raise _ReverseUnavailableError("The upgrade chain of this period cannot be proven.")
        if applied is not None:
            source = "previous_upgrade"
            terms_ok = self._terms_unchanged_since(s, previous, applied.paid_at)
        else:
            source = "period_payment"
            terms_ok = period.terms_version is not None and self._tier_has_terms(
                s, previous, period.terms_version
            )
        if not terms_ok:
            raise _ReverseUnavailableError("The previous plan's terms have changed since.")
        pending = sub.pending_plan_tier_id
        if pending is not None and self._renewal_price(s, pending) <= self._renewal_price(
            s, previous
        ):
            # The payer already chose a plan that costs no more: never replace it with a dearer one.
            return {"reverse_effect": "already_scheduled", "pending_plan_tier_id": pending}
        try:
            SubscriptionService(s, self._client, self._settings).schedule_downgrade(
                sub.id,
                actor_user_id=sub.payer_user_id,  # type: ignore[arg-type]
                plan_tier_id=previous,
                now=self._now(),
            )
        except SubscriptionError as exc:
            raise _ReverseUnavailableError(
                f"The previous plan cannot be restored now ({exc})."
            ) from exc
        return {
            "reverse_effect": "downgrade_scheduled",
            "previous_plan_tier_id": previous,
            "previous_tier_source": source,
        }

    @staticmethod
    def _is_upgrade_over(s: Session, old_id: uuid.UUID, new_id: uuid.UUID) -> bool:
        old, new = s.get(PlanTier, old_id), s.get(PlanTier, new_id)
        return (
            old is not None
            and new is not None
            and is_upgrade(old, current_terms(s, old), new, current_terms(s, new))
        )

    @staticmethod
    def _renewal_price(s: Session, tier_id: uuid.UUID) -> int:
        tier = s.get(PlanTier, tier_id)
        return 0 if tier is None else int(current_terms(s, tier).price_minor)

    @staticmethod
    def _tier_has_terms(s: Session, tier_id: uuid.UUID, terms_version: int) -> bool:
        """True when ``tier_id`` is at ``terms_version`` now (a downgrade applies current terms)."""
        tier = s.get(PlanTier, tier_id)
        known = s.scalar(
            select(PlanTierTerms.plan_tier_id).where(
                PlanTierTerms.plan_tier_id == tier_id,
                PlanTierTerms.terms_version == terms_version,
            )
        )
        return tier is not None and known is not None and tier.terms_version == terms_version

    @staticmethod
    def _terms_unchanged_since(s: Session, tier_id: uuid.UUID, paid_at: datetime | None) -> bool:
        """True when the tier's current terms were written no later than ``paid_at``."""
        tier = s.get(PlanTier, tier_id)
        if tier is None or paid_at is None:
            return False
        written = s.scalar(
            select(PlanTierTerms.created_at).where(
                PlanTierTerms.plan_tier_id == tier_id,
                PlanTierTerms.terms_version == tier.terms_version,
            )
        )
        return written is not None and written <= paid_at

    def _apply_success(
        self, s: Session, payment: Payment, refund: PaymentRefund
    ) -> dict[str, object]:
        """Move the status forward, take back what a full refund returns, and undo on request.

        Returns the audit notes. The status is recomputed from both sources (our refunds and
        Paymob's own total) and never lowered: a parent ``is_refunded``/``is_voided`` callback may
        have moved it while Paymob was being called. Claw-back is idempotent (a repeat returns 0).
        """
        if refund.kind is RefundKind.void:
            target = PaymentStatus.voided
        else:
            view = payment_views(s, [payment])[0]
            target = (
                PaymentStatus.refunded
                if _committed_refunded(s, view) >= payment.amount_minor
                else PaymentStatus.partially_refunded
            )
        if _RANK.get(target, 0) > _RANK.get(payment.status, 0):
            payment.status = target
        full = payment.status in (PaymentStatus.refunded, PaymentStatus.voided)
        effect: dict[str, object] = {}
        if full:
            effect = self._apply_full(s, payment, refund)
        elif refund.reverse_change:  # refused at request time; only a callback race gets here
            effect = {"reverse_effect": "not_applied_partial"}
        s.flush()
        return effect

    def _apply_full(self, s: Session, payment: Payment, refund: PaymentRefund) -> dict[str, object]:
        """What a fully refunded or voided payment gives back, by purpose (UD-4, UD-6 (a))."""
        purpose = payment.purpose
        ledger = UsageLedger(s)
        reason = f"refund {refund.id}"

        def claw(kinds: frozenset[GrantKind] | None) -> int:
            return sum(
                ledger.claw_back_grant(gid, reason=reason, now=self._now())
                for gid in _grant_ids(s, payment.id, kinds)
            )

        if purpose in _CLAWBACK_PURPOSES:  # a pack or top-up always returns its unspent units
            refund.clawed_back_units = claw(None)
            return {"reverse_effect": "same_as_full_refund"} if refund.reverse_change else {}
        if _grant_ids(s, payment.id, frozenset({GrantKind.credit_pack})):
            # The purchase bought nothing and became credits (UD-3): no plan, seat or tier was
            # applied, so Phase 05's refund hook must not run as if one had been.
            if not refund.reverse_change:
                return {"purpose_effect": "money_only", "credits_kept": True}
            refund.clawed_back_units = claw(frozenset({GrantKind.credit_pack}))
            return {"reverse_effect": "credits_clawed_back"}
        if purpose in _SUBSCRIPTION_PURPOSES:
            sub = (
                None
                if payment.subscription_id is None
                else s.get(Subscription, payment.subscription_id)
            )
            was_live = sub is not None and sub.status is not SubscriptionStatus.cancelled
            clawed_before = _clawed_total(s, payment.id)
            SubscriptionService(s, self._client, self._settings).on_payment_refunded(
                payment.id, full=True, now=self._now()
            )
            refund.clawed_back_units = _clawed_total(s, payment.id) - clawed_before
            ended = sub is not None and was_live and sub.status is SubscriptionStatus.cancelled
            effect: dict[str, object] = {"subscription_effect": "plan_ended" if ended else "none"}
            if refund.reverse_change:
                effect["reverse_effect"] = "same_as_full_refund"
            return effect
        if not refund.reverse_change:
            return {"purpose_effect": "money_only"}
        nested = s.begin_nested()
        try:
            effect = self._reverse(s, payment)
            if purpose is PaymentPurpose.upgrade_proration:  # the allowance the upgrade added
                refund.clawed_back_units = claw(frozenset({GrantKind.period_allowance}))
            nested.commit()
        except _ReverseUnavailableError as exc:
            nested.rollback()
            alerts.error(
                "admin_refund_reverse_unavailable",
                alert=True,
                refund_id=str(refund.id),
                payment_id=str(payment.id),
                reason=str(exc),
            )
            effect = {"reverse_effect": "unavailable_after_refund", "reverse_reason": str(exc)}
        return effect


__all__ = [
    "CALLBACK_GRACE",
    "HMAC_WINDOW",
    "REFUND_STUCK_AFTER",
    "REFUND_UNCLEAR_FOR",
    "STALE_PENDING_AFTER",
    "AdminPaymentsService",
    "PaymentPage",
    "ProblemQueue",
    "classify_answer",
    "classify_error",
    "redacted_error",
    "redacted_response",
]
