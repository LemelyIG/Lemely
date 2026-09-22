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

    The exemption is narrow: it must key off BOTH ``marker_source=="missing"``
    AND the blank reason, not off ``confidence_score`` or ``marker_source``
    alone -- see ``test_review_queue_still_queues_genuine_missing_and_dropped``
    for the two look-alike builders (real ``needs_teacher_review=True`` blanks)
    that must keep queuing unaffected by this exemption.
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
        marker_source="missing",
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
    the exemption's own gate: with both fixtures also true-blank look-alikes
    (``marker_source == "missing"``/``"dropped"``, ``confidence_score == 0.0``,
    the real review_reason literal from their builder), the only thing that
    can legitimately keep them out of the queue is the exemption keying on
    the *exact* blank ``review_reason``, not on ``marker_source`` or
    ``confidence_score`` alone. Before this rewrite, both fixtures also
    carried ``needs_teacher_review=True``, so ``marking_flagged`` queued them
    regardless of the exemption and the test could not distinguish a narrow
    exemption from an over-broad one collapsed to ``marker_source ==
    "missing"`` alone (verified: with the conjunct removed, this test still
    passed -- see the commit message for the two mutation proofs).
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


def test_review_queue_blank_with_integrity_flag_queues_plagiarism_only(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """Second independent review of the US-039 blank exemption, round 2.

    ``apply_integrity_checks`` (``lemely/io/integrity.py``) APPENDS to
    ``review_reason`` rather than replacing it (its own docstring: "appended
    to (preserving any existing text)") whenever it flags a question. Before
    this fix, the exemption in ``review_queue_rules.review_reasons_for``
    tested ``review_reason == _BLANK_ANSWER_REVIEW_REASON`` by full string
    equality, so a genuine blank that also picked up an integrity flag
    carried ``"<blank reason> | copied from another candidate"`` -- not
    equal to the bare blank reason -- which defeated the exemption. The row
    came back labelled ``low_confidence`` (0.0 confidence, "unsure marker")
    stacked on top of its own ``plagiarism_flag`` row, even though no marker
    ever ran to be unsure. ``review_reasons_for`` now checks membership of
    the blank's exact reason among the ``" | "``-split segments instead of
    whole-field equality, so an appended integrity reason no longer defeats
    it. The result: a flagged blank queues for the real reason it was
    flagged (plagiarism) and ONLY that reason -- not a fabricated
    low-confidence signal alongside it.

    (In today's pipeline this exact combination cannot arise via
    ``correct_paper``: ``_build_blank_corrected`` sets both
    ``student_answer`` and ``expected_answer`` to ``None``, and
    ``apply_integrity_checks``'s plagiarism check requires both truthy
    before it runs. This test constructs the ``CorrectedQuestion`` directly,
    the same way ``test_review_queue_low_confidence_row_survives_alongside_integrity_flags``
    above does, because the predicate's contract must hold for any
    question shaped this way, not merely for what today's one caller
    happens to produce.)
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
        review_reason=f"{_BLANK_ANSWER_REVIEW_REASON} | copied from another candidate",
        marker_source="missing",
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
