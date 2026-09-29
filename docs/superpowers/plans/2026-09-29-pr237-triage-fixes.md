# PR #237 Triage Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the next fix round on PR #237: merge `origin/develop`, close the two merge blockers (F3 two Alembic heads, F1 legacy `report_json`), the verdict-path arithmetic (F2, F4, F5, F6), the four cheap user-visible fixes (#255, #256, F7, #243) and the small follow-ups (F8, F9, #257, #259, #263, #266, #267, #268), as triaged in `/home/sico/.claude/jobs/33cebc31/tmp/triage/SUMMARY.md`.

**Architecture:** Every task is a small, tested change to an existing seam. The develop merge lands first and alone; every later task builds on the merged tree. F1 is tolerated on load by a one-key `mode="before"` validator rather than a data migration (Task 3 justifies this). F5 changes `lemely.core.point_groups.group_points` to a per-pool cap and F4/F6 make the verdict path consistent with it: the backstop recomputes the group-capped total over surviving ids instead of subtracting tariffs, and the coherence interval is clamped at `question.marks`. F2 adds a structural bound on every `Pow` of an `evaluate=False` parse before the real parse, and a factorial guard. F8 splits `check_pdf_content` into a per-page entry point the crop route uses for the one page it renders. #255 applies EXIF orientation at extraction and the crop route, and #256 replaces the pixel ceiling for image uploads with a decoded-bytes budget shared by upload, extraction and crop.

**Tech Stack:** Python 3.12–3.14, pydantic v2, SQLAlchemy 2 + Alembic, FastAPI, SymPy, Pillow 12.2, pypdfium2 5.11, PyMuPDF, structlog, pytest + unittest, ruff, mypy, pyright, import-linter, pre-commit; React + TypeScript + vitest for `web/`.

## Global Constraints

- Signed commits: `git commit -S`, conventional messages with scopes (e.g. `fix(io):`, `fix(core):`, `docs:`). Commit with `git commit -S -- <paths>`; never `git add -A`/`-a`/`.`, never `git stash`, never `git reset`. The merge commit in Task 1 is `git merge -S origin/develop`.
- Run `pre-commit run --files <changed files>` before each commit and fix failures without relying on autofix hiding them.
- Never run the full test suite locally (no bare `pytest`, no `make test`). Run only the touched/covering test files, as `PYTHONPATH=$PWD .venv/bin/python -m pytest <files> -q`.
- The repo is public: no real student scans in fixtures; build synthetic images/PDFs in tests.
- Do not push.
- For any change to marking logic, state whether the accuracy-harness fingerprint pin (`af7fa9cd0e2a`) moves; find how the fingerprint is computed and say so in the task.
- Each task lists which issues it closes so the PR body can say `Closes #N`.

Additional constraints carried over from the previous plan (`docs/superpowers/plans/2026-09-26-pr237-review-fixes.md`):

- Work in the worktree `/home/sico/Code/Lemely/.claude/worktrees/feat-ai-improvements`; every command below runs from that directory. The pre-commit invocation that works in this worktree is `PYTHONPATH=$PWD PATH="$PWD/.venv/bin:$PATH" pre-commit run --files <paths>`. The `PYTHONPATH=$PWD` prefix is mandatory on every python/pytest/pre-commit command: the shared venv's editable install points at another worktree.
- Local pyright failures of the exact form `"X" is not assignable to "X"` are a known shared-venv artefact; CI's `pyright lemely` is authoritative for those and only those.
- `file:line` anchors below are against the tree **after Task 1's merge commit** unless a task says "at 298f30c7". Where the merge shifts a line, search for the quoted code.
- TDD: every code task writes its failing test first, runs it and pastes the red assertion, then implements, then shows green.
- Layering (`pyproject.toml` `[tool.importlinter]`): `lemely.app` > `lemely.web` > `lemely.io` > `lemely.core`; `lemely.core` never imports `io`, `web` or `db`.
- No `TODO`, `test.skip`, stub tests or unimplemented branches. No new dependencies.

**How the harness fingerprint is computed (for every marking-logic task below).** `lemely/accuracy/harness.py::_build_run_manifest` (`:867-1034`) builds `fingerprint_raw` from `settings.gemini`'s per-task models, thinking levels and generation params, then appends `|equivalence_gate=True`, `|ecf_substitution=True`, `|reread_substitution=True` and `|arm=<arm>` only when set, and takes `hashlib.sha256(fingerprint_raw.encode()).hexdigest()[:12]`. It hashes **settings and flags, never code**, so no task in this plan moves the pin `af7fa9cd0e2a` (`tests/test_accuracy_harness.py:1586`, guarded by `test_flag_off_fingerprint_is_unchanged` at `:1631`). Every marking task still runs that test to prove it.

## Task map

| Task | Closes | Files (main) | Runs after |
|---|---|---|---|
| 1 | merge (#239, #240, #241, #246, #247 fixed on branch; #253 arrives from develop) | the 8 conflict paths | — (first, alone) |
| 2 | F3 | `lemely/db/migrations/versions/0043_merge_heads.py`, `tests/test_db_schema.py` | 1 |
| 3 | F1 | `lemely/core/schemas.py`, `tests/test_schemas_corrected_question.py`, `tests/test_teacher_paper_repo.py` | 2 |
| 4 | F2 (guards + killable parse worker) | `lemely/core/equivalence.py`, `tests/test_equivalence.py` | 3 |
| 5 | F5 | `lemely/core/point_groups.py`, `tests/test_question_points.py`, `tests/test_correction_ai.py` | 4 |
| 6 | F4 | `lemely/io/correction_ai.py`, `tests/test_correction_ai.py` | 5 |
| 7 | F6 | `lemely/io/correction_ai.py`, `tests/test_correction_ai.py` | 6 |
| 8 | F7 | `lemely/db/attempt_repo.py`, `tests/test_attempt_repo.py` | 7 |
| 9 | F8 (crop route drops the page cap; #269 becomes preview-only) | `lemely/io/scan_limits.py`, `lemely/web/routers/review.py`, `tests/test_scan_limits.py`, `tests/pdf_fakes.py`, `tests/test_web_review.py`, `tests/test_web_teacher.py` | 8 |
| 10 | F9 | `lemely/web/routers/review.py`, `lemely/db/review_repo.py` | 9 |
| 11 | #255 | `lemely/io/rasterise.py`, `lemely/web/routers/review.py`, `tests/test_rasterise.py`, `tests/test_web_review.py` | 10 |
| 12 | #256 (per-mode pixel cap) | `lemely/io/scan_limits.py`, `lemely/io/rasterise.py`, `lemely/web/routers/review.py`, `tests/test_scan_limits.py`, `tests/test_rasterise.py`, `tests/test_web_review.py` | 11 |
| 13 | #243 | `web/src/portals/marketing/dataHandling.ts`, `web/tests/unit/dataHandling.test.ts` | 12 |
| 14 | #257 | `tests/test_equivalence.py` | 13 |
| 15 | #259 | `lemely/web/deps.py`, `lemely/web/routers/teacher.py`, `tests/test_deps_marking_options.py`, `tests/test_web_teacher.py` | 14 |
| 16 | #263 | `lemely/accuracy/harness.py`, `lemely/app/cli.py`, `tests/test_accuracy_harness.py`, `tests/test_cli_review_rate_gate.py` | 15 |
| 17 | #266 | `lemely/io/question_gates.py`, `tests/test_question_generation.py` | 16 |
| 18 | #267 | `scripts/rasterise_handwritten_fixtures.py`, `tests/test_rasterise_handwritten_fixtures.py` | 17 |
| 19 | #268 | `tests/test_rasterise.py` | 18 |
| 20 | gate sweep | none | 19 |
| 21 | PR body | none (GitHub) | 20 |

Tasks that touch the same files (they run sequentially in the order above anyway): `lemely/web/routers/review.py` — 9, 10, 11, 12; `lemely/io/scan_limits.py` — 9, 12; `lemely/io/rasterise.py` — 11, 12; `tests/test_web_review.py` — 9, 11, 12; `lemely/io/correction_ai.py` — 6, 7; `tests/test_correction_ai.py` — 5, 6, 7; `tests/test_equivalence.py` — 4, 14; `tests/test_rasterise.py` — 11, 12, 19; `lemely/db/review_repo.py` — 1, 10; `lemely/db/attempt_repo.py` and `tests/test_attempt_repo.py` — 1, 8; `tests/test_scan_limits.py` — 9, 12.

Scratch files (probe outputs, conflict dumps) go under `/home/sico/.claude/jobs/33cebc31/tmp/plan5/`, never `/tmp`. The triage probes that the tests below reproduce are in `/home/sico/.claude/jobs/33cebc31/tmp/triage/` (`probe1_*.py`, `probe2.py`, `probe3_heads.py`, `probe_marking.py`, `probe7.py`, `probe8.py`, `be_probe_img.py`).

---
## Tier 1: merge blockers

### Task 1: Merge `origin/develop` (33d2c1e6) into `feat/ai-improvements`

**Closes:** nothing by itself; after this merge #239, #240, #241, #246, #247 (fixed on this branch) and #253 (fixed on develop by `d7a33623`) are all in one tree and close with the PR.

**Files:**
- Modify (conflict resolution only): `lemely/db/attempt_repo.py`, `lemely/db/models/ops.py`, `lemely/db/review_repo.py`, `lemely/db/teacher_paper_repo.py`, `scripts/seed_e2e.py`, `tests/test_attempt_repo.py`, `tests/test_authz_matrix_complete.py`, `web/src/portals/student/screens/PaperResult.tsx`
- Everything else auto-merges (see `/home/sico/.claude/jobs/33cebc31/tmp/triage/merge-tree.txt`).

**Interfaces:**
- Consumes: `origin/develop` at `33d2c1e68ac998110fd07046ca12784fae8159c3`; merge base `8e23ac2e`.
- Produces: the merged tree every later task anchors to. Known state after this task: Alembic has two heads (`0039_paper_soft_delete`, `0042_question_result_source_box`) and `tests/test_db_schema.py::test_migrations_have_a_single_head` fails until Task 2.

- [ ] **Step 1: Confirm the starting point**

Run: `git status --short --branch` and `git rev-parse HEAD origin/develop`
Expected: `## feat/ai-improvements...origin/feat/ai-improvements` with no file lines, then `298f30c7...` and `33d2c1e68ac998110fd07046ca12784fae8159c3`. Do **not** `git fetch`: the plan's anchors are against this exact develop SHA. If either SHA differs, stop and report.

- [ ] **Step 2: Start the merge**

Run: `git merge -S origin/develop`
Expected: `Automatic merge failed; fix conflicts and then commit the result.` with exactly these eight `CONFLICT (content)` lines: `lemely/db/attempt_repo.py`, `lemely/db/models/ops.py`, `lemely/db/review_repo.py`, `lemely/db/teacher_paper_repo.py`, `scripts/seed_e2e.py`, `tests/test_attempt_repo.py`, `tests/test_authz_matrix_complete.py`, `web/src/portals/student/screens/PaperResult.tsx`. Any other conflict means develop moved; stop and report.

- [ ] **Step 3: Resolve the four `lemely/db` conflicts (both sides are kept in every one)**

Every hunk is an import or a field added on each side. Keep both, in this order:

`lemely/db/attempt_repo.py` (one hunk, import block):
```python
from lemely.db.review_queue_rules import low_confidence_review_needed, review_reasons_for
from lemely.db.session import INCLUDE_DELETED
```

`lemely/db/models/ops.py` (one hunk in `ReviewQueueItem`): keep the branch's `is_audit` column with the `#:` comment lines above it exactly as on the branch, then develop's `withdrawn_at` column and docstring:
```python
    is_audit: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=False, server_default=sa.false()
    )
    withdrawn_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    """Set with ``status = withdrawn`` when the attempt was soft-deleted.

    Holds **exactly** the attempt's ``deleted_at``, which is what lets restore
    reopen precisely the items that deletion withdrew and no others
    (design 2026-09-22 §6).
    """
```

`lemely/db/review_repo.py` (one hunk, import block):
```python
from lemely.core.schemas import (
    AccuracyReport,
    CorrectedQuestion,
    ExamMetadata,
    SourceBox,
)
from lemely.db.models.attempts import Attempt, QuestionResult, Upload, WeaknessRecord
from lemely.db.models.deletion import ClassPaperExclusion
```

`lemely/db/teacher_paper_repo.py` (one hunk, import block):
```python
from lemely.db.review_queue_rules import review_reasons_for
from lemely.db.session import INCLUDE_DELETED
```

- [ ] **Step 4: Resolve `scripts/seed_e2e.py` (three hunks, all inside `accuracy_report_for_score`)**

Hunk 1, the signature: keep the branch's four keyword parameters and add develop's one after them:
```python
    matched_point_ids: list[str] | None = None,
    point_verdicts: list[PointVerdict] | None = None,
    point_notes: dict[str, str] | None = None,
    source_box: SourceBox | None = None,
    plagiarism_flagged: bool = False,
```
Hunk 2, the docstring: keep the branch's two paragraphs (the one starting ``matched_point_ids``/``point_verdicts``/``point_notes`` default to empty and the one starting ``source_box`` (task #72)), then develop's paragraph starting ``plagiarism_flagged`` (Task 18 e2e) after them.

Hunk 3, the `CorrectedQuestion(...)` construction: keep the branch's five lines and add develop's one:
```python
        marker_source="deterministic" if point_verdicts is None else "ai",
        matched_point_ids=matched_point_ids or [],
        point_verdicts=point_verdicts or [],
        point_notes=point_notes,
        source_box=source_box,
        plagiarism_flagged=plagiarism_flagged,
```

Then prove #241's onboarding calls survived. Run:
`grep -n "mark_onboarding_complete" scripts/seed_e2e.py`
Expected: among the lines, one each for `declining["userId"]`, `inactive["userId"]`, `control["userId"]` and `corrected["userId"]`. If any is missing, the merge dropped `a37df46c`; restore the call next to that account's creation.

- [ ] **Step 5: Resolve the two test conflicts**

`tests/test_attempt_repo.py`, hunk 1 (the `from lemely.db.attempt_repo import (...)` list): keep both names:
```python
from lemely.db.attempt_repo import (
    AttemptRepository,
    UploadDeletedError,
    _integrity_flagged,
    fill_correction_topics,
    is_marking_low_confidence,
)
```
Hunk 2 (module imports): keep both sides:
```python
from lemely.db.review_queue_rules import low_confidence_review_needed
from lemely.db.session import INCLUDE_DELETED
from lemely.io.correction_ai import (
    _BLANK_ANSWER_REVIEW_REASON,
    _DROPPED_ANSWER_REVIEW_REASON,
)
```
(ruff's isort hook may reorder; accept what pre-commit produces and re-stage.)

`tests/test_authz_matrix_complete.py`, one hunk, the section comment: the base said `STAFF (40)`, the branch added the crop route (41) and develop added three paper-deletion routes (43). Write:
```python
    # ── STAFF (44) ────────────────────
```
then verify by counting the `): STAFF,` entries between that comment and the next `# ── ` section comment (the file's own test asserts the route set, not the number; if the count is not 44, write the count you get).

- [ ] **Step 6: Resolve `web/src/portals/student/screens/PaperResult.tsx` (one import hunk)**

```tsx
import { confidenceSummaryOf, confidenceTierFor, markerScored } from "@/lib/markingConfidence"
import { deletionRefusal, isDeletionRefusal } from "@/lib/paperDeletion"
```
Both are used further down the file (`markerScored` at the `"not marked"` label, `deletionRefusal`/`isDeletionRefusal` in the 409 handler).

- [ ] **Step 7: Prove the resolved tree**

Run: `grep -rn "^<<<<<<<\|^>>>>>>>" lemely scripts tests web/src` → expected no output.

Run: `PYTHONPATH=$PWD PATH="$PWD/.venv/bin:$PATH" pre-commit run --files lemely/db/attempt_repo.py lemely/db/models/ops.py lemely/db/review_repo.py lemely/db/teacher_paper_repo.py scripts/seed_e2e.py tests/test_attempt_repo.py tests/test_authz_matrix_complete.py web/src/portals/student/screens/PaperResult.tsx` → every hook `Passed` or `Skipped`; if ruff reorders an import, keep its result.

Run: `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_attempt_repo.py tests/test_authz_matrix_complete.py tests/test_review_repo.py tests/test_teacher_paper_repo.py tests/test_seed_e2e.py tests/test_web_review.py tests/test_web_teacher.py tests/test_student_correct.py -q`
Expected: all passed (Postgres-backed files skip cleanly without a local Postgres on 54322; say so in the report).

Run: `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_db_schema.py -q -k single_head`
Expected: **1 failed** with `expected exactly one Alembic head, found 2: ['0039_paper_soft_delete', '0042_question_result_source_box']` (order may differ). This is F3, fixed by Task 2, and is the only allowed red.

Run, from `web/`: `npm run typecheck` then `npx vitest run tests/unit/markingConfidence.test.ts tests/unit/rtlSafety.test.ts tests/unit/persistAllowlist.test.ts tests/unit/failureCopy.test.ts`
Expected: typecheck clean; all four files pass (`persistAllowlist.test.ts` is develop's #253 test and proves the merged `main.tsx` carries `d7a33623`).

- [ ] **Step 8: Commit the merge**

```bash
git add lemely/db/attempt_repo.py lemely/db/models/ops.py lemely/db/review_repo.py lemely/db/teacher_paper_repo.py scripts/seed_e2e.py tests/test_attempt_repo.py tests/test_authz_matrix_complete.py web/src/portals/student/screens/PaperResult.tsx
git commit -S --no-edit
```
(`git commit -- <paths>` is refused during a merge; the merge commit takes git's default message `Merge remote-tracking branch 'origin/develop' into feat/ai-improvements`.) Then `git log --oneline -1` and `git status --short` → one merge commit, clean tree. Report the merge SHA; later tasks anchor to it.

---

### Task 2: F3 — `0043_merge_heads` joins `0039_paper_soft_delete` and `0042_question_result_source_box`

**Closes:** F3 (triage-report §3). No GitHub issue.

**Files:**
- Create: `lemely/db/migrations/versions/0043_merge_heads.py`
- Test: `tests/test_db_schema.py` (existing `test_migrations_have_a_single_head` at `:207`, plus one new test)

**Interfaces:**
- Consumes: Alembic revisions `0042_question_result_source_box` (branch head) and `0039_paper_soft_delete` (develop head). Precedent for a pure no-op join: `lemely/db/migrations/versions/0035_merge_parent_invites_review.py`.
- Produces: the single head `0043_merge_heads`, which `docker-entrypoint.sh`'s `alembic upgrade head` and CI's `alembic upgrade head` (`.github/workflows/ci.yml:80`) need.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_db_schema.py` directly after `test_migrations_have_a_single_head`:

```python
def test_0043_merge_heads_joins_the_develop_and_branch_chains() -> None:
    """Triage F3 (2026-09-29): ``feat/ai-improvements`` consumed
    ``0038_point_group_key`` with ``0039_merge_heads`` while develop grew
    ``0039_paper_soft_delete`` on the same parent, so the merged tree had two
    heads. ``0043_merge_heads`` is the pure no-op join (``0035`` precedent):
    ``0039_paper_soft_delete`` only ADDs enum values, columns and a table, and
    no branch migration touches ``reviewstatus``/``notificationtype``, so the
    two chains are order-independent.
    """
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    script_dir = ScriptDirectory.from_config(Config("alembic.ini"))
    revision = script_dir.get_revision("0043_merge_heads")
    assert set(revision.down_revision) == {
        "0042_question_result_source_box",
        "0039_paper_soft_delete",
    }
    assert script_dir.get_heads() == ["0043_merge_heads"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_db_schema.py -q -k "single_head or 0043"`
Expected: 2 failed — `expected exactly one Alembic head, found 2` and `alembic.script.revision.ResolutionError: No such revision or branch '0043_merge_heads'`.

- [ ] **Step 3: Create the migration**

`lemely/db/migrations/versions/0043_merge_heads.py`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_db_schema.py -q`
Expected: all passed (the Postgres-backed tests in that file skip without a local server; the two head tests are hermetic).

Run: `PYTHONPATH=$PWD PATH="$PWD/.venv/bin:$PATH" alembic heads`
Expected: exactly one line, `0043_merge_heads (head)`.

If a local Postgres is reachable on 54322, also run `PYTHONPATH=$PWD PATH="$PWD/.venv/bin:$PATH" alembic upgrade head` and expect it to end at `0043_merge_heads`; otherwise say CI's `alembic upgrade head` step covers it.

- [ ] **Step 5: Commit**

```bash
PYTHONPATH=$PWD PATH="$PWD/.venv/bin:$PATH" pre-commit run --files lemely/db/migrations/versions/0043_merge_heads.py tests/test_db_schema.py
git add lemely/db/migrations/versions/0043_merge_heads.py tests/test_db_schema.py
git commit -S -m "fix(db): join the two Alembic heads left by the develop merge" -- lemely/db/migrations/versions/0043_merge_heads.py tests/test_db_schema.py
```

---

### Task 3: F1 — stored `report_json` carrying the removed `ai_detection_flagged` key must load

**Closes:** F1 (triage-report §1). No GitHub issue.

**Files:**
- Modify: `lemely/core/schemas.py` (class `CorrectedQuestion`, `:305`; add a validator before the existing `@model_validator(mode="after")` at `:443`)
- Modify: `lemely/db/migrations/versions/0037_remove_ai_detection.py:72-83` (one sentence in the docstring paragraph that says `report_json` is not rewritten)
- Test: `tests/test_schemas_corrected_question.py`, `tests/test_teacher_paper_repo.py`

**Interfaces:**
- Consumes: `StrictModel` (`extra="forbid"`, `lemely/core/schemas.py:32`); the two loaders `AccuracyReport.model_validate(row.report_json)` in `lemely/db/teacher_paper_repo.py` (`_snapshot`) and `lemely/db/review_repo.py` (`_console_report`).
- Produces: `CorrectedQuestion` accepts and discards exactly the one legacy key `ai_detection_flagged`; every other unknown key stays `extra_forbidden`.

**Decision: tolerate on load, not a data migration.** Reasons, to be quoted in the commit body:
1. The value is meaningless by F4's own ruling (`0037_remove_ai_detection` and `0039_merge_heads` document that the detector's flags are "not evidence anybody should act on"), so nothing is lost by ignoring the key; a migration would spend a table-wide `jsonb` rewrite inside `alembic upgrade head` at container start to delete a key nobody reads.
2. A migration only reaches `teacher_papers.report_json`. The same `AccuracyReport` JSON shape is written by `model_dump(mode="json")` to the CLI's output dir, to accuracy result archives and to any backup restored after the migration ran; a `mode="before"` validator makes every reader tolerant at once.
3. It keeps `extra="forbid"` for everything else: the allowance is one named key, with a test that a second unknown key is still rejected, so the wire contract does not loosen.
4. Rows are rewritten to the current shape the next time a paper is regraded, so the legacy key ages out on its own.

- [ ] **Step 1: Write the failing unit tests**

Append to `tests/test_schemas_corrected_question.py`:

```python
#: A ``teacher_papers.report_json`` exactly as develop wrote it before ``1094cfde``
#: removed ``CorrectedQuestion.ai_detection_flagged`` (triage probe
#: ``probe1_make.py``, 2026-09-29): ``model_dump(mode="json")`` emits defaults,
#: so EVERY stored report carries the key.
_LEGACY_REPORT = {
    "correction": {
        "metadata": {
            "subject_code": "9999",
            "paper_number": 1,
            "paper_variant": 1,
            "session_month": "May/June",
            "session_year": 2020,
            "source_document": None,
        },
        "questions": [
            {
                "question_id": "1a",
                "awarded_marks": 1,
                "maximum_marks": 2,
                "confidence": "high",
                "confidence_score": 0.9,
                "needs_teacher_review": False,
                "student_answer": None,
                "expected_answer": None,
                "topic": None,
                "review_reason": None,
                "marker_source": "ai",
                "feedback": None,
                "matched_point_ids": [],
                "plagiarism_flagged": False,
                "ai_detection_flagged": False,
                "extraction_confidence": None,
                "rationale": None,
                "point_notes": None,
            }
        ],
        "awarded_marks": 1,
        "maximum_marks": 2,
        "needs_teacher_review": False,
    },
    "weaknesses": {"weak_areas": [], "needs_teacher_review": False},
    "grade_prediction": {
        "awarded_marks": 1,
        "maximum_marks": 2,
        "percentage": 50.0,
        "grade": "U",
        "confidence": "high",
        "needs_teacher_review": False,
        "boundary_source": "global_default",
    },
}


def test_a_report_stored_before_the_ai_detection_removal_still_loads() -> None:
    """Triage F1: ``StrictModel`` is ``extra="forbid"`` and ``1094cfde`` deleted
    the field, so ``AccuracyReport.model_validate`` on any pre-PR
    ``report_json`` raised ``extra_forbidden`` -- a 500 on the teacher paper
    list (``teacher_paper_repo._snapshot``) and a silently dropped report on
    console review items (``review_repo._console_report``)."""
    import copy

    from lemely.core.schemas import AccuracyReport

    report = AccuracyReport.model_validate(copy.deepcopy(_LEGACY_REPORT))

    question = report.correction.questions[0]
    assert question.awarded_marks == 1
    assert "ai_detection_flagged" not in question.model_dump()


def test_the_legacy_key_is_the_only_unknown_key_tolerated() -> None:
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="ai_detection_score"):
        _question(ai_detection_score=0.9)


def test_the_before_validator_does_not_mutate_the_caller_dict() -> None:
    """A loader that re-reads the same dict (``review_repo`` parses a paper's
    report once and threads it through) must not see it change under it."""
    stored = {
        "question_id": "1a",
        "awarded_marks": 2,
        "maximum_marks": 3,
        "confidence": ConfidenceBand.HIGH,
        "confidence_score": 0.95,
        "needs_teacher_review": False,
        "ai_detection_flagged": True,
    }
    CorrectedQuestion.model_validate(stored)
    assert stored["ai_detection_flagged"] is True
```

- [ ] **Step 2: Run the unit tests to verify they fail**

Run: `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_schemas_corrected_question.py -q`
Expected: 2 failed, the rest passed. `test_a_report_stored_before_the_ai_detection_removal_still_loads` fails with `pydantic_core._pydantic_core.ValidationError: 1 validation error for AccuracyReport correction.questions.0.ai_detection_flagged Extra inputs are not permitted [type=extra_forbidden ...]` (the probe's exact error); `test_the_before_validator_does_not_mutate_the_caller_dict` fails with the same `extra_forbidden`. `test_the_legacy_key_is_the_only_unknown_key_tolerated` already passes.

- [ ] **Step 3: Write the failing repository test**

Append to `tests/test_teacher_paper_repo.py`:

```python
def test_a_report_stored_before_the_ai_detection_removal_still_lists(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """Triage F1: one pre-PR row must not 500 the whole teacher paper list.

    ``repo.finish`` writes the CURRENT shape, so the legacy key is injected
    with a raw UPDATE, exactly where develop's ``model_dump(mode="json")`` put
    it: on every question of ``correction.questions``.
    """
    import copy

    repo = _repo(pg_sessionmaker)
    owner = _user(pg_sessionmaker, Role.teacher)
    pid = _paper(repo, owner)
    repo.claim_run(pid)
    repo.finish(pid, _report())

    with pg_sessionmaker.begin() as s:
        stored = s.get(TeacherPaper, pid)
        assert stored is not None and stored.report_json is not None
        legacy = copy.deepcopy(stored.report_json)
        for question in legacy["correction"]["questions"]:
            question["ai_detection_flagged"] = False
        s.execute(sa.update(TeacherPaper).where(TeacherPaper.id == pid).values(report_json=legacy))

    rows = repo.list_visible(viewer_id=owner, viewer_role=Role.teacher)
    assert [r.id for r in rows] == [pid]
    assert rows[0].report is not None and rows[0].report.correction.awarded_marks == 7
    row = repo.get_visible(pid, viewer_id=owner, viewer_role=Role.teacher)
    assert row is not None and row.report is not None
    assert "ai_detection_flagged" not in row.report.correction.questions[0].model_dump()
```

Run: `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_teacher_paper_repo.py -q -k ai_detection_removal`
Expected with a local Postgres on 54322: FAIL with `pydantic_core._pydantic_core.ValidationError ... extra_forbidden` raised from `list_visible` (the uncaught 500 path). Without Postgres: `1 skipped`; note that CI runs it.

- [ ] **Step 4: Add the validator**

In `lemely/core/schemas.py`, inside `class CorrectedQuestion(StrictModel)`, immediately before the first `@model_validator(mode="after")` (the one at `:443`), add:

```python
    @model_validator(mode="before")
    @classmethod
    def _drop_removed_ai_detection_flag(cls, data: object) -> object:
        """Accept a ``report_json`` written before ``1094cfde`` removed
        ``ai_detection_flagged`` (triage F1, 2026-09-29).

        ``model_dump(mode="json")`` emitted the field's default on every
        stored report, and ``0037_remove_ai_detection`` deliberately did not
        rewrite ``teacher_papers.report_json``; with ``extra="forbid"`` every
        pre-PR row then failed to load. The one legacy key is discarded here
        -- its value is not evidence anybody should act on, per F4's own
        ruling -- and every OTHER unknown key stays forbidden. The caller's
        dict is copied, not mutated: ``review_repo`` parses a paper's report
        once and threads the same dict through several rows.
        """
        if isinstance(data, dict) and "ai_detection_flagged" in data:
            return {key: value for key, value in data.items() if key != "ai_detection_flagged"}
        return data
```

- [ ] **Step 5: Correct the migration docstring**

In `lemely/db/migrations/versions/0037_remove_ai_detection.py`, in the docstring paragraph (around `:72-83`) that states the migration does not rewrite `teacher_papers.report_json`, append one sentence to that paragraph:

```
    Stored reports that still carry the key load anyway:
    ``CorrectedQuestion._drop_removed_ai_detection_flag`` (``lemely/core/
    schemas.py``) discards exactly that key on the way in (triage F1).
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_schemas_corrected_question.py tests/test_schemas.py tests/test_teacher_paper_repo.py tests/test_review_repo.py tests/test_migration_0037_remove_ai_detection.py -q`
Expected: all passed (Postgres-backed files may skip locally).

Also re-run the triage probe against the fixed code to close the loop:
Run: `PYTHONPATH=$PWD .venv/bin/python /home/sico/.claude/jobs/33cebc31/tmp/triage/probe1_load.py /home/sico/.claude/jobs/33cebc31/tmp/triage/probe1_develop_report.json`
Expected: last line `VALIDATES OK`.

- [ ] **Step 7: Commit**

```bash
PYTHONPATH=$PWD PATH="$PWD/.venv/bin:$PATH" pre-commit run --files lemely/core/schemas.py lemely/db/migrations/versions/0037_remove_ai_detection.py tests/test_schemas_corrected_question.py tests/test_teacher_paper_repo.py
git add lemely/core/schemas.py lemely/db/migrations/versions/0037_remove_ai_detection.py tests/test_schemas_corrected_question.py tests/test_teacher_paper_repo.py
git commit -S -m "fix(core): load stored reports that still carry ai_detection_flagged" -- lemely/core/schemas.py lemely/db/migrations/versions/0037_remove_ai_detection.py tests/test_schemas_corrected_question.py tests/test_teacher_paper_repo.py
```
Put the four-point "tolerate on load, not a data migration" justification above in the commit body.

---
## Tier 2: equivalence and the verdict path (all behind `equivalence_gate`, default off)

### Task 4: F2 — computed and factorial exponents are refused before any big-int work, and a killable parse worker backstops whatever slips past

**Closes:** F2 (triage-report §2). No GitHub issue.

**Files:**
- Modify: `lemely/core/equivalence.py` (`_MAX_EXPONENT_VALUE` block at `:122`; `_looks_like_prose_or_unsafe` at `:417-430`; `_has_unsafe_exponent` at `:433-442`; `_run_bounded` docstring at `:482-506`; `parse_expr_safe` at `:528-583`; new `_ParseWorker` class and `_parse_worker_main`)
- Test: `tests/test_equivalence.py` (the `parse_expr_safe edge cases` section at `:2290-2340`)

**Interfaces:**
- Consumes: `sympy.Pow`, `sympy.postorder_traversal`, `parse_expr(..., evaluate=False)`, the existing `_TRANSFORMATIONS`/`_UNIT_LOCAL_DICT`; stdlib `multiprocessing` (`get_context("spawn")`, `Pipe`, `Process`), `resource.setrlimit(RLIMIT_AS)`, `threading.Lock`. No new dependencies.
- Produces: `equivalence._MAX_POW_RESULT_BITS: int = 1_000_000`, `equivalence._MAX_FACTORIAL_OPERAND: int = 1000`, `equivalence._has_unsafe_factorial(text: str) -> bool`, `equivalence._pow_would_explode(node: sympy.Pow) -> bool`, `equivalence._PARSE_WORKER_MEMORY_BYTES: int = 512 * 1024 * 1024`, `equivalence._parse_worker_main(conn, memory_limit: int) -> None` (child entry point), `equivalence._ParseWorker` with `.parse(text: str, timeout: float) -> sympy.Expr | None`, `.pid() -> int | None`, `.shutdown() -> None`, and the module singleton `equivalence._PARSE_WORKER`. `parse_expr_safe`'s signature and every existing verdict are unchanged.

**What the probes showed (2026-09-29, this venv).** `2^(999*999*999)` passes both regexes (`_EXPONENT_VALUE_RE` reads only `999`; `_EXPONENT_TOWER_RE` needs a second operator) and `parse_expr_safe(timeout=1.0)` returned an `Integer` of 997,003,000 bits after 3.79 s while a heartbeat thread stalled 3.83 s: the GIL was held, the whole process froze. A second bypass in the same family: `2^(999!)` (`factorial_notation` is in SymPy's `standard_transformations`) passes both regexes and did not return within 30 s. `parse_expr(..., evaluate=False)` gives `Pow(Integer(2), Mul(Integer(999), Integer(999), Integer(999)))` and `Pow(Integer(2), Integer(<2565 digits>))` respectively, i.e. the exponent is inspectable before anything is computed.

**Design.** Four layers, cheapest first: (1) the existing regexes; (2) a textual factorial guard, because `9999999!` hangs *parsing* itself even with `evaluate=False`; (3) a structural bound in the parent: parse with `evaluate=False` (builds a tree and evaluates nothing but whitelisted function calls and textually-bounded factorials), walk every `Pow` in post-order, substitute 1 for free symbols, refuse when the exponent's magnitude exceeds `_MAX_EXPONENT_VALUE` or `bits(base) * exponent` exceeds `_MAX_POW_RESULT_BITS`; (4) **the backstop**: the `evaluate=True` parse — the only step that can do big-integer work — runs in a killable child process with a wall-clock timeout and an address-space limit. The guards are what make the backstop rarely fire; the backstop is what makes a guard gap survivable.

**Backstop decisions (user decision 3, 2026-09-29):**
- *Reusable worker, not a process per call.* Measured in this venv: a spawn start (interpreter + `sympy` import) costs 0.17–0.23 s; a warm call through the worker costs a median 0.3–0.6 ms (max 1.6 ms once warm; the very first parse after a start is up to ~150–190 ms while SymPy's parser warms). A fresh process per call would be 300–700× the parse itself, so one lazily-started worker is kept alive and reused; after a kill it is respawned on the next call (measured 0.18–0.19 s). One worker per parent process, guarded by a lock: calls are serialised, so the worst contention a caller sees is one timeout (1 s default) plus one respawn.
- *What the parent returns.* `None` from `parse_expr_safe` in every failure mode — timeout (child killed and joined), `MemoryError` in the child (child reports it and stays alive), child crash or broken pipe (killed, joined, respawned lazily), parse exception in the child (`SyntaxError`, `TypeError`, `ValueError`, `AttributeError`, `RecursionError`, `SympifyError`: reported, `None`). That is exactly what today's `_run_bounded` timeout and `except` clause give, so downstream `equivalent(...)` still says `UNPARSEABLE` and the marking loop never sees an exception.
- *Memory limit.* `resource.setrlimit(RLIMIT_AS, 512 MiB)` in the child on POSIX (skipped, with the timeout as the only bound, where `resource` is unavailable or the call is refused). Measured: the child's address space after importing SymPy is ~75 MB, so ordinary parses have ample room; under the limit `2**999999999` (a 125 MB integer) raised `MemoryError` after 1.8 s and the child stayed alive, and a 4 GB-integer input likewise returned `None` in 1.7 s. 512 MiB keeps the worst case well inside a 1 GiB Cloud Run worker even before the timeout fires.
- *Web server and pytest.* The `spawn` start method, never `fork`: FastAPI runs sync routes on a thread pool and forking a threaded process is unsafe; `spawn` also behaves the same on macOS. The child imports `lemely.core.equivalence` by qualified name (so `PYTHONPATH=$PWD` must be set for tests, as it already must be). The worker records its owner pid: a pre-forked server (gunicorn `--preload`) or a test harness that forks sees a foreign pid and starts its own child rather than sharing a pipe across processes. The child is `daemon=True`, so `multiprocessing`'s atexit hook terminates it at interpreter exit and no child outlives pytest or a server worker; `shutdown()` exists for tests that want to prove that explicitly.
- *`_run_bounded` is kept for `simplify` and the numeric fallback and replaced for parsing.* Those two steps are pure-Python SymPy loops that release the GIL between bytecodes, which is why their thread timeouts demonstrably return on time (`test_slow_simplify_falls_back_to_numeric_within_budget` measures 2.48 s against a 2.0 s + 0.5 s budget). Parsing is the one step where a C-level `int.__pow__` can hold the GIL for seconds, so it is the one step moved to a process. `_run_bounded`'s docstring says which is which.

**Measured overhead (this venv, `probe_subprocess.py` in the scratch dir):** cold start 0.17–0.23 s once per parent process; respawn after a kill 0.18–0.19 s; warm per-call median 0.30–0.58 ms for `2+2`, `3.0×10^8`, `0.5mv²`, `(x+1)^2 - x^2` (the in-process parse of the same inputs is 0.5–1 ms, so the pipe round-trip is within noise of the parse itself); timeout case `2**(999*999*999)` with `timeout=1.0`: `None` after 1.01 s with the parent's 50 ms heartbeat thread never delayed beyond 0.050 s (against a 3.83 s stall in-process); no child alive after the kill (`os.kill(pid, 0)` raises, `active_children()` empty).

**Fingerprint:** unchanged (it hashes settings; see the Global Constraints note). Prove it in Step 9.

- [ ] **Step 1: Write the failing guard tests**

In `tests/test_equivalence.py`, extend the `test_parse_expr_safe_rejects_dangerous_constructs` parametrisation (`:2308-2325`) by adding, after `"2**3**4"` and its id `"exponent-tower-double-star"`:

```python
        "2^(999*999*999)",
        "2^(10*10*10*10*10*10*10*10*10)",
        "(2+x-x)^(999*999*999)",
        "(10^300*10^300*10^300*10^300)^999",
        "2^(999!)",
        "(999!)!",
        "9999999!",
```
with ids:
```python
        "computed-exponent",
        "computed-exponent-products",
        "computed-exponent-symbolic-base",
        "result-too-many-bits",
        "factorial-exponent",
        "factorial-of-parenthesised",
        "factorial-too-large",
```

Then add, directly after that test:

```python
@pytest.mark.parametrize(
    "text",
    ["2^(999*999*999)", "2^(10*10*10*10*10*10*10*10*10)", "(2+x-x)^(999*999*999)"],
    ids=["computed-exponent", "computed-exponent-products", "computed-exponent-symbolic-base"],
)
def test_computed_exponents_are_refused_before_any_big_int_work(text: str) -> None:
    """Triage F2 (2026-09-29): ``2^(999*999*999)`` used to pass both regexes
    and return a 997,003,000-bit Integer after 3.79 s, during which a
    heartbeat thread stalled 3.83 s -- the GIL was held, so ``_run_bounded``'s
    timeout could not have helped. The refusal must come from the pre-parse
    guards, i.e. in milliseconds, before the parse worker is even asked."""
    started = time.monotonic()
    assert parse_expr_safe(text, timeout=1.0) is None
    assert time.monotonic() - started < 0.5


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2^(1/2)", sympy.sqrt(2)),
        ("10^(-3)", sympy.Rational(1, 1000)),
        ("2^(3*4)", sympy.Integer(4096)),
        ("5!", sympy.Integer(120)),
        ("2^999", sympy.Integer(2) ** 999),
    ],
    ids=["fractional-exponent", "negative-exponent", "small-computed-exponent", "small-factorial", "largest-literal"],
)
def test_bounded_exponents_still_parse(text: str, expected: sympy.Expr) -> None:
    assert parse_expr_safe(text) == expected


def test_symbolic_exponents_still_parse() -> None:
    x, n = sympy.symbols("x n")
    assert parse_expr_safe("x^(n+1)") == x ** (n + 1)
```

- [ ] **Step 2: Run the guard tests to verify the new cases fail (keep the factorial cases out of the red run: they hang)**

Run: `timeout 60 .venv/bin/python -m pytest tests/test_equivalence.py -q -k "computed_exponents or (rejects_dangerous_constructs and (computed-exponent or result-too-many-bits)) or bounded_exponents or symbolic_exponents"` with `PYTHONPATH=$PWD` in the environment.
Expected: the three `computed_exponents_are_refused` cases and the four `rejects_dangerous_constructs[computed-...|result-too-many-bits]` cases FAIL (`assert <Integer> is None` after roughly 3-4 s each, or the elapsed assertion); `bounded_exponents` and `symbolic_exponents` pass. Do **not** run the `factorial-exponent`, `factorial-of-parenthesised` or `factorial-too-large` ids before the fix: `2^(999!)` does not return.

- [ ] **Step 3: Add the constants and the factorial guard**

In `lemely/core/equivalence.py`, after `_MAX_EXPONENT_VALUE = 1000` (`:122`) add:

```python
#: Triage F2 (2026-09-29): the exponent regexes read literals, so a COMPUTED
#: exponent (`2^(999*999*999)`, `2^(999!)`) slipped past them and SymPy then
#: built the integer -- 997,003,000 bits in 3.8 s with the GIL held, so the
#: whole process froze and `_run_bounded`'s timeout was moot. The structural
#: bound in `_pow_would_explode` refuses any power whose RESULT would exceed
#: this many bits (~300,000 decimal digits: no CAIE answer is near it), on top
#: of the per-exponent literal cap above.
_MAX_POW_RESULT_BITS = 1_000_000

#: `factorial_notation` is one of SymPy's `standard_transformations`, and a
#: factorial is computed at PARSE time even under `evaluate=False`, so it must
#: be bounded textually, before parsing: `9999999!` hangs the parser. `1000!`
#: is a 2,568-digit integer, cheap; anything larger, or a factorial of a
#: parenthesised expression (`(999!)!`), is refused.
_MAX_FACTORIAL_OPERAND = 1000
_FACTORIAL_RE = re.compile(r"(\)|\d+)\s*!")

#: Address-space limit for the parse worker (see `_ParseWorker`). Measured:
#: the child's VmSize after importing SymPy is ~75 MB; under this limit
#: `2**999999999` (a 125 MB integer) raises MemoryError in 1.8 s and the
#: child survives. Small enough that the worst case fits a 1 GiB worker.
_PARSE_WORKER_MEMORY_BYTES = 512 * 1024 * 1024
```

After `_has_unsafe_exponent` (`:433-442`) add:

```python
def _has_unsafe_factorial(text: str) -> bool:
    """``(...)!`` or ``N!`` with ``N > _MAX_FACTORIAL_OPERAND``: see the constant."""
    for match in _FACTORIAL_RE.finditer(text):
        operand = match.group(1)
        if operand == ")" or int(operand) > _MAX_FACTORIAL_OPERAND:
            return True
    return False
```

In `_looks_like_prose_or_unsafe` (`:417-430`), change the last two lines to:

```python
    if _has_unsafe_factorial(text):
        return True
    calls = _FUNCTION_CALL_RE.findall(text)
    return any(_is_disallowed_sympy_call(name) for name in calls)
```

- [ ] **Step 4: Add the structural bound**

After `_has_unsafe_factorial` add:

```python
def _magnitude_bits(value: sympy.Expr) -> int | None:
    """Bit length of a finite number's magnitude, or ``None`` when it has none."""
    if not value.is_number or not value.is_finite:
        return None
    if value.is_Integer:
        return int(abs(value)).bit_length()
    if value.is_Rational:
        return max(int(abs(value.p)).bit_length(), int(value.q).bit_length())
    try:
        magnitude = abs(float(value))
    except (OverflowError, TypeError, ValueError):
        return None
    return int(math.log2(magnitude)) + 1 if magnitude >= 1 else 1


def _pow_would_explode(node: sympy.Pow) -> bool:
    """Would evaluating this (still unevaluated) power build an oversized integer?

    Called on every ``Pow`` of an ``evaluate=False`` parse in POST-order, so
    the node's own children have already passed this check and evaluating
    them here (``subs`` rebuilds and evaluates) costs at most what they were
    bounded to. Free symbols are substituted with 1: ``x^(n+1)`` bounds as
    ``x^2`` and stays parseable, while ``(2+x-x)^(999*999*999)`` -- which SymPy
    would collapse to ``2**997002999`` -- bounds as the number it is. Refused
    when the exponent's magnitude exceeds :data:`_MAX_EXPONENT_VALUE`, when
    ``bits(base) * exponent`` exceeds :data:`_MAX_POW_RESULT_BITS`, or when
    either side does not bound to a finite number at all (fail closed).
    """
    ones = {symbol: sympy.Integer(1) for symbol in node.free_symbols}
    try:
        exponent = sympy.sympify(node.exp).subs(ones).doit()
        base = sympy.sympify(node.base).subs(ones).doit()
    except Exception:
        return True
    exponent_bits = _magnitude_bits(exponent)
    base_bits = _magnitude_bits(base)
    if exponent_bits is None or base_bits is None:
        return True
    if abs(exponent) > _MAX_EXPONENT_VALUE:
        return True
    return base_bits * math.ceil(float(abs(exponent))) > _MAX_POW_RESULT_BITS


def _parse_normalized(normalized: str, *, evaluate: bool) -> sympy.Expr:
    """The one ``parse_expr`` call, shared by the parent's vetting parse and the worker."""
    return parse_expr(
        normalized,
        transformations=_TRANSFORMATIONS,
        local_dict=dict(_UNIT_LOCAL_DICT),
        evaluate=evaluate,
    )
```

- [ ] **Step 5: Write the failing backstop tests**

Append to the same section of `tests/test_equivalence.py`:

```python
def _guards_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """Let a known-dangerous text reach the parse worker, so the backstop is
    what is under test rather than the guards that normally stop it first."""
    from lemely.core import equivalence as eq

    monkeypatch.setattr(eq, "_has_unsafe_exponent", lambda _text: False)
    monkeypatch.setattr(eq, "_pow_would_explode", lambda _node: False)


def _alive(pid: int | None) -> bool:
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def test_the_parse_worker_kills_a_runaway_parse_and_keeps_the_parent_responsive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Triage F2, user decision 3: the guards can be bypassed by something
    nobody has thought of yet, so the evaluate=True parse runs in a child
    that can be KILLED. In-process, ``2**(999*999*999)`` held the GIL for
    3.8 s and a 50 ms heartbeat stalled 3.83 s; through the worker the parent
    gets ``None`` at the timeout and its heartbeat never misses a beat."""
    import multiprocessing

    from lemely.core import equivalence as eq

    _guards_off(monkeypatch)
    beats: list[float] = []
    stop = threading.Event()

    def beat() -> None:
        while not stop.is_set():
            beats.append(time.monotonic())
            time.sleep(0.05)

    threading.Thread(target=beat, daemon=True).start()
    started = time.monotonic()
    result = parse_expr_safe("2^(999*999*999)", timeout=1.0)
    elapsed = time.monotonic() - started
    stop.set()
    killed_pid = eq._PARSE_WORKER.pid()

    assert result is None
    assert elapsed < 1.6, f"the timeout was not honoured: {elapsed:.2f}s"
    gaps = [b - a for a, b in zip(beats, beats[1:], strict=False)]
    assert max(gaps) < 0.25, f"the parent stalled for {max(gaps):.2f}s -- the GIL was held"
    assert killed_pid is None or not _alive(killed_pid)
    assert all(child.name != "lemely-parse-worker" or child.is_alive() for child in multiprocessing.active_children())
    # The next call respawns the worker transparently.
    assert parse_expr_safe("2+2") == sympy.Integer(4)


def test_the_parse_worker_survives_a_memory_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """A parse that breaches the child's address-space limit comes back as
    ``None`` -- not a crash, not a respawn: the child catches MemoryError."""
    from lemely.core import equivalence as eq

    _guards_off(monkeypatch)
    assert parse_expr_safe("2+2") == sympy.Integer(4)
    pid_before = eq._PARSE_WORKER.pid()
    started = time.monotonic()
    assert parse_expr_safe("2**999999999", timeout=10.0) is None
    assert time.monotonic() - started < 10.0
    assert eq._PARSE_WORKER.pid() == pid_before


def test_the_parse_worker_leaves_no_child_behind() -> None:
    import multiprocessing

    from lemely.core import equivalence as eq

    assert parse_expr_safe("3*10^8") == sympy.Integer(300000000)
    pid = eq._PARSE_WORKER.pid()
    assert pid is not None and _alive(pid)
    eq._PARSE_WORKER.shutdown()
    assert not _alive(pid)
    assert eq._PARSE_WORKER.pid() is None
    assert not [c for c in multiprocessing.active_children() if c.name == "lemely-parse-worker"]


def test_ordinary_inputs_are_unchanged_through_the_parse_worker() -> None:
    m, v = sympy.symbols("m v")
    assert parse_expr_safe("0.5mv²") == sympy.Rational(1, 2) * m * v**2
    assert parse_expr_safe("3.0×10^8") == sympy.Float("3.0") * 10**8
    assert parse_expr_safe("not an answer at all, really") is None
```

Add `import os` and `import threading` to the file's imports if absent (`time`, `sympy`, `pytest` are already there). If the `0.5mv²` expectation does not match the parser's exact form, replace it with `parse_expr_safe("0.5mv²") == parse_expr_safe("0.5*m*v**2")`: the point is equality with the in-process form, not a specific spelling.

Run: `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_equivalence.py -q -k "parse_worker or ordinary_inputs"`
Expected: `AttributeError: module 'lemely.core.equivalence' has no attribute '_PARSE_WORKER'` for the three worker tests (the first after ~3.8 s of in-process big-int work); `ordinary_inputs` passes.

- [ ] **Step 6: Add the parse worker**

After `_run_bounded` in `lemely/core/equivalence.py` add:

```python
def _parse_worker_main(conn: object, memory_limit: int) -> None:  # pragma: no cover -- runs in the child
    """The parse worker's loop: ``(text) -> ("ok", expr) | ("memory", None) | ("error", repr)``.

    Runs in a ``spawn``ed child, so this module is imported afresh there.
    The address-space limit is set first; where ``resource`` is unavailable
    or refuses, the parent's timeout is the only bound (documented on
    :class:`_ParseWorker`).
    """
    try:
        import resource

        _soft, hard = resource.getrlimit(resource.RLIMIT_AS)
        resource.setrlimit(resource.RLIMIT_AS, (memory_limit, hard))
    except (ImportError, ValueError, OSError):
        pass
    while True:
        text = conn.recv()  # type: ignore[attr-defined]
        if text is None:
            return
        try:
            conn.send(("ok", _parse_normalized(text, evaluate=True)))  # type: ignore[attr-defined]
        except MemoryError:
            conn.send(("memory", None))  # type: ignore[attr-defined]
        except Exception as exc:
            conn.send(("error", repr(exc)))  # type: ignore[attr-defined]


class _ParseWorker:
    """One reusable, killable child process for the ``evaluate=True`` parse.

    Triage F2 (user decision 3, 2026-09-29). The parse is the one step of
    this module where SymPy can do C-level big-integer work that holds the
    GIL -- a thread timeout cannot interrupt it (see :func:`_run_bounded`),
    but a process can be killed. Measured in this venv: a spawn start costs
    0.17-0.23 s, a warm call 0.3-0.6 ms, so ONE lazily-started worker is
    kept and reused rather than one process per call (300-700x the parse).

    Guarantees, in every failure mode, that :meth:`parse` returns ``None``
    and never raises: a timeout kills and joins the child; a MemoryError in
    the child (address space capped at :data:`_PARSE_WORKER_MEMORY_BYTES`)
    is reported and the child lives on; a crash or broken pipe is joined and
    the next call respawns. ``spawn``, never ``fork``: the web server runs
    sync routes on threads. Calls are serialised by a lock (one worker per
    parent), so a caller waits at most one timeout plus one respawn behind a
    runaway sibling. The owner pid is recorded so a forked server worker or
    test process starts its own child instead of sharing a pipe. The child
    is a daemon, so ``multiprocessing``'s atexit hook terminates it with the
    parent; :meth:`shutdown` does so explicitly.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._process: object | None = None
        self._conn: object | None = None
        self._owner_pid: int | None = None

    def _start(self) -> None:
        import multiprocessing
        import os

        context = multiprocessing.get_context("spawn")
        parent_conn, child_conn = context.Pipe()
        process = context.Process(
            target=_parse_worker_main,
            args=(child_conn, _PARSE_WORKER_MEMORY_BYTES),
            name="lemely-parse-worker",
            daemon=True,
        )
        process.start()
        child_conn.close()
        self._process, self._conn, self._owner_pid = process, parent_conn, os.getpid()

    def _discard(self, *, kill: bool) -> None:
        process, conn = self._process, self._conn
        self._process = self._conn = self._owner_pid = None
        if conn is not None:
            conn.close()  # type: ignore[attr-defined]
        if process is None:
            return
        if kill:
            process.kill()  # type: ignore[attr-defined]
        process.join()  # type: ignore[attr-defined]

    def _ready(self) -> None:
        import os

        if self._process is None or self._owner_pid != os.getpid():
            self._process = self._conn = None  # a foreign or never-started worker: never joined here
            self._start()
        elif not self._process.is_alive():  # type: ignore[attr-defined]
            self._discard(kill=False)
            self._start()

    def parse(self, text: str, timeout: float) -> sympy.Expr | None:
        """``text`` parsed in the child, or ``None`` on timeout, memory, crash or parse error."""
        with self._lock:
            self._ready()
            conn = self._conn
            try:
                conn.send(text)  # type: ignore[attr-defined]
                if not conn.poll(timeout):  # type: ignore[attr-defined]
                    self._discard(kill=True)
                    return None
                kind, value = conn.recv()  # type: ignore[attr-defined]
            except (EOFError, OSError):
                self._discard(kill=True)
                return None
            if kind != "ok" or not isinstance(value, sympy.Basic):
                return None
            return value

    def pid(self) -> int | None:
        process = self._process
        return None if process is None else process.pid  # type: ignore[attr-defined]

    def shutdown(self) -> None:
        with self._lock:
            if self._process is not None and self._conn is not None:
                try:
                    self._conn.send(None)  # type: ignore[attr-defined]
                except OSError:
                    pass
            self._discard(kill=True)


_PARSE_WORKER = _ParseWorker()
```

If pyright or mypy reject the `object`-typed process/connection attributes, type them precisely instead: `from multiprocessing.connection import Connection` and `from multiprocessing.process import BaseProcess` under `TYPE_CHECKING`, annotate `_process: BaseProcess | None`, `_conn: Connection | None`, `conn: Connection` in `_parse_worker_main`, and drop the `# type: ignore[attr-defined]` comments. Either way `lint-imports` must stay green (`lemely.core` imports only stdlib and sympy here).

- [ ] **Step 7: Use the guards in the parent and the worker for the real parse**

In `parse_expr_safe`, replace the inner `_parse` definition, the `try: expr = _run_bounded(_parse, timeout)` block and its `except` clause (`:565-583`) with:

```python
    # Triage F2: bound every power on an UNEVALUATED parse first, in this
    # process -- it builds a tree and evaluates nothing but whitelisted
    # function calls and textually-bounded factorials. The regexes above
    # read literals; a computed exponent needs the tree.
    try:
        unevaluated = _parse_normalized(normalized, evaluate=False)
    except (
        SyntaxError,
        TypeError,
        ValueError,
        AttributeError,
        RecursionError,
        sympy.SympifyError,
    ):
        return None
    for node in sympy.postorder_traversal(unevaluated):
        if isinstance(node, sympy.Pow) and _pow_would_explode(node):
            return None
    # The evaluate=True parse is the one step that can build a huge integer
    # with the GIL held, so it runs in a killable child (`_ParseWorker`):
    # None on timeout, memory-limit breach, crash or parse error alike.
    expr = _PARSE_WORKER.parse(normalized, timeout)
    if not isinstance(expr, sympy.Basic):
        return None
    return expr
```

In the `parse_expr_safe` docstring, replace the sentence `both caught by the exponent check above in the common case, this is the backstop for whatever it misses.` with: `caught by the exponent and factorial checks and by the structural bound on every Pow of an unevaluated parse; and the evaluated parse itself runs in a killable child process with an address-space limit (_ParseWorker), which is the backstop for whatever those miss -- a thread timeout is not, see _run_bounded.`

Append this paragraph to `_run_bounded`'s docstring (before its closing `"""`):

```
    What this cannot do (triage F2, 2026-09-29): interrupt C-level big-int
    work. CPython holds the GIL for the whole of a large ``int.__pow__``, so
    an abandoned worker computing ``2**997002999`` froze EVERY thread in the
    process for 3.83 s (measured with a heartbeat thread) -- the caller's
    ``queue.get(timeout=...)`` cannot even wake up to give up. This is kept
    for ``simplify`` and the numeric fallback, pure-Python SymPy loops that
    release the GIL between bytecodes and demonstrably return on time; the
    parse, the one step that can build a huge integer, runs in a killable
    child process instead (:class:`_ParseWorker`).
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_equivalence.py -q -x`
Expected: all passed, including every `rejects_dangerous_constructs` id (the factorial ones now return in milliseconds), the three worker tests, the forty-pair table and the timing-sensitive tests. If `test_parse_expr_safe_treats_unknown_identifier_call_as_multiplication` or any forty-pair row changes verdict, the walk is rejecting something it should not: print the offending `node` in `_pow_would_explode` and narrow, do not loosen the bound. If `test_slow_simplify_falls_back_to_numeric_within_budget` (a subprocess test with `timeout=4`) now exceeds its bound, the worker's cold start is the cause; it is ~0.2 s, so raise that test's `timeout` to 5 and say so in the commit body.

Re-run the triage probe: `PYTHONPATH=$PWD .venv/bin/python /home/sico/.claude/jobs/33cebc31/tmp/triage/probe2.py '2^(999*999*999)' '2^(999!)'`
Expected: both print `parse_expr_safe(timeout=1.0) returned in 0.0Xs -> NoneType` with a longest heartbeat gap well under 0.25 s.

Then prove there is no leaked child after a whole-file run: `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_equivalence.py -q; sleep 1; pgrep -f "lemely-parse-worker\|multiprocessing.spawn" || echo "no children"` → `no children`.

- [ ] **Step 9: Prove the harness pin and the marking callers are untouched**

Run: `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_accuracy_harness.py -q -k "fingerprint" && PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_question_generation.py tests/test_correction_ai.py -q -k "equivalen or sympy or gate"`
Expected: all passed; the pin `af7fa9cd0e2a` is unchanged (`equivalence.py` is not an input to it). `tests/architecture` (import-linter contracts) must also pass: `PATH="$PWD/.venv/bin:$PATH" lint-imports`.

- [ ] **Step 10: Commit**

```bash
PYTHONPATH=$PWD PATH="$PWD/.venv/bin:$PATH" pre-commit run --files lemely/core/equivalence.py tests/test_equivalence.py
git add lemely/core/equivalence.py tests/test_equivalence.py
git commit -S -m "fix(core): bound computed exponents and run the parse in a killable worker" -- lemely/core/equivalence.py tests/test_equivalence.py
```
Commit body: the four backstop decisions and the measured overhead figures above, verbatim.

---
### Task 5: F5 — a pool without `select_count` is capped at its own tariffs (per-pool cap)

**Closes:** F5 (triage-report §5). No GitHub issue. **User decision:** PER-POOL CAP: cap each pool at its own points' total, then clamp the question at its marks.

**Files:**
- Modify: `lemely/core/point_groups.py` (docstring `:52-55`, comment block and `else` branch at `:96-117`)
- Test: `tests/test_question_points.py` (`test_two_pools_in_one_question_share_the_leftover_rather_than_each_taking_it` at `:349`, `test_two_groups_get_distinct_keys_and_the_leftover_subtracts_the_either_or_cap` at `:395`), `tests/test_correction_ai.py` (`test_a_later_pool_capped_to_zero_by_a_shared_leftover_does_not_flag` at `:2343`)

**Interfaces:**
- Consumes: `group_points(points, *, total, select_count) -> list[tuple[str | None, int | None]]` (unchanged signature). Consumers: `lemely/db/question_points.py::derive_point_rows` (ledger `group_max_marks`), `lemely/io/correction_ai.py::_scheme_groups` (marking), the student self-review view (`lemely/web/routers/student_self_review.py:155,186`, read-only display of `group_max_marks`).
- Produces: for a pool with `select_count is None`, `group_max_marks = min(total, sum of the pool's tariffs)`; such pools no longer consume the shared `pool_room`. Pools **with** a `select_count` keep today's rule (`min(pool_room, N largest tariffs)`, consuming `pool_room` in scheme order).

**Fingerprint:** unchanged (settings-only hash). `group_points` is marking logic behind `equivalence_gate` on the marking side and ledger metadata on the write side; prove the pin in Step 5.

- [ ] **Step 1: Write the failing tests**

In `tests/test_question_points.py`, replace `test_two_pools_in_one_question_share_the_leftover_rather_than_each_taking_it` (`:349-378`) with:

```python
def test_two_pools_without_a_select_count_are_each_capped_at_their_own_tariffs() -> None:
    """Triage F5 (user decision, 2026-09-29: per-pool cap). A pool whose N is
    unstated used to take the whole leftover and leave a later pool capped at
    0, so a student earning two marks in each of two pools got 4/6 with no
    review flag (``probe_marking.py``, case F5). Each such pool is now worth
    its own tariffs, capped at the question, and the question-level clamp in
    the consumers bounds the total.
    """
    scheme = _scheme_with(
        _points(
            ("p1", 1, "opt"),
            ("p2", 1, "opt"),
            ("p3", 1, ""),
            ("p4", 1, "opt"),
            ("p5", 1, "opt"),
        ),
        marks=4,
    )

    rows = derive_point_rows(_corrected(), scheme)

    assert _groups(rows) == [
        ("pool:1", 2),
        ("pool:1", 2),
        (None, None),
        ("pool:2", 2),
        ("pool:2", 2),
    ]


def test_a_pool_without_a_select_count_never_exceeds_the_question() -> None:
    scheme = _scheme_with(
        _points(("p1", 2, "opt"), ("p2", 2, "opt"), ("p3", 2, "opt")), marks=4
    )

    rows = derive_point_rows(_corrected(), scheme)

    assert _groups(rows) == [("pool:1", 4)] * 3


def test_a_pool_with_a_select_count_still_shares_the_leftover() -> None:
    """The stated-N rule is unchanged: ``min(pool_room, N largest tariffs)``,
    consumed in scheme order, so a later stated-N pool can still end at 0."""
    scheme = _scheme_with(
        _points(("p1", 1, "opt"), ("p2", 1, "opt"), ("p3", 1, ""), ("p4", 1, "opt"), ("p5", 1, "opt")),
        marks=2,
        select_count=2,
    )

    rows = derive_point_rows(_corrected(), scheme)

    assert _groups(rows) == [("pool:1", 1), ("pool:1", 1), (None, None), ("pool:2", 0), ("pool:2", 0)]
```

Rewrite the docstring of `test_two_groups_get_distinct_keys_and_the_leftover_subtracts_the_either_or_cap` (`:395`) to: `"""p1|p2 (either/or, worth 1) then a pool p3,p4 with no select_count on a 3-mark question: the pool is worth its own tariffs, min(3, 2) = 2."""` (its assertion `[("alt:1", 1), ("alt:1", 1), ("pool:1", 2), ("pool:1", 2)]` is unchanged).

In `tests/test_correction_ai.py`, replace `test_a_later_pool_capped_to_zero_by_a_shared_leftover_does_not_flag` (`:2343-2373`) with two tests:

```python
    def test_two_unstated_pools_each_pay_their_own_marks(self):
        """Triage F5 (``probe_marking.py`` case F5): 6 marks, i1, pool a1..a3,
        i2, pool b1..b3, no select_count. Two in each pool plus both
        independents used to award 4 with no flag (pool:2 capped at 0 by the
        shared leftover). Per-pool cap: 1 + 2 + 1 + 2 = 6."""
        from lemely.core.loose_schemas import AnswerPoint
        from lemely.io.correction_ai import _build_ai_corrected

        q = self._question(
            [
                AnswerPoint(id="i1", point="i1", marks=1),
                *(AnswerPoint(id=f"a{i}", point=f"a{i}", marks=1, is_optional=True) for i in range(3)),
                AnswerPoint(id="i2", point="i2", marks=1),
                *(AnswerPoint(id=f"b{i}", point=f"b{i}", marks=1, is_optional=True) for i in range(3)),
            ],
            marks=6,
        )
        verdicts = [
            PointVerdict(point_id=pid, verdict="awarded", evidence_span=pid)
            for pid in ("i1", "i2", "a0", "a1", "b0", "b1")
        ] + [
            PointVerdict(point_id=pid, verdict="withheld", evidence_span="") for pid in ("a2", "b2")
        ]
        cq = _build_ai_corrected(
            q, "i1 i2 a0 a1 b0 b1", self._mark(verdicts, claimed=6), equivalence_gate=True
        )
        self.assertEqual(cq.awarded_marks, 6)
        self.assertFalse(cq.needs_teacher_review)
        self.assertIsNone(cq.review_reason)

    def test_unstated_pools_are_clamped_at_the_question_not_at_a_shared_leftover(self):
        """Every point awarded: 1 + 3 + 1 + 3 = 8 caps at the question's 6."""
        from lemely.core.loose_schemas import AnswerPoint
        from lemely.io.correction_ai import _build_ai_corrected

        q = self._question(
            [
                AnswerPoint(id="i1", point="i1", marks=1),
                *(AnswerPoint(id=f"a{i}", point=f"a{i}", marks=1, is_optional=True) for i in range(3)),
                AnswerPoint(id="i2", point="i2", marks=1),
                *(AnswerPoint(id=f"b{i}", point=f"b{i}", marks=1, is_optional=True) for i in range(3)),
            ],
            marks=6,
        )
        ids = ["i1", "i2", "a0", "a1", "a2", "b0", "b1", "b2"]
        verdicts = [PointVerdict(point_id=pid, verdict="awarded", evidence_span=pid) for pid in ids]
        cq = _build_ai_corrected(q, " ".join(ids), self._mark(verdicts, claimed=6), equivalence_gate=True)
        self.assertEqual(cq.awarded_marks, 6)
        self.assertFalse(cq.needs_teacher_review)
```

(`self._question`, `self._mark` and `PointVerdict` are the class's existing helpers/imports in `GroupCappedVerdictTotalTests`.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_question_points.py tests/test_correction_ai.py -q -k "unstated_pool or without_a_select_count or select_count_still_shares"`
Expected: `test_two_pools_without_a_select_count_are_each_capped_at_their_own_tariffs` FAILS (`("pool:1", 3) ... ("pool:2", 0)` instead of 2/2), `test_a_pool_without_a_select_count_never_exceeds_the_question` passes (leftover happens to be 4), `test_two_unstated_pools_each_pay_their_own_marks` FAILS with `AssertionError: 4 != 6`, `test_unstated_pools_are_clamped...` FAILS with `5 != 6` (pool:1 capped at the leftover 4 holds 3, pool:2 at 0), `test_a_pool_with_a_select_count_still_shares_the_leftover` passes.

- [ ] **Step 3: Change the rule**

In `lemely/core/point_groups.py`, replace the docstring sentences from `a pool without a` through `so a later pool can end capped at 0.` (`:51-55`) with:

```
    ``select_count`` is worth its own tariffs, capped at ``total`` -- the
    tightest cap the scheme supports when N is unstated is the pool itself
    (triage F5, per-pool cap; 2026-09-29). Only pools WITH a ``select_count``
    share the leftover, consuming it in scheme order, so only such a pool can
    end capped at 0 when an earlier one has taken the room. Either way the
    consumer clamps the question's total at ``total``.
```

Replace the comment block and the `else` branch (`:96-117`) so the loop reads:

```python
    # The leftover is the room *the question has* for its stated-N pools
    # together, so those consume it in scheme order rather than each receiving
    # the whole figure. Measured on a 4-mark question (one independent point
    # plus an "any 1 from" pool of three), a student claiming all three pool
    # points gained 3 where the scheme allows 1, and the question-level clamp
    # never fired because 3 sits under maximum_marks. A pool WITHOUT a stated N
    # does not draw on the room (triage F5): sharing it silently capped a later
    # unstated pool at 0 and under-credited a fully-correct answer 4/6 with no
    # review flag; such a pool is worth its own tariffs and the question clamp
    # bounds the total.
    pool_room = leftover
    for kind, members in real:
        counters[kind] += 1
        if kind == "alt":
            group_max = alt_cap(members)
        elif select_count is not None:
            tariffs = sorted((points[index].marks for index in members), reverse=True)
            group_max = max(0, min(pool_room, sum(tariffs[:select_count])))
            pool_room -= group_max
        else:
            group_max = min(total, sum(points[index].marks for index in members))
        key = f"{kind}:{counters[kind]}"
        for index in members:
            result[index] = (key, group_max)
    return result
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_question_points.py tests/test_correction_ai.py tests/test_self_review_repo.py tests/test_attempt_repo.py -q`
Expected: all passed (Postgres-backed files may skip locally). If a golden case in `PointVerdictGoldenFixtureTests` moves, it is an unstated pool that was under-credited; update the golden's expected total and say why in the commit body.

- [ ] **Step 5: Prove the fingerprint pin**

Run: `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_accuracy_harness.py -q -k fingerprint`
Expected: passed; `af7fa9cd0e2a` unchanged.

- [ ] **Step 6: Commit**

```bash
PYTHONPATH=$PWD PATH="$PWD/.venv/bin:$PATH" pre-commit run --files lemely/core/point_groups.py tests/test_question_points.py tests/test_correction_ai.py
git add lemely/core/point_groups.py tests/test_question_points.py tests/test_correction_ai.py
git commit -S -m "fix(core): cap an unstated pool at its own tariffs instead of a shared leftover" -- lemely/core/point_groups.py tests/test_question_points.py tests/test_correction_ai.py
```

---

### Task 6: F4 — the backstop recomputes the group-capped total instead of subtracting tariffs

**Closes:** F4 (triage-report §4). No GitHub issue.

**Files:**
- Modify: `lemely/io/correction_ai.py` (`_awarded_from_verdicts` at `:1048-1101`; `_build_ai_corrected_from_verdicts` at `:1226-1236`, the `_verify_calculated_answers` call and what follows)
- Test: `tests/test_correction_ai.py` (add a class after `GroupCappedVerdictTotalTests`)

**Interfaces:**
- Consumes: `_verify_calculated_answers(question, student_answer, student_working, matched_point_ids, starting_awarded, *, equivalence_gate) -> tuple[int, list[str], list[str]]` (unchanged; the legacy path still uses its returned total).
- Produces: `correction_ai._group_capped_total(question: Question, awarded_ids: set[str]) -> tuple[int, int]` returning `(capped, additive)`; `_awarded_from_verdicts` delegates to it. On the verdict path the awarded figure after the backstop is `_group_capped_total(question, set(surviving matched ids))[0]`.

**Fingerprint:** unchanged (settings-only hash); prove in Step 5.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_correction_ai.py`, directly after `GroupCappedVerdictTotalTests`:

```python
class BackstopOnGroupCappedTotalTests(unittest.TestCase):
    """Triage F4 (``probe_marking.py`` cases F4): ``_verify_calculated_answers``
    did ``awarded = max(0, awarded - point.marks)`` against a total that
    ``_awarded_from_verdicts`` had ALREADY group-capped, so rejecting one
    member of an either/or pair took the whole group's mark away."""

    def _cq(self, question, awarded_ids):
        from lemely.core.schemas import AIMarkResponse
        from lemely.io.correction_ai import _build_ai_corrected_from_verdicts

        verdicts = [
            PointVerdict(
                point_id=p.id,
                verdict="awarded" if p.id in awarded_ids else "withheld",
                evidence_span="ev" if p.id in awarded_ids else "",
            )
            for p in question.answer_points
        ]
        mark = AIMarkResponse(
            awarded_marks=len(awarded_ids),
            confidence=0.95,
            matched_point_ids=sorted(awarded_ids),
            feedback="fb",
            point_verdicts=verdicts,
        )
        return _build_ai_corrected_from_verdicts(question, "speed is 3.1 m/s ev", mark, None, None)

    def test_a_rejected_either_or_member_leaves_the_surviving_member_its_mark(self):
        from lemely.core.loose_schemas import AnswerPoint, CalculatedAnswer, Question, QuestionType

        q = Question(
            id="4a",
            marks=1,
            type=QuestionType.RECALL,
            answer_points=[
                AnswerPoint(id="p1", point="p1", marks=1, calculated_answer=CalculatedAnswer(value=2.5)),
                AnswerPoint(id="p2", point="p2", marks=1, is_alternative=True),
            ],
        )
        cq = self._cq(q, {"p1", "p2"})
        self.assertEqual(cq.awarded_marks, 1)
        self.assertEqual(cq.matched_point_ids, ["p2"])
        self.assertTrue(cq.needs_teacher_review)
        self.assertIn("unverified accuracy mark(s): p1", cq.review_reason or "")
        self.assertEqual(
            {pv.point_id: pv.verdict for pv in cq.point_verdicts},
            {"p1": "unverifiable", "p2": "awarded"},
        )

    def test_a_rejected_pool_member_leaves_the_other_members_the_pool_cap(self):
        from lemely.core.loose_schemas import AnswerPoint, CalculatedAnswer, Question, QuestionType

        q = Question(
            id="4b",
            marks=2,
            type=QuestionType.RECALL,
            select_count=2,
            answer_points=[
                AnswerPoint(
                    id="p1", point="p1", marks=1, is_optional=True,
                    calculated_answer=CalculatedAnswer(value=9.81),
                ),
                AnswerPoint(id="p2", point="p2", marks=1, is_optional=True),
                AnswerPoint(id="p3", point="p3", marks=1, is_optional=True),
            ],
        )
        cq = self._cq(q, {"p1", "p2", "p3"})
        self.assertEqual(cq.awarded_marks, 2)
        self.assertEqual(cq.matched_point_ids, ["p2", "p3"])
        self.assertTrue(cq.needs_teacher_review)

    def test_a_rejected_independent_point_still_costs_its_tariff(self):
        """The legacy subtraction and the recomputation agree when no group is
        involved: this pins that F4 changes nothing there."""
        from lemely.core.loose_schemas import AnswerPoint, CalculatedAnswer, Question, QuestionType

        q = Question(
            id="4c",
            marks=2,
            type=QuestionType.RECALL,
            answer_points=[
                AnswerPoint(id="p1", point="p1", marks=1, calculated_answer=CalculatedAnswer(value=2.5)),
                AnswerPoint(id="p2", point="p2", marks=1),
            ],
        )
        cq = self._cq(q, {"p1", "p2"})
        self.assertEqual(cq.awarded_marks, 1)
        self.assertEqual(cq.matched_point_ids, ["p2"])
```

If `Question(...)` rejects the either/or fixture with a validation error about the sum of primary points, use `Question.model_construct(...)` with the same fields plus `parts=[]`, `assessment_objectives=[]`, `rejected_answers=[]`, `ignored_answers=[]`, `select_count=None` (the shape `GroupCappedVerdictTotalTests._question` uses) and say so in the commit body.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_correction_ai.py -q -k BackstopOnGroupCappedTotal`
Expected: 2 failed, 1 passed. Either/or: `AssertionError: 0 != 1`; pool: `AssertionError: 1 != 2`; the independent case already passes.

- [ ] **Step 3: Extract the capped total and use it after the backstop**

In `lemely/io/correction_ai.py`, split `_awarded_from_verdicts`. Directly above it (after `_scheme_groups`) add:

```python
def _group_capped_total(question: Question, awarded_ids: set[str]) -> tuple[int, int]:
    """``(capped, additive)`` for the scheme points in ``awarded_ids``.

    ``capped``: independent points add their tariff, each scheme group adds
    ``min(group cap, awarded tariffs in the group)``, and the whole is capped
    at ``question.marks``. ``additive``: the plain sum, likewise capped. One
    function so that :func:`_awarded_from_verdicts` (the marker's claim) and
    the post-backstop recomputation in
    :func:`_build_ai_corrected_from_verdicts` (triage F4) cannot disagree.
    """
    points, groups = _scheme_groups(question)
    additive = 0
    independent = 0
    by_group: dict[str, tuple[int, int]] = {}  # key -> (cap, awarded tariff sum)
    for point, (key, cap) in zip(points, groups, strict=True):
        if point.id not in awarded_ids:
            continue
        additive += point.marks
        if key is None:
            independent += point.marks
        else:
            prev_cap, prev_sum = by_group.get(key, (cap or 0, 0))
            by_group[key] = (prev_cap, prev_sum + point.marks)
    grouped = sum(min(cap, tariff_sum) for cap, tariff_sum in by_group.values())
    return min(independent + grouped, question.marks), min(additive, question.marks)
```

Then in `_awarded_from_verdicts`, replace everything from `awarded_ids = set(matched_point_ids)` to the `return _VerdictTotals(...)` with:

```python
    capped, additive = _group_capped_total(question, set(matched_point_ids))
    return _VerdictTotals(capped=capped, additive=additive, matched_point_ids=matched_point_ids)
```

In `_build_ai_corrected_from_verdicts`, change the backstop call (`:1226-1234`) to discard the subtracted total and recompute:

```python
    pre_verify_point_ids = set(matched_point_ids)
    _, matched_point_ids, rejections = _verify_calculated_answers(
        question,
        student_answer,
        student_working,
        matched_point_ids,
        capped,
        equivalence_gate=True,
    )
    value_mismatch = bool(rejections)
    # Triage F4: the backstop's own arithmetic subtracts a rejected point's
    # FULL tariff, which is right for the legacy path's additive total and
    # wrong here, where `capped` is already group-capped -- rejecting one
    # member of an either/or pair took the whole pair's mark away (probe:
    # awarded 0 where the surviving alternative alone earns 1). The total is
    # therefore recomputed from the SURVIVING ids with the same group rule
    # the marker's claim was capped with, never adjusted by subtraction.
    awarded, _ = _group_capped_total(question, set(matched_point_ids))
```

Update item 3 of the function's docstring (the paragraph starting `3. The deterministic calculated-answer backstop`) by appending: `Its subtracted total is discarded on this path; the mark is recomputed from the surviving ids by _group_capped_total (triage F4).`

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_correction_ai.py tests/test_question_points.py -q`
Expected: all passed.

Re-run the triage probe: `PYTHONPATH=$PWD .venv/bin/python /home/sico/.claude/jobs/33cebc31/tmp/triage/probe_marking.py` → the `[F4 either/or ...]` block now says `awarded_marks=1 needs_review=True`, `[F4 pool cap 2 ...]` says `awarded_marks=2 needs_review=True`, `[F5 ...]` says `awarded_marks=6 needs_review=False` (Task 5).

- [ ] **Step 5: Prove the fingerprint pin**

Run: `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_accuracy_harness.py -q -k fingerprint`
Expected: passed; `af7fa9cd0e2a` unchanged.

- [ ] **Step 6: Commit**

```bash
PYTHONPATH=$PWD PATH="$PWD/.venv/bin:$PATH" pre-commit run --files lemely/io/correction_ai.py tests/test_correction_ai.py
git add lemely/io/correction_ai.py tests/test_correction_ai.py
git commit -S -m "fix(correction_ai): recompute the group-capped total after the backstop instead of subtracting tariffs" -- lemely/io/correction_ai.py tests/test_correction_ai.py
```

---

### Task 7: F6 — the verdict-path coherence interval is clamped at the question's marks

**Closes:** F6 (triage-report §6). No GitHub issue.

**Files:**
- Modify: `lemely/io/correction_ai.py` (`_check_coherence`, the `if groups is not None:` branch ending at `implied_max += min(cap, sum(tariffs))`, around `:905-921`; docstring item 2 around `:815-830`)
- Test: `tests/test_correction_ai.py` (add to `BackstopOnGroupCappedTotalTests`'s neighbour: a new class)

**Interfaces:**
- Consumes: `_check_coherence(question, matched_point_ids, awarded_marks, *, point_verdicts=None, groups=None)` (unchanged signature).
- Produces: on the verdict path (`groups is not None`) `implied_min` and `implied_max` are each `min(value, question.marks)`. The legacy path (`groups is None`) is unchanged.

**Fingerprint:** unchanged; prove in Step 5.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_correction_ai.py` after `BackstopOnGroupCappedTotalTests`:

```python
class ClampedCoherenceIntervalTests(unittest.TestCase):
    """Triage F6 (``probe_marking.py`` cases F6): the awarded figure the
    coherence check receives is already clamped at ``question.marks``, but
    the interval it was compared with was not, so a fully-correct answer was
    routed to review with "implies between 5 and 5" on a 4-mark question."""

    def _cq(self, question, awarded_ids, claimed):
        from lemely.core.schemas import AIMarkResponse
        from lemely.io.correction_ai import _build_ai_corrected_from_verdicts

        verdicts = [
            PointVerdict(
                point_id=p.id,
                verdict="awarded" if p.id in awarded_ids else "withheld",
                evidence_span="ev" if p.id in awarded_ids else "",
            )
            for p in question.answer_points
        ]
        mark = AIMarkResponse(
            awarded_marks=claimed,
            confidence=0.95,
            matched_point_ids=sorted(awarded_ids),
            feedback="fb",
            point_verdicts=verdicts,
        )
        return _build_ai_corrected_from_verdicts(question, "x ev", mark, None, None)

    def test_det_shaped_breach_of_the_primary_sum_does_not_flag_a_full_answer(self):
        """``io/det/reconcile.py`` assigns ``answer_points`` after construction
        and bypasses ``validate_mark_point_sum`` (4 of 479 corpus schemes are
        in breach); model it the same way."""
        from lemely.core.loose_schemas import AnswerPoint, Question, QuestionType

        q = Question(
            id="6",
            marks=4,
            type=QuestionType.RECALL,
            answer_points=[AnswerPoint(id="p1", point="p1", marks=1)],
        )
        q.answer_points = [AnswerPoint(id=f"p{i}", point=f"p{i}", marks=1) for i in range(1, 6)]
        cq = self._cq(q, {f"p{i}" for i in range(1, 6)}, claimed=4)
        self.assertEqual(cq.awarded_marks, 4)
        self.assertFalse(cq.needs_teacher_review)
        self.assertIsNone(cq.review_reason)

    def test_an_alternative_worth_more_than_its_sibling_does_not_flag_on_a_valid_scheme(self):
        from lemely.core.loose_schemas import AnswerPoint, Question, QuestionType

        q = Question(
            id="6b",
            marks=2,
            type=QuestionType.RECALL,
            answer_points=[
                AnswerPoint(id="p1", point="p1", marks=1),
                AnswerPoint(id="p2", point="p2", marks=1),
                AnswerPoint(id="p3", point="p3", marks=2, is_alternative=True),
            ],
        )
        cq = self._cq(q, {"p1", "p3"}, claimed=2)
        self.assertEqual(cq.awarded_marks, 2)
        self.assertFalse(cq.needs_teacher_review)
        self.assertIsNone(cq.review_reason)

    def test_a_genuine_under_award_inside_the_clamp_still_flags(self):
        """The clamp must not blind the check: 2 independent 1-mark points
        matched on a 4-mark question with awarded 1 is still incoherent."""
        from lemely.core.loose_schemas import AnswerPoint, Question, QuestionType
        from lemely.io.correction_ai import _check_coherence, _scheme_groups

        q = Question(
            id="6c",
            marks=4,
            type=QuestionType.RECALL,
            answer_points=[AnswerPoint(id=f"p{i}", point=f"p{i}", marks=1) for i in range(1, 5)],
        )
        _, groups = _scheme_groups(q)
        reason = _check_coherence(q, ["p1", "p2"], 1, groups=groups)
        self.assertIsNotNone(reason)
        self.assertIn("between 2 and 2", reason or "")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_correction_ai.py -q -k ClampedCoherenceInterval`
Expected: 2 failed, 1 passed. The det-shaped case fails `assertFalse(True)` with `review_reason` = `awarded 4 mark(s) but matched_point_ids implies between 5 and 5 mark(s)`; the alternative case with `... implies between 3 and 3 mark(s)`; the genuine under-award passes.

- [ ] **Step 3: Clamp the interval on the verdict path**

In `_check_coherence`, inside the `if groups is not None:` branch, after the `for cap, tariffs in by_group.values():` loop (the two lines `implied_min += min(cap, max(tariffs))` / `implied_max += min(cap, sum(tariffs))`), add:

```python
        # Triage F6: `awarded_marks` reaches here already clamped at
        # `question.marks` (`_group_capped_total`), so the interval must be
        # too, or a det-parsed scheme whose independent tariffs exceed the
        # question (reconcile.py bypasses validate_mark_point_sum; 4 of 479
        # corpus schemes) and a valid scheme whose alternative outweighs its
        # sibling both routed a FULLY-CORRECT answer to review.
        implied_min = min(implied_min, question.marks)
        implied_max = min(implied_max, question.marks)
```

In the docstring's item 2 (the paragraph that begins `2. ``awarded_marks`` falls outside the RANGE`), after the sentence ending `at most ``min(cap, sum of matched tariffs)``.` add: `Both ends are then clamped at ``question.marks`` (triage F6), because the awarded figure compared against them already is.`

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_correction_ai.py -q`
Expected: all passed. Re-run the probe (`PYTHONPATH=$PWD .venv/bin/python /home/sico/.claude/jobs/33cebc31/tmp/triage/probe_marking.py`): both `[F6 ...]` blocks now say `needs_review=False`.

- [ ] **Step 5: Prove the fingerprint pin**

Run: `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_accuracy_harness.py -q -k "fingerprint or Coherence"`
Expected: passed; `af7fa9cd0e2a` unchanged; `COHERENCE_TRIGGER_MARKER` wiring tests still green.

- [ ] **Step 6: Commit**

```bash
PYTHONPATH=$PWD PATH="$PWD/.venv/bin:$PATH" pre-commit run --files lemely/io/correction_ai.py tests/test_correction_ai.py
git add lemely/io/correction_ai.py tests/test_correction_ai.py
git commit -S -m "fix(correction_ai): clamp the verdict-path coherence interval at the question's marks" -- lemely/io/correction_ai.py tests/test_correction_ai.py
```

---
## Tier 3 and follow-ups

### Task 8: F7 — the attempt confidence band exempts only `blank`

**Closes:** F7 (triage-report §7). No GitHub issue.

**Files:**
- Modify: `lemely/db/attempt_repo.py` (`_weakest_confidence_band`, the `scored = [...]` line at `:452` and the docstring paragraph starting `Finding I (US-039 consumer-fixes brief)` at `:432-441`)
- Test: `tests/test_attempt_repo.py`

**Interfaces:**
- Consumes: `CorrectedQuestion.marker_source` (`"ai" | "deterministic" | "missing" | "dropped" | "blank"`), `lemely.db.models.enums.ConfidenceBand as DBConfidenceBand` (already imported in the test file at `:70`).
- Produces: `_weakest_confidence_band(questions)` takes the minimum over every question whose `marker_source != "blank"`; a `"missing"` or `"dropped"` question pulls the band to its own (LOW) value again.

- [ ] **Step 1: Write the failing tests**

In `tests/test_attempt_repo.py`, add `_weakest_confidence_band` to the `from lemely.db.attempt_repo import (...)` list (`:46-51`), then append at the end of the file:

```python
def _band_question(index: int, band: ConfidenceBand, source: str) -> CorrectedQuestion:
    return CorrectedQuestion(
        question_id=f"q{index}",
        awarded_marks=0,
        maximum_marks=1,
        confidence=band,
        confidence_score=0.0 if band is ConfidenceBand.LOW else 0.95,
        needs_teacher_review=band is ConfidenceBand.LOW,
        marker_source=source,
        review_reason="AI marking failed: 503" if source == "missing" else None,
    )


@pytest.mark.parametrize("source", ["missing", "dropped"])
def test_a_failed_marking_call_still_pulls_the_attempt_band_to_low(source: str) -> None:
    """Triage F7 (``probe7.py``): one ``marker_source="missing"`` question
    ("AI marking failed: 503") plus nine HIGH gave the attempt ``high`` on
    this branch and ``low`` on develop. ``marker_scored`` was the wrong
    predicate here: its rationale is ``_build_blank_corrected``'s LOW on a
    genuine blank, which has been ``"blank"`` since task #36, so excluding
    ``"missing"`` and ``"dropped"`` no longer has a reason and hides a
    failure the teacher should see in the label."""
    questions = [_band_question(0, ConfidenceBand.LOW, source)] + [
        _band_question(i, ConfidenceBand.HIGH, "ai") for i in range(1, 10)
    ]
    assert _weakest_confidence_band(questions) is DBConfidenceBand.low


def test_a_genuine_blank_still_does_not_pull_the_attempt_band_down() -> None:
    questions = [_band_question(0, ConfidenceBand.LOW, "blank")] + [
        _band_question(i, ConfidenceBand.HIGH, "ai") for i in range(1, 10)
    ]
    assert _weakest_confidence_band(questions) is DBConfidenceBand.high


def test_an_all_blank_attempt_still_gets_a_band() -> None:
    questions = [_band_question(i, ConfidenceBand.LOW, "blank") for i in range(3)]
    assert _weakest_confidence_band(questions) is DBConfidenceBand.low
```

(`ConfidenceBand` here is `lemely.core.schemas.ConfidenceBand`, already imported at the top of the file inside the `from lemely.core.schemas import (...)` block; `pytest` is imported at `:16`.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_attempt_repo.py -q -k "attempt_band"`
Expected: 2 failed (`missing` and `dropped`: `assert <ConfidenceBand.high: 'high'> is <ConfidenceBand.low: 'low'>`), 2 passed. These are pure-function tests and run without Postgres.

- [ ] **Step 3: Change the filter**

In `lemely/db/attempt_repo.py`, replace `scored = [q for q in questions if marker_scored(q.marker_source)]` with:

```python
    # Triage F7: only a genuine student blank (`"blank"`, task #36) is exempt.
    # `marker_scored` also drops "missing" (nothing was attempted: an AI call
    # that raised, or --mcq-only) and "dropped" (extraction discarded the
    # answer), but those are failures a teacher should see in the label, and
    # excluding them made a ten-question attempt with one "AI marking failed:
    # 503" read HIGH.
    scored = [q for q in questions if q.marker_source != "blank"]
```

Replace the docstring paragraph starting `Finding I (US-039 consumer-fixes brief): a question no marker scored` (`:432-441`) with:

```
    Finding I (US-039 consumer-fixes brief), narrowed by triage F7: a genuine
    student blank (``marker_source == "blank"``) does not enter the minimum.
    ``_build_blank_corrected`` sets ``confidence=ConfidenceBand.LOW`` on it
    explicitly, so one unattempted part out of ten used to force the whole
    attempt's ``confidence_band`` to LOW alongside
    ``needs_teacher_review=False`` -- the same changed-meaning-of-0.0 bug as
    Finding E, on the band rather than the score. A ``"missing"`` or
    ``"dropped"`` question is NOT exempt: its LOW is a marking failure, and
    hiding it behind nine HIGH siblings mislabels the attempt.
```

If `marker_scored` is now unused in `attempt_repo.py`, remove it from the `from lemely.core.schemas import (...)` block (ruff F401 will tell you).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_attempt_repo.py tests/test_practice_repo.py tests/test_marker_scored_one_formulation.py -q`
Expected: all passed (Postgres-backed tests may skip). If `test_marker_scored_one_formulation.py` pins `_weakest_confidence_band` to `marker_scored`, update that pin to the new `!= "blank"` rule and cite F7 in its docstring: the "one formulation" it guards is for `marker_scored`'s own consumers, and the band is no longer one of them by design. Re-run the probe: `PYTHONPATH=$PWD .venv/bin/python /home/sico/.claude/jobs/33cebc31/tmp/triage/probe7.py` → `missing + 9 HIGH -> low`.

- [ ] **Step 5: Commit**

```bash
PYTHONPATH=$PWD PATH="$PWD/.venv/bin:$PATH" pre-commit run --files lemely/db/attempt_repo.py tests/test_attempt_repo.py
git add lemely/db/attempt_repo.py tests/test_attempt_repo.py
git commit -S -m "fix(db): let a failed marking call pull the attempt band to low again" -- lemely/db/attempt_repo.py tests/test_attempt_repo.py
```

---

### Task 9: F8 — the crop route checks only the page it renders, and drops the page cap

**Closes:** F8 (triage-report §8). No GitHub issue. **User decision 2 (2026-09-29):** the crop route no longer applies the 40-page cap: it checks only the page it renders, so stored scans over `MAX_SCAN_PAGES` keep their review crops. The preview route (`teacher.py::get_paper_preview`, `check_pdf_content`) and extraction (`rasterise.py`, `plan_pdf_pages` + `check_pdf_content_path`) keep the cap unchanged. After this task **#269 applies to the preview route only**.

**Files:**
- Modify: `lemely/io/scan_limits.py` (`check_pdf_content` at `:798-890`; add `_check_page` and `check_pdf_page_content`)
- Modify: `lemely/web/routers/review.py` (`_crop_pdf_scan` at `:494-528`; import at `:45`)
- Test: `tests/pdf_fakes.py` (one new builder), `tests/test_scan_limits.py`, `tests/test_web_review.py`, `tests/test_web_teacher.py`

**Interfaces:**
- Consumes: `_page_tree`, `_PageWalk`, `_ContentBudget`, `_walk_resource_graph`, `_walk_annotations`, `_check_image_and_masks`, `_resources_refs` (all in `scan_limits.py`); `tests/test_web_review.py::_synthetic_scan(pages=...)`; `tests/test_web_teacher.py`'s stored-object pattern in `test_preview_refuses_a_stored_content_stream_bomb` (`:654`).
- Produces: `scan_limits.check_pdf_page_content(doc: pymupdf.Document, page_index: int) -> None` — same rejections as `check_pdf_content` for that one page, **no document page cap**, walks nothing else; `scan_limits._check_page(doc, tree, budget, page_index)` shared by both. `tests.pdf_fakes.bomb_on_second_page_pdf(inflated_bytes: int) -> bytes`.

- [ ] **Step 1: Add the fixture builder**

Append to `tests/pdf_fakes.py`:

```python
def bomb_on_second_page_pdf(inflated_bytes: int) -> bytes:
    """Two A4 pages: page 1 draws one small red rectangle; page 2's only
    content stream inflates to ``inflated_bytes`` (a content bomb).

    Triage F8: the crop route used to walk EVERY page before rendering one,
    so a request for page 1 paid for, and was refused by, page 2.
    """
    return assemble_pdf(
        [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R 5 0 R] /Count 2 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R >>",
            pdf_stream(b"", b"q 1 0 0 rg 60 500 120 250 re f Q"),
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 6 0 R >>",
            pdf_stream(b"/Filter /FlateDecode", flate_bomb_ops(inflated_bytes)),
        ]
    )
```

- [ ] **Step 2: Write the failing unit tests**

In `tests/test_scan_limits.py`, add `check_pdf_page_content` to the `from lemely.io.scan_limits import (...)` list and `bomb_on_second_page_pdf` to the `from tests.pdf_fakes import (...)` list, then add after `ContentWalkPageCapTests`:

```python
class PageScopedContentCheckTests(unittest.TestCase):
    """Triage F8: ``check_pdf_page_content`` is ``check_pdf_content`` for the
    one page a caller is about to render -- and only that page."""

    def _doc(self, data: bytes) -> pymupdf.Document:
        return pymupdf.open(stream=data, filetype="pdf")  # type: ignore[no-untyped-call]

    def test_a_clean_page_passes_when_another_page_is_a_bomb(self) -> None:
        with self._doc(bomb_on_second_page_pdf(MAX_PAGE_CONTENT_BYTES + 1_000_000)) as doc:
            check_pdf_page_content(doc, 0)

    def test_the_bomb_page_itself_is_still_refused(self) -> None:
        with (
            self._doc(bomb_on_second_page_pdf(MAX_PAGE_CONTENT_BYTES + 1_000_000)) as doc,
            self.assertRaises(ScanTooLargeError),
        ):
            check_pdf_page_content(doc, 1)

    def test_the_whole_document_check_still_refuses_it(self) -> None:
        with self.assertRaises(ScanTooLargeError):
            check_pdf_content_bytes(bomb_on_second_page_pdf(MAX_PAGE_CONTENT_BYTES + 1_000_000))

    def test_only_the_named_page_is_walked(self) -> None:
        with (
            self._doc(bomb_on_second_page_pdf(MAX_PAGE_CONTENT_BYTES + 1_000_000)) as doc,
            patch.object(scan_limits, "_walk_resource_graph") as walk,
        ):
            check_pdf_page_content(doc, 0)
        pages_walked = {call.args[2].page_index for call in walk.call_args_list}
        self.assertEqual(pages_walked, {0})

    def test_the_page_cap_does_not_apply_to_a_page_scoped_check(self) -> None:
        """User decision 2 (2026-09-29): a stored scan over MAX_SCAN_PAGES
        keeps its review crops; the cap bounds whole-document work
        (extraction, preview) and a one-page render is not that."""
        with self._doc(_pdf_bytes(*([(595.0, 842.0)] * (MAX_SCAN_PAGES + 1)))) as doc:
            check_pdf_page_content(doc, 0)
            check_pdf_page_content(doc, MAX_SCAN_PAGES)

    def test_the_whole_document_check_keeps_the_page_cap(self) -> None:
        with self.assertRaises(ScanTooLargeError):
            check_pdf_content_bytes(_pdf_bytes(*([(595.0, 842.0)] * (MAX_SCAN_PAGES + 1))))
```

Run: `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_scan_limits.py -q -k PageScopedContentCheck`
Expected: `ImportError: cannot import name 'check_pdf_page_content'` (collection error) — the red state.

- [ ] **Step 3: Split `check_pdf_content`**

In `lemely/io/scan_limits.py`, replace the body of `check_pdf_content` from `budget = _ContentBudget()` to the end of the function with:

```python
    budget = _ContentBudget()
    for page_index in range(doc.page_count):
        _check_page(doc, tree, budget, page_index)
```

and add, directly after `check_pdf_content`:

```python
def _check_page(
    doc: pymupdf.Document, tree: _PageTree, budget: _ContentBudget, page_index: int
) -> None:
    """One page's share of :func:`check_pdf_content`: images, contents, resources, annotations."""
    page = doc.load_page(page_index)  # type: ignore[no-untyped-call]
    page_xref = doc.page_xref(page_index)  # type: ignore[no-untyped-call]
    budget.page_total = 0
    budget.objects = 0
    walk = _PageWalk(page_index=page_index, tree=tree.xrefs, budget=budget)
    try:
        for image in page.get_images(full=True):
            _check_image_and_masks(doc, image, page_index=page_index)
        start: list[tuple[int, _Role]] = []
        for xref in page.get_contents():
            xref = int(xref)
            if xref in tree.xrefs or not doc.xref_is_stream(xref):  # type: ignore[no-untyped-call]
                raise ScanRejectedError(_MALFORMED_STRUCTURE_MESSAGE.format(page=page_index + 1))
            start.append((xref, "any"))
        start.extend(
            ref for holder in tree.holders.get(page_xref, ()) for ref in _resources_refs(doc, holder)
        )
        _walk_resource_graph(doc, start, walk)
        _walk_annotations(doc, page_xref, walk)
    except ScanRejectedError:
        raise
    except Exception as exc:
        raise ScanRejectedError(_WALK_FAILED_MESSAGE.format(page=page_index + 1)) from exc
    budget.scan_total += budget.page_total


def check_pdf_page_content(doc: pymupdf.Document, page_index: int) -> None:
    """:func:`check_pdf_content` for the ONE page a caller is about to render.

    Triage F8: the crop route renders one page but used to pay for the
    whole-document walk on every request (35-48 ms against a 60-78 ms crop
    render on a normal paper), and a bomb on some OTHER page refused a crop
    that never touched it. pdfium parses only the page it renders, so only
    that page's content, resources and annotations need bounding. The same
    rules apply as in :func:`check_pdf_content` -- encrypted and non-PDF
    documents left alone, fail-closed on any walk failure -- with a fresh
    budget, since no other page contributes to it.

    No page cap (user decision 2, 2026-09-29): ``MAX_SCAN_PAGES`` bounds
    whole-document work, and a one-page render is not that, so a stored scan
    over the cap keeps its review crops. Extraction and the preview route
    still go through :func:`check_pdf_content` and keep the cap (issue #269
    is about the preview route alone from here on). The caller has already
    bounds-checked ``page_index`` (``review._require_page_in_range``).
    """
    if not doc.is_pdf:
        return
    if doc.needs_pass:
        return
    try:
        tree = _page_tree(doc)
    except Exception as exc:
        raise ScanRejectedError(_WALK_FAILED_MESSAGE.format(page=1)) from exc
    _check_page(doc, tree, _ContentBudget(), page_index)
```

`_page_tree` still climbs every page's `/Parent` chain for the resource holders: that reads dictionaries only, never a stream, so it is cheap for any page count.

- [ ] **Step 4: Run the unit tests to verify they pass**

Run: `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_scan_limits.py -q`
Expected: all passed (the whole file: the refactor must not move any existing bomb test; `ContentWalkPageCapTests` still proves the whole-document cap).

- [ ] **Step 5: Write the failing route tests**

Add to `tests/test_web_review.py` (after `test_an_image_scan_too_large_to_decode_is_refused_before_decoding`; `_synthetic_scan`, `_seed_boxed_review_item`, `_use_review_service`, `_use_storage`, `_auth_as` are the file's helpers):

```python
def test_crop_route_checks_only_the_page_it_renders(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
    storage_backend: FakeStorageBackend,
) -> None:
    """Triage F8: a box on a clean page must not be refused because ANOTHER
    page of the same scan is a content bomb -- pdfium never parses that page
    for this crop. The bomb page itself is still refused, which is what makes
    the first half a proof that the check moved rather than disappeared."""
    from lemely.io.scan_limits import MAX_PAGE_CONTENT_BYTES
    from tests.pdf_fakes import bomb_on_second_page_pdf

    scan = bomb_on_second_page_pdf(MAX_PAGE_CONTENT_BYTES + 1_000_000)
    # Each call seeds its own teacher, student and class; keep both teachers.
    clean_owner, clean_item = _seed_boxed_review_item(
        pg_sessionmaker, class_service, storage=storage_backend, scan=scan, page=0
    )
    bomb_owner, bomb_item = _seed_boxed_review_item(
        pg_sessionmaker, class_service, storage=storage_backend, scan=scan, page=1
    )
    _use_review_service(client, review_service)
    _use_storage(client, storage_backend)

    _auth_as(client, clean_owner, Role.teacher)
    clean = client.get(f"/api/teacher/review/{clean_item}/crop")
    assert clean.status_code == 200, clean.text
    assert clean.headers["content-type"] == "image/png"

    _auth_as(client, bomb_owner, Role.teacher)
    bomb = client.get(f"/api/teacher/review/{bomb_item}/crop")
    assert bomb.status_code == 422, bomb.text


def test_crop_route_serves_a_stored_scan_over_the_page_cap(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
    storage_backend: FakeStorageBackend,
) -> None:
    """User decision 2 (2026-09-29): a scan stored before the upload-time
    page cap, with more than MAX_SCAN_PAGES pages, keeps its review crops --
    the crop renders one page and never walks the rest. (The preview route
    still refuses the same scan: ``tests/test_web_teacher.py::
    test_preview_still_refuses_a_stored_scan_over_the_page_cap``.)"""
    from lemely.io.scan_limits import MAX_SCAN_PAGES

    scan = _synthetic_scan(pages=MAX_SCAN_PAGES + 1, marked_page=0)
    teacher, item_id = _seed_boxed_review_item(
        pg_sessionmaker, class_service, storage=storage_backend, scan=scan, page=0
    )
    _use_review_service(client, review_service)
    _use_storage(client, storage_backend)
    _auth_as(client, teacher, Role.teacher)

    resp = client.get(f"/api/teacher/review/{item_id}/crop")
    assert resp.status_code == 200, resp.text
    got = Image.open(io.BytesIO(resp.content)).convert("RGB")
    reddish, bluish, total = _colour_counts(got)
    assert bluish == 0 and reddish / total > 0.5, "wrong region on the over-cap scan"
```

Add to `tests/test_web_teacher.py`, directly after `test_preview_refuses_a_stored_content_stream_bomb` (`:654-696`), modelled on it:

```python
def test_preview_still_refuses_a_stored_scan_over_the_page_cap(
    client: TestClient,
    paper_repo: TeacherPaperRepository,
    storage_backend: FakeStorageBackend,
    settings: Settings,
    teacher_user: uuid.UUID,
) -> None:
    """User decision 2 (2026-09-29): the crop route dropped the page cap; the
    preview route keeps it (#269 is about this route alone now). Seeded
    directly into storage, as the upload route rejects the file."""
    from unittest.mock import patch

    import pymupdf

    from lemely.io.scan_limits import MAX_SCAN_PAGES

    doc = pymupdf.open()
    for _ in range(MAX_SCAN_PAGES + 1):
        doc.new_page(width=595.0, height=842.0)
    scan: bytes = doc.tobytes()
    doc.close()
    paper_id = uuid.uuid4()
    key = f"teacher/{teacher_user}/{paper_id.hex}/scan.pdf"
    storage_backend.upload(settings.storage.bucket, key, scan, "application/pdf")
    paper_repo.create(
        paper_id=paper_id,
        uploaded_by=teacher_user,
        storage_path=key,
        scheme_storage_path=None,
        original_filename="scan.pdf",
        content_type="application/pdf",
        byte_size=len(scan),
    )

    with patch.object(pymupdf.Page, "get_pixmap") as get_pixmap:
        preview = client.get(f"/api/papers/{paper_id}/preview")
    get_pixmap.assert_not_called()
    assert preview.status_code == 422
    assert f"limit is {MAX_SCAN_PAGES}" in preview.json()["detail"]
```

Run: `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_web_review.py tests/test_web_teacher.py -q -k "checks_only_the_page_it_renders or over_the_page_cap"`
Expected with Postgres: the two crop tests FAIL at `assert ... == 200` with 422 (`Page 2 of this PDF contains far more drawing data ...` and `The scan has 41 pages; the limit is 40.`); the preview test passes already (it pins that nothing regresses). Without Postgres: skipped; CI runs them.

- [ ] **Step 6: Use the page-scoped check in the crop route**

In `lemely/web/routers/review.py` change the import at `:45` to `from lemely.io.scan_limits import ScanRejectedError, check_pdf_page_content` and in `_crop_pdf_scan` replace `check_pdf_content(doc)` with `check_pdf_page_content(doc, box.page)`. Replace the comment above it (`# _require_page_in_range first: ...` through `... a few lines down.`) with:

```python
        # `_require_page_in_range` first: it reads only `doc.page_count`, no
        # `load_page` -- an out-of-range box must still cost a bounds check,
        # not a page load (test_crop_route_422s_for_a_page_out_of_range_without_rendering
        # booby-traps `load_page` to prove it). Then the content check for the
        # ONE page pdfium will parse (triage F8): the whole-document walk cost
        # 35-48 ms per request against a 60-78 ms render, a bomb on some OTHER
        # page refused a crop that never touched it, and the document page cap
        # refused every crop of a scan stored before that cap existed. Uploads
        # that pre-date the upload-time check still get the render-bomb
        # protection for the page actually rendered; the page cap stays with
        # the whole-document callers (extraction, the preview route).
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_web_review.py tests/test_web_teacher.py tests/test_scan_limits.py tests/test_rasterise.py -q`
Expected: all passed (Postgres-backed tests may skip). Also `grep -n "check_pdf_content\b" lemely/web/routers/review.py` → no match (only `check_pdf_page_content`), and `grep -n "check_pdf_content(doc)" lemely/web/routers/teacher.py` → still one match (the preview route keeps the whole-document check and its page cap).

- [ ] **Step 8: Commit**

```bash
PYTHONPATH=$PWD PATH="$PWD/.venv/bin:$PATH" pre-commit run --files lemely/io/scan_limits.py lemely/web/routers/review.py tests/pdf_fakes.py tests/test_scan_limits.py tests/test_web_review.py tests/test_web_teacher.py
git add lemely/io/scan_limits.py lemely/web/routers/review.py tests/pdf_fakes.py tests/test_scan_limits.py tests/test_web_review.py tests/test_web_teacher.py
git commit -S -m "fix(review): bound only the page the crop route renders, without the page cap" -- lemely/io/scan_limits.py lemely/web/routers/review.py tests/pdf_fakes.py tests/test_scan_limits.py tests/test_web_review.py tests/test_web_teacher.py
```
Commit body: "After this, #269 (stored scans over 40 pages) applies to the preview route only."

---
### Task 10: F9 — the crop route's docstrings state the 403 for out-of-scope items

**Closes:** F9 (triage-report §9). Touches #248 only in prose: the 403/404 mapping is unchanged (the user kept #248 out of scope).

**Files:**
- Modify: `lemely/web/routers/review.py` (`get_review_item_crop` docstring, the paragraph starting `Every "there is no image here"`)
- Modify: `lemely/db/review_repo.py` (`get_item_crop_source` docstring, the `ReviewNotFoundError:` entry under `Raises:`)

**Interfaces:** none (documentation only). The pinned test `tests/test_web_review.py::test_crop_route_refuses_a_caller_who_cannot_see_the_student` asserts the crop route's denied status equals the detail route's; it must stay green and untouched.

- [ ] **Step 1: Rewrite the route docstring paragraph**

In `lemely/web/routers/review.py`, replace the paragraph

```
    Every "there is no image here" — no such item, a console item, no upload, no
    box, or a stored object that has expired — answers with the same 404 and the
    same body, so the response cannot be used to probe which students have scans
    on file. The distinguishable reason is logged server-side instead.
```

with

```
    An item outside the caller's scope is a 403, exactly as on
    :func:`get_review_item` (``ReviewOwnershipError`` through ``_raise_for``);
    the two routes must never disagree about the same caller and item, and
    ``test_crop_route_refuses_a_caller_who_cannot_see_the_student`` pins that
    by comparison. For an item the caller MAY see, every "there is no image
    here" — no such item, a console item, no upload, no box, or a stored
    object that has expired — answers with the same 404 and the same body, so
    the response cannot be used to learn which of the caller's students have
    scans on file or why a crop is missing. The distinguishable reason is
    logged server-side instead. Ownership is checked before any of those
    absences is evaluated, so an out-of-scope caller learns nothing about
    scans at all (triage F9; the broader 403-vs-404 question is #248).
```

- [ ] **Step 2: Rewrite the repository docstring entry**

In `lemely/db/review_repo.py`, in `get_item_crop_source`'s `Raises:` block, replace the `ReviewNotFoundError:` entry's second sentence (`All of these are "there is no image here" and are deliberately indistinguishable to the caller — same type, same message: a 404 that varied by reason would let a caller probe which students have scans, and confirm that a guessed id names a real item. The distinguishable reason is logged server-side.`) with:

```
                All of these are "there is no image here" for an item the
                caller may see, and are deliberately indistinguishable to the
                caller — same type, same message: a 404 that varied by reason
                would let a caller learn which of their students have scans
                on file. It does not hide that an id names a real item: an
                existing item outside the caller's scope is the 403 below,
                as on :meth:`get_item` (triage F9; see #248). The
                distinguishable reason is logged server-side.
```

- [ ] **Step 3: Prove nothing but prose changed**

Run: `git diff --stat` → exactly the two files, docstring lines only (`git diff -U0 | grep '^[+-]' | grep -v '^[+-][+-]' | grep -v '^[+-]\s*[A-Za-z:`—(\[]' ` should print nothing that looks like code).

Run: `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_web_review.py -q -k "refuses_a_caller_who_cannot_see or 404s"` → all passed (or skipped without Postgres).

- [ ] **Step 4: Commit**

```bash
PYTHONPATH=$PWD PATH="$PWD/.venv/bin:$PATH" pre-commit run --files lemely/web/routers/review.py lemely/db/review_repo.py
git add lemely/web/routers/review.py lemely/db/review_repo.py
git commit -S -m "docs(review): say that an out-of-scope crop is a 403, as on get_item" -- lemely/web/routers/review.py lemely/db/review_repo.py
```

---
### Task 11: #255 — EXIF orientation is applied at extraction and the crop route

**Closes:** #255.

**Files:**
- Modify: `lemely/io/rasterise.py` (`_rasterise_single_image` at `:154-190`)
- Modify: `lemely/web/routers/review.py` (`_upright` and `_EXIF_ORIENTATION_TAG` at `:449-472`; `_crop_image_scan` at `:585-609`)
- Test: `tests/test_rasterise.py` (`GeometryBoundedRasteriseTests`), `tests/test_web_review.py` (`:1693-1878`: `_PHOTO_RAW_SIZE`, `_synthetic_phone_photo`, `_expected_upright_crop`, `test_crop_route_crops_an_exif_rotated_photo_where_extraction_boxed_it`)

**Interfaces:**
- Consumes: `PIL.ImageOps.exif_transpose(image, *, in_place=False)` (Pillow 12.2).
- Produces: extraction pages and every `source_box` extracted from an image upload are in the **upright** frame; `_crop_image_scan` transposes the whole decode before cropping; `review._upright` and `review._EXIF_ORIENTATION_TAG` are deleted (only `tests/test_web_review.py` referenced the tag, via its own copy at `:1693`).

**Why now, and why no box version marker:** the issue's stated cost is that stored `source_box` rows are in raw coordinates. The `question_results.source_box_*` columns come from migration `0042`, which exists only on this branch, so production holds no image-space boxes yet; changing the coordinate space before merge needs no migration and no marker. PDF pages are unaffected (MuPDF and the extraction renderer already agree on page rotation).

- [ ] **Step 1: Write the failing extraction test**

Add to `tests/test_rasterise.py`'s `GeometryBoundedRasteriseTests` (it has `self.tmp`):

```python
    def test_a_phone_photo_is_turned_upright_by_its_exif_flag(self) -> None:
        """#255 (probe ``be_probe_img.py``): a 400x200 JPEG with EXIF
        orientation 6 reached the model as a 400x200 page. Phones store a
        portrait photo as a landscape sensor frame plus that flag; the page
        the model reads, and the frame every ``source_box`` is in, must be
        the upright one. The green corner marks the raw top-left; after a
        quarter turn it must sit at the top-right of the upright page."""
        from PIL import ImageDraw

        image = Image.new("RGB", (400, 200), (255, 255, 255))
        ImageDraw.Draw(image).rectangle((0, 0, 39, 39), fill=(0, 255, 0))
        exif = Image.Exif()
        exif[0x0112] = 6
        image_path = Path(self.tmp) / "phone.jpg"
        image.save(image_path, "JPEG", exif=exif.tobytes(), quality=95)

        (page,) = rasterise_scan_to_pages(image_path)

        self.assertEqual((page.width, page.height), (200, 400))
        decoded = Image.open(io.BytesIO(page.png_bytes)).convert("RGB")
        r, g, b = decoded.getpixel((199, 0))
        self.assertTrue(g > 200 and r < 80 and b < 80, "green corner is not at the top-right")
        self.assertIsNone(decoded.getexif().get(0x0112))

    def test_an_image_without_an_exif_flag_is_unchanged(self) -> None:
        image_path = Path(self.tmp) / "plain.png"
        Image.new("RGB", (400, 200), (255, 255, 255)).save(image_path, "PNG")
        (page,) = rasterise_scan_to_pages(image_path)
        self.assertEqual((page.width, page.height), (400, 200))
```

Add `import io` to the file's imports.

Run: `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_rasterise.py -q -k "exif_flag"`
Expected: `test_a_phone_photo_is_turned_upright_by_its_exif_flag` FAILS with `AssertionError: Tuples differ: (400, 200) != (200, 400)`; the other passes.

- [ ] **Step 2: Apply the flag at extraction**

In `lemely/io/rasterise.py::_rasterise_single_image`, change the PIL import to `from PIL import Image, ImageOps, JpegImagePlugin` and replace `pil_image = opened.convert("RGB")` with:

```python
            # #255: a phone stores a portrait photo as a landscape sensor frame
            # plus an EXIF orientation flag. Apply it, so the model reads the
            # page upright and every `source_box` from here on is in the
            # upright frame -- the crop route (`review._crop_image_scan`)
            # transposes the same way before cutting. `draft()` above has
            # already picked the reduced decode, so this transposes at most
            # the reduced size; `in_place` avoids a second full-size copy when
            # there is no flag.
            ImageOps.exif_transpose(opened, in_place=True)
            pil_image = opened.convert("RGB")
```

Update the function docstring's first paragraph by appending: `The EXIF orientation flag is applied (#255), so the page, and every source_box read from it, is upright.`

Run: `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_rasterise.py -q` → all passed.

- [ ] **Step 3: Rewrite the crop-route fixture and test to the upright frame (they fail against the current route)**

In `tests/test_web_review.py`:

Rename `_PHOTO_RAW_SIZE = (600, 300)` (`:1697`) to `_PHOTO_UPRIGHT_SIZE = (600, 300)` and update its comment to say it is the size of the UPRIGHT photo, the frame extraction now sees. Replace `_synthetic_phone_photo` (`:1700-1727`) with:

```python
#: The transpose that turns an UPRIGHT image into the frame a camera STORES
#: under each EXIF orientation: the inverse of the table ``ImageOps.exif_transpose``
#: applies. Flips, 180 and the two diagonals are self-inverse; the two
#: quarter turns swap.
_STORED_FRAME_FOR = {
    2: Image.Transpose.FLIP_LEFT_RIGHT,
    3: Image.Transpose.ROTATE_180,
    4: Image.Transpose.FLIP_TOP_BOTTOM,
    5: Image.Transpose.TRANSPOSE,
    6: Image.Transpose.ROTATE_90,
    7: Image.Transpose.TRANSVERSE,
    8: Image.Transpose.ROTATE_270,
}


def _synthetic_phone_photo(orientation: int) -> bytes:
    """A JPEG whose pixels are stored sideways, with an EXIF flag saying so.

    Phones store a portrait photo as a landscape sensor frame plus EXIF
    orientation (6 is the usual one). The red mark covers ``_MARK_BOX`` in
    the UPRIGHT grid (#255: extraction applies the flag, so that is the grid
    it boxes against); the image is then turned into the stored frame and
    saved with the flag. A green corner at the mark's upright top-left shows
    which way up a crop came out.
    """
    from PIL import ImageDraw

    width, height = _PHOTO_UPRIGHT_SIZE
    image = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0.70 * width, 0.70 * height, 0.95 * width, 0.95 * height), fill=_OUTSIDE_RGB)
    ymin, xmin, ymax, xmax = _MARK_BOX
    left, upper = xmin / 1000 * width, ymin / 1000 * height
    right, lower = xmax / 1000 * width, ymax / 1000 * height
    draw.rectangle((left, upper, right - 1, lower - 1), fill=_MARK_RGB)
    draw.rectangle(
        (left, upper, left + 0.25 * (right - left) - 1, upper + 0.4 * (lower - upper) - 1),
        fill=_CORNER_RGB,
    )
    stored = image.transpose(_STORED_FRAME_FOR[orientation]) if orientation in _STORED_FRAME_FOR else image
    exif = Image.Exif()
    exif[_EXIF_ORIENTATION_TAG] = orientation
    buf = io.BytesIO()
    stored.save(buf, format="JPEG", exif=exif.tobytes(), quality=95)
    return buf.getvalue()
```

Replace `_expected_upright_crop` (`:1757-1794`) with:

```python
def _expected_upright_crop(scan: bytes) -> Image.Image:
    """The route's crop, computed independently: turn the WHOLE photo upright
    with Pillow's own ``exif_transpose``, cut the box's padded rectangle in
    that frame, upscale as the re-read does."""
    from PIL import ImageOps

    from lemely.io.reread import REREAD_UPSCALE, padded_crop_rect

    upright = ImageOps.exif_transpose(Image.open(io.BytesIO(scan))).convert("RGB")
    rect = padded_crop_rect(upright.width, upright.height, list(_MARK_BOX))
    region = upright.crop(rect)
    return region.resize(
        (region.width * REREAD_UPSCALE, region.height * REREAD_UPSCALE),
        Image.Resampling.LANCZOS,
    )
```

In `test_crop_route_crops_an_exif_rotated_photo_where_extraction_boxed_it`, replace the docstring with:

```
    """#255: extraction applies the EXIF flag, so the box is in the UPRIGHT
    pixel grid and the route must crop there too -- decode, transpose the
    whole photo the way ``exif_transpose`` does, then cut. The colour census
    shows the region is right; the green corner, at the mark's upright
    top-left, shows the crop is the right way up; and the pixel-exact
    comparison with ``_expected_upright_crop`` (Pillow's own transpose, then
    crop) shows the two agree byte for byte for all eight orientations.
    Orientation 1 is the control.
    """
```

replace the premise pin

```python
    (extracted,) = rasterise_scan_to_pages(photo_path)
    assert (extracted.width, extracted.height) == _PHOTO_RAW_SIZE
```
with
```python
    # The premise, pinned: extraction sees the UPRIGHT frame (#255). If it
    # ever stops applying the flag, this fails, and the crop route has to
    # change with it.
    (extracted,) = rasterise_scan_to_pages(photo_path)
    assert (extracted.width, extracted.height) == _PHOTO_UPRIGHT_SIZE
```

and replace the orientation-dependent shape assertion and corner check

```python
    assert (got.height > got.width) == (orientation in (5, 6, 7, 8)), got.size
    upright = ImageOps.exif_transpose(Image.open(io.BytesIO(scan))).convert("RGB")
    want_x, want_y = _corner_position(upright)
    got_x, got_y = _corner_position(got)
    assert abs(got_x - want_x) < 0.15, (orientation, (got_x, got_y), (want_x, want_y))
    assert abs(got_y - want_y) < 0.15, (orientation, (got_x, got_y), (want_x, want_y))
```
with
```python
    # Upright: the mark is wide in the upright frame, whatever the flag.
    assert got.width > got.height, (orientation, got.size)
    got_x, got_y = _corner_position(got)
    assert got_x < 0.2 and got_y < 0.3, (orientation, (got_x, got_y))
```
(the `from PIL import ImageOps` import inside the test becomes unused; remove it). Leave the `_expected_upright_crop` byte comparison as is.

Run: `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_web_review.py -q -k exif_rotated_photo`
Expected with Postgres: orientation 1 passes; orientations 2-8 FAIL (the route still crops the stored frame and rotates the crop, so the census or the byte comparison fails). Without Postgres: skipped; CI runs it.

- [ ] **Step 4: Transpose before cropping in the route**

In `lemely/web/routers/review.py`: delete `_EXIF_ORIENTATION_TAG` and `_upright` (`:449-472`) and rewrite `_crop_image_scan`:

```python
def _crop_image_scan(data: bytes, box: SourceBox, *, item_id: str) -> bytes:
    """Crop ``box`` out of a non-PDF scan, in the pixel grid extraction boxed.

    Extraction decodes an image upload with PIL and applies its EXIF
    orientation (``rasterise._rasterise_single_image``, #255), so ``box`` is
    in the UPRIGHT frame. This decodes with PIL too, transposes the whole
    photo the same way, and crops there. A single image has one page, as it
    does for extraction.
    """
    from PIL import Image, ImageOps

    with Image.open(io.BytesIO(data)) as opened:
        _require_page_in_range(box, 1, item_id=item_id)
        _decode_within_ceiling(opened, box, item_id=item_id)
        # `in_place`: no second full-size copy when there is no flag; with
        # one, the transposed frame replaces the decode, bounded by
        # `_decode_within_ceiling` above.
        ImageOps.exif_transpose(opened, in_place=True)
        rect = padded_crop_rect(opened.width, opened.height, list(box.box))
        region = _fitted_region(opened, rect)
    buf = io.BytesIO()
    region.save(buf, format="PNG")
    return _upscaled_png(buf.getvalue(), region.width, region.height, page=box.page)
```

Then `grep -n "_upright\|_EXIF_ORIENTATION_TAG" lemely/` → no matches.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_web_review.py tests/test_rasterise.py tests/test_answer_extraction.py -q`
Expected: all passed (Postgres-backed tests may skip). Re-run the probe: `PYTHONPATH=$PWD .venv/bin/python /home/sico/.claude/jobs/33cebc31/tmp/triage/be_probe_img.py` → `#255 extraction page size: (200, 400)`.

- [ ] **Step 6: Commit**

```bash
PYTHONPATH=$PWD PATH="$PWD/.venv/bin:$PATH" pre-commit run --files lemely/io/rasterise.py lemely/web/routers/review.py tests/test_rasterise.py tests/test_web_review.py
git add lemely/io/rasterise.py lemely/web/routers/review.py tests/test_rasterise.py tests/test_web_review.py
git commit -S -m "fix(io): apply EXIF orientation at extraction and crop in the upright frame" -- lemely/io/rasterise.py lemely/web/routers/review.py tests/test_rasterise.py tests/test_web_review.py
```
Commit body: "Closes #255. No box version marker: migration 0042 exists only on this branch, so no production row holds an image-space box yet."

---

### Task 12: #256 — image uploads get a per-mode pixel cap: colour stays at 40 Mpx, bilevel and greyscale go to 160 Mpx

**Closes:** #256 (the upload/extraction regression against develop, and the crop route's refusal). **User decision 1 (2026-09-29):** a PER-MODE cap, not one byte budget. Colour (`RGB`, `RGBA`, `CMYK`, `P`, `LA` and anything else) keeps its 40 Mpx ceiling; bilevel (`"1"`) and 8-bit greyscale (`"L"`) may go to 160 Mpx; 16-bit greyscale (`I;16` family) to 80 Mpx and 32-bit single-channel (`I`, `F`) to 40 Mpx, i.e. the same 160 MB of one-channel decode.

**Files:**
- Modify: `lemely/io/scan_limits.py` (constants at `:41-57`; `plan_image` at `:219-234`; `check_scan_bytes` image branch at `:952-962`)
- Modify: `lemely/io/rasterise.py` (`_rasterise_single_image`; new helper `single_channel_or_rgb`)
- Modify: `lemely/web/routers/review.py` (`_MAX_DECODE_PX` import at `:44`; `_decode_within_ceiling` at `:530-559`; `_fitted_region` at `:562-582`)
- Test: `tests/test_scan_limits.py` (`ImagePlanTests` at `:151-161`, `test_bounds_are_the_documented_values` at `:300`, `CheckScanBytesTests`), `tests/test_rasterise.py` (`:202-219`), `tests/test_web_review.py` (`:2762-2860`)

**Interfaces:**
- Consumes: `PIL.Image.Image.mode`, `Image.reduce` (not available for modes `"1"` and `"P"`, measured on Pillow 12.2), `Image.draft` (JPEG only).
- Produces: `scan_limits.MAX_DECODE_PX_GREY: int = 160_000_000`; `scan_limits.decode_pixel_cap(mode: str) -> int` (`"1"`/`"L"` → `MAX_DECODE_PX_GREY`; `"I;16"`, `"I;16L"`, `"I;16B"`, `"I;16N"` → `MAX_DECODE_PX_GREY // 2`; everything else, including `"I"`, `"F"`, `"LA"`, `"P"` and every multi-channel mode → `MAX_DECODE_PX`); `scan_limits.plan_image(width: int, height: int, mode: str = "RGB") -> int` (the ceiling is now `decode_pixel_cap(mode)`; the reduce-factor rule is unchanged); `rasterise.single_channel_or_rgb(image) -> Image` (a mode Pillow can reduce/resample without a full-size three-channel expansion of a one-channel scan). `MAX_DECODE_PX` (40 Mpx) is unchanged and stays the ceiling for colour images and for PDF pages (`plan_page_dpi`: a render is always RGB). `review._MAX_DECODE_PX` stays (it is the colour ceiling) and `review` also imports `decode_pixel_cap`.

**Measured facts this design rests on (this venv, Pillow 12.2.0):** a 100 Mpx mode-`"1"` image costs 96 MB in memory, the same as mode `"L"` — Pillow stores bilevel at one byte per pixel, so the issue's "about 17 MB as 1-bit" is wrong for PIL and `"1"` costs exactly what `"L"` costs. `Image.reduce` raises `image has wrong mode` for `"1"` and `"P"`; `"L"`, `"LA"`, `"RGB"`, `"RGBA"` reduce fine. So `"1"` goes through `"L"` (same size) before reducing, `"P"` through `"RGB"` (hence its colour cap). Peak memory for the worst admitted image: 160 Mpx `"1"` → 160 MB decode + 160 MB `"L"` copy = 320 MB; 80 Mpx `I;16` → 160 MB + 80 MB `"L"` = 240 MB; 40 Mpx colour → 120 MB + a 120 MB RGB copy, unchanged. All under the 1 GiB worker; aggregate concurrency is #249/#260, out of scope.

**Consistency with the scan-wide budgets.** `MAX_SCAN_TOTAL_PX = 160_000_000` is the pixel budget for an entire PDF scan (`plan_pdf_pages`), so a single greyscale image page at the new cap costs exactly what a whole scan may, never more; it is reduced to at most `MAX_PAGE_PX` (16 Mpx) like any page before the model sees it (a 139 Mpx scan reduces by 4 to 8.7 Mpx; 160 Mpx by 4 to 10 Mpx; `_REDUCE_FACTORS = (1, 2, 4, 8)` reaches 160 / 16 = 10 Mpx with factor 4, so the `pragma: no cover` fallthrough stays unreachable). `MIN_EXTRACTION_DPI = 100` bounds how far a PDF page's *render* DPI may be lowered to fit the scan budget; a raster image carries no DPI and is never rendered, so the floor does not apply to it — and for orientation, a 1200 dpi A4 scan reduced by 4 is 300 dpi effective, above the 200 dpi extraction target, let alone the floor.

- [ ] **Step 1: Write the failing unit tests**

In `tests/test_scan_limits.py`, add `MAX_DECODE_PX_GREY` and `decode_pixel_cap` to the `from lemely.io.scan_limits import (...)` list. Replace `ImagePlanTests` (`:151-161`) with:

```python
class ImagePlanTests(unittest.TestCase):
    def test_image_under_the_target_is_not_reduced(self) -> None:
        self.assertEqual(plan_image(1655, 2339), 1)

    def test_image_within_the_band_is_reduced_by_the_smallest_factor_that_fits(self) -> None:
        self.assertEqual(plan_image(5000, 5000), 2)  # 25 Mpx -> 6.25 Mpx

    def test_a_colour_image_just_over_forty_megapixels_is_still_refused(self) -> None:
        """User decision 1 (2026-09-29): colour keeps its ceiling."""
        for mode in ("RGB", "RGBA", "CMYK", "P", "LA"):
            with self.subTest(mode=mode), self.assertRaises(ScanTooLargeError):
                plan_image(6500, 6400, mode)  # 41.6 Mpx

    def test_a_bilevel_office_scan_at_1200_dpi_is_admitted_and_reduced(self) -> None:
        """#256 (probe ``be_probe_img.py``): a 1-bit A4 at 1200 dpi is 139 Mpx
        in a 0.04 MB file and was refused at upload with "limit 40
        megapixels". Bilevel and 8-bit greyscale go to 160 Mpx; it is reduced
        by 4 to 8.7 Mpx for the model."""
        self.assertEqual(plan_image(9921, 14031, "1"), 4)
        self.assertEqual(plan_image(9921, 14031, "L"), 4)

    def test_greyscale_just_over_the_grey_ceiling_is_refused(self) -> None:
        self.assertEqual(plan_image(12600, 12600, "L"), 4)  # 158.8 Mpx: admitted
        for mode in ("1", "L"):
            with self.subTest(mode=mode), self.assertRaises(ScanTooLargeError):
                plan_image(12700, 12700, mode)  # 161.3 Mpx

    def test_decode_pixel_cap_charges_what_pillow_holds(self) -> None:
        """Pillow keeps mode "1" at one byte per pixel (measured: 100 Mpx of
        "1" and of "L" both cost 96 MB), so both get the grey ceiling; 16-bit
        grey is two bytes, so half; "P" is converted to RGB before it can be
        reduced and "LA" is two channels, so both keep the colour ceiling."""
        self.assertEqual(decode_pixel_cap("1"), MAX_DECODE_PX_GREY)
        self.assertEqual(decode_pixel_cap("L"), MAX_DECODE_PX_GREY)
        self.assertEqual(decode_pixel_cap("I;16"), MAX_DECODE_PX_GREY // 2)
        for mode in ("I", "F", "LA", "P", "RGB", "RGBA", "CMYK", "no-such-mode"):
            with self.subTest(mode=mode):
                self.assertEqual(decode_pixel_cap(mode), MAX_DECODE_PX)
```

In `test_bounds_are_the_documented_values` (`:300`), change the assertion to:

```python
        self.assertEqual(
            (MAX_SCAN_PAGES, MAX_PAGE_PX, MAX_DECODE_PX, MAX_DECODE_PX_GREY, MAX_SCAN_TOTAL_PX),
            (40, 16_000_000, 40_000_000, 160_000_000, 160_000_000),
        )
```

Add to `CheckScanBytesTests`:

```python
    def test_a_bilevel_scan_over_forty_megapixels_is_accepted_at_upload(self) -> None:
        """#256: the regression against develop, which accepted this file."""
        buf = io.BytesIO()
        Image.new("1", (7000, 7000), 1).save(buf, format="PNG")  # 49 Mpx, one byte each
        check_scan_bytes(buf.getvalue())
```

Run: `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_scan_limits.py -q -k "ImagePlan or documented_values or bilevel"`
Expected: collection `ImportError` for `MAX_DECODE_PX_GREY` (red).

- [ ] **Step 2: Implement the per-mode cap in `scan_limits.py`**

After `MAX_DECODE_PX = 40_000_000` (`:50`) and its comment add:

```python
#: #256 (user decision 1, 2026-09-29): the image ceiling is PER MODE. Pillow
#: holds every mode at whole bytes per pixel -- "1" and "L" at one (measured:
#: 100 Mpx of either costs 96 MB), 16-bit grey at two, "RGB" at three -- so a
#: 1200 dpi bilevel A4 office scan (9921 x 14031 = 139 Mpx, 0.04 MB on disk)
#: is a 139 MB decode where the same pixels in colour would be 417 MB. Bilevel
#: and 8-bit greyscale therefore get this ceiling, 16-bit grey half of it, and
#: colour (and "P", converted to RGB before it can be reduced, and "LA") keeps
#: MAX_DECODE_PX. Equal to MAX_SCAN_TOTAL_PX on purpose: one grey page may
#: cost what a whole scan may, never more.
MAX_DECODE_PX_GREY = 160_000_000

_ONE_BYTE_GREY_MODES = frozenset({"1", "L"})
_TWO_BYTE_GREY_MODES = frozenset({"I;16", "I;16L", "I;16B", "I;16N"})


def decode_pixel_cap(mode: str) -> int:
    """The most pixels an image in ``mode`` may decode to (see :data:`MAX_DECODE_PX_GREY`)."""
    if mode in _ONE_BYTE_GREY_MODES:
        return MAX_DECODE_PX_GREY
    if mode in _TWO_BYTE_GREY_MODES:
        return MAX_DECODE_PX_GREY // 2
    return MAX_DECODE_PX
```

Replace `plan_image`:

```python
def plan_image(width: int, height: int, mode: str = "RGB") -> int:
    """The integer reduce factor that brings ``width`` x ``height`` under the target.

    ``1`` when the image already fits; :class:`ScanTooLargeError` beyond
    :func:`decode_pixel_cap` for ``mode`` (#256: per mode, so a cheap bilevel
    or greyscale scan is not refused for a pixel count only a colour decode
    would make expensive, while colour keeps :data:`MAX_DECODE_PX`).
    """
    px = width * height
    cap = decode_pixel_cap(mode)
    if px > cap:
        raise ScanTooLargeError(
            f"This scan is too large to process (limit {cap // 1_000_000} megapixels "
            f"for a {'greyscale' if cap != MAX_DECODE_PX else 'colour'} image). "
            "Rescan at a lower resolution."
        )
    for factor in _REDUCE_FACTORS:
        if px / (factor * factor) <= MAX_PAGE_PX:
            return factor
    return _REDUCE_FACTORS[-1]  # pragma: no cover -- 160 Mpx / 64 is always under the target
```

In `check_scan_bytes`, change `plan_image(opened.width, opened.height)` to `plan_image(opened.width, opened.height, opened.mode)`.

Run: `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_scan_limits.py -q` → all passed.

- [ ] **Step 3: Write the failing extraction tests**

In `tests/test_rasterise.py`'s `GeometryBoundedRasteriseTests`, replace `test_an_oversized_image_is_rejected` (`:214-218`) with:

```python
    def test_an_oversized_image_is_rejected(self) -> None:
        image_path = Path(self.tmp) / "huge.png"
        Image.new("1", (13000, 13000), color=1).save(image_path, "PNG")  # 169 Mpx bilevel
        with self.assertRaises(ScanTooLargeError):
            rasterise_scan_to_pages(image_path)

    def test_an_oversized_colour_image_is_still_rejected_at_forty_megapixels(self) -> None:
        image_path = Path(self.tmp) / "colour.png"
        Image.new("RGB", (6500, 6400), color=(255, 255, 255)).save(image_path, "PNG")  # 41.6 Mpx
        with self.assertRaises(ScanTooLargeError):
            rasterise_scan_to_pages(image_path)

    def test_a_bilevel_scan_over_forty_megapixels_is_reduced_not_refused(self) -> None:
        """#256: 49 Mpx of mode "1" is a 49 MB decode; it used to be refused
        for its pixel count. Reduced by 2 (to 12.25 Mpx) BEFORE the RGB
        conversion, so the three-channel copy is never made at full size."""
        image_path = Path(self.tmp) / "office.png"
        Image.new("1", (7000, 7000), color=1).save(image_path, "PNG")
        pages = rasterise_scan_to_pages(image_path)
        self.assertEqual((pages[0].width, pages[0].height), (3500, 3500))

    def test_the_reduce_happens_before_the_rgb_conversion(self) -> None:
        image_path = Path(self.tmp) / "grey.png"
        Image.new("L", (5000, 5000), color=200).save(image_path, "PNG")
        real_convert = Image.Image.convert
        sizes_converted_to_rgb: list[tuple[int, int]] = []

        def _convert(image: Image.Image, mode: str = "RGB", *args: object, **kwargs: object) -> Image.Image:
            if mode == "RGB":
                sizes_converted_to_rgb.append(image.size)
            return real_convert(image, mode, *args, **kwargs)

        with patch.object(Image.Image, "convert", _convert):
            rasterise_scan_to_pages(image_path)
        self.assertEqual(sizes_converted_to_rgb, [(2500, 2500)])
```

Run: `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_rasterise.py -q -k "oversized_image or oversized_colour or bilevel_scan or before_the_rgb"`
Expected: both `oversized` tests pass, `bilevel_scan_over_forty_megapixels` FAILS with `ScanTooLargeError` (the extractor still calls `plan_image` without `mode`), `before_the_rgb_conversion` FAILS (`[(5000, 5000)] != [(2500, 2500)]`).

- [ ] **Step 4: Reduce before converting at extraction**

In `lemely/io/rasterise.py`, add a module-level helper (after `_looks_like_pdf`):

```python
#: Modes Pillow cannot `reduce` or resample well and which convert losslessly
#: to one byte per pixel; everything else that is not "L"/"RGB" goes to RGB.
_ONE_CHANNEL_MODES = frozenset({"1", "I", "F", "I;16", "I;16B", "I;16L", "I;16N"})


def single_channel_or_rgb(image: PILImage) -> PILImage:
    """``image`` in a mode Pillow can ``reduce``/resample: "L" or "RGB".

    #256: a bilevel ("1") scan is taken to "L" (same size, one byte per
    pixel), never straight to RGB at full size; a palette or other
    multi-channel mode goes to RGB, which is why :func:`scan_limits.
    decode_pixel_cap` gives it the colour ceiling. "L" and "RGB" are
    returned as they are.
    """
    if image.mode in ("L", "RGB"):
        return image
    if image.mode in _ONE_CHANNEL_MODES:
        return image.convert("L")
    return image.convert("RGB")
```

The module imports PIL lazily inside functions and has `from __future__ import annotations`, so annotate with a type-only name: add `from PIL.Image import Image as PILImage` inside the module's existing `if TYPE_CHECKING:` block (the body only calls `image.convert`, no runtime `Image` reference). Then rewrite the body of `_rasterise_single_image`'s `try` block and what follows:

```python
    try:
        with Image.open(image_path) as opened:
            factor = plan_image(opened.width, opened.height, opened.mode)
            if factor > 1 and isinstance(opened, JpegImagePlugin.JpegImageFile):
                opened.draft(None, (opened.width // factor, opened.height // factor))
            # #255: apply the EXIF orientation flag so the page, and every
            # `source_box` read from it, is upright; the crop route transposes
            # the same way. `draft()` above has already picked the reduced
            # decode, so this transposes at most the reduced size.
            ImageOps.exif_transpose(opened, in_place=True)
            # #256: reduce BEFORE any three-channel conversion, so a large
            # bilevel or greyscale scan is never expanded to RGB at full size.
            pil_image = single_channel_or_rgb(opened)
    except Image.DecompressionBombError as exc:
        raise ScanTooLargeError("image declares too many pixels to decode") from exc
    # Re-planned against the post-open dimensions: a JPEG's `.draft()` above picks
    # the nearest supported DCT scale, not exactly `factor`, so the image may still
    # need an extra integer `.reduce()` here to land under MAX_PAGE_PX.
    factor = plan_image(pil_image.width, pil_image.height, pil_image.mode)
    if factor > 1:
        pil_image = pil_image.reduce(factor)
    pil_image = pil_image.convert("RGB")
```

Update the docstring sentence `one beyond MAX_DECODE_PX is refused from its header` to `one beyond decode_pixel_cap for its mode (40 Mpx colour, 160 Mpx bilevel/greyscale, #256) is refused from its header`.

Run: `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_rasterise.py tests/test_answer_extraction.py -q` → all passed.

- [ ] **Step 5: Update the crop-route tests (they fail against the current route)**

In `tests/test_web_review.py`:

`test_an_image_scan_too_large_to_decode_is_refused_before_decoding` (`:2762`): the streamed PNG is 8-bit greyscale (colour type 0), so the size must exceed the GREY ceiling now: change the import to `from lemely.io.scan_limits import MAX_DECODE_PX_GREY`, the size to `side = int(MAX_DECODE_PX_GREY**0.5) + 100` (12749 px, 162.5 Mpx), and `assert len(scan) < 200_000` to `assert len(scan) < 400_000`. Rewrite its docstring's last sentence: `The route reads the size and mode from the header and refuses first: this one is greyscale, so it is judged against the grey ceiling (#256).`

`test_a_high_resolution_photo_is_decoded_smaller_and_still_cropped_right` (`:2807`) is unchanged: 8000 x 5400 RGB is 43 Mpx, still over the colour ceiling, still decoded at half scale.

Add after `test_an_image_region_over_the_ceiling_is_scaled_down_not_refused`:

```python
def test_a_bilevel_scan_over_forty_megapixels_is_cropped_not_refused(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
    storage_backend: FakeStorageBackend,
) -> None:
    """#256: 49 Mpx of mode "1" is a 49 MB decode. It used to be refused for
    its pixel count; and the crop must be cut from the "L" copy, never from
    a full-size RGB expansion (147 MB) of the page."""
    from PIL import ImageDraw

    width, height = 7000, 7000
    image = Image.new("1", (width, height), 1)
    ymin, xmin, ymax, xmax = _MARK_BOX
    ImageDraw.Draw(image).rectangle(
        (xmin / 1000 * width, ymin / 1000 * height, xmax / 1000 * width, ymax / 1000 * height),
        fill=0,
    )
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    del image
    teacher, item_id = _seed_boxed_review_item(
        pg_sessionmaker,
        class_service,
        storage=storage_backend,
        scan=buf.getvalue(),
        page=0,
        content_type="image/png",
    )
    _use_review_service(client, review_service)
    _use_storage(client, storage_backend)
    _auth_as(client, teacher, Role.teacher)

    resp = client.get(f"/api/teacher/review/{item_id}/crop")
    assert resp.status_code == 200, resp.text
    got = Image.open(io.BytesIO(resp.content)).convert("L")
    dark = sum(got.histogram()[:64]) / (got.width * got.height)
    assert dark > 0.5, f"{dark:.2f} dark: the black mark inside the box is missing"


def test_a_colour_scan_over_forty_megapixels_is_still_refused_at_the_crop(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
    storage_backend: FakeStorageBackend,
) -> None:
    """User decision 1: colour keeps its ceiling. A streamed RGB PNG, so the
    test never holds the 125 MB decode itself."""
    import struct
    import zlib

    from lemely.io.scan_limits import MAX_DECODE_PX

    side = int(MAX_DECODE_PX**0.5) + 100

    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = struct.pack(">I", zlib.crc32(tag + data))
        return struct.pack(">I", len(data)) + tag + data + crc

    compressor = zlib.compressobj(9)
    row = b"\x00" + b"\x80" * (side * 3)
    idat = bytearray()
    for _ in range(side):
        idat += compressor.compress(row)
    idat += compressor.flush()
    header = struct.pack(">IIBBBBB", side, side, 8, 2, 0, 0, 0)  # colour type 2: RGB
    scan = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", bytes(idat)) + chunk(b"IEND", b"")
    assert len(scan) < 400_000

    teacher, item_id = _seed_boxed_review_item(
        pg_sessionmaker, class_service, storage=storage_backend, scan=scan, page=0, content_type="image/png"
    )
    _use_review_service(client, review_service)
    _use_storage(client, storage_backend)
    _auth_as(client, teacher, Role.teacher)

    with structlog.testing.capture_logs() as logs:
        resp = client.get(f"/api/teacher/review/{item_id}/crop")
    assert resp.status_code == 422, (resp.status_code, len(resp.content))
    assert [e["event"] for e in logs if e["event"].startswith("review_crop_")] == [
        "review_crop_page_too_large"
    ]
```

Run: `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_web_review.py -q -k "too_large_to_decode or bilevel_scan or colour_scan_over"`
Expected with Postgres: `ImportError` for `MAX_DECODE_PX_GREY` (collection error, red). Without Postgres: the import error still shows at collection.

- [ ] **Step 6: Apply the per-mode cap in the crop route**

In `lemely/web/routers/review.py`: keep `from lemely.io.scan_limits import MAX_DECODE_PX as _MAX_DECODE_PX` and add `decode_pixel_cap` to the `from lemely.io.scan_limits import ...` line below it; change `from lemely.io.rasterise import RasterisedPage, looks_like_pdf` to also import `single_channel_or_rgb`. Update the comment above `_PdfCropPlan` (`# The image decode bound is ...`) to say the bound is `decode_pixel_cap` per mode (#256) and that `_MAX_DECODE_PX` is the colour ceiling the tests import.

Rewrite `_decode_within_ceiling`:

```python
def _decode_within_ceiling(opened: PILImage, box: SourceBox, *, item_id: str) -> None:
    """Keep ``opened``'s decode under its mode's ceiling, before it happens.

    ``Image.open`` has read only the header, so the size and mode are known
    and nothing is decoded yet. The ceiling is per mode (#256:
    ``scan_limits.decode_pixel_cap`` -- 40 Mpx for colour, 160 Mpx for a
    bilevel or greyscale scan that decodes to one byte per pixel), the same
    rule upload and extraction apply. A JPEG can be decoded at 1/2, 1/4 or
    1/8 scale natively (``draft``); anything else over the ceiling is refused.

    Checked by ``isinstance``, not ``opened.format == "JPEG"``: a phone JPEG
    carrying a second embedded image (Android Ultra HDR's gain map, some
    iPhone exports) is reported by Pillow as ``format == "MPO"`` through
    ``MpoImageFile``, which subclasses ``JpegImageFile`` and supports the
    same ``draft`` reduced-scale decode.
    """
    from PIL import JpegImagePlugin

    width, height = opened.size
    cap = decode_pixel_cap(opened.mode)
    if width * height <= cap:
        return
    if isinstance(opened, JpegImagePlugin.JpegImageFile):
        for scale in (2, 4, 8):
            if -(-width // scale) * -(-height // scale) <= cap:
                # Floor division here: ``draft`` picks the largest scale whose
                # result is no smaller than the size asked for.
                opened.draft(None, (width // scale, height // scale))
                break
        if opened.width * opened.height <= cap:
            return
    _refuse_too_large(box, item_id=item_id, width_px=width, height_px=height)
```

In `_fitted_region`, replace

```python
        if image.mode not in ("RGB", "L"):
            # PIL resamples palette and bilevel images by nearest neighbour.
            image = image.convert("RGB")
```
with
```python
        # PIL resamples palette and bilevel images by nearest neighbour; a
        # bilevel page goes to "L" (same size), not to a full-size RGB (#256).
        image = single_channel_or_rgb(image)
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_web_review.py tests/test_scan_limits.py tests/test_rasterise.py tests/test_web_teacher.py tests/test_student_correct.py -q`
Expected: all passed (Postgres-backed tests may skip). Re-run the probe: `PYTHONPATH=$PWD .venv/bin/python /home/sico/.claude/jobs/33cebc31/tmp/triage/be_probe_img.py` → `#256 upload-time check_scan_bytes: ACCEPTED`.

- [ ] **Step 8: Commit**

```bash
PYTHONPATH=$PWD PATH="$PWD/.venv/bin:$PATH" pre-commit run --files lemely/io/scan_limits.py lemely/io/rasterise.py lemely/web/routers/review.py tests/test_scan_limits.py tests/test_rasterise.py tests/test_web_review.py
git add lemely/io/scan_limits.py lemely/io/rasterise.py lemely/web/routers/review.py tests/test_scan_limits.py tests/test_rasterise.py tests/test_web_review.py
git commit -S -m "fix(io): cap image decodes per mode so cheap bilevel and greyscale scans are not refused" -- lemely/io/scan_limits.py lemely/io/rasterise.py lemely/web/routers/review.py tests/test_scan_limits.py tests/test_rasterise.py tests/test_web_review.py
```
Commit body: "Closes #256." plus the measured Pillow facts and the per-mode rule (colour 40 Mpx unchanged; bilevel/8-bit grey 160 Mpx; 16-bit grey 80 Mpx).

---
### Task 13: #243 — the data-handling page names school and platform administrators

**Closes:** #243 (copy fix only; option 1 of the issue).

**Files:**
- Modify: `web/src/portals/marketing/dataHandling.ts:125-138` (the `"Who else can see your work"` section: its source comment and `body`)
- Test: `web/tests/unit/dataHandling.test.ts`

**Interfaces:**
- Consumes: `dataHandlingSections` (exported array of `{heading, body}`), the test file's `bannedPromises` list (no `we ...`, no `\d+ days`, no em dash `—`) and `npm run check:copy` (no em dashes in UI strings).
- Produces: the section body names both admin roles. The access itself is unchanged: `teacher_paper_visible` (`lemely/db/teacher_paper_repo.py`) grants `platform_admin` every console paper and `school_admin` their schools' teachers' papers; `ClassService` (`lemely/db/class_repo.py`) gives `school_admin` every class in their schools.

- [ ] **Step 1: Write the failing test**

Add to `web/tests/unit/dataHandling.test.ts`, inside the `describe("the page states facts, not promises — D6.8", ...)` block (or as a new `describe` after it):

```ts
describe("the access it describes is the access the backend grants — #243", () => {
  /*
   * `teacher_paper_visible` (`lemely/db/teacher_paper_repo.py`) returns
   * `sa.true()` for platform_admin and every school-member teacher's papers
   * for school_admin; `ClassService` (`lemely/db/class_repo.py`) gives a
   * school_admin every class in their schools. A page that named only
   * class-scoped teachers was narrower than the code.
   */
  it("names the school administrator and the platform administrator", () => {
    const section = dataHandlingSections.find((s) => s.heading === "Who else can see your work")
    expect(section).toBeDefined()
    expect(section!.body).toMatch(/school administrator/i)
    expect(section!.body).toMatch(/platform administrator/i)
  })
})
```

Run, from `web/`: `npx vitest run tests/unit/dataHandling.test.ts`
Expected: 1 failed (`expected "A parent who is linked ..." to match /school administrator/i`), the rest pass.

- [ ] **Step 2: Change the copy and its source comment**

In `web/src/portals/marketing/dataHandling.ts`, replace the section's source comment sentence `Teacher access is class-scoped (\`lemely/web/routers/teacher.py\`, \`lemely/db/models/…\` class membership), and the review queue is` with:

```
     * Teacher access is class-scoped (`lemely/web/routers/teacher.py`,
     * `lemely/db/models/…` class membership). Two roles see more (#243):
     * `teacher_paper_visible` in `lemely/db/teacher_paper_repo.py` grants a
     * `school_admin` every paper their schools' teachers upload and a
     * `platform_admin` every console paper, and `ClassService`
     * (`lemely/db/class_repo.py`) gives a `school_admin` every class in their
     * schools. The review queue is
```

and replace the `body` string with:

```ts
    body: "A parent who is linked to a student account can see that student's marks, weak topics and at-risk flags, and only for a student they are linked to. A teacher can see the work of students in their own classes. A school administrator can see the work of students in classes at their school, and the papers their school's teachers upload. Lemely's own platform administrators can open papers uploaded to the grading console, for support. When Lemely is unsure about a paper it marked, that paper is put in a queue for a teacher to look at.",
```

- [ ] **Step 3: Run the gates that cover copy**

Run, from `web/`: `npx vitest run tests/unit/dataHandling.test.ts tests/unit/checkCopy.test.ts && npm run check:copy && npm run typecheck`
Expected: all pass; `check:copy` reports 0 findings (no em dash was introduced; the sentence uses commas and full stops only).

- [ ] **Step 4: Commit**

```bash
PYTHONPATH=$PWD PATH="$PWD/.venv/bin:$PATH" pre-commit run --files web/src/portals/marketing/dataHandling.ts web/tests/unit/dataHandling.test.ts
git add web/src/portals/marketing/dataHandling.ts web/tests/unit/dataHandling.test.ts
git commit -S -m "docs(web): name school and platform administrators on the data-handling page" -- web/src/portals/marketing/dataHandling.ts web/tests/unit/dataHandling.test.ts
```
Commit body: "Closes #243."

---
### Task 14: #257 — the numeric-fallback tests reach the sampler by construction, not by the clock

**Closes:** #257.

**Files:**
- Test only: `tests/test_equivalence.py` (`test_simplify_timeout_is_configurable_and_bounds_worst_case` at `:2092-2112`, `test_numeric_fallback_is_deterministic_across_repeated_calls` at `:2134-2164`)

**Interfaces:**
- Consumes: `lemely.core.equivalence._run_bounded(func, timeout)`; `equivalent(...)` calls it with an inner function named `_simplify_diff` for the simplify step (`equivalence.py:1806-1809`) and `_numeric_fallback` calls it with one named `_compare` (`:1698-1734`).
- Produces: a module-level pytest fixture `declined_simplify` in `tests/test_equivalence.py` that makes `_run_bounded` return `None` for `_simplify_diff` (simplify "timed out", by construction) and run everything else with a 30 s budget. `test_pool_saturation_does_not_degrade_a_later_unrelated_call` (`:2241`) is a wall-clock test by design (it proves an absence of contagion) and is deliberately left alone.

- [ ] **Step 1: Add the fixture and rewrite the determinism test**

In `tests/test_equivalence.py`, directly above `test_simplify_timeout_is_configurable_and_bounds_worst_case`, add:

```python
@pytest.fixture
def declined_simplify(monkeypatch: pytest.MonkeyPatch):
    """Force `equivalent` onto the numeric path by construction (#257).

    `_run_bounded` returns ``None`` for the simplify step -- exactly what a
    timeout returns -- without starting a thread, and gives every other
    bounded step a 30 s budget. The tests that use this are about the
    SAMPLER, not the budgets; racing a real `simplify` against 0.05 s turned
    runner load into a red build (CI run 36155845596, 3.13 only).
    """
    from lemely.core import equivalence as eq

    real = eq._run_bounded

    def bounded(func, timeout):  # noqa: ANN001, ANN202 -- mirrors the private seam
        if func.__name__ == "_simplify_diff":
            return None
        return real(func, 30.0)

    monkeypatch.setattr(eq, "_run_bounded", bounded)
```

Replace `test_numeric_fallback_is_deterministic_across_repeated_calls` with:

```python
def test_numeric_fallback_is_deterministic_across_repeated_calls(declined_simplify: None) -> None:
    """The sampler must not flip its verdict run to run on the SAME pair,
    proven by forcing every call through the ACTUAL numeric path (#257: the
    `declined_simplify` fixture, not a 0.05 s race that a loaded runner can
    lose on BOTH budgets and report UNPARSEABLE). `method` is asserted on
    every iteration, so this cannot silently degrade into re-testing
    `simplify`; and `simplify_timeout=100.0` proves the path is forced by
    the fixture, not by the clock -- with the real `_run_bounded`, a 100 s
    budget would let `simplify` finish and the first assertion would fail.
    """
    lhs, rhs = _slow_cosine_sum_identity(25)

    kinds = set()
    for _ in range(10):
        verdict = equivalent(lhs, rhs, simplify_timeout=100.0, numeric_timeout=3.0)
        assert verdict.method is EquivalenceMethod.NUMERIC, (
            "did not reach the numeric path — this run tests nothing about the sampler"
        )
        kinds.add(verdict.kind)
    assert kinds == {VerdictKind.EQUAL_SAMPLED}, f"verdict flipped across repeated calls: {kinds}"
```

- [ ] **Step 2: Prove the fixture is load-bearing**

Run: `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_equivalence.py -q -k numeric_fallback_is_deterministic -p no:cacheprovider`
Expected: passed. Then temporarily comment out the `monkeypatch.setattr(...)` line in the fixture and re-run: expected FAIL with `did not reach the numeric path` after several seconds (the real `simplify` completes within 100 s and answers first). Restore the line. This is the "check goes red" proof for a test-only change.

- [ ] **Step 3: Make the sibling independent of the numeric budget**

In `test_simplify_timeout_is_configurable_and_bounds_worst_case`, change `numeric_timeout=0.5` to `numeric_timeout=30.0` and append to its docstring:

```
    The numeric budget is generous (#257): this test is about the SIMPLIFY
    budget bounding wall time, and a 0.5 s numeric budget could also expire
    on a loaded runner and turn a passing simplify bound into UNPARSEABLE.
    The `elapsed < 5.0` bound still proves `simplify_timeout` was honoured:
    the numeric comparison on this pair takes milliseconds.
```

- [ ] **Step 4: Run the file five times**

Run: `for i in 1 2 3 4 5; do PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_equivalence.py -q -k "numeric_fallback_is_deterministic or simplify_timeout_is_configurable" -p no:cacheprovider || break; done`
Expected: five consecutive `2 passed`. Then `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_equivalence.py -q` → all passed.

- [ ] **Step 5: Commit**

```bash
PYTHONPATH=$PWD PATH="$PWD/.venv/bin:$PATH" pre-commit run --files tests/test_equivalence.py
git add tests/test_equivalence.py
git commit -S -m "test(core): reach the numeric fallback by construction, not by a timeout race" -- tests/test_equivalence.py
```
Commit body: "Closes #257."

---

### Task 15: #259 — quiz marking and the teacher console grading job use the configured integrity settings

**Closes:** #259 (both callers the triage found).

**Files:**
- Modify: `lemely/web/deps.py` (`get_quiz_marking_service` at `:541-558`)
- Modify: `lemely/web/routers/teacher.py` (`_run_grading_job`'s `grade_paper(...)` call at about `:490-497`)
- Test: `tests/test_deps_marking_options.py`, `tests/test_web_teacher.py` (next to `test_grading_job_passes_marking_options_from_settings` at `:1125`)

**Interfaces:**
- Consumes: `Settings.integrity: IntegritySettings` (`lemely/runtime/config.py:940`, `plagiarism_enabled: bool = True` at `:569`); `QuizMarkingService(..., integrity_settings=...)` (`lemely/db/quiz_marking_repo.py:155`, stored as `self._integrity_settings`); `grade_paper(..., integrity_settings=...)` (already passed by `lemely/web/routers/student.py:1065`).
- Produces: both callers pass `integrity_settings=settings.integrity`.

- [ ] **Step 1: Write the failing deps test**

Append to `tests/test_deps_marking_options.py`:

```python
def test_quiz_marking_service_wires_configured_integrity_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#259: ``QuizMarkingService`` fell back to ``IntegritySettings()``
    because ``get_quiz_marking_service`` never passed the operator's
    ``[integrity]`` -- the same shape as the missing marking options above,
    and just as invisible to every test that builds the service directly."""
    monkeypatch.setenv("LEMELY_INTEGRITY__PLAGIARISM_ENABLED", "false")
    deps.reset_singletons()
    try:
        with monkeypatch.context() as m:
            m.setattr(deps, "get_sessionmaker", lambda _settings: MagicMock())
            m.setattr(deps, "get_attempt_repo", lambda: MagicMock())
            m.setattr(deps, "get_gemini_client", lambda: MagicMock())
            service = deps.get_quiz_marking_service()
            assert service._integrity_settings is not None
            assert service._integrity_settings.plagiarism_enabled is False
    finally:
        deps.reset_singletons()
```

Run: `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_deps_marking_options.py -q`
Expected: 1 failed (`assert None is not None`), 1 passed.

- [ ] **Step 2: Write the failing teacher-console test**

Add to `tests/test_web_teacher.py` directly after `test_grading_job_passes_marking_options_from_settings`:

```python
def test_grading_job_passes_integrity_settings_from_settings(
    client: TestClient,
    settings: Settings,
    paper_repo: TeacherPaperRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#259, second caller: ``_run_grading_job`` called ``grade_paper``
    without ``integrity_settings``, so a console paper was checked under the
    defaults whatever ``[integrity]`` said; the student upload passes it.
    Same arrangement as the marking-options test above."""
    from lemely.web.routers import student as student_router
    from lemely.web.services import grading as grading_service

    report = _report(needs_review=False, grade="A")
    seen: dict[str, object] = {}

    def _grade(*_a: object, **kwargs: object) -> AccuracyReport:
        seen["integrity_settings"] = kwargs.get("integrity_settings")
        return report

    monkeypatch.setattr(student_router, "resolve_mark_scheme", lambda *_a, **_k: _scheme())
    monkeypatch.setattr(grading_service, "extract_answers", lambda *_a, **_k: {"5b": "42"})
    monkeypatch.setattr(grading_service, "grade_paper", _grade)

    integrity_settings = settings.model_copy(
        update={"integrity": settings.integrity.model_copy(update={"plagiarism_enabled": False})}
    )
    client.app.dependency_overrides[get_settings] = lambda: integrity_settings  # type: ignore[union-attr]

    paper_id = _upload(client)
    row = _settle(paper_repo, paper_id)

    assert teacher._row_kind(row) == "graded"
    assert seen["integrity_settings"] is integrity_settings.integrity
    assert seen["integrity_settings"].plagiarism_enabled is False  # type: ignore[attr-defined]
```

Run: `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_web_teacher.py -q -k integrity_settings_from_settings`
Expected: FAIL with `AssertionError: assert None is <IntegritySettings ...>` (Postgres-backed; skipped locally without it, CI runs it).

- [ ] **Step 3: Pass the settings at both callers**

`lemely/web/deps.py`, in `get_quiz_marking_service`:

```python
    return QuizMarkingService(
        get_sessionmaker(settings),
        get_attempt_repo(),
        get_gemini_client(),
        marking_options=settings.grading.marking_options(),
        # #259: the operator's [integrity], not QuizMarkingService's default.
        integrity_settings=settings.integrity,
    )
```

`lemely/web/routers/teacher.py`, in `_run_grading_job`'s `grade_paper(...)` call, add `integrity_settings=settings.integrity,` after `history_store=None,`, and append to the comment above it: `integrity_settings: the operator's [integrity], as the student upload already passes (#259).`

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_deps_marking_options.py tests/test_web_teacher.py tests/test_marking_options_wiring.py tests/test_quiz_marking_repo.py -q`
Expected: all passed (Postgres-backed tests may skip).

- [ ] **Step 5: Commit**

```bash
PYTHONPATH=$PWD PATH="$PWD/.venv/bin:$PATH" pre-commit run --files lemely/web/deps.py lemely/web/routers/teacher.py tests/test_deps_marking_options.py tests/test_web_teacher.py
git add lemely/web/deps.py lemely/web/routers/teacher.py tests/test_deps_marking_options.py tests/test_web_teacher.py
git commit -S -m "fix(web): pass the configured integrity settings to quiz marking and the console grading job" -- lemely/web/deps.py lemely/web/routers/teacher.py tests/test_deps_marking_options.py tests/test_web_teacher.py
```
Commit body: "Closes #259."

---

### Task 16: #263 — the accuracy harness reports re-reads skipped by the time budget

**Closes:** #263.

**Files:**
- Modify: `lemely/accuracy/harness.py` (`AccuracyResult` at `:424-431`; `measure_accuracy` loop at `:1178-1207` and the `return AccuracyResult(...)` at `:1356`; `format_report` end at `:1470-1484`; `save_result` `data` dict at `:1506`)
- Modify: `lemely/app/cli.py` (`measure_accuracy_cmd` options at `:1160-1190`, signature at `:1191`, the `failed` list at `:1273-1290`)
- Test: `tests/test_accuracy_harness.py` (`MeasureAccuracyTests`), `tests/test_cli_review_rate_gate.py` (`_fake_result`, `_run_cli`)

**Interfaces:**
- Consumes: `ExtractedAnswers.reread_skipped_by_budget: int` (`lemely/core/schemas.py:651`), set by `lemely/io/answer_extraction.py` and reaching the harness through `extract_answers(...)` on the `extract+mark` arm.
- Produces: `AccuracyResult.reread_skipped_by_budget: int = 0` (summed over every case that ran extraction; oracle cases contribute 0); a `WARNING:` line in `format_report` when it is non-zero; the key `"reread_skipped_by_budget"` in `save_result`'s JSON; `measure-accuracy --fail-on-skipped-rereads` (flag, default off) that adds `reread_skipped_by_budget N > 0` to the `Targets missed` list and so exits non-zero.

- [ ] **Step 1: Write the failing harness tests**

Add to `tests/test_accuracy_harness.py`'s `MeasureAccuracyTests` (it has `self._mark_scheme`):

```python
    def test_rereads_skipped_by_the_budget_are_summed_and_warned_about(self):
        """#263: a run whose re-reads were cut short by
        ``GeminiSettings.reread_budget_seconds`` produces timing-dependent
        marks, and nothing in the harness or the report said so."""
        from lemely.accuracy.harness import (
            DEFAULT_RENDER,
            GoldenAnswer,
            GoldenCase,
            format_report,
            measure_accuracy,
        )
        from lemely.core.schemas import ExtractedAnswer, ExtractedAnswers
        from lemely.runtime.config import Settings

        scan_path = Path("/nonexistent/scan.pdf")
        cases = [
            GoldenCase(
                paper_id=f"p-skip-{i}",
                mark_scheme=self._mark_scheme(["1"]),
                ground_truth={"1": GoldenAnswer(student_answer="A", awarded_marks=1)},
                scan_path=scan_path,
                renders={DEFAULT_RENDER: scan_path},
            )
            for i in range(2)
        ]
        skipped = iter([2, 3])

        def _extract(*_a: object, **_k: object) -> ExtractedAnswers:
            return ExtractedAnswers(
                paper_id="p",
                source_scan="fake",
                answers=[ExtractedAnswer(question_id="1", answer="A", confidence=0.9)],
                reread_skipped_by_budget=next(skipped),
            )

        with patch("lemely.web.services.grading.extract_answers", side_effect=_extract):
            result = measure_accuracy(cases, gemini_client=None, settings=None, arm="extract+mark")

        self.assertEqual(result.reread_skipped_by_budget, 5)
        report = format_report(result, Settings().accuracy_eval)
        self.assertIn("WARNING: 5 re-read(s) were skipped by the wall-clock budget", report)

    def test_a_run_with_no_skipped_rereads_does_not_warn(self):
        from lemely.accuracy.harness import GoldenAnswer, GoldenCase, format_report, measure_accuracy
        from lemely.runtime.config import Settings

        case = GoldenCase(
            paper_id="p-clean",
            mark_scheme=self._mark_scheme(["1"]),
            ground_truth={"1": GoldenAnswer(student_answer="A", awarded_marks=1)},
            scan_path=None,
        )
        result = measure_accuracy([case], gemini_client=None, settings=None)
        self.assertEqual(result.reread_skipped_by_budget, 0)
        self.assertNotIn("WARNING", format_report(result, Settings().accuracy_eval))
```

Run: `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_accuracy_harness.py -q -k "skipped_rereads or skipped_by_the_budget"`
Expected: 2 failed with `AttributeError: 'AccuracyResult' object has no attribute 'reread_skipped_by_budget'`.

- [ ] **Step 2: Write the failing CLI test**

In `tests/test_cli_review_rate_gate.py`: give `_fake_result` a keyword `reread_skipped: int = 0` and pass `reread_skipped_by_budget=reread_skipped` into its `AccuracyResult(...)`; give `_run_cli` keywords `reread_skipped: int = 0` and `extra_args: tuple[str, ...] = ()`, forward `reread_skipped=reread_skipped` to `_fake_result` and append `*extra_args` to the `runner.invoke(cli, [...])` argument list. Then add a class at the end of the file:

```python
class TestSkippedRereadsFlag:
    """#263: a run that skipped re-reads is reported, and fails only on request."""

    def test_skipped_rereads_are_reported_but_do_not_fail_by_default(self, tmp_path) -> None:
        result = _run_cli(tmp_path, armed=False, n_reviewed=0, reread_skipped=3)
        assert result.exit_code == 0, result.output
        assert "WARNING: 3 re-read(s) were skipped" in result.output

    def test_fail_on_skipped_rereads_exits_nonzero_naming_the_count(self, tmp_path) -> None:
        result = _run_cli(
            tmp_path, armed=False, n_reviewed=0, reread_skipped=3,
            extra_args=("--fail-on-skipped-rereads",),
        )
        assert result.exit_code != 0
        assert "reread_skipped_by_budget 3 > 0" in result.output

    def test_fail_on_skipped_rereads_is_quiet_when_none_were_skipped(self, tmp_path) -> None:
        result = _run_cli(
            tmp_path, armed=False, n_reviewed=0, extra_args=("--fail-on-skipped-rereads",)
        )
        assert result.exit_code == 0, result.output
```

Run: `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_cli_review_rate_gate.py -q`
Expected: the new class fails (`TypeError: AccuracyResult.__init__() got an unexpected keyword argument 'reread_skipped_by_budget'`); the existing tests still pass or fail for the same reason (the helper changed) — after Step 3 all pass.

- [ ] **Step 3: Implement**

`lemely/accuracy/harness.py`:

1. In `AccuracyResult`, after `funnel: FunnelCounts  # ...` add:
```python
    reread_skipped_by_budget: int = 0
    """#263: re-reads the extractor skipped because ``GeminiSettings.
    reread_budget_seconds`` ran out, summed over every case that ran
    extraction (``ExtractedAnswers.reread_skipped_by_budget``). Non-zero
    means this run's marks are timing-dependent and not comparable with
    another run's; ``format_report`` warns and ``measure-accuracy
    --fail-on-skipped-rereads`` fails on it."""
```
2. In `measure_accuracy`, next to `funnel = FunnelCounts()` add `reread_skipped_by_budget = 0`; in the `extract+mark` branch, directly after `extracted_ids = {a.question_id for a in extracted.answers}`, add `reread_skipped_by_budget += extracted.reread_skipped_by_budget`; and pass `reread_skipped_by_budget=reread_skipped_by_budget,` to the `return AccuracyResult(...)`.
3. In `format_report`, after the `lines.append(f"  (extracted={f.extracted} — ...")` line and before `return "\n".join(lines)`:
```python
    if result.reread_skipped_by_budget:
        lines.append("")
        lines.append(
            f"WARNING: {result.reread_skipped_by_budget} re-read(s) were skipped by the "
            "wall-clock budget (GeminiSettings.reread_budget_seconds) -- this run's marks "
            "are timing-dependent and not comparable with another run's (#263)"
        )
```
4. In `save_result`, add `"reread_skipped_by_budget": result.reread_skipped_by_budget,` to the `data` dict after `"prompt_versions": result.prompt_versions,`.

`lemely/app/cli.py`, on `measure_accuracy_cmd`: add the option after the `--arm` option:
```python
@click.option(
    "--fail-on-skipped-rereads",
    "fail_on_skipped_rereads",
    is_flag=True,
    default=False,
    help=(
        "Exit non-zero when any crop-and-re-read was skipped by the wall-clock "
        "budget (#263): such a run's marks are timing-dependent, so a sweep meant "
        "for comparison should refuse to publish them."
    ),
)
```
add `fail_on_skipped_rereads: bool,` to the signature after `arm: str | None,`, and after the `flag_recall` check in the `failed` list add:
```python
    if fail_on_skipped_rereads and result.reread_skipped_by_budget:
        failed.append(
            f"reread_skipped_by_budget {result.reread_skipped_by_budget} > 0 "
            "(--fail-on-skipped-rereads)"
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_accuracy_harness.py tests/test_cli_review_rate_gate.py tests/test_cli_new_commands.py -q`
Expected: all passed, including `test_flag_off_fingerprint_is_unchanged` (this task adds a result field, not a fingerprint segment: the count is an outcome of the run, not a parameter of it, so it must not move `af7fa9cd0e2a`).

- [ ] **Step 5: Commit**

```bash
PYTHONPATH=$PWD PATH="$PWD/.venv/bin:$PATH" pre-commit run --files lemely/accuracy/harness.py lemely/app/cli.py tests/test_accuracy_harness.py tests/test_cli_review_rate_gate.py
git add lemely/accuracy/harness.py lemely/app/cli.py tests/test_accuracy_harness.py tests/test_cli_review_rate_gate.py
git commit -S -m "feat(accuracy): report re-reads skipped by the budget and fail on request" -- lemely/accuracy/harness.py lemely/app/cli.py tests/test_accuracy_harness.py tests/test_cli_review_rate_gate.py
```
Commit body: "Closes #263."

---

### Task 17: #266 — the generation gate's unit whitelist gains h, min, rad, T, F, H, deg

**Closes:** #266.

**Files:**
- Modify: `lemely/io/question_gates.py:117` (`_UNIT_BASE_RE`) and the `#:` comment above it
- Test: `tests/test_question_generation.py` (`TestVerifyQuestionSympyGate`, near the `test_prefixed_or_percent_tails_are_never_stripped` test at `:433`)

**Interfaces:**
- Consumes: `_UNIT_TAIL_RE` (`:140-142`, anchored at `$`, with the `(?<![A-Za-z/·*^])` prefix guard), `_strip_trailing_unit` (`:163`), `_compare_stated` (`:236`), `verify_question`.
- Produces: `_UNIT_BASE_RE = r"(?:kg|ohm|mol|min|rad|deg|eV|Pa|Hz|°C|m|s|g|h|J|N|W|V|A|K|C|L|T|F|H|Ω)"` (multi-letter atoms before single letters so `min`/`deg`/`rad` are tried before `m`/`g`; the `$` anchor and the prefix guard make the order a matter of speed, not correctness).

- [ ] **Step 1: Write the failing tests**

Add to `TestVerifyQuestionSympyGate` in `tests/test_question_generation.py`:

```python
    @pytest.mark.parametrize(
        ("stated", "value"),
        [
            ("2.5 h", "2.5"),
            ("30 min", "30"),
            ("1.57 rad", "1.57"),
            ("0.3 T", "0.3"),
            ("4.7 F", "4.7"),
            ("2 H", "2"),
            ("45 deg", "45"),
        ],
    )
    def test_the_seven_missing_unprefixed_units_are_stripped(self, stated: str, value: str) -> None:
        """#266: hours, minutes, radians, tesla, farad, henry and degrees were
        not in the whitelist, so "2.5 h" fell through to a paid sandbox call."""
        from lemely.io.question_gates import _strip_trailing_unit

        assert _strip_trailing_unit(stated) == value

    @pytest.mark.parametrize(
        ("solution_expr", "answer"),
        [("5/2", "2.5 h"), ("0.3", "0.3 T"), ("pi/2", "1.57 rad"), ("45", "45 deg")],
    )
    def test_the_new_units_verify_at_the_sympy_step_with_no_sandbox_call(
        self, solution_expr: str, answer: str
    ) -> None:
        question = _generated_question(
            "Fields", question_type=QuestionType.CALCULATION, solution_expr=solution_expr, answer=answer
        )
        client = MagicMock()
        client.generate_structured.return_value = _validity_response()
        result = verify_question(client, question, subject_code="0625")

        assert result.verified_by == "sympy", result.rejection_reason
        client.generate_with_code_execution.assert_not_called()

    @pytest.mark.parametrize("stated", ["24 d", "24 x", "24 Q", "24 hh", "24 mT", "24 nF", "24 kH", "24 mm"])
    def test_a_bare_non_unit_letter_or_a_prefixed_new_unit_is_still_not_stripped(self, stated: str) -> None:
        """The dangling-letter and prefix guards must hold for the new single
        capitals too: "mT" is a prefixed tesla, not metre-then-tesla."""
        from lemely.io.question_gates import _strip_trailing_unit

        assert _strip_trailing_unit(stated) == stated
```

Run: `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_question_generation.py -q -k "missing_unprefixed_units or new_units_verify or bare_non_unit_letter"`
Expected: the seven strip cases and the four verify cases FAIL (`assert '2.5 h' == '2.5'`; `assert None == 'sympy'`), the eight guard cases pass.

- [ ] **Step 2: Extend the whitelist**

In `lemely/io/question_gates.py` replace `:117` with:

```python
_UNIT_BASE_RE = r"(?:kg|ohm|mol|min|rad|deg|eV|Pa|Hz|°C|m|s|g|h|J|N|W|V|A|K|C|L|T|F|H|Ω)"
```

and append to the `#:` comment block above it:

```
#: #266 added h, min, rad, deg, T, F and H. Multi-letter atoms come before the
#: single letters they start with (``min`` before ``m``); with the tail
#: anchored at ``$`` and the prefix guard in ``_UNIT_TAIL_RE`` this is only
#: about backtracking, and "24 mT" is still a PREFIXED tesla, left alone.
```

- [ ] **Step 3: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_question_generation.py -q`
Expected: all passed (every pre-existing prefix, percent and dangling-operator case included).

- [ ] **Step 4: Commit**

```bash
PYTHONPATH=$PWD PATH="$PWD/.venv/bin:$PATH" pre-commit run --files lemely/io/question_gates.py tests/test_question_generation.py
git add lemely/io/question_gates.py tests/test_question_generation.py
git commit -S -m "fix(question_gates): recognise h, min, rad, deg, T, F and H as unprefixed units" -- lemely/io/question_gates.py tests/test_question_generation.py
```
Commit body: "Closes #266."

---

### Task 18: #267 — the fixture script closes each pdfium page and bitmap after rendering it

**Closes:** #267.

**Files:**
- Modify: `scripts/rasterise_handwritten_fixtures.py` (`rasterise`, the `images = [...]` comprehension at `:99`)
- Test: `tests/test_rasterise_handwritten_fixtures.py` (`TestFlattening`)

**Interfaces:**
- Consumes: `pypdfium2.PdfDocument.__iter__` (yields `self.get_page(i)`), `PdfPage.render(...).to_pil()`, `PdfPage.close()`, `PdfBitmap.close()`; the production pattern in `lemely/io/rasterise.py:112-121`.
- Produces: the same `rasterise(source, out_pdf) -> dict` contract; pages are closed one at a time.

- [ ] **Step 1: Write the failing test**

Add to `TestFlattening` in `tests/test_rasterise_handwritten_fixtures.py`:

```python
    def test_each_page_is_closed_before_the_next_is_loaded(self, tmp_path: Path) -> None:
        """#267: the script held every rendered page until ``pdf.close()``,
        the pattern ``298f30c7`` fixed in production (1037 MB vs 553 MB peak
        on a 40-page scan). Same spy as ``tests/test_rasterise.py``."""
        from unittest.mock import patch

        import pypdfium2 as pdfium

        module = _load_module()
        source = _pdf_with_text_layer(tmp_path / "source.pdf", pages=3)
        events: list[tuple[str, int]] = []
        real_get_page = pdfium.PdfDocument.get_page
        real_close = pdfium.PdfPage.close
        index_of: dict[int, int] = {}

        def _get_page(doc: pdfium.PdfDocument, index: int) -> pdfium.PdfPage:
            page = real_get_page(doc, index)
            index_of[id(page)] = index
            events.append(("load", index))
            return page

        def _close(page: pdfium.PdfPage, _by_parent: bool = False) -> None:
            if id(page) in index_of:
                events.append(("close", index_of.pop(id(page))))
            real_close(page, _by_parent)

        with (
            patch.object(pdfium.PdfDocument, "get_page", _get_page),
            patch.object(pdfium.PdfPage, "close", _close),
        ):
            entry = module.rasterise(source, tmp_path / "out" / "source.pdf")

        assert entry["pages"] == 3
        assert events == [
            ("load", 0), ("close", 0), ("load", 1), ("close", 1), ("load", 2), ("close", 2)
        ]
```

Run: `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_rasterise_handwritten_fixtures.py -q -k closed_before_the_next`
Expected: FAIL — `events` is `[("load", 0), ("load", 1), ("load", 2), ("close", ...), ...]` (all loads first; the closes arrive from `pdf.close()`).

- [ ] **Step 2: Close per page**

In `scripts/rasterise_handwritten_fixtures.py::rasterise`, replace

```python
        images = [page.render(scale=scale).to_pil().convert("RGB") for page in pdf]
        page_count = len(images)
```
with
```python
        # #267: close each page and its bitmap as soon as the RGB copy exists,
        # as lemely/io/rasterise.py does -- a loaded page keeps its decoded
        # images alive until it is closed, and pdf.close() alone held every
        # page's at once (1037 MB vs 553 MB peak on a 40-page scan).
        images = []
        for page in pdf:
            try:
                bitmap = page.render(scale=scale)
                try:
                    images.append(bitmap.to_pil().convert("RGB"))
                finally:
                    bitmap.close()
            finally:
                page.close()
        page_count = len(images)
```

- [ ] **Step 3: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_rasterise_handwritten_fixtures.py -q`
Expected: all passed (the determinism tests prove the output bytes are unchanged).

- [ ] **Step 4: Commit**

```bash
PYTHONPATH=$PWD PATH="$PWD/.venv/bin:$PATH" pre-commit run --files scripts/rasterise_handwritten_fixtures.py tests/test_rasterise_handwritten_fixtures.py
git add scripts/rasterise_handwritten_fixtures.py tests/test_rasterise_handwritten_fixtures.py
git commit -S -m "fix(scripts): close each pdfium page after rendering a handwritten fixture" -- scripts/rasterise_handwritten_fixtures.py tests/test_rasterise_handwritten_fixtures.py
```
Commit body: "Closes #267."

---

### Task 19: #268 — the page-close spy wrapper matches `PdfPage.close`'s signature

**Closes:** #268.

**Files:**
- Modify: `tests/test_rasterise.py` (`test_each_page_is_closed_before_the_next_page_is_loaded`, the `_close` wrapper at about `:177`)

**Interfaces:**
- Consumes: `pypdfium2.PdfPage.close(self, _by_parent: bool = False) -> None`.
- Produces: `def _close(page: pdfium.PdfPage, _by_parent: bool = False) -> None`.

- [ ] **Step 1: Reproduce the pyright error**

Run: `PYTHONPATH=$PWD .venv/bin/pyright tests/test_rasterise.py`
Expected: includes `tests/test_rasterise.py:<line>:<col> - error: Argument of type "object" cannot be assigned to parameter "_by_parent" of type "bool" in function "close"`. A second, pre-existing error `"EXTRACTION_DPI" is unknown import symbol` is the shared-venv artefact (the editable install resolves `lemely` from another worktree) and is not this task's; note it in the report.

- [ ] **Step 2: Type the wrapper**

Replace

```python
        def _close(page: pdfium.PdfPage, *args: object, **kwargs: object) -> object:
            if id(page) in index_of:
                events.append(("close", index_of.pop(id(page))))
            return real_close(page, *args, **kwargs)
```
with
```python
        def _close(page: pdfium.PdfPage, _by_parent: bool = False) -> None:
            # #268: the real signature, so pyright checks the forward.
            if id(page) in index_of:
                events.append(("close", index_of.pop(id(page))))
            real_close(page, _by_parent)
```

- [ ] **Step 3: Verify**

Run: `PYTHONPATH=$PWD .venv/bin/pyright tests/test_rasterise.py` → the `_by_parent` error is gone (only the pre-existing `EXTRACTION_DPI` line may remain).
Run: `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_rasterise.py -q` → all passed.

- [ ] **Step 4: Commit**

```bash
PYTHONPATH=$PWD PATH="$PWD/.venv/bin:$PATH" pre-commit run --files tests/test_rasterise.py
git add tests/test_rasterise.py
git commit -S -m "test(io): type the page-close spy to PdfPage.close's signature" -- tests/test_rasterise.py
```
Commit body: "Closes #268."

---
## Closing tasks

### Task 20: Gate sweep on the final tree

**Closes:** nothing. **Files:** none modified. Runs after the last fix commit (Task 19); any later commit voids it and it must be re-run (a sweep certifies only the tree it ran on).

Derived from `.github/workflows/ci.yml` at the merged tree: `test` job steps at `:55` (`ruff check .`), `:58` (`ruff format --check .`), `:61` (`mypy lemely`), `:72` (`pyright lemely`), `:75` (`lint-imports`), `:80` (`alembic upgrade head`), `:83` (`pytest`), `:109` (`python scripts/check_review_rate_gate.py`); `pre-commit` job at `:130` (`pre-commit run --all-files --show-diff-on-failure`); `web` job at `:148` (`npm ci`), `:151` (`npm run typecheck`), `:161` (`npm test`), `:166` (`npm run lint`), `:174` (`npm run check:copy`), `:180` (`npm run build`), `:190` (`npm run check:installable`). Re-derive by reading the file: `grep -n "run: " .github/workflows/ci.yml` must list exactly these commands; if it lists more, add them.

- [ ] **Step 1: Record the tree**

Run: `git rev-parse HEAD` and `git status --short`
Expected: a SHA and no output from `status`. Report that SHA with the results.

- [ ] **Step 2: Lint and types (`ci.yml:55-75`)**

```bash
PATH="$PWD/.venv/bin:$PATH" ruff check .
PATH="$PWD/.venv/bin:$PATH" ruff format --check .
PYTHONPATH=$PWD PATH="$PWD/.venv/bin:$PATH" mypy lemely
PYTHONPATH=$PWD PATH="$PWD/.venv/bin:$PATH" pyright lemely
PATH="$PWD/.venv/bin:$PATH" lint-imports
```
Expected: each exits 0. Pyright's `"X" is not assignable to "X"` lines are the known shared-venv artefact and are the only failures allowed; list them verbatim.

- [ ] **Step 3: Migrations (`ci.yml:80`)**

Run: `PYTHONPATH=$PWD PATH="$PWD/.venv/bin:$PATH" alembic heads` → exactly `0043_merge_heads (head)`. If a local Postgres is reachable on 54322: `PYTHONPATH=$PWD PATH="$PWD/.venv/bin:$PATH" alembic upgrade head` → exits 0; otherwise report it as left to CI.

- [ ] **Step 4: Scoped pytest (`ci.yml:83` is the full run; that stays CI's)**

```bash
PYTHONPATH=$PWD .venv/bin/python -m pytest \
  tests/test_db_schema.py tests/test_schemas_corrected_question.py tests/test_schemas.py \
  tests/test_teacher_paper_repo.py tests/test_review_repo.py tests/test_attempt_repo.py \
  tests/test_authz_matrix_complete.py tests/test_seed_e2e.py \
  tests/test_migration_0037_remove_ai_detection.py \
  tests/test_equivalence.py tests/test_question_points.py tests/test_correction_ai.py \
  tests/test_self_review_repo.py tests/test_practice_repo.py tests/test_marker_scored_one_formulation.py \
  tests/test_scan_limits.py tests/test_rasterise.py tests/test_answer_extraction.py \
  tests/test_web_review.py tests/test_web_teacher.py tests/test_student_correct.py \
  tests/test_deps_marking_options.py tests/test_marking_options_wiring.py tests/test_quiz_marking_repo.py \
  tests/test_accuracy_harness.py tests/test_cli_review_rate_gate.py tests/test_cli_new_commands.py \
  tests/test_question_generation.py tests/test_rasterise_handwritten_fixtures.py \
  tests/architecture -q
```
Expected: all passed (Postgres-backed files skip cleanly without a local server; list which skipped). `tests/test_accuracy_harness.py::...::test_flag_off_fingerprint_is_unchanged` and the `:1586` pin among them (`af7fa9cd0e2a`).

- [ ] **Step 5: Review-rate gate (`ci.yml:109`)**

Run: `PYTHONPATH=$PWD .venv/bin/python scripts/check_review_rate_gate.py`
Expected: exits 0 and reports the committed baseline (`BUILD/review-rate-baseline.json`) unchanged.

- [ ] **Step 6: pre-commit (`ci.yml:130`)**

Run: `PYTHONPATH=$PWD PATH="$PWD/.venv/bin:$PATH" pre-commit run --all-files --show-diff-on-failure`
Expected: every hook `Passed`. If the ruff hook autofixes anything, the tree was not what the earlier commits certified: report the diff and stop (a fix commit after this sweep voids it).

- [ ] **Step 7: Web job (`ci.yml:148-190`)**

From `web/`: `npm ci && npm run typecheck && npm test && npm run lint && npm run check:copy && npm run build && npm run check:installable`
Expected: each exits 0 (`npm run build` triggers `postbuild`'s `check:bundle`). Tasks 1 and 13 changed files under `web/`, so the whole job runs, not a subset.

- [ ] **Step 8: Report**

Report: the SHA from Step 1, the outcome of every step, the skipped Postgres files, the pin value, and any pyright artefact lines. No commit is made by this task.

---

### Task 21: PR body update

**Closes:** nothing itself; makes GitHub close the issues on merge. **Files:** none (GitHub PR #237 body via `gh`; no push).

- [ ] **Step 1: Fetch the current body**

Run: `gh pr view 237 --json body -q .body > /home/sico/.claude/jobs/33cebc31/tmp/plan5/pr-body-before.md` and read it. It opens with a commit/file count line and has sections `## CI`, `## The four changes that matter most`, `## Plan 2: ...`, `## Other fixes on the branch since ...`, `## What is in the branch, by area`.

- [ ] **Step 2: Write the new section**

Create `/home/sico/.claude/jobs/33cebc31/tmp/plan5/pr-body-after.md` as the old body with (a) the opening count line refreshed from `git rev-list --count origin/develop..HEAD` and `git diff --shortstat origin/develop...HEAD`, (b) the first paragraph's list of plans extended with `and Plan 5 (the 2026-09-29 triage round: the develop merge and the fixes below; see "Plan 5")`, and (c) this section inserted directly after `## CI`:

```markdown
## Plan 5: develop merge and the triage round (2026-09-29)

Plan: `docs/superpowers/plans/2026-09-29-pr237-triage-fixes.md`, from the triage of the `/code-review` findings and issues #239–#269. `origin/develop` (`33d2c1e6`) is merged in; the eight conflicts were import and field unions plus `scripts/seed_e2e.py`'s seeded-question helper, and #241's four onboarding calls survived.

**Merge blockers.** Two Alembic heads after the merge (`0039_paper_soft_delete` from develop, `0042_question_result_source_box` from this branch): `0043_merge_heads` is the no-op join. Every `teacher_papers.report_json` written before this PR carries `ai_detection_flagged`, which `1094cfde` removed from an `extra="forbid"` model, so the teacher paper list 500'd on one old row and console review items silently lost their report: `CorrectedQuestion` now discards exactly that one key on load (a `mode="before"` validator, not a data migration — the reasons are in the commit body of `fix(core): load stored reports ...`).

**Verdict path (behind `equivalence_gate`, still off by default).** `2^(999*999*999)` and `2^(999!)` passed the exponent regexes and froze the process building the integer (the GIL is held, so the thread timeout cannot fire): every `Pow` of an unevaluated parse is now bounded before the real parse, factorials are bounded textually, and the evaluated parse itself runs in a killable child process (spawn, one reusable worker, 1 s wall-clock timeout, 512 MiB address-space limit; measured 0.3–0.6 ms per warm call, 0.2 s to start) that returns the same `UNPARSEABLE` outcome on timeout, memory breach or crash. An unstated "any N from" pool took the whole leftover and capped a later pool at 0, awarding 4/6 silently: each such pool is now worth its own tariffs, clamped at the question (per-pool cap). The calculated-answer backstop subtracted a rejected point's full tariff from a group-capped total, so rejecting one half of an either/or took the pair's mark: the total is recomputed from the surviving ids. The coherence interval is clamped at the question's marks, so a det-parsed scheme in breach of the primary sum no longer routes a fully-correct answer to review. The harness fingerprint pin `af7fa9cd0e2a` is unchanged by all of it (it hashes settings, not code).

**User-visible.** Phone photos are read upright (EXIF orientation applied at extraction and at the crop route; boxes are in the upright frame — no migration, since `0042` exists only here). Image uploads get a per-mode ceiling: colour stays at 40 Mpx, bilevel and greyscale may go to 160 Mpx (16-bit grey 80 Mpx), so a 1200 dpi bilevel office scan (139 Mpx, 0.04 MB) is accepted at upload, extraction and crop again, as on develop; Pillow holds bilevel at one byte per pixel, and the pipeline reduces before any RGB expansion. One `AI marking failed` question pulls the attempt band to LOW again; only a genuine blank is exempt. The data-handling page names school and platform administrators. The crop route bounds only the page it renders and no longer applies the 40-page cap, so stored scans over 40 pages keep their review crops (#269 now concerns the preview route only). Quiz marking and the console grading job now use `[integrity]`. The accuracy harness reports re-reads skipped by the time budget and can fail on them (`--fail-on-skipped-rereads`). Seven unprefixed units (`h min rad deg T F H`) no longer cost a sandbox call. Two test-hygiene fixes (#257, #268) and the fixture script's per-page close (#267).

Closes #239, closes #240, closes #241, closes #243, closes #246, closes #247, closes #253, closes #255, closes #256, closes #257, closes #259, closes #263, closes #266, closes #267, closes #268.

Out of this round, deliberately: #242, #244, #245, #248, #249, #250, #251, #252, #254, #260, #261, #262, #264, #265, #269 (the pre-deploy checks #261 and #269 stay open as deploy gates).
```

Also, in `## CI`, prepend one line: `Plan 5 CI: <fill in after the next push; the local gate sweep on <SHA from Task 20> is recorded in the plan's Task 20 report>.`

- [ ] **Step 3: Apply and verify**

Run: `gh pr edit 237 --body-file /home/sico/.claude/jobs/33cebc31/tmp/plan5/pr-body-after.md` then `gh pr view 237 --json body -q .body | grep -c "closes #"` → expected `15` occurrences on one line (grep counts the line; also `grep -o "closes #[0-9]*" | wc -l` → `15`).

No commit and no push. Report the list of `Closes` numbers exactly as applied.

---

## Self-review against the scope

| Scope item | Task(s) |
|---|---|
| Tier 1: merge develop (8 conflicts, keep #241's seed calls) | 1 |
| Tier 1: F3 no-op `0043_merge_heads` | 2 |
| Tier 1: F1 legacy `ai_detection_flagged` loads (tolerate-on-load, justified) | 3 |
| Tier 2: F2 exponent guard bypass + GIL-holding big-int | 4 |
| Tier 2: F5 per-pool cap (user decision) | 5 |
| Tier 2: F4 consistent with the per-pool cap | 6 |
| Tier 2: F6 consistent with the per-pool cap | 7 |
| Tier 3: F7 exempt only `blank` | 8 |
| F8 crop route checks only the rendered page | 9 |
| F9 docstrings only | 10 |
| Tier 3: #255 EXIF orientation | 11 |
| Tier 3: #256 cheap bilevel/greyscale scans accepted at upload | 12 |
| Tier 3: #243 copy naming both admin roles | 13 |
| #257 | 14 |
| #259 incl. the teacher console grading call | 15 |
| #263 | 16 |
| #266 | 17 |
| #267 | 18 |
| #268 | 19 |
| Gate sweep derived from `ci.yml` | 20 |
| PR body with `Closes #N` | 21 |

Out of scope and untouched: #242, #244, #245, #248 (beyond F9's prose), #249, #250, #251, #252, #254, #260–#262, #264, #265, #269, all e2e/CI work.

Placeholder scan: no "TBD", "TODO", "similar to Task N", or code-less code steps. Type consistency: `_group_capped_total(question, awarded_ids) -> tuple[int, int]` (Task 6) is the only new `correction_ai` seam and Task 7 does not use it; `check_pdf_page_content(doc, page_index)` (Task 9) is what Task 11/12's `review.py` edits leave untouched; `plan_image(width, height, mode="RGB")` (Task 12) is called with three arguments by `rasterise.py` and `check_scan_bytes` and with two by the unchanged PDF tests; `single_channel_or_rgb` (Task 12) is imported by `review.py` from `lemely.io.rasterise`, which `review.py` already imports from; `decode_pixel_cap(mode)` (Task 12) is the one ceiling rule used by `plan_image`, `check_scan_bytes` and `review._decode_within_ceiling`, while `review._MAX_DECODE_PX` keeps its name as the colour ceiling the tests import; `_ParseWorker.parse(text, timeout) -> sympy.Expr | None` (Task 4) is called only from `parse_expr_safe`, and Task 14's `declined_simplify` fixture patches `_run_bounded`, which Task 4 keeps for `simplify` and the numeric fallback; `AccuracyResult.reread_skipped_by_budget` (Task 16) defaults to 0 so `tests/test_cli_review_rate_gate.py::_fake_result` and every other constructor call keep working; Task 11's `ImageOps.exif_transpose(opened, in_place=True)` line is carried verbatim into Task 12's rewrite of the same function.
