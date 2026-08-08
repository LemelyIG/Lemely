"""Database enumeration types and shared ORM mixins.

All Python :class:`enum.Enum` subclasses defined here are mapped to Postgres
``ENUM`` types by SQLAlchemy.  The :class:`TimestampMixin` attaches
``created_at`` / ``updated_at`` columns to every model that inherits it.
"""

from __future__ import annotations

import enum
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

# ---------------------------------------------------------------------------
# Enum definitions
# ---------------------------------------------------------------------------


class Role(enum.Enum):
    """User role within the platform."""

    student = "student"
    parent = "parent"
    teacher = "teacher"
    school_admin = "school_admin"
    platform_admin = "platform_admin"


class QualificationLevel(enum.Enum):
    """Qualification track a student is studying towards (P4.3 S-02, D4.5).

    Free-text ``grade_level`` (e.g. "Year 11") captures the school-year
    dimension; this captures the *qualification* dimension separately, since
    the same year group can sit different qualifications (an IGCSE resit
    alongside AS-level subjects, for instance).
    """

    igcse = "igcse"
    o_level = "o_level"
    as_level = "as_level"
    a_level = "a_level"


class SessionMonth(enum.Enum):
    """CAIE exam session month codes.

    ``SESSION_MONTH_LABELS`` maps each member to its display string.
    """

    may_june = "may_june"
    oct_nov = "oct_nov"
    feb_mar = "feb_mar"
    specimen = "specimen"


#: Display labels for :class:`SessionMonth` members.
SESSION_MONTH_LABELS: dict[SessionMonth, str] = {
    SessionMonth.may_june: "May/June",
    SessionMonth.oct_nov: "Oct/Nov",
    SessionMonth.feb_mar: "Feb/Mar",
    SessionMonth.specimen: "Specimen",
}


class ExamBoard(enum.Enum):
    """Exam board identifier.

    Only ``caie`` is used in Phase 1; the others are present for additive
    readiness in later phases.
    """

    caie = "caie"
    edexcel = "edexcel"
    oxford_aqa = "oxford_aqa"


class ConfidenceBand(enum.Enum):
    """AI marking confidence band."""

    high = "high"
    medium = "medium"
    low = "low"


class MarkerSource(enum.Enum):
    """Which engine produced a question mark."""

    deterministic = "deterministic"
    ai = "ai"
    missing = "missing"


class BoundarySource(enum.Enum):
    """Origin of the grade boundary used for a prediction."""

    exact = "exact"
    subject_default = "subject_default"
    global_default = "global_default"


class PlanInterval(enum.Enum):
    """Billing plan recurrence interval."""

    monthly = "monthly"
    yearly = "yearly"


class SubscriptionStatus(enum.Enum):
    """Lifecycle state of a user subscription.

    Activation is manual (platform-admin toggle); payment is out of scope for
    Phase 1.
    """

    inactive = "inactive"
    active = "active"
    cancelled = "cancelled"
    expired = "expired"


class SeatStatus(enum.Enum):
    """State of a school seat."""

    available = "available"
    assigned = "assigned"
    revoked = "revoked"


class MembershipRole(enum.Enum):
    """Role of a staff member within a school."""

    teacher = "teacher"
    school_admin = "school_admin"


class UploadStatus(enum.Enum):
    """Processing state of a student upload."""

    pending = "pending"
    processing = "processing"
    complete = "complete"
    failed = "failed"


class ReviewStatus(enum.Enum):
    """State of a review-queue item."""

    open = "open"
    resolved = "resolved"
    dismissed = "dismissed"


class ReviewReason(enum.Enum):
    """Why a question result was flagged for teacher review."""

    low_confidence = "low_confidence"
    plagiarism_flag = "plagiarism_flag"
    ai_detection_flag = "ai_detection_flag"
    manual = "manual"


class NotificationType(enum.Enum):
    """Category of a user notification."""

    grade_ready = "grade_ready"
    announcement = "announcement"
    streak_warning = "streak_warning"
    study_plan_reminder = "study_plan_reminder"
    at_risk_alert = "at_risk_alert"


class XpSource(enum.Enum):
    """Event type that generated an XP award."""

    paper_corrected = "paper_corrected"
    quiz_completed = "quiz_completed"
    flashcard_reviewed = "flashcard_reviewed"
    study_session_completed = "study_session_completed"


class QuizKind(enum.Enum):
    """What a ``quizzes`` row *is*, and therefore which owner column it uses (D4.6 §1).

    ``teacher`` is the P3.5 quiz a teacher builds and assigns to a class; the
    other three are platform-assembled and owned by the student they were
    assembled for. ``ck_quizzes_kind_owner`` ties the two together in the
    database: ``kind = 'teacher'`` exactly when ``teacher_id`` is set.

    **This is a label, not a tenancy filter** (D4.6 §3). Every query scopes on
    an owner/target predicate — ``teacher_id = :caller``, ``class_id IN
    (:enrolled)``, ``student_id = :caller``. ``kind`` may only *narrow* a
    query that is already owner-scoped, and only as a positive allowlist
    (``kind IN (...)``): ``kind != 'teacher'`` fails open the day a fifth kind
    is added.
    """

    teacher = "teacher"
    placement = "placement"
    practice = "practice"
    study_plan = "study_plan"


class QuizStatus(enum.Enum):
    """Lifecycle state of a teacher-built quiz (P3.5, ``docs/quiz-model.md`` §1.1).

    ``draft -> assigned -> closed -> archived``, plus ``draft -> archived``
    (an abandoned draft). No transition ever goes backwards: an assigned quiz
    whose questions a teacher wants to change is duplicated into a new draft
    rather than edited in place, so a live quiz never changes under students
    mid-attempt (§1.4).
    """

    draft = "draft"
    assigned = "assigned"
    closed = "closed"
    archived = "archived"


class QuizQuestionStatus(enum.Enum):
    """Whether a materialized :class:`quiz_questions` row is live or curated out."""

    included = "included"
    removed = "removed"  # curated out in step 5; row is kept (§1.5)


class QuizSubmissionStatus(enum.Enum):
    """Lifecycle state of a student's attempt at an assigned quiz."""

    not_started = "not_started"
    in_progress = "in_progress"
    submitted = "submitted"
    marked = "marked"


class QuestionSource(enum.Enum):
    """Provenance of a :class:`question_bank` row."""

    past_paper = "past_paper"
    generated = "generated"
    teacher_upload = "teacher_upload"


class QuestionDifficulty(enum.Enum):
    """Difficulty band of a question.

    Deliberately identical to :data:`lemely.core.difficulty.Band` and to
    ``GeneratedQuestion.difficulty``'s ``Literal`` — one vocabulary, pinned by
    ``tests/test_db_schema.py``'s vocabulary-agreement test so the three can
    never drift apart. A generated question's band is stored verbatim, never
    re-derived (``docs/quiz-model.md`` §1.1).
    """

    foundation = "foundation"
    standard = "standard"
    challenge = "challenge"


class DifficultySource(enum.Enum):
    """How a :class:`question_bank` row's ``difficulty`` was determined."""

    declared_by_generator = "declared_by_generator"
    inferred_from_marks = "inferred_from_marks"
    teacher_set = "teacher_set"


class AttemptOrigin(enum.Enum):
    """What kind of assessment produced an :class:`Attempt` row.

    Quiz marks are written as ``Attempt`` rows but carry no grade boundaries
    (a ten-question quiz has no grade claim to make); this column is what
    lets grade-bearing consumers (``grade_distribution``, ``cohort_trend``,
    ``at_risk._check_below_target``, ...) exclude quiz attempts in exactly
    one place rather than re-deriving "is this grade-bearing" per consumer
    (``docs/quiz-model.md`` §1.2).
    """

    past_paper = "past_paper"
    quiz = "quiz"
    custom_paper = "custom_paper"  # T-11, marked through the same path


# ---------------------------------------------------------------------------
# Shared ORM mixins
# ---------------------------------------------------------------------------


class TimestampMixin:
    """Adds ``created_at`` / ``updated_at`` columns to an ORM model.

    Both columns carry ``timezone=True`` and are server-defaulted to
    ``now()``; ``updated_at`` is also updated automatically on every row
    modification via ``onupdate``.
    """

    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
        nullable=False,
    )


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------

__all__ = [
    "SESSION_MONTH_LABELS",
    "AttemptOrigin",
    "BoundarySource",
    "ConfidenceBand",
    "DifficultySource",
    "ExamBoard",
    "MarkerSource",
    "MembershipRole",
    "NotificationType",
    "PlanInterval",
    "QualificationLevel",
    "QuestionDifficulty",
    "QuestionSource",
    "QuizKind",
    "QuizQuestionStatus",
    "QuizStatus",
    "QuizSubmissionStatus",
    "ReviewReason",
    "ReviewStatus",
    "Role",
    "SeatStatus",
    "SessionMonth",
    "SubscriptionStatus",
    "TimestampMixin",
    "UploadStatus",
    "XpSource",
]
