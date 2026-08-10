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
from lemely.db.models.academic import ExamDate, MarkScheme, Paper, Subject
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
    FriendshipStatus,
    MarkerSource,
    MembershipRole,
    NotificationType,
    PlanInterval,
    QualificationLevel,
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
from lemely.db.models.flashcards import (
    CardSource,
    DeckOrigin,
    Flashcard,
    FlashcardDeck,
    FlashcardReview,
)
from lemely.db.models.flashcards import ReviewGrade as FlashcardReviewGrade
from lemely.db.models.ops import (
    Announcement,
    AnnouncementRead,
    AtRiskAcknowledgement,
    Notification,
    NotificationPreference,
    ReviewQueueItem,
)
from lemely.db.models.orgs import ClassEnrollment, School, SchoolClass, SchoolMembership, Seat
from lemely.db.models.profiles import (
    StudentConfidenceRating,
    StudentEnrolmentPaper,
    StudentProfile,
    StudentSubjectEnrolment,
)
from lemely.db.models.quizzes import (
    QuestionBank,
    Quiz,
    QuizAnswer,
    QuizAssignment,
    QuizQuestion,
    QuizSubmission,
)
from lemely.db.models.study_plan import StudyPlan as StudyPlanTable
from lemely.db.models.study_plan import StudyPlanActivityType
from lemely.db.models.study_plan import StudyPlanSession as StudyPlanSessionTable
from lemely.db.models.users import Device, Friendship, ParentChildLink, User


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
        flashcards,
        ops,
        orgs,
        profiles,
        quizzes,
        study_plan,
        users,
    )


__all__ = [
    "SESSION_MONTH_LABELS",
    # Models
    "Announcement",
    "AnnouncementRead",
    "AtRiskAcknowledgement",
    "Attempt",
    # Enums and mixins
    "AttemptOrigin",
    "BoundarySource",
    "CardSource",
    "ClassEnrollment",
    "ConfidenceBand",
    "DeckOrigin",
    "Device",
    "DifficultySource",
    "ExamBoard",
    "ExamDate",
    "Flashcard",
    "FlashcardDeck",
    "FlashcardReview",
    "FlashcardReviewGrade",
    "Friendship",
    "FriendshipStatus",
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
    "QualificationLevel",
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
    "StudentConfidenceRating",
    "StudentEnrolmentPaper",
    "StudentProfile",
    "StudentSubjectEnrolment",
    "StudyPlanActivityType",
    "StudyPlanSessionTable",
    "StudyPlanTable",
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
