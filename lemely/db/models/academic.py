"""ORM models for subjects, papers, and mark schemes."""

from __future__ import annotations

import uuid
from datetime import date

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from lemely.db.base import Base
from lemely.db.models.enums import ExamBoard, QualificationLevel, SessionMonth, TimestampMixin


class Subject(TimestampMixin, Base):
    """An examinable subject identified by its CAIE syllabus code."""

    __tablename__ = "subjects"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    code: Mapped[str] = mapped_column(sa.String, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(sa.String, nullable=False)
    board: Mapped[ExamBoard] = mapped_column(
        sa.Enum(ExamBoard, name="examboard"),
        nullable=False,
        server_default=sa.text("'caie'::examboard"),
    )
    active: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, server_default=sa.text("true"))
    qualification_level: Mapped[QualificationLevel | None] = mapped_column(
        sa.Enum(QualificationLevel, name="qualificationlevel"), nullable=True
    )
    syllabus_version: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    # The syllabus PDF the topic tree was transcribed from. Nullable because a
    # subject may exist before its taxonomy does; `get_taxonomy` returns None
    # for such a subject rather than building a `SyllabusTaxonomy` whose
    # required `source_url` would have to be faked.
    source_url: Mapped[str | None] = mapped_column(sa.String, nullable=True)

    papers: Mapped[list[Paper]] = relationship(
        "Paper", back_populates="subject", cascade="all, delete-orphan"
    )


class Paper(TimestampMixin, Base):
    """A specific exam paper uniquely identified by board/subject/session/variant."""

    __tablename__ = "papers"
    __table_args__ = (
        sa.UniqueConstraint(
            "board",
            "subject_code",
            "session_month",
            "session_year",
            "paper_number",
            "paper_variant",
            name="uq_papers_identity",
        ),
        sa.Index(
            "ix_papers_board_subject_code_session",
            "board",
            "subject_code",
            "session_month",
            "session_year",
            "paper_number",
            "paper_variant",
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
    subject_code: Mapped[str] = mapped_column(
        sa.String,
        sa.ForeignKey("subjects.code"),
        nullable=False,
    )
    session_month: Mapped[SessionMonth] = mapped_column(
        sa.Enum(SessionMonth, name="sessionmonth"),
        nullable=False,
    )
    session_year: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    paper_number: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    paper_variant: Mapped[int] = mapped_column(sa.Integer, nullable=False)

    subject: Mapped[Subject] = relationship("Subject", back_populates="papers")
    mark_scheme: Mapped[MarkScheme | None] = relationship(
        "MarkScheme",
        back_populates="paper",
        uselist=False,
        cascade="all, delete-orphan",
    )


class MarkScheme(TimestampMixin, Base):
    """Parsed mark scheme for a :class:`Paper`."""

    __tablename__ = "mark_schemes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    paper_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("papers.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    maximum_mark: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    source_document: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    parsed_payload: Mapped[dict] = mapped_column(  # type: ignore[type-arg]
        JSONB, nullable=False
    )
    provenance: Mapped[str | None] = mapped_column(sa.String, nullable=True)

    paper: Mapped[Paper] = relationship("Paper", back_populates="mark_scheme")


class ExamDate(TimestampMixin, Base):
    """When one CAIE paper variant is sat, as stated by an official timetable.

    **Every row must come from a published timetable document** (D5.8). The
    table ships empty because this build has no path to one, and the honest
    empty calendar that produces is the intended behaviour, not a gap waiting
    to be filled with plausible dates — the calendar's whole purpose is a
    countdown a student plans revision around, so a fabricated date
    misinforms rather than merely disappoints (UI spec 1.4).

    ``source`` is ``NOT NULL`` for that reason: a row that cannot name the
    document it came from is indistinguishable from an invented one.

    Deliberately **not** a foreign key to :class:`Paper`. ``papers`` rows
    exist only for papers whose PDFs have been ingested, which is a property
    of the corpus, not of the exam calendar — a student sitting a paper this
    build has never downloaded still needs its date. The same reasoning
    already keeps :class:`~lemely.db.models.profiles.StudentEnrolmentPaper`
    off that FK.
    """

    __tablename__ = "exam_dates"
    __table_args__ = (
        sa.UniqueConstraint(
            "subject_code",
            "session_month",
            "session_year",
            "paper_variant",
            name="uq_exam_dates_variant",
        ),
        sa.CheckConstraint("paper_number > 0", name="ck_exam_dates_paper_number_positive"),
        sa.CheckConstraint("length(paper_variant) > 0", name="ck_exam_dates_variant_nonempty"),
        sa.CheckConstraint("length(source) > 0", name="ck_exam_dates_source_nonempty"),
        sa.Index(
            "ix_exam_dates_subject_session_paper",
            "subject_code",
            "session_month",
            "session_year",
            "paper_number",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    subject_code: Mapped[str] = mapped_column(
        sa.String,
        sa.ForeignKey("subjects.code"),
        nullable=False,
    )
    session_month: Mapped[SessionMonth] = mapped_column(
        sa.Enum(SessionMonth, name="sessionmonth"),
        nullable=False,
    )
    session_year: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    paper_number: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    """The component number a student declares in onboarding (2, 4, ...).

    Stored alongside ``paper_variant`` rather than derived from it: the read
    path can only join on what the student told us, and deriving it by
    parsing a digit out of the variant string would be a guess dressed as
    data. It comes from the source document."""
    paper_variant: Mapped[str] = mapped_column(sa.String, nullable=False)
    """The full variant as the timetable states it ("22", "41").

    The grain is the variant, not the number, because variants of one paper
    can sit on different days in different zones — storing at number grain
    would force the ingester to pick one real date and discard the others."""
    exam_date: Mapped[date] = mapped_column(sa.Date, nullable=False)
    starts_at_local: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    """Local start time as the timetable prints it, or ``None`` when it does
    not state one. A string, not a ``Time``: the document gives a wall-clock
    time in a zone this table does not model, and coercing it into a typed
    time would imply a precision about *which* zone that we do not have."""
    duration_minutes: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    source: Mapped[str] = mapped_column(sa.String, nullable=False)
    """Provenance of the row: which published timetable stated this date."""


__all__ = ["ExamDate", "MarkScheme", "Paper", "Subject"]
