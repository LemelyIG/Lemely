"""Admin-set AI token price overrides: the one registry the cost lookups consult (UD13-D).

A price is looked up on every LLM call, in worker threads and CLI runs that hold no database
session, and ``lemely.io`` may not import ``lemely.db``. So the admin table reaches here as an
immutable :class:`Snapshot` that ``lemely.web.llm_price_refresh`` builds and swaps in whole with
:func:`install`. Nothing here mutates a snapshot, so a reader sees the old one or the new one,
never a mix. With nothing installed (the CLI, most tests) the code and config values apply.

Prices are stored and validated per million tokens, the unit vendors publish, as exact
``Decimal`` values. :meth:`Override.to_row` converts to the code's per-1k ``float`` convention
with ``Decimal`` division, so no binary rounding enters before the final ``float``.

Cost safety. An override can never make a recorded cost negative, ``NaN`` or silently zero:
every rate must be a finite ``Decimal`` greater than 0 and at most :data:`MTOK_MAX`, with at
most :data:`PLACES` decimals. A zero rate is refused because it would bill a model for nothing
without anyone noticing; the code rates are all positive, and :data:`MTOK_MAX` is twenty times
the dearest one.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime  # noqa: TC003 - the dataclass field is read at runtime
from decimal import Decimal
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Mapping

    from lemely.io.llm.pricing import PriceRow

#: The dearest legal rate, USD per million tokens (the code's dearest is $50).
MTOK_MAX: Final = Decimal(1000)
#: Most decimal places of a rate (``NUMERIC(14, 6)``).
PLACES: Final = 6
#: The largest legal ``tier_threshold_tokens``.
TIER_THRESHOLD_MAX: Final = 10_000_000
#: The container hour is a price too: above 0 and at most this, USD.
CODE_EXECUTION_HOUR_MAX: Final = Decimal(100)

_PER_1K: Final = Decimal(1000)


class InvalidPriceError(ValueError):
    """A price outside what the cost accounting can safely use; the message names the field."""


def _places(value: Decimal) -> int:
    exponent = value.normalize().as_tuple().exponent
    return -exponent if isinstance(exponent, int) and exponent < 0 else 0


def check_rate(name: str, value: object, *, high: Decimal = MTOK_MAX) -> Decimal:
    """``value`` as a legal rate, or :class:`InvalidPriceError` naming ``name``."""
    if (
        not isinstance(value, Decimal)
        or not value.is_finite()
        or value <= 0
        or value > high
        or _places(value) > PLACES
    ):
        raise InvalidPriceError(
            f"{name} must be greater than 0 and at most {high}, "
            f"with at most {PLACES} decimal places."
        )
    return value


def check_code_execution_hour(value: object) -> Decimal:
    """``value`` as a legal container-hour price in USD, or :class:`InvalidPriceError`."""
    return check_rate("codeExecutionUsdPerHour", value, high=CODE_EXECUTION_HOUR_MAX)


def _per_1k(per_mtok: Decimal) -> float:
    return float(per_mtok / _PER_1K)


@dataclass(frozen=True, slots=True)
class Override:
    """One model's admin prices, USD per million tokens. Validated when built."""

    model: str
    input_usd_per_mtok: Decimal
    output_usd_per_mtok: Decimal
    cached_input_usd_per_mtok: Decimal | None = None
    cache_write_5m_usd_per_mtok: Decimal | None = None
    cache_write_1h_usd_per_mtok: Decimal | None = None
    tier_threshold_tokens: int | None = None
    tier2_input_usd_per_mtok: Decimal | None = None
    tier2_output_usd_per_mtok: Decimal | None = None

    def __post_init__(self) -> None:
        """Refuse any price the cost accounting cannot safely use."""
        check_rate("inputUsdPerMtok", self.input_usd_per_mtok)
        check_rate("outputUsdPerMtok", self.output_usd_per_mtok)
        for name, value in (
            ("cachedInputUsdPerMtok", self.cached_input_usd_per_mtok),
            ("cacheWrite5mUsdPerMtok", self.cache_write_5m_usd_per_mtok),
            ("cacheWrite1hUsdPerMtok", self.cache_write_1h_usd_per_mtok),
        ):
            if value is not None:
                check_rate(name, value)
        trio = (
            self.tier_threshold_tokens,
            self.tier2_input_usd_per_mtok,
            self.tier2_output_usd_per_mtok,
        )
        if all(part is None for part in trio):
            return
        threshold = self.tier_threshold_tokens
        if (
            any(part is None for part in trio)
            or isinstance(threshold, bool)
            or not isinstance(threshold, int)
            or not 0 < threshold <= TIER_THRESHOLD_MAX
        ):
            raise InvalidPriceError(
                "tierThresholdTokens must be a whole number from 1 to "
                f"{TIER_THRESHOLD_MAX}, and is sent with both tier 2 prices or none of them."
            )
        check_rate("tier2InputUsdPerMtok", self.tier2_input_usd_per_mtok)
        check_rate("tier2OutputUsdPerMtok", self.tier2_output_usd_per_mtok)

    def to_row(self, code_row: PriceRow | None) -> PriceRow:
        """The per-1k row the cost lookups use.

        A cache rate left empty falls back to ``code_row``'s rate for the model, else to the
        override's own input rate (a row with no write rate bills writes at input). With no tier 2
        prices the row is flat at every input size. A tier 2 row scales each cache rate of tier 1
        by ``tier2 input / input``, the way the vendor's tiers move every rate together.
        """
        from lemely.io.llm.pricing import PriceRow  # pricing imports this module

        cached = self.cached_input_usd_per_mtok
        write_5m = self.cache_write_5m_usd_per_mtok
        write_1h = self.cache_write_1h_usd_per_mtok
        input_1k = _per_1k(self.input_usd_per_mtok)
        cached_1k = (
            _per_1k(cached)
            if cached is not None
            else (code_row.cached_input if code_row is not None else input_1k)
        )
        write_5m_1k = (
            _per_1k(write_5m)
            if write_5m is not None
            else (code_row.cache_write_5m if code_row is not None else None)
        )
        write_1h_1k = (
            _per_1k(write_1h)
            if write_1h is not None
            else (code_row.cache_write_1h if code_row is not None else None)
        )
        tier2: PriceRow | None = None
        if (
            self.tier_threshold_tokens is not None
            and self.tier2_input_usd_per_mtok is not None
            and self.tier2_output_usd_per_mtok is not None
        ):
            ratio = float(self.tier2_input_usd_per_mtok / self.input_usd_per_mtok)
            tier2 = PriceRow(
                _per_1k(self.tier2_input_usd_per_mtok),
                cached_1k * ratio,
                _per_1k(self.tier2_output_usd_per_mtok),
                None if write_5m_1k is None else write_5m_1k * ratio,
                None if write_1h_1k is None else write_1h_1k * ratio,
            )
        return PriceRow(
            input_1k,
            cached_1k,
            _per_1k(self.output_usd_per_mtok),
            write_5m_1k,
            write_1h_1k,
            self.tier_threshold_tokens if tier2 is not None else None,
            tier2,
        )


@dataclass(frozen=True, slots=True)
class Snapshot:
    """Everything the admin set, as of ``loaded_at``. Immutable: replace it, never edit it."""

    overrides: Mapping[str, Override]
    code_execution_usd_per_hour: Decimal | None
    loaded_at: datetime

    def __post_init__(self) -> None:
        """Keep a read-only copy and refuse an unusable container-hour price."""
        # A private read-only copy: a caller keeping the dict it passed cannot change a snapshot.
        object.__setattr__(self, "overrides", MappingProxyType(dict(self.overrides)))
        hour = self.code_execution_usd_per_hour
        if hour is not None:
            check_code_execution_hour(hour)


_lock = threading.Lock()
_current: Snapshot | None = None


def install(snapshot: Snapshot | None) -> None:
    """Make ``snapshot`` the registry's content in one step; ``None`` removes every override."""
    global _current
    with _lock:
        _current = snapshot


def current() -> Snapshot | None:
    """The installed snapshot, or ``None`` when none was ever installed."""
    return _current


def resolve_in(
    snapshot: Snapshot | None,
    model: str,
    code_row: PriceRow | None,
    config_row: PriceRow | None = None,
) -> PriceRow | None:
    """:func:`resolve` against one given snapshot, so a caller can price a whole call from one."""
    if snapshot is not None:
        override = snapshot.overrides.get(model)
        if override is not None:
            return override.to_row(code_row)
    if config_row is not None:
        return config_row
    return code_row


def resolve(
    model: str, code_row: PriceRow | None, *, config_row: PriceRow | None = None
) -> PriceRow | None:
    """The row for ``model``: an exact override, else the config row, else the code row.

    ``None`` only when all three are absent (an unknown model).
    """
    return resolve_in(_current, model, code_row, config_row)


def has_override(model: str) -> bool:
    """True when the installed snapshot holds an override for exactly ``model``."""
    snapshot = _current
    return snapshot is not None and model in snapshot.overrides


def code_execution_hour_in(snapshot: Snapshot | None) -> float | None:
    """The container-hour price of ``snapshot`` as a float, or ``None`` for the code value."""
    if snapshot is None or snapshot.code_execution_usd_per_hour is None:
        return None
    return float(snapshot.code_execution_usd_per_hour)


def code_execution_usd_per_hour() -> float | None:
    """The admin's container-hour price, or ``None`` for the code value."""
    return code_execution_hour_in(_current)
