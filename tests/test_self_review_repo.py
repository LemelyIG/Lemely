"""``SelfReviewService`` (self-review spec, 2026-09-17) against real Postgres.

Same throwaway-database fixture as ``tests/test_review_repo.py``. The scheme
is two point-based questions: "1" (2 marks, p1/p2) and "2" (3 marks,
p1/p2/p3); each test chooses the confidence of each question.
"""

from __future__ import annotations

import dataclasses
import json
import threading
import time
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.core.analytics import summarize_weaknesses
from lemely.core.loose_schemas import (
    AnswerPoint,
    MarkScheme,
    MarkSchemeMetadata,
    PaperType,
    SchemeFormat,
)
from lemely.core.loose_schemas import Question as SchemeQuestion
from lemely.core.loose_schemas import QuestionType as SchemeQuestionType
from lemely.core.loose_schemas import SessionMonth as LooseSessionMonth
from lemely.core.schemas import (
    AccuracyReport,
    ConfidenceBand,
    CorrectedQuestion,
    CorrectionResult,
    ExamMetadata,
    GradePrediction,
)
from lemely.core.self_review import JudgeRequest, JudgeVerdict
from lemely.db.attempt_repo import AttemptRepository
from lemely.db.base import Base
from lemely.db.models import User
from lemely.db.models.attempts import Attempt, QuestionResult
from lemely.db.models.enums import ReviewReason, ReviewStatus, RevisionSource, Role
from lemely.db.models.ops import ReviewQueueItem
from lemely.db.self_review_repo import (
    MAX_EVIDENCE_CHARS,
    MAX_JUDGE_REASON_CHARS,
    SELFMARK_RESOLUTION_NOTE,
    PendingPoint,
    PendingSelfReview,
    PointVerdict,
    RevealedSelfReview,
    SelfReviewAlreadySubmittedError,
    SelfReviewNotFoundError,
    SelfReviewService,
    SelfReviewValidationError,
)
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


def _seed_user(sm: sessionmaker[Session], role: Role = Role.student) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=role))
    return uid


# ── Fixtures: a two-question point-based scheme and a report against it ───────


def _scheme() -> MarkScheme:
    return MarkScheme(
        metadata=MarkSchemeMetadata(
            subject="Physics",
            subject_code="0625",
            paper_number=1,
            paper_variant=1,
            session_month=LooseSessionMonth.MAY_JUNE,
            session_year=2020,
            paper_type=PaperType.THEORY_CORE,
            maximum_mark=5,
            scheme_format=SchemeFormat.POINT_BASED,
        ),
        questions=[
            SchemeQuestion(
                id="1",
                marks=2,
                type=SchemeQuestionType.RECALL,
                answer_points=[
                    AnswerPoint(id="p1", point="States the law", marks=1),
                    AnswerPoint(id="p2", point="Gives the unit", marks=1),
                ],
            ),
            SchemeQuestion(
                id="2",
                marks=3,
                type=SchemeQuestionType.RECALL,
                answer_points=[
                    AnswerPoint(id="p1", point="Correct method", marks=1),
                    AnswerPoint(id="p2", point="Correct substitution", marks=1),
                    AnswerPoint(id="p3", point="Answer awarded to 2 sf", marks=1),
                ],
            ),
        ],
    )


def _question(
    question_id: str,
    *,
    matched: list[str],
    maximum: int,
    confidence_score: float = 0.95,
    needs_review: bool = False,
    plagiarism_flagged: bool = False,
    ai_detection_flagged: bool = False,
) -> CorrectedQuestion:
    return CorrectedQuestion(
        question_id=question_id,
        awarded_marks=len(matched),
        maximum_marks=maximum,
        confidence=ConfidenceBand.LOW if needs_review else ConfidenceBand.HIGH,
        confidence_score=confidence_score,
        needs_teacher_review=needs_review,
        student_answer=f"answer-{question_id}",
        expected_answer=f"expected-{question_id}",
        topic="Waves",
        marker_source="ai",
        feedback="Method not shown.",
        plagiarism_flagged=plagiarism_flagged,
        ai_detection_flagged=ai_detection_flagged,
        matched_point_ids=matched,
    )


def _low(question_id: str = "2", *, matched: list[str] | None = None) -> CorrectedQuestion:
    """Question "2" (3 marks) at confidence 0.2 — low-confidence."""
    return _question(
        question_id, matched=matched or [], maximum=3, confidence_score=0.2, needs_review=True
    )


def _high(question_id: str = "1", *, matched: list[str] | None = None) -> CorrectedQuestion:
    """Question "1" (2 marks) at confidence 0.95 — high-confidence."""
    return _question(question_id, matched=matched if matched is not None else ["p1"], maximum=2)


def _report(questions: list[CorrectedQuestion]) -> AccuracyReport:
    # subject_code "9999" matches no bundled boundary data, so grades resolve
    # against DEFAULT_GRADE_BOUNDARIES deterministically (as test_review_repo).
    correction = CorrectionResult(
        metadata=ExamMetadata(
            subject_code="9999",
            paper_number=1,
            paper_variant=1,
            session_month="May/June",
            session_year=2020,
        ),
        questions=questions,
    )
    awarded, maximum = correction.awarded_marks, correction.maximum_marks
    pct = round((awarded / maximum) * 100.0, 2) if maximum else 0.0
    return AccuracyReport(
        correction=correction,
        weaknesses=summarize_weaknesses(correction),
        grade_prediction=GradePrediction(
            awarded_marks=awarded,
            maximum_marks=maximum,
            percentage=pct,
            grade="U",
            confidence=ConfidenceBand.LOW,
            needs_teacher_review=correction.needs_teacher_review,
            boundary_source="global_default",
        ),
    )


def _seed_attempt(
    sm: sessionmaker[Session],
    student: uuid.UUID,
    questions: list[CorrectedQuestion],
    *,
    with_scheme: bool = True,
) -> uuid.UUID:
    return AttemptRepository(sm).persist_correction(
        user_id=str(student),
        report=_report(questions),
        mark_scheme=_scheme() if with_scheme else None,
    )


def _qr_id(sm: sessionmaker[Session], attempt_id: uuid.UUID, question_id: str) -> uuid.UUID:
    with sm() as session:
        return session.scalars(
            select(QuestionResult.id).where(
                QuestionResult.attempt_id == attempt_id, QuestionResult.question_id == question_id
            )
        ).one()


def _load_qr(sm: sessionmaker[Session], qr_id: uuid.UUID) -> QuestionResult:
    with sm() as session:
        qr = session.get(QuestionResult, qr_id)
        assert qr is not None
        _ = qr.points, qr.revisions  # load before the session closes
        return qr


def _queue_rows(sm: sessionmaker[Session], qr_id: uuid.UUID) -> list[ReviewQueueItem]:
    with sm() as session:
        return list(
            session.scalars(
                select(ReviewQueueItem).where(ReviewQueueItem.question_result_id == qr_id)
            ).all()
        )


def _service(sm: sessionmaker[Session], judge: object | None = None) -> SelfReviewService:
    return SelfReviewService(sm, judge=judge)  # type: ignore[arg-type]


def _all_earned(point_ids: list[str], evidence: str | None = None) -> list[PointVerdict]:
    return [PointVerdict(mark_point_id=pid, earned=True, evidence=evidence) for pid in point_ids]


# ── get ────────────────────────────────────────────────────────────────────


def test_get_before_submission_is_pending_and_carries_no_verdict(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student = _seed_user(pg_sessionmaker)
    attempt_id = _seed_attempt(pg_sessionmaker, student, [_high(), _low()])
    qr_id = _qr_id(pg_sessionmaker, attempt_id, "2")

    view = _service(pg_sessionmaker).get(student, attempt_id, qr_id)

    assert isinstance(view, PendingSelfReview)
    assert view.state == "not_started"
    assert view.question_id == "2"
    assert view.maximum_marks == 3
    assert view.evidence_required is False  # low-confidence: the student wins
    assert [p.mark_point_id for p in view.points] == ["p1", "p2", "p3"]
    assert [p.tariff for p in view.points] == [1, 1, 1]
    assert view.points[0].point_text == "Correct method"
    # is_alternative/is_optional are scheme-derived (not verdict-bearing) and
    # must reach the pending view so the UI can render OR-groups.
    assert [p.is_alternative for p in view.points] == [False, False, False]
    assert [p.is_optional for p in view.points] == [False, False, False]
    # The reveal is server-enforced: the pending point type has no such field.
    # Exact field-set equality (not a denylist) so any new field forces a
    # deliberate decision about whether it leaks the marker's verdict.
    assert {f.name for f in dataclasses.fields(PendingPoint)} == {
        "mark_point_id",
        "ordinal",
        "mark_type",
        "tariff",
        "point_text",
        "is_alternative",
        "is_optional",
    }
    assert {f.name for f in dataclasses.fields(PendingSelfReview)} == {
        "state",
        "attempt_id",
        "question_result_id",
        "question_id",
        "maximum_marks",
        "evidence_required",
        "points",
    }


def test_get_reports_evidence_required_on_a_high_confidence_question(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student = _seed_user(pg_sessionmaker)
    attempt_id = _seed_attempt(pg_sessionmaker, student, [_high(), _low()])
    view = _service(pg_sessionmaker).get(
        student, attempt_id, _qr_id(pg_sessionmaker, attempt_id, "1")
    )
    assert view.evidence_required is True


def test_get_treats_an_integrity_only_flag_as_high_confidence(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """Integrity flags grant no authority — and nothing in the view says why."""
    student = _seed_user(pg_sessionmaker)
    flagged = _question("1", matched=["p1"], maximum=2, needs_review=True, plagiarism_flagged=True)
    attempt_id = _seed_attempt(pg_sessionmaker, student, [flagged, _low()])
    view = _service(pg_sessionmaker).get(
        student, attempt_id, _qr_id(pg_sessionmaker, attempt_id, "1")
    )
    assert view.evidence_required is True
    assert not any("plagiar" in f.name or "integrity" in f.name for f in dataclasses.fields(view))


def test_get_unknown_attempt_is_not_found(pg_sessionmaker: sessionmaker[Session]) -> None:
    student = _seed_user(pg_sessionmaker)
    with pytest.raises(SelfReviewNotFoundError):
        _service(pg_sessionmaker).get(student, uuid.uuid4(), uuid.uuid4())


def test_get_malformed_ids_are_not_found_not_a_500(pg_sessionmaker: sessionmaker[Session]) -> None:
    student = _seed_user(pg_sessionmaker)
    with pytest.raises(SelfReviewNotFoundError):
        _service(pg_sessionmaker).get(student, "not-a-uuid", "also-not")


def test_get_another_students_attempt_is_not_found(pg_sessionmaker: sessionmaker[Session]) -> None:
    owner = _seed_user(pg_sessionmaker)
    other = _seed_user(pg_sessionmaker)
    attempt_id = _seed_attempt(pg_sessionmaker, owner, [_high(), _low()])
    qr_id = _qr_id(pg_sessionmaker, attempt_id, "2")
    with pytest.raises(SelfReviewNotFoundError):
        _service(pg_sessionmaker).get(other, attempt_id, qr_id)


def test_get_question_from_a_different_attempt_is_not_found(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """A question id that exists, on an attempt the caller owns, but not on
    the attempt named in the path — must not resolve by question id alone."""
    student = _seed_user(pg_sessionmaker)
    first = _seed_attempt(pg_sessionmaker, student, [_high(), _low()])
    second = _seed_attempt(pg_sessionmaker, student, [_high(), _low()])
    qr_on_second = _qr_id(pg_sessionmaker, second, "2")
    with pytest.raises(SelfReviewNotFoundError):
        _service(pg_sessionmaker).get(student, first, qr_on_second)


def test_get_without_point_rows_is_not_found(pg_sessionmaker: sessionmaker[Session]) -> None:
    """A quiz, or a paper corrected before spec 1 shipped: the surface is
    absent, derived from the absence of rows, not from a flag."""
    student = _seed_user(pg_sessionmaker)
    attempt_id = _seed_attempt(pg_sessionmaker, student, [_high(), _low()], with_scheme=False)
    with pytest.raises(SelfReviewNotFoundError):
        _service(pg_sessionmaker).get(student, attempt_id, _qr_id(pg_sessionmaker, attempt_id, "2"))


def test_get_before_self_mark_is_pending_even_when_teacher_already_overrode(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """``_to_view`` branches on ``qr.is_self_marked`` alone. A teacher override
    sets ``teacher_awarded_marks`` (``is_overridden``) but never touches
    ``student_selfmarked_at`` — so a question the teacher has already
    corrected, but the student has not yet self-marked, must still come back
    as the pending view. Pinning this so a later widening of the gate to
    consult ``is_overridden`` is caught here, not in production."""
    student = _seed_user(pg_sessionmaker)
    attempt_id = _seed_attempt(pg_sessionmaker, student, [_high(), _low()])
    qr_id = _qr_id(pg_sessionmaker, attempt_id, "2")
    with pg_sessionmaker() as session:
        qr = session.get(QuestionResult, qr_id)
        assert qr is not None
        qr.teacher_awarded_marks = 3
        session.commit()

    view = _service(pg_sessionmaker).get(student, attempt_id, qr_id)

    assert isinstance(view, PendingSelfReview)
    assert view.state == "not_started"


# ── submit, no judge configured ────────────────────────────────────────────


def _attempt_row(sm: sessionmaker[Session], attempt_id: uuid.UUID) -> Attempt:
    with sm() as session:
        attempt = session.get(Attempt, attempt_id)
        assert attempt is not None
        _ = attempt.weakness_records
        return attempt


def test_low_confidence_grant_moves_marks_through_the_whole_attempt(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """The headline path (D2 + D4 + D5): student says earned on every point of
    a low-confidence question the marker gave 0/3 — the marks, the attempt
    total, the grade, the weakness rows and the queue row all move together,
    and the AI's mark is untouched."""
    student = _seed_user(pg_sessionmaker)
    attempt_id = _seed_attempt(pg_sessionmaker, student, [_high(matched=["p1", "p2"]), _low()])
    qr_id = _qr_id(pg_sessionmaker, attempt_id, "2")
    before = _attempt_row(pg_sessionmaker, attempt_id)
    assert before.awarded_marks == 2 and before.percentage == 40.0

    view = _service(pg_sessionmaker).submit(
        student, attempt_id, qr_id, _all_earned(["p1", "p2", "p3"])
    )

    assert isinstance(view, RevealedSelfReview)
    assert view.state == "settled"
    assert view.ai_marks == 0
    assert view.student_marks == 3
    assert view.effective_marks == 3
    assert view.teacher_settled is False and view.pending_teacher is False
    assert [p.awarded for p in view.points] == [False, False, False]
    assert [p.student_selfmark for p in view.points] == [True, True, True]
    assert [p.evidence_verdict for p in view.points] == ["not_required"] * 3
    assert all(p.mark_changed for p in view.points)

    qr = _load_qr(pg_sessionmaker, qr_id)
    assert qr.awarded_marks == 0  # the accuracy guard: lemely/eval reads this
    assert qr.student_selfmark_marks == 3
    assert qr.student_selfmarked_at is not None
    assert all(p.student_selfmark is True and p.student_selfmark_at is not None for p in qr.points)
    assert [r.revision for r in qr.revisions] == [1, 2]
    assert qr.revisions[1].source is RevisionSource.student_selfmark
    assert qr.revisions[1].awarded_marks == 3
    assert qr.revisions[1].actor_user_id == student
    assert {e["mark_point_id"] for e in qr.revisions[1].points_snapshot} == {"p1", "p2", "p3"}

    after = _attempt_row(pg_sessionmaker, attempt_id)
    assert after.awarded_marks == 5
    assert after.percentage == 100.0
    assert after.grade == "A" and after.predicted_grade == "A"
    assert after.weakness_records == []  # "Waves" no longer loses marks

    rows = _queue_rows(pg_sessionmaker, qr_id)
    assert [r.reason for r in rows] == [ReviewReason.low_confidence]
    assert rows[0].status is ReviewStatus.resolved
    assert rows[0].resolved_by == student
    assert rows[0].resolved_at is not None
    assert rows[0].resolution_note == SELFMARK_RESOLUTION_NOTE


def test_low_confidence_downward_self_mark_is_honoured(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """D6: a student who says they did *not* earn an awarded point loses it."""
    student = _seed_user(pg_sessionmaker)
    attempt_id = _seed_attempt(pg_sessionmaker, student, [_high(), _low(matched=["p1", "p2"])])
    qr_id = _qr_id(pg_sessionmaker, attempt_id, "2")

    view = _service(pg_sessionmaker).submit(
        student,
        attempt_id,
        qr_id,
        [
            PointVerdict("p1", earned=False),
            PointVerdict("p2", earned=True),
            PointVerdict("p3", earned=False),
        ],
    )

    assert view.ai_marks == 2
    assert view.student_marks == 1
    assert view.effective_marks == 1
    assert [p.mark_changed for p in view.points] == [True, False, False]
    assert _load_qr(pg_sessionmaker, qr_id).awarded_marks == 2


def test_agreement_changes_nothing_but_records_the_pass(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student = _seed_user(pg_sessionmaker)
    attempt_id = _seed_attempt(pg_sessionmaker, student, [_high(), _low(matched=["p1"])])
    qr_id = _qr_id(pg_sessionmaker, attempt_id, "2")

    view = _service(pg_sessionmaker).submit(
        student,
        attempt_id,
        qr_id,
        [
            PointVerdict("p1", earned=True),
            PointVerdict("p2", earned=False),
            PointVerdict("p3", earned=False),
        ],
    )

    assert view.state == "settled"
    assert view.student_marks is None
    assert view.effective_marks == 1
    assert not any(p.mark_changed for p in view.points)
    assert [p.evidence_verdict for p in view.points] == [None, None, None]
    qr = _load_qr(pg_sessionmaker, qr_id)
    assert qr.is_self_marked
    # Agreement does nothing beyond confirming it: the queue row stays open.
    assert [r.status for r in _queue_rows(pg_sessionmaker, qr_id)] == [ReviewStatus.open]
    # ...but the pass itself is history.
    assert [r.source for r in qr.revisions] == [RevisionSource.ai, RevisionSource.student_selfmark]
    assert qr.revisions[1].awarded_marks == 1


def test_second_submission_is_rejected_and_writes_nothing(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student = _seed_user(pg_sessionmaker)
    attempt_id = _seed_attempt(pg_sessionmaker, student, [_high(), _low()])
    qr_id = _qr_id(pg_sessionmaker, attempt_id, "2")
    service = _service(pg_sessionmaker)
    service.submit(student, attempt_id, qr_id, _all_earned(["p1", "p2", "p3"]))
    first = _load_qr(pg_sessionmaker, qr_id)

    with pytest.raises(SelfReviewAlreadySubmittedError):
        service.submit(
            student,
            attempt_id,
            qr_id,
            [PointVerdict(p, earned=False) for p in ("p1", "p2", "p3")],
        )

    second = _load_qr(pg_sessionmaker, qr_id)
    assert second.student_selfmarked_at == first.student_selfmarked_at
    assert second.student_selfmark_marks == 3
    assert len(second.revisions) == 2


@pytest.mark.parametrize(
    ("verdicts", "message"),
    [
        (_all_earned(["p1", "p2"]), "missing"),  # partial: reveal-by-halves is refused
        (_all_earned(["p1", "p2", "p3", "p9"]), "Unknown"),
        (_all_earned(["p1", "p2", "p3", "p3"]), "Duplicate"),
        ([], "missing"),
    ],
)
def test_incomplete_or_malformed_submissions_are_rejected_before_any_write(
    pg_sessionmaker: sessionmaker[Session], verdicts: list[PointVerdict], message: str
) -> None:
    student = _seed_user(pg_sessionmaker)
    attempt_id = _seed_attempt(pg_sessionmaker, student, [_high(), _low()])
    qr_id = _qr_id(pg_sessionmaker, attempt_id, "2")

    with pytest.raises(SelfReviewValidationError, match=message):
        _service(pg_sessionmaker).submit(student, attempt_id, qr_id, verdicts)

    qr = _load_qr(pg_sessionmaker, qr_id)
    assert not qr.is_self_marked
    assert all(p.student_selfmark is None for p in qr.points)
    assert len(qr.revisions) == 1


def test_high_confidence_disagreement_without_evidence_is_a_misconception_only(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """D3: on a confident point a bare self-mark changes nothing — but the
    misconception (claimed, not awarded, nothing granted) is recorded."""
    student = _seed_user(pg_sessionmaker)
    attempt_id = _seed_attempt(pg_sessionmaker, student, [_high(matched=["p1"]), _low()])
    qr_id = _qr_id(pg_sessionmaker, attempt_id, "1")

    view = _service(pg_sessionmaker).submit(student, attempt_id, qr_id, _all_earned(["p1", "p2"]))

    assert view.state == "settled"
    assert view.effective_marks == 1 and view.student_marks is None
    p2 = next(p for p in view.points if p.mark_point_id == "p2")
    assert p2.awarded is False and p2.student_selfmark is True
    assert p2.evidence_verdict is None and p2.mark_changed is False
    assert _queue_rows(pg_sessionmaker, qr_id) == []


def test_high_confidence_challenge_with_evidence_and_no_judge_goes_to_a_teacher(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """No judge configured is a judge failure: never a silent accept or reject."""
    student = _seed_user(pg_sessionmaker)
    attempt_id = _seed_attempt(pg_sessionmaker, student, [_high(matched=["p1"]), _low()])
    qr_id = _qr_id(pg_sessionmaker, attempt_id, "1")

    view = _service(pg_sessionmaker, judge=None).submit(
        student,
        attempt_id,
        qr_id,
        [PointVerdict("p1", True), PointVerdict("p2", True, evidence="I wrote the unit, N.")],
    )

    assert view.state == "revealed"
    assert view.pending_teacher is True
    assert view.effective_marks == 1
    p2 = next(p for p in view.points if p.mark_point_id == "p2")
    assert p2.evidence_verdict is None and p2.mark_changed is False
    assert p2.student_evidence == "I wrote the unit, N."
    rows = _queue_rows(pg_sessionmaker, qr_id)
    assert [r.reason for r in rows] == [ReviewReason.student_evidence_unjudged]
    assert rows[0].status is ReviewStatus.open


def test_integrity_only_flag_behaves_as_high_confidence(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student = _seed_user(pg_sessionmaker)
    flagged = _question(
        "1", matched=["p1"], maximum=2, needs_review=True, ai_detection_flagged=True
    )
    attempt_id = _seed_attempt(pg_sessionmaker, student, [flagged, _low()])
    qr_id = _qr_id(pg_sessionmaker, attempt_id, "1")

    view = _service(pg_sessionmaker).submit(student, attempt_id, qr_id, _all_earned(["p1", "p2"]))

    assert view.effective_marks == 1 and view.student_marks is None
    # The integrity row is never touched by a self-mark.
    assert [r.reason for r in _queue_rows(pg_sessionmaker, qr_id)] == [
        ReviewReason.ai_detection_flag
    ]
    assert _queue_rows(pg_sessionmaker, qr_id)[0].status is ReviewStatus.open


def test_teacher_override_already_recorded_wins_and_skips_nothing_else(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """The race: a teacher settled this question mid-pass. The self-mark and
    its misconception signal are still recorded; marks do not move."""
    student = _seed_user(pg_sessionmaker)
    attempt_id = _seed_attempt(pg_sessionmaker, student, [_high(), _low()])
    qr_id = _qr_id(pg_sessionmaker, attempt_id, "2")
    with pg_sessionmaker() as session, session.begin():
        qr = session.get(QuestionResult, qr_id)
        assert qr is not None
        qr.teacher_awarded_marks = 2
        qr.overridden_at = datetime.now(UTC)
        for row in session.scalars(
            select(ReviewQueueItem).where(ReviewQueueItem.question_result_id == qr_id)
        ):
            row.status = ReviewStatus.resolved

    view = _service(pg_sessionmaker).submit(
        student, attempt_id, qr_id, _all_earned(["p1", "p2", "p3"])
    )

    assert view.teacher_settled is True
    assert view.effective_marks == 2
    assert view.student_marks is None
    assert not any(p.mark_changed for p in view.points)
    qr = _load_qr(pg_sessionmaker, qr_id)
    assert all(p.student_selfmark is True for p in qr.points)
    assert qr.is_self_marked


def test_evidence_with_a_nul_byte_is_stored_stripped_not_fatal(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """Postgres rejects NUL in text and JSONB; a student's paste must not
    abort their own pass (the spec-1 lesson: loose input meeting a strict
    constraint lost a whole transaction)."""
    student = _seed_user(pg_sessionmaker)
    attempt_id = _seed_attempt(pg_sessionmaker, student, [_high(), _low()])
    qr_id = _qr_id(pg_sessionmaker, attempt_id, "2")

    view = _service(pg_sessionmaker).submit(
        student, attempt_id, qr_id, _all_earned(["p1", "p2", "p3"], evidence="see\x00 line 2")
    )

    assert view.points[0].student_evidence == "see line 2"
    assert _load_qr(pg_sessionmaker, qr_id).is_self_marked


def test_evidence_with_a_lone_surrogate_is_stored_stripped_not_fatal(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """A lone surrogate survives ``json.loads`` of a student's evidence string
    (reachable straight through the API, since evidence arrives as JSON) but
    cannot be encoded as UTF-8 — it must not abort the transaction on flush
    into ``student_evidence`` (``sa.Text``) or the JSONB snapshot."""
    student = _seed_user(pg_sessionmaker)
    attempt_id = _seed_attempt(pg_sessionmaker, student, [_high(), _low()])
    qr_id = _qr_id(pg_sessionmaker, attempt_id, "2")
    lone_surrogate = json.loads('"\\ud800"')
    assert lone_surrogate == "\ud800"

    view = _service(pg_sessionmaker).submit(
        student,
        attempt_id,
        qr_id,
        _all_earned(["p1", "p2", "p3"], evidence=f"see{lone_surrogate} line 2"),
    )

    assert view.points[0].student_evidence == "see line 2"
    assert _load_qr(pg_sessionmaker, qr_id).is_self_marked


def test_evidence_longer_than_the_max_is_truncated(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student = _seed_user(pg_sessionmaker)
    attempt_id = _seed_attempt(pg_sessionmaker, student, [_high(), _low()])
    qr_id = _qr_id(pg_sessionmaker, attempt_id, "2")
    long_evidence = "x" * (MAX_EVIDENCE_CHARS + 500)

    view = _service(pg_sessionmaker).submit(
        student, attempt_id, qr_id, _all_earned(["p1", "p2", "p3"], evidence=long_evidence)
    )

    stored = view.points[0].student_evidence
    assert stored is not None
    assert len(stored) == MAX_EVIDENCE_CHARS
    assert _load_qr(pg_sessionmaker, qr_id).points[0].student_evidence == stored


class _JunkJudge:
    """Returns whatever junk it was constructed with, ignoring the request."""

    def __init__(self, junk: object) -> None:
        self._junk = junk

    def judge(self, request: JudgeRequest) -> JudgeVerdict:
        return self._junk  # type: ignore[return-value]


@pytest.mark.parametrize("junk", [None, {"accepted": True, "reason": "looks fine"}])
def test_a_malformed_judge_return_does_not_abort_the_pass(
    pg_sessionmaker: sessionmaker[Session], junk: object
) -> None:
    """Finding 1: ``JudgeVerdict(bool(verdict.accepted), ...)`` used to sit
    outside the ``try``, so a judge returning ``None`` or a dict raised
    ``AttributeError`` there and rolled back the student's whole self-mark.
    Any junk from a judge must be treated exactly like a raised exception:
    unjudged, not fatal."""
    student = _seed_user(pg_sessionmaker)
    attempt_id = _seed_attempt(pg_sessionmaker, student, [_high(matched=["p1"]), _low()])
    qr_id = _qr_id(pg_sessionmaker, attempt_id, "1")

    view = _service(pg_sessionmaker, judge=_JunkJudge(junk)).submit(
        student,
        attempt_id,
        qr_id,
        [PointVerdict("p1", True), PointVerdict("p2", True, evidence="I wrote the unit, N.")],
    )

    assert view.state == "revealed"
    assert view.pending_teacher is True
    p2 = next(p for p in view.points if p.mark_point_id == "p2")
    assert p2.evidence_verdict is None and p2.mark_changed is False
    rows = _queue_rows(pg_sessionmaker, qr_id)
    assert [r.reason for r in rows] == [ReviewReason.student_evidence_unjudged]
    assert rows[0].status is ReviewStatus.open
    assert _load_qr(pg_sessionmaker, qr_id).is_self_marked


class _StubJudge:
    """Always returns the verdict it was constructed with."""

    def __init__(self, verdict: JudgeVerdict) -> None:
        self._verdict = verdict

    def judge(self, request: JudgeRequest) -> JudgeVerdict:
        return self._verdict


def test_judge_reason_longer_than_the_max_is_truncated(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student = _seed_user(pg_sessionmaker)
    attempt_id = _seed_attempt(pg_sessionmaker, student, [_high(matched=["p1"]), _low()])
    qr_id = _qr_id(pg_sessionmaker, attempt_id, "1")
    long_reason = "y" * (MAX_JUDGE_REASON_CHARS + 500)
    judge = _StubJudge(JudgeVerdict(accepted=True, reason=long_reason))

    view = _service(pg_sessionmaker, judge=judge).submit(
        student,
        attempt_id,
        qr_id,
        [PointVerdict("p1", True), PointVerdict("p2", True, evidence="I wrote the unit, N.")],
    )

    p2 = next(p for p in view.points if p.mark_point_id == "p2")
    assert p2.judge_reason is not None
    assert len(p2.judge_reason) == MAX_JUDGE_REASON_CHARS
    assert p2.mark_changed is True


def test_self_marked_and_teacher_overridden_attempts_with_identical_marks_agree(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """The totals invariant: one recompute, so the two paths cannot round
    differently. Attempt A is self-marked to 3/3 on question 2; attempt B has
    a teacher override to 3 on the same question."""
    from lemely.db.review_repo import recompute_attempt_totals, recompute_weakness_records
    from lemely.io.grade_boundaries import GradeBoundaryStore

    student = _seed_user(pg_sessionmaker)
    a = _seed_attempt(pg_sessionmaker, student, [_high(), _low()])
    b = _seed_attempt(pg_sessionmaker, student, [_high(), _low()])

    _service(pg_sessionmaker).submit(
        student, a, _qr_id(pg_sessionmaker, a, "2"), _all_earned(["p1", "p2", "p3"])
    )
    with pg_sessionmaker() as session, session.begin():
        attempt_b = session.get(Attempt, b)
        assert attempt_b is not None
        results = session.scalars(
            select(QuestionResult).where(QuestionResult.attempt_id == b)
        ).all()
        next(qr for qr in results if qr.question_id == "2").teacher_awarded_marks = 3
        recompute_attempt_totals(session, attempt_b, results, boundary_store=GradeBoundaryStore())
        recompute_weakness_records(session, attempt_b, results)

    ra, rb = _attempt_row(pg_sessionmaker, a), _attempt_row(pg_sessionmaker, b)
    assert (ra.awarded_marks, ra.percentage, ra.grade) == (
        rb.awarded_marks,
        rb.percentage,
        rb.grade,
    )
    assert {(w.topic, w.lost_marks) for w in ra.weakness_records} == {
        (w.topic, w.lost_marks) for w in rb.weakness_records
    }


# ── delta vs. re-sum: an either/or group must not double-credit ────────────


def _alt_group_scheme() -> MarkScheme:
    """Question "3" (1 mark): p1/p2 are alternatives worth 1 mark combined."""
    return MarkScheme(
        metadata=MarkSchemeMetadata(
            subject="Physics",
            subject_code="0625",
            paper_number=1,
            paper_variant=1,
            session_month=LooseSessionMonth.MAY_JUNE,
            session_year=2020,
            paper_type=PaperType.THEORY_CORE,
            maximum_mark=1,
            scheme_format=SchemeFormat.POINT_BASED,
        ),
        questions=[
            SchemeQuestion(
                id="3",
                marks=1,
                type=SchemeQuestionType.RECALL,
                answer_points=[
                    AnswerPoint(id="p1", point="Either form", marks=1, is_alternative=True),
                    AnswerPoint(id="p2", point="Or this form", marks=1, is_alternative=True),
                ],
            ),
        ],
    )


def _seed_alt_attempt(
    sm: sessionmaker[Session], student: uuid.UUID, *, low_confidence: bool = False
) -> uuid.UUID:
    """One question, "3": both alternative points matched, capped to 1 mark —
    exactly what correction_ai's own coherence check would produce for an
    either/or group, and the situation the delta rule (not a re-sum) exists
    for (see the module docstring of ``lemely/db/self_review_repo.py``)."""
    question = CorrectedQuestion(
        question_id="3",
        awarded_marks=1,  # capped: NOT len(matched) == 2
        maximum_marks=1,
        confidence=ConfidenceBand.LOW if low_confidence else ConfidenceBand.HIGH,
        confidence_score=0.2 if low_confidence else 0.95,
        needs_teacher_review=low_confidence,
        student_answer="answer-3",
        expected_answer="expected-3",
        topic="Waves",
        marker_source="ai",
        feedback="Either form accepted.",
        matched_point_ids=["p1", "p2"],
    )
    return AttemptRepository(sm).persist_correction(
        user_id=str(student),
        report=_report([question]),
        mark_scheme=_alt_group_scheme(),
    )


def test_agreement_on_a_capped_alternative_group_is_not_resummed_into_double_credit(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """The delta rule vs. a re-sum, made to disagree on purpose. p1 and p2 are
    alternatives worth 1 mark combined; the marker matched both and capped
    the award at 1 (``QuestionResultPoint.awarded`` is True on *both* rows,
    ``awarded_marks == 1``).

    Finding 4: the original version of this test was all-AGREE (student
    ticks both points, same as the marker), so ``changed`` was ``False`` and
    the write never ran — a buggy ``if changed: student_selfmark_marks =
    sum(tariff for ticked)`` implementation passed it (and all other tests in
    this file) despite being wrong. This fixture forces both points to
    actually change: the student says p1 was **not** earned (ungranting a
    point the marker awarded, delta -1) and p2 **was** earned — but p2 is
    already AI-awarded True, so that is an AGREE, not a grant, and
    contributes nothing. The correct delta is ``awarded_marks(1) + (-1) ==
    0``. A ``sum(tariff for verdict.earned)`` re-sum would instead total the
    tariff of every point the student ticked ``True`` — just p2 — giving 1,
    diverging from the delta result.

    Verified by hand against a re-sum stand-in
    (``student_selfmark_marks = sum(p.tariff for p in qr.points if
    by_point[p.mark_point_id].earned)`` in place of the delta line): it
    produced 1 where this test asserts 0, confirming the fixture
    discriminates."""
    student = _seed_user(pg_sessionmaker)
    attempt_id = _seed_alt_attempt(pg_sessionmaker, student, low_confidence=True)
    qr_id = _qr_id(pg_sessionmaker, attempt_id, "3")

    view = _service(pg_sessionmaker).submit(
        student,
        attempt_id,
        qr_id,
        [PointVerdict("p1", earned=False), PointVerdict("p2", earned=True)],
    )

    p1 = next(p for p in view.points if p.mark_point_id == "p1")
    p2 = next(p for p in view.points if p.mark_point_id == "p2")
    assert p1.mark_changed is True  # ungranted: the marker's award is withdrawn
    assert p2.mark_changed is False  # agreement: ai_awarded is already True
    assert view.student_marks == 0  # delta: 1 - 1 == 0, NOT a re-sum's 1
    assert view.effective_marks == 0
    qr = _load_qr(pg_sessionmaker, qr_id)
    assert qr.awarded_marks == 1  # the AI's mark is never mutated
    assert qr.student_selfmark_marks == 0


# ── concurrent submissions on one attempt ───────────────────────────────────


def test_concurrent_submissions_on_different_questions_of_one_attempt_do_not_lose_a_total(
    pg_sessionmaker: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Finding 3: ``submit`` used to lock only the ``QuestionResult`` row, not
    the ``Attempt``. Two submissions on *different* questions of the same
    attempt take different QuestionResult locks, then both call
    ``recompute_attempt_totals`` / ``recompute_weakness_records`` for the same
    attempt from their own read. Under READ COMMITTED the second overwrites
    the first, and one question's change silently vanishes from
    ``attempts.awarded_marks``.

    Real threads against real Postgres locks: a monkeypatched
    ``recompute_attempt_totals`` sleeps while holding the (now-fixed) Attempt
    lock, widening the window in which the second submission would race
    ahead of the first if the lock were absent. With the Attempt locked
    attempt-then-question (the same order used elsewhere in this module and
    in ``review_repo``, so no new deadlock), the two passes serialize and
    both questions' marks land in the final total."""
    student = _seed_user(pg_sessionmaker)
    attempt_id = _seed_attempt(
        pg_sessionmaker,
        student,
        [
            _question("1", matched=[], maximum=2, confidence_score=0.2, needs_review=True),
            _question("2", matched=[], maximum=3, confidence_score=0.2, needs_review=True),
        ],
    )
    qr1 = _qr_id(pg_sessionmaker, attempt_id, "1")
    qr2 = _qr_id(pg_sessionmaker, attempt_id, "2")

    import lemely.db.self_review_repo as repo_module

    real_recompute = repo_module.recompute_attempt_totals

    def _slow_recompute(*args: object, **kwargs: object) -> None:
        time.sleep(0.2)
        real_recompute(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(repo_module, "recompute_attempt_totals", _slow_recompute)

    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def _submit(qr_id: uuid.UUID, point_ids: list[str]) -> None:
        try:
            barrier.wait(timeout=5)
            _service(pg_sessionmaker).submit(student, attempt_id, qr_id, _all_earned(point_ids))
        except BaseException as exc:
            errors.append(exc)

    t1 = threading.Thread(target=_submit, args=(qr1, ["p1", "p2"]))
    t2 = threading.Thread(target=_submit, args=(qr2, ["p1", "p2", "p3"]))
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)

    assert not errors, errors
    after = _attempt_row(pg_sessionmaker, attempt_id)
    assert after.awarded_marks == 5  # both questions' 2 and 3 marks, neither lost
    assert after.percentage == 100.0
    assert after.weakness_records == []
    assert _load_qr(pg_sessionmaker, qr1).student_selfmark_marks == 2
    assert _load_qr(pg_sessionmaker, qr2).student_selfmark_marks == 3
