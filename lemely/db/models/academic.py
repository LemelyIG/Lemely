"""ORM models for subjects, papers, and mark schemes."""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from lemely.db.base import Base
from lemely.db.models.enums import ExamBoard, SessionMonth, TimestampMixin


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


__all__ = ["MarkScheme", "Paper", "Subject"]
