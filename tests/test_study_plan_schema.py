"""Schema-level tests for the study-plan tables (P4.7 chunk B, migration ``0012_study_plans``).

Pins three things a migration/model pair can silently drift on:

* ``studyplanactivitytype`` (db mirror) agrees with
  ``lemely.core.study.ActivityType`` (core original) member-for-member;
* plan -> session ``ON DELETE CASCADE`` actually deletes sessions;
* ``uq_study_plans_active`` (the partial unique index behind "weekly
  regeneration supersedes") really does allow at most one *active*
  (``superseded_at IS NULL``) plan per ``(user_id, subject_code,
  week_start)``, while a superseded row for the same week does not conflict.

Same throwaway-database fixture pattern as ``tests/test_flashcard_schema.py``:
skips cleanly when no local Postgres is reachable.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from lemely.core.study import ActivityType as CoreActivityType
from lemely.db.base import Base
from lemely.db.models import import_all_models
from lemely.db.models.enums import Role
from lemely.db.models.study_plan import StudyPlan, StudyPlanActivityType, StudyPlanSession
from lemely.db.models.users import User
from lemely.runtime.config import DatabaseSettings

if TYPE_CHECKING:
    from collections.abc import Iterator

import_all_models()

_NOW = datetime(2026, 8, 6, 12, 0, 0, tzinfo=UTC)
_WEEK_START = date(2026, 8, 3)  # Monday


# ---------------------------------------------------------------------------
# Metadata layer — no database required
# ---------------------------------------------------------------------------


def test_activity_type_enum_matches_the_core_scheduler_vocabulary() -> None:
    """The db-mirror enum and the core enum must never drift apart.

    See the "mirrors, does not import" docstrings in
    ``lemely/core/study.py`` and ``lemely/db/models/study_plan.py`` for why
    the duplication exists; this is the test that makes it safe.
    """
    assert {m.value for m in StudyPlanActivityType} == {m.value for m in CoreActivityType}
    assert [m.name for m in StudyPlanActivityType] == [m.name for m in CoreActivityType]


# ---------------------------------------------------------------------------
# Integration layer — real Postgres, skipped when unreachable
# ---------------------------------------------------------------------------


def _server_reachable(url: str) -> bool:
    server_url = make_url(url).set(database="postgres")
    engine = create_engine(server_url)
    try:
        with engine.connect():
            return True
    except OperationalError:
        return False
    finally:
        engine.dispose()


@pytest.fixture(scope="module")
def pg_engine() -> Iterator[sa.Engine]:
    base_url = DatabaseSettings().url
    if not _server_reachable(base_url):
        pytest.skip("local Postgres not reachable")

    server_url = make_url(base_url).set(database="postgres")
    admin = create_engine(server_url, isolation_level="AUTOCOMMIT")
    dbname = f"lemely_test_{uuid.uuid4().hex[:12]}"
    with admin.connect() as conn:
        conn.execute(sa.text(f'CREATE DATABASE "{dbname}"'))

    engine = create_engine(make_url(base_url).set(database=dbname))
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE)'))
        admin.dispose()


def _seed_user(session: Session) -> uuid.UUID:
    uid = uuid.uuid4()
    session.add(User(id=uid, email=f"{uid}@example.com", role=Role.student))
    session.flush()
    return uid


def _seed_plan(
    session: Session,
    user_id: uuid.UUID,
    *,
    week_start: date = _WEEK_START,
    superseded_at: datetime | None = None,
    available: bool = True,
) -> uuid.UUID:
    plan = StudyPlan(
        user_id=user_id,
        subject_code="0625",
        week_start=week_start,
        weekly_hours=10.0,
        available=available,
        reason=None if available else "no_signal",
        generated_at=_NOW,
        superseded_at=superseded_at,
    )
    session.add(plan)
    session.flush()
    return plan.id


def test_plan_cascade_deletes_its_sessions(pg_engine: sa.Engine) -> None:
    with Session(pg_engine) as session:
        user_id = _seed_user(session)
        plan_id = _seed_plan(session, user_id)
        session.add(
            StudyPlanSession(
                plan_id=plan_id,
                date=_WEEK_START,
                topic="1 Motion",
                activity_type=StudyPlanActivityType.review,
                duration_minutes=30,
                focus="Review notes: 1 Motion",
            )
        )
        session.commit()

        assert session.scalar(sa.select(sa.func.count()).select_from(StudyPlanSession)) == 1

        session.execute(sa.delete(StudyPlan).where(StudyPlan.id == plan_id))
        session.commit()

        assert session.scalar(sa.select(sa.func.count()).select_from(StudyPlanSession)) == 0


def test_activity_type_enum_round_trips(pg_engine: sa.Engine) -> None:
    with Session(pg_engine) as session:
        user_id = _seed_user(session)
        plan_id = _seed_plan(session, user_id)
        for activity_type in StudyPlanActivityType:
            row = StudyPlanSession(
                plan_id=plan_id,
                date=_WEEK_START,
                topic="1 Motion",
                activity_type=activity_type,
                duration_minutes=30,
                focus="focus",
            )
            session.add(row)
            session.flush()
            session.refresh(row)
            assert row.activity_type is activity_type
        session.commit()


def test_at_most_one_active_plan_per_student_subject_week(pg_engine: sa.Engine) -> None:
    """``uq_study_plans_active`` blocks a second *active* plan for the same week.

    Verified by its inverse in the same test: superseding the first (setting
    ``superseded_at``) makes room for a second active one without touching
    the first row at all.
    """
    with Session(pg_engine) as session:
        user_id = _seed_user(session)
        _seed_plan(session, user_id)
        session.commit()

        with pytest.raises(IntegrityError):
            _seed_plan(session, user_id)
        session.rollback()

        # Inverse: superseding the first makes room for a second active plan.
        existing = session.scalars(select_active(user_id)).one()
        existing.superseded_at = _NOW
        session.flush()
        second_id = _seed_plan(session, user_id)
        session.commit()

        active_ids = session.scalars(select_active(user_id)).all()
        assert [p.id for p in active_ids] == [second_id]


def test_a_superseded_plan_for_the_same_week_does_not_conflict(pg_engine: sa.Engine) -> None:
    """Two *superseded* rows for the identical week are not a violation.

    The partial index only constrains ``superseded_at IS NULL`` rows —
    history may accumulate freely.
    """
    with Session(pg_engine) as session:
        user_id = _seed_user(session)
        _seed_plan(session, user_id, superseded_at=_NOW)
        _seed_plan(session, user_id, superseded_at=_NOW)
        session.commit()

        count = session.scalar(
            sa.select(sa.func.count())
            .select_from(StudyPlan)
            .where(StudyPlan.user_id == user_id, StudyPlan.week_start == _WEEK_START)
        )
        assert count == 2


def select_active(user_id: uuid.UUID) -> sa.Select[tuple[StudyPlan]]:
    return sa.select(StudyPlan).where(
        StudyPlan.user_id == user_id,
        StudyPlan.week_start == _WEEK_START,
        StudyPlan.superseded_at.is_(None),
    )
