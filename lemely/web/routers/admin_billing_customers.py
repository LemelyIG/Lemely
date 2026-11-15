"""Admin billing, area 2: customer search and the customer detail (spec §8).

A lane router of ``admin_billing`` (DV-2). It is mounted in ``app.py`` beside the parent with
the full prefix, and carries its own ``platform_admin`` guard: FastAPI 0.138 keeps a router
included into another as a lazy wrapper, so ``flatten_routes`` (the authz matrix and
``test_admin_billing_authz``) would see ``/customers`` without the parent's prefix. Mounted
directly, the discovery tests see the real path and check this guard. The prefix stops at
``/api/admin/billing`` because the lane also owns ``/subscriptions/...`` (Task 7); every route
spells its own ``/customers`` or ``/subscriptions`` segment. Task 6 appends the ledger actions
(grant, adjust, forgive debt) below the reads; Task 7 the subscription ones.
"""

# FastAPI ``Depends``/``response_model`` and pydantic construction need these type imports at
# runtime (see the per-file-ignore in pyproject.toml).
from __future__ import annotations

import uuid  # noqa: TC003 - FastAPI resolves the path-parameter type at runtime
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, Query

from lemely.db.admin_customer_repo import AdminCustomerService, CustomerDetail, JobView, MemberView
from lemely.db.models.enums import Role
from lemely.web.admin_billing_common import (
    AdminAuth,
    admin_id,
    mapped_errors,
    optional_id,
    payment_row_dto,
)
from lemely.web.deps import require_role
from lemely.web.deps_admin_billing import get_admin_customer_service
from lemely.web.schemas_admin_billing_customers import (
    AdminAdjustRequestDTO,
    AdminCancelRequestDTO,
    AdminExtendRequestDTO,
    AdminForgiveRequestDTO,
    AdminGrantRequestDTO,
    AuditEntryDTO,
    BalanceDTO,
    CustomerDetailDTO,
    CustomerHitDTO,
    CustomerSearchResultDTO,
    CustomerUserDTO,
    DebtDTO,
    GrantDTO,
    LinkedUserDTO,
    ManualActivationRequestDTO,
    MemberDTO,
    PeriodDTO,
    SubscriptionDTO,
    UsageJobDTO,
)

if TYPE_CHECKING:
    from lemely.db.models.admin_audit import AdminAuditLog
    from lemely.db.models.users import User

router = APIRouter(
    prefix="/api/admin/billing",
    dependencies=[Depends(require_role(Role.platform_admin))],
)

CustomerService = Annotated[AdminCustomerService, Depends(get_admin_customer_service)]


def _member_dto(view: MemberView) -> MemberDTO:
    m = view.member
    return MemberDTO(
        memberId=str(m.id),
        userId=str(view.other_user_id),
        email=view.other_email,
        kind=m.kind.value,
        status=m.status.value,
        scopeSubjects=list(m.scope_subjects) if m.scope_subjects is not None else None,
        scopeActions=list(m.scope_actions) if m.scope_actions is not None else None,
        rolePreset=m.role_preset.value if m.role_preset is not None else None,
        capUnits=m.cap_units,
        capPeriod=m.cap_period.value if m.cap_period is not None else None,
        leavesAt=m.leaves_at,
    )


def _linked(u: User) -> LinkedUserDTO:
    return LinkedUserDTO(userId=str(u.id), email=u.email, displayName=u.display_name)


def _job_dto(view: JobView) -> UsageJobDTO:
    j = view.job
    return UsageJobDTO(
        jobId=str(j.job_id),
        action=j.action,
        status=j.status.value,
        estimateLow=j.estimate_low,
        estimateHigh=j.estimate_high,
        estimatorVersion=j.estimator_version,
        rateVersion=j.rate_version,
        reserved=j.reserved,
        charged=j.charged,
        debtCreated=j.debt_created,
        actualCostUsd=None if j.actual_cost_usd is None else f"{j.actual_cost_usd:.6f}",
        actualUnits=view.actual_units,
        outsideRange=view.outside_range,
        createdAt=j.created_at,
        settledAt=j.settled_at,
    )


def _audit_dto(a: AdminAuditLog) -> AuditEntryDTO:
    return AuditEntryDTO(
        id=str(a.id),
        adminUserId=str(a.admin_user_id),
        action=a.action,
        targetKind=a.target_kind,
        targetId=str(a.target_id),
        reason=a.reason,
        before=a.before,
        after=a.after,
        createdAt=a.created_at,
    )


def customer_detail_dto(d: CustomerDetail) -> CustomerDetailDTO:
    return CustomerDetailDTO(
        user=CustomerUserDTO(
            id=str(d.user.id),
            email=d.user.email,
            displayName=d.user.display_name,
            role=d.user.role.value,
            createdAt=d.user.created_at,
        ),
        balance=BalanceDTO(
            allowanceAvailable=d.balance.allowance_available,
            creditsAvailable=d.balance.credits_available,
            seatAvailable=d.balance.seat_available,
            outstandingDebt=d.balance.outstanding_debt,
        ),
        subscriptions=[
            SubscriptionDTO(
                id=str(v.subscription.id),
                planTierId=str(v.subscription.plan_tier_id),
                planCode=v.plan_code,
                planName=v.plan_name,
                status=v.subscription.status.value,
                payerUserId=optional_id(v.subscription.payer_user_id),
                currentPeriodStart=v.subscription.current_period_start,
                currentPeriodEnd=v.subscription.current_period_end,
                cancelAtPeriodEnd=bool(v.subscription.cancel_at_period_end),
                pendingPlanTierId=optional_id(v.subscription.pending_plan_tier_id),
                graceUntil=v.subscription.grace_until,
                extraSeats=v.subscription.extra_seats or 0,
                pendingExtraSeats=v.subscription.pending_extra_seats,
                paymobSubscriptionId=optional_id(v.subscription.paymob_subscription_id),
                isManuallyActivated=v.subscription.is_manually_activated,
                periods=[
                    PeriodDTO(
                        periodStart=p.period_start,
                        periodEnd=p.period_end,
                        paymentId=optional_id(p.payment_id),
                    )
                    for p in v.periods
                ],
            )
            for v in d.subscriptions
        ],
        grants=[
            GrantDTO(
                id=str(g.grant.id),
                kind=g.grant.kind.value,
                visible=g.grant.visible,
                units=g.grant.units,
                remaining=g.remaining,
                held=g.held,
                effectiveAt=g.grant.effective_at,
                expiresAt=g.grant.expires_at,
                teacherMemberId=optional_id(g.grant.teacher_member_id),
                paymentId=optional_id(g.grant.payment_id),
            )
            for g in d.grants
        ],
        debts=[
            DebtDTO(
                id=str(x.id),
                jobId=optional_id(x.job_id),
                units=x.units,
                outstanding=x.outstanding,
                createdAt=x.created_at,
            )
            for x in d.debts
        ],
        usageJobs=[_job_dto(j) for j in d.jobs],
        payments=[payment_row_dto(p) for p in d.payments],
        seats=[_member_dto(m) for m in d.seats],
        assistants=[_member_dto(m) for m in d.assistants],
        seatedWith=[_member_dto(m) for m in d.seated_with],
        parents=[_linked(u) for u in d.parents],
        children=[_linked(u) for u in d.children],
        audit=[_audit_dto(a) for a in d.audit],
    )


@router.get("/customers", response_model=CustomerSearchResultDTO)
def search_customers(
    service: CustomerService,
    q: Annotated[str, Query(min_length=1, max_length=200)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> CustomerSearchResultDTO:
    with mapped_errors():
        hits = service.search(q, limit=limit)
    return CustomerSearchResultDTO(
        hits=[
            CustomerHitDTO(
                userId=str(h.user_id),
                email=h.email,
                displayName=h.display_name,
                role=h.role,
                matchedOn=h.matched_on,
            )
            for h in hits
        ]
    )


@router.get("/customers/{user_id}", response_model=CustomerDetailDTO)
def get_customer(user_id: uuid.UUID, service: CustomerService) -> CustomerDetailDTO:
    with mapped_errors():
        return customer_detail_dto(service.detail(user_id))


@router.post("/customers/{user_id}/grant", response_model=CustomerDetailDTO)
def grant_credits(
    user_id: uuid.UUID, body: AdminGrantRequestDTO, service: CustomerService, auth: AdminAuth
) -> CustomerDetailDTO:
    with mapped_errors():
        return customer_detail_dto(
            service.grant_credits(
                user_id,
                units=body.units,
                valid_days=body.validDays,
                request_id=body.requestId,
                admin_user_id=admin_id(auth),
                reason=body.reason,
            )
        )


@router.post("/customers/{user_id}/adjust", response_model=CustomerDetailDTO)
def adjust_balance(
    user_id: uuid.UUID, body: AdminAdjustRequestDTO, service: CustomerService, auth: AdminAuth
) -> CustomerDetailDTO:
    with mapped_errors():
        return customer_detail_dto(
            service.adjust(
                user_id,
                units=body.units,
                request_id=body.requestId,
                admin_user_id=admin_id(auth),
                reason=body.reason,
            )
        )


@router.post("/customers/{user_id}/forgive-debt", response_model=CustomerDetailDTO)
def forgive_debt(
    user_id: uuid.UUID, body: AdminForgiveRequestDTO, service: CustomerService, auth: AdminAuth
) -> CustomerDetailDTO:
    with mapped_errors():
        return customer_detail_dto(
            service.forgive_debt(
                user_id, units=body.units, admin_user_id=admin_id(auth), reason=body.reason
            )
        )


@router.post("/customers/{user_id}/manual-activation", response_model=CustomerDetailDTO)
def manual_activation(
    user_id: uuid.UUID, body: ManualActivationRequestDTO, service: CustomerService, auth: AdminAuth
) -> CustomerDetailDTO:
    with mapped_errors():
        return customer_detail_dto(
            service.manual_activation(
                user_id,
                plan_tier_id=body.planTierId,
                period_days=body.periodDays,
                admin_user_id=admin_id(auth),
                reason=body.reason,
            )
        )


@router.post("/subscriptions/{subscription_id}/extend", response_model=CustomerDetailDTO)
def extend_subscription(
    subscription_id: uuid.UUID,
    body: AdminExtendRequestDTO,
    service: CustomerService,
    auth: AdminAuth,
) -> CustomerDetailDTO:
    with mapped_errors():
        return customer_detail_dto(
            service.extend_subscription(
                subscription_id, days=body.days, admin_user_id=admin_id(auth), reason=body.reason
            )
        )


@router.post("/subscriptions/{subscription_id}/cancel", response_model=CustomerDetailDTO)
def cancel_subscription(
    subscription_id: uuid.UUID,
    body: AdminCancelRequestDTO,
    service: CustomerService,
    auth: AdminAuth,
) -> CustomerDetailDTO:
    with mapped_errors():
        return customer_detail_dto(
            service.cancel_subscription(
                subscription_id, when=body.when, admin_user_id=admin_id(auth), reason=body.reason
            )
        )
