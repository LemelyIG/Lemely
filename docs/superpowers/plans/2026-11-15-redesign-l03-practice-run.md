# L3 Practice Run, Start and Result Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the practice-set take screen and the practice result screen with the approved game-like run from `.impeccable/mocks/student-r2/practice-final.html`: a start screen with an "Answer here" or "Print and scan" choice, a check after every question (multiple choice instantly, typed answers through the existing marker), combo, marks won back, autosave, resume, flags, the reveal sheets, every run state, and the new result screen.

**Architecture:** One new table (`practice_question_states`) stores each question's flag and check outcome. A new `PracticeRunService` checks one answer by running the existing `correct_paper` on a one-question scheme and stores the marker's `CorrectedQuestion`. The final submit (the existing quiz submit route) reuses those stored results, so no answer is marked twice. A new router file `lemely/web/routers/practice_run.py` (same `/api/student/practice` prefix) serves the run payload, checks, flags and the result summary. On the web side, typed API functions, TanStack Query hooks and two pure view-model modules hold every decision, and thin screens render them with the F1 kit.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, pytest (throwaway Postgres), React 19, react-router 7, TanStack Query 5, Tailwind 4, Vitest (node environment, `tests/unit/**`), Playwright.

**Lane id:** L3. **Branch:** `redesign/l03-practice-run`, cut from `develop` after F1 merges. **Worktree:** `.claude/worktrees/l03-practice-run`.

## Global Constraints

Inherits the master plan Global Constraints (`docs/superpowers/plans/2026-11-15-redesign-00-master.md`, "Global Constraints") in full. Lane-specific additions:

- **Owned files.** L3 owns `web/src/portals/student/screens/practice/PracticeSet.tsx`, `PracticeResult.tsx`, the new directories `practice/run/` and `practice/result/`, and every new file named in the File Map below. `PracticePrint.tsx` must keep working and is not restyled. L4 owns `PracticeGenerator.tsx`, the set builder and `practiceData.ts`.
- **practiceData.ts.** L3 makes exactly one named edit, in Task 18: delete `practiceResultView`, `PracticeResultView`, `practiceMarkState` and `PracticeMarkState`, which only the old result screen uses. Post the edit to the L4 lane before committing. Keep `confidenceBandTier`.
- **QuizTaker stays.** `components/quiz/QuizTaker.tsx` still serves `PlacementTest.tsx`. Do not edit it. The practice run reuses the pure helpers in `components/quiz/quizTakerData.ts` without editing them.
- **Narrow edits outside owned files.** Each must stay this small:
  - `lemely/web/app.py`: one import name and one `include_router` line.
  - `lemely/web/deps.py`: one factory, `get_practice_run_service`, plus its two imports.
  - `lemely/db/models/__init__.py`: one re-export line and one `import_all_models` name. This needs the user's approval (Needs user decision 1).
  - `lemely/db/quiz_taking_repo.py`: the answer lock in `save_answer`.
  - `lemely/db/quiz_marking_repo.py`: the reuse of stored checks in `mark_submission`.
  - `web/src/portals/student/index.tsx`: the `practice/set/:assignmentId` route handle gains `immersive: true`.
  - `tests/test_migration_waitlist_email_confirmation.py`: its "is the head" assertion.
- **Marking.** No new prompt and no new engine. A check is `correct_paper(..., expects_pages=False)` on a one-question `MarkScheme` built by `build_quiz_mark_scheme`. Every check runs inside `script_cost_scope` and logs `practice_check_cost` with `cost_usd`. The final submit makes no model call for an answer that was already checked.
- **Answer locking.** Once a question's check is `checking` or `checked`, `PUT /api/student/quizzes/{id}/answers/{ref}` returns 422 for that question. A `failed` check unlocks it, so it can be retried.
- **Scheme text is shown only after the lock.** The run payload carries scheme-point text and the correct option only inside `check` for a question whose check is `checked`. An unchecked question never carries `points`, `correctOption` or `feedback`. Task 7's leak test asserts this.
- **Copy.** UI strings come from the mock. Copy for states the mock lacks is listed in Needs user decision 7. No em dashes (`npm run check:copy`). Numbers render in `font-mono`.
- **Binny.** At most one Binny is on screen at any time. Start: happy, 112px, `idle`. Reveal right with combo of 2 or more: happy, 56px, `pop`. Checking: thinking, 64px, `idle`. Error: sad, 96px, `none`. Result: mood from the view model, 110px phone and 96px desktop, `hop`.
- **Gold only for earned things.** Gold appears only on the combo chip (F1 `ComboChip`) and on complete today-ring parts (F1 `GoldRing`).
- **Run commands.**
  - Python: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/python -m pytest <files> -q`
  - Web unit: `cd web && npx vitest run <files>`
  - Web types: `cd web && npx tsc -p tsconfig.app.json --noEmit`
  - Copy: `cd web && npm run check:copy`
  - Pre-commit: `PYTHONPATH=$PWD pre-commit run --files <touched files>`

---

## Keep-list (live features that must survive)

Every item is ticked in Task 18 and copied into the PR body.

**Route and navigation** (`web/src/portals/student/index.tsx:398-412`, `PracticeSet.tsx:12-34`)
- [ ] K1 `practice/set/:assignmentId` opens the set. Now it shows the start screen first, then the run.
- [ ] K2 Submit goes to `/student/practice/result/:id` with `state: { justSubmitted: true }` (`PracticeSet.tsx:27-29`).
- [ ] K3 "Leave for now" goes to `/student` (`PracticeSet.tsx:31`, `QuizTaker.tsx:604`). Now it opens the leave sheet first.
- [ ] K4 `practice/print/:assignmentId` and `PracticePrint.tsx` keep working, including "Answer on screen instead" back to the set (`PracticePrint.tsx:98`).
- [ ] K5 The builder's "Start now" and "Print instead" links (`PracticeGenerator.tsx:181,188`) still land on working screens.

**Loading and errors** (`QuizTaker.tsx`)
- [ ] K6 A skeleton while the set loads (`QuizTaker.tsx:184-207`). Becomes `RunSkeleton`.
- [ ] K7 Missing id: "No test to load" (`QuizTaker.tsx:527`). Becomes the ER frame with "We couldn't find this set".
- [ ] K8 403: "This test isn't yours to take." (`QuizTaker.tsx:540`). Becomes "This set isn't yours".
- [ ] K9 404: "This test couldn't be found." (`QuizTaker.tsx:542`). Becomes "We couldn't find this set".
- [ ] K10 Other load errors: `studentLoadFailureMessage` with retry (`QuizTaker.tsx:536-545`). Becomes the ER frame with "Try again".
- [ ] K11 A set with no questions: "This test has no questions" (`QuizTaker.tsx:555`).

**Answering**
- [ ] K12 The question prompt keeps real newlines with `whitespace-pre-line` (`QuizTaker.tsx:654`).
- [ ] K13 MCQ is a radiogroup with `aria-checked` (`QuizTaker.tsx:762`). Becomes 2×2 tiles.
- [ ] K14 Short answer is a single input (`QuizTaker.tsx:801`). Becomes "Your final answer".
- [ ] K15 Structured answer has working plus a final answer (`QuizTaker.tsx:818,831`).
- [ ] K16 Each question shows its marks (the `Chip` near `QuizTaker.tsx:630`). Becomes "Question 4 · 3 marks".
- [ ] K17 Each question shows its topic chip (`formatQuestionTopic`). Becomes the reveal-sheet and result-row title. See the frame table, QA.

**Autosave and resume** (`QuizTaker.tsx:40-64, 250-372, 411-428`)
- [ ] K18 Every keystroke goes to local state and `localStorage` at once (`writeCachedAnswers`, marked dirty).
- [ ] K19 A debounced 600 ms save per question (`QuizTaker.tsx:361-372`).
- [ ] K20 Saves for one question are serialised (`saveChains`) and marked clean only if unchanged (`isCacheEntryUnchanged`).
- [ ] K21 Dirty answers are resent on reconnect and after reload (`refsToRetry`, `QuizTaker.tsx:354-359`).
- [ ] K22 All pending saves flush before submit, and a failed flush blocks submit with the live message (`QuizTaker.tsx:478`).
- [ ] K23 A reload restores a dirty local edit over the server's older value (`mergeAnswers`).
- [ ] K24 Save status per question: "Saving…", "Saved", and the error copy (`QuizTaker.tsx:728-742`).
- [ ] K25 The local cache is cleared after a successful submit (`QuizTaker.tsx:485`).

**Flags**
- [ ] K26 "Flag for review" toggles per question, with `aria-pressed` (`QuizTaker.tsx:650`). Now it is stored on the server as well (Needs user decision 4).

**Offline**
- [ ] K27 The offline indicator "Offline. Answers save locally." (`QuizTaker.tsx:594`). Becomes the OF banner.

**Submit**
- [ ] K28 The unanswered warning with "Go back" or "Submit anyway" (`QuizTaker.tsx:675-686`). Becomes the SU sheet.
- [ ] K29 A submit failure shows `studentSaveFailureMessage(err)` (`QuizTaker.tsx:488`).
- [ ] K30 Submit is disabled while pending, showing "Submitting…" (`QuizTaker.tsx:686,710`).

**Dropped by design** (Needs user decision 6)
- [ ] K31 The elapsed and time-left chip and the "Less than 2 minutes left." banner (`QuizTaker.tsx:598,617`). Practice sets are created with `time_limit_minutes=None` (`practice_repo.py` `create`), so a time-left state cannot happen. The elapsed chip is dropped.
- [ ] K32 Previous/Next buttons and swipe navigation (`QuizTaker.tsx:442,698`). Replaced by tappable progress dots and check-then-next.
- [ ] K33 The class and teacher affiliation line (`QuizTaker.tsx:570`). Always null for a practice set, which is student-owned.

**Result screen** (`PracticeResult.tsx`)
- [ ] K34 `justSubmitted` narrowing from `location.state` (`PracticeResult.tsx:87-93`). The count-up runs only when just submitted.
- [ ] K35 Missing id: "No practice set selected" with "Back to dashboard" (`PracticeResult.tsx:117-124`).
- [ ] K36 Load error: "Couldn't load this practice set" plus `studentLoadFailureMessage` (`PracticeResult.tsx:125-128`).
- [ ] K37 Not submitted: "Continue the set" goes to `/student/practice/set/:id` (`PracticeResult.tsx:133-145`).
- [ ] K38 Marking: an indeterminate progress bar, "updates on its own", and "Come back to this later" (`PracticeResult.tsx:147-165`). The poll is every 4 s while `marked:false` (`usePracticeApi.ts:113`).
- [ ] K39 The awarded/maximum total in Mono (`PracticeResult.tsx:187-202`).
- [ ] K40 A per-question row with number, awarded/available, state and topic (`PracticeResult.tsx:218-231`).
- [ ] K41 The confidence summary (`ConfidenceIndicatorSummary`, `PracticeResult.tsx:205-210`). Becomes "Teacher will check this one" on low-confidence rows. The product rule is to show confidence where it matters, not as decoration.
- [ ] K42 "No questions in this set." (`PracticeResult.tsx:214-215`).
- [ ] K43 "See your study plan" goes to `/student/plan/:subjectCode` (`PracticeResult.tsx:242-248`). It is now the primary button when there is no next topic (Needs user decision 10).
- [ ] K44 "Back to dashboard" goes to `/student` (`PracticeResult.tsx:249-251`). Becomes the close button.

**Backend** (`lemely/web/routers/practice.py`, `quiz.py`)
- [ ] K45 `GET /{id}/result` is unchanged. It covers ownership 403, the not-practice 404 and the marked/unmarked shape.
- [ ] K46 `GET /{id}/export` is unchanged (it serves PracticePrint).
- [ ] K47 The quiz take, save and submit routes are unchanged for teacher quizzes and placement. Submit still awards `quiz_completed` XP and marks in the background.
- [ ] K48 `mark_submission` with no practice states takes the original code path, byte for byte.

## Frame-to-state table

Mock: `.impeccable/mocks/student-r2/practice-final.html`, built by `pr.js`. Breakpoints are 390 (phone), 768–1279 (tablet), and 1280 and up (desktop, rail from the shell).

| Frame | Real state | Component | Breakpoints | Trigger |
|---|---|---|---|---|
| `PSF` | Start, "Answer here" picked | `run/PracticeStart.tsx` | phone and tablet full width. Desktop: a centred 640px column inside the shell | `shouldShowStart(run)` is true and the student hasn't pressed Start |
| `PSS` | Start, "Print and scan" picked | `run/PracticeStart.tsx` (`mode="print"`) | same | tap the "Print and scan" radio |
| `QA` | Run, typed question (working plus final answer) | `run/PracticeRun.tsx` → `run/QuestionBody.tsx` (`kind="structured"`) | phone. Desktop uses the `DR` layout | current question kind `structured`. A `short` kind shows only "Your final answer" |
| `QB` | Run, multiple choice 2×2 | `QuestionBody` (`kind="mcq"`) | phone (`min-h-[84px]` tiles) | current question kind `mcq` |
| `RC` | Reveal sheet: checking | `run/RevealSheet.tsx` (`kind="wait"`) | all | typed check POST returned 202. Polls until `checked` or `failed` |
| `RA` | Reveal sheet: right, with combo | `RevealSheet` (`kind="ok"`) | all | check `awardedMarks >= maximumMarks`. The combo line appears only when `combo >= 2` |
| `RB` | Reveal sheet: part marks | `RevealSheet` (`kind="part"`) | all | check `0 < awardedMarks < maximumMarks` |
| (new) | Reveal sheet: no marks | `RevealSheet` (`kind="zero"`) | all | check `awardedMarks === 0` (Needs user decision 7) |
| (new) | Reveal sheet: check failed | `RevealSheet` (`kind="failed"`) | all | check `status === "failed"`, or a 60 s poll timeout |
| `ZF` | Result, marked | `PracticeResult.tsx` → `result/*` | phone | `practiceResultScreen(...).kind === "marked"` |
| `DZ` | Result, desktop | `PracticeResult.tsx` | 1280 and up: 640px centred column, Binny 96 | same |
| `LV` | Leave sheet | `run/RunSheets.tsx` `LeaveSheet` | all | tap X in the run header |
| `OF` | Offline banner, "Check when online", "Skip to next question" | `run/RunStates.tsx` `OfflineBanner` plus the footer variant | all | `useOnlineStatus()` is false |
| `SU` | Blank question at the end | `RunSheets.tsx` `BlankSheet` | all | Next on the last question while `blankPositions(...)` is not empty |
| `ER` | Couldn't load | `RunStates.tsx` `RunError` | all | run query error, missing id, 403, 404, or no questions (copy from `runErrorCopy`) |
| `DR` | Desktop run with key hints | `PracticeRun.tsx` (`lg:` classes) | 1280 and up: `max-w-[640px] mx-auto`, MCQ tiles `min-h-[110px] text-[24px]`, key hints shown | viewport 1280 and up (`sidebar:` breakpoint) |
| (live) | Result marking | `PracticeResult.tsx` `ResultMarking` | all | `kind === "marking"` |
| (live) | Result not submitted | `PracticeResult.tsx` `ResultNotSubmitted` | all | `kind === "not_submitted"` |
| (live) | Run and result loading | `RunSkeleton`, `ResultSkeleton` | all | query pending |

Tablet (768–1279) uses the phone layout centred at `max-w-[640px]`. Key hints are hidden below the `sidebar` breakpoint, which is 1280 in the shell.

## Interactions and motion

All durations and easings come from `pr.css`. `--ease` is `cubic-bezier(.2,.8,.2,1)`, the token `var(--ease-out)`. Every keyframe lives in `web/src/portals/student/screens/practice/run/practiceRun.css` and sits inside `@media (prefers-reduced-motion: no-preference)`. Under reduced motion each one falls back as listed.

| Interaction | Exact values (mock) | Reduced-motion fallback |
|---|---|---|
| Reveal sheet slides up (`.rvl`, `@keyframes rvup`) | `animation: rvup .45s var(--ease-out) both`, from `transform: translateY(40%); opacity: .4` | appears in place, no animation |
| Reveal icon pops (`.rvi`, `@keyframes pop2`) | `.5s var(--ease-out) .15s both`. 0%: `scale(.4)`. 60%: `scale(1.15)`. 100%: `scale(1)` | static |
| Checking dots (`.rvdots i`, `@keyframes bd`) | `1s infinite`, delays `0s, .15s, .3s`. 50%: `translateY(-5px); opacity: .5` | static dots. The "Checking your working…" text carries the state |
| Won bar fill (`.wbar i`) | `transition: width .5s var(--ease-out)` | `transition: none` |
| Mastery bar fill (`.lv3b i`, `@keyframes fill3`) | `1s var(--ease-out) .2s both`, from `width: <before>%` to `width: <after>%` (CSS variable `--from`) | renders at `after` width |
| MCQ tile press (`.mcq button:active`) | `transform: scale(.97)`, `transition: transform .15s var(--ease-out)` | no scale |
| Primary button press | the shell's existing `installPressFeedback` | the shell handles it |
| Combo bump | F1 `ComboChip` (hidden below 2, bumps on rise) | F1 handles it |
| Binny | F1 `Binny` `motion` prop (see Global Constraints) | F1 turns every motion into `none` |
| Leave and blank sheets | the existing `Sheet side="bottom"` slide and fade from `components/ui/sheet.tsx` | `motion-reduce:animate-none` (already in the primitive) |
| Result count-up | `CountUp` from `components/ui/celebration`, only when `justSubmitted` (K34) | `CountUp` already honours reduced motion |
| Focus ring | `outline: 2.5px solid var(--md-primary); outline-offset: 3px` on tiles and the radio cards | same |

Keyboard (desktop, `DR`): `A`–`D` (case-insensitive) pick option 1–4 while the reveal is closed and focus is not in a text field. `Enter` presses the footer's primary action (Check, Next, Try again) when focus is not in a `<textarea>`. `Escape` closes an open sheet, which Radix already handles. The key hint line reads `Press A–D to choose`, and the Check button shows `<kbd>Enter</kbd>`.

## Token mapping (mock class → app token)

| Mock value | App token / Tailwind |
|---|---|
| `--p` `#042f4f` | `primary` |
| `--pc` | `primary-container` |
| `--s` | `surface` |
| `--l`, `#fff` | `surface-container-lowest` |
| `--sh` | `surface-container-high` |
| `oklch(.9 .012 240)` (empty dot) | `surface-container-highest` |
| `--ink` | `on-surface` |
| `--v` | `on-surface-variant` |
| `--o` | `outline` |
| `--ov` | `outline-variant` |
| `--ok` | `success-text` |
| `--okc` | `success-container` |
| `--err` | `error` |
| `--errc` / `--onerrc` | `error-container` / `on-error-container` |
| `--gold` | `tertiary` (F1 kit only) |
| `--gC` (part) | `grade-c`. Part badge background: `color-mix(in oklch, var(--grade-c) 70%, black)` |
| part sheet `oklch(.97 .03 88)` | `bg-[color-mix(in_oklch,var(--grade-c)_10%,var(--md-surface-container-lowest))]` |
| part marks text `oklch(.45 .1 88)`, `.rv2` text, `.mk2.part` text | `grade-c-shell` |
| `.mk2.part` background | `bg-[color-mix(in_oklch,var(--grade-c)_16%,var(--md-surface-container-lowest))]` |
| `.offb` | `bg-tertiary-container text-on-tertiary-container` |
| `--tide` | `inverse-primary` |
| `.scrim` | the `Sheet` overlay (`bg-scrim native:bg-scrim-dialog`) |
| start gradient | `bg-[linear-gradient(180deg,color-mix(in_oklch,var(--md-primary-container)_60%,var(--md-surface)),var(--md-surface)_55%)]` |
| result gradient | `bg-[linear-gradient(180deg,var(--md-success-container),var(--md-surface)_45%)]` |
| mastery track | `linear-gradient(90deg, var(--md-error-container) 0 60%, var(--md-surface-container-high) 60% 75%, var(--md-primary-container) 75%)` |
| `'Bricolage Grotesque'` | `font-display` |
| `'Schibsted Grotesk'` | `font-sans` |
| `'JetBrains Mono'` | `font-mono` |
| radius 28 (sheet top) | `rounded-t-[28px]` |
| radius 18 (tiles, radio cards, big button) | `rounded-[18px]` (`--radius-inner`) |
| radius 16 (fields) | `rounded-[16px]` |
| radius 14 (`.icl`) | `rounded-[14px]` (`--radius-button`) |

## File map

**Backend (new)**
- `lemely/db/models/practice_runs.py`: the `PracticeCheckStatus` enum and the `PracticeQuestionState` model.
- `lemely/db/migrations/versions/0055_practice_question_states.py`: creates the table and the enum. Has a downgrade.
- `lemely/core/practice_run.py`: pure helpers (combo, resume, focus topic, covered topics, check points, mastery ratio).
- `lemely/db/practice_run_repo.py`: `PracticeRunService` and its row dataclasses and errors.
- `lemely/web/schemas_practice_run.py`: the DTOs.
- `lemely/web/routers/practice_run.py`: the routes.
- Tests: `tests/test_migration_practice_question_states.py`, `tests/test_practice_run_core.py`, `tests/test_practice_run_repo.py`, `tests/test_practice_answer_lock.py`, `tests/test_quiz_marking_reuses_checks.py`, `tests/test_web_practice_run.py`, `tests/practice_run_fixtures.py`.

**Backend (narrow edits)**
- `lemely/db/models/__init__.py`, `lemely/db/quiz_taking_repo.py`, `lemely/db/quiz_marking_repo.py`, `lemely/web/deps.py`, `lemely/web/app.py`, `tests/test_migration_waitlist_email_confirmation.py`.

**Web (new)**
- `web/src/lib/practiceRunTypes.ts`: wire types.
- `web/src/lib/practiceRunApi.ts`: typed API functions.
- `web/src/lib/hooks/usePracticeRunApi.ts`: query keys and hooks.
- `web/src/portals/student/screens/practice/run/practiceRunModel.ts`: the pure run view model and reducer.
- `web/src/portals/student/screens/practice/run/usePracticeRunController.ts`: autosave, check, poll, flag and submit wiring.
- `web/src/portals/student/screens/practice/run/practiceRun.css`: the keyframes.
- `web/src/portals/student/screens/practice/run/PracticeStart.tsx`, `PracticeRun.tsx`, `RunHeader.tsx`, `QuestionBody.tsx`, `RevealSheet.tsx`, `RunSheets.tsx`, `RunStates.tsx`.
- `web/src/portals/student/screens/practice/result/practiceResultModel.ts`: the pure result view model.
- `web/src/portals/student/screens/practice/result/MasteryBar.tsx`, `ResultGains.tsx`, `AnswerRows.tsx`, `AnswerSheet.tsx`, `ResultStates.tsx`.
- Tests: `web/tests/unit/practiceRunApi.test.ts`, `web/tests/unit/practiceRunModel.test.ts`, `web/tests/unit/practiceResultModel.test.ts`, `web/e2e/practice-run.spec.ts`.

**Web (replaced)**
- `web/src/portals/student/screens/practice/PracticeSet.tsx` (rewritten) and `PracticeResult.tsx` (rewritten).

---

## Backend tasks

### Task 1: The `practice_question_states` table, its model and its migration

**Files:**
- Create: `lemely/db/models/practice_runs.py`
- Create: `lemely/db/migrations/versions/0055_practice_question_states.py`
- Modify: `lemely/db/models/__init__.py` (one re-export line after the `quizzes` import block; add `practice_runs,` to `import_all_models`)
- Modify: `tests/test_migration_waitlist_email_confirmation.py` (the "is the head" assertion in `test_revision_chains_from_0053_and_is_the_head`)
- Test: `tests/test_migration_practice_question_states.py`

**Interfaces:**
- Produces: `PracticeCheckStatus` (`checking | checked | failed`), and `PracticeQuestionState` with columns `id, submission_id, quiz_question_id, flagged, check_status, checked_answer_text, checked_working_text, awarded_marks, corrected (JSONB), cost_usd, check_error, check_started_at, checked_at, created_at, updated_at`, unique on `(submission_id, quiz_question_id)`.

> **STOP before running this migration against any shared database.** The user must approve (Needs user decision 1). The tests below run it only on throwaway databases.

- [ ] **Step 1: Write the failing migration test**

```python
# tests/test_migration_practice_question_states.py
"""Migration 0055_practice_question_states: per-question practice-run state (L3).

Additive: one table and one enum type. The downgrade removes exactly those two.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory

from lemely.db.base import Base
from lemely.db.models import import_all_models
from tests.test_migration_tutoring_enums import current_revision, head_revision, upgrade_head

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.orm import Session, sessionmaker

import_all_models()

REVISION = "0055_practice_question_states"
DOWN_REVISION = "0054_waitlist_email_confirmation"
TABLE = "practice_question_states"
ENUM = "practicecheckstatus"
INDEX = "uq_practice_question_states"


def _tables(session: Session) -> set[str]:
    return set(
        session.execute(
            sa.text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        ).scalars()
    )


def _types(session: Session) -> set[str]:
    return set(session.execute(sa.text("SELECT typname FROM pg_type")).scalars())


def test_revision_chains_from_0054_and_is_the_head() -> None:
    script_dir = ScriptDirectory.from_config(Config("alembic.ini"))
    revision = script_dir.get_revision(REVISION)
    assert revision is not None
    assert revision.down_revision == DOWN_REVISION
    assert len(REVISION) <= 32  # alembic_version.version_num is varchar(32)
    assert head_revision() == REVISION


def test_the_table_matches_the_orm_and_is_unique_per_question(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    with migrated_sessionmaker.begin() as session:
        assert TABLE in _tables(session)
        indexes = dict(
            session.execute(
                sa.text("SELECT indexname, indexdef FROM pg_indexes WHERE tablename = :t"),
                {"t": TABLE},
            ).tuples()
        )
        assert INDEX in indexes
        assert "UNIQUE" in indexes[INDEX]
        assert "(submission_id, quiz_question_id)" in indexes[INDEX]
        diff = compare_metadata(
            MigrationContext.configure(session.connection(), opts={"compare_type": True}),
            Base.metadata,
        )
    assert [d for d in diff if TABLE in repr(d)] == []


def test_upgrade_downgrade_upgrade_round_trip(
    migrated_sessionmaker_with_downgrade: tuple[sessionmaker[Session], Callable[[str], None]],
) -> None:
    sm, downgrade_to = migrated_sessionmaker_with_downgrade

    downgrade_to(DOWN_REVISION)

    with sm() as session:
        assert current_revision(session) == DOWN_REVISION
        assert TABLE not in _tables(session)
        assert ENUM not in _types(session)

    upgrade_head()

    with sm() as session:
        assert current_revision(session) == REVISION
        assert TABLE in _tables(session)
        assert ENUM in _types(session)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/python -m pytest tests/test_migration_practice_question_states.py -q`
Expected: FAIL. `get_revision` returns `None` because the migration does not exist yet.

- [ ] **Step 3: Write the model**

```python
# lemely/db/models/practice_runs.py
"""Per-question state for a student's practice run (redesign lane L3).

One row per ``(submission, question)``, written when the student flags a
question or asks for it to be checked. ``quiz_answers`` keeps what the
student wrote. This table keeps what the run did with it: the flag, and the
outcome of the per-question check. ``corrected`` is the marker's
:class:`~lemely.core.schemas.CorrectedQuestion`, stored verbatim
(``model_dump(mode="json")``) so the final submit
(:mod:`lemely.db.quiz_marking_repo`) reuses it and never marks the same
answer twice.

Only ``practice``-kind quizzes write rows here. Teacher quizzes and
placement tests never do, so their marking path is unchanged.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from lemely.db.base import Base
from lemely.db.models.enums import TimestampMixin


class PracticeCheckStatus(enum.Enum):
    """Where one question's check is. ``failed`` is retryable and unlocks the answer."""

    checking = "checking"
    checked = "checked"
    failed = "failed"


class PracticeQuestionState(TimestampMixin, Base):
    """The flag and check outcome for one question of one practice submission."""

    __tablename__ = "practice_question_states"
    __table_args__ = (
        sa.Index(
            "uq_practice_question_states", "submission_id", "quiz_question_id", unique=True
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    submission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("quiz_submissions.id", ondelete="CASCADE"),
        nullable=False,
    )
    quiz_question_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("quiz_questions.id", ondelete="CASCADE"),
        nullable=False,
    )
    flagged: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, server_default=sa.false())
    check_status: Mapped[PracticeCheckStatus | None] = mapped_column(
        sa.Enum(PracticeCheckStatus, name="practicecheckstatus"),
        nullable=True,
    )
    checked_answer_text: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    checked_working_text: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    awarded_marks: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    corrected: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # type: ignore[type-arg]
    cost_usd: Mapped[float] = mapped_column(sa.Float, nullable=False, server_default=sa.text("0"))
    check_error: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    check_started_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    checked_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)


__all__ = ["PracticeCheckStatus", "PracticeQuestionState"]
```

- [ ] **Step 4: Register the model (narrow edit, `lemely/db/models/__init__.py`)**

Add this line directly after the `from lemely.db.models.quizzes import (...)` block:

```python
from lemely.db.models.practice_runs import PracticeCheckStatus, PracticeQuestionState
```

In `import_all_models`, add `practice_runs,` between `otp_challenges,` and `profiles,`.

- [ ] **Step 5: Write the migration**

```python
# lemely/db/migrations/versions/0055_practice_question_states.py
"""practice question states: per-question flag and check outcome for the practice run (L3).

Revision ID: 0055_practice_question_states
Revises: 0054_waitlist_email_confirmation
Create Date: 2026-11-15 00:00:00.000000

One new table and one new enum type. Entirely additive.

* ``practice_question_states``: one row per (quiz submission, quiz question)
  once the student flags the question or asks for it to be checked. Holds the
  flag, the check status (``practicecheckstatus``), the answer snapshot that
  was checked, the awarded marks, the marker's ``CorrectedQuestion`` as JSONB,
  the model cost and any error. Unique on ``(submission_id, quiz_question_id)``.
  Rows cascade with their submission and question.

``downgrade`` drops the table (its index goes with it) and the enum type, nothing else.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
# Kept to <=32 chars: alembic_version.version_num is varchar(32).
revision: str = "0055_practice_question_states"
down_revision: str | Sequence[str] | None = "0054_waitlist_email_confirmation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "practice_question_states",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("submission_id", sa.UUID(), nullable=False),
        sa.Column("quiz_question_id", sa.UUID(), nullable=False),
        sa.Column("flagged", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column(
            "check_status",
            sa.Enum("checking", "checked", "failed", name="practicecheckstatus"),
            nullable=True,
        ),
        sa.Column("checked_answer_text", sa.Text(), nullable=True),
        sa.Column("checked_working_text", sa.Text(), nullable=True),
        sa.Column("awarded_marks", sa.Integer(), nullable=True),
        sa.Column("corrected", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("cost_usd", sa.Float(), server_default=sa.text("0"), nullable=False),
        sa.Column("check_error", sa.Text(), nullable=True),
        sa.Column("check_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["submission_id"],
            ["quiz_submissions.id"],
            name=op.f("fk_practice_question_states_submission_id_quiz_submissions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["quiz_question_id"],
            ["quiz_questions.id"],
            name=op.f("fk_practice_question_states_quiz_question_id_quiz_questions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_practice_question_states")),
    )
    op.create_index(
        "uq_practice_question_states",
        "practice_question_states",
        ["submission_id", "quiz_question_id"],
        unique=True,
    )


def downgrade() -> None:
    """Downgrade schema: drop the table (its index goes with it) and its enum type."""
    op.drop_table("practice_question_states")
    op.execute("DROP TYPE practicecheckstatus")
```

- [ ] **Step 6: Relax the previous head assertion**

In `tests/test_migration_waitlist_email_confirmation.py`, inside `test_revision_chains_from_0053_and_is_the_head`, replace `assert head_revision() == REVISION` with:

```python
    # No longer the head once 0055 lands; it must still be on the chain.
    assert REVISION in {r.revision for r in script_dir.walk_revisions()}
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/python -m pytest tests/test_migration_practice_question_states.py tests/test_migration_waitlist_email_confirmation.py -q`
Expected: PASS. If the FK names differ from the naming convention, `compare_metadata` reports it. Fix the `op.f(...)` names to match `lemely/db/base.py`'s `NAMING_CONVENTION`.

- [ ] **Step 8: Commit**

```bash
PYTHONPATH=$PWD pre-commit run --files lemely/db/models/practice_runs.py lemely/db/models/__init__.py lemely/db/migrations/versions/0055_practice_question_states.py tests/test_migration_practice_question_states.py tests/test_migration_waitlist_email_confirmation.py
git commit -S -m "feat(db): practice_question_states table for per-question checks" -- lemely/db/models/practice_runs.py lemely/db/models/__init__.py lemely/db/migrations/versions/0055_practice_question_states.py tests/test_migration_practice_question_states.py tests/test_migration_waitlist_email_confirmation.py
```

---

### Task 2: Pure practice-run helpers

**Files:**
- Create: `lemely/core/practice_run.py`
- Test: `tests/test_practice_run_core.py`

**Interfaces:**
- Produces:
  - `combo_stats(outcomes: Sequence[tuple[int, int]]) -> tuple[int, int]` returns `(current, best)`. Input is `(awarded, maximum)` in check order.
  - `resume_index(checked: Sequence[bool]) -> int`
  - `focus_topic(included_topics: Sequence[str], question_topics: Sequence[str | None]) -> str | None`
  - `covered_topics(question_topics: Sequence[str | None]) -> tuple[str, ...]`
  - `CheckPoint(text: str, verdict: str, note: str | None)`, a frozen dataclass
  - `check_points(mark_scheme_points: Sequence[str], corrected: Mapping[str, object] | None) -> tuple[CheckPoint, ...]`
  - `mastery_ratio(rows: Iterable[tuple[int, int]]) -> float | None`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_practice_run_core.py
"""Pure helpers behind the practice run (L3): combo, resume, topics, points, mastery."""

from __future__ import annotations

from lemely.core.practice_run import (
    CheckPoint,
    check_points,
    combo_stats,
    covered_topics,
    focus_topic,
    mastery_ratio,
    resume_index,
)


def test_combo_counts_consecutive_full_marks_and_keeps_the_best_run() -> None:
    assert combo_stats([]) == (0, 0)
    assert combo_stats([(1, 1), (2, 2), (3, 3)]) == (3, 3)
    assert combo_stats([(1, 1), (2, 2), (1, 3), (1, 1)]) == (1, 2)
    assert combo_stats([(1, 1), (0, 2)]) == (0, 1)


def test_a_zero_mark_question_never_counts_as_full() -> None:
    assert combo_stats([(0, 0)]) == (0, 0)


def test_resume_picks_the_first_unchecked_question_after_the_last_checked_one() -> None:
    assert resume_index([]) == 0
    assert resume_index([False, False, False]) == 0
    assert resume_index([True, True, False, False]) == 2
    # Q2 was skipped; the student was last on Q3, so resume moves on to Q4.
    assert resume_index([True, False, True, False]) == 3
    # Nothing after the last checked one: go back to the first gap.
    assert resume_index([True, False, True]) == 1
    # Everything checked: land on the last question.
    assert resume_index([True, True]) == 1


def test_focus_topic_prefers_one_included_topic_then_one_question_topic() -> None:
    assert focus_topic(["Vectors"], ["Vectors", "Algebra"]) == "Vectors"
    assert focus_topic([], ["Vectors", "Vectors", None]) == "Vectors"
    assert focus_topic([], ["Vectors", "Algebra"]) is None
    assert focus_topic(["Vectors", "Algebra"], ["Vectors"]) == "Vectors"
    assert focus_topic([], [None, None]) is None


def test_covered_topics_keeps_first_seen_order_without_blanks() -> None:
    assert covered_topics(["Magnitude", None, "Parallel", "Magnitude"]) == ("Magnitude", "Parallel")


def test_check_points_joins_verdicts_to_scheme_text_by_position() -> None:
    corrected = {
        "point_verdicts": [
            {"point_id": "p1", "verdict": "awarded", "note": ""},
            {"point_id": "p2", "verdict": "awarded", "note": ""},
            {"point_id": "p3", "verdict": "withheld", "note": "Give 9.22 (3 s.f.)"},
            {"point_id": "p3", "verdict": "awarded", "note": "duplicate, ignored"},
        ]
    }
    points = check_points(["2a - b = (7, 6)", "Method for magnitude", "9.22"], corrected)
    assert points == (
        CheckPoint(text="2a - b = (7, 6)", verdict="awarded", note=None),
        CheckPoint(text="Method for magnitude", verdict="awarded", note=None),
        CheckPoint(text="9.22", verdict="withheld", note="Give 9.22 (3 s.f.)"),
    )


def test_check_points_falls_back_to_matched_point_ids() -> None:
    points = check_points(["A", "B"], {"point_verdicts": [], "matched_point_ids": ["p2"]})
    assert [p.verdict for p in points] == ["withheld", "awarded"]


def test_check_points_is_empty_when_the_marker_said_nothing_per_point() -> None:
    assert check_points(["A", "B"], {"point_verdicts": [], "matched_point_ids": []}) == ()
    assert check_points(["A"], None) == ()
    assert check_points([], {"matched_point_ids": ["p1"]}) == ()


def test_mastery_ratio_is_marks_over_maximum_or_none() -> None:
    assert mastery_ratio([]) is None
    assert mastery_ratio([(0, 0)]) is None
    assert mastery_ratio([(2, 4), (3, 4)]) == 0.625
```

- [ ] **Step 2: Run them to verify they fail**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/python -m pytest tests/test_practice_run_core.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'lemely.core.practice_run'`.

- [ ] **Step 3: Write the implementation**

```python
# lemely/core/practice_run.py
"""Pure helpers for the practice run (redesign lane L3). No I/O, no session.

The run checks one question at a time. These functions turn stored check
outcomes into the numbers the screen shows: the combo, where to resume,
which topic the set is about, which scheme points were met, and topic mastery.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence


@dataclass(frozen=True, slots=True)
class CheckPoint:
    """One mark-scheme point and the marker's verdict on it."""

    text: str
    verdict: str
    note: str | None


def combo_stats(outcomes: Sequence[tuple[int, int]]) -> tuple[int, int]:
    """Return ``(current, best)`` runs of full-mark answers, in check order.

    A question worth 0 marks never counts as full, so it breaks a run.
    """
    current = best = 0
    for awarded, maximum in outcomes:
        if maximum > 0 and awarded >= maximum:
            current += 1
            best = max(best, current)
        else:
            current = 0
    return current, best


def resume_index(checked: Sequence[bool]) -> int:
    """Where a returning student picks up.

    The first unchecked question after the last checked one. If there is none,
    the first unchecked question anywhere. If every question is checked, the last one.
    """
    if not checked:
        return 0
    last = max((i for i, done in enumerate(checked) if done), default=-1)
    for i in range(last + 1, len(checked)):
        if not checked[i]:
            return i
    for i, done in enumerate(checked):
        if not done:
            return i
    return len(checked) - 1


def focus_topic(
    included_topics: Sequence[str], question_topics: Sequence[str | None]
) -> str | None:
    """The one topic a set is about, or ``None`` for a mixed set."""
    if len(included_topics) == 1:
        return included_topics[0]
    distinct = {t for t in question_topics if t}
    if len(distinct) == 1:
        return next(iter(distinct))
    return None


def covered_topics(question_topics: Sequence[str | None]) -> tuple[str, ...]:
    """Distinct non-empty question topics, in first-seen order."""
    seen: dict[str, None] = {}
    for topic in question_topics:
        if topic:
            seen.setdefault(topic, None)
    return tuple(seen)


def check_points(
    mark_scheme_points: Sequence[str], corrected: Mapping[str, object] | None
) -> tuple[CheckPoint, ...]:
    """Join the marker's per-point verdicts onto the scheme text, by position.

    Point ids are ``p1..pn`` in scheme order (``quiz_question_to_scheme_question``).
    The first verdict for an id wins (``dedupe_point_verdicts``' rule). Without
    verdicts, ``matched_point_ids`` decides. If the marker reported neither, it
    said nothing per point, and an empty tuple is returned rather than a
    fabricated list of misses.
    """
    if not corrected or not mark_scheme_points:
        return ()
    raw_verdicts = corrected.get("point_verdicts") or []
    by_id: dict[str, Mapping[str, object]] = {}
    if isinstance(raw_verdicts, list):
        for verdict in raw_verdicts:
            if isinstance(verdict, dict):
                point_id = str(verdict.get("point_id"))
                by_id.setdefault(point_id, verdict)
    raw_matched = corrected.get("matched_point_ids") or []
    matched = {str(p) for p in raw_matched} if isinstance(raw_matched, list) else set()
    if not by_id and not matched:
        return ()
    points: list[CheckPoint] = []
    for i, text in enumerate(mark_scheme_points):
        point_id = f"p{i + 1}"
        found = by_id.get(point_id)
        if found is not None:
            note = str(found.get("note") or "").strip() or None
            points.append(CheckPoint(text=text, verdict=str(found.get("verdict")), note=note))
        else:
            verdict = "awarded" if point_id in matched else "withheld"
            points.append(CheckPoint(text=text, verdict=verdict, note=None))
    return tuple(points)


def mastery_ratio(rows: Iterable[tuple[int, int]]) -> float | None:
    """Marks earned over marks available, or ``None`` when nothing was available."""
    earned = available = 0
    for awarded, maximum in rows:
        earned += awarded
        available += maximum
    if available <= 0:
        return None
    return earned / available


__all__ = [
    "CheckPoint",
    "check_points",
    "combo_stats",
    "covered_topics",
    "focus_topic",
    "mastery_ratio",
    "resume_index",
]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/python -m pytest tests/test_practice_run_core.py -q`
Expected: PASS (11 tests).

- [ ] **Step 5: Commit**

```bash
PYTHONPATH=$PWD pre-commit run --files lemely/core/practice_run.py tests/test_practice_run_core.py
git commit -S -m "feat(core): pure helpers for the practice run" -- lemely/core/practice_run.py tests/test_practice_run_core.py
```

---

### Task 3: `PracticeRunService`: run payload, flags and the per-question check

**Files:**
- Create: `lemely/db/practice_run_repo.py`
- Modify: `lemely/db/quiz_marking_repo.py` (add the public alias `build_quiz_mark_scheme = _build_mark_scheme` under `_build_mark_scheme`, and add `"build_quiz_mark_scheme"` to `__all__`)
- Create: `tests/practice_run_fixtures.py`
- Test: `tests/test_practice_run_repo.py`

**Interfaces:**
- Consumes: Task 1 `PracticeQuestionState`, `PracticeCheckStatus`. Task 2 helpers. `quiz_question_to_scheme_question`, `build_quiz_mark_scheme`, `correct_paper`.
- Produces (all in `lemely.db.practice_run_repo`):
  - Errors: `PracticeRunError`, `PracticeRunNotFoundError` (404), `PracticeRunOwnershipError` (403), `PracticeRunValidationError` (422; `str(exc)` is a stable code: `"empty_answer"`, `"not_open"`, `"unknown_question"`, `"retry"`).
  - `PracticeCheckRow(question_ref: str, status: str, awarded_marks: int | None, maximum_marks: int, points: tuple[CheckPoint, ...], correct_option: str | None, feedback: str | None, needs_teacher_review: bool, failed: bool, combo: int, best_combo: int, won_marks: int)`
  - `PracticeRunQuestion(question_ref, position, topic, question_type, prompt, total_marks, mcq_options, answer_text, working_text, flagged: bool, check: PracticeCheckRow | None)`
  - `PracticeRunRow(assignment_id: uuid.UUID, subject_code: str, title: str, focus_topic: str | None, included_topics: tuple[str, ...], submission_status: str, marks_to_win: int | None, total_marks: int, questions: tuple[PracticeRunQuestion, ...], combo: int, best_combo: int, won_marks: int, resume_index: int)`
  - `CheckJob(state_id: uuid.UUID, start: bool, is_mcq: bool)`
  - `PracticeRunService(sessionmaker, gemini_client, *, marking_options=None, cost_scope=None, now=_utcnow)` with:
    - `run(student_id, assignment_id) -> PracticeRunRow`
    - `get_check(student_id, assignment_id, question_ref) -> PracticeCheckRow | None`
    - `begin_check(student_id, assignment_id, question_ref) -> CheckJob`
    - `perform_check(state_id: uuid.UUID) -> None`
    - `set_flag(student_id, assignment_id, question_ref, flagged: bool) -> bool`
  - `CHECK_STALE_AFTER = timedelta(minutes=2)`. A `checking` row older than this reads as failed and can be restarted.

- [ ] **Step 1: Write the shared fixtures**

```python
# tests/practice_run_fixtures.py
"""Shared seeding for the L3 practice-run tests.

A throwaway Postgres database per test (skipped when Postgres is unreachable,
like every repo test here), a student, and a two-question practice set built
through the real ``PracticeService.create``: one MCQ worth 1 mark, and one
calculation question worth 3 marks with three scheme points.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.core.schemas import (
    ConfidenceBand,
    CorrectedQuestion,
    CorrectionResult,
    ExamMetadata,
    PointVerdict,
)
from lemely.db.base import Base
from lemely.db.models import User, import_all_models
from lemely.db.models.enums import DifficultySource, QuestionSource, Role
from lemely.db.models.quizzes import QuizQuestion
from lemely.db.practice_repo import PracticeRequest, PracticeService
from lemely.db.question_bank_repo import NewBankQuestion, QuestionBankService
from lemely.runtime.config import DatabaseSettings

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

import_all_models()

SUBJECT = "0625"
TOPIC = "1 Motion"
TYPED_POINTS = ["2a - b = (7, 6)", "Method for magnitude", "9.22 (3 s.f.)"]


def _server_reachable(url: str) -> bool:
    server_url = make_url(url).set(database="postgres")
    engine = create_engine(server_url)
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


def seed_user(sm: sessionmaker[Session], role: Role = Role.student) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=role))
    return uid


def _seed_bank(sm: sessionmaker[Session]) -> None:
    service = QuestionBankService(sm)
    service.add_questions(
        [
            NewBankQuestion(
                subject_code=SUBJECT,
                source=QuestionSource.past_paper,
                difficulty="standard",
                difficulty_source=DifficultySource.inferred_from_marks,
                question_type="mcq",
                prompt="Which vector is parallel to (2, -3)?",
                total_marks=1,
                topic=TOPIC,
                source_question_id="0625_s23_qp_41#1",
                mcq_options=["A", "B", "C", "D"],
                mcq_answer="A",
            ),
            NewBankQuestion(
                subject_code=SUBJECT,
                source=QuestionSource.past_paper,
                difficulty="standard",
                difficulty_source=DifficultySource.inferred_from_marks,
                question_type="calculation",
                prompt="Find 2a - b and its magnitude.",
                total_marks=3,
                topic=TOPIC,
                source_question_id="0625_s23_qp_41#2",
                mark_scheme_points=list(TYPED_POINTS),
            ),
        ]
    )
    service.link_past_paper_rows()


@dataclass(frozen=True, slots=True)
class SeededSet:
    student_id: uuid.UUID
    assignment_id: uuid.UUID
    quiz_id: uuid.UUID
    mcq_ref: str
    typed_ref: str


def seed_practice_set(sm: sessionmaker[Session]) -> SeededSet:
    _seed_bank(sm)
    student = seed_user(sm)
    created = PracticeService(sm).create(
        student,
        PracticeRequest(
            subject_code=SUBJECT,
            count=2,
            topics=(TOPIC,),
            weak_topics_only=False,
            difficulty_bands=(),
            source=None,
        ),
    )
    with sm() as session:
        rows = session.scalars(
            select(QuizQuestion).where(QuizQuestion.quiz_id == created.quiz_id)
        ).all()
    types = {q.question_type: q.question_ref for q in rows}
    assert "mcq" in types and "calculation" in types, f"seed produced {types}"
    return SeededSet(
        student_id=student,
        assignment_id=created.assignment_id,
        quiz_id=created.quiz_id,
        mcq_ref=types["mcq"],
        typed_ref=types["calculation"],
    )


def fake_correction(
    question_id: str,
    awarded: int,
    maximum: int,
    *,
    verdicts: Sequence[tuple[str, str]] = (),
    needs_review: bool = False,
) -> CorrectionResult:
    """A marker result for one typed question, without a model call."""
    return CorrectionResult(
        metadata=ExamMetadata(
            subject_code=SUBJECT, paper_number=1, paper_variant=1, session_month="Specimen"
        ),
        questions=[
            CorrectedQuestion(
                question_id=question_id,
                awarded_marks=awarded,
                maximum_marks=maximum,
                confidence=ConfidenceBand.HIGH,
                confidence_score=0.92,
                needs_teacher_review=needs_review,
                marker_source="ai",
                point_verdicts=[PointVerdict(point_id=p, verdict=v) for p, v in verdicts],  # type: ignore[arg-type]
            )
        ],
    )
```

- [ ] **Step 2: Write the failing repo tests**

```python
# tests/test_practice_run_repo.py
"""PracticeRunService (L3): run payload, ownership, the per-question check, flags."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

import pytest

from lemely.db import practice_run_repo
from lemely.db.class_repo import ClassService
from lemely.db.models.practice_runs import PracticeCheckStatus, PracticeQuestionState
from lemely.db.practice_run_repo import (
    PracticeRunNotFoundError,
    PracticeRunOwnershipError,
    PracticeRunService,
    PracticeRunValidationError,
)
from lemely.db.quiz_taking_repo import QuizTakingService
from tests.practice_run_fixtures import (  # noqa: F401 - pytest fixture
    TYPED_POINTS,
    fake_correction,
    pg_sessionmaker,
    seed_practice_set,
    seed_user,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker


def _service(sm: sessionmaker[Session]) -> PracticeRunService:
    return PracticeRunService(sm, gemini_client=None)


def _taking(sm: sessionmaker[Session]) -> QuizTakingService:
    return QuizTakingService(sm, ClassService(sm))


def test_run_lists_questions_in_order_without_any_answer_key(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    seeded = seed_practice_set(pg_sessionmaker)
    _taking(pg_sessionmaker).get_take(seeded.student_id, seeded.assignment_id)
    run = _service(pg_sessionmaker).run(seeded.student_id, seeded.assignment_id)

    assert [q.position for q in run.questions] == [1, 2]
    assert run.total_marks == 4
    assert run.focus_topic == "1 Motion"
    assert run.included_topics == ("1 Motion",)
    assert run.submission_status in {"not_started", "in_progress"}
    assert run.resume_index == 0
    assert (run.combo, run.best_combo, run.won_marks) == (0, 0, 0)
    assert all(q.check is None and not q.flagged for q in run.questions)
    # No field anywhere on the row could carry the answer key.
    assert "mcq_answer" not in practice_run_repo.PracticeRunQuestion.__slots__
    assert "mark_scheme_points" not in practice_run_repo.PracticeRunQuestion.__slots__


def test_another_students_set_is_403_and_an_unknown_id_is_404(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    seeded = seed_practice_set(pg_sessionmaker)
    stranger = seed_user(pg_sessionmaker)
    with pytest.raises(PracticeRunOwnershipError):
        _service(pg_sessionmaker).run(stranger, seeded.assignment_id)
    with pytest.raises(PracticeRunNotFoundError):
        _service(pg_sessionmaker).run(seeded.student_id, uuid.uuid4())


def test_an_mcq_check_is_marked_deterministically_and_counts_for_the_combo(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    seeded = seed_practice_set(pg_sessionmaker)
    service = _service(pg_sessionmaker)
    _taking(pg_sessionmaker).save_answer(
        seeded.student_id, seeded.assignment_id, seeded.mcq_ref, answer_text="A"
    )
    job = service.begin_check(seeded.student_id, seeded.assignment_id, seeded.mcq_ref)
    assert job.start and job.is_mcq
    service.perform_check(job.state_id)

    check = service.get_check(seeded.student_id, seeded.assignment_id, seeded.mcq_ref)
    assert check is not None
    assert check.status == "checked"
    assert (check.awarded_marks, check.maximum_marks) == (1, 1)
    assert check.correct_option == "A"
    assert (check.combo, check.best_combo, check.won_marks) == (1, 1, 1)


def test_a_typed_check_stores_the_marker_result_and_its_points(
    pg_sessionmaker: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    seeded = seed_practice_set(pg_sessionmaker)
    calls: list[Any] = []

    def _fake_correct_paper(**kwargs: Any) -> Any:
        calls.append(kwargs)
        return fake_correction(
            seeded.typed_ref,
            2,
            3,
            verdicts=[("p1", "awarded"), ("p2", "awarded"), ("p3", "withheld")],
        )

    monkeypatch.setattr(practice_run_repo, "correct_paper", _fake_correct_paper)
    service = _service(pg_sessionmaker)
    _taking(pg_sessionmaker).save_answer(
        seeded.student_id,
        seeded.assignment_id,
        seeded.typed_ref,
        answer_text="sqrt(85)",
        working_text="2a = (6, 8)",
    )
    job = service.begin_check(seeded.student_id, seeded.assignment_id, seeded.typed_ref)
    assert job.start and not job.is_mcq
    pending = service.get_check(seeded.student_id, seeded.assignment_id, seeded.typed_ref)
    assert pending is not None and pending.status == "checking" and pending.points == ()

    service.perform_check(job.state_id)

    assert len(calls) == 1
    assert calls[0]["expects_pages"] is False
    scheme = calls[0]["mark_scheme"]
    assert [q.id for q in scheme.questions] == [seeded.typed_ref]
    answers = calls[0]["extracted_answers"].answers
    assert (answers[0].answer, answers[0].working_out) == ("sqrt(85)", "2a = (6, 8)")

    check = service.get_check(seeded.student_id, seeded.assignment_id, seeded.typed_ref)
    assert check is not None and check.status == "checked"
    assert (check.awarded_marks, check.maximum_marks) == (2, 3)
    assert [p.text for p in check.points] == TYPED_POINTS
    assert [p.verdict for p in check.points] == ["awarded", "awarded", "withheld"]
    assert check.correct_option is None
    assert check.combo == 0


def test_a_marker_failure_marks_the_check_failed_and_it_can_be_restarted(
    pg_sessionmaker: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    seeded = seed_practice_set(pg_sessionmaker)

    def _boom(**_kwargs: Any) -> Any:
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(practice_run_repo, "correct_paper", _boom)
    service = _service(pg_sessionmaker)
    _taking(pg_sessionmaker).save_answer(
        seeded.student_id, seeded.assignment_id, seeded.typed_ref, answer_text="9.22"
    )
    job = service.begin_check(seeded.student_id, seeded.assignment_id, seeded.typed_ref)
    service.perform_check(job.state_id)
    failed = service.get_check(seeded.student_id, seeded.assignment_id, seeded.typed_ref)
    assert failed is not None and failed.status == "failed" and failed.failed

    again = service.begin_check(seeded.student_id, seeded.assignment_id, seeded.typed_ref)
    assert again.start and again.state_id == job.state_id


def test_a_second_begin_while_checked_does_not_restart(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    seeded = seed_practice_set(pg_sessionmaker)
    service = _service(pg_sessionmaker)
    _taking(pg_sessionmaker).save_answer(
        seeded.student_id, seeded.assignment_id, seeded.mcq_ref, answer_text="B"
    )
    job = service.begin_check(seeded.student_id, seeded.assignment_id, seeded.mcq_ref)
    service.perform_check(job.state_id)
    repeat = service.begin_check(seeded.student_id, seeded.assignment_id, seeded.mcq_ref)
    assert not repeat.start


def test_an_empty_answer_cannot_be_checked(pg_sessionmaker: sessionmaker[Session]) -> None:
    seeded = seed_practice_set(pg_sessionmaker)
    _taking(pg_sessionmaker).save_answer(
        seeded.student_id, seeded.assignment_id, seeded.typed_ref, answer_text="   "
    )
    with pytest.raises(PracticeRunValidationError, match="empty_answer"):
        _service(pg_sessionmaker).begin_check(
            seeded.student_id, seeded.assignment_id, seeded.typed_ref
        )


def test_an_unknown_question_ref_is_rejected(pg_sessionmaker: sessionmaker[Session]) -> None:
    seeded = seed_practice_set(pg_sessionmaker)
    _taking(pg_sessionmaker).get_take(seeded.student_id, seeded.assignment_id)
    with pytest.raises(PracticeRunValidationError, match="unknown_question"):
        _service(pg_sessionmaker).begin_check(seeded.student_id, seeded.assignment_id, "q99")


def test_a_flag_is_stored_and_shows_in_the_run(pg_sessionmaker: sessionmaker[Session]) -> None:
    seeded = seed_practice_set(pg_sessionmaker)
    _taking(pg_sessionmaker).get_take(seeded.student_id, seeded.assignment_id)
    service = _service(pg_sessionmaker)
    assert service.set_flag(seeded.student_id, seeded.assignment_id, seeded.typed_ref, True)
    run = service.run(seeded.student_id, seeded.assignment_id)
    assert [q.flagged for q in run.questions if q.question_ref == seeded.typed_ref] == [True]
    assert not service.set_flag(seeded.student_id, seeded.assignment_id, seeded.typed_ref, False)


def test_resume_moves_past_checked_questions(pg_sessionmaker: sessionmaker[Session]) -> None:
    seeded = seed_practice_set(pg_sessionmaker)
    service = _service(pg_sessionmaker)
    _taking(pg_sessionmaker).save_answer(
        seeded.student_id, seeded.assignment_id, seeded.mcq_ref, answer_text="A"
    )
    job = service.begin_check(seeded.student_id, seeded.assignment_id, seeded.mcq_ref)
    service.perform_check(job.state_id)
    run = service.run(seeded.student_id, seeded.assignment_id)
    mcq_index = next(i for i, q in enumerate(run.questions) if q.question_ref == seeded.mcq_ref)
    expected = 1 if mcq_index == 0 else 0
    assert run.resume_index == expected
    assert run.won_marks == 1


def test_a_stale_checking_row_reads_as_failed(pg_sessionmaker: sessionmaker[Session]) -> None:
    seeded = seed_practice_set(pg_sessionmaker)
    service = _service(pg_sessionmaker)
    _taking(pg_sessionmaker).save_answer(
        seeded.student_id, seeded.assignment_id, seeded.typed_ref, answer_text="9.22"
    )
    job = service.begin_check(seeded.student_id, seeded.assignment_id, seeded.typed_ref)
    with pg_sessionmaker.begin() as session:
        row = session.get(PracticeQuestionState, job.state_id)
        assert row is not None and row.check_status == PracticeCheckStatus.checking
        assert row.check_started_at is not None
        row.check_started_at = row.check_started_at - practice_run_repo.CHECK_STALE_AFTER * 2
    check = service.get_check(seeded.student_id, seeded.assignment_id, seeded.typed_ref)
    assert check is not None and check.status == "failed"
```

- [ ] **Step 3: Run them to verify they fail**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/python -m pytest tests/test_practice_run_repo.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'lemely.db.practice_run_repo'`.

- [ ] **Step 4: Add the public scheme-builder alias in `quiz_marking_repo.py`**

Directly below `def _build_mark_scheme(...)`, add:

```python
#: Public name for the practice run's one-question check (L3,
#: ``lemely.db.practice_run_repo``). Same function, so a check and the final
#: submit build their in-memory schemes identically.
build_quiz_mark_scheme = _build_mark_scheme
```

Then add `"build_quiz_mark_scheme",` to `__all__`.

- [ ] **Step 5: Write the service**

```python
# lemely/db/practice_run_repo.py
"""Practice run service: the per-question check, flags, resume and summary (redesign L3).

Sits beside :mod:`lemely.db.practice_repo`, which builds and exports a set,
and :mod:`lemely.db.quiz_taking_repo`, which owns the submission and the saved
answers. This module adds what the redesigned run needs:

* :meth:`PracticeRunService.run`: the run payload. Questions, saved answers,
  flags, each question's check, the combo, marks won back and where to resume.
* :meth:`PracticeRunService.begin_check` and :meth:`perform_check`: mark one
  answer through the existing :func:`~lemely.io.correction_ai.correct_paper`,
  on a one-question scheme built exactly as the final submit builds it. The
  stored ``CorrectedQuestion`` is reused by
  :meth:`~lemely.db.quiz_marking_repo.QuizMarkingService.mark_submission`, so
  no answer is marked twice.
* :meth:`set_flag`, :meth:`get_check` and :meth:`summary` (Task 6).

As in :mod:`lemely.db.quiz_marking_repo`, the model call never runs inside an
open DB session. Every check runs inside the injected cost scope, and its
cost is stored on the row and logged as ``practice_check_cost``.
"""

from __future__ import annotations

import contextlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from lemely.core.practice_run import (
    CheckPoint,
    check_points,
    combo_stats,
    covered_topics,
    focus_topic,
    resume_index,
)
from lemely.core.schemas import ExtractedAnswer, ExtractedAnswers
from lemely.db.models.attempts import Attempt, WeaknessRecord
from lemely.db.models.enums import (
    AttemptOrigin,
    QuizKind,
    QuizQuestionStatus,
    QuizSubmissionStatus,
)
from lemely.db.models.practice_runs import PracticeCheckStatus, PracticeQuestionState
from lemely.db.models.quizzes import (
    Quiz,
    QuizAnswer,
    QuizAssignment,
    QuizQuestion,
    QuizSubmission,
)
from lemely.db.quiz_marking_repo import build_quiz_mark_scheme, quiz_question_to_scheme_question
from lemely.io.correction_ai import correct_paper
from lemely.runtime.config import MarkingOptions

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Sequence
    from contextlib import AbstractContextManager

    from sqlalchemy.orm import Session, sessionmaker

    from lemely.io.gemini import GeminiClient

log = structlog.get_logger(__name__)

#: A ``checking`` row older than this is treated as failed (the server
#: restarted mid-check, say). It reads as ``failed`` and can be restarted.
CHECK_STALE_AFTER = timedelta(minutes=2)

_LOCKED = (PracticeCheckStatus.checking, PracticeCheckStatus.checked)
_OPEN = (QuizSubmissionStatus.not_started, QuizSubmissionStatus.in_progress)


def _utcnow() -> datetime:
    return datetime.now(UTC)


@contextlib.contextmanager
def _no_cost_scope(_key: str) -> Iterator[dict[str, float]]:
    yield {}


class PracticeRunError(Exception):
    """Base class for practice-run errors."""


class PracticeRunNotFoundError(PracticeRunError):
    """No such assignment, or it is not a practice set (404)."""


class PracticeRunOwnershipError(PracticeRunError):
    """The practice set belongs to another student (403)."""


class PracticeRunValidationError(PracticeRunError):
    """The request cannot be honoured. ``str(exc)`` is a stable code (422)."""


@dataclass(frozen=True, slots=True)
class PracticeCheckRow:
    question_ref: str
    status: str
    awarded_marks: int | None
    maximum_marks: int
    points: tuple[CheckPoint, ...]
    correct_option: str | None
    feedback: str | None
    needs_teacher_review: bool
    failed: bool
    combo: int
    best_combo: int
    won_marks: int


@dataclass(frozen=True, slots=True)
class PracticeRunQuestion:
    question_ref: str
    position: int
    topic: str | None
    question_type: str
    prompt: str
    total_marks: int
    mcq_options: list[str] | None
    answer_text: str | None
    working_text: str | None
    flagged: bool
    check: PracticeCheckRow | None


@dataclass(frozen=True, slots=True)
class PracticeRunRow:
    assignment_id: uuid.UUID
    subject_code: str
    title: str
    focus_topic: str | None
    included_topics: tuple[str, ...]
    submission_status: str
    marks_to_win: int | None
    total_marks: int
    questions: tuple[PracticeRunQuestion, ...]
    combo: int
    best_combo: int
    won_marks: int
    resume_index: int


@dataclass(frozen=True, slots=True)
class CheckJob:
    state_id: uuid.UUID
    start: bool
    is_mcq: bool


@dataclass(frozen=True, slots=True)
class _RunStats:
    combo: int
    best_combo: int
    won_marks: int


class PracticeRunService:
    """The practice run's reads and writes on top of quiz taking and marking."""

    def __init__(
        self,
        sessionmaker: sessionmaker[Session],
        gemini_client: GeminiClient | None,
        *,
        marking_options: MarkingOptions | None = None,
        cost_scope: Callable[[str], AbstractContextManager[dict[str, float]]] | None = None,
        now: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._gemini_client = gemini_client
        self._marking_options = marking_options or MarkingOptions()
        self._cost_scope = cost_scope or _no_cost_scope
        self._now = now

    # -- Reads -------------------------------------------------------------

    def run(self, student_id: uuid.UUID | str, assignment_id: uuid.UUID | str) -> PracticeRunRow:
        """The whole run payload. Never carries an answer key for an unchecked question."""
        student_uuid = _as_uuid(student_id)
        assignment_uuid = _as_uuid(assignment_id)
        now = self._now()
        with self._sessionmaker() as session:
            _assignment, quiz = _load_owned(session, student_uuid, assignment_uuid)
            questions = _included_questions(session, quiz.id)
            submission = _find_submission(session, assignment_uuid, student_uuid)
            answers = _answers_by_question(session, submission.id) if submission else {}
            states = _states_by_question(session, submission.id) if submission else {}
            topics = _target_topics(quiz, questions)
            marks_to_win = _marks_to_win(session, student_uuid, quiz.subject_code, topics)
            status = (
                submission.status.value if submission else QuizSubmissionStatus.not_started.value
            )
            stats = _run_stats(questions, states, now)
            rows = tuple(
                PracticeRunQuestion(
                    question_ref=qq.question_ref,
                    position=qq.position,
                    topic=qq.topic,
                    question_type=qq.question_type,
                    prompt=qq.prompt,
                    total_marks=qq.total_marks,
                    mcq_options=list(qq.mcq_options) if qq.mcq_options else None,
                    answer_text=answers[qq.id].answer_text if qq.id in answers else None,
                    working_text=answers[qq.id].working_text if qq.id in answers else None,
                    flagged=bool(states[qq.id].flagged) if qq.id in states else False,
                    check=_check_row(qq, states.get(qq.id), stats, now),
                )
                for qq in questions
            )
            return PracticeRunRow(
                assignment_id=assignment_uuid,
                subject_code=quiz.subject_code,
                title=quiz.title,
                focus_topic=focus_topic(list(quiz.included_topics or []), [q.topic for q in questions]),
                included_topics=topics,
                submission_status=status,
                marks_to_win=marks_to_win,
                total_marks=sum(q.total_marks for q in questions),
                questions=rows,
                combo=stats.combo,
                best_combo=stats.best_combo,
                won_marks=stats.won_marks,
                resume_index=resume_index(
                    [r.check is not None and r.check.status == "checked" for r in rows]
                ),
            )

    def get_check(
        self,
        student_id: uuid.UUID | str,
        assignment_id: uuid.UUID | str,
        question_ref: str,
    ) -> PracticeCheckRow | None:
        """One question's check, or ``None`` if it was never checked."""
        student_uuid = _as_uuid(student_id)
        assignment_uuid = _as_uuid(assignment_id)
        now = self._now()
        with self._sessionmaker() as session:
            _assignment, quiz = _load_owned(session, student_uuid, assignment_uuid)
            questions = _included_questions(session, quiz.id)
            qq = next((q for q in questions if q.question_ref == question_ref), None)
            if qq is None:
                raise PracticeRunValidationError("unknown_question")
            submission = _find_submission(session, assignment_uuid, student_uuid)
            if submission is None:
                return None
            states = _states_by_question(session, submission.id)
            return _check_row(qq, states.get(qq.id), _run_stats(questions, states, now), now)

    # -- Writes ------------------------------------------------------------

    def begin_check(
        self,
        student_id: uuid.UUID | str,
        assignment_id: uuid.UUID | str,
        question_ref: str,
    ) -> CheckJob:
        """Lock the saved answer and mark the check as running.

        Call after the answer is saved through ``QuizTakingService.save_answer``.
        A question already ``checking`` (and not stale) or ``checked`` returns
        ``start=False``. The caller then runs nothing. A ``failed`` or stale row
        is restarted.

        Raises:
            PracticeRunValidationError: ``unknown_question``; ``not_open``
                (no submission yet, or already submitted or marked);
                ``empty_answer``; ``retry`` (a concurrent insert won the race).
        """
        student_uuid = _as_uuid(student_id)
        assignment_uuid = _as_uuid(assignment_id)
        now = self._now()
        with self._sessionmaker() as session, session.begin():
            _assignment, quiz = _load_owned(session, student_uuid, assignment_uuid)
            qq = _included_question(session, quiz.id, question_ref)
            submission = _find_submission(session, assignment_uuid, student_uuid, for_update=True)
            if submission is None or submission.status not in _OPEN:
                raise PracticeRunValidationError("not_open")
            answer = session.scalars(
                select(QuizAnswer).where(
                    QuizAnswer.submission_id == submission.id,
                    QuizAnswer.quiz_question_id == qq.id,
                )
            ).first()
            answer_text = answer.answer_text if answer else None
            working_text = answer.working_text if answer else None
            if not (answer_text or "").strip() and not (working_text or "").strip():
                raise PracticeRunValidationError("empty_answer")
            state = session.scalars(
                select(PracticeQuestionState)
                .where(
                    PracticeQuestionState.submission_id == submission.id,
                    PracticeQuestionState.quiz_question_id == qq.id,
                )
                .with_for_update()
            ).first()
            is_mcq = qq.question_type == "mcq"
            if state is not None and state.check_status in _LOCKED and not _is_stale(state, now):
                return CheckJob(state_id=state.id, start=False, is_mcq=is_mcq)
            if state is None:
                state = PracticeQuestionState(submission_id=submission.id, quiz_question_id=qq.id)
                session.add(state)
            state.check_status = PracticeCheckStatus.checking
            state.checked_answer_text = answer_text
            state.checked_working_text = working_text
            state.check_started_at = now
            state.checked_at = None
            state.awarded_marks = None
            state.corrected = None
            state.check_error = None
            try:
                session.flush()
            except IntegrityError as exc:
                raise PracticeRunValidationError("retry") from exc
            return CheckJob(state_id=state.id, start=True, is_mcq=is_mcq)

    def perform_check(self, state_id: uuid.UUID) -> None:
        """Mark one locked answer and store the outcome. Never raises for a marker failure.

        Short read session, then the model call outside any session, then a
        short write. A row that is no longer ``checking`` when the result
        lands is left alone.
        """
        with self._sessionmaker() as session:
            state = session.get(PracticeQuestionState, state_id)
            if state is None or state.check_status != PracticeCheckStatus.checking:
                return
            qq = session.get(QuizQuestion, state.quiz_question_id)
            submission = session.get(QuizSubmission, state.submission_id)
            if qq is None or submission is None:  # pragma: no cover - FKs guarantee both
                return
            assignment = session.get(QuizAssignment, submission.assignment_id)
            quiz = session.get(Quiz, assignment.quiz_id) if assignment else None
            if assignment is None or quiz is None:  # pragma: no cover - FKs guarantee both
                return
            scheme_question = quiz_question_to_scheme_question(qq)
            subject_code = quiz.subject_code
            question_ref = qq.question_ref
            extracted = ExtractedAnswers(
                paper_id=str(assignment.id),
                source_scan="quiz",
                answers=[
                    ExtractedAnswer(
                        question_id=qq.question_ref,
                        answer=state.checked_answer_text or "",
                        confidence=1.0,
                        working_out=state.checked_working_text,
                    )
                ],
            )
            cost_key = f"practice_check:{submission.id}:{qq.question_ref}"

        try:
            with self._cost_scope(cost_key) as costs:
                correction = correct_paper(
                    mark_scheme=build_quiz_mark_scheme(subject_code, [scheme_question]),
                    extracted_answers=extracted,
                    gemini_client=self._gemini_client,
                    options=self._marking_options,
                    expects_pages=False,
                )
            corrected = correction.questions[0]
            cost = float(sum(costs.values()))
        except Exception as exc:
            log.warning("practice_check_failed", state_id=str(state_id), error=str(exc))
            with self._sessionmaker() as session, session.begin():
                row = session.get(PracticeQuestionState, state_id, with_for_update=True)
                if row is not None and row.check_status == PracticeCheckStatus.checking:
                    row.check_status = PracticeCheckStatus.failed
                    row.check_error = str(exc)
            return

        log.info(
            "practice_check_cost",
            state_id=str(state_id),
            question_ref=question_ref,
            cost_usd=round(cost, 6),
        )
        with self._sessionmaker() as session, session.begin():
            row = session.get(PracticeQuestionState, state_id, with_for_update=True)
            if row is None or row.check_status != PracticeCheckStatus.checking:
                return
            row.check_status = PracticeCheckStatus.checked
            row.awarded_marks = corrected.awarded_marks
            row.corrected = corrected.model_dump(mode="json")
            row.cost_usd = cost
            row.checked_at = self._now()
            row.check_error = None

    def set_flag(
        self,
        student_id: uuid.UUID | str,
        assignment_id: uuid.UUID | str,
        question_ref: str,
        flagged: bool,
    ) -> bool:
        """Store the student's flag on one question and return it.

        Raises:
            PracticeRunValidationError: ``unknown_question``; ``not_open``.
        """
        student_uuid = _as_uuid(student_id)
        assignment_uuid = _as_uuid(assignment_id)
        with self._sessionmaker() as session, session.begin():
            _assignment, quiz = _load_owned(session, student_uuid, assignment_uuid)
            qq = _included_question(session, quiz.id, question_ref)
            submission = _find_submission(session, assignment_uuid, student_uuid, for_update=True)
            if submission is None or submission.status not in _OPEN:
                raise PracticeRunValidationError("not_open")
            state = session.scalars(
                select(PracticeQuestionState)
                .where(
                    PracticeQuestionState.submission_id == submission.id,
                    PracticeQuestionState.quiz_question_id == qq.id,
                )
                .with_for_update()
            ).first()
            if state is None:
                state = PracticeQuestionState(submission_id=submission.id, quiz_question_id=qq.id)
                session.add(state)
            state.flagged = flagged
            try:
                session.flush()
            except IntegrityError as exc:
                raise PracticeRunValidationError("retry") from exc
            return flagged


# ---------------------------------------------------------------------------
# Module helpers (session-scoped, no commits).
# ---------------------------------------------------------------------------


def _load_owned(
    session: Session, student_uuid: uuid.UUID, assignment_uuid: uuid.UUID
) -> tuple[QuizAssignment, Quiz]:
    """The caller's practice assignment and its quiz.

    Same order as ``PracticeService.result``: 404 if missing, 403 if it is
    someone else's, 404 if it is the caller's but not a practice set.
    """
    assignment = session.get(QuizAssignment, assignment_uuid)
    if assignment is None:
        raise PracticeRunNotFoundError(f"Unknown assignment: {assignment_uuid}")
    if assignment.student_id != student_uuid:
        raise PracticeRunOwnershipError(
            f"Assignment {assignment_uuid} is not assigned to student {student_uuid}"
        )
    quiz = session.get(Quiz, assignment.quiz_id)
    if quiz is None:  # pragma: no cover - FK guarantees the row exists
        raise PracticeRunError(f"Unknown quiz: {assignment.quiz_id}")
    if quiz.kind != QuizKind.practice:
        raise PracticeRunNotFoundError(f"Assignment {assignment_uuid} is not a practice set")
    return assignment, quiz


def _included_questions(session: Session, quiz_id: uuid.UUID) -> list[QuizQuestion]:
    return list(
        session.scalars(
            select(QuizQuestion)
            .where(
                QuizQuestion.quiz_id == quiz_id,
                QuizQuestion.status == QuizQuestionStatus.included,
            )
            .order_by(QuizQuestion.position)
        ).all()
    )


def _included_question(session: Session, quiz_id: uuid.UUID, question_ref: str) -> QuizQuestion:
    qq = session.scalars(
        select(QuizQuestion).where(
            QuizQuestion.quiz_id == quiz_id,
            QuizQuestion.question_ref == question_ref,
            QuizQuestion.status == QuizQuestionStatus.included,
        )
    ).first()
    if qq is None:
        raise PracticeRunValidationError("unknown_question")
    return qq


def _find_submission(
    session: Session,
    assignment_uuid: uuid.UUID,
    student_uuid: uuid.UUID,
    *,
    for_update: bool = False,
) -> QuizSubmission | None:
    stmt = select(QuizSubmission).where(
        QuizSubmission.assignment_id == assignment_uuid,
        QuizSubmission.student_id == student_uuid,
    )
    if for_update:
        stmt = stmt.with_for_update()
    return session.scalars(stmt).first()


def _answers_by_question(session: Session, submission_id: uuid.UUID) -> dict[uuid.UUID, QuizAnswer]:
    return {
        a.quiz_question_id: a
        for a in session.scalars(
            select(QuizAnswer).where(QuizAnswer.submission_id == submission_id)
        ).all()
    }


def _states_by_question(
    session: Session, submission_id: uuid.UUID
) -> dict[uuid.UUID, PracticeQuestionState]:
    return {
        s.quiz_question_id: s
        for s in session.scalars(
            select(PracticeQuestionState).where(
                PracticeQuestionState.submission_id == submission_id
            )
        ).all()
    }


def _target_topics(quiz: Quiz, questions: Sequence[QuizQuestion]) -> tuple[str, ...]:
    """The topics the set targets: the quiz's own list, else what its questions cover."""
    included = tuple(quiz.included_topics or [])
    return included or covered_topics([q.topic for q in questions])


def _is_stale(state: PracticeQuestionState, now: datetime) -> bool:
    return (
        state.check_status == PracticeCheckStatus.checking
        and state.check_started_at is not None
        and now - state.check_started_at > CHECK_STALE_AFTER
    )


def _effective_status(state: PracticeQuestionState, now: datetime) -> PracticeCheckStatus | None:
    if _is_stale(state, now):
        return PracticeCheckStatus.failed
    return state.check_status


def _run_stats(
    questions: Sequence[QuizQuestion],
    states: dict[uuid.UUID, PracticeQuestionState],
    now: datetime,
) -> _RunStats:
    by_id = {q.id: q for q in questions}
    checked = sorted(
        (
            s
            for s in states.values()
            if s.quiz_question_id in by_id
            and _effective_status(s, now) == PracticeCheckStatus.checked
            and s.awarded_marks is not None
        ),
        key=lambda s: (s.checked_at or now, by_id[s.quiz_question_id].position),
    )
    outcomes = [(s.awarded_marks or 0, by_id[s.quiz_question_id].total_marks) for s in checked]
    combo, best = combo_stats(outcomes)
    return _RunStats(combo=combo, best_combo=best, won_marks=sum(a for a, _ in outcomes))


def _check_row(
    qq: QuizQuestion,
    state: PracticeQuestionState | None,
    stats: _RunStats,
    now: datetime,
) -> PracticeCheckRow | None:
    if state is None:
        return None
    status = _effective_status(state, now)
    if status is None:
        return None
    checked = status == PracticeCheckStatus.checked
    corrected = state.corrected if checked else None
    return PracticeCheckRow(
        question_ref=qq.question_ref,
        status=status.value,
        awarded_marks=state.awarded_marks if checked else None,
        maximum_marks=qq.total_marks,
        points=check_points(list(qq.mark_scheme_points or []), corrected),
        correct_option=(
            str(corrected.get("expected_answer"))
            if corrected and qq.question_type == "mcq" and corrected.get("expected_answer")
            else None
        ),
        feedback=(str(corrected.get("feedback")) if corrected and corrected.get("feedback") else None),
        needs_teacher_review=bool(corrected.get("needs_teacher_review")) if corrected else False,
        failed=status == PracticeCheckStatus.failed,
        combo=stats.combo,
        best_combo=stats.best_combo,
        won_marks=stats.won_marks,
    )


def _marks_to_win(
    session: Session, student_uuid: uuid.UUID, subject_code: str, topics: Sequence[str]
) -> int | None:
    """What these topics cost on the student's latest paper where they cost anything.

    Only grade-bearing attempts (not quizzes, not deleted). ``None`` when no
    paper ever lost marks on these topics: the screen then counts against the
    set's own total instead.
    """
    if not topics:
        return None
    latest = session.execute(
        select(Attempt.id)
        .join(WeaknessRecord, WeaknessRecord.attempt_id == Attempt.id)
        .where(
            Attempt.user_id == student_uuid,
            Attempt.subject_code == subject_code,
            Attempt.origin != AttemptOrigin.quiz,
            Attempt.deleted_at.is_(None),
            WeaknessRecord.topic.in_(list(topics)),
            WeaknessRecord.lost_marks > 0,
        )
        .order_by(Attempt.recorded_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if latest is None:
        return None
    lost = session.scalars(
        select(WeaknessRecord.lost_marks).where(
            WeaknessRecord.attempt_id == latest,
            WeaknessRecord.topic.in_(list(topics)),
        )
    ).all()
    total = int(sum(lost))
    return total or None


def _as_uuid(value: uuid.UUID | str) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise PracticeRunNotFoundError(f"Identifier must be a UUID, got {value!r}") from exc


__all__ = [
    "CHECK_STALE_AFTER",
    "CheckJob",
    "PracticeCheckRow",
    "PracticeRunError",
    "PracticeRunNotFoundError",
    "PracticeRunOwnershipError",
    "PracticeRunQuestion",
    "PracticeRunRow",
    "PracticeRunService",
    "PracticeRunValidationError",
]
```

Note: `_as_uuid` raises `PracticeRunNotFoundError` for a non-UUID path value, so a malformed id is a 404 and never a 500.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/python -m pytest tests/test_practice_run_repo.py tests/test_quiz_marking_repo.py -q`
Expected: PASS. `test_quiz_marking_repo.py` proves the alias did not change marking.

- [ ] **Step 7: Commit**

```bash
PYTHONPATH=$PWD pre-commit run --files lemely/db/practice_run_repo.py lemely/db/quiz_marking_repo.py tests/practice_run_fixtures.py tests/test_practice_run_repo.py
git commit -S -m "feat(practice): per-question check, flags and run payload service" -- lemely/db/practice_run_repo.py lemely/db/quiz_marking_repo.py tests/practice_run_fixtures.py tests/test_practice_run_repo.py
```

---

### Task 4: Lock a checked answer against later saves

**Files:**
- Modify: `lemely/db/quiz_taking_repo.py` (`save_answer`, inside the `elif submission.status in (...)` branch's sibling path, before the `answer = session.scalars(...)` upsert)
- Test: `tests/test_practice_answer_lock.py`

**Interfaces:**
- Consumes: Task 1 model. Task 3 service, used in the tests.
- Produces: `QuizTakingService.save_answer` raises `QuizTakingValidationError("Question 'qN' has been checked; its answer is locked")` when that question's practice state is `checking` or `checked`. The router maps this to 422.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_practice_answer_lock.py
"""A checked practice answer is locked: a later autosave is refused (L3)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from lemely.db import practice_run_repo
from lemely.db.class_repo import ClassService
from lemely.db.practice_run_repo import PracticeRunService
from lemely.db.quiz_taking_repo import QuizTakingService, QuizTakingValidationError
from tests.practice_run_fixtures import (  # noqa: F401 - pytest fixture
    fake_correction,
    pg_sessionmaker,
    seed_practice_set,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker


def test_saving_a_checked_answer_is_refused_and_others_still_save(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    seeded = seed_practice_set(pg_sessionmaker)
    taking = QuizTakingService(pg_sessionmaker, ClassService(pg_sessionmaker))
    service = PracticeRunService(pg_sessionmaker, gemini_client=None)
    taking.save_answer(seeded.student_id, seeded.assignment_id, seeded.mcq_ref, answer_text="A")
    job = service.begin_check(seeded.student_id, seeded.assignment_id, seeded.mcq_ref)
    service.perform_check(job.state_id)

    with pytest.raises(QuizTakingValidationError, match="locked"):
        taking.save_answer(
            seeded.student_id, seeded.assignment_id, seeded.mcq_ref, answer_text="B"
        )
    row = taking.save_answer(
        seeded.student_id, seeded.assignment_id, seeded.typed_ref, answer_text="9.22"
    )
    assert row.answer_text == "9.22"


def test_a_failed_check_unlocks_the_answer_for_a_retry(
    pg_sessionmaker: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    seeded = seed_practice_set(pg_sessionmaker)

    def _boom(**_kwargs: Any) -> Any:
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(practice_run_repo, "correct_paper", _boom)
    taking = QuizTakingService(pg_sessionmaker, ClassService(pg_sessionmaker))
    service = PracticeRunService(pg_sessionmaker, gemini_client=None)
    taking.save_answer(seeded.student_id, seeded.assignment_id, seeded.typed_ref, answer_text="9")
    job = service.begin_check(seeded.student_id, seeded.assignment_id, seeded.typed_ref)
    service.perform_check(job.state_id)

    row = taking.save_answer(
        seeded.student_id, seeded.assignment_id, seeded.typed_ref, answer_text="9.22"
    )
    assert row.answer_text == "9.22"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/python -m pytest tests/test_practice_answer_lock.py -q`
Expected: FAIL. `DID NOT RAISE QuizTakingValidationError` in the first test.

- [ ] **Step 3: Add the lock**

Add the import at the top of `lemely/db/quiz_taking_repo.py`:

```python
from lemely.db.models.practice_runs import PracticeCheckStatus, PracticeQuestionState
```

In `save_answer`, replace

```python
            if submission is None:
                submission = self._create_submission(session, assignment_uuid, student_uuid, now)
            elif submission.status in (QuizSubmissionStatus.submitted, QuizSubmissionStatus.marked):
                raise QuizTakingValidationError(
                    f"Submission is {submission.status.value}; answers can no longer be saved"
                )
```

with

```python
            if submission is None:
                submission = self._create_submission(session, assignment_uuid, student_uuid, now)
            elif submission.status in (QuizSubmissionStatus.submitted, QuizSubmissionStatus.marked):
                raise QuizTakingValidationError(
                    f"Submission is {submission.status.value}; answers can no longer be saved"
                )
            else:
                # L3 practice run: once a question is being checked or has been
                # checked, its answer is what was marked and must not change.
                # A failed check unlocks it. Teacher quizzes and placement never
                # write practice states, so this never fires for them.
                locked = session.scalars(
                    select(PracticeQuestionState.id).where(
                        PracticeQuestionState.submission_id == submission.id,
                        PracticeQuestionState.quiz_question_id == qq.id,
                        PracticeQuestionState.check_status.in_(
                            (PracticeCheckStatus.checking, PracticeCheckStatus.checked)
                        ),
                    )
                ).first()
                if locked is not None:
                    raise QuizTakingValidationError(
                        f"Question {question_ref!r} has been checked; its answer is locked"
                    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/python -m pytest tests/test_practice_answer_lock.py tests/test_quiz_taking_repo.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
PYTHONPATH=$PWD pre-commit run --files lemely/db/quiz_taking_repo.py tests/test_practice_answer_lock.py
git commit -S -m "feat(quiz): lock a checked practice answer against later saves" -- lemely/db/quiz_taking_repo.py tests/test_practice_answer_lock.py
```

---

### Task 5: The final submit reuses stored checks and routes flagged questions to review

**Files:**
- Modify: `lemely/db/quiz_marking_repo.py` (`mark_submission`, plus three new module functions)
- Test: `tests/test_quiz_marking_reuses_checks.py`

**Interfaces:**
- Consumes: Task 1 model, Task 3 alias.
- Produces: `STUDENT_FLAG_REVIEW_REASON = "Flagged by the student during practice"`. `mark_submission` makes no `correct_paper` call for a question whose practice state is `checked`. It sets `needs_teacher_review=True` on every flagged question. With no practice states, the code path is the original one (K48).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_quiz_marking_reuses_checks.py
"""mark_submission reuses the practice run's stored checks (L3)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import select

from lemely.db import practice_run_repo, quiz_marking_repo
from lemely.db.attempt_repo import AttemptRepository
from lemely.db.class_repo import ClassService
from lemely.db.models.attempts import Attempt, QuestionResult
from lemely.db.models.enums import QuizSubmissionStatus
from lemely.db.practice_run_repo import PracticeRunService
from lemely.db.quiz_marking_repo import STUDENT_FLAG_REVIEW_REASON, QuizMarkingService
from lemely.db.quiz_taking_repo import QuizTakingService
from tests.practice_run_fixtures import (  # noqa: F401 - pytest fixture
    fake_correction,
    pg_sessionmaker,
    seed_practice_set,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker

    from tests.practice_run_fixtures import SeededSet


def _check_both(sm: sessionmaker[Session], seeded: SeededSet, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        practice_run_repo,
        "correct_paper",
        lambda **_kw: fake_correction(seeded.typed_ref, 2, 3),
    )
    taking = QuizTakingService(sm, ClassService(sm))
    service = PracticeRunService(sm, gemini_client=None)
    taking.save_answer(seeded.student_id, seeded.assignment_id, seeded.typed_ref, answer_text="9")
    # The MCQ check runs the real deterministic path; un-patch for it.
    for ref in (seeded.typed_ref,):
        job = service.begin_check(seeded.student_id, seeded.assignment_id, ref)
        service.perform_check(job.state_id)
    monkeypatch.undo()
    taking.save_answer(seeded.student_id, seeded.assignment_id, seeded.mcq_ref, answer_text="A")
    job = service.begin_check(seeded.student_id, seeded.assignment_id, seeded.mcq_ref)
    service.perform_check(job.state_id)


def _submit_and_mark(sm: sessionmaker[Session], seeded: SeededSet) -> Any:
    taking = QuizTakingService(sm, ClassService(sm))
    submitted = taking.submit(seeded.student_id, seeded.assignment_id)
    marking = QuizMarkingService(sm, AttemptRepository(sm), gemini_client=None)  # type: ignore[arg-type]
    return marking.mark_submission(submitted.submission_id)


def test_every_question_checked_means_no_marker_call_at_submit(
    pg_sessionmaker: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    seeded = seed_practice_set(pg_sessionmaker)
    _check_both(pg_sessionmaker, seeded, monkeypatch)

    def _must_not_run(**_kwargs: Any) -> Any:
        raise AssertionError("correct_paper must not run for checked answers")

    monkeypatch.setattr(quiz_marking_repo, "correct_paper", _must_not_run)
    result = _submit_and_mark(pg_sessionmaker, seeded)

    assert result.status == QuizSubmissionStatus.marked
    with pg_sessionmaker() as session:
        attempt = session.get(Attempt, result.attempt_id)
        assert attempt is not None
        assert (attempt.awarded_marks, attempt.maximum_marks) == (3, 4)


def test_only_unchecked_questions_reach_the_marker(
    pg_sessionmaker: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    seeded = seed_practice_set(pg_sessionmaker)
    taking = QuizTakingService(pg_sessionmaker, ClassService(pg_sessionmaker))
    service = PracticeRunService(pg_sessionmaker, gemini_client=None)
    taking.save_answer(seeded.student_id, seeded.assignment_id, seeded.mcq_ref, answer_text="A")
    job = service.begin_check(seeded.student_id, seeded.assignment_id, seeded.mcq_ref)
    service.perform_check(job.state_id)
    taking.save_answer(seeded.student_id, seeded.assignment_id, seeded.typed_ref, answer_text="9")

    seen: list[list[str]] = []

    def _spy(**kwargs: Any) -> Any:
        seen.append([q.id for q in kwargs["mark_scheme"].questions])
        return fake_correction(seeded.typed_ref, 1, 3)

    monkeypatch.setattr(quiz_marking_repo, "correct_paper", _spy)
    result = _submit_and_mark(pg_sessionmaker, seeded)

    assert seen == [[seeded.typed_ref]]
    with pg_sessionmaker() as session:
        attempt = session.get(Attempt, result.attempt_id)
        assert attempt is not None and attempt.awarded_marks == 2


def test_a_flagged_question_goes_to_review(
    pg_sessionmaker: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    seeded = seed_practice_set(pg_sessionmaker)
    _check_both(pg_sessionmaker, seeded, monkeypatch)
    PracticeRunService(pg_sessionmaker, gemini_client=None).set_flag(
        seeded.student_id, seeded.assignment_id, seeded.typed_ref, True
    )
    result = _submit_and_mark(pg_sessionmaker, seeded)

    with pg_sessionmaker() as session:
        rows = {
            r.question_id: r
            for r in session.scalars(
                select(QuestionResult).where(QuestionResult.attempt_id == result.attempt_id)
            ).all()
        }
    assert rows[seeded.typed_ref].needs_teacher_review is True
    assert rows[seeded.typed_ref].review_reason == STUDENT_FLAG_REVIEW_REASON
    assert rows[seeded.mcq_ref].needs_teacher_review is False
```

Note: if `QuestionResult` names the reason column differently, read `lemely/db/models/attempts.py` and use that column. The assertion intent stays: the flagged row carries `STUDENT_FLAG_REVIEW_REASON`.

- [ ] **Step 2: Run them to verify they fail**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/python -m pytest tests/test_quiz_marking_reuses_checks.py -q`
Expected: FAIL with `ImportError: cannot import name 'STUDENT_FLAG_REVIEW_REASON'`.

- [ ] **Step 3: Implement the reuse**

Add to the imports of `lemely/db/quiz_marking_repo.py`:

```python
from collections.abc import Mapping

from lemely.core.schemas import CorrectedQuestion, CorrectionResult, ExamMetadata
from lemely.db.models.practice_runs import PracticeCheckStatus, PracticeQuestionState
```

(`ExtractedAnswer` and `ExtractedAnswers` are already imported. Put `Mapping` under `TYPE_CHECKING` if ruff's TC rules ask.)

Add these module-level definitions above `_split_marks_evenly`:

```python
#: Review reason on a question the student flagged during a practice run (L3).
STUDENT_FLAG_REVIEW_REASON = "Flagged by the student during practice"


def _quiz_exam_metadata(mark_scheme: MarkScheme) -> ExamMetadata:
    """The same synthetic ``ExamMetadata`` ``correct_paper`` derives from a quiz scheme."""
    m = mark_scheme.metadata
    return ExamMetadata(
        subject_code=m.subject_code,
        paper_number=m.paper_number,
        paper_variant=m.paper_variant,
        session_month=m.session_month.value,
        session_year=m.session_year,
        source_document=m.source_document,
    )


def _student_flagged(cq: CorrectedQuestion) -> CorrectedQuestion:
    return cq.model_copy(
        update={
            "needs_teacher_review": True,
            "review_reason": cq.review_reason or STUDENT_FLAG_REVIEW_REASON,
        }
    )


def _correct_with_reuse(
    *,
    subject_code: str,
    mark_scheme: MarkScheme,
    scheme_questions: list[Question],
    extracted: ExtractedAnswers,
    reused: Mapping[str, Mapping[str, object]],
    flagged_refs: set[str],
    gemini_client: GeminiClient,
    options: MarkingOptions,
) -> CorrectionResult:
    """Mark only the questions the practice run did not check, then merge in scheme order.

    ``reused`` maps question ref to the stored ``CorrectedQuestion`` JSON.
    Flagged questions are sent to teacher review whatever their marks.
    """
    remaining = [q for q in scheme_questions if q.id not in reused]
    by_id: dict[str, CorrectedQuestion] = {}
    if remaining:
        fresh = correct_paper(
            mark_scheme=_build_mark_scheme(subject_code, remaining),
            extracted_answers=ExtractedAnswers(
                paper_id=extracted.paper_id,
                source_scan=extracted.source_scan,
                answers=[a for a in extracted.answers if a.question_id not in reused],
            ),
            gemini_client=gemini_client,
            options=options,
            expects_pages=False,
        )
        by_id.update({cq.question_id: cq for cq in fresh.questions})
    by_id.update({ref: CorrectedQuestion.model_validate(data) for ref, data in reused.items()})
    merged = [
        _student_flagged(by_id[q.id]) if q.id in flagged_refs else by_id[q.id]
        for q in scheme_questions
    ]
    return CorrectionResult(metadata=_quiz_exam_metadata(mark_scheme), questions=merged)
```

In `mark_submission`, directly after the `answers_by_question = {...}` block (still inside the read session), add:

```python
            # L3 practice run: answers already checked one at a time are not
            # marked again, and flagged questions go to review. Empty for
            # teacher quizzes and placement tests.
            practice_states = {
                s.quiz_question_id: s
                for s in session.scalars(
                    select(PracticeQuestionState).where(
                        PracticeQuestionState.submission_id == submission.id
                    )
                ).all()
            }
            reused = {
                q.question_ref: dict(practice_states[q.id].corrected or {})
                for q in questions
                if q.id in practice_states
                and practice_states[q.id].check_status == PracticeCheckStatus.checked
                and practice_states[q.id].corrected is not None
            }
            flagged_refs = {
                q.question_ref
                for q in questions
                if q.id in practice_states and practice_states[q.id].flagged
            }
```

In the `try:` block, replace

```python
            mark_scheme = _build_mark_scheme(subject_code, scheme_questions)
            correction = correct_paper(
                mark_scheme=mark_scheme,
                extracted_answers=extracted,
                gemini_client=self._gemini_client,
                options=self._marking_options,
                expects_pages=False,  # typed answers: there is no scan to adjudicate from
            )
```

with

```python
            mark_scheme = _build_mark_scheme(subject_code, scheme_questions)
            if reused or flagged_refs:
                correction = _correct_with_reuse(
                    subject_code=subject_code,
                    mark_scheme=mark_scheme,
                    scheme_questions=scheme_questions,
                    extracted=extracted,
                    reused=reused,
                    flagged_refs=flagged_refs,
                    gemini_client=self._gemini_client,
                    options=self._marking_options,
                )
            else:
                correction = correct_paper(
                    mark_scheme=mark_scheme,
                    extracted_answers=extracted,
                    gemini_client=self._gemini_client,
                    options=self._marking_options,
                    expects_pages=False,  # typed answers: there is no scan to adjudicate from
                )
```

Add `"STUDENT_FLAG_REVIEW_REASON",` to `__all__`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/python -m pytest tests/test_quiz_marking_reuses_checks.py tests/test_quiz_marking_repo.py tests/test_web_quiz.py -q`
Expected: PASS. The existing marking tests prove K48.

- [ ] **Step 5: Commit**

```bash
PYTHONPATH=$PWD pre-commit run --files lemely/db/quiz_marking_repo.py tests/test_quiz_marking_reuses_checks.py
git commit -S -m "feat(quiz): reuse practice checks at submit and route flags to review" -- lemely/db/quiz_marking_repo.py tests/test_quiz_marking_reuses_checks.py
```

---

### Task 6: The result summary (marks back, mastery, next topic, XP)

**Files:**
- Modify: `lemely/db/practice_run_repo.py` (add `PracticeMastery`, `PracticeNextTopic`, `PracticeSummaryRow`, `PracticeRunService.summary`, and helpers `_mastery`, `_next_topic`, `_xp_awarded`)
- Test: `tests/test_practice_run_summary.py`

**Interfaces:**
- Produces:
  - `PracticeMastery(topic: str, before: float | None, after: float)`
  - `PracticeNextTopic(topic: str, marks_lost: int)`
  - `PracticeSummaryRow(assignment_id, subject_code, marked: bool, awarded_marks: int | None, maximum_marks: int | None, marks_to_win: int | None, marks_back: int | None, best_combo: int, xp_awarded: int, focus_topic: str | None, included_topics: tuple[str, ...], question_count: int, mastery: PracticeMastery | None, next_topic: PracticeNextTopic | None)`
  - `PracticeRunService.summary(student_id, assignment_id) -> PracticeSummaryRow`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_practice_run_summary.py
"""PracticeRunService.summary (L3): the numbers the result screen shows."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

from lemely.db.attempt_repo import AttemptRepository
from lemely.db.class_repo import ClassService
from lemely.db.models.attempts import Attempt, WeaknessRecord
from lemely.db.models.engagement import XpEvent
from lemely.db.models.enums import AttemptOrigin, XpSource
from lemely.db.practice_run_repo import PracticeRunService
from lemely.db.quiz_marking_repo import QuizMarkingService
from lemely.db.quiz_taking_repo import QuizTakingService
from tests.practice_run_fixtures import (  # noqa: F401 - pytest fixture
    SUBJECT,
    TOPIC,
    pg_sessionmaker,
    seed_practice_set,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker


def _paper_with_losses(
    sm: sessionmaker[Session], student: uuid.UUID, losses: dict[str, int]
) -> uuid.UUID:
    attempt_id = uuid.uuid4()
    with sm.begin() as session:
        session.add(
            Attempt(
                id=attempt_id,
                user_id=student,
                subject_code=SUBJECT,
                awarded_marks=40,
                maximum_marks=80,
                percentage=50.0,
                recorded_at=datetime(2026, 11, 1, tzinfo=UTC),
                origin=AttemptOrigin.past_paper,
            )
        )
        for topic, lost in losses.items():
            session.add(
                WeaknessRecord(
                    user_id=student,
                    attempt_id=attempt_id,
                    topic=topic,
                    lost_marks=lost,
                    maximum_marks=lost + 2,
                    accuracy=2 / (lost + 2),
                    question_ids=[],
                )
            )
    return attempt_id


def test_unmarked_summary_carries_no_scores(pg_sessionmaker: sessionmaker[Session]) -> None:
    seeded = seed_practice_set(pg_sessionmaker)
    QuizTakingService(pg_sessionmaker, ClassService(pg_sessionmaker)).get_take(
        seeded.student_id, seeded.assignment_id
    )
    summary = PracticeRunService(pg_sessionmaker, gemini_client=None).summary(
        seeded.student_id, seeded.assignment_id
    )
    assert summary.marked is False
    assert summary.awarded_marks is None and summary.marks_back is None
    assert summary.question_count == 2


def test_marked_summary_reports_marks_back_mastery_next_topic_and_xp(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    seeded = seed_practice_set(pg_sessionmaker)
    _paper_with_losses(pg_sessionmaker, seeded.student_id, {TOPIC: 3, "2 Waves": 7})
    taking = QuizTakingService(pg_sessionmaker, ClassService(pg_sessionmaker))
    taking.save_answer(seeded.student_id, seeded.assignment_id, seeded.mcq_ref, answer_text="A")
    service = PracticeRunService(pg_sessionmaker, gemini_client=None)
    job = service.begin_check(seeded.student_id, seeded.assignment_id, seeded.mcq_ref)
    service.perform_check(job.state_id)
    submitted = taking.submit(seeded.student_id, seeded.assignment_id)
    QuizMarkingService(
        pg_sessionmaker, AttemptRepository(pg_sessionmaker), gemini_client=None  # type: ignore[arg-type]
    ).mark_submission(submitted.submission_id)
    with pg_sessionmaker.begin() as session:
        session.add(
            XpEvent(
                user_id=seeded.student_id,
                source=XpSource.quiz_completed,
                amount=30,
                awarded_on=date(2026, 11, 15),
                subject_code=SUBJECT,
                dedupe_key=str(seeded.assignment_id),
                event_metadata={},
            )
        )

    summary = service.summary(seeded.student_id, seeded.assignment_id)

    assert summary.marked is True
    assert (summary.awarded_marks, summary.maximum_marks) == (1, 4)
    assert summary.marks_to_win == 3
    assert summary.marks_back == 1
    assert summary.best_combo == 1
    assert summary.xp_awarded == 30
    assert summary.focus_topic == TOPIC
    assert summary.next_topic is not None
    assert (summary.next_topic.topic, summary.next_topic.marks_lost) == ("2 Waves", 7)
    assert summary.mastery is not None
    assert summary.mastery.topic == TOPIC
    assert summary.mastery.after == 0.25  # 1 of 4 on this topic, the only results so far
    assert summary.mastery.before is None


def test_marks_back_is_capped_at_the_target(pg_sessionmaker: sessionmaker[Session]) -> None:
    seeded = seed_practice_set(pg_sessionmaker)
    _paper_with_losses(pg_sessionmaker, seeded.student_id, {TOPIC: 1})
    taking = QuizTakingService(pg_sessionmaker, ClassService(pg_sessionmaker))
    taking.save_answer(seeded.student_id, seeded.assignment_id, seeded.mcq_ref, answer_text="A")
    submitted = taking.submit(seeded.student_id, seeded.assignment_id)
    QuizMarkingService(
        pg_sessionmaker, AttemptRepository(pg_sessionmaker), gemini_client=None  # type: ignore[arg-type]
    ).mark_submission(submitted.submission_id)
    summary = PracticeRunService(pg_sessionmaker, gemini_client=None).summary(
        seeded.student_id, seeded.assignment_id
    )
    assert summary.marks_to_win == 1
    assert summary.marks_back == 1
```

The MCQ-only marking in these tests needs no model. The typed question is blank, so `correct_paper` builds a blank result without a call.

- [ ] **Step 2: Run them to verify they fail**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/python -m pytest tests/test_practice_run_summary.py -q`
Expected: FAIL with `AttributeError: 'PracticeRunService' object has no attribute 'summary'`.

- [ ] **Step 3: Implement the summary**

Add the imports to `lemely/db/practice_run_repo.py`:

```python
import sqlalchemy as sa

from lemely.core.practice_run import mastery_ratio
from lemely.db.models.attempts import QuestionResult
from lemely.db.models.engagement import XpEvent
from lemely.db.models.enums import XpSource
```

Add the dataclasses below `CheckJob`:

```python
@dataclass(frozen=True, slots=True)
class PracticeMastery:
    topic: str
    before: float | None
    after: float


@dataclass(frozen=True, slots=True)
class PracticeNextTopic:
    topic: str
    marks_lost: int


@dataclass(frozen=True, slots=True)
class PracticeSummaryRow:
    assignment_id: uuid.UUID
    subject_code: str
    marked: bool
    awarded_marks: int | None
    maximum_marks: int | None
    marks_to_win: int | None
    marks_back: int | None
    best_combo: int
    xp_awarded: int
    focus_topic: str | None
    included_topics: tuple[str, ...]
    question_count: int
    mastery: PracticeMastery | None
    next_topic: PracticeNextTopic | None
```

Add the method to `PracticeRunService` after `get_check`:

```python
    def summary(
        self, student_id: uuid.UUID | str, assignment_id: uuid.UUID | str
    ) -> PracticeSummaryRow:
        """What the result screen shows beyond ``GET .../result``.

        Score fields are ``None`` until the submission is marked: never a
        fabricated zero, the same discipline as ``PracticeService.result``.
        """
        student_uuid = _as_uuid(student_id)
        assignment_uuid = _as_uuid(assignment_id)
        now = self._now()
        with self._sessionmaker() as session:
            _assignment, quiz = _load_owned(session, student_uuid, assignment_uuid)
            questions = _included_questions(session, quiz.id)
            submission = _find_submission(session, assignment_uuid, student_uuid)
            states = _states_by_question(session, submission.id) if submission else {}
            topics = _target_topics(quiz, questions)
            focus = focus_topic(list(quiz.included_topics or []), [q.topic for q in questions])
            marks_to_win = _marks_to_win(session, student_uuid, quiz.subject_code, topics)
            stats = _run_stats(questions, states, now)
            xp = _xp_awarded(session, student_uuid, assignment_uuid)
            next_topic = _next_topic(session, student_uuid, quiz.subject_code, set(topics))
            base = {
                "assignment_id": assignment_uuid,
                "subject_code": quiz.subject_code,
                "marks_to_win": marks_to_win,
                "best_combo": stats.best_combo,
                "xp_awarded": xp,
                "focus_topic": focus,
                "included_topics": topics,
                "question_count": len(questions),
                "next_topic": next_topic,
            }
            if (
                submission is None
                or submission.status != QuizSubmissionStatus.marked
                or submission.attempt_id is None
            ):
                return PracticeSummaryRow(
                    marked=False,
                    awarded_marks=None,
                    maximum_marks=None,
                    marks_back=None,
                    mastery=None,
                    **base,
                )
            attempt = session.get(Attempt, submission.attempt_id)
            if attempt is None:  # pragma: no cover - FK guarantees the row exists
                raise PracticeRunError(f"Unknown attempt: {submission.attempt_id}")
            return PracticeSummaryRow(
                marked=True,
                awarded_marks=attempt.awarded_marks,
                maximum_marks=attempt.maximum_marks,
                marks_back=(
                    min(attempt.awarded_marks, marks_to_win) if marks_to_win is not None else None
                ),
                mastery=(
                    _mastery(session, student_uuid, quiz.subject_code, focus, attempt.id)
                    if focus
                    else None
                ),
                **base,
            )
```

Add these helpers next to `_marks_to_win`:

```python
def _mastery(
    session: Session,
    student_uuid: uuid.UUID,
    subject_code: str,
    topic: str,
    attempt_id: uuid.UUID,
) -> PracticeMastery | None:
    """Topic accuracy over every live attempt, before and after this practice attempt."""
    results = session.scalars(
        select(QuestionResult)
        .join(Attempt, Attempt.id == QuestionResult.attempt_id)
        .where(
            Attempt.user_id == student_uuid,
            Attempt.subject_code == subject_code,
            Attempt.deleted_at.is_(None),
            QuestionResult.topic == topic,
        )
    ).all()
    after = mastery_ratio((r.effective_marks, r.maximum_marks) for r in results)
    if after is None:
        return None
    before = mastery_ratio(
        (r.effective_marks, r.maximum_marks) for r in results if r.attempt_id != attempt_id
    )
    return PracticeMastery(topic=topic, before=before, after=after)


def _next_topic(
    session: Session, student_uuid: uuid.UUID, subject_code: str, exclude: set[str]
) -> PracticeNextTopic | None:
    """The topic with the most net lost marks, outside this set's topics."""
    rows = session.execute(
        select(WeaknessRecord.topic, sa.func.sum(WeaknessRecord.lost_marks))
        .join(Attempt, Attempt.id == WeaknessRecord.attempt_id)
        .where(
            WeaknessRecord.user_id == student_uuid,
            Attempt.subject_code == subject_code,
            Attempt.deleted_at.is_(None),
        )
        .group_by(WeaknessRecord.topic)
    ).all()
    candidates = sorted(
        ((topic, int(lost)) for topic, lost in rows if topic not in exclude and int(lost or 0) > 0),
        key=lambda c: (-c[1], c[0]),
    )
    if not candidates:
        return None
    topic, lost = candidates[0]
    return PracticeNextTopic(topic=topic, marks_lost=lost)


def _xp_awarded(session: Session, student_uuid: uuid.UUID, assignment_uuid: uuid.UUID) -> int:
    """The ``quiz_completed`` XP this set earned. 0 when the daily cap held it back."""
    total = session.scalar(
        select(sa.func.coalesce(sa.func.sum(XpEvent.amount), 0)).where(
            XpEvent.user_id == student_uuid,
            XpEvent.source == XpSource.quiz_completed,
            XpEvent.dedupe_key == str(assignment_uuid),
        )
    )
    return int(total or 0)
```

Add `"PracticeMastery"`, `"PracticeNextTopic"` and `"PracticeSummaryRow"` to `__all__`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/python -m pytest tests/test_practice_run_summary.py tests/test_practice_run_repo.py -q`
Expected: PASS. If `Attempt` needs more non-null columns than the helper sets, add them by reading `lemely/db/models/attempts.py:101-180`. Keep the values neutral.

- [ ] **Step 5: Commit**

```bash
PYTHONPATH=$PWD pre-commit run --files lemely/db/practice_run_repo.py tests/test_practice_run_summary.py
git commit -S -m "feat(practice): result summary with marks back, mastery and next topic" -- lemely/db/practice_run_repo.py tests/test_practice_run_summary.py
```

---

### Task 7: DTOs, router, dependency and registration

**Files:**
- Create: `lemely/web/schemas_practice_run.py`
- Create: `lemely/web/routers/practice_run.py`
- Modify: `lemely/web/deps.py` (add `get_practice_run_service` after `get_practice_service`; import `PracticeRunService` and `script_cost_scope`)
- Modify: `lemely/web/app.py` (add `practice_run,` to the routers import, and `app.include_router(practice_run.router)` directly after `app.include_router(practice.router)`)
- Test: `tests/test_web_practice_run.py`

**Interfaces:**
- Consumes: Tasks 3–6.
- Produces these routes, all `require_role(Role.student)`:
  - `GET /api/student/practice/{assignment_id}/run` → `PracticeRunDTO`
  - `POST /api/student/practice/{assignment_id}/questions/{question_ref}/check`, body `PracticeCheckRequestDTO` → `PracticeCheckDTO`. 200 when checked or failed, 202 while checking.
  - `GET /api/student/practice/{assignment_id}/questions/{question_ref}/check` → `PracticeCheckDTO`, or 404 `{"detail": "not_checked"}`
  - `PUT /api/student/practice/{assignment_id}/questions/{question_ref}/flag`, body `PracticeFlagRequestDTO` → `PracticeFlagDTO`
  - `GET /api/student/practice/{assignment_id}/summary` → `PracticeSummaryDTO`
  - Error mapping: 404 not found or not practice, 403 not yours, 422 with `detail` set to the stable code.
  - `get_check_launcher()`, a dependency that tests override with a synchronous launcher.

- [ ] **Step 1: Write the failing route tests**

```python
# tests/test_web_practice_run.py
"""Route tests for the L3 practice-run endpoints (/api/student/practice/{id}/...)."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

import pytest
from fastapi.testclient import TestClient

from lemely.db import practice_run_repo
from lemely.db.class_repo import ClassService
from lemely.db.models.enums import Role
from lemely.db.practice_run_repo import PracticeRunService
from lemely.db.quiz_taking_repo import QuizTakingService
from lemely.db.xp_repo import XpService
from lemely.web import create_app
from lemely.web.deps import (
    AuthContext,
    get_auth_context,
    get_practice_run_service,
    get_quiz_taking_service,
    get_xp_service,
)
from lemely.web.routers.practice_run import get_check_launcher
from tests.practice_run_fixtures import (  # noqa: F401 - pytest fixture
    fake_correction,
    pg_sessionmaker,
    seed_practice_set,
    seed_user,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker

    from tests.practice_run_fixtures import SeededSet


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app()
    yield TestClient(app)
    app.dependency_overrides.clear()


def _wire(client: TestClient, sm: sessionmaker[Session], user_id: uuid.UUID) -> PracticeRunService:
    service = PracticeRunService(sm, gemini_client=None)
    overrides = client.app.dependency_overrides  # type: ignore[union-attr]
    overrides[get_practice_run_service] = lambda: service
    overrides[get_quiz_taking_service] = lambda: QuizTakingService(sm, ClassService(sm))
    overrides[get_xp_service] = lambda: XpService(sm)
    overrides[get_check_launcher] = lambda: (lambda svc, state_id: svc.perform_check(state_id))
    overrides[get_auth_context] = lambda: AuthContext(user_id=str(user_id), role=Role.student.value)
    return service


def _base(seeded: SeededSet) -> str:
    return f"/api/student/practice/{seeded.assignment_id}"


def test_run_payload_has_no_answer_key_and_creates_the_submission(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    seeded = seed_practice_set(pg_sessionmaker)
    _wire(client, pg_sessionmaker, seeded.student_id)
    res = client.get(f"{_base(seeded)}/run")
    assert res.status_code == 200
    body = res.json()
    assert body["submissionStatus"] in {"not_started", "in_progress"}
    assert [q["position"] for q in body["questions"]] == [1, 2]
    for q in body["questions"]:
        assert q["check"] is None
        assert not {"mcqAnswer", "markSchemePoints", "modelAnswer"} & set(q)
    assert body["resumeIndex"] == 0


def test_other_students_and_unknown_ids_are_refused_without_data(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    seeded = seed_practice_set(pg_sessionmaker)
    stranger = seed_user(pg_sessionmaker)
    _wire(client, pg_sessionmaker, stranger)
    for method, path in [
        ("get", "/run"),
        ("get", f"/questions/{seeded.mcq_ref}/check"),
        ("get", "/summary"),
    ]:
        res = getattr(client, method)(f"{_base(seeded)}{path}")
        assert res.status_code == 403, path
        assert "questions" not in res.json()
    res = client.post(f"{_base(seeded)}/questions/{seeded.mcq_ref}/check", json={"answerText": "A"})
    assert res.status_code == 403
    res = client.put(f"{_base(seeded)}/questions/{seeded.mcq_ref}/flag", json={"flagged": True})
    assert res.status_code == 403
    assert client.get(f"/api/student/practice/{uuid.uuid4()}/run").status_code == 404
    assert client.get("/api/student/practice/not-a-uuid/summary").status_code in {404, 422}


def test_a_teacher_cannot_reach_the_routes(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    seeded = seed_practice_set(pg_sessionmaker)
    teacher = seed_user(pg_sessionmaker, Role.teacher)
    _wire(client, pg_sessionmaker, teacher)
    client.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[union-attr]
        user_id=str(teacher), role=Role.teacher.value
    )
    assert client.get(f"{_base(seeded)}/run").status_code == 403


def test_mcq_check_is_instant_and_locks_the_answer(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    seeded = seed_practice_set(pg_sessionmaker)
    _wire(client, pg_sessionmaker, seeded.student_id)
    client.get(f"{_base(seeded)}/run")
    res = client.post(f"{_base(seeded)}/questions/{seeded.mcq_ref}/check", json={"answerText": "A"})
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "checked"
    assert (body["awardedMarks"], body["maximumMarks"]) == (1, 1)
    assert body["correctOption"] == "A"
    assert body["combo"] == 1 and body["wonMarks"] == 1
    # The quiz autosave now refuses this question.
    locked = client.put(
        f"/api/student/quizzes/{seeded.assignment_id}/answers/{seeded.mcq_ref}",
        json={"answerText": "B"},
    )
    assert locked.status_code == 422
    # Repeating the check returns the stored result, unchanged.
    again = client.post(f"{_base(seeded)}/questions/{seeded.mcq_ref}/check", json={"answerText": "B"})
    assert again.status_code == 200 and again.json()["awardedMarks"] == 1


def test_typed_check_is_accepted_then_readable(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    seeded = seed_practice_set(pg_sessionmaker)

    def _fake(**_kw: Any) -> Any:
        return fake_correction(
            seeded.typed_ref, 2, 3, verdicts=[("p1", "awarded"), ("p2", "awarded"), ("p3", "withheld")]
        )

    monkeypatch.setattr(practice_run_repo, "correct_paper", _fake)
    _wire(client, pg_sessionmaker, seeded.student_id)
    client.get(f"{_base(seeded)}/run")
    res = client.post(
        f"{_base(seeded)}/questions/{seeded.typed_ref}/check",
        json={"answerText": "9.22", "workingText": "2a = (6, 8)"},
    )
    assert res.status_code in {200, 202}
    got = client.get(f"{_base(seeded)}/questions/{seeded.typed_ref}/check")
    assert got.status_code == 200
    body = got.json()
    assert body["status"] == "checked"
    assert [p["verdict"] for p in body["points"]] == ["awarded", "awarded", "withheld"]
    assert body["error"] is None


def test_unchecked_question_is_404_and_empty_answer_is_422(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    seeded = seed_practice_set(pg_sessionmaker)
    _wire(client, pg_sessionmaker, seeded.student_id)
    client.get(f"{_base(seeded)}/run")
    res = client.get(f"{_base(seeded)}/questions/{seeded.typed_ref}/check")
    assert res.status_code == 404 and res.json()["detail"] == "not_checked"
    res = client.post(f"{_base(seeded)}/questions/{seeded.typed_ref}/check", json={"answerText": " "})
    assert res.status_code == 422 and res.json()["detail"] == "empty_answer"
    res = client.post(f"{_base(seeded)}/questions/q99/check", json={"answerText": "x"})
    assert res.status_code == 422


def test_flag_round_trips_through_the_run(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    seeded = seed_practice_set(pg_sessionmaker)
    _wire(client, pg_sessionmaker, seeded.student_id)
    client.get(f"{_base(seeded)}/run")
    res = client.put(f"{_base(seeded)}/questions/{seeded.typed_ref}/flag", json={"flagged": True})
    assert res.status_code == 200
    assert res.json() == {"questionRef": seeded.typed_ref, "flagged": True}
    run = client.get(f"{_base(seeded)}/run").json()
    assert [q["flagged"] for q in run["questions"] if q["questionRef"] == seeded.typed_ref] == [True]


def test_summary_before_marking_has_no_scores(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    seeded = seed_practice_set(pg_sessionmaker)
    _wire(client, pg_sessionmaker, seeded.student_id)
    client.get(f"{_base(seeded)}/run")
    body = client.get(f"{_base(seeded)}/summary").json()
    assert body["marked"] is False
    assert body["awardedMarks"] is None and body["marksBack"] is None
    assert set(body["today"]) == {"practice", "flashcards", "paper"}
    assert body["questionCount"] == 2
```

- [ ] **Step 2: Run them to verify they fail**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/python -m pytest tests/test_web_practice_run.py -q`
Expected: FAIL with `ImportError: cannot import name 'get_practice_run_service'`.

- [ ] **Step 3: Write the DTOs**

```python
# lemely/web/schemas_practice_run.py
"""DTOs for the practice-run routes (redesign L3, ``lemely.web.routers.practice_run``).

camelCase on the wire, like ``schemas_practice``. Scheme-point text and the
correct option appear only inside ``check`` for a question whose check is
``checked``, so after the answer is locked. An unchecked question carries no
field shaped like an answer key.
"""

from __future__ import annotations

from typing import Literal

from lemely.web.schemas import ApiModel


class PracticeCheckPointDTO(ApiModel):
    text: str
    verdict: Literal["awarded", "withheld", "unverifiable"]
    note: str | None


class PracticeCheckDTO(ApiModel):
    questionRef: str
    status: Literal["checking", "checked", "failed"]
    awardedMarks: int | None
    maximumMarks: int
    points: list[PracticeCheckPointDTO]
    correctOption: str | None
    feedback: str | None
    needsTeacherReview: bool
    error: Literal["check_failed"] | None
    combo: int
    bestCombo: int
    wonMarks: int


class PracticeRunQuestionDTO(ApiModel):
    questionRef: str
    position: int
    topic: str | None
    questionType: str
    prompt: str
    totalMarks: int
    mcqOptions: list[str] | None
    answerText: str | None
    workingText: str | None
    flagged: bool
    check: PracticeCheckDTO | None


class PracticeRunDTO(ApiModel):
    assignmentId: str
    subjectCode: str
    title: str
    focusTopic: str | None
    includedTopics: list[str]
    submissionStatus: str
    marksToWin: int | None
    totalMarks: int
    questions: list[PracticeRunQuestionDTO]
    combo: int
    bestCombo: int
    wonMarks: int
    resumeIndex: int


class PracticeCheckRequestDTO(ApiModel):
    answerText: str | None = None
    workingText: str | None = None


class PracticeFlagRequestDTO(ApiModel):
    flagged: bool


class PracticeFlagDTO(ApiModel):
    questionRef: str
    flagged: bool


class PracticeTodayDTO(ApiModel):
    practice: bool
    flashcards: bool
    paper: bool


class PracticeMasteryDTO(ApiModel):
    topic: str
    before: float | None
    after: float


class PracticeNextTopicDTO(ApiModel):
    topic: str
    marksLost: int


class PracticeSummaryDTO(ApiModel):
    assignmentId: str
    subjectCode: str
    marked: bool
    awardedMarks: int | None
    maximumMarks: int | None
    marksToWin: int | None
    marksBack: int | None
    bestCombo: int
    xpAwarded: int
    focusTopic: str | None
    includedTopics: list[str]
    questionCount: int
    mastery: PracticeMasteryDTO | None
    nextTopic: PracticeNextTopicDTO | None
    today: PracticeTodayDTO


__all__ = [
    "PracticeCheckDTO",
    "PracticeCheckPointDTO",
    "PracticeCheckRequestDTO",
    "PracticeFlagDTO",
    "PracticeFlagRequestDTO",
    "PracticeMasteryDTO",
    "PracticeNextTopicDTO",
    "PracticeRunDTO",
    "PracticeRunQuestionDTO",
    "PracticeSummaryDTO",
    "PracticeTodayDTO",
]
```

- [ ] **Step 4: Write the router**

```python
# lemely/web/routers/practice_run.py
"""Practice-run endpoints (redesign L3): run payload, per-question check, flags, summary.

Same ``/api/student/practice`` prefix as ``lemely.web.routers.practice``, in
its own file so L4's additions to that router never conflict with this one.
Every path has a literal second segment (``run``, ``questions``, ``summary``),
so none collides with ``/{subject_code}/preview`` or ``/{assignment_id}/result``.

Autosave and submit stay on ``/api/student/quizzes/{id}/...``. A typed check
runs on a daemon thread like quiz marking does
(``lemely.web.routers.quiz._trigger_marking_in_background``), so a model round
trip never sits inside the request. An MCQ check is deterministic and runs inline.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated, NoReturn

import structlog
from fastapi import APIRouter, Depends, HTTPException, Response

from lemely.db.models.enums import Role, XpSource
from lemely.db.practice_run_repo import (
    PracticeCheckRow,
    PracticeRunError,
    PracticeRunNotFoundError,
    PracticeRunOwnershipError,
    PracticeRunRow,
    PracticeRunService,
    PracticeSummaryRow,
)
from lemely.db.quiz_taking_repo import (
    QuizTakingError,
    QuizTakingNotFoundError,
    QuizTakingOwnershipError,
    QuizTakingService,
)
from lemely.db.xp_repo import UserZoneReader, XpService, civil_date_in_zone, week_bounds
from lemely.runtime.events import current_run_id
from lemely.web.deps import (
    AuthContext,
    get_practice_run_service,
    get_quiz_taking_service,
    get_user_zone_reader,
    get_xp_service,
    require_role,
)
from lemely.web.schemas_practice_run import (
    PracticeCheckDTO,
    PracticeCheckPointDTO,
    PracticeCheckRequestDTO,
    PracticeFlagDTO,
    PracticeFlagRequestDTO,
    PracticeMasteryDTO,
    PracticeNextTopicDTO,
    PracticeRunDTO,
    PracticeRunQuestionDTO,
    PracticeSummaryDTO,
    PracticeTodayDTO,
)

log = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/student/practice", dependencies=[Depends(require_role(Role.student))]
)

CheckLauncher = Callable[[PracticeRunService, uuid.UUID], None]


def _launch_in_thread(service: PracticeRunService, state_id: uuid.UUID) -> None:
    def run() -> None:
        # Scope bus events to this check so they reach no other stream (DS10).
        token = current_run_id.set(f"practice_check:{state_id}")
        try:
            service.perform_check(state_id)
        except Exception:
            log.exception("practice_check_unexpected_error", state_id=str(state_id))
        finally:
            current_run_id.reset(token)

    threading.Thread(target=run, daemon=True).start()


def get_check_launcher() -> CheckLauncher:
    """How a typed check is started. Tests override this with a synchronous launcher."""
    return _launch_in_thread


def _raise_for(exc: PracticeRunError | QuizTakingError) -> NoReturn:
    if isinstance(exc, (PracticeRunNotFoundError, QuizTakingNotFoundError)):
        raise HTTPException(status_code=404, detail="not_found") from exc
    if isinstance(exc, (PracticeRunOwnershipError, QuizTakingOwnershipError)):
        raise HTTPException(status_code=403, detail="not_yours") from exc
    raise HTTPException(status_code=422, detail=str(exc)) from exc


def _check_to_dto(row: PracticeCheckRow) -> PracticeCheckDTO:
    return PracticeCheckDTO(
        questionRef=row.question_ref,
        status=row.status,  # type: ignore[arg-type]  # one of the three enum values
        awardedMarks=row.awarded_marks,
        maximumMarks=row.maximum_marks,
        points=[
            PracticeCheckPointDTO(text=p.text, verdict=p.verdict, note=p.note)  # type: ignore[arg-type]
            for p in row.points
        ],
        correctOption=row.correct_option,
        feedback=row.feedback,
        needsTeacherReview=row.needs_teacher_review,
        error="check_failed" if row.failed else None,
        combo=row.combo,
        bestCombo=row.best_combo,
        wonMarks=row.won_marks,
    )


def _run_to_dto(row: PracticeRunRow) -> PracticeRunDTO:
    return PracticeRunDTO(
        assignmentId=str(row.assignment_id),
        subjectCode=row.subject_code,
        title=row.title,
        focusTopic=row.focus_topic,
        includedTopics=list(row.included_topics),
        submissionStatus=row.submission_status,
        marksToWin=row.marks_to_win,
        totalMarks=row.total_marks,
        questions=[
            PracticeRunQuestionDTO(
                questionRef=q.question_ref,
                position=q.position,
                topic=q.topic,
                questionType=q.question_type,
                prompt=q.prompt,
                totalMarks=q.total_marks,
                mcqOptions=q.mcq_options,
                answerText=q.answer_text,
                workingText=q.working_text,
                flagged=q.flagged,
                check=_check_to_dto(q.check) if q.check else None,
            )
            for q in row.questions
        ],
        combo=row.combo,
        bestCombo=row.best_combo,
        wonMarks=row.won_marks,
        resumeIndex=row.resume_index,
    )


def _today(xp: XpService, zones: UserZoneReader, user_id: str) -> PracticeTodayDTO:
    """Today's three small things, from XP events in the student's own zone.

    Practice and flashcards count for today. A paper counts for the week
    (Home's "a paper this week"). A capped award writes no row, but an
    earlier same-day row still lights the part, so this stays honest.
    """
    today = civil_date_in_zone(datetime.now(UTC), zone=zones.zone_for(user_id))
    day = xp.xp_breakdown(user_id, start=today, end=today)
    week_start, week_end = week_bounds(today)
    week = xp.xp_breakdown(user_id, start=week_start, end=week_end)
    return PracticeTodayDTO(
        practice=day.by_source[XpSource.quiz_completed] > 0,
        flashcards=day.by_source[XpSource.flashcard_reviewed] > 0,
        paper=week.by_source[XpSource.paper_corrected] > 0,
    )


def _summary_to_dto(row: PracticeSummaryRow, today: PracticeTodayDTO) -> PracticeSummaryDTO:
    return PracticeSummaryDTO(
        assignmentId=str(row.assignment_id),
        subjectCode=row.subject_code,
        marked=row.marked,
        awardedMarks=row.awarded_marks,
        maximumMarks=row.maximum_marks,
        marksToWin=row.marks_to_win,
        marksBack=row.marks_back,
        bestCombo=row.best_combo,
        xpAwarded=row.xp_awarded,
        focusTopic=row.focus_topic,
        includedTopics=list(row.included_topics),
        questionCount=row.question_count,
        mastery=(
            PracticeMasteryDTO(
                topic=row.mastery.topic, before=row.mastery.before, after=row.mastery.after
            )
            if row.mastery
            else None
        ),
        nextTopic=(
            PracticeNextTopicDTO(topic=row.next_topic.topic, marksLost=row.next_topic.marks_lost)
            if row.next_topic
            else None
        ),
        today=today,
    )


Auth = Annotated[AuthContext, Depends(require_role(Role.student))]
RunService = Annotated[PracticeRunService, Depends(get_practice_run_service)]
Taking = Annotated[QuizTakingService, Depends(get_quiz_taking_service)]


@router.get("/{assignment_id}/run", response_model=PracticeRunDTO)
def practice_run(assignment_id: str, auth: Auth, service: RunService, taking: Taking) -> PracticeRunDTO:
    """The run payload. Opening it lazily creates the submission, like the quiz take route."""
    try:
        service.run(auth.user_id, assignment_id)  # ownership and kind first, never data
        taking.get_take(auth.user_id, assignment_id)
        row = service.run(auth.user_id, assignment_id)
    except (PracticeRunError, QuizTakingError) as exc:
        _raise_for(exc)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _run_to_dto(row)


@router.post(
    "/{assignment_id}/questions/{question_ref}/check",
    response_model=PracticeCheckDTO,
    responses={202: {"model": PracticeCheckDTO}},
)
def check_question(
    assignment_id: str,
    question_ref: str,
    body: PracticeCheckRequestDTO,
    response: Response,
    auth: Auth,
    service: RunService,
    taking: Taking,
    launcher: Annotated[CheckLauncher, Depends(get_check_launcher)],
) -> PracticeCheckDTO:
    """Save the answer, lock it, and check it. 200 when the result is known, 202 while checking.

    A question already checking or checked returns its stored state, and the
    body is ignored: a checked answer cannot change.
    """
    try:
        existing = service.get_check(auth.user_id, assignment_id, question_ref)
        if existing is None or existing.status == "failed":
            taking.save_answer(
                auth.user_id,
                assignment_id,
                question_ref,
                answer_text=body.answerText,
                working_text=body.workingText,
            )
            job = service.begin_check(auth.user_id, assignment_id, question_ref)
            if job.start:
                if job.is_mcq:
                    service.perform_check(job.state_id)
                else:
                    launcher(service, job.state_id)
        row = service.get_check(auth.user_id, assignment_id, question_ref)
    except (PracticeRunError, QuizTakingError) as exc:
        _raise_for(exc)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if row is None:  # pragma: no cover - begin_check always leaves a row
        raise HTTPException(status_code=500, detail="check_missing")
    response.status_code = 202 if row.status == "checking" else 200
    return _check_to_dto(row)


@router.get("/{assignment_id}/questions/{question_ref}/check", response_model=PracticeCheckDTO)
def get_question_check(
    assignment_id: str, question_ref: str, auth: Auth, service: RunService
) -> PracticeCheckDTO:
    """Poll target for a running check. 404 ``not_checked`` when never checked."""
    try:
        row = service.get_check(auth.user_id, assignment_id, question_ref)
    except PracticeRunError as exc:
        _raise_for(exc)
    if row is None:
        raise HTTPException(status_code=404, detail="not_checked")
    return _check_to_dto(row)


@router.put("/{assignment_id}/questions/{question_ref}/flag", response_model=PracticeFlagDTO)
def flag_question(
    assignment_id: str,
    question_ref: str,
    body: PracticeFlagRequestDTO,
    auth: Auth,
    service: RunService,
) -> PracticeFlagDTO:
    """Store the student's flag. A flagged question goes to teacher review at submit."""
    try:
        flagged = service.set_flag(auth.user_id, assignment_id, question_ref, body.flagged)
    except PracticeRunError as exc:
        _raise_for(exc)
    return PracticeFlagDTO(questionRef=question_ref, flagged=flagged)


@router.get("/{assignment_id}/summary", response_model=PracticeSummaryDTO)
def practice_summary(
    assignment_id: str,
    auth: Auth,
    service: RunService,
    xp: Annotated[XpService, Depends(get_xp_service)],
    zones: Annotated[UserZoneReader, Depends(get_user_zone_reader)],
) -> PracticeSummaryDTO:
    """What the result screen adds to ``GET .../result``. Score fields are null until marked."""
    try:
        row = service.summary(auth.user_id, assignment_id)
    except PracticeRunError as exc:
        _raise_for(exc)
    return _summary_to_dto(row, _today(xp, zones, auth.user_id))


__all__ = ["get_check_launcher", "router"]
```

`run` calls `service.run` once before `get_take`. A stranger's or a teacher quiz's id is then refused by the practice-kind check before `get_take` can create a submission row on it.

- [ ] **Step 5: Add the dependency (narrow edit, `lemely/web/deps.py`)**

Add the imports next to their siblings:

```python
from lemely.db.practice_run_repo import PracticeRunService
from lemely.io.gemini import script_cost_scope
```

(If `lemely.io.gemini` is already imported for `GeminiClient`, extend that import instead.)

Add after `get_practice_service`:

```python
@lru_cache(maxsize=1)
def get_practice_run_service() -> PracticeRunService:
    """Return the process-wide :class:`PracticeRunService` singleton (redesign L3).

    Same marker wiring as :func:`get_quiz_marking_service`, so a one-question
    check and the final submit mark identically. Each check runs inside
    ``script_cost_scope``, so its cost is summed, stored and checked against
    ``paper_cost_target_usd``. Tests override this with a throwaway-DB service
    and a stubbed marker.
    """
    settings = get_settings()
    return PracticeRunService(
        get_sessionmaker(settings),
        get_gemini_client(),
        marking_options=settings.grading.marking_options(),
        cost_scope=lambda key: script_cost_scope(settings, script_key=key),
    )
```

- [ ] **Step 6: Register the router (narrow edit, `lemely/web/app.py`)**

Add `practice_run,` after `practice,` in the routers import block. Add `app.include_router(practice_run.router)` on the line after `app.include_router(practice.router)`.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/python -m pytest tests/test_web_practice_run.py tests/test_web_practice.py tests/test_web_quiz.py -q`
Expected: PASS.

Also run any source-scanning lint tests: `ls tests | grep -i lint`, then run each file found (master Global Constraints).

- [ ] **Step 8: Commit**

```bash
PYTHONPATH=$PWD pre-commit run --files lemely/web/schemas_practice_run.py lemely/web/routers/practice_run.py lemely/web/deps.py lemely/web/app.py tests/test_web_practice_run.py
git commit -S -m "feat(practice): run, check, flag and summary routes" -- lemely/web/schemas_practice_run.py lemely/web/routers/practice_run.py lemely/web/deps.py lemely/web/app.py tests/test_web_practice_run.py
```

---

## Frontend data layer

### Task 8: Wire types, API functions, query keys and hooks

**Files:**
- Create: `web/src/lib/practiceRunTypes.ts`
- Create: `web/src/lib/practiceRunApi.ts`
- Create: `web/src/lib/hooks/usePracticeRunApi.ts`
- Test: `web/tests/unit/practiceRunApi.test.ts`

**Interfaces:**
- Produces:
  - Types: `PracticeCheckStatus`, `PracticeCheckPoint`, `PracticeCheck`, `PracticeRunQuestion`, `PracticeRun`, `PracticeCheckRequest`, `PracticeFlag`, `PracticeToday`, `PracticeMastery`, `PracticeNextTopic`, `PracticeSummary`
  - API: `practiceRunPaths`, `fetchPracticeRun(id)`, `postPracticeCheck(id, ref, body)`, `fetchPracticeCheck(id, ref)`, `putPracticeFlag(id, ref, flagged)`, `fetchPracticeSummary(id)`
  - Keys: `practiceRunKeys.run(id)`, `.check(id, ref)`, `.summary(id)`
  - Hooks: `usePracticeRun(id)`, `usePracticeCheck(id, ref | null)`, `useCheckQuestion(id)`, `useFlagQuestion(id)`, `usePracticeSummary(id, enabled)`
  - `CHECK_POLL_MS = 1500`, `SUMMARY_POLL_MS = 4000`

- [ ] **Step 1: Write the failing test**

```ts
// web/tests/unit/practiceRunApi.test.ts
import { beforeEach, describe, expect, it, vi } from "vitest"

vi.mock("@/lib/api", () => ({ request: vi.fn(() => Promise.resolve({})) }))

import { request } from "@/lib/api"
import {
  fetchPracticeCheck,
  fetchPracticeRun,
  fetchPracticeSummary,
  postPracticeCheck,
  practiceRunPaths,
  putPracticeFlag,
} from "@/lib/practiceRunApi"
import { CHECK_POLL_MS, checkRefetchInterval, practiceRunKeys, summaryRefetchInterval } from "@/lib/hooks/usePracticeRunApi"

const mocked = vi.mocked(request)

describe("practice run API", () => {
  beforeEach(() => mocked.mockClear())

  it("builds every path under /student/practice/{id} and encodes the question ref", () => {
    expect(practiceRunPaths.run("a1")).toBe("/student/practice/a1/run")
    expect(practiceRunPaths.check("a1", "q 1")).toBe("/student/practice/a1/questions/q%201/check")
    expect(practiceRunPaths.flag("a1", "q2")).toBe("/student/practice/a1/questions/q2/flag")
    expect(practiceRunPaths.summary("a1")).toBe("/student/practice/a1/summary")
  })

  it("reads the run, the check and the summary with GET", async () => {
    await fetchPracticeRun("a1")
    await fetchPracticeCheck("a1", "q1")
    await fetchPracticeSummary("a1")
    expect(mocked.mock.calls.map((c) => c[0])).toEqual([
      "/student/practice/a1/run",
      "/student/practice/a1/questions/q1/check",
      "/student/practice/a1/summary",
    ])
    expect(mocked.mock.calls.every((c) => c[1] === undefined)).toBe(true)
  })

  it("posts a check with both answer fields and puts a flag", async () => {
    await postPracticeCheck("a1", "q1", { answerText: "9.22", workingText: "2a = (6, 8)" })
    await putPracticeFlag("a1", "q1", true)
    expect(mocked.mock.calls[0]).toEqual([
      "/student/practice/a1/questions/q1/check",
      { method: "POST", body: JSON.stringify({ answerText: "9.22", workingText: "2a = (6, 8)" }) },
    ])
    expect(mocked.mock.calls[1]).toEqual([
      "/student/practice/a1/questions/q1/flag",
      { method: "PUT", body: JSON.stringify({ flagged: true }) },
    ])
  })
})

describe("practice run query keys and polling", () => {
  it("keys are scoped by assignment and question", () => {
    expect(practiceRunKeys.run("a1")).toEqual(["practice", "run", "a1"])
    expect(practiceRunKeys.check("a1", "q1")).toEqual(["practice", "run", "a1", "check", "q1"])
    expect(practiceRunKeys.summary("a1")).toEqual(["practice", "summary", "a1"])
  })

  it("polls a check only while it is checking", () => {
    expect(checkRefetchInterval("checking")).toBe(CHECK_POLL_MS)
    expect(checkRefetchInterval("checked")).toBe(false)
    expect(checkRefetchInterval("failed")).toBe(false)
    expect(checkRefetchInterval(undefined)).toBe(CHECK_POLL_MS)
  })

  it("polls the summary only while unmarked", () => {
    expect(summaryRefetchInterval(false)).toBe(4000)
    expect(summaryRefetchInterval(true)).toBe(false)
    expect(summaryRefetchInterval(undefined)).toBe(false)
  })
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd web && npx vitest run tests/unit/practiceRunApi.test.ts`
Expected: FAIL. `Failed to resolve import "@/lib/practiceRunApi"`.

- [ ] **Step 3: Write the types**

```ts
// web/src/lib/practiceRunTypes.ts
/*
 * Wire types for the L3 practice-run routes (`lemely/web/schemas_practice_run.py`).
 * camelCase, mirroring the DTOs field for field. Scheme text (`points`) and
 * `correctOption` appear only on a check whose `status` is "checked".
 */

export type PracticeCheckStatus = "checking" | "checked" | "failed"

export interface PracticeCheckPoint {
  text: string
  verdict: "awarded" | "withheld" | "unverifiable"
  note: string | null
}

export interface PracticeCheck {
  questionRef: string
  status: PracticeCheckStatus
  awardedMarks: number | null
  maximumMarks: number
  points: PracticeCheckPoint[]
  correctOption: string | null
  feedback: string | null
  needsTeacherReview: boolean
  error: "check_failed" | null
  combo: number
  bestCombo: number
  wonMarks: number
}

export interface PracticeRunQuestion {
  questionRef: string
  position: number
  topic: string | null
  questionType: string
  prompt: string
  totalMarks: number
  mcqOptions: string[] | null
  answerText: string | null
  workingText: string | null
  flagged: boolean
  check: PracticeCheck | null
}

export interface PracticeRun {
  assignmentId: string
  subjectCode: string
  title: string
  focusTopic: string | null
  includedTopics: string[]
  submissionStatus: string
  marksToWin: number | null
  totalMarks: number
  questions: PracticeRunQuestion[]
  combo: number
  bestCombo: number
  wonMarks: number
  resumeIndex: number
}

export interface PracticeCheckRequest {
  answerText: string | null
  workingText: string | null
}

export interface PracticeFlag {
  questionRef: string
  flagged: boolean
}

export interface PracticeToday {
  practice: boolean
  flashcards: boolean
  paper: boolean
}

export interface PracticeMastery {
  topic: string
  before: number | null
  after: number
}

export interface PracticeNextTopic {
  topic: string
  marksLost: number
}

export interface PracticeSummary {
  assignmentId: string
  subjectCode: string
  marked: boolean
  awardedMarks: number | null
  maximumMarks: number | null
  marksToWin: number | null
  marksBack: number | null
  bestCombo: number
  xpAwarded: number
  focusTopic: string | null
  includedTopics: string[]
  questionCount: number
  mastery: PracticeMastery | null
  nextTopic: PracticeNextTopic | null
  today: PracticeToday
}
```

- [ ] **Step 4: Write the API functions**

```ts
// web/src/lib/practiceRunApi.ts
import { request } from "@/lib/api"
import type {
  PracticeCheck,
  PracticeCheckRequest,
  PracticeFlag,
  PracticeRun,
  PracticeSummary,
} from "@/lib/practiceRunTypes"

/* L3 practice run. No `fallback` is passed to `request()`: a failure surfaces
   as an error the screen renders, never as silent empty data. */

export const practiceRunPaths = {
  run: (id: string) => `/student/practice/${id}/run`,
  check: (id: string, ref: string) => `/student/practice/${id}/questions/${encodeURIComponent(ref)}/check`,
  flag: (id: string, ref: string) => `/student/practice/${id}/questions/${encodeURIComponent(ref)}/flag`,
  summary: (id: string) => `/student/practice/${id}/summary`,
} as const

export function fetchPracticeRun(id: string): Promise<PracticeRun> {
  return request<PracticeRun>(practiceRunPaths.run(id))
}

export function postPracticeCheck(id: string, ref: string, body: PracticeCheckRequest): Promise<PracticeCheck> {
  return request<PracticeCheck>(practiceRunPaths.check(id, ref), {
    method: "POST",
    body: JSON.stringify(body),
  })
}

export function fetchPracticeCheck(id: string, ref: string): Promise<PracticeCheck> {
  return request<PracticeCheck>(practiceRunPaths.check(id, ref))
}

export function putPracticeFlag(id: string, ref: string, flagged: boolean): Promise<PracticeFlag> {
  return request<PracticeFlag>(practiceRunPaths.flag(id, ref), {
    method: "PUT",
    body: JSON.stringify({ flagged }),
  })
}

export function fetchPracticeSummary(id: string): Promise<PracticeSummary> {
  return request<PracticeSummary>(practiceRunPaths.summary(id))
}
```

- [ ] **Step 5: Write the hooks**

```ts
// web/src/lib/hooks/usePracticeRunApi.ts
import { useMutation, useQuery, type UseMutationResult, type UseQueryResult } from "@tanstack/react-query"
import {
  fetchPracticeCheck,
  fetchPracticeRun,
  fetchPracticeSummary,
  postPracticeCheck,
  putPracticeFlag,
} from "@/lib/practiceRunApi"
import type {
  PracticeCheck,
  PracticeCheckRequest,
  PracticeCheckStatus,
  PracticeFlag,
  PracticeRun,
  PracticeSummary,
} from "@/lib/practiceRunTypes"

export const CHECK_POLL_MS = 1500
export const SUMMARY_POLL_MS = 4000

/* L3 query keys. They live under "practice" so a practice-wide invalidation
   still reaches them, and they never collide with L4's keys. */
export const practiceRunKeys = {
  run: (id: string) => ["practice", "run", id] as const,
  check: (id: string, ref: string) => ["practice", "run", id, "check", ref] as const,
  summary: (id: string) => ["practice", "summary", id] as const,
}

export function checkRefetchInterval(status: PracticeCheckStatus | undefined): number | false {
  return status === undefined || status === "checking" ? CHECK_POLL_MS : false
}

export function summaryRefetchInterval(marked: boolean | undefined): number | false {
  return marked === false ? SUMMARY_POLL_MS : false
}

export function usePracticeRun(id: string): UseQueryResult<PracticeRun, Error> {
  return useQuery({
    queryKey: practiceRunKeys.run(id),
    queryFn: () => fetchPracticeRun(id),
    enabled: !!id,
    // The run is local state once loaded. A refetch mid-run would fight the reducer.
    refetchOnWindowFocus: false,
    staleTime: Infinity,
  })
}

/** Polls one running check. `ref === null` turns polling off. */
export function usePracticeCheck(id: string, ref: string | null): UseQueryResult<PracticeCheck, Error> {
  return useQuery({
    queryKey: practiceRunKeys.check(id, ref ?? ""),
    queryFn: () => fetchPracticeCheck(id, ref ?? ""),
    enabled: !!id && ref !== null,
    refetchInterval: (query) => checkRefetchInterval(query.state.data?.status),
    gcTime: 0,
  })
}

export function useCheckQuestion(
  id: string,
): UseMutationResult<PracticeCheck, Error, { questionRef: string; body: PracticeCheckRequest }> {
  return useMutation({
    mutationFn: ({ questionRef, body }) => postPracticeCheck(id, questionRef, body),
  })
}

export function useFlagQuestion(
  id: string,
): UseMutationResult<PracticeFlag, Error, { questionRef: string; flagged: boolean }> {
  return useMutation({
    mutationFn: ({ questionRef, flagged }) => putPracticeFlag(id, questionRef, flagged),
  })
}

export function usePracticeSummary(id: string, enabled: boolean): UseQueryResult<PracticeSummary, Error> {
  return useQuery({
    queryKey: practiceRunKeys.summary(id),
    queryFn: () => fetchPracticeSummary(id),
    enabled: !!id && enabled,
    refetchInterval: (query) => summaryRefetchInterval(query.state.data?.marked),
  })
}
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `cd web && npx vitest run tests/unit/practiceRunApi.test.ts`
Expected: PASS (6 tests).

- [ ] **Step 7: Commit**

```bash
git commit -S -m "feat(web): practice run API, query keys and hooks" -- web/src/lib/practiceRunTypes.ts web/src/lib/practiceRunApi.ts web/src/lib/hooks/usePracticeRunApi.ts web/tests/unit/practiceRunApi.test.ts
```

---

### Task 9: The run view model (pure reducer and selectors)

**Files:**
- Create: `web/src/portals/student/screens/practice/run/practiceRunModel.ts`
- Test: `web/tests/unit/practiceRunModel.test.ts`

**Interfaces:**
- Consumes: Task 8 types. `answerInputKind`, `isQuestionAnswered`, `formatQuestionTopic`, `LocalAnswer`, `CachedAnswers`, `mergeAnswers` from `@/components/quiz/quizTakerData`. `BinnyMood` from `@/components/redesign`. `ApiError` from `@/lib/api`.
- Produces (all exported):
  - `PRACTICE_HOME = "/student/practice"`, `CHECK_TIMEOUT_MS = 60000`
  - `RunState`, `RunAction`, `initialRunState(run, cached)`, `runReducer(state, action)`
  - `shouldShowStart(run, cached)`, `runRedirect(run): "result" | null`
  - `startView(run, subjectName)`, `estimatedMinutes(questions)`
  - `progressDots(run, state)`: `{ tone: DotTone; label: string }[]`
  - `wonMeta(run, state)`: `{ won, target, pct, suffix }`
  - `answerKind(q)`, `canCheck(q, answer)`, `mcqTiles(options)`
  - `primaryAction(run, state, online)`: `PrimaryAction`
  - `revealView(check, questionType)`: `RevealView | null`
  - `blankPositions(run, state)`, `blankSheetCopy(positions)`, `leaveCopy(position)`
  - `keyAction(key, ctx)`: `KeyAction | null`
  - `runErrorCopy(error)`: `RunErrorCopy`
  - `marksLabel(n)`

- [ ] **Step 1: Write the failing tests**

```ts
// web/tests/unit/practiceRunModel.test.ts
import { describe, expect, it } from "vitest"
import { ApiError } from "@/lib/api"
import type { PracticeCheck, PracticeRun, PracticeRunQuestion } from "@/lib/practiceRunTypes"
import {
  blankPositions,
  blankSheetCopy,
  canCheck,
  estimatedMinutes,
  initialRunState,
  keyAction,
  leaveCopy,
  marksLabel,
  mcqTiles,
  primaryAction,
  progressDots,
  revealView,
  runErrorCopy,
  runReducer,
  runRedirect,
  shouldShowStart,
  startView,
  wonMeta,
} from "@/portals/student/screens/practice/run/practiceRunModel"

function q(position: number, over: Partial<PracticeRunQuestion> = {}): PracticeRunQuestion {
  return {
    questionRef: `q${position}`,
    position,
    topic: "Vectors",
    questionType: "calculation",
    prompt: `Prompt ${position}`,
    totalMarks: 2,
    mcqOptions: null,
    answerText: null,
    workingText: null,
    flagged: false,
    check: null,
    ...over,
  }
}

function check(ref: string, awarded: number | null, max: number, over: Partial<PracticeCheck> = {}): PracticeCheck {
  return {
    questionRef: ref,
    status: "checked",
    awardedMarks: awarded,
    maximumMarks: max,
    points: [],
    correctOption: null,
    feedback: null,
    needsTeacherReview: false,
    error: null,
    combo: 0,
    bestCombo: 0,
    wonMarks: 0,
    ...over,
  }
}

function run(over: Partial<PracticeRun> = {}): PracticeRun {
  return {
    assignmentId: "a1",
    subjectCode: "0580",
    title: "Mathematics practice",
    focusTopic: "Vectors",
    includedTopics: ["Vectors"],
    submissionStatus: "in_progress",
    marksToWin: 9,
    totalMarks: 13,
    questions: [q(1), q(2), q(3)],
    combo: 0,
    bestCombo: 0,
    wonMarks: 0,
    resumeIndex: 0,
    ...over,
  }
}

describe("start and redirect", () => {
  it("shows the start screen only before any answer or check exists", () => {
    expect(shouldShowStart(run(), null)).toBe(true)
    expect(shouldShowStart(run({ questions: [q(1, { answerText: "x" })] }), null)).toBe(false)
    expect(shouldShowStart(run(), { q1: { answerText: "x", workingText: null, dirty: true } })).toBe(false)
    expect(shouldShowStart(run({ questions: [q(1, { check: check("q1", 1, 2) })] }), null)).toBe(false)
    expect(shouldShowStart(run({ submissionStatus: "submitted" }), null)).toBe(false)
  })

  it("sends a submitted or marked run to its result", () => {
    expect(runRedirect(run({ submissionStatus: "submitted" }))).toBe("result")
    expect(runRedirect(run({ submissionStatus: "marked" }))).toBe("result")
    expect(runRedirect(run())).toBeNull()
  })

  it("estimates minutes from marks and builds the start copy", () => {
    expect(estimatedMinutes([q(1, { totalMarks: 13 })])).toBe(10)
    expect(estimatedMinutes([q(1, { totalMarks: 1 })])).toBe(1)
    const view = startView(run(), "Mathematics")
    expect(view.title).toBe("Vectors")
    expect(view.sub).toBe("Mathematics · 3 questions · about 5 min")
    expect(view.goal).toEqual({ value: "+9", title: "marks to win back", sub: "What Vectors cost you on your last paper" })
    expect(view.covers).toEqual(["Vectors"])
    expect(startView(run({ focusTopic: null, marksToWin: null }), "Mathematics").title).toBe("Mathematics")
    expect(startView(run({ marksToWin: null }), "Mathematics").goal).toBeNull()
  })
})

describe("reducer", () => {
  it("starts at the server's resume index with server answers under dirty local edits", () => {
    const state = initialRunState(run({ resumeIndex: 2, questions: [q(1, { answerText: "srv" }), q(2), q(3)] }), {
      q1: { answerText: "local", workingText: null, dirty: true },
    })
    expect(state.index).toBe(2)
    expect(state.answers.q1.answerText).toBe("local")
  })

  it("records a check, opens the reveal, and takes combo and won marks from the server", () => {
    let state = initialRunState(run(), null)
    state = runReducer(state, { type: "checkUpdated", check: check("q1", 2, 2, { combo: 1, bestCombo: 1, wonMarks: 2 }) })
    expect(state.revealRef).toBe("q1")
    expect([state.combo, state.bestCombo, state.wonMarks]).toEqual([1, 1, 2])
    state = runReducer(state, { type: "next" })
    expect(state.revealRef).toBeNull()
    expect(state.index).toBe(1)
  })

  it("a timed-out check reads as failed locally", () => {
    let state = initialRunState(run(), null)
    state = runReducer(state, { type: "checkUpdated", check: check("q1", null, 2, { status: "checking" }) })
    state = runReducer(state, { type: "checkTimedOut", questionRef: "q1" })
    expect(state.checks.q1.status).toBe("failed")
  })

  it("skip moves on without a check, and goTo clamps", () => {
    let state = initialRunState(run(), null)
    state = runReducer(state, { type: "skip" })
    expect(state.index).toBe(1)
    state = runReducer(state, { type: "goTo", index: 99 })
    expect(state.index).toBe(2)
  })

  it("sheets open and close, and a submit failure closes them with the message", () => {
    let state = initialRunState(run(), null)
    state = runReducer(state, { type: "openSheet", sheet: "leave" })
    expect(state.sheet).toBe("leave")
    state = runReducer(state, { type: "submitFailed", message: "nope" })
    expect(state.sheet).toBeNull()
    expect(state.submitError).toBe("nope")
  })
})

describe("header", () => {
  it("colours dots by result and marks the current one", () => {
    const r = run({ questions: [q(1, { check: check("q1", 2, 2) }), q(2, { check: check("q2", 1, 2) }), q(3, { check: check("q3", 0, 2) })] })
    const state = { ...initialRunState(r, null), index: 1 }
    expect(progressDots(r, state).map((d) => d.tone)).toEqual(["ok", "now", "no"])
    expect(progressDots(r, state)[1].label).toBe("Question 2 of 3")
  })

  it("counts marks won against the target, or against the set when there is none", () => {
    const state = { ...initialRunState(run(), null), wonMarks: 4 }
    expect(wonMeta(run(), state)).toEqual({ won: 4, target: 9, pct: 4 / 9, suffix: "of 9 marks back" })
    expect(wonMeta(run({ marksToWin: null }), state).suffix).toBe("of 13 marks")
    expect(wonMeta(run({ marksToWin: 2 }), state).pct).toBe(1)
  })
})

describe("answering", () => {
  it("picks the input kind and when Check is enabled", () => {
    expect(canCheck(q(1), { answerText: " ", workingText: null })).toBe(false)
    expect(canCheck(q(1), { answerText: null, workingText: "2a = (6, 8)" })).toBe(true)
  })

  it("labels MCQ tiles A to D and hides a body equal to its letter", () => {
    expect(mcqTiles(["A", "B"])).toEqual([
      { letter: "A", option: "A", body: null },
      { letter: "B", option: "B", body: null },
    ])
    expect(mcqTiles(["(4, -6)"])[0]).toEqual({ letter: "A", option: "(4, -6)", body: "(4, -6)" })
  })

  it("chooses the footer action", () => {
    const r = run()
    const state = initialRunState(r, null)
    expect(primaryAction(r, state, true)).toEqual({ kind: "check", label: "Check", disabled: true })
    const typed = { ...state, answers: { q1: { answerText: "x", workingText: null } } }
    expect(primaryAction(r, typed, true)).toEqual({ kind: "check", label: "Check", disabled: false })
    expect(primaryAction(r, typed, false)).toEqual({ kind: "waitOnline", label: "Check when online", disabled: true })
    const checked = { ...typed, checks: { q1: check("q1", 1, 2) } }
    expect(primaryAction(r, checked, true)).toEqual({ kind: "next", label: "Next question", disabled: false })
    const last = { ...checked, index: 2, checks: { ...checked.checks, q3: check("q3", 1, 2) } }
    expect(primaryAction(r, last, true)).toEqual({ kind: "finish", label: "See my result", disabled: false })
    const failed = { ...typed, checks: { q1: check("q1", null, 2, { status: "failed" }) } }
    expect(primaryAction(r, failed, true)).toEqual({ kind: "check", label: "Try again", disabled: false })
  })
})

describe("reveal", () => {
  it("right, with a combo line only from 2 in a row", () => {
    expect(revealView(check("q1", 1, 1, { combo: 3 }), "mcq")).toMatchObject({
      kind: "ok", title: "Spot on!", marks: "+1 mark", comboLine: "3 in a row!", mood: "happy",
    })
    expect(revealView(check("q1", 2, 2, { combo: 1 }), "calculation")).toMatchObject({ comboLine: null, mood: null })
  })

  it("part marks, no marks, checking and failed", () => {
    expect(revealView(check("q1", 2, 3), "calculation")).toMatchObject({ kind: "part", title: "So close", badge: "2/3", marks: "+2 marks", showChallenge: true })
    expect(revealView(check("q1", 0, 1, { correctOption: "C" }), "mcq")).toMatchObject({ kind: "zero", title: "No marks this time", badge: "0/1", answerLine: "The answer is C" })
    expect(revealView(check("q1", null, 3, { status: "checking" }), "calculation")).toMatchObject({ kind: "wait", title: "Checking your working…", mood: "thinking" })
    expect(revealView(check("q1", null, 3, { status: "failed" }), "calculation")).toMatchObject({ kind: "failed", title: "Couldn't check this one" })
  })

  it("says when a teacher will look again", () => {
    expect(revealView(check("q1", 1, 3, { needsTeacherReview: true }), "calculation")?.reviewLine).toBe("Teacher will check this one")
  })
})

describe("sheets and copy", () => {
  it("lists blank questions that were never checked", () => {
    const r = run()
    const state = { ...initialRunState(r, null), answers: { q1: { answerText: "x", workingText: null } }, checks: { q1: check("q1", 1, 2) } }
    expect(blankPositions(r, state)).toEqual([2, 3])
  })

  it("words the blank sheet for one and for many", () => {
    expect(blankSheetCopy([5])).toEqual({ title: "One question left blank", body: "Question 5 has no answer. Blank answers score 0.", go: "Go to question 5" })
    expect(blankSheetCopy([2, 4, 5])).toEqual({ title: "3 questions left blank", body: "Questions 2, 4 and 5 have no answers. Blank answers score 0.", go: "Go to question 2" })
  })

  it("words the leave sheet and pluralises marks", () => {
    expect(leaveCopy(4)).toBe("Your answers are saved. Pick up at question 4 any time from Home.")
    expect(marksLabel(1)).toBe("+1 mark")
    expect(marksLabel(0)).toBe("+0 marks")
  })
})

describe("keyboard", () => {
  const ctx = { kind: "mcq" as const, optionCount: 4, blocked: false, inTextField: false, inTextarea: false }
  it("maps A–D to options and Enter to the primary action", () => {
    expect(keyAction("b", ctx)).toEqual({ type: "choose", index: 1 })
    expect(keyAction("E", ctx)).toBeNull()
    expect(keyAction("Enter", ctx)).toEqual({ type: "primary" })
  })
  it("ignores letters while typing, Enter in a textarea, and everything while a sheet is open", () => {
    expect(keyAction("a", { ...ctx, inTextField: true })).toBeNull()
    expect(keyAction("Enter", { ...ctx, inTextField: true })).toEqual({ type: "primary" })
    expect(keyAction("Enter", { ...ctx, inTextField: true, inTextarea: true })).toBeNull()
    expect(keyAction("a", { ...ctx, blocked: true })).toBeNull()
  })
})

describe("errors", () => {
  it("maps 403, 404 and anything else to the ER frame copy", () => {
    expect(runErrorCopy(new ApiError("x", 403))).toMatchObject({ title: "This set isn't yours", retry: false })
    expect(runErrorCopy(new ApiError("x", 404))).toMatchObject({ title: "We couldn't find this set", retry: false })
    expect(runErrorCopy(new Error("boom"))).toMatchObject({
      title: "We couldn't load this set",
      body: "Check your connection, then try again. Nothing you answered is lost.",
      retry: true,
    })
  })
})
```

Check the `ApiError` constructor signature in `web/src/lib/api.ts:19` before running. If it is not `(message, status)`, adjust the three `new ApiError(...)` calls to match.

- [ ] **Step 2: Run them to verify they fail**

Run: `cd web && npx vitest run tests/unit/practiceRunModel.test.ts`
Expected: FAIL with an unresolved import of `practiceRunModel`.

- [ ] **Step 3: Write the view model**

```ts
// web/src/portals/student/screens/practice/run/practiceRunModel.ts
/*
 * L3 practice run: every decision the run screens make, as pure functions.
 * The screens only render what these return. Copy comes from the approved
 * mock (`.impeccable/mocks/student-r2/pr.js`). Copy for states the mock lacks
 * ("No marks this time", "Couldn't check this one") is listed in the plan's
 * Needs user decision 7.
 */
import { ApiError } from "@/lib/api"
import type { PracticeCheck, PracticeRun, PracticeRunQuestion } from "@/lib/practiceRunTypes"
import type { BinnyMood } from "@/components/redesign"
import {
  answerInputKind,
  formatQuestionTopic,
  isQuestionAnswered,
  mergeAnswers,
  type AnswerInputKind,
  type CachedAnswers,
  type LocalAnswer,
} from "@/components/quiz/quizTakerData"

export const PRACTICE_HOME = "/student/practice"
export const CHECK_TIMEOUT_MS = 60_000

export type DotTone = "ok" | "part" | "no" | "now" | "todo"
export type RunSheet = null | "leave" | "blank"

export interface RunState {
  total: number
  index: number
  answers: Record<string, LocalAnswer>
  checks: Record<string, PracticeCheck>
  flagged: Record<string, boolean>
  revealRef: string | null
  sheet: RunSheet
  combo: number
  bestCombo: number
  wonMarks: number
  submitError: string | null
}

export type RunAction =
  | { type: "answer"; questionRef: string; field: "answerText" | "workingText"; value: string }
  | { type: "goTo"; index: number }
  | { type: "checkUpdated"; check: PracticeCheck }
  | { type: "checkTimedOut"; questionRef: string }
  | { type: "next" }
  | { type: "skip" }
  | { type: "flag"; questionRef: string; flagged: boolean }
  | { type: "openSheet"; sheet: "leave" | "blank" }
  | { type: "closeSheet" }
  | { type: "submitFailed"; message: string }
  | { type: "clearSubmitError" }

const clamp = (i: number, total: number) => Math.max(0, Math.min(i, Math.max(0, total - 1)))

export function initialRunState(run: PracticeRun, cached: CachedAnswers | null): RunState {
  const server: Record<string, LocalAnswer> = {}
  const checks: Record<string, PracticeCheck> = {}
  const flagged: Record<string, boolean> = {}
  for (const q of run.questions) {
    server[q.questionRef] = { answerText: q.answerText, workingText: q.workingText }
    if (q.check) checks[q.questionRef] = q.check
    if (q.flagged) flagged[q.questionRef] = true
  }
  return {
    total: run.questions.length,
    index: clamp(run.resumeIndex, run.questions.length),
    answers: mergeAnswers(server, cached),
    checks,
    flagged,
    revealRef: null,
    sheet: null,
    combo: run.combo,
    bestCombo: run.bestCombo,
    wonMarks: run.wonMarks,
    submitError: null,
  }
}

export function runReducer(state: RunState, action: RunAction): RunState {
  switch (action.type) {
    case "answer": {
      const prev = state.answers[action.questionRef] ?? { answerText: null, workingText: null }
      return { ...state, answers: { ...state.answers, [action.questionRef]: { ...prev, [action.field]: action.value } } }
    }
    case "goTo":
      return { ...state, index: clamp(action.index, state.total), revealRef: null, sheet: null }
    case "checkUpdated":
      return {
        ...state,
        checks: { ...state.checks, [action.check.questionRef]: action.check },
        revealRef: action.check.questionRef,
        combo: action.check.combo,
        bestCombo: action.check.bestCombo,
        wonMarks: action.check.wonMarks,
      }
    case "checkTimedOut": {
      const current = state.checks[action.questionRef]
      if (!current || current.status !== "checking") return state
      return { ...state, checks: { ...state.checks, [action.questionRef]: { ...current, status: "failed", error: "check_failed" } } }
    }
    case "next":
    case "skip":
      return { ...state, revealRef: null, index: clamp(state.index + 1, state.total) }
    case "flag":
      return { ...state, flagged: { ...state.flagged, [action.questionRef]: action.flagged } }
    case "openSheet":
      return { ...state, sheet: action.sheet }
    case "closeSheet":
      return { ...state, sheet: null }
    case "submitFailed":
      return { ...state, sheet: null, submitError: action.message }
    case "clearSubmitError":
      return { ...state, submitError: null }
  }
}

// ── Start ───────────────────────────────────────────────────────────────

export function shouldShowStart(run: PracticeRun, cached: CachedAnswers | null): boolean {
  if (run.submissionStatus !== "not_started" && run.submissionStatus !== "in_progress") return false
  if (run.questions.some((q) => q.check !== null || isQuestionAnswered(q))) return false
  if (cached && Object.values(cached).some((entry) => isQuestionAnswered(entry))) return false
  return true
}

export function runRedirect(run: PracticeRun): "result" | null {
  return run.submissionStatus === "submitted" || run.submissionStatus === "marked" ? "result" : null
}

export function estimatedMinutes(questions: readonly PracticeRunQuestion[]): number {
  const marks = questions.reduce((sum, q) => sum + q.totalMarks, 0)
  return Math.max(1, Math.round(marks * 0.75))
}

export interface StartView {
  title: string
  sub: string
  goal: { value: string; title: string; sub: string } | null
  covers: string[]
}

export function startView(run: PracticeRun, subjectName: string): StartView {
  const title = run.focusTopic ? formatQuestionTopic(run.focusTopic) : subjectName
  const n = run.questions.length
  return {
    title,
    sub: `${subjectName} · ${n} question${n === 1 ? "" : "s"} · about ${estimatedMinutes(run.questions)} min`,
    goal: run.marksToWin
      ? { value: `+${run.marksToWin}`, title: "marks to win back", sub: `What ${title} cost you on your last paper` }
      : null,
    covers: run.includedTopics.map((t) => formatQuestionTopic(t)),
  }
}

// ── Header ──────────────────────────────────────────────────────────────

export function progressDots(run: PracticeRun, state: RunState): { tone: DotTone; label: string }[] {
  return run.questions.map((q, i) => {
    const label = `Question ${i + 1} of ${run.questions.length}`
    if (i === state.index) return { tone: "now", label }
    const c = state.checks[q.questionRef]
    if (!c || c.status !== "checked" || c.awardedMarks === null) return { tone: "todo", label }
    if (c.awardedMarks >= c.maximumMarks) return { tone: "ok", label }
    return { tone: c.awardedMarks > 0 ? "part" : "no", label }
  })
}

export function wonMeta(run: PracticeRun, state: RunState) {
  const target = run.marksToWin ?? run.totalMarks
  return {
    won: state.wonMarks,
    target,
    pct: target > 0 ? Math.min(1, state.wonMarks / target) : 0,
    suffix: run.marksToWin ? `of ${target} marks back` : `of ${target} marks`,
  }
}

// ── Answering ───────────────────────────────────────────────────────────

export function answerKind(q: PracticeRunQuestion): AnswerInputKind {
  return answerInputKind(q.questionType, q.mcqOptions)
}

export function canCheck(_q: PracticeRunQuestion, answer: LocalAnswer | undefined): boolean {
  return !!answer && isQuestionAnswered(answer)
}

export function mcqTiles(options: readonly string[]) {
  return options.map((option, i) => {
    const letter = String.fromCharCode(65 + i)
    return { letter, option, body: option.trim().toUpperCase() === letter ? null : option }
  })
}

export type PrimaryAction =
  | { kind: "check"; label: "Check" | "Try again"; disabled: boolean }
  | { kind: "waitOnline"; label: "Check when online"; disabled: true }
  | { kind: "checking"; label: "Checking…"; disabled: true }
  | { kind: "next"; label: "Next question"; disabled: false }
  | { kind: "finish"; label: "See my result"; disabled: false }

export function primaryAction(run: PracticeRun, state: RunState, online: boolean): PrimaryAction {
  const q = run.questions[state.index]
  const c = q ? state.checks[q.questionRef] : undefined
  const isLast = state.index === run.questions.length - 1
  if (c?.status === "checked") return isLast ? { kind: "finish", label: "See my result", disabled: false } : { kind: "next", label: "Next question", disabled: false }
  if (c?.status === "checking") return { kind: "checking", label: "Checking…", disabled: true }
  if (!online) return { kind: "waitOnline", label: "Check when online", disabled: true }
  const label = c?.status === "failed" ? "Try again" : "Check"
  return { kind: "check", label, disabled: !q || !canCheck(q, state.answers[q.questionRef]) }
}

// ── Reveal ──────────────────────────────────────────────────────────────

export type RevealKind = "ok" | "part" | "zero" | "wait" | "failed"

export interface RevealView {
  kind: RevealKind
  title: string
  sub: string | null
  badge: string | null
  marks: string | null
  comboLine: string | null
  mood: BinnyMood | null
  points: PracticeCheck["points"]
  answerLine: string | null
  reviewLine: string | null
  showChallenge: boolean
}

export function marksLabel(n: number): string {
  return `+${n} mark${n === 1 ? "" : "s"}`
}

export function revealView(check: PracticeCheck | undefined, questionType: string): RevealView | null {
  if (!check) return null
  const base: RevealView = {
    kind: "wait", title: "", sub: null, badge: null, marks: null, comboLine: null, mood: null,
    points: check.points, answerLine: null,
    reviewLine: check.needsTeacherReview ? "Teacher will check this one" : null,
    showChallenge: false,
  }
  if (check.status === "checking") {
    return { ...base, kind: "wait", title: "Checking your working…", sub: "Method marks too. A few seconds.", mood: "thinking" }
  }
  if (check.status === "failed" || check.awardedMarks === null) {
    return { ...base, kind: "failed", title: "Couldn't check this one", sub: "It gets marked when you finish." }
  }
  const a = check.awardedMarks
  const m = check.maximumMarks
  if (a >= m) {
    const combo = check.combo >= 2
    return { ...base, kind: "ok", title: "Spot on!", marks: marksLabel(a), comboLine: combo ? `${check.combo} in a row!` : null, mood: combo ? "happy" : null }
  }
  const answerLine = questionType === "mcq" && check.correctOption ? `The answer is ${check.correctOption}` : null
  if (a > 0) {
    return { ...base, kind: "part", title: "So close", badge: `${a}/${m}`, marks: marksLabel(a), answerLine, showChallenge: true }
  }
  return { ...base, kind: "zero", title: "No marks this time", badge: `0/${m}`, marks: marksLabel(0), answerLine, showChallenge: true }
}

// ── Sheets ──────────────────────────────────────────────────────────────

export function blankPositions(run: PracticeRun, state: RunState): number[] {
  return run.questions
    .filter((q) => {
      const c = state.checks[q.questionRef]
      if (c && c.status !== "failed") return false
      const a = state.answers[q.questionRef] ?? { answerText: null, workingText: null }
      return !isQuestionAnswered(a)
    })
    .map((q) => q.position)
}

function listWords(ns: number[]): string {
  if (ns.length <= 1) return ns.join("")
  return `${ns.slice(0, -1).join(", ")} and ${ns[ns.length - 1]}`
}

export function blankSheetCopy(positions: number[]) {
  const first = positions[0]
  if (positions.length === 1) {
    return { title: "One question left blank", body: `Question ${first} has no answer. Blank answers score 0.`, go: `Go to question ${first}` }
  }
  return {
    title: `${positions.length} questions left blank`,
    body: `Questions ${listWords(positions)} have no answers. Blank answers score 0.`,
    go: `Go to question ${first}`,
  }
}

export function leaveCopy(position: number): string {
  return `Your answers are saved. Pick up at question ${position} any time from Home.`
}

// ── Keyboard (desktop DR frame) ─────────────────────────────────────────

export interface KeyContext {
  kind: AnswerInputKind
  optionCount: number
  blocked: boolean
  inTextField: boolean
  inTextarea: boolean
}

export type KeyAction = { type: "choose"; index: number } | { type: "primary" }

export function keyAction(key: string, ctx: KeyContext): KeyAction | null {
  if (ctx.blocked) return null
  if (key === "Enter") return ctx.inTextarea ? null : { type: "primary" }
  if (ctx.inTextField || ctx.kind !== "mcq" || key.length !== 1) return null
  const index = key.toUpperCase().charCodeAt(0) - 65
  return index >= 0 && index < Math.min(4, ctx.optionCount) ? { type: "choose", index } : null
}

// ── Errors (ER frame) ───────────────────────────────────────────────────

export interface RunErrorCopy {
  title: string
  body: string
  retry: boolean
}

export function runErrorCopy(error: unknown): RunErrorCopy {
  if (error instanceof ApiError && error.status === 403) {
    return { title: "This set isn't yours", body: "Open your own practice from the Practice tab.", retry: false }
  }
  if (error instanceof ApiError && error.status === 404) {
    return { title: "We couldn't find this set", body: "Start a new one from the Practice tab.", retry: false }
  }
  return { title: "We couldn't load this set", body: "Check your connection, then try again. Nothing you answered is lost.", retry: true }
}

export const EMPTY_SET_COPY: RunErrorCopy = {
  title: "This set has no questions",
  body: "Build another one from the Practice tab.",
  retry: false,
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd web && npx vitest run tests/unit/practiceRunModel.test.ts && npx tsc -p tsconfig.app.json --noEmit`
Expected: PASS. The `tsc` run fails only if F1's `BinnyMood` export is missing. F1 must be merged first (master plan merge order).

- [ ] **Step 5: Commit**

```bash
git commit -S -m "feat(web): practice run view model" -- web/src/portals/student/screens/practice/run/practiceRunModel.ts web/tests/unit/practiceRunModel.test.ts
```

---

### Task 10: The result view model

**Files:**
- Create: `web/src/portals/student/screens/practice/result/practiceResultModel.ts`
- Test: `web/tests/unit/practiceResultModel.test.ts`

**Interfaces:**
- Consumes: `PracticeResult` (`@/lib/practiceTypes`), `PracticeSummary`, `PracticeFilterSet`, `formatQuestionTopic`, `BinnyMood`.
- Produces: `MASTERY_THRESHOLDS = { getting: 0.6, secure: 0.75 }`, `MasteryLevel`, `masteryLevel(r)`, `MASTERY_LABEL`, `masteryView(m)`, `practiceResultScreen(result, summary, subjectName)`, and the types `PracticeResultScreen`, `AnswerRowView`, `ResultPrimary`.

- [ ] **Step 1: Write the failing tests**

```ts
// web/tests/unit/practiceResultModel.test.ts
import { describe, expect, it } from "vitest"
import type { PracticeResult } from "@/lib/practiceTypes"
import type { PracticeSummary } from "@/lib/practiceRunTypes"
import {
  masteryLevel,
  masteryView,
  practiceResultScreen,
} from "@/portals/student/screens/practice/result/practiceResultModel"

function result(over: Partial<PracticeResult> = {}): PracticeResult {
  return {
    assignmentId: "a1",
    quizId: "z1",
    subjectCode: "0580",
    marked: true,
    submissionStatus: "marked",
    awardedMarks: 7,
    maximumMarks: 13,
    questions: [
      { questionRef: "q1", position: 1, topic: "Parallel vectors", totalMarks: 1, awardedMarks: 1, confidenceBand: "high", confidenceScore: 0.95, markerSource: "deterministic", needsTeacherReview: false },
      { questionRef: "q2", position: 2, topic: "Vector proof", totalMarks: 4, awardedMarks: 1, confidenceBand: "low", confidenceScore: 0.5, markerSource: "ai", needsTeacherReview: true },
      { questionRef: "q3", position: 3, topic: null, totalMarks: 2, awardedMarks: 0, confidenceBand: "low", confidenceScore: 1, markerSource: "blank", needsTeacherReview: false },
    ],
    ...over,
  }
}

function summary(over: Partial<PracticeSummary> = {}): PracticeSummary {
  return {
    assignmentId: "a1",
    subjectCode: "0580",
    marked: true,
    awardedMarks: 7,
    maximumMarks: 13,
    marksToWin: 9,
    marksBack: 7,
    bestCombo: 3,
    xpAwarded: 30,
    focusTopic: "Vectors",
    includedTopics: ["Vectors"],
    questionCount: 6,
    mastery: { topic: "Vectors", before: 0.41, after: 0.63 },
    nextTopic: { topic: "Algebra", marksLost: 7 },
    today: { practice: true, flashcards: false, paper: false },
    ...over,
  }
}

describe("mastery", () => {
  it("levels at 60% and 75%", () => {
    expect(masteryLevel(0.59)).toBe("work")
    expect(masteryLevel(0.6)).toBe("getting")
    expect(masteryLevel(0.75)).toBe("secure")
  })

  it("words the hint and aria label from before and after", () => {
    expect(masteryView({ topic: "Vectors", before: 0.41, after: 0.63 })).toEqual({
      beforePct: 41, afterPct: 63, level: "getting", label: "Getting there",
      hint: { lead: "Vectors is now ", strong: "Getting there", tail: ". 12% more and it's secure." },
      aria: "Vectors went from 41% to 63%, now Getting there",
    })
    expect(masteryView({ topic: "Vectors", before: null, after: 0.5 })?.hint).toEqual({ lead: "", strong: "", tail: "10% more and Vectors is getting there." })
    expect(masteryView({ topic: "Vectors", before: 0.7, after: 0.8 })?.hint).toEqual({ lead: "Vectors is ", strong: "Secure", tail: "." })
    expect(masteryView({ topic: "Vectors", before: null, after: 0.5 })?.aria).toBe("Vectors is at 50%, Work on")
    expect(masteryView(null)).toBeNull()
  })
})

describe("result screen", () => {
  it("not submitted and marking states come from the result alone", () => {
    expect(practiceResultScreen(result({ marked: false, submissionStatus: "in_progress", awardedMarks: null, maximumMarks: null, questions: [] }), undefined, "Mathematics").kind).toBe("not_submitted")
    expect(practiceResultScreen(result({ marked: false, submissionStatus: "submitted", awardedMarks: null, maximumMarks: null, questions: [] }), undefined, "Mathematics").kind).toBe("marking")
  })

  it("marked with a target: marks back hero, gains, mastery, rows and Next", () => {
    const view = practiceResultScreen(result(), summary(), "Mathematics")
    if (view.kind !== "marked") throw new Error("expected marked")
    expect(view.hero).toEqual({ title: "7 of 9 back!", sub: "You scored 7 of 13 on Vectors · best combo ×3", mood: "wink", awarded: 7, max: 13 })
    expect(view.gains).toEqual({ marks: { value: 7, label: "marks back" }, xp: 30, today: [1, 0, 0], todayLabel: "Today 1 of 3" })
    expect(view.mastery?.afterPct).toBe(63)
    expect(view.answers.map((r) => [r.position, r.title, r.mark, r.tone, r.sub])).toEqual([
      [1, "Parallel vectors", "1/1", "full", null],
      [2, "Vector proof", "1/4", "part", "Teacher will check this one"],
      [3, "Unknown topic", "0/2", "zero", null],
    ])
    expect(view.primary).toEqual({
      type: "create",
      label: "Next: Algebra · +7 marks",
      request: { subjectCode: "0580", count: 6, topics: ["Algebra"], weakTopicsOnly: false, difficultyBands: [], source: null },
    })
    expect(view.again).toEqual({
      label: "Try Vectors again",
      request: { subjectCode: "0580", count: 6, topics: ["Vectors"], weakTopicsOnly: false, difficultyBands: [], source: null },
    })
  })

  it("without a target, without next topic, and before the summary loads", () => {
    const noTarget = practiceResultScreen(result(), summary({ marksToWin: null, marksBack: null, nextTopic: null, xpAwarded: 0, bestCombo: 1 }), "Mathematics")
    if (noTarget.kind !== "marked") throw new Error("expected marked")
    expect(noTarget.hero.title).toBe("7 of 13 marks")
    expect(noTarget.hero.sub).toBe("You scored 7 of 13 on Vectors")
    expect(noTarget.gains?.marks).toEqual({ value: 7, label: "marks" })
    expect(noTarget.gains?.xp).toBeNull()
    expect(noTarget.primary).toEqual({ type: "plan", label: "See your study plan", to: "/student/plan/0580" })

    const zero = practiceResultScreen(result({ awardedMarks: 0 }), summary({ marksBack: 0 }), "Mathematics")
    if (zero.kind !== "marked") throw new Error("expected marked")
    expect(zero.hero.title).toBe("Round one done")
    expect(zero.hero.mood).toBe("open")

    const early = practiceResultScreen(result(), undefined, "Mathematics")
    if (early.kind !== "marked") throw new Error("expected marked")
    expect(early.gains).toBeNull()
    expect(early.mastery).toBeNull()
    expect(early.again).toBeNull()
    expect(early.hero.sub).toBe("You scored 7 of 13 on Mathematics")
  })
})
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd web && npx vitest run tests/unit/practiceResultModel.test.ts`
Expected: FAIL with an unresolved import.

- [ ] **Step 3: Write the result model**

```ts
// web/src/portals/student/screens/practice/result/practiceResultModel.ts
/*
 * L3 result screen decisions (mock frames ZF and DZ). The not-submitted and
 * marking split mirrors the old `practiceResultView` exactly (K37, K38), so
 * that function can be deleted from practiceData.ts.
 */
import { formatQuestionTopic } from "@/components/quiz/quizTakerData"
import type { BinnyMood } from "@/components/redesign"
import type { PracticeFilterSet, PracticeResult } from "@/lib/practiceTypes"
import type { PracticeMastery, PracticeSummary } from "@/lib/practiceRunTypes"

/* Mock grid: Work on 0–60, Getting there 60–75, Secure 75–100 (`.lv3t` 60fr 15fr 25fr).
   Must match F1's TopicState and L2's chips. See Needs user decision 8. */
export const MASTERY_THRESHOLDS = { getting: 0.6, secure: 0.75 } as const
export type MasteryLevel = "work" | "getting" | "secure"
export const MASTERY_LABEL: Record<MasteryLevel, string> = { work: "Work on", getting: "Getting there", secure: "Secure" }

export function masteryLevel(ratio: number): MasteryLevel {
  if (ratio >= MASTERY_THRESHOLDS.secure) return "secure"
  if (ratio >= MASTERY_THRESHOLDS.getting) return "getting"
  return "work"
}

export interface MasteryView {
  beforePct: number | null
  afterPct: number
  level: MasteryLevel
  label: string
  hint: { lead: string; strong: string; tail: string }
  aria: string
}

export function masteryView(m: PracticeMastery | null): MasteryView | null {
  if (!m) return null
  const topic = formatQuestionTopic(m.topic)
  const afterPct = Math.round(m.after * 100)
  const beforePct = m.before === null ? null : Math.round(m.before * 100)
  const level = masteryLevel(m.after)
  const label = MASTERY_LABEL[level]
  const hint =
    level === "secure"
      ? { lead: `${topic} is `, strong: "Secure", tail: "." }
      : level === "getting"
        ? { lead: `${topic} is now `, strong: "Getting there", tail: `. ${Math.ceil(MASTERY_THRESHOLDS.secure * 100 - afterPct)}% more and it's secure.` }
        : { lead: "", strong: "", tail: `${Math.ceil(MASTERY_THRESHOLDS.getting * 100 - afterPct)}% more and ${topic} is getting there.` }
  const aria = beforePct === null ? `${topic} is at ${afterPct}%, ${label}` : `${topic} went from ${beforePct}% to ${afterPct}%, now ${label}`
  return { beforePct, afterPct, level, label, hint, aria }
}

export interface AnswerRowView {
  questionRef: string
  position: number
  title: string
  sub: string | null
  mark: string
  tone: "full" | "part" | "zero"
}

export type ResultPrimary =
  | { type: "create"; label: string; request: PracticeFilterSet }
  | { type: "plan"; label: string; to: string }

export type PracticeResultScreen =
  | { kind: "not_submitted" }
  | { kind: "marking" }
  | {
      kind: "marked"
      hero: { title: string; sub: string; mood: BinnyMood; awarded: number; max: number }
      gains: { marks: { value: number; label: string }; xp: number | null; today: [number, number, number]; todayLabel: string } | null
      mastery: MasteryView | null
      answers: AnswerRowView[]
      primary: ResultPrimary
      again: { label: string; request: PracticeFilterSet } | null
    }

function setRequest(subjectCode: string, count: number, topics: string[]): PracticeFilterSet {
  return { subjectCode, count, topics, weakTopicsOnly: false, difficultyBands: [], source: null }
}

export function practiceResultScreen(
  result: PracticeResult,
  summary: PracticeSummary | undefined,
  subjectName: string,
): PracticeResultScreen {
  if (!result.marked || result.awardedMarks === null || result.maximumMarks === null) {
    return result.submissionStatus === "not_started" || result.submissionStatus === "in_progress"
      ? { kind: "not_submitted" }
      : { kind: "marking" }
  }
  const a = result.awardedMarks
  const m = result.maximumMarks
  const topicName = summary?.focusTopic ? formatQuestionTopic(summary.focusTopic) : subjectName
  const target = summary?.marksToWin ?? null
  const back = summary?.marksBack ?? null
  const ratio = m > 0 ? a / m : 0
  const mood: BinnyMood = a === 0 ? "open" : ratio >= 0.7 ? "happy" : ratio >= 0.4 ? "wink" : "open"
  const title = target !== null && back !== null ? (back > 0 ? `${back} of ${target} back!` : "Round one done") : `${a} of ${m} marks`
  const combo = summary && summary.bestCombo >= 2 ? ` · best combo ×${summary.bestCombo}` : ""

  const gains = summary
    ? (() => {
        const today: [number, number, number] = [summary.today.practice ? 1 : 0, summary.today.flashcards ? 1 : 0, summary.today.paper ? 1 : 0]
        return {
          marks: target !== null && back !== null ? { value: back, label: "marks back" } : { value: a, label: "marks" },
          xp: summary.xpAwarded > 0 ? summary.xpAwarded : null,
          today,
          todayLabel: `Today ${today.reduce((s, n) => s + n, 0)} of 3`,
        }
      })()
    : null

  const answers: AnswerRowView[] = result.questions.map((q) => ({
    questionRef: q.questionRef,
    position: q.position,
    title: formatQuestionTopic(q.topic),
    sub: q.needsTeacherReview ? "Teacher will check this one" : null,
    mark: `${q.awardedMarks}/${q.totalMarks}`,
    tone: q.awardedMarks >= q.totalMarks ? "full" : q.awardedMarks > 0 ? "part" : "zero",
  }))

  const count = summary?.questionCount ?? result.questions.length
  const primary: ResultPrimary = summary?.nextTopic
    ? {
        type: "create",
        label: `Next: ${formatQuestionTopic(summary.nextTopic.topic)} · +${summary.nextTopic.marksLost} marks`,
        request: setRequest(result.subjectCode, count, [summary.nextTopic.topic]),
      }
    : { type: "plan", label: "See your study plan", to: `/student/plan/${result.subjectCode}` }

  return {
    kind: "marked",
    hero: { title, sub: `You scored ${a} of ${m} on ${topicName}${combo}`, mood, awarded: a, max: m },
    gains,
    mastery: masteryView(summary?.mastery ?? null),
    answers,
    primary,
    again:
      summary && summary.includedTopics.length > 0
        ? { label: `Try ${topicName} again`, request: setRequest(result.subjectCode, count, summary.includedTopics) }
        : null,
  }
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd web && npx vitest run tests/unit/practiceResultModel.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git commit -S -m "feat(web): practice result view model" -- web/src/portals/student/screens/practice/result/practiceResultModel.ts web/tests/unit/practiceResultModel.test.ts
```

---

### Task 11: The run controller hook (autosave, check, poll, flag, submit)

**Files:**
- Create: `web/src/portals/student/screens/practice/run/usePracticeRunController.ts`

**Interfaces:**
- Consumes: Task 8 hooks, Task 9 reducer and selectors, `useSaveQuizAnswer` and `useSubmitQuiz` (`@/lib/hooks/usePlacementApi`), `useOnlineStatus` (`@/lib/online`), the `quizTakerData` cache helpers, and `studentSaveFailureMessage` (`@/lib/studentOutcome`).
- Produces: `usePracticeRunController(run: PracticeRun)`, which returns `{ state, current, kind, online, saveStatus, primary, reveal, onAnswer, onChoose, onPrimary, onNext, onSkip, onToggleFlag, onChallenge, openLeave, closeSheet, leave, goToBlank, finishAnyway, submitting }`.

This hook wires effects only. Every decision is in Task 9, which has the unit tests. The browser behaviour is proved by Task 16's Playwright spec. The node-only Vitest setup has no DOM to render hooks in.

- [ ] **Step 1: Write the hook**

```ts
// web/src/portals/student/screens/practice/run/usePracticeRunController.ts
/*
 * L3 run controller. The autosave keeps QuizTaker's contract point for point
 * (K18–K25). Each keystroke goes to local state and the dirty localStorage
 * cache. A 600 ms debounced save is serialised per question, marked clean
 * only if the cache is unchanged, retried on reconnect and after reload, and
 * flushed (blocking) before a check and before submit. QuizTaker itself is
 * not touched (placement still uses it). A shared hook is a follow-up.
 */
import { useCallback, useEffect, useReducer, useRef, useState } from "react"
import { useNavigate } from "react-router-dom"
import { useSaveQuizAnswer, useSubmitQuiz } from "@/lib/hooks/usePlacementApi"
import { useCheckQuestion, useFlagQuestion, usePracticeCheck } from "@/lib/hooks/usePracticeRunApi"
import { useOnlineStatus } from "@/lib/online"
import { studentSaveFailureMessage } from "@/lib/studentOutcome"
import { useToast } from "@/components/ui/toast"
import type { PracticeRun } from "@/lib/practiceRunTypes"
import {
  answerCacheKey,
  buildRetrySavePayload,
  dirtyQuestionRefs,
  isCacheEntryUnchanged,
  readCachedAnswers,
  refsToFlush,
  refsToRetry,
  writeCachedAnswers,
  type CachedAnswers,
  type LocalAnswer,
} from "@/components/quiz/quizTakerData"
import {
  CHECK_TIMEOUT_MS,
  answerKind,
  blankPositions,
  initialRunState,
  primaryAction,
  revealView,
  runReducer,
} from "./practiceRunModel"

type SaveStatus = "idle" | "saving" | "saved" | "error"

const FLUSH_FAILED =
  "We couldn't save your latest answers, so we haven't submitted yet. Check your connection and try again. Nothing you've written has been lost."

function safeStorage(): Storage | null {
  try {
    return window.localStorage
  } catch {
    return null
  }
}

export function usePracticeRunController(run: PracticeRun) {
  const id = run.assignmentId
  const navigate = useNavigate()
  const toast = useToast()
  const online = useOnlineStatus()
  const saveAnswer = useSaveQuizAnswer(id)
  const submitQuiz = useSubmitQuiz(id)
  const checkQuestion = useCheckQuestion(id)
  const flagQuestion = useFlagQuestion(id)

  const cacheKey = answerCacheKey(id)
  const answerCache = useRef<CachedAnswers>({})
  const [state, dispatch] = useReducer(runReducer, undefined, () => {
    const storage = safeStorage()
    answerCache.current = (storage && readCachedAnswers(storage, cacheKey)) ?? {}
    return initialRunState(run, answerCache.current)
  })
  const [saveStatus, setSaveStatus] = useState<Record<string, SaveStatus>>({})
  const [submitting, setSubmitting] = useState(false)

  const current = run.questions[state.index]
  const kind = current ? answerKind(current) : "structured"

  // ── Autosave (K18–K23) ───────────────────────────────────────────────
  const timers = useRef<Record<string, number>>({})
  const chains = useRef<Record<string, Promise<void>>>({})
  const busy = useRef<Set<string>>(new Set())
  const saveMutateAsync = saveAnswer.mutateAsync

  const persist = useCallback(
    (ref: string, entry: LocalAnswer, dirty: boolean) => {
      answerCache.current = { ...answerCache.current, [ref]: { ...entry, dirty } }
      const storage = safeStorage()
      if (storage) writeCachedAnswers(storage, cacheKey, answerCache.current)
    },
    [cacheKey],
  )

  const enqueueSave = useCallback(
    (ref: string): Promise<void> => {
      const runSave = async () => {
        const entry = answerCache.current[ref]
        if (!entry || !entry.dirty) return
        const sent: LocalAnswer = { answerText: entry.answerText, workingText: entry.workingText }
        setSaveStatus((s) => ({ ...s, [ref]: "saving" }))
        try {
          await saveMutateAsync({ questionRef: ref, body: buildRetrySavePayload(sent) })
        } catch {
          setSaveStatus((s) => ({ ...s, [ref]: "error" }))
          return
        }
        if (!isCacheEntryUnchanged(answerCache.current[ref], sent)) return
        persist(ref, sent, false)
        setSaveStatus((s) => ({ ...s, [ref]: "saved" }))
      }
      const prev = chains.current[ref] ?? Promise.resolve()
      const chained: Promise<void> = prev.then(runSave, runSave).then(() => {
        if (chains.current[ref] === chained) {
          delete chains.current[ref]
          busy.current.delete(ref)
        }
      })
      chains.current[ref] = chained
      busy.current.add(ref)
      return chained
    },
    [saveMutateAsync, persist],
  )

  useEffect(() => {
    if (!online) return
    for (const ref of refsToRetry(answerCache.current, busy.current)) void enqueueSave(ref)
  }, [online, enqueueSave])

  const onAnswer = (field: "answerText" | "workingText", value: string) => {
    if (!current) return
    const ref = current.questionRef
    const prev = state.answers[ref] ?? { answerText: null, workingText: null }
    const next = { ...prev, [field]: value }
    dispatch({ type: "answer", questionRef: ref, field, value })
    persist(ref, next, true)
    if (timers.current[ref]) window.clearTimeout(timers.current[ref])
    timers.current[ref] = window.setTimeout(() => {
      delete timers.current[ref]
      void enqueueSave(ref)
    }, 600)
  }

  const onChoose = (option: string) => onAnswer("answerText", option)

  async function flush(refs?: string[]): Promise<boolean> {
    const targets = refs ?? Object.keys(timers.current)
    for (const ref of targets) {
      if (timers.current[ref]) {
        window.clearTimeout(timers.current[ref])
        delete timers.current[ref]
      }
    }
    const pending = refs ?? refsToFlush(answerCache.current, busy.current)
    await Promise.all(pending.map((ref) => enqueueSave(ref)))
    const dirty = dirtyQuestionRefs(answerCache.current)
    return refs ? refs.every((r) => !dirty.includes(r)) : dirty.length === 0
  }

  // ── Check and poll ───────────────────────────────────────────────────
  const pendingRef =
    state.revealRef && state.checks[state.revealRef]?.status === "checking" ? state.revealRef : null
  const poll = usePracticeCheck(id, pendingRef)
  useEffect(() => {
    if (poll.data && poll.data.status !== "checking") dispatch({ type: "checkUpdated", check: poll.data })
  }, [poll.data])
  useEffect(() => {
    if (!pendingRef) return
    const t = window.setTimeout(() => dispatch({ type: "checkTimedOut", questionRef: pendingRef }), CHECK_TIMEOUT_MS)
    return () => window.clearTimeout(t)
  }, [pendingRef])

  async function onCheck() {
    if (!current) return
    const ref = current.questionRef
    const answer = state.answers[ref] ?? { answerText: null, workingText: null }
    // The check body carries the answer, so only this question's queue must drain first.
    await flush([ref]).catch(() => false)
    try {
      const check = await checkQuestion.mutateAsync({ questionRef: ref, body: buildRetrySavePayload(answer) })
      persist(ref, answer, false)
      dispatch({ type: "checkUpdated", check })
    } catch (err) {
      toast.show({ variant: "error", title: "Couldn't check this one", description: studentSaveFailureMessage(err) })
    }
  }

  // ── Navigation, finish and submit (K2, K22, K25, K28–K30) ────────────
  async function submit() {
    setSubmitting(true)
    dispatch({ type: "clearSubmitError" })
    const ok = await flush()
    if (!ok) {
      setSubmitting(false)
      dispatch({ type: "submitFailed", message: FLUSH_FAILED })
      return
    }
    try {
      await submitQuiz.mutateAsync()
      safeStorage()?.removeItem(cacheKey)
      navigate(`/student/practice/result/${id}`, { state: { justSubmitted: true } })
    } catch (err) {
      setSubmitting(false)
      dispatch({ type: "submitFailed", message: studentSaveFailureMessage(err) })
    }
  }

  function finish() {
    if (blankPositions(run, state).length > 0) dispatch({ type: "openSheet", sheet: "blank" })
    else void submit()
  }

  const primary = primaryAction(run, state, online)
  function onPrimary() {
    if (primary.disabled) return
    if (primary.kind === "check") void onCheck()
    else if (primary.kind === "next") dispatch({ type: "next" })
    else if (primary.kind === "finish") finish()
  }
  const onNext = () => (state.index === run.questions.length - 1 ? finish() : dispatch({ type: "next" }))

  function onToggleFlag(ref = current?.questionRef) {
    if (!ref) return
    const next = !state.flagged[ref]
    dispatch({ type: "flag", questionRef: ref, flagged: next })
    flagQuestion.mutate(
      { questionRef: ref, flagged: next },
      {
        onError: () => {
          dispatch({ type: "flag", questionRef: ref, flagged: !next })
          toast.show({ variant: "error", title: "Couldn't save the flag" })
        },
      },
    )
  }

  function onChallenge() {
    if (!current) return
    if (!state.flagged[current.questionRef]) onToggleFlag(current.questionRef)
    toast.show({ variant: "success", title: "Flagged. A teacher will look again." })
  }

  const reveal = state.revealRef
    ? revealView(state.checks[state.revealRef], run.questions.find((q) => q.questionRef === state.revealRef)?.questionType ?? "")
    : null

  return {
    state,
    current,
    kind,
    online,
    saveStatus: current ? (saveStatus[current.questionRef] ?? "idle") : "idle",
    primary,
    reveal,
    onAnswer,
    onChoose,
    onPrimary,
    onNext,
    onSkip: () => dispatch({ type: "skip" }),
    onGoTo: (index: number) => dispatch({ type: "goTo", index }),
    onToggleFlag,
    onChallenge,
    openLeave: () => dispatch({ type: "openSheet", sheet: "leave" }),
    closeSheet: () => dispatch({ type: "closeSheet" }),
    leave: () => navigate("/student"),
    goToBlank: () => {
      const first = blankPositions(run, state)[0]
      const index = run.questions.findIndex((q) => q.position === first)
      dispatch({ type: "goTo", index })
    },
    finishAnyway: () => void submit(),
    submitting,
  }
}

export type PracticeRunController = ReturnType<typeof usePracticeRunController>
```

Check `useToast()`'s method name and option shape in `web/src/components/ui/toast.tsx:44-75` before writing. Adapt the `toast.show({...})` calls to the real API (for example `toast({ title, variant })`) and keep the same copy.

- [ ] **Step 2: Type-check**

Run: `cd web && npx tsc -p tsconfig.app.json --noEmit`
Expected: no errors in `practice/run/`.

- [ ] **Step 3: Commit**

```bash
git commit -S -m "feat(web): practice run controller with autosave, check and submit" -- web/src/portals/student/screens/practice/run/usePracticeRunController.ts
```

---

## Screen tasks (designer agent)

Every screen task goes to the `designer` agent. Before any UI edit, it invokes the `impeccable` skill, reads `.claude/skills/impeccable/reference/craft-floor.md`, and reads the three taste memories named in the master plan. F1 kit imports come from `@/components/redesign`: `Binny`, `ComboChip`, `GoldRing`, `H2Row`, `HairRows`, `HairRow`, `GhostRows`. The rest of the kit comes from `@/components/ui/*`. Visual checks are the side-by-side shots in Task 17. Behaviour is covered by Task 9's and Task 10's unit tests and Task 16's Playwright spec.

### Task 12: Keyframes, the start screen and the route wrapper

**Files:**
- Create: `web/src/portals/student/screens/practice/run/practiceRun.css`
- Create: `web/src/portals/student/screens/practice/run/PracticeStart.tsx`
- Create: `web/src/portals/student/screens/practice/run/RunStates.tsx` (`RunSkeleton`, `RunError`, `OfflineBanner`)
- Rewrite: `web/src/portals/student/screens/practice/PracticeSet.tsx`
- Modify: `web/src/portals/student/index.tsx` (the `practice/set/:assignmentId` handle becomes `{ title: "Practice", skeleton: "page-header", immersive: true }`)

**Interfaces:**
- Consumes: Task 8 `usePracticeRun`, Task 9 `shouldShowStart`, `runRedirect`, `startView`, `runErrorCopy`, `EMPTY_SET_COPY`, `PRACTICE_HOME`, and `useSubjectName`.
- Produces: `PracticeStart({ run, subjectName, onStart, onPrint, onClose })`, `RunError({ copy, onRetry?, onBack })`, `RunSkeleton()`, `OfflineBanner()`, and the route component `PracticeSet`. Task 13 provides `PracticeRun({ run })`.

- [ ] **Step 1: Write the keyframes**

```css
/* web/src/portals/student/screens/practice/run/practiceRun.css
   Exact values from .impeccable/mocks/student-r2/pr.css. Motion only when allowed. */
@media (prefers-reduced-motion: no-preference) {
  .pr-rvl { animation: pr-rvup 0.45s var(--ease-out) both; }
  .pr-rvi { animation: pr-pop 0.5s var(--ease-out) 0.15s both; }
  .pr-dot { animation: pr-bd 1s infinite; }
  .pr-dot:nth-child(2) { animation-delay: 0.15s; }
  .pr-dot:nth-child(3) { animation-delay: 0.3s; }
  .pr-wbar { transition: width 0.5s var(--ease-out); }
  .pr-fill { animation: pr-fill 1s var(--ease-out) 0.2s both; }
  .pr-tile { transition: transform 0.15s var(--ease-out); }
  .pr-tile:active { transform: scale(0.97); }
}
@keyframes pr-rvup { from { transform: translateY(40%); opacity: 0.4; } }
@keyframes pr-pop { 0% { transform: scale(0.4); } 60% { transform: scale(1.15); } }
@keyframes pr-bd { 50% { transform: translateY(-5px); opacity: 0.5; } }
@keyframes pr-fill { from { width: var(--from); } }
```

- [ ] **Step 2: Write `RunStates.tsx`**

```tsx
// web/src/portals/student/screens/practice/run/RunStates.tsx
import { WifiSlash, X } from "@phosphor-icons/react"
import { Binny } from "@/components/redesign"
import { SkeletonBlock, SkeletonLine } from "@/components/ui/skeleton"
import type { RunErrorCopy } from "./practiceRunModel"

const iconBtn =
  "grid size-11 flex-none place-items-center rounded-[14px] bg-surface-container-high text-on-surface focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"

/** K6: the run skeleton (dots row, question lines, two field blocks, the button). */
export function RunSkeleton() {
  return (
    <div role="status" aria-label="Loading" className="mx-auto flex w-full max-w-[640px] flex-col gap-4 px-4 pt-4">
      <div className="flex items-center gap-3">
        <SkeletonBlock announce={false} className="size-11 rounded-[14px]" />
        <SkeletonLine announce={false} className="h-2 flex-1" />
        <SkeletonBlock announce={false} className="size-11 rounded-[14px]" />
      </div>
      <SkeletonLine announce={false} className="h-3" width="10rem" />
      <SkeletonBlock announce={false} className="h-16" />
      <SkeletonBlock announce={false} className="h-28 rounded-[16px]" />
      <SkeletonBlock announce={false} className="h-[54px] rounded-[18px]" />
    </div>
  )
}

/** ER frame. Also covers missing id, 403, 404 and an empty set (K7–K11). */
export function RunError({ copy, onRetry, onBack }: { copy: RunErrorCopy; onRetry?: () => void; onBack: () => void }) {
  return (
    <div className="mx-auto flex min-h-[70dvh] w-full max-w-[640px] flex-col px-4 pt-4">
      <div className="flex">
        <button type="button" aria-label="Close" onClick={onBack} className={iconBtn}>
          <X size={20} aria-hidden />
        </button>
      </div>
      <div className="flex flex-1 flex-col items-center justify-center gap-3 text-center">
        <Binny mood="sad" size={96} motion="none" aria-hidden />
        <h1 className="m-0 font-sans text-[22px] font-extrabold text-on-surface">{copy.title}</h1>
        <p className="m-0 max-w-[30ch] text-[14px] text-on-surface-variant">{copy.body}</p>
        {copy.retry && onRetry ? (
          <button type="button" onClick={onRetry} className="mt-2 min-h-[54px] w-full max-w-[300px] rounded-[18px] bg-primary px-7 font-sans text-[16px] font-bold text-on-primary">
            Try again
          </button>
        ) : null}
        <button type="button" onClick={onBack} className="min-h-11 px-3.5 font-sans text-[14px] font-semibold text-on-surface-variant">
          Back to Practice
        </button>
      </div>
    </div>
  )
}

/** OF frame banner (K27). */
export function OfflineBanner() {
  return (
    <div role="status" className="mx-[18px] mt-2 flex items-center gap-2 rounded-[12px] bg-tertiary-container px-3 py-2.5 font-sans text-[13.5px] font-semibold leading-[1.35] text-on-tertiary-container">
      <WifiSlash size={16} aria-hidden className="flex-none" />
      Offline. Your answer is saved here and checks when you're back.
    </div>
  )
}
```

- [ ] **Step 3: Write `PracticeStart.tsx` (frames PSF and PSS)**

```tsx
// web/src/portals/student/screens/practice/run/PracticeStart.tsx
import { useState } from "react"
import { Keyboard, Printer, X } from "@phosphor-icons/react"
import { cn } from "@/lib/utils"
import { Binny } from "@/components/redesign"
import type { PracticeRun } from "@/lib/practiceRunTypes"
import { startView } from "./practiceRunModel"
import "./practiceRun.css"

type Mode = "here" | "print"

export function PracticeStart({
  run,
  subjectName,
  onStart,
  onPrint,
  onClose,
}: {
  run: PracticeRun
  subjectName: string
  onStart: () => void
  onPrint: () => void
  onClose: () => void
}) {
  const [mode, setMode] = useState<Mode>("here")
  const view = startView(run, subjectName)
  const card = (m: Mode) =>
    cn(
      "grid justify-items-start gap-1 rounded-[18px] bg-surface-container-lowest px-3 py-3.5 text-start text-on-surface",
      "focus-visible:outline-[2.5px] focus-visible:outline-offset-[3px] focus-visible:outline-primary",
      mode === m ? "bg-primary-container shadow-[inset_0_0_0_2.5px_var(--md-primary)]" : "shadow-[inset_0_0_0_1.5px_var(--md-outline)]",
    )

  return (
    <div className="mx-auto flex min-h-[calc(100dvh-4rem)] w-full max-w-[640px] flex-col gap-3 bg-[linear-gradient(180deg,color-mix(in_oklch,var(--md-primary-container)_60%,var(--md-surface)),var(--md-surface)_55%)] px-5 pb-[26px] pt-4">
      <button type="button" aria-label="Close" onClick={onClose} className="grid size-11 place-items-center rounded-[14px] bg-primary-container text-primary">
        <X size={20} aria-hidden />
      </button>
      <div className="self-center">
        <Binny mood="happy" size={112} motion="idle" aria-hidden />
      </div>
      <h1 className="m-0 text-center font-display text-[34px] font-extrabold leading-[1.05] tracking-[-0.03em] text-primary">{view.title}</h1>
      <p className="m-0 text-center font-sans text-[14px] font-medium text-on-surface-variant">{view.sub}</p>
      {view.goal ? (
        <div className="flex items-center gap-3.5 px-1 py-3">
          <span className="min-w-16 text-center font-mono text-[30px] font-extrabold leading-none text-success-text">{view.goal.value}</span>
          <span className="grid">
            <b className="font-sans text-[15px] font-bold text-on-surface">{view.goal.title}</b>
            <span className="text-[13px] text-on-surface-variant">{view.goal.sub}</span>
          </span>
        </div>
      ) : null}
      {view.covers.length > 0 ? (
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="mr-1 font-sans text-[13px] font-semibold text-on-surface-variant">Covers</span>
          {view.covers.map((c) => (
            <span key={c} className="rounded-[10px] bg-primary-container px-2.5 py-[5px] font-sans text-[13px] font-semibold text-primary">{c}</span>
          ))}
        </div>
      ) : null}
      <div role="radiogroup" aria-label="How do you want to answer?" className="mt-auto grid grid-cols-2 gap-2.5">
        <button type="button" role="radio" aria-checked={mode === "here"} onClick={() => setMode("here")} className={card("here")}>
          <Keyboard size={20} aria-hidden className="mb-1 text-primary" />
          <b className="font-sans text-[15px] font-bold">Answer here</b>
          <span className="font-sans text-[12.5px] leading-[1.35] text-on-surface-variant">Type or tap. Checked after each one.</span>
        </button>
        <button type="button" role="radio" aria-checked={mode === "print"} onClick={() => setMode("print")} className={card("print")}>
          <Printer size={20} aria-hidden className="mb-1 text-primary" />
          <b className="font-sans text-[15px] font-bold">Print and scan</b>
          <span className="font-sans text-[12.5px] leading-[1.35] text-on-surface-variant">Solve on paper, scan to mark.</span>
        </button>
      </div>
      {mode === "here" ? (
        <button type="button" onClick={onStart} className="min-h-[50px] w-full rounded-[18px] bg-primary font-sans text-[15.5px] font-bold text-on-primary shadow-[0_14px_24px_-16px_oklch(0.3_0.07_242/0.7)]">
          Start
        </button>
      ) : (
        <div className="grid gap-2.5">
          <button type="button" onClick={onPrint} className="inline-flex min-h-[50px] w-full items-center justify-center gap-2 rounded-[18px] bg-primary font-sans text-[15.5px] font-bold text-on-primary">
            <Printer size={20} aria-hidden /> Print the questions
          </button>
          {/* "I've done it, scan" is held back until a practice-scan marking path exists (Needs user decision 3). */}
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 4: Rewrite `PracticeSet.tsx`**

```tsx
// web/src/portals/student/screens/practice/PracticeSet.tsx
/* L3 practice run route: start screen, then the run. Replaces the QuizTaker wrapper. */
import { useMemo, useState } from "react"
import { Navigate, useNavigate, useParams } from "react-router-dom"
import { usePracticeRun } from "@/lib/hooks/usePracticeRunApi"
import { useSubjectName } from "@/lib/hooks/useReferenceApi"
import { answerCacheKey, readCachedAnswers } from "@/components/quiz/quizTakerData"
import { PracticeStart } from "./run/PracticeStart"
import { PracticeRun } from "./run/PracticeRun"
import { RunError, RunSkeleton } from "./run/RunStates"
import { EMPTY_SET_COPY, PRACTICE_HOME, runErrorCopy, runRedirect, shouldShowStart } from "./run/practiceRunModel"

export function PracticeSet() {
  const navigate = useNavigate()
  const { assignmentId = "" } = useParams<{ assignmentId: string }>()
  const query = usePracticeRun(assignmentId)
  const subjectName = useSubjectName(query.data?.subjectCode ?? "")
  const [started, setStarted] = useState(false)
  const cached = useMemo(() => {
    try {
      return readCachedAnswers(window.localStorage, answerCacheKey(assignmentId))
    } catch {
      return null
    }
  }, [assignmentId])
  const back = () => navigate(PRACTICE_HOME)

  if (!assignmentId) {
    return <RunError copy={{ title: "We couldn't find this set", body: "Start a new one from the Practice tab.", retry: false }} onBack={back} />
  }
  if (query.isPending) return <RunSkeleton />
  if (query.isError) return <RunError copy={runErrorCopy(query.error)} onRetry={() => void query.refetch()} onBack={back} />

  const run = query.data
  if (runRedirect(run) === "result") return <Navigate to={`/student/practice/result/${assignmentId}`} replace />
  if (run.questions.length === 0) return <RunError copy={EMPTY_SET_COPY} onBack={back} />
  if (!started && shouldShowStart(run, cached)) {
    return (
      <>
        <h1 className="sr-only">{run.title}</h1>
        <PracticeStart
          run={run}
          subjectName={subjectName}
          onStart={() => setStarted(true)}
          onPrint={() => navigate(`/student/practice/print/${assignmentId}`)}
          onClose={() => navigate(-1)}
        />
      </>
    )
  }
  return <PracticeRun run={run} />
}
```

`PRACTICE_HOME` (`/student/practice`) is L4's Practice tab root. Until L4 merges, that path has no route. In that case change `PRACTICE_HOME` to `/student` in the model and note it in the PR (lane dependency).

- [ ] **Step 5: Mark the route immersive**

In `web/src/portals/student/index.tsx`, change the `practice/set/:assignmentId` entry's handle to `{ title: "Practice", skeleton: "page-header", immersive: true }`. This hides the native tab bar during the run (phone frames show none). The desktop rail stays, as in `DR`.

- [ ] **Step 6: Type-check and copy check**

Run: `cd web && npx tsc -p tsconfig.app.json --noEmit && npm run check:copy`
Expected: clean. `PracticeRun` comes from Task 13. If Task 13 has not landed yet, add a one-line stub export in `run/PracticeRun.tsx` and replace it in Task 13 within the same PR.

- [ ] **Step 7: Commit**

```bash
git commit -S -m "feat(web): practice start screen and run route wrapper" -- web/src/portals/student/screens/practice/run/practiceRun.css web/src/portals/student/screens/practice/run/PracticeStart.tsx web/src/portals/student/screens/practice/run/RunStates.tsx web/src/portals/student/screens/practice/PracticeSet.tsx web/src/portals/student/index.tsx
```

---

### Task 13: The run screen (header, question, footer, keys, offline)

**Files:**
- Create: `web/src/portals/student/screens/practice/run/RunHeader.tsx`
- Create: `web/src/portals/student/screens/practice/run/QuestionBody.tsx`
- Create: `web/src/portals/student/screens/practice/run/PracticeRun.tsx`

**Interfaces:**
- Consumes: Task 11 controller, Task 9 `progressDots`, `wonMeta`, `mcqTiles`, `keyAction`, and F1 `ComboChip`.
- Produces: `RunHeader({ run, ctl })`, `QuestionBody({ question, kind, answer, locked, onAnswer, onChoose, dim })`, `PracticeRun({ run })`.

- [ ] **Step 1: Write `RunHeader.tsx` (`.prtop` and `.prmeta`)**

```tsx
// web/src/portals/student/screens/practice/run/RunHeader.tsx
import { Flag, X } from "@phosphor-icons/react"
import { cn } from "@/lib/utils"
import { ComboChip } from "@/components/redesign"
import type { PracticeRun } from "@/lib/practiceRunTypes"
import { progressDots, wonMeta } from "./practiceRunModel"
import type { PracticeRunController } from "./usePracticeRunController"

const DOT: Record<string, string> = {
  ok: "bg-success-text",
  part: "bg-grade-c",
  no: "bg-error",
  now: "bg-primary shadow-[0_0_0_3px_var(--md-primary-container)]",
  todo: "bg-surface-container-highest",
}

export function RunHeader({ run, ctl }: { run: PracticeRun; ctl: PracticeRunController }) {
  const dots = progressDots(run, ctl.state)
  const won = wonMeta(run, ctl.state)
  const flagged = ctl.current ? !!ctl.state.flagged[ctl.current.questionRef] : false
  return (
    <>
      <div className="flex items-center gap-3 px-4 pb-1.5 pt-4">
        <button type="button" aria-label="Leave for now" onClick={ctl.openLeave} className="grid size-11 flex-none place-items-center rounded-[14px] bg-surface-container-high text-on-surface">
          <X size={20} aria-hidden />
        </button>
        <nav aria-label={dots[ctl.state.index]?.label} className="grid flex-1 auto-cols-fr grid-flow-col gap-1.5">
          {dots.map((d, i) => (
            <button
              key={run.questions[i].questionRef}
              type="button"
              aria-label={`Go to question ${i + 1}`}
              aria-current={i === ctl.state.index ? "step" : undefined}
              onClick={() => ctl.onGoTo(i)}
              className="grid min-h-11 items-center"
            >
              <i className={cn("block h-2 rounded-[4px]", DOT[d.tone])} />
            </button>
          ))}
        </nav>
        <button
          type="button"
          aria-label="Flag for review"
          aria-pressed={flagged}
          onClick={() => ctl.onToggleFlag()}
          className={cn("grid size-11 flex-none place-items-center rounded-[14px]", flagged ? "bg-primary-container text-primary" : "text-on-surface-variant")}
        >
          <Flag size={18} weight={flagged ? "fill" : "regular"} aria-hidden />
        </button>
      </div>
      <div className="flex items-center gap-2.5 px-[18px] pb-1 pt-1.5 font-sans text-[13px] font-medium text-on-surface-variant">
        <span>
          <b className="font-mono text-[15px] font-extrabold text-success-text">+{won.won}</b> {won.suffix}
        </span>
        <span className="h-1.5 flex-1 overflow-hidden rounded-[3px] bg-surface-container-high" aria-hidden>
          <i className="pr-wbar block h-full rounded-[3px] bg-success-text" style={{ width: `${won.pct * 100}%` }} />
        </span>
        <ComboChip count={ctl.state.combo} />
      </div>
    </>
  )
}
```

- [ ] **Step 2: Write `QuestionBody.tsx` (`.prq`, `.fld`, `.mcq`)**

```tsx
// web/src/portals/student/screens/practice/run/QuestionBody.tsx
import { Check } from "@phosphor-icons/react"
import { cn } from "@/lib/utils"
import type { AnswerInputKind, LocalAnswer } from "@/components/quiz/quizTakerData"
import type { PracticeRunQuestion } from "@/lib/practiceRunTypes"
import { mcqTiles } from "./practiceRunModel"

const field =
  "w-full resize-none rounded-[16px] border-0 bg-surface-container-lowest px-3.5 py-3 font-mono text-[16px] leading-[1.5] text-on-surface shadow-[inset_0_0_0_1.5px_var(--md-outline)] outline-none focus:shadow-[inset_0_0_0_2px_var(--md-primary)] disabled:opacity-70"

export function QuestionBody({
  question,
  kind,
  answer,
  locked,
  dim,
  saveStatus,
  onAnswer,
  onChoose,
}: {
  question: PracticeRunQuestion
  kind: AnswerInputKind
  answer: LocalAnswer
  locked: boolean
  dim: boolean
  saveStatus: "idle" | "saving" | "saved" | "error"
  onAnswer: (field: "answerText" | "workingText", value: string) => void
  onChoose: (option: string) => void
}) {
  return (
    <div className={cn("flex min-h-0 flex-1 flex-col gap-4 overflow-auto px-5 pb-3 pt-[18px]", dim && "opacity-40")}>
      <span className="font-sans text-[13px] font-semibold text-on-surface-variant">
        Question {question.position} · <span className="font-mono">{question.totalMarks}</span> mark{question.totalMarks === 1 ? "" : "s"}
      </span>
      <p className="m-0 whitespace-pre-line font-sans text-[19px] font-semibold leading-[1.5] text-on-surface [text-wrap:pretty]">{question.prompt}</p>
      {kind === "mcq" ? (
        <div role="radiogroup" aria-label="Choose an answer" className="grid grid-cols-2 gap-2.5">
          {mcqTiles(question.mcqOptions ?? []).map((t) => {
            const on = answer.answerText === t.option
            return (
              <button
                key={t.option}
                type="button"
                role="radio"
                aria-checked={on}
                disabled={locked}
                onClick={() => onChoose(t.option)}
                className={cn(
                  "pr-tile relative grid min-h-[84px] place-items-center rounded-[18px] bg-surface-container-lowest text-[20px] text-on-surface sidebar:min-h-[110px] sidebar:text-[24px]",
                  "focus-visible:outline-[2.5px] focus-visible:outline-offset-[3px] focus-visible:outline-primary",
                  on ? "bg-primary-container shadow-[inset_0_0_0_2.5px_var(--md-primary)]" : "shadow-[inset_0_0_0_1.5px_var(--md-outline)]",
                )}
              >
                <span className="absolute left-2.5 top-2 font-sans text-[12px] font-bold text-on-surface-variant">{t.letter}</span>
                <span className={t.body ? "font-mono text-[18px]" : "font-mono font-bold"}>{t.body ?? t.letter}</span>
              </button>
            )
          })}
        </div>
      ) : (
        <>
          {kind === "structured" ? (
            <label className="grid gap-1.5 font-sans text-[13px] font-semibold text-on-surface-variant">
              <span>Your working</span>
              <textarea rows={4} value={answer.workingText ?? ""} disabled={locked} onChange={(e) => onAnswer("workingText", e.target.value)} className={field} />
            </label>
          ) : null}
          <label className="grid gap-1.5 font-sans text-[13px] font-semibold text-on-surface-variant">
            <span>Your final answer</span>
            <input value={answer.answerText ?? ""} disabled={locked} onChange={(e) => onAnswer("answerText", e.target.value)} className={field} />
          </label>
        </>
      )}
      <SaveLine status={saveStatus} />
    </div>
  )
}

function SaveLine({ status }: { status: "idle" | "saving" | "saved" | "error" }) {
  if (status === "idle") return null
  if (status === "error") {
    return (
      <p role="status" className="m-0 self-end font-sans text-[12.5px] text-error">
        We couldn't save this answer. It's kept on this device, and we'll send it again before you submit.
      </p>
    )
  }
  return (
    <span role="status" className="inline-flex items-center gap-1.5 self-end font-sans text-[12.5px] font-medium text-success-text">
      {status === "saved" ? <Check size={14} weight="bold" aria-hidden /> : null}
      {status === "saving" ? "Saving…" : "Saved"}
    </span>
  )
}
```

- [ ] **Step 3: Write `PracticeRun.tsx` (QA, QB, OF and DR)**

```tsx
// web/src/portals/student/screens/practice/run/PracticeRun.tsx
import { useEffect } from "react"
import type { PracticeRun as Run } from "@/lib/practiceRunTypes"
import { Kbd } from "@/components/ui/kbd"
import { keyAction, mcqTiles } from "./practiceRunModel"
import { usePracticeRunController } from "./usePracticeRunController"
import { RunHeader } from "./RunHeader"
import { QuestionBody } from "./QuestionBody"
import { RevealSheet } from "./RevealSheet"
import { BlankSheet, LeaveSheet } from "./RunSheets"
import { OfflineBanner } from "./RunStates"
import "./practiceRun.css"

export function PracticeRun({ run }: { run: Run }) {
  const ctl = usePracticeRunController(run)
  const q = ctl.current
  const answer = q ? (ctl.state.answers[q.questionRef] ?? { answerText: null, workingText: null }) : { answerText: null, workingText: null }
  const check = q ? ctl.state.checks[q.questionRef] : undefined
  const locked = check?.status === "checked" || check?.status === "checking"
  const revealOpen = ctl.state.revealRef !== null

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const target = e.target as HTMLElement | null
      const action = keyAction(e.key, {
        kind: ctl.kind,
        optionCount: q?.mcqOptions?.length ?? 0,
        blocked: ctl.state.sheet !== null || e.metaKey || e.ctrlKey || e.altKey,
        inTextField: !!target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA"),
        inTextarea: target?.tagName === "TEXTAREA",
      })
      if (!action) return
      e.preventDefault()
      if (action.type === "primary") {
        if (revealOpen && ctl.reveal && ctl.reveal.kind !== "wait") ctl.onNext()
        else ctl.onPrimary()
      } else if (!locked && q) {
        ctl.onChoose(mcqTiles(q.mcqOptions ?? [])[action.index].option)
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [ctl, q, locked, revealOpen])

  if (!q) return null
  const p = ctl.primary
  return (
    <div className="relative mx-auto flex min-h-[calc(100dvh-4rem)] w-full max-w-[640px] flex-col sidebar:pt-3">
      <h1 className="sr-only">{run.title}</h1>
      <RunHeader run={run} ctl={ctl} />
      {!ctl.online ? <OfflineBanner /> : null}
      <QuestionBody
        question={q}
        kind={ctl.kind}
        answer={answer}
        locked={locked}
        dim={revealOpen}
        saveStatus={ctl.saveStatus}
        onAnswer={ctl.onAnswer}
        onChoose={ctl.onChoose}
      />
      {!revealOpen ? (
        <div className="grid gap-1 px-[18px] pb-[26px] pt-2.5">
          {ctl.state.submitError ? <p role="alert" className="m-0 text-center font-sans text-[13px] text-error">{ctl.state.submitError}</p> : null}
          <button
            type="button"
            onClick={ctl.onPrimary}
            disabled={p.disabled || ctl.submitting}
            aria-disabled={p.disabled || ctl.submitting}
            className="min-h-[50px] w-full rounded-[18px] bg-primary font-sans text-[15.5px] font-bold text-on-primary shadow-[0_14px_24px_-16px_oklch(0.3_0.07_242/0.7)] disabled:bg-surface-container-high disabled:text-on-surface-variant disabled:shadow-none"
          >
            {ctl.submitting ? "Submitting…" : p.label}
            <Kbd className="ml-2 hidden bg-[oklch(1_0_0/0.18)] sidebar:inline">Enter</Kbd>
          </button>
          {!ctl.online && p.kind === "waitOnline" ? (
            <button type="button" onClick={ctl.onSkip} className="min-h-11 justify-self-center px-3.5 font-sans text-[14px] font-semibold text-on-surface-variant">
              Skip to next question
            </button>
          ) : null}
          {ctl.kind === "mcq" ? (
            <p className="m-0 mt-2.5 hidden text-center font-sans text-[13px] text-on-surface-variant sidebar:block">
              Press <Kbd>A</Kbd>–<Kbd>D</Kbd> to choose
            </p>
          ) : null}
        </div>
      ) : null}
      {ctl.reveal ? (
        <RevealSheet
          view={ctl.reveal}
          isLast={ctl.state.index === run.questions.length - 1}
          onNext={ctl.onNext}
          onRetry={ctl.onPrimary}
          onChallenge={ctl.onChallenge}
        />
      ) : null}
      <LeaveSheet open={ctl.state.sheet === "leave"} position={q.position} onKeepGoing={ctl.closeSheet} onLeave={ctl.leave} />
      <BlankSheet open={ctl.state.sheet === "blank"} run={run} state={ctl.state} onGoTo={ctl.goToBlank} onFinish={ctl.finishAnyway} onClose={ctl.closeSheet} submitting={ctl.submitting} />
    </div>
  )
}
```

`sidebar:` is the shell's 1280px breakpoint. Confirm the variant name in `web/src/index.css` (`@custom-variant`), and use the existing desktop variant if it is named differently.

- [ ] **Step 4: Type-check**

Run: `cd web && npx tsc -p tsconfig.app.json --noEmit && npm run check:copy && npm run check:native`
Expected: clean once Task 14's `RevealSheet` and `RunSheets` exist. Tasks 13 and 14 may share one commit if the reviewer prefers.

- [ ] **Step 5: Commit**

```bash
git commit -S -m "feat(web): practice run screen with header, questions and keys" -- web/src/portals/student/screens/practice/run/RunHeader.tsx web/src/portals/student/screens/practice/run/QuestionBody.tsx web/src/portals/student/screens/practice/run/PracticeRun.tsx
```

---

### Task 14: Reveal sheets, the leave sheet and the blank sheet

**Files:**
- Create: `web/src/portals/student/screens/practice/run/RevealSheet.tsx`
- Create: `web/src/portals/student/screens/practice/run/RunSheets.tsx`

**Interfaces:**
- Consumes: Task 9 `RevealView`, `blankPositions`, `blankSheetCopy`, `leaveCopy`, F1 `Binny`, and the `Sheet` primitives.
- Produces: `RevealSheet({ view, isLast, onNext, onRetry, onChallenge })`, `LeaveSheet({ open, position, onKeepGoing, onLeave })`, `BlankSheet({ open, run, state, onGoTo, onFinish, onClose, submitting })`.

- [ ] **Step 1: Write `RevealSheet.tsx` (RA, RB, RC, plus zero and failed)**

```tsx
// web/src/portals/student/screens/practice/run/RevealSheet.tsx
/* Non-modal: role=status over the dimmed question, as in the mock. No scrim, and focus stays in the page. */
import { useEffect, useRef } from "react"
import { Check, Fire } from "@phosphor-icons/react"
import { cn } from "@/lib/utils"
import { Binny } from "@/components/redesign"
import type { RevealView } from "./practiceRunModel"

const SHEET_BG: Record<RevealView["kind"], string> = {
  ok: "bg-success-container",
  part: "bg-[color-mix(in_oklch,var(--grade-c)_10%,var(--md-surface-container-lowest))]",
  zero: "bg-surface-container-lowest",
  wait: "bg-surface-container-lowest",
  failed: "bg-surface-container-lowest",
}

export function RevealSheet({
  view,
  isLast,
  onNext,
  onRetry,
  onChallenge,
}: {
  view: RevealView
  isLast: boolean
  onNext: () => void
  onRetry: () => void
  onChallenge: () => void
}) {
  const nextRef = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    if (view.kind !== "wait") nextRef.current?.focus({ preventScroll: true })
  }, [view.kind])

  return (
    <div role="status" aria-live="polite" className={cn("pr-rvl absolute inset-x-0 bottom-0 z-10 grid gap-3.5 rounded-t-[28px] px-5 pb-[26px] pt-[22px] shadow-[0_-12px_30px_-12px_oklch(0.3_0.05_240/0.25)]", SHEET_BG[view.kind])}>
      {view.kind === "wait" ? (
        <>
          <div className="flex items-center gap-3">
            <Binny mood="thinking" size={64} motion="idle" aria-hidden />
            <p className="m-0 font-sans text-[15px] font-medium leading-[1.4] text-on-surface">
              <b>{view.title}</b>
              <br />
              <span className="text-[14px] text-on-surface-variant">{view.sub}</span>
            </p>
          </div>
          <div className="flex justify-center gap-1.5" aria-hidden>
            {[0, 1, 2].map((i) => (
              <i key={i} className="pr-dot size-2 rounded-full bg-inverse-primary" />
            ))}
          </div>
        </>
      ) : (
        <>
          <div className="flex items-center gap-3">
            {view.kind === "ok" ? (
              <span className="pr-rvi grid size-11 place-items-center rounded-full bg-success-text text-white"><Check size={22} weight="bold" aria-hidden /></span>
            ) : view.badge ? (
              <span className="pr-rvi grid size-11 place-items-center rounded-full bg-[color-mix(in_oklch,var(--grade-c)_70%,black)] font-mono text-[14px] font-extrabold text-white">{view.badge}</span>
            ) : null}
            <b className="flex-1 font-sans text-[22px] font-extrabold text-on-surface">{view.title}</b>
            {view.marks ? <span className={cn("font-mono text-[18px] font-extrabold", view.kind === "ok" ? "text-success-text" : "text-grade-c-shell")}>{view.marks}</span> : null}
          </div>
          {view.sub ? <p className="m-0 font-sans text-[14px] text-on-surface-variant">{view.sub}</p> : null}
          {view.comboLine && view.mood ? (
            <div className="flex items-center gap-3">
              <Binny mood={view.mood} size={56} motion="pop" aria-hidden />
              <p className="m-0 font-sans text-[15px] font-medium text-on-surface">
                <b>{view.comboLine}</b> <Fire size={16} weight="fill" aria-hidden className="inline align-[-2px] text-tertiary" /> Combo ×{view.comboLine.split(" ")[0]}
              </p>
            </div>
          ) : null}
          {view.points.length > 0 ? (
            <ul className="m-0 grid list-none gap-2 p-0 font-sans text-[15px] font-medium text-on-surface">
              {view.points.map((pt) => (
                <li key={pt.text} className="flex items-center gap-2.5">
                  {pt.verdict === "awarded" ? (
                    <Check size={16} weight="bold" aria-label="Met" className="flex-none text-success-text" />
                  ) : (
                    <span aria-label="Missed" className="size-4 flex-none rounded-full shadow-[inset_0_0_0_2px_var(--md-error)]" />
                  )}
                  {pt.note ?? pt.text}
                </li>
              ))}
            </ul>
          ) : null}
          {view.answerLine ? <p className="m-0 font-sans text-[15px] font-semibold text-on-surface">{view.answerLine}</p> : null}
          {view.reviewLine ? <p className="m-0 font-sans text-[12.5px] font-medium text-grade-c-shell">{view.reviewLine}</p> : null}
          {view.kind === "failed" ? (
            <div className="grid gap-1">
              <button type="button" onClick={onRetry} className="min-h-[50px] w-full rounded-[18px] bg-primary font-sans text-[15.5px] font-bold text-on-primary">Try again</button>
              <button ref={nextRef} type="button" onClick={onNext} className="min-h-11 justify-self-center px-3.5 font-sans text-[14px] font-semibold text-on-surface-variant">Check it later</button>
            </div>
          ) : (
            <button ref={nextRef} type="button" onClick={onNext} className="min-h-[50px] w-full rounded-[18px] bg-primary font-sans text-[15.5px] font-bold text-on-primary">
              {isLast ? "See my result" : "Next question"}
            </button>
          )}
          {view.showChallenge ? (
            <button type="button" onClick={onChallenge} className="min-h-11 justify-self-center px-3.5 font-sans text-[14px] font-semibold text-on-surface-variant">
              Think this is wrong?
            </button>
          ) : null}
        </>
      )}
    </div>
  )
}
```

Small fix to note in the PR: the mock's combo line reads "3 in a row! Combo ×3". The `split(" ")[0]` above pulls the count from `comboLine`. The designer may pass `combo` as a number prop instead. That is a cleaner equivalent, as long as the copy stays the same.

- [ ] **Step 2: Write `RunSheets.tsx` (LV and SU)**

```tsx
// web/src/portals/student/screens/practice/run/RunSheets.tsx
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet"
import type { PracticeRun } from "@/lib/practiceRunTypes"
import { blankPositions, blankSheetCopy, leaveCopy, type RunState } from "./practiceRunModel"

const primaryBtn = "min-h-[50px] w-full rounded-[18px] bg-primary font-sans text-[15.5px] font-bold text-on-primary disabled:opacity-60"
const quietBtn = "min-h-11 justify-self-center px-3.5 font-sans text-[14px] font-semibold text-on-surface-variant"
const sheetBody = "grid gap-3.5 rounded-t-[28px] px-5 pb-[26px] pt-[22px]"

export function LeaveSheet({ open, position, onKeepGoing, onLeave }: { open: boolean; position: number; onKeepGoing: () => void; onLeave: () => void }) {
  return (
    <Sheet open={open} onOpenChange={(o) => !o && onKeepGoing()}>
      <SheetContent side="bottom" showCloseButton={false} className={sheetBody}>
        <SheetTitle className="m-0 font-sans text-[22px] font-extrabold text-on-surface">Leave for now?</SheetTitle>
        <SheetDescription className="m-0 font-sans text-[14px] leading-[1.4] text-on-surface-variant">{leaveCopy(position)}</SheetDescription>
        <button type="button" onClick={onKeepGoing} className={primaryBtn} autoFocus>Keep going</button>
        <button type="button" onClick={onLeave} className={quietBtn}>Leave for now</button>
      </SheetContent>
    </Sheet>
  )
}

export function BlankSheet({
  open, run, state, onGoTo, onFinish, onClose, submitting,
}: {
  open: boolean
  run: PracticeRun
  state: RunState
  onGoTo: () => void
  onFinish: () => void
  onClose: () => void
  submitting: boolean
}) {
  const positions = blankPositions(run, state)
  if (positions.length === 0) return null
  const copy = blankSheetCopy(positions)
  return (
    <Sheet open={open} onOpenChange={(o) => !o && onClose()}>
      <SheetContent side="bottom" showCloseButton={false} className={sheetBody}>
        <SheetTitle className="m-0 font-sans text-[22px] font-extrabold text-on-surface">{copy.title}</SheetTitle>
        <SheetDescription className="m-0 font-sans text-[14px] leading-[1.4] text-on-surface-variant">{copy.body}</SheetDescription>
        <button type="button" onClick={onGoTo} className={primaryBtn} autoFocus>{copy.go}</button>
        <button type="button" onClick={onFinish} disabled={submitting} className={quietBtn}>
          {submitting ? "Submitting…" : "Finish anyway"}
        </button>
      </SheetContent>
    </Sheet>
  )
}
```

- [ ] **Step 3: Type-check and run the model tests**

Run: `cd web && npx tsc -p tsconfig.app.json --noEmit && npx vitest run tests/unit/practiceRunModel.test.ts && npm run check:copy`
Expected: clean.

- [ ] **Step 4: Commit**

```bash
git commit -S -m "feat(web): practice reveal, leave and blank sheets" -- web/src/portals/student/screens/practice/run/RevealSheet.tsx web/src/portals/student/screens/practice/run/RunSheets.tsx
```

---

### Task 15: The result screen

**Files:**
- Create: `web/src/portals/student/screens/practice/result/MasteryBar.tsx`, `ResultGains.tsx`, `AnswerRows.tsx`, `AnswerSheet.tsx`, `ResultStates.tsx`
- Rewrite: `web/src/portals/student/screens/practice/PracticeResult.tsx`

**Interfaces:**
- Consumes: `usePracticeResult` (existing), Task 8 `usePracticeSummary` and `usePracticeRun` (for the answer sheet), Task 10 `practiceResultScreen`, `useCreatePractice` (existing, L4's hook, unchanged), and F1 `Binny`, `GoldRing`, `H2Row`, `HairRows`, `HairRow`, `GhostRows`.
- Produces: the rewritten `PracticeResult` route component.

- [ ] **Step 1: Write the parts**

```tsx
// web/src/portals/student/screens/practice/result/MasteryBar.tsx  (.lvl3)
import type { MasteryView } from "./practiceResultModel"

export function MasteryBar({ view }: { view: MasteryView }) {
  return (
    <div className="grid gap-2">
      <div className="grid grid-cols-[60fr_15fr_25fr] whitespace-nowrap font-sans text-[12px] font-semibold text-on-surface-variant">
        <span>Work on</span><span>Getting there</span><span className="text-end">Secure</span>
      </div>
      <div role="img" aria-label={view.aria} className="relative h-3.5 rounded-[7px] bg-[linear-gradient(90deg,var(--md-error-container)_0_60%,var(--md-surface-container-high)_60%_75%,var(--md-primary-container)_75%)]">
        <i
          className="pr-fill absolute inset-y-0 left-0 rounded-[7px] bg-success-text opacity-85"
          style={{ width: `${view.afterPct}%`, ["--from" as string]: `${view.beforePct ?? view.afterPct}%` }}
        />
        {view.beforePct !== null ? <b aria-hidden className="absolute -top-[3px] h-5 w-0.5 bg-on-surface opacity-35" style={{ left: `${view.beforePct}%` }} /> : null}
      </div>
      <p className="m-0 font-sans text-[14px] leading-[1.4] text-on-surface-variant">
        {view.hint.lead}
        {view.hint.strong ? <b className="text-on-surface">{view.hint.strong}</b> : null}
        {view.hint.tail}
      </p>
    </div>
  )
}
```

```tsx
// web/src/portals/student/screens/practice/result/ResultGains.tsx  (.gain3)
import { CountUp } from "@/components/ui/celebration"
import { GoldRing } from "@/components/redesign"

export function ResultGains({
  gains, justSubmitted,
}: {
  gains: { marks: { value: number; label: string }; xp: number | null; today: [number, number, number]; todayLabel: string }
  justSubmitted: boolean
}) {
  const cells = gains.xp === null ? "grid-cols-2" : "grid-cols-3"
  return (
    <div className={`grid ${cells} text-center`}>
      <span className="grid justify-items-center gap-0.5">
        <b className="font-mono text-[24px] font-extrabold text-success-text">+{justSubmitted ? <CountUp value={gains.marks.value} from={0} /> : gains.marks.value}</b>
        <small className="font-sans text-[12.5px] font-medium text-on-surface-variant">{gains.marks.label}</small>
      </span>
      {gains.xp !== null ? (
        <span className="grid justify-items-center gap-0.5">
          <b className="font-mono text-[24px] font-extrabold text-primary">+{gains.xp}</b>
          <small className="font-sans text-[12.5px] font-medium text-on-surface-variant">XP</small>
        </span>
      ) : null}
      <span className="grid justify-items-center gap-0.5">
        <GoldRing parts={gains.today} size={32} label={gains.todayLabel} />
        <small className="font-sans text-[12.5px] font-medium text-on-surface-variant">{gains.todayLabel}</small>
      </span>
    </div>
  )
}
```

```tsx
// web/src/portals/student/screens/practice/result/AnswerRows.tsx  (.qr2 rows)
import { cn } from "@/lib/utils"
import { H2Row, HairRow, HairRows } from "@/components/redesign"
import type { AnswerRowView } from "./practiceResultModel"

const MARK: Record<AnswerRowView["tone"], string> = {
  full: "bg-success-container text-success-text",
  part: "bg-[color-mix(in_oklch,var(--grade-c)_16%,var(--md-surface-container-lowest))] text-grade-c-shell",
  zero: "bg-error-container text-on-error-container",
}

export function AnswerRows({ rows, onOpen }: { rows: AnswerRowView[]; onOpen: (ref: string) => void }) {
  if (rows.length === 0) {
    return <p className="m-0 font-sans text-[14px] text-on-surface-variant">No questions in this set.</p>
  }
  return (
    <section className="grid">
      <H2Row title="Your answers" />
      <HairRows aria-label="Your answers">
        {rows.map((r) => (
          <HairRow
            key={r.questionRef}
            leading={<span className="w-[34px] font-mono text-[13px] font-bold text-on-surface-variant">Q{r.position}</span>}
            title={r.title}
            sub={r.sub ? <span className="text-grade-c-shell">{r.sub}</span> : undefined}
            trailing={<span className={cn("rounded-[8px] px-2 py-[3px] font-mono text-[14px] font-bold", MARK[r.tone])}>{r.mark}</span>}
            onClick={() => onOpen(r.questionRef)}
          />
        ))}
      </HairRows>
    </section>
  )
}
```

```tsx
// web/src/portals/student/screens/practice/result/AnswerSheet.tsx
/* A tapped answer row ("Practice answer: Qn" in the mock). It shows the prompt,
   what the student wrote, and the stored check's points, from GET .../run. */
import { Check } from "@phosphor-icons/react"
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet"
import { usePracticeRun } from "@/lib/hooks/usePracticeRunApi"

export function AnswerSheet({ assignmentId, questionRef, onClose }: { assignmentId: string; questionRef: string | null; onClose: () => void }) {
  const run = usePracticeRun(questionRef ? assignmentId : "")
  const q = run.data?.questions.find((x) => x.questionRef === questionRef)
  return (
    <Sheet open={questionRef !== null} onOpenChange={(o) => !o && onClose()}>
      <SheetContent side="bottom" className="grid max-h-[85dvh] gap-3 overflow-auto rounded-t-[28px] px-5 pb-[26px] pt-[22px]">
        <SheetTitle className="m-0 font-sans text-[18px] font-extrabold text-on-surface">Question {q?.position ?? ""}</SheetTitle>
        {q ? (
          <>
            <p className="m-0 whitespace-pre-line font-sans text-[16px] font-semibold leading-[1.5] text-on-surface">{q.prompt}</p>
            {q.workingText ? <pre className="m-0 whitespace-pre-wrap font-mono text-[14px] text-on-surface-variant">{q.workingText}</pre> : null}
            <p className="m-0 font-mono text-[15px] text-on-surface">{q.answerText ?? "No answer"}</p>
            {q.check?.points.length ? (
              <ul className="m-0 grid list-none gap-2 p-0 font-sans text-[15px] text-on-surface">
                {q.check.points.map((pt) => (
                  <li key={pt.text} className="flex items-center gap-2.5">
                    {pt.verdict === "awarded" ? <Check size={16} weight="bold" aria-label="Met" className="text-success-text" /> : <span aria-label="Missed" className="size-4 rounded-full shadow-[inset_0_0_0_2px_var(--md-error)]" />}
                    {pt.note ?? pt.text}
                  </li>
                ))}
              </ul>
            ) : null}
          </>
        ) : (
          <p className="m-0 font-sans text-[14px] text-on-surface-variant">Loading…</p>
        )}
      </SheetContent>
    </Sheet>
  )
}
```

```tsx
// web/src/portals/student/screens/practice/result/ResultStates.tsx  (K35–K38)
import { Binny, GhostRows } from "@/components/redesign"
import { ProgressBar } from "@/components/ui/progress-bar"
import { SkeletonBlock } from "@/components/ui/skeleton"

const quiet = "min-h-11 px-3.5 font-sans text-[14px] font-semibold text-on-surface-variant"
const primary = "min-h-[50px] w-full max-w-[300px] rounded-[18px] bg-primary font-sans text-[15.5px] font-bold text-on-primary"

export function ResultSkeleton() {
  return (
    <div role="status" aria-label="Loading" className="mx-auto grid w-full max-w-[640px] gap-4 px-5 pt-6">
      <SkeletonBlock announce={false} className="mx-auto size-[110px] rounded-full" />
      <SkeletonBlock announce={false} className="mx-auto h-9 w-48" />
      <GhostRows rows={5} withLeading />
    </div>
  )
}

export function ResultMessage({ title, body, action, onAction, back, onBack }: { title: string; body: string; action?: string; onAction?: () => void; back: string; onBack: () => void }) {
  return (
    <div className="mx-auto flex min-h-[60dvh] w-full max-w-[640px] flex-col items-center justify-center gap-3 px-5 text-center">
      <Binny mood="open" size={96} motion="none" aria-hidden />
      <h1 className="m-0 font-sans text-[22px] font-extrabold text-on-surface">{title}</h1>
      <p className="m-0 max-w-[32ch] font-sans text-[14px] text-on-surface-variant">{body}</p>
      {action && onAction ? <button type="button" onClick={onAction} className={primary}>{action}</button> : null}
      <button type="button" onClick={onBack} className={quiet}>{back}</button>
    </div>
  )
}

export function ResultMarking({ onLater }: { onLater: () => void }) {
  return (
    <div className="mx-auto flex min-h-[60dvh] w-full max-w-[640px] flex-col items-center justify-center gap-4 px-5 text-center">
      <Binny mood="thinking" size={96} motion="idle" aria-hidden />
      <h1 className="m-0 font-sans text-[22px] font-extrabold text-on-surface">Adding up your marks</h1>
      <p className="m-0 font-sans text-[14px] text-on-surface-variant">This page updates on its own.</p>
      <div className="w-full max-w-[300px]"><ProgressBar indeterminate ariaLabel="Marking your practice set" /></div>
      <button type="button" onClick={onLater} className={quiet}>Come back to this later</button>
    </div>
  )
}
```

- [ ] **Step 2: Rewrite `PracticeResult.tsx` (frames ZF and DZ)**

```tsx
// web/src/portals/student/screens/practice/PracticeResult.tsx
/* L3 result screen. Every decision is in practiceResultModel.ts. */
import { useState } from "react"
import { useLocation, useNavigate, useParams } from "react-router-dom"
import { X } from "@phosphor-icons/react"
import { Binny } from "@/components/redesign"
import { CountUp } from "@/components/ui/celebration"
import { useToast } from "@/components/ui/toast"
import { useCreatePractice, usePracticeResult } from "@/lib/hooks/usePracticeApi"
import { usePracticeSummary } from "@/lib/hooks/usePracticeRunApi"
import { useSubjectName } from "@/lib/hooks/useReferenceApi"
import { studentLoadFailureMessage } from "@/lib/studentOutcome"
import type { PracticeFilterSet } from "@/lib/practiceTypes"
import { practiceResultScreen } from "./result/practiceResultModel"
import { MasteryBar } from "./result/MasteryBar"
import { ResultGains } from "./result/ResultGains"
import { AnswerRows } from "./result/AnswerRows"
import { AnswerSheet } from "./result/AnswerSheet"
import { ResultMarking, ResultMessage, ResultSkeleton } from "./result/ResultStates"
import "./run/practiceRun.css"

function isJustSubmitted(state: unknown): boolean {
  return typeof state === "object" && state !== null && (state as { justSubmitted?: unknown }).justSubmitted === true
}

export function PracticeResult() {
  const navigate = useNavigate()
  const location = useLocation()
  const toast = useToast()
  const justSubmitted = isJustSubmitted(location.state)
  const { assignmentId = "" } = useParams<{ assignmentId: string }>()
  const query = usePracticeResult(assignmentId)
  const summary = usePracticeSummary(assignmentId, query.data?.marked === true)
  const subjectName = useSubjectName(query.data?.subjectCode ?? "")
  const create = useCreatePractice()
  const [openRef, setOpenRef] = useState<string | null>(null)

  if (!assignmentId) {
    return <ResultMessage title="No practice set selected" body="This link is missing which practice set to show." back="Back to dashboard" onBack={() => navigate("/student")} />
  }
  if (query.isPending) return <ResultSkeleton />
  if (query.isError) {
    return <ResultMessage title="Couldn't load this practice set" body={studentLoadFailureMessage(query.error)} action="Try again" onAction={() => void query.refetch()} back="Back to dashboard" onBack={() => navigate("/student")} />
  }

  const view = practiceResultScreen(query.data, summary.data, subjectName)
  if (view.kind === "not_submitted") {
    return <ResultMessage title="This set isn't finished" body={`Finish your ${subjectName} practice set to see how you did.`} action="Continue the set" onAction={() => navigate(`/student/practice/set/${assignmentId}`)} back="Back to dashboard" onBack={() => navigate("/student")} />
  }
  if (view.kind === "marking") return <ResultMarking onLater={() => navigate("/student")} />

  function startSet(request: PracticeFilterSet) {
    create.mutate(request, {
      onSuccess: (created) => navigate(`/student/practice/set/${created.assignmentId}`),
      onError: () => {
        toast.show({ variant: "error", title: "Couldn't make the set" })
        navigate(`/student/practice/${request.subjectCode}`)
      },
    })
  }

  return (
    <div className="mx-auto flex w-full max-w-[640px] flex-col gap-[18px] bg-[linear-gradient(180deg,var(--md-success-container),var(--md-surface)_45%)] px-5 pb-[26px] pt-4 sidebar:bg-none sidebar:px-0 sidebar:pt-6">
      <button type="button" aria-label="Close" onClick={() => navigate("/student")} className="grid size-11 place-items-center rounded-[14px] bg-primary-container text-primary">
        <X size={20} aria-hidden />
      </button>
      <div className="grid justify-items-center gap-1.5">
        <span className="sidebar:hidden"><Binny mood={view.hero.mood} size={110} motion="hop" aria-hidden /></span>
        <span className="hidden sidebar:block"><Binny mood={view.hero.mood} size={96} motion="hop" aria-hidden /></span>
        <h1 className="m-0 text-center font-display text-[34px] font-extrabold leading-[1.05] tracking-[-0.03em] text-primary">{view.hero.title}</h1>
        <p className="m-0 text-center font-sans text-[14px] font-medium text-on-surface-variant">
          You scored <span className="font-mono">{justSubmitted ? <CountUp value={view.hero.awarded} from={0} /> : view.hero.awarded}</span> of <span className="font-mono">{view.hero.max}</span>
          {view.hero.sub.slice(view.hero.sub.indexOf(" on "))}
        </p>
      </div>
      {view.gains ? <ResultGains gains={view.gains} justSubmitted={justSubmitted} /> : null}
      {view.mastery ? <MasteryBar view={view.mastery} /> : null}
      <AnswerRows rows={view.answers} onOpen={setOpenRef} />
      <button
        type="button"
        disabled={create.isPending}
        onClick={() => (view.primary.type === "create" ? startSet(view.primary.request) : navigate(view.primary.to))}
        className="min-h-[50px] w-full rounded-[18px] bg-primary font-sans text-[15.5px] font-bold text-on-primary shadow-[0_14px_24px_-16px_oklch(0.3_0.07_242/0.7)] disabled:opacity-60"
      >
        {view.primary.label}
      </button>
      {view.again ? (
        <button type="button" onClick={() => startSet(view.again!.request)} className="min-h-11 self-center px-3.5 font-sans text-[14px] font-semibold text-on-surface-variant">
          {view.again.label}
        </button>
      ) : null}
      <AnswerSheet assignmentId={assignmentId} questionRef={openRef} onClose={() => setOpenRef(null)} />
    </div>
  )
}
```

The hero line keeps K34 and K39: the awarded number is in Mono and counts up only when `justSubmitted`. The `.slice(indexOf(" on "))` reuses the model's sub text after the numbers. If the designer prefers, split `hero.sub` into `{ topic, combo }` in the model and update Task 10's test to match.

- [ ] **Step 3: Type-check and run the unit tests**

Run: `cd web && npx tsc -p tsconfig.app.json --noEmit && npx vitest run tests/unit/practiceResultModel.test.ts && npm run check:copy`
Expected: clean.

- [ ] **Step 4: Commit**

```bash
git commit -S -m "feat(web): practice result screen" -- web/src/portals/student/screens/practice/PracticeResult.tsx web/src/portals/student/screens/practice/result/MasteryBar.tsx web/src/portals/student/screens/practice/result/ResultGains.tsx web/src/portals/student/screens/practice/result/AnswerRows.tsx web/src/portals/student/screens/practice/result/AnswerSheet.tsx web/src/portals/student/screens/practice/result/ResultStates.tsx
```

---

## Tests

### Task 16: Playwright happy paths (run and result)

**Files:**
- Create: `web/e2e/practice-run.spec.ts`

**Interfaces:**
- Consumes: `injectSession`, `readSeed`, `watchConsole` (`web/e2e/seed.ts`, `console-errors.ts`), and the seed's `practice.students.active.unsubmittedAssignmentId` and `.markedAssignmentId`.

- [ ] **Step 1: Write the spec**

```ts
// web/e2e/practice-run.spec.ts
import { test, expect, type Page } from "@playwright/test"
import { watchConsole } from "./console-errors"
import { injectSession, readSeed, type SeedAccount } from "./seed"

/*
 * L3 happy paths. The run: start screen, answer, check, reveal, leave sheet.
 * The check endpoint is stubbed with page.route, so CI never makes a model
 * call (the marker path is covered by pytest with a stubbed correct_paper).
 * The result: a real marked set from the seed.
 */

async function asStudent(page: Page, account: SeedAccount) {
  await injectSession(page, { accessToken: account.accessToken, userId: account.userId, role: "student" })
}

test("practice run · start, answer, check, reveal, leave", async ({ page }) => {
  const seed = readSeed()
  const errors = watchConsole(page)
  const student = seed.practice.students.active
  await asStudent(page, student)

  await page.route("**/api/student/practice/*/questions/*/check", async (route) => {
    if (route.request().method() !== "POST") return route.continue()
    const ref = route.request().url().split("/questions/")[1].split("/")[0]
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        questionRef: decodeURIComponent(ref), status: "checked", awardedMarks: 1, maximumMarks: 1,
        points: [], correctOption: null, feedback: null, needsTeacherReview: false, error: null,
        combo: 1, bestCombo: 1, wonMarks: 1,
      }),
    })
  })

  await page.goto(`/student/practice/set/${student.unsubmittedAssignmentId}`)

  const start = page.getByRole("button", { name: "Start" })
  if (await start.isVisible({ timeout: 15_000 }).catch(() => false)) {
    await expect(page.getByRole("radio", { name: /Answer here/ })).toHaveAttribute("aria-checked", "true")
    await start.click()
  }

  await expect(page.getByText(/^Question \d+ · \d+ marks?$/)).toBeVisible({ timeout: 15_000 })
  const choices = page.getByRole("radiogroup", { name: "Choose an answer" })
  if (await choices.isVisible().catch(() => false)) {
    await choices.getByRole("radio").first().click()
  } else {
    await page.getByLabel("Your final answer").fill("42")
  }
  await page.getByRole("button", { name: /^Check/ }).click()
  await expect(page.getByText("Spot on!")).toBeVisible()

  await page.getByRole("button", { name: "Leave for now" }).first().click()
  await expect(page.getByText("Leave for now?")).toBeVisible()
  await page.getByRole("button", { name: "Leave for now" }).last().click()
  await expect(page).toHaveURL(/\/student$/)

  expect(errors, JSON.stringify(errors, null, 2)).toEqual([])
})

test("practice result · a marked set shows the hero, answers and a next step", async ({ page }) => {
  const seed = readSeed()
  const errors = watchConsole(page)
  const student = seed.practice.students.active
  await asStudent(page, student)

  await page.goto(`/student/practice/result/${student.markedAssignmentId}`)
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible({ timeout: 15_000 })
  await expect(page.getByText(/You scored \d+ of \d+/)).toBeVisible()
  await expect(page.getByRole("list", { name: "Your answers" })).toBeVisible()
  await expect(page.getByRole("button", { name: /^(Next: |See your study plan)/ })).toBeVisible()

  expect(errors, JSON.stringify(errors, null, 2)).toEqual([])
})
```

The leave-sheet step relies on both buttons being named "Leave for now": the header X (`aria-label`) and the sheet's link. That is why it uses `.first()` and `.last()`. If F1's `HairRows` does not render a `<ul>` with the passed `aria-label`, assert on the `H2Row` heading "Your answers" instead.

- [ ] **Step 2: Run it (only this spec)**

Run: `cd web && npx playwright test e2e/practice-run.spec.ts`
Expected: PASS against the local e2e stack. If the stack is not available locally, record that in the PR, and CI runs it.

- [ ] **Step 3: Commit**

```bash
git commit -S -m "test(e2e): practice run and result happy paths" -- web/e2e/practice-run.spec.ts
```

---

## Final tasks

### Task 17: Side-by-side fidelity screenshots, drift fixes, `/impeccable polish`

**Files:**
- Create: `reports/redesign/l03/` (screenshots, gitignored if `reports/` is, so attach them to the PR instead)

- [ ] **Step 1: Serve the mock.** Run `cd .impeccable/mocks/student-r2 && python -m http.server 8765`, then open `http://localhost:8765/practice-final.html`.
- [ ] **Step 2: Capture each frame against its app state at 390 and 1280.** Use Playwright (`page.setViewportSize`) or the chrome-devtools MCP. Frame pairs: PSF/PSS ↔ `/student/practice/set/:unsubmitted` (Start, then tap "Print and scan"); QA, QB, RA, RB, RC, LV, OF, SU, ER ↔ the run (drive OF with `context.setOffline(true)`, RC with a delayed `page.route` that answers 202 and then `checked`, ER with a route that answers 500); ZF/DZ ↔ `/student/practice/result/:marked`. Save the pairs as `<frame>-<width>-mock.png` and `<frame>-<width>-app.png`.
- [ ] **Step 3: Fix visible drift** in spacing, size, colour and type, using the token map. List every intentional difference in the PR's "Changes from the mock" section.
- [ ] **Step 4: Run `/impeccable polish`** on `practice/run/*`, `practice/result/*`, `PracticeSet.tsx` and `PracticeResult.tsx`. Apply its fixes.
- [ ] **Step 5: Re-run** `cd web && npx tsc -p tsconfig.app.json --noEmit && npx vitest run tests/unit/practiceRunModel.test.ts tests/unit/practiceResultModel.test.ts tests/unit/practiceRunApi.test.ts && npm run check:copy && npm run check:native`.
- [ ] **Step 6: Commit** the polish changes, listing the touched paths explicitly: `git commit -S -m "fix(web): practice run fidelity and polish" -- <paths>`.

### Task 18: Keep-list check and deleting the old code

**Files:**
- Modify: `web/src/portals/student/screens/practice/practiceData.ts` (the named edit: delete `PracticeMarkState`, `PracticeResultView`, `practiceResultView`, `practiceMarkState`)
- Modify: `web/tests/unit/practice.test.ts` (delete the `practiceResultView` and `practiceMarkState` describe blocks and their imports)
- Do not touch `web/src/components/quiz/QuizTaker.tsx`. Its docstring still names `PracticeSet.tsx` as a caller. That is stale but harmless, so list it in the PR as a follow-up.

- [ ] **Step 1: Confirm nothing else uses the four names**

Run: `cd web && grep -rn "practiceResultView\|practiceMarkState\|PracticeResultView\|PracticeMarkState" src tests`
Expected: hits only in `practiceData.ts` and `tests/unit/practice.test.ts`.

- [ ] **Step 2: Post the named edit to L4**, then make it. Delete only those four exports and the now-unused `PracticeResult` type import if nothing else in the file needs it.
- [ ] **Step 3: Delete the two describe blocks** in `web/tests/unit/practice.test.ts`.
- [ ] **Step 4: Run** `cd web && npx vitest run tests/unit/practice.test.ts tests/unit/quizTaker.test.ts && npx tsc -p tsconfig.app.json --noEmit`. Expected: PASS.
- [ ] **Step 5: Walk the keep-list** (K1–K48) in the running app and the tests. Tick each item in the PR body, with the test or screenshot that proves it.
- [ ] **Step 6: Refresh the graph:** `graphify update .`
- [ ] **Step 7: Commit:** `git commit -S -m "refactor(web): drop the old practice result helpers" -- web/src/portals/student/screens/practice/practiceData.ts web/tests/unit/practice.test.ts`

### Task 19: Gate sweep, push and PR to develop

- [ ] **Step 1: Derive the gate list from `.github/workflows/ci.yml`** (memory "Derive gate lists from ci.yml"). Run every gate on the touched files only. This includes source-scanning lint tests (`ls tests | grep -i lint`), `check:copy` and `check:native`. Do not run the full suite.
- [ ] **Step 2: Run `PYTHONPATH=$PWD pre-commit run --files <every touched file>`.** The ruff hook autofixes, so re-stage and re-run until clean, and confirm `git diff` is empty before the push.
- [ ] **Step 3: Rebase on `develop`.** If another migration landed meanwhile, re-point `0055`'s `down_revision` to the new head, rename the file and revision if needed, and update both migration tests' head assertions.
- [ ] **Step 4: Push and open the PR:** `git push -u origin redesign/l03-practice-run`, then `gh pr create --base develop --title "feat: practice run, start and result (redesign L3)"`. The body contains: the keep-list ticks, the frame table with screenshot pairs, "Changes from the mock", the migration note (approval needed before any shared-DB run), cost notes (one marker call per typed check, none at submit for checked answers, `practice_check_cost` logs), and the Needs user decision answers.
- [ ] **Step 5: Hand off** for the Opus review, then fixes, green CI and the merge (master plan workflow).

---

## Self-review notes

- Spec coverage: one question at a time (Tasks 3, 7, 9, 13), MCQ instant (Task 7, inline `perform_check`), typed through the existing marker (Task 3), combo (Tasks 2, 3, 13), XP (Task 6, result), level (Task 10 mastery bar, plus Needs user decision 2), autosave (Task 11), resume (Tasks 2, 3, 9), flags (Tasks 3, 5, 13), reveal sheets (Task 14), leave, offline, blank and error states (Tasks 12–14), result (Task 15), and the start choice (Task 12).
- Names checked across tasks: `build_quiz_mark_scheme`, `PracticeCheckRow.failed` → DTO `error`, `practiceRunKeys`, `usePracticeRunController` return keys (`onGoTo` is used by `RunHeader`), `RevealView` fields, `MasteryView.hint` shape.

## Needs user decision

Each item has a recommendation. None of them blocks the start of the work.

1. **Migration and a model file under `lemely/db/models/`.** The master plan lets only L1, L6, L9, L11 and L12 touch models. L3 needs one new table (`practice_question_states`, Task 1) to store checks for resume and reuse at submit. **Recommend: approve the exception.** It is additive, has a downgrade, and adds one new file plus two lines in `__init__.py`.
2. **F1 `LevelBar` (XP level) is not in the mock.** The approved result shows a topic mastery bar (Work on → Getting there → Secure) and "+XP", but no XP level bar. **Recommend: build the mock's mastery bar lane-locally (`MasteryBar`) and not render `LevelBar` here.** If you want the XP level too, it would be a small row under the gains.
3. **"I've done it, scan" has no marking path.** No flow marks a scanned practice set against its questions. **Recommend: ship "Print the questions" only, and hide the scan button until L6/L12 add practice scans.** The alternative is to route it to the normal upload, which would not mark against this set.
4. **Flags now mean "a teacher should look".** In the check-per-question run, a flag no longer helps the student come back to a question, so flagged questions go to the teacher review queue at submit (Task 5). **Recommend: yes.**
5. **"Think this is wrong?"** There is no challenge flow for practice. **Recommend: it flags the question (same as 4) and shows "Flagged. A teacher will look again."**
6. **Dropped live features.** These are the elapsed timer chip (practice has no time limit), swipe navigation, and Previous/Next. They are replaced by tappable progress dots and check-then-next. **Recommend: drop them.**
7. **Copy for states the mock lacks:**
   - The no-marks reveal: "No marks this time", with "The answer is C" for MCQ.
   - A failed check: "Couldn't check this one" / "It gets marked when you finish." with "Try again" and "Check it later".
   - The result marking state: "Adding up your marks".
   - The not-finished result: "This set isn't finished".
   - A zero-back hero: "Round one done".

   **Recommend: approve as written.**
8. **One source for the mastery thresholds** (60% and 75%). L2's topic chips and F1's `TopicState` need the same numbers. **Recommend: F1 exports `MASTERY_THRESHOLDS`, and L3 imports it once available.**
9. **Two offline banners.** The shell's global `OfflineBanner` and the run's own banner would both show. **Recommend: F1 hides the global banner on `immersive` routes.**
10. **Result buttons.** "Next: Algebra · +7 marks" replaces the live "See your study plan" and "Back to dashboard". The study plan becomes the primary button only when there is no next topic, and close goes to Home. **Recommend: approve.**
11. **The shortfall note** ("fewer than you asked for") stays on L4's builder. The start screen shows only the real question count. **Recommend: approve.**

