"""Admin billing, area 3: payments (list, problem queue, reconcile, refund and void; spec §6, §8).

A lane router of ``admin_billing`` (DV-2, DV-T5a). It is mounted in ``app.py`` beside the parent
and carries its own ``platform_admin`` guard: a router nested into another is a lazy wrapper, so
``flatten_routes`` (the authz matrix and ``test_admin_billing_authz``) would lose the prefix. The
prefix is the whole ``/api/admin/billing`` because ``/problems`` sits beside ``/payments``.
"""

# FastAPI ``Depends``/``response_model`` and pydantic construction need these type imports at
# runtime (see the per-file-ignore in pyproject.toml).
from __future__ import annotations

import uuid  # noqa: TC003 - FastAPI resolves the path-parameter type at runtime
from datetime import datetime  # noqa: TC003 - FastAPI resolves the query type at runtime
from typing import Annotated, cast

from fastapi import APIRouter, Depends, Query

from lemely.db.admin_payments_repo import AdminPaymentsService
from lemely.db.models.billing import PaymentPurpose, PaymentStatus  # noqa: TC001 - query types
from lemely.db.models.enums import Role
from lemely.db.session import get_sessionmaker
from lemely.web.admin_billing_common import (
    AdminAuth,
    admin_id,
    mapped_errors,
    payment_row_dto,
    refund_dto,
    require_aware,
)
from lemely.web.deps import get_settings, require_role
from lemely.web.deps_billing import get_paymob_client
from lemely.web.schemas_admin_billing import AdminPaymentRowDTO, ReasonDTO
from lemely.web.schemas_admin_billing_payments import (
    AdminPaymentsPageDTO,
    AdminRefundRequestDTO,
    AdminVoidRequestDTO,
    ProblemQueueDTO,
    WebhookFailureDTO,
    WebhookKind,
)

router = APIRouter(
    prefix="/api/admin/billing",
    dependencies=[Depends(require_role(Role.platform_admin))],
)


def get_admin_payments_service() -> AdminPaymentsService:
    settings = get_settings()  # one Settings read: sessionmaker and Paymob settings agree
    return AdminPaymentsService(get_sessionmaker(settings), get_paymob_client(), settings.paymob)


PaymentsService = Annotated[AdminPaymentsService, Depends(get_admin_payments_service)]


@router.get("/payments", response_model=AdminPaymentsPageDTO)
def list_payments(
    service: PaymentsService,
    status: PaymentStatus | None = None,
    purpose: PaymentPurpose | None = None,
    userId: uuid.UUID | None = None,
    start: Annotated[datetime | None, Query(alias="from")] = None,
    end: Annotated[datetime | None, Query(alias="to")] = None,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> AdminPaymentsPageDTO:
    with mapped_errors():
        page = service.list_payments(
            status=status,
            purpose=purpose,
            user_id=userId,
            start=require_aware(start, "from"),
            end=require_aware(end, "to"),
            cursor=cursor,
            limit=limit,
        )
    return AdminPaymentsPageDTO(
        items=[payment_row_dto(v) for v in page.items], nextCursor=page.next_cursor
    )


@router.post("/payments/{payment_id}/refund", response_model=AdminPaymentRowDTO)
def refund_payment(
    payment_id: uuid.UUID, body: AdminRefundRequestDTO, service: PaymentsService, auth: AdminAuth
) -> AdminPaymentRowDTO:
    with mapped_errors():
        view = service.refund(
            payment_id,
            amount_minor=body.amountMinor,
            admin_user_id=admin_id(auth),
            reason=body.reason,
            reverse_change=body.reverseChange,
        )
    return payment_row_dto(view)


@router.post("/payments/{payment_id}/void", response_model=AdminPaymentRowDTO)
def void_payment(
    payment_id: uuid.UUID, body: AdminVoidRequestDTO, service: PaymentsService, auth: AdminAuth
) -> AdminPaymentRowDTO:
    with mapped_errors():
        view = service.void(
            payment_id,
            admin_user_id=admin_id(auth),
            reason=body.reason,
            reverse_change=body.reverseChange,
        )
    return payment_row_dto(view)


@router.post("/payments/{payment_id}/reconcile", response_model=AdminPaymentRowDTO)
def reconcile_payment(
    payment_id: uuid.UUID, body: ReasonDTO, service: PaymentsService, auth: AdminAuth
) -> AdminPaymentRowDTO:
    with mapped_errors():
        view = service.reconcile(payment_id, admin_user_id=admin_id(auth), reason=body.reason)
    return payment_row_dto(view)


@router.get("/problems", response_model=ProblemQueueDTO)
def problem_queue(service: PaymentsService) -> ProblemQueueDTO:
    queue = service.problems()
    return ProblemQueueDTO(
        mismatches=[payment_row_dto(v) for v in queue.mismatches],
        stalePending=[payment_row_dto(v) for v in queue.stale_pending],
        missingCallbacks=[payment_row_dto(v) for v in queue.missing_callbacks],
        hmacFailures=[
            WebhookFailureDTO(
                id=str(f.id),
                kind=cast(
                    "WebhookKind", f.kind
                ),  # the table's check constraint keeps it to these three
                reason=f.reason,
                remoteAddr=f.remote_addr,
                receivedAt=f.received_at,
            )
            for f in queue.hmac_failures
        ],
        hmacFailures24h=queue.hmac_failures_24h,
        refundsNeedingAttention=[
            refund_dto(r, queue.refund_currency[r.payment_id])
            for r in queue.refunds_needing_attention
        ],
    )
