"""Billing API DTOs (camelCase wire format; billing spec §5.5, §2.5).

Allowance sizes are deliberately absent from the catalogue: users see a usage
meter, never the unit count behind it (spec §2.1).
"""

from __future__ import annotations

import uuid  # noqa: TC003 - pydantic reads the type at runtime
from datetime import datetime  # noqa: TC003 - pydantic reads the type at runtime
from typing import Any, Literal

from pydantic import Field

from lemely.web.schemas import ApiModel


class PlanTierDTO(ApiModel):
    planTierId: str
    code: str
    name: str
    priceMinor: int
    currency: str
    interval: str | None = None
    audience: str
    includedSeats: int
    extraSeatPriceMinor: int
    features: dict[str, Any] = Field(default_factory=dict)


class CreditPackDTO(ApiModel):
    creditPackId: str
    code: str
    name: str
    credits: int
    priceMinor: int
    currency: str


class PublicPlanTierDTO(ApiModel):
    """A tier as the public pricing page shows it: no ids, no Paymob link, no allowances."""

    code: str
    name: str
    audience: str
    interval: str | None = None
    priceMinor: int
    currency: str
    features: dict[str, Any] = Field(default_factory=dict)
    #: Teacher tiers only; ``None`` on student tiers.
    includedSeats: int | None = None
    extraSeatPriceMinor: int | None = None


class PublicCreditPackDTO(ApiModel):
    """A pack as the public pricing page shows it (credits are visible by design)."""

    code: str
    name: str
    units: int
    priceMinor: int
    currency: str


class PublicCatalogueDTO(ApiModel):
    """Response for ``GET /api/billing/public-catalogue?audience=…`` (no auth)."""

    audience: str
    planTiers: list[PublicPlanTierDTO] = Field(default_factory=list)
    creditPacks: list[PublicCreditPackDTO] = Field(default_factory=list)


class CatalogueDTO(ApiModel):
    """Response for ``GET /api/billing/catalogue``."""

    planTiers: list[PlanTierDTO] = Field(default_factory=list)
    creditPacks: list[CreditPackDTO] = Field(default_factory=list)


class PackCheckoutRequest(ApiModel):
    """Body for ``POST /api/billing/checkout/pack``; the price is never client-sent."""

    creditPackId: uuid.UUID
    beneficiaryId: uuid.UUID | None = None


class CheckoutDTO(ApiModel):
    paymentId: str
    checkoutUrl: str


class PaymentStatusDTO(ApiModel):
    """Response for ``GET /api/billing/payments/{id}`` (the return page polls it)."""

    paymentId: str
    status: str
    purpose: str
    amountMinor: int
    currency: str
    description: str
    paidAt: datetime | None = None
    #: Credits an upgrade or seat payment was turned into when its effect was void at settle
    #: time (the plan ended, the period rolled, a later change landed); ``None`` otherwise.
    creditedUnits: int | None = None
    #: What a paid upgrade or seat payment came to: ``applied`` (the change took effect),
    #: ``credited`` (turned into ``creditedUnits``) or ``needs_attention`` (paid, but neither
    #: applied nor converted, e.g. no credit rate: the payment was received and is being handled).
    #: ``None`` for any other purpose and for a payment not yet paid.
    outcome: Literal["applied", "credited", "needs_attention"] | None = None
    #: Why an upgrade or seat payment was voided (``plan_ended``, ``period_rolled``,
    #: ``superseded``, ``seats_over_limit``...), whether it was then credited or left for a
    #: manual refund; ``None`` when it was not voided and for any other purpose.
    voidReason: str | None = None


class ReceiptDTO(ApiModel):
    paymentId: str
    purpose: str
    description: str
    amountMinor: int
    currency: str
    status: str
    paidAt: datetime
    beneficiaryId: str


class ReceiptListDTO(ApiModel):
    """Response for ``GET /api/billing/receipts``: money the caller paid (§2.5)."""

    receipts: list[ReceiptDTO] = Field(default_factory=list)


class SavedCardView(ApiModel):
    """One saved card, masked only; the token never leaves the server (spec §7)."""

    cardId: str
    maskedPan: str
    brand: str


class SavedCardList(ApiModel):
    """Response for ``GET /api/billing/cards`` (index R3; Phase 08's ``SavedCardList``)."""

    cards: list[SavedCardView] = Field(default_factory=list)
