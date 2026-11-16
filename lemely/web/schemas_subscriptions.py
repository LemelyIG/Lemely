"""Subscription API DTOs (camelCase wire format; billing spec §2.1, §7, index R3).

Field names match the built frontend's wire types (``web/src/lib/billingTypes.ts``): rename
nothing here without changing them.
"""

# Pydantic's mypy plugin injects Any into generated __init__ signatures (the rule that
# pyproject.toml's per-module override applies to the other schemas_* modules).
# mypy: disallow-any-explicit=False
from __future__ import annotations

import uuid  # noqa: TC003 - pydantic reads the type at runtime
from datetime import datetime  # noqa: TC003 - pydantic reads the type at runtime
from typing import Literal

from pydantic import Field

from lemely.web.schemas import ApiModel
from lemely.web.schemas_billing import (
    PlanTierDTO,  # noqa: TC001 - pydantic reads the type at runtime
)


class SummaryBeneficiaryDTO(ApiModel):
    userId: str
    displayName: str | None
    audience: str


class PendingTermsChangeDTO(ApiModel):
    """A noticed move to the plan's newer terms (UD13-A), as the payer's own screen shows it.

    Shown to the signed-in payer only; the email about the same move states no amount (UD13-E).
    Allowance sizes are never shown (spec §2.1): ``allowanceChange`` says whether the usage
    allowance gets larger or smaller. ``effectiveAt`` is when the notice period ends and
    ``firstRenewalAt`` the first renewal the new terms apply to.
    """

    effectiveAt: datetime
    firstRenewalAt: datetime | None
    priceMinor: int
    extraSeatPriceMinor: int
    includedSeats: int
    priceChanges: bool
    allowanceChange: Literal["more", "less"] | None
    includedSeatsChanges: bool
    seatAllowanceChanges: bool
    endsInsteadOfMoving: bool


class SubscriptionViewDTO(ApiModel):
    subscriptionId: str
    status: str
    tier: PlanTierDTO
    currentPeriodStart: datetime | None
    currentPeriodEnd: datetime | None
    cancelAtPeriodEnd: bool
    pendingTier: PlanTierDTO | None
    graceUntil: datetime | None
    extraSeats: int
    pendingExtraSeats: int | None
    pendingTermsChange: PendingTermsChangeDTO | None = None
    cancelReason: Literal["plan_terms_changed"] | None = None
    """Why the plan is cancelling when the payer did not ask: the platform scheduled it because a
    price change cannot be charged to this subscription. The payer subscribes again when it ends."""


class SavedCardViewDTO(ApiModel):
    cardId: str
    maskedPan: str
    brand: str | None


class UsageMeterViewDTO(ApiModel):
    fraction: float | None
    resetsAt: datetime | None


class CreditLotDTO(ApiModel):
    units: int
    expiresAt: datetime | None


class CreditsViewDTO(ApiModel):
    totalUnits: int
    expiring: list[CreditLotDTO]


class SeatsViewDTO(ApiModel):
    capacity: int
    used: int


class BillingSummaryDTO(ApiModel):
    beneficiary: SummaryBeneficiaryDTO
    subscription: SubscriptionViewDTO | None
    canManage: bool
    managedByName: str | None
    savedCard: SavedCardViewDTO | None
    usage: UsageMeterViewDTO
    credits: CreditsViewDTO
    debtUnits: int
    seats: SeatsViewDTO | None


# -- subscription checkout and plan changes (Phase 05, T11) ---------------------------------------


class SubscriptionCheckoutRequestDTO(ApiModel):
    """Body for ``POST /api/billing/subscriptions/checkout``; the price is never client-sent."""

    planTierId: uuid.UUID
    beneficiaryId: uuid.UUID | None = None
    extraSeats: int = Field(default=0, ge=0, le=200)


class SubscriptionCheckoutDTO(ApiModel):
    subscriptionId: str
    paymentId: str
    checkoutUrl: str


class DowngradeRequestDTO(ApiModel):
    planTierId: uuid.UUID


class SubscriptionDTO(ApiModel):
    id: str
    beneficiaryUserId: str
    isPayer: bool
    planTierId: str
    planCode: str
    planName: str
    status: str
    currentPeriodStart: datetime | None
    currentPeriodEnd: datetime | None
    graceUntil: datetime | None
    cancelAtPeriodEnd: bool
    pendingPlanTierId: str | None
    extraSeats: int


class SubscriptionListDTO(ApiModel):
    subscriptions: list[SubscriptionDTO]
