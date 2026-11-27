"""DTOs for ``/api/usage/*`` (billing spec §2.1, §2.4, §5.7)."""

from __future__ import annotations

import uuid  # noqa: TC003 - pydantic resolves field annotations at runtime
from datetime import datetime  # noqa: TC003 - pydantic resolves field annotations at runtime
from typing import Literal

from pydantic import Field

from lemely.core.metered_actions import MeteredAction  # noqa: TC001 - pydantic runtime
from lemely.web.schemas import ApiModel

EstimatePayer = Literal["seat", "allowance", "credits", "none"]
PaidByDTO = Literal["allowance", "seat", "credits", "teacher_credits", "mixed", "none"]


class EstimateRequestDTO(ApiModel):
    """Which action, and which record it would work on. The server reads the record.

    ``attemptId``, ``questionResultId`` and ``assignmentId`` name a record the caller owns;
    its subject and countable inputs are read from it on the server, and ``subjectCode`` and
    ``count`` are ignored for those actions. ``subjectCode``, ``origin`` and ``count`` are read only
    for the actions whose subject, deck origin and size the route itself takes from its own
    request (``origin`` is the flashcard deck's: a seat pays only for a ``weakness`` deck).
    """

    action: MeteredAction
    attemptId: uuid.UUID | None = None
    questionResultId: uuid.UUID | None = None
    assignmentId: uuid.UUID | None = None
    subjectCode: str | None = Field(default=None, min_length=1, max_length=16)
    origin: Literal["topic", "weakness"] | None = None
    count: int | None = Field(default=None, ge=1, le=50)


class EstimateDTO(ApiModel):
    """The quoted range, in units, and who pays first.

    ``percentLow``/``percentHigh`` are set only when a live plan pays, and never for an
    assistant acting for a lead: the units are public, so a percentage beside them would give
    away the lead's plan size.
    """

    low: int
    high: int
    payer: EstimatePayer
    percentLow: int | None
    percentHigh: int | None
    blockedReason: str | None


class CreditLotDTO(ApiModel):
    remaining: int
    expiresAt: datetime | None


class SeatMeterDTO(ApiModel):
    teacherMemberId: str
    teacherUserId: str
    fraction: float | None
    resetsAt: datetime | None


class UsageMeterDTO(ApiModel):
    allowanceFraction: float | None
    allowanceResetsAt: datetime | None
    creditsBalance: int
    creditLots: list[CreditLotDTO]
    seats: list[SeatMeterDTO]
    debtUnits: int


class UsageJobDTO(ApiModel):
    """One usage-history row, without allowance unit counts (spec §2.1).

    Plan and seat portions are ``percentOfPlan``; credit portions are ``credits``.
    """

    jobId: str
    action: str
    status: str
    paidBy: PaidByDTO
    percentOfPlan: float | None
    credits: int | None
    debtCredits: int | None
    estimatePercentOfPlan: list[float] | None
    #: Credits only: set when credits pay first. Null when a plan pays, whoever asks: the plan
    #: is quoted as ``estimatePercentOfPlan``, or not at all for an assistant acting for a lead.
    estimateCredits: list[int] | None
    actorUserId: str
    createdAt: datetime
    settledAt: datetime | None


class UsageHistoryDTO(ApiModel):
    jobs: list[UsageJobDTO]
    nextCursor: str | None
