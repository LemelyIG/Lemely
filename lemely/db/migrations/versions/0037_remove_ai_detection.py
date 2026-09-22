"""Remove the AI-generated-answer detector: drop `ai_detection_flag`, add `random_audit` + `review_queue.is_audit`.

F4 deletes ``AIContentDetector`` (``lemely/io/integrity.py``) outright: it was
a zero-shot Gemini classifier with no measured false-positive rate, and
published AI-text detectors run ~61% FPR on authentic L2 student writing —
JCQ guidance is that a detector must never be sole evidence (B5
[integrity 1,5,6,11]). The feature already shipped
``ai_detection_enabled=False`` by default and is now removed entirely, along
with its config knobs, its prompt, and every trace it left behind in data.

This is **one review-queue migration for the whole cycle** (plan F4/N2), so
two parallel work-streams never collide on a second Alembic head:

1. **Remove** ``ReviewReason.ai_detection_flag``. Postgres has no
   ``ALTER TYPE ... DROP VALUE``, so the enum is rebuilt: rename the old
   type out of the way, create the replacement, cast the column across, drop
   the old type. ``SET lock_timeout`` first (see point 5 below). Because this
   is a rebuild rather than an ``ALTER TYPE ... DROP VALUE``, every member the
   type is meant to KEEP has to be named on the way back in — and the
   survivors are therefore read from the live type
   (:func:`_members_now`) rather than hardcoded, so that a member belonging to
   the Alembic *sibling* revision ``0037_question_result_pts``
   (``student_evidence_unjudged``) is not silently dropped on whichever
   ordering the merge head runs that revision first. See the
   ``_REMOVED_MEMBER`` comment below.
2. **One-way data rewrite, ``review_queue.reason``.** Any existing row with
   ``reason = 'ai_detection_flag'`` becomes ``reason = 'manual'`` — the
   closest surviving member; ``manual`` already means "flagged for a reason
   outside the other specific enum cases" (see ``lemely/db/models/enums.py``).
3. **One-way data rewrite, ``question_results.review_reason``.** This is the
   half of the detector's footprint that is easy to miss: the enum value
   above is teacher-only (it drives ``review_queue`` filtering), but
   ``apply_integrity_checks`` (pre-F4 ``lemely/io/integrity.py``) also
   appended a literal ``"ai_detection (score 0.NN)"`` segment onto
   ``CorrectedQuestion.review_reason`` — a free-text column persisted
   verbatim by ``AttemptRepository._persist`` — and that string renders
   **directly on the student's own results page**
   (``web/src/portals/student/screens/PaperResult.tsx``). Leaving it in
   place after removing the detector would mean a student could still be
   shown an accusation from a system the product no longer runs and whose
   threshold nobody can any longer inspect — precisely the JCQ/liability
   exposure F4 exists to close, and worse than the teacher-only case above.
   Segments are ``" | "``-joined; the rewrite splits on that separator,
   drops every segment that is *exactly* the detector's literal (via
   ``string_to_array``/``string_agg``, not a single anchored
   ``regexp_replace``), and rejoins what's left — this handles the segment
   appearing at any position and any number of times, not only the trailing
   position pre-F4 code always produced it at. (An earlier draft of this
   migration used an anchored regex that only matched a leading or trailing
   segment; a middle or repeated segment survived untouched while still
   getting logged as rewritten. Caught in review before merge, before any
   real row was ever processed by it — see the acceptance tests for the
   middle/repeated cases this fix closes.) A ``review_reason`` that becomes
   empty is set to ``NULL`` rather than an empty string.
4. **One audit-log row per rewritten value, in both cases above**, written
   to a new ``ai_detection_removal_audit_log`` table *before* the rewrite so
   it names the value about to be lost. The table is schema-generic
   (``source_table``/``source_id``/``previous_value``/``new_value``) rather
   than one pair of columns per table, precisely because this migration
   already needed two: a third future source needs no schema change, only
   another `INSERT`. **Both rewrites are intentionally lossy**:
   ``downgrade()`` restores the enum member and the ``is_audit`` column, but
   it restores neither the ``ai_detection_flag`` reason nor the stripped
   ``review_reason`` text on any row the upgrade rewrote — there is no way
   to tell a row that was genuinely ``manual``/genuinely missing that segment
   before this migration from one this migration produced, and guessing
   would be worse than an honest, documented one-way step. The audit-log
   table records exactly which rows and what they held, for anyone who needs
   the historical fact; it is dropped on downgrade along with everything
   else this migration added, so an upgrade+downgrade round trip on an
   *empty* database leaves the schema exactly as it started.
5. **Scope boundary, documented rather than silently skipped:**
   ``teacher_papers.report_json`` (a JSONB snapshot of a console-graded
   paper's full ``AccuracyReport``, including each question's
   ``review_reason``) can also hold the same ``"ai_detection (score 0.NN)"``
   text for papers graded before this migration, and this migration does
   **not** rewrite it. Two reasons: a console-graded paper is never
   attributed to a student (``teacher_papers.student_id`` is always NULL,
   D1.12), so this text reaches a teacher's own grading console, not a
   candidate — a materially different exposure from point 3 above, which is
   why point 3 is a MUST-FIX and this is not; and rewriting text nested
   inside a free-form JSONB blob via a schema migration risks corrupting
   sibling data for a lower-stakes surface. Revisit with a dedicated
   migration if this is ever judged to need cleaning up.
6. **Add** ``ReviewReason.random_audit`` — consumed by a later story (N2,
   not implemented here) — in the same enum rebuild, so N2 does not need a
   second head.
7. **Add** ``review_queue.is_audit boolean not null default false`` — also
   consumed by N2, added now for the same one-head reason.

**Lock behaviour.** The enum rebuild's ``ALTER TABLE ... ALTER COLUMN ...
TYPE`` rewrites every row of ``review_queue`` under an ``ACCESS EXCLUSIVE``
lock — correct here (``reviewreason`` backs exactly one column, no view
depends on it, and ``review_queue`` is small), but unbounded by default: on a
busy deployment this migration would queue behind a long-running transaction
while itself blocking every reader and writer that arrives after it.
``SET lock_timeout`` makes it fail fast and retriably in a maintenance window
instead of stalling ``docker-entrypoint.sh``'s pre-API ``alembic upgrade
head`` indefinitely. ``env.py`` runs every migration a single ``alembic
upgrade``/``downgrade`` invocation applies inside ONE shared transaction
(``transaction_per_migration`` is not set), so both ``upgrade()`` and
``downgrade()`` explicitly ``RESET lock_timeout`` before returning — without
that, the timeout would silently keep applying to every later migration the
same invocation runs after this one.

Revision ID: 0037_remove_ai_detection
Revises: 0036_upload_idempotency_key
Create Date: 2026-09-18 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
# Kept to <=32 chars: alembic_version.version_num is varchar(32).
revision: str = "0037_remove_ai_detection"
down_revision: str | Sequence[str] | None = "0036_upload_idempotency_key"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The one member this migration REMOVES and the one it ADDS. Every other member
# is carried across from whatever the type currently holds, read from the
# database rather than listed here — see :func:`_members_now`.
#
# Listing the survivors was the original design and it was wrong once ``develop``
# merged in. This migration REBUILDS ``reviewreason`` wholesale (Postgres has no
# ``ALTER TYPE ... DROP VALUE``), and it is an Alembic SIBLING of
# ``0037_question_result_pts``, which reaches ``student_evidence_unjudged`` with
# ``ALTER TYPE ... ADD VALUE IF NOT EXISTS``. The order the two run in belongs to
# the merge head (``0039_merge_heads``) and is not something either file can see,
# so a hardcoded survivor list silently DROPS the sibling's member on whichever
# ordering runs that revision first. The loss does not surface as a migration
# failure: ``lemely.db.self_review_repo`` writes that member into
# ``review_queue.reason``, so it surfaces as a runtime enum error on a student's
# evidence-backed challenge.
#
# Naming the sibling's member in a hardcoded list instead would fix the ordering
# but break this migration's own documented property 2a — an upgrade+downgrade
# round trip on an empty database leaves the schema exactly as it started — by
# pre-creating, and then leaving behind, a member this chain's ancestors never
# added. Reading the live member set satisfies both: nothing is invented and
# nothing is lost, in either direction and in either order.
_REMOVED_MEMBER = "ai_detection_flag"
_ADDED_MEMBER = "random_audit"


def _members_now(bind: sa.engine.Connection) -> tuple[str, ...]:
    """``reviewreason``'s current members, in the type's own sort order.

    Preserving ``enumsortorder`` keeps the rebuilt type ordered as it was, so an
    ``ORDER BY reason`` does not silently change meaning across this migration.
    """
    rows = bind.execute(
        sa.text(
            "SELECT enumlabel FROM pg_enum "
            "JOIN pg_type ON pg_type.oid = pg_enum.enumtypid "
            "WHERE pg_type.typname = 'reviewreason' "
            "ORDER BY pg_enum.enumsortorder"
        )
    ).scalars()
    return tuple(rows)


def _rebuild_reviewreason(bind: sa.engine.Connection, members: tuple[str, ...]) -> None:
    """Replace the ``reviewreason`` type with exactly ``members``.

    Rename the old type out of the way, create the replacement, cast
    ``review_queue.reason`` across, drop the old type. Shared by ``upgrade`` and
    ``downgrade`` so the two cannot drift on the mechanics.
    """
    op.execute("ALTER TYPE reviewreason RENAME TO reviewreason_old")
    sa.Enum(*members, name="reviewreason").create(bind)
    op.execute(
        "ALTER TABLE review_queue "
        "ALTER COLUMN reason TYPE reviewreason USING reason::text::reviewreason"
    )
    op.execute("DROP TYPE reviewreason_old")

# The exact literal appended by pre-F4 `apply_integrity_checks`
# (`lemely/io/integrity.py`, `f"ai_detection (score {finding.score:.2f})"`) —
# always two decimal places, always this prefix. Used both to select
# affected `question_results` rows (unanchored: matches the segment
# anywhere in the string) and, anchored to a whole segment, to filter it
# out segment-by-segment in `_strip_ai_detection_segment_sql` below.
_AI_DETECTION_SEGMENT = r"ai_detection \(score [0-9]+\.[0-9]{2}\)"


def _strip_ai_detection_segment_sql(column: str) -> str:
    """A SQL expression: ``column`` with every AI-detection segment removed.

    Segment-wise — split on ``" | "``, drop any segment that exactly matches
    the detector's literal, rejoin what's left — rather than a single
    anchored ``regexp_replace``. The anchored-alternation version this
    migration shipped with first
    (``(^SEG$)|(^SEG \\| )|( \\| SEG$)``) only matched a segment at the very
    start or very end of the string: a segment in the MIDDLE of three, or a
    SECOND occurrence after the first was already consumed, survived
    untouched — and still got logged in the audit table as rewritten, since
    the audit `INSERT` and this expression must be computed the same way.
    ``string_agg`` over zero remaining segments returns ``NULL`` directly
    (the sole-segment case), and the outer ``NULLIF`` is defense-in-depth
    for the same result via any other path.
    """
    return (
        "NULLIF("
        "(SELECT string_agg(seg, ' | ' ORDER BY ord) "
        f"FROM unnest(string_to_array({column}, ' | ')) WITH ORDINALITY AS t(seg, ord) "
        f"WHERE seg !~ '^{_AI_DETECTION_SEGMENT}$'), "
        "'')"
    )


def upgrade() -> None:
    """Upgrade schema."""
    # Fail fast and retriably rather than queueing behind — and then
    # blocking — ordinary traffic (see the module docstring's "Lock
    # behaviour" section).
    op.execute("SET lock_timeout = '5s'")

    op.create_table(
        "ai_detection_removal_audit_log",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("source_table", sa.Text(), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column("previous_value", sa.Text(), nullable=False),
        sa.Column("new_value", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_detection_removal_audit_log")),
    )
    # No index on (source_table, source_id): this table is written once by
    # this migration and otherwise read in full or not at all (a historical
    # record, not a hot lookup path) — an index would cost write time on the
    # rewrite for a query pattern nothing in this codebase performs.

    # One audit row per row about to be rewritten, written BEFORE the
    # rewrite so it names the value that is about to be lost (2b).
    op.execute(
        """
        INSERT INTO ai_detection_removal_audit_log
            (source_table, source_id, previous_value, new_value)
        SELECT 'review_queue', id, 'ai_detection_flag', 'manual'
        FROM review_queue
        WHERE reason = 'ai_detection_flag'
        """
    )
    op.execute("UPDATE review_queue SET reason = 'manual' WHERE reason = 'ai_detection_flag'")

    # The student-visible half (point 3 above): strip the detector's segment
    # out of question_results.review_reason, logging the pre-strip text. The
    # audit INSERT's `new_value` and the UPDATE's `SET` both compute the
    # SAME expression (`_strip_ai_detection_segment_sql`) over the SAME
    # `WHERE` predicate, so the audit log cannot claim a rewrite this
    # statement did not also perform.
    _stripped = _strip_ai_detection_segment_sql("review_reason")
    op.execute(
        f"""
        INSERT INTO ai_detection_removal_audit_log
            (source_table, source_id, previous_value, new_value)
        SELECT
            'question_results',
            id,
            review_reason,
            {_stripped}
        FROM question_results
        WHERE review_reason ~ '{_AI_DETECTION_SEGMENT}'
        """
    )
    op.execute(
        f"""
        UPDATE question_results
        SET review_reason = {_stripped}
        WHERE review_reason ~ '{_AI_DETECTION_SEGMENT}'
        """
    )

    # Rebuild the enum: drop ai_detection_flag, add random_audit, KEEP everything
    # else the type currently holds (see the _REMOVED_MEMBER comment above for
    # why the survivors are read rather than listed).
    bind = op.get_bind()
    members = _members_now(bind)
    new_members = tuple(m for m in members if m != _REMOVED_MEMBER)
    if _ADDED_MEMBER not in new_members:
        new_members += (_ADDED_MEMBER,)
    _rebuild_reviewreason(bind, new_members)

    op.add_column(
        "review_queue",
        sa.Column("is_audit", sa.Boolean(), server_default=sa.false(), nullable=False),
    )

    # `env.py` runs every migration in ONE shared transaction
    # (`transaction_per_migration` is not set), so a plain `SET` here would
    # otherwise stay in effect for every later migration this same `alembic
    # upgrade` invocation applies after this one — an unrelated migration's
    # DDL could then fail on a timeout it never asked for, with no trace
    # pointing back to 0037. Reset it explicitly rather than relying on
    # transaction end.
    op.execute("RESET lock_timeout")


def downgrade() -> None:
    """Downgrade schema.

    Restores the enum member set and column shape exactly, so an
    upgrade+downgrade round trip on an empty database is a no-op (2a). Does
    **not** restore ``ai_detection_flag`` on any ``review_queue`` row, nor the
    stripped ``ai_detection (score 0.NN)`` segment on any
    ``question_results.review_reason`` — see the module docstring's points 2
    and 3: both rewrites are one-way by design and unrecoverable from
    anything this migration keeps around.
    """
    op.execute("SET lock_timeout = '5s'")

    op.drop_column("review_queue", "is_audit")

    # The mirror image of upgrade(): drop random_audit, put ai_detection_flag
    # back where it was, keep every other member the type currently holds. A
    # member the sibling revision 0037_question_result_pts added is therefore
    # preserved rather than dropped -- that revision's own downgrade
    # deliberately never removes it either (Postgres cannot drop an enum value),
    # and dropping it here would fail the `reason::text::reviewreason` cast
    # outright on any row still carrying it.
    bind = op.get_bind()
    members = _members_now(bind)
    old_members = tuple(m for m in members if m != _ADDED_MEMBER)
    if _REMOVED_MEMBER not in old_members:
        # Restore it in its original position (immediately after
        # plagiarism_flag, per 0002_core_schema) rather than appending, so the
        # type's sort order round-trips too.
        anchor = old_members.index("plagiarism_flag") + 1
        old_members = old_members[:anchor] + (_REMOVED_MEMBER,) + old_members[anchor:]
    _rebuild_reviewreason(bind, old_members)

    op.drop_table("ai_detection_removal_audit_log")

    # Same reasoning as upgrade()'s own reset: don't leak a downgrade-scoped
    # lock_timeout into whatever migration this run applies next.
    op.execute("RESET lock_timeout")
