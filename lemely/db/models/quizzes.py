"""ORM models for the teacher quiz builder (P3.5, ``docs/quiz-model.md`` §1).

Six tables: :class:`QuestionBank` (the queryable question pool), :class:`Quiz`
(a draft-through-archived quiz), :class:`QuizQuestion` (the curated, ordered,
**materialized** question set a quiz actually contains), :class:`QuizAssignment`
(a quiz handed to a class), :class:`QuizSubmission` (one student's attempt at
an assignment), and :class:`QuizAnswer` (what a student actually wrote for one
question, independent of any marking run).

This module is schema only (P3.5 chunk A) — no repo, no service, no route
reads or writes any of these tables yet. See ``docs/quiz-model.md`` §1 for the
full design rationale; docstrings below summarise the load-bearing decisions
rather than repeat the whole document.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from lemely.db.base import Base
from lemely.db.models.enums import (
    DifficultySource,
    ExamBoard,
    QuestionDifficulty,
    QuestionSource,
    QuizQuestionStatus,
    QuizStatus,
    QuizSubmissionStatus,
    TimestampMixin,
)


class QuestionBank(TimestampMixin, Base):
    """The queryable question pool: one row per markable question.

    **Visibility** is resolved by ``owner_id``/``school_id``: both NULL means
    platform-shared (past papers, platform-generated questions); ``owner_id``
    set means visible to that user only; ``school_id`` set means visible to
    that school's members. The predicate that resolves this
    (``visible_bank_filter``, chunk B) must be the single place both the
    pool-count endpoint and the selection query apply it — see §1.3.

    ``question_type`` is a plain ``varchar`` holding a ``QuestionType`` member
    value, not a native Postgres enum: ``QuestionType`` has sixteen members
    and is owned by the board-agnostic mark-scheme parser, which will grow
    members as new boards arrive. Freezing it into a PG type would mean an
    ``ALTER TYPE`` migration every time the parser learns a question shape.

    ``uq_question_bank_paper_question`` (partial, ``WHERE paper_id IS NOT
    NULL``) makes the past-paper ingest (chunk B) idempotent: re-running it
    over the same parsed mark scheme updates rather than duplicates.
    """

    __tablename__ = "question_bank"
    __table_args__ = (
        sa.Index("ix_question_bank_pool", "subject_code", "source", "difficulty", "is_active"),
        sa.Index("ix_question_bank_topic", "subject_code", "topic", "is_active"),
        sa.Index("ix_question_bank_owner", "owner_id"),
        sa.Index(
            "uq_question_bank_paper_question",
            "paper_id",
            "source_question_id",
            unique=True,
            postgresql_where=sa.text("paper_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    board: Mapped[ExamBoard] = mapped_column(
        sa.Enum(ExamBoard, name="examboard"),
        nullable=False,
        server_default=sa.text("'caie'::examboard"),
    )
    subject_code: Mapped[str] = mapped_column(sa.String, nullable=False)
    source: Mapped[QuestionSource] = mapped_column(
        sa.Enum(QuestionSource, name="questionsource"),
        nullable=False,
    )
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
    )
    school_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("schools.id", ondelete="CASCADE"),
        nullable=True,
    )
    paper_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("papers.id"),
        nullable=True,
    )
    source_question_id: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    """Leaf id within that paper, e.g. ``"3a_ii"``."""
    topic: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    difficulty: Mapped[QuestionDifficulty] = mapped_column(
        sa.Enum(QuestionDifficulty, name="questiondifficulty"),
        nullable=False,
    )
    difficulty_source: Mapped[DifficultySource] = mapped_column(
        sa.Enum(DifficultySource, name="difficultysource"),
        nullable=False,
    )
    question_type: Mapped[str] = mapped_column(sa.String, nullable=False)
    """A ``QuestionType`` member value — plain string, see class docstring."""
    prompt: Mapped[str] = mapped_column(sa.Text, nullable=False)
    model_answer: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    mark_scheme_points: Mapped[list] = mapped_column(  # type: ignore[type-arg]
        JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")
    )
    mcq_options: Mapped[list | None] = mapped_column(  # type: ignore[type-arg]
        JSONB, nullable=True
    )
    """``["A text", "B text", ...]`` for MCQ questions only."""
    mcq_answer: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    """``"A"``..``"D"`` for MCQ questions only."""
    total_marks: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    source_question_ids: Mapped[list] = mapped_column(  # type: ignore[type-arg]
        JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")
    )
    """Provenance of generated questions: the source questions a generated
    question was derived from."""
    is_active: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, server_default=sa.true())
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("users.id"),
        nullable=True,
    )

    quiz_questions: Mapped[list[QuizQuestion]] = relationship(
        "QuizQuestion", back_populates="question_bank"
    )


class Quiz(TimestampMixin, Base):
    """A teacher-built quiz, from first draft through archival.

    Every step-2/3/4 field is nullable and the row is created on entering
    step 1: a half-filled draft is a legal row, not a schema violation, which
    is what makes "draft saving throughout" a ``PATCH`` on an existing row.

    ``status`` lifecycle: ``draft -> assigned -> closed -> archived``, plus
    ``draft -> archived`` (abandoned draft). No transition ever goes
    backwards — an assigned quiz whose questions a teacher wants to change is
    duplicated into a new draft, so a live quiz never changes under students
    mid-attempt.

    ``target_grade`` is a plain ``varchar`` validated against
    ``lemely.core.at_risk.GRADE_ORDER`` at the API boundary rather than a PG
    enum: grade ladders are board-specific and ``GRADE_ORDER`` is already the
    single Python-side source of truth; a PG enum here would create a second
    one.
    """

    __tablename__ = "quizzes"
    __table_args__ = (sa.Index("ix_quizzes_teacher_status", "teacher_id", "status"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    teacher_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    school_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("schools.id", ondelete="SET NULL"),
        nullable=True,
    )
    subject_code: Mapped[str] = mapped_column(sa.String, nullable=False)
    title: Mapped[str] = mapped_column(sa.String, nullable=False)
    status: Mapped[QuizStatus] = mapped_column(
        sa.Enum(QuizStatus, name="quizstatus"),
        nullable=False,
        server_default=sa.text("'draft'::quizstatus"),
    )
    target_grade: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    """A ``GRADE_ORDER`` member; NULL means untargeted. See class docstring."""
    included_topics: Mapped[list] = mapped_column(  # type: ignore[type-arg]
        JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")
    )
    pool_source: Mapped[QuestionSource | None] = mapped_column(
        sa.Enum(QuestionSource, name="questionsource"),
        nullable=True,
    )
    """Step 4's pool choice; NULL while undecided."""
    requested_count: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    time_limit_minutes: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    builder_step: Mapped[int] = mapped_column(
        sa.SmallInteger, nullable=False, server_default=sa.text("1")
    )
    """1..6, for draft resume. Advisory only — the server never trusts it for
    authorization."""

    questions: Mapped[list[QuizQuestion]] = relationship(
        "QuizQuestion", back_populates="quiz", cascade="all, delete-orphan"
    )
    assignments: Mapped[list[QuizAssignment]] = relationship(
        "QuizAssignment", back_populates="quiz", cascade="all, delete-orphan"
    )


class QuizQuestion(TimestampMixin, Base):
    """The curated, ordered, **materialized** question set a quiz contains.

    **The question text is copied, not referenced.** ``question_bank_id`` is
    a nullable provenance pointer only: a bank row can be edited,
    deactivated, or relabelled after a quiz is assigned, and reading through
    the FK could end up showing a student's marked answer next to a
    different question than the one they answered. Snapshotting costs
    duplicated text and buys an assessment record that cannot change after
    the fact.

    **Removed questions are kept, not deleted** (``status = 'removed'``,
    with ``replaced_by_id`` set when step 5's swap produced a replacement).

    ``question_ref`` is the stable per-quiz identifier that flows all the way
    to ``question_results.question_id``. Assigned at insert, never
    renumbered — removing question 3 must not turn question 4 into question
    3 and silently re-point an existing mark. Display order comes from
    ``position``, which may be rewritten freely while the quiz is a draft.
    """

    __tablename__ = "quiz_questions"
    __table_args__ = (
        sa.Index("uq_quiz_questions_ref", "quiz_id", "question_ref", unique=True),
        sa.Index("ix_quiz_questions_quiz_position", "quiz_id", "position", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    quiz_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("quizzes.id", ondelete="CASCADE"),
        nullable=False,
    )
    question_bank_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("question_bank.id", ondelete="SET NULL"),
        nullable=True,
    )
    question_ref: Mapped[str] = mapped_column(sa.String, nullable=False)
    """``"q1"``..``"qN"``; becomes ``question_results.question_id``."""
    position: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    status: Mapped[QuizQuestionStatus] = mapped_column(
        sa.Enum(QuizQuestionStatus, name="quizquestionstatus"),
        nullable=False,
        server_default=sa.text("'included'::quizquestionstatus"),
    )
    replaced_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("quiz_questions.id", ondelete="SET NULL"),
        nullable=True,
    )
    # --- frozen snapshot (see class docstring) -----------------------------
    topic: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    difficulty: Mapped[QuestionDifficulty] = mapped_column(
        sa.Enum(QuestionDifficulty, name="questiondifficulty"),
        nullable=False,
    )
    question_type: Mapped[str] = mapped_column(sa.String, nullable=False)
    prompt: Mapped[str] = mapped_column(sa.Text, nullable=False)
    model_answer: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    mark_scheme_points: Mapped[list] = mapped_column(  # type: ignore[type-arg]
        JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")
    )
    mcq_options: Mapped[list | None] = mapped_column(  # type: ignore[type-arg]
        JSONB, nullable=True
    )
    mcq_answer: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    total_marks: Mapped[int] = mapped_column(sa.Integer, nullable=False)

    quiz: Mapped[Quiz] = relationship("Quiz", back_populates="questions")
    question_bank: Mapped[QuestionBank | None] = relationship(
        "QuestionBank", back_populates="quiz_questions", foreign_keys=[question_bank_id]
    )
    answers: Mapped[list[QuizAnswer]] = relationship("QuizAnswer", back_populates="quiz_question")


class QuizAssignment(TimestampMixin, Base):
    """A quiz handed to a class.

    A separate table rather than a ``class_id`` on ``quizzes``: the same
    quiz assigned to two classes is an obvious teacher need, and modelling it
    now costs one table and no complexity, whereas retrofitting it later
    means rewriting every submission's parentage. T-10 aggregates per
    assignment (a class's results), not per quiz.
    """

    __tablename__ = "quiz_assignments"
    __table_args__ = (
        sa.Index("uq_quiz_assignments", "quiz_id", "class_id", unique=True),
        sa.Index("ix_quiz_assignments_class", "class_id", "assigned_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    quiz_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("quizzes.id", ondelete="CASCADE"),
        nullable=False,
    )
    class_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("classes.id", ondelete="CASCADE"),
        nullable=False,
    )
    assigned_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("users.id"),
        nullable=False,
    )
    assigned_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )
    due_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    closes_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)

    quiz: Mapped[Quiz] = relationship("Quiz", back_populates="assignments")
    submissions: Mapped[list[QuizSubmission]] = relationship(
        "QuizSubmission", back_populates="assignment", cascade="all, delete-orphan"
    )


class QuizSubmission(TimestampMixin, Base):
    """One student's attempt at an assigned quiz.

    Rows are created lazily on first open, not pre-seeded at assignment
    time, so T-10's completion rate is computed against the live class
    roster rather than a frozen snapshot that could drift once a student
    joins or leaves the class after assignment.

    ``attempt_id`` is the join to the marking universe: NULL until marking
    succeeds, with ``marking_error`` holding the failure text if it did not,
    so a failed Gemini call leaves a visible ``submitted``-but-unmarked row
    rather than a silently missing result.

    No confidence column here — quiz confidence is read from
    ``attempts.confidence_band``, one source (§5).
    """

    __tablename__ = "quiz_submissions"
    __table_args__ = (
        sa.Index("uq_quiz_submissions", "assignment_id", "student_id", unique=True),
        sa.Index("ix_quiz_submissions_status", "assignment_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    assignment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("quiz_assignments.id", ondelete="CASCADE"),
        nullable=False,
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[QuizSubmissionStatus] = mapped_column(
        sa.Enum(QuizSubmissionStatus, name="quizsubmissionstatus"),
        nullable=False,
        server_default=sa.text("'not_started'::quizsubmissionstatus"),
    )
    started_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    marked_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    attempt_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("attempts.id", ondelete="SET NULL"),
        nullable=True,
    )
    marking_error: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

    assignment: Mapped[QuizAssignment] = relationship(
        "QuizAssignment", back_populates="submissions"
    )
    answers: Mapped[list[QuizAnswer]] = relationship(
        "QuizAnswer", back_populates="submission", cascade="all, delete-orphan"
    )


class QuizAnswer(TimestampMixin, Base):
    """What a student actually wrote for one question in a submission.

    Separate from ``question_results`` because an answer exists before any
    marking run and must outlive every one of them. Re-marking (a retry
    after a Gemini outage, or a future re-run against a corrected T-11 mark
    scheme) deletes and rewrites the ``Attempt`` and its ``QuestionResult``s;
    it must never touch what the student actually wrote. ``working_text`` is
    present so the method-mark awareness in
    ``AICorrector.mark_question(question, answer, working)`` is not thrown
    away on the quiz path.
    """

    __tablename__ = "quiz_answers"
    __table_args__ = (
        sa.Index("uq_quiz_answers", "submission_id", "quiz_question_id", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    submission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("quiz_submissions.id", ondelete="CASCADE"),
        nullable=False,
    )
    quiz_question_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("quiz_questions.id", ondelete="CASCADE"),
        nullable=False,
    )
    answer_text: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    working_text: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    answered_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)

    submission: Mapped[QuizSubmission] = relationship("QuizSubmission", back_populates="answers")
    quiz_question: Mapped[QuizQuestion] = relationship("QuizQuestion", back_populates="answers")


__all__ = [
    "QuestionBank",
    "Quiz",
    "QuizAnswer",
    "QuizAssignment",
    "QuizQuestion",
    "QuizSubmission",
]
