"""``GET /api/student/subject/{code}``: the paper-history rows behind the All papers screen (S-09).

Each history row also carries what the screen filters and compares on: the
variant, the session label, a confidence summary of how sure the marker was, and
how many questions a teacher re-marked. The confidence summary and the
teacher-correction count come from ``question_results``, so they exist only for
a relational store; the JSON store has no such table and says so with ``None``.

The Postgres tests create a throwaway ``lemely_test_*`` database and skip when no
local server answers, like ``tests/test_history_repo_parity.py``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.core.history import PaperRecord
from lemely.core.schemas import ExamMetadata, confidence_tier_for
from lemely.db.base import Base
from lemely.db.history_repo import AttemptReviewSummary, DbHistoryStore
from lemely.db.models import User
from lemely.db.models.attempts import QuestionResult
from lemely.db.models.enums import (
    ConfidenceBand,
    MarkerSource,
    ReviewReason,
    ReviewStatus,
    Role,
)
from lemely.db.models.ops import ReviewQueueItem
from lemely.io.history_store import HistoryStore
from lemely.runtime.config import DatabaseSettings
from lemely.web import create_app
from lemely.web.deps import (
    AuthContext,
    get_auth_context,
    get_history_store,
    get_student_profile_service,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from lemely.io.grade_boundaries import BoundarySource


class _FakeBoundaryStore:
    def __init__(self, *_args: object, **_kwargs: object) -> None:
        pass

    def resolve(self, metadata: ExamMetadata) -> tuple[dict[str, float], BoundarySource]:
        return {"A*": 85.0, "A": 72.0, "B": 60.0, "C": 48.0}, "exact"


def _rec(
    student_id: str, *, day: int, paper: int = 2, variant: int = 1, year: int = 2024
) -> PaperRecord:
    return PaperRecord(
        student_id=student_id,
        metadata=ExamMetadata(
            subject_code="0580",
            paper_number=paper,
            paper_variant=variant,
            session_month="Oct/Nov",
            session_year=year,
        ),
        awarded_marks=50,
        maximum_marks=70,
        percentage=71.43,
        grade="B",
        weak_areas=[],
        recorded_at=datetime(2026, 1, day, tzinfo=UTC).isoformat(),
    )


def _client(store: object, student_id: str, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr("lemely.web.routers.student.GradeBoundaryStore", _FakeBoundaryStore)
    profile_service = MagicMock()
    profile_service.list_enrolments.return_value = []
    app = create_app()
    app.dependency_overrides[get_history_store] = lambda: store
    app.dependency_overrides[get_student_profile_service] = lambda: profile_service
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(
        user_id=student_id, role="student"
    )
    return TestClient(app)


# ── JSON store: structure only, no per-question evidence ──────────────────────


def test_rows_carry_variant_and_session_and_no_evidence_without_a_relational_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = HistoryStore(tmp_path / "history")
    store.append("maya", _rec("maya", day=1, paper=4, variant=3, year=2023))
    row = (
        _client(store, "maya", monkeypatch)
        .get("/api/student/subject/0580")
        .json()["paperHistory"][0]
    )

    assert row["variant"] == 3
    assert row["session"] == "Oct/Nov 2023"
    assert row["confidence"] is None
    assert row["teacherCorrected"] == 0


# ── Postgres store ────────────────────────────────────────────────────────────


def _server_reachable(url: str) -> bool:
    engine = create_engine(make_url(url).set(database="postgres"))
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
    admin = create_engine(make_url(base_url).set(database="postgres"), isolation_level="AUTOCOMMIT")
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


def _seed_user(sm: sessionmaker[Session]) -> str:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=Role.student))
    return str(uid)


def _question(
    attempt_id: str,
    qid: str,
    *,
    score: float,
    source: MarkerSource = MarkerSource.ai,
    teacher: int | None = None,
    reason: str | None = None,
    needs_review: bool = False,
) -> QuestionResult:
    return QuestionResult(
        attempt_id=uuid.UUID(attempt_id),
        question_id=qid,
        awarded_marks=2,
        maximum_marks=4,
        confidence_band=ConfidenceBand.high if score >= 0.9 else ConfidenceBand.low,
        confidence_score=score,
        marker_source=source,
        teacher_awarded_marks=teacher,
        review_reason=reason,
        needs_teacher_review=needs_review,
    )


def _add_queued(
    sm: sessionmaker[Session], attempt_id: str, question: QuestionResult, queue: ReviewStatus
) -> None:
    """Add a question and the review-queue row the marker opened for it, in ``queue``'s state.

    Marking opens a ``low_confidence`` row for every question it doubts; a self-mark, a
    teacher's accept or a dismissal later closes that row. Those close it without writing
    ``teacher_awarded_marks``.
    """
    with sm.begin() as session:
        session.add(question)
        session.flush()
        session.add(
            ReviewQueueItem(
                attempt_id=uuid.UUID(attempt_id),
                question_result_id=question.id,
                reason=ReviewReason.low_confidence,
                status=queue,
            )
        )


def _append(sm: sessionmaker[Session], store: DbHistoryStore, uid: str, day: int) -> str:
    store.append(uid, _rec(uid, day=day))
    return store.load(uid).records[-1].attempt_id or ""


def _add_questions(sm: sessionmaker[Session], rows: list[QuestionResult]) -> None:
    with sm.begin() as session:
        session.add_all(rows)


def _summary(
    sm: sessionmaker[Session], *questions: tuple[QuestionResult, ReviewStatus | None]
) -> AttemptReviewSummary:
    uid = _seed_user(sm)
    store = DbHistoryStore(sm)
    attempt = _append(sm, store, uid, 1)
    for question, queue in questions:
        question.attempt_id = uuid.UUID(attempt)
        if queue is None:
            _add_questions(sm, [question])
        else:
            _add_queued(sm, attempt, question, queue)
    return store.review_summaries(uid, [attempt])[attempt]


def _q(qid: str, **kw: object) -> QuestionResult:
    return _question(str(uuid.uuid4()), qid, **kw)  # type: ignore[arg-type]


def test_a_plain_low_score_question_still_waiting_for_a_teacher_is_unsure(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    summary = _summary(
        pg_sessionmaker,
        (_q("1a", score=0.97), None),
        (_q("2a", score=0.55), ReviewStatus.open),
    )

    assert summary == AttemptReviewSummary(scored=2, uncertain=1, needs_review=0, corrected=0)


def test_a_self_marked_question_is_sure_like_the_result_screen(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    # The self-mark closed the queue row; it wrote no teacher mark.
    summary = _summary(pg_sessionmaker, (_q("2a", score=0.55), ReviewStatus.resolved))

    assert summary == AttemptReviewSummary(scored=1, uncertain=0, needs_review=0, corrected=0)


def test_a_teacher_accepting_the_mark_settles_it(pg_sessionmaker: sessionmaker[Session]) -> None:
    summary = _summary(
        pg_sessionmaker,
        (_q("2a", score=0.4, reason="Answer off-scheme", needs_review=True), ReviewStatus.resolved),
    )

    assert summary == AttemptReviewSummary(scored=1, uncertain=0, needs_review=0, corrected=0)


def test_a_teacher_dismissing_the_flag_settles_it(pg_sessionmaker: sessionmaker[Session]) -> None:
    summary = _summary(pg_sessionmaker, (_q("2a", score=0.5), ReviewStatus.dismissed))

    assert summary == AttemptReviewSummary(scored=1, uncertain=0, needs_review=0, corrected=0)


def test_a_flagged_question_is_needs_review_whatever_its_score(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    # A fidelity-gate flag on a 0.97 question: the old score-only rule read this as "all sure".
    summary = _summary(
        pg_sessionmaker,
        (_q("1a", score=0.97), None),
        (_q("2a", score=0.97, reason="Handwriting unclear", needs_review=True), ReviewStatus.open),
    )

    assert summary == AttemptReviewSummary(scored=2, uncertain=0, needs_review=1, corrected=0)


def test_a_teacher_re_marked_question_is_sure_and_counted_as_corrected(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    summary = _summary(
        pg_sessionmaker,
        (_q("2b", score=0.4, teacher=3), ReviewStatus.resolved),
        (_q("3", score=0.0, source=MarkerSource.blank), None),  # never marked: not counted
    )

    assert summary == AttemptReviewSummary(scored=1, uncertain=0, needs_review=0, corrected=1)


@pytest.mark.parametrize(
    ("kwargs", "tier"),
    [
        # The cases of `confidenceTierFor` in web/tests/unit/markingConfidence.test.ts.
        ({"confidence_score": 0.87}, "uncertain"),
        ({"confidence_score": 0.9}, "confident"),
        ({"confidence_score": 0.899}, "uncertain"),
        ({"confidence_score": 1.0, "review_reason": "Handwriting unclear"}, "needs-review"),
        ({"confidence_score": 0.2, "review_reason": "Answer off-scheme"}, "needs-review"),
        (
            {"confidence_score": 0.0, "needs_teacher_review": False, "marker_source": "dropped"},
            "not-marked",
        ),
        (
            {"confidence_score": 0.0, "needs_teacher_review": False, "marker_source": "blank"},
            "not-marked",
        ),
        ({"confidence_score": 0.0, "needs_teacher_review": False}, "uncertain"),
        (
            {"review_reason": "Two answers given", "needs_teacher_review": True},
            "needs-review",
        ),
        ({"review_reason": "low confidence", "pending_teacher": False}, "confident"),
        ({"review_reason": "low confidence", "pending_teacher": True}, "needs-review"),
        ({"review_reason": "low confidence"}, "needs-review"),
        ({"confidence_score": 0.3, "pending_teacher": False}, "confident"),
        ({}, "confident"),
        ({"confidence_score": float("nan")}, "confident"),
        (
            {
                "confidence_score": 0.0,
                "needs_teacher_review": False,
                "marker_source": "blank",
                "pending_teacher": False,
            },
            "not-marked",
        ),
    ],
)
def test_confidence_tier_for_matches_the_result_screens_cases(
    kwargs: dict[str, object], tier: str
) -> None:
    base: dict[str, object] = {
        "marker_source": "ai",
        "confidence_score": None,
        "review_reason": None,
        "needs_teacher_review": None,
        "pending_teacher": None,
    }
    assert confidence_tier_for(**{**base, **kwargs}) == tier  # type: ignore[arg-type]


def test_review_summaries_omit_an_attempt_with_no_question_rows(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    uid = _seed_user(pg_sessionmaker)
    store = DbHistoryStore(pg_sessionmaker)
    attempt = _append(pg_sessionmaker, store, uid, 1)

    assert store.review_summaries(uid, [attempt]) == {}
    assert store.review_summaries(uid, []) == {}


def test_review_summaries_never_return_another_students_attempt(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    mine = _seed_user(pg_sessionmaker)
    theirs = _seed_user(pg_sessionmaker)
    store = DbHistoryStore(pg_sessionmaker)
    their_attempt = _append(pg_sessionmaker, store, theirs, 1)
    _add_questions(pg_sessionmaker, [_question(their_attempt, "1a", score=0.3, teacher=2)])

    assert store.review_summaries(mine, [their_attempt]) == {}
    assert store.review_summaries(theirs, [their_attempt])[their_attempt].corrected == 1


def test_subject_rows_show_evidence_and_never_another_students_attempts(
    pg_sessionmaker: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    mine = _seed_user(pg_sessionmaker)
    theirs = _seed_user(pg_sessionmaker)
    store = DbHistoryStore(pg_sessionmaker)
    my_attempt = _append(pg_sessionmaker, store, mine, 1)
    their_attempt = _append(pg_sessionmaker, store, theirs, 2)
    _add_questions(
        pg_sessionmaker,
        [
            _question(my_attempt, "1a", score=0.95),
            _question(their_attempt, "1a", score=0.2, teacher=4),
        ],
    )
    _add_queued(
        pg_sessionmaker, my_attempt, _question(my_attempt, "1b", score=0.5), ReviewStatus.open
    )
    _add_queued(
        pg_sessionmaker,
        my_attempt,
        _question(my_attempt, "1c", score=0.5, teacher=1),
        ReviewStatus.resolved,
    )

    body = _client(store, mine, monkeypatch).get("/api/student/subject/0580").json()

    assert len(body["paperHistory"]) == 1
    row = body["paperHistory"][0]
    assert row["confidence"] == {"scored": 3, "uncertain": 1, "needsReview": 0}
    assert row["teacherCorrected"] == 1
    assert their_attempt not in str(body)
