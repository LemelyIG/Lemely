"""DTOs for the admin billing surface (``/api/admin/billing/*``, spec §8).

camelCase on the wire, ``extra="forbid"`` (``ApiModel``). Money is integer piasters, usage
integer units. The upper bounds are sanity limits that keep a typo from becoming a database
error (a ``BIGINT``/``INTEGER`` overflow), not business rules.
"""

from __future__ import annotations

import json
from datetime import datetime  # noqa: TC003 - pydantic resolves annotations at runtime
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, Field, StringConstraints

from lemely.web.schemas_admin import ApiModel

Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=2000)]
#: Piasters: up to ten billion (100 million EGP).
Money = Annotated[int, Field(ge=0, le=10**10)]
#: ``plan_tiers.price_minor`` is an ``INTEGER`` column (the others are ``BIGINT``).
TierPrice = Annotated[int, Field(ge=0, le=2**31 - 1)]
PositiveMoney = Annotated[int, Field(gt=0, le=10**10)]
#: Usage units: up to a trillion.
Units = Annotated[int, Field(ge=0, le=10**12)]
PositiveUnits = Annotated[int, Field(gt=0, le=10**12)]
Seats = Annotated[int, Field(ge=0, le=10_000)]
Code = Annotated[str, StringConstraints(pattern=r"^[a-z0-9_]{2,64}$")]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
ActionName = Annotated[str, StringConstraints(min_length=1, max_length=64)]
#: ``version`` is an ``INTEGER`` column; an expected version is one the client read.
ExpectedVersion = Annotated[int, Field(ge=1, le=2**31 - 1)]
#: ``credit_packs.signup_validity_days`` (``ck_credit_packs_signup_validity``): 1 day to 10 years.
ValidDays = Annotated[int, Field(ge=1, le=3650)]
#: ``features`` is free-form JSON stored as JSONB: cap the key count and the serialised size.
FEATURES_MAX_BYTES = 16 * 1024


def _bounded_features(value: dict[str, Any]) -> dict[str, Any]:
    if len(json.dumps(value, separators=(",", ":"), default=str)) > FEATURES_MAX_BYTES:
        raise ValueError(f"features must serialise to at most {FEATURES_MAX_BYTES} bytes")
    return value


Features = Annotated[dict[str, Any], Field(max_length=100), AfterValidator(_bounded_features)]


class ReasonDTO(ApiModel):
    reason: Reason


# -- catalogue ------------------------------------------------------------------


class PlanTierDTO(ApiModel):
    id: str
    code: str
    name: str
    audience: str
    interval: str | None
    priceMinor: int
    currency: str
    allowanceUnits: int
    includedSeats: int
    seatAllowanceUnits: int
    extraSeatPriceMinor: int
    features: dict[str, Any]
    isActive: bool
    version: int
    termsVersion: int
    liveSubscriptionCount: int
    pendingMoves: int
    paymobPlanId: int | None
    paymobDrift: Literal["in_sync", "not_synced", "unverified", "drifted"]


class CreditPackDTO(ApiModel):
    id: str
    code: str
    name: str
    units: int
    priceMinor: int
    currency: str
    isActive: bool
    version: int
    autoTopupCount: int
    autoTopupCapBelowPriceCount: int


class PackPriceImpactDTO(ApiModel):
    """Auto top-ups on a pack at a proposed price (a preview; nothing is saved).

    Counts only settings that can charge: enabled, consented, with a saved card, on an active pack.
    """

    autoTopupCount: Annotated[int, Field(ge=0, le=10**9)]
    capBelowPriceCount: Annotated[int, Field(ge=0, le=10**9)]


class FreeAllowanceDTO(ApiModel):
    audience: Literal["student", "teacher"]
    creditPackId: str
    units: int
    validDays: int | None
    version: int


class UsageRateDTO(ApiModel):
    id: str
    version: int
    action: str
    unitsPerUsd: int
    effectiveFrom: datetime


class UsageEstimatorDTO(ApiModel):
    id: str
    version: int
    action: str
    inputKind: str
    baseLow: int
    baseHigh: int
    perInputLow: int
    perInputHigh: int
    effectiveFrom: datetime


class AdminCatalogueDTO(ApiModel):
    planTiers: list[PlanTierDTO]
    creditPacks: list[CreditPackDTO]
    freeAllowances: list[FreeAllowanceDTO]
    usageRates: list[UsageRateDTO]
    usageEstimators: list[UsageEstimatorDTO]
    subscriptionAmountUpdatable: bool
    priceChangeNoticeDays: int


class PlanTierCreateDTO(ApiModel):
    code: Code
    name: Name
    audience: Literal["student", "teacher"]
    interval: Literal["monthly", "yearly"]
    priceMinor: TierPrice
    currency: Literal["EGP"] = "EGP"
    allowanceUnits: Units
    includedSeats: Seats = 0
    seatAllowanceUnits: Units = 0
    extraSeatPriceMinor: Money = 0
    features: Features = Field(default_factory=dict)
    isActive: bool = True
    reason: Reason


class PlanTierUpdateDTO(ApiModel):
    """Replaces the editable fields; ``features`` is replaced whole (the client sends the merge)."""

    name: Name
    priceMinor: TierPrice
    allowanceUnits: Units
    includedSeats: Seats
    seatAllowanceUnits: Units
    extraSeatPriceMinor: Money
    features: Features
    isActive: bool
    expectedVersion: ExpectedVersion | None = None
    reason: Reason


class CreditPackCreateDTO(ApiModel):
    code: Code
    name: Name
    units: PositiveUnits
    priceMinor: PositiveMoney
    currency: Literal["EGP"] = "EGP"
    isActive: bool = True
    reason: Reason


class CreditPackUpdateDTO(ApiModel):
    name: Name
    units: PositiveUnits
    priceMinor: PositiveMoney
    isActive: bool
    expectedVersion: ExpectedVersion | None = None
    reason: Reason


class FreeAllowanceUpdateDTO(ApiModel):
    audience: Literal["student", "teacher"]
    units: Units
    #: Absent keeps the stored value; ``null`` means never expires.
    validDays: ValidDays | None = None
    expectedVersion: ExpectedVersion | None = None
    reason: Reason


class UsageRateVersionDTO(ApiModel):
    action: ActionName
    unitsPerUsd: PositiveUnits
    effectiveFrom: datetime | None = None
    reason: Reason


class UsageEstimatorVersionDTO(ApiModel):
    action: ActionName
    inputKind: Literal["pages", "marks", "questions", "none"]
    baseLow: Units
    baseHigh: Units
    perInputLow: Units
    perInputHigh: Units
    effectiveFrom: datetime | None = None
    reason: Reason


# -- payments (shared by the customer view and the problem queue) ----------------


#: What a requested reverse did, by the service's own outcomes. ``failed``: the money was
#: returned but the undo could not run (``reason`` says why); an operator is alerted.
ReverseEffectName = Literal[
    "same_as_full_refund",
    "nothing_ended",
    "credits_clawed_back",
    "seat_reduction_scheduled",
    "already_scheduled",
    "plan_ends_at_period_end",
    "downgrade_scheduled",
    "not_applied_partial",
    "failed",
]


class ReverseOutcomeDTO(ApiModel):
    """``effect`` is ``None`` while there is no outcome: not requested, or not succeeded yet."""

    requested: bool
    effect: ReverseEffectName | None
    reason: str | None


class RefundDTO(ApiModel):
    id: str
    paymentId: str
    currency: str
    kind: Literal["refund", "void"]
    status: Literal["requested", "succeeded", "failed", "unknown"]
    amountMinor: int
    reason: str
    adminUserId: str
    clawedBackUnits: int
    reverse: ReverseOutcomeDTO
    createdAt: datetime
    updatedAt: datetime


class AdminPaymentRowDTO(ApiModel):
    id: str
    payerUserId: str
    beneficiaryUserId: str
    purpose: str
    status: str
    amountMinor: int
    currency: str
    refundedMinor: int
    paymobOrderId: str | None
    paymobTxnId: str | None
    planTierId: str | None
    creditPackId: str | None
    subscriptionId: str | None
    seatQuantity: int | None
    convertedToCredits: bool
    creditedUnits: int | None
    seatRenewalCharge: bool
    createdAt: datetime
    paidAt: datetime | None
    refunds: list[RefundDTO]
