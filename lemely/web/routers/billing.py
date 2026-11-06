"""Billing endpoints: catalogue, pack checkout, payment status, receipts (billing spec §5.5, §7).

**Authz.** ``GET /public-catalogue`` is PUBLIC (pricing page; IP rate-limited,
public fields only). Every other route is students, parents and teachers only
(``require_role``), and every object-level check keys on ``auth.user_id``:

* checkout: a student or teacher buys only for themselves; a parent only for a
  child linked by ``parent_child_links``. The link is checked by
  ``BillingService`` (``NotLinkedToBeneficiary``, mapped to 403 here), so there is
  one authority. An unlinked or non-existent child is the same 403, so the route
  is no user-existence oracle;
* payment status: payer or beneficiary, else 404 (same answer as a missing id);
* receipts: payments the caller *paid for*; a child never sees a parent's
  receipts, only the plan and balance they were bought;
* cards: the caller's own active saved cards, masked only. The route never
  touches the token cipher, so neither plaintext nor ciphertext can leave.

The price is computed on the server from ``credit_packs``; the request body
forbids extra fields, so a client-sent price is a 422. A Paymob failure is a
503 whatever its cause: whether the payment row stays open or is closed is
``BillingService``'s decision (index R20b), not the router's.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Final, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session, sessionmaker  # noqa: TC002 - FastAPI reads the type at runtime

from lemely.db.billing_repo import (
    BillingService,
    CheckoutUnavailable,
    NotLinkedToBeneficiary,
    UnknownCreditPack,
    active_catalogue,
    describe_payment,
    payment_for_viewer,
    receipts_for,
    saved_cards_for,
)
from lemely.db.models.billing import PlanAudience
from lemely.db.models.enums import Role
from lemely.io.paymob.client import PaymobClient  # noqa: TC001 - FastAPI reads the type at runtime
from lemely.runtime.config import Settings  # noqa: TC001 - FastAPI reads the type at runtime
from lemely.web.deps import AuthContext, get_settings, require_role
from lemely.web.deps_billing import (
    get_billing_sessionmaker,
    get_checkout_limiter,
    get_paymob_client,
    get_public_catalogue_limiter,
)
from lemely.web.ratelimit import (
    SlidingWindowLimiter,  # noqa: TC001 - FastAPI reads the type at runtime
)
from lemely.web.routers.client_errors import _client_ip
from lemely.web.schemas_billing import (
    CatalogueDTO,
    CheckoutDTO,
    CreditPackDTO,
    PackCheckoutRequest,
    PaymentStatusDTO,
    PlanTierDTO,
    PublicCatalogueDTO,
    PublicCreditPackDTO,
    PublicPlanTierDTO,
    ReceiptDTO,
    ReceiptListDTO,
    SavedCardList,
    SavedCardView,
)

require_billing_party: Final = require_role(Role.student, Role.parent, Role.teacher)

router = APIRouter(prefix="/api/billing")

_UNAVAILABLE = "Payments are temporarily unavailable. Please try again in a few minutes."


def _requested_beneficiary(
    auth: AuthContext, payer: uuid.UUID, requested: uuid.UUID | None
) -> uuid.UUID:
    """Who the caller names as the beneficiary; the parent-child link is checked later.

    A parent must name a child (the service then requires the link). A student or
    teacher buys only for themselves, so any other id is refused here.
    """
    if auth.role == Role.parent.value:
        if requested is None:
            raise HTTPException(422, "beneficiaryId is required for a parent")
        return requested
    if requested is not None and requested != payer:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You can only buy for yourself")
    return payer


@router.get("/catalogue", response_model=CatalogueDTO)
def get_catalogue(
    auth: Annotated[AuthContext, Depends(require_billing_party)],
    sm: Annotated[sessionmaker[Session], Depends(get_billing_sessionmaker)],
) -> CatalogueDTO:
    """Active plan tiers for the caller's audience, and every active credit pack."""
    audience = PlanAudience.teacher if auth.role == Role.teacher.value else PlanAudience.student
    with sm() as session:
        tiers, packs = active_catalogue(session, audience=audience)
        return CatalogueDTO(
            planTiers=[
                PlanTierDTO(
                    planTierId=str(t.id),
                    code=t.code,
                    name=t.name,
                    priceMinor=t.price_minor,
                    currency=t.currency,
                    interval=t.interval.value if t.interval is not None else None,
                    audience=t.audience.value,
                    includedSeats=t.included_seats,
                    extraSeatPriceMinor=t.extra_seat_price_minor,
                    features=dict(t.features),
                )
                for t in tiers
            ],
            creditPacks=[
                CreditPackDTO(
                    creditPackId=str(p.id),
                    code=p.code,
                    name=p.name,
                    credits=p.units,
                    priceMinor=p.price_minor,
                    currency=p.currency,
                )
                for p in packs
            ],
        )


@router.get("/public-catalogue", response_model=PublicCatalogueDTO)
def get_public_catalogue(
    request: Request,
    audience: Annotated[Literal["student", "teacher"], Query()],
    sm: Annotated[sessionmaker[Session], Depends(get_billing_sessionmaker)],
    limiter: Annotated[SlidingWindowLimiter, Depends(get_public_catalogue_limiter)],
) -> PublicCatalogueDTO:
    """Public pricing page: active tiers of one audience and sellable packs (no auth).

    PUBLIC on purpose: a visitor compares plans before signing up. It exposes no
    ids, no Paymob plan link and no allowance sizes, which stay hidden by design
    (spec §2.1). Rate-limited per client IP, like the contact form.
    """
    client_ip = _client_ip(request)
    if not limiter.allow(client_ip):
        retry = limiter.retry_after(client_ip)
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Too many requests; retry in {retry}s.",
            headers={"Retry-After": str(retry)},
        )
    is_teacher = audience == "teacher"
    with sm() as session:
        tiers, packs = active_catalogue(session, audience=PlanAudience(audience))
        return PublicCatalogueDTO(
            audience=audience,
            planTiers=[
                PublicPlanTierDTO(
                    code=t.code,
                    name=t.name,
                    audience=t.audience.value,
                    interval=t.interval.value if t.interval is not None else None,
                    priceMinor=t.price_minor,
                    currency=t.currency,
                    features=dict(t.features),
                    includedSeats=t.included_seats if is_teacher else None,
                    extraSeatPriceMinor=t.extra_seat_price_minor if is_teacher else None,
                )
                for t in tiers
            ],
            creditPacks=[
                PublicCreditPackDTO(
                    code=p.code,
                    name=p.name,
                    units=p.units,
                    priceMinor=p.price_minor,
                    currency=p.currency,
                )
                for p in packs
            ],
        )


@router.post("/checkout/pack", response_model=CheckoutDTO, status_code=status.HTTP_201_CREATED)
def checkout_pack(
    body: PackCheckoutRequest,
    auth: Annotated[AuthContext, Depends(require_billing_party)],
    sm: Annotated[sessionmaker[Session], Depends(get_billing_sessionmaker)],
    client: Annotated[PaymobClient, Depends(get_paymob_client)],
    settings: Annotated[Settings, Depends(get_settings)],
    limiter: Annotated[SlidingWindowLimiter, Depends(get_checkout_limiter)],
) -> CheckoutDTO:
    """Create a one-off credit-pack checkout and return the Unified Checkout URL."""
    if not limiter.allow(auth.user_id):
        retry = limiter.retry_after(auth.user_id)
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Too many checkout attempts; retry in {retry}s.",
            headers={"Retry-After": str(retry)},
        )
    payer = uuid.UUID(auth.user_id)
    beneficiary = _requested_beneficiary(auth, payer, body.beneficiaryId)
    with sm() as session:
        service = BillingService(session, client, settings.paymob)
        try:
            result = service.create_pack_checkout(
                payer_user_id=payer,
                beneficiary_user_id=beneficiary,
                credit_pack_id=body.creditPackId,
            )
        except UnknownCreditPack as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown credit pack") from exc
        except NotLinkedToBeneficiary as exc:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "You can only buy for a linked child"
            ) from exc
        except CheckoutUnavailable as exc:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, _UNAVAILABLE) from exc
    return CheckoutDTO(paymentId=str(result.payment_id), checkoutUrl=result.checkout_url)


@router.get("/payments/{payment_id}", response_model=PaymentStatusDTO)
def get_payment(
    payment_id: uuid.UUID,
    auth: Annotated[AuthContext, Depends(require_billing_party)],
    sm: Annotated[sessionmaker[Session], Depends(get_billing_sessionmaker)],
) -> PaymentStatusDTO:
    """Status of one payment for the return page; payer or beneficiary only."""
    with sm() as session:
        payment = payment_for_viewer(
            session, payment_id=payment_id, user_id=uuid.UUID(auth.user_id)
        )
        if payment is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown payment")
        return PaymentStatusDTO(
            paymentId=str(payment.id),
            status=payment.status.value,
            purpose=payment.purpose.value,
            amountMinor=payment.amount_minor,
            currency=payment.currency,
            description=describe_payment(session, payment),
            paidAt=payment.paid_at,
        )


@router.get("/receipts", response_model=ReceiptListDTO)
def list_receipts(
    auth: Annotated[AuthContext, Depends(require_billing_party)],
    sm: Annotated[sessionmaker[Session], Depends(get_billing_sessionmaker)],
) -> ReceiptListDTO:
    """Every payment the caller paid for, newest first (spec §2.5)."""
    with sm() as session:
        receipts: list[ReceiptDTO] = []
        for payment in receipts_for(session, uuid.UUID(auth.user_id)):
            if payment.paid_at is None:  # receipts_for filters on it; narrows the type
                continue
            receipts.append(
                ReceiptDTO(
                    paymentId=str(payment.id),
                    purpose=payment.purpose.value,
                    description=describe_payment(session, payment),
                    amountMinor=payment.amount_minor,
                    currency=payment.currency,
                    status=payment.status.value,
                    paidAt=payment.paid_at,
                    beneficiaryId=str(payment.beneficiary_user_id),
                )
            )
        return ReceiptListDTO(receipts=receipts)


@router.get("/cards", response_model=SavedCardList)
def list_saved_cards(
    auth: Annotated[AuthContext, Depends(require_billing_party)],
    sm: Annotated[sessionmaker[Session], Depends(get_billing_sessionmaker)],
) -> SavedCardList:
    """The caller's own active saved cards, masked only (index R3, spec §7)."""
    with sm() as session:
        return SavedCardList(
            cards=[
                SavedCardView(
                    cardId=str(card.id), maskedPan=card.masked_pan, brand=card.brand or ""
                )
                for card in saved_cards_for(session, uuid.UUID(auth.user_id))
            ]
        )
