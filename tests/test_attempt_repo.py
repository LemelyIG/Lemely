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
    WeakArea,
    WeaknessReport,
)
from lemely.db.attempt_repo import AttemptRepository, fill_correction_topics
from lemely.db.base import Base
from lemely.db.history_repo import DbHistoryStore
from lemely.db.models import User
from lemely.db.models.attempts import Attempt, QuestionResult, WeaknessRecord
from lemely.db.models.enums import BoundarySource, MarkerSource, ReviewReason, Role
from lemely.db.models.enums import ConfidenceBand as DBConfidenceBand
from lemely.db.models.ops import ReviewQueueItem
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


def _report_with_integrity_flags() -> AccuracyReport:
    """One HIGH-confidence question flagged for BOTH plagiarism and AI-detection.

    ``needs_teacher_review`` is True purely because ``apply_integrity_checks``
    set it (confidence_score is 1.0, well above the review threshold, and
    there is no marking-side out-of-range/value-mismatch signal either) — so
    ``persist_correction`` must NOT also queue a ``low_confidence`` row for
    this question; that would misleadingly label a fully-confident mark as
    low-confidence. Only the two integrity-specific rows should appear.
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
        review_reason="plagiarism (score 0.95) | ai_detection (score 0.90)",
        marker_source="deterministic",
        matched_point_ids=["p1"],
        plagiarism_flagged=True,
        ai_detection_flagged=True,
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
        # from the two integrity flags, which already have their own rows below.
        assert reasons == {
            ReviewReason.plagiarism_flag,
            ReviewReason.ai_detection_flag,
        }
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
