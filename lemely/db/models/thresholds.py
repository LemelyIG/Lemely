r"""ORM models for CAIE grade thresholds.

Two tables, because Cambridge publishes two tables and they mean different
things. ``component_thresholds`` is per paper: it is what a single marked paper
is graded against, and **Grade A\* does not exist at this level** — the source
documents say so in those words. ``option_thresholds`` is per weighted
combination of components, and is the only place A\* appears.

Raw marks are stored with ``max_mark`` rather than pre-computed percentages, so
every stored number is one a human can check against the document.
:class:`~lemely.io.grade_boundaries.GradeBoundaryStore` divides at read time.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from lemely.db.base import Base
from lemely.db.models.enums import ExamBoard, SessionMonth, TimestampMixin


class ComponentThreshold(TimestampMixin, Base):
    """Minimum raw marks per grade for one component in one session."""

    __tablename__ = "component_thresholds"
    __table_args__ = (
        sa.UniqueConstraint(
            "board",
            "subject_code",
            "session_month",
            "session_year",
            "paper_number",
            "paper_variant",
            name="uq_component_thresholds_identity",
        ),
        sa.Index("ix_component_thresholds_lookup", "board", "subject_code", "session_year"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
    )
    board: Mapped[ExamBoard] = mapped_column(
        sa.Enum(ExamBoard, name="examboard"),
        nullable=False,
        server_default=sa.text("'caie'::examboard"),
    )
    subject_code: Mapped[str] = mapped_column(sa.String, nullable=False)
    session_month: Mapped[SessionMonth] = mapped_column(
        sa.Enum(SessionMonth, name="sessionmonth"), nullable=False
    )
    session_year: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    paper_number: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    paper_variant: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    max_mark: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    #: ``{"C": 42, "D": 34, ...}`` — grade → minimum raw mark.
    thresholds: Mapped[dict[str, int]] = mapped_column(JSONB, nullable=False)
    #: True when every grade above was confirmed against the official PDF.
    #: False means the row came from ciegt alone and only the weaker
    #: "drop anything at or below zero raw marks" filter was applied. Nothing
    #: may cite Cambridge as the source of an unverified row.
    verified: Mapped[bool] = mapped_column(sa.Boolean, nullable=False)
    source_url: Mapped[str] = mapped_column(sa.String, nullable=False)


class OptionThreshold(TimestampMixin, Base):
    r"""Syllabus-level thresholds for one weighted option, including A\*."""

    __tablename__ = "option_thresholds"
    __table_args__ = (
        sa.UniqueConstraint(
            "board",
            "subject_code",
            "session_month",
            "session_year",
            "option_code",
            name="uq_option_thresholds_identity",
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
    subject_code: Mapped[str] = mapped_column(sa.String, nullable=False)
    session_month: Mapped[SessionMonth] = mapped_column(
        sa.Enum(SessionMonth, name="sessionmonth"), nullable=False
    )
    session_year: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    #: e.g. ``"BX"`` — Cambridge's own label for the combination.
    option_code: Mapped[str] = mapped_column(sa.String, nullable=False)
    #: e.g. ``[21, 41, 51]``.
    component_numbers: Mapped[list[int]] = mapped_column(JSONB, nullable=False)
    #: Nullable: the pre-2020 layout omits this column entirely.
    max_mark_after_weighting: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    thresholds: Mapped[dict[str, int]] = mapped_column(JSONB, nullable=False)
    source_url: Mapped[str] = mapped_column(sa.String, nullable=False)
