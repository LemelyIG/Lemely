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
  touches the token cipher, so neither plaintext nor ciphertext can leave;
* summary: a parent names a linked student (the checkout rule), anyone else sees
  only themselves; the acting-teacher header is ignored, as billing is never a
  team permission.

Phase 06 adds the merchant charges. Upgrade, seat purchase and auto top-up are the payer's alone
(``MerchantChargeService`` answers a beneficiary, a stranger and an unlinked parent with the one
404); the three seat routes are teacher-only and, like every billing route, never read the
acting-teacher header. Upgrade and seat purchase open a 3DS checkout (201 ``CheckoutDTO``) and
share the payer's checkout budget.

A payer with no valid phone gets a 422 ``{"code": "phone_required", "message": ...}`` before
anything is written (UD-11: no placeholder number is ever sent to Paymob).

The price is computed on the server from ``credit_packs``; the request body
forbids extra fields, so a client-sent price is a 422. A Paymob failure is a
503 whatever its cause: whether the payment row stays open or is closed is
``BillingService``'s decision (index R20b), not the router's.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable  # noqa: TC003 - FastAPI reads the type at runtime
from datetime import UTC, datetime
from typing import Annotated, Final, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker  # noqa: TC002 - FastAPI reads the type at runtime

from lemely.db.auto_topup_repo import AutoTopupView, get_auto_topup, put_auto_topup
from lemely.db.billing_repo import (
    BillingService,
    CheckoutResult,
    CheckoutUnavailable,
    NotLinkedToBeneficiary,
    PhoneRequired,
    UnknownCreditPack,
    UnknownPayer,
    active_catalogue,
    describe_payment,
    payment_for_viewer,
    receipts_for,
    saved_cards_for,
)
from lemely.db.billing_summary import build_billing_summary, is_linked_student
from lemely.db.merchant_charge_repo import (
    ChargeQuote,
    ChargesUnavailable,
    MerchantChargeError,
    MerchantChargeService,
    SeatsExceedNewTier,
    SeatsNotSold,
    charges_configured,
)
from lemely.db.models.billing import (
    Payment,
    PaymentPurpose,
    PaymentStatus,
    PlanAudience,
    PlanTier,
    Subscription,
)
from lemely.db.models.enums import Role
from lemely.db.plan_terms_repo import PendingTermsChange, TierTerms, current_terms_for
from lemely.db.subscription_repo import SeatsInsufficient, SubscriptionError
from lemely.io.paymob.client import PaymobClient  # noqa: TC001 - FastAPI reads the type at runtime
from lemely.runtime.config import Settings  # noqa: TC001 - FastAPI reads the type at runtime
from lemely.web.deps import AuthContext, get_settings, require_role
from lemely.web.deps_billing import (
    PublicCatalogueCache,
    get_billing_sessionmaker,
    get_checkout_limiter,
    get_merchant_charge_deps,
    get_paymob_client,
    get_public_catalogue_cache,
    get_public_catalogue_limiter,
    get_subscription_checkout_limiter,
    get_subscription_deps,
)
from lemely.web.merchant_charge_deps import (
    MerchantChargeDeps,  # noqa: TC001 - FastAPI reads the type at runtime
)
from lemely.web.phone_http import checkout_phone_required
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
from lemely.web.schemas_billing_charges import (
    AutoTopupDTO,
    AutoTopupRequest,
    ChargeQuoteDTO,
    ExtraSeatsRequest,
    SeatReductionRequest,
    SeatsDTO,
    UpgradeRequest,
)
from lemely.web.schemas_subscriptions import (
    BillingSummaryDTO,
    CreditLotDTO,
    CreditsViewDTO,
    DowngradeRequestDTO,
    PendingTermsChangeDTO,
    SavedCardViewDTO,
    SeatsViewDTO,
    SubscriptionCheckoutDTO,
    SubscriptionCheckoutRequestDTO,
    SubscriptionDTO,
    SubscriptionListDTO,
    SubscriptionViewDTO,
    SummaryBeneficiaryDTO,
    UsageMeterViewDTO,
)
from lemely.web.subscription_deps import (
    SubscriptionDeps,  # noqa: TC001 - FastAPI reads the type at runtime
)

require_billing_party: Final = require_role(Role.student, Role.parent, Role.teacher)
#: The seat routes: only a teacher holds seats, and the acting-teacher header is never read.
require_seat_payer: Final = require_role(Role.teacher)

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


def _plan_tier_dto(t: PlanTier, terms: TierTerms) -> PlanTierDTO:
    """One tier as the catalogue and the billing summary show it.

    The price and seats come from ``terms``, never the tier's own columns: the catalogue passes
    the tier's current terms (a new purchase), the summary the terms the subscriber is billed on.
    """
    return PlanTierDTO(
        planTierId=str(t.id),
        code=t.code,
        name=t.name,
        priceMinor=terms.price_minor,
        currency=t.currency,
        interval=t.interval.value if t.interval is not None else None,
        audience=t.audience.value,
        includedSeats=terms.included_seats,
        extraSeatPriceMinor=terms.extra_seat_price_minor,
        features=dict(t.features),
    )


def _pending_terms_dto(change: PendingTermsChange, billed: TierTerms) -> PendingTermsChangeDTO:
    allowance: Literal["more", "less"] | None = None
    if change.new_terms.allowance_units > billed.allowance_units:
        allowance = "more"
    elif change.new_terms.allowance_units < billed.allowance_units:
        allowance = "less"
    return PendingTermsChangeDTO(
        effectiveAt=change.effective_at,
        firstRenewalAt=change.first_renewal_at,
        priceMinor=change.new_terms.price_minor,
        extraSeatPriceMinor=change.new_terms.extra_seat_price_minor,
        includedSeats=change.new_terms.included_seats,
        priceChanges=change.price_changes,
        allowanceChange=allowance,
        includedSeatsChanges=change.included_seats_changes,
        seatAllowanceChanges=change.seat_allowance_changes,
        endsInsteadOfMoving=change.ends_instead_of_moving,
    )


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
            planTiers=[_plan_tier_dto(t, current_terms_for(session, t)) for t in tiers],
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


def _render_public_catalogue(
    session: Session, audience: Literal["student", "teacher"]
) -> PublicCatalogueDTO:
    """The public pricing page for one audience: sellable tiers and packs, public fields only."""
    is_teacher = audience == "teacher"
    tiers, packs = active_catalogue(
        session, audience=PlanAudience(audience), sellable_tiers_only=True
    )
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


@router.get("/public-catalogue", response_model=PublicCatalogueDTO)
def get_public_catalogue(
    request: Request,
    audience: Annotated[Literal["student", "teacher"], Query()],
    sm: Annotated[sessionmaker[Session], Depends(get_billing_sessionmaker)],
    limiter: Annotated[SlidingWindowLimiter, Depends(get_public_catalogue_limiter)],
    cache: Annotated[PublicCatalogueCache, Depends(get_public_catalogue_cache)],
) -> PublicCatalogueDTO:
    """Public pricing page: sellable tiers of one audience and sellable packs (no auth).

    PUBLIC on purpose: a visitor compares plans before signing up. It exposes no
    ids, no Paymob plan link and no allowance sizes, which stay hidden by design
    (spec §2.1). Rate-limited per client IP, like the contact form; the rendered
    answer is also cached for a short TTL per audience, because a direct caller of
    the Cloud Run URL can rotate ``X-Forwarded-For`` past the per-IP limit and
    must not be able to turn every request into database reads.
    """
    client_ip = _client_ip(request)
    if not limiter.allow(client_ip):
        retry = limiter.retry_after(client_ip)
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Too many requests; retry in {retry}s.",
            headers={"Retry-After": str(retry)},
        )
    cached = cache.get(audience)
    if cached is not None:
        return cached
    with sm() as session:
        rendered = _render_public_catalogue(session, audience)
    cache.put(audience, rendered)
    return rendered


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
        except UnknownPayer as exc:
            # A valid token whose user row is gone: refuse, and do not echo the id.
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Billing is not available") from exc
        except NotLinkedToBeneficiary as exc:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "You can only buy for a linked child"
            ) from exc
        except PhoneRequired as exc:
            # UD-11: Paymob needs the payer's phone and none is ever invented. The client
            # sends the user to PUT /api/me/phone, then retries.
            raise checkout_phone_required() from exc
        except CheckoutUnavailable as exc:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, _UNAVAILABLE) from exc
    return CheckoutDTO(paymentId=str(result.payment_id), checkoutUrl=result.checkout_url)


#: The purposes whose payment can end as credits instead of the change it priced (UD-P2).
_CHARGE_PURPOSES: Final = (PaymentPurpose.upgrade_proration, PaymentPurpose.extra_seats)


def _charge_outcome(
    payment: Payment,
) -> Literal["applied", "credited", "needs_attention"] | None:
    """What a paid upgrade or seat payment came to, for the return page's third state.

    Read from the payment alone, never from the subscription as it is now. ``credited``: it was
    turned into credits (``grant_units`` is stamped). ``applied``: the paid handler applied it
    (``applied_at``). ``needs_attention``: paid, yet neither (no credit rate fails the
    conversion closed, so the money was received and an operator handles it): the page must not
    read "done". ``None`` for any other purpose, a payment not yet paid, and a queued renewal
    seat payment (it pays for seats that already exist).
    """
    if (
        payment.purpose not in _CHARGE_PURPOSES
        or payment.status is not PaymentStatus.paid
        or payment.dedupe_key is not None
    ):
        return None
    if payment.grant_units is not None:
        return "credited"
    return "applied" if payment.applied_at is not None else "needs_attention"


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
        is_charge = payment.purpose in _CHARGE_PURPOSES
        return PaymentStatusDTO(
            paymentId=str(payment.id),
            status=payment.status.value,
            purpose=payment.purpose.value,
            amountMinor=payment.amount_minor,
            currency=payment.currency,
            description=describe_payment(session, payment),
            paidAt=payment.paid_at,
            creditedUnits=payment.grant_units if is_charge else None,
            outcome=_charge_outcome(payment),
            voidReason=payment.void_reason if is_charge else None,
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


def get_billing_clock() -> Callable[[], datetime]:
    """The clock the billing summary reads "now" from; tests override it."""
    return lambda: datetime.now(UTC)


@router.get("/summary", response_model=BillingSummaryDTO)
def get_billing_summary(
    auth: Annotated[AuthContext, Depends(require_billing_party)],
    sm: Annotated[sessionmaker[Session], Depends(get_billing_sessionmaker)],
    clock: Annotated[Callable[[], datetime], Depends(get_billing_clock)],
    settings: Annotated[Settings, Depends(get_settings)],
    beneficiaryId: uuid.UUID | None = None,
) -> BillingSummaryDTO:
    """Plan, period, usage meter, credits with expiry, debt and seats (index R3).

    A parent must name a linked child (422 without one, 403 for anyone else, including a
    linked user who is not a student); a student or teacher sees only themselves. The
    ``X-Lemely-Acting-Teacher`` header is deliberately not read: billing is never a team
    permission, so an assistant sees only their own summary.
    """
    caller = uuid.UUID(auth.user_id)
    target = _requested_beneficiary(auth, caller, beneficiaryId)
    with sm() as session:
        if auth.role == Role.parent.value and not is_linked_student(session, caller, target):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "You can only view a linked child's billing"
            )
        try:
            s = build_billing_summary(
                session,
                caller_user_id=caller,
                beneficiary_user_id=target,
                now=clock(),
                amount_updatable=settings.paymob.subscription_amount_updatable,
            )
        except LookupError as exc:
            # A valid token whose user row is gone: refuse, and do not echo the id.
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Billing is not available") from exc
        sub, card = s.subscription, s.saved_card
        return BillingSummaryDTO(
            beneficiary=SummaryBeneficiaryDTO(
                userId=str(s.beneficiary.id),
                displayName=s.beneficiary.display_name,
                audience=s.audience,
            ),
            subscription=(
                SubscriptionViewDTO(
                    subscriptionId=str(sub.id),
                    status=sub.status.value,
                    tier=_plan_tier_dto(s.tier, s.terms),
                    currentPeriodStart=sub.current_period_start,
                    currentPeriodEnd=sub.current_period_end,
                    cancelAtPeriodEnd=sub.cancel_at_period_end,
                    pendingTier=(
                        _plan_tier_dto(s.pending_tier, current_terms_for(session, s.pending_tier))
                        if s.pending_tier
                        else None
                    ),
                    graceUntil=sub.grace_until,
                    extraSeats=sub.extra_seats,
                    pendingExtraSeats=sub.pending_extra_seats,
                    pendingTermsChange=(
                        _pending_terms_dto(s.pending_terms_change, s.terms)
                        if s.pending_terms_change is not None
                        else None
                    ),
                    cancelReason="plan_terms_changed" if s.cancel_reason else None,
                )
                if sub is not None and s.tier is not None and s.terms is not None
                else None
            ),
            canManage=s.can_manage,
            managedByName=s.managed_by_name,
            savedCard=(
                SavedCardViewDTO(cardId=str(card.id), maskedPan=card.masked_pan, brand=card.brand)
                if card is not None
                else None
            ),
            usage=UsageMeterViewDTO(fraction=s.meter_fraction, resetsAt=s.meter_resets_at),
            credits=CreditsViewDTO(
                totalUnits=s.credits_balance,
                expiring=[
                    CreditLotDTO(units=lot.units, expiresAt=lot.expires_at) for lot in s.credits
                ],
            ),
            debtUnits=s.debt_units,
            seats=(
                SeatsViewDTO(capacity=s.seat_capacity, used=s.seats_used or 0)
                if s.seat_capacity is not None
                else None
            ),
        )


# -- subscriptions (Phase 05, spec §5.1-§5.3, §7) -----------------------------------------------

#: The HTTP status of each ``SubscriptionError`` code a route here can raise. A code missing from
#: this map answers 400, so a new error is mapped on purpose (``tests/test_web_subscriptions.py``).
_STATUS_FOR_CODE: Final = {
    "already_subscribed": status.HTTP_409_CONFLICT,
    "seats_insufficient": status.HTTP_409_CONFLICT,
    "downgrade_unavailable": status.HTTP_409_CONFLICT,
    "plan_mode_mismatch": status.HTTP_409_CONFLICT,
    "not_linked_parent": status.HTTP_403_FORBIDDEN,
    "subscription_not_found": status.HTTP_404_NOT_FOUND,
    "plan_not_purchasable": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "invalid_extra_seats": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "invalid_plan_change": status.HTTP_422_UNPROCESSABLE_CONTENT,
}


def _subscription_error(exc: SubscriptionError) -> HTTPException:
    """The refusal as ``{"error": code, "message": text}``; seats add ``inUse`` and ``capacity``."""
    detail: dict[str, object] = {"error": exc.code, "message": str(exc)}
    if isinstance(exc, SeatsInsufficient):
        detail |= {"inUse": exc.in_use, "capacity": exc.capacity}
    return HTTPException(_STATUS_FOR_CODE.get(exc.code, status.HTTP_400_BAD_REQUEST), detail)


def _payments_unavailable() -> HTTPException:
    return HTTPException(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        {"error": "payments_unavailable", "message": _UNAVAILABLE},
    )


def _subscription_dto(
    subscription: Subscription, tier: PlanTier, viewer: uuid.UUID
) -> SubscriptionDTO:
    pending = subscription.pending_plan_tier_id
    return SubscriptionDTO(
        id=str(subscription.id),
        beneficiaryUserId=str(subscription.user_id),
        isPayer=subscription.payer_user_id == viewer,
        planTierId=str(tier.id),
        planCode=tier.code,
        planName=tier.name,
        status=subscription.status.value,
        currentPeriodStart=subscription.current_period_start,
        currentPeriodEnd=subscription.current_period_end,
        graceUntil=subscription.grace_until,
        cancelAtPeriodEnd=bool(subscription.cancel_at_period_end),
        pendingPlanTierId=str(pending) if pending is not None else None,
        extraSeats=subscription.extra_seats or 0,
    )


def _changed_subscription(
    session: Session, subscription: Subscription, viewer: uuid.UUID
) -> SubscriptionDTO:
    tier = session.get(PlanTier, subscription.plan_tier_id)
    if tier is None:  # the FK makes this unreachable; a corrupt row must not 500 the payer
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown subscription")
    return _subscription_dto(subscription, tier, viewer)


@router.post(
    "/subscriptions/checkout",
    response_model=SubscriptionCheckoutDTO,
    status_code=status.HTTP_201_CREATED,
)
def create_subscription_checkout(
    body: SubscriptionCheckoutRequestDTO,
    auth: Annotated[AuthContext, Depends(require_billing_party)],
    deps: Annotated[SubscriptionDeps, Depends(get_subscription_deps)],
    limiter: Annotated[SlidingWindowLimiter, Depends(get_subscription_checkout_limiter)],
) -> SubscriptionCheckoutDTO:
    """Start a card subscription; the browser then redirects to ``checkoutUrl`` (spec §5.1).

    The price comes from ``plan_tiers`` on the server; a student or teacher buys only for
    themselves and a parent only for a linked child (the service checks the link).
    """
    if not limiter.allow(auth.user_id):
        retry = limiter.retry_after(auth.user_id)
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            {"error": "rate_limited", "message": f"Too many checkout attempts; retry in {retry}s."},
            headers={"Retry-After": str(retry)},
        )
    payer = uuid.UUID(auth.user_id)
    beneficiary = _requested_beneficiary(auth, payer, body.beneficiaryId)
    try:
        # No ``session.begin()``: Phase 02's intention checkout commits inside the call (spec §6).
        # A refusal raises before that commit, so closing the session rolls the attempt back.
        with deps.sessionmaker() as session:
            result = deps.service(session).create_subscription_checkout(
                payer_user_id=payer,
                plan_tier_id=body.planTierId,
                beneficiary_user_id=beneficiary,
                extra_seats=body.extraSeats,
                now=datetime.now(UTC),
            )
            session.commit()
    except SubscriptionError as exc:
        raise _subscription_error(exc) from exc
    except UnknownPayer as exc:
        # A valid token whose user row is gone: refuse, and do not echo the id.
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Billing is not available") from exc
    except PhoneRequired as exc:
        raise checkout_phone_required() from exc
    except CheckoutUnavailable as exc:
        raise _payments_unavailable() from exc
    return SubscriptionCheckoutDTO(
        subscriptionId=str(result.subscription_id),
        paymentId=str(result.payment_id),
        checkoutUrl=result.checkout_url,
    )


@router.get("/subscriptions", response_model=SubscriptionListDTO)
def list_subscriptions(
    auth: Annotated[AuthContext, Depends(require_billing_party)],
    deps: Annotated[SubscriptionDeps, Depends(get_subscription_deps)],
) -> SubscriptionListDTO:
    """The caller's subscriptions as payer or beneficiary, newest first (DV-31)."""
    viewer = uuid.UUID(auth.user_id)
    with deps.sessionmaker() as session:
        rows = deps.service(session).list_for_user(viewer)
        return SubscriptionListDTO(
            subscriptions=[_subscription_dto(sub, tier, viewer) for sub, tier in rows]
        )


@router.post("/subscriptions/{subscription_id}/downgrade", response_model=SubscriptionDTO)
def downgrade_subscription(
    subscription_id: uuid.UUID,
    body: DowngradeRequestDTO,
    auth: Annotated[AuthContext, Depends(require_billing_party)],
    deps: Annotated[SubscriptionDeps, Depends(get_subscription_deps)],
) -> SubscriptionDTO:
    """Schedule a downgrade for the period end; the payer only, anyone else gets 404 (§5.3)."""
    viewer = uuid.UUID(auth.user_id)
    try:
        with deps.sessionmaker.begin() as session:
            subscription = deps.service(session).schedule_downgrade(
                subscription_id,
                actor_user_id=viewer,
                plan_tier_id=body.planTierId,
                now=datetime.now(UTC),
            )
            return _changed_subscription(session, subscription, viewer)
    except SubscriptionError as exc:
        raise _subscription_error(exc) from exc


@router.post("/subscriptions/{subscription_id}/cancel", response_model=SubscriptionDTO)
def cancel_subscription(
    subscription_id: uuid.UUID,
    auth: Annotated[AuthContext, Depends(require_billing_party)],
    deps: Annotated[SubscriptionDeps, Depends(get_subscription_deps)],
) -> SubscriptionDTO:
    """Cancel at the period end; access continues until then. The payer only (spec §5.3).

    Always the payer-checked ``schedule_cancel``: the system cancel is never reachable here.
    """
    viewer = uuid.UUID(auth.user_id)
    try:
        with deps.sessionmaker.begin() as session:
            subscription = deps.service(session).schedule_cancel(
                subscription_id, actor_user_id=viewer, now=datetime.now(UTC)
            )
            return _changed_subscription(session, subscription, viewer)
    except SubscriptionError as exc:
        raise _subscription_error(exc) from exc


# -- merchant charges (Phase 06, spec §4.5-§4.6, §7) --------------------------------------------

#: The HTTP status of each ``MerchantChargeError`` code with a status of its own. Every other code
#: is a conflict with the plan or the seats as they are now (409), and a code nobody mapped is a
#: 409 too: each refusal is raised before any write, so "nothing was charged" stays true
#: (``tests/test_web_billing_charges.py`` pins the map).
_CHARGE_STATUS: Final = {
    "not_found": status.HTTP_404_NOT_FOUND,
    "tier_not_found": status.HTTP_404_NOT_FOUND,
    "pack_not_found": status.HTTP_404_NOT_FOUND,
    "card_not_found": status.HTTP_404_NOT_FOUND,
    "invalid_seats": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "invalid_settings": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "payments_unavailable": status.HTTP_503_SERVICE_UNAVAILABLE,
    "unknown_payer": status.HTTP_403_FORBIDDEN,
}

#: The machine-readable facts a refusal carries to the client, by wire name.
_CHARGE_EXTRA_KEYS: Final = {"in_use": "inUse", "capacity": "capacity", "extra_seats": "extraSeats"}


def charge_error(exc: MerchantChargeError) -> HTTPException:
    """The refusal as ``{"error": code, "message": text}`` plus the facts the page needs.

    ``seats_exceed_new_tier`` adds ``inUse`` and ``capacity``; ``seats_not_sold`` adds
    ``extraSeats`` (the teacher must reduce them first); ``upgrade_unavailable`` adds ``next``
    when the fixed-amount fallback is the cause. A 503 and an unknown payer carry fixed copy.
    """
    code = exc.code
    code_status = _CHARGE_STATUS.get(code, status.HTTP_409_CONFLICT)
    detail: dict[str, object] = {"error": code, "message": str(exc)}
    if code == "payments_unavailable":
        detail["message"] = _UNAVAILABLE
    elif code == "unknown_payer":
        detail["message"] = "Billing is not available"
    if isinstance(exc, SeatsExceedNewTier | SeatsNotSold):
        for key, wire in _CHARGE_EXTRA_KEYS.items():
            if key in exc.detail:
                detail[wire] = exc.detail[key]
    if "next" in exc.detail:
        detail["next"] = exc.detail["next"]
    return HTTPException(code_status, detail)


def _quote_dto(quote: ChargeQuote) -> ChargeQuoteDTO:
    return ChargeQuoteDTO(
        amountMinor=quote.amount_minor,
        currency=quote.currency,
        allowanceUnits=quote.allowance_units,
        periodEnd=quote.period_end,
    )


def _checkout_budget(limiter: SlidingWindowLimiter, user_id: str) -> None:
    """Spend one of the payer's checkout attempts, or answer 429 with ``Retry-After``."""
    if not limiter.allow(user_id):
        retry = limiter.retry_after(user_id)
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            {"error": "rate_limited", "message": f"Too many checkout attempts; retry in {retry}s."},
            headers={"Retry-After": str(retry)},
        )


def _start_charge_checkout(
    deps: MerchantChargeDeps,
    start: Callable[[MerchantChargeService], CheckoutResult],
) -> CheckoutDTO:
    """Run a payer-present checkout start and map its refusals; the 201 body is the checkout.

    No ``session.begin()``: Phase 02's intention checkout commits inside the call. A refusal
    raises before that commit, so closing the session rolls the attempt back. A
    ``CheckoutUnavailable`` is a true "nothing was charged": no client secret reached the browser.
    """
    try:
        with deps.sessionmaker() as session:
            result = start(deps.service(session))
    except MerchantChargeError as exc:
        raise charge_error(exc) from exc
    except PhoneRequired as exc:
        raise checkout_phone_required() from exc
    except CheckoutUnavailable as exc:
        raise _payments_unavailable() from exc
    return CheckoutDTO(paymentId=str(result.payment_id), checkoutUrl=result.checkout_url)


@router.post(
    "/subscriptions/{subscription_id}/upgrade/quote",
    response_model=ChargeQuoteDTO,
)
def quote_upgrade(
    subscription_id: uuid.UUID,
    body: UpgradeRequest,
    auth: Annotated[AuthContext, Depends(require_billing_party)],
    deps: Annotated[MerchantChargeDeps, Depends(get_merchant_charge_deps)],
    clock: Annotated[Callable[[], datetime], Depends(get_billing_clock)],
) -> ChargeQuoteDTO:
    """What an upgrade would charge now; the payer only, and it writes nothing."""
    try:
        with deps.sessionmaker() as session:
            quote = deps.service(session).quote_upgrade(
                subscription_id=subscription_id,
                actor_user_id=uuid.UUID(auth.user_id),
                plan_tier_id=body.planTierId,
                now=clock(),
            )
    except MerchantChargeError as exc:
        raise charge_error(exc) from exc
    return _quote_dto(quote)


@router.post(
    "/subscriptions/{subscription_id}/upgrade",
    response_model=CheckoutDTO,
    status_code=status.HTTP_201_CREATED,
)
def start_upgrade(
    subscription_id: uuid.UUID,
    body: UpgradeRequest,
    auth: Annotated[AuthContext, Depends(require_billing_party)],
    deps: Annotated[MerchantChargeDeps, Depends(get_merchant_charge_deps)],
    clock: Annotated[Callable[[], datetime], Depends(get_billing_clock)],
    limiter: Annotated[SlidingWindowLimiter, Depends(get_checkout_limiter)],
) -> CheckoutDTO:
    """Open the 3DS checkout of a prorated plan upgrade; the tier changes on the callback."""
    _checkout_budget(limiter, auth.user_id)
    actor = uuid.UUID(auth.user_id)
    return _start_charge_checkout(
        deps,
        lambda service: service.start_upgrade_checkout(
            subscription_id=subscription_id,
            actor_user_id=actor,
            plan_tier_id=body.planTierId,
            now=clock(),
        ),
    )


@router.post("/subscriptions/{subscription_id}/seats/quote", response_model=ChargeQuoteDTO)
def quote_extra_seats(
    subscription_id: uuid.UUID,
    body: ExtraSeatsRequest,
    auth: Annotated[AuthContext, Depends(require_seat_payer)],
    deps: Annotated[MerchantChargeDeps, Depends(get_merchant_charge_deps)],
    clock: Annotated[Callable[[], datetime], Depends(get_billing_clock)],
) -> ChargeQuoteDTO:
    """What ``seats`` extra seats would charge now; the paying teacher only."""
    try:
        with deps.sessionmaker() as session:
            quote = deps.service(session).quote_extra_seats(
                subscription_id=subscription_id,
                actor_user_id=uuid.UUID(auth.user_id),
                seats=body.seats,
                now=clock(),
            )
    except MerchantChargeError as exc:
        raise charge_error(exc) from exc
    return _quote_dto(quote)


@router.post(
    "/subscriptions/{subscription_id}/seats",
    response_model=CheckoutDTO,
    status_code=status.HTTP_201_CREATED,
)
def start_extra_seats(
    subscription_id: uuid.UUID,
    body: ExtraSeatsRequest,
    auth: Annotated[AuthContext, Depends(require_seat_payer)],
    deps: Annotated[MerchantChargeDeps, Depends(get_merchant_charge_deps)],
    clock: Annotated[Callable[[], datetime], Depends(get_billing_clock)],
    limiter: Annotated[SlidingWindowLimiter, Depends(get_checkout_limiter)],
) -> CheckoutDTO:
    """Open the 3DS checkout of an extra-seat purchase; the seats are added on the callback."""
    _checkout_budget(limiter, auth.user_id)
    actor = uuid.UUID(auth.user_id)
    return _start_charge_checkout(
        deps,
        lambda service: service.start_extra_seats_checkout(
            subscription_id=subscription_id,
            actor_user_id=actor,
            seats=body.seats,
            now=clock(),
        ),
    )


@router.put("/subscriptions/{subscription_id}/seats/pending", response_model=SeatsDTO)
def schedule_seat_reduction(
    subscription_id: uuid.UUID,
    body: SeatReductionRequest,
    auth: Annotated[AuthContext, Depends(require_seat_payer)],
    deps: Annotated[MerchantChargeDeps, Depends(get_merchant_charge_deps)],
    clock: Annotated[Callable[[], datetime], Depends(get_billing_clock)],
) -> SeatsDTO:
    """Set the extra-seat total wanted from the next renewal (current count cancels it)."""
    try:
        with deps.sessionmaker.begin() as session:
            sub = deps.service(session).schedule_seat_reduction(
                subscription_id=subscription_id,
                actor_user_id=uuid.UUID(auth.user_id),
                extra_seats=body.extraSeats,
                now=clock(),
            )
            return SeatsDTO(
                extraSeats=sub.extra_seats or 0, pendingExtraSeats=sub.pending_extra_seats
            )
    except MerchantChargeError as exc:
        raise charge_error(exc) from exc


def _auto_topup_beneficiary(
    session: Session, auth: AuthContext, requested: uuid.UUID | None
) -> uuid.UUID:
    """Whose balance the caller manages: themselves, or a linked student for a parent."""
    caller = uuid.UUID(auth.user_id)
    target = _requested_beneficiary(auth, caller, requested)
    if auth.role == Role.parent.value and not is_linked_student(session, caller, target):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            {
                "error": "not_linked_parent",
                "message": "You can only manage auto top-up for a linked child",
            },
        )
    return target


def _auto_topup_dto(view: AutoTopupView) -> AutoTopupDTO:
    return AutoTopupDTO(
        beneficiaryId=str(view.beneficiary_user_id),
        enabled=view.enabled,
        thresholdUnits=view.threshold_units,
        creditPackId=None if view.credit_pack_id is None else str(view.credit_pack_id),
        savedCardId=None if view.saved_card_id is None else str(view.saved_card_id),
        monthlyCapMinor=view.monthly_cap_minor,
        spentThisMonthMinor=view.spent_this_month_minor,
        currency=view.currency,
        disabledReason=view.disabled_reason,
    )


@router.get("/auto-topup", response_model=AutoTopupDTO)
def read_auto_topup(
    auth: Annotated[AuthContext, Depends(require_billing_party)],
    deps: Annotated[MerchantChargeDeps, Depends(get_merchant_charge_deps)],
    clock: Annotated[Callable[[], datetime], Depends(get_billing_clock)],
    beneficiaryId: uuid.UUID | None = None,
) -> AutoTopupDTO:
    """The auto top-up of one balance; a balance never set up reads as disabled."""
    try:
        with deps.sessionmaker() as session:
            target = _auto_topup_beneficiary(session, auth, beneficiaryId)
            view = get_auto_topup(
                session,
                payer_user_id=uuid.UUID(auth.user_id),
                beneficiary_user_id=target,
                now=clock(),
            )
    except MerchantChargeError as exc:
        raise charge_error(exc) from exc
    return _auto_topup_dto(view)


def _is_unique_violation(exc: IntegrityError) -> bool:
    """True for PostgreSQL's ``unique_violation`` (SQLSTATE 23505), whatever the driver calls it."""
    orig = exc.orig
    return "23505" in (getattr(orig, "sqlstate", None), getattr(orig, "pgcode", None))


def _save_auto_topup(
    deps: MerchantChargeDeps, auth: AuthContext, body: AutoTopupRequest, now: datetime
) -> AutoTopupDTO:
    if body.enabled and not charges_configured(deps.settings):
        # Nothing could charge a saved card (no MOTO id or no token key): refuse to arm a top-up
        # that would never run. Switching one off stays possible.
        raise ChargesUnavailable
    with deps.sessionmaker.begin() as session:
        target = _auto_topup_beneficiary(session, auth, body.beneficiaryId)
        view = put_auto_topup(
            session,
            payer_user_id=uuid.UUID(auth.user_id),
            beneficiary_user_id=target,
            enabled=body.enabled,
            threshold_units=body.thresholdUnits,
            credit_pack_id=body.creditPackId,
            saved_card_id=body.savedCardId,
            monthly_cap_minor=body.monthlyCapMinor,
            now=now,
        )
        return _auto_topup_dto(view)


@router.put("/auto-topup", response_model=AutoTopupDTO)
def save_auto_topup(
    body: AutoTopupRequest,
    auth: Annotated[AuthContext, Depends(require_billing_party)],
    deps: Annotated[MerchantChargeDeps, Depends(get_merchant_charge_deps)],
    clock: Annotated[Callable[[], datetime], Depends(get_billing_clock)],
) -> AutoTopupDTO:
    """Create or update the auto top-up of one balance (the payer only, consent stamped on).

    Two first saves at once hit the unique constraint on the balance. The loser is retried once,
    as an update (or as ``managed_by_another_payer`` if the winner was someone else); a second
    collision is a 409, never a 500.
    """
    try:
        try:
            return _save_auto_topup(deps, auth, body, clock())
        except IntegrityError as exc:
            if not _is_unique_violation(exc):
                raise
            return _save_auto_topup(deps, auth, body, clock())
    except IntegrityError as exc:
        if not _is_unique_violation(exc):
            raise
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"error": "settings_changing", "message": "These settings changed; try again"},
        ) from exc
    except MerchantChargeError as exc:
        raise charge_error(exc) from exc
    except PhoneRequired as exc:
        raise checkout_phone_required() from exc
