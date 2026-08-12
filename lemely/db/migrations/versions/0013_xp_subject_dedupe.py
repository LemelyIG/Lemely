"""xp_events: subject attribution + award idempotency (P5.2 chunk A, D5.1 §7/§8).

Revision ID: 0013_xp_subject_dedupe
Revises: 0012_study_plans
Create Date: 2026-08-09 00:00:00.000000

Two additive columns on ``xp_events``, no existing column touched
(D1.2/D1.3) — the only XP-related schema work D5.1 authorizes for P5:

* ``subject_code`` — nullable ``String`` FK to ``subjects.code``. Nullable
  because not every award has a subject (a flashcard review does; a future
  account-level award might not); per-subject leaderboard queries (S-29)
  filter on it, total boards ignore it. D5.1 §7 rejected storing this in the
  ``metadata`` JSONB — it is a real foreign key with real referential
  integrity and must be indexable, so it gets ``ix_xp_events_subject_code``
  (a plain btree is the right shape for "sum XP where subject_code = X",
  matching the existing ``ix_xp_events_user_id_awarded_on`` philosophy of
  one index per real query shape).

  **D5.1 §7 said ``subject_id``, a UUID FK to ``subjects.id``. That was
  wrong and this migration deliberately does not implement it** — see D5.2,
  which records the correction. Every other subject-scoped table in this
  schema keys on the code (``papers``, ``quizzes``, ``quiz_questions``,
  ``flashcard_decks``, ``study_plans``, ``student_subject_enrolments``,
  ``attempts``, ``announcements`` — eight of them, no exceptions), and every
  award seam P5.2 chunk B wires already carries a ``subject_code``. A UUID
  column here would have forced a code-to-UUID lookup at every single award
  call site to store something no caller possesses, for no gain.

* ``dedupe_key`` — nullable ``String``, plus a **partial unique index** over
  ``(user_id, source, dedupe_key)`` restricted to ``WHERE dedupe_key IS NOT
  NULL``. D5.1 §8 requires idempotency to be a database constraint: every
  award the P5.2 engine issues carries a ``dedupe_key`` derived from the
  identity of the thing that caused it (paper id, assignment id, plan-session
  id, flashcard-review id), and re-awarding for the same identity must be a
  rejected insert, not a silent double count.

  The column is nullable, not ``NOT NULL``, for one reason only: this
  migration is additive over a table that has existed since migration 0002,
  and an unconditional ``NOT NULL`` would either require backfilling a
  meaningless value into every pre-existing row or reject this migration
  outright on any environment where ``xp_events`` is non-empty. No award
  call site exists yet anywhere in ``lemely`` as of this migration (P5.2
  chunk B wires them), so today every environment's ``xp_events`` table is
  empty in practice — but the schema itself must not assume that stays true.
  A **partial** unique index (``postgresql_where=dedupe_key IS NOT NULL``,
  mirroring migration 0012's ``uq_study_plans_active`` pattern) gets the
  actual guarantee D5.1 §8 asks for — no two rows with the same
  ``(user_id, source, dedupe_key)`` — without forcing every historical or
  future non-deduped row to fabricate a key. ``lemely.db.xp_repo`` always
  supplies a real ``dedupe_key`` on every award it issues, so the constraint
  is total in practice for every row the engine ever writes; the nullability
  only accommodates rows outside the engine's control.

Reversible: both columns and both new indexes are dropped in ``downgrade``,
leaving ``xp_events`` exactly as migration 0002 defined it.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0013_xp_subject_dedupe"
down_revision: str | Sequence[str] | None = "0012_study_plans"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("xp_events", sa.Column("subject_code", sa.String(), nullable=True))
    op.add_column("xp_events", sa.Column("dedupe_key", sa.String(), nullable=True))

    op.create_foreign_key(
        op.f("fk_xp_events_subject_code_subjects"),
        "xp_events",
        "subjects",
        ["subject_code"],
        ["code"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_xp_events_subject_code",
        "xp_events",
        ["subject_code"],
    )
    op.create_index(
        "uq_xp_events_user_source_dedupe",
        "xp_events",
        ["user_id", "source", "dedupe_key"],
        unique=True,
        postgresql_where=sa.text("dedupe_key IS NOT NULL"),
    )


def downgrade() -> None:
    """Reverse 0013: drop both new indexes, the FK, then both new columns."""
    op.drop_index("uq_xp_events_user_source_dedupe", table_name="xp_events")
    op.drop_index("ix_xp_events_subject_code", table_name="xp_events")
    op.drop_constraint(op.f("fk_xp_events_subject_code_subjects"), "xp_events", type_="foreignkey")
    op.drop_column("xp_events", "dedupe_key")
    op.drop_column("xp_events", "subject_code")
