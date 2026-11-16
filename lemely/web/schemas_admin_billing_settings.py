"""DTOs for ``/api/admin/billing/settings`` and ``/credit-rates`` (UD-13, Phase 07 T14).

camelCase on the wire, ``extra="forbid"`` (``ApiModel``). Decimals leave as strings so no float
rounds them. The ranges are not repeated here: the service checks them and answers 422
``invalid_setting`` / ``invalid_rate`` with a message naming the field and its range, so the
limits live in one place (``lemely.db.billing_settings_repo``). A decimal field accepts a JSON
string or number; ``null`` clears the two optional decimals.
"""

from __future__ import annotations

from datetime import date, datetime  # noqa: TC003 - pydantic resolves annotations at runtime
from decimal import Decimal  # noqa: TC003 - pydantic resolves annotations at runtime
from typing import Annotated

from pydantic import Field

from lemely.web.schemas_admin import ApiModel
from lemely.web.schemas_admin_billing import Reason  # noqa: TC001 - pydantic resolves it

StrictInt = Annotated[int, Field(strict=True)]


class BillingSettingsDTO(ApiModel):
    creditValidityMonths: int
    graceDays: int
    maxExtraSeats: int
    priceChangeNoticeDays: int
    marginEgpPerUsd: str | None
    codeExecutionUsdPerHour: str | None
    version: int
    updatedAt: datetime
    updatedBy: str | None


class BillingSettingsUpdate(ApiModel):
    """A partial update: a field left out is untouched; ``null`` is legal for the two decimals."""

    creditValidityMonths: StrictInt | None = None
    graceDays: StrictInt | None = None
    maxExtraSeats: StrictInt | None = None
    priceChangeNoticeDays: StrictInt | None = None
    marginEgpPerUsd: Decimal | None = None
    codeExecutionUsdPerHour: Decimal | None = None
    #: Needed for a container-hour price below 1/100 or above 100x the code value.
    confirmUnusualPrice: bool = False
    expectedVersion: StrictInt
    reason: Reason


class CreditRateDTO(ApiModel):
    currency: str
    unitsPerMinor: str
    version: int
    updatedAt: datetime
    updatedBy: str | None


class CreditRatesDTO(ApiModel):
    rates: list[CreditRateDTO]


class CreditRateSet(ApiModel):
    """``expectedVersion`` is ``null`` to create a rate, the version read to replace one."""

    unitsPerMinor: Decimal
    expectedVersion: StrictInt | None
    reason: Reason


class CreditRateClear(ApiModel):
    """``confirmStopConversions`` must be ``true``: with no rate, conversions fail closed."""

    expectedVersion: StrictInt
    confirmStopConversions: bool = False
    reason: Reason


class LlmPriceDTO(ApiModel):
    """An admin price override. USD per million tokens, as exact decimal strings."""

    model: str
    inputUsdPerMtok: str
    outputUsdPerMtok: str
    cachedInputUsdPerMtok: str | None
    cacheWrite5mUsdPerMtok: str | None
    cacheWrite1hUsdPerMtok: str | None
    tierThresholdTokens: int | None
    tier2InputUsdPerMtok: str | None
    tier2OutputUsdPerMtok: str | None
    version: int
    updatedAt: datetime
    updatedBy: str | None


class LlmCodeDefaultDTO(ApiModel):
    """The price a model has with no override: the config rate if set, else the code table's."""

    inputUsdPerMtok: str
    outputUsdPerMtok: str
    cachedInputUsdPerMtok: str | None
    cacheWrite5mUsdPerMtok: str | None
    cacheWrite1hUsdPerMtok: str | None
    tiered: bool
    tierThresholdTokens: int | None
    tier2InputUsdPerMtok: str | None
    tier2OutputUsdPerMtok: str | None
    #: ``config`` for a ``gemini.pricing`` entry, else where the code table's rate was read.
    source: str
    readOn: date | None


class LlmModelDTO(ApiModel):
    model: str
    provider: str
    codeDefault: LlmCodeDefaultDTO | None
    override: LlmPriceDTO | None
    seenInLast30Days: bool


class LlmModelsDTO(ApiModel):
    models: list[LlmModelDTO]


class LlmPriceSet(ApiModel):
    """``expectedVersion`` is ``null`` to create an override, the version read to replace one.

    Every field but the model is a full replacement: an optional price left ``null`` is cleared.
    The ranges are checked by ``Override`` (above 0, at most 1000 USD per million tokens).
    """

    inputUsdPerMtok: Decimal
    outputUsdPerMtok: Decimal
    cachedInputUsdPerMtok: Decimal | None = None
    cacheWrite5mUsdPerMtok: Decimal | None = None
    cacheWrite1hUsdPerMtok: Decimal | None = None
    tierThresholdTokens: StrictInt | None = None
    tier2InputUsdPerMtok: Decimal | None = None
    tier2OutputUsdPerMtok: Decimal | None = None
    #: Needed to set a flat price on a model whose vendor price has a tier (422 otherwise).
    confirmDropTier: bool = False
    #: Needed for a price below 1/100 or above 100x the model's default (422 otherwise).
    confirmUnusualPrice: bool = False
    expectedVersion: StrictInt | None
    reason: Reason


class LlmPriceClear(ApiModel):
    expectedVersion: StrictInt
    reason: Reason
