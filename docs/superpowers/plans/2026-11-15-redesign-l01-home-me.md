# L1 · Student Home hub and Me Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the student Overview and Profile screens with the approved Home hub (H4/H6 "calm stage") and the "Me · alive" screen, backed by one new endpoint, `GET /api/student/home`.

**Architecture:** The backend adds a pure builder module (`lemely/web/services/student_home.py`) that turns data from the existing services into one DTO, plus one read-only repo query for teacher replies, plus one thin router. The frontend adds typed API and hook files, then a pure view model (`home/model.ts`, `home/me/meModel.ts`) that holds every decision: which moment is on stage, Binny's mood, motion and line, which rows show, and every link target. The screens are thin compositions of F1 kit parts. `Overview.tsx` and `Profile.tsx` stay as the route entry files, each reduced to a query plus a `QueryState` and a screen component from `portals/student/home/`.

**Tech Stack:** FastAPI, Pydantic v2, SQLAlchemy 2, pytest; React 19, react-router 7, TanStack Query 5, Tailwind 4, Vitest (node env, no jsdom), Playwright.

**Mocks (source of truth):** `.impeccable/mocks/student-r2/home4.html`, built by `h4.js` then `h5.js` then `h6.js` (the final layer), with helpers in `t.js`, `h.js` (BIN), `st.js` and styles in `t.css`. `states-r1/` holds no Home or Me frames (checked: its frames are RQ, SR, UP, E, O, P, Q, S, X only), so the first-run and sparse states below follow the empty/sparse rules and the nearest approved pattern (`states-r1/s.js` SR1 "starting line" and RQ3 walkthrough). See "Needs user decision" item 1.

## Global Constraints

Inherits master plan Global Constraints (`docs/superpowers/plans/2026-11-15-redesign-00-master.md`). Lane-specific additions:

- Owned files: `web/src/portals/student/screens/Overview.tsx`, `web/src/portals/student/screens/Profile.tsx`, everything under `web/src/portals/student/home/`, plus the new files this plan creates. Shared-file edits are limited to: one `include_router` line plus import in `lemely/web/app.py`; one `EXPECTED` row in `tests/test_authz_matrix_complete.py`; the two route `handle.title` strings in `web/src/portals/student/index.tsx`; the lint-test path lists named in Task 11.
- No migration. Nothing in this lane writes to the database.
- Copy rules enforced by `web/scripts/check_copy.mjs`: no em dash used as punctuation, and no `!` at the end of a sentence in any string or JSX text under `web/src/`. The mock's exclamation marks become full stops (listed as small fixes in the PR).
- Binny appears once per screen: the stage Binny on Home, the peek Binny on Me. Binny's mood, motion and line come only from the view model.
- Gold (`tertiary`) only for earned things: completed ring parts, done week days, a lit streak pill, earned badges, the level ring and badge.
- Numbers use `font-mono` (`wn` marks, stats, level badge, XP). Grade letters use `font-display` (Bricolage) at 28px and above.
- The `PortalShell` top bar already renders the notification bell (`web/src/components/shell/ShellTopBar.tsx:127-132`). Home does not render a second bell (see "Needs user decision" item 3).
- Every link is a real `<Link to>` (no `button onClick={navigate}`), with a 44px hit area.
- `prefers-reduced-motion`: no press scale, no stage crossfade, Binny motion `none` (F1 handles Binny).
- Breakpoints follow the shell: phone `<768`, tablet `md` 768–1279, desktop `xl` ≥1280.
- Python: `ruff` rules `ANN` (annotate every function, tests included), `D` (docstring style when present), `TCH`, `S`. Line length 100.
- Commands run from the lane worktree root. Python: `source /home/sico/Code/Lemely/.venv/bin/activate` and prefix pytest with `PYTHONPATH="$(git rev-parse --show-toplevel)"` (all worktrees share one venv).

---

## File map

**Backend (create)**
- `lemely/web/schemas_student_home.py`: every DTO for `GET /api/student/home`.
- `lemely/web/services/student_home.py`: pure builders, no DB, no clock.
- `lemely/db/student_home_repo.py`: `StudentHomeReads.recent_teacher_replies`, the one new query.
- `lemely/web/routers/student_home.py`: the route and its `get_student_home_reads` dependency.
- `tests/test_student_home_service.py`, `tests/test_student_home_repo.py`, `tests/test_student_home_route.py`.

**Backend (modify)**
- `lemely/web/app.py`: import `student_home`, add `app.include_router(student_home.router)`.
- `tests/test_authz_matrix_complete.py`: add `("GET", "/api/student/home"): STUDENT,`.

**Frontend (create)**
- `web/src/lib/studentHomeTypes.ts`: wire types.
- `web/src/lib/studentHomeApi.ts`: `fetchStudentHome`.
- `web/src/lib/hooks/useStudentHomeApi.ts`: `STUDENT_HOME_KEY`, `homeRefetchInterval`, `useStudentHome`.
- `web/src/portals/student/home/routes.ts`: every door's destination.
- `web/src/portals/student/home/dismiss.ts`: the "Not now" per-day memory.
- `web/src/portals/student/home/model.ts` (replaces the old file): the Home view model.
- `web/src/portals/student/home/me/meModel.ts`: the Me view model, plus the four helpers moved out of `Profile.tsx`.
- Home components: `home/HomeScreen.tsx`, `home/HomeTopRow.tsx`, `home/HomeStage.tsx`, `home/TodayBlock.tsx`, `home/WeekStrip.tsx`, `home/GradeFloor.tsx`, `home/LastPaperRow.tsx`, `home/WinBack.tsx`, `home/MomentRows.tsx`, `home/HomeBand.tsx`, `home/HomeFirstRun.tsx`, `home/HomeSkeleton.tsx`, `home/gradeClass.ts`.
- Me components: `home/me/MeScreen.tsx`, `home/me/MeHero.tsx`, `home/me/StreakStrip.tsx`, `home/me/StatsRow.tsx`, `home/me/PeopleDoors.tsx`, `home/me/BadgeRow.tsx`, `home/me/YourSubjects.tsx`, `home/me/RecentActivity.tsx`, `home/me/AccountRows.tsx`, `home/me/ProgressSheet.tsx`, `home/me/BadgesSheet.tsx`, `home/me/MeSkeleton.tsx`.
- Tests: `web/tests/unit/studentHomeApi.test.ts`, `web/tests/unit/studentHomeRoutes.test.ts`, `web/tests/unit/studentHomeDismiss.test.ts`, `web/tests/unit/studentHomeModel.test.ts` (rewritten), `web/tests/unit/studentMeModel.test.ts`, `web/tests/unit/studentHomeFixture.ts` (shared fixture builder), `web/e2e/student-home.spec.ts`.

**Frontend (modify)**
- `web/src/portals/student/screens/Overview.tsx`, `Profile.tsx`: reduced to entry files.
- `web/src/portals/student/index.tsx`: `handle.title` "Dashboard" → "Home", "Your profile" → "Me".
- `web/tests/unit/xpProfile.test.ts`: import path moves to `meModel`.
- `web/tests/unit/streakChip.test.ts`, `sectionHead.test.ts`, `rtlSafety.test.ts`, `utilityExistence.test.ts`: path lists and the Overview assertions (Task 8 and Task 11).
- `web/e2e/student-journey.spec.ts`, `web/e2e/engagement.spec.ts`, `web/e2e/screenshots.spec.ts`: Overview text assertions (Task 11).

**Delete (Task 13)**
- `web/dev-previews/student-home/` (all nine files), `web/dev-previews/student-home.html`, `student-home-a.html`, `student-home-b.html`, `student-home-c.html`, their four entries in `web/vite.preview.config.ts:55-58`, and `web/tests/unit/studentHomeFixtures.test.ts`. These only exercise the old `home/model.ts`, which this lane replaces.

---

## Keep-list

Every item is ticked off in Task 13 and copied into the PR body.

### `web/src/portals/student/screens/Overview.tsx`

| # | Live feature (file:line) | Where it lives after L1 |
|---|---|---|
| O1 | Greeting by the reader's local hour, name falls back to "there" (`Overview.tsx:427-434`) | `shortGreeting(hour)` + `firstName()` in `home/model.ts`; desktop `h1` "Morning, Mariam"; sr-only `h1` on phone/tablet |
| O2 | First-run getting-started view when no papers, CTA to `/student/correct` (`:460-491`) | `HomeFirstRun` walkthrough + stage "Scan a paper" (Task 9) |
| O3 | Subject rows link to `/student/subject/:code` with predicted grade (`:137-241`) | Grade floor doors (phone/tablet/desktop) + desktop "Recent papers"; the Me "Your subjects" rows |
| O4 | Subject row qualification identifier, pct, paper count, trend arrow with spoken label (`:97-135`, `:207-225`) | Moved to the Subject screen (L2) per the approved mock; floor shows grade and "N pts to X". Listed in "Needs user decision" item 4 |
| O5 | Momentum chart with "One paper down" empty state and "Correct another paper" CTA (`:257-337`) | Trend moves to Subject (L2 trend line). The sparse nudge "One more paper draws your trend" on Home keeps the CTA (Task 9). Item 4 |
| O6 | Weakest threads by accuracy with empty state (`:539-561`) | "Win marks back" rows (+N marks) with "Nothing to win back yet" sparse line |
| O7 | Join-your-teacher's-class prompt, only after the classes read succeeds with zero (`:353-370`) | Moment row "Join your teacher's class" when `classCount === 0` (server-side count, so no flash while pending) |
| O8 | Streak and XP chip linking to `/student/profile` (`:380-382`, `:513-526`) | Streak pill in the top row links to Me; XP shows on Me |
| O9 | Layout-matching skeleton (`:401-410`) | `HomeSkeleton` with `GhostRows` |
| O10 | Error "Couldn't load your overview" with `studentLoadFailureMessage` (`:411-420`) | Error heading "Couldn't load your home", same body helper, Try again |
| O11 | Kicker with subject and paper counts (`:505-510`) | Me stat "papers marked"; floor shows each subject |
| O12 | Uses `QueryState` (`web/tests/unit/queryStateGate.test.ts:311-316`) | `Overview.tsx` keeps `useStudentHome` + `QueryState` |
| O13 | No own pull-to-refresh, the shell owns it (`web/tests/unit/shellPullToRefresh.test.ts:61-66`) | Unchanged |
| O14 | No pastel subject tones (`web/tests/unit/subjectGlyph.test.ts:72-77`) | Unchanged, Home uses grade colours only |

### `web/src/portals/student/screens/Profile.tsx`

| # | Live feature (file:line) | Where it lives after L1 |
|---|---|---|
| P1 | Name: `displayName` → email local part → "Your profile" (`Profile.tsx:397-398`) | `displayName()` in `meModel.ts` (fallback "You") |
| P2 | Level and total XP with `Celebrate` + `CountUp` on growth only (`:158-204`) | Level badge on the hero ring (`Celebrate` on `level`); total XP in `ProgressSheet` with `Celebrate` |
| P3 | Progress to next level and "N XP to level N+1" (`:194-200`) | `KeyRing` value from `levelProgress`, line "Level 7 · 260 XP to level 8" |
| P4 | Streak current, longest, freezes chip, last-active sentence, `MilestoneSticker` (`:206-258`) | Streak strip line "9-day streak · best 14"; `ProgressSheet` holds freezes, last active and the sticker |
| P5 | This week by source with fallback labels (`:132-147`, `:317-362`) | `ProgressSheet` "This week" rows using `sourceLabel` |
| P6 | Four-week XP bar chart with tooltips and copy (`:281-315`) | `ProgressSheet` "Last four weeks" `BarChart` |
| P7 | Error "Your XP could not be loaded" with the reassurance body (`:434-438`) | Same copy in `MeScreen`'s `QueryState` |
| P8 | Layout-matching skeleton (`:372-383`) | `MeSkeleton` |
| P9 | Leaderboards button → `/student/board` (`:473-479`) | Standings people door |
| P10 | Your devices → `/student/settings/devices` with overlay state (`:480-486`) | "Profile and settings" row → `/student/settings` with `state: overlayState` (devices is a tab in that overlay) |
| P11 | Exported helpers `calendarDays`, `fillCalendar`, `levelProgress`, `sourceLabel` (`:87-147`, tested in `web/tests/unit/xpProfile.test.ts`) | Moved verbatim to `home/me/meModel.ts`; test import updated |
| P12 | The level curve is never computed client-side (`:38-41`) | Unchanged: `levelProgress` reads `levelStartXp`/`nextLevelXp` |
| P13 | The streak is never used as leverage, the freeze is offered kindly (`:43-47`) | The streak-at-risk moment is suppressed when a freeze is available (server rule) and its copy has no red and no warning tone. Item 5 |

### `web/src/portals/student/home/model.ts` (old)

| # | Live behaviour (file:line) | Where it lives after L1 |
|---|---|---|
| M1 | Next action priority: marking > unseen result > due session > first paper > weakest topic > correct another (`model.ts:130-141`) | Stage priority: marking > result/tough > teacher reply > streak at risk > goal done > back after a break > today's session > morning (weakest topic) > scan next / first run |
| M2 | Binny mood from marking, grade improved, paper marked (24h), streak kept (`:163-176`) | `stageVm` mood per moment; result window is 48h server-side |
| M3 | 7-day streak strip (`:178-186`) | Home week strip (Mon–Sun) and Me 14-day strip |
| M4 | `preferClosestExam` ordering option (`:82-85`) | Dropped: it was only a dev-preview variant switch (B). The exam now drives the countdown pill and Binny's line |

### Endpoints

`GET /api/student/overview` is **kept unchanged**: the student shell's subject tree still reads it (`web/src/portals/student/shell.tsx:113`). L1 adds `GET /api/student/home` and removes nothing on the backend.

---

## Frame-to-state table

Frames rendered by `home4.html` after `h6.js` (`paint6` writes `P5`, `P5b`, `D5`; `ME2`, `DME`; `ME` is the superseded "Me (before)").

| Mock frame | Real component state | Breakpoint | Trigger |
|---|---|---|---|
| `P5` morning (`M6.morning`) | `HomeScreen`, stage kind `morning`, also rows teacher reply + homework | phone | no higher moment; `winBack[0]` exists |
| `P5` paper (`M6.paper`) | stage `result`, also row "See your full result" | phone | `moments` has `result` (paper ≤48h old, grade ≥ C and not lower than previous) |
| `P5` tough (`M6.tough`) | stage `tough`, also row result with grade D tile | phone | `moments` has `tough` (grade D–U, or dropped from previous) |
| `P5` streak (`M6.streak`) | stage `streakAtRisk` | phone | `moments` has `streakAtRisk` (server rule in Task 2) |
| `P5` done (`M6.done`) | stage `goalDone`, ring all gold, streak pill lit | phone | all three goals done |
| `P5` back (`M6.back`) | stage `backAfterBreak`, streak pill "New streak", win rows 1 | phone | `moments` has `backAfterBreak` |
| `P5` marking (`M6.marking`) | stage `marking`, not dismissible | phone | `moments` has `marking` |
| `P5b` | same states, second moment | phone | n/a (mock comparison frame) |
| `D5` (`H6D`) | `HomeScreen` three columns: stage + also-under; Today (no week) + floor + win; band: This week + Recent papers + From your class | desktop `xl` | any moment |
| (none) | two columns + band row of three | tablet `md` | any moment (derived from D5, see item 1) |
| `ME2` (`ME6`) | `MeScreen` single column: hero, streak, stats, people, badges, subjects, activity, rows | phone | loaded |
| `DME` (`MED6`) | `MeScreen` two columns: hero, streak, stats, badges, subjects / people, activity, rows; page header "Me" | tablet `md` and desktop `xl` | loaded |
| `ME` | not built (superseded by `ME2`) | n/a | n/a |
| (none, rule) | `HomeFirstRun`: stage "Let's mark your first paper", walkthrough of 3 steps, ghost floor | all | `floor` and `recentPapers` empty |
| (none, rule) | sparse: one paper; nudge row "One more paper draws your trend"; win empty line | all | `stats.papersMarked === 1` / `winBack` empty |
| (none, rule) | `HomeSkeleton` / `MeSkeleton` ghost rows | all | query pending |
| (none, rule) | `QueryState` error with Try again | all | query error |
| (none, rule) | offline: same error view with `OfflineState` copy "You're offline" when `useOnlineStatus()` is false | all | fetch failed while offline |
| (none) | `ProgressSheet` (adaptive sheet) | all | tap streak strip or "Progress" door |
| (none) | `BadgesSheet` (adaptive sheet) | all | tap "All badges" |

---

## Interactions and motion

Values from `t.css` (`/* polish */` and `/* H6 */` blocks) and `h6.js`.

| Element | Interaction / animation | Exact values | Tailwind | Reduced motion |
|---|---|---|---|---|
| Pills, floor letters, today chips, section links | press scale | `transform: scale(.97)` on `:active`, transition `transform .15s cubic-bezier(.2,.8,.2,1)` | `motion-safe:active:scale-[.97] transition-transform duration-[var(--dur-fast)] ease-out` | no scale |
| Hairline rows (win, moment, recent, account), stats, people doors | press scale + hover wash | `scale(.985)`; hover `linear-gradient(90deg,transparent,oklch(.965 .012 240) 12%,… 88%,transparent)`; `background-color .15s` | `motion-safe:active:scale-[.985] hover:bg-[linear-gradient(90deg,transparent,var(--md-surface-container-low)_12%,var(--md-surface-container-low)_88%,transparent)]` | no scale, wash stays |
| Binny (stage, peek) | mood motion | happy: hop 1.1s `cubic-bezier(.3,.7,.4,1)` infinite; others: bob 3.2s ease-in-out; sad sway 4s; thinking look 3s; wink tilt 2.4s; blink 4.6s; ears 5s | F1 `Binny motion` (`hop` for happy, `idle` otherwise) | F1 forces `none` |
| Stage swap on "Not now" | crossfade (small addition, listed in PR) | 200ms `--dur-base`, opacity 0→1, `translateY(6px)`→0, `--ease-out` | `motion-safe:animate-[stage-in_var(--dur-base)_var(--ease-out)]` defined in `HomeStage.tsx` via a `<style>` keyframe `stage-in` | instant swap |
| Big button | static shadow | `box-shadow: 0 14px 24px -16px oklch(.3 .07 242/.7)`, radius 18px, min-height 54, font 16/700 | `shadow-[0_14px_24px_-16px_color-mix(in_oklch,var(--md-shadow)_70%,transparent)] rounded-inner min-h-[54px]` | same |
| Tab fade | gradient above tab bar | `.tabfade` 28px | shell owns it, not built here | n/a |
| Level ring, today ring | static fills | ring segments `stroke-dasharray 23 59`, offset `-i*27.2`, 4.5 stroke, 32px | F1 `GoldRing` / `KeyRing` | static |
| Streak strip `now` cell | static ring | `box-shadow: 0 0 0 2px oklch(.6 .13 60)` | `ring-2 ring-on-tertiary-container/60` | same |
| Level badge, XP total | `Celebrate` on growth while watching (live P2) | existing `components/ui/celebration.tsx` | as is | the component's own reduced-motion branch |

---

## Mock class → token map

| Mock class / var | Value | Token / Tailwind |
|---|---|---|
| `--p` | `#042f4f` | `text-primary`, `bg-primary` |
| `--pc` | `oklch(.92 .035 235)` | `bg-primary-container` |
| `--v` | `oklch(.47 .02 240)` | `text-on-surface-variant` |
| `--ink` | `#130e10` | `text-on-surface` |
| `--ov` | `oklch(.92 .01 240)` | `border-outline-variant` |
| `--o` | `oklch(.87 .012 240)` | `border-outline`, `ring-outline` |
| `--s` | surface | `bg-surface` |
| `--l` / `oklch(1 0 0/.7)` | white 70% | `bg-surface-container-lowest/70` |
| `--gold` | `oklch(.8 .13 80)` | `bg-tertiary`, `text-tertiary` |
| `.pill4.lit` | `oklch(.95 .06 82)` / `oklch(.48 .12 60)` | `bg-tertiary-container text-on-tertiary-container` |
| `.tl3 a.ok` | `oklch(.96 .045 85)` | `bg-tertiary-container/70 text-on-tertiary-container` |
| `.bd.on svg` | `oklch(.94 .07 85)` / `oklch(.5 .12 65)` | `bg-tertiary-container text-on-tertiary-container` |
| `.bd svg` (off) | `oklch(.94 .008 240)` / `oklch(.7 .01 240)` | `bg-surface-container-high text-outline` |
| `.sd i` / `.on` / `.now` | `oklch(.92 .012 240)` / `oklch(.85 .11 82)` / gold | `bg-surface-container-highest` / `bg-tertiary/60` / `bg-tertiary` |
| `.wd6 i` ring | `oklch(.86 .012 240)` | `ring-2 ring-inset ring-outline` |
| `--gA*`…`--gU` | grade ramp | `text-grade-a-star` … `text-grade-u` (`home/gradeClass.ts`) |
| `.h4pad` gradient | `oklch(.965 .02 235)` → `--s` at 46% | `bg-[linear-gradient(180deg,color-mix(in_oklch,var(--md-primary-container)_45%,var(--md-surface))_0%,var(--md-surface)_46%)]` |
| `.spot` | radial `oklch(.8 .05 235/.45)` | `bg-[radial-gradient(closest-side,color-mix(in_oklch,var(--md-primary-container)_80%,transparent),transparent)]` |
| Bricolage | display | `font-display` |
| Schibsted | body | `font-sans` |
| JetBrains Mono | numbers | `font-mono` |
| `--ease` | `cubic-bezier(.2,.8,.2,1)` | `ease-out` (theme `--ease-out`) |
| `.15s` | | `duration-[var(--dur-fast)]` |

Sizes are copied as arbitrary values where no rung matches: `line4` 20px/1.38 700 (`text-[20px] leading-[1.38] font-bold`), desktop 22px; `floor b` 44px/1 800; `hlink.h` 18px 800; `wn` mono 17px 700; `rp>b` 28px; `stats3 b` 30px; `mhero h2` 32px (desktop 40px); body rows 15px/13px; badge label 12px. No text under 12px.

---

## Task 1: Home DTOs and the history-derived builders

**Files:**
- Create: `lemely/web/schemas_student_home.py`
- Create: `lemely/web/services/student_home.py`
- Test: `tests/test_student_home_service.py`

**Interfaces:**
- Consumes: `lemely.core.history.PaperRecord`, `is_grade_bearing`; `lemely.web.routers.student._grade_for(percentage: float, boundaries: dict[str, float]) -> str`; `lemely.io.det.profiles.get_profile(code).name`.
- Produces (later tasks import these exact names):
  - DTOs: `MarkingMomentDTO`, `PaperMomentDTO`, `TeacherReplyDTO`, `TeacherReplyMomentDTO`, `StreakMomentDTO`, `BackMomentDTO`, `MomentDTO`, `TodayDTO`, `PlanSessionDTO`, `WeekDayDTO`, `StreakDTO`, `FloorSubjectDTO`, `WinBackTopicDTO`, `RecentPaperDTO`, `HomeworkDTO`, `BestGradeDTO`, `HomeStatsDTO`, `ActivityDTO`, `StudentHomeDTO`.
  - Functions: `grade_rank(grade: str) -> int`, `subject_name(code: str) -> str`, `question_label(question_id: str) -> str`, `recorded_at(record: PaperRecord) -> datetime`, `indexed_papers(records) -> list[tuple[int, PaperRecord]]`, `next_boundary(pct: float, boundaries: dict[str, float]) -> tuple[str | None, int | None]`, `build_floor(records, boundaries_for) -> list[FloorSubjectDTO]`, `build_win_back(records, *, limit=3) -> list[WinBackTopicDTO]`, `build_recent_papers(records, *, limit=3) -> list[RecentPaperDTO]`, `focus_question(record, *, easiest: bool) -> str | None`, `paper_moment(records, now: datetime) -> PaperMomentDTO | None`, `build_stats(records) -> HomeStatsDTO`, `attempt_index(records) -> dict[str, int]`, `build_activity(records, replies, *, limit=6) -> list[ActivityDTO]`.
  - Constants: `GRADE_ORDER`, `TOUGH_GRADES`, `RESULT_WINDOW = timedelta(hours=48)`, `REPLY_WINDOW = timedelta(days=7)`.

- [ ] **Step 1: Write the DTO module**

```python
"""DTOs for ``GET /api/student/home`` (redesign lane L1).

camelCase on the wire, like every other student DTO. Every field is data-backed
by an existing service; see :mod:`lemely.web.services.student_home` for which.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import Field

from lemely.web.schemas import ApiModel


class TeacherReplyDTO(ApiModel):
    """A teacher resolved a review item on one of the caller's answers."""

    reviewId: str
    teacherName: str
    questionId: str
    subjectCode: str | None
    subjectName: str | None
    paperNumber: int | None
    marksAdded: int
    paperId: str | None
    resolvedAt: datetime


class MarkingMomentDTO(ApiModel):
    kind: Literal["marking"] = "marking"
    paperId: str
    filename: str | None
    startedAt: datetime | None
    stale: bool
    questionsDone: int | None = None
    questionsTotal: int | None = None


class PaperMomentDTO(ApiModel):
    kind: Literal["result", "tough"]
    paperId: str
    subjectCode: str
    subjectName: str
    paperNumber: int
    awarded: int
    maximum: int
    grade: str
    previousGrade: str | None
    focusQuestion: str | None
    recordedAt: datetime


class TeacherReplyMomentDTO(ApiModel):
    kind: Literal["teacherReply"] = "teacherReply"
    reply: TeacherReplyDTO


class StreakMomentDTO(ApiModel):
    kind: Literal["streakAtRisk", "goalDone"]
    streakDays: int


class BackMomentDTO(ApiModel):
    kind: Literal["backAfterBreak"] = "backAfterBreak"
    daysAway: int


MomentDTO = Annotated[
    MarkingMomentDTO
    | PaperMomentDTO
    | TeacherReplyMomentDTO
    | StreakMomentDTO
    | BackMomentDTO,
    Field(discriminator="kind"),
]


class TodayDTO(ApiModel):
    practice: bool
    flashcards: bool
    paperThisWeek: bool


class PlanSessionDTO(ApiModel):
    sessionId: str
    subjectCode: str
    topic: str
    minutes: int
    done: bool


class WeekDayDTO(ApiModel):
    day: date
    label: str | None
    done: bool
    isToday: bool


class StreakDTO(ApiModel):
    current: int
    longest: int
    lastActiveOn: date | None
    freezesAvailable: int


class FloorSubjectDTO(ApiModel):
    code: str
    name: str
    grade: str
    previousGrade: str | None
    nextGrade: str | None
    pointsToNext: int | None
    papers: int


class WinBackTopicDTO(ApiModel):
    topic: str
    subjectCode: str
    subjectName: str
    marks: int


class RecentPaperDTO(ApiModel):
    paperId: str
    subjectCode: str
    subjectName: str
    paperNumber: int
    awarded: int
    maximum: int
    grade: str
    recordedAt: datetime


class HomeworkDTO(ApiModel):
    assignmentId: str
    title: str
    subjectCode: str
    teacherName: str
    dueAt: datetime | None
    questionCount: int
    isOverdue: bool


class BestGradeDTO(ApiModel):
    grade: str
    subjectCode: str


class HomeStatsDTO(ApiModel):
    papersMarked: int
    marksWonBack: int
    bestGrade: BestGradeDTO | None


class ActivityDTO(ApiModel):
    kind: Literal["paper", "practice", "teacher"]
    title: str
    sub: str
    at: datetime


class StudentHomeDTO(ApiModel):
    """Payload for ``GET /api/student/home``."""

    studentName: str
    localDate: date
    localHour: int
    moments: list[MomentDTO]
    goals: TodayDTO
    todaySessions: list[PlanSessionDTO]
    week: list[WeekDayDTO]
    streak: StreakDTO
    nextExamOn: date | None
    floor: list[FloorSubjectDTO]
    winBack: list[WinBackTopicDTO]
    recentPapers: list[RecentPaperDTO]
    lastPaperAt: datetime | None
    teacherReplies: list[TeacherReplyDTO]
    homework: list[HomeworkDTO]
    classCount: int
    stats: HomeStatsDTO
    activity: list[ActivityDTO]
```

- [ ] **Step 2: Write the failing tests for the history-derived builders**

```python
"""Unit tests for the pure builders behind ``GET /api/student/home``."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from lemely.core.history import PaperRecord
from lemely.core.schemas import ExamMetadata, WeakArea
from lemely.io.det.profiles import get_profile
from lemely.web.schemas_student_home import TeacherReplyDTO
from lemely.web.services.student_home import (
    build_activity,
    build_floor,
    build_recent_papers,
    build_stats,
    build_win_back,
    focus_question,
    next_boundary,
    paper_moment,
    question_label,
)

NOW = datetime(2026, 11, 12, 15, 0, tzinfo=UTC)
BOUNDARIES = {"A*": 90.0, "A": 80.0, "B": 70.0, "C": 60.0, "D": 50.0, "E": 40.0}


def _boundaries(_metadata: ExamMetadata) -> dict[str, float]:
    return dict(BOUNDARIES)


def _weak(topic: str, lost: int, maximum: int, qid: str) -> WeakArea:
    return WeakArea(
        topic=topic,
        lost_marks=lost,
        maximum_marks=maximum,
        accuracy=round(1.0 - lost / maximum, 4),
        question_ids=[qid],
    )


def _paper(
    *,
    code: str = "0580",
    paper: int = 4,
    awarded: int = 61,
    maximum: int = 80,
    grade: str = "B",
    at: datetime = NOW - timedelta(hours=2),
    weak: list[WeakArea] | None = None,
    origin: str = "past_paper",
    attempt_id: str | None = None,
) -> PaperRecord:
    return PaperRecord(
        student_id="s",
        metadata=ExamMetadata(
            subject_code=code,
            paper_number=paper,
            paper_variant=2,
            session_month="May/June",
            session_year=2024,
        ),
        awarded_marks=awarded,
        maximum_marks=maximum,
        percentage=round(awarded / maximum * 100, 2),
        grade=grade,
        weak_areas=weak or [],
        recorded_at=at.isoformat(),
        origin=origin,  # type: ignore[arg-type]
        attempt_id=attempt_id,
    )


def test_next_boundary_returns_the_next_grade_and_rounded_up_points() -> None:
    assert next_boundary(76, BOUNDARIES) == ("A", 4)
    assert next_boundary(79.2, BOUNDARIES) == ("A", 1)
    assert next_boundary(95, BOUNDARIES) == (None, None)


def test_floor_grades_each_subject_from_its_weighted_mean() -> None:
    records = [
        _paper(code="0580", awarded=48, maximum=80, grade="C", at=NOW - timedelta(days=20)),
        _paper(code="0580", awarded=61, maximum=80, grade="B", at=NOW - timedelta(days=2)),
        _paper(code="0625", awarded=27, maximum=40, grade="C", at=NOW - timedelta(days=9)),
    ]
    floor = build_floor(records, _boundaries)
    assert [f.code for f in floor] == ["0580", "0625"]
    maths = floor[0]
    # (48 + 61) / 160 = 68% -> C, next B at 70 -> 2 points.
    assert (maths.grade, maths.nextGrade, maths.pointsToNext, maths.papers) == ("C", "B", 2, 2)
    # The grade before the latest paper: 48/80 = 60% -> C.
    assert maths.previousGrade == "C"
    assert maths.name == (get_profile("0580").name or "0580")
    physics = floor[1]
    assert physics.previousGrade is None


def test_floor_ignores_quiz_records() -> None:
    records = [_paper(origin="quiz", awarded=10, maximum=10, grade="A*")]
    assert build_floor(records, _boundaries) == []


def test_win_back_ranks_topics_from_each_subjects_latest_paper() -> None:
    records = [
        _paper(code="0580", at=NOW - timedelta(days=30), weak=[_weak("Old topic", 20, 30, "1")]),
        _paper(
            code="0580",
            at=NOW - timedelta(days=2),
            weak=[_weak("Vectors", 9, 12, "8"), _weak("Algebra", 0, 10, "2")],
        ),
        _paper(code="0625", at=NOW - timedelta(days=5), weak=[_weak("Waves", 7, 10, "3")]),
        _paper(code="0606", at=NOW - timedelta(days=6), weak=[_weak("Inequalities", 6, 9, "5")]),
        _paper(code="0606", at=NOW - timedelta(days=6), origin="quiz", weak=[_weak("Q", 50, 60, "9")]),
    ]
    rows = build_win_back(records)
    assert [(r.topic, r.subjectCode, r.marks) for r in rows] == [
        ("Vectors", "0580", 9),
        ("Waves", "0625", 7),
        ("Inequalities", "0606", 6),
    ]


def test_recent_papers_are_newest_first_with_history_indices_as_ids() -> None:
    records = [
        _paper(code="0580", at=NOW - timedelta(days=9)),
        _paper(origin="quiz", at=NOW - timedelta(days=8)),
        _paper(code="0625", at=NOW - timedelta(days=1)),
    ]
    rows = build_recent_papers(records)
    assert [(r.paperId, r.subjectCode) for r in rows] == [("2", "0625"), ("0", "0580")]


def test_focus_question_picks_most_lost_or_easiest_win() -> None:
    record = _paper(weak=[_weak("Vectors", 9, 12, "8"), _weak("Units", 1, 10, "3")])
    assert focus_question(record, easiest=False) == "8"
    assert focus_question(record, easiest=True) == "3"
    assert focus_question(_paper(weak=[]), easiest=False) is None


def test_paper_moment_is_a_result_when_recent_and_not_a_drop() -> None:
    records = [
        _paper(grade="C", at=NOW - timedelta(days=20)),
        _paper(grade="B", awarded=61, weak=[_weak("Vectors", 9, 12, "8")]),
    ]
    moment = paper_moment(records, NOW)
    assert moment is not None
    assert (moment.kind, moment.grade, moment.previousGrade, moment.focusQuestion) == (
        "result",
        "B",
        "C",
        "8",
    )
    assert moment.paperId == "1"


def test_paper_moment_is_tough_for_a_low_grade_or_a_drop() -> None:
    low = paper_moment([_paper(grade="D", awarded=42)], NOW)
    assert low is not None
    assert low.kind == "tough"
    dropped = paper_moment(
        [_paper(grade="A", at=NOW - timedelta(days=9)), _paper(grade="B")], NOW
    )
    assert dropped is not None
    assert dropped.kind == "tough"


def test_paper_moment_expires_after_48_hours() -> None:
    assert paper_moment([_paper(at=NOW - timedelta(hours=49))], NOW) is None
    assert paper_moment([], NOW) is None


def test_stats_count_papers_and_practice_marks() -> None:
    records = [
        _paper(grade="B"),
        _paper(code="0606", grade="A"),
        _paper(origin="quiz", awarded=7, maximum=9),
        _paper(origin="quiz", awarded=5, maximum=10),
    ]
    stats = build_stats(records)
    assert stats.papersMarked == 2
    assert stats.marksWonBack == 12
    assert stats.bestGrade is not None
    assert (stats.bestGrade.grade, stats.bestGrade.subjectCode) == ("A", "0606")
    assert build_stats([]).bestGrade is None


def test_activity_merges_papers_practice_and_teacher_replies_newest_first() -> None:
    reply = TeacherReplyDTO(
        reviewId="r1",
        teacherName="Ms. Hanna",
        questionId="7",
        subjectCode="0580",
        subjectName="Mathematics",
        paperNumber=4,
        marksAdded=1,
        paperId="0",
        resolvedAt=NOW - timedelta(hours=1),
    )
    records = [
        _paper(at=NOW - timedelta(days=2)),
        _paper(origin="quiz", awarded=8, maximum=10, at=NOW - timedelta(hours=3)),
    ]
    rows = build_activity(records, [reply])
    assert [r.kind for r in rows] == ["teacher", "practice", "paper"]
    assert rows[0].title == "Ms. Hanna checked Q7"
    assert rows[0].sub == "Mathematics · +1 mark"
    assert rows[1].sub.endswith("8 of 10")


def test_question_label_adds_q_once() -> None:
    assert question_label("7") == "Q7"
    assert question_label("Q4b") == "Q4b"
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `PYTHONPATH="$(git rev-parse --show-toplevel)" pytest tests/test_student_home_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'lemely.web.services.student_home'`.

- [ ] **Step 4: Write the builders**

```python
"""Pure builders for ``GET /api/student/home`` (redesign lane L1).

Every function takes plain values and returns DTOs: no database, no clock, no
network. The router gathers inputs from the existing services and hands them
over, so each rule here is a unit test. Grades reuse the Overview's own rule
(:func:`lemely.web.routers.student._grade_for`, mark-weighted mean against the
latest paper's boundaries) so Home, Overview and Subject never disagree.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from lemely.core.history import is_grade_bearing
from lemely.io.det.profiles import get_profile
from lemely.web.routers.student import _grade_for
from lemely.web.schemas_student_home import (
    ActivityDTO,
    BestGradeDTO,
    FloorSubjectDTO,
    HomeStatsDTO,
    PaperMomentDTO,
    RecentPaperDTO,
    TeacherReplyDTO,
    WinBackTopicDTO,
)

if TYPE_CHECKING:
    from lemely.core.history import PaperRecord
    from lemely.core.schemas import ExamMetadata

BoundariesFor = Callable[["ExamMetadata"], dict[str, float]]

GRADE_ORDER: tuple[str, ...] = ("U", "G", "F", "E", "D", "C", "B", "A", "A*")
TOUGH_GRADES = frozenset({"D", "E", "F", "G", "U"})
RESULT_WINDOW = timedelta(hours=48)
REPLY_WINDOW = timedelta(days=7)


def grade_rank(grade: str) -> int:
    """Position on the grade ladder, ``-1`` for anything off it."""
    return GRADE_ORDER.index(grade) if grade in GRADE_ORDER else -1


def subject_name(code: str) -> str:
    """The subject's human name, falling back to its code (never invented)."""
    return get_profile(code).name or code


def question_label(question_id: str) -> str:
    """``"7"`` -> ``"Q7"``; an id that already starts with Q is left alone."""
    return question_id if question_id[:1] in {"Q", "q"} else f"Q{question_id}"


def recorded_at(record: PaperRecord) -> datetime:
    """The record's timestamp as an aware datetime."""
    moment = datetime.fromisoformat(record.recorded_at)
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def indexed_papers(records: Sequence[PaperRecord]) -> list[tuple[int, PaperRecord]]:
    """Grade-bearing records paired with their index in the full history.

    The index is the id ``GET /student/result/{paper_id}`` addresses, the same
    scheme the Subject screen's paper history uses.
    """
    return [(i, r) for i, r in enumerate(records) if is_grade_bearing(r)]


def next_boundary(pct: float, boundaries: dict[str, float]) -> tuple[str | None, int | None]:
    """The next grade above ``pct`` and the whole percentage points to reach it."""
    above = sorted((threshold, grade) for grade, threshold in boundaries.items() if threshold > pct)
    if not above:
        return None, None
    threshold, grade = above[0]
    return grade, math.ceil(threshold - pct)


def _weighted_pct(records: Sequence[PaperRecord]) -> int:
    awarded = sum(r.awarded_marks for r in records)
    maximum = sum(r.maximum_marks for r in records)
    return round(awarded / maximum * 100.0) if maximum else 0


def build_floor(
    records: Sequence[PaperRecord], boundaries_for: BoundariesFor
) -> list[FloorSubjectDTO]:
    """One grade per subject, plus the gap to the next grade."""
    by_code: dict[str, list[PaperRecord]] = {}
    for _, record in indexed_papers(records):
        by_code.setdefault(record.metadata.subject_code, []).append(record)
    floor: list[FloorSubjectDTO] = []
    for code, papers in sorted(by_code.items()):
        boundaries = boundaries_for(papers[-1].metadata)
        pct = _weighted_pct(papers)
        previous = (
            _grade_for(float(_weighted_pct(papers[:-1])), boundaries) if len(papers) > 1 else None
        )
        next_grade, points = next_boundary(pct, boundaries)
        floor.append(
            FloorSubjectDTO(
                code=code,
                name=subject_name(code),
                grade=_grade_for(float(pct), boundaries),
                previousGrade=previous,
                nextGrade=next_grade,
                pointsToNext=points,
                papers=len(papers),
            )
        )
    return floor


def build_win_back(records: Sequence[PaperRecord], *, limit: int = 3) -> list[WinBackTopicDTO]:
    """Topics that cost marks on each subject's latest paper, biggest first."""
    latest: dict[str, PaperRecord] = {}
    for _, record in indexed_papers(records):
        latest[record.metadata.subject_code] = record
    topics = [
        WinBackTopicDTO(
            topic=area.topic,
            subjectCode=code,
            subjectName=subject_name(code),
            marks=area.lost_marks,
        )
        for code, record in latest.items()
        for area in record.weak_areas
        if area.lost_marks > 0
    ]
    topics.sort(key=lambda t: (-t.marks, t.topic))
    return topics[:limit]


def build_recent_papers(records: Sequence[PaperRecord], *, limit: int = 3) -> list[RecentPaperDTO]:
    """The newest grade-bearing papers."""
    rows = [
        RecentPaperDTO(
            paperId=str(index),
            subjectCode=record.metadata.subject_code,
            subjectName=subject_name(record.metadata.subject_code),
            paperNumber=record.metadata.paper_number,
            awarded=record.awarded_marks,
            maximum=record.maximum_marks,
            grade=record.grade,
            recordedAt=recorded_at(record),
        )
        for index, record in reversed(indexed_papers(records))
    ]
    return rows[:limit]


def focus_question(record: PaperRecord, *, easiest: bool) -> str | None:
    """The question Binny points at: the biggest loss, or the easiest win back."""
    lost = [a for a in record.weak_areas if a.lost_marks > 0 and a.question_ids]
    if not lost:
        return None
    pick = (
        max(lost, key=lambda a: a.accuracy) if easiest else max(lost, key=lambda a: a.lost_marks)
    )
    return pick.question_ids[0]


def paper_moment(records: Sequence[PaperRecord], now: datetime) -> PaperMomentDTO | None:
    """A ``result`` or ``tough`` moment for a paper marked in the last 48 hours."""
    papers = indexed_papers(records)
    if not papers:
        return None
    index, last = papers[-1]
    if now - recorded_at(last) > RESULT_WINDOW:
        return None
    code = last.metadata.subject_code
    earlier = [r for _, r in papers[:-1] if r.metadata.subject_code == code]
    previous = earlier[-1].grade if earlier else None
    dropped = previous is not None and grade_rank(last.grade) < grade_rank(previous)
    tough = last.grade in TOUGH_GRADES or dropped
    return PaperMomentDTO(
        kind="tough" if tough else "result",
        paperId=str(index),
        subjectCode=code,
        subjectName=subject_name(code),
        paperNumber=last.metadata.paper_number,
        awarded=last.awarded_marks,
        maximum=last.maximum_marks,
        grade=last.grade,
        previousGrade=previous,
        focusQuestion=focus_question(last, easiest=tough),
        recordedAt=recorded_at(last),
    )


def build_stats(records: Sequence[PaperRecord]) -> HomeStatsDTO:
    """Me's three stats: papers marked, practice marks won, best paper grade."""
    papers = [r for _, r in indexed_papers(records)]
    practice = [r for r in records if not is_grade_bearing(r)]
    ranked = [r for r in papers if grade_rank(r.grade) >= 0]
    best = max(ranked, key=lambda r: grade_rank(r.grade), default=None)
    return HomeStatsDTO(
        papersMarked=len(papers),
        marksWonBack=sum(r.awarded_marks for r in practice),
        bestGrade=(
            BestGradeDTO(grade=best.grade, subjectCode=best.metadata.subject_code)
            if best is not None
            else None
        ),
    )


def attempt_index(records: Sequence[PaperRecord]) -> dict[str, int]:
    """``attempts.id`` -> history index, for linking a teacher reply to its result."""
    return {r.attempt_id: i for i, r in enumerate(records) if r.attempt_id}


def build_activity(
    records: Sequence[PaperRecord], replies: Sequence[TeacherReplyDTO], *, limit: int = 6
) -> list[ActivityDTO]:
    """Me's recent-activity timeline, newest first."""
    events: list[ActivityDTO] = []
    for record in records:
        name = subject_name(record.metadata.subject_code)
        if is_grade_bearing(record):
            events.append(
                ActivityDTO(
                    kind="paper",
                    title="Paper marked",
                    sub=f"{name} P{record.metadata.paper_number} · {record.grade}",
                    at=recorded_at(record),
                )
            )
        else:
            events.append(
                ActivityDTO(
                    kind="practice",
                    title="Practice done",
                    sub=f"{name} · {record.awarded_marks} of {record.maximum_marks}",
                    at=recorded_at(record),
                )
            )
    for reply in replies:
        plural = "" if reply.marksAdded == 1 else "s"
        added = f" · +{reply.marksAdded} mark{plural}" if reply.marksAdded else ""
        events.append(
            ActivityDTO(
                kind="teacher",
                title=f"{reply.teacherName} checked {question_label(reply.questionId)}",
                sub=f"{reply.subjectName or 'Your paper'}{added}",
                at=reply.resolvedAt,
            )
        )
    events.sort(key=lambda e: e.at, reverse=True)
    return events[:limit]
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `PYTHONPATH="$(git rev-parse --show-toplevel)" pytest tests/test_student_home_service.py -v`
Expected: 12 passed.

- [ ] **Step 6: Lint, then commit**

```bash
pre-commit run --files lemely/web/schemas_student_home.py lemely/web/services/student_home.py tests/test_student_home_service.py
git commit -S -m "feat(home): add student home DTOs and history builders" -- lemely/web/schemas_student_home.py lemely/web/services/student_home.py tests/test_student_home_service.py
```

(Stage first with `git add` on the same three paths if they are new.)

---

## Task 2: Time-derived builders and `build_home`

**Files:**
- Modify: `lemely/web/services/student_home.py` (append)
- Test: `tests/test_student_home_service.py` (append)

**Interfaces:**
- Consumes: Task 1 names; `lemely.db.xp_repo.StreakState(current_length, longest_length, last_active_on, freezes_available)`, `XpBreakdown(total, by_source: dict[XpSource, int])`; `lemely.db.study_plan_repo.SessionView(id, date, topic, activity_type, duration_minutes, focus, completed_at, subject_code)`; `lemely.db.exam_calendar_repo.StudentExamCalendar(availability, entries[].dates[].exam_date)`; `lemely.db.quiz_taking_repo.AssignedQuizRow`; `lemely.web.schemas_student.UploadRunDTO(paperId, status, filename, startedAt, stale)`; Task 3's `TeacherReplyRow` (only as a type; the dataclass is defined in Task 3, so this task's tests build `TeacherReplyRow` after Task 3 lands; until then the `build_home` test passes `teacher_replies=[]`).
- Produces: `BREAK_DAYS = 3`, `STREAK_RISK_HOUR = 17`, `build_goals(today, week) -> TodayDTO`, `build_today_sessions(sessions, local_date) -> list[PlanSessionDTO]`, `build_week(week_start, local_date, xp_by_day, sessions) -> list[WeekDayDTO]`, `streak_dto(streak) -> StreakDTO`, `streak_moments(streak, goals, local_date, local_hour) -> list[StreakMomentDTO]`, `back_moment(streak, local_date) -> BackMomentDTO | None`, `marking_moment(run) -> MarkingMomentDTO | None`, `next_exam_on(calendar, local_date) -> date | None`, `build_homework(rows, *, limit=3) -> list[HomeworkDTO]`, `build_teacher_replies(rows, index) -> list[TeacherReplyDTO]`, `HomeInputs` (dataclass), `build_home(inputs, boundaries_for) -> StudentHomeDTO`.

- [ ] **Step 1: Append the failing tests**

Merge the import lines below into the test module's top import block (ruff `E402` rejects imports below code); append the rest at the end.

```python
# ── time-derived builders ─────────────────────────────────────────────────

import uuid
from datetime import date

from lemely.db.exam_calendar_repo import ExamDateRow, StudentExamCalendar, StudentExamEntry
from lemely.db.models.enums import QuizSubmissionStatus, XpSource
from lemely.db.quiz_taking_repo import AssignedQuizRow
from lemely.db.study_plan_repo import SessionView
from lemely.db.xp_repo import StreakState, XpBreakdown
from lemely.web.schemas_student import UploadRunDTO
from lemely.web.schemas_student_home import TodayDTO
from lemely.web.services.student_home import (
    HomeInputs,
    back_moment,
    build_goals,
    build_home,
    build_homework,
    build_today_sessions,
    build_week,
    marking_moment,
    next_exam_on,
    streak_moments,
)

TODAY = date(2026, 11, 12)  # a Thursday
MONDAY = date(2026, 11, 9)


def _bd(**xp: int) -> XpBreakdown:
    by_source = dict.fromkeys(XpSource, 0)
    for name, amount in xp.items():
        by_source[XpSource[name]] = amount
    return XpBreakdown(total=sum(by_source.values()), by_source=by_source)


def _streak(current: int = 9, last: date | None = TODAY, freezes: int = 0) -> StreakState:
    return StreakState(
        current_length=current, longest_length=14, last_active_on=last, freezes_available=freezes
    )


def _session(day: date, topic: str, *, done: bool = False, code: str = "0580") -> SessionView:
    return SessionView(
        id=uuid.uuid4(),
        date=day,
        topic=topic,
        activity_type=None,  # type: ignore[arg-type]
        duration_minutes=10,
        focus="",
        completed_at=NOW if done else None,
        subject_code=code,
    )


def test_goals_read_todays_xp_by_source_and_this_weeks_papers() -> None:
    goals = build_goals(_bd(quiz_completed=20), _bd(paper_corrected=50))
    assert goals == TodayDTO(practice=True, flashcards=False, paperThisWeek=True)
    assert build_goals(_bd(study_session_completed=5), _bd()).practice is True


def test_week_marks_done_days_labels_and_today() -> None:
    sessions = [
        _session(MONDAY, "Vectors"),
        _session(MONDAY, "Second"),
        _session(date(2026, 11, 13), "Paper 4"),
    ]
    xp = {MONDAY: 10, date(2026, 11, 10): 5, date(2026, 11, 14): 30}
    week = build_week(MONDAY, TODAY, xp, sessions)
    assert len(week) == 7
    assert week[0].label == "Vectors"
    assert [d.done for d in week] == [True, True, False, False, False, False, False]
    assert [d.isToday for d in week].index(True) == 3
    assert week[4].label == "Paper 4"


def test_today_sessions_only_today() -> None:
    rows = build_today_sessions([_session(TODAY, "Vectors", done=True), _session(MONDAY, "x")], TODAY)
    assert [(r.topic, r.done, r.minutes) for r in rows] == [("Vectors", True, 10)]


def test_streak_at_risk_needs_evening_a_gap_today_and_no_freeze() -> None:
    goals = TodayDTO(practice=False, flashcards=False, paperThisWeek=True)
    yesterday = date(2026, 11, 11)
    at_risk = streak_moments(_streak(last=yesterday), goals, TODAY, 18)
    assert [(m.kind, m.streakDays) for m in at_risk] == [("streakAtRisk", 9)]
    assert streak_moments(_streak(last=yesterday), goals, TODAY, 10) == []
    assert streak_moments(_streak(last=yesterday, freezes=1), goals, TODAY, 20) == []
    assert streak_moments(_streak(current=1, last=yesterday), goals, TODAY, 20) == []
    assert streak_moments(_streak(last=TODAY), goals, TODAY, 20) == []


def test_goal_done_when_all_three_goals_are_met() -> None:
    goals = TodayDTO(practice=True, flashcards=True, paperThisWeek=True)
    assert [m.kind for m in streak_moments(_streak(current=10), goals, TODAY, 20)] == ["goalDone"]


def test_back_after_break_from_three_days_away() -> None:
    back = back_moment(_streak(current=0, last=date(2026, 11, 6)), TODAY)
    assert back is not None
    assert back.daysAway == 6
    assert back_moment(_streak(last=date(2026, 11, 10)), TODAY) is None
    assert back_moment(_streak(last=None), TODAY) is None


def test_marking_moment_only_for_a_live_run() -> None:
    run = UploadRunDTO(paperId="p1", status="processing", filename="phys.pdf", startedAt=NOW, stale=False)
    moment = marking_moment(run)
    assert moment is not None
    assert (moment.paperId, moment.filename, moment.stale) == ("p1", "phys.pdf", False)
    done = UploadRunDTO(paperId="p1", status="complete", filename=None, startedAt=None, stale=False)
    assert marking_moment(done) is None
    assert marking_moment(None) is None


def test_next_exam_is_the_earliest_future_date() -> None:
    def row(day: date) -> ExamDateRow:
        return ExamDateRow(
            paper_variant="2", exam_date=day, starts_at_local=None, duration_minutes=None, source="t"
        )

    calendar = StudentExamCalendar(
        availability="ok",  # type: ignore[arg-type]
        entries=[
            StudentExamEntry(
                subject_code="0580",
                session_month=None,
                session_year=None,
                paper_number=4,
                availability="dated",  # type: ignore[arg-type]
                dates=[row(date(2026, 11, 1)), row(date(2027, 5, 10)), row(date(2027, 5, 3))],
            )
        ],
    )
    assert next_exam_on(calendar, TODAY) == date(2027, 5, 3)
    assert next_exam_on(StudentExamCalendar(availability="ok", entries=[]), TODAY) is None  # type: ignore[arg-type]


def _assigned(**overrides: object) -> AssignedQuizRow:
    base: dict[str, object] = {
        "assignment_id": uuid.uuid4(),
        "quiz_title": "Trigonometry set",
        "subject_code": "0580",
        "class_name": "10B",
        "teacher_name": "Ms. Hanna",
        "assigned_at": NOW - timedelta(days=1),
        "due_at": NOW + timedelta(days=2),
        "closes_at": None,
        "question_count": 12,
        "time_limit_minutes": None,
        "submission_status": QuizSubmissionStatus.not_started,
        "is_open": True,
        "is_overdue": False,
    }
    base.update(overrides)
    return AssignedQuizRow(**base)  # type: ignore[arg-type]


def test_homework_is_open_teacher_work_due_soonest_first() -> None:
    rows = [
        _assigned(quiz_title="Later", due_at=NOW + timedelta(days=5)),
        _assigned(quiz_title="Soon", due_at=NOW + timedelta(days=1)),
        _assigned(quiz_title="Mine", teacher_name=None),
        _assigned(quiz_title="Done", submission_status=QuizSubmissionStatus.submitted),
        _assigned(quiz_title="Closed", is_open=False),
        _assigned(quiz_title="No date", due_at=None),
    ]
    assert [h.title for h in build_homework(rows)] == ["Soon", "Later", "No date"]


def _inputs(**overrides: object) -> HomeInputs:
    base: dict[str, object] = {
        "student_name": "Mariam Adel",
        "records": [],
        "now": NOW,
        "local_date": TODAY,
        "local_hour": 15,
        "week_start": MONDAY,
        "streak": _streak(current=0, last=None),
        "today_xp": _bd(),
        "week_xp": _bd(),
        "week_xp_by_day": {},
        "sessions": [],
        "calendar": None,
        "assigned": [],
        "active_run": None,
        "teacher_replies": [],
        "class_count": 0,
    }
    base.update(overrides)
    return HomeInputs(**base)  # type: ignore[arg-type]


def test_build_home_for_a_new_student_is_neutral_and_never_needs_boundaries() -> None:
    def refuse(_metadata: ExamMetadata) -> dict[str, float]:
        raise AssertionError("no papers, no boundaries")

    home = build_home(_inputs(), refuse)
    assert home.moments == []
    assert home.floor == []
    assert home.stats.papersMarked == 0
    assert home.lastPaperAt is None
    assert len(home.week) == 7
    assert home.nextExamOn is None


def test_build_home_orders_moments_marking_paper_reply_streak_back() -> None:
    run = UploadRunDTO(paperId="u1", status="processing", filename=None, startedAt=NOW, stale=False)
    home = build_home(
        _inputs(
            records=[_paper(grade="B")],
            active_run=run,
            streak=_streak(current=0, last=date(2026, 11, 6)),
        ),
        _boundaries,
    )
    assert [m.kind for m in home.moments] == ["marking", "result", "backAfterBreak"]
    # 61/80 = 76% against BOUNDARIES -> B
    assert home.floor[0].grade == "B"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH="$(git rev-parse --show-toplevel)" pytest tests/test_student_home_service.py -v`
Expected: FAIL with `ImportError: cannot import name 'HomeInputs'`.

- [ ] **Step 3: Append the builders**

Add these imports to the top of `lemely/web/services/student_home.py` (merge with the existing import block):

```python
from dataclasses import dataclass
from datetime import date

from lemely.db.models.enums import QuizSubmissionStatus, XpSource
from lemely.web.schemas_student_home import (
    BackMomentDTO,
    HomeworkDTO,
    MarkingMomentDTO,
    MomentDTO,
    PlanSessionDTO,
    StreakDTO,
    StreakMomentDTO,
    StudentHomeDTO,
    TeacherReplyMomentDTO,
    TodayDTO,
    WeekDayDTO,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from lemely.db.exam_calendar_repo import StudentExamCalendar
    from lemely.db.quiz_taking_repo import AssignedQuizRow
    from lemely.db.student_home_repo import TeacherReplyRow
    from lemely.db.study_plan_repo import SessionView
    from lemely.db.xp_repo import StreakState, XpBreakdown
    from lemely.web.schemas_student import UploadRunDTO
```

Then append:

```python
BREAK_DAYS = 3
STREAK_RISK_HOUR = 17
_OPEN_SUBMISSION = frozenset({QuizSubmissionStatus.not_started, QuizSubmissionStatus.in_progress})
_LIVE_RUN = frozenset({"pending", "processing"})


def build_goals(today: XpBreakdown, week: XpBreakdown) -> TodayDTO:
    """Today's three goals from XP already earned: practice, flashcards, a paper this week."""
    practice = (
        today.by_source.get(XpSource.quiz_completed, 0) > 0
        or today.by_source.get(XpSource.study_session_completed, 0) > 0
    )
    return TodayDTO(
        practice=practice,
        flashcards=today.by_source.get(XpSource.flashcard_reviewed, 0) > 0,
        paperThisWeek=week.by_source.get(XpSource.paper_corrected, 0) > 0,
    )


def build_today_sessions(sessions: Iterable[SessionView], local_date: date) -> list[PlanSessionDTO]:
    """Study-plan sessions scheduled for today, across subjects."""
    return [
        PlanSessionDTO(
            sessionId=str(s.id),
            subjectCode=s.subject_code,
            topic=s.topic,
            minutes=s.duration_minutes,
            done=s.completed_at is not None,
        )
        for s in sessions
        if s.date == local_date
    ]


def build_week(
    week_start: date,
    local_date: date,
    xp_by_day: dict[date, int],
    sessions: Sequence[SessionView],
) -> list[WeekDayDTO]:
    """Mon–Sun: a day is done when it earned XP; its label is its first planned topic."""
    labels: dict[date, str] = {}
    for session in sorted(sessions, key=lambda s: s.date):
        labels.setdefault(session.date, session.topic)
    days: list[WeekDayDTO] = []
    for offset in range(7):
        day = week_start + timedelta(days=offset)
        days.append(
            WeekDayDTO(
                day=day,
                label=labels.get(day),
                done=day <= local_date and xp_by_day.get(day, 0) > 0,
                isToday=day == local_date,
            )
        )
    return days


def streak_dto(streak: StreakState) -> StreakDTO:
    return StreakDTO(
        current=streak.current_length,
        longest=streak.longest_length,
        lastActiveOn=streak.last_active_on,
        freezesAvailable=streak.freezes_available,
    )


def streak_moments(
    streak: StreakState, goals: TodayDTO, local_date: date, local_hour: int
) -> list[StreakMomentDTO]:
    """``goalDone`` when all three goals are met, else ``streakAtRisk`` when it applies.

    At risk means: a streak of two days or more, last active yesterday, nothing
    earned yet today, it is evening in the student's own zone, and no freeze is
    saved. A saved freeze covers the day on its own, so warning about it would
    be the leverage the Profile screen promised never to use.
    """
    if goals.practice and goals.flashcards and goals.paperThisWeek:
        return [StreakMomentDTO(kind="goalDone", streakDays=streak.current_length)]
    at_risk = (
        streak.current_length >= 2
        and streak.freezes_available == 0
        and streak.last_active_on == local_date - timedelta(days=1)
        and local_hour >= STREAK_RISK_HOUR
    )
    if at_risk:
        return [StreakMomentDTO(kind="streakAtRisk", streakDays=streak.current_length)]
    return []


def back_moment(streak: StreakState, local_date: date) -> BackMomentDTO | None:
    """Back after a break: three or more days since the last XP."""
    if streak.last_active_on is None:
        return None
    away = (local_date - streak.last_active_on).days
    return BackMomentDTO(daysAway=away) if away >= BREAK_DAYS else None


def marking_moment(run: UploadRunDTO | None) -> MarkingMomentDTO | None:
    """A paper is being marked right now."""
    if run is None or run.status not in _LIVE_RUN:
        return None
    return MarkingMomentDTO(
        paperId=run.paperId, filename=run.filename, startedAt=run.startedAt, stale=run.stale
    )


def next_exam_on(calendar: StudentExamCalendar, local_date: date) -> date | None:
    """The earliest exam date still ahead, across every declared paper and variant."""
    upcoming = [
        row.exam_date
        for entry in calendar.entries
        for row in entry.dates
        if row.exam_date >= local_date
    ]
    return min(upcoming, default=None)


def build_homework(rows: Sequence[AssignedQuizRow], *, limit: int = 3) -> list[HomeworkDTO]:
    """Open, unsubmitted work a teacher set, due soonest first."""
    open_rows = [
        r
        for r in rows
        if r.teacher_name is not None and r.is_open and r.submission_status in _OPEN_SUBMISSION
    ]
    far = datetime.max.replace(tzinfo=UTC)
    open_rows.sort(key=lambda r: (r.due_at or far, r.assigned_at))
    return [
        HomeworkDTO(
            assignmentId=str(r.assignment_id),
            title=r.quiz_title,
            subjectCode=r.subject_code,
            teacherName=r.teacher_name or "",
            dueAt=r.due_at,
            questionCount=r.question_count,
            isOverdue=r.is_overdue,
        )
        for r in open_rows[:limit]
    ]


def build_teacher_replies(
    rows: Sequence[TeacherReplyRow], index: dict[str, int]
) -> list[TeacherReplyDTO]:
    """Teacher replies, each linked to its result when the paper is in history."""
    return [
        TeacherReplyDTO(
            reviewId=str(row.review_id),
            teacherName=row.teacher_name,
            questionId=row.question_id,
            subjectCode=row.subject_code,
            subjectName=subject_name(row.subject_code) if row.subject_code else None,
            paperNumber=row.paper_number,
            marksAdded=row.marks_added,
            paperId=(
                str(index[str(row.attempt_id)]) if str(row.attempt_id) in index else None
            ),
            resolvedAt=row.resolved_at,
        )
        for row in rows
    ]


@dataclass(frozen=True, slots=True)
class HomeInputs:
    """Everything the router gathered for one request."""

    student_name: str
    records: Sequence[PaperRecord]
    now: datetime
    local_date: date
    local_hour: int
    week_start: date
    streak: StreakState
    today_xp: XpBreakdown
    week_xp: XpBreakdown
    week_xp_by_day: dict[date, int]
    sessions: Sequence[SessionView]
    calendar: StudentExamCalendar | None
    assigned: Sequence[AssignedQuizRow]
    active_run: UploadRunDTO | None
    teacher_replies: Sequence[TeacherReplyRow]
    class_count: int


def build_home(inputs: HomeInputs, boundaries_for: BoundariesFor) -> StudentHomeDTO:
    """Assemble the whole payload. The client picks the stage moment from ``moments``."""
    records = inputs.records
    papers = indexed_papers(records)
    replies = build_teacher_replies(inputs.teacher_replies, attempt_index(records))
    goals = build_goals(inputs.today_xp, inputs.week_xp)

    moments: list[MomentDTO] = []
    marking = marking_moment(inputs.active_run)
    if marking is not None:
        moments.append(marking)
    paper = paper_moment(records, inputs.now)
    if paper is not None:
        moments.append(paper)
    if replies:
        moments.append(TeacherReplyMomentDTO(reply=replies[0]))
    moments.extend(streak_moments(inputs.streak, goals, inputs.local_date, inputs.local_hour))
    back = back_moment(inputs.streak, inputs.local_date)
    if back is not None:
        moments.append(back)

    return StudentHomeDTO(
        studentName=inputs.student_name,
        localDate=inputs.local_date,
        localHour=inputs.local_hour,
        moments=moments,
        goals=goals,
        todaySessions=build_today_sessions(inputs.sessions, inputs.local_date),
        week=build_week(
            inputs.week_start, inputs.local_date, inputs.week_xp_by_day, inputs.sessions
        ),
        streak=streak_dto(inputs.streak),
        nextExamOn=(
            next_exam_on(inputs.calendar, inputs.local_date) if inputs.calendar else None
        ),
        floor=build_floor(records, boundaries_for) if papers else [],
        winBack=build_win_back(records),
        recentPapers=build_recent_papers(records),
        lastPaperAt=recorded_at(papers[-1][1]) if papers else None,
        teacherReplies=replies,
        homework=build_homework(inputs.assigned),
        classCount=inputs.class_count,
        stats=build_stats(records),
        activity=build_activity(records, replies),
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH="$(git rev-parse --show-toplevel)" pytest tests/test_student_home_service.py -v`
Expected: 23 passed. If `ExamDateRow`/`StudentExamEntry` constructor fields differ from the test, read `lemely/db/exam_calendar_repo.py:100-135` and match them; do not change the repo.

- [ ] **Step 5: Lint, then commit**

```bash
pre-commit run --files lemely/web/services/student_home.py tests/test_student_home_service.py
git commit -S -m "feat(home): build today, week, streak and moment data" -- lemely/web/services/student_home.py tests/test_student_home_service.py
```

---

## Task 3: Teacher replies repo query

**Files:**
- Create: `lemely/db/student_home_repo.py`
- Test: `tests/test_student_home_repo.py`

**Interfaces:**
- Consumes: models `ReviewQueueItem` (`lemely/db/models/ops.py`), `Attempt`, `QuestionResult` (`lemely/db/models/attempts.py`), `User` (`lemely/db/models`), enum `ReviewStatus`.
- Produces: `TeacherReplyRow(review_id: uuid.UUID, attempt_id: uuid.UUID, teacher_name: str, question_id: str, subject_code: str | None, paper_number: int | None, marks_added: int, resolved_at: datetime)` and `StudentHomeReads(sessionmaker).recent_teacher_replies(student_id: uuid.UUID | str, *, since: datetime, limit: int = 3) -> list[TeacherReplyRow]`.

Scoping rule: rows come only from review items whose attempt belongs to `student_id` (`Attempt.user_id == student`) and whose attempt is not soft-deleted. The teacher's email is never exposed: a teacher with no display name shows as "Your teacher".

- [ ] **Step 1: Write the failing test**

```python
"""``StudentHomeReads.recent_teacher_replies`` against a throwaway Postgres."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.core.analytics import summarize_weaknesses
from lemely.core.schemas import (
    AccuracyReport,
    ConfidenceBand,
    CorrectedQuestion,
    CorrectionResult,
    ExamMetadata,
    GradePrediction,
)
from lemely.db.attempt_repo import AttemptRepository
from lemely.db.base import Base
from lemely.db.class_repo import ClassService
from lemely.db.models import User
from lemely.db.models.attempts import Attempt
from lemely.db.models.enums import Role
from lemely.db.models.ops import ReviewQueueItem
from lemely.db.review_repo import ReviewService
from lemely.db.student_home_repo import StudentHomeReads
from lemely.runtime.config import DatabaseSettings

if TYPE_CHECKING:
    from collections.abc import Iterator


def _reachable(url: str) -> bool:
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
    if not _reachable(base_url):
        pytest.skip("local Postgres not reachable")
    admin = create_engine(make_url(base_url).set(database="postgres"), isolation_level="AUTOCOMMIT")
    name = f"lemely_test_{uuid.uuid4().hex[:12]}"
    with admin.connect() as conn:
        conn.execute(sa.text(f'CREATE DATABASE "{name}"'))
    engine = create_engine(make_url(base_url).set(database=name))
    Base.metadata.create_all(engine)
    try:
        yield sessionmaker(bind=engine, expire_on_commit=False, future=True)
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


def _user(sm: sessionmaker[Session], role: Role, name: str | None) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=role, display_name=name))
    return uid


def _report() -> AccuracyReport:
    metadata = ExamMetadata(
        subject_code="9999", paper_number=4, paper_variant=1, session_month="May/June", session_year=2024
    )
    question = CorrectedQuestion(
        question_id="7",
        awarded_marks=1,
        maximum_marks=3,
        confidence=ConfidenceBand.LOW,
        confidence_score=0.4,
        needs_teacher_review=True,
        student_answer="a",
        expected_answer="b",
        topic="Vectors",
        marker_source="ai",
        review_reason="low_confidence",
        plagiarism_flagged=False,
        matched_point_ids=["p1"],
    )
    correction = CorrectionResult(metadata=metadata, questions=[question])
    return AccuracyReport(
        correction=correction,
        weaknesses=summarize_weaknesses(correction),
        grade_prediction=GradePrediction(
            awarded_marks=1,
            maximum_marks=3,
            percentage=33.33,
            grade="U",
            confidence=ConfidenceBand.LOW,
            needs_teacher_review=True,
            boundary_source="global_default",
        ),
    )


def _setup(sm: sessionmaker[Session]) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
    classes = ClassService(sm)
    teacher = _user(sm, Role.teacher, "Ms. Hanna")
    student = _user(sm, Role.student, "Mariam")
    cls = classes.create_class(teacher, "10B Mathematics")
    assert cls.join_code is not None
    classes.join_by_code(student, cls.join_code)
    attempt = AttemptRepository(sm).persist_correction(user_id=str(student), report=_report())
    with sm() as session:
        item = session.scalars(
            select(ReviewQueueItem).where(ReviewQueueItem.attempt_id == attempt)
        ).one()
    return teacher, student, attempt, item.id


def test_a_resolved_override_is_a_reply_with_marks_added(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    teacher, student, attempt, item = _setup(pg_sessionmaker)
    ReviewService(pg_sessionmaker, ClassService(pg_sessionmaker)).resolve(
        teacher, Role.teacher, item, override_marks=2
    )
    rows = StudentHomeReads(pg_sessionmaker).recent_teacher_replies(
        student, since=datetime.now(UTC) - timedelta(days=7)
    )
    assert len(rows) == 1
    row = rows[0]
    assert (row.teacher_name, row.question_id, row.marks_added) == ("Ms. Hanna", "7", 1)
    assert (row.attempt_id, row.subject_code, row.paper_number) == (attempt, "9999", 4)


def test_open_items_other_students_and_deleted_papers_are_not_replies(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    teacher, student, attempt, item = _setup(pg_sessionmaker)
    reads = StudentHomeReads(pg_sessionmaker)
    since = datetime.now(UTC) - timedelta(days=7)
    assert reads.recent_teacher_replies(student, since=since) == []

    ReviewService(pg_sessionmaker, ClassService(pg_sessionmaker)).resolve(teacher, Role.teacher, item)
    stranger = _user(pg_sessionmaker, Role.student, "Other")
    assert reads.recent_teacher_replies(stranger, since=since) == []
    accepted = reads.recent_teacher_replies(student, since=since)
    assert [r.marks_added for r in accepted] == [0]

    with pg_sessionmaker.begin() as session:
        session.get_one(Attempt, attempt).deleted_at = datetime.now(UTC)
    assert reads.recent_teacher_replies(student, since=since) == []


def test_replies_older_than_since_are_left_out(pg_sessionmaker: sessionmaker[Session]) -> None:
    teacher, student, _attempt, item = _setup(pg_sessionmaker)
    ReviewService(pg_sessionmaker, ClassService(pg_sessionmaker)).resolve(teacher, Role.teacher, item)
    rows = StudentHomeReads(pg_sessionmaker).recent_teacher_replies(
        student, since=datetime.now(UTC) + timedelta(minutes=1)
    )
    assert rows == []


def test_a_teacher_without_a_display_name_is_your_teacher(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    teacher, student, _attempt, item = _setup(pg_sessionmaker)
    with pg_sessionmaker.begin() as session:
        session.get_one(User, teacher).display_name = None
    ReviewService(pg_sessionmaker, ClassService(pg_sessionmaker)).resolve(teacher, Role.teacher, item)
    rows = StudentHomeReads(pg_sessionmaker).recent_teacher_replies(
        student, since=datetime.now(UTC) - timedelta(days=1)
    )
    assert rows[0].teacher_name == "Your teacher"
```

If a `CorrectedQuestion`/`GradePrediction` field name differs, copy the exact construction from `tests/test_review_repo.py:134-185` (that file's `_question` and `_report` are the reference).

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONPATH="$(git rev-parse --show-toplevel)" pytest tests/test_student_home_repo.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'lemely.db.student_home_repo'` (or SKIPPED when no local Postgres; start it before claiming a pass).

- [ ] **Step 3: Write the repo**

```python
"""Read-only queries the student Home needs and no other repo answers (lane L1).

One question today: which of my answers did a teacher check recently? The
teacher review queue (:mod:`lemely.db.review_repo`) is teacher-scoped by
design, so this is a separate, student-scoped read rather than a widening of
that service's tenancy rules.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import select

from lemely.db.models import User
from lemely.db.models.attempts import Attempt, QuestionResult
from lemely.db.models.enums import ReviewStatus
from lemely.db.models.ops import ReviewQueueItem

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.orm import Session, sessionmaker

_FALLBACK_TEACHER = "Your teacher"


@dataclass(frozen=True, slots=True)
class TeacherReplyRow:
    """One resolved review item on the student's own answer."""

    review_id: uuid.UUID
    attempt_id: uuid.UUID
    teacher_name: str
    question_id: str
    subject_code: str | None
    paper_number: int | None
    marks_added: int
    resolved_at: datetime


class StudentHomeReads:
    """Student-scoped reads for ``GET /api/student/home``."""

    def __init__(self, sessionmaker: sessionmaker[Session]) -> None:
        self._sessionmaker = sessionmaker

    def recent_teacher_replies(
        self, student_id: uuid.UUID | str, *, since: datetime, limit: int = 3
    ) -> list[TeacherReplyRow]:
        """Resolved review items on the student's live attempts since ``since``, newest first.

        ``marks_added`` is the teacher's override minus the original mark,
        floored at zero; an accepted mark adds nothing.
        """
        student = student_id if isinstance(student_id, uuid.UUID) else uuid.UUID(student_id)
        query = (
            select(
                ReviewQueueItem.id,
                ReviewQueueItem.attempt_id,
                ReviewQueueItem.resolved_at,
                User.display_name,
                QuestionResult.question_id,
                QuestionResult.awarded_marks,
                QuestionResult.teacher_awarded_marks,
                Attempt.subject_code,
                Attempt.paper_number,
            )
            .join(Attempt, Attempt.id == ReviewQueueItem.attempt_id)
            .join(QuestionResult, QuestionResult.id == ReviewQueueItem.question_result_id)
            .join(User, User.id == ReviewQueueItem.resolved_by)
            .where(
                Attempt.user_id == student,
                Attempt.deleted_at.is_(None),
                ReviewQueueItem.status == ReviewStatus.resolved,
                ReviewQueueItem.resolved_at.is_not(None),
                ReviewQueueItem.resolved_at >= since,
            )
            .order_by(ReviewQueueItem.resolved_at.desc())
            .limit(limit)
        )
        with self._sessionmaker() as session:
            rows = session.execute(query).all()
        replies: list[TeacherReplyRow] = []
        for row in rows:
            override = row.teacher_awarded_marks
            added = max(0, override - row.awarded_marks) if override is not None else 0
            replies.append(
                TeacherReplyRow(
                    review_id=row.id,
                    attempt_id=row.attempt_id,
                    teacher_name=row.display_name or _FALLBACK_TEACHER,
                    question_id=row.question_id,
                    subject_code=row.subject_code,
                    paper_number=row.paper_number,
                    marks_added=added,
                    resolved_at=row.resolved_at,
                )
            )
        return replies
```

- [ ] **Step 4: Run it to verify it passes**

Run: `PYTHONPATH="$(git rev-parse --show-toplevel)" pytest tests/test_student_home_repo.py -v`
Expected: 4 passed (not skipped).

- [ ] **Step 5: Lint, then commit**

```bash
pre-commit run --files lemely/db/student_home_repo.py tests/test_student_home_repo.py
git commit -S -m "feat(home): read a student's recent teacher replies" -- lemely/db/student_home_repo.py tests/test_student_home_repo.py
```

---

## Task 4: `GET /api/student/home` router

**Files:**
- Create: `lemely/web/routers/student_home.py`
- Modify: `lemely/web/app.py` (import list near line 57, include near line 224)
- Modify: `tests/test_authz_matrix_complete.py` (near line 477)
- Test: `tests/test_student_home_route.py`

**Interfaces:**
- Consumes: Tasks 1–3; deps from `lemely/web/deps.py`: `AuthContext`, `require_role`, `get_settings`, `get_history_store`, `get_user_mirror`, `get_student_profile_service`, `get_xp_service`, `get_user_zone_reader`, `get_study_plan_service`, `get_exam_calendar_service`, `get_quiz_taking_service`, `get_student_upload_repo`, `get_class_service`; `lemely.db.session.get_sessionmaker`; `lemely.db.xp_repo.week_bounds`, `StreakState`, `XpBreakdown`; `lemely.web.routers.student._run_dto`.
- Produces: `router` (prefix `/api/student`), `get_student_home_reads() -> StudentHomeReads`, `_now() -> datetime` (monkeypatched in tests). Response model `StudentHomeDTO`.

Auth and tenancy: `require_role(Role.student)`. Every read is keyed by `auth.user_id`; there is no path parameter, so no IDOR surface. A non-UUID `auth.user_id` (hermetic tests only, see `student_overview`'s docstring) skips every database read and returns neutral values instead of a 500.

- [ ] **Step 1: Write the failing route tests**

```python
"""``GET /api/student/home`` wiring, with every service faked."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from lemely.core.history import PaperRecord
from lemely.core.schemas import ExamMetadata, WeakArea
from lemely.db.models.enums import UploadStatus, XpSource
from lemely.db.student_home_repo import TeacherReplyRow
from lemely.db.xp_repo import StreakState, XpBreakdown
from lemely.io.history_store import HistoryStore
from lemely.web import create_app
from lemely.web.deps import (
    AuthContext,
    get_auth_context,
    get_class_service,
    get_exam_calendar_service,
    get_history_store,
    get_quiz_taking_service,
    get_student_profile_service,
    get_student_upload_repo,
    get_study_plan_service,
    get_user_mirror,
    get_user_zone_reader,
    get_xp_service,
)
from lemely.web.routers.student_home import get_student_home_reads

if TYPE_CHECKING:
    from pathlib import Path

STUDENT = uuid.uuid4()
NOW = datetime(2026, 11, 12, 16, 0, tzinfo=UTC)  # 18:00 in Cairo


class _Boundaries:
    def __init__(self) -> None:
        pass

    def resolve(self, _metadata: ExamMetadata) -> tuple[dict[str, float], str]:
        return {"A*": 90.0, "A": 80.0, "B": 70.0, "C": 60.0, "D": 50.0, "E": 40.0}, "exact"


def _breakdown(**xp: int) -> XpBreakdown:
    by_source = dict.fromkeys(XpSource, 0)
    for name, amount in xp.items():
        by_source[XpSource[name]] = amount
    return XpBreakdown(total=sum(by_source.values()), by_source=by_source)


def _record(*, at: datetime, grade: str = "B", attempt_id: str | None = None) -> PaperRecord:
    return PaperRecord(
        student_id=str(STUDENT),
        metadata=ExamMetadata(
            subject_code="0580", paper_number=4, paper_variant=2, session_month="May/June", session_year=2024
        ),
        awarded_marks=61,
        maximum_marks=80,
        percentage=76.25,
        grade=grade,
        weak_areas=[
            WeakArea(topic="Vectors", lost_marks=9, maximum_marks=12, accuracy=0.25, question_ids=["8"])
        ],
        recorded_at=at.isoformat(),
        attempt_id=attempt_id,
    )


@pytest.fixture
def fakes(monkeypatch: pytest.MonkeyPatch) -> dict[str, MagicMock]:
    monkeypatch.setattr("lemely.web.routers.student_home._now", lambda: NOW)
    monkeypatch.setattr("lemely.web.routers.student_home.GradeBoundaryStore", _Boundaries)
    xp = MagicMock()
    xp.streak.return_value = StreakState(
        current_length=9, longest_length=14, last_active_on=date(2026, 11, 11), freezes_available=0
    )
    xp.xp_breakdown.return_value = _breakdown()
    xp.xp_by_day.return_value = {}
    zones = MagicMock()
    zones.zone_for.return_value = ZoneInfo("Africa/Cairo")
    plans = MagicMock()
    plans.get_current.return_value = None
    calendar = MagicMock()
    calendar.calendar_for_student.return_value = MagicMock(entries=[])
    quizzes = MagicMock()
    quizzes.list_assigned.return_value = []
    uploads = MagicMock()
    uploads.get_active_run.return_value = None
    classes = MagicMock()
    classes.enrolled_class_ids.return_value = [uuid.uuid4()]
    reads = MagicMock()
    reads.recent_teacher_replies.return_value = []
    mirror = MagicMock()
    mirror.get_by_id.return_value = MagicMock(display_name="Mariam Adel", email="m@example.com")
    profiles = MagicMock()
    profiles.list_enrolments.return_value = []
    return {
        "xp": xp,
        "zones": zones,
        "plans": plans,
        "calendar": calendar,
        "quizzes": quizzes,
        "uploads": uploads,
        "classes": classes,
        "reads": reads,
        "mirror": mirror,
        "profiles": profiles,
    }


def _client(store: HistoryStore, fakes: dict[str, MagicMock], user_id: str = str(STUDENT)) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(user_id=user_id, role="student")
    app.dependency_overrides[get_history_store] = lambda: store
    app.dependency_overrides[get_xp_service] = lambda: fakes["xp"]
    app.dependency_overrides[get_user_zone_reader] = lambda: fakes["zones"]
    app.dependency_overrides[get_study_plan_service] = lambda: fakes["plans"]
    app.dependency_overrides[get_exam_calendar_service] = lambda: fakes["calendar"]
    app.dependency_overrides[get_quiz_taking_service] = lambda: fakes["quizzes"]
    app.dependency_overrides[get_student_upload_repo] = lambda: fakes["uploads"]
    app.dependency_overrides[get_class_service] = lambda: fakes["classes"]
    app.dependency_overrides[get_student_home_reads] = lambda: fakes["reads"]
    app.dependency_overrides[get_user_mirror] = lambda: fakes["mirror"]
    app.dependency_overrides[get_student_profile_service] = lambda: fakes["profiles"]
    return TestClient(app)


def test_home_for_a_student_with_a_fresh_paper(tmp_path: Path, fakes: dict[str, MagicMock]) -> None:
    store = HistoryStore(tmp_path / "h")
    store.append(str(STUDENT), _record(at=NOW - timedelta(hours=3), attempt_id="att-1"))
    fakes["reads"].recent_teacher_replies.return_value = [
        TeacherReplyRow(
            review_id=uuid.uuid4(),
            attempt_id=uuid.UUID(int=1),
            teacher_name="Ms. Hanna",
            question_id="7",
            subject_code="0580",
            paper_number=4,
            marks_added=1,
            resolved_at=NOW - timedelta(hours=1),
        )
    ]
    body = _client(store, fakes).get("/api/student/home").json()

    assert body["studentName"] == "Mariam Adel"
    assert body["localDate"] == "2026-11-12"
    assert body["localHour"] == 18
    kinds = [m["kind"] for m in body["moments"]]
    assert kinds == ["result", "teacherReply", "streakAtRisk"]
    assert body["moments"][0]["focusQuestion"] == "8"
    assert body["floor"][0] | {"name": None} == {
        "code": "0580",
        "name": None,
        "grade": "B",
        "previousGrade": None,
        "nextGrade": "A",
        "pointsToNext": 4,
        "papers": 1,
    }
    assert body["winBack"][0]["topic"] == "Vectors"
    assert body["recentPapers"][0]["paperId"] == "0"
    assert body["classCount"] == 1
    assert len(body["week"]) == 7
    fakes["reads"].recent_teacher_replies.assert_called_once()
    assert fakes["reads"].recent_teacher_replies.call_args.args[0] == STUDENT


def test_home_reads_only_the_callers_own_data(tmp_path: Path, fakes: dict[str, MagicMock]) -> None:
    _client(HistoryStore(tmp_path / "h"), fakes).get("/api/student/home")
    fakes["xp"].streak.assert_called_once()
    assert fakes["xp"].streak.call_args.args[0] == STUDENT
    assert fakes["quizzes"].list_assigned.call_args.args[0] == STUDENT
    assert fakes["uploads"].get_active_run.call_args.kwargs == {"user_id": str(STUDENT)}
    assert fakes["classes"].enrolled_class_ids.call_args.args[0] == STUDENT


def test_home_for_a_new_student_never_builds_the_boundary_store(
    tmp_path: Path, fakes: dict[str, MagicMock], monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse() -> None:
        raise AssertionError("built the boundary store with nothing to grade")

    monkeypatch.setattr("lemely.web.routers.student_home.GradeBoundaryStore", refuse)
    response = _client(HistoryStore(tmp_path / "empty"), fakes).get("/api/student/home")
    assert response.status_code == 200, response.text
    assert response.json()["floor"] == []


def test_home_marking_moment_from_the_active_run(tmp_path: Path, fakes: dict[str, MagicMock]) -> None:
    fakes["uploads"].get_active_run.return_value = MagicMock(
        id=uuid.uuid4(), status=UploadStatus.processing, original_filename="p.pdf", started_at=NOW
    )
    body = _client(HistoryStore(tmp_path / "h"), fakes).get("/api/student/home").json()
    assert body["moments"][0]["kind"] == "marking"


def test_home_with_a_malformed_id_returns_neutral_200(
    tmp_path: Path, fakes: dict[str, MagicMock]
) -> None:
    response = _client(HistoryStore(tmp_path / "h"), fakes, user_id="maya").get("/api/student/home")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["moments"] == []
    assert body["classCount"] == 0
    fakes["xp"].streak.assert_not_called()
```

The marking test passes the real `UploadStatus.processing` enum because `_run_dto` compares with `is`.

- [ ] **Step 2: Run them to verify they fail**

Run: `PYTHONPATH="$(git rev-parse --show-toplevel)" pytest tests/test_student_home_route.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'lemely.web.routers.student_home'`.

- [ ] **Step 3: Write the router**

```python
"""``GET /api/student/home``: the student Home hub and Me stats (redesign lane L1).

Gathers inputs from the services that already own them (history, XP and streak,
study plans, exam calendar, assigned quizzes, the active upload, classes, and
one new student-scoped read for teacher replies) and hands them to the pure
builders in :mod:`lemely.web.services.student_home`. Nothing here decides what
the student sees; the client's view model picks the stage moment.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, Depends

from lemely.auth.mirror import UserMirror
from lemely.core.history import HistoryStoreProtocol, is_grade_bearing
from lemely.core.schemas import ExamMetadata
from lemely.db.class_repo import ClassService
from lemely.db.exam_calendar_repo import ExamCalendarService
from lemely.db.models.enums import Role, XpSource
from lemely.db.quiz_taking_repo import QuizTakingService
from lemely.db.session import get_sessionmaker
from lemely.db.student_home_repo import StudentHomeReads
from lemely.db.student_profile_repo import StudentProfileService
from lemely.db.study_plan_repo import SessionView, StudyPlanService
from lemely.db.upload_repo import StudentUploadRepository
from lemely.db.xp_repo import StreakState, UserZoneReader, XpBreakdown, XpService, week_bounds
from lemely.io.grade_boundaries import GradeBoundaryStore
from lemely.web.deps import (
    AuthContext,
    get_class_service,
    get_exam_calendar_service,
    get_history_store,
    get_quiz_taking_service,
    get_settings,
    get_student_profile_service,
    get_student_upload_repo,
    get_study_plan_service,
    get_user_mirror,
    get_user_zone_reader,
    get_xp_service,
    require_role,
)
from lemely.web.routers.student import _run_dto
from lemely.web.schemas_student_home import StudentHomeDTO
from lemely.web.services.student_home import REPLY_WINDOW, HomeInputs, build_home

router = APIRouter(prefix="/api/student", tags=["student-home"])

_EMPTY_STREAK = StreakState(
    current_length=0, longest_length=0, last_active_on=None, freezes_available=0
)


def _now() -> datetime:
    return datetime.now(UTC)


def _empty_breakdown() -> XpBreakdown:
    return XpBreakdown(total=0, by_source=dict.fromkeys(XpSource, 0))


def _student_uuid(user_id: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(user_id)
    except ValueError:
        return None


@lru_cache(maxsize=1)
def get_student_home_reads() -> StudentHomeReads:
    """Process-wide :class:`StudentHomeReads`; tests override it."""
    return StudentHomeReads(get_sessionmaker(get_settings()))


@router.get("/home", response_model=StudentHomeDTO)
def student_home(
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    history_store: Annotated[HistoryStoreProtocol, Depends(get_history_store)],
    mirror: Annotated[UserMirror, Depends(get_user_mirror)],
    profile_service: Annotated[StudentProfileService, Depends(get_student_profile_service)],
    xp_service: Annotated[XpService, Depends(get_xp_service)],
    zones: Annotated[UserZoneReader, Depends(get_user_zone_reader)],
    study_plans: Annotated[StudyPlanService, Depends(get_study_plan_service)],
    exam_calendar: Annotated[ExamCalendarService, Depends(get_exam_calendar_service)],
    quizzes: Annotated[QuizTakingService, Depends(get_quiz_taking_service)],
    uploads: Annotated[StudentUploadRepository, Depends(get_student_upload_repo)],
    classes: Annotated[ClassService, Depends(get_class_service)],
    reads: Annotated[StudentHomeReads, Depends(get_student_home_reads)],
) -> StudentHomeDTO:
    """Return everything the Home hub and the Me screen's stats need, in one read."""
    now = _now()
    records = history_store.load(auth.user_id).records

    store: list[GradeBoundaryStore] = []

    def boundaries_for(metadata: ExamMetadata) -> dict[str, float]:
        if not store:
            store.append(GradeBoundaryStore())
        return store[0].resolve(metadata)[0]

    student = _student_uuid(auth.user_id)
    if student is None:
        week_start, _ = week_bounds(now.date())
        inputs = HomeInputs(
            student_name="",
            records=records,
            now=now,
            local_date=now.date(),
            local_hour=now.hour,
            week_start=week_start,
            streak=_EMPTY_STREAK,
            today_xp=_empty_breakdown(),
            week_xp=_empty_breakdown(),
            week_xp_by_day={},
            sessions=[],
            calendar=None,
            assigned=[],
            active_run=None,
            teacher_replies=[],
            class_count=0,
        )
        return build_home(inputs, boundaries_for)

    local = now.astimezone(zones.zone_for(student))
    local_date = local.date()
    week_start, week_end = week_bounds(local_date)

    try:
        enrolled_codes = {e.subject_code for e in profile_service.list_enrolments(auth.user_id)}
    except ValueError:
        enrolled_codes = set()
    paper_codes = {r.metadata.subject_code for r in records if is_grade_bearing(r)}
    sessions: list[SessionView] = []
    for code in sorted(enrolled_codes | paper_codes):
        plan = study_plans.get_current(student, code, now=now)
        if plan is not None:
            sessions.extend(plan.sessions)

    user = mirror.get_by_id(student)
    run = uploads.get_active_run(user_id=auth.user_id)

    inputs = HomeInputs(
        student_name=(user.display_name or user.email) if user is not None else "",
        records=records,
        now=now,
        local_date=local_date,
        local_hour=local.hour,
        week_start=week_start,
        streak=xp_service.streak(student, now=now),
        today_xp=xp_service.xp_breakdown(student, start=local_date, end=local_date),
        week_xp=xp_service.xp_breakdown(student, start=week_start, end=week_end),
        week_xp_by_day=xp_service.xp_by_day(student, start=week_start, end=week_end),
        sessions=sessions,
        calendar=exam_calendar.calendar_for_student(student),
        assigned=quizzes.list_assigned(student),
        active_run=_run_dto(run, now=now) if run is not None else None,
        teacher_replies=reads.recent_teacher_replies(student, since=now - REPLY_WINDOW),
        class_count=len(classes.enrolled_class_ids(student)),
    )
    return build_home(inputs, boundaries_for)
```

If ruff `TCH` asks to move a dependency type into `TYPE_CHECKING`, keep it at runtime and add `# noqa: TC001`/`TC002`/`TC003` as `lemely/web/deps_tutoring.py:23-36` does, because FastAPI reads these annotations at runtime.

- [ ] **Step 4: Register the router**

In `lemely/web/app.py`, add `student_home,` to the `from lemely.web.routers import (...)` list right after `student,` (line 57), and add this line directly after `app.include_router(student.router)` (line 224):

```python
    app.include_router(student_home.router)
```

- [ ] **Step 5: Add the authz matrix row**

In `tests/test_authz_matrix_complete.py`, add directly after `("GET", "/api/student/overview"): STUDENT,` (line 477):

```python
    ("GET", "/api/student/home"): STUDENT,
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `PYTHONPATH="$(git rev-parse --show-toplevel)" pytest tests/test_student_home_route.py tests/test_student_home_service.py tests/test_authz_matrix_complete.py -v`
Expected: all pass. `test_authz_matrix_complete.py` proves the route answers 401 unauthenticated and 403 to teacher, parent, school_admin, platform_admin and tutor.

- [ ] **Step 7: Lint, then commit**

```bash
pre-commit run --files lemely/web/routers/student_home.py lemely/web/app.py tests/test_student_home_route.py tests/test_authz_matrix_complete.py
git commit -S -m "feat(home): add GET /api/student/home" -- lemely/web/routers/student_home.py lemely/web/app.py tests/test_student_home_route.py tests/test_authz_matrix_complete.py
```

Also run the import-layer gate once, since a new router imports from another router: `lint-imports`. Expected: all contracts kept.

---

## Task 5: Wire types, API function and query hook

**Files:**
- Create: `web/src/lib/studentHomeTypes.ts`
- Create: `web/src/lib/studentHomeApi.ts`
- Create: `web/src/lib/hooks/useStudentHomeApi.ts`
- Test: `web/tests/unit/studentHomeApi.test.ts`

**Interfaces:**
- Consumes: `request<T>(path)` from `web/src/lib/api.ts:265`.
- Produces: every type below (exact names), `STUDENT_HOME_PATH = "/student/home"`, `fetchStudentHome(): Promise<StudentHome>`, `STUDENT_HOME_KEY = ["student", "home"] as const`, `MARKING_POLL_MS = 5_000`, `homeRefetchInterval(data: StudentHome | undefined): number | false`, `useStudentHome(): UseQueryResult<StudentHome, Error>`.

- [ ] **Step 1: Write the types**

```ts
/*
 * Wire types for `GET /api/student/home` (lane L1). Mirrors
 * `lemely/web/schemas_student_home.py` field for field. Dates are ISO strings:
 * `YYYY-MM-DD` for `date`, full ISO-8601 for `datetime`.
 */

export interface MarkingMoment {
  kind: "marking"
  paperId: string
  filename: string | null
  startedAt: string | null
  stale: boolean
  questionsDone: number | null
  questionsTotal: number | null
}

export interface PaperMoment {
  kind: "result" | "tough"
  paperId: string
  subjectCode: string
  subjectName: string
  paperNumber: number
  awarded: number
  maximum: number
  grade: string
  previousGrade: string | null
  focusQuestion: string | null
  recordedAt: string
}

export interface TeacherReply {
  reviewId: string
  teacherName: string
  questionId: string
  subjectCode: string | null
  subjectName: string | null
  paperNumber: number | null
  marksAdded: number
  /** History index for `/student/result/:paperId`; `null` when the paper is not in history. */
  paperId: string | null
  resolvedAt: string
}

export interface TeacherReplyMoment {
  kind: "teacherReply"
  reply: TeacherReply
}

export interface StreakMoment {
  kind: "streakAtRisk" | "goalDone"
  streakDays: number
}

export interface BackMoment {
  kind: "backAfterBreak"
  daysAway: number
}

export type HomeMoment = MarkingMoment | PaperMoment | TeacherReplyMoment | StreakMoment | BackMoment
export type HomeMomentKind = HomeMoment["kind"]

export interface HomeGoals {
  practice: boolean
  flashcards: boolean
  paperThisWeek: boolean
}

export interface PlanSession {
  sessionId: string
  subjectCode: string
  topic: string
  minutes: number
  done: boolean
}

export interface WeekDay {
  day: string
  label: string | null
  done: boolean
  isToday: boolean
}

export interface HomeStreak {
  current: number
  longest: number
  lastActiveOn: string | null
  freezesAvailable: number
}

export interface FloorSubject {
  code: string
  name: string
  grade: string
  previousGrade: string | null
  nextGrade: string | null
  pointsToNext: number | null
  papers: number
}

export interface WinBackTopic {
  topic: string
  subjectCode: string
  subjectName: string
  marks: number
}

export interface RecentPaper {
  paperId: string
  subjectCode: string
  subjectName: string
  paperNumber: number
  awarded: number
  maximum: number
  grade: string
  recordedAt: string
}

export interface Homework {
  assignmentId: string
  title: string
  subjectCode: string
  teacherName: string
  dueAt: string | null
  questionCount: number
  isOverdue: boolean
}

export interface HomeStats {
  papersMarked: number
  marksWonBack: number
  bestGrade: { grade: string; subjectCode: string } | null
}

export interface HomeActivity {
  kind: "paper" | "practice" | "teacher"
  title: string
  sub: string
  at: string
}

export interface StudentHome {
  studentName: string
  localDate: string
  localHour: number
  moments: HomeMoment[]
  goals: HomeGoals
  todaySessions: PlanSession[]
  week: WeekDay[]
  streak: HomeStreak
  nextExamOn: string | null
  floor: FloorSubject[]
  winBack: WinBackTopic[]
  recentPapers: RecentPaper[]
  lastPaperAt: string | null
  teacherReplies: TeacherReply[]
  homework: Homework[]
  classCount: number
  stats: HomeStats
  activity: HomeActivity[]
}
```

- [ ] **Step 2: Write the failing test**

```ts
import { beforeEach, describe, expect, it, vi } from "vitest"

const request = vi.fn()
vi.mock("@/lib/api", () => ({ request: (...args: unknown[]) => request(...args) }))

import { fetchStudentHome, STUDENT_HOME_PATH } from "@/lib/studentHomeApi"
import { homeRefetchInterval, MARKING_POLL_MS, STUDENT_HOME_KEY } from "@/lib/hooks/useStudentHomeApi"
import { makeHome } from "./studentHomeFixture"

describe("student home API", () => {
  beforeEach(() => request.mockReset())

  it("reads GET /student/home", async () => {
    request.mockResolvedValue(makeHome())
    await fetchStudentHome()
    expect(request).toHaveBeenCalledWith(STUDENT_HOME_PATH)
    expect(STUDENT_HOME_PATH).toBe("/student/home")
  })

  it("keys the query under student/home", () => {
    expect(STUDENT_HOME_KEY).toEqual(["student", "home"])
  })

  it("polls only while a paper is marking", () => {
    expect(homeRefetchInterval(undefined)).toBe(false)
    expect(homeRefetchInterval(makeHome())).toBe(false)
    const marking = makeHome({
      moments: [
        { kind: "marking", paperId: "u1", filename: null, startedAt: null, stale: false, questionsDone: null, questionsTotal: null },
      ],
    })
    expect(homeRefetchInterval(marking)).toBe(MARKING_POLL_MS)
  })
})
```

Also create the shared fixture builder `web/tests/unit/studentHomeFixture.ts` (not a test file; Vitest only runs `*.test.ts`):

```ts
import type { StudentHome } from "@/lib/studentHomeTypes"

/** A loaded Home for a student with three subjects, mirroring the mock's Mariam. */
export function makeHome(overrides: Partial<StudentHome> = {}): StudentHome {
  return {
    studentName: "Mariam Adel",
    localDate: "2026-11-12",
    localHour: 9,
    moments: [],
    goals: { practice: false, flashcards: false, paperThisWeek: false },
    todaySessions: [],
    week: [
      { day: "2026-11-09", label: "Vectors", done: true, isToday: false },
      { day: "2026-11-10", label: "Waves", done: true, isToday: false },
      { day: "2026-11-11", label: "Flashcards", done: true, isToday: false },
      { day: "2026-11-12", label: "Vectors", done: false, isToday: true },
      { day: "2026-11-13", label: "Paper 4", done: false, isToday: false },
      { day: "2026-11-14", label: null, done: false, isToday: false },
      { day: "2026-11-15", label: null, done: false, isToday: false },
    ],
    streak: { current: 9, longest: 14, lastActiveOn: "2026-11-11", freezesAvailable: 0 },
    nextExamOn: "2027-05-11",
    floor: [
      { code: "0580", name: "Mathematics", grade: "B", previousGrade: "C", nextGrade: "A", pointsToNext: 4, papers: 3 },
      { code: "0625", name: "Physics", grade: "C", previousGrade: null, nextGrade: "B", pointsToNext: 6, papers: 1 },
      { code: "0606", name: "Additional Mathematics", grade: "B", previousGrade: "B", nextGrade: "A", pointsToNext: 9, papers: 2 },
    ],
    winBack: [
      { topic: "Vectors", subjectCode: "0580", subjectName: "Mathematics", marks: 9 },
      { topic: "Waves", subjectCode: "0625", subjectName: "Physics", marks: 7 },
      { topic: "Quadratic inequalities", subjectCode: "0606", subjectName: "Additional Mathematics", marks: 6 },
    ],
    recentPapers: [
      { paperId: "5", subjectCode: "0580", subjectName: "Mathematics", paperNumber: 4, awarded: 61, maximum: 80, grade: "B", recordedAt: "2026-11-10T10:00:00+00:00" },
      { paperId: "3", subjectCode: "0625", subjectName: "Physics", paperNumber: 6, awarded: 27, maximum: 40, grade: "C", recordedAt: "2026-11-04T10:00:00+00:00" },
      { paperId: "1", subjectCode: "0606", subjectName: "Additional Mathematics", paperNumber: 2, awarded: 52, maximum: 80, grade: "B", recordedAt: "2026-10-29T10:00:00+00:00" },
    ],
    lastPaperAt: "2026-11-10T10:00:00+00:00",
    teacherReplies: [
      { reviewId: "r1", teacherName: "Ms. Hanna", questionId: "7", subjectCode: "0580", subjectName: "Mathematics", paperNumber: 4, marksAdded: 1, paperId: "5", resolvedAt: "2026-11-11T12:00:00+00:00" },
    ],
    homework: [
      { assignmentId: "a1", title: "Trigonometry set", subjectCode: "0580", teacherName: "Ms. Hanna", dueAt: "2026-11-13T15:00:00+00:00", questionCount: 12, isOverdue: false },
    ],
    classCount: 2,
    stats: { papersMarked: 22, marksWonBack: 64, bestGrade: { grade: "A", subjectCode: "0580" } },
    activity: [],
    ...overrides,
  }
}
```

- [ ] **Step 3: Run it to verify it fails**

Run: `cd web && npx vitest run tests/unit/studentHomeApi.test.ts`
Expected: FAIL, cannot resolve `@/lib/studentHomeApi`.

- [ ] **Step 4: Write the API function and the hook**

`web/src/lib/studentHomeApi.ts`:

```ts
import { request } from "@/lib/api"
import type { StudentHome } from "@/lib/studentHomeTypes"

// L1 · student Home hub (`lemely/web/routers/student_home.py`).
export const STUDENT_HOME_PATH = "/student/home"

/** No `fallback`: a failed read must surface as an error the screen renders. */
export function fetchStudentHome(): Promise<StudentHome> {
  return request<StudentHome>(STUDENT_HOME_PATH)
}
```

`web/src/lib/hooks/useStudentHomeApi.ts`:

```ts
import { useQuery, type UseQueryResult } from "@tanstack/react-query"
import { fetchStudentHome } from "@/lib/studentHomeApi"
import type { StudentHome } from "@/lib/studentHomeTypes"

export const STUDENT_HOME_KEY = ["student", "home"] as const

/** While a paper is marking, Home re-reads every 5s so the stage moves on by itself. */
export const MARKING_POLL_MS = 5_000

export function homeRefetchInterval(data: StudentHome | undefined): number | false {
  return data?.moments.some((m) => m.kind === "marking") ? MARKING_POLL_MS : false
}

export function useStudentHome(): UseQueryResult<StudentHome, Error> {
  return useQuery({
    queryKey: STUDENT_HOME_KEY,
    queryFn: fetchStudentHome,
    refetchInterval: (query) => homeRefetchInterval(query.state.data),
  })
}
```

- [ ] **Step 5: Run it to verify it passes**

Run: `cd web && npx vitest run tests/unit/studentHomeApi.test.ts`
Expected: 3 passed.

- [ ] **Step 6: Typecheck, lint, commit**

```bash
cd web && npx tsc -b --noEmit && npx oxlint src/lib/studentHomeTypes.ts src/lib/studentHomeApi.ts src/lib/hooks/useStudentHomeApi.ts && cd ..
pre-commit run --files web/src/lib/studentHomeTypes.ts web/src/lib/studentHomeApi.ts web/src/lib/hooks/useStudentHomeApi.ts web/tests/unit/studentHomeApi.test.ts web/tests/unit/studentHomeFixture.ts
git commit -S -m "feat(web): add the student home API and query hook" -- web/src/lib/studentHomeTypes.ts web/src/lib/studentHomeApi.ts web/src/lib/hooks/useStudentHomeApi.ts web/tests/unit/studentHomeApi.test.ts web/tests/unit/studentHomeFixture.ts
```

---

## Task 6: Home view model, door routes and "Not now" memory

**Files:**
- Create: `web/src/portals/student/home/routes.ts`
- Create: `web/src/portals/student/home/dismiss.ts`
- Replace: `web/src/portals/student/home/model.ts` (whole file)
- Replace: `web/tests/unit/studentHomeModel.test.ts` (whole file)
- Test: `web/tests/unit/studentHomeRoutes.test.ts`, `web/tests/unit/studentHomeDismiss.test.ts`

**Interfaces:**
- Consumes: Task 5 types; F1 types `BinnyMood`, `BinnyMotion` (type-only import from `@/components/redesign`, erased at runtime so the node test never loads React).
- Produces:
  - `homeRoutes` object (keys below), `practiceTarget(home)`, `planTarget(home)`.
  - `readDismissed(storage, day): Set<string>`, `writeDismissed(storage, day, keys)`, `safeLocalStorage(): Storage | null`, `DISMISS_KEY`.
  - Model: `EXAM_NEAR_DAYS`, `STAGE_PRIORITY`, `parseDay`, `daysBetween`, `firstName`, `shortGreeting`, `questionLabel`, `shortSubject`, `initials`, `relativeDay`, `isFirstRun`, `examInfo`, `stageCandidates`, `pickStage`, `alsoRows`, `todayVm`, `weekVm`, `floorVm`, `lastPaperVm`, `winVm`, `streakPillVm`, `bandVm`, `homeView`; types `StageKind`, `StageVm`, `RowVm`, `RowLeading`, `HomeVm`.

Note: the old `model.ts` exports (`deriveNextAction`, `todayList`, `binnyMood`, `streakStrip`, `localISODate`, `GRADE_ORDER`) are only read by `web/dev-previews/student-home/*` and `web/tests/unit/studentHomeFixtures.test.ts`, both deleted in Task 13. Delete those two consumers in this task's commit if `tsc -b` fails on them (it will, because the old exports are gone): move the Task 13 deletion of `web/dev-previews/student-home/`, the four `student-home*.html` files, their `web/vite.preview.config.ts:55-58` entries and `web/tests/unit/studentHomeFixtures.test.ts` into this commit.

- [ ] **Step 1: Write the routes module and its failing test**

`web/src/portals/student/home/routes.ts`:

```ts
import type { StudentHome } from "@/lib/studentHomeTypes"

/*
 * Every door Home and Me open, in one place. Routes that do not exist yet
 * (the Practice tab root from L4, the all-subjects week from L9) fall back to
 * the per-subject routes that exist today. When L4 and L9 merge, only this
 * file changes.
 */
export const homeRoutes = {
  scan: "/student/correct",
  me: "/student/profile",
  subject: (code: string) => `/student/subject/${code}`,
  result: (paperId: string, filter?: "lost") =>
    filter ? `/student/result/${paperId}?q=${filter}` : `/student/result/${paperId}`,
  practice: (code: string) => `/student/practice/${code}`,
  practiceTopic: (code: string, topic: string) =>
    `/student/practice/${code}?topic=${encodeURIComponent(topic)}`,
  practiceSet: (assignmentId: string) => `/student/practice/set/${assignmentId}`,
  flashcards: (code: string) => `/student/flashcards/${code}`,
  plan: (code: string) => `/student/plan/${code}`,
  session: (code: string, sessionId: string) => `/student/plan/${code}/session/${sessionId}`,
  classes: "/student/classes",
  standings: "/student/board",
  friends: "/student/friends",
  parents: "/student/parents",
  tutoring: "/student/tutors",
  placement: (code: string) => `/student/placement/${code}`,
  settings: "/student/settings",
  notifications: "/student/notifications",
  recentlyDeleted: "/student/recently-deleted",
} as const

/** Where "practice" goes: the top topic to win back, else the first subject, else scan. */
export function practiceTarget(home: StudentHome): string {
  const top = home.winBack[0]
  if (top) return homeRoutes.practiceTopic(top.subjectCode, top.topic)
  const first = home.floor[0]
  return first ? homeRoutes.practice(first.code) : homeRoutes.scan
}

/** The subject whose plan Home opens: today's first session, else the first subject. */
export function planSubject(home: StudentHome): string | null {
  return home.todaySessions[0]?.subjectCode ?? home.floor[0]?.code ?? null
}

export function planTarget(home: StudentHome): string {
  const code = planSubject(home)
  return code ? homeRoutes.plan(code) : homeRoutes.scan
}

export function flashcardsTarget(home: StudentHome): string {
  const code = home.winBack[0]?.subjectCode ?? home.floor[0]?.code
  return code ? homeRoutes.flashcards(code) : homeRoutes.scan
}
```

`web/tests/unit/studentHomeRoutes.test.ts`:

```ts
import { describe, expect, it } from "vitest"
import { flashcardsTarget, homeRoutes, planTarget, practiceTarget } from "@/portals/student/home/routes"
import { makeHome } from "./studentHomeFixture"

describe("home routes", () => {
  it("builds result links with the lost filter PaperResult already reads", () => {
    expect(homeRoutes.result("5")).toBe("/student/result/5")
    expect(homeRoutes.result("5", "lost")).toBe("/student/result/5?q=lost")
  })

  it("encodes the topic on practice links", () => {
    expect(homeRoutes.practiceTopic("0606", "Quadratic inequalities")).toBe(
      "/student/practice/0606?topic=Quadratic%20inequalities",
    )
  })

  it("sends practice to the top topic, then the first subject, then scan", () => {
    expect(practiceTarget(makeHome())).toBe("/student/practice/0580?topic=Vectors")
    expect(practiceTarget(makeHome({ winBack: [] }))).toBe("/student/practice/0580")
    expect(practiceTarget(makeHome({ winBack: [], floor: [] }))).toBe("/student/correct")
  })

  it("opens the plan of today's session subject first", () => {
    const home = makeHome({
      todaySessions: [{ sessionId: "s1", subjectCode: "0625", topic: "Waves", minutes: 10, done: false }],
    })
    expect(planTarget(home)).toBe("/student/plan/0625")
    expect(planTarget(makeHome())).toBe("/student/plan/0580")
    expect(planTarget(makeHome({ floor: [] }))).toBe("/student/correct")
  })

  it("opens flashcards for the top topic's subject", () => {
    expect(flashcardsTarget(makeHome())).toBe("/student/flashcards/0580")
  })
})
```

- [ ] **Step 2: Write the dismiss module and its failing test**

`web/src/portals/student/home/dismiss.ts`:

```ts
/*
 * "Not now" memory. A per-viewer convenience, so browser storage is right:
 * it may come back empty (private window, cleared data) and Home still works,
 * Binny just suggests the same thing again. Keys reset each new local day.
 */
export const DISMISS_KEY = "lemely.home.notNow"

type Reader = Pick<Storage, "getItem">
type Writer = Pick<Storage, "setItem">

export function safeLocalStorage(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage
  } catch {
    return null
  }
}

export function readDismissed(storage: Reader | null, day: string): Set<string> {
  if (!storage) return new Set()
  try {
    const raw = storage.getItem(DISMISS_KEY)
    if (!raw) return new Set()
    const parsed = JSON.parse(raw) as { day?: unknown; keys?: unknown }
    if (parsed.day !== day || !Array.isArray(parsed.keys)) return new Set()
    return new Set(parsed.keys.filter((k): k is string => typeof k === "string"))
  } catch {
    return new Set()
  }
}

export function writeDismissed(storage: Writer | null, day: string, keys: ReadonlySet<string>): void {
  if (!storage) return
  try {
    storage.setItem(DISMISS_KEY, JSON.stringify({ day, keys: [...keys] }))
  } catch {
    // Storage full or blocked: the dismissal lasts until the page reloads.
  }
}
```

`web/tests/unit/studentHomeDismiss.test.ts`:

```ts
import { describe, expect, it } from "vitest"
import { DISMISS_KEY, readDismissed, writeDismissed } from "@/portals/student/home/dismiss"

function memory(): Storage {
  const map = new Map<string, string>()
  return {
    get length() {
      return map.size
    },
    clear: () => map.clear(),
    getItem: (k) => map.get(k) ?? null,
    key: (i) => [...map.keys()][i] ?? null,
    removeItem: (k) => void map.delete(k),
    setItem: (k, v) => void map.set(k, v),
  }
}

describe("Not now memory", () => {
  it("round-trips keys for the same day", () => {
    const s = memory()
    writeDismissed(s, "2026-11-12", new Set(["result:5"]))
    expect([...readDismissed(s, "2026-11-12")]).toEqual(["result:5"])
  })

  it("forgets everything on a new day", () => {
    const s = memory()
    writeDismissed(s, "2026-11-12", new Set(["result:5"]))
    expect(readDismissed(s, "2026-11-13").size).toBe(0)
  })

  it("survives missing, corrupt or throwing storage", () => {
    expect(readDismissed(null, "d").size).toBe(0)
    const s = memory()
    s.setItem(DISMISS_KEY, "{not json")
    expect(readDismissed(s, "d").size).toBe(0)
    const throwing = { getItem: () => { throw new Error("blocked") }, setItem: () => { throw new Error("blocked") } }
    expect(readDismissed(throwing, "d").size).toBe(0)
    expect(() => writeDismissed(throwing, "d", new Set(["x"]))).not.toThrow()
  })
})
```

- [ ] **Step 3: Write the failing model test (replaces the old file entirely)**

`web/tests/unit/studentHomeModel.test.ts`:

```ts
import { describe, expect, it } from "vitest"
import {
  alsoRows,
  bandVm,
  daysBetween,
  examInfo,
  firstName,
  floorVm,
  homeView,
  initials,
  isFirstRun,
  lastPaperVm,
  pickStage,
  questionLabel,
  relativeDay,
  shortGreeting,
  shortSubject,
  stageCandidates,
  streakPillVm,
  todayVm,
  weekVm,
  winVm,
} from "@/portals/student/home/model"
import type { HomeMoment } from "@/lib/studentHomeTypes"
import { makeHome } from "./studentHomeFixture"

const NONE: ReadonlySet<string> = new Set()
const result: HomeMoment = {
  kind: "result", paperId: "5", subjectCode: "0580", subjectName: "Mathematics", paperNumber: 4,
  awarded: 61, maximum: 80, grade: "B", previousGrade: "C", focusQuestion: "8", recordedAt: "2026-11-12T07:00:00+00:00",
}
const tough: HomeMoment = { ...result, kind: "tough", subjectCode: "0625", subjectName: "Physics", grade: "D", previousGrade: null, focusQuestion: "3" }
const marking: HomeMoment = { kind: "marking", paperId: "u1", filename: null, startedAt: null, stale: false, questionsDone: 8, questionsTotal: 14 }
const streak: HomeMoment = { kind: "streakAtRisk", streakDays: 9 }
const done: HomeMoment = { kind: "goalDone", streakDays: 10 }
const back: HomeMoment = { kind: "backAfterBreak", daysAway: 6 }
const reply: HomeMoment = { kind: "teacherReply", reply: makeHome().teacherReplies[0] }

describe("small helpers", () => {
  it("names and greetings", () => {
    expect(firstName("Mariam Adel")).toBe("Mariam")
    expect(firstName("m.adel@example.com")).toBe("m.adel")
    expect(firstName("  ")).toBe("there")
    expect(shortGreeting(9)).toBe("Morning")
    expect(shortGreeting(14)).toBe("Afternoon")
    expect(shortGreeting(23)).toBe("Evening")
    expect(shortGreeting(3)).toBe("Evening")
  })

  it("labels", () => {
    expect(questionLabel("8")).toBe("Q8")
    expect(questionLabel("Q4b")).toBe("Q4b")
    expect(shortSubject("Additional Mathematics")).toBe("Add Maths")
    expect(shortSubject("Mathematics")).toBe("Mathematics")
    expect(initials("Ms. Hanna")).toBe("MH")
    expect(initials("Hanna")).toBe("H")
  })

  it("days and relative days", () => {
    expect(daysBetween("2026-11-12", "2026-12-12")).toBe(30)
    expect(relativeDay("2026-11-12T08:00:00", "2026-11-12")).toBe("today")
    expect(relativeDay("2026-11-11T08:00:00", "2026-11-12")).toBe("yesterday")
    expect(relativeDay("2026-11-10T08:00:00", "2026-11-12")).toBe("2 days ago")
    expect(relativeDay("2026-11-03T08:00:00", "2026-11-12")).toBe("last week")
    expect(relativeDay("2026-10-20T08:00:00", "2026-11-12")).toBe("3 weeks ago")
  })

  it("exam info turns near inside 30 days", () => {
    expect(examInfo(makeHome({ nextExamOn: null }))).toBeNull()
    expect(examInfo(makeHome({ nextExamOn: "2026-12-12" }))).toEqual({ date: "2026-12-12", days: 30, near: true })
    expect(examInfo(makeHome({ nextExamOn: "2026-12-13" }))?.near).toBe(false)
  })
})

describe("stage", () => {
  it("follows the priority order", () => {
    const home = makeHome({ moments: [back, done, streak, reply, tough, marking] })
    expect(stageCandidates(home).map((s) => s.kind).slice(0, 6)).toEqual([
      "marking", "tough", "teacherReply", "streakAtRisk", "goalDone", "backAfterBreak",
    ])
  })

  it("result: happy hop, names the question to fix", () => {
    const s = pickStage(makeHome({ moments: [result] }), NONE)
    expect(s).toMatchObject({ kind: "result", mood: "happy", motion: "hop", dismissible: true })
    expect(s.line).toBe("61 out of 80. That's a B, up from a C. Q8 is the one to fix.")
    expect(s.action).toEqual({ label: "Fix Q8", to: "/student/result/5?q=lost" })
    const anA = pickStage(makeHome({ moments: [{ ...result, grade: "A", previousGrade: "E" } as HomeMoment] }), NONE)
    expect(anA.line).toBe("61 out of 80. That's an A, up from an E. Q8 is the one to fix.")
  })

  it("tough: sad, easiest question first", () => {
    const s = pickStage(makeHome({ moments: [tough] }), NONE)
    expect(s.mood).toBe("sad")
    expect(s.line).toBe("Physics Paper 4 was a tough one. Let's win back the easy marks first.")
    expect(s.action.label).toBe("Start with Q3")
  })

  it("marking: thinking, never dismissible, shows progress when known", () => {
    const s = pickStage(makeHome({ moments: [marking] }), new Set(["marking:u1"]))
    expect(s).toMatchObject({ kind: "marking", mood: "thinking", dismissible: false })
    expect(s.line).toBe("Marking your paper. 8 of 14 questions done.")
    expect(s.action).toEqual({ label: "Watch it mark", to: "/student/correct" })
  })

  it("streak, goal done, back after a break", () => {
    expect(pickStage(makeHome({ moments: [streak] }), NONE)).toMatchObject({
      mood: "thinking",
      line: "Your 9-day streak ends at midnight. One quick set keeps it going.",
      action: { label: "Keep my streak", to: "/student/practice/0580?topic=Vectors" },
    })
    expect(pickStage(makeHome({ moments: [done] }), NONE)).toMatchObject({
      mood: "happy",
      line: "Three for three today. That's you done. See you tomorrow.",
      action: { label: "See tomorrow's plan", to: "/student/plan/0580" },
    })
    expect(pickStage(makeHome({ moments: [back] }), NONE)).toMatchObject({
      mood: "wink",
      line: "There you are. 6 days off is fine. Ease back in with five minutes.",
      action: { label: "5-minute warm-up" },
    })
  })

  it("teacher reply: wink, links the result", () => {
    const s = pickStage(makeHome({ moments: [reply] }), NONE)
    expect(s.line).toBe("Ms. Hanna checked your Q7. +1 mark.")
    expect(s.action).toEqual({ label: "See the answer", to: "/student/result/5" })
  })

  it("falls back to today's session, then the top topic (morning), then scan", () => {
    const withSession = makeHome({
      todaySessions: [{ sessionId: "s1", subjectCode: "0625", topic: "Waves", minutes: 15, done: false }],
      nextExamOn: null,
    })
    expect(pickStage(withSession, NONE)).toMatchObject({
      kind: "session",
      line: "Today's plan: Waves, 15 minutes.",
      action: { label: "Start", to: "/student/plan/0625/session/s1" },
    })
    const morning = pickStage(makeHome({ nextExamOn: null }), NONE)
    expect(morning).toMatchObject({
      kind: "morning",
      mood: "open",
      greeting: "Morning, Mariam.",
      line: "Vectors cost you 9 marks last time. Ten minutes fixes most of it.",
      action: { label: "Start 10 minutes", to: "/student/practice/0580?topic=Vectors" },
    })
    expect(pickStage(makeHome({ nextExamOn: null, localHour: 15 }), NONE).greeting).toBeNull()
    expect(pickStage(makeHome({ winBack: [], nextExamOn: null }), NONE)).toMatchObject({
      kind: "scanNext",
      dismissible: false,
      action: { label: "Scan a paper", to: "/student/correct" },
    })
  })

  it("mentions the exam inside 30 days", () => {
    const s = pickStage(makeHome({ nextExamOn: "2026-11-24" }), NONE)
    expect(s.line).toBe("12 days to exams. Vectors first, +9 marks.")
    expect(s.greeting).toBeNull()
  })

  it("skips dismissed moments and never dismisses the last fallback", () => {
    const home = makeHome({ moments: [result], nextExamOn: null })
    expect(pickStage(home, new Set(["result:5"])).kind).toBe("morning")
    expect(pickStage(home, new Set(["result:5", "morning:0580:Vectors"])).kind).toBe("scanNext")
  })

  it("first run", () => {
    const home = makeHome({ floor: [], recentPapers: [], winBack: [], nextExamOn: null, stats: { papersMarked: 0, marksWonBack: 0, bestGrade: null } })
    expect(isFirstRun(home)).toBe(true)
    expect(pickStage(home, NONE)).toMatchObject({
      kind: "firstRun",
      mood: "open",
      line: "Hi Mariam. Let's mark your first paper.",
      action: { label: "Scan a paper", to: "/student/correct" },
      dismissible: false,
    })
  })
})

describe("rows and blocks", () => {
  it("also rows: result row pairs with a paper stage, two rows at most", () => {
    const home = makeHome({ moments: [result] })
    const rows = alsoRows(home, pickStage(home, NONE), "phone")
    expect(rows.map((r) => r.kind)).toEqual(["result", "teacher"])
    expect(rows[0]).toMatchObject({ title: "See your full result", sub: "Mathematics · Paper 4", to: "/student/result/5", leading: { type: "grade", grade: "B" } })
  })

  it("also rows: morning shows teacher reply and homework on phone, neither on desktop", () => {
    const home = makeHome({ nextExamOn: null })
    const stage = pickStage(home, NONE)
    expect(alsoRows(home, stage, "phone").map((r) => r.kind)).toEqual(["teacher", "homework"])
    expect(alsoRows(home, stage, "desktop")).toEqual([])
    expect(alsoRows(home, stage, "phone")[1]).toMatchObject({
      title: "Trigonometry set from Ms. Hanna",
      sub: "Due tomorrow · 12 questions",
      to: "/student/practice/set/a1",
    })
  })

  it("also rows: join class, sparse nudge, scan nudge", () => {
    const base = makeHome({ teacherReplies: [], homework: [], classCount: 0, nextExamOn: null, lastPaperAt: "2026-11-01T10:00:00+00:00" })
    const kinds = alsoRows(base, pickStage(base, NONE), "phone").map((r) => r.kind)
    expect(kinds).toEqual(["joinClass", "scan"])
    const sparse = makeHome({ teacherReplies: [], homework: [], stats: { papersMarked: 1, marksWonBack: 0, bestGrade: null } })
    expect(alsoRows(sparse, pickStage(sparse, NONE), "phone")[0]).toMatchObject({
      kind: "sparse",
      title: "One more paper draws your trend",
      to: "/student/correct",
    })
  })

  it("today block", () => {
    const vm = todayVm(makeHome({ goals: { practice: true, flashcards: false, paperThisWeek: true } }))
    expect(vm.parts).toEqual([1, 0, 1])
    expect(vm.doneCount).toBe(2)
    expect(vm.label).toBe("2 of 3 today")
    expect(vm.chips.map((c) => [c.label, c.done, c.to])).toEqual([
      ["Practice", true, "/student/practice/0580?topic=Vectors"],
      ["Flashcards", false, "/student/flashcards/0580"],
      ["Paper this week", true, "/student/correct"],
    ])
  })

  it("week strip", () => {
    const days = weekVm(makeHome())
    expect(days.map((d) => d.letter).join("")).toBe("MTWTFSS")
    expect(days[3]).toMatchObject({ isToday: true, done: false, ariaLabel: "Thursday: Vectors" })
    expect(days[0].ariaLabel).toBe("Monday: Vectors, done")
  })

  it("grade floor", () => {
    const floor = floorVm(makeHome())
    expect(floor[2]).toEqual({ code: "0606", name: "Add Maths", grade: "B", sub: "9 pts to A", to: "/student/subject/0606" })
    const top = floorVm(makeHome({ floor: [{ ...makeHome().floor[0], grade: "A*", nextGrade: null, pointsToNext: null }] }))
    expect(top[0].sub).toBe("Top grade")
  })

  it("last paper, win rows, streak pill", () => {
    expect(lastPaperVm(makeHome())).toEqual({
      grade: "B", title: "Last paper · Mathematics P4", sub: "61/80 · 2 days ago", to: "/student/result/5",
    })
    expect(lastPaperVm(makeHome({ recentPapers: [] }))).toBeNull()
    expect(winVm(makeHome(), "morning")).toHaveLength(3)
    expect(winVm(makeHome(), "backAfterBreak")).toHaveLength(1)
    expect(winVm(makeHome(), "morning")[0]).toEqual({ topic: "Vectors", sub: "Mathematics", marks: 9, to: "/student/practice/0580?topic=Vectors" })
    expect(streakPillVm(makeHome())).toEqual({ label: "9 days", lit: false, to: "/student/profile" })
    expect(streakPillVm(makeHome({ goals: { practice: true, flashcards: true, paperThisWeek: true } })).lit).toBe(true)
    expect(streakPillVm(makeHome({ streak: { current: 0, longest: 14, lastActiveOn: null, freezesAvailable: 0 } })).label).toBe("New streak")
    expect(streakPillVm(makeHome({ streak: { current: 0, longest: 0, lastActiveOn: null, freezesAvailable: 0 } })).label).toBe("Start a streak")
    expect(streakPillVm(makeHome({ streak: { current: 1, longest: 1, lastActiveOn: null, freezesAvailable: 0 } })).label).toBe("1 day")
  })

  it("desktop band", () => {
    const band = bandVm(makeHome())
    expect(band.weekNext).toEqual([{ when: "Today", what: "Vectors" }, { when: "Friday", what: "Paper 4" }])
    expect(band.recent).toHaveLength(3)
    expect(band.recent[1]).toMatchObject({ grade: "C", title: "Physics · Paper 6", sub: "27/40 · last week" })
    expect(band.classRows.map((r) => r.kind)).toEqual(["teacher", "homework"])
  })

  it("homeView puts it together", () => {
    const vm = homeView(makeHome({ nextExamOn: null }), NONE)
    expect(vm.firstRun).toBe(false)
    expect(vm.heading).toBe("Morning, Mariam")
    expect(vm.stage.kind).toBe("morning")
    expect(vm.exam).toBeNull()
  })
})
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `cd web && npx vitest run tests/unit/studentHomeModel.test.ts tests/unit/studentHomeRoutes.test.ts tests/unit/studentHomeDismiss.test.ts`
Expected: routes and dismiss PASS after Steps 1–2 files exist; the model test FAILs on missing exports.

- [ ] **Step 5: Write the model (replace the whole file)**

```ts
/*
 * Student Home view model (lane L1). Pure: no React, no fetching, no clock
 * reads. The server's `localDate`/`localHour` are the student's own civil
 * time, so the same payload always renders the same screen. Every decision
 * the Home screen makes lives here: the stage moment, Binny's mood, motion
 * and line, the button and its door, which rows show, and every label.
 *
 * Copy rules (web/scripts/check_copy.mjs): no "!" ending a sentence, no em
 * dash as punctuation. Binny's line is the stage headline from the approved
 * mock (see plan "Needs user decision" item 2).
 */
import type { BinnyMood, BinnyMotion } from "@/components/redesign"
import type {
  HomeMoment,
  HomeMomentKind,
  PaperMoment,
  StudentHome,
} from "@/lib/studentHomeTypes"
import { flashcardsTarget, homeRoutes, planTarget, practiceTarget } from "./routes"

export const EXAM_NEAR_DAYS = 30
export const SCAN_NUDGE_DAYS = 7
const DAY_MS = 86_400_000
const WEEKDAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]

export const STAGE_PRIORITY: readonly HomeMomentKind[] = [
  "marking",
  "result",
  "tough",
  "teacherReply",
  "streakAtRisk",
  "goalDone",
  "backAfterBreak",
]

export type StageKind = HomeMomentKind | "session" | "morning" | "scanNext" | "firstRun"

export interface StageVm {
  /** Stable id for "Not now", e.g. `result:5`. */
  key: string
  kind: StageKind
  mood: BinnyMood
  motion: BinnyMotion
  /** "Morning, Mariam." Shown before the line on phone and tablet only. */
  greeting: string | null
  line: string
  action: { label: string; to: string }
  dismissible: boolean
}

export type RowLeading =
  | { type: "grade"; grade: string }
  | { type: "initials"; text: string }
  | { type: "icon"; icon: "sheet" | "camera" | "class" | "trend" }

export interface RowVm {
  key: string
  kind: "result" | "teacher" | "homework" | "joinClass" | "sparse" | "scan"
  leading: RowLeading
  title: string
  sub: string
  to: string
}

/* ── helpers ──────────────────────────────────────────────────────────── */

export function parseDay(day: string): Date {
  return new Date(`${day}T00:00:00`)
}

function isoDay(d: Date): string {
  const m = String(d.getMonth() + 1).padStart(2, "0")
  const day = String(d.getDate()).padStart(2, "0")
  return `${d.getFullYear()}-${m}-${day}`
}

export function daysBetween(from: string, to: string): number {
  return Math.round((parseDay(to).getTime() - parseDay(from).getTime()) / DAY_MS)
}

export function firstName(name: string): string {
  const trimmed = name.trim()
  if (!trimmed) return "there"
  const base = trimmed.includes("@") ? trimmed.split("@")[0] : trimmed.split(/\s+/)[0]
  return base || "there"
}

export function shortGreeting(hour: number): string {
  if (hour >= 5 && hour < 12) return "Morning"
  if (hour >= 12 && hour < 18) return "Afternoon"
  return "Evening"
}

export function questionLabel(id: string): string {
  return /^q/i.test(id) ? id : `Q${id}`
}

export function shortSubject(name: string): string {
  return name.replace(/^Additional Mathematics$/, "Add Maths").replace(/^Additional /, "Add ")
}

export function initials(name: string): string {
  return name
    .replace(/[^\p{L}\s]/gu, "")
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]!.toUpperCase())
    .join("")
}

function plural(n: number, word: string): string {
  return `${n} ${word}${n === 1 ? "" : "s"}`
}

export function relativeDay(iso: string, localDate: string): string {
  const days = daysBetween(isoDay(new Date(iso)), localDate)
  if (days <= 0) return "today"
  if (days === 1) return "yesterday"
  if (days < 7) return `${days} days ago`
  if (days < 14) return "last week"
  return `${Math.floor(days / 7)} weeks ago`
}

function dueLabel(dueAt: string | null, localDate: string, overdue: boolean): string {
  if (overdue) return "Overdue"
  if (!dueAt) return "No due date"
  const due = new Date(dueAt)
  const days = daysBetween(localDate, isoDay(due))
  if (days <= 0) return "Due today"
  if (days === 1) return "Due tomorrow"
  if (days < 7) return `Due ${WEEKDAYS[due.getDay()]}`
  return `Due ${due.toLocaleDateString("en-GB", { day: "numeric", month: "short" })}`
}

export function isFirstRun(home: StudentHome): boolean {
  return home.floor.length === 0 && home.recentPapers.length === 0
}

export function examInfo(home: StudentHome): { date: string; days: number; near: boolean } | null {
  if (!home.nextExamOn) return null
  const days = daysBetween(home.localDate, home.nextExamOn)
  return { date: home.nextExamOn, days, near: days >= 0 && days <= EXAM_NEAR_DAYS }
}

/* ── stage ────────────────────────────────────────────────────────────── */

function motionFor(mood: BinnyMood): BinnyMotion {
  return mood === "happy" ? "hop" : "idle"
}

function stage(
  key: string,
  kind: StageKind,
  mood: BinnyMood,
  line: string,
  action: { label: string; to: string },
  dismissible = true,
  greeting: string | null = null,
): StageVm {
  return { key, kind, mood, motion: motionFor(mood), greeting, line, action, dismissible }
}

/** "an A", "an A*", "an E", "an F", "a B", "a U". */
export function withArticle(grade: string): string {
  return `${/^[AEF]/.test(grade) ? "an" : "a"} ${grade}`
}

function paperStage(m: PaperMoment): StageVm {
  const focus = m.focusQuestion ? questionLabel(m.focusQuestion) : null
  const to = homeRoutes.result(m.paperId, "lost")
  if (m.kind === "tough") {
    return stage(
      `tough:${m.paperId}`,
      "tough",
      "sad",
      `${m.subjectName} Paper ${m.paperNumber} was a tough one. Let's win back the easy marks first.`,
      { label: focus ? `Start with ${focus}` : "See my result", to },
    )
  }
  const up =
    m.previousGrade && m.previousGrade !== m.grade ? `, up from ${withArticle(m.previousGrade)}` : ""
  const fix = focus ? ` ${focus} is the one to fix.` : ""
  return stage(
    `result:${m.paperId}`,
    "result",
    "happy",
    `${m.awarded} out of ${m.maximum}. That's ${withArticle(m.grade)}${up}.${fix}`,
    { label: focus ? `Fix ${focus}` : "See my result", to },
  )
}

function momentStage(m: HomeMoment, home: StudentHome): StageVm {
  switch (m.kind) {
    case "marking": {
      const progress =
        m.questionsTotal != null && m.questionsDone != null
          ? `Marking your paper. ${m.questionsDone} of ${m.questionsTotal} questions done.`
          : "Marking your paper now."
      const line = m.stale ? "Still marking. This one's taking a while." : progress
      return stage(`marking:${m.paperId}`, "marking", "thinking", line, {
        label: "Watch it mark",
        to: homeRoutes.scan,
      }, false)
    }
    case "result":
    case "tough":
      return paperStage(m)
    case "teacherReply": {
      const r = m.reply
      const added = r.marksAdded > 0 ? ` +${plural(r.marksAdded, "mark")}.` : ""
      return stage(
        `teacherReply:${r.reviewId}`,
        "teacherReply",
        "wink",
        `${r.teacherName} checked your ${questionLabel(r.questionId)}.${added}`,
        { label: "See the answer", to: r.paperId ? homeRoutes.result(r.paperId) : homeRoutes.notifications },
      )
    }
    case "streakAtRisk":
      return stage(
        `streakAtRisk:${home.localDate}`,
        "streakAtRisk",
        "thinking",
        `Your ${m.streakDays}-day streak ends at midnight. One quick set keeps it going.`,
        { label: "Keep my streak", to: practiceTarget(home) },
      )
    case "goalDone":
      return stage(
        `goalDone:${home.localDate}`,
        "goalDone",
        "happy",
        "Three for three today. That's you done. See you tomorrow.",
        { label: "See tomorrow's plan", to: planTarget(home) },
      )
    case "backAfterBreak":
      return stage(
        `backAfterBreak:${home.localDate}`,
        "backAfterBreak",
        "wink",
        `There you are. ${m.daysAway} days off is fine. Ease back in with five minutes.`,
        { label: "5-minute warm-up", to: practiceTarget(home) },
      )
  }
}

function fallbackStages(home: StudentHome): StageVm[] {
  const exam = examInfo(home)
  const near = exam?.near ? `${plural(exam.days, "day")} to exams. ` : null
  const name = firstName(home.studentName)
  const out: StageVm[] = []

  if (isFirstRun(home)) {
    out.push(
      stage("firstRun", "firstRun", "open", near ? `${near}Let's mark a paper.` : `Hi ${name}. Let's mark your first paper.`, {
        label: "Scan a paper",
        to: homeRoutes.scan,
      }, false),
    )
    return out
  }

  const session = home.todaySessions.find((s) => !s.done)
  if (session) {
    out.push(
      stage(
        `session:${session.sessionId}`,
        "session",
        "open",
        near ? `${near}Today: ${session.topic}.` : `Today's plan: ${session.topic}, ${session.minutes} minutes.`,
        { label: "Start", to: homeRoutes.session(session.subjectCode, session.sessionId) },
      ),
    )
  }

  const top = home.winBack[0]
  if (top) {
    const greeting = !near && home.localHour < 12 ? `${shortGreeting(home.localHour)}, ${name}.` : null
    out.push(
      stage(
        `morning:${top.subjectCode}:${top.topic}`,
        "morning",
        "open",
        near
          ? `${near}${top.topic} first, +${top.marks} marks.`
          : `${top.topic} cost you ${top.marks} marks last time. Ten minutes fixes most of it.`,
        { label: "Start 10 minutes", to: homeRoutes.practiceTopic(top.subjectCode, top.topic) },
        true,
        greeting,
      ),
    )
  }

  out.push(
    stage("scanNext", "scanNext", "open", near ? `${near}Scan your next paper.` : "Nothing to win back yet. Scan your next paper.", {
      label: "Scan a paper",
      to: homeRoutes.scan,
    }, false),
  )
  return out
}

export function stageCandidates(home: StudentHome): StageVm[] {
  const moments = [...home.moments].sort(
    (a, b) => STAGE_PRIORITY.indexOf(a.kind) - STAGE_PRIORITY.indexOf(b.kind),
  )
  return [...moments.map((m) => momentStage(m, home)), ...fallbackStages(home)]
}

export function pickStage(home: StudentHome, dismissed: ReadonlySet<string>): StageVm {
  const candidates = stageCandidates(home)
  return candidates.find((s) => !s.dismissible || !dismissed.has(s.key)) ?? candidates[candidates.length - 1]!
}

/* ── rows ─────────────────────────────────────────────────────────────── */

function teacherRow(home: StudentHome): RowVm | null {
  const r = home.teacherReplies[0]
  if (!r) return null
  const added = r.marksAdded > 0 ? ` · +${plural(r.marksAdded, "mark")}` : ""
  return {
    key: `teacher:${r.reviewId}`,
    kind: "teacher",
    leading: { type: "initials", text: initials(r.teacherName) },
    title: `${r.teacherName} checked your answer`,
    sub: `${questionLabel(r.questionId)}${added}`,
    to: r.paperId ? homeRoutes.result(r.paperId) : homeRoutes.notifications,
  }
}

function homeworkRow(home: StudentHome): RowVm | null {
  const h = home.homework[0]
  if (!h) return null
  return {
    key: `homework:${h.assignmentId}`,
    kind: "homework",
    leading: { type: "icon", icon: "sheet" },
    title: `${h.title} from ${h.teacherName}`,
    sub: `${dueLabel(h.dueAt, home.localDate, h.isOverdue)} · ${plural(h.questionCount, "question")}`,
    to: homeRoutes.practiceSet(h.assignmentId),
  }
}

export function alsoRows(home: StudentHome, current: StageVm, layout: "phone" | "desktop"): RowVm[] {
  const rows: (RowVm | null)[] = []
  const paper = home.moments.find(
    (m): m is PaperMoment => (m.kind === "result" || m.kind === "tough") && current.kind === m.kind,
  )
  if (paper) {
    rows.push({
      key: `result:${paper.paperId}`,
      kind: "result",
      leading: { type: "grade", grade: paper.grade },
      title: "See your full result",
      sub: `${paper.subjectName} · Paper ${paper.paperNumber}`,
      to: homeRoutes.result(paper.paperId),
    })
  }
  if (layout === "phone") {
    if (current.kind !== "teacherReply") rows.push(teacherRow(home))
    rows.push(homeworkRow(home))
  }
  if (home.classCount === 0) {
    rows.push({
      key: "joinClass",
      kind: "joinClass",
      leading: { type: "icon", icon: "class" },
      title: "Join your teacher's class",
      sub: "Enter the code they gave you",
      to: homeRoutes.classes,
    })
  }
  if (home.stats.papersMarked === 1) {
    rows.push({
      key: "sparse",
      kind: "sparse",
      leading: { type: "icon", icon: "trend" },
      title: "One more paper draws your trend",
      sub: "Scan your next paper",
      to: homeRoutes.scan,
    })
  }
  if (home.lastPaperAt && current.kind !== "scanNext" && current.kind !== "firstRun") {
    const days = daysBetween(isoDay(new Date(home.lastPaperAt)), home.localDate)
    if (days > SCAN_NUDGE_DAYS) {
      rows.push({
        key: "scan",
        kind: "scan",
        leading: { type: "icon", icon: "camera" },
        title: "Scan your next paper",
        sub: `Your last one was ${days} days ago`,
        to: homeRoutes.scan,
      })
    }
  }
  return rows.filter((r): r is RowVm => r !== null).slice(0, 2)
}

/* ── blocks ───────────────────────────────────────────────────────────── */

export function todayVm(home: StudentHome) {
  const g = home.goals
  const parts: [number, number, number] = [g.practice ? 1 : 0, g.flashcards ? 1 : 0, g.paperThisWeek ? 1 : 0]
  const doneCount = parts.reduce<number>((a, b) => a + b, 0)
  return {
    parts,
    doneCount,
    label: `${doneCount} of 3 today`,
    planTo: planTarget(home),
    chips: [
      { label: "Practice", done: g.practice, to: practiceTarget(home) },
      { label: "Flashcards", done: g.flashcards, to: flashcardsTarget(home) },
      { label: "Paper this week", done: g.paperThisWeek, to: homeRoutes.scan },
    ],
  }
}

export function weekVm(home: StudentHome) {
  const to = planTarget(home)
  return home.week.map((d) => {
    const name = WEEKDAYS[parseDay(d.day).getDay()]!
    const label = d.label ? `: ${d.label}` : ""
    return {
      day: d.day,
      letter: name[0]!,
      done: d.done,
      isToday: d.isToday,
      ariaLabel: `${name}${label}${d.done ? ", done" : ""}`,
      to,
    }
  })
}

export function floorVm(home: StudentHome) {
  return home.floor.map((f) => ({
    code: f.code,
    name: shortSubject(f.name),
    grade: f.grade,
    sub: f.nextGrade && f.pointsToNext != null ? `${f.pointsToNext} pts to ${f.nextGrade}` : "Top grade",
    to: homeRoutes.subject(f.code),
  }))
}

export function lastPaperVm(home: StudentHome) {
  const p = home.recentPapers[0]
  if (!p) return null
  return {
    grade: p.grade,
    title: `Last paper · ${shortSubject(p.subjectName)} P${p.paperNumber}`,
    sub: `${p.awarded}/${p.maximum} · ${relativeDay(p.recordedAt, home.localDate)}`,
    to: homeRoutes.result(p.paperId),
  }
}

export function winVm(home: StudentHome, kind: StageKind) {
  const limit = kind === "backAfterBreak" ? 1 : 3
  return home.winBack.slice(0, limit).map((t) => ({
    topic: t.topic,
    sub: shortSubject(t.subjectName),
    marks: t.marks,
    to: homeRoutes.practiceTopic(t.subjectCode, t.topic),
  }))
}

export function streakPillVm(home: StudentHome) {
  const s = home.streak
  const g = home.goals
  const label = s.current > 0 ? plural(s.current, "day") : s.longest > 0 ? "New streak" : "Start a streak"
  return { label, lit: g.practice && g.flashcards && g.paperThisWeek, to: homeRoutes.me }
}

export function bandVm(home: StudentHome) {
  const todayIdx = home.week.findIndex((d) => d.isToday)
  const weekNext: { when: string; what: string }[] = []
  const today = home.week[todayIdx]
  if (today?.label) weekNext.push({ when: "Today", what: today.label })
  const next = home.week.slice(todayIdx + 1).find((d) => d.label)
  if (next?.label) weekNext.push({ when: WEEKDAYS[parseDay(next.day).getDay()]!, what: next.label })
  return {
    weekNext,
    recent: home.recentPapers.map((p) => ({
      grade: p.grade,
      title: `${shortSubject(p.subjectName)} · Paper ${p.paperNumber}`,
      sub: `${p.awarded}/${p.maximum} · ${relativeDay(p.recordedAt, home.localDate)}`,
      to: homeRoutes.result(p.paperId),
    })),
    classRows: [teacherRow(home), homeworkRow(home)].filter((r): r is RowVm => r !== null),
  }
}

export interface HomeVm {
  firstRun: boolean
  heading: string
  stage: StageVm
  also: { phone: RowVm[]; desktop: RowVm[] }
  today: ReturnType<typeof todayVm>
  week: ReturnType<typeof weekVm>
  floor: ReturnType<typeof floorVm>
  last: ReturnType<typeof lastPaperVm>
  win: ReturnType<typeof winVm>
  streakPill: ReturnType<typeof streakPillVm>
  exam: ReturnType<typeof examInfo>
  band: ReturnType<typeof bandVm>
  allPapersTo: string | null
}

export function homeView(home: StudentHome, dismissed: ReadonlySet<string>): HomeVm {
  const current = pickStage(home, dismissed)
  const last = home.recentPapers[0]
  return {
    firstRun: isFirstRun(home),
    heading: `${shortGreeting(home.localHour)}, ${firstName(home.studentName)}`,
    stage: current,
    also: { phone: alsoRows(home, current, "phone"), desktop: alsoRows(home, current, "desktop") },
    today: todayVm(home),
    week: weekVm(home),
    floor: floorVm(home),
    last: lastPaperVm(home),
    win: winVm(home, current.kind),
    streakPill: streakPillVm(home),
    exam: examInfo(home),
    band: bandVm(home),
    // "All papers" has no screen yet; it opens the last paper's subject (item 6).
    allPapersTo: last ? homeRoutes.subject(last.subjectCode) : null,
  }
}
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd web && npx vitest run tests/unit/studentHomeModel.test.ts tests/unit/studentHomeRoutes.test.ts tests/unit/studentHomeDismiss.test.ts`
Expected: all pass. `relativeDay` and `dueLabel` read local time, so run once more with `TZ=Africa/Cairo` and once with `TZ=America/Los_Angeles` to prove the fixture dates are zone-safe; if a case flips, move the fixture timestamp to midday UTC rather than changing the helper.

- [ ] **Step 7: Typecheck, lint, commit**

```bash
cd web && npx tsc -b --noEmit && npm run lint && npm run check:copy && cd ..
pre-commit run --files web/src/portals/student/home/model.ts web/src/portals/student/home/routes.ts web/src/portals/student/home/dismiss.ts web/tests/unit/studentHomeModel.test.ts web/tests/unit/studentHomeRoutes.test.ts web/tests/unit/studentHomeDismiss.test.ts
git rm -r --quiet web/dev-previews/student-home web/dev-previews/student-home.html web/dev-previews/student-home-a.html web/dev-previews/student-home-b.html web/dev-previews/student-home-c.html web/tests/unit/studentHomeFixtures.test.ts
# remove the four "student-home*" entries at web/vite.preview.config.ts:55-58 and its doc line 31 mention
git commit -S -m "feat(web): student home view model and door routes" -- web/src/portals/student/home/model.ts web/src/portals/student/home/routes.ts web/src/portals/student/home/dismiss.ts web/tests/unit/studentHomeModel.test.ts web/tests/unit/studentHomeRoutes.test.ts web/tests/unit/studentHomeDismiss.test.ts web/dev-previews web/tests/unit/studentHomeFixtures.test.ts web/vite.preview.config.ts
```

---

## Task 7: Me view model

**Files:**
- Create: `web/src/portals/student/home/me/meModel.ts`
- Modify: `web/tests/unit/xpProfile.test.ts` (import path only, lines 2-7)
- Test: `web/tests/unit/studentMeModel.test.ts`

**Interfaces:**
- Consumes: `XpProfile`, `XpDay`, `XpSource` (`web/src/lib/xpTypes.ts`); `Profile` (`web/src/lib/meTypes.ts`); Task 5 `StudentHome`; Task 6 `homeRoutes`, `shortSubject`, `GRADE ORDER` logic.
- Produces: `calendarDays`, `fillCalendar`, `levelProgress`, `sourceLabel` (moved verbatim from `Profile.tsx:87-147`); `displayName(profile)`, `levelLine(xp)`, `streakStrip(xp, days = 14)`, `streakLine(xp)`, `statsVm(home)`, `BADGES`, `deriveBadges(home, xp)`, `ordinal(n)`, `peopleVm(input)`, `subjectsVm(home)`, `activityVm(home)`, `accountRows(input)`, `gradeRank(grade)`.

- [ ] **Step 1: Write the failing test**

```ts
import { describe, expect, it } from "vitest"
import {
  accountRows,
  activityVm,
  deriveBadges,
  displayName,
  levelLine,
  ordinal,
  peopleVm,
  statsVm,
  streakLine,
  streakStrip,
  subjectsVm,
} from "@/portals/student/home/me/meModel"
import type { XpProfile } from "@/lib/xpTypes"
import { makeHome } from "./studentHomeFixture"

function xp(overrides: Partial<XpProfile> = {}): XpProfile {
  return {
    totalXp: 2240,
    level: 7,
    levelStartXp: 2000,
    nextLevelXp: 2500,
    streak: { current: 9, longest: 14, lastActiveOn: "2026-11-12", freezesAvailable: 1 },
    week: { total: 0, start: "2026-11-09", end: "2026-11-15", bySource: [] },
    calendar: [
      { day: "2026-11-12", xp: 30 },
      { day: "2026-11-11", xp: 10 },
    ],
    calendarStart: "2026-10-16",
    calendarEnd: "2026-11-12",
    ...overrides,
  } as XpProfile
}

describe("Me view model", () => {
  it("names the student with the live fallback chain", () => {
    expect(displayName({ displayName: "Mariam Adel", email: "m@x.com" })).toBe("Mariam Adel")
    expect(displayName({ displayName: null, email: "mariam@x.com" })).toBe("mariam")
    expect(displayName(undefined)).toBe("You")
  })

  it("level line reads the server's curve, never computes one", () => {
    expect(levelLine(xp())).toBe("Level 7 · 260 XP to level 8")
  })

  it("14-day streak strip ends today", () => {
    const strip = streakStrip(xp())
    expect(strip).toHaveLength(14)
    expect(strip[13]).toEqual({ day: "2026-11-12", on: true, now: true })
    expect(strip[12]).toEqual({ day: "2026-11-11", on: true, now: false })
    expect(strip[11]!.on).toBe(false)
    expect(streakLine(xp())).toEqual({ main: "9-day streak", best: "best 14" })
    expect(streakLine(xp({ streak: { current: 0, longest: 0, lastActiveOn: null, freezesAvailable: 0 } }))).toEqual({
      main: "No streak yet",
      best: null,
    })
  })

  it("stats", () => {
    expect(statsVm(makeHome())).toEqual([
      { value: "22", label: "papers marked", to: "/student/subject/0580", grade: null },
      { value: "+64", label: "marks won back", to: "/student/practice/0580?topic=Vectors", grade: null },
      { value: "A", label: "best grade", to: "/student/subject/0580", grade: "A" },
    ])
    const fresh = makeHome({ stats: { papersMarked: 0, marksWonBack: 0, bestGrade: null }, recentPapers: [], floor: [], winBack: [] })
    expect(statsVm(fresh).map((s) => s.value)).toEqual(["0", "0", "–"])
  })

  it("badges are derived from real data only", () => {
    const badges = deriveBadges(makeHome(), xp())
    expect(badges.map((b) => [b.id, b.earned])).toEqual([
      ["first-paper", true],
      ["streak-7", true],
      ["grade-up", true],
      ["streak-30", false],
      ["a-star", false],
    ])
    const none = deriveBadges(
      makeHome({ stats: { papersMarked: 0, marksWonBack: 0, bestGrade: null }, floor: [] }),
      xp({ streak: { current: 0, longest: 0, lastActiveOn: null, freezesAvailable: 0 } }),
    )
    expect(none.every((b) => !b.earned)).toBe(true)
  })

  it("people doors", () => {
    expect(ordinal(1)).toBe("1st")
    expect(ordinal(3)).toBe("3rd")
    expect(ordinal(11)).toBe("11th")
    expect(ordinal(22)).toBe("22nd")
    const doors = peopleVm({ classes: 2, rank: 3, friends: 4, parents: 1 })
    expect(doors.map((d) => [d.label, d.sub, d.to])).toEqual([
      ["Classes", "2 classes", "/student/classes"],
      ["Standings", "3rd", "/student/board"],
      ["Friends", "4 friends", "/student/friends"],
      ["Parents", "1 linked", "/student/parents"],
    ])
    expect(peopleVm({ classes: undefined, rank: null, friends: 0, parents: 0 }).map((d) => d.sub)).toEqual([
      null,
      "Not ranked yet",
      "Add a friend",
      "Invite a parent",
    ])
  })

  it("subjects and activity", () => {
    expect(subjectsVm(makeHome())[2]).toEqual({
      grade: "B",
      title: "Additional Mathematics",
      sub: "0606 · 2 papers · 9 pts to A",
      to: "/student/subject/0606",
    })
    const home = makeHome({ activity: [{ kind: "paper", title: "Paper marked", sub: "Mathematics P4 · B", at: "2026-11-10T10:00:00+00:00" }] })
    expect(activityVm(home)).toEqual([{ kind: "paper", title: "Paper marked", sub: "Mathematics P4 · B", when: "2 days ago" }])
  })

  it("account rows keep tutoring, placement, settings, notifications and recently deleted", () => {
    const rows = accountRows({ deletedCount: 2, placementCode: "0580" })
    expect(rows.map((r) => [r.label, r.sub, r.to])).toEqual([
      ["Tutoring", "Book a session", "/student/tutors"],
      ["Placement test", "Find your starting level", "/student/placement/0580"],
      ["Profile and settings", null, "/student/settings"],
      ["Notifications", null, "/student/notifications"],
      ["Recently deleted", "2 papers", "/student/recently-deleted"],
    ])
    expect(accountRows({ deletedCount: 0, placementCode: null }).map((r) => r.label)).not.toContain("Placement test")
  })
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd web && npx vitest run tests/unit/studentMeModel.test.ts`
Expected: FAIL, cannot resolve `@/portals/student/home/me/meModel`.

- [ ] **Step 3: Write the model**

```ts
/*
 * Me view model (lane L1). Pure. The first four exports moved verbatim from
 * the old `screens/Profile.tsx` (see its history for the reasoning on each):
 * the window comes from the server, absent days are zero, the level curve is
 * read from the wire and never recomputed here.
 */
import type { Profile } from "@/lib/meTypes"
import type { StudentHome } from "@/lib/studentHomeTypes"
import type { XpDay, XpProfile, XpSource } from "@/lib/xpTypes"
import { relativeDay, shortSubject } from "../model"
import { homeRoutes, practiceTarget } from "../routes"

const GRADE_ORDER = ["U", "G", "F", "E", "D", "C", "B", "A", "A*"]

export function gradeRank(grade: string): number {
  return GRADE_ORDER.indexOf(grade)
}

/* ── moved from Profile.tsx (unchanged) ───────────────────────────────── */

export function calendarDays(start: string, end: string): string[] {
  const days: string[] = []
  const cursor = new Date(`${start}T00:00:00`)
  const last = new Date(`${end}T00:00:00`)
  while (cursor.getTime() <= last.getTime()) {
    const year = cursor.getFullYear()
    const month = String(cursor.getMonth() + 1).padStart(2, "0")
    const day = String(cursor.getDate()).padStart(2, "0")
    days.push(`${year}-${month}-${day}`)
    cursor.setDate(cursor.getDate() + 1)
  }
  return days
}

export function fillCalendar(profile: XpProfile): { day: string; xp: number }[] {
  const earned = new Map(profile.calendar.map((d: XpDay) => [d.day, d.xp]))
  return calendarDays(profile.calendarStart, profile.calendarEnd).map((day) => ({
    day,
    xp: earned.get(day) ?? 0,
  }))
}

export function levelProgress(profile: XpProfile): number {
  const span = profile.nextLevelXp - profile.levelStartXp
  if (span <= 0) return 0
  const into = profile.totalXp - profile.levelStartXp
  return Math.max(0, Math.min(100, (into / span) * 100))
}

const SOURCE_LABELS: Record<XpSource, string> = {
  paper_corrected: "Papers corrected",
  quiz_completed: "Quizzes",
  flashcard_reviewed: "Flashcards",
  study_session_completed: "Study sessions",
}

export function sourceLabel(source: XpSource | string): string {
  return SOURCE_LABELS[source as XpSource] ?? source.replace(/_/g, " ")
}

/* ── Me ───────────────────────────────────────────────────────────────── */

function plural(n: number, word: string): string {
  return `${n} ${word}${n === 1 ? "" : "s"}`
}

export function displayName(profile: Pick<Profile, "displayName" | "email"> | undefined): string {
  return profile?.displayName ?? profile?.email.split("@")[0] ?? "You"
}

export function levelLine(xp: XpProfile): string {
  const remaining = Math.max(0, xp.nextLevelXp - xp.totalXp)
  return `Level ${xp.level} · ${remaining.toLocaleString()} XP to level ${xp.level + 1}`
}

export function streakStrip(xp: XpProfile, days = 14): { day: string; on: boolean; now: boolean }[] {
  const filled = fillCalendar(xp).slice(-days)
  return filled.map((d, i) => ({ day: d.day, on: d.xp > 0, now: i === filled.length - 1 }))
}

export function streakLine(xp: XpProfile): { main: string; best: string | null } {
  const { current, longest } = xp.streak
  if (current === 0 && longest === 0) return { main: "No streak yet", best: null }
  return { main: `${current}-day streak`, best: longest > 0 ? `best ${longest}` : null }
}

export function statsVm(home: StudentHome) {
  const last = home.recentPapers[0]
  const best = home.stats.bestGrade
  return [
    { value: String(home.stats.papersMarked), label: "papers marked", to: last ? homeRoutes.subject(last.subjectCode) : homeRoutes.scan, grade: null },
    {
      value: home.stats.marksWonBack > 0 ? `+${home.stats.marksWonBack}` : "0",
      label: "marks won back",
      to: practiceTarget(home),
      grade: null,
    },
    { value: best?.grade ?? "–", label: "best grade", to: best ? homeRoutes.subject(best.subjectCode) : homeRoutes.scan, grade: best?.grade ?? null },
  ]
}

export const BADGES = [
  { id: "first-paper", label: "First paper", hint: "Mark your first paper" },
  { id: "streak-7", label: "7-day streak", hint: "Earn XP seven days in a row" },
  { id: "grade-up", label: "Grade up", hint: "Move a subject up a grade" },
  { id: "streak-30", label: "30-day streak", hint: "Earn XP thirty days in a row" },
  { id: "a-star", label: "A* paper", hint: "Score an A* on a paper" },
] as const

export type BadgeId = (typeof BADGES)[number]["id"]

export function deriveBadges(home: StudentHome, xp: XpProfile) {
  const earned: Record<BadgeId, boolean> = {
    "first-paper": home.stats.papersMarked >= 1,
    "streak-7": xp.streak.longest >= 7,
    "grade-up": home.floor.some((f) => f.previousGrade !== null && gradeRank(f.grade) > gradeRank(f.previousGrade)),
    "streak-30": xp.streak.longest >= 30,
    "a-star": home.stats.bestGrade?.grade === "A*",
  }
  return BADGES.map((b) => ({ ...b, earned: earned[b.id] }))
}

export function ordinal(n: number): string {
  const tens = n % 100
  if (tens >= 11 && tens <= 13) return `${n}th`
  return `${n}${({ 1: "st", 2: "nd", 3: "rd" } as Record<number, string>)[n % 10] ?? "th"}`
}

export function peopleVm(input: {
  classes: number | undefined
  rank: number | null | undefined
  friends: number | undefined
  parents: number | undefined
}) {
  const sub = <T,>(v: T | undefined, f: (v: T) => string) => (v === undefined ? null : f(v))
  return [
    { id: "classes", label: "Classes", sub: sub(input.classes, (n) => `${n} ${n === 1 ? "class" : "classes"}`), to: homeRoutes.classes },
    { id: "standings", label: "Standings", sub: input.rank === undefined ? null : input.rank === null ? "Not ranked yet" : ordinal(input.rank), to: homeRoutes.standings },
    { id: "friends", label: "Friends", sub: sub(input.friends, (n) => (n === 0 ? "Add a friend" : plural(n, "friend"))), to: homeRoutes.friends },
    { id: "parents", label: "Parents", sub: sub(input.parents, (n) => (n === 0 ? "Invite a parent" : `${n} linked`)), to: homeRoutes.parents },
  ] as const
}

export function subjectsVm(home: StudentHome) {
  return home.floor.map((f) => ({
    grade: f.grade,
    title: f.name,
    sub: [
      f.code,
      plural(f.papers, "paper"),
      f.nextGrade && f.pointsToNext != null ? `${f.pointsToNext} pts to ${f.nextGrade}` : "Top grade",
    ].join(" · "),
    to: homeRoutes.subject(f.code),
  }))
}

export function activityVm(home: StudentHome) {
  return home.activity.map((a) => ({ kind: a.kind, title: a.title, sub: a.sub, when: relativeDay(a.at, home.localDate) }))
}

export function accountRows(input: { deletedCount: number | undefined; placementCode: string | null }) {
  const rows: { id: string; label: string; sub: string | null; to: string; overlay?: boolean }[] = [
    { id: "tutoring", label: "Tutoring", sub: "Book a session", to: homeRoutes.tutoring },
  ]
  if (input.placementCode) {
    rows.push({ id: "placement", label: "Placement test", sub: "Find your starting level", to: homeRoutes.placement(input.placementCode) })
  }
  rows.push(
    { id: "settings", label: "Profile and settings", sub: null, to: homeRoutes.settings, overlay: true },
    { id: "notifications", label: "Notifications", sub: null, to: homeRoutes.notifications },
    {
      id: "deleted",
      label: "Recently deleted",
      sub: input.deletedCount ? plural(input.deletedCount, "paper") : null,
      to: homeRoutes.recentlyDeleted,
    },
  )
  return rows
}

export { shortSubject }
```

The `accountRows` test expects `["Profile and settings", null, "/student/settings"]`; the extra `overlay` flag is ignored by that mapping.

- [ ] **Step 4: Point the moved helpers' test at the new file**

In `web/tests/unit/xpProfile.test.ts` change the import source on line 7 from `"@/portals/student/screens/Profile"` to `"@/portals/student/home/me/meModel"`. Nothing else changes.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd web && npx vitest run tests/unit/studentMeModel.test.ts tests/unit/xpProfile.test.ts`
Expected: all pass. (`Profile.tsx` still exports its own copies until Task 10; that is fine.)

- [ ] **Step 6: Typecheck, lint, commit**

```bash
cd web && npx tsc -b --noEmit && npm run lint && npm run check:copy && cd ..
pre-commit run --files web/src/portals/student/home/me/meModel.ts web/tests/unit/studentMeModel.test.ts web/tests/unit/xpProfile.test.ts
git commit -S -m "feat(web): student Me view model" -- web/src/portals/student/home/me/meModel.ts web/tests/unit/studentMeModel.test.ts web/tests/unit/xpProfile.test.ts
```

---

## Screen tasks: shared instructions for the `designer` agent

Before any UI edit in Tasks 8–10: invoke the `impeccable` skill, read `.claude/skills/impeccable/reference/craft-floor.md`, read the three taste memories named in the master plan, and open `.impeccable/mocks/student-r2/home4.html` in a browser (serve `.impeccable/mocks` with `python -m http.server 4599 --directory .impeccable/mocks`, then `http://127.0.0.1:4599/student-r2/home4.html`; the moment buttons above the frames switch `P5` and `D5`).

Rules for every component below:
- Import F1 parts only from `@/components/redesign`: `Binny`, `GoldRing`, `KeyRing`, `CountdownPill`, `HairRows`, `HairRow`, `Walkthrough`, `GhostRows`.
- If F1's `HairRow` already draws a trailing chevron for rows with `to`, do not pass another one.
- Icons come from `@phosphor-icons/react` at 14–24px with `aria-hidden="true"`.
- Use the token map above. No raw hex or oklch in class names except inside the `color-mix()` arbitrary values given in this plan.
- Use logical properties only (`ms-`, `me-`, `ps-`, `pe-`, `start-`, `end-`, `border-s`). The files are added to `rtlSafety.test.ts` in Task 11.
- Components take view-model objects as props. No component reads a query or computes copy.

### Shared small files (create in Task 8)

`web/src/portals/student/home/gradeClass.ts`:

```ts
/* Static class strings so Tailwind sees every grade colour. */
const GRADE_TEXT: Record<string, string> = {
  "A*": "text-grade-a-star",
  A: "text-grade-a",
  B: "text-grade-b",
  C: "text-grade-c",
  D: "text-grade-d",
  E: "text-grade-e",
  F: "text-grade-f",
  G: "text-grade-g",
  U: "text-grade-u",
}

export function gradeText(grade: string): string {
  return GRADE_TEXT[grade] ?? "text-on-surface"
}

export const PRESS = "transition-transform duration-[var(--dur-fast)] ease-out motion-safe:active:scale-[.97]"
export const ROW_PRESS =
  "transition-[transform,background-color] duration-[var(--dur-fast)] ease-out motion-safe:active:scale-[.985] hover:bg-[linear-gradient(90deg,transparent,var(--md-surface-container-low)_12%,var(--md-surface-container-low)_88%,transparent)]"
export const FOCUS = "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
/** 44px hit area around a small control, without changing its look (mock `.pill4::before`). */
export const HIT = "relative before:absolute before:-inset-x-[3px] before:-inset-y-2 before:content-['']"
```

`web/src/portals/student/home/SectionLink.tsx` (the mock's `.hlink.h` heading that is itself a door):

```tsx
import { Link } from "react-router-dom"
import { CaretRight } from "@phosphor-icons/react"
import { cn } from "@/lib/utils"
import { FOCUS, HIT, PRESS } from "./gradeClass"

export function SectionLink({ id, title, to, onClick }: { id?: string; title: string; to?: string; onClick?: () => void }) {
  const inner = (
    <>
      <b className="text-[18px] font-extrabold tracking-[-0.01em]">{title}</b>
      <CaretRight size={14} weight="bold" className="text-on-surface-variant" aria-hidden="true" />
    </>
  )
  const cls = cn("inline-flex items-center gap-2 justify-self-start rounded-row py-1 pe-1.5 text-on-surface", HIT, PRESS, FOCUS)
  return (
    <h2 id={id} className="mb-0.5">
      {to ? (
        <Link to={to} className={cls}>{inner}</Link>
      ) : (
        <button type="button" onClick={onClick} className={cls}>{inner}</button>
      )}
    </h2>
  )
}
```

---

## Task 8: Home screen, phone layout, loading, error and offline

**Files:**
- Create: `web/src/portals/student/home/gradeClass.ts`, `SectionLink.tsx`, `HomeScreen.tsx`, `HomeTopRow.tsx`, `HomeStage.tsx`, `TodayBlock.tsx`, `WeekStrip.tsx`, `GradeFloor.tsx`, `LastPaperRow.tsx`, `WinBack.tsx`, `MomentRows.tsx`, `HomeSkeleton.tsx` (all under `web/src/portals/student/home/`)
- Replace: `web/src/portals/student/screens/Overview.tsx` (whole file)
- Modify: `web/tests/unit/streakChip.test.ts` (the `Overview.tsx` describe block, lines 19-32), `web/tests/unit/sectionHead.test.ts` (drop the Overview entry from `MIGRATED_SCREENS`, line 21)

**Interfaces:**
- Consumes: Task 5 `useStudentHome`, `StudentHome`; Task 6 `homeView`, `HomeVm`, `StageVm`, `RowVm`, `parseDay`, `homeRoutes`, `readDismissed`, `writeDismissed`, `safeLocalStorage`; F1 parts.
- Produces: `HomeScreen({ home })`, `HomeSkeleton()`, `MomentRows({ rows, className })`, `WeekStrip({ days, className })` (reused by Task 9's band), `SectionLink`, `gradeText`, `PRESS`, `ROW_PRESS`, `FOCUS`, `HIT`.

Component tree (phone, mock `P5` / `H6`):

```
Overview (QueryState: HomeSkeleton | error | HomeScreen)
└─ HomeScreen                         .h4pad   gradient, gap 22, px 20, pb 96
   ├─ header: PageHeading (sr-only <xl) + HomeTopRow   .top4 + desktop .dtop
   │   └─ streak pill (Link → Me), CountdownPill (Link → plan)
   ├─ section "Binny"
   │   ├─ HomeStage                   .stage4  spot, Binny 150 (200 at xl), line, big button, Not now
   │   └─ MomentRows (vm.also.phone, md:hidden) / (vm.also.desktop, hidden md:grid)  .also
   ├─ section "Today and grades"
   │   ├─ TodayBlock                  .today6  GoldRing 32, "N of 3 today · Plan ›", chips, WeekStrip (md:hidden)
   │   ├─ GradeFloor | HomeFirstRun   .floor
   │   ├─ LastPaperRow (md:hidden)    .lastw
   │   └─ WinBack                     .win4
   └─ HomeBand (hidden md:grid)       Task 9
```

- [ ] **Step 1: Write the entry file**

`web/src/portals/student/screens/Overview.tsx`:

```tsx
import { QueryState } from "@/components/ui/query-state"
import { useStudentHome } from "@/lib/hooks/useStudentHomeApi"
import { useOnlineStatus } from "@/lib/online"
import { studentLoadFailureMessage } from "@/lib/studentOutcome"
import { HomeScreen } from "../home/HomeScreen"
import { HomeSkeleton } from "../home/HomeSkeleton"

/*
 * Student Home, the hub (redesign lane L1, mock student-r2/home4.html + h6.js).
 * Route entry only: one query, one QueryState, one screen. Every decision is
 * in `../home/model.ts`.
 */
export function Overview() {
  const query = useStudentHome()
  const online = useOnlineStatus()
  return (
    <QueryState
      query={query}
      srHeading="Home"
      skeleton={<HomeSkeleton />}
      error={
        online
          ? { heading: "Couldn't load your home", body: studentLoadFailureMessage }
          : { heading: "You're offline", body: "Home comes back when you reconnect. Nothing you did is lost." }
      }
    >
      {(home) => <HomeScreen home={home} />}
    </QueryState>
  )
}
```

- [ ] **Step 2: Write `HomeScreen`**

```tsx
import { useMemo, useState } from "react"
import { PageHeading } from "@/components/ui/page-heading"
import type { StudentHome } from "@/lib/studentHomeTypes"
import { readDismissed, safeLocalStorage, writeDismissed } from "./dismiss"
import { GradeFloor } from "./GradeFloor"
import { HomeBand } from "./HomeBand"
import { HomeFirstRun } from "./HomeFirstRun"
import { HomeStage } from "./HomeStage"
import { HomeTopRow } from "./HomeTopRow"
import { LastPaperRow } from "./LastPaperRow"
import { MomentRows } from "./MomentRows"
import { homeView } from "./model"
import { TodayBlock } from "./TodayBlock"
import { WinBack } from "./WinBack"

export function HomeScreen({ home }: { home: StudentHome }) {
  const [dismissed, setDismissed] = useState(() => readDismissed(safeLocalStorage(), home.localDate))
  const vm = useMemo(() => homeView(home, dismissed), [home, dismissed])

  function notNow() {
    const next = new Set(dismissed).add(vm.stage.key)
    writeDismissed(safeLocalStorage(), home.localDate, next)
    setDismissed(next)
  }

  return (
    <div className="flex flex-col gap-[22px] pb-24 max-md:-mx-4 max-md:px-5 max-md:pt-3.5 max-md:bg-[linear-gradient(180deg,color-mix(in_oklch,var(--md-primary-container)_45%,var(--md-surface))_0%,var(--md-surface)_46%)] md:pb-8">
      <header className="flex items-center gap-5 xl:pt-2">
        <PageHeading
          repeatsTitle={false}
          className="sr-only xl:not-sr-only xl:flex-1 xl:font-display xl:text-[32px] xl:font-extrabold xl:leading-[1.1] xl:tracking-[-0.03em] xl:text-primary"
        >
          {vm.heading}
        </PageHeading>
        <HomeTopRow pill={vm.streakPill} exam={vm.exam} examTo={vm.today.planTo} localDate={home.localDate} />
      </header>

      <div className="flex flex-col gap-[22px] md:grid md:grid-cols-2 md:items-start md:gap-x-9 md:gap-y-6 xl:grid-cols-[minmax(0,.95fr)_minmax(0,1.1fr)_minmax(0,.95fr)]">
        <section aria-label="Binny" className="flex flex-col gap-[18px] md:pt-2">
          <HomeStage stage={vm.stage} onNotNow={notNow} />
          <MomentRows rows={vm.also.phone} className="md:hidden" />
          {vm.also.desktop.length > 0 ? (
            <MomentRows rows={vm.also.desktop} className="hidden border-t border-outline-variant pt-1 md:grid" />
          ) : null}
        </section>

        <section aria-label="Today and grades" className="flex flex-col gap-[22px] md:gap-6 md:pt-4">
          <TodayBlock today={vm.today} week={vm.week} />
          {vm.firstRun ? <HomeFirstRun /> : <GradeFloor floor={vm.floor} />}
          {vm.last ? <LastPaperRow last={vm.last} allPapersTo={vm.allPapersTo} className="md:hidden" /> : null}
          {vm.firstRun ? null : <WinBack rows={vm.win} />}
        </section>

        <HomeBand
          band={vm.band}
          week={vm.week}
          planTo={vm.today.planTo}
          allPapersTo={vm.allPapersTo}
          className="hidden md:col-span-2 md:grid md:grid-cols-3 md:gap-10 md:border-t md:border-outline-variant md:pt-6 xl:col-span-1 xl:grid-cols-1 xl:gap-6 xl:border-s xl:border-t-0 xl:ps-8 xl:pt-4"
        />
      </div>
    </div>
  )
}
```

`max-md:-mx-4` assumes the shell's 16px phone gutter (`--spacing-page-mobile`). Check it in the 390px screenshot (Task 12) and adjust the bleed to the shell's real padding.

- [ ] **Step 3: Write `HomeTopRow`**

```tsx
import { Link } from "react-router-dom"
import { CaretRight, Fire } from "@phosphor-icons/react"
import { CountdownPill } from "@/components/redesign"
import { cn } from "@/lib/utils"
import { FOCUS, HIT, PRESS } from "./gradeClass"
import { parseDay, type HomeVm } from "./model"

const PILL = "inline-flex min-h-8 items-center gap-1.5 rounded-chip px-[11px] py-1.5 text-[13px] font-semibold"

export function HomeTopRow({
  pill,
  exam,
  examTo,
  localDate,
}: {
  pill: HomeVm["streakPill"]
  exam: HomeVm["exam"]
  examTo: string
  localDate: string
}) {
  return (
    <div className="flex flex-1 items-center gap-2 xl:flex-none xl:gap-2.5">
      <Link
        to={pill.to}
        aria-label={`Streak: ${pill.label}. Open Me`}
        className={cn(
          PILL, HIT, PRESS, FOCUS,
          pill.lit ? "bg-tertiary-container text-on-tertiary-container" : "bg-surface-container-lowest/70 text-on-surface-variant",
        )}
      >
        <Fire size={14} weight={pill.lit ? "fill" : "regular"} aria-hidden="true" />
        {pill.label}
        <CaretRight size={14} className="-ms-0.5 opacity-55" aria-hidden="true" />
      </Link>
      {exam ? (
        <Link to={examTo} aria-label="Exam countdown. Open your study plan" className={cn("inline-flex items-center gap-1 rounded-chip", HIT, PRESS, FOCUS)}>
          <CountdownPill examDate={exam.date} now={parseDay(localDate)} />
          <CaretRight size={14} className="-ms-0.5 text-on-surface-variant opacity-55" aria-hidden="true" />
        </Link>
      ) : null}
    </div>
  )
}
```

- [ ] **Step 4: Write `HomeStage`**

```tsx
import { Link } from "react-router-dom"
import { Binny } from "@/components/redesign"
import { cn } from "@/lib/utils"
import { FOCUS, PRESS } from "./gradeClass"
import type { StageVm } from "./model"

const STAGE_IN = "@keyframes home-stage-in{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}"

export function HomeStage({ stage, onNotNow }: { stage: StageVm; onNotNow: () => void }) {
  return (
    <div
      key={stage.key}
      aria-live="polite"
      className="relative grid justify-items-center gap-3.5 pb-1 pt-1.5 text-center motion-safe:animate-[home-stage-in_var(--dur-base)_var(--ease-out)]"
    >
      <style>{STAGE_IN}</style>
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-x-0 top-[118px] mx-auto h-[30px] w-[210px] rounded-[50%] bg-[radial-gradient(closest-side,color-mix(in_oklch,var(--md-primary-container)_80%,transparent),transparent)] xl:top-[150px] xl:w-[260px]"
      />
      <div className="relative z-[1]">
        <Binny mood={stage.mood} motion={stage.motion} size={150} className="xl:hidden" aria-hidden />
        <Binny mood={stage.mood} motion={stage.motion} size={200} className="hidden xl:block" aria-hidden />
      </div>
      <p className="max-w-[26ch] text-balance text-[20px] font-bold leading-[1.38] tracking-[-0.01em] text-on-surface xl:max-w-[22ch] xl:text-[22px]">
        {stage.greeting ? <span className="xl:hidden">{stage.greeting} </span> : null}
        {stage.line}
      </p>
      <div className="grid w-full justify-items-center gap-0.5">
        <Link
          to={stage.action.to}
          data-testid="home-stage-action"
          className={cn(
            "inline-flex min-h-[54px] w-full max-w-[300px] items-center justify-center rounded-inner bg-primary px-7 text-[16px] font-bold text-on-primary",
            "shadow-[0_14px_24px_-16px_color-mix(in_oklch,var(--md-shadow)_70%,transparent)]",
            PRESS, FOCUS,
          )}
        >
          {stage.action.label}
        </Link>
        {stage.dismissible ? (
          <button
            type="button"
            onClick={onNotNow}
            title="Binny will suggest something else later"
            className={cn("min-h-11 px-3.5 text-[14px] font-semibold text-on-surface-variant", FOCUS)}
          >
            Not now
          </button>
        ) : null}
      </div>
    </div>
  )
}
```

Two `Binny` elements exist in the DOM but only one is ever displayed, so the screen still shows one Binny. If F1's `Binny` accepts a responsive size, use one element instead.

- [ ] **Step 5: Write `TodayBlock` and `WeekStrip`**

```tsx
// TodayBlock.tsx
import { Link } from "react-router-dom"
import { CaretRight, Check } from "@phosphor-icons/react"
import { GoldRing } from "@/components/redesign"
import { cn } from "@/lib/utils"
import { FOCUS, HIT, PRESS } from "./gradeClass"
import type { HomeVm } from "./model"
import { WeekStrip } from "./WeekStrip"

export function TodayBlock({ today, week }: { today: HomeVm["today"]; week: HomeVm["week"] }) {
  return (
    <div className="grid gap-3">
      <Link to={today.planTo} className={cn("inline-flex items-center gap-2 justify-self-start rounded-row py-1 pe-1.5 text-on-surface", HIT, PRESS, FOCUS)}>
        <GoldRing parts={today.parts} size={32} label={today.label} />
        <b className="text-[15px] font-bold">{today.label}</b>
        <span className="ms-1 text-[13px] font-semibold text-primary">Plan</span>
        <CaretRight size={14} weight="bold" className="text-on-surface-variant" aria-hidden="true" />
      </Link>
      <div className="flex flex-nowrap gap-1.5">
        {today.chips.map((chip) => (
          <Link
            key={chip.label}
            to={chip.to}
            className={cn(
              "inline-flex min-h-9 items-center gap-1.5 whitespace-nowrap rounded-row px-2.5 text-[13px] font-semibold",
              HIT, PRESS, FOCUS,
              chip.done ? "bg-tertiary-container/70 ps-[7px] text-on-tertiary-container" : "bg-surface-container-lowest/70 text-on-surface-variant",
            )}
          >
            {chip.done ? (
              <span className="grid size-4 place-items-center rounded-[5px] bg-tertiary text-on-tertiary">
                <Check size={10} weight="bold" aria-hidden="true" />
              </span>
            ) : (
              <span aria-hidden="true" className="size-1.5 rounded-full bg-outline" />
            )}
            {chip.label}
            {chip.done ? <span className="sr-only">, done</span> : null}
          </Link>
        ))}
      </div>
      <WeekStrip days={week} className="-mt-0.5 md:hidden" />
    </div>
  )
}
```

```tsx
// WeekStrip.tsx
import { Link } from "react-router-dom"
import { Check } from "@phosphor-icons/react"
import { cn } from "@/lib/utils"
import { FOCUS } from "./gradeClass"
import type { HomeVm } from "./model"

export function WeekStrip({ days, className }: { days: HomeVm["week"]; className?: string }) {
  return (
    <ol aria-label="This week" className={cn("grid grid-cols-7 gap-1", className)}>
      {days.map((d) => (
        <li key={d.day}>
          <Link
            to={d.to}
            aria-label={d.ariaLabel}
            aria-current={d.isToday ? "date" : undefined}
            className={cn("grid min-h-11 justify-items-center gap-[5px] rounded-chip py-1.5 text-[12px] font-semibold", FOCUS, d.isToday ? "text-primary" : "text-on-surface-variant")}
          >
            <span aria-hidden="true">{d.letter}</span>
            <span
              aria-hidden="true"
              className={cn(
                "grid size-5 place-items-center rounded-full text-on-tertiary",
                d.done ? "bg-tertiary" : "ring-2 ring-inset ring-outline",
                d.isToday && !d.done && "ring-[2.5px] ring-primary",
                d.isToday && d.done && "outline-2 outline-primary",
              )}
            >
              {d.done ? <Check size={12} weight="bold" /> : null}
            </span>
          </Link>
        </li>
      ))}
    </ol>
  )
}
```

- [ ] **Step 6: Write `GradeFloor`, `LastPaperRow`, `WinBack`, `MomentRows`**

```tsx
// GradeFloor.tsx
import { Link } from "react-router-dom"
import { cn } from "@/lib/utils"
import { FOCUS, gradeText, PRESS } from "./gradeClass"
import type { HomeVm } from "./model"

export function GradeFloor({ floor }: { floor: HomeVm["floor"] }) {
  return (
    <nav aria-label="Your grades" className="grid grid-cols-3 border-y border-outline-variant py-3.5">
      {floor.map((f, i) => (
        <Link
          key={f.code}
          to={f.to}
          className={cn("grid justify-items-center gap-0.5 px-1 py-0.5 text-center", PRESS, FOCUS, i % 3 !== 0 && "border-s border-outline-variant")}
        >
          <b className={cn("font-display text-[44px] font-extrabold leading-none tracking-[-0.03em]", gradeText(f.grade))}>{f.grade}</b>
          <span className="mt-1 text-[15px] font-bold text-on-surface">{f.name}</span>
          <span className="text-[13px] text-on-surface-variant">{f.sub}</span>
        </Link>
      ))}
    </nav>
  )
}
```

```tsx
// LastPaperRow.tsx
import { Link } from "react-router-dom"
import { CaretRight } from "@phosphor-icons/react"
import { cn } from "@/lib/utils"
import { FOCUS, gradeText, HIT, ROW_PRESS } from "./gradeClass"
import type { HomeVm } from "./model"

export function LastPaperRow({ last, allPapersTo, className }: { last: NonNullable<HomeVm["last"]>; allPapersTo: string | null; className?: string }) {
  return (
    <div className={cn("grid grid-cols-[minmax(0,1fr)_auto] items-center gap-2", className)}>
      <Link to={last.to} className={cn("grid grid-cols-[36px_minmax(0,1fr)_18px] items-center gap-3 px-0.5 py-2.5 text-on-surface", ROW_PRESS, FOCUS)}>
        <b className={cn("text-center font-display text-[28px] font-extrabold leading-none", gradeText(last.grade))}>{last.grade}</b>
        <span className="min-w-0">
          <b className="block truncate text-[15px] font-bold">{last.title}</b>
          <span className="text-[13px] text-on-surface-variant">{last.sub}</span>
        </span>
        <CaretRight size={18} className="text-on-surface-variant" aria-hidden="true" />
      </Link>
      {allPapersTo ? (
        <Link to={allPapersTo} className={cn("flex min-h-11 items-center px-1 text-[13px] font-semibold text-primary", HIT, FOCUS)}>
          All papers
        </Link>
      ) : null}
    </div>
  )
}
```

```tsx
// WinBack.tsx
import { HairRow, HairRows } from "@/components/redesign"
import type { HomeVm } from "./model"
import { SectionLink } from "./SectionLink"

export function WinBack({ rows }: { rows: HomeVm["win"] }) {
  return (
    <section aria-labelledby="home-win" className="mt-1 grid">
      <SectionLink id="home-win" title="Win marks back" to={rows[0]?.to ?? "/student/correct"} />
      {rows.length > 0 ? (
        <HairRows aria-label="Topics to win marks back">
          {rows.map((r) => (
            <HairRow
              key={r.to}
              to={r.to}
              title={r.topic}
              sub={r.sub}
              trailing={
                <span className="font-mono text-[17px] font-bold leading-none tracking-[-0.02em] text-primary">
                  +{r.marks}
                  <small className="font-sans text-[12px] font-semibold tracking-normal text-on-surface-variant"> marks</small>
                </span>
              }
            />
          ))}
        </HairRows>
      ) : (
        <p className="py-3 text-[13px] text-on-surface-variant">Lost marks from your next paper show up here.</p>
      )}
    </section>
  )
}
```

The section heading door goes to the Practice tab once L4 lands (`homeRoutes` gains `practiceHub`); until then it opens the top topic. See item 7.

```tsx
// MomentRows.tsx
import { ChalkboardTeacher, Camera, FileText, TrendUp } from "@phosphor-icons/react"
import { HairRow, HairRows } from "@/components/redesign"
import { cn } from "@/lib/utils"
import { gradeText } from "./gradeClass"
import type { RowLeading, RowVm } from "./model"

const ICONS = { sheet: FileText, camera: Camera, class: ChalkboardTeacher, trend: TrendUp } as const

function Leading({ leading }: { leading: RowLeading }) {
  const base = "grid size-10 place-items-center rounded-full"
  if (leading.type === "grade") {
    return <span className={cn(base, "bg-surface-container font-display text-[20px] font-extrabold", gradeText(leading.grade))}>{leading.grade}</span>
  }
  if (leading.type === "initials") {
    return <span aria-hidden="true" className={cn(base, "bg-primary-container text-[13px] font-bold text-primary")}>{leading.text}</span>
  }
  const Icon = ICONS[leading.icon]
  return <span className={cn(base, "bg-primary-container text-primary")}><Icon size={20} aria-hidden="true" /></span>
}

export function MomentRows({ rows, className }: { rows: RowVm[]; className?: string }) {
  if (rows.length === 0) return null
  return (
    <div className={cn("grid", className)}>
      <HairRows aria-label="For you">
        {rows.map((r) => (
          <HairRow key={r.key} to={r.to} leading={<Leading leading={r.leading} />} title={r.title} sub={r.sub} />
        ))}
      </HairRows>
    </div>
  )
}
```

- [ ] **Step 7: Write `HomeSkeleton`**

```tsx
import { GhostRows } from "@/components/redesign"

export function HomeSkeleton() {
  return (
    <div role="status" aria-label="Loading" className="flex flex-col gap-[22px] max-md:pt-3.5">
      <div className="flex gap-2">
        <span className="h-8 w-20 rounded-chip bg-surface-container-high" />
        <span className="h-8 w-36 rounded-chip bg-surface-container-high" />
      </div>
      <div className="grid justify-items-center gap-3.5">
        <span className="size-[150px] rounded-full bg-surface-container-high" />
        <span className="h-6 w-64 max-w-full rounded-bar bg-surface-container-high" />
        <span className="h-[54px] w-full max-w-[300px] rounded-inner bg-surface-container-high" />
      </div>
      <div className="grid grid-cols-3 border-y border-outline-variant py-3.5">
        {[0, 1, 2].map((i) => (
          <span key={i} className="mx-auto h-11 w-9 rounded-row bg-surface-container-high" />
        ))}
      </div>
      <GhostRows rows={3} />
    </div>
  )
}
```

- [ ] **Step 8: Update the two source-scanning tests that read `Overview.tsx`**

`web/tests/unit/streakChip.test.ts`: replace the `describe("Overview.tsx", …)` block (lines 19-32) with:

```ts
describe("Home top row", () => {
  // Lane L1: the streak chip became Home's streak pill. It must still be a
  // real link to the student's training log (Me), on every viewport.
  const source = sourceOf("src/portals/student/home/HomeTopRow.tsx")

  it("renders the streak pill as a Link to Me", () => {
    expect(source).toContain("<Link")
    expect(source).toContain("to={pill.to}")
  })

  it("never hides the pill at a breakpoint", () => {
    const pillAt = source.indexOf("to={pill.to}")
    expect(source.slice(pillAt, pillAt + 400)).not.toMatch(/\b(?:sm|md|lg|xl):hidden\b/)
  })
})
```

`web/tests/unit/sectionHead.test.ts`: delete the `"src/portals/student/screens/Overview.tsx",` line from `MIGRATED_SCREENS`. Home has no section-head kicker by design (the mock bans kicker labels).

- [ ] **Step 9: Verify**

Temporarily give `HomeScreen` a stub for `HomeBand` and `HomeFirstRun` only if Task 9 is not done yet (create both files as `export function HomeBand() { return null }` and `export function HomeFirstRun() { return null }`, then replace them in Task 9 within the same branch before review).

Run:
```bash
cd web && npx tsc -b --noEmit && npm run lint && npm run check:copy && npx vitest run tests/unit/streakChip.test.ts tests/unit/sectionHead.test.ts tests/unit/queryStateGate.test.ts tests/unit/shellPullToRefresh.test.ts tests/unit/subjectGlyph.test.ts tests/unit/studentHomeModel.test.ts
```
Expected: all pass. Then `npm run dev`, sign in as a seeded student, open `/student` at 390px and compare with mock `P5` for each moment (use `page.route` on `**/api/student/home` with `makeHome`-shaped JSON to force each moment).

- [ ] **Step 10: Commit**

```bash
pre-commit run --files web/src/portals/student/screens/Overview.tsx web/src/portals/student/home/*.tsx web/src/portals/student/home/gradeClass.ts web/tests/unit/streakChip.test.ts web/tests/unit/sectionHead.test.ts
git commit -S -m "feat(web): student Home hub, phone layout" -- web/src/portals/student/screens/Overview.tsx web/src/portals/student/home web/tests/unit/streakChip.test.ts web/tests/unit/sectionHead.test.ts
```

---

## Task 9: Home first run, sparse, tablet and desktop

**Files:**
- Create (or replace the Task 8 stubs): `web/src/portals/student/home/HomeBand.tsx`, `web/src/portals/student/home/HomeFirstRun.tsx`
- Modify: `web/src/portals/student/home/HomeScreen.tsx` only if the screenshot check needs it

**Interfaces:**
- Consumes: Task 6 `HomeVm["band"]`, `HomeVm["week"]`; Task 8 `WeekStrip`, `MomentRows`, `SectionLink`, `gradeText`; F1 `Walkthrough`, `GhostRows`, `HairRows`, `HairRow`.
- Produces: `HomeBand({ band, week, planTo, allPapersTo, className })`, `HomeFirstRun()`.

Desktop (mock `D5`, `H6D`): three columns. Left: stage (Binny 200, line 22px) and the also rows under a hairline (teacher reply and homework are excluded here because the band's "From your class" owns them). Middle: Today without the week strip, floor, win rows. Right: the band, split from the middle by a start border, with This week (strip + "Today: Vectors · Friday: Paper 4"), Recent papers (3), From your class. Tablet: two columns, then the band as a row of three under both (`md:col-span-2 md:grid-cols-3`).

- [ ] **Step 1: Write `HomeBand`**

```tsx
import { Fragment } from "react"
import { GhostRows, HairRow, HairRows } from "@/components/redesign"
import { cn } from "@/lib/utils"
import { gradeText } from "./gradeClass"
import type { HomeVm } from "./model"
import { MomentRows } from "./MomentRows"
import { homeRoutes } from "./routes"
import { SectionLink } from "./SectionLink"
import { WeekStrip } from "./WeekStrip"

export function HomeBand({
  band,
  week,
  planTo,
  allPapersTo,
  className,
}: {
  band: HomeVm["band"]
  week: HomeVm["week"]
  planTo: string
  allPapersTo: string | null
  className?: string
}) {
  return (
    <section aria-label="This week and your class" className={className}>
      <div className="grid content-start gap-1.5">
        <SectionLink title="This week" to={planTo} />
        <WeekStrip days={week} />
        {band.weekNext.length > 0 ? (
          <p className="mt-1.5 text-[13px] text-on-surface-variant">
            {band.weekNext.map((w, i) => (
              <Fragment key={w.when}>
                {i > 0 ? " · " : null}
                {w.when}: <b className="font-semibold text-on-surface">{w.what}</b>
              </Fragment>
            ))}
          </p>
        ) : null}
      </div>

      <div className="grid content-start gap-1.5">
        <SectionLink title="Recent papers" to={allPapersTo ?? homeRoutes.scan} />
        {band.recent.length > 0 ? (
          <HairRows aria-label="Recent papers">
            {band.recent.map((p) => (
              <HairRow
                key={p.to}
                to={p.to}
                leading={<b className={cn("w-9 text-center font-display text-[28px] font-extrabold leading-none", gradeText(p.grade))}>{p.grade}</b>}
                title={p.title}
                sub={p.sub}
              />
            ))}
          </HairRows>
        ) : (
          <>
            <GhostRows rows={2} withLeading />
            <p className="text-[13px] text-on-surface-variant">Your marked papers land here.</p>
          </>
        )}
      </div>

      <div className="grid content-start gap-1.5">
        <SectionLink title="From your class" to={homeRoutes.classes} />
        {band.classRows.length > 0 ? (
          <MomentRows rows={band.classRows} />
        ) : (
          <p className="py-2 text-[13px] text-on-surface-variant">Nothing from your class yet.</p>
        )}
      </div>
    </section>
  )
}
```

- [ ] **Step 2: Write `HomeFirstRun`** (rule-derived; no mock frame, item 1)

```tsx
import { Camera, ChartBar, Target } from "@phosphor-icons/react"
import { Walkthrough } from "@/components/redesign"
import { cn } from "@/lib/utils"

/*
 * First run: the stage already says "Let's mark your first paper" with the
 * one action. Below it, a ghost floor shows where grades will sit, and three
 * short steps say what happens next (states-r1 RQ3 pattern).
 */
export function HomeFirstRun() {
  return (
    <div className="grid gap-4">
      <div aria-hidden="true" className="grid grid-cols-3 border-y border-outline-variant py-3.5">
        {[0, 1, 2].map((i) => (
          <div key={i} className={cn("grid justify-items-center gap-1.5", i > 0 && "border-s border-outline-variant")}>
            <span className="h-11 w-9 rounded-row bg-surface-container-high" />
            <span className="h-3 w-16 rounded-bar bg-surface-container-high" />
          </div>
        ))}
      </div>
      <Walkthrough
        steps={[
          { icon: Camera, title: "Scan a paper you've sat", body: "Lemely marks it question by question." },
          { icon: ChartBar, title: "See your grades", body: "Real grade boundaries, per subject." },
          { icon: Target, title: "Win marks back", body: "Practice built from your own mistakes." },
        ]}
      />
    </div>
  )
}
```

Sparse states come from the view model and need no extra component: one paper adds the "One more paper draws your trend" row (`alsoRows`), an empty `winBack` shows the "Lost marks from your next paper show up here." line, and an empty band column shows its own one-line nudge.

- [ ] **Step 3: Verify at three widths**

Run `cd web && npx tsc -b --noEmit && npm run lint && npm run check:copy`. Then with `npm run dev`, force with `page.route('**/api/student/home', …)`: first run (`floor: [], recentPapers: [], winBack: []`), sparse (`stats.papersMarked: 1`, one floor subject, one recent paper), and the full fixture. Screenshot each at 390, 834 and 1280 into the scratchpad. Check against `D5`: three columns at 1280 with no horizontal scroll, the band split by a start border, no text under 12px, all tap targets at least 44px.

- [ ] **Step 4: Commit**

```bash
pre-commit run --files web/src/portals/student/home/HomeBand.tsx web/src/portals/student/home/HomeFirstRun.tsx web/src/portals/student/home/HomeScreen.tsx
git commit -S -m "feat(web): Home first run, sparse, tablet and desktop" -- web/src/portals/student/home/HomeBand.tsx web/src/portals/student/home/HomeFirstRun.tsx web/src/portals/student/home/HomeScreen.tsx
```

---

## Task 10: Me screen, phone and desktop, with the progress and badge sheets

**Files:**
- Create under `web/src/portals/student/home/me/`: `MeScreen.tsx`, `MeHero.tsx`, `StreakStrip.tsx`, `StatsRow.tsx`, `PeopleDoors.tsx`, `BadgeRow.tsx`, `YourSubjects.tsx`, `RecentActivity.tsx`, `AccountRows.tsx`, `ProgressSheet.tsx`, `BadgesSheet.tsx`, `MeSkeleton.tsx`
- Replace: `web/src/portals/student/screens/Profile.tsx` (whole file)

**Interfaces:**
- Consumes: `useXpProfile` (`@/lib/hooks/useXpApi`), `useProfile` (`@/lib/hooks/useMeApi`), `useStudentHome`, `useMyClasses`, `useLeaderboard` (`@/lib/hooks/useLeaderboardApi`), `useFriends` (`@/lib/hooks/useFriendApi`), `useParentLinks` (`@/lib/hooks/useStudentApi`), `useDeletedPapers` (`@/lib/hooks/usePaperDeletionApi`), `useOverlayState` (`@/lib/nav/useOverlayState`); Task 7 model; Task 8 `SectionLink`, `gradeText`, `ROW_PRESS`, `PRESS`, `FOCUS`; F1 `Binny`, `KeyRing`, `HairRows`, `HairRow`, `GhostRows`; `Celebrate`, `CountUp`, `MilestoneSticker` (`@/components/ui/celebration`); `Sheet`, `SheetContent`, `SheetTitle`, `SheetDescription` (`@/components/ui/sheet`, `side="adaptive"`); `Chip` (`@/components/ui/chip`); `Meter` (`@/components/ui/primitives`); `BarChart` (`@/components/ui/lazy-chart`).
- Produces: `Profile()` route entry rendering `MeScreen`.

Component tree (mock `ME6` phone, `MED6` desktop):

```
Profile → MeScreen
├─ PageHeading "Me" (sr-only <md; desktop header .dtop)
└─ QueryState(xp): MeSkeleton | error (live P7 copy) |
   grid (phone: one column in mock order via `order-*`; md: two columns)
   ├─ col 1: MeHero(1) · StreakStrip(2) · StatsRow(3) · BadgeRow(5) · YourSubjects(6)
   └─ col 2: PeopleDoors(4) · RecentActivity(7) · AccountRows(8)
├─ ProgressSheet (streak strip tap)  live P2, P4, P5, P6
└─ BadgesSheet ("All badges")
```

- [ ] **Step 1: Write the entry file**

```tsx
import { MeScreen } from "../home/me/MeScreen"

/* The Me screen (redesign lane L1, mock student-r2/home4.html ME2/DME). Route entry only. */
export function Profile() {
  return <MeScreen />
}
```

- [ ] **Step 2: Write `MeScreen`**

```tsx
import { useState } from "react"
import { GhostRows } from "@/components/redesign"
import { PageHeading } from "@/components/ui/page-heading"
import { QueryState } from "@/components/ui/query-state"
import { useFriends } from "@/lib/hooks/useFriendApi"
import { useLeaderboard, useMyClasses } from "@/lib/hooks/useLeaderboardApi"
import { useProfile } from "@/lib/hooks/useMeApi"
import { useDeletedPapers } from "@/lib/hooks/usePaperDeletionApi"
import { useParentLinks } from "@/lib/hooks/useStudentApi"
import { useStudentHome } from "@/lib/hooks/useStudentHomeApi"
import { useXpProfile } from "@/lib/hooks/useXpApi"
import { useOverlayState } from "@/lib/nav/useOverlayState"
import { AccountRows } from "./AccountRows"
import { BadgeRow } from "./BadgeRow"
import { BadgesSheet } from "./BadgesSheet"
import { MeHero } from "./MeHero"
import {
  accountRows,
  activityVm,
  deriveBadges,
  displayName,
  peopleVm,
  statsVm,
  subjectsVm,
} from "./meModel"
import { MeSkeleton } from "./MeSkeleton"
import { PeopleDoors } from "./PeopleDoors"
import { ProgressSheet } from "./ProgressSheet"
import { RecentActivity } from "./RecentActivity"
import { StatsRow } from "./StatsRow"
import { StreakStrip } from "./StreakStrip"
import { YourSubjects } from "./YourSubjects"

const COL = "contents md:flex md:flex-col md:gap-[18px]"

export function MeScreen() {
  const xp = useXpProfile()
  const me = useProfile()
  const home = useStudentHome()
  const classes = useMyClasses()
  const firstClass = classes.data?.classes[0]?.classId
  const board = useLeaderboard({ scope: "class", basis: "total", classId: firstClass })
  const friends = useFriends()
  const parents = useParentLinks()
  const deleted = useDeletedPapers()
  const overlayState = useOverlayState()
  const [sheet, setSheet] = useState<null | "progress" | "badges">(null)
  const name = displayName(me.data)

  const homePart = (render: (h: NonNullable<typeof home.data>) => React.ReactNode, order: string) =>
    home.data ? (
      <div className={order}>{render(home.data)}</div>
    ) : home.isError ? (
      <button type="button" onClick={() => void home.refetch()} className={`${order} min-h-11 text-start text-[13px] font-semibold text-primary`}>
        Couldn't load this part. Try again
      </button>
    ) : (
      <div className={order}><GhostRows rows={2} /></div>
    )

  return (
    <div className="flex flex-col gap-[22px] pb-24 md:pb-8">
      <header className="flex items-center gap-5">
        <PageHeading repeatsTitle className="sr-only md:not-sr-only md:flex-1 md:font-display md:text-[32px] md:font-extrabold md:leading-[1.1] md:tracking-[-0.03em] md:text-primary">
          Me
        </PageHeading>
      </header>
      <QueryState
        query={xp}
        skeleton={<MeSkeleton />}
        error={{
          heading: "Your XP could not be loaded",
          body: "This is a connection problem. Your XP and streak are safe, and nothing has been lost.",
          marginalia: "Nothing you earned is lost",
        }}
      >
        {(profile) => (
          <div className="flex flex-col gap-[22px] md:grid md:grid-cols-2 md:items-start md:gap-12">
            <div className={COL}>
              <MeHero className="order-1 md:order-none" name={name} xp={profile} avatarUrl={me.data?.avatarUrl ?? null} />
              <StreakStrip className="order-2 md:order-none" xp={profile} onOpen={() => setSheet("progress")} />
              {homePart((h) => <StatsRow stats={statsVm(h)} />, "order-3 md:order-none")}
              {homePart((h) => <BadgeRow badges={deriveBadges(h, profile)} onAll={() => setSheet("badges")} />, "order-5 md:order-none")}
              {homePart((h) => <YourSubjects rows={subjectsVm(h)} />, "order-6 md:order-none")}
            </div>
            <div className={COL}>
              <PeopleDoors
                className="order-4 md:order-none"
                doors={peopleVm({
                  classes: classes.data?.classes.length,
                  rank: firstClass ? (board.data ? board.data.viewer?.rank ?? null : undefined) : null,
                  friends: friends.data?.friends.length,
                  parents: parents.data?.parents.length,
                })}
              />
              {homePart((h) => <RecentActivity rows={activityVm(h)} />, "order-7 md:order-none")}
              <AccountRows
                className="order-8 md:order-none"
                rows={accountRows({ deletedCount: deleted.data?.papers.length, placementCode: home.data?.floor[0]?.code ?? null })}
                overlayState={overlayState}
              />
            </div>
          </div>
        )}
      </QueryState>
      <ProgressSheet open={sheet === "progress"} onOpenChange={(o) => setSheet(o ? "progress" : null)} xp={xp.data} />
      <BadgesSheet
        open={sheet === "badges"}
        onOpenChange={(o) => setSheet(o ? "badges" : null)}
        badges={home.data && xp.data ? deriveBadges(home.data, xp.data) : []}
      />
    </div>
  )
}
```

Check `useMyClasses`'s rank semantics: `viewer.rank` is `null` when the viewer has no XP this week or opted out (`web/src/lib/leaderboardTypes.ts:53-55`), which reads "Not ranked yet". No class at all also reads "Not ranked yet" (the `firstClass` guard).

- [ ] **Step 3: Write `MeHero` and `StreakStrip`**

```tsx
// MeHero.tsx
import { Link } from "react-router-dom"
import { Binny, KeyRing } from "@/components/redesign"
import { Celebrate, CountUp } from "@/components/ui/celebration"
import type { XpProfile } from "@/lib/xpTypes"
import { cn } from "@/lib/utils"
import { FOCUS } from "../gradeClass"
import { homeRoutes } from "../routes"
import { levelLine, levelProgress } from "./meModel"

export function MeHero({ name, xp, avatarUrl, className }: { name: string; xp: XpProfile; avatarUrl: string | null; className?: string }) {
  const progress = levelProgress(xp)
  const avatar = avatarUrl ? (
    <img src={avatarUrl} alt="" className="size-[70px] rounded-full object-cover md:size-16" />
  ) : (
    <span className="grid size-[70px] place-items-center rounded-full bg-primary-container font-display text-[28px] font-extrabold text-primary md:size-16">
      {name.charAt(0).toUpperCase()}
    </span>
  )
  return (
    <div className={cn("relative flex items-center gap-3.5", className)}>
      <Link to={homeRoutes.settings} aria-label="Profile and settings" className={cn("relative flex-none rounded-full", FOCUS)}>
        <KeyRing
          value={progress / 100}
          size={92}
          tone="gold"
          label={`Level ${xp.level}, ${Math.round(progress)}% of the way to level ${xp.level + 1}`}
          center={avatar}
        />
        <Celebrate
          value={xp.level}
          className="absolute -end-0.5 bottom-1 grid h-7 min-w-7 place-items-center rounded-full bg-tertiary px-1 font-mono text-[14px] font-extrabold text-on-tertiary shadow-[0_0_0_3px_var(--md-surface)]"
        >
          <CountUp value={xp.level} />
        </Celebrate>
      </Link>
      <div className="min-w-0 flex-1">
        <h2 className="truncate font-display text-[32px] font-extrabold leading-[1.05] tracking-[-0.03em] text-primary md:text-[40px]">{name}</h2>
        <span className="text-[13px] text-on-surface-variant">{levelLine(xp)}</span>
      </div>
      <div className="-me-1 flex-none self-center">
        <Binny mood="wink" motion="idle" size={66} aria-hidden />
      </div>
    </div>
  )
}
```

```tsx
// StreakStrip.tsx
import { Fire } from "@phosphor-icons/react"
import type { XpProfile } from "@/lib/xpTypes"
import { cn } from "@/lib/utils"
import { FOCUS, ROW_PRESS } from "../gradeClass"
import { streakLine, streakStrip } from "./meModel"

export function StreakStrip({ xp, onOpen, className }: { xp: XpProfile; onOpen: () => void; className?: string }) {
  const strip = streakStrip(xp)
  const line = streakLine(xp)
  return (
    <button
      type="button"
      onClick={onOpen}
      aria-label={`${line.main}${line.best ? `, ${line.best}` : ""}. Open your progress`}
      className={cn("grid gap-2 text-start text-on-surface", ROW_PRESS, FOCUS, className)}
    >
      <span aria-hidden="true" className="grid grid-cols-[repeat(14,1fr)] gap-1">
        {strip.map((d) => (
          <i
            key={d.day}
            className={cn(
              "h-[22px] rounded-[6px]",
              d.on ? (d.now ? "bg-tertiary" : "bg-tertiary/60") : "bg-surface-container-highest",
              d.now && "ring-2 ring-on-tertiary-container/60",
            )}
          />
        ))}
      </span>
      <span className="flex items-center gap-2 text-[13px] text-on-surface-variant">
        <b className="inline-flex items-center gap-[5px] text-[15px] font-bold text-on-tertiary-container">
          <Fire size={14} weight="fill" aria-hidden="true" />
          {line.main}
        </b>
        {line.best}
      </span>
    </button>
  )
}
```

- [ ] **Step 4: Write `StatsRow`, `PeopleDoors`, `BadgeRow`, `YourSubjects`, `RecentActivity`, `AccountRows`**

```tsx
// StatsRow.tsx
import { Link } from "react-router-dom"
import { cn } from "@/lib/utils"
import { FOCUS, gradeText, ROW_PRESS } from "../gradeClass"
import type { statsVm } from "./meModel"

export function StatsRow({ stats }: { stats: ReturnType<typeof statsVm> }) {
  return (
    <div className="grid grid-cols-3 border-y border-outline-variant py-3.5">
      {stats.map((s, i) => (
        <Link key={s.label} to={s.to} className={cn("grid justify-items-center gap-0.5 text-on-surface", ROW_PRESS, FOCUS, i > 0 && "border-s border-outline-variant")}>
          <b className={cn("text-[30px] font-extrabold leading-none tracking-[-0.02em]", s.grade ? cn("font-display", gradeText(s.grade)) : "font-mono text-primary")}>{s.value}</b>
          <span className="text-[13px] text-on-surface-variant">{s.label}</span>
        </Link>
      ))}
    </div>
  )
}
```

```tsx
// PeopleDoors.tsx
import { Link } from "react-router-dom"
import { ChalkboardTeacher, ChartBar, Heart, UsersThree } from "@phosphor-icons/react"
import { cn } from "@/lib/utils"
import { FOCUS, ROW_PRESS } from "../gradeClass"
import type { peopleVm } from "./meModel"

const ICON = { classes: ChalkboardTeacher, standings: ChartBar, friends: UsersThree, parents: Heart } as const

export function PeopleDoors({ doors, className }: { doors: ReturnType<typeof peopleVm>; className?: string }) {
  return (
    <nav aria-label="Your people" className={cn("grid grid-cols-4 gap-1.5 md:gap-3", className)}>
      {doors.map((d) => {
        const Icon = ICON[d.id]
        return (
          <Link key={d.id} to={d.to} className={cn("grid justify-items-center gap-1.5 text-[13px] font-semibold text-on-surface", ROW_PRESS, FOCUS)}>
            <span className="grid size-14 place-items-center rounded-tile bg-primary-container text-primary md:size-16 md:rounded-[22px]">
              <Icon size={24} aria-hidden="true" />
            </span>
            <span>{d.label}</span>
            {d.sub ? <small className="-mt-1 text-[12px] font-medium text-on-surface-variant">{d.sub}</small> : null}
          </Link>
        )
      })}
    </nav>
  )
}
```

```tsx
// BadgeRow.tsx
import { CaretRight, Clock, Fire, FileText, Star, TrendUp } from "@phosphor-icons/react"
import { cn } from "@/lib/utils"
import { FOCUS } from "../gradeClass"
import { SectionLink } from "../SectionLink"
import type { BadgeId, deriveBadges } from "./meModel"

export const BADGE_ICON: Record<BadgeId, typeof Star> = {
  "first-paper": FileText,
  "streak-7": Fire,
  "grade-up": TrendUp,
  "streak-30": Clock,
  "a-star": Star,
}

export function BadgeRow({ badges, onAll }: { badges: ReturnType<typeof deriveBadges>; onAll: () => void }) {
  return (
    <section aria-labelledby="me-badges" className="grid gap-2">
      <SectionLink id="me-badges" title="Badges" onClick={onAll} />
      <ul className="-mx-[18px] flex gap-2.5 overflow-x-auto px-[18px] [scrollbar-width:none] md:mx-0 md:justify-between md:gap-1 md:overflow-visible md:px-0">
        {badges.map((b) => {
          const Icon = BADGE_ICON[b.id]
          return (
            <li key={b.id} className="grid w-[76px] flex-none justify-items-center gap-1.5 text-center md:w-[70px]">
              <span className={cn("grid size-[52px] place-items-center rounded-full", b.earned ? "bg-tertiary-container text-on-tertiary-container" : "bg-surface-container-high text-outline")}>
                <Icon size={24} aria-hidden="true" />
              </span>
              <small className={cn("text-[12px] font-semibold leading-[1.2]", b.earned ? "text-on-surface" : "text-on-surface-variant")}>
                {b.label}
                <span className="sr-only">{b.earned ? ", earned" : ", not earned yet"}</span>
              </small>
            </li>
          )
        })}
        <li className="grid w-[76px] flex-none justify-items-center gap-1.5 text-center md:w-[70px]">
          <button type="button" onClick={onAll} className={cn("grid size-[52px] place-items-center rounded-full text-primary ring-[1.5px] ring-inset ring-outline", FOCUS)} aria-label="All badges">
            <CaretRight size={14} weight="bold" aria-hidden="true" />
          </button>
          <small className="text-[12px] font-semibold leading-[1.2] text-on-surface-variant">All badges</small>
        </li>
      </ul>
    </section>
  )
}
```

```tsx
// YourSubjects.tsx
import { HairRow, HairRows } from "@/components/redesign"
import { cn } from "@/lib/utils"
import { gradeText } from "../gradeClass"
import type { subjectsVm } from "./meModel"

export function YourSubjects({ rows }: { rows: ReturnType<typeof subjectsVm> }) {
  return (
    <section aria-labelledby="me-subjects" className="grid gap-1.5">
      <h2 id="me-subjects" className="py-1 text-[18px] font-extrabold tracking-[-0.01em] text-on-surface">Your subjects</h2>
      {rows.length > 0 ? (
        <HairRows aria-label="Your subjects">
          {rows.map((r) => (
            <HairRow
              key={r.to}
              to={r.to}
              leading={<b className={cn("w-9 text-center font-display text-[28px] font-extrabold leading-none", gradeText(r.grade))}>{r.grade}</b>}
              title={r.title}
              sub={r.sub}
            />
          ))}
        </HairRows>
      ) : (
        <p className="text-[13px] text-on-surface-variant">Your subjects appear after your first paper.</p>
      )}
    </section>
  )
}
```

```tsx
// RecentActivity.tsx
import { cn } from "@/lib/utils"
import type { activityVm } from "./meModel"

const DOT = { paper: "bg-primary", practice: "bg-primary", teacher: "bg-success" } as const

export function RecentActivity({ rows }: { rows: ReturnType<typeof activityVm> }) {
  return (
    <section aria-labelledby="me-activity" className="grid gap-1.5">
      <h2 id="me-activity" className="py-1 text-[18px] font-extrabold tracking-[-0.01em] text-on-surface">Recent activity</h2>
      {rows.length > 0 ? (
        <ul className="relative grid list-none">
          {rows.map((a, i) => (
            <li
              key={`${a.kind}-${i}`}
              className="relative grid grid-cols-[14px_minmax(0,1fr)_auto] items-start gap-3 py-[9px] before:absolute before:start-1.5 before:top-6 before:-bottom-[9px] before:w-0.5 before:bg-outline-variant before:content-[''] last:before:hidden"
            >
              <i aria-hidden="true" className={cn("mt-[3px] size-3.5 rounded-full", DOT[a.kind])} />
              <div className="min-w-0">
                <b className="block text-[15px] font-semibold text-on-surface">{a.title}</b>
                <span className="text-[13px] text-on-surface-variant">{a.sub}</span>
              </div>
              <small className="whitespace-nowrap text-[12.5px] font-medium text-on-surface-variant">{a.when}</small>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-[13px] text-on-surface-variant">Your activity shows up here.</p>
      )}
    </section>
  )
}
```

The mock gives the timeline a gold dot for an earned badge. No badge-earned event exists in the data (badges are derived), so there is no gold dot (item 8).

```tsx
// AccountRows.tsx
import { Link } from "react-router-dom"
import { CaretRight } from "@phosphor-icons/react"
import { cn } from "@/lib/utils"
import type { BackgroundState } from "@/lib/nav/useOverlayState"
import { FOCUS, ROW_PRESS } from "../gradeClass"
import type { accountRows } from "./meModel"

export function AccountRows({ rows, overlayState, className }: { rows: ReturnType<typeof accountRows>; overlayState: BackgroundState; className?: string }) {
  return (
    <ul aria-label="Help and account" className={cn("grid", className)}>
      {rows.map((r) => (
        <li key={r.id} className="[&+&]:border-t [&+&]:border-outline-variant">
          <Link
            to={r.to}
            state={r.overlay ? overlayState : undefined}
            className={cn("grid grid-cols-[auto_minmax(0,1fr)_18px] items-center gap-2.5 px-0.5 py-[13px] text-on-surface", ROW_PRESS, FOCUS)}
          >
            <b className="text-[15px] font-semibold">{r.label}</b>
            <span className="text-end text-[13px] text-on-surface-variant">{r.sub}</span>
            <CaretRight size={18} className="text-on-surface-variant" aria-hidden="true" />
          </Link>
        </li>
      ))}
    </ul>
  )
}
```

If `BackgroundState` is not exported from `useOverlayState.ts`, type the prop as `ReturnType<typeof useOverlayState>`.

- [ ] **Step 5: Write `ProgressSheet` (carries live P2, P4, P5, P6)**

```tsx
import { useMemo } from "react"
import { Snowflake } from "@phosphor-icons/react"
import { Celebrate, CountUp, MilestoneSticker } from "@/components/ui/celebration"
import { Chip } from "@/components/ui/chip"
import { BarChart } from "@/components/ui/lazy-chart"
import { Meter } from "@/components/ui/primitives"
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet"
import type { XpProfile } from "@/lib/xpTypes"
import { fillCalendar, sourceLabel } from "./meModel"

function formatDay(day: string): string {
  return new Date(`${day}T00:00:00`).toLocaleDateString("en-GB", { day: "numeric", month: "short" })
}

export function ProgressSheet({ open, onOpenChange, xp }: { open: boolean; onOpenChange: (open: boolean) => void; xp: XpProfile | undefined }) {
  const days = useMemo(() => (xp ? fillCalendar(xp) : []), [xp])
  const data = useMemo(() => days.map((d) => ({ label: formatDay(d.day), value: d.xp })), [days])
  if (!xp) return null
  const { current, longest, freezesAvailable, lastActiveOn } = xp.streak
  const peak = Math.max(1, ...xp.week.bySource.map((s) => s.xp))
  const total = days.reduce((sum, d) => sum + d.xp, 0)

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="adaptive" className="flex flex-col gap-6">
        <SheetTitle className="text-display-md">Your progress</SheetTitle>
        <SheetDescription>Everything here measures work done, never how well you did it.</SheetDescription>

        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <div role="group" aria-label="Total XP">
            <span className="text-[13px] text-on-surface-variant">Total XP</span>
            <Celebrate value={xp.totalXp} className="block font-mono text-[30px] font-extrabold text-on-surface">
              <CountUp value={xp.totalXp} />
            </Celebrate>
          </div>
          <MilestoneSticker streakDays={current} />
        </div>

        <div className="flex flex-col gap-2">
          <div className="flex flex-wrap items-center gap-2">
            <Chip tone="neutral">Longest {longest}</Chip>
            {freezesAvailable > 0 ? (
              <Chip tone="accent">
                <Snowflake size={11} weight="bold" aria-hidden="true" />
                {freezesAvailable} freeze{freezesAvailable === 1 ? "" : "s"} saved
              </Chip>
            ) : null}
          </div>
          <p className="text-body-sm text-on-surface-variant">
            {lastActiveOn === null ? "Your streak starts the first day you earn XP." : `Last earned XP on ${formatDay(lastActiveOn)}.`}
            {freezesAvailable > 0 ? " A freeze covers a day you miss, automatically." : ""}
          </p>
        </div>

        <section aria-labelledby="progress-week" className="flex flex-col gap-2.5">
          <h3 id="progress-week" className="text-[18px] font-extrabold">This week</h3>
          {xp.week.bySource.map((s) => (
            <div key={s.source} className="flex items-center gap-3">
              <span className="w-32 flex-none text-[15px] text-on-surface-variant">{sourceLabel(s.source)}</span>
              <span className="min-w-0 flex-1">
                <Meter value={(s.xp / peak) * 100} label={`${sourceLabel(s.source)}: ${s.xp} XP this week`} />
              </span>
              <span className="w-16 flex-none text-end font-mono text-[15px] text-on-surface">
                {s.xp}
                <span className="ms-1 font-sans text-[13px] text-on-surface-variant">XP</span>
              </span>
            </div>
          ))}
        </section>

        <section aria-labelledby="progress-calendar" className="flex flex-col gap-2">
          <h3 id="progress-calendar" className="text-[18px] font-extrabold">Last four weeks</h3>
          <BarChart
            data={data}
            height={180}
            tickEvery={7}
            axisLeftLegend="XP"
            formatValue={(v) => String(Math.round(v))}
            tooltipDetail={(point) => (point.value === 0 ? "No XP earned" : null)}
            ariaLabel="XP earned per day over the last four weeks"
          />
          <p className="text-body-sm text-on-surface-variant">
            {total === 0 ? "The first day you earn XP is the first bar here." : `${formatDay(xp.calendarStart)} to ${formatDay(xp.calendarEnd)}.`}
          </p>
        </section>
      </SheetContent>
    </Sheet>
  )
}
```

- [ ] **Step 6: Write `BadgesSheet` and `MeSkeleton`**

```tsx
// BadgesSheet.tsx
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet"
import { cn } from "@/lib/utils"
import { BADGE_ICON } from "./BadgeRow"
import type { deriveBadges } from "./meModel"

export function BadgesSheet({ open, onOpenChange, badges }: { open: boolean; onOpenChange: (o: boolean) => void; badges: ReturnType<typeof deriveBadges> }) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="adaptive" className="flex flex-col gap-4">
        <SheetTitle className="text-display-md">Badges</SheetTitle>
        <SheetDescription>Earned from real work only.</SheetDescription>
        <ul className="grid">
          {badges.map((b) => {
            const Icon = BADGE_ICON[b.id]
            return (
              <li key={b.id} className="grid grid-cols-[52px_minmax(0,1fr)] items-center gap-3 py-2.5 [&+&]:border-t [&+&]:border-outline-variant">
                <span className={cn("grid size-[52px] place-items-center rounded-full", b.earned ? "bg-tertiary-container text-on-tertiary-container" : "bg-surface-container-high text-outline")}>
                  <Icon size={24} aria-hidden="true" />
                </span>
                <span>
                  <b className="block text-[15px] font-semibold text-on-surface">{b.label}</b>
                  <span className="text-[13px] text-on-surface-variant">{b.earned ? "Earned" : b.hint}</span>
                </span>
              </li>
            )
          })}
        </ul>
      </SheetContent>
    </Sheet>
  )
}
```

```tsx
// MeSkeleton.tsx
import { GhostRows } from "@/components/redesign"

export function MeSkeleton() {
  return (
    <div role="status" aria-label="Loading" className="flex flex-col gap-[22px]">
      <div className="flex items-center gap-3.5">
        <span className="size-[92px] rounded-full bg-surface-container-high" />
        <span className="grid flex-1 gap-2">
          <span className="h-8 w-40 rounded-bar bg-surface-container-high" />
          <span className="h-4 w-48 rounded-bar bg-surface-container-high" />
        </span>
      </div>
      <span className="h-[22px] w-full rounded-[6px] bg-surface-container-high" />
      <GhostRows rows={4} />
    </div>
  )
}
```

- [ ] **Step 7: Verify**

Run:
```bash
cd web && npx tsc -b --noEmit && npm run lint && npm run check:copy && npx vitest run tests/unit/xpProfile.test.ts tests/unit/studentMeModel.test.ts tests/unit/queryStateGate.test.ts
```
Expected: all pass. With `npm run dev`, open `/student/profile` at 390, 834 and 1280; open both sheets; tab through every door (focus ring visible, 44px targets); compare with `ME2` and `DME`.

- [ ] **Step 8: Commit**

```bash
pre-commit run --files web/src/portals/student/screens/Profile.tsx web/src/portals/student/home/me/*.tsx
git commit -S -m "feat(web): student Me screen" -- web/src/portals/student/screens/Profile.tsx web/src/portals/student/home/me
```

---

## Task 11: Route titles, lint-test lists and Playwright

**Files:**
- Modify: `web/src/portals/student/index.tsx` (the index route `handle.title` "Dashboard" → "Home"; the `profile` route `handle.title` "Your profile" → "Me")
- Modify: `web/tests/unit/rtlSafety.test.ts`, `web/tests/unit/utilityExistence.test.ts` (append the new files)
- Modify: `web/e2e/student-journey.spec.ts`, `web/e2e/screenshots.spec.ts`
- Create: `web/e2e/student-home.spec.ts`

**Interfaces:**
- Consumes: Tasks 8–10 screens and their accessible names: `navigation "Your grades"`, `data-testid="home-stage-action"`, button "Not now", `navigation "Your people"`, text `Level N · `.
- Produces: nothing new.

- [ ] **Step 1: Route titles**

In `web/src/portals/student/index.tsx` change `handle: { title: "Dashboard", skeleton: "card-grid" }` to `handle: { title: "Home", skeleton: "card-grid" }` and `handle: { title: "Your profile", skeleton: "page-header" }` to `handle: { title: "Me", skeleton: "page-header" }`.

- [ ] **Step 2: Lint lists**

Append to the list in `rtlSafety.test.ts` (after `"src/portals/student/screens/Profile.tsx",`) and to the list in `utilityExistence.test.ts` (after its `Profile.tsx` entry):

```ts
  // Lane L1 · Home hub and Me.
  "src/portals/student/home/HomeScreen.tsx",
  "src/portals/student/home/HomeTopRow.tsx",
  "src/portals/student/home/HomeStage.tsx",
  "src/portals/student/home/TodayBlock.tsx",
  "src/portals/student/home/WeekStrip.tsx",
  "src/portals/student/home/GradeFloor.tsx",
  "src/portals/student/home/LastPaperRow.tsx",
  "src/portals/student/home/WinBack.tsx",
  "src/portals/student/home/MomentRows.tsx",
  "src/portals/student/home/HomeBand.tsx",
  "src/portals/student/home/HomeFirstRun.tsx",
  "src/portals/student/home/HomeSkeleton.tsx",
  "src/portals/student/home/SectionLink.tsx",
  "src/portals/student/home/me/MeScreen.tsx",
  "src/portals/student/home/me/MeHero.tsx",
  "src/portals/student/home/me/StreakStrip.tsx",
  "src/portals/student/home/me/StatsRow.tsx",
  "src/portals/student/home/me/PeopleDoors.tsx",
  "src/portals/student/home/me/BadgeRow.tsx",
  "src/portals/student/home/me/YourSubjects.tsx",
  "src/portals/student/home/me/RecentActivity.tsx",
  "src/portals/student/home/me/AccountRows.tsx",
  "src/portals/student/home/me/ProgressSheet.tsx",
  "src/portals/student/home/me/BadgesSheet.tsx",
  "src/portals/student/home/me/MeSkeleton.tsx",
```

Run: `cd web && npx vitest run tests/unit/rtlSafety.test.ts tests/unit/utilityExistence.test.ts`
Expected: pass. A failure names a physical property or an unresolved class: fix the component, not the test.

- [ ] **Step 3: Update the existing e2e assertions about the old Overview**

`web/e2e/student-journey.spec.ts` (the block after the login, roughly lines 38-80): replace the first-run, ledger, progressbar and "Predicted grade" assertions with:

```ts
  // Lane L1: Home replaced the Overview. The first-run view must NOT render
  // for this student (one seeded paper in 0625), and the grade floor links
  // the subject.
  await expect(page.getByText("Let's mark your first paper")).toHaveCount(0)
  const floor = page.getByRole("main").getByRole("navigation", { name: "Your grades" })
  await expect(floor).toBeVisible()
  const subjectDoor = floor.getByRole("link").first()
  await expect(subjectDoor).toHaveAttribute("href", "/student/subject/0625")
  await expect(subjectDoor).toContainText(/pts to|Top grade/)
```

`web/e2e/screenshots.spec.ts` (S-06 block, roughly lines 187-239): change the heading regex to `/(morning|afternoon|evening), /i`, replace `page.getByText("Subjects this session")` with `page.getByRole("navigation", { name: "Your grades" })`, change both `**/api/student/overview` route patterns (and their `unroute`) to `**/api/student/home`, and change `"Couldn't load your overview"` to `"Couldn't load your home"`.

`web/e2e/engagement.spec.ts:221-248` needs no change: the grade floor's subject links match `main a[href^='/student/subject/']`.

- [ ] **Step 4: Write the new happy-path spec**

`web/e2e/student-home.spec.ts`:

```ts
import { test, expect } from "@playwright/test"
import { watchConsole } from "./console-errors"
import { injectSession, readSeed } from "./seed"

test("Home's doors go somewhere real, and Me opens its people doors", async ({ page }) => {
  const seed = readSeed()
  const errors = watchConsole(page)
  const student = seed.students.correctedPaper
  await injectSession(page, { accessToken: student.accessToken, userId: student.userId, role: "student" })

  await page.goto("/student")
  const main = page.getByRole("main")
  const floor = main.getByRole("navigation", { name: "Your grades" })
  await expect(floor).toBeVisible({ timeout: 15_000 })

  const action = main.getByTestId("home-stage-action").filter({ visible: true })
  await expect(action).toBeVisible()
  expect(await action.getAttribute("href")).toMatch(/^\/student\//)

  const subject = floor.getByRole("link").first()
  const href = await subject.getAttribute("href")
  await subject.click()
  await expect(page).toHaveURL(new RegExp(`${href}$`))

  await page.goto("/student/profile")
  await expect(main.getByText(/Level \d+ · /)).toBeVisible({ timeout: 15_000 })
  await main.getByRole("navigation", { name: "Your people" }).getByRole("link", { name: /Standings/ }).click()
  await expect(page).toHaveURL(/\/student\/board$/)

  expect(errors, `console/page errors: ${JSON.stringify(errors, null, 2)}`).toEqual([])
})

test("Not now moves Binny on to the next suggestion", async ({ page }) => {
  const seed = readSeed()
  const student = seed.students.correctedPaper
  await injectSession(page, { accessToken: student.accessToken, userId: student.userId, role: "student" })
  await page.route("**/api/student/home", async (route) => {
    const response = await route.fetch()
    const body = await response.json()
    body.moments = [
      {
        kind: "result", paperId: "0", subjectCode: "0625", subjectName: "Physics", paperNumber: 1,
        awarded: 35, maximum: 40, grade: "A", previousGrade: null, focusQuestion: "3",
        recordedAt: new Date().toISOString(),
      },
    ]
    await route.fulfill({ response, json: body })
  })
  await page.goto("/student")
  const main = page.getByRole("main")
  await expect(main.getByText("35 out of 40. That's an A. Q3 is the one to fix.")).toBeVisible({ timeout: 15_000 })
  await main.getByRole("button", { name: "Not now" }).click()
  await expect(main.getByText(/35 out of 40/)).toHaveCount(0)
})
```

- [ ] **Step 5: Run only this lane's e2e specs**

Run: `cd web && npx playwright test e2e/student-home.spec.ts e2e/student-journey.spec.ts e2e/engagement.spec.ts --project=chromium`
Expected: pass. (`screenshots.spec.ts` is long; run its S-06 part only if the config supports `--grep "S-06"`, else leave it to CI.)

- [ ] **Step 6: Commit**

```bash
pre-commit run --files web/src/portals/student/index.tsx web/tests/unit/rtlSafety.test.ts web/tests/unit/utilityExistence.test.ts web/e2e/student-home.spec.ts web/e2e/student-journey.spec.ts web/e2e/screenshots.spec.ts 
git commit -S -m "test(web): Home and Me e2e, lint lists and route titles" -- web/src/portals/student/index.tsx web/tests/unit/rtlSafety.test.ts web/tests/unit/utilityExistence.test.ts web/e2e/student-home.spec.ts web/e2e/student-journey.spec.ts web/e2e/screenshots.spec.ts
```

---

## Task 12: Side-by-side fidelity, drift fixes, `/impeccable polish`

**Files:** any file under `web/src/portals/student/home/` that drifts; screenshots go to the scratchpad only (not committed).

- [ ] **Step 1: Capture the pairs.** Serve the mocks (`python -m http.server 4599 --directory .impeccable/mocks`) and the app (`cd web && npm run dev`, backend running, seeded student). For each pair, screenshot at 390×844 and 1280×800:
  - Home morning: mock `#P5` after clicking `[data-m5=morning]`, and `#D5`; app `/student` with `**/api/student/home` routed to a `makeHome()`-shaped body.
  - Home paper, tough, streak, done, back, marking: same, switching `[data-m5=…]` and the routed `moments`.
  - Me: mock `#ME2` and `#DME`; app `/student/profile`.
  - First run and sparse: app only (no mock frame), checked against the empty/sparse rules.
  Save as `<scratchpad>/l1-fidelity/<screen>-<moment>-<width>-{mock,app}.png`.
- [ ] **Step 2: Fix the drift.** Compare each pair by eye: spacing (22px rhythm), type sizes, colours, the hairlines, Binny size and position, the spot shadow, pill shapes, ring sizes. Fix in the components. Keep a list of every intentional difference for the PR (copy "!" removed, Mono stats, no page bell, stage crossfade, "That's an A").
- [ ] **Step 3: Polish.** Run `/impeccable polish` on `web/src/portals/student/home/`. Apply its fixes that keep the approved layout, flow and copy; anything that would change layout, flow or content goes to "Needs user decision".
- [ ] **Step 4: Re-run** `cd web && npx tsc -b --noEmit && npm run lint && npm run check:copy && npx vitest run tests/unit/studentHomeModel.test.ts tests/unit/studentMeModel.test.ts tests/unit/rtlSafety.test.ts tests/unit/utilityExistence.test.ts`.
- [ ] **Step 5: Commit** with explicit paths: `git commit -S -m "fix(web): Home and Me fidelity polish" -- <each changed file>`.

---

## Task 13: Keep-list check and old-code deletion

**Files:**
- Delete (if not already removed in Task 6): `web/dev-previews/student-home/`, `web/dev-previews/student-home{,-a,-b,-c}.html`, the four `student-home*` entries in `web/vite.preview.config.ts`, `web/tests/unit/studentHomeFixtures.test.ts`.
- Verify: `web/src/portals/student/screens/Overview.tsx` and `Profile.tsx` contain only the entry code from Tasks 8 and 10 (no leftover `SubjectLedgerRow`, `MomentumPanel`, `JoinClassPrompt`, `LevelCard`, `StreakCard`, `CalendarPanel`, `WeekPanel`).

- [ ] **Step 1: Search for stragglers.** Run `git grep -n "useOverview()\|deriveNextAction\|binnyMood\|todayList\|screens/Profile\"" web/src web/tests web/dev-previews`. Expected: only `web/src/portals/student/shell.tsx` (its `useOverview` call stays) and no other hit.
- [ ] **Step 2: Walk the keep-list.** For each row O1–O14, P1–P13, M1–M4, open the app (or the test) and confirm the "Where it lives after L1" column is true. Write the ticked table into the PR body draft.
- [ ] **Step 3: Placeholder scan.** `git grep -nE "TODO|FIXME|test\.skip|\.only\(" -- web/src/portals/student/home web/src/portals/student/screens/Overview.tsx web/src/portals/student/screens/Profile.tsx lemely/web/services/student_home.py lemely/web/routers/student_home.py lemely/db/student_home_repo.py tests/test_student_home_*.py web/tests/unit/studentHome*.ts web/tests/unit/studentMeModel.test.ts web/e2e/student-home.spec.ts`. Expected: no hits.
- [ ] **Step 4: Final touched-file sweep** (derive the gate list from `.github/workflows/ci.yml`; never run the full suite locally):

```bash
source /home/sico/Code/Lemely/.venv/bin/activate
ruff check lemely/web/schemas_student_home.py lemely/web/services/student_home.py lemely/web/routers/student_home.py lemely/db/student_home_repo.py lemely/web/app.py tests/test_student_home_*.py tests/test_authz_matrix_complete.py
ruff format --check lemely/web/schemas_student_home.py lemely/web/services/student_home.py lemely/web/routers/student_home.py lemely/db/student_home_repo.py tests/test_student_home_*.py
mypy lemely/web/services/student_home.py lemely/web/routers/student_home.py lemely/db/student_home_repo.py lemely/web/schemas_student_home.py
pyright lemely/web/services/student_home.py lemely/web/routers/student_home.py lemely/db/student_home_repo.py
lint-imports
PYTHONPATH="$(git rev-parse --show-toplevel)" pytest tests/test_student_home_service.py tests/test_student_home_repo.py tests/test_student_home_route.py tests/test_authz_matrix_complete.py tests/test_web_student.py -q
cd web && npm run typecheck && npm run lint && npm run check:copy && npx vitest run tests/unit/studentHome*.test.ts tests/unit/studentMeModel.test.ts tests/unit/xpProfile.test.ts tests/unit/streakChip.test.ts tests/unit/sectionHead.test.ts tests/unit/rtlSafety.test.ts tests/unit/utilityExistence.test.ts tests/unit/queryStateGate.test.ts tests/unit/shellPullToRefresh.test.ts tests/unit/subjectGlyph.test.ts && npm run build
```

Expected: all green. `npm run build` also runs `check:bundle` (postbuild); the Home chunk must stay inside the budget.

- [ ] **Step 5: Commit any deletion** with explicit paths: `git commit -S -m "chore(web): remove the old student home preview" -- <paths>`.

---

## Task 14: Push and open the PR

- [ ] **Step 1:** `git status --short --branch` shows the lane branch `redesign/l01-home-me` and a clean tree.
- [ ] **Step 2:** `git fetch origin && git rebase origin/develop`. Resolve conflicts in the shared files by keeping both sides' single lines (`app.py`, `test_authz_matrix_complete.py`, `index.tsx` titles, the lint lists). Re-run Task 13 Step 4 after a rebase that touched anything.
- [ ] **Step 3:** `git push -u origin redesign/l01-home-me`.
- [ ] **Step 4:** Open the PR against `develop` (never `main`):

```bash
gh pr create --base develop --head redesign/l01-home-me \
  --title "feat(home): student Home hub and Me (redesign L1)" \
  --body-file <scratchpad>/l1-pr-body.md
```

The body holds: summary; the new endpoint and its tenancy (student role, caller-scoped, no path id); the keep-list table ticked; the frame-to-state table; the fidelity screenshot pairs (attach or link); the list of small changes from the mock (copy "!" removed; Mono stats; no page bell; stage crossfade; "That's an A"; first-run/sparse built from rules); the "Needs user decision" items with their current default; the test commands run and their results. End with the attribution lines from the session's system reminder.

---

## Needs user decision

Each item has a recommendation that the plan already implements, so nothing blocks.

1. **No mock frames for Home/Me first run, sparse, tablet, loading or error.** `states-r1/` has none for these screens. Recommendation: build them from the empty/sparse rules as specified (walkthrough + ghost floor; "One more paper draws your trend"; tablet = two columns plus the band row) and review them in the Task 12 screenshots.
2. **Binny's line length.** The master plan says Binny lines are 2–4 words, but the approved H4/H6 stage line is a short sentence or two ("Vectors cost you 9 marks last time. Ten minutes fixes most of it."). Recommendation: keep the mock's stage lines, because they are the screen's headline and carry the key number; keep every other Binny text 2–4 words.
3. **Second notification bell.** The mock puts a bell in Home's top row; the shell's top bar already has one. Recommendation: no page bell; the shell's bell is the door.
4. **Overview features not on the mock.** Per-subject percentage, trend arrows, the momentum chart and the accuracy meters leave Home. Recommendation: accept; they live on Subject (L2's trend line) and Home keeps the "One more paper draws your trend" nudge.
5. **Streak at risk vs "never used as leverage".** Recommendation: show the moment only when no freeze is saved, with neutral (not red) styling and the mock's copy.
6. **"All papers" door.** No all-papers screen exists. Recommendation: open the last paper's subject page for now; add a papers list later as its own screen.
7. **Doors to routes owned by other lanes.** Practice tab root (L4), the all-subjects week (L9) and the Subjects tab (F1/shell) do not exist yet. Recommendation: `home/routes.ts` points at today's per-subject routes; a one-line change there when those lanes merge.
8. **Mock rows with no data source.** "You moved up to 3rd in 10B" (no rank history) and the gold "Earned a badge" timeline dot (badges are derived, never stored). Recommendation: drop both; no fabricated rows.
9. **Teacher reply wording.** There is no challenge feature yet (L7 adds it), so "replied to your challenge" becomes "checked your answer", sourced from resolved review items. Recommendation: accept; switch the copy to challenge wording once L7 lands challenge replies.
10. **Opt-out for class rank** and **softening the exam countdown** were open in the redesign decisions. Recommendation: the countdown follows the spec (neutral, Tide inside 30 days, Binny mentions it); the rank shows on Me's Standings door and respects the leaderboard's existing opt-out (`viewerOptedOut`).

## Dependencies on other lanes

- **F1** must merge first: every screen imports `Binny`, `GoldRing`, `KeyRing`, `CountdownPill`, `HairRows`, `HairRow`, `Walkthrough`, `GhostRows` from `@/components/redesign`.
- **L4** should honour `?topic=` on `/student/practice/:subjectCode` (Home's practice doors pass it), and may reuse `build_win_back` from `lemely/web/services/student_home.py` for its own "Win marks back" rows.
- **L6** can fill `questionsDone`/`questionsTotal` on the marking moment when per-question progress exists; until then the line reads "Marking your paper now."
- **L7** challenge replies can feed the teacher-reply moment later (item 9).

## Self-review

- Spec coverage: endpoint with all seven moments and every block (Tasks 1–4); client-side mood/line (Task 6); Me sections incl. level ring, streak strip, stats, people doors, badges, subjects, activity, tutoring and account rows (Tasks 7, 10); countdown pill neutral/Tide plus Binny's exam line (Tasks 6, 8); Home as hub for every door (routes table in Task 6, doors in Tasks 8–10); all states (Tasks 8–9); Playwright per screen (Task 11); fidelity, polish, keep-list, deletion, PR (Tasks 12–14).
- No migration.
- Names checked across tasks: `homeView`, `pickStage`, `alsoRows`, `homeRoutes`, `practiceTarget`, `planTarget`, `flashcardsTarget`, `STUDENT_HOME_KEY`, `useStudentHome`, `build_home`, `HomeInputs`, `StudentHomeReads.recent_teacher_replies`, `get_student_home_reads`.
