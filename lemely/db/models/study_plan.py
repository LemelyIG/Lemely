"""ORM models for the persisted adaptive study plan (P4.7 chunk B).

Two tables, additive only (migration ``0012_study_plans``):

* :class:`StudyPlan` — one generated week's plan for one (student, subject).
  ``week_start`` is the Monday-aligned ISO week the plan was generated for
  (see :func:`lemely.db.study_plan_repo._week_start`) — the key that decides
  what "the current week" means for regeneration and lookup.
* :class:`StudyPlanSession` — one concrete scheduled session within a plan.

**Weekly regeneration supersedes, never mutates** (P4.7 chunk B plan).
Calling :meth:`~lemely.db.study_plan_repo.StudyPlanService.generate` again
for the same ``(user_id, subject_code, week_start)`` sets the previous row's
``superseded_at`` and inserts a fresh one — the old plan and its sessions
(including any completion a student already recorded) are never rewritten,
so last week stays auditable and a completed session stays a true record of
what was actually completed. ``uq_study_plans_active`` (partial unique,
``WHERE superseded_at IS NULL``) makes "at most one active plan per
(student, subject, week)" a database invariant, not a convention a bug
could quietly violate.

**A refused plan is persisted as a refusal, not silently as an empty
successful one.** ``available``/``reason`` mirror
:class:`lemely.core.study.StudyPlan`'s honesty fields verbatim — a
``no_signal`` refusal has ``available=False`` and an empty session list, and
is never indistinguishable on read from the *real* "nothing to schedule this
week" state (``available=True``, empty sessions) — see
:mod:`lemely.core.study_plan`'s docstring, D4.12.

**XP is P5, not here.** ``StudyPlanSession.completed_at`` is the seam a
future XP award reads; nothing in this module computes or stores points,
streaks, or XP events for completing a session.

**``StudyPlanActivityType`` mirrors (does not import)
``lemely.core.study.ActivityType``** — no module under ``lemely.db.models``
imports ``lemely.core`` (see ``lemely/db/models/flashcards.py``'s identical
choice for ``ReviewGrade``, and every other enum in this package); the four
members are declared here a second time on purpose.
``tests/test_study_plan_schema.py`` pins that the two never drift apart.
"""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from lemely.db.base import Base
from lemely.db.models.enums import TimestampMixin


class StudyPlanActivityType(enum.Enum):
    """Mirrors :class:`lemely.core.study.ActivityType` member-for-member.

    See the module docstring for why this is a second declaration rather
    than an import.
    """

    practice = "practice"
    flashcards = "flashcards"
    past_paper = "past_paper"
    review = "review"


class StudyPlan(TimestampMixin, Base):
    """One generated week's study plan for one (student, subject).

    Named ``StudyPlan`` to match the table's domain name, like every other
    model in this package — the same bare name as the pydantic model
    :class:`lemely.core.study.StudyPlan`. The two never appear unaliased in
    the same module: ``lemely/db/study_plan_repo.py`` imports this one as
    ``DbStudyPlan``, the identical pattern
    ``lemely/db/models/flashcards.py`` already uses for its ``ReviewGrade``.

    ``reason`` mirrors :class:`lemely.core.study.StudyPlanUnavailableReason`
    by value (a plain ``varchar``, not a second Postgres enum — today it has
    exactly one member, ``"no_signal"``, and a growing machine-readable
    reason vocabulary elsewhere in this codebase (P4.5/P4.6) is always a
    string column for the same reason: it is read by the frontend, never
    branched on inside SQL).
    """

    __tablename__ = "study_plans"
    __table_args__ = (
        sa.Index("ix_study_plans_user_subject_week", "user_id", "subject_code", "week_start"),
        sa.Index(
            "uq_study_plans_active",
            "user_id",
            "subject_code",
            "week_start",
            unique=True,
            postgresql_where=sa.text("superseded_at IS NULL"),
        ),
    )

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
    subject_code: Mapped[str] = mapped_column(sa.String, nullable=False)
    week_start: Mapped[date] = mapped_column(sa.Date, nullable=False)
    """The Monday of the ISO week this plan was generated for — the identity
    of "the current week" for regeneration and lookup (see
    :func:`lemely.db.study_plan_repo._week_start`)."""
    weekly_hours: Mapped[float] = mapped_column(sa.Float, nullable=False)
    available: Mapped[bool] = mapped_column(sa.Boolean, nullable=False)
    reason: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    generated_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    superseded_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    """``NULL`` means this is the active plan for its week. Set by a later
    :meth:`~lemely.db.study_plan_repo.StudyPlanService.generate` call for the
    same ``(user_id, subject_code, week_start)`` — the row itself, and every
    one of its sessions, is otherwise never modified again."""

    sessions: Mapped[list[StudyPlanSession]] = relationship(
        "StudyPlanSession", back_populates="plan", cascade="all, delete-orphan"
    )


class StudyPlanSession(TimestampMixin, Base):
    """One concrete scheduled session within a :class:`StudyPlan`.

    ``subject_code`` is deliberately not repeated here — a plan is
    single-subject (:mod:`lemely.core.study_plan`'s ``build_study_plan``
    signature), so it lives once, on the parent row.
    """

    __tablename__ = "study_plan_sessions"
    __table_args__ = (sa.Index("ix_study_plan_sessions_plan_id_date", "plan_id", "date"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("study_plans.id", ondelete="CASCADE"),
        nullable=False,
    )
    date: Mapped[date] = mapped_column(sa.Date, nullable=False)
    topic: Mapped[str] = mapped_column(sa.String, nullable=False)
    activity_type: Mapped[StudyPlanActivityType] = mapped_column(
        sa.Enum(StudyPlanActivityType, name="studyplanactivitytype"),
        nullable=False,
    )
    duration_minutes: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    focus: Mapped[str] = mapped_column(sa.Text, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    """``NULL`` until the student marks this session complete. The P5 XP
    seam: nothing in this module reads it for points/streaks (see the module
    docstring)."""

    plan: Mapped[StudyPlan] = relationship("StudyPlan", back_populates="sessions")


__all__ = ["StudyPlan", "StudyPlanActivityType", "StudyPlanSession"]
