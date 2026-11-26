"""Loads the admin AI price overrides into the runtime registry (UD13-D, DV-6).

``lemely.io.llm.price_overrides`` is the one cached value in the billing code: LLM calls price
themselves in worker threads and CLI runs that hold no session, and ``lemely.io`` may not import
``lemely.db``. This module is the only writer. It runs at app start, after every admin price write
commits in that process, from the ``billing.llm_price_refresh`` sweeper job once per sweep pass,
and, in the web app, from a price read that finds the installed prices older than
:data:`PRICE_TTL_SECONDS` (:func:`install_stale_refresh`). The sweep pass refreshes only the
instance that serves it, so the read-time refresh is what lets every other instance see a change
within about a minute of its next priced call, including an instance whose startup load failed.
A call already made keeps the price it was costed at, and a settled job keeps its recorded cost
(``usage_job_model_costs``).

Safe across processes and threads:

* each load reads the table in one statement and installs the result in one step, so a reader sees
  the old snapshot or the new one;
* the load and the install happen under one lock, so a slow load that started earlier can never
  install after a newer one and bring back an older price;
* a row or setting that fails the registry's own bounds (a direct database edit can hold a zero
  price the API refuses) is skipped and logged with ``alert=True``, never installed. Its model then
  prices at the config or code value, which is dearer than free and never negative;
* a failed refresh keeps the previous snapshot and logs ``llm_price_refresh_failed``, with
  ``alert=True`` from the fifth failure in a row;
* the read-time refresh runs at most one load at a time per process, off the calling thread, and
  waits :data:`RETRY_BACKOFF_SECONDS` after a failure before it tries again, so a database outage
  never turns every priced call into a load.
"""

from __future__ import annotations

import contextlib
import threading
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

import structlog

from lemely.db.billing_settings_repo import get_billing_settings
from lemely.db.llm_price_repo import list_overrides
from lemely.io.llm import price_overrides
from lemely.io.llm.price_overrides import InvalidPriceError, Override, Snapshot

if TYPE_CHECKING:
    from collections.abc import Callable
    from decimal import Decimal

    from sqlalchemy.orm import Session, sessionmaker

log = structlog.get_logger(__name__)

#: Consecutive failures before the log line carries ``alert=True``.
ALERT_AFTER: Final = 5
#: Age, in seconds, after which a price read starts a refresh of the installed prices.
PRICE_TTL_SECONDS: Final = 60.0
#: Seconds a process waits after a failed refresh before a price read may start another.
RETRY_BACKOFF_SECONDS: Final = 30.0

_lock = threading.Lock()
_failures = 0


class StaleGuard:
    """Decides when a process's installed prices need a refresh, one refresh at a time.

    :meth:`claim` is true when the prices were never loaded, or were loaded :attr:`ttl` seconds
    ago or more, no refresh is running, and no failure in the last :attr:`backoff` seconds is
    holding refreshes off. A true claim must be followed by :meth:`run`, which releases it.
    """

    def __init__(
        self, *, ttl: float, backoff: float, clock: Callable[[], float] = time.monotonic
    ) -> None:
        """A guard with nothing loaded yet: the first claim is true."""
        self.ttl = ttl
        self.backoff = backoff
        self._clock = clock
        self._lock = threading.Lock()
        self._fresh_at: float | None = None
        self._retry_at = float("-inf")
        self._in_flight = False

    def claim(self) -> bool:
        """True when the caller should refresh now; it then owns the one refresh in flight."""
        with self._lock:
            if self._in_flight:
                return False
            now = self._clock()
            if self._fresh_at is not None and now - self._fresh_at < self.ttl:
                return False
            if now < self._retry_at:
                return False
            self._in_flight = True
            return True

    def succeeded(self) -> None:
        """Note a refresh that installed the current table."""
        with self._lock:
            self._fresh_at = self._clock()
            self._retry_at = float("-inf")

    def failed(self) -> None:
        """Note a failed refresh: no read starts another for :attr:`backoff` seconds."""
        with self._lock:
            self._retry_at = self._clock() + self.backoff

    def run(self, refresh: Callable[[], object]) -> None:
        """Run a claimed ``refresh``, note how it went and release the claim; never raises.

        ``refresh`` logs its own failure (:func:`refresh_prices` does).
        """
        try:
            refresh()
        except Exception:
            self.failed()
        else:
            self.succeeded()
        finally:
            with self._lock:
                self._in_flight = False


_guard: StaleGuard | None = None


def _start_in_background(work: Callable[[], None]) -> None:
    threading.Thread(target=work, name="llm-price-refresh", daemon=True).start()


def install_stale_refresh(
    factory: sessionmaker[Session],
    *,
    ttl: float = PRICE_TTL_SECONDS,
    backoff: float = RETRY_BACKOFF_SECONDS,
    clock: Callable[[], float] = time.monotonic,
    start: Callable[[Callable[[], None]], None] = _start_in_background,
) -> StaleGuard:
    """Make every price read in this process refresh the prices once they are ``ttl`` old.

    The read that finds them stale starts :func:`refresh_prices` with ``start`` (a background
    thread by default) and prices itself with the prices already installed; the reads after the
    load see the new ones. Every other refresh of this process (startup, an admin write, the
    sweeper job) counts as fresh too, so a process that is refreshed anyway loads no more often.
    """
    global _guard
    guard = StaleGuard(ttl=ttl, backoff=backoff, clock=clock)

    def on_read() -> None:
        if guard.claim():
            start(lambda: guard.run(lambda: refresh_prices(factory)))

    _guard = guard
    price_overrides.set_read_hook(on_read)
    return guard


def uninstall_stale_refresh() -> None:
    """Stop price reads from refreshing (app shutdown, tests)."""
    global _guard
    price_overrides.set_read_hook(None)
    _guard = None


def load_snapshot(session: Session, *, now: datetime) -> Snapshot:
    """The table and the container-hour setting as a registry snapshot, bad entries skipped."""
    overrides: dict[str, Override] = {}
    for row in list_overrides(session):
        try:
            overrides[row.model] = Override(
                model=row.model,
                input_usd_per_mtok=row.input_usd_per_mtok,
                output_usd_per_mtok=row.output_usd_per_mtok,
                cached_input_usd_per_mtok=row.cached_input_usd_per_mtok,
                cache_write_5m_usd_per_mtok=row.cache_write_5m_usd_per_mtok,
                cache_write_1h_usd_per_mtok=row.cache_write_1h_usd_per_mtok,
                tier_threshold_tokens=row.tier_threshold_tokens,
                tier2_input_usd_per_mtok=row.tier2_input_usd_per_mtok,
                tier2_output_usd_per_mtok=row.tier2_output_usd_per_mtok,
            )
        except InvalidPriceError as exc:
            log.error("llm_price_override_ignored", alert=True, model=row.model, reason=str(exc))
    hour: Decimal | None = get_billing_settings(session).code_execution_usd_per_hour
    if hour is not None:
        try:
            price_overrides.check_code_execution_hour(hour)
        except InvalidPriceError as exc:
            log.error("llm_price_code_execution_ignored", alert=True, reason=str(exc))
            hour = None
    return Snapshot(overrides=overrides, code_execution_usd_per_hour=hour, loaded_at=now)


def refresh(session: Session, *, now: datetime | None = None) -> int:
    """Load the table and install it; returns the number of overrides installed.

    Raises whatever the load raises, leaving the previous snapshot installed.
    """
    with _lock:
        snapshot = load_snapshot(session, now=now or datetime.now(UTC))
        price_overrides.install(snapshot)
    return len(snapshot.overrides)


def _record_failure(error: Exception) -> None:
    global _failures
    with _lock:
        _failures += 1
        count = _failures
    log.error(
        "llm_price_refresh_failed",
        alert=count >= ALERT_AFTER,
        consecutive_failures=count,
        error_type=type(error).__name__,
    )


def refresh_prices(factory: sessionmaker[Session]) -> int:
    """:func:`refresh` on a fresh read-only session; a failure is logged, counted and re-raised."""
    global _failures
    guard = _guard
    try:
        with factory() as session:
            count = refresh(session)
    except Exception as exc:
        _record_failure(exc)
        if guard is not None:
            guard.failed()
        raise
    with _lock:
        _failures = 0
    if guard is not None:
        guard.succeeded()
    return count


def refresh_after_commit(factory: sessionmaker[Session]) -> None:
    """:func:`refresh_prices` for a request whose write already committed: never raises."""
    # The write is committed; a failure is already logged and a later read or sweep retries.
    with contextlib.suppress(Exception):
        refresh_prices(factory)


def reset_failures() -> None:
    """Forget the failure streak (tests)."""
    global _failures
    with _lock:
        _failures = 0
