# Paper Deletion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a student delete an uploaded paper — the scan and its whole marked result — with a 30-day restore window, then purge it permanently.

**Architecture:** Soft delete via a session-level SQLAlchemy loader criterion on `Attempt` and `Upload`, so a new reader cannot forget to exclude deleted rows; one `include_deleted` escape hatch used by exactly three callers. Delete/restore/list routes live in a new thin router keyed on `attempt_id`. A purge job on the existing notification sweeper deletes the GCS object first and treats the row as the record of intent, made race-free against restore by disjoint time windows rather than locks.

**Tech Stack:** Python 3.12–3.14, SQLAlchemy 2.0 (sync), Alembic, FastAPI, Postgres, pytest; React 19 + TypeScript + Tailwind + react-query on the frontend, vitest (node environment, no jsdom) and Playwright.

**Design:** `docs/superpowers/specs/2026-09-22-paper-deletion-design.md`
**Decisions:** `docs/superpowers/specs/2026-09-21-paper-deletion-decisions.md`

## Global Constraints

- Signed commits only: `git commit -S`. Conventional messages with scopes (`feat(db):`, `fix(web):`, `test(e2e):`).
- Run `pre-commit run --all-files` and fix every failure before any commit.
- Do not push and do not open a PR unless asked.
- Never run the full test suite locally; CI does. Run only the test files you touched, and always pass `--no-cov` (the 70% gate fails on a partial run).
- **Activate the venv first: `source .venv/bin/activate`.** It lives in the main checkout, not in this worktree, and `alembic` is not otherwise on `PATH`. Migrations can also be applied with `make db-migrate`, which wraps `alembic upgrade head`. Note that `pytest -q` prints no summary line in this environment — check the exit code rather than reporting a pass you did not see.
- `GEMINI_API_KEY` is never committed and never placed in `lemely.toml`.
- Never run `make db-reset` — it wipes local dev data.
- Never use bare `git stash` / `git stash pop`; the stash stack is shared across worktrees.
- **Integrity flags (`plagiarism_flagged`, `ai_detection_flagged`, and integrity segments of `review_reason`) must never reach a student-facing surface** — `BUILD/QUALITY-BAR.md`. This constrains Task 6's refusal copy absolutely.
- Alembic revision ids are capped at 32 characters (`alembic_version.version_num` is `varchar(32)`).
- Ruff enforces `D205` — a docstring summary is one line, followed by a blank line.
- **The owner's rulings R1–R6 are settled** and recorded in the decisions document. Four of them reversed the design's recommendation; the plan below implements the rulings, not the recommendations. Do not re-open them.
- **One pull request (R6).** Every task below lands on one branch. The loader criterion (Task 3) is the highest-consequence change in that diff — flag it explicitly in the PR body so a reviewer knows where to spend their attention.

---

### Task 0: Confirm the rulings are recorded (no code)

**Files:** `docs/superpowers/specs/2026-09-21-paper-deletion-decisions.md` (already written).

No longer a gate — the owner answered on 2026-09-22. This task exists so the
implementer reads the rulings before writing code that contradicts them.

- [ ] **Step 1: Read the "Owner rulings, 2026-09-22" section**

The four that reversed the design, and therefore the four most likely to be
implemented from stale memory of the design's prose:

- **R2** — teacher-console deletion is **in scope** (Tasks 16–17).
- **R3** — unshare **does** clear the paper from that class's review queue,
  by filtering, never by mutating the item's status (Task 13).
- **R4/R4a** — D8's block **lifts** when a teacher closes the integrity item as
  `resolved` **or** `dismissed`, and **never** on `withdrawn` (Tasks 5, 8).
- **R5** — the data-handling page is reviewed after merge, so Task 15 carries
  no blocking checkbox.

---

### Task 1: The retention constant and the pure predicates

**Files:**
- Create: `lemely/core/deletion.py`
- Test: `tests/test_core_deletion.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `RETENTION_DAYS: int`, `PURGE_GRACE: timedelta`, `restore_deadline(deleted_at: datetime) -> datetime`, `purge_cutoff(now: datetime) -> datetime`, `integrity_hold_until(recorded_at: datetime) -> datetime`, `is_within_restore_window(deleted_at: datetime, now: datetime) -> bool`. Tasks 5, 6, 7, 8 and 10 all import from here.

Pure module, no I/O, no SQLAlchemy — so the arithmetic that decides whether a
paper is restorable or purgeable is testable without a database and has
exactly one definition.

- [ ] **Step 1: Write the failing test**

```python
"""The deletion window arithmetic (design 2026-09-22, §7)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from lemely.core.deletion import (
    PURGE_GRACE,
    RETENTION_DAYS,
    integrity_hold_until,
    is_within_restore_window,
    purge_cutoff,
    restore_deadline,
)

NOW = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)


def test_retention_is_thirty_days_and_shared() -> None:
    assert RETENTION_DAYS == 30


def test_restore_deadline_is_retention_after_deletion() -> None:
    assert restore_deadline(NOW) == NOW + timedelta(days=30)


def test_integrity_hold_uses_the_same_number() -> None:
    assert integrity_hold_until(NOW) - NOW == restore_deadline(NOW) - NOW


def test_purge_cutoff_is_retention_plus_grace_ago() -> None:
    assert purge_cutoff(NOW) == NOW - timedelta(days=30) - PURGE_GRACE


def test_restore_and_purge_windows_cannot_both_claim_one_row() -> None:
    """The gap is the whole safety argument — no row is restorable and purgeable."""
    just_restorable = NOW - timedelta(days=30) + timedelta(seconds=1)
    assert is_within_restore_window(just_restorable, NOW) is True
    assert just_restorable > purge_cutoff(NOW)

    purgeable = purge_cutoff(NOW) - timedelta(seconds=1)
    assert is_within_restore_window(purgeable, NOW) is False


def test_restore_window_rejects_a_naive_datetime() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        is_within_restore_window(datetime(2026, 9, 1), NOW)  # noqa: DTZ001
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_core_deletion.py --no-cov -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'lemely.core.deletion'`

- [ ] **Step 3: Write the implementation**

```python
"""Retention arithmetic for paper deletion (design 2026-09-22 §7, decisions D3/D8).

One module so the 30 days is **one number**: D8's integrity hold and the purge
window are the same retention, and a second literal is how they drift apart.

Deliberately not a settings knob. A configurable retention would make the
public "How Lemely handles your data" page conditional on deployment config,
and that page states the window as fact.
"""

from __future__ import annotations

from datetime import datetime, timedelta

#: The restore window, and D8's integrity hold. One number, both uses.
RETENTION_DAYS = 30

#: Gap between the last restorable instant and the first purgeable one.
#: Absorbs clock skew between replicas so restore and purge can never both
#: succeed on one row — the whole reason purge may delete the GCS object first.
PURGE_GRACE = timedelta(hours=1)

_RETENTION = timedelta(days=RETENTION_DAYS)


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError(f"{name} must be timezone-aware")


def restore_deadline(deleted_at: datetime) -> datetime:
    """The instant after which this deletion can no longer be undone."""
    _require_aware(deleted_at, "deleted_at")
    return deleted_at + _RETENTION


def integrity_hold_until(recorded_at: datetime) -> datetime:
    """The instant an integrity-flagged paper becomes deletable (D8).

    Keyed on ``recorded_at`` because the flags are written at marking time and
    there is no ``flagged_at`` column — inventing one would be a second clock.
    """
    _require_aware(recorded_at, "recorded_at")
    return recorded_at + _RETENTION


def purge_cutoff(now: datetime) -> datetime:
    """Rows whose ``deleted_at`` is at or before this are purgeable."""
    _require_aware(now, "now")
    return now - _RETENTION - PURGE_GRACE


def is_within_restore_window(deleted_at: datetime, now: datetime) -> bool:
    """Whether a row stamped at ``deleted_at`` may still be restored."""
    _require_aware(deleted_at, "deleted_at")
    _require_aware(now, "now")
    return deleted_at > now - _RETENTION


__all__ = [
    "PURGE_GRACE",
    "RETENTION_DAYS",
    "integrity_hold_until",
    "is_within_restore_window",
    "purge_cutoff",
    "restore_deadline",
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_core_deletion.py --no-cov -q`
Expected: PASS, 6 passed

- [ ] **Step 5: Commit**

```bash
pre-commit run --all-files
git add lemely/core/deletion.py tests/test_core_deletion.py
git commit -S -m "feat(core): one retention constant and the deletion window arithmetic"
```

---

### Task 2: Migration 0039 and the model columns

> **Review amendments (2026-09-24) — these OVERRIDE any conflicting text below in this task.** Source: pre-execution plan review (`.superpowers/sdd-deletion/plan-review.md`) and owner rulings R7–R10.
>
> - **Notification preferences (B2, R10).** `NotificationType.review_withdrawn` breaks two exhaustiveness pins unless it gets a preference. In 0039 add `notification_preferences.review_withdrawn BOOLEAN NOT NULL DEFAULT true`; add the model column; extend `NotificationPreferencesRow`, `DEFAULTS` and `set()` in `lemely/db/notification_prefs_repo.py` (~:66,109,148,175,188); add the entry to `PREFERENCE_FIELD_FOR_TYPE` in `lemely/db/notification_repo.py` (~:87-93); extend the preferences wire DTO; add `review_withdrawn` to the frontend `NotificationType` union in `web/src/lib/notificationTypes.ts` (~:21-26). The settings **toggle UI** is Task 17, not here. `tests/test_notification_repo.py:131` and `tests/test_db_schema.py:181-203` must stay green — run them.
> - **`teacher_papers.deleted_at` goes in 0039 now (I4).** Add the nullable column and `TeacherPaper.deleted_at` model field in this task, so Task 16 never edits an already-applied migration. Cover it in `tests/test_migration_0039.py` and in `downgrade()`.
> - **`EXPECTED_TABLES` (I11).** Add `class_paper_exclusions` to `EXPECTED_TABLES` in `tests/test_db_schema.py` (~:116) and commit that file.
> - After Step 7, run `alembic downgrade -1 && alembic upgrade head` once and confirm clean.


**Files:**
- Create: `lemely/db/migrations/versions/0039_paper_soft_delete.py`
- Modify: `lemely/db/models/attempts.py` (add `deleted_at` to `Upload` and `Attempt`)
- Modify: `lemely/db/models/ops.py` (add `withdrawn_at` to `ReviewQueueItem`)
- Modify: `lemely/db/models/enums.py` (`ReviewStatus.withdrawn`, `NotificationType.review_withdrawn`)
- Create: `lemely/db/models/deletion.py` (`ClassPaperExclusion`)
- Test: `tests/test_migration_0039.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Attempt.deleted_at: Mapped[datetime | None]`, `Upload.deleted_at: Mapped[datetime | None]`, `ReviewQueueItem.withdrawn_at: Mapped[datetime | None]`, `ReviewStatus.withdrawn`, `NotificationType.review_withdrawn`, and `ClassPaperExclusion` with columns `class_id`, `attempt_id`, `excluded_by`, `created_at`. Every later task depends on these names.

The head is `0038_point_group_key` and nothing is branched — confirm with
`alembic heads` before writing, and if two heads appear, stop and
report rather than guessing a parent.

- [ ] **Step 1: Write the failing test**

```python
"""Migration 0039 puts the soft-delete columns and enum values in place."""

from __future__ import annotations

import sqlalchemy as sa


def test_attempts_and_uploads_have_deleted_at(migrated_sessionmaker) -> None:
    with migrated_sessionmaker() as session:
        rows = session.execute(
            sa.text(
                "SELECT table_name, is_nullable, data_type FROM information_schema.columns "
                "WHERE column_name = 'deleted_at' AND table_name IN ('attempts', 'uploads')"
            )
        ).all()
    assert {r.table_name for r in rows} == {"attempts", "uploads"}
    assert all(r.is_nullable == "YES" for r in rows)
    assert all(r.data_type == "timestamp with time zone" for r in rows)


def test_partial_index_exists_on_attempts(migrated_sessionmaker) -> None:
    with migrated_sessionmaker() as session:
        ddl = session.execute(
            sa.text("SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_attempts_deleted_at'")
        ).scalar_one()
    assert "deleted_at IS NOT NULL" in ddl


def test_review_status_gained_withdrawn(migrated_sessionmaker) -> None:
    with migrated_sessionmaker() as session:
        values = set(
            session.scalars(
                sa.text(
                    "SELECT e.enumlabel FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid "
                    "WHERE t.typname = 'reviewstatus'"
                )
            ).all()
        )
    assert values == {"open", "resolved", "dismissed", "withdrawn"}


def test_notification_type_gained_review_withdrawn(migrated_sessionmaker) -> None:
    with migrated_sessionmaker() as session:
        values = set(
            session.scalars(
                sa.text(
                    "SELECT e.enumlabel FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid "
                    "WHERE t.typname = 'notificationtype'"
                )
            ).all()
        )
    assert "review_withdrawn" in values


def test_class_paper_exclusions_is_keyed_on_the_pair(migrated_sessionmaker) -> None:
    with migrated_sessionmaker() as session:
        cols = set(
            session.scalars(
                sa.text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'class_paper_exclusions'"
                )
            ).all()
        )
    assert cols == {"class_id", "attempt_id", "excluded_by", "created_at", "updated_at"}


def test_review_queue_gained_withdrawn_at(migrated_sessionmaker) -> None:
    with migrated_sessionmaker() as session:
        nullable = session.execute(
            sa.text(
                "SELECT is_nullable FROM information_schema.columns "
                "WHERE table_name = 'review_queue' AND column_name = 'withdrawn_at'"
            )
        ).scalar_one()
    assert nullable == "YES"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_migration_0039.py --no-cov -q`
Expected: FAIL — the `deleted_at` query returns an empty set.

- [ ] **Step 3: Write the migration**

```python
"""paper soft delete: deleted_at, withdrawn review items, class exclusions

Revision ID: 0039_paper_soft_delete
Revises: 0038_point_group_key
Create Date: 2026-09-22 00:00:00.000000

The product's first soft delete (design 2026-09-22 §3). Entirely additive: two
nullable timestamps, one nullable timestamp on the review queue, two enum
values and one table. No backfill — a NULL ``deleted_at`` is exactly "not
deleted", which is true of every existing row.

The partial index carries ``WHERE deleted_at IS NOT NULL`` because its only
readers are the purge candidate query and the recently-deleted list, both of
which look at the small deleted minority. A full index would be mostly NULLs.

Reversible, with one Postgres limitation: ``downgrade`` drops the columns, the
index and the table, but **cannot remove the added enum values** — Postgres has
no ``DROP VALUE``, and recreating ``reviewstatus`` would mean rewriting every
dependent column for no benefit. This matches how 0037 handled ``reviewreason``.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
# Kept to <=32 chars: alembic_version.version_num is varchar(32).
revision: str = "0039_paper_soft_delete"
down_revision: str | Sequence[str] | None = "0038_point_group_key"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("ALTER TYPE reviewstatus ADD VALUE IF NOT EXISTS 'withdrawn'")
    op.execute("ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'review_withdrawn'")

    op.add_column("attempts", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("uploads", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "review_queue", sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True)
    )

    op.create_index(
        "ix_attempts_deleted_at",
        "attempts",
        ["deleted_at"],
        postgresql_where=sa.text("deleted_at IS NOT NULL"),
    )

    op.create_table(
        "class_paper_exclusions",
        sa.Column("class_id", sa.UUID(), nullable=False),
        sa.Column("attempt_id", sa.UUID(), nullable=False),
        sa.Column("excluded_by", sa.UUID(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["class_id"],
            ["classes.id"],
            name="fk_class_paper_exclusions_class_id_classes",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id"],
            ["attempts.id"],
            name="fk_class_paper_exclusions_attempt_id_attempts",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["excluded_by"],
            ["users.id"],
            name="fk_class_paper_exclusions_excluded_by_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("class_id", "attempt_id", name="pk_class_paper_exclusions"),
    )


def downgrade() -> None:
    """Downgrade schema. The two enum values stay; Postgres cannot drop them."""
    op.drop_table("class_paper_exclusions")
    op.drop_index("ix_attempts_deleted_at", table_name="attempts")
    op.drop_column("review_queue", "withdrawn_at")
    op.drop_column("uploads", "deleted_at")
    op.drop_column("attempts", "deleted_at")
```

**Caution:** `ALTER TYPE … ADD VALUE` could not run inside a transaction block
before Postgres 12. Check how `0037_question_result_pts` handles this in the
same file and mirror it exactly; if it runs the statement plainly, so does this.

- [ ] **Step 4: Add the enum members**

In `lemely/db/models/enums.py`, inside `class ReviewStatus`:

```python
    withdrawn = "withdrawn"
    """The subject of the review went away — the student deleted the paper.

    Distinct from ``dismissed``, which is a teacher's judgement and stamps
    ``resolved_by``. Recording a student's deletion as ``dismissed`` would lie
    in the audit column and make every dismissed-by-teacher metric count
    deletions (design 2026-09-22 §6).
    """
```

and inside `class NotificationType`:

```python
    review_withdrawn = "review_withdrawn"
```

- [ ] **Step 5: Add the model columns**

In `lemely/db/models/attempts.py`, add to **both** `Upload` and `Attempt`:

```python
    deleted_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    """When the student deleted this row; NULL means live (design 2026-09-22 §3).

    **Readers do not filter on this themselves.** A session-level loader
    criterion registered in :mod:`lemely.db.session` excludes deleted rows from
    every ORM select, so a query that does not opt in with
    ``execution_options(include_deleted=True)`` never sees one. Adding a
    belt-and-braces ``WHERE`` at a call site is actively harmful: it makes that
    site's tests pass even when the criterion is dead.
    """
```

In `lemely/db/models/ops.py`, add to `ReviewQueueItem`:

```python
    withdrawn_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    """Set with ``status = withdrawn`` when the attempt was soft-deleted.

    Holds **exactly** the attempt's ``deleted_at``, which is what lets restore
    reopen precisely the items that deletion withdrew and no others
    (design 2026-09-22 §6).
    """
```

- [ ] **Step 6: Create the exclusion model**

```python
"""The per-class paper exclusion behind a teacher's unshare (design §5).

The product's first per-paper sharing concept: teacher visibility of a
student's papers has until now derived purely from class enrollment, with
nothing to unshare. Grain is ``(class, attempt)`` — a class has owners and
administrators, so "their view" is the class's view, and D9 is per paper, so a
student in two classes unshared in one still counts in the other.

Read by exactly one thing,
:class:`~lemely.db.class_history.ClassScopedHistoryStore`, which is constructed
only in :mod:`lemely.web.routers.classes`. That containment is what makes the
student genuinely unaffected rather than carefully unaffected.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from lemely.db.base import Base
from lemely.db.models.enums import TimestampMixin


class ClassPaperExclusion(TimestampMixin, Base):
    """One attempt hidden from one class's view and analytics."""

    __tablename__ = "class_paper_exclusions"

    class_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("classes.id", ondelete="CASCADE"),
        primary_key=True,
    )
    attempt_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("attempts.id", ondelete="CASCADE"),
        primary_key=True,
    )
    excluded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )


__all__ = ["ClassPaperExclusion"]
```

Register it in `lemely/db/models/__init__.py` in **both** places that file
maintains, or `Base.metadata` will be incomplete and Alembic autogenerate will
propose dropping the table: add `deletion` to the lazy import list inside
`import_all_models()` (`:101`), and add
`from lemely.db.models.deletion import ClassPaperExclusion` to the module-level
re-exports above it, alphabetically between `catalogue` and `engagement`.

- [ ] **Step 7: Run the migration and the test**

```bash
alembic heads          # expect exactly 0038_point_group_key
alembic upgrade head
pytest tests/test_migration_0039.py --no-cov -q
```
Expected: 6 passed. Then confirm the downgrade path parses:
`alembic downgrade -1 && alembic upgrade head`

- [ ] **Step 8: Commit**

```bash
pre-commit run --all-files
git add lemely/db/migrations/versions/0039_paper_soft_delete.py lemely/db/models/ \
        tests/test_migration_0039.py
git commit -S -m "feat(db): soft-delete columns, withdrawn review status, class exclusions"
```

---

### Task 3: The session-level exclusion, and its guards

> **Review amendments (2026-09-24) — these OVERRIDE any conflicting text below in this task.** Source: pre-execution plan review (`.superpowers/sdd-deletion/plan-review.md`) and owner rulings R7–R10.
>
> - **Circular import (B1, reproduced).** Do NOT import models at the top of `lemely/db/session.py`: `lemely.auth.mirror` imports `session_scope` from it mid-initialisation and `import lemely.db` then fails (so does Alembic). Resolve the entity tuple lazily inside the listener, cached in a module global (e.g. `_soft_deleted_entities()` doing a function-local import of `Attempt`, `Upload`, `TeacherPaper`). Add a guard test that runs `python -c "import lemely.db; import lemely.db.session; import lemely.db.review_repo"` in a **subprocess** and asserts exit 0.
> - **Three entities, not two.** `TeacherPaper.deleted_at` exists from Task 2, so the criterion covers `(Attempt, Upload, TeacherPaper)` from the start. Add a `TeacherPaper` presence → absence → `include_deleted` test with the same three-assertion shape.
> - The reviewer verified by experiment that the criterion filters every shape the plan relies on (column-only GROUP BY, joins, EXISTS/IN subqueries, `aliased`, `session.get`, lazy loads) on SQLAlchemy 2.0.51. Keep the tests; Step 4's fallback should not be needed.
> - Put `ORMExecuteState` under `TYPE_CHECKING`.
> - **Permitted `include_deleted` callers, one list:** `session.py` (definition), `deletion_repo.py` (delete, restore, list — student and teacher), `purge.py`, `admin_repo.py`. Use the constant `INCLUDE_DELETED` everywhere, never the bare string, outside `session.py`.


**Files:**
- Modify: `lemely/db/session.py`
- Test: `tests/test_soft_delete_criteria.py`

**Interfaces:**
- Consumes: `Attempt.deleted_at`, `Upload.deleted_at` (Task 2).
- Produces: the registered listener `_exclude_soft_deleted`, and the contract that `session.execute(stmt.execution_options(include_deleted=True))` sees deleted rows. Tasks 7 and 10 are the only callers permitted to use it.

This is the task the whole design rests on. Its tests must fail against an
empty database — each asserts presence *before* absence.

- [ ] **Step 1: Write the failing test**

```python
"""The soft-delete loader criterion (design 2026-09-22 §3).

Every test here asserts the row is visible BEFORE it is stamped, so none of
them can pass against a database where the insert silently failed.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from lemely.db.models.attempts import Attempt
from lemely.db.session import _exclude_soft_deleted


def test_listener_is_registered_at_class_level() -> None:
    """Instance-level registration would leave tests/conftest's own sessionmaker bare."""
    assert event.contains(Session, "do_orm_execute", _exclude_soft_deleted)


def test_entity_select_hides_a_stamped_row(migrated_sessionmaker, seeded_attempt) -> None:
    with migrated_sessionmaker() as session:
        stmt = select(Attempt).where(Attempt.id == seeded_attempt.id)
        assert session.scalars(stmt).one_or_none() is not None  # present first

        session.execute(
            sa.update(Attempt)
            .where(Attempt.id == seeded_attempt.id)
            .values(deleted_at=datetime.now(UTC))
        )
        session.commit()
        session.expunge_all()

        assert session.scalars(stmt).one_or_none() is None  # then absent


def test_include_deleted_is_the_escape_hatch(migrated_sessionmaker, deleted_attempt) -> None:
    with migrated_sessionmaker() as session:
        stmt = select(Attempt).where(Attempt.id == deleted_attempt.id)
        assert session.scalars(stmt).one_or_none() is None
        opted_in = session.scalars(stmt.execution_options(include_deleted=True)).one_or_none()
        assert opted_in is not None
        assert opted_in.id == deleted_attempt.id


def test_column_only_select_is_filtered(migrated_sessionmaker, seeded_attempt) -> None:
    """seat_repo.py:369's exact shape — the one SQLAlchemy behaviour not yet confirmed."""
    stmt = (
        select(Attempt.user_id, func.max(Attempt.recorded_at))
        .where(Attempt.user_id == seeded_attempt.user_id)
        .group_by(Attempt.user_id)
    )
    with migrated_sessionmaker() as session:
        assert session.execute(stmt).all() != []  # present first

        session.execute(
            sa.update(Attempt)
            .where(Attempt.id == seeded_attempt.id)
            .values(deleted_at=datetime.now(UTC))
        )
        session.commit()
        session.expunge_all()

        assert session.execute(stmt).all() == []


def test_session_get_on_a_cold_session_returns_none(
    migrated_sessionmaker, deleted_attempt
) -> None:
    """placement_repo.py:332 and practice_repo.py:565 rely on this 404 path."""
    with migrated_sessionmaker() as session:
        assert session.get(Attempt, deleted_attempt.id) is None


def test_a_live_row_is_never_hidden(migrated_sessionmaker, seeded_attempt) -> None:
    with migrated_sessionmaker() as session:
        assert session.get(Attempt, seeded_attempt.id) is not None
```

Add `seeded_attempt` and `deleted_attempt` fixtures to this module (a user, an
upload, an attempt; the second stamped with `deleted_at`), following the
fixture style already used in `tests/test_self_review_repo.py`.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_soft_delete_criteria.py --no-cov -q`
Expected: FAIL — `ImportError: cannot import name '_exclude_soft_deleted'`

- [ ] **Step 3: Register the listener**

Add to `lemely/db/session.py`, after the existing imports:

```python
from sqlalchemy import event
from sqlalchemy.orm import ORMExecuteState, with_loader_criteria

from lemely.db.models.attempts import Attempt, Upload

#: Execution option that opts a statement out of the soft-delete filter.
#: Permitted in exactly three places — the recently-deleted list, restore, and
#: the purge job. Anywhere else is a bug; ``tests/test_include_deleted_scope.py``
#: pins the allowlist.
INCLUDE_DELETED = "include_deleted"


@event.listens_for(Session, "do_orm_execute")
def _exclude_soft_deleted(state: ORMExecuteState) -> None:
    """Hide soft-deleted attempts and uploads from every ORM select.

    Registered on the :class:`Session` **class**, not on a sessionmaker
    instance: ``sessionmaker`` is built independently here and in
    ``tests/conftest.py``, and an instance-level listener would leave the whole
    test suite unfiltered — green tests over an unprotected mechanism.

    This is the structural half of decisions D3. A reader that writes a plain
    ``select(Attempt)`` is safe by default, and seeing a deleted row requires
    the deliberate act of passing ``include_deleted=True``. The alternative
    considered — a ``live_attempts()`` helper policed by a source lint — fails
    on ``session.get`` and join shapes the lint cannot see.
    """
    if not state.is_select or state.is_column_load or state.is_relationship_load:
        return
    if state.execution_options.get(INCLUDE_DELETED):
        return
    for entity in (Attempt, Upload):
        state.statement = state.statement.options(
            with_loader_criteria(
                entity,
                lambda cls: cls.deleted_at.is_(None),
                include_aliases=True,
            )
        )
```

Extend the module docstring with a paragraph naming the criterion, the
`include_deleted` hatch, and the design document.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_soft_delete_criteria.py --no-cov -q`
Expected: PASS, 6 passed.

**If `test_column_only_select_is_filtered` fails**, the criterion does not
reach column-only selects. Do not weaken the test. Add an explicit
`.where(Attempt.deleted_at.is_(None))` to `seat_repo.py:369`'s statement, note
it in the design's §3.2, and keep this test as the pin.

- [ ] **Step 5: Commit**

```bash
pre-commit run --all-files
git add lemely/db/session.py tests/test_soft_delete_criteria.py
git commit -S -m "feat(db): exclude soft-deleted attempts from every ORM select"
```

---

### Task 4: Behavioural proof for each bypass reader

> **Review amendments (2026-09-24) — these OVERRIDE any conflicting text below in this task.** Source: pre-execution plan review (`.superpowers/sdd-deletion/plan-review.md`) and owner rulings R7–R10.
>
> - **Seat reader (I12).** There is no `SeatRepository.last_attempt_at_for`. The reader is `SeatService._last_attempt_by_student(session, student_ids)` (`lemely/db/seat_repo.py` ~:141, 358-373); call it directly with a session in the test. Read every other repository's real constructor and method before writing its pair.
> - Rename `test_weakness_rows_are_unreachable_except_through_an_attempt` to `test_weakness_join_excludes_a_deleted_attempt` and drop the docstring claim that it catches a future direct `select(WeaknessRecord)` — it cannot.


**Files:**
- Test: `tests/test_soft_delete_readers.py`
- Modify (only if Task 3 Step 4 required it): `lemely/db/seat_repo.py`

**Interfaces:**
- Consumes: Task 3's listener.
- Produces: no production interface — this is the regression net that makes §3.2's claim true rather than asserted.

Each test calls **the reader's own public function**, never `load()`. A test
routed through the history store would prove nothing about the reader.

- [ ] **Step 1: Write the failing tests**

One presence-then-absence pair per reader. The shape, written once here and
repeated per reader with its own call:

```python
def test_roster_last_attempt_at_drops_a_deleted_paper(
    migrated_sessionmaker, seeded_attempt
) -> None:
    repo = SeatRepository(migrated_sessionmaker)
    before = repo.last_attempt_at_for([seeded_attempt.user_id])
    assert before[seeded_attempt.user_id] is not None      # present first

    _soft_delete(migrated_sessionmaker, seeded_attempt.id)

    after = repo.last_attempt_at_for([seeded_attempt.user_id])
    assert after.get(seeded_attempt.user_id) is None       # then absent
```

Write the same pair for:
- `study_plan_repo` — the weakness query at `:367`
- `practice_repo` — the weakness query at `:820`
- `flashcard_repo` — the weakness query at `:804`
- `admin_repo` — the boundary-source counts at `:373`
- `review_repo.list_queue` — an open item on the attempt leaves the queue
- `DbHistoryStore.load` — the record disappears from `StudentHistory.records`

Substitute each repository's real constructor and method name; read the
function first rather than guessing its signature.

Add one test that does **not** move:

```python
def test_weakness_rows_are_unreachable_except_through_an_attempt(
    migrated_sessionmaker, seeded_attempt
) -> None:
    """Design §3.2's corollary, pinned as behaviour rather than left as a comment.

    WeaknessRecord carries no criterion of its own because every reader reaches
    it through Attempt. This test fails the day someone writes a direct
    ``select(WeaknessRecord).where(user_id == ...)``.
    """
    _soft_delete(migrated_sessionmaker, seeded_attempt.id)
    with migrated_sessionmaker() as session:
        rows = session.scalars(
            select(WeaknessRecord).join(Attempt, Attempt.id == WeaknessRecord.attempt_id)
        ).all()
    assert rows == []
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/test_soft_delete_readers.py --no-cov -q`
Expected: every test PASSES immediately if Task 3's criterion reaches that
reader. **A test that fails here is the finding** — add the explicit
`.where(Attempt.deleted_at.is_(None))` to that one reader and re-run.

- [ ] **Step 3: Commit**

```bash
pre-commit run --all-files
git add tests/test_soft_delete_readers.py lemely/db/
git commit -S -m "test(db): prove every attempt reader excludes soft-deleted rows"
```

---

### Task 5: `PaperDeletionService.delete`

> **Review amendments (2026-09-24) — these OVERRIDE any conflicting text below in this task.** Source: pre-execution plan review (`.superpowers/sdd-deletion/plan-review.md`) and owner rulings R7–R10.
>
> - **Unit of deletion is the upload (B3, R7).** Lock, in `id` order, the addressed attempt and every attempt sharing its `upload_id` (`FOR UPDATE`, `include_deleted`). Ownership is checked on the addressed attempt. Refusals (non-past-paper, integrity hold) are evaluated across **all** sibling attempts — any held sibling refuses the whole delete. Stamp every sibling and the upload with one `now`; withdraw open review items on every sibling. `DeletedPaper` gains `sibling_attempt_ids: list[uuid.UUID]` (all stamped attempts, including the addressed one); `withdrawn_item_ids` covers all of them. Add a test: two attempts on one upload, delete one, both vanish from `DbHistoryStore.load`.
> - **R4 lifting predicate, controller's resolution.** The hold lifts only when the attempt has at least one integrity review item (`reason IN (plagiarism_flag, ai_detection_flag)`) and **every** such item is in `(resolved, dismissed)`. An open or `withdrawn` integrity item keeps the hold. Replace the `_integrity_item_closed_by_teacher` query accordingly (an `EXISTS` of any integrity item AND NOT `EXISTS` of one outside `_TEACHER_CLOSED`) and add a test: two integrity items, one resolved, one open → still refused.
> - **Move `test_delete_restore_delete_does_not_launder_the_hold` to Task 6** (I5) — it needs `restore`, and as written no fixture can satisfy it.
> - Ignore stated pass counts ("10 passed"); the bar is: every test in the file passes, exit 0.


**Files:**
- Create: `lemely/db/deletion_repo.py`
- Test: `tests/test_deletion_repo.py`

**Interfaces:**
- Consumes: `RETENTION_DAYS`, `integrity_hold_until` (Task 1); the Task 2 columns; `INCLUDE_DELETED` (Task 3).
- Produces:
  - `class PaperDeletionError(Exception)` with subclasses `PaperNotFoundError`, `PaperNotDeletableError(deletable_from: datetime | None)`, `PaperNotRestorableError`.
  - `class DeletedPaper` — a frozen dataclass: `attempt_id: uuid.UUID`, `subject_code: str | None`, `paper_label: str`, `deleted_at: datetime`, `restore_deadline: datetime`, `withdrawn_item_ids: list[uuid.UUID]`.
  - `class PaperDeletionService` with `delete(user_id: str, attempt_id: str) -> DeletedPaper`.
- Tasks 6, 7, 8 and 9 build on these exact names.

`delete` runs as one transaction: load the attempt with `FOR UPDATE`, run the
three refusals, stamp `deleted_at` on the attempt and its upload, null the
upload's `idempotency_key`, flip open review items to `withdrawn` with
`withdrawn_at = deleted_at`. Notification is **after** commit (Task 9).

- [ ] **Step 1: Write the failing tests**

```python
def test_delete_hides_the_paper_from_the_students_history(service, store, attempt) -> None:
    assert [r.attempt_id for r in store.load(OWNER).records] == [str(attempt.id)]
    service.delete(OWNER, str(attempt.id))
    assert store.load(OWNER).records == []


def test_delete_stamps_the_upload_too(service, sessionmaker_, attempt) -> None:
    service.delete(OWNER, str(attempt.id))
    with sessionmaker_() as session:
        upload = session.scalars(
            select(Upload)
            .where(Upload.id == attempt.upload_id)
            .execution_options(include_deleted=True)
        ).one()
    assert upload.deleted_at is not None


def test_delete_nulls_the_idempotency_key(service, sessionmaker_, attempt) -> None:
    """Otherwise a re-upload of the same scan collides with the hidden row."""
    service.delete(OWNER, str(attempt.id))
    with sessionmaker_() as session:
        upload = session.scalars(
            select(Upload)
            .where(Upload.id == attempt.upload_id)
            .execution_options(include_deleted=True)
        ).one()
    assert upload.idempotency_key is None


def test_delete_withdraws_open_review_items_at_the_same_instant(
    service, sessionmaker_, attempt, open_item
) -> None:
    result = service.delete(OWNER, str(attempt.id))
    with sessionmaker_() as session:
        item = session.get(ReviewQueueItem, open_item.id)
    assert item.status is ReviewStatus.withdrawn
    assert item.withdrawn_at == result.deleted_at
    assert item.resolved_by is None  # a student's delete is not a teacher's judgement


def test_another_students_paper_is_a_404_not_a_403(service, attempt) -> None:
    with pytest.raises(PaperNotFoundError):
        service.delete(STRANGER, str(attempt.id))


def test_an_integrity_flagged_paper_is_refused_with_a_date(service, flagged_attempt) -> None:
    with pytest.raises(PaperNotDeletableError) as exc:
        service.delete(OWNER, str(flagged_attempt.id))
    assert exc.value.deletable_from == integrity_hold_until(flagged_attempt.recorded_at)


def test_a_low_confidence_review_does_not_block_deletion(service, attempt, open_item) -> None:
    """The predicate is the integrity flag, not 'has a review item'."""
    service.delete(OWNER, str(attempt.id))  # does not raise


@pytest.mark.parametrize("closed_as", [ReviewStatus.resolved, ReviewStatus.dismissed])
def test_a_teacher_closing_the_integrity_item_lifts_the_block(
    service, flagged_attempt, integrity_item, closed_as
) -> None:
    """R4: both outcomes mean a teacher looked. The student is never told which."""
    _set_status(integrity_item, closed_as)
    service.delete(OWNER, str(flagged_attempt.id))  # does not raise


def test_a_withdrawn_integrity_item_does_not_lift_the_block(
    service, flagged_attempt, integrity_item
) -> None:
    """R4a. Without this, delete+restore lifts a student's own hold.

    The cycle is the attack: deleting withdraws the item, and if `withdrawn`
    counted as closed, the restored paper would be freely deletable. Restore
    reopens the item (Task 6), so the block only holds if `withdrawn` is
    absent from the lifting set here.
    """
    _set_status(integrity_item, ReviewStatus.withdrawn)
    with pytest.raises(PaperNotDeletableError):
        service.delete(OWNER, str(flagged_attempt.id))


def test_delete_restore_delete_does_not_launder_the_hold(
    service, attempt_flagged_after_first_delete
) -> None:
    """End-to-end form of R4a, through the real delete and restore paths."""
    service.delete(OWNER, str(attempt_flagged_after_first_delete.id))
    service.restore(OWNER, str(attempt_flagged_after_first_delete.id))
    with pytest.raises(PaperNotDeletableError):
        service.delete(OWNER, str(attempt_flagged_after_first_delete.id))


def test_a_closed_low_confidence_item_does_not_lift_an_integrity_hold(
    service, flagged_attempt, integrity_item, resolved_low_confidence_item
) -> None:
    """The lifting query must filter on reason, not merely on status."""
    with pytest.raises(PaperNotDeletableError):
        service.delete(OWNER, str(flagged_attempt.id))


def test_a_quiz_attempt_is_refused(service, quiz_attempt) -> None:
    with pytest.raises(PaperNotDeletableError) as exc:
        service.delete(OWNER, str(quiz_attempt.id))
    assert exc.value.deletable_from is None


def test_deleting_twice_is_a_404(service, attempt) -> None:
    service.delete(OWNER, str(attempt.id))
    with pytest.raises(PaperNotFoundError):
        service.delete(OWNER, str(attempt.id))


def test_a_teacher_override_does_not_block_deletion(service, attempt, overridden_question) -> None:
    service.delete(OWNER, str(attempt.id))  # D10: does not raise
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_deletion_repo.py --no-cov -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'lemely.db.deletion_repo'`

- [ ] **Step 3: Implement `delete`**

Key body, inside `with self._sessionmaker.begin() as session:`:

```python
attempt = session.get(
    Attempt,
    parsed_id,
    with_for_update=True,
    execution_options={INCLUDE_DELETED: True},
)
if attempt is None or str(attempt.user_id) != user_id or attempt.deleted_at is not None:
    raise PaperNotFoundError("No such paper")
if attempt.origin is not AttemptOrigin.past_paper or attempt.upload_id is None:
    raise PaperNotDeletableError("Only uploaded papers can be deleted.", deletable_from=None)

hold_until = integrity_hold_until(attempt.recorded_at)
if (
    self._has_integrity_flag(session, attempt.id)
    and now < hold_until
    and not self._integrity_item_closed_by_teacher(session, attempt.id)
):
    raise PaperNotDeletableError(
        "This paper can't be deleted yet.", deletable_from=hold_until
    )

attempt.deleted_at = now
upload = session.get(
    Upload, attempt.upload_id, execution_options={INCLUDE_DELETED: True}
)
if upload is not None:
    upload.deleted_at = now
    # ux_uploads_user_idempotency survives the soft delete, so a re-upload of
    # the same scan would collide with a row the student cannot see.
    upload.idempotency_key = None

withdrawn = session.scalars(
    select(ReviewQueueItem).where(
        ReviewQueueItem.attempt_id == attempt.id,
        ReviewQueueItem.status == ReviewStatus.open,
    )
).all()
for item in withdrawn:
    item.status = ReviewStatus.withdrawn
    # Exactly the attempt's deleted_at — restore selects on this equality.
    item.withdrawn_at = now
```

`_has_integrity_flag` is one `EXISTS` over `question_results`:

```python
def _has_integrity_flag(self, session: Session, attempt_id: uuid.UUID) -> bool:
    """Whether any question on this attempt carries an integrity finding (D8).

    Reads the two booleans, never ``review_reason`` text and never the review
    queue: those are echoes of this fact, and an echo can be resolved away
    while the fact stands.
    """
    return bool(
        session.scalar(
            select(
                select(QuestionResult.id)
                .where(
                    QuestionResult.attempt_id == attempt_id,
                    sa.or_(
                        QuestionResult.plagiarism_flagged.is_(True),
                        QuestionResult.ai_detection_flagged.is_(True),
                    ),
                )
                .exists()
            )
        )
    )
```

And the lifting query R4 introduces:

```python
#: The outcomes that mean a teacher looked at an integrity finding (R4).
#: ``withdrawn`` is deliberately absent (R4a): it is set by a student's own
#: deletion, so counting it would let a delete-then-restore cycle lift the
#: student's own hold. Adding a member to this set is a security decision.
_TEACHER_CLOSED = (ReviewStatus.resolved, ReviewStatus.dismissed)

_INTEGRITY_REASONS = (ReviewReason.plagiarism_flag, ReviewReason.ai_detection_flag)


def _integrity_item_closed_by_teacher(
    self, session: Session, attempt_id: uuid.UUID
) -> bool:
    """Whether a teacher has closed an integrity review on this attempt (R4).

    Filters on **reason as well as status**: a resolved low-confidence item
    says nothing about an integrity finding, and treating any closed item as
    clearance would let an ordinary marking review unlock the hold.
    """
    return bool(
        session.scalar(
            select(
                select(ReviewQueueItem.id)
                .where(
                    ReviewQueueItem.attempt_id == attempt_id,
                    ReviewQueueItem.reason.in_(_INTEGRITY_REASONS),
                    ReviewQueueItem.status.in_(_TEACHER_CLOSED),
                )
                .exists()
            )
        )
    )
```

`now` is `datetime.now(UTC)`, taken once at the top of the transaction so the
attempt, the upload and every withdrawn item share one instant.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_deletion_repo.py --no-cov -q`
Expected: PASS, 10 passed.

- [ ] **Step 5: Commit**

```bash
pre-commit run --all-files
git add lemely/db/deletion_repo.py tests/test_deletion_repo.py
git commit -S -m "feat(db): delete a paper, withholding the reason for an integrity hold"
```

---

### Task 6: `restore`, and reopening what the delete withdrew

> **Review amendments (2026-09-24) — these OVERRIDE any conflicting text below in this task.** Source: pre-execution plan review (`.superpowers/sdd-deletion/plan-review.md`) and owner rulings R7–R10.
>
> - **Restore covers the whole upload (R7):** unstamp every attempt on the upload whose `deleted_at` equals the addressed attempt's, plus the upload; reopen items on all of them matched by `withdrawn_at == deleted_at`.
> - **Laundering tests, moved here from Task 5 and corrected (I5):** (1) delete an unflagged paper → set `plagiarism_flagged` and insert an open integrity item on it → restore → `delete` raises `PaperNotDeletableError`. (2) flagged, past the hold, with an open integrity item → delete (allowed) → restore → the item is `open` again with its original id and `created_at`.
> - Ignore stated pass counts.


**Files:**
- Modify: `lemely/db/deletion_repo.py`
- Modify: `tests/test_deletion_repo.py`

**Interfaces:**
- Consumes: Task 5's service and errors; `is_within_restore_window` (Task 1).
- Produces: `PaperDeletionService.restore(user_id: str, attempt_id: str) -> None`.

The laundering hole closes here. Without the reopen, delete → restore returns
the paper and silently drops the teacher's review item.

- [ ] **Step 1: Write the failing tests**

```python
def test_restore_brings_the_paper_back(service, store, attempt) -> None:
    service.delete(OWNER, str(attempt.id))
    assert store.load(OWNER).records == []
    service.restore(OWNER, str(attempt.id))
    assert [r.attempt_id for r in store.load(OWNER).records] == [str(attempt.id)]


def test_restore_reopens_exactly_the_items_this_deletion_withdrew(
    service, sessionmaker_, attempt, open_item, previously_dismissed_item
) -> None:
    """Delete then restore must not launder a review item out of the queue."""
    original_created_at = open_item.created_at
    service.delete(OWNER, str(attempt.id))
    service.restore(OWNER, str(attempt.id))

    with sessionmaker_() as session:
        reopened = session.get(ReviewQueueItem, open_item.id)
        untouched = session.get(ReviewQueueItem, previously_dismissed_item.id)

    assert reopened.status is ReviewStatus.open
    assert reopened.withdrawn_at is None
    assert reopened.created_at == original_created_at  # sorts where it always did
    assert untouched.status is ReviewStatus.dismissed  # not swept up


def test_restore_after_the_window_is_refused(service, sessionmaker_, attempt) -> None:
    service.delete(OWNER, str(attempt.id))
    _backdate_deletion(sessionmaker_, attempt.id, days=RETENTION_DAYS + 1)
    with pytest.raises(PaperNotRestorableError):
        service.restore(OWNER, str(attempt.id))


def test_restoring_a_live_paper_is_a_404(service, attempt) -> None:
    with pytest.raises(PaperNotFoundError):
        service.restore(OWNER, str(attempt.id))


def test_another_student_cannot_restore(service, attempt) -> None:
    service.delete(OWNER, str(attempt.id))
    with pytest.raises(PaperNotFoundError):
        service.restore(STRANGER, str(attempt.id))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_deletion_repo.py -k restore --no-cov -q`
Expected: FAIL — `AttributeError: 'PaperDeletionService' object has no attribute 'restore'`

- [ ] **Step 3: Implement `restore`**

```python
def restore(self, user_id: str, attempt_id: str) -> None:
    """Undo a deletion inside the retention window, review items and all.

    Reopens precisely the items this deletion withdrew, matched on
    ``withdrawn_at == attempt.deleted_at``. Without that, delete-then-restore
    returns the paper and silently drops the teacher's queue item — for an
    integrity item past D8's hold, a student clearing their own flag
    (design 2026-09-22 §6).
    """
    parsed_id = self._parse(attempt_id)
    now = datetime.now(UTC)
    with self._sessionmaker.begin() as session:
        attempt = session.get(
            Attempt,
            parsed_id,
            with_for_update=True,
            execution_options={INCLUDE_DELETED: True},
        )
        if attempt is None or str(attempt.user_id) != user_id or attempt.deleted_at is None:
            raise PaperNotFoundError("No such paper")
        deleted_at = attempt.deleted_at
        if not is_within_restore_window(deleted_at, now):
            raise PaperNotRestorableError("This paper can no longer be restored.")

        items = session.scalars(
            select(ReviewQueueItem).where(
                ReviewQueueItem.attempt_id == attempt.id,
                ReviewQueueItem.status == ReviewStatus.withdrawn,
                ReviewQueueItem.withdrawn_at == deleted_at,
            )
        ).all()
        for item in items:
            item.status = ReviewStatus.open
            item.withdrawn_at = None

        attempt.deleted_at = None
        upload = session.get(
            Upload, attempt.upload_id, execution_options={INCLUDE_DELETED: True}
        )
        if upload is not None:
            upload.deleted_at = None
```

The `idempotency_key` is **not** restored — it was released so a re-upload
could succeed, and a key that may already belong to another row cannot be
reclaimed. Say so in the docstring.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_deletion_repo.py --no-cov -q`
Expected: PASS, 15 passed.

- [ ] **Step 5: Commit**

```bash
pre-commit run --all-files
git add lemely/db/deletion_repo.py tests/test_deletion_repo.py
git commit -S -m "feat(db): restore a deleted paper and reopen the reviews it withdrew"
```

---

### Task 7: The recently-deleted list

> **Review amendments (2026-09-24) — these OVERRIDE any conflicting text below in this task.** Source: pre-execution plan review (`.superpowers/sdd-deletion/plan-review.md`) and owner rulings R7–R10.
>
> - **One row per upload (R7):** siblings share a `deleted_at`; return one row per upload, labelled from its newest attempt. Use a list-row dataclass without `withdrawn_item_ids` (e.g. `DeletedPaperSummary`) rather than filling it with `[]`.
> - Add `restore_floor(now) -> datetime` to `lemely/core/deletion.py` (with a test in `tests/test_core_deletion.py`) instead of re-deriving `now - timedelta(days=RETENTION_DAYS)` here.
> - Ignore stated pass counts.


**Files:**
- Modify: `lemely/db/deletion_repo.py`
- Modify: `tests/test_deletion_repo.py`

**Interfaces:**
- Consumes: Tasks 1, 5.
- Produces: `PaperDeletionService.list_deleted(user_id: str) -> list[DeletedPaper]`, newest deletion first.

One of the three permitted `include_deleted` callers.

- [ ] **Step 1: Write the failing tests**

```python
def test_list_deleted_returns_only_this_students_deleted_papers(
    service, attempt, other_students_attempt
) -> None:
    service.delete(OWNER, str(attempt.id))
    service.delete(STRANGER, str(other_students_attempt.id))
    rows = service.list_deleted(OWNER)
    assert [r.attempt_id for r in rows] == [attempt.id]


def test_list_deleted_is_empty_before_any_deletion(service, attempt) -> None:
    assert service.list_deleted(OWNER) == []


def test_list_deleted_carries_the_restore_deadline(service, attempt) -> None:
    deleted = service.delete(OWNER, str(attempt.id))
    row = service.list_deleted(OWNER)[0]
    assert row.restore_deadline == restore_deadline(deleted.deleted_at)


def test_list_deleted_excludes_rows_past_the_window(service, sessionmaker_, attempt) -> None:
    """A paper awaiting purge is gone as far as the student is concerned."""
    service.delete(OWNER, str(attempt.id))
    _backdate_deletion(sessionmaker_, attempt.id, days=RETENTION_DAYS + 1)
    assert service.list_deleted(OWNER) == []


def test_list_deleted_is_newest_first(service, attempt, second_attempt) -> None:
    service.delete(OWNER, str(attempt.id))
    service.delete(OWNER, str(second_attempt.id))
    rows = service.list_deleted(OWNER)
    assert [r.attempt_id for r in rows] == [second_attempt.id, attempt.id]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_deletion_repo.py -k list_deleted --no-cov -q`
Expected: FAIL — no attribute `list_deleted`.

- [ ] **Step 3: Implement**

```python
def list_deleted(self, user_id: str) -> list[DeletedPaper]:
    """This student's still-restorable deletions, newest first (D4).

    One of three callers permitted to pass ``include_deleted`` — the others
    are :meth:`restore` and the purge job. A row past the restore window is
    omitted: it is waiting to be purged and no countdown is honest about it.
    """
    owner = self._parse_user(user_id)
    now = datetime.now(UTC)
    floor = now - timedelta(days=RETENTION_DAYS)
    stmt = (
        select(Attempt)
        .where(
            Attempt.user_id == owner,
            Attempt.deleted_at.is_not(None),
            Attempt.deleted_at > floor,
        )
        .order_by(Attempt.deleted_at.desc(), Attempt.id)
        .execution_options(**{INCLUDE_DELETED: True})
    )
    with self._sessionmaker() as session:
        return [self._to_deleted_paper(a) for a in session.scalars(stmt).all()]
```

`_to_deleted_paper` builds `paper_label` from the attempt's subject and session
columns using the same convention `attempt_to_record` uses for
`ExamMetadata` — read it and reuse its `SESSION_MONTH_LABELS` lookup rather
than formatting a second way.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_deletion_repo.py --no-cov -q`
Expected: PASS, 20 passed.

- [ ] **Step 5: Commit**

```bash
pre-commit run --all-files
git add lemely/db/deletion_repo.py tests/test_deletion_repo.py
git commit -S -m "feat(db): list a student's restorable deletions with their deadlines"
```

---

### Task 8: Routes, DTOs, and the non-leak proof

> **Review amendments (2026-09-24) — these OVERRIDE any conflicting text below in this task.** Source: pre-execution plan review (`.superpowers/sdd-deletion/plan-review.md`) and owner rulings R7–R10.
>
> - **Flat 409 body (B4).** `HTTPException(detail=dict)` nests under `detail`. Return `JSONResponse(status_code=409, content={"detail": msg, "deletableFrom": iso})` for the hold (omit `deletableFrom` for the quiz refusal). Design §8 and Task 14 read the flat shape.
> - **410 for restore past the window (I13):** map `PaperNotRestorableError` to 410 and test it.
> - **Bad ids (Minor 5):** a non-UUID `attempt_id` (including the literal `deleted` on DELETE) returns the fixed 404 `"No such paper"`, never 422.
> - **Shared leak helpers:** put the detectors in `tests/_integrity_leak.py` — `leaks_to_student(obj)` (integrity words **and** `review`) and `leaks_integrity(obj)` (integrity words only, for teacher-facing copy in Task 9). Both reuse `_INTEGRITY_REASON_PREFIXES` from `lemely/web/schemas.py`, and both are proven to detect.
> - **Existing guard goes red here (I10).** `web/tests/unit/dataHandling.test.ts` has `still has no upload-deletion route` (~:233-240). Invert it in this task: assert the student deletion route now exists in `lemely/web/routers/student_deletion.py`. Task 15 adds the page-copy assertions.


**Files:**
- Create: `lemely/web/routers/student_deletion.py`
- Create: `lemely/web/schemas_student_deletion.py`
- Modify: `lemely/web/deps.py` (add `get_paper_deletion_service`)
- Modify: `lemely/web/app.py` (register the router)
- Test: `tests/test_student_deletion_routes.py`

**Interfaces:**
- Consumes: Tasks 5–7.
- Produces: `DELETE /api/student/attempts/{attempt_id}` → 204; `POST /api/student/attempts/{attempt_id}/restore` → 204; `GET /api/student/attempts/deleted` → `DeletedPapersDTO`. Task 14 consumes these.

A new thin router on the `student_self_review.py` precedent, not growth of
`student.py`. `PaperNotFoundError` → 404 with the fixed body `"No such paper"`,
never a 403 — the route must not be an existence oracle for another student's
attempts.

- [ ] **Step 1: Write the failing tests**

```python
def test_delete_returns_204_and_hides_the_paper(client, attempt) -> None:
    assert client.get("/api/student/overview").json()["subjects"] != []
    assert client.delete(f"/api/student/attempts/{attempt.id}").status_code == 204
    assert client.get("/api/student/overview").json()["subjects"] == []


def test_deleting_another_students_paper_is_404_with_the_fixed_body(
    client_as_stranger, attempt
) -> None:
    response = client_as_stranger.delete(f"/api/student/attempts/{attempt.id}")
    assert response.status_code == 404
    assert response.json()["detail"] == "No such paper"


def test_a_teacher_cannot_delete_a_students_paper(teacher_client, attempt) -> None:
    assert teacher_client.delete(f"/api/student/attempts/{attempt.id}").status_code == 403


def test_integrity_hold_is_409_with_a_date_and_no_reason(client, flagged_attempt) -> None:
    response = client.delete(f"/api/student/attempts/{flagged_attempt.id}")
    assert response.status_code == 409
    body = response.json()
    assert body["detail"] == "This paper can't be deleted yet."
    assert body["deletableFrom"].startswith("2026-")


def test_the_409_body_leaks_no_integrity_language(client, flagged_attempt) -> None:
    response = client.delete(f"/api/student/attempts/{flagged_attempt.id}")
    assert _leaks_integrity(response.json()) is False


def test_the_leak_detector_actually_detects(client) -> None:
    """A leak test whose detector has never detected is a test that cannot fail."""
    assert _leaks_integrity({"detail": "flagged for plagiarism (score 0.94)"}) is True
    assert _leaks_integrity({"detail": "This paper can't be deleted yet."}) is False


def test_a_quiz_attempt_is_409_with_its_own_copy(client, quiz_attempt) -> None:
    response = client.delete(f"/api/student/attempts/{quiz_attempt.id}")
    assert response.status_code == 409
    assert response.json()["detail"] == "Only uploaded papers can be deleted."


def test_restore_returns_204_and_the_paper_comes_back(client, attempt) -> None:
    client.delete(f"/api/student/attempts/{attempt.id}")
    assert client.post(f"/api/student/attempts/{attempt.id}/restore").status_code == 204
    assert client.get("/api/student/overview").json()["subjects"] != []


def test_deleted_list_is_scoped_to_the_caller(client, client_as_stranger, attempt) -> None:
    client.delete(f"/api/student/attempts/{attempt.id}")
    assert len(client.get("/api/student/attempts/deleted").json()["papers"]) == 1
    assert client_as_stranger.get("/api/student/attempts/deleted").json()["papers"] == []


def test_the_history_row_does_not_pre_signal_deletability(client, flagged_attempt) -> None:
    """Design §8: no screen marks one paper as different before the student acts."""
    body = client.get("/api/student/overview").json()
    serialised = json.dumps(body)
    assert "canDelete" not in serialised
    assert "deletableFrom" not in serialised
```

`_leaks_integrity` reuses the segment prefixes
`lemely.web.schemas._INTEGRITY_REASON_PREFIXES` already maintains, plus the
words `integrity`, `flag`, `cheat`, `similar`, `review` and `score`, applied to
the fully serialised body — never to one field.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_student_deletion_routes.py --no-cov -q`
Expected: FAIL — 404 on every route (the router does not exist).

- [ ] **Step 3: Write the DTOs**

```python
"""Wire shapes for the paper-deletion routes (design 2026-09-22 §8).

``DeletedPaperDTO`` deliberately carries no mark, grade or percentage. The
recently-deleted list is a recovery surface, not a second results screen, and
a deleted paper's marks are exactly what the student asked to stop seeing.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DeletedPaperDTO(BaseModel):
    """One restorable deletion, with its countdown."""

    model_config = ConfigDict(extra="forbid")

    attemptId: str
    paperLabel: str
    subjectCode: str | None
    deletedAt: datetime
    restoreDeadline: datetime


class DeletedPapersDTO(BaseModel):
    """The recently-deleted area's whole payload."""

    model_config = ConfigDict(extra="forbid")

    papers: list[DeletedPaperDTO]
    retentionDays: int
```

- [ ] **Step 4: Write the router**

Mirror `student_self_review.py` exactly: module docstring naming the design,
`_raise_for` mapping errors to statuses, `require_role(Role.student)` on every
route. The one shape worth spelling out:

```python
def _raise_for(exc: PaperDeletionError) -> NoReturn:
    """Map a deletion error to its status.

    The 404 body is fixed at ``"No such paper"`` for not-yours and not-found
    alike, so the route is not an existence oracle for another student's
    attempts — the same rule the self-review routes follow.

    The 409 carries ``deletableFrom`` and **never** the reason. D8's hold
    exists because of an integrity finding, and QUALITY-BAR.md makes integrity
    teacher-only: "you can't delete this because it was flagged for plagiarism"
    is precisely the accusation that rule forbids. The word "review" is absent
    too — an ordinary low-confidence review does not block deletion, so naming
    review here would be both a leak and a lie.
    """
    if isinstance(exc, PaperNotFoundError):
        raise HTTPException(status_code=404, detail="No such paper") from exc
    if isinstance(exc, PaperNotDeletableError):
        detail: dict[str, object] = {"detail": str(exc)}
        if exc.deletable_from is not None:
            detail["deletableFrom"] = exc.deletable_from.isoformat()
        raise HTTPException(status_code=409, detail=detail) from exc
    raise HTTPException(status_code=409, detail=str(exc)) from exc
```

Register in `lemely/web/app.py` beside the self-review router, and add the
`@lru_cache(maxsize=1)` factory to `deps.py` following
`get_self_review_service`'s shape.

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_student_deletion_routes.py --no-cov -q`
Expected: PASS, 10 passed.

- [ ] **Step 6: Commit**

```bash
pre-commit run --all-files
git add lemely/web/routers/student_deletion.py lemely/web/schemas_student_deletion.py \
        lemely/web/deps.py lemely/web/app.py tests/test_student_deletion_routes.py
git commit -S -m "feat(web): student delete, restore and recently-deleted routes"
```

---

### Task 9: Telling the teacher (D10)

> **Review amendments (2026-09-24) — these OVERRIDE any conflicting text below in this task.** Source: pre-execution plan review (`.superpowers/sdd-deletion/plan-review.md`) and owner rulings R7–R10.
>
> - **Recipients (I6):** use `ClassService.teachers_for_student` (`lemely/db/class_repo.py` ~:248); student name via `ClassService.display_name_for` (~:230). When `assigned_teacher_id` is set, notify only that teacher.
> - **Copy vs detector (I6):** teacher-facing copy may say "review". Test it with `leaks_integrity` from `tests/_integrity_leak.py` (integrity words only), not the student detector.
> - **No deep link (Minor 6):** a withdrawn item 403s when opened. Payload carries ids for record only; confirm the inbox renders `review_withdrawn` as non-navigable (check how the web inbox uses `payload` and handle the new type).
> - Fixtures `notifications.for_user` / `broken_notifications` are illustrative — use the real `NotificationService` listing method and a transport/service double that raises.
> - `withdrawn_item_ids` spans all sibling attempts (R7).


**Files:**
- Modify: `lemely/web/routers/student_deletion.py`
- Modify: wherever notification-type preference defaults are governed (find it with `grep -rn "NotificationType.at_risk_alert" lemely/db/notification_prefs_repo.py`)
- Test: `tests/test_deletion_notifications.py`

**Interfaces:**
- Consumes: `DeletedPaper.withdrawn_item_ids` (Task 5), `NotificationType.review_withdrawn` (Task 2).
- Produces: no new public API; a `review_withdrawn` inbox row per withdrawn item.

Fires **after** the delete transaction commits, through `notify_safely`, so a
notification failure can never roll back the deletion the student asked for.

- [ ] **Step 1: Write the failing tests**

```python
def test_the_assigned_teacher_is_told_when_their_item_is_withdrawn(
    client, notifications, attempt, item_assigned_to_teacher
) -> None:
    client.delete(f"/api/student/attempts/{attempt.id}")
    rows = notifications.for_user(TEACHER_ID)
    assert [r.type for r in rows] == [NotificationType.review_withdrawn]


def test_the_notification_never_says_why(client, notifications, attempt, flagged_item) -> None:
    client.delete(f"/api/student/attempts/{attempt.id}")
    row = notifications.for_user(TEACHER_ID)[0]
    assert _leaks_integrity({"title": row.title, "body": row.body}) is False


def test_delete_restore_delete_notifies_twice(client, notifications, attempt, open_item) -> None:
    """The dedupe key carries deleted_at, so a second real deletion is a second notice."""
    client.delete(f"/api/student/attempts/{attempt.id}")
    client.post(f"/api/student/attempts/{attempt.id}/restore")
    client.delete(f"/api/student/attempts/{attempt.id}")
    assert len(notifications.for_user(TEACHER_ID)) == 2


def test_a_paper_with_no_open_item_notifies_nobody(client, notifications, attempt) -> None:
    client.delete(f"/api/student/attempts/{attempt.id}")
    assert notifications.for_user(TEACHER_ID) == []


def test_a_notification_failure_does_not_undo_the_deletion(
    client, broken_notifications, store, attempt, open_item
) -> None:
    assert client.delete(f"/api/student/attempts/{attempt.id}").status_code == 204
    assert store.load(OWNER).records == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_deletion_notifications.py --no-cov -q`
Expected: FAIL — no `review_withdrawn` rows are created.

- [ ] **Step 3: Implement the fan-out**

After `service.delete(...)` returns, for each withdrawn item id:

`notify_safely` takes the service **and** the transport positionally before its
keyword arguments (`lemely/web/notify.py:77`), and never raises:

```python
notify_safely(
    notifications,
    transport,
    user_id=recipient_id,
    type=NotificationType.review_withdrawn,
    title="A review item was withdrawn",
    body=f"{student_name} deleted {result.paper_label}, so the question you had to review is gone.",
    # deleted_at in the key: a delete → restore → delete cycle is two real
    # events and must notify twice.
    dedupe_key=f"review_withdrawn:{item_id}:{result.deleted_at.isoformat()}",
    payload={
        "reviewItemId": str(item_id),
        "attemptId": str(result.attempt_id),
        "studentId": user_id,
    },
    seam="review_withdrawn",
)
```

Recipient is `assigned_teacher_id` when set, otherwise every teacher in the
item's visible-class set — reuse `review_repo`'s existing visibility helper
rather than writing a second class-visibility query. **The body never says
why**, because we never ask why.

Add `review_withdrawn` to the notification-preference defaults so the type is
allowed by default; a type with no default is silently dropped by
`NotificationService.create`'s preference gate.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_deletion_notifications.py --no-cov -q`
Expected: PASS, 5 passed.

- [ ] **Step 5: Commit**

```bash
pre-commit run --all-files
git add lemely/web/routers/student_deletion.py lemely/db/ tests/test_deletion_notifications.py
git commit -S -m "feat(web): notify a teacher when a deletion withdraws their review item"
```

---

### Task 10: The purge job

> **Review amendments (2026-09-24) — these OVERRIDE any conflicting text below in this task.** Source: pre-execution plan review (`.superpowers/sdd-deletion/plan-review.md`) and owner rulings R7–R10.
>
> - **Sweeper wiring (I8):** add `storage: StorageBackend | None = None` and `bucket: str | None = None` to the `Sweeper` dataclass (`lemely/web/scheduled_notifications.py` ~:443-457), skip purge when unset, and wire `get_storage_backend()` + `settings.storage.bucket` in `get_sweeper` (`lemely/web/deps.py` ~:770-776). Add `deps.py` to the commit.
> - **Purge by upload (B3, R7):** delete the object(s) only when **every** attempt on the upload has `deleted_at <= cutoff`. Delete all those attempts, then the upload, each DELETE re-asserting `deleted_at <= cutoff`. Add a fixture with two attempts on one upload.
> - Order candidates by `(deleted_at, id)`. Persistent GCS failures can hold up to `LIMIT` rows per pass; accept this, say so in the docstring, and rely on Task 11's backlog metric to surface it.
> - If the FK-ordering question fails, write migration `0040`; never edit 0039.


**Files:**
- Create: `lemely/web/purge.py`
- Modify: `lemely/web/scheduled_notifications.py` (register the job on `Sweeper`)
- Test: `tests/test_purge_job.py`

**Interfaces:**
- Consumes: `purge_cutoff`, `PURGE_GRACE` (Task 1); `INCLUDE_DELETED` (Task 3); the storage seam's `delete(bucket, object_path)`.
- Produces: `purge_expired_papers(session_factory, storage, bucket, *, now=None, limit=50) -> int`, returning the number of attempts purged.

GCS first, row as the record of intent. Safe against restore by the time gap,
not by locking.

- [ ] **Step 1: Write the failing tests**

```python
def test_purge_deletes_the_object_then_every_row(
    sessionmaker_, fake_storage, fully_populated_deleted_attempt
) -> None:
    """The fixture carries question results, points, revisions, weaknesses, an
    upload AND a review item with question_result_id set — without all of them
    the FK-ordering question is never exercised."""
    attempt = fully_populated_deleted_attempt
    assert purge_expired_papers(sessionmaker_, fake_storage, BUCKET) == 1

    assert fake_storage.deleted == [(BUCKET, attempt.upload.storage_path)]
    with sessionmaker_() as session:
        assert session.scalars(
            select(Attempt).where(Attempt.id == attempt.id)
            .execution_options(include_deleted=True)
        ).all() == []
        assert session.scalars(
            select(QuestionResult).where(QuestionResult.attempt_id == attempt.id)
        ).all() == []
        assert session.scalars(
            select(ReviewQueueItem).where(ReviewQueueItem.attempt_id == attempt.id)
        ).all() == []


def test_a_row_inside_the_window_is_untouched(
    sessionmaker_, fake_storage, recently_deleted_attempt
) -> None:
    assert purge_expired_papers(sessionmaker_, fake_storage, BUCKET) == 0
    assert fake_storage.deleted == []


def test_a_row_inside_the_grace_gap_is_untouched(sessionmaker_, fake_storage, attempt) -> None:
    """Exactly RETENTION_DAYS old: no longer restorable, not yet purgeable."""
    _backdate_deletion(sessionmaker_, attempt.id, days=RETENTION_DAYS, minutes=1)
    assert purge_expired_papers(sessionmaker_, fake_storage, BUCKET) == 0


def test_a_storage_failure_leaves_both_rows_for_the_next_pass(
    sessionmaker_, failing_storage, fully_populated_deleted_attempt
) -> None:
    assert purge_expired_papers(sessionmaker_, failing_storage, BUCKET) == 0
    with sessionmaker_() as session:
        assert session.scalars(
            select(Attempt).where(Attempt.id == fully_populated_deleted_attempt.id)
            .execution_options(include_deleted=True)
        ).one_or_none() is not None


def test_a_missing_object_is_not_a_failure(
    sessionmaker_, not_found_storage, fully_populated_deleted_attempt
) -> None:
    assert purge_expired_papers(sessionmaker_, not_found_storage, BUCKET) == 1


def test_the_sibling_mark_scheme_scan_goes_too(
    sessionmaker_, fake_storage, attempt_with_scheme_scan
) -> None:
    purge_expired_papers(sessionmaker_, fake_storage, BUCKET)
    paths = {path for _, path in fake_storage.deleted}
    assert any(p.endswith("/mark_scheme.pdf") for p in paths)


def test_mark_scheme_reference_rows_are_never_touched(
    sessionmaker_, fake_storage, fully_populated_deleted_attempt, mark_scheme_row
) -> None:
    """D2: mark schemes are shared reference data, not the student's upload."""
    purge_expired_papers(sessionmaker_, fake_storage, BUCKET)
    with sessionmaker_() as session:
        assert session.get(MarkScheme, mark_scheme_row.id) is not None


def test_purging_twice_is_a_no_op(
    sessionmaker_, fake_storage, fully_populated_deleted_attempt
) -> None:
    assert purge_expired_papers(sessionmaker_, fake_storage, BUCKET) == 1
    assert purge_expired_papers(sessionmaker_, fake_storage, BUCKET) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_purge_job.py --no-cov -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'lemely.web.purge'`

- [ ] **Step 3: Implement the job**

Candidate select (the only other `include_deleted` caller):

```python
stmt = (
    select(Attempt)
    .where(Attempt.deleted_at.is_not(None), Attempt.deleted_at <= cutoff)
    .order_by(Attempt.deleted_at)
    .limit(limit)
    .execution_options(**{INCLUDE_DELETED: True})
)
```

Then per attempt, **object first**:

```python
try:
    storage.delete(bucket, storage_path)
    if scheme_path is not None:
        storage.delete(bucket, scheme_path)
except ExternalServiceError:
    # Leave both rows: still hidden, still past cutoff, retried next pass.
    # DB-first would leak an object no row remembers, and the public data page
    # would then be describing something untrue.
    log.warning("purge_object_delete_failed", attempt_id=str(attempt_id), exc_info=True)
    continue
```

Then the conditional delete, in its own short transaction:

```python
# The cutoff is re-asserted in the WHERE rather than trusted from the select
# above: two replicas may be mid-pass, and a row restored in between must not
# be deleted by a decision taken a moment ago.
result = session.execute(
    sa.delete(Attempt).where(Attempt.id == attempt_id, Attempt.deleted_at <= cutoff)
)
if result.rowcount == 0:
    continue
session.execute(
    sa.delete(Upload).where(
        Upload.id == upload_id,
        ~sa.exists().where(Attempt.upload_id == upload_id),
    )
)
```

The attempt must go before the upload: `attempts.upload_id` carries no
`ondelete`, so the FK would refuse the upload's deletion while the attempt
stands. The `exists` guard covers an upload shared by more than one attempt.

Register on the `Sweeper` alongside the three notification jobs, gated by the
same `sweeper_enabled` flag, and extend `scheduled_notifications`' module
docstring to name the fourth job.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_purge_job.py --no-cov -q`
Expected: PASS, 8 passed.

**If the fully-populated fixture raises a `ForeignKeyViolation`** on
`review_queue.question_result_id`, add `ondelete="CASCADE"` to that FK in
migration 0039 and note it in the design's §7.

- [ ] **Step 5: Commit**

```bash
pre-commit run --all-files
git add lemely/web/purge.py lemely/web/scheduled_notifications.py tests/test_purge_job.py
git commit -S -m "feat(web): purge expired deletions, object first, row as intent"
```

---

### Task 11: Purge-backlog visibility and `include_deleted` containment

> **Review amendments (2026-09-24) — these OVERRIDE any conflicting text below in this task.** Source: pre-execution plan review (`.superpowers/sdd-deletion/plan-review.md`) and owner rulings R7–R10.
>
> - **AST detector (I7):** write a function that walks `lemely/` ASTs and reports files using `INCLUDE_DELETED` (Name/Attribute), keyword `include_deleted=`, or the string `"include_deleted"` inside a Call — ignoring docstrings and comments. Assert the allowlist `{session.py, deletion_repo.py, purge.py, admin_repo.py}`. Prove it by running **the same function** over a `tmp_path` package containing an intruder and asserting it is reported.
> - **Admin target (I14):** the method is `PlatformAdminService.pipeline_health()` returning `PipelineHealth` (`lemely/db/admin_repo.py` ~:147, 349-395). Expose `purgeBacklog` via the admin DTO (`lemely/web/schemas_admin.py`) and router (`lemely/web/routers/admin.py`); add those files.


**Files:**
- Modify: `lemely/db/admin_repo.py`
- Test: `tests/test_purge_backlog_metric.py`, `tests/test_include_deleted_scope.py`

**Interfaces:**
- Consumes: Task 10.
- Produces: `purge_backlog` on the admin health payload — the count of attempts more than one day past their purge cutoff and still present.

- [ ] **Step 1: Write the failing tests**

```python
def test_backlog_counts_a_row_that_should_have_been_purged(admin_repo, stuck_attempt) -> None:
    assert admin_repo.health().purge_backlog == 1


def test_backlog_is_zero_when_purge_is_keeping_up(admin_repo, recently_deleted_attempt) -> None:
    assert admin_repo.health().purge_backlog == 0
```

```python
def test_include_deleted_appears_only_where_it_is_allowed() -> None:
    """The escape hatch must not spread beyond its three callers."""
    allowed = {
        Path("lemely/db/session.py"),
        Path("lemely/db/deletion_repo.py"),
        Path("lemely/web/purge.py"),
    }
    found = {
        path
        for path in Path("lemely").rglob("*.py")
        if "include_deleted" in path.read_text(encoding="utf-8")
    }
    assert found == allowed


def test_the_scope_test_would_notice_a_new_user(tmp_path) -> None:
    """The detector is shown to detect, so this test cannot pass vacuously."""
    intruder = tmp_path / "rogue.py"
    intruder.write_text('stmt.execution_options(include_deleted=True)\n', encoding="utf-8")
    assert "include_deleted" in intruder.read_text(encoding="utf-8")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_purge_backlog_metric.py tests/test_include_deleted_scope.py --no-cov -q`
Expected: FAIL — `AttributeError: … has no attribute 'purge_backlog'`

- [ ] **Step 3: Implement the metric**

Add to the admin health query, beside the boundary-source counts:

```python
purge_backlog=session.scalar(
    select(func.count())
    .select_from(Attempt)
    .where(Attempt.deleted_at <= purge_cutoff(now) - timedelta(days=1))
    .execution_options(**{INCLUDE_DELETED: True})
)
```

Adding `admin_repo.py` to the allowlist in the scope test is expected here —
update it in the same commit so the test states the real, intended set.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_purge_backlog_metric.py tests/test_include_deleted_scope.py --no-cov -q`
Expected: PASS, 4 passed.

- [ ] **Step 5: Commit**

```bash
pre-commit run --all-files
git add lemely/db/admin_repo.py tests/test_purge_backlog_metric.py tests/test_include_deleted_scope.py
git commit -S -m "feat(db): surface the purge backlog and pin the include_deleted allowlist"
```

---

### Task 12: The class-scoped history store (D9's mechanism)

> **Review amendments (2026-09-24) — these OVERRIDE any conflicting text below in this task.** Source: pre-execution plan review (`.superpowers/sdd-deletion/plan-review.md`) and owner rulings R7–R10.
>
> - **Protocol (I9):** `HistoryStoreProtocol` is not `runtime_checkable`; replace the `isinstance` test with a mypy-checked assignment `store: HistoryStoreProtocol = ClassScopedHistoryStore(...)`.
> - **One signature:** `ClassScopedHistoryStore(inner: HistoryStoreProtocol, excluded_attempt_ids: frozenset[str])`. Create `lemely/db/class_exclusion_repo.py` here with `ClassExclusionRepository(sessionmaker).excluded_attempt_ids(class_id) -> frozenset[str]` (read only; Task 13 adds writes).
> - **Define `load_roster_histories(store, roster) -> list[tuple[RosterEntry, StudentHistory]]`**; callers at `classes.py` ~:217 and ~:404 take the histories from it, ~:298 uses the tuples.
> - Existing tests to keep green: `tests/test_web_classes.py`, `tests/test_class_analytics.py` (not `test_classes_routes.py`).


**Files:**
- Create: `lemely/db/class_history.py`
- Modify: `lemely/web/routers/classes.py` (replace the three roster comprehensions)
- Test: `tests/test_class_scoped_history.py`

**Interfaces:**
- Consumes: `ClassPaperExclusion` (Task 2).
- Produces: `ClassScopedHistoryStore(inner: HistoryStoreProtocol, exclusions: ClassExclusionService, class_id: uuid.UUID)` satisfying `HistoryStoreProtocol`, and `load_roster_histories(store, roster) -> list[StudentHistory]` — the single helper that replaces `classes.py:217`, `:298` and `:404`.

- [ ] **Step 1: Write the failing tests**

```python
def test_an_excluded_attempt_is_dropped_from_the_class_view(
    scoped_store, inner_store, excluded_attempt
) -> None:
    assert len(inner_store.load(STUDENT).records) == 2      # present in the raw store
    assert len(scoped_store.load(STUDENT).records) == 1     # absent in the class's view


def test_exclusion_is_scoped_to_one_class(
    scoped_store_a, scoped_store_b, excluded_in_a_attempt
) -> None:
    assert len(scoped_store_a.load(STUDENT).records) == 1
    assert len(scoped_store_b.load(STUDENT).records) == 2


def test_the_scoped_store_satisfies_the_protocol() -> None:
    assert isinstance(ClassScopedHistoryStore(...), HistoryStoreProtocol)


def test_a_record_with_no_attempt_id_is_never_dropped(scoped_store, file_store_record) -> None:
    """The JSON store carries attempt_id=None; it cannot be excluded and must pass through."""
    assert len(scoped_store.load(STUDENT).records) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_class_scoped_history.py --no-cov -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'lemely.db.class_history'`

- [ ] **Step 3: Implement**

```python
class ClassScopedHistoryStore:
    """A history store that hides papers unshared from one class (D9).

    A wrapper rather than a parameter on
    :class:`~lemely.core.history.HistoryStoreProtocol`: that protocol is
    satisfied by the JSON file store too, where a class id is meaningless.
    Constructed **only** in :mod:`lemely.web.routers.classes`, which is what
    keeps the student's own surfaces structurally unable to see exclusions.

    The exclusion set is fetched once per class, not once per student.
    """

    def __init__(
        self,
        inner: HistoryStoreProtocol,
        excluded_attempt_ids: frozenset[str],
    ) -> None:
        self._inner = inner
        self._excluded = excluded_attempt_ids

    def load(self, student_id: str) -> StudentHistory:
        """The student's history minus anything unshared from this class."""
        history = self._inner.load(student_id)
        if not self._excluded:
            return history
        kept = [
            record
            for record in history.records
            # A record with no attempt_id came from the file store and cannot
            # be addressed by an exclusion; pass it through rather than guess.
            if record.attempt_id is None or record.attempt_id not in self._excluded
        ]
        return StudentHistory(student_id=history.student_id, records=kept)

    def append(self, student_id: str, record: PaperRecord) -> None:
        """Delegate; a class view never writes, but the protocol requires it."""
        self._inner.append(student_id, record)

    def list_students(self) -> list[str]:
        """Delegate unchanged — exclusions hide papers, never students."""
        return self._inner.list_students()
```

Then replace all three comprehensions in `classes.py` with one call to
`load_roster_histories(scoped_store, roster)`, which is where the triplication
finally goes away.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_class_scoped_history.py --no-cov -q`
Expected: PASS, 4 passed.

Then run the existing class-route tests to prove the refactor is behaviour-
preserving: `pytest tests/test_classes_routes.py --no-cov -q`

- [ ] **Step 5: Commit**

```bash
pre-commit run --all-files
git add lemely/db/class_history.py lemely/web/routers/classes.py tests/test_class_scoped_history.py
git commit -S -m "refactor(web): one class-scoped history load, ready to honour exclusions"
```

---

### Task 13: The unshare routes

> **Review amendments (2026-09-24) — these OVERRIDE any conflicting text below in this task.** Source: pre-execution plan review (`.superpowers/sdd-deletion/plan-review.md`) and owner rulings R7–R10.
>
> - **Routes & status (I2):** POST/DELETE `/api/classes/{class_id}/papers/{attempt_id}/unshare`. A foreign class returns **403** (reuse the existing check in `classes.py` ~:124-125); fix the test to expect 403. Validate the attempt exists and belongs to a student on that class's roster, else 404 — never let an unknown id reach the FK.
> - **Queue (I1, R8):** the teacher queue is `GET /api/teacher/review` and rows carry `itemId`. `list_queue` scopes by student via `_visible_class_map` (single class per student). Add a student → set-of-class-ids helper (do not change `_visible_class_map`'s existing consumers) and exclude an item only when its attempt is excluded in **every** caller class that rosters the student. Add a test: student in two of the teacher's classes, unshared in one → item stays. Add `lemely/db/review_repo.py` to Files and the commit.
> - **Average (I2):** `average` is on `ClassSummaryDTO` from `GET /api/teacher/classes`, and is the mean of each student's *latest* percentage — the fixture must unshare the student's latest past paper, or the inequality is vacuous.
> - **R9:** class pages only; `teacher.py` surfaces are unchanged. Note it for the PR body.
> - Ignore stated pass counts.


**Files:**
- Modify: `lemely/web/routers/classes.py`
- Create: `lemely/db/class_exclusion_repo.py`
- Test: `tests/test_class_unshare.py`

**Interfaces:**
- Consumes: Tasks 2 and 12.
- Produces: `POST /api/classes/{class_id}/papers/{attempt_id}/unshare` → 204, `DELETE …/unshare` → 204 (reshare).

- [ ] **Step 1: Write the failing tests**

```python
def test_unshare_changes_the_class_average_and_leaves_the_student_untouched(
    teacher_client, student_client, class_id, attempt
) -> None:
    """Both halves in one test. Without the inequality the equality proves nothing."""
    student_before = student_client.get("/api/student/overview").json()
    average_before = teacher_client.get(f"/api/classes/{class_id}").json()["average"]

    assert teacher_client.post(
        f"/api/classes/{class_id}/papers/{attempt.id}/unshare"
    ).status_code == 204

    assert student_client.get("/api/student/overview").json() == student_before
    assert teacher_client.get(f"/api/classes/{class_id}").json()["average"] != average_before


def test_the_students_own_result_screen_is_identical(
    teacher_client, student_client, class_id, attempt
) -> None:
    before = student_client.get(f"/api/student/attempts/{attempt.id}/questions").json()
    teacher_client.post(f"/api/classes/{class_id}/papers/{attempt.id}/unshare")
    assert student_client.get(f"/api/student/attempts/{attempt.id}/questions").json() == before


def test_reshare_restores_the_average(teacher_client, class_id, attempt) -> None:
    before = teacher_client.get(f"/api/classes/{class_id}").json()["average"]
    teacher_client.post(f"/api/classes/{class_id}/papers/{attempt.id}/unshare")
    teacher_client.delete(f"/api/classes/{class_id}/papers/{attempt.id}/unshare")
    assert teacher_client.get(f"/api/classes/{class_id}").json()["average"] == before


def test_a_teacher_of_another_class_cannot_unshare(other_teacher_client, class_id, attempt) -> None:
    assert other_teacher_client.post(
        f"/api/classes/{class_id}/papers/{attempt.id}/unshare"
    ).status_code == 404


def test_a_student_cannot_unshare(student_client, class_id, attempt) -> None:
    assert student_client.post(
        f"/api/classes/{class_id}/papers/{attempt.id}/unshare"
    ).status_code == 403


def test_unsharing_twice_is_idempotent(teacher_client, class_id, attempt) -> None:
    teacher_client.post(f"/api/classes/{class_id}/papers/{attempt.id}/unshare")
    assert teacher_client.post(
        f"/api/classes/{class_id}/papers/{attempt.id}/unshare"
    ).status_code == 204


def test_unshare_removes_the_item_from_that_classs_queue(
    teacher_client, class_id, attempt, open_item
) -> None:
    """R3: the queue is class-scoped, so an unshared paper leaves it."""
    before = {i["id"] for i in teacher_client.get("/api/review/queue").json()["items"]}
    assert str(open_item.id) in before                      # present first

    teacher_client.post(f"/api/classes/{class_id}/papers/{attempt.id}/unshare")

    after = {i["id"] for i in teacher_client.get("/api/review/queue").json()["items"]}
    assert str(open_item.id) not in after


def test_unshare_does_not_mutate_the_items_status(
    teacher_client, sessionmaker_, class_id, attempt, open_item
) -> None:
    """It is filtered out, not withdrawn.

    `withdrawn` means a student deleted the subject, and it is excluded from
    D8's lifting set (R4a). Setting it here would both lie about what happened
    and entangle a teacher's reversible toggle with the integrity hold.
    """
    teacher_client.post(f"/api/classes/{class_id}/papers/{attempt.id}/unshare")
    with sessionmaker_() as session:
        assert session.get(ReviewQueueItem, open_item.id).status is ReviewStatus.open


def test_resharing_returns_the_item_to_the_queue_unchanged(
    teacher_client, class_id, attempt, open_item
) -> None:
    teacher_client.post(f"/api/classes/{class_id}/papers/{attempt.id}/unshare")
    teacher_client.delete(f"/api/classes/{class_id}/papers/{attempt.id}/unshare")
    items = teacher_client.get("/api/review/queue").json()["items"]
    assert str(open_item.id) in {i["id"] for i in items}


def test_another_classs_queue_still_shows_the_item(
    teacher_client, other_class_teacher_client, class_id, attempt, open_item
) -> None:
    """Exclusion is per class, so a second class teaching this student is unaffected."""
    teacher_client.post(f"/api/classes/{class_id}/papers/{attempt.id}/unshare")
    items = other_class_teacher_client.get("/api/review/queue").json()["items"]
    assert str(open_item.id) in {i["id"] for i in items}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_class_unshare.py --no-cov -q`
Expected: FAIL — 404 on the unshare route.

- [ ] **Step 3: Implement**

The repository is an upsert and a delete on `class_paper_exclusions`
(`ON CONFLICT DO NOTHING` for idempotency). Authorisation reuses `classes.py`'s
existing class-visibility check — do not write a second one.

**The queue change (R3) is a read filter, not a write.** In
`review_repo.list_queue`'s class-scoped branch, exclude rows whose
`attempt_id` appears in `class_paper_exclusions` for the class being listed:

```python
# R3: an unshared paper leaves that class's queue the same way it leaves that
# class's analytics — by exclusion at read time. The item itself is never
# mutated, so resharing restores it with its original created_at, and
# `withdrawn` keeps meaning only "the student deleted the paper".
.where(
    ~select(ClassPaperExclusion.attempt_id)
    .where(
        ClassPaperExclusion.class_id.in_(visible_class_ids),
        ClassPaperExclusion.attempt_id == ReviewQueueItem.attempt_id,
    )
    .exists()
)
```

Set `excluded_by` on every insert. Per design §5 it is the only trace that a
teacher removed a flagged paper from their own queue.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_class_unshare.py --no-cov -q`
Expected: PASS, 7 passed.

- [ ] **Step 5: Commit**

```bash
pre-commit run --all-files
git add lemely/db/class_exclusion_repo.py lemely/web/routers/classes.py tests/test_class_unshare.py
git commit -S -m "feat(web): a teacher unshares a paper from one class's view and analytics"
```

---

### Task 14: The student surfaces

> **Review amendments (2026-09-24) — these OVERRIDE any conflicting text below in this task.** Source: pre-execution plan review (`.superpowers/sdd-deletion/plan-review.md`) and owner rulings R7–R10.
>
> - **Hook location (Minor 4):** `web/src/lib/hooks/usePaperDeletionApi.ts` (convention: `useSelfReviewApi.ts`), not `portals/student/hooks/`. Find the student route table by grepping for an existing student screen's route (e.g. `PaperResult`).
> - **409 body is flat** (`{detail, deletableFrom}`) per the Task 8 amendment; 410 means past the window.
> - **Recently-deleted rows are per upload (R7).**
> - Reuse the student leak regex from the plan; keep it consistent with `tests/_integrity_leak.py`'s student detector.


**Files:**
- Modify: `web/src/lib/studentTypes.ts` (wire types)
- Create: `web/src/portals/student/hooks/usePaperDeletion.ts`
- Create: `web/src/portals/student/screens/RecentlyDeleted.tsx`
- Modify: `web/src/portals/student/screens/PaperResult.tsx` (the delete control)
- Modify: the student route table
- Test: `web/tests/unit/paperDeletion.test.ts`, `web/tests/unit/recentlyDeletedWiring.test.ts`

**Interfaces:**
- Consumes: Task 8's three routes.
- Produces: `useDeletePaper()`, `useRestorePaper()`, `useDeletedPapers()`, and the `RecentlyDeleted` screen.

**REQUIRED SUB-SKILL:** this is frontend work, so invoke the design skills
before writing any component — `hallmark` for the pre-emit critique stamp, and
`minimalist-ui`/`ui-ux-pro-max` per `BUILD/REDESIGN-MISSION.md` §3. The file
carries a `/* Hallmark · pre-emit critique: … */` stamp on line 1 and
`web/tests/unit/hallmarkStamp.test.ts` enforces every axis at ≥3. Do not
transcribe the code blocks below as final UI — they fix behaviour, not design.

Behaviour that is **not** negotiable, because it is where this ships broken:

- The delete control is on the result screen, never in the list, and it never
  renders a disabled or greyed state for a blocked paper (design §8 — no
  pre-signalling). The refusal is discovered on the POST and shown as copy.
- Optimistic update removes **only the deleted row**. It must not be trusted
  for neighbouring links, because `/student/result/{paper_id}` is positional
  (design §2.1). On success, `invalidateQueries` for the overview and subject
  keys, and navigate only after the refetch settles.
- The countdown shows whole days remaining, and "0 days" reads as gone.

- [ ] **Step 1: Write the failing tests**

```typescript
describe("deleteCountdown", () => {
  it("floors to whole days", () => {
    expect(deleteCountdown(iso("2026-10-21T12:00:00Z"), iso("2026-09-22T00:00:00Z"))).toBe(29)
  })

  it("reads a past deadline as gone, never as negative", () => {
    expect(deleteCountdown(iso("2026-09-01T00:00:00Z"), iso("2026-09-22T00:00:00Z"))).toBe(0)
  })
})

describe("deletionRefusal", () => {
  it("renders the hold with its date and no reason", () => {
    const copy = deletionRefusal({ detail: "This paper can't be deleted yet.",
                                   deletableFrom: "2026-10-21T00:00:00Z" })
    expect(copy).toBe("This paper can't be deleted yet. You'll be able to delete it from 21 October.")
    expect(copy).not.toMatch(/review|flag|plagiar|integrity|score/i)
  })

  it("the forbidden-word check would catch a leak", () => {
    expect("flagged for plagiarism").toMatch(/review|flag|plagiar|integrity|score/i)
  })
})
```

And a source-text gate, since vitest here is node-only with no jsdom:

```typescript
it("invalidates the overview after a delete rather than trusting the optimistic list", () => {
  const body = functionBody(source, "useDeletePaper")
  expect(body).toContain("invalidateQueries")
  expect(body).toMatch(/overview/)
})

it("never renders a disabled delete control", () => {
  expect(resultSource).not.toMatch(/disabled=\{[^}]*deletabl/i)
})
```

Anchor gates on the enclosing function body, never a whole-file `toContain` —
a whole-file assertion passes on a comment.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd web && npx vitest run tests/unit/paperDeletion.test.ts`
Expected: FAIL — the module does not exist.

- [ ] **Step 3: Implement the hooks, the screen and the control**

Pure helpers (`deleteCountdown`, `deletionRefusal`) live in
`web/src/lib/paperDeletion.ts` so they are unit-testable without a renderer,
matching how `selfReview.ts` was split out of its panel.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd web && npx vitest run tests/unit/paperDeletion.test.ts tests/unit/recentlyDeletedWiring.test.ts tests/unit/hallmarkStamp.test.ts`
Expected: PASS.

- [ ] **Step 5: Capture the screens**

Desktop 1280x900 and mobile 375x812, all states: result with the control,
refusal copy, recently-deleted with a countdown, empty recently-deleted.
Save under `reports/phase-8/screens/paper-deletion/`. §9 gate 5 is not met by
a passing unit suite — a node-only suite has never evaluated a render.

- [ ] **Step 6: Commit**

```bash
pre-commit run --all-files
git add web/src web/tests reports/phase-8
git commit -S -m "feat(web): delete a paper from the result screen, restore from recently deleted"
```

---

### Task 15: The disclosure page

> **Review amendments (2026-09-24) — these OVERRIDE any conflicting text below in this task.** Source: pre-execution plan review (`.superpowers/sdd-deletion/plan-review.md`) and owner rulings R7–R10.
>
> - **Structure (I10):** `dataHandlingSections` is an array; the "no way to delete" copy lives in the separate `notYetBuilt` export. Replace `notYetBuilt` with a concrete `deletion` export and test that export (and the absence of the old strings across **all** exports), so Step 2 genuinely fails before the change.
> - `web/tests/unit/dataHandling.test.ts` already exists and imports `notYetBuilt` — rewrite those parts; Task 8 already inverted the route guard.
> - Say that deletion covers every marking run of the scan (R7).


**Files:**
- Modify: `web/src/portals/marketing/dataHandling.ts`
- Modify: `lemely/db/models/attempts.py` (`Upload` docstring)
- Test: `web/tests/unit/dataHandling.test.ts`

**Interfaces:**
- Consumes: the shipped behaviour of Tasks 5–10.
- Produces: truthful published copy.

Ships in this PR. The page currently states the opposite of what will be true.

- [ ] **Step 1: Write the failing test**

```typescript
it("no longer claims that nothing can be deleted", () => {
  const serialised = JSON.stringify(dataHandlingSections)
  expect(serialised).not.toContain("There is no way to delete any of this")
  expect(serialised).not.toContain("no retention machinery")
})

it("states the window, what goes, and what stays", () => {
  const serialised = JSON.stringify(dataHandlingSections)
  expect(serialised).toContain("30 days")
  expect(serialised).toMatch(/mark scheme/i)   // kept (D2)
  expect(serialised).toMatch(/XP|streak/)      // kept (D7)
})

it("describes the hold without naming a reason", () => {
  const hold = dataHandlingSections.deletion.hold
  expect(hold).toMatch(/can't be deleted for up to 30 days/)
  expect(hold).not.toMatch(/plagiar|integrity|cheat|flag/i)
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run tests/unit/dataHandling.test.ts`
Expected: FAIL — the old `notYetBuilt` strings are still present.

- [ ] **Step 3: Rewrite the copy**

Replace the `notYetBuilt` panel with a deletion section covering: what deletion
removes (the scan and its sibling scheme scan, the upload row, the marks,
per-question points and history, the weaknesses); what it keeps (mark-scheme
reference data, XP and streak history, and the teacher's notification that a
review item was withdrawn — a surviving record that a paper existed); the
30-day window and that the file stays in Google Cloud Storage during it; and
the hold, worded without a reason. Also correct the module docstring's "no
retention machinery" paragraph and the `Upload` model docstring.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npx vitest run tests/unit/dataHandling.test.ts`
Expected: PASS, 3 passed.

- [ ] **Step 5: Flag the copy for post-merge review (R5)**

Not a gate — the owner ruled review happens after merge. Add the rewritten
copy to the PR body under a heading the reviewer cannot miss, and say plainly
that it publishes on merge without prior sign-off. The tests in Step 1 are the
real safeguard: a version that omits the window, or that names the hold's
reason, fails CI rather than merely reading oddly.

- [ ] **Step 6: Commit**

```bash
pre-commit run --all-files
git add web/src/portals/marketing/dataHandling.ts lemely/db/models/attempts.py web/tests
git commit -S -m "docs(web): the data-handling page describes deletion truthfully"
```

---

### Task 16: Teacher-console paper deletion (R2), backend

> **Review amendments (2026-09-24) — these OVERRIDE any conflicting text below in this task.** Source: pre-execution plan review (`.superpowers/sdd-deletion/plan-review.md`) and owner rulings R7–R10.
>
> - **No migration work (I4):** `teacher_papers.deleted_at` exists from Task 2 and `TeacherPaper` is already in the criterion from Task 3. Skip Step 3's migration and entity-tuple edits.
> - **Routes belong to Task 17:** move `test_the_console_list_hides_a_deleted_paper` there.
> - **Teacher row type:** `DeletedTeacherPaper(paper_id, label, deleted_at, restore_deadline)` — do not reuse the attempt-shaped `DeletedPaper`.
> - **Replace the tautology** with: a console paper deleted `RETENTION_DAYS` + 30 minutes ago is untouched; one deleted `RETENTION_DAYS` + 2 hours ago is purged.
> - Purge deletes both `storage_path` and `scheme_storage_path` (`lemely/db/models/teacher_papers.py` ~:41) when set; assert both.
> - Implement `TeacherPaperDeletionService` (delete/restore/list_deleted, withdraw/reopen via `teacher_paper_id`, owner = `uploaded_by`, **no integrity hold**) and `purge_expired_teacher_papers`, registered on the Sweeper beside Task 10's job. Follow Tasks 5–7 and 10's patterns, including the `INCLUDE_DELETED` constant.


**Files:**
- Modify: `lemely/db/migrations/versions/0039_paper_soft_delete.py` (add `teacher_papers.deleted_at`)
- Modify: `lemely/db/models/teacher_papers.py`
- Modify: `lemely/db/session.py` (add `TeacherPaper` to the criterion)
- Modify: `lemely/db/deletion_repo.py` (`TeacherPaperDeletionService`)
- Modify: `lemely/web/purge.py`
- Test: `tests/test_teacher_paper_deletion.py`

**Interfaces:**
- Consumes: Tasks 1, 2, 3, 10.
- Produces: `TeacherPaperDeletionService` with `delete(user_id, paper_id)`, `restore(user_id, paper_id)`, `list_deleted(user_id)`; `purge_expired_teacher_papers(...)`.

R2 ruled this in scope, mirroring the student flow. It is **not** the same code
twice — four differences are load-bearing:

- A console paper has **no `Attempt` and no `question_results`**; its marks live
  in `teacher_papers.report_json`. Nothing cascades. Purge deletes one row and
  its object.
- Its review-queue rows hang off `teacher_paper_id`, not `attempt_id`, so §6's
  withdraw-and-reopen applies through a different foreign key.
- **There is no integrity hold.** D8 exists to stop a student destroying
  evidence about themselves; a console paper has no attributed student
  (`teacher_papers.student_id` is always NULL). Applying the hold would block a
  teacher over a flag raised against nobody.
- The owner is `uploaded_by`, not `user_id`.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_teacher_deletes_their_own_console_paper(service, console_paper) -> None:
    service.delete(TEACHER, str(console_paper.id))
    assert service.list_deleted(TEACHER)[0].paper_id == console_paper.id


def test_another_teacher_cannot_delete_it(service, console_paper) -> None:
    with pytest.raises(PaperNotFoundError):
        service.delete(OTHER_TEACHER, str(console_paper.id))


def test_an_integrity_flag_does_not_block_a_console_paper(service, flagged_console_paper) -> None:
    """No attributed student, so D8's evidence argument does not apply."""
    service.delete(TEACHER, str(flagged_console_paper.id))  # does not raise


def test_deletion_withdraws_its_queue_items_through_teacher_paper_id(
    service, sessionmaker_, console_paper, console_item
) -> None:
    result = service.delete(TEACHER, str(console_paper.id))
    with sessionmaker_() as session:
        item = session.get(ReviewQueueItem, console_item.id)
    assert item.status is ReviewStatus.withdrawn
    assert item.withdrawn_at == result.deleted_at


def test_restore_reopens_them(service, sessionmaker_, console_paper, console_item) -> None:
    service.delete(TEACHER, str(console_paper.id))
    service.restore(TEACHER, str(console_paper.id))
    with sessionmaker_() as session:
        assert session.get(ReviewQueueItem, console_item.id).status is ReviewStatus.open


def test_the_console_list_hides_a_deleted_paper(teacher_client, console_paper) -> None:
    before = teacher_client.get("/api/teacher/papers").json()["papers"]
    assert str(console_paper.id) in {p["id"] for p in before}
    teacher_client.delete(f"/api/teacher/papers/{console_paper.id}")
    after = teacher_client.get("/api/teacher/papers").json()["papers"]
    assert str(console_paper.id) not in {p["id"] for p in after}


def test_purge_removes_the_row_and_its_object(
    sessionmaker_, fake_storage, expired_console_paper
) -> None:
    assert purge_expired_teacher_papers(sessionmaker_, fake_storage, BUCKET) == 1
    assert fake_storage.deleted == [(BUCKET, expired_console_paper.storage_path)]


def test_purge_uses_the_same_retention_as_the_student_flow(sessionmaker_, fake_storage) -> None:
    """One number across the product, as the decisions doc asked."""
    assert purge_cutoff(NOW) == purge_cutoff(NOW)  # same function, not a second constant
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_teacher_paper_deletion.py --no-cov -q`
Expected: FAIL — no `TeacherPaperDeletionService`.

- [ ] **Step 3: Implement**

Add the column to migration 0039 (it has not shipped yet, so extend it rather
than writing 0040):

```python
op.add_column(
    "teacher_papers", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True)
)
```

and extend the listener's entity tuple in `session.py`:

```python
for entity in (Attempt, Upload, TeacherPaper):
```

Update Task 3's `test_listener_is_registered_at_class_level` module with a
`TeacherPaper` presence-then-absence pair, so the third entity is covered by
the same three-assertion shape as the first two.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_teacher_paper_deletion.py tests/test_soft_delete_criteria.py --no-cov -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
pre-commit run --all-files
git add lemely/db lemely/web/purge.py tests/test_teacher_paper_deletion.py
git commit -S -m "feat(db): soft delete, restore and purge for teacher console papers"
```

---

### Task 17: Teacher-console deletion, the console surface

> **Review amendments (2026-09-24) — these OVERRIDE any conflicting text below in this task.** Source: pre-execution plan review (`.superpowers/sdd-deletion/plan-review.md`) and owner rulings R7–R10.
>
> - **Real paths (I3):** teacher router prefix is `/api`; console routes are `/api/papers…`. New routes: `DELETE /api/papers/{paper_id}`, `POST /api/papers/{paper_id}/restore`, `GET /api/papers/deleted` — declare `/papers/deleted` **above** `get_paper` (`lemely/web/routers/teacher.py` ~:851) with a comment, and test that `GET /api/papers/deleted` returns the list DTO.
> - Include `test_the_console_list_hides_a_deleted_paper` (moved from Task 16) against `GET /api/papers`.
> - **Settings toggle (R10):** add the `review_withdrawn` toggle to `web/src/portals/settings/NotificationSettings.tsx`, on by default, under the design skills.


**Files:**
- Modify: `lemely/web/routers/teacher.py` (delete/restore/deleted routes)
- Modify: the teacher console screens under `web/src/portals/teacher/`
- Test: `tests/test_teacher_paper_routes.py`, `web/tests/unit/teacherPaperDeletion.test.ts`

**Interfaces:**
- Consumes: Task 16.
- Produces: `DELETE /api/teacher/papers/{paper_id}`, `POST /api/teacher/papers/{paper_id}/restore`, `GET /api/teacher/papers/deleted`.

**REQUIRED SUB-SKILL:** frontend work — invoke `hallmark` and the design skills
before writing the component, and carry the pre-emit critique stamp. The
recently-deleted console surface is a real screen, not a modal afterthought:
R2 chose the full mirror of the student flow, and D4's objection to a hidden
safety net applies here too.

Routes mirror Task 8's shapes and error mapping. There is no 409 hold here, so
the only refusals are 404 (not yours / not found, one fixed body) and 410
(past the restore window).

- [ ] **Step 1: Write the failing tests** — the route-level authz matrix
  (owner deletes; another teacher 404s; a student 403s), plus a source-text
  gate that the console list invalidates after a delete rather than trusting
  its optimistic removal.
- [ ] **Step 2: Run to verify they fail** — `pytest tests/test_teacher_paper_routes.py --no-cov -q`
- [ ] **Step 3: Implement the routes and the screen.**
- [ ] **Step 4: Run to verify they pass.**
- [ ] **Step 5: Capture the screens** — desktop and mobile, list / deleted /
  empty, into `reports/phase-8/screens/teacher-paper-deletion/`.
- [ ] **Step 6: Commit**

```bash
pre-commit run --all-files
git add lemely/web/routers/teacher.py web/src web/tests tests reports/phase-8
git commit -S -m "feat(web): delete and restore a paper from the teacher console"
```

---

### Task 18: End-to-end proof

> **Review amendments (2026-09-24) — these OVERRIDE any conflicting text below in this task.** Source: pre-execution plan review (`.superpowers/sdd-deletion/plan-review.md`) and owner rulings R7–R10.
>
> - Scenario 6's average comes from `GET /api/teacher/classes` and the queue from `/api/teacher/review`; seed the unshared paper as the student's latest.
> - Add a scenario: re-mark one scan twice, delete one result, both disappear (R7).
> - PR body must note R9 (class pages only) and that a correction already in flight when a paper is deleted can still write rows (known, accepted).


**Files:**
- Modify: `scripts/seed_e2e.py`
- Create: `web/e2e/paper-deletion.spec.ts`

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Write the spec**

Eight scenarios against a real backend and browser:

1. Delete a paper from the result screen; the overview no longer lists it and
   the grade moves.
2. **The positional-URL trap:** with three papers, delete the second, then open
   what the list now shows as the second and assert the title is the paper that
   was tapped. This is design §2.1's failure, and it is the reason this spec
   exists rather than being deferred.
3. Restore from recently deleted; the paper and the grade come back.
4. Attempt to delete an integrity-flagged paper; the refusal shows a date and
   the page contains no integrity language.
5. **R4 end to end:** the teacher resolves the integrity item, and the same
   paper then deletes successfully — the block lifted without any screen
   saying why.
6. A teacher unshares a paper; the class average moves, the item leaves that
   teacher's review queue (R3), and the student's own overview is
   byte-identical.
7. Reshare; the average and the queue item both come back.
8. **R2:** a teacher deletes their own console paper, sees it in the console's
   recently-deleted area, and restores it.

- [ ] **Step 2: Extend the seed**

Add a student with three corrected papers, one of them integrity-flagged; a
class with a teacher enrolled; an open integrity review item the teacher can
resolve in scenario 5; and one teacher-console paper for scenario 8 — following
`seed_e2e.py`'s existing shape.

- [ ] **Step 3: Run**

```bash
cd web && npx playwright test e2e/paper-deletion.spec.ts
```
Expected: 8 passed.

- [ ] **Step 4: Commit**

```bash
pre-commit run --all-files
git add scripts/seed_e2e.py web/e2e/paper-deletion.spec.ts
git commit -S -m "test(e2e): prove deletion, restore, the hold and unshare in a real browser"
```

---

## Self-review

**Spec coverage.** D1 → Tasks 5, 10. D2 → Task 10 (scheme rows untouched; the
student's own scheme scan goes, recorded as a clarification). D3 → Tasks 2, 3,
4. D4 → Tasks 7, 14. D5 → Task 8 (student) **and Tasks 16–17 (teacher console,
per R2)**. D6 amended → ratified as R1, then satisfied for free by the
live-read architecture. D7 → no task needed; verified in design §9. D8 →
Tasks 5, 8, 14, **with R4's lifting predicate and R4a's exclusion of
`withdrawn` in Task 5**. D9 → Tasks 12, 13, **including R3's queue filter**.
D10 → Tasks 5, 6, 9. Open questions → design §7 (purge/GCS), §9 (parents,
quizzes), §10 (the page, Task 15, non-blocking per R5).

**Ruling coverage.** R1 → the architecture, no task. R2 → Tasks 16, 17.
R3 → Task 13. R4/R4a → Task 5 (`_TEACHER_CLOSED`, and four tests including the
delete-restore-delete cycle). R4b → recorded in design §8, no code. R5 →
Task 15 Step 5. R6 → one branch, flagged in the Global Constraints.

**Gaps deliberately left:** notification batching for a bulk delete (design §4,
follow-up); per-question class analytics for unshare, which has no surface
today (design §5).

**Known unknowns, carried openly:**
1. Whether `with_loader_criteria` reaches a column-only select. Task 3 Step 4
   names the fallback and the test that pins whichever answer is true.
2. Whether `review_queue.question_result_id`'s missing `ondelete` survives the
   attempt cascade. Task 10 Step 4 names the fixture that decides it and the
   one-line fix if it does not.

**Where this plan is most likely to go wrong, given the rulings.** R4a is a
tuple membership — `_TEACHER_CLOSED` gaining `withdrawn` in some later
"tidy-up" silently hands students the ability to lift their own integrity hold,
and nothing but that one test would notice. R3's queue filter must stay a read
filter; the moment someone "simplifies" it into a status write, unshare and
deletion become indistinguishable in the audit trail. R6 means both of those
land inside one large diff.
