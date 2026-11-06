# Student Home Overview (design A) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the student Overview page with design A (`web/dev-previews/student-home-a.html`), backed by real API data for every one of its 14 states, and prove pixel fidelity with the drift gate.

**Architecture:** The backend extends `GET /api/student/overview` and `UploadRunDTO`, adds `POST /api/student/results/{paperId}/seen`, and needs two migrations (`attempts.seen_at`, upload progress columns). The frontend adds `web/src/portals/student/home/facts.ts`. It turns the three query responses into a `HomeView`: `HomeFacts` for the existing `model.ts` decisions, plus the display data the design prints. `homeState()` picks one of the 14 states. Nine Tailwind v4 components render the view. Every UI task passes when its drift scenes pass. The drift script (`web/scripts/home-drift.mjs`) renders the preview and the real page with the API mocked from fixtures built on `web/dev-previews/student-home/fixtures.ts`.

**Tech Stack:** FastAPI + Pydantic (`ApiModel`), SQLAlchemy 2, Alembic, pytest; React 19, TanStack Query, react-router, Tailwind v4 (`@theme` tokens in `web/src/index.css`), Vitest (node env, `renderToStaticMarkup`), Playwright (route mocks, axe, pixelmatch).

## Global Constraints

- Spec: `docs/superpowers/specs/2026-11-06-student-home-overview-design.md`. It is the contract. Where this plan names a value, the spec or the design source it cites is the origin.
- Starting point: `origin/develop` merged into `design/student-home-variants`, and the portal-shell plan (`docs/superpowers/plans/2026-11-06-portal-shell.md`) finished. The shared shell wraps student pages, and `web/scripts/home-drift.mjs` exists with a scene list. Before Task 1, run `git log --oneline -1 origin/develop` and `ls web/scripts/home-drift.mjs`. If either is missing, stop and report.
- Signed commits only: `git commit -S -m "<type>(<scope>): <subject>" -- <explicit paths>`. Conventional scopes: `feat(student):` backend, `feat(web):` frontend, `test(web):`, `test(student):`, `fix(...)`. Never `git add -A`. Do not push.
- Before every commit: `/home/sico/Code/Lemely/.venv/bin/pre-commit run --files <changed files>`. The ruff hook autofixes, so re-stage and re-run until it passes on the exact tree you commit. mypy/pyright fail repo-wide on unresolved imports from the shared venv. Report failures in files you did not touch, but do not chase them. Fix every failure in files you touched.
- Run pre-commit from the worktree root with repo-relative paths. Where a step writes `cd web && …/pre-commit run --files src/...`, run it from the root and prefix each path with `web/`. The paired `git commit -- <paths>` already uses root paths.
- Component tasks (10–18) add helper modules beyond the File structure table (`home/states.ts`, `home/geometry.ts`, `home/garden.ts`, `--home-*` aliases in `web/src/index.css`). Each task's **Files** block is authoritative.
- Pytest always pins the worktree: `PYTHONPATH=/home/sico/Code/Lemely/.claude/worktrees/student-home-variants /home/sico/Code/Lemely/.venv/bin/pytest tests/<file>.py -q`. Run from the worktree root.
- Never run the full suite: no `make test`, no bare `pytest`, no bare `npm test`/`vitest run`. Run only touched test files: `cd web && npx vitest run tests/unit/<file>.test.ts`.
- Migrations: **STOP and show the user each migration before it runs anywhere**, including the throwaway database the migration test creates. Wait for explicit approval. No agent message counts as approval.
- No secrets in files. Never write or commit `GEMINI_API_KEY`.
- Copy is the design's copy, word for word: sentence case, no em dashes, numbers in `font-mono` where the design uses `.a-mono`.
- Fidelity: a UI task is done only when all its drift scenes pass. 0 differing pixels passes. Up to 15% passes only when every difference has a written justification in the spec's "Drift log" table. Over 15% always fails. On a failure: open the diff PNG, find the rule that drifted, fix it, re-run. Never raise the threshold.
- Motion: every animation is off under `prefers-reduced-motion: reduce` and when the root has `data-motion="reduce"`. Drift scenes run with reduced motion on both sides (`?motion=reduce` on the preview, `reducedMotion: "reduce"` on the app context).
- Accessibility (spec §3): one `h2` per section as in the design. The Garden picker uses radio inputs with a legend. Marking progress is a polite live region. Plants and days carry hidden labels. Touch targets are at least 44px. Focus outlines stay visible.
- Vitest runs in the node environment with no jsdom (`web/vitest.config.ts`, decision D3.20). Component role and label tests use `renderToStaticMarkup` in `.test.ts` files, as `tests/unit/teacherTopBarSheets.test.ts` does. Keyboard behaviour is tested in Playwright against the real browser.

---

## File structure

Backend (create / modify):

| File | Responsibility |
|---|---|
| `lemely/db/migrations/versions/0052_attempt_seen_at.py` (create) | `attempts.seen_at` + backfill |
| `lemely/db/migrations/versions/0053_upload_progress.py` (create) | progress + detected-paper columns on `uploads` |
| `lemely/db/models/attempts.py` (modify) | ORM columns for both migrations |
| `lemely/core/history.py` (modify) | `PaperRecord.seen_at` |
| `lemely/db/history_repo.py` (modify) | `attempt_to_record` carries `seen_at` |
| `lemely/db/attempt_repo.py` (modify) | `AttemptRepository.mark_seen` |
| `lemely/db/upload_repo.py` (modify) | `UploadRun` progress fields, `set_progress`, `set_detected_paper` |
| `lemely/web/upload_progress.py` (create) | `UploadProgressRecorder`: bus events to progress writes |
| `lemely/db/study_plan_repo.py` (modify) | `upcoming_sessions`, `last_plan_end` |
| `lemely/web/overview_home.py` (create) | pure builders for the new overview fields |
| `lemely/web/schemas_student.py` (modify) | new DTOs and fields |
| `lemely/web/routers/student.py` (modify) | overview wiring, seen endpoint, progress wiring, `_run_dto` |
| `tests/test_migration_0052_attempt_seen_at.py`, `tests/test_migration_0053_upload_progress.py` (create) | migration round trips |
| `tests/test_student_result_seen.py`, `tests/test_upload_progress.py`, `tests/test_overview_home.py` (create) | behaviour tests |

Frontend:

| File | Responsibility |
|---|---|
| `web/src/lib/studentTypes.ts` (modify) | wire types |
| `web/src/lib/hooks/useStudentApi.ts` (modify) | `useActiveUpload({ poll })`, `useMarkResultSeen` |
| `web/src/portals/student/screens/PaperResult.tsx` (modify) | opening a result marks it seen |
| `web/src/portals/student/home/facts.ts` (create) | `toHomeView`, `toHomeFacts`, `homeState`, `pageState` |
| `web/src/portals/student/home/format.ts` (create) | date, number and article formatting |
| `web/src/portals/student/home/primitives.tsx` (create) | `Mono`, `Code`, `Vh`, `Icon`, `ButtonLink`, `GradeChip`, `Est`, motion hooks |
| `web/src/portals/student/home/{StudentHome,HomeHero,Garden,NextStepCard,GradesList,PracticeTargets,ExamsTimeline,HomeSkeleton,HomeError}.tsx` (create) | one component per design section |
| `web/dev-previews/student-home/api-fixtures.ts` (create) | API-shaped responses for the 12 data states, built on `fixtures.ts` |
| `web/scripts/home-drift/overview.mjs` (create) | Overview drift scenes + route mocks |
| `web/e2e/student-home.spec.ts` (create) | keyboard, mark-seen, axe per state |
| `web/tests/unit/studentHomeFacts.test.ts`, `studentHomeFormat.test.ts`, `studentHomeMarkup.test.ts` (create) | Vitest |
| `web/src/portals/student/index.tsx` (modify) | route switch |
| `web/src/portals/student/screens/Overview.tsx` (delete) | replaced |

`model.ts` is **not** changed. Its `HomeFacts` is the decision input shared with the preview and `fixtures.ts`. Adding fields there would change the preview's fixtures and `studentHomeModel.test.ts`. The display-only fields the spec mentions (`firstPct`, `examAvailability`, upload `progress`) go on `HomeView` in `facts.ts` instead, next to the facts. That is the spec's "add to the model types where the components need them", kept out of the shared decision type. Task 8 tests that `toHomeFacts(api)` equals `FIXTURES[state].facts` exactly.

---

## Shared interfaces (every task's implementer reads this section)

### Wire types (`web/src/lib/studentTypes.ts`, mirrored by `lemely/web/schemas_student.py`)

```ts
export type ExamAvailability = "dated" | "no_timetable" | "no_session"

/** Grade letter → boundary percentage (whole number), e.g. { C: 42, B: 55, A: 70, "A*": 85 }. */
export type GradeBoundaries = Record<string, number>

export interface SubjectRow {
  code: string
  name: string
  qualificationLevel: string | null
  detail: string
  pct: number
  papers: number
  trend: string
  grade: string
  barColor: VizColor
  trendUp: boolean
  // new
  firstPct: number | null
  previousGrade: string | null
  /** ISO date YYYY-MM-DD, the soonest dated sitting on or after today. */
  nextExamOn: string | null
  examAvailability: ExamAvailability
  boundaries: GradeBoundaries | null
  /** True when the boundaries are not the exact published ones for the latest paper. */
  boundariesEstimated: boolean
  /** ISO date of the latest grade-bearing paper. */
  lastPaperOn: string | null
}

export interface LatestResult {
  subjectCode: string
  grade: string
  /** Same addressing as GET /student/result/{paperId}: the record's index in history. */
  paperId: string
  /** "0580/42 · m/j 2024" */
  paperLabel: string
  recordedAt: string
  seen: boolean
  awarded: number
  maximum: number
}

export interface UpcomingSessionDto {
  sessionId: string
  subjectCode: string
  title: string
  minutes: number
  scheduledFor: string
}

export interface WeakTopicDto {
  topic: string
  subjectCode: string
  /** Whole percent over the subject's last 3 papers. */
  acc: number
  /** Same measure one paper earlier, or null when the topic is new. */
  previousAcc: number | null
  /** Marks lost on this topic over the subject's last 3 papers. */
  lostMarks: number
}

export interface Overview {
  studentName: string
  forecast: string
  subjects: SubjectRow[]
  weakGlobal: WeakThread[]
  momentum: Momentum
  // new
  latestResult: LatestResult | null
  upcomingSessions: UpcomingSessionDto[]
  weakTopics: WeakTopicDto[]
  /** ISO date of the last day of the student's most recent study plan, or null. */
  planEndedOn: string | null
}

export interface UploadProgress {
  stage: 1 | 2 | 3
  done: number
  total: number
}

export interface UploadRun {
  paperId: string
  status: UploadRunStatus
  filename: string | null
  startedAt: string | null
  stale: boolean
  // new
  progress: UploadProgress | null
  /** "0625/42" once scan metadata is read, else null. */
  paperLabel: string | null
  subjectCode: string | null
}
```

Python field names in `ApiModel` DTOs are camelCase, as in the existing file (`qualificationLevel`). Helper functions and repository code are snake_case.

### Endpoints

- `GET /api/student/overview` → `Overview`.
- `GET /api/student/uploads/active` → `UploadRun | null`.
- `POST /api/student/results/{paperId}/seen` → `204`. Idempotent. It returns `404 {"detail": "No paper <id>"}` for a malformed, out-of-range or foreign paper. That matches `GET /student/result/{paper_id}`'s convention: one uniform 404, no ownership oracle.

### View model (`web/src/portals/student/home/facts.ts`)

```ts
import type { HomeFacts, NextAction, BinnyMood, StreakDay } from "./model"
import type { Overview, UploadRun, UploadProgress, ExamAvailability, GradeBoundaries } from "@/lib/studentTypes"
import type { XpProfile } from "@/lib/xpTypes"

export const HOME_STATES = [
  "loading", "error", "new", "sparse0", "marking", "result-in", "one-paper",
  "sparse1", "sparse2", "sparse3", "streak-zero", "no-plan", "no-exams", "populated",
] as const
export type HomeState = (typeof HOME_STATES)[number]
export type DataState = Exclude<HomeState, "loading" | "error">

export interface SubjectView {
  code: string
  name: string            // "Mathematics"
  shortName: string       // "Maths"
  papers: number
  grade: string           // "" when papers === 0
  previousGrade: string | null
  pct: number | null      // null when papers === 0
  firstPct: number | null
  nextExamOn: string | null
  examAvailability: ExamAvailability
  boundaries: GradeBoundaries | null
  boundariesEstimated: boolean
  lastPaperOn: string | null
}

export interface WeakTopicView {
  topic: string
  subjectCode: string
  acc: number
  previousAcc: number | null
  lostMarks: number
}

export interface XpView {
  totalXp: number
  level: number
  /** XP earned inside the current level. */
  intoLevel: number
  /** XP the current level spans (nextLevelXp - levelStartXp). */
  levelSpan: number
  streak: number
  longest: number
  freezes: number
}

export interface UploadView {
  paperLabel: string | null
  subjectCode: string | null
  progress: UploadProgress | null
  stale: boolean
}

export interface HomeView {
  facts: HomeFacts
  state: DataState
  action: NextAction
  mood: BinnyMood
  week: StreakDay[]
  studentName: string
  subjects: SubjectView[]          // backend order (code order)
  weakTopics: WeakTopicView[]      // weakest first
  latestScore: { awarded: number; maximum: number } | null
  xp: XpView | null                // null when the XP query failed
  upload: UploadView | null
  planEndedOn: string | null
  totalPapers: number
}

export interface PageQueries {
  overview: { data: Overview | undefined; isPending: boolean; isError: boolean; error: unknown; dataUpdatedAt: number }
  xp: { data: XpProfile | undefined; isPending: boolean; isError: boolean }
  upload: { data: UploadRun | null | undefined; isPending: boolean; isError: boolean }
}

export type PageModel =
  | { kind: "loading" }
  | { kind: "error"; message: string }                                  // no cached data
  | { kind: "ready"; view: HomeView; stale: { at: number } | null }      // stale = refetch failed, banner over cached page

export function toHomeView(o: Overview, xp: XpProfile | null, upload: UploadRun | null, now: Date): HomeView
export function toHomeFacts(o: Overview, xp: XpProfile | null, upload: UploadRun | null, now: Date): HomeFacts
export function homeState(f: HomeFacts): DataState
export function pageState(q: PageQueries, now: Date): PageModel
export const SUBJECT_SHORT_NAMES: Readonly<Record<string, string>>
```

`PageModel.kind === "ready"` with `stale !== null` is the design's `error` state: the banner sits over the last-known page (`variant-a.css` "Error: keep the last-known page under the banner"). The data-attribute value on the root is then `data-state="error"`.

### Formatting (`web/src/portals/student/home/format.ts`)

```ts
export function dayMonth(iso: string): string            // "2027-05-04" → "4 May"
export function longDay(iso: string): string             // "2026-10-30" → "30 October"
export function weekdayShort(iso: string): string        // "2026-10-30" → "Fri"
export function dayOfMonth(iso: string): string          // "2026-10-30" → "30"
export function clockTime(ms: number): string            // local "09:41"
export function daysBetween(fromISO: string, toISO: string): number   // whole days, DST-safe
export function indefinite(word: string): "a" | "an"     // "A*"→"an", "A"→"an", "B"→"a", "Add Maths"→"an", "Physics"→"a"
export function thousands(n: number): string             // 2340 → "2,340"
export function greetingWord(now: Date): string          // re-exports greetingFor(now.getHours())
```

### Primitives (`web/src/portals/student/home/primitives.tsx`). Task 10 implements these. Every later component imports them.

```tsx
export function Mono(props: { children: React.ReactNode; className?: string }): JSX.Element          // .a-mono
export function Code(props: { children: React.ReactNode; className?: string }): JSX.Element          // .a-code
export function Vh(props: { children: React.ReactNode }): JSX.Element                                // .a-vh
export type IconName = "arrow" | "chev" | "up" | "flame"
export function Icon(props: { name: IconName; className?: string; down?: boolean }): JSX.Element     // .a-ico (+ .a-ico-down)
export function ButtonLink(props: { to: string; variant: "primary" | "tonal"; className?: string; children: React.ReactNode }): JSX.Element  // .a-btn .a-btn-primary|.a-btn-tonal
export function GradeChip(props: { grade: string; kind?: "chip" | "next" | "bud" | "stone"; className?: string }): JSX.Element
export function Est(): JSX.Element                                                                    // .a-est with its title
export function useMotionOn(): boolean        // false under prefers-reduced-motion or [data-motion="reduce"] on #sh-root
export function useCountUp(target: number, on: boolean, ms?: number): number
export function useInView<T extends Element>(): [React.RefCallback<T>, boolean]   // IntersectionObserver, once
```

### Root data attributes

`StudentHome` renders `<div id="sh-root" data-home="page" data-state={state} data-action={action.kind} data-mood={mood} data-exams={"yes"|"no"} data-motion={"full"|"reduce"}>`. These match `controller.ts`, so selectors and drift scenes line up. Every component root carries `data-home="<part>"`: `hero`, `garden`, `next`, `grades`, `weak`, `exams`, `skeleton`, `error`, `new`.

### Drift scenes (`web/scripts/home-drift/overview.mjs`). Task 9 creates it. Component tasks call it.

```js
export const OVERVIEW_STATES      // the 14 state ids, same order as fixtures.ts STATES
export const WINDOW_WIDTHS        // [390, 768, 1024, 1440, 1920]
export const THEMES               // ["light", "dark"]
export const PARTS                // { hero: {preview: ".ah-hero", app: '[data-home="hero"]'}, garden: {...}, ... page: {preview: "#as-main", app: "main"} }
export function overviewScenes({ part, states = OVERVIEW_STATES, interactions = [] })  // → Scene[] in home-drift.mjs's format
export async function mockStudentHome(page, state, overrides = {})  // page.route mocks + clock pin
```

Run one part: `cd web && node scripts/home-drift.mjs --only overview:<part>`. Expected last line: `overview:<part> PASS <n>/<n>` (n = states × 5 widths × 2 themes, + interactions). Diff images land in `web/reports/home-drift/overview/<part>/`.

---

## Task 1: Migration 0052: `attempts.seen_at`

**Files:**
- Create: `lemely/db/migrations/versions/0052_attempt_seen_at.py`
- Modify: `lemely/db/models/attempts.py` (`Attempt`, after `deleted_at` ~line 178)
- Test: `tests/test_migration_0052_attempt_seen_at.py`

**Interfaces:**
- Consumes: Alembic head `0051_tutor_evidence_uploads` on develop. Confirm with `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/alembic heads`. If the head differs (shell plan or develop added one), set `down_revision` to the real head and use the next free number.
- Produces: column `attempts.seen_at TIMESTAMPTZ NULL`; ORM `Attempt.seen_at: Mapped[datetime | None]`.

- [ ] **Step 1: Write the failing migration test**

Copy the `_server_reachable` and `_throwaway_db` helpers verbatim from `tests/test_migration_0042_question_result_source_box.py` (rename the db prefix to `lemely_mig0052_`). Then add:

```python
"""Acceptance for migration ``0052_attempt_seen_at``.

* upgrade adds ``attempts.seen_at`` (timestamptz, nullable, no default);
* upgrade backfills every pre-existing attempt with ``seen_at = recorded_at``,
  so no old result takes over a student's home after deploy;
* a row inserted after upgrade starts unseen (NULL);
* downgrade removes the column and leaves the rest of ``attempts`` unchanged.
"""

_PRE = "0051_tutor_evidence_uploads"
_REV = "0052_attempt_seen_at"


def _insert_attempt(conn: sa.Connection, recorded_at: str) -> uuid.UUID:
    user_id = uuid.uuid4()
    conn.execute(
        sa.text("INSERT INTO users (id, email, role) VALUES (:id, :email, 'student')"),
        {"id": user_id, "email": f"{user_id}@example.test"},
    )
    attempt_id = uuid.uuid4()
    conn.execute(
        sa.text(
            "INSERT INTO attempts (id, user_id, awarded_marks, maximum_marks, percentage, recorded_at) "
            "VALUES (:id, :uid, 1, 2, 50.0, CAST(:rec AS timestamptz))"
        ),
        {"id": attempt_id, "uid": user_id, "rec": recorded_at},
    )
    return attempt_id


def _columns(engine: Engine) -> dict[str, tuple[str, str, str | None]]:
    with engine.connect() as conn:
        rows = conn.execute(
            sa.text(
                "SELECT column_name, data_type, is_nullable, column_default "
                "FROM information_schema.columns WHERE table_name = 'attempts'"
            )
        ).all()
    return {r[0]: (r[1], r[2], r[3]) for r in rows}


def test_upgrade_backfills_and_new_rows_start_unseen() -> None:
    with _throwaway_db() as (cfg, engine):
        command.upgrade(cfg, _PRE)
        with engine.begin() as conn:
            old = _insert_attempt(conn, "2026-10-01T09:00:00+00:00")
        command.upgrade(cfg, _REV)
        assert _columns(engine)["seen_at"] == ("timestamp with time zone", "YES", None)
        with engine.begin() as conn:
            new = _insert_attempt(conn, "2026-11-05T09:00:00+00:00")
            seen_old, rec_old = conn.execute(
                sa.text("SELECT seen_at, recorded_at FROM attempts WHERE id = :id"), {"id": old}
            ).one()
            (seen_new,) = conn.execute(
                sa.text("SELECT seen_at FROM attempts WHERE id = :id"), {"id": new}
            ).one()
        assert seen_old == rec_old
        assert seen_new is None


def test_downgrade_restores_the_pre_migration_columns() -> None:
    with _throwaway_db() as (cfg, engine):
        command.upgrade(cfg, _PRE)
        before = _columns(engine)
        command.upgrade(cfg, _REV)
        command.downgrade(cfg, _PRE)
        assert _columns(engine) == before
```

- [ ] **Step 2: Write the migration**

```python
"""Add attempts.seen_at: when the student first opened the result.

The student home shows an unseen result in its hero ("result-in"). Rows that
exist before this migration were already shown by the old Overview, so they are
backfilled as seen at the moment they were recorded.

Revision ID: 0052_attempt_seen_at
Revises: 0051_tutor_evidence_uploads
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0052_attempt_seen_at"
down_revision: str | Sequence[str] | None = "0051_tutor_evidence_uploads"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("attempts", sa.Column("seen_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE attempts SET seen_at = recorded_at WHERE seen_at IS NULL")


def downgrade() -> None:
    op.drop_column("attempts", "seen_at")
```

Add to `Attempt` in `lemely/db/models/attempts.py`, directly after `deleted_at`:

```python
    seen_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    """When the student first opened this result (migration 0052). NULL means
    unseen: the student home shows it in the hero until it is opened. Written
    once by :meth:`AttemptRepository.mark_seen`, never cleared."""
```

- [ ] **Step 3: STOP. Show the user the migration before it runs**

Print `lemely/db/migrations/versions/0052_attempt_seen_at.py` and the SQL it will emit:

```bash
PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/alembic upgrade 0051_tutor_evidence_uploads:0052_attempt_seen_at --sql
```

Ask the user to approve it, and point out the backfill (`seen_at = recorded_at` for every existing attempt). Do not run Step 4 until the user says yes in the conversation. If they decline, stop the plan and report.

- [ ] **Step 4: Run the migration test**

Run: `PYTHONPATH=/home/sico/Code/Lemely/.claude/worktrees/student-home-variants /home/sico/Code/Lemely/.venv/bin/pytest tests/test_migration_0052_attempt_seen_at.py -q`
Expected: `2 passed` (or `2 skipped` with "local Postgres not reachable". In that case start local Postgres (`supabase start`) and re-run, because a skip is not a pass).

Then run any model/migration sync test the repo has (`grep -l compare_metadata tests/*.py`). Expected: pass.

- [ ] **Step 5: Commit**

```bash
/home/sico/Code/Lemely/.venv/bin/pre-commit run --files lemely/db/migrations/versions/0052_attempt_seen_at.py lemely/db/models/attempts.py tests/test_migration_0052_attempt_seen_at.py
git commit -S -m "feat(student): add attempts.seen_at for unseen results" -- lemely/db/migrations/versions/0052_attempt_seen_at.py lemely/db/models/attempts.py tests/test_migration_0052_attempt_seen_at.py
```

---

## Task 2: Migration 0053: upload progress columns

**Files:**
- Create: `lemely/db/migrations/versions/0053_upload_progress.py`
- Modify: `lemely/db/models/attempts.py` (`Upload`, after `deleted_at` ~line 87)
- Test: `tests/test_migration_0053_upload_progress.py`

**Interfaces:**
- Consumes: revision `0052_attempt_seen_at` (Task 1).
- Produces: `uploads.progress_stage SMALLINT NULL CHECK (1..3)`, `uploads.progress_done INT NULL CHECK (>= 0)`, `uploads.progress_total INT NULL CHECK (>= 0)`, `uploads.detected_paper_label VARCHAR NULL`, `uploads.detected_subject_code VARCHAR NULL`. The ORM attributes have the same names.

The two `detected_*` columns are needed by design A. The marking card says "`0625/42` is being marked", the Garden marks that subject "Marking now", and the grades row says "Your first grade lands here when `0580/42` is marked". `UploadRunDTO` today carries only the filename. Show these two columns in the stop gate as part of migration 2. They are this plan's addition to the spec's "stage, done, total".

- [ ] **Step 1: Write the failing migration test**

Same helpers as Task 1 (db prefix `lemely_mig0053_`). Then:

```python
"""Acceptance for migration ``0053_upload_progress``.

* upgrade adds the five nullable columns to ``uploads``;
* stage outside 1..3 and negative counts are rejected by the database;
* a valid row round-trips;
* downgrade restores the pre-migration column set and drops the CHECKs.
"""

_PRE = "0052_attempt_seen_at"
_REV = "0053_upload_progress"
_NEW = ("progress_stage", "progress_done", "progress_total", "detected_paper_label", "detected_subject_code")


def _columns(engine: Engine) -> dict[str, tuple[str, str, str | None]]:
    with engine.connect() as conn:
        rows = conn.execute(
            sa.text(
                "SELECT column_name, data_type, is_nullable, column_default "
                "FROM information_schema.columns WHERE table_name = 'uploads'"
            )
        ).all()
    return {r[0]: (r[1], r[2], r[3]) for r in rows}


def _insert_upload(engine: Engine, stage: int | None, done: int | None, total: int | None) -> uuid.UUID:
    upload_id = uuid.uuid4()
    with engine.begin() as conn:
        user_id = uuid.uuid4()
        conn.execute(
            sa.text("INSERT INTO users (id, email, role) VALUES (:id, :email, 'student')"),
            {"id": user_id, "email": f"{user_id}@example.test"},
        )
        conn.execute(
            sa.text(
                "INSERT INTO uploads (id, user_id, storage_path, progress_stage, progress_done, "
                "progress_total, detected_paper_label, detected_subject_code) "
                "VALUES (:id, :uid, 'k', :s, :d, :t, '0625/42', '0625')"
            ),
            {"id": upload_id, "uid": user_id, "s": stage, "d": done, "t": total},
        )
    return upload_id


def test_upgrade_adds_nullable_columns_and_round_trips() -> None:
    with _throwaway_db() as (cfg, engine):
        command.upgrade(cfg, _REV)
        cols = _columns(engine)
        for name in _NEW:
            assert cols[name][1] == "YES", name
        upload_id = _insert_upload(engine, 3, 7, 12)
        with engine.connect() as conn:
            row = conn.execute(
                sa.text("SELECT progress_stage, progress_done, progress_total, detected_paper_label FROM uploads WHERE id = :id"),
                {"id": upload_id},
            ).one()
        assert tuple(row) == (3, 7, 12, "0625/42")


@pytest.mark.parametrize(("stage", "done", "total"), [(0, 0, 0), (4, 0, 0), (1, -1, 0), (1, 0, -1)])
def test_out_of_range_progress_is_rejected(stage: int, done: int, total: int) -> None:
    with _throwaway_db() as (cfg, engine):
        command.upgrade(cfg, _REV)
        with pytest.raises(IntegrityError):
            _insert_upload(engine, stage, done, total)


def test_downgrade_restores_columns() -> None:
    with _throwaway_db() as (cfg, engine):
        command.upgrade(cfg, _PRE)
        before = _columns(engine)
        command.upgrade(cfg, _REV)
        command.downgrade(cfg, _PRE)
        assert _columns(engine) == before
```

- [ ] **Step 2: Write the migration and ORM columns**

```python
"""Add marking progress and the detected paper to uploads.

The marking run writes its stage (1 finding paper and scheme, 2 reading answers,
3 marking questions) and done/total counts here, so a reloaded student home can
say "Marking question 7 of 12". ``detected_paper_label`` / ``detected_subject_code``
hold what scan metadata found ("0625/42", "0625") so the home can name the paper.

Revision ID: 0053_upload_progress
Revises: 0052_attempt_seen_at
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0053_upload_progress"
down_revision: str | Sequence[str] | None = "0052_attempt_seen_at"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("uploads", sa.Column("progress_stage", sa.SmallInteger(), nullable=True))
    op.add_column("uploads", sa.Column("progress_done", sa.Integer(), nullable=True))
    op.add_column("uploads", sa.Column("progress_total", sa.Integer(), nullable=True))
    op.add_column("uploads", sa.Column("detected_paper_label", sa.String(), nullable=True))
    op.add_column("uploads", sa.Column("detected_subject_code", sa.String(), nullable=True))
    op.create_check_constraint("progress_stage_range", "uploads", "progress_stage BETWEEN 1 AND 3")
    op.create_check_constraint(
        "progress_counts_non_negative", "uploads", "progress_done >= 0 AND progress_total >= 0"
    )


def downgrade() -> None:
    op.drop_constraint("progress_counts_non_negative", "uploads", type_="check")
    op.drop_constraint("progress_stage_range", "uploads", type_="check")
    for name in ("detected_subject_code", "detected_paper_label", "progress_total", "progress_done", "progress_stage"):
        op.drop_column("uploads", name)
```

The naming convention in `lemely/db/base.py` may rewrite the constraint names (see the 0042 test docstring). If `downgrade` cannot find them, drop them by the name `alembic upgrade --sql` printed in Step 3.

In `Upload` (`lemely/db/models/attempts.py`), after `deleted_at`:

```python
    progress_stage: Mapped[int | None] = mapped_column(sa.SmallInteger, nullable=True)
    """Marking stage while ``status`` is processing: 1 paper and scheme, 2 answers,
    3 questions (migration 0053). Written by
    :class:`~lemely.web.upload_progress.UploadProgressRecorder` without moving
    ``updated_at``, which is the run's start time."""
    progress_done: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    progress_total: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    detected_paper_label: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    detected_subject_code: Mapped[str | None] = mapped_column(sa.String, nullable=True)
```

Add the two CHECKs to `Upload.__table_args__` as `sa.CheckConstraint("progress_stage BETWEEN 1 AND 3", name="progress_stage_range")` and `sa.CheckConstraint("progress_done >= 0 AND progress_total >= 0", name="progress_counts_non_negative")`. Then the ORM metadata matches the migration.

- [ ] **Step 3: STOP. Show the user the migration before it runs**

```bash
PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/alembic upgrade 0052_attempt_seen_at:0053_upload_progress --sql
```

Show the file and the SQL. Name the two `detected_*` columns as additions beyond the spec's "stage, done, total", and give the reason from the Interfaces note above. Wait for explicit approval in the conversation.

- [ ] **Step 4: Run the test**

Run: `PYTHONPATH=/home/sico/Code/Lemely/.claude/worktrees/student-home-variants /home/sico/Code/Lemely/.venv/bin/pytest tests/test_migration_0053_upload_progress.py -q`
Expected: `6 passed`. Re-run the metadata sync test from Task 1 Step 4. Expected: pass.

- [ ] **Step 5: Commit**

```bash
/home/sico/Code/Lemely/.venv/bin/pre-commit run --files lemely/db/migrations/versions/0053_upload_progress.py lemely/db/models/attempts.py tests/test_migration_0053_upload_progress.py
git commit -S -m "feat(student): add marking progress columns to uploads" -- lemely/db/migrations/versions/0053_upload_progress.py lemely/db/models/attempts.py tests/test_migration_0053_upload_progress.py
```

---

## Task 3: Mark a result seen

**Files:**
- Modify: `lemely/core/history.py` (`PaperRecord`, after `attempt_id`)
- Modify: `lemely/db/history_repo.py:158-215` (`attempt_to_record`)
- Modify: `lemely/db/attempt_repo.py` (new method on `AttemptRepository`)
- Modify: `lemely/web/routers/student.py` (new route after `student_result`, ~line 614)
- Test: `tests/test_student_result_seen.py`

**Interfaces:**
- Consumes: `Attempt.seen_at` (Task 1); `migrated_sessionmaker` fixture (`tests/conftest.py:617`).
- Produces:
  - `PaperRecord.seen_at: str | None = None` (ISO-8601 UTC).
  - `AttemptRepository.mark_seen(self, *, user_id: str, attempt_id: str, now: datetime | None = None) -> bool`: True when the attempt belongs to `user_id` (stamped now or earlier), False otherwise.
  - `POST /api/student/results/{paper_id}/seen` → 204 / 404.

- [ ] **Step 1: Write the failing tests**

```python
"""POST /api/student/results/{paperId}/seen (spec 2026-11-06 §1).

Idempotent; stamps seen_at once; another student's paper is a uniform 404 like
GET /student/result/{paper_id}.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from lemely.core.history import PaperRecord
from lemely.core.schemas import ExamMetadata
from lemely.db.attempt_repo import AttemptRepository
from lemely.db.history_repo import DbHistoryStore
from lemely.db.models import Attempt
from lemely.db.models.users import User
from lemely.web import create_app
from lemely.web.deps import AuthContext, get_attempt_repo, get_auth_context, get_history_store


def _student(sm: sessionmaker[Session]) -> str:
    uid = uuid.uuid4()
    with sm.begin() as s:
        s.add(User(id=uid, email=f"{uid}@example.test", role="student"))
    return str(uid)


def _paper(store: DbHistoryStore, student: str, recorded_at: str = "2026-11-05T09:52:00+00:00") -> None:
    store.append(
        student,
        PaperRecord(
            student_id=student,
            metadata=ExamMetadata(subject_code="0580", paper_number=4, paper_variant=2,
                                  session_month="May/June", session_year=2024),
            awarded_marks=37, maximum_marks=80, percentage=46.25, grade="C",
            weak_areas=[], recorded_at=recorded_at,
        ),
    )


def _client(sm: sessionmaker[Session], student: str) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_history_store] = lambda: DbHistoryStore(sm)
    app.dependency_overrides[get_attempt_repo] = lambda: AttemptRepository(sm)
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(user_id=student, role="student")
    return TestClient(app)


def _seen_at(sm: sessionmaker[Session], student: str) -> datetime | None:
    with sm() as s:
        return s.query(Attempt).filter(Attempt.user_id == uuid.UUID(student)).one().seen_at


def test_new_attempt_loads_unseen(migrated_sessionmaker: sessionmaker[Session]) -> None:
    student = _student(migrated_sessionmaker)
    store = DbHistoryStore(migrated_sessionmaker)
    _paper(store, student)
    assert store.load(student).records[0].seen_at is None


def test_seen_stamps_once_and_is_idempotent(migrated_sessionmaker: sessionmaker[Session]) -> None:
    student = _student(migrated_sessionmaker)
    _paper(DbHistoryStore(migrated_sessionmaker), student)
    client = _client(migrated_sessionmaker, student)

    assert client.post("/api/student/results/0/seen").status_code == 204
    first = _seen_at(migrated_sessionmaker, student)
    assert first is not None
    assert client.post("/api/student/results/0/seen").status_code == 204
    assert _seen_at(migrated_sessionmaker, student) == first


@pytest.mark.parametrize("paper_id", ["1", "-1", "abc"])
def test_unknown_paper_is_404(migrated_sessionmaker: sessionmaker[Session], paper_id: str) -> None:
    student = _student(migrated_sessionmaker)
    _paper(DbHistoryStore(migrated_sessionmaker), student)
    response = _client(migrated_sessionmaker, student).post(f"/api/student/results/{paper_id}/seen")
    assert response.status_code == 404
    assert response.json() == {"detail": f"No paper {paper_id}"}


def test_another_students_paper_is_404_and_untouched(migrated_sessionmaker: sessionmaker[Session]) -> None:
    owner = _student(migrated_sessionmaker)
    intruder = _student(migrated_sessionmaker)
    _paper(DbHistoryStore(migrated_sessionmaker), owner)

    response = _client(migrated_sessionmaker, intruder).post("/api/student/results/0/seen")

    assert response.status_code == 404
    assert _seen_at(migrated_sessionmaker, owner) is None


def test_repo_refuses_a_foreign_attempt_id(migrated_sessionmaker: sessionmaker[Session]) -> None:
    owner = _student(migrated_sessionmaker)
    intruder = _student(migrated_sessionmaker)
    store = DbHistoryStore(migrated_sessionmaker)
    _paper(store, owner)
    attempt_id = store.load(owner).records[0].attempt_id
    assert attempt_id is not None
    repo = AttemptRepository(migrated_sessionmaker)

    assert repo.mark_seen(user_id=intruder, attempt_id=attempt_id) is False
    assert _seen_at(migrated_sessionmaker, owner) is None
    assert repo.mark_seen(user_id=owner, attempt_id=attempt_id, now=datetime(2026, 11, 5, tzinfo=UTC)) is True
    assert _seen_at(migrated_sessionmaker, owner) == datetime(2026, 11, 5, tzinfo=UTC)
```

If `User`'s import path or constructor fields differ, copy the user-insert helper used by `tests/test_student_deletion_routes.py`.

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=/home/sico/Code/Lemely/.claude/worktrees/student-home-variants /home/sico/Code/Lemely/.venv/bin/pytest tests/test_student_result_seen.py -q`
Expected: FAIL. `PaperRecord` has no `seen_at`; the route returns 404/405.

- [ ] **Step 3: Implement**

`lemely/core/history.py`, in `PaperRecord` after `attempt_id`:

```python
    seen_at: str | None = None
    """ISO-8601 UTC moment the student first opened this result; None when unseen
    or when the store has no attempts table (the JSON file store)."""
```

`lemely/db/history_repo.py`, in `attempt_to_record`'s `PaperRecord(...)` call after `attempt_id=`:

```python
        seen_at=attempt.seen_at.isoformat() if attempt.seen_at is not None else None,
```

`lemely/db/attempt_repo.py`, a method on `AttemptRepository` (imports: `uuid`; `Attempt` is already imported from `lemely.db.models.attempts`):

```python
    def mark_seen(self, *, user_id: str, attempt_id: str, now: datetime | None = None) -> bool:
        """Stamp ``seen_at`` once on the caller's own attempt.

        Returns True when the attempt is ``user_id``'s, whether it was stamped
        now or before (idempotent), and False for a malformed, unknown or
        foreign id, so the router answers all three with one 404.
        """
        owner = parse_user_id(user_id)
        try:
            target = uuid.UUID(attempt_id)
        except (ValueError, AttributeError, TypeError):
            return False
        moment = now or datetime.now(UTC)
        with self._sm.begin() as session:
            row = session.scalars(
                select(Attempt).where(Attempt.id == target, Attempt.user_id == owner)
            ).one_or_none()
            if row is None:
                return False
            if row.seen_at is None:
                row.seen_at = moment
            return True
```

`lemely/web/routers/student.py`, after `student_result`:

```python
@router.post("/student/results/{paper_id}/seen", status_code=204)
def student_mark_result_seen(
    paper_id: str,
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    history_store: Annotated[HistoryStoreProtocol, Depends(get_history_store)],
    attempt_repo: Annotated[AttemptRepository, Depends(get_attempt_repo)],
) -> Response:
    """Mark the caller's result ``paper_id`` (a history index) as opened.

    Same addressing and the same uniform 404 as ``GET /student/result/{paper_id}``.
    A file-store record has no attempt row to stamp, so it is already "seen"
    and answers 204 without a write.
    """
    history = history_store.load(auth.user_id)
    try:
        index = int(paper_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=f"No paper {paper_id}") from exc
    if index < 0 or index >= len(history.records):
        raise HTTPException(status_code=404, detail=f"No paper {paper_id}")
    attempt_id = history.records[index].attempt_id
    if attempt_id is not None and not attempt_repo.mark_seen(user_id=auth.user_id, attempt_id=attempt_id):
        raise HTTPException(status_code=404, detail=f"No paper {paper_id}")
    return Response(status_code=204)
```

- [ ] **Step 4: Run the tests**

Run: `PYTHONPATH=/home/sico/Code/Lemely/.claude/worktrees/student-home-variants /home/sico/Code/Lemely/.venv/bin/pytest tests/test_student_result_seen.py tests/test_web_student.py -q`
Expected: all pass. `test_web_student.py` guards the existing result route.

- [ ] **Step 5: Commit**

```bash
/home/sico/Code/Lemely/.venv/bin/pre-commit run --files lemely/core/history.py lemely/db/history_repo.py lemely/db/attempt_repo.py lemely/web/routers/student.py tests/test_student_result_seen.py
git commit -S -m "feat(student): mark a result seen when it is opened" -- lemely/core/history.py lemely/db/history_repo.py lemely/db/attempt_repo.py lemely/web/routers/student.py tests/test_student_result_seen.py
```

---

## Task 4: Persist marking progress

**Files:**
- Modify: `lemely/db/upload_repo.py` (`UploadRun`, `_to_run`, new `set_progress`, `set_detected_paper`)
- Create: `lemely/web/upload_progress.py`
- Modify: `lemely/web/schemas_student.py` (`UploadProgressDTO`, `UploadRunDTO`)
- Modify: `lemely/web/routers/student.py` (`_run_dto` ~line 769; `student_correct.run()` ~lines 1031-1100)
- Test: `tests/test_upload_progress.py`

**Interfaces:**
- Consumes: columns from Task 2; `lemely.runtime.events.bus`, `EventType.EXTRACTION_PROGRESS` (payload `index`, `total`, `lemely/io/answer_extraction.py:1365`), `EventType.MARKING_PROGRESS` (payload `index`, `total`; the final summary frame has neither), `current_run_id`.
- Produces:
  - `UploadRun` gains `progress_stage: int | None`, `progress_done: int | None`, `progress_total: int | None`, `detected_paper_label: str | None`, `detected_subject_code: str | None`.
  - `StudentUploadRepository.set_progress(self, upload_id: uuid.UUID, *, stage: int, done: int, total: int) -> None` and `set_detected_paper(self, upload_id: uuid.UUID, *, label: str, subject_code: str) -> None`. Neither moves `updated_at`.
  - `class UploadProgressRecorder(repo, upload_id, *, run_id)` with `start()`, `on_extraction(**payload)`, `on_marking(**payload)`, and context-manager use that subscribes and unsubscribes.
  - `UploadRunDTO.progress: UploadProgressDTO | None`, `.paperLabel: str | None`, `.subjectCode: str | None`.

`set_status` relies on `updated_at` to date the start of a run (`UploadRun` docstring). Progress writes pass `updated_at=Upload.updated_at`, which overrides `TimestampMixin.onupdate`, so `startedAt` and `stale` keep their meaning.

- [ ] **Step 1: Write the failing tests**

```python
"""Marking progress persisted on the upload row (spec 2026-11-06 §1)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session, sessionmaker

from lemely.db.models import Upload
from lemely.db.models.enums import UploadStatus
from lemely.db.models.users import User
from lemely.db.upload_repo import StudentUploadRepository, UploadRun
from lemely.runtime.events import EventType, bus, current_run_id
from lemely.web.routers.student import _run_dto
from lemely.web.upload_progress import UploadProgressRecorder


def _upload(sm: sessionmaker[Session]) -> tuple[str, uuid.UUID]:
    uid, upload_id = uuid.uuid4(), uuid.uuid4()
    with sm.begin() as s:
        s.add(User(id=uid, email=f"{uid}@example.test", role="student"))
        s.add(Upload(id=upload_id, user_id=uid, storage_path="k", original_filename="scan.jpg"))
    return str(uid), upload_id


def test_set_progress_keeps_started_at(migrated_sessionmaker: sessionmaker[Session]) -> None:
    repo = StudentUploadRepository(migrated_sessionmaker)
    user, upload_id = _upload(migrated_sessionmaker)
    repo.set_status(upload_id, UploadStatus.processing)
    before = repo.get_run(user_id=user, upload_id=str(upload_id))
    assert before is not None

    repo.set_progress(upload_id, stage=3, done=7, total=12)
    repo.set_detected_paper(upload_id, label="0625/42", subject_code="0625")

    after = repo.get_run(user_id=user, upload_id=str(upload_id))
    assert after is not None
    assert after.started_at == before.started_at
    assert (after.progress_stage, after.progress_done, after.progress_total) == (3, 7, 12)
    assert (after.detected_paper_label, after.detected_subject_code) == ("0625/42", "0625")


def test_recorder_maps_events_to_stages_for_its_own_run_only(migrated_sessionmaker: sessionmaker[Session]) -> None:
    repo = StudentUploadRepository(migrated_sessionmaker)
    user, upload_id = _upload(migrated_sessionmaker)
    token = current_run_id.set("student:mine")
    try:
        with UploadProgressRecorder(repo, upload_id, run_id="student:mine") as rec:
            rec.start()
            assert repo.get_run(user_id=user, upload_id=str(upload_id)).progress_stage == 1
            bus.publish(EventType.EXTRACTION_PROGRESS, question_id="1", index=0, total=12)
            run = repo.get_run(user_id=user, upload_id=str(upload_id))
            assert (run.progress_stage, run.progress_done, run.progress_total) == (2, 1, 12)
            bus.publish(EventType.MARKING_PROGRESS, question_id="7", index=6, total=12)
            bus.publish(EventType.MARKING_PROGRESS, phase="complete")  # summary frame: ignored
            run = repo.get_run(user_id=user, upload_id=str(upload_id))
            assert (run.progress_stage, run.progress_done, run.progress_total) == (3, 7, 12)
        other = current_run_id.set("student:other")
        try:
            bus.publish(EventType.MARKING_PROGRESS, question_id="8", index=7, total=12)
        finally:
            current_run_id.reset(other)
    finally:
        current_run_id.reset(token)
    assert repo.get_run(user_id=user, upload_id=str(upload_id)).progress_done == 7


def _run(status: UploadStatus, stage: int | None) -> UploadRun:
    return UploadRun(
        id=uuid.uuid4(), status=status, original_filename="scan.jpg",
        started_at=datetime(2026, 11, 5, 9, 58, tzinfo=UTC),
        progress_stage=stage, progress_done=7 if stage else None, progress_total=12 if stage else None,
        detected_paper_label="0625/42", detected_subject_code="0625",
    )


def test_dto_carries_progress_only_while_processing() -> None:
    now = datetime(2026, 11, 5, 10, 0, tzinfo=UTC)
    live = _run_dto(_run(UploadStatus.processing, 3), now=now)
    assert live.progress is not None and (live.progress.stage, live.progress.done, live.progress.total) == (3, 7, 12)
    assert (live.paperLabel, live.subjectCode) == ("0625/42", "0625")
    assert _run_dto(_run(UploadStatus.complete, 3), now=now).progress is None
    assert _run_dto(_run(UploadStatus.processing, None), now=now).progress is None
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=/home/sico/Code/Lemely/.claude/worktrees/student-home-variants /home/sico/Code/Lemely/.venv/bin/pytest tests/test_upload_progress.py -q`
Expected: FAIL with `ImportError: lemely.web.upload_progress`.

- [ ] **Step 3: Implement the repository**

In `lemely/db/upload_repo.py`, extend the dataclass (keep field order; new fields default to None so existing constructors still work):

```python
@dataclass(frozen=True, slots=True)
class UploadRun:
    ...existing docstring...
    id: uuid.UUID
    status: UploadStatus
    original_filename: str | None
    started_at: datetime
    progress_stage: int | None = None
    progress_done: int | None = None
    progress_total: int | None = None
    detected_paper_label: str | None = None
    detected_subject_code: str | None = None
```

Methods on `StudentUploadRepository` (add `from sqlalchemy import update`):

```python
    def set_progress(self, upload_id: uuid.UUID, *, stage: int, done: int, total: int) -> None:
        """Record the run's stage and counts without moving ``updated_at``.

        ``updated_at`` is the run's start time while it is processing
        (:class:`UploadRun`); passing it back to itself overrides
        ``TimestampMixin.onupdate`` so progress never resets the stale clock.
        """
        with self._sm.begin() as session:
            session.execute(
                update(Upload)
                .where(Upload.id == upload_id)
                .values(progress_stage=stage, progress_done=done, progress_total=total,
                        updated_at=Upload.updated_at)
            )

    def set_detected_paper(self, upload_id: uuid.UUID, *, label: str, subject_code: str) -> None:
        """Record the paper scan metadata found ("0625/42", "0625"); keeps ``updated_at``."""
        with self._sm.begin() as session:
            session.execute(
                update(Upload)
                .where(Upload.id == upload_id)
                .values(detected_paper_label=label, detected_subject_code=subject_code,
                        updated_at=Upload.updated_at)
            )
```

`_to_run` adds the five fields from the row.

- [ ] **Step 4: Implement the recorder**

`lemely/web/upload_progress.py`:

```python
"""Persist a marking run's progress so a reloaded page can report it.

The SSE frames live on a process-global bus with no replay. This recorder
listens to the same frames for one run and writes stage/done/total to the
upload row: stage 1 when the run starts (finding the paper and mark scheme),
stage 2 per answer read (``extraction_progress``), stage 3 per question marked
(``marking_progress``). Bus callbacks run on the publishing thread, so
``current_run_id`` tells this run's frames from another run's.
"""

from __future__ import annotations

import uuid
from types import TracebackType
from typing import Any, Self

from lemely.db.upload_repo import StudentUploadRepository
from lemely.runtime.events import EventType, bus, current_run_id


class UploadProgressRecorder:
    """Subscribe for one run; write only when (stage, done, total) changes."""

    def __init__(self, repo: StudentUploadRepository, upload_id: uuid.UUID, *, run_id: str) -> None:
        self._repo = repo
        self._upload_id = upload_id
        self._run_id = run_id
        self._last: tuple[int, int, int] | None = None

    def __enter__(self) -> Self:
        bus.subscribe(EventType.EXTRACTION_PROGRESS, self.on_extraction)
        bus.subscribe(EventType.MARKING_PROGRESS, self.on_marking)
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None) -> None:
        bus.unsubscribe(EventType.EXTRACTION_PROGRESS, self.on_extraction)
        bus.unsubscribe(EventType.MARKING_PROGRESS, self.on_marking)

    def start(self) -> None:
        self._write(1, 0, 0)

    def on_extraction(self, **payload: Any) -> None:  # noqa: ANN401
        self._from_frame(2, payload)

    def on_marking(self, **payload: Any) -> None:  # noqa: ANN401
        self._from_frame(3, payload)

    def _from_frame(self, stage: int, payload: dict[str, Any]) -> None:
        if current_run_id.get() != self._run_id:
            return
        index, total = payload.get("index"), payload.get("total")
        if not isinstance(index, int) or not isinstance(total, int):
            return
        self._write(stage, index + 1, total)

    def _write(self, stage: int, done: int, total: int) -> None:
        if self._last == (stage, done, total):
            return
        self._last = (stage, done, total)
        self._repo.set_progress(self._upload_id, stage=stage, done=done, total=total)
```

Progress is best-effort. Wrap `_write`'s repo call so a database error is logged (`structlog.get_logger(__name__).warning("upload_progress_write_failed", ...)`) and swallowed. A progress write must never fail a marking run.

- [ ] **Step 5: DTO and wiring**

`lemely/web/schemas_student.py`. Add before `UploadRunDTO`, then extend it and replace its "deliberately carries no per-question progress" paragraph with one saying progress is now persisted by `UploadProgressRecorder`:

```python
class UploadProgressDTO(ApiModel):
    """Where a processing run is: stage 1 paper and scheme, 2 answers, 3 questions."""

    stage: Literal[1, 2, 3]
    done: int
    total: int
```

```python
    progress: UploadProgressDTO | None = None
    paperLabel: str | None = None
    subjectCode: str | None = None
```

`_run_dto` in `lemely/web/routers/student.py`:

```python
    progress = (
        UploadProgressDTO(stage=run.progress_stage, done=run.progress_done or 0, total=run.progress_total or 0)
        if processing and run.progress_stage in (1, 2, 3)
        else None
    )
    return UploadRunDTO(
        paperId=str(run.id),
        status=run.status.value,
        filename=run.original_filename,
        startedAt=run.started_at if processing else None,
        stale=processing and (moment - run.started_at) > MARKING_RUN_STALE_AFTER,
        progress=progress,
        paperLabel=run.detected_paper_label,
        subjectCode=run.detected_subject_code,
    )
```

In `student_correct`'s `run()`, right after `upload_repo.set_status(owned.id, UploadStatus.processing)`:

```python
            recorder = UploadProgressRecorder(upload_repo, owned.id, run_id=f"student:{payload.paperId}")
            with recorder:
                recorder.start()
                ...the existing `with tempfile.TemporaryDirectory()` block, indented one level...
```

After `metadata = ScanMetadataExtractor(gemini_client)(scan_path)` succeeds:

```python
                            if metadata is not None:
                                upload_repo.set_detected_paper(
                                    owned.id,
                                    label=f"{metadata.subject_code}/{metadata.paper_number}{metadata.paper_variant}",
                                    subject_code=metadata.subject_code,
                                )
```

The `run_id` string must equal the one passed to `bus_event_stream(run, run_id=...)` (line ~1267). Use a shared local `run_id = f"student:{payload.paperId}"` for both.

- [ ] **Step 6: Run the tests**

Run: `PYTHONPATH=/home/sico/Code/Lemely/.claude/worktrees/student-home-variants /home/sico/Code/Lemely/.venv/bin/pytest tests/test_upload_progress.py tests/test_student_correct.py tests/test_web_student.py -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
/home/sico/Code/Lemely/.venv/bin/pre-commit run --files lemely/db/upload_repo.py lemely/web/upload_progress.py lemely/web/schemas_student.py lemely/web/routers/student.py tests/test_upload_progress.py
git commit -S -m "feat(student): persist marking progress on the upload" -- lemely/db/upload_repo.py lemely/web/upload_progress.py lemely/web/schemas_student.py lemely/web/routers/student.py tests/test_upload_progress.py
```

---

## Task 5: Overview subject fields

**Files:**
- Create: `lemely/web/overview_home.py`
- Modify: `lemely/web/schemas_student.py` (`SubjectRowDTO`)
- Modify: `lemely/web/routers/student.py` (`_subjects` ~line 246, `student_overview` ~line 313)
- Test: `tests/test_overview_home.py`

**Interfaces:**
- Consumes: `GradeBoundaryStore.resolve(metadata) -> (dict[str, float], "exact"|"subject_default"|"global_default")`; `ExamCalendarService.calendar_for_student(student_id) -> StudentExamCalendar` (`entries[].subject_code`, `.availability`, `.dates[].exam_date`); `get_exam_calendar_service`, `get_user_zone_reader`, `civil_date_in_zone`.
- Produces (pure, in `lemely/web/overview_home.py`):
  - `ExamAvailability = Literal["dated", "no_timetable", "no_session"]`
  - `exam_fields(calendar: StudentExamCalendar | None, code: str, today: date) -> tuple[date | None, ExamAvailability]`
  - `previous_grade(records: list[PaperRecord], boundaries: dict[str, float]) -> str | None`
  - `rounded_boundaries(boundaries: dict[str, float]) -> dict[str, int]`
  - `SubjectRowDTO` new fields as in Shared interfaces. Enrolled subjects with no paper appear as rows with `papers=0, pct=0, grade="", trend="", barColor="t3", trendUp=False, detail="No papers yet", firstPct=None, boundaries=None`.

Rules:
- `firstPct = round(records[0].percentage)`; `lastPaperOn = date of records[-1].recorded_at`.
- `previousGrade` = the grade of the mark-weighted percentage over `records[:-1]`, using the latest paper's boundaries; `None` with one paper.
- `boundariesEstimated = source != "exact"`.
- `exam_fields`: the soonest `exam_date >= today` among the subject's entries → `(date, "dated")`; else `"no_timetable"` if any entry says so; else `(None, "no_session")`. A subject with no declared paper has no entries, which is also "no_session" (the student has not said which session they sit).
- `today` is the student's civil date (`civil_date_in_zone(datetime.now(UTC), zone=zones.zone_for(user_id))`). For a non-UUID test id, use the UTC date and skip the calendar (calendar `None`), the same guard as the route's existing mirror lookup.

- [ ] **Step 1: Write the failing tests**

```python
"""New GET /student/overview fields (spec 2026-11-06 §1)."""

from __future__ import annotations

import uuid
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from lemely.core.history import PaperRecord
from lemely.core.schemas import ExamMetadata, WeakArea
from lemely.db.exam_calendar_repo import ExamDateRow, StudentExamCalendar, StudentExamEntry
from lemely.io.history_store import HistoryStore
from lemely.web import create_app
from lemely.web.deps import (
    AuthContext, get_auth_context, get_exam_calendar_service, get_history_store,
    get_student_profile_service, get_study_plan_service, get_user_mirror, get_user_zone_reader,
)
from lemely.web.overview_home import exam_fields, previous_grade

STUDENT = str(uuid.UUID(int=7))
TODAY = date(2026, 11, 5)


def _rec(
    code: str, pct: float, awarded: int, recorded: str, weak: list[WeakArea] | None = None, grade: str = "C"
) -> PaperRecord:
    # grade must be in GRADE_ORDER: is_grade_bearing() ignores records without one.
    return PaperRecord(
        student_id=STUDENT,
        metadata=ExamMetadata(subject_code=code, paper_number=4, paper_variant=2,
                              session_month="May/June", session_year=2024),
        awarded_marks=awarded, maximum_marks=80, percentage=pct, grade=grade, weak_areas=weak or [],
        recorded_at=recorded,
    )


def _entry(code: str, availability: str, dates: list[date]) -> StudentExamEntry:
    return StudentExamEntry(
        subject_code=code, session_month=None, session_year=2027, paper_number=4,
        availability=availability,  # type: ignore[arg-type]
        dates=[ExamDateRow(paper_variant="2", exam_date=d, starts_at_local=None,
                           duration_minutes=None, source="test") for d in dates],
    )


def test_exam_fields_picks_soonest_future_date() -> None:
    cal = StudentExamCalendar(availability="available", entries=[
        _entry("0580", "dated", [date(2026, 6, 1), date(2027, 5, 12), date(2027, 5, 20)]),
    ])
    assert exam_fields(cal, "0580", TODAY) == (date(2027, 5, 12), "dated")


@pytest.mark.parametrize(("entries", "expected"), [
    ([], "no_session"),
    ([_entry("0625", "no_session", [])], "no_session"),
    ([_entry("0625", "no_timetable", [])], "no_timetable"),
    ([_entry("0625", "dated", [date(2026, 6, 1)])], "no_session"),  # only past dates
])
def test_exam_fields_reason_when_no_date(entries: list[StudentExamEntry], expected: str) -> None:
    cal = StudentExamCalendar(availability="no_timetable", entries=entries)
    assert exam_fields(cal, "0625", TODAY) == (None, expected)


def test_exam_fields_without_calendar() -> None:
    assert exam_fields(None, "0580", TODAY) == (None, "no_session")


def test_previous_grade_uses_all_but_the_latest_paper() -> None:
    bounds = {"A*": 85.0, "A": 70.0, "B": 55.0, "C": 42.0}
    recs = [_rec("0580", 46.0, 37, "2026-10-01T10:00:00+00:00"), _rec("0580", 70.0, 56, "2026-11-04T10:00:00+00:00")]
    assert previous_grade(recs, bounds) == "C"
    assert previous_grade(recs[:1], bounds) is None


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    store = HistoryStore(tmp_path / "history")
    store.append(STUDENT, _rec("0580", 46.0, 37, "2026-10-01T10:00:00+00:00"))
    store.append(STUDENT, _rec("0580", 61.0, 49, "2026-11-04T18:00:00+00:00"))
    profiles = MagicMock()
    enrol = MagicMock(subject_code="0625", qualification_level=None)
    profiles.list_enrolments.return_value = [enrol]
    calendar = MagicMock()
    calendar.calendar_for_student.return_value = StudentExamCalendar(availability="available", entries=[
        _entry("0580", "dated", [date(2027, 5, 12)]),
    ])
    plans = MagicMock()
    plans.upcoming_sessions.return_value = []
    plans.last_plan_end.return_value = None
    zones = MagicMock()
    zones.zone_for.return_value = ZoneInfo("UTC")
    app = create_app()
    app.dependency_overrides[get_history_store] = lambda: store
    app.dependency_overrides[get_student_profile_service] = lambda: profiles
    app.dependency_overrides[get_exam_calendar_service] = lambda: calendar
    app.dependency_overrides[get_study_plan_service] = lambda: plans
    app.dependency_overrides[get_user_zone_reader] = lambda: zones
    app.dependency_overrides[get_user_mirror] = lambda: MagicMock(get_by_id=MagicMock(return_value=None))
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(user_id=STUDENT, role="student")
    return TestClient(app)


def test_overview_subject_rows_carry_home_fields(client: TestClient) -> None:
    rows = {r["code"]: r for r in client.get("/api/student/overview").json()["subjects"]}
    maths = rows["0580"]
    assert maths["firstPct"] == 46
    assert maths["nextExamOn"] == "2027-05-12"
    assert maths["examAvailability"] == "dated"
    assert maths["lastPaperOn"] == "2026-11-04"
    assert set(maths["boundaries"]) >= {"A", "B", "C"}
    assert isinstance(maths["boundariesEstimated"], bool)
    assert maths["previousGrade"] is not None


def test_enrolled_subject_without_papers_is_a_row(client: TestClient) -> None:
    physics = {r["code"]: r for r in client.get("/api/student/overview").json()["subjects"]}["0625"]
    assert physics["papers"] == 0
    assert physics["grade"] == ""
    assert physics["firstPct"] is None
    assert physics["boundaries"] is None
    assert physics["examAvailability"] == "no_session"
```

`GradeBoundaryStore()` reads `component_thresholds`. If the test database has none (`EmptyGradeBoundaryStoreError`), monkeypatch it the way `tests/test_web_student.py` does (search it for `EmptyGradeBoundaryStoreError` and copy the fixture).

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=/home/sico/Code/Lemely/.claude/worktrees/student-home-variants /home/sico/Code/Lemely/.venv/bin/pytest tests/test_overview_home.py -q`
Expected: FAIL with `ModuleNotFoundError: lemely.web.overview_home`.

- [ ] **Step 3: Implement the pure helpers**

`lemely/web/overview_home.py`:

```python
"""Pure builders for the student home's overview fields (spec 2026-11-06 §1).

Kept out of the router so each rule is a unit test: exam date and its reason,
the grade before the latest paper, and (Task 6) the latest result, upcoming
sessions and weak topics.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from lemely.core.history import PaperRecord
    from lemely.db.exam_calendar_repo import StudentExamCalendar

ExamAvailability = Literal["dated", "no_timetable", "no_session"]


def grade_for(percentage: float, boundaries: dict[str, float]) -> str:
    """Highest grade whose boundary ``percentage`` clears, else ``U`` (same rule as the router)."""
    for grade, threshold in sorted(boundaries.items(), key=lambda kv: kv[1], reverse=True):
        if percentage >= threshold:
            return grade
    return "U"


def weighted_pct(records: list[PaperRecord]) -> float:
    awarded = sum(r.awarded_marks for r in records)
    maximum = sum(r.maximum_marks for r in records)
    return (awarded / maximum) * 100.0 if maximum else 0.0


def previous_grade(records: list[PaperRecord], boundaries: dict[str, float]) -> str | None:
    """Grade over every paper but the latest, on the latest paper's boundaries."""
    if len(records) < 2:
        return None
    return grade_for(round(weighted_pct(records[:-1])), boundaries)


def rounded_boundaries(boundaries: dict[str, float]) -> dict[str, int]:
    return {grade: round(pct) for grade, pct in boundaries.items()}


def exam_fields(
    calendar: StudentExamCalendar | None, code: str, today: date
) -> tuple[date | None, ExamAvailability]:
    """Soonest sitting on or after ``today``, or the reason there is none."""
    if calendar is None:
        return None, "no_session"
    entries = [e for e in calendar.entries if e.subject_code == code]
    future = sorted(d.exam_date for e in entries for d in e.dates if d.exam_date >= today)
    if future:
        return future[0], "dated"
    if any(e.availability == "no_timetable" for e in entries):
        return None, "no_timetable"
    return None, "no_session"
```

Replace the router's `_grade_for` body with a call to `overview_home.grade_for` so the rule lives once.

- [ ] **Step 4: Extend the DTO and `_subjects`**

`SubjectRowDTO` new fields (with defaults, so other routes that build `SubjectRowDTO` compile unchanged):

```python
    firstPct: int | None = None
    previousGrade: str | None = None
    nextExamOn: date | None = None
    examAvailability: ExamAvailability = "no_session"
    boundaries: dict[str, int] | None = None
    boundariesEstimated: bool = False
    lastPaperOn: date | None = None
```

(`from datetime import date, datetime`; `from lemely.web.overview_home import ExamAvailability`.)

Change `_subjects` to `_subjects(history, enrolments, *, calendar: StudentExamCalendar | None, today: date)`:
1. Group grade-bearing records by code as today.
2. Build a row for each code that has records, adding `firstPct`, `previousGrade` (`previous_grade(records, boundaries)`), `boundaries` (`rounded_boundaries`), `boundariesEstimated = source != "exact"`, `lastPaperOn = datetime.fromisoformat(records[-1].recorded_at).date()`, and `nextExamOn, examAvailability = exam_fields(calendar, code, today)`.
3. For each enrolment code with no records, append the zero row described in Interfaces, with exam fields.
4. Sort all rows by code.
5. Only construct `GradeBoundaryStore()` when at least one code has records. Keep the existing comment about `EmptyGradeBoundaryStoreError`.

In `student_overview`, add the dependencies `calendar_service: Annotated[ExamCalendarService, Depends(get_exam_calendar_service)]`, `plans: Annotated[StudyPlanService, Depends(get_study_plan_service)]` (used in Task 6) and `zones: Annotated[UserZoneReader, Depends(get_user_zone_reader)]`. Compute:

```python
    if user_id is not None:
        today = civil_date_in_zone(datetime.now(UTC), zone=zones.zone_for(user_id))
        calendar = calendar_service.calendar_for_student(user_id)
    else:
        today = datetime.now(UTC).date()
        calendar = None
```

Move the existing `uuid.UUID(auth.user_id)` parse above `_subjects`. Every existing caller of `_subjects` (grep `_subjects(` in the router) passes `calendar=None, today=...`. Only the overview needs exam fields.

- [ ] **Step 5: Run the tests**

Run: `PYTHONPATH=/home/sico/Code/Lemely/.claude/worktrees/student-home-variants /home/sico/Code/Lemely/.venv/bin/pytest tests/test_overview_home.py tests/test_web_student.py -q`
Expected: all pass. Existing overview tests use a non-UUID id, so they exercise the guard.

- [ ] **Step 6: Commit**

```bash
/home/sico/Code/Lemely/.venv/bin/pre-commit run --files lemely/web/overview_home.py lemely/web/schemas_student.py lemely/web/routers/student.py tests/test_overview_home.py
git commit -S -m "feat(student): overview subjects carry first score, exam date and boundaries" -- lemely/web/overview_home.py lemely/web/schemas_student.py lemely/web/routers/student.py tests/test_overview_home.py
```

---

## Task 6: Overview latest result, sessions, weak topics, plan end

**Files:**
- Modify: `lemely/web/overview_home.py`
- Modify: `lemely/db/study_plan_repo.py` (two methods on `StudyPlanService`)
- Modify: `lemely/web/schemas_student.py` (`LatestResultDTO`, `UpcomingSessionDTO`, `WeakTopicDTO`, `OverviewDTO`)
- Modify: `lemely/web/routers/student.py` (`student_overview`)
- Test: `tests/test_overview_home.py` (append), `tests/test_study_plan_upcoming.py` (create)

**Interfaces:**
- Consumes: `PaperRecord.seen_at` (Task 3); `SessionView` (`id`, `date`, `topic`, `duration_minutes`, `completed_at`, `subject_code`); `DbStudyPlan`, `DbStudyPlanSession`.
- Produces:
  - `short_paper_label(metadata: ExamMetadata) -> str` → `"0580/42 · m/j 2024"` (`May/June`→`m/j`, `October/November`→`o/n`, `February/March`→`f/m`; with no year or another month, just `"0580/42"`).
  - `latest_result(records: list[PaperRecord]) -> LatestResultDTO | None`: the grade-bearing record with the greatest `recorded_at`, where `paperId = str(index in records)` and `seen = record.seen_at is not None or record.attempt_id is None`.
  - `weak_topics(history_records: list[PaperRecord], *, limit: int = 6) -> list[WeakTopicDTO]`.
  - `StudyPlanService.upcoming_sessions(self, student_id: uuid.UUID | str, *, start: date, days: int = 7) -> list[SessionView]`: incomplete sessions dated `start .. start+days-1` from non-superseded plans, ordered by `(date, created_at)`.
  - `StudyPlanService.last_plan_end(self, student_id: uuid.UUID | str) -> date | None`: the latest `week_start + 6 days` over the student's non-superseded plans.
  - `OverviewDTO.latestResult`, `.upcomingSessions`, `.weakTopics`, `.planEndedOn`.

Weak topic rule (design: "54%, up 7 from 47%, 9 marks to win back from the last 3 papers"):
- Per subject, over grade-bearing records in order, `window = records[-3:]`, `prior = records[-4:-1]`.
- For each topic in `window`'s weak areas: `acc = round(100 * (1 - Σlost / Σmax))` over the window's areas with that topic. `previousAcc` = the same over `prior` if the topic appears there and `len(records) >= 2`, else `None`. `lostMarks = Σlost` in the window.
- Keep topics with `acc < 70` (the design's secure line), sort by `acc` ascending, then by subject code, then by topic. Return the first `limit`.

- [ ] **Step 1: Write the failing tests (append to `tests/test_overview_home.py`)**

```python
from lemely.web.overview_home import latest_result, short_paper_label, weak_topics


def _weak(topic: str, lost: int, maximum: int) -> WeakArea:
    return WeakArea(topic=topic, lost_marks=lost, maximum_marks=maximum,
                    accuracy=round(1 - lost / maximum, 4), question_ids=["1"])


def test_short_paper_label() -> None:
    meta = ExamMetadata(subject_code="0580", paper_number=4, paper_variant=2, session_month="May/June", session_year=2024)
    assert short_paper_label(meta) == "0580/42 · m/j 2024"
    meta2 = ExamMetadata(subject_code="0580", paper_number=4, paper_variant=1, session_month="October/November", session_year=2023)
    assert short_paper_label(meta2) == "0580/41 · o/n 2023"


def test_latest_result_is_newest_grade_bearing_record_by_index() -> None:
    older = _rec("0606", 50.0, 40, "2026-10-27T16:00:00+00:00")
    newer = _rec("0580", 76.25, 61, "2026-11-04T18:00:00+00:00").model_copy(update={"grade": "A"})
    result = latest_result([newer, older])
    assert result is not None
    assert (result.paperId, result.subjectCode, result.grade) == ("0", "0580", "A")
    assert (result.awarded, result.maximum) == (61, 80)
    assert result.paperLabel == "0580/42 · m/j 2024"
    assert result.seen is True  # file-store record (no attempt id) cannot be marked, so it counts as seen
    unseen = newer.model_copy(update={"attempt_id": str(uuid.uuid4()), "seen_at": None})
    assert latest_result([unseen]).seen is False
    assert latest_result([]) is None


def test_weak_topics_window_trend_and_secure_line() -> None:
    recs = [
        _rec("0625", 40.0, 32, "2026-09-01T10:00:00+00:00", [_weak("Waves", 8, 15)]),
        _rec("0625", 45.0, 36, "2026-10-01T10:00:00+00:00", [_weak("Waves", 3, 5)]),
        _rec("0625", 48.0, 38, "2026-11-01T10:00:00+00:00", [_weak("Waves", 3, 5), _weak("Moments", 3, 9), _weak("Light", 1, 10)]),
    ]
    topics = {t.topic: t for t in weak_topics(recs)}
    assert "Light" not in topics  # 90% is secure
    waves = topics["Waves"]
    assert (waves.subjectCode, waves.acc, waves.lostMarks) == ("0625", 44, 14)
    assert waves.previousAcc == 45  # over records[-4:-1] = first two papers: 1 - 11/20
    assert topics["Moments"].previousAcc is None
    assert [t.topic for t in weak_topics(recs)] == ["Waves", "Moments"]


def test_overview_new_top_level_fields(client: TestClient) -> None:
    body = client.get("/api/student/overview").json()
    assert body["latestResult"]["subjectCode"] == "0580"
    assert body["latestResult"]["paperId"] == "1"
    assert body["upcomingSessions"] == []
    assert body["weakTopics"] == []
    assert body["planEndedOn"] is None
```

`tests/test_study_plan_upcoming.py` (Postgres, `migrated_sessionmaker`): insert a user, two plans (one superseded) with sessions on `2026-11-04` (completed), `2026-11-05`, `2026-11-11`, `2026-11-12`. Assert `upcoming_sessions(uid, start=date(2026, 11, 5))` returns the 05 and 11 sessions from the live plan only, in date order. Assert `last_plan_end(uid)` equals the live plan's `week_start + 6`. Insert rows through `DbStudyPlan` / `DbStudyPlanSession` the way `tests/` tests for `study_plan_repo` already do (find them with `grep -l StudyPlanService tests/*.py` and copy the setup helper).

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=/home/sico/Code/Lemely/.claude/worktrees/student-home-variants /home/sico/Code/Lemely/.venv/bin/pytest tests/test_overview_home.py tests/test_study_plan_upcoming.py -q`
Expected: FAIL with `ImportError: latest_result`.

- [ ] **Step 3: Implement**

Append to `lemely/web/overview_home.py`:

```python
_SESSION_SHORT = {"February/March": "f/m", "May/June": "m/j", "October/November": "o/n"}
SECURE_PCT = 70


def short_paper_label(metadata: ExamMetadata) -> str:
    base = f"{metadata.subject_code}/{metadata.paper_number}{metadata.paper_variant}"
    short = _SESSION_SHORT.get(metadata.session_month)
    if short is None or metadata.session_year is None:
        return base
    return f"{base} · {short} {metadata.session_year}"


def latest_result(records: list[PaperRecord]) -> LatestResultDTO | None:
    indexed = [(i, r) for i, r in enumerate(records) if is_grade_bearing(r)]
    if not indexed:
        return None
    index, record = max(indexed, key=lambda pair: pair[1].recorded_at)
    return LatestResultDTO(
        subjectCode=record.metadata.subject_code,
        grade=record.grade,
        paperId=str(index),
        paperLabel=short_paper_label(record.metadata),
        recordedAt=record.recorded_at,
        seen=record.seen_at is not None or record.attempt_id is None,
        awarded=record.awarded_marks,
        maximum=record.maximum_marks,
    )


def _topic_acc(records: list[PaperRecord], topic: str) -> tuple[int, int] | None:
    lost = maximum = 0
    for r in records:
        for area in r.weak_areas:
            if area.topic == topic:
                lost += area.lost_marks
                maximum += area.maximum_marks
    return (lost, maximum) if maximum else None


def weak_topics(records: list[PaperRecord], *, limit: int = 6) -> list[WeakTopicDTO]:
    by_code: dict[str, list[PaperRecord]] = {}
    for r in records:
        if is_grade_bearing(r):
            by_code.setdefault(r.metadata.subject_code, []).append(r)
    out: list[WeakTopicDTO] = []
    for code, recs in by_code.items():
        window, prior = recs[-3:], recs[-4:-1]
        for topic in sorted({a.topic for r in window for a in r.weak_areas}):
            now = _topic_acc(window, topic)
            if now is None:
                continue
            acc = round(100 * (1 - now[0] / now[1]))
            if acc >= SECURE_PCT:
                continue
            before = _topic_acc(prior, topic) if len(recs) >= 2 else None
            out.append(WeakTopicDTO(
                topic=topic, subjectCode=code, acc=acc,
                previousAcc=round(100 * (1 - before[0] / before[1])) if before else None,
                lostMarks=now[0],
            ))
    out.sort(key=lambda t: (t.acc, t.subjectCode, t.topic))
    return out[:limit]
```

(Runtime imports: `from lemely.core.history import is_grade_bearing`, `from lemely.web.schemas_student import LatestResultDTO, WeakTopicDTO`; `ExamMetadata` under `TYPE_CHECKING`.)

The test expects Waves `previousAcc == 45`. `prior = recs[-4:-1]` is the first two papers: lost 8+3=11 of 15+5=20, so 1 - 11/20 = 45%. The window is all three: lost 14 of 25 → 44%.

DTOs in `schemas_student.py`:

```python
class LatestResultDTO(ApiModel):
    """The newest marked paper, for the student home's result card."""

    subjectCode: str
    grade: str
    paperId: str
    paperLabel: str
    recordedAt: str
    seen: bool
    awarded: int
    maximum: int


class UpcomingSessionDTO(ApiModel):
    sessionId: str
    subjectCode: str
    title: str
    minutes: int
    scheduledFor: date


class WeakTopicDTO(ApiModel):
    topic: str
    subjectCode: str
    acc: int
    previousAcc: int | None
    lostMarks: int
```

`OverviewDTO` gains `latestResult: LatestResultDTO | None = None`, `upcomingSessions: list[UpcomingSessionDTO] = []`, `weakTopics: list[WeakTopicDTO] = []`, `planEndedOn: date | None = None`.

`StudyPlanService`:

```python
    def upcoming_sessions(self, student_id: uuid.UUID | str, *, start: date, days: int = 7) -> list[SessionView]:
        """Incomplete sessions dated start..start+days-1 across the student's live plans."""
        student_uuid = _as_uuid(student_id)
        end = start + timedelta(days=days - 1)
        with self._sessionmaker() as session:
            rows = session.execute(
                select(DbStudyPlanSession, DbStudyPlan.subject_code)
                .join(DbStudyPlan, DbStudyPlanSession.plan_id == DbStudyPlan.id)
                .where(
                    DbStudyPlan.user_id == student_uuid,
                    DbStudyPlan.superseded_at.is_(None),
                    DbStudyPlanSession.completed_at.is_(None),
                    DbStudyPlanSession.date >= start,
                    DbStudyPlanSession.date <= end,
                )
                .order_by(DbStudyPlanSession.date, DbStudyPlanSession.created_at)
            ).all()
            return [self._session_view(s, code) for s, code in rows]

    def last_plan_end(self, student_id: uuid.UUID | str) -> date | None:
        """Last day (week_start + 6) of the student's most recent live plan."""
        student_uuid = _as_uuid(student_id)
        with self._sessionmaker() as session:
            latest = session.scalar(
                select(func.max(DbStudyPlan.week_start)).where(
                    DbStudyPlan.user_id == student_uuid, DbStudyPlan.superseded_at.is_(None)
                )
            )
        return latest + timedelta(days=6) if latest is not None else None
```

`_session_view` is the per-session part of the existing `_to_view`. Extract it (find how `_to_view` builds `SessionView`) rather than duplicating it.

Router (`student_overview`), after `subjects`:

```python
    upcoming = plans.upcoming_sessions(user_id, start=today) if user_id is not None else []
    plan_end = plans.last_plan_end(user_id) if user_id is not None else None
    return OverviewDTO(
        ...existing fields...,
        latestResult=latest_result(history.records),
        upcomingSessions=[
            UpcomingSessionDTO(sessionId=str(s.id), subjectCode=s.subject_code, title=s.topic,
                               minutes=s.duration_minutes, scheduledFor=s.date)
            for s in upcoming
        ],
        weakTopics=weak_topics(history.records),
        planEndedOn=plan_end,
    )
```

The plan only sets `planEndedOn` when the plan has ended: `plan_end if plan_end is not None and plan_end < today else None`. The design prints "Your study plan ended on 27 Oct" only in that case.

- [ ] **Step 4: Run the tests**

Run: `PYTHONPATH=/home/sico/Code/Lemely/.claude/worktrees/student-home-variants /home/sico/Code/Lemely/.venv/bin/pytest tests/test_overview_home.py tests/test_study_plan_upcoming.py tests/test_web_student.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
/home/sico/Code/Lemely/.venv/bin/pre-commit run --files lemely/web/overview_home.py lemely/db/study_plan_repo.py lemely/web/schemas_student.py lemely/web/routers/student.py tests/test_overview_home.py tests/test_study_plan_upcoming.py
git commit -S -m "feat(student): overview latest result, upcoming sessions and weak topics" -- lemely/web/overview_home.py lemely/db/study_plan_repo.py lemely/web/schemas_student.py lemely/web/routers/student.py tests/test_overview_home.py tests/test_study_plan_upcoming.py
```

---

## Task 7: Frontend wire types, hooks, mark seen on open

**Files:**
- Modify: `web/src/lib/studentTypes.ts` (`SubjectRow`, `Overview`, `UploadRun`; new types)
- Modify: `web/src/lib/hooks/useStudentApi.ts` (`useActiveUpload`, new `useMarkResultSeen`)
- Modify: `web/src/portals/student/screens/PaperResult.tsx` (~line 649)
- Test: `web/tests/unit/studentHomeHooks.test.ts`

**Interfaces:**
- Consumes: endpoints from Tasks 3–6.
- Produces: the wire types in Shared interfaces, plus:
  - `useActiveUpload(opts?: { poll?: boolean }): UseQueryResult<UploadRun | null, Error>`. With `poll: true` it refetches every `RUN_POLL_MS` while `data?.status === "processing"`. When a polled run disappears (processing → null), it invalidates `["student", "overview"]` and `["student", "xp"]`.
  - `useMarkResultSeen(): UseMutationResult<void, Error, { paperId: string }>`: `POST /student/results/{paperId}/seen`, then invalidates `["student", "overview"]`.
  - `activeUploadRefetchInterval(data: UploadRun | null | undefined): number | false`: exported for the test.

- [ ] **Step 1: Failing test**

```ts
import { describe, expect, it } from "vitest"
import { activeUploadRefetchInterval } from "@/lib/hooks/useStudentApi"
import type { UploadRun } from "@/lib/studentTypes"

const run = (status: UploadRun["status"]): UploadRun => ({
  paperId: "u1", status, filename: "scan.jpg", startedAt: null, stale: false,
  progress: null, paperLabel: null, subjectCode: null,
})

describe("activeUploadRefetchInterval", () => {
  it("polls only while a run is processing", () => {
    expect(activeUploadRefetchInterval(run("processing"))).toBeGreaterThan(0)
    expect(activeUploadRefetchInterval(run("complete"))).toBe(false)
    expect(activeUploadRefetchInterval(null)).toBe(false)
    expect(activeUploadRefetchInterval(undefined)).toBe(false)
  })
})
```

Run: `cd web && npx vitest run tests/unit/studentHomeHooks.test.ts`. Expected: FAIL (no export).

- [ ] **Step 2: Implement**

Add the types from Shared interfaces to `studentTypes.ts`, extending the existing interfaces in place. `UpcomingSessionDto` and `WeakTopicDto` are named with a `Dto` suffix because `model.ts` already exports `UpcomingSession` and `WeakTopic`.

`useStudentApi.ts`:

```ts
export function activeUploadRefetchInterval(data: UploadRun | null | undefined): number | false {
  return data?.status === "processing" ? RUN_POLL_MS : false
}

export function useActiveUpload(opts: { poll?: boolean } = {}): UseQueryResult<UploadRun | null, Error> {
  const queryClient = useQueryClient()
  const wasProcessing = useRef(false)
  const query = useQuery({
    queryKey: ["student", "upload", "active"],
    queryFn: () => request<UploadRun | null>("/student/uploads/active"),
    staleTime: RUN_POLL_MS,
    refetchInterval: opts.poll ? (q) => activeUploadRefetchInterval(q.state.data) : false,
  })
  useEffect(() => {
    if (!opts.poll) return
    const processing = query.data?.status === "processing"
    if (wasProcessing.current && !processing) {
      void queryClient.invalidateQueries({ queryKey: ["student", "overview"] })
      void queryClient.invalidateQueries({ queryKey: ["student", "xp"] })
    }
    wasProcessing.current = processing
  }, [opts.poll, query.data, queryClient])
  return query
}

export function useMarkResultSeen(): UseMutationResult<void, Error, { paperId: string }> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ paperId }) =>
      request<void>(`/student/results/${encodeURIComponent(paperId)}/seen`, { method: "POST" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["student", "overview"] }),
  })
}
```

Keep the existing doc comment on `useActiveUpload`, adding one line: "`poll: true` (the student home) keeps it live while a run is processing." Check that `request<void>` handles a 204 empty body (read `request` in `web/src/lib/api.ts`). If it does not, pass the `fallback` argument as `undefined`, as other 204 mutations in this file do (`useUnlinkParent`).

`PaperResult.tsx`: next to `const query = useResult(...)`:

```tsx
  const markSeen = useMarkResultSeen()
  const seenFor = useRef<string | null>(null)
  useEffect(() => {
    if (live || !paperId || !query.data || seenFor.current === paperId) return
    seenFor.current = paperId
    markSeen.mutate({ paperId })
  }, [live, paperId, query.data, markSeen])
```

- [ ] **Step 3: Run**

Run: `cd web && npx vitest run tests/unit/studentHomeHooks.test.ts && npx tsc -b --noEmit`
Expected: test PASS. `tsc` may report other files that build `UploadRun` or `SubjectRow` literals (test fixtures, `CorrectPaper.tsx`). Add the new fields there, with `null`/neutral values.

- [ ] **Step 4: Commit**

```bash
/home/sico/Code/Lemely/.venv/bin/pre-commit run --files web/src/lib/studentTypes.ts web/src/lib/hooks/useStudentApi.ts web/src/portals/student/screens/PaperResult.tsx web/tests/unit/studentHomeHooks.test.ts
git commit -S -m "feat(web): home wire types, live active upload, mark result seen" -- web/src/lib/studentTypes.ts web/src/lib/hooks/useStudentApi.ts web/src/portals/student/screens/PaperResult.tsx web/tests/unit/studentHomeHooks.test.ts
```

(Include any file `tsc` made you touch in both commands.)

---

## Task 8: API fixtures, `facts.ts`, `format.ts`

**Files:**
- Create: `web/dev-previews/student-home/api-fixtures.ts`
- Create: `web/src/portals/student/home/facts.ts`
- Create: `web/src/portals/student/home/format.ts`
- Test: `web/tests/unit/studentHomeFacts.test.ts`, `web/tests/unit/studentHomeFormat.test.ts`

**Interfaces:**
- Consumes: `FIXTURES`, `STATES`, `NOW` (`fixtures.ts`); `deriveNextAction`, `binnyMood`, `streakStrip` (`model.ts`); wire types (Task 7); `XpProfile` (`web/src/lib/xpTypes.ts`); `greetingFor`, `studentLoadFailureMessage`.
- Produces: everything in Shared interfaces under "View model" and "Formatting", plus:
  - `API_FIXTURES: Record<Exclude<StateId, "loading" | "error">, { overview: Overview; xp: XpProfile; upload: UploadRun | null }>`
  - `API_NOW: Date` (= `NOW`)

`api-fixtures.ts` must import values only from `./fixtures.ts` (with the extension) and types only with `import type`. That way Node 26 can load it directly (type stripping) from `web/scripts/home-drift/overview.mjs`. Every display value comes from the design markup in `student-home-a.html` (the line numbers are in the table comments).

- [ ] **Step 1: Write `api-fixtures.ts`**

```ts
/*
 * API responses for the student home's 12 data states, for the drift gate's
 * route mocks and the facts tests. The decision facts come from fixtures.ts
 * (spread, never retyped); every display value (names, boundaries, scores, XP)
 * is copied from student-home-a.html so the real page renders the same words.
 * toHomeFacts(API_FIXTURES[s]) must equal FIXTURES[s].facts (studentHomeFacts.test.ts).
 */
import type { HomeFacts, HomeSubject } from "@/portals/student/home/model"
import type { Overview, SubjectRow, UploadRun, WeakTopicDto } from "@/lib/studentTypes"
import type { XpProfile } from "@/lib/xpTypes"
import { FIXTURES, NOW, type StateId } from "./fixtures.ts"

export const API_NOW = NOW
export type DataStateId = Exclude<StateId, "loading" | "error">

const NAMES: Record<string, string> = { "0580": "Mathematics", "0606": "Additional Mathematics", "0625": "Physics" }
// student-home-a.html grades rows (aria-labels list each subject's boundaries).
const BOUNDS: Record<string, Record<string, number>> = {
  "0580": { C: 42, B: 55, A: 70, "A*": 85 },
  "0606": { C: 40, B: 54, A: 68, "A*": 82 },
  "0625": { C: 45, B: 52, A: 66, "A*": 80 },
}
const ESTIMATED: Record<string, boolean> = { "0580": false, "0606": false, "0625": true }

/** Per state and subject: [pct, firstPct, lastPaperOn]. From the Garden and grades markup. */
const SCORES: Record<DataStateId, Record<string, [number, number, string] | undefined>> = {
  populated: { "0580": [76, 49, "2026-11-04"], "0606": [59, 44, "2026-10-30"], "0625": [48, 41, "2026-11-02"] },
  "result-in": { "0580": [76, 49, "2026-11-04"], "0606": [59, 44, "2026-10-30"], "0625": [48, 41, "2026-11-02"] },
  marking: { "0580": [76, 49, "2026-11-04"], "0606": [59, 44, "2026-10-30"], "0625": [48, 41, "2026-11-02"] },
  "no-plan": { "0580": [76, 49, "2026-11-04"], "0606": [59, 44, "2026-10-30"], "0625": [48, 41, "2026-11-02"] },
  "no-exams": { "0580": [76, 49, "2026-11-04"], "0606": [59, 44, "2026-10-30"], "0625": [48, 41, "2026-11-02"] },
  "streak-zero": { "0580": [76, 49, "2026-11-01"], "0606": [59, 44, "2026-10-30"], "0625": [48, 41, "2026-10-29"] },
  new: {},
  "one-paper": { "0580": [65, 65, "2026-11-02"] },
  sparse0: {},
  sparse1: { "0580": [46, 46, "2026-11-05"] },
  sparse2: { "0580": [58, 46, "2026-11-04"], "0606": [47, 47, "2026-11-03"] },
  sparse3: { "0580": [60, 46, "2026-10-27"], "0606": [49, 45, "2026-10-27"] },
}

/** Weak-topic trend and marks to win back, keyed "<code>:<topic>". From the weak-topics markup. */
const WEAK_EXTRA: Record<string, [number | null, number]> = {
  "0625:Waves": [47, 9], "0606:Quadratic inequalities": [61, 6], "0580:Vectors": [55, 5], "0625:Moments": [null, 3],
}
const WEAK_EXTRA_BY_STATE: Partial<Record<DataStateId, Record<string, [number | null, number]>>> = {
  "one-paper": { "0580:Vectors": [null, 4] },
  sparse1: { "0580:Vectors": [null, 4], "0580:Transformations": [null, 3] },
  sparse2: { "0606:Logarithms": [null, 5], "0580:Vectors": [50, 4], "0580:Transformations": [58, 2] },
  sparse3: { "0606:Logarithms": [48, 5], "0580:Vectors": [52, 3], "0580:Transformations": [61, 2] },
}

/** Result card score (awarded of maximum). From .a-act-score. */
const SCORE_BY_STATE: Partial<Record<DataStateId, [number, number]>> = {
  sparse1: [37, 80], "one-paper": [52, 80], sparse2: [46, 80], sparse3: [38, 80],
}
const DEFAULT_SCORE: [number, number] = [61, 80]

/** XP header per state: [totalXp, level, levelStartXp, nextLevelXp, streak, longest, freezes]. From .ah-level / .ah-week. */
const XP: Record<DataStateId, [number, number, number, number, number, number, number]> = {
  populated: [2340, 7, 2100, 2600, 9, 14, 1],
  "result-in": [2340, 7, 2100, 2600, 9, 14, 1],
  marking: [2340, 7, 2100, 2600, 9, 14, 1],
  "no-plan": [2340, 7, 2100, 2600, 9, 14, 1],
  "no-exams": [2340, 7, 2100, 2600, 9, 14, 1],
  "streak-zero": [2340, 7, 2100, 2600, 0, 14, 1],
  new: [0, 1, 0, 100, 0, 0, 0],
  "one-paper": [50, 1, 0, 100, 0, 1, 0],
  sparse0: [20, 1, 0, 100, 1, 1, 0],
  sparse1: [70, 1, 0, 100, 1, 1, 0],
  sparse2: [220, 2, 100, 300, 3, 3, 0],
  sparse3: [270, 2, 100, 300, 0, 7, 0],
}

/** Marking card: stage 3, question 7 of 12, as the preview's .a-prog[data-stage="3"]. */
const UPLOAD_BY_STATE: Partial<Record<DataStateId, { label: string; code: string }>> = {
  sparse0: { label: "0580/42", code: "0580" },
  marking: { label: "0625/42", code: "0625" },
}

function subjectRow(state: DataStateId, s: HomeSubject): SubjectRow {
  const score = SCORES[state][s.code]
  const papers = s.papers
  return {
    code: s.code,
    name: NAMES[s.code] ?? s.code,
    qualificationLevel: null,
    detail: papers > 0 ? `${papers} papers corrected` : "No papers yet",
    pct: score?.[0] ?? 0,
    papers,
    trend: "",
    grade: s.grade,
    barColor: "t3",
    trendUp: false,
    firstPct: papers > 0 ? (score?.[1] ?? null) : null,
    previousGrade: s.previousGrade,
    nextExamOn: s.nextExamOn,
    examAvailability: s.nextExamOn ? "dated" : "no_session",
    boundaries: papers > 0 ? BOUNDS[s.code] : null,
    boundariesEstimated: papers > 0 ? ESTIMATED[s.code] : false,
    lastPaperOn: papers > 0 ? (score?.[2] ?? null) : null,
  }
}

function weak(state: DataStateId, f: HomeFacts): WeakTopicDto[] {
  const extras = WEAK_EXTRA_BY_STATE[state] ?? WEAK_EXTRA
  return f.weakTopics.map((t) => {
    const [previousAcc, lostMarks] = extras[`${t.subjectCode}:${t.topic}`] ?? [null, 0]
    return { topic: t.topic, subjectCode: t.subjectCode, acc: t.acc, previousAcc, lostMarks }
  })
}

function build(state: DataStateId): { overview: Overview; xp: XpProfile; upload: UploadRun | null } {
  const f = FIXTURES[state].facts
  const [awarded, maximum] = SCORE_BY_STATE[state] ?? DEFAULT_SCORE
  const [totalXp, level, levelStartXp, nextLevelXp, current, longest, freezes] = XP[state]
  const up = UPLOAD_BY_STATE[state]
  return {
    overview: {
      studentName: "Mariam",
      forecast: f.subjects.map((s) => s.grade).join(" "),
      subjects: f.subjects.map((s) => subjectRow(state, s)),
      weakGlobal: [],
      momentum: { points: [] },
      latestResult: f.latestResult ? { ...f.latestResult, awarded, maximum } : null,
      upcomingSessions: f.upcomingSessions.map((s) => ({ ...s })),
      weakTopics: weak(state, f),
      planEndedOn: state === "sparse3" ? "2026-10-27" : null,
    },
    xp: {
      totalXp, level, levelStartXp, nextLevelXp,
      streak: { current, longest, lastActiveOn: f.calendar.at(-1)?.day ?? null, freezesAvailable: freezes },
      week: { start: "2026-11-02", end: "2026-11-08", total: 0, bySource: [] },
      calendar: f.calendar.map((d) => ({ ...d })),
      calendarStart: "2026-10-09",
      calendarEnd: "2026-11-05",
    } as XpProfile,
    upload: up
      ? {
          paperId: "u-1", status: "processing", filename: "scan.jpg",
          startedAt: new Date(2026, 10, 5, 9, 58).toISOString(), stale: false,
          progress: { stage: 3, done: 7, total: 12 }, paperLabel: up.label, subjectCode: up.code,
        }
      : null,
  }
}

const DATA_STATES = [
  "populated", "result-in", "new", "one-paper", "sparse0", "sparse1", "sparse2", "sparse3",
  "marking", "no-plan", "no-exams", "streak-zero",
] as const satisfies readonly DataStateId[]

export const API_FIXTURES = Object.fromEntries(DATA_STATES.map((s) => [s, build(s)])) as Record<
  DataStateId,
  ReturnType<typeof build>
>
```

Before writing `XP`, `SCORES`, `SCORE_BY_STATE`, open `student-home-a.html` and check each number against the markup. One example: `sparse2` "120 / 200 XP to level 3" means level 2 with `levelStartXp` 100, `nextLevelXp` 300 and total 220. Read the `XpProfile` interface in `web/src/lib/xpTypes.ts` and drop the `as XpProfile` cast once every required field is present. If a field this table does not list is required, add it with a neutral value.

- [ ] **Step 2: Write the failing facts tests**

```ts
import { describe, expect, it } from "vitest"
import { API_FIXTURES, API_NOW, type DataStateId } from "../../dev-previews/student-home/api-fixtures"
import { FIXTURES } from "../../dev-previews/student-home/fixtures"
import { homeState, pageState, toHomeFacts, toHomeView } from "@/portals/student/home/facts"

const DATA = Object.keys(API_FIXTURES) as DataStateId[]

describe("toHomeFacts", () => {
  it.each(DATA)("%s maps the API back to the design fixture's facts", (s) => {
    const { overview, xp, upload } = API_FIXTURES[s]
    expect(toHomeFacts(overview, xp, upload, API_NOW)).toEqual(FIXTURES[s].facts)
  })
})

describe("homeState", () => {
  it.each(DATA)("%s", (s) => {
    expect(homeState(FIXTURES[s].facts)).toBe(s)
  })

  it("a paper with an unseen result in a single-subject student stays one-paper (layout), action is result", () => {
    const f = { ...FIXTURES["one-paper"].facts, latestResult: { ...FIXTURES["one-paper"].facts.latestResult!, seen: false } }
    expect(homeState(f)).toBe("one-paper")
  })

  it("five papers with a missing subject and a live streak is sparse2", () => {
    const base = FIXTURES.sparse2.facts
    const f = { ...base, subjects: base.subjects.map((s) => (s.code === "0580" ? { ...s, papers: 4 } : s)) }
    expect(homeState(f)).toBe("sparse2")
  })

  it("six papers with a missing subject falls through to the populated family", () => {
    const base = FIXTURES.sparse2.facts
    const f = { ...base, subjects: base.subjects.map((s) => (s.code === "0580" ? { ...s, papers: 5 } : s)) }
    expect(["populated", "no-plan", "no-exams"]).toContain(homeState(f))
  })

  it("no-plan wins over no-exams when both are true", () => {
    const f = { ...FIXTURES["no-exams"].facts, upcomingSessions: [] }
    expect(homeState(f)).toBe("no-plan")
  })
})

describe("toHomeView", () => {
  it("carries display fields and the model's decisions", () => {
    const { overview, xp, upload } = API_FIXTURES.populated
    const v = toHomeView(overview, xp, upload, API_NOW)
    expect(v.state).toBe("populated")
    expect(v.action.kind).toBe("session")
    expect(v.mood).toBe("grade-improved")
    expect(v.totalPapers).toBe(22)
    expect(v.xp).toEqual({ totalXp: 2340, level: 7, intoLevel: 240, levelSpan: 500, streak: 9, longest: 14, freezes: 1 })
    expect(v.subjects.find((s) => s.code === "0606")?.shortName).toBe("Add Maths")
    expect(v.latestScore).toEqual({ awarded: 61, maximum: 80 })
    expect(v.week).toHaveLength(7)
  })

  it("XP failure gives xp null and an empty calendar, nothing else changes", () => {
    const { overview, upload } = API_FIXTURES.populated
    const v = toHomeView(overview, null, upload, API_NOW)
    expect(v.xp).toBeNull()
    expect(v.facts.calendar).toEqual([])
  })

  it("an upload that is not processing is ignored", () => {
    const { overview, xp, upload } = API_FIXTURES.marking
    const v = toHomeView(overview, xp, { ...upload!, status: "complete" }, API_NOW)
    expect(v.upload).toBeNull()
    expect(v.facts.activeUpload).toBeNull()
  })
})

describe("pageState", () => {
  const ok = API_FIXTURES.populated
  const q = (o: Partial<Parameters<typeof pageState>[0]["overview"]>) => ({
    overview: { data: ok.overview, isPending: false, isError: false, error: null, dataUpdatedAt: 1, ...o },
    xp: { data: ok.xp, isPending: false, isError: false },
    upload: { data: ok.upload, isPending: false, isError: false },
  })

  it("loading while overview has no data", () => {
    expect(pageState(q({ data: undefined, isPending: true }), API_NOW).kind).toBe("loading")
  })
  it("error with no cached data uses studentLoadFailureMessage", () => {
    const m = pageState(q({ data: undefined, isError: true, error: new Error("x") }), API_NOW)
    expect(m).toEqual({ kind: "error", message: expect.any(String) })
  })
  it("refetch failure keeps the page and marks it stale", () => {
    const m = pageState(q({ isError: true, dataUpdatedAt: 42 }), API_NOW)
    expect(m.kind === "ready" && m.stale).toEqual({ at: 42 })
  })
  it("xp pending with no data is loading; xp error is ready with xp null", () => {
    const base = q({})
    expect(pageState({ ...base, xp: { data: undefined, isPending: true, isError: false } }, API_NOW).kind).toBe("loading")
    const m = pageState({ ...base, xp: { data: undefined, isPending: false, isError: true } }, API_NOW)
    expect(m.kind === "ready" && m.view.xp).toBeNull()
  })
})
```

`studentHomeFormat.test.ts`:

```ts
import { describe, expect, it } from "vitest"
import { clockTime, dayMonth, dayOfMonth, daysBetween, indefinite, longDay, thousands, weekdayShort } from "@/portals/student/home/format"

describe("format", () => {
  it("dates", () => {
    expect(dayMonth("2027-05-04")).toBe("4 May")
    expect(longDay("2026-10-30")).toBe("30 October")
    expect(weekdayShort("2026-10-30")).toBe("Fri")
    expect(dayOfMonth("2026-11-01")).toBe("1")
    expect(daysBetween("2026-11-05", "2027-05-04")).toBe(180)
    expect(daysBetween("2026-11-05", "2027-05-12")).toBe(188)
    expect(daysBetween("2026-11-05", "2027-05-18")).toBe(194)
  })
  it("clock", () => {
    expect(clockTime(new Date(2026, 10, 5, 9, 41).getTime())).toBe("09:41")
  })
  it("articles and numbers", () => {
    expect(indefinite("A*")).toBe("an")
    expect(indefinite("A")).toBe("an")
    expect(indefinite("B")).toBe("a")
    expect(indefinite("Add Maths")).toBe("an")
    expect(indefinite("Physics")).toBe("a")
    expect(thousands(2340)).toBe("2,340")
  })
})
```

Run: `cd web && npx vitest run tests/unit/studentHomeFacts.test.ts tests/unit/studentHomeFormat.test.ts`
Expected: FAIL (modules missing).

- [ ] **Step 3: Implement `format.ts`**

```ts
/* Formatting for the student home. Local-time dates, en-GB words, no Intl
 * variance in the drift gate: month and weekday names are fixed tables. */
import { greetingFor } from "@/lib/utils"

const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]

function parts(iso: string): [number, number, number] {
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number)
  return [y, m, d]
}
const local = (iso: string): Date => { const [y, m, d] = parts(iso); return new Date(y, m - 1, d) }

export const dayMonth = (iso: string): string => { const [, m, d] = parts(iso); return `${d} ${MON[m - 1]}` }
export const longDay = (iso: string): string => { const [, m, d] = parts(iso); return `${d} ${MONTHS[m - 1]}` }
export const weekdayShort = (iso: string): string => WEEKDAYS[local(iso).getDay()]
export const dayOfMonth = (iso: string): string => String(parts(iso)[2])
export const clockTime = (ms: number): string => {
  const d = new Date(ms)
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`
}
export function daysBetween(fromISO: string, toISO: string): number {
  const [fy, fm, fd] = parts(fromISO)
  const [ty, tm, td] = parts(toISO)
  return Math.round((Date.UTC(ty, tm - 1, td) - Date.UTC(fy, fm - 1, fd)) / 86_400_000)
}
export const indefinite = (word: string): "a" | "an" => (/^[AEIOU]/i.test(word) ? "an" : "a")
export const thousands = (n: number): string => n.toLocaleString("en-GB")
export const greetingWord = (now: Date): string => greetingFor(now.getHours())
```

`dayMonth` uses the short month ("4 Nov", "27 Oct", "4 May"). The design writes May as "May", which `MON` already has. The design does not show "June" or "July" anywhere, so the three-letter table matches it.

- [ ] **Step 4: Implement `facts.ts`**

```ts
/*
 * Student home data adapter (spec 2026-11-06 §1, §3). The only place the page
 * reads API shapes: three responses in, one HomeView out. Decisions stay in
 * model.ts; this file adds the display data design A prints and picks the state.
 */
import { studentLoadFailureMessage } from "@/lib/studentOutcome"
import type { Overview, UploadRun } from "@/lib/studentTypes"
import type { XpProfile } from "@/lib/xpTypes"
import { binnyMood, deriveNextAction, localISODate, streakStrip, type HomeFacts } from "./model"
// …the types exported in Shared interfaces (HomeState, DataState, SubjectView, WeakTopicView, XpView,
//  UploadView, HomeView, PageQueries, PageModel) are declared here verbatim…

export const SUBJECT_SHORT_NAMES: Readonly<Record<string, string>> = {
  "0580": "Maths",
  "0606": "Add Maths",
  "0625": "Physics",
}

const DAY_MS = 86_400_000

export function toHomeFacts(o: Overview, xp: XpProfile | null, upload: UploadRun | null, now: Date): HomeFacts {
  const live = upload?.status === "processing" ? upload : null
  return {
    now,
    activeUpload: live ? { paperLabel: live.paperLabel ?? "" } : null,
    subjects: o.subjects.map((s) => ({
      code: s.code, papers: s.papers, grade: s.grade, previousGrade: s.previousGrade, nextExamOn: s.nextExamOn,
    })),
    upcomingSessions: o.upcomingSessions.map((s) => ({
      sessionId: s.sessionId, subjectCode: s.subjectCode, title: s.title, minutes: s.minutes, scheduledFor: s.scheduledFor,
    })),
    weakTopics: o.weakTopics.map((t) => ({ topic: t.topic, subjectCode: t.subjectCode, acc: t.acc })),
    latestResult: o.latestResult
      ? {
          subjectCode: o.latestResult.subjectCode, grade: o.latestResult.grade, paperId: o.latestResult.paperId,
          paperLabel: o.latestResult.paperLabel, seen: o.latestResult.seen, recordedAt: o.latestResult.recordedAt,
        }
      : null,
    calendar: xp ? xp.calendar.map((d) => ({ day: d.day, xp: d.xp })) : [],
  }
}

const totalPapers = (f: HomeFacts): number => f.subjects.reduce((n, s) => n + s.papers, 0)
const earned = (f: HomeFacts, iso: string): boolean => f.calendar.some((d) => d.day === iso && d.xp > 0)

function streakReset(f: HomeFacts): boolean {
  const today = localISODate(f.now)
  const yesterday = localISODate(new Date(f.now.getFullYear(), f.now.getMonth(), f.now.getDate() - 1))
  return !earned(f, today) && !earned(f, yesterday)
}

/**
 * The 14-state table of spec §3, evaluated top to bottom. Thresholds follow
 * fixtures.ts (the fixture wins on conflict): sparse2 covers 2–5 papers, not
 * 2–4, so a 5-paper student with a subject still to plant and a live streak is
 * not dropped into the populated layout, which has no seed pots.
 */
export function homeState(f: HomeFacts): DataState {
  const papers = totalPapers(f)
  const missing = f.subjects.some((s) => s.papers === 0)
  const noExamDate = f.subjects.some((s) => s.nextExamOn === null)
  if (papers === 0) return f.activeUpload ? "sparse0" : "new"
  if (f.activeUpload) return "marking"
  if (papers === 1) return missing ? "sparse1" : "one-paper"
  if (papers <= 5) {
    const last = f.latestResult ? Date.parse(f.latestResult.recordedAt) : 0
    if (f.now.getTime() - last >= 7 * DAY_MS && streakReset(f)) return "sparse3"
    if (missing || noExamDate) return "sparse2"
  }
  if (f.latestResult && f.latestResult.seen === false) return "result-in"
  if (streakReset(f) && f.calendar.some((d) => d.xp > 0)) return "streak-zero"
  if (f.upcomingSessions.length === 0) return "no-plan"
  if (f.subjects.length > 0 && f.subjects.every((s) => s.nextExamOn === null)) return "no-exams"
  return "populated"
}

export function toHomeView(o: Overview, xp: XpProfile | null, upload: UploadRun | null, now: Date): HomeView {
  const facts = toHomeFacts(o, xp, upload, now)
  const live = upload?.status === "processing" ? upload : null
  return {
    facts,
    state: homeState(facts),
    action: deriveNextAction(facts),
    mood: binnyMood(facts),
    week: streakStrip(facts.calendar, now),
    studentName: o.studentName,
    subjects: o.subjects.map((s) => ({
      code: s.code, name: s.name, shortName: SUBJECT_SHORT_NAMES[s.code] ?? s.name,
      papers: s.papers, grade: s.grade, previousGrade: s.previousGrade,
      pct: s.papers > 0 ? s.pct : null, firstPct: s.firstPct,
      nextExamOn: s.nextExamOn, examAvailability: s.examAvailability,
      boundaries: s.boundaries, boundariesEstimated: s.boundariesEstimated, lastPaperOn: s.lastPaperOn,
    })),
    weakTopics: [...o.weakTopics].sort((a, b) => a.acc - b.acc),
    latestScore: o.latestResult ? { awarded: o.latestResult.awarded, maximum: o.latestResult.maximum } : null,
    xp: xp
      ? {
          totalXp: xp.totalXp, level: xp.level,
          intoLevel: xp.totalXp - xp.levelStartXp, levelSpan: xp.nextLevelXp - xp.levelStartXp,
          streak: xp.streak.current, longest: xp.streak.longest, freezes: xp.streak.freezesAvailable,
        }
      : null,
    upload: live ? { paperLabel: live.paperLabel, subjectCode: live.subjectCode, progress: live.progress, stale: live.stale } : null,
    planEndedOn: o.planEndedOn,
    totalPapers: totalPapers(facts),
  }
}

export function pageState(q: PageQueries, now: Date): PageModel {
  const o = q.overview
  if (o.data === undefined) {
    if (o.isError) return { kind: "error", message: studentLoadFailureMessage(o.error) }
    return { kind: "loading" }
  }
  if (q.xp.data === undefined && q.xp.isPending) return { kind: "loading" }
  if (q.upload.data === undefined && q.upload.isPending) return { kind: "loading" }
  const view = toHomeView(o.data, q.xp.data ?? null, q.upload.data ?? null, now)
  return { kind: "ready", view, stale: o.isError ? { at: o.dataUpdatedAt } : null }
}
```

Check the ordering against the fixtures before running. `marking` has 22 papers plus an upload → `marking`. `sparse3` has 5 papers, its last paper is 9 days old, and there is no XP on 4 or 5 Nov → `sparse3`. `sparse2` has 4 papers and XP today → not sparse3; it is missing 0625 → `sparse2`. `streak-zero` has 22 papers, the result is seen, and there is no XP on 4/5 Nov but XP earlier → `streak-zero`. The tests prove this; if one fails, fix `homeState`, never the fixture. If a real conflict with the spec table appears, update the spec table (spec §3: "the fixture wins and this table is updated") and record it in the commit message.

- [ ] **Step 5: Run**

Run: `cd web && npx vitest run tests/unit/studentHomeFacts.test.ts tests/unit/studentHomeFormat.test.ts tests/unit/studentHomeModel.test.ts tests/unit/studentHomeFixtures.test.ts`
Expected: all PASS. The last two prove `model.ts` and `fixtures.ts` are untouched.

Run: `cd web && node -e "import('./dev-previews/student-home/api-fixtures.ts').then(m => console.log(Object.keys(m.API_FIXTURES).length))"`
Expected: `12` (proves the drift script can load it without a bundler).

Run: `cd web && npx tsc -b --noEmit`. Expected: no new errors.

- [ ] **Step 6: Update the spec table**

In the spec's §3 table, change `sparse2`'s trigger to "2–5 papers, at least one subject with no paper or no exam date (and not sparse3)". Add one sentence under the table: "Evaluated top to bottom in the order of `homeState` in `facts.ts`: new, sparse0, marking, sparse1, one-paper, sparse3, sparse2, result-in, streak-zero, no-plan, no-exams, populated."

- [ ] **Step 7: Commit**

```bash
/home/sico/Code/Lemely/.venv/bin/pre-commit run --files web/dev-previews/student-home/api-fixtures.ts web/src/portals/student/home/facts.ts web/src/portals/student/home/format.ts web/tests/unit/studentHomeFacts.test.ts web/tests/unit/studentHomeFormat.test.ts docs/superpowers/specs/2026-11-06-student-home-overview-design.md
git commit -S -m "feat(web): student home facts adapter, state picker and API fixtures" -- web/dev-previews/student-home/api-fixtures.ts web/src/portals/student/home/facts.ts web/src/portals/student/home/format.ts web/tests/unit/studentHomeFacts.test.ts web/tests/unit/studentHomeFormat.test.ts docs/superpowers/specs/2026-11-06-student-home-overview-design.md
```

---

## Task 9: Drift scenes, route mocks and the dev mount

**Files:**
- Create: `web/scripts/home-drift/overview.mjs`
- Modify: `web/scripts/home-drift.mjs` (register the Overview scenes; add element clipping and `--only` if the shell plan's version lacks them)
- Create: `web/src/portals/student/home/StudentHome.tsx` (minimal mount; Task 17 completes it)
- Modify: `web/src/portals/student/index.tsx` (dev-only route `/student/home-next`)

**Interfaces:**
- Consumes: `API_FIXTURES`, `API_NOW` (Task 8); the shell plan's drift script: its `Scene` shape, theme switch, auth, equal-content-width capture and pixelmatch pass rule. Read `web/scripts/home-drift.mjs` first and adapt the field names below to it. The content of each scene stays as written here.
- Produces: everything in Shared interfaces under "Drift scenes"; route `/student/home-next` (only when `import.meta.env.DEV`) rendering `<StudentHome />`.

- [ ] **Step 1: Write `overview.mjs`**

```js
/*
 * Overview scenes for the home drift gate (spec 2026-11-06 §4).
 * Preview: student-home-a.html?state=<id>&motion=reduce (&theme=dark).
 * App: /student/home-next (Task 17 moves it to /student), API mocked from
 * API_FIXTURES, clock pinned to the fixtures' NOW (Thu 5 Nov 2026 10:00).
 */
import { API_FIXTURES, API_NOW } from "../../dev-previews/student-home/api-fixtures.ts"

export const OVERVIEW_STATES = [
  "populated", "result-in", "new", "one-paper", "sparse0", "sparse1", "sparse2", "sparse3",
  "marking", "no-plan", "no-exams", "streak-zero", "loading", "error",
]
export const WINDOW_WIDTHS = [390, 768, 1024, 1440, 1920]
export const THEMES = ["light", "dark"]
export const APP_PATH = "/student/home-next"

export const PARTS = {
  page: { preview: "#as-main", app: "main" },
  hero: { preview: '[data-when-state="ready"] .ah-hero', app: '[data-home="hero"]' },
  garden: { preview: '[data-when-state="ready"] .a-mo', app: '[data-home="garden"]' },
  next: { preview: ".a-action-card", app: '[data-home="next"]' },
  grades: { preview: ".a-grades", app: '[data-home="grades"]' },
  weak: { preview: ".a-weak", app: '[data-home="weak"]' },
  exams: { preview: ".a-exams", app: '[data-home="exams"]' },
  skeleton: { preview: '[data-when-state="loading"]', app: '[data-home="skeleton"]' },
  error: { preview: ".a-error-wrap", app: '[data-home="error"]' },
  new: { preview: '[data-when-state="new"]', app: '[data-home="new"]' },
}

const json = (body, status = 200) => ({ status, contentType: "application/json", body: JSON.stringify(body) })

/** Register API mocks and pin the clock. `state` is one of OVERVIEW_STATES. */
export async function mockStudentHome(page, state, overrides = {}) {
  const fixture = API_FIXTURES[state === "loading" || state === "error" ? "populated" : state]
  const data = { ...fixture, ...overrides }
  // The error scene shows the banner over the last-known page: load at 09:41, fail the refetch at 10:00.
  const start = state === "error" ? new Date(2026, 10, 5, 9, 41) : API_NOW
  await page.clock.install({ time: start })
  await page.route("**/api/student/overview", async (route) => {
    if (state === "loading") return // never answer: the skeleton stays
    if (state === "error" && page.__homeFail) return route.fulfill(json({ detail: "drift" }, 500))
    return route.fulfill(json(data.overview))
  })
  await page.route("**/api/student/xp", (route) => route.fulfill(json(data.xp)))
  await page.route("**/api/student/uploads/active", (route) => route.fulfill(json(data.upload)))
  await page.route("**/api/student/results/*/seen", (route) => route.fulfill({ status: 204, body: "" }))
}

/** After the first render of the error scene: make the next overview fetch fail and trigger it. */
export async function failOverviewRefetch(page) {
  page.__homeFail = true
  await page.clock.setFixedTime(API_NOW)
  await page.evaluate(() => window.dispatchEvent(new Event("focus")))
  await page.getByRole("status").filter({ hasText: "Couldn't refresh your overview." }).waitFor()
}

/** Scenes for one part. `interactions`: [{ id, preview: async (page) => {}, app: async (page) => {} }]. */
export function overviewScenes({ part, states = OVERVIEW_STATES, interactions = [] }) {
  const sel = PARTS[part]
  const scenes = []
  for (const state of states) {
    for (const width of WINDOW_WIDTHS) {
      for (const theme of THEMES) {
        scenes.push({
          id: `overview:${part}:${state}:${width}:${theme}`,
          width,
          theme,
          preview: { url: `/student-home-a.html?state=${state}&motion=reduce&theme=${theme}`, selector: sel.preview },
          app: {
            url: APP_PATH,
            selector: sel.app,
            setup: async (page) => mockStudentHome(page, state),
            afterLoad: state === "error" ? failOverviewRefetch : undefined,
          },
        })
      }
    }
  }
  for (const it of interactions) {
    for (const width of WINDOW_WIDTHS) {
      for (const theme of THEMES) {
        scenes.push({
          id: `overview:${part}:${it.id}:${width}:${theme}`,
          width,
          theme,
          preview: { url: `/student-home-a.html?state=${it.state}&motion=reduce&theme=${theme}`, selector: sel.preview, afterLoad: it.preview },
          app: { url: APP_PATH, selector: sel.app, setup: async (page) => mockStudentHome(page, it.state, it.overrides), afterLoad: it.app },
        })
      }
    }
  }
  return scenes
}
```

The app must set `reducedMotion: "reduce"` on its browser context, and the preview gets `motion=reduce`. If `home-drift.mjs` creates contexts itself, pass `reducedMotion` through its context options for Overview scenes. Check whether TanStack Query's `focusManager` listens for `visibilitychange` rather than `focus` in this version (`node_modules/@tanstack/query-core/build/modern/focusManager.js`). If it does, dispatch that event instead. Check the app's `QueryClient` `retry` setting (`grep -rn "new QueryClient" web/src`). If overview queries retry, the error scene's `waitFor` needs a timeout that covers the retry backoff, or the route must keep failing until the banner shows.

- [ ] **Step 2: Extend `home-drift.mjs` if needed**

Open it. If its scenes cannot capture an element (only the whole content area), add clipping. Inside the existing capture function, when `scene.preview.selector`/`scene.app.selector` is set, compute `await page.locator(selector).first().boundingBox()` and pass `clip` to `page.screenshot`. Before capture, resize the app window until the two boxes have equal width, using the same loop the script already uses for the content area. If heights differ, compare at `max(height)` with the shorter image padded in magenta (`#ff00ff`), so a height difference shows as differing pixels instead of being cropped away.

If there is no `--only <prefix>` filter, add one that keeps scenes whose `id` starts with the prefix.

Register the scenes: `import { overviewScenes } from "./home-drift/overview.mjs"`, then add the parts as each component lands. Start with `overviewScenes({ part: "page", states: [] })` so the import is exercised, and add parts in Tasks 10–17.

The summary line must be `<prefix> PASS <passed>/<total>` when every scene passes, or `<prefix> FAIL <passed>/<total>` otherwise. Each failing scene's line names its diff image path and its percent of differing pixels.

- [ ] **Step 3: Minimal mount**

`web/src/portals/student/home/StudentHome.tsx`:

```tsx
/* Student home (design A). Task 9 mounts the data flow; Task 17 lays out the sections. */
import { useXpProfile } from "@/lib/hooks/useXpApi"
import { useActiveUpload, useOverview } from "@/lib/hooks/useStudentApi"
import { pageState } from "./facts"

export function StudentHome() {
  const overview = useOverview()
  const xp = useXpProfile()
  const upload = useActiveUpload({ poll: true })
  const model = pageState({ overview, xp, upload }, new Date())
  const state = model.kind === "ready" ? (model.stale ? "error" : model.view.state) : model.kind
  return <div id="sh-root" data-home="page" data-state={state} />
}
```

`web/src/portals/student/index.tsx`, next to the existing lazy `Overview`:

```tsx
const StudentHome = lazy(() => import("./home/StudentHome").then((m) => ({ default: m.StudentHome })))
```

In the route children (near line 944), add `...(import.meta.env.DEV ? [{ path: "home-next", element: <StudentHome /> }] : [])`. Match the shape of the neighbouring route objects.

- [ ] **Step 4: Smoke the harness**

With the preview server (`cd web && npx vite --config vite.preview.config.ts --port 5180 --host 127.0.0.1`) and the app dev server running, as the shell plan's script expects, run:

`cd web && node scripts/home-drift.mjs --only overview:page:populated:1440:light`

Expected: `FAIL 0/1`. The app page is empty, and a diff image is written. This proves the mocks, clock and capture work end to end. Then open `/student/home-next` with the mocks in the Playwright trace or with `--headed`, and confirm `data-state="populated"` on `#sh-root`. Repeat for `?state` `error`: the scene ends with `data-state="error"` after `failOverviewRefetch`.

- [ ] **Step 5: Commit**

```bash
/home/sico/Code/Lemely/.venv/bin/pre-commit run --files web/scripts/home-drift/overview.mjs web/scripts/home-drift.mjs web/src/portals/student/home/StudentHome.tsx web/src/portals/student/index.tsx
git commit -S -m "test(web): overview drift scenes and API mocks for the student home" -- web/scripts/home-drift/overview.mjs web/scripts/home-drift.mjs web/src/portals/student/home/StudentHome.tsx web/src/portals/student/index.tsx
```

---

## Task 10: Home tokens, primitives and the markup test file

**Files:**
- Modify: `web/src/index.css` (home aliases, font-size tokens, keyframes; after the existing `:root[data-theme="dark"]` block and the last `@theme inline` block)
- Modify: `web/src/lib/utils.ts` (`CUSTOM_FONT_SIZE_CLASSES`)
- Modify: `web/tests/unit/utils.test.ts` (the test that pins that list)
- Create: `web/src/portals/student/home/primitives.tsx`
- Test: `web/tests/unit/studentHomeMarkup.test.ts` (create; later component tasks add `describe` blocks to it)

**Interfaces:**
- Consumes: `cn` (`web/src/lib/utils.ts`), react-router `Link`.
- Produces: everything listed under "Primitives" in Shared interfaces, plus these exports, which later tasks use:
  - `VH_CLASS: string`: the `.a-vh` class string, for elements that cannot be wrapped in a span (a visually hidden `h1`).
  - `buttonClass(variant: "primary" | "tonal"): string`: the `.a-btn` classes for a `<button>`.
  - `motionClass(on: boolean, inView: boolean | null, cls: string): string`. Returns `""` when motion is off. Returns `cls` when on. Adds `[animation-play-state:paused]` while `inView === false`. This is the design's "paused on the first frame until the section is in view" rule (variant-a.css:493-501).
  - `GRADE_BG: Readonly<Record<string, string>>`, `GRADE_OUTLINE: Readonly<Record<string, string>>`: grade colour classes for components that size their own grade marks (`.mo-bud`, `.a-stone`, `.a-act-grade`).
  - Tailwind utilities: colours `home-ink-2`, `home-card`, `home-row`, `home-track`, `home-line`, `home-hover`, `home-control`, `home-gold-ink`, `home-grade-c`; font sizes `text-home-display` (64px), `text-home-display-sm` (40), `text-home-headline` (32), `text-home-title` (21), `text-home-body` (16), `text-home-sm` (14), `text-home-label` (11); the CSS variable `--home-card-edge` (use as `[box-shadow:var(--home-card-edge)]`); keyframes `home-fill`, `home-grow`, `home-rise`, `home-rise-in`, `home-peek`, `home-flip`, `home-pop`, `home-bob`, `home-bob-soft`, `home-jump`, `home-cheer`, `home-blink`, `home-blink-quick`, `home-pulse`.

### Token map (canonical for every home component)

The design's custom properties come from `web/dev-previews/student-home/tokens.css` (light :3-111, dark :130-175), `variant-a.css:6-13,94-95,1870-1871` and `shell.css:19-24`. Each maps to an existing `@theme` utility from `web/src/index.css`, to a new `--home-*` alias where index.css has no equal value, or to a literal.

| Design property (file:line) | Light / dark value | Tailwind |
|---|---|---|
| `--md-primary` (tokens:34/131) | `#042f4f` / `#7fb8e0` | `primary` (`bg-primary`, `text-primary`, `outline-primary`) |
| `--md-primary-hover` (tokens:36/132) | | `primary-hover` |
| `--md-on-primary` (tokens:35/133) | | `on-primary` |
| `--md-primary-container` / `--md-on-primary-container` (tokens:37-38/134-135) | | `primary-container` / `on-primary-container` |
| `--a-band-ink` (variant-a:10) | = on-primary-container | `on-primary-container` |
| `--md-tertiary` (tokens:39/140) | gold | `tertiary` |
| `--md-surface` / `--surface-page` (tokens:24,59) | | `surface` |
| `--md-surface-lowest` (tokens:25) | | `surface-container-lowest` |
| `--md-surface-low` / `--surface-section` (tokens:26,60) | | `surface-container-low` |
| `--md-surface-container` (tokens:27) | | `surface-container` |
| `--md-surface-high` (tokens:28) | | `surface-container-high` |
| `--md-surface-highest` (tokens:29) | | `surface-container-highest` |
| `--md-on-surface` / `--text-body` (tokens:30,56) | | `on-surface` |
| `--md-on-surface-variant` / `--text-muted` (tokens:31,58) | | `on-surface-variant` |
| `--text-secondary` (tokens:57/162) | `oklch(0.42 0.02 240)` / on-surface-variant | **new** `home-ink-2` (index.css has no 0.42 ink) |
| `--surface-card` (tokens:61/166) | lowest / surface-high | **new** `home-card` (the role switches token per theme) |
| `--surface-row` (tokens:62/167) | low / container | **new** `home-row` |
| `--surface-hover-tint` (tokens:63/168) | `oklch(0.95 0.015 240)` / highest | **new** `home-hover` |
| `--track` (tokens:67/172) | `oklch(0.94 0.01 240)` (= container-high) / highest | **new** `home-track` |
| `--md-outline` / `--border-default` (tokens:32,65) | | `outline` |
| `--md-outline-subtle` / `--border-subtle` (tokens:33,64) | `oklch(0.92 0.01 240)` / `oklch(0.30 0.018 240)` | `outline-variant` (same values in index.css:49/113) |
| `--border-control` (tokens:66/171) | `oklch(0.85 0.03 240)` / outline | **new** `home-control` |
| `--ah-line` (variant-a:94-95) | border-default / transparent | **new** `home-line` |
| `--a-card-edge` (variant-a:9,13) | `0 0 0 1.5px var(--border-subtle)` / `none` | `[box-shadow:var(--home-card-edge)]` (not a `shadow-*` utility, because `none` inside Tailwind's shadow composition is invalid) |
| `--sh-gold-text` (tokens:118) | `oklch(0.20 0.019 80)` both | **new** `home-gold-ink` |
| `--sh-success-text` (tokens:119/146) | | `success-text` |
| `--sh-grade-astar`, `-a`, `-b`, `-d`, `-e`, `-u` (tokens:120-126) | same values as index.css:56-64 | `grade-a-star`, `grade-a`, `grade-b`, `grade-d`, `grade-e`, `grade-u` |
| `--sh-grade-c` (variant-a:1870-1871) | `oklch(0.47 0.09 75)` / `oklch(0.49 0.09 75)` | **new** `home-grade-c` (index.css `--grade-c` is the old 0.63 gold) |
| `--white` (tokens:14) | `#fff` | `white` |
| `--md-error`, `--md-error-container`, `--md-on-error-container` | | `error`, `error-container`, `on-error-container` |
| `--font-display` / `--font-ui` / `--font-mono` (tokens:69-71) | | `font-display` / `font-sans` / `font-mono` |
| `--fs-display` 64, `--fs-display-sm` 40, `--fs-headline` 32, `--fs-title` 21, `--fs-body` 16, `--fs-body-sm` 14, `--fs-data` 14, `--fs-label` 11 (tokens:73-80) | | **new** `text-home-display`, `text-home-display-sm`, `text-home-headline`, `text-home-title`, `text-home-body`, `text-home-sm` (body-sm and data), `text-home-label`. These set font size only; line height always comes from an explicit `leading-*`. |
| `--ls-display` -0.05em, `--ls-headline-ui` -0.02em, `--ls-label` 0.08em | | `tracking-[-0.05em]`, `tracking-[-0.02em]`, `tracking-[0.08em]` |
| `--lh-body` 1.5 (variant-a:11) | | `leading-normal` |
| `--space-1..12` (tokens:86-94) | 4px steps | Tailwind spacing `1..12` (index.css keeps the default `--spacing: 0.25rem`) |
| `--radius-board/card/tile/inner/button/chip/pill` (tokens:96-102) | 32/24/20/18/14/12/999 | `rounded-board/card/tile/inner/button/chip/pill` |
| `--shadow-hover`, `--shadow-panel` | | `shadow-hover`, `shadow-panel` |
| `--ease-out` | `cubic-bezier(.2,.8,.2,1)` | `ease-out` |
| `--a-ease-expo`, `--ah-ease-x` (variant-a:7,94) | `cubic-bezier(0.16,1,0.3,1)` | `ease-[var(--ease-expo)]`, or inside `animate-[…]` as `var(--ease-expo)` |
| `--dur-fast` .15s, `--dur-base` .2s, `--dur-slow` .35s | | `duration-150`, `duration-200`, `duration-350` |

Dark mode: index.css:6 already declares `@custom-variant dark (&:where([data-theme="dark"], [data-theme="dark"] *))`. The `--home-*` aliases switch on `:root[data-theme="dark"]`, so most components need no `dark:` classes. The preview switches on `.sh-root[data-theme="dark"]`; the drift script sets `data-theme` on `<html>` for the app and passes `theme=dark` to the preview.

### Breakpoint map

The design's page container is `home` on the shell's padded main (variant-a.css:748). `StudentHome`'s root is `@container/home` (Task 18). It sits inside the shell's padded main, so its content box is the same width the preview's queries read.

| Design query | Tailwind v4 variant | Note |
|---|---|---|
| `@container home (max-width: N)` | `@max-[{N+1}px]/home:` | v4 `@max-*` is `width < value`; CSS `max-width: N` is `≤ N` |
| `@container home (min-width: N)` | `@min-[Npx]/home:` | `width >= N` in both |
| `(min-width: A) and (max-width: B)` | `@min-[Apx]/home:@max-[{B+1}px]/home:` | stacked variants |
| `@media (pointer: coarse)` | `pointer-coarse:` | built in since Tailwind 4.1 (repo pins 4.3) |
| `@media (prefers-reduced-motion: …)` | no class. `useMotionOn()` adds animation classes only when motion is allowed | |

**Rule for every home component:** when two container variants set the same property, their ranges must not overlap. Write the tiers as disjoint ranges (`@max-[561px]`, `@min-[561px]:@max-[761px]`, `@min-[761px]:@max-[960px]`, …). The one exception is a pure `@min-*` ladder on one property: v4 sorts `@min-[…]` arbitrary values ascending, so the widest tier wins. Unprefixed base classes may sit under any variants.

Tier shorthand used in the tables below:
- **P** = `@max-[561px]/home:` (≤560)
- **S** = `@min-[561px]/home:@max-[761px]/home:` (561–760)
- **M** = `@max-[761px]/home:` (≤760)
- **T** = `@min-[761px]/home:@max-[960px]/home:` (761–959)
- **D** = `@min-[761px]/home:` (≥761)
- **W** = `@min-[960px]/home:` (≥960)
- **X** = `@min-[960px]/home:@max-[1101px]/home:` (960–1100)
- **XL** = `@min-[1101px]/home:` (≥1101)

- [ ] **Step 1: Add the tokens to `web/src/index.css`**

After the `:root[data-theme="dark"] { … }` block (index.css:82-…), add:

```css
/* Student home (design A) aliases: roles whose value index.css does not already carry,
   or that switch token between themes. Source: web/dev-previews/student-home/tokens.css
   and variant-a.css (critique wave 2 grade C). */
:root {
  --home-ink-2: oklch(0.42 0.02 240);
  --home-card: var(--md-surface-container-lowest);
  --home-row: var(--md-surface-container-low);
  --home-hover: oklch(0.95 0.015 240);
  --home-track: var(--md-surface-container-high);
  --home-line: var(--md-outline);
  --home-control: oklch(0.85 0.03 240);
  --home-card-edge: 0 0 0 1.5px var(--md-outline-variant);
  --home-gold-ink: oklch(0.20 0.019 80);
  --home-grade-c: oklch(0.47 0.09 75);
}
:root[data-theme="dark"] {
  --home-ink-2: var(--md-on-surface-variant);
  --home-card: var(--md-surface-container-high);
  --home-row: var(--md-surface-container);
  --home-hover: var(--md-surface-container-highest);
  --home-track: var(--md-surface-container-highest);
  --home-line: transparent;
  --home-control: var(--md-outline);
  --home-card-edge: none;
  --home-grade-c: oklch(0.49 0.09 75);
}
```

Inside the last `@theme inline { … }` block, add:

```css
  --color-home-ink-2: var(--home-ink-2);
  --color-home-card: var(--home-card);
  --color-home-row: var(--home-row);
  --color-home-hover: var(--home-hover);
  --color-home-track: var(--home-track);
  --color-home-line: var(--home-line);
  --color-home-control: var(--home-control);
  --color-home-gold-ink: var(--home-gold-ink);
  --color-home-grade-c: var(--home-grade-c);
  --text-home-display: 64px;
  --text-home-display-sm: 40px;
  --text-home-headline: 32px;
  --text-home-title: 21px;
  --text-home-body: 16px;
  --text-home-sm: 14px;
  --text-home-label: 11px;
```

At the top level (outside `@theme`, so they are always emitted for arbitrary `animate-[…]` classes), add the design's keyframes. Each is renamed `home-*`, and the source line is in the comment:

```css
/* Student home motion (variant-a.css). Used only through animate-[…] classes that
   components add when useMotionOn() is true; reduced motion never renders them. */
@keyframes home-fill { from { transform: scaleX(0) } }                                  /* ahFill :190 */
@keyframes home-grow { from { transform: scaleY(0) } }                                  /* aGrow :570 */
@keyframes home-rise { from { transform: translateY(8px); opacity: 0 } }                /* aRise :571, haRise :1675 */
@keyframes home-rise-in { from { transform: translateY(8px) scale(0.96); opacity: 0 } } /* aRiseIn :569 */
@keyframes home-peek { from { transform: translateY(40%) } }                            /* haPeek :1676 */
@keyframes home-flip { from { opacity: 0; transform: perspective(300px) rotateX(-80deg) } } /* haFlip :1677 */
@keyframes home-pop { 50% { scale: 1.12 } }                                             /* haPop :1678 */
@keyframes home-bob { 0%, 100% { transform: translateY(0) } 50% { transform: translateY(-7px) } } /* ahBob :189 */
@keyframes home-bob-soft { from { transform: translateY(0) } to { transform: translateY(-5px) } } /* a-bob :267 */
@keyframes home-jump {                                                                  /* aJump :583 */
  0% { transform: none } 25% { transform: translateY(4px) scaleY(0.9) }
  55% { transform: translateY(-24px) scaleY(1.05) } 80% { transform: translateY(2px) scaleY(0.96) } 100% { transform: none }
}
@keyframes home-cheer {                                                                 /* aCheer :584 */
  0%, 100% { transform: none } 30% { transform: translateY(-10px) rotate(-6deg) } 60% { transform: translateY(-4px) rotate(5deg) }
}
@keyframes home-blink { 0%, 94%, 100% { transform: scaleY(1) } 97% { transform: scaleY(0.1) } } /* aBlink :582 */
@keyframes home-blink-quick { 50% { scale: 1 0.1 } }                                    /* bnBlink :1661 */
@keyframes home-pulse { from { opacity: 1 } to { opacity: 0.55 } }                      /* a-pulse :718 */
```

Then check each "same value" row of the token map against index.css. In particular, compare `--grade-a-star/a/b/d/e/u`, `--md-outline-variant` (light and dark), `--md-surface-container-*` (light and dark) and `--ease-expo` with tokens.css. If any value differs, add a `--home-*` alias holding the tokens.css value and use it instead. Record any such alias in the commit message.

- [ ] **Step 2: Register the font sizes with tailwind-merge**

In `web/src/lib/utils.ts`, append to `CUSTOM_FONT_SIZE_CLASSES` (under a `// ── Student home (design A) ──` comment): `"home-display"`, `"home-display-sm"`, `"home-headline"`, `"home-title"`, `"home-body"`, `"home-sm"`, `"home-label"`. Without this, `cn("text-home-sm text-home-ink-2")` drops one of the two classes (utils.ts:5-14 explains why). Add the same seven names to the pinned list in `web/tests/unit/utils.test.ts`. Find the assertion that lists the names with `grep -n "display-hero" web/tests/unit/utils.test.ts`. Then add this case:

```ts
it("keeps a home font size next to a home colour", () => {
  expect(cn("text-home-sm text-home-ink-2")).toBe("text-home-sm text-home-ink-2")
})
```

- [ ] **Step 3: Write the failing markup test**

`web/tests/unit/studentHomeMarkup.test.ts`:

```ts
/*
 * Student home markup: roles, labels and copy, rendered with renderToStaticMarkup
 * (node environment, no jsdom: decision D3.20 in vitest.config.ts). Keyboard and
 * focus behaviour is covered by web/e2e/student-home.spec.ts.
 */
import { createElement, type ReactElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { MemoryRouter } from "react-router-dom"
import { describe, expect, it } from "vitest"
import { ButtonLink, Code, Est, GradeChip, Icon, Mono, Vh, buttonClass, motionClass } from "@/portals/student/home/primitives"

export function html(el: ReactElement): string {
  return renderToStaticMarkup(createElement(MemoryRouter, null, el))
    .replaceAll("&#x27;", "'")
    .replaceAll("&amp;", "&")
}

describe("primitives", () => {
  it("Mono and Code carry the design's mono classes", () => {
    expect(html(createElement(Mono, null, "09:41"))).toContain('class="font-mono tabular-nums font-semibold"')
    expect(html(createElement(Code, null, "0580"))).toContain(">0580</span>")
  })

  it("Vh is visually hidden text, still in the accessibility tree", () => {
    const out = html(createElement(Vh, null, "5 November, today, 25 XP"))
    expect(out).toContain("[clip-path:inset(50%)]")
    expect(out).toContain("5 November, today, 25 XP")
    expect(out).not.toContain("aria-hidden")
  })

  it("Icon is decorative and draws the design's arrow path", () => {
    const out = html(createElement(Icon, { name: "arrow" }))
    expect(out).toContain('aria-hidden="true"')
    expect(out).toContain('d="M4 10h11M11 5.5 15.5 10 11 14.5"')
    expect(html(createElement(Icon, { name: "up", down: true }))).toContain("rotate-180")
  })

  it("ButtonLink renders a link with the primary button classes", () => {
    const out = html(createElement(ButtonLink, { to: "/student/correct", variant: "primary" }, "Upload a paper"))
    expect(out).toContain('href="/student/correct"')
    expect(out).toContain("bg-primary")
    expect(out).toContain("min-h-12")
    expect(buttonClass("tonal")).toContain("bg-primary-container")
  })

  it("GradeChip colours by grade; C uses the bronze home token", () => {
    expect(html(createElement(GradeChip, { grade: "A" }))).toContain("bg-grade-a")
    expect(html(createElement(GradeChip, { grade: "C" }))).toContain("bg-home-grade-c")
    const next = html(createElement(GradeChip, { grade: "A*", kind: "next" }))
    expect(next).toContain("outline-dashed")
    expect(next).toContain("outline-grade-a-star")
    expect(next).toContain('data-grade="A*"')
  })

  it("Est explains itself in its title", () => {
    const out = html(createElement(Est))
    expect(out).toContain('title="No exact boundary for this paper yet; based on past sessions."')
    expect(out).toContain(">estimated<")
  })

  it("motionClass is empty with motion off and paused until in view", () => {
    expect(motionClass(false, true, "animate-[home-fill_1s]")).toBe("")
    expect(motionClass(true, false, "animate-[home-fill_1s]")).toBe("animate-[home-fill_1s] [animation-play-state:paused]")
    expect(motionClass(true, true, "animate-[home-fill_1s]")).toBe("animate-[home-fill_1s]")
    expect(motionClass(true, null, "x")).toBe("x")
  })
})
```

Run: `cd web && npx vitest run tests/unit/studentHomeMarkup.test.ts`
Expected: FAIL, `Cannot find module '@/portals/student/home/primitives'`.

- [ ] **Step 4: Implement `primitives.tsx`**

Mapping (variant-a.css):

| Design rule | Declarations | Tailwind |
|---|---|---|
| `.a-vh` :22-25 | `position:absolute; inline-size:1px; block-size:1px; overflow:hidden; clip-path:inset(50%); white-space:nowrap` | `absolute size-px overflow-hidden [clip-path:inset(50%)] whitespace-nowrap` (not `sr-only`: that uses `clip` and a -1px margin) |
| `.a-ico` :26-29 | `18px; flex:none; fill:none; stroke:currentColor; stroke-width:1.8; round caps/joins` | `size-[18px] flex-none fill-none stroke-current [stroke-width:1.8] [stroke-linecap:round] [stroke-linejoin:round]` |
| `.a-ico-down` :679 | `transform: rotate(180deg)` | `rotate-180` |
| `.a-mono` :30 | `font-family mono; tabular-nums; 600` | `font-mono tabular-nums font-semibold` |
| `.a-code` :31-34 | `font: 600 11px/1 mono; letter-spacing .04em; tabular-nums; color text-muted` | `font-mono font-semibold text-home-label leading-none tracking-[0.04em] tabular-nums text-on-surface-variant` |
| `.a-btn` :79-87 | `inline-flex; center; gap 8; border 0; radius button; font 700 16px/1.2 ui; transition background, transform .15s ease-out; :active scale .97; .a-ico transition transform .2s; :hover .a-ico translateX(3px)` | `inline-flex items-center gap-2 border-0 rounded-button font-sans font-bold leading-[1.2] no-underline cursor-pointer transition-[background-color,transform] duration-150 ease-out active:scale-[0.97] [&_svg]:transition-transform [&_svg]:duration-200 [&_svg]:ease-out hover:[&_svg]:translate-x-[3px]` |
| `.a-btn` sizes :81 | `min-block-size 48; padding 12px 22px; font-size 16` | (primary) `min-h-12 py-3 px-[22px] text-home-body` |
| `.a-btn-primary` :88-89 | `bg md-primary; color on-primary; :hover primary-hover` | `bg-primary text-on-primary hover:bg-primary-hover` |
| `.a-btn-tonal` :587-588 | `bg primary-container; color on-primary-container; 14px; min-h 44; padding 10px 16px; :hover color-mix(primary-container, primary 10%)` | `bg-primary-container text-on-primary-container text-home-sm min-h-11 py-2.5 px-4 hover:bg-[color-mix(in_oklch,var(--md-primary-container),var(--md-primary)_10%)]` |
| `.a-grade-chip, .a-grade-next` :473-476 | `inline-grid; center; 34×32; radius 10px; font 800 21px/1 ui; letter-spacing -.01em` | `inline-grid place-items-center w-[34px] h-8 rounded-[10px] font-sans font-extrabold text-home-title leading-none tracking-[-0.01em]` |
| `.a-grade-chip` :477-481 | `color white; bg by grade (default C)` | `text-white` + `GRADE_BG[grade] ?? "bg-home-grade-c"` |
| `.a-grade-next` :482-485 | `color text-body; bg surface-card; outline 2px dashed grade (default B); offset -2px` | `text-on-surface bg-home-card outline-2 outline-dashed -outline-offset-2` + `GRADE_OUTLINE[grade] ?? "outline-grade-b"` |
| `.a-est` :312-316 | `inline-block; padding 2px 8px; pill; font 600 11px/1.2 mono; letter-spacing .04em; color text-secondary; inset 1px border-default ring; cursor help` | `inline-block py-0.5 px-2 rounded-pill font-mono font-semibold text-home-label leading-[1.2] tracking-[0.04em] text-home-ink-2 [box-shadow:inset_0_0_0_1px_var(--md-outline)] cursor-help` |

The icon paths are copied from the `<symbol>`s at the top of `student-home-a.html` (`a-i-arrow`, `a-i-chev`, `a-i-up`, `a-i-flame`, all `viewBox="0 0 20 20"`). An inline `<path>` renders the same pixels as `<use href>`.

```tsx
/*
 * Student home primitives (design A): the small pieces every section repeats.
 * Class strings map variant-a.css rules one to one (plan Task 10 mapping table).
 */
import { useCallback, useEffect, useRef, useState, useSyncExternalStore, type ReactNode, type RefCallback } from "react"
import { Link } from "react-router-dom"
import { cn } from "@/lib/utils"

export const VH_CLASS = "absolute size-px overflow-hidden [clip-path:inset(50%)] whitespace-nowrap"

export function Mono({ children, className }: { children: ReactNode; className?: string }) {
  return <span className={cn("font-mono tabular-nums font-semibold", className)}>{children}</span>
}

export function Code({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <span className={cn("font-mono font-semibold text-home-label leading-none tracking-[0.04em] tabular-nums text-on-surface-variant", className)}>
      {children}
    </span>
  )
}

export function Vh({ children }: { children: ReactNode }) {
  return <span className={VH_CLASS}>{children}</span>
}

export type IconName = "arrow" | "chev" | "up" | "flame"
const PATHS: Record<IconName, readonly string[]> = {
  arrow: ["M4 10h11M11 5.5 15.5 10 11 14.5"],
  chev: ["M8 5l5 5-5 5"],
  up: ["M10 15.5V5M5.5 9.5 10 5l4.5 4.5"],
  flame: [
    "M10 2.5c.6 2.6 3.9 4.4 3.9 8.3A3.9 3.9 0 0 1 10 14.7a3.9 3.9 0 0 1-3.9-3.9c0-1.7.8-2.8 1.7-3.8.3 1.3 1 2 1.8 2.2-.5-2.6.3-4.9.4-6.7Z",
    "M5 17.5h10",
  ],
}

export function Icon({ name, className, down = false }: { name: IconName; className?: string; down?: boolean }) {
  return (
    <svg
      viewBox="0 0 20 20"
      aria-hidden="true"
      className={cn(
        "size-[18px] flex-none fill-none stroke-current [stroke-width:1.8] [stroke-linecap:round] [stroke-linejoin:round]",
        down && "rotate-180",
        className,
      )}
    >
      {PATHS[name].map((d) => (
        <path key={d} d={d} />
      ))}
    </svg>
  )
}

const BTN =
  "inline-flex items-center gap-2 border-0 rounded-button font-sans font-bold leading-[1.2] no-underline cursor-pointer transition-[background-color,transform] duration-150 ease-out active:scale-[0.97] [&_svg]:transition-transform [&_svg]:duration-200 [&_svg]:ease-out hover:[&_svg]:translate-x-[3px]"
const BTN_VARIANT = {
  primary: "min-h-12 py-3 px-[22px] text-home-body bg-primary text-on-primary hover:bg-primary-hover",
  tonal:
    "min-h-11 py-2.5 px-4 text-home-sm bg-primary-container text-on-primary-container hover:bg-[color-mix(in_oklch,var(--md-primary-container),var(--md-primary)_10%)]",
} as const

export function buttonClass(variant: "primary" | "tonal"): string {
  return `${BTN} ${BTN_VARIANT[variant]}`
}

export function ButtonLink({ to, variant, className, children }: { to: string; variant: "primary" | "tonal"; className?: string; children: ReactNode }) {
  return (
    <Link to={to} className={cn(buttonClass(variant), className)}>
      {children}
    </Link>
  )
}

export const GRADE_BG: Readonly<Record<string, string>> = {
  "A*": "bg-grade-a-star", A: "bg-grade-a", B: "bg-grade-b", C: "bg-home-grade-c", D: "bg-grade-d", E: "bg-grade-e", U: "bg-grade-u",
}
export const GRADE_OUTLINE: Readonly<Record<string, string>> = {
  "A*": "outline-grade-a-star", A: "outline-grade-a", B: "outline-grade-b", C: "outline-home-grade-c", D: "outline-grade-d", E: "outline-grade-e", U: "outline-grade-u",
}
const CHIP = "inline-grid place-items-center w-[34px] h-8 rounded-[10px] font-sans font-extrabold text-home-title leading-none tracking-[-0.01em]"

/**
 * kind "chip" = .a-grade-chip, "next" = .a-grade-next (both sized here).
 * "bud" and "stone" carry only the grade colour: .mo-bud and .a-stone size themselves (Tasks 12, 14).
 */
export function GradeChip({ grade, kind = "chip", className }: { grade: string; kind?: "chip" | "next" | "bud" | "stone"; className?: string }) {
  const cls =
    kind === "chip"
      ? cn(CHIP, "text-white", GRADE_BG[grade] ?? "bg-home-grade-c")
      : kind === "next"
        ? cn(CHIP, "text-on-surface bg-home-card outline-2 outline-dashed -outline-offset-2", GRADE_OUTLINE[grade] ?? "outline-grade-b")
        : GRADE_BG[grade] ?? ""
  return (
    <span data-grade={grade} className={cn(cls, className)}>
      {grade}
    </span>
  )
}

export function Est() {
  return (
    <span
      className="inline-block py-0.5 px-2 rounded-pill font-mono font-semibold text-home-label leading-[1.2] tracking-[0.04em] text-home-ink-2 [box-shadow:inset_0_0_0_1px_var(--md-outline)] cursor-help"
      title="No exact boundary for this paper yet; based on past sessions."
    >
      estimated
    </span>
  )
}

const REDUCE = "(prefers-reduced-motion: reduce)"
function subscribeMotion(onChange: () => void): () => void {
  const mq = window.matchMedia(REDUCE)
  mq.addEventListener("change", onChange)
  return () => mq.removeEventListener("change", onChange)
}

/** False under prefers-reduced-motion (StudentHome mirrors it to data-motion) and during server render. */
export function useMotionOn(): boolean {
  return useSyncExternalStore(subscribeMotion, () => !window.matchMedia(REDUCE).matches, () => false)
}

export function motionClass(on: boolean, inView: boolean | null, cls: string): string {
  if (!on) return ""
  return inView === false ? `${cls} [animation-play-state:paused]` : cls
}

/** Eased count from 0 to target (quartic out). Returns target at once when `on` is false. */
export function useCountUp(target: number, on: boolean, ms = 700): number {
  const [value, setValue] = useState(on ? 0 : target)
  useEffect(() => {
    if (!on) {
      setValue(target)
      return
    }
    let raf = 0
    const start = performance.now()
    const tick = (t: number) => {
      const p = Math.min(1, (t - start) / ms)
      setValue(Math.round(target * (1 - (1 - p) ** 4)))
      if (p < 1) raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [target, on, ms])
  return value
}

/** Section reveal: true once 20% of the element is visible (variant-a.js IntersectionObserver, threshold 0.2). */
export function useInView<T extends Element>(): [RefCallback<T>, boolean] {
  const [inView, setInView] = useState(false)
  const observer = useRef<IntersectionObserver | null>(null)
  const ref = useCallback(
    (el: T | null) => {
      observer.current?.disconnect()
      if (!el || inView) return
      if (typeof IntersectionObserver === "undefined") {
        setInView(true)
        return
      }
      observer.current = new IntersectionObserver(
        (entries) => {
          if (entries.some((e) => e.isIntersecting)) {
            setInView(true)
            observer.current?.disconnect()
          }
        },
        { threshold: 0.2 },
      )
      observer.current.observe(el)
    },
    [inView],
  )
  useEffect(() => () => observer.current?.disconnect(), [])
  return [ref, inView]
}
```

No section in design A counts numbers up (`variant-a.js` has no count-up code). `useCountUp` exists because the spec's interface lists it. Tasks 11–18 do not call it, and adding a count-up later needs the user's approval as an improvement on the design.

- [ ] **Step 5: Run**

Run: `cd web && npx vitest run tests/unit/studentHomeMarkup.test.ts tests/unit/utils.test.ts tests/unit/design-tokens.test.ts`
Expected: all PASS. `design-tokens.test.ts` guards index.css. If it pins the token list, add the new names there too.

Run: `cd web && npx tsc -b --noEmit`
Expected: no new errors.

- [ ] **Step 6: Commit**

```bash
cd web && /home/sico/Code/Lemely/.venv/bin/pre-commit run --files src/index.css src/lib/utils.ts tests/unit/utils.test.ts src/portals/student/home/primitives.tsx tests/unit/studentHomeMarkup.test.ts
git commit -S -m "feat(web): student home tokens and primitives" -- web/src/index.css web/src/lib/utils.ts web/tests/unit/utils.test.ts web/src/portals/student/home/primitives.tsx web/tests/unit/studentHomeMarkup.test.ts
```

---

## Task 11: `HomeHero`

**Files:**
- Create: `web/src/portals/student/home/HomeHero.tsx`
- Modify: `web/src/portals/student/home/StudentHome.tsx` (temporary: render the hero so its drift scenes have something to capture. Task 18 replaces the file)
- Modify: `web/scripts/home-drift.mjs` (register the `hero` part)
- Test: `web/tests/unit/studentHomeMarkup.test.ts` (append)

**Interfaces:**
- Consumes: `HomeView`, `XpView` (`facts.ts`); `StreakDay`, `BinnyMood` (`model.ts`); `greetingWord`, `longDay`, `dayMonth`, `weekdayShort`, `dayOfMonth`, `thousands` (`format.ts`); `Mono`, `Vh`, `motionClass`, `useInView`, `useMotionOn` (Task 10); `Binny` (`web/src/portals/marketing/Binny.tsx`) and `web/src/portals/marketing/brand-tokens.css`.
- Produces:
  - `HomeHero(props: { view: HomeView; lean?: boolean }): JSX.Element`. Root `<section data-home="hero" aria-label="Level and streak">`. `lean` is the Binny lean while the next-step button is hovered or focused (variant-a.js `lean()`). StudentHome owns that state, and `NextStepCard` reports it through `onLean`.
  - `HomeBinny(props: { mood: BinnyMood }): JSX.Element`: the marketing Binny with the preview's mood map. Task 18 reuses it in the new-student block.
  - Pure copy helpers, exported for the tests: `firstName(full: string): string`, `heroKicker(v: HomeView): string`, `binnyCaption(v: HomeView, mode: "mood" | "greeting" | "cheering"): string`, `weekKind(v: HomeView): "kept" | "zero" | "sparse"`, `stripLabel(kind, week: StreakDay[]): string`, `xpScale(xp: number): number`.

Binny: the preview draws `@/portals/marketing/Binny` through `binny-island.tsx` with a six-expression mood map. To pass the drift gate, the hero draws the same component with the same map. The `binny-island.tsx` comment says "the React port draws the real v5 moods". Drawing the v5 moods is a later design change and needs its own drift-log entry.

### Copy templates (every string the hero prints)

| Where (design markup, `page-a.txt` line) | Template | Fixture → output |
|---|---|---|
| h1 `.a-greet` :78 | `name ? "${greetingWord(now)}, ${name}." : "${greetingWord(now)}."` with `name = firstName(studentName)` | populated → "Good morning, Mariam." |
| kicker, populated family :78 | `"${n} subject(s), ${p} paper(s) corrected so far."` with n = subjects with papers, p = `totalPapers` | populated → "3 subjects, 22 papers corrected so far."; one-paper → "1 subject, 1 paper corrected so far." |
| kicker sparse0 | `"Your first paper is being marked."` | |
| kicker sparse1 | `"Your first paper is marked. ${Spelled(missing)} subject(s) to go."` | → "Your first paper is marked. Two subjects to go." |
| kicker sparse2 | `"${p} paper(s) corrected."` + (missing ? `" ${names} is/are still to plant."` : "") with names = missing `shortName`s joined "A, B and C" | → "4 papers corrected. Physics is still to plant." |
| kicker sparse3 | `"Good to see you again."` | |
| caption, mood marking :82 | `"Reading your answers."` | sparse0, marking |
| caption, grade-improved + action result :83 | `"${grade} in ${code}, up from ${previousGrade}."` | result-in → "A in 0580, up from B." |
| caption, paper-marked + action result :84 | `"Your ${paperLabel before ' · '} result is in."` | sparse1 → "Your 0580/42 result is in." |
| caption, grade-improved/paper-marked + session :85 | `"Today's session is ready."` | populated, no-exams |
| caption, grade-improved/paper-marked + practice :86 | `"A short set is ready."` | sparse2, no-plan |
| caption, grade-improved/paper-marked + any other action | `"Ready when you are."` | no design state reaches this (fallback so the caption is never empty) |
| caption, streak-kept :87,90,91 / cheering | `streak === 1 ? "Day 1. Streak started." : "Day ${streak}. Streak kept."` | populated cheer → "Day 9. Streak kept." |
| caption, idle :88-89 | sparse3 ? `"Welcome back, ${name}."` : `"Ready when you are."` | sparse3 → "Welcome back, Mariam."; one-paper, streak-zero → "Ready when you are." |
| caption, greeting :92 | `name ? "Hi, ${name}." : "Hi."` | |
| level :98-101 | `"Level ${level}"` | "Level 7" |
| XP :102 | `thousands(totalXp)` + chip "XP" | "2,340" |
| progressbar :105 | label `"XP to level ${level+1}"`, valuemin 0, valuemax `levelSpan`, valuenow `intoLevel`, valuetext `"${intoLevel} of ${levelSpan} XP to level ${level+1}"`; fill width `intoLevel/levelSpan` | "240 of 500 XP to level 8", fill 48% |
| bar label :108 | `"${intoLevel} / ${levelSpan} XP to level ${level+1}"` | "240 / 500 XP to level 8" |
| week kept head :137 | button `"${streak}-day streak"`, aria-label `"${streak}-day streak. Press to make Binny cheer."`, title "Press to make Binny cheer" | "9-day streak" |
| week kept meta :138 | `"Longest ${longest} · ${freezes} freeze(s) · XP per day"` | "Longest 14 · 1 freeze · XP per day" |
| week zero :152-154 | head "Streak paused." body "Earn XP today to start again. Correct a paper, finish a session, take a quiz or review flashcards." | streak-zero, one-paper |
| week sparse0 :167-168 | head `"Day ${streak}."` body `"Uploading your first paper earned <Mono>${todayXp}</Mono> XP. Come back tomorrow for day ${streak+1}."` | "Day 1." / "…earned 20 XP. Come back tomorrow for day 2." |
| week sparse1 :180-181 | head `"${streak}-day streak"` body `"Practise or upload tomorrow to make it ${streak+1}."` | "1-day streak" / "…make it 2." |
| week sparse2 :193 | head `"${streak}-day streak"` meta `(streak >= longest ? "Your longest yet" : "Longest ${longest}") + " · XP per day"` | "3-day streak" / "Your longest yet · XP per day" |
| week sparse3 :205-206 | head "Welcome back." body "Your streak reset. Your progress didn't. Earn XP today to start a new one." | |
| strip aria-label :140,155,169,182,194,207 | zero: `"XP per day, last 7 days"`; no earned day: `+ ". No XP yet this week."`; only today earned: `+ ". ${xp} XP today."`; else `+ ". Peak ${peak.xp} XP on ${longDay(peak.day)}."` | populated → "…Peak 120 XP on 4 November."; sparse0 → "…20 XP today." |
| day hidden label :141-147 | earned: `"${longDay}${today ? ", today" : ""}, ${xp} XP"`; not earned: today ? `"${longDay}, today, no XP yet"` : `"${longDay}, no XP"` | "5 November, today, 25 XP" |
| day title (kept strip, earned days only) :141 | today ? `"Today · ${xp} XP"` : `"${dayMonth} · ${xp} XP"` | "30 Oct · 60 XP" |
| day visible | weekday `weekdayShort` (uppercased by CSS) over `dayOfMonth`; today shows "Today" (wide) / weekday (narrow ≤760) | "FRI" / "30" |
| xp value over the bar | the first day with the strip's highest XP, earned days only, except in the zero strip of one-paper (the design hides it there via `.ah-op-empty`, variant-a.css:182-183) | populated → "120" on Wed |

The design copy is inconsistent between the hidden day labels of different strips ("no XP yet" vs "no XP", "today, no XP yet" vs "no XP yet"). Those labels are visually hidden, so no drift scene sees them. The template above uses one rule.

### Mapping (variant-a.css, resolved per tier; later rules win as in the cascade)

| Element / design selector | Declarations (file:line) | Tailwind |
|---|---|---|
| section `.ah-hero.ah-card` | `display:grid; align-items:center` :108-112; `background surface-card; border 1.5px solid --ah-line` :101-104; radius board :114 overridden to card at D :1415 and M :212 → card everywhere | `grid items-center rounded-card bg-home-card border-[1.5px] border-home-line` |
| columns / gaps | XL `160px minmax(0,1fr) auto`, col-gap 36 :110-112; X col-gap 24 :195-196; T `160px minmax(0,1fr)`, row-gap 20 :200; S `72px minmax(0,1fr)`, col-gap 20, row-gap 12 :1729-1731; P `56px minmax(0,1fr)`, col-gap 12, row-gap 12 :1747-1749; W row-gap 16 :1632 | `@min-[960px]/home:grid-cols-[160px_minmax(0,1fr)_auto] @min-[1101px]/home:gap-x-9 X gap-x-6 T grid-cols-[160px_minmax(0,1fr)] T gap-x-6 T gap-y-5 S grid-cols-[72px_minmax(0,1fr)] S gap-x-5 S gap-y-3 P grid-cols-[56px_minmax(0,1fr)] P gap-x-3 P gap-y-3 W gap-y-4` |
| areas | W `"binny greet week" "binny level week"` :1632; T `"greet greet" "binny level" "week week"` :1623; S `"greet greet" "binny level" "binny say" "week week"` :1730; P `"greet greet" "binny level" "say say" "week week"` :1748 | `W [grid-template-areas:'binny_greet_week'_'binny_level_week'] T [grid-template-areas:'greet_greet'_'binny_level'_'week_week'] S [grid-template-areas:'greet_greet'_'binny_level'_'binny_say'_'week_week'] P [grid-template-areas:'greet_greet'_'binny_level'_'say_say'_'week_week']` |
| align | W `align-items: stretch` :1632 | `W items-stretch` |
| padding | D 20px 24px :1415; S 20px 24px :1731; P 12px 14px 14px :1295 | `D px-6 D py-5 S px-6 S py-5 P pt-3 P px-3.5 P pb-3.5` |
| min height | :2211-2219, ladder 395/376:361/410:344/561:368/761:426/960:293/974:260/1010:239/1138:205 | `min-h-[395px] @min-[376px]/home:min-h-[361px] @min-[410px]/home:min-h-[344px] @min-[561px]/home:min-h-[368px] @min-[761px]/home:min-h-[426px] @min-[960px]/home:min-h-[293px] @min-[974px]/home:min-h-[260px] @min-[1010px]/home:min-h-[239px] @min-[1138px]/home:min-h-[205px]` (a pure `@min` ladder) |
| `.ah-greet` | `grid-area greet; min-inline-size 0` :1628; W `align-self end; padding-block-end 16; border-bottom 1px subtle` :1633 | `[grid-area:greet] min-w-0 W self-end W pb-4 W border-b W border-outline-variant` |
| h1 `.ah-greet .a-greet` | `.a-greet` :48-51 `800 display, letter-spacing -.04em, text-body, balance` + :1629 `32px/1.05` | `m-0 font-display font-extrabold text-home-headline leading-[1.05] tracking-[-0.04em] text-on-surface text-balance` |
| `.ah-greet .a-kicker` | :52 `color text-secondary` + :1630 `margin 4px 0 0; 14px` | `mt-1 text-home-sm text-home-ink-2` |
| figure `.ah-binny` | :116 `grid-area binny; margin 0; flex column; gap 8`; W :1643,1648 `relative; gap 0; justify-content flex-end`; M :1721 `display: contents` | `[grid-area:binny] m-0 flex flex-col gap-2 W relative W gap-0 W justify-end M contents` |
| tile `.ah-binny-tile` (button) | :117-122 `grid; center; padding 8; radius tile; bg primary-container`; :1342-1343 reset + focus offset 3px; :522 `cursor pointer; transition transform .35s expo`; T height 80 :1416; W :1644+1649 `relative; overflow visible; h 116; margin-top 32; padding 0; align-content start`; M :215,1722 `grid-area binny; align-self center; flex none; radius 50%; padding 6; min-h 0`; S 72×72 :1733; P 56×56 :1751 | `m-0 border-0 appearance-none grid place-items-center rounded-tile bg-primary-container text-inherit [font:inherit] cursor-pointer transition-transform duration-350 ease-[var(--ease-expo)] focus-visible:outline-offset-[3px] T h-20 T p-2 W relative W overflow-visible W h-[116px] W mt-8 W p-0 W content-start M [grid-area:binny] M self-center M flex-none M rounded-full M p-1.5 M min-h-0 S size-[72px] P size-14` |
| tile `svg` | :123 `display block; inline-size auto; h 88`; T h 64 :1417; W :1650 `absolute; inset-inline 0; margin-inline auto; bottom 18; h 128`; S h 58 :1734; P h 44 :1752; always :1652 `transform-origin 50% 100%; transition transform .35s expo` | `[&_svg]:block [&_svg]:w-auto [&_svg]:origin-bottom [&_svg]:transition-transform [&_svg]:duration-350 [&_svg]:ease-[var(--ease-expo)] T [&_svg]:h-16 W [&_svg]:absolute W [&_svg]:inset-x-0 W [&_svg]:mx-auto W [&_svg]:bottom-[18px] W [&_svg]:h-32 S [&_svg]:h-[58px] P [&_svg]:h-11` |
| ears | :1641,1653 `transform-box fill-box; origin 50% 100%; transition rotate .2s expo` | `[&_.brand-binny-ear]:[transform-box:fill-box] [&_.brand-binny-ear]:origin-bottom [&_.brand-binny-ear]:transition-[rotate] [&_.brand-binny-ear]:duration-200 [&_.brand-binny-ear]:ease-[var(--ease-expo)]` |
| tile motion | :1655-1659 hover/focus svg `translateY(-6px)`, ears ±10deg, hover eyes bnBlink .3s, active svg `translateY(2px) scale(1.03,.95)` 80ms; :523 eyes aBlink 3.6s, origin 100px 140px; :1667 svg haPeek .7s expo .2s both; :525-526 jump/cheer 500ms expo; :524 lean `rotate(-5deg) translateY(-2px)` | motion only: `[&:is(:hover,:focus-visible)_svg]:[transform:translateY(-6px)] [&:is(:hover,:focus-visible)_.brand-binny-ear-left]:rotate-[-10deg] [&:is(:hover,:focus-visible)_.brand-binny-ear-right]:rotate-[10deg] [&:hover_.brand-binny-eyes]:animate-[home-blink-quick_300ms_linear] [&:active_svg]:[transform:translateY(2px)_scale(1.03,0.95)] [&:active_svg]:duration-75 [&_.brand-binny-eyes]:origin-[100px_140px] [&_.brand-binny-eyes]:animate-[home-blink_3.6s_linear_infinite]`; svg animation per state (see code); lean `[transform:rotate(-5deg)_translateY(-2px)]` |
| figcaption `.ah-say` | :124-128 `padding 7px 10px; radius 10; bg surface-row; 600 14px/1.35 ui; text-body; pretty`; W :1645+1854 `absolute; z 1; inset-inline 10; bottom -12; padding 5px 10px; 14px/1.3; center; shadow-hover; bg surface-card`; dark no shadow :1875; M :217,1723 `grid-area say; flex 1; padding 8px 12px; justify-self start`; P :1753 `justify-self stretch` | `rounded-[10px] bg-home-row py-[7px] px-2.5 font-sans font-semibold text-home-sm leading-[1.35] text-on-surface text-pretty W absolute W z-[1] W inset-x-2.5 W -bottom-3 W py-[5px] W leading-[1.3] W text-center W shadow-hover W bg-home-card dark:shadow-none M [grid-area:say] M flex-1 M py-2 M px-3 S justify-self-start P justify-self-stretch` |
| `.ah-level` | :130; W self-start :1634 | `[grid-area:level] W self-start` |
| `.ah-level-row` | :131 `flex wrap; baseline; space-between; gap 6px 20px`; M nowrap :219 | `flex flex-wrap items-baseline justify-between gap-x-5 gap-y-1.5 M flex-nowrap` |
| `.ah-level-n` | :132 `800 display; -.04em; lining-nums`; D 32/1 :1418; M :1724 `800 21px/1.15 ui; -.02em` | `font-extrabold [font-variant-numeric:lining-nums] D font-display D text-home-headline D leading-none D tracking-[-0.04em] M font-sans M text-home-title M leading-[1.15] M tracking-[-0.02em]` |
| `.ah-xp` | :133 `flex; center; gap 8`; M gap 6 :221 | `flex items-center gap-2 M gap-1.5` |
| `.ah-xp-n` | :134 `600 mono, line-height 1; -.02em; tabular`; D 16 :1419; S 21 :222; P 16 :1754 | `font-mono font-semibold leading-none tracking-[-0.02em] tabular-nums D text-home-body S text-home-title P text-home-body` |
| `.ah-xp-u` | :135-139 `padding 4px 7px; pill; bg tertiary; gold ink; 700 11px/1 mono; .08em`; M padding-inline 6 :223 | `py-1 px-[7px] rounded-pill bg-tertiary text-home-gold-ink font-mono font-bold text-home-label leading-none tracking-[0.08em] M px-1.5` |
| `.ah-bar` | :140-143 `overflow hidden; pill; bg track`; D h 8, mt 12 :1420; S h 10 :224, mt 8 :1299; P h 8, mt 6 :1755 | `overflow-hidden rounded-pill bg-home-track D h-2 D mt-3 S h-2.5 S mt-2 P h-2 P mt-1.5` |
| `.ah-bar-fill` | :144-150 `block; h 100%; radius inherit; bg primary; origin 0 50% (rtl 100%)`; width from data; motion :1669 ahFill .7s expo .45s, paused until in view | `block h-full rounded-[inherit] bg-primary origin-left rtl:origin-right` + `style={{ inlineSize }}` + `motionClass(m, inView, "animate-[home-fill_700ms_var(--ease-expo)_450ms_both]")` |
| `.ah-bar-label` | :151 `margin-top 6; 600 14px/1.4 mono; secondary; tabular` | `mt-1.5 font-mono font-semibold text-home-sm leading-[1.4] text-home-ink-2 tabular-nums` |
| `.ah-week` | :153 `grid-area week; padding-left 36; border-left 1px subtle`; X padding-left 24 :197; W self-center :1635; T :201 `pl 0; pt 20; border-top`; S pt 16 :1735; P pt 12 :1756 | `[grid-area:week] border-outline-variant XL pl-9 X pl-6 W border-l W self-center T pt-5 T border-t S pt-4 S border-t P pt-3 P border-t` |
| `.ah-week-head` | :154 `flex wrap; baseline; space-between; gap 4px 16px`; mb 8 at D :1421 and M :1725; M gap 2px 12px :232 | `flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 mb-2 M gap-x-3 M gap-y-0.5` |
| `.ah-week-n` | :155 `800 32px/1 display; -.04em; balance`; M :1724 `800 21px/1.15 ui; -.02em` | `font-extrabold text-balance D font-display D text-home-headline D leading-none D tracking-[-0.04em] M font-sans M text-home-title M leading-[1.15] M tracking-[-0.02em]` |
| `.ah-streak` (button) | :1344-1352,1887-1892 `reset; radius 10; inherit font; cursor; color transition .15s; hover primary; focus offset 4; coarse padding-block 8 / margin -8; ::after 45px hit area` | `relative m-0 p-0 border-0 rounded-[10px] bg-transparent appearance-none [font:inherit] [letter-spacing:inherit] text-inherit text-start cursor-pointer transition-colors duration-150 ease-out hover:text-primary focus-visible:outline-offset-4 pointer-coarse:py-2 pointer-coarse:-my-2 after:absolute after:content-[''] after:inset-y-[min(0px,calc((100%-45px)/2))] after:inset-x-[min(0px,calc((100%-45px)/2))]` |
| `.ah-week-meta` | :156 `600 14px/1.4 mono; secondary; tabular`; M 11px nowrap :231 | `font-mono font-semibold text-home-sm leading-[1.4] text-home-ink-2 tabular-nums M text-home-label M whitespace-nowrap` |
| `.ah-week-body` | :157 `max 46ch; margin -4px 0 12px; 14px; secondary; pretty`; M margin -2px 0 10px :233; 561–959 max none :2221 | `max-w-[46ch] -mt-1 mb-3 text-home-sm text-home-ink-2 text-pretty M -mt-0.5 M mb-2.5 @min-[561px]/home:@max-[960px]/home:max-w-none` |
| `.ah-strip` | :160 + final :1481 `grid; repeat(7, minmax(0,1fr)); stretch; gap 4; no list styling` | `m-0 p-0 list-none grid grid-cols-7 gap-1` |
| `.ah-day` | :161 + :1482 `flex column; gap 4; align stretch; center; color secondary` | `flex flex-col items-stretch gap-1 text-center text-home-ink-2` |
| `.ah-xp-col` | :173-177 `flex column; justify end; center; full width; border-bottom 1px subtle`; height 30 :1483, P 28 :1757 | `flex flex-col justify-end items-center w-full border-b border-outline-variant h-[30px] P h-7` |
| `.ah-xp-bar` | :178 + :1484 `w calc(100% - 12px); h calc(--xp × 24px); radius 4 4 0 0; bg tertiary`; P ×20px :1758; motion :1672 aGrow .45s, origin bottom, delay .6s + di×60ms, paused until in view; streak-zero fade opacity .45 :1863 | `w-[calc(100%-12px)] h-[calc(var(--xp)*24px)] P h-[calc(var(--xp)*20px)] rounded-t-[4px] bg-tertiary` + fade `opacity-45` + `motionClass(m, inView, "origin-bottom animate-[home-grow_450ms_var(--ease-expo)_calc(600ms+var(--di)*60ms)_both]")` |
| `.ah-xp-val` | :179 `margin-bottom 3; 600 11px/1 mono; secondary; tabular` | `mb-[3px] font-mono font-semibold text-home-label leading-none text-home-ink-2 tabular-nums` + fade `opacity-45` |
| `.ah-day-w` | :162 `600 11px/1 mono; .04em; uppercase`; M letter-spacing 0 :238; today primary :169; streak-zero fade muted :1864 | `font-mono font-semibold text-home-label leading-none tracking-[0.04em] uppercase M tracking-normal` + today `text-primary` / fade `text-on-surface-variant` |
| `.ah-day-d` | :163-167 + final :1485 `grid; center; w 100%; h 36; radius chip; 600 16px/1 mono; -.02em; tabular; bg surface-row; color muted`; earned :1859 `bg color-mix(tertiary 38%, surface-card); text-body`; earned today :1860 `bg tertiary; gold ink`; today :170 `outline 2px primary; offset 2`; streak-zero earned past :1862 `color-mix(tertiary 14%, surface-card); muted`; motion :1671,1673 haFlip .45s (today .91s + haPop .4s 1.2s), origin top | `grid place-items-center w-full h-9 rounded-chip font-mono font-semibold text-home-body leading-none tracking-[-0.02em] tabular-nums` + state classes (see `dayTile()`) + `motionClass(…)` |
| wide/narrow | :184,240-241 | wide `M hidden`; narrow `hidden M inline` |

(The table's **T/S/P/M/D/W/X/XL** stand for the prefixes defined in Task 10. In code each one is the literal variant string, written out in full so Tailwind's scanner sees it.)

- [ ] **Step 1: Write the failing tests (append to `studentHomeMarkup.test.ts`)**

```ts
import { API_FIXTURES, API_NOW, type DataStateId } from "../../dev-previews/student-home/api-fixtures"
import { toHomeView } from "@/portals/student/home/facts"
import { HomeHero, binnyCaption, heroKicker, stripLabel, weekKind, xpScale } from "@/portals/student/home/HomeHero"

const viewOf = (s: DataStateId) => {
  const { overview, xp, upload } = API_FIXTURES[s]
  return toHomeView(overview, xp, upload, API_NOW)
}
const hero = (s: DataStateId) => html(createElement(HomeHero, { view: viewOf(s) }))

describe("HomeHero", () => {
  it("populated: greeting, kicker, level, XP bar, kept week", () => {
    const out = hero("populated")
    expect(out).toContain('data-home="hero"')
    expect(out).toContain('aria-label="Level and streak"')
    expect(out).toMatch(/<h1[^>]*>Good morning, Mariam\.<\/h1>/)
    expect(out).toContain("3 subjects, 22 papers corrected so far.")
    expect(out).toContain(">Level 7<")
    expect(out).toContain(">2,340<")
    expect(out).toContain('role="progressbar"')
    expect(out).toContain('aria-label="XP to level 8"')
    expect(out).toContain('aria-valuenow="240"')
    expect(out).toContain('aria-valuemax="500"')
    expect(out).toContain('aria-valuetext="240 of 500 XP to level 8"')
    expect(out).toContain("240 / 500 XP to level 8")
    expect(out).toContain('aria-label="9-day streak. Press to make Binny cheer."')
    expect(out).toContain("Longest 14 · 1 freeze · XP per day")
    expect(out).toContain('aria-label="XP per day, last 7 days. Peak 120 XP on 4 November."')
    expect(out.match(/<li /g)).toHaveLength(7)
    expect(out).toContain('aria-current="date"')
    expect(out).toContain("5 November, today, 25 XP")
    expect(out).toContain('aria-live="polite"')
    expect(out).toContain("Today's session is ready.")
    expect(out).toContain('aria-label="Binny, your study buddy. Press to say hi."')
  })

  it.each<[DataStateId, string]>([
    ["one-paper", "1 subject, 1 paper corrected so far."],
    ["sparse0", "Your first paper is being marked."],
    ["sparse1", "Your first paper is marked. Two subjects to go."],
    ["sparse2", "4 papers corrected. Physics is still to plant."],
    ["sparse3", "Good to see you again."],
  ])("%s kicker", (s, text) => {
    expect(heroKicker(viewOf(s))).toBe(text)
  })

  it.each<[DataStateId, string]>([
    ["populated", "Today's session is ready."],
    ["result-in", "A in 0580, up from B."],
    ["sparse1", "Your 0580/42 result is in."],
    ["sparse0", "Reading your answers."],
    ["marking", "Reading your answers."],
    ["sparse2", "A short set is ready."],
    ["no-plan", "A short set is ready."],
    ["one-paper", "Ready when you are."],
    ["streak-zero", "Ready when you are."],
    ["sparse3", "Welcome back, Mariam."],
  ])("%s caption", (s, text) => {
    expect(binnyCaption(viewOf(s), "mood")).toBe(text)
  })

  it("greeting and cheering captions", () => {
    expect(binnyCaption(viewOf("populated"), "greeting")).toBe("Hi, Mariam.")
    expect(binnyCaption(viewOf("populated"), "cheering")).toBe("Day 9. Streak kept.")
    expect(binnyCaption(viewOf("sparse0"), "cheering")).toBe("Day 1. Streak started.")
  })

  it("week kinds and strip labels", () => {
    expect(weekKind(viewOf("populated"))).toBe("kept")
    expect(weekKind(viewOf("streak-zero"))).toBe("zero")
    expect(weekKind(viewOf("one-paper"))).toBe("zero")
    expect(weekKind(viewOf("sparse2"))).toBe("sparse")
    expect(stripLabel("sparse", viewOf("sparse0").week)).toBe("XP per day, last 7 days. 20 XP today.")
    expect(stripLabel("sparse", viewOf("sparse3").week)).toBe("XP per day, last 7 days. No XP yet this week.")
    expect(stripLabel("sparse", viewOf("sparse2").week)).toBe("XP per day, last 7 days. Peak 60 XP on 3 November.")
    expect(stripLabel("zero", viewOf("streak-zero").week)).toBe("XP per day, last 7 days")
    expect([xpScale(20), xpScale(35), xpScale(120), xpScale(500)]).toEqual([0.167, 0.292, 1, 1])
  })

  it("sparse weeks", () => {
    expect(hero("sparse0")).toContain("Day 1.")
    expect(hero("sparse0")).toContain("Come back tomorrow for day 2.")
    expect(hero("sparse1")).toContain("Practise or upload tomorrow to make it 2.")
    expect(hero("sparse2")).toContain("Your longest yet · XP per day")
    expect(hero("sparse2")).toContain("120 / 200 XP to level 3")
    expect(hero("sparse3")).toContain("Your streak reset. Your progress didn't. Earn XP today to start a new one.")
  })

  it("zero week has no streak button", () => {
    const out = hero("streak-zero")
    expect(out).toContain("Streak paused.")
    expect(out).not.toContain("Press to make Binny cheer")
  })

  it("XP failure keeps the greeting and drops level and week", () => {
    const { overview, upload } = API_FIXTURES.populated
    const out = html(createElement(HomeHero, { view: toHomeView(overview, null, upload, API_NOW) }))
    expect(out).toContain("Good morning, Mariam.")
    expect(out).not.toContain('role="progressbar"')
    expect(out).not.toContain("XP per day")
  })
})
```

Run: `cd web && npx vitest run tests/unit/studentHomeMarkup.test.ts`
Expected: FAIL, `Cannot find module '@/portals/student/home/HomeHero'`.

- [ ] **Step 2: Implement `HomeHero.tsx`**

```tsx
/* Student home hero (design A `.ah-hero`): greeting, Binny, level and XP, the week.
 * Classes map variant-a.css per container tier (plan Task 11 mapping table). */
import { useEffect, useId, useRef, useState, type CSSProperties } from "react"
import { Binny, type BinnyMood as MarketingMood } from "@/portals/marketing/Binny"
import "@/portals/marketing/brand-tokens.css"
import { cn } from "@/lib/utils"
import type { HomeView } from "./facts"
import { dayMonth, dayOfMonth, greetingWord, longDay, thousands, weekdayShort } from "./format"
import type { BinnyMood, StreakDay } from "./model"
import { Mono, Vh, motionClass, useInView, useMotionOn } from "./primitives"

const MARKETING_MOOD: Record<BinnyMood, MarketingMood> = {
  marking: "thinking", "grade-improved": "happy", "paper-marked": "open", "streak-kept": "wink", idle: "idle",
}
// .marketing-brand carries the --brand-* tokens Binny fills from; the wrapper neutralises its
// font/colour/background (same object as dev-previews/student-home/binny-island.tsx, minus the
// --binny-* values index.css already declares).
const BRAND_SCOPE = { display: "contents", background: "transparent", color: "inherit", fontFamily: "inherit" } as CSSProperties

export function HomeBinny({ mood }: { mood: BinnyMood }) {
  return (
    <div className="marketing-brand" style={BRAND_SCOPE}>
      <Binny mood={MARKETING_MOOD[mood]} />
    </div>
  )
}

const SPELLED = ["Zero", "One", "Two", "Three", "Four", "Five", "Six"]
const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`
const joinNames = (names: string[]) =>
  names.length <= 1 ? (names[0] ?? "") : `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`

export function firstName(full: string): string {
  return full.trim().split(/\s+/)[0] ?? ""
}

export function heroKicker(v: HomeView): string {
  const missing = v.subjects.filter((s) => s.papers === 0)
  switch (v.state) {
    case "sparse0":
      return "Your first paper is being marked."
    case "sparse1": {
      const n = missing.length
      return `Your first paper is marked. ${SPELLED[n] ?? n} subject${n === 1 ? "" : "s"} to go.`
    }
    case "sparse2": {
      const base = `${plural(v.totalPapers, "paper")} corrected.`
      if (missing.length === 0) return base
      return `${base} ${joinNames(missing.map((s) => s.shortName))} ${missing.length === 1 ? "is" : "are"} still to plant.`
    }
    case "sparse3":
      return "Good to see you again."
    default: {
      const subjects = v.subjects.filter((s) => s.papers > 0).length
      return `${plural(subjects, "subject")}, ${plural(v.totalPapers, "paper")} corrected so far.`
    }
  }
}

function streakLine(v: HomeView): string {
  const n = v.xp?.streak ?? 0
  return n === 1 ? "Day 1. Streak started." : `Day ${n}. Streak kept.`
}

export function binnyCaption(v: HomeView, mode: "mood" | "greeting" | "cheering"): string {
  const name = firstName(v.studentName)
  if (mode === "greeting") return name ? `Hi, ${name}.` : "Hi."
  if (mode === "cheering") return streakLine(v)
  switch (v.mood) {
    case "marking":
      return "Reading your answers."
    case "grade-improved":
    case "paper-marked": {
      const a = v.action
      if (a.kind === "result") {
        if (v.mood === "grade-improved") {
          const previous = v.subjects.find((s) => s.code === a.result.subjectCode)?.previousGrade
          return `${a.result.grade} in ${a.result.subjectCode}, up from ${previous}.`
        }
        return `Your ${a.result.paperLabel.split(" · ")[0]} result is in.`
      }
      if (a.kind === "session") return "Today's session is ready."
      if (a.kind === "practice") return "A short set is ready."
      return "Ready when you are."
    }
    case "streak-kept":
      return streakLine(v)
    case "idle":
      return v.state === "sparse3" ? (name ? `Welcome back, ${name}.` : "Welcome back.") : "Ready when you are."
  }
}

export type WeekKind = "kept" | "zero" | "sparse"
export function weekKind(v: HomeView): WeekKind {
  if (v.state.startsWith("sparse")) return "sparse"
  if (v.state === "streak-zero" || v.state === "one-paper" || (v.xp?.streak ?? 0) === 0) return "zero"
  return "kept"
}

function peakOf(week: StreakDay[]): StreakDay | null {
  return week.filter((d) => d.earned).reduce<StreakDay | null>((best, d) => (best === null || d.xp > best.xp ? d : best), null)
}

export function stripLabel(kind: WeekKind, week: StreakDay[]): string {
  const base = "XP per day, last 7 days"
  if (kind === "zero") return base
  const earned = week.filter((d) => d.earned)
  if (earned.length === 0) return `${base}. No XP yet this week.`
  if (earned.length === 1 && earned[0].isToday) return `${base}. ${earned[0].xp} XP today.`
  const peak = peakOf(week)!
  return `${base}. Peak ${peak.xp} XP on ${longDay(peak.day)}.`
}

/** One shared scale: 120 XP fills the bar (variant-a.css:172). Rounded like the preview's inline styles. */
export function xpScale(xp: number): number {
  return Math.round(Math.min(xp / 120, 1) * 1000) / 1000
}

function dayLabel(d: StreakDay): string {
  if (d.earned) return `${longDay(d.day)}${d.isToday ? ", today" : ""}, ${d.xp} XP`
  return d.isToday ? `${longDay(d.day)}, today, no XP yet` : `${longDay(d.day)}, no XP`
}

function dayTile(d: StreakDay, fade: boolean): string {
  if (d.earned && d.isToday) return "bg-tertiary text-home-gold-ink"
  if (d.earned && fade) return "bg-[color-mix(in_oklch,var(--md-tertiary)_14%,var(--home-card))] text-on-surface-variant"
  if (d.earned) return "bg-[color-mix(in_oklch,var(--md-tertiary)_38%,var(--home-card))] text-on-surface"
  return "bg-home-row text-on-surface-variant"
}

function Day(props: { d: StreakDay; i: number; kind: WeekKind; fade: boolean; showVal: boolean; motion: boolean; inView: boolean }) {
  const { d, i, kind, fade, showVal, motion, inView } = props
  const title = kind === "kept" && d.earned ? (d.isToday ? `Today · ${d.xp} XP` : `${dayMonth(d.day)} · ${d.xp} XP`) : undefined
  const flip = d.isToday
    ? "origin-top animate-[home-flip_450ms_var(--ease-expo)_910ms_both,home-pop_400ms_var(--ease-expo)_1200ms]"
    : "origin-top animate-[home-flip_450ms_var(--ease-expo)_calc(550ms+var(--di)*60ms)_both]"
  return (
    <li
      className="flex flex-col items-stretch gap-1 text-center text-home-ink-2"
      aria-current={d.isToday ? "date" : undefined}
      title={title}
      style={{ "--di": i, "--xp": xpScale(d.xp) } as CSSProperties}
    >
      <span className="flex flex-col justify-end items-center w-full border-b border-outline-variant h-[30px] @max-[561px]/home:h-7">
        {d.earned && showVal && (
          <span aria-hidden="true" className={cn("mb-[3px] font-mono font-semibold text-home-label leading-none text-home-ink-2 tabular-nums", fade && "opacity-45")}>
            {d.xp}
          </span>
        )}
        {d.earned && (
          <span
            className={cn(
              "w-[calc(100%-12px)] h-[calc(var(--xp)*24px)] @max-[561px]/home:h-[calc(var(--xp)*20px)] rounded-t-[4px] bg-tertiary",
              fade && "opacity-45",
              motionClass(motion, inView, "origin-bottom animate-[home-grow_450ms_var(--ease-expo)_calc(600ms+var(--di)*60ms)_both]"),
            )}
          />
        )}
      </span>
      <span
        className={cn(
          "font-mono font-semibold text-home-label leading-none tracking-[0.04em] uppercase @max-[761px]/home:tracking-normal",
          d.isToday && "text-primary",
          fade && d.earned && !d.isToday && "text-on-surface-variant",
        )}
      >
        {d.isToday ? (
          <>
            <span className="@max-[761px]/home:hidden">Today</span>
            <span className="hidden @max-[761px]/home:inline">{weekdayShort(d.day)}</span>
          </>
        ) : (
          weekdayShort(d.day)
        )}
      </span>
      <span
        className={cn(
          "grid place-items-center w-full h-9 rounded-chip font-mono font-semibold text-home-body leading-none tracking-[-0.02em] tabular-nums",
          dayTile(d, fade),
          d.isToday && "outline-2 outline-primary outline-offset-2",
          motionClass(motion, inView, flip),
        )}
      >
        {dayOfMonth(d.day)}
      </span>
      <Vh>{dayLabel(d)}</Vh>
    </li>
  )
}

const WEEK_N =
  "font-extrabold text-balance @min-[761px]/home:font-display @min-[761px]/home:text-home-headline @min-[761px]/home:leading-none @min-[761px]/home:tracking-[-0.04em] @max-[761px]/home:font-sans @max-[761px]/home:text-home-title @max-[761px]/home:leading-[1.15] @max-[761px]/home:tracking-[-0.02em]"
const WEEK_META =
  "font-mono font-semibold text-home-sm leading-[1.4] text-home-ink-2 tabular-nums @max-[761px]/home:text-home-label @max-[761px]/home:whitespace-nowrap"
const WEEK_BODY =
  "max-w-[46ch] -mt-1 mb-3 text-home-sm text-home-ink-2 text-pretty @max-[761px]/home:-mt-0.5 @max-[761px]/home:mb-2.5 @min-[561px]/home:@max-[960px]/home:max-w-none"
const WEEK_HEAD =
  "flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 mb-2 @max-[761px]/home:gap-x-3 @max-[761px]/home:gap-y-0.5"

function WeekHead({ v, kind, onCheer, metaId, motion }: { v: HomeView; kind: WeekKind; onCheer: () => void; metaId: string; motion: boolean }) {
  const xp = v.xp!
  const rise = motion ? "animate-[home-rise_500ms_var(--ease-expo)_450ms_both]" : ""
  if (kind === "kept") {
    return (
      <div className={cn(WEEK_HEAD, rise)}>
        <p className={WEEK_N}>
          <button
            type="button"
            className="relative m-0 p-0 border-0 rounded-[10px] bg-transparent appearance-none [font:inherit] [letter-spacing:inherit] text-inherit text-start cursor-pointer transition-colors duration-150 ease-out hover:text-primary focus-visible:outline-offset-4 pointer-coarse:py-2 pointer-coarse:-my-2 after:absolute after:content-[''] after:inset-y-[min(0px,calc((100%-45px)/2))] after:inset-x-[min(0px,calc((100%-45px)/2))]"
            aria-describedby={metaId}
            aria-label={`${xp.streak}-day streak. Press to make Binny cheer.`}
            title="Press to make Binny cheer"
            onClick={onCheer}
          >
            {xp.streak}-day streak
          </button>
        </p>
        <p className={WEEK_META} id={metaId}>
          Longest {xp.longest} · {plural(xp.freezes, "freeze")} · XP per day
        </p>
      </div>
    )
  }
  if (kind === "zero") {
    return (
      <div className={cn(WEEK_HEAD, rise)}>
        <p className={WEEK_N}>Streak paused.</p>
      </div>
    )
  }
  const head =
    v.state === "sparse0" ? `Day ${xp.streak}.` : v.state === "sparse3" ? "Welcome back." : `${xp.streak}-day streak`
  return (
    <div className={cn(WEEK_HEAD, rise)}>
      <p className={WEEK_N}>{head}</p>
      {v.state === "sparse2" && (
        <p className={WEEK_META}>{xp.streak >= xp.longest ? "Your longest yet" : `Longest ${xp.longest}`} · XP per day</p>
      )}
    </div>
  )
}

function WeekBody({ v, kind }: { v: HomeView; kind: WeekKind }) {
  const xp = v.xp!
  const today = v.week.find((d) => d.isToday)?.xp ?? 0
  if (kind === "zero")
    return <p className={WEEK_BODY}>Earn XP today to start again. Correct a paper, finish a session, take a quiz or review flashcards.</p>
  if (kind !== "sparse") return null
  if (v.state === "sparse0")
    return (
      <p className={WEEK_BODY}>
        Uploading your first paper earned <Mono>{today}</Mono> XP. Come back tomorrow for day {xp.streak + 1}.
      </p>
    )
  if (v.state === "sparse1") return <p className={WEEK_BODY}>Practise or upload tomorrow to make it {xp.streak + 1}.</p>
  if (v.state === "sparse3") return <p className={WEEK_BODY}>Your streak reset. Your progress didn't. Earn XP today to start a new one.</p>
  return null
}

const HOLD_MS = 2400

export function HomeHero({ view, lean = false }: { view: HomeView; lean?: boolean }) {
  const motion = useMotionOn()
  const [ref, inView] = useInView<HTMLElement>()
  const metaId = useId()
  const [mode, setMode] = useState<"mood" | "greeting" | "cheering">("mood")
  const [jump, setJump] = useState<"jump" | "cheer" | null>(null)
  const timer = useRef(0)
  useEffect(() => () => window.clearTimeout(timer.current), [])

  const kind = weekKind(view)
  const canCheer = view.xp !== null && kind !== "zero" && view.state !== "sparse3"
  const hold = (m: "greeting" | "cheering") => {
    window.clearTimeout(timer.current)
    setMode(m)
    timer.current = window.setTimeout(() => setMode("mood"), HOLD_MS)
  }
  const replay = (a: "jump" | "cheer") => {
    setJump(null)
    requestAnimationFrame(() => setJump(a))
  }
  const onTile = () => (motion ? replay("jump") : hold("greeting"))
  const cheer = () => {
    if (!canCheer) return
    hold("cheering")
    if (motion) replay("cheer")
  }

  const name = firstName(view.studentName)
  const hello = greetingWord(view.facts.now)
  const xp = view.xp
  const pct = xp && xp.levelSpan > 0 ? Math.round((xp.intoLevel / xp.levelSpan) * 10000) / 100 : 0
  const peak = peakOf(view.week)
  const fade = view.state === "streak-zero"
  const svgAnim =
    jump === "jump"
      ? "[&_svg]:animate-[home-jump_500ms_var(--ease-expo)]"
      : jump === "cheer"
        ? "[&_svg]:animate-[home-cheer_500ms_var(--ease-expo)]"
        : motion
          ? "[&_svg]:animate-[home-peek_700ms_var(--ease-expo)_200ms_both]"
          : ""

  return (
    <section
      ref={ref}
      data-home="hero"
      aria-label="Level and streak"
      className="grid items-center rounded-card bg-home-card border-[1.5px] border-home-line
        min-h-[395px] @min-[376px]/home:min-h-[361px] @min-[410px]/home:min-h-[344px] @min-[561px]/home:min-h-[368px] @min-[761px]/home:min-h-[426px] @min-[960px]/home:min-h-[293px] @min-[974px]/home:min-h-[260px] @min-[1010px]/home:min-h-[239px] @min-[1138px]/home:min-h-[205px]
        @min-[960px]/home:grid-cols-[160px_minmax(0,1fr)_auto] @min-[960px]/home:[grid-template-areas:'binny_greet_week'_'binny_level_week'] @min-[960px]/home:gap-y-4 @min-[960px]/home:items-stretch
        @min-[1101px]/home:gap-x-9 @min-[960px]/home:@max-[1101px]/home:gap-x-6
        @min-[761px]/home:@max-[960px]/home:grid-cols-[160px_minmax(0,1fr)] @min-[761px]/home:@max-[960px]/home:[grid-template-areas:'greet_greet'_'binny_level'_'week_week'] @min-[761px]/home:@max-[960px]/home:gap-x-6 @min-[761px]/home:@max-[960px]/home:gap-y-5
        @min-[561px]/home:@max-[761px]/home:grid-cols-[72px_minmax(0,1fr)] @min-[561px]/home:@max-[761px]/home:[grid-template-areas:'greet_greet'_'binny_level'_'binny_say'_'week_week'] @min-[561px]/home:@max-[761px]/home:gap-x-5 @min-[561px]/home:@max-[761px]/home:gap-y-3
        @max-[561px]/home:grid-cols-[56px_minmax(0,1fr)] @max-[561px]/home:[grid-template-areas:'greet_greet'_'binny_level'_'say_say'_'week_week'] @max-[561px]/home:gap-x-3 @max-[561px]/home:gap-y-3
        @min-[761px]/home:px-6 @min-[761px]/home:py-5 @min-[561px]/home:@max-[761px]/home:px-6 @min-[561px]/home:@max-[761px]/home:py-5 @max-[561px]/home:pt-3 @max-[561px]/home:px-3.5 @max-[561px]/home:pb-3.5"
    >
      <div
        className={cn(
          "[grid-area:greet] min-w-0 @min-[960px]/home:self-end @min-[960px]/home:pb-4 @min-[960px]/home:border-b @min-[960px]/home:border-outline-variant",
          motion && "animate-[home-rise_500ms_var(--ease-expo)_both]",
        )}
      >
        <h1 className="m-0 font-display font-extrabold text-home-headline leading-[1.05] tracking-[-0.04em] text-on-surface text-balance">
          {name ? `${hello}, ${name}.` : `${hello}.`}
        </h1>
        <p className="mt-1 text-home-sm text-home-ink-2">{heroKicker(view)}</p>
      </div>

      <figure className="[grid-area:binny] m-0 flex flex-col gap-2 @min-[960px]/home:relative @min-[960px]/home:gap-0 @min-[960px]/home:justify-end @max-[761px]/home:contents">
        <button
          type="button"
          aria-label="Binny, your study buddy. Press to say hi."
          title="Say hi to Binny"
          onClick={onTile}
          onAnimationEnd={() => setJump(null)}
          className={cn(
            "m-0 border-0 appearance-none grid place-items-center rounded-tile bg-primary-container text-inherit [font:inherit] cursor-pointer transition-transform duration-350 ease-[var(--ease-expo)] focus-visible:outline-offset-[3px]",
            "[&_svg]:block [&_svg]:w-auto [&_svg]:origin-bottom [&_svg]:transition-transform [&_svg]:duration-350 [&_svg]:ease-[var(--ease-expo)]",
            "[&_.brand-binny-ear]:[transform-box:fill-box] [&_.brand-binny-ear]:origin-bottom [&_.brand-binny-ear]:transition-[rotate] [&_.brand-binny-ear]:duration-200 [&_.brand-binny-ear]:ease-[var(--ease-expo)]",
            "@min-[761px]/home:@max-[960px]/home:h-20 @min-[761px]/home:@max-[960px]/home:p-2 @min-[761px]/home:@max-[960px]/home:[&_svg]:h-16",
            "@min-[960px]/home:relative @min-[960px]/home:overflow-visible @min-[960px]/home:h-[116px] @min-[960px]/home:mt-8 @min-[960px]/home:p-0 @min-[960px]/home:content-start @min-[960px]/home:[&_svg]:absolute @min-[960px]/home:[&_svg]:inset-x-0 @min-[960px]/home:[&_svg]:mx-auto @min-[960px]/home:[&_svg]:bottom-[18px] @min-[960px]/home:[&_svg]:h-32",
            "@max-[761px]/home:[grid-area:binny] @max-[761px]/home:self-center @max-[761px]/home:flex-none @max-[761px]/home:rounded-full @max-[761px]/home:p-1.5 @max-[761px]/home:min-h-0",
            "@min-[561px]/home:@max-[761px]/home:size-[72px] @min-[561px]/home:@max-[761px]/home:[&_svg]:h-[58px] @max-[561px]/home:size-14 @max-[561px]/home:[&_svg]:h-11",
            motion &&
              "[&_.brand-binny-eyes]:origin-[100px_140px] [&_.brand-binny-eyes]:animate-[home-blink_3.6s_linear_infinite] [&:is(:hover,:focus-visible)_svg]:[transform:translateY(-6px)] [&:is(:hover,:focus-visible)_.brand-binny-ear-left]:rotate-[-10deg] [&:is(:hover,:focus-visible)_.brand-binny-ear-right]:rotate-[10deg] [&:hover_.brand-binny-eyes]:animate-[home-blink-quick_300ms_linear] [&:active_svg]:[transform:translateY(2px)_scale(1.03,0.95)] [&:active_svg]:duration-75",
            motion && lean && "[transform:rotate(-5deg)_translateY(-2px)]",
            svgAnim,
          )}
        >
          <HomeBinny mood={mode === "cheering" ? "streak-kept" : view.mood} />
        </button>
        <figcaption
          aria-live="polite"
          className="rounded-[10px] bg-home-row py-[7px] px-2.5 font-sans font-semibold text-home-sm leading-[1.35] text-on-surface text-pretty
            @min-[960px]/home:absolute @min-[960px]/home:z-[1] @min-[960px]/home:inset-x-2.5 @min-[960px]/home:-bottom-3 @min-[960px]/home:py-[5px] @min-[960px]/home:leading-[1.3] @min-[960px]/home:text-center @min-[960px]/home:shadow-hover @min-[960px]/home:bg-home-card dark:shadow-none
            @max-[761px]/home:[grid-area:say] @max-[761px]/home:flex-1 @max-[761px]/home:py-2 @max-[761px]/home:px-3 @min-[561px]/home:@max-[761px]/home:justify-self-start @max-[561px]/home:justify-self-stretch"
        >
          {binnyCaption(view, mode)}
        </figcaption>
      </figure>

      <div className="[grid-area:level] @min-[960px]/home:self-start">
        {xp && (
          <>
            <div className={cn("flex flex-wrap items-baseline justify-between gap-x-5 gap-y-1.5 @max-[761px]/home:flex-nowrap", motion && "animate-[home-rise_500ms_var(--ease-expo)_300ms_both]")}>
              <p className="font-extrabold [font-variant-numeric:lining-nums] @min-[761px]/home:font-display @min-[761px]/home:text-home-headline @min-[761px]/home:leading-none @min-[761px]/home:tracking-[-0.04em] @max-[761px]/home:font-sans @max-[761px]/home:text-home-title @max-[761px]/home:leading-[1.15] @max-[761px]/home:tracking-[-0.02em]">
                Level {xp.level}
              </p>
              <p className="flex items-center gap-2 @max-[761px]/home:gap-1.5">
                <span className="font-mono font-semibold leading-none tracking-[-0.02em] tabular-nums @min-[761px]/home:text-home-body @min-[561px]/home:@max-[761px]/home:text-home-title @max-[561px]/home:text-home-body">
                  {thousands(xp.totalXp)}
                </span>
                <span className="py-1 px-[7px] rounded-pill bg-tertiary text-home-gold-ink font-mono font-bold text-home-label leading-none tracking-[0.08em] @max-[761px]/home:px-1.5">XP</span>
              </p>
            </div>
            <div
              role="progressbar"
              aria-label={`XP to level ${xp.level + 1}`}
              aria-valuemin={0}
              aria-valuemax={xp.levelSpan}
              aria-valuenow={xp.intoLevel}
              aria-valuetext={`${xp.intoLevel} of ${xp.levelSpan} XP to level ${xp.level + 1}`}
              className="overflow-hidden rounded-pill bg-home-track @min-[761px]/home:h-2 @min-[761px]/home:mt-3 @min-[561px]/home:@max-[761px]/home:h-2.5 @min-[561px]/home:@max-[761px]/home:mt-2 @max-[561px]/home:h-2 @max-[561px]/home:mt-1.5"
            >
              <span
                className={cn("block h-full rounded-[inherit] bg-primary origin-left rtl:origin-right", motionClass(motion, inView, "animate-[home-fill_700ms_var(--ease-expo)_450ms_both]"))}
                style={{ inlineSize: `${pct}%` }}
              />
            </div>
            <p className="mt-1.5 font-mono font-semibold text-home-sm leading-[1.4] text-home-ink-2 tabular-nums">
              {xp.intoLevel} / {xp.levelSpan} XP to level {xp.level + 1}
            </p>
          </>
        )}
      </div>

      <div
        className="[grid-area:week] border-outline-variant @min-[1101px]/home:pl-9 @min-[960px]/home:@max-[1101px]/home:pl-6 @min-[960px]/home:border-l @min-[960px]/home:self-center @min-[761px]/home:@max-[960px]/home:pt-5 @min-[761px]/home:@max-[960px]/home:border-t @min-[561px]/home:@max-[761px]/home:pt-4 @min-[561px]/home:@max-[761px]/home:border-t @max-[561px]/home:pt-3 @max-[561px]/home:border-t"
        onPointerEnter={cheer}
        onFocus={cheer}
      >
        {xp && (
          <>
            <WeekHead v={view} kind={kind} onCheer={cheer} metaId={metaId} motion={motion} />
            <WeekBody v={view} kind={kind} />
            <ol className="m-0 p-0 list-none grid grid-cols-7 gap-1" aria-label={stripLabel(kind, view.week)}>
              {view.week.map((d, i) => (
                <Day
                  key={d.day}
                  d={d}
                  i={i}
                  kind={kind}
                  fade={fade}
                  showVal={peak?.day === d.day && !(kind === "zero" && view.state === "one-paper")}
                  motion={motion}
                  inView={inView}
                />
              ))}
            </ol>
          </>
        )}
      </div>
    </section>
  )
}
```

`onFocus` on the week `div` fires for focus inside it, because React's `onFocus` bubbles. This matches the design's `focusin` listener (variant-a.js:250). A `<div>` with pointer and focus handlers is not an interactive element, so it does not need a role. The streak `<button>` is the control.

- [ ] **Step 3: Run the unit tests**

Run: `cd web && npx vitest run tests/unit/studentHomeMarkup.test.ts`
Expected: PASS.

- [ ] **Step 4: Mount the hero for its drift scenes**

Replace the `return` of `StudentHome.tsx` (Task 9's minimal mount):

```tsx
  const view = model.kind === "ready" ? model.view : null
  return (
    <div id="sh-root" data-home="page" data-state={state} className="@container/home font-sans leading-normal text-on-surface">
      {view && view.state !== "new" && <HomeHero view={view} />}
    </div>
  )
```

with `import { HomeHero } from "./HomeHero"`. Register the scenes in `web/scripts/home-drift.mjs`:

```js
...overviewScenes({ part: "hero", states: OVERVIEW_STATES.filter((s) => s !== "loading" && s !== "new") }),
```

`error` stays in the list: the preview keeps the populated ready page, hero included, under the error banner (variant-a.css:1767-1768). `loading` and `new` have no `.ah-hero`.

- [ ] **Step 5: Run the drift gate**

Run: `cd web && node scripts/home-drift.mjs --only overview:hero`
Expected: `overview:hero PASS 120/120` (12 states × 5 widths × 2 themes).

For each failing pair, open `web/reports/home-drift/overview/hero/<scene>.diff.png`. Then:
- A uniform band of differing pixels along one side means a padding, gap or height is off. Find the tier and the row in the mapping table, and check that its variant range matches the width in the scene id.
- Glyph-edge differences only mean a font size, weight, tracking or line height is off. Compare the element's computed style in both pages (`page.locator(sel).evaluate(el => getComputedStyle(el).font)`).
- A colour-only difference means the wrong token. Check the token map.
- Binny differs: confirm that `brand-tokens.css` is loaded and that the mood map is the preview's.

Fix the cause and re-run the failing scene ids (`--only overview:hero:<state>:<width>:<theme>`) until the whole part passes. A remaining difference may stay only if it is ≤15% and has a written row in the spec's drift log. Ask the user for approval before logging anything that is not a technical artefact.

- [ ] **Step 6: Commit**

```bash
cd web && /home/sico/Code/Lemely/.venv/bin/pre-commit run --files src/portals/student/home/HomeHero.tsx src/portals/student/home/StudentHome.tsx scripts/home-drift.mjs tests/unit/studentHomeMarkup.test.ts
git commit -S -m "feat(web): student home hero from design A" -- web/src/portals/student/home/HomeHero.tsx web/src/portals/student/home/StudentHome.tsx web/scripts/home-drift.mjs web/tests/unit/studentHomeMarkup.test.ts
```

---


---

## Task 12: Garden

**Files:**
- Create: `web/src/portals/student/home/garden.ts` (pure Garden rules: stem heights, leaves, readouts, pots, fill line)
- Create: `web/src/portals/student/home/Garden.tsx`
- Create: `web/scripts/home-drift/overview.d.mts` (types for the `.mjs` so `web/e2e` type-checks)
- Create: `web/e2e/student-home.spec.ts` (Garden keyboard test; later tasks append)
- Create: `web/tests/unit/studentHomeGarden.test.ts`
- Modify: `web/tests/unit/studentHomeMarkup.test.ts` (created by Task 10; append a `describe("Garden")`)
- Modify: `web/src/index.css` (append the `home-*` keyframes below the last `@keyframes` block)
- Modify: `web/scripts/home-drift/overview.mjs` (export `READY_STATES`, `GARDEN_PICK`)
- Modify: `web/scripts/home-drift.mjs` (register the `garden` part)

**Interfaces:**
- Consumes:
  - Task 8: `HomeView`, `SubjectView`, `DataState`, `toHomeView(o, xp, upload, now)`, `API_FIXTURES`, `API_NOW`, `DataStateId`; `format.ts` `dayMonth`, `longDay`, `indefinite`; `model.ts` `GRADE_ORDER`.
  - Task 9: `OVERVIEW_STATES`, `overviewScenes({ part, states, interactions })` (interaction objects are `{ id, state, overrides?, preview, app }`), `mockStudentHome(page, state, overrides?)`, `APP_PATH`, `PARTS.garden` (`preview: '[data-when-state="ready"] .a-mo'`, `app: '[data-home="garden"]'`).
  - Task 10: `Vh`, `Icon` (`name: "arrow"`), `GradeChip` (`kind: "bud"`), `useMotionOn()`. Must be SSR-safe: `false` when `window` is undefined. Also the token map and the `@container/home` root on `#sh-root`.
- Produces:
  - `export function Garden(props: { view: HomeView; variant?: "ghost" }): JSX.Element`. The root is a `<section data-home="garden">`. `variant="ghost"` is the new-student Garden (Task 17 renders it inside the `new` block).
  - From `garden.ts`:
    ```ts
    export const MANY_PAPER_STATES: ReadonlySet<DataState>   // populated, result-in, marking, no-plan, no-exams, streak-zero
    export function isSparse(state: DataState): boolean       // state.startsWith("sparse")
    export function stemPct(pct: number): string              // "76.7%"
    export function leafStops(papers: number, compact: boolean): number[]
    export function gradeUp(previous: string | null, grade: string): boolean
    export interface Readout { pre: string; bold: string; post: string; ctx: string; lead: string | null }
    export function manyReadout(s: SubjectView): Readout
    export function manyLabel(s: SubjectView): string
    export function soloReadout(s: SubjectView): Readout
    export function sparseReadout(view: HomeView): Readout
    export type PotKind = "germ" | "seed" | "grown"
    export interface Pot { s: SubjectView; kind: PotKind; lead: boolean; dry: boolean; val: string; up: boolean; label: string }
    export function sparsePots(view: HomeView): Pot[]
    export interface Pip { title: string; done: string; on: boolean }
    export interface Fill { pips: Pip[]; on: number; doneText: string; next: string }
    export function gardenFill(view: HomeView): Fill
    export function joinOr(words: string[]): string          // ["a"] "a"; ["a","b"] "a or b"; ["a","b","c"] "a, b or c"
    ```
  - `NextStepCard` (Task 13) imports `gradeUp` and `isSparse`.

### Rules derived from the design (each one checked against every value in the markup)

**Stem height (`--now`) and first-paper line (`--was`).** The many-papers picker (`student-home-a.html` populated block, `page-a.txt` lines 229–242) uses `--now = (pct − 30) / 60 × 100%`, to one decimal:
76→76.7 ✓, 59→48.3 ✓, 48→30.0 ✓; `--was` 49→31.7 ✓, 44→23.3 ✓, 41→18.3 ✓. The value is clamped to 0–100. The stem is `block-size: calc(var(--now) * 0.8)` of the pot area (`variant-a.css:1522`). The dashed line sits at `calc(var(--was) * 0.8 * 1.08 + 20px)` (`:1523`).

The solo and sparse pots do **not** follow any formula. They are hand-placed: 65→52 (solo), 46→40 (sparse1), 58→62 and 47→34 (sparse2), 60→64 and 49→44 (sparse3), and `--was` 46→40, 45→40. 46→40 next to 47→34 is not monotonic, so no rule reproduces them. The product uses the picker formula everywhere, because a stem is "score now" (`variant-a.css:1494`). Expect differing pixels in the solo/sparse pots (a 3px stem, its leaves and the flower). Log them as described in Step 7.

**Leaves.** Picker: `n = min(papers, 6)` leaves at `round(i × 100 / (n + 1))%`, i = 1..n. 14 or 6 papers → 14, 29, 43, 57, 71, 86 ✓; 2 papers → 33, 67 ✓. Compact (solo and sparse) pots use a fixed table, `n = min(papers, 3)`: 1 → [45], 2 → [30, 62], 3 → [22, 48, 74]. That matches sparse2 Add Maths (1 paper, 45) ✓, sparse2/3 Maths (3 papers) ✓ and sparse3 Add Maths (2 papers) ✓. The design contradicts its own rule ("one leaf per paper", `variant-a.css:1495`) in two places: solo and sparse1 Maths have 1 paper but show 2 leaves (30, 62). The product follows the rule, which gives 1 leaf at 45%. Log it.

**A dashed first-paper line** is drawn only when `papers >= 2` (the markup has none on any 1-paper plant).

**Fill line pips** (`page-a.txt` 301–320), computed from the view:

| Pip (title) | Done name | On when |
|---|---|---|
| First result | first result | `view.facts.latestResult !== null` |
| Practice targets | practice targets | `view.weakTopics.length > 0` |
| Exam dates | exam dates | `view.subjects.length > 0 && view.subjects.every((s) => s.nextExamOn !== null)` |
| 3-day streak | streak | `(view.xp?.streak ?? 0) >= 3` |
| Study plan | study plan | `view.facts.upcomingSessions.length > 0` |
| All {n} subjects planted | all subjects planted | `view.subjects.every((s) => s.papers > 0)` |

Check against the markup. sparse0: exam dates → 1 ✓. sparse1: result, targets, exams → 3 ✓. sparse2: result, targets, streak 3, plan (0625 has no date, so no exam pip) → 4 ✓. sparse3: result, targets, exams → 3 ✓.

Next line, first match wins: a live upload → "Next: your first result, marking now." ✓ sparse0. State `sparse3` → "Next: one short set restarts your streak." ✓. Any unplanted subjects → `Next: plant ${joinOr(shortNames)}`, plus " and add its exam date" when exactly one subject is unplanted and it has no exam date, then "." ✓ sparse1 "plant Add Maths or Physics." ✓ sparse2 "plant Physics and add its exam date.". Fallbacks the design never shows (no fixture reaches them): "Next: add your exam dates.", "Next: build a study plan.", "Next: keep your streak going.".

**Readouts.**
- Picker: `${short} is up <b>${d} points</b>` / ctx `${first}% → ${pct}% · ${papers} papers`. A negative d reads "is down"; d = 0 reads `${short} is <b>holding steady</b>`. Singular "1 point" / "1 paper". The last three are not in the design.
- Solo: `${short} has <b>sprouted</b>` / `Grade ${g} · first paper`.
- sparse0: `Your first seed is <b>germinating</b>` / `${label} is being marked · ${n} subjects planted`. When the label is null: `Your paper is being marked · …`.
- sparse1: `${short} has <b>sprouted</b>` / `Grade ${g} · your first result`. The lead is the latest result's subject.
- sparse2: `${short} is <b>up a grade</b>` / `${prev} → ${g} · ${growing} of ${n} subjects growing`. The lead is the first subject with `gradeUp`. With no improved subject: `<b>${growing} of ${n}</b> subjects growing` / `${totalPapers} papers corrected` (not in the design).
- sparse3: `Your progress <b>is safe</b>` / `Last watered ${dayMonth(max lastPaperOn)} · ${totalPapers} papers kept`.

### Token and container map used below

Classes use the app `@theme` utilities where a design token has a 1:1 app token. Four design semantics have no `@theme` utility, so the classes use the v4 var shorthand. Task 10's token map must define these on `#sh-root`, with light and dark values: `--text-secondary`, `--track`, `--a-card-edge` (`0 0 0 1.5px <border-subtle>`, `none` in dark), `--a-ease-expo` (`cubic-bezier(0.16, 1, 0.3, 1)`), and `--night`. If Task 10's map names a row differently, use Task 10's name. The design var in the left column is the contract.

| Design (`tokens.css`) | Class |
|---|---|
| `--surface-card` | `bg-surface-container-lowest` |
| `--surface-row` | `bg-surface-container-low`, `border-surface-container-low` |
| `--text-body` | `text-on-surface` |
| `--text-muted` | `text-on-surface-variant`, `border-on-surface-variant` |
| `--text-secondary` | `text-(--text-secondary)` |
| `--md-primary` / `--md-primary-container` / `--md-on-primary-container` | `primary` / `primary-container` / `on-primary-container` |
| `--md-success` / `--sh-success-text` | `bg-success` / `text-success-text` |
| `--md-secondary` | `bg-secondary` |
| `--sh-grade-a/-b/-c/-astar` | `grade-a` / `grade-b` / `grade-c` / `grade-a-star` |
| `--track` | `bg-(--track)` |
| `--a-card-edge` | `shadow-(--a-card-edge)` |
| `--fs-title` 21 · `--fs-body` 16 · `--fs-body-sm` 14 · `--fs-label` 11 | `text-[21px]` · `text-base` · `text-sm` · `text-2xs` |
| `--space-N` | Tailwind spacing `N` (4px unit) |
| `--radius-card/-chip/-pill` | `rounded-card` / `rounded-chip` / `rounded-pill` |
| `--font-ui` / `--font-mono` | `font-sans` / `font-mono` |
| `@container home (min-width: 900px)` / `(max-width: 560px)` | `@min-[900px]/home:` / `@max-[560px]/home:` |

The design's `.a-vh` (`variant-a.css:22`: absolute, 1×1, `clip-path: inset(50%)`, nowrap) is the `Vh` primitive. Elements that must be a specific tag (the radio input, the legend) use `sr-only`, which is visually identical.

### Selector → class mapping (`variant-a.css`)

| Selector (line) | Declarations | Classes |
|---|---|---|
| `.a-mo` (1496) | `position: relative; padding: space-5 space-6; border-radius: radius-card; background: surface-card; box-shadow: a-card-edge; color: text-body` | `relative rounded-card bg-surface-container-lowest px-6 py-5 text-on-surface shadow-(--a-card-edge)` |
| `.a-mo` ≥900 (1508) | `display: grid; grid-template-columns: minmax(200px,280px) minmax(0,1fr); column-gap: space-8; align-content: center` | `@min-[900px]/home:grid @min-[900px]/home:grid-cols-[minmax(200px,280px)_minmax(0,1fr)] @min-[900px]/home:gap-x-8 @min-[900px]/home:content-center` |
| `.a-mo > .mo-h` / `.mo-read` / `.mo-garden` ≥900 (1509–1511) | col 1 row 1 end / col 1 row 2 start / col 2 rows 1–2, gap space-4 | `@min-[900px]/home:col-start-1 @min-[900px]/home:row-start-1 @min-[900px]/home:self-end` / `…col-start-1 …row-start-2 …self-start` / `…col-start-2 …row-[1/span_2] …gap-4` |
| sparse `.a-mo` ≥900 (2234–2237) | `grid-template-columns: minmax(0,1fr); align-content: space-between; row-gap: space-2`; children auto; `.mo-read` mb space-2; `.mo-garden` gap space-2 | `@min-[900px]/home:grid @min-[900px]/home:grid-cols-[minmax(0,1fr)] @min-[900px]/home:content-between @min-[900px]/home:gap-y-2`; read `@min-[900px]/home:mb-2` |
| `.a-mo .mo-h` (1497, 1848) | `margin 0; font: 800 fs-title/1.2 font-ui; letter-spacing: ls-headline-ui (-0.02em); color text-body` | `m-0 font-sans text-[21px] font-extrabold leading-[1.2] tracking-[-0.02em] text-on-surface` |
| `.a-mo .mo-read` (1566) | `display flex; flex-direction column; align-items flex-start; gap space-1; margin space-2 0 space-3` | `mt-2 mb-3 flex flex-col items-start gap-1` |
| `.mo-sent` (1567, 1850) | `600 fs-title/1.2 font-ui; -0.02em; text-body; word-spacing 0.04em`; `b` 800, md-primary (1568) | `font-sans text-[21px] font-semibold leading-[1.2] tracking-[-0.02em] text-on-surface [word-spacing:0.04em] [&_b]:font-extrabold [&_b]:text-primary` |
| `.mo-ctx` (1569) | `600 fs-label/1.3 font-mono; 0.02em; text-secondary; tabular-nums` | `font-mono text-2xs font-semibold leading-[1.3] tracking-[0.02em] tabular-nums text-(--text-secondary)` |
| `.a-mo .mo-garden` (1516) | `display grid; repeat(3,1fr); gap space-2; margin 0; padding 0; border 0; min-inline-size 0` | `m-0 grid min-w-0 grid-cols-3 gap-2 border-0 p-0` |
| `.mo-plant` (1517, 1570) | `grid; justify-items center; gap 0; padding space-2 0 space-1; radius-chip; cursor pointer; transition background fast` | `grid justify-items-center gap-0 rounded-chip pt-2 pb-1 transition-colors duration-150` |
| `.mo-plant:hover` (1518) / `.mo-r:checked + .mo-plant` (1520) | `surface-row` / `md-primary-container` | `hover:bg-surface-container-low` / `bg-primary-container hover:bg-primary-container` (checked is later in the file, so it wins over hover) |
| `.mo-r:focus-visible + .mo-plant` (1519) | `outline: 2px solid md-primary; offset 2px` | `[input:focus-visible+&]:outline-2 [input:focus-visible+&]:outline-offset-2 [input:focus-visible+&]:outline-primary` (an adjacent-sibling variant: `peer-*` compiles to `~` and would outline every later plant) |
| `.mo-pot-area` (1521, 1512, 2238) | `relative; flex column; items center; justify end; 64×108`; ≥900 80×136; sparse ≥900 block 112 | `relative flex h-[108px] w-16 flex-col items-center justify-end @min-[900px]/home:w-20` + `@min-[900px]/home:h-[136px]` or (sparse) `@min-[900px]/home:h-[112px]` |
| `.mo-stem` (1522, 1549) | `relative; flex none; 3px wide; block-size calc(var(--now)*0.8); radius-pill; md-success; transform-origin 50% 100%` | `relative w-[3px] flex-none origin-bottom rounded-pill h-[calc(var(--now)*0.8)]` + tone class |
| `.mo-r:not(:checked) + .mo-plant :is(.mo-stem,.mo-leaf)` (1533) | `color-mix(md-success 50%, surface-card)` | tone `faded`: `bg-[color-mix(in_oklch,var(--color-success)_50%,var(--color-surface-container-lowest))]` |
| streak-zero stems/leaves (1790–1794) | `color-mix(md-success 35%, text-muted)`; leaf `rotate 22deg`; stem `rotate 5deg`; flower `opacity .5; saturate(.3)`; bud `saturate(.5)` | tone `rest`: `bg-[color-mix(in_oklch,var(--color-success)_35%,var(--color-on-surface-variant))]`; leaf `rotate-[22deg]`; stem `rotate-5`; `before:opacity-50 before:saturate-30`; bud `saturate-50` |
| `.mo-sp.is-dry` (2127–2130) | `color-mix(md-success 55%, text-muted)`; leaf `rotate 14deg`; flower `opacity .6; saturate(.4)`; bud `saturate(.6)` | tone `dry`: `bg-[color-mix(in_oklch,var(--color-success)_55%,var(--color-on-surface-variant))]`; leaf `rotate-[14deg]`; `before:opacity-60 before:saturate-40`; bud `saturate-60` |
| `.mo-stem::before` flower (1542–1546) | `inset-block-end calc(100%+5px); left 50%; translate -50% 0; 10×10; radius-pill; --pc: color-mix(petal 30%, surface-card); background --pc; box-shadow` five petals; petal = grade-a for A, grade-b for B, otherwise grade-c (A* included); unchecked `scale .7` | `before:absolute before:bottom-[calc(100%+5px)] before:left-1/2 before:size-[10px] before:-translate-x-1/2 before:rounded-pill before:bg-(--pc) before:shadow-[0_-12px_0_2px_var(--pc),11.4px_-3.7px_0_2px_var(--pc),7px_9.7px_0_2px_var(--pc),-7px_9.7px_0_2px_var(--pc),-11.4px_-3.7px_0_2px_var(--pc)] before:content-['']`; unchecked `before:scale-70`; `--pc` set inline |
| `.mo-was` (1523) | `absolute; inset-inline 8px; inset-block-end calc(var(--was)*0.8*1.08+20px); border-top 1.5px dashed text-muted` | `absolute inset-x-2 bottom-[calc(var(--was)*0.8*1.08+20px)] border-t-[1.5px] border-dashed border-on-surface-variant` |
| `.mo-leaf` (1524–1526) | `absolute; bottom var(--at); 14×8; md-success; radius pill 0`; odd `inset-inline-start 3px`; even `inset-inline-end 3px; scale -1 1` | `absolute bottom-(--at) h-2 w-[14px] rounded-[999px_0]` + tone; odd `start-[3px]`; even `end-[3px] -scale-x-100` |
| `.mo-bud` (1527–1531, 1872) | `absolute; bottom 100%; left 50%; translate -50% 2px; 24×24 grid center; radius-pill; grade bg; 700 fs-label/1 mono`; A white text, B night, C white | `<GradeChip kind="bud">` (Task 10 implements these declarations) + positioning `absolute bottom-full left-1/2 -translate-x-1/2 translate-y-[2px]` |
| `.mo-pot` (1531) | `34×20; flex none; radius 4px 4px chip chip; md-secondary` | `h-5 w-[34px] flex-none rounded-[4px_4px_12px_12px] bg-secondary` |
| `.mo-name` (1532, 1571) | `margin-top space-1; 600 fs-body-sm/1.2 font-ui` | `mt-1 font-sans text-sm font-semibold leading-[1.2]` |
| `.mo-val` (1572–1573) | `600 fs-label/1.3 mono; text-muted; tabular`; checked md-primary | `font-mono text-2xs font-semibold leading-[1.3] tabular-nums text-on-surface-variant`; checked `text-primary` |
| `.mo-rest` (1783–1786) | streak-zero: `block; margin space-3 0 0; padding-top space-3; border-top 1px surface-row`; `.mo-sent` 700 fs-body/1.3 text-body; `.mo-ctx` block mt space-1; grid col 1/-1 | `col-span-full mt-3 border-t border-surface-container-low pt-3`; sent `font-sans text-base font-bold leading-[1.3] text-on-surface`; ctx + `mt-1 block` |
| `.mo-garden-solo` (1802, 1806) | `grid; minmax(0,1fr); justify-items center; align-content center; gap space-3; margin 0`; ≥900 col 2 rows 1–2 | `m-0 grid grid-cols-[minmax(0,1fr)] content-center justify-items-center gap-3 @min-[900px]/home:col-start-2 @min-[900px]/home:row-[1/span_2]` |
| `.mo-plant.is-solo` (1803) | `cursor default; padding-inline space-6; md-primary-container` | `cursor-default bg-primary-container px-6` |
| `.mo-seed` (1804) | `margin 0; max 24ch; center; 600 fs-label/1.4 mono; text-secondary` | `m-0 max-w-[24ch] text-center font-mono text-2xs font-semibold leading-[1.4] text-(--text-secondary)` |
| `.a-mo-ghost` (1810, 1816) | `margin-block space-5` | `my-5` |
| `.mo-garden-ghost` (1812, 2009, 1820) | `grid; repeat(3,1fr); gap space-4; margin space-3 0 0`; ≥900 col 2 rows 1–2, margin 0 | `mt-3 grid grid-cols-3 gap-4 @min-[900px]/home:col-start-2 @min-[900px]/home:row-[1/span_2] @min-[900px]/home:m-0` |
| ghost `.mo-plant` (1813, 2010) | `grid; justify-items center; padding space-2 0 space-1; opacity .7` | `grid justify-items-center pt-2 pb-1 opacity-70` |
| ghost pot area / stem / pot / name (2012, 1814, 2013, 1817, 2011, 1818) | block 96; first stem 56px, 2px dashed text-muted, no flower; pot 48×28, transparent, 2px dashed text-muted; name text-secondary | `h-24`; `h-14 w-0 flex-none border-s-2 border-dashed border-on-surface-variant`; `h-7 w-12 flex-none rounded-[4px_4px_12px_12px] border-2 border-dashed border-on-surface-variant`; name + `text-(--text-secondary)` |
| `.mo-garden-sp` (2076) | `align-items: end` | `items-end` |
| `.mo-sp` (2077–2082) | `cursor default; no underline; color inherit; hover transparent`; `.is-lead` primary-container; `a.mo-sp` pointer, hover surface-row, focus-visible outline 2px primary offset 2px | `cursor-default text-inherit no-underline`; lead `bg-primary-container`; link `group cursor-pointer hover:bg-surface-container-low focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary` |
| `.mo-sp .mo-val` (2083–2086) | `min-block-size 18px`; lead md-primary; `.mo-val-up` success-text | `min-h-[18px]`; `text-primary`; `text-success-text` |
| `.mo-plant-it` (2087–2089) | `inline-flex; center; gap 2px; 700 fs-body-sm/1.3 font-ui; md-primary`; icon 14px, hover translate 3px | `inline-flex items-center gap-0.5 font-sans text-sm font-bold leading-[1.3] text-primary`; icon `size-[14px] transition-[translate] duration-200 group-hover:translate-x-[3px]` |
| `.mo-sp-seed` (2092–2096) / `.is-germ` (2105) | `relative; z 1; flex none; 12×8; margin-bottom -3px; radius 50% 50% 45% 45% / 60% 60% 40% 40%; color-mix(success 45%, text-muted)` / 14×9 | `relative z-[1] -mb-[3px] h-2 w-3 flex-none rounded-[50%_50%_45%_45%/60%_60%_40%_40%] bg-[color-mix(in_oklch,var(--color-success)_45%,var(--color-on-surface-variant))]` / `h-[9px] w-[14px]` |
| `.mo-sp-guide` (2097–2102) | `flex none; 0 wide; 40% tall; margin-bottom space-1; 2px dashed color-mix(text-muted 50%, transparent)`; hover md-primary | `mb-1 h-[40%] w-0 flex-none border-s-2 border-dashed border-[color-mix(in_oklch,var(--color-on-surface-variant)_50%,transparent)] transition-colors duration-150 group-hover:border-primary` |
| `.mo-sp-shoot` + `::after` (2106–2113) | `absolute; bottom 60%; left 50%; 2×18; translate -50% 0; origin 50% 100%; radius-pill; success`; after `absolute; top 1px; left 1px; 10×6; radius pill 0; success` | `absolute bottom-[60%] left-1/2 h-[18px] w-[2px] -translate-x-1/2 origin-bottom rounded-pill bg-success after:absolute after:top-px after:left-px after:h-[6px] after:w-[10px] after:rounded-[999px_0] after:bg-success after:content-['']` |
| `.is-germ .mo-pot-area::before` (2114–2118) | `absolute; bottom 6px; left 50%; translate -50%; 56px square; circle; radial-gradient(closest-side, color-mix(success 24%, transparent), transparent)` | `before:absolute before:bottom-[6px] before:left-1/2 before:aspect-square before:w-14 before:-translate-x-1/2 before:rounded-full before:bg-[radial-gradient(closest-side,color-mix(in_oklch,var(--color-success)_24%,transparent),transparent)] before:content-['']` |
| `.mo-fill` (2133–2138, 2192) | `col 1/-1; grid; auto minmax(96px,168px); areas "t p" "n n"; justify space-between; align center; gap space-1 space-4; margin space-4 0 0; padding-top space-3; border-top 1px surface-row`; ≤560 one column, areas t/p/n, row-gap space-2 | `col-span-full mt-4 grid grid-cols-[auto_minmax(96px,168px)] items-center justify-between gap-x-4 gap-y-1 border-t border-surface-container-low pt-3 [grid-template-areas:'t_p'_'n_n'] @max-[560px]/home:grid-cols-[minmax(0,1fr)] @max-[560px]/home:gap-y-2 @max-[560px]/home:[grid-template-areas:'t'_'p'_'n']` |
| `.mo-fill-t` / `b` (2139–2140) | `area t; 600 fs-body-sm/1.3 font-ui; text-secondary`; b text-body 700 (mono from `.a-mono`) | `m-0 font-sans text-sm font-semibold leading-[1.3] text-(--text-secondary) [grid-area:t]`; b `font-mono font-bold tabular-nums text-on-surface` |
| `.mo-pips` / `i` / `.is-on` (2141–2143, 2193) | `area p; flex; gap space-1`; i `flex 1; 6px; radius-pill; track`; on success; ≤560 max 168px | `flex gap-1 [grid-area:p] @max-[560px]/home:max-w-[168px]`; `h-[6px] flex-1 rounded-pill bg-(--track)` / `bg-success` |
| `.mo-fill-next` (2144) | `area n; 700 fs-body-sm/1.3 font-ui; text-body` | `m-0 font-sans text-sm font-bold leading-[1.3] text-on-surface [grid-area:n]` |

Motion (`variant-a.css:1534–1562`, `2119–2124`) runs only when `useMotionOn()` is true. Drift scenes run with reduced motion, so these classes never affect a scene: the stem grows from `--was` (`home-gr-up 1.1s expo .2s both`) and sways three times (`home-gr-sway 1.4s ease-in-out 1.3s 3`); the flower opens (`home-gr-open .5s expo 1.2s both`); the picked plant's dashed line flashes (`home-gr-mark 1.1s ease-out .2s both`) and its bud pops (`home-mo-pop dur-slow expo`); the germinating shoot and glow pulse (`home-sp-shoot`/`home-sp-glow 1.8s infinite alternate`). Picking a plant replays its growth through a React `key` change on the stem, which stands in for the design's A/B keyframe swap.

- [ ] **Step 1: Write the failing pure-rule tests**

`web/tests/unit/studentHomeGarden.test.ts`:

```ts
import { describe, expect, it } from "vitest"
import { API_FIXTURES, API_NOW, type DataStateId } from "../../dev-previews/student-home/api-fixtures"
import { toHomeView } from "@/portals/student/home/facts"
import {
  gardenFill, gradeUp, joinOr, leafStops, manyLabel, manyReadout, sparsePots, sparseReadout, stemPct,
} from "@/portals/student/home/garden"

const view = (s: DataStateId) => {
  const f = API_FIXTURES[s]
  return toHomeView(f.overview, f.xp, f.upload, API_NOW)
}

describe("stem and leaves", () => {
  it("stem height follows (pct - 30) / 60, as the picker markup", () => {
    expect([76, 59, 48, 49, 44, 41].map(stemPct)).toEqual(["76.7%", "48.3%", "30.0%", "31.7%", "23.3%", "18.3%"])
    expect(stemPct(10)).toBe("0.0%")
    expect(stemPct(100)).toBe("100.0%")
  })
  it("picker leaves: one per paper up to six, evenly spaced", () => {
    expect(leafStops(14, false)).toEqual([14, 29, 43, 57, 71, 86])
    expect(leafStops(6, false)).toEqual([14, 29, 43, 57, 71, 86])
    expect(leafStops(2, false)).toEqual([33, 67])
  })
  it("compact leaves: the sparse table, up to three", () => {
    expect(leafStops(1, true)).toEqual([45])
    expect(leafStops(2, true)).toEqual([30, 62])
    expect(leafStops(3, true)).toEqual([22, 48, 74])
    expect(leafStops(9, true)).toEqual([22, 48, 74])
  })
})

describe("readouts", () => {
  it("picker readout and hidden label", () => {
    const maths = view("populated").subjects.find((s) => s.code === "0580")!
    expect(manyReadout(maths)).toMatchObject({ pre: "Maths is up ", bold: "27 points", ctx: "49% → 76% · 14 papers" })
    expect(manyLabel(maths)).toBe("Maths 0580: 49% to 76%, up 27, 14 papers.")
  })
  it.each([
    ["sparse0", "Your first seed is ", "germinating", "0580/42 is being marked · 3 subjects planted"],
    ["sparse1", "Maths has ", "sprouted", "Grade C · your first result"],
    ["sparse2", "Maths is ", "up a grade", "C → B · 2 of 3 subjects growing"],
    ["sparse3", "Your progress ", "is safe", "Last watered 27 Oct · 5 papers kept"],
  ] as const)("%s", (s, pre, bold, ctx) => {
    expect(sparseReadout(view(s))).toMatchObject({ pre, bold, ctx })
  })
  it("gradeUp", () => {
    expect(gradeUp("C", "B")).toBe(true)
    expect(gradeUp("B", "B")).toBe(false)
    expect(gradeUp(null, "A")).toBe(false)
  })
  it("joinOr", () => {
    expect(joinOr(["Physics"])).toBe("Physics")
    expect(joinOr(["Add Maths", "Physics"])).toBe("Add Maths or Physics")
    expect(joinOr(["A", "B", "C"])).toBe("A, B or C")
  })
})

describe("sparse pots", () => {
  it("sparse0: germinating lead, then seeds", () => {
    const pots = sparsePots(view("sparse0"))
    expect(pots.map((p) => [p.s.code, p.kind, p.lead, p.val])).toEqual([
      ["0580", "germ", true, "Marking now"], ["0606", "seed", false, "Plant it"], ["0625", "seed", false, "Plant it"],
    ])
    expect(pots[1].label).toBe("Add Maths 0606: planted, no paper yet. Upload an Add Maths paper to plant it.")
    expect(pots[2].label).toBe("Physics 0625: planted, no paper yet. Upload a Physics paper to plant it.")
  })
  it("sparse2: improved lead shows the step up", () => {
    const [maths, add] = sparsePots(view("sparse2"))
    expect([maths.lead, maths.val, maths.up]).toEqual([true, "C → B", true])
    expect(maths.label).toBe("Maths 0580: grade B, up from C, 3 papers.")
    expect([add.lead, add.val, add.label]).toEqual([false, "Grade C", "Add Maths 0606: grade C on your first paper."])
  })
  it("sparse3: grown pots are dry and carry the last paper date", () => {
    const [maths] = sparsePots(view("sparse3"))
    expect([maths.dry, maths.lead, maths.val]).toEqual([true, false, "Grade B"])
    expect(maths.label).toBe("Maths 0580: grade B, up from C, 3 papers. Last paper 27 October.")
  })
})

describe("fill line", () => {
  it.each([
    ["sparse0", 1, "exam dates", "Next: your first result, marking now."],
    ["sparse1", 3, "first result, practice targets, exam dates", "Next: plant Add Maths or Physics."],
    ["sparse2", 4, "first result, practice targets, streak, study plan", "Next: plant Physics and add its exam date."],
    ["sparse3", 3, "first result, practice targets, exam dates", "Next: one short set restarts your streak."],
  ] as const)("%s", (s, on, done, next) => {
    const fill = gardenFill(view(s))
    expect(fill.on).toBe(on)
    expect(fill.doneText).toBe(done)
    expect(fill.next).toBe(next)
    expect(fill.pips.map((p) => p.title)).toEqual([
      "First result", "Practice targets", "Exam dates", "3-day streak", "Study plan", "All 3 subjects planted",
    ])
  })
})
```

Run: `cd web && npx vitest run tests/unit/studentHomeGarden.test.ts`
Expected: FAIL (`Cannot find module '@/portals/student/home/garden'`).

- [ ] **Step 2: Implement `garden.ts`**

```ts
/*
 * Garden rules (design A, variant-a.css:1494 "Stem = score now, dashed line = first
 * paper, one leaf per paper (max 6), bud = current grade"). Pure: the component and
 * the tests share them. Plan Task 12 lists which design values each rule reproduces.
 */
import type { DataState, HomeView, SubjectView } from "./facts"
import { dayMonth, indefinite, longDay } from "./format"
import { GRADE_ORDER } from "./model"

export const MANY_PAPER_STATES: ReadonlySet<DataState> = new Set<DataState>([
  "populated", "result-in", "marking", "no-plan", "no-exams", "streak-zero",
])

export const isSparse = (state: DataState): boolean => state.startsWith("sparse")

export function stemPct(pct: number): string {
  const v = Math.min(100, Math.max(0, ((pct - 30) / 60) * 100))
  return `${v.toFixed(1)}%`
}

const COMPACT_LEAVES: Record<number, number[]> = { 1: [45], 2: [30, 62], 3: [22, 48, 74] }

export function leafStops(papers: number, compact: boolean): number[] {
  if (compact) return COMPACT_LEAVES[Math.min(papers, 3)] ?? []
  const n = Math.min(papers, 6)
  return Array.from({ length: n }, (_, i) => Math.round(((i + 1) * 100) / (n + 1)))
}

const rank = (g: string): number => (GRADE_ORDER as readonly string[]).indexOf(g)

export function gradeUp(previous: string | null, grade: string): boolean {
  return previous !== null && rank(previous) >= 0 && rank(grade) > rank(previous)
}

export function joinOr(words: string[]): string {
  if (words.length <= 1) return words[0] ?? ""
  return `${words.slice(0, -1).join(", ")} or ${words[words.length - 1]}`
}

const plural = (n: number, one: string, many: string): string => `${n} ${n === 1 ? one : many}`

export interface Readout { pre: string; bold: string; post: string; ctx: string; lead: string | null }

export function manyReadout(s: SubjectView): Readout {
  const pct = s.pct ?? 0
  const first = s.firstPct ?? pct
  const d = pct - first
  const ctx = `${first}% → ${pct}% · ${plural(s.papers, "paper", "papers")}`
  if (d === 0) return { pre: `${s.shortName} is `, bold: "holding steady", post: "", ctx, lead: s.code }
  return {
    pre: `${s.shortName} is ${d > 0 ? "up" : "down"} `,
    bold: plural(Math.abs(d), "point", "points"),
    post: "",
    ctx,
    lead: s.code,
  }
}

export function manyLabel(s: SubjectView): string {
  const pct = s.pct ?? 0
  const first = s.firstPct ?? pct
  const d = pct - first
  return `${s.shortName} ${s.code}: ${first}% to ${pct}%, ${d >= 0 ? "up" : "down"} ${Math.abs(d)}, ${plural(s.papers, "paper", "papers")}.`
}

export function soloReadout(s: SubjectView): Readout {
  return { pre: `${s.shortName} has `, bold: "sprouted", post: "", ctx: `Grade ${s.grade} · first paper`, lead: s.code }
}

export function sparseReadout(view: HomeView): Readout {
  const n = view.subjects.length
  const growing = view.subjects.filter((s) => s.papers > 0)
  if (view.state === "sparse0") {
    const label = view.upload?.paperLabel
    return {
      pre: "Your first seed is ", bold: "germinating", post: "",
      ctx: `${label ?? "Your paper"} is being marked · ${plural(n, "subject", "subjects")} planted`,
      lead: view.upload?.subjectCode ?? null,
    }
  }
  if (view.state === "sparse1") {
    const code = view.facts.latestResult?.subjectCode
    const s = growing.find((x) => x.code === code) ?? growing[0]
    return { pre: `${s.shortName} has `, bold: "sprouted", post: "", ctx: `Grade ${s.grade} · your first result`, lead: s.code }
  }
  if (view.state === "sparse3") {
    const last = growing.map((s) => s.lastPaperOn).filter((d): d is string => d !== null).sort().at(-1)
    return {
      pre: "Your progress ", bold: "is safe", post: "",
      ctx: `${last ? `Last watered ${dayMonth(last)} · ` : ""}${view.totalPapers} papers kept`,
      lead: null,
    }
  }
  const up = growing.find((s) => gradeUp(s.previousGrade, s.grade))
  if (up) {
    return {
      pre: `${up.shortName} is `, bold: "up a grade", post: "",
      ctx: `${up.previousGrade} → ${up.grade} · ${growing.length} of ${n} subjects growing`,
      lead: up.code,
    }
  }
  return { pre: "", bold: `${growing.length} of ${n}`, post: " subjects growing", ctx: `${view.totalPapers} papers corrected`, lead: null }
}

export type PotKind = "germ" | "seed" | "grown"
export interface Pot { s: SubjectView; kind: PotKind; lead: boolean; dry: boolean; val: string; up: boolean; label: string }

export function sparsePots(view: HomeView): Pot[] {
  const lead = sparseReadout(view).lead
  return view.subjects.map((s) => {
    const name = `${s.shortName} ${s.code}`
    if (s.papers === 0 && view.totalPapers === 0 && view.upload?.subjectCode === s.code) {
      return {
        s, kind: "germ", lead: true, dry: false, val: "Marking now", up: false,
        label: `${name}: your first paper is being marked. Its plant appears when the grade lands.`,
      }
    }
    if (s.papers === 0) {
      return {
        s, kind: "seed", lead: false, dry: false, val: "Plant it", up: false,
        label: `${name}: planted, no paper yet. Upload ${indefinite(s.shortName)} ${s.shortName} paper to plant it.`,
      }
    }
    const isLead = s.code === lead
    const improved = gradeUp(s.previousGrade, s.grade)
    const showUp = view.state === "sparse2" && isLead && improved
    const dry = view.state === "sparse3"
    const label =
      s.papers === 1
        ? `${name}: grade ${s.grade} on your first paper.`
        : `${name}: grade ${s.grade}${improved ? `, up from ${s.previousGrade}` : ""}, ${s.papers} papers.` +
          (dry && s.lastPaperOn ? ` Last paper ${longDay(s.lastPaperOn)}.` : "")
    return {
      s, kind: "grown", lead: isLead, dry,
      val: showUp ? `${s.previousGrade} → ${s.grade}` : `Grade ${s.grade}`,
      up: showUp, label,
    }
  })
}

export interface Pip { title: string; done: string; on: boolean }
export interface Fill { pips: Pip[]; on: number; doneText: string; next: string }

export function gardenFill(view: HomeView): Fill {
  const subjects = view.subjects
  const exams = subjects.length > 0 && subjects.every((s) => s.nextExamOn !== null)
  const plan = view.facts.upcomingSessions.length > 0
  const pips: Pip[] = [
    { title: "First result", done: "first result", on: view.facts.latestResult !== null },
    { title: "Practice targets", done: "practice targets", on: view.weakTopics.length > 0 },
    { title: "Exam dates", done: "exam dates", on: exams },
    { title: "3-day streak", done: "streak", on: (view.xp?.streak ?? 0) >= 3 },
    { title: "Study plan", done: "study plan", on: plan },
    { title: `All ${subjects.length} subjects planted`, done: "all subjects planted", on: subjects.every((s) => s.papers > 0) },
  ]
  const unplanted = subjects.filter((s) => s.papers === 0)
  let next: string
  if (view.upload) next = "Next: your first result, marking now."
  else if (view.state === "sparse3") next = "Next: one short set restarts your streak."
  else if (unplanted.length > 0) {
    const tail = unplanted.length === 1 && unplanted[0].nextExamOn === null ? " and add its exam date" : ""
    next = `Next: plant ${joinOr(unplanted.map((s) => s.shortName))}${tail}.`
  } else if (!exams) next = "Next: add your exam dates."
  else if (!plan) next = "Next: build a study plan."
  else next = "Next: keep your streak going."
  return {
    pips,
    on: pips.filter((p) => p.on).length,
    doneText: pips.filter((p) => p.on).map((p) => p.done).join(", "),
    next,
  }
}
```

- [ ] **Step 3: Run the rule tests**

Run: `cd web && npx vitest run tests/unit/studentHomeGarden.test.ts`
Expected: PASS (all). If a fixture-backed case fails, compare the failing value with `page-a.txt` and fix the rule, never the expected string.

- [ ] **Step 4: Write the failing markup tests**

Append to `web/tests/unit/studentHomeMarkup.test.ts`. Reuse the `view` and `html` helpers Task 10 defined there. If Task 10 named them differently, add these two at the top of the new block:

```ts
import { Garden } from "@/portals/student/home/Garden"
// const view = (s: DataStateId) => { const f = API_FIXTURES[s]; return toHomeView(f.overview, f.xp, f.upload, API_NOW) }
// const html = (el: ReactElement) => renderToStaticMarkup(createElement(MemoryRouter, null, el))

describe("Garden", () => {
  it("populated: one h2, a radio group with a legend, hidden plant labels", () => {
    const out = html(createElement(Garden, { view: view("populated") }))
    expect(out.match(/<h2/g)).toHaveLength(1)
    expect(out).toContain(">Your Garden</h2>")
    expect(out).toContain("<fieldset")
    expect(out).toContain("Pick a subject to see how far it has grown</legend>")
    expect(out.match(/type="radio"/g)).toHaveLength(3)
    expect(out.match(/checked=""/g)).toHaveLength(1)
    expect(out).toContain("Maths 0580: 49% to 76%, up 27, 14 papers.")
    expect(out).toContain('data-plant="0625"')
    expect(out).not.toContain("growing on your page")
  })
  it("one-paper: a single sprout in a labelled group", () => {
    const out = html(createElement(Garden, { view: view("one-paper") }))
    expect(out).toContain('role="group" aria-label="Your garden"')
    expect(out).toContain("Maths 0580: grade B on your first paper.")
    expect(out).toContain("Mark more papers to see how it grows.")
    expect(out).not.toContain('type="radio"')
  })
  it.each([
    ["sparse0", "1 of 6", "Next: your first result, marking now."],
    ["sparse1", "3 of 6", "Next: plant Add Maths or Physics."],
    ["sparse2", "4 of 6", "Next: plant Physics and add its exam date."],
    ["sparse3", "3 of 6", "Next: one short set restarts your streak."],
  ] as const)("%s: a list of pots and the fill line", (s, count, next) => {
    const out = html(createElement(Garden, { view: view(s) }))
    expect(out).toContain('role="list" aria-label="Your garden, one plant per subject"')
    expect(out.match(/role="listitem"/g)).toHaveLength(3)
    expect(out).toContain(`${count}</b> growing on your page`)
    expect(out).toContain(next)
    expect(out).toContain('href="/student/correct"')
  })
  it("streak-zero: the garden rests", () => {
    const out = html(createElement(Garden, { view: view("streak-zero") }))
    expect(out).toContain("Your garden is resting.")
    expect(out).toContain("Streak paused. Earn XP today and it grows again.")
  })
  it("ghost: dashed preview with no data", () => {
    const out = html(createElement(Garden, { view: view("new"), variant: "ghost" }))
    expect(out).toContain("Every subject grows its own plant.")
    expect(out).toContain("Plant your first by getting a paper marked.")
    expect(out).toContain("Your first subject")
    expect(out).not.toContain("%")
  })
})
```

Run: `cd web && npx vitest run tests/unit/studentHomeMarkup.test.ts -t Garden`
Expected: FAIL (`Garden` not found).

- [ ] **Step 5: Implement `Garden.tsx`**

```tsx
/*
 * Your Garden (design A `.a-mo`, variant-a.css:1494–1573, 1782–1821, 2074–2144,
 * 2228–2238). One plant per subject: stem = score now, dashed line = first
 * paper, a leaf per paper, bud = grade. Four layouts: the many-papers picker
 * (radios + legend), the one-paper sprout, the sparse pots with the fill line,
 * and the new-student ghost. Rules live in garden.ts.
 */
import { Fragment, useId, useState, type CSSProperties, type ReactNode } from "react"
import { Link } from "react-router-dom"
import { cn } from "@/lib/utils"
import type { HomeView, SubjectView } from "./facts"
import {
  gardenFill, leafStops, manyLabel, manyReadout, soloReadout, sparsePots, sparseReadout, stemPct, isSparse,
  type Pot, type Readout,
} from "./garden"
import { GradeChip, Icon, Vh, useMotionOn } from "./primitives"

type Vars = CSSProperties & Record<`--${string}`, string>
type Tone = "full" | "faded" | "rest" | "dry"

const W = "@min-[900px]/home:"
const SECTION = "relative rounded-card bg-surface-container-lowest px-6 py-5 text-on-surface shadow-(--a-card-edge)"
const SECTION_SPLIT = `${W}grid ${W}grid-cols-[minmax(200px,280px)_minmax(0,1fr)] ${W}gap-x-8 ${W}content-center`
const SECTION_STACK = `${W}grid ${W}grid-cols-[minmax(0,1fr)] ${W}content-between ${W}gap-y-2`
const H2 = "m-0 font-sans text-[21px] font-extrabold leading-[1.2] tracking-[-0.02em] text-on-surface"
const H2_SPLIT = `${W}col-start-1 ${W}row-start-1 ${W}self-end`
const READ = "mt-2 mb-3 flex flex-col items-start gap-1"
const READ_SPLIT = `${W}col-start-1 ${W}row-start-2 ${W}self-start`
const SENT = "font-sans text-[21px] font-semibold leading-[1.2] tracking-[-0.02em] text-on-surface [word-spacing:0.04em] [&_b]:font-extrabold [&_b]:text-primary"
const CTX = "font-mono text-2xs font-semibold leading-[1.3] tracking-[0.02em] tabular-nums text-(--text-secondary)"
const BED = "m-0 grid min-w-0 grid-cols-3 gap-2 border-0 p-0"
const BED_SPLIT = `${W}col-start-2 ${W}row-[1/span_2] ${W}gap-4`
const PLANT = "grid justify-items-center gap-0 rounded-chip pt-2 pb-1 transition-colors duration-150"
const NAME = "mt-1 font-sans text-sm font-semibold leading-[1.2]"
const VAL = "font-mono text-2xs font-semibold leading-[1.3] tabular-nums text-on-surface-variant"
const POT = "h-5 w-[34px] flex-none rounded-[4px_4px_12px_12px] bg-secondary"
const SEED = "relative z-[1] -mb-[3px] h-2 w-3 flex-none rounded-[50%_50%_45%_45%/60%_60%_40%_40%] bg-[color-mix(in_oklch,var(--color-success)_45%,var(--color-on-surface-variant))]"

const TONE: Record<Tone, string> = {
  full: "bg-success",
  faded: "bg-[color-mix(in_oklch,var(--color-success)_50%,var(--color-surface-container-lowest))]",
  rest: "bg-[color-mix(in_oklch,var(--color-success)_35%,var(--color-on-surface-variant))]",
  dry: "bg-[color-mix(in_oklch,var(--color-success)_55%,var(--color-on-surface-variant))]",
}
const PETAL: Record<string, string> = { A: "var(--color-grade-a)", B: "var(--color-grade-b)" }
const FLOWER =
  "before:absolute before:bottom-[calc(100%+5px)] before:left-1/2 before:size-[10px] before:-translate-x-1/2 before:rounded-pill before:bg-(--pc) before:shadow-[0_-12px_0_2px_var(--pc),11.4px_-3.7px_0_2px_var(--pc),7px_9.7px_0_2px_var(--pc),-7px_9.7px_0_2px_var(--pc),-11.4px_-3.7px_0_2px_var(--pc)] before:content-['']"

function potArea(stack: boolean): string {
  return cn(
    "relative flex h-[108px] w-16 flex-col items-center justify-end",
    `${W}w-20`,
    stack ? `${W}h-[112px]` : `${W}h-[136px]`,
  )
}

function ReadLine({ r, split, hidden }: { r: Readout; split: boolean; hidden?: boolean }) {
  return (
    <p className={cn(READ, split ? READ_SPLIT : `${W}mb-2`)} aria-hidden={hidden ? "true" : undefined}>
      <span className={SENT}>
        {r.pre}
        <b>{r.bold}</b>
        {r.post}
      </span>
      <span className={CTX}>{r.ctx}</span>
    </p>
  )
}

/** Stem, leaves, bud and the first-paper line, inside the pot area. */
function Growth(props: {
  s: SubjectView
  compact: boolean
  tone: Tone
  stack: boolean
  picked: boolean
  replay?: string
}) {
  const { s, compact, tone, stack, picked, replay } = props
  const motion = useMotionOn()
  const was = s.papers >= 2 && s.firstPct !== null
  const vars: Vars = {
    "--now": stemPct(s.pct ?? 0),
    "--was": was ? stemPct(s.firstPct ?? 0) : "0%",
    "--pc": `color-mix(in oklch, ${PETAL[s.grade] ?? "var(--color-grade-c)"} 30%, var(--color-surface-container-lowest))`,
  }
  const leafTilt = tone === "rest" ? "rotate-[22deg]" : tone === "dry" ? "rotate-[14deg]" : ""
  return (
    <span className={potArea(stack)} aria-hidden="true" style={vars}>
      {was && (
        <span
          className={cn(
            "absolute inset-x-2 bottom-[calc(var(--was)*0.8*1.08+20px)] border-t-[1.5px] border-dashed border-on-surface-variant",
            motion && picked && "animate-[home-gr-mark_1.1s_ease-out_.2s_both]",
          )}
        />
      )}
      <span
        key={replay}
        className={cn(
          "relative w-[3px] flex-none origin-bottom rounded-pill h-[calc(var(--now)*0.8)]",
          TONE[tone],
          FLOWER,
          tone === "faded" && "before:scale-70",
          tone === "rest" && "rotate-5 before:opacity-50 before:saturate-30",
          tone === "dry" && "before:opacity-60 before:saturate-40",
          motion &&
            "animate-[home-gr-up_1.1s_var(--a-ease-expo)_.2s_both,home-gr-sway_1.4s_ease-in-out_1.3s_3] before:animate-[home-gr-open_.5s_var(--a-ease-expo)_1.2s_both]",
        )}
      >
        {leafStops(s.papers, compact).map((at, i) => (
          <span
            key={at}
            className={cn(
              "absolute bottom-(--at) h-2 w-[14px] rounded-[999px_0]",
              TONE[tone],
              i % 2 === 0 ? "start-[3px]" : "end-[3px] -scale-x-100",
              leafTilt,
            )}
            style={{ "--at": `${at}%` } as Vars}
          />
        ))}
        <GradeChip
          grade={s.grade}
          kind="bud"
          className={cn(
            "absolute bottom-full left-1/2 -translate-x-1/2 translate-y-[2px]",
            tone === "rest" && "saturate-50",
            tone === "dry" && "saturate-60",
            motion && picked && "animate-[home-mo-pop_var(--dur-slow)_var(--a-ease-expo)]",
          )}
        />
      </span>
      <span className={POT} />
    </span>
  )
}

function Shell(props: { stack: boolean; children: ReactNode; labelledBy?: string; ghost?: boolean }) {
  return (
    <section
      data-home="garden"
      aria-label={props.labelledBy ? undefined : "Your momentum"}
      aria-labelledby={props.labelledBy}
      className={cn(SECTION, props.stack ? SECTION_STACK : SECTION_SPLIT, props.ghost && "my-5")}
    >
      {props.children}
    </section>
  )
}

function PickerGarden({ view }: { view: HomeView }) {
  const planted = view.subjects.filter((s) => s.papers > 0)
  const [picked, setPicked] = useState(planted[0]?.code ?? "")
  const name = useId()
  const resting = view.state === "streak-zero"
  const current = planted.find((s) => s.code === picked) ?? planted[0]
  const cols = planted.length === 3 ? undefined : { gridTemplateColumns: `repeat(${planted.length}, 1fr)` }
  return (
    <Shell stack={false}>
      <h2 className={cn(H2, H2_SPLIT)}>Your Garden</h2>
      {current && <ReadLine r={manyReadout(current)} split hidden />}
      <fieldset className={cn(BED, BED_SPLIT)} style={cols}>
        <legend className="sr-only">Pick a subject to see how far it has grown</legend>
        {planted.map((s) => {
          const on = s.code === current?.code
          const id = `${name}-${s.code}`
          return (
            <Fragment key={s.code}>
              <input
                className="sr-only"
                type="radio"
                name={name}
                id={id}
                value={s.code}
                checked={on}
                onChange={() => setPicked(s.code)}
              />
              <label
                htmlFor={id}
                data-plant={s.code}
                className={cn(
                  PLANT,
                  "cursor-pointer hover:bg-surface-container-low",
                  "[input:focus-visible+&]:outline-2 [input:focus-visible+&]:outline-offset-2 [input:focus-visible+&]:outline-primary",
                  on && "bg-primary-container hover:bg-primary-container",
                )}
              >
                <Growth
                  s={s}
                  compact={false}
                  tone={resting ? "rest" : on ? "full" : "faded"}
                  stack={false}
                  picked={on}
                  replay={on ? `on-${picked}` : "off"}
                />
                <span className={NAME}>{s.shortName}</span>
                <span className={cn(VAL, on && "text-primary")}>{s.pct}%</span>
                <Vh>{manyLabel(s)}</Vh>
              </label>
            </Fragment>
          )
        })}
      </fieldset>
      {resting && (
        <p className="col-span-full mt-3 border-t border-surface-container-low pt-3">
          <span className="font-sans text-base font-bold leading-[1.3] text-on-surface">Your garden is resting.</span>{" "}
          <span className={cn(CTX, "mt-1 block")}>Streak paused. Earn XP today and it grows again.</span>
        </p>
      )}
    </Shell>
  )
}

function SoloGarden({ view }: { view: HomeView }) {
  const s = view.subjects.find((x) => x.papers > 0) ?? view.subjects[0]
  return (
    <Shell stack={false}>
      <h2 className={cn(H2, H2_SPLIT)}>Your Garden</h2>
      <ReadLine r={soloReadout(s)} split />
      <div
        role="group"
        aria-label="Your garden"
        className={`m-0 grid grid-cols-[minmax(0,1fr)] content-center justify-items-center gap-3 ${W}col-start-2 ${W}row-[1/span_2]`}
      >
        <div className={cn(PLANT, "cursor-default bg-primary-container px-6")}>
          <Growth s={s} compact tone="full" stack={false} picked={false} />
          <span className={NAME}>{s.shortName}</span>
          <span className={VAL}>{s.code}</span>
          <Vh>{`${s.shortName} ${s.code}: grade ${s.grade} on your first paper.`}</Vh>
        </div>
        <p className="m-0 max-w-[24ch] text-center font-mono text-2xs font-semibold leading-[1.4] text-(--text-secondary)">
          Mark more papers to see how it grows.
        </p>
      </div>
    </Shell>
  )
}

function SparsePot({ pot }: { pot: Pot }) {
  const motion = useMotionOn()
  const base = cn(PLANT, "cursor-default text-inherit no-underline", pot.lead && "bg-primary-container")
  const val = (
    <span
      aria-hidden="true"
      className={cn(VAL, "min-h-[18px]", pot.lead && "text-primary", pot.up && "text-success-text")}
    >
      {pot.val}
    </span>
  )
  if (pot.kind === "seed") {
    return (
      <Link
        to="/student/correct"
        role="listitem"
        className={cn(
          base,
          "group cursor-pointer hover:bg-surface-container-low focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary",
        )}
      >
        <span className={potArea(true)} aria-hidden="true">
          <span className="mb-1 h-[40%] w-0 flex-none border-s-2 border-dashed border-[color-mix(in_oklch,var(--color-on-surface-variant)_50%,transparent)] transition-colors duration-150 group-hover:border-primary" />
          <span className={SEED} />
          <span className={POT} />
        </span>
        <span className={NAME} aria-hidden="true">{pot.s.shortName}</span>
        <span
          aria-hidden="true"
          className="inline-flex min-h-[18px] items-center gap-0.5 font-sans text-sm font-bold leading-[1.3] text-primary"
        >
          Plant it <Icon name="arrow" className="size-[14px] transition-[translate] duration-200 group-hover:translate-x-[3px]" />
        </span>
        <Vh>{pot.label}</Vh>
      </Link>
    )
  }
  if (pot.kind === "germ") {
    return (
      <div role="listitem" className={base}>
        <span
          aria-hidden="true"
          className={cn(
            potArea(true),
            "before:absolute before:bottom-[6px] before:left-1/2 before:aspect-square before:w-14 before:-translate-x-1/2 before:rounded-full before:bg-[radial-gradient(closest-side,color-mix(in_oklch,var(--color-success)_24%,transparent),transparent)] before:content-['']",
            motion && "before:animate-[home-sp-glow_1.8s_ease-in-out_infinite_alternate]",
          )}
        >
          <span className={cn(SEED, "h-[9px] w-[14px]")}>
            <span
              className={cn(
                "absolute bottom-[60%] left-1/2 h-[18px] w-[2px] -translate-x-1/2 origin-bottom rounded-pill bg-success after:absolute after:top-px after:left-px after:h-[6px] after:w-[10px] after:rounded-[999px_0] after:bg-success after:content-['']",
                motion && "animate-[home-sp-shoot_1.8s_var(--a-ease-expo)_infinite_alternate]",
              )}
            />
          </span>
          <span className={POT} />
        </span>
        <span className={NAME} aria-hidden="true">{pot.s.shortName}</span>
        {val}
        <Vh>{pot.label}</Vh>
      </div>
    )
  }
  return (
    <div role="listitem" className={base}>
      <Growth s={pot.s} compact tone={pot.dry ? "dry" : "full"} stack picked={false} />
      <span className={NAME} aria-hidden="true">{pot.s.shortName}</span>
      {val}
      <Vh>{pot.label}</Vh>
    </div>
  )
}

function SparseGarden({ view }: { view: HomeView }) {
  const fill = gardenFill(view)
  return (
    <Shell stack>
      <h2 className={H2}>Your Garden</h2>
      <ReadLine r={sparseReadout(view)} split={false} />
      <div role="list" aria-label="Your garden, one plant per subject" className={cn(BED, "items-end")}>
        {sparsePots(view).map((pot) => (
          <SparsePot key={pot.s.code} pot={pot} />
        ))}
      </div>
      <div className="col-span-full mt-4 grid grid-cols-[auto_minmax(96px,168px)] items-center justify-between gap-x-4 gap-y-1 border-t border-surface-container-low pt-3 [grid-template-areas:'t_p'_'n_n'] @max-[560px]/home:grid-cols-[minmax(0,1fr)] @max-[560px]/home:gap-y-2 @max-[560px]/home:[grid-template-areas:'t'_'p'_'n']">
        <p className="m-0 font-sans text-sm font-semibold leading-[1.3] text-(--text-secondary) [grid-area:t]">
          <b className="font-mono font-bold tabular-nums text-on-surface">{fill.on} of 6</b> growing on your page
        </p>
        <span aria-hidden="true" className="flex gap-1 [grid-area:p] @max-[560px]/home:max-w-[168px]">
          {fill.pips.map((p) => (
            <i key={p.title} title={p.title} className={cn("h-[6px] flex-1 rounded-pill", p.on ? "bg-success" : "bg-(--track)")} />
          ))}
        </span>
        <p className="m-0 font-sans text-sm font-bold leading-[1.3] text-on-surface [grid-area:n]">
          {fill.doneText && <Vh>{`Done: ${fill.doneText}. `}</Vh>}
          {fill.next}
        </p>
      </div>
    </Shell>
  )
}

const GHOST_PLANTS = ["Your first subject", "Next", "Next"] as const

function GhostGarden() {
  const hid = useId()
  return (
    <Shell stack={false} labelledBy={hid} ghost>
      <h2 id={hid} className={cn(H2, H2_SPLIT)}>
        Your Garden
      </h2>
      <p className={cn(READ, READ_SPLIT)}>
        <span className={SENT}>Every subject grows its own plant.</span>
        <span className={CTX}>Plant your first by getting a paper marked.</span>
      </p>
      <div aria-hidden="true" className={`mt-3 grid grid-cols-3 gap-4 ${W}col-start-2 ${W}row-[1/span_2] ${W}m-0`}>
        {GHOST_PLANTS.map((label, i) => (
          <div key={i} className="grid justify-items-center pt-2 pb-1 opacity-70">
            <span className={`relative flex h-24 w-16 flex-col items-center justify-end ${W}w-20`}>
              {i === 0 && <span className="h-14 w-0 flex-none rounded-none border-s-2 border-dashed border-on-surface-variant" />}
              <span className="h-7 w-12 flex-none rounded-[4px_4px_12px_12px] border-2 border-dashed border-on-surface-variant" />
            </span>
            <span className={cn(NAME, "text-(--text-secondary)")}>{label}</span>
          </div>
        ))}
      </div>
    </Shell>
  )
}

export function Garden({ view, variant }: { view: HomeView; variant?: "ghost" }) {
  if (variant === "ghost") return <GhostGarden />
  if (view.state === "one-paper") return <SoloGarden view={view} />
  if (isSparse(view.state)) return <SparseGarden view={view} />
  return <PickerGarden view={view} />
}
```

Notes for the implementer:
- The ghost's first stem is fixed at 56px (`variant-a.css:2013`). Its inline `--now: 14%` in the markup is overridden there, so it is not reproduced.
- The picker readout is `aria-hidden="true"` as in the markup (`page-a.txt:225`). The hidden plant labels carry the same facts.
- `<i>` pips: `flex-1` makes them flex items, so `display` needs no change.

- [ ] **Step 6: Keyframes**

Append to `web/src/index.css` after the last `@keyframes` block. Skip `home-rise`/`home-rise-in` if Task 10 already added them, and keep its definitions.

```css
/* Student home Garden and next-step motion (variant-a.css:569–571, 1536–1562, 2123–2124). */
@keyframes home-gr-up { from { block-size: calc(var(--was) * 0.8) } }
@keyframes home-gr-sway { 25% { rotate: 2deg } 75% { rotate: -2deg } }
@keyframes home-gr-open { from { transform: scale(0); opacity: 0 } }
@keyframes home-gr-mark { 0%, 60% { border-color: var(--color-primary) } }
@keyframes home-mo-pop { 40% { scale: 1.25 } }
@keyframes home-sp-shoot { from { transform: scaleY(0.55) } }
@keyframes home-sp-glow { from { opacity: 0.35 } }
@keyframes home-rise { from { transform: translateY(8px); opacity: 0 } }
@keyframes home-rise-in { from { transform: translateY(8px) scale(0.96); opacity: 0 } }
```

- [ ] **Step 7: Run the markup tests**

Run: `cd web && npx vitest run tests/unit/studentHomeGarden.test.ts tests/unit/studentHomeMarkup.test.ts`
Expected: PASS.

- [ ] **Step 8: Keyboard test (Playwright)**

`web/scripts/home-drift/overview.d.mts`:

```ts
import type { Page } from "@playwright/test"

export declare const OVERVIEW_STATES: readonly string[]
export declare const READY_STATES: readonly string[]
export declare const APP_PATH: string
export declare function mockStudentHome(page: Page, state: string, overrides?: Record<string, unknown>): Promise<void>
```

`web/e2e/student-home.spec.ts`:

```ts
/*
 * Student home behaviour the node-environment unit tests cannot see (D3.20):
 * keyboard use of the Garden radios. API mocked from the design fixtures, so the
 * test needs no seeded marks; the session is the seed contract's first student.
 */
import { expect, test, type Page } from "@playwright/test"
import { APP_PATH, mockStudentHome } from "../scripts/home-drift/overview.mjs"
import { injectSession, readSeed, type SeedStudent } from "./seed"

async function openHome(page: Page, state: string, overrides?: Record<string, unknown>): Promise<void> {
  const who = Object.values(readSeed().students)[0] as SeedStudent
  await injectSession(page, { accessToken: who.accessToken, userId: who.userId, role: "student" })
  await mockStudentHome(page, state, overrides)
  await page.goto(APP_PATH)
  await page.locator(`#sh-root[data-state="${state}"]`).waitFor()
}

test.describe("Garden picker", () => {
  test("Tab reaches the radio group; arrow keys move the pick and the readout follows", async ({ page }) => {
    await openHome(page, "populated")
    const garden = page.locator('[data-home="garden"]')
    const radios = garden.getByRole("radio")
    await expect(radios).toHaveCount(3)
    await expect(garden.getByRole("group", { name: "Pick a subject to see how far it has grown" })).toBeVisible()
    await expect(radios.nth(0)).toBeChecked()

    for (let i = 0; i < 80; i += 1) {
      await page.keyboard.press("Tab")
      if (await radios.nth(0).evaluate((el) => el === document.activeElement)) break
    }
    await expect(radios.nth(0)).toBeFocused()

    const outline = await garden.locator('[data-plant="0580"]').evaluate((el) => {
      const s = getComputedStyle(el)
      return { style: s.outlineStyle, width: s.outlineWidth }
    })
    expect(outline).toEqual({ style: "solid", width: "2px" })

    await page.keyboard.press("ArrowRight")
    await expect(radios.nth(1)).toBeChecked()
    await expect(radios.nth(1)).toBeFocused()
    await expect(garden.locator('p[aria-hidden="true"]')).toContainText("Add Maths is up 15 points")
    await expect(garden.locator('p[aria-hidden="true"]')).toContainText("44% → 59% · 6 papers")

    await page.keyboard.press("ArrowRight")
    await expect(radios.nth(2)).toBeChecked()
    await expect(garden.locator('p[aria-hidden="true"]')).toContainText("Physics is up 7 points")

    await page.keyboard.press("ArrowLeft")
    await expect(radios.nth(1)).toBeChecked()
  })
})
```

Run (app dev server and backend as the e2e config boots them): `cd web && npx playwright test e2e/student-home.spec.ts --project=chromium`
Expected: `1 passed`. If `--project=chromium` is not a project name in `playwright.config.ts`, use the desktop project name it defines.

- [ ] **Step 9: Drift scenes**

In `web/scripts/home-drift/overview.mjs`, add:

```js
/** States whose ready page is on screen (error shows the banner over the last-known page). */
export const READY_STATES = OVERVIEW_STATES.filter((s) => s !== "new" && s !== "loading")

/** Spec §4 interaction pair: after a Garden pick (third plant). */
export const GARDEN_PICK = {
  id: "garden-pick",
  state: "populated",
  preview: async (page) => page.click('label[for="mo2-c"]'),
  app: async (page) => page.click('[data-home="garden"] [data-plant="0625"]'),
}
```

In `web/scripts/home-drift.mjs`, add next to the Overview registration from Task 9:

```js
import { GARDEN_PICK, READY_STATES, overviewScenes } from "./home-drift/overview.mjs"
// …in the scene list:
...overviewScenes({ part: "garden", states: READY_STATES, interactions: [GARDEN_PICK] }),
```

The new-student ghost is compared inside the `new` part (Task 17), because the preview's ghost sits in `[data-when-state="new"]` and `PARTS.garden.preview` targets the ready block.

Run: `cd web && node scripts/home-drift.mjs --only overview:garden`
Expected: `overview:garden PASS 130/130` (12 states × 5 widths × 2 themes + 10 interaction scenes).

Expected first-run failures, and what to do with each:
- Picker, solo and ghost scenes must reach **0 px**. Any difference there is drift: open the diff, find the row of the mapping table above that differs, and fix it.
- sparse1–3 and one-paper scenes will differ in the stems, leaves and flowers only, because the design hand-placed those heights and leaf counts (see "Rules"). Confirm each diff image shows nothing outside the plants. Then STOP and show the user one diff per state (light, 1440) with the rule: "stem = score now on the picker's scale; one leaf per paper". Ask for approval. When approved, add one drift-log row per state to the spec, for example: `| overview:garden:sparse1:* | stem 40%→26.7% and 1 leaf instead of 2 on the Maths pot | <measured max %> | Design hand-placed this plant; product follows the design's own rule "stem = score now, one leaf per paper" (variant-a.css:1494–1495) | yes, <date> |`. Then re-run. The script passes these scenes only because they have a justification and are under 15%. If the user rejects the rule, stop and report: no data rule reproduces the hand-placed values.

- [ ] **Step 10: Commit**

```bash
cd web && /home/sico/Code/Lemely/.venv/bin/pre-commit run --files src/portals/student/home/garden.ts src/portals/student/home/Garden.tsx src/index.css scripts/home-drift/overview.mjs scripts/home-drift/overview.d.mts scripts/home-drift.mjs e2e/student-home.spec.ts tests/unit/studentHomeGarden.test.ts tests/unit/studentHomeMarkup.test.ts ../docs/superpowers/specs/2026-11-06-student-home-overview-design.md
git commit -S -m "feat(web): student home Garden with picker, sprout, sparse pots and fill line" -- web/src/portals/student/home/garden.ts web/src/portals/student/home/Garden.tsx web/src/index.css web/scripts/home-drift/overview.mjs web/scripts/home-drift/overview.d.mts web/scripts/home-drift.mjs web/e2e/student-home.spec.ts web/tests/unit/studentHomeGarden.test.ts web/tests/unit/studentHomeMarkup.test.ts docs/superpowers/specs/2026-11-06-student-home-overview-design.md
```

---

## Task 13: NextStepCard

**Files:**
- Create: `web/src/portals/student/home/NextStepCard.tsx`
- Modify: `web/tests/unit/studentHomeMarkup.test.ts` (append `describe("NextStepCard")`)
- Modify: `web/scripts/home-drift/overview.mjs` (export `MARKING_STAGE_2`)
- Modify: `web/scripts/home-drift.mjs` (register the `next` part)

**Interfaces:**
- Consumes:
  - Task 8: `HomeView` (`action`, `state`, `upload`, `latestScore`, `subjects`, `totalPapers`, `facts.now`), `API_FIXTURES`; `format.ts` `dayMonth`, `indefinite`; `model.ts` `localISODate`, `NextAction`.
  - Task 10: `Mono`, `Code`, `Vh`, `Icon`, `ButtonLink` (merges `className` through `cn`, so the overrides below win), `useMotionOn`, `useInView`.
  - Task 12: `gradeUp`, `isSparse`, `joinOr`; the `home-rise`/`home-rise-in` keyframes.
  - Task 9: `overviewScenes`, `API_FIXTURES` in `overview.mjs`.
- Produces: `export function NextStepCard(props: { view: HomeView }): JSX.Element`. The root is `<section data-home="next" data-anim aria-labelledby=…>`. Task 17 places it in the next-step row. The row sets the card's `margin-block-start: 0` (`variant-a.css:1503`), so the card sets no outer margin.

### Copy rules (one layout per `view.action.kind`, `page-a.txt` 325–405)

| Kind | Meta line | Title | Facts / score | Body | Button |
|---|---|---|---|---|---|
| `result`, first paper (`totalPapers === 1`) | `Your first result · marked today` (recorded today), else `Your first result · marked <Mono>{dayMonth}</Mono>`; code chip | `paperLabel` (`.a-act-paper`) | `<Vh>Score </Vh>` marks, `/max`, grade tile `aria-label="Grade X"`, `Your starting point` | `Every mark explained, question by question.` | `See your marks` → `action.to` |
| `result`, otherwise | `Marked <Mono>{dayMonth(local date of recordedAt)}</Mono>`; code chip | same | same, with `↑ up from {previousGrade}` only when `gradeUp(prev, grade)` | same | same |
| `marking` | `Marking now`; chip = `upload.subjectCode` (omitted when null) | `totalPapers === 0` → `Your first paper is being marked`; else `${paperLabel} is being marked` (null label: `Your paper is being marked`) | 3-stage progress (below) | only when `totalPapers === 0`: `When <Mono>{label}</Mono> is marked you get your grade, every lost mark explained, and your first practice targets.` (null label: `When your paper is marked …`) | `See progress` → `action.to`, then the `.a-sp-also` link when `totalPapers === 0` and unplanted subjects other than the uploading one exist: `While you wait, upload ${indefinite(first)} ${joinOr(shortNames)} paper` |
| `session` | `Today's session`; chip | `session.title` | `<Mono>{minutes} min</Mono>` | `Next in your study plan for ${subject.name}.` | `Start session` |
| `first-paper` | (none) | `Let's get your first paper marked` | (none) | `Photograph or upload a paper you have already sat. Lemely finds the session and variant, pulls the official mark scheme, and marks it question by question.` | `Upload a paper` |
| `practice`, state `sparse3` | `Pick up where you left off`; chip | topic | `<Mono>{acc}% accuracy · 10 min</Mono>` | `One 10-minute set starts a new streak and waters your ${shortName} plant.` | `Start a 10-minute set` |
| `practice`, state `sparse1`/`sparse2` | `Practise next`; chip | topic | `<Mono>{acc}% accuracy</Mono>` | `Your weakest topic so far. One short set shows whether it is moving.` | `Practise ${topic.toLowerCase()}` |
| `practice`, otherwise | `Practise next`; chip | topic | `<Mono>{acc}% accuracy</Mono>` | `Your weakest topic right now. A short set shows whether it is improving.` | `Practise ${topic.toLowerCase()}` |
| `correct` | (none) | `Ready for another paper?` | (none) | `Each paper sharpens your predicted grade.` | `Upload a paper` |

Every button ends with `<Icon name="arrow" />`. The also-link ends with `<Icon name="chev" />`.

**Marking progress** (`variant-a.css:1360–1403`, `variant-a.js:257–266`). The stage is `view.upload?.progress?.stage ?? 1`.
- Live text (`role="status" aria-live="polite"`): stage 1 `Finding the paper and mark scheme`; stage 2 `Reading your answers`; stage 3 `Marking question <Mono>{done}</Mono> of <Mono>{total}</Mono>` (with total 0: `Marking questions`).
- Segment fill: segments before the stage are full and segments after it are empty. The current segment is 0.55 at stage 1 (the design's fixed value) and `done / total` at stages 2 and 3. With total 0 it falls back to the design's 0.5 at stage 2 and 0 at stage 3. Fixture check: stage 3, 7/12 → 0.5833 (design 0.583, which differs by less than 0.1px at any width). The stage-2 interaction uses 6/12 → 0.5 (design 0.5).
- Progressbar ARIA: stage 3 with total > 0: `aria-valuemin=0 aria-valuemax={total} aria-valuenow={done} aria-valuetext="Question {done} of {total}"`; otherwise `aria-valuemax=3 aria-valuenow={stage − 1} aria-valuetext={stage text}`. `aria-label="Marking progress"`.
- Steps (`aria-hidden`): `Paper and mark scheme`, `Your answers`, `Questions` + ` <Mono>{done}/{total}</Mono>` only at stage 3 with total > 0. Stage 2's counts are answers, not questions. The design shows "Questions 7/12" at every stage only because its markup is static. The preview setup of the stage-2 interaction rewrites that step to "Questions" so both sides show the same honest copy.
- No count-up: the design animates the score in (`aRise`, `variant-a.css:1324`) but does not count it.

### Selector → class mapping

| Selector (line) | Declarations | Classes |
|---|---|---|
| `.a-action-card` (328–332) | `padding 44px 56px 48px; radius-board; md-primary-container; on-primary-container` | `rounded-board bg-primary-container px-14 pt-11 pb-12 text-on-primary-container` |
| ≥761 (1426) | `padding space-6 space-7; radius-card` | `@min-[761px]/home:rounded-card @min-[761px]/home:px-7 @min-[761px]/home:py-6` |
| ≥900 (1489, 1505–1506) | `padding space-6`; in the row: `flex column; justify center` | `@min-[900px]/home:flex @min-[900px]/home:flex-col @min-[900px]/home:justify-center @min-[900px]/home:p-6` |
| ≤760 (1255) | `padding space-5` | `@max-[760px]/home:p-5` |
| `.a-act` (333, 1490) | `max-inline-size 760px`; ≥900 none | `max-w-[760px] @min-[900px]/home:max-w-none` |
| `.a-meta-line` + `.a-act .a-meta-line` (61–64, 334, 1427, 1257) | `flex; center; gap space-2; margin 0 0 space-4; 600 fs-body/1.2 font-ui; on-primary-container`; ≥761 mb space-3, fs-body-sm; ≤760 mb space-2, fs-body-sm | `m-0 mb-4 flex items-center gap-2 font-sans text-base font-semibold leading-[1.2] text-on-primary-container @min-[761px]/home:mb-3 @min-[761px]/home:text-sm @max-[760px]/home:mb-2 @max-[760px]/home:text-sm` |
| `.a-act .a-meta-line .a-code` (31–33, 65–66, 335) | `600 fs-label/1 mono; 0.04em; tabular`; `padding 4px 8px; radius-pill; surface-card; text-body` | `<Code className="rounded-pill bg-surface-container-lowest px-2 py-1 text-on-surface">` |
| `.a-act-title` (336–338, 1428, 1258) | `margin 0; 800 fs-display(64)/0.98 display; -0.045em; balance`; ≥761 32px/1.05, -0.04em; ≤760 32px | `m-0 font-display text-[64px] font-extrabold leading-[0.98] tracking-[-0.045em] text-balance @min-[761px]/home:text-[32px] @min-[761px]/home:leading-[1.05] @min-[761px]/home:tracking-[-0.04em] @max-[760px]/home:text-[32px]` |
| `.a-act-result .a-act-paper` (1308, 1331, 1433) | `fs-headline; line-height 1.1; -0.03em` at every width (its specificity beats the ≥761 title rule) | `m-0 font-display text-[32px] font-extrabold leading-[1.1] tracking-[-0.03em] text-balance` |
| `.a-act .a-facts` (72, 339, 1429, 1256) | `margin space-3 0 0; fs-body; on-primary-container`; ≥761 mt space-2, fs-body-sm; ≤760 margin space-1 0 space-4 | `m-0 mt-3 text-base text-on-primary-container @min-[761px]/home:mt-2 @min-[761px]/home:text-sm @max-[760px]/home:mt-1 @max-[760px]/home:mb-4` (value inside `<Mono>`) |
| `.a-act-body` (340, 1430, 1491, 1259) | `margin space-4 0 space-7; max 52ch; fs-body; lh 1.5; pretty`; ≥761 `space-2 0 space-5`, fs-body-sm; ≥900 mb space-5; ≤760 `display none` | `mt-4 mb-7 max-w-[52ch] text-base leading-[1.5] text-pretty @min-[761px]/home:mt-2 @min-[761px]/home:mb-5 @min-[761px]/home:text-sm @max-[760px]/home:hidden` |
| sparse `.a-sp-next` ≥900 (2242) | `margin-block-end space-3` | `+ @min-[900px]/home:mb-3` when `isSparse(state)` |
| `.a-btn` + `.a-btn-primary` + `.a-act-btn` (79–89, 341–346, 1431, 1260) | base in `ButtonLink`; `min-block 56px; padding 16px 28px; fs-body; radius-button`; hover `translateY(-2px); shadow-hover`; active `scale .97; 80ms`; ≥761 `min 44px; space-3 space-5; fs-body-sm`; ≤760 `width 100%; center` | `<ButtonLink variant="primary" className="min-h-14 rounded-button px-7 py-4 text-base transition-[background,transform,box-shadow] hover:-translate-y-0.5 hover:shadow-hover active:scale-97 active:duration-75 @min-[761px]/home:min-h-11 @min-[761px]/home:px-5 @min-[761px]/home:py-3 @min-[761px]/home:text-sm @max-[760px]/home:w-full @max-[760px]/home:justify-center">` |
| `.a-act-score` (1309, 1332) | `flex; wrap; center; gap space-2 space-4; margin space-4 0 0`; ≤760 margin space-3 0 space-4, gap space-2 space-3 | `m-0 mt-4 flex flex-wrap items-center gap-x-4 gap-y-2 @max-[760px]/home:mt-3 @max-[760px]/home:mb-4 @max-[760px]/home:gap-x-3` |
| `.a-act-marks` (1310, 1333) | `800 fs-display(64)/0.82 display; -0.05em; tabular lining` | `font-display text-[64px] font-extrabold leading-[0.82] tracking-[-0.05em] tabular-nums lining-nums` |
| `.a-act-of` (1311, 1434, 1334) | `margin-inline-start −space-3; align-self end; 800 fs-display-sm(40)/1 display; -0.04em; opacity .72`; ≥761 and ≤760 32px | `-ms-3 self-end font-display text-[40px] font-extrabold leading-none tracking-[-0.04em] opacity-72 @min-[761px]/home:text-[32px] @max-[760px]/home:text-[32px]` |
| `.a-act-grade` (1312–1318, 1435, 1335) | `inline-grid; center; 64×64; radius-inner; grade bg (A default, A*, B, C); white; 800 40px/1 display; -0.02em`; ≥761 and ≤760 48×48, radius-chip, 32px | `inline-grid size-16 place-items-center rounded-inner font-display text-[40px] font-extrabold leading-none tracking-[-0.02em] text-white @min-[761px]/home:size-12 @min-[761px]/home:rounded-chip @min-[761px]/home:text-[32px] @max-[760px]/home:size-12 @max-[760px]/home:rounded-chip @max-[760px]/home:text-[32px]` + `ACT_GRADE[grade]` |
| `.a-act-up` (1319–1323, 1436, 1336) | `inline-flex; center; gap 4px; padding 6px 12px; radius-pill; surface-card; success-text; 700 fs-body/1 ui`; icon 18px, stroke 2.2; ≥761 / ≤760 fs-body-sm | `inline-flex items-center gap-1 rounded-pill bg-surface-container-lowest px-3 py-1.5 font-sans text-base font-bold leading-none text-success-text @min-[761px]/home:text-sm @max-[760px]/home:text-sm`; icon `size-[18px] stroke-[2.2]` |
| `.a-act-first` (2147–2150) | `inline-flex; center; padding 6px 12px; radius-pill; surface-card; md-primary; 700 fs-body-sm/1 ui` | `inline-flex items-center rounded-pill bg-surface-container-lowest px-3 py-1.5 font-sans text-sm font-bold leading-none text-primary` |
| `.a-prog` (1362, 1432, 1400, 2241) | `max 640px; margin-block space-6 space-7`; ≥761 space-4 space-5; ≤760 space-2 space-3; sparse ≥900 space-3 | `mt-6 mb-7 max-w-[640px] @min-[761px]/home:mt-4 @min-[761px]/home:mb-5 @max-[760px]/home:mt-2 @max-[760px]/home:mb-3` + sparse `@min-[900px]/home:my-3` |
| `.a-prog-now` (1363–1364, 1401) | `margin 0 0 space-3; 700 fs-body/1.3 ui; on-primary-container`; mono 700; ≤760 mb space-1, fs-body-sm | `m-0 mb-3 font-sans text-base font-bold leading-[1.3] text-on-primary-container @max-[760px]/home:mb-1 @max-[760px]/home:text-sm`; `<Mono className="font-bold">` |
| `.a-prog-bar` (1369) | `grid; repeat(3, minmax(0,1fr)); gap 6px` | `grid grid-cols-3 gap-[6px]` |
| `.a-prog-seg` (1370–1373) | `8px; overflow hidden; radius-pill; color-mix(on-primary-container 16%, transparent)` | `block h-2 overflow-hidden rounded-pill bg-[color-mix(in_oklch,var(--color-on-primary-container)_16%,transparent)]` |
| `.a-prog-fill` (1374–1384) | `block; 100% tall; radius inherit; md-primary; scaleX(f); origin 0 50% (rtl 100% 50%); transition 500ms expo` | `block h-full origin-left rounded-[inherit] bg-primary transition-transform duration-500 ease-(--a-ease-expo) rtl:origin-right motion-reduce:transition-none`, `style={{ transform: \`scaleX(${f})\` }}` (`transform: none` when f = 1, as the design) |
| `.a-prog-steps` (1385–1397, 1402) | `grid; 3 cols; gap 6px; margin space-2 0 0; no list; 600 fs-body-sm/1.3 ui; on-primary-container`; li opacity .62, reached 1, current 700; mono fs-label; ≤760 hidden | `m-0 mt-2 grid list-none grid-cols-3 gap-[6px] p-0 font-sans text-sm font-semibold leading-[1.3] text-on-primary-container @max-[760px]/home:hidden`; li `opacity-62 transition-opacity duration-200` / `opacity-100` / `font-bold`; `<Mono className="text-2xs">` |
| `.a-sp-also` (2151–2156, 2243) | `inline-flex; center; gap 2px; min 44px; margin-top space-2; md-primary; 700 fs-body-sm/1.3 ui; no underline`; hover underline offset 3px; icon 16px; sparse ≥900 `max calc(100% − 176px); margin 0 0 0 space-3; vertical-align middle` | `mt-2 inline-flex min-h-11 items-center gap-0.5 font-sans text-sm font-bold leading-[1.3] text-primary no-underline hover:underline hover:underline-offset-3 @min-[900px]/home:m-0 @min-[900px]/home:ms-3 @min-[900px]/home:max-w-[calc(100%-176px)] @min-[900px]/home:align-middle`; icon `size-4 flex-none` |
| motion (532, 1324–1328) | `.a-act` rises 120ms; result marks rise 120ms, grade rise-in 260ms, up-chip rise 380ms; paused until the section is in view | when `useMotionOn() && inView`: `animate-[home-rise_var(--dur-slow)_var(--a-ease-expo)_120ms_both]`, `animate-[home-rise-in_var(--dur-slow)_var(--a-ease-expo)_260ms_both]`, `animate-[home-rise_var(--dur-slow)_var(--a-ease-expo)_380ms_both]` |

- [ ] **Step 1: Write the failing markup tests**

Append to `web/tests/unit/studentHomeMarkup.test.ts`:

```ts
import { NextStepCard } from "@/portals/student/home/NextStepCard"

describe("NextStepCard", () => {
  const card = (s: DataStateId) => html(createElement(NextStepCard, { view: view(s) }))

  it("every state has one hidden h2 naming the section", () => {
    for (const s of Object.keys(API_FIXTURES) as DataStateId[]) {
      const out = card(s)
      expect(out.match(/<h2/g)).toHaveLength(1)
      expect(out).toContain("Your next step</h2>")
    }
  })
  it("session", () => {
    const out = card("populated")
    expect(out).toContain("Quadratic inequalities</h3>")
    expect(out).toContain("25 min")
    expect(out).toContain("Next in your study plan for Additional Mathematics.")
    expect(out).toContain('href="/student/plan/0606/session/s1"')
    expect(out).toContain("Start session")
  })
  it("result, returning student", () => {
    const out = card("result-in")
    expect(out).toContain("0580/42 · m/j 2024</h3>")
    expect(out).toContain(">61</b>")
    expect(out).toContain("/80")
    expect(out).toContain('aria-label="Grade A"')
    expect(out).toContain("up from B")
    expect(out).toContain("4 Nov")
    expect(out).toContain('href="/student/result/p-0580-42"')
  })
  it("result, first paper", () => {
    const out = card("sparse1")
    expect(out).toContain("Your first result · marked today")
    expect(out).toContain(">37</b>")
    expect(out).toContain("Your starting point")
    expect(out).not.toContain("up from")
  })
  it("marking with a polite live region and a progressbar", () => {
    const out = card("marking")
    expect(out).toContain("0625/42 is being marked")
    expect(out).toContain('role="status" aria-live="polite"')
    expect(out).toContain("Marking question")
    expect(out).toContain('role="progressbar"')
    expect(out).toContain('aria-valuetext="Question 7 of 12"')
    expect(out).toContain('href="/student/correct"')
    expect(out).not.toContain("While you wait")
  })
  it("first paper marking: body and the while-you-wait link", () => {
    const out = card("sparse0")
    expect(out).toContain("Your first paper is being marked")
    expect(out).toContain("is marked you get your grade, every lost mark explained, and your first practice targets.")
    expect(out).toContain("While you wait, upload an Add Maths or Physics paper")
  })
  it.each([
    ["no-plan", "Practise next", "Waves", "54% accuracy", "Your weakest topic right now.", "Practise waves"],
    ["one-paper", "Practise next", "Vectors", "50% accuracy", "Your weakest topic right now.", "Practise vectors"],
    ["sparse2", "Practise next", "Logarithms", "48% accuracy", "Your weakest topic so far. One short set shows whether it is moving.", "Practise logarithms"],
    ["sparse3", "Pick up where you left off", "Logarithms", "51% accuracy · 10 min", "One 10-minute set starts a new streak and waters your Add Maths plant.", "Start a 10-minute set"],
  ] as const)("practice: %s", (s, meta, title, facts, body, btn) => {
    const out = card(s)
    for (const text of [meta, `${title}</h3>`, facts, body, btn]) expect(out).toContain(text)
  })
  it("correct", () => {
    const f = API_FIXTURES.populated
    const v = toHomeView({ ...f.overview, upcomingSessions: [], weakTopics: [] }, f.xp, null, API_NOW)
    const out = html(createElement(NextStepCard, { view: v }))
    expect(out).toContain("Ready for another paper?")
    expect(out).toContain("Each paper sharpens your predicted grade.")
  })
})
```

Run: `cd web && npx vitest run tests/unit/studentHomeMarkup.test.ts -t NextStepCard`
Expected: FAIL (`NextStepCard` not found).

- [ ] **Step 2: Implement `NextStepCard.tsx`**

```tsx
/*
 * Your next step (design A `.a-action-card`, variant-a.css:327–347, 1307–1337,
 * 1360–1403, 1426–1436, 1487–1492, 2146–2156, 2239–2243). One layout per
 * deriveNextAction kind; the page's only filled button. Marking progress reads
 * the persisted upload progress (plan Task 4) as a polite live region.
 */
import { useId, type ReactNode } from "react"
import { cn } from "@/lib/utils"
import type { HomeView, SubjectView } from "./facts"
import { dayMonth, indefinite } from "./format"
import { gradeUp, isSparse, joinOr } from "./garden"
import { localISODate, type NextAction } from "./model"
import { ButtonLink, Code, Icon, Mono, Vh, useInView, useMotionOn } from "./primitives"

const N = "@min-[761px]/home:"
const M = "@max-[760px]/home:"
const X = "@min-[900px]/home:"

const CARD = cn(
  "rounded-board bg-primary-container px-14 pt-11 pb-12 text-on-primary-container",
  `${N}rounded-card ${N}px-7 ${N}py-6`,
  `${X}flex ${X}flex-col ${X}justify-center ${X}p-6`,
  `${M}p-5`,
)
const ACT = `max-w-[760px] ${X}max-w-none`
const META = `m-0 mb-4 flex items-center gap-2 font-sans text-base font-semibold leading-[1.2] text-on-primary-container ${N}mb-3 ${N}text-sm ${M}mb-2 ${M}text-sm`
const CHIP = "rounded-pill bg-surface-container-lowest px-2 py-1 text-on-surface"
const TITLE = `m-0 font-display text-[64px] font-extrabold leading-[0.98] tracking-[-0.045em] text-balance ${N}text-[32px] ${N}leading-[1.05] ${N}tracking-[-0.04em] ${M}text-[32px]`
const PAPER = "m-0 font-display text-[32px] font-extrabold leading-[1.1] tracking-[-0.03em] text-balance"
const FACTS = `m-0 mt-3 text-base text-on-primary-container ${N}mt-2 ${N}text-sm ${M}mt-1 ${M}mb-4`
const BODY = `mt-4 mb-7 max-w-[52ch] text-base leading-[1.5] text-pretty ${N}mt-2 ${N}mb-5 ${N}text-sm ${M}hidden`
const BTN = `min-h-14 rounded-button px-7 py-4 text-base transition-[background,transform,box-shadow] hover:-translate-y-0.5 hover:shadow-hover active:scale-97 active:duration-75 ${N}min-h-11 ${N}px-5 ${N}py-3 ${N}text-sm ${M}w-full ${M}justify-center`
const ACT_GRADE: Record<string, string> = {
  "A*": "bg-grade-a-star", A: "bg-grade-a", B: "bg-grade-b", C: "bg-grade-c", D: "bg-grade-d", E: "bg-grade-e", U: "bg-grade-u",
}

function Meta({ children, code }: { children: ReactNode; code?: string | null }) {
  return (
    <p className={META}>
      <span>{children}</span>
      {code && <Code className={CHIP}>{code}</Code>}
    </p>
  )
}

function Go({ to, children }: { to: string; children: ReactNode }) {
  return (
    <ButtonLink to={to} variant="primary" className={BTN}>
      {children} <Icon name="arrow" />
    </ButtonLink>
  )
}

const subjectOf = (view: HomeView, code: string): SubjectView | undefined => view.subjects.find((s) => s.code === code)

function ResultAct({ view, action, rise }: { view: HomeView; action: Extract<NextAction, { kind: "result" }>; rise: boolean }) {
  const r = action.result
  const first = view.totalPapers === 1
  const day = localISODate(new Date(r.recordedAt))
  const today = day === localISODate(view.facts.now)
  const prev = subjectOf(view, r.subjectCode)?.previousGrade ?? null
  const score = view.latestScore
  return (
    <>
      <Meta code={r.subjectCode}>
        {first ? (
          today ? "Your first result · marked today" : <>Your first result · marked <Mono>{dayMonth(day)}</Mono></>
        ) : (
          <>Marked <Mono>{dayMonth(day)}</Mono></>
        )}
      </Meta>
      <h3 className={PAPER}>{r.paperLabel}</h3>
      <p className={`m-0 mt-4 flex flex-wrap items-center gap-x-4 gap-y-2 ${M}mt-3 ${M}mb-4 ${M}gap-x-3`}>
        <Vh>Score </Vh>
        {score && (
          <>
            <b
              className={cn(
                "font-display text-[64px] font-extrabold leading-[0.82] tracking-[-0.05em] tabular-nums lining-nums",
                rise && "animate-[home-rise_var(--dur-slow)_var(--a-ease-expo)_120ms_both]",
              )}
            >
              {score.awarded}
            </b>
            <span className={`-ms-3 self-end font-display text-[40px] font-extrabold leading-none tracking-[-0.04em] opacity-72 ${N}text-[32px] ${M}text-[32px]`}>
              /{score.maximum}
            </span>
          </>
        )}
        <span
          aria-label={`Grade ${r.grade}`}
          className={cn(
            `inline-grid size-16 place-items-center rounded-inner font-display text-[40px] font-extrabold leading-none tracking-[-0.02em] text-white ${N}size-12 ${N}rounded-chip ${N}text-[32px] ${M}size-12 ${M}rounded-chip ${M}text-[32px]`,
            ACT_GRADE[r.grade] ?? "bg-grade-a",
            rise && "animate-[home-rise-in_var(--dur-slow)_var(--a-ease-expo)_260ms_both]",
          )}
        >
          {r.grade}
        </span>
        {first ? (
          <span className="inline-flex items-center rounded-pill bg-surface-container-lowest px-3 py-1.5 font-sans text-sm font-bold leading-none text-primary">
            Your starting point
          </span>
        ) : (
          gradeUp(prev, r.grade) && (
            <span
              className={cn(
                `inline-flex items-center gap-1 rounded-pill bg-surface-container-lowest px-3 py-1.5 font-sans text-base font-bold leading-none text-success-text ${N}text-sm ${M}text-sm`,
                rise && "animate-[home-rise_var(--dur-slow)_var(--a-ease-expo)_380ms_both]",
              )}
            >
              <Icon name="up" className="size-[18px] stroke-[2.2]" />
              up from {prev}
            </span>
          )
        )}
      </p>
      <p className={BODY}>Every mark explained, question by question.</p>
      <Go to={action.to}>See your marks</Go>
    </>
  )
}

const STAGE_TEXT = { 1: "Finding the paper and mark scheme", 2: "Reading your answers" } as const

function Progress({ view }: { view: HomeView }) {
  const p = view.upload?.progress ?? { stage: 1 as const, done: 0, total: 0 }
  const { stage, done, total } = p
  const counted = stage === 3 && total > 0
  const segFill = (seg: 1 | 2 | 3): number => {
    if (seg < stage) return 1
    if (seg > stage) return 0
    if (stage === 1) return 0.55
    if (total > 0) return Math.min(1, done / total)
    return stage === 2 ? 0.5 : 0
  }
  const text = stage === 3 ? (counted ? `Question ${done} of ${total}` : "Marking questions") : STAGE_TEXT[stage]
  return (
    <div
      className={cn(
        `mt-6 mb-7 max-w-[640px] ${N}mt-4 ${N}mb-5 ${M}mt-2 ${M}mb-3`,
        isSparse(view.state) && `${X}my-3`,
      )}
    >
      <p
        role="status"
        aria-live="polite"
        className={`m-0 mb-3 font-sans text-base font-bold leading-[1.3] text-on-primary-container ${M}mb-1 ${M}text-sm`}
      >
        {stage === 3 ? (
          counted ? (
            <>
              Marking question <Mono className="font-bold">{done}</Mono> of <Mono className="font-bold">{total}</Mono>
            </>
          ) : (
            "Marking questions"
          )
        ) : (
          STAGE_TEXT[stage]
        )}
      </p>
      <div
        role="progressbar"
        aria-label="Marking progress"
        aria-valuemin={0}
        aria-valuemax={counted ? total : 3}
        aria-valuenow={counted ? done : stage - 1}
        aria-valuetext={text}
        className="grid grid-cols-3 gap-[6px]"
      >
        {([1, 2, 3] as const).map((seg) => {
          const f = segFill(seg)
          return (
            <span
              key={seg}
              className="block h-2 overflow-hidden rounded-pill bg-[color-mix(in_oklch,var(--color-on-primary-container)_16%,transparent)]"
            >
              <span
                className="block h-full origin-left rounded-[inherit] bg-primary transition-transform duration-500 ease-(--a-ease-expo) rtl:origin-right motion-reduce:transition-none"
                style={{ transform: f === 1 ? "none" : `scaleX(${f})` }}
              />
            </span>
          )
        })}
      </div>
      <ol
        aria-hidden="true"
        className={`m-0 mt-2 grid list-none grid-cols-3 gap-[6px] p-0 font-sans text-sm font-semibold leading-[1.3] text-on-primary-container ${M}hidden`}
      >
        {(["Paper and mark scheme", "Your answers", "Questions"] as const).map((label, i) => {
          const step = i + 1
          return (
            <li
              key={label}
              className={cn("opacity-62 transition-opacity duration-200", step <= stage && "opacity-100", step === stage && "font-bold")}
            >
              {label}
              {step === 3 && counted && (
                <>
                  {" "}
                  <Mono className="text-2xs">{`${done}/${total}`}</Mono>
                </>
              )}
            </li>
          )
        })}
      </ol>
    </div>
  )
}

function MarkingAct({ view, action }: { view: HomeView; action: Extract<NextAction, { kind: "marking" }> }) {
  const first = view.totalPapers === 0
  const label = view.upload?.paperLabel ?? null
  const code = view.upload?.subjectCode ?? null
  const waiting = view.subjects.filter((s) => s.papers === 0 && s.code !== code).map((s) => s.shortName)
  const sparse = isSparse(view.state)
  return (
    <>
      <Meta code={code}>Marking now</Meta>
      <h3 className={TITLE}>
        {first ? "Your first paper is being marked" : `${label ?? "Your paper"} is being marked`}
      </h3>
      <Progress view={view} />
      {first && (
        <p className={cn(BODY, sparse && `${X}mb-3`)}>
          When {label ? <Mono>{label}</Mono> : "your paper"} is marked you get your grade, every lost mark explained,
          and your first practice targets.
        </p>
      )}
      <Go to={action.to}>See progress</Go>
      {first && waiting.length > 0 && (
        <>
          {" "}
          <a
            href="/student/correct"
            className={`mt-2 inline-flex min-h-11 items-center gap-0.5 font-sans text-sm font-bold leading-[1.3] text-primary no-underline hover:underline hover:underline-offset-3 ${X}m-0 ${X}ms-3 ${X}max-w-[calc(100%-176px)] ${X}align-middle`}
          >
            While you wait, upload {indefinite(waiting[0])} {joinOr(waiting)} paper{" "}
            <Icon name="chev" className="size-4 flex-none" />
          </a>
        </>
      )}
    </>
  )
}

function PracticeAct({ view, action }: { view: HomeView; action: Extract<NextAction, { kind: "practice" }> }) {
  const t = action.topic
  const s = subjectOf(view, t.subjectCode)
  if (view.state === "sparse3") {
    return (
      <>
        <Meta code={t.subjectCode}>Pick up where you left off</Meta>
        <h3 className={TITLE}>{t.topic}</h3>
        <p className={FACTS}><Mono>{`${t.acc}% accuracy · 10 min`}</Mono></p>
        <p className={BODY}>One 10-minute set starts a new streak and waters your {s?.shortName ?? t.subjectCode} plant.</p>
        <Go to={action.to}>Start a 10-minute set</Go>
      </>
    )
  }
  const soFar = view.state === "sparse1" || view.state === "sparse2"
  return (
    <>
      <Meta code={t.subjectCode}>Practise next</Meta>
      <h3 className={TITLE}>{t.topic}</h3>
      <p className={FACTS}><Mono>{`${t.acc}% accuracy`}</Mono></p>
      <p className={BODY}>
        {soFar
          ? "Your weakest topic so far. One short set shows whether it is moving."
          : "Your weakest topic right now. A short set shows whether it is improving."}
      </p>
      <Go to={action.to}>Practise {t.topic.toLowerCase()}</Go>
    </>
  )
}

function Act({ view, rise }: { view: HomeView; rise: boolean }) {
  const a = view.action
  switch (a.kind) {
    case "result":
      return <ResultAct view={view} action={a} rise={rise} />
    case "marking":
      return <MarkingAct view={view} action={a} />
    case "session":
      return (
        <>
          <Meta code={a.session.subjectCode}>Today's session</Meta>
          <h3 className={TITLE}>{a.session.title}</h3>
          <p className={FACTS}><Mono>{`${a.session.minutes} min`}</Mono></p>
          <p className={BODY}>Next in your study plan for {subjectOf(view, a.session.subjectCode)?.name ?? a.session.subjectCode}.</p>
          <Go to={a.to}>Start session</Go>
        </>
      )
    case "first-paper":
      return (
        <>
          <h3 className={TITLE}>Let's get your first paper marked</h3>
          <p className={BODY}>
            Photograph or upload a paper you have already sat. Lemely finds the session and variant, pulls the official
            mark scheme, and marks it question by question.
          </p>
          <Go to={a.to}>Upload a paper</Go>
        </>
      )
    case "practice":
      return <PracticeAct view={view} action={a} />
    case "correct":
      return (
        <>
          <h3 className={TITLE}>Ready for another paper?</h3>
          <p className={BODY}>Each paper sharpens your predicted grade.</p>
          <Go to={a.to}>Upload a paper</Go>
        </>
      )
  }
}

export function NextStepCard({ view }: { view: HomeView }) {
  const hid = useId()
  const motion = useMotionOn()
  const [ref, inView] = useInView<HTMLElement>()
  const rise = motion && inView
  return (
    <section ref={ref} data-home="next" data-anim aria-labelledby={hid} className={CARD}>
      <h2 id={hid} className="sr-only">
        Your next step
      </h2>
      <div
        data-action={view.action.kind}
        className={cn(ACT, rise && "animate-[home-rise_var(--dur-slow)_var(--a-ease-expo)_120ms_both]")}
      >
        <Act view={view} rise={rise} />
      </div>
    </section>
  )
}
```

Notes for the implementer:
- `localISODate(new Date(recordedAt))` dates the result in the reader's time zone, as the design does ("Marked 4 Nov" for 18:00 local on 4 Nov).
- `Practise ${topic.toLowerCase()}` reproduces "Practise waves", "Practise quadratic inequalities". A topic with a proper noun would be lowercased too. That is the design's copy, kept as is.
- `ACT_GRADE` gives D, E and U their own grade colours. The design's default (`.a-act-grade` = grade A green, `variant-a.css:1314`) would show a D in green. No fixture reaches D, E or U, so no scene changes. Name it in the task report as a design improvement for the user to confirm.
- Whitespace: the design has a newline between the button and the also-link, which renders a space. `{" "}` reproduces it, so the link sits beside the button at ≥900 in sparse0 (`variant-a.css:2239–2243`).

- [ ] **Step 3: Run the markup tests**

Run: `cd web && npx vitest run tests/unit/studentHomeMarkup.test.ts`
Expected: PASS (Garden and NextStepCard blocks). React escapes `'` as `&#x27;`, which is why no assertion includes "Today's session" or "Let's".

- [ ] **Step 4: Drift scenes**

In `web/scripts/home-drift/overview.mjs`, add:

```js
/** Spec §4 interaction pair: mid marking-stage walk (stage 2 of 3). */
export const MARKING_STAGE_2 = {
  id: "marking-stage-2",
  state: "marking",
  overrides: { upload: { ...API_FIXTURES.marking.upload, progress: { stage: 2, done: 6, total: 12 } } },
  // variant-a.js setStage(prog, 2) sets data-stage; the static "Questions 7/12" step is
  // rewritten to the app's stage-2 copy ("Questions": no question counts before stage 3).
  preview: async (page) => {
    await page.evaluate(() => {
      const prog = document.querySelector('[data-when-action="marking"] .a-prog')
      prog.dataset.stage = "2"
      prog.querySelector('[data-step="3"]').textContent = "Questions"
    })
    await page.waitForTimeout(600) // .a-prog-fill transition is 500ms
  },
  app: async () => {},
}
```

In `web/scripts/home-drift.mjs`:

```js
import { MARKING_STAGE_2 } from "./home-drift/overview.mjs"
// …in the scene list:
...overviewScenes({ part: "next", states: READY_STATES, interactions: [MARKING_STAGE_2] }),
```

Run: `cd web && node scripts/home-drift.mjs --only overview:next`
Expected: `overview:next PASS 130/130` (12 states × 5 widths × 2 themes + 10). Every next-card scene must reach 0 px. This card has no design value the data cannot reproduce. On a failure, open the diff, find the mapping row, fix it, and re-run that scene with `--only overview:next:<state>:<width>:<theme>`.

The third spec interaction, "after a result is opened", is a page-level pair: open the result, come back, and see the hero and card return to `populated`. It belongs to the `page` part (Task 17/19), not this task.

- [ ] **Step 5: Commit**

```bash
cd web && /home/sico/Code/Lemely/.venv/bin/pre-commit run --files src/portals/student/home/NextStepCard.tsx tests/unit/studentHomeMarkup.test.ts scripts/home-drift/overview.mjs scripts/home-drift.mjs
git commit -S -m "feat(web): student home next-step card with live marking progress" -- web/src/portals/student/home/NextStepCard.tsx web/tests/unit/studentHomeMarkup.test.ts web/scripts/home-drift/overview.mjs web/scripts/home-drift.mjs
```

---

---

## Conventions for Tasks 14–16

These three tasks share the rules below. Every implementer of Task 14, 15 or 16 reads this block.

- **Design variables.** Class strings reference design A's variables with Tailwind v4's arbitrary-variable syntax, e.g. `bg-(--surface-card)`, `text-(--text-secondary)`, `rounded-(--radius-tile)`, `shadow-(--a-card-edge)`, `duration-(--dur-fast)`. The **Task 10 token map** defines every design variable named here (`--surface-card`, `--surface-row`, `--surface-hover-tint`, `--text-body`, `--text-secondary`, `--text-muted`, `--border-default`, `--border-subtle`, `--md-primary`, `--md-on-primary`, `--md-primary-container`, `--md-on-primary-container`, `--md-surface-low`, `--md-surface-highest`, `--md-success`, `--a-success-text`, `--a-card-edge`, `--a-ease-expo`, `--sh-grade-c|b|a|astar`, `--radius-*`, `--shadow-hover`, `--dur-*`, `--font-ui|mono|display`) as custom properties on `#sh-root`, in light and dark, from `web/src/index.css` tokens. If Task 10 instead published a utility for a variable (for example `bg-card` for `--surface-card`), use that utility. The left column of each mapping table (the design rule) is authoritative.
- **Fixed sizes.** `--fs-*` and `--space-*` are constants in `tokens.css` (`--fs-label` 11px, `--fs-body-sm`/`--fs-data` 14px, `--fs-body` 16px, `--fs-title` 21px, `--fs-headline` 32px; `--space-N` = N×4px). They are written as literal Tailwind values (`text-[14px]`, `p-5`).
- **Container breakpoints.** `StudentHome` (Task 17) puts `@container/home` on the page column, as `container-name: home` does in the preview. The CSS's `@container home (max-width: 760px)` is `@max-[760px]/home:`; `(min-width: 761px)` is `@min-[761px]/home:`; `(max-width: 560px)` is `@max-[560px]/home:`; `(min-width: 561px) and (max-width: 760px)` is `@min-[561px]/home:@max-[760px]/home:`; `(max-width: 959px)` is `@max-[959px]/home:`. These match the **Task 10 token map**'s breakpoint list.
- **Cascade.** `variant-a.css` overrides its own rules later in the file (critique waves, the "live steer" tail). Each mapping table gives the **effective** value at each width and cites every line that contributes. Where a later line wins, the earlier one is listed as "overridden".
- **Shared state helpers.** Task 14 creates `web/src/portals/student/home/states.ts`. If an earlier task (10–13) already created it with the same exports, reuse it and skip that step.
- **Motion.** Entrance animations run only when `useMotionOn()` is true and the section has been seen (`useInView()`). The drift gate runs with reduced motion, so motion is checked by eye in Step "Motion check", not by pixels.

---

## Task 14: `GradesList` (Your grades)

**Files:**
- Create: `web/src/portals/student/home/states.ts`
- Create: `web/src/portals/student/home/geometry.ts`
- Create: `web/src/portals/student/home/GradesList.tsx`
- Modify: `web/src/index.css` (keyframes in `@theme`)
- Modify: `web/scripts/home-drift.mjs` (register `grades` scenes)
- Test: `web/tests/unit/studentHomeGeometry.test.ts` (create), `web/tests/unit/studentHomeMarkup.test.ts` (append; create if absent)

**Interfaces:**
- Consumes: `HomeView`, `SubjectView`, `DataState` (`facts.ts`, Task 8); `indefinite`, `dayMonth` (`format.ts`, Task 8); `Code`, `Est`, `Icon`, `Mono`, `Vh`, `useMotionOn`, `useInView` (`primitives.tsx`, Task 10); `overviewScenes` (Task 9); `API_FIXTURES`, `API_NOW` (Task 8).
- Produces:
  - `states.ts`: `export const MANY_PAPERS_STATES: ReadonlySet<DataState>` (`populated`, `result-in`, `marking`, `no-plan`, `no-exams`, `streak-zero`); `export function isSparse(s: DataState): boolean` (`s.startsWith("sparse")`); `export function isManyPapers(s: DataState): boolean`.
  - `geometry.ts`: `export const GRADE_STOPS = [["C", 12], ["B", 37], ["A", 62], ["A*", 87]] as const`; `export function nextGrade(pct: number, b: GradeBoundaries): string | null`; `export function journeyPos(pct: number, b: GradeBoundaries): number` (percent of the journey width, 2 decimals). Task 16 adds `examPos` to this file.
  - `export function GradesList(props: { view: HomeView }): JSX.Element`, root `<section data-home="grades">`.
  - `export function gradeRowLabel(s: SubjectView, state: DataState): string`, exported for the markup test.

**Design facts this task encodes** (from `page-a.txt` 413–522 and `variant-a.css`):
- Row order: graded subjects (`papers > 0`) by `nextExamOn` ascending, with no date last and code as tie-break. Populated: Physics (4 May), Mathematics (12 May), Additional Mathematics (18 May). Then one waiting row per `papers === 0` subject: the subject being marked (`view.upload?.subjectCode`) first, then code order (sparse0: Mathematics, Additional Mathematics, Physics).
- Stones sit at fixed positions C 12%, B 37%, A 62%, A* 87%. A stone `is-passed` when `pct >= boundary`. `is-next` is the lowest grade not passed. The rest are `is-ahead`.
- **Marker position formula** (verified against every row in the markup): between two stones, linear on that subject's boundaries. Below C: `12 × (pct − (C − 10)) / 10`, floored at 0. At or above A*: `87 + 13 × (pct − A*) / (100 − A*)`.
  - Physics: 48 between C45/B52 gives 12 + 3/7·25 = **22.71** ✓. Its first paper, 41, is below C: 12·(41−35)/10 = **7.2** ✓.
  - Mathematics: 76 between A70/A*85 gives 62 + 6/15·25 = **72.0** ✓; first paper 49 gives 12 + 7/13·25 = **25.46** ✓.
  - Additional Mathematics: 59 gives **45.93** ✓; first paper 44 gives **19.14** ✓.
  - one-paper Mathematics 65 → **53.67** ✓; sparse1 46 → **19.69** ✓; sparse2 Mathematics 58 → **42.0** ✓, Additional Mathematics 47 → **24.5** ✓; sparse3 60 → **45.33** ✓, 49 → **28.07** ✓, first 45 → **20.93** ✓.
- The trail runs from `journeyPos(firstPct)` to `journeyPos(pct)`, width = difference. It is drawn only when `papers >= 2` (no trail in one-paper or sparse1, or for sparse2's 1-paper Additional Mathematics).
- The distance line is `<Mono>{next − pct}%</Mono> from {a|an} {next}`.
- The per-stone threshold labels (`.a-j-b`, "C 45%") are in the markup but **never visible**: `variant-a.css:1829` `.a-gj .a-j-b { display: none }` applies at every width. They are not rendered. The row's `aria-label` carries the numbers.
- `details.a-key` ("What do the labels mean?") renders only in the many-papers states (`data-needs="many-papers"`; hidden in one-paper by `shell.css:70` and in sparse by `variant-a.css:2071`).
- `.a-est` "estimated" after the code when `boundariesEstimated`.
- aria-label template (each clause verified against all 11 graded rows in the markup):
  `"{name}, {code}: {pct}%, grade {grade}, {d}% from {a|an} {next}."` + (estimated ? `" Boundaries estimated: no exact boundary for this paper yet; based on past sessions."` : "") + `" C {c}%, B {b}%, A {a}%, A* {a*}%."` + suffix. The suffix is `" Your first paper."` when `papers === 1` and the state is sparse; `" Started at {firstPct}%."` when `papers >= 2`; nothing in one-paper.
- Waiting row: `href="/student/correct"`. If the subject is being marked: dist "Marking now", wait "Your first grade lands here when `<Mono>{paperLabel}</Mono>` is marked." Otherwise: dist "No paper yet", wait "Upload {a|an} {shortName} paper to see where you stand."
- No next grade (pct ≥ A* boundary): the design has no example. The row shows the distance text "Top grade" and the aria-label clause becomes "grade A*, top grade.". This is copy beyond the design: log it under "Copy added" in the drift log at Task 19, for the user to approve.

### Mapping: design rule → Tailwind (effective values)

| Element | Design rule (variant-a.css line: declarations) | Tailwind classes |
|---|---|---|
| `section.a-sec` | 591 `margin-block-start: calc(space-5*2)` = 40px; 1439 `@min 761 → 20px`; 1226 `@max 760 → 32px` | `mt-10 @min-[761px]/home:mt-5 @max-[760px]/home:mt-8` |
| `h2.a-sec-h` | 592–595 `margin: 0 0 12px; font: 800 21px/1.2 font-ui; letter-spacing: ls-headline-ui(-0.02em); color: text-body` (1440 same margin) | `m-0 mb-3 font-(family-name:--font-ui) text-[21px]/[1.2] font-extrabold tracking-[-0.02em] text-(--text-body)` |
| `details.a-key` | 1895 `margin: -8px 0 12px; font-size: 14px; color: text-secondary` | `-mt-2 mb-3 text-[14px] text-(--text-secondary)` |
| `.a-key > summary` | 1896–1903 `inline-flex; align-items:center; min-block-size:44px; padding-inline:4px; radius-chip; color text-secondary; 700; cursor:pointer; list-style:none; ::after "+" / open "−" mono ml 8px; hover primary` | `inline-flex items-center min-h-11 px-1 rounded-(--radius-chip) font-bold cursor-pointer list-none [&::-webkit-details-marker]:hidden after:content-['+'] after:ml-2 after:font-(family-name:--font-mono) group-open/key:after:content-['\2212'] hover:text-(--md-primary)` (the `details` carries `group/key`) |
| `.a-key dl` | 1904 `grid; gap 8px; margin 0; padding 12px 16px; radius-inner; bg md-surface-low`; 1910 `@max 560 gap 12px` | `grid gap-2 m-0 px-4 py-3 rounded-(--radius-inner) bg-(--md-surface-low) @max-[560px]/home:gap-3` |
| `.a-key dl > div` | 1905 `grid; cols minmax(7rem,max-content) minmax(0,1fr); gap 12px; baseline`; 1909 `@max 560 cols minmax(0,1fr)` | `grid grid-cols-[minmax(7rem,max-content)_minmax(0,1fr)] gap-3 items-baseline @max-[560px]/home:grid-cols-[minmax(0,1fr)]` |
| `dt` / `dd` | 1906 `color text-body; 700` / 1907 `margin 0` | `text-(--text-body) font-bold` / `m-0` |
| `ul.a-gj` | 351–354 `margin 0; padding 8px; list-style none; radius-card; bg surface-card; box-shadow a-card-edge`; 1830 `padding 4px` (wins) | `m-0 p-1 list-none rounded-(--radius-card) bg-(--surface-card) shadow-(--a-card-edge)` |
| `li + li` | 355 `border-block-start: 1px solid border-subtle` (one-paper has one row; 2169 re-asserts it for sparse) | `[&+li]:border-t [&+li]:border-(--border-subtle)` |
| `a.a-gj-row` (desktop ≥761) | 357–362 `grid; cols 220px 170px minmax(0,1fr) 18px; align center; gap 24px; min-h 64 (1442 → 52; 1831 → 0 wins); padding 4px 20px (1831 padding-block 4px wins); radius-tile; color text-body; transition bg fast, transform/box-shadow base`; 363 hover `bg surface-card; shadow-hover`; 364 focus `outline-offset -2px` | `grid grid-cols-[220px_170px_minmax(0,1fr)_18px] items-center gap-6 min-h-0 px-5 py-1 rounded-(--radius-tile) text-(--text-body) no-underline transition-[background-color,transform,box-shadow] duration-(--dur-base) hover:bg-(--surface-card) hover:shadow-(--shadow-hover) focus-visible:outline-offset-[-2px] group/row` |
| row ≤760 | 1262–1265 `cols minmax(0,1fr) auto; areas "n d" "j j"; row-gap 4px; padding 12px 16px 8px` (padding-block overridden by 1831 → 4px) | `@max-[760px]/home:grid-cols-[minmax(0,1fr)_auto] @max-[760px]/home:[grid-template-areas:'n_d'_'j_j'] @max-[760px]/home:gap-y-1 @max-[760px]/home:px-4` |
| row 561–760 | 1737–1740 `cols minmax(160px,240px) minmax(0,1fr); areas "n j" "d j"; column-gap 20px; row-gap 2px; padding 12px 16px` (block → 4px by 1831) | `@min-[561px]/home:@max-[760px]/home:grid-cols-[minmax(160px,240px)_minmax(0,1fr)] @min-[561px]/home:@max-[760px]/home:[grid-template-areas:'n_j'_'d_j'] @min-[561px]/home:@max-[760px]/home:gap-x-5 @min-[561px]/home:@max-[760px]/home:gap-y-0.5` |
| row ≤560 | 1760 `row-gap 0; padding 12px 16px 4px`; 1836 `padding-block 8px 4px` (wins) | `@max-[560px]/home:gap-y-0 @max-[560px]/home:pt-2 @max-[560px]/home:pb-1` |
| `.a-gj-name` | 365 `flex; baseline; wrap; gap 2px 8px; min-w 0`; 1266 `grid-area n`; 1741 `561–760 align-self end` | `flex items-baseline flex-wrap gap-x-2 gap-y-0.5 min-w-0 @max-[760px]/home:[grid-area:n] @min-[561px]/home:@max-[760px]/home:self-end` |
| `.a-gj-name b` | 366 `16px 700`; 1443 `@min 761 14px` | `text-[16px] font-bold @min-[761px]/home:text-[14px]` |
| `.a-gj-dist` | 367 `14px 600 text-secondary`; 368 mono `text-body`; 1267 `grid-area d`; 1742 `561–760 align-self start` | `text-[14px] font-semibold text-(--text-secondary) [&_.a-mono]:text-(--text-body) @max-[760px]/home:[grid-area:d] @min-[561px]/home:@max-[760px]/home:self-start` (the `Mono` primitive gets `text-(--text-body)` directly) |
| `.a-journey` | 282 `relative; h 64; margin-inline 18px`; 369/1444/1762 heights overridden; 1832 `block-size 40px; margin-block-end 0` (wins); 1743 `561–760 margin-block-start 8px`; 1268 `grid-area j` | `relative h-10 mx-[18px] mb-0 @max-[760px]/home:[grid-area:j] @min-[561px]/home:@max-[760px]/home:mt-2` |
| `.a-j-line` | 283–286 `absolute; inset-inline -18px; top calc(68% - 2px); h 4px; radius pill; bg md-surface-highest` | `absolute -inset-x-[18px] top-[calc(68%-2px)] h-1 rounded-full bg-(--md-surface-highest)` |
| `.a-j-trail` | 287–290 `absolute; top calc(68% - 5px); h 10px; radius pill; bg color-mix(primary 30%, transparent)` | `absolute top-[calc(68%-5px)] h-2.5 rounded-full bg-[color-mix(in_oklch,var(--md-primary)_30%,transparent)] origin-left` + inline `insetInlineStart`, `inlineSize` |
| `.a-stone` | 291–296 `absolute; z 1; top 68%; translate(-50%,-50%); grid center; 34px (1445/1238 30px; 1833 28px wins); radius 50%; font 800 21px/1 font-ui; ls -0.02em; bg surface-card; color text-muted; inset 0 0 0 2px border-default` | `absolute z-[1] top-[68%] -translate-x-1/2 -translate-y-1/2 grid place-items-center size-7 rounded-full font-(family-name:--font-ui) text-[21px]/none font-extrabold tracking-[-0.02em]` + state classes below |
| `.is-ahead` (default) | 295 | `bg-(--surface-card) text-(--text-muted) shadow-[inset_0_0_0_2px_var(--border-default)]` |
| `.is-passed` | 297 `color white; box-shadow 0 0 0 3px surface-card`; 299–302 bg per grade | `text-white shadow-[0_0_0_3px_var(--surface-card)]` + `bg-(--sh-grade-c)` / `bg-(--sh-grade-b)` / `bg-(--sh-grade-a)` / `bg-(--sh-grade-astar)` |
| `.is-next` | 298 `color text-body; inset 0 0 0 3px sh-grade-b`; 303 A → grade-a; 304 A* → astar (C uses B's ring: no rule) | `bg-(--surface-card) text-(--text-body)` + `shadow-[inset_0_0_0_3px_var(--sh-grade-b)]` (C, B) / `shadow-[inset_0_0_0_3px_var(--sh-grade-a)]` (A) / `shadow-[inset_0_0_0_3px_var(--sh-grade-astar)]` (A*) |
| `.a-j-me` | 317–320 `absolute; z 2; top 68%; 18px (1834 → 14px wins); radius 50%; bg primary; shadow 0 0 0 3px surface-card; translate(-50%,-50%)` | `absolute z-[2] top-[68%] size-3.5 rounded-full bg-(--md-primary) shadow-[0_0_0_3px_var(--surface-card)] -translate-x-1/2 -translate-y-1/2` |
| `.a-j-me-l` | 321–325 `absolute; bottom calc(100% + 8px); left 50%; translateX(-50%); padding 2px 6px; pill; bg primary; color on-primary; nowrap; 700 11px/1.2 mono; tabular`; 2225 `@max 560 bottom calc(100% + 10px)` | `absolute bottom-[calc(100%+8px)] left-1/2 -translate-x-1/2 px-1.5 py-0.5 rounded-full bg-(--md-primary) text-(--md-on-primary) whitespace-nowrap font-(family-name:--font-mono) text-[11px]/[1.2] font-bold tabular-nums @max-[560px]/home:bottom-[calc(100%+10px)]` |
| `.a-gj-go` | 370 `color text-muted; transition transform base, color fast`; 371 row hover `translateX(3px); text-body`; 1269 `@max 760 display none` | `text-(--text-muted) transition-[transform,color] duration-(--dur-base) group-hover/row:translate-x-[3px] group-hover/row:text-(--text-body) @max-[760px]/home:hidden` |
| `.a-gj-row-lock` | 2163 `padding-block 8px` (wins over 1831 and 1836: later); 2164 dist `text-muted`; 2165 hover wait `border primary; text-body` | add `py-2 @max-[560px]/home:py-2` to the row; dist gets `text-(--text-muted)`; wait gets `group-hover/row:border-(--md-primary) group-hover/row:text-(--text-body)` |
| `.a-gj-wait` | 2159–2162 `block; padding 8px 12px; 1.5px dashed border-default; radius-chip; text-secondary; 14px; lh 1.4`; 2166–2168 `@max 959 grid-area j; margin-block 8px` | `block px-3 py-2 border-[1.5px] border-dashed border-(--border-default) rounded-(--radius-chip) text-(--text-secondary) text-[14px]/[1.4] @max-[959px]/home:[grid-area:j] @max-[959px]/home:my-2` |

Motion (537–546, `@media (prefers-reduced-motion: no-preference)` scope via `useMotionOn()`): trail `aDraw 500ms expo 150ms both`; marker `aSlide` from the first-paper position; passed stones `aAck 240ms` delayed by when the marker reaches them; next stone `aGlow` 350ms at 550ms. These become `@theme` keyframes in Step 4.

- [ ] **Step 1: Write the failing geometry test**

`web/tests/unit/studentHomeGeometry.test.ts`:

```ts
import { describe, expect, it } from "vitest"
import { journeyPos, nextGrade } from "@/portals/student/home/geometry"

const MATHS = { C: 42, B: 55, A: 70, "A*": 85 }
const ADD = { C: 40, B: 54, A: 68, "A*": 82 }
const PHYS = { C: 45, B: 52, A: 66, "A*": 80 }

describe("journeyPos: every marker and trail start in student-home-a.html", () => {
  it.each([
    [48, PHYS, 22.71], [41, PHYS, 7.2],
    [76, MATHS, 72], [49, MATHS, 25.46], [65, MATHS, 53.67], [46, MATHS, 19.69], [58, MATHS, 42], [60, MATHS, 45.33],
    [59, ADD, 45.93], [44, ADD, 19.14], [47, ADD, 24.5], [49, ADD, 28.07], [45, ADD, 20.93],
  ] as const)("%d%% → %d", (pct, b, expected) => {
    expect(journeyPos(pct, b)).toBe(expected)
  })

  it("clamps below the floor and runs to 100 above A*", () => {
    expect(journeyPos(10, PHYS)).toBe(0)
    expect(journeyPos(100, MATHS)).toBe(100)
    expect(journeyPos(85, MATHS)).toBe(87)
  })
})

describe("nextGrade", () => {
  it("is the lowest grade not yet reached", () => {
    expect(nextGrade(48, PHYS)).toBe("B")
    expect(nextGrade(76, MATHS)).toBe("A*")
    expect(nextGrade(30, MATHS)).toBe("C")
    expect(nextGrade(90, MATHS)).toBeNull()
  })
})
```

Run: `cd web && npx vitest run tests/unit/studentHomeGeometry.test.ts`
Expected: FAIL, `Cannot find module '@/portals/student/home/geometry'`.

- [ ] **Step 2: Implement `states.ts` and `geometry.ts`**

`web/src/portals/student/home/states.ts`:

```ts
/* State families design A gates on (shell.css:68-74, variant-a.css:2049-2071). */
import type { DataState } from "./facts"

export const MANY_PAPERS_STATES: ReadonlySet<DataState> = new Set<DataState>([
  "populated", "result-in", "marking", "no-plan", "no-exams", "streak-zero",
])

export const isSparse = (s: DataState): boolean => s.startsWith("sparse")
export const isManyPapers = (s: DataState): boolean => MANY_PAPERS_STATES.has(s)
```

`web/src/portals/student/home/geometry.ts`:

```ts
/*
 * Positions design A draws from data. Every constant is read off
 * student-home-a.html and checked against each row in studentHomeGeometry.test.ts.
 */
import type { GradeBoundaries } from "@/lib/studentTypes"

/** Grade stones on the journey line, as percent of its width (.a-stone inset-inline-start). */
export const GRADE_STOPS = [["C", 12], ["B", 37], ["A", 62], ["A*", 87]] as const
const STONE_GAP = 25
const BELOW_C_SPAN = 10 // pct points below C that map onto 0..12%

const round2 = (n: number): number => Math.round(n * 100) / 100

export function nextGrade(pct: number, b: GradeBoundaries): string | null {
  for (const [grade] of GRADE_STOPS) {
    if (b[grade] !== undefined && pct < b[grade]) return grade
  }
  return null
}

export function journeyPos(pct: number, b: GradeBoundaries): number {
  const stops = GRADE_STOPS.filter(([g]) => b[g] !== undefined).map(([g, at]) => [b[g], at] as const)
  const [cPct, cAt] = stops[0]
  if (pct < cPct) return round2(Math.max(0, (cAt * (pct - (cPct - BELOW_C_SPAN))) / BELOW_C_SPAN))
  for (let i = 0; i < stops.length - 1; i++) {
    const [lo, loAt] = stops[i]
    const [hi] = stops[i + 1]
    if (pct < hi) return round2(loAt + (STONE_GAP * (pct - lo)) / (hi - lo))
  }
  const [topPct, topAt] = stops[stops.length - 1]
  return round2(Math.min(100, topAt + ((100 - topAt) * (pct - topPct)) / (100 - topPct)))
}
```

Run: `cd web && npx vitest run tests/unit/studentHomeGeometry.test.ts`
Expected: PASS (16 tests).

- [ ] **Step 3: Write the failing markup test (append)**

Append to `web/tests/unit/studentHomeMarkup.test.ts`. If the file does not exist yet, create it with these imports. If it exists, add only the imports that are missing and reuse its `render(state)` helper when it has one with this signature.

```ts
import { createElement, type ReactElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { MemoryRouter } from "react-router-dom"
import { describe, expect, it } from "vitest"
import { API_FIXTURES, API_NOW, type DataStateId } from "../../dev-previews/student-home/api-fixtures"
import { toHomeView } from "@/portals/student/home/facts"
import { GradesList, gradeRowLabel } from "@/portals/student/home/GradesList"

const viewOf = (s: DataStateId) => {
  const { overview, xp, upload } = API_FIXTURES[s]
  return toHomeView(overview, xp, upload, API_NOW)
}
const html = (el: ReactElement) => renderToStaticMarkup(createElement(MemoryRouter, null, el))
const labels = (markup: string) => [...markup.matchAll(/aria-label="([^"]+)"/g)].map((m) => m[1].replaceAll("&#x27;", "'"))

describe("GradesList", () => {
  it("populated: closest exam first, design aria-labels verbatim, key shown", () => {
    const out = html(createElement(GradesList, { view: viewOf("populated") }))
    expect(out).toContain(">Your grades</h2>")
    expect(out).toContain("What do the labels mean?")
    expect(labels(out)).toEqual([
      "Physics, 0625: 48%, grade C, 4% from a B. Boundaries estimated: no exact boundary for this paper yet; based on past sessions. C 45%, B 52%, A 66%, A* 80%. Started at 41%.",
      "Mathematics, 0580: 76%, grade A, 9% from an A*. C 42%, B 55%, A 70%, A* 85%. Started at 49%.",
      "Additional Mathematics, 0606: 59%, grade B, 9% from an A. C 40%, B 54%, A 68%, A* 82%. Started at 44%.",
    ])
  })

  it("one-paper: no key, no started/first suffix", () => {
    const out = html(createElement(GradesList, { view: viewOf("one-paper") }))
    expect(out).not.toContain("What do the labels mean?")
    expect(labels(out)).toEqual(["Mathematics, 0580: 65%, grade B, 5% from an A. C 42%, B 55%, A 70%, A* 85%."])
  })

  it("sparse rows: first-paper suffix, then waiting rows", () => {
    const v = viewOf("sparse2")
    expect(v.subjects.map((s) => gradeRowLabel(s, v.state)).filter(Boolean)).toEqual([
      "Mathematics, 0580: 58%, grade B, 12% from an A. C 42%, B 55%, A 70%, A* 85%. Started at 46%.",
      "Additional Mathematics, 0606: 47%, grade C, 7% from a B. C 40%, B 54%, A 68%, A* 82%. Your first paper.",
    ])
    const out = html(createElement(GradesList, { view: v }))
    expect(out).toContain("Upload a Physics paper to see where you stand.")
    expect(out.indexOf("Additional Mathematics")).toBeLessThan(out.indexOf("Upload a Physics paper"))
  })

  it("sparse0: the subject being marked waits first, the others ask for a paper", () => {
    const out = html(createElement(GradesList, { view: viewOf("sparse0") }))
    expect(out).toContain("Marking now")
    expect(out).toMatch(/Your first grade lands here when <span[^>]*>0580\/42<\/span> is marked\./)
    expect(out).toContain("Upload an Add Maths paper to see where you stand.")
    expect(out.indexOf("Mathematics")).toBeLessThan(out.indexOf("Additional Mathematics"))
  })
})
```

Run: `cd web && npx vitest run tests/unit/studentHomeMarkup.test.ts -t GradesList`
Expected: FAIL, module `GradesList` not found.

- [ ] **Step 4: Keyframes**

Append inside the `@theme` block of `web/src/index.css` that holds animations. If Task 10 already declared any of these names with identical bodies, keep one copy.

```css
  --animate-home-draw: home-draw 500ms var(--ease-expo) both;
  --animate-home-slide: home-slide 500ms var(--ease-expo) both;
  --animate-home-ack: home-ack 240ms var(--ease-expo) both;
  --animate-home-glow: home-glow 350ms var(--ease-expo) both;
  @keyframes home-draw { from { transform: scaleX(0) } }
  @keyframes home-slide { from { inset-inline-start: var(--from) } }
  @keyframes home-ack { 0%, 100% { transform: translate(-50%, -50%) } 45% { transform: translate(-50%, -50%) scale(1.08) } }
  @keyframes home-glow { 0% { opacity: 0.9; transform: scale(1) } 100% { opacity: 0; transform: scale(1.6) } }
```

`home-slide` animates `inset-inline-start` from the first-paper position instead of the preview's measured `--from` pixel offset (`variant-a.js measureJourneys`). The start and end frames are the same and no script measures anything. `--ease-expo` is the app token matching `--a-ease-expo: cubic-bezier(0.16, 1, 0.3, 1)` (`variant-a.css:7`). If the token map shows the values differ, use `cubic-bezier(0.16,1,0.3,1)` literally.

- [ ] **Step 5: Implement `GradesList.tsx`**

```tsx
/* Your grades (design A .a-grades, student-home-a.html 413-522). One journey per graded
 * subject, closest exam first, then a dashed waiting row per subject with no paper. */
import type { CSSProperties } from "react"
import { Link } from "react-router-dom"
import { cn } from "@/lib/utils"
import type { DataState, HomeView, SubjectView } from "./facts"
import { indefinite } from "./format"
import { GRADE_STOPS, journeyPos, nextGrade } from "./geometry"
import { Code, Est, Icon, Mono, useInView, useMotionOn } from "./primitives"
import { isManyPapers, isSparse } from "./states"

const NO_DATE = "9999-12-31"

const ROW = cn(
  "group/row grid grid-cols-[220px_170px_minmax(0,1fr)_18px] items-center gap-6 min-h-0 px-5 py-1",
  "rounded-(--radius-tile) text-(--text-body) no-underline",
  "transition-[background-color,transform,box-shadow] duration-(--dur-base)",
  "hover:bg-(--surface-card) hover:shadow-(--shadow-hover) focus-visible:outline-offset-[-2px]",
  "@max-[760px]/home:grid-cols-[minmax(0,1fr)_auto] @max-[760px]/home:[grid-template-areas:'n_d'_'j_j'] @max-[760px]/home:gap-y-1 @max-[760px]/home:px-4",
  "@min-[561px]/home:@max-[760px]/home:grid-cols-[minmax(160px,240px)_minmax(0,1fr)] @min-[561px]/home:@max-[760px]/home:[grid-template-areas:'n_j'_'d_j'] @min-[561px]/home:@max-[760px]/home:gap-x-5 @min-[561px]/home:@max-[760px]/home:gap-y-0.5",
  "@max-[560px]/home:gap-y-0 @max-[560px]/home:pt-2 @max-[560px]/home:pb-1",
)
const NAME = "flex items-baseline flex-wrap gap-x-2 gap-y-0.5 min-w-0 @max-[760px]/home:[grid-area:n] @min-[561px]/home:@max-[760px]/home:self-end"
const NAME_B = "text-[16px] font-bold @min-[761px]/home:text-[14px]"
const DIST = "text-[14px] font-semibold text-(--text-secondary) @max-[760px]/home:[grid-area:d] @min-[561px]/home:@max-[760px]/home:self-start"
const GO = "text-(--text-muted) transition-[transform,color] duration-(--dur-base) group-hover/row:translate-x-[3px] group-hover/row:text-(--text-body) @max-[760px]/home:hidden"

const PASSED_BG: Record<string, string> = {
  C: "bg-(--sh-grade-c)", B: "bg-(--sh-grade-b)", A: "bg-(--sh-grade-a)", "A*": "bg-(--sh-grade-astar)",
}
const NEXT_RING: Record<string, string> = {
  C: "shadow-[inset_0_0_0_3px_var(--sh-grade-b)]", B: "shadow-[inset_0_0_0_3px_var(--sh-grade-b)]",
  A: "shadow-[inset_0_0_0_3px_var(--sh-grade-a)]", "A*": "shadow-[inset_0_0_0_3px_var(--sh-grade-astar)]",
}

function graded(view: HomeView): SubjectView[] {
  return view.subjects
    .filter((s) => s.papers > 0 && s.pct !== null && s.boundaries)
    .sort((a, b) => (a.nextExamOn ?? NO_DATE).localeCompare(b.nextExamOn ?? NO_DATE) || a.code.localeCompare(b.code))
}

function waiting(view: HomeView): SubjectView[] {
  const marking = view.upload?.subjectCode ?? null
  return view.subjects
    .filter((s) => s.papers === 0)
    .sort((a, b) => Number(b.code === marking) - Number(a.code === marking) || a.code.localeCompare(b.code))
}

export function gradeRowLabel(s: SubjectView, state: DataState): string {
  if (s.papers === 0 || s.pct === null || !s.boundaries) return ""
  const b = s.boundaries
  const next = nextGrade(s.pct, b)
  const head = next
    ? `${s.name}, ${s.code}: ${s.pct}%, grade ${s.grade}, ${b[next] - s.pct}% from ${indefinite(next)} ${next}.`
    : `${s.name}, ${s.code}: ${s.pct}%, grade ${s.grade}, top grade.`
  const est = s.boundariesEstimated
    ? " Boundaries estimated: no exact boundary for this paper yet; based on past sessions."
    : ""
  const bounds = ` ${GRADE_STOPS.filter(([g]) => b[g] !== undefined).map(([g]) => `${g} ${b[g]}%`).join(", ")}.`
  const tail =
    s.papers >= 2 && s.firstPct !== null
      ? ` Started at ${s.firstPct}%.`
      : s.papers === 1 && isSparse(state)
        ? " Your first paper."
        : ""
  return head + est + bounds + tail
}

function Journey({ s, motion }: { s: SubjectView; motion: boolean }) {
  const b = s.boundaries!
  const pct = s.pct!
  const me = journeyPos(pct, b)
  const from = s.papers >= 2 && s.firstPct !== null ? journeyPos(s.firstPct, b) : null
  const next = nextGrade(pct, b)
  return (
    <div className="relative h-10 mx-[18px] mb-0 @max-[760px]/home:[grid-area:j] @min-[561px]/home:@max-[760px]/home:mt-2" aria-hidden="true">
      <span className="absolute -inset-x-[18px] top-[calc(68%-2px)] h-1 rounded-full bg-(--md-surface-highest)" />
      {from !== null && (
        <span
          className={cn(
            "absolute top-[calc(68%-5px)] h-2.5 rounded-full origin-left bg-[color-mix(in_oklch,var(--md-primary)_30%,transparent)]",
            motion && "animate-home-draw [animation-delay:150ms]",
          )}
          style={{ insetInlineStart: `${from}%`, inlineSize: `${round2(me - from)}%` }}
        />
      )}
      {GRADE_STOPS.map(([g, at]) => {
        const state = b[g] !== undefined && pct >= b[g] ? "passed" : g === next ? "next" : "ahead"
        const reachAt = from === null || me === from ? 0 : Math.max(0, ((at - from) / (me - from)) * 500)
        return (
          <span
            key={g}
            data-grade={g}
            className={cn(
              "absolute z-[1] top-[68%] -translate-x-1/2 -translate-y-1/2 grid place-items-center size-7 rounded-full",
              "font-(family-name:--font-ui) text-[21px]/none font-extrabold tracking-[-0.02em]",
              state === "passed" && cn("text-white shadow-[0_0_0_3px_var(--surface-card)]", PASSED_BG[g]),
              state === "next" && cn("bg-(--surface-card) text-(--text-body)", NEXT_RING[g]),
              state === "ahead" && "bg-(--surface-card) text-(--text-muted) shadow-[inset_0_0_0_2px_var(--border-default)]",
              motion && state === "passed" && from !== null && at > from && "animate-home-ack",
            )}
            style={{ insetInlineStart: `${at}%`, animationDelay: motion ? `${150 + reachAt}ms` : undefined }}
          >
            {g}
            {motion && state === "next" && (
              <span className="absolute -inset-[3px] rounded-full shadow-[0_0_0_3px_var(--md-primary)] opacity-0 animate-home-glow [animation-delay:550ms]" />
            )}
          </span>
        )
      })}
      <span
        className={cn(
          "absolute z-[2] top-[68%] size-3.5 rounded-full bg-(--md-primary) shadow-[0_0_0_3px_var(--surface-card)] -translate-x-1/2 -translate-y-1/2",
          motion && from !== null && "animate-home-slide [animation-delay:150ms]",
        )}
        style={{ insetInlineStart: `${me}%`, ["--from" as string]: from !== null ? `${from}%` : undefined } as CSSProperties}
      >
        <span className="absolute bottom-[calc(100%+8px)] left-1/2 -translate-x-1/2 px-1.5 py-0.5 rounded-full bg-(--md-primary) text-(--md-on-primary) whitespace-nowrap font-(family-name:--font-mono) text-[11px]/[1.2] font-bold tabular-nums @max-[560px]/home:bottom-[calc(100%+10px)]">
          {pct}%
        </span>
      </span>
    </div>
  )
}

const round2 = (n: number): number => Math.round(n * 100) / 100

function GradedRow({ s, state, motion }: { s: SubjectView; state: DataState; motion: boolean }) {
  const next = nextGrade(s.pct!, s.boundaries!)
  return (
    <li className="[&+li]:border-t [&+li]:border-(--border-subtle)">
      <Link className={ROW} to={`/student/subject/${s.code}`} aria-label={gradeRowLabel(s, state)}>
        <span className={NAME}>
          <b className={NAME_B}>{s.name}</b>
          <Code>{s.code}</Code>
          {s.boundariesEstimated && <Est />}
        </span>
        <span className={DIST}>
          {next ? (
            <>
              <Mono className="text-(--text-body)">{s.boundaries![next] - s.pct!}%</Mono> from {indefinite(next)} {next}
            </>
          ) : (
            "Top grade"
          )}
        </span>
        <Journey s={s} motion={motion} />
        <Icon name="chev" className={GO} />
      </Link>
    </li>
  )
}

function WaitingRow({ s, view }: { s: SubjectView; view: HomeView }) {
  const marking = view.upload?.subjectCode === s.code
  return (
    <li className="[&+li]:border-t [&+li]:border-(--border-subtle)">
      <Link className={cn(ROW, "py-2 @max-[560px]/home:py-2")} to="/student/correct">
        <span className={NAME}>
          <b className={NAME_B}>{s.name}</b>
          <Code>{s.code}</Code>
        </span>
        <span className={cn(DIST, "text-(--text-muted)")}>{marking ? "Marking now" : "No paper yet"}</span>
        <span className="block px-3 py-2 border-[1.5px] border-dashed border-(--border-default) rounded-(--radius-chip) text-(--text-secondary) text-[14px]/[1.4] group-hover/row:border-(--md-primary) group-hover/row:text-(--text-body) @max-[959px]/home:[grid-area:j] @max-[959px]/home:my-2">
          {marking ? (
            <>
              Your first grade lands here when <Mono>{view.upload?.paperLabel ?? ""}</Mono> is marked.
            </>
          ) : (
            `Upload ${indefinite(s.shortName)} ${s.shortName} paper to see where you stand.`
          )}
        </span>
        <Icon name="chev" className={GO} />
      </Link>
    </li>
  )
}

export function GradesList({ view }: { view: HomeView }) {
  const motionOn = useMotionOn()
  const [ref, inView] = useInView<HTMLElement>()
  const motion = motionOn && inView
  return (
    <section ref={ref} data-home="grades" aria-labelledby="a-grades-h" className="mt-10 @min-[761px]/home:mt-5 @max-[760px]/home:mt-8">
      <h2 id="a-grades-h" className="m-0 mb-3 font-(family-name:--font-ui) text-[21px]/[1.2] font-extrabold tracking-[-0.02em] text-(--text-body)">
        Your grades
      </h2>
      {isManyPapers(view.state) && (
        <details className="group/key -mt-2 mb-3 text-[14px] text-(--text-secondary)">
          <summary className="inline-flex items-center min-h-11 px-1 rounded-(--radius-chip) font-bold cursor-pointer list-none [&::-webkit-details-marker]:hidden after:content-['+'] after:ml-2 after:font-(family-name:--font-mono) group-open/key:after:content-['\2212'] hover:text-(--md-primary)">
            What do the labels mean?
          </summary>
          <dl className="grid gap-2 m-0 px-4 py-3 rounded-(--radius-inner) bg-(--md-surface-low) @max-[560px]/home:gap-3">
            {[
              [<Est key="e" />, "We have no published boundaries for this paper yet, so grades use boundaries from past sessions."],
              ["Dashed outline", "The next grade you are working towards."],
              ["Dashed line in Your Garden", "Where a subject started, on your first paper."],
            ].map(([dt, dd], i) => (
              <div key={i} className="grid grid-cols-[minmax(7rem,max-content)_minmax(0,1fr)] gap-3 items-baseline @max-[560px]/home:grid-cols-[minmax(0,1fr)]">
                <dt className="text-(--text-body) font-bold">{dt}</dt>
                <dd className="m-0">{dd}</dd>
              </div>
            ))}
          </dl>
        </details>
      )}
      <ul className="m-0 p-1 list-none rounded-(--radius-card) bg-(--surface-card) shadow-(--a-card-edge)">
        {graded(view).map((s) => (
          <GradedRow key={s.code} s={s} state={view.state} motion={motion} />
        ))}
        {waiting(view).map((s) => (
          <WaitingRow key={s.code} s={s} view={view} />
        ))}
      </ul>
    </section>
  )
}
```

Before running, read the `Est`, `Code`, `Mono` and `Icon` signatures in `primitives.tsx` (Task 10). If `Icon` does not forward `className` to the `svg`, wrap it in a `span` that carries `GO`.

- [ ] **Step 6: Run the unit tests**

Run: `cd web && npx vitest run tests/unit/studentHomeGeometry.test.ts tests/unit/studentHomeMarkup.test.ts -t "GradesList|journeyPos|nextGrade"`
Expected: PASS. If an aria-label differs, compare it character by character with `page-a.txt` lines 425–493 and fix `gradeRowLabel`, never the expected string.

- [ ] **Step 7: Mount and register drift scenes**

Render `<GradesList view={view} />` in `StudentHome.tsx`, after the next-step row, inside the ready page. The exact place is Task 17's layout; for now put it directly under the `#sh-root` div so the scenes can find `[data-home="grades"]`, and keep the `@container/home` wrapper Task 17 specifies (`<div className="@container/home">`). If Task 17 is already done, it is already mounted there.

In `web/scripts/home-drift.mjs`, add `...overviewScenes({ part: "grades", states: OVERVIEW_STATES.filter((s) => s !== "loading" && s !== "new") })`. The new-student page and the skeleton have no grades section on either side.

- [ ] **Step 8: Run the drift gate**

Run: `cd web && node scripts/home-drift.mjs --only overview:grades`
Expected: `overview:grades PASS 120/120` (12 states × 5 widths × 2 themes).

On any FAIL: open the diff PNG it names. The usual causes are:
- a stone or marker off by a pixel: check `journeyPos` rounding (2 decimals) and the 28px stone size;
- a row height off: check the cascade rows above (1831 `padding-block 4px`, 2163 lock rows 8px);
- grade C colour: `--sh-grade-c` is overridden to `oklch(0.47 0.09 75)` / dark `oklch(0.49 0.09 75)` (`variant-a.css:1870-1871`); the token map must carry the override.

Fix and re-run until it passes. Differences the app cannot avoid (font hinting, sub-pixel anti-aliasing at a fractional `left`) must stay under 15% and get a drift-log row at Task 19.

- [ ] **Step 9: Motion check**

Open `/student/home-next` with the `populated` mocks in a normal browser (motion on). Watch the trails draw, the markers slide from the first paper and the passed stones swell once in order. Then set reduced motion in DevTools (Rendering → `prefers-reduced-motion: reduce`), reload, and confirm nothing moves.

- [ ] **Step 10: Commit**

```bash
cd web && /home/sico/Code/Lemely/.venv/bin/pre-commit run --files src/portals/student/home/states.ts src/portals/student/home/geometry.ts src/portals/student/home/GradesList.tsx src/portals/student/home/StudentHome.tsx src/index.css scripts/home-drift.mjs tests/unit/studentHomeGeometry.test.ts tests/unit/studentHomeMarkup.test.ts
git commit -S -m "feat(web): student home grades list (design A journeys)" -- web/src/portals/student/home/states.ts web/src/portals/student/home/geometry.ts web/src/portals/student/home/GradesList.tsx web/src/portals/student/home/StudentHome.tsx web/src/index.css web/scripts/home-drift.mjs web/tests/unit/studentHomeGeometry.test.ts web/tests/unit/studentHomeMarkup.test.ts
```

---

## Task 15: `PracticeTargets` (Weak topics)

**Files:**
- Create: `web/src/portals/student/home/PracticeTargets.tsx`
- Modify: `web/src/index.css` (keyframes)
- Modify: `web/src/portals/student/home/StudentHome.tsx` (mount, unless Task 17 already did)
- Modify: `web/scripts/home-drift.mjs` (register `weak`)
- Test: `web/tests/unit/studentHomeMarkup.test.ts` (append)

**Interfaces:**
- Consumes: `HomeView`, `WeakTopicView`, `DataState` (Task 8); `isManyPapers`, `isSparse` (`states.ts`, Task 14); `Code`, `Icon`, `Mono`, `useMotionOn`, `useInView` (Task 10); `overviewScenes` (Task 9).
- Produces: `export function PracticeTargets(props: { view: HomeView }): JSX.Element` (root `<section data-home="weak">`); `export function laneLabel(t: WeakTopicView, i: number, view: HomeView): string`.

**Design facts this task encodes** (`page-a.txt` 524–656, `variant-a.css` 597–680, 1680–1695, 1837–1843, 2170–2174):
- Heading: "Your first practice targets" in sparse0 and sparse1, "Weak topics" everywhere else.
- Secure note "A topic counts as **secure** at `70%` or more of its marks." and the 0/50/70 secure/100 scale are shown in every state except sparse0 (2174).
- sparse0 shows one dashed item instead of lanes: "Lemely picks these from the marks you lose on `<Mono>{upload.paperLabel}</Mono>`. They show up here the moment it is marked."
- Lanes are weakest first. The first lane is `is-top`.
- Track: the marker sits at `acc%`. When `previousAcc !== null && previousAcc !== acc`, the tail runs from `min(prev, acc)` with width `|acc − prev|`, classed `is-up` (acc > prev) or `is-down`.
- Change chip: "up N" (`is-up`, up icon) / "down N" (`is-down`, up icon rotated) when `previousAcc` is known. With no previous value: "first paper" when `view.totalPapers === 1`, else "first seen" (populated Moments; sparse2 Logarithms, whose subject has one paper but the student has four).
- When `previousAcc === acc` the design has no example. The chip says "no change", with no tail and no icon. Log it under "Copy added" at Task 19.
- "N marks to win back" (`.a-drop`).
- Practise text: `Practise {topic.toLowerCase()}` (design: "Practise quadratic inequalities").
- aria-label (verified against all 13 lanes in the markup):
  `"{topic}, {code}: "` + top prefix + body + `" Practise {topic lower}."`
  - The top prefix is "your first practice target. " in sparse0/sparse1, "your weakest topic. " otherwise. Non-top lanes get no prefix.
  - The body is one of:
    - known previous value: `"{acc}%, {up|down} {n} from {prev}%, {lost} marks to win back{S}."`;
    - `totalPapers === 1`: `"{acc}% on your first paper, {lost} marks to win back."`;
    - subject has 1 paper: `"{acc}%, first seen on your first {shortName} paper, {lost} marks to win back."`;
    - otherwise: `"{acc}%, first seen this paper, {lost} marks to win back{S}."`
  - `{S}` = `" from the last 3 papers"` in the many-papers states only. The design omits it in sparse2/sparse3 rows.
- Visible Practise link (`.a-lane-act`, under the topic name): one at a time. By default it is the top lane's. While another lane is hovered or holds focus, it is that lane's and the top one hides (`variant-a.css:619-624`). Hidden links keep their line. When the page's next action is practice (`view.action.kind === "practice"`), every `.a-lane-act` is `display: none` (617) and the end-of-row arrow `.a-lane-go` becomes the affordance (618, 376–377). This is implemented with React state (`active` lane index from pointer enter/leave and focus/blur), which matches the CSS `:has()` rules and is testable.
- Empty list outside sparse0 (no weak topics): the design has no example. Render the dashed slot with "Every topic is at `70%` or more so far. New targets show up here after your next paper." Log it under "Copy added" at Task 19; it needs the user's approval before the route switch.

### Mapping: design rule → Tailwind (effective values)

| Element | Design rule (line: declarations) | Tailwind classes |
|---|---|---|
| `section.a-sec` / `h2.a-sec-h` | as Task 14 (591, 592–595, 1226, 1439) | same strings as Task 14 |
| `p.a-sec-sub.a-secure-note` | 382 `margin: -8px 0 12px; 14px; text-secondary`; 383 mono `text-body` | `-mt-2 mb-3 text-[14px] text-(--text-secondary)`; `Mono` gets `text-(--text-body)`; `b` stays bold (UA) |
| `.a-ruler` | 599–604 `--lane-cols: 224px minmax(0,1fr) 104px 172px 18px; flex col; gap 12px; padding 20px 24px; radius-card; bg surface-card; shadow a-card-edge`; 1447 `@min 761 padding 16px 20px; radius-tile`; 1272 `@max 760 padding 16px 12px; gap 12px` | `flex flex-col gap-3 px-6 py-5 rounded-(--radius-card) bg-(--surface-card) shadow-(--a-card-edge) @min-[761px]/home:px-5 @min-[761px]/home:py-4 @min-[761px]/home:rounded-(--radius-tile) @max-[760px]/home:px-3 @max-[760px]/home:py-4` |
| `.a-scale` | 626 `grid; cols lane-cols; gap 16px; padding-inline 12px`; 1273 `@max 760 cols minmax(0,1fr); padding-inline 12px 24px` | `grid grid-cols-[224px_minmax(0,1fr)_104px_172px_18px] gap-4 px-3 @max-[760px]/home:grid-cols-[minmax(0,1fr)] @max-[760px]/home:pr-6` |
| `.a-scale-gap` | 1274 `@max 760 display none` | `@max-[760px]/home:hidden` |
| `.a-scale-axis` | 627 `grid-column 2; relative; h 16px`; 1275 `@max 760 grid-column 1` | `col-start-2 relative h-4 @max-[760px]/home:col-start-1` |
| axis `span` | 628–633 `absolute; top 0; translateX(-50%); nowrap; 600 11px/1 mono; text-muted`; first `transform none`; last `translateX(-100%)`; 634 `.is-secure` `a-success-text` | `absolute top-0 -translate-x-1/2 whitespace-nowrap font-(family-name:--font-mono) text-[11px]/none font-semibold text-(--text-muted)`; first: `translate-x-0`; last: `-translate-x-full`; secure: `text-(--a-success-text)` |
| `ul.a-lanes` | 636 `margin 0; padding 0; list-style none` | `m-0 p-0 list-none` |
| `li + li` | 637 `border-top 1px border-subtle`; 609 after `.is-top` `transparent` | `[&+li]:border-t [&+li]:border-(--border-subtle)`; the li after top adds `border-t-transparent` |
| lane `a` (desktop) | 638–643 `grid; cols lane-cols; gap 16px; align center; min-h 48px (1448 @min 761 44px); padding 4px 12px; radius-chip; text-body; no underline`; 374 transition bg fast, transform/shadow base; 375 hover `shadow-hover` (bg overridden by 646); 646 hover `bg surface-hover-tint`; 647 focus `outline-offset -2px` | `group/lane-a grid grid-cols-[224px_minmax(0,1fr)_104px_172px_18px] gap-4 items-center min-h-12 @min-[761px]/home:min-h-11 px-3 py-1 rounded-(--radius-chip) text-(--text-body) no-underline transition-[background-color,transform,box-shadow] duration-(--dur-base) hover:bg-(--surface-hover-tint) hover:shadow-(--shadow-hover) focus-visible:outline-offset-[-2px]` |
| lane `a` ≤760 | 1276–1279 `cols minmax(0,1fr) auto; areas "n n" "t t" "c d"; row-gap 4px; padding 12px 24px 12px 12px` | `@max-[760px]/home:grid-cols-[minmax(0,1fr)_auto] @max-[760px]/home:[grid-template-areas:'n_n'_'t_t'_'c_d'] @max-[760px]/home:gap-y-1 @max-[760px]/home:py-3 @max-[760px]/home:pl-3 @max-[760px]/home:pr-6` |
| lane `a` ≤560 | 1838–1840 `areas "n c" "t t"; row-gap 0; padding-block 8px`; 1842 top lane `areas "n c" "t t" "d d"` | `@max-[560px]/home:[grid-template-areas:'n_c'_'t_t'] @max-[560px]/home:gap-y-0 @max-[560px]/home:py-2`; top lane: `@max-[560px]/home:[grid-template-areas:'n_c'_'t_t'_'d_d']` |
| `li.is-top > a` | 607 `bg color-mix(primary-container 55%, transparent)`; 608 hover `bg primary-container` | `bg-[color-mix(in_oklch,var(--md-primary-container)_55%,transparent)] hover:bg-(--md-primary-container)` |
| `.a-lane-name` | 648 `flex baseline wrap gap 2px 8px min-w 0`; 649 `b 16px 700` (1443 @min 761 14px); 1280 `grid-area n` | `flex items-baseline flex-wrap gap-x-2 gap-y-0.5 min-w-0 @max-[760px]/home:[grid-area:n]`; b: `text-[16px] font-bold @min-[761px]/home:text-[14px]` |
| `.a-lane-act` | 611–614 `flex-basis 100%; inline-flex; center; gap 4px; mt 2px; nowrap; 700 14px/1.3 font-ui; primary`; 615 icon 16px transition; 616 hover icon `translateX(3px)`; 621–624 visibility/opacity, transition opacity fast, visibility delayed; 617 hidden when action is practice | `basis-full inline-flex items-center gap-1 mt-0.5 whitespace-nowrap font-(family-name:--font-ui) text-[14px]/[1.3] font-bold text-(--md-primary) transition-[opacity,visibility] duration-(--dur-fast)`; shown: `visible opacity-100`; hidden: `invisible opacity-0`; icon: `size-4 transition-transform duration-(--dur-base) group-hover/lane-a:translate-x-[3px]` |
| `.a-lane-track` | 650 `relative; h 42px`; 1281 `grid-area t` | `relative h-[42px] @max-[760px]/home:[grid-area:t]` |
| track `::before` (line) | 651–654 `absolute; inset-inline 0; top calc(72% - 2px); h 4px; pill; md-surface-highest` | a `span`: `absolute inset-x-0 top-[calc(72%-2px)] h-1 rounded-full bg-(--md-surface-highest)` |
| track `::after` (secure band) | 655–662 `absolute; top calc(72% - 11px); h 22px; inset-inline 70% 0; end radii pill; bg color-mix(success 14%, transparent); border-inline-start 2px a-success-text` | a `span`: `absolute top-[calc(72%-11px)] h-[22px] left-[70%] right-0 rounded-r-full bg-[color-mix(in_oklch,var(--md-success)_14%,transparent)] border-l-2 border-(--a-success-text) origin-left` |
| `.a-tail` | 663–666 `absolute; top calc(72% - 3px); h 6px; pill; bg color-mix(primary 35%, transparent)`; 556 up `origin left`, down `origin right` | `absolute top-[calc(72%-3px)] h-1.5 rounded-full bg-[color-mix(in_oklch,var(--md-primary)_35%,transparent)]` + `origin-left` / `origin-right` |
| `.a-marker` | 667–670 `absolute; z 1; top 72%; 16px; 50%; bg primary; shadow 0 0 0 3px surface-card; translate(-50%,-50%)` | `absolute z-[1] top-[72%] size-4 rounded-full bg-(--md-primary) shadow-[0_0_0_3px_var(--surface-card)] -translate-x-1/2 -translate-y-1/2` |
| `.a-marker-l` | 671–675 `absolute; z 1; top 72%; translate(-50%, calc(-100% - 11px)); padding 1px 4px; pill; bg surface-card; 700 14px/1.2 mono; tabular; text-body`; 610 top lane `bg transparent` | `absolute z-[1] top-[72%] translate-x-[-50%] translate-y-[calc(-100%-11px)] px-1 py-px rounded-full bg-(--surface-card) font-(family-name:--font-mono) text-[14px]/[1.2] font-bold tabular-nums text-(--text-body)`; top lane: `bg-transparent` |
| `.a-chg` | 676 `inline-flex; center; gap 4px; 600 14px/1.2 font-ui; text-secondary`; 677 up `a-success-text`; 678 icon 16px stroke 2.2; 679 down icon `rotate(180deg)`; 1282 `grid-area c` | `inline-flex items-center gap-1 font-(family-name:--font-ui) text-[14px]/[1.2] font-semibold text-(--text-secondary) @max-[760px]/home:[grid-area:c]`; up: `text-(--a-success-text)`; icon: `size-4 [stroke-width:2.2]` |
| `.a-drop` | 680 `14px 500 text-muted; text-align end; nowrap`; 1283 `grid-area d`; 1841 `@max 560 none`; 1843 top lane `block` | `text-[14px] font-medium text-(--text-muted) text-end whitespace-nowrap @max-[760px]/home:[grid-area:d] @max-[560px]/home:hidden`; top lane: `@max-[560px]/home:block` |
| `.a-lane-go` | 376 `primary; opacity 0; translateX(-4px); transition opacity, transform base`; 377 hover/focus-visible `opacity 1; transform none`; 618 hidden unless action is practice; 1270 `@max 760 none` | `text-(--md-primary) opacity-0 -translate-x-1 transition-[opacity,transform] duration-(--dur-base) group-hover/lane-a:opacity-100 group-hover/lane-a:translate-x-0 group-focus-visible/lane-a:opacity-100 group-focus-visible/lane-a:translate-x-0 @max-[760px]/home:hidden`; rendered only when `view.action.kind === "practice"` |
| `.a-lane-lock p` | 2170–2173 `margin 0; padding 12px 16px; 1.5px dashed border-default; radius-chip; text-secondary; 14px; lh 1.4` | `m-0 px-4 py-3 border-[1.5px] border-dashed border-(--border-default) rounded-(--radius-chip) text-(--text-secondary) text-[14px]/[1.4]` |

Motion (1680–1694, `useMotionOn() && inView`): the band grows from the 70% line (`rlBand .6s`). Each marker and its label race in from 0% to their score (`rlRace .9s`, delay `.35s + i·90ms`). The tail draws (`aDraw .5s`, delay `1.05s + i·90ms`). Chip and drop fade up (`rlIn .4s`, delay `1.1s + i·90ms`).

- [ ] **Step 1: Write the failing markup test (append)**

```ts
import { PracticeTargets, laneLabel } from "@/portals/student/home/PracticeTargets"

describe("PracticeTargets", () => {
  const lanes = (s: DataStateId) => {
    const v = viewOf(s)
    return v.weakTopics.map((t, i) => laneLabel(t, i, v))
  }

  it("populated: design aria-labels verbatim, weakest first", () => {
    expect(lanes("populated")).toEqual([
      "Waves, 0625: your weakest topic. 54%, up 7 from 47%, 9 marks to win back from the last 3 papers. Practise waves.",
      "Quadratic inequalities, 0606: 58%, down 3 from 61%, 6 marks to win back from the last 3 papers. Practise quadratic inequalities.",
      "Vectors, 0580: 63%, up 8 from 55%, 5 marks to win back from the last 3 papers. Practise vectors.",
      "Moments, 0625: 66%, first seen this paper, 3 marks to win back from the last 3 papers. Practise moments.",
    ])
    const out = html(createElement(PracticeTargets, { view: viewOf("populated") }))
    expect(out).toContain(">Weak topics<")
    expect(out).toContain('aria-label="Topic accuracy against the 70% secure line"')
    expect(out).toContain(">first seen<")
    expect(out).toContain("9 marks to win back")
  })

  it("one-paper and sparse1 use first-paper wording", () => {
    expect(lanes("one-paper")).toEqual([
      "Vectors, 0580: your weakest topic. 50% on your first paper, 4 marks to win back. Practise vectors.",
    ])
    expect(lanes("sparse1")).toEqual([
      "Vectors, 0580: your first practice target. 50% on your first paper, 4 marks to win back. Practise vectors.",
      "Transformations, 0580: 58% on your first paper, 3 marks to win back. Practise transformations.",
    ])
    expect(html(createElement(PracticeTargets, { view: viewOf("sparse1") }))).toContain(">Your first practice targets<")
  })

  it("sparse2 and sparse3 drop the last-3-papers suffix", () => {
    expect(lanes("sparse2")).toEqual([
      "Logarithms, 0606: your weakest topic. 48%, first seen on your first Add Maths paper, 5 marks to win back. Practise logarithms.",
      "Vectors, 0580: 52%, up 2 from 50%, 4 marks to win back. Practise vectors.",
      "Transformations, 0580: 61%, up 3 from 58%, 2 marks to win back. Practise transformations.",
    ])
    expect(lanes("sparse3")[0]).toBe(
      "Logarithms, 0606: your weakest topic. 51%, up 3 from 48%, 5 marks to win back. Practise logarithms.",
    )
  })

  it("sparse0: no scale, a dashed wait naming the paper", () => {
    const out = html(createElement(PracticeTargets, { view: viewOf("sparse0") }))
    expect(out).not.toContain("70% secure")
    expect(out).not.toContain("counts as")
    expect(out).toMatch(/marks you lose on <span[^>]*>0580\/42<\/span>\. They show up here the moment it is marked\./)
  })

  it("practice as the next action hides the inline Practise link and shows the row arrow", () => {
    const out = html(createElement(PracticeTargets, { view: viewOf("no-plan") }))
    expect(out).not.toContain('data-lane-act=""')
    expect(out).toContain('data-lane-go=""')
  })
})
```

Run: `cd web && npx vitest run tests/unit/studentHomeMarkup.test.ts -t PracticeTargets`
Expected: FAIL, module not found.

- [ ] **Step 2: Keyframes (append to the same `@theme` block as Task 14)**

```css
  --animate-home-band: home-band 600ms var(--ease-expo) both;
  --animate-home-race: home-race 900ms var(--ease-expo) both;
  --animate-home-in: home-in 400ms var(--ease-expo) both;
  @keyframes home-band { from { transform: scaleX(0) } }
  @keyframes home-race { from { inset-inline-start: 0% } }
  @keyframes home-in { from { opacity: 0; transform: translateY(4px) } }
```

The marker label's race in `variant-a.css:1691` also fades in (`opacity: 0`). Add `@keyframes home-race-l { from { inset-inline-start: 0%; opacity: 0 } }` with `--animate-home-race-l: home-race-l 900ms var(--ease-expo) both`.

- [ ] **Step 3: Implement `PracticeTargets.tsx`**

```tsx
/* Weak topics (design A .a-weak, student-home-a.html 524-656): the mastery ruler. One
 * 0-100% scale, a lane per topic, a tail from the previous value, the 70% secure band. */
import { useState, type CSSProperties } from "react"
import { Link } from "react-router-dom"
import { cn } from "@/lib/utils"
import type { HomeView, WeakTopicView } from "./facts"
import { Code, Icon, Mono, useInView, useMotionOn } from "./primitives"
import { isManyPapers } from "./states"

const COLS = "grid-cols-[224px_minmax(0,1fr)_104px_172px_18px]"
const FIRST_TARGETS = new Set(["sparse0", "sparse1"])
const SUB = "-mt-2 mb-3 text-[14px] text-(--text-secondary)"
const SLOT = "m-0 px-4 py-3 border-[1.5px] border-dashed border-(--border-default) rounded-(--radius-chip) text-(--text-secondary) text-[14px]/[1.4]"

function subjectPapers(view: HomeView, code: string): number {
  return view.subjects.find((s) => s.code === code)?.papers ?? 0
}

function chipText(t: WeakTopicView, view: HomeView): { text: string; dir: "up" | "down" | null } {
  if (t.previousAcc === null) return { text: view.totalPapers === 1 ? "first paper" : "first seen", dir: null }
  const d = t.acc - t.previousAcc
  if (d === 0) return { text: "no change", dir: null }
  return d > 0 ? { text: `up ${d}`, dir: "up" } : { text: `down ${-d}`, dir: "down" }
}

export function laneLabel(t: WeakTopicView, i: number, view: HomeView): string {
  const prefix = i === 0 ? (FIRST_TARGETS.has(view.state) ? "your first practice target. " : "your weakest topic. ") : ""
  const S = isManyPapers(view.state) ? " from the last 3 papers" : ""
  const won = `${t.lostMarks} marks to win back`
  let body: string
  if (t.previousAcc !== null) {
    const d = t.acc - t.previousAcc
    body = d === 0
      ? `${t.acc}%, no change from ${t.previousAcc}%, ${won}${S}.`
      : `${t.acc}%, ${d > 0 ? "up" : "down"} ${Math.abs(d)} from ${t.previousAcc}%, ${won}${S}.`
  } else if (view.totalPapers === 1) {
    body = `${t.acc}% on your first paper, ${won}.`
  } else if (subjectPapers(view, t.subjectCode) === 1) {
    const short = view.subjects.find((s) => s.code === t.subjectCode)?.shortName ?? t.subjectCode
    body = `${t.acc}%, first seen on your first ${short} paper, ${won}.`
  } else {
    body = `${t.acc}%, first seen this paper, ${won}${S}.`
  }
  return `${t.topic}, ${t.subjectCode}: ${prefix}${body} Practise ${t.topic.toLowerCase()}.`
}

function Lane({ t, i, view, shown, onActive, motion }: {
  t: WeakTopicView; i: number; view: HomeView; shown: boolean; onActive: (i: number | null) => void; motion: boolean
}) {
  const top = i === 0
  const chip = chipText(t, view)
  const practiseNext = view.action.kind === "practice"
  const delay = (base: number): CSSProperties | undefined => (motion ? { animationDelay: `${base + i * 90}ms` } : undefined)
  const tail = t.previousAcc !== null && t.previousAcc !== t.acc
    ? { start: Math.min(t.previousAcc, t.acc), width: Math.abs(t.acc - t.previousAcc), up: t.acc > t.previousAcc }
    : null
  return (
    <li
      className={cn("[&+li]:border-t [&+li]:border-(--border-subtle)", top && "[&+li]:border-t-transparent")}
      onPointerEnter={() => onActive(i)}
      onPointerLeave={() => onActive(null)}
      onFocus={() => onActive(i)}
      onBlur={() => onActive(null)}
    >
      <Link
        to={`/student/practice/${t.subjectCode}`}
        aria-label={laneLabel(t, i, view)}
        className={cn(
          "group/lane-a grid gap-4 items-center min-h-12 @min-[761px]/home:min-h-11 px-3 py-1 rounded-(--radius-chip) text-(--text-body) no-underline",
          COLS,
          "transition-[background-color,transform,box-shadow] duration-(--dur-base) hover:bg-(--surface-hover-tint) hover:shadow-(--shadow-hover) focus-visible:outline-offset-[-2px]",
          "@max-[760px]/home:grid-cols-[minmax(0,1fr)_auto] @max-[760px]/home:[grid-template-areas:'n_n'_'t_t'_'c_d'] @max-[760px]/home:gap-y-1 @max-[760px]/home:py-3 @max-[760px]/home:pl-3 @max-[760px]/home:pr-6",
          "@max-[560px]/home:[grid-template-areas:'n_c'_'t_t'] @max-[560px]/home:gap-y-0 @max-[560px]/home:py-2",
          top && "bg-[color-mix(in_oklch,var(--md-primary-container)_55%,transparent)] hover:bg-(--md-primary-container) @max-[560px]/home:[grid-template-areas:'n_c'_'t_t'_'d_d']",
        )}
      >
        <span className="flex items-baseline flex-wrap gap-x-2 gap-y-0.5 min-w-0 @max-[760px]/home:[grid-area:n]">
          <b className="text-[16px] font-bold @min-[761px]/home:text-[14px]">{t.topic}</b>
          <Code>{t.subjectCode}</Code>
          {!practiseNext && (
            <span
              data-lane-act=""
              aria-hidden="true"
              className={cn(
                "basis-full inline-flex items-center gap-1 mt-0.5 whitespace-nowrap font-(family-name:--font-ui) text-[14px]/[1.3] font-bold text-(--md-primary) transition-[opacity,visibility] duration-(--dur-fast)",
                shown ? "visible opacity-100" : "invisible opacity-0",
              )}
            >
              Practise {t.topic.toLowerCase()}{" "}
              <Icon name="arrow" className="size-4 transition-transform duration-(--dur-base) group-hover/lane-a:translate-x-[3px]" />
            </span>
          )}
        </span>
        <span className="relative h-[42px] @max-[760px]/home:[grid-area:t]" aria-hidden="true">
          <span className="absolute inset-x-0 top-[calc(72%-2px)] h-1 rounded-full bg-(--md-surface-highest)" />
          <span className={cn(
            "absolute top-[calc(72%-11px)] h-[22px] left-[70%] right-0 rounded-r-full bg-[color-mix(in_oklch,var(--md-success)_14%,transparent)] border-l-2 border-(--a-success-text) origin-left",
            motion && "animate-home-band",
          )} />
          {tail && (
            <span
              className={cn(
                "absolute top-[calc(72%-3px)] h-1.5 rounded-full bg-[color-mix(in_oklch,var(--md-primary)_35%,transparent)]",
                tail.up ? "origin-left" : "origin-right",
                motion && "animate-home-draw",
              )}
              style={{ insetInlineStart: `${tail.start}%`, inlineSize: `${tail.width}%`, ...delay(1050) }}
            />
          )}
          <span
            className={cn("absolute z-[1] top-[72%] size-4 rounded-full bg-(--md-primary) shadow-[0_0_0_3px_var(--surface-card)] -translate-x-1/2 -translate-y-1/2", motion && "animate-home-race")}
            style={{ insetInlineStart: `${t.acc}%`, ...delay(350) }}
          />
          <span
            className={cn(
              "absolute z-[1] top-[72%] translate-x-[-50%] translate-y-[calc(-100%-11px)] px-1 py-px rounded-full font-(family-name:--font-mono) text-[14px]/[1.2] font-bold tabular-nums text-(--text-body)",
              top ? "bg-transparent" : "bg-(--surface-card)",
              motion && "animate-home-race-l",
            )}
            style={{ insetInlineStart: `${t.acc}%`, ...delay(350) }}
          >
            {t.acc}%
          </span>
        </span>
        <span
          className={cn(
            "inline-flex items-center gap-1 font-(family-name:--font-ui) text-[14px]/[1.2] font-semibold text-(--text-secondary) @max-[760px]/home:[grid-area:c]",
            chip.dir === "up" && "text-(--a-success-text)",
            motion && "animate-home-in",
          )}
          style={delay(1100)}
        >
          {chip.dir && <Icon name="up" down={chip.dir === "down"} className="size-4 [stroke-width:2.2]" />}
          {chip.text}
        </span>
        <Mono
          className={cn(
            "text-[14px] font-medium text-(--text-muted) text-end whitespace-nowrap @max-[760px]/home:[grid-area:d] @max-[560px]/home:hidden",
            top && "@max-[560px]/home:block",
            motion && "animate-home-in",
          )}
        >
          {t.lostMarks} marks to win back
        </Mono>
        {practiseNext ? (
          <Icon
            name="arrow"
            data-lane-go=""
            className="text-(--md-primary) opacity-0 -translate-x-1 transition-[opacity,transform] duration-(--dur-base) group-hover/lane-a:opacity-100 group-hover/lane-a:translate-x-0 group-focus-visible/lane-a:opacity-100 group-focus-visible/lane-a:translate-x-0 @max-[760px]/home:hidden"
          />
        ) : (
          <span aria-hidden="true" />
        )}
      </Link>
    </li>
  )
}

export function PracticeTargets({ view }: { view: HomeView }) {
  const [active, setActive] = useState<number | null>(null)
  const motionOn = useMotionOn()
  const [ref, inView] = useInView<HTMLElement>()
  const motion = motionOn && inView
  const waitingForFirst = view.state === "sparse0"
  return (
    <section ref={ref} data-home="weak" aria-labelledby="a-weak-h" className="mt-10 @min-[761px]/home:mt-5 @max-[760px]/home:mt-8">
      <h2 id="a-weak-h" className="m-0 mb-3 font-(family-name:--font-ui) text-[21px]/[1.2] font-extrabold tracking-[-0.02em] text-(--text-body)">
        {FIRST_TARGETS.has(view.state) ? "Your first practice targets" : "Weak topics"}
      </h2>
      {!waitingForFirst && (
        <p className={SUB}>
          A topic counts as <b>secure</b> at <Mono className="text-(--text-body)">70%</Mono> or more of its marks.
        </p>
      )}
      <div className="flex flex-col gap-3 px-6 py-5 rounded-(--radius-card) bg-(--surface-card) shadow-(--a-card-edge) @min-[761px]/home:px-5 @min-[761px]/home:py-4 @min-[761px]/home:rounded-(--radius-tile) @max-[760px]/home:px-3 @max-[760px]/home:py-4">
        {!waitingForFirst && (
          <div className={cn("grid gap-4 px-3 @max-[760px]/home:grid-cols-[minmax(0,1fr)] @max-[760px]/home:pr-6", COLS)} aria-hidden="true">
            <span className="@max-[760px]/home:hidden" />
            <span className="col-start-2 relative h-4 @max-[760px]/home:col-start-1">
              {[["0%", 0, "translate-x-0"], ["50%", 50, ""], ["70% secure", 70, "text-(--a-success-text)"], ["100%", 100, "-translate-x-full"]].map(([label, at, extra]) => (
                <span
                  key={String(label)}
                  className={cn("absolute top-0 -translate-x-1/2 whitespace-nowrap font-(family-name:--font-mono) text-[11px]/none font-semibold text-(--text-muted)", extra)}
                  style={{ insetInlineStart: `${at}%` }}
                >
                  {label}
                </span>
              ))}
            </span>
          </div>
        )}
        <ul className="m-0 p-0 list-none" aria-label="Topic accuracy against the 70% secure line">
          {waitingForFirst ? (
            <li>
              <p className={SLOT}>
                Lemely picks these from the marks you lose on <Mono>{view.upload?.paperLabel ?? ""}</Mono>. They show up here the moment it is marked.
              </p>
            </li>
          ) : view.weakTopics.length === 0 ? (
            <li>
              <p className={SLOT}>
                Every topic is at <Mono>70%</Mono> or more so far. New targets show up here after your next paper.
              </p>
            </li>
          ) : (
            view.weakTopics.map((t, i) => (
              <Lane
                key={`${t.subjectCode}:${t.topic}`}
                t={t}
                i={i}
                view={view}
                shown={(active ?? 0) === i}
                onActive={setActive}
                motion={motion}
              />
            ))
          )}
        </ul>
      </div>
    </section>
  )
}
```

The axis `span`s in the markup are 0%, 50%, 70% secure, 100% in that order. The first has no transform (632), the last `translateX(-100%)` (633), and the secure one is coloured (634); the code maps them in order. Check that `Icon` forwards extra props (`data-lane-go`). If it does not, wrap it in a `span data-lane-go=""` carrying the classes.

- [ ] **Step 4: Run the unit tests**

Run: `cd web && npx vitest run tests/unit/studentHomeMarkup.test.ts -t PracticeTargets`
Expected: PASS (5 tests).

- [ ] **Step 5: Mount and register drift scenes**

Mount `<PracticeTargets view={view} />` after `GradesList` (Task 17 owns the final layout). Add `...overviewScenes({ part: "weak", states: OVERVIEW_STATES.filter((s) => s !== "loading" && s !== "new") })` to `home-drift.mjs`.

- [ ] **Step 6: Run the drift gate**

Run: `cd web && node scripts/home-drift.mjs --only overview:weak`
Expected: `overview:weak PASS 120/120`.

Likely causes of failure:
- the axis `0%` label is shifted: it must have no transform;
- the band start is off: `left-[70%]` sits on the track box, not the row;
- the top lane label background is wrong: it must be `bg-transparent`.

- [ ] **Step 7: Behaviour check in a browser**

On `/student/home-next` with `populated` mocks: hover the third lane. Only its "Practise vectors" link shows, the top lane's hides, and no row changes height. Tab through the lanes and see the same with focus. With `no-plan` mocks (action is practice): no inline links; the end arrow fades in on hover and focus. Under reduced motion nothing animates.

- [ ] **Step 8: Commit**

```bash
cd web && /home/sico/Code/Lemely/.venv/bin/pre-commit run --files src/portals/student/home/PracticeTargets.tsx src/portals/student/home/StudentHome.tsx src/index.css scripts/home-drift.mjs tests/unit/studentHomeMarkup.test.ts
git commit -S -m "feat(web): student home practice targets (design A mastery ruler)" -- web/src/portals/student/home/PracticeTargets.tsx web/src/portals/student/home/StudentHome.tsx web/src/index.css web/scripts/home-drift.mjs web/tests/unit/studentHomeMarkup.test.ts
```

---

## Task 16: `ExamsTimeline` (Exams)

**Files:**
- Create: `web/src/portals/student/home/ExamsTimeline.tsx`
- Modify: `web/src/portals/student/home/geometry.ts` (add `examPos`)
- Modify: `web/src/index.css` (keyframes)
- Modify: `web/src/portals/student/home/StudentHome.tsx` (mount, unless Task 17 already did)
- Modify: `web/scripts/home-drift.mjs` (register `exams` + `exam-pick`)
- Modify: `web/e2e/student-home.spec.ts` (append keyboard test; the file is created by Task 12)
- Test: `web/tests/unit/studentHomeGeometry.test.ts`, `web/tests/unit/studentHomeMarkup.test.ts` (append)

**Interfaces:**
- Consumes: `HomeView`, `SubjectView` (Task 8); `dayMonth`, `daysBetween`, `indefinite` (Task 8); `nextGrade` (Task 14); `isSparse` (Task 14); `ButtonLink`, `Code`, `Est`, `GradeChip`, `Icon`, `Mono`, `Vh`, `useMotionOn`, `useInView` (Task 10); `mockStudentHome`, `overviewScenes`, `APP_PATH` (Task 9); the `openHome(page, state)` helper Task 12 defines at the top of `web/e2e/student-home.spec.ts` (if Task 12 named it differently, use its name).
- Produces: `export function examPos(todayISO: string, examISO: string): number`; `export function ExamsTimeline(props: { view: HomeView }): JSX.Element | null` (root `<section data-home="exams">`, `null` when no subject has a date); `export function practiseName(s: SubjectView): string`.

**Design facts this task encodes** (`page-a.txt` 658–707, `variant-a.css` 379–441, 1456–1478, 1575–1617, 1867, 1913–1915, 2176–2189):
- Section renders only when some subject has `nextExamOn` (preview `data-needs="exams"`, hidden by `shell.css:69` when `data-exams="no"`). `StudentHome` sets `data-exams` (Task 17).
- Subtitle: `First exam: {name}, <Mono>{dayMonth}</Mono>` for the soonest dated subject (populated "Physics, 4 May"; sparse2 "Mathematics, 12 May"; one-paper "Mathematics, 12 May"). `variant-a.js` `selectExam` targets the retired `.a-xt` tiles, so in the current design the subtitle does **not** change on pick. The app keeps it static. It stays a polite live region (`aria-live="polite"`), as in the markup.
- Timeline (`aria-hidden`):
  - The "Today · `{d Mon}`" pill.
  - 24 week ticks at 4%, 8% … 96% inside `.a-xb-weeks` (which spans 0 to 14% of the track).
  - "`{Mon of today}` – Apr" at 7%, the break at 15.5%, "May" at 17%.
  - One pin per dated subject, and the fill up to the selected pin.
- **Pin position formula** (verified on all three pins): a date in May on day `d ≤ 20` sits at `17 + (d − 1) × 83/19`, so 4 May → **30.11**, 12 May → **65.05**, 18 May → **91.26**. Dates from today to 30 April squeeze into `0..15`: `15 × daysBetween(today, date) / daysBetween(today, 1 May)`. Dates after 20 May clamp to 100. The design draws May only up to the 20th; see Spec gaps.
- The design's first label reads "Nov – Apr" because today is in November. The app writes the three-letter month of today, so the drift fixtures print "Nov".
- Note under the band: "Nov to Apr is squeezed to fit. May is shown in full." (hidden ≤760, 1915). The design's copy is fixed. The app writes `{Month of today} to Apr is squeezed to fit. May is shown in full.`; in November that is the design's sentence.
- List, soonest first: dated subjects by date, then each subject with no date as a dashed `a-xs-nodate` link to `/student/profile` ("–", "no date", code, name, "Add exam date" + chev). Radios share one `name`; the first dated tile starts selected.
- Tile: `{daysBetween(today, date)}` + "days", code, full name, then the meta. Meta in the many-papers and one-paper states: date, current grade chip, arrow, next-grade chip (`a-grade-next`, from `nextGrade`), and `Est` if estimated. Meta in sparse states (2177): date, then for a subject with no paper "Marking now" (it is the subject being marked) or "No paper yet"; otherwise the current grade chip only.
- Foot: one tonal button for the selected tile.
  - If the selected subject has papers: `Practise {practiseName}` → `/student/practice/{code}`. `practiseName` is the full name when it is one word ("Physics", "Mathematics"), else the short name ("Add Maths"), matching the design's "Practise Physics / Practise Mathematics / Practise Add Maths".
  - If it has no paper and is not being marked: `Upload {a|an} {shortName} paper` → `/student/correct`.
  - If it is being marked: no button (2187 hides 0580's in sparse0).
- **Known design quirk, sparse2:** the preview's checked radio is Physics, but Physics' dated tile is hidden in sparse2 (Physics has no date). So the preview shows no selected tile, fills to 30.11% with no pin, and shows "Upload a Physics paper". The app selects the first visible dated tile (Mathematics): tinted, fill 65.05%, "Practise Mathematics". This drift is expected and below 15% of the section's pixels. At Task 19 it goes in the drift log as "preview bug: hidden radio selected" for the user to approve.

### Mapping: design rule → Tailwind (effective values)

| Element | Design rule (line: declarations) | Tailwind classes |
|---|---|---|
| `section.a-sec` / `h2.a-sec-h` | as Task 14 | same strings |
| `p.a-sec-sub#a-exams-sub` | 382–383 | `-mt-2 mb-3 text-[14px] text-(--text-secondary)`; `Mono` `text-(--text-body)` |
| `.a-xcard.a-xs-card` | 384–387 xcard `padding 20px 24px 24px; radius-card` (1450 @min 761 16/20/20 radius-tile; 1240 @max 760 20px 16px); 1458 `.a-xs-card` (later, same specificity) `padding 16px 20px; radius-tile; bg surface-card; shadow a-card-edge` wins at every width | `px-5 py-4 rounded-(--radius-tile) bg-(--surface-card) shadow-(--a-card-edge)` |
| `.a-xb` | 388 `relative; h 64; mt 12px`; 1472 `.a-xs-card > .a-xb` `margin-block 0 12px`; 1241 `@max 760 display none` | `relative h-16 mt-0 mb-3 @max-[760px]/home:hidden` |
| `.a-xb-today` | 389–394 `absolute; bottom calc(100% - 14px); left 0; padding 4px 10px; pill; 700 11px/1.2 font-ui; nowrap`; 1867 `bg primary; color on-primary` (wins over 392); 395 mono `600` | `absolute bottom-[calc(100%-14px)] left-0 px-2.5 py-1 rounded-full bg-(--md-primary) text-(--md-on-primary) font-(family-name:--font-ui) text-[11px]/[1.2] font-bold whitespace-nowrap`; mono: `font-semibold` |
| `.a-xb-track` | 396–399 `absolute; inset-inline 0; top 20px; h 14px; overflow hidden; pill; bg primary-container` | `absolute inset-x-0 top-5 h-3.5 overflow-hidden rounded-full bg-(--md-primary-container)` |
| `.a-xb-weeks` / `i` | 400–403 `absolute; inset-block 3px; inset-inline 0 86%` / `absolute; inset-block 0; w 1px; bg color-mix(on-primary-container 30%, transparent)` | `absolute inset-y-[3px] left-0 right-[86%]` / `absolute inset-y-0 w-px bg-[color-mix(in_oklch,var(--md-on-primary-container)_30%,transparent)]` |
| `.a-xb-fill` | 404–408 `absolute; inset-block 0; left 0; width (selected pin); radius inherit; bg color-mix(primary 40%, primary-container); origin left`; 1578 `transition width slow expo` | `absolute inset-y-0 left-0 rounded-[inherit] bg-[color-mix(in_oklch,var(--md-primary)_40%,var(--md-primary-container))] origin-left transition-[width] duration-(--dur-slow) ease-(--a-ease-expo)` + inline `width` |
| `.a-xb-m` | 410–414 `absolute; top 42px; translateX(-50%); 600 11px/1 mono; ls .04em; text-muted`; `.is-may` `transform none; text-body; 800` | `absolute top-[42px] -translate-x-1/2 font-(family-name:--font-mono) text-[11px]/none font-semibold tracking-[0.04em] text-(--text-muted)`; May: `translate-x-0 text-(--text-body) font-extrabold` |
| `.a-xb-break` + `::before/::after` | 415–424 `absolute; top 18px; 14×18px; translateX(-50%); bg surface-card`; strokes `absolute; top 1px; 2×16px; pill; bg text-muted; rotate(22deg); left 3px / 9px` | `absolute top-[18px] w-3.5 h-[18px] -translate-x-1/2 bg-(--surface-card)` with two child spans `absolute top-px w-0.5 h-4 rounded-full bg-(--text-muted) rotate-[22deg]` at `left-[3px]` / `left-[9px]` |
| `.a-xb-pin` | 425 `absolute; top 20px; w 0` | `absolute top-5 w-0` |
| pin dot (`::before`) | 426–429 `absolute; top 1px; left -6px; 12px; 50%; bg surface-card; inset 0 0 0 3px primary`; selected 1589 `bg primary; shadow 0 0 0 3px surface-card; scale 1.25`; 1579 transition bg fast, scale base | span `absolute top-px -left-1.5 size-3 rounded-full transition-[background-color,scale] duration-(--dur-base)`; idle: `bg-(--surface-card) shadow-[inset_0_0_0_3px_var(--md-primary)]`; selected: `bg-(--md-primary) shadow-[0_0_0_3px_var(--surface-card)] scale-125` |
| `.a-xb-stem` | 430–433 `absolute; top 14px; left -1px; 2×36px; bg border-default; origin top`; selected `bg primary` | `absolute top-3.5 -left-px w-0.5 h-9 origin-top bg-(--border-default)`; selected `bg-(--md-primary)` |
| `.a-xb-code` | 436–440 `absolute; top 36px; left 6px; nowrap; 600 11px/1 mono; ls .04em; tabular; text-muted`; selected `primary; 800` | `absolute top-9 left-1.5 whitespace-nowrap font-(family-name:--font-mono) text-[11px]/none font-semibold tracking-[0.04em] tabular-nums text-(--text-muted)`; selected `text-(--md-primary) font-extrabold` |
| `p.a-xb-note` | 1914–1915 `margin 0 0 12px; 14px; text-secondary; @max 760 none` | `m-0 mb-3 text-[14px] text-(--text-secondary) @max-[760px]/home:hidden` |
| `ol.a-xs-list` | 1459 `list-style none; margin 0; padding 0; grid; 3 cols minmax(0,1fr); gap 8px`; 1475 `@max 760 1 col` | `group/xs list-none m-0 p-0 grid grid-cols-3 gap-2 @max-[760px]/home:grid-cols-1` |
| `.a-xs-item` | 1460 `grid; cols auto 1fr; rows auto auto; column-gap 12px; row-gap 4px; center; padding 12px 16px; radius-chip`; 1581 `cursor pointer; transitions opacity base, bg fast, color fast, translate base expo`; 1582 checked `bg primary-container; color on-primary-container`; 1583 focus `outline 2px primary offset 2px`; 1584 others dim `.65` while one hovers; 1585 hover `translate 0 -2px`; 1586 hover unchecked `bg surface-row` | `grid grid-cols-[auto_1fr] grid-rows-[auto_auto] gap-x-3 gap-y-1 items-center px-4 py-3 rounded-(--radius-chip) cursor-pointer transition-[opacity,background-color,color,translate] duration-(--dur-base) group-has-[li:hover]/xs:opacity-65 group-hover/li:opacity-100 group-hover/li:-translate-y-0.5 peer-checked:bg-(--md-primary-container) peer-checked:text-(--md-on-primary-container) peer-focus-visible:outline-2 peer-focus-visible:outline-(--md-primary) peer-focus-visible:outline-offset-2 peer-[:not(:checked)]:group-hover/li:bg-(--surface-row)` |
| `.a-xs-days` / `.a-xs-n` / `.a-xs-u` | 1462 `row 1/3; flex col; center; min-w 56px` / 1463 `800 32px/1 display; ls -.04em; tabular lining` / 1464 `600 11px/1.4 mono; ls .08em; uppercase; text-secondary` | `row-span-2 flex flex-col items-center min-w-14` / `font-(family-name:--font-display) text-[32px]/none font-extrabold tracking-[-0.04em] tabular-nums lining-nums` / `font-(family-name:--font-mono) text-[11px]/[1.4] font-semibold tracking-[0.08em] uppercase text-(--text-secondary)` |
| `.a-xs-name` / `b` | 1466–1467 `flex; baseline; gap 6px; 700; 14px; min-w 0` / `truncate; 700` | `flex items-baseline gap-1.5 font-bold text-[14px] min-w-0` / `truncate font-bold` |
| `.a-xs-meta` | 1468 `flex; center; wrap; gap 6px; 14px; text-secondary`; 1470 icon `14px; text-muted` | `flex items-center flex-wrap gap-1.5 text-[14px] text-(--text-secondary)`; icon `size-3.5 text-(--text-muted)` |
| `.a-grade-chip` / `.a-grade-next` | 473–485 `inline-grid; center; 34×32; radius 10px; 800 21px/1 font-ui; ls -.01em`; chip `white on grade colour`; next `text-body; bg surface-card; outline 2px dashed grade; offset -2px` | `GradeChip kind="chip"` / `GradeChip kind="next"` (Task 10 implements exactly these rules) |
| `.a-xs-wait` | 2178 `600 14px/1.3 font-ui; text-secondary`; 2179 checked `inherit` | `font-(family-name:--font-ui) text-[14px]/[1.3] font-semibold text-(--text-secondary) group-[:is(:checked)+*]:...` (use `[.peer:checked+*_&]:text-inherit`) |
| `.a-xs-nodate .a-xs-item` | 2180–2183 `text-body; no underline; outline 1.5px dashed border-default; offset -1.5px; hover outline primary`; n `text-muted`; wait `primary 700` | `text-(--text-body) no-underline outline-[1.5px] outline-dashed outline-(--border-default) -outline-offset-[1.5px] hover:outline-(--md-primary)`; n: `text-(--text-muted)`; wait: `text-(--md-primary) font-bold` |
| `.a-xs-foot` / `.a-xs-act` | 1471 `flex; justify end; mt 12px`; 1476 `@max 760 wrap`; 1473 `flex none; nowrap`; 587 tonal | `flex justify-end mt-3 @max-[760px]/home:flex-wrap` / `ButtonLink variant="tonal" className="flex-none whitespace-nowrap"` |

Motion (562–566, `useMotionOn() && inView`): the fill draws (`home-draw 500ms`, 100ms delay). The weeks fade (`home-fade` `dur-base`, 150ms). Stems drop (`home-drop`, `80ms × i + 300ms`). The day counts are final from the first frame.

- [ ] **Step 1: Failing geometry test (append to `studentHomeGeometry.test.ts`)**

```ts
import { examPos } from "@/portals/student/home/geometry"

describe("examPos: pins in student-home-a.html", () => {
  it.each([
    ["2027-05-04", 30.11], ["2027-05-12", 65.05], ["2027-05-18", 91.26], ["2027-05-01", 17], ["2027-05-20", 100],
  ] as const)("%s → %d", (date, expected) => {
    expect(examPos("2026-11-05", date)).toBe(expected)
  })

  it("squeezes Nov–Apr into 0..15 and clamps after 20 May", () => {
    expect(examPos("2026-11-05", "2026-11-05")).toBe(0)
    expect(examPos("2026-11-05", "2027-04-30")).toBeLessThan(15)
    expect(examPos("2026-11-05", "2027-06-10")).toBe(100)
  })
})
```

Run: `cd web && npx vitest run tests/unit/studentHomeGeometry.test.ts -t examPos`
Expected: FAIL (`examPos` is not exported).

- [ ] **Step 2: Implement `examPos`**

Append to `geometry.ts`:

```ts
import { daysBetween } from "./format"

const MAY_START = 17 // "May" label and 1 May (.a-xb-m.is-may inset-inline-start)
const MAY_DAYS_SHOWN = 19 // 1 May → 17%, 20 May → 100%
const SQUEEZE_END = 15 // Nov–Apr ends before the break at 15.5%

/** Exam date → percent of the timeline (.a-xb-pin inset-inline-start). */
export function examPos(todayISO: string, examISO: string): number {
  const [, m, d] = examISO.split("-").map(Number)
  if (m === 5) return round2(Math.min(100, MAY_START + ((d - 1) * (100 - MAY_START)) / MAY_DAYS_SHOWN))
  // The May the band zooms on is the next one on or after today (today in Nov → next year's May).
  const [ty, tm] = todayISO.split("-").map(Number)
  const may1 = `${tm >= 6 ? ty + 1 : ty}-05-01`
  if (examISO > may1) return 100
  const span = daysBetween(todayISO, may1)
  return round2(span > 0 ? (SQUEEZE_END * Math.max(0, daysBetween(todayISO, examISO))) / span : 0)
}
```

(`round2` is already in the file. Move the `daysBetween` import to the top with the others.)

Run: `cd web && npx vitest run tests/unit/studentHomeGeometry.test.ts`
Expected: PASS.

- [ ] **Step 3: Failing markup test (append to `studentHomeMarkup.test.ts`)**

```ts
import { ExamsTimeline, practiseName } from "@/portals/student/home/ExamsTimeline"

describe("ExamsTimeline", () => {
  it("populated: soonest first, days, chips, Physics selected, its Practise button", () => {
    const v = viewOf("populated")
    const out = html(createElement(ExamsTimeline, { view: v }))
    expect(out).toMatch(/First exam: Physics, <span[^>]*>4 May<\/span>/)
    expect(out).toContain('aria-label="Your exams, soonest first"')
    expect(out).toMatch(/180<\/span>.*188<\/span>.*194<\/span>/s)
    expect(out).toContain("Nov to Apr is squeezed to fit. May is shown in full.")
    expect(out).toContain(">Practise Physics")
    expect(out).not.toContain(">Practise Mathematics")
    expect(out).toMatch(/value="0625"[^>]*checked/)
    expect(out).toContain("width:30.11%")
  })

  it("no-exams renders nothing", () => {
    expect(html(createElement(ExamsTimeline, { view: viewOf("no-exams") }))).toBe("")
  })

  it("sparse0: wait labels instead of chips, upload the first unplanted subject", () => {
    const out = html(createElement(ExamsTimeline, { view: viewOf("sparse0") }))
    expect(out).toContain("Marking now")
    expect(out).toContain("No paper yet")
    expect(out).not.toContain('data-grade="')
    expect(out).toContain(">Upload a Physics paper")
  })

  it("sparse2: Physics without a date asks for one; first exam is Mathematics", () => {
    const out = html(createElement(ExamsTimeline, { view: viewOf("sparse2") }))
    expect(out).toMatch(/First exam: Mathematics, <span[^>]*>12 May<\/span>/)
    expect(out).toContain('href="/student/profile"')
    expect(out).toContain("Add exam date")
    expect(out).toContain("no date")
  })

  it("practiseName follows the design's button copy", () => {
    const v = viewOf("populated")
    expect(v.subjects.map(practiseName)).toEqual(["Mathematics", "Add Maths", "Physics"])
  })
})
```

Run: `cd web && npx vitest run tests/unit/studentHomeMarkup.test.ts -t ExamsTimeline`
Expected: FAIL, module not found.

- [ ] **Step 4: Keyframes (append to the same `@theme` block)**

```css
  --animate-home-fade: home-fade 200ms var(--ease-out) both;
  --animate-home-drop: home-drop 200ms var(--ease-expo) both;
  @keyframes home-fade { from { opacity: 0 } }
  @keyframes home-drop { from { transform: scaleY(0) } }
```

- [ ] **Step 5: Implement `ExamsTimeline.tsx`**

```tsx
/* Exams (design A .a-exams, student-home-a.html 658-707): a band from Today (Nov to Apr
 * squeezed, May in full), a pin per dated exam, and a radio strip of countdown rows. */
import { useId, useState, type CSSProperties } from "react"
import { Link } from "react-router-dom"
import { cn } from "@/lib/utils"
import { localISODate } from "./model"
import type { HomeView, SubjectView } from "./facts"
import { dayMonth, daysBetween, indefinite } from "./format"
import { examPos, nextGrade } from "./geometry"
import { ButtonLink, Code, Est, GradeChip, Icon, Mono, Vh, useInView, useMotionOn } from "./primitives"
import { isSparse } from "./states"

const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
const MONTH = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
const ITEM = cn(
  "grid grid-cols-[auto_1fr] grid-rows-[auto_auto] gap-x-3 gap-y-1 items-center px-4 py-3 rounded-(--radius-chip) cursor-pointer",
  "transition-[opacity,background-color,color,translate] duration-(--dur-base)",
  "group-has-[li:hover]/xs:opacity-65 group-hover/li:opacity-100 group-hover/li:-translate-y-0.5",
)
const DAYS_N = "font-(family-name:--font-display) text-[32px]/none font-extrabold tracking-[-0.04em] tabular-nums lining-nums"
const DAYS_U = "font-(family-name:--font-mono) text-[11px]/[1.4] font-semibold tracking-[0.08em] uppercase text-(--text-secondary)"
const WAIT = "font-(family-name:--font-ui) text-[14px]/[1.3] font-semibold text-(--text-secondary) [.peer:checked+*_&]:text-inherit"

export function practiseName(s: SubjectView): string {
  return s.name.includes(" ") ? s.shortName : s.name
}

function Meta({ s, view }: { s: SubjectView; view: HomeView }) {
  const marking = view.upload?.subjectCode === s.code
  const sparse = isSparse(view.state)
  const next = s.pct !== null && s.boundaries ? nextGrade(s.pct, s.boundaries) : null
  return (
    <span className="flex items-center flex-wrap gap-1.5 text-[14px] text-(--text-secondary)">
      <Mono>{dayMonth(s.nextExamOn!)}</Mono>
      {s.papers === 0 ? (
        <span className={WAIT}>{marking ? "Marking now" : "No paper yet"}</span>
      ) : (
        <>
          <GradeChip grade={s.grade} kind="chip" />
          {!sparse && next && (
            <>
              <Icon name="arrow" className="size-3.5 text-(--text-muted)" />
              <GradeChip grade={next} kind="next" />
            </>
          )}
          {!sparse && s.boundariesEstimated && <Est />}
        </>
      )}
    </span>
  )
}

export function ExamsTimeline({ view }: { view: HomeView }) {
  const today = localISODate(view.facts.now)
  const dated = view.subjects
    .filter((s) => s.nextExamOn !== null)
    .sort((a, b) => a.nextExamOn!.localeCompare(b.nextExamOn!) || a.code.localeCompare(b.code))
  const undated = view.subjects.filter((s) => s.nextExamOn === null).sort((a, b) => a.code.localeCompare(b.code))
  const [picked, setPicked] = useState<string | null>(null)
  const name = useId()
  const motionOn = useMotionOn()
  const [ref, inView] = useInView<HTMLElement>()
  const motion = motionOn && inView
  if (dated.length === 0) return null

  const selected = dated.find((s) => s.code === picked) ?? dated[0]
  const first = dated[0]
  const monthNow = view.facts.now.getMonth()
  const action =
    selected.papers > 0
      ? { to: `/student/practice/${selected.code}`, label: `Practise ${practiseName(selected)}` }
      : view.upload?.subjectCode === selected.code
        ? null
        : { to: "/student/correct", label: `Upload ${indefinite(selected.shortName)} ${selected.shortName} paper` }

  return (
    <section ref={ref} data-home="exams" aria-labelledby="a-exams-h" className="mt-10 @min-[761px]/home:mt-5 @max-[760px]/home:mt-8">
      <h2 id="a-exams-h" className="m-0 mb-3 font-(family-name:--font-ui) text-[21px]/[1.2] font-extrabold tracking-[-0.02em] text-(--text-body)">
        Exams
      </h2>
      <p id="a-exams-sub" aria-live="polite" className="-mt-2 mb-3 text-[14px] text-(--text-secondary)">
        First exam: {first.name}, <Mono className="text-(--text-body)">{dayMonth(first.nextExamOn!)}</Mono>
      </p>
      <div className="px-5 py-4 rounded-(--radius-tile) bg-(--surface-card) shadow-(--a-card-edge)">
        <div className="relative h-16 mt-0 mb-3 @max-[760px]/home:hidden" aria-hidden="true">
          <span className="absolute bottom-[calc(100%-14px)] left-0 px-2.5 py-1 rounded-full bg-(--md-primary) text-(--md-on-primary) font-(family-name:--font-ui) text-[11px]/[1.2] font-bold whitespace-nowrap">
            Today · <Mono className="font-semibold">{dayMonth(today)}</Mono>
          </span>
          <span className="absolute inset-x-0 top-5 h-3.5 overflow-hidden rounded-full bg-(--md-primary-container)">
            <span className={cn("absolute inset-y-[3px] left-0 right-[86%]", motion && "animate-home-fade [animation-delay:150ms]")}>
              {Array.from({ length: 24 }, (_, i) => (
                <i
                  key={i}
                  className="absolute inset-y-0 w-px bg-[color-mix(in_oklch,var(--md-on-primary-container)_30%,transparent)]"
                  style={{ insetInlineStart: `${((i + 1) * 4).toFixed(1)}%` }}
                />
              ))}
            </span>
            <span
              className={cn(
                "absolute inset-y-0 left-0 rounded-[inherit] origin-left bg-[color-mix(in_oklch,var(--md-primary)_40%,var(--md-primary-container))] transition-[width] duration-(--dur-slow) ease-(--a-ease-expo)",
                motion && "animate-home-draw [animation-delay:100ms]",
              )}
              style={{ width: `${examPos(today, selected.nextExamOn!)}%` }}
            />
          </span>
          <span className="absolute top-[42px] -translate-x-1/2 font-(family-name:--font-mono) text-[11px]/none font-semibold tracking-[0.04em] text-(--text-muted)" style={{ insetInlineStart: "7%" }}>
            {MON[monthNow]} – Apr
          </span>
          <span className="absolute top-[18px] w-3.5 h-[18px] -translate-x-1/2 bg-(--surface-card)" style={{ insetInlineStart: "15.5%" }}>
            <span className="absolute top-px left-[3px] w-0.5 h-4 rounded-full bg-(--text-muted) rotate-[22deg]" />
            <span className="absolute top-px left-[9px] w-0.5 h-4 rounded-full bg-(--text-muted) rotate-[22deg]" />
          </span>
          <span className="absolute top-[42px] translate-x-0 font-(family-name:--font-mono) text-[11px]/none font-extrabold tracking-[0.04em] text-(--text-body)" style={{ insetInlineStart: "17%" }}>
            May
          </span>
          {dated.map((s, i) => {
            const sel = s.code === selected.code
            return (
              <span key={s.code} data-exam={s.code} className="absolute top-5 w-0" style={{ insetInlineStart: `${examPos(today, s.nextExamOn!)}%` }}>
                <span className={cn(
                  "absolute top-px -left-1.5 size-3 rounded-full transition-[background-color,scale] duration-(--dur-base)",
                  sel ? "bg-(--md-primary) shadow-[0_0_0_3px_var(--surface-card)] scale-125" : "bg-(--surface-card) shadow-[inset_0_0_0_3px_var(--md-primary)]",
                )} />
                <span
                  className={cn("absolute top-3.5 -left-px w-0.5 h-9 origin-top transition-colors duration-(--dur-fast)", sel ? "bg-(--md-primary)" : "bg-(--border-default)", motion && "animate-home-drop")}
                  style={motion ? ({ animationDelay: `${i * 80 + 300}ms` } as CSSProperties) : undefined}
                />
                <span className={cn(
                  "absolute top-9 left-1.5 whitespace-nowrap font-(family-name:--font-mono) text-[11px]/none tracking-[0.04em] tabular-nums transition-colors duration-(--dur-fast)",
                  sel ? "text-(--md-primary) font-extrabold" : "text-(--text-muted) font-semibold",
                )}>
                  {s.code}
                </span>
              </span>
            )
          })}
        </div>
        <p className="m-0 mb-3 text-[14px] text-(--text-secondary) @max-[760px]/home:hidden">
          {MONTH[monthNow].slice(0, 3)} to Apr is squeezed to fit. May is shown in full.
        </p>
        <ol className="group/xs list-none m-0 p-0 grid grid-cols-3 gap-2 @max-[760px]/home:grid-cols-1" aria-label="Your exams, soonest first">
          {dated.map((s) => {
            const id = `${name}-${s.code}`
            return (
              <li key={s.code} data-x={s.code} className="group/li">
                <input
                  className="peer sr-only"
                  type="radio"
                  name={name}
                  id={id}
                  value={s.code}
                  checked={s.code === selected.code}
                  onChange={() => setPicked(s.code)}
                />
                <label
                  htmlFor={id}
                  className={cn(
                    ITEM,
                    "peer-checked:bg-(--md-primary-container) peer-checked:text-(--md-on-primary-container)",
                    "peer-focus-visible:outline-2 peer-focus-visible:outline-(--md-primary) peer-focus-visible:outline-offset-2",
                    "peer-[:not(:checked)]:group-hover/li:bg-(--surface-row)",
                  )}
                >
                  <span className="row-span-2 flex flex-col items-center min-w-14">
                    <span className={DAYS_N}>{daysBetween(today, s.nextExamOn!)}</span>
                    <span className={DAYS_U}>days</span>
                  </span>
                  <span className="flex items-baseline gap-1.5 font-bold text-[14px] min-w-0">
                    <Code>{s.code}</Code>
                    <b className="truncate font-bold">{s.name}</b>
                  </span>
                  <Meta s={s} view={view} />
                </label>
              </li>
            )
          })}
          {undated.map((s) => (
            <li key={s.code} className="group/li">
              <Link
                to="/student/profile"
                className={cn(ITEM, "text-(--text-body) no-underline outline-[1.5px] outline-dashed outline-(--border-default) -outline-offset-[1.5px] hover:outline-(--md-primary)")}
              >
                <span className="row-span-2 flex flex-col items-center min-w-14">
                  <span className={cn(DAYS_N, "text-(--text-muted)")} aria-hidden="true">–</span>
                  <span className={DAYS_U}>no date</span>
                </span>
                <span className="flex items-baseline gap-1.5 font-bold text-[14px] min-w-0">
                  <Code>{s.code}</Code>
                  <b className="truncate font-bold">{s.name}</b>
                </span>
                <span className="flex items-center flex-wrap gap-1.5 text-[14px] text-(--text-secondary)">
                  <span className="font-(family-name:--font-ui) text-[14px]/[1.3] font-bold text-(--md-primary)">Add exam date</span>
                  <Icon name="chev" className="size-3.5 text-(--text-muted)" />
                </span>
              </Link>
            </li>
          ))}
        </ol>
        {action && (
          <div className="flex justify-end mt-3 @max-[760px]/home:flex-wrap">
            <ButtonLink variant="tonal" to={action.to} className="flex-none whitespace-nowrap">
              {action.label} <Icon name="arrow" />
            </ButtonLink>
          </div>
        )}
      </div>
    </section>
  )
}
```

`sr-only` must render exactly like the design's `.a-vh` (both take the input out of layout). If Task 10's `Vh` exposes a class name for this (e.g. `VH_CLASS`), use it instead of `sr-only` and drop the unused `Vh` import. Check that the `GradeChip` from Task 10 emits `data-grade`; the sparse0 test relies on there being none rendered. The week ticks' `toFixed(1)` matches the markup's `4.0%` steps.

- [ ] **Step 6: Run the unit tests**

Run: `cd web && npx vitest run tests/unit/studentHomeGeometry.test.ts tests/unit/studentHomeMarkup.test.ts -t "examPos|ExamsTimeline"`
Expected: PASS.

- [ ] **Step 7: Keyboard test (append to `web/e2e/student-home.spec.ts`)**

```ts
test.describe("exam strip radios", () => {
  test("arrow keys move the selection; fill, pin and action follow", async ({ page }) => {
    await openHome(page, "populated")
    const exams = page.locator('[data-home="exams"]')
    const physics = exams.locator('input[value="0625"]')
    const maths = exams.locator('input[value="0580"]')
    await expect(physics).toBeChecked()
    await physics.focus()
    await page.keyboard.press("ArrowRight")
    await expect(maths).toBeChecked()
    await expect(maths).toBeFocused()
    await expect(exams.getByRole("link", { name: /Practise Mathematics/ })).toBeVisible()
    await expect(exams.getByRole("link", { name: /Practise Physics/ })).toHaveCount(0)
    await expect(exams.locator('[data-exam="0580"] span').first()).toHaveClass(/scale-125/)
    await page.keyboard.press("ArrowRight")
    await expect(exams.locator('input[value="0606"]')).toBeChecked()
    await expect(exams.getByRole("link", { name: /Practise Add Maths/ })).toBeVisible()
  })

  test("the no-date tile is a link to the profile", async ({ page }) => {
    await openHome(page, "sparse2")
    await expect(page.locator('[data-home="exams"]').getByRole("link", { name: /Add exam date/ })).toHaveAttribute("href", "/student/profile")
  })
})
```

Run: `cd web && npx playwright test e2e/student-home.spec.ts -g "exam strip radios" --project=chromium`
Expected: `2 passed`. (Use the project name `playwright.config.ts` defines for desktop Chromium; `npx playwright test --list` shows it.)

- [ ] **Step 8: Mount and register drift scenes**

Mount `<ExamsTimeline view={view} />` after `PracticeTargets`. In `web/scripts/home-drift/overview.mjs`, export the interaction (Task 20 reuses it on the page part):

```js
export const EXAM_PICK = {
  id: "exam-pick",
  state: "populated",
  preview: async (page) => { await page.locator('label[for="xs-many-0580"]').click() },
  app: async (page) => { await page.locator('[data-home="exams"] input[value="0580"]').check({ force: true }) },
}
```

In `home-drift.mjs`:

```js
...overviewScenes({
  part: "exams",
  states: OVERVIEW_STATES.filter((s) => !["loading", "new", "no-exams"].includes(s)),
  interactions: [EXAM_PICK],
}),
```

Before capturing, move the pointer off the strip on both sides (`page.mouse.move(0, 0)`), so the hover dim (1584) is not in the image.

- [ ] **Step 9: Run the drift gate**

Run: `cd web && node scripts/home-drift.mjs --only overview:exams`
Expected: `overview:exams FAIL 110/120` **only** for the 10 `sparse2` scenes (5 widths × 2 themes). Those differ because of the design quirk described above. Every other scene, including the 10 `exam-pick` scenes, passes. For each sparse2 diff, confirm the differing pixels are only the selected-tile tint, the fill length, the 0580 pin and the foot button, and that the percent is ≤ 15%. Write one drift-log row in the spec ("`overview:exams:sparse2:*` | preview selects the hidden Physics radio; app selects Mathematics | n% | design bug: no visible selection in the preview | pending") and ask the user to approve it at Task 19. Anything else that fails gets fixed and re-run.

At ≤760 the band and note are hidden, so mobile diffs come from the list only. Check the `grid-cols-1` switch and the item padding.

- [ ] **Step 10: Motion check**

Motion on, `populated` mocks: the band fills from Today to Physics, the weeks fade in, the stems drop in date order, and the day counts never count. Pick Mathematics: the fill grows to 65.05% over 350ms. Under reduced motion the pick changes instantly and nothing animates on load.

- [ ] **Step 11: Commit**

```bash
cd web && /home/sico/Code/Lemely/.venv/bin/pre-commit run --files src/portals/student/home/ExamsTimeline.tsx src/portals/student/home/geometry.ts src/portals/student/home/StudentHome.tsx src/index.css scripts/home-drift.mjs e2e/student-home.spec.ts tests/unit/studentHomeGeometry.test.ts tests/unit/studentHomeMarkup.test.ts ../docs/superpowers/specs/2026-11-06-student-home-overview-design.md
git commit -S -m "feat(web): student home exams timeline and countdown strip" -- web/src/portals/student/home/ExamsTimeline.tsx web/src/portals/student/home/geometry.ts web/src/portals/student/home/StudentHome.tsx web/src/index.css web/scripts/home-drift.mjs web/e2e/student-home.spec.ts web/tests/unit/studentHomeGeometry.test.ts web/tests/unit/studentHomeMarkup.test.ts docs/superpowers/specs/2026-11-06-student-home-overview-design.md
```

---

---

## Task 17: `HomeSkeleton` and `HomeError`

**Files:**
- Create: `web/src/portals/student/home/HomeSkeleton.tsx`
- Create: `web/src/portals/student/home/HomeError.tsx`
- Modify: `web/src/portals/student/home/StudentHome.tsx` (temporary mount, replaced in Task 18)
- Modify: `web/scripts/home-drift.mjs` (register `skeleton` and `error`)
- Test: `web/tests/unit/studentHomeMarkup.test.ts` (append)

**Interfaces:**
- Consumes: `clockTime` (`format.ts`); `Mono`, `buttonClass`, `useMotionOn` (Task 10).
- Produces:
  - `HomeSkeleton(): JSX.Element`: root `<section data-home="skeleton" aria-busy="true" aria-label="Loading your overview">`.
  - `HomeError(props: { stale: { at: number } | null; message?: string; onRetry: () => void }): JSX.Element`: root `<section data-home="error" aria-label="Refresh status">` containing a `role="status"` banner.
    - `stale !== null` is the design's banner over the last-known page.
    - `stale === null` with `message` is the case with no cached data: no page underneath, the text is `studentLoadFailureMessage` (spec §3).

The case with no cached data has no design. It reuses the `.a-error` banner unchanged, with title "Couldn't load your overview." (the old Overview's wording, which `web/e2e/screenshots.spec.ts` already expects) and the failure message. No drift pair covers it: the preview has no such state, so nothing is logged. The reasons for reusing the banner: the design already has a status banner with a retry, a second error style would be a new design element, and the spec names `HomeError` as the error banner for both triggers.

### Mapping

| Element / design selector | Declarations (variant-a.css) | Tailwind |
|---|---|---|
| section `.a-page.a-error-wrap` | `.as-main .a-page` padding 0 :753; error `padding-block-end 0` :1769 | (no classes) |
| `.a-error` | :704-709 `flex; wrap; center; gap 12px 20px; padding 12px 20px; radius card; bg primary-container; card-edge shadow; color on-primary-container`; :1770 `margin-bottom 16` | `flex flex-wrap items-center gap-x-5 gap-y-3 py-3 px-5 rounded-card bg-primary-container [box-shadow:var(--home-card-edge)] text-on-primary-container mb-4` |
| `.a-error-text` | :710 `flex 1 1 280px; margin 0; 14px; line-height 1.45` | `flex-[1_1_280px] m-0 text-home-sm leading-[1.45]` |
| `.a-error-title` | :711 `800` | `font-extrabold` |
| `.a-error-retry` | `.a-btn .a-btn-primary` + :712 `flex none` | `buttonClass("primary")` + `flex-none` |
| skeleton section | `.a-page`, padding 0 in the shell :753 | (no classes) |
| `.a-skel` | :716 `radius tile; bg md-surface-high`; :717 pulse 1.4s alternate under motion | `rounded-tile bg-surface-container-high` + motion `animate-[home-pulse_1.4s_ease-in-out_infinite_alternate]` |
| `.a-sk-card` | :1975 `flex; radius card; bg surface-card; card edge; border-box` | `flex rounded-card bg-home-card [box-shadow:var(--home-card-edge)] box-border` |
| `.a-sk-hero` | :1981 `h var(--sk-hero); center; space-between; gap 24; padding 32`; M :2001 `column-reverse; start; justify end; gap 16; padding 24px 20px` | `h-[395px] @min-[376px]/home:h-[361px] @min-[410px]/home:h-[344px] @min-[561px]/home:h-[368px] @min-[761px]/home:h-[426px] @min-[960px]/home:h-[293px] @min-[974px]/home:h-[260px] @min-[1010px]/home:h-[239px] @min-[1138px]/home:h-[205px] items-center justify-between gap-6 p-8 @max-[761px]/home:flex-col-reverse @max-[761px]/home:items-start @max-[761px]/home:justify-end @max-[761px]/home:gap-4 @max-[761px]/home:py-6 @max-[761px]/home:px-5` (--sk-hero tiers :1925-1973) |
| `.a-sk-col` | :1982 `flex column; gap 12; flex 1 1 auto; min-w 0`; M :2003 `flex 0 0 auto; w 100%` | `flex flex-col gap-3 flex-auto min-w-0 @max-[761px]/home:flex-none @max-[761px]/home:w-full` |
| `.a-sk-title` | :1977 `block; w min(360px,90%); h 32; radius chip`; M h 30 :2004 | `block w-[min(360px,90%)] h-8 rounded-chip @max-[761px]/home:h-[30px]` |
| `.a-sk-line` / `.a-sk-short` | :1978-1979 `block; w min(420px,100%) / min(260px,70%); h 14; pill` | `block w-[min(420px,100%)] h-3.5 rounded-pill` / `w-[min(260px,70%)]` |
| `.a-sk-disc` | :1983 `flex none; 128×128; circle`; M 72×72, self-start :2002 | `flex-none size-32 rounded-full @max-[761px]/home:size-[72px] @max-[761px]/home:self-start` |
| `.a-next-row.a-sk-next` | :1502 `grid; gap 16; margin-top 20`; ≥900 cols `minmax(0,63%) minmax(300px,1fr)`, stretch :1505; ≤899 action first :1998 | `grid gap-4 mt-5 @min-[900px]/home:grid-cols-[minmax(0,63%)_minmax(300px,1fr)] @min-[900px]/home:items-stretch` |
| `.a-sk-garden` | :1984 `h var(--sk-garden); column; padding 20`; tiers 288 / 1044:256 / 1084:235 | `h-[288px] @min-[1044px]/home:h-[256px] @min-[1084px]/home:h-[235px] flex-col p-5` |
| `.a-sk-h` | :1976 `block; flex none; 140×19; mb 12; radius chip` | `block flex-none w-[140px] h-[19px] mb-3 rounded-chip` |
| `.a-sk-plants` | :1985-1986 `flex 1; grid 3 cols; gap 12; min-h 0`; children radius tile | `flex-1 grid grid-cols-3 gap-3 min-h-0` |
| `.a-sk-action` | :1987-1988 `h var(--sk-action); column; justify center; start; gap 12; padding 20`; its `.a-sk-h` `margin 0; 180×28`; tiers 199 / ≤357:231 / 761:235 | `h-[199px] @max-[358px]/home:h-[231px] @min-[761px]/home:h-[235px] flex-col justify-center items-start gap-3 p-5 @max-[900px]/home:order-[-1]`; heading `block flex-none w-[180px] h-7 m-0 rounded-chip` |
| `.a-sk-btn` | :1980 `block; 160×44; pill` | `block w-40 h-11 rounded-pill` |
| `.a-sec` | :591 mt 40; M mt 32 :1226; D mt 20 :1439 | `@max-[761px]/home:mt-8 @min-[761px]/home:mt-5` (the two tiers cover every width) |
| `.a-sk-sec` | :1989 `flex column` | `flex flex-col` |
| `.a-sk-grades` | :1990 tiers 336 / ≤337:360 / ≤327:379 / 376:323 / 561:263 / 761:239 | `h-[336px] @min-[328px]/home:@max-[338px]/home:h-[360px] @max-[328px]/home:h-[379px] @min-[376px]/home:h-[323px] @min-[561px]/home:h-[263px] @min-[761px]/home:h-[239px]` |
| `.a-sk-weak` | :1991 tiers 563 / ≤351:597 / ≤321:621 / 561:690 / 761:330 | `h-[563px] @min-[322px]/home:@max-[352px]/home:h-[597px] @max-[322px]/home:h-[621px] @min-[561px]/home:h-[690px] @min-[761px]/home:h-[330px]` |
| `.a-sk-exams` | :1992 tiers 432 / 376:409 / 761:378 / 802:363 / 1044:340 | `h-[432px] @min-[376px]/home:h-[409px] @min-[761px]/home:h-[378px] @min-[802px]/home:h-[363px] @min-[1044px]/home:h-[340px]` |
| `.a-sk-body` | :1993 `flex 1; column; gap 8; min-h 0`; `.a-sk-card` variant padding 8 :1994; children `flex 1; radius tile` :1995 | `flex-1 flex flex-col gap-2 min-h-0` (+ card variant `p-2`); children `flex-1` |
| `.a-sk-list > .a-skel` | :1996 radius card | `rounded-card` |

The `--sk-*` heights are the design's measurements of the ready page per content-width tier (variant-a.css:1923-1973). They are copied, not re-derived. Within each property, the `@min` ladders and the disjoint `@max` ranges follow Task 10's ordering rule.

- [ ] **Step 1: Failing tests (append)**

```ts
import { HomeError } from "@/portals/student/home/HomeError"
import { HomeSkeleton } from "@/portals/student/home/HomeSkeleton"

describe("HomeSkeleton", () => {
  it("is one busy region with the design's label", () => {
    const out = html(createElement(HomeSkeleton))
    expect(out).toContain('data-home="skeleton"')
    expect(out).toContain('aria-busy="true"')
    expect(out).toContain('aria-label="Loading your overview"')
    expect(out).not.toContain("<h2")
  })
})

describe("HomeError", () => {
  it("stale: banner with the last refresh time and a retry", () => {
    const at = new Date(2026, 10, 5, 9, 41).getTime()
    const out = html(createElement(HomeError, { stale: { at }, onRetry: () => {} }))
    expect(out).toContain('aria-label="Refresh status"')
    expect(out).toContain('role="status"')
    expect(out).toContain("Couldn't refresh your overview.")
    expect(out).toMatch(/You're seeing what we had at <span[^>]*>09:41<\/span>\. Marks and streak may be out of date\./)
    expect(out).toMatch(/<button type="button"[^>]*>Try again<\/button>/)
  })

  it("no cached data: load failure with the student message", () => {
    const out = html(createElement(HomeError, { stale: null, message: "Check your connection and try again.", onRetry: () => {} }))
    expect(out).toContain("Couldn't load your overview.")
    expect(out).toContain("Check your connection and try again.")
  })
})
```

Run: `cd web && npx vitest run tests/unit/studentHomeMarkup.test.ts`. Expected: FAIL (modules missing).

- [ ] **Step 2: Implement**

`HomeError.tsx`:

```tsx
/* Student home error banner (design A `.a-error`, role="status"). */
import { clockTime } from "./format"
import { Mono, buttonClass } from "./primitives"

export function HomeError({ stale, message, onRetry }: { stale: { at: number } | null; message?: string; onRetry: () => void }) {
  return (
    <section data-home="error" aria-label="Refresh status">
      <div
        role="status"
        className="flex flex-wrap items-center gap-x-5 gap-y-3 py-3 px-5 rounded-card bg-primary-container [box-shadow:var(--home-card-edge)] text-on-primary-container mb-4"
      >
        <p className="flex-[1_1_280px] m-0 text-home-sm leading-[1.45]">
          {stale ? (
            <>
              <b className="font-extrabold">Couldn't refresh your overview.</b> You're seeing what we had at <Mono>{clockTime(stale.at)}</Mono>. Marks and streak
              may be out of date.
            </>
          ) : (
            <>
              <b className="font-extrabold">Couldn't load your overview.</b> {message}
            </>
          )}
        </p>
        <button type="button" className={`${buttonClass("primary")} flex-none`} onClick={onRetry}>
          Try again
        </button>
      </div>
    </section>
  )
}
```

`HomeSkeleton.tsx`:

```tsx
/* Student home loading skeleton (design A `[data-when-state="loading"]`): the ready page's
 * boxes at their measured heights, so nothing shifts when data lands. */
import { cn } from "@/lib/utils"
import { useMotionOn } from "./primitives"

const CARD = "flex rounded-card bg-home-card [box-shadow:var(--home-card-edge)] box-border"
const SEC = "flex flex-col @max-[761px]/home:mt-8 @min-[761px]/home:mt-5"

function Skel({ className }: { className: string }) {
  const motion = useMotionOn()
  return <span className={cn("rounded-tile bg-surface-container-high", motion && "animate-[home-pulse_1.4s_ease-in-out_infinite_alternate]", className)} />
}

export function HomeSkeleton() {
  return (
    <section data-home="skeleton" aria-busy="true" aria-label="Loading your overview">
      <div
        className={cn(
          CARD,
          "h-[395px] @min-[376px]/home:h-[361px] @min-[410px]/home:h-[344px] @min-[561px]/home:h-[368px] @min-[761px]/home:h-[426px] @min-[960px]/home:h-[293px] @min-[974px]/home:h-[260px] @min-[1010px]/home:h-[239px] @min-[1138px]/home:h-[205px]",
          "items-center justify-between gap-6 p-8 @max-[761px]/home:flex-col-reverse @max-[761px]/home:items-start @max-[761px]/home:justify-end @max-[761px]/home:gap-4 @max-[761px]/home:py-6 @max-[761px]/home:px-5",
        )}
      >
        <div className="flex flex-col gap-3 flex-auto min-w-0 @max-[761px]/home:flex-none @max-[761px]/home:w-full">
          <Skel className="block w-[min(360px,90%)] h-8 rounded-chip @max-[761px]/home:h-[30px]" />
          <Skel className="block w-[min(420px,100%)] h-3.5 rounded-pill" />
          <Skel className="block w-[min(260px,70%)] h-3.5 rounded-pill" />
        </div>
        <Skel className="flex-none size-32 rounded-full @max-[761px]/home:size-[72px] @max-[761px]/home:self-start" />
      </div>

      <div className="grid gap-4 mt-5 @min-[900px]/home:grid-cols-[minmax(0,63%)_minmax(300px,1fr)] @min-[900px]/home:items-stretch">
        <div className={cn(CARD, "h-[288px] @min-[1044px]/home:h-[256px] @min-[1084px]/home:h-[235px] flex-col p-5")}>
          <Skel className="block flex-none w-[140px] h-[19px] mb-3 rounded-chip" />
          <span className="flex-1 grid grid-cols-3 gap-3 min-h-0">
            <Skel className="" />
            <Skel className="" />
            <Skel className="" />
          </span>
        </div>
        <div className={cn(CARD, "h-[199px] @max-[358px]/home:h-[231px] @min-[761px]/home:h-[235px] flex-col justify-center items-start gap-3 p-5 @max-[900px]/home:order-[-1]")}>
          <Skel className="block flex-none w-[180px] h-7 m-0 rounded-chip" />
          <Skel className="block w-[min(420px,100%)] h-3.5 rounded-pill" />
          <Skel className="block w-40 h-11 rounded-pill" />
        </div>
      </div>

      <div className={cn(SEC, "h-[336px] @min-[328px]/home:@max-[338px]/home:h-[360px] @max-[328px]/home:h-[379px] @min-[376px]/home:h-[323px] @min-[561px]/home:h-[263px] @min-[761px]/home:h-[239px]")}>
        <Skel className="block flex-none w-[140px] h-[19px] mb-3 rounded-chip" />
        <div className={cn(CARD, "flex-1 flex-col gap-2 min-h-0 p-2")}>
          <Skel className="flex-1" />
          <Skel className="flex-1" />
          <Skel className="flex-1" />
        </div>
      </div>

      <div className={cn(SEC, "h-[563px] @min-[322px]/home:@max-[352px]/home:h-[597px] @max-[322px]/home:h-[621px] @min-[561px]/home:h-[690px] @min-[761px]/home:h-[330px]")}>
        <Skel className="block flex-none w-[140px] h-[19px] mb-3 rounded-chip" />
        <div className="flex-1 flex flex-col gap-2 min-h-0">
          <Skel className="flex-1 rounded-card" />
          <Skel className="flex-1 rounded-card" />
          <Skel className="flex-1 rounded-card" />
        </div>
      </div>

      <div className={cn(SEC, "h-[432px] @min-[376px]/home:h-[409px] @min-[761px]/home:h-[378px] @min-[802px]/home:h-[363px] @min-[1044px]/home:h-[340px]")}>
        <Skel className="block flex-none w-[140px] h-[19px] mb-3 rounded-chip" />
        <div className="flex-1 flex flex-col gap-2 min-h-0">
          <Skel className="flex-1 rounded-card" />
          <Skel className="flex-1 rounded-card" />
          <Skel className="flex-1 rounded-card" />
        </div>
      </div>
    </section>
  )
}
```

`cn` merges `rounded-tile` with a later `rounded-chip`/`rounded-card`/`rounded-full`/`rounded-pill`, keeping the later one. That is the design's cascade (`.a-sk-title` etc. override `.a-skel`'s radius). The `.a-sk-plants > .a-skel` children keep `rounded-tile`.

- [ ] **Step 3: Run the unit tests**

Run: `cd web && npx vitest run tests/unit/studentHomeMarkup.test.ts`
Expected: PASS.

- [ ] **Step 4: Mount and register**

In `StudentHome.tsx`, extend the temporary `return` from Task 11:

```tsx
    <div id="sh-root" data-home="page" data-state={state} className="@container/home font-sans leading-normal text-on-surface">
      {model.kind === "loading" && <HomeSkeleton />}
      {model.kind === "error" && <HomeError stale={null} message={model.message} onRetry={() => void overview.refetch()} />}
      {model.kind === "ready" && model.stale && <HomeError stale={model.stale} onRetry={() => void overview.refetch()} />}
      {view && view.state !== "new" && <HomeHero view={view} />}
    </div>
```

Register: `...overviewScenes({ part: "skeleton", states: ["loading"] }), ...overviewScenes({ part: "error", states: ["error"] }),`.

- [ ] **Step 5: Drift**

Run: `cd web && node scripts/home-drift.mjs --only overview:skeleton`. Expected: `overview:skeleton PASS 10/10`.
Run: `cd web && node scripts/home-drift.mjs --only overview:error`. Expected: `overview:error PASS 10/10`.

The error scene depends on `failOverviewRefetch` (Task 9) leaving the page with cached data and a failed refetch, so the banner reads "09:41". If the app shows "10:00", the clock was advanced before the first load finished. Make `mockStudentHome` wait for the first overview response before `failOverviewRefetch` moves the clock. Re-run and read diffs as in Task 11 Step 5.

- [ ] **Step 6: Commit**

```bash
cd web && /home/sico/Code/Lemely/.venv/bin/pre-commit run --files src/portals/student/home/HomeSkeleton.tsx src/portals/student/home/HomeError.tsx src/portals/student/home/StudentHome.tsx scripts/home-drift.mjs tests/unit/studentHomeMarkup.test.ts
git commit -S -m "feat(web): student home skeleton and error banner" -- web/src/portals/student/home/HomeSkeleton.tsx web/src/portals/student/home/HomeError.tsx web/src/portals/student/home/StudentHome.tsx web/scripts/home-drift.mjs web/tests/unit/studentHomeMarkup.test.ts
```

---

## Task 18: `StudentHome`: page frame, notes, new state, composition

**Files:**
- Modify: `web/src/portals/student/home/StudentHome.tsx` (final version)
- Modify: `web/scripts/home-drift.mjs` (register `new` and `page`)
- Test: `web/tests/unit/studentHomeMarkup.test.ts` (append)

**Interfaces:**
- Consumes: `pageState`, `HomeView`, `PageModel` (Task 8); `useOverview`, `useActiveUpload`, `useXpProfile` (Task 7); `usePullToRefresh` (`web/src/lib/gestures/usePullToRefresh.ts`), `PullIndicator` (`web/src/components/ui/pull-indicator.tsx`); `HomeHero`, `HomeBinny` (Task 11); `Garden` (Task 12: `Garden(props: { view: HomeView; variant?: "ghost" })`); `NextStepCard` (Task 13: `NextStepCard(props: { view: HomeView; onLean?: (on: boolean) => void })`); `GradesList`, `PracticeTargets`, `ExamsTimeline` (Tasks 14–16: `(props: { view: HomeView })`. `ExamsTimeline` renders nothing when no subject has an exam date, the design's `[data-exams="no"] [data-needs="exams"]` rule, shell.css:69); `HomeSkeleton`, `HomeError` (Task 17); `Icon`, `Mono`, `ButtonLink`, `VH_CLASS`, `useMotionOn` (Task 10); `greetingWord`, `dayMonth` (`format.ts`).
- Produces:
  - `StudentHome(): JSX.Element`: the `/student` route element. Root carries the attributes in Shared interfaces ("Root data attributes").
  - `HomeNotes(props: { view: HomeView }): JSX.Element | null` and `NewHome(props: { view: HomeView }): JSX.Element`, exported for the markup tests.
  - Row placement contract: `StudentHome` owns how the Garden and next-step cards sit in `.a-next-row` (columns, `order`, `margin-top: 0`, the next card's flex centring). It does this through `[&>[data-home=…]]:` child variants. `Garden` and `NextStepCard` set no grid placement, `order` or top margin of their own. `Garden` owns its internal sparse stacked layout (variant-a.css:2234-2238).

### Copy templates

| Where (page-a.txt line) | Template | Fixture → output |
|---|---|---|
| new h1 :46 | `"${greetingWord(now)}."` (no name: the design greets a new student without one) | "Good morning." |
| new title :51 | "Let's get your first paper marked" | |
| new body :52 | "Photograph or upload a paper you have already sat. Lemely finds the session and variant, pulls the official mark scheme, and marks it question by question." | |
| new button :53 | "Upload a paper" + arrow → `/student/correct` | |
| new caption :57 | "Ready when you are." | |
| new steps :70-72 | 1 "Correct your first paper" "Now" (current); 2 "See where you stand" "Later" with ruler C B A A*; 3 "Get a study plan built from your own mistakes" "Later"; list label "How Lemely works for you" | |
| note sparse1 :407 | `<span><b>Study plan</b> unlocks after one more paper or one practice set.</span>` + link `"Practise ${weakTopics[0].topic.toLowerCase()}"` → `/student/practice/${weakTopics[0].subjectCode}` (omit the link if there is no weak topic) | "Practise vectors" → `/student/practice/0580` |
| note sparse2 :408 | only when some subject has `nextExamOn === null`: `"Add your ${names} exam date(s) to see how long you have."` + link `"Add exam date(s)"` → `/student/profile`; names = those subjects' `shortName`s joined "A, B and C" | "Add your Physics exam date to see how long you have." / "Add exam date" |
| note sparse3 :409 | `planEndedOn` ? `<span>Your study plan ended on <Mono>${dayMonth(planEndedOn)}</Mono>. Build a fresh week from your weak topics.</span>` : the no-plan sentence; link "Build a plan" → `/student/plan` | "…ended on 27 Oct…" |
| note no-plan :410 | state `no-plan`: "No study plan this week. Build one from your weak topics." + "Build a plan" → `/student/plan` | |
| note no-exams :411 | any ready state with no exam date at all (`data-exams="no"`, shell.css:74), excluding sparse states and `new`: "Add your exam dates to see how long you have for each subject." + "Add exam dates" → `/student/profile` | no-exams |

### Mapping

| Element / design selector | Declarations (variant-a.css / shell.css) | Tailwind |
|---|---|---|
| root `#sh-root` | shell.css:19-24 `container home; bg surface-page; color text-body; font ui`; variant-a.css:11 `line-height 1.5`, :15-17 selection colours, focus outline 2px primary offset 2, links no underline. The container is the padded main (:748); the shell provides the background | `@container/home relative font-sans leading-normal text-on-surface [&_a]:no-underline [&_::selection]:bg-primary-container [&_::selection]:text-on-primary-container [&_:focus-visible]:outline-2 [&_:focus-visible]:outline-primary [&_:focus-visible]:outline-offset-2` |
| `.a-page` (ready, new, error, loading) | :37-41 padding/max-width, reset inside the shell by :753 `padding 0; max-inline-size none; margin-inline 0` | (no classes) |
| `.a-next-row` | :1502 `grid; gap 16; margin-top 20`; ≥900 :1505 `minmax(0,63%) minmax(300px,1fr)`, stretch; sparse ≥900 :2233 `minmax(0,1fr) minmax(0,1fr)` | `grid gap-4 mt-5 @min-[900px]/home:items-stretch` + `@min-[900px]/home:grid-cols-[minmax(0,63%)_minmax(300px,1fr)]` or, for sparse states, `@min-[900px]/home:grid-cols-2` |
| `.a-next-row > .a-action-card` | :1503 `margin-top 0`; ≥900 :1506 `flex; column; justify center`; ≤899 :1826 `order -1` | `[&>[data-home=next]]:mt-0 @min-[900px]/home:[&>[data-home=next]]:flex @min-[900px]/home:[&>[data-home=next]]:flex-col @min-[900px]/home:[&>[data-home=next]]:justify-center @max-[900px]/home:[&>[data-home=next]]:order-[-1]` |
| `.a-note` | :270-274 `flex; wrap; center; gap 4px 12px; margin 0; padding 12px 20px; radius tile; bg surface-card; color secondary; 14px`; :348 `margin-top 12` | `flex flex-wrap items-center gap-x-3 gap-y-1 m-0 mt-3 py-3 px-5 rounded-tile bg-home-card text-home-ink-2 text-home-sm` |
| `.a-note a` | :275-278 `inline-flex; center; gap 2; margin-left auto; primary; 700; no underline`; :20 hover primary-hover; coarse :1215-1216 `min-h 44; padding-block 10` | `inline-flex items-center gap-0.5 ms-auto text-primary font-bold no-underline hover:text-primary-hover pointer-coarse:min-h-11 pointer-coarse:py-2.5` |
| `.a-note .a-ico` | :279 16×16 | `size-4` |
| new `.a-head` | :44-47 `flex; end; space-between; gap 24; mb 20`; D mb 16 :1411; M :1222,1294 `column; start; gap 12; mb 12` | `flex items-end justify-between gap-6 @min-[761px]/home:mb-4 @max-[761px]/home:flex-col @max-[761px]/home:items-start @max-[761px]/home:gap-3 @max-[761px]/home:mb-3` |
| new h1 `.a-greet` | :48-51 `800 40px/1.05 display; -.04em; text-body; balance`; D and M 32px :1412,1223 | `m-0 font-display font-extrabold text-home-headline leading-[1.05] tracking-[-0.04em] text-on-surface text-balance` |
| `.a-hero.a-hero-new` | :54-59 `grid; cols minmax(0,1fr) auto; gap 24; start; padding 24; radius card; bg surface-card; card edge`; :683 `mb 24`; D padding 24 :1437; M :1228,1286 `1 col; gap 16; padding 24px 20px` | `grid items-start content-start gap-6 rounded-card bg-home-card [box-shadow:var(--home-card-edge)] mb-6 @min-[761px]/home:grid-cols-[minmax(0,1fr)_auto] @min-[761px]/home:p-6 @max-[761px]/home:grid-cols-1 @max-[761px]/home:gap-4 @max-[761px]/home:py-6 @max-[761px]/home:px-5` |
| `.a-action` | :60 `min-inline-size 0` | `min-w-0` |
| `.a-title` (h2) | :68-71 `800 40px/1.02 display; -.04em; text-body; balance`; D and M 32px :1412,1234 | `m-0 font-display font-extrabold text-home-headline leading-[1.02] tracking-[-0.04em] text-on-surface text-balance` |
| `.a-body` | :73-76 `margin 12px 0 24px; max 48ch; 16px; secondary; pretty`; M mb 16 :1236 | `mt-3 mb-6 max-w-[48ch] text-home-body text-home-ink-2 text-pretty @max-[761px]/home:mb-4` |
| `.a-hero .a-btn-primary` | Task 10 primary button; M :1237 `inline-size 100%; justify center` | `ButtonLink variant="primary"` + `@max-[761px]/home:w-full @max-[761px]/home:justify-center` |
| `.a-binny` (figure) | :245-248 `margin 0; flex column; center; gap 12; inline-size 208`; M :1229 `order -1; row; auto width; gap 12` | `m-0 flex flex-col items-center gap-3 w-[208px] @max-[761px]/home:order-[-1] @max-[761px]/home:flex-row @max-[761px]/home:w-auto` |
| `.a-binny-art` | :249-253 `grid; place-items end center; 192×192; padding-bottom 12; circle; bg primary-container; overflow hidden`; svg :254-257 `inline-size 146; h auto; a-bob 3.6s alternate`; M :1230-1231 `80×80; pb 4; svg 62` | `grid items-end justify-items-center size-48 pb-3 rounded-full bg-primary-container overflow-hidden [&_svg]:w-[146px] [&_svg]:h-auto @max-[761px]/home:size-20 @max-[761px]/home:pb-1 @max-[761px]/home:[&_svg]:w-[62px]` + motion `[&_svg]:animate-[home-bob-soft_3.6s_ease-in-out_infinite_alternate]` |
| `.a-binny figcaption` | :258-266 `relative; max-w 100%; padding 10px 14px; radius inner; bg surface-section; center; 700 16px/1.3 ui; text-body; balance`; ::before 12px diamond, top -6, left calc(50% - 6px), rotate 45, radius 4, bg inherit; M :1232-1233 `start; 14px; ::before top calc(50% - 6px), left -5` | `relative max-w-full py-2.5 px-3.5 rounded-inner bg-surface-container-low text-center font-sans font-bold text-home-body leading-[1.3] text-on-surface text-balance before:content-[''] before:absolute before:-top-1.5 before:left-[calc(50%-6px)] before:size-3 before:bg-inherit before:rotate-45 before:rounded-[4px] @max-[761px]/home:text-start @max-[761px]/home:text-home-sm @max-[761px]/home:before:top-[calc(50%-6px)] @max-[761px]/home:before:-left-[5px]` |
| `.a-steps` | :684-687 `grid; 3 cols; gap 12; no list styling`; M 1 col :1285 | `m-0 p-0 list-none grid gap-3 @min-[761px]/home:grid-cols-3 @max-[761px]/home:grid-cols-1` |
| `.a-steps li` | :688-692 + :2014 `grid; cols auto minmax(0,1fr); rows auto auto 1fr; gap 2px 12px; center; content stretch; padding 16px 20px; radius tile; bg md-surface-container; color secondary`; current :693 `bg primary-container; color on-primary-container` | `grid grid-cols-[auto_minmax(0,1fr)] grid-rows-[auto_auto_1fr] gap-x-3 gap-y-0.5 items-center content-stretch py-4 px-5 rounded-tile` + current `bg-primary-container text-on-primary-container`, else `bg-surface-container text-home-ink-2` |
| `.a-step-n` | :694-697 `row span 2; grid; center; 32×32; circle; bg surface-card; 600 14px/1 mono; text-body` | `row-span-2 grid place-items-center size-8 rounded-full bg-home-card font-mono font-semibold text-home-sm leading-none text-on-surface` |
| `.a-step-t` | :698-699 `700; 14px; text-body; balance` (current: inherit) | `font-bold text-home-sm text-balance` + `text-on-surface` (not current) / `text-inherit` (current) |
| `.a-step-s` | :700 `600 11px/1 mono; .08em; uppercase` | `font-mono font-semibold text-home-label leading-none tracking-[0.08em] uppercase` |
| `.a-step-ghost` | :2015-2020 `col 1/-1; align-self end; border-box; flex; min-h 88; mt 12; padding 12px 16px; 2px dashed currentColor 35%; radius tile`; i block, normal style; M min-h 72 :2039 | `col-span-full self-end box-border flex min-h-[88px] mt-3 py-3 px-4 border-2 border-dashed border-[color-mix(in_oklch,currentColor_35%,transparent)] rounded-tile [&_i]:block [&_i]:not-italic @max-[761px]/home:min-h-[72px]` |
| `.a-g-paper` | :2021-2026 `column; justify center; gap 8`; i `h 8; pill; currentColor 22%`; widths 55/100/88/64% | `flex-col justify-center gap-2 [&_i]:h-2 [&_i]:rounded-pill [&_i]:bg-[color-mix(in_oklch,currentColor_22%,transparent)]` + per-`i` `w-[55%]`, `w-full`, `w-[88%]`, `w-[64%]` |
| `.a-g-ruler` | :2027-2032 `center; space-between; gap 8`; i `grid; center; 36×36; circle; 2px dashed currentColor 45%; 700 11px/1 mono; text-muted`; M max-w 280 :2040 | `items-center justify-between gap-2 @max-[761px]/home:max-w-[280px] [&_i]:grid [&_i]:place-items-center [&_i]:size-9 [&_i]:rounded-full [&_i]:border-2 [&_i]:border-dashed [&_i]:border-[color-mix(in_oklch,currentColor_45%,transparent)] [&_i]:font-mono [&_i]:font-bold [&_i]:text-home-label [&_i]:leading-none [&_i]:text-on-surface-variant` |
| `.a-g-rows` | :2033-2037 `column; justify center; gap 8`; i `h 12; pill; 22%`; widths 100/72/48% | `flex-col justify-center gap-2 [&_i]:h-3 [&_i]:rounded-pill [&_i]:bg-[color-mix(in_oklch,currentColor_22%,transparent)]` + `w-full`, `w-[72%]`, `w-[48%]` |

The binny-art cell is `place-items: end center`. In Tailwind that is `items-end justify-items-center` on a grid; use exactly those two classes. (`size-48` = 192px, `size-20` = 80px.)

- [ ] **Step 1: Failing tests (append)**

```ts
import { HomeNotes, NewHome } from "@/portals/student/home/StudentHome"

describe("StudentHome notes", () => {
  const note = (s: DataStateId) => html(createElement(HomeNotes, { view: viewOf(s) }))
  it("sparse1 unlock note links the weakest topic", () => {
    const out = note("sparse1")
    expect(out).toContain("<b>Study plan</b> unlocks after one more paper or one practice set.")
    expect(out).toMatch(/href="\/student\/practice\/0580"[^>]*>Practise vectors/)
  })
  it("sparse2 names the subject without an exam date", () => {
    expect(note("sparse2")).toContain("Add your Physics exam date to see how long you have.")
    expect(note("sparse2")).toMatch(/href="\/student\/profile"[^>]*>Add exam date</)
  })
  it("sparse3 says when the plan ended", () => {
    expect(note("sparse3")).toMatch(/Your study plan ended on <span[^>]*>27 Oct<\/span>\. Build a fresh week from your weak topics\./)
  })
  it("no-plan and no-exams", () => {
    expect(note("no-plan")).toContain("No study plan this week. Build one from your weak topics.")
    expect(note("no-exams")).toContain("Add your exam dates to see how long you have for each subject.")
  })
  it("populated has no note", () => {
    expect(note("populated")).toBe("")
  })
})

describe("NewHome", () => {
  it("greets without a name and shows the three steps", () => {
    const out = html(createElement(NewHome, { view: viewOf("new") }))
    expect(out).toContain('data-home="new"')
    expect(out).toMatch(/<h1[^>]*>Good morning\.<\/h1>/)
    expect(out).toMatch(/<h2[^>]*>Let's get your first paper marked<\/h2>/)
    expect(out).toMatch(/href="\/student\/correct"[^>]*>Upload a paper/)
    expect(out).toContain('aria-label="How Lemely works for you"')
    expect(out).toContain('aria-current="step"')
    expect(out.match(/<li/g)).toHaveLength(3)
    expect(out).toContain("Ready when you are.")
  })
})
```

`NewHome` renders `<Garden variant="ghost">` from Task 12, which must be committed before this task. Run: `cd web && npx vitest run tests/unit/studentHomeMarkup.test.ts`. Expected: FAIL (exports missing).

- [ ] **Step 2: Implement the final `StudentHome.tsx`**

```tsx
/*
 * Student home (design A, spec 2026-11-06). Route element for /student.
 * Reads three queries, turns them into one PageModel (facts.ts), and lays out the
 * sections in the design's order. Every section is a component in this folder.
 */
import { useRef, useState, type ReactElement, type ReactNode } from "react"
import { Link } from "react-router-dom"
import { PullIndicator } from "@/components/ui/pull-indicator"
import { usePullToRefresh } from "@/lib/gestures/usePullToRefresh"
import { useXpProfile } from "@/lib/hooks/useXpApi"
import { useActiveUpload, useOverview } from "@/lib/hooks/useStudentApi"
import { cn } from "@/lib/utils"
import { ExamsTimeline } from "./ExamsTimeline"
import { pageState, type HomeView } from "./facts"
import { dayMonth, greetingWord } from "./format"
import { Garden } from "./Garden"
import { GradesList } from "./GradesList"
import { HomeBinny, HomeHero } from "./HomeHero"
import { HomeError } from "./HomeError"
import { HomeSkeleton } from "./HomeSkeleton"
import { NextStepCard } from "./NextStepCard"
import { PracticeTargets } from "./PracticeTargets"
import { ButtonLink, Icon, Mono, VH_CLASS, useMotionOn } from "./primitives"

const NOTE = "flex flex-wrap items-center gap-x-3 gap-y-1 m-0 mt-3 py-3 px-5 rounded-tile bg-home-card text-home-ink-2 text-home-sm"
const NOTE_LINK = "inline-flex items-center gap-0.5 ms-auto text-primary font-bold no-underline hover:text-primary-hover pointer-coarse:min-h-11 pointer-coarse:py-2.5"

function NoteLink({ to, children }: { to: string; children: string }) {
  return (
    <Link to={to} className={NOTE_LINK}>
      {children} <Icon name="chev" className="size-4" />
    </Link>
  )
}

const joinNames = (names: string[]) =>
  names.length <= 1 ? (names[0] ?? "") : `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`

export function HomeNotes({ view }: { view: HomeView }) {
  const s = view.state
  const noDate = view.subjects.filter((x) => x.nextExamOn === null)
  const weakest = view.weakTopics[0]
  const sparse = s.startsWith("sparse")
  const noExams = !sparse && view.subjects.length > 0 && noDate.length === view.subjects.length
  const notes: ReactElement[] = []
  if (s === "sparse1")
    notes.push(
      <p key="lock" className={NOTE}>
        <span>
          <b>Study plan</b> unlocks after one more paper or one practice set.
        </span>{" "}
        {weakest && <NoteLink to={`/student/practice/${weakest.subjectCode}`}>{`Practise ${weakest.topic.toLowerCase()}`}</NoteLink>}
      </p>,
    )
  if (s === "sparse2" && noDate.length > 0)
    notes.push(
      <p key="date" className={NOTE}>
        Add your {joinNames(noDate.map((x) => x.shortName))} exam date{noDate.length === 1 ? "" : "s"} to see how long you have.{" "}
        <NoteLink to="/student/profile">{noDate.length === 1 ? "Add exam date" : "Add exam dates"}</NoteLink>
      </p>,
    )
  if (s === "sparse3")
    notes.push(
      <p key="ended" className={NOTE}>
        {view.planEndedOn ? (
          <span>
            Your study plan ended on <Mono>{dayMonth(view.planEndedOn)}</Mono>. Build a fresh week from your weak topics.
          </span>
        ) : (
          "No study plan this week. Build one from your weak topics."
        )}{" "}
        <NoteLink to="/student/plan">Build a plan</NoteLink>
      </p>,
    )
  if (s === "no-plan")
    notes.push(
      <p key="plan" className={NOTE}>
        No study plan this week. Build one from your weak topics. <NoteLink to="/student/plan">Build a plan</NoteLink>
      </p>,
    )
  if (noExams)
    notes.push(
      <p key="exams" className={NOTE}>
        Add your exam dates to see how long you have for each subject. <NoteLink to="/student/profile">Add exam dates</NoteLink>
      </p>,
    )
  return notes.length ? <>{notes}</> : null
}

const STEP = "grid grid-cols-[auto_minmax(0,1fr)] grid-rows-[auto_auto_1fr] gap-x-3 gap-y-0.5 items-center content-stretch py-4 px-5 rounded-tile"
const GHOST =
  "col-span-full self-end box-border flex min-h-[88px] mt-3 py-3 px-4 border-2 border-dashed border-[color-mix(in_oklch,currentColor_35%,transparent)] rounded-tile [&_i]:block [&_i]:not-italic @max-[761px]/home:min-h-[72px]"
const BAR_I = "[&_i]:rounded-pill [&_i]:bg-[color-mix(in_oklch,currentColor_22%,transparent)]"

function Step({ n, title, when, current, children }: { n: number; title: string; when: string; current?: boolean; children: ReactNode }) {
  return (
    <li aria-current={current ? "step" : undefined} className={cn(STEP, current ? "bg-primary-container text-on-primary-container" : "bg-surface-container text-home-ink-2")}>
      <span className="row-span-2 grid place-items-center size-8 rounded-full bg-home-card font-mono font-semibold text-home-sm leading-none text-on-surface">{n}</span>
      <span className={cn("font-bold text-home-sm text-balance", current ? "text-inherit" : "text-on-surface")}>{title}</span>
      <span className="font-mono font-semibold text-home-label leading-none tracking-[0.08em] uppercase">{when}</span>
      {children}
    </li>
  )
}

export function NewHome({ view }: { view: HomeView }) {
  const motion = useMotionOn()
  return (
    <section data-home="new">
      <header className="flex items-end justify-between gap-6 @min-[761px]/home:mb-4 @max-[761px]/home:flex-col @max-[761px]/home:items-start @max-[761px]/home:gap-3 @max-[761px]/home:mb-3">
        <div>
          <h1 className="m-0 font-display font-extrabold text-home-headline leading-[1.05] tracking-[-0.04em] text-on-surface text-balance">{greetingWord(view.facts.now)}.</h1>
        </div>
      </header>
      <article className="grid items-start content-start gap-6 rounded-card bg-home-card [box-shadow:var(--home-card-edge)] mb-6 @min-[761px]/home:grid-cols-[minmax(0,1fr)_auto] @min-[761px]/home:p-6 @max-[761px]/home:grid-cols-1 @max-[761px]/home:gap-4 @max-[761px]/home:py-6 @max-[761px]/home:px-5">
        <div className="min-w-0">
          <h2 className="m-0 font-display font-extrabold text-home-headline leading-[1.02] tracking-[-0.04em] text-on-surface text-balance">Let's get your first paper marked</h2>
          <p className="mt-3 mb-6 max-w-[48ch] text-home-body text-home-ink-2 text-pretty @max-[761px]/home:mb-4">
            Photograph or upload a paper you have already sat. Lemely finds the session and variant, pulls the official mark scheme, and marks it question by question.
          </p>
          <ButtonLink to="/student/correct" variant="primary" className="@max-[761px]/home:w-full @max-[761px]/home:justify-center">
            Upload a paper <Icon name="arrow" />
          </ButtonLink>
        </div>
        <figure className="m-0 flex flex-col items-center gap-3 w-[208px] @max-[761px]/home:order-[-1] @max-[761px]/home:flex-row @max-[761px]/home:w-auto">
          <div
            className={cn(
              "grid items-end justify-items-center size-48 pb-3 rounded-full bg-primary-container overflow-hidden [&_svg]:w-[146px] [&_svg]:h-auto @max-[761px]/home:size-20 @max-[761px]/home:pb-1 @max-[761px]/home:[&_svg]:w-[62px]",
              motion && "[&_svg]:animate-[home-bob-soft_3.6s_ease-in-out_infinite_alternate]",
            )}
          >
            <HomeBinny mood={view.mood} />
          </div>
          <figcaption className="relative max-w-full py-2.5 px-3.5 rounded-inner bg-surface-container-low text-center font-sans font-bold text-home-body leading-[1.3] text-on-surface text-balance before:content-[''] before:absolute before:-top-1.5 before:left-[calc(50%-6px)] before:size-3 before:bg-inherit before:rotate-45 before:rounded-[4px] @max-[761px]/home:text-start @max-[761px]/home:text-home-sm @max-[761px]/home:before:top-[calc(50%-6px)] @max-[761px]/home:before:-left-[5px]">
            Ready when you are.
          </figcaption>
        </figure>
      </article>
      <Garden view={view} variant="ghost" />
      <ol aria-label="How Lemely works for you" className="m-0 p-0 list-none grid gap-3 @min-[761px]/home:grid-cols-3 @max-[761px]/home:grid-cols-1">
        <Step n={1} title="Correct your first paper" when="Now" current>
          <span aria-hidden="true" className={cn(GHOST, "flex-col justify-center gap-2 [&_i]:h-2", BAR_I)}>
            <i className="w-[55%]" />
            <i className="w-full" />
            <i className="w-[88%]" />
            <i className="w-[64%]" />
          </span>
        </Step>
        <Step n={2} title="See where you stand" when="Later">
          <span
            aria-hidden="true"
            className={cn(
              GHOST,
              "items-center justify-between gap-2 @max-[761px]/home:max-w-[280px] [&_i]:grid [&_i]:place-items-center [&_i]:size-9 [&_i]:rounded-full [&_i]:border-2 [&_i]:border-dashed [&_i]:border-[color-mix(in_oklch,currentColor_45%,transparent)] [&_i]:font-mono [&_i]:font-bold [&_i]:text-home-label [&_i]:leading-none [&_i]:text-on-surface-variant",
            )}
          >
            <i>C</i>
            <i>B</i>
            <i>A</i>
            <i>A*</i>
          </span>
        </Step>
        <Step n={3} title="Get a study plan built from your own mistakes" when="Later">
          <span aria-hidden="true" className={cn(GHOST, "flex-col justify-center gap-2 [&_i]:h-3", BAR_I)}>
            <i className="w-full" />
            <i className="w-[72%]" />
            <i className="w-[48%]" />
          </span>
        </Step>
      </ol>
    </section>
  )
}

function ReadyHome({ view, lean, onLean }: { view: HomeView; lean: boolean; onLean: (on: boolean) => void }) {
  const sparse = view.state.startsWith("sparse")
  return (
    <div>
      <HomeHero view={view} lean={lean} />
      <div
        className={cn(
          "grid gap-4 mt-5 @min-[900px]/home:items-stretch",
          sparse ? "@min-[900px]/home:grid-cols-2" : "@min-[900px]/home:grid-cols-[minmax(0,63%)_minmax(300px,1fr)]",
          "[&>[data-home=next]]:mt-0 @min-[900px]/home:[&>[data-home=next]]:flex @min-[900px]/home:[&>[data-home=next]]:flex-col @min-[900px]/home:[&>[data-home=next]]:justify-center @max-[900px]/home:[&>[data-home=next]]:order-[-1]",
        )}
      >
        <Garden view={view} />
        <NextStepCard view={view} onLean={onLean} />
      </div>
      <HomeNotes view={view} />
      <GradesList view={view} />
      <PracticeTargets view={view} />
      <ExamsTimeline view={view} />
    </div>
  )
}

export function StudentHome() {
  const overview = useOverview()
  const xp = useXpProfile()
  const upload = useActiveUpload({ poll: true })
  const motion = useMotionOn()
  const [lean, setLean] = useState(false)
  const surface = useRef<HTMLDivElement>(null)
  const { pulling, refreshing } = usePullToRefresh(surface, {
    onRefresh: () => Promise.all([overview.refetch(), xp.refetch(), upload.refetch()]),
  })

  const model = pageState({ overview, xp, upload }, new Date())
  const view = model.kind === "ready" ? model.view : null
  const state = model.kind === "ready" ? (model.stale ? "error" : model.view.state) : model.kind
  const retry = () => void overview.refetch()

  return (
    <div
      ref={surface}
      id="sh-root"
      data-home="page"
      data-state={state}
      data-action={view?.action.kind}
      data-mood={view?.mood}
      data-exams={view ? (view.subjects.some((s) => s.nextExamOn !== null) ? "yes" : "no") : undefined}
      data-motion={motion ? "full" : "reduce"}
      className="@container/home relative font-sans leading-normal text-on-surface [&_a]:no-underline [&_::selection]:bg-primary-container [&_::selection]:text-on-primary-container [&_:focus-visible]:outline-2 [&_:focus-visible]:outline-primary [&_:focus-visible]:outline-offset-2"
    >
      {(pulling || refreshing) && (
        <div className="pointer-events-none absolute inset-x-0 z-dropdown flex justify-center" style={{ top: "calc(var(--lm-pull-progress, 0) * 40px - 40px)" }}>
          <PullIndicator progress={pulling ? 1 : 0} refreshing={refreshing} />
        </div>
      )}
      {model.kind === "loading" && (
        <>
          <h1 className={VH_CLASS}>Overview</h1>
          <HomeSkeleton />
        </>
      )}
      {model.kind === "error" && (
        <>
          <h1 className={VH_CLASS}>Overview</h1>
          <HomeError stale={null} message={model.message} onRetry={retry} />
        </>
      )}
      {model.kind === "ready" && model.stale && <HomeError stale={model.stale} onRetry={retry} />}
      {view && (view.state === "new" ? <NewHome view={view} /> : <ReadyHome view={view} lean={lean} onLean={setLean} />)}
    </div>
  )
}
```

Notes on choices:
- The pull indicator renders only while pulling or refreshing. The old Overview mounted it permanently at `top: -40px`, where it would sit inside the captured content area and cost drift pixels. It also carries `role="status"`, which would collide with the error banner's status region in the error drift scene.
- The visually hidden `<h1>Overview</h1>` in the loading and no-data states keeps one `h1` per page (axe `page-has-heading-one`) without a visible element. The design has no heading there, and a clipped 1px element changes no pixels.
- `data-motion` mirrors `prefers-reduced-motion`. The preview's `?motion=` switch does not exist in the app. The drift harness sets `reducedMotion: "reduce"` on the app context instead.
- `JoinClassPrompt`, which the old Overview rendered above its content, is not in design A. Task 19's route switch must say where it goes (or that it goes away) in its commit message, and must flag it to the user.

- [ ] **Step 3: Run the unit tests**

Run: `cd web && npx vitest run tests/unit/studentHomeMarkup.test.ts tests/unit/studentHomeFacts.test.ts`
Expected: PASS.
Run: `cd web && npx tsc -b --noEmit`
Expected: no new errors.

- [ ] **Step 4: Register and run the drift parts**

Add to `web/scripts/home-drift.mjs`: `...overviewScenes({ part: "new", states: ["new"] }), ...overviewScenes({ part: "page" }),`.

Run: `cd web && node scripts/home-drift.mjs --only overview:new`. Expected: `overview:new PASS 10/10`.
Run: `cd web && node scripts/home-drift.mjs --only overview:page`. Expected: `overview:page PASS 140/140` (14 states × 5 widths × 2 themes).

A failure in `page` while every section part passes means the drift is between sections: `.a-next-row` gap and columns, note margins, `.a-sec` top margins (owned by Tasks 14–16), or the order of the next card below 900px. Read the diff, find the band, fix the owning rule, and re-run.

- [ ] **Step 5: Commit**

```bash
cd web && /home/sico/Code/Lemely/.venv/bin/pre-commit run --files src/portals/student/home/StudentHome.tsx scripts/home-drift.mjs tests/unit/studentHomeMarkup.test.ts
git commit -S -m "feat(web): compose the student home page from design A" -- web/src/portals/student/home/StudentHome.tsx web/scripts/home-drift.mjs web/tests/unit/studentHomeMarkup.test.ts
```

---

## Task 19: Switch `/student` to the new home and delete the old Overview

**Files:**
- Modify: `web/src/portals/student/index.tsx` (lazy import ~line 64, route ~line 944, dev route from Task 9)
- Delete: `web/src/portals/student/screens/Overview.tsx`
- Delete: every module only the old Overview imported (Step 1 decides which; on develop that is `web/src/components/ui/getting-started.tsx`)
- Modify: source-scanning unit tests that list `screens/Overview.tsx`: `web/tests/unit/subjectGlyph.test.ts:73`, `streakChip.test.ts:20`, `sectionHead.test.ts:21`, `utilityExistence.test.ts:85`, `rtlSafety.test.ts:122`, `queryStateGate.test.ts:312` (re-grep, the list may have moved)
- Modify: e2e specs that assert old Overview copy: `web/e2e/student-journey.spec.ts:46,73`, `web/e2e/screenshots.spec.ts:200,237`
- Modify: `web/scripts/home-drift/overview.mjs` (`APP_PATH`)

**Interfaces:**
- Consumes: `StudentHome` (Task 18), every component's drift part passing.
- Produces: `/student` renders `StudentHome`; `/student/home-next` is gone; `APP_PATH = "/student"`.

- [ ] **Step 1: Gate and inventory**

Run every part once more against `/student/home-next`:

```bash
cd web && for p in hero garden next grades weak exams skeleton error new page; do node scripts/home-drift.mjs --only overview:$p | tail -1; done
```

Expected: ten lines, each `overview:<part> PASS n/n`. If any line says FAIL, stop. The task that owns that part is not done.

List what only the old screen uses:

```bash
cd web && for m in $(grep -oE 'from "[^"]+"' src/portals/student/screens/Overview.tsx | sed -E 's/from "(.*)"/\1/'); do
  n=$(grep -rlF "$m" src --include='*.ts' --include='*.tsx' | grep -v screens/Overview.tsx | wc -l); echo "$n $m"; done | sort -n
```

Every module with `0` that lives in this repo (starts with `@/` or `../`) is deleted in Step 3, along with its own unit test file if it has one. Check `src/portals/student/index.tsx` too: its sidebar block (~line 443) says it reads the same query as `Overview.tsx`. That comment must stop naming the deleted file.

- [ ] **Step 2: Update the source-scanning tests first (they fail when the file goes)**

```bash
cd web && grep -rln "screens/Overview.tsx" tests/unit | grep -v teacher
```

In each file, replace the path `src/portals/student/screens/Overview.tsx` with the new home files that took over the same duty. For example:
- `sectionHead.test.ts` and `rtlSafety.test.ts` scan files for disallowed patterns. Point them at `src/portals/student/home/StudentHome.tsx` and the eight section components.
- `queryStateGate.test.ts` checks that a screen gates on query state. Point it at `home/StudentHome.tsx`, which gates through `pageState`. If the gate test asserts a specific `QueryState` component, add `StudentHome.tsx` to its documented exceptions with the reason "gates through `pageState` (facts.ts)". Do not weaken the rule for other screens.
- `streakChip.test.ts` and `subjectGlyph.test.ts` assert the old screen used a shared component. If the new home deliberately does not use it (the design owns its own glyphs), remove the Overview entry and say why in a comment.

Run: `cd web && npx vitest run tests/unit/subjectGlyph.test.ts tests/unit/streakChip.test.ts tests/unit/sectionHead.test.ts tests/unit/utilityExistence.test.ts tests/unit/rtlSafety.test.ts tests/unit/queryStateGate.test.ts`
Expected: PASS (the old file still exists, and the new paths are scanned too).

- [ ] **Step 3: Switch the route and delete**

`web/src/portals/student/index.tsx`: delete the `Overview` lazy import, keep `StudentHome`'s, and change the index route element to `<StudentHome />`. Remove the `home-next` dev route. Delete `screens/Overview.tsx` and the Step 1 zero-user modules:

```bash
git rm web/src/portals/student/screens/Overview.tsx web/src/components/ui/getting-started.tsx
```

(Adjust the list to Step 1's output.) Set `APP_PATH = "/student"` in `web/scripts/home-drift/overview.mjs`.

Update the e2e assertions:
- `student-journey.spec.ts`: the "Subjects this session" heading becomes the design's grades heading. Assert `page.getByRole("heading", { name: "Your grades" })`, and where line 73 scopes into the old subjects panel, scope into `page.locator('[data-home="grades"]')`.
- `screenshots.spec.ts` S-06: default waits for `getByRole("heading", { name: "Your grades" })`. Loading waits for `page.locator('[data-home="skeleton"]')`. Error waits for `getByText("Couldn't load your overview")` only if `HomeError`'s no-cache copy is `studentLoadFailureMessage`'s text; otherwise wait for `page.locator('[data-home="error"]')`.

- [ ] **Step 4: Verify**

```bash
cd web && npx tsc -b --noEmit && npx oxlint src/portals/student && npx vitest run tests/unit/studentHomeFacts.test.ts tests/unit/studentHomeMarkup.test.ts tests/unit/subjectGlyph.test.ts tests/unit/streakChip.test.ts tests/unit/sectionHead.test.ts tests/unit/utilityExistence.test.ts tests/unit/rtlSafety.test.ts tests/unit/queryStateGate.test.ts
cd web && npx playwright test e2e/student-journey.spec.ts e2e/student-home.spec.ts
cd web && node scripts/home-drift.mjs --only overview:page | tail -1
```

Expected: no type or lint errors; all listed tests pass; `overview:page PASS 140/140` now against `/student`. Run `npm run check:bundle` if it exists in `package.json` (`check-bundle-budget.mjs`). The student entry must stay within budget, because the old screen's chart chunk is gone.

- [ ] **Step 5: Commit**

```bash
/home/sico/Code/Lemely/.venv/bin/pre-commit run --files web/src/portals/student/index.tsx web/scripts/home-drift/overview.mjs web/e2e/student-journey.spec.ts web/e2e/screenshots.spec.ts web/tests/unit/subjectGlyph.test.ts web/tests/unit/streakChip.test.ts web/tests/unit/sectionHead.test.ts web/tests/unit/utilityExistence.test.ts web/tests/unit/rtlSafety.test.ts web/tests/unit/queryStateGate.test.ts
git commit -S -m "feat(web): student home replaces the Overview screen" -- web/src/portals/student/index.tsx web/src/portals/student/screens/Overview.tsx web/src/components/ui/getting-started.tsx web/scripts/home-drift/overview.mjs web/e2e/student-journey.spec.ts web/e2e/screenshots.spec.ts web/tests/unit/subjectGlyph.test.ts web/tests/unit/streakChip.test.ts web/tests/unit/sectionHead.test.ts web/tests/unit/utilityExistence.test.ts web/tests/unit/rtlSafety.test.ts web/tests/unit/queryStateGate.test.ts
```

---

## Task 20: Full drift sweep, result-opened interaction, axe, drift log

**Files:**
- Modify: `web/scripts/home-drift/overview.mjs` (the `result-opened` interaction)
- Modify: `web/scripts/home-drift.mjs` (register `page` with all interactions)
- Modify: `web/e2e/student-home.spec.ts` (mark-seen flow, axe per state)
- Modify: `docs/superpowers/specs/2026-11-06-student-home-overview-design.md` (Drift log)

**Interfaces:**
- Consumes: `overviewScenes`, `mockStudentHome`, `PARTS` (Task 9); the interactions defined in Tasks 12 (`garden-pick`), 13 (`marking-stage-2`) and 16 (`exam-pick`), exported from their tasks' code as `GARDEN_PICK`, `MARKING_STAGE_2`, `EXAM_PICK` in `overview.mjs`.
- Produces: the final drift report and the filled drift log.

- [ ] **Step 1: Add the result-opened interaction**

In `overview.mjs`:

```js
/** Result opened: the result-in hero goes away once the result is opened and the student comes back. */
export const RESULT_OPENED = {
  id: "result-opened",
  state: "result-in",
  preview: async (page) => {
    await page.goto(page.url().replace("state=result-in", "state=populated"))
  },
  app: async (page) => {
    await page.route("**/api/student/result/*", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ code: "0580", paper: "Paper 4 - Variant 2", session: "May/June 2024", markerLabel: "", headline: "61 out of 80.", summary: "", awarded: 61, max: 80, pct: 76, grade: "A", boundaryYear: "2024", railLeft: 76, railFoot: "", railNote: "", theory: [], integrity: [], provenance: "", attemptId: null }) }),
    )
    let seen = false
    await page.unroute("**/api/student/results/*/seen")
    await page.route("**/api/student/results/*/seen", (route) => { seen = true; return route.fulfill({ status: 204, body: "" }) })
    await page.unroute("**/api/student/overview")
    await page.route("**/api/student/overview", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(seen ? API_FIXTURES.populated.overview : API_FIXTURES["result-in"].overview) }),
    )
    await page.getByRole("link", { name: "See your marks" }).click()
    await page.waitForURL(/\/student\/result\//)
    await page.waitForFunction(() => true) // let PaperResult's effect fire
    await page.goBack()
    await page.locator('#sh-root[data-state="populated"]').waitFor()
  },
}
```

The `ResultDTO` literal must match `web/src/lib/studentTypes.ts`'s `Result` type. Copy its field list from there if it differs from the one above.

Register: `overviewScenes({ part: "page", interactions: [GARDEN_PICK, MARKING_STAGE_2, EXAM_PICK, RESULT_OPENED] })`.

- [ ] **Step 2: Full sweep**

```bash
cd web && node scripts/home-drift.mjs --only overview: 2>&1 | tee ../reports/home-drift/overview-sweep.txt | tail -12
```

Expected: one `PASS` line per part. The page part reports `overview:page PASS 180/180` (140 state scenes + 4 interactions × 5 widths × 2 themes). For every scene above 0 px, read its diff image. Either fix the drift (go back to the owning task's component and re-run that part) or, only when the difference is a deliberate improvement or an unavoidable renderer difference such as font hinting of the same glyphs, write its row in Step 4. Anything over 15% fails, with no exceptions.

- [ ] **Step 3: Behaviour and axe in the real browser**

Append to `web/e2e/student-home.spec.ts`, using the login helper that Task 12 set up in this file:

```ts
import AxeBuilder from "@axe-core/playwright"
import { OVERVIEW_STATES, mockStudentHome, failOverviewRefetch } from "../scripts/home-drift/overview.mjs"

for (const state of OVERVIEW_STATES) {
  test(`axe: student home ${state} has no violations`, async ({ page }) => {
    await mockStudentHome(page, state)
    await page.goto("/student")
    await page.locator(`#sh-root[data-state="${state === "loading" ? "loading" : state === "error" ? "populated" : state}"]`).waitFor()
    if (state === "error") await failOverviewRefetch(page)
    const results = await new AxeBuilder({ page }).include("main").analyze()
    expect(results.violations).toEqual([])
  })
}

test("opening the result marks it seen once", async ({ page }) => {
  await mockStudentHome(page, "result-in")
  const posts: string[] = []
  await page.unroute("**/api/student/results/*/seen")
  await page.route("**/api/student/results/*/seen", (route) => { posts.push(route.request().url()); return route.fulfill({ status: 204, body: "" }) })
  await page.goto("/student")
  await page.getByRole("link", { name: "See your marks" }).click()
  await expect.poll(() => posts.length).toBe(1)
  expect(posts[0]).toMatch(/\/api\/student\/results\/p-0580-42\/seen$/)
})

test("marking progress is a polite live region that names the question", async ({ page }) => {
  await mockStudentHome(page, "marking")
  await page.goto("/student")
  const live = page.locator('[data-home="next"] [role="status"][aria-live="polite"]')
  await expect(live).toHaveText("Marking question 7 of 12")
})

test.describe("on a touch phone", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true })
  for (const state of ["populated", "sparse2", "one-paper"] as const) {
    test(`touch targets are at least 44px (${state})`, async ({ page }) => {
      await mockStudentHome(page, state)
      await page.goto("/student")
      await page.locator(`#sh-root[data-state="${state}"]`).waitFor()
      const small: string[] = []
      for (const el of await page.locator("main a, main button, main summary, main label[for]").all()) {
        if (!(await el.isVisible())) continue
        const box = await el.boundingBox()
        if (box && (box.height < 44 || box.width < 44)) small.push(`${await el.evaluate((n) => n.outerHTML.slice(0, 80))} ${box.width}x${box.height}`)
      }
      expect(small).toEqual([])
    })
  }
})
```

Run: `cd web && npx playwright test e2e/student-home.spec.ts`
Expected: all pass. A failing axe rule is fixed in the component, never disabled. A colour-contrast violation that the design itself has is a design bug: show it to the user with the measured ratio and the fix, apply the fix only with their approval, and log it in the drift log.

- [ ] **Step 4: Fill the drift log**

Replace the `(none yet)` row of the spec's "Drift log" with one row per non-zero scene from Step 2: `| <scene id> | <what differs, which element> | <percent> | <why it is justified> | <user approval: pending> |`. If every scene is 0 px, write `| all 180 page scenes and every part | none | 0 | n/a | n/a |`. Show the table to the user. Entries marked `pending` need the user's approval before the work is called done (spec §4: improvements need approval).

- [ ] **Step 5: Final verification and commit**

Re-run, on the final tree:

```bash
PYTHONPATH=/home/sico/Code/Lemely/.claude/worktrees/student-home-variants /home/sico/Code/Lemely/.venv/bin/pytest tests/test_migration_0052_attempt_seen_at.py tests/test_migration_0053_upload_progress.py tests/test_student_result_seen.py tests/test_upload_progress.py tests/test_overview_home.py tests/test_study_plan_upcoming.py tests/test_web_student.py tests/test_student_correct.py -q
cd web && npx vitest run tests/unit/studentHomeFacts.test.ts tests/unit/studentHomeFormat.test.ts tests/unit/studentHomeHooks.test.ts tests/unit/studentHomeMarkup.test.ts tests/unit/studentHomeModel.test.ts tests/unit/studentHomeFixtures.test.ts
cd web && npx tsc -b --noEmit && npm run lint
cd web && node scripts/home-drift.mjs --only overview: | grep -E "PASS|FAIL"
grep -rnE "TODO|FIXME|test\.only|test\.skip|describe\.only" web/src/portals/student/home web/e2e/student-home.spec.ts web/scripts/home-drift/overview.mjs lemely/web/overview_home.py lemely/web/upload_progress.py
```

Expected: all green; every part PASS; the grep prints nothing. This sweep certifies only this tree, so any later fix commit means running it again.

```bash
/home/sico/Code/Lemely/.venv/bin/pre-commit run --files web/scripts/home-drift/overview.mjs web/scripts/home-drift.mjs web/e2e/student-home.spec.ts docs/superpowers/specs/2026-11-06-student-home-overview-design.md
git commit -S -m "test(web): student home drift sweep, axe per state, drift log" -- web/scripts/home-drift/overview.mjs web/scripts/home-drift.mjs web/e2e/student-home.spec.ts docs/superpowers/specs/2026-11-06-student-home-overview-design.md
```

Do not push.

---

## Self-review (run by the plan author against the spec)

| Spec item | Task |
|---|---|
| §1 overview: `latestResult` with `seen` | 3 (seen), 6 (field) |
| §1 `firstPct`, `previousGrade`, `nextExamOn`, `examAvailability` per subject | 5 |
| §1 `upcomingSessions` next 7 days | 6 |
| §1 `UploadRunDTO.progress`, written by the pipeline | 2, 4 |
| §1 `POST /student/results/{paperId}/seen`, idempotent, own papers only | 3 |
| §1 two migrations, stop and show each | 1 (Step 3), 2 (Step 3) |
| §1 frontend queries, `useMarkResultSeen`, upload polling | 7 |
| §1 `facts.ts` `toHomeFacts`, `homeState`; model decides action/mood/strip | 8 |
| §2 nine components, markup order and copy | 10–18 |
| §2 behaviour as hooks (Garden pick, stage walk, motion, count-up, reveal), reduced motion | 10, 11, 12, 13, 15, 16, 18 |
| §2 light and dark | every drift part runs both themes |
| §2 old Overview deleted with unused imports | 19 |
| §3 14 states, fixture wins | 8 (tests per state, spec table updated) |
| §3 XP/upload failure hides only its piece | 8 (`pageState`, `xp: null`), 11 (hero without XP) |
| §3 edge cases: long names, 0/1/3+ subjects, exam with no start time, stale upload, offline | 8 (facts), 14–16 (markup tests); offline banner is the shell's |
| §3 accessibility | 10–18 markup tests, 12/16 keyboard, 20 axe, live region, 44px |
| §4 drift gate matrix and pass rule | 9, every UI task, 20 |
| §4 pytest incl. other student's paper, migrations both ways | 1, 2, 3, 4, 5, 6 |
| §4 rollout after every gate | 19 Step 1 |

Additions beyond the spec, each flagged where it lands: `detected_paper_label` / `detected_subject_code` on uploads (Task 2), enrolled subjects with no paper as overview rows (Task 5), `boundaries` / `boundariesEstimated` / `lastPaperOn` on subject rows (Task 5), `latestResult.awarded/maximum`, `weakTopics` with trend and marks, `planEndedOn` (Task 6), the `attempts.seen_at` backfill (Task 1), `SUBJECT_SHORT_NAMES` (Task 8), and `sparse2` widened to 2–5 papers (Task 8). Design A prints each of these values. Without them the page could not show real data in every state.

Decisions the user must make during execution (each task stops at the point named):
- Garden solo and sparse plants: the design places their stems and leaves by hand. The plan uses a formula that matches every picker value, so those scenes differ inside the plants (Task 12 stop plus drift-log rows).
- Exams in sparse2: the preview checks a hidden Physics radio, so no tile looks selected. 10 scenes are expected to fail at ≤15% (Task 16 drift-log row).
- Exam dates after 20 May fall outside the timeline the design draws (Task 16).
- Fallback copy the design never shows: "Top grade", "no change", the empty weak-topics line, "Your paper is being marked" with no label, and Garden "Next:" lines when every subject is planted (Tasks 12–16).
- `JoinClassPrompt` from the old Overview is not in design A and disappears at the route switch unless the user places it (Task 19).
- Binny reuses the marketing component's mood art. Check the bundle budget (Task 19 Step 4).
