"""ORM model registry.

Every model module must be imported for :attr:`lemely.db.Base.metadata` to be
complete (Alembic autogenerate and ``create_all`` only see imported models).
:func:`import_all_models` is the single place that imports them all; Alembic's
``env.py`` and the test harness call it so no model is ever silently missed.
"""

from __future__ import annotations

# Re-export model classes for convenient ``from lemely.db.models import User`` usage.
# These imports must come before import_all_models so they are always available
# regardless of whether the caller has already triggered the lazy imports.
from lemely.db.models.academic import MarkScheme, Paper, Subject
from lemely.db.models.attempts import Attempt, QuestionResult, Upload, WeaknessRecord
from lemely.db.models.billing import PlanTier, Subscription
from lemely.db.models.engagement import Streak, XpEvent
from lemely.db.models.enums import (
    SESSION_MONTH_LABELS,
    AttemptOrigin,
    BoundarySource,
    ConfidenceBand,
    DifficultySource,
    ExamBoard,
    MarkerSource,
    MembershipRole,
    NotificationType,
    PlanInterval,
    QuestionDifficulty,
    QuestionSource,
    QuizQuestionStatus,
    QuizStatus,
    QuizSubmissionStatus,
    ReviewReason,
    ReviewStatus,
    Role,
    SeatStatus,
    SessionMonth,
    SubscriptionStatus,
    TimestampMixin,
    UploadStatus,
    XpSource,
)
from lemely.db.models.ops import (
    Announcement,
    AtRiskAcknowledgement,
    Notification,
    NotificationPreference,
    ReviewQueueItem,
)
from lemely.db.models.orgs import ClassEnrollment, School, SchoolClass, SchoolMembership, Seat
from lemely.db.models.quizzes import (
    QuestionBank,
    Quiz,
    QuizAnswer,
    QuizAssignment,
    QuizQuestion,
    QuizSubmission,
)
from lemely.db.models.users import Device, ParentChildLink, User


def import_all_models() -> None:
    """Import every ORM model module so ``Base.metadata`` is fully populated.

    New model modules are added here as the schema grows. Imports are performed
    lazily inside the function to avoid import-time cycles; the module-level
    re-exports above already trigger the imports when this package is loaded
    directly, but Alembic's env.py calls this function explicitly.
    """
    from lemely.db.models import (  # noqa: F401
        academic,
        attempts,
        billing,
        engagement,
        ops,
        orgs,
        quizzes,
        users,
    )


__all__ = [
    "SESSION_MONTH_LABELS",
    # Models
    "Announcement",
    "AtRiskAcknowledgement",
    "Attempt",
    # Enums and mixins
    "AttemptOrigin",
    "BoundarySource",
    "ClassEnrollment",
    "ConfidenceBand",
    "Device",
    "DifficultySource",
    "ExamBoard",
    "MarkScheme",
    "MarkerSource",
    "MembershipRole",
    "Notification",
    "NotificationPreference",
    "NotificationType",
    "Paper",
    "ParentChildLink",
    "PlanInterval",
    "PlanTier",
    "QuestionBank",
    "QuestionDifficulty",
    "QuestionResult",
    "QuestionSource",
    "Quiz",
    "QuizAnswer",
    "QuizAssignment",
    "QuizQuestion",
    "QuizQuestionStatus",
    "QuizStatus",
    "QuizSubmission",
    "QuizSubmissionStatus",
    "ReviewQueueItem",
    "ReviewReason",
    "ReviewStatus",
    "Role",
    "School",
    "SchoolClass",
    "SchoolMembership",
    "Seat",
    "SeatStatus",
    "SessionMonth",
    "Streak",
    "Subject",
    "Subscription",
    "SubscriptionStatus",
    "TimestampMixin",
    "Upload",
    "UploadStatus",
    "User",
    "WeaknessRecord",
    "XpEvent",
    "XpSource",
    # Registry function
    "import_all_models",
]
