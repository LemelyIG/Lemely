"""Admin billing, area 3: payment money actions (refund and void, spec §6, §8).

A lane router of ``admin_billing`` (DV-2, DV-T5a). It is mounted in ``app.py`` beside the parent
with the full prefix and carries its own ``platform_admin`` guard: a router nested into another
is a lazy wrapper, so ``flatten_routes`` (the authz matrix and ``test_admin_billing_authz``)
would lose the prefix. Task 9 appends the payment list, problem queue and reconcile routes.
"""

# FastAPI ``Depends``/``response_model`` and pydantic construction need these type imports at
# runtime (see the per-file-ignore in pyproject.toml).
from __future__ import annotations

import uuid  # noqa: TC003 - FastAPI resolves the path-parameter type at runtime
from typing import Annotated

from fastapi import APIRouter, Depends

from lemely.db.admin_payments_repo import AdminPaymentsService
from lemely.db.models.enums import Role
from lemely.db.session import get_sessionmaker
from lemely.web.admin_billing_common import AdminAuth, admin_id, mapped_errors, payment_row_dto
from lemely.web.deps import get_settings, require_role
from lemely.web.deps_billing import get_paymob_client
from lemely.web.schemas_admin_billing import AdminPaymentRowDTO, ReasonDTO
from lemely.web.schemas_admin_billing_payments import (  # noqa: TC001 - FastAPI resolves the body type at runtime
    AdminRefundRequestDTO,
)

router = APIRouter(
    prefix="/api/admin/billing/payments",
    dependencies=[Depends(require_role(Role.platform_admin))],
)


def get_admin_payments_service() -> AdminPaymentsService:
    settings = get_settings()  # one Settings read: sessionmaker and Paymob settings agree
    return AdminPaymentsService(get_sessionmaker(settings), get_paymob_client(), settings.paymob)


PaymentsService = Annotated[AdminPaymentsService, Depends(get_admin_payments_service)]


@router.post("/{payment_id}/refund", response_model=AdminPaymentRowDTO)
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


@router.post("/{payment_id}/void", response_model=AdminPaymentRowDTO)
def void_payment(
    payment_id: uuid.UUID, body: ReasonDTO, service: PaymentsService, auth: AdminAuth
) -> AdminPaymentRowDTO:
    with mapped_errors():
        view = service.void(payment_id, admin_user_id=admin_id(auth), reason=body.reason)
    return payment_row_dto(view)
