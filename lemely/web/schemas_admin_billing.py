"""DTOs for the admin billing surface (``/api/admin/billing/*``, spec §8).

camelCase on the wire, ``extra="forbid"`` (``ApiModel``). Money is integer piasters, usage
integer units. The upper bounds are sanity limits that keep a typo from becoming a database
error (a ``BIGINT``/``INTEGER`` overflow), not business rules.
"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - pydantic resolves annotations at runtime
from typing import Annotated, Any, Literal

from pydantic import Field, StringConstraints

from lemely.web.schemas_admin import ApiModel

Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=2000)]
#: Piasters: up to ten billion (100 million EGP).
Money = Annotated[int, Field(ge=0, le=10**10)]
PositiveMoney = Annotated[int, Field(gt=0, le=10**10)]
#: Usage units: up to a trillion.
Units = Annotated[int, Field(ge=0, le=10**12)]
PositiveUnits = Annotated[int, Field(gt=0, le=10**12)]
Seats = Annotated[int, Field(ge=0, le=10_000)]
Code = Annotated[str, StringConstraints(pattern=r"^[a-z0-9_]{2,64}$")]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
ActionName = Annotated[str, StringConstraints(min_length=1, max_length=64)]


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


class FreeAllowanceDTO(ApiModel):
    audience: Literal["student", "teacher"]
    creditPackId: str
    units: int
    validDays: int | None


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


class PlanTierCreateDTO(ApiModel):
    code: Code
    name: Name
    audience: Literal["student", "teacher"]
    interval: Literal["monthly", "yearly"]
    priceMinor: Money
    currency: Literal["EGP"] = "EGP"
    allowanceUnits: Units
    includedSeats: Seats = 0
    seatAllowanceUnits: Units = 0
    extraSeatPriceMinor: Money = 0
    features: dict[str, Any] = Field(default_factory=dict)
    isActive: bool = True
    reason: Reason


class PlanTierUpdateDTO(ApiModel):
    """Replaces the editable fields; ``features`` is replaced whole (the client sends the merge)."""

    name: Name
    priceMinor: Money
    allowanceUnits: Units
    includedSeats: Seats
    seatAllowanceUnits: Units
    extraSeatPriceMinor: Money
    features: dict[str, Any]
    isActive: bool
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
    reason: Reason


class FreeAllowanceUpdateDTO(ApiModel):
    audience: Literal["student", "teacher"]
    units: Units
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
