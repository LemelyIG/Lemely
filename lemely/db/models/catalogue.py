"""ORM models for the syllabus catalogue: paper structure and topic taxonomy.

These tables hold what ``lemely/data/paper_timing.json`` and
``lemely/data/syllabus_topics.json`` used to hold. They are separate from
:class:`~lemely.db.models.academic.Paper`, which means "an ingested past-paper
instance" keyed by session and variant — this is the *structure* a syllabus
defines, independent of which PDFs have been downloaded.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from lemely.db.base import Base
from lemely.db.models.enums import ExamBoard, PaperTier, TimestampMixin


class SyllabusPaper(TimestampMixin, Base):
    """One paper a syllabus defines, with the timing facts placement needs."""

    __tablename__ = "syllabus_papers"
    __table_args__ = (
        sa.UniqueConstraint(
            "board", "subject_code", "paper_number", name="uq_syllabus_papers_identity"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
    )
    board: Mapped[ExamBoard] = mapped_column(
        sa.Enum(ExamBoard, name="examboard"),
        nullable=False,
        server_default=sa.text("'caie'::examboard"),
    )
    subject_code: Mapped[str] = mapped_column(
        sa.String, sa.ForeignKey("subjects.code"), nullable=False
    )
    paper_number: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    name: Mapped[str] = mapped_column(sa.String, nullable=False)
    tier: Mapped[PaperTier | None] = mapped_column(
        sa.Enum(PaperTier, name="papertier"), nullable=True
    )
    duration_minutes: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    total_marks: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    practical: Mapped[bool] = mapped_column(sa.Boolean, nullable=False)
    # Provenance is NOT NULL for the reason `ExamDate.source` is: a row that
    # cannot name the document it was transcribed from is indistinguishable
    # from an invented one.
    source_document: Mapped[str] = mapped_column(sa.String, nullable=False)
    source_url: Mapped[str] = mapped_column(sa.String, nullable=False)
    syllabus_version: Mapped[str] = mapped_column(sa.String, nullable=False)


class SubjectTopic(TimestampMixin, Base):
    """One node of a syllabus topic tree.

    ``strong`` and ``keywords`` are Lemely's authored matching vocabulary for
    the deterministic classifier, **not** syllabus content — the retired
    ``syllabus_topics.json`` said so in its own header. They are stored because
    the classifier needs them and are excluded from every DTO.
    """

    __tablename__ = "subject_topics"
    __table_args__ = (
        sa.UniqueConstraint("board", "subject_code", "code", name="uq_subject_topics_identity"),
        sa.Index("ix_subject_topics_subject", "board", "subject_code"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
    )
    board: Mapped[ExamBoard] = mapped_column(
        sa.Enum(ExamBoard, name="examboard"),
        nullable=False,
        server_default=sa.text("'caie'::examboard"),
    )
    subject_code: Mapped[str] = mapped_column(
        sa.String, sa.ForeignKey("subjects.code"), nullable=False
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("subject_topics.id", ondelete="CASCADE"), nullable=True
    )
    code: Mapped[str] = mapped_column(sa.String, nullable=False)
    name: Mapped[str] = mapped_column(sa.String, nullable=False)
    strong: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")
    )
    keywords: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")
    )
