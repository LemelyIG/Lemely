"""DTOs for ``/api/admin/billing/settings`` and ``/credit-rates`` (UD-13, Phase 07 T14).

camelCase on the wire, ``extra="forbid"`` (``ApiModel``). Decimals leave as strings so no float
rounds them. The ranges are not repeated here: the service checks them and answers 422
``invalid_setting`` / ``invalid_rate`` with a message naming the field and its range, so the
limits live in one place (``lemely.db.billing_settings_repo``). A decimal field accepts a JSON
string or number; ``null`` clears the two optional decimals.
"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - pydantic resolves annotations at runtime
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
    expectedVersion: StrictInt
    reason: Reason
