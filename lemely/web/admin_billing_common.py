"""Helpers every admin billing router shares (DV-2).

Lane routers import from here, never from the parent router, so there is no import cycle.
Errors leave as ``{"code", "message"}`` in ``detail``; the status comes from the service
error's class.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import datetime  # noqa: TC003 - used in a signature FastAPI never inspects
from typing import TYPE_CHECKING, Annotated, cast

from fastapi import Depends, HTTPException

from lemely.db.admin_billing_repo import (
    AdminBillingError,
    AdminConflictError,
    AdminInvalidError,
    AdminNotFoundError,
    PaymobCallError,
)
from lemely.db.models.enums import Role
from lemely.web.deps import AuthContext, require_role
from lemely.web.schemas_admin_billing import (
    AdminPaymentRowDTO,
    RefundDTO,
    ReverseEffectName,
    ReverseOutcomeDTO,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from lemely.db.admin_billing_repo import PaymentView, ReverseEffect
    from lemely.db.models.billing_ops import PaymentRefund

AdminAuth = Annotated[AuthContext, Depends(require_role(Role.platform_admin))]

_STATUS: tuple[tuple[type[AdminBillingError], int], ...] = (
    (AdminNotFoundError, 404),
    (AdminConflictError, 409),
    (AdminInvalidError, 422),
    (PaymobCallError, 502),
)


def admin_id(auth: AuthContext) -> uuid.UUID:
    """The signed-in platform admin, for the audit row."""
    return uuid.UUID(auth.user_id)


@contextmanager
def mapped_errors() -> Iterator[None]:
    """Turn a service error into an ``HTTPException`` carrying ``{"code", "message"}``."""
    try:
        yield
    except AdminBillingError as exc:
        status = next((code for kind, code in _STATUS if isinstance(exc, kind)), 500)
        raise HTTPException(
            status_code=status, detail={"code": exc.code, "message": exc.message}
        ) from exc


def require_aware(value: datetime | None, field: str) -> datetime | None:
    """``value`` unchanged when it carries a time zone (or is absent); else 422 ``naive_datetime``.

    A naive instant compared with a ``timestamptz`` column is read in the server's zone, so a
    value the admin typed in their own is silently shifted (DV-24).
    """
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise AdminInvalidError(
            "naive_datetime", f"{field} needs a time zone, such as Z or +02:00."
        )
    return value


def optional_id(value: object | None) -> str | None:
    """``str(value)``, or ``None`` for an absent id (ids and Paymob numbers go out as strings)."""
    return None if value is None else str(value)


#: The service's audit name for an undo that could not run after the money moved; the wire
#: says what an admin needs to know, that it failed. Every other name is sent as recorded.
_REVERSE_WIRE_NAMES = {"unavailable_after_refund": "failed"}


def reverse_outcome_dto(refund: PaymentRefund, outcome: ReverseEffect | None) -> ReverseOutcomeDTO:
    """Whether the refund asked to undo the purchase, and what the undo came to (if it ran)."""
    if not refund.reverse_change or outcome is None:
        return ReverseOutcomeDTO(requested=refund.reverse_change, effect=None, reason=None)
    name = _REVERSE_WIRE_NAMES.get(outcome.effect, outcome.effect)
    return ReverseOutcomeDTO(
        requested=True, effect=cast("ReverseEffectName", name), reason=outcome.reason
    )


def refund_dto(
    refund: PaymentRefund, currency: str, outcome: ReverseEffect | None = None
) -> RefundDTO:
    """A refund attempt; ``currency`` is the payment's (DV-21)."""
    return RefundDTO(
        id=str(refund.id),
        paymentId=str(refund.payment_id),
        currency=currency,
        kind=refund.kind.value,
        status=refund.status.value,
        amountMinor=refund.amount_minor,
        reason=refund.reason,
        adminUserId=str(refund.admin_user_id),
        clawedBackUnits=refund.clawed_back_units,
        reverse=reverse_outcome_dto(refund, outcome),
        createdAt=refund.created_at,
        updatedAt=refund.updated_at,
    )


def payment_row_dto(view: PaymentView) -> AdminPaymentRowDTO:
    """A payment with its refunds and how much of it is already returned (DV-19)."""
    p = view.payment
    return AdminPaymentRowDTO(
        id=str(p.id),
        payerUserId=str(p.payer_user_id),
        beneficiaryUserId=str(p.beneficiary_user_id),
        purpose=p.purpose.value,
        status=p.status.value,
        amountMinor=p.amount_minor,
        currency=p.currency,
        refundedMinor=view.refunded_minor,
        paymobOrderId=optional_id(p.paymob_order_id),
        paymobTxnId=optional_id(p.paymob_txn_id),
        planTierId=optional_id(p.plan_tier_id),
        creditPackId=optional_id(p.credit_pack_id),
        subscriptionId=optional_id(p.subscription_id),
        seatQuantity=p.seat_quantity,
        convertedToCredits=view.credited_units is not None,
        creditedUnits=view.credited_units,
        createdAt=p.created_at,
        paidAt=p.paid_at,
        refunds=[refund_dto(r, p.currency, view.reverse_effects.get(r.id)) for r in view.refunds],
    )
