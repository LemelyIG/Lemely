"""ORM models for student onboarding data (P4.3, D4.5).

Four additive tables so the study-plan/at-risk engines have real
whole-person facts (S-02) and per-subject targets (S-01) to work from,
instead of the study-plan builder's previous hand-typed
:class:`~lemely.core.study.StudentProfile` placeholder.

**Everything the onboarding spec calls skippable is nullable.** S-02 allows
"skip for now" on everything non-essential, and a study plan must be able to
say "we do not know your weekly study time" rather than invent a default
that looks like an answer the student gave. A skipped field is ``NULL``,
never a sentinel or a zero (D4.5).

**Target grades are keyed per subject, not scalar** (:class:`StudentSubjectEnrolment`),
because :func:`lemely.core.at_risk.assess_at_risk` now resolves a target
against the subject of the record it is comparing (D4.5) — a single
student-wide target grade would compare a physics paper against a maths
target the moment a student enrols in two subjects.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from lemely.db.base import Base
from lemely.db.models.enums import QualificationLevel, SessionMonth, TimestampMixin


class StudentProfile(TimestampMixin, Base):
    """The whole-person onboarding facts S-02 collects. One row per student.

    Keyed directly on ``user_id`` — no synthetic ``id`` — mirroring
    :class:`~lemely.db.models.ops.NotificationPreference`'s shape exactly: a
    profile has no reason to be addressed by anything other than the user it
    belongs to.

    Unlike :class:`~lemely.db.notification_prefs_repo.NotificationPreferencesService.get`
    (which never materialises a row), this table's row is created on first
    touch by :meth:`~lemely.db.student_profile_repo.StudentProfileService.get_or_create_profile`
    — see that method's docstring for why the two diverge: enrolments hang
    off this row by foreign key, so onboarding needs a real row to attach
    them to, while notification prefs has no child table depending on its
    existence.
    """

    __tablename__ = "student_profiles"
    __table_args__ = (
        sa.CheckConstraint(
            "weekly_study_hours IS NULL OR (weekly_study_hours >= 0 AND weekly_study_hours <= 80)",
            name="ck_student_profiles_weekly_study_hours_range",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    qualification_level: Mapped[QualificationLevel | None] = mapped_column(
        sa.Enum(QualificationLevel, name="qualificationlevel"),
        nullable=True,
    )
    grade_level: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    """Free-text form/year level (e.g. "Year 11"); not a controlled vocabulary."""
    school_name: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    has_external_lessons: Mapped[bool | None] = mapped_column(sa.Boolean, nullable=True)
    """Tri-state: ``NULL`` means "not answered", never defaulted to ``False`` —
    a default would silently assert "no external lessons" for a student who
    simply skipped the question (D4.5)."""
    weekly_study_hours: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    onboarding_completed_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    leaderboard_opt_out: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.false()
    )
    """D5.1 §9: absent from every board when ``True``, including boards their
    own friends see. Enforced in ``lemely.db.leaderboard_repo``'s query WHERE
    clause, never filtered in a DTO/route layer — see that module's docstring."""

    # No ORM relationship to StudentSubjectEnrolment here: that table's
    # user_id is its own independent FK to users.id (see class docstring),
    # not to this table's PK, so there is no real FK path a relationship()
    # could traverse. StudentProfileService queries enrolments by user_id
    # directly instead.


class StudentSubjectEnrolment(TimestampMixin, Base):
    """One (student, subject) enrolment: target grade + exam session (S-01).

    Unique on ``(user_id, subject_code)`` — a student has at most one
    enrolment per subject; re-submitting the onboarding form for a subject
    already enrolled is an update, not a duplicate row (see
    :meth:`~lemely.db.student_profile_repo.StudentProfileService.upsert_enrolment`).
    """

    __tablename__ = "student_subject_enrolments"
    __table_args__ = (
        sa.UniqueConstraint(
            "user_id",
            "subject_code",
            name="uq_student_subject_enrolments_user_id_subject_code",
        ),
        sa.Index("ix_student_subject_enrolments_user_id", "user_id"),
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
    subject_code: Mapped[str] = mapped_column(
        sa.String,
        sa.ForeignKey("subjects.code"),
        nullable=False,
    )
    target_grade: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    """A ``lemely.core.history.GRADE_ORDER`` member; validated at the service
    layer, not a PG enum — same rationale as ``Quiz.target_grade``
    (``lemely/db/models/quizzes.py``): grade ladders are board-specific and
    ``GRADE_ORDER`` is already the single Python-side source of truth."""
    session_month: Mapped[SessionMonth | None] = mapped_column(
        sa.Enum(SessionMonth, name="sessionmonth"),
        nullable=True,
    )
    session_year: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)

    papers: Mapped[list[StudentEnrolmentPaper]] = relationship(
        "StudentEnrolmentPaper",
        back_populates="enrolment",
        cascade="all, delete-orphan",
    )
    confidence_ratings: Mapped[list[StudentConfidenceRating]] = relationship(
        "StudentConfidenceRating",
        back_populates="enrolment",
        cascade="all, delete-orphan",
    )


class StudentEnrolmentPaper(TimestampMixin, Base):
    """A specific CAIE paper number (e.g. P2, P4) a student intends to sit.

    ``paper_number`` is a plain integer, not a FK to :class:`~lemely.db.models.academic.Paper`:
    a student picks a paper *number* they intend to sit independent of any
    specific session's ``Paper`` row (which is keyed on board/session/variant,
    not a student's intent).
    """

    __tablename__ = "student_enrolment_papers"
    __table_args__ = (
        sa.UniqueConstraint(
            "enrolment_id",
            "paper_number",
            name="uq_student_enrolment_papers_enrolment_id_paper_number",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    enrolment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("student_subject_enrolments.id", ondelete="CASCADE"),
        nullable=False,
    )
    paper_number: Mapped[int] = mapped_column(sa.Integer, nullable=False)

    enrolment: Mapped[StudentSubjectEnrolment] = relationship(
        "StudentSubjectEnrolment", back_populates="papers"
    )


class StudentConfidenceRating(TimestampMixin, Base):
    """One (enrolment, topic) self-assessment slider, 1 (low) to 5 (high).

    ``topic`` holds a P4.2 syllabus topic label (e.g. "4.3 Electric
    circuits") — that vocabulary is produced by the deterministic classifier
    in ``lemely/core`` (P4.2), not imported here; this model just stores the
    string so the onboarding questionnaire, the question bank, and the
    weakness engine share one vocabulary rather than three (D4.5).
    """

    __tablename__ = "student_confidence_ratings"
    __table_args__ = (
        sa.CheckConstraint(
            "rating >= 1 AND rating <= 5",
            name="ck_student_confidence_ratings_rating_range",
        ),
        sa.UniqueConstraint(
            "enrolment_id",
            "topic",
            name="uq_student_confidence_ratings_enrolment_id_topic",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    enrolment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("student_subject_enrolments.id", ondelete="CASCADE"),
        nullable=False,
    )
    topic: Mapped[str] = mapped_column(sa.String, nullable=False)
    rating: Mapped[int] = mapped_column(sa.Integer, nullable=False)

    enrolment: Mapped[StudentSubjectEnrolment] = relationship(
        "StudentSubjectEnrolment", back_populates="confidence_ratings"
    )


__all__ = [
    "StudentConfidenceRating",
    "StudentEnrolmentPaper",
    "StudentProfile",
    "StudentSubjectEnrolment",
]
