"""Write paths behind the admin health and problem views (Phase 07, spec §8 areas 3 and 5).

* :func:`record_webhook_failure`: one row per callback refused for a bad or missing HMAC,
  capped at 60 rows per rolling minute per process. Its own transaction: the request that
  triggers it ends in a 401 with nothing else to commit. It never stores a body, an HMAC
  or an object id.
* :func:`prune_webhook_failures`: the 90-day bounded delete the sweeper runs as
  ``billing.prune_webhook_failures`` (UD-6).
* :class:`JobRunRecorder`: upserts ``job_runs`` (one row per sweeper job name) around every
  run, each call in its own short transaction.

Neither writer may change what the caller does next. The callers wrap both in
``try/except`` and log the exception type only; nothing here swallows an error itself,
so a failed write is visible to the one place that decides what to do about it.
"""

from __future__ import annotations

import threading
from collections import deque
from datetime import timedelta
from typing import TYPE_CHECKING, Final

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert

from lemely.db.billing_repo import BillingError
from lemely.db.models.billing_ops import JobRun, PaymobWebhookFailure
from lemely.runtime.errors import LemelyError

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.orm import Session, sessionmaker

#: ``job_runs.last_error`` is ``String(200)``: the whole text (type and message) is cut to it,
#: or the insert would fail and the recorder's own failure would be swallowed by its caller.
MAX_ERROR_CHARS: Final = 200
#: ``paymob_webhook_failures.remote_addr`` is ``String(64)``.
_MAX_ADDR_CHARS: Final = 64

#: Rows the failure writer accepts per rolling minute, per process (DV-6). Unauthenticated
#: requests write these rows, so a flood of bad signatures must not become a flood of inserts.
FAILURE_ROWS_PER_MINUTE: Final = 60
_FAILURE_WINDOW: Final = timedelta(minutes=1)


class FailureCap:
    """At most ``limit`` accepted events inside any rolling ``window``, process-wide.

    Driven by the caller's ``now`` so a test can walk the window without sleeping. A dropped
    event is not recorded, so a flood never extends its own window.
    """

    def __init__(
        self, *, limit: int = FAILURE_ROWS_PER_MINUTE, window: timedelta = _FAILURE_WINDOW
    ) -> None:
        self._limit = limit
        self._window = window
        self._events: deque[datetime] = deque()
        # Sync routes run on a thread pool: check-and-record must be one atomic step.
        self._lock = threading.Lock()

    def allow(self, now: datetime) -> bool:
        """Record an event at ``now`` and say whether it is inside the cap."""
        with self._lock:
            cutoff = now - self._window
            while self._events and self._events[0] <= cutoff:
                self._events.popleft()
            if len(self._events) >= self._limit:
                return False
            self._events.append(now)
            return True


_failure_cap = FailureCap()


def record_webhook_failure(
    sm: sessionmaker[Session],
    *,
    kind: str,
    reason: str,
    remote_addr: str | None,
    now: datetime,
) -> bool:
    """Store one refused callback; ``False`` (no row) when the per-minute cap dropped it.

    ``kind`` is ``transaction``, ``token`` or ``subscription`` and ``reason`` a fixed
    word (``hmac_mismatch``, ``hmac_missing``): the table's CHECK rejects another kind.
    ``remote_addr`` is best effort (``client_errors._client_ip``, spoofable off the Worker).
    The body, the received HMAC and the object id are deliberately not parameters.
    """
    if not _failure_cap.allow(now):
        return False
    with sm.begin() as session:
        session.add(
            PaymobWebhookFailure(
                kind=kind,
                reason=reason,
                remote_addr=None if remote_addr is None else remote_addr[:_MAX_ADDR_CHARS],
                received_at=now,
            )
        )
    return True


#: Refused-callback rows are kept this long (UD-6 b), then pruned by the sweeper.
WEBHOOK_FAILURE_RETENTION: Final = timedelta(days=90)
#: Rows one prune pass deletes at most; a backlog is cleared over the next passes.
PRUNE_BATCH: Final = 1000


def prune_webhook_failures(
    sm: sessionmaker[Session], *, now: datetime, batch: int = PRUNE_BATCH
) -> int:
    """Delete refused-callback rows older than 90 days, at most ``batch`` of the oldest.

    Rows are written by unauthenticated requests, so the table needs a bound. The delete
    is one short transaction; ``ix_paymob_webhook_failures_received_at`` serves the scan.
    Returns the number deleted.
    """
    cutoff = now - WEBHOOK_FAILURE_RETENTION
    oldest = (
        sa.select(PaymobWebhookFailure.id)
        .where(PaymobWebhookFailure.received_at < cutoff)
        .order_by(PaymobWebhookFailure.received_at)
        .limit(batch)
    )
    with sm.begin() as session:
        result = session.execute(
            sa.delete(PaymobWebhookFailure).where(PaymobWebhookFailure.id.in_(oldest))
        )
    return int(result.rowcount)  # type: ignore[attr-defined]


#: Exception types whose message a job's author wrote and controls, so it is safe to keep:
#: the project's own errors (``LemelyError``: ``PaymobError`` carries a method, a path and an
#: exception type) and billing's. Every other type, builtin or library, may format a message
#: from data (an address, a URL with a query string, a SQL parameter), so only its name is kept.
_SAFE_MESSAGE_TYPES: Final = (LemelyError, BillingError)


def describe_job_error(exc: BaseException) -> str:
    """The text ``job_runs.last_error`` keeps for ``exc``, at most 200 characters.

    The type name, plus ``: <message>`` only for the allowlisted types above, cut as a whole.
    Platform admins read this column, so a message that could echo bound parameters, a card
    token or an email (every database error, any exception of unknown origin) is never kept.
    """
    if isinstance(exc, _SAFE_MESSAGE_TYPES):
        return f"{type(exc).__name__}: {exc}"[:MAX_ERROR_CHARS]
    return type(exc).__name__[:MAX_ERROR_CHARS]


class JobRunRecorder:
    """Upsert ``job_runs`` around each sweeper job; every call is its own transaction."""

    def __init__(self, sm: sessionmaker[Session]) -> None:
        self._sm = sm

    def start(self, name: str, now: datetime) -> None:
        """Stamp ``last_started_at``; the previous outcome stays visible until this run ends."""
        stmt = (
            pg_insert(JobRun)
            .values(name=name, last_started_at=now)
            .on_conflict_do_update(index_elements=[JobRun.name], set_={"last_started_at": now})
        )
        with self._sm.begin() as session:
            session.execute(stmt)

    def record_finish(
        self, name: str, *, now: datetime, count: int | None, error: BaseException | None
    ) -> None:
        """Record the outcome: ``count`` for a job that returned, ``error`` for one that raised."""
        ok = error is None
        values: dict[str, object] = {
            "name": name,
            "last_started_at": now,  # used only when no start row exists (the insert branch)
            "last_finished_at": now,
            "last_outcome": "ok" if ok else "failed",
            "last_result_count": count if ok else None,
            "last_error": None if error is None else describe_job_error(error),
            "last_success_at": now if ok else None,
            "consecutive_failures": 0 if ok else 1,
            "total_runs": 1,
            "total_failures": 0 if ok else 1,
        }
        update: dict[str, object] = {
            "last_finished_at": now,
            "last_outcome": values["last_outcome"],
            "last_result_count": values["last_result_count"],
            "last_error": values["last_error"],
            "consecutive_failures": 0 if ok else JobRun.consecutive_failures + 1,
            "total_runs": JobRun.total_runs + 1,
            "total_failures": JobRun.total_failures + (0 if ok else 1),
        }
        if ok:
            update["last_success_at"] = now
        stmt = (
            pg_insert(JobRun)
            .values(**values)
            .on_conflict_do_update(index_elements=[JobRun.name], set_=update)
        )
        with self._sm.begin() as session:
            session.execute(stmt)


__all__ = [
    "FAILURE_ROWS_PER_MINUTE",
    "MAX_ERROR_CHARS",
    "PRUNE_BATCH",
    "WEBHOOK_FAILURE_RETENTION",
    "FailureCap",
    "JobRunRecorder",
    "describe_job_error",
    "prune_webhook_failures",
    "record_webhook_failure",
]
