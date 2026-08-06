"""Parity tests: the DB-backed history store matches the JSON store (D1.8).

These are Postgres integration tests — they create a throwaway database and
skip cleanly when no local server is reachable (mirrors ``test_db_schema.py``).
The core assertion is *parity*: appending the same ``PaperRecord``s to the JSON
``HistoryStore`` and to :class:`DbHistoryStore` yields an equal
``StudentHistory`` from ``load`` (modulo the deterministic normalisations
recorded in D1.8).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.core.history import PaperRecord, StudentHistory, is_grade_bearing
from lemely.core.schemas import ExamMetadata, WeakArea
from lemely.db.base import Base
from lemely.db.history_repo import DbHistoryStore, migrate_json_history
from lemely.db.models import User
from lemely.db.models.enums import Role
from lemely.io.history_store import HistoryStore
from lemely.runtime.config import DatabaseSettings

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


def _record(user_id: str, *, day: int, grade: str, topics: list[str]) -> PaperRecord:
    # weak_areas built in topic-sorted order so parity is exact including order
    # (the DB store sorts weak_areas by topic; see D1.8).
    return PaperRecord(
        student_id=user_id,
        metadata=ExamMetadata(
            subject_code="0625",
            paper_number=1,
            paper_variant=2,
            session_month="May/June",
            session_year=2020,
        ),
        awarded_marks=65,
        maximum_marks=80,
        percentage=81.25,
        grade=grade,
        weak_areas=[
            WeakArea(
                topic=t,
                lost_marks=5,
                maximum_marks=10,
                accuracy=0.5,
                question_ids=[f"{t}-3a"],
            )
            for t in sorted(topics)
        ],
        # Distinct, canonical UTC timestamps → deterministic recorded_at ordering
        # and exact ISO round-trip.
        recorded_at=datetime(2026, 1, day, tzinfo=UTC).isoformat(),
    )


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


def _seed_user(sm: sessionmaker[Session], role: Role = Role.student) -> str:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=role))
    return str(uid)


def test_append_load_parity_with_json_store(
    pg_sessionmaker: sessionmaker[Session], tmp_path: Path
) -> None:
    user_id = _seed_user(pg_sessionmaker)
    db_store = DbHistoryStore(pg_sessionmaker)
    json_store = HistoryStore(tmp_path / "history")

    records = [
        _record(user_id, day=1, grade="C", topics=["Waves", "Forces"]),
        _record(user_id, day=2, grade="B", topics=["Electricity"]),
        _record(user_id, day=3, grade="A", topics=["Optics", "Energy", "Atoms"]),
    ]
    for rec in records:
        json_store.append(user_id, rec)
        db_store.append(user_id, rec)

    db_history = db_store.load(user_id)
    json_history = json_store.load(user_id)

    assert isinstance(db_history, StudentHistory)
    assert db_history.model_dump() == json_history.model_dump()


def test_load_unknown_user_is_empty(pg_sessionmaker: sessionmaker[Session]) -> None:
    user_id = _seed_user(pg_sessionmaker)
    history = DbHistoryStore(pg_sessionmaker).load(user_id)
    assert history.records == []
    assert history.student_id == user_id


def test_records_returned_in_recorded_at_order(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    user_id = _seed_user(pg_sessionmaker)
    store = DbHistoryStore(pg_sessionmaker)
    # Append out of chronological order; load must still sort by recorded_at.
    store.append(user_id, _record(user_id, day=3, grade="A", topics=["X"]))
    store.append(user_id, _record(user_id, day=1, grade="C", topics=["Y"]))
    store.append(user_id, _record(user_id, day=2, grade="B", topics=["Z"]))
    grades = [r.grade for r in store.load(user_id).records]
    assert grades == ["C", "B", "A"]


def test_list_students_returns_users_with_attempts(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    store = DbHistoryStore(pg_sessionmaker)
    with_attempt = _seed_user(pg_sessionmaker)
    without_attempt = _seed_user(pg_sessionmaker)
    store.append(with_attempt, _record(with_attempt, day=1, grade="B", topics=["W"]))

    students = store.list_students()
    assert with_attempt in students
    assert without_attempt not in students


def test_non_uuid_student_id_rejected(pg_sessionmaker: sessionmaker[Session]) -> None:
    store = DbHistoryStore(pg_sessionmaker)
    with pytest.raises(ValueError, match="must be a UUID"):
        store.load("anonymous")
    with pytest.raises(ValueError, match="must be a UUID"):
        store.append("anonymous", _record(str(uuid.uuid4()), day=1, grade="B", topics=["W"]))


def test_migrate_json_history_moves_records(
    pg_sessionmaker: sessionmaker[Session], tmp_path: Path
) -> None:
    user_id = _seed_user(pg_sessionmaker)
    json_store = HistoryStore(tmp_path / "history")
    json_store.append(user_id, _record(user_id, day=1, grade="B", topics=["Waves"]))
    json_store.append(user_id, _record(user_id, day=2, grade="A", topics=["Forces"]))
    # A legacy non-UUID key must be reported as skipped, not abort the batch.
    json_store.append("anonymous", _record(str(uuid.uuid4()), day=1, grade="C", topics=["X"]))

    db_store = DbHistoryStore(pg_sessionmaker)
    results = migrate_json_history(json_store, db_store)

    assert results[user_id] == "migrated 2 record(s)"
    assert "skipped" in results["anonymous"]
    assert len(db_store.load(user_id).records) == 2


# ---------------------------------------------------------------------------
# P3.5 chunk G — attempts.origin round-trips (docs/quiz-model.md §5)
# ---------------------------------------------------------------------------


def test_origin_round_trips_through_the_db_store(pg_sessionmaker: sessionmaker[Session]) -> None:
    """A quiz record must not read back as a past-paper one.

    ``_to_attempt`` writes ``attempts.origin`` and ``_to_record`` reads it
    back; if either side is dropped the record silently re-enters the
    grade-bearing analytics that ``origin`` exists to keep it out of, and
    nothing else in the system would notice.
    """
    user_id = _seed_user(pg_sessionmaker)
    store = DbHistoryStore(pg_sessionmaker)

    paper = _record(user_id, day=1, grade="B", topics=["Waves"])
    quiz = _record(user_id, day=2, grade="", topics=["Forces"]).model_copy(
        update={"origin": "quiz"}
    )
    store.append(user_id, paper)
    store.append(user_id, quiz)

    loaded = store.load(user_id)
    assert [r.origin for r in loaded.records] == ["past_paper", "quiz"]
    assert [is_grade_bearing(r) for r in loaded.records] == [True, False]


def test_store_loads_every_origin_not_just_grade_bearing_ones(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """The store is not where the split happens (§5).

    Filtering at the store would silently starve the topic analytics that
    quizzes are supposed to feed. ``load`` returns everything; each consumer
    applies ``is_grade_bearing`` itself.
    """
    user_id = _seed_user(pg_sessionmaker)
    store = DbHistoryStore(pg_sessionmaker)
    for day, origin in ((1, "past_paper"), (2, "quiz"), (3, "custom_paper")):
        store.append(
            user_id,
            _record(user_id, day=day, grade="B", topics=["Waves"]).model_copy(
                update={"origin": origin}
            ),
        )

    loaded = store.load(user_id)
    assert [r.origin for r in loaded.records] == ["past_paper", "quiz", "custom_paper"]
