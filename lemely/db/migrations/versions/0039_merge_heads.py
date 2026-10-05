"""Merge the two ``0038`` heads, and drop the column F4 deleted the writer for.

``feat/ai-improvements`` and ``develop`` each grew a two-revision chain off
``0036_upload_idempotency_key`` in parallel:

* ``0037_remove_ai_detection`` → ``0038_marker_source_dropped`` (this branch)
* ``0037_question_result_pts`` → ``0038_point_group_key`` (develop)

Neither chain's author could see the other's revision ids, so both correctly
declared ``down_revision = "0036_upload_idempotency_key"`` and Alembic has two
heads once the branches meet — ``alembic upgrade head`` then refuses to run at
all, because "head" is ambiguous. In-repo precedent for the join:
``0035_merge_parent_invites_review``.

**Unlike ``0035``, this one is not a pure no-op.** It drops
``question_results.ai_detection_flagged``.

``0037_question_result_pts`` adds that column (it was written before F4 landed,
when ``CorrectedQuestion.ai_detection_flagged`` still existed). F4 —
``0037_remove_ai_detection``, on the other chain — deleted the detector, its
config knobs, its ``ReviewReason`` member and the ``"ai_detection (score
0.NN)"`` text it left on ``question_results.review_reason``, for reasons that
are about liability rather than tidiness: a zero-shot classifier with no
measured false-positive rate, which JCQ guidance says may never be sole
evidence. Nothing writes the column after the merge — ``_to_question_result``
no longer passes it and ``QuestionResult`` no longer maps it — so leaving it
would leave a ``NOT NULL DEFAULT false`` column that is pure schema drift, and
would leave the *name* of a removed accusation in the table a student's marks
live in.

Dropping it here rather than editing ``0037_question_result_pts`` is
deliberate: that revision is already released on ``develop``, and rewriting an
applied migration means every database that ran it disagrees with the file.

**Ordering between the two 0037s is Alembic's to choose, and both orders now
give the same result.** That took one fix, in ``0037_remove_ai_detection``
rather than here: it REBUILDS the ``reviewreason`` enum (Postgres has no
``ALTER TYPE ... DROP VALUE``), so its member lists had to be taught about
``student_evidence_unjudged`` — develop's member, added by
``0037_question_result_pts`` — or the rebuild would silently drop it whenever
develop's revision ran first. See that file's ``_NEW_MEMBERS`` comment.

Reversible: ``downgrade`` re-adds the column with the same type, nullability
and server default ``0037_question_result_pts`` created it with. Its DATA is
not restored, because the upgrade does not keep it: every value was ``false``
except on rows the deleted detector had flagged, and F4's whole point is that
those flags are not evidence anybody should act on. This is the same one-way
posture ``0037_remove_ai_detection`` documents for the two rewrites it
performs.

Revision ID: 0039_merge_heads
Revises: 0038_point_group_key, 0038_marker_source_dropped
Create Date: 2026-09-22 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
# Kept to <=32 chars: alembic_version.version_num is varchar(32).
# "0039_merge_heads" is 16.
revision: str = "0039_merge_heads"
down_revision: str | Sequence[str] | None = (
    "0038_point_group_key",
    "0038_marker_source_dropped",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Join the two heads and drop the AI-detection column (see module docstring)."""
    op.drop_column("question_results", "ai_detection_flagged")


def downgrade() -> None:
    """Re-add the column exactly as ``0037_question_result_pts`` created it.

    Values are not restored — see the module docstring.
    """
    op.add_column(
        "question_results",
        sa.Column(
            "ai_detection_flagged",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
