"""Loads the admin AI price overrides into the runtime registry (UD13-D, DV-6).

``lemely.io.llm.price_overrides`` is the one cached value in the billing code: LLM calls price
themselves in worker threads and CLI runs that hold no session, and ``lemely.io`` may not import
``lemely.db``. This module is the only writer. It runs at app start, after every admin price write
commits in that process, and from the ``billing.llm_price_refresh`` sweeper job every 60 seconds,
so another instance sees a change within a minute. A call already made keeps the price it was
costed at, and a settled job keeps its recorded cost (``usage_job_model_costs``).

Safe across processes and threads:

* each load reads the table in one statement and installs the result in one step, so a reader sees
  the old snapshot or the new one;
* the load and the install happen under one lock, so a slow load that started earlier can never
  install after a newer one and bring back an older price;
* a row or setting that fails the registry's own bounds (a direct database edit can hold a zero
  price the API refuses) is skipped and logged with ``alert=True``, never installed. Its model then
  prices at the config or code value, which is dearer than free and never negative;
* a failed refresh keeps the previous snapshot and logs ``llm_price_refresh_failed``, with
  ``alert=True`` from the fifth failure in a row.
"""

from __future__ import annotations

import contextlib
import threading
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

import structlog

from lemely.db.billing_settings_repo import get_billing_settings
from lemely.db.llm_price_repo import list_overrides
from lemely.io.llm import price_overrides
from lemely.io.llm.price_overrides import InvalidPriceError, Override, Snapshot

if TYPE_CHECKING:
    from decimal import Decimal

    from sqlalchemy.orm import Session, sessionmaker

log = structlog.get_logger(__name__)

#: Consecutive failures before the log line carries ``alert=True``.
ALERT_AFTER: Final = 5

_lock = threading.Lock()
_failures = 0


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
    try:
        with factory() as session:
            count = refresh(session)
    except Exception as exc:
        _record_failure(exc)
        raise
    with _lock:
        _failures = 0
    return count


def refresh_after_commit(factory: sessionmaker[Session]) -> None:
    """:func:`refresh_prices` for a request whose write already committed: never raises."""
    # The write is committed; a failure is already logged and the 60 s job retries.
    with contextlib.suppress(Exception):
        refresh_prices(factory)


def reset_failures() -> None:
    """Forget the failure streak (tests)."""
    global _failures
    with _lock:
        _failures = 0
