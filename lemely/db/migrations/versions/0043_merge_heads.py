"""Merge the post-develop-merge heads: ``0042`` (this branch) and ``0039_paper_soft_delete``.

``feat/ai-improvements`` joined the two ``0038`` heads with ``0039_merge_heads``
and went on to ``0040_marker_source_blank``, ``0041_point_verdict_columns`` and
``0042_question_result_source_box``. Meanwhile ``develop`` (``5c0914ba``) added
``0039_paper_soft_delete`` on ``0038_point_group_key`` -- the same parent
``0039_merge_heads`` had already consumed. Neither side was wrong alone; the
merge of the two branches is what leaves Alembic with two heads, and
``alembic upgrade head`` refuses to run while "head" is ambiguous
(``docker-entrypoint.sh``, ``.github/workflows/ci.yml``).

This revision does nothing to the schema. It is the join point only, exactly
like ``0035_merge_parent_invites_review``. The order Alembic picks between the
two parents does not matter: ``0039_paper_soft_delete`` only ``ADD VALUE``s to
``reviewstatus`` and ``notificationtype``, adds columns and creates a table;
no revision on this branch's chain touches either enum
(``0037_remove_ai_detection`` rebuilds ``reviewreason``, ``0040`` rebuilds
``markersource``) or any of those columns.

Revision ID: 0043_merge_heads
Revises: 0042_question_result_source_box, 0039_paper_soft_delete
Create Date: 2026-09-29 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

# revision identifiers, used by Alembic.
# Kept to <=32 chars: alembic_version.version_num is varchar(32).
# "0043_merge_heads" is 16.
revision: str = "0043_merge_heads"
down_revision: str | Sequence[str] | None = (
    "0042_question_result_source_box",
    "0039_paper_soft_delete",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """No schema change: this revision only merges the two post-merge heads."""


def downgrade() -> None:
    """No schema change: this revision only merges the two post-merge heads."""
