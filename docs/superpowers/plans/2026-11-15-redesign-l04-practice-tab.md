# L4 · Practice Tab and Set Builder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the Practice tab root (`/student/practice`) from the approved mock C, with the set builder sheet that replaces `PracticeGenerator.tsx` without losing any generator feature, the past papers screen and sheet, and the `GET /api/student/practice/runs` endpoint behind "Recent".

**Architecture:** Backend first. A new `PracticeHubService` (`lemely/db/practice_hub_repo.py`) reads recent practice runs and past papers, and builds a set from one past paper. It sits in its own router (`lemely/web/routers/practice_hub.py`, same `/api/student/practice` prefix) and its own schemas file, so L3's edits to `practice_repo.py` and `practice.py` never conflict with L4. The builder reuses the availability check that already exists (`GET /api/student/practice/{code}/preview`), the topic list (`/topics`) and create (`POST /api/student/practice`) unchanged. The frontend gets typed hooks, three pure view models (hub, builder, papers) with Vitest coverage, and thin screens built on the F1 kit.

**Tech Stack:**
- Web: React 19, react-router 7, TanStack Query, Tailwind 4, Vitest (node), Playwright
- Backend: FastAPI and SQLAlchemy 2, pytest against a throwaway Postgres
- F1 kit: `web/src/components/redesign`

**Spec:** `docs/superpowers/specs/2026-11-14-redesign-implementation-design.md` (Wave 1 item 4)
**Master plan:** `docs/superpowers/plans/2026-11-15-redesign-00-master.md`
**Mock:** `.impeccable/mocks/student-r2/practice-hub-final.html` with `ph.js`, `ph.css`, `t.js`, `t.css`, `pr.css`, `sp.css`, `fc.css` and `base.css`. Option C is approved.

## Global Constraints

Inherits the master plan's Global Constraints. L4 adds these:

- **Owned files (create or edit freely):**
  - `web/src/portals/student/screens/practice/PracticeHub.tsx`
  - `web/src/portals/student/screens/practice/hub/*`, `builder/*`, `papers/*`
  - `web/src/portals/student/screens/practice/practiceIcons.tsx`, `practiceCopy.ts`, `practiceData.ts`
  - `web/src/lib/practiceHubTypes.ts`, `web/src/lib/practiceHubKeys.ts`, `web/src/lib/hooks/usePracticeHubApi.ts`
  - `lemely/db/practice_hub_repo.py`, `lemely/web/routers/practice_hub.py`, `lemely/web/schemas_practice_hub.py`
  - the new tests named in each task
  - `web/e2e/phase4-practice.spec.ts`, which tests the screen L4 replaces
- **Narrow edits to shared files only:**
  - `lemely/web/app.py`: one import and one `include_router` line
  - `web/src/portals/student/index.tsx`: the student route table, which is where student routes live (`web/src/routes.tsx` only mounts `studentRoute`). Two lazy imports plus the three practice route entries.
  - `web/src/portals/student/shell.tsx`: the Practice tab's `to` only (F1 owns the bar)
  - `web/src/portals/student/data.ts`: the Practice nav item, two crumbs, the crumb-link map and the `currentSubjectCode` practice arm
  - `web/tests/unit/navigation.test.ts`: only the assertions about the lines above
  - `web/scripts/audit.mjs`: only the three S-20 entries and one new helper
- **Never touch:** `PracticeSet.tsx` and `PracticeResult.tsx` (L3), `lemely/db/practice_repo.py` and `lemely/web/routers/practice.py` (L3 may edit them), anything under `flashcards/` (L10), `Overview.tsx` and `home/` (L1).
- **Copy:** `npm run check:copy` is a CI gate, and it bans `!` and prose em dashes in product copy. Binny's lines therefore end in a period ("Vectors first. +9 marks."). See Needs user decision 1.
- **Honesty rules the live generator follows stay in force:**
  - The match count is never padded.
  - A shortfall can still be created.
  - A refusal (`no_questions`, `no_weaknesses`) is never shown as success.
  - The weak-topic prefill never selects a topic that has no visible chip.
- **pytest command form** (shared venv, pin the worktree): `PYTHONPATH=$(git rev-parse --show-toplevel) /home/sico/Code/Lemely/.venv/bin/pytest <files> -q`
- **Vitest command form:** `cd web && npx vitest run <files>`
- **Pre-commit per commit:** `PYTHONPATH=$(git rev-parse --show-toplevel) pre-commit run --files <touched files>`

---

## File structure

| File | Responsibility |
|---|---|
| `lemely/db/practice_hub_repo.py` | `PracticeHubService`: `runs()`, `past_papers()`, `create_from_paper()`. Its dataclasses, plus `PastPaperUnavailableError`. |
| `lemely/web/schemas_practice_hub.py` | camelCase DTOs for the three routes |
| `lemely/web/routers/practice_hub.py` | `GET /runs`, `GET /papers/{subject_code}`, `POST /papers/{paper_id}`, and `get_practice_hub_service` |
| `tests/test_practice_hub_repo.py` | service tests on a throwaway Postgres |
| `tests/test_web_practice_hub.py` | route tests: shapes, status codes, role gate |
| `web/src/lib/practiceHubTypes.ts` | wire types for runs, papers and the student quiz list (homework) |
| `web/src/lib/practiceHubKeys.ts` | query keys and request paths, pure and unit-tested |
| `web/src/lib/hooks/usePracticeHubApi.ts` | TanStack hooks |
| `web/src/portals/student/screens/practice/practiceCopy.ts` | `plural`, `topicLabel`, `tryOthers`, `subjectDotColor` |
| `.../practice/hub/hubModel.ts` | hub view model: state, subtitle, Binny, tiles, homework, win-back, recent |
| `.../practice/hub/usePracticeHubData.ts` | composes the queries into `HubInput`, the builder subject list and `refetchAll` |
| `.../practice/hub/HubLayout.tsx`, `HubTiles.tsx`, `HomeworkRow.tsx`, `WinBackList.tsx`, `RecentRuns.tsx`, `HubStates.tsx`, `useWide.ts` | hub UI pieces |
| `.../practice/PracticeHub.tsx` | the screen: layout plus the builder sheet driven by the URL |
| `.../practice/builder/builderModel.ts` | builder draft, filters, availability line, CTA, notes |
| `.../practice/builder/SetBuilderSheet.tsx`, `TopicChips.tsx`, `CountStepper.tsx`, `AvailabilityLine.tsx`, `MoreFilters.tsx`, `SubjectChoice.tsx` | builder UI |
| `.../practice/papers/papersModel.ts` | past papers groups, rows, sheet copy and state |
| `.../practice/papers/PastPapers.tsx`, `PastPaperSheet.tsx` | past papers UI |
| `.../practice/practiceIcons.tsx` | the mock's drawn SVG icons |
| `web/tests/unit/practiceHubKeys.test.ts`, `practiceHubModel.test.ts`, `practiceBuilderModel.test.ts`, `practicePapersModel.test.ts`, `practiceCopy.test.ts` | Vitest |
| `web/e2e/practice-hub.spec.ts` | Playwright happy path |

---

## Keep-list (live features that must survive)

Sources: `web/src/portals/student/screens/practice/PracticeGenerator.tsx` (PG), `practiceData.ts` (PD), `web/src/lib/hooks/usePracticeApi.ts` (UA), `lemely/web/routers/practice.py` (PR), `web/src/portals/student/index.tsx` (IX), `shell.tsx` (SH) and `data.ts` (DT). The final task ticks each item.

| # | Live feature | Where (file:line) | Carried by |
|---|---|---|---|
| K1 | Deep link `/student/practice/:subjectCode` opens practice for that subject | IX:395-398 | The route still mounts and opens the hub with the builder sheet for that subject (Task 9, Task 11) |
| K2 | Sidebar subject tree "Practice" row per subject | SH:96 | Unchanged link, which now opens the sheet (K1) |
| K3 | Links from Home, Study plan and PaperResult to `/student/practice/:code` | `home/model.ts:126`, `studyPlanData.ts:279`, `StudyPlanWeek.tsx:371`, `PaperResult.tsx:534` | K1. PaperResult's `?topic=` param, which the live screen ignored, now preselects that topic (`initialDraft` focusTopic). |
| K4 | Subject name in the heading, from reference data | PG:41,211 | Sheet subject chips are named by `subjectNameFor` |
| K5 | Count control 5..30 in steps of 5, default 10 | PG:48,220-228 | `CountStepper` with `COUNT_MIN/MAX/STEP/DEFAULT` (Task 6) |
| K6 | Source filter: All, Past papers, Your marked papers, Lemely's practice bank, single-select | PG:241-266, `practiceSources.ts` | "Difficulty and source" fold, a radiogroup over `PRACTICE_SOURCES` (Task 9) |
| K7 | "Weak topics only": the server derives the weak set and ignores the topic selection | PG:268-283, PR:216-219 | Switch. With no chip picked it sends `weakTopicsOnly: true`, so the server derives the set (`draftToFilters`, Task 6). |
| K8 | Topic chips grouped by `syllabusGroup`, parent and child kept as distinct rows | PG:293-327, PD:48-61 | `visibleTopicGroups` uses `groupTopicsBySyllabusGroup`. A group heading shows when there is more than one group. |
| K9 | Each chip shows its `availableCount` | PG:310 | Chip shows the full topic text plus a Mono count |
| K10 | `marksLost` per topic, omitted when 0 | PG:316-320 | A chip with `marksLost > 0` uses the weak tone, and the hub's Win marks back rows show `+N marks` |
| K11 | Weak prefill exactly once, never reverted by a refetch, only servable topics | PG:66-73, PD:90-102 | `initialDraft` runs once per subject, guarded by a ref (Task 9) |
| K12 | Dropped weak topics are named, not swallowed | PG:328-338 | `droppedNote` (Task 6) |
| K13 | Untopiced count note | PG:339-346 | `untopicedNote` (Task 6) |
| K14 | Difficulty band toggles from `reference.difficultyBands`. None picked means no filter. | PG:350-374 | "Difficulty and source" fold, toggle chips (Task 9) |
| K15 | Live preview re-fetches on every filter change, with no write | PG:92, UA:39-55 | Same `usePracticePreview` hook and the same query key |
| K16 | "Checking what matches…" while the preview is pending | PG:429-430 | `line.tone === "wait"` |
| K17 | Preview failure shown inline, not as a page error | PG:431-434 | `line.tone === "error"` |
| K18 | Tri-state availability: available, shortfall (still creatable), unavailable | PD:107-142, PG:376-405 | `practiceAvailabilityView`, then the line and CTA in `builderView` |
| K19 | A specific message per refusal reason, and an unknown reason is still named | PD:154-174 | `unavailableText` (Task 6) |
| K20 | Shortfall CTA states the real count | PG:422-423 | "Start with N" |
| K21 | Create pending state | PG:420 | "Making your set…", disabled |
| K22 | 409 race: show the refusal from `err.detail` | PG:119-129 | `race` state fed into `builderView` |
| K23 | Other create failure: inline error and a preview refetch | PG:126-127,407-411 | `errorBanner` "Couldn't make this set. Try again." plus `previewQuery.refetch()` |
| K24 | Created set: Start now leads to `/student/practice/set/:id`, Print instead to `/student/practice/print/:id` | PG:178-191 | CTA and the "Print instead" link create, then navigate (Task 9) |
| K25 | Created set fewer than asked: say so | PG:172-174 | `createdToast` (Task 6) |
| K26 | Topics loading skeleton | PG:137-143 | `body === "loading"`: chip ghosts |
| K27 | Topics load failure | PG:155-158 | `body === "topicsError"`: inline error with Try again |
| K28 | Missing subject (malformed link) | PG:147-154 | Unreachable now: the hub route never needs a subject. A sheet with no subjects shows "Pick your subjects first" and links to `/student/onboard`. |
| K29 | No servable topics for the subject | PG:296-299 | `body === "noQuestions"` (CB3) |
| K30 | Role gate: students only. Ownership: export and result return 403/404. | PR:50-52,303-342 | Untouched. New routes use the same `require_role(Role.student)` and caller-scoped queries. |
| K31 | Breadcrumb `Home / Practice / <code>` and the sidebar subject highlight on the practice route | DT:189-190, DT:89-97 | The crumb becomes `Home / Practice`, because the page is the hub. `currentSubjectCode` still returns the code. Practice is now linked. |
| K32 | e2e acceptance: the generated set targets the seeded weakness; bare account refused; 0580 refused | `web/e2e/phase4-practice.spec.ts` | Spec rewritten against the sheet with the same three measurements (Task 12) |
| K33 | Audit registry S-20 captures (default, no-questions, no-weaknesses) | `web/scripts/audit.mjs:2007-2060` | Entries updated to the new copy and the switch (Task 12) |

---

## Frame-to-state table

All frames live in `practice-hub-final.html`. Phone frames are 390px. Tablet (768–1279) uses the phone order with four tiles in a row. Desktop is ≥1024 content, with the shell rail at ≥1280.

| Frame | Real state | Breakpoint | Trigger |
|---|---|---|---|
| CF | `view.state === "normal"` with `view.homework` | all; desktop arrangement is CDK | a teacher quiz that is open, `not_started`/`in_progress`, with a teacher |
| CN | `"normal"`, no homework | all | as CF, with no open homework |
| CS | `"sparse"` | all | the sum of `subjects[].papers` is 1. One topic row, the scan tip, Binny "Good start. Try one set." |
| CZ | `"firstTime"` | all | 0 papers and 0 runs. Tiles read "Pick any topic" and "Make your first deck". Binny open, walkthrough, "Scan a paper". |
| CL | `"loading"` | all | overview, runs or any subject's topics still pending |
| CE | `"error"` | all | overview, runs or any topics query errored. Tiles still work. "Try again" refetches all. |
| PS | builder `body === "ready"`, line `ok` | phone bottom sheet; adaptive side panel ≥640 | `/student/practice/:code` |
| CB1 | builder line `wait` | same | preview pending |
| CB2 | builder line `short`, CTA "Start with N" | same | `availableCount < requestedCount` |
| CB3 | builder `body === "noQuestions"`, CTA disabled, no print link | same | topics empty and `untopicedCount === 0` |
| CB4 | builder `errorBanner`, CTA "Try again" | same | create failed with a non-409 error |
| PP | `PastPapers` with `state === "ready"` | all; desktop centres an 880px list | `/student/practice/papers` |
| PQ | `PastPaperSheet` open | phone bottom sheet; adaptive ≥640 | tap a paper row |
| CDK | hub desktop arrangement: homework and Binny row, four tiles, two columns | ≥1024 | width |

States the mock does not draw, each built in the mock's own idiom:
- the builder's topics error (`errl`)
- the builder's no-weaknesses line
- the past papers loading (`GhostRows`), error (`err2`) and empty (`err2` with the CB3 copy pattern) states
- the past paper create error (`errl`)
- the homework "+N more" suffix

---

## Interactions and motion

Values come from `ph.css`, `t.css`, `pr.css` and `base.css`. `--ease` is `cubic-bezier(.2,.8,.2,1)`, which equals the `--ease-out` token, so the Tailwind class is `ease-out`.

| Interaction | Values | Reduced motion |
|---|---|---|
| Tile press | `:active { transform: scale(.97) }`, `transition: transform .15s ease-out` (`.ptile`) | no transition, no scale (`motion-reduce:transition-none motion-reduce:active:scale-100`) |
| Tile hover (tinted) | `filter: brightness(.98)` | kept (not motion) |
| Row hover | title colour turns `primary` (`.wmr:hover b`) | kept |
| Focus | `outline: 2.5px solid primary; outline-offset: 2px; radius 16px` | kept |
| Builder or paper sheet open | the shell's sheet motion (`BottomSheetSurface` on native, Radix slide on web). The mock's `rvup .45s ease-out from translateY(40%) opacity .4` is the reference, and the shell wins (master rule). | the shell's own `motion-reduce` handling |
| Switch thumb | `translateX(20px)`, `.2s ease-out` (`.sw::after`). The existing `Switch` uses its own token timing. | the `Switch` component's own handling |
| Topic chip hover | `translate: 0 -2px`, `.2s ease-out` (`.tm`) | `motion-reduce:hover:translate-y-0` |
| "Checking" spinner | 14px ring, `border 2px outline`, top `primary`, `rotate 360deg .8s linear infinite` | `motion-reduce:animate-none` (static ring) |
| Skeleton shimmer | `skm 1.4s linear infinite` (existing `Skeleton`) | existing `motion-reduce` |
| Binny | `motion="idle"` on hub states, `"pop"` on first run (F1 maps reduced motion to `none`) | F1 |
| Count stepper | value swaps instantly. The mock has no animation. | n/a |

---

## Mock class to token mapping

| Mock | Tailwind / token |
|---|---|
| `--p` `#042f4f` | `text-primary` / `bg-primary` |
| `--pc` | `bg-primary-container` |
| `--ink` | `text-on-surface` |
| `--v` | `text-on-surface-variant` |
| `--ov` hairline | `HairRow` (F1). Elsewhere `shadow-[0_-1px_0_var(--color-outline-variant)]`. |
| `--o` | `border-outline` |
| `--ok` / `--okc` | `text-success-text` / `bg-success-container` |
| `--errc` / `--onerrc` | `bg-error-container` / `text-on-error-container` |
| `.avl.no` `oklch(.42 .09 70)` | `text-on-tertiary-container` (nearest token, listed in the PR) |
| `#fff` surfaces | `bg-surface-container-lowest` |
| Schibsted / JetBrains / Bricolage | `font-sans` / `font-mono` / `font-display` |
| `.sjhd h1` 800 28px Bricolage | `font-display text-[28px] font-extrabold leading-[1.1] tracking-[-0.03em] text-primary` |
| `.dtop h1` 32px | `lg:text-[32px]` |
| `.sjhd .s` 500 13px | `text-[13px] font-medium text-on-surface-variant` |
| `.sjh2` 800 18px | `text-[18px] font-extrabold tracking-[-0.01em] text-on-surface` |
| `.sh2` 800 22px | `text-[22px] font-extrabold text-on-surface` |
| `.ptile` radius 20, padding 14, min-height 124 (tinted) / 140 (four-up) | `Tile` (F1). The grid is `grid-cols-2 gap-2.5 md:grid-cols-4 md:gap-3`. |
| `.hwr` | `grid min-h-[60px] grid-cols-[40px_minmax(0,1fr)_18px] items-center gap-3 rounded-2xl bg-primary-container px-3 py-2.5` |
| `.sic` 40px radius 13 | `grid size-10 place-items-center rounded-[13px]` |
| `.plus` 800 17px Mono, `small` 600 12px | `font-mono text-[17px] font-extrabold leading-none text-primary` + `text-[12px] font-semibold font-sans text-on-surface-variant` |
| `.rsm` 700 14px | `text-[14px] font-bold text-primary min-h-11 inline-flex items-center` |
| `.psc` 700 14px Mono ok | `font-mono text-[14px] font-bold text-success-text` |
| `.sfilt button` 40px h, radius 12, ring 1.5 ov, selected bg p | `min-h-11 rounded-xl px-3.5 text-[13.5px] font-semibold shadow-[inset_0_0_0_1.5px_var(--color-outline-variant)] bg-surface-container-lowest aria-checked:bg-primary aria-checked:text-on-primary aria-checked:shadow-none` |
| `.tm` 40px (44 on phone), radius 12, 600 13.5px | `min-h-11 rounded-xl px-3 text-[13.5px] font-semibold` |
| `.tm.w` / `.tm.sel` | `bg-error-container text-on-error-container` / `shadow-[inset_0_0_0_2px_var(--color-on-error-container)]` |
| `.tm` neutral (not weak) | `bg-surface-container-low text-on-surface shadow-[inset_0_0_0_1px_var(--color-outline-variant)]` |
| `.stepr button` 44px radius 14 pc, `.val` 800 26px Bricolage | `size-11 rounded-[14px] bg-primary-container text-primary text-xl font-bold` / `font-display text-[26px] font-extrabold text-primary tabular-nums` |
| `.avl` 600 13.5px ok | `flex items-center gap-1.5 text-[13.5px] font-semibold text-success-text` |
| `.errl` | `rounded-xl bg-error-container px-3 py-2.5 text-[13.5px] font-semibold leading-[1.35] text-on-error-container` |
| `.btn.big4.go2` 50px, radius 18, full width | `Button` (existing, `variant="primary" size="lg"`) plus `min-h-[50px] w-full rounded-[18px] text-[15.5px]` |
| `.lnk.q.tc` | `inline-flex min-h-11 items-center justify-center gap-1.5 text-[14px] font-semibold text-on-surface-variant` |
| `.err2 h2` 800 28px Bricolage | `font-display text-[28px] font-extrabold leading-[1.15] tracking-[-0.02em] text-primary text-balance` |
| `.hint2` 500 14px | `text-[14px] font-medium leading-[1.4] text-on-surface-variant text-pretty` |
| `.pcols` gap 40 | `lg:grid-cols-2 lg:gap-x-10` |
| `.sdot` 8px | `SubjectDot`: `inline-block size-2 rounded-full me-1.5 align-[1px]` with `subjectDotColor` |
| `.ppopt button` radius 16, ring 1.5 ov; `.on` ring 2 p + bg pc | `grid min-h-[60px] grid-cols-[40px_minmax(0,1fr)] items-center gap-3 rounded-2xl px-3 py-2.5 text-start bg-surface-container-lowest shadow-[inset_0_0_0_1.5px_var(--color-outline-variant)] aria-checked:bg-primary-container aria-checked:shadow-[inset_0_0_0_2px_var(--color-primary)]` |

Subject dots: the mock uses `--gA` for Maths and two off-token hues. `subjectDotColor` picks by subject order from `var(--color-grade-a)`, `var(--color-primary)`, `var(--color-on-tertiary-container)` and `var(--color-outline)`. Token changes are banned, so these are the nearest tokens, and the PR lists the swap.

---

## Backend tasks

### Task 1: `PracticeHubService.runs()`, the student's recent practice runs

**Files:**
- Create: `lemely/db/practice_hub_repo.py`
- Test: `tests/test_practice_hub_repo.py`

**Interfaces:**
- Consumes: the models `Quiz`, `QuizAssignment`, `QuizQuestion`, `QuizSubmission`, `QuizAnswer` and `Attempt`, plus `PracticeError` from `lemely.db.practice_repo`.
- Produces:
  - `PracticeHubService(sessionmaker)`
  - `.runs(student_id: uuid.UUID | str, *, limit: int = 10) -> list[PracticeRun]`, which raises `ValueError` outside 1..50
  - `PracticeRun` (frozen dataclass): `assignment_id: uuid.UUID`, `subject_code: str`, `title: str`, `topics: list[str]` (by frequency, ties broken by first position), `status: str` (`not_started|in_progress|submitted|marked`), `question_count: int`, `answered_count: int`, `awarded_marks: int | None`, `maximum_marks: int | None`, `time_limit_minutes: int | None`, `last_activity_at: datetime`
  - `RUNS_LIMIT_MAX = 50`

- [ ] **Step 1: Write the failing tests**

```python
"""Service tests for :mod:`lemely.db.practice_hub_repo` (L4 Practice tab).

Throwaway Postgres per test (mirrors ``tests/test_web_practice.py``), skipped
when no local server is reachable.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.db.base import Base
from lemely.db.models import User
from lemely.db.models.attempts import Attempt
from lemely.db.models.enums import (
    AttemptOrigin,
    QuestionDifficulty,
    QuizKind,
    QuizQuestionStatus,
    QuizStatus,
    QuizSubmissionStatus,
    Role,
)
from lemely.db.models.quizzes import Quiz, QuizAnswer, QuizAssignment, QuizQuestion, QuizSubmission
from lemely.db.practice_hub_repo import RUNS_LIMIT_MAX, PracticeHubService
from lemely.runtime.config import DatabaseSettings

if TYPE_CHECKING:
    from collections.abc import Iterator

T0 = datetime(2026, 11, 10, 9, 0, tzinfo=UTC)


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
def sm() -> Iterator[sessionmaker[Session]]:
    base_url = DatabaseSettings().url
    if not _server_reachable(base_url):
        pytest.skip("local Postgres not reachable")
    admin = create_engine(make_url(base_url).set(database="postgres"), isolation_level="AUTOCOMMIT")
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


@pytest.fixture
def service(sm: sessionmaker[Session]) -> PracticeHubService:
    return PracticeHubService(sm)


def _user(sm: sessionmaker[Session], role: Role = Role.student) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=role))
    return uid


def _set(
    sm: sessionmaker[Session],
    student: uuid.UUID,
    *,
    topics: list[str | None],
    assigned_at: datetime = T0,
    kind: QuizKind = QuizKind.practice,
    subject_code: str = "0625",
    status: QuizSubmissionStatus | None = None,
    answers: list[str] | None = None,
    answered_at: datetime | None = None,
    marks: tuple[int, int] | None = None,
) -> uuid.UUID:
    """One self-assigned set; returns the assignment id."""
    with sm.begin() as session:
        quiz = Quiz(
            teacher_id=None,
            student_id=student,
            kind=kind,
            subject_code=subject_code,
            title="Physics Practice Set",
            status=QuizStatus.assigned,
        )
        session.add(quiz)
        session.flush()
        assignment = QuizAssignment(
            quiz_id=quiz.id, class_id=None, student_id=student, assigned_by=student, assigned_at=assigned_at
        )
        session.add(assignment)
        questions = []
        for position, topic in enumerate(topics, start=1):
            qq = QuizQuestion(
                quiz_id=quiz.id,
                question_ref=f"q{position}",
                position=position,
                status=QuizQuestionStatus.included,
                topic=topic,
                difficulty=QuestionDifficulty.standard,
                question_type="short",
                prompt=f"Question {position}",
                mark_scheme_points=[],
                total_marks=2,
            )
            session.add(qq)
            questions.append(qq)
        session.flush()
        if status is not None:
            attempt_id = None
            if marks is not None:
                attempt = Attempt(
                    user_id=student,
                    subject_code=subject_code,
                    awarded_marks=marks[0],
                    maximum_marks=marks[1],
                    percentage=100.0 * marks[0] / marks[1],
                    recorded_at=assigned_at,
                    origin=AttemptOrigin.quiz,
                )
                session.add(attempt)
                session.flush()
                attempt_id = attempt.id
            submission = QuizSubmission(
                assignment_id=assignment.id,
                student_id=student,
                status=status,
                started_at=assigned_at,
                submitted_at=assigned_at if status in (QuizSubmissionStatus.submitted, QuizSubmissionStatus.marked) else None,
                marked_at=assigned_at if status == QuizSubmissionStatus.marked else None,
                attempt_id=attempt_id,
            )
            session.add(submission)
            session.flush()
            for qq, text in zip(questions, answers or [], strict=False):
                session.add(
                    QuizAnswer(
                        submission_id=submission.id,
                        quiz_question_id=qq.id,
                        answer_text=text,
                        answered_at=answered_at or assigned_at,
                    )
                )
        return assignment.id


def test_no_runs_is_an_empty_list(service: PracticeHubService, sm: sessionmaker[Session]) -> None:
    assert service.runs(_user(sm)) == []


def test_a_fresh_set_is_not_started_with_topics_by_frequency(
    service: PracticeHubService, sm: sessionmaker[Session]
) -> None:
    student = _user(sm)
    aid = _set(sm, student, topics=["2 Waves", "1 Motion", "1 Motion", None])
    [run] = service.runs(student)
    assert run.assignment_id == aid
    assert run.status == "not_started"
    assert run.question_count == 4
    assert run.answered_count == 0
    assert run.topics == ["1 Motion", "2 Waves"]
    assert run.awarded_marks is None
    assert run.maximum_marks is None
    assert run.title == "Physics Practice Set"
    assert run.subject_code == "0625"


def test_in_progress_counts_only_non_blank_answers(service: PracticeHubService, sm: sessionmaker[Session]) -> None:
    student = _user(sm)
    _set(
        sm,
        student,
        topics=["1 Motion"] * 4,
        status=QuizSubmissionStatus.in_progress,
        answers=["12 m/s", "   ", "B"],
    )
    [run] = service.runs(student)
    assert run.status == "in_progress"
    assert run.answered_count == 2


def test_marked_run_carries_the_attempt_marks(service: PracticeHubService, sm: sessionmaker[Session]) -> None:
    student = _user(sm)
    _set(sm, student, topics=["1 Motion"] * 3, status=QuizSubmissionStatus.marked, answers=["a", "b", "c"], marks=(7, 9))
    [run] = service.runs(student)
    assert run.status == "marked"
    assert (run.awarded_marks, run.maximum_marks) == (7, 9)


def test_submitted_but_unmarked_never_shows_a_score(service: PracticeHubService, sm: sessionmaker[Session]) -> None:
    student = _user(sm)
    _set(sm, student, topics=["1 Motion"], status=QuizSubmissionStatus.submitted, answers=["a"])
    [run] = service.runs(student)
    assert run.status == "submitted"
    assert run.awarded_marks is None
    assert run.maximum_marks is None


def test_marked_without_an_attempt_reads_as_submitted(service: PracticeHubService, sm: sessionmaker[Session]) -> None:
    student = _user(sm)
    _set(sm, student, topics=["1 Motion"], status=QuizSubmissionStatus.marked, answers=["a"], marks=None)
    [run] = service.runs(student)
    assert run.status == "submitted"
    assert run.awarded_marks is None


def test_orders_by_last_activity_not_creation(service: PracticeHubService, sm: sessionmaker[Session]) -> None:
    student = _user(sm)
    older = _set(
        sm,
        student,
        topics=["1 Motion"],
        assigned_at=T0,
        status=QuizSubmissionStatus.in_progress,
        answers=["a"],
        answered_at=T0 + timedelta(days=3),
    )
    newer = _set(sm, student, topics=["2 Waves"], assigned_at=T0 + timedelta(days=1))
    assert [r.assignment_id for r in service.runs(student)] == [older, newer]
    assert service.runs(student)[0].last_activity_at == T0 + timedelta(days=3)


def test_only_the_callers_own_practice_sets(service: PracticeHubService, sm: sessionmaker[Session]) -> None:
    student = _user(sm)
    other = _user(sm)
    mine = _set(sm, student, topics=["1 Motion"])
    _set(sm, other, topics=["1 Motion"])
    _set(sm, student, topics=["1 Motion"], kind=QuizKind.placement)
    assert [r.assignment_id for r in service.runs(student)] == [mine]


def test_limit_is_honoured_and_bounded(service: PracticeHubService, sm: sessionmaker[Session]) -> None:
    student = _user(sm)
    for day in range(3):
        _set(sm, student, topics=["1 Motion"], assigned_at=T0 + timedelta(days=day))
    assert len(service.runs(student, limit=2)) == 2
    with pytest.raises(ValueError, match="limit"):
        service.runs(student, limit=0)
    with pytest.raises(ValueError, match="limit"):
        service.runs(student, limit=RUNS_LIMIT_MAX + 1)
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH=$(git rev-parse --show-toplevel) /home/sico/Code/Lemely/.venv/bin/pytest tests/test_practice_hub_repo.py -q`
Expected: collection error `ModuleNotFoundError: No module named 'lemely.db.practice_hub_repo'`.

- [ ] **Step 3: Write the service (runs part)**

Create `lemely/db/practice_hub_repo.py`:

```python
"""Practice tab reads (L4): recent practice runs, past papers, and a set built from one past paper.

Kept apart from :mod:`lemely.db.practice_repo` so the Practice-tab lane never
edits the generator module L3 also changes. The same ownership rule holds:
every run query is scoped by ``QuizAssignment.student_id == caller`` **and**
``Quiz.student_id == caller`` **and** ``Quiz.kind == practice``, so another
student's set, a teacher quiz or a placement test can never appear.

Scores are only reported for a ``marked`` submission with a real ``Attempt``
row. Anything else carries ``None`` and never a fabricated zero, the same rule
:meth:`~lemely.db.practice_repo.PracticeService.result` follows.
"""

from __future__ import annotations

import uuid
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy import func, select

from lemely.db.models.attempts import Attempt
from lemely.db.models.enums import QuizKind, QuizQuestionStatus, QuizSubmissionStatus
from lemely.db.models.quizzes import Quiz, QuizAnswer, QuizAssignment, QuizQuestion, QuizSubmission
from lemely.db.practice_repo import PracticeError

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.orm import Session, sessionmaker

RUNS_LIMIT_MAX = 50


@dataclass(frozen=True, slots=True)
class PracticeRun:
    """One practice set, as the Practice tab's "Recent" list shows it."""

    assignment_id: uuid.UUID
    subject_code: str
    title: str
    topics: list[str]
    status: str
    question_count: int
    answered_count: int
    awarded_marks: int | None
    maximum_marks: int | None
    time_limit_minutes: int | None
    last_activity_at: datetime


class PracticeHubService:
    """Reads behind the Practice tab. Constructed with a ``sessionmaker`` alone."""

    def __init__(self, sessionmaker: sessionmaker[Session]) -> None:
        """Wire the service to a session factory."""
        self._sessionmaker = sessionmaker

    def runs(self, student_id: uuid.UUID | str, *, limit: int = 10) -> list[PracticeRun]:
        """The caller's practice sets, most recent activity first.

        Last activity is the latest of: assigned, last non-blank answer,
        submitted, marked. Postgres ``GREATEST`` ignores NULL arguments, so a
        set nobody opened falls back to its assignment time.
        """
        if limit < 1 or limit > RUNS_LIMIT_MAX:
            raise ValueError(f"limit must be between 1 and {RUNS_LIMIT_MAX}, got {limit}")
        student_uuid = _as_uuid(student_id)
        with self._sessionmaker() as session:
            answered = (
                select(
                    QuizAnswer.submission_id.label("submission_id"),
                    func.count(QuizAnswer.id).label("answered"),
                    func.max(QuizAnswer.answered_at).label("last_answer_at"),
                )
                .where(func.coalesce(func.trim(QuizAnswer.answer_text), "") != "")
                .group_by(QuizAnswer.submission_id)
                .subquery()
            )
            counts = (
                select(QuizQuestion.quiz_id.label("quiz_id"), func.count(QuizQuestion.id).label("n"))
                .where(QuizQuestion.status == QuizQuestionStatus.included)
                .group_by(QuizQuestion.quiz_id)
                .subquery()
            )
            last_activity = func.greatest(
                QuizAssignment.assigned_at,
                answered.c.last_answer_at,
                QuizSubmission.submitted_at,
                QuizSubmission.marked_at,
            ).label("last_activity_at")
            stmt = (
                select(
                    QuizAssignment.id,
                    Quiz.id,
                    Quiz.subject_code,
                    Quiz.title,
                    Quiz.time_limit_minutes,
                    QuizSubmission.status,
                    Attempt.awarded_marks,
                    Attempt.maximum_marks,
                    func.coalesce(counts.c.n, 0),
                    func.coalesce(answered.c.answered, 0),
                    last_activity,
                )
                .join(Quiz, Quiz.id == QuizAssignment.quiz_id)
                .outerjoin(
                    QuizSubmission,
                    sa.and_(
                        QuizSubmission.assignment_id == QuizAssignment.id,
                        QuizSubmission.student_id == student_uuid,
                    ),
                )
                .outerjoin(answered, answered.c.submission_id == QuizSubmission.id)
                .outerjoin(Attempt, Attempt.id == QuizSubmission.attempt_id)
                .outerjoin(counts, counts.c.quiz_id == Quiz.id)
                .where(
                    QuizAssignment.student_id == student_uuid,
                    Quiz.student_id == student_uuid,
                    Quiz.kind == QuizKind.practice,
                )
                .order_by(sa.desc(last_activity), QuizAssignment.id)
                .limit(limit)
            )
            rows = session.execute(stmt).all()
            topics = _topics_by_quiz(session, [row[1] for row in rows])
            runs: list[PracticeRun] = []
            for (
                assignment_id,
                quiz_id,
                subject_code,
                title,
                time_limit,
                sub_status,
                awarded,
                maximum,
                question_count,
                answered_count,
                activity,
            ) in rows:
                status = _run_status(sub_status, awarded)
                runs.append(
                    PracticeRun(
                        assignment_id=assignment_id,
                        subject_code=subject_code,
                        title=title,
                        topics=topics.get(quiz_id, []),
                        status=status,
                        question_count=int(question_count),
                        answered_count=int(answered_count),
                        awarded_marks=awarded if status == "marked" else None,
                        maximum_marks=maximum if status == "marked" else None,
                        time_limit_minutes=time_limit,
                        last_activity_at=activity,
                    )
                )
            return runs


def _run_status(status: QuizSubmissionStatus | None, awarded: int | None) -> str:
    """``not_started`` when no submission exists. ``marked`` only with a real attempt."""
    if status is None:
        return QuizSubmissionStatus.not_started.value
    if status == QuizSubmissionStatus.marked:
        return "marked" if awarded is not None else QuizSubmissionStatus.submitted.value
    return status.value


def _topics_by_quiz(session: Session, quiz_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[str]]:
    """Each quiz's distinct topics, most frequent first, ties broken by first position."""
    if not quiz_ids:
        return {}
    rows = session.execute(
        select(QuizQuestion.quiz_id, QuizQuestion.topic)
        .where(
            QuizQuestion.quiz_id.in_(quiz_ids),
            QuizQuestion.status == QuizQuestionStatus.included,
            QuizQuestion.topic.is_not(None),
        )
        .order_by(QuizQuestion.quiz_id, QuizQuestion.position)
    ).all()
    ordered: dict[uuid.UUID, list[str]] = {}
    for quiz_id, topic in rows:
        ordered.setdefault(quiz_id, []).append(topic)
    return {quiz_id: _by_frequency(found) for quiz_id, found in ordered.items()}


def _by_frequency(topics: list[str]) -> list[str]:
    counts = Counter(topics)
    first: dict[str, int] = {}
    for index, topic in enumerate(topics):
        first.setdefault(topic, index)
    return sorted(counts, key=lambda topic: (-counts[topic], first[topic]))


def _as_uuid(value: uuid.UUID | str) -> uuid.UUID:
    """Coerce a str/UUID to :class:`uuid.UUID`, raising ``ValueError`` if invalid."""
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Identifier must be a UUID, got {value!r}") from exc


__all__ = ["RUNS_LIMIT_MAX", "PracticeError", "PracticeHubService", "PracticeRun"]
```

- [ ] **Step 4: Run the tests and watch them pass**

Run: `PYTHONPATH=$(git rev-parse --show-toplevel) /home/sico/Code/Lemely/.venv/bin/pytest tests/test_practice_hub_repo.py -q`
Expected: `9 passed`. If local Postgres is down, every test reports skipped, which is not a pass. Start Postgres and run again.

- [ ] **Step 5: Prove a test can fail, then commit**

Temporarily change `_run_status` to return `"marked"` for any marked status. Run again and expect `test_marked_without_an_attempt_reads_as_submitted` to fail. Revert, then:

```bash
PYTHONPATH=$(git rev-parse --show-toplevel) pre-commit run --files lemely/db/practice_hub_repo.py tests/test_practice_hub_repo.py
git add lemely/db/practice_hub_repo.py tests/test_practice_hub_repo.py
git commit -S -m "feat(practice): list a student's recent practice runs" -- lemely/db/practice_hub_repo.py tests/test_practice_hub_repo.py
```

### Task 2: Past papers list and a set built from one paper

**Files:**
- Modify: `lemely/db/practice_hub_repo.py` (append)
- Test: `tests/test_practice_hub_repo.py` (append)

**Interfaces:**
- Consumes:
  - `visible_bank_filter`, `renderable_bank_filter` and `_to_row` (`lemely.db.question_bank_repo`)
  - `_snapshot_bank_row` (`lemely.db.quiz_repo`)
  - `enrolled_paper_numbers` (`lemely.db.student_profile_repo`)
  - `PracticeCreated` and `PracticeNotFoundError` (`lemely.db.practice_repo`)
  - the `syllabus_papers` table (`SyllabusPaper`) for durations, which are transcribed from the syllabus and never guessed
- Produces:
  - `.past_papers(student_id, subject_code: str) -> list[PastPaperRow]`
  - `.create_from_paper(student_id, paper_id, *, timed: bool) -> PracticeCreated`
  - `PastPaperRow` (frozen dataclass): `paper_id: uuid.UUID`, `subject_code: str`, `code: str` (`"0625/41"`), `paper_number: int`, `paper_variant: int`, `session_label: str` (`"May/June 2023"`), `duration_minutes: int | None`, `total_marks: int | None`, `question_count: int`, `awarded_marks: int | None`, `maximum_marks: int | None`
  - `PastPaperUnavailableError(PracticeError)`

Rules:
- A paper is listed when it has at least one servable past-paper bank row, or when the caller has a `past_paper` attempt on it.
- The list is narrowed to the student's enrolled paper numbers when they have any (D4.9).
- Order: paper number descending, then newest session first (year, then Oct/Nov, May/June, Feb/Mar, Specimen), then variant ascending.
- Create-from-paper serves the servable rows in question-number order (the `#N` suffix of `source_question_id`). `timed=True` copies the syllabus duration into `Quiz.time_limit_minutes`, or `None` when the syllabus has no entry.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_practice_hub_repo.py`)

```python
from lemely.db.models.academic import MarkScheme, Paper, Subject
from lemely.db.models.catalogue import SyllabusPaper
from lemely.db.models.enums import DifficultySource, ExamBoard, QuestionSource, SessionMonth
from lemely.db.practice_hub_repo import PastPaperUnavailableError
from lemely.db.practice_repo import PracticeNotFoundError
from lemely.db.question_bank_repo import NewBankQuestion, QuestionBankService


def _paper(
    sm: sessionmaker[Session], *, number: int, variant: int, month: SessionMonth, year: int, scheme_max: int | None = None
) -> uuid.UUID:
    with sm.begin() as session:
        if session.scalars(sa.select(Subject).where(Subject.code == "0625")).first() is None:
            session.add(Subject(code="0625", name="Physics", board=ExamBoard.caie))
            session.flush()
        paper = Paper(
            board=ExamBoard.caie,
            subject_code="0625",
            session_month=month,
            session_year=year,
            paper_number=number,
            paper_variant=variant,
        )
        session.add(paper)
        session.flush()
        if scheme_max is not None:
            session.add(MarkScheme(paper_id=paper.id, maximum_mark=scheme_max, parsed_payload={}))
        return paper.id


def _bank(sm: sessionmaker[Session], paper_id: uuid.UUID, refs: list[int], *, prefix: str = "0625_s23_qp_41") -> None:
    QuestionBankService(sm).add_questions(
        [
            NewBankQuestion(
                subject_code="0625",
                source=QuestionSource.past_paper,
                difficulty="standard",
                difficulty_source=DifficultySource.inferred_from_marks,
                question_type="short",
                prompt=f"Calculate the speed in part {ref}.",
                total_marks=3,
                topic="1 Motion",
                source_question_id=f"{prefix}#{ref}",
                paper_id=paper_id,
            )
            for ref in refs
        ]
    )


def _timing(sm: sessionmaker[Session], *, number: int, minutes: int, total: int) -> None:
    with sm.begin() as session:
        session.add(
            SyllabusPaper(
                board=ExamBoard.caie,
                subject_code="0625",
                paper_number=number,
                name=f"Paper {number}",
                duration_minutes=minutes,
                total_marks=total,
                practical=False,
                source_document="0625 syllabus",
                source_url="https://example.org/0625.pdf",
                syllabus_version="2023-2025",
            )
        )


def _paper_attempt(sm: sessionmaker[Session], student: uuid.UUID, paper_id: uuid.UUID, awarded: int, maximum: int) -> None:
    with sm.begin() as session:
        session.add(
            Attempt(
                user_id=student,
                paper_id=paper_id,
                subject_code="0625",
                awarded_marks=awarded,
                maximum_marks=maximum,
                percentage=100.0 * awarded / maximum,
                recorded_at=T0,
                origin=AttemptOrigin.past_paper,
            )
        )


def test_past_papers_lists_servable_or_attempted_papers_in_order(
    service: PracticeHubService, sm: sessionmaker[Session]
) -> None:
    student = _user(sm)
    p41 = _paper(sm, number=4, variant=1, month=SessionMonth.may_june, year=2023, scheme_max=80)
    p42 = _paper(sm, number=4, variant=2, month=SessionMonth.oct_nov, year=2023)
    p21 = _paper(sm, number=2, variant=1, month=SessionMonth.may_june, year=2023)
    _paper(sm, number=3, variant=1, month=SessionMonth.may_june, year=2023)  # no rows, no attempt: hidden
    _bank(sm, p41, [1, 2, 3])
    _bank(sm, p42, [1], prefix="0625_w23_qp_42")
    _paper_attempt(sm, student, p21, 41, 70)
    _timing(sm, number=4, minutes=75, total=80)

    rows = service.past_papers(student, "0625")

    assert [r.paper_id for r in rows] == [p42, p41, p21]
    first, second, third = rows
    assert (first.code, first.session_label) == ("0625/42", "Oct/Nov 2023")
    assert first.duration_minutes == 75
    assert first.total_marks == 80  # from the syllabus when there is no mark scheme
    assert second.question_count == 3
    assert second.total_marks == 80
    assert (third.code, third.question_count, third.duration_minutes) == ("0625/21", 0, None)
    assert (third.awarded_marks, third.maximum_marks) == (41, 70)
    assert first.awarded_marks is None


def test_past_papers_ignore_another_students_attempt(service: PracticeHubService, sm: sessionmaker[Session]) -> None:
    student = _user(sm)
    other = _user(sm)
    p21 = _paper(sm, number=2, variant=1, month=SessionMonth.may_june, year=2023)
    _paper_attempt(sm, other, p21, 41, 70)
    assert service.past_papers(student, "0625") == []


def test_inactive_bank_rows_do_not_make_a_paper_printable(service: PracticeHubService, sm: sessionmaker[Session]) -> None:
    student = _user(sm)
    p41 = _paper(sm, number=4, variant=1, month=SessionMonth.may_june, year=2023)
    _bank(sm, p41, [1])
    with sm.begin() as session:
        session.execute(sa.text("UPDATE question_bank SET is_active = false"))
    assert service.past_papers(student, "0625") == []


def test_create_from_paper_keeps_question_order_and_titles_the_set(
    service: PracticeHubService, sm: sessionmaker[Session]
) -> None:
    student = _user(sm)
    p41 = _paper(sm, number=4, variant=1, month=SessionMonth.may_june, year=2023)
    _bank(sm, p41, [10, 2, 1])
    _timing(sm, number=4, minutes=75, total=80)

    created = service.create_from_paper(student, p41, timed=True)

    assert created.question_count == 3
    assert created.requested_count == 3
    assert created.reason is None
    with sm() as session:
        quiz = session.get(Quiz, created.quiz_id)
        assert quiz is not None
        assert quiz.kind == QuizKind.practice
        assert quiz.student_id == student
        assert quiz.title == "0625/41 · May/June 2023"
        assert quiz.time_limit_minutes == 75
        prompts = session.scalars(
            sa.select(QuizQuestion.prompt).where(QuizQuestion.quiz_id == quiz.id).order_by(QuizQuestion.position)
        ).all()
    assert prompts == [
        "Calculate the speed in part 1.",
        "Calculate the speed in part 2.",
        "Calculate the speed in part 10.",
    ]
    # The new set shows up in Recent straight away.
    assert service.runs(student)[0].assignment_id == created.assignment_id


def test_create_from_paper_untimed_has_no_limit(service: PracticeHubService, sm: sessionmaker[Session]) -> None:
    student = _user(sm)
    p41 = _paper(sm, number=4, variant=1, month=SessionMonth.may_june, year=2023)
    _bank(sm, p41, [1])
    _timing(sm, number=4, minutes=75, total=80)
    created = service.create_from_paper(student, p41, timed=False)
    with sm() as session:
        quiz = session.get(Quiz, created.quiz_id)
        assert quiz is not None
        assert quiz.time_limit_minutes is None


def test_create_from_unknown_paper_is_not_found(service: PracticeHubService, sm: sessionmaker[Session]) -> None:
    with pytest.raises(PracticeNotFoundError):
        service.create_from_paper(_user(sm), uuid.uuid4(), timed=False)


def test_create_from_paper_with_nothing_servable_is_refused(service: PracticeHubService, sm: sessionmaker[Session]) -> None:
    p21 = _paper(sm, number=2, variant=1, month=SessionMonth.may_june, year=2023)
    with pytest.raises(PastPaperUnavailableError):
        service.create_from_paper(_user(sm), p21, timed=False)
```

Before running, check two model details and adjust the helpers only (never the assertions):
- `Subject` required columns: open `lemely/db/models/academic.py` (class `Subject`). The helper passes `code`, `name` and `board`.
- `MarkScheme` required columns: same file. The helper passes `paper_id`, `maximum_mark` and `parsed_payload`.

- [ ] **Step 2: Run and watch the tests fail**

Run: `PYTHONPATH=$(git rev-parse --show-toplevel) /home/sico/Code/Lemely/.venv/bin/pytest tests/test_practice_hub_repo.py -q`
Expected: `ImportError: cannot import name 'PastPaperUnavailableError'`.

- [ ] **Step 3: Implement**

Add to the imports at the top of `lemely/db/practice_hub_repo.py`:

```python
import re

from lemely.db.models.academic import MarkScheme, Paper
from lemely.db.models.catalogue import SyllabusPaper
from lemely.db.models.enums import (
    SESSION_MONTH_LABELS,
    AttemptOrigin,
    QuestionSource,
    QuizStatus,
    SessionMonth,
)
from lemely.db.models.quizzes import QuestionBank
from lemely.db.practice_repo import PracticeCreated, PracticeNotFoundError
from lemely.db.question_bank_repo import _to_row, renderable_bank_filter, visible_bank_filter
from lemely.db.quiz_repo import _snapshot_bank_row
from lemely.db.student_profile_repo import enrolled_paper_numbers
```

Also add `from sqlalchemy import ColumnElement` inside the `TYPE_CHECKING` block. Merge these with the existing `lemely.db.models.enums`, `lemely.db.models.quizzes` and `lemely.db.practice_repo` import lines (ruff's isort will complain otherwise).

Append below `PracticeRun`:

```python
_MONTH_RANK: dict[SessionMonth, int] = {
    SessionMonth.oct_nov: 3,
    SessionMonth.may_june: 2,
    SessionMonth.feb_mar: 1,
    SessionMonth.specimen: 0,
}
_QUESTION_NUMBER = re.compile(r"#(\d+)\s*$")


class PastPaperUnavailableError(PracticeError):
    """The paper exists but has no question the bank can serve yet (→ 409)."""


@dataclass(frozen=True, slots=True)
class PastPaperRow:
    """One past paper on the Practice tab's past papers screen."""

    paper_id: uuid.UUID
    subject_code: str
    code: str
    paper_number: int
    paper_variant: int
    session_label: str
    duration_minutes: int | None
    total_marks: int | None
    question_count: int
    awarded_marks: int | None
    maximum_marks: int | None
```

Add these two methods to `PracticeHubService`:

```python
    def past_papers(self, student_id: uuid.UUID | str, subject_code: str) -> list[PastPaperRow]:
        """Papers for ``subject_code`` the caller can print, or has already done."""
        student_uuid = _as_uuid(student_id)
        with self._sessionmaker() as session:
            servable = (
                select(QuestionBank.paper_id.label("paper_id"), func.count(QuestionBank.id).label("n"))
                .where(*_servable_clauses(student_uuid))
                .group_by(QuestionBank.paper_id)
                .subquery()
            )
            stmt = (
                select(Paper, MarkScheme.maximum_mark, func.coalesce(servable.c.n, 0))
                .outerjoin(MarkScheme, MarkScheme.paper_id == Paper.id)
                .outerjoin(servable, servable.c.paper_id == Paper.id)
                .where(Paper.subject_code == subject_code)
            )
            enrolled = enrolled_paper_numbers(session, student_uuid, subject_code)
            if enrolled:
                stmt = stmt.where(Paper.paper_number.in_(enrolled))
            found = session.execute(stmt).all()
            latest = _latest_paper_attempts(session, student_uuid, [paper.id for paper, _, _ in found])
            timings = {
                number: (minutes, total)
                for number, minutes, total in session.execute(
                    select(
                        SyllabusPaper.paper_number,
                        SyllabusPaper.duration_minutes,
                        SyllabusPaper.total_marks,
                    ).where(SyllabusPaper.subject_code == subject_code)
                ).all()
            }
            keyed: list[tuple[tuple[int, int, int, int], PastPaperRow]] = []
            for paper, scheme_max, count in found:
                attempt = latest.get(paper.id)
                if int(count) == 0 and attempt is None:
                    continue
                timing = timings.get(paper.paper_number)
                row = PastPaperRow(
                    paper_id=paper.id,
                    subject_code=paper.subject_code,
                    code=_paper_code(paper),
                    paper_number=paper.paper_number,
                    paper_variant=paper.paper_variant,
                    session_label=_session_label(paper.session_month, paper.session_year),
                    duration_minutes=timing[0] if timing else None,
                    total_marks=scheme_max if scheme_max is not None else (timing[1] if timing else None),
                    question_count=int(count),
                    awarded_marks=attempt[0] if attempt else None,
                    maximum_marks=attempt[1] if attempt else None,
                )
                sort_key = (
                    -paper.paper_number,
                    -(paper.session_year or 0),
                    -_MONTH_RANK.get(paper.session_month, 0),
                    paper.paper_variant,
                )
                keyed.append((sort_key, row))
            return [row for _, row in sorted(keyed, key=lambda pair: pair[0])]

    def create_from_paper(
        self, student_id: uuid.UUID | str, paper_id: uuid.UUID | str, *, timed: bool
    ) -> PracticeCreated:
        """Self-assign a practice set made of one past paper's servable questions.

        Raises:
            PracticeNotFoundError: No paper with ``paper_id`` (→ 404).
            PastPaperUnavailableError: The paper has no servable question (→ 409).
        """
        student_uuid = _as_uuid(student_id)
        paper_uuid = _as_uuid(paper_id)
        with self._sessionmaker() as session, session.begin():
            paper = session.get(Paper, paper_uuid)
            if paper is None:
                raise PracticeNotFoundError(f"Unknown paper: {paper_uuid}")
            rows = list(
                session.scalars(
                    select(QuestionBank).where(
                        *_servable_clauses(student_uuid), QuestionBank.paper_id == paper_uuid
                    )
                ).all()
            )
            if not rows:
                raise PastPaperUnavailableError(f"Paper {paper_uuid} has no question we can serve yet")
            rows.sort(key=_question_order)
            duration = (
                session.scalar(
                    select(SyllabusPaper.duration_minutes).where(
                        SyllabusPaper.subject_code == paper.subject_code,
                        SyllabusPaper.paper_number == paper.paper_number,
                    )
                )
                if timed
                else None
            )
            quiz = Quiz(
                teacher_id=None,
                student_id=student_uuid,
                kind=QuizKind.practice,
                subject_code=paper.subject_code,
                title=f"{_paper_code(paper)} · {_session_label(paper.session_month, paper.session_year)}",
                status=QuizStatus.assigned,
                time_limit_minutes=duration,
            )
            session.add(quiz)
            session.flush()
            assignment = QuizAssignment(
                quiz_id=quiz.id, class_id=None, student_id=student_uuid, assigned_by=student_uuid
            )
            session.add(assignment)
            for position, bank_row in enumerate(rows, start=1):
                session.add(
                    _snapshot_bank_row(
                        _to_row(bank_row), quiz_id=quiz.id, question_ref=f"q{position}", position=position
                    )
                )
            session.flush()
            return PracticeCreated(
                assignment_id=assignment.id,
                quiz_id=quiz.id,
                question_count=len(rows),
                requested_count=len(rows),
                topics=sorted({row.topic for row in rows if row.topic}),
                reason=None,
            )
```

Append these module functions:

```python
def _servable_clauses(student_uuid: uuid.UUID) -> list[ColumnElement[bool]]:
    """Past-paper bank rows linked to a paper that practice may serve to this caller.

    The same visibility and renderability predicates the generator uses
    (``PracticeService._matching_clauses``), so "printable" never means
    something different here.
    """
    return [
        QuestionBank.is_active.is_(True),
        visible_bank_filter(student_uuid, ()),
        renderable_bank_filter(),
        QuestionBank.source == QuestionSource.past_paper,
        QuestionBank.paper_id.is_not(None),
    ]


def _latest_paper_attempts(
    session: Session, student_uuid: uuid.UUID, paper_ids: list[uuid.UUID]
) -> dict[uuid.UUID, tuple[int, int]]:
    if not paper_ids:
        return {}
    rows = session.execute(
        select(Attempt.paper_id, Attempt.awarded_marks, Attempt.maximum_marks)
        .where(
            Attempt.user_id == student_uuid,
            Attempt.paper_id.in_(paper_ids),
            Attempt.origin == AttemptOrigin.past_paper,
        )
        .order_by(Attempt.recorded_at.desc())
    ).all()
    latest: dict[uuid.UUID, tuple[int, int]] = {}
    for paper_id, awarded, maximum in rows:
        latest.setdefault(paper_id, (awarded, maximum))
    return latest


def _paper_code(paper: Paper) -> str:
    return f"{paper.subject_code}/{paper.paper_number}{paper.paper_variant}"


def _session_label(month: SessionMonth, year: int | None) -> str:
    label = SESSION_MONTH_LABELS[month]
    return f"{label} {year}" if year else label


def _question_order(row: QuestionBank) -> tuple[int, str, str]:
    ref = row.source_question_id or ""
    match = _QUESTION_NUMBER.search(ref)
    return (int(match.group(1)) if match else 10**6, ref, str(row.id))
```

Extend `__all__` with `"PastPaperRow"` and `"PastPaperUnavailableError"`.

- [ ] **Step 4: Run and watch the tests pass**

Run: `PYTHONPATH=$(git rev-parse --show-toplevel) /home/sico/Code/Lemely/.venv/bin/pytest tests/test_practice_hub_repo.py -q`
Expected: `16 passed`.

- [ ] **Step 5: Prove a test can fail, then commit**

Temporarily drop the `rows.sort(key=_question_order)` line. Run and expect `test_create_from_paper_keeps_question_order_and_titles_the_set` to fail. Revert, then:

```bash
PYTHONPATH=$(git rev-parse --show-toplevel) pre-commit run --files lemely/db/practice_hub_repo.py tests/test_practice_hub_repo.py
git commit -S -m "feat(practice): list printable past papers and build a set from one" -- lemely/db/practice_hub_repo.py tests/test_practice_hub_repo.py
```

### Task 3: Routes: `GET /runs`, `GET /papers/{subject_code}`, `POST /papers/{paper_id}`

**Files:**
- Create: `lemely/web/schemas_practice_hub.py`
- Create: `lemely/web/routers/practice_hub.py`
- Modify: `lemely/web/app.py` (one import inside the existing `from lemely.web.routers import (...)` block, and one `app.include_router(practice_hub.router)` right after `app.include_router(practice.router)`)
- Test: `tests/test_web_practice_hub.py`

**Interfaces:**
- Consumes: `PracticeHubService` (Tasks 1–2), `require_role`/`AuthContext`/`get_settings` (`lemely.web.deps`), `get_sessionmaker` (`lemely.db.session`), and `CreatePracticeResponseDTO` (`lemely.web.schemas_practice`).
- Produces (wire, camelCase):
  - `GET /api/student/practice/runs?limit=10` (1..50) → `{ runs: PracticeRunDTO[] }`
  - `GET /api/student/practice/papers/{subjectCode}` → `{ subjectCode, papers: PastPaperDTO[] }`
  - `POST /api/student/practice/papers/{paperId}` with body `{ timed: boolean }` → 201 `CreatePracticeResponseDTO`. 404 for an unknown paper, 409 when nothing is servable, 422 for a bad id.
  - all three: 401 without auth, 403 for a non-student
  - the dependency `get_practice_hub_service`, which tests override

No path clash with `practice.router`: its routes are `/{x}/preview`, `/{x}/topics`, `/{x}/export` and `/{x}/result`, all with a literal second segment, plus `POST ""`. `/runs` has one segment, and `/papers/{x}` never has a second segment equal to those literals.

- [ ] **Step 1: Write the failing route tests**

```python
"""Route tests for the Practice tab endpoints (L4).

The service is replaced with a stub, so these tests pin the HTTP contract:
shapes, status codes and the role gate. Service behaviour is covered by
``tests/test_practice_hub_repo.py``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from lemely.db.models.enums import Role
from lemely.db.practice_hub_repo import PastPaperRow, PastPaperUnavailableError, PracticeRun
from lemely.db.practice_repo import PracticeCreated, PracticeNotFoundError
from lemely.web import create_app
from lemely.web.deps import AuthContext, get_auth_context
from lemely.web.routers.practice_hub import get_practice_hub_service

if TYPE_CHECKING:
    from collections.abc import Iterator

STUDENT = uuid.uuid4()
RUN = PracticeRun(
    assignment_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
    subject_code="0625",
    title="Physics Practice Set",
    topics=["1 Motion"],
    status="in_progress",
    question_count=8,
    answered_count=3,
    awarded_marks=None,
    maximum_marks=None,
    time_limit_minutes=None,
    last_activity_at=datetime(2026, 11, 14, 9, 30, tzinfo=UTC),
)
PAPER = PastPaperRow(
    paper_id=uuid.UUID("22222222-2222-2222-2222-222222222222"),
    subject_code="0625",
    code="0625/41",
    paper_number=4,
    paper_variant=1,
    session_label="May/June 2023",
    duration_minutes=75,
    total_marks=80,
    question_count=18,
    awarded_marks=52,
    maximum_marks=80,
)
CREATED = PracticeCreated(
    assignment_id=uuid.UUID("33333333-3333-3333-3333-333333333333"),
    quiz_id=uuid.UUID("44444444-4444-4444-4444-444444444444"),
    question_count=18,
    requested_count=18,
    topics=["1 Motion"],
    reason=None,
)


class StubService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.create_error: Exception | None = None

    def runs(self, student_id: str, *, limit: int = 10) -> list[PracticeRun]:
        self.calls.append(("runs", (student_id, limit)))
        return [RUN]

    def past_papers(self, student_id: str, subject_code: str) -> list[PastPaperRow]:
        self.calls.append(("papers", (student_id, subject_code)))
        return [PAPER]

    def create_from_paper(self, student_id: str, paper_id: str, *, timed: bool) -> PracticeCreated:
        self.calls.append(("create", (student_id, paper_id, timed)))
        if self.create_error is not None:
            raise self.create_error
        uuid.UUID(paper_id)  # mirrors the real service's id validation
        return CREATED


@pytest.fixture
def stub() -> StubService:
    return StubService()


@pytest.fixture
def client(stub: StubService) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_practice_hub_service] = lambda: stub
    yield TestClient(app)
    app.dependency_overrides.clear()


def _as(client: TestClient, role: Role) -> None:
    client.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[union-attr]
        user_id=str(STUDENT), role=role.value
    )


def test_runs_shape_and_default_limit(client: TestClient, stub: StubService) -> None:
    _as(client, Role.student)
    res = client.get("/api/student/practice/runs")
    assert res.status_code == 200
    assert res.json() == {
        "runs": [
            {
                "assignmentId": "11111111-1111-1111-1111-111111111111",
                "subjectCode": "0625",
                "title": "Physics Practice Set",
                "topics": ["1 Motion"],
                "status": "in_progress",
                "questionCount": 8,
                "answeredCount": 3,
                "awardedMarks": None,
                "maximumMarks": None,
                "timeLimitMinutes": None,
                "lastActivityAt": "2026-11-14T09:30:00+00:00",
            }
        ]
    }
    assert stub.calls == [("runs", (str(STUDENT), 10))]


@pytest.mark.parametrize("limit", [0, 51])
def test_runs_limit_out_of_range_is_422(client: TestClient, limit: int) -> None:
    _as(client, Role.student)
    assert client.get(f"/api/student/practice/runs?limit={limit}").status_code == 422


def test_papers_shape(client: TestClient, stub: StubService) -> None:
    _as(client, Role.student)
    res = client.get("/api/student/practice/papers/0625")
    assert res.status_code == 200
    assert res.json() == {
        "subjectCode": "0625",
        "papers": [
            {
                "paperId": "22222222-2222-2222-2222-222222222222",
                "code": "0625/41",
                "subjectCode": "0625",
                "paperNumber": 4,
                "paperVariant": 1,
                "sessionLabel": "May/June 2023",
                "durationMinutes": 75,
                "totalMarks": 80,
                "questionCount": 18,
                "awardedMarks": 52,
                "maximumMarks": 80,
            }
        ],
    }
    assert stub.calls == [("papers", (str(STUDENT), "0625"))]


def test_create_from_paper_201(client: TestClient, stub: StubService) -> None:
    _as(client, Role.student)
    res = client.post("/api/student/practice/papers/22222222-2222-2222-2222-222222222222", json={"timed": True})
    assert res.status_code == 201
    assert res.json()["assignmentId"] == "33333333-3333-3333-3333-333333333333"
    assert res.json()["questionCount"] == 18
    assert stub.calls == [("create", (str(STUDENT), "22222222-2222-2222-2222-222222222222", True))]


def test_create_from_paper_defaults_to_untimed(client: TestClient, stub: StubService) -> None:
    _as(client, Role.student)
    res = client.post("/api/student/practice/papers/22222222-2222-2222-2222-222222222222", json={})
    assert res.status_code == 201
    assert stub.calls[0][1][2] is False


def test_create_from_unknown_paper_404(client: TestClient, stub: StubService) -> None:
    _as(client, Role.student)
    stub.create_error = PracticeNotFoundError("Unknown paper")
    assert client.post(f"/api/student/practice/papers/{uuid.uuid4()}", json={}).status_code == 404


def test_create_from_unservable_paper_409(client: TestClient, stub: StubService) -> None:
    _as(client, Role.student)
    stub.create_error = PastPaperUnavailableError("nothing servable")
    assert client.post(f"/api/student/practice/papers/{uuid.uuid4()}", json={}).status_code == 409


def test_create_from_paper_bad_id_422(client: TestClient) -> None:
    _as(client, Role.student)
    assert client.post("/api/student/practice/papers/not-a-uuid", json={}).status_code == 422


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/student/practice/runs"),
        ("get", "/api/student/practice/papers/0625"),
        ("post", "/api/student/practice/papers/22222222-2222-2222-2222-222222222222"),
    ],
)
def test_teacher_is_forbidden(client: TestClient, method: str, path: str) -> None:
    _as(client, Role.teacher)
    res = client.request(method, path, json={} if method == "post" else None)
    assert res.status_code == 403


def test_unauthenticated_is_401(client: TestClient) -> None:
    assert client.get("/api/student/practice/runs").status_code == 401


def test_existing_practice_routes_still_resolve(client: TestClient) -> None:
    """The new router must not shadow the generator's preview route."""
    _as(client, Role.teacher)
    # 403 (role gate on the generator router) proves the path still routes there, not 404/405.
    assert client.get("/api/student/practice/0625/preview").status_code == 403
```

- [ ] **Step 2: Run and watch the tests fail**

Run: `PYTHONPATH=$(git rev-parse --show-toplevel) /home/sico/Code/Lemely/.venv/bin/pytest tests/test_web_practice_hub.py -q`
Expected: `ModuleNotFoundError: No module named 'lemely.web.routers.practice_hub'`.

- [ ] **Step 3: Write the schemas**

`lemely/web/schemas_practice_hub.py`:

```python
"""API DTOs for the Practice tab endpoints (L4). camelCase, mirroring ``schemas_practice.py``."""

from __future__ import annotations

from typing import Literal

from lemely.web.schemas import ApiModel

PracticeRunStatus = Literal["not_started", "in_progress", "submitted", "marked"]


class PracticeRunDTO(ApiModel):
    """One practice set in "Recent". ``awardedMarks``/``maximumMarks`` are set only when marked."""

    assignmentId: str
    subjectCode: str
    title: str
    topics: list[str]
    status: PracticeRunStatus
    questionCount: int
    answeredCount: int
    awardedMarks: int | None
    maximumMarks: int | None
    timeLimitMinutes: int | None
    lastActivityAt: str


class PracticeRunsDTO(ApiModel):
    """Response for ``GET /api/student/practice/runs``."""

    runs: list[PracticeRunDTO]


class PastPaperDTO(ApiModel):
    """One printable or already-done past paper."""

    paperId: str
    code: str
    subjectCode: str
    paperNumber: int
    paperVariant: int
    sessionLabel: str
    durationMinutes: int | None
    totalMarks: int | None
    questionCount: int
    awardedMarks: int | None
    maximumMarks: int | None


class PastPapersDTO(ApiModel):
    """Response for ``GET /api/student/practice/papers/{subject_code}``."""

    subjectCode: str
    papers: list[PastPaperDTO]


class CreateFromPaperRequestDTO(ApiModel):
    """Body for ``POST /api/student/practice/papers/{paper_id}``."""

    timed: bool = False
```

- [ ] **Step 4: Write the router**

`lemely/web/routers/practice_hub.py`:

```python
"""Practice tab endpoints (L4): recent runs and past papers.

Same ``/api/student/practice`` prefix and role gate as
:mod:`lemely.web.routers.practice`, in a separate file so the Practice-tab
lane and the practice-run lane (L3) never edit one router. The builder's
availability check is the generator's existing ``GET .../{code}/preview``,
which is reused unchanged.
"""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Query

from lemely.db.models.enums import Role
from lemely.db.practice_hub_repo import (
    RUNS_LIMIT_MAX,
    PastPaperRow,
    PastPaperUnavailableError,
    PracticeHubService,
    PracticeRun,
)
from lemely.db.practice_repo import PracticeCreated, PracticeNotFoundError
from lemely.db.session import get_sessionmaker
from lemely.web.deps import AuthContext, get_settings, require_role
from lemely.web.schemas_practice import CreatePracticeResponseDTO
from lemely.web.schemas_practice_hub import (
    CreateFromPaperRequestDTO,
    PastPaperDTO,
    PastPapersDTO,
    PracticeRunDTO,
    PracticeRunsDTO,
    PracticeRunStatus,
)

router = APIRouter(prefix="/api/student/practice", dependencies=[Depends(require_role(Role.student))])


def get_practice_hub_service() -> PracticeHubService:
    """The Practice tab service, on the process-wide session factory. Tests override this."""
    return PracticeHubService(get_sessionmaker(get_settings()))


def _run_to_dto(run: PracticeRun) -> PracticeRunDTO:
    return PracticeRunDTO(
        assignmentId=str(run.assignment_id),
        subjectCode=run.subject_code,
        title=run.title,
        topics=run.topics,
        status=cast("PracticeRunStatus", run.status),
        questionCount=run.question_count,
        answeredCount=run.answered_count,
        awardedMarks=run.awarded_marks,
        maximumMarks=run.maximum_marks,
        timeLimitMinutes=run.time_limit_minutes,
        lastActivityAt=run.last_activity_at.isoformat(),
    )


def _paper_to_dto(row: PastPaperRow) -> PastPaperDTO:
    return PastPaperDTO(
        paperId=str(row.paper_id),
        code=row.code,
        subjectCode=row.subject_code,
        paperNumber=row.paper_number,
        paperVariant=row.paper_variant,
        sessionLabel=row.session_label,
        durationMinutes=row.duration_minutes,
        totalMarks=row.total_marks,
        questionCount=row.question_count,
        awardedMarks=row.awarded_marks,
        maximumMarks=row.maximum_marks,
    )


def _created_to_dto(row: PracticeCreated) -> CreatePracticeResponseDTO:
    return CreatePracticeResponseDTO(
        assignmentId=str(row.assignment_id),
        quizId=str(row.quiz_id),
        questionCount=row.question_count,
        requestedCount=row.requested_count,
        topics=row.topics,
        reason=row.reason,
    )


@router.get("/runs", response_model=PracticeRunsDTO)
def practice_runs(
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    service: Annotated[PracticeHubService, Depends(get_practice_hub_service)],
    limit: Annotated[int, Query(ge=1, le=RUNS_LIMIT_MAX)] = 10,
) -> PracticeRunsDTO:
    """The caller's practice sets, most recent activity first (Practice tab "Recent")."""
    try:
        runs = service.runs(auth.user_id, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return PracticeRunsDTO(runs=[_run_to_dto(run) for run in runs])


@router.get("/papers/{subject_code}", response_model=PastPapersDTO)
def past_papers(
    subject_code: str,
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    service: Annotated[PracticeHubService, Depends(get_practice_hub_service)],
) -> PastPapersDTO:
    """Past papers the caller can print for ``subject_code``, or has already done."""
    try:
        rows = service.past_papers(auth.user_id, subject_code)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return PastPapersDTO(subjectCode=subject_code, papers=[_paper_to_dto(row) for row in rows])


@router.post("/papers/{paper_id}", response_model=CreatePracticeResponseDTO, status_code=201)
def create_from_paper(
    paper_id: str,
    body: CreateFromPaperRequestDTO,
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    service: Annotated[PracticeHubService, Depends(get_practice_hub_service)],
) -> CreatePracticeResponseDTO:
    """Self-assign a set made of one past paper's servable questions (past paper sheet)."""
    try:
        created = service.create_from_paper(auth.user_id, paper_id, timed=body.timed)
    except PracticeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PastPaperUnavailableError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _created_to_dto(created)


__all__ = ["get_practice_hub_service", "router"]
```

Then edit `lemely/web/app.py`. Add `practice_hub,` after `practice,` in the routers import block, and add after line 212 (`app.include_router(practice.router)`):

```python
    app.include_router(practice_hub.router)
```

- [ ] **Step 5: Run and watch the tests pass**

Run: `PYTHONPATH=$(git rev-parse --show-toplevel) /home/sico/Code/Lemely/.venv/bin/pytest tests/test_web_practice_hub.py tests/test_practice_hub_repo.py tests/test_web_practice.py -q`
Expected: all pass. `test_web_practice.py` runs too because it shares the URL prefix.

- [ ] **Step 6: Prove a test can fail, then commit**

Temporarily change `except PastPaperUnavailableError` to raise 422. Run and expect `test_create_from_unservable_paper_409` to fail. Revert. Then check whether a route-inventory or OpenAPI snapshot test exists:

```bash
TOKENSAVE_DISABLE_GREP_HOOK=1 grep -rln "openapi\|route_inventory\|all_routes" tests | head
```

Run any it lists as touched. Then:

```bash
PYTHONPATH=$(git rev-parse --show-toplevel) pre-commit run --files lemely/web/schemas_practice_hub.py lemely/web/routers/practice_hub.py lemely/web/app.py tests/test_web_practice_hub.py
git commit -S -m "feat(practice): add runs and past paper routes for the Practice tab" -- lemely/web/schemas_practice_hub.py lemely/web/routers/practice_hub.py lemely/web/app.py tests/test_web_practice_hub.py
```

---

## Frontend data layer

### Task 4: Wire types, query keys and hooks

**Files:**
- Create: `web/src/lib/practiceHubTypes.ts`
- Create: `web/src/lib/practiceHubKeys.ts`
- Create: `web/src/lib/hooks/usePracticeHubApi.ts`
- Test: `web/tests/unit/practiceHubKeys.test.ts`

**Interfaces:**
- Consumes: `request`/`ApiError` (`@/lib/api`), `PracticeTopics`/`CreatePracticeResponse` (`@/lib/practiceTypes`), and the Task 3 routes.
- Produces:
  - types `PracticeRun`, `PracticeRunStatus`, `PracticeRuns`, `PastPaper`, `PastPapers`, `StudentQuizListItem`, `StudentQuizList`
  - `practiceHubKeys`, `practiceHubPaths`, `RUNS_LIMIT`
  - hooks `usePracticeRuns()`, `usePracticeTopicsMany(codes)`, `useStudentQuizzes()`, `usePastPapers(code)`, `useCreateFromPaper()`

`practiceHubKeys.topics(code)` must equal `["practice", "topics", code]`, the key `usePracticeTopics` already uses (`usePracticeApi.ts:61`). The hub and the builder sheet then share one cached fetch per subject.

- [ ] **Step 1: Write the failing test**

```ts
import { describe, expect, it } from "vitest"
import { RUNS_LIMIT, practiceHubKeys, practiceHubPaths } from "@/lib/practiceHubKeys"

describe("practiceHubKeys", () => {
  it("shares the topics key with usePracticeTopics so one fetch serves hub and sheet", () => {
    expect(practiceHubKeys.topics("0625")).toEqual(["practice", "topics", "0625"])
  })

  it("nests every runs key under one prefix, so invalidating runsAll refreshes Recent", () => {
    expect(practiceHubKeys.runs(RUNS_LIMIT).slice(0, 2)).toEqual([...practiceHubKeys.runsAll])
  })

  it("keeps papers keyed per subject", () => {
    expect(practiceHubKeys.papers("0580")).not.toEqual(practiceHubKeys.papers("0625"))
  })
})

describe("practiceHubPaths", () => {
  it("builds the runs path with its limit", () => {
    expect(practiceHubPaths.runs(10)).toBe("/student/practice/runs?limit=10")
  })

  it("encodes path segments", () => {
    expect(practiceHubPaths.papers("06/25")).toBe("/student/practice/papers/06%2F25")
    expect(practiceHubPaths.createFromPaper("a b")).toBe("/student/practice/papers/a%20b")
  })

  it("points homework at the existing student quiz list", () => {
    expect(practiceHubPaths.homework).toBe("/student/quizzes")
  })
})
```

- [ ] **Step 2: Run and watch it fail**

Run: `cd web && npx vitest run tests/unit/practiceHubKeys.test.ts`
Expected: FAIL, `Cannot find module '@/lib/practiceHubKeys'`.

- [ ] **Step 3: Implement**

`web/src/lib/practiceHubTypes.ts`:

```ts
/*
 * Wire types for the Practice tab (L4): `lemely/web/schemas_practice_hub.py`,
 * plus the existing `GET /api/student/quizzes` list (`StudentQuizListItemDTO`,
 * `lemely/web/schemas_quiz.py`), which has had no frontend type until now.
 */

export type PracticeRunStatus = "not_started" | "in_progress" | "submitted" | "marked"

/** One practice set in "Recent". Marks are non-null only when `status === "marked"`. */
export interface PracticeRun {
  assignmentId: string
  subjectCode: string
  title: string
  /** Distinct topics, most frequent first. */
  topics: string[]
  status: PracticeRunStatus
  questionCount: number
  answeredCount: number
  awardedMarks: number | null
  maximumMarks: number | null
  timeLimitMinutes: number | null
  lastActivityAt: string
}

export interface PracticeRuns {
  runs: PracticeRun[]
}

/** One past paper the student can print, or has already done. */
export interface PastPaper {
  paperId: string
  code: string
  subjectCode: string
  paperNumber: number
  paperVariant: number
  sessionLabel: string
  durationMinutes: number | null
  totalMarks: number | null
  questionCount: number
  awardedMarks: number | null
  maximumMarks: number | null
}

export interface PastPapers {
  subjectCode: string
  papers: PastPaper[]
}

/** One row of `GET /api/student/quizzes`. `teacherName` is null for the student's own sets. */
export interface StudentQuizListItem {
  assignmentId: string
  quizTitle: string
  subjectCode: string
  className: string | null
  teacherName: string | null
  assignedAt: string
  dueAt: string | null
  closesAt: string | null
  questionCount: number
  timeLimitMinutes: number | null
  submissionStatus: string
  isOpen: boolean
  isOverdue: boolean
}

export interface StudentQuizList {
  quizzes: StudentQuizListItem[]
}
```

`web/src/lib/practiceHubKeys.ts`:

```ts
/* Query keys and request paths for the Practice tab. Pure, so Vitest can pin them. */

export const RUNS_LIMIT = 10

export const practiceHubKeys = {
  runsAll: ["practice", "runs"] as const,
  runs: (limit: number) => ["practice", "runs", limit] as const,
  papers: (subjectCode: string) => ["practice", "papers", subjectCode] as const,
  /** Identical to `usePracticeTopics`'s key (usePracticeApi.ts). */
  topics: (subjectCode: string) => ["practice", "topics", subjectCode] as const,
  homework: ["student", "quizzes"] as const,
}

export const practiceHubPaths = {
  runs: (limit: number) => `/student/practice/runs?limit=${limit}`,
  papers: (subjectCode: string) => `/student/practice/papers/${encodeURIComponent(subjectCode)}`,
  createFromPaper: (paperId: string) => `/student/practice/papers/${encodeURIComponent(paperId)}`,
  topics: (subjectCode: string) => `/student/practice/${encodeURIComponent(subjectCode)}/topics`,
  homework: "/student/quizzes",
}
```

`web/src/lib/hooks/usePracticeHubApi.ts`:

```ts
import {
  useMutation,
  useQueries,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query"
import { request } from "@/lib/api"
import { RUNS_LIMIT, practiceHubKeys, practiceHubPaths } from "@/lib/practiceHubKeys"
import type { PastPapers, PracticeRuns, StudentQuizList } from "@/lib/practiceHubTypes"
import type { CreatePracticeResponse, PracticeTopics } from "@/lib/practiceTypes"

/*
 * Practice tab hooks (L4). Same convention as `usePracticeApi.ts`: no
 * `fallback` passed to `request()`, so a backend failure is a query error the
 * screen renders, never silently empty data.
 */

/** `GET /api/student/practice/runs`: "Recent". */
export function usePracticeRuns(limit = RUNS_LIMIT): UseQueryResult<PracticeRuns, Error> {
  return useQuery({
    queryKey: practiceHubKeys.runs(limit),
    queryFn: () => request<PracticeRuns>(practiceHubPaths.runs(limit)),
  })
}

/** Topics for every subject at once (win marks back). Shares the cache key with `usePracticeTopics`. */
export function usePracticeTopicsMany(subjectCodes: readonly string[]): UseQueryResult<PracticeTopics, Error>[] {
  return useQueries({
    queries: subjectCodes.map((code) => ({
      queryKey: practiceHubKeys.topics(code),
      queryFn: () => request<PracticeTopics>(practiceHubPaths.topics(code)),
      enabled: !!code,
    })),
  })
}

/** `GET /api/student/quizzes`: the homework row reads the teacher-set entries. */
export function useStudentQuizzes(): UseQueryResult<StudentQuizList, Error> {
  return useQuery({
    queryKey: practiceHubKeys.homework,
    queryFn: () => request<StudentQuizList>(practiceHubPaths.homework),
  })
}

/** `GET /api/student/practice/papers/{code}`. */
export function usePastPapers(subjectCode: string): UseQueryResult<PastPapers, Error> {
  return useQuery({
    queryKey: practiceHubKeys.papers(subjectCode),
    queryFn: () => request<PastPapers>(practiceHubPaths.papers(subjectCode)),
    enabled: !!subjectCode,
  })
}

/** `POST /api/student/practice/papers/{paperId}`. On success, Recent refreshes. */
export function useCreateFromPaper(): UseMutationResult<
  CreatePracticeResponse,
  Error,
  { paperId: string; timed: boolean }
> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ paperId, timed }) =>
      request<CreatePracticeResponse>(practiceHubPaths.createFromPaper(paperId), {
        method: "POST",
        body: JSON.stringify({ timed }),
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: practiceHubKeys.runsAll })
    },
  })
}
```

- [ ] **Step 4: Run the test and the typecheck**

Run: `cd web && npx vitest run tests/unit/practiceHubKeys.test.ts && npm run typecheck`
Expected: 6 passed, and the typecheck exits 0.

- [ ] **Step 5: Commit**

```bash
PYTHONPATH=$(git rev-parse --show-toplevel) pre-commit run --files web/src/lib/practiceHubTypes.ts web/src/lib/practiceHubKeys.ts web/src/lib/hooks/usePracticeHubApi.ts web/tests/unit/practiceHubKeys.test.ts
git commit -S -m "feat(web): add Practice tab types, keys and hooks" -- web/src/lib/practiceHubTypes.ts web/src/lib/practiceHubKeys.ts web/src/lib/hooks/usePracticeHubApi.ts web/tests/unit/practiceHubKeys.test.ts
```

### Task 5: Shared copy helpers and the hub view model

**Files:**
- Create: `web/src/portals/student/screens/practice/practiceCopy.ts`
- Create: `web/src/portals/student/screens/practice/hub/hubModel.ts`
- Test: `web/tests/unit/practiceCopy.test.ts`, `web/tests/unit/practiceHubModel.test.ts`

**Interfaces:**
- Consumes: `PracticeRun`, `StudentQuizListItem` (Task 4), `PracticeTopics`.
- Produces:
  - `practiceCopy.ts`: `plural(n, one, many?)`, `topicLabel(topic)`, `tryOthers(names)`, `subjectDotColor(code, orderedCodes)`
  - `hubModel.ts`:
    - functions `practiceHubView(input: HubInput): HubView`, `hubState`, `winBackRows`, `recentRows`, `pickHomework`, `hubTiles`, `dayLabel`, `dueLabel`
    - types `HubInput`, `HubView`, `HubState`, `HubSubject`, `TileView`, `TileKey`, `WinBackRow`, `RecentRow`, `HomeworkView`
    - constants `RECENT_SHOWN = 4`, `WIN_BACK_SHOWN = 3`

Neither file may import a `.tsx` module (the `tsconfig.test.json` rule in the header of `practiceData.ts`).

- [ ] **Step 1: Write the failing tests**

`web/tests/unit/practiceCopy.test.ts`:

```ts
import { describe, expect, it } from "vitest"
import { plural, subjectDotColor, topicLabel, tryOthers } from "@/portals/student/screens/practice/practiceCopy"

describe("practiceCopy", () => {
  it("plural picks the singular only for exactly one", () => {
    expect(plural(1, "topic")).toBe("1 topic")
    expect(plural(0, "topic")).toBe("0 topics")
    expect(plural(3, "match", "matches")).toBe("3 matches")
  })

  it("topicLabel drops syllabus numbering but never empties a label", () => {
    expect(topicLabel("1.2 Motion")).toBe("Motion")
    expect(topicLabel("3 Waves and light")).toBe("Waves and light")
    expect(topicLabel("Vectors")).toBe("Vectors")
    expect(topicLabel("12")).toBe("12")
  })

  it("tryOthers names the other subjects, or says to check back", () => {
    expect(tryOthers([])).toBe("We're adding them. Check back soon.")
    expect(tryOthers(["Physics"])).toBe("We're adding them. Try Physics for now.")
    expect(tryOthers(["Maths", "Physics"])).toBe("We're adding them. Try Maths or Physics for now.")
    expect(tryOthers(["Maths", "Physics", "Chemistry"])).toBe(
      "We're adding them. Try Maths, Physics or Chemistry for now.",
    )
  })

  it("subjectDotColor is stable by subject order and only uses tokens", () => {
    const codes = ["0580", "0625", "0606"]
    expect(subjectDotColor("0580", codes)).toBe("var(--color-grade-a)")
    expect(subjectDotColor("0625", codes)).toBe("var(--color-primary)")
    expect(subjectDotColor("9999", codes)).toBe("var(--color-outline)")
  })
})
```

`web/tests/unit/practiceHubModel.test.ts`:

```ts
import { describe, expect, it } from "vitest"
import type { PracticeRun, StudentQuizListItem } from "@/lib/practiceHubTypes"
import type { PracticeTopics } from "@/lib/practiceTypes"
import {
  dayLabel,
  dueLabel,
  hubState,
  hubTiles,
  pickHomework,
  practiceHubView,
  recentRows,
  winBackRows,
  type HubInput,
} from "@/portals/student/screens/practice/hub/hubModel"

// Local-time constructors keep every assertion independent of the runner's TZ.
const NOW = new Date(2026, 10, 15, 12, 0) // Sun 15 Nov 2026
const iso = (y: number, m: number, d: number, h = 9) => new Date(y, m, d, h).toISOString()

const SUBJECTS = [
  { code: "0580", name: "Maths", papers: 3 },
  { code: "0625", name: "Physics", papers: 2 },
]

function topics(code: string, rows: [string, number][]): PracticeTopics {
  return {
    subjectCode: code,
    topics: rows.map(([topic, marksLost]) => ({ topic, availableCount: 10, syllabusGroup: topic, marksLost })),
    weakTopics: rows.filter(([, lost]) => lost > 0).map(([t]) => t),
    untopicedCount: 0,
  }
}

function run(over: Partial<PracticeRun>): PracticeRun {
  return {
    assignmentId: "a1",
    subjectCode: "0580",
    title: "Mathematics Practice Set",
    topics: ["Vectors"],
    status: "marked",
    questionCount: 9,
    answeredCount: 9,
    awardedMarks: 7,
    maximumMarks: 9,
    timeLimitMinutes: null,
    lastActivityAt: iso(2026, 10, 10),
    ...over,
  }
}

function homework(over: Partial<StudentQuizListItem>): StudentQuizListItem {
  return {
    assignmentId: "h1",
    quizTitle: "Vectors set",
    subjectCode: "0580",
    className: "10B",
    teacherName: "Ms Adel",
    assignedAt: iso(2026, 10, 12),
    dueAt: iso(2026, 10, 20),
    closesAt: null,
    questionCount: 8,
    timeLimitMinutes: null,
    submissionStatus: "not_started",
    isOpen: true,
    isOverdue: false,
    ...over,
  }
}

function input(over: Partial<HubInput> = {}): HubInput {
  return {
    overviewStatus: "success",
    subjects: SUBJECTS,
    topics: [
      { code: "0580", status: "success", data: topics("0580", [["Vectors", 9], ["Algebra", 0], ["2.1 Quadratic inequalities", 6]]) },
      { code: "0625", status: "success", data: topics("0625", [["3 Waves", 6]]) },
    ],
    runsStatus: "success",
    runs: [run({})],
    homework: [],
    dueTotal: 26,
    deckCount: 4,
    placement: [
      { code: "0580", available: false, minutes: null },
      { code: "0625", available: true, minutes: 10 },
    ],
    now: NOW,
    ...over,
  }
}

describe("dayLabel / dueLabel", () => {
  it("names today, yesterday, this week by weekday, and older by date", () => {
    expect(dayLabel(iso(2026, 10, 15), NOW)).toBe("Today")
    expect(dayLabel(iso(2026, 10, 14), NOW)).toBe("Yesterday")
    expect(dayLabel(iso(2026, 10, 10), NOW)).toBe("Tue")
    expect(dayLabel(iso(2026, 10, 2), NOW)).toBe("2 Nov")
  })

  it("says overdue first, then today, tomorrow, weekday, date", () => {
    expect(dueLabel({ dueAt: iso(2026, 10, 10), isOverdue: true }, NOW)).toBe("overdue")
    expect(dueLabel({ dueAt: null, isOverdue: false }, NOW)).toBeNull()
    expect(dueLabel({ dueAt: iso(2026, 10, 15, 18), isOverdue: false }, NOW)).toBe("due today")
    expect(dueLabel({ dueAt: iso(2026, 10, 16), isOverdue: false }, NOW)).toBe("due tomorrow")
    expect(dueLabel({ dueAt: iso(2026, 10, 20), isOverdue: false }, NOW)).toBe("due Friday")
    expect(dueLabel({ dueAt: iso(2026, 11, 1), isOverdue: false }, NOW)).toBe("due 1 Dec")
  })
})

describe("hubState", () => {
  it("is loading while any source is pending", () => {
    expect(hubState(input({ runsStatus: "pending" }))).toBe("loading")
    expect(hubState(input({ topics: [{ code: "0580", status: "pending" }] }))).toBe("loading")
  })

  it("prefers error over loading, so a failed source never spins forever", () => {
    expect(hubState(input({ overviewStatus: "error", runsStatus: "pending" }))).toBe("error")
    expect(hubState(input({ topics: [{ code: "0580", status: "error" }] }))).toBe("error")
  })

  it("is first time with no papers and no runs", () => {
    expect(hubState(input({ subjects: [{ code: "0580", name: "Maths", papers: 0 }], runs: [] }))).toBe("firstTime")
  })

  it("is not first time once a set has been run, even with no papers", () => {
    expect(hubState(input({ subjects: [{ code: "0580", name: "Maths", papers: 0 }] }))).toBe("normal")
  })

  it("is sparse with exactly one paper", () => {
    expect(hubState(input({ subjects: [{ code: "0580", name: "Maths", papers: 1 }] }))).toBe("sparse")
  })

  it("is normal otherwise", () => {
    expect(hubState(input())).toBe("normal")
  })
})

describe("winBackRows", () => {
  it("keeps only topics that lost marks, most marks first, labels stripped", () => {
    const rows = winBackRows(input().subjects, input().topics)
    expect(rows.map((r) => [r.label, r.subjectName, r.marks])).toEqual([
      ["Vectors", "Maths", 9],
      ["Quadratic inequalities", "Maths", 6],
      ["Waves", "Physics", 6],
    ])
  })

  it("links each row to the builder for its subject with that topic preselected", () => {
    const [first] = winBackRows(input().subjects, input().topics)
    expect(first.to).toBe("/student/practice/0580?topic=Vectors")
    const quad = winBackRows(input().subjects, input().topics)[1]
    expect(quad.to).toBe("/student/practice/0580?topic=2.1%20Quadratic%20inequalities")
  })

  it("skips a subject whose topics have not loaded", () => {
    expect(winBackRows(SUBJECTS, [{ code: "0580", status: "error" }])).toEqual([])
  })
})

describe("recentRows", () => {
  it("puts unfinished runs first, then the rest by recency", () => {
    const rows = recentRows(
      [
        run({ assignmentId: "old-done", lastActivityAt: iso(2026, 10, 9) }),
        run({ assignmentId: "new-done", lastActivityAt: iso(2026, 10, 14) }),
        run({ assignmentId: "open", status: "in_progress", answeredCount: 3, questionCount: 8, awardedMarks: null, maximumMarks: null, topics: ["Trigonometry"], lastActivityAt: iso(2026, 10, 1) }),
      ],
      SUBJECTS,
      NOW,
    )
    expect(rows.map((r) => r.assignmentId)).toEqual(["open", "new-done", "old-done"])
  })

  it("resume row says which question is next and links to the set", () => {
    const [row] = recentRows(
      [run({ status: "in_progress", answeredCount: 3, questionCount: 8, awardedMarks: null, maximumMarks: null, topics: ["Trigonometry"] })],
      SUBJECTS,
      NOW,
    )
    expect(row).toMatchObject({ kind: "resume", title: "Trigonometry", sub: "Question 4 of 8 · saved", to: "/student/practice/set/a1" })
  })

  it("never points past the last question", () => {
    const [row] = recentRows([run({ status: "in_progress", answeredCount: 8, questionCount: 8, awardedMarks: null, maximumMarks: null })], SUBJECTS, NOW)
    expect(row.sub).toBe("Question 8 of 8 · saved")
  })

  it("done row shows marks won back and the day", () => {
    const [row] = recentRows([run({})], SUBJECTS, NOW)
    expect(row).toMatchObject({ kind: "done", sub: "7 of 9 back · Tue", to: "/student/practice/result/a1", subjectName: "Maths" })
  })

  it("submitted-but-unmarked never invents a score", () => {
    const [row] = recentRows([run({ status: "submitted", awardedMarks: null, maximumMarks: null })], SUBJECTS, NOW)
    expect(row.kind).toBe("marking")
    expect(row.sub).toBe("Marking · Tue")
    expect(row.sub).not.toMatch(/\d+ of \d+/)
  })

  it("falls back to the set title when no question has a topic", () => {
    const [row] = recentRows([run({ topics: [] })], SUBJECTS, NOW)
    expect(row.title).toBe("Mathematics Practice Set")
  })
})

describe("pickHomework", () => {
  it("is null with no open teacher homework", () => {
    expect(pickHomework([], NOW)).toBeNull()
    expect(pickHomework([homework({ teacherName: null })], NOW)).toBeNull()
    expect(pickHomework([homework({ submissionStatus: "submitted" })], NOW)).toBeNull()
    expect(pickHomework([homework({ isOpen: false })], NOW)).toBeNull()
  })

  it("shows the most urgent: overdue, then soonest due", () => {
    const hw = pickHomework(
      [
        homework({ assignmentId: "later", dueAt: iso(2026, 10, 25) }),
        homework({ assignmentId: "late", isOverdue: true, dueAt: iso(2026, 10, 12) }),
        homework({ assignmentId: "soon", dueAt: iso(2026, 10, 16) }),
      ],
      NOW,
    )
    expect(hw?.assignmentId).toBe("late")
    expect(hw?.sub).toBe("Ms Adel · 8 questions · overdue · +2 more")
  })

  it("matches the mock line for a single homework", () => {
    expect(pickHomework([homework({})], NOW)).toEqual({
      assignmentId: "h1",
      title: "Homework · Vectors set",
      sub: "Ms Adel · 8 questions · due Friday",
      to: "/student/practice/set/h1",
    })
  })
})

describe("hubTiles", () => {
  const base = { firstTime: false, primarySubject: "0580", dueTotal: 26, deckCount: 4, placement: input().placement }

  it("matches the mock statuses", () => {
    expect(hubTiles(base).map((t) => [t.key, t.title, t.status, t.tone])).toEqual([
      ["set", "Practice set", "Build your own", "tide"],
      ["cards", "Flashcards", "26 due today", "violet"],
      ["paper", "Past papers", "Print or do timed", "mint"],
      ["test", "Placement test", "Find your level · 10 min", "gold"],
    ])
  })

  it("routes placement to the first subject that has a test", () => {
    expect(hubTiles(base).find((t) => t.key === "test")?.to).toBe("/student/placement/0625")
  })

  it("first time: pick any topic and make a first deck", () => {
    const tiles = hubTiles({ ...base, firstTime: true, dueTotal: 0, deckCount: 0 })
    expect(tiles[0].status).toBe("Pick any topic")
    expect(tiles[1].status).toBe("Make your first deck")
  })

  it("flashcards: caught up when nothing is due, neutral when unknown", () => {
    expect(hubTiles({ ...base, dueTotal: 0 })[1].status).toBe("All caught up")
    expect(hubTiles({ ...base, dueTotal: null, deckCount: null })[1].status).toBe("Review your cards")
  })

  it("placement: not ready and disabled when no subject has a test", () => {
    const test = hubTiles({ ...base, placement: [{ code: "0580", available: false, minutes: null }] })[3]
    expect(test).toMatchObject({ status: "Not ready yet", disabled: true, to: null })
  })

  it("no subject at all disables only the subject-bound tiles", () => {
    const tiles = hubTiles({ ...base, primarySubject: null, placement: [] })
    expect(tiles[0].disabled).toBe(true)
    expect(tiles[1].disabled).toBe(false)
    expect(tiles[2].disabled).toBe(false)
  })

  it("flashcards always opens the flashcards root (L10 makes it a route)", () => {
    expect(hubTiles(base)[1].to).toBe("/student/flashcards")
  })

  it("exposes the due count so the tile can set it in Mono, and none when nothing is due", () => {
    expect(hubTiles(base)[1].count).toBe(26)
    expect(hubTiles({ ...base, dueTotal: 0 })[1].count).toBeNull()
    expect(hubTiles(base)[0].count).toBeNull()
  })
})

describe("practiceHubView", () => {
  it("normal: subtitle counts every topic to win back, Binny names the top one", () => {
    const view = practiceHubView(input())
    expect(view.state).toBe("normal")
    expect(view.subtitle).toBe("3 topics to win back")
    expect(view.binny).toEqual({ mood: "happy", line: "Vectors first. +9 marks." })
    expect(view.primarySubject).toBe("0580")
    expect(view.allTopicsTo).toBeNull()
  })

  it("Binny's line never uses an exclamation mark (check:copy gate)", () => {
    for (const v of [practiceHubView(input()), practiceHubView(input({ subjects: [{ code: "0580", name: "Maths", papers: 1 }] }))]) {
      expect(v.binny?.line).not.toContain("!")
    }
  })

  it("shows at most three win-back rows and links All topics when there are more", () => {
    const view = practiceHubView(
      input({ topics: [{ code: "0580", status: "success", data: topics("0580", [["A", 4], ["B", 3], ["C", 2], ["D", 1]]) }] }),
    )
    expect(view.winBack).toHaveLength(3)
    expect(view.allTopicsTo).toBe("/student/subject/0580")
    expect(view.subtitle).toBe("4 topics to win back")
  })

  it("sparse: one topic, the scan tip, an encouraging line", () => {
    const view = practiceHubView(
      input({ subjects: [{ code: "0580", name: "Maths", papers: 1 }], topics: [{ code: "0580", status: "success", data: topics("0580", [["Vectors", 9]]) }], runs: [] }),
    )
    expect(view.state).toBe("sparse")
    expect(view.subtitle).toBe("1 topic to win back")
    expect(view.binny?.line).toBe("Good start. Try one set.")
    expect(view.showScanTip).toBe(true)
  })

  it("first time: open Binny with the walkthrough line, no subtitle", () => {
    const view = practiceHubView(input({ subjects: [{ code: "0580", name: "Maths", papers: 0 }], topics: [], runs: [] }))
    expect(view.state).toBe("firstTime")
    expect(view.subtitle).toBeNull()
    expect(view.binny).toEqual({ mood: "open", line: "Scan a paper and I'll find your marks to win back." })
  })

  it("normal with nothing to win back: no subtitle, a calm line", () => {
    const view = practiceHubView(input({ topics: [{ code: "0580", status: "success", data: topics("0580", [["Vectors", 0]]) }] }))
    expect(view.subtitle).toBeNull()
    expect(view.binny?.line).toBe("All caught up. Try a set.")
  })

  it("error: tiles still present, no Binny line, no subtitle", () => {
    const view = practiceHubView(input({ runsStatus: "error" }))
    expect(view.state).toBe("error")
    expect(view.tiles).toHaveLength(4)
    expect(view.binny).toBeNull()
    expect(view.subtitle).toBeNull()
  })

  it("splits recent into the first four and the rest", () => {
    const runs = Array.from({ length: 6 }, (_, i) => run({ assignmentId: `r${i}`, lastActivityAt: iso(2026, 10, 14 - i) }))
    const view = practiceHubView(input({ runs }))
    expect(view.recent).toHaveLength(4)
    expect(view.recentMore).toHaveLength(2)
  })

  it("shows homework only when set, and never while loading", () => {
    expect(practiceHubView(input()).homework).toBeNull()
    expect(practiceHubView(input({ homework: [homework({})] })).homework?.title).toBe("Homework · Vectors set")
    expect(practiceHubView(input({ homework: [homework({})], runsStatus: "pending" })).homework).toBeNull()
  })
})
```

- [ ] **Step 2: Run and watch them fail**

Run: `cd web && npx vitest run tests/unit/practiceCopy.test.ts tests/unit/practiceHubModel.test.ts`
Expected: FAIL, the modules cannot be found.

- [ ] **Step 3: Implement**

`web/src/portals/student/screens/practice/practiceCopy.ts`:

```ts
/* Small copy helpers shared by the Practice tab models (L4). Pure; no `.tsx` imports. */

export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`
}

const NUMBERING = /^\d+(?:\.\d+)*\s+/

/** "1.2 Motion" -> "Motion". Keeps the raw string if stripping would empty it. */
export function topicLabel(topic: string): string {
  const stripped = topic.replace(NUMBERING, "").trim()
  return stripped.length > 0 ? stripped : topic
}

/** The "try another subject" sentence for a subject with no questions yet. */
export function tryOthers(names: readonly string[]): string {
  if (names.length === 0) return "We're adding them. Check back soon."
  if (names.length === 1) return `We're adding them. Try ${names[0]} for now.`
  return `We're adding them. Try ${names.slice(0, -1).join(", ")} or ${names[names.length - 1]} for now.`
}

/* Nearest existing tokens to the mock's subject dots (no token changes allowed). */
const DOT_COLORS = [
  "var(--color-grade-a)",
  "var(--color-primary)",
  "var(--color-on-tertiary-container)",
] as const

export function subjectDotColor(code: string, orderedCodes: readonly string[]): string {
  const index = orderedCodes.indexOf(code)
  return index >= 0 && index < DOT_COLORS.length ? DOT_COLORS[index] : "var(--color-outline)"
}
```

`web/src/portals/student/screens/practice/hub/hubModel.ts`:

```ts
/*
 * Practice tab (L4) view model. Pure: no React, no DOM, no `.tsx` imports.
 * Every decision the hub screen makes lives here: the state, the subtitle,
 * Binny's mood and line, the tile statuses, the homework row, win marks back
 * and Recent. The screen only renders `HubView`.
 */
import type { PracticeRun, StudentQuizListItem } from "@/lib/practiceHubTypes"
import type { PracticeTopics } from "@/lib/practiceTypes"
import { plural, topicLabel } from "../practiceCopy"

export type HubQueryStatus = "pending" | "error" | "success"
export type HubState = "loading" | "error" | "firstTime" | "sparse" | "normal"

export interface HubSubject {
  code: string
  name: string
  /** Marked papers in this subject (OverviewDTO `subjects[].papers`); 0 for an enrolment with none. */
  papers: number
}

export interface HubInput {
  overviewStatus: HubQueryStatus
  subjects: readonly HubSubject[]
  topics: readonly { code: string; status: HubQueryStatus; data?: PracticeTopics }[]
  runsStatus: HubQueryStatus
  runs: readonly PracticeRun[]
  /** Empty when the list failed: the row simply hides. */
  homework: readonly StudentQuizListItem[]
  /** null when unknown (loading or failed). */
  dueTotal: number | null
  deckCount: number | null
  /** One entry per subject, in subject order. `available` null while loading. */
  placement: readonly { code: string; available: boolean | null; minutes: number | null }[]
  now: Date
}

export type TileKey = "set" | "cards" | "paper" | "test"
export type HubTileTone = "tide" | "violet" | "mint" | "gold"

export interface TileView {
  key: TileKey
  title: string
  status: string
  tone: HubTileTone
  to: string | null
  disabled: boolean
  /** The flashcards due count, rendered in Mono inside the ReactNode status; null otherwise. */
  count: number | null
}

export interface WinBackRow {
  topic: string
  label: string
  subjectCode: string
  subjectName: string
  marks: number
  to: string
}

export interface HomeworkView {
  assignmentId: string
  title: string
  sub: string
  to: string
}

export type RecentKind = "resume" | "marking" | "done"

export interface RecentRow {
  assignmentId: string
  kind: RecentKind
  title: string
  subjectCode: string
  subjectName: string
  sub: string
  to: string
}

export interface HubView {
  state: HubState
  subtitle: string | null
  binny: { mood: "happy" | "open"; line: string } | null
  homework: HomeworkView | null
  tiles: TileView[]
  winBack: WinBackRow[]
  allTopicsTo: string | null
  recent: RecentRow[]
  recentMore: RecentRow[]
  showScanTip: boolean
  primarySubject: string | null
}

export const RECENT_SHOWN = 4
export const WIN_BACK_SHOWN = 3

const DAY_MS = 86_400_000
const UNFINISHED = new Set(["not_started", "in_progress"])

function startOfDay(d: Date): number {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()
}

function dayDiff(isoString: string, now: Date): number {
  return Math.round((startOfDay(new Date(isoString)) - startOfDay(now)) / DAY_MS)
}

function shortDate(isoString: string): string {
  return new Date(isoString).toLocaleDateString("en-GB", { day: "numeric", month: "short" })
}

/** "Today", "Yesterday", "Tue" within the week, else "2 Nov". */
export function dayLabel(isoString: string, now: Date): string {
  const diff = dayDiff(isoString, now)
  if (diff === 0) return "Today"
  if (diff === -1) return "Yesterday"
  if (diff < -1 && diff > -7) return new Date(isoString).toLocaleDateString("en-GB", { weekday: "short" })
  return shortDate(isoString)
}

export function dueLabel(item: Pick<StudentQuizListItem, "dueAt" | "isOverdue">, now: Date): string | null {
  if (item.isOverdue) return "overdue"
  if (!item.dueAt) return null
  const diff = dayDiff(item.dueAt, now)
  if (diff <= 0) return "due today"
  if (diff === 1) return "due tomorrow"
  if (diff < 7) return `due ${new Date(item.dueAt).toLocaleDateString("en-GB", { weekday: "long" })}`
  return `due ${shortDate(item.dueAt)}`
}

export function hubState(input: HubInput): HubState {
  const anyError =
    input.overviewStatus === "error" || input.runsStatus === "error" || input.topics.some((t) => t.status === "error")
  if (anyError) return "error"
  const anyPending =
    input.overviewStatus === "pending" || input.runsStatus === "pending" || input.topics.some((t) => t.status === "pending")
  if (anyPending) return "loading"
  const papers = input.subjects.reduce((sum, s) => sum + s.papers, 0)
  if (papers === 0 && input.runs.length === 0) return "firstTime"
  if (papers === 1) return "sparse"
  return "normal"
}

function namesOf(subjects: readonly HubSubject[]): Map<string, string> {
  return new Map(subjects.map((s) => [s.code, s.name]))
}

export function winBackRows(subjects: readonly HubSubject[], topics: HubInput["topics"]): WinBackRow[] {
  const names = namesOf(subjects)
  const rows: WinBackRow[] = []
  for (const entry of topics) {
    if (!entry.data) continue
    for (const t of entry.data.topics) {
      if (t.marksLost <= 0) continue
      rows.push({
        topic: t.topic,
        label: topicLabel(t.topic),
        subjectCode: entry.code,
        subjectName: names.get(entry.code) ?? entry.code,
        marks: t.marksLost,
        to: `/student/practice/${entry.code}?topic=${encodeURIComponent(t.topic)}`,
      })
    }
  }
  return rows.sort((a, b) => b.marks - a.marks || a.label.localeCompare(b.label))
}

export function recentRows(runs: readonly PracticeRun[], subjects: readonly HubSubject[], now: Date): RecentRow[] {
  const names = namesOf(subjects)
  const byRecency = (a: PracticeRun, b: PracticeRun) => Date.parse(b.lastActivityAt) - Date.parse(a.lastActivityAt)
  const ordered = [
    ...runs.filter((r) => UNFINISHED.has(r.status)).sort(byRecency),
    ...runs.filter((r) => !UNFINISHED.has(r.status)).sort(byRecency),
  ]
  return ordered.map((r): RecentRow => {
    const base = {
      assignmentId: r.assignmentId,
      title: r.topics.length > 0 ? topicLabel(r.topics[0]) : r.title,
      subjectCode: r.subjectCode,
      subjectName: names.get(r.subjectCode) ?? r.subjectCode,
    }
    if (UNFINISHED.has(r.status)) {
      const next = Math.min(r.answeredCount + 1, Math.max(r.questionCount, 1))
      return { ...base, kind: "resume", sub: `Question ${next} of ${r.questionCount} · saved`, to: `/student/practice/set/${r.assignmentId}` }
    }
    const day = dayLabel(r.lastActivityAt, now)
    if (r.status === "marked" && r.awardedMarks !== null && r.maximumMarks !== null) {
      return { ...base, kind: "done", sub: `${r.awardedMarks} of ${r.maximumMarks} back · ${day}`, to: `/student/practice/result/${r.assignmentId}` }
    }
    return { ...base, kind: "marking", sub: `Marking · ${day}`, to: `/student/practice/result/${r.assignmentId}` }
  })
}

export function pickHomework(list: readonly StudentQuizListItem[], now: Date): HomeworkView | null {
  const open = list.filter((q) => q.teacherName !== null && q.isOpen && UNFINISHED.has(q.submissionStatus))
  if (open.length === 0) return null
  const sorted = [...open].sort((a, b) => {
    if (a.isOverdue !== b.isOverdue) return a.isOverdue ? -1 : 1
    const ad = a.dueAt ? Date.parse(a.dueAt) : Number.POSITIVE_INFINITY
    const bd = b.dueAt ? Date.parse(b.dueAt) : Number.POSITIVE_INFINITY
    if (ad !== bd) return ad - bd
    return Date.parse(b.assignedAt) - Date.parse(a.assignedAt)
  })
  const first = sorted[0]
  const parts = [first.teacherName as string, plural(first.questionCount, "question")]
  const due = dueLabel(first, now)
  if (due) parts.push(due)
  if (sorted.length > 1) parts.push(`+${sorted.length - 1} more`)
  return {
    assignmentId: first.assignmentId,
    title: `Homework · ${first.quizTitle}`,
    sub: parts.join(" · "),
    to: `/student/practice/set/${first.assignmentId}`,
  }
}

function cardsStatus(due: number | null, decks: number | null): string {
  if (due !== null && due > 0) return `${due} due today`
  if (decks === 0) return "Make your first deck"
  if (due === 0) return "All caught up"
  return "Review your cards"
}

export function hubTiles(input: {
  firstTime: boolean
  primarySubject: string | null
  dueTotal: number | null
  deckCount: number | null
  placement: HubInput["placement"]
}): TileView[] {
  const primary = input.primarySubject
  const available = input.placement.find((p) => p.available === true)
  const noneAvailable = input.placement.length > 0 && input.placement.every((p) => p.available === false)
  const testTo = available
    ? `/student/placement/${available.code}`
    : noneAvailable || primary === null
      ? null
      : `/student/placement/${primary}`
  return [
    {
      key: "set",
      title: "Practice set",
      status: input.firstTime ? "Pick any topic" : "Build your own",
      tone: "tide",
      to: primary ? `/student/practice/${primary}` : null,
      disabled: primary === null,
      count: null,
    },
    {
      key: "cards",
      title: "Flashcards",
      status: cardsStatus(input.dueTotal, input.deckCount),
      tone: "violet",
      to: "/student/flashcards",
      disabled: false,
      count: input.dueTotal !== null && input.dueTotal > 0 ? input.dueTotal : null,
    },
    { key: "paper", title: "Past papers", status: "Print or do timed", tone: "mint", to: "/student/practice/papers", disabled: false, count: null },
    {
      key: "test",
      title: "Placement test",
      status: available
        ? available.minutes
          ? `Find your level · ${available.minutes} min`
          : "Find your level"
        : noneAvailable
          ? "Not ready yet"
          : "Find your level",
      tone: "gold",
      to: testTo,
      disabled: testTo === null,
      count: null,
    },
  ]
}

function binnyFor(state: HubState, top: WinBackRow | undefined): HubView["binny"] {
  if (state === "firstTime") return { mood: "open", line: "Scan a paper and I'll find your marks to win back." }
  if (state === "sparse") return { mood: "happy", line: "Good start. Try one set." }
  if (state === "normal") {
    return top
      ? { mood: "happy", line: `${top.label} first. +${top.marks} marks.` }
      : { mood: "happy", line: "All caught up. Try a set." }
  }
  return null
}

export function practiceHubView(input: HubInput): HubView {
  const state = hubState(input)
  const allWinBack = winBackRows(input.subjects, input.topics)
  const primarySubject = allWinBack[0]?.subjectCode ?? input.subjects[0]?.code ?? null
  const recentAll = recentRows(input.runs, input.subjects, input.now)
  const showsContent = state === "normal" || state === "sparse"
  return {
    state,
    subtitle: showsContent && allWinBack.length > 0 ? `${plural(allWinBack.length, "topic")} to win back` : null,
    binny: binnyFor(state, allWinBack[0]),
    homework: state === "loading" ? null : pickHomework(input.homework, input.now),
    tiles: hubTiles({
      firstTime: state === "firstTime",
      primarySubject,
      dueTotal: input.dueTotal,
      deckCount: input.deckCount,
      placement: input.placement,
    }),
    winBack: showsContent ? allWinBack.slice(0, WIN_BACK_SHOWN) : [],
    allTopicsTo:
      showsContent && allWinBack.length > WIN_BACK_SHOWN ? `/student/subject/${allWinBack[0].subjectCode}` : null,
    recent: showsContent ? recentAll.slice(0, RECENT_SHOWN) : [],
    recentMore: showsContent ? recentAll.slice(RECENT_SHOWN) : [],
    showScanTip: state === "sparse",
    primarySubject,
  }
}
```

- [ ] **Step 4: Run and watch them pass**

Run: `cd web && npx vitest run tests/unit/practiceCopy.test.ts tests/unit/practiceHubModel.test.ts`
Expected: all pass. Then temporarily swap the `anyError` and `anyPending` checks in `hubState`, and expect "prefers error over loading" to fail. Revert.

- [ ] **Step 5: Commit**

```bash
PYTHONPATH=$(git rev-parse --show-toplevel) pre-commit run --files web/src/portals/student/screens/practice/practiceCopy.ts web/src/portals/student/screens/practice/hub/hubModel.ts web/tests/unit/practiceCopy.test.ts web/tests/unit/practiceHubModel.test.ts
git commit -S -m "feat(web): add the Practice tab hub view model" -- web/src/portals/student/screens/practice/practiceCopy.ts web/src/portals/student/screens/practice/hub/hubModel.ts web/tests/unit/practiceCopy.test.ts web/tests/unit/practiceHubModel.test.ts
```

### Task 6: Builder view model (replaces the generator's decisions)

**Files:**
- Create: `web/src/portals/student/screens/practice/builder/builderModel.ts`
- Test: `web/tests/unit/practiceBuilderModel.test.ts`

**Interfaces:**
- Consumes: `groupTopicsBySyllabusGroup`, `weakTopicPrefill`, `practiceAvailabilityView` and `TopicGroup` (`../practiceData`), `plural`, `topicLabel` and `tryOthers` (`../practiceCopy`), and `PracticeFilterSet`, `PracticePreview`, `PracticeTopics` and `CreatePracticeResponse`.
- Produces:
  - constants `COUNT_MIN = 5`, `COUNT_MAX = 30`, `COUNT_STEP = 5`, `COUNT_DEFAULT = 10`
  - types `BuilderDraft`, `DraftSeed`, `BuilderView`, `BuilderViewInput`, `AvailabilityLine`, `LineTone`, `BuilderBody`
  - functions `stepCount`, `initialDraft`, `toggleTopic`, `toggleBand`, `setWeakOnly`, `setSource`, `draftToFilters`, `weakServableTopics`, `visibleTopicGroups`, `builderView`, `unavailableText`, `createdToast`

Semantics of "Weak topics only" (keeps K7 honest while matching the mock):
- The switch filters the chip list to the student's servable weak topics.
- With the switch on and no chip picked, the request is `weakTopicsOnly: true`, so the server derives the weak set (and refuses with `no_weaknesses` when there is none).
- With chips picked, the request is `topics: picked, weakTopicsOnly: false`. That is exactly what the live generator sent after its prefill.
- A chip's pressed state is therefore always true to the request.

- [ ] **Step 1: Write the failing tests**

```ts
import { describe, expect, it } from "vitest"
import type { PracticePreview, PracticeTopics } from "@/lib/practiceTypes"
import {
  COUNT_DEFAULT,
  COUNT_MAX,
  COUNT_MIN,
  builderView,
  createdToast,
  draftToFilters,
  initialDraft,
  setSource,
  setWeakOnly,
  stepCount,
  toggleBand,
  toggleTopic,
  unavailableText,
  visibleTopicGroups,
  weakServableTopics,
  type BuilderViewInput,
} from "@/portals/student/screens/practice/builder/builderModel"

const TOPICS: PracticeTopics = {
  subjectCode: "0625",
  topics: [
    { topic: "1 Motion, forces and energy", availableCount: 152, syllabusGroup: "1 Motion, forces and energy", marksLost: 4 },
    { topic: "1.2 Motion", availableCount: 6, syllabusGroup: "1 Motion, forces and energy", marksLost: 0 },
    { topic: "3 Waves", availableCount: 20, syllabusGroup: "3 Waves", marksLost: 6 },
  ],
  weakTopics: ["3 Waves", "Electricity", "1 Motion, forces and energy"],
  untopicedCount: 12,
}

const preview = (over: Partial<PracticePreview>): PracticePreview => ({
  available: true,
  reason: null,
  requestedCount: 10,
  availableCount: 32,
  topics: [],
  ...over,
})

const vin = (over: Partial<BuilderViewInput> = {}): BuilderViewInput => ({
  topicsStatus: "success",
  topics: TOPICS,
  previewStatus: "success",
  preview: preview({}),
  race: null,
  creating: false,
  createFailed: false,
  subjectName: "Physics",
  otherSubjectNames: ["Maths"],
  dropped: [],
  ...over,
})

describe("count stepper", () => {
  it("steps by 5 and clamps at 5 and 30", () => {
    expect(stepCount(COUNT_DEFAULT, 1)).toBe(15)
    expect(stepCount(COUNT_MIN, -1)).toBe(COUNT_MIN)
    expect(stepCount(COUNT_MAX, 1)).toBe(COUNT_MAX)
  })
})

describe("initialDraft", () => {
  it("prefills only servable weak topics, turns the switch on, and reports the dropped ones", () => {
    const seed = initialDraft("0625", TOPICS, null)
    expect(seed.draft).toEqual({
      subjectCode: "0625",
      count: 10,
      weakOnly: true,
      selected: ["3 Waves", "1 Motion, forces and energy"],
      bands: [],
      source: null,
    })
    expect(seed.dropped).toEqual(["Electricity"])
  })

  it("a focus topic (win-back row or ?topic=) selects only that topic with the switch off", () => {
    const seed = initialDraft("0625", TOPICS, "1.2 Motion")
    expect(seed.draft.selected).toEqual(["1.2 Motion"])
    expect(seed.draft.weakOnly).toBe(false)
  })

  it("ignores a focus topic with no chip, falling back to the weak prefill", () => {
    expect(initialDraft("0625", TOPICS, "Electricity").draft.selected).toEqual(["3 Waves", "1 Motion, forces and energy"])
  })

  it("no weaknesses: switch off, nothing selected", () => {
    const seed = initialDraft("0625", { ...TOPICS, weakTopics: [] }, null)
    expect(seed.draft.weakOnly).toBe(false)
    expect(seed.draft.selected).toEqual([])
  })
})

describe("draft edits", () => {
  const draft = initialDraft("0625", TOPICS, null).draft

  it("toggles topics and bands without mutating", () => {
    const next = toggleTopic(draft, "3 Waves")
    expect(next.selected).toEqual(["1 Motion, forces and energy"])
    expect(draft.selected).toHaveLength(2)
    expect(toggleBand(toggleBand(draft, "challenge"), "challenge").bands).toEqual([])
  })

  it("turning weak-only on keeps only weak selections", () => {
    const mixed = { ...draft, weakOnly: false, selected: ["1.2 Motion", "3 Waves"] }
    expect(setWeakOnly(mixed, true, weakServableTopics(TOPICS)).selected).toEqual(["3 Waves"])
    expect(setWeakOnly(mixed, false, weakServableTopics(TOPICS)).selected).toEqual(["1.2 Motion", "3 Waves"])
  })

  it("source is single-select, null meaning all sources", () => {
    expect(setSource(draft, "past_paper").source).toBe("past_paper")
    expect(setSource(draft, null).source).toBeNull()
  })
})

describe("draftToFilters", () => {
  const draft = initialDraft("0625", TOPICS, null).draft

  it("sends picked chips as topics, never weakTopicsOnly, when something is picked", () => {
    expect(draftToFilters(draft)).toEqual({
      subjectCode: "0625",
      count: 10,
      topics: ["3 Waves", "1 Motion, forces and energy"],
      weakTopicsOnly: false,
      difficultyBands: [],
      source: null,
    })
  })

  it("weak-only with nothing picked asks the server for the weak set", () => {
    const f = draftToFilters({ ...draft, selected: [] })
    expect(f.weakTopicsOnly).toBe(true)
    expect(f.topics).toEqual([])
  })

  it("switch off with nothing picked means no topic filter at all", () => {
    const f = draftToFilters({ ...draft, weakOnly: false, selected: [] })
    expect(f).toMatchObject({ weakTopicsOnly: false, topics: [] })
  })
})

describe("visibleTopicGroups", () => {
  it("off: every servable topic, parent and child kept as distinct rows in one group", () => {
    const groups = visibleTopicGroups(TOPICS, false)
    expect(groups.map((g) => [g.syllabusGroup, g.topics.map((t) => t.topic)])).toEqual([
      ["1 Motion, forces and energy", ["1 Motion, forces and energy", "1.2 Motion"]],
      ["3 Waves", ["3 Waves"]],
    ])
  })

  it("on: only the servable weak topics", () => {
    expect(visibleTopicGroups(TOPICS, true).flatMap((g) => g.topics.map((t) => t.topic))).toEqual([
      "1 Motion, forces and energy",
      "3 Waves",
    ])
  })
})

describe("builderView", () => {
  it("ready and available: tick line, Start now, print link", () => {
    const v = builderView(vin())
    expect(v.body).toBe("ready")
    expect(v.line).toEqual({ tone: "ok", text: "32 questions match" })
    expect(v.cta).toEqual({ label: "Start now", disabled: false })
    expect(v.showPrint).toBe(true)
    expect(v.startCount).toBe(10)
  })

  it("checking (CB1) while the preview is pending", () => {
    const v = builderView(vin({ previewStatus: "pending", preview: undefined }))
    expect(v.line).toEqual({ tone: "wait", text: "Checking what matches…" })
    expect(v.cta.disabled).toBe(true)
    expect(v.showPrint).toBe(false)
  })

  it("too few match (CB2): honest count, still creatable", () => {
    const v = builderView(vin({ preview: preview({ reason: "insufficient_pool", requestedCount: 20, availableCount: 6 }) }))
    expect(v.line).toEqual({ tone: "short", text: "Only 6 questions match. Add a topic or ask for fewer." })
    expect(v.cta).toEqual({ label: "Start with 6", disabled: false })
    expect(v.startCount).toBe(6)
  })

  it("singular copy for one question", () => {
    expect(builderView(vin({ preview: preview({ requestedCount: 5, availableCount: 1 }) })).line?.text).toBe(
      "Only 1 question matches. Add a topic or ask for fewer.",
    )
  })

  it("no questions for the subject (CB3): disabled, no print link, names the other subjects", () => {
    const v = builderView(vin({ topics: { ...TOPICS, topics: [], weakTopics: [], untopicedCount: 0 } }))
    expect(v.body).toBe("noQuestions")
    expect(v.noQuestions).toEqual({ heading: "No Physics questions yet", body: "We're adding them. Try Maths for now." })
    expect(v.cta).toEqual({ label: "Start now", disabled: true })
    expect(v.showPrint).toBe(false)
  })

  it("untopiced-only subject is not 'no questions'", () => {
    expect(builderView(vin({ topics: { ...TOPICS, topics: [], untopicedCount: 4 } })).body).toBe("ready")
  })

  it("couldn't make the set (CB4): banner and Try again, preview line kept", () => {
    const v = builderView(vin({ createFailed: true }))
    expect(v.errorBanner).toBe("Couldn't make this set. Try again.")
    expect(v.cta).toEqual({ label: "Try again", disabled: false })
    expect(v.line?.tone).toBe("ok")
  })

  it("a 409 race replaces the preview with the refusal, never a generic error", () => {
    const v = builderView(vin({ race: preview({ available: false, reason: "no_questions", availableCount: 0 }), createFailed: false }))
    expect(v.line).toEqual({ tone: "none", text: "Nothing matches. Try other topics or another difficulty." })
    expect(v.cta.disabled).toBe(true)
    expect(v.errorBanner).toBeNull()
  })

  it("no weaknesses refusal tells the student how to get out of it", () => {
    const v = builderView(vin({ preview: preview({ available: false, reason: "no_weaknesses", availableCount: 0 }) }))
    expect(v.line).toEqual({ tone: "none", text: "No weak topics yet. Turn this off to pick any topic." })
  })

  it("preview failure is an inline line, not a page error", () => {
    const v = builderView(vin({ previewStatus: "error", preview: undefined }))
    expect(v.line?.tone).toBe("error")
    expect(v.body).toBe("ready")
  })

  it("creating: disabled CTA with progress copy", () => {
    expect(builderView(vin({ creating: true })).cta).toEqual({ label: "Making your set…", disabled: true })
  })

  it("topics loading and topics error", () => {
    expect(builderView(vin({ topicsStatus: "pending", topics: undefined })).body).toBe("loading")
    expect(builderView(vin({ topicsStatus: "error", topics: undefined })).body).toBe("topicsError")
  })

  it("names dropped weak topics and the untopiced pool", () => {
    expect(builderView(vin({ dropped: ["Electricity"] })).droppedNote).toBe("Electricity isn't in the question bank yet.")
    expect(builderView(vin({ dropped: ["4.1 Electricity", "unknown"] })).droppedNote).toBe(
      "2 weak topics aren't in the question bank yet: Electricity, unknown.",
    )
    expect(builderView(vin()).untopicedNote).toBe("Plus 12 untagged questions, used when no topic is picked.")
  })
})

describe("unavailableText / createdToast", () => {
  it("names an unknown reason instead of hiding it", () => {
    expect(unavailableText("pool_locked")).toBe("Not available right now (pool_locked).")
    expect(unavailableText(null)).toBe("Not available right now.")
  })

  it("only toasts when the made set is shorter than expected", () => {
    const created = { assignmentId: "a", quizId: "q", questionCount: 7, requestedCount: 10, topics: [], reason: "insufficient_pool" }
    expect(createdToast(created, 10)).toBe("Made a set of 7. That's all that matched.")
    expect(createdToast(created, 7)).toBeNull()
  })
})
```

- [ ] **Step 2: Run and watch them fail**

Run: `cd web && npx vitest run tests/unit/practiceBuilderModel.test.ts`
Expected: FAIL, the module cannot be found.

- [ ] **Step 3: Implement** `builderModel.ts`

```ts
/*
 * Set builder sheet (L4) view model: the generator's decisions, moved out of
 * JSX. Pure; no `.tsx` imports. See the plan for the "Weak topics only"
 * semantics. The pressed chips are always exactly what is sent.
 */
import type {
  CreatePracticeResponse,
  PracticeFilterSet,
  PracticePreview,
  PracticeTopics,
} from "@/lib/practiceTypes"
import { plural, topicLabel, tryOthers } from "../practiceCopy"
import { groupTopicsBySyllabusGroup, practiceAvailabilityView, weakTopicPrefill, type TopicGroup } from "../practiceData"

export const COUNT_MIN = 5
export const COUNT_MAX = 30
export const COUNT_STEP = 5
export const COUNT_DEFAULT = 10

export interface BuilderDraft {
  subjectCode: string
  count: number
  weakOnly: boolean
  selected: string[]
  bands: string[]
  source: string | null
}

export interface DraftSeed {
  draft: BuilderDraft
  /** Weak topics with no chip on screen (K12). */
  dropped: string[]
}

export function stepCount(count: number, direction: 1 | -1): number {
  return Math.min(COUNT_MAX, Math.max(COUNT_MIN, count + direction * COUNT_STEP))
}

export function weakServableTopics(topics: PracticeTopics): string[] {
  return weakTopicPrefill(topics.weakTopics, topics.topics).selected
}

export function initialDraft(subjectCode: string, topics: PracticeTopics, focusTopic: string | null): DraftSeed {
  const prefill = weakTopicPrefill(topics.weakTopics, topics.topics)
  const base = { subjectCode, count: COUNT_DEFAULT, bands: [], source: null }
  if (focusTopic && topics.topics.some((t) => t.topic === focusTopic)) {
    return { draft: { ...base, weakOnly: false, selected: [focusTopic] }, dropped: prefill.dropped }
  }
  return {
    draft: { ...base, weakOnly: prefill.selected.length > 0, selected: prefill.selected },
    dropped: prefill.dropped,
  }
}

function toggle(list: readonly string[], item: string): string[] {
  return list.includes(item) ? list.filter((x) => x !== item) : [...list, item]
}

export function toggleTopic(draft: BuilderDraft, topic: string): BuilderDraft {
  return { ...draft, selected: toggle(draft.selected, topic) }
}

export function toggleBand(draft: BuilderDraft, band: string): BuilderDraft {
  return { ...draft, bands: toggle(draft.bands, band) }
}

export function setWeakOnly(draft: BuilderDraft, on: boolean, weakServable: readonly string[]): BuilderDraft {
  if (!on) return { ...draft, weakOnly: false }
  return { ...draft, weakOnly: true, selected: draft.selected.filter((t) => weakServable.includes(t)) }
}

export function setSource(draft: BuilderDraft, source: string | null): BuilderDraft {
  return { ...draft, source }
}

export function draftToFilters(draft: BuilderDraft): PracticeFilterSet {
  const serverWeak = draft.weakOnly && draft.selected.length === 0
  return {
    subjectCode: draft.subjectCode,
    count: draft.count,
    topics: serverWeak ? [] : [...draft.selected],
    weakTopicsOnly: serverWeak,
    difficultyBands: [...draft.bands],
    source: draft.source,
  }
}

export function visibleTopicGroups(topics: PracticeTopics, weakOnly: boolean): TopicGroup[] {
  if (!weakOnly) return groupTopicsBySyllabusGroup(topics.topics)
  const weak = new Set(weakServableTopics(topics))
  return groupTopicsBySyllabusGroup(topics.topics.filter((t) => weak.has(t.topic)))
}

export type BuilderBody = "loading" | "topicsError" | "noQuestions" | "ready"
export type LineTone = "wait" | "ok" | "short" | "none" | "error"
export interface AvailabilityLine {
  tone: LineTone
  text: string
}

export interface BuilderViewInput {
  topicsStatus: "pending" | "error" | "success"
  topics: PracticeTopics | undefined
  previewStatus: "pending" | "error" | "success"
  preview: PracticePreview | undefined
  /** The 409 payload from create, which overrides the preview until a filter changes. */
  race: PracticePreview | null
  creating: boolean
  createFailed: boolean
  subjectName: string
  otherSubjectNames: readonly string[]
  dropped: readonly string[]
}

export interface BuilderView {
  body: BuilderBody
  noQuestions: { heading: string; body: string } | null
  line: AvailabilityLine | null
  cta: { label: string; disabled: boolean }
  showPrint: boolean
  errorBanner: string | null
  droppedNote: string | null
  untopicedNote: string | null
  /** The size the created set should have, for `createdToast`. */
  startCount: number | null
}

export function unavailableText(reason: string | null): string {
  switch (reason) {
    case "no_weaknesses":
      return "No weak topics yet. Turn this off to pick any topic."
    case "no_questions":
      return "Nothing matches. Try other topics or another difficulty."
    default:
      return reason ? `Not available right now (${reason}).` : "Not available right now."
  }
}

function matchText(n: number): string {
  return `${plural(n, "question")} ${n === 1 ? "matches" : "match"}`
}

function droppedNote(dropped: readonly string[]): string | null {
  if (dropped.length === 0) return null
  if (dropped.length === 1) return `${topicLabel(dropped[0])} isn't in the question bank yet.`
  return `${dropped.length} weak topics aren't in the question bank yet: ${dropped.map(topicLabel).join(", ")}.`
}

function untopicedNote(n: number): string | null {
  return n > 0 ? `Plus ${plural(n, "untagged question")}, used when no topic is picked.` : null
}

const START = "Start now"

export function builderView(i: BuilderViewInput): BuilderView {
  const idle: BuilderView = {
    body: "loading",
    noQuestions: null,
    line: null,
    cta: { label: START, disabled: true },
    showPrint: false,
    errorBanner: null,
    droppedNote: droppedNote(i.dropped),
    untopicedNote: null,
    startCount: null,
  }
  if (i.topicsStatus === "pending") return idle
  if (i.topicsStatus === "error" || !i.topics) return { ...idle, body: "topicsError" }
  if (i.topics.topics.length === 0 && i.topics.untopicedCount === 0) {
    return {
      ...idle,
      body: "noQuestions",
      droppedNote: null,
      noQuestions: { heading: `No ${i.subjectName} questions yet`, body: tryOthers(i.otherSubjectNames) },
    }
  }

  const effective = i.race ?? (i.previewStatus === "success" ? (i.preview ?? null) : null)
  let line: AvailabilityLine
  let label = START
  let enabled = false
  let startCount: number | null = null
  if (effective) {
    const view = practiceAvailabilityView(effective)
    if (view.kind === "unavailable") {
      line = { tone: "none", text: unavailableText(view.reason) }
    } else if (view.kind === "shortfall") {
      line = { tone: "short", text: `Only ${matchText(view.availableCount)}. Add a topic or ask for fewer.` }
      label = `Start with ${view.availableCount}`
      enabled = true
      startCount = view.availableCount
    } else {
      line = { tone: "ok", text: matchText(view.availableCount) }
      enabled = true
      startCount = view.requestedCount
    }
  } else if (i.previewStatus === "error") {
    line = { tone: "error", text: "Couldn't check what matches. Change a filter to try again." }
  } else {
    line = { tone: "wait", text: "Checking what matches…" }
  }

  const ready: BuilderView = {
    ...idle,
    body: "ready",
    line,
    untopicedNote: untopicedNote(i.topics.untopicedCount),
    startCount,
    cta: { label, disabled: !enabled },
    showPrint: enabled,
  }
  if (i.creating) return { ...ready, cta: { label: "Making your set…", disabled: true }, showPrint: false }
  if (i.createFailed && !i.race && enabled) {
    return { ...ready, errorBanner: "Couldn't make this set. Try again.", cta: { label: "Try again", disabled: false } }
  }
  return ready
}

export function createdToast(created: CreatePracticeResponse, expected: number): string | null {
  return created.questionCount < expected ? `Made a set of ${created.questionCount}. That's all that matched.` : null
}
```

- [ ] **Step 4: Run and watch them pass**

Run: `cd web && npx vitest run tests/unit/practiceBuilderModel.test.ts tests/unit/practice.test.ts`
Expected: all pass. `practice.test.ts` still covers the shared `practiceData` helpers. Then temporarily make `draftToFilters` always send `weakTopicsOnly: draft.weakOnly`, and expect the "sends picked chips" test to fail. Revert.

- [ ] **Step 5: Commit**

```bash
PYTHONPATH=$(git rev-parse --show-toplevel) pre-commit run --files web/src/portals/student/screens/practice/builder/builderModel.ts web/tests/unit/practiceBuilderModel.test.ts
git commit -S -m "feat(web): add the set builder view model" -- web/src/portals/student/screens/practice/builder/builderModel.ts web/tests/unit/practiceBuilderModel.test.ts
```

### Task 7: Past papers view model

**Files:**
- Create: `web/src/portals/student/screens/practice/papers/papersModel.ts`
- Test: `web/tests/unit/practicePapersModel.test.ts`

**Interfaces:**
- Consumes: `PastPaper` (Task 4), `plural` and `tryOthers` (Task 5).
- Produces:
  - functions `formatDuration`, `paperRow`, `paperGroups`, `papersState`, `paperSheetView`, `emptyPapersCopy`
  - types `PaperRowView`, `PaperGroupView`, `PapersState`, `PaperOption`, `PaperSheetView`

- [ ] **Step 1: Write the failing tests**

```ts
import { describe, expect, it } from "vitest"
import type { PastPaper } from "@/lib/practiceHubTypes"
import {
  emptyPapersCopy,
  formatDuration,
  paperGroups,
  paperRow,
  paperSheetView,
  papersState,
} from "@/portals/student/screens/practice/papers/papersModel"

const paper = (over: Partial<PastPaper>): PastPaper => ({
  paperId: "p1",
  code: "0580/42",
  subjectCode: "0580",
  paperNumber: 4,
  paperVariant: 2,
  sessionLabel: "May/June 2025",
  durationMinutes: 150,
  totalMarks: 80,
  questionCount: 18,
  awardedMarks: 52,
  maximumMarks: 80,
  ...over,
})

describe("formatDuration", () => {
  it("matches the mock's '2 h 30' style", () => {
    expect(formatDuration(150)).toBe("2 h 30")
    expect(formatDuration(90)).toBe("1 h 30")
    expect(formatDuration(60)).toBe("1 h")
    expect(formatDuration(45)).toBe("45 min")
    expect(formatDuration(65)).toBe("1 h 05")
  })
})

describe("paperRow", () => {
  it("done paper shows its score", () => {
    expect(paperRow(paper({}))).toEqual({
      paperId: "p1",
      title: "0580/42 · May/June 2025",
      sub: "Paper 4 · 2 h 30",
      score: "52/80",
      done: true,
    })
  })

  it("undone paper has no score; a paper with no timing shows no duration", () => {
    const row = paperRow(paper({ awardedMarks: null, maximumMarks: null, durationMinutes: null }))
    expect(row).toMatchObject({ sub: "Paper 4", score: null, done: false })
  })
})

describe("paperGroups", () => {
  it("groups by paper number, highest first, keeping server order inside a group", () => {
    const groups = paperGroups([
      paper({ paperId: "a", paperNumber: 2 }),
      paper({ paperId: "b", paperNumber: 4 }),
      paper({ paperId: "c", paperNumber: 4 }),
    ])
    expect(groups.map((g) => [g.heading, g.rows.map((r) => r.paperId)])).toEqual([
      ["Paper 4", ["b", "c"]],
      ["Paper 2", ["a"]],
    ])
  })
})

describe("papersState", () => {
  it("covers loading, error, empty and ready", () => {
    expect(papersState("pending", undefined)).toBe("loading")
    expect(papersState("error", undefined)).toBe("error")
    expect(papersState("success", [])).toBe("empty")
    expect(papersState("success", [paper({})])).toBe("ready")
  })
})

describe("paperSheetView", () => {
  it("offers timed first when the syllabus gives a duration", () => {
    const v = paperSheetView(paper({}), "Maths")
    expect(v.title).toBe("0580/42 · May/June 2025")
    expect(v.sub).toBe("Maths · Paper 4 · 80 marks")
    expect(v.options.map((o) => o.key)).toEqual(["timed", "print"])
    expect(v.options[0].body).toBe("2 h 30 on paper, then type your answers in")
    expect(v.defaultOption).toBe("timed")
    expect(v.hint).toBe("Prints 18 questions. Lemely marks the answers you type in.")
  })

  it("never offers a timed option without a real duration", () => {
    const v = paperSheetView(paper({ durationMinutes: null, totalMarks: null }), "Maths")
    expect(v.options.map((o) => o.key)).toEqual(["print"])
    expect(v.defaultOption).toBe("print")
    expect(v.sub).toBe("Maths · Paper 4")
  })

  it("a done paper with nothing printable cannot be printed", () => {
    expect(paperSheetView(paper({ questionCount: 0 }), "Maths").printable).toBe(false)
  })
})

describe("emptyPapersCopy", () => {
  it("follows the no-questions pattern", () => {
    expect(emptyPapersCopy("Maths", ["Physics"])).toEqual({
      heading: "No Maths papers to print yet",
      body: "We're adding them. Try Physics for now.",
    })
  })
})
```

- [ ] **Step 2: Run and watch them fail**

Run: `cd web && npx vitest run tests/unit/practicePapersModel.test.ts`
Expected: FAIL, the module cannot be found.

- [ ] **Step 3: Implement** `papersModel.ts`

```ts
/* Past papers screen and sheet (L4) view model. Pure; no `.tsx` imports. */
import type { PastPaper } from "@/lib/practiceHubTypes"
import { plural, tryOthers } from "../practiceCopy"

export type PaperOption = "timed" | "print"
export type PapersState = "loading" | "error" | "empty" | "ready"

export interface PaperRowView {
  paperId: string
  title: string
  sub: string
  score: string | null
  done: boolean
}

export interface PaperGroupView {
  paperNumber: number
  heading: string
  rows: PaperRowView[]
}

export interface PaperSheetView {
  title: string
  sub: string
  options: { key: PaperOption; title: string; body: string }[]
  defaultOption: PaperOption
  hint: string
  printable: boolean
}

export function formatDuration(minutes: number): string {
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  if (h === 0) return `${m} min`
  if (m === 0) return `${h} h`
  return `${h} h ${String(m).padStart(2, "0")}`
}

export function paperRow(p: PastPaper): PaperRowView {
  const score = p.awardedMarks !== null && p.maximumMarks !== null ? `${p.awardedMarks}/${p.maximumMarks}` : null
  return {
    paperId: p.paperId,
    title: `${p.code} · ${p.sessionLabel}`,
    sub: p.durationMinutes ? `Paper ${p.paperNumber} · ${formatDuration(p.durationMinutes)}` : `Paper ${p.paperNumber}`,
    score,
    done: score !== null,
  }
}

export function paperGroups(papers: readonly PastPaper[]): PaperGroupView[] {
  const byNumber = new Map<number, PaperRowView[]>()
  for (const p of papers) {
    const rows = byNumber.get(p.paperNumber) ?? []
    rows.push(paperRow(p))
    byNumber.set(p.paperNumber, rows)
  }
  return [...byNumber.entries()]
    .sort(([a], [b]) => b - a)
    .map(([paperNumber, rows]) => ({ paperNumber, heading: `Paper ${paperNumber}`, rows }))
}

export function papersState(status: "pending" | "error" | "success", papers: readonly PastPaper[] | undefined): PapersState {
  if (status === "pending") return "loading"
  if (status === "error" || !papers) return "error"
  return papers.length === 0 ? "empty" : "ready"
}

export function paperSheetView(p: PastPaper, subjectName: string): PaperSheetView {
  const subParts = [subjectName, `Paper ${p.paperNumber}`]
  if (p.totalMarks) subParts.push(`${p.totalMarks} marks`)
  const options: PaperSheetView["options"] = []
  if (p.durationMinutes) {
    options.push({ key: "timed", title: "Do it timed", body: `${formatDuration(p.durationMinutes)} on paper, then type your answers in` })
  }
  options.push({ key: "print", title: "Just print it", body: "No timer. Type your answers in when you're done." })
  return {
    title: `${p.code} · ${p.sessionLabel}`,
    sub: subParts.join(" · "),
    options,
    defaultOption: options[0].key,
    hint: `Prints ${plural(p.questionCount, "question")}. Lemely marks the answers you type in.`,
    printable: p.questionCount > 0,
  }
}

export function emptyPapersCopy(subjectName: string, otherSubjectNames: readonly string[]): { heading: string; body: string } {
  return { heading: `No ${subjectName} papers to print yet`, body: tryOthers(otherSubjectNames) }
}
```

- [ ] **Step 4: Run and watch them pass**

Run: `cd web && npx vitest run tests/unit/practicePapersModel.test.ts`
Expected: all pass. Temporarily push the timed option unconditionally, and expect "never offers a timed option" to fail. Revert.

- [ ] **Step 5: Commit**

```bash
PYTHONPATH=$(git rev-parse --show-toplevel) pre-commit run --files web/src/portals/student/screens/practice/papers/papersModel.ts web/tests/unit/practicePapersModel.test.ts
git commit -S -m "feat(web): add the past papers view model" -- web/src/portals/student/screens/practice/papers/papersModel.ts web/tests/unit/practicePapersModel.test.ts
```

---

## Screen tasks (designer agent)

Every screen task is for the `designer` agent. Before any UI edit it invokes the `impeccable` skill and reads `.claude/skills/impeccable/reference/craft-floor.md`. Keep the mock open while building. Classes follow the mapping table above, and F1 names follow the master contract:
- `Tile`, `BinnyLine`, `Binny`
- `H2Row`, `HairRows`, `HairRow`
- `Walkthrough`, `GhostRows`

If an F1 component's rendered geometry differs from the mock, fix it in the PR's drift list. Never by forking the component.

### Task 8: Icons, hub data hook and the hub screen (CF, CN, CS, CZ, CL, CE, CDK)

**Files:**
- Create: `web/src/portals/student/screens/practice/practiceIcons.tsx`
- Create: `web/src/portals/student/screens/practice/hub/usePracticeHubData.ts`
- Create: `web/src/portals/student/screens/practice/hub/HubTiles.tsx`, `HomeworkRow.tsx`, `WinBackList.tsx`, `RecentRuns.tsx`, `HubStates.tsx`, `HubLayout.tsx`, `useWide.ts`
- Create: `web/src/portals/student/screens/practice/PracticeHub.tsx`

**Interfaces:**
- Consumes:
  - `practiceHubView`, `HubView` and `HubSubject` (Task 5), and the Task 4 hooks
  - `useOverview` (`@/lib/hooks/useStudentApi`), `useStudentProfile` (`@/lib/hooks/useMeApi`), `useReference` (`@/lib/hooks/useReferenceApi`) and `subjectNameFor` (`@/lib/reference`)
  - `useDueSession` and `useFlashcardDecks` (`@/lib/hooks/useFlashcardApi`), `usePlacementAvailabilities` (`@/lib/hooks/usePlacementApi`)
  - F1 components, `PageHeading`, `Button` and `SkeletonBlock`
  - `SetBuilderSheet` (Task 9), rendered when the route has `:subjectCode`. Until Task 9 lands, leave the sheet line commented with the Task 9 reference. The Task 9 checklist re-enables it.
- Produces:
  - `PracticeHub` (named export)
  - `usePracticeHubData(): { input: HubInput; builderSubjects: { code: string; name: string }[]; refetchAll: () => void }`
  - the icons `SetIcon`, `CardsIcon`, `PaperIcon`, `TestIcon`, `ResumeIcon`, `HomeworkIcon`, `PrintIcon`, `ClockIcon`, `TickIcon`, `ChevronIcon`, `SpinnerRing`, and `SubjectDot`

Component tree:

```
PracticeHub
├─ header: PageHeading "Practice" (repeatsTitle) + subtitle <p>
├─ state loading → HubSkeleton (CL)
├─ else HubLayout (grid areas differ by state and breakpoint)
│   ├─ hw:     HomeworkRow (when view.homework)
│   ├─ binny:  BinnyLine size 48 (normal, sparse)
│   ├─ tiles:  HubTiles → 4 × Tile
│   ├─ error:  HubError (CE)
│   ├─ first:  FirstRun (CZ): BinnyLine open 64 + Walkthrough + "Scan a paper"
│   ├─ win:    WinBackList (H2Row + HairRows) + ScanTip (CS)
│   └─ recent: RecentRuns (H2Row + HairRows, "See all" toggle)
└─ SetBuilderSheet when :subjectCode is in the URL (Task 9)
```

- [ ] **Step 1: Icons** (`practiceIcons.tsx`, paths copied verbatim from `ph.js` `IC`, `TK` and `t.js` `CHEV`)

```tsx
import type { CSSProperties, ReactNode, SVGProps } from "react"
import { cn } from "@/lib/utils"

export type PracticeIconProps = SVGProps<SVGSVGElement> & { size?: number }

function Svg({ size = 22, viewBox, children, ...rest }: PracticeIconProps & { viewBox: string; children: ReactNode }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox={viewBox}
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      {...rest}
    >
      {children}
    </svg>
  )
}

export function SetIcon(p: PracticeIconProps) {
  return (
    <Svg viewBox="0 0 22 22" {...p}>
      <path d="M5 4h12v14H5zM8 8h6M8 12h4" />
      <path d="m12.5 15 1.5 1.5 3-3.5" />
    </Svg>
  )
}

export function CardsIcon(p: PracticeIconProps) {
  return (
    <Svg viewBox="0 0 20 20" strokeWidth={1.7} {...p}>
      <rect x={3} y={5} width={11} height={12} rx={2} />
      <path d="M7 3h8a2 2 0 0 1 2 2v9" />
    </Svg>
  )
}

export function PaperIcon(p: PracticeIconProps) {
  return (
    <Svg viewBox="0 0 20 20" strokeWidth={1.7} {...p}>
      <path d="M5 2.5h7l3.5 3.5v11.5h-10.5zM12 2.5V6h3.5M8 10h5M8 13h5" />
    </Svg>
  )
}

export function TestIcon(p: PracticeIconProps) {
  return (
    <Svg viewBox="0 0 20 20" strokeWidth={1.7} {...p}>
      <circle cx={10} cy={10} r={7} />
      <path d="m12.8 7.2-1.8 3.8-3.8 1.8 1.8-3.8z" />
    </Svg>
  )
}

export function ResumeIcon(p: PracticeIconProps) {
  return (
    <Svg viewBox="0 0 18 18" size={18} fill="currentColor" stroke="none" {...p}>
      <path d="M6 4.2v9.6L13.5 9z" />
    </Svg>
  )
}

export function HomeworkIcon(p: PracticeIconProps) {
  return (
    <Svg viewBox="0 0 20 20" size={20} strokeWidth={1.7} {...p}>
      <path d="M3 7.5 10 4l7 3.5-7 3.5z" />
      <path d="M6 9.2V13c0 1 1.8 2.2 4 2.2s4-1.2 4-2.2V9.2" />
    </Svg>
  )
}

export function PrintIcon(p: PracticeIconProps) {
  return (
    <Svg viewBox="0 0 18 18" size={18} strokeWidth={1.7} {...p}>
      <path d="M5 7V2.5h8V7M5 13H3V7h12v6h-2M5 10.5h8v5H5z" />
    </Svg>
  )
}

export function ClockIcon(p: PracticeIconProps) {
  return (
    <Svg viewBox="0 0 18 18" size={18} strokeWidth={1.7} {...p}>
      <circle cx={9} cy={9.5} r={6} />
      <path d="M9 6.5v3l2 1.5M7 2h4" />
    </Svg>
  )
}

export function TickIcon(p: PracticeIconProps) {
  return (
    <Svg viewBox="0 0 16 16" size={16} strokeWidth={2.2} {...p}>
      <path d="M3.5 8.3 6.5 11l6-6.5" />
    </Svg>
  )
}

export function ChevronIcon(p: PracticeIconProps) {
  return (
    <Svg viewBox="0 0 18 18" size={18} {...p}>
      <path d="M7 4l5 5-5 5" />
    </Svg>
  )
}

/** `.spin`: 14px ring, outline track, primary head, .8s linear; static under reduced motion. */
export function SpinnerRing() {
  return (
    <span
      aria-hidden="true"
      className="inline-block size-3.5 flex-none animate-spin rounded-full border-2 border-outline border-t-primary [animation-duration:.8s] [animation-timing-function:linear] motion-reduce:animate-none"
    />
  )
}

export function SubjectDot({ color, className }: { color: string; className?: string }) {
  const style: CSSProperties = { background: color }
  return <i aria-hidden="true" style={style} className={cn("me-1.5 inline-block size-2 flex-none rounded-full align-[1px]", className)} />
}
```

- [ ] **Step 2: The data hook** (`hub/usePracticeHubData.ts`)

```ts
import { useMemo } from "react"
import { usePlacementAvailabilities } from "@/lib/hooks/usePlacementApi"
import { useDueSession, useFlashcardDecks } from "@/lib/hooks/useFlashcardApi"
import { useStudentProfile } from "@/lib/hooks/useMeApi"
import { usePracticeRuns, usePracticeTopicsMany, useStudentQuizzes } from "@/lib/hooks/usePracticeHubApi"
import { useReference } from "@/lib/hooks/useReferenceApi"
import { useOverview } from "@/lib/hooks/useStudentApi"
import { subjectNameFor } from "@/lib/reference"
import type { HubInput, HubSubject } from "./hubModel"

/**
 * Composes every query the hub reads into one `HubInput`. Subjects are the
 * overview's (they carry paper counts) followed by any enrolled subject with
 * no paper yet, so a first-time student can still open the builder.
 */
export function usePracticeHubData(): {
  input: HubInput
  builderSubjects: { code: string; name: string }[]
  refetchAll: () => void
} {
  const overview = useOverview()
  const profile = useStudentProfile()
  const { data: reference } = useReference()

  const subjects = useMemo<HubSubject[]>(() => {
    const fromOverview = (overview.data?.subjects ?? []).map((s) => ({ code: s.code, name: s.name, papers: s.papers }))
    const seen = new Set(fromOverview.map((s) => s.code))
    const fromEnrolments = (profile.data?.enrolments ?? [])
      .filter((e) => !seen.has(e.subjectCode))
      .map((e) => ({ code: e.subjectCode, name: subjectNameFor(reference, e.subjectCode), papers: 0 }))
    return [...fromOverview, ...fromEnrolments]
  }, [overview.data, profile.data, reference])

  const codes = subjects.map((s) => s.code)
  const topicQueries = usePracticeTopicsMany(codes)
  const runs = usePracticeRuns()
  const quizzes = useStudentQuizzes()
  const due = useDueSession()
  const decks = useFlashcardDecks()
  const placement = usePlacementAvailabilities(codes)
  const now = useMemo(() => new Date(), [])

  const input: HubInput = {
    overviewStatus: overview.status,
    subjects,
    topics: codes.map((code, i) => ({ code, status: topicQueries[i].status, data: topicQueries[i].data })),
    runsStatus: runs.status,
    runs: runs.data?.runs ?? [],
    homework: quizzes.data?.quizzes ?? [],
    dueTotal: due.data?.totalDue ?? null,
    deckCount: decks.data ? decks.data.length : null,
    placement: codes.map((code, i) => ({
      code,
      available: placement[i].data ? placement[i].data.available : null,
      minutes: placement[i].data?.estimatedMinutes ?? null,
    })),
    now,
  }

  return {
    input,
    builderSubjects: subjects.map(({ code, name }) => ({ code, name })),
    refetchAll: () => {
      void overview.refetch()
      void runs.refetch()
      for (const q of topicQueries) void q.refetch()
    },
  }
}
```

- [ ] **Step 3: The pieces**

`hub/HubTiles.tsx`:

```tsx
import { useNavigate } from "react-router-dom"
import { Tile } from "@/components/redesign"
import { CardsIcon, PaperIcon, SetIcon, TestIcon } from "../practiceIcons"
import type { TileView } from "./hubModel"

const ICONS = { set: SetIcon, cards: CardsIcon, paper: PaperIcon, test: TestIcon } as const

/** `.pgrid.tint` (2 up) and `.pgrid.tint.four` (4 up from md). */
export function HubTiles({ tiles }: { tiles: readonly TileView[] }) {
  const navigate = useNavigate()
  return (
    <ul aria-label="Ways to practise" className="grid grid-cols-2 gap-2.5 md:grid-cols-4 md:gap-3">
      {tiles.map((t) => (
        <li key={t.key} className="contents">
          <Tile
            icon={ICONS[t.key]}
            title={t.title}
            status={
              t.count !== null ? (
                <>
                  <b className="font-mono text-[15px] font-extrabold text-primary">{t.count}</b> due today
                </>
              ) : (
                t.status
              )
            }
            tone={t.tone}
            disabled={t.disabled}
            onClick={t.to ? () => navigate(t.to as string, { state: { fromHub: true } }) : undefined}
          />
        </li>
      ))}
    </ul>
  )
}
```

`hub/HomeworkRow.tsx`:

```tsx
import { Link } from "react-router-dom"
import { ChevronIcon, HomeworkIcon } from "../practiceIcons"
import type { HomeworkView } from "./hubModel"

/** `.hwr`: the only tinted row on the hub, shown on top only when homework is set. */
export function HomeworkRow({ homework }: { homework: HomeworkView }) {
  return (
    <Link
      to={homework.to}
      className="group grid min-h-[60px] grid-cols-[40px_minmax(0,1fr)_18px] items-center gap-3 rounded-2xl bg-primary-container px-3 py-2.5 text-on-surface focus-visible:outline-[2.5px] focus-visible:outline-offset-2 focus-visible:outline-primary lg:max-w-[560px]"
    >
      <span className="grid size-10 place-items-center rounded-[13px] bg-primary text-on-primary">
        <HomeworkIcon />
      </span>
      <span className="grid min-w-0 gap-0.5">
        <b className="truncate text-[15px] font-bold group-hover:text-primary">{homework.title}</b>
        <span className="truncate text-[13px] text-on-surface-variant">{homework.sub}</span>
      </span>
      <ChevronIcon className="text-on-surface-variant" />
    </Link>
  )
}
```

`hub/WinBackList.tsx`:

```tsx
import { useNavigate } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { H2Row, HairRow, HairRows } from "@/components/redesign"
import { subjectDotColor } from "../practiceCopy"
import { SubjectDot } from "../practiceIcons"
import type { WinBackRow } from "./hubModel"

export function WinBackList({
  rows,
  allTopicsTo,
  subjectOrder,
}: {
  rows: readonly WinBackRow[]
  allTopicsTo: string | null
  subjectOrder: readonly string[]
}) {
  const navigate = useNavigate()
  if (rows.length === 0) return null
  return (
    <section aria-labelledby="win-back-h" className="grid gap-1">
      <H2Row title="Win marks back" link={allTopicsTo ? { label: "All topics", to: allTopicsTo } : undefined} />
      <HairRows aria-label="Topics to win back">
        {rows.map((r) => (
          <HairRow
            key={`${r.subjectCode}:${r.topic}`}
            title={r.label}
            sub={
              <>
                <SubjectDot color={subjectDotColor(r.subjectCode, subjectOrder)} />
                {r.subjectName}
              </>
            }
            trailing={
              <span className="grid justify-items-end font-mono text-[17px] font-extrabold leading-none text-primary">
                +{r.marks}
                <small className="mt-0.5 font-sans text-[12px] font-semibold text-on-surface-variant">marks</small>
              </span>
            }
            onClick={() => navigate(r.to, { state: { fromHub: true } })}
          />
        ))}
      </HairRows>
    </section>
  )
}

/** `.tipr` (CS): sparse nudge to scan more papers. */
export function ScanTip() {
  const navigate = useNavigate()
  return (
    <div className="flex items-center justify-between gap-3 py-3 shadow-[0_-1px_0_var(--color-outline-variant)]">
      <span className="grid gap-0.5">
        <b className="text-[15px] font-bold text-on-surface">More papers, sharper picks</b>
        <span className="text-[13px] text-on-surface-variant">Each paper you scan adds topics here.</span>
      </span>
      <Button variant="primary" size="sm" className="relative min-h-11 before:absolute before:inset-x-0 before:-inset-y-1.5" onClick={() => navigate("/student/correct")}>
        Scan
      </Button>
    </div>
  )
}
```

`H2Row` renders the `<h2>`. Give its heading the id `win-back-h`, or drop `aria-labelledby` if `H2Row` exposes no id prop, and use `aria-label="Win marks back"` instead. Settle this against the F1 source.

`hub/RecentRuns.tsx`:

```tsx
import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { H2Row, HairRow, HairRows } from "@/components/redesign"
import { subjectDotColor } from "../practiceCopy"
import { ClockIcon, ResumeIcon, SubjectDot, TickIcon } from "../practiceIcons"
import type { RecentRow } from "./hubModel"

const LEADING = {
  resume: { className: "bg-primary text-on-primary", icon: <ResumeIcon /> },
  done: { className: "bg-success-container text-success-text", icon: <TickIcon /> },
  marking: { className: "bg-primary-container text-primary", icon: <ClockIcon /> },
} as const

export function RecentRuns({
  rows,
  more,
  subjectOrder,
}: {
  rows: readonly RecentRow[]
  more: readonly RecentRow[]
  subjectOrder: readonly string[]
}) {
  const navigate = useNavigate()
  const [expanded, setExpanded] = useState(false)
  if (rows.length === 0) return null
  const shown = expanded ? [...rows, ...more] : rows
  return (
    <section aria-label="Recent" className="grid gap-1">
      <H2Row
        title="Recent"
        link={more.length > 0 ? { label: expanded ? "Show less" : "See all", onClick: () => setExpanded((v) => !v) } : undefined}
      />
      <HairRows aria-label="Recent practice">
        {shown.map((r) => (
          <HairRow
            key={r.assignmentId}
            leading={
              <span className={`grid size-10 place-items-center rounded-[13px] ${LEADING[r.kind].className}`}>
                {LEADING[r.kind].icon}
              </span>
            }
            title={r.title}
            sub={
              <>
                <SubjectDot color={subjectDotColor(r.subjectCode, subjectOrder)} />
                {r.sub}
              </>
            }
            trailing={
              r.kind === "resume" ? (
                <span className="inline-flex min-h-11 items-center text-[14px] font-bold text-primary">Resume</span>
              ) : undefined
            }
            onClick={() => navigate(r.to)}
          />
        ))}
      </HairRows>
    </section>
  )
}
```

`hub/HubStates.tsx`:

```tsx
import { useNavigate } from "react-router-dom"
import { Binny, BinnyLine, GhostRows, Walkthrough } from "@/components/redesign"
import { Button } from "@/components/ui/button"
import { SkeletonBlock } from "@/components/ui/skeleton"
import { PaperIcon, SetIcon, TestIcon } from "../practiceIcons"

const BIG_CTA = "min-h-[54px] w-full max-w-[300px] rounded-[18px] text-[16px] shadow-[0_14px_24px_-16px_oklch(.3_.07_242/.7)]"

/** CL */
export function HubSkeleton() {
  return (
    <div aria-busy="true" aria-label="Loading practice" className="grid gap-3.5">
      <div className="grid grid-cols-2 gap-2.5 md:grid-cols-4 md:gap-3">
        {[0, 1, 2, 3].map((i) => (
          <SkeletonBlock key={i} className="h-[124px] rounded-[20px] lg:h-[140px]" />
        ))}
      </div>
      <SkeletonBlock className="h-[22px] w-40" />
      <GhostRows rows={3} />
    </div>
  )
}

/** CE: the tiles stay above this; only the topic-driven parts failed. */
export function HubError({ onRetry }: { onRetry: () => void }) {
  return (
    <div role="alert" className="grid justify-items-center gap-3 px-2 pt-2 pb-6 text-center">
      <Binny mood="sad" size={80} motion="none" />
      <h2 className="mt-1.5 font-display text-[28px] font-extrabold leading-[1.15] tracking-[-0.02em] text-balance text-primary">
        We couldn’t load your topics
      </h2>
      <p className="mb-1.5 max-w-[30ch] text-[15px] font-medium leading-[1.4] text-on-surface-variant">
        The tiles still work. Check your connection for the rest.
      </p>
      <Button variant="primary" size="lg" className={BIG_CTA} onClick={onRetry}>
        Try again
      </Button>
    </div>
  )
}

/** CZ */
export function FirstRun({ line }: { line: string }) {
  const navigate = useNavigate()
  return (
    <div className="grid gap-5">
      <BinnyLine mood="open" line={line} size={64} motion="pop" />
      <Walkthrough
        steps={[
          { icon: PaperIcon, title: "Scan a marked paper", body: "Or take the 10-minute placement test." },
          { icon: TestIcon, title: "See where marks went", body: "Your weakest topics show up here." },
          { icon: SetIcon, title: "Win them back", body: "Short sets, checked as you go." },
        ]}
      />
      <Button variant="primary" size="lg" className={`${BIG_CTA} max-w-none`} onClick={() => navigate("/student/correct")}>
        Scan a paper
      </Button>
    </div>
  )
}
```

The mock's walkthrough says "10-minute placement test", which is mock copy. If placement availability gives a different estimate, keep the mock copy (it is approved content) and note it in the PR.

`hub/HubLayout.tsx` places the areas. Phone and tablet use one column in mock order. Desktop (`lg`, 1024px) puts homework and Binny on one row (`.phr`), tiles across, then two columns (`.pcols`, gap 40). Binny must mount exactly once (master rule, and it avoids two idle animations). So the screen renders `BinnyLine` into either the top slot or the after-tiles slot, chosen by `useWide()`. CSS-hiding a second copy is not allowed. If `web/src/lib` already has a media-query hook (`grep -rn "matchMedia" web/src/lib | head`), use it instead of this local one.

```ts
// hub/useWide.ts
import { useSyncExternalStore } from "react"
const QUERY = "(min-width: 1024px)"
export function useWide(): boolean {
  return useSyncExternalStore(
    (cb) => {
      const mq = window.matchMedia(QUERY)
      mq.addEventListener("change", cb)
      return () => mq.removeEventListener("change", cb)
    },
    () => window.matchMedia(QUERY).matches,
    () => false,
  )
}
```

`hub/HubLayout.tsx`:

```tsx
export function HubLayout({ homework, binnyTop, binnyAfterTiles, tiles, middle, win, recent }: {
  homework: ReactNode; binnyTop: ReactNode; binnyAfterTiles: ReactNode; tiles: ReactNode; middle: ReactNode; win: ReactNode; recent: ReactNode
}) {
  return (
    <div className="flex flex-col gap-6 lg:gap-5">
      {homework || binnyTop ? (
        <div className="flex flex-col gap-6 lg:grid lg:grid-cols-[minmax(0,560px)_minmax(0,1fr)] lg:items-center lg:gap-6">
          {homework ? <div>{homework}</div> : <div aria-hidden="true" />}
          {binnyTop}
        </div>
      ) : null}
      {tiles}
      {binnyAfterTiles}
      {middle}
      {win || recent ? (
        <div className="flex flex-col gap-6 lg:grid lg:grid-cols-2 lg:items-start lg:gap-x-10">
          {win ? <div className="flex flex-col gap-6">{win}</div> : null}
          {recent ? <div>{recent}</div> : null}
        </div>
      ) : null}
    </div>
  )
}
```


- [ ] **Step 4: The screen** (`PracticeHub.tsx`)

```tsx
/* L4 · Practice tab root (mock C, practice-hub-final.html). Thin: every decision is in hubModel. */
import { useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom"
import { BinnyLine } from "@/components/redesign"
import { PageHeading } from "@/components/ui/page-heading"
// import { SetBuilderSheet } from "./builder/SetBuilderSheet" — enabled in Task 9
import { HomeworkRow } from "./hub/HomeworkRow"
import { practiceHubView } from "./hub/hubModel"
import { HubLayout } from "./hub/HubLayout"
import { FirstRun, HubError, HubSkeleton } from "./hub/HubStates"
import { HubTiles } from "./hub/HubTiles"
import { RecentRuns } from "./hub/RecentRuns"
import { usePracticeHubData } from "./hub/usePracticeHubData"
import { useWide } from "./hub/useWide"
import { ScanTip, WinBackList } from "./hub/WinBackList"

export function PracticeHub() {
  const { subjectCode } = useParams<{ subjectCode?: string }>()
  const [search] = useSearchParams()
  const navigate = useNavigate()
  const location = useLocation()
  const wide = useWide()
  const hub = usePracticeHubData()
  const view = practiceHubView(hub.input)
  const order = hub.builderSubjects.map((s) => s.code)

  const closeBuilder = () => {
    if ((location.state as { fromHub?: boolean } | null)?.fromHub) navigate(-1)
    else navigate("/student/practice", { replace: true })
  }

  const binny =
    view.binny && view.state !== "firstTime" ? (
      <BinnyLine mood={view.binny.mood} line={view.binny.line} size={48} motion="idle" />
    ) : null

  return (
    <div className="flex flex-col gap-4 pb-6">
      <header className="grid gap-0.5">
        <PageHeading
          repeatsTitle
          className="font-display text-[28px] font-extrabold leading-[1.1] tracking-[-0.03em] text-primary lg:text-[32px]"
        >
          Practice
        </PageHeading>
        {view.subtitle ? <p className="text-[13px] font-medium text-on-surface-variant">{view.subtitle}</p> : null}
      </header>

      {view.state === "loading" ? (
        <HubSkeleton />
      ) : (
        <HubLayout
          homework={view.homework ? <HomeworkRow homework={view.homework} /> : null}
          binnyTop={wide ? binny : null}
          binnyAfterTiles={wide ? null : binny}
          tiles={<HubTiles tiles={view.tiles} />}
          middle={
            view.state === "error" ? (
              <HubError onRetry={hub.refetchAll} />
            ) : view.state === "firstTime" && view.binny ? (
              <FirstRun line={view.binny.line} />
            ) : null
          }
          win={
            view.winBack.length > 0 || view.showScanTip ? (
              <>
                <WinBackList rows={view.winBack} allTopicsTo={view.allTopicsTo} subjectOrder={order} />
                {view.showScanTip ? <ScanTip /> : null}
              </>
            ) : null
          }
          recent={view.recent.length > 0 ? <RecentRuns rows={view.recent} more={view.recentMore} subjectOrder={order} /> : null}
        />
      )}

      {/* Task 9:
      {subjectCode ? (
        <SetBuilderSheet
          key={subjectCode}
          subjects={hub.builderSubjects}
          initialSubject={subjectCode}
          focusTopic={search.get("topic")}
          onClose={closeBuilder}
        />
      ) : null} */}
    </div>
  )
}
```

The sparse frame (CS) renders the win heading without the "All topics" link (`allTopicsTo` is null), then the tip, which matches the mock.

`PageHeading repeatsTitle` makes the heading `native:sr-only`, so on the native frame the shell's large title says "Practice" once. On the web frame the page heading shows, as the mock's `.sjhd` does.

- [ ] **Step 5: Typecheck and lint**

Run: `cd web && npm run typecheck && npx oxlint src/portals/student/screens/practice && npm run check:copy && npm run check:native`
Expected: exit 0. `check:copy` flags any `!` or prose em dash in the new copy, so fix it at the source.

- [ ] **Step 6: Commit**

```bash
P=web/src/portals/student/screens/practice
PYTHONPATH=$(git rev-parse --show-toplevel) pre-commit run --files $P/practiceIcons.tsx $P/PracticeHub.tsx $P/hub/*.ts $P/hub/*.tsx
git add $P/practiceIcons.tsx $P/PracticeHub.tsx $P/hub
git commit -S -m "feat(web): build the Practice tab hub screen" -- $P/practiceIcons.tsx $P/PracticeHub.tsx $P/hub
```

### Task 9: Set builder sheet (PS, CB1, CB2, CB3, CB4), replacing the generator

**Files:**
- Create: `web/src/portals/student/screens/practice/builder/SetBuilderSheet.tsx`
- Create: `web/src/portals/student/screens/practice/builder/TopicChips.tsx`, `CountStepper.tsx`, `AvailabilityLine.tsx`, `MoreFilters.tsx`, `SubjectChoice.tsx`
- Modify: `web/src/portals/student/screens/practice/PracticeHub.tsx` (enable the sheet import and render block left commented in Task 8)

**Interfaces:**
- Consumes:
  - Task 6's `builderView`, `initialDraft`, `draftToFilters`, the edit helpers and `createdToast`
  - `usePracticeTopics`, `usePracticePreview` and `useCreatePractice` (`@/lib/hooks/usePracticeApi`, unchanged)
  - `practiceHubKeys.runsAll`, `useReference`, `PRACTICE_SOURCES`, `ApiError`, `useToast`
  - `Sheet`, `SheetContent` and `SheetTitle` (`@/components/ui/sheet`), `Switch` (`@/components/ui/switch`) and `Button`
- Produces: `SetBuilderSheet(props: { subjects: { code: string; name: string }[]; initialSubject: string; focusTopic: string | null; onClose: () => void })`

Sheet anatomy (the mock's `bsheet`, top to bottom):
- grabber (shell)
- title "Practice set"
- subject choice
- "Weak topics only" switch row
- topic chips
- Questions stepper
- "Difficulty and source" fold
- availability line
- CTA
- "Print instead"

CB3 swaps the switch, chips, count and fold for the `err2` block. CB4 puts the `errl` banner first.

- [ ] **Step 1: Small pieces**

`builder/SubjectChoice.tsx`. The mock uses `role=tablist`, but there are no tab panels, so this is a radiogroup (a11y fix, listed in the PR):

```tsx
import { subjectDotColor } from "../practiceCopy"
import { SubjectDot } from "../practiceIcons"

const CHIP =
  "relative inline-flex min-h-11 flex-none cursor-pointer items-center gap-1.5 rounded-xl px-3.5 text-[13.5px] font-semibold text-on-surface bg-surface-container-lowest shadow-[inset_0_0_0_1.5px_var(--color-outline-variant)] aria-checked:bg-primary aria-checked:text-on-primary aria-checked:shadow-none focus-visible:outline-[2.5px] focus-visible:outline-offset-2 focus-visible:outline-primary"

export function SubjectChoice({
  subjects,
  value,
  onChange,
}: {
  subjects: readonly { code: string; name: string }[]
  value: string
  onChange: (code: string) => void
}) {
  const order = subjects.map((s) => s.code)
  return (
    <div role="radiogroup" aria-label="Subject" className="-mx-5 flex flex-none gap-1.5 overflow-x-auto px-5 [scrollbar-width:none]">
      {subjects.map((s) => (
        <button key={s.code} type="button" role="radio" aria-checked={s.code === value} className={CHIP} onClick={() => onChange(s.code)}>
          <SubjectDot color={s.code === value ? "currentColor" : subjectDotColor(s.code, order)} className="me-0" />
          {s.name}
        </button>
      ))}
    </div>
  )
}

export { CHIP as SUBJECT_CHIP_CLASS }
```

`builder/TopicChips.tsx` keeps the full topic text plus the count (K8, K9) and the weak tone for `marksLost > 0` (K10):

```tsx
import type { TopicGroup } from "../practiceData"
import { cn } from "@/lib/utils"

export function TopicChips({
  groups,
  selected,
  onToggle,
}: {
  groups: readonly TopicGroup[]
  selected: readonly string[]
  onToggle: (topic: string) => void
}) {
  if (groups.length === 0) return null
  const showHeadings = groups.length > 1
  return (
    <div role="group" aria-label="Topics" className="grid gap-3">
      {groups.map((g) => (
        <div key={g.syllabusGroup} className="grid gap-1.5">
          {showHeadings ? <h3 className="text-[12.5px] font-semibold text-on-surface-variant">{g.syllabusGroup}</h3> : null}
          <div className="flex flex-wrap gap-1.5">
            {g.topics.map((t) => {
              const on = selected.includes(t.topic)
              return (
                <button
                  key={t.topic}
                  type="button"
                  aria-pressed={on}
                  onClick={() => onToggle(t.topic)}
                  className={cn(
                    "relative inline-flex min-h-11 items-center gap-2 rounded-xl px-3 text-[13.5px] font-semibold transition-[translate] duration-200 ease-out hover:-translate-y-0.5 motion-reduce:transition-none motion-reduce:hover:translate-y-0",
                    "focus-visible:outline-[2.5px] focus-visible:outline-offset-2 focus-visible:outline-primary",
                    t.marksLost > 0
                      ? "bg-error-container text-on-error-container"
                      : "bg-surface-container-low text-on-surface shadow-[inset_0_0_0_1px_var(--color-outline-variant)]",
                    on && t.marksLost > 0 && "shadow-[inset_0_0_0_2px_var(--color-on-error-container)]",
                    on && t.marksLost <= 0 && "bg-primary-container text-primary shadow-[inset_0_0_0_2px_var(--color-primary)]",
                  )}
                >
                  <span>{t.topic}</span>
                  <b className="font-mono text-[12px] font-bold">{t.availableCount}</b>
                </button>
              )
            })}
          </div>
        </div>
      ))}
    </div>
  )
}
```

`builder/CountStepper.tsx` (`.cnt`/`.stepr`). F1 does not export a number stepper (the existing `components/ui/stepper.tsx` is a wizard stepper). If F1 adds one, swap it in.

```tsx
import { COUNT_MAX, COUNT_MIN, stepCount } from "./builderModel"

const BTN =
  "grid size-11 place-items-center rounded-[14px] bg-primary-container text-xl font-bold text-primary disabled:opacity-45 disabled:cursor-not-allowed focus-visible:outline-[2.5px] focus-visible:outline-offset-2 focus-visible:outline-primary"

export function CountStepper({ value, onChange }: { value: number; onChange: (n: number) => void }) {
  return (
    <div className="flex items-center justify-between text-[14px] font-semibold text-on-surface">
      <span id="count-label">Questions</span>
      <div className="flex items-center gap-3" role="group" aria-labelledby="count-label">
        <button type="button" aria-label="Fewer" className={BTN} disabled={value <= COUNT_MIN} onClick={() => onChange(stepCount(value, -1))}>
          −
        </button>
        <span aria-live="polite" className="min-w-[2ch] text-center font-display text-[26px] font-extrabold leading-none text-primary tabular-nums">
          {value}
        </span>
        <button type="button" aria-label="More" className={BTN} disabled={value >= COUNT_MAX} onClick={() => onChange(stepCount(value, 1))}>
          +
        </button>
      </div>
    </div>
  )
}
```

`builder/AvailabilityLine.tsx` (`.avl`, `.avl.wait`, `.avl.no`, plus error):

```tsx
import { cn } from "@/lib/utils"
import { SpinnerRing, TickIcon } from "../practiceIcons"
import type { AvailabilityLine as Line } from "./builderModel"

const TONE: Record<Line["tone"], string> = {
  ok: "text-success-text",
  wait: "text-on-surface-variant",
  short: "text-on-tertiary-container",
  none: "text-on-tertiary-container",
  error: "text-error",
}

export function AvailabilityLine({ line }: { line: Line }) {
  return (
    <p role="status" aria-live="polite" className={cn("m-0 flex items-center gap-1.5 text-[13.5px] font-semibold", TONE[line.tone])}>
      {line.tone === "ok" ? <TickIcon /> : null}
      {line.tone === "wait" ? <SpinnerRing /> : null}
      {line.text}
    </p>
  )
}
```

`builder/MoreFilters.tsx` (the `details.more` fold, K6 and K14):

```tsx
import { PRACTICE_SOURCES } from "@/lib/practiceSources"
import { SUBJECT_CHIP_CLASS } from "./SubjectChoice"

export function MoreFilters({
  bands,
  availableBands,
  source,
  onToggleBand,
  onSource,
}: {
  bands: readonly string[]
  availableBands: readonly string[]
  source: string | null
  onToggleBand: (band: string) => void
  onSource: (source: string | null) => void
}) {
  return (
    <details className="group">
      <summary className="flex min-h-11 cursor-pointer list-none items-center gap-1.5 text-[14px] font-semibold text-primary [&::-webkit-details-marker]:hidden after:ms-1 after:size-[7px] after:-translate-y-0.5 after:rotate-45 after:border-r-2 after:border-b-2 after:border-current group-open:after:translate-y-0.5 group-open:after:-rotate-135">
        Difficulty and source
      </summary>
      <div className="grid gap-3 pt-1">
        <div className="grid gap-1.5">
          <h3 className="text-[12.5px] font-semibold text-on-surface-variant">Difficulty</h3>
          <div className="flex flex-wrap gap-1.5">
            {availableBands.map((band) => (
              <button key={band} type="button" aria-pressed={bands.includes(band)} className={`${SUBJECT_CHIP_CLASS} aria-pressed:bg-primary aria-pressed:text-on-primary aria-pressed:shadow-none`} onClick={() => onToggleBand(band)}>
                {band[0].toUpperCase() + band.slice(1)}
              </button>
            ))}
          </div>
          <p className="text-[12.5px] text-on-surface-variant">None picked means any difficulty.</p>
        </div>
        <div className="grid gap-1.5">
          <h3 className="text-[12.5px] font-semibold text-on-surface-variant">Source</h3>
          <div role="radiogroup" aria-label="Question source" className="flex flex-wrap gap-1.5">
            {PRACTICE_SOURCES.map((opt) => (
              <button key={opt.value ?? "all"} type="button" role="radio" aria-checked={source === opt.value} className={SUBJECT_CHIP_CLASS} onClick={() => onSource(opt.value)}>
                {opt.label}
              </button>
            ))}
          </div>
        </div>
      </div>
    </details>
  )
}
```

- [ ] **Step 2: The sheet** (`builder/SetBuilderSheet.tsx`)

```tsx
/* L4 · set builder sheet. Replaces PracticeGenerator.tsx; every generator feature is on the keep-list. */
import { useRef, useState } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { useNavigate } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet"
import { SkeletonBlock } from "@/components/ui/skeleton"
import { Switch } from "@/components/ui/switch"
import { useToast } from "@/components/ui/toast"
import { ApiError } from "@/lib/api"
import { practiceHubKeys } from "@/lib/practiceHubKeys"
import { useCreatePractice, usePracticePreview, usePracticeTopics } from "@/lib/hooks/usePracticeApi"
import { useReference } from "@/lib/hooks/useReferenceApi"
import type { PracticeFilterSet, PracticePreview } from "@/lib/practiceTypes"
import { PrintIcon } from "../practiceIcons"
import { AvailabilityLine } from "./AvailabilityLine"
import {
  builderView,
  createdToast,
  draftToFilters,
  initialDraft,
  setSource,
  setWeakOnly,
  toggleBand,
  toggleTopic,
  visibleTopicGroups,
  weakServableTopics,
  type BuilderDraft,
} from "./builderModel"
import { CountStepper } from "./CountStepper"
import { MoreFilters } from "./MoreFilters"
import { SubjectChoice } from "./SubjectChoice"
import { TopicChips } from "./TopicChips"

/** `subjectCode: ""` disables `usePracticePreview` until a draft exists. */
const NO_FILTERS: PracticeFilterSet = { subjectCode: "", count: 0, topics: [], weakTopicsOnly: false, difficultyBands: [], source: null }
const GO = "min-h-[50px] w-full rounded-[18px] text-[15.5px] shadow-[0_14px_24px_-16px_oklch(.3_.07_242/.7)] disabled:shadow-none"

export function SetBuilderSheet({
  subjects,
  initialSubject,
  focusTopic,
  onClose,
}: {
  subjects: { code: string; name: string }[]
  initialSubject: string
  focusTopic: string | null
  onClose: () => void
}) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const { data: reference } = useReference()

  // A deep link can name a subject the student is not enrolled in; it still gets a chip.
  const allSubjects = subjects.some((s) => s.code === initialSubject)
    ? subjects
    : [{ code: initialSubject, name: initialSubject }, ...subjects]
  const [subjectCode, setSubjectCode] = useState(initialSubject)
  const subjectName = allSubjects.find((s) => s.code === subjectCode)?.name ?? subjectCode

  const topicsQuery = usePracticeTopics(subjectCode)
  const [draft, setDraft] = useState<BuilderDraft | null>(null)
  const [dropped, setDropped] = useState<string[]>([])
  // K11: prefill exactly once per subject, the moment topics arrive; a refetch never reverts a choice.
  const seededFor = useRef<string | null>(null)
  if (topicsQuery.data && seededFor.current !== subjectCode) {
    seededFor.current = subjectCode
    const seed = initialDraft(subjectCode, topicsQuery.data, subjectCode === initialSubject ? focusTopic : null)
    setDraft(seed.draft)
    setDropped(seed.dropped)
  }

  const filters = draft && draft.subjectCode === subjectCode ? draftToFilters(draft) : NO_FILTERS
  const previewQuery = usePracticePreview(filters)
  const create = useCreatePractice()
  const [race, setRace] = useState<PracticePreview | null>(null)
  const [createFailed, setCreateFailed] = useState(false)

  const view = builderView({
    topicsStatus: topicsQuery.status,
    topics: topicsQuery.data,
    previewStatus: previewQuery.status,
    preview: previewQuery.data,
    race,
    creating: create.isPending,
    createFailed,
    subjectName,
    otherSubjectNames: allSubjects.filter((s) => s.code !== subjectCode).map((s) => s.name),
    dropped,
  })

  function edit(next: BuilderDraft) {
    setRace(null)
    setCreateFailed(false)
    setDraft(next)
  }

  function chooseSubject(code: string) {
    if (code === subjectCode) return
    setRace(null)
    setCreateFailed(false)
    setDraft(null)
    setDropped([])
    setSubjectCode(code)
  }

  async function make(dest: "set" | "print") {
    if (!draft) return
    setRace(null)
    setCreateFailed(false)
    try {
      const created = await create.mutateAsync(draftToFilters(draft))
      void queryClient.invalidateQueries({ queryKey: practiceHubKeys.runsAll })
      const note = createdToast(created, view.startCount ?? draft.count)
      if (note) toast({ title: note })
      navigate(
        dest === "set" ? `/student/practice/set/${created.assignmentId}` : `/student/practice/print/${created.assignmentId}`,
        { replace: true },
      )
    } catch (err) {
      // K22: a 409 carries the preview payload; show that refusal, not a generic failure.
      if (err instanceof ApiError && err.status === 409 && err.detail) {
        setRace(err.detail as PracticePreview)
      } else {
        setCreateFailed(true)
        void previewQuery.refetch()
      }
    }
  }

  return (
    <Sheet open onOpenChange={(open) => (open ? undefined : onClose())}>
      <SheetContent
        side="adaptive"
        aria-describedby={undefined}
        nativeHeader={<SheetTitle className="text-[22px] font-extrabold text-on-surface">Practice set</SheetTitle>}
        nativeBodyClassName="grid gap-3 px-5 pt-1 pb-6"
      >
        <div className="grid gap-3">
          {view.errorBanner ? (
            <div role="alert" className="rounded-xl bg-error-container px-3 py-2.5 text-[13.5px] font-semibold leading-[1.35] text-on-error-container">
              {view.errorBanner}
            </div>
          ) : null}

          {allSubjects.length > 0 ? (
            <SubjectChoice subjects={allSubjects} value={subjectCode} onChange={chooseSubject} />
          ) : null}

          {view.body === "loading" ? (
            <div aria-busy="true" aria-label="Loading topics" className="flex flex-wrap gap-1.5">
              {[96, 120, 84, 132, 104].map((w) => (
                <SkeletonBlock key={w} className="h-11 rounded-xl" style={{ width: w }} />
              ))}
            </div>
          ) : null}

          {view.body === "topicsError" ? (
            <div role="alert" className="flex items-center justify-between gap-3 rounded-xl bg-error-container px-3 py-2.5 text-[13.5px] font-semibold text-on-error-container">
              Couldn’t load topics.
              <button type="button" className="min-h-11 font-bold underline" onClick={() => void topicsQuery.refetch()}>
                Try again
              </button>
            </div>
          ) : null}

          {view.body === "noQuestions" && view.noQuestions ? (
            <div className="grid justify-items-center gap-2 py-2 text-center">
              <h3 className="font-display text-[28px] font-extrabold leading-[1.15] tracking-[-0.02em] text-balance text-primary">
                {view.noQuestions.heading}
              </h3>
              <p className="max-w-[30ch] text-[15px] font-medium leading-[1.4] text-on-surface-variant">{view.noQuestions.body}</p>
            </div>
          ) : null}

          {view.body === "ready" && draft && topicsQuery.data ? (
            <>
              <Switch
                layout="row"
                label="Weak topics only"
                checked={draft.weakOnly}
                onCheckedChange={(on) => edit(setWeakOnly(draft, on, weakServableTopics(topicsQuery.data)))}
                wrapperClassName="min-h-11 justify-center text-[14px] font-semibold"
              />
              <TopicChips
                groups={visibleTopicGroups(topicsQuery.data, draft.weakOnly)}
                selected={draft.selected}
                onToggle={(topic) => edit(toggleTopic(draft, topic))}
              />
              {view.droppedNote ? <p className="text-[12.5px] text-on-surface-variant">{view.droppedNote}</p> : null}
              {view.untopicedNote ? <p className="text-[12.5px] text-on-surface-variant">{view.untopicedNote}</p> : null}
              <CountStepper value={draft.count} onChange={(count) => edit({ ...draft, count })} />
              <MoreFilters
                bands={draft.bands}
                availableBands={reference?.difficultyBands ?? []}
                source={draft.source}
                onToggleBand={(band) => edit(toggleBand(draft, band))}
                onSource={(source) => edit(setSource(draft, source))}
              />
              {view.line ? <AvailabilityLine line={view.line} /> : null}
            </>
          ) : null}

          <Button
            variant="primary"
            size="lg"
            className={GO}
            disabled={view.cta.disabled}
            aria-disabled={view.cta.disabled || undefined}
            onClick={() => void make("set")}
          >
            {view.cta.label}
          </Button>
          {view.showPrint ? (
            <button
              type="button"
              className="inline-flex min-h-11 items-center justify-center gap-1.5 text-[14px] font-semibold text-on-surface-variant"
              onClick={() => void make("print")}
            >
              <PrintIcon /> Print instead
            </button>
          ) : null}
        </div>
      </SheetContent>
    </Sheet>
  )
}
```

Check before building:
- `SheetContent` gives the web (non-native) branch a title. If it renders `nativeHeader` first there (its docstring says so), the title shows on both. Otherwise add a visible `SheetTitle` for the web branch.
- `Switch`'s `layout="row"` puts the label start and the control end, which matches `.wtog`.

- [ ] **Step 3: Enable the sheet in `PracticeHub.tsx`**

Uncomment the `SetBuilderSheet` import and the render block left by Task 8.

- [ ] **Step 4: Verify**

Run: `cd web && npm run typecheck && npx vitest run tests/unit/practiceBuilderModel.test.ts && npm run check:copy && npx oxlint src/portals/student/screens/practice`
Expected: exit 0. The interactive check runs in Task 11, once the route is mounted.

- [ ] **Step 5: Commit**

```bash
P=web/src/portals/student/screens/practice
PYTHONPATH=$(git rev-parse --show-toplevel) pre-commit run --files $P/builder/*.tsx $P/PracticeHub.tsx
git add $P/builder
git commit -S -m "feat(web): build the set builder sheet" -- $P/builder $P/PracticeHub.tsx
```

### Task 10: Past papers screen and paper sheet (PP, PQ)

**Files:**
- Create: `web/src/portals/student/screens/practice/papers/PastPapers.tsx`
- Create: `web/src/portals/student/screens/practice/papers/PastPaperSheet.tsx`

**Interfaces:**
- Consumes: Task 7's model, `usePastPapers`/`useCreateFromPaper` (Task 4), `usePracticeHubData().builderSubjects` (Task 8, for the subject list), `SubjectChoice` (Task 9), F1 `HairRows`/`HairRow`/`GhostRows`, and `Sheet`.
- Produces: `PastPapers` (named export), routed at `/student/practice/papers` in Task 11. `PastPaperSheet(props: { paper: PastPaper; subjectName: string; onClose: () => void })`.

The header is the shell's (title "Past papers", back to Practice). The mock's "Cambridge IGCSE" subline renders as the first page line. Its text comes from the selected subject's qualification level label (`qualificationLevelLabel`, as `shell.tsx` uses it), and it hides when unknown.

- [ ] **Step 1: `PastPapers.tsx`**

```tsx
/* L4 · past papers (mock PP). Grouped by paper number, scores in Mono, a sheet to print. */
import { useState } from "react"
import { GhostRows, HairRow, HairRows } from "@/components/redesign"
import { Button } from "@/components/ui/button"
import { PageHeading } from "@/components/ui/page-heading"
import { usePastPapers } from "@/lib/hooks/usePracticeHubApi"
import type { PastPaper } from "@/lib/practiceHubTypes"
import { SubjectChoice } from "../builder/SubjectChoice"
import { usePracticeHubData } from "../hub/usePracticeHubData"
import { ChevronIcon, PaperIcon, TickIcon } from "../practiceIcons"
import { emptyPapersCopy, paperGroups, papersState } from "./papersModel"
import { PastPaperSheet } from "./PastPaperSheet"

export function PastPapers() {
  const { builderSubjects } = usePracticeHubData()
  const [chosen, setChosen] = useState<string | null>(null)
  const subjectCode = chosen ?? builderSubjects[0]?.code ?? ""
  const subjectName = builderSubjects.find((s) => s.code === subjectCode)?.name ?? subjectCode
  const query = usePastPapers(subjectCode)
  const [open, setOpen] = useState<PastPaper | null>(null)
  const state = subjectCode ? papersState(query.status, query.data?.papers) : "empty"

  return (
    <div className="mx-auto flex w-full max-w-[880px] flex-col gap-6 pb-6">
      <PageHeading repeatsTitle className="sr-only">Past papers</PageHeading>
      {builderSubjects.length > 1 ? <SubjectChoice subjects={builderSubjects} value={subjectCode} onChange={setChosen} /> : null}

      {state === "loading" ? <GhostRows rows={4} withLeading /> : null}

      {state === "error" ? (
        <div role="alert" className="grid justify-items-center gap-3 py-6 text-center">
          <h2 className="font-display text-[28px] font-extrabold leading-[1.15] tracking-[-0.02em] text-primary">We couldn’t load past papers</h2>
          <Button variant="primary" size="lg" className="min-h-[50px] w-full max-w-[300px] rounded-[18px]" onClick={() => void query.refetch()}>
            Try again
          </Button>
        </div>
      ) : null}

      {state === "empty" ? (
        (() => {
          const copy = emptyPapersCopy(subjectName, builderSubjects.filter((s) => s.code !== subjectCode).map((s) => s.name))
          return (
            <div className="grid justify-items-center gap-2 py-6 text-center">
              <h2 className="font-display text-[28px] font-extrabold leading-[1.15] tracking-[-0.02em] text-balance text-primary">{copy.heading}</h2>
              <p className="max-w-[30ch] text-[15px] font-medium leading-[1.4] text-on-surface-variant">{copy.body}</p>
            </div>
          )
        })()
      ) : null}

      {state === "ready" && query.data
        ? paperGroups(query.data.papers).map((group) => (
            <section key={group.paperNumber} aria-label={group.heading} className="grid gap-1">
              <h2 className="text-[18px] font-extrabold tracking-[-0.01em] text-on-surface">{group.heading}</h2>
              <HairRows aria-label={group.heading}>
                {group.rows.map((row) => (
                  <HairRow
                    key={row.paperId}
                    leading={
                      <span
                        className={`grid size-10 place-items-center rounded-[13px] ${row.done ? "bg-success-container text-success-text" : "bg-success-container/70 text-success-text"}`}
                      >
                        {row.done ? <TickIcon /> : <PaperIcon size={20} />}
                      </span>
                    }
                    title={row.title}
                    sub={row.sub}
                    trailing={
                      <span className="flex items-center gap-3">
                        {row.score ? <span className="font-mono text-[14px] font-bold text-success-text">{row.score}</span> : null}
                        <ChevronIcon className="text-on-surface-variant" />
                      </span>
                    }
                    onClick={() => setOpen(query.data.papers.find((p) => p.paperId === row.paperId) ?? null)}
                  />
                ))}
              </HairRows>
            </section>
          ))
        : null}

      {open ? <PastPaperSheet paper={open} subjectName={subjectName} onClose={() => setOpen(null)} /> : null}
    </div>
  )
}
```

`HairRow` might already render a trailing chevron for clickable rows. If so, drop the explicit `ChevronIcon` here and in `RecentRuns`/`WinBackList`, so each row has exactly one chevron. Check the F1 source.

- [ ] **Step 2: `PastPaperSheet.tsx`**

```tsx
/* L4 · past paper sheet (mock PQ). */
import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet"
import { useCreateFromPaper } from "@/lib/hooks/usePracticeHubApi"
import type { PastPaper } from "@/lib/practiceHubTypes"
import { ClockIcon, PaperIcon, PrintIcon } from "../practiceIcons"
import { paperSheetView, type PaperOption } from "./papersModel"

const OPTION =
  "grid min-h-[60px] grid-cols-[40px_minmax(0,1fr)] items-center gap-3 rounded-2xl px-3 py-2.5 text-start text-on-surface bg-surface-container-lowest shadow-[inset_0_0_0_1.5px_var(--color-outline-variant)] aria-checked:bg-primary-container aria-checked:shadow-[inset_0_0_0_2px_var(--color-primary)] focus-visible:outline-[2.5px] focus-visible:outline-offset-2 focus-visible:outline-primary"

export function PastPaperSheet({ paper, subjectName, onClose }: { paper: PastPaper; subjectName: string; onClose: () => void }) {
  const navigate = useNavigate()
  const view = paperSheetView(paper, subjectName)
  const [choice, setChoice] = useState<PaperOption>(view.defaultOption)
  const create = useCreateFromPaper()

  async function print() {
    try {
      const created = await create.mutateAsync({ paperId: paper.paperId, timed: choice === "timed" })
      navigate(`/student/practice/print/${created.assignmentId}`)
    } catch {
      // The errl banner below reads create.isError.
    }
  }

  return (
    <Sheet open onOpenChange={(o) => (o ? undefined : onClose())}>
      <SheetContent
        side="adaptive"
        aria-describedby={undefined}
        nativeHeader={
          <div className="flex items-center gap-3">
            <span className="grid size-10 place-items-center rounded-[13px] bg-success-container text-success-text">
              <PaperIcon size={20} />
            </span>
            <div>
              <SheetTitle className="text-[22px] font-extrabold text-on-surface">{view.title}</SheetTitle>
              <span className="text-[13px] font-medium text-on-surface-variant">{view.sub}</span>
            </div>
          </div>
        }
        nativeBodyClassName="grid gap-3 px-5 pt-1 pb-6"
      >
        <div className="grid gap-3">
          {create.isError ? (
            <div role="alert" className="rounded-xl bg-error-container px-3 py-2.5 text-[13.5px] font-semibold text-on-error-container">
              Couldn’t get this paper ready. Try again.
            </div>
          ) : null}
          <div role="radiogroup" aria-label="How do you want to do it" className="grid gap-2">
            {view.options.map((o) => (
              <button key={o.key} type="button" role="radio" aria-checked={choice === o.key} className={OPTION} onClick={() => setChoice(o.key)}>
                <span className="grid size-10 place-items-center rounded-[13px] text-primary">{o.key === "timed" ? <ClockIcon /> : <PrintIcon />}</span>
                <span className="grid gap-0.5">
                  <b className="text-[15px] font-bold">{o.title}</b>
                  <span className="text-[13px] text-on-surface-variant">{o.body}</span>
                </span>
              </button>
            ))}
          </div>
          <Button
            variant="primary"
            size="lg"
            className="min-h-[50px] w-full rounded-[18px] text-[15.5px]"
            disabled={!view.printable || create.isPending}
            onClick={() => void print()}
          >
            {create.isPending ? "Getting it ready…" : "Print paper"}
          </Button>
          <p className="text-[14px] font-medium leading-[1.4] text-pretty text-on-surface-variant">
            {view.printable ? view.hint : "We can't print this one yet."}
          </p>
        </div>
      </SheetContent>
    </Sheet>
  )
}
```

- [ ] **Step 3: Verify and commit**

Run: `cd web && npm run typecheck && npm run check:copy && npx oxlint src/portals/student/screens/practice/papers`
Expected: exit 0.

```bash
P=web/src/portals/student/screens/practice/papers
PYTHONPATH=$(git rev-parse --show-toplevel) pre-commit run --files $P/PastPapers.tsx $P/PastPaperSheet.tsx
git add $P
git commit -S -m "feat(web): build the past papers screen and sheet" -- $P
```

---

## Wiring

### Task 11: Routes, the Practice tab, the sidebar item and crumbs (coordinate with F1)

**Files:**
- Modify: `web/src/portals/student/index.tsx` (lazy imports near lines 82–93, route entries at lines 395–398)
- Modify: `web/src/portals/student/shell.tsx` (the Practice tab's `to` only, as F1 left it)
- Modify: `web/src/portals/student/data.ts` (`studentNavItems` line 36, `crumbs` line 125, `currentSubjectCode` line 89, `resolveCrumb` lines 189–190, `resolveCrumbTrail` lines 234–243)
- Test: `web/tests/unit/navigation.test.ts`

**F1 coordination (coordinator ruling: the approved mock wins).** F1 implements the whole bar. Phone tabs are Home, Practice, [Scan centre], Subjects, Me. The desktop rail is Home, Practice, Subjects and Me, plus "Scan a paper". F1's Practice entry ships pointing at a placeholder. L4 is cut after F1 merges, rebases, and changes only the Practice tab's `to` (and the rail item's, if it is separate) to `/student/practice`. L4 does not add, remove, reorder, rename or re-icon any tab. It does not touch F1's tab tests either, beyond what pointing at a newly mounted route needs.

- [ ] **Step 1: Update the failing navigation tests first**

In `web/tests/unit/navigation.test.ts`, replace the `it("links Home and nothing else", ...)` test (lines 178–198) and its comment block with:

```ts
  /*
   * L4 mounted `/student/practice` as the Practice tab root, so "Practice"
   * is now a real destination and links there. Every other grouping label
   * ("Marking", "Flashcards", "Study plan") still has no route and stays
   * unlinked.
   */
  it("links Home, and Practice now that it is a mounted tab root", () => {
    const allowed: Record<string, string> = { Home: "/student", Practice: "/student/practice" }
    const paths = [
      "/student",
      "/student/correct",
      "/student/board",
      "/student/subject/0625",
      "/student/practice/0625",
      "/student/practice/set/abc-123",
      "/student/practice/papers",
      "/student/flashcards/0625",
      "/student/plan/0625",
      "/student/plan/0625/session/abc-123",
      "/student/result/abc-123",
    ]
    for (const path of paths) {
      for (const crumb of resolveCrumbTrail(path)) {
        if (crumb.to !== undefined) {
          expect(allowed[crumb.label], `linked crumb "${crumb.label}" on ${path}`).toBe(crumb.to)
        }
      }
    }
  })

  it("the builder deep link reads as the Practice page, a tab root", () => {
    expect(resolveCrumbTrail("/student/practice/0625").map((c) => c.label)).toEqual(["Home", "Practice"])
    expect(resolveCrumbTrail("/student/practice/papers")).toEqual([
      { label: "Home", to: "/student" },
      { label: "Practice", to: "/student/practice" },
      { label: "Past papers" },
    ])
  })
```

Add `"/student/practice/set/abc-123"` to the `linked` array of `it("points every link it does emit at a route the router mounts", ...)` (line 201), so the Practice link is checked against the mounted routes.

Add a new describe block at the end of the file:

```ts
import { currentSubjectCode } from "@/portals/student/data"

describe("Practice tab — L4", () => {
  it("is a student bottom tab pointing at the mounted tab root", () => {
    const practice = STUDENT_BOTTOM_TABS.find((t) => t.label === "Practice")
    expect(practice?.to).toBe("/student/practice")
    expect(matchesSomeRoute("/student/practice", studentRoutePaths)).toBe(true)
  })

  it("mounts past papers and keeps the builder deep link", () => {
    expect(matchesSomeRoute("/student/practice/papers", studentRoutePaths)).toBe(true)
    expect(matchesSomeRoute("/student/practice/0625", studentRoutePaths)).toBe(true)
  })

  it("never reads 'papers' as a subject code for the sidebar", () => {
    expect(currentSubjectCode("/student/practice/papers")).toBeNull()
    expect(currentSubjectCode("/student/practice/0625")).toBe("0625")
  })
})
```

Merge the `currentSubjectCode` import into the existing `@/portals/student/data` import line.

Run: `cd web && npx vitest run tests/unit/navigation.test.ts`
Expected: FAIL. The Practice tab is missing, `/student/practice` is not mounted, and "papers" is read as a code.

- [ ] **Step 2: Routes** (`index.tsx`)

Replace the `PracticeGenerator` lazy import (lines 82–84) with:

```tsx
const PracticeHub = lazy(() =>
  import("./screens/practice/PracticeHub").then((m) => ({ default: m.PracticeHub })),
)
const PastPapers = lazy(() =>
  import("./screens/practice/papers/PastPapers").then((m) => ({ default: m.PastPapers })),
)
```

Replace the `practice/:subjectCode` entry (lines 394–398) with:

```tsx
    {
      path: "practice",
      element: <PracticeHub />,
      handle: { title: "Practice", skeleton: "list" },
    },
    {
      path: "practice/papers",
      element: <PastPapers />,
      handle: { title: "Past papers", skeleton: "list" },
    },
    {
      // K1: the builder deep link. Same hub underneath, sheet open for this subject.
      path: "practice/:subjectCode",
      element: <PracticeHub />,
      handle: { title: "Practice", skeleton: "list" },
    },
```

Static segments (`papers`, `set`, `result`, `print`) outrank `:subjectCode` in react-router 7, so the existing practice set, result and print routes are unaffected.

- [ ] **Step 3: Tab and sidebar**

`shell.tsx`: in F1's `STUDENT_BOTTOM_TABS`, set the Practice entry's `to` to `/student/practice`. Nothing else changes.

`data.ts`: if F1's rail (`studentNavItems` or its replacement) has a Practice item, set its `to` to `/student/practice`. If the rail has no Practice item, stop and ask F1, because adding rail items is F1's job.

Add to `crumbs`:

```ts
  "/student/practice": "Home / Practice",
  "/student/practice/papers": "Home / Practice / Past papers",
```

In `resolveCrumb`, change the practice generator arm to:

```ts
  // L4: the builder is a sheet over the Practice tab, so the page is "Practice".
  if (/^\/student\/practice\/[^/]+$/.test(pathname)) return "Home / Practice"
```

The exact `crumbs` lookup runs first, so `/practice/papers` keeps its own crumb.

`currentSubjectCode`: change the practice arm to `/^\/student\/practice\/(?!papers$)([^/]+)$/`.

`resolveCrumbTrail`: replace the body with:

```ts
const CRUMB_LINKS: Record<string, string> = { Home: "/student", Practice: "/student/practice" }

export function resolveCrumbTrail(pathname: string): Crumb[] {
  const parts = resolveCrumb(pathname).split(" / ")
  return parts.map((label, i) => {
    if (i === parts.length - 1) return { label }
    const to = CRUMB_LINKS[label]
    return to ? { label, to } : { label }
  })
}
```

Update its doc comment's last paragraph: "Home" and, since L4, "Practice" are linked. The other grouping labels still have no route.

- [ ] **Step 4: Run the tests and try it by hand**

Run: `cd web && npx vitest run tests/unit/navigation.test.ts tests/unit/navigationModel.test.ts tests/unit/navigationDirection.test.ts && npm run typecheck && npm run check:native`
Expected: all pass.

Then run the app against the e2e backend (`cd web && npx playwright test e2e/_smoke.spec.ts` boots both servers; or `npm run dev` with the backend on :8000). Log in as `seed.practice.students.active` and check:
- `/student/practice` shows the tiles, win rows and Recent.
- Tapping "Practice set" opens the sheet with the weak topic pressed.
- The line reads "Only N questions match".
- Changing the count re-checks.
- "Start with N" lands on the practice run.
- Back closes the sheet.
- `/student/practice/0580` shows "No Mathematics questions yet".

- [ ] **Step 5: Commit**

```bash
PYTHONPATH=$(git rev-parse --show-toplevel) pre-commit run --files web/src/portals/student/index.tsx web/src/portals/student/shell.tsx web/src/portals/student/data.ts web/tests/unit/navigation.test.ts
git commit -S -m "feat(web): make Practice a student tab root" -- web/src/portals/student/index.tsx web/src/portals/student/shell.tsx web/src/portals/student/data.ts web/tests/unit/navigation.test.ts
```

---

## Tests and finish

### Task 12: Playwright happy path, the S-20 acceptance spec and the audit registry

**Files:**
- Create: `web/e2e/practice-hub.spec.ts`
- Modify: `web/e2e/phase4-practice.spec.ts` (owned: it tests the screen L4 replaces)
- Modify: `web/scripts/audit.mjs` (the three S-20 entries at lines ~2007–2060, one new helper next to `pressCheckboxOnce`, and one new hub entry)

- [ ] **Step 1: The happy path** (`web/e2e/practice-hub.spec.ts`)

```ts
import { test, expect, type Page } from "@playwright/test"
import { watchConsole } from "./console-errors"
import { injectSession, readSeed, type SeedAccount } from "./seed"

/*
 * L4 · the Practice tab end to end on the seeded `practice.students.active`
 * account: tiles, win marks back, Recent with the unsubmitted set to resume,
 * the builder sheet with a live match count, and a created set.
 */

async function asStudent(page: Page, account: SeedAccount): Promise<void> {
  await injectSession(page, { accessToken: account.accessToken, userId: account.userId, role: "student" })
}

test("Practice tab · hub, builder sheet and a started set", async ({ page }) => {
  const seed = readSeed()
  const errors = watchConsole(page)
  await asStudent(page, seed.practice.students.active)
  await page.goto("/student/practice")

  for (const name of ["Practice set", "Flashcards", "Past papers", "Placement test"]) {
    await expect(page.getByText(name, { exact: true })).toBeVisible({ timeout: 15_000 })
  }
  // The seed's one deliberate wrong answer is a real weakness, so a topic is worth marks.
  await expect(page.getByText("Win marks back")).toBeVisible()
  await expect(page.getByText(/^\+\d+$/).first()).toBeVisible()
  // The seed's created-but-untouched set is the resume row.
  await expect(page.getByText("Resume", { exact: true })).toBeVisible()

  await page.getByText("Practice set", { exact: true }).click()
  const sheet = page.getByRole("dialog", { name: "Practice set" })
  await expect(sheet).toBeVisible()
  await expect(sheet.getByRole("status")).toHaveText(/questions? match/, { timeout: 15_000 })

  await sheet.getByRole("button", { name: "More" }).click()
  await expect(sheet.getByRole("status")).toHaveText(/questions? match/, { timeout: 15_000 })

  await sheet.getByRole("button", { name: /^Start/ }).click()
  await expect(page).toHaveURL(/\/student\/practice\/set\/[0-9a-f-]+$/, { timeout: 15_000 })

  expect(errors, `console/page errors: ${JSON.stringify(errors, null, 2)}`).toEqual([])
})

test("Practice tab · past papers opens the paper sheet or the honest empty state", async ({ page }) => {
  const seed = readSeed()
  const errors = watchConsole(page)
  await asStudent(page, seed.practice.students.active)
  await page.goto("/student/practice/papers")

  const empty = page.getByText(/papers to print yet/)
  const firstRow = page.getByRole("listitem").filter({ hasText: /·/ }).first()
  await expect(empty.or(firstRow)).toBeVisible({ timeout: 15_000 })
  if (await firstRow.isVisible()) {
    await firstRow.click()
    await expect(page.getByRole("dialog")).toBeVisible()
    await expect(page.getByRole("button", { name: "Print paper" })).toBeVisible()
  }

  expect(errors, `console/page errors: ${JSON.stringify(errors, null, 2)}`).toEqual([])
})
```

- [ ] **Step 2: Rewrite the three S-20 acceptance tests against the sheet** (`phase4-practice.spec.ts`)

Keep the file header and `asStudent`. Delete `checkOnce`, and add:

```ts
async function switchOnOnce(page: Page, name: string): Promise<void> {
  const sw = page.getByRole("switch", { name })
  await expect(sw).toBeVisible({ timeout: 15_000 })
  if ((await sw.getAttribute("aria-checked")) !== "true") await sw.click()
  await expect(sw).toHaveAttribute("aria-checked", "true")
}

const escapeRegExp = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
```

Test 1, the generated set targets the seeded weakness. Same measurements, new controls:

```ts
  await asStudent(page, seed.practice.students.active)
  await page.goto(`/student/practice/${seed.practice.subjectCode}`)
  const sheet = page.getByRole("dialog", { name: "Practice set" })

  // Trap 1: the honest shortfall is the normal path for this corpus.
  await expect(sheet.getByText(/Only \d+ questions? match/)).toBeVisible({ timeout: 15_000 })

  // THE ACCEPTANCE ASSERTION: the seeded weak topic's chip is pressed.
  const weakTopic = seed.studyPlan.activeSessionTopic
  await expect(sheet.getByRole("button", { name: new RegExp(`^${escapeRegExp(weakTopic)} \\d+$`) })).toHaveAttribute(
    "aria-pressed",
    "true",
  )
  // And the prefill is selective.
  await expect(sheet.getByRole("group", { name: "Topics" }).locator('[aria-pressed="true"]')).toHaveCount(1)
```

Test 2, the bare account is refused:

```ts
  await asStudent(page, seed.practice.students.bare)
  await page.goto(`/student/practice/${seed.practice.subjectCode}`)
  const sheet = page.getByRole("dialog", { name: "Practice set" })
  await expect(sheet.getByRole("switch", { name: "Weak topics only" })).toBeVisible({ timeout: 15_000 })
  await expect(sheet.getByRole("group", { name: "Topics" }).locator('[aria-pressed="true"]')).toHaveCount(0)

  // Trap 2: the refusal only exists once the filter is applied.
  await switchOnOnce(page, "Weak topics only")
  await expect(sheet.getByText("No weak topics yet. Turn this off to pick any topic.")).toBeVisible({ timeout: 15_000 })
  await expect(sheet.getByText(/questions? match/)).toHaveCount(0)
  await expect(sheet.getByRole("button", { name: "Start now" })).toBeDisabled()
```

Test 3, 0580 gets the honest no-questions state:

```ts
  await asStudent(page, seed.practice.students.active)
  await page.goto("/student/practice/0580")
  const sheet = page.getByRole("dialog", { name: "Practice set" })
  await expect(sheet.getByText(/^No .+ questions yet$/)).toBeVisible({ timeout: 15_000 })
  await expect(sheet.getByText("No weak topics yet", { exact: false })).toHaveCount(0)
  await expect(sheet.getByRole("button", { name: "Start now" })).toBeDisabled()
```

Update each test's comments where they name old copy ("Only N of M requested questions match", "No practice material for this filter set", "Practice for <subject>", the checkbox). The reasoning blocks stay, because they describe the measurements, which have not changed.

- [ ] **Step 3: Audit registry** (`web/scripts/audit.mjs`)

Add next to `pressCheckboxOnce`:

```js
/**
 * Turn a `role="switch"` on ONLY if it is off (the set builder's "Weak topics
 * only", L4). Same idempotent shape as `pressCheckboxOnce`; the switch is
 * named by its `<label for>`, `aria-labelledby` or `aria-label`.
 */
async function pressSwitchOnce(page, labelPattern, timeout = 15_000) {
  const handle = await page.waitForFunction(
    (source) => {
      const re = new RegExp(source, "i")
      return (
        Array.from(document.querySelectorAll('[role="switch"]')).find((el) => {
          const byFor = el.id ? document.querySelector(`label[for="${el.id}"]`)?.textContent : null
          const byIds = (el.getAttribute("aria-labelledby") || "")
            .split(/\s+/)
            .map((id) => document.getElementById(id)?.textContent || "")
            .join(" ")
          const text = byFor || byIds || el.getAttribute("aria-label") || el.closest("label")?.textContent || ""
          return re.test(text)
        }) ?? null
      )
    },
    { timeout },
    labelPattern,
  )
  const element = handle.asElement()
  if (!element) throw new Error(`No switch found labelled ${labelPattern}`)
  if ((await element.evaluate((el) => el.getAttribute("aria-checked"))) !== "true") await element.click()
  await page.waitForFunction((el) => el.getAttribute("aria-checked") === "true", { timeout }, element)
}
```

In the three S-20 entries, change only:
- default entry `ready`: `waitForText(page, "Only \\d+ questions? match")`
- no-questions `ready`: `waitForText(page, "No .+ questions yet")`
- no-weaknesses `ready`: `await pressSwitchOnce(page, "Weak topics only")` then `await waitForText(page, "No weak topics yet")`
- the comments that name `PracticeGenerator.tsx`, which now name `builder/SetBuilderSheet.tsx`

Delete `pressCheckboxOnce` only if nothing else calls it (`grep -n "pressCheckboxOnce" web/scripts/audit.mjs`).

Add one entry before the S-20 block:

```js
    {
      // L4 · Practice tab root (mock C), `active` session: tiles, win marks back, Recent.
      screenId: "S-20",
      slug: "student-practice-hub",
      path: "/student/practice",
      session: practiceActiveSession,
      ready: (page) => waitForText(page, "Win marks back"),
      authed: true,
    },
```

If a test pins the registry's slugs or screen ids (`grep -rln "student-practice-generator" web/tests web/e2e web/scripts`), add the new slug there as well.

- [ ] **Step 4: Run**

Run: `cd web && npx playwright test e2e/practice-hub.spec.ts e2e/phase4-practice.spec.ts --project=chromium`
Expected: 5 passed. Then prove the acceptance test can fail: temporarily make `initialDraft` select every servable topic. Expect "the generated set targets a seeded weakness" to fail on the `toHaveCount(1)`. Revert.

Run the audit's syntax check only (the full audit is a long run, so leave it to CI): `node --check web/scripts/audit.mjs`.

- [ ] **Step 5: Commit**

```bash
PYTHONPATH=$(git rev-parse --show-toplevel) pre-commit run --files web/e2e/practice-hub.spec.ts web/e2e/phase4-practice.spec.ts web/scripts/audit.mjs
git commit -S -m "test(web): cover the Practice tab and move S-20 checks to the builder sheet" -- web/e2e/practice-hub.spec.ts web/e2e/phase4-practice.spec.ts web/scripts/audit.mjs
```

### Task 13: Side-by-side fidelity screenshots, drift fixes, `/impeccable polish`

**Files:**
- Scratch only (not committed): `$SCRATCH/l4-fidelity/mock.mjs` and the PNGs
- Modify: whatever drift fixes touch, all inside the owned files

- [ ] **Step 1: Screenshot the mock frames**

Serve the mocks: `python3 -m http.server 8765 -d .impeccable/mocks/student-r2` (run it in the background). Save this as `$SCRATCH/l4-fidelity/mock.mjs`, where `$SCRATCH` is the session scratchpad:

```js
import { chromium } from "@playwright/test"
const out = process.argv[2]
const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1400, height: 1000 }, deviceScaleFactor: 2 })
await page.goto("http://127.0.0.1:8765/practice-hub-final.html")
for (const id of ["CF", "CN", "CS", "CZ", "CL", "CE", "PS", "CB1", "CB2", "CB3", "CB4", "PP", "PQ", "CDK"]) {
  await page.locator(`#${id}`).screenshot({ path: `${out}/mock-${id}.png` })
}
await browser.close()
```

Run it from the web package so Playwright resolves: `cd web && node $SCRATCH/l4-fidelity/mock.mjs $SCRATCH/l4-fidelity`.

- [ ] **Step 2: Screenshot the app**

Use the e2e harness with the seeded accounts, at 390×844 and 1280×820:
- `/student/practice` as `active` (CN or CF)
- the `bare` account for first time if it has no papers (CZ); otherwise note which seed account shows CZ and CS
- the sheet at `/student/practice/{code}` (PS/CB2), and `/student/practice/0580` (CB3)
- `/student/practice/papers` (PP)

Route-intercept `**/api/student/practice/runs*` with a 500 for CE, and with a held response for CL. Do the same with `**/api/student/practice/*/preview*` for CB1, and with a 500 on `POST **/api/student/practice` for CB4. Write these captures as a temporary spec in the scratchpad, run it with `npx playwright test <path> --project=chromium`, and never commit it.

- [ ] **Step 3: Compare and fix drift**

Put each pair side by side. For every visible difference in spacing, size, colour, weight, radius, order or copy, fix it in the owned files, or record why it stays:
- the shell wins (header, tab bar, sheet chrome)
- a contract component's geometry (raise it with F1)
- a listed honesty or copy change (Needs user decision)

There is no pixel gate (master rule).

- [ ] **Step 4: Polish**

The designer invokes `/impeccable polish` on `PracticeHub.tsx`, `builder/*` and `papers/*`. It re-checks:
- 44px targets and no text under 12px
- contrast, focus rings, reduced motion
- Binny exactly once per screen

Then re-run Task 8–11 verifications and the Task 12 specs.

- [ ] **Step 5: Commit the fixes**

```bash
PYTHONPATH=$(git rev-parse --show-toplevel) pre-commit run --files <changed files>
git commit -S -m "fix(web): close Practice tab drift against the mock" -- <changed files>
```

### Task 14: Keep-list check, then delete the old generator

**Files:**
- Delete: `web/src/portals/student/screens/practice/PracticeGenerator.tsx`
- Modify: `web/src/portals/student/screens/practice/practiceData.ts` (remove `practiceUnavailableMessage` and its interface if unused; refresh the header)
- Modify: `web/tests/unit/practice.test.ts` (remove the `practiceUnavailableMessage` describe block, if the function is removed)

- [ ] **Step 1: Walk the keep-list**

For K1–K33, open the new code at the "Carried by" location and confirm it, then tick it in the PR body. Any item that fails is a blocker: fix it before going on.

- [ ] **Step 2: Find remaining callers**

```bash
TOKENSAVE_DISABLE_GREP_HOOK=1 grep -rn "PracticeGenerator\|practiceUnavailableMessage" web/src web/tests web/e2e web/scripts
```

Expected: only `practiceData.ts`, `practice.test.ts` and comments. Update comments that point at `PracticeGenerator.tsx` to `builder/SetBuilderSheet.tsx`.

- [ ] **Step 3: Delete**

```bash
git rm web/src/portals/student/screens/practice/PracticeGenerator.tsx
```

Remove `practiceUnavailableMessage` and `PracticeUnavailableMessage` from `practiceData.ts`. Its replacement is `unavailableText` in `builderModel.ts`, which `practiceBuilderModel.test.ts` covers. Remove the matching describe block from `practice.test.ts`. In the `practiceData.ts` header, change "S-20 (practice generator)" to "S-20 (set builder sheet, L4)", and add: "Owned by L4; L3 coordinates edits through it."

- [ ] **Step 4: Verify**

Run: `cd web && npm run typecheck && npx vitest run tests/unit/practice.test.ts tests/unit/practiceBuilderModel.test.ts tests/unit/practiceHubModel.test.ts tests/unit/practicePapersModel.test.ts tests/unit/practiceCopy.test.ts tests/unit/practiceHubKeys.test.ts tests/unit/navigation.test.ts tests/unit/practiceSources.test.ts && npm run check:copy && npm run lint`
Expected: exit 0.

Scan the changed files for placeholders: `git diff --name-only origin/develop... | xargs grep -n "TODO\|TBD\|test.only\|test.skip\|\.skip(" || true`. The output must be empty.

- [ ] **Step 5: Commit**

```bash
PYTHONPATH=$(git rev-parse --show-toplevel) pre-commit run --files web/src/portals/student/screens/practice/practiceData.ts web/tests/unit/practice.test.ts
git commit -S -m "refactor(web): remove the old practice generator" -- web/src/portals/student/screens/practice/PracticeGenerator.tsx web/src/portals/student/screens/practice/practiceData.ts web/tests/unit/practice.test.ts
```

### Task 15: Final sweep, push and PR to `develop`

- [ ] **Step 1: Rebase on `develop`** (F1 and any merged W1 lane). Resolve shared-file conflicts with the narrow-edit rule. Re-run Tasks 11 and 12 checks afterwards.

- [ ] **Step 2: Gate sweep, last, on the final tree.** Derive the list from `.github/workflows/ci.yml`, not from memory. At minimum:
  - backend: `PYTHONPATH=$(git rev-parse --show-toplevel) /home/sico/Code/Lemely/.venv/bin/pytest tests/test_practice_hub_repo.py tests/test_web_practice_hub.py tests/test_web_practice.py tests/test_practice_repo.py -q`, plus any `tests/test_*lint*` that scans `lemely/web/routers` or schemas
  - frontend: `cd web && npm run typecheck && npm run lint && npm run check:copy && npx vitest run <the unit files above>`
  - e2e: `npx playwright test e2e/practice-hub.spec.ts e2e/phase4-practice.spec.ts --project=chromium`
  - `PYTHONPATH=$(git rev-parse --show-toplevel) pre-commit run --files $(git diff --name-only origin/develop...)`. Then confirm `git status` is clean, because the ruff hook autofixes and a local pass must match what is committed.
  - `graphify update .`

  Any fix commit after this voids the sweep, so run it again.

- [ ] **Step 3: Push and open the PR**

```bash
git push -u origin redesign/l04-practice-tab
gh pr create --base develop --title "feat: Practice tab and set builder (L4)" --body-file <scratch>/l4-pr.md
```

The PR body holds:
- the keep-list with ticks
- the frame-to-state table
- the screenshots from Task 13
- the small changes from the mock, with reasons. These are:
  - the radiogroup in place of tablist
  - the topic chips showing full syllabus labels and counts, with group headings
  - the subject dot tokens
  - "Build your own" without the invented "10 min"
  - placement minutes from the real estimate
  - the "!" removed from Binny lines
  - the homework "+N more"
  - the "See all" inline expand
  - the amber line token
- the Needs user decision items still open

- [ ] **Step 4:** An Opus reviewer (the skill reviewer template, general-purpose agent) reviews the PR at its head SHA. Fix the findings, get CI green, merge. No rerun of CI without asking, and nothing goes to `main`.

---

## Needs user decision

Each item has a recommendation. The plan already implements the recommendation, so nothing blocks.

1. **Exclamation marks in Binny's lines.** The approved mock says "Vectors first. +9 marks!" and "Good start! Try one set.", but `npm run check:copy` is a CI gate that bans `!` in product copy. **Recommend:** periods ("Vectors first. +9 marks."). The alternative is adding the hub model to `EXCLAMATION_ALLOWLIST` (`web/scripts/check_copy.mjs:277`) with a reason. That is a rule change every lane with Binny lines would want too, so decide it once, in the master plan.
2. **Past paper printing.** No question-paper PDFs are stored. The mock's "Print paper" and its hint "Lemely marks it when you scan your answers" assume real papers and photo-answer marking, and neither exists. `PracticePrint.tsx:20-26` states there is no route to attach a photographed answer. **Recommend (implemented):**
   - List papers that have servable bank questions, or that the student has already done.
   - "Print paper" builds a set from that paper's renderable questions and opens the existing print view.
   - The hint reads "Prints N questions. Lemely marks the answers you type in."
   - "Do it timed" only shows when the syllabus table has a real duration, and it stores the duration as the set's time limit.
   - Consequence: Maths (0580/0606) has no banked questions, so it shows the empty state.

   Real PDFs and photo marking would be a separate project.
3. **The student tab bar: resolved by the coordinator.** The approved mock wins. Phone tabs are Home, Practice, [Scan centre], Subjects, Me. The rail is Home, Practice, Subjects and Me, plus "Scan a paper". F1 builds it, and L4 only points Practice at `/student/practice` (Task 11).
4. **Homework destination.** There is no student route that takes a teacher-assigned quiz today. **Recommend:** the homework row opens `/student/practice/set/:assignmentId`, because `QuizTaker` serves any assignment the student can see. L3 must make `PracticeSet`'s submit route a non-practice quiz somewhere other than the practice result: `GET .../practice/{id}/result` returns 404 for `kind != practice`. A toast and a return to the Practice tab is enough. Listed as an L3 dependency below.
5. **Placement tile with several subjects.** The mock shows one tile and no subject choice. **Recommend (implemented):** open placement for the first enrolled subject that has a test, which is the onboarding rule (`firstAvailablePlacementSubject`). A picker would be a new frame.
6. **"All topics" and "See all" destinations.** The mock has no screens for them. **Recommend (implemented):** "All topics" shows only when there are more than three topics, and opens the top topic's Subject page, which has every topic chip. "See all" expands Recent inline (up to 10).
7. **Flashcards tile target: resolved by the coordinator.** The tile links to `/student/flashcards`, which L10 makes a real route.

## Dependencies on other lanes (beyond the master plan)

- **F1:**
  - `Tile.status` is typed `ReactNode` (F1 is changing the contract to match). `HubTiles` renders the flashcards count in Mono (`TileView.count`), as the mock's `<b>26</b> due today` does.
  - `Tile` should pass `size`/`strokeWidth` (or `className`) to its icon for the 64px faint glyph.
  - `H2Row.link.onClick` is used for "See all".
  - F1 exports no number stepper, so L4 ships `builder/CountStepper.tsx`. L10 builds its own (`flashcards/parts/CountStepper.tsx`). Merging the two later is a follow-up, not part of this lane.
  - F1 builds the tab bar and rail per the ruling. L4 only sets the Practice `to` (Task 11).
- **L3:** the homework row relies on `PracticeSet` handling a non-practice assignment on submit (Needs user decision 4). L3 also coordinates any `practiceData.ts` edit with L4.
- **L10:** must mount `/student/flashcards` (the Flashcards tile links there). Until it does, the Task 12 happy path doesn't click that tile.
- **L1:** Home's practice links keep working unchanged (K3).

## Self-review

- **Spec coverage (Wave 1 item 4):**

  | Spec item | Task |
  |---|---|
  | tinted tiles | 5, 8 |
  | homework row only when set | 5, 8 |
  | Binny's line | 5, 8 |
  | win marks back | 5, 8 |
  | recent runs with resume | 1, 3, 5, 8 |
  | builder sheet and its four states | 6, 9 |
  | past papers and paper sheet | 2, 3, 7, 10 |
  | `GET /student/practice/runs` | 1, 3 |
  | availability check reused (`/preview`, unchanged) | 9 |
  | tab root wiring | 11 |
  | first-run and sparse states | 5, 8 |
  | loading and error | 5, 8, 9, 10 |
  | desktop CDK | 8 |
  | e2e | 12 |
  | fidelity and polish | 13 |
  | keep-list and deletion | 14 |
  | PR | 15 |

- **Migration:** none. Practice sets already use `quizkind = practice`, and durations come from the existing `syllabus_papers` table.
- **Type names are consistent across tasks:**
  - `PracticeRun`, `PastPaper`, `HubInput`, `HubView`, `TileView`
  - `BuilderDraft`, `builderView`, `paperSheetView`
  - `practiceHubKeys.runsAll`, `SetBuilderSheet` props, `usePracticeHubData().builderSubjects`
