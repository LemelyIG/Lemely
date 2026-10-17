"""Merge the two independent ``0034`` heads back onto a single branch.

``0034_parent_invites`` (parent invites, spec §3) and
``0034_review_queue_paper_src`` (review-queue console-paper source) were
each written as PR branches off the same parent, ``0033_announcement_notified_at``,
in parallel. Neither PR's author could see the other's revision id at the time,
so both correctly declared ``down_revision = "0033_announcement_notified_at"``
and Alembic ended up with two heads once both merged to ``develop`` —
``alembic upgrade head`` then refuses to run because "head" is ambiguous.

This migration does nothing to the schema. It exists purely as the join
point Alembic needs: a single revision whose ``down_revision`` names both
0034 branches, restoring one linear head. Both parents are additive
(new column/index/enum-value work, no shared table touched by both) and
independent of each other, so there is no ordering concern between them and
no schema change of its own to make here.

Revision ID: 0035_merge_heads
Revises: 0034_parent_invites, 0034_review_queue_paper_src
Create Date: 2026-09-08 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

# revision identifiers, used by Alembic.
# Kept to <=32 chars: alembic_version.version_num is varchar(32).
revision: str = "0035_merge_heads"
down_revision: str | Sequence[str] | None = (
    "0034_parent_invites",
    "0034_review_queue_paper_src",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """No schema change: this revision only merges the two 0034 heads."""


def downgrade() -> None:
    """No schema change: this revision only merges the two 0034 heads."""
