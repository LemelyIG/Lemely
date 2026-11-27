"""DTOs for the merchant-charge routes (Phase 06 T9; camelCase wire format).

The shapes are the ones the built frontend reads (``web/src/lib/billingTypes.ts``: ``WireQuote``,
``WireSeats``, ``WireAutoTopup``). Requests forbid extra keys, so a client-sent price is a 422.
The upgrade and seat POSTs answer with ``schemas_billing.CheckoutDTO``: there is no charge DTO.
"""

from __future__ import annotations

import uuid  # noqa: TC003 - pydantic reads the type at runtime
from datetime import datetime  # noqa: TC003 - pydantic reads the type at runtime

from pydantic import Field

from lemely.db.auto_topup_repo import MAX_SETTING_VALUE
from lemely.db.merchant_charge_repo import MAX_SEATS_PER_PURCHASE
from lemely.web.schemas import ApiModel


class UpgradeRequest(ApiModel):
    """Body for the upgrade quote and the upgrade checkout; the price is never client-sent."""

    planTierId: uuid.UUID


class ExtraSeatsRequest(ApiModel):
    """Body for the seat quote and the seat checkout."""

    seats: int = Field(ge=1, le=MAX_SEATS_PER_PURCHASE)


class SeatReductionRequest(ApiModel):
    """Body for ``PUT .../seats/pending``: the extra-seat total wanted from the next renewal."""

    #: ``le`` is a sanity bound (``billing_settings.max_extra_seats`` tops out at 10 000); the
    #: service holds the admin-set ceiling, and a reduction never needs it (UD-13 A15).
    extraSeats: int = Field(ge=0, le=10_000)


class AutoTopupRequest(ApiModel):
    """Body for ``PUT /api/billing/auto-topup``; ``beneficiaryId`` is ``null`` for the caller."""

    beneficiaryId: uuid.UUID | None = None
    enabled: bool
    thresholdUnits: int = Field(gt=0, le=MAX_SETTING_VALUE)
    creditPackId: uuid.UUID
    savedCardId: uuid.UUID | None = None
    monthlyCapMinor: int = Field(ge=0, le=MAX_SETTING_VALUE)


class ChargeQuoteDTO(ApiModel):
    """What an upgrade or seat purchase would charge now (exactly these four keys)."""

    amountMinor: int
    currency: str
    allowanceUnits: int | None
    periodEnd: datetime


class SeatsDTO(ApiModel):
    """The extra seats held and the total scheduled from the next renewal (or ``None``)."""

    extraSeats: int
    pendingExtraSeats: int | None


class AutoTopupDTO(ApiModel):
    """One balance's auto top-up; a balance never set up reads as disabled with ``None`` fields."""

    beneficiaryId: str
    enabled: bool
    thresholdUnits: int | None
    creditPackId: str | None
    savedCardId: str | None
    monthlyCapMinor: int | None
    spentThisMonthMinor: int
    currency: str
    disabledReason: str | None


__all__ = [
    "AutoTopupDTO",
    "AutoTopupRequest",
    "ChargeQuoteDTO",
    "ExtraSeatsRequest",
    "SeatReductionRequest",
    "SeatsDTO",
    "UpgradeRequest",
]
