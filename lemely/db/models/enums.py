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
    "BoundarySource",
    "ConfidenceBand",
    "ExamBoard",
    "MarkerSource",
    "MembershipRole",
    "NotificationType",
    "PlanInterval",
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
