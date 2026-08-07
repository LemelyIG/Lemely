"""ORM models for review queue, announcements, notifications, and acks.

Covers the review queue, announcements, notifications, and at-risk
acknowledgements tables.
"""

from __future__ import annotations

import uuid
from datetime import datetime, time

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
        # `values_callable` is load-bearing, not decoration (P3.7 chunk d
        # defect found by a real E2E run, not by `pytest`). Every *other*
        # native-enum column in this package (`ReviewReason`,
        # `NotificationType`, `Role`, ...) is deliberately declared with
        # lowercase member names equal to their values
        # (`low_confidence = "low_confidence"`) specifically so
        # SQLAlchemy's default enum binding — which converts a Python enum
        # instance to its DB value using `.name`, not `.value`, unless told
        # otherwise — happens to produce the right string anyway.
        # `AtRiskReason` (`lemely/core/at_risk.py`) is the one enum reused
        # directly from `lemely.core` rather than mirrored in this module's
        # own lowercase-name convention, and it uses ordinary
        # SCREAMING_SNAKE_CASE members (`DECLINING_TREND = "declining_trend"`)
        # — so without `values_callable`, every acknowledge/unacknowledge
        # query binds `"DECLINING_TREND"`, which the migration's real
        # Postgres enum (`0006_at_risk_acknowledgements`, literal lowercase
        # labels) rejects with `DataError: invalid input value for enum
        # atriskreason`. `tests/test_at_risk_repo.py` never caught this
        # because its Postgres schema comes from `Base.metadata.create_all()`
        # (see that test module), which derives the enum's DDL labels from
        # this same class using the same (buggy) default — self-consistently
        # wrong, so every unit test passed while every real,
        # Alembic-migrated stack 500'd on every acknowledge call. This does
        # not need a migration: the real DB enum type already holds the
        # correct lowercase labels (migration 0006); only the Python-side
        # bind/read conversion was wrong.
        sa.Enum(
            AtRiskReason,
            name="atriskreason",
            values_callable=lambda enum_cls: [e.value for e in enum_cls],
        ),
        nullable=False,
    )
    # The evidence identity this ack covers — see class docstring. Always the
    # output of flag_fingerprint(); never hand-constructed by a caller.
    evidence_fingerprint: Mapped[str] = mapped_column(sa.Text, nullable=False)
    # Teacher-facing only, never surfaced on any student/parent route (D3.5) —
    # unlike QuestionResult.teacher_note (P3.4/T-08), which is explicitly a
    # note *to* the student.
    note: Mapped[str | None] = mapped_column(sa.Text, nullable=True)


class NotificationPreference(TimestampMixin, Base):
    """Per-user notification toggle + quiet-hours settings (G-12, P3.6 chunk B).

    One row per user, keyed directly on ``user_id`` — no synthetic ``id``,
    unlike :class:`~lemely.db.models.engagement.Streak` (also one-row-per-user)
    which carries both; a preferences row has no reason to be addressed by
    anything other than the user it belongs to.

    **One explicit ``NOT NULL BOOLEAN DEFAULT true`` column per**
    :class:`NotificationType` **member**, not a JSONB blob and not a
    row-per-type table: this keeps every toggle typed, and the day a sixth
    notification type is added, the migration that adds its column is where
    someone has to make an explicit, reviewed decision about its default —
    a JSONB key would just silently default to "off" (missing key) with no
    migration at all. ``tests/test_db_schema.py``'s
    ``test_notification_type_enum_matches_preference_columns`` pins the two
    vocabularies together (P3.5 chunk A's three-way-pin pattern) so they can
    never drift apart.

    **Absent row reads as all-defaults and is never auto-created on read** —
    see :meth:`~lemely.db.notification_prefs_repo.NotificationPreferencesService.get`,
    which returns the defaults value directly rather than materialising a
    row; a GET must not have a write side effect.

    ``quiet_hours_start``/``quiet_hours_end`` are both nullable :class:`sa.Time`
    (time-of-day, no date/timezone component); both null means "no quiet
    hours configured". :class:`~lemely.db.notification_prefs_repo.NotificationPreferencesService`
    enforces "both or neither" — a window with only one bound set is not a
    representable state.

    **This table stores a preference, it does not deliver anything.** No
    query anywhere reads this table to decide whether to actually send/queue
    a notification, including against the quiet-hours window — that
    interpretation belongs to P5, which owns notification delivery end to
    end. G-12 also lists a "weekly summary" toggle; it has no corresponding
    :class:`NotificationType` member and nothing in this codebase emits that
    notification, so it is deliberately NOT a column here — inventing one
    would be a toggle with no backing preference to toggle. Deferred to P5.
    """

    __tablename__ = "notification_preferences"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    grade_ready: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, server_default=sa.true())
    announcement: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, server_default=sa.true())
    streak_warning: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.true()
    )
    study_plan_reminder: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.true()
    )
    at_risk_alert: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.true()
    )
    quiet_hours_start: Mapped[time | None] = mapped_column(sa.Time(), nullable=True)
    quiet_hours_end: Mapped[time | None] = mapped_column(sa.Time(), nullable=True)


__all__ = [
    "Announcement",
    "AtRiskAcknowledgement",
    "Notification",
    "NotificationPreference",
    "ReviewQueueItem",
]
