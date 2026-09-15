"""Tests for Task 8 (C3c)'s per-topic ``marks_lost`` stat on
:meth:`~lemely.db.practice_repo.PracticeService.topics`
(``PracticeTopicCount.marks_lost`` / ``PracticeTopicCountDTO.marksLost``).

Self-contained (mirrors ``tests/test_practice_repo.py``'s throwaway-database
fixture) — a topic's marks-lost figure must equal the caller's own net lost
marks on that topic (the same ``WeaknessRecord`` aggregate
``_weak_topics_for`` uses), reported for *every* servable topic regardless of
whether it clears the "weak" threshold. ``weak_topics`` excludes a topic with
zero net loss (module docstring, mirroring
:func:`~lemely.core.analytics.group_weak_areas`); ``marks_lost`` is a
different question — "how much has this topic cost you" — and reports 0
honestly rather than omitting the topic.
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

from lemely.db.base import Base
from lemely.db.models import User
from lemely.db.models.attempts import Attempt, WeaknessRecord
from lemely.db.models.enums import AttemptOrigin, DifficultySource, QuestionSource, Role
from lemely.db.practice_repo import PracticeService
from lemely.db.question_bank_repo import NewBankQuestion, QuestionBankService
from lemely.runtime.config import DatabaseSettings

if TYPE_CHECKING:
    from collections.abc import Iterator


# ---------------------------------------------------------------------------
# Fixtures — throwaway Postgres database, mirrors the sibling practice suite.
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


@pytest.fixture
def practice_service(pg_sessionmaker: sessionmaker[Session]) -> PracticeService:
    return PracticeService(pg_sessionmaker)


def _seed_user(sm: sessionmaker[Session], role: Role = Role.student) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=role))
    return uid


def _seed_rows(
    sm: sessionmaker[Session],
    *,
    subject_code: str = "0625",
    topics: list[str],
    per_topic: int = 2,
) -> None:
    service = QuestionBankService(sm)
    rows = []
    ref = 1
    for topic in topics:
        for _ in range(per_topic):
            rows.append(
                NewBankQuestion(
                    subject_code=subject_code,
                    source=QuestionSource.past_paper,
                    difficulty="standard",
                    difficulty_source=DifficultySource.inferred_from_marks,
                    question_type="mcq",
                    prompt=f"Question {ref}",
                    total_marks=2,
                    topic=topic,
                    source_question_id=f"0625_s23_qp_41#{ref}",
                    mcq_options=["A", "B", "C", "D"],
                    mcq_answer="B",
                )
            )
            ref += 1
    service.add_questions(rows)
    service.link_past_paper_rows()


def _seed_weakness(
    sm: sessionmaker[Session],
    student_id: uuid.UUID,
    *,
    subject_code: str = "0625",
    topic: str,
    lost_marks: int,
    maximum_marks: int,
) -> None:
    with sm.begin() as session:
        attempt = Attempt(
            user_id=student_id,
            subject_code=subject_code,
            awarded_marks=maximum_marks - lost_marks,
            maximum_marks=maximum_marks,
            percentage=100.0 * (maximum_marks - lost_marks) / maximum_marks,
            recorded_at=datetime.now(UTC),
            origin=AttemptOrigin.quiz,
        )
        session.add(attempt)
        session.flush()
        session.add(
            WeaknessRecord(
                user_id=student_id,
                attempt_id=attempt.id,
                topic=topic,
                lost_marks=lost_marks,
                maximum_marks=maximum_marks,
                accuracy=1.0 - lost_marks / maximum_marks,
            )
        )


# ---------------------------------------------------------------------------
# `marks_lost`.
# ---------------------------------------------------------------------------


def test_topics_reports_each_topics_own_net_lost_marks(
    pg_sessionmaker: sessionmaker[Session], practice_service: PracticeService
) -> None:
    student = _seed_user(pg_sessionmaker)
    _seed_rows(pg_sessionmaker, topics=["1 Motion", "2 Thermal", "3 Waves"], per_topic=3)
    _seed_weakness(pg_sessionmaker, student, topic="1 Motion", lost_marks=4, maximum_marks=10)
    _seed_weakness(pg_sessionmaker, student, topic="1 Motion", lost_marks=2, maximum_marks=10)
    _seed_weakness(pg_sessionmaker, student, topic="2 Thermal", lost_marks=0, maximum_marks=10)

    result = practice_service.topics(student, "0625")

    by_topic = {t.topic: t.marks_lost for t in result.topics}
    # Aggregated across every attempt, not just the latest one.
    assert by_topic["1 Motion"] == 6
    # A topic with a recorded attempt but zero net loss still reports 0 —
    # `marks_lost` is not the "weak" filter (`weak_topics` excludes it;
    # this stat does not).
    assert by_topic["2 Thermal"] == 0
    # A topic with no recorded attempts at all is also 0, not absent from
    # the payload — every servable topic gets a figure.
    assert by_topic["3 Waves"] == 0


def test_topics_marks_lost_is_independent_of_the_weak_topics_threshold(
    pg_sessionmaker: sessionmaker[Session], practice_service: PracticeService
) -> None:
    """``weak_topics`` excludes zero-net-loss topics; ``marks_lost`` reports the real
    figure for every topic regardless."""
    student = _seed_user(pg_sessionmaker)
    _seed_rows(pg_sessionmaker, topics=["1 Motion"], per_topic=2)
    _seed_weakness(pg_sessionmaker, student, topic="1 Motion", lost_marks=0, maximum_marks=10)

    result = practice_service.topics(student, "0625")

    assert result.weak_topics == []
    assert {t.topic: t.marks_lost for t in result.topics} == {"1 Motion": 0}
