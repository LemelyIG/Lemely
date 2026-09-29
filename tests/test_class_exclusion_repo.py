"""Postgres-integration tests for :class:`ClassExclusionRepository` (T12, D9).

Exercises the real SQL directly — no test elsewhere inserted a
``ClassPaperExclusion`` row before this file (``tests/test_class_scoped_history.py``
builds ``ClassScopedHistoryStore`` from literal ``frozenset`` values and never
touches this table, so a wrong column or filter in the repo's query would have
passed every existing test unnoticed).

Follows ``tests/test_at_risk_repo.py``'s fixture pattern: a throwaway Postgres
database per test, skipping cleanly when no local Postgres is reachable.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.core.history import PaperRecord
from lemely.core.schemas import ExamMetadata
from lemely.db.base import Base
from lemely.db.class_exclusion_repo import ClassExclusionRepository
from lemely.db.class_repo import ClassService
from lemely.db.history_repo import DbHistoryStore
from lemely.db.models import ClassPaperExclusion, User
from lemely.db.models.enums import Role
from lemely.runtime.config import DatabaseSettings

if TYPE_CHECKING:
    from collections.abc import Iterator


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


@pytest.fixture
def pg_sessionmaker() -> Iterator[sessionmaker[Session]]:
    """A sessionmaker bound to a throwaway Postgres DB; skips if unreachable."""
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
        yield sessionmaker(bind=engine, expire_on_commit=False, future=True)
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE)'))
        admin.dispose()


def _seed_user(sm: sessionmaker[Session], role: Role, display_name: str | None = None) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=role, display_name=display_name))
    return uid


def _seed_attempt(store: DbHistoryStore, student_id: uuid.UUID, *, recorded_at: str) -> str:
    """Persist one real ``Attempt`` row and return its id as a string.

    Goes through :class:`DbHistoryStore` (not a hand-built ``Attempt``) so this
    test tracks the real schema rather than a second, independently
    maintained construction of it.
    """
    store.append(
        str(student_id),
        PaperRecord(
            student_id=str(student_id),
            metadata=ExamMetadata(
                subject_code="0625",
                paper_number=1,
                paper_variant=1,
                session_month="May/June",
                session_year=2020,
            ),
            awarded_marks=40,
            maximum_marks=80,
            percentage=50.0,
            grade="D",
            weak_areas=[],
            recorded_at=recorded_at,
        ),
    )
    records = store.load(str(student_id)).records
    attempt_id = records[-1].attempt_id
    assert attempt_id is not None
    return attempt_id


@pytest.fixture
def class_service(pg_sessionmaker: sessionmaker[Session]) -> ClassService:
    return ClassService(pg_sessionmaker)


def test_excluded_attempt_ids_scoped_per_class(
    pg_sessionmaker: sessionmaker[Session], class_service: ClassService
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    student = _seed_user(pg_sessionmaker, Role.student)
    class_a = class_service.create_class(teacher, "Class A")
    class_b = class_service.create_class(teacher, "Class B")
    class_c = class_service.create_class(teacher, "Class C")  # never excluded from

    history = DbHistoryStore(pg_sessionmaker)
    attempt_a = _seed_attempt(history, student, recorded_at="2026-01-01T00:00:00+00:00")
    attempt_b = _seed_attempt(history, student, recorded_at="2026-02-01T00:00:00+00:00")

    with pg_sessionmaker.begin() as session:
        session.add(ClassPaperExclusion(class_id=class_a.class_id, attempt_id=uuid.UUID(attempt_a)))
        session.add(ClassPaperExclusion(class_id=class_b.class_id, attempt_id=uuid.UUID(attempt_b)))

    repo = ClassExclusionRepository(pg_sessionmaker)
    assert repo.excluded_attempt_ids(class_a.class_id) == frozenset({attempt_a})
    assert repo.excluded_attempt_ids(class_b.class_id) == frozenset({attempt_b})
    assert repo.excluded_attempt_ids(class_c.class_id) == frozenset()


def test_excluded_attempt_ids_for_a_class_with_no_exclusions_is_empty(
    pg_sessionmaker: sessionmaker[Session], class_service: ClassService
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    cls = class_service.create_class(teacher, "Untouched class")

    repo = ClassExclusionRepository(pg_sessionmaker)
    assert repo.excluded_attempt_ids(cls.class_id) == frozenset()


def test_excluded_attempt_ids_returns_strings_not_uuids(
    pg_sessionmaker: sessionmaker[Session], class_service: ClassService
) -> None:
    """``PaperRecord.attempt_id`` is a ``str``; the repo must match that type
    so ``ClassScopedHistoryStore`` never converts on every ``load`` call."""
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    student = _seed_user(pg_sessionmaker, Role.student)
    cls = class_service.create_class(teacher, "Class A")

    history = DbHistoryStore(pg_sessionmaker)
    attempt_id = _seed_attempt(history, student, recorded_at="2026-01-01T00:00:00+00:00")

    with pg_sessionmaker.begin() as session:
        session.add(ClassPaperExclusion(class_id=cls.class_id, attempt_id=uuid.UUID(attempt_id)))

    repo = ClassExclusionRepository(pg_sessionmaker)
    excluded = repo.excluded_attempt_ids(cls.class_id)
    assert excluded == {attempt_id}
    assert all(isinstance(a, str) for a in excluded)
