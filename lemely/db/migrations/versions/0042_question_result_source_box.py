"""Persist the extraction bounding box on `question_results`.

Story E, `docs/superpowers/specs/2026-09-24-verdict-path-production-readiness-design.md`.
`CorrectedQuestion.source_box` is produced by extraction (`ExtractedAnswer.source_box`,
US-006), checked for ink (`io/box_plausibility.py`, US-017), and cropped in-process by
`io/reread.py` -- and then discarded: before this migration `grep -rn "source_box"
lemely/db/ lemely/web/` returns zero hits. The same shape of gap `point_verdicts` had
before `0041`.

**Five explicit integer columns, not one jsonb blob.** `SourceBox.validate_box_coords`
enforces that every coordinate is in [0, 1000] and that the box has positive area. A
jsonb blob would let a degenerate box reach the crop route, where the failure surfaces
as a broken image and nobody can see why. The CHECK constraints below carry the same
invariant in the database, so no writer can store a box that cannot be cropped --
including a future writer that does not go through pydantic.

`source_box_page` is the 0-based index of the rasterised page, matching
`lemely.io.rasterise.RasterisedPage.index` and the `page` Gemini echoes back.
Coordinates are `[ymin, xmin, ymax, xmax]` on a 0-1000 scale, so they are independent
of renderer and DPI.

All five are nullable and all-or-nothing: a partially populated box is meaningless, so
`ck_question_results_source_box_all_or_none` rejects it. `NULL` is the common case, not
an error -- the extractor may return no box, and a returned box may have been dropped as
unusable (`ExtractedAnswers.source_box_drops`), and those are deliberately
indistinguishable downstream.

`downgrade()` drops all five, restoring the pre-migration shape exactly. No backfill
either direction, the same posture as every other lossy migration on this table.

Revision ID: 0042_question_result_source_box
Revises: 0041_point_verdict_columns
Create Date: 2026-09-24 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0042_question_result_source_box"
down_revision: str | Sequence[str] | None = "0041_point_verdict_columns"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COORD_COLUMNS = ("source_box_ymin", "source_box_xmin", "source_box_ymax", "source_box_xmax")


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "question_results",
        sa.Column("source_box_page", sa.Integer(), nullable=True),
    )
    for name in _COORD_COLUMNS:
        op.add_column("question_results", sa.Column(name, sa.Integer(), nullable=True))

    # Mirrors `SourceBox.validate_box_coords`: coordinates in range, positive
    # area. Enforced here as well as in pydantic because the crop route reads
    # these columns, not the model, and a degenerate box is only visible as a
    # broken image at that point.
    op.create_check_constraint(
        "ck_question_results_source_box_page_non_negative",
        "question_results",
        "source_box_page IS NULL OR source_box_page >= 0",
    )
    op.create_check_constraint(
        "ck_question_results_source_box_range",
        "question_results",
        " AND ".join(
            f"({name} IS NULL OR ({name} >= 0 AND {name} <= 1000))" for name in _COORD_COLUMNS
        ),
    )
    op.create_check_constraint(
        "ck_question_results_source_box_positive_area",
        "question_results",
        "source_box_ymax IS NULL OR source_box_xmax IS NULL "
        "OR (source_box_ymax > source_box_ymin AND source_box_xmax > source_box_xmin)",
    )
    # A half-written box is meaningless: either the page and all four
    # coordinates are present, or none of them are.
    op.create_check_constraint(
        "ck_question_results_source_box_all_or_none",
        "question_results",
        "(source_box_page IS NULL AND source_box_ymin IS NULL AND source_box_xmin IS NULL "
        "AND source_box_ymax IS NULL AND source_box_xmax IS NULL) "
        "OR (source_box_page IS NOT NULL AND source_box_ymin IS NOT NULL "
        "AND source_box_xmin IS NOT NULL AND source_box_ymax IS NOT NULL "
        "AND source_box_xmax IS NOT NULL)",
    )


def downgrade() -> None:
    """Downgrade schema."""
    for name in (
        "ck_question_results_source_box_all_or_none",
        "ck_question_results_source_box_positive_area",
        "ck_question_results_source_box_range",
        "ck_question_results_source_box_page_non_negative",
    ):
        op.drop_constraint(name, "question_results", type_="check")
    for name in ("source_box_xmax", "source_box_ymax", "source_box_xmin", "source_box_ymin"):
        op.drop_column("question_results", name)
    op.drop_column("question_results", "source_box_page")
