"""ORM models for review queue, announcements, notifications, and acks.

Covers the review queue, announcements, notifications, and at-risk
acknowledgements tables.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from lemely.core.at_risk import AtRiskReason
from lemely.db.base import Base
from lemely.db.models.enums import (
    NotificationType,
    ReviewReason,
    ReviewStatus,
    TimestampMixin,
)


class ReviewQueueItem(TimestampMixin, Base):
    """A question result that requires teacher review."""

    __tablename__ = "review_queue"
    __table_args__ = (sa.Index("ix_review_queue_status", "status"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    attempt_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("attempts.id", ondelete="CASCADE"),
        nullable=False,
    )
    question_result_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("question_results.id"),
        nullable=True,
    )
    reason: Mapped[ReviewReason] = mapped_column(
        sa.Enum(ReviewReason, name="reviewreason"),
        nullable=False,
    )
    status: Mapped[ReviewStatus] = mapped_column(
        sa.Enum(ReviewStatus, name="reviewstatus"),
        nullable=False,
        server_default=sa.text("'open'::reviewstatus"),
    )
    assigned_teacher_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("users.id"),
        nullable=True,
    )
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("users.id"),
        nullable=True,
    )
    resolution_note: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)

    question_result: Mapped[object] = relationship(
        "QuestionResult", back_populates="review_queue_items"
    )


class Announcement(TimestampMixin, Base):
    """An announcement published by a teacher or school admin."""

    __tablename__ = "announcements"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    author_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("users.id"),
        nullable=False,
    )
    school_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("schools.id"),
        nullable=True,
    )
    class_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("classes.id"),
        nullable=True,
    )
    title: Mapped[str] = mapped_column(sa.String, nullable=False)
    body: Mapped[str] = mapped_column(sa.Text, nullable=False)
    publish_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)


class Notification(TimestampMixin, Base):
    """An in-app notification delivered to a specific user."""

    __tablename__ = "notifications"
    __table_args__ = (sa.Index("ix_notifications_user_id_read_at", "user_id", "read_at"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    type: Mapped[NotificationType] = mapped_column(
        sa.Enum(NotificationType, name="notificationtype"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(sa.String, nullable=False)
    body: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    payload: Mapped[dict] = mapped_column(  # type: ignore[type-arg]
        JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
    )
    read_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)


class AtRiskAcknowledgement(TimestampMixin, Base):
    """A teacher's "seen this" tag on one (student, reason) at-risk flag (D3.5, T-06).

    **Why this table exists at all.** At-risk flags are derived, not stored —
    :func:`lemely.core.at_risk.assess_at_risk` recomputes them from history on
    every request (D3.3), so there is no flag row an acknowledgement could
    reference by id. This table is the *only* persistent state the
    acknowledge-with-a-note action needs: who (``teacher_id``) acknowledged
    which signal (``student_id``, ``reason``) against what evidence
    (``evidence_fingerprint``), with an optional note.

    **``evidence_fingerprint`` is the whole mechanism that keeps an
    acknowledgement honest.** It is not a bookkeeping nicety — a stored ack
    with no fingerprint would silently swallow a student's *next* decline too
    (permanent-mute failure mode D3.5 rejects). A flag reads as acknowledged
    only when a row exists here **and** its fingerprint equals
    :func:`~lemely.core.at_risk.flag_fingerprint` of the flag currently
    firing; new evidence (a further decline, a fresh submission ending an
    inactivity streak) changes the fingerprint and the flag re-surfaces
    unacknowledged, exactly like a flag that was never acknowledged at all.

    **Unique on ``(teacher_id, student_id, reason)``, not a fourth column.**
    Per-teacher scoping is deliberate (D3.5): teacher A acknowledging a
    student does not blind teacher B, who carries their own responsibility
    for the same student in a different class. An upsert against this key
    (rather than always inserting) means re-acknowledging the *same*
    evidence just refreshes ``note``/``updated_at`` rather than
    accumulating rows — see :mod:`lemely.db.at_risk_repo`.

    **``reason`` reuses the core** :class:`~lemely.core.at_risk.AtRiskReason`
    **enum directly, not a private db-layer copy.** Every other native-enum
    column in this package (``ReviewReason``, ``NotificationType``, ...) is
    declared in :mod:`lemely.db.models.enums`, which might suggest a mirrored
    ``AtRiskReason`` belongs there too. It deliberately does not: the import
    would run the wrong direction (``lemely.db.models.enums`` importing a
    *rules-engine* concept out of ``lemely.core.at_risk``, rather than the db
    layer depending on core, which is how every other core/db coupling in
    this codebase already runs — see ``lemely.db.history_repo``,
    ``lemely.db.review_repo``, both of which import Pydantic models straight
    out of ``lemely.core``). A second, hand-copied ``AtRiskReason`` in
    ``enums.py`` would be exactly the drift D2.2's "single-sourced constant"
    discipline exists to prevent: the day ``lemely.core.at_risk`` gains a
    fourth rule, this table would silently keep accepting only three reason
    values until someone remembered to update a second definition by hand.
    ``tests/test_at_risk_repo.py`` pins the two representations in sync
    (every :class:`AtRiskReason` member round-trips through the Postgres
    enum) so this can never quietly drift regardless.

    This import is **not** a layering violation: ``import-linter``'s layered
    contract (``pyproject.toml``) governs only ``lemely.app`` / ``lemely.io``
    / ``lemely.core`` (``lemely.db`` is a separate top-level package the
    contract does not enumerate), and ``lemely.db`` already imports
    Pydantic/enum types out of ``lemely.core`` throughout
    (``history_repo.py``, ``review_repo.py``, ``attempt_repo.py``) — this is
    the same, already-established direction, not a new one.
    """

    __tablename__ = "at_risk_acknowledgements"
    __table_args__ = (
        sa.UniqueConstraint(
            "teacher_id",
            "student_id",
            "reason",
            name="uq_at_risk_acknowledgements_teacher_id_student_id_reason",
        ),
    )

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
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    reason: Mapped[AtRiskReason] = mapped_column(
        sa.Enum(AtRiskReason, name="atriskreason"),
        nullable=False,
    )
    # The evidence identity this ack covers — see class docstring. Always the
    # output of flag_fingerprint(); never hand-constructed by a caller.
    evidence_fingerprint: Mapped[str] = mapped_column(sa.Text, nullable=False)
    # Teacher-facing only, never surfaced on any student/parent route (D3.5) —
    # unlike QuestionResult.teacher_note (P3.4/T-08), which is explicitly a
    # note *to* the student.
    note: Mapped[str | None] = mapped_column(sa.Text, nullable=True)


__all__ = ["Announcement", "AtRiskAcknowledgement", "Notification", "ReviewQueueItem"]
