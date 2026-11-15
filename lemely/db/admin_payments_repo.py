"""Admin payments (spec §6 refunds, §8 area 3): refund and void.

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
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

from sqlalchemy import select

from lemely.db.admin_billing_repo import (
    AdminConflictError,
    AdminInvalidError,
    AdminNotFoundError,
    AuditAction,
    AuditTarget,
    PaymentView,
    alerts,
    audited,
    payment_views,
    require_reason,
)
from lemely.db.billing_repo import _outcome_unknown
from lemely.db.models.billing import Payment, PaymentPurpose, PaymentStatus
from lemely.db.models.billing_ops import PaymentRefund, RefundKind, RefundStatus
from lemely.db.models.usage import UsageGrant
from lemely.db.usage_ledger_repo import UsageLedger
from lemely.io.paymob.client import PaymobError

if TYPE_CHECKING:
    import uuid
    from collections.abc import Callable

    from sqlalchemy.orm import Session, sessionmaker

    from lemely.io.paymob.client import PaymobClient
    from lemely.runtime.config import PaymobSettings

_REFUNDABLE: Final = frozenset({PaymentStatus.paid, PaymentStatus.partially_refunded})
_IN_FLIGHT: Final = frozenset({RefundStatus.requested, RefundStatus.unknown})
_CLAWBACK_PURPOSES: Final = frozenset({PaymentPurpose.credit_pack, PaymentPurpose.auto_topup})
#: Purposes whose refund changes no plan yet: a subscription payment waits for Phase 05's
#: ``on_payment_refunded`` (DV-20); a proration or extra-seat payment waits for UD-4 (Part C).
_SUBSCRIPTION_PURPOSES: Final = frozenset(
    {PaymentPurpose.subscription_first, PaymentPurpose.subscription_renewal}
)
_MONEY_ONLY_PURPOSES: Final = frozenset(
    {PaymentPurpose.upgrade_proration, PaymentPurpose.extra_seats}
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
_KEPT: Final = ("id", "success", "pending", "amount_cents", "is_refund", "is_void", "created_at")


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


class AdminPaymentsService:
    """Refund and void (this task); list, problem queue and reconcile arrive with Task 9."""

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
    ) -> PaymentView:
        """Refund ``amount_minor`` piasters (``None`` = everything not yet refunded)."""
        return self._run(payment_id, RefundKind.refund, amount_minor, admin_user_id, reason)

    def void(self, payment_id: uuid.UUID, *, admin_user_id: uuid.UUID, reason: str) -> PaymentView:
        """Void a paid, never-refunded payment (Paymob allows it until settlement)."""
        return self._run(payment_id, RefundKind.void, None, admin_user_id, reason)

    def _run(
        self,
        payment_id: uuid.UUID,
        kind: RefundKind,
        amount_minor: int | None,
        admin_user_id: uuid.UUID,
        reason: str,
    ) -> PaymentView:
        require_reason(reason)
        refund_id, txn_id, amount = self._open_refund(
            payment_id,
            kind=kind,
            amount_minor=amount_minor,
            admin_user_id=admin_user_id,
            reason=reason,
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
        self._close_refund(
            refund_id, outcome=outcome, response=stored, admin_user_id=admin_user_id, reason=reason
        )
        return self.payment_view(payment_id)

    def _open_refund(
        self,
        payment_id: uuid.UUID,
        *,
        kind: RefundKind,
        amount_minor: int | None,
        admin_user_id: uuid.UUID,
        reason: str,
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
            refunded = view.refunded_minor
            if kind is RefundKind.void:
                if payment.status is not PaymentStatus.paid or refunded:
                    raise AdminConflictError(
                        "not_voidable", "Only a paid, unrefunded payment voids."
                    )
                amount = payment.amount_minor
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
            if payment.paymob_txn_id is None:
                raise AdminConflictError(
                    "no_paymob_transaction", "Paymob never charged this payment."
                )
            row = PaymentRefund(
                payment_id=payment.id,
                admin_user_id=admin_user_id,
                kind=kind,
                status=RefundStatus.requested,
                amount_minor=amount,
                reason=reason.strip(),
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
                {"refund_id": row.id, "kind": kind, "amount_minor": amount},
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

        Task 9's reconcile reuses this to settle an ``unknown`` row.
        """
        with self._sm.begin() as s:
            payment_id = s.scalars(
                select(PaymentRefund.payment_id).where(PaymentRefund.id == refund_id)
            ).one()
            payment = s.get(Payment, payment_id, with_for_update=True)
            refund = s.get(PaymentRefund, refund_id, with_for_update=True)
            assert payment is not None and refund is not None  # noqa: S101 - rows written by _open_refund
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

    def _apply_success(
        self, s: Session, payment: Payment, refund: PaymentRefund
    ) -> dict[str, object]:
        """Move the status forward only and claw back a fully refunded pack. Returns audit notes.

        The status is recomputed from both sources (our succeeded refunds and Paymob's own
        total), and never lowered: a parent ``is_refunded``/``is_voided`` callback may have
        moved it while Paymob was being called. ``claw_back_grant`` is idempotent, so a repeat
        returns 0.
        """
        if refund.kind is RefundKind.void:
            target = PaymentStatus.voided
        else:
            refunded = payment_views(s, [payment])[0].refunded_minor
            target = (
                PaymentStatus.refunded
                if refunded >= payment.amount_minor
                else PaymentStatus.partially_refunded
            )
        if _RANK.get(target, 0) > _RANK.get(payment.status, 0):
            payment.status = target
        full = payment.status in (PaymentStatus.refunded, PaymentStatus.voided)
        if full and payment.purpose in _CLAWBACK_PURPOSES:
            ledger = UsageLedger(s)
            grant_ids = s.scalars(
                select(UsageGrant.id)
                .where(UsageGrant.payment_id == payment.id)
                .order_by(UsageGrant.created_at)
            ).all()
            refund.clawed_back_units = sum(
                ledger.claw_back_grant(gid, reason=f"refund {refund.id}", now=self._now())
                for gid in grant_ids
            )
        s.flush()
        if payment.purpose in _SUBSCRIPTION_PURPOSES:
            return {"subscription_effect": "pending_phase05"}
        if payment.purpose in _MONEY_ONLY_PURPOSES:
            return {"purpose_effect": "money_only"}
        return {}


__all__ = [
    "AdminPaymentsService",
    "classify_answer",
    "classify_error",
    "redacted_error",
    "redacted_response",
]
