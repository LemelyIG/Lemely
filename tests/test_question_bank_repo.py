"""Postgres-integration tests for the question-bank repo (P3.5 chunk B).

Mirrors ``test_review_repo.py``/``test_class_repo.py``'s throwaway-database
fixture, skipping cleanly when no local Postgres is reachable.

Covers, per the chunk-B brief:

* :func:`visible_bank_filter` — all three visibility tiers, exercised
  through :class:`QuestionBankService`, including the adversarial negative
  cases (a teacher must not see another teacher's owned rows or another
  school's rows).
* Count (:meth:`QuestionBankService.count_by_band`) and selection
  (:meth:`QuestionBankService.select_questions`) agreeing with each other —
  the §1.3 "count of 40, quiz of 12" failure mode.
* ``is_active = false`` rows excluded from both count and selection.
* :func:`import_generated_quiz_files` — a real file on disk produces rows
  with the right provenance; a malformed file is skipped, not fatal.
* :func:`survey_past_paper_questions` against a corpus-shaped
  :class:`~lemely.core.loose_schemas.MarkScheme` — 0 produced / N skipped
  for the missing prompt, and leaf-only counting.
"""

from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING, Any

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.core.generation import GeneratedQuestion, GeneratedQuiz
from lemely.core.loose_schemas import MarkScheme as LooseMarkScheme
from lemely.db.base import Base
from lemely.db.models import Paper, School, Subject, User
from lemely.db.models.academic import MarkScheme as MarkSchemeRecord
from lemely.db.models.enums import (
    DifficultySource,
    ExamBoard,
    QuestionDifficulty,
    QuestionSource,
    Role,
    SessionMonth,
)
from lemely.db.models.quizzes import QuestionBank
from lemely.db.question_bank_repo import (
    QuestionBankService,
    classification_text,
    classify_bank_topics,
    generated_questions_to_bank_rows,
    import_generated_quiz_files,
    survey_past_paper_questions,
    visible_bank_filter,
)
from lemely.runtime.config import DatabaseSettings

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


# ── Fixture: throwaway Postgres database (mirrors test_review_repo.py) ─────


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
def bank_service(pg_sessionmaker: sessionmaker[Session]) -> QuestionBankService:
    return QuestionBankService(pg_sessionmaker)


# ── Seed helpers ─────────────────────────────────────────────────────────


def _seed_user(sm: sessionmaker[Session], role: Role = Role.teacher) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=role))
    return uid


def _seed_school(sm: sessionmaker[Session]) -> uuid.UUID:
    school_id = uuid.uuid4()
    with sm.begin() as session:
        session.add(School(id=school_id, name="Test School", seat_quota=5))
    return school_id


def _seed_bank_row(
    sm: sessionmaker[Session],
    *,
    subject_code: str = "0580-qb",
    difficulty: QuestionDifficulty = QuestionDifficulty.standard,
    owner_id: uuid.UUID | None = None,
    school_id: uuid.UUID | None = None,
    is_active: bool = True,
    prompt: str = "A dummy prompt",
) -> uuid.UUID:
    row_id = uuid.uuid4()
    with sm.begin() as session:
        session.add(
            QuestionBank(
                id=row_id,
                board=ExamBoard.caie,
                subject_code=subject_code,
                source=QuestionSource.teacher_upload,
                owner_id=owner_id,
                school_id=school_id,
                difficulty=difficulty,
                difficulty_source=DifficultySource.teacher_set,
                question_type="explanation",
                prompt=prompt,
                total_marks=2,
                is_active=is_active,
            )
        )
    return row_id


# ---------------------------------------------------------------------------
# visible_bank_filter / QuestionBankService — visibility tiers + parity
# ---------------------------------------------------------------------------


def test_visibility_tiers_and_count_selection_parity(
    pg_sessionmaker: sessionmaker[Session], bank_service: QuestionBankService
) -> None:
    """All three §1.3 tiers, the adversarial negatives, and count==selection.

    Builds a set of rows where a naive divergence between the count query
    and the selection query would show different numbers (the exact §1.3
    failure mode), then asserts every caller's count exactly matches the
    number of rows their selection returns, band by band.
    """
    subject = "0580-vis"
    teacher_a = _seed_user(pg_sessionmaker)
    teacher_b = _seed_user(pg_sessionmaker)
    school_x = _seed_school(pg_sessionmaker)
    school_y = _seed_school(pg_sessionmaker)

    shared_id = _seed_bank_row(
        pg_sessionmaker, subject_code=subject, difficulty=QuestionDifficulty.foundation
    )
    teacher_a_id = _seed_bank_row(
        pg_sessionmaker,
        subject_code=subject,
        difficulty=QuestionDifficulty.standard,
        owner_id=teacher_a,
    )
    teacher_b_id = _seed_bank_row(
        pg_sessionmaker,
        subject_code=subject,
        difficulty=QuestionDifficulty.standard,
        owner_id=teacher_b,
    )
    school_x_id = _seed_bank_row(
        pg_sessionmaker,
        subject_code=subject,
        difficulty=QuestionDifficulty.challenge,
        school_id=school_x,
    )
    school_y_id = _seed_bank_row(
        pg_sessionmaker,
        subject_code=subject,
        difficulty=QuestionDifficulty.challenge,
        school_id=school_y,
    )

    # Tier 1 (shared) + tier 2 (owner) as teacher_a, no school membership.
    counts = bank_service.count_by_band(teacher_a, [], subject_code=subject)
    assert counts == {"foundation": 1, "standard": 1, "challenge": 0}

    for band, expected_ids in (
        ("foundation", {shared_id}),
        ("standard", {teacher_a_id}),  # negative: teacher_b's row must not appear
        ("challenge", set()),  # negative: no school membership → no school rows
    ):
        selected = bank_service.select_questions(
            teacher_a, [], subject_code=subject, band=band, count=10
        )
        assert {row.id for row in selected} == expected_ids
        assert len(selected) == counts[band]

    # teacher_b must not see teacher_a's owned row either (symmetric negative).
    counts_b = bank_service.count_by_band(teacher_b, [], subject_code=subject)
    assert counts_b["standard"] == 1
    selected_b = bank_service.select_questions(
        teacher_b, [], subject_code=subject, band="standard", count=10
    )
    assert {row.id for row in selected_b} == {teacher_b_id}

    # Tier 3 (school): a member of school_x sees school_x's row only.
    counts_school = bank_service.count_by_band(teacher_a, [school_x], subject_code=subject)
    assert counts_school["challenge"] == 1
    selected_school = bank_service.select_questions(
        teacher_a, [school_x], subject_code=subject, band="challenge", count=10
    )
    assert {row.id for row in selected_school} == {school_x_id}
    assert school_y_id not in {row.id for row in selected_school}


def test_visible_bank_filter_shared_only_when_caller_and_schools_empty(
    pg_sessionmaker: sessionmaker[Session], bank_service: QuestionBankService
) -> None:
    """No caller id and no school ids still resolves — to shared rows only, not everything."""
    subject = "0580-anon"
    shared_id = _seed_bank_row(
        pg_sessionmaker, subject_code=subject, difficulty=QuestionDifficulty.foundation
    )
    _seed_bank_row(
        pg_sessionmaker,
        subject_code=subject,
        difficulty=QuestionDifficulty.foundation,
        owner_id=_seed_user(pg_sessionmaker),
    )

    counts = bank_service.count_by_band(None, [], subject_code=subject)
    assert counts["foundation"] == 1
    selected = bank_service.select_questions(
        None, [], subject_code=subject, band="foundation", count=10
    )
    assert {row.id for row in selected} == {shared_id}


def test_is_active_excluded_from_count_and_selection(
    pg_sessionmaker: sessionmaker[Session], bank_service: QuestionBankService
) -> None:
    subject = "0580-inactive"
    active_id = _seed_bank_row(
        pg_sessionmaker, subject_code=subject, difficulty=QuestionDifficulty.foundation
    )
    _seed_bank_row(
        pg_sessionmaker,
        subject_code=subject,
        difficulty=QuestionDifficulty.foundation,
        is_active=False,
    )

    counts = bank_service.count_by_band(None, [], subject_code=subject)
    assert counts["foundation"] == 1
    selected = bank_service.select_questions(
        None, [], subject_code=subject, band="foundation", count=10
    )
    assert {row.id for row in selected} == {active_id}


# ---------------------------------------------------------------------------
# import_generated_quiz_files
# ---------------------------------------------------------------------------


def _generated_quiz_payload() -> dict[str, Any]:
    return {
        "subject_code": "0625",
        "questions": [
            {
                "topic": "Waves",
                "difficulty": "standard",
                "prompt": "Explain how a transverse wave differs from a longitudinal wave.",
                "model_answer": "In a transverse wave the oscillation is perpendicular to "
                "the direction of travel; in a longitudinal wave it is parallel.",
                "mark_scheme_points": ["perpendicular oscillation", "parallel oscillation"],
                "total_marks": 2,
                "source_question_ids": ["1a", "1b"],
            },
            {
                "topic": "Forces",
                "difficulty": "foundation",
                "prompt": "State Newton's first law of motion.",
                "model_answer": "An object remains at rest or in uniform motion unless "
                "acted on by a resultant force.",
                "mark_scheme_points": ["state the law"],
                "total_marks": 1,
                "source_question_ids": [],
            },
        ],
    }


def test_import_generated_quiz_files_creates_rows_with_provenance(
    tmp_path: Path, bank_service: QuestionBankService, pg_sessionmaker: sessionmaker[Session]
) -> None:
    questions_dir = tmp_path / "questions"
    questions_dir.mkdir()
    (questions_dir / "quiz_1.json").write_text(
        json.dumps(_generated_quiz_payload()), encoding="utf-8"
    )

    result = import_generated_quiz_files(bank_service, questions_dir)

    assert result.files_read == 1
    assert result.rows_created == 2
    assert result.skipped == []

    with pg_sessionmaker() as session:
        rows = session.scalars(
            select(QuestionBank).where(QuestionBank.subject_code == "0625")
        ).all()
    assert len(rows) == 2
    by_topic = {row.topic: row for row in rows}
    assert by_topic["Waves"].source == QuestionSource.generated
    assert by_topic["Waves"].difficulty_source == DifficultySource.declared_by_generator
    assert by_topic["Waves"].difficulty == QuestionDifficulty.standard
    assert by_topic["Waves"].owner_id is None
    assert by_topic["Waves"].school_id is None
    assert by_topic["Waves"].source_question_ids == ["1a", "1b"]
    assert by_topic["Waves"].prompt.startswith("Explain how a transverse wave")
    assert by_topic["Forces"].difficulty == QuestionDifficulty.foundation
    assert by_topic["Forces"].source_question_ids == []


def test_import_generated_quiz_files_skips_malformed_file_without_aborting(
    tmp_path: Path, bank_service: QuestionBankService
) -> None:
    questions_dir = tmp_path / "questions"
    questions_dir.mkdir()
    (questions_dir / "good.json").write_text(
        json.dumps(_generated_quiz_payload()), encoding="utf-8"
    )
    (questions_dir / "bad.json").write_text("{not valid json", encoding="utf-8")
    (questions_dir / "wrong_shape.json").write_text(json.dumps({"foo": "bar"}), encoding="utf-8")

    result = import_generated_quiz_files(bank_service, questions_dir)

    assert result.files_read == 3
    assert result.rows_created == 2  # only good.json's two questions
    skipped_names = {s.path.name for s in result.skipped}
    assert skipped_names == {"bad.json", "wrong_shape.json"}
    assert all(s.reason for s in result.skipped)


def test_import_generated_quiz_files_missing_directory_is_honest_zero(
    tmp_path: Path, bank_service: QuestionBankService
) -> None:
    result = import_generated_quiz_files(bank_service, tmp_path / "does-not-exist")
    assert result.files_read == 0
    assert result.rows_created == 0
    assert result.skipped == []


# ---------------------------------------------------------------------------
# generated_questions_to_bank_rows (chunk D: /quizzes/generate's write path)
# ---------------------------------------------------------------------------


def test_generated_questions_to_bank_rows_sets_owner_when_given(
    bank_service: QuestionBankService, pg_sessionmaker: sessionmaker[Session]
) -> None:
    """The mapping ``/quizzes/generate`` (chunk D) uses: owner_id = the generating
    teacher, not the ``None`` the one-shot legacy importer passes."""
    teacher = uuid.uuid4()
    with pg_sessionmaker.begin() as session:
        session.add(User(id=teacher, email=f"{teacher}@example.com", role=Role.teacher))

    quiz = GeneratedQuiz(
        subject_code="0625",
        questions=[
            GeneratedQuestion(
                topic="Waves",
                difficulty="standard",
                prompt="Explain diffraction.",
                model_answer="Bending of waves around an obstacle.",
                mark_scheme_points=["bending", "obstacle"],
                total_marks=2,
                source_question_ids=[],
            )
        ],
    )

    rows = generated_questions_to_bank_rows(quiz, owner_id=teacher)
    assert len(rows) == 1
    assert rows[0].owner_id == teacher
    assert rows[0].source == QuestionSource.generated
    assert rows[0].difficulty_source == DifficultySource.declared_by_generator

    ids = bank_service.add_questions(rows)
    with pg_sessionmaker() as session:
        stored = session.get(QuestionBank, ids[0])
    assert stored is not None
    assert stored.owner_id == teacher


def test_generated_questions_to_bank_rows_defaults_owner_to_none(
    bank_service: QuestionBankService,
) -> None:
    """The legacy one-shot importer's contract: platform-shared, no owner."""
    quiz = GeneratedQuiz(
        subject_code="0625",
        questions=[
            GeneratedQuestion(
                topic="Forces",
                difficulty="foundation",
                prompt="State Newton's first law.",
                model_answer="An object stays at rest or in uniform motion unless acted on.",
                mark_scheme_points=["state the law"],
                total_marks=1,
                source_question_ids=[],
            )
        ],
    )
    rows = generated_questions_to_bank_rows(quiz)
    assert rows[0].owner_id is None
    assert rows[0].school_id is None


# ---------------------------------------------------------------------------
# has_inferred_difficulty (chunk D: pool-count's difficultyEstimated flag)
# ---------------------------------------------------------------------------


def test_has_inferred_difficulty_true_only_when_an_estimated_row_matches(
    pg_sessionmaker: sessionmaker[Session], bank_service: QuestionBankService
) -> None:
    subject = "0580-inferred"
    with pg_sessionmaker.begin() as session:
        session.add(
            QuestionBank(
                board=ExamBoard.caie,
                subject_code=subject,
                source=QuestionSource.generated,
                difficulty=QuestionDifficulty.standard,
                difficulty_source=DifficultySource.declared_by_generator,
                question_type="explanation",
                prompt="Declared-band question",
                total_marks=1,
            )
        )
    assert bank_service.has_inferred_difficulty(None, [], subject_code=subject) is False

    with pg_sessionmaker.begin() as session:
        session.add(
            QuestionBank(
                board=ExamBoard.caie,
                subject_code=subject,
                source=QuestionSource.past_paper,
                difficulty=QuestionDifficulty.foundation,
                difficulty_source=DifficultySource.inferred_from_marks,
                question_type="mcq",
                prompt="Estimated-band question",
                total_marks=1,
            )
        )
    assert bank_service.has_inferred_difficulty(None, [], subject_code=subject) is True
    # Scoped to source, like every other bank query.
    assert (
        bank_service.has_inferred_difficulty(
            None, [], subject_code=subject, source=QuestionSource.generated
        )
        is False
    )


def test_has_inferred_difficulty_respects_visibility(
    pg_sessionmaker: sessionmaker[Session], bank_service: QuestionBankService
) -> None:
    subject = "0580-inferred-vis"
    owner = uuid.uuid4()
    with pg_sessionmaker.begin() as session:
        session.add(User(id=owner, email=f"{owner}@example.com", role=Role.teacher))
    with pg_sessionmaker.begin() as session:
        session.add(
            QuestionBank(
                board=ExamBoard.caie,
                subject_code=subject,
                source=QuestionSource.past_paper,
                owner_id=owner,
                difficulty=QuestionDifficulty.foundation,
                difficulty_source=DifficultySource.inferred_from_marks,
                question_type="mcq",
                prompt="Owner-only estimated question",
                total_marks=1,
            )
        )
    assert bank_service.has_inferred_difficulty(None, [], subject_code=subject) is False
    assert bank_service.has_inferred_difficulty(owner, [], subject_code=subject) is True


# ---------------------------------------------------------------------------
# survey_past_paper_questions
# ---------------------------------------------------------------------------


def _corpus_shaped_payload() -> dict[str, Any]:
    """A mark scheme shaped like the real parsed corpus (D3.7): marking points,
    no question-stem text anywhere, one container with two leaf sub-parts.
    """
    ms = LooseMarkScheme.model_validate(
        {
            "metadata": {
                "subject": "Physics",
                "subject_code": "0625",
                "paper_number": 1,
                "paper_variant": 2,
                "session_month": "May/June",
                "session_year": 2020,
                "paper_type": "theory_core",
                "maximum_mark": 8,
                "scheme_format": "mixed",
            },
            "questions": [
                {"id": "1", "marks": 1, "type": "mcq", "mcq_answer": "A"},
                {
                    "id": "2",
                    "marks": 0,
                    "type": "recall",
                    "parts": [
                        {"id": "2a", "marks": 2, "type": "recall", "topic_hint": "Waves"},
                        {"id": "2b", "marks": 5, "type": "calculation"},
                    ],
                },
            ],
        }
    )
    return ms.model_dump(mode="json")


def _seed_mark_scheme(
    sm: sessionmaker[Session], payload: dict[str, Any], *, subject_code: str = "0625-survey"
) -> None:
    with sm.begin() as session:
        session.add(Subject(code=subject_code, name="Physics"))
        session.flush()
        paper = Paper(
            subject_code=subject_code,
            session_month=SessionMonth.may_june,
            session_year=2020,
            paper_number=1,
            paper_variant=2,
        )
        session.add(paper)
        session.flush()
        session.add(MarkSchemeRecord(paper_id=paper.id, maximum_mark=8, parsed_payload=payload))


def test_survey_past_paper_questions_zero_produced_leaf_only(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    _seed_mark_scheme(pg_sessionmaker, _corpus_shaped_payload())

    report = survey_past_paper_questions(pg_sessionmaker)

    assert report.mark_schemes_scanned == 1
    assert report.parse_failures == 0
    # Leaf-only: "1", "2a", "2b" — the container "2" (has parts) is excluded.
    assert report.leaf_questions_seen == 3
    assert report.produced == 0
    assert report.skipped_no_prompt == report.leaf_questions_seen == 3
    assert report.topic_hints_present == 1  # only "2a" carries a topic_hint
    assert report.band_distribution == {"foundation": 1, "standard": 1, "challenge": 1}

    explanation = report.explanation()
    assert "0 past-paper questions produced" in explanation
    assert "question-stem" in explanation or "prompt" in explanation


def test_survey_past_paper_questions_empty_corpus_is_honest_zero(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    report = survey_past_paper_questions(pg_sessionmaker)
    assert report.mark_schemes_scanned == 0
    assert report.leaf_questions_seen == 0
    assert report.produced == 0
    assert report.skipped_no_prompt == 0
    assert report.band_distribution == {"foundation": 0, "standard": 0, "challenge": 0}

    # Having scanned nothing, the report must not claim it *found* every
    # question to be stem-less — that is prior knowledge (D3.7), not this
    # run's observation. It must still name the blocker, so an operator who
    # indexes mark schemes and re-runs is not misled into expecting a
    # different number.
    explanation = report.explanation()
    assert "nothing was examined" in explanation
    assert "no leaf question" not in explanation
    assert "stem extractor" in explanation


def test_survey_past_paper_questions_malformed_payload_is_skipped_not_fatal(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    _seed_mark_scheme(pg_sessionmaker, {"not": "a valid mark scheme"}, subject_code="0625-bad")
    _seed_mark_scheme(pg_sessionmaker, _corpus_shaped_payload(), subject_code="0625-good")

    report = survey_past_paper_questions(pg_sessionmaker)

    assert report.parse_failures == 1
    assert report.mark_schemes_scanned == 1
    assert report.leaf_questions_seen == 3


# ---------------------------------------------------------------------------
# visible_bank_filter as a pure predicate (unit-level, no service indirection)
# ---------------------------------------------------------------------------


def test_add_questions_empty_sequence_is_a_noop(bank_service: QuestionBankService) -> None:
    assert bank_service.add_questions([]) == []


def test_select_questions_non_positive_count_returns_empty(
    pg_sessionmaker: sessionmaker[Session], bank_service: QuestionBankService
) -> None:
    subject = "0580-zero-count"
    _seed_bank_row(pg_sessionmaker, subject_code=subject, difficulty=QuestionDifficulty.foundation)
    assert (
        bank_service.select_questions(None, [], subject_code=subject, band="foundation", count=0)
        == []
    )
    assert (
        bank_service.select_questions(None, [], subject_code=subject, band="foundation", count=-1)
        == []
    )


def test_count_and_select_apply_source_and_topic_filters(
    pg_sessionmaker: sessionmaker[Session], bank_service: QuestionBankService
) -> None:
    subject = "0580-filters"
    with pg_sessionmaker.begin() as session:
        session.add(
            QuestionBank(
                board=ExamBoard.caie,
                subject_code=subject,
                source=QuestionSource.generated,
                difficulty=QuestionDifficulty.foundation,
                difficulty_source=DifficultySource.declared_by_generator,
                question_type="explanation",
                prompt="p1",
                total_marks=1,
                topic="Waves",
            )
        )
        session.add(
            QuestionBank(
                board=ExamBoard.caie,
                subject_code=subject,
                source=QuestionSource.past_paper,
                difficulty=QuestionDifficulty.foundation,
                difficulty_source=DifficultySource.inferred_from_marks,
                question_type="explanation",
                prompt="p2",
                total_marks=1,
                topic="Forces",
            )
        )

    counts_generated = bank_service.count_by_band(
        None, [], subject_code=subject, source=QuestionSource.generated
    )
    assert counts_generated["foundation"] == 1
    selected_generated = bank_service.select_questions(
        None, [], subject_code=subject, band="foundation", count=10, source=QuestionSource.generated
    )
    assert {row.topic for row in selected_generated} == {"Waves"}

    counts_topic = bank_service.count_by_band(None, [], subject_code=subject, topics=["Forces"])
    assert counts_topic["foundation"] == 1
    selected_topic = bank_service.select_questions(
        None, [], subject_code=subject, band="foundation", count=10, topics=["Forces"]
    )
    assert {row.topic for row in selected_topic} == {"Forces"}


def test_past_paper_survey_report_explanation_when_produced_is_nonzero() -> None:
    """Unreachable against today's corpus, but the report type itself must
    format a positive count correctly should a future stem extractor land."""
    from lemely.db.question_bank_repo import PastPaperSurveyReport

    report = PastPaperSurveyReport(
        mark_schemes_scanned=2,
        parse_failures=0,
        leaf_questions_seen=10,
        produced=4,
        skipped_no_prompt=6,
        topic_hints_present=3,
        band_distribution={"foundation": 2, "standard": 1, "challenge": 1},
    )
    assert report.explanation() == "4 past-paper question(s) produced from 2 mark scheme(s)."


def test_visible_bank_filter_composes_into_an_arbitrary_select(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """The predicate is usable standalone in any ``select()``, per the module contract."""
    subject = "0580-direct"
    teacher = _seed_user(pg_sessionmaker)
    shared_id = _seed_bank_row(pg_sessionmaker, subject_code=subject)
    owned_id = _seed_bank_row(pg_sessionmaker, subject_code=subject, owner_id=teacher)
    other_id = _seed_bank_row(
        pg_sessionmaker, subject_code=subject, owner_id=_seed_user(pg_sessionmaker)
    )

    with pg_sessionmaker() as session:
        stmt = select(QuestionBank.id).where(
            QuestionBank.subject_code == subject, visible_bank_filter(teacher, [])
        )
        ids = set(session.scalars(stmt).all())

    assert ids == {shared_id, owned_id}
    assert other_id not in ids


# ---------------------------------------------------------------------------
# classify_bank_topics (P4.2, D4.4)
# ---------------------------------------------------------------------------


def test_classify_bank_topics_assigns_writes_and_is_idempotent(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """A confident row gets a syllabus label; a second run leaves it alone.

    Idempotency is not cosmetic — the corpus grows between runs, and a backfill
    that re-derived every row each time would silently churn labels a teacher
    may already have seen.
    """
    row_id = _seed_bank_row(
        pg_sessionmaker,
        subject_code="0625",
        prompt=(
            "A thin converging lens is used to produce a real image of an object. "
            "State the focal length and mark the principal focus on the ray diagram."
        ),
    )

    first = classify_bank_topics(pg_sessionmaker, subject_code="0625")
    assert first.assigned >= 1
    with pg_sessionmaker() as session:
        assert session.get(QuestionBank, row_id).topic == "3.2 Light"

    second = classify_bank_topics(pg_sessionmaker, subject_code="0625")
    assert second.assigned == 0
    assert second.already_classified >= 1
    with pg_sessionmaker() as session:
        assert session.get(QuestionBank, row_id).topic == "3.2 Light"


def test_classify_bank_topics_leaves_an_unplaceable_row_null(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """The whole point of the module: no label beats a wrong one (UI spec §1.4)."""
    row_id = _seed_bank_row(
        pg_sessionmaker, subject_code="0625", prompt="Which statement is correct?"
    )

    report = classify_bank_topics(pg_sessionmaker, subject_code="0625")

    assert report.unclassified >= 1
    with pg_sessionmaker() as session:
        assert session.get(QuestionBank, row_id).topic is None


def test_classify_bank_topics_dry_run_writes_nothing(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """``--dry-run`` must report the identical counts without touching a row."""
    row_id = _seed_bank_row(
        pg_sessionmaker,
        subject_code="0625",
        prompt=(
            "Define specific heat capacity. Describe experiments to measure the "
            "specific heat capacity of a metal block."
        ),
    )

    dry = classify_bank_topics(pg_sessionmaker, subject_code="0625", dry_run=True)
    assert dry.assigned >= 1
    with pg_sessionmaker() as session:
        assert session.get(QuestionBank, row_id).topic is None

    wet = classify_bank_topics(pg_sessionmaker, subject_code="0625")
    assert wet.assigned == dry.assigned
    with pg_sessionmaker() as session:
        assert session.get(QuestionBank, row_id).topic is not None


def test_classify_bank_topics_skips_a_subject_with_no_bundled_syllabus(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """Forcing a 9701 question against the physics tree would be worse than nothing."""
    row_id = _seed_bank_row(
        pg_sessionmaker,
        subject_code="9701",
        prompt="Describe the reaction of ethanol with acidified potassium dichromate.",
    )

    report = classify_bank_topics(pg_sessionmaker, subject_code="9701")

    assert report.no_taxonomy >= 1
    assert report.assigned == 0
    with pg_sessionmaker() as session:
        assert session.get(QuestionBank, row_id).topic is None


def test_reclassify_removes_a_label_the_vocabulary_no_longer_supports(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """A reclassify pass must be able to retract, not only add.

    Otherwise editing the taxonomy could only ever grow coverage, and a term
    removed because it was producing wrong labels would leave those labels
    behind in the bank.
    """
    row_id = _seed_bank_row(
        pg_sessionmaker, subject_code="0625", prompt="Which statement is correct?"
    )
    with pg_sessionmaker.begin() as session:
        session.get(QuestionBank, row_id).topic = "9.9 Nonsense From An Older Run"

    report = classify_bank_topics(pg_sessionmaker, subject_code="0625", reclassify=True)

    assert report.already_classified == 0  # reclassify re-derives everything
    with pg_sessionmaker() as session:
        assert session.get(QuestionBank, row_id).topic is None


def test_classification_text_includes_mcq_options(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """Measured on the real bank, the options carried coverage from 78.8% to 89.4%.

    An MCQ stem is deliberately terse and the discriminating vocabulary often
    lives entirely in the four options.
    """
    row_id = _seed_bank_row(
        pg_sessionmaker, subject_code="0625", prompt="Which planet is closest to the Sun?"
    )
    with pg_sessionmaker.begin() as session:
        session.get(QuestionBank, row_id).mcq_options = [
            "A Mercury",
            "B a comet in the solar system",
            "C an asteroid",
            "D Neptune",
        ]

    with pg_sessionmaker() as session:
        text = classification_text(session.get(QuestionBank, row_id))

    assert "asteroid" in text
    assert "comet in the solar system" in text
