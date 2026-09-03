"""Enforce max_mark > 0 on component_thresholds.

Revision ID: 0026_component_max_mark_positive
Revises: 0025_thresholds
Create Date: 2026-09-03 00:00:00.000000

Adds a ``CHECK (max_mark > 0)`` constraint to ``component_thresholds``.

Every percentage in :func:`lemely.io.grade_boundaries._percentages` divides a
raw mark by ``max_mark`` — a zero raises ``ZeroDivisionError`` and a negative
value produces a nonsensical, grade-inflating percentage
(``_percentages({"A": 24}, -1) == {"A": -2400.0}``). ``_percentages`` now
guards this in Python too, but a database constraint is the backstop: it makes
a non-positive ``max_mark`` impossible to store at all, regardless of which
code path writes the row.

``0025_thresholds`` is already applied to real databases (1,354 ingested
rows as of this migration), so the constraint is added here rather than
editing ``0025`` in place.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0026_component_max_mark_positive"
down_revision: str | Sequence[str] | None = "0025_thresholds"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONSTRAINT_NAME = "ck_component_thresholds_max_mark_positive"


def upgrade() -> None:
    """Upgrade schema."""
    op.create_check_constraint(
        _CONSTRAINT_NAME,
        "component_thresholds",
        "max_mark > 0",
    )


def downgrade() -> None:
    """Reverse 0026: drop the constraint."""
    op.drop_constraint(_CONSTRAINT_NAME, "component_thresholds", type_="check")
