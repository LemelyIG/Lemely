"""Admin-editable billing settings and credit conversion rates (UD-13, UD-12; Phase 07 T14).

Two stores, both read in the caller's transaction with no cache (UD13-DV-2):

* ``billing_settings``: the single ``id = 1`` row of six scalars. :func:`get_billing_settings`
  inserts the defaults on first read, so a ``create_all`` database never answers "no row".
* ``credit_conversion_rates``: usage units one minor currency unit buys, one row per currency.

Every write goes through :class:`BillingSettingsService`. It validates first, then locks the row
``FOR UPDATE``, compares the version the admin read, writes, bumps ``version`` and adds exactly one
audit row last, in the caller's transaction. A refusal therefore leaves no audit row. Each bound
below is the same as the database CHECK and as what the runtime consumers accept:

* ``credit_validity_months`` 1-120 (months added to a grant's start);
* ``grace_days`` 1-7 (UD13-C; Paymob ``retrial_days`` is capped at 7);
* ``max_extra_seats`` 1-10000 (the seat sanity bound of the seat purchase routes);
* ``price_change_notice_days`` 7-90 (UD13-G);
* ``margin_egp_per_usd`` greater than 0 up to 10000 with at most 4 decimals (the margin report's
  own ``egpPerUsd`` bound, ``NUMERIC(12, 4)``);
* ``code_execution_usd_per_hour`` greater than 0 up to 100 with at most 6 decimals
  (``NUMERIC(10, 6)``). Zero is refused: it would bill code execution for nothing (T19, UD13-D);
* a conversion rate greater than 0 up to 100000 with at most 6 decimals. The cap keeps
  ``amount_minor x rate`` inside ``BIGINT`` for every payment the database can hold (Phase 05
  UD-12 review M-1).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Final

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert

from lemely.core.billing_defaults import (
    CREDIT_VALIDITY_MONTHS,
    GRACE_DAYS,
    MAX_EXTRA_SEATS,
    PRICE_CHANGE_NOTICE_DAYS,
)
from lemely.db.admin_billing_repo import (
    AdminConflictError,
    AdminInvalidError,
    AdminNotFoundError,
    AuditAction,
    AuditTarget,
    audited,
    lock_idempotency_key,
    require_reason,
    snapshot,
)
from lemely.db.models.admin_audit import AdminAuditLog
from lemely.db.models.billing_ops import BillingSettings, CreditConversionRate
from lemely.io.llm.price_overrides import CODE_EXECUTION_HOUR_MAX

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from sqlalchemy.orm import Session

#: The audit actions, members of ``AuditAction``.
ACTION_SETTINGS_UPDATE: Final = AuditAction.BILLING_SETTINGS_UPDATE
ACTION_CREDIT_RATE_SET: Final = AuditAction.CREDIT_RATE_SET
ACTION_CREDIT_RATE_CLEAR: Final = AuditAction.CREDIT_RATE_CLEAR

#: The audit target of the settings row: ``audit.target_id`` is a UUID, the row's key is ``1``.
SETTINGS_TARGET_ID: Final = uuid.UUID(int=1)
SETTINGS_TARGET_KIND: Final = AuditTarget.BILLING_SETTINGS

INT_FIELDS: Final[Mapping[str, tuple[int, int]]] = {
    "credit_validity_months": (1, 120),
    "grace_days": (1, 7),
    "max_extra_seats": (1, 10_000),
    "price_change_notice_days": (7, 90),
}
#: ``(lowest allowed, highest allowed, most decimal places, lowest is allowed)``.
DECIMAL_FIELDS: Final[Mapping[str, tuple[Decimal, Decimal, int, bool]]] = {
    "margin_egp_per_usd": (Decimal(0), Decimal(10_000), 4, False),
    "code_execution_usd_per_hour": (Decimal(0), CODE_EXECUTION_HOUR_MAX, 6, False),
}
SETTING_FIELDS: Final = (*INT_FIELDS, *DECIMAL_FIELDS)
#: The wire name of each setting; error messages name the field as the admin sent it.
API_NAMES: Final[Mapping[str, str]] = {
    "credit_validity_months": "creditValidityMonths",
    "grace_days": "graceDays",
    "max_extra_seats": "maxExtraSeats",
    "price_change_notice_days": "priceChangeNoticeDays",
    "margin_egp_per_usd": "marginEgpPerUsd",
    "code_execution_usd_per_hour": "codeExecutionUsdPerHour",
}

RATE_MAX: Final = Decimal(100_000)
RATE_PLACES: Final = 6

_SETTINGS_AUDIT: Final = (*SETTING_FIELDS, "version")
_RATE_AUDIT: Final = ("currency", "units_per_minor", "version")


@dataclass(frozen=True, slots=True)
class BillingSettingsView:
    credit_validity_months: int
    grace_days: int
    max_extra_seats: int
    price_change_notice_days: int
    margin_egp_per_usd: Decimal | None
    code_execution_usd_per_hour: Decimal | None
    version: int
    updated_at: datetime
    updated_by: uuid.UUID | None


@dataclass(frozen=True, slots=True)
class CreditRateView:
    currency: str
    units_per_minor: Decimal
    version: int
    updated_at: datetime
    updated_by: uuid.UUID | None


def _utc_now() -> datetime:
    return datetime.now(UTC)


def ensure_billing_settings(session: Session) -> None:
    """Insert the ``id = 1`` row with the seed defaults; a no-op when it exists."""
    session.execute(
        pg_insert(BillingSettings)
        .values(
            id=1,
            credit_validity_months=CREDIT_VALIDITY_MONTHS,
            grace_days=GRACE_DAYS,
            max_extra_seats=MAX_EXTRA_SEATS,
            price_change_notice_days=PRICE_CHANGE_NOTICE_DAYS,
        )
        .on_conflict_do_nothing(index_elements=[BillingSettings.id])
    )


def _view(row: BillingSettings) -> BillingSettingsView:
    return BillingSettingsView(
        credit_validity_months=row.credit_validity_months,
        grace_days=row.grace_days,
        max_extra_seats=row.max_extra_seats,
        price_change_notice_days=row.price_change_notice_days,
        margin_egp_per_usd=row.margin_egp_per_usd,
        code_execution_usd_per_hour=row.code_execution_usd_per_hour,
        version=row.version,
        updated_at=row.updated_at,
        updated_by=row.updated_by,
    )


def _rate_view(row: CreditConversionRate) -> CreditRateView:
    return CreditRateView(
        currency=row.currency,
        units_per_minor=row.units_per_minor,
        version=row.version,
        updated_at=row.updated_at,
        updated_by=row.updated_by,
    )


def get_billing_settings(session: Session) -> BillingSettingsView:
    """The settings, inserting the defaults once when the row is missing. Never cached."""
    ensure_billing_settings(session)
    row = session.execute(
        sa.select(BillingSettings)
        .where(BillingSettings.id == 1)
        .execution_options(populate_existing=True)
    ).scalar_one()
    return _view(row)


def list_credit_rates(session: Session) -> list[CreditRateView]:
    """Every configured conversion rate, by currency."""
    rows = session.scalars(
        sa.select(CreditConversionRate)
        .order_by(CreditConversionRate.currency)
        .execution_options(populate_existing=True)
    )
    return [_rate_view(row) for row in rows]


def credit_rate_for(session: Session, currency: str) -> Decimal | None:
    """Units one minor unit of ``currency`` buys, or ``None`` when no rate is set."""
    return session.scalar(
        sa.select(CreditConversionRate.units_per_minor).where(
            CreditConversionRate.currency == currency
        )
    )


def _places(value: Decimal) -> int:
    exponent = value.normalize().as_tuple().exponent
    return -exponent if isinstance(exponent, int) and exponent < 0 else 0


def _validate_int(name: str, value: object) -> int:
    low, high = INT_FIELDS[name]
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise AdminInvalidError(
            "invalid_setting", f"{API_NAMES[name]} must be a whole number from {low} to {high}."
        )
    return value


def _validate_decimal(name: str, value: object) -> Decimal | None:
    low, high, places, low_ok = DECIMAL_FIELDS[name]
    if value is None:
        return None
    bound = f"at least {low}" if low_ok else f"greater than {low}"
    problem = (
        f"{API_NAMES[name]} must be empty, or {bound} and at most {high}, "
        f"with at most {places} decimal places."
    )
    if (
        not isinstance(value, Decimal)
        or not value.is_finite()
        or value > high
        or value < low
        or (value == low and not low_ok)
        or _places(value) > places
    ):
        raise AdminInvalidError("invalid_setting", problem)
    return value


def validate_settings(fields: Mapping[str, object]) -> dict[str, int | Decimal | None]:
    """The checked ``fields`` (only the six setting names), or ``AdminInvalidError``.

    Raises:
        AdminInvalidError: ``no_setting_given`` for an empty mapping; ``invalid_setting`` for an
            unknown name, a wrong type or a value outside its range (the message names both).
    """
    if not fields:
        raise AdminInvalidError("no_setting_given", "Send at least one setting to change.")
    clean: dict[str, int | Decimal | None] = {}
    for name, value in fields.items():
        if name in INT_FIELDS:
            clean[name] = _validate_int(name, value)
        elif name in DECIMAL_FIELDS:
            clean[name] = _validate_decimal(name, value)
        else:
            raise AdminInvalidError("invalid_setting", f"{name} is not a billing setting.")
    return clean


def validate_currency(currency: str) -> str:
    if not (
        len(currency) == 3 and currency.isascii() and currency.isalpha() and currency.isupper()
    ):
        raise AdminInvalidError(
            "invalid_currency", "A currency is three upper-case letters, such as EGP."
        )
    return currency


def validate_rate(units_per_minor: object) -> Decimal:
    message = (
        f"unitsPerMinor must be greater than 0 and at most {RATE_MAX}, "
        f"with at most {RATE_PLACES} decimal places."
    )
    if (
        not isinstance(units_per_minor, Decimal)
        or not units_per_minor.is_finite()
        or units_per_minor <= 0
        or units_per_minor > RATE_MAX
        or _places(units_per_minor) > RATE_PLACES
    ):
        raise AdminInvalidError("invalid_rate", message)
    return units_per_minor


def _stale(what: str) -> AdminConflictError:
    return AdminConflictError(
        "stale_write", f"{what} changed since you loaded it. Reload and try again."
    )


class BillingSettingsService:
    """Audited writes of the settings row and the conversion rates.

    The caller owns the transaction: commit on success, roll back on any raised error. Because the
    audit row joins that transaction, a refusal can never leave one.
    """

    def __init__(self, session: Session, *, now: Callable[[], datetime] = _utc_now) -> None:
        self._s = session
        self._now = now

    def get(self) -> BillingSettingsView:
        return get_billing_settings(self._s)

    def list_rates(self) -> list[CreditRateView]:
        return list_credit_rates(self._s)

    def update(
        self,
        admin_id: uuid.UUID,
        *,
        fields: Mapping[str, object],
        expected_version: int,
        reason: str,
    ) -> BillingSettingsView:
        require_reason(reason)
        clean = validate_settings(fields)
        ensure_billing_settings(self._s)
        row = self._s.execute(
            sa.select(BillingSettings)
            .where(BillingSettings.id == 1)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).scalar_one()
        if row.version != expected_version:
            raise _stale("The billing settings")
        before = snapshot(row, _SETTINGS_AUDIT)
        for name, value in clean.items():
            setattr(row, name, value)
        row.version += 1
        row.updated_by = admin_id
        row.updated_at = self._now()
        self._s.flush()
        self._s.refresh(row)  # the audit and the answer carry the stored (quantised) values
        audited(
            self._s,
            admin_id,
            ACTION_SETTINGS_UPDATE,
            SETTINGS_TARGET_KIND,
            SETTINGS_TARGET_ID,
            reason,
            before,
            snapshot(row, _SETTINGS_AUDIT),
        )
        return _view(row)

    def _locked_rate(self, currency: str) -> CreditConversionRate | None:
        lock_idempotency_key(self._s, f"credit-rate:{currency}")
        return self._s.execute(
            sa.select(CreditConversionRate)
            .where(CreditConversionRate.currency == currency)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()

    def _highest_version_seen(self, currency: str) -> int:
        """The highest version any set or clear of ``currency`` left in the audit log (0 if none).

        Called under the per-currency advisory lock, so no other writer adds a row meanwhile.
        """
        versions = [
            sa.cast(AdminAuditLog.before["version"].astext, sa.Integer),
            sa.cast(AdminAuditLog.after["version"].astext, sa.Integer),
        ]
        highest = self._s.scalar(
            sa.select(sa.func.max(sa.func.greatest(*versions))).where(
                AdminAuditLog.action.in_((ACTION_CREDIT_RATE_SET, ACTION_CREDIT_RATE_CLEAR)),
                sa.or_(
                    AdminAuditLog.before["currency"].astext == currency,
                    AdminAuditLog.after["currency"].astext == currency,
                ),
            )
        )
        return highest or 0

    def set_credit_rate(
        self,
        admin_id: uuid.UUID,
        *,
        currency: str,
        units_per_minor: Decimal,
        expected_version: int | None,
        reason: str,
    ) -> CreditRateView:
        """Create (``expected_version`` ``None``) or replace the rate of ``currency``."""
        require_reason(reason)
        validate_currency(currency)
        validate_rate(units_per_minor)
        row = self._locked_rate(currency)
        before: dict[str, object] | None = None
        if row is None:
            if expected_version is not None:
                raise _stale(f"The {currency} rate")
            row = CreditConversionRate(
                currency=currency,
                units_per_minor=units_per_minor,
                version=self._highest_version_seen(currency) + 1,
                updated_by=admin_id,
                updated_at=self._now(),
            )
            self._s.add(row)
        else:
            if expected_version is None:
                raise AdminConflictError(
                    "credit_rate_exists",
                    f"A {currency} rate is already set. Send its version to replace it.",
                )
            if row.version != expected_version:
                raise _stale(f"The {currency} rate")
            before = snapshot(row, _RATE_AUDIT)
            row.units_per_minor = units_per_minor
            row.version += 1
            row.updated_by = admin_id
            row.updated_at = self._now()
        self._s.flush()
        self._s.refresh(row)
        audited(
            self._s,
            admin_id,
            ACTION_CREDIT_RATE_SET,
            AuditTarget.CONVERSION_RATE,
            row.id,
            reason,
            before,
            snapshot(row, _RATE_AUDIT),
        )
        return _rate_view(row)

    def clear_credit_rate(
        self,
        admin_id: uuid.UUID,
        *,
        currency: str,
        expected_version: int,
        confirm_stop_conversions: bool,
        reason: str,
    ) -> list[CreditRateView]:
        """Delete the rate of ``currency``; the other currencies are returned.

        Without ``confirm_stop_conversions`` the call is refused (409 ``rate_clear_needs_confirm``):
        with no rate, every conversion in that currency fails closed.
        """
        require_reason(reason)
        validate_currency(currency)
        row = self._locked_rate(currency)
        if row is None:
            raise AdminNotFoundError("credit_rate_not_set", f"No {currency} rate is set.")
        if row.version != expected_version:
            raise _stale(f"The {currency} rate")
        if not confirm_stop_conversions:
            raise AdminConflictError(
                "rate_clear_needs_confirm",
                f"Clearing the {currency} rate stops credit conversions in {currency}: a payment "
                "that needs converting will fail closed and grant nothing. Send "
                "confirmStopConversions: true to clear it.",
            )
        before = snapshot(row, _RATE_AUDIT)
        row_id = row.id
        self._s.delete(row)
        self._s.flush()
        audited(
            self._s,
            admin_id,
            ACTION_CREDIT_RATE_CLEAR,
            AuditTarget.CONVERSION_RATE,
            row_id,
            reason,
            before,
            None,
        )
        return list_credit_rates(self._s)


__all__ = [
    "ACTION_CREDIT_RATE_CLEAR",
    "ACTION_CREDIT_RATE_SET",
    "ACTION_SETTINGS_UPDATE",
    "API_NAMES",
    "DECIMAL_FIELDS",
    "INT_FIELDS",
    "RATE_MAX",
    "RATE_PLACES",
    "SETTING_FIELDS",
    "BillingSettingsService",
    "BillingSettingsView",
    "CreditRateView",
    "credit_rate_for",
    "ensure_billing_settings",
    "get_billing_settings",
    "list_credit_rates",
    "validate_currency",
    "validate_rate",
    "validate_settings",
]
