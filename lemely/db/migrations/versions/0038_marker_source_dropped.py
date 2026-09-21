"""Add `"dropped"` to the `markersource` Postgres enum (US-038).

`US-031` gave `CorrectedQuestion.marker_source` (`lemely/core/schemas.py`) a
fourth literal value, `"dropped"`, to distinguish an answer the model
**returned and extraction discarded as malformed** from one that was
**never extracted** (`"missing"`). The DB's `MarkerSource`
(`lemely/db/models/enums.py`) is a native Postgres enum created by
`0002_core_schema.py` with only `deterministic` / `ai` / `missing`, so it
could not carry the distinction — `lemely/db/attempt_repo.py` mapped
`"dropped"` onto `MarkerSource.missing` on write as an interim measure,
documented at the time as "out of scope, needs a migration". This is that
migration.

**The user-visible cost this closes:** `ReviewItemDetail.marker_source` is
filled by two siblings feeding the same review-queue response —
`review_repo.py:440` (student-attempt path) read the DB enum and could only
ever yield `"missing"` for a dropped question, while `review_repo.py:1042`
(`_console_item_detail`, teacher-console path) read `report_json` — a JSONB
snapshot of the in-memory `CorrectedQuestion`, never narrowed by the DB
enum — and could yield `"dropped"`. A teacher working ONE review queue could
see two different labels for the identical situation. Adding the enum
member and removing the write-side mapping (`attempt_repo.py`) makes both
readers agree.

**Semantics decision, recorded here since it must be a decision rather than
an accident of which code path supplied the object:** a `"dropped"` answer
genuinely was not marked by a marker — `US-031`'s short-circuit returns
before any paid marking call is made, exactly like `"missing"`. So anywhere
existing code treats `marker_source != "missing"` as "this question was
marked" (e.g. `lemely/web/routers/teacher.py:600`'s "Mark scheme aligned"
count) will, after this migration, also need to exclude `"dropped"` to stay
correct — but that is a **pre-existing** classification question the enum
change makes newly answerable, not a regression this migration causes: pre-
migration the same dropped question arrived as `"ai"` or `"deterministic"`,
both also `!= "missing"`, so the miscount already existed. This migration's
own scope is limited to making the two `ReviewItemDetail` readers agree; it
does not touch `teacher.py`.

**`downgrade()` and a row persisted as `dropped` — it cannot keep the value.**
Postgres has no way to shrink an enum in place, so before the type is
rebuilt without `"dropped"`, any `question_results` row currently holding it
is rewritten to `"missing"` — the same lossy mapping `attempt_repo.py` used
to perform on write, restoring the pre-migration status quo exactly rather
than inventing a different fallback. This is a one-way rewrite on the
`marker_source` column itself (there is no way to tell, from that column
alone after downgrading, which `"missing"` rows were always `"missing"`
and which used to be `"dropped"`), consistent with `0037`'s own downgrade
being similarly lossy for its own enum rebuild.

**Correction (recorded per this branch's `1798d705` precedent, since this
migration's own commit is too far back on this branch to amend):** an
earlier version of this docstring justified adding no audit-log table by
claiming the `"dropped"` distinction is unrecoverable once the rewrite
runs. That claim is false — every dropped row's `report_json` snapshot
(and, for an in-flight correction, `CorrectedQuestion.review_reason`) still
carries `correction_ai.py`'s fixed `_DROPPED_ANSWER_REVIEW_REASON` literal
(`lemely/io/correction_ai.py:723-724`, set at line 776), independent of
`marker_source`, so
the distinction survives outside this column even after the rewrite. The
decision to skip an audit-log table stands regardless: no audit table is
added because the information this rewrite would otherwise discard is
already preserved elsewhere (`report_json`'s `review_reason`), not because
it is trivially lost — unlike `0037`'s two rewrites, which had no such
surviving record of the value they overwrote.

**Lock behaviour**, same reasoning as `0037_remove_ai_detection`: the enum
rebuild's `ALTER TABLE ... ALTER COLUMN ... TYPE` rewrites every row of
`question_results` under an `ACCESS EXCLUSIVE` lock. `SET lock_timeout`
makes it fail fast and retriably in a maintenance window rather than
queueing behind — and then blocking — ordinary traffic; both `upgrade()` and
`downgrade()` explicitly `RESET lock_timeout` before returning, since
`env.py` runs every migration one `alembic upgrade`/`downgrade` invocation
applies in ONE shared transaction (`transaction_per_migration` unset) and a
plain `SET` would otherwise leak into whatever migration runs next.

Revision ID: 0038_marker_source_dropped
Revises: 0037_remove_ai_detection
Create Date: 2026-09-21 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
# Kept to <=32 chars: alembic_version.version_num is varchar(32).
revision: str = "0038_marker_source_dropped"
down_revision: str | Sequence[str] | None = "0037_remove_ai_detection"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The enum's member set before and after this migration. Declared once so
# upgrade()/downgrade() cannot drift apart on the member list.
_OLD_MEMBERS = ("deterministic", "ai", "missing")
_NEW_MEMBERS = ("deterministic", "ai", "missing", "dropped")


def upgrade() -> None:
    """Upgrade schema."""
    # Fail fast and retriably rather than queueing behind — and then
    # blocking — ordinary traffic (see the module docstring's "Lock
    # behaviour" section).
    op.execute("SET lock_timeout = '5s'")

    # Rebuild the enum: add `dropped`. Postgres 10 has `ALTER TYPE ... ADD
    # VALUE`, but it cannot run inside the same transaction that later uses
    # the new value (which `env.py`'s shared-transaction-per-invocation
    # setup would risk on a multi-migration run), so the type is recreated
    # wholesale — the same pattern `0037_remove_ai_detection` established
    # for `reviewreason`.
    op.execute("ALTER TYPE markersource RENAME TO markersource_old")
    sa.Enum(*_NEW_MEMBERS, name="markersource").create(op.get_bind())
    op.execute(
        "ALTER TABLE question_results "
        "ALTER COLUMN marker_source TYPE markersource USING marker_source::text::markersource"
    )
    op.execute("DROP TYPE markersource_old")

    # `env.py` runs every migration in ONE shared transaction
    # (`transaction_per_migration` is not set), so a plain `SET` here would
    # otherwise stay in effect for every later migration this same `alembic
    # upgrade` invocation applies after this one. Reset it explicitly rather
    # than relying on transaction end.
    op.execute("RESET lock_timeout")


def downgrade() -> None:
    """Downgrade schema.

    Restores the enum member set exactly, so an upgrade+downgrade round trip
    on an empty database is a no-op. Does **not** restore the `"dropped"`
    distinction on any row that held it — see the module docstring's
    semantics section: it cannot, since the value itself is about to stop
    existing, so it is rewritten to `"missing"` (the same interim mapping
    `attempt_repo.py` used to perform on write) before the type is rebuilt.
    """
    op.execute("SET lock_timeout = '5s'")

    # Must run BEFORE the enum is rebuilt without `dropped`: rewriting a
    # `question_results` row still holding `dropped` to `missing` while the
    # enum still has the value to rewrite FROM is what makes this a
    # documented one-way data change rather than a `CAST` failure.
    op.execute("UPDATE question_results SET marker_source = 'missing' WHERE marker_source = 'dropped'")

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
