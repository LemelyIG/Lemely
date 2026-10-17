"""Shared helpers for tests that prove real lock behaviour across two connections.

Used by ``test_attempt_repo.py`` and ``test_deletion_repo.py``, whose race tests
both need to run one transaction on a thread, pause it mid-way, and confirm a
second transaction really is queued behind it before releasing the first —
otherwise the two would run sequentially and the test would pass on buggy code.
"""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.orm import Session, sessionmaker


def _wait_until_a_backend_waits_on_a_lock(sm: sessionmaker[Session]) -> None:
    """Block until some connection to this database is queued behind a lock holder.

    ``pg_blocking_pids(pid) <> '{}'`` names a backend actually blocked by
    another backend's lock, not merely one reporting ``wait_event_type =
    'Lock'`` for any reason — the narrower check the race tests need.
    """
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        with sm() as session:
            blocked = session.scalar(
                sa.text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE datname = current_database() "
                    "AND pg_blocking_pids(pid) <> '{}'"
                )
            )
        if blocked:
            return
        time.sleep(0.05)
    pytest.fail("the second transaction never queued behind the first")


class _Paused:
    """Run ``target`` on a thread, keeping what it returned or raised."""

    def __init__(self, target: Callable[[], object]) -> None:
        self.result: object = None
        self.error: BaseException | None = None

        def run() -> None:
            try:
                self.result = target()
            except BaseException as exc:  # re-raised or asserted on by the test
                self.error = exc

        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()

    def join(self) -> None:
        self._thread.join(timeout=30)
        assert not self._thread.is_alive(), "worker thread hung"


__all__ = ["_Paused", "_wait_until_a_backend_waits_on_a_lock"]
