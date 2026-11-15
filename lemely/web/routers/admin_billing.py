"""Admin billing console API (spec §8) under ``/api/admin/billing``.

The parent router: gated at router level to ``platform_admin`` alone, like ``admin.py``, so every
route added here, and every lane router included below, inherits the 401-then-403 guard by
construction. Handlers that write also take ``AdminAuth`` to read the caller's id for the audit
row; both guards are the same role set, so the effective guard is unchanged.

Every write requires ``reason`` and is audited by the service in the same transaction as the
change. Shared helpers live in ``lemely.web.admin_billing_common`` (DV-2); each later lane adds one
``include_router`` line below.
"""

# FastAPI ``Depends``/``response_model`` and pydantic construction need these type imports at
# runtime (see the per-file-ignore in pyproject.toml).
from __future__ import annotations

import uuid  # noqa: TC003 - FastAPI resolves the path-parameter type at runtime
from typing import Annotated

from fastapi import APIRouter, Depends

from lemely.db.admin_billing_repo import (
    UNSET,
    AdminCatalogueService,
    CreditPackFields,
    FreeAllowanceView,
    PlanTierFields,
    TierCounts,
    paymob_drift,
)
from lemely.db.models.billing import CreditPack, PlanAudience, PlanTier
from lemely.db.models.enums import PlanInterval, Role
from lemely.db.models.usage import EstimatorInputKind, UsageEstimator, UsageRate
from lemely.web.admin_billing_common import AdminAuth, admin_id, mapped_errors, require_aware
from lemely.web.deps import require_role
from lemely.web.deps_admin_billing import get_admin_catalogue_service
from lemely.web.schemas_admin_billing import (
    AdminCatalogueDTO,
    CreditPackCreateDTO,
    CreditPackDTO,
    CreditPackUpdateDTO,
    FreeAllowanceDTO,
    FreeAllowanceUpdateDTO,
    PlanTierCreateDTO,
    PlanTierDTO,
    PlanTierUpdateDTO,
    ReasonDTO,
    UsageEstimatorDTO,
    UsageEstimatorVersionDTO,
    UsageRateDTO,
    UsageRateVersionDTO,
)

router = APIRouter(
    prefix="/api/admin/billing",
    dependencies=[Depends(require_role(Role.platform_admin))],
)

CatalogueService = Annotated[AdminCatalogueService, Depends(get_admin_catalogue_service)]


# -- DTO mapping ------------------------------------------------------------------


def plan_tier_dto(t: PlanTier, key_mode: str, counts: TierCounts | None = None) -> PlanTierDTO:
    counts = counts or TierCounts()
    return PlanTierDTO(
        id=str(t.id),
        code=t.code,
        name=t.name,
        audience=t.audience.value,
        interval=t.interval.value if t.interval else None,
        priceMinor=t.price_minor,
        currency=t.currency,
        allowanceUnits=t.allowance_units,
        includedSeats=t.included_seats or 0,
        seatAllowanceUnits=t.seat_allowance_units or 0,
        extraSeatPriceMinor=t.extra_seat_price_minor or 0,
        features=dict(t.features or {}),
        isActive=t.is_active,
        version=t.version,
        termsVersion=t.terms_version,
        liveSubscriptionCount=counts.live,
        pendingMoves=counts.pending_moves,
        paymobPlanId=t.paymob_plan_id,
        paymobDrift=paymob_drift(t, key_mode),
    )


def credit_pack_dto(p: CreditPack, auto_topup_count: int = 0) -> CreditPackDTO:
    return CreditPackDTO(
        id=str(p.id),
        code=p.code,
        name=p.name,
        units=p.units,
        priceMinor=p.price_minor,
        currency=p.currency,
        isActive=p.is_active,
        version=p.version,
        autoTopupCount=auto_topup_count,
    )


def free_allowance_dto(f: FreeAllowanceView) -> FreeAllowanceDTO:
    return FreeAllowanceDTO(
        audience=f.audience,
        creditPackId=str(f.pack.id),
        units=f.pack.units,
        validDays=f.valid_days,
        version=f.pack.version,
    )


def usage_rate_dto(r: UsageRate) -> UsageRateDTO:
    return UsageRateDTO(
        id=str(r.id),
        version=r.version,
        action=r.action,
        unitsPerUsd=r.units_per_usd,
        effectiveFrom=r.effective_from,
    )


def usage_estimator_dto(e: UsageEstimator) -> UsageEstimatorDTO:
    return UsageEstimatorDTO(
        id=str(e.id),
        version=e.version,
        action=e.action,
        inputKind=e.input_kind.value,
        baseLow=e.base_low,
        baseHigh=e.base_high,
        perInputLow=e.per_input_low,
        perInputHigh=e.per_input_high,
        effectiveFrom=e.effective_from,
    )


def _tier_response(service: AdminCatalogueService, tier: PlanTier) -> PlanTierDTO:
    return plan_tier_dto(tier, service.key_mode, service.tier_counts().get(tier.id))


# -- area 1: catalogue ----------------------------------------------------------


@router.get("/catalogue", response_model=AdminCatalogueDTO)
def get_catalogue(service: CatalogueService) -> AdminCatalogueDTO:
    snap = service.catalogue()
    mode = service.key_mode
    return AdminCatalogueDTO(
        planTiers=[plan_tier_dto(t, mode, snap.tier_counts.get(t.id)) for t in snap.plan_tiers],
        creditPacks=[
            credit_pack_dto(p, snap.auto_topup_counts.get(p.id, 0)) for p in snap.credit_packs
        ],
        freeAllowances=[free_allowance_dto(f) for f in snap.free_allowances],
        usageRates=[usage_rate_dto(r) for r in snap.usage_rates],
        usageEstimators=[usage_estimator_dto(e) for e in snap.usage_estimators],
        subscriptionAmountUpdatable=service.subscription_amount_updatable,
        priceChangeNoticeDays=snap.price_change_notice_days,
    )


@router.post("/tiers", response_model=PlanTierDTO)
def create_tier(body: PlanTierCreateDTO, service: CatalogueService, auth: AdminAuth) -> PlanTierDTO:
    fields = PlanTierFields(
        code=body.code,
        name=body.name,
        audience=PlanAudience(body.audience),
        interval=PlanInterval(body.interval),
        price_minor=body.priceMinor,
        currency=body.currency,
        allowance_units=body.allowanceUnits,
        included_seats=body.includedSeats,
        seat_allowance_units=body.seatAllowanceUnits,
        extra_seat_price_minor=body.extraSeatPriceMinor,
        features=body.features,
        is_active=body.isActive,
    )
    with mapped_errors():
        tier = service.create_plan_tier(fields, admin_user_id=admin_id(auth), reason=body.reason)
    return _tier_response(service, tier)


@router.put("/tiers/{plan_tier_id}", response_model=PlanTierDTO)
def update_tier(
    plan_tier_id: uuid.UUID, body: PlanTierUpdateDTO, service: CatalogueService, auth: AdminAuth
) -> PlanTierDTO:
    changes = {
        "name": body.name,
        "price_minor": body.priceMinor,
        "allowance_units": body.allowanceUnits,
        "included_seats": body.includedSeats,
        "seat_allowance_units": body.seatAllowanceUnits,
        "extra_seat_price_minor": body.extraSeatPriceMinor,
        "features": body.features,
        "is_active": body.isActive,
    }
    with mapped_errors():
        tier = service.update_plan_tier(
            plan_tier_id,
            changes,
            admin_user_id=admin_id(auth),
            reason=body.reason,
            expected_version=body.expectedVersion,
        )
    return _tier_response(service, tier)


@router.post("/tiers/{plan_tier_id}/sync", response_model=PlanTierDTO)
def sync_tier(
    plan_tier_id: uuid.UUID, body: ReasonDTO, service: CatalogueService, auth: AdminAuth
) -> PlanTierDTO:
    with mapped_errors():
        tier = service.sync_paymob_plan(
            plan_tier_id, admin_user_id=admin_id(auth), reason=body.reason
        )
    return _tier_response(service, tier)


@router.post("/packs", response_model=CreditPackDTO)
def create_pack(
    body: CreditPackCreateDTO, service: CatalogueService, auth: AdminAuth
) -> CreditPackDTO:
    fields = CreditPackFields(
        code=body.code,
        name=body.name,
        units=body.units,
        price_minor=body.priceMinor,
        currency=body.currency,
        is_active=body.isActive,
    )
    with mapped_errors():
        pack = service.create_credit_pack(fields, admin_user_id=admin_id(auth), reason=body.reason)
    return credit_pack_dto(pack)


@router.put("/packs/{credit_pack_id}", response_model=CreditPackDTO)
def update_pack(
    credit_pack_id: uuid.UUID, body: CreditPackUpdateDTO, service: CatalogueService, auth: AdminAuth
) -> CreditPackDTO:
    changes = {
        "name": body.name,
        "units": body.units,
        "price_minor": body.priceMinor,
        "is_active": body.isActive,
    }
    with mapped_errors():
        pack = service.update_credit_pack(
            credit_pack_id,
            changes,
            admin_user_id=admin_id(auth),
            reason=body.reason,
            expected_version=body.expectedVersion,
        )
    return credit_pack_dto(pack)


@router.put("/free-allowances", response_model=FreeAllowanceDTO)
def set_free_allowance(
    body: FreeAllowanceUpdateDTO, service: CatalogueService, auth: AdminAuth
) -> FreeAllowanceDTO:
    with mapped_errors():
        view = service.set_free_allowance(
            audience=body.audience,
            units=body.units,
            valid_days=body.validDays if "validDays" in body.model_fields_set else UNSET,
            admin_user_id=admin_id(auth),
            reason=body.reason,
            expected_version=body.expectedVersion,
        )
    return free_allowance_dto(view)


@router.post("/rates", response_model=UsageRateDTO)
def add_rate(body: UsageRateVersionDTO, service: CatalogueService, auth: AdminAuth) -> UsageRateDTO:
    with mapped_errors():
        row = service.add_usage_rate(
            action=body.action,
            units_per_usd=body.unitsPerUsd,
            effective_from=require_aware(body.effectiveFrom, "effectiveFrom"),
            admin_user_id=admin_id(auth),
            reason=body.reason,
        )
    return usage_rate_dto(row)


@router.post("/estimators", response_model=UsageEstimatorDTO)
def add_estimator(
    body: UsageEstimatorVersionDTO, service: CatalogueService, auth: AdminAuth
) -> UsageEstimatorDTO:
    with mapped_errors():
        row = service.add_usage_estimator(
            action=body.action,
            input_kind=EstimatorInputKind(body.inputKind),
            base_low=body.baseLow,
            base_high=body.baseHigh,
            per_input_low=body.perInputLow,
            per_input_high=body.perInputHigh,
            effective_from=require_aware(body.effectiveFrom, "effectiveFrom"),
            admin_user_id=admin_id(auth),
            reason=body.reason,
        )
    return usage_estimator_dto(row)
