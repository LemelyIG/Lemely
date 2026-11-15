"""DTOs for the money and margin report (``/api/admin/billing/margin``, spec §8 area 4).

Responses only: camelCase on the wire, ``extra="forbid"`` (``ApiModel``). Money is integer
piasters, usage is integer units, and USD leaves as a 6-decimal string so no float rounds it.
The keys equal ``MarginReport`` in ``web/src/lib/billingTypes.ts``, field for field.
"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - pydantic resolves annotations at runtime
from typing import Literal

from pydantic import Field

from lemely.web.schemas_admin import ApiModel


class MoneyByKeyDTO(ApiModel):
    key: str
    minor: int


class CostRowDTO(ApiModel):
    key: str | None
    jobs: int
    costUsd: str


class ModelCostDTO(ApiModel):
    model: str
    costUsd: str


class RevenueDTO(ApiModel):
    recurringMinor: int
    packsMinor: int
    refundedMinor: int
    netMinor: int
    byPurpose: dict[str, int]
    byPlan: list[MoneyByKeyDTO]


class CostDTO(ApiModel):
    """LLM cost is the metered settled cost; it excludes released or exempt spend."""

    totalUsd: str = Field(description="Metered settled cost; excludes released or exempt spend.")
    byAction: list[CostRowDTO]
    byPlan: list[CostRowDTO]
    byModel: list[ModelCostDTO]
    unattributedModelUsd: str


class AccuracyRowDTO(ApiModel):
    action: str
    estimatorVersion: int
    jobs: int
    below: int
    above: int
    shareOutside: float
    meanOverrunUnits: float | None
    maxOverrunUnits: int | None


class DebtorDTO(ApiModel):
    userId: str
    email: str
    outstanding: int


class ExpiredJobsDTO(ApiModel):
    """Jobs that expired unsettled. No cost: an expired job never has one recorded."""

    count: int


class ExposureDTO(ApiModel):
    outstandingDebtUnits: int
    debtors: int
    topDebtors: list[DebtorDTO]
    usersAtLimit: int
    creditsExpiring30dUnits: int
    creditsExpiring30dOwners: int
    creditsExpiredUnusedUnits: int
    expiredJobs: ExpiredJobsDTO


class MarginReportDTO(ApiModel):
    windowStart: datetime
    windowEnd: datetime
    revenue: RevenueDTO
    cost: CostDTO
    egpPerUsd: str | None
    egpPerUsdSource: Literal["request", "settings"] | None
    costMinor: int | None
    marginMinor: int | None
    accuracy: list[AccuracyRowDTO]
    exposure: ExposureDTO
