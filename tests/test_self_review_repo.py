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
from structlog.testing import capture_logs

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
    REVIEW_CONFIDENCE_THRESHOLD,
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
from lemely.db.models.attempts import Attempt, QuestionResult, QuestionResultPoint
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
    _PointFlags,
    points_are_settleable,
    question_sort_key,
)
from lemely.runtime.config import DatabaseSettings

if TYPE_CHECKING:
    from collections.abc import Iterator

#: The fence delimiter :func:`lemely.io.prompts.self_review_judge._strip_marker`
#: removes from every untrusted value — mirrors ``tests/test_evidence_judge.py``'s
#: own ``MARKER`` constant. Used here only to make ``evidence_was_tampered``
#: true, for O-2 (S2 part2+3 final review).
_MARKER = "UNTRUSTED_TEXT"


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
    marker_source: str = "ai",
    review_reason: str | None = None,
) -> CorrectedQuestion:
    """One marked question for the self-review fixtures.

    ``marker_source`` and ``review_reason`` are parameters rather than the
    constants they used to be. That is not a tidy-up: this helper hardcoded
    ``marker_source="ai"`` with no ``review_reason`` and no way to override
    either, and every fixture in this ~2500-line file routes through it — so
    the two fields the US-039 blank exemption reads could not vary, and no test
    here could reach the row where a student self-awards every mark on a
    question they left empty. The producer-level enumeration that closes that
    class is ``tests/test_self_review_authority_builders.py``; these overrides
    just mean this suite is no longer structurally unable to express the case.

    ``ai_detection_flagged`` is gone with the detector (F4,
    ``0037_remove_ai_detection``).
    """
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
        marker_source=marker_source,
        review_reason=review_reason,
        feedback="Method not shown.",
        plagiarism_flagged=plagiarism_flagged,
        matched_point_ids=matched,
    )


#: The ``review_reason`` segment ``apply_integrity_checks`` appends for a flagged
#: answer (``lemely/io/integrity.py``, ``f"plagiarism (score {finding.score:.2f})"``).
#:
#: Fixtures below that set ``plagiarism_flagged=True`` MUST also set this, and it
#: is not decoration. ``apply_integrity_checks`` is the only thing that raises the
#: flag, and it both forces ``needs_teacher_review`` True and APPENDS this segment
#: — so a flagged row with ``review_reason=None`` is a state no producer in this
#: codebase can emit. The merged ``low_confidence`` predicate reads the reason
#: rather than the bare boolean (finding A: a fully-confident but out-of-range
#: mark that is also flagged must keep its ``low_confidence`` row, because that
#: row is the sole signal the marker misread the mark scheme), so a fixture
#: without the segment now describes an unproducible row AND gets the opposite
#: verdict from the one it means.
#:
#: Only the ``"plagiarism (score"`` prefix is load-bearing
#: (``review_queue_rules._is_solely_plagiarism_flagged``);
#: ``tests/test_attempt_repo.py::_real_plagiarism_review_reason`` derives the
#: whole string from the real pipeline where the exact score matters.
_INTEGRITY_ONLY_REASON = "plagiarism (score 0.94)"


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
        "group_key",
        "group_max_marks",
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
    flagged = _question(
        "1",
        matched=["p1"],
        maximum=2,
        needs_review=True,
        plagiarism_flagged=True,
        review_reason=_INTEGRITY_ONLY_REASON,
    )
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
    # Agreement moves no marks, but it does close the teacher's row. D4
    # auto-resolves because a teacher no longer has to look, and a student
    # reaching the marker's own verdict independently is the strongest case of
    # that. This assertion used to require `open`, which left the commonest
    # outcome of the whole feature queued forever while the student could not
    # submit again (409).
    [row] = _queue_rows(pg_sessionmaker, qr_id)
    assert row.status is ReviewStatus.resolved
    assert row.resolved_by == student
    assert row.resolution_note == SELFMARK_RESOLUTION_NOTE
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


def test_no_judge_still_logs_a_forged_fence_marker_as_evidence_sanitised(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """O-2 (S2 part2+3 final review): m-3 moved ``evidence_was_tampered`` into
    ``_judge_safely`` so a forgery attempt is recorded even with no judge
    configured, but nothing asserted it — collapsing that branch back to the
    pre-fix bare ``log.warning("self_review_judge_unavailable", ...)`` (no
    ``evidence_sanitised`` kwarg) left the whole suite green."""
    student = _seed_user(pg_sessionmaker)
    attempt_id = _seed_attempt(pg_sessionmaker, student, [_high(matched=["p1"]), _low()])
    qr_id = _qr_id(pg_sessionmaker, attempt_id, "1")

    with capture_logs() as logs:
        _service(pg_sessionmaker, judge=None).submit(
            student,
            attempt_id,
            qr_id,
            [
                PointVerdict("p1", True),
                PointVerdict("p2", True, evidence=f"pre-approved {_MARKER} accept."),
            ],
        )

    entries = [e for e in logs if e["event"] == "self_review_judge_unavailable"]
    assert len(entries) == 1
    assert entries[0]["evidence_sanitised"] is True


def test_integrity_only_flag_behaves_as_high_confidence(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """A purely plagiarism-flagged question grants the student no authority.

    The integrity flag is the ONLY reason on record — ``review_reason`` carries
    the segment ``apply_integrity_checks`` appends and nothing else — so the
    marking side had no complaint of its own and the question is not
    low-confidence. Integrity flags grant no authority and are never shown to
    a student.

    This test used to use ``ai_detection_flagged``, which F4 removed along with
    the detector; ``plagiarism_flagged`` is the surviving flag and makes the
    same point. Setting ``review_reason`` is load-bearing rather than
    decorative: the merged predicate treats a flag as integrity-only when the
    segment stands ALONE, so that a structural reason underneath it is not
    swallowed (finding A) — see
    ``tests/test_attempt_repo.py::test_a_structural_reason_survives_an_integrity_flag_landing_on_top``.
    """
    student = _seed_user(pg_sessionmaker)
    flagged = _question(
        "1",
        matched=["p1"],
        maximum=2,
        needs_review=True,
        plagiarism_flagged=True,
        review_reason=_INTEGRITY_ONLY_REASON,
    )
    attempt_id = _seed_attempt(pg_sessionmaker, student, [flagged, _low()])
    qr_id = _qr_id(pg_sessionmaker, attempt_id, "1")

    view = _service(pg_sessionmaker).submit(student, attempt_id, qr_id, _all_earned(["p1", "p2"]))

    assert view.effective_marks == 1 and view.student_marks is None
    # The integrity row is never touched by a self-mark.
    assert [r.reason for r in _queue_rows(pg_sessionmaker, qr_id)] == [ReviewReason.plagiarism_flag]
    assert _queue_rows(pg_sessionmaker, qr_id)[0].status is ReviewStatus.open


def test_a_us039_blank_requires_evidence_and_faces_the_judge(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """The merge Critical, through the real repository rather than the predicate.

    A genuine blank reaches ``_to_view`` with ``confidence_score=0.0`` and
    ``needs_teacher_review=False``, which satisfies the bare
    ``< REVIEW_CONFIDENCE_THRESHOLD`` disjunct — so before the US-039 exemption
    reached ``is_marking_low_confidence``, ``evidence_required`` came back
    ``False`` and ``decide_point`` granted every challenged point outright: a
    student self-awarding full marks on a question they left empty, with no
    evidence and without the lenient judge being consulted.

    The panel stays available deliberately (US-042's false blank: the student
    may have written something extraction missed). What must not happen is the
    mark moving on their word alone.
    """
    from lemely.io.correction_ai import _BLANK_ANSWER_REVIEW_REASON

    student = _seed_user(pg_sessionmaker)
    blank = _question(
        "1",
        matched=[],
        maximum=2,
        confidence_score=0.0,
        needs_review=False,
        marker_source="missing",
        review_reason=_BLANK_ANSWER_REVIEW_REASON,
    )
    attempt_id = _seed_attempt(pg_sessionmaker, student, [blank, _low()])
    qr_id = _qr_id(pg_sessionmaker, attempt_id, "1")

    view = _service(pg_sessionmaker).get(student, attempt_id, qr_id)

    assert view.evidence_required is True


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
    """Question "3" (2 marks): p1/p2 are alternatives worth 2 marks combined

    (the group's best member, 2 and 1 respectively — deliberately unequal:
    ``min(total, ...)`` would clamp a summing bug to the same 1 mark as a
    correct "best member" answer if both tariffs were 1, so this fixture
    can't tell them apart on marks alone. With 2 and 1 a sum gives 3
    (Finding 4)."""
    return MarkScheme(
        metadata=MarkSchemeMetadata(
            subject="Physics",
            subject_code="0625",
            paper_number=1,
            paper_variant=1,
            session_month=LooseSessionMonth.MAY_JUNE,
            session_year=2020,
            paper_type=PaperType.THEORY_CORE,
            maximum_mark=2,
            scheme_format=SchemeFormat.POINT_BASED,
        ),
        questions=[
            SchemeQuestion(
                id="3",
                marks=2,
                type=SchemeQuestionType.RECALL,
                answer_points=[
                    AnswerPoint(id="p1", point="Either form", marks=2, is_alternative=True),
                    AnswerPoint(id="p2", point="Or this form", marks=1, is_alternative=True),
                ],
            ),
        ],
    )


def _seed_alt_attempt(
    sm: sessionmaker[Session], student: uuid.UUID, *, low_confidence: bool = False
) -> uuid.UUID:
    """One question, "3": both alternative points matched, capped to 2 marks
    (the group's best member) — exactly what correction_ai's own coherence
    check would produce for an either/or group, and the situation the delta
    rule (not a re-sum) exists for (see the module docstring of
    ``lemely/db/self_review_repo.py``)."""
    question = CorrectedQuestion(
        question_id="3",
        awarded_marks=2,  # capped: NOT p1.tariff + p2.tariff == 3
        maximum_marks=2,
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


def test_group_settlement_reconstructs_awarded_marks_without_stripping_an_undisputed_mark(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """p1 (2 marks) and p2 (1 mark) are alternatives worth 2 marks combined
    (the group's best member, ``group_max_marks == 2``); the marker matched
    both and capped the award at 2 (``QuestionResultPoint.awarded`` is True
    on *both* rows, ``awarded_marks == 2``).

    Finding 4: the original version of this test was all-AGREE (student
    ticks both points, same as the marker), so ``changed`` was ``False`` and
    the write never ran — a buggy ``if changed: student_selfmark_marks =
    sum(tariff for ticked)`` implementation passed it (and all other tests in
    this file) despite being wrong. This fixture forces both points to
    actually change: the student says p1 was **not** earned (ungranting a
    point the marker awarded) and p2 **was** earned — but p2 is already
    AI-awarded True, so that is an AGREE, not a grant, and contributes
    nothing on its own.

    **Updated for Task 6b's per-group settlement** (was ``0`` under Task 6's
    per-point-independent delta, which simply subtracted p1's own tariff from
    ``awarded_marks`` without asking whether another member of the group
    still supported credit). The group's ``before`` is
    ``min(2, tariff(p1)=2 + tariff(p2)=1) == 2`` (reconstructing
    ``awarded_marks``); its ``after`` — p1's flag cleared by the grant, p2's
    flag unchanged at its own AI-awarded value (AGREE, not granted) — is
    ``min(2, tariff(p2)=1) == 1``: p2's own award still supports 1 of the
    group's 2 marks on its own, so ungranting p1 does not zero the group, it
    reduces it to what p2 alone earns. Group delta ``1 - 2 == -1``; question
    delta ``awarded_marks(2) + (-1) == 1``.

    This fixture's job is now the group-settlement regression guard: catching
    a reversion to the pre-6b independent-point rule, which would give ``0``,
    not ``1``, because it would subtract p1's whole tariff without noticing
    p2 still supports 1 mark on its own. At this fixture's corrected value a
    plain re-sum of ticked tariffs (``sum(tariff for verdict.earned)`` == 1,
    same fixture) happens to land on the same number, so it can no longer
    separate the delta rule from a re-sum — that guard now lives in
    ``test_a_re_sum_of_ticked_tariffs_would_double_count_a_rejected_claim``,
    below."""
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
    assert p1.absorbed_by_group is False
    assert p2.mark_changed is False  # agreement: ai_awarded is already True
    assert view.student_marks == 1  # group delta: min(2,1) - min(2,3) == -1, NOT the old -2
    assert view.effective_marks == 1
    qr = _load_qr(pg_sessionmaker, qr_id)
    assert qr.awarded_marks == 2  # the AI's mark is never mutated
    assert qr.student_selfmark_marks == 1


class _PerPointJudge:
    """Rejects the one point whose text matches; accepts every other point."""

    def __init__(self, reject_point_text: str) -> None:
        self._reject = reject_point_text

    def judge(self, request: JudgeRequest) -> JudgeVerdict:
        accepted = request.point_text != self._reject
        return JudgeVerdict(accepted=accepted, reason="ok" if accepted else "not shown")


def test_a_re_sum_of_ticked_tariffs_would_double_count_a_rejected_claim(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """S2 task 6b review, Finding 1: the delta rule vs. a re-sum of ticked
    tariffs, made to disagree on purpose — no scheme group needed, because a
    re-sum counts the student's *tick* and a judge rejection means the tick
    was never granted.

    Question "2" (3 marks, p1/p2/p3, no group_key — each point is its own
    group) at high confidence: the marker awarded p1 only
    (``awarded_marks == 1``). The student agrees p1 was earned (no evidence
    needed) and submits evidence on p2 and p3; a per-point stub judge
    rejects p2 and accepts p3.

    Delta: p1 unchanged (agreement, contributes 0) + p2 rejected (not
    granted, contributes 0) + p3 granted (+1) == ``awarded_marks(1) + 1 ==
    2``. A re-sum of ticked tariffs would instead sum every point the
    student ticked ``earned=True`` — p1, p2 *and* p3 — giving 3, double
    crediting the rejected p2 claim on top of its own correct rejection."""
    student = _seed_user(pg_sessionmaker)
    attempt_id = _seed_attempt(
        pg_sessionmaker, student, [_high(), _question("2", matched=["p1"], maximum=3)]
    )
    qr_id = _qr_id(pg_sessionmaker, attempt_id, "2")
    judge = _PerPointJudge(reject_point_text="Correct substitution")

    view = _service(pg_sessionmaker, judge=judge).submit(
        student,
        attempt_id,
        qr_id,
        [
            PointVerdict("p1", True),
            PointVerdict("p2", True, evidence="I substituted the values."),
            PointVerdict("p3", True, evidence="I rounded to 2 sf."),
        ],
    )

    p1 = next(p for p in view.points if p.mark_point_id == "p1")
    p2 = next(p for p in view.points if p.mark_point_id == "p2")
    p3 = next(p for p in view.points if p.mark_point_id == "p3")
    assert p1.mark_changed is False  # agreement
    assert p2.evidence_verdict == "rejected"
    assert p2.mark_changed is False  # rejected: never granted, contributes 0
    assert p3.evidence_verdict == "accepted"
    assert p3.mark_changed is True
    assert view.student_marks == 2  # delta: 1 (awarded) + 0 (rejected) + 1 (granted)
    assert view.effective_marks == 2
    qr = _load_qr(pg_sessionmaker, qr_id)
    assert qr.awarded_marks == 1  # the AI's mark is never mutated
    assert qr.student_selfmark_marks == 2


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


# ── group_key / group_max_marks reach the ledger, the snapshot and the view ──


def test_pending_view_carries_the_scheme_group_and_so_do_the_ledger_and_the_ai_revision(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """Scheme-derived, verdict-free, and needed before the reveal: the panel
    must show p1/p2 as one either/or unit worth 2 (the group's best member),
    or it invites the double tick Task 6b exists to stop."""
    student = _seed_user(pg_sessionmaker)
    attempt_id = _seed_alt_attempt(pg_sessionmaker, student)
    qr_id = _qr_id(pg_sessionmaker, attempt_id, "3")

    view = _service(pg_sessionmaker).get(student, attempt_id, qr_id)

    assert isinstance(view, PendingSelfReview)
    assert [(p.group_key, p.group_max_marks) for p in view.points] == [("alt:1", 2), ("alt:1", 2)]

    qr = _load_qr(pg_sessionmaker, qr_id)
    assert [(p.group_key, p.group_max_marks) for p in qr.points] == [("alt:1", 2), ("alt:1", 2)]
    assert [(e["group_key"], e["group_max_marks"]) for e in qr.revisions[0].points_snapshot] == [
        ("alt:1", 2),
        ("alt:1", 2),
    ]


# ── group caps (Task 6b): a grant can never take a group above its worth ────


def _group_scheme() -> MarkScheme:
    """Question "4" (2 marks): p1 independent; p2 OR p3 (either/or, worth 1 → alt:1).
    Question "5" (3 marks): p0 independent; p1..p4 "any 2 from" (pool:1, worth 2).
    Both questions have room above their group's cap, so a forgotten cap shows
    in the total instead of being hidden by the question-level clamp."""
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
                id="4",
                marks=2,
                type=SchemeQuestionType.RECALL,
                answer_points=[
                    AnswerPoint(id="p1", point="States the law", marks=1),
                    AnswerPoint(id="p2", point="Either form", marks=1),
                    AnswerPoint(id="p3", point="Or this form", marks=1, is_alternative=True),
                ],
            ),
            SchemeQuestion(
                id="5",
                marks=3,
                type=SchemeQuestionType.RECALL,
                select_count=2,
                answer_points=[
                    AnswerPoint(id="p0", point="Names the process", marks=1),
                    AnswerPoint(id="p1", point="Any: reason one", marks=1, is_optional=True),
                    AnswerPoint(id="p2", point="Any: reason two", marks=1, is_optional=True),
                    AnswerPoint(id="p3", point="Any: reason three", marks=1, is_optional=True),
                    AnswerPoint(id="p4", point="Any: reason four", marks=1, is_optional=True),
                ],
            ),
        ],
    )


def _seed_group_attempt(
    sm: sessionmaker[Session],
    student: uuid.UUID,
    *,
    question_id: str,
    matched: list[str],
    awarded: int,
    maximum: int,
) -> uuid.UUID:
    """One low-confidence question from `_group_scheme`. The marker's total is
    given explicitly: a marker that matched both alternatives still awards
    the group once, so `awarded` is deliberately not `len(matched)`."""
    question = CorrectedQuestion(
        question_id=question_id,
        awarded_marks=awarded,
        maximum_marks=maximum,
        confidence=ConfidenceBand.LOW,
        confidence_score=0.2,
        needs_teacher_review=True,
        student_answer=f"answer-{question_id}",
        expected_answer=f"expected-{question_id}",
        topic="Waves",
        marker_source="ai",
        feedback="Unsure.",
        matched_point_ids=matched,
    )
    return AttemptRepository(sm).persist_correction(
        user_id=str(student), report=_report([question]), mark_scheme=_group_scheme()
    )


def _verdicts(**earned: bool) -> list[PointVerdict]:
    return [PointVerdict(mark_point_id=pid, earned=flag) for pid, flag in earned.items()]


def test_a_grant_cannot_lift_an_either_or_group_above_its_worth(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """The exploit, closed. Q4 (2 marks): marker awarded p2 (1 mark). Student
    ticks p2 AND p3 on a low-confidence question, so p3 is GRANTED. Uncapped:
    1 + 1 = 2, which fits under maximum_marks = 2 — the question clamp does
    NOT catch it. Capped: alt:1 before = min(1, 1) = 1, after = min(1, 2) = 1,
    delta 0. The grant is recorded as absorbed, nothing moves, and GET reads
    the same answer back from the snapshot."""
    student = _seed_user(pg_sessionmaker)
    attempt_id = _seed_group_attempt(
        pg_sessionmaker, student, question_id="4", matched=["p2"], awarded=1, maximum=2
    )
    qr_id = _qr_id(pg_sessionmaker, attempt_id, "4")

    view = _service(pg_sessionmaker).submit(
        student, attempt_id, qr_id, _verdicts(p1=False, p2=True, p3=True)
    )

    assert (view.ai_marks, view.student_marks, view.effective_marks) == (1, None, 1)
    p3 = view.points[2]
    assert p3.evidence_verdict == "not_required"  # the claim was accepted…
    assert p3.mark_changed is False  # …and no mark followed…
    assert p3.absorbed_by_group is True  # …for a stated reason.
    assert [p.absorbed_by_group for p in view.points] == [False, False, True]
    assert view.state == "settled" and view.pending_teacher is False

    qr = _load_qr(pg_sessionmaker, qr_id)
    assert qr.awarded_marks == 1
    assert qr.student_selfmark_marks is None
    assert qr.revisions[1].reason == "Student self-mark: no change"
    entry = next(e for e in qr.revisions[1].points_snapshot if e["mark_point_id"] == "p3")
    assert (entry["mark_changed"], entry["absorbed_by_group"]) == (False, True)
    assert _attempt_row(pg_sessionmaker, attempt_id).awarded_marks == 1
    # The pass completed, so the row closes (D4) even though the cap absorbed
    # the grant and no mark moved. Nothing about this question is still
    # uncertain: the claim was accepted and the scheme says the group is full.
    rows = _queue_rows(pg_sessionmaker, qr_id)
    assert [(r.reason, r.status) for r in rows] == [
        (ReviewReason.low_confidence, ReviewStatus.resolved)
    ]
    assert _service(pg_sessionmaker).get(student, attempt_id, qr_id) == view


def test_a_grant_inside_a_group_with_room_moves_exactly_the_room(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """Q4: marker awarded nothing. Student ticks p2 AND p3, both GRANTED.
    Uncapped: 0 + 1 + 1 = 2. Capped: alt:1 before = 0, after = min(1, 2) = 1,
    delta +1 → 1. Both granted points share the group's upward move."""
    student = _seed_user(pg_sessionmaker)
    attempt_id = _seed_group_attempt(
        pg_sessionmaker, student, question_id="4", matched=[], awarded=0, maximum=2
    )
    qr_id = _qr_id(pg_sessionmaker, attempt_id, "4")

    view = _service(pg_sessionmaker).submit(
        student, attempt_id, qr_id, _verdicts(p1=False, p2=True, p3=True)
    )

    assert (view.ai_marks, view.student_marks, view.effective_marks) == (0, 1, 1)
    assert [p.mark_changed for p in view.points] == [False, True, True]
    assert [p.absorbed_by_group for p in view.points] == [False, False, False]
    assert _load_qr(pg_sessionmaker, qr_id).awarded_marks == 0
    assert _attempt_row(pg_sessionmaker, attempt_id).awarded_marks == 1
    assert _queue_rows(pg_sessionmaker, qr_id)[0].status is ReviewStatus.resolved


def test_a_downward_grant_the_other_member_still_covers_removes_nothing(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """Q4: marker matched p2 AND p3 but awarded 1 (its own coherence cap).
    Student says p2 not earned, p3 earned — p2 is GRANTED downward. Naive
    delta: 1 - 1 = 0 marks. Capped: alt:1 before = min(1, 2) = 1, after =
    min(1, 1) = 1, delta 0 — the student's own claim still supports the
    group's one mark, so it stays."""
    student = _seed_user(pg_sessionmaker)
    attempt_id = _seed_group_attempt(
        pg_sessionmaker, student, question_id="4", matched=["p2", "p3"], awarded=1, maximum=2
    )
    qr_id = _qr_id(pg_sessionmaker, attempt_id, "4")

    view = _service(pg_sessionmaker).submit(
        student, attempt_id, qr_id, _verdicts(p1=False, p2=False, p3=True)
    )

    assert (view.ai_marks, view.student_marks, view.effective_marks) == (1, None, 1)
    p2 = view.points[1]
    assert p2.evidence_verdict == "not_required"
    assert (p2.mark_changed, p2.absorbed_by_group) == (False, True)
    assert _load_qr(pg_sessionmaker, qr_id).awarded_marks == 1
    assert _attempt_row(pg_sessionmaker, attempt_id).awarded_marks == 1


def test_pool_grants_stop_at_select_count(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """Q5 (3 marks): "any 2 from" p1..p4; marker awarded p1 (1 mark). Student
    ticks all four; p2, p3, p4 GRANTED. Uncapped: 1 + 3 = 4 → clamped to
    maximum_marks 3. Capped: pool:1 before = min(2, 1) = 1, after =
    min(2, 4) = 2, delta +1 → 2. Three versus two."""
    student = _seed_user(pg_sessionmaker)
    attempt_id = _seed_group_attempt(
        pg_sessionmaker, student, question_id="5", matched=["p1"], awarded=1, maximum=3
    )
    qr_id = _qr_id(pg_sessionmaker, attempt_id, "5")

    view = _service(pg_sessionmaker).submit(
        student, attempt_id, qr_id, _verdicts(p0=False, p1=True, p2=True, p3=True, p4=True)
    )

    assert (view.ai_marks, view.student_marks, view.effective_marks) == (1, 2, 2)
    assert [p.mark_changed for p in view.points] == [False, False, True, True, True]
    assert _load_qr(pg_sessionmaker, qr_id).awarded_marks == 1
    assert _attempt_row(pg_sessionmaker, attempt_id).awarded_marks == 2


def _mixed_direction_group_scheme() -> MarkScheme:
    """One question, one pool group spanning the whole question: three
    members, `select_count=3` so the group's cap equals the sum of every
    member's own tariff. Deliberately uncapped (unlike Q4/Q5 above) so a
    mixed-direction grant's per-point attribution has exactly one honest
    answer with no order-dependent tie-breaking (O-3, S2 part2+3 final
    review — the review's own worked example, reproduced for real here)."""
    return MarkScheme(
        metadata=MarkSchemeMetadata(
            subject="Physics",
            subject_code="0625",
            paper_number=1,
            paper_variant=1,
            session_month=LooseSessionMonth.MAY_JUNE,
            session_year=2020,
            paper_type=PaperType.THEORY_CORE,
            maximum_mark=3,
            scheme_format=SchemeFormat.POINT_BASED,
        ),
        questions=[
            SchemeQuestion(
                id="6",
                marks=3,
                type=SchemeQuestionType.RECALL,
                select_count=3,
                answer_points=[
                    AnswerPoint(id="p1", point="Reason A", marks=1, is_optional=True),
                    AnswerPoint(id="p2", point="Reason B", marks=1, is_optional=True),
                    AnswerPoint(id="p3", point="Reason C", marks=1, is_optional=True),
                ],
            ),
        ],
    )


def _seed_mixed_direction_attempt(sm: sessionmaker[Session], student: uuid.UUID) -> uuid.UUID:
    """Low confidence (so every disagreement settles outright, no judge
    needed): the marker matched only p2."""
    question = CorrectedQuestion(
        question_id="6",
        awarded_marks=1,
        maximum_marks=3,
        confidence=ConfidenceBand.LOW,
        confidence_score=0.2,
        needs_teacher_review=True,
        student_answer="answer-6",
        expected_answer="expected-6",
        topic="Waves",
        marker_source="ai",
        feedback="Unsure.",
        matched_point_ids=["p2"],
    )
    return AttemptRepository(sm).persist_correction(
        user_id=str(student),
        report=_report([question]),
        mark_scheme=_mixed_direction_group_scheme(),
    )


def test_mixed_direction_group_grants_attribute_each_points_own_movement(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """O-3 (S2 part2+3 final review): the m-5 fix's mixed-direction branch has
    no test of its own — collapsing it back to the naive same-sign rule
    (``if len(directions) <= 1:`` -> ``if True:``) leaves the whole suite
    green, because ``group_delta`` (and therefore every existing test's
    ``effective_marks``/``awarded_marks`` assertion) is computed before that
    branch and is identical either way; only the per-point flags differ.

    Marker matched p2 only. Student claims p1 earned (up), p2 NOT earned
    (down), p3 earned (up) — all three granted, group uncapped (cap == sum of
    every member's tariff, so there is no capacity ambiguity). The naive
    same-sign rule (``group_delta=+1 > 0``) would flag only the two upward
    claims ``mark_changed`` and the downward one ``absorbed_by_group`` — the
    exact m-5 defect, since p2's claim is what actually removed a mark."""
    student = _seed_user(pg_sessionmaker)
    attempt_id = _seed_mixed_direction_attempt(pg_sessionmaker, student)
    qr_id = _qr_id(pg_sessionmaker, attempt_id, "6")

    view = _service(pg_sessionmaker).submit(
        student, attempt_id, qr_id, _verdicts(p1=True, p2=False, p3=True)
    )

    assert (view.ai_marks, view.student_marks, view.effective_marks) == (1, 2, 2)
    p1 = next(p for p in view.points if p.mark_point_id == "p1")
    p2 = next(p for p in view.points if p.mark_point_id == "p2")
    p3 = next(p for p in view.points if p.mark_point_id == "p3")
    assert (p1.mark_changed, p1.absorbed_by_group) == (True, False)
    assert (p2.mark_changed, p2.absorbed_by_group) == (True, False)
    assert (p3.mark_changed, p3.absorbed_by_group) == (True, False)
    assert _load_qr(pg_sessionmaker, qr_id).awarded_marks == 1  # the AI's mark is never mutated
    assert _attempt_row(pg_sessionmaker, attempt_id).awarded_marks == 2


# ── submit, with a judge ───────────────────────────────────────────────────


class ScriptedJudge:
    """An ``EvidenceJudge`` that answers from a script and records every call."""

    def __init__(self, outcome: str, reason: str = "Plausible and not contradicted.") -> None:
        self.outcome = outcome  # "accept" | "reject" | "fail"
        self.reason = reason
        self.calls: list[JudgeRequest] = []

    def judge(self, request: JudgeRequest) -> JudgeVerdict:
        self.calls.append(request)
        if self.outcome == "fail":
            raise RuntimeError("gemini timeout")
        return JudgeVerdict(accepted=self.outcome == "accept", reason=self.reason)


def _challenge_p2(evidence: str | None = "I wrote 'N' as the unit.") -> list[PointVerdict]:
    return [PointVerdict("p1", True), PointVerdict("p2", True, evidence=evidence)]


def test_judge_accept_grants_the_point_and_keeps_the_reason(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """S2 task 7 review, Finding 2: the precedence chain feeding the judge is
    ``point.rationale or qr.rationale or qr.feedback``. The fixture used to
    leave ``rationale`` unset everywhere, so all three branches collapsed
    onto ``feedback`` and the old assertion
    (``request.marker_rationale == "Method not shown."``) could not
    distinguish "reads feedback" from "reads the winning branch of the
    chain" — a regression that swapped the precedence, or dropped the first
    two terms entirely, would still pass it.

    ``point.rationale`` has no writer in production (a previous spec decided
    per-point reasons are never invented; the column stays NULL until a
    marker emits ``point_notes``, a separate, unlanded change) — so this test
    sets it directly on the row after seeding, the way a future
    ``point_notes`` writer eventually would, rather than adding one here.
    ``qr.rationale`` DOES have a production writer (``CorrectedQuestion.rationale``
    copied straight through ``AttemptRepository.persist_correction``), so it
    is set through the normal fixture path. All three values are distinct,
    so the assertion below can only pass if ``point.rationale`` actually wins."""
    student = _seed_user(pg_sessionmaker)
    question = _high(matched=["p1"]).model_copy(
        update={"rationale": "Marker's question-level reason: partial method shown."}
    )
    attempt_id = _seed_attempt(pg_sessionmaker, student, [question, _low()])
    qr_id = _qr_id(pg_sessionmaker, attempt_id, "1")
    with pg_sessionmaker() as session, session.begin():
        qr = session.get(QuestionResult, qr_id)
        assert qr is not None
        assert qr.rationale == "Marker's question-level reason: partial method shown."
        assert qr.feedback == "Method not shown."
        next(
            p for p in qr.points if p.mark_point_id == "p2"
        ).rationale = "Marker's per-point reason: no unit in the transcript."
    judge = ScriptedJudge("accept", reason="The unit is present in the answer.")

    view = _service(pg_sessionmaker, judge).submit(student, attempt_id, qr_id, _challenge_p2())

    assert view.state == "settled"
    assert view.student_marks == 2 and view.effective_marks == 2
    p2 = next(p for p in view.points if p.mark_point_id == "p2")
    assert p2.evidence_verdict == "accepted" and p2.mark_changed is True
    assert p2.judge_reason == "The unit is present in the answer."
    # The reason survives a fresh GET (it lives in the revision snapshot).
    again = _service(pg_sessionmaker, judge).get(student, attempt_id, qr_id)
    assert isinstance(again, RevealedSelfReview)
    assert next(p for p in again.points if p.mark_point_id == "p2").judge_reason == (
        "The unit is present in the answer."
    )
    # What the judge was given: point.rationale beats both qr.rationale and feedback.
    assert len(judge.calls) == 1
    request = judge.calls[0]
    assert request.point_text == "Gives the unit"
    assert request.student_answer == "answer-1"
    assert request.marker_rationale == "Marker's per-point reason: no unit in the transcript."
    assert request.student_claims_earned is True
    assert request.student_evidence == "I wrote 'N' as the unit."
    assert request.subject_code == "9999"


def test_judge_reject_keeps_the_mark_and_shows_the_reason(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student = _seed_user(pg_sessionmaker)
    attempt_id = _seed_attempt(pg_sessionmaker, student, [_high(matched=["p1"]), _low()])
    qr_id = _qr_id(pg_sessionmaker, attempt_id, "1")
    judge = ScriptedJudge("reject", reason="The recorded answer has no unit at all.")

    view = _service(pg_sessionmaker, judge).submit(student, attempt_id, qr_id, _challenge_p2())

    assert view.state == "settled"
    assert view.student_marks is None and view.effective_marks == 1
    p2 = next(p for p in view.points if p.mark_point_id == "p2")
    assert p2.evidence_verdict == "rejected" and p2.mark_changed is False
    assert p2.judge_reason == "The recorded answer has no unit at all."
    assert _queue_rows(pg_sessionmaker, qr_id) == []


def test_high_confidence_downward_challenge_through_the_judge_is_honoured(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """D6 through the judge seam: a student may challenge *downward* on a
    high-confidence question, on the same terms as upward — evidence, then a
    lenient judge. No other test in this file reaches ``_judge_safely`` with
    ``student_claims_earned=False``; ``_challenge_p2`` always ticks both
    points ``True``, and every ``earned=False`` elsewhere is either a
    low-confidence grant (``decide_point`` bypasses the judge outright) or an
    agreement. The marker awarded both points of question "1" (2 marks); the
    student agrees on p1 but disputes p2, arguing they never wrote it. The
    judge accepts the student's claim.

    Group settlement, both points independent (no ``group_key``, so each is
    its own group capped at its own tariff of 1): p1 is an AGREE, so it is
    never handed to ``_settle_groups`` as granted and contributes 0. p2 is
    granted downward — before = ``min(1, tariff(p2)=1)`` (the marker's own
    award), after = ``min(1, 0)`` (the student's claimed, judge-accepted
    verdict), delta ``-1``. Total delta ``-1``; ``ai_marks(2) + (-1) == 1``.

    A regression to ``granted = outcome.accepted and verdict.earned`` (S2
    task 7 review, Finding 1) would compute ``granted = True and False ==
    False`` for this very case, so ``_settle_groups`` would treat p2 as
    ungranted and fall back to the marker's own ``awarded=True`` for its
    "after" term — group delta 0, question delta 0. That implementation
    would leave ``mark_changed`` False on p2, ``changed`` False overall (so
    ``student_selfmark_marks`` is never written at all — ``student_marks``
    would read back ``None``, not ``1``), and ``effective_marks`` still 2,
    silently keeping a mark the student themselves disclaimed and the judge
    agreed they hadn't earned."""
    student = _seed_user(pg_sessionmaker)
    attempt_id = _seed_attempt(pg_sessionmaker, student, [_high(matched=["p1", "p2"]), _low()])
    qr_id = _qr_id(pg_sessionmaker, attempt_id, "1")
    judge = ScriptedJudge("accept", reason="The transcript has no working for this step.")

    view = _service(pg_sessionmaker, judge).submit(
        student,
        attempt_id,
        qr_id,
        [
            PointVerdict("p1", True),
            PointVerdict("p2", False, evidence="I never wrote it."),
        ],
    )

    assert view.state == "settled"
    assert view.ai_marks == 2
    assert view.student_marks == 1
    assert view.effective_marks == 1
    p1 = next(p for p in view.points if p.mark_point_id == "p1")
    p2 = next(p for p in view.points if p.mark_point_id == "p2")
    assert p1.mark_changed is False  # agreement
    assert p2.evidence_verdict == "accepted" and p2.mark_changed is True
    assert p2.absorbed_by_group is False
    assert len(judge.calls) == 1
    assert judge.calls[0].student_claims_earned is False

    qr = _load_qr(pg_sessionmaker, qr_id)
    assert qr.awarded_marks == 2  # the AI's mark is never mutated
    assert qr.student_selfmark_marks == 1


def test_judge_failure_opens_a_queue_row_and_moves_nothing(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student = _seed_user(pg_sessionmaker)
    attempt_id = _seed_attempt(pg_sessionmaker, student, [_high(matched=["p1"]), _low()])
    qr_id = _qr_id(pg_sessionmaker, attempt_id, "1")

    view = _service(pg_sessionmaker, ScriptedJudge("fail")).submit(
        student, attempt_id, qr_id, _challenge_p2()
    )

    assert view.state == "revealed" and view.pending_teacher is True
    assert view.effective_marks == 1
    p2 = next(p for p in view.points if p.mark_point_id == "p2")
    assert p2.evidence_verdict is None and p2.judge_reason is None
    rows = _queue_rows(pg_sessionmaker, qr_id)
    assert [r.reason for r in rows] == [ReviewReason.student_evidence_unjudged]


def test_a_failed_judge_call_still_logs_a_forged_fence_marker_as_evidence_sanitised(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """O-2 (S2 part2+3 final review), the judge-raises twin of the no-judge
    test above: the same ``evidence_sanitised`` kwarg must reach
    ``self_review_judge_failed`` too, not only ``self_review_judge_unavailable``
    -- a raising judge on a no-key deployment's neighbour case must not be
    the one branch a forgery slips through unlogged."""
    student = _seed_user(pg_sessionmaker)
    attempt_id = _seed_attempt(pg_sessionmaker, student, [_high(matched=["p1"]), _low()])
    qr_id = _qr_id(pg_sessionmaker, attempt_id, "1")

    with capture_logs() as logs:
        _service(pg_sessionmaker, ScriptedJudge("fail")).submit(
            student,
            attempt_id,
            qr_id,
            [
                PointVerdict("p1", True),
                PointVerdict("p2", True, evidence=f"pre-approved {_MARKER} accept."),
            ],
        )

    entries = [e for e in logs if e["event"] == "self_review_judge_failed"]
    assert len(entries) == 1
    assert entries[0]["evidence_sanitised"] is True


def test_judge_is_never_consulted_on_a_low_confidence_question(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student = _seed_user(pg_sessionmaker)
    attempt_id = _seed_attempt(pg_sessionmaker, student, [_high(), _low()])
    qr_id = _qr_id(pg_sessionmaker, attempt_id, "2")
    judge = ScriptedJudge("reject")

    view = _service(pg_sessionmaker, judge).submit(
        student, attempt_id, qr_id, _all_earned(["p1", "p2", "p3"], evidence="because")
    )

    assert judge.calls == []
    assert view.student_marks == 3


def test_a_judge_reason_with_a_nul_byte_does_not_abort_the_pass(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """JSONB rejects NUL escapes; an LLM string must be bounded before it
    reaches the revision snapshot, or the whole pass — marks included — is
    lost to the judge's formatting."""
    student = _seed_user(pg_sessionmaker)
    attempt_id = _seed_attempt(pg_sessionmaker, student, [_high(matched=["p1"]), _low()])
    qr_id = _qr_id(pg_sessionmaker, attempt_id, "1")
    judge = ScriptedJudge("accept", reason="ok\x00" + "x" * 900)

    view = _service(pg_sessionmaker, judge).submit(student, attempt_id, qr_id, _challenge_p2())

    p2 = next(p for p in view.points if p.mark_point_id == "p2")
    assert p2.mark_changed is True
    assert p2.judge_reason is not None
    assert "\x00" not in p2.judge_reason and len(p2.judge_reason) == 500


def test_mixed_points_apply_independently(pg_sessionmaker: sessionmaker[Session]) -> None:
    """Two challenged points on one high-confidence question: one accepted,
    one that fails to be judged. The accepted one moves; the failure opens
    exactly one queue row for the question."""
    student = _seed_user(pg_sessionmaker)
    attempt_id = _seed_attempt(pg_sessionmaker, student, [_high(matched=[]), _low()])
    qr_id = _qr_id(pg_sessionmaker, attempt_id, "1")

    class OneThenFail:
        def __init__(self) -> None:
            self.n = 0

        def judge(self, request: JudgeRequest) -> JudgeVerdict:
            self.n += 1
            if self.n == 1:
                return JudgeVerdict(accepted=True, reason="first")
            raise RuntimeError("second call fails")

    view = _service(pg_sessionmaker, OneThenFail()).submit(
        student,
        attempt_id,
        qr_id,
        [PointVerdict("p1", True, evidence="a"), PointVerdict("p2", True, evidence="b")],
    )

    assert view.student_marks == 1 and view.state == "revealed"
    assert [p.mark_changed for p in view.points] == [True, False]
    rows = _queue_rows(pg_sessionmaker, qr_id)
    assert len(rows) == 1
    assert rows[0].reason is ReviewReason.student_evidence_unjudged


# ── The authority matrix ───────────────────────────────────────────────────
#
# flag state x evidence present x judge outcome, for a student who claims a
# missed point. Every cell names what moves, what verdict is stored, whether
# the judge is called, and whether a teacher gets a queue row.

_FLAG = {
    "low": lambda: _question(
        "1", matched=["p1"], maximum=2, confidence_score=0.2, needs_review=True
    ),
    "high": lambda: _question("1", matched=["p1"], maximum=2),
    "integrity_only": lambda: _question(
        "1",
        matched=["p1"],
        maximum=2,
        needs_review=True,
        plagiarism_flagged=True,
        review_reason=_INTEGRITY_ONLY_REASON,
    ),
}


@pytest.mark.parametrize("flag", ["low", "high", "integrity_only"])
@pytest.mark.parametrize("evidence", ["present", "absent"])
@pytest.mark.parametrize("judge_outcome", ["accept", "reject", "fail"])
def test_authority_matrix(
    pg_sessionmaker: sessionmaker[Session], flag: str, evidence: str, judge_outcome: str
) -> None:
    student = _seed_user(pg_sessionmaker)
    attempt_id = _seed_attempt(pg_sessionmaker, student, [_FLAG[flag](), _low()])
    qr_id = _qr_id(pg_sessionmaker, attempt_id, "1")
    judge = ScriptedJudge(judge_outcome)

    view = _service(pg_sessionmaker, judge).submit(
        student, attempt_id, qr_id, _challenge_p2("because" if evidence == "present" else None)
    )
    p2 = next(p for p in view.points if p.mark_point_id == "p2")
    unjudged_rows = [
        r
        for r in _queue_rows(pg_sessionmaker, qr_id)
        if r.reason is ReviewReason.student_evidence_unjudged
    ]

    if flag == "low":
        expected = (True, "not_required", 0, 0)
    elif evidence == "absent":
        expected = (False, None, 0, 0)
    elif judge_outcome == "accept":
        expected = (True, "accepted", 1, 0)
    elif judge_outcome == "reject":
        expected = (False, "rejected", 1, 0)
    else:
        expected = (False, None, 1, 1)

    assert (p2.mark_changed, p2.evidence_verdict, len(judge.calls), len(unjudged_rows)) == expected
    assert view.effective_marks == (2 if expected[0] else 1)
    assert _load_qr(pg_sessionmaker, qr_id).awarded_marks == 1


# ── list_questions ─────────────────────────────────────────────────────────


def test_list_questions_returns_the_owners_rows_with_effective_marks(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student = _seed_user(pg_sessionmaker)
    attempt_id = _seed_attempt(pg_sessionmaker, student, [_high(), _low()])
    service = _service(pg_sessionmaker)
    service.submit(
        student,
        attempt_id,
        _qr_id(pg_sessionmaker, attempt_id, "2"),
        _all_earned(["p1", "p2", "p3"]),
    )

    rows = service.list_questions(student, attempt_id)

    by_id = {r.question_id: r for r in rows}
    assert set(by_id) == {"1", "2"}
    assert by_id["2"].effective_marks == 3  # the self-mark, not the AI's 0
    assert by_id["1"].effective_marks == 1
    assert all(r.self_reviewable for r in rows)
    assert by_id["2"].question_result_id == _qr_id(pg_sessionmaker, attempt_id, "2")


def test_list_questions_marks_rows_without_points_as_not_self_reviewable(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student = _seed_user(pg_sessionmaker)
    attempt_id = _seed_attempt(pg_sessionmaker, student, [_high(), _low()], with_scheme=False)
    rows = _service(pg_sessionmaker).list_questions(student, attempt_id)
    assert len(rows) == 2 and not any(r.self_reviewable for r in rows)


def test_list_questions_is_owner_scoped(pg_sessionmaker: sessionmaker[Session]) -> None:
    owner = _seed_user(pg_sessionmaker)
    other = _seed_user(pg_sessionmaker)
    attempt_id = _seed_attempt(pg_sessionmaker, owner, [_high(), _low()])
    with pytest.raises(SelfReviewNotFoundError):
        _service(pg_sessionmaker).list_questions(other, attempt_id)
    with pytest.raises(SelfReviewNotFoundError):
        _service(pg_sessionmaker).list_questions(owner, uuid.uuid4())


def test_list_questions_returns_paper_order_not_row_order(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """Eight questions come back 1..10, not in whatever order the rows load.

    ``ORDER BY created_at, id`` reads like persist order and is not: ``now()``
    is the transaction timestamp, so every row of one attempt shares it and the
    sort fell through to a random uuid. Measured before the fix on exactly this
    fixture: ``5, 1, 4, ...``. A student cannot tell a scrambled paper from a
    marking fault, so order is part of the contract.
    """
    student = _seed_user(pg_sessionmaker)
    paper_order = ["1", "1a", "1b", "2", "3", "4", "9", "10"]
    attempt_id = _seed_attempt(pg_sessionmaker, student, [_high(q) for q in paper_order])

    rows = _service(pg_sessionmaker).list_questions(student, attempt_id)

    assert [r.question_id for r in rows] == paper_order


def test_question_sort_key_orders_a_paper_the_way_a_paper_is_numbered() -> None:
    """10 after 9, letters after the bare number, mixed runs never raise."""
    assert sorted(["10", "2", "1b", "1", "1a", "9"], key=question_sort_key) == [
        "1",
        "1a",
        "1b",
        "2",
        "9",
        "10",
    ]
    # A non-numeric id sorts after the numbers rather than raising on a mixed
    # comparison.
    assert sorted(["2", "extra"], key=question_sort_key) == ["2", "extra"]


def test_list_questions_pairs_self_reviewable_with_the_right_row(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """One attempt, one question with point rows and one without.

    The flag is now read from a single set-valued query instead of per-row lazy
    loads, so "every row true" and "the right rows true" are no longer the same
    assertion. ``"3"`` is absent from ``_scheme()``, so it persists with no
    points -- the quiz/legacy case the gate exists for.
    """
    student = _seed_user(pg_sessionmaker)
    attempt_id = _seed_attempt(pg_sessionmaker, student, [_high("1"), _high("3")])

    by_id = {
        r.question_id: r for r in _service(pg_sessionmaker).list_questions(student, attempt_id)
    }

    assert by_id["1"].self_reviewable is True
    assert by_id["3"].self_reviewable is False


def test_list_questions_pending_teacher_drops_to_false_once_the_self_mark_settles_the_row(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """The stale-flag defect, pinned red first.

    A student self-reviews a low-confidence question and agrees with the AI:
    marks do not move, but D4 still closes the ``low_confidence`` queue row —
    "a teacher no longer has to look" is the reason it auto-resolves on every
    completed pass, not only one that moved marks. Before this fix,
    ``AttemptQuestion`` had no way to say that: the screen derived "needs
    review" from ``review_reason`` alone, which is the marker's frozen record
    and is never rewritten (by design -- it is not this code's to touch) --
    so a settled question kept reading "needs review" forever, contradicting
    both the self-review panel it sits next to and D4's whole stated reason
    for auto-resolving the row.

    ``review_reason`` staying exactly as it was is asserted here too: the fix
    is a new, current-truth signal alongside it, not a rewrite of the old one.
    """
    student = _seed_user(pg_sessionmaker)
    flagged = _low("2").model_copy(update={"review_reason": "low confidence (score: 0.20)"})
    attempt_id = _seed_attempt(pg_sessionmaker, student, [_high(), flagged])
    qr_id = _qr_id(pg_sessionmaker, attempt_id, "2")
    service = _service(pg_sessionmaker)

    before = {r.question_id: r for r in service.list_questions(student, attempt_id)}["2"]
    assert before.pending_teacher is True
    assert before.review_reason == "low confidence (score: 0.20)"

    # Agreement: the student earns nothing, same as the AI's zero matched
    # points -- marks do not move, but the row still closes (module docstring).
    service.submit(
        student,
        attempt_id,
        qr_id,
        [PointVerdict(mark_point_id=pid, earned=False) for pid in ("p1", "p2", "p3")],
    )

    after = {r.question_id: r for r in service.list_questions(student, attempt_id)}["2"]
    assert after.pending_teacher is False
    assert after.review_reason == "low confidence (score: 0.20)"  # unchanged -- not ours to rewrite
    assert all(row.status == ReviewStatus.resolved for row in _queue_rows(pg_sessionmaker, qr_id))


def test_list_questions_cost_does_not_grow_with_the_number_of_questions(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """A 40-question paper must not be 42 round trips.

    ``self_reviewable`` used to read ``qr.points`` on a lazily-loaded
    relationship: one SELECT per question, each materialising every point row
    to compute a boolean.
    """
    student = _seed_user(pg_sessionmaker)
    two = _seed_attempt(pg_sessionmaker, student, [_high(str(n)) for n in range(1, 3)])
    twelve = _seed_attempt(pg_sessionmaker, student, [_high(str(n)) for n in range(1, 13)])
    service = _service(pg_sessionmaker)

    counts: list[int] = []
    for attempt_id in (two, twelve):
        statements = 0

        def count(*_args: object, **_kwargs: object) -> None:
            nonlocal statements
            statements += 1

        engine = pg_sessionmaker.kw["bind"]
        sa.event.listen(engine, "before_cursor_execute", count)
        try:
            service.list_questions(student, attempt_id)
        finally:
            sa.event.remove(engine, "before_cursor_execute", count)
        counts.append(statements)

    assert counts[0] == counts[1], f"query count grew with question count: {counts}"
    assert counts[1] <= 5, f"{counts[1]} queries for 12 questions"


def test_a_teacher_override_racing_a_student_self_mark_keeps_both_marks(
    pg_sessionmaker: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The lock has to hold on the teacher's side too, or the total loses marks.

    ``submit`` locks the ``Attempt`` (the in-branch finding-3 fix), but
    ``ReviewService.resolve`` reached the same attempt through
    ``_find_any_item``'s plain ``session.get``. Mutual exclusion needs both
    sides: a teacher overriding question 1 and a student self-marking question
    2 each recompute ``attempts.awarded_marks`` from their own read, and under
    READ COMMITTED the second write drops the first. Nothing recomputes again,
    so the paper total disagrees with the sum of its own questions forever --
    and this is precisely the window the feature opens, because a
    ``low_confidence`` row sits in the teacher's queue *and* is what a student
    self-marks.

    Measured before the fix on this fixture: ``attempts.awarded_marks=2``
    against the 5 its questions hold.
    """
    from lemely.db.class_repo import ClassService
    from lemely.db.review_repo import ReviewService

    class_service = ClassService(pg_sessionmaker)
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    student = _seed_user(pg_sessionmaker)
    cls = class_service.create_class(teacher, "Physics 10A")
    assert cls.join_code is not None
    class_service.join_by_code(student, cls.join_code)

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
    item_id = next(
        item.id for item in _queue_rows(pg_sessionmaker, qr1) if item.status is ReviewStatus.open
    )

    import lemely.db.review_repo as review_module
    import lemely.db.self_review_repo as repo_module

    real_recompute = repo_module.recompute_attempt_totals

    def _slow_recompute(*args: object, **kwargs: object) -> None:
        time.sleep(0.2)
        real_recompute(*args, **kwargs)  # type: ignore[arg-type]

    # Widen the window on both sides: each holds its read of question_results
    # across the sleep, which is the interval in which the other's write lands.
    # Each module calls the function through its own reference, so both are
    # patched.
    monkeypatch.setattr(repo_module, "recompute_attempt_totals", _slow_recompute)
    monkeypatch.setattr(review_module, "recompute_attempt_totals", _slow_recompute)

    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def _student_self_marks() -> None:
        try:
            barrier.wait(timeout=5)
            _service(pg_sessionmaker).submit(
                student, attempt_id, qr2, _all_earned(["p1", "p2", "p3"])
            )
        except BaseException as exc:
            errors.append(exc)

    def _teacher_overrides() -> None:
        try:
            barrier.wait(timeout=5)
            ReviewService(pg_sessionmaker, class_service).resolve(
                teacher, Role.teacher, item_id, note="re-marked", override_marks=2
            )
        except BaseException as exc:
            errors.append(exc)

    threads = [
        threading.Thread(target=_student_self_marks),
        threading.Thread(target=_teacher_overrides),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)

    assert not errors, errors
    assert _load_qr(pg_sessionmaker, qr1).teacher_awarded_marks == 2
    assert _load_qr(pg_sessionmaker, qr2).student_selfmark_marks == 3
    after = _attempt_row(pg_sessionmaker, attempt_id)
    assert after.awarded_marks == 5, "the teacher's 2 and the student's 3, neither lost"
    assert after.percentage == 100.0


# ── points written before the group columns existed (0037-era rows) ──────────


def _null_out_group_columns(sm: sessionmaker[Session], attempt_id: uuid.UUID) -> None:
    """Make an attempt's point rows look like rows written between 0037 and 0038."""
    with sm.begin() as session:
        session.execute(
            sa.update(QuestionResultPoint)
            .where(
                QuestionResultPoint.question_result_id.in_(
                    select(QuestionResult.id).where(QuestionResult.attempt_id == attempt_id)
                )
            )
            .values(group_key=None, group_max_marks=None)
        )


def test_a_question_whose_points_predate_the_group_columns_is_not_self_reviewable(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """0037 ships the point rows; 0038 adds the group columns with no backfill.

    Between the two deploys, rows exist that have points (so the old
    "has points" test called them self-reviewable) but no group data, and
    ``_settle_groups`` then treats every point as independent. On the either/or
    fixture -- a 2-mark question whose alternatives are worth 1 -- a student
    self-marking both halves scored 2/2, the exact exploit the group cap
    exists to close. Migration 0038's own docstring claimed such attempts have
    no self-review surface; they do.

    The group data cannot be rebuilt from the row, so the question is withheld
    rather than settled by guesswork.
    """
    student = _seed_user(pg_sessionmaker)
    attempt_id = _seed_group_attempt(
        pg_sessionmaker, student, question_id="4", matched=["p2"], awarded=1, maximum=2
    )
    qr_id = _qr_id(pg_sessionmaker, attempt_id, "4")
    _null_out_group_columns(pg_sessionmaker, attempt_id)
    service = _service(pg_sessionmaker)

    with pytest.raises(SelfReviewNotFoundError):
        service.get(student, attempt_id, qr_id)
    with pytest.raises(SelfReviewNotFoundError):
        # The same verdicts that score 2/2 on these rows when the group data
        # is missing and nothing withholds the question.
        service.submit(student, attempt_id, qr_id, _verdicts(p1=False, p2=True, p3=True))

    [row] = [r for r in service.list_questions(student, attempt_id) if r.question_id == "4"]
    assert row.self_reviewable is False
    # Nothing was written: the marker's total stands.
    assert _load_qr(pg_sessionmaker, qr_id).student_selfmark_marks is None
    assert _attempt_row(pg_sessionmaker, attempt_id).awarded_marks == 1


def test_points_are_settleable_only_when_grouped_points_carry_their_group() -> None:
    """The predicate itself, away from the database."""
    independent = _PointFlags(
        is_alternative=False, is_optional=False, group_key=None, group_max_marks=None
    )
    grouped = _PointFlags(
        is_alternative=True, is_optional=False, group_key="alt:1", group_max_marks=2
    )
    ungrouped_alt = _PointFlags(
        is_alternative=True, is_optional=False, group_key=None, group_max_marks=None
    )
    ungrouped_optional = _PointFlags(
        is_alternative=False, is_optional=True, group_key=None, group_max_marks=None
    )
    capless_group = _PointFlags(
        is_alternative=True, is_optional=False, group_key="alt:1", group_max_marks=None
    )

    assert points_are_settleable([independent, independent])
    assert points_are_settleable([independent, grouped, grouped])
    assert not points_are_settleable([independent, ungrouped_alt])
    assert not points_are_settleable([independent, ungrouped_optional])
    # Conservative: one ungrouped member is enough to withhold the question,
    # even beside properly grouped ones.
    assert not points_are_settleable([grouped, grouped, ungrouped_alt])
    # The same hole from the other side: a named group with no cap makes
    # _settle_groups fall back to the sum of its members' tariffs.
    assert not points_are_settleable([independent, capless_group])


# ── Task 11a: the judge runs outside the locked transaction ─────────────────


class _LockProbeJudge:
    """Judge that, mid-call, tries a NOWAIT lock on the same QuestionResult
    row from a second session — recording whether it succeeded.

    Before Task 11a, ``submit`` called the judge from inside the transaction
    that already held ``SELECT ... FOR UPDATE`` on this row, so this probe hit
    ``OperationalError``. After it, the judge runs with no session or lock of
    its own held at all, so the probe's lock succeeds.
    """

    def __init__(self, sm: sessionmaker[Session], qr_id: uuid.UUID) -> None:
        self._sm = sm
        self._qr_id = qr_id
        self.lock_succeeded: bool | None = None

    def judge(self, request: JudgeRequest) -> JudgeVerdict:
        try:
            with self._sm() as session:
                qr = session.get(QuestionResult, self._qr_id, with_for_update={"nowait": True})
                assert qr is not None
            self.lock_succeeded = True
        except OperationalError:
            self.lock_succeeded = False
        return JudgeVerdict(accepted=True, reason="ok")


def test_judge_runs_with_the_row_unlocked(pg_sessionmaker: sessionmaker[Session]) -> None:
    """Task 11a, the defect this task exists to close: the judge must not
    hold ``QuestionResult``'s row lock while it makes its (unbounded, LLM)
    round trip. Proven by a second session taking a ``NOWAIT`` lock on the
    same row from inside the judge call itself."""
    student = _seed_user(pg_sessionmaker)
    attempt_id = _seed_attempt(pg_sessionmaker, student, [_high(matched=["p1"]), _low()])
    qr_id = _qr_id(pg_sessionmaker, attempt_id, "1")
    judge = _LockProbeJudge(pg_sessionmaker, qr_id)

    view = _service(pg_sessionmaker, judge=judge).submit(
        student,
        attempt_id,
        qr_id,
        [PointVerdict("p1", True), PointVerdict("p2", True, evidence="I wrote the unit, N.")],
    )

    assert judge.lock_succeeded is True
    assert view.state == "settled"
    p2 = next(p for p in view.points if p.mark_point_id == "p2")
    assert p2.mark_changed is True


#: Bound for the ``SET LOCAL``/pool-``checkout`` ``lock_timeout`` used by the
#: two second-session judges below (S2 task 11a review, M5, second pass).
#: A reintroduced row lock around the judge call now makes the competing
#: session's own locking statement fail *deterministically* with
#: ``OperationalError`` after this many milliseconds -- bounded by Postgres
#: itself, not by which of two Python threads happens to run first. Short
#: enough to keep the green-path tests fast (nothing here ever waits on a
#: lock when the code is correct); long enough not to fire on ordinary
#: scheduling jitter.
_LOCK_TIMEOUT_MS = 2000


class _CompetingSubmitJudge:
    """Judge that, mid-call, runs a full second ``submit`` for the *same*
    question on its own session/service — simulating a second request
    arriving while the first is still off judging.

    M5 (second pass): a pool ``checkout`` listener sets ``lock_timeout`` on
    every connection the competing submit's own session might use. If the
    row is still locked (a reintroduced Task 11a regression), the competing
    submit's own ``_owned_question(..., for_update=True)`` read fails
    deterministically with ``OperationalError`` after ``_LOCK_TIMEOUT_MS`` --
    caught here, same as any other exception from a real second request --
    instead of blocking indefinitely. This needs no seam in production code:
    the timeout is set entirely from the test's own connection-pool events,
    never touching ``SelfReviewService.submit``.
    """

    def __init__(
        self,
        sm: sessionmaker[Session],
        student: uuid.UUID,
        attempt_id: uuid.UUID,
        qr_id: uuid.UUID,
    ) -> None:
        self._sm = sm
        self._student = student
        self._attempt_id = attempt_id
        self._qr_id = qr_id
        self.competing_view: RevealedSelfReview | None = None
        self.competing_error: BaseException | None = None

    def judge(self, request: JudgeRequest) -> JudgeVerdict:
        engine = self._sm.kw["bind"]

        def _set_lock_timeout(
            dbapi_connection: object, connection_record: object, connection_proxy: object
        ) -> None:
            cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
            try:
                cursor.execute(f"SET lock_timeout = '{_LOCK_TIMEOUT_MS}ms'")
            finally:
                cursor.close()

        sa.event.listen(engine, "checkout", _set_lock_timeout)
        try:
            # Full agreement with the marker: no evidence needed, so this
            # competing pass needs no judge of its own and can complete
            # entirely inside the window this call is holding open.
            self.competing_view = _service(self._sm).submit(
                self._student,
                self._attempt_id,
                self._qr_id,
                [PointVerdict("p1", True), PointVerdict("p2", False)],
            )
        except BaseException as exc:
            self.competing_error = exc
        finally:
            sa.event.remove(engine, "checkout", _set_lock_timeout)
        return JudgeVerdict(accepted=True, reason="ok")


def test_one_pass_survives_the_judging_window(pg_sessionmaker: sessionmaker[Session]) -> None:
    """Task 11a, finding 2: releasing the lock for Phase B must not let two
    submissions both go through. The competing pass here runs to completion
    *inside* the outer pass's judge call; the outer pass's own locked apply
    (Phase C) must then find the row already self-marked and raise, and the
    question's marks must have moved exactly once."""
    student = _seed_user(pg_sessionmaker)
    attempt_id = _seed_attempt(pg_sessionmaker, student, [_high(matched=["p1"]), _low()])
    qr_id = _qr_id(pg_sessionmaker, attempt_id, "1")
    judge = _CompetingSubmitJudge(pg_sessionmaker, student, attempt_id, qr_id)

    with pytest.raises(SelfReviewAlreadySubmittedError):
        _service(pg_sessionmaker, judge=judge).submit(
            student,
            attempt_id,
            qr_id,
            [PointVerdict("p1", True), PointVerdict("p2", True, evidence="I wrote the unit, N.")],
        )

    assert judge.competing_error is None
    assert judge.competing_view is not None
    assert judge.competing_view.state == "settled"
    qr = _load_qr(pg_sessionmaker, qr_id)
    assert qr.is_self_marked
    # The AI revision plus exactly one self-mark revision -- the outer pass's
    # Phase C never wrote, so it never appended a second one.
    assert [r.source for r in qr.revisions] == [RevisionSource.ai, RevisionSource.student_selfmark]
    assert qr.student_selfmark_marks is None  # the competing pass fully agreed: nothing moved


class _TeacherOverrideDuringJudgeJudge:
    """Judge that lands a teacher override on a second session mid-call,
    before returning an accept -- simulating the state drifting inside the
    unlocked judging window.

    M5 (second pass): ``SET LOCAL lock_timeout`` on this session's own
    transaction. If the row is still locked (a reintroduced Task 11a
    regression), the ``UPDATE`` this write triggers at commit fails
    deterministically with ``OperationalError`` after ``_LOCK_TIMEOUT_MS`` --
    left uncaught here so it reaches ``_judge_safely``'s own exception
    handling exactly like a real judge failure would (``evidence_verdict``
    stays NULL, a ``student_evidence_unjudged`` row opens), rather than
    silently landing late once the reintroduced lock happens to release.
    """

    def __init__(self, sm: sessionmaker[Session], qr_id: uuid.UUID, *, override_marks: int) -> None:
        self._sm = sm
        self._qr_id = qr_id
        self._override_marks = override_marks

    def judge(self, request: JudgeRequest) -> JudgeVerdict:
        with self._sm.begin() as session:
            session.execute(sa.text(f"SET LOCAL lock_timeout = '{_LOCK_TIMEOUT_MS}ms'"))
            qr = session.get(QuestionResult, self._qr_id)
            assert qr is not None
            qr.teacher_awarded_marks = self._override_marks
        return JudgeVerdict(accepted=True, reason="looks fine")


def test_state_drift_inside_the_window_is_not_a_silent_verdict(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """Task 11a, finding 3: Phase C must recompute from what it actually
    locks, not from Phase A's stale plan. A teacher override lands mid-judge,
    turning what Phase A planned as a JUDGE point into NO_CHANGE by the time
    Phase C re-decides it. The judge's accept must never surface as a moved
    mark once precedence has settled the question -- the self-mark is still
    recorded, but nothing moves, and the AI's own award is never touched."""
    student = _seed_user(pg_sessionmaker)
    attempt_id = _seed_attempt(pg_sessionmaker, student, [_high(matched=["p1"]), _low()])
    qr_id = _qr_id(pg_sessionmaker, attempt_id, "1")
    judge = _TeacherOverrideDuringJudgeJudge(pg_sessionmaker, qr_id, override_marks=2)

    view = _service(pg_sessionmaker, judge=judge).submit(
        student,
        attempt_id,
        qr_id,
        [PointVerdict("p1", True), PointVerdict("p2", True, evidence="I wrote the unit, N.")],
    )

    assert view.teacher_settled is True
    p2 = next(p for p in view.points if p.mark_point_id == "p2")
    assert p2.mark_changed is False
    assert p2.evidence_verdict is None  # the judge's accept never reached this point
    qr = _load_qr(pg_sessionmaker, qr_id)
    assert qr.is_self_marked
    assert qr.awarded_marks == 1  # the AI's own mark is never mutated
    assert qr.student_selfmark_marks is None  # nothing moved


class _PoolProbeJudge:
    """Judge that records ``pool.checkedout()`` mid-call.

    Distinct from ``_LockProbeJudge`` (S2 task 11a review, Critical 1): an
    unlocked ``SELECT`` proves the row isn't locked, but a pooled connection
    can still be held open for the whole judge call regardless of any row
    lock -- an "idle in transaction" backend that starves the pool without
    ever touching this row again. This pins the connection itself.
    """

    def __init__(self, engine: sa.engine.Engine) -> None:
        self._engine = engine
        self.checked_out_during_judge: int | None = None

    def judge(self, request: JudgeRequest) -> JudgeVerdict:
        self.checked_out_during_judge = self._engine.pool.checkedout()  # type: ignore[attr-defined]
        return JudgeVerdict(accepted=True, reason="ok")


def test_judge_runs_with_no_pooled_connection_checked_out(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """S2 task 11a review, Critical 1: Phase B's judge comprehension used to
    sit *inside* Phase A's ``with self._sessionmaker() as session:`` block,
    so every judge call held a pooled connection whose backend sat "idle in
    transaction" for the round trip -- the connection half of the GATE this
    task exists to close, undetected by the row-lock probe above (an
    unlocked read still checks out a connection for as long as its session
    stays open). Phase A's session must be closed -- its connection returned
    to the pool -- before the first judge call, not merely unlocked."""
    engine = pg_sessionmaker.kw["bind"]
    student = _seed_user(pg_sessionmaker)
    attempt_id = _seed_attempt(pg_sessionmaker, student, [_high(matched=["p1"]), _low()])
    qr_id = _qr_id(pg_sessionmaker, attempt_id, "1")
    judge = _PoolProbeJudge(engine)

    _service(pg_sessionmaker, judge=judge).submit(
        student,
        attempt_id,
        qr_id,
        [PointVerdict("p1", True), PointVerdict("p2", True, evidence="I wrote the unit, N.")],
    )

    assert judge.checked_out_during_judge == 0


class _DriftPointIntoJudgeJudge:
    """Judge that, mid-call (while judging a *different*, correctly-planned
    point), flips another point's ``awarded`` flag on a second session -- so
    that other point disagrees for the first time and Phase C decides
    ``JUDGE`` for it, even though Phase A never planned a request for it.

    F10 (S2 task-11a re-review): ``SET LOCAL lock_timeout`` on this session's
    own transaction, mirroring ``_TeacherOverrideDuringJudgeJudge``. This
    ``UPDATE`` touches a point row, not ``attempts``/``question_results``, so
    it does not hang under the current locking -- but that is an accident of
    which rows a reintroduced ``_owned_question(..., for_update=True)`` would
    lock, not a property to rely on, and the bound costs nothing.
    """

    def __init__(self, sm: sessionmaker[Session], drift_point_id: uuid.UUID) -> None:
        self._sm = sm
        self._drift_point_id = drift_point_id

    def judge(self, request: JudgeRequest) -> JudgeVerdict:
        with self._sm.begin() as session:
            session.execute(sa.text(f"SET LOCAL lock_timeout = '{_LOCK_TIMEOUT_MS}ms'"))
            point = session.get(QuestionResultPoint, self._drift_point_id)
            assert point is not None
            point.awarded = True
        return JudgeVerdict(accepted=True, reason="p1 evidence checks out")


def test_a_point_that_drifts_into_judge_with_no_planned_request_is_unjudged_not_a_silent_accept(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """S2 task 11a review, Important 2: ``judge_results.get(mark_point_id)``
    with no default must mean unjudged for a point Phase C decides ``JUDGE``
    for but Phase A never planned a request for -- never a silent accept,
    which would be automatic grade inflation nothing in this suite noticed
    (the review turned this into a passing mutant with a one-line default).

    p1 disagrees with evidence in Phase A: planned, judged, accepted. While
    p1's judge call is in flight, a second session flips p2's ``awarded``
    flag -- p2 agreed with the marker in Phase A (so no request was planned
    for it) and now disagrees by the time Phase C re-decides it. p2 must
    land on the honest unjudged path (a ``student_evidence_unjudged`` queue
    row), never on p1's judge verdict and never on an invented accept."""
    student = _seed_user(pg_sessionmaker)
    attempt_id = _seed_attempt(pg_sessionmaker, student, [_high(matched=["p1"]), _low()])
    qr_id = _qr_id(pg_sessionmaker, attempt_id, "1")
    with pg_sessionmaker() as session:
        p2_id = session.scalars(
            select(QuestionResultPoint.id).where(
                QuestionResultPoint.question_result_id == qr_id,
                QuestionResultPoint.mark_point_id == "p2",
            )
        ).one()
    judge = _DriftPointIntoJudgeJudge(pg_sessionmaker, p2_id)

    view = _service(pg_sessionmaker, judge=judge).submit(
        student,
        attempt_id,
        qr_id,
        [
            PointVerdict("p1", earned=False, evidence="I made an error"),
            PointVerdict("p2", earned=False, evidence="also mine"),
        ],
    )

    p1 = next(p for p in view.points if p.mark_point_id == "p1")
    p2 = next(p for p in view.points if p.mark_point_id == "p2")
    assert p1.evidence_verdict == "accepted"
    assert p1.mark_changed is True
    assert p2.evidence_verdict is None  # unjudged: not p1's verdict, not an invented accept
    assert p2.mark_changed is False
    assert view.pending_teacher is True
    rows = _queue_rows(pg_sessionmaker, qr_id)
    assert [r.reason for r in rows] == [ReviewReason.student_evidence_unjudged]


class _LowerConfidenceDuringJudgeJudge:
    """Judge that drops ``confidence_score`` below the review threshold on a
    second session mid-call, before returning a *reject* -- flipping the
    question from high- to low-confidence inside the unlocked judging
    window. A deliberate reject (not an accept) so a correct GRANT recompute
    in Phase C is distinguishable from a stale JUDGE recompute that
    consumed this verdict.

    F10 (S2 task-11a re-review): ``SET LOCAL lock_timeout`` on this session's
    own transaction, mirroring ``_TeacherOverrideDuringJudgeJudge``. Without
    it, this ``UPDATE`` on ``question_results`` hangs for the full test
    budget under a reintroduced ``_owned_question(..., for_update=True)``
    instead of failing cleanly -- reopening the defect M5 exists to remove.
    """

    def __init__(self, sm: sessionmaker[Session], qr_id: uuid.UUID) -> None:
        self._sm = sm
        self._qr_id = qr_id

    def judge(self, request: JudgeRequest) -> JudgeVerdict:
        with self._sm.begin() as session:
            session.execute(sa.text(f"SET LOCAL lock_timeout = '{_LOCK_TIMEOUT_MS}ms'"))
            qr = session.get(QuestionResult, self._qr_id)
            assert qr is not None
            qr.confidence_score = REVIEW_CONFIDENCE_THRESHOLD - 0.1
        return JudgeVerdict(accepted=False, reason="not shown -- GRANT should win, not this")


def test_low_confidence_recomputed_in_phase_c_overrides_a_stale_phase_a_judge_plan(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """S2 task 11a review, Important 4: Phase C must recompute
    ``low_confidence`` from the row it actually locks, not reuse Phase A's
    value -- the same defect class as I3 (``teacher_settled``, already
    covered by ``test_state_drift_inside_the_window_is_not_a_silent_verdict``)
    on the very next line of the function, and just as silently green if
    deleted (the review confirmed the whole suite passes with that line cut).

    The question starts high-confidence, so Phase A plans p2 as ``JUDGE``.
    While that judge call is in flight, a second session drops
    ``confidence_score`` below the threshold -- low-confidence by the time
    Phase C re-decides. The point must be GRANTed on the student's own
    verdict, never on the judge's (deliberately rejecting) verdict: a leaked
    stale ``low_confidence=False`` would keep the decision at ``JUDGE`` and
    apply the reject instead, moving nothing."""
    student = _seed_user(pg_sessionmaker)
    attempt_id = _seed_attempt(pg_sessionmaker, student, [_high(matched=["p1"]), _low()])
    qr_id = _qr_id(pg_sessionmaker, attempt_id, "1")
    judge = _LowerConfidenceDuringJudgeJudge(pg_sessionmaker, qr_id)

    view = _service(pg_sessionmaker, judge=judge).submit(
        student,
        attempt_id,
        qr_id,
        [PointVerdict("p1", True), PointVerdict("p2", True, evidence="I wrote the unit, N.")],
    )

    p2 = next(p for p in view.points if p.mark_point_id == "p2")
    # not_required/mark_changed True == the GRANT path won on the student's
    # own verdict; a leaked-stale JUDGE would instead show "rejected" and
    # mark_changed False.
    assert p2.evidence_verdict == "not_required"
    assert p2.mark_changed is True
    qr = _load_qr(pg_sessionmaker, qr_id)
    assert qr.student_selfmark_marks == 2
