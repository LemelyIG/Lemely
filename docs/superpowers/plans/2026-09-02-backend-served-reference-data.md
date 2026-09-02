# Backend-Served Reference Data Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move every piece of curriculum and grade reference data out of hardcoded frontend constants and bundled JSON files into Postgres, served over one authenticated endpoint.

**Architecture:** Three new catalogue tables (`syllabus_papers`, `subject_topics`) plus two threshold tables (`component_thresholds`, `option_thresholds`) become the source of truth. A migration backfills the catalogue from the two JSON files that are then deleted, and the `lemely/io/` loaders that read those files are rewired to read Postgres behind a process cache. `GET /api/reference` serves the catalogue and every enumeration the UI needs; the frontend deletes nine import sites and reads one cached react-query hook.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy 2.0, Alembic, Pydantic v2, pytest. React 19, TypeScript, TanStack Query, Vitest (unit), Playwright (E2E).

**Spec:** `docs/superpowers/specs/2026-09-02-backend-served-reference-data-design.md`

## Global Constraints

- **The frontend must not contain hardcoded data.** Any table the backend owns is fetched, never declared in `web/src`.
- **Nothing lands on local disk.** Reference data lives in Postgres. No new file reads or writes on the request path.
- **Provenance is NOT NULL.** Every `syllabus_papers`, `component_thresholds` and `option_thresholds` row names the document it came from. A row that cannot name its source is rejected by the schema.
- **No silent fallbacks.** No hook passes `fallback` to `request()`; a backend failure surfaces as a query error. No bundled default subject list.
- **Signed commits:** always `git commit -S` (CLAUDE.md).
- **Conventional commits with scopes:** `feat(web):`, `feat(db):`, `fix(io):`, `test(web):`, `refactor(core):`.
- **Run `pre-commit run --all-files` and fix every failure before any commit.** Stage new files first — `--all-files` skips untracked files.
- **Activate the venv first:** `source .venv/bin/activate`. `.venv/bin/pre-commit` fake-fails mypy and import-linter.
- **Branch from fresh `develop`**, never from `main`.
- **Playwright is the E2E harness only.** No browser in the runtime or ingest path.
- **Topic strings are `"<code> <name>"`** (e.g. `"1 Motion, forces and energy"`) — the vocabulary `ConfidenceRating.topic` and the weakness engine already use. The frontend never composes it.
- **Grade vocabularies:** awarded grades derive per-paper from that component's threshold record plus `U`. Target grades derive per `(subject, tier)` from `option_thresholds`. A* exists only at option level.

---

## File Structure

**Backend — new**

| File | Responsibility |
|---|---|
| `lemely/db/models/catalogue.py` | `SyllabusPaper`, `SubjectTopic` ORM models |
| `lemely/db/models/thresholds.py` | `ComponentThreshold`, `OptionThreshold` ORM models |
| `lemely/db/catalogue_repo.py` | Read the catalogue; the only module that queries the catalogue tables |
| `lemely/db/threshold_repo.py` | Read thresholds; derive target vocabularies from option rows |
| `lemely/web/routers/reference.py` | `GET /api/reference` |
| `lemely/web/schemas_reference.py` | Reference DTOs |
| `lemely/db/migrations/versions/0024_reference_catalogue.py` | Catalogue schema + JSON backfill |
| `lemely/db/migrations/versions/0025_thresholds.py` | Threshold schema |
| `lemely/io/ciegt.py` | Fetch + devalue-decode ciegt payloads |
| `lemely/io/threshold_pdf.py` | Parse component and option tables from a CAIE PDF |
| `scripts/ingest_thresholds.py` | Orchestrate ciegt + PDF, verify, upsert |

**Backend — modified**

| File | Change |
|---|---|
| `lemely/db/models/enums.py` | Add `PaperTier` |
| `lemely/db/models/academic.py` | `Subject` gains `active`, `qualification_level`, `syllabus_version` |
| `lemely/io/paper_timing.py` | Read Postgres, not JSON |
| `lemely/io/syllabus_topics.py` | Read Postgres, not JSON |
| `lemely/io/grade_boundaries.py` | `GradeBoundaryStore` reads `component_thresholds` |
| `lemely/db/seed.py` | `DEMO_SUBJECTS` → `CATALOGUE_SUBJECTS`; upsert catalogue |
| `lemely/web/app.py` | Mount `reference.router` |

**Backend — deleted**

`lemely/data/paper_timing.json`, `lemely/data/syllabus_topics.json`, `lemely/data/grade_boundaries.json`, `lemely/data/grade_boundaries_provenance.json`, `scripts/ingest_grade_boundaries.py` (superseded by `scripts/ingest_thresholds.py`, which keeps its PDF parser).

**Frontend — new**

| File | Responsibility |
|---|---|
| `web/src/lib/referenceTypes.ts` | DTO mirrors |
| `web/src/lib/hooks/useReferenceApi.ts` | `useReference`, `useSubjectName` |
| `web/src/lib/grades.ts` | `gradeRank` |
| `web/tests/unit/reference.test.ts` | Hook-free logic tests |
| `web/tests/unit/noHardcodedReferenceData.test.ts` | The gate |

**Frontend — modified**

`onboardingData.ts`, `SubjectsStep.tsx`, `Onboarding.tsx`, `QuestionnaireStep.tsx`, `qualificationLevels.ts`, `grade-badge.tsx`, `types.ts`, and the seven name-lookup screens (`PracticeGenerator`, `PracticeResult`, `FlashcardDecks`, `FlashcardReview`, `PlacementInvite`, `PlacementResult`, `StudyPlanWeek`, `StudyPlanSession`).

---

# Stage 1 — The catalogue in Postgres, served

### Task 1: Catalogue ORM models and the `PaperTier` enum

**Files:**
- Create: `lemely/db/models/catalogue.py`
- Modify: `lemely/db/models/enums.py` (add `PaperTier`), `lemely/db/models/academic.py` (`Subject` columns), `lemely/db/models/__init__.py` (exports)
- Test: `tests/test_catalogue_models.py`

**Interfaces:**
- Consumes: `Base` from `lemely.db.base`; `TimestampMixin`, `ExamBoard`, `QualificationLevel` from `lemely.db.models.enums`.
- Produces: `PaperTier` (`core`/`extended`), `SyllabusPaper`, `SubjectTopic`; `Subject.active`, `Subject.qualification_level`, `Subject.syllabus_version`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_catalogue_models.py
"""Model-shape tests for the catalogue tables (no database required)."""

from __future__ import annotations

from lemely.db.models.academic import Subject
from lemely.db.models.catalogue import SubjectTopic, SyllabusPaper
from lemely.db.models.enums import PaperTier


def test_paper_tier_has_exactly_core_and_extended() -> None:
    assert {t.value for t in PaperTier} == {"core", "extended"}


def test_syllabus_paper_provenance_columns_are_not_nullable() -> None:
    cols = SyllabusPaper.__table__.columns
    for name in ("source_document", "source_url", "syllabus_version"):
        assert cols[name].nullable is False, f"{name} must be NOT NULL"


def test_syllabus_paper_is_unique_per_board_subject_and_number() -> None:
    uniques = {
        tuple(sorted(c.name for c in con.columns))
        for con in SyllabusPaper.__table__.constraints
        if con.__class__.__name__ == "UniqueConstraint"
    }
    assert ("board", "paper_number", "subject_code") in uniques


def test_subject_topic_nests_via_self_referential_parent() -> None:
    parent = SubjectTopic.__table__.columns["parent_id"]
    assert parent.nullable is True
    assert {fk.column.table.name for fk in parent.foreign_keys} == {"subject_topics"}


def test_subject_gains_active_and_qualification_level() -> None:
    cols = Subject.__table__.columns
    assert cols["active"].nullable is False
    assert "qualification_level" in cols
    # `SyllabusTaxonomy.source_url` is a required str, so the subject must be
    # able to supply one — see `lemely/core/topics.py`.
    assert "source_url" in cols
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `source .venv/bin/activate && pytest tests/test_catalogue_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lemely.db.models.catalogue'`

- [ ] **Step 3: Add the `PaperTier` enum**

In `lemely/db/models/enums.py`, after `QualificationLevel`:

```python
class PaperTier(enum.Enum):
    """Which tier of a tiered syllabus a paper belongs to.

    IGCSE splits some subjects into Core and Extended. The distinction is
    load-bearing rather than cosmetic: Cambridge publishes different grade
    thresholds for each, and a Core candidate cannot be awarded above C. A
    subject with no tiering (0606 Additional Mathematics) leaves the column
    NULL rather than inventing a tier for it.
    """

    core = "core"
    extended = "extended"
```

Add `"PaperTier"` to that module's `__all__`.

- [ ] **Step 4: Create the catalogue models**

```python
# lemely/db/models/catalogue.py
"""ORM models for the syllabus catalogue: paper structure and topic taxonomy.

These tables hold what ``lemely/data/paper_timing.json`` and
``lemely/data/syllabus_topics.json`` used to hold. They are separate from
:class:`~lemely.db.models.academic.Paper`, which means "an ingested past-paper
instance" keyed by session and variant — this is the *structure* a syllabus
defines, independent of which PDFs have been downloaded.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from lemely.db.base import Base
from lemely.db.models.enums import ExamBoard, PaperTier, TimestampMixin


class SyllabusPaper(TimestampMixin, Base):
    """One paper a syllabus defines, with the timing facts placement needs."""

    __tablename__ = "syllabus_papers"
    __table_args__ = (
        sa.UniqueConstraint(
            "board", "subject_code", "paper_number", name="uq_syllabus_papers_identity"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
    )
    board: Mapped[ExamBoard] = mapped_column(
        sa.Enum(ExamBoard, name="examboard"),
        nullable=False,
        server_default=sa.text("'caie'::examboard"),
    )
    subject_code: Mapped[str] = mapped_column(
        sa.String, sa.ForeignKey("subjects.code"), nullable=False
    )
    paper_number: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    name: Mapped[str] = mapped_column(sa.String, nullable=False)
    tier: Mapped[PaperTier | None] = mapped_column(
        sa.Enum(PaperTier, name="papertier"), nullable=True
    )
    duration_minutes: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    total_marks: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    practical: Mapped[bool] = mapped_column(sa.Boolean, nullable=False)
    # Provenance is NOT NULL for the reason `ExamDate.source` is: a row that
    # cannot name the document it was transcribed from is indistinguishable
    # from an invented one.
    source_document: Mapped[str] = mapped_column(sa.String, nullable=False)
    source_url: Mapped[str] = mapped_column(sa.String, nullable=False)
    syllabus_version: Mapped[str] = mapped_column(sa.String, nullable=False)


class SubjectTopic(TimestampMixin, Base):
    """One node of a syllabus topic tree.

    ``strong`` and ``keywords`` are Lemely's authored matching vocabulary for
    the deterministic classifier, **not** syllabus content — the retired
    ``syllabus_topics.json`` said so in its own header. They are stored because
    the classifier needs them and are excluded from every DTO.
    """

    __tablename__ = "subject_topics"
    __table_args__ = (
        sa.UniqueConstraint("board", "subject_code", "code", name="uq_subject_topics_identity"),
        sa.Index("ix_subject_topics_subject", "board", "subject_code"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
    )
    board: Mapped[ExamBoard] = mapped_column(
        sa.Enum(ExamBoard, name="examboard"),
        nullable=False,
        server_default=sa.text("'caie'::examboard"),
    )
    subject_code: Mapped[str] = mapped_column(
        sa.String, sa.ForeignKey("subjects.code"), nullable=False
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("subject_topics.id", ondelete="CASCADE"), nullable=True
    )
    code: Mapped[str] = mapped_column(sa.String, nullable=False)
    name: Mapped[str] = mapped_column(sa.String, nullable=False)
    strong: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default=sa.text("'[]'::jsonb"))
    keywords: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default=sa.text("'[]'::jsonb"))
```

In `lemely/db/models/academic.py`, add to `Subject` after `board`:

```python
    active: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.text("true")
    )
    qualification_level: Mapped[QualificationLevel | None] = mapped_column(
        sa.Enum(QualificationLevel, name="qualificationlevel"), nullable=True
    )
    syllabus_version: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    # The syllabus PDF the topic tree was transcribed from. Nullable because a
    # subject may exist before its taxonomy does; `get_taxonomy` returns None
    # for such a subject rather than building a `SyllabusTaxonomy` whose
    # required `source_url` would have to be faked.
    source_url: Mapped[str | None] = mapped_column(sa.String, nullable=True)
```

and extend its import to `from lemely.db.models.enums import ExamBoard, QualificationLevel, SessionMonth, TimestampMixin`.

Export `SubjectTopic` and `SyllabusPaper` from `lemely/db/models/__init__.py` alongside the existing model exports.

- [ ] **Step 5: Run the test to verify it passes**

Run: `pytest tests/test_catalogue_models.py -v`
Expected: 5 passed

- [ ] **Step 6: Commit**

```bash
source .venv/bin/activate && pre-commit run --all-files
git add lemely/db/models/catalogue.py lemely/db/models/enums.py lemely/db/models/academic.py lemely/db/models/__init__.py tests/test_catalogue_models.py
git commit -S -m "feat(db): add syllabus catalogue models and PaperTier enum"
```

---

### Task 2: Migration 0024 — catalogue schema and JSON backfill

**Files:**
- Create: `lemely/db/migrations/versions/0024_reference_catalogue.py`
- Test: `tests/test_migration_0024_backfill.py`

**Interfaces:**
- Consumes: Task 1's models.
- Produces: populated `syllabus_papers` and `subject_topics`; `subjects` rows carrying `qualification_level='igcse'`.

The backfill reads the JSON files at migration time. They are deleted in Task 3, *after* this migration is written — a migration that reads a file deleted in the same commit cannot be re-run on a fresh database, so the migration embeds the data it inserts rather than reading the files at runtime.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_migration_0024_backfill.py
"""The 0024 backfill must reproduce exactly what the retiring JSON held.

This is the one chance to prove nothing was lost in transcription: after this
migration the JSON files are deleted, so any divergence becomes permanent and
silent. The expectations below are transcribed from the files as they stood at
the time of the migration.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker

from lemely.db.models.catalogue import SubjectTopic, SyllabusPaper

EXPECTED_PAPERS = {
    "0625": [
        (1, "Multiple Choice (Core)", "core", False),
        (2, "Multiple Choice (Extended)", "extended", False),
        (3, "Theory (Core)", "core", False),
        (4, "Theory (Extended)", "extended", False),
        (5, "Practical Test", None, True),
        (6, "Alternative to Practical", None, True),
    ],
    "0580": [
        (1, "Non-calculator (Core)", "core", False),
        (2, "Non-calculator (Extended)", "extended", False),
        (3, "Calculator (Core)", "core", False),
        (4, "Calculator (Extended)", "extended", False),
    ],
    "0606": [
        (1, "Non-calculator", None, False),
        (2, "Calculator", None, False),
    ],
}

EXPECTED_TOP_TOPIC_COUNTS = {"0625": 6, "0580": 9, "0606": 14}

EXPECTED_FIRST_TOPICS = {
    "0625": ["1 Motion, forces and energy", "2 Thermal physics", "3 Waves"],
    "0580": ["1 Number", "2 Algebra and graphs", "3 Coordinate geometry"],
    "0606": ["1 Functions", "2 Quadratic functions", "3 Factors of polynomials"],
}


@pytest.mark.parametrize("code", sorted(EXPECTED_PAPERS))
def test_papers_match_the_retired_json(migrated_sessionmaker: sessionmaker[Session], code: str) -> None:
    with migrated_sessionmaker() as s:
        rows = s.scalars(
            sa.select(SyllabusPaper)
            .where(SyllabusPaper.subject_code == code)
            .order_by(SyllabusPaper.paper_number)
        ).all()
    actual = [(r.paper_number, r.name, r.tier.value if r.tier else None, r.practical) for r in rows]
    assert actual == EXPECTED_PAPERS[code]


@pytest.mark.parametrize("code", sorted(EXPECTED_TOP_TOPIC_COUNTS))
def test_top_level_topic_counts_match(migrated_sessionmaker: sessionmaker[Session], code: str) -> None:
    with migrated_sessionmaker() as s:
        n = s.scalar(
            sa.select(sa.func.count())
            .select_from(SubjectTopic)
            .where(SubjectTopic.subject_code == code, SubjectTopic.parent_id.is_(None))
        )
    assert n == EXPECTED_TOP_TOPIC_COUNTS[code]


@pytest.mark.parametrize("code", sorted(EXPECTED_FIRST_TOPICS))
def test_first_three_topics_match_the_onboarding_vocabulary(
    migrated_sessionmaker: sessionmaker[Session], code: str
) -> None:
    """The exact strings S-02's confidence step used to hardcode."""
    with migrated_sessionmaker() as s:
        rows = s.scalars(
            sa.select(SubjectTopic)
            .where(SubjectTopic.subject_code == code, SubjectTopic.parent_id.is_(None))
            .order_by(SubjectTopic.code)
        ).all()
    assert [f"{r.code} {r.name}" for r in rows][:3] == EXPECTED_FIRST_TOPICS[code]


def test_every_paper_names_its_source_document(migrated_sessionmaker: sessionmaker[Session]) -> None:
    with migrated_sessionmaker() as s:
        rows = s.scalars(sa.select(SyllabusPaper)).all()
    assert rows
    assert all(r.source_document and r.source_url and r.syllabus_version for r in rows)
```

Add the shared fixture to `tests/conftest.py` (it runs Alembic against a throwaway database, so migration behaviour is tested rather than `Base.metadata.create_all`):

```python
@pytest.fixture
def migrated_sessionmaker() -> Iterator[sessionmaker[Session]]:
    """A throwaway Postgres database with `alembic upgrade head` applied.

    Distinct from the `pg_sessionmaker` fixtures in the router tests, which use
    `Base.metadata.create_all` and therefore never execute a migration's data
    steps. Anything asserting what a migration *inserted* needs this one.
    """
    import uuid as _uuid

    import sqlalchemy as sa
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine
    from sqlalchemy.engine import make_url
    from sqlalchemy.exc import OperationalError
    from sqlalchemy.orm import Session, sessionmaker

    from lemely.runtime.config import DatabaseSettings

    base_url = DatabaseSettings().url
    server_url = make_url(base_url).set(database="postgres")
    try:
        probe = create_engine(server_url)
        with probe.connect():
            pass
        probe.dispose()
    except OperationalError:
        pytest.skip("local Postgres not reachable")

    admin = create_engine(server_url, isolation_level="AUTOCOMMIT")
    dbname = f"lemely_mig_{_uuid.uuid4().hex[:12]}"
    with admin.connect() as conn:
        conn.execute(sa.text(f'CREATE DATABASE "{dbname}"'))
    url = make_url(base_url).set(database=dbname)

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url.render_as_string(hide_password=False))
    command.upgrade(cfg, "head")

    engine = create_engine(url)
    try:
        yield sessionmaker(bind=engine, expire_on_commit=False, future=True)
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE)'))
        admin.dispose()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_migration_0024_backfill.py -v`
Expected: FAIL — the `syllabus_papers` relation does not exist.

- [ ] **Step 3: Write the migration**

Generate the row literals from the files being retired, so the migration embeds exactly what they held:

```bash
source .venv/bin/activate && python - <<'PY' > /tmp/rows.py
import json
pt = json.load(open("lemely/data/paper_timing.json"))
st = json.load(open("lemely/data/syllabus_topics.json"))

def tier(name):
    if "(Core)" in name: return "core"
    if "(Extended)" in name: return "extended"
    return None

print("PAPERS = [")
for p in pt["papers"]:
    print(f'    dict(board={p["board"]!r}, subject_code={p["subject_code"]!r}, '
          f'paper_number={p["paper_number"]}, name={p["name"]!r}, tier={tier(p["name"])!r}, '
          f'duration_minutes={p["duration_minutes"]}, total_marks={p["total_marks"]}, '
          f'practical={bool(p["practical"])}, source_document={p["source"]["document"]!r}, '
          f'source_url={p["source"]["url"]!r}, syllabus_version={p["source"]["syllabus_version"]!r}),')
print("]")

print("SUBJECTS = [")
for s in st["subjects"]:
    print(f'    dict(code={s["subject_code"]!r}, name={s["subject_name"]!r}, '
          f'syllabus_version={s["syllabus_version"]!r}, source_url={s["source"]["url"]!r}),')
print("]")

def walk(nodes, parent=None, out=None):
    out = [] if out is None else out
    for n in nodes:
        out.append((n["code"], n["name"], parent, n.get("strong", []), n.get("keywords", [])))
        walk(n.get("subtopics", []), n["code"], out)
    return out

print("TOPICS = {")
for s in st["subjects"]:
    print(f'    {s["subject_code"]!r}: [')
    for code, name, parent, strong, kw in walk(s["topics"]):
        print(f'        ({code!r}, {name!r}, {parent!r}, {strong!r}, {kw!r}),')
    print("    ],")
print("}")
PY
```

Create `lemely/db/migrations/versions/0024_reference_catalogue.py` with the generated `PAPERS`, `SUBJECTS` and `TOPICS` literals pasted in, and this structure:

```python
"""reference catalogue: syllabus papers and subject topics

Revision ID: 0024_reference_catalogue
Revises: 0023_invites
Create Date: 2026-09-02 00:00:00.000000

Two additive tables plus three columns on ``subjects``, and the data that used
to live in ``lemely/data/paper_timing.json`` and
``lemely/data/syllabus_topics.json``. Those files are deleted in the same
change, which is why the rows are **embedded here as literals** rather than
read from disk at migration time: a migration that reads a file the repository
no longer contains cannot be replayed on a fresh database, and replayability is
the whole contract of a migration.

``papertier`` is a new enum. It is nullable on ``syllabus_papers`` because not
every syllabus is tiered — 0606 has no Core/Extended split, and inventing one
would be a claim the syllabus does not make.

``subjects.active`` exists because ``papers.subject_code`` is a foreign key to
``subjects.code``: ingesting a fourth subject's past papers would otherwise
enrol students in it through onboarding as a side effect.

Reversible: ``downgrade`` drops both tables, drops the three added columns, then
drops the ``papertier`` type explicitly — a table drop does not drop the type
backing an enum column, the trap ``0006`` and ``0022`` both document.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0024_reference_catalogue"
down_revision: str | Sequence[str] | None = "0023_invites"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# <paste PAPERS, SUBJECTS, TOPICS literals here>


def upgrade() -> None:
    op.add_column(
        "subjects", sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true"))
    )
    op.add_column(
        "subjects",
        sa.Column(
            "qualification_level",
            postgresql.ENUM(name="qualificationlevel", create_type=False),
            nullable=True,
        ),
    )
    op.add_column("subjects", sa.Column("syllabus_version", sa.String(), nullable=True))
    op.add_column("subjects", sa.Column("source_url", sa.String(), nullable=True))

    tier = postgresql.ENUM("core", "extended", name="papertier")
    tier.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "syllabus_papers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("board", postgresql.ENUM(name="examboard", create_type=False),
                  nullable=False, server_default=sa.text("'caie'::examboard")),
        sa.Column("subject_code", sa.String(), sa.ForeignKey("subjects.code"), nullable=False),
        sa.Column("paper_number", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("tier", tier, nullable=True),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("total_marks", sa.Integer(), nullable=False),
        sa.Column("practical", sa.Boolean(), nullable=False),
        sa.Column("source_document", sa.String(), nullable=False),
        sa.Column("source_url", sa.String(), nullable=False),
        sa.Column("syllabus_version", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("board", "subject_code", "paper_number", name="uq_syllabus_papers_identity"),
    )

    op.create_table(
        "subject_topics",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("board", postgresql.ENUM(name="examboard", create_type=False),
                  nullable=False, server_default=sa.text("'caie'::examboard")),
        sa.Column("subject_code", sa.String(), sa.ForeignKey("subjects.code"), nullable=False),
        sa.Column("parent_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("subject_topics.id", ondelete="CASCADE"), nullable=True),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("strong", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("keywords", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("board", "subject_code", "code", name="uq_subject_topics_identity"),
    )
    op.create_index("ix_subject_topics_subject", "subject_topics", ["board", "subject_code"])

    _backfill()


def _backfill() -> None:
    """Insert the catalogue. Idempotent: skips a subject that already has rows."""
    bind = op.get_bind()

    for subject in SUBJECTS:
        bind.execute(
            sa.text(
                "INSERT INTO subjects (code, name, board, active, qualification_level, "
                "syllabus_version, source_url) "
                "VALUES (:code, :name, 'caie', true, 'igcse', :version, :source_url) "
                "ON CONFLICT (code) DO UPDATE SET "
                "qualification_level = EXCLUDED.qualification_level, "
                "syllabus_version = EXCLUDED.syllabus_version, "
                "source_url = EXCLUDED.source_url"
            ),
            {
                "code": subject["code"],
                "name": subject["name"],
                "version": subject["syllabus_version"],
                "source_url": subject["source_url"],
            },
        )

    for paper in PAPERS:
        bind.execute(
            sa.text(
                "INSERT INTO syllabus_papers (board, subject_code, paper_number, name, tier, "
                "duration_minutes, total_marks, practical, source_document, source_url, syllabus_version) "
                "VALUES (:board, :subject_code, :paper_number, :name, "
                "CAST(:tier AS papertier), :duration_minutes, :total_marks, :practical, "
                ":source_document, :source_url, :syllabus_version) "
                "ON CONFLICT ON CONSTRAINT uq_syllabus_papers_identity DO NOTHING"
            ),
            paper,
        )

    import json as _json

    for subject_code, rows in TOPICS.items():
        ids: dict[str, str] = {}
        # Parents first: a child's `parent_id` must reference a row that exists,
        # and the source file lists every parent before its own subtopics.
        for code, name, parent_code, strong, keywords in rows:
            new_id = bind.execute(
                sa.text(
                    "INSERT INTO subject_topics (board, subject_code, parent_id, code, name, strong, keywords) "
                    "VALUES ('caie', :subject_code, CAST(:parent_id AS uuid), :code, :name, "
                    "CAST(:strong AS jsonb), CAST(:keywords AS jsonb)) "
                    "ON CONFLICT ON CONSTRAINT uq_subject_topics_identity DO NOTHING "
                    "RETURNING id"
                ),
                {
                    "subject_code": subject_code,
                    "parent_id": ids.get(parent_code) if parent_code else None,
                    "code": code,
                    "name": name,
                    "strong": _json.dumps(strong),
                    "keywords": _json.dumps(keywords),
                },
            ).scalar()
            if new_id is not None:
                ids[code] = str(new_id)


def downgrade() -> None:
    op.drop_index("ix_subject_topics_subject", table_name="subject_topics")
    op.drop_table("subject_topics")
    op.drop_table("syllabus_papers")
    op.drop_column("subjects", "source_url")
    op.drop_column("subjects", "syllabus_version")
    op.drop_column("subjects", "qualification_level")
    op.drop_column("subjects", "active")
    op.execute("DROP TYPE IF EXISTS papertier")
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_migration_0024_backfill.py -v`
Expected: 11 passed (3 + 3 + 3 parametrised, plus the provenance test; skipped if Postgres is unreachable)

- [ ] **Step 5: Verify the migration is reversible**

Run: `make db-migrate && make db-downgrade && make db-migrate`
Expected: all three succeed; no "type papertier already exists" on the second upgrade.

- [ ] **Step 6: Commit**

```bash
source .venv/bin/activate && pre-commit run --all-files
git add lemely/db/migrations/versions/0024_reference_catalogue.py tests/test_migration_0024_backfill.py tests/conftest.py
git commit -S -m "feat(db): migrate the syllabus catalogue into Postgres"
```

---

### Task 3: Rewire the loaders onto Postgres and delete the JSON

**Files:**
- Modify: `lemely/io/paper_timing.py`, `lemely/io/syllabus_topics.py`
- Delete: `lemely/data/paper_timing.json`, `lemely/data/syllabus_topics.json`
- Test: `tests/test_topics.py`, `tests/test_placement_assembly.py` (adapt), `tests/test_loader_cache.py` (new)

**Interfaces:**
- Consumes: Task 2's populated tables; `get_sessionmaker` from `lemely.db.session`.
- Produces: unchanged public signatures —
  `get_paper_timings(subject_code: str, *, board: str = "caie", include_practical: bool = False, session: Session | None = None) -> dict[int, PaperTiming]`
  `get_taxonomy(subject_code: str, *, board: str = "caie", session: Session | None = None) -> SyllabusTaxonomy | None`
  plus `invalidate_reference_cache() -> None` in each module.

The `session` parameter is additive and defaults to `None`, so the five existing call sites (`placement_repo.py:409` and `:510`, `question_bank_repo.py:287` and `:1022`, `practice_repo.py:826`, `attempt_repo.py:425`) need no edit. Tests inject a session; production opens one.

`get_taxonomy` runs **per question** inside classification loops — `question_bank_repo.py:1022` backfills the entire bank through it. Without a cache this turns one file parse into N round trips, so the process cache is not an optimisation, it is the thing that keeps the rewire from being a regression.

- [ ] **Step 1: Write the failing cache test**

```python
# tests/test_loader_cache.py
"""The reference loaders must hit the database once per process, not per call.

`get_taxonomy` is called once per classified question. A cache miss per call
would turn `question_bank_repo.backfill_topics` from one file parse into one
round trip per row, which is the regression this test exists to prevent.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import lemely.io.paper_timing as paper_timing
import lemely.io.syllabus_topics as syllabus_topics

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker


class _CountingSession:
    """Wraps a real session and counts `execute`/`scalars` calls."""

    def __init__(self, inner: Session) -> None:
        self._inner = inner
        self.queries = 0

    def scalars(self, *args: object, **kwargs: object) -> object:
        self.queries += 1
        return self._inner.scalars(*args, **kwargs)

    def execute(self, *args: object, **kwargs: object) -> object:
        self.queries += 1
        return self._inner.execute(*args, **kwargs)


def test_taxonomy_is_cached_after_the_first_load(migrated_sessionmaker: sessionmaker[Session]) -> None:
    syllabus_topics.invalidate_reference_cache()
    with migrated_sessionmaker() as raw:
        counting = _CountingSession(raw)
        first = syllabus_topics.get_taxonomy("0625", session=counting)  # type: ignore[arg-type]
        after_first = counting.queries
        for _ in range(20):
            syllabus_topics.get_taxonomy("0625", session=counting)  # type: ignore[arg-type]
        assert first is not None
        assert counting.queries == after_first, "every call after the first must be served from cache"


def test_invalidate_forces_a_reload(migrated_sessionmaker: sessionmaker[Session]) -> None:
    syllabus_topics.invalidate_reference_cache()
    with migrated_sessionmaker() as raw:
        counting = _CountingSession(raw)
        syllabus_topics.get_taxonomy("0625", session=counting)  # type: ignore[arg-type]
        before = counting.queries
        syllabus_topics.invalidate_reference_cache()
        syllabus_topics.get_taxonomy("0625", session=counting)  # type: ignore[arg-type]
        assert counting.queries > before


def test_paper_timings_still_exclude_practicals_by_default(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    paper_timing.invalidate_reference_cache()
    with migrated_sessionmaker() as s:
        assert set(paper_timing.get_paper_timings("0625", session=s)) == {1, 2, 3, 4}
        assert set(paper_timing.get_paper_timings("0625", include_practical=True, session=s)) == {
            1, 2, 3, 4, 5, 6,
        }
        assert paper_timing.get_paper_timings("9999", session=s) == {}
```

- [ ] **Step 2: Run it to verify it fails**

Run: `pytest tests/test_loader_cache.py -v`
Expected: FAIL — `module 'lemely.io.paper_timing' has no attribute 'invalidate_reference_cache'`

- [ ] **Step 3: Rewrite `lemely/io/paper_timing.py`**

```python
"""Loader for CAIE paper timing facts, backed by ``syllabus_papers``.

Was bundled static JSON; the table is the source of truth now (spec D1), so a
subject can be added without a deploy. The public shape is deliberately
unchanged — same function names, same ``dict[int, PaperTiming]`` return, same
practical-exclusion policy — so the placement assembler did not have to change.

Only ``duration_minutes`` and ``total_marks`` are stored. The minutes-per-mark
rate a placement estimate needs is computed from them
(:attr:`~lemely.core.placement.PaperTiming.minutes_per_mark`) and never written
down, so every stored number is one a human can check against the syllabus PDF
named in ``source_document``.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

import sqlalchemy as sa

from lemely.core.placement import PaperTiming
from lemely.db.models.catalogue import SyllabusPaper
from lemely.db.session import get_sessionmaker

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

_lock = threading.Lock()
_cache: dict[tuple[str, str], dict[int, PaperTiming]] | None = None


def invalidate_reference_cache() -> None:
    """Drop the process cache. Called by the seeding and ingest paths."""
    global _cache
    with _lock:
        _cache = None


def _load(session: Session) -> dict[tuple[str, str], dict[int, PaperTiming]]:
    out: dict[tuple[str, str], dict[int, PaperTiming]] = {}
    for row in session.scalars(sa.select(SyllabusPaper)):
        timing = PaperTiming(
            board=row.board.value,
            subject_code=row.subject_code,
            paper_number=row.paper_number,
            duration_minutes=row.duration_minutes,
            total_marks=row.total_marks,
            practical=row.practical,
            source_document=row.source_document,
            syllabus_version=row.syllabus_version,
        )
        out.setdefault((timing.board, timing.subject_code), {})[timing.paper_number] = timing
    return out


def load_paper_timings(session: Session | None = None) -> dict[tuple[str, str], dict[int, PaperTiming]]:
    """Every timing, keyed ``(board, subject_code)`` → ``paper_number``.

    Cached per process: the catalogue changes only when the ingest or seeder
    runs, and both call :func:`invalidate_reference_cache`.
    """
    global _cache
    with _lock:
        if _cache is not None:
            return _cache
    loaded = _load(session) if session is not None else _load_with_own_session()
    with _lock:
        _cache = loaded
    return loaded


def _load_with_own_session() -> dict[tuple[str, str], dict[int, PaperTiming]]:
    with get_sessionmaker()() as session:
        return _load(session)


def get_paper_timings(
    subject_code: str,
    *,
    board: str = "caie",
    include_practical: bool = False,
    session: Session | None = None,
) -> dict[int, PaperTiming]:
    """Timings for one subject, keyed by paper number.

    An empty mapping is a normal outcome, not an error: a subject whose
    Assessment overview has not been transcribed has no eligible placement
    questions, which is what the caller should report.

    Practical papers (0625 Papers 5/6) are excluded by default. Their questions
    assume apparatus in front of the candidate, so a practical question in an
    at-home placement test measures whether the student owns a ripple tank. The
    rows are still stored — this is an assembly policy, not a claim the data is
    wrong.
    """
    timings = load_paper_timings(session).get((board, subject_code), {})
    if include_practical:
        return dict(timings)
    return {number: t for number, t in timings.items() if not t.practical}
```

- [ ] **Step 4: Rewrite `lemely/io/syllabus_topics.py`**

```python
"""Loader for CAIE syllabus topic taxonomies, backed by ``subject_topics``.

Was bundled static JSON. Keyed on ``(board, subject_code)``, so another board
arrives as extra rows rather than a schema change. Provenance still travels
with the data: ``subjects.source_url`` and ``subjects.syllabus_version`` are
what a label like ``"4.3 Electric circuits"`` is only meaningful against,
because CAIE renumbers topics between syllabus cycles.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from typing import TYPE_CHECKING

import sqlalchemy as sa

from lemely.core.topics import SyllabusTaxonomy, TopicNode
from lemely.db.models.academic import Subject
from lemely.db.models.catalogue import SubjectTopic
from lemely.db.session import get_sessionmaker

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.orm import Session

_lock = threading.Lock()
_cache: dict[tuple[str, str], SyllabusTaxonomy] | None = None


def invalidate_reference_cache() -> None:
    """Drop the process cache. Called by the seeding and ingest paths."""
    global _cache
    with _lock:
        _cache = None


def _build_nodes(
    children: dict[uuid.UUID | None, list[SubjectTopic]], parent: uuid.UUID | None
) -> list[TopicNode]:
    """Depth-first tree build. Ordered by `code` so syllabus order survives."""
    return [
        TopicNode(
            code=row.code,
            name=row.name,
            strong=list(row.strong),
            keywords=list(row.keywords),
            subtopics=_build_nodes(children, row.id),
        )
        for row in sorted(children.get(parent, []), key=lambda r: r.code)
    ]


def _load(session: Session) -> dict[tuple[str, str], SyllabusTaxonomy]:
    subjects = {s.code: s for s in session.scalars(sa.select(Subject))}
    by_subject: dict[tuple[str, str], dict[uuid.UUID | None, list[SubjectTopic]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for row in session.scalars(sa.select(SubjectTopic)):
        by_subject[(row.board.value, row.subject_code)][row.parent_id].append(row)

    out: dict[tuple[str, str], SyllabusTaxonomy] = {}
    for (board, code), children in by_subject.items():
        subject = subjects.get(code)
        # A taxonomy needs a source URL by construction. A subject without one
        # yields no taxonomy rather than one citing nothing.
        if subject is None or not subject.source_url or not subject.syllabus_version:
            continue
        out[(board, code)] = SyllabusTaxonomy(
            board=board,
            subject_code=code,
            subject_name=subject.name,
            syllabus_version=subject.syllabus_version,
            source_url=subject.source_url,
            topics=_build_nodes(children, None),
        )
    return out


def load_taxonomies(session: Session | None = None) -> dict[tuple[str, str], SyllabusTaxonomy]:
    """Every taxonomy, keyed ``(board, subject_code)``. Cached per process."""
    global _cache
    with _lock:
        if _cache is not None:
            return _cache
    loaded = _load(session) if session is not None else _load_with_own_session()
    with _lock:
        _cache = loaded
    return loaded


def _load_with_own_session() -> dict[tuple[str, str], SyllabusTaxonomy]:
    with get_sessionmaker()() as session:
        return _load(session)


def get_taxonomy(
    subject_code: str, *, board: str = "caie", session: Session | None = None
) -> SyllabusTaxonomy | None:
    """The taxonomy for a subject, or ``None`` if none is stored.

    ``None`` is a normal outcome, not an error: the corpus can contain a
    subject whose syllabus has not been transcribed, and the honest result is
    an unclassified question rather than an invented topic.
    """
    return load_taxonomies(session).get((board, subject_code))
```

- [ ] **Step 5: Delete the JSON and repoint its tests**

```bash
git rm lemely/data/paper_timing.json lemely/data/syllabus_topics.json
```

In `tests/test_topics.py` and `tests/test_placement_assembly.py`, replace every `DATA_DIR / "*.json"` read and every bare `get_taxonomy(...)` / `get_paper_timings(...)` call with the `migrated_sessionmaker` fixture and an explicit `session=`. The assertions themselves — expected subjects, topic labels, the `{1,2,3,4}` vs `{1,2,3,4,5,6}` practical split — stay exactly as they are: they are the contract this rewire must not change.

- [ ] **Step 6: Run the full affected suite**

Run: `pytest tests/test_loader_cache.py tests/test_topics.py tests/test_placement_assembly.py -v`
Expected: all pass. Any failure here means the rewire changed behaviour, which it must not.

- [ ] **Step 7: Prove no bundled JSON is read on the request path**

Run: `grep -rn "paper_timing.json\|syllabus_topics.json" lemely/ tests/ scripts/ --include="*.py"`
Expected: no output.

- [ ] **Step 8: Commit**

```bash
source .venv/bin/activate && pre-commit run --all-files
git add -A lemely/io tests lemely/data
git commit -S -m "refactor(io): read the syllabus catalogue from Postgres, retire the bundled JSON"
```

---

### Task 4: `GET /api/reference` serving the subject catalogue

**Files:**
- Create: `lemely/db/catalogue_repo.py`, `lemely/web/schemas_reference.py`, `lemely/web/routers/reference.py`
- Modify: `lemely/web/app.py`, `lemely/web/routers/__init__.py`, `lemely/web/deps.py`
- Test: `tests/test_web_reference.py`

**Interfaces:**
- Consumes: Task 1's models.
- Produces:
  `CatalogueSubject(code: str, name: str, board: str, qualification_level: str | None, papers: list[CataloguePaper], topics: list[str])`
  `CataloguePaper(number: int, name: str, tier: str | None, practical: bool)`
  `CatalogueService(sessionmaker).subjects() -> list[CatalogueSubject]`
  `get_catalogue_service` dependency; `SubjectCatalogueDTO`, `SubjectPaperDTO`, `ReferenceDTO`.

`ReferenceDTO` gains `targetGradeVocabularies` in Task 14; it is declared now with an empty default so the frontend contract does not change shape mid-plan.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_web_reference.py
"""Route tests for ``GET /api/reference``.

Self-contained, mirroring ``tests/test_web_me.py``: a throwaway Postgres DB per
test, skipped cleanly when unreachable. Reachable by every authenticated role —
onboarding is a student flow, but seven other screens resolve subject names
through the same payload.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.db.base import Base
from lemely.db.catalogue_repo import CatalogueService
from lemely.db.models.academic import Subject
from lemely.db.models.catalogue import SubjectTopic, SyllabusPaper
from lemely.db.models.enums import ExamBoard, PaperTier, QualificationLevel, Role
from lemely.runtime.config import DatabaseSettings
from lemely.web import create_app
from lemely.web.deps import AuthContext, get_auth_context, get_catalogue_service

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app()
    yield TestClient(app)
    app.dependency_overrides.clear()


def _server_reachable(url: str) -> bool:
    engine = create_engine(make_url(url).set(database="postgres"))
    try:
        with engine.connect():
            return True
    except OperationalError:
        return False
    finally:
        engine.dispose()


@pytest.fixture
def pg_sessionmaker() -> Iterator[sessionmaker[Session]]:
    base_url = DatabaseSettings().url
    if not _server_reachable(base_url):
        pytest.skip("local Postgres not reachable")
    server_url = make_url(base_url).set(database="postgres")
    admin = create_engine(server_url, isolation_level="AUTOCOMMIT")
    dbname = f"lemely_test_{uuid.uuid4().hex[:12]}"
    with admin.connect() as conn:
        conn.execute(sa.text(f'CREATE DATABASE "{dbname}"'))
    engine = create_engine(make_url(base_url).set(database=dbname))
    Base.metadata.create_all(engine)
    try:
        yield sessionmaker(bind=engine, expire_on_commit=False, future=True)
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE)'))
        admin.dispose()


def _seed_catalogue(sm: sessionmaker[Session]) -> None:
    with sm.begin() as s:
        s.add(Subject(code="0625", name="Physics", board=ExamBoard.caie, active=True,
                      qualification_level=QualificationLevel.igcse,
                      syllabus_version="2023-2025", source_url="https://example.invalid/0625.pdf"))
        s.add(Subject(code="0580", name="Mathematics", board=ExamBoard.caie, active=True,
                      qualification_level=QualificationLevel.igcse,
                      syllabus_version="2025-2027", source_url="https://example.invalid/0580.pdf"))
        s.add(Subject(code="9999", name="Retired", board=ExamBoard.caie, active=False))
        s.add(SyllabusPaper(subject_code="0625", paper_number=2, name="Multiple Choice (Extended)",
                            tier=PaperTier.extended, duration_minutes=45, total_marks=40,
                            practical=False, source_document="d.pdf",
                            source_url="https://example.invalid/0625.pdf", syllabus_version="2023-2025"))
        s.add(SyllabusPaper(subject_code="0625", paper_number=1, name="Multiple Choice (Core)",
                            tier=PaperTier.core, duration_minutes=45, total_marks=40,
                            practical=False, source_document="d.pdf",
                            source_url="https://example.invalid/0625.pdf", syllabus_version="2023-2025"))
        s.add(SubjectTopic(subject_code="0625", code="2", name="Thermal physics",
                           strong=[], keywords=["heat"]))
        s.add(SubjectTopic(subject_code="0625", code="1", name="Motion, forces and energy",
                           strong=[], keywords=["force"]))


def _authenticate(client: TestClient, role: Role) -> None:
    ctx = AuthContext(user_id=uuid.uuid4(), role=role.value)
    client.app.dependency_overrides[get_auth_context] = lambda: ctx  # type: ignore[union-attr]


def _use_catalogue(client: TestClient, sm: sessionmaker[Session]) -> None:
    service = CatalogueService(sm)
    client.app.dependency_overrides[get_catalogue_service] = lambda: service  # type: ignore[union-attr]


def test_unauthenticated_call_is_401(client: TestClient) -> None:
    assert client.get("/api/reference").status_code == 401


@pytest.mark.parametrize("role", list(Role))
def test_every_authenticated_role_can_read_the_catalogue(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], role: Role
) -> None:
    _seed_catalogue(pg_sessionmaker)
    _authenticate(client, role)
    _use_catalogue(client, pg_sessionmaker)
    assert client.get("/api/reference").status_code == 200


def test_subjects_are_ordered_by_code_and_exclude_inactive(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    _seed_catalogue(pg_sessionmaker)
    _authenticate(client, Role.student)
    _use_catalogue(client, pg_sessionmaker)
    body = client.get("/api/reference").json()
    assert [s["code"] for s in body["subjects"]] == ["0580", "0625"]


def test_papers_are_ordered_by_number_and_carry_their_tier(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    _seed_catalogue(pg_sessionmaker)
    _authenticate(client, Role.student)
    _use_catalogue(client, pg_sessionmaker)
    physics = next(s for s in client.get("/api/reference").json()["subjects"] if s["code"] == "0625")
    assert [(p["number"], p["tier"]) for p in physics["papers"]] == [(1, "core"), (2, "extended")]


def test_topics_are_code_prefixed_strings_in_syllabus_order(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    """The `"<code> <name>"` vocabulary `ConfidenceRating.topic` already speaks."""
    _seed_catalogue(pg_sessionmaker)
    _authenticate(client, Role.student)
    _use_catalogue(client, pg_sessionmaker)
    physics = next(s for s in client.get("/api/reference").json()["subjects"] if s["code"] == "0625")
    assert physics["topics"] == ["1 Motion, forces and energy", "2 Thermal physics"]


def test_classifier_vocabulary_is_never_served(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    """`strong`/`keywords` are Lemely's authored matching terms, not syllabus content."""
    _seed_catalogue(pg_sessionmaker)
    _authenticate(client, Role.student)
    _use_catalogue(client, pg_sessionmaker)
    raw = client.get("/api/reference").text
    assert "keywords" not in raw
    assert "strong" not in raw


def test_an_empty_catalogue_is_an_empty_list_not_an_error(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    _authenticate(client, Role.student)
    _use_catalogue(client, pg_sessionmaker)
    response = client.get("/api/reference")
    assert response.status_code == 200
    assert response.json()["subjects"] == []


def test_enumerations_mirror_the_backend_enums(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    _authenticate(client, Role.student)
    _use_catalogue(client, pg_sessionmaker)
    body = client.get("/api/reference").json()
    assert [q["value"] for q in body["qualificationLevels"]] == [
        "igcse", "o_level", "as_level", "a_level",
    ]
    assert [m["value"] for m in body["sessionMonths"]] == [
        "may_june", "oct_nov", "feb_mar", "specimen",
    ]
    assert body["difficultyBands"] == ["foundation", "standard", "challenge"]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `pytest tests/test_web_reference.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lemely.db.catalogue_repo'`

- [ ] **Step 3: Write the repo**

```python
# lemely/db/catalogue_repo.py
"""Read side of the syllabus catalogue.

The only module that queries ``subjects`` / ``syllabus_papers`` /
``subject_topics`` for presentation. Returns plain frozen dataclasses rather
than ORM rows so the router never holds a detached instance, matching how the
other ``*_repo`` modules hand rows to their routers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import sqlalchemy as sa

from lemely.db.models.academic import Subject
from lemely.db.models.catalogue import SubjectTopic, SyllabusPaper

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker


@dataclass(frozen=True, slots=True)
class CataloguePaper:
    """One paper offered for selection in S-01."""

    number: int
    name: str
    tier: str | None
    practical: bool


@dataclass(frozen=True, slots=True)
class CatalogueSubject:
    """One offered subject with its papers and top-level topics."""

    code: str
    name: str
    board: str
    qualification_level: str | None
    papers: list[CataloguePaper]
    topics: list[str]


class CatalogueService:
    """Reads the offered catalogue."""

    def __init__(self, sessionmaker: sessionmaker[Session]) -> None:
        self._sessionmaker = sessionmaker

    def subjects(self) -> list[CatalogueSubject]:
        """Every active subject, ordered by ``code``.

        Ordered by code rather than by a display-order column: the spec (D3)
        drops that column, and code order is deterministic without one.
        Top-level topics only — S-02 asks about those, and the subtopic tree
        exists for the classifier, not for a picker.
        """
        with self._sessionmaker() as session:
            subjects = session.scalars(
                sa.select(Subject).where(Subject.active.is_(True)).order_by(Subject.code)
            ).all()
            papers = session.scalars(
                sa.select(SyllabusPaper).order_by(SyllabusPaper.paper_number)
            ).all()
            topics = session.scalars(
                sa.select(SubjectTopic)
                .where(SubjectTopic.parent_id.is_(None))
                .order_by(SubjectTopic.code)
            ).all()

        papers_by_subject: dict[str, list[CataloguePaper]] = {}
        for row in papers:
            papers_by_subject.setdefault(row.subject_code, []).append(
                CataloguePaper(
                    number=row.paper_number,
                    name=row.name,
                    tier=row.tier.value if row.tier else None,
                    practical=row.practical,
                )
            )

        topics_by_subject: dict[str, list[str]] = {}
        for row in topics:
            # `"<code> <name>"` is the vocabulary `ConfidenceRating.topic` and
            # the weakness engine already use. Composed here, once, so no
            # caller has to know the convention.
            topics_by_subject.setdefault(row.subject_code, []).append(f"{row.code} {row.name}")

        return [
            CatalogueSubject(
                code=s.code,
                name=s.name,
                board=s.board.value,
                qualification_level=(
                    s.qualification_level.value if s.qualification_level else None
                ),
                papers=papers_by_subject.get(s.code, []),
                topics=topics_by_subject.get(s.code, []),
            )
            for s in subjects
        ]
```

- [ ] **Step 4: Write the DTOs**

```python
# lemely/web/schemas_reference.py
"""``GET /api/reference`` DTOs — the catalogue and every enumeration the UI needs.

One endpoint rather than several (spec D4): one round trip, one cache key, one
hook, and one place the frontend's "no hardcoded reference data" gate can point
at. Field names are camelCase declared directly, matching
``schemas_student_profile.py``'s convention — an explicit ``ApiModel`` subclass
per DTO, no alias generator.
"""

from __future__ import annotations

from lemely.web.schemas import ApiModel


class SubjectPaperDTO(ApiModel):
    """One paper a student can tick in S-01."""

    number: int
    name: str
    tier: str | None = None
    practical: bool


class SubjectCatalogueDTO(ApiModel):
    """One offered subject.

    ``qualificationLevel`` is the subject's own (spec D10) — 0580/0606/0625 are
    all IGCSE syllabuses — not a student-declared preference. S-01 displays it
    rather than asking, which is what removes "A-Level Physics 0625" from the
    set of expressible answers.
    """

    code: str
    name: str
    board: str
    qualificationLevel: str | None = None
    papers: list[SubjectPaperDTO]
    topics: list[str]


class LabelledValueDTO(ApiModel):
    """A ``(value, label)`` pair for an enumeration the UI renders."""

    value: str
    label: str


class TargetGradeVocabularyDTO(ApiModel):
    """The grades a student may aim for in one subject at one tier.

    Keyed by **subject**, not only by qualification level, because the measured
    data differs that way: 0580 Extended options publish A*-E with no F/G,
    while 0625 Extended options publish A*-G. A vocabulary keyed on
    ``(qualificationLevel, tier)`` alone would offer a 0580 student an F they
    cannot be awarded.

    Populated in a later stage from ``option_thresholds``; declared now so the
    wire contract does not change shape underneath the frontend.
    """

    subjectCode: str
    qualificationLevel: str | None = None
    tier: str | None = None
    grades: list[str]


class ReferenceDTO(ApiModel):
    """Everything the frontend used to hardcode."""

    subjects: list[SubjectCatalogueDTO]
    targetGradeVocabularies: list[TargetGradeVocabularyDTO] = []
    qualificationLevels: list[LabelledValueDTO]
    sessionMonths: list[LabelledValueDTO]
    difficultyBands: list[str]
```

- [ ] **Step 5: Write the router and wire it up**

```python
# lemely/web/routers/reference.py
"""``GET /api/reference`` — the reference data the frontend must not hardcode.

Authenticated for any role: onboarding is a student flow, but the seven screens
that resolve a syllabus code to a display name span the student portal, and the
payload contains nothing user-specific.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from lemely.core.difficulty import _BANDS
from lemely.db.models.enums import SESSION_MONTH_LABELS, QualificationLevel
from lemely.web.deps import AuthContext, get_auth_context, get_catalogue_service
from lemely.web.schemas_reference import (
    LabelledValueDTO,
    ReferenceDTO,
    SubjectCatalogueDTO,
    SubjectPaperDTO,
)

if False:  # pragma: no cover - typing only
    from lemely.db.catalogue_repo import CatalogueService

router = APIRouter(prefix="/api")

#: Display labels for `QualificationLevel`. The backend owns this table now —
#: `web/src/lib/qualificationLevels.ts` used to declare its own copy.
QUALIFICATION_LEVEL_LABELS: dict[QualificationLevel, str] = {
    QualificationLevel.igcse: "IGCSE",
    QualificationLevel.o_level: "O-Level",
    QualificationLevel.as_level: "AS-Level",
    QualificationLevel.a_level: "A-Level",
}


@router.get("/reference", response_model=ReferenceDTO)
def get_reference(
    _auth: Annotated[AuthContext, Depends(get_auth_context)],
    catalogue: Annotated["CatalogueService", Depends(get_catalogue_service)],
) -> ReferenceDTO:
    """Return the subject catalogue and every UI enumeration.

    An empty ``subjects`` list is returned honestly rather than as an error: an
    unseeded environment has no catalogue, and the screen renders that as a
    failure the student can retry, never as a bundled default list.
    """
    return ReferenceDTO(
        subjects=[
            SubjectCatalogueDTO(
                code=s.code,
                name=s.name,
                board=s.board,
                qualificationLevel=s.qualification_level,
                papers=[
                    SubjectPaperDTO(
                        number=p.number, name=p.name, tier=p.tier, practical=p.practical
                    )
                    for p in s.papers
                ],
                topics=s.topics,
            )
            for s in catalogue.subjects()
        ],
        qualificationLevels=[
            LabelledValueDTO(value=level.value, label=label)
            for level, label in QUALIFICATION_LEVEL_LABELS.items()
        ],
        sessionMonths=[
            LabelledValueDTO(value=month.value, label=label)
            for month, label in SESSION_MONTH_LABELS.items()
        ],
        difficultyBands=list(_BANDS),
    )
```

In `lemely/web/deps.py`, beside `get_history_store`:

```python
def get_catalogue_service() -> CatalogueService:
    """The syllabus catalogue reader, bound to the process sessionmaker."""
    return CatalogueService(get_sessionmaker(get_settings()))
```

In `lemely/web/routers/__init__.py` add `reference` to the import and `__all__`. In `lemely/web/app.py` add `app.include_router(reference.router)` beside `meta.router`.

- [ ] **Step 6: Run the tests**

Run: `pytest tests/test_web_reference.py -v`
Expected: all pass (13 tests; the role-parametrised one runs 5 times)

- [ ] **Step 7: Commit**

```bash
source .venv/bin/activate && pre-commit run --all-files
git add lemely/db/catalogue_repo.py lemely/web/schemas_reference.py lemely/web/routers/reference.py lemely/web/routers/__init__.py lemely/web/app.py lemely/web/deps.py tests/test_web_reference.py
git commit -S -m "feat(web): serve the subject catalogue and UI enumerations from /api/reference"
```

---

# Stage 2 — The frontend onto the catalogue

The unit suite runs in a Node environment with no jsdom and no
`@testing-library` (`vitest.config.ts`, D3.20) — component behaviour is
Playwright's job. So every decision worth testing lives in a **pure selector**
in `lib/reference.ts`, and the hooks are thin wrappers over it. This mirrors how
`onboardingData.ts` is already structured.

### Task 5: Reference types, pure selectors, and the query hook

**Files:**
- Create: `web/src/lib/referenceTypes.ts`, `web/src/lib/reference.ts`, `web/src/lib/hooks/useReferenceApi.ts`, `web/tests/unit/reference.test.ts`
- Modify: `web/src/lib/qualificationLevels.ts`

**Interfaces:**
- Consumes: `GET /api/reference` from Task 4.
- Produces:
  `interface ReferenceData { subjects: CatalogueSubject[]; targetGradeVocabularies: TargetGradeVocabulary[]; qualificationLevels: LabelledValue[]; sessionMonths: LabelledValue[]; difficultyBands: string[] }`
  `subjectNameFor(reference: ReferenceData | undefined, code: string): string`
  `subjectFor(reference: ReferenceData | undefined, code: string): CatalogueSubject | null`
  `confidenceTopicsFor(subject: CatalogueSubject | null): string[]`
  `CONFIDENCE_TOPICS_SHOWN = 3`
  `useReference(): UseQueryResult<ReferenceData, Error>`
  `useSubjectName(code: string): string`

- [ ] **Step 1: Write the failing test**

```ts
// web/tests/unit/reference.test.ts
import { describe, expect, it } from "vitest"
import {
  CONFIDENCE_TOPICS_SHOWN,
  confidenceTopicsFor,
  subjectFor,
  subjectNameFor,
} from "@/lib/reference"
import type { CatalogueSubject, ReferenceData } from "@/lib/referenceTypes"

function subject(code: string, name: string, topics: string[] = []): CatalogueSubject {
  return { code, name, board: "caie", qualificationLevel: "igcse", papers: [], topics }
}

const REFERENCE: ReferenceData = {
  subjects: [
    subject("0580", "Mathematics"),
    subject("0625", "Physics", [
      "1 Motion, forces and energy",
      "2 Thermal physics",
      "3 Waves",
      "4 Electricity and magnetism",
    ]),
  ],
  targetGradeVocabularies: [],
  qualificationLevels: [],
  sessionMonths: [],
  difficultyBands: [],
}

describe("subjectNameFor", () => {
  it("resolves a known code to its catalogue name", () => {
    expect(subjectNameFor(REFERENCE, "0625")).toBe("Physics")
  })

  it("falls back to the raw code for an unknown subject", () => {
    // The exact expression the seven lookup screens used before this existed
    // (`SUPPORTED_SUBJECTS.find(...)?.name ?? subjectCode`). Keeping it means a
    // subject added to the catalogue before a screen knows about it degrades to
    // showing the code, never to showing nothing.
    expect(subjectNameFor(REFERENCE, "9709")).toBe("9709")
  })

  it("falls back to the raw code while the query is still loading", () => {
    // `undefined` is what react-query hands a component on first render. A
    // screen must render the code, not crash and not flash an empty heading.
    expect(subjectNameFor(undefined, "0625")).toBe("0625")
  })
})

describe("subjectFor", () => {
  it("returns the catalogue entry for a known code", () => {
    expect(subjectFor(REFERENCE, "0580")?.name).toBe("Mathematics")
  })

  it("returns null rather than undefined for an unknown code", () => {
    expect(subjectFor(REFERENCE, "9999")).toBeNull()
  })

  it("returns null while the query is loading", () => {
    expect(subjectFor(undefined, "0625")).toBeNull()
  })
})

describe("confidenceTopicsFor", () => {
  it("shows the first three topics, preserving S-02's existing behaviour", () => {
    // The endpoint returns every top-level topic (0606 has fourteen). How many
    // to ask about is a UI decision, not a curriculum fact, so the slice lives
    // here rather than in the backend.
    expect(confidenceTopicsFor(subjectFor(REFERENCE, "0625"))).toEqual([
      "1 Motion, forces and energy",
      "2 Thermal physics",
      "3 Waves",
    ])
  })

  it("returns an empty list for a subject with no topics", () => {
    expect(confidenceTopicsFor(subjectFor(REFERENCE, "0580"))).toEqual([])
  })

  it("returns an empty list for a missing subject", () => {
    expect(confidenceTopicsFor(null)).toEqual([])
  })

  it("pins the count so a change is a deliberate edit", () => {
    expect(CONFIDENCE_TOPICS_SHOWN).toBe(3)
  })
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd web && npm test -- reference`
Expected: FAIL — cannot resolve `@/lib/reference`

- [ ] **Step 3: Write the types**

```ts
// web/src/lib/referenceTypes.ts
/*
 * TS interfaces mirroring `lemely/web/schemas_reference.py` field-for-field
 * (camelCase). `GET /api/reference` is reachable by every authenticated role.
 *
 * This module replaces every hardcoded backend-owned table the frontend used
 * to declare: the subject catalogue, the grade vocabularies, qualification
 * levels, session months and difficulty bands. Adding a constant here that
 * mirrors backend truth defeats the point — fetch it.
 */

/** One paper a student can tick in S-01 (mirrors `SubjectPaperDTO`). */
export interface CataloguePaper {
  number: number
  name: string
  /** `"core"`, `"extended"`, or null for an untiered subject such as 0606. */
  tier: string | null
  practical: boolean
}

/** One offered subject (mirrors `SubjectCatalogueDTO`).
 *
 * `qualificationLevel` is the subject's own, not a student preference: 0580,
 * 0606 and 0625 are all IGCSE syllabuses, so S-01 displays it instead of
 * asking. `topics` are `"<code> <name>"` strings in syllabus order — the
 * vocabulary `ConfidenceRating.topic` speaks. Never compose that string here.
 */
export interface CatalogueSubject {
  code: string
  name: string
  board: string
  qualificationLevel: string | null
  papers: CataloguePaper[]
  topics: string[]
}

/** The grades a student may aim for in one subject at one tier.
 *
 * Keyed by subject, not only by qualification level: 0580 Extended publishes
 * A*-E while 0625 Extended publishes A*-G, so a coarser key would offer a
 * 0580 student an F they cannot be awarded.
 */
export interface TargetGradeVocabulary {
  subjectCode: string
  qualificationLevel: string | null
  tier: string | null
  grades: string[]
}

/** A `(value, label)` pair for an enumeration the UI renders. */
export interface LabelledValue {
  value: string
  label: string
}

/** Response for `GET /api/reference` (mirrors `ReferenceDTO`). */
export interface ReferenceData {
  subjects: CatalogueSubject[]
  targetGradeVocabularies: TargetGradeVocabulary[]
  qualificationLevels: LabelledValue[]
  sessionMonths: LabelledValue[]
  difficultyBands: string[]
}
```

- [ ] **Step 4: Write the pure selectors**

```ts
// web/src/lib/reference.ts
/*
 * Pure selectors over `ReferenceData`. No React, no fetching — this is what
 * `web/tests/unit/reference.test.ts` exercises directly, the same split
 * `onboardingData.ts` uses (the unit suite runs in Node with no jsdom, so
 * component behaviour belongs to Playwright and pure logic belongs here).
 *
 * Every selector accepts `undefined` for the reference payload, because that
 * is what react-query hands a component on its first render. Degrading to the
 * raw syllabus code is deliberate: it is the exact fallback the seven lookup
 * screens had before the catalogue was fetched, so nothing regresses while the
 * query is in flight.
 */

import type { CatalogueSubject, ReferenceData, TargetGradeVocabulary } from "@/lib/referenceTypes"

/**
 * How many of a subject's top-level topics S-02's confidence step asks about.
 *
 * The endpoint returns every top-level topic — 0606 has fourteen — because how
 * many to ask is a UI decision and which ones exist is a curriculum fact. Three
 * is what S-01/S-02 shipped with; changing it should be a deliberate edit with
 * a test failure attached, which is why the unit suite pins the number.
 */
export const CONFIDENCE_TOPICS_SHOWN = 3

/** The catalogue entry for a code, or null when unknown or still loading. */
export function subjectFor(
  reference: ReferenceData | undefined,
  code: string,
): CatalogueSubject | null {
  return reference?.subjects.find((s) => s.code === code) ?? null
}

/** A subject's display name, falling back to the raw code. */
export function subjectNameFor(reference: ReferenceData | undefined, code: string): string {
  return subjectFor(reference, code)?.name ?? code
}

/** The topics S-02 asks a confidence rating for. */
export function confidenceTopicsFor(subject: CatalogueSubject | null): string[] {
  return (subject?.topics ?? []).slice(0, CONFIDENCE_TOPICS_SHOWN)
}

/**
 * The grades a student may set as a target for one subject.
 *
 * Keyed on the subject and the tier of the papers they ticked, because the
 * vocabularies genuinely differ that way: 0580 Core publishes C–G with no A*,
 * 0580 Extended publishes A*–E with no F/G, and 0625 publishes A*–G. Returns
 * an empty list when no vocabulary matches, so the picker renders nothing
 * rather than an invented grade set.
 */
export function targetGradesFor(
  reference: ReferenceData | undefined,
  subjectCode: string,
  tier: string | null,
): string[] {
  if (!reference) return []
  const forSubject = reference.targetGradeVocabularies.filter(
    (v: TargetGradeVocabulary) => v.subjectCode === subjectCode,
  )
  // An exact tier match first; then the untiered vocabulary, which is what an
  // untiered subject (0606) publishes and what a student who has ticked no
  // papers yet should see.
  return (
    forSubject.find((v) => v.tier === tier)?.grades ??
    forSubject.find((v) => v.tier === null)?.grades ??
    []
  )
}

/**
 * The tier implied by the papers a student ticked for one subject.
 *
 * Extended wins when both are present: a candidate sitting any Extended paper
 * is an Extended candidate, and offering them the Core vocabulary would cap
 * their target at C. Returns null when nothing is ticked or the subject is
 * untiered, which `targetGradesFor` treats as "use the untiered vocabulary".
 */
export function tierForPapers(subject: CatalogueSubject | null, papers: readonly number[]): string | null {
  if (!subject) return null
  const tiers = new Set(
    papers
      .map((n) => subject.papers.find((p) => p.number === n)?.tier)
      .filter((t): t is string => Boolean(t)),
  )
  if (tiers.has("extended")) return "extended"
  if (tiers.has("core")) return "core"
  return null
}
```

- [ ] **Step 5: Write the hook**

```ts
// web/src/lib/hooks/useReferenceApi.ts
import { useQuery, type UseQueryResult } from "@tanstack/react-query"
import { request } from "@/lib/api"
import { subjectNameFor } from "@/lib/reference"
import type { ReferenceData } from "@/lib/referenceTypes"

/*
 * React-query hook wrapping `GET /api/reference` (`lemely/web/routers/reference.py`),
 * reachable by every authenticated role. Follows useMeApi.ts's conventions: one
 * hook per endpoint, and **no `fallback` passed to `request()`** — a real
 * backend or auth failure must surface as a query error the screen can render,
 * never silently resolve to an empty catalogue. An empty subject list would
 * read as "we support no subjects", which is a claim, not an absence.
 */

const REFERENCE_KEY = ["reference"] as const

/**
 * The reference payload.
 *
 * `staleTime: Infinity` because this data changes only when the catalogue is
 * re-seeded or the threshold ingest runs — both deploy-time events. Nine screens
 * read it; refetching per mount would be nine requests for a payload that
 * cannot have changed between them.
 */
export function useReference(): UseQueryResult<ReferenceData, Error> {
  return useQuery({
    queryKey: REFERENCE_KEY,
    queryFn: () => request<ReferenceData>("/reference"),
    staleTime: Number.POSITIVE_INFINITY,
  })
}

/** A subject's display name, or the raw code while loading or when unknown. */
export function useSubjectName(code: string): string {
  const { data } = useReference()
  return subjectNameFor(data, code)
}
```

- [ ] **Step 6: Reduce `qualificationLevels.ts` to its helper**

Delete the `QUALIFICATION_LEVELS` array. Keep the helper, now taking the fetched table:

```ts
// web/src/lib/qualificationLevels.ts
import type { LabelledValue } from "@/lib/referenceTypes"

/**
 * The human label for a raw qualification-level value, or `null` for
 * null/undefined/unrecognised — never an invented label.
 *
 * The table itself is served by `/api/reference` (it mirrors
 * `lemely.db.models.enums.QualificationLevel`); this module keeps only the
 * lookup, so there is no second copy of the values in the frontend.
 */
export function qualificationLevelLabel(
  levels: LabelledValue[] | undefined,
  value: string | null | undefined,
): string | null {
  if (!value) return null
  return levels?.find((l) => l.value === value)?.label ?? null
}
```

Update `subjectIdentifier` (`web/src/lib/subjectIdentifier.ts`) to take `levels: LabelledValue[] | undefined` as its first argument and pass it through, and update its call sites accordingly.

- [ ] **Step 7: Run the tests and the typechecker**

Run: `cd web && npm test -- reference && npm run typecheck`
Expected: 10 passed; typecheck clean.

- [ ] **Step 8: Commit**

```bash
source .venv/bin/activate && pre-commit run --all-files
git add web/src/lib/referenceTypes.ts web/src/lib/reference.ts web/src/lib/hooks/useReferenceApi.ts web/src/lib/qualificationLevels.ts web/src/lib/subjectIdentifier.ts web/tests/unit/reference.test.ts
git commit -S -m "feat(web): fetch reference data instead of hardcoding the catalogue"
```

---

### Task 6: Strip the catalogue out of `onboardingData.ts`

**Files:**
- Modify: `web/src/portals/student/screens/onboarding/onboardingData.ts`, `web/tests/unit/onboarding.test.ts`

**Interfaces:**
- Consumes: `CatalogueSubject` from Task 5.
- Produces: `placementInviteSubject(enrolledCodes: readonly string[], subjects: readonly CatalogueSubject[]): string | null`. `SUPPORTED_SUBJECTS`, `SupportedSubject`, `SubjectPaper`, `GRADE_ORDER`, `SESSION_MONTHS` and the `QUALIFICATION_LEVELS` re-export are all deleted.

- [ ] **Step 1: Rewrite the failing tests**

Replace the `placementInviteSubject` describe block in `web/tests/unit/onboarding.test.ts`:

```ts
import type { CatalogueSubject } from "@/lib/referenceTypes"

function cat(code: string): CatalogueSubject {
  return { code, name: code, board: "caie", qualificationLevel: "igcse", papers: [], topics: [] }
}

// Catalogue order is `code` order now (spec D3 drops the display-order
// column), so the fixture is ordered the way `/api/reference` returns it.
const CATALOGUE = [cat("0580"), cat("0606"), cat("0625")]

describe("placementInviteSubject — S-02 → S-03 routing", () => {
  it("sends a single-subject student to that subject", () => {
    expect(placementInviteSubject(["0580"], CATALOGUE)).toBe("0580")
  })

  it("returns null when the student enrolled in nothing (S-06 instead)", () => {
    expect(placementInviteSubject([], CATALOGUE)).toBeNull()
  })

  it("orders by the fetched catalogue, not by the order the codes arrive in", () => {
    expect(placementInviteSubject(["0625", "0580"], CATALOGUE)).toBe("0580")
    expect(placementInviteSubject(["0580", "0625"], CATALOGUE)).toBe("0580")
  })

  it("does not depend on JS object key enumeration order", () => {
    // The regression this function exists for. `Object.keys` hoists
    // integer-like keys ahead of insertion order, so a syllabus code without a
    // leading zero silently jumps the queue. Today's codes all have one, which
    // is exactly why the bug was invisible.
    const drafts: Record<string, boolean> = {}
    drafts["0625"] = true
    drafts["9709"] = true
    expect(Object.keys(drafts)[0]).toBe("9709") // the trap, pinned
    expect(placementInviteSubject(Object.keys(drafts), CATALOGUE)).toBe("0625")
  })

  it("ignores a code that is not in the catalogue", () => {
    expect(placementInviteSubject(["9999"], CATALOGUE)).toBeNull()
  })

  it("returns null when the catalogue has not loaded", () => {
    // Guards the same failure `Onboarding.tsx`'s seeding effect guards: acting
    // on an empty catalogue must not silently mean "no subjects".
    expect(placementInviteSubject(["0625"], [])).toBeNull()
  })
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd web && npm test -- onboarding`
Expected: FAIL — `placementInviteSubject` takes one argument.

- [ ] **Step 3: Edit `onboardingData.ts`**

Delete `SupportedSubject`, `SubjectPaper`, `SUPPORTED_SUBJECTS`, `SESSION_MONTHS`, `GRADE_ORDER` and the `QUALIFICATION_LEVELS` re-export. Replace the header note that justified mirroring the data with the new arrangement, and rewrite the function:

```ts
import type { CatalogueSubject } from "@/lib/referenceTypes"

/**
 * Which subject's placement invite (S-03) to send the student to when they
 * finish S-02, or `null` if they enrolled in none — in which case there is no
 * placement test to invite them into and the caller sends them to S-06.
 *
 * Deliberately NOT `Object.keys(drafts)[0]`. The drafts object is keyed by
 * syllabus code, and JS enumerates integer-like string keys first, ahead of
 * every other key's insertion order. All of today's codes have a leading zero
 * and so are not integer-like — insertion order happens to survive, which is
 * exactly what makes the bug invisible now and live the day a code without a
 * leading zero is added. Ordering by the catalogue instead means the student
 * is sent to the first subject *as presented to them in S-01*, which stays
 * true whatever the codes look like.
 *
 * `subjects` is the fetched catalogue rather than a module constant, so an
 * empty array (query still loading) correctly yields `null` instead of
 * silently claiming the student enrolled in nothing.
 */
export function placementInviteSubject(
  enrolledCodes: readonly string[],
  subjects: readonly CatalogueSubject[],
): string | null {
  const enrolled = new Set(enrolledCodes)
  return subjects.find((subject) => enrolled.has(subject.code))?.code ?? null
}
```

- [ ] **Step 4: Run the tests**

Run: `cd web && npm test -- onboarding && npm run typecheck`
Expected: the onboarding suite passes; typecheck reports errors only in files Tasks 7 and 8 will fix (`SubjectsStep.tsx`, `Onboarding.tsx`, `QuestionnaireStep.tsx`, and the seven lookup screens). Those are the work list for the next two tasks.

- [ ] **Step 5: Commit**

```bash
git add web/src/portals/student/screens/onboarding/onboardingData.ts web/tests/unit/onboarding.test.ts
git commit -S -m "refactor(web): take the subject catalogue as a parameter, not a constant"
```

---

### Task 7: Wire the onboarding screens to the fetched catalogue

**Files:**
- Modify: `web/src/portals/student/screens/Onboarding.tsx`, `web/src/portals/student/screens/onboarding/SubjectsStep.tsx`, `web/src/portals/student/screens/onboarding/QuestionnaireStep.tsx`

**Interfaces:**
- Consumes: `useReference` (Task 5), `subjectFor`, `confidenceTopicsFor`, `targetGradesFor`, `tierForPapers` (Task 5), `placementInviteSubject` (Task 6).
- Produces: `SubjectsStepProps` loses `qualificationLevel`, `onQualificationLevel` and `onSubjectQualificationLevel`; gains `subjects: CatalogueSubject[]`, `sessionMonths: LabelledValue[]`, `targetGrades: (code: string) => string[]`, `loading: boolean`, `loadError: boolean`, `onRetry: () => void`.

Two changes here are behavioural, not cosmetic, and are the reason this is one task rather than three:

1. **The seeding effect must wait for the catalogue.** `Onboarding.tsx` filters existing enrolments against it. Seeding while it is empty silently drops every saved enrolment for a student resuming onboarding — a data-loss bug, not a flicker.
2. **Both qualification-level controls are removed** (spec D10). A subject carries its own level, so the profile-wide picker and the per-subject override both go, along with `backfillNullQualificationLevels`, whose entire purpose was reconciling the two.

- [ ] **Step 1: Gate the seeding effect and fetch the catalogue**

In `Onboarding.tsx`, add the query and make the effect depend on it:

```tsx
import { useReference } from "@/lib/hooks/useReferenceApi"
import { subjectFor, targetGradesFor, tierForPapers } from "@/lib/reference"

  const { data: reference, isLoading: referenceLoading, isError: referenceError, refetch } = useReference()

  const seeded = useRef(false)
  useEffect(() => {
    // `reference` is load-bearing, not decorative: the filter below drops any
    // enrolment whose subject is not in the catalogue, so seeding against an
    // empty catalogue would drop *every* saved enrolment and the student would
    // silently lose the subjects they picked last session.
    if (seeded.current || !existing || !reference) return
    seeded.current = true
    const seededDrafts: Record<string, SubjectDraft> = {}
    const seededConfidence: Record<string, Record<string, number>> = {}
    for (const enrolment of existing.enrolments) {
      if (!reference.subjects.some((s) => s.code === enrolment.subjectCode)) continue
      seededDrafts[enrolment.subjectCode] = {
        subjectCode: enrolment.subjectCode,
        qualificationLevel: enrolment.qualificationLevel,
        papers: new Set(enrolment.papers),
        targetGrade: enrolment.targetGrade,
        sessionMonth: enrolment.sessionMonth,
        sessionYear: enrolment.sessionYear,
      }
      if (enrolment.confidenceRatings.length > 0) {
        seededConfidence[enrolment.subjectCode] = Object.fromEntries(
          enrolment.confidenceRatings.map((r) => [r.topic, r.rating]),
        )
      }
    }
    setDrafts(seededDrafts)
    setConfidenceBySubject(seededConfidence)
    setAnswers({
      schoolName: existing.profile.schoolName ?? undefined,
      hasExternalLessons: existing.profile.hasExternalLessons ?? undefined,
      weeklyStudyHours: existing.profile.weeklyStudyHours ?? undefined,
      gradeLevel: existing.profile.gradeLevel ?? undefined,
    })
  }, [existing, reference])
```

- [ ] **Step 2: Take the qualification level from the subject**

Delete the `qualificationLevel` state, the `backfillNullQualificationLevels` import and call, and the `patchProfile` call that wrote it. `toggleSubject` reads the level off the catalogue entry:

```tsx
  function toggleSubject(code: string) {
    setDrafts((prev) => {
      const next = { ...prev }
      if (next[code]) {
        delete next[code]
      } else {
        next[code] = {
          subjectCode: code,
          // The subject's own level (D10) — 0580/0606/0625 are IGCSE
          // syllabuses, so asking the student produced answers like "A-Level
          // Physics 0625" that describe nothing that exists.
          qualificationLevel: subjectFor(reference, code)?.qualificationLevel ?? null,
          papers: new Set(),
          targetGrade: null,
          sessionMonth: null,
          sessionYear: null,
        }
      }
      return next
    })
  }
```

and `handleSubjectsContinue` drops its `patchProfile` branch, keeping only the enrolments PUT.

- [ ] **Step 3: Pass the catalogue down**

```tsx
  <SubjectsStep
    subjects={reference?.subjects ?? []}
    sessionMonths={reference?.sessionMonths ?? []}
    targetGrades={(code) =>
      targetGradesFor(
        reference,
        code,
        tierForPapers(subjectFor(reference, code), [...(drafts[code]?.papers ?? [])]),
      )
    }
    loading={referenceLoading}
    loadError={referenceError}
    onRetry={() => void refetch()}
    drafts={drafts}
    onToggleSubject={toggleSubject}
    onTogglePaper={togglePaper}
    onTargetGrade={(code, grade) => updateDraft(code, { targetGrade: grade })}
    onSessionMonth={(code, month) => updateDraft(code, { sessionMonth: month })}
    onSessionYear={(code, year) => updateDraft(code, { sessionYear: year })}
    onContinue={handleSubjectsContinue}
    saving={putEnrolments.isPending}
    error={error}
  />
```

and `handleFinish`'s routing call becomes `placementInviteSubject(Object.keys(drafts), reference?.subjects ?? [])`.

- [ ] **Step 4: Rework `SubjectsStep.tsx`**

Replace the `SUPPORTED_SUBJECTS`/`QUALIFICATION_LEVELS`/`GRADE_ORDER`/`SESSION_MONTHS` imports with the props above, delete the qualification-level `Card` and the per-subject qualification `Select`, and render the fetched list. Add the two states the screen never had:

```tsx
      {loadError ? (
        <Card className="flex flex-col items-start gap-3 p-5">
          <p role="alert" className="text-body-md text-ink">
            We couldn't load the subject list. Nothing you've entered has been lost.
          </p>
          <Button type="button" variant="secondary" size="sm" className="min-h-11" onClick={onRetry}>
            Try again
          </Button>
        </Card>
      ) : loading ? (
        // A skeleton rather than a spinner: the shape of what is coming is
        // known (a stack of subject cards), so showing it avoids the layout
        // shift a spinner guarantees.
        <div className="flex flex-col gap-4" aria-busy="true" aria-live="polite">
          <span className="sr-only">Loading subjects</span>
          {[0, 1, 2].map((i) => (
            <Card key={i} className="h-20 animate-pulse bg-paper-sunk" />
          ))}
        </div>
      ) : (
        <div className="flex flex-col gap-4">{/* existing subject cards, over `subjects` */}</div>
      )}
```

The target-grade `Select` iterates `targetGrades(subject.code)` and the session `Select` iterates the `sessionMonths` prop. Replace the footer note, which hardcoded the three subject names, with one derived from the data:

```tsx
        <p className="text-pretty text-body-sm text-ink-muted">
          More subjects are coming.{" "}
          {subjects.length > 0
            ? `${subjects.map((s) => s.name).join(", ")} ${subjects.length === 1 ? "is the one" : "are the ones"} we can mark and build study plans for today.`
            : ""}
        </p>
```

- [ ] **Step 5: Point `QuestionnaireStep.tsx` at the fetched topics**

Replace its `SUPPORTED_SUBJECTS` import and lookup:

```tsx
import { confidenceTopicsFor, subjectFor } from "@/lib/reference"

    const topics = confidenceTopicsFor(subjectFor(reference, step.subjectCode))
```

with `reference` threaded in as a prop from `Onboarding.tsx`, and iterate `topics` where it iterated `subject?.confidenceTopics ?? []`.

- [ ] **Step 6: Verify**

Run: `cd web && npm run typecheck && npm test && npm run lint`
Expected: typecheck clean for these three files; the unit suite passes.

- [ ] **Step 7: Commit**

```bash
git add web/src/portals/student/screens/Onboarding.tsx web/src/portals/student/screens/onboarding/
git commit -S -m "feat(web): drive onboarding from the fetched subject catalogue"
```

---

### Task 8: The seven name-lookup screens

**Files:**
- Modify: `PracticeGenerator.tsx`, `PracticeResult.tsx`, `FlashcardDecks.tsx`, `FlashcardReview.tsx`, `PlacementInvite.tsx`, `PlacementResult.tsx`, `StudyPlanWeek.tsx`, `StudyPlanSession.tsx`

**Interfaces:**
- Consumes: `useSubjectName` (Task 5).
- Produces: nothing new. This task only removes the last `SUPPORTED_SUBJECTS` importers.

Each of these files does the same thing in one line. The replacement preserves behaviour exactly: `useSubjectName` falls back to the raw code, which is what `?? subjectCode` already did.

- [ ] **Step 1: Replace each lookup**

In every file, delete:

```tsx
import { SUPPORTED_SUBJECTS } from "@/portals/student/screens/onboarding/onboardingData"
const subjectName = SUPPORTED_SUBJECTS.find((s) => s.code === subjectCode)?.name ?? subjectCode
```

and add:

```tsx
import { useSubjectName } from "@/lib/hooks/useReferenceApi"
const subjectName = useSubjectName(subjectCode)
```

`PracticeResult.tsx:90` and `PlacementResult.tsx:96` read `data.subjectCode` rather than a `subjectCode` variable — use `useSubjectName(data.subjectCode)` there. Because `useSubjectName` is a hook, it must be called at the top level of the component, never inside a `map` or a conditional; in `FlashcardDecks.tsx:296` the lookup sits in a child component, which is already the right place for it.

- [ ] **Step 2: Prove the constant is gone**

Run: `grep -rn "SUPPORTED_SUBJECTS" web/src web/tests web/e2e`
Expected: no output.

- [ ] **Step 3: Verify**

Run: `cd web && npm run typecheck && npm test && npm run lint`
Expected: all clean.

- [ ] **Step 4: Run the E2E journey against a seeded stack**

Run: `make up && cd web && npx playwright test e2e/phase4-journey.spec.ts e2e/signup.spec.ts`
Expected: both pass. If S-01 renders no subject cards, the E2E database has no catalogue — `web/e2e/global-setup.ts` must run the migration (Task 2 seeds it) before the specs.

- [ ] **Step 5: Commit**

```bash
git add web/src/portals/student/screens
git commit -S -m "refactor(web): resolve subject names through the fetched catalogue"
```

---

# Stage 3 — Grade thresholds in Postgres

### Task 9: Threshold models and migration 0025

**Files:**
- Create: `lemely/db/models/thresholds.py`, `lemely/db/migrations/versions/0025_thresholds.py`
- Test: `tests/test_threshold_models.py`

**Interfaces:**
- Produces: `ComponentThreshold`, `OptionThreshold`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_threshold_models.py
"""Model-shape tests for the threshold tables (no database required)."""

from __future__ import annotations

from lemely.db.models.thresholds import ComponentThreshold, OptionThreshold


def test_component_threshold_records_whether_it_was_verified() -> None:
    """`verified` is the honest half of the ingest: a row sourced from ciegt
    alone must not be indistinguishable from one a Cambridge PDF confirmed."""
    cols = ComponentThreshold.__table__.columns
    assert cols["verified"].nullable is False
    assert cols["source_url"].nullable is False


def test_component_threshold_is_unique_per_paper_and_session() -> None:
    uniques = {
        tuple(sorted(c.name for c in con.columns))
        for con in ComponentThreshold.__table__.constraints
        if con.__class__.__name__ == "UniqueConstraint"
    }
    assert (
        "board", "paper_number", "paper_variant", "session_month", "session_year", "subject_code",
    ) in uniques


def test_option_max_mark_is_nullable_for_the_pre_2020_layout() -> None:
    """Older CAIE threshold tables print `Option A* A B C D E F G` with no
    "maximum mark after weighting" column at all. A NOT NULL column here would
    make those sessions unstorable."""
    assert OptionThreshold.__table__.columns["max_mark_after_weighting"].nullable is True
```

- [ ] **Step 2: Run it to verify it fails**

Run: `pytest tests/test_threshold_models.py -v`
Expected: FAIL — no module `lemely.db.models.thresholds`

- [ ] **Step 3: Write the models**

```python
# lemely/db/models/thresholds.py
"""ORM models for CAIE grade thresholds.

Two tables, because Cambridge publishes two tables and they mean different
things. ``component_thresholds`` is per paper: it is what a single marked paper
is graded against, and **Grade A\\* does not exist at this level** — the source
documents say so in those words. ``option_thresholds`` is per weighted
combination of components, and is the only place A\\* appears.

Raw marks are stored with ``max_mark`` rather than pre-computed percentages, so
every stored number is one a human can check against the document.
:class:`~lemely.io.grade_boundaries.GradeBoundaryStore` divides at read time.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from lemely.db.base import Base
from lemely.db.models.enums import ExamBoard, SessionMonth, TimestampMixin


class ComponentThreshold(TimestampMixin, Base):
    """Minimum raw marks per grade for one component in one session."""

    __tablename__ = "component_thresholds"
    __table_args__ = (
        sa.UniqueConstraint(
            "board", "subject_code", "session_month", "session_year",
            "paper_number", "paper_variant",
            name="uq_component_thresholds_identity",
        ),
        sa.Index("ix_component_thresholds_lookup", "board", "subject_code", "session_year"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
    )
    board: Mapped[ExamBoard] = mapped_column(
        sa.Enum(ExamBoard, name="examboard"), nullable=False,
        server_default=sa.text("'caie'::examboard"),
    )
    subject_code: Mapped[str] = mapped_column(sa.String, nullable=False)
    session_month: Mapped[SessionMonth] = mapped_column(
        sa.Enum(SessionMonth, name="sessionmonth"), nullable=False
    )
    session_year: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    paper_number: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    paper_variant: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    max_mark: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    #: ``{"C": 42, "D": 34, ...}`` — grade → minimum raw mark.
    thresholds: Mapped[dict[str, int]] = mapped_column(JSONB, nullable=False)
    #: True when every grade above was confirmed against the official PDF.
    #: False means the row came from ciegt alone and only the weaker
    #: "drop anything at or below zero raw marks" filter was applied. Nothing
    #: may cite Cambridge as the source of an unverified row.
    verified: Mapped[bool] = mapped_column(sa.Boolean, nullable=False)
    source_url: Mapped[str] = mapped_column(sa.String, nullable=False)


class OptionThreshold(TimestampMixin, Base):
    """Syllabus-level thresholds for one weighted option, including A\\*."""

    __tablename__ = "option_thresholds"
    __table_args__ = (
        sa.UniqueConstraint(
            "board", "subject_code", "session_month", "session_year", "option_code",
            name="uq_option_thresholds_identity",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
    )
    board: Mapped[ExamBoard] = mapped_column(
        sa.Enum(ExamBoard, name="examboard"), nullable=False,
        server_default=sa.text("'caie'::examboard"),
    )
    subject_code: Mapped[str] = mapped_column(sa.String, nullable=False)
    session_month: Mapped[SessionMonth] = mapped_column(
        sa.Enum(SessionMonth, name="sessionmonth"), nullable=False
    )
    session_year: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    #: e.g. ``"BX"`` — Cambridge's own label for the combination.
    option_code: Mapped[str] = mapped_column(sa.String, nullable=False)
    #: e.g. ``[21, 41, 51]``.
    component_numbers: Mapped[list[int]] = mapped_column(JSONB, nullable=False)
    #: Nullable: the pre-2020 layout omits this column entirely.
    max_mark_after_weighting: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    thresholds: Mapped[dict[str, int]] = mapped_column(JSONB, nullable=False)
    source_url: Mapped[str] = mapped_column(sa.String, nullable=False)
```

- [ ] **Step 4: Write migration 0025**

`lemely/db/migrations/versions/0025_thresholds.py`, `revision = "0025_thresholds"`, `down_revision = "0024_reference_catalogue"`. Two `op.create_table` calls mirroring the models above, reusing the existing `examboard` and `sessionmonth` types with `postgresql.ENUM(name=..., create_type=False)`, plus `op.create_index("ix_component_thresholds_lookup", ...)`. `downgrade` drops both tables. No new enum type is created, so `downgrade` drops none.

- [ ] **Step 5: Verify**

Run: `pytest tests/test_threshold_models.py -v && make db-migrate && make db-downgrade && make db-migrate`
Expected: 3 passed; migrations round-trip.

- [ ] **Step 6: Commit**

```bash
source .venv/bin/activate && pre-commit run --all-files
git add lemely/db/models/thresholds.py lemely/db/migrations/versions/0025_thresholds.py tests/test_threshold_models.py
git commit -S -m "feat(db): add component and option threshold tables"
```

---

### Task 10: The ciegt client

**Files:**
- Create: `lemely/io/ciegt.py`, `tests/fixtures/ciegt_0625.json`, `tests/test_ciegt.py`

**Interfaces:**
- Produces:
  `decode_devalue(payload: dict) -> list[dict]`
  `parse_session_label(label: str) -> tuple[SessionMonth, int]`
  `parse_component(component: str) -> tuple[int, int]`
  `ComponentRow(subject_code, session_month, session_year, paper_number, paper_variant, max_mark, thresholds, source_url)`
  `fetch_rows(subject_code: str, *, qualification: str = "igcse") -> list[ComponentRow]`

- [ ] **Step 1: Capture the fixture**

```bash
source .venv/bin/activate && python - <<'PY'
import json, urllib.request
url = "https://ciegt.pooruli.com/igcse/0625/__data.json"
req = urllib.request.Request(url, headers={
    "User-Agent": "Lemely-ingest/1.0 (+https://github.com/LemelyIG/Lemely; educational grade-boundary ingestion)",
    "Accept": "application/json",
})
raw = urllib.request.urlopen(req, timeout=60).read().decode()
open("tests/fixtures/ciegt_0625.json", "w").write(raw)
print("captured", len(raw), "bytes")
PY
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_ciegt.py
"""Decoding tests for the ciegt payload, against a captured real response.

The site is a SvelteKit app and its data route serves devalue: a flat pool where
a number *inside* an object or array is an index into that pool, and a number
*in* the pool is a literal value. Getting that distinction wrong yields
plausible-looking nonsense rather than an error, which is why it is pinned here
against a real captured payload rather than a hand-written one.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lemely.db.models.enums import SessionMonth
from lemely.io.ciegt import decode_devalue, parse_component, parse_session_label, rows_from_payload

FIXTURE = Path(__file__).parent / "fixtures" / "ciegt_0625.json"


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("M/J 24", (SessionMonth.may_june, 2024)),
        ("O/N 23", (SessionMonth.oct_nov, 2023)),
        ("F/M 26", (SessionMonth.feb_mar, 2026)),
    ],
)
def test_session_labels_map_to_enum_and_year(label: str, expected: tuple[SessionMonth, int]) -> None:
    assert parse_session_label(label) == expected


def test_an_unknown_session_label_raises_rather_than_guessing() -> None:
    with pytest.raises(ValueError, match="Unrecognised session label"):
        parse_session_label("Q4 24")


@pytest.mark.parametrize(
    ("component", "expected"), [("11", (1, 1)), ("50", (5, 0)), ("1", (1, 0))]
)
def test_component_codes_split_into_paper_and_variant(
    component: str, expected: tuple[int, int]
) -> None:
    assert parse_component(component) == expected


def test_decode_finds_the_threshold_table() -> None:
    rows = decode_devalue(json.loads(FIXTURE.read_text(encoding="utf-8")))
    assert len(rows) > 500, "0625 has ~660 rows across ~50 sessions"
    assert {"session", "component", "max"} <= set(rows[0])


def test_rows_carry_raw_marks_and_drop_the_not_applicable_sentinel() -> None:
    """`-1` is how the payload encodes CAIE's en dash — "not available at this
    tier". It is an absence, not a threshold of minus one mark."""
    rows = rows_from_payload(json.loads(FIXTURE.read_text(encoding="utf-8")), "0625")
    core = next(
        r for r in rows
        if r.session_year == 2024 and r.session_month is SessionMonth.may_june
        and (r.paper_number, r.paper_variant) == (1, 1)
    )
    assert "A" not in core.thresholds
    assert "B" not in core.thresholds
    assert core.thresholds["C"] == 27
    assert core.max_mark == 40


def test_source_url_points_at_the_official_document() -> None:
    rows = rows_from_payload(json.loads(FIXTURE.read_text(encoding="utf-8")), "0625")
    row = next(r for r in rows if r.session_year == 2024 and r.session_month is SessionMonth.may_june)
    assert row.source_url.endswith("0625_s24_gt.pdf")
```

- [ ] **Step 3: Run it to verify it fails**

Run: `pytest tests/test_ciegt.py -v`
Expected: FAIL — no module `lemely.io.ciegt`

- [ ] **Step 4: Write the client**

```python
# lemely/io/ciegt.py
"""Client for the CIE Grade Thresholds Database (ciegt.pooruli.com).

Supplies component threshold rows and the index of which sessions exist. Its
numbers are verified against the official Cambridge PDFs by
``scripts/ingest_thresholds.py`` before they are stored, because the site is an
unaffiliated transcription and these numbers decide real grades: a measured
comparison of 57 records found 51 exact matches and 6 rows in 0606 carrying F
and G grades the official document does not publish at all.

No browser is involved. The site is a SvelteKit app, but its data route serves
JSON directly, so this is plain ``urllib``.
"""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from typing import Any

from lemely.db.models.enums import SessionMonth
from lemely.runtime.errors import ExternalServiceError

_BASE = "https://ciegt.pooruli.com"
_PAPACAMBRIDGE = "https://pastpapers.papacambridge.com/directories/CAIE/CAIE-pastpapers/upload"
_USER_AGENT = (
    "Lemely-ingest/1.0 (+https://github.com/LemelyIG/Lemely; "
    "educational grade-boundary ingestion)"
)
_TIMEOUT_SECONDS = 60.0

#: ciegt's session labels → our enum plus the short code CAIE uses in filenames.
_SESSIONS: dict[str, tuple[SessionMonth, str]] = {
    "M/J": (SessionMonth.may_june, "s"),
    "O/N": (SessionMonth.oct_nov, "w"),
    "F/M": (SessionMonth.feb_mar, "m"),
}

#: The payload marks "not available at this tier" as -1, mirroring the en dash
#: the PDF prints. An absence, never a threshold.
_NOT_APPLICABLE = -1

_GRADES = ("A", "B", "C", "D", "E", "F", "G")


@dataclass(frozen=True, slots=True)
class ComponentRow:
    """One component's thresholds for one session, as ciegt reports them."""

    subject_code: str
    session_month: SessionMonth
    session_year: int
    paper_number: int
    paper_variant: int
    max_mark: int
    thresholds: dict[str, int]
    source_url: str


def parse_session_label(label: str) -> tuple[SessionMonth, int]:
    """``"M/J 24"`` → ``(SessionMonth.may_june, 2024)``.

    Raises rather than guessing on an unknown label: a mis-parsed session
    silently files a paper's thresholds under the wrong year, which surfaces as
    a wrong grade rather than as an error.
    """
    try:
        prefix, year = label.rsplit(" ", 1)
        month, _code = _SESSIONS[prefix]
        return month, 2000 + int(year)
    except (KeyError, ValueError) as exc:
        raise ValueError(f"Unrecognised session label: {label!r}") from exc


def parse_component(component: str) -> tuple[int, int]:
    """``"11"`` → ``(1, 1)``; ``"50"`` → ``(5, 0)``; ``"1"`` → ``(1, 0)``.

    A single-digit component is an unvaried paper, which we store as variant 0
    rather than inventing variant 1.
    """
    if len(component) == 1:
        return int(component), 0
    return int(component[0]), int(component[1])


def session_filename_code(month: SessionMonth, year: int) -> str:
    """``(may_june, 2024)`` → ``"s24"`` — CAIE's own filename convention."""
    code = next(c for m, c in _SESSIONS.values() if m is month)
    return f"{code}{year % 100:02d}"


def gt_pdf_url(subject_code: str, month: SessionMonth, year: int) -> str:
    """The official grade-threshold PDF for one syllabus and session."""
    return f"{_PAPACAMBRIDGE}/{subject_code}_{session_filename_code(month, year)}_gt.pdf"


def _unflatten(pool: list[Any], index: Any) -> Any:
    """Resolve one devalue index into a plain Python value.

    A number *inside* a dict or list is an index into ``pool``; a number found
    *in* ``pool`` is a literal. That asymmetry is the whole format. Negative
    indices are devalue's sentinels (``-1`` undefined, ``-2`` a hole).
    """
    if isinstance(index, int) and index < 0:
        return None
    value = pool[index]
    if isinstance(value, dict):
        return {k: _unflatten(pool, i) for k, i in value.items()}
    if isinstance(value, list):
        return [_unflatten(pool, i) for i in value]
    return value


def decode_devalue(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the threshold table from a decoded ``__data.json`` payload."""
    for node in payload.get("nodes", []):
        if node.get("type") != "data":
            continue
        root = _unflatten(node["data"], 0)
        if isinstance(root, dict) and "table" in root:
            table = root["table"]
            if isinstance(table, list):
                return table
    raise ExternalServiceError("ciegt payload carried no threshold table")


def rows_from_payload(payload: dict[str, Any], subject_code: str) -> list[ComponentRow]:
    """Decode a payload into typed rows, dropping the -1 sentinel."""
    rows: list[ComponentRow] = []
    for raw in decode_devalue(payload):
        month, year = parse_session_label(raw["session"])
        number, variant = parse_component(str(raw["component"]))
        rows.append(
            ComponentRow(
                subject_code=subject_code,
                session_month=month,
                session_year=year,
                paper_number=number,
                paper_variant=variant,
                max_mark=int(raw["max"]),
                thresholds={
                    grade: int(raw[grade])
                    for grade in _GRADES
                    if raw.get(grade) not in (None, _NOT_APPLICABLE)
                },
                source_url=gt_pdf_url(subject_code, month, year),
            )
        )
    return rows


def fetch_rows(subject_code: str, *, qualification: str = "igcse") -> list[ComponentRow]:
    """Fetch and decode one syllabus's rows. One request per syllabus."""
    url = f"{_BASE}/{qualification}/{subject_code}/__data.json"
    request = urllib.request.Request(  # noqa: S310 - fixed https host
        url, headers={"User-Agent": _USER_AGENT, "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:  # noqa: S310
            payload = json.loads(response.read().decode())
    except (OSError, ValueError) as exc:
        raise ExternalServiceError(f"ciegt fetch failed for {subject_code}: {exc}") from exc
    return rows_from_payload(payload, subject_code)
```

- [ ] **Step 5: Run the tests**

Run: `pytest tests/test_ciegt.py -v`
Expected: 9 passed

- [ ] **Step 6: Commit**

```bash
source .venv/bin/activate && pre-commit run --all-files
git add lemely/io/ciegt.py tests/test_ciegt.py tests/fixtures/ciegt_0625.json
git commit -S -m "feat(io): add the ciegt threshold client"
```

---

### Task 11: The threshold PDF parser

**Files:**
- Create: `lemely/io/threshold_pdf.py`, `tests/fixtures/0625_s24_gt.pdf`, `tests/fixtures/0625_s19_gt.pdf`, `tests/test_threshold_pdf.py`

**Interfaces:**
- Produces:
  `ParsedComponent(paper_number, paper_variant, max_mark, thresholds)`
  `ParsedOption(option_code, component_numbers, max_mark_after_weighting, thresholds)`
  `parse_threshold_pdf(pdf_bytes: bytes) -> tuple[list[ParsedComponent], list[ParsedOption]]`

Both tables come out of one parse because they live in one document. The two fixtures are the two layout eras: 2024 prints `Option mark after A* A B C D E F G` with a maximum-mark column, 2019 prints `Option A* A B C D E F G` without one. Handling only the current layout silently yields zero options for every older session.

- [ ] **Step 1: Capture the fixtures**

```bash
source .venv/bin/activate && python - <<'PY'
import urllib.request, time
base = "https://pastpapers.papacambridge.com/directories/CAIE/CAIE-pastpapers/upload"
ua = {"User-Agent": "Lemely-ingest/1.0 (+https://github.com/LemelyIG/Lemely; educational grade-boundary ingestion)"}
for name in ("0625_s24_gt.pdf", "0625_s19_gt.pdf"):
    req = urllib.request.Request(f"{base}/{name}", headers=ua)
    open(f"tests/fixtures/{name}", "wb").write(urllib.request.urlopen(req, timeout=60).read())
    print("captured", name)
    time.sleep(2)
PY
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_threshold_pdf.py
"""Parser tests against two real CAIE grade-threshold PDFs.

The two fixtures are the two layout eras. 2024 prints the option header as
"Option mark after A* A B C D E F G" with a maximum-mark column; 2019 prints
"Option A* A B C D E F G" without one. A parser that handles only the current
layout returns zero options for every older session and does so silently.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lemely.io.threshold_pdf import parse_threshold_pdf

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def s24() -> tuple[list, list]:
    return parse_threshold_pdf((FIXTURES / "0625_s24_gt.pdf").read_bytes())


@pytest.fixture(scope="module")
def s19() -> tuple[list, list]:
    return parse_threshold_pdf((FIXTURES / "0625_s19_gt.pdf").read_bytes())


def test_components_parse_with_their_raw_marks(s24: tuple[list, list]) -> None:
    components, _ = s24
    assert len(components) == 18
    p21 = next(c for c in components if (c.paper_number, c.paper_variant) == (2, 1))
    assert p21.max_mark == 40
    assert p21.thresholds == {"A": 24, "B": 21, "C": 18, "D": 16, "E": 15, "F": 14, "G": 13}


def test_a_core_component_omits_the_grades_marked_with_an_en_dash(s24: tuple[list, list]) -> None:
    """CAIE prints "–" where a grade is not available at that tier. That is an
    absence, and must not become a threshold."""
    components, _ = s24
    p11 = next(c for c in components if (c.paper_number, c.paper_variant) == (1, 1))
    assert "A" not in p11.thresholds
    assert "B" not in p11.thresholds
    assert p11.thresholds["C"] == 27


def test_no_component_anywhere_carries_a_star(s24: tuple[list, list], s19: tuple[list, list]) -> None:
    """The documents state it outright: "Grade A* does not exist at the level of
    an individual component." This is why an awarded single-paper grade tops out
    at A, and why A* lives only in the option table."""
    for components, _ in (s24, s19):
        assert all("A*" not in c.thresholds for c in components)


def test_options_carry_a_star_and_their_component_combination(s24: tuple[list, list]) -> None:
    _, options = s24
    bx = next(o for o in options if o.option_code == "BX")
    assert bx.component_numbers == [21, 41, 51]
    assert bx.max_mark_after_weighting == 200
    assert bx.thresholds["A*"] == 144
    assert bx.thresholds["G"] == 44


def test_the_older_layout_parses_without_a_maximum_mark_column(s19: tuple[list, list]) -> None:
    _, options = s19
    assert len(options) == 12
    bx = next(o for o in options if o.option_code == "BX")
    assert bx.max_mark_after_weighting is None
    assert bx.component_numbers == [21, 41, 51]
    assert bx.thresholds["A*"] == 130


def test_an_unparseable_document_yields_empty_lists_rather_than_raising() -> None:
    """Pre-2014 documents carry a watermark that bleeds into the text layer. The
    ingest stores those sessions unverified rather than failing the whole run."""
    assert parse_threshold_pdf(b"%PDF-1.4 not really a pdf") == ([], [])
```

- [ ] **Step 3: Run it to verify it fails**

Run: `pytest tests/test_threshold_pdf.py -v`
Expected: FAIL — no module `lemely.io.threshold_pdf`

- [ ] **Step 4: Write the parser**

```python
# lemely/io/threshold_pdf.py
"""Parser for official CAIE grade-threshold PDFs.

One document carries two tables and they mean different things:

* **Components** — minimum raw mark per grade for one paper. The document
  states "Grade A\\* does not exist at the level of an individual component",
  which is why a single marked paper can never be graded A\\*.
* **Options** — thresholds for a weighted combination of components (e.g.
  ``BX = 21, 41, 51``), and the only place A\\* appears.

Two layout eras exist for each table and both are still in circulation, so both
are handled. The component header is either ``mark A B C ...`` or ``Component A
B C ...``; the option header is either ``Option A* A B ...`` (pre-2020, no
maximum-mark column) or ``Option mark after A* A B ...`` (current). A parser
that knows only the current layout returns nothing for older sessions and does
so without complaint, which is worse than failing.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass

import pdfplumber

#: CAIE marks "not applicable at this tier" with an en dash or a hyphen.
_NOT_APPLICABLE = ("–", "-", "—")

_COMPONENT_HEADER = re.compile(r"^(?:mark|Component)\s+((?:[A-Z]\*?\s+)*[A-Z]\*?)$")
_COMPONENT_ROW = re.compile(r"^Component\s+(\d+)\s+(\d+)\s+(.+)$")
#: `mark after` is optional — that is the whole difference between the eras.
_OPTION_HEADER = re.compile(r"^Option\s+(?:mark\s+after\s+)?((?:[A-Z]\*?\s+)*[A-Z]\*?)$")
_OPTION_ROW = re.compile(
    r"^([A-Z]{1,3})\s+(?:(\d+)\s+)?((?:\d+\s*,\s*)*\d+)\s+((?:[-–\d]+\s+)*[-–\d]+)$"
)


@dataclass(frozen=True, slots=True)
class ParsedComponent:
    """One component's thresholds, as the document prints them."""

    paper_number: int
    paper_variant: int
    max_mark: int
    thresholds: dict[str, int]


@dataclass(frozen=True, slots=True)
class ParsedOption:
    """One weighted option's thresholds, including A\\*."""

    option_code: str
    component_numbers: list[int]
    max_mark_after_weighting: int | None
    thresholds: dict[str, int]


def _text(pdf_bytes: bytes) -> str:
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


def parse_threshold_pdf(pdf_bytes: bytes) -> tuple[list[ParsedComponent], list[ParsedOption]]:
    """Return ``(components, options)``.

    Empty lists are a supported outcome, not an error: pre-2014 documents carry
    a watermark that bleeds into the text layer and defeats line-based parsing.
    The ingest stores those sessions unverified rather than aborting the run,
    so one unreadable document cannot cost us fifty readable ones.
    """
    try:
        text = _text(pdf_bytes)
    except Exception:  # noqa: BLE001 - any malformed PDF is "unreadable", not fatal
        return [], []

    components: list[ParsedComponent] = []
    options: list[ParsedOption] = []
    component_grades: list[str] | None = None
    option_grades: list[str] | None = None

    for line in (raw.strip() for raw in text.splitlines()):
        header = _COMPONENT_HEADER.match(line)
        if header:
            component_grades = header.group(1).split()
            continue
        option_header = _OPTION_HEADER.match(line)
        if option_header:
            option_grades = option_header.group(1).split()
            continue

        row = _COMPONENT_ROW.match(line)
        if row and component_grades:
            number_variant, max_mark, rest = row.group(1), int(row.group(2)), row.group(3).split()
            if len(rest) != len(component_grades):
                continue
            components.append(
                ParsedComponent(
                    paper_number=int(number_variant[0]),
                    paper_variant=int(number_variant[1]) if len(number_variant) > 1 else 0,
                    max_mark=max_mark,
                    thresholds={
                        grade: int(value)
                        for grade, value in zip(component_grades, rest, strict=True)
                        if value not in _NOT_APPLICABLE
                    },
                )
            )
            continue

        option = _OPTION_ROW.match(line)
        if option and option_grades:
            values = option.group(4).split()
            if len(values) != len(option_grades):
                continue
            options.append(
                ParsedOption(
                    option_code=option.group(1),
                    component_numbers=[int(c.strip()) for c in option.group(3).split(",")],
                    max_mark_after_weighting=int(option.group(2)) if option.group(2) else None,
                    thresholds={
                        grade: int(value)
                        for grade, value in zip(option_grades, values, strict=True)
                        if value not in _NOT_APPLICABLE
                    },
                )
            )

    return components, options
```

- [ ] **Step 5: Run the tests**

Run: `pytest tests/test_threshold_pdf.py -v`
Expected: 6 passed

- [ ] **Step 6: Commit**

```bash
source .venv/bin/activate && pre-commit run --all-files
git add lemely/io/threshold_pdf.py tests/test_threshold_pdf.py tests/fixtures/0625_s24_gt.pdf tests/fixtures/0625_s19_gt.pdf
git commit -S -m "feat(io): parse component and option tables from CAIE threshold PDFs"
```

---

### Task 12: The ingest script

**Files:**
- Create: `scripts/ingest_thresholds.py`, `tests/test_ingest_thresholds.py`
- Delete: `scripts/ingest_grade_boundaries.py`

**Interfaces:**
- Consumes: `ComponentRow` (Task 10), `parse_threshold_pdf` (Task 11), the models (Task 9).
- Produces: `verify_row(row: ComponentRow, parsed: list[ParsedComponent] | None) -> tuple[dict[str, int], bool]`, `ingest(subject_codes: list[str], *, session_factory, fetch_pdf) -> IngestReport`.

`verify_row` is the honest core of this task and is pure, so it is tested without a network or a database.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ingest_thresholds.py
"""The verification rule that keeps fabricated grades out of the database.

The premise this whole design rests on was measured, not assumed: 57 ciegt
component records were compared against the official PDFs and 51 matched
exactly. The 6 that did not were all 0606, where ciegt carries F and G grades
Cambridge does not publish — and 0606's option table publishes A*-E too, so it
is not a tier artefact. These tests pin the rule that removes them.
"""

from __future__ import annotations

from lemely.db.models.enums import SessionMonth
from lemely.io.ciegt import ComponentRow
from lemely.io.threshold_pdf import ParsedComponent
from scripts.ingest_thresholds import verify_row


def _row(thresholds: dict[str, int]) -> ComponentRow:
    return ComponentRow(
        subject_code="0606",
        session_month=SessionMonth.may_june,
        session_year=2024,
        paper_number=1,
        paper_variant=1,
        max_mark=80,
        thresholds=thresholds,
        source_url="https://example.invalid/0606_s24_gt.pdf",
    )


def test_a_grade_the_document_does_not_publish_is_dropped() -> None:
    """0606 M/J 24 component 11, verbatim from both sources. ciegt reports
    A-G; the official PDF publishes A-E. F and G must not survive."""
    row = _row({"A": 53, "B": 38, "C": 22, "D": 16, "E": 10, "F": 4, "G": 0})
    parsed = [
        ParsedComponent(
            paper_number=1, paper_variant=1, max_mark=80,
            thresholds={"A": 53, "B": 38, "C": 22, "D": 16, "E": 10},
        )
    ]
    thresholds, verified = verify_row(row, parsed)
    assert thresholds == {"A": 53, "B": 38, "C": 22, "D": 16, "E": 10}
    assert verified is True


def test_the_document_wins_when_a_value_differs() -> None:
    row = _row({"A": 53, "B": 99})
    parsed = [ParsedComponent(paper_number=1, paper_variant=1, max_mark=80,
                              thresholds={"A": 53, "B": 38})]
    thresholds, verified = verify_row(row, parsed)
    assert thresholds["B"] == 38
    assert verified is True


def test_without_a_document_only_impossible_values_are_dropped() -> None:
    """The fallback for a session whose PDF is missing or watermark-mangled.
    A threshold of zero raw marks is not a published boundary; a threshold of
    four is not obviously wrong, so it survives — which is exactly why the row
    is marked unverified rather than trusted."""
    row = _row({"A": 53, "E": 10, "F": 4, "G": 0})
    thresholds, verified = verify_row(row, None)
    assert thresholds == {"A": 53, "E": 10, "F": 4}
    assert verified is False


def test_a_component_missing_from_the_document_is_unverified_not_deleted() -> None:
    row = _row({"A": 53})
    parsed = [ParsedComponent(paper_number=9, paper_variant=9, max_mark=80, thresholds={"A": 1})]
    thresholds, verified = verify_row(row, parsed)
    assert thresholds == {"A": 53}
    assert verified is False


def test_a_formulaic_looking_threshold_is_kept_when_the_document_publishes_it() -> None:
    """CAIE's own 2012 document says "G is set as many marks below the F
    threshold as the E threshold is above it" - Cambridge derives G by formula
    itself. The rule is "does the document publish this grade", never "does
    this number look derived"."""
    row = _row({"E": 21, "F": 15, "G": 9})
    parsed = [ParsedComponent(paper_number=1, paper_variant=1, max_mark=80,
                              thresholds={"E": 21, "F": 15, "G": 9})]
    thresholds, verified = verify_row(row, parsed)
    assert thresholds == {"E": 21, "F": 15, "G": 9}
    assert verified is True
```

- [ ] **Step 2: Run it to verify it fails**

Run: `pytest tests/test_ingest_thresholds.py -v`
Expected: FAIL — no module `scripts.ingest_thresholds`

- [ ] **Step 3: Write the script**

```python
#!/usr/bin/env python
"""Ingest CAIE grade thresholds into Postgres.

Rows come from ciegt.pooruli.com (one request per syllabus, ~1,354 rows for our
three subjects across ~50 sessions back to 2011). Every row is then checked
against the official Cambridge PDF for its session, which the run has already
downloaded for the option table — so verification costs no extra request.

Only grades the official document publishes survive. That check is not
optional politeness: ciegt reports F and G for 0606 in 216 of its 230 rows,
and Cambridge publishes neither, at component or at syllabus level. Ingesting
them would have Lemely award an F in Additional Mathematics that no Cambridge
document defines.

Sessions whose PDF is missing or unparseable are stored with ``verified=False``
and only the weaker "drop anything at or below zero raw marks" filter, so one
unreadable document does not cost us fifty readable ones.

Politeness: a descriptive User-Agent, sequential requests, and a pause between
them. This is one small site and one document host.
"""

from __future__ import annotations

import argparse
import sys
import time
import urllib.request
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

import sqlalchemy as sa
import structlog

from lemely.db.models.thresholds import ComponentThreshold, OptionThreshold
from lemely.db.session import get_sessionmaker
from lemely.io.ciegt import ComponentRow, fetch_rows, gt_pdf_url
from lemely.io.grade_boundaries import invalidate_reference_cache as invalidate_boundaries
from lemely.io.threshold_pdf import ParsedComponent, parse_threshold_pdf

if TYPE_CHECKING:
    from lemely.db.models.enums import SessionMonth

logger = structlog.get_logger(__name__)

DEFAULT_SUBJECTS = ("0580", "0606", "0625")
_USER_AGENT = (
    "Lemely-ingest/1.0 (+https://github.com/LemelyIG/Lemely; "
    "educational grade-boundary ingestion)"
)
_PAUSE_SECONDS = 2.0


@dataclass
class IngestReport:
    """What one run did, for the operator and for the logs."""

    components_written: int = 0
    components_verified: int = 0
    options_written: int = 0
    grades_dropped: int = 0
    documents_unreadable: int = 0


def verify_row(
    row: ComponentRow, parsed: list[ParsedComponent] | None
) -> tuple[dict[str, int], bool]:
    """Return ``(thresholds, verified)`` for one ciegt row.

    With a document: keep only grades it publishes for this component, taking
    the document's value wherever the two differ. Without one (missing PDF, or
    a pre-2014 watermark that defeats text extraction): drop only thresholds at
    or below zero raw marks, which is not a boundary any document publishes,
    and mark the row unverified.
    """
    if parsed is None:
        return {g: v for g, v in row.thresholds.items() if v > 0}, False

    official = next(
        (
            c
            for c in parsed
            if (c.paper_number, c.paper_variant) == (row.paper_number, row.paper_variant)
        ),
        None,
    )
    if official is None:
        # The document was readable but says nothing about this component.
        # Keeping the row unverified is honest; deleting it would lose coverage
        # over a parsing gap.
        return {g: v for g, v in row.thresholds.items() if v > 0}, False

    return dict(official.thresholds), True


def _fetch_pdf(url: str) -> bytes | None:
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
            return bytes(response.read())
    except OSError as exc:
        logger.info("threshold.pdf.unavailable", url=url, error=str(exc))
        return None


def ingest(
    subject_codes: list[str],
    *,
    session_factory: Callable[[], object] | None = None,
    fetch_pdf: Callable[[str], bytes | None] = _fetch_pdf,
) -> IngestReport:
    """Fetch, verify and upsert every threshold for ``subject_codes``."""
    report = IngestReport()
    sessionmaker = session_factory or get_sessionmaker()

    for subject_code in subject_codes:
        rows = fetch_rows(subject_code)
        time.sleep(_PAUSE_SECONDS)
        by_session: dict[tuple[SessionMonth, int], list[ComponentRow]] = {}
        for row in rows:
            by_session.setdefault((row.session_month, row.session_year), []).append(row)

        for (month, year), session_rows in sorted(by_session.items(), key=lambda kv: kv[0][1]):
            url = gt_pdf_url(subject_code, month, year)
            pdf = fetch_pdf(url)
            time.sleep(_PAUSE_SECONDS)
            components, options = parse_threshold_pdf(pdf) if pdf else ([], [])
            parsed = components or None
            if parsed is None:
                report.documents_unreadable += 1

            with sessionmaker() as session, session.begin():  # type: ignore[union-attr]
                for row in session_rows:
                    thresholds, verified = verify_row(row, parsed)
                    report.grades_dropped += len(row.thresholds) - len(thresholds)
                    report.components_written += 1
                    report.components_verified += int(verified)
                    session.execute(
                        sa.dialects.postgresql.insert(ComponentThreshold)
                        .values(
                            board="caie",
                            subject_code=row.subject_code,
                            session_month=row.session_month,
                            session_year=row.session_year,
                            paper_number=row.paper_number,
                            paper_variant=row.paper_variant,
                            max_mark=row.max_mark,
                            thresholds=thresholds,
                            verified=verified,
                            source_url=row.source_url,
                        )
                        .on_conflict_do_update(
                            constraint="uq_component_thresholds_identity",
                            set_={"thresholds": thresholds, "verified": verified,
                                  "max_mark": row.max_mark, "source_url": row.source_url},
                        )
                    )
                for option in options:
                    report.options_written += 1
                    session.execute(
                        sa.dialects.postgresql.insert(OptionThreshold)
                        .values(
                            board="caie",
                            subject_code=subject_code,
                            session_month=month,
                            session_year=year,
                            option_code=option.option_code,
                            component_numbers=option.component_numbers,
                            max_mark_after_weighting=option.max_mark_after_weighting,
                            thresholds=option.thresholds,
                            source_url=url,
                        )
                        .on_conflict_do_update(
                            constraint="uq_option_thresholds_identity",
                            set_={"thresholds": option.thresholds,
                                  "component_numbers": option.component_numbers,
                                  "max_mark_after_weighting": option.max_mark_after_weighting},
                        )
                    )

    # The stores cache per process and this run just changed what they cache.
    # Without this a long-lived process keeps serving pre-ingest boundaries,
    # which is a wrong grade rather than a stale page.
    invalidate_boundaries()
    logger.info("threshold.ingest.done", **vars(report))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subjects", nargs="*", default=list(DEFAULT_SUBJECTS))
    args = parser.parse_args()
    report = ingest(args.subjects)
    print(  # noqa: T201 - operator-facing CLI output
        f"components={report.components_written} verified={report.components_verified} "
        f"options={report.options_written} grades_dropped={report.grades_dropped} "
        f"unreadable_documents={report.documents_unreadable}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the tests**

Run: `pytest tests/test_ingest_thresholds.py -v`
Expected: 5 passed

- [ ] **Step 5: Run the real ingest and record what it did**

Run: `source .venv/bin/activate && python scripts/ingest_thresholds.py`
Expected: roughly `components=1354`, a high `verified` count, `options>0`, and a non-zero `grades_dropped` — the 0606 F/G removals plus the ≤0 entries. Record the actual numbers in the commit message; they are the evidence the verification did something.

- [ ] **Step 6: Delete the superseded script**

```bash
git rm scripts/ingest_grade_boundaries.py
```

Its PDF parsing lives on in `lemely/io/threshold_pdf.py`, which is the part worth keeping.

- [ ] **Step 7: Commit**

```bash
source .venv/bin/activate && pre-commit run --all-files
git add scripts/ingest_thresholds.py tests/test_ingest_thresholds.py
git commit -S -m "feat(io): ingest thresholds from ciegt, verified against the official PDFs"
```

---

### Task 13: `GradeBoundaryStore` onto Postgres

**Files:**
- Modify: `lemely/io/grade_boundaries.py`
- Delete: `lemely/data/grade_boundaries.json`, `lemely/data/grade_boundaries_provenance.json`
- Test: `tests/test_grade_boundaries.py` (adapt)

**Interfaces:**
- Produces: unchanged — `GradeBoundaryStore().resolve(metadata) -> tuple[dict[str, float], BoundarySource]`, plus `invalidate_reference_cache()`.

The fallback chain (`exact` → `subject_default` → `global_default`) is preserved exactly; only where the numbers come from changes. Percentages are computed from `raw / max_mark` at read time, because the table stores raw marks.

**The awarded-grade vocabulary needs no code.** `_grade_for` (`student.py:151`) already returns whichever grade keys the resolved boundary map contains, so an IGCSE Core paper tops out at C and A\* is unreachable — which is exactly what spec D7 requires, because Cambridge states A\* does not exist at component level. This task must not change that behaviour; it only changes where the map comes from.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_grade_boundaries_db.py
"""`GradeBoundaryStore` must keep its fallback chain after moving to Postgres.

`attempts.boundary_source` records which rung answered, so the three-way
distinction is a stored fact about every graded paper, not an implementation
detail free to change.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from lemely.core.schemas import ExamMetadata
from lemely.db.models.enums import SessionMonth
from lemely.db.models.thresholds import ComponentThreshold
from lemely.io.grade_boundaries import GradeBoundaryStore, invalidate_reference_cache

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker


def _seed(sm: sessionmaker[Session]) -> None:
    with sm.begin() as s:
        s.add(ComponentThreshold(
            subject_code="0625", session_month=SessionMonth.may_june, session_year=2024,
            paper_number=1, paper_variant=2, max_mark=40,
            thresholds={"C": 20, "D": 18, "E": 16}, verified=True,
            source_url="https://example.invalid/0625_s24_gt.pdf",
        ))


def test_an_exact_match_reports_itself_as_exact(migrated_sessionmaker: sessionmaker[Session]) -> None:
    invalidate_reference_cache()
    _seed(migrated_sessionmaker)
    store = GradeBoundaryStore(sessionmaker=migrated_sessionmaker)
    boundaries, source = store.resolve(
        ExamMetadata(subject_code="0625", session_month="May/June", session_year=2024,
                     paper_number=1, paper_variant=2)
    )
    assert source == "exact"
    # 20/40 → 50%. Raw marks are stored; the percentage is derived here.
    assert boundaries["C"] == 50.0


def test_an_unknown_paper_falls_back_to_the_subject_default(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    invalidate_reference_cache()
    _seed(migrated_sessionmaker)
    store = GradeBoundaryStore(sessionmaker=migrated_sessionmaker)
    _, source = store.resolve(
        ExamMetadata(subject_code="0625", session_month="May/June", session_year=1999,
                     paper_number=9, paper_variant=9)
    )
    assert source == "subject_default"


def test_an_unknown_subject_falls_back_to_the_global_default(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    invalidate_reference_cache()
    _seed(migrated_sessionmaker)
    store = GradeBoundaryStore(sessionmaker=migrated_sessionmaker)
    _, source = store.resolve(
        ExamMetadata(subject_code="9999", session_month="May/June", session_year=2024,
                     paper_number=1, paper_variant=1)
    )
    assert source == "global_default"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `pytest tests/test_grade_boundaries_db.py -v`
Expected: FAIL — `GradeBoundaryStore` takes no `sessionmaker` argument.

- [ ] **Step 3: Rewrite the store**

Keep `_make_key`, `_SESSION_CODE` and the `BoundarySource` literal exactly as they are. Replace the JSON load with a cached query that builds the same three structures:

```python
_lock = threading.Lock()
_cache: tuple[dict[str, dict[str, float]], dict[str, dict[str, float]], dict[str, float]] | None = None


def invalidate_reference_cache() -> None:
    """Drop the process cache. Called by the ingest path."""
    global _cache
    with _lock:
        _cache = None


def _percentages(thresholds: dict[str, int], max_mark: int) -> dict[str, float]:
    """Raw marks → percentages. Derived at read time, never stored, so every
    stored number stays one a human can check against the PDF."""
    return {grade: round((mark / max_mark) * 100.0, 2) for grade, mark in thresholds.items()}


def _load(session: Session) -> tuple[...]:
    exact: dict[str, dict[str, float]] = {}
    by_subject: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    everything: dict[str, list[float]] = defaultdict(list)
    for row in session.scalars(sa.select(ComponentThreshold)):
        pct = _percentages(row.thresholds, row.max_mark)
        code = _SESSION_CODE_BY_MONTH[row.session_month]
        key = f"{row.subject_code}_{code}{row.session_year % 100:02d}_p{row.paper_number}{row.paper_variant}"
        exact[key] = pct
        for grade, value in pct.items():
            by_subject[row.subject_code][grade].append(value)
            everything[grade].append(value)
    subject_defaults = {
        subject: {g: round(mean(v), 2) for g, v in grades.items()}
        for subject, grades in by_subject.items()
    }
    global_default = {g: round(mean(v), 2) for g, v in everything.items()}
    return exact, subject_defaults, global_default
```

`GradeBoundaryStore.__init__` takes `sessionmaker: sessionmaker[Session] | None = None`, defaulting to `get_sessionmaker()`; `resolve` keeps its exact current body, reading the three cached structures.

- [ ] **Step 4: Delete the JSON and confirm nothing reads it**

```bash
git rm lemely/data/grade_boundaries.json lemely/data/grade_boundaries_provenance.json
grep -rn "grade_boundaries.json\|grade_boundaries_provenance" lemely/ tests/ scripts/
```
Expected: no output from the grep.

- [ ] **Step 5: Run the affected suites**

Run: `pytest tests/test_grade_boundaries_db.py tests/test_web_student.py tests/test_review_repo.py -v`
Expected: all pass. `deps.py:65` wires this store into the student, parent, admin, review and grading paths, so a regression here is a regression in every grade the product reports.

- [ ] **Step 6: Commit**

```bash
source .venv/bin/activate && pre-commit run --all-files
git add lemely/io/grade_boundaries.py tests/test_grade_boundaries_db.py lemely/data
git commit -S -m "refactor(io): resolve grade boundaries from Postgres, retire the bundled JSON"
```

---

# Stage 4 — Grade vocabularies, and the end of hardcoded tables

### Task 14: Derive target vocabularies from the option thresholds

**Files:**
- Create: `lemely/db/threshold_repo.py`
- Modify: `lemely/web/routers/reference.py`, `lemely/web/deps.py`
- Test: `tests/test_threshold_repo.py`

**Interfaces:**
- Consumes: `OptionThreshold`, `SyllabusPaper`.
- Produces:
  `TargetVocabulary(subject_code: str, qualification_level: str | None, tier: str | None, grades: list[str])`
  `ThresholdService(sessionmaker).target_vocabularies() -> list[TargetVocabulary]`
  `get_threshold_service` dependency.

An option's tier is not read off its code letter — it is derived by looking its
component numbers up in `syllabus_papers`. `0580 AX = [11, 31]` maps to papers
1 and 3, both Core; `BX = [21, 41]` maps to papers 2 and 4, both Extended. That
uses our own catalogue rather than guessing a naming convention, and it is
correct for 0606, whose papers carry no tier at all.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_threshold_repo.py
"""Target grade vocabularies, derived from what Cambridge actually publishes.

The numbers below are transcribed from the real June 2024 documents. They are
the reason this is derived rather than declared: a generic per-qualification
rule would give 0580 Extended an F and a G it does not publish.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from lemely.db.models.academic import Subject
from lemely.db.models.catalogue import SyllabusPaper
from lemely.db.models.enums import ExamBoard, PaperTier, QualificationLevel, SessionMonth
from lemely.db.models.thresholds import OptionThreshold
from lemely.db.threshold_repo import ThresholdService

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker


def _paper(code: str, number: int, tier: PaperTier | None) -> SyllabusPaper:
    return SyllabusPaper(
        subject_code=code, paper_number=number, name=f"Paper {number}", tier=tier,
        duration_minutes=45, total_marks=40, practical=False,
        source_document="d.pdf", source_url="https://example.invalid/d.pdf",
        syllabus_version="2023-2025",
    )


def _option(code: str, option: str, components: list[int], thresholds: dict[str, int]) -> OptionThreshold:
    return OptionThreshold(
        subject_code=code, session_month=SessionMonth.may_june, session_year=2024,
        option_code=option, component_numbers=components, max_mark_after_weighting=200,
        thresholds=thresholds, source_url="https://example.invalid/gt.pdf",
    )


def _seed(sm: sessionmaker[Session]) -> None:
    with sm.begin() as s:
        s.add(Subject(code="0580", name="Mathematics", board=ExamBoard.caie, active=True,
                      qualification_level=QualificationLevel.igcse))
        s.add(Subject(code="0606", name="Additional Mathematics", board=ExamBoard.caie,
                      active=True, qualification_level=QualificationLevel.igcse))
        for number, tier in ((1, PaperTier.core), (2, PaperTier.extended),
                             (3, PaperTier.core), (4, PaperTier.extended)):
            s.add(_paper("0580", number, tier))
        s.add(_paper("0606", 1, None))
        s.add(_paper("0606", 2, None))
        # Real June 2024 rows.
        s.add(_option("0580", "AX", [11, 31], {"C": 77, "D": 63, "E": 50, "F": 36, "G": 22}))
        s.add(_option("0580", "BX", [21, 41], {"A*": 152, "A": 125, "B": 98, "C": 72, "D": 56, "E": 40}))
        s.add(_option("0606", "AX", [11, 21], {"A*": 132, "A": 105, "B": 76, "C": 47, "D": 35, "E": 23}))


def test_core_and_extended_get_different_vocabularies(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    _seed(migrated_sessionmaker)
    vocabularies = {
        (v.subject_code, v.tier): v.grades
        for v in ThresholdService(migrated_sessionmaker).target_vocabularies()
    }
    # Core caps at C — Cambridge publishes no A* or A for a Core option.
    assert vocabularies[("0580", "core")] == ["C", "D", "E", "F", "G", "U"]
    # Extended reaches A* but publishes no F/G for 0580.
    assert vocabularies[("0580", "extended")] == ["A*", "A", "B", "C", "D", "E", "U"]


def test_an_untiered_subject_yields_a_null_tier_vocabulary(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    _seed(migrated_sessionmaker)
    vocabularies = {
        (v.subject_code, v.tier): v.grades
        for v in ThresholdService(migrated_sessionmaker).target_vocabularies()
    }
    assert vocabularies[("0606", None)] == ["A*", "A", "B", "C", "D", "E", "U"]


def test_grades_come_back_in_descending_order_with_u_last(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    """A picker renders them in this order, and `gradeRank` indexes into it, so
    the order is contract rather than presentation."""
    _seed(migrated_sessionmaker)
    extended = next(
        v for v in ThresholdService(migrated_sessionmaker).target_vocabularies()
        if v.subject_code == "0580" and v.tier == "extended"
    )
    assert extended.grades[0] == "A*"
    assert extended.grades[-1] == "U"


def test_the_vocabulary_carries_the_subjects_qualification_level(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    _seed(migrated_sessionmaker)
    assert all(
        v.qualification_level == "igcse"
        for v in ThresholdService(migrated_sessionmaker).target_vocabularies()
    )
```

- [ ] **Step 2: Run it to verify it fails**

Run: `pytest tests/test_threshold_repo.py -v`
Expected: FAIL — no module `lemely.db.threshold_repo`

- [ ] **Step 3: Write the repo**

```python
# lemely/db/threshold_repo.py
"""Read side of the threshold tables, and the target vocabularies they imply.

A *target* grade is a syllabus-level aspiration, so its vocabulary comes from
``option_thresholds`` — the only table where A\\* appears, because Cambridge
states that "Grade A\\* does not exist at the level of an individual component".

An option's tier is derived by looking its component numbers up in
``syllabus_papers`` rather than by reading its code letter. ``0580 AX =
[11, 31]`` maps to papers 1 and 3, both Core; ``BX = [21, 41]`` maps to papers
2 and 4, both Extended. That uses the catalogue we already have instead of
trusting a naming convention, and it produces the right answer for 0606, whose
papers carry no tier at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import sqlalchemy as sa

from lemely.db.models.academic import Subject
from lemely.db.models.catalogue import SyllabusPaper
from lemely.db.models.thresholds import OptionThreshold

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker

#: Descending grade order, the order a picker renders and `gradeRank` indexes.
#: `U` is appended rather than published: no threshold table lists it, because
#: it is what a candidate gets when they clear none of the others.
_GRADE_ORDER = ("A*", "A", "B", "C", "D", "E", "F", "G")
_UNGRADED = "U"


@dataclass(frozen=True, slots=True)
class TargetVocabulary:
    """The grades a student may aim for in one subject at one tier."""

    subject_code: str
    qualification_level: str | None
    tier: str | None
    grades: list[str]


class ThresholdService:
    """Reads thresholds and derives the vocabularies the UI offers."""

    def __init__(self, sessionmaker: sessionmaker[Session]) -> None:
        self._sessionmaker = sessionmaker

    def target_vocabularies(self) -> list[TargetVocabulary]:
        """One vocabulary per ``(subject, tier)`` Cambridge publishes options for."""
        with self._sessionmaker() as session:
            subjects = {s.code: s for s in session.scalars(sa.select(Subject))}
            tier_by_paper = {
                (p.subject_code, p.paper_number): (p.tier.value if p.tier else None)
                for p in session.scalars(sa.select(SyllabusPaper))
            }
            options = session.scalars(sa.select(OptionThreshold)).all()

        grades_by_key: dict[tuple[str, str | None], set[str]] = {}
        for option in options:
            tiers = {
                tier_by_paper.get((option.subject_code, number // 10 or number))
                for number in option.component_numbers
            }
            tiers.discard(None)
            # Extended wins a mixed option: a candidate sitting any Extended
            # component is an Extended candidate.
            tier = "extended" if "extended" in tiers else ("core" if "core" in tiers else None)
            grades_by_key.setdefault((option.subject_code, tier), set()).update(option.thresholds)

        return [
            TargetVocabulary(
                subject_code=code,
                qualification_level=(
                    subjects[code].qualification_level.value
                    if code in subjects and subjects[code].qualification_level
                    else None
                ),
                tier=tier,
                grades=[g for g in _GRADE_ORDER if g in grades] + [_UNGRADED],
            )
            for (code, tier), grades in sorted(
                grades_by_key.items(), key=lambda kv: (kv[0][0], kv[0][1] or "")
            )
        ]
```

- [ ] **Step 4: Serve it**

Add `get_threshold_service` to `deps.py` beside `get_catalogue_service`, then in `reference.py` inject it and populate the field:

```python
        targetGradeVocabularies=[
            TargetGradeVocabularyDTO(
                subjectCode=v.subject_code,
                qualificationLevel=v.qualification_level,
                tier=v.tier,
                grades=v.grades,
            )
            for v in thresholds.target_vocabularies()
        ],
```

Add a route test to `tests/test_web_reference.py` asserting the field round-trips.

- [ ] **Step 5: Run the tests**

Run: `pytest tests/test_threshold_repo.py tests/test_web_reference.py -v`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
source .venv/bin/activate && pre-commit run --all-files
git add lemely/db/threshold_repo.py lemely/web/routers/reference.py lemely/web/deps.py tests/test_threshold_repo.py tests/test_web_reference.py
git commit -S -m "feat(web): derive target grade vocabularies from the option thresholds"
```

---

### Task 15: One `gradeRank`, and the end of six grade tables

**Files:**
- Create: `web/src/lib/grades.ts`, `web/tests/unit/grades.test.ts`
- Modify: `Quizzes.tsx`, `ClassRoster.tsx`, `AtRiskList.tsx`, `QuizBuilder.tsx`, `AtRiskList` helpers, `web/src/lib/types.ts`, `web/src/components/ui/grade-badge.tsx`, `SubjectsStep.tsx`

**Interfaces:**
- Produces: `gradeRank(grade: string | null | undefined, vocabulary: readonly string[]): number`.

The six copies are all `indexOf` sort keys. `indexOf` returns `-1` for anything unrecognised, which sorts an unknown grade **ahead of A\***. Core-tier papers genuinely award F and G — 234 of 350 boundary records carry them — so this is a live mis-ordering, not a hypothetical.

- [ ] **Step 1: Write the failing test**

```ts
// web/tests/unit/grades.test.ts
import { describe, expect, it } from "vitest"
import { gradeRank } from "@/lib/grades"

const IGCSE_EXTENDED = ["A*", "A", "B", "C", "D", "E", "F", "G", "U"]
const A_LEVEL = ["A*", "A", "B", "C", "D", "E", "U"]

describe("gradeRank", () => {
  it("ranks by position in the given vocabulary, best first", () => {
    expect(gradeRank("A*", IGCSE_EXTENDED)).toBe(0)
    expect(gradeRank("U", IGCSE_EXTENDED)).toBe(8)
  })

  it("sorts an unrecognised grade last, never first", () => {
    // The defect this function exists for. Four screens used
    // `GRADE_ORDER.indexOf(grade)` over a vocabulary without F or G, so a
    // Core-tier F scored -1 and sorted ahead of an A*. 234 of 350 boundary
    // records award F or G, so this was reachable, not theoretical.
    expect(gradeRank("F", A_LEVEL)).toBeGreaterThan(gradeRank("U", A_LEVEL))
  })

  it("sorts a null or missing grade last", () => {
    expect(gradeRank(null, A_LEVEL)).toBeGreaterThan(gradeRank("U", A_LEVEL))
    expect(gradeRank(undefined, A_LEVEL)).toBeGreaterThan(gradeRank("U", A_LEVEL))
  })

  it("orders a real mixed list correctly when sorted ascending", () => {
    const sorted = ["U", "F", "A*", "C"].sort((a, b) =>
      gradeRank(a, IGCSE_EXTENDED) - gradeRank(b, IGCSE_EXTENDED),
    )
    expect(sorted).toEqual(["A*", "C", "F", "U"])
  })

  it("returns the same rank for an empty vocabulary regardless of grade", () => {
    // While `/api/reference` is loading there is no vocabulary. Every grade
    // ranking equal keeps a table's order stable rather than scrambling it.
    expect(gradeRank("A*", [])).toBe(gradeRank("U", []))
  })
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd web && npm test -- grades`
Expected: FAIL — cannot resolve `@/lib/grades`

- [ ] **Step 3: Write it**

```ts
// web/src/lib/grades.ts
/**
 * Rank a grade within a served vocabulary. Lower is better.
 *
 * Replaces six copies of `GRADE_ORDER` that had drifted apart — four sort keys
 * (`Quizzes`, `ClassRoster`, `AtRiskList`, `onboardingData`), `GRADES` in
 * `QuizBuilder`, and the `Grade` union in `lib/types.ts`, with a seventh,
 * wider set in `grade-badge.tsx`.
 *
 * The behavioural fix is the fallback. Every one of those call sites used
 * `GRADE_ORDER.indexOf(grade)`, which returns `-1` for anything it does not
 * know — so a Core-tier F sorted *ahead of* an A*. Core papers genuinely award
 * F and G (234 of 350 boundary records carry them), so that was reachable.
 * Returning `vocabulary.length` puts an unknown grade last, which is the only
 * honest place for a grade the vocabulary cannot rank.
 */
export function gradeRank(
  grade: string | null | undefined,
  vocabulary: readonly string[],
): number {
  if (!grade) return vocabulary.length
  const index = vocabulary.indexOf(grade)
  return index === -1 ? vocabulary.length : index
}
```

- [ ] **Step 4: Delete every copy and repoint the call sites**

In `Quizzes.tsx:86`, `ClassRoster.tsx:68` and `AtRiskList.tsx:71`, delete the local `const GRADE_ORDER` and replace `GRADE_ORDER.indexOf(x)` with `gradeRank(x, vocabulary)`, where `vocabulary` comes from `useReference()` — these are teacher screens spanning subjects, so use the vocabulary for the subject in hand where one exists and `[]` while loading. Delete `GRADES` in `QuizBuilder.tsx:126` and render the served vocabulary. In `SubjectsStep.tsx` the target-grade `Select` already iterates `targetGrades(subject.code)` from Task 7.

`web/src/lib/types.ts:12`'s `Grade` union and `grade-badge.tsx:16`'s wider union both become `type Grade = string`, because the vocabulary is now data. `grade-badge.tsx`'s `A*|A|B → "top"` tone mapping stays — that is presentation, not a data table.

- [ ] **Step 5: Prove the tables are gone**

Run: `grep -rn 'GRADE_ORDER\|"A\*", "A", "B", "C", "D", "E"' web/src`
Expected: no output.

- [ ] **Step 6: Verify**

Run: `cd web && npm test && npm run typecheck && npm run lint`
Expected: all clean.

- [ ] **Step 7: Commit**

```bash
git add web/src/lib/grades.ts web/tests/unit/grades.test.ts web/src/lib/types.ts web/src/components/ui/grade-badge.tsx web/src/portals
git commit -S -m "fix(web): rank grades against the served vocabulary, sorting unknowns last"
```

---

### Task 16: The gate that keeps hardcoded data out

**Files:**
- Create: `web/tests/unit/noHardcodedReferenceData.test.ts`

**Interfaces:** none — this task adds a test and nothing else.

This repo's convention is that "a screen no list claims is a screen no gate reads" (`documentMeta.ts`). Without this test, the seventh `GRADE_ORDER` arrives unnoticed, exactly as the first six did.

- [ ] **Step 1: Write the gate**

```ts
// web/tests/unit/noHardcodedReferenceData.test.ts
import { readdirSync, readFileSync, statSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"

/*
 * The frontend must not declare data the backend owns.
 *
 * Six copies of the grade vocabulary drifted apart before `/api/reference`
 * existed, and they disagreed: four omitted F and G, which Core-tier papers
 * genuinely award. Nothing caught that, because a constant no list claims is a
 * constant no gate reads. This is that list.
 *
 * Add a pattern here whenever the backend takes ownership of a table. Do not
 * add an exemption for a new file — fetch the data instead.
 */

const ROOT = new URL("../../src", import.meta.url).pathname

/** Files allowed to mention a value, because they define the fetch or the test. */
const ALLOWED = new Set(["lib/referenceTypes.ts", "lib/reference.ts", "lib/hooks/useReferenceApi.ts"])

const FORBIDDEN: { name: string; pattern: RegExp }[] = [
  {
    name: "the grade vocabulary (served as targetGradeVocabularies)",
    pattern: /\[\s*"A\*"\s*,\s*"A"\s*,\s*"B"\s*,/,
  },
  {
    name: "qualification levels (served as qualificationLevels)",
    pattern: /"igcse"[\s\S]{0,80}"o_level"/,
  },
  {
    name: "session months (served as sessionMonths)",
    pattern: /"may_june"[\s\S]{0,80}"oct_nov"/,
  },
  {
    name: "difficulty bands (served as difficultyBands)",
    pattern: /"foundation"[\s\S]{0,60}"standard"[\s\S]{0,60}"challenge"/,
  },
  {
    name: "the subject catalogue (served as subjects)",
    pattern: /"0625"[\s\S]{0,120}"0580"/,
  },
]

function sourceFiles(dir: string, base = ""): string[] {
  const out: string[] = []
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry)
    const rel = base ? `${base}/${entry}` : entry
    if (statSync(full).isDirectory()) out.push(...sourceFiles(full, rel))
    else if (/\.tsx?$/.test(entry)) out.push(rel)
  }
  return out
}

describe("no hardcoded reference data in web/src", () => {
  const files = sourceFiles(ROOT)

  it("finds source files to scan", () => {
    expect(files.length).toBeGreaterThan(50)
  })

  for (const { name, pattern } of FORBIDDEN) {
    it(`does not redeclare ${name}`, () => {
      const offenders = files.filter(
        (rel) => !ALLOWED.has(rel) && pattern.test(readFileSync(join(ROOT, rel), "utf8")),
      )
      expect(offenders, `fetch this from /api/reference instead of declaring it`).toEqual([])
    })
  }
})
```

- [ ] **Step 2: Run it**

Run: `cd web && npm test -- noHardcodedReferenceData`
Expected: 6 passed. A failure names the offending file and the table it redeclared.

- [ ] **Step 3: Commit**

```bash
git add web/tests/unit/noHardcodedReferenceData.test.ts
git commit -S -m "test(web): fail the build when the frontend redeclares backend-owned data"
```

---

# Stage 5 — The student chooses their placement subject

### Task 17: A placement-choice step at the end of S-02

**Files:**
- Modify: `web/src/portals/student/screens/onboarding/onboardingData.ts`, `QuestionnaireStep.tsx`, `Onboarding.tsx`, `web/src/lib/hooks/usePlacementApi.ts`
- Test: `web/tests/unit/onboarding.test.ts`, `web/e2e/phase4-journey.spec.ts`

**Interfaces:**
- Consumes: `GET /api/placement/{subject_code}/availability`, which already exists and returns `PlacementAvailabilityDTO`.
- Produces: `QuestionnaireStepKind` gains `"placementChoice"`; `buildQuestionnaireSteps` appends one such step when the student enrolled in two or more subjects.

Ordering the catalogue by `code` (spec D3) would otherwise send a multi-subject student to 0580, which has no placement questions (`core/placement.py:75`) — the honest "unavailable" panel instead of the Physics test they get today. Asking removes the dependency on catalogue order entirely.

- [ ] **Step 1: Write the failing test**

```ts
describe("buildQuestionnaireSteps — placement choice", () => {
  it("appends a placement-choice step when the student enrolled in more than one subject", () => {
    const steps = buildQuestionnaireSteps(["0580", "0625"])
    expect(steps[steps.length - 1]).toEqual({ id: "placementChoice", kind: "placementChoice" })
  })

  it("does not ask when there is only one subject to choose from", () => {
    // A question with one possible answer is not a question.
    const steps = buildQuestionnaireSteps(["0625"])
    expect(steps.some((s) => s.kind === "placementChoice")).toBe(false)
  })

  it("does not ask when the student enrolled in nothing", () => {
    expect(buildQuestionnaireSteps([]).some((s) => s.kind === "placementChoice")).toBe(false)
  })

  it("keeps the confidence steps before the choice", () => {
    const steps = buildQuestionnaireSteps(["0580", "0625"])
    const lastConfidence = steps.map((s) => s.kind).lastIndexOf("confidence")
    const choice = steps.map((s) => s.kind).indexOf("placementChoice")
    expect(choice).toBeGreaterThan(lastConfidence)
  })
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd web && npm test -- onboarding`
Expected: FAIL — no `placementChoice` step is produced.

- [ ] **Step 3: Extend the step builder**

```ts
export type QuestionnaireStepKind =
  | "school"
  | "externalLessons"
  | "weeklyHours"
  | "gradeLevel"
  | "confidence"
  | "placementChoice"

/**
 * The ordered S-02 sequence: four scalar questions, one confidence step per
 * enrolled subject, then — only when there is a real choice to make — which
 * subject to be placed in.
 *
 * The choice step exists because catalogue order is `code` order, and 0580
 * sorts first while having no placement questions at all. Routing by position
 * would send a multi-subject student to an "unavailable" panel; asking them
 * removes the dependency on ordering rather than hiding it behind a different
 * sort. One enrolled subject means no question: there is nothing to choose.
 */
export function buildQuestionnaireSteps(subjectCodes: string[]): QuestionnaireStepDef[] {
  return [
    { id: "school", kind: "school" },
    { id: "externalLessons", kind: "externalLessons" },
    { id: "weeklyHours", kind: "weeklyHours" },
    { id: "gradeLevel", kind: "gradeLevel" },
    ...subjectCodes.map((subjectCode) => ({
      id: `confidence-${subjectCode}`,
      kind: "confidence" as const,
      subjectCode,
    })),
    ...(subjectCodes.length > 1
      ? [{ id: "placementChoice", kind: "placementChoice" as const }]
      : []),
  ]
}
```

- [ ] **Step 4: Render the step**

In `QuestionnaireStep.tsx`, add a `placementChoice` arm listing each enrolled subject with its availability from `usePlacementAvailability(code)`, and a "Skip for now" that resolves to `null`. A subject whose availability reports `available: false` renders its honest reason and is not selectable — the student sees *why* rather than picking a dead end.

In `Onboarding.tsx`, `handleFinish` uses the chosen code when the step ran, and falls back to `placementInviteSubject(Object.keys(drafts), reference?.subjects ?? [])` for the single-subject case.

- [ ] **Step 5: Extend the E2E journey**

In `web/e2e/phase4-journey.spec.ts`, the S-01 leg already ticks one subject; add a second so the choice step appears, then assert the student reaches S-03 for the subject they picked. Keep it in Playwright — this is exactly the component behaviour the Node unit suite cannot exercise.

- [ ] **Step 6: Verify**

Run: `cd web && npm test && npm run typecheck && npx playwright test e2e/phase4-journey.spec.ts`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add web/src/portals/student/screens/onboarding web/src/portals/student/screens/Onboarding.tsx web/tests/unit/onboarding.test.ts web/e2e/phase4-journey.spec.ts
git commit -S -m "feat(web): let the student choose which subject to be placed in"
```

---

---

### Task 18: Seeding and the E2E catalogue

**Files:**
- Modify: `lemely/db/seed.py`, `tests/test_seed.py`, `web/e2e/global-setup.ts`

**Interfaces:**
- Produces: `CATALOGUE_SUBJECTS` (replacing `DEMO_SUBJECTS`), `seed_reference_data(settings) -> int` unchanged in signature.

Sequenced last only to keep the earlier task numbers stable — it depends on
nothing after Task 2 and can be done any time after it.

Migration 0024 now inserts the catalogue, so the seeder is no longer the only
thing that puts rows there. It still exists for `make seed` against a database
someone has emptied, and it must not fight the migration: same rows, same
conflict handling.

- [ ] **Step 1: Update the seed test**

In `tests/test_seed.py`, rename every `DEMO_SUBJECTS` reference to
`CATALOGUE_SUBJECTS` and add:

```python
def test_catalogue_subjects_carry_their_qualification_level() -> None:
    """0580, 0606 and 0625 are IGCSE syllabuses. The level belongs to the
    subject (spec D10), not to a question the wizard asks the student."""
    assert {s.code for s in CATALOGUE_SUBJECTS} == {"0580", "0606", "0625"}
    assert all(s.qualification_level is QualificationLevel.igcse for s in CATALOGUE_SUBJECTS)


def test_reseeding_corrects_a_changed_name_rather_than_skipping_it() -> None:
    """Insert-if-absent was right when the seeder was the only writer. It is
    not now: the migration also writes these rows, so a seeder that skips an
    existing row can never correct one that drifted."""
    assert subjects_to_upsert({"0580"}) == list(CATALOGUE_SUBJECTS)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `pytest tests/test_seed.py -v`
Expected: FAIL — `cannot import name 'CATALOGUE_SUBJECTS'`

- [ ] **Step 3: Update the seeder**

Rename `DEMO_SUBJECTS` to `CATALOGUE_SUBJECTS` throughout `lemely/db/seed.py`
(it seeds reference data, not demo data — the module docstring already called
it reference data), give `SubjectSpec` a `qualification_level` field defaulting
to `QualificationLevel.igcse`, replace `subjects_to_insert` with
`subjects_to_upsert` returning every spec regardless of what exists, and make
`seed_reference_data` upsert on `code`, updating `name`,
`qualification_level` and `active`. Update `__all__`.

Call `lemely.io.paper_timing.invalidate_reference_cache()` and
`lemely.io.syllabus_topics.invalidate_reference_cache()` at the end of
`seed_reference_data`, for the reason the ingest does: a long-lived process
that seeded must not keep serving what it cached beforehand.

- [ ] **Step 4: Give the E2E stack a catalogue**

`web/e2e/global-setup.ts` must reach a database with migration 0024 applied, or
S-01 renders an empty subject list and `phase4-journey` and `signup` both fail
at the first step. Confirm the setup runs `alembic upgrade head` (or `make
db-migrate`) before the specs; add it if it does not.

- [ ] **Step 5: Verify**

Run: `pytest tests/test_seed.py -v && make seed && make seed`
Expected: tests pass; the second `make seed` reports zero rows added and changes
nothing — idempotence is the property that lets this run on every deploy.

- [ ] **Step 6: Commit**

```bash
source .venv/bin/activate && pre-commit run --all-files
git add lemely/db/seed.py tests/test_seed.py web/e2e/global-setup.ts
git commit -S -m "refactor(db): upsert the catalogue from the seeder, rename DEMO_SUBJECTS"
```

## Final verification

After Task 17, run the whole thing:

```bash
source .venv/bin/activate
pytest                                   # backend suite
cd web && npm test && npm run typecheck && npm run lint
make up && npx playwright test           # E2E against a seeded stack
```

Then confirm the two project-wide rules actually hold:

```bash
# No bundled reference JSON is read anywhere.
grep -rn "paper_timing.json\|syllabus_topics.json\|grade_boundaries.json" lemely/ scripts/ tests/

# No frontend file redeclares a backend-owned table.
cd web && npm test -- noHardcodedReferenceData
```

Both must come back clean.
