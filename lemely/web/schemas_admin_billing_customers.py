"""DTOs for the admin customer view (``/api/admin/billing/customers``, spec §8 area 2).

Responses, plus the three ledger-action requests: camelCase on the wire, ``extra="forbid"``
(``ApiModel``), money in integer piasters and usage in integer units. The payment and refund
DTOs live in ``schemas_admin_billing`` because the problem queue emits them too (DV-2, DV-21).
"""

from __future__ import annotations

import uuid  # noqa: TC003 - pydantic resolves annotations at runtime
from datetime import datetime  # noqa: TC003 - pydantic resolves annotations at runtime
from typing import Annotated, Literal

from pydantic import Field

from lemely.web.schemas_admin import ApiModel
from lemely.web.schemas_admin_billing import (  # noqa: TC001 - pydantic field types
    AdminPaymentRowDTO,
    Reason,
)


class CustomerHitDTO(ApiModel):
    userId: str
    email: str
    displayName: str | None
    role: str
    matchedOn: Literal["user_id", "payment_id", "paymob_order", "email", "name"]


class CustomerSearchResultDTO(ApiModel):
    hits: list[CustomerHitDTO]


class CustomerUserDTO(ApiModel):
    id: str
    email: str
    displayName: str | None
    role: str
    createdAt: datetime


class BalanceDTO(ApiModel):
    allowanceAvailable: int
    creditsAvailable: int
    seatAvailable: int
    outstandingDebt: int


class PeriodDTO(ApiModel):
    periodStart: datetime
    periodEnd: datetime
    paymentId: str | None


class SubscriptionDTO(ApiModel):
    id: str
    planTierId: str
    planCode: str
    planName: str
    status: str
    payerUserId: str | None
    currentPeriodStart: datetime | None
    currentPeriodEnd: datetime | None
    cancelAtPeriodEnd: bool
    pendingPlanTierId: str | None
    graceUntil: datetime | None
    extraSeats: int
    pendingExtraSeats: int | None
    paymobSubscriptionId: str | None
    isManuallyActivated: bool
    periods: list[PeriodDTO]


class GrantDTO(ApiModel):
    id: str
    kind: str
    visible: bool
    units: int
    remaining: int
    held: int
    effectiveAt: datetime
    expiresAt: datetime | None
    teacherMemberId: str | None
    paymentId: str | None


class DebtDTO(ApiModel):
    id: str
    jobId: str | None
    units: int
    outstanding: int
    createdAt: datetime


class UsageJobDTO(ApiModel):
    jobId: str
    action: str
    status: str
    estimateLow: int
    estimateHigh: int
    estimatorVersion: int
    rateVersion: int
    reserved: int
    charged: int | None
    debtCreated: int | None
    actualCostUsd: str | None
    actualUnits: int | None
    outsideRange: bool
    createdAt: datetime
    settledAt: datetime | None


class MemberDTO(ApiModel):
    memberId: str
    userId: str
    email: str
    kind: str
    status: str
    scopeSubjects: list[str] | None
    scopeActions: list[str] | None
    rolePreset: str | None
    capUnits: int | None
    capPeriod: str | None
    leavesAt: datetime | None


class LinkedUserDTO(ApiModel):
    userId: str
    email: str
    displayName: str | None


class AuditEntryDTO(ApiModel):
    id: str
    adminUserId: str
    action: str
    targetKind: str
    targetId: str
    reason: str
    before: dict[str, object] | None
    after: dict[str, object] | None
    createdAt: datetime


class CustomerDetailDTO(ApiModel):
    user: CustomerUserDTO
    balance: BalanceDTO
    subscriptions: list[SubscriptionDTO]
    grants: list[GrantDTO]
    debts: list[DebtDTO]
    usageJobs: list[UsageJobDTO]
    payments: list[AdminPaymentRowDTO]
    seats: list[MemberDTO]
    assistants: list[MemberDTO]
    seatedWith: list[MemberDTO]
    parents: list[LinkedUserDTO]
    children: list[LinkedUserDTO]
    audit: list[AuditEntryDTO]


# -- ledger-action requests (Task 6) -----------------------------------------------


class AdminGrantRequestDTO(ApiModel):
    """``validDays`` absent means 365, ``null`` means no expiry (DV-30)."""

    units: Annotated[int, Field(gt=0, le=1_000_000)]
    validDays: Annotated[int, Field(gt=0, le=730)] | None = 365
    requestId: uuid.UUID
    reason: Reason


class AdminAdjustRequestDTO(ApiModel):
    """Positive adds credits, negative debits them; zero is refused by the service."""

    units: Annotated[int, Field(ge=-1_000_000, le=1_000_000)]
    requestId: uuid.UUID
    reason: Reason


class AdminForgiveRequestDTO(ApiModel):
    """``units`` absent or null forgives all the debt."""

    units: Annotated[int, Field(gt=0, le=1_000_000)] | None = None
    reason: Reason


# -- subscription-action requests (Task 7) ----------------------------------------


class ManualActivationRequestDTO(ApiModel):
    planTierId: uuid.UUID
    periodDays: Annotated[int, Field(gt=0, le=400)]
    reason: Reason


class AdminExtendRequestDTO(ApiModel):
    """``requestId`` is optional: with one, a retried request changes nothing the second time."""

    days: Annotated[int, Field(gt=0, le=366)]
    reason: Reason
    requestId: uuid.UUID | None = None


class AdminCancelRequestDTO(ApiModel):
    when: Literal["period_end", "now"]
    reason: Reason
    requestId: uuid.UUID | None = None
