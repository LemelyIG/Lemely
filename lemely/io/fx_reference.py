"""Market USD to EGP reference rate, a display-only hint for the admin billing screens (P08-T21).

DV-2 carve-out: this module reads a public market rate so an admin can compare it with the rate
they set by hand. It never feeds a price, a credit conversion, a margin or any other money figure
(UD-13: admins set every rate). ``tests/test_fx_reference_isolation.py`` fails if a billing
calculation path imports it, so the value cannot leak into money.

Source: ``https://open.er-api.com/v6/latest/USD`` (ExchangeRate-API open access: no key, one update
a day, rate limited with a 20 minute 429 ban, attribution required, caching allowed, no
re-distribution). The UI credits the source.

Every failure (transport error, timeout, non-200, bad JSON, missing or out-of-band rate) returns
``None`` and logs one warning. Nothing raises into a request and nothing alerts. A success is cached
in process for 24 hours; a failure for 10 minutes (20 after a 429, the feed's own ban), so a dead
feed is not hammered. The whole fetch gets one 2 s wall-clock budget.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Final

import httpx

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

SOURCE_URL: Final = "https://open.er-api.com/v6/latest/USD"
#: What the UI shows as the source name.
SOURCE_NAME: Final = "open.er-api.com"
TIMEOUT_SECONDS: Final = 2.0
SUCCESS_TTL_SECONDS: Final = 24 * 60 * 60
FAILURE_TTL_SECONDS: Final = 10 * 60
#: The source bans a rate-limited caller for 20 minutes after a 429; do not call into the ban.
RATE_LIMITED_TTL_SECONDS: Final = 20 * 60
#: One wall-clock budget for the whole fetch (connect, read, parsing), not per phase.
DEADLINE_SECONDS: Final = 2.0
#: A rate outside this band is a feed fault, not a market (EGP has traded between about 5 and 60).
MIN_RATE: Final = Decimal(1)
MAX_RATE: Final = Decimal(1000)


@dataclass(frozen=True, slots=True)
class FxReference:
    """One market reading: 1 USD buys ``rate`` EGP, as of the source's last update date."""

    rate: Decimal
    source: str
    as_of: date


@dataclass(frozen=True, slots=True)
class _Fetched:
    value: FxReference | None
    ttl: float


@dataclass(slots=True)
class _Entry:
    value: FxReference | None
    expires_at: float


_lock = threading.Lock()
_entry: _Entry | None = None


def clear_cache() -> None:
    """Forget the cached reading (tests)."""
    global _entry
    with _lock:
        _entry = None


def _parse(payload: object) -> FxReference | None:
    """The reading in a decoded body, or ``None`` when any part of it is unusable."""
    if not isinstance(payload, dict):
        return None
    if payload.get("result") != "success":
        return None
    rates = payload.get("rates")
    raw_rate = rates.get("EGP") if isinstance(rates, dict) else None
    stamp = payload.get("time_last_update_unix")
    if not isinstance(raw_rate, int | float | str):
        return None
    if isinstance(stamp, bool) or not isinstance(stamp, int):
        return None
    try:
        rate = Decimal(str(raw_rate))
        as_of = datetime.fromtimestamp(stamp, tz=UTC).date()
    except (InvalidOperation, ValueError, OverflowError, OSError):
        return None
    if not rate.is_finite() or not MIN_RATE <= rate <= MAX_RATE:
        return None
    return FxReference(rate=rate, source=SOURCE_NAME, as_of=as_of)


def _fetch(client: httpx.Client | None) -> _Fetched:
    """One request to the source; no reading plus one warning on any failure."""
    owned = client is None
    http = client or httpx.Client(timeout=TIMEOUT_SECONDS)
    try:
        response = http.get(SOURCE_URL, timeout=TIMEOUT_SECONDS)
        if response.status_code != 200:
            logger.warning("fx reference: HTTP %s from %s", response.status_code, SOURCE_NAME)
            limited = response.status_code == 429
            return _Fetched(None, RATE_LIMITED_TTL_SECONDS if limited else FAILURE_TTL_SECONDS)
        reading = _parse(response.json())
    except httpx.HTTPError as exc:
        logger.warning("fx reference: %s from %s", type(exc).__name__, SOURCE_NAME)
        return _Fetched(None, FAILURE_TTL_SECONDS)
    except ValueError:
        logger.warning("fx reference: unreadable body from %s", SOURCE_NAME)
        return _Fetched(None, FAILURE_TTL_SECONDS)
    finally:
        if owned:
            http.close()
    if reading is None:
        logger.warning("fx reference: no usable EGP rate from %s", SOURCE_NAME)
        return _Fetched(None, FAILURE_TTL_SECONDS)
    return _Fetched(reading, SUCCESS_TTL_SECONDS)


def _fetch_within_deadline(client: httpx.Client | None) -> _Fetched:
    """``_fetch`` on a daemon thread, abandoned once ``DEADLINE_SECONDS`` of wall clock pass.

    httpx timeouts apply per phase, so a slow feed could hold a request for several of them; this
    caps the whole wait. An abandoned fetch ends on its own at its per-phase timeouts.
    """
    box: list[_Fetched] = []
    worker = threading.Thread(target=lambda: box.append(_fetch(client)), daemon=True)
    worker.start()
    worker.join(DEADLINE_SECONDS)
    if box:
        return box[0]
    logger.warning("fx reference: no answer from %s within %.1f s", SOURCE_NAME, DEADLINE_SECONDS)
    return _Fetched(None, FAILURE_TTL_SECONDS)


def get_usd_egp_reference(
    *,
    client: httpx.Client | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> FxReference | None:
    """The cached market USD to EGP reading, fetched when the cache has run out.

    ``None`` means no usable reading (a failure inside the last 10 minutes, 20 after a 429, or
    just now). It never raises. The lock is held across the fetch so concurrent requests share
    one call.
    """
    global _entry
    with _lock:
        now = clock()
        if _entry is not None and now < _entry.expires_at:
            return _entry.value
        fetched = _fetch_within_deadline(client)
        _entry = _Entry(value=fetched.value, expires_at=clock() + fetched.ttl)
        return fetched.value
