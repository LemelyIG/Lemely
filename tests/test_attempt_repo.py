"""Postgres-integration tests for :class:`AttemptRepository` (P2.1).

Throwaway-DB tests that skip cleanly when no local Postgres is reachable
(mirrors ``test_history_repo_parity.py``). They assert the full-report mapping:
one attempt, per-question results, weakness records, and a review-queue row for
every question flagged for review — and that the totals-only ``DbHistoryStore``
still coexists on the same tables.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.core.analytics import summarize_weaknesses
from lemely.core.history import PaperRecord
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
    SourceBox,
    WeakArea,
    WeaknessReport,
)
from lemely.db.attempt_repo import (
    AttemptRepository,
    _integrity_flagged,
    fill_correction_topics,
    is_marking_low_confidence,
)
from lemely.db.base import Base
from lemely.db.history_repo import DbHistoryStore
from lemely.db.models import User
from lemely.db.models.attempts import (
    Attempt,
    QuestionResult,
    QuestionResultPoint,
    QuestionResultRevision,
    WeaknessRecord,
)
from lemely.db.models.enums import (
    BoundarySource,
    MarkerSource,
    ReviewReason,
    ReviewStatus,
    RevisionSource,
    Role,
)
from lemely.db.models.enums import ConfidenceBand as DBConfidenceBand
from lemely.db.models.ops import ReviewQueueItem
from lemely.db.review_queue_rules import low_confidence_review_needed
from lemely.io.correction_ai import (
    _BLANK_ANSWER_REVIEW_REASON,
    _DROPPED_ANSWER_REVIEW_REASON,
)
from lemely.runtime.config import DatabaseSettings
from tests.conftest import _scheme

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


def _seed_user(sm: sessionmaker[Session], role: Role = Role.student) -> str:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=role))
    return str(uid)


def _report() -> AccuracyReport:
    """A mixed report: one HIGH-confidence pass, one LOW-confidence flag."""
    metadata = ExamMetadata(
        subject_code="0625",
        paper_number=1,
        paper_variant=2,
        session_month="May/June",
        session_year=2020,
    )
    high = CorrectedQuestion(
        question_id="1",
        awarded_marks=1,
        maximum_marks=1,
        confidence=ConfidenceBand.HIGH,
        confidence_score=1.0,
        needs_teacher_review=False,
        student_answer="A",
        expected_answer="A",
        topic="Waves",
        marker_source="deterministic",
        matched_point_ids=["p1"],
    )
    low = CorrectedQuestion(
        question_id="2",
        awarded_marks=0,
        maximum_marks=2,
        confidence=ConfidenceBand.LOW,
        confidence_score=0.3,
        needs_teacher_review=True,
        student_answer="",
        expected_answer=None,
        topic="Forces",
        review_reason="missing answer",
        marker_source="ai",
        feedback="No working shown.",
        matched_point_ids=[],
    )
    correction = CorrectionResult(metadata=metadata, questions=[high, low])
    weaknesses = WeaknessReport(
        weak_areas=[
            WeakArea(
                topic="Forces",
                lost_marks=2,
                maximum_marks=2,
                accuracy=0.0,
                question_ids=["2"],
            ),
            WeakArea(
                topic="Waves",
                lost_marks=0,
                maximum_marks=1,
                accuracy=1.0,
                question_ids=["1"],
            ),
        ]
    )
    prediction = GradePrediction(
        awarded_marks=1,
        maximum_marks=3,
        percentage=33.33,
        grade="U",
        confidence=ConfidenceBand.LOW,
        needs_teacher_review=True,
        boundary_source="subject_default",
    )
    return AccuracyReport(correction=correction, weaknesses=weaknesses, grade_prediction=prediction)


def test_persist_correction_writes_one_attempt(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    user_id = _seed_user(pg_sessionmaker)
    repo = AttemptRepository(pg_sessionmaker)

    attempt_id = repo.persist_correction(user_id=user_id, report=_report())
    assert isinstance(attempt_id, uuid.UUID)

    with pg_sessionmaker() as session:
        attempts = session.scalars(select(Attempt)).all()
        assert len(attempts) == 1
        attempt = attempts[0]
        assert attempt.id == attempt_id
        assert attempt.subject_code == "0625"
        assert attempt.grade == "U"
        assert attempt.predicted_grade == "U"
        assert attempt.boundary_source == BoundarySource.subject_default
        assert attempt.confidence_band == DBConfidenceBand.low
        # needs_teacher_review is True because at least one question was flagged.
        assert attempt.needs_teacher_review is True


def test_persist_correction_maps_question_results(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    user_id = _seed_user(pg_sessionmaker)
    AttemptRepository(pg_sessionmaker).persist_correction(user_id=user_id, report=_report())

    with pg_sessionmaker() as session:
        results = session.scalars(select(QuestionResult).order_by(QuestionResult.question_id)).all()
        assert len(results) == 2
        first, second = results
        assert first.question_id == "1"
        assert first.confidence_band == DBConfidenceBand.high
        assert first.marker_source == MarkerSource.deterministic
        assert first.matched_point_ids == ["p1"]
        assert second.question_id == "2"
        assert second.confidence_band == DBConfidenceBand.low
        assert second.marker_source == MarkerSource.ai
        assert second.matched_point_ids == []


def test_persist_correction_round_trips_dropped_marker_source(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """US-038: ``marker_source="dropped"`` must survive persistence unchanged.

    Before this migration, ``MarkerSource`` (the native Postgres enum) had
    only ``deterministic``/``ai``/``missing``, so ``_to_question_result``
    mapped ``"dropped"`` onto ``MarkerSource.missing`` -- an answer the model
    returned and extraction discarded as malformed became indistinguishable,
    on read-back, from one never attempted. That mapping is now gone: the
    fourth enum member round-trips like the other three.
    """
    user_id = _seed_user(pg_sessionmaker)
    dropped = CorrectedQuestion(
        question_id="3",
        awarded_marks=0,
        maximum_marks=1,
        confidence=ConfidenceBand.LOW,
        confidence_score=0.0,
        needs_teacher_review=True,
        student_answer=None,
        expected_answer="A",
        topic="Waves",
        review_reason="answer discarded as malformed",
        marker_source="dropped",
        matched_point_ids=[],
    )
    report = _report()
    report.correction.questions.append(dropped)
    AttemptRepository(pg_sessionmaker).persist_correction(user_id=user_id, report=report)

    with pg_sessionmaker() as session:
        result = session.scalars(
            select(QuestionResult).where(QuestionResult.question_id == "3")
        ).one()
        assert result.marker_source == MarkerSource.dropped


def test_persist_correction_writes_weakness_records(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    user_id = _seed_user(pg_sessionmaker)
    attempt_id = AttemptRepository(pg_sessionmaker).persist_correction(
        user_id=user_id, report=_report()
    )

    with pg_sessionmaker() as session:
        records = session.scalars(select(WeaknessRecord)).all()
        assert len(records) == 2
        assert all(r.attempt_id == attempt_id for r in records)
        assert {r.topic for r in records} == {"Forces", "Waves"}


def test_review_queue_only_for_flagged_questions(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    user_id = _seed_user(pg_sessionmaker)
    attempt_id = AttemptRepository(pg_sessionmaker).persist_correction(
        user_id=user_id, report=_report()
    )

    with pg_sessionmaker() as session:
        items = session.scalars(select(ReviewQueueItem)).all()
        # Only the LOW-confidence, review-flagged question (id "2") queues.
        assert len(items) == 1
        item = items[0]
        assert item.attempt_id == attempt_id
        assert item.reason.value == "low_confidence"
        flagged = session.get(QuestionResult, item.question_result_id)
        assert flagged is not None
        assert flagged.question_id == "2"


def test_review_queue_exempts_the_us039_unflagged_blank(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """US-039 MUST-FIX 1 (independent review, blocking 674f309d).

    ``_build_blank_corrected`` sets ``confidence_score=0.0`` *and*
    ``needs_teacher_review=False`` -- the second disjunct at
    ``attempt_repo.py``'s review-queue fan-out
    (``qr.confidence_score < REVIEW_CONFIDENCE_THRESHOLD``) used to fire
    unconditionally for it regardless of the first, so every blank still
    entered the review queue despite the product owner's explicit "unflagged
    zero, no queue item" ruling. A paper with 8 unattempted parts produced 8
    queue items a teacher dismisses on sight -- exactly the scenario the
    ruling rejected.

    The exemption is narrow: since task #36 it keys off
    ``marker_source == "blank"`` and nothing else -- see
    ``test_review_queue_still_queues_genuine_missing_and_dropped`` for the two
    look-alike builders that must keep queuing unaffected by it. The blank
    ``review_reason`` is still set on the fixture because the real builder sets
    it, but it is deliberately no longer what the exemption reads: that
    ``" | "``-split substring search over prose is the thing task #36 removed,
    and this test would go green either way, so the narrowness proof lives in
    the sibling test below and in
    ``test_a_missing_row_carrying_the_blank_prose_is_not_exempt``.
    """
    from lemely.io.correction_ai import _BLANK_ANSWER_REVIEW_REASON

    user_id = _seed_user(pg_sessionmaker)
    report = _report()
    blank = CorrectedQuestion(
        question_id="3",
        awarded_marks=0,
        maximum_marks=1,
        confidence=ConfidenceBand.LOW,
        confidence_score=0.0,
        needs_teacher_review=False,
        student_answer=None,
        expected_answer=None,
        topic="Waves",
        review_reason=_BLANK_ANSWER_REVIEW_REASON,
        marker_source="blank",
        matched_point_ids=[],
    )
    report.correction.questions.append(blank)
    AttemptRepository(pg_sessionmaker).persist_correction(user_id=user_id, report=report)

    with pg_sessionmaker() as session:
        items = session.scalars(select(ReviewQueueItem)).all()
        queued_question_ids = set()
        for item in items:
            flagged = session.get(QuestionResult, item.question_result_id)
            assert flagged is not None
            queued_question_ids.add(flagged.question_id)
        # Question "2" (genuinely low-confidence) still queues; the new
        # unflagged blank ("3") must NOT.
        assert queued_question_ids == {"2"}


def test_review_queue_still_queues_genuine_missing_and_dropped(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """The MUST-FIX 1 exemption must not leak onto ``_build_missing_corrected``'s
    and ``_build_dropped_corrected``'s output.

    These fixtures deliberately set ``needs_teacher_review=False`` --
    UNLIKE the real builders, which always set it True -- so that each
    question here reaches the queue via ONLY the confidence-score disjunct
    (``low_confidence_flagged``), never via ``marking_flagged``. That isolates
    the exemption's own gate: both fixtures are blank look-alikes on every
    field EXCEPT ``marker_source`` (``confidence_score == 0.0``, the real
    ``review_reason`` literal from their own builder), so the only thing that
    can legitimately keep them out of the queue is the exemption keying on
    ``marker_source == "blank"``. Widen it to
    ``not marker_scored(marker_source)`` and both disappear from the queue and
    this fails -- which is exactly the mutation task #36's one-formulation
    refactor makes easy to write by accident, since that predicate is now
    sitting right there and answers a *different* question.
    """
    from lemely.io.correction_ai import _DROPPED_ANSWER_REVIEW_REASON

    user_id = _seed_user(pg_sessionmaker)
    report = _report()
    missing = CorrectedQuestion(
        question_id="3",
        awarded_marks=0,
        maximum_marks=1,
        confidence=ConfidenceBand.LOW,
        confidence_score=0.0,
        needs_teacher_review=False,
        student_answer=None,
        expected_answer=None,
        topic="Waves",
        review_reason="non-MCQ question not marked (--mcq-only or no AI client)",
        marker_source="missing",
        matched_point_ids=[],
    )
    dropped = CorrectedQuestion(
        question_id="4",
        awarded_marks=0,
        maximum_marks=1,
        confidence=ConfidenceBand.LOW,
        confidence_score=0.0,
        needs_teacher_review=False,
        student_answer=None,
        expected_answer="A",
        topic="Waves",
        review_reason=_DROPPED_ANSWER_REVIEW_REASON,
        marker_source="dropped",
        matched_point_ids=[],
    )
    report.correction.questions.extend([missing, dropped])
    AttemptRepository(pg_sessionmaker).persist_correction(user_id=user_id, report=report)

    with pg_sessionmaker() as session:
        items = session.scalars(select(ReviewQueueItem)).all()
        queued_question_ids = set()
        for item in items:
            flagged = session.get(QuestionResult, item.question_result_id)
            assert flagged is not None
            queued_question_ids.add(flagged.question_id)
        assert queued_question_ids == {"2", "3", "4"}


def _report_with_integrity_flags() -> AccuracyReport:
    """One HIGH-confidence question flagged for plagiarism.

    ``needs_teacher_review`` is True purely because ``apply_integrity_checks``
    set it (confidence_score is 1.0, well above the review threshold, and
    there is no marking-side out-of-range/value-mismatch signal either) — so
    ``persist_correction`` must NOT also queue a ``low_confidence`` row for
    this question; that would misleadingly label a fully-confident mark as
    low-confidence. Only the integrity-specific row should appear. (F4
    removed the AI-generated-answer flag this fixture used to also set.)
    """
    metadata = ExamMetadata(
        subject_code="0625",
        paper_number=1,
        paper_variant=2,
        session_month="May/June",
        session_year=2020,
    )
    flagged = CorrectedQuestion(
        question_id="1",
        awarded_marks=1,
        maximum_marks=1,
        confidence=ConfidenceBand.HIGH,
        confidence_score=1.0,
        needs_teacher_review=True,
        student_answer="A",
        expected_answer="A",
        topic="Waves",
        review_reason="plagiarism (score 0.95)",
        marker_source="deterministic",
        matched_point_ids=["p1"],
        plagiarism_flagged=True,
    )
    correction = CorrectionResult(metadata=metadata, questions=[flagged])
    prediction = GradePrediction(
        awarded_marks=1,
        maximum_marks=1,
        percentage=100.0,
        grade="A",
        confidence=ConfidenceBand.HIGH,
        needs_teacher_review=True,
        boundary_source="subject_default",
    )
    return AccuracyReport(
        correction=correction,
        weaknesses=WeaknessReport(weak_areas=[]),
        grade_prediction=prediction,
    )


def test_review_queue_includes_integrity_flag_rows(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    user_id = _seed_user(pg_sessionmaker)
    attempt_id = AttemptRepository(pg_sessionmaker).persist_correction(
        user_id=user_id, report=_report_with_integrity_flags()
    )

    with pg_sessionmaker() as session:
        items = session.scalars(select(ReviewQueueItem)).all()
        reasons = {item.reason for item in items}
        # NOT low_confidence: confidence_score is 1.0 and there is no marking-side
        # out-of-range/value-mismatch signal, so needs_teacher_review is True purely
        # from the integrity flag, which already has its own row below.
        assert reasons == {ReviewReason.plagiarism_flag}
        assert all(item.attempt_id == attempt_id for item in items)
        question_result_ids = {item.question_result_id for item in items}
        assert len(question_result_ids) == 1


def test_review_queue_low_confidence_row_survives_alongside_integrity_flags(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """A genuinely low-confidence question that is ALSO integrity-flagged still
    gets its own low_confidence row — the fix that stops a high-confidence,
    purely-integrity-flagged question from getting a spurious low_confidence
    row must not suppress a real low-confidence signal when the two coincide.
    """
    metadata = ExamMetadata(
        subject_code="0625",
        paper_number=1,
        paper_variant=2,
        session_month="May/June",
        session_year=2020,
    )
    flagged = CorrectedQuestion(
        question_id="1",
        awarded_marks=0,
        maximum_marks=1,
        confidence=ConfidenceBand.LOW,
        confidence_score=0.5,
        needs_teacher_review=True,
        student_answer="A",
        expected_answer="A",
        topic="Waves",
        review_reason="confidence 0.50 below review threshold 0.90 | plagiarism (score 0.95)",
        marker_source="deterministic",
        matched_point_ids=["p1"],
        plagiarism_flagged=True,
    )
    correction = CorrectionResult(metadata=metadata, questions=[flagged])
    prediction = GradePrediction(
        awarded_marks=0,
        maximum_marks=1,
        percentage=0.0,
        grade="U",
        confidence=ConfidenceBand.LOW,
        needs_teacher_review=True,
        boundary_source="subject_default",
    )
    report = AccuracyReport(
        correction=correction,
        weaknesses=WeaknessReport(weak_areas=[]),
        grade_prediction=prediction,
    )

    user_id = _seed_user(pg_sessionmaker)
    attempt_id = AttemptRepository(pg_sessionmaker).persist_correction(
        user_id=user_id, report=report
    )

    with pg_sessionmaker() as session:
        items = session.scalars(select(ReviewQueueItem)).all()
        reasons = {item.reason for item in items}
        assert reasons == {ReviewReason.low_confidence, ReviewReason.plagiarism_flag}
        assert all(item.attempt_id == attempt_id for item in items)


def _real_plagiarism_review_reason() -> str:
    """The exact ``review_reason`` segment ``apply_integrity_checks`` appends for a flagged answer.

    Derived by running the REAL integrity-check pipeline
    (``lemely.io.integrity.apply_integrity_checks``) against a
    verbatim-copied answer -- not retyped or invented -- so a fixture built
    from this cannot silently drift from what the real producer actually
    appends (``lemely/io/integrity.py:102``,
    ``f"plagiarism (score {finding.score:.2f})"``).

    (Independent review, third pass: an earlier version of this test's
    fixture hand-typed ``"copied from another candidate"`` as the appended
    reason -- a string no builder in this codebase produces, exactly the
    defect class ``129297cc`` removed elsewhere in this same file. This
    function exists so that mistake cannot recur here.)
    """
    from lemely.io.integrity import apply_integrity_checks
    from lemely.runtime.config import IntegritySettings

    verbatim = "gravity acts on the object"
    scheme = _mark_scheme([_scheme_question("1", point_text=verbatim)])
    near_verbatim = CorrectedQuestion(
        question_id="1",
        awarded_marks=1,
        maximum_marks=1,
        confidence=ConfidenceBand.HIGH,
        confidence_score=0.95,
        needs_teacher_review=False,
        student_answer=verbatim,
        expected_answer=verbatim,
        marker_source="ai",
    )
    correction = CorrectionResult(
        metadata=ExamMetadata(
            subject_code="0625",
            paper_number=1,
            paper_variant=2,
            session_month="May/June",
            session_year=2020,
        ),
        questions=[near_verbatim],
    )
    result = apply_integrity_checks(
        correction, scheme, gemini_client=None, settings=IntegritySettings()
    )
    flagged = result.questions[0]
    assert flagged.plagiarism_flagged is True
    assert flagged.review_reason is not None
    return flagged.review_reason


def test_review_queue_blank_with_integrity_flag_queues_plagiarism_only(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """Second independent review of the US-039 blank exemption, round 2.

    ``apply_integrity_checks`` (``lemely/io/integrity.py``) APPENDS to
    ``review_reason`` rather than replacing it (its own docstring: "appended
    to (preserving any existing text)") whenever it flags a question, and it
    forces ``needs_teacher_review`` True. Both of those used to be able to
    defeat the blank exemption, in two successive ways: first a whole-field
    ``review_reason == _BLANK_ANSWER_REVIEW_REASON`` equality test, then a
    ``" | "``-split membership test that had to be gated on
    ``plagiarism_flagged`` so a literal collision could not silence a real
    marking reason. Task #36 removed the prose from the question entirely: the
    exemption is ``marker_source == "blank"``, which no appended text and no
    collision can reach. The invariant this test pins is unchanged and is what
    matters -- a flagged blank queues for the real reason it was flagged
    (plagiarism) and ONLY that reason, not a fabricated low-confidence signal
    alongside it for a marker that never ran.

    (In today's pipeline this exact combination cannot arise via
    ``correct_paper``: ``_build_blank_corrected`` sets both
    ``student_answer`` and ``expected_answer`` to ``None``, and
    ``apply_integrity_checks``'s plagiarism check requires both truthy
    before it runs. This test constructs the ``CorrectedQuestion`` directly,
    the same way ``test_review_queue_low_confidence_row_survives_alongside_integrity_flags``
    above does, because the predicate's contract must hold for any
    question shaped this way, not merely for what today's one caller
    happens to produce -- but the APPENDED text itself is derived from a
    real run of the integrity pipeline, not invented, so this test cannot
    silently drift from what that pipeline actually produces.)
    """
    from lemely.io.correction_ai import _BLANK_ANSWER_REVIEW_REASON

    metadata = ExamMetadata(
        subject_code="0625",
        paper_number=1,
        paper_variant=2,
        session_month="May/June",
        session_year=2020,
    )
    flagged_blank = CorrectedQuestion(
        question_id="1",
        awarded_marks=0,
        maximum_marks=1,
        confidence=ConfidenceBand.LOW,
        confidence_score=0.0,
        needs_teacher_review=True,
        student_answer=None,
        expected_answer=None,
        topic="Waves",
        review_reason=f"{_BLANK_ANSWER_REVIEW_REASON} | {_real_plagiarism_review_reason()}",
        marker_source="blank",
        plagiarism_flagged=True,
        matched_point_ids=[],
    )
    correction = CorrectionResult(metadata=metadata, questions=[flagged_blank])
    prediction = GradePrediction(
        awarded_marks=0,
        maximum_marks=1,
        percentage=0.0,
        grade="U",
        confidence=ConfidenceBand.LOW,
        needs_teacher_review=True,
        boundary_source="subject_default",
    )
    report = AccuracyReport(
        correction=correction,
        weaknesses=WeaknessReport(weak_areas=[]),
        grade_prediction=prediction,
    )

    user_id = _seed_user(pg_sessionmaker)
    attempt_id = AttemptRepository(pg_sessionmaker).persist_correction(
        user_id=user_id, report=report
    )

    with pg_sessionmaker() as session:
        items = session.scalars(select(ReviewQueueItem)).all()
        reasons = {item.reason for item in items}
        # ONLY plagiarism_flag -- no fabricated low_confidence row for a
        # marker that never ran.
        assert reasons == {ReviewReason.plagiarism_flag}
        assert all(item.attempt_id == attempt_id for item in items)


def test_coexists_with_db_history_store(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    user_id = _seed_user(pg_sessionmaker)
    # A separate PaperRecord written via the totals-only history store.
    history = DbHistoryStore(pg_sessionmaker)
    history.append(
        user_id,
        PaperRecord(
            student_id=user_id,
            metadata=ExamMetadata(
                subject_code="0625",
                paper_number=2,
                paper_variant=1,
                session_month="Oct/Nov",
                session_year=2021,
            ),
            awarded_marks=40,
            maximum_marks=50,
            percentage=80.0,
            grade="A",
            weak_areas=[],
            recorded_at="2026-01-01T00:00:00+00:00",
        ),
    )
    AttemptRepository(pg_sessionmaker).persist_correction(user_id=user_id, report=_report())

    # The history store sees BOTH attempts (its own record + the repo's).
    assert len(history.load(user_id).records) == 2


# ---------------------------------------------------------------------------
# fill_correction_topics (P4.4, D4.4 §6)
# ---------------------------------------------------------------------------

# Real text against the bundled 0625 taxonomy, chosen by running the actual
# classifier (not guessed): two strong hits, uncontested -> HIGH; one
# uncontested strong hit -> MEDIUM; a topic-level match contested by a rival
# -> LOW (discarded); no vocabulary at all -> unclassified.
HALF_LIFE_TEXT = (
    "State the half-life of a radioactive isotope and describe background radiation measurements."
)
CIRCUIT_TEXT = (
    "Calculate the current flowing through the circuit component when the switch is closed."
)
LOW_BAND_TEXT = "Describe how force affects motion of the object."
UNPLACEABLE_TEXT = "Which statement is correct?"


def _scheme_question(question_id: str, *, point_text: str, marks: int = 1) -> SchemeQuestion:
    return SchemeQuestion(
        id=question_id,
        marks=marks,
        type=SchemeQuestionType.RECALL,
        answer_points=[AnswerPoint(id="p1", point=point_text, marks=marks)],
    )


def _mark_scheme(questions: list[SchemeQuestion], *, subject_code: str = "0625") -> MarkScheme:
    metadata = MarkSchemeMetadata(
        subject="Physics",
        subject_code=subject_code,
        paper_number=1,
        paper_variant=2,
        session_month=LooseSessionMonth.MAY_JUNE,
        session_year=2020,
        paper_type=PaperType.THEORY_CORE,
        maximum_mark=sum(q.marks for q in questions),
        scheme_format=SchemeFormat.POINT_BASED,
    )
    return MarkScheme(metadata=metadata, questions=questions)


def _corrected(question_id: str, *, topic: str | None = None) -> CorrectedQuestion:
    return CorrectedQuestion(
        question_id=question_id,
        awarded_marks=1,
        maximum_marks=1,
        confidence=ConfidenceBand.HIGH,
        confidence_score=1.0,
        needs_teacher_review=False,
        marker_source="ai",
        topic=topic,
    )


def _single_question_correction(
    subject_code: str = "0625", *, question_id: str = "1", topic: str | None = None
) -> CorrectionResult:
    return CorrectionResult(
        metadata=ExamMetadata(
            subject_code=subject_code,
            paper_number=1,
            paper_variant=2,
            session_month="May/June",
            session_year=2020,
        ),
        questions=[_corrected(question_id, topic=topic)],
    )


def test_fill_correction_topics_assigns_a_high_confidence_label() -> None:
    correction = _single_question_correction()
    mark_scheme = _mark_scheme([_scheme_question("1", point_text=HALF_LIFE_TEXT)])

    fill_correction_topics(correction, mark_scheme)

    assert correction.questions[0].topic == "5.2 Radioactivity"


def test_fill_correction_topics_assigns_a_medium_confidence_label() -> None:
    correction = _single_question_correction()
    mark_scheme = _mark_scheme([_scheme_question("1", point_text=CIRCUIT_TEXT)])

    fill_correction_topics(correction, mark_scheme)

    assert correction.questions[0].topic == "4.3 Electric circuits"


def test_fill_correction_topics_discards_a_low_confidence_match() -> None:
    """A low-band match is real (``classify`` returns one) but must not be written."""
    correction = _single_question_correction()
    mark_scheme = _mark_scheme([_scheme_question("1", point_text=LOW_BAND_TEXT)])

    fill_correction_topics(correction, mark_scheme)

    assert correction.questions[0].topic is None


def test_fill_correction_topics_never_overwrites_an_existing_topic() -> None:
    """A real ``topic_hint`` from the mark scheme outranks the classifier."""
    correction = _single_question_correction(topic="3.2 Light")
    # Point text that would otherwise classify as Radioactivity.
    mark_scheme = _mark_scheme([_scheme_question("1", point_text=HALF_LIFE_TEXT)])

    fill_correction_topics(correction, mark_scheme)

    assert correction.questions[0].topic == "3.2 Light"


def test_fill_correction_topics_leaves_an_unclassifiable_question_unlabelled() -> None:
    correction = _single_question_correction()
    mark_scheme = _mark_scheme([_scheme_question("1", point_text=UNPLACEABLE_TEXT)])

    fill_correction_topics(correction, mark_scheme)

    assert correction.questions[0].topic is None


def test_fill_correction_topics_classifies_nothing_for_an_unbundled_subject() -> None:
    correction = _single_question_correction(subject_code="9701")
    mark_scheme = _mark_scheme(
        [_scheme_question("1", point_text=HALF_LIFE_TEXT)], subject_code="9701"
    )

    fill_correction_topics(correction, mark_scheme)

    assert correction.questions[0].topic is None


def test_fill_correction_topics_leaves_a_question_absent_from_the_scheme_unlabelled() -> None:
    """A ``CorrectedQuestion`` id absent from the mark scheme is skipped, not fatal."""
    correction = _single_question_correction(question_id="does-not-exist")
    mark_scheme = _mark_scheme([_scheme_question("1", point_text=HALF_LIFE_TEXT)])

    fill_correction_topics(correction, mark_scheme)

    assert correction.questions[0].topic is None


def test_fill_correction_topics_classifies_a_parent_from_its_parts() -> None:
    """A parent node carries no prose of its own — the marking content hangs off
    its ``parts``. Measured on the real 0625 corpus, classifying nodes in
    isolation reaches 8.1% of marked nodes and using the subtree reaches 14.9%.
    """
    child = _scheme_question("1(a)", point_text=HALF_LIFE_TEXT)
    parent = SchemeQuestion(id="1", marks=1, type=SchemeQuestionType.RECALL, parts=[child])
    correction = _single_question_correction()  # the CorrectedQuestion for "1"

    fill_correction_topics(correction, _mark_scheme([parent]))

    assert correction.questions[0].topic == "5.2 Radioactivity"


def test_fill_correction_topics_inherits_the_nearest_ancestors_label() -> None:
    """A sub-part whose own mark points are bare bookkeeping ("correct
    substitution") inherits its parent's topic — it *is* structurally part of
    that question, and the parent's evidence is a superset of the child's.
    Worth 14.9% -> 32.2% of marked nodes on the real corpus.
    """
    child = _scheme_question("1(a)", point_text="correct substitution")
    parent = SchemeQuestion(
        id="1",
        marks=1,
        type=SchemeQuestionType.RECALL,
        answer_points=[AnswerPoint(id="p1", point=HALF_LIFE_TEXT, marks=1)],
        parts=[child],
    )
    correction = _single_question_correction(question_id="1(a)")

    fill_correction_topics(correction, _mark_scheme([parent]))

    assert correction.questions[0].topic == "5.2 Radioactivity"


def test_fill_correction_topics_prefers_a_childs_own_match_over_inheritance() -> None:
    """Inheritance is a fallback, never an override: a part that confidently
    classifies on its own keeps its own label, not its parent's.
    """
    child = _scheme_question("1(a)", point_text=CIRCUIT_TEXT)
    parent = SchemeQuestion(
        id="1",
        marks=1,
        type=SchemeQuestionType.RECALL,
        answer_points=[AnswerPoint(id="p1", point=HALF_LIFE_TEXT, marks=1)],
        parts=[child],
    )
    correction = _single_question_correction(question_id="1(a)")

    fill_correction_topics(correction, _mark_scheme([parent]))

    assert correction.questions[0].topic == "4.3 Electric circuits"


def test_fill_correction_topics_does_not_inherit_from_an_unplaceable_ancestor() -> None:
    """Inheritance is still gated by ``is_writable`` — a topic no ancestor could
    confidently place stays ``None`` rather than becoming a laundered guess.
    """
    child = _scheme_question("1(a)", point_text="correct substitution")
    parent = SchemeQuestion(
        id="1",
        marks=1,
        type=SchemeQuestionType.RECALL,
        answer_points=[AnswerPoint(id="p1", point=UNPLACEABLE_TEXT, marks=1)],
        parts=[child],
    )
    correction = _single_question_correction(question_id="1(a)")

    fill_correction_topics(correction, _mark_scheme([parent]))

    assert correction.questions[0].topic is None


def test_fill_correction_topics_leaves_mcq_nodes_unlabelled() -> None:
    """The structural ceiling, pinned so it is not mistaken for a regression:
    a CAIE MCQ mark scheme carries exactly one datum — the answer letter — so
    520 of the real corpus's 1329 marked nodes have no text to classify at any
    depth. Their stems live in the question paper (D3.7).
    """
    mcq = SchemeQuestion(id="1", marks=1, type=SchemeQuestionType.MCQ, mcq_answer="D")
    correction = _single_question_correction()

    fill_correction_topics(correction, _mark_scheme([mcq]))

    assert correction.questions[0].topic is None


def test_fill_correction_topics_changes_the_weakness_grouping() -> None:
    """The feature-proving test: real syllabus topics group the weakness report,
    not a single 'unknown' bucket — the entire point of D4.4 §6 / P4.4.
    """
    correction = CorrectionResult(
        metadata=ExamMetadata(
            subject_code="0625",
            paper_number=1,
            paper_variant=2,
            session_month="May/June",
            session_year=2020,
        ),
        questions=[_corrected("1"), _corrected("2")],
    )
    mark_scheme = _mark_scheme(
        [
            _scheme_question("1", point_text=HALF_LIFE_TEXT),
            _scheme_question("2", point_text=CIRCUIT_TEXT),
        ]
    )
    for q in correction.questions:
        q.awarded_marks = 0  # ensure every question contributes lost marks

    before = summarize_weaknesses(correction)
    assert {area.topic for area in before.weak_areas} == {"unknown"}

    fill_correction_topics(correction, mark_scheme)
    after = summarize_weaknesses(correction)

    assert {area.topic for area in after.weak_areas} == {
        "5.2 Radioactivity",
        "4.3 Electric circuits",
    }


def test_persist_quiz_correction_writes_weakness_records_grouped_by_real_topic(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """End-to-end through the actual writer: fill, summarize, persist — the
    ``WeaknessRecord`` rows a teacher/analytics query reads come out grouped
    by a real syllabus topic, not ``"unknown"``.
    """
    correction = _single_question_correction()
    correction.questions[0].awarded_marks = 0
    mark_scheme = _mark_scheme([_scheme_question("1", point_text=HALF_LIFE_TEXT)])

    fill_correction_topics(correction, mark_scheme)
    weaknesses = summarize_weaknesses(correction)

    user_id = _seed_user(pg_sessionmaker)
    AttemptRepository(pg_sessionmaker).persist_quiz_correction(
        user_id=user_id, correction=correction, weaknesses=weaknesses
    )

    with pg_sessionmaker() as session:
        records = session.scalars(select(WeaknessRecord)).all()
        assert {r.topic for r in records} == {"5.2 Radioactivity"}


def test_marking_detail_tables_exist_and_relate() -> None:
    """The two new tables and the six additive columns are reachable from the ORM.

    A schema-shape test, not a behaviour test — Task 5 is what fills them. It
    takes no ``pg_sessionmaker``: every assertion here reads SQLAlchemy mapper
    metadata, and that fixture creates and drops a throwaway database per test,
    which this would pay for and never use.
    """
    assert QuestionResultPoint.__tablename__ == "question_result_points"
    assert QuestionResultRevision.__tablename__ == "question_result_revisions"

    columns = QuestionResult.__table__.columns
    for name in (
        "extraction_confidence",
        "rationale",
        "student_selfmark_marks",
        "student_selfmarked_at",
    ):
        assert name in columns, f"{name} missing from question_results"

    # Both integrity flags are gone, for different reasons, and both are
    # asserted absent rather than merely omitted above so a re-add has to be
    # deliberate. F4 removed the AI-detection feature and `0039_merge_heads`
    # drops the column develop's sibling `0037_question_result_pts` added for
    # it. `plagiarism_flagged` went with `0040_marker_source_blank` (task #36
    # ruling 2): the signal is dead end to end, and the one reader that needs
    # the fact -- `attempt_repo.is_marking_low_confidence`, an authority gate
    # -- reads the `ReviewReason.plagiarism_flag` queue row
    # `review_reasons_for` opens, which is where the flag was already being
    # persisted.
    assert "ai_detection_flagged" not in columns
    assert "plagiarism_flagged" not in columns

    assert "points" in QuestionResult.__mapper__.relationships
    assert "revisions" in QuestionResult.__mapper__.relationships


def _report_with_one_question(**overrides: object) -> AccuracyReport:
    """An AccuracyReport carrying exactly one question against ``_scheme()``.

    Keyword overrides land on the CorrectedQuestion, so a test can vary
    ``matched_point_ids``, ``extraction_confidence``, the integrity flags or
    ``rationale`` without rebuilding the whole report.
    """
    question: dict[str, object] = {
        "question_id": "1a",
        "awarded_marks": 1,
        "maximum_marks": 3,
        "confidence": ConfidenceBand.HIGH,
        "confidence_score": 0.95,
        "needs_teacher_review": False,
        "matched_point_ids": ["p1"],
    }
    question.update(overrides)
    awarded = question["awarded_marks"]
    maximum = question["maximum_marks"]
    assert isinstance(awarded, int)
    assert isinstance(maximum, int)

    correction = CorrectionResult(
        metadata=ExamMetadata(
            subject_code="0580",
            session_month="May/June",
            session_year=2024,
            paper_number=2,
            paper_variant=1,
        ),
        questions=[CorrectedQuestion(**question)],  # type: ignore[arg-type]
    )
    return AccuracyReport(
        correction=correction,
        weaknesses=WeaknessReport(weak_areas=[]),
        # Kept in step with an overridden awarded_marks/maximum_marks so the
        # prediction never reads as an error next to the QuestionResult it
        # nominally summarizes (nothing here validates the two against each
        # other; this is legibility only).
        grade_prediction=GradePrediction(
            awarded_marks=awarded,
            maximum_marks=maximum,
            percentage=round(awarded / maximum * 100, 2) if maximum else 0.0,
            grade="E",
            confidence=ConfidenceBand.HIGH,
        ),
    )


def _points_for(
    pg_sessionmaker: sessionmaker[Session], attempt_id: uuid.UUID
) -> list[QuestionResultPoint]:
    with pg_sessionmaker() as session:
        return list(
            session.scalars(
                select(QuestionResultPoint)
                .join(QuestionResult)
                .where(QuestionResult.attempt_id == attempt_id)
                .order_by(QuestionResultPoint.ordinal)
            ).all()
        )


def _revisions_for(
    pg_sessionmaker: sessionmaker[Session], attempt_id: uuid.UUID
) -> list[QuestionResultRevision]:
    with pg_sessionmaker() as session:
        return list(
            session.scalars(
                select(QuestionResultRevision)
                .join(QuestionResult)
                .where(QuestionResult.attempt_id == attempt_id)
            ).all()
        )


def _only_result(pg_sessionmaker: sessionmaker[Session], attempt_id: uuid.UUID) -> QuestionResult:
    with pg_sessionmaker() as session:
        return session.scalars(
            select(QuestionResult).where(QuestionResult.attempt_id == attempt_id)
        ).one()


def test_persist_writes_point_rows_including_missed_points(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """The inversion, end to end: a missed point is a row with awarded=False."""
    attempt_id = AttemptRepository(pg_sessionmaker).persist_correction(
        user_id=_seed_user(pg_sessionmaker),
        report=_report_with_one_question(matched_point_ids=["p1"]),
        mark_scheme=_scheme(),
    )

    points = _points_for(pg_sessionmaker, attempt_id)

    assert [p.mark_point_id for p in points] == ["p1", "p2", "p3"]
    assert [p.awarded for p in points] == [True, False, False]
    assert [p.tariff for p in points] == [1, 1, 1]
    assert points[0].mark_type == "M"


def test_persist_writes_revision_one(pg_sessionmaker: sessionmaker[Session]) -> None:
    """``awarded_marks=3`` (not 1) so pass-through and point-ledger recomputation

    disagree: ``matched_point_ids=["p1"]`` against three tariff-1 points sums
    to 1 on the ledger, so a wrong implementation that recomputed the
    revision's ``awarded_marks`` from the ledger instead of passing it
    through would write 1 here, not 3 — see
    ``test_awarded_marks_is_untouched_by_the_point_ledger`` for the same
    reasoning against ``QuestionResult`` itself.
    """
    attempt_id = AttemptRepository(pg_sessionmaker).persist_correction(
        user_id=_seed_user(pg_sessionmaker),
        report=_report_with_one_question(matched_point_ids=["p1"], awarded_marks=3),
        mark_scheme=_scheme(),
    )

    revisions = _revisions_for(pg_sessionmaker, attempt_id)

    assert len(revisions) == 1
    assert revisions[0].revision == 1
    assert revisions[0].source is RevisionSource.ai
    assert revisions[0].awarded_marks == 3
    assert len(revisions[0].points_snapshot) == 3


def test_persist_without_a_scheme_writes_no_points(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """The quiz case. The attempt itself must still persist normally, and a
    revision is still written for the question result — with an empty
    snapshot, not skipped — because ``awarded_marks`` still needs a revision
    trail even when there is no scheme to derive points from.
    """
    attempt_id = AttemptRepository(pg_sessionmaker).persist_correction(
        user_id=_seed_user(pg_sessionmaker),
        report=_report_with_one_question(matched_point_ids=["p1"]),
        mark_scheme=None,
    )

    assert _points_for(pg_sessionmaker, attempt_id) == []
    with pg_sessionmaker() as session:
        assert session.get(Attempt, attempt_id) is not None

    revisions = _revisions_for(pg_sessionmaker, attempt_id)
    assert len(revisions) == 1
    assert revisions[0].points_snapshot == []


def test_persist_carries_the_previously_dropped_fields(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    attempt_id = AttemptRepository(pg_sessionmaker).persist_correction(
        user_id=_seed_user(pg_sessionmaker),
        report=_report_with_one_question(
            matched_point_ids=["p1"],
            extraction_confidence=0.82,
            plagiarism_flagged=True,
            rationale="Method correct, rounding wrong.",
        ),
        mark_scheme=_scheme(),
    )

    result = _only_result(pg_sessionmaker, attempt_id)

    assert result.extraction_confidence == 0.82
    assert result.rationale == "Method correct, rounding wrong."
    # `plagiarism_flagged` is NOT carried onto the row -- there is no such
    # column since `0040_marker_source_blank`. It is still carried, as the
    # `plagiarism_flag` queue row `review_reasons_for` opens from the same
    # `CorrectedQuestion` field, which is the persisted form
    # `is_marking_low_confidence` reads. Asserted here rather than only in the
    # authority tests below, because this is the test that would otherwise go
    # green on the flag being dropped on the floor entirely.
    assert not hasattr(result, "plagiarism_flagged")
    with pg_sessionmaker() as session:
        reasons = {
            item.reason
            for item in session.scalars(
                select(ReviewQueueItem).where(ReviewQueueItem.attempt_id == attempt_id)
            ).all()
        }
    assert ReviewReason.plagiarism_flag in reasons


def test_awarded_marks_is_untouched_by_the_point_ledger(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """The accuracy guard: lemely/eval reads awarded_marks and must not shift.

    ``matched_point_ids=["p1"]`` against three tariff-1 points sums to 1 on
    the ledger, so ``awarded_marks`` is deliberately set to 3 instead of 1: a
    wrong implementation that recomputed ``awarded_marks`` from the ledger
    would yield 1 here, not 3, and this assertion would catch it. With the
    previous awarded_marks=1 fixture, pass-through and recomputation produced
    the same number and the test could not fail.
    """
    attempt_id = AttemptRepository(pg_sessionmaker).persist_correction(
        user_id=_seed_user(pg_sessionmaker),
        report=_report_with_one_question(matched_point_ids=["p1"], awarded_marks=3),
        mark_scheme=_scheme(),
    )

    result = _only_result(pg_sessionmaker, attempt_id)

    assert result.awarded_marks == 3
    assert result.effective_marks == 3


def test_snapshot_is_independent_of_later_scheme_edits(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """D3: a re-parsed scheme must not change a paper already marked.

    The row read back through ``_points_for`` is a plain committed row and
    cannot change regardless of implementation, so it proves nothing about
    D3's "snapshot, do not join live" rule on its own. The stored JSON
    snapshot on the revision is what that rule is actually about, so it is
    asserted here too.
    """
    scheme = _scheme()
    attempt_id = AttemptRepository(pg_sessionmaker).persist_correction(
        user_id=_seed_user(pg_sessionmaker),
        report=_report_with_one_question(matched_point_ids=["p1"]),
        mark_scheme=scheme,
    )

    scheme.questions[0].answer_points[0].point = "COMPLETELY DIFFERENT TEXT"
    scheme.questions[0].answer_points[0].marks = 99

    point = _points_for(pg_sessionmaker, attempt_id)[0]
    assert point.point_text == "Correct method"
    assert point.tariff == 1

    snapshot = _revisions_for(pg_sessionmaker, attempt_id)[0].points_snapshot[0]
    assert snapshot["point_text"] == "Correct method"
    assert snapshot["tariff"] == 1


def test_quiz_correction_persists_with_no_points(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """persist_quiz_correction passes no scheme and must be unaffected."""
    attempt_id = AttemptRepository(pg_sessionmaker).persist_quiz_correction(
        user_id=_seed_user(pg_sessionmaker),
        correction=_report_with_one_question(matched_point_ids=["p1"]).correction,
        weaknesses=WeaknessReport(weak_areas=[]),
    )

    with pg_sessionmaker() as session:
        attempt = session.get(Attempt, attempt_id)
        assert attempt is not None
        assert attempt.paper_id is None

    assert _points_for(pg_sessionmaker, attempt_id) == []
    assert len(_revisions_for(pg_sessionmaker, attempt_id)) == 1, (
        "revision 1 is written even with no points"
    )


def test_persist_survives_derive_point_rows_raising(
    pg_sessionmaker: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    """``_safe_derive_point_rows``'s except branch, exercised end to end.

    Nothing in the suite previously called ``derive_point_rows`` in a way that
    could raise, so this branch — and ``_warn_if_point_ids_were_deduplicated``,
    which it also guards downstream of — could be deleted with the suite
    staying green (fix 4). Monkeypatching the name as imported into
    ``lemely.db.attempt_repo`` (not the original module) is what actually
    exercises the call site.
    """
    import lemely.db.attempt_repo as attempt_repo_module

    def _boom(*_args: object, **_kwargs: object) -> list[dict[str, object]]:
        raise RuntimeError("scheme derivation exploded")

    monkeypatch.setattr(attempt_repo_module, "derive_point_rows", _boom)

    attempt_id = AttemptRepository(pg_sessionmaker).persist_correction(
        user_id=_seed_user(pg_sessionmaker),
        report=_report_with_one_question(matched_point_ids=["p1"]),
        mark_scheme=_scheme(),
    )

    with pg_sessionmaker() as session:
        assert session.get(Attempt, attempt_id) is not None
        assert session.scalars(
            select(QuestionResult).where(QuestionResult.attempt_id == attempt_id)
        ).all()
    assert _points_for(pg_sessionmaker, attempt_id) == []
    # A revision is still written, with an empty snapshot — the same contract
    # as the no-scheme case.
    revisions = _revisions_for(pg_sessionmaker, attempt_id)
    assert len(revisions) == 1
    assert revisions[0].points_snapshot == []


def test_persist_writes_the_source_box_columns(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """A box on the corrected question reaches the row, not just the object."""
    attempt_id = AttemptRepository(pg_sessionmaker).persist_correction(
        user_id=_seed_user(pg_sessionmaker),
        report=_report_with_one_question(
            matched_point_ids=["p1"],
            source_box=SourceBox(page=1, box=[10, 20, 30, 40]),
        ),
        mark_scheme=_scheme(),
    )

    result = _only_result(pg_sessionmaker, attempt_id)

    assert result.source_box_page == 1
    assert result.source_box_ymin == 10
    assert result.source_box_xmin == 20
    assert result.source_box_ymax == 30
    assert result.source_box_xmax == 40


def test_persist_survives_an_unusable_source_box(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """A bad box costs the box, never the attempt.

    ``_safe_derive_point_rows`` can use ``session.begin_nested()`` because
    ``question_result_points`` rows are added after a flush. These columns
    are on the ``question_results`` row itself, attached to the attempt
    BEFORE ``session.add(attempt)``, so no savepoint can protect them -- the
    guard has to reject the value before the row is built. This test is what
    proves it does.
    """
    report = _report_with_one_question(matched_point_ids=["p1"])
    # `SourceBox.validate_box_coords` would reject this (ymax <= ymin and
    # xmax <= xmin): `model_construct` is the one legitimate use of it here,
    # since a real producer can never emit this value, and the point is that
    # the WRITE path -- not pydantic -- is what has to catch it.
    report.correction.questions[0].source_box = SourceBox.model_construct(
        page=1, box=[500, 500, 100, 100]
    )

    attempt_id = AttemptRepository(pg_sessionmaker).persist_correction(
        user_id=_seed_user(pg_sessionmaker),
        report=report,
        mark_scheme=_scheme(),
    )

    with pg_sessionmaker() as session:
        assert session.get(Attempt, attempt_id) is not None
        results = session.scalars(
            select(QuestionResult).where(QuestionResult.attempt_id == attempt_id)
        ).all()
    assert len(results) == 1
    assert results[0].source_box_page is None
    assert results[0].source_box_ymin is None
    assert results[0].source_box_xmin is None
    assert results[0].source_box_ymax is None
    assert results[0].source_box_xmax is None


def test_persist_deduplicates_shared_point_ids_at_the_database(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """The end-to-end proof that deduped rows satisfy the DB's own unique

    constraint (``uq_question_result_points_point``): the pure-function test
    in ``tests/test_question_points.py`` proves ``derive_point_rows`` never
    *emits* two rows for one id, but only a real flush proves that dedup is
    what's needed to satisfy the constraint at all (fix 4).
    """
    scheme = _scheme()
    scheme.questions[0].answer_points = [
        AnswerPoint(id="p1", point="Correct method", marks=1),
        AnswerPoint(id="p1", point="Duplicate, should be dropped", marks=5),
        AnswerPoint(id="p2", point="Answer to 3sf", marks=1),
    ]

    attempt_id = AttemptRepository(pg_sessionmaker).persist_correction(
        user_id=_seed_user(pg_sessionmaker),
        report=_report_with_one_question(matched_point_ids=["p1"]),
        mark_scheme=scheme,
    )

    with pg_sessionmaker() as session:
        assert session.get(Attempt, attempt_id) is not None

    points = _points_for(pg_sessionmaker, attempt_id)
    assert [p.mark_point_id for p in points] == ["p1", "p2"]
    assert len({p.mark_point_id for p in points}) == len(points)


def test_persist_savepoint_isolates_a_ledger_row_postgres_rejects(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """FIX 1, proven at the database: a tariff Postgres itself rejects must

    cost only the ledger, not the attempt. ``AnswerPoint.marks`` is
    ``ge=0`` with no upper bound in pydantic, and an ``is_optional`` point is
    excluded from ``Question.validate_mark_point_sum``'s primary-sum check —
    so a point with ``marks=3_000_000_000`` escapes every validator upstream
    and only fails at the Postgres ``tariff`` column (``sa.Integer``, int4) on
    flush.
    """
    scheme = _scheme()
    scheme.questions[0].answer_points = [
        AnswerPoint(id="p1", point="Correct method", marks=1),
        AnswerPoint(
            id="p2",
            point="Optional point with an out-of-range tariff",
            marks=3_000_000_000,
            is_optional=True,
        ),
        AnswerPoint(id="p3", point="Units stated", marks=1),
    ]

    attempt_id = AttemptRepository(pg_sessionmaker).persist_correction(
        user_id=_seed_user(pg_sessionmaker),
        report=_report_with_one_question(matched_point_ids=["p1"]),
        mark_scheme=scheme,
    )

    with pg_sessionmaker() as session:
        assert session.get(Attempt, attempt_id) is not None
        results = session.scalars(
            select(QuestionResult).where(QuestionResult.attempt_id == attempt_id)
        ).all()
        assert len(results) == 1
        assert results[0].awarded_marks == 1

    # The revision insert lives in the same savepoint as the point rows (it
    # carries the same bad tariff in its ``points_snapshot``), so it rolls
    # back with them — unlike the no-scheme/derivation-failure cases, where
    # there is nothing bad to roll back and a revision is still written.
    assert _points_for(pg_sessionmaker, attempt_id) == []
    assert _revisions_for(pg_sessionmaker, attempt_id) == []


# ── The one definition of "low confidence" (self-review spec, Authority) ──────
#
# Two layers, deliberately, because the gate has two inputs with different
# lifetimes. The RULE is a pure function over five fields and is tested as one
# (no database). The WIRING -- that the gate feeds the rule a truthful
# integrity flag read back out of the `review_queue` rows, now that
# `question_results.plagiarism_flagged` is gone (`0040_marker_source_blank`,
# task #36 ruling 2) -- needs a real persisted row, and gets one below.
#
# The rule half used to be written against `is_marking_low_confidence` with a
# hand-built transient `QuestionResult`. It cannot be any more: an
# integrity-flagged row is no longer expressible as a field on that object, and
# faking one would be testing the gate against an input no producer can emit,
# which is the error `probes/README.md` exists about.


def _rule(
    *,
    confidence_score: float,
    needs_review: bool,
    plagiarism: bool = False,
    review_reason: str | None = None,
    marker_source: MarkerSource = MarkerSource.ai,
) -> bool:
    """Evaluate the shared rule directly, over the five fields it reads.

    ``review_reason`` and ``marker_source`` are parameters, not constants, and
    that is a merge fix rather than a tidy-up. The fixture this replaced
    hardcoded ``marker_source=MarkerSource.ai`` with no ``review_reason`` at
    all, so the fields the US-039 exemption reads could not vary and no
    combination of these tests could reach the blank that granted evidence-free
    self-mark authority. The producer-level enumeration that closes that class
    for good lives in ``tests/test_self_review_authority_builders.py``; these
    stay as the field-level table.

    ``ai_detection`` is gone with the detector (F4).
    """
    return low_confidence_review_needed(
        marker_source=marker_source.value,
        review_reason=review_reason,
        needs_teacher_review=needs_review,
        confidence_score=confidence_score,
        plagiarism_flagged=plagiarism,
    )


def test_low_confidence_score_is_low_confidence() -> None:
    assert _rule(confidence_score=0.55, needs_review=True)


def test_structural_review_flag_without_integrity_flags_is_low_confidence() -> None:
    # The D2.4 out-of-range / value-mismatch signal: high score, review forced.
    assert _rule(confidence_score=0.99, needs_review=True)


def test_integrity_only_flag_is_not_low_confidence() -> None:
    """Purely plagiarism-flagged: review is needed, but not for a marking reason.

    ``review_reason`` carries the integrity segment and NOTHING else, which is
    what "integrity-only" actually looks like on the wire:
    ``apply_integrity_checks`` APPENDS its segment to whatever the builder
    wrote, so the segment standing alone is precisely the case where the
    marking side had no complaint of its own.

    Setting the reason matters, and this assertion used to pass without it for
    the wrong reason. develop's predicate suppressed ``marking_flagged`` on the
    bare boolean, so ANY plagiarism-flagged question was treated as
    integrity-only — including a fully-confident, out-of-range mark, whose
    ``low_confidence`` row is the sole signal that the marker misread the mark
    scheme (finding A). The merged predicate reads the reason instead, so this
    test now has to describe a genuinely reason-free row to make its point.
    """
    assert not _rule(
        confidence_score=0.99,
        needs_review=True,
        plagiarism=True,
        review_reason="plagiarism (score 0.94)",
    )


def test_a_structural_reason_survives_an_integrity_flag_landing_on_top() -> None:
    """Finding A: the integrity exemption must not swallow a marking reason.

    Same flag, same score, same forced review — the only difference is that a
    builder wrote a structural reason before integrity appended its segment.
    That reason is the one signal that the marker misread the scheme, and it
    must still open a ``low_confidence`` row (and still grant self-mark
    authority, since the marker's own verdict is the thing in doubt).
    """
    assert _rule(
        confidence_score=0.99,
        needs_review=True,
        plagiarism=True,
        review_reason="out of range | plagiarism (score 0.94)",
    )


def test_an_unflagged_blank_is_not_low_confidence() -> None:
    """US-039, at the field level: a question no marker read grants no authority.

    ``confidence_score=0.0`` satisfies the bare
    ``< REVIEW_CONFIDENCE_THRESHOLD`` disjunct, so this row is exactly the one
    that let a student self-award every mark on a blank with no evidence and no
    judge. Since task #36 the exemption keys on ``marker_source ==
    MarkerSource.blank`` and nothing else.
    """
    assert not _rule(
        confidence_score=0.0,
        needs_review=False,
        review_reason=_BLANK_ANSWER_REVIEW_REASON,
        marker_source=MarkerSource.blank,
    )


def test_a_missing_row_carrying_the_blank_prose_is_not_exempt() -> None:
    """The removal of the prose test, pinned from the side that would reintroduce it.

    Same ``review_reason`` as the blank above, same score, same absent marker —
    but ``marker_source`` is ``missing``, so this is a ``--mcq-only``/no-client
    question, not a student blank, and it must still carry authority. Under the
    ``" | "``-split substring search this replaced, a ``missing`` row whose
    prose collided with the blank literal was silenced; the gate is on the
    column now, so nothing a builder writes into ``review_reason`` can reach
    the exemption.
    """
    assert _rule(
        confidence_score=0.0,
        needs_review=True,
        review_reason=_BLANK_ANSWER_REVIEW_REASON,
        marker_source=MarkerSource.missing,
    )
    # And the real `--mcq-only` reason, which is what actually ships there.
    assert _rule(
        confidence_score=0.0,
        needs_review=True,
        review_reason="non-MCQ question not marked (--mcq-only or no AI client)",
        marker_source=MarkerSource.missing,
    )


def test_a_blank_flagged_by_something_that_opens_no_row_still_queues() -> None:
    """The conjunct on the blank's ``needs_teacher_review`` exemption, from the
    direction that would remove it.

    ``_build_blank_corrected`` sets ``needs_teacher_review=False``, and today the
    only stage that can flip it True on a blank is ``apply_integrity_checks`` —
    which sets it inside the same ``if updates:`` that just set
    ``plagiarism_flagged``, and which therefore already opens its own
    ``plagiarism_flag`` row. So this row is NOT producible today, and the
    exemption could be simplified to ``unscored_blank`` alone with no observable
    change. That simplification is the wrong direction, which is why this test
    exists rather than the simplification.

    A later stage that flags a blank WITHOUT opening a row of its own (a
    false-blank detector — US-042's accepted residual is exactly this shape)
    would, under the simplified predicate, produce a flagged question with NO
    queue row at all. Suppressing a signal is worse than the duplicate row the
    exemption exists to prevent, and the duplicate is not even possible here:
    with ``plagiarism_flagged`` False there is no second row to duplicate.
    """
    assert _rule(
        confidence_score=0.0,
        needs_review=True,
        plagiarism=False,
        review_reason=_BLANK_ANSWER_REVIEW_REASON,
        marker_source=MarkerSource.blank,
    )
    # The producible counterpart, unchanged: integrity forced the flag and owns
    # its own row, so `low_confidence` stays suppressed.
    assert not _rule(
        confidence_score=0.0,
        needs_review=True,
        plagiarism=True,
        review_reason=f"{_BLANK_ANSWER_REVIEW_REASON} | plagiarism (score 0.94)",
        marker_source=MarkerSource.blank,
    )


def test_a_dropped_row_is_not_exempt_even_though_no_marker_scored_it() -> None:
    """``marker_scored`` is a DIFFERENT question from "is this a student blank".

    Both ``dropped`` and ``blank`` are unscored, so the one-formulation refactor
    puts a predicate answering "was this scored?" within easy reach of this
    exemption — and substituting it here would silence a dropped answer, which
    the model DID respond to and whose mark is therefore genuinely in doubt.
    """
    assert _rule(
        confidence_score=0.0,
        needs_review=True,
        review_reason=_DROPPED_ANSWER_REVIEW_REASON,
        marker_source=MarkerSource.dropped,
    )


def test_low_score_with_integrity_flag_is_still_low_confidence() -> None:
    # The score is a marking-side signal in its own right; an integrity flag
    # on top does not launder it away.
    assert _rule(confidence_score=0.55, needs_review=True, plagiarism=True)


def test_confident_unflagged_question_is_not_low_confidence() -> None:
    assert not _rule(confidence_score=0.95, needs_review=False)


def test_integrity_flag_reaches_the_authority_gate(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """The wiring half: the gate must read the integrity fact off the queue row.

    This is the test the "just drop the integrity term" option fails, and it is
    a security property, not a tidiness one. The row below is what real
    ``correct_paper`` -> real ``apply_integrity_checks`` produces on a
    malformed scheme (a non-MCQ question's id shadowing an MCQ leaf's, defeating
    the MCQ exemption's first-match DFS in ``get_question_by_id``):
    ``marker_source="deterministic"``, ``confidence_score=1.0``,
    ``needs_teacher_review=True`` forced by integrity, and the plagiarism
    segment ALONE on ``review_reason``. Measured, not assumed — that
    combination is producible, so the term cannot be dropped as unreachable.

    With the flag reaching the rule, the gate says False and
    ``self_review_repo._to_view`` sets ``evidence_required=True``. Feed it
    ``False`` instead — which is all a gate with no access to the flag can do —
    and it says True, and a student self-marks an integrity-flagged question
    with no evidence and without the lenient judge, because ``decide_point``
    tests ``low_confidence`` above ``has_evidence``.
    """
    user_id = _seed_user(pg_sessionmaker)
    attempt_id = AttemptRepository(pg_sessionmaker).persist_correction(
        user_id=user_id, report=_report_with_integrity_flags()
    )

    with pg_sessionmaker() as session:
        qr = session.scalars(
            select(QuestionResult).where(QuestionResult.attempt_id == attempt_id)
        ).one()
        # The flag survived the column's removal, as a queue row.
        assert _integrity_flagged(qr) is True
        # So the gate withholds authority, and evidence is required.
        assert is_marking_low_confidence(qr) is False

        # The inversion: a gate that could not see the flag would grant it.
        assert (
            low_confidence_review_needed(
                marker_source=qr.marker_source.value,
                review_reason=qr.review_reason,
                needs_teacher_review=qr.needs_teacher_review,
                confidence_score=qr.confidence_score,
                plagiarism_flagged=False,
            )
            is True
        )


def test_the_integrity_flag_is_not_read_off_the_queue_status(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """A teacher dismissing the row does not change what the marker found.

    ``_integrity_flagged`` is deliberately unfiltered by ``ReviewStatus``: the
    gate asks a historical question. Filtering on ``open`` would hand a student
    evidence-free authority over an integrity-flagged question the moment a
    teacher closed the row.
    """
    user_id = _seed_user(pg_sessionmaker)
    attempt_id = AttemptRepository(pg_sessionmaker).persist_correction(
        user_id=user_id, report=_report_with_integrity_flags()
    )

    with pg_sessionmaker() as session, session.begin():
        for item in session.scalars(
            select(ReviewQueueItem).where(ReviewQueueItem.attempt_id == attempt_id)
        ).all():
            item.status = ReviewStatus.dismissed

    with pg_sessionmaker() as session:
        qr = session.scalars(
            select(QuestionResult).where(QuestionResult.attempt_id == attempt_id)
        ).one()
        assert _integrity_flagged(qr) is True
        assert is_marking_low_confidence(qr) is False


def test_question_result_ids_maps_question_id_to_row_id(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    repo = AttemptRepository(pg_sessionmaker)
    attempt_id = repo.persist_correction(
        user_id=_seed_user(pg_sessionmaker),
        report=_report_with_one_question(matched_point_ids=["p1"]),
        mark_scheme=_scheme(),
    )

    ids = repo.question_result_ids(attempt_id)

    assert set(ids) == {"1a"}
    assert ids["1a"] == _only_result(pg_sessionmaker, attempt_id).id
    assert repo.question_result_ids(uuid.uuid4()) == {}


def _report_with_two_questions() -> AccuracyReport:
    """The same report as :func:`_report_with_one_question`, plus a second question.

    Two questions are the minimum that can tell a per-question mapping from a
    positional one: with a single question every wrong pairing is also the
    right one.
    """
    base = _report_with_one_question()
    first = base.correction.questions[0]
    second = first.model_copy(update={"question_id": "1b", "awarded_marks": 2})
    correction = base.correction.model_copy(update={"questions": [first, second]})
    return base.model_copy(update={"correction": correction})


def test_question_result_ids_pairs_each_question_with_its_own_row(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """Each question id maps to *its* row, not to whichever row came back first."""
    repo = AttemptRepository(pg_sessionmaker)
    attempt_id = repo.persist_correction(
        user_id=_seed_user(pg_sessionmaker),
        report=_report_with_two_questions(),
        mark_scheme=_scheme(),
    )

    ids = repo.question_result_ids(attempt_id)

    with pg_sessionmaker() as session:
        rows = session.execute(
            select(QuestionResult.question_id, QuestionResult.id).where(
                QuestionResult.attempt_id == attempt_id
            )
        ).all()
    expected = {question_id: row_id for question_id, row_id in rows}
    assert set(expected) == {"1a", "1b"}, "fixture must persist two distinct questions"
    assert ids == expected
    assert ids["1a"] != ids["1b"]
