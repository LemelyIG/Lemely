"""Add `"blank"` to `markersource`, and drop `question_results.plagiarism_flagged`.

One migration, one enum rebuild, one hash move. The user approved the
marking-cache hash budget for this ONCE (task #36 amendment, ruling 1), so both
schema changes ride together rather than costing two rebuilds of the same table.

**Why `"blank"` (ruling 1).** US-039 made a genuine student blank an UNFLAGGED
zero — `confidence_score = 0.0`, `confidence = LOW`, `needs_teacher_review =
False` — without giving it a `marker_source` of its own: it reused `"missing"`,
which already meant "the AI was not called for this question" for two other
reasons, and carried the distinction in free-text `review_reason` instead. So
`0.0` stopped meaning "the marker looked and was unsure" and started ALSO
meaning "nothing looked", with no change to its representation. Every consumer
that read it the old way silently changed behaviour on unchanged input: nine had
to be found by hand, in three waves, and the last one was a grading-AUTHORITY
gate (`attempt_repo.is_marking_low_confidence`, which decides whether a student
may overturn their own mark without evidence and without a judge).

This is exactly the situation `0038_marker_source_dropped` was written for —
a state smuggled through an existing enum value — so this follows that
precedent. After it, the blank exemption is `marker_source == "blank"`: a
column comparison, in one place
(`lemely.core.schemas.UNSCORED_MARKER_SOURCES` / `marker_scored`), instead of a
`" | "`-split substring search over `review_reason`.

**Why `plagiarism_flagged` goes (ruling 2).** The develop merge took the column
along with develop's `is_marking_low_confidence`, which read `qr.plagiarism_flagged`.
The user has ruled to keep the merge and revert the column: the plagiarism
signal is dead end to end and was already dead at the fork point, and building a
new persisted column on a signal nothing produces is the wrong direction.

The gate still needs the integrity fact — it reads a PERSISTED `QuestionResult`
months later, so anything it needs must be persisted — and it now reads the
`review_queue` rows for it (`attempt_repo._integrity_flagged`). Those rows are
written by the same `review_reasons_for` that would have set the column, from
the same `CorrectedQuestion`, so the two cannot disagree; they are never
deleted for an attempt-sourced question (only `status` moves, and
`teacher_paper_repo`'s one `DELETE` is scoped to `teacher_paper_id` rows, which
the `one_source` check constraint guarantees have no `question_result_id`); and
they predate this column, so for rows written before `0037_question_result_pts`
the queue is strictly MORE faithful than the column's `false` server default.

`CorrectedQuestion.plagiarism_flagged` (core, in-memory) is untouched — it is
what `apply_integrity_checks` writes and what `review_reasons_for` reads to open
the `plagiarism_flag` queue row in the first place. Only the persisted copy goes.

**Lock behaviour**, same reasoning as `0038_marker_source_dropped`: the enum
rebuild's `ALTER TABLE ... ALTER COLUMN ... TYPE` rewrites every row of
`question_results` under an `ACCESS EXCLUSIVE` lock. `SET lock_timeout` makes it
fail fast and retriably in a maintenance window rather than queueing behind —
and then blocking — ordinary traffic; both `upgrade()` and `downgrade()`
explicitly `RESET lock_timeout` before returning, since `env.py` runs every
migration one `alembic upgrade`/`downgrade` invocation applies in ONE shared
transaction (`transaction_per_migration` unset) and a plain `SET` would
otherwise leak into whatever migration runs next.

**`downgrade()` is lossy in both directions, deliberately.** A row persisted as
`blank` cannot keep the value once the member stops existing, so it is rewritten
to `missing` — the exact value it carried before this migration, restoring the
pre-migration status quo rather than inventing a different fallback, and the
same one-way posture `0038_marker_source_dropped` documents. The distinction
survives outside the column either way: every blank row still carries
`correction_ai._BLANK_ANSWER_REVIEW_REASON` on `review_reason`. The re-added
`plagiarism_flagged` column comes back `false` for every row; its values are not
restored because the upgrade does not keep them, and the `plagiarism_flag`
`review_queue` rows the upgrade relies on are the surviving record.

Revision ID: 0040_marker_source_blank
Revises: 0039_merge_heads
Create Date: 2026-09-22 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
# Kept to <=32 chars: alembic_version.version_num is varchar(32).
# "0040_marker_source_blank" is 24.
revision: str = "0040_marker_source_blank"
down_revision: str | Sequence[str] | None = "0039_merge_heads"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The enum's member set before and after this migration. Declared once so
# upgrade()/downgrade() cannot drift apart on the member list.
_OLD_MEMBERS = ("deterministic", "ai", "missing", "dropped")
_NEW_MEMBERS = ("deterministic", "ai", "missing", "dropped", "blank")


def upgrade() -> None:
    """Upgrade schema."""
    # Fail fast and retriably rather than queueing behind — and then
    # blocking — ordinary traffic (see the module docstring's "Lock
    # behaviour" section).
    op.execute("SET lock_timeout = '5s'")

    # Rebuild the enum: add `blank`. Postgres has `ALTER TYPE ... ADD VALUE`,
    # but it cannot run inside the same transaction that later uses the new
    # value (which `env.py`'s shared-transaction-per-invocation setup would
    # risk on a multi-migration run), so the type is recreated wholesale — the
    # pattern `0037_remove_ai_detection` established and
    # `0038_marker_source_dropped` reused.
    op.execute("ALTER TYPE markersource RENAME TO markersource_old")
    sa.Enum(*_NEW_MEMBERS, name="markersource").create(op.get_bind())
    op.execute(
        "ALTER TABLE question_results "
        "ALTER COLUMN marker_source TYPE markersource USING marker_source::text::markersource"
    )
    op.execute("DROP TYPE markersource_old")

    # Ruling 2. Runs in the same migration as the rebuild above so
    # `question_results` is rewritten once, not twice.
    op.drop_column("question_results", "plagiarism_flagged")

    # `env.py` runs every migration in ONE shared transaction
    # (`transaction_per_migration` is not set), so a plain `SET` here would
    # otherwise stay in effect for every later migration this same `alembic
    # upgrade` invocation applies after this one. Reset it explicitly rather
    # than relying on transaction end.
    op.execute("RESET lock_timeout")


def downgrade() -> None:
    """Downgrade schema — see the module docstring on what it cannot restore."""
    op.execute("SET lock_timeout = '5s'")

    op.add_column(
        "question_results",
        sa.Column(
            "plagiarism_flagged",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )

    # Must run BEFORE the enum is rebuilt without `blank`: rewriting a row
    # still holding `blank` while the enum still has the value to rewrite FROM
    # is what makes this a documented one-way data change rather than a `CAST`
    # failure.
    op.execute("UPDATE question_results SET marker_source = 'missing' WHERE marker_source = 'blank'")

    op.execute("ALTER TYPE markersource RENAME TO markersource_new")
    sa.Enum(*_OLD_MEMBERS, name="markersource").create(op.get_bind())
    op.execute(
        "ALTER TABLE question_results "
        "ALTER COLUMN marker_source TYPE markersource USING marker_source::text::markersource"
    )
    op.execute("DROP TYPE markersource_new")

    # Same reasoning as upgrade()'s own reset: don't leak a downgrade-scoped
    # lock_timeout into whatever migration this run applies next.
    op.execute("RESET lock_timeout")
