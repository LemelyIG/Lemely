"""Tests for :mod:`lemely.db.placement_repo` (P4.4 chunk B-4, D4.6/D4.8).

Postgres-integration, mirroring ``tests/test_placement_quiz_ownership.py``'s
throwaway-database fixture. The seeded bank uses 0625's real top-level
syllabus labels and the real transcribed Paper 4 rate (75 min / 80 marks,
D4.8's "measurement that stands") so ``PlacementService.availability``
exercises the same assembly path measured against the production bank,
without depending on the full ingested corpus being present in CI.

Covers, per D4.6 §7:

* availability against a viable 0625-shaped bank vs. an empty 0580 one;
* create -> self-assignment -> frozen questions, in one transaction;
* the 409 payload on create-when-unavailable equalling the availability
  payload;
* a retake excluding every question the prior placement already used;
* result() before/after marking, and its 403/404 split;
* create -> take -> submit -> mark end to end: ``attempts.origin == quiz``,
  ``grade``/``predicted_grade`` both NULL, and a real ``WeaknessRecord``
  whose topic is a P4.2 ``"<code> <name>"`` label.

MCQ-only questions throughout, so marking never touches Gemini
(``correct_paper``'s deterministic path — mirrors
``tests/test_quiz_marking_repo.py``'s strictest stub).
"""

from __future__ import annotations

import os
import re
import uuid
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

import lemely.io.paper_timing as paper_timing_loader
import lemely.io.syllabus_topics as syllabus_topics_loader
from lemely.db.attempt_repo import AttemptRepository
from lemely.db.base import Base
from lemely.db.class_repo import ClassService
from lemely.db.models import User
from lemely.db.models.academic import Subject
from lemely.db.models.attempts import Attempt
from lemely.db.models.catalogue import SubjectTopic, SyllabusPaper
from lemely.db.models.enums import (
    AttemptOrigin,
    DifficultySource,
    ExamBoard,
    QuestionSource,
    Role,
)
from lemely.db.models.profiles import StudentEnrolmentPaper, StudentSubjectEnrolment
from lemely.db.models.quizzes import QuestionBank, Quiz, QuizQuestion, QuizSubmission
from lemely.db.placement_repo import (
    PlacementCreated,
    PlacementNotFoundError,
    PlacementOwnershipError,
    PlacementService,
    PlacementUnavailableError,
)
from lemely.db.question_bank_repo import NewBankQuestion, QuestionBankService
from lemely.db.quiz_marking_repo import QuizMarkingService
from lemely.db.quiz_taking_repo import QuizTakingService
from lemely.db.session import dispose_engine
from lemely.io.gemini import GeminiClient
from lemely.runtime.config import DatabaseSettings, PathsSettings, load_settings

if TYPE_CHECKING:
    from collections.abc import Iterator

# 0625's real top-level syllabus labels (the `subject_topics` table).
_PHYSICS_TOPICS = [
    "1 Motion, forces and energy",
    "2 Thermal physics",
    "3 Waves",
    "4 Electricity and magnetism",
]

# The same transcribed facts `tests/test_placement_assembly.py`'s `P4` fixture
# uses (75 min / 80 marks) and 0625's real top-level topic labels above —
# seeded into *this* test's own throwaway database so that
# `placement_repo.py`'s bare (session-less) `get_paper_timings`/`get_taxonomy`
# calls resolve against it rather than an ambient one. See
# `_hermetic_reference_data` below for why this is necessary.
_SOURCE_URL = "https://www.cambridgeinternational.org/Images/595430-2023-2025-syllabus.pdf"
_SYLLABUS_VERSION = "2023-2025"


# ---------------------------------------------------------------------------
# Fixtures — throwaway Postgres database, mirrors the sibling ownership suite.
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


@pytest.fixture(autouse=True)
def _hermetic_reference_data(pg_sessionmaker: sessionmaker[Session]) -> Iterator[None]:
    """Give `placement_repo.py`'s bare loader calls somewhere real to read.

    ``PlacementService._timings_for`` (``placement_repo.py:409``) and
    ``_placement_title`` (``:510``) call ``get_paper_timings``/``get_taxonomy``
    with no ``session=`` — deliberately, per the P4.9 rewire brief, since
    threading a session through every call site was out of scope and the
    ``session`` parameter is additive. A bare call falls back to
    ``_load_with_own_session()``, which opens a session against whatever
    database ``get_sessionmaker()``'s *process-wide* default settings resolve
    to — not this test's own throwaway ``pg_sessionmaker`` database. Without
    this fixture the suite only passes by accident, on a machine whose
    ambient default database happens to already be migrated with real 0625
    data (or because another test warmed the process cache first); on a
    clean environment it fails in a way that reads like a placement-logic bug
    rather than a missing seed.

    So, for the duration of each test:

    1. Point ``LEMELY_DATABASE__URL`` — the same override
       ``tests/conftest.py``'s ``migrated_sessionmaker`` uses, because
       ``load_settings()`` is what ``_load_with_own_session()`` ultimately
       reads — at *this* test's own throwaway database.
    2. Seed the ``Subject``/``SyllabusPaper``/``SubjectTopic`` rows those two
       bare call sites need: 0625's real top-level topic labels (so
       ``get_taxonomy`` resolves and ``_placement_title`` can put "Physics" in
       a quiz title) and the real Paper 4 timing (75 min / 80 marks) that
       ``test_placement_assembly.py``'s own ``P4`` fixture uses, so the
       assembled-minutes assertions here are exercising the genuine
       transcribed rate, not a coincidence.
    3. Invalidate both loaders' process caches before *and* after, so this
       test neither inherits a warm cache left by another test file nor
       leaves one behind for the next.
    """
    paper_timing_loader.invalidate_reference_cache()
    syllabus_topics_loader.invalidate_reference_cache()

    engine = pg_sessionmaker.kw["bind"]
    rendered_url = engine.url.render_as_string(hide_password=False)
    previous_db_url = os.environ.get("LEMELY_DATABASE__URL")
    os.environ["LEMELY_DATABASE__URL"] = rendered_url

    with pg_sessionmaker.begin() as session:
        session.add(
            Subject(
                code="0625",
                name="Physics",
                board=ExamBoard.caie,
                source_url=_SOURCE_URL,
                syllabus_version=_SYLLABUS_VERSION,
            )
        )
        session.add(
            SyllabusPaper(
                board=ExamBoard.caie,
                subject_code="0625",
                paper_number=4,
                name="Theory (Extended)",
                duration_minutes=75,
                total_marks=80,
                practical=False,
                source_document="595430-2023-2025-syllabus.pdf",
                source_url=_SOURCE_URL,
                syllabus_version=_SYLLABUS_VERSION,
            )
        )
        for label in _PHYSICS_TOPICS:
            code, name = label.split(" ", 1)
            session.add(
                SubjectTopic(board=ExamBoard.caie, subject_code="0625", code=code, name=name)
            )

    try:
        yield
    finally:
        if previous_db_url is None:
            os.environ.pop("LEMELY_DATABASE__URL", None)
        else:
            os.environ["LEMELY_DATABASE__URL"] = previous_db_url
        dispose_engine()
        paper_timing_loader.invalidate_reference_cache()
        syllabus_topics_loader.invalidate_reference_cache()


@pytest.fixture
def placement_service(pg_sessionmaker: sessionmaker[Session]) -> PlacementService:
    return PlacementService(pg_sessionmaker)


@pytest.fixture
def taking_service(pg_sessionmaker: sessionmaker[Session]) -> QuizTakingService:
    return QuizTakingService(pg_sessionmaker, ClassService(pg_sessionmaker))


@pytest.fixture
def attempt_repo(pg_sessionmaker: sessionmaker[Session]) -> AttemptRepository:
    return AttemptRepository(pg_sessionmaker)


def _seed_user(sm: sessionmaker[Session], role: Role) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=role))
    return uid


def _seed_placement_bank(
    sm: sessionmaker[Session],
    *,
    subject_code: str = "0625",
    topics: list[str] | None = None,
    per_topic: int,
    marks: int = 2,
    stem: str = "0625_s23_qp_41",
) -> None:
    """MCQ past-paper rows on real Paper 4, linked to a real ``Paper`` row.

    Paper 4 (75 min / 80 marks, D4.8) is the exact fixture
    ``tests/test_placement_assembly.py`` uses, so the derived rate here is
    the one transcribed from the syllabus, not a test-only number.
    """
    service = QuestionBankService(sm)
    rows: list[NewBankQuestion] = []
    ref = 1
    for topic in topics if topics is not None else _PHYSICS_TOPICS:
        for _ in range(per_topic):
            rows.append(
                NewBankQuestion(
                    subject_code=subject_code,
                    source=QuestionSource.past_paper,
                    difficulty="standard",
                    difficulty_source=DifficultySource.inferred_from_marks,
                    question_type="mcq",
                    prompt=f"Question {ref}",
                    total_marks=marks,
                    topic=topic,
                    source_question_id=f"{stem}#{ref}",
                    mcq_options=["A", "B", "C", "D"],
                    mcq_answer="B",
                )
            )
            ref += 1
    service.add_questions(rows)
    service.link_past_paper_rows()


def _seed_enrolment(
    sm: sessionmaker[Session],
    student_id: uuid.UUID,
    *,
    subject_code: str = "0625",
    paper_numbers: list[int],
) -> None:
    """An S-01/S-02 enrolment naming the papers this student intends to sit.

    Requires the ``subjects`` row, so call it *after* ``_seed_placement_bank``
    (``link_past_paper_rows`` is what creates that row — D4.8 §1).
    """
    with sm.begin() as session:
        enrolment = StudentSubjectEnrolment(user_id=student_id, subject_code=subject_code)
        session.add(enrolment)
        session.flush()
        for number in paper_numbers:
            session.add(StudentEnrolmentPaper(enrolment_id=enrolment.id, paper_number=number))


def _never_called_gemini_client(tmp_path: Path) -> GeminiClient:
    """Mirrors ``test_quiz_marking_repo.py``'s strictest stub for an all-MCQ quiz."""
    mock_genai = MagicMock()
    mock_genai.models.generate_content.side_effect = AssertionError(
        "Gemini must not be called for an all-MCQ placement quiz"
    )
    settings = load_settings(toml_path=None, cwd=tmp_path)
    settings = settings.model_copy(
        update={
            "paths": PathsSettings(cache_dir=tmp_path / ".cache", output_dir=tmp_path / "outputs")
        }
    )
    return GeminiClient(settings, _genai_client=mock_genai)


def _submitted_ids(sm: sessionmaker[Session], quiz_id: uuid.UUID) -> set[uuid.UUID]:
    with sm() as session:
        ids = session.scalars(
            select(QuizQuestion.question_bank_id).where(QuizQuestion.quiz_id == quiz_id)
        ).all()
        return {i for i in ids if i is not None}


# ---------------------------------------------------------------------------
# Availability (D4.6 §5/§7).
# ---------------------------------------------------------------------------


def test_availability_true_for_a_viable_0625_bank(
    pg_sessionmaker: sessionmaker[Session], placement_service: PlacementService
) -> None:
    student = _seed_user(pg_sessionmaker, Role.student)
    _seed_placement_bank(pg_sessionmaker, per_topic=6)

    result = placement_service.availability(student, "0625")

    assert result.available is True
    assert result.reason is None
    assert result.topic_count >= 4
    assert 12.0 <= result.estimated_minutes <= 18.0
    assert result.question_count >= 6


def test_availability_false_for_a_subject_with_no_ingested_questions(
    pg_sessionmaker: sessionmaker[Session], placement_service: PlacementService
) -> None:
    student = _seed_user(pg_sessionmaker, Role.student)

    result = placement_service.availability(student, "0580")

    assert result.available is False
    assert result.reason == "no_questions"
    assert result.question_count == 0
    assert result.topic_count == 0


def test_load_candidates_excludes_figure_dependent_rows_ordinary_rows_still_load(
    pg_sessionmaker: sessionmaker[Session], placement_service: PlacementService
) -> None:
    """P4.8 chunk 0: ``PlacementService._load_candidates`` builds its own
    subject/source/``is_active`` filter rather than calling
    ``visible_bank_filter`` (placement is always direct-to-student), so the
    figure-dependency exclusion had to be applied there explicitly — this is
    the "wrong seam" case the brief called out, pinned directly against the
    exact function that was changed.

    Mutates one seeded row's prompt to a stem that reads an existing figure
    ("The diagram shows...") and asserts it drops out of the candidate set.
    The inverse: every *other* seeded row — ordinary prose, never touched —
    must still come back, so a detector that accidentally excluded the whole
    pool cannot pass silently.
    """
    _seed_placement_bank(pg_sessionmaker, per_topic=6)
    with pg_sessionmaker() as session:
        all_ids = set(
            session.scalars(
                select(QuestionBank.id).where(QuestionBank.subject_code == "0625")
            ).all()
        )
    assert len(all_ids) == 24, "sanity: 4 topics x 6 per_topic"
    figure_id = next(iter(all_ids))

    with pg_sessionmaker.begin() as session:
        row = session.get(QuestionBank, figure_id)
        assert row is not None
        row.prompt = (
            "The diagram shows a radio signal from the Earth being reflected by Pluto "
            "and returning to the Earth. What is the time taken?"
        )

    with pg_sessionmaker() as session:
        candidates = placement_service._load_candidates(session, "0625")
    candidate_ids = {c.question_bank_id for c in candidates}

    assert figure_id not in candidate_ids
    assert candidate_ids == all_ids - {figure_id}

    # Exclusion from serving, never deletion (brief's hard constraint 1) —
    # the row is still in the bank, still active.
    with pg_sessionmaker() as session:
        still_there = session.get(QuestionBank, figure_id)
    assert still_there is not None
    assert still_there.is_active is True


def test_a_paper_the_student_will_not_sit_is_not_drawn_from(
    pg_sessionmaker: sessionmaker[Session], placement_service: PlacementService
) -> None:
    """D4.6 §5's enrolment clause: 0625 Core (P1/P3) is not measured on Extended (P2/P4).

    The seeded bank is entirely Paper 4. A student whose onboarding says they
    sit Papers 1 and 3 therefore has no eligible question at all — the honest
    outcome, rather than a weakness profile built from a tier they will never
    sit.
    """
    student = _seed_user(pg_sessionmaker, Role.student)
    _seed_placement_bank(pg_sessionmaker, per_topic=6)
    _seed_enrolment(pg_sessionmaker, student, paper_numbers=[1, 3])

    result = placement_service.availability(student, "0625")

    assert result.available is False
    assert result.reason == "no_eligible_questions"


def test_an_enrolled_paper_is_drawn_from(
    pg_sessionmaker: sessionmaker[Session], placement_service: PlacementService
) -> None:
    """The mirror of the above: naming Paper 4 leaves the same bank fully eligible."""
    student = _seed_user(pg_sessionmaker, Role.student)
    _seed_placement_bank(pg_sessionmaker, per_topic=6)
    _seed_enrolment(pg_sessionmaker, student, paper_numbers=[4])

    result = placement_service.availability(student, "0625")

    assert result.available is True
    assert result.topic_count >= 4


def test_a_student_who_skipped_the_paper_question_is_not_narrowed(
    pg_sessionmaker: sessionmaker[Session], placement_service: PlacementService
) -> None:
    """No enrolment-paper rows means "not answered", never "sits no papers".

    Every S-02 field is skippable (D4.5), so an empty allowlist here would
    silently deny placement to every student who skipped one question —
    a defaulted answer wearing a filter's clothes.
    """
    student = _seed_user(pg_sessionmaker, Role.student)
    _seed_placement_bank(pg_sessionmaker, per_topic=6)
    _seed_enrolment(pg_sessionmaker, student, paper_numbers=[])

    result = placement_service.availability(student, "0625")

    assert result.available is True


def test_another_students_enrolment_does_not_narrow_this_one(
    pg_sessionmaker: sessionmaker[Session], placement_service: PlacementService
) -> None:
    """The enrolment lookup is owner-scoped, so B's Core enrolment cannot deny A."""
    student_a = _seed_user(pg_sessionmaker, Role.student)
    student_b = _seed_user(pg_sessionmaker, Role.student)
    _seed_placement_bank(pg_sessionmaker, per_topic=6)
    _seed_enrolment(pg_sessionmaker, student_b, paper_numbers=[1, 3])

    assert placement_service.availability(student_a, "0625").available is True
    assert placement_service.availability(student_b, "0625").available is False


# ---------------------------------------------------------------------------
# Create (D4.6 §1/§4/§5).
# ---------------------------------------------------------------------------


def test_create_persists_a_self_owned_assigned_quiz(
    pg_sessionmaker: sessionmaker[Session], placement_service: PlacementService
) -> None:
    student = _seed_user(pg_sessionmaker, Role.student)
    _seed_placement_bank(pg_sessionmaker, per_topic=6)

    created = placement_service.create(student, "0625")

    assert isinstance(created, PlacementCreated)
    assert created.topic_count >= 4
    assert created.question_count >= 6
    assert 12.0 <= created.estimated_minutes <= 18.0

    with pg_sessionmaker() as session:
        quiz = session.get(Quiz, created.quiz_id)
        assert quiz is not None
        assert quiz.teacher_id is None
        assert quiz.student_id == student
        assert quiz.kind.value == "placement"
        assert quiz.time_limit_minutes is None
        assert quiz.status.value == "assigned"
        assert quiz.title  # a real, non-empty, transcribed subject name
        assert "Physics" in quiz.title

        questions = session.scalars(
            select(QuizQuestion).where(QuizQuestion.quiz_id == created.quiz_id)
        ).all()
        assert len(questions) == created.question_count
        # D4.6 §6: quiz_questions.topic carries question_bank.topic verbatim,
        # so no new marking-side code is needed for the weakness profile.
        assert all(q.topic in _PHYSICS_TOPICS for q in questions)


def test_create_raises_with_the_same_payload_availability_reports(
    pg_sessionmaker: sessionmaker[Session], placement_service: PlacementService
) -> None:
    student = _seed_user(pg_sessionmaker, Role.student)
    # No bank rows at all for 0580 -> unavailable.

    availability = placement_service.availability(student, "0580")
    with pytest.raises(PlacementUnavailableError) as excinfo:
        placement_service.create(student, "0580")

    assert excinfo.value.availability == availability


def test_a_retake_shares_no_question_with_the_first_placement(
    pg_sessionmaker: sessionmaker[Session], placement_service: PlacementService
) -> None:
    student = _seed_user(pg_sessionmaker, Role.student)
    _seed_placement_bank(pg_sessionmaker, per_topic=6)

    first = placement_service.create(student, "0625")
    second = placement_service.create(student, "0625")

    first_ids = _submitted_ids(pg_sessionmaker, first.quiz_id)
    second_ids = _submitted_ids(pg_sessionmaker, second.quiz_id)
    assert first_ids, "sanity: the first placement actually froze questions"
    assert second_ids, "sanity: the retake actually froze questions"
    assert not (first_ids & second_ids)


# ---------------------------------------------------------------------------
# Result (S-05, D4.6 §6/§7).
# ---------------------------------------------------------------------------


def test_result_before_marking_says_so_honestly(
    pg_sessionmaker: sessionmaker[Session], placement_service: PlacementService
) -> None:
    student = _seed_user(pg_sessionmaker, Role.student)
    _seed_placement_bank(pg_sessionmaker, per_topic=6)
    created = placement_service.create(student, "0625")

    result = placement_service.result(student, created.assignment_id)

    assert result.marked is False
    assert result.awarded_marks is None
    assert result.maximum_marks is None
    assert result.questions == []
    assert result.topic_breakdown == []
    assert result.spans_multiple_bands is False


def test_result_unknown_assignment_is_404_not_403(
    pg_sessionmaker: sessionmaker[Session], placement_service: PlacementService
) -> None:
    student = _seed_user(pg_sessionmaker, Role.student)

    with pytest.raises(PlacementNotFoundError):
        placement_service.result(student, uuid.uuid4())


def test_result_for_another_students_placement_is_403_not_404(
    pg_sessionmaker: sessionmaker[Session], placement_service: PlacementService
) -> None:
    owner = _seed_user(pg_sessionmaker, Role.student)
    other = _seed_user(pg_sessionmaker, Role.student)
    _seed_placement_bank(pg_sessionmaker, per_topic=6)
    created = placement_service.create(owner, "0625")

    with pytest.raises(PlacementOwnershipError):
        placement_service.result(other, created.assignment_id)


# ---------------------------------------------------------------------------
# End to end: create -> take -> submit -> mark (D4.6 §6/§7).
# ---------------------------------------------------------------------------


def test_create_take_submit_mark_end_to_end(
    pg_sessionmaker: sessionmaker[Session],
    placement_service: PlacementService,
    taking_service: QuizTakingService,
    attempt_repo: AttemptRepository,
    tmp_path: Path,
) -> None:
    student = _seed_user(pg_sessionmaker, Role.student)
    _seed_placement_bank(pg_sessionmaker, per_topic=6)
    created = placement_service.create(student, "0625")
    assignment_id = created.assignment_id

    detail = taking_service.get_take(student, assignment_id)
    assert detail.header.class_name is None
    assert detail.header.teacher_name is None
    # Every question's correct MCQ answer is "B" (see _seed_placement_bank).
    # Answer the first question wrong so summarize_weaknesses has a lost
    # mark to group — a perfect score produces no WeaknessRecord at all
    # (group_weak_areas excludes any topic with zero net lost marks).
    for position, question in enumerate(detail.questions):
        wrong_first = "A" if position == 0 else "B"
        taking_service.save_answer(
            student, assignment_id, question.question_ref, answer_text=wrong_first
        )
    submit_result = taking_service.submit(student, assignment_id)

    marking = QuizMarkingService(
        pg_sessionmaker, attempt_repo, _never_called_gemini_client(tmp_path)
    )
    mark_outcome = marking.mark_submission(submit_result.submission_id)
    assert mark_outcome.attempt_id is not None

    with pg_sessionmaker() as session:
        attempt = session.get(Attempt, mark_outcome.attempt_id)
        assert attempt is not None
        assert attempt.origin == AttemptOrigin.quiz
        assert attempt.grade is None
        assert attempt.predicted_grade is None
        submission = session.get(QuizSubmission, submit_result.submission_id)
        assert submission is not None
        assert submission.status.value == "marked"

    result = placement_service.result(student, assignment_id)
    assert result.marked is True
    assert result.awarded_marks is not None
    assert result.maximum_marks is not None
    assert result.awarded_marks < result.maximum_marks  # the first answer was wrong
    assert len(result.questions) == created.question_count
    assert result.topic_breakdown, "a marked placement must produce at least one weakness row"
    for weakness in result.topic_breakdown:
        assert re.match(r"^\d+ .+", weakness.topic), (
            f"topic {weakness.topic!r} is not a P4.2 '<code> <name>' label"
        )
