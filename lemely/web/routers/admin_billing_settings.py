"""Admin billing, settings lane: scalar billing settings and credit conversion rates (UD-13).

A lane router of ``admin_billing`` (DV-2, DV-T5a). It is mounted in ``app.py`` beside the parent
with the full prefix and carries its own ``platform_admin`` guard, never nested into the parent.
Each write is one audited transaction (reason required) with optimistic concurrency: the admin
sends the ``version`` they read, a stale one is 409 ``stale_write``.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends

from lemely.db.billing_settings_repo import (
    API_NAMES,
    BillingSettingsService,
    BillingSettingsView,
    CreditRateView,
)
from lemely.db.llm_price_repo import LlmPriceService, LlmPriceView
from lemely.db.models.enums import Role
from lemely.db.session import get_sessionmaker
from lemely.io.gemini import code_price_models, code_price_row
from lemely.io.llm.pricing import CLAUDE_PRICE_SOURCES, PriceRow
from lemely.io.providers import is_anthropic_model
from lemely.runtime.config import Settings  # noqa: TC001 - FastAPI resolves the dependency type
from lemely.web.admin_billing_common import AdminAuth, admin_id, mapped_errors, optional_id
from lemely.web.deps import get_settings, require_role
from lemely.web.llm_price_refresh import refresh_after_commit
from lemely.web.schemas_admin_billing_settings import (
    BillingSettingsDTO,
    BillingSettingsUpdate,
    CreditRateClear,
    CreditRateDTO,
    CreditRatesDTO,
    CreditRateSet,
    LlmCodeDefaultDTO,
    LlmModelDTO,
    LlmModelsDTO,
    LlmPriceClear,
    LlmPriceDTO,
    LlmPriceSet,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker


router = APIRouter(
    prefix="/api/admin/billing",
    dependencies=[Depends(require_role(Role.platform_admin))],
)


def get_billing_settings_service() -> Iterator[BillingSettingsService]:
    """One service on one transaction per request: commit when the handler returns.

    The handler turns a service error into an ``HTTPException``, which reaches this generator and
    rolls the transaction back, audit row and all. Tests override this dependency.
    """
    factory = get_sessionmaker(get_settings())
    with factory.begin() as session:
        yield BillingSettingsService(session)
    # Committed: a changed container-hour price reaches this process now (UD13-D, DV-6). A refused
    # request raised above and never gets here.
    refresh_after_commit(factory)


SettingsService = Annotated[BillingSettingsService, Depends(get_billing_settings_service)]


def llm_price_scope(factory: sessionmaker[Session]) -> Iterator[LlmPriceService]:
    """One price service on one transaction; after a committed write, refresh this process.

    The other instances pick the change up from the ``billing.llm_price_refresh`` job within one
    sweep pass (normally about 60 seconds, longer when a pass is slow). A refused request raises
    inside the ``with``, rolls back and never refreshes.
    """
    with factory.begin() as session:
        service = LlmPriceService(session)
        yield service
    if service.wrote:
        refresh_after_commit(factory)


def get_llm_price_service() -> Iterator[LlmPriceService]:
    """The price service of this request. Tests override this dependency."""
    yield from llm_price_scope(get_sessionmaker(get_settings()))


PriceService = Annotated[LlmPriceService, Depends(get_llm_price_service)]


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
                confirm_unusual_price=body.confirmUnusualPrice,
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


_PER_MTOK = Decimal(1000)


def _mtok(per_1k: float | None) -> str | None:
    """A per-1k float rate as a per-million-token decimal string (``0.0001`` becomes ``0.1``)."""
    if per_1k is None:
        return None
    return format((Decimal(repr(per_1k)) * _PER_MTOK).normalize(), "f")


def _default_dto(row: PriceRow, *, source: str, read_on: date | None) -> LlmCodeDefaultDTO:
    tier = row.tier2
    return LlmCodeDefaultDTO(
        inputUsdPerMtok=_mtok(row.input) or "0",
        outputUsdPerMtok=_mtok(row.output) or "0",
        cachedInputUsdPerMtok=_mtok(row.cached_input),
        cacheWrite5mUsdPerMtok=_mtok(row.cache_write_5m),
        cacheWrite1hUsdPerMtok=_mtok(row.cache_write_1h),
        tiered=tier is not None,
        tierThresholdTokens=row.tier_threshold_tokens if tier is not None else None,
        tier2InputUsdPerMtok=_mtok(tier.input) if tier is not None else None,
        tier2OutputUsdPerMtok=_mtok(tier.output) if tier is not None else None,
        source=source,
        readOn=read_on,
    )


def _decimal_text(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


def llm_price_dto(view: LlmPriceView) -> LlmPriceDTO:
    return LlmPriceDTO(
        model=view.model,
        inputUsdPerMtok=format(view.input_usd_per_mtok, "f"),
        outputUsdPerMtok=format(view.output_usd_per_mtok, "f"),
        cachedInputUsdPerMtok=_decimal_text(view.cached_input_usd_per_mtok),
        cacheWrite5mUsdPerMtok=_decimal_text(view.cache_write_5m_usd_per_mtok),
        cacheWrite1hUsdPerMtok=_decimal_text(view.cache_write_1h_usd_per_mtok),
        tierThresholdTokens=view.tier_threshold_tokens,
        tier2InputUsdPerMtok=_decimal_text(view.tier2_input_usd_per_mtok),
        tier2OutputUsdPerMtok=_decimal_text(view.tier2_output_usd_per_mtok),
        version=view.version,
        updatedAt=view.updated_at,
        updatedBy=optional_id(view.updated_by),
    )


def _default_rows(
    name: str, settings: Settings, today: date
) -> tuple[PriceRow | None, PriceRow | None]:
    """``(code row, default row)`` of ``name``.

    The code row is the code table's own (the vendor's tiers). The default row is the price with no
    override: the config rate when set, else the code row.
    """
    code_row = code_price_row(name, today)
    rate = settings.gemini.pricing.get(name)
    if rate is None:
        return code_row, code_row
    return code_row, PriceRow(float(rate[0]), float(rate[0]), float(rate[1]))


def _model_rows(service: LlmPriceService, settings: Settings, *, today: date) -> list[LlmModelDTO]:
    """Code table keys, config keys, models seen in the last 30 days and overrides, by name."""
    overrides = {view.model: view for view in service.list()}
    seen = service.seen()
    config = settings.gemini.pricing
    names = {*code_price_models(today), *config, *seen, *overrides}
    rows: list[LlmModelDTO] = []
    for name in sorted(names):
        default: LlmCodeDefaultDTO | None = None
        if name in config:
            rate = config[name]
            default = _default_dto(
                PriceRow(float(rate[0]), float(rate[0]), float(rate[1])),
                source="config",
                read_on=None,
            )
        else:
            code_row = code_price_row(name, today)
            if code_row is not None:
                url, read_on = CLAUDE_PRICE_SOURCES.get(
                    name, ("built-in table, lemely.io.gemini", None)
                )
                default = _default_dto(code_row, source=url, read_on=read_on)
        override = overrides.get(name)
        rows.append(
            LlmModelDTO(
                model=name,
                provider="anthropic" if is_anthropic_model(name) else "gemini",
                codeDefault=default,
                override=None if override is None else llm_price_dto(override),
                seenInLast30Days=name in seen,
            )
        )
    return rows


def _models_body(service: LlmPriceService, settings: Settings) -> LlmModelsDTO:
    return LlmModelsDTO(models=_model_rows(service, settings, today=datetime.now(UTC).date()))


@router.get("/llm-prices", response_model=LlmModelsDTO)
def read_llm_prices(
    service: PriceService, settings: Annotated[Settings, Depends(get_settings)]
) -> LlmModelsDTO:
    return _models_body(service, settings)


def _rates(body: LlmPriceSet) -> dict[str, object]:
    return {
        "input_usd_per_mtok": body.inputUsdPerMtok,
        "output_usd_per_mtok": body.outputUsdPerMtok,
        "cached_input_usd_per_mtok": body.cachedInputUsdPerMtok,
        "cache_write_5m_usd_per_mtok": body.cacheWrite5mUsdPerMtok,
        "cache_write_1h_usd_per_mtok": body.cacheWrite1hUsdPerMtok,
        "tier_threshold_tokens": body.tierThresholdTokens,
        "tier2_input_usd_per_mtok": body.tier2InputUsdPerMtok,
        "tier2_output_usd_per_mtok": body.tier2OutputUsdPerMtok,
    }


@router.put("/llm-prices/{model}", response_model=LlmPriceDTO)
def set_llm_price(
    model: str,
    body: LlmPriceSet,
    auth: AdminAuth,
    service: PriceService,
    settings: Annotated[Settings, Depends(get_settings)],
) -> LlmPriceDTO:
    code_row, default_row = _default_rows(model, settings, datetime.now(UTC).date())
    with mapped_errors():
        return llm_price_dto(
            service.set_price(
                admin_id(auth),
                model=model,
                rates=_rates(body),
                expected_version=body.expectedVersion,
                reason=body.reason,
                code_row=code_row,
                default_row=default_row,
                confirm_drop_tier=body.confirmDropTier,
                confirm_unusual_price=body.confirmUnusualPrice,
            )
        )


@router.post("/llm-prices/{model}/clear", response_model=LlmModelsDTO)
def clear_llm_price(
    model: str,
    body: LlmPriceClear,
    auth: AdminAuth,
    service: PriceService,
    settings: Annotated[Settings, Depends(get_settings)],
) -> LlmModelsDTO:
    with mapped_errors():
        service.clear_price(
            admin_id(auth),
            model=model,
            expected_version=body.expectedVersion,
            reason=body.reason,
        )
    return _models_body(service, settings)
