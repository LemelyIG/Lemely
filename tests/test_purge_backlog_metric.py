"""Purge-backlog visibility on the platform-admin pipeline-health metric (Task 11).

A purge that keeps failing (Task 10's sweeper) is otherwise invisible: the rows
it should have removed are already hidden from every tenant-facing reader by
the soft-delete loader criterion, so nothing downstream would ever notice the
sweep has stalled. ``PlatformAdminService.pipeline_health().purge_backlog``
counts attempts more than a day past their purge cutoff and still present,
giving an administrator the one aggregate number that catches it.

``now`` is fixed and injected (matching :meth:`PlatformAdminService.counts`'s
own convention) so the boundary between "purge is keeping up" and "purge is
overdue" is exercised precisely, rather than racing the wall clock.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import sqlalchemy as sa

from lemely.core.deletion import purge_cutoff
from lemely.db.admin_repo import PlatformAdminService
from lemely.db.models import Attempt, Upload, User
from lemely.db.models.enums import Role

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker

_NOW = datetime(2026, 1, 15, tzinfo=UTC)


@dataclass(frozen=True)
class _Seeded:
    attempt_id: uuid.UUID


def _seed_deleted_attempt(sm: sessionmaker[Session], *, deleted_at: datetime) -> _Seeded:
    """A student, one upload, and one attempt, soft-deleted at ``deleted_at``.

    The ``UPDATE`` that stamps ``deleted_at`` is a Core statement, not a
    session add/flush, so it is unaffected by the soft-delete loader criterion
    that governs ORM ``SELECT``s.
    """
    uid = uuid.uuid4()
    upload_id = uuid.uuid4()
    attempt_id = uuid.uuid4()
    with sm.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=Role.student))
        session.flush()
        session.add(Upload(id=upload_id, user_id=uid, storage_path=f"uploads/{upload_id}.pdf"))
        session.flush()
        session.add(
            Attempt(
                id=attempt_id,
                user_id=uid,
                upload_id=upload_id,
                subject_code="0625",
                awarded_marks=30,
                maximum_marks=40,
                percentage=75.0,
                recorded_at=_NOW,
            )
        )
    with sm.begin() as session:
        result = session.execute(
            sa.update(Attempt).where(Attempt.id == attempt_id).values(deleted_at=deleted_at)
        )
        assert result.rowcount == 1  # type: ignore[attr-defined]
    return _Seeded(attempt_id=attempt_id)


def test_backlog_counts_a_row_that_should_have_been_purged(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    """Deleted well past the one-day grace on top of the purge cutoff: overdue."""
    _seed_deleted_attempt(
        migrated_sessionmaker,
        deleted_at=purge_cutoff(_NOW) - timedelta(days=1, minutes=1),
    )
    service = PlatformAdminService(migrated_sessionmaker)

    health = service.pipeline_health(
        exact_boundary_keys=0, subject_default_boundary_keys=0, now=_NOW
    )

    assert health.purge_backlog == 1


def test_backlog_is_zero_when_purge_is_keeping_up(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    """Deleted right at the purge cutoff — purgeable, but not yet overdue by a
    full day, so a sweeper that simply hasn't run in the last instant is not
    reported as backlogged.
    """
    _seed_deleted_attempt(migrated_sessionmaker, deleted_at=purge_cutoff(_NOW))
    service = PlatformAdminService(migrated_sessionmaker)

    health = service.pipeline_health(
        exact_boundary_keys=0, subject_default_boundary_keys=0, now=_NOW
    )

    assert health.purge_backlog == 0
