"""Market USD to EGP reference rate, a display-only hint for the admin billing screens (P08-T21).

DV-2 carve-out: this module reads a public market rate so an admin can compare it with the rate
they set by hand. It never feeds a price, a credit conversion, a margin or any other money figure
(UD-13: admins set every rate). Two guards keep the value out of money: the import-linter contract
"Money paths never reach the market FX hint" (``pyproject.toml``, transitive, so a chain through
the settings router counts) and ``tests/test_fx_reference_isolation.py`` (direct, dynamic and
string forms anywhere under ``lemely/``).

Source: ``https://open.er-api.com/v6/latest/USD`` (ExchangeRate-API open access: no key, one update
a day, rate limited with a 20 minute 429 ban, attribution required, caching allowed, no
re-distribution). The UI credits the source.

Every failure (transport error, timeout, non-200, a redirect, an oversized or unreadable body, a
missing or out-of-band rate, any unexpected error) returns ``None`` and logs one warning. Nothing
raises into a request and nothing alerts. A success is cached in process for 24 hours; a failure
for 10 minutes (20 after a 429, the feed's own ban), so a dead feed is not hammered. The whole
fetch gets one 2 s wall-clock budget.
"""

from __future__ import annotations

import contextvars
import json
import logging
import threading
import time
from contextlib import AbstractContextManager, nullcontext
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
#: The live body is about 4 KB (166 rates). A body far past that is not this feed.
MAX_BODY_BYTES: Final = 64 * 1024
#: The fetch thread's name, so a stalled one can be told apart in a thread dump.
THREAD_NAME: Final = "fx-reference-fetch"
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
    #: Why there is no value, for the one warning; ``None`` on success.
    problem: str | None = None


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


def _failed(problem: str, ttl: float = FAILURE_TTL_SECONDS) -> _Fetched:
    return _Fetched(value=None, ttl=ttl, problem=problem)


def _read_capped(response: httpx.Response) -> bytes | None:
    """The body, or ``None`` once it passes ``MAX_BODY_BYTES`` (the rest is never read)."""
    body = bytearray()
    for chunk in response.iter_bytes():
        if len(body) + len(chunk) > MAX_BODY_BYTES:
            return None
        body += chunk
    return bytes(body)


def _fetch(client: httpx.Client | None) -> _Fetched:
    """One request to the source. It never raises and never logs: the caller logs ``problem``."""
    try:
        owned: AbstractContextManager[httpx.Client] = (
            httpx.Client(timeout=TIMEOUT_SECONDS) if client is None else nullcontext(client)
        )
        with (
            owned as http,
            http.stream(
                "GET", SOURCE_URL, timeout=TIMEOUT_SECONDS, follow_redirects=False
            ) as response,
        ):
            if response.status_code != 200:
                ttl = (
                    RATE_LIMITED_TTL_SECONDS if response.status_code == 429 else FAILURE_TTL_SECONDS
                )
                return _failed(f"HTTP {response.status_code}", ttl)
            body = _read_capped(response)
        if body is None:
            return _failed(f"a body over {MAX_BODY_BYTES} bytes")
        try:
            payload: object = json.loads(body)
        except ValueError:
            return _failed("an unreadable body")
        reading = _parse(payload)
    except httpx.HTTPError as exc:
        return _failed(type(exc).__name__)
    except Exception as exc:
        return _failed(f"unexpected {type(exc).__name__}")
    if reading is None:
        return _failed("no usable EGP rate")
    return _Fetched(value=reading, ttl=SUCCESS_TTL_SECONDS)


def _fetch_within_deadline(client: httpx.Client | None) -> _Fetched:
    """``_fetch`` on a daemon thread, abandoned once ``DEADLINE_SECONDS`` of wall clock pass.

    httpx timeouts apply per phase (and not at all to DNS), so they cannot cap the whole wait;
    this does. An abandoned fetch ends on its own at its per-phase timeouts.

    A result that arrives after the deadline is dropped on purpose, success or failure. The waiter
    has already logged the one warning and cached the miss, so a late failure must not log again,
    and a late success must not overwrite a cache entry that a newer request may have written. The
    next request after the short negative cache fetches afresh.
    """
    results: list[_Fetched] = []

    def work() -> None:
        results.append(_fetch(client))

    # The feed makes no priced call, but worker threads under lemely/io run in a copied context
    # (billing spec §5.7), so a contextvar the caller set is visible here and never written back.
    worker = threading.Thread(
        target=contextvars.copy_context().run, args=(work,), name=THREAD_NAME, daemon=True
    )
    try:
        worker.start()
        worker.join(DEADLINE_SECONDS)
    except RuntimeError as exc:  # no thread could be started
        return _failed(f"{type(exc).__name__} starting the fetch thread")
    if results:
        return results[0]
    if worker.is_alive():
        return _failed(f"no answer within {DEADLINE_SECONDS:.1f} s")
    return _failed("the fetch thread ended without an answer")


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
        if fetched.problem is not None:
            logger.warning("fx reference: %s from %s", fetched.problem, SOURCE_NAME)
        _entry = _Entry(value=fetched.value, expires_at=clock() + fetched.ttl)
        return fetched.value
