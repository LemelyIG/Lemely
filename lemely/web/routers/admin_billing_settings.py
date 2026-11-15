"""Admin billing, settings lane: scalar billing settings and credit conversion rates (UD-13).

A lane router of ``admin_billing`` (DV-2, DV-T5a). It is mounted in ``app.py`` beside the parent
with the full prefix and carries its own ``platform_admin`` guard, never nested into the parent.
Each write is one audited transaction (reason required) with optimistic concurrency: the admin
sends the ``version`` they read, a stale one is 409 ``stale_write``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends

from lemely.db.billing_settings_repo import (
    API_NAMES,
    BillingSettingsService,
    BillingSettingsView,
    CreditRateView,
)
from lemely.db.models.enums import Role
from lemely.db.session import get_sessionmaker
from lemely.web.admin_billing_common import AdminAuth, admin_id, mapped_errors, optional_id
from lemely.web.deps import get_settings, require_role
from lemely.web.schemas_admin_billing_settings import (
    BillingSettingsDTO,
    BillingSettingsUpdate,
    CreditRateClear,
    CreditRateDTO,
    CreditRatesDTO,
    CreditRateSet,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

router = APIRouter(
    prefix="/api/admin/billing",
    dependencies=[Depends(require_role(Role.platform_admin))],
)


def get_billing_settings_service() -> Iterator[BillingSettingsService]:
    """One service on one transaction per request: commit when the handler returns.

    The handler turns a service error into an ``HTTPException``, which reaches this generator and
    rolls the transaction back, audit row and all. Tests override this dependency.
    """
    with get_sessionmaker(get_settings()).begin() as session:
        yield BillingSettingsService(session)


SettingsService = Annotated[BillingSettingsService, Depends(get_billing_settings_service)]


def settings_dto(view: BillingSettingsView) -> BillingSettingsDTO:
    margin = view.margin_egp_per_usd
    code = view.code_execution_usd_per_hour
    return BillingSettingsDTO(
        creditValidityMonths=view.credit_validity_months,
        graceDays=view.grace_days,
        maxExtraSeats=view.max_extra_seats,
        priceChangeNoticeDays=view.price_change_notice_days,
        marginEgpPerUsd=None if margin is None else format(margin.normalize(), "f"),
        codeExecutionUsdPerHour=None if code is None else f"{code:.6f}",
        version=view.version,
        updatedAt=view.updated_at,
        updatedBy=optional_id(view.updated_by),
    )


def credit_rate_dto(view: CreditRateView) -> CreditRateDTO:
    return CreditRateDTO(
        currency=view.currency,
        unitsPerMinor=f"{view.units_per_minor:.6f}",
        version=view.version,
        updatedAt=view.updated_at,
        updatedBy=optional_id(view.updated_by),
    )


@router.get("/settings", response_model=BillingSettingsDTO)
def read_settings(service: SettingsService) -> BillingSettingsDTO:
    return settings_dto(service.get())


@router.put("/settings", response_model=BillingSettingsDTO)
def update_settings(
    body: BillingSettingsUpdate, auth: AdminAuth, service: SettingsService
) -> BillingSettingsDTO:
    """A partial update; a field left out is untouched, one equal to its value is still a write."""
    given = body.model_fields_set
    fields = {name: getattr(body, api) for name, api in API_NAMES.items() if api in given}
    with mapped_errors():
        return settings_dto(
            service.update(
                admin_id(auth),
                fields=fields,
                expected_version=body.expectedVersion,
                reason=body.reason,
            )
        )


@router.get("/credit-rates", response_model=CreditRatesDTO)
def read_credit_rates(service: SettingsService) -> CreditRatesDTO:
    return CreditRatesDTO(rates=[credit_rate_dto(r) for r in service.list_rates()])


@router.put("/credit-rates/{currency}", response_model=CreditRateDTO)
def set_credit_rate(
    currency: str, body: CreditRateSet, auth: AdminAuth, service: SettingsService
) -> CreditRateDTO:
    with mapped_errors():
        return credit_rate_dto(
            service.set_credit_rate(
                admin_id(auth),
                currency=currency,
                units_per_minor=body.unitsPerMinor,
                expected_version=body.expectedVersion,
                reason=body.reason,
            )
        )


@router.post("/credit-rates/{currency}/clear", response_model=CreditRatesDTO)
def clear_credit_rate(
    currency: str, body: CreditRateClear, auth: AdminAuth, service: SettingsService
) -> CreditRatesDTO:
    with mapped_errors():
        rates = service.clear_credit_rate(
            admin_id(auth),
            currency=currency,
            expected_version=body.expectedVersion,
            confirm_stop_conversions=body.confirmStopConversions,
            reason=body.reason,
        )
    return CreditRatesDTO(rates=[credit_rate_dto(r) for r in rates])
