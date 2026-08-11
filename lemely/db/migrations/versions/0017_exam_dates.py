"""exam_dates table (P5.5 chunk C)

Revision ID: 0017_exam_dates
Revises: 0016_announcement_reads
Create Date: 2026-08-10 00:00:00.000000

One additive table, no existing column touched (D1.2/D1.3).

**This table ships empty, and that is the point (D5.8).** There is no CAIE
timetable data anywhere on this machine — not in ``Sources/`` (mark schemes
only) and not in the PaperScraper corpus, which fetches question papers and
grade-boundary documents and has never fetched a timetable. Real dates live
in a separate official CAIE timetable PDF this build has no path to. So the
migration creates the table and the ingestion path fills it *when a human
supplies the official document*; nothing in this build invents a row.

Inventing plausible exam dates would be worse here than on any other surface,
because the exam calendar's entire purpose is a countdown a student plans
around: a fabricated date does not degrade the feature, it actively
misinforms revision scheduling. UI spec 1.4 ("never invent precision")
applied at its sharpest.

**The grain is the paper *variant*, not the paper number.** The official
timetable states a date per component variant (``0625/22``), and variants of
the same paper number can sit on different days in different zones. Storing
at paper-number grain would have forced the ingester to pick one of several
real dates and discard the rest — invented precision arriving through the
back door. ``paper_number`` is stored alongside because that is the grain a
student declares in onboarding (``student_enrolment_papers.paper_number``,
P4.3) and is therefore the only key the read path can join on; it comes from
the source document, never computed by parsing a digit out of the variant.

``uq_exam_dates_variant`` makes ingestion idempotent by database rather than
by care — the same choice migrations 0013, 0015 and 0016 already made. A
timetable is re-published with corrections, so re-ingesting the same session
must update dates in place, never append a second row that would make the
same paper appear twice on one student's calendar.

``source`` is not decoration. Every row must be able to name the document it
came from, so a wrong date can be traced to a specific published timetable
rather than to "the database says so". A row with no provenance is exactly
the invented row this table exists to prevent, which is why the column is
``NOT NULL``.

``starts_at_local`` and ``duration_minutes`` are nullable because the
timetable does not always state both, and a missing time must read as
missing rather than as midnight.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0017_exam_dates"
down_revision: str | Sequence[str] | None = "0016_announcement_reads"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "exam_dates",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("subject_code", sa.String(), nullable=False),
        sa.Column(
            "session_month",
            # ``postgresql.ENUM``, not ``sa.Enum``: only the dialect type
            # honours ``create_type=False``, and ``sessionmonth`` already
            # exists (``student_subject_enrolments`` created it in 0009).
            # ``sa.Enum`` would silently ignore the flag and emit a
            # ``CREATE TYPE`` that fails with "type already exists".
            sa.dialects.postgresql.ENUM(
                "may_june",
                "oct_nov",
                "feb_mar",
                "specimen",
                name="sessionmonth",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("session_year", sa.Integer(), nullable=False),
        sa.Column("paper_number", sa.Integer(), nullable=False),
        sa.Column("paper_variant", sa.String(), nullable=False),
        sa.Column("exam_date", sa.Date(), nullable=False),
        sa.Column("starts_at_local", sa.String(), nullable=True),
        sa.Column("duration_minutes", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["subject_code"], ["subjects.code"]),
        sa.PrimaryKeyConstraint("id"),
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
    )
    # The read direction the student calendar actually uses: "the papers I
    # declared, for the session I declared". Subject and session lead because
    # a student's enrolment fixes both before any paper number is considered.
    op.create_index(
        "ix_exam_dates_subject_session_paper",
        "exam_dates",
        ["subject_code", "session_month", "session_year", "paper_number"],
    )


def downgrade() -> None:
    """Reverse 0017: drop the exam-date table and its index.

    The ``sessionmonth`` enum type is **not** dropped — it predates this
    migration (``student_subject_enrolments`` created it) and dropping it here
    would break that table on downgrade. ``create_type=False`` above is the
    matching half of that.
    """
    op.drop_index("ix_exam_dates_subject_session_paper", table_name="exam_dates")
    op.drop_table("exam_dates")
