"""Request DTOs for the admin payments money actions (``/api/admin/billing/payments``, spec §8).

camelCase on the wire, ``extra="forbid"`` (``ApiModel``). The payment and refund response DTOs
live in ``schemas_admin_billing`` because the customer view and the problem queue emit them too
(DV-2, DV-21).
"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - pydantic field type
from typing import Literal

from lemely.web.schemas_admin import ApiModel
from lemely.web.schemas_admin_billing import (  # noqa: TC001 - pydantic field types
    AdminPaymentRowDTO,
    PositiveMoney,
    Reason,
    RefundDTO,
)


class AdminVoidRequestDTO(ApiModel):
    """A void is always full, so there is no amount. ``reverseChange`` also undoes the purchase."""

    reverseChange: bool = False
    reason: Reason


class AdminRefundRequestDTO(ApiModel):
    """``amountMinor`` ``None`` refunds everything not yet refunded.

    ``reverseChange`` also undoes what the payment bought (UD-4); the default is money only.
    """

    amountMinor: PositiveMoney | None = None
    reverseChange: bool = False
    reason: Reason


WebhookKind = Literal["transaction", "token", "subscription"]


class AdminPaymentsPageDTO(ApiModel):
    items: list[AdminPaymentRowDTO]
    nextCursor: str | None


class WebhookFailureDTO(ApiModel):
    """A callback Paymob sent that failed its HMAC check. No body is stored.

    ``remoteAddr`` is the *reported* address (taken from ``X-Forwarded-For``, so a caller can
    choose it): show it as plain text under that label, never as a verified source.
    """

    id: str
    kind: WebhookKind
    reason: str
    remoteAddr: str | None
    receivedAt: datetime


class ProblemQueueDTO(ApiModel):
    mismatches: list[AdminPaymentRowDTO]
    stalePending: list[AdminPaymentRowDTO]
    missingCallbacks: list[AdminPaymentRowDTO]
    hmacFailures: list[WebhookFailureDTO]
    hmacFailures24h: int
    refundsNeedingAttention: list[RefundDTO]
