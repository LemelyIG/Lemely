# L10 Flashcards Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the student flashcard screens (`web/src/portals/student/screens/flashcards/*`) with the approved `cards-final.html` design. That means decks due first and grouped by subject, a new-deck sheet, deck detail with card editing, deck rename and delete, a swipe review with combo and interval labels, "All caught up", every state, and a desktop list with a side panel. Extend the flashcard backend to support it, with a deck generation status.

**Architecture:** The backend extends the existing `FlashcardService` (`lemely/db/flashcard_repo.py`) and router (`lemely/web/routers/flashcards.py`). Additions: mastery counts, marks lost, rename, weak topics, a deck/forecast/interval-aware due session, XP in the review response, and generation that runs in the background with a status on the deck. The status needs one additive migration. The frontend gets typed API functions (`web/src/lib/flashcardApi.ts`), rewritten TanStack Query hooks, and four pure view-model modules that hold every decision. Thin screens compose the F1 kit (`web/src/components/redesign`) with a few flashcard-only parts.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, pytest (throwaway Postgres per test); React 19, react-router 7, TanStack Query 5, Tailwind 4, Radix Sheet, phosphor icons, Vitest (node env, no jsdom), Playwright.

**Spec:** `docs/superpowers/specs/2026-11-14-redesign-implementation-design.md` §Wave 3 item 10. **Master plan:** `docs/superpowers/plans/2026-11-15-redesign-00-master.md`. **Mock:** `.impeccable/mocks/student-r2/cards-final.html` with `fc.js`, `fc.css`, `t.js`, `t.css`, `pr.css`, `sp.css`, `base.css`.

## Global Constraints

Inherits the master plan's Global Constraints unchanged. They are not repeated here, and every task's requirements include them.

Lane-specific constraints:
- Branch `redesign/l10-flashcards`, cut from `develop` after F1 merges, in its own worktree. Every command below runs from that worktree's root, written `$WT`.
- Python runs as `PYTHONPATH=$WT /home/sico/Code/Lemely/.venv/bin/python -m pytest …`. The venv is shared across worktrees, so `PYTHONPATH` must be pinned.
- Web commands run from `$WT/web`: `npx vitest run <files>`, `npx tsc -b --noEmit`, `npx oxlint <files>`, `npm run check:copy`, `npm run check:native`.
- **Owned files.** The lane owns everything under `web/src/portals/student/screens/flashcards/`, plus:
  - `web/src/lib/flashcardTypes.ts`, `flashcardApi.ts` (new), `flashcardSession.ts`, `flashcardSwipe.ts` and `hooks/useFlashcardApi.ts`
  - `lemely/web/routers/flashcards.py`, `lemely/web/schemas_flashcards.py` and `lemely/db/flashcard_repo.py`
  - the migration `lemely/db/migrations/versions/0055_flashcard_generation.py`
  - the flashcard tests
- **Narrow edits to shared files, and only these:**
  - `lemely/db/models/flashcards.py`: four columns and one enum. This is a master-plan exception; see Needs user decision 1.
  - `web/src/portals/student/index.tsx`: the flashcard route entries.
  - `web/src/portals/student/data.ts`: one regex arm in `currentSubjectCode` and the flashcard crumb arms.
  - `tests/test_authz_matrix_complete.py`: four route rows.
  - `web/tests/unit/gestureWiring.test.ts` and `capabilityWiring.test.ts`: the source paths they scan.
- Migrations live in `lemely/db/migrations/versions/` (the master plan's `alembic/versions/*` means this folder). Before merge, rebase `down_revision` onto the `develop` head. **Do not run the migration against any shared database without the user's approval.** Tests run it on throwaway databases only.
- Model cost: generation stays one Gemini call per deck, with `count` bounded 1–50 and `task_tag="flashcard_generation"`. `lemely/io/gemini.py` already records a `CallRecord` with USD for every call. No new model calls.
- Honesty rules kept from P4.6/P4.9:
  - an AI card stays `source="ai"` for life, and every card surface marks it
  - `generatedCount` is never padded
  - "nothing due" says when
  - `totalDue` ignores `limit`
  - another student's deck is a 404
- Copy: Binny lines are 2–4 words, with no eyebrow labels. Numbers are Mono. Gold appears only on the combo chip and the completed ring segments. Run `/humanizer` on sheet and dialog copy before the polish task.
- Binny appears once per screen: decks hero, empty shelf, couldn't load, writing (phone), and the review done screen. None on the deck detail, the review card or the sheets.

---

## File structure

Backend:

| File | Change | Responsibility |
|---|---|---|
| `lemely/db/models/flashcards.py` | modify | `DeckGenerationStatus` enum and four deck columns |
| `lemely/db/migrations/versions/0055_flashcard_generation.py` | create | additive columns, check constraint, downgrade |
| `lemely/db/flashcard_repo.py` | modify | mastery counts, marks lost, rename, weak topics, weakness topic pick, due filters, forecast, interval preview, async generation |
| `lemely/web/schemas_flashcards.py` | modify | new DTO fields and DTOs |
| `lemely/web/routers/flashcards.py` | modify | `PATCH /decks/{id}`, `GET /weak-topics`, 202 generate, `GET/POST …/generation`, `deck_id` on `/due`, `xpAwarded` |
| `tests/test_migration_flashcard_generation.py` | create | migration chain, shape, round trip |
| `tests/test_flashcard_repo.py` | modify | service tests |
| `tests/test_web_flashcards.py` | modify | route tests |
| `tests/test_authz_matrix_complete.py` | modify | four new routes |

Frontend data:

| File | Change | Responsibility |
|---|---|---|
| `web/src/lib/flashcardTypes.ts` | modify | wire types |
| `web/src/lib/flashcardApi.ts` | create | URL builders, query keys, typed fetchers |
| `web/src/lib/hooks/useFlashcardApi.ts` | rewrite | hooks, invalidation, generation polling |
| `web/src/lib/flashcardSession.ts` | extend | combo, best combo, knew-it, XP, retry-all |
| `web/src/lib/flashcardSwipe.ts` | extend | `swipeVisual` for stamp and tilt |
| `web/src/portals/student/screens/flashcards/flashcardsView.ts` | create | decks screen model |
| `.../flashcards/deckView.ts` | create | deck detail and writing model |
| `.../flashcards/newDeckView.ts` | create | new-deck sheet model and request builders |
| `.../flashcards/reviewView.ts` | create | review and done model |
| `web/tests/unit/flashcardApi.test.ts`, `flashcardsView.test.ts`, `deckView.test.ts`, `newDeckView.test.ts`, `reviewView.test.ts` | create | Vitest |
| `web/tests/unit/flashcardSession.test.ts`, `flashcardSwipe.test.ts` | modify | Vitest |

Screens (all under `web/src/portals/student/screens/flashcards/`):

| File | Responsibility |
|---|---|
| `flashcards.css` | keyframes only: `fc-flip`, `fc-rise`, `fc-out-left`, `fc-out-right` |
| `parts/SubjectDot.tsx`, `parts/MasteryBar.tsx`, `parts/OriginTag.tsx`, `parts/DueCount.tsx`, `parts/DeckRow.tsx`, `parts/CountStepper.tsx`, `parts/FcSheet.tsx`, `parts/AiMark.tsx` | small presentational parts |
| `FlashcardsScreen.tsx` | routes `flashcards` and `flashcards/:subjectCode`: header, hero, groups, states, desktop panel |
| `DecksStates.tsx` | FL, FE, FZ, and the FS extras |
| `NewDeckSheet.tsx` | FN and FGX |
| `WritingState.tsx` | FG |
| `DeckBody.tsx` | the deck detail body, shared by the phone route and the desktop panel |
| `DeckScreen.tsx` | route `flashcards/deck/:deckId` (phone and tablet) |
| `DeckMenu.tsx`, `RenameDeckSheet.tsx`, `DeleteDeckSheet.tsx`, `CardSheet.tsx` | deck options, FX, FC, add card |
| `ReviewScreen.tsx` | route `flashcards/review`: RF0/RF1/RF2, FR, FRD |
| `ReviewCard.tsx` | the swipe stack (flip, stamp, fly out) |
| `ReviewDone.tsx` | RD |

Deleted at the end: `FlashcardDecks.tsx`, `FlashcardReview.tsx`, `flashcardData.ts`, `web/tests/unit/flashcards.test.ts`.

---

## Keep-list (every live feature, state and rule, with where it lives today)

The final task ticks every row in the PR body. "→" says where it goes.

**Decks screen** (`FlashcardDecks.tsx`, `flashcardData.ts`)

| # | Live behaviour | Source | → New home |
|---|---|---|---|
| K1 | Decks for one subject (`useFlashcardDecks(subjectCode)`) | FlashcardDecks.tsx:418 | `flashcards/:subjectCode` still filters; `flashcards` shows all subjects (Task 10) |
| K2 | Due count + "Review due cards" scoped to the subject | :519-535 | hero `Review N cards` → `flashcards/review?subject=` (Task 10) |
| K3 | "Nothing due today" says when (`nextDueMessage`), with distinct copy when no cards exist | :537-543, flashcardData.ts:84-98 | hero "Nothing due" + `comingBackLine` (Task 6) |
| K4 | Due check pending / due check failed lines | :513-518 | hero sub "Checking…"; hero sub "Couldn't check what's due" (Task 6) |
| K5 | Three new-deck modes: manual, topic, weakness | :71-75, :551-568 | NewDeckSheet options (Tasks 8, 11) |
| K6 | Manual deck: title + optional topic; origin stays `manual` with a topic; blank title → "<Subject> deck"; blank topic → null | flashcardData.ts:45-58 | `manualDeckRequest` moved to `newDeckView.ts` (Task 8) |
| K7 | Topic mode needs a topic; submit disabled without one | :578-585, :660 | `buildNewDeckRequest` → `invalid` disables submit (Task 8) |
| K8 | Weakness mode: topic comes from recorded weaknesses, never typed | :586-591 | chips list only recorded weak topics; server validates (Tasks 2, 8) |
| K9 | Card count 1–50 | :603-611, schemas_flashcards.py:56 | `CountStepper` 1–50, default 12 (Tasks 8, 9) |
| K10 | 409 refusal message per reason (`no_weaknesses`) | :616-626, flashcardData.ts:136-151 | `newDeckErrorMessage` + disabled weakness option (Task 8) |
| K11 | Generated outcome uses `generatedCount`; shortfall named | :628-643, flashcardData.ts:166-178 | `generationOutcome` toast + deck detail line (Task 7) |
| K12 | Generic create failure message | :645-650 | `newDeckErrorMessage` default (Task 8) |
| K13 | Pending label and disabled submit | :657-668 | `submitLabel(..., pending)` (Task 8) |
| K14 | Delete deck asks first; pending; error | :674-678, :714-732 | `DeleteDeckSheet` (FX) (Task 12) |
| K15 | Long-press a deck opens its menu | :315-411 | `DeckRow` long-press → `DeckMenu` (Tasks 9, 12) |
| K16 | Empty "No decks yet" | :680-685 | FZ empty shelf (Task 10) |
| K17 | Grouped by topic | :487, :687-711 | grouped by subject per spec; topic name becomes the deck title (Task 6) |
| K18 | Deck row: origin label + card count + due count | :77-81, :359-362 | `DeckRow` origin tag, "N cards", due count (Tasks 6, 9) |
| K19 | Every card shows its source (AI vs yours) | :122-124 | `AiMark` on AI card rows and the review card (Needs user decision 4) |
| K20 | Per-card due date | :125-127 | dropped from rows; the mastery legend replaces it (listed in PR) |
| K21 | Edit card: front/back required, Saving…, error | :129-166 | `CardSheet` edit (FC) (Task 12) |
| K22 | Delete card asks first; pending; error | :171-215 | `CardSheet` confirm step (Task 12) |
| K23 | Add card: required fields, Adding…, error | :259-295 | `CardSheet` add (Task 12) |
| K24 | Empty deck "No cards in this deck yet" | :249-250 | DeckBody empty-cards line + Add card (Task 12) |
| K25 | Deck load skeleton / error | :235, :242-245 | DeckBody skeleton / error with Try again (Task 12) |
| K26 | Decks load skeleton / error | :474-484 | FL / FE (Task 10) |
| K27 | No rename (no endpoint) | :303-309 | rename added: `PATCH /decks/{id}` + `RenameDeckSheet` (Tasks 2, 4, 12) |

**Review** (`FlashcardReview.tsx`, `flashcardSession.ts`, `flashcardSwipe.ts`)

| # | Live behaviour | Source | → New home |
|---|---|---|---|
| R1 | Snapshot the due cards once; refetches never reshuffle | :113-127 | same snapshot pattern in ReviewScreen (Task 13) |
| R2 | Swipe: right reveals; after reveal left = again, right = good | :149-166, flashcardSwipe.ts:35-48 | unchanged rule + `swipeVisual` stamps (Tasks 7, 13) |
| R3 | Optimistic grading: index advances before the request | :172-191 | kept; source test still pins it (Task 13) |
| R4 | Retry 3 with backoff | useFlashcardApi.ts:213-214 | kept in the hook (Task 5) |
| R5 | Failed grades listed with Retry, in session and at the end | :80-103, :193-218, :340, :429 | FR banner "N ratings not saved yet · Retry" + on RD (Tasks 7, 13) |
| R6 | One success haptic at the finish | :223-229 | kept (Task 13) |
| R7 | Space/Enter reveal; 1–4 grade after reveal | :234-253, flashcardData.ts:193-215 | `reviewKeyAction` (Task 7) |
| R8 | Loading skeleton / load error | :278-299 | review skeleton / error with Try again (Task 13) |
| R9 | Nothing due → says when + Back to decks | :301-316 | review "Nothing due" state (Task 13) |
| R10 | Reviewed count and "N still due" | :321-332 | RD sub-line "26 cards · best combo ×9" + "N still due" row (Task 7) |
| R11 | "N grades still saving" | :333-337 | RD `savingLine` (Task 7) |
| R12 | Grade distribution | :342-354 | replaced by "knew it" count (listed in PR; Needs user decision 6) |
| R13 | Per-card interval before → after | :356-378 | intervals shown on each grade button before rating (Needs user decision 6) |
| R14 | Back to decks | :380-388 | RD "Back to decks" (Task 13) |
| R15 | Progress "Card X of Y", remaining, bar | :393-423 | `4/26` + bar (Task 13) |
| R16 | Source badge on the review card | :435-437 | `AiMark` corner (Task 13) |
| R17 | Reveal button with Space hint | :451-453 | "Show answer" button; desktop keys line (Task 13) |
| R18 | Grade buttons with 1–4 hints | :460-482 | grade buttons; desktop shows `<kbd>` (Task 13) |

**Backend** (`routers/flashcards.py`, `flashcard_repo.py`, `schemas_flashcards.py`)

| # | Rule | Source | Kept by |
|---|---|---|---|
| B1 | Student-only router | flashcards.py:68-70 | unchanged |
| B2 | Another student's deck/card → 404 | :79-82 | new routes use `_raise_for` (Task 4 tests) |
| B3 | `no_weaknesses` → 409 with reason | :83-84 | unchanged + weakness pick (Task 2) |
| B4 | No generator → 503 | :85-88 | `start_generation` raises first (Task 3) |
| B5 | Unknown origin/grade, bad UUID → 422 | :92-104 | unchanged + rename validation |
| B6 | Decks newest first | flashcard_repo.py:420 | unchanged ordering from the API; the client sorts due-first |
| B7 | `count` 1–50 | schemas_flashcards.py:56 | unchanged |
| B8 | `generatedCount` never padded | flashcard_repo.py:400-406 | `GenerationStatusDTO.generatedCount` = real rows (Task 3) |
| B9 | AI source permanent; edit has no `source` | :570-604 | unchanged |
| B10 | `limit` ≥ 1 | flashcards.py:350 | unchanged |
| B11 | `totalDue` ignores `limit`; `nextDueAt` | flashcard_repo.py:480-523 | unchanged + `upcoming` (Task 2) |
| B12 | `flashcard_reviewed` XP on the review id | flashcards.py:383-391 | unchanged; amount surfaced as `xpAwarded` (Task 4) |
| B13 | Deleting a deck cascades its cards and reviews | flashcard_repo.py:619-640 | unchanged |

**Navigation and platform**

| # | Item | Source | Kept by |
|---|---|---|---|
| N1 | Sidebar per-subject "Flashcards" link | shell.tsx:97 | route `flashcards/:subjectCode` stays |
| N2 | Study plan "Go to flashcards" | studyPlanData.ts:281 | same route |
| N3 | Old review deep links `flashcards/review/:subjectCode` | index.tsx:420 | redirect to `flashcards/review?subject=` (Task 10) |
| N4 | Breadcrumbs and subject accordion | data.ts:93, :199-203 | updated arms (Task 10) |
| N5 | Decks list persists offline (`["flashcards","decks"]`) | persistAllowlist.ts:25 | key prefix unchanged (Task 5) |

---

## Frame-to-state table

Breakpoints:
- **phone:** below 768px
- **tablet:** 768–1023px. Same layout as phone, with content centred at a max width of 640px.
- **desktop:** 1024px and up. List plus side panel; the review is a centred 640px column with key hints.

The shell draws the rail at 1280px and up. Between 1024 and 1279 it draws top-bar tabs and the content keeps the list and panel.

| Frame | Real state | Component | Breakpoints | Trigger |
|---|---|---|---|---|
| FD | Decks, due first | `FlashcardsScreen` `kind:"ready"` with `hero.reviewLabel` | all (desktop = FDD) | decks loaded, `totalDue > 0` |
| FN | New deck sheet | `NewDeckSheet` | all (desktop: adaptive panel) | `+` button, an FZ option, the FS tip "Make it" |
| FV | Deck, cards | `DeckScreen` → `DeckBody` | phone, tablet | tap a deck row |
| FC | Edit card | `CardSheet mode="edit"` | all | pen button on a card row |
| — | Add card | `CardSheet mode="add"` | all | "+ Add card" |
| — | Delete card confirm | `CardSheet` step `confirm-delete` | all | "Delete card" in FC |
| FX | Delete deck | `DeleteDeckSheet` | all | deck menu → Delete deck |
| — | Rename deck | `RenameDeckSheet` | all | deck menu → Rename |
| FG | Writing a deck | `WritingState` (phone/tablet, in `DeckScreen`); compact panel version without Binny (desktop) | all | deck `generationStatus === "writing"` |
| FGX | Couldn't write cards | `NewDeckSheet` with `errl` + Try again | all | generation status `failed` while the sheet is open, or a failed deck opened from the list |
| — | Failed deck row | `DeckRow` with status line "Couldn't write the cards" | all | `generationStatus === "failed"` in the list |
| — | Writing deck row | `DeckRow` with status line "Writing 12 cards…" | all | `generationStatus === "writing"` in the list |
| FZ | Empty shelf | `EmptyShelf` | all | `decks.length === 0` |
| FS | Sparse | `kind:"ready"` + `sparse` extras (tip + walkthrough) | all | one deck with ≤ 10 cards |
| FL | Loading | `DecksLoading` | all | decks query pending |
| FE | Couldn't load | `DecksError` | all | decks query error |
| RF0 | Review front | `ReviewScreen` `phase:"front"` | phone/tablet (desktop = FRD) | session started |
| RF1 | Flipped, rate | `phase:"back"` with the 4 grade buttons and intervals | phone/tablet | tap card, Show answer, Space, right swipe |
| RF2 | Swiping right = Good | `ReviewCard` drag with `swipeVisual` stamp | touch/pointer | horizontal drag on a flipped card |
| FR | Ratings not saved | sync banner above the stack | all | `session.failed.length > 0` |
| RD | All caught up | `ReviewDone` | all | `index >= cards.length` |
| — | Nothing due (review) | `ReviewScreen` `kind:"none"` | all | review opened with zero due |
| FDD | Desktop list + deck panel | `FlashcardsScreen` with `<aside>` `DeckBody variant="panel"` | ≥1024 | default; `?deck=` selects |
| FRD | Desktop review | `ReviewScreen` 640px column, `<kbd>` on grades, keys line | ≥1024 | same as RF1 |

---

## Interactions and motion

All durations and easings below come from `fc.css`, `pr.css`, `sp.css` and `t.css`. Mock `var(--ease)` = `cubic-bezier(.2,.8,.2,1)` = the app's `--ease-out` token (Tailwind `ease-out` class maps to it via `--ease-out`). Every animation listed has a `motion-reduce:` fallback.

| Interaction | Mock source | Values | Reduced motion |
|---|---|---|---|
| Card flip on reveal | fc.css `.fcard.flip{animation:flip .45s var(--ease) both}`, `@keyframes flip{from{transform:rotateY(-80deg);opacity:.3}}` | `fc-flip 450ms var(--ease-out) both` | `motion-reduce:animate-none` (instant) |
| Under-card | fc.css `.fcard.under{transform:translateY(12px) scale(.94);opacity:.6}` | static | same |
| Next card rises after a grade | derived from `.under` | `fc-rise 280ms var(--ease-out)`: from `translateY(12px) scale(.94)`, opacity .6 | none |
| Drag follow | RF2 `.swr{transform:translateX(18px) rotate(4deg)}` | `translateX(dx) rotate(clamp(dx*0.08,-12,12)deg)` via `useDragGesture` `onProgress`; spring back uses the hook's `springEasing` | no rotation (`rotateDeg` 0); translate only |
| Stamp | fc.css `.stamp` (top 22px left 22px, 800 18px, inset 2.5px ring, rotate −10deg) | opacity = `clamp(abs(dx)/80,0,1)`; "Good" left-top in success-text, "Again" right-top in on-error-container rotated +10deg | same (opacity is not motion) |
| Card ring past threshold | `.swr` `inset 0 0 0 3px var(--ok)` | ring appears when `abs(dx) ≥ 80` | same |
| Fly out on commit | none in mock (gap filled) | `fc-out-right` / `fc-out-left` 240ms `var(--ease-in-soft)`: to `translateX(±120%) rotate(±18deg)`, opacity 0 | instant swap |
| Grade button press | fc.css `.grades button{transition:transform .15s var(--ease)}`, `:active{scale(.96)}` | `transition-transform duration-150 ease-out active:scale-[0.96]` | `motion-reduce:transition-none motion-reduce:active:scale-100` |
| Sheet up | pr.css `.rvl{animation:rvup .45s var(--ease) both}`, `@keyframes rvup{from{transform:translateY(40%);opacity:.4}}` | kit `SheetContent` / `BottomSheetSurface` motion (same intent) | kit handles reduced motion |
| Topic chip hover | t.css `.tm{transition:translate .2s var(--ease)}`, `.tm:hover{translate:0 -2px}` | `transition-[translate] duration-200 ease-out hover:-translate-y-0.5` | `motion-reduce:hover:translate-y-0` |
| Deck row hover | fc.css `.dkr:hover b{color:var(--p)}` | `group-hover:text-primary` on the title | same |
| Skeleton shimmer | t.css `.sk{animation:skm 1.4s linear infinite}` | kit `SkeletonBlock` | kit `motion-reduce` |
| Progress bar | `.fprog i` width | `scale-x` transform, `transition-transform duration-300 ease-out` | `motion-reduce:transition-none` |
| Writing progress | FG `.fprog` 55% | `writingProgress(elapsed, requested)` 0→0.9, `transition-transform duration-[600ms] ease-out` every 500ms tick | no transition; value still updates |
| Combo chip bump | `.combo` | F1 `ComboChip` (bumps when count rises; hidden < 2) | F1 handles |
| Binny | `BIN('happy',64)` etc. | F1 `Binny` with `motion="idle"`; done screen `motion="hop"` | F1 → `none` |
| Focus | fc.css `:focus-visible{outline:2.5px solid var(--p);outline-offset:2px;border-radius:14px}` | `focus-visible:outline-[2.5px] focus-visible:outline-primary focus-visible:outline-offset-2` | — |

Keys: Space/Enter flips; 1–4 rate after the flip; Escape closes sheets (Radix). Swipe: before the flip, only a rightward swipe reveals. After the flip, left = Again and right = Good. Hard and Easy stay button- and key-only.

---

## Backend

### Task 1: Deck generation status columns (model + migration)

**Needs user decision 1 before merge.** The master plan does not list L10 among the lanes that may edit `lemely/db/models/*`. Write and test this on throwaway databases; do not run it on a shared database.

**Files:**
- Modify: `lemely/db/models/flashcards.py` (the `FlashcardDeck` class and `__all__`)
- Create: `lemely/db/migrations/versions/0055_flashcard_generation.py`
- Test: `tests/test_migration_flashcard_generation.py`

**Interfaces:**
- Produces: `DeckGenerationStatus(StrEnum)` with members `writing`, `ready`, `failed`. New `FlashcardDeck` columns:
  - `generation_status: str` (NOT NULL, default `'ready'`, check constraint)
  - `requested_count: int | None`
  - `generation_started_at: datetime | None`
  - `generation_error: str | None` (max 64)

- [ ] **Step 1: Write the failing migration test**

```python
# tests/test_migration_flashcard_generation.py
"""Migration 0055_flashcard_generation: a generation status on flashcard decks.

Additive. Existing decks read as ``ready``; the check constraint refuses an unknown status; the
downgrade drops the four columns and the constraint and nothing else.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.exc import IntegrityError

from lemely.db.base import Base
from lemely.db.models import User, import_all_models
from lemely.db.models.enums import Role
from tests.test_migration_tutoring_enums import current_revision, head_revision, upgrade_head

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.orm import Session, sessionmaker

import_all_models()

REVISION = "0055_flashcard_generation"
DOWN_REVISION = "0054_waitlist_email_confirmation"
TABLE = "flashcard_decks"
NEW_COLUMNS = {"generation_status", "requested_count", "generation_started_at", "generation_error"}

_COLUMNS_SQL = sa.text(
    "SELECT column_name, data_type, character_maximum_length, is_nullable, column_default "
    "FROM information_schema.columns WHERE table_name = :t"
)


def _user(session: Session) -> uuid.UUID:
    uid = uuid.uuid4()
    session.add(User(id=uid, email=f"{uid}@example.com", role=Role.student))
    session.flush()
    return uid


def _insert_old_style_deck(session: Session, user_id: uuid.UUID) -> None:
    # Only pre-0055 columns, as a deck written before this migration would be.
    session.execute(
        sa.text(
            "INSERT INTO flashcard_decks (user_id, subject_code, title, origin) "
            "VALUES (:u, '0580', 'Vectors', 'manual')"
        ),
        {"u": user_id},
    )


def test_revision_chains_from_0054() -> None:
    script_dir = ScriptDirectory.from_config(Config("alembic.ini"))
    revision = script_dir.get_revision(REVISION)
    assert revision is not None
    assert revision.down_revision == DOWN_REVISION
    assert len(REVISION) <= 32  # alembic_version.version_num is varchar(32)


def test_columns_defaults_and_orm_match(migrated_sessionmaker: sessionmaker[Session]) -> None:
    with migrated_sessionmaker.begin() as session:
        cols = {row[0]: row for row in session.execute(_COLUMNS_SQL, {"t": TABLE})}
        assert NEW_COLUMNS <= set(cols)
        assert cols["generation_status"][1:4] == ("character varying", 16, "NO")
        assert "ready" in (cols["generation_status"][4] or "")
        assert cols["requested_count"][1] == "integer"
        assert cols["requested_count"][3] == "YES"
        assert cols["generation_started_at"][1] == "timestamp with time zone"
        assert cols["generation_error"][1:4] == ("character varying", 64, "YES")

        user_id = _user(session)
        _insert_old_style_deck(session, user_id)
        status = session.execute(sa.text("SELECT generation_status FROM flashcard_decks")).scalar_one()
        assert status == "ready"

        diff = compare_metadata(
            MigrationContext.configure(session.connection(), opts={"compare_type": True}),
            Base.metadata,
        )
    assert [d for d in diff if TABLE in repr(d)] == []


def test_check_constraint_refuses_an_unknown_status(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    with migrated_sessionmaker() as session:
        user_id = _user(session)
        _insert_old_style_deck(session, user_id)
        with pytest.raises(IntegrityError):
            session.execute(sa.text("UPDATE flashcard_decks SET generation_status = 'cooking'"))
            session.flush()
        session.rollback()


def test_upgrade_downgrade_upgrade_round_trip(
    migrated_sessionmaker_with_downgrade: tuple[sessionmaker[Session], Callable[[str], None]],
) -> None:
    sm, downgrade_to = migrated_sessionmaker_with_downgrade
    with sm.begin() as session:
        user_id = _user(session)
        _insert_old_style_deck(session, user_id)

    downgrade_to(DOWN_REVISION)

    with sm() as session:
        assert current_revision(session) == DOWN_REVISION
        cols = {row[0] for row in session.execute(_COLUMNS_SQL, {"t": TABLE})}
        assert cols.isdisjoint(NEW_COLUMNS)
        assert session.execute(sa.text(f"SELECT count(*) FROM {TABLE}")).scalar_one() == 1  # noqa: S608 - constant

    upgrade_head()

    with sm() as session:
        assert current_revision(session) == head_revision()
        status = session.execute(sa.text("SELECT generation_status FROM flashcard_decks")).scalar_one()
        assert status == "ready"
```

- [ ] **Step 2: Run it to see it fail**

Run: `PYTHONPATH=$WT /home/sico/Code/Lemely/.venv/bin/python -m pytest tests/test_migration_flashcard_generation.py -q`
Expected: FAIL. `test_revision_chains_from_0054` fails with `revision is None`; the others fail on the missing columns. A skip means local Postgres is down; start it before going on.

- [ ] **Step 3: Add the enum and columns to the model**

In `lemely/db/models/flashcards.py`, after `class ReviewGrade`, add:

```python
class DeckGenerationStatus(enum.StrEnum):
    """Where an AI deck's card writing stands (redesign L10).

    ``ready`` is also the value for every manual deck and every deck written before generation
    became asynchronous, so a reader never has to special-case "no status". Stored as a short
    string with a check constraint rather than a Postgres enum: the set is small, and widening
    it later should not need an ``ALTER TYPE``.
    """

    writing = "writing"
    ready = "ready"
    failed = "failed"
```

In `class FlashcardDeck`, replace `__table_args__` and add the columns after `origin`:

```python
    __table_args__ = (
        sa.Index("ix_flashcard_decks_user_id_subject_code", "user_id", "subject_code"),
        sa.CheckConstraint(
            "generation_status IN ('writing', 'ready', 'failed')", name="generation_status"
        ),
    )
```

```python
    generation_status: Mapped[str] = mapped_column(
        sa.String(16), nullable=False, server_default=sa.text("'ready'")
    )
    """A :class:`DeckGenerationStatus` value. ``writing`` while the background job runs."""
    requested_count: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    """How many cards the student asked the model for. ``NULL`` for a manual deck."""
    generation_started_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    """When the current writing attempt began; a stale ``writing`` deck is reported failed."""
    generation_error: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    """A short machine code (``model_error``, ``no_cards``, ``timeout``, ``unavailable``)."""
```

Add `"DeckGenerationStatus",` to `__all__` (keep it sorted).

- [ ] **Step 4: Write the migration**

```python
# lemely/db/migrations/versions/0055_flashcard_generation.py
"""flashcard decks: generation status (redesign L10).

Revision ID: 0055_flashcard_generation
Revises: 0054_waitlist_email_confirmation
Create Date: 2026-11-15 00:00:00.000000

Four columns and one check constraint on ``flashcard_decks``. Additive.

* ``generation_status``: ``writing`` / ``ready`` / ``failed``, NOT NULL, default ``ready`` so
  every existing deck reads as ready without a backfill.
* ``requested_count``: the card count the student asked the model for.
* ``generation_started_at``: start of the current writing attempt (stale detection).
* ``generation_error``: a short machine code when writing failed.

``downgrade`` drops the constraint and the four columns.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
# Kept to <=32 chars: alembic_version.version_num is varchar(32).
revision: str = "0055_flashcard_generation"
down_revision: str | Sequence[str] | None = "0054_waitlist_email_confirmation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "flashcard_decks"
CHECK = "ck_flashcard_decks_generation_status"


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        TABLE,
        sa.Column(
            "generation_status",
            sa.String(length=16),
            server_default=sa.text("'ready'"),
            nullable=False,
        ),
    )
    op.add_column(TABLE, sa.Column("requested_count", sa.Integer(), nullable=True))
    op.add_column(
        TABLE, sa.Column("generation_started_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(TABLE, sa.Column("generation_error", sa.String(length=64), nullable=True))
    op.create_check_constraint(
        op.f(CHECK), TABLE, "generation_status IN ('writing', 'ready', 'failed')"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(op.f(CHECK), TABLE, type_="check")
    op.drop_column(TABLE, "generation_error")
    op.drop_column(TABLE, "generation_started_at")
    op.drop_column(TABLE, "requested_count")
    op.drop_column(TABLE, "generation_status")
```

- [ ] **Step 5: Run the migration test and the schema tests**

Run: `PYTHONPATH=$WT /home/sico/Code/Lemely/.venv/bin/python -m pytest tests/test_migration_flashcard_generation.py tests/test_flashcard_schema.py tests/test_db_schema.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
pre-commit run --files lemely/db/models/flashcards.py lemely/db/migrations/versions/0055_flashcard_generation.py tests/test_migration_flashcard_generation.py
git commit -S -m "feat(db): flashcard deck generation status (L10)" -- lemely/db/models/flashcards.py lemely/db/migrations/versions/0055_flashcard_generation.py tests/test_migration_flashcard_generation.py
```

---

### Task 2: Service reads: mastery, marks lost, rename, weak topics, weakness pick, due scope, forecast, interval preview

**Files:**
- Modify: `lemely/db/flashcard_repo.py`
- Test: `tests/test_flashcard_repo.py` (append a section; change one existing test)

**Interfaces:**
- Consumes: `DeckGenerationStatus` and the new deck columns (Task 1).
- Produces:
  - constants `KNOWN_INTERVAL_DAYS = 7`, `UPCOMING_WINDOW = timedelta(days=8)`, `UPCOMING_CAP = 1000`
  - `MasteryCounts(new: int, learning: int, known: int)`
  - `WeakTopic(subject_code: str, topic: str, marks_lost: int, accuracy_pct: int)`
  - `DeckSummary` gains `mastery: MasteryCounts`, `marks_lost: int | None`, `generation_status: DeckGenerationStatus`, `requested_count: int | None`
  - `DeckDetail` gains `due_count: int`, `mastery: MasteryCounts`, `marks_lost: int | None`, `generation_status: DeckGenerationStatus`, `requested_count: int | None`
  - `CardView` gains `next_interval_days: dict[str, int]` (keys `again`, `hard`, `good`, `easy`)
  - `DueSession` gains `upcoming: list[datetime]` and `again_delay_minutes: int`
  - methods:
    - `rename_deck(student_id, deck_id, *, title: str) -> DeckSummary`
    - `weak_topics(student_id, *, subject_code: str | None = None, limit: int = 6) -> list[WeakTopic]`
    - `list_due_cards(..., deck_id=None)`
    - `due_session(student_id, *, subject_code=None, deck_id=None, limit=None) -> DueSession`
  - `create_deck`/`start_generation` with `origin=weakness` accept a `topic` that is one of the caller's recorded weak topics. A topic outside them raises `FlashcardValidationError`; omitting it still picks the top one.

- [ ] **Step 1: Write the failing tests**

Change the existing `test_weakness_deck_rejects_a_caller_supplied_topic` in `tests/test_flashcard_repo.py` to the pair below (the rule moves from "never accept a topic" to "only accept a recorded one"), then append the new section. Add `from lemely.db.flashcard_repo import KNOWN_INTERVAL_DAYS, MasteryCounts` to the existing import block, and `ReviewGrade` from `lemely.db.models.flashcards` if not already imported.

```python
def test_weakness_deck_rejects_a_topic_that_is_not_a_recorded_weakness(
    pg_sessionmaker: sessionmaker[Session], flashcard_service: FlashcardService
) -> None:
    student = _seed_user(pg_sessionmaker)
    _seed_weakness(pg_sessionmaker, student, topic="3 Waves", lost_marks=5)
    with pytest.raises(FlashcardValidationError):
        flashcard_service.create_deck(
            student,
            subject_code="0625",
            title="Weak spots",
            origin=DeckOrigin.weakness,
            topic="1 Motion",
        )


def test_weakness_deck_accepts_a_chosen_recorded_weakness(
    pg_sessionmaker: sessionmaker[Session], flashcard_service: FlashcardService
) -> None:
    student = _seed_user(pg_sessionmaker)
    _seed_weakness(pg_sessionmaker, student, topic="3 Waves", lost_marks=9)
    _seed_weakness(pg_sessionmaker, student, topic="1 Motion", lost_marks=2)
    deck = flashcard_service.create_deck(
        student, subject_code="0625", title="Motion", origin=DeckOrigin.weakness, topic="1 Motion"
    )
    assert deck.topic == "1 Motion"
```

```python
# ---------------------------------------------------------------------------
# Redesign L10: mastery, marks lost, rename, weak topics, due scope, forecast
# ---------------------------------------------------------------------------


def _manual_deck_with_cards(service: FlashcardService, student: uuid.UUID, n: int) -> uuid.UUID:
    deck = service.create_deck(student, subject_code="0625", title="Deck", origin=DeckOrigin.manual)
    for i in range(n):
        service.add_card(student, deck.id, front=f"Q{i}", back=f"A{i}")
    return deck.id


def test_list_decks_reports_new_learning_known_counts(
    pg_sessionmaker: sessionmaker[Session], flashcard_service: FlashcardService
) -> None:
    student = _seed_user(pg_sessionmaker)
    deck_id = _manual_deck_with_cards(flashcard_service, student, 4)
    cards = flashcard_service.get_deck(student, deck_id).cards
    # One card reviewed once (learning), one pushed past the known threshold, two untouched.
    flashcard_service.record_review(student, cards[0].id, ReviewGrade.good)
    with pg_sessionmaker.begin() as session:
        row = session.get(Flashcard, cards[1].id)
        assert row is not None
        row.repetitions = 3
        row.interval_days = KNOWN_INTERVAL_DAYS
        row.last_reviewed_at = _FIXED_NOW

    [summary] = flashcard_service.list_decks(student)
    assert summary.mastery == MasteryCounts(new=2, learning=1, known=1)
    assert summary.card_count == 4


def test_weakness_deck_reports_the_marks_its_topic_cost(
    pg_sessionmaker: sessionmaker[Session], flashcard_service: FlashcardService
) -> None:
    student = _seed_user(pg_sessionmaker)
    _seed_weakness(pg_sessionmaker, student, topic="3 Waves", lost_marks=5)
    _seed_weakness(pg_sessionmaker, student, topic="3 Waves", lost_marks=4)
    flashcard_service.create_deck(
        student, subject_code="0625", title="Waves", origin=DeckOrigin.weakness
    )
    flashcard_service.create_deck(
        student, subject_code="0625", title="Mine", origin=DeckOrigin.manual, topic="3 Waves"
    )
    by_title = {d.title: d for d in flashcard_service.list_decks(student)}
    assert by_title["Waves"].marks_lost == 9
    # Only a weakness deck claims "cost you N marks"; a manual deck on the same topic does not.
    assert by_title["Mine"].marks_lost is None


def test_rename_deck_trims_and_rejects_blank_or_long_titles(
    pg_sessionmaker: sessionmaker[Session], flashcard_service: FlashcardService
) -> None:
    student = _seed_user(pg_sessionmaker)
    deck_id = _manual_deck_with_cards(flashcard_service, student, 1)
    renamed = flashcard_service.rename_deck(student, deck_id, title="  Vectors  ")
    assert renamed.title == "Vectors"
    assert renamed.card_count == 1
    with pytest.raises(FlashcardValidationError):
        flashcard_service.rename_deck(student, deck_id, title="   ")
    with pytest.raises(FlashcardValidationError):
        flashcard_service.rename_deck(student, deck_id, title="x" * 81)


def test_rename_someone_elses_deck_is_an_ownership_error(
    pg_sessionmaker: sessionmaker[Session], flashcard_service: FlashcardService
) -> None:
    owner = _seed_user(pg_sessionmaker)
    other = _seed_user(pg_sessionmaker)
    deck_id = _manual_deck_with_cards(flashcard_service, owner, 0)
    with pytest.raises(FlashcardOwnershipError):
        flashcard_service.rename_deck(other, deck_id, title="Mine now")


def test_weak_topics_ranks_by_marks_lost_with_accuracy(
    pg_sessionmaker: sessionmaker[Session], flashcard_service: FlashcardService
) -> None:
    student = _seed_user(pg_sessionmaker)
    _seed_weakness(pg_sessionmaker, student, topic="3 Waves", lost_marks=6, maximum_marks=10)
    _seed_weakness(pg_sessionmaker, student, topic="1 Motion", lost_marks=2, maximum_marks=10)
    _seed_weakness(
        pg_sessionmaker, student, subject_code="0580", topic="E7 Vectors", lost_marks=9,
        maximum_marks=15,
    )
    topics = flashcard_service.weak_topics(student)
    assert [(t.subject_code, t.topic, t.marks_lost) for t in topics] == [
        ("0580", "E7 Vectors", 9),
        ("0625", "3 Waves", 6),
        ("0625", "1 Motion", 2),
    ]
    assert topics[0].accuracy_pct == 40
    only_physics = flashcard_service.weak_topics(student, subject_code="0625", limit=1)
    assert [t.topic for t in only_physics] == ["3 Waves"]


def test_due_session_scoped_to_one_deck_and_carries_the_forecast(
    pg_sessionmaker: sessionmaker[Session], flashcard_service: FlashcardService
) -> None:
    student = _seed_user(pg_sessionmaker)
    deck_a = _manual_deck_with_cards(flashcard_service, student, 2)
    deck_b = _manual_deck_with_cards(flashcard_service, student, 3)
    first_b = flashcard_service.get_deck(student, deck_b).cards[0]
    flashcard_service.record_review(student, first_b.id, ReviewGrade.good)  # due in 1 day

    session_a = flashcard_service.due_session(student, deck_id=deck_a)
    assert session_a.total_due == 2
    assert {c.id for c in session_a.cards} <= {
        c.id for c in flashcard_service.get_deck(student, deck_a).cards
    }

    session_all = flashcard_service.due_session(student)
    assert session_all.total_due == 4
    assert session_all.upcoming == [_FIXED_NOW + timedelta(days=1)]
    assert session_all.again_delay_minutes == 10


def test_due_session_for_someone_elses_deck_is_an_ownership_error(
    pg_sessionmaker: sessionmaker[Session], flashcard_service: FlashcardService
) -> None:
    owner = _seed_user(pg_sessionmaker)
    other = _seed_user(pg_sessionmaker)
    deck_id = _manual_deck_with_cards(flashcard_service, owner, 1)
    with pytest.raises(FlashcardOwnershipError):
        flashcard_service.due_session(other, deck_id=deck_id)


def test_cards_carry_the_interval_each_grade_would_give(
    pg_sessionmaker: sessionmaker[Session], flashcard_service: FlashcardService
) -> None:
    student = _seed_user(pg_sessionmaker)
    deck_id = _manual_deck_with_cards(flashcard_service, student, 1)
    [card] = flashcard_service.due_session(student, deck_id=deck_id).cards
    # A new card: Again is the 10-minute relearning step (0 days); any pass is 1 day.
    assert card.next_interval_days == {"again": 0, "hard": 1, "good": 1, "easy": 1}
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `PYTHONPATH=$WT /home/sico/Code/Lemely/.venv/bin/python -m pytest tests/test_flashcard_repo.py -q`
Expected: FAIL with `ImportError: cannot import name 'KNOWN_INTERVAL_DAYS'`.

- [ ] **Step 3: Implement**

In `lemely/db/flashcard_repo.py`:

1. Imports. Add `timedelta` to the `datetime` import and `structlog`. Add `AGAIN_REVIEW_DELAY` to the `lemely.core.spaced_repetition` import. Add `DeckGenerationStatus` to the `lemely.db.models.flashcards` import. Below the imports, add:

```python
log = structlog.get_logger(__name__)

#: A card whose interval has reached a week counts as "known" on the deck's mastery bar.
#: "Easy" on a young card sends it about a week out, so "known" means "you said it was easy".
KNOWN_INTERVAL_DAYS = 7
#: How far ahead :meth:`FlashcardService.due_session` lists upcoming due times ("Coming back").
UPCOMING_WINDOW = timedelta(days=8)
#: Hard cap on the forecast list so a huge backlog can't bloat the response.
UPCOMING_CAP = 1000
#: Longest title a rename accepts.
DECK_TITLE_MAX = 80
#: A topic label's leading syllabus code, e.g. ``"4.3 "`` in ``"4.3 Electric circuits"``.
_TOPIC_CODE = re.compile(r"^[A-Z]?\d+(?:\.\d+)*\s+")
```

Add `import re` to the stdlib imports.

2. New dataclasses (after `ReviewOutcome`), and the extra fields on the existing ones:

```python
@dataclass(frozen=True, slots=True)
class MasteryCounts:
    """How a deck's cards split on the mastery bar: never reviewed, in progress, known."""

    new: int
    learning: int
    known: int


@dataclass(frozen=True, slots=True)
class WeakTopic:
    """One recorded weak topic, for the new-deck sheet's chips."""

    subject_code: str
    topic: str
    marks_lost: int
    accuracy_pct: int


@dataclass(frozen=True, slots=True)
class _DeckCounts:
    total: int
    due: int
    mastery: MasteryCounts

    @classmethod
    def empty(cls) -> _DeckCounts:
        return cls(total=0, due=0, mastery=MasteryCounts(new=0, learning=0, known=0))
```

Append these fields to `DeckSummary` (after `created_at`):

```python
    mastery: MasteryCounts
    marks_lost: int | None
    """Net marks the deck's topic cost the student. Only for ``origin=weakness``."""
    generation_status: DeckGenerationStatus
    requested_count: int | None
```

Append these fields to `DeckDetail` (after `cards`):

```python
    due_count: int
    mastery: MasteryCounts
    marks_lost: int | None
    generation_status: DeckGenerationStatus
    requested_count: int | None
```

Append this field to `CardView` (after `last_reviewed_at`):

```python
    next_interval_days: dict[str, int]
    """The interval in days each grade would give right now (``again`` is 0: the 10-minute step)."""
```

Append these fields to `DueSession` (after `next_due_at`):

```python
    upcoming: list[datetime]
    """Due times of cards coming due within :data:`UPCOMING_WINDOW`, soonest first."""
    again_delay_minutes: int
```

3. Weakness topic resolution: replace `_resolve_deck_topic`'s weakness branch and `_top_weak_topic` with:

```python
        if origin == DeckOrigin.weakness:
            with self._sessionmaker() as session:
                totals = self._weak_topic_totals(session, student_uuid, subject_code)
            if not totals:
                raise FlashcardUnavailableError(FlashcardUnavailableReason.no_weaknesses)
            if topic is None:
                return sorted(totals, key=lambda t: (-totals[t], t))[0]
            if topic not in totals:
                # The student may choose among their own recorded weak topics, never name one the
                # weakness engine did not flag: that would launder an arbitrary topic as a weakness.
                raise FlashcardValidationError(
                    "origin='weakness' topic must be one of your recorded weak topics"
                )
            return topic
```

```python
    def _weak_topic_totals(
        self, session: Session, student_uuid: uuid.UUID, subject_code: str
    ) -> dict[str, int]:
        """Net lost marks per topic for ``subject_code``, keeping only topics with marks lost.

        Reads ``WeaknessRecord`` rows verbatim (D4.10 §2), as P4.5's practice service does.
        """
        rows = session.execute(
            select(WeaknessRecord.topic, WeaknessRecord.lost_marks)
            .join(Attempt, Attempt.id == WeaknessRecord.attempt_id)
            .where(WeaknessRecord.user_id == student_uuid, Attempt.subject_code == subject_code)
        ).all()
        totals: dict[str, int] = {}
        for topic, lost in rows:
            totals[topic] = totals.get(topic, 0) + lost
        return {t: lost for t, lost in totals.items() if lost > 0}
```

Delete `_top_weak_topic`. Its only caller was the branch above; ties still break alphabetically.

4. Counts and summaries: replace `_deck_counts` and `_to_summary`, and add `_marks_lost_by_topic`:

```python
    def _deck_counts(self, session: Session, deck_id: uuid.UUID, moment: datetime) -> _DeckCounts:
        total, due, new, known = session.execute(
            select(
                func.count(),
                func.count().filter(Flashcard.due_at <= moment),
                func.count().filter(
                    Flashcard.repetitions == 0, Flashcard.last_reviewed_at.is_(None)
                ),
                func.count().filter(Flashcard.interval_days >= KNOWN_INTERVAL_DAYS),
            )
            .select_from(Flashcard)
            .where(Flashcard.deck_id == deck_id)
        ).one()
        total, due, new, known = int(total or 0), int(due or 0), int(new or 0), int(known or 0)
        return _DeckCounts(
            total=total,
            due=due,
            mastery=MasteryCounts(new=new, learning=max(total - new - known, 0), known=known),
        )

    def _marks_lost_by_topic(
        self, session: Session, student_uuid: uuid.UUID
    ) -> dict[tuple[str, str], int]:
        rows = session.execute(
            select(Attempt.subject_code, WeaknessRecord.topic, func.sum(WeaknessRecord.lost_marks))
            .join(Attempt, Attempt.id == WeaknessRecord.attempt_id)
            .where(WeaknessRecord.user_id == student_uuid)
            .group_by(Attempt.subject_code, WeaknessRecord.topic)
        ).all()
        return {(subject, topic): int(lost or 0) for subject, topic, lost in rows}

    @staticmethod
    def _deck_marks_lost(
        deck: FlashcardDeck, marks: dict[tuple[str, str], int]
    ) -> int | None:
        if deck.origin != DeckOrigin.weakness or deck.topic is None:
            return None
        lost = marks.get((deck.subject_code, deck.topic), 0)
        return lost if lost > 0 else None

    def _to_summary(
        self, deck: FlashcardDeck, counts: _DeckCounts, *, marks_lost: int | None
    ) -> DeckSummary:
        return DeckSummary(
            id=deck.id,
            subject_code=deck.subject_code,
            topic=deck.topic,
            title=deck.title,
            description=deck.description,
            origin=deck.origin,
            card_count=counts.total,
            due_count=counts.due,
            created_at=deck.created_at,
            mastery=counts.mastery,
            marks_lost=marks_lost,
            generation_status=DeckGenerationStatus(deck.generation_status),
            requested_count=deck.requested_count,
        )
```

Update the callers:
- `create_deck` returns `self._to_summary(deck, _DeckCounts.empty(), marks_lost=None)`. `FlashcardDeck(...)` there also sets `generation_status=DeckGenerationStatus.ready.value`. The server default covers it, but the ORM object is read before refresh.
- `list_decks` body inside the session becomes:

```python
            decks = session.scalars(stmt).all()
            marks = self._marks_lost_by_topic(session, student_uuid)
            return [
                self._to_summary(
                    deck,
                    self._deck_counts(session, deck.id, moment),
                    marks_lost=self._deck_marks_lost(deck, marks),
                )
                for deck in decks
            ]
```

- `get_deck` computes `counts = self._deck_counts(session, deck.id, self._now())` and `marks = self._marks_lost_by_topic(session, student_uuid)`. It returns `DeckDetail(..., cards=[...], due_count=counts.due, mastery=counts.mastery, marks_lost=self._deck_marks_lost(deck, marks), generation_status=DeckGenerationStatus(deck.generation_status), requested_count=deck.requested_count)`.

5. Rename and weak topics (new public methods, after `get_deck`):

```python
    def rename_deck(
        self, student_id: uuid.UUID | str, deck_id: uuid.UUID | str, *, title: str
    ) -> DeckSummary:
        """Rename one of the caller's decks. The title is trimmed; blank or over 80 chars is 422.

        Raises:
            FlashcardValidationError: blank or too long.
            FlashcardNotFoundError / FlashcardOwnershipError: as :meth:`get_deck`.
        """
        cleaned = title.strip()
        if not cleaned or len(cleaned) > DECK_TITLE_MAX:
            raise FlashcardValidationError(f"title must be 1-{DECK_TITLE_MAX} characters")
        student_uuid = _as_uuid(student_id)
        deck_uuid = _as_uuid(deck_id)
        with self._sessionmaker() as session, session.begin():
            deck = self._owned_deck(session, student_uuid, deck_uuid)
            deck.title = cleaned
            session.flush()
            marks = self._marks_lost_by_topic(session, student_uuid)
            return self._to_summary(
                deck,
                self._deck_counts(session, deck.id, self._now()),
                marks_lost=self._deck_marks_lost(deck, marks),
            )

    def weak_topics(
        self, student_id: uuid.UUID | str, *, subject_code: str | None = None, limit: int = 6
    ) -> list[WeakTopic]:
        """The caller's recorded weak topics, most marks lost first (ties: subject, then topic).

        ``accuracy_pct`` is ``100 * (available - lost) / available`` over the same rows, rounded
        and clamped to 0-100. Topics with no net marks lost are left out, as in deck creation.
        """
        student_uuid = _as_uuid(student_id)
        with self._sessionmaker() as session:
            stmt = (
                select(
                    Attempt.subject_code,
                    WeaknessRecord.topic,
                    func.sum(WeaknessRecord.lost_marks),
                    func.sum(WeaknessRecord.maximum_marks),
                )
                .join(Attempt, Attempt.id == WeaknessRecord.attempt_id)
                .where(WeaknessRecord.user_id == student_uuid)
                .group_by(Attempt.subject_code, WeaknessRecord.topic)
            )
            if subject_code is not None:
                stmt = stmt.where(Attempt.subject_code == subject_code)
            rows = session.execute(stmt).all()
        topics = []
        for subject, topic, lost, available in rows:
            lost_i, available_i = int(lost or 0), int(available or 0)
            if lost_i <= 0:
                continue
            pct = round(100 * (available_i - lost_i) / available_i) if available_i else 0
            topics.append(WeakTopic(subject, topic, lost_i, max(0, min(100, pct))))
        topics.sort(key=lambda t: (-t.marks_lost, t.subject_code, t.topic))
        return topics[:limit]
```

6. Due scope and forecast. Replace `list_due_cards` and `due_session` with:

```python
    def _due_scope(
        self,
        session: Session,
        student_uuid: uuid.UUID,
        subject_code: str | None,
        deck_id: uuid.UUID | str | None,
    ) -> list[sa.ColumnElement[bool]]:
        clauses: list[sa.ColumnElement[bool]] = [FlashcardDeck.user_id == student_uuid]
        if subject_code is not None:
            clauses.append(FlashcardDeck.subject_code == subject_code)
        if deck_id is not None:
            deck = self._owned_deck(session, student_uuid, _as_uuid(deck_id))
            clauses.append(FlashcardDeck.id == deck.id)
        return clauses

    def list_due_cards(
        self,
        student_id: uuid.UUID | str,
        *,
        subject_code: str | None = None,
        deck_id: uuid.UUID | str | None = None,
        limit: int | None = None,
    ) -> list[CardView]:
        """Every card owned by ``student_id`` due at or before now, soonest first.

        An empty list is a real state ("nothing due today", S-22). ``deck_id`` narrows to one
        deck the caller owns (another student's deck raises, it is never silently empty).
        """
        student_uuid = _as_uuid(student_id)
        moment = self._now()
        with self._sessionmaker() as session:
            scope = self._due_scope(session, student_uuid, subject_code, deck_id)
            stmt = (
                select(Flashcard)
                .join(FlashcardDeck, FlashcardDeck.id == Flashcard.deck_id)
                .where(*scope, Flashcard.due_at <= moment)
                .order_by(Flashcard.due_at)
            )
            if limit is not None:
                stmt = stmt.limit(limit)
            return [self._to_card_view(c, moment) for c in session.scalars(stmt).all()]

    def due_session(
        self,
        student_id: uuid.UUID | str,
        *,
        subject_code: str | None = None,
        deck_id: uuid.UUID | str | None = None,
        limit: int | None = None,
    ) -> DueSession:
        """A review session: due cards, the true due total, the next due time and the forecast.

        ``total_due`` ignores ``limit`` (spec §1.4). ``upcoming`` lists the due times of cards
        coming due within :data:`UPCOMING_WINDOW` so the done screen can say what comes back when
        without inventing it.
        """
        student_uuid = _as_uuid(student_id)
        moment = self._now()
        cards = self.list_due_cards(
            student_id, subject_code=subject_code, deck_id=deck_id, limit=limit
        )
        with self._sessionmaker() as session:
            scope = self._due_scope(session, student_uuid, subject_code, deck_id)
            joined = select(Flashcard).join(FlashcardDeck, FlashcardDeck.id == Flashcard.deck_id)
            total_due = session.scalar(
                select(func.count())
                .select_from(Flashcard)
                .join(FlashcardDeck, FlashcardDeck.id == Flashcard.deck_id)
                .where(*scope, Flashcard.due_at <= moment)
            )
            next_due_at = session.scalar(
                select(func.min(Flashcard.due_at))
                .select_from(Flashcard)
                .join(FlashcardDeck, FlashcardDeck.id == Flashcard.deck_id)
                .where(*scope, Flashcard.due_at > moment)
            )
            upcoming = list(
                session.scalars(
                    joined.with_only_columns(Flashcard.due_at)
                    .where(
                        *scope,
                        Flashcard.due_at > moment,
                        Flashcard.due_at <= moment + UPCOMING_WINDOW,
                    )
                    .order_by(Flashcard.due_at)
                    .limit(UPCOMING_CAP)
                ).all()
            )
        return DueSession(
            cards=cards,
            total_due=int(total_due or 0),
            next_due_at=next_due_at,
            upcoming=upcoming,
            again_delay_minutes=int(AGAIN_REVIEW_DELAY.total_seconds() // 60),
        )
```

Add `import sqlalchemy as sa` for the `sa.ColumnElement` annotation (under `TYPE_CHECKING` is fine since annotations are postponed).

7. Interval preview. Replace `_to_card_view` with a version that takes the clock:

```python
    def _to_card_view(self, card: Flashcard, moment: datetime | None = None) -> CardView:
        schedule = CardSchedule(
            repetitions=card.repetitions,
            ease_factor=card.ease_factor,
            interval_days=card.interval_days,
            lapses=card.lapses,
            due_at=card.due_at,
            last_reviewed_at=card.last_reviewed_at,
        )
        at = moment if moment is not None else self._now()
        return CardView(
            id=card.id,
            front=card.front,
            back=card.back,
            position=card.position,
            source=card.source,
            source_question_id=card.source_question_id,
            repetitions=card.repetitions,
            ease_factor=card.ease_factor,
            interval_days=card.interval_days,
            lapses=card.lapses,
            due_at=card.due_at,
            last_reviewed_at=card.last_reviewed_at,
            next_interval_days={
                grade.value: apply_review(schedule, grade, now=at).interval_days
                for grade in CoreReviewGrade
            },
        )
```

Existing callers that pass one argument keep working.

8. Add `"MasteryCounts"`, `"WeakTopic"` and `"KNOWN_INTERVAL_DAYS"` to `__all__`.

- [ ] **Step 4: Run the repo tests**

Run: `PYTHONPATH=$WT /home/sico/Code/Lemely/.venv/bin/python -m pytest tests/test_flashcard_repo.py -q`
Expected: PASS (all, including the untouched P4.6 tests).

- [ ] **Step 5: Commit**

```bash
pre-commit run --files lemely/db/flashcard_repo.py tests/test_flashcard_repo.py
git commit -S -m "feat(flashcards): mastery, marks lost, rename, weak topics, due scope (L10)" -- lemely/db/flashcard_repo.py tests/test_flashcard_repo.py
```

---

### Task 3: Background generation with a status

**Files:**
- Modify: `lemely/db/flashcard_repo.py`
- Test: `tests/test_flashcard_repo.py` (append)

**Interfaces:**
- Consumes: Task 1 columns, Task 2 `_to_summary(deck, counts, marks_lost=)`, `_DeckCounts`.
- Produces:
  - `GENERATION_STALE_AFTER = timedelta(minutes=5)`
  - `GenerationState(deck_id: uuid.UUID, status: DeckGenerationStatus, requested_count: int | None, generated_count: int, error: str | None)`
  - methods:
    - `start_generation(student_id, *, subject_code, origin, count, topic=None, title=None) -> DeckSummary`: deck saved as `writing`, nothing generated yet
    - `run_generation(deck_id) -> None`: never raises
    - `generation_status(student_id, deck_id) -> GenerationState`
    - `retry_generation(student_id, deck_id) -> GenerationState`
  - `generate_deck(...)` keeps its signature and `GeneratedDeckResult` (start + run + read back), for scripts and existing tests.
  - The default title of a generated deck is the topic name without its syllabus code (`"4.3 Electric circuits"` → `"Electric circuits"`).

- [ ] **Step 1: Write the failing tests**

```python
# ---------------------------------------------------------------------------
# Redesign L10: background generation with a status
# ---------------------------------------------------------------------------


def test_start_generation_saves_a_writing_deck_without_calling_the_model(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student = _seed_user(pg_sessionmaker)
    generator = _mock_generator([], subject_code="0625", topic="4.3 Electric circuits")
    service = FlashcardService(pg_sessionmaker, generator, now=lambda: _FIXED_NOW)

    deck = service.start_generation(
        student, subject_code="0625", origin=DeckOrigin.topic, topic="4.3 Electric circuits",
        count=12,
    )

    assert deck.generation_status == DeckGenerationStatus.writing
    assert deck.requested_count == 12
    assert deck.card_count == 0
    assert deck.title == "Electric circuits"
    generator.generate.assert_not_called()
    state = service.generation_status(student, deck.id)
    assert (state.status, state.generated_count) == (DeckGenerationStatus.writing, 0)


def test_run_generation_writes_ai_cards_and_marks_the_deck_ready(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student = _seed_user(pg_sessionmaker)
    generator = _mock_generator(
        [GeneratedFlashcard(front="Q1", back="A1"), GeneratedFlashcard(front="Q2", back="A2")],
        subject_code="0625",
        topic="1 Motion",
    )
    service = FlashcardService(pg_sessionmaker, generator, now=lambda: _FIXED_NOW)
    deck = service.start_generation(
        student, subject_code="0625", origin=DeckOrigin.topic, topic="1 Motion", count=5
    )

    service.run_generation(deck.id)

    state = service.generation_status(student, deck.id)
    assert state.status == DeckGenerationStatus.ready
    assert (state.requested_count, state.generated_count) == (5, 2)  # never padded
    detail = service.get_deck(student, deck.id)
    assert [c.source for c in detail.cards] == [CardSource.ai, CardSource.ai]
    generator.generate.assert_called_once_with(subject_code="0625", topic="1 Motion", count=5)


def test_a_model_error_marks_the_deck_failed_and_saves_no_cards(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student = _seed_user(pg_sessionmaker)
    generator = MagicMock()
    generator.generate.side_effect = RuntimeError("gemini down")
    service = FlashcardService(pg_sessionmaker, generator, now=lambda: _FIXED_NOW)
    deck = service.start_generation(
        student, subject_code="0625", origin=DeckOrigin.topic, topic="1 Motion", count=5
    )

    service.run_generation(deck.id)  # must not raise

    state = service.generation_status(student, deck.id)
    assert (state.status, state.error, state.generated_count) == (
        DeckGenerationStatus.failed, "model_error", 0,
    )


def test_an_empty_model_answer_is_a_failure_not_an_empty_ready_deck(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student = _seed_user(pg_sessionmaker)
    generator = _mock_generator([], subject_code="0625", topic="1 Motion")
    service = FlashcardService(pg_sessionmaker, generator, now=lambda: _FIXED_NOW)
    deck = service.start_generation(
        student, subject_code="0625", origin=DeckOrigin.topic, topic="1 Motion", count=5
    )
    service.run_generation(deck.id)
    state = service.generation_status(student, deck.id)
    assert (state.status, state.error) == (DeckGenerationStatus.failed, "no_cards")


def test_a_stale_writing_deck_is_reported_failed(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student = _seed_user(pg_sessionmaker)
    clock = {"now": _FIXED_NOW}
    generator = _mock_generator([], subject_code="0625", topic="1 Motion")
    service = FlashcardService(pg_sessionmaker, generator, now=lambda: clock["now"])
    deck = service.start_generation(
        student, subject_code="0625", origin=DeckOrigin.topic, topic="1 Motion", count=5
    )
    clock["now"] = _FIXED_NOW + timedelta(minutes=6)
    state = service.generation_status(student, deck.id)
    assert (state.status, state.error) == (DeckGenerationStatus.failed, "timeout")
    # Persisted, so the list agrees with the status endpoint.
    [summary] = service.list_decks(student)
    assert summary.generation_status == DeckGenerationStatus.failed


def test_retry_puts_a_failed_deck_back_to_writing_and_refuses_a_ready_one(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student = _seed_user(pg_sessionmaker)
    generator = MagicMock()
    generator.generate.side_effect = [
        RuntimeError("first try fails"),
        GeneratedFlashcardDeck(
            subject_code="0625", topic="1 Motion", cards=[GeneratedFlashcard(front="Q", back="A")]
        ),
    ]
    service = FlashcardService(pg_sessionmaker, generator, now=lambda: _FIXED_NOW)
    deck = service.start_generation(
        student, subject_code="0625", origin=DeckOrigin.topic, topic="1 Motion", count=3
    )
    service.run_generation(deck.id)

    retried = service.retry_generation(student, deck.id)
    assert retried.status == DeckGenerationStatus.writing
    service.run_generation(deck.id)
    assert service.generation_status(student, deck.id).status == DeckGenerationStatus.ready
    with pytest.raises(FlashcardValidationError):
        service.retry_generation(student, deck.id)


def test_a_deck_deleted_while_writing_is_left_alone(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student = _seed_user(pg_sessionmaker)
    generator = _mock_generator(
        [GeneratedFlashcard(front="Q", back="A")], subject_code="0625", topic="1 Motion"
    )
    service = FlashcardService(pg_sessionmaker, generator, now=lambda: _FIXED_NOW)
    deck = service.start_generation(
        student, subject_code="0625", origin=DeckOrigin.topic, topic="1 Motion", count=3
    )
    service.delete_deck(student, deck.id)
    service.run_generation(deck.id)  # no deck: a no-op, not an error
    assert service.list_decks(student) == []


def test_generation_status_of_someone_elses_deck_is_an_ownership_error(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    owner = _seed_user(pg_sessionmaker)
    other = _seed_user(pg_sessionmaker)
    generator = _mock_generator([], subject_code="0625", topic="1 Motion")
    service = FlashcardService(pg_sessionmaker, generator, now=lambda: _FIXED_NOW)
    deck = service.start_generation(
        owner, subject_code="0625", origin=DeckOrigin.topic, topic="1 Motion", count=3
    )
    with pytest.raises(FlashcardOwnershipError):
        service.generation_status(other, deck.id)
```

Add `DeckGenerationStatus` to the `lemely.db.models.flashcards` import in the test module.

- [ ] **Step 2: Run them to see them fail**

Run: `PYTHONPATH=$WT /home/sico/Code/Lemely/.venv/bin/python -m pytest tests/test_flashcard_repo.py -q -k "generation or writing or retry or stale"`
Expected: FAIL with `AttributeError: 'FlashcardService' object has no attribute 'start_generation'`.

- [ ] **Step 3: Implement**

Add the constant and dataclass near the others:

```python
#: A ``writing`` deck older than this is reported (and saved) as failed: its worker died.
GENERATION_STALE_AFTER = timedelta(minutes=5)


@dataclass(frozen=True, slots=True)
class GenerationState:
    """Where one deck's card writing stands. ``generated_count`` is the real row count."""

    deck_id: uuid.UUID
    status: DeckGenerationStatus
    requested_count: int | None
    generated_count: int
    error: str | None
```

Replace the whole `generate_deck` method with this block:

```python
    @staticmethod
    def _default_title(topic: str) -> str:
        name = _TOPIC_CODE.sub("", topic).strip()
        return name or topic

    def start_generation(
        self,
        student_id: uuid.UUID | str,
        *,
        subject_code: str,
        origin: DeckOrigin,
        count: int,
        topic: str | None = None,
        title: str | None = None,
    ) -> DeckSummary:
        """Resolve the topic and save an empty ``writing`` deck. No model call happens here.

        The caller schedules :meth:`run_generation` (the route does it after the response), so
        the student can leave the screen while the cards are written.

        Raises:
            FlashcardGenerationUnavailableError: no generator was wired in (checked first).
            FlashcardValidationError: ``origin=manual`` or a topic mismatch.
            FlashcardUnavailableError: weakness origin with no recorded weaknesses.
        """
        if self._generator is None:
            raise FlashcardGenerationUnavailableError(
                "FlashcardService was constructed with no FlashcardGenerator"
            )
        if origin == DeckOrigin.manual:
            raise FlashcardValidationError("origin='manual' has no AI content to generate")
        student_uuid = _as_uuid(student_id)
        resolved_topic = self._resolve_deck_topic(student_uuid, subject_code, origin, topic)
        if resolved_topic is None:
            raise FlashcardValidationError("could not resolve a topic to generate for")
        with self._sessionmaker() as session, session.begin():
            deck = FlashcardDeck(
                user_id=student_uuid,
                subject_code=subject_code,
                topic=resolved_topic,
                title=(title or "").strip() or self._default_title(resolved_topic),
                description=None,
                origin=origin,
                generation_status=DeckGenerationStatus.writing.value,
                requested_count=count,
                generation_started_at=self._now(),
                generation_error=None,
            )
            session.add(deck)
            session.flush()
            return self._to_summary(deck, _DeckCounts.empty(), marks_lost=None)

    def run_generation(self, deck_id: uuid.UUID | str) -> None:
        """Write the cards for a ``writing`` deck, then mark it ``ready`` or ``failed``.

        Never raises: it runs after the HTTP response, where an exception would only reach a
        log. A deck that is no longer ``writing`` (deleted, or already finished) is left alone.
        """
        deck_uuid = _as_uuid(deck_id)
        with self._sessionmaker() as session:
            deck = session.get(FlashcardDeck, deck_uuid)
            if deck is None or deck.generation_status != DeckGenerationStatus.writing.value:
                return
            subject_code, topic, count = deck.subject_code, deck.topic, deck.requested_count or 0
        if self._generator is None or topic is None or count < 1:
            self._mark_failed(deck_uuid, "unavailable")
            return
        try:
            generated = self._generator.generate(
                subject_code=subject_code, topic=topic, count=count
            )
        except Exception:  # any model or parse failure is a failed deck, never a crash
            log.exception("flashcard_generation_failed", deck_id=str(deck_uuid))
            self._mark_failed(deck_uuid, "model_error")
            return
        if not generated.cards:
            self._mark_failed(deck_uuid, "no_cards")
            return
        moment = self._now()
        with self._sessionmaker() as session, session.begin():
            deck = session.get(FlashcardDeck, deck_uuid)
            if deck is None or deck.generation_status != DeckGenerationStatus.writing.value:
                return
            for position, card in enumerate(generated.cards, start=1):
                sched = initial_schedule(moment)
                session.add(
                    Flashcard(
                        deck_id=deck.id,
                        front=card.front,
                        back=card.back,
                        position=position,
                        source=CardSource.ai,
                        source_question_id=card.source_question_id,
                        repetitions=sched.repetitions,
                        ease_factor=sched.ease_factor,
                        interval_days=sched.interval_days,
                        lapses=sched.lapses,
                        due_at=sched.due_at,
                        last_reviewed_at=sched.last_reviewed_at,
                    )
                )
            deck.generation_status = DeckGenerationStatus.ready.value
            deck.generation_error = None
        log.info(
            "flashcard_generation_ready",
            deck_id=str(deck_uuid),
            requested=count,
            generated=len(generated.cards),
        )

    def _mark_failed(self, deck_uuid: uuid.UUID, error: str) -> None:
        with self._sessionmaker() as session, session.begin():
            deck = session.get(FlashcardDeck, deck_uuid)
            if deck is not None and deck.generation_status == DeckGenerationStatus.writing.value:
                deck.generation_status = DeckGenerationStatus.failed.value
                deck.generation_error = error

    def generation_status(
        self, student_id: uuid.UUID | str, deck_id: uuid.UUID | str
    ) -> GenerationState:
        """The deck's writing status. A ``writing`` deck past :data:`GENERATION_STALE_AFTER` is
        saved as ``failed`` (``timeout``) first, so the list and this endpoint agree.
        """
        student_uuid = _as_uuid(student_id)
        deck_uuid = _as_uuid(deck_id)
        moment = self._now()
        with self._sessionmaker() as session, session.begin():
            deck = self._owned_deck(session, student_uuid, deck_uuid)
            if (
                deck.generation_status == DeckGenerationStatus.writing.value
                and deck.generation_started_at is not None
                and moment - deck.generation_started_at > GENERATION_STALE_AFTER
            ):
                deck.generation_status = DeckGenerationStatus.failed.value
                deck.generation_error = "timeout"
            generated = session.scalar(
                select(func.count()).select_from(Flashcard).where(Flashcard.deck_id == deck.id)
            )
            return GenerationState(
                deck_id=deck.id,
                status=DeckGenerationStatus(deck.generation_status),
                requested_count=deck.requested_count,
                generated_count=int(generated or 0),
                error=deck.generation_error,
            )

    def retry_generation(
        self, student_id: uuid.UUID | str, deck_id: uuid.UUID | str
    ) -> GenerationState:
        """Put a ``failed`` deck back to ``writing``. The caller schedules :meth:`run_generation`.

        Raises:
            FlashcardValidationError: the deck is not failed (ready, or still writing).
        """
        state = self.generation_status(student_id, deck_id)
        if state.status != DeckGenerationStatus.failed:
            raise FlashcardValidationError("only a deck whose writing failed can be retried")
        with self._sessionmaker() as session, session.begin():
            deck = self._owned_deck(session, _as_uuid(student_id), _as_uuid(deck_id))
            deck.generation_status = DeckGenerationStatus.writing.value
            deck.generation_started_at = self._now()
            deck.generation_error = None
        return GenerationState(
            deck_id=state.deck_id,
            status=DeckGenerationStatus.writing,
            requested_count=state.requested_count,
            generated_count=state.generated_count,
            error=None,
        )

    def generate_deck(
        self,
        student_id: uuid.UUID | str,
        *,
        subject_code: str,
        origin: DeckOrigin,
        count: int,
        topic: str | None = None,
        title: str | None = None,
    ) -> GeneratedDeckResult:
        """Synchronous generation: :meth:`start_generation`, then :meth:`run_generation`.

        Kept for scripts and tests. ``generated_count`` is the real persisted count, never padded.
        """
        deck = self.start_generation(
            student_id,
            subject_code=subject_code,
            origin=origin,
            count=count,
            topic=topic,
            title=title,
        )
        self.run_generation(deck.id)
        [summary] = [d for d in self.list_decks(student_id) if d.id == deck.id]
        return GeneratedDeckResult(
            deck=summary, requested_count=count, generated_count=summary.card_count
        )
```

Add `"GENERATION_STALE_AFTER"` and `"GenerationState"` to `__all__`.

- [ ] **Step 4: Run the whole repo test file**

Run: `PYTHONPATH=$WT /home/sico/Code/Lemely/.venv/bin/python -m pytest tests/test_flashcard_repo.py -q`
Expected: PASS. That includes the P4.6 `generate_deck` tests, which now go through start + run.

- [ ] **Step 5: Commit**

```bash
pre-commit run --files lemely/db/flashcard_repo.py tests/test_flashcard_repo.py
git commit -S -m "feat(flashcards): background deck generation with a status (L10)" -- lemely/db/flashcard_repo.py tests/test_flashcard_repo.py
```

---

### Task 4: Schemas and routes

**Files:**
- Modify: `lemely/web/schemas_flashcards.py`, `lemely/web/routers/flashcards.py`
- Modify: `tests/test_authz_matrix_complete.py` (four rows)
- Test: `tests/test_web_flashcards.py` (update the two generate tests; append a section)

**Interfaces:**
- Consumes: Tasks 2–3 service API.
- Produces (wire contract for Task 5):
  - `CardDTO` + `nextIntervalDays: {again, hard, good, easy}`
  - `DeckSummaryDTO` + `newCount`, `learningCount`, `knownCount`, `marksLost: int | null`, `generationStatus`, `requestedCount: int | null`
  - `DeckDetailDTO` + `dueCount`, the same mastery fields, `marksLost`, `generationStatus`, `requestedCount`
  - `DueSessionDTO` + `upcoming: list[str]`, `againDelayMinutes: int`
  - `ReviewResultDTO` + `xpAwarded: int`
  - new `RenameDeckRequestDTO {title}`, `GenerationStatusDTO {deckId, status, requestedCount, generatedCount, error}`, `WeakTopicDTO {subjectCode, topic, marksLost, accuracyPct}`
  - `POST /decks/generate` → **202** with `GenerateDeckResponseDTO` (`deck.generationStatus="writing"`, `generatedCount=0`)
  - `GET /decks/{id}/generation` → `GenerationStatusDTO`
  - `POST /decks/{id}/generation/retry` → 202 `GenerationStatusDTO`
  - `PATCH /decks/{id}` → `DeckSummaryDTO`
  - `GET /weak-topics?subject_code=&limit=` → `list[WeakTopicDTO]`
  - `GET /due?subject_code=&deck_id=&limit=`

- [ ] **Step 1: Write the failing route tests**

Update the two existing generate tests in `tests/test_web_flashcards.py`. Starlette's `TestClient` runs background tasks before `client.post` returns, so the deck is finished when the test reads it.

```python
def test_generated_cards_are_marked_ai_on_the_wire(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student = _seed_user(pg_sessionmaker)
    generator = _mock_generator(
        [
            GeneratedFlashcard(front="What is current?", back="Rate of flow of charge"),
            GeneratedFlashcard(front="Unit of current?", back="Ampere"),
        ],
        topic="4.3 Circuits",
    )
    service = FlashcardService(pg_sessionmaker, generator, now=lambda: _FIXED_NOW)
    _use_service(client, service)
    _auth_as(client, student)

    response = client.post(
        "/api/student/flashcards/decks/generate",
        json={"subjectCode": "0625", "origin": "topic", "topic": "4.3 Circuits", "count": 2},
    )
    assert response.status_code == 202
    assert response.json()["deck"]["generationStatus"] == "writing"
    deck_id = response.json()["deck"]["id"]

    cards = client.get(f"/api/student/flashcards/decks/{deck_id}").json()["cards"]
    assert [c["source"] for c in cards] == ["ai", "ai"]


def test_a_short_generation_reports_the_true_count_never_the_requested_one(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student = _seed_user(pg_sessionmaker)
    generator = _mock_generator(
        [GeneratedFlashcard(front="Only one", back="card")], topic="4.3 Circuits"
    )
    service = FlashcardService(pg_sessionmaker, generator, now=lambda: _FIXED_NOW)
    _use_service(client, service)
    _auth_as(client, student)

    started = client.post(
        "/api/student/flashcards/decks/generate",
        json={"subjectCode": "0625", "origin": "topic", "topic": "4.3 Circuits", "count": 10},
    ).json()
    assert started["requestedCount"] == 10
    assert started["generatedCount"] == 0

    status = client.get(
        f"/api/student/flashcards/decks/{started['deck']['id']}/generation"
    ).json()
    assert status == {
        "deckId": started["deck"]["id"],
        "status": "ready",
        "requestedCount": 10,
        "generatedCount": 1,
        "error": None,
    }
```

Append:

```python
# ---------------------------------------------------------------------------
# Redesign L10 routes.
# ---------------------------------------------------------------------------


def _deck_with_cards(client: TestClient, n: int, title: str = "Deck") -> str:
    deck_id = client.post(
        "/api/student/flashcards/decks", json={"subjectCode": "0625", "title": title}
    ).json()["id"]
    for i in range(n):
        client.post(
            f"/api/student/flashcards/decks/{deck_id}/cards", json={"front": f"Q{i}", "back": "A"}
        )
    return deck_id


def test_deck_summary_carries_mastery_and_generation_fields(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], flashcard_service: FlashcardService
) -> None:
    student = _seed_user(pg_sessionmaker)
    _use_service(client, flashcard_service)
    _auth_as(client, student)
    _deck_with_cards(client, 2)

    [deck] = client.get("/api/student/flashcards/decks").json()
    assert (deck["newCount"], deck["learningCount"], deck["knownCount"]) == (2, 0, 0)
    assert deck["generationStatus"] == "ready"
    assert deck["requestedCount"] is None
    assert deck["marksLost"] is None


def test_rename_a_deck_and_reject_a_blank_title(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], flashcard_service: FlashcardService
) -> None:
    student = _seed_user(pg_sessionmaker)
    _use_service(client, flashcard_service)
    _auth_as(client, student)
    deck_id = _deck_with_cards(client, 0)

    renamed = client.patch(f"/api/student/flashcards/decks/{deck_id}", json={"title": " Vectors "})
    assert renamed.status_code == 200
    assert renamed.json()["title"] == "Vectors"
    assert client.patch(
        f"/api/student/flashcards/decks/{deck_id}", json={"title": "  "}
    ).status_code == 422


def test_rename_someone_elses_deck_is_404(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], flashcard_service: FlashcardService
) -> None:
    owner = _seed_user(pg_sessionmaker)
    other = _seed_user(pg_sessionmaker)
    _use_service(client, flashcard_service)
    _auth_as(client, owner)
    deck_id = _deck_with_cards(client, 0)
    _auth_as(client, other)
    assert client.patch(
        f"/api/student/flashcards/decks/{deck_id}", json={"title": "Mine"}
    ).status_code == 404
    assert client.get(f"/api/student/flashcards/decks/{deck_id}/generation").status_code == 404
    assert client.get(f"/api/student/flashcards/due?deck_id={deck_id}").status_code == 404


def test_weak_topics_route_ranks_by_marks_lost(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], flashcard_service: FlashcardService
) -> None:
    student = _seed_user(pg_sessionmaker)
    _seed_weakness(pg_sessionmaker, student, topic="3 Waves", lost_marks=6)
    _seed_weakness(pg_sessionmaker, student, topic="1 Motion", lost_marks=3)
    _use_service(client, flashcard_service)
    _auth_as(client, student)

    body = client.get("/api/student/flashcards/weak-topics?subject_code=0625").json()
    assert body == [
        {"subjectCode": "0625", "topic": "3 Waves", "marksLost": 6, "accuracyPct": 40},
        {"subjectCode": "0625", "topic": "1 Motion", "marksLost": 3, "accuracyPct": 70},
    ]


def test_generate_for_a_chosen_weak_topic(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    student = _seed_user(pg_sessionmaker)
    _seed_weakness(pg_sessionmaker, student, topic="3 Waves", lost_marks=9)
    _seed_weakness(pg_sessionmaker, student, topic="1 Motion", lost_marks=2)
    generator = _mock_generator([GeneratedFlashcard(front="Q", back="A")], topic="1 Motion")
    service = FlashcardService(pg_sessionmaker, generator, now=lambda: _FIXED_NOW)
    _use_service(client, service)
    _auth_as(client, student)

    ok = client.post(
        "/api/student/flashcards/decks/generate",
        json={"subjectCode": "0625", "origin": "weakness", "topic": "1 Motion", "count": 4},
    )
    assert ok.status_code == 202
    assert ok.json()["deck"]["topic"] == "1 Motion"
    not_weak = client.post(
        "/api/student/flashcards/decks/generate",
        json={"subjectCode": "0625", "origin": "weakness", "topic": "9 Space", "count": 4},
    )
    assert not_weak.status_code == 422


def test_a_failed_generation_can_be_retried(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    student = _seed_user(pg_sessionmaker)
    generator = MagicMock()
    generator.generate.side_effect = [
        RuntimeError("down"),
        GeneratedFlashcardDeck(
            subject_code="0625", topic="1 Motion", cards=[GeneratedFlashcard(front="Q", back="A")]
        ),
    ]
    service = FlashcardService(pg_sessionmaker, generator, now=lambda: _FIXED_NOW)
    _use_service(client, service)
    _auth_as(client, student)

    deck_id = client.post(
        "/api/student/flashcards/decks/generate",
        json={"subjectCode": "0625", "origin": "topic", "topic": "1 Motion", "count": 3},
    ).json()["deck"]["id"]
    failed = client.get(f"/api/student/flashcards/decks/{deck_id}/generation").json()
    assert (failed["status"], failed["error"]) == ("failed", "model_error")

    retried = client.post(f"/api/student/flashcards/decks/{deck_id}/generation/retry")
    assert retried.status_code == 202
    assert retried.json()["status"] == "writing"
    after = client.get(f"/api/student/flashcards/decks/{deck_id}/generation").json()
    assert (after["status"], after["generatedCount"]) == ("ready", 1)
    # A ready deck cannot be retried.
    assert client.post(
        f"/api/student/flashcards/decks/{deck_id}/generation/retry"
    ).status_code == 422


def test_due_session_scoped_to_a_deck_with_intervals_and_forecast(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], flashcard_service: FlashcardService
) -> None:
    student = _seed_user(pg_sessionmaker)
    _use_service(client, flashcard_service)
    _auth_as(client, student)
    deck_a = _deck_with_cards(client, 2, "A")
    _deck_with_cards(client, 3, "B")

    body = client.get(f"/api/student/flashcards/due?deck_id={deck_a}").json()
    assert body["totalDue"] == 2
    assert body["againDelayMinutes"] == 10
    assert body["upcoming"] == []
    assert body["cards"][0]["nextIntervalDays"] == {"again": 0, "hard": 1, "good": 1, "easy": 1}
    assert client.get("/api/student/flashcards/due?deck_id=not-a-uuid").status_code == 422


def test_review_reports_the_xp_it_awarded(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], flashcard_service: FlashcardService
) -> None:
    student = _seed_user(pg_sessionmaker)
    _use_service(client, flashcard_service)
    _auth_as(client, student)
    xp = MagicMock()
    xp.award.return_value = MagicMock(awarded=True, amount=2)
    client.app.dependency_overrides[get_xp_service] = lambda: xp  # type: ignore[union-attr]
    deck_id = _deck_with_cards(client, 1)
    card_id = client.get(f"/api/student/flashcards/decks/{deck_id}").json()["cards"][0]["id"]

    body = client.post(
        f"/api/student/flashcards/cards/{card_id}/review", json={"grade": "good"}
    ).json()
    assert body["xpAwarded"] == 2

    xp.award.side_effect = RuntimeError("xp down")
    second = client.post(
        f"/api/student/flashcards/cards/{card_id}/review", json={"grade": "again"}
    ).json()
    assert second["xpAwarded"] == 0  # the review still succeeded
```

Add `get_xp_service` to the `lemely.web.deps` import at the top of the test module.

In `tests/test_authz_matrix_complete.py`, add these rows next to the existing flashcard rows, keeping the block sorted the way it is:

```python
    ("PATCH", "/api/student/flashcards/decks/{deck_id}"): STUDENT,
    ("GET", "/api/student/flashcards/decks/{deck_id}/generation"): STUDENT,
    ("POST", "/api/student/flashcards/decks/{deck_id}/generation/retry"): STUDENT,
    ("GET", "/api/student/flashcards/weak-topics"): STUDENT,
```

- [ ] **Step 2: Run them to see them fail**

Run: `PYTHONPATH=$WT /home/sico/Code/Lemely/.venv/bin/python -m pytest tests/test_web_flashcards.py tests/test_authz_matrix_complete.py -q`
Expected: FAIL. You should see 201 ≠ 202, missing keys, and 405 on PATCH. The authz test fails with "route declared but not wired".

- [ ] **Step 3: Implement the schemas**

In `lemely/web/schemas_flashcards.py`, update `GenerateDeckRequestDTO`'s docstring: `topic` is required for `"topic"`, and optional for `"weakness"`, where it must be one of the caller's recorded weak topics. Then add or extend:

```python
class NextIntervalsDTO(ApiModel):
    """Interval in days each grade would give the card right now. ``again`` is 0: the
    same-session step of ``DueSessionDTO.againDelayMinutes``."""

    again: int
    hard: int
    good: int
    easy: int


class RenameDeckRequestDTO(ApiModel):
    """Body for ``PATCH /api/student/flashcards/decks/{deck_id}``. Trimmed; 1-80 characters."""

    title: str = Field(max_length=200)


class GenerationStatusDTO(ApiModel):
    """Where a generated deck's card writing stands. ``generatedCount`` is the real row count."""

    deckId: str
    status: str
    requestedCount: int | None
    generatedCount: int
    error: str | None


class WeakTopicDTO(ApiModel):
    """One recorded weak topic for the new-deck sheet. ``accuracyPct`` is 0-100."""

    subjectCode: str
    topic: str
    marksLost: int
    accuracyPct: int
```

`CardDTO` gains `nextIntervalDays: NextIntervalsDTO`. `DeckSummaryDTO` gains:

```python
    newCount: int
    learningCount: int
    knownCount: int
    marksLost: int | None
    generationStatus: str
    requestedCount: int | None
```

`DeckDetailDTO` gains `dueCount: int` and the same six fields, all declared before `cards`. `DueSessionDTO` gains `upcoming: list[str] = Field(default_factory=list)` and `againDelayMinutes: int`. `ReviewResultDTO` gains `xpAwarded: int = 0`.

- [ ] **Step 4: Implement the routes**

In `lemely/web/routers/flashcards.py`:
- Import `BackgroundTasks` from fastapi.
- Import the new DTOs.
- Under `TYPE_CHECKING`, import `GenerationState` and `WeakTopic` from the repo.

Update the converters:

```python
def _card_to_dto(card: CardView) -> CardDTO:
    return CardDTO(
        id=str(card.id),
        front=card.front,
        back=card.back,
        position=card.position,
        source=card.source.value,
        sourceQuestionId=card.source_question_id,
        repetitions=card.repetitions,
        easeFactor=card.ease_factor,
        intervalDays=card.interval_days,
        lapses=card.lapses,
        dueAt=card.due_at.isoformat(),
        lastReviewedAt=card.last_reviewed_at.isoformat() if card.last_reviewed_at else None,
        nextIntervalDays=NextIntervalsDTO(**card.next_interval_days),
    )


def _summary_to_dto(deck: DeckSummary) -> DeckSummaryDTO:
    return DeckSummaryDTO(
        id=str(deck.id),
        subjectCode=deck.subject_code,
        topic=deck.topic,
        title=deck.title,
        description=deck.description,
        origin=deck.origin.value,
        cardCount=deck.card_count,
        dueCount=deck.due_count,
        createdAt=deck.created_at.isoformat(),
        newCount=deck.mastery.new,
        learningCount=deck.mastery.learning,
        knownCount=deck.mastery.known,
        marksLost=deck.marks_lost,
        generationStatus=deck.generation_status.value,
        requestedCount=deck.requested_count,
    )


def _detail_to_dto(deck: DeckDetail) -> DeckDetailDTO:
    return DeckDetailDTO(
        id=str(deck.id),
        subjectCode=deck.subject_code,
        topic=deck.topic,
        title=deck.title,
        description=deck.description,
        origin=deck.origin.value,
        dueCount=deck.due_count,
        newCount=deck.mastery.new,
        learningCount=deck.mastery.learning,
        knownCount=deck.mastery.known,
        marksLost=deck.marks_lost,
        generationStatus=deck.generation_status.value,
        requestedCount=deck.requested_count,
        cards=[_card_to_dto(c) for c in deck.cards],
    )


def _generation_to_dto(state: GenerationState) -> GenerationStatusDTO:
    return GenerationStatusDTO(
        deckId=str(state.deck_id),
        status=state.status.value,
        requestedCount=state.requested_count,
        generatedCount=state.generated_count,
        error=state.error,
    )


def _session_to_dto(session: DueSession) -> DueSessionDTO:
    return DueSessionDTO(
        cards=[_card_to_dto(c) for c in session.cards],
        totalDue=session.total_due,
        nextDueAt=session.next_due_at.isoformat() if session.next_due_at else None,
        upcoming=[d.isoformat() for d in session.upcoming],
        againDelayMinutes=session.again_delay_minutes,
    )


def _review_to_dto(outcome: ReviewOutcome, xp_awarded: int) -> ReviewResultDTO:
    return ReviewResultDTO(
        card=_card_to_dto(outcome.card),
        reviewId=str(outcome.review_id),
        grade=outcome.grade.value,
        intervalBeforeDays=outcome.interval_before_days,
        intervalAfterDays=outcome.interval_after_days,
        xpAwarded=xp_awarded,
    )
```

Delete `_generated_to_dto`; `GeneratedDeckResult` is no longer used here. Replace the generate route and add the new routes. `/weak-topics` and the two `/generation` routes are literal or deeper paths, so order does not matter for them. Keep `/decks/generate` declared before `/decks/{deck_id}`, as now.

```python
@router.get("/weak-topics", response_model=list[WeakTopicDTO])
def weak_topics(
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    service: Annotated[FlashcardService, Depends(get_flashcard_service)],
    subject_code: str | None = None,
    limit: Annotated[int, Query(ge=1, le=20)] = 6,
) -> list[WeakTopicDTO]:
    """The caller's recorded weak topics, most marks lost first (new-deck sheet chips)."""
    return [
        WeakTopicDTO(
            subjectCode=t.subject_code,
            topic=t.topic,
            marksLost=t.marks_lost,
            accuracyPct=t.accuracy_pct,
        )
        for t in service.weak_topics(auth.user_id, subject_code=subject_code, limit=limit)
    ]


@router.post("/decks/generate", response_model=GenerateDeckResponseDTO, status_code=202)
def generate_deck(
    body: GenerateDeckRequestDTO,
    background: BackgroundTasks,
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    service: Annotated[FlashcardService, Depends(get_flashcard_service)],
) -> GenerateDeckResponseDTO:
    """Start writing an AI deck and return at once (202). Poll ``GET .../generation``.

    The deck is saved as ``writing`` before the response; the model call runs after it, so the
    student can leave. ``generatedCount`` here is 0. The real, never-padded count comes from the
    status endpoint once the deck is ``ready``. 409/422/503 refusals still happen up front.
    """
    try:
        deck = service.start_generation(
            auth.user_id,
            subject_code=body.subjectCode,
            origin=_parse_origin(body.origin),
            count=body.count,
            topic=body.topic,
            title=body.title,
        )
    except FlashcardError as exc:
        _raise_for(exc)
    background.add_task(service.run_generation, deck.id)
    return GenerateDeckResponseDTO(
        deck=_summary_to_dto(deck), requestedCount=body.count, generatedCount=0
    )


@router.patch("/decks/{deck_id}", response_model=DeckSummaryDTO)
def rename_deck(
    deck_id: str,
    body: RenameDeckRequestDTO,
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    service: Annotated[FlashcardService, Depends(get_flashcard_service)],
) -> DeckSummaryDTO:
    """Rename one of the caller's decks. Blank or over 80 characters is 422."""
    try:
        deck = service.rename_deck(auth.user_id, deck_id, title=body.title)
    except FlashcardError as exc:
        _raise_for(exc)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _summary_to_dto(deck)


@router.get("/decks/{deck_id}/generation", response_model=GenerationStatusDTO)
def generation_status(
    deck_id: str,
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    service: Annotated[FlashcardService, Depends(get_flashcard_service)],
) -> GenerationStatusDTO:
    """Where the deck's card writing stands (``writing`` / ``ready`` / ``failed``)."""
    try:
        state = service.generation_status(auth.user_id, deck_id)
    except FlashcardError as exc:
        _raise_for(exc)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _generation_to_dto(state)


@router.post(
    "/decks/{deck_id}/generation/retry", response_model=GenerationStatusDTO, status_code=202
)
def retry_generation(
    deck_id: str,
    background: BackgroundTasks,
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    service: Annotated[FlashcardService, Depends(get_flashcard_service)],
) -> GenerationStatusDTO:
    """Write a failed deck's cards again. A deck that is not failed is 422."""
    try:
        state = service.retry_generation(auth.user_id, deck_id)
    except FlashcardError as exc:
        _raise_for(exc)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    background.add_task(service.run_generation, state.deck_id)
    return _generation_to_dto(state)
```

Replace `due_session`:

```python
@router.get("/due", response_model=DueSessionDTO)
def due_session(
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    service: Annotated[FlashcardService, Depends(get_flashcard_service)],
    subject_code: str | None = None,
    deck_id: str | None = None,
    limit: Annotated[int | None, Query(ge=1)] = None,
) -> DueSessionDTO:
    """S-22/S-23: due cards, the backlog size, the next due time and the 8-day forecast.

    ``deck_id`` narrows to one of the caller's decks (another student's deck is a 404). An
    empty ``cards`` list is a real state carrying ``nextDueAt``. ``limit`` is ``ge=1`` because
    it reaches SQL as a bare ``LIMIT``.
    """
    try:
        session = service.due_session(
            auth.user_id, subject_code=subject_code, deck_id=deck_id, limit=limit
        )
    except FlashcardError as exc:
        _raise_for(exc)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _session_to_dto(session)
```

In `review_card`, capture the award and pass its amount:

```python
    award = award_xp_safely(
        xp_service,
        user_id=auth.user_id,
        source=XpSource.flashcard_reviewed,
        dedupe_key=str(outcome.review_id),
        subject_code=outcome.subject_code,
        seam="flashcard_reviewed",
    )
    xp_awarded = award.amount if award is not None and award.awarded else 0
    return _review_to_dto(outcome, xp_awarded)
```

- [ ] **Step 5: Run the route, authz and repo tests**

Run: `PYTHONPATH=$WT /home/sico/Code/Lemely/.venv/bin/python -m pytest tests/test_web_flashcards.py tests/test_authz_matrix_complete.py tests/test_flashcard_repo.py -q`
Expected: PASS.

- [ ] **Step 6: Check the e2e seed still works with the service changes**

`scripts/seed_e2e.py` calls `create_deck`, `add_card`, `record_review` and `due_session`. All keep their signatures. Run `PYTHONPATH=$WT /home/sico/Code/Lemely/.venv/bin/python -m pytest tests/ -q -k "seed_e2e"` if such a test exists (`ls tests | grep seed`). Otherwise read lines 3255-3305 of the script and confirm nothing there reads a removed field.

- [ ] **Step 7: Commit**

```bash
pre-commit run --files lemely/web/schemas_flashcards.py lemely/web/routers/flashcards.py tests/test_web_flashcards.py tests/test_authz_matrix_complete.py
git commit -S -m "feat(flashcards): rename, weak topics, generation status and due scope routes (L10)" -- lemely/web/schemas_flashcards.py lemely/web/routers/flashcards.py tests/test_web_flashcards.py tests/test_authz_matrix_complete.py
```

---

## Frontend data layer

### Task 5: Wire types, typed API functions, query keys and hooks

**Files:**
- Modify: `web/src/lib/flashcardTypes.ts`
- Create: `web/src/lib/flashcardApi.ts`
- Rewrite: `web/src/lib/hooks/useFlashcardApi.ts`
- Test: `web/tests/unit/flashcardApi.test.ts`

**Interfaces:**
- Consumes: the Task 4 wire contract.
- Produces:
  - `flashcardKeys`, `decksUrl`, `dueUrl`, `weakTopicsUrl`, `flashcardApi.*` from `@/lib/flashcardApi`
  - hooks:
    - `useFlashcardDecks(subjectCode?)`, `useFlashcardDeck(deckId)`, `useDueSession(scope: DueScope)`, `useWeakTopics(subjectCode?)`
    - `useGenerationStatus(deckId, enabled)`, `useCreateDeck()`, `useRenameDeck()`, `useDeleteDeck()`, `useGenerateDeck()`, `useRetryGeneration()`
    - `useAddCard(deckId)`, `useEditCard(deckId)`, `useDeleteCard(deckId)`, `useReviewCard()`

- [ ] **Step 1: Extend the wire types**

Append to `web/src/lib/flashcardTypes.ts` and edit the existing interfaces as shown. Keep the existing doc comments.

```ts
/** Where an AI deck's card writing stands. Every manual deck is `"ready"`. */
export type DeckGenerationStatus = "writing" | "ready" | "failed"

/** Interval in days each grade would give the card right now. `again` is 0: the
 * same-session step of `DueSessionDTO.againDelayMinutes`. */
export interface NextIntervals {
  again: number
  hard: number
  good: number
  easy: number
}

/** Body for `PATCH /api/student/flashcards/decks/{deckId}`. */
export interface RenameDeckRequest {
  title: string
}

/** `GET /api/student/flashcards/decks/{deckId}/generation`. `generatedCount` is the real
 * row count, never padded to `requestedCount`. */
export interface GenerationStatusDTO {
  deckId: string
  status: DeckGenerationStatus
  requestedCount: number | null
  generatedCount: number
  error: string | null
}

/** One recorded weak topic (new-deck sheet chips). `accuracyPct` is 0-100. */
export interface WeakTopicDTO {
  subjectCode: string
  topic: string
  marksLost: number
  accuracyPct: number
}
```

Edits:
- `CardDTO` gains `nextIntervalDays: NextIntervals`.
- `DeckSummaryDTO` gains `newCount: number`, `learningCount: number`, `knownCount: number`, `marksLost: number | null`, `generationStatus: DeckGenerationStatus` and `requestedCount: number | null`.
- `DeckDetailDTO` gains `dueCount: number` plus the same six fields.
- `DueSessionDTO` gains `upcoming: string[]` and `againDelayMinutes: number`.
- `ReviewResultDTO` gains `xpAwarded: number`.
- `GenerateDeckRequest`'s comment changes: `topic` is required for `"topic"` and optional for `"weakness"`, where it must be a recorded weak topic.

- [ ] **Step 2: Write the failing test**

```ts
// web/tests/unit/flashcardApi.test.ts
import { describe, expect, it } from "vitest"
import { decksUrl, dueUrl, flashcardKeys, weakTopicsUrl } from "@/lib/flashcardApi"
import { isPersistableQueryKey } from "@/lib/offline/persistAllowlist"

describe("flashcard URL builders", () => {
  it("lists every deck, or one subject's", () => {
    expect(decksUrl()).toBe("/student/flashcards/decks")
    expect(decksUrl("0580")).toBe("/student/flashcards/decks?subject_code=0580")
  })

  it("scopes the due session by subject, deck and limit, encoding values", () => {
    expect(dueUrl({})).toBe("/student/flashcards/due")
    expect(dueUrl({ subjectCode: "0580", deckId: "d 1", limit: 20 })).toBe(
      "/student/flashcards/due?subject_code=0580&deck_id=d+1&limit=20",
    )
  })

  it("asks for weak topics across subjects or for one", () => {
    expect(weakTopicsUrl()).toBe("/student/flashcards/weak-topics")
    expect(weakTopicsUrl("0625")).toBe("/student/flashcards/weak-topics?subject_code=0625")
  })
})

describe("flashcard query keys", () => {
  it("keeps the decks list persistable offline and the rest not", () => {
    expect(isPersistableQueryKey(flashcardKeys.decks())).toBe(true)
    expect(isPersistableQueryKey(flashcardKeys.decks("0580"))).toBe(true)
    expect(isPersistableQueryKey(flashcardKeys.deck("d1"))).toBe(false)
    expect(isPersistableQueryKey(flashcardKeys.due({}))).toBe(false)
    expect(isPersistableQueryKey(flashcardKeys.generation("d1"))).toBe(false)
  })

  it("nests every scoped key under its root so one invalidation reaches them all", () => {
    expect(flashcardKeys.decks("0580").slice(0, 2)).toEqual([...flashcardKeys.decksRoot])
    expect(flashcardKeys.due({ deckId: "d1" }).slice(0, 2)).toEqual([...flashcardKeys.dueRoot])
  })
})
```

- [ ] **Step 3: Run it to see it fail**

Run: `cd $WT/web && npx vitest run tests/unit/flashcardApi.test.ts`
Expected: FAIL. Vitest reports it cannot resolve `@/lib/flashcardApi`.

- [ ] **Step 4: Write `flashcardApi.ts`**

```ts
// web/src/lib/flashcardApi.ts
import { request } from "@/lib/api"
import type {
  AddCardRequest,
  CardDTO,
  CreateDeckRequest,
  DeckDetailDTO,
  DeckSummaryDTO,
  DueSessionDTO,
  EditCardRequest,
  GenerateDeckRequest,
  GenerateDeckResponseDTO,
  GenerationStatusDTO,
  RenameDeckRequest,
  ReviewGrade,
  ReviewResultDTO,
  WeakTopicDTO,
} from "@/lib/flashcardTypes"

/*
 * L10 · typed calls to `/api/student/flashcards/*`, plus the URL builders and query keys
 * the hooks share. Pure apart from `request()`, so the builders are unit-testable.
 */

export interface DueScope {
  subjectCode?: string | null
  deckId?: string | null
  limit?: number | null
}

function withQuery(path: string, params: Record<string, string | number | null | undefined>): string {
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined && value !== "") query.set(key, String(value))
  }
  const qs = query.toString()
  return qs ? `${path}?${qs}` : path
}

export function decksUrl(subjectCode?: string | null): string {
  return withQuery("/student/flashcards/decks", { subject_code: subjectCode })
}

export function dueUrl(scope: DueScope): string {
  return withQuery("/student/flashcards/due", {
    subject_code: scope.subjectCode,
    deck_id: scope.deckId,
    limit: scope.limit,
  })
}

export function weakTopicsUrl(subjectCode?: string | null): string {
  return withQuery("/student/flashcards/weak-topics", { subject_code: subjectCode })
}

/** Query keys. `["flashcards","decks"]` stays the persisted prefix (persistAllowlist.ts). */
export const flashcardKeys = {
  decksRoot: ["flashcards", "decks"] as const,
  dueRoot: ["flashcards", "due"] as const,
  decks: (subjectCode?: string | null) => ["flashcards", "decks", subjectCode ?? null] as const,
  deck: (deckId: string) => ["flashcards", "deck", deckId] as const,
  due: (scope: DueScope) =>
    ["flashcards", "due", scope.subjectCode ?? null, scope.deckId ?? null, scope.limit ?? null] as const,
  weakTopics: (subjectCode?: string | null) => ["flashcards", "weak-topics", subjectCode ?? null] as const,
  generation: (deckId: string) => ["flashcards", "generation", deckId] as const,
}

const json = (method: string, body?: unknown): RequestInit => ({
  method,
  ...(body === undefined ? {} : { body: JSON.stringify(body) }),
})

export const flashcardApi = {
  listDecks: (subjectCode?: string | null) => request<DeckSummaryDTO[]>(decksUrl(subjectCode)),
  getDeck: (deckId: string) => request<DeckDetailDTO>(`/student/flashcards/decks/${deckId}`),
  createDeck: (body: CreateDeckRequest) =>
    request<DeckSummaryDTO>("/student/flashcards/decks", json("POST", body)),
  renameDeck: (deckId: string, body: RenameDeckRequest) =>
    request<DeckSummaryDTO>(`/student/flashcards/decks/${deckId}`, json("PATCH", body)),
  deleteDeck: (deckId: string) => request<void>(`/student/flashcards/decks/${deckId}`, json("DELETE")),
  generateDeck: (body: GenerateDeckRequest) =>
    request<GenerateDeckResponseDTO>("/student/flashcards/decks/generate", json("POST", body)),
  generationStatus: (deckId: string) =>
    request<GenerationStatusDTO>(`/student/flashcards/decks/${deckId}/generation`),
  retryGeneration: (deckId: string) =>
    request<GenerationStatusDTO>(`/student/flashcards/decks/${deckId}/generation/retry`, json("POST")),
  addCard: (deckId: string, body: AddCardRequest) =>
    request<CardDTO>(`/student/flashcards/decks/${deckId}/cards`, json("POST", body)),
  editCard: (cardId: string, body: EditCardRequest) =>
    request<CardDTO>(`/student/flashcards/cards/${cardId}`, json("PATCH", body)),
  deleteCard: (cardId: string) => request<void>(`/student/flashcards/cards/${cardId}`, json("DELETE")),
  dueSession: (scope: DueScope) => request<DueSessionDTO>(dueUrl(scope)),
  reviewCard: (cardId: string, grade: ReviewGrade) =>
    request<ReviewResultDTO>(`/student/flashcards/cards/${cardId}/review`, json("POST", { grade })),
  weakTopics: (subjectCode?: string | null) => request<WeakTopicDTO[]>(weakTopicsUrl(subjectCode)),
}
```

- [ ] **Step 5: Rewrite the hooks**

```ts
// web/src/lib/hooks/useFlashcardApi.ts
import { useEffect, useRef } from "react"
import {
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query"
import { flashcardApi, flashcardKeys, type DueScope } from "@/lib/flashcardApi"
import type {
  AddCardRequest,
  CardDTO,
  CreateDeckRequest,
  DeckDetailDTO,
  DeckSummaryDTO,
  DueSessionDTO,
  EditCardRequest,
  GenerateDeckRequest,
  GenerateDeckResponseDTO,
  GenerationStatusDTO,
  ReviewGrade,
  ReviewResultDTO,
  WeakTopicDTO,
} from "@/lib/flashcardTypes"

/*
 * React-query hooks for `/api/student/flashcards/*` (L10). No `fallback` on any request: a
 * real failure surfaces as an error the screen renders, never as silently empty data.
 */

/** Poll while a generated deck is writing. */
export const GENERATION_POLL_MS = 2000
const DECKS_POLL_MS = 4000

function invalidateDeckLists(queryClient: QueryClient) {
  void queryClient.invalidateQueries({ queryKey: flashcardKeys.decksRoot })
  void queryClient.invalidateQueries({ queryKey: flashcardKeys.dueRoot })
}

/** Every deck, or one subject's. Polls while any deck is still writing. */
export function useFlashcardDecks(subjectCode?: string | null): UseQueryResult<DeckSummaryDTO[], Error> {
  return useQuery({
    queryKey: flashcardKeys.decks(subjectCode),
    queryFn: () => flashcardApi.listDecks(subjectCode),
    refetchInterval: (query) =>
      query.state.data?.some((d) => d.generationStatus === "writing") ? DECKS_POLL_MS : false,
  })
}

export function useFlashcardDeck(deckId: string): UseQueryResult<DeckDetailDTO, Error> {
  return useQuery({
    queryKey: flashcardKeys.deck(deckId),
    queryFn: () => flashcardApi.getDeck(deckId),
    enabled: !!deckId,
  })
}

export function useDueSession(scope: DueScope): UseQueryResult<DueSessionDTO, Error> {
  return useQuery({
    queryKey: flashcardKeys.due(scope),
    queryFn: () => flashcardApi.dueSession(scope),
  })
}

export function useWeakTopics(subjectCode?: string | null): UseQueryResult<WeakTopicDTO[], Error> {
  return useQuery({
    queryKey: flashcardKeys.weakTopics(subjectCode),
    queryFn: () => flashcardApi.weakTopics(subjectCode),
    staleTime: 60_000,
  })
}

/**
 * The writing status of one generated deck. It polls every 2 s while the deck is `writing`.
 * When the deck leaves `writing`, it refreshes the deck, the lists and the due session once.
 */
export function useGenerationStatus(
  deckId: string,
  enabled: boolean,
): UseQueryResult<GenerationStatusDTO, Error> {
  const queryClient = useQueryClient()
  const query = useQuery({
    queryKey: flashcardKeys.generation(deckId),
    queryFn: () => flashcardApi.generationStatus(deckId),
    enabled: enabled && !!deckId,
    refetchInterval: (q) => (q.state.data?.status === "writing" ? GENERATION_POLL_MS : false),
  })
  const previous = useRef<string | undefined>(undefined)
  const status = query.data?.status
  useEffect(() => {
    if (previous.current === "writing" && status && status !== "writing") {
      void queryClient.invalidateQueries({ queryKey: flashcardKeys.deck(deckId) })
      invalidateDeckLists(queryClient)
    }
    previous.current = status
  }, [status, deckId, queryClient])
  return query
}

export function useCreateDeck(): UseMutationResult<DeckSummaryDTO, Error, CreateDeckRequest> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body) => flashcardApi.createDeck(body),
    onSuccess: () => invalidateDeckLists(queryClient),
  })
}

export function useRenameDeck(): UseMutationResult<DeckSummaryDTO, Error, { deckId: string; title: string }> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ deckId, title }) => flashcardApi.renameDeck(deckId, { title }),
    onSuccess: (_deck, { deckId }) => {
      void queryClient.invalidateQueries({ queryKey: flashcardKeys.deck(deckId) })
      invalidateDeckLists(queryClient)
    },
  })
}

export function useDeleteDeck(): UseMutationResult<void, Error, string> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (deckId) => flashcardApi.deleteDeck(deckId),
    onSuccess: (_v, deckId) => {
      queryClient.removeQueries({ queryKey: flashcardKeys.deck(deckId) })
      invalidateDeckLists(queryClient)
    },
  })
}

/** Starts writing an AI deck (202). The returned deck is `writing`; poll `useGenerationStatus`. */
export function useGenerateDeck(): UseMutationResult<GenerateDeckResponseDTO, Error, GenerateDeckRequest> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body) => flashcardApi.generateDeck(body),
    onSuccess: () => invalidateDeckLists(queryClient),
  })
}

export function useRetryGeneration(): UseMutationResult<GenerationStatusDTO, Error, string> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (deckId) => flashcardApi.retryGeneration(deckId),
    onSuccess: (state, deckId) => {
      queryClient.setQueryData(flashcardKeys.generation(deckId), state)
      invalidateDeckLists(queryClient)
    },
  })
}

export function useAddCard(deckId: string): UseMutationResult<CardDTO, Error, AddCardRequest> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body) => flashcardApi.addCard(deckId, body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: flashcardKeys.deck(deckId) })
      invalidateDeckLists(queryClient)
    },
  })
}

/** Reword a card. No `source` field exists, so an AI card never becomes "yours". */
export function useEditCard(
  deckId: string,
): UseMutationResult<CardDTO, Error, { cardId: string; body: EditCardRequest }> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ cardId, body }) => flashcardApi.editCard(cardId, body),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: flashcardKeys.deck(deckId) }),
  })
}

export function useDeleteCard(deckId: string): UseMutationResult<void, Error, string> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (cardId) => flashcardApi.deleteCard(cardId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: flashcardKeys.deck(deckId) })
      invalidateDeckLists(queryClient)
    },
  })
}

/**
 * Grade one card. Grading is optimistic (the review screen moves on before this settles), so a
 * transient failure retries quietly with capped backoff before it reaches "ratings not saved".
 */
export function useReviewCard(): UseMutationResult<
  ReviewResultDTO,
  Error,
  { cardId: string; grade: ReviewGrade }
> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ cardId, grade }) => flashcardApi.reviewCard(cardId, grade),
    retry: 3,
    retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 8000),
    onSuccess: () => invalidateDeckLists(queryClient),
  })
}
```

- [ ] **Step 6: Run the tests and the type check**

Run: `cd $WT/web && npx vitest run tests/unit/flashcardApi.test.ts tests/unit/persistAllowlist.test.ts tests/unit/capabilityWiring.test.ts`
Expected: PASS. `capabilityWiring` still finds `retry: 3` and `retryDelay:` in `useFlashcardApi.ts`. Its `FlashcardReview.tsx` block still passes, because that file is not deleted until Task 18.

Run: `cd $WT/web && npx tsc -b --noEmit`
Expected: errors only in the old `FlashcardDecks.tsx`, `FlashcardReview.tsx` and `flashcards.test.ts` (old hook signatures, missing new fields in fixtures). Do not fix them; Tasks 10–13 replace these files and Task 18 deletes them. To keep CI green at this commit, apply these two minimal shims:
- In `FlashcardDecks.tsx` and `FlashcardReview.tsx`, change `useDueSession(subjectCode)` to `useDueSession({ subjectCode })`.
- In `web/tests/unit/flashcards.test.ts` and `flashcardSession.test.ts`, add the new required fields to the `card()`/`result()`/`deck()` fixture builders:
  - card: `nextIntervalDays: { again: 0, hard: 1, good: 1, easy: 1 }`
  - result: `xpAwarded: 0`
  - deck: `newCount: 0, learningCount: 0, knownCount: 0, marksLost: null, generationStatus: "ready", requestedCount: null`
  - due session: `upcoming: [], againDelayMinutes: 10`

Re-run `npx tsc -b --noEmit`. Expected: clean.

- [ ] **Step 7: Commit**

```bash
cd $WT/web && npx oxlint src/lib/flashcardApi.ts src/lib/hooks/useFlashcardApi.ts src/lib/flashcardTypes.ts && cd $WT
pre-commit run --files web/src/lib/flashcardTypes.ts web/src/lib/flashcardApi.ts web/src/lib/hooks/useFlashcardApi.ts web/tests/unit/flashcardApi.test.ts web/src/portals/student/screens/flashcards/FlashcardDecks.tsx web/src/portals/student/screens/flashcards/FlashcardReview.tsx web/tests/unit/flashcards.test.ts web/tests/unit/flashcardSession.test.ts
git commit -S -m "feat(web): flashcard api module, keys and hooks for L10" -- web/src/lib/flashcardTypes.ts web/src/lib/flashcardApi.ts web/src/lib/hooks/useFlashcardApi.ts web/tests/unit/flashcardApi.test.ts web/src/portals/student/screens/flashcards/FlashcardDecks.tsx web/src/portals/student/screens/flashcards/FlashcardReview.tsx web/tests/unit/flashcards.test.ts web/tests/unit/flashcardSession.test.ts
```

---

### Task 6: Decks screen view model

**Files:**
- Create: `web/src/portals/student/screens/flashcards/flashcardsView.ts`
- Test: `web/tests/unit/flashcardsView.test.ts`

**Interfaces:**
- Consumes: `DeckSummaryDTO`, `DueSessionDTO`, `WeakTopicDTO`.
- Produces:
  - `topicName(topic: string): string`
  - `subjectDot(code: string, order: readonly string[]): string`
  - `originView(origin): { icon: OriginIcon; label: string }`
  - `masteryView(counts): MasteryView`
  - `deckRowView(deck): DeckRowView`
  - `estimateMinutes(cards: number): number`
  - `comingBackLine(upcoming: readonly string[], nextDueAt: string | null, now: Date): string`
  - `decksScreenView(input: DecksScreenInput): DecksScreenView`
  - types `FcMood`, `OriginIcon`, `MasteryView`, `DeckRowView`, `SubjectGroupView`, `HeroView`, `SparseView`, `DecksScreenView`, `DecksScreenInput`
  - constants `SECONDS_PER_CARD = 18`, `SPARSE_MAX_CARDS = 10`

- [ ] **Step 1: Write the failing test**

```ts
// web/tests/unit/flashcardsView.test.ts
import { describe, expect, it } from "vitest"
import {
  comingBackLine,
  decksScreenView,
  deckRowView,
  estimateMinutes,
  masteryView,
  originView,
  subjectDot,
  topicName,
  type DecksScreenInput,
} from "@/portals/student/screens/flashcards/flashcardsView"
import type { DeckSummaryDTO, DueSessionDTO, WeakTopicDTO } from "@/lib/flashcardTypes"

const NOW = new Date("2026-11-16T09:00:00")

function deck(o: Partial<DeckSummaryDTO> & { id: string }): DeckSummaryDTO {
  return {
    subjectCode: "0580",
    topic: null,
    title: o.id,
    description: null,
    origin: "manual",
    cardCount: 10,
    dueCount: 0,
    createdAt: "2026-11-01T00:00:00Z",
    newCount: 4,
    learningCount: 4,
    knownCount: 2,
    marksLost: null,
    generationStatus: "ready",
    requestedCount: null,
    ...o,
  }
}

function due(o: Partial<DueSessionDTO> = {}): DueSessionDTO {
  return { cards: [], totalDue: 0, nextDueAt: null, upcoming: [], againDelayMinutes: 10, ...o }
}

const names: Record<string, string> = { "0580": "Maths", "0625": "Physics", "0606": "Add Maths" }

function input(o: Partial<DecksScreenInput>): DecksScreenInput {
  return {
    decks: [],
    decksStatus: "success",
    due: due(),
    dueStatus: "success",
    weakTopics: [],
    subjectName: (c) => names[c] ?? c,
    subjectOrder: ["0580", "0625", "0606"],
    filterSubject: null,
    now: NOW,
    ...o,
  }
}

describe("small helpers", () => {
  it("strips the syllabus code from a topic label", () => {
    expect(topicName("4.3 Electric circuits")).toBe("Electric circuits")
    expect(topicName("E7 Vectors")).toBe("Vectors")
    expect(topicName("Vectors")).toBe("Vectors")
  })

  it("gives each subject a stable dot colour by enrolment order", () => {
    expect(subjectDot("0580", ["0580", "0625"])).toBe("var(--color-grade-a)")
    expect(subjectDot("0625", ["0580", "0625"])).toBe("var(--color-inverse-primary)")
    expect(subjectDot("9999", ["0580"])).toBe("var(--color-on-surface-variant)")
  })

  it("labels origins the way the mock does", () => {
    expect(originView("weakness")).toEqual({ icon: "target", label: "From a weakness" })
    expect(originView("topic")).toEqual({ icon: "sparkle", label: "For a topic" })
    expect(originView("manual")).toEqual({ icon: "pen", label: "Written by you" })
  })

  it("builds mastery fractions and an aria label, safe on an empty deck", () => {
    expect(masteryView({ newCount: 4, learningCount: 8, knownCount: 6 })).toEqual({
      known: 6,
      learning: 8,
      fresh: 4,
      total: 18,
      knownPct: (6 / 18) * 100,
      learningPct: (8 / 18) * 100,
      label: "6 known, 8 learning, 4 new",
    })
    expect(masteryView({ newCount: 0, learningCount: 0, knownCount: 0 }).knownPct).toBe(0)
  })

  it("estimates about 18 seconds a card, never zero minutes", () => {
    expect(estimateMinutes(26)).toBe(8)
    expect(estimateMinutes(1)).toBe(1)
  })
})

describe("deckRowView", () => {
  it("shows origin, card count and due", () => {
    const row = deckRowView(deck({ id: "Vectors", origin: "weakness", cardCount: 18, dueCount: 9 }))
    expect(row.originLabel).toBe("From a weakness")
    expect(row.meta).toBe("From a weakness · 18 cards")
    expect(row.due).toBe(9)
    expect(row.statusLine).toBeNull()
  })

  it("replaces the meta line while writing or after a failure", () => {
    expect(
      deckRowView(deck({ id: "W", generationStatus: "writing", requestedCount: 12, cardCount: 0 }))
        .statusLine,
    ).toBe("Writing 12 cards…")
    expect(deckRowView(deck({ id: "F", generationStatus: "failed" })).statusLine).toBe(
      "Couldn't write the cards",
    )
  })
})

describe("comingBackLine", () => {
  it("counts tomorrow's cards first", () => {
    expect(
      comingBackLine(["2026-11-17T08:00:00", "2026-11-17T20:00:00", "2026-11-19T08:00:00"], null, NOW),
    ).toBe("2 cards back tomorrow")
  })
  it("falls back to the next due day, then to an add-cards nudge", () => {
    expect(comingBackLine([], "2026-11-20T08:00:00", NOW)).toBe("Next card Friday")
    expect(comingBackLine([], null, NOW)).toBe("Add cards to start")
  })
})

describe("decksScreenView", () => {
  it("is loading, then error, before anything else", () => {
    expect(decksScreenView(input({ decks: undefined, decksStatus: "pending" })).kind).toBe("loading")
    expect(decksScreenView(input({ decks: undefined, decksStatus: "error" })).kind).toBe("error")
  })

  it("is the empty shelf with a weak-topic hint when there are no decks", () => {
    const weak: WeakTopicDTO[] = [
      { subjectCode: "0580", topic: "E7 Vectors", marksLost: 9, accuracyPct: 41 },
    ]
    expect(decksScreenView(input({ weakTopics: weak }))).toEqual({
      kind: "empty",
      mood: "open",
      weakHint: "Vectors cost you 9 marks",
    })
  })

  it("orders decks due first, groups by subject, and fills the hero", () => {
    const view = decksScreenView(
      input({
        decks: [
          deck({ id: "Algebra", dueCount: 4 }),
          deck({ id: "Vectors", dueCount: 9 }),
          deck({ id: "Waves", subjectCode: "0625", dueCount: 14 }),
          deck({ id: "Functions", subjectCode: "0606", dueCount: 0 }),
        ],
        due: due({ totalDue: 27 }),
      }),
    )
    if (view.kind !== "ready") throw new Error(view.kind)
    // Physics (14 due) beats Maths (13 due); Add Maths has none.
    expect(view.groups.map((g) => g.subjectName)).toEqual(["Physics", "Maths", "Add Maths"])
    expect(view.groups[1].decks.map((d) => d.title)).toEqual(["Vectors", "Algebra"])
    expect(view.hero).toEqual({
      mood: "happy",
      headline: "27 cards due",
      sub: "About 8 minutes · 3 decks",
      reviewLabel: "Review 27 cards",
    })
    expect(view.header).toEqual({ title: "Flashcards", sub: "4 decks · 40 cards" })
    expect(view.firstDeckId).toBe("Waves")
    expect(view.sparse).toBeNull()
  })

  it("says nothing is due and when cards come back", () => {
    const view = decksScreenView(
      input({
        decks: [deck({ id: "A" }), deck({ id: "B" })],
        due: due({ upcoming: ["2026-11-17T08:00:00"] }),
      }),
    )
    if (view.kind !== "ready") throw new Error(view.kind)
    expect(view.hero).toEqual({
      mood: "happy",
      headline: "Nothing due",
      sub: "1 card back tomorrow",
      reviewLabel: null,
    })
  })

  it("keeps the hero honest while the due check is pending or failed", () => {
    const pending = decksScreenView(input({ decks: [deck({ id: "A" })], due: undefined, dueStatus: "pending" }))
    const failed = decksScreenView(input({ decks: [deck({ id: "A" })], due: undefined, dueStatus: "error" }))
    if (pending.kind !== "ready" || failed.kind !== "ready") throw new Error("not ready")
    expect(pending.hero.sub).toBe("Checking what's due…")
    expect(failed.hero.sub).toBe("Couldn't check what's due")
    expect(failed.hero.reviewLabel).toBeNull()
  })

  it("adds the sparse tip and walkthrough for one small deck", () => {
    const view = decksScreenView(
      input({
        decks: [deck({ id: "Vectors", origin: "weakness", topic: "E7 Vectors", cardCount: 6 })],
        weakTopics: [
          { subjectCode: "0580", topic: "E7 Vectors", marksLost: 9, accuracyPct: 41 },
          { subjectCode: "0625", topic: "3 Waves", marksLost: 6, accuracyPct: 50 },
        ],
      }),
    )
    if (view.kind !== "ready") throw new Error(view.kind)
    expect(view.sparse).toEqual({
      tip: { title: "One more deck?", body: "Waves cost you 6 marks.", subjectCode: "0625", topic: "3 Waves" },
    })
  })

  it("narrows to one subject when the route filters", () => {
    const view = decksScreenView(
      input({
        decks: [deck({ id: "Vectors" }), deck({ id: "Waves", subjectCode: "0625" })],
        filterSubject: "0625",
      }),
    )
    if (view.kind !== "ready") throw new Error(view.kind)
    expect(view.groups.map((g) => g.subjectCode)).toEqual(["0625"])
    expect(view.header.sub).toBe("Physics · 1 deck · 10 cards")
  })
})
```

- [ ] **Step 2: Run it to see it fail**

Run: `cd $WT/web && npx vitest run tests/unit/flashcardsView.test.ts`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement**

```ts
// web/src/portals/student/screens/flashcards/flashcardsView.ts
import type { DeckOrigin, DeckSummaryDTO, DueSessionDTO, WeakTopicDTO } from "@/lib/flashcardTypes"

/*
 * L10 · every decision on the decks screen, as plain data. No React, no DOM, so Vitest runs it
 * in node (vitest.config.ts). The screen renders `decksScreenView(...)` and decides nothing.
 */

/** Structurally the F1 `BinnyMood`; declared here so this `.ts` file never imports a `.tsx`. */
export type FcMood = "happy" | "wink" | "open" | "thinking" | "sad"
export type OriginIcon = "target" | "sparkle" | "pen"
type QueryStatus = "pending" | "error" | "success"

export const SECONDS_PER_CARD = 18
export const SPARSE_MAX_CARDS = 10

const TOPIC_CODE = /^[A-Z]?\d+(?:\.\d+)*\s+/

export function topicName(topic: string): string {
  return topic.replace(TOPIC_CODE, "").trim() || topic
}

/** Dot colours from existing tokens only (no new tokens; mock blue/violet map to tide/orange). */
const SUBJECT_DOTS = [
  "var(--color-grade-a)",
  "var(--color-inverse-primary)",
  "var(--color-grade-d)",
  "var(--color-primary)",
  "var(--color-grade-b)",
]

export function subjectDot(code: string, order: readonly string[]): string {
  const i = order.indexOf(code)
  return i < 0 ? "var(--color-on-surface-variant)" : SUBJECT_DOTS[i % SUBJECT_DOTS.length]
}

export function originView(origin: DeckOrigin): { icon: OriginIcon; label: string } {
  if (origin === "weakness") return { icon: "target", label: "From a weakness" }
  if (origin === "topic") return { icon: "sparkle", label: "For a topic" }
  return { icon: "pen", label: "Written by you" }
}

export interface MasteryView {
  known: number
  learning: number
  fresh: number
  total: number
  knownPct: number
  learningPct: number
  label: string
}

export function masteryView(c: { newCount: number; learningCount: number; knownCount: number }): MasteryView {
  const total = c.newCount + c.learningCount + c.knownCount
  return {
    known: c.knownCount,
    learning: c.learningCount,
    fresh: c.newCount,
    total,
    knownPct: total ? (c.knownCount / total) * 100 : 0,
    learningPct: total ? (c.learningCount / total) * 100 : 0,
    label: `${c.knownCount} known, ${c.learningCount} learning, ${c.newCount} new`,
  }
}

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`

export interface DeckRowView {
  id: string
  title: string
  subjectCode: string
  originIcon: OriginIcon
  originLabel: string
  meta: string
  mastery: MasteryView
  due: number
  status: DeckSummaryDTO["generationStatus"]
  statusLine: string | null
}

export function deckRowView(deck: DeckSummaryDTO): DeckRowView {
  const origin = originView(deck.origin)
  const statusLine =
    deck.generationStatus === "writing"
      ? `Writing ${plural(deck.requestedCount ?? 0, "card")}…`
      : deck.generationStatus === "failed"
        ? "Couldn't write the cards"
        : null
  return {
    id: deck.id,
    title: deck.title,
    subjectCode: deck.subjectCode,
    originIcon: origin.icon,
    originLabel: origin.label,
    meta: `${origin.label} · ${plural(deck.cardCount, "card")}`,
    mastery: masteryView(deck),
    due: deck.dueCount,
    status: deck.generationStatus,
    statusLine,
  }
}

export function estimateMinutes(cards: number): number {
  return Math.max(1, Math.round((cards * SECONDS_PER_CARD) / 60))
}

function localDayIndex(d: Date, now: Date): number {
  const a = new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()
  const b = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  return Math.round((a - b) / 86_400_000)
}

/** "N cards back tomorrow" from the forecast; else the next due weekday; else a nudge. */
export function comingBackLine(upcoming: readonly string[], nextDueAt: string | null, now: Date): string {
  const tomorrow = upcoming.filter((iso) => localDayIndex(new Date(iso), now) === 1).length
  if (tomorrow > 0) return `${plural(tomorrow, "card")} back tomorrow`
  if (nextDueAt) {
    const d = new Date(nextDueAt)
    if (!Number.isNaN(d.getTime())) {
      const day = localDayIndex(d, now)
      if (day <= 0) return "Next card later today"
      return `Next card ${d.toLocaleDateString(undefined, { weekday: "long" })}`
    }
  }
  return "Add cards to start"
}

export interface SubjectGroupView {
  subjectCode: string
  subjectName: string
  dot: string
  decks: DeckRowView[]
}

export interface HeroView {
  mood: FcMood
  headline: string
  sub: string
  reviewLabel: string | null
}

export interface SparseView {
  tip: { title: string; body: string; subjectCode: string; topic: string } | null
}

export type DecksScreenView =
  | { kind: "loading" }
  | { kind: "error" }
  | { kind: "empty"; mood: FcMood; weakHint: string | null }
  | {
      kind: "ready"
      header: { title: string; sub: string }
      hero: HeroView
      groups: SubjectGroupView[]
      sparse: SparseView | null
      firstDeckId: string | null
    }

export interface DecksScreenInput {
  decks: DeckSummaryDTO[] | undefined
  decksStatus: QueryStatus
  due: DueSessionDTO | undefined
  dueStatus: QueryStatus
  weakTopics: readonly WeakTopicDTO[]
  subjectName: (code: string) => string
  subjectOrder: readonly string[]
  filterSubject: string | null
  now: Date
}

function hero(input: DecksScreenInput, decks: DeckSummaryDTO[]): HeroView {
  if (input.dueStatus === "pending" && !input.due) {
    return { mood: "happy", headline: "Your cards", sub: "Checking what's due…", reviewLabel: null }
  }
  if (input.dueStatus === "error" && !input.due) {
    return { mood: "happy", headline: "Your cards", sub: "Couldn't check what's due", reviewLabel: null }
  }
  const due = input.due!
  if (due.totalDue > 0) {
    const decksDue = decks.filter((d) => d.dueCount > 0).length
    return {
      mood: "happy",
      headline: `${plural(due.totalDue, "card")} due`,
      sub: `About ${plural(estimateMinutes(due.totalDue), "minute")} · ${plural(decksDue, "deck")}`,
      reviewLabel: `Review ${plural(due.totalDue, "card")}`,
    }
  }
  return {
    mood: "happy",
    headline: "Nothing due",
    sub: comingBackLine(due.upcoming, due.nextDueAt, input.now),
    reviewLabel: null,
  }
}

const groupOrderRank = (order: readonly string[], code: string) => {
  const i = order.indexOf(code)
  return i < 0 ? order.length : i
}

export function decksScreenView(input: DecksScreenInput): DecksScreenView {
  if (!input.decks) return input.decksStatus === "error" ? { kind: "error" } : { kind: "loading" }
  const decks = input.filterSubject
    ? input.decks.filter((d) => d.subjectCode === input.filterSubject)
    : input.decks
  if (decks.length === 0) {
    const weak = input.weakTopics.find((t) => !input.filterSubject || t.subjectCode === input.filterSubject)
    return {
      kind: "empty",
      mood: "open",
      weakHint: weak ? `${topicName(weak.topic)} cost you ${weak.marksLost} marks` : null,
    }
  }

  const bySubject = new Map<string, DeckSummaryDTO[]>()
  for (const d of decks) bySubject.set(d.subjectCode, [...(bySubject.get(d.subjectCode) ?? []), d])
  const statusRank = (d: DeckSummaryDTO) => (d.generationStatus === "ready" ? 1 : 0)
  const groups: SubjectGroupView[] = [...bySubject.entries()]
    .map(([code, list]) => ({
      subjectCode: code,
      subjectName: input.subjectName(code),
      dot: subjectDot(code, input.subjectOrder),
      decks: [...list]
        .sort((a, b) => statusRank(a) - statusRank(b) || b.dueCount - a.dueCount || a.title.localeCompare(b.title))
        .map(deckRowView),
      dueTotal: list.reduce((s, d) => s + d.dueCount, 0),
    }))
    .sort(
      (a, b) =>
        b.dueTotal - a.dueTotal ||
        groupOrderRank(input.subjectOrder, a.subjectCode) - groupOrderRank(input.subjectOrder, b.subjectCode),
    )
    .map(({ dueTotal: _dueTotal, ...g }) => g)

  const totalCards = decks.reduce((s, d) => s + d.cardCount, 0)
  const counts = `${plural(decks.length, "deck")} · ${plural(totalCards, "card")}`
  const sub = input.filterSubject ? `${input.subjectName(input.filterSubject)} · ${counts}` : counts

  const isSparse = decks.length === 1 && totalCards <= SPARSE_MAX_CARDS
  let sparse: SparseView | null = null
  if (isSparse) {
    const covered = new Set(decks.map((d) => `${d.subjectCode}|${d.topic ?? ""}`))
    const next = input.weakTopics.find((t) => !covered.has(`${t.subjectCode}|${t.topic}`))
    sparse = {
      tip: next
        ? {
            title: "One more deck?",
            body: `${topicName(next.topic)} cost you ${next.marksLost} marks.`,
            subjectCode: next.subjectCode,
            topic: next.topic,
          }
        : null,
    }
  }

  return {
    kind: "ready",
    header: { title: "Flashcards", sub },
    hero: hero(input, decks),
    groups,
    sparse,
    firstDeckId: groups[0]?.decks[0]?.id ?? null,
  }
}
```

- [ ] **Step 4: Run it**

Run: `cd $WT/web && npx vitest run tests/unit/flashcardsView.test.ts`
Expected: PASS. If the weekday case fails because of the host timezone, note that `NOW` and the ISO strings are local-time literals (no `Z`) on purpose; fix the code, not the test.

- [ ] **Step 5: Commit**

```bash
pre-commit run --files web/src/portals/student/screens/flashcards/flashcardsView.ts web/tests/unit/flashcardsView.test.ts
git commit -S -m "feat(web): flashcard decks view model (L10)" -- web/src/portals/student/screens/flashcards/flashcardsView.ts web/tests/unit/flashcardsView.test.ts
```

---

### Task 7: Review session model, swipe visuals and review/done view model

**Files:**
- Modify: `web/src/lib/flashcardSession.ts`, `web/src/lib/flashcardSwipe.ts`
- Create: `web/src/portals/student/screens/flashcards/reviewView.ts`
- Test: `web/tests/unit/flashcardSession.test.ts` (update), `web/tests/unit/flashcardSwipe.test.ts` (extend), `web/tests/unit/reviewView.test.ts` (create)

**Interfaces:**
- Produces:
  - session (`flashcardSession.ts`):
    - `FlashcardSessionState` gains `combo: number` and `bestCombo: number`
    - `startSession(): FlashcardSessionState`
    - `registerGrade(state, grade): FlashcardSessionState`
    - `beginRetry(state): { state: FlashcardSessionState; retries: FailedGrade[] }`
    - `knewCount(results): number`
    - `xpEarned(results): number`
    - `applyGradeOutcome` unchanged
  - swipe (`flashcardSwipe.ts`): `swipeVisual(dx, revealed, reduced): SwipeVisual`, where `SwipeVisual = { stamp: "again" | "good" | null; opacity: number; rotateDeg: number; armed: boolean }`
  - review (`reviewView.ts`):
    - `GRADE_ORDER`, `intervalLabel(days, againDelayMinutes): string`, `gradeButtons(card, againDelayMinutes): GradeButtonView[]`
    - `reviewKeyAction(key, revealed): ReviewKeyAction | null`
    - `progressView(index, total): { label: string; fraction: number }`
    - `syncBannerText(failedCount): string | null`
    - `comingBackRows(upcoming, now): ComingBackRow[]`
    - `doneView(input: DoneInput): DoneView`
    - `generationOutcome(status: GenerationStatusDTO): { text: string; shortfall: boolean }`

- [ ] **Step 1: Write the failing tests**

Replace the state literals in `web/tests/unit/flashcardSession.test.ts` with `startSession()` spreads: every `{ results: [], failed: [], inFlight: N }` becomes `{ ...startSession(), inFlight: N }`. Then append:

```ts
import { beginRetry, knewCount, registerGrade, startSession, xpEarned } from "@/lib/flashcardSession"

describe("combo and totals", () => {
  it("builds a combo on passing grades, resets on Again, and remembers the best", () => {
    let s = startSession()
    for (const g of ["good", "easy", "hard"] as const) s = registerGrade(s, g)
    expect([s.combo, s.bestCombo, s.inFlight]).toEqual([3, 3, 3])
    s = registerGrade(s, "again")
    expect([s.combo, s.bestCombo]).toEqual([0, 3])
  })

  it("retries every failed grade at once and counts them in flight", () => {
    const s = {
      ...startSession(),
      failed: [
        { cardId: "a", front: "A", grade: "good" as const },
        { cardId: "b", front: "B", grade: "again" as const },
      ],
    }
    const { state, retries } = beginRetry(s)
    expect(retries.map((r) => r.cardId)).toEqual(["a", "b"])
    expect([state.failed.length, state.inFlight]).toEqual([0, 2])
  })

  it("counts knew-it as every grade but Again, and sums the XP the server gave", () => {
    const r = (grade: "again" | "good", xp: number) => ({ ...result("c" + xp), grade, xpAwarded: xp })
    expect(knewCount([r("good", 2), r("again", 0), r("good", 3)])).toBe(2)
    expect(xpEarned([r("good", 2), r("again", 0), r("good", 3)])).toBe(5)
  })
})
```

(`result(id)` is the file's existing `ReviewResultDTO` fixture builder, given `xpAwarded: 0` in Task 5.)

Append to `web/tests/unit/flashcardSwipe.test.ts`:

```ts
import { swipeVisual } from "@/lib/flashcardSwipe"

describe("swipeVisual", () => {
  it("shows no stamp before the flip", () => {
    expect(swipeVisual(120, false, false)).toEqual({ stamp: null, opacity: 0, rotateDeg: 6, armed: false })
  })
  it("fades the Good stamp in to the grade threshold, then arms", () => {
    expect(swipeVisual(40, true, false)).toEqual({ stamp: "good", opacity: 0.5, rotateDeg: 3.2, armed: false })
    expect(swipeVisual(GRADE_SWIPE_THRESHOLD, true, false).armed).toBe(true)
  })
  it("stamps Again to the left and caps the tilt", () => {
    expect(swipeVisual(-400, true, false)).toEqual({ stamp: "again", opacity: 1, rotateDeg: -12, armed: true })
  })
  it("never tilts under reduced motion", () => {
    expect(swipeVisual(-400, true, true).rotateDeg).toBe(0)
  })
})
```

Create `web/tests/unit/reviewView.test.ts`:

```ts
import { describe, expect, it } from "vitest"
import {
  comingBackRows,
  doneView,
  generationOutcome,
  gradeButtons,
  intervalLabel,
  progressView,
  reviewKeyAction,
  syncBannerText,
} from "@/portals/student/screens/flashcards/reviewView"
import { startSession } from "@/lib/flashcardSession"
import type { CardDTO, ReviewResultDTO } from "@/lib/flashcardTypes"

const NOW = new Date("2026-11-16T09:00:00") // a Monday

const card: CardDTO = {
  id: "c1", front: "f", back: "b", position: 1, source: "manual", sourceQuestionId: null,
  repetitions: 2, easeFactor: 2.5, intervalDays: 6, lapses: 0, dueAt: "2026-11-16T08:00:00Z",
  lastReviewedAt: null, nextIntervalDays: { again: 0, hard: 1, good: 15, easy: 40 },
}

function res(grade: ReviewResultDTO["grade"], xp = 1): ReviewResultDTO {
  return { card, reviewId: "r", grade, intervalBeforeDays: 6, intervalAfterDays: 15, xpAwarded: xp }
}

describe("intervals and grade buttons", () => {
  it("speaks intervals in plain units", () => {
    expect(intervalLabel(0, 10)).toBe("10 min")
    expect(intervalLabel(1, 10)).toBe("1 day")
    expect(intervalLabel(3, 10)).toBe("3 days")
    expect(intervalLabel(7, 10)).toBe("1 week")
    expect(intervalLabel(15, 10)).toBe("2 weeks")
    expect(intervalLabel(40, 10)).toBe("1 month")
    expect(intervalLabel(400, 10)).toBe("1 year")
  })

  it("lists Again, Hard, Good, Easy with keys 1-4 and real intervals", () => {
    expect(gradeButtons(card, 10)).toEqual([
      { grade: "again", label: "Again", interval: "10 min", key: "1", tone: "again" },
      { grade: "hard", label: "Hard", interval: "1 day", key: "2", tone: "hard" },
      { grade: "good", label: "Good", interval: "2 weeks", key: "3", tone: "good" },
      { grade: "easy", label: "Easy", interval: "1 month", key: "4", tone: "easy" },
    ])
  })
})

describe("reviewKeyAction", () => {
  it("flips on Space or Enter before the reveal, and ignores digits then", () => {
    expect(reviewKeyAction(" ", false)).toEqual({ kind: "reveal" })
    expect(reviewKeyAction("Enter", false)).toEqual({ kind: "reveal" })
    expect(reviewKeyAction("3", false)).toBeNull()
  })
  it("rates 1-4 after the reveal and ignores Space then", () => {
    expect(reviewKeyAction("1", true)).toEqual({ kind: "grade", grade: "again" })
    expect(reviewKeyAction("4", true)).toEqual({ kind: "grade", grade: "easy" })
    expect(reviewKeyAction(" ", true)).toBeNull()
    expect(reviewKeyAction("5", true)).toBeNull()
  })
})

describe("progress and the sync banner", () => {
  it("shows the card on screen out of the total, clamped", () => {
    expect(progressView(3, 26)).toEqual({ label: "4/26", fraction: 4 / 26 })
    expect(progressView(30, 26)).toEqual({ label: "26/26", fraction: 1 })
  })
  it("names unsaved ratings, or nothing", () => {
    expect(syncBannerText(0)).toBeNull()
    expect(syncBannerText(1)).toBe("1 rating not saved yet")
    expect(syncBannerText(3)).toBe("3 ratings not saved yet")
  })
})

describe("comingBackRows", () => {
  it("lists later today, tomorrow and the biggest later day, at most two rows", () => {
    const upcoming = [
      "2026-11-16T09:10:00",
      "2026-11-17T08:00:00", "2026-11-17T09:00:00",
      "2026-11-19T08:00:00",
      "2026-11-21T08:00:00", "2026-11-21T09:00:00", "2026-11-21T10:00:00",
    ]
    expect(comingBackRows(upcoming, NOW)).toEqual([
      { title: "1 card later today", sub: "The ones you marked Again" },
      { title: "2 cards tomorrow", sub: null },
    ])
    expect(comingBackRows(upcoming.slice(1), NOW)).toEqual([
      { title: "2 cards tomorrow", sub: null },
      { title: "Next big review Saturday", sub: "3 cards" },
    ])
    expect(comingBackRows([], NOW)).toEqual([{ title: "Nothing due this week", sub: null }])
  })
})

describe("doneView", () => {
  it("celebrates with knew-it, XP, best combo and a practice link", () => {
    const session = {
      ...startSession(),
      results: [res("good", 2), res("easy", 2), res("again", 0)],
      bestCombo: 2,
    }
    expect(
      doneView({
        session, totalCards: 3, stillDue: 0, upcoming: [], now: NOW,
        practice: { subjectCode: "0580", topicName: "Vectors", marksLost: 9 },
      }),
    ).toEqual({
      mood: "happy",
      title: "All caught up!",
      sub: "3 cards · best combo ×2",
      knew: 2,
      xp: 4,
      stillDueLine: null,
      savingLine: null,
      comingBack: [{ title: "Nothing due this week", sub: null }],
      practiceLink: { label: "Practise Vectors · +9 marks", to: "/student/practice/0580" },
    })
  })

  it("drops the combo under 2, softens Binny on a rough run, and names unfinished work", () => {
    const session = { ...startSession(), results: [res("again", 0), res("again", 0), res("good", 1)], inFlight: 2 }
    const view = doneView({ session, totalCards: 3, stillDue: 4, upcoming: [], now: NOW, practice: null })
    expect(view.sub).toBe("3 cards")
    expect(view.mood).toBe("open")
    expect(view.stillDueLine).toBe("4 more still due")
    expect(view.savingLine).toBe("2 ratings still saving")
    expect(view.practiceLink).toBeNull()
  })
})

describe("generationOutcome", () => {
  it("reports the real count and names a shortfall", () => {
    const base = { deckId: "d", status: "ready" as const, error: null }
    expect(generationOutcome({ ...base, requestedCount: 12, generatedCount: 12 })).toEqual({
      text: "12 cards ready", shortfall: false,
    })
    expect(generationOutcome({ ...base, requestedCount: 12, generatedCount: 9 })).toEqual({
      text: "9 of 12 cards written", shortfall: true,
    })
  })
})
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd $WT/web && npx vitest run tests/unit/flashcardSession.test.ts tests/unit/flashcardSwipe.test.ts tests/unit/reviewView.test.ts`
Expected: FAIL (missing exports).

- [ ] **Step 3: Extend `flashcardSession.ts`**

Keep `FailedGrade`, `GradeOutcome` and `applyGradeOutcome` exactly as they are. Change the state interface and add the helpers:

```ts
export interface FlashcardSessionState {
  results: ReviewResultDTO[]
  failed: FailedGrade[]
  inFlight: number
  /** Consecutive "knew it" grades (anything but Again) in this session. */
  combo: number
  bestCombo: number
}

export function startSession(): FlashcardSessionState {
  return { results: [], failed: [], inFlight: 0, combo: 0, bestCombo: 0 }
}

/** A grade was pressed: count it in flight and move the combo. Called before the request. */
export function registerGrade(state: FlashcardSessionState, grade: ReviewGrade): FlashcardSessionState {
  const combo = grade === "again" ? 0 : state.combo + 1
  return { ...state, inFlight: state.inFlight + 1, combo, bestCombo: Math.max(state.bestCombo, combo) }
}

/** "Retry" on the banner: every failed grade is re-sent at once. */
export function beginRetry(state: FlashcardSessionState): {
  state: FlashcardSessionState
  retries: FailedGrade[]
} {
  return {
    state: { ...state, failed: [], inFlight: state.inFlight + state.failed.length },
    retries: state.failed,
  }
}

export function knewCount(results: readonly ReviewResultDTO[]): number {
  return results.filter((r) => r.grade !== "again").length
}

/** XP the server actually awarded (capped days award 0). Never an estimate. */
export function xpEarned(results: readonly ReviewResultDTO[]): number {
  return results.reduce((sum, r) => sum + r.xpAwarded, 0)
}
```

`applyGradeOutcome` keeps spreading `session`, so it preserves `combo` and `bestCombo`. Change its two return objects to `{ ...session, results: ..., failed: ..., inFlight }`.

- [ ] **Step 4: Extend `flashcardSwipe.ts`**

```ts
export interface SwipeVisual {
  stamp: "again" | "good" | null
  /** 0..1, reaches 1 at the grade threshold. */
  opacity: number
  rotateDeg: number
  /** Past the threshold: releasing now grades. */
  armed: boolean
}

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v))

/** What the card shows mid-drag. Pure, so the stamp maths are unit-tested. */
export function swipeVisual(dx: number, revealed: boolean, reduced: boolean): SwipeVisual {
  if (!revealed) {
    return { stamp: null, opacity: 0, rotateDeg: reduced ? 0 : clamp(dx * 0.05, -6, 6), armed: false }
  }
  return {
    stamp: dx > 0 ? "good" : dx < 0 ? "again" : null,
    opacity: clamp(Math.abs(dx) / GRADE_SWIPE_THRESHOLD, 0, 1),
    rotateDeg: reduced ? 0 : clamp(dx * 0.08, -12, 12),
    armed: Math.abs(dx) >= GRADE_SWIPE_THRESHOLD,
  }
}
```

(At `dx = 120` before the flip, `120 × 0.05 = 6`, matching the test. At `dx = 40` after it, `40 × 0.08 = 3.2`.)

- [ ] **Step 5: Write `reviewView.ts`**

```ts
// web/src/portals/student/screens/flashcards/reviewView.ts
import type { CardDTO, GenerationStatusDTO, ReviewGrade } from "@/lib/flashcardTypes"
import { knewCount, xpEarned, type FlashcardSessionState } from "@/lib/flashcardSession"
import type { FcMood } from "./flashcardsView"

export const GRADE_ORDER: readonly ReviewGrade[] = ["again", "hard", "good", "easy"]
const GRADE_LABEL: Record<ReviewGrade, string> = { again: "Again", hard: "Hard", good: "Good", easy: "Easy" }

const plural = (n: number, w: string) => `${n} ${w}${n === 1 ? "" : "s"}`

export function intervalLabel(days: number, againDelayMinutes: number): string {
  if (days <= 0) return `${againDelayMinutes} min`
  if (days < 7) return plural(days, "day")
  if (days < 30) return plural(Math.floor(days / 7), "week")
  if (days < 365) return plural(Math.max(1, Math.round(days / 30)), "month")
  return plural(Math.round(days / 365), "year")
}

export interface GradeButtonView {
  grade: ReviewGrade
  label: string
  interval: string
  key: "1" | "2" | "3" | "4"
  tone: ReviewGrade
}

export function gradeButtons(card: CardDTO, againDelayMinutes: number): GradeButtonView[] {
  return GRADE_ORDER.map((grade, i) => ({
    grade,
    label: GRADE_LABEL[grade],
    interval: intervalLabel(card.nextIntervalDays[grade], againDelayMinutes),
    key: String(i + 1) as GradeButtonView["key"],
    tone: grade,
  }))
}

export type ReviewKeyAction = { kind: "reveal" } | { kind: "grade"; grade: ReviewGrade }

/** Space/Enter flip before the reveal; 1-4 rate after it. Anything else is ignored. */
export function reviewKeyAction(key: string, revealed: boolean): ReviewKeyAction | null {
  if (!revealed) return key === " " || key === "Enter" ? { kind: "reveal" } : null
  const i = ["1", "2", "3", "4"].indexOf(key)
  return i < 0 ? null : { kind: "grade", grade: GRADE_ORDER[i] }
}

export function progressView(index: number, total: number): { label: string; fraction: number } {
  const current = Math.min(index + 1, total)
  return { label: `${current}/${total}`, fraction: total ? current / total : 0 }
}

export function syncBannerText(failedCount: number): string | null {
  return failedCount > 0 ? `${plural(failedCount, "rating")} not saved yet` : null
}

export interface ComingBackRow {
  title: string
  sub: string | null
}

function dayIndex(d: Date, now: Date): number {
  const a = new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()
  const b = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  return Math.round((a - b) / 86_400_000)
}

/** From the server forecast only. Later today first (the Again cards), then tomorrow, then the
 * biggest later day. At most two rows. */
export function comingBackRows(upcoming: readonly string[], now: Date): ComingBackRow[] {
  const byDay = new Map<number, number>()
  for (const iso of upcoming) {
    const d = dayIndex(new Date(iso), now)
    byDay.set(d, (byDay.get(d) ?? 0) + 1)
  }
  const rows: ComingBackRow[] = []
  const today = byDay.get(0) ?? 0
  if (today > 0) rows.push({ title: `${plural(today, "card")} later today`, sub: "The ones you marked Again" })
  const tomorrow = byDay.get(1) ?? 0
  if (tomorrow > 0) rows.push({ title: `${plural(tomorrow, "card")} tomorrow`, sub: null })
  const later = [...byDay.entries()].filter(([d]) => d >= 2).sort((a, b) => b[1] - a[1] || a[0] - b[0])[0]
  if (later) {
    const date = new Date(now.getFullYear(), now.getMonth(), now.getDate() + later[0])
    rows.push({
      title: `Next big review ${date.toLocaleDateString(undefined, { weekday: "long" })}`,
      sub: plural(later[1], "card"),
    })
  }
  return rows.length ? rows.slice(0, 2) : [{ title: "Nothing due this week", sub: null }]
}

export interface DoneInput {
  session: FlashcardSessionState
  totalCards: number
  /** Due cards beyond this session's snapshot (`totalDue - totalCards`), or 0. */
  stillDue: number
  upcoming: readonly string[]
  now: Date
  practice: { subjectCode: string; topicName: string; marksLost: number } | null
}

export interface DoneView {
  mood: FcMood
  title: string
  sub: string
  knew: number
  xp: number
  stillDueLine: string | null
  savingLine: string | null
  comingBack: ComingBackRow[]
  practiceLink: { label: string; to: string } | null
}

export function doneView(input: DoneInput): DoneView {
  const { session } = input
  const knew = knewCount(session.results)
  const reviewed = session.results.length
  const combo = session.bestCombo >= 2 ? ` · best combo ×${session.bestCombo}` : ""
  return {
    mood: reviewed === 0 || knew / reviewed >= 0.6 ? "happy" : "open",
    title: "All caught up!",
    sub: `${plural(input.totalCards, "card")}${combo}`,
    knew,
    xp: xpEarned(session.results),
    stillDueLine: input.stillDue > 0 ? `${input.stillDue} more still due` : null,
    savingLine: session.inFlight > 0 ? `${plural(session.inFlight, "rating")} still saving` : null,
    comingBack: comingBackRows(input.upcoming, input.now),
    practiceLink: input.practice
      ? {
          label: `Practise ${input.practice.topicName} · +${input.practice.marksLost} marks`,
          to: `/student/practice/${input.practice.subjectCode}`,
        }
      : null,
  }
}

/** The real count, never the requested one (P4.9 honesty rule 2). */
export function generationOutcome(status: GenerationStatusDTO): { text: string; shortfall: boolean } {
  const requested = status.requestedCount ?? status.generatedCount
  if (status.generatedCount < requested) {
    return { text: `${status.generatedCount} of ${requested} cards written`, shortfall: true }
  }
  return { text: `${plural(status.generatedCount, "card")} ready`, shortfall: false }
}
```

Note on `stillDueLine`: the live summary said "N still due today" (R10). The done screen keeps it as one quiet line under the stats.

- [ ] **Step 6: Run the tests**

Run: `cd $WT/web && npx vitest run tests/unit/flashcardSession.test.ts tests/unit/flashcardSwipe.test.ts tests/unit/reviewView.test.ts tests/unit/dragMath.test.ts`
Expected: PASS. Then run `npx tsc -b --noEmit`. The old `FlashcardReview.tsx` constructs a session literal; change that one to `startSession()` so the type check stays clean.

- [ ] **Step 7: Commit**

```bash
pre-commit run --files web/src/lib/flashcardSession.ts web/src/lib/flashcardSwipe.ts web/src/portals/student/screens/flashcards/reviewView.ts web/tests/unit/flashcardSession.test.ts web/tests/unit/flashcardSwipe.test.ts web/tests/unit/reviewView.test.ts web/src/portals/student/screens/flashcards/FlashcardReview.tsx
git commit -S -m "feat(web): flashcard review model, combo and swipe stamps (L10)" -- web/src/lib/flashcardSession.ts web/src/lib/flashcardSwipe.ts web/src/portals/student/screens/flashcards/reviewView.ts web/tests/unit/flashcardSession.test.ts web/tests/unit/flashcardSwipe.test.ts web/tests/unit/reviewView.test.ts web/src/portals/student/screens/flashcards/FlashcardReview.tsx
```

---

### Task 8: Deck detail and new-deck sheet view models

**Files:**
- Create: `web/src/portals/student/screens/flashcards/deckView.ts`, `newDeckView.ts`
- Test: `web/tests/unit/deckView.test.ts`, `web/tests/unit/newDeckView.test.ts`

**Interfaces:**
- Produces:
  - `deckView.ts`:
    - `deckDetailView(deck: DeckDetailDTO, subjectName: string, dot: string): DeckDetailView`
    - `writingView(deck: { topic: string | null; origin: DeckOrigin; requestedCount: number | null }): WritingView`
    - `writingProgress(elapsedMs: number, requested: number): number`
    - `cardSourceLabel(source): string`
  - `newDeckView.ts`:
    - `COUNT_MIN = 1`, `COUNT_MAX = 50`, `COUNT_DEFAULT = 12`, `clampCount(n)`
    - `NewDeckMode`, `newDeckOptions(weak: WeakTopicDTO[], subjectCode: string): NewDeckOptionView[]`
    - `weaknessChips(weak, subjectCode): ChipView[]`, `topicChips(topics: string[]): ChipView[]`
    - `submitLabel(mode, count, pending): string`
    - `manualDeckRequest(...)` (moved from flashcardData.ts, unchanged)
    - `buildNewDeckRequest(input): NewDeckRequest`
    - `newDeckErrorMessage(err: { status?: number; detail?: unknown } | null): string`
    - `GENERATION_FAILED_TEXT`

- [ ] **Step 1: Write the failing tests**

```ts
// web/tests/unit/deckView.test.ts
import { describe, expect, it } from "vitest"
import { cardSourceLabel, deckDetailView, writingProgress, writingView } from "@/portals/student/screens/flashcards/deckView"
import type { CardDTO, DeckDetailDTO } from "@/lib/flashcardTypes"

const card = (id: string, source: CardDTO["source"]): CardDTO => ({
  id, front: `F${id}`, back: `B${id}`, position: 1, source, sourceQuestionId: null, repetitions: 0,
  easeFactor: 2.5, intervalDays: 0, lapses: 0, dueAt: "2026-11-16T08:00:00Z", lastReviewedAt: null,
  nextIntervalDays: { again: 0, hard: 1, good: 1, easy: 1 },
})

function deck(o: Partial<DeckDetailDTO> = {}): DeckDetailDTO {
  return {
    id: "d", subjectCode: "0580", topic: "E7 Vectors", title: "Vectors", description: null,
    origin: "weakness", dueCount: 9, newCount: 4, learningCount: 8, knownCount: 6, marksLost: 9,
    generationStatus: "ready", requestedCount: 18, cards: [card("1", "ai"), card("2", "manual")], ...o,
  }
}

describe("deckDetailView", () => {
  it("builds the header, origin line, legend, review button and card rows", () => {
    const v = deckDetailView(deck(), "Maths", "var(--color-grade-a)")
    expect(v.title).toBe("Vectors")
    expect(v.sub).toBe("Maths · 2 cards")
    expect(v.originLine).toBe("From a weakness · cost you 9 marks")
    expect(v.legend).toEqual(["6 known", "8 learning", "4 new"])
    expect(v.review).toEqual({ label: "Review 9 due", enabled: true })
    expect(v.cards.map((c) => [c.id, c.ai])).toEqual([["1", true], ["2", false]])
    expect(v.emptyCards).toBe(false)
    expect(v.state).toBe("ready")
  })

  it("disables review when nothing is due and flags an empty deck", () => {
    const v = deckDetailView(deck({ dueCount: 0, cards: [], origin: "manual", marksLost: null }), "Maths", "x")
    expect(v.review).toEqual({ label: "Nothing due", enabled: false })
    expect(v.originLine).toBe("Written by you")
    expect(v.emptyCards).toBe(true)
  })

  it("passes writing and failed through as states", () => {
    expect(deckDetailView(deck({ generationStatus: "writing" }), "Maths", "x").state).toBe("writing")
    expect(deckDetailView(deck({ generationStatus: "failed" }), "Maths", "x").state).toBe("failed")
  })
})

describe("writing", () => {
  it("names the count and the topic, and why for a weakness deck", () => {
    expect(writingView({ topic: "E7 Vectors", origin: "weakness", requestedCount: 12 })).toEqual({
      title: "Writing 12 cards…",
      body: "On Vectors, from the questions that cost you marks.",
      hint: "You can leave. The deck shows up when it's ready.",
    })
    expect(writingView({ topic: "1 Motion", origin: "topic", requestedCount: 1 }).body).toBe("On Motion.")
  })

  it("eases toward 90% and never claims done", () => {
    expect(writingProgress(0, 12)).toBe(0)
    expect(writingProgress(1_000_000, 12)).toBe(0.9)
    const mid = writingProgress(7_500, 12)
    expect(mid).toBeGreaterThan(0.3)
    expect(mid).toBeLessThan(0.9)
  })
})

it("keeps the two source labels distinct", () => {
  expect(cardSourceLabel("ai")).toBe("AI-generated")
  expect(cardSourceLabel("manual")).toBe("Your card")
})
```

```ts
// web/tests/unit/newDeckView.test.ts
import { describe, expect, it } from "vitest"
import {
  buildNewDeckRequest,
  clampCount,
  manualDeckRequest,
  newDeckErrorMessage,
  newDeckOptions,
  submitLabel,
  topicChips,
  weaknessChips,
} from "@/portals/student/screens/flashcards/newDeckView"
import type { WeakTopicDTO } from "@/lib/flashcardTypes"

const weak: WeakTopicDTO[] = [
  { subjectCode: "0580", topic: "E7 Vectors", marksLost: 9, accuracyPct: 41 },
  { subjectCode: "0580", topic: "E2 Algebra", marksLost: 5, accuracyPct: 58 },
  { subjectCode: "0625", topic: "3 Waves", marksLost: 6, accuracyPct: 50 },
]

describe("options and chips", () => {
  it("offers three modes and disables weakness with no recorded weak topics", () => {
    expect(newDeckOptions(weak, "0580").map((o) => [o.mode, o.title, o.sub, o.disabled])).toEqual([
      ["weakness", "From a weakness", "Cards on what cost you marks", false],
      ["topic", "For a topic", "Pick any syllabus topic", false],
      ["manual", "Write my own", "Type your own cards", false],
    ])
    expect(newDeckOptions(weak, "0606")[0]).toMatchObject({ sub: "Needs a marked paper first", disabled: true })
  })

  it("shows one subject's weak topics with accuracy, and plain topic chips", () => {
    expect(weaknessChips(weak, "0580")).toEqual([
      { topic: "E7 Vectors", label: "Vectors", badge: "41%" },
      { topic: "E2 Algebra", label: "Algebra", badge: "58%" },
    ])
    expect(topicChips(["1 Motion", "3 Waves"])).toEqual([
      { topic: "1 Motion", label: "Motion", badge: null },
      { topic: "3 Waves", label: "Waves", badge: null },
    ])
  })
})

describe("count, labels, requests", () => {
  it("clamps the count to 1-50", () => {
    expect([clampCount(0), clampCount(12), clampCount(99)]).toEqual([1, 12, 50])
  })

  it("labels the button for each mode and while pending", () => {
    expect(submitLabel("weakness", 12, false)).toBe("Make 12 cards")
    expect(submitLabel("topic", 1, false)).toBe("Make 1 card")
    expect(submitLabel("manual", 12, false)).toBe("Make deck")
    expect(submitLabel("topic", 12, true)).toBe("Starting…")
  })

  it("builds a generate request for weakness and topic, and needs a topic", () => {
    expect(
      buildNewDeckRequest({ mode: "weakness", subjectCode: "0580", subjectName: "Maths", topic: "E7 Vectors", count: 12, title: "" }),
    ).toEqual({
      kind: "generate",
      body: { subjectCode: "0580", origin: "weakness", count: 12, topic: "E7 Vectors", title: null },
    })
    expect(
      buildNewDeckRequest({ mode: "topic", subjectCode: "0580", subjectName: "Maths", topic: null, count: 12, title: "" }),
    ).toEqual({ kind: "invalid", reason: "Pick a topic first." })
  })

  it("keeps a manual deck manual even with a topic (provenance)", () => {
    expect(manualDeckRequest("0580", "Maths", "  ", " E7 Vectors ")).toEqual({
      subjectCode: "0580", title: "Maths deck", description: null, origin: "manual", topic: "E7 Vectors",
    })
    expect(
      buildNewDeckRequest({ mode: "manual", subjectCode: "0580", subjectName: "Maths", topic: null, count: 12, title: "Mine" }),
    ).toEqual({ kind: "create", body: manualDeckRequest("0580", "Maths", "Mine", "") })
  })
})

describe("newDeckErrorMessage", () => {
  it("maps each refusal to short, specific copy", () => {
    expect(newDeckErrorMessage({ status: 409, detail: { reason: "no_weaknesses" } })).toBe(
      "No weak topics yet. Mark a paper first.",
    )
    expect(newDeckErrorMessage({ status: 503 })).toBe("Card writing is off right now.")
    expect(newDeckErrorMessage({ status: 422 })).toBe("Pick a topic from the list.")
    expect(newDeckErrorMessage({ status: 500 })).toBe("Couldn't make the deck. Try again.")
    expect(newDeckErrorMessage(null)).toBe("Couldn't make the deck. Try again.")
  })
})
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd $WT/web && npx vitest run tests/unit/deckView.test.ts tests/unit/newDeckView.test.ts`
Expected: FAIL (modules not found).

- [ ] **Step 3: Implement `deckView.ts`**

```ts
// web/src/portals/student/screens/flashcards/deckView.ts
import type { CardSource, DeckDetailDTO, DeckOrigin } from "@/lib/flashcardTypes"
import { masteryView, originView, topicName, type MasteryView, type OriginIcon } from "./flashcardsView"

const plural = (n: number, w: string) => `${n} ${w}${n === 1 ? "" : "s"}`

/** Distinct both ways, never blank (P4.9 honesty rule 1). */
export function cardSourceLabel(source: CardSource): string {
  return source === "ai" ? "AI-generated" : "Your card"
}

export interface CardRowView {
  id: string
  front: string
  back: string
  ai: boolean
  sourceLabel: string
}

export interface DeckDetailView {
  title: string
  sub: string
  dot: string
  originIcon: OriginIcon
  originLine: string
  mastery: MasteryView
  legend: [string, string, string]
  review: { label: string; enabled: boolean }
  cards: CardRowView[]
  emptyCards: boolean
  state: DeckDetailDTO["generationStatus"]
}

export function deckDetailView(deck: DeckDetailDTO, subjectName: string, dot: string): DeckDetailView {
  const origin = originView(deck.origin)
  const mastery = masteryView(deck)
  return {
    title: deck.title,
    sub: `${subjectName} · ${plural(deck.cards.length, "card")}`,
    dot,
    originIcon: origin.icon,
    originLine: deck.marksLost ? `${origin.label} · cost you ${deck.marksLost} marks` : origin.label,
    mastery,
    legend: [`${mastery.known} known`, `${mastery.learning} learning`, `${mastery.fresh} new`],
    review: deck.dueCount > 0 ? { label: `Review ${deck.dueCount} due`, enabled: true } : { label: "Nothing due", enabled: false },
    cards: deck.cards.map((c) => ({
      id: c.id,
      front: c.front,
      back: c.back,
      ai: c.source === "ai",
      sourceLabel: cardSourceLabel(c.source),
    })),
    emptyCards: deck.cards.length === 0,
    state: deck.generationStatus,
  }
}

export interface WritingView {
  title: string
  body: string
  hint: string
}

export function writingView(deck: { topic: string | null; origin: DeckOrigin; requestedCount: number | null }): WritingView {
  const topic = deck.topic ? topicName(deck.topic) : "your topic"
  return {
    title: `Writing ${plural(deck.requestedCount ?? 0, "card")}…`,
    body: deck.origin === "weakness" ? `On ${topic}, from the questions that cost you marks.` : `On ${topic}.`,
    hint: "You can leave. The deck shows up when it's ready.",
  }
}

/** Honest-looking progress with no server progress to read: eases toward 0.9 over the expected
 * time (6 s plus 0.75 s a card) and never reaches 1 until the status says ready. */
export function writingProgress(elapsedMs: number, requested: number): number {
  const expectedMs = (6 + 0.75 * Math.max(1, requested)) * 1000
  const p = 0.9 * (1 - Math.exp(-elapsedMs / expectedMs))
  return Math.min(0.9, Math.round(p * 1000) / 1000)
}
```

The test expects exactly `0.9` for a huge elapsed time. `1 - exp(-big)` is 1, so 0.9 × 1 = 0.9. The `min` guards rounding.

- [ ] **Step 4: Implement `newDeckView.ts`**

```ts
// web/src/portals/student/screens/flashcards/newDeckView.ts
import type { CreateDeckRequest, GenerateDeckRequest, WeakTopicDTO } from "@/lib/flashcardTypes"
import { topicName } from "./flashcardsView"

export type NewDeckMode = "weakness" | "topic" | "manual"
export const COUNT_MIN = 1
export const COUNT_MAX = 50
export const COUNT_DEFAULT = 12
export const GENERATION_FAILED_TEXT = "Couldn't write the cards. Nothing was saved."

export function clampCount(n: number): number {
  return Math.min(COUNT_MAX, Math.max(COUNT_MIN, Math.round(n)))
}

export interface NewDeckOptionView {
  mode: NewDeckMode
  title: string
  sub: string
  disabled: boolean
}

export function newDeckOptions(weak: readonly WeakTopicDTO[], subjectCode: string): NewDeckOptionView[] {
  const hasWeak = weak.some((t) => t.subjectCode === subjectCode)
  return [
    {
      mode: "weakness",
      title: "From a weakness",
      sub: hasWeak ? "Cards on what cost you marks" : "Needs a marked paper first",
      disabled: !hasWeak,
    },
    { mode: "topic", title: "For a topic", sub: "Pick any syllabus topic", disabled: false },
    { mode: "manual", title: "Write my own", sub: "Type your own cards", disabled: false },
  ]
}

export interface ChipView {
  topic: string
  label: string
  badge: string | null
}

export function weaknessChips(weak: readonly WeakTopicDTO[], subjectCode: string): ChipView[] {
  return weak
    .filter((t) => t.subjectCode === subjectCode)
    .map((t) => ({ topic: t.topic, label: topicName(t.topic), badge: `${t.accuracyPct}%` }))
}

export function topicChips(topics: readonly string[]): ChipView[] {
  return topics.map((t) => ({ topic: t, label: topicName(t), badge: null }))
}

export function submitLabel(mode: NewDeckMode, count: number, pending: boolean): string {
  if (pending) return "Starting…"
  if (mode === "manual") return "Make deck"
  return `Make ${count} card${count === 1 ? "" : "s"}`
}

/** "Write my own": origin stays `manual` even with a topic (a typed topic is not a model writing
 * cards). Blank title → "<Subject> deck"; blank topic → null, never "". */
export function manualDeckRequest(
  subjectCode: string,
  subjectName: string,
  title: string,
  topic: string,
): CreateDeckRequest {
  return {
    subjectCode,
    title: title.trim() || `${subjectName} deck`,
    description: null,
    origin: "manual",
    topic: topic.trim() || null,
  }
}

export type NewDeckRequest =
  | { kind: "generate"; body: GenerateDeckRequest }
  | { kind: "create"; body: CreateDeckRequest }
  | { kind: "invalid"; reason: string }

export function buildNewDeckRequest(input: {
  mode: NewDeckMode
  subjectCode: string
  subjectName: string
  topic: string | null
  count: number
  title: string
}): NewDeckRequest {
  if (input.mode === "manual") {
    return { kind: "create", body: manualDeckRequest(input.subjectCode, input.subjectName, input.title, input.topic ?? "") }
  }
  if (!input.topic) return { kind: "invalid", reason: "Pick a topic first." }
  return {
    kind: "generate",
    body: {
      subjectCode: input.subjectCode,
      origin: input.mode,
      count: clampCount(input.count),
      topic: input.topic,
      title: input.title.trim() || null,
    },
  }
}

/** Structural, so this file never imports `lib/api.ts` (which touches browser globals). */
export function newDeckErrorMessage(err: { status?: number; detail?: unknown } | null): string {
  if (err?.status === 409) {
    const reason = (err.detail as { reason?: string } | undefined)?.reason
    if (reason === "no_weaknesses") return "No weak topics yet. Mark a paper first."
    return reason ? `That deck can't be made right now (${reason}).` : "That deck can't be made right now."
  }
  if (err?.status === 503) return "Card writing is off right now."
  if (err?.status === 422) return "Pick a topic from the list."
  return "Couldn't make the deck. Try again."
}
```

- [ ] **Step 5: Run the tests**

Run: `cd $WT/web && npx vitest run tests/unit/deckView.test.ts tests/unit/newDeckView.test.ts tests/unit/flashcardsView.test.ts`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
pre-commit run --files web/src/portals/student/screens/flashcards/deckView.ts web/src/portals/student/screens/flashcards/newDeckView.ts web/tests/unit/deckView.test.ts web/tests/unit/newDeckView.test.ts
git commit -S -m "feat(web): flashcard deck and new-deck view models (L10)" -- web/src/portals/student/screens/flashcards/deckView.ts web/src/portals/student/screens/flashcards/newDeckView.ts web/tests/unit/deckView.test.ts web/tests/unit/newDeckView.test.ts
```

---

## Screens (designer agent)

Every screen task goes to the `designer` agent. Before any UI edit, the designer:
- invokes the `impeccable` skill
- reads `.claude/skills/impeccable/reference/craft-floor.md`
- reads the three taste memories
- opens `.impeccable/mocks/student-r2/cards-final.html` in a browser next to the app

Screens stay thin. Every string, count, mood and branch comes from the view models (Tasks 6–8). If a screen needs a new decision, add it to the view model with a test first.

**Mock class → Tailwind/token map** (used throughout):

| Mock | Tailwind / token |
|---|---|
| `--p` | `text-primary` / `bg-primary` |
| `--pc` | `bg-primary-container` |
| `--v` | `text-on-surface-variant` |
| `--ink` | `text-on-surface` |
| `--ov` hairline `box-shadow:0 -1px 0 var(--ov)` | `shadow-[0_-1px_0_var(--color-outline-variant)]` (first row none) |
| `--o` | `outline` colour (`shadow-[inset_0_0_0_1.5px_var(--color-outline)]`) |
| `--sh` | `bg-surface-container-high` |
| `--sc` | `bg-surface-container` |
| `--s` | `bg-surface` |
| `--ok` | `text-success-text` / `bg-success-text` |
| `--okc` | `bg-success-container`, text `text-on-success-container` |
| `--errc` / `--onerrc` | `bg-error-container` / `text-on-error-container` |
| `--tide` | `bg-inverse-primary` |
| `--gold` | `text-tertiary` (combo flame and ring only) |
| Hard button `oklch(.95 .05 80)`/`oklch(.38 .08 70)` | `bg-tertiary-container text-on-tertiary-container` |
| `.syncb` `oklch(.96 .03 80)`/`oklch(.38 .08 70)` | `bg-tertiary-container text-on-tertiary-container` |
| `.sic.t` violet `oklch(.94 .04 300)` | `bg-secondary-container text-on-secondary-container` (no violet token; listed in PR) |
| `'Bricolage Grotesque'` | `font-display` |
| `'Schibsted Grotesk'` | `font-sans` |
| `'JetBrains Mono'` | `font-mono` |
| `.sjhd h1` 800 28px/1.1, −.03em | `font-display text-[28px] leading-[1.1] font-extrabold tracking-[-0.03em] text-primary` |
| `.dtop h1` 800 32px | same at `text-[32px]` |
| `.sjh2` 800 18px −.01em | `font-sans text-[18px] font-extrabold tracking-[-0.01em] text-on-surface` |
| `.sh2` 800 22px | `font-sans text-[22px] font-extrabold text-on-surface` |
| `.at b` 700 15px / `.at span` 13px | `text-[15px] font-bold` / `text-[13px] text-on-surface-variant` |
| `.btn.big4.go2` | `min-h-[50px] w-full rounded-[18px] bg-primary px-7 text-[15.5px] font-bold text-on-primary shadow-[0_14px_24px_-16px_oklch(0.3_0.07_242/0.7)]` |
| `.icl` 44×44 r14 | `grid size-11 place-items-center rounded-[14px] bg-primary-container text-primary`; `.icl.nd` → `bg-primary text-on-primary` |
| `.lnk` | `min-h-11 font-bold text-[15px] text-primary` (mock tide on light fails contrast; primary used, listed in PR) |
| `.sjpad` gap 24 | `flex flex-col gap-6 px-[18px] pb-24 pt-2` (shell owns the bottom inset) |
| `.err2` | `grid flex-1 content-center justify-items-center gap-3 px-2 py-6 text-center`; h2 `font-display text-[28px] font-extrabold leading-[1.15] tracking-[-0.02em] text-primary`; p `text-[15px] leading-[1.4] text-on-surface-variant max-w-[30ch]` |

### Task 9: Flashcard parts and keyframes

**Files:**
- Create: `web/src/portals/student/screens/flashcards/flashcards.css`
- Create: `parts/SubjectDot.tsx`, `parts/MasteryBar.tsx`, `parts/OriginTag.tsx`, `parts/DueCount.tsx`, `parts/DeckRow.tsx`, `parts/CountStepper.tsx`, `parts/FcSheet.tsx`, `parts/AiMark.tsx`
- Test: covered by Tasks 15 (Playwright) and 16 (fidelity). No jsdom, so no component unit tests.

**Interfaces:**
- Consumes: `DeckRowView`, `MasteryView`, `OriginIcon` (Task 6).
- Produces:
  - `SubjectDot({ color })`, `MasteryBar({ mastery, size?: "row" | "detail" })`, `MasteryLegend({ legend })`
  - `OriginTag({ icon, children })`, `DueCount({ due })`
  - `DeckRow({ row, selected?, onOpen, onLongPress })`
  - `CountStepper({ value, onChange, min, max, label })`
  - `FcSheet({ open, onOpenChange, title, alert?, children })`
  - `AiMark({ label })`

- [ ] **Step 1: Keyframes**

```css
/* web/src/portals/student/screens/flashcards/flashcards.css
 * L10 · keyframes only. Values from .impeccable/mocks/student-r2/fc.css (flip) and the motion
 * table in the L10 plan. Every user is guarded by a motion-reduce class at the call site. */
@keyframes fc-flip {
  from { transform: rotateY(-80deg); opacity: 0.3; }
}
@keyframes fc-rise {
  from { transform: translateY(12px) scale(0.94); opacity: 0.6; }
}
@keyframes fc-out-right {
  to { transform: translateX(120%) rotate(18deg); opacity: 0; }
}
@keyframes fc-out-left {
  to { transform: translateX(-120%) rotate(-18deg); opacity: 0; }
}
```

- [ ] **Step 2: Small parts**

```tsx
// parts/SubjectDot.tsx
export function SubjectDot({ color }: { color: string }) {
  return <i aria-hidden className="inline-block size-2 flex-none rounded-full" style={{ background: color }} />
}
```

```tsx
// parts/MasteryBar.tsx
import type { MasteryView } from "../flashcardsView"

/** fc.css `.mstr`: 6px (row, max 180px) or 10px (detail, full width); known = success, learning = tide. */
export function MasteryBar({ mastery, size = "row" }: { mastery: MasteryView; size?: "row" | "detail" }) {
  return (
    <div
      role="img"
      aria-label={mastery.label}
      className={
        size === "row"
          ? "flex h-1.5 max-w-[180px] overflow-hidden rounded-[3px] bg-surface-container-high"
          : "flex h-2.5 overflow-hidden rounded-[5px] bg-surface-container-high"
      }
    >
      <i className="block h-full bg-success-text" style={{ width: `${mastery.knownPct}%` }} />
      <i className="block h-full bg-inverse-primary" style={{ width: `${mastery.learningPct}%` }} />
    </div>
  )
}

export function MasteryLegend({ legend }: { legend: readonly [string, string, string] }) {
  const swatch = ["bg-success-text", "bg-inverse-primary", "bg-surface-container-high"]
  return (
    <div className="flex gap-3.5 text-[13px] font-medium text-on-surface-variant">
      {legend.map((text, i) => (
        <span key={text} className="inline-flex items-center gap-1.5">
          <i aria-hidden className={`size-2.5 rounded-[3px] ${swatch[i]}`} />
          <span className="font-mono">{text.split(" ")[0]}</span> {text.split(" ").slice(1).join(" ")}
        </span>
      ))}
    </div>
  )
}
```

```tsx
// parts/OriginTag.tsx
import { PencilSimple, Sparkle, Target } from "@phosphor-icons/react"
import type { ReactNode } from "react"
import type { OriginIcon } from "../flashcardsView"

const ICON = { target: Target, sparkle: Sparkle, pen: PencilSimple } as const

/** fc.css `.og`: 500 13px, gap 5px, variant colour, 14px glyph. */
export function OriginTag({ icon, children }: { icon: OriginIcon; children: ReactNode }) {
  const Glyph = ICON[icon]
  return (
    <span className="inline-flex items-center gap-[5px] text-[13px] font-medium text-on-surface-variant">
      <Glyph size={14} weight="bold" aria-hidden />
      {children}
    </span>
  )
}
```

```tsx
// parts/DueCount.tsx
import { Check } from "@phosphor-icons/react"

/** fc.css `.due`: Mono 800 18px primary over a 12px "due"; zero shows a success tick. */
export function DueCount({ due }: { due: number }) {
  if (due === 0) {
    return (
      <span className="grid min-w-11 justify-items-center text-success-text">
        <Check size={16} weight="bold" aria-label="Nothing due" />
      </span>
    )
  }
  return (
    <span className="grid min-w-11 justify-items-center font-mono text-[18px] font-extrabold leading-none text-primary">
      {due}
      <small className="mt-0.5 font-sans text-[12px] font-semibold text-on-surface-variant">due</small>
    </span>
  )
}
```

```tsx
// parts/AiMark.tsx
import { Sparkle } from "@phosphor-icons/react"

/** Marks an AI-written card (P4.9 honesty rule 1). Visible glyph + "AI", full label for AT. */
export function AiMark({ label }: { label: string }) {
  return (
    <span className="inline-flex items-center gap-1 text-[12px] font-semibold text-on-surface-variant" aria-label={label}>
      <Sparkle size={12} weight="fill" aria-hidden />
      <span aria-hidden>AI</span>
    </span>
  )
}
```

```tsx
// parts/CountStepper.tsx
import { Minus, Plus } from "@phosphor-icons/react"

/** fc.css `.cnt` + t.css `.stepr`: label left; − value + right; 44px buttons, Bricolage 26px value. */
export function CountStepper({
  value, onChange, min, max, label,
}: { value: number; onChange: (n: number) => void; min: number; max: number; label: string }) {
  return (
    <div className="flex items-center justify-between text-[14px] font-semibold text-on-surface">
      <span id="fc-count-label">{label}</span>
      <div className="flex items-center gap-3" role="group" aria-labelledby="fc-count-label">
        <button type="button" aria-label="Fewer" disabled={value <= min} onClick={() => onChange(value - 1)}
          className="grid size-11 place-items-center rounded-[14px] bg-primary-container text-primary disabled:opacity-40">
          <Minus size={18} weight="bold" aria-hidden />
        </button>
        <output aria-live="polite" className="min-w-[2ch] text-center font-display text-[26px] font-extrabold leading-none text-primary">
          {value}
        </output>
        <button type="button" aria-label="More" disabled={value >= max} onClick={() => onChange(value + 1)}
          className="grid size-11 place-items-center rounded-[14px] bg-primary-container text-primary disabled:opacity-40">
          <Plus size={18} weight="bold" aria-hidden />
        </button>
      </div>
    </div>
  )
}
```

```tsx
// parts/FcSheet.tsx
import type { ReactNode } from "react"
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet"

/** pr.css `.rvl.leave.ssh`: white, r28 top, 22px 20px 26px padding, 12px gap, grabber (kit). */
export function FcSheet({
  open, onOpenChange, title, alert = false, children,
}: { open: boolean; onOpenChange: (open: boolean) => void; title: string; alert?: boolean; children: ReactNode }) {
  const heading = <SheetTitle className="font-sans text-[22px] font-extrabold text-on-surface">{title}</SheetTitle>
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="adaptive"
        role={alert ? "alertdialog" : "dialog"}
        aria-describedby={undefined}
        showCloseButton={false}
        nativeHeader={heading}
        nativeBodyClassName="px-5 pb-[26px] pt-3"
        className="sm:max-w-[420px]"
      >
        <div className="grid gap-3">
          <div className="hidden [[data-slot=sheet-content]:not(:has([data-native-header]))_&]:block">{heading}</div>
          {children}
        </div>
      </SheetContent>
    </Sheet>
  )
}
```

Implementation note for the designer: `SheetContent` renders `nativeHeader` "first in the content" when the frame is not native (sheet.tsx:58-60). So in the non-native case, do **not** render the title a second time. Delete the hidden duplicate `<div>` above once you confirm in the browser that the title appears exactly once in both frames. The rule is one `SheetTitle` per sheet; Radix logs an error without it.

- [ ] **Step 3: Deck row**

```tsx
// parts/DeckRow.tsx
import { CaretRight } from "@phosphor-icons/react"
import { useLongPress } from "@/lib/gestures/useLongPress"
import type { DeckRowView } from "../flashcardsView"
import { DueCount } from "./DueCount"
import { MasteryBar } from "./MasteryBar"
import { OriginTag } from "./OriginTag"

/**
 * fc.css `.dkr`: grid [1fr auto 18px], gap 12, padding 12px 0, hairline above; selected = `.dkr.on`
 * (primary-container, r14, inline padding 12). Long-press opens the deck menu (live K15).
 */
export function DeckRow({
  row, selected = false, onOpen, onLongPress,
}: { row: DeckRowView; selected?: boolean; onOpen: () => void; onLongPress: () => void }) {
  const longPress = useLongPress({ onLongPress })
  return (
    <li className="[&+li>button]:shadow-[0_-1px_0_var(--color-outline-variant)]">
      <button
        type="button"
        onClick={onOpen}
        aria-current={selected ? "true" : undefined}
        {...longPress}
        className={[
          "group grid w-full grid-cols-[minmax(0,1fr)_auto_18px] items-center gap-3 py-3 text-start text-on-surface",
          "focus-visible:rounded-[14px] focus-visible:outline-[2.5px] focus-visible:outline-offset-2 focus-visible:outline-primary",
          selected ? "rounded-[14px] bg-primary-container px-3 !shadow-none" : "",
        ].join(" ")}
      >
        <span className="grid gap-1">
          <b className="text-[15px] font-bold group-hover:text-primary">{row.title}</b>
          {row.statusLine ? (
            <span className={row.status === "failed" ? "text-[13px] font-semibold text-on-error-container" : "text-[13px] text-on-surface-variant"}>
              {row.statusLine}
            </span>
          ) : (
            <>
              <OriginTag icon={row.originIcon}>{row.meta}</OriginTag>
              <MasteryBar mastery={row.mastery} />
            </>
          )}
        </span>
        {row.status === "ready" ? <DueCount due={row.due} /> : <span />}
        <CaretRight size={18} aria-hidden className="text-on-surface-variant" />
      </button>
    </li>
  )
}
```

Check the real `useLongPress` return type (`web/src/lib/gestures/useLongPress.ts`). The live `DeckRow` spreads it onto a `Card`, so spreading it onto a `<button>` is fine. If it returns a `ref`, merge it.

- [ ] **Step 4: Type check and lint**

Run: `cd $WT/web && npx tsc -b --noEmit && npx oxlint src/portals/student/screens/flashcards/parts && npm run check:native`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
pre-commit run --files web/src/portals/student/screens/flashcards/flashcards.css web/src/portals/student/screens/flashcards/parts/*.tsx
git commit -S -m "feat(web): flashcard parts and keyframes (L10)" -- web/src/portals/student/screens/flashcards/flashcards.css web/src/portals/student/screens/flashcards/parts
```

---

### Task 10: Decks screen (FD, FS, FZ, FL, FE, FDD) and routes

**Files:**
- Create: `FlashcardsScreen.tsx`, `DecksStates.tsx`
- Modify: `web/src/portals/student/index.tsx` (flashcard routes), `web/src/portals/student/data.ts` (`currentSubjectCode` arm, crumbs)
- Test: Task 15 Playwright; `web/tests/unit/navigation.test.ts` (run, extend by one path)

**Interfaces:**
- Consumes:
  - hooks: `useFlashcardDecks`, `useDueSession`, `useWeakTopics` (Task 5), plus `useOverview` (enrolled subjects) and `useSubjectName`/`useReference` (names)
  - `decksScreenView` (Task 6)
  - F1: `Binny`, `Walkthrough`, `HairRows`
- Produces: `FlashcardsScreen` (named export), `DeckPanel` slot filled by Task 12, `NewDeckSheet` opener filled by Task 11. Until those tasks land, `FlashcardsScreen` imports them from stub files that Tasks 11–12 replace. The stubs return `null` and are never committed past Task 12 (see Step 6).

Component tree:

```
FlashcardsScreen
├─ header: phone `.sjhd` (h1 + sub + "+" icl.nd) | desktop `.dtop` (h1 + sub + Review button + "+")
├─ view.kind === "loading" → <DecksLoading/>
├─ view.kind === "error"   → <DecksError onRetry/>
├─ view.kind === "empty"   → <EmptyShelf weakHint onPick(mode)/>
└─ view.kind === "ready"
   ├─ grid lg:[1fr_320px] xl:[1fr_340px]
   │  ├─ list column
   │  │  ├─ Hero (Binny happy 64 + headline/sub) + Review button (phone/tablet only)
   │  │  ├─ groups.map → <section><h2 dot+name/><HairRows>{DeckRow…}</HairRows></section>
   │  │  └─ sparse → <SparseTip/> + <Walkthrough steps=2/>
   │  └─ <aside hidden lg:flex> <DeckPanel deckId={selected}/> (Task 12)
   ├─ <NewDeckSheet …/> (Task 11)
   └─ <DeckMenu …/> for long-press (Task 12)
```

- [ ] **Step 1: States file**

```tsx
// DecksStates.tsx
import { CaretRight, PencilSimple, Sparkle, Target } from "@phosphor-icons/react"
import { Link } from "react-router-dom"
import { Binny, Walkthrough } from "@/components/redesign"
import { SkeletonBlock } from "@/components/ui/skeleton"
import type { NewDeckMode } from "./newDeckView"

/** FL: 64 r16, 56 r16, 120×20, 4 × 60 r14 (fc.js `put('FL',…)`). */
export function DecksLoading() {
  return (
    <div className="grid gap-3.5" aria-busy="true" aria-label="Loading your decks">
      <SkeletonBlock className="h-16 rounded-2xl" />
      <SkeletonBlock className="h-14 rounded-2xl" />
      <SkeletonBlock className="h-5 w-[120px] rounded-[10px]" />
      {[0, 1, 2, 3].map((i) => <SkeletonBlock key={i} className="h-[60px] rounded-[14px]" />)}
    </div>
  )
}

/** FE. */
export function DecksError({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="grid flex-1 content-center justify-items-center gap-3 px-2 py-6 text-center" role="alert">
      <Binny mood="sad" size={96} />
      <h2 className="mt-1.5 font-display text-[28px] font-extrabold leading-[1.15] tracking-[-0.02em] text-primary">
        We couldn’t load your decks
      </h2>
      <p className="mb-1.5 max-w-[30ch] text-[15px] leading-[1.4] text-on-surface-variant">Check your connection, then try again.</p>
      <button type="button" onClick={onRetry} className="min-h-[50px] w-full rounded-[18px] bg-primary px-7 text-[15.5px] font-bold text-on-primary">
        Try again
      </button>
      <Link to="/student" className="inline-flex min-h-11 items-center px-3.5 text-[15px] font-bold text-primary">Back to Home</Link>
    </div>
  )
}

const OPTIONS: { mode: NewDeckMode; icon: typeof Target; title: string; tone: string }[] = [
  { mode: "weakness", icon: Target, title: "From a weakness", tone: "bg-error-container text-on-error-container" },
  { mode: "topic", icon: Sparkle, title: "For a topic", tone: "bg-secondary-container text-on-secondary-container" },
  { mode: "manual", icon: PencilSimple, title: "Write my own", tone: "bg-primary-container text-primary" },
]

/** FZ: Binny open 96, heading, line, then the three ways in (`.ndo` with chevrons). */
export function EmptyShelf({ weakHint, onPick }: { weakHint: string | null; onPick: (mode: NewDeckMode) => void }) {
  const subs: Record<NewDeckMode, string> = {
    weakness: weakHint ?? "Cards on what cost you marks",
    topic: "Pick any syllabus topic",
    manual: "Type your own cards",
  }
  return (
    <div className="flex flex-col gap-6">
      <div className="grid justify-items-center gap-3 pt-3 text-center">
        <Binny mood="open" size={96} />
        <h2 className="mt-1.5 font-display text-[28px] font-extrabold leading-[1.15] tracking-[-0.02em] text-primary">Nothing on the shelf yet</h2>
        <p className="max-w-[30ch] text-[15px] leading-[1.4] text-on-surface-variant">Make a deck from what cost you marks. Lemely writes the cards.</p>
      </div>
      <div className="grid gap-2">
        {OPTIONS.map((o, i) => (
          <button key={o.mode} type="button" onClick={() => onPick(o.mode)}
            className={[
              "grid min-h-[60px] grid-cols-[40px_minmax(0,1fr)_auto] items-center gap-3 rounded-2xl bg-surface-container-lowest px-3 py-2.5 text-start text-on-surface",
              i === 0 ? "bg-primary-container shadow-[inset_0_0_0_2px_var(--color-primary)]" : "shadow-[inset_0_0_0_1.5px_var(--color-outline-variant)]",
            ].join(" ")}>
            <span className={`grid size-10 place-items-center rounded-xl ${o.tone}`}><o.icon size={16} weight="bold" aria-hidden /></span>
            <span className="grid"><b className="text-[15px] font-bold">{o.title}</b><span className="text-[13px] text-on-surface-variant">{subs[o.mode]}</span></span>
            <CaretRight size={18} aria-hidden className="text-on-surface-variant" />
          </button>
        ))}
      </div>
    </div>
  )
}

/** FS extras: `.tipr` + `.walk2` (2 steps). */
export function SparseExtras({
  tip, onMakeTip,
}: { tip: { title: string; body: string } | null; onMakeTip: () => void }) {
  return (
    <>
      {tip ? (
        <div className="flex items-center justify-between gap-3 py-3 shadow-[0_-1px_0_var(--color-outline-variant)]">
          <span className="grid"><b className="text-[15px] font-bold">{tip.title}</b><span className="text-[13px] text-on-surface-variant">{tip.body}</span></span>
          <button type="button" onClick={onMakeTip} className="relative min-h-11 rounded-[14px] bg-primary px-4 text-[14px] font-bold text-on-primary">Make it</button>
        </div>
      ) : null}
      <Walkthrough
        steps={[
          { icon: Sparkle, title: "A few minutes a day", body: "Cards show up here when they’re due." },
          { icon: Target, title: "Be honest when you rate", body: "Again brings a card back soon. Easy sends it away for a week." },
        ]}
      />
    </>
  )
}
```

- [ ] **Step 2: The screen**

```tsx
// FlashcardsScreen.tsx
import { Plus } from "@phosphor-icons/react"
import { useMemo, useState } from "react"
import { useNavigate, useParams, useSearchParams } from "react-router-dom"
import { Binny, HairRows } from "@/components/redesign"
import { useDueSession, useFlashcardDecks, useWeakTopics } from "@/lib/hooks/useFlashcardApi"
import { useReference } from "@/lib/hooks/useReferenceApi"
import { useOverview } from "@/lib/hooks/useStudentApi"
import { DecksError, DecksLoading, EmptyShelf, SparseExtras } from "./DecksStates"
import { DeckMenu } from "./DeckMenu"
import { DeckPanel } from "./DeckBody"
import { NewDeckSheet, type NewDeckSeed } from "./NewDeckSheet"
import { decksScreenView } from "./flashcardsView"
import { DeckRow } from "./parts/DeckRow"
import { SubjectDot } from "./parts/SubjectDot"

/** ≥1024 is list + side panel (plan: Frame-to-state table). Read at tap time; no resize state. */
export const WIDE_QUERY = "(min-width: 1024px)"
export const isWide = () => typeof window !== "undefined" && window.matchMedia(WIDE_QUERY).matches

const PRIMARY_BTN =
  "min-h-[50px] rounded-[18px] bg-primary px-7 text-[15.5px] font-bold text-on-primary shadow-[0_14px_24px_-16px_oklch(0.3_0.07_242/0.7)] focus-visible:outline-[2.5px] focus-visible:outline-offset-2 focus-visible:outline-primary"

export function FlashcardsScreen() {
  const navigate = useNavigate()
  const { subjectCode } = useParams<{ subjectCode?: string }>()
  const [params, setParams] = useSearchParams()
  const filterSubject = subjectCode ?? null

  const decks = useFlashcardDecks()
  const due = useDueSession({ subjectCode: filterSubject })
  const weak = useWeakTopics()
  const overview = useOverview()
  const reference = useReference()

  const [sheet, setSheet] = useState<NewDeckSeed | null>(null)
  const [menuDeckId, setMenuDeckId] = useState<string | null>(null)

  const subjectOrder = useMemo(() => (overview.data?.subjects ?? []).map((s) => s.code), [overview.data])
  const subjectName = (code: string) =>
    overview.data?.subjects.find((s) => s.code === code)?.name ??
    reference.data?.subjects?.find((s: { code: string; name: string }) => s.code === code)?.name ??
    code

  const view = decksScreenView({
    decks: decks.data,
    decksStatus: decks.status,
    due: due.data,
    dueStatus: due.status,
    weakTopics: weak.data ?? [],
    subjectName,
    subjectOrder,
    filterSubject,
    now: new Date(),
  })

  const selectedId = view.kind === "ready" ? params.get("deck") ?? view.firstDeckId : null
  const reviewTo = filterSubject ? `/student/flashcards/review?subject=${filterSubject}` : "/student/flashcards/review"
  const defaultSubject = filterSubject ?? weak.data?.[0]?.subjectCode ?? subjectOrder[0] ?? ""

  function openDeck(id: string) {
    if (isWide()) setParams((p) => { p.set("deck", id); return p }, { replace: true })
    else navigate(`/student/flashcards/deck/${id}`)
  }

  const header = view.kind === "ready" ? view.header : { title: "Flashcards", sub: view.kind === "empty" ? "No decks yet" : "" }
  const newDeckButton = (
    <button type="button" aria-label="New deck" onClick={() => setSheet({ mode: null, subjectCode: defaultSubject, topic: null })}
      className="grid size-11 flex-none place-items-center rounded-[14px] bg-primary text-on-primary focus-visible:outline-[2.5px] focus-visible:outline-offset-2 focus-visible:outline-primary">
      <Plus size={18} weight="bold" aria-hidden />
    </button>
  )

  return (
    <div className="mx-auto flex w-full max-w-[640px] flex-col lg:max-w-none">
      {/* `.sjhd` (phone/tablet) and `.dtop` (desktop) in one header. */}
      <header className="flex items-center gap-2.5 px-4 pb-1.5 pt-3.5 lg:gap-5 lg:px-10 lg:pb-2 lg:pt-6">
        <div className="min-w-0 flex-1">
          <h1 className="font-display text-[28px] font-extrabold leading-[1.1] tracking-[-0.03em] text-primary lg:text-[32px]">{header.title}</h1>
          {header.sub ? <span className="text-[13px] font-medium text-on-surface-variant">{header.sub}</span> : null}
        </div>
        {view.kind === "ready" && view.hero.reviewLabel ? (
          <button type="button" onClick={() => navigate(reviewTo)} className={`hidden lg:inline-block ${PRIMARY_BTN}`}>
            {view.hero.reviewLabel}
          </button>
        ) : null}
        {newDeckButton}
      </header>

      <div className="flex flex-col gap-6 px-[18px] pb-24 pt-2 lg:px-10">
        {view.kind === "loading" ? <DecksLoading /> : null}
        {view.kind === "error" ? <DecksError onRetry={() => void decks.refetch()} /> : null}
        {view.kind === "empty" ? (
          <EmptyShelf weakHint={view.weakHint} onPick={(mode) => setSheet({ mode, subjectCode: defaultSubject, topic: null })} />
        ) : null}
        {view.kind === "ready" ? (
          <div className="lg:grid lg:grid-cols-[minmax(0,1fr)_320px] lg:gap-6 xl:grid-cols-[minmax(0,1fr)_340px] xl:gap-10">
            <div className="flex flex-col gap-6">
              <section className="flex items-center gap-3">
                <Binny mood={view.hero.mood} size={64} motion="idle" />
                <div className="grid gap-0.5">
                  <b className="font-display text-[28px] font-extrabold leading-[1.1] tracking-[-0.02em] text-primary">{view.hero.headline}</b>
                  <span className="text-[14px] font-medium text-on-surface-variant">{view.hero.sub}</span>
                </div>
              </section>
              {view.hero.reviewLabel ? (
                <button type="button" onClick={() => navigate(reviewTo)} className={`w-full lg:hidden ${PRIMARY_BTN}`}>
                  {view.hero.reviewLabel}
                </button>
              ) : null}
              {view.groups.map((g) => (
                <section key={g.subjectCode} className="grid">
                  <h2 className="flex items-center gap-2 font-sans text-[18px] font-extrabold tracking-[-0.01em] text-on-surface">
                    <SubjectDot color={g.dot} />
                    {g.subjectName}
                  </h2>
                  <HairRows aria-label={`${g.subjectName} decks`}>
                    {g.decks.map((row) => (
                      <DeckRow key={row.id} row={row} selected={row.id === selectedId}
                        onOpen={() => openDeck(row.id)} onLongPress={() => setMenuDeckId(row.id)} />
                    ))}
                  </HairRows>
                </section>
              ))}
              {view.sparse ? (
                <SparseExtras tip={view.sparse.tip}
                  onMakeTip={() => view.sparse?.tip && setSheet({ mode: "weakness", subjectCode: view.sparse.tip.subjectCode, topic: view.sparse.tip.topic })} />
              ) : null}
            </div>
            {selectedId ? (
              <aside className="hidden min-h-0 lg:flex" aria-label="Deck">
                <DeckPanel deckId={selectedId} onDeleted={() => setParams((p) => { p.delete("deck"); return p }, { replace: true })} />
              </aside>
            ) : null}
          </div>
        ) : null}
      </div>

      <NewDeckSheet seed={sheet} onClose={() => setSheet(null)}
        onStarted={(deckId) => { setSheet(null); openDeck(deckId) }} />
      <DeckMenu deckId={menuDeckId} onClose={() => setMenuDeckId(null)} />
    </div>
  )
}
```

Notes for the designer:
- Check the shape of `useReference().data` (`web/src/lib/hooks/useReferenceApi.ts:25`). If `useSubjectName` is the cheaper lookup, build `subjectName` from the reference data the way `useSubjectName` does internally; a hook cannot be called inside the callback.
- `HairRows` is the F1 `<ul>`. `DeckRow` renders `<li>`, so nesting is valid. If F1's `HairRows` already draws hairlines between children, drop the `[&+li>button]` shadow from `DeckRow`.
- The hero on the desktop list column keeps Binny (one per screen). `DeckPanel` never renders Binny.

- [ ] **Step 3: Routes**

In `web/src/portals/student/index.tsx`, replace the two flashcard lazy imports and route entries with:

```tsx
const FlashcardsScreen = lazy(() =>
  import("./screens/flashcards/FlashcardsScreen").then((m) => ({ default: m.FlashcardsScreen })),
)
const DeckScreen = lazy(() =>
  import("./screens/flashcards/DeckScreen").then((m) => ({ default: m.DeckScreen })),
)
const ReviewScreen = lazy(() =>
  import("./screens/flashcards/ReviewScreen").then((m) => ({ default: m.ReviewScreen })),
)
```

```tsx
    { path: "flashcards", element: <FlashcardsScreen />, handle: { title: "Flashcards", skeleton: "list" } },
    { path: "flashcards/deck/:deckId", element: <DeckScreen />, handle: { title: "Deck", skeleton: "list" } },
    {
      path: "flashcards/review",
      element: <ReviewScreen />,
      handle: { title: "Flashcard review", skeleton: "page-header", immersive: true },
    },
    { path: "flashcards/review/:subjectCode", element: <LegacyReviewRedirect /> },
    { path: "flashcards/:subjectCode", element: <FlashcardsScreen />, handle: { title: "Flashcards", skeleton: "list" } },
```

Add near the other small helpers in `index.tsx` (`Navigate`, `useParams` from react-router-dom are likely already imported; add them if not):

```tsx
/** Old `/student/flashcards/review/:subjectCode` links (N3) land on the scoped review. */
function LegacyReviewRedirect() {
  const { subjectCode = "" } = useParams<{ subjectCode: string }>()
  return <Navigate to={`/student/flashcards/review?subject=${encodeURIComponent(subjectCode)}`} replace />
}
```

Until Tasks 12 and 13 land, `DeckScreen.tsx` and `ReviewScreen.tsx` must exist for the lazy imports to type-check. Task 10 adds them as two-line placeholders exporting a component that renders `null`. Tasks 12 and 13 overwrite them. Do the same for `NewDeckSheet.tsx`, `DeckMenu.tsx` and `DeckBody.tsx` (`DeckPanel`), with the exact prop types above. Task 18's placeholder scan must find none of these left.

The old `FlashcardDecks`/`FlashcardReview` imports go; their files stay until Task 18. Tasks 10–13 do not commit the routes to old screens, so the source-scanning tests (`gestureWiring`, `capabilityWiring`) keep reading the old files until Task 13 repoints them.

- [ ] **Step 4: Breadcrumbs and subject accordion**

In `web/src/portals/student/data.ts`:
- `currentSubjectCode` (around line 93): the flashcards arm becomes `/^\/student\/flashcards\/(?!review$|deck$)([^/]+)$/`.
- The `crumbs` map gains `"/student/flashcards": "Home / Flashcards"` and `"/student/flashcards/review": "Home / Flashcards / Review"`. These are now real mounted paths, which `navigation.test.ts` requires.
- In `resolveCrumb` (around lines 199-203), add `const flashcardDeckMatch = pathname.match(/^\/student\/flashcards\/deck\/([^/]+)$/); if (flashcardDeckMatch) return "Home / Flashcards / Deck"` before the decks arm. Keep the old review arm, which the redirect still passes through.
- Update the doc comments that say `/student/flashcards` is unmounted (data.ts:111-113; navigation.test.ts:174).

Add `"/student/flashcards"`, `"/student/flashcards/deck/abc"` and `"/student/flashcards/review"` to the `paths` list in `navigation.test.ts`'s "links Home and nothing else" test.

- [ ] **Step 5: Verify**

Run: `cd $WT/web && npx tsc -b --noEmit && npx vitest run tests/unit/navigation.test.ts tests/unit/flashcardsView.test.ts && npx oxlint src/portals/student && npm run check:copy && npm run check:native`
Expected: clean.

Manual: run `npm run dev` with the backend up, sign in as a seeded student (`seed.practice.students.active`), and open `/student/flashcards` at 390 and 1280. Check FD/FDD against the mock: hero, grouping, the selected row in the panel slot (empty until Task 12).

- [ ] **Step 6: Commit**

```bash
pre-commit run --files web/src/portals/student/screens/flashcards/FlashcardsScreen.tsx web/src/portals/student/screens/flashcards/DecksStates.tsx web/src/portals/student/screens/flashcards/DeckScreen.tsx web/src/portals/student/screens/flashcards/ReviewScreen.tsx web/src/portals/student/screens/flashcards/NewDeckSheet.tsx web/src/portals/student/screens/flashcards/DeckMenu.tsx web/src/portals/student/screens/flashcards/DeckBody.tsx web/src/portals/student/index.tsx web/src/portals/student/data.ts web/tests/unit/navigation.test.ts
git commit -S -m "feat(web): flashcard decks screen, states and routes (L10)" -- web/src/portals/student/screens/flashcards/FlashcardsScreen.tsx web/src/portals/student/screens/flashcards/DecksStates.tsx web/src/portals/student/screens/flashcards/DeckScreen.tsx web/src/portals/student/screens/flashcards/ReviewScreen.tsx web/src/portals/student/screens/flashcards/NewDeckSheet.tsx web/src/portals/student/screens/flashcards/DeckMenu.tsx web/src/portals/student/screens/flashcards/DeckBody.tsx web/src/portals/student/index.tsx web/src/portals/student/data.ts web/tests/unit/navigation.test.ts
```

---

### Task 11: New-deck sheet (FN, FGX) and writing state (FG)

**Files:**
- Overwrite: `NewDeckSheet.tsx`
- Create: `WritingState.tsx`
- Test: Task 15 Playwright (sheet opens, manual deck is made); Task 16 fidelity

**Interfaces:**
- Consumes:
  - hooks: `useCreateDeck`, `useGenerateDeck`, `useGenerationStatus`, `useRetryGeneration`, `useDeleteDeck`, `useWeakTopics`, `usePracticeTopics(subjectCode)` (topic chips, existing hook), `useOverview`
  - view models: `newDeckView.*`, `writingView`, `writingProgress`, `generationOutcome`
  - kit: `useToast`
- Produces:
  - `NewDeckSeed = { mode: NewDeckMode | null; subjectCode: string; topic: string | null }`
  - `NewDeckSheet({ seed: NewDeckSeed | null, onClose, onStarted(deckId) })`
  - `WritingState({ deck, variant: "page" | "panel" })`

Behaviour:
1. Open with `seed`. Mode defaults to `seed.mode`, else `"weakness"` if enabled, else `"topic"`. Subject chips (`.tmap`, `tm.m`) appear only when the student has two or more subjects (Needs user decision 3).
2. Mode radios (`.ndo` with `role="radiogroup"`, each `role="radio" aria-checked`). Disabled weakness shows its sub "Needs a marked paper first".
3. Below the radios:
   - weakness: `weaknessChips` (`tm w`, selected `shadow-[inset_0_0_0_2px_var(--color-on-error-container)]`, `aria-pressed`)
   - topic: `topicChips(practiceTopics.topics.map(t => t.topic))` (`tm m`)
   - manual: a Title field (`.fld` input) instead of the chips and stepper
4. `CountStepper` (1–50, default 12) for weakness/topic.
5. Submit `submitLabel(...)`, disabled when `buildNewDeckRequest` is `invalid` or pending.
   - Generate: on success, close the sheet and call `onStarted(deck.id)`. The deck screen or panel shows FG and polls.
   - Create: on success, `onStarted(deck.id)`; the deck opens empty with "Add card".
6. Errors: an `.errl` block (`role="alert"`, `rounded-xl bg-error-container px-3 py-2.5 text-[13.5px] font-semibold text-on-error-container`) with `newDeckErrorMessage(err)` for request errors.
7. FGX: when the sheet is reopened for a failed deck (`seed` carries `failedDeckId`, see below), show `GENERATION_FAILED_TEXT` in `.errl`, keep the chips and stepper, and change the button to "Try again" → `useRetryGeneration`. Closing the sheet without retrying deletes the failed deck (`useDeleteDeck`), so "Nothing was saved" stays true.

Extend `NewDeckSeed` with `failedDeckId?: string`. `DeckScreen`/`DeckPanel` open the sheet with it when the deck's state is `failed` (Task 12).

- [ ] **Step 1: Writing state**

```tsx
// WritingState.tsx
import { useEffect, useState } from "react"
import { Binny } from "@/components/redesign"
import type { DeckOrigin } from "@/lib/flashcardTypes"
import { writingProgress, writingView } from "./deckView"

/** FG: Binny thinking 96 (page only), "Writing 12 cards…", the topic line, a 220px bar, the hint. */
export function WritingState({
  deck, variant,
}: { deck: { topic: string | null; origin: DeckOrigin; requestedCount: number | null }; variant: "page" | "panel" }) {
  const view = writingView(deck)
  const [startedAt] = useState(() => Date.now())
  const [elapsed, setElapsed] = useState(0)
  useEffect(() => {
    const id = window.setInterval(() => setElapsed(Date.now() - startedAt), 500)
    return () => window.clearInterval(id)
  }, [startedAt])
  const progress = writingProgress(elapsed, deck.requestedCount ?? 12)
  return (
    <div role="status" className="grid flex-1 content-center justify-items-center gap-3 px-2 pt-7 text-center">
      {variant === "page" ? <Binny mood="thinking" size={96} motion="idle" /> : null}
      <h2 className="mt-1.5 font-display text-[28px] font-extrabold leading-[1.15] tracking-[-0.02em] text-primary">{view.title}</h2>
      <p className="max-w-[30ch] text-[15px] leading-[1.4] text-on-surface-variant">{view.body}</p>
      <div className="h-2 w-[220px] overflow-hidden rounded bg-surface-container-high" aria-hidden>
        <i className="block h-full origin-left rounded bg-primary transition-transform duration-[600ms] ease-out motion-reduce:transition-none"
          style={{ transform: `scaleX(${progress})` }} />
      </div>
      <p className="text-[14px] leading-[1.4] text-on-surface-variant">{view.hint}</p>
    </div>
  )
}
```

- [ ] **Step 2: The sheet**

```tsx
// NewDeckSheet.tsx
import { PencilSimple, Sparkle, Target } from "@phosphor-icons/react"
import { useEffect, useState } from "react"
import { usePracticeTopics } from "@/lib/hooks/usePracticeApi"
import { useOverview } from "@/lib/hooks/useStudentApi"
import {
  useCreateDeck, useDeleteDeck, useGenerateDeck, useRetryGeneration, useWeakTopics,
} from "@/lib/hooks/useFlashcardApi"
import { CountStepper } from "./parts/CountStepper"
import { FcSheet } from "./parts/FcSheet"
import {
  COUNT_DEFAULT, COUNT_MAX, COUNT_MIN, GENERATION_FAILED_TEXT, buildNewDeckRequest, clampCount,
  newDeckErrorMessage, newDeckOptions, submitLabel, topicChips, weaknessChips, type NewDeckMode,
} from "./newDeckView"

export interface NewDeckSeed {
  mode: NewDeckMode | null
  subjectCode: string
  topic: string | null
  failedDeckId?: string
}

const ICONS = { weakness: Target, topic: Sparkle, manual: PencilSimple } as const
const TONES = {
  weakness: "bg-error-container text-on-error-container",
  topic: "bg-secondary-container text-on-secondary-container",
  manual: "bg-primary-container text-primary",
} as const

export function NewDeckSheet({
  seed, onClose, onStarted,
}: { seed: NewDeckSeed | null; onClose: () => void; onStarted: (deckId: string) => void }) {
  const overview = useOverview()
  const subjects = overview.data?.subjects ?? []
  const [subjectCode, setSubjectCode] = useState("")
  const [mode, setMode] = useState<NewDeckMode>("weakness")
  const [topic, setTopic] = useState<string | null>(null)
  const [count, setCount] = useState(COUNT_DEFAULT)
  const [title, setTitle] = useState("")
  const weak = useWeakTopics()
  const topics = usePracticeTopics(subjectCode)
  const create = useCreateDeck()
  const generate = useGenerateDeck()
  const retry = useRetryGeneration()
  const discard = useDeleteDeck()

  const options = newDeckOptions(weak.data ?? [], subjectCode)

  // Reset whenever the sheet opens with a new seed.
  useEffect(() => {
    if (!seed) return
    const code = seed.subjectCode || subjects[0]?.code || ""
    const opts = newDeckOptions(weak.data ?? [], code)
    setSubjectCode(code)
    setMode(seed.mode ?? (opts[0].disabled ? "topic" : "weakness"))
    setTopic(seed.topic)
    setCount(COUNT_DEFAULT)
    setTitle("")
    create.reset(); generate.reset(); retry.reset()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seed])

  const subjectName = subjects.find((s) => s.code === subjectCode)?.name ?? subjectCode
  const chips = mode === "weakness"
    ? weaknessChips(weak.data ?? [], subjectCode)
    : mode === "topic" ? topicChips((topics.data?.topics ?? []).map((t) => t.topic)) : []
  const req = buildNewDeckRequest({ mode, subjectCode, subjectName, topic, count, title })
  const pending = create.isPending || generate.isPending || retry.isPending
  const failedDeckId = seed?.failedDeckId
  const requestError = (create.error ?? generate.error ?? retry.error) as { status?: number; detail?: unknown } | null

  function close() {
    if (failedDeckId && !retry.isSuccess) discard.mutate(failedDeckId) // "Nothing was saved"
    onClose()
  }

  async function submit() {
    if (failedDeckId) {
      await retry.mutateAsync(failedDeckId)
      onStarted(failedDeckId)
      return
    }
    if (req.kind === "generate") onStarted((await generate.mutateAsync(req.body)).deck.id)
    else if (req.kind === "create") onStarted((await create.mutateAsync(req.body)).id)
  }

  return (
    <FcSheet open={seed !== null} onOpenChange={(o) => { if (!o) close() }} title="New deck">
      {failedDeckId ? <div role="alert" className="rounded-xl bg-error-container px-3 py-2.5 text-[13.5px] font-semibold leading-[1.35] text-on-error-container">{GENERATION_FAILED_TEXT}</div> : null}
      {subjects.length > 1 && !failedDeckId ? (
        <div className="flex flex-wrap gap-1.5" role="group" aria-label="Subject">
          {subjects.map((s) => (
            <button key={s.code} type="button" aria-pressed={s.code === subjectCode}
              onClick={() => { setSubjectCode(s.code); setTopic(null) }}
              className={`min-h-11 rounded-xl px-3 text-[13.5px] font-semibold ${s.code === subjectCode ? "bg-primary-container text-primary shadow-[inset_0_0_0_2px_var(--color-primary)]" : "bg-surface-container-low text-on-surface shadow-[inset_0_0_0_1px_var(--color-outline-variant)]"}`}>
              {s.name}
            </button>
          ))}
        </div>
      ) : null}
      {!failedDeckId ? (
        <div className="grid gap-2" role="radiogroup" aria-label="Kind of deck">
          {options.map((o) => {
            const Icon = ICONS[o.mode]
            const on = o.mode === mode
            return (
              <button key={o.mode} type="button" role="radio" aria-checked={on} disabled={o.disabled}
                onClick={() => { setMode(o.mode); setTopic(null) }}
                className={`grid min-h-[60px] grid-cols-[40px_minmax(0,1fr)] items-center gap-3 rounded-2xl px-3 py-2.5 text-start text-on-surface disabled:opacity-60 ${on ? "bg-primary-container shadow-[inset_0_0_0_2px_var(--color-primary)]" : "bg-surface-container-lowest shadow-[inset_0_0_0_1.5px_var(--color-outline-variant)]"}`}>
                <span className={`grid size-10 place-items-center rounded-xl ${TONES[o.mode]}`}><Icon size={14} weight="bold" aria-hidden /></span>
                <span className="grid"><b className="text-[15px] font-bold">{o.title}</b><span className="text-[13px] text-on-surface-variant">{o.sub}</span></span>
              </button>
            )
          })}
        </div>
      ) : null}
      {mode === "manual" ? (
        <label className="grid gap-1.5 text-[13px] font-semibold text-on-surface-variant">
          <span>Title</span>
          <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder={`${subjectName} deck`}
            className="rounded-2xl bg-surface-container-lowest px-3.5 py-3 font-sans text-[16px] text-on-surface shadow-[inset_0_0_0_1.5px_var(--color-outline)] outline-none focus:shadow-[inset_0_0_0_2px_var(--color-primary)]" />
        </label>
      ) : (
        <>
          <div className="flex flex-wrap gap-1.5" role="group" aria-label="Topic">
            {chips.map((c) => {
              const sel = c.topic === topic
              return (
                <button key={c.topic} type="button" aria-pressed={sel} onClick={() => setTopic(c.topic)}
                  className={`relative inline-flex min-h-11 items-center gap-2 rounded-xl px-3 text-[13.5px] font-semibold transition-[translate] duration-200 ease-out hover:-translate-y-0.5 motion-reduce:transition-none motion-reduce:hover:translate-y-0 ${mode === "weakness" ? "bg-error-container text-on-error-container" : "bg-surface-container-low text-on-surface shadow-[inset_0_0_0_1px_var(--color-outline-variant)]"} ${sel ? "shadow-[inset_0_0_0_2px_var(--color-on-error-container)]" : ""}`}>
                  <span>{c.label}</span>
                  {c.badge ? <b className="font-mono text-[12px] font-bold">{c.badge}</b> : null}
                </button>
              )
            })}
          </div>
          <CountStepper label="Cards" value={count} min={COUNT_MIN} max={COUNT_MAX} onChange={(n) => setCount(clampCount(n))} />
        </>
      )}
      {requestError ? <div role="alert" className="rounded-xl bg-error-container px-3 py-2.5 text-[13.5px] font-semibold text-on-error-container">{newDeckErrorMessage(requestError)}</div> : null}
      <button type="button" onClick={() => void submit()} disabled={pending || (!failedDeckId && req.kind === "invalid")}
        className="min-h-[50px] w-full rounded-[18px] bg-primary px-7 text-[15.5px] font-bold text-on-primary disabled:bg-surface-container-high disabled:text-on-surface-variant">
        {failedDeckId ? (pending ? "Starting…" : "Try again") : submitLabel(mode, count, pending)}
      </button>
    </FcSheet>
  )
}
```

For a selected topic chip in topic mode, use the `--color-primary` ring instead of the error ring. The designer adjusts the class so each mode has its own selected ring. That keeps the weakness chips red-on-red and the topic chips navy.

- [ ] **Step 3: Generation finished toast (K11)**

In `DeckBody` (Task 12), when `useGenerationStatus` moves `writing → ready`, show `toast({ title: generationOutcome(status).text, variant: status.shortfall ? "info" : "success" })`. If `shortfall` is true, also keep a quiet line under the origin line: "9 of 12 cards written". Task 12 implements this; it is listed here so the K11 trail is complete.

- [ ] **Step 4: Verify**

Run: `cd $WT/web && npx tsc -b --noEmit && npx oxlint src/portals/student/screens/flashcards && npm run check:copy`
Manual (dev server, seeded `practice.students.active`):
1. `+` opens FN.
2. Write my own → Make deck opens the empty deck.
3. Weakness option disabled for `bare`.
4. Topic → chips → Make 12 cards → deck shows FG.

With no `GEMINI_API_KEY` locally, generation fails into the failed state. That is the FGX path to check. Do not use a real key here (cost rule).

- [ ] **Step 5: Commit**

```bash
pre-commit run --files web/src/portals/student/screens/flashcards/NewDeckSheet.tsx web/src/portals/student/screens/flashcards/WritingState.tsx
git commit -S -m "feat(web): new-deck sheet and writing state (L10)" -- web/src/portals/student/screens/flashcards/NewDeckSheet.tsx web/src/portals/student/screens/flashcards/WritingState.tsx
```

---

### Task 12: Deck detail (FV), desktop panel, card sheet (FC/add/delete), rename, delete deck (FX), deck menu

**Files:**
- Overwrite: `DeckBody.tsx` (exports `DeckBody`, `DeckPanel`), `DeckScreen.tsx`, `DeckMenu.tsx`
- Create: `CardSheet.tsx`, `RenameDeckSheet.tsx`, `DeleteDeckSheet.tsx`
- Test: Task 15 Playwright (add card, edit, delete deck); Task 16 fidelity

**Interfaces:**
- Consumes:
  - hooks: `useFlashcardDeck`, `useGenerationStatus`, `useAddCard`, `useEditCard`, `useDeleteCard`, `useRenameDeck`, `useDeleteDeck`
  - `deckDetailView`, `generationOutcome`, `subjectDot`
  - `NewDeckSheet` (FGX on failed decks), `WritingState`
- Produces:
  - `DeckBody({ deckId, variant: "page" | "panel", onDeleted })`
  - `DeckPanel({ deckId, onDeleted })` = `DeckBody variant="panel"` inside `.sside`
  - `DeckScreen()`
  - `DeckMenu({ deckId: string | null, onClose, onDeleted? })`
  - `CardSheet({ deckId, card: CardRowView | null, mode: "add" | "edit" | null, onClose })`
  - `RenameDeckSheet({ deckId, title, open, onClose })`
  - `DeleteDeckSheet({ deckId, title, cardCount, open, onClose, onDeleted })`

Component tree (DeckBody):

```
DeckBody
├─ header row: page → `.sjhd` (Back icl, h1 title, sub dot+subject·N cards, options icl DOTS)
│              panel → `.h2row` (h2 .sh2 title + `.s2` sub, options icl DOTS)
├─ state "writing" → <WritingState variant={page|panel}/>
├─ state "failed"  → errl GENERATION_FAILED_TEXT + "Try again" (opens NewDeckSheet seed.failedDeckId) + "Delete deck"
└─ state "ready"
   ├─ `.dvt`: OriginTag(originLine) + MasteryBar(detail) + MasteryLegend
   ├─ shortfall line (only when the last generation outcome was short)
   ├─ Review button (`review.label`; disabled → `.go2[disabled]`) → /student/flashcards/review?deck=id
   ├─ `.h2row`: h2 "Cards" + `.addc` "+ Add card"
   └─ cards: emptyCards → "No cards in this deck yet" | rows `.cdr` (front b, back span, AiMark if ai, pen icl → CardSheet edit)
```

- [ ] **Step 1: Write `CardSheet.tsx`**

```tsx
import { useEffect, useState } from "react"
import { useAddCard, useDeleteCard, useEditCard } from "@/lib/hooks/useFlashcardApi"
import type { CardRowView } from "./deckView"
import { FcSheet } from "./parts/FcSheet"

const FIELD = "rounded-2xl bg-surface-container-lowest px-3.5 py-3 font-mono text-[16px] leading-[1.5] text-on-surface shadow-[inset_0_0_0_1.5px_var(--color-outline)] outline-none resize-none focus:shadow-[inset_0_0_0_2px_var(--color-primary)]"

/** FC (edit), add, and the delete-card confirm step (live K21-K23). */
export function CardSheet({
  deckId, card, mode, onClose,
}: { deckId: string; card: CardRowView | null; mode: "add" | "edit" | null; onClose: () => void }) {
  const add = useAddCard(deckId)
  const edit = useEditCard(deckId)
  const remove = useDeleteCard(deckId)
  const [front, setFront] = useState("")
  const [back, setBack] = useState("")
  const [confirming, setConfirming] = useState(false)

  useEffect(() => {
    setFront(card?.front ?? ""); setBack(card?.back ?? ""); setConfirming(false)
    add.reset(); edit.reset(); remove.reset()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, card?.id])

  const valid = front.trim() !== "" && back.trim() !== ""
  const saving = add.isPending || edit.isPending
  function save() {
    if (!valid) return
    const body = { front: front.trim(), back: back.trim() }
    if (mode === "add") add.mutate(body, { onSuccess: onClose })
    else if (card) edit.mutate({ cardId: card.id, body }, { onSuccess: onClose })
  }

  if (confirming && card) {
    return (
      <FcSheet open onOpenChange={(o) => { if (!o) onClose() }} title="Delete this card?" alert>
        <p className="text-[14px] leading-[1.4] text-on-surface-variant">{card.front}</p>
        {remove.isError ? <div role="alert" className="rounded-xl bg-error-container px-3 py-2.5 text-[13.5px] font-semibold text-on-error-container">Couldn’t delete that card. Try again.</div> : null}
        <button type="button" disabled={remove.isPending} onClick={() => remove.mutate(card.id, { onSuccess: onClose })}
          className="min-h-[50px] w-full rounded-[18px] bg-on-error-container px-7 text-[15.5px] font-bold text-on-primary">
          {remove.isPending ? "Deleting…" : "Delete card"}
        </button>
        <button type="button" onClick={() => setConfirming(false)} className="min-h-11 justify-self-center px-3.5 text-[15px] font-bold text-primary">Keep it</button>
      </FcSheet>
    )
  }

  const error = add.isError ? "Couldn’t add that card. Try again." : edit.isError ? "Couldn’t save that change. Try again." : null
  return (
    <FcSheet open={mode !== null} onOpenChange={(o) => { if (!o) onClose() }} title={mode === "add" ? "New card" : "Edit card"}>
      <label className="grid gap-1.5 text-[13px] font-semibold text-on-surface-variant">
        <span>Front</span>
        <textarea rows={2} required value={front} onChange={(e) => setFront(e.target.value)} className={FIELD} />
      </label>
      <label className="grid gap-1.5 text-[13px] font-semibold text-on-surface-variant">
        <span>Back</span>
        <textarea rows={2} required value={back} onChange={(e) => setBack(e.target.value)} className={FIELD} />
      </label>
      {error ? <div role="alert" className="rounded-xl bg-error-container px-3 py-2.5 text-[13.5px] font-semibold text-on-error-container">{error}</div> : null}
      <button type="button" disabled={!valid || saving} onClick={save}
        className="min-h-[50px] w-full rounded-[18px] bg-primary px-7 text-[15.5px] font-bold text-on-primary disabled:bg-surface-container-high disabled:text-on-surface-variant">
        {saving ? (mode === "add" ? "Adding…" : "Saving…") : mode === "add" ? "Add card" : "Save"}
      </button>
      {mode === "edit" ? (
        <button type="button" onClick={() => setConfirming(true)} className="min-h-11 justify-self-center px-3.5 text-[15px] font-bold text-on-error-container">Delete card</button>
      ) : null}
    </FcSheet>
  )
}
```

- [ ] **Step 2: Write `RenameDeckSheet.tsx` and `DeleteDeckSheet.tsx`**

```tsx
// RenameDeckSheet.tsx
import { useEffect, useState } from "react"
import { useRenameDeck } from "@/lib/hooks/useFlashcardApi"
import { FcSheet } from "./parts/FcSheet"

export function RenameDeckSheet({ deckId, title, open, onClose }: { deckId: string; title: string; open: boolean; onClose: () => void }) {
  const rename = useRenameDeck()
  const [value, setValue] = useState(title)
  useEffect(() => { if (open) { setValue(title); rename.reset() } }, [open, title]) // eslint-disable-line react-hooks/exhaustive-deps
  const clean = value.trim()
  const valid = clean.length > 0 && clean.length <= 80 && clean !== title
  return (
    <FcSheet open={open} onOpenChange={(o) => { if (!o) onClose() }} title="Rename deck">
      <label className="grid gap-1.5 text-[13px] font-semibold text-on-surface-variant">
        <span>Name</span>
        <input autoFocus maxLength={80} value={value} onChange={(e) => setValue(e.target.value)}
          className="rounded-2xl bg-surface-container-lowest px-3.5 py-3 text-[16px] text-on-surface shadow-[inset_0_0_0_1.5px_var(--color-outline)] outline-none focus:shadow-[inset_0_0_0_2px_var(--color-primary)]" />
      </label>
      {rename.isError ? <div role="alert" className="rounded-xl bg-error-container px-3 py-2.5 text-[13.5px] font-semibold text-on-error-container">Couldn’t rename the deck. Try again.</div> : null}
      <button type="button" disabled={!valid || rename.isPending} onClick={() => rename.mutate({ deckId, title: clean }, { onSuccess: onClose })}
        className="min-h-[50px] w-full rounded-[18px] bg-primary px-7 text-[15.5px] font-bold text-on-primary disabled:bg-surface-container-high disabled:text-on-surface-variant">
        {rename.isPending ? "Saving…" : "Save"}
      </button>
      <button type="button" onClick={onClose} className="min-h-11 justify-self-center px-3.5 text-[15px] font-bold text-primary">Cancel</button>
    </FcSheet>
  )
}
```

```tsx
// DeleteDeckSheet.tsx  (FX)
import { useDeleteDeck } from "@/lib/hooks/useFlashcardApi"
import { FcSheet } from "./parts/FcSheet"

export function DeleteDeckSheet({
  deckId, title, cardCount, open, onClose, onDeleted,
}: { deckId: string; title: string; cardCount: number; open: boolean; onClose: () => void; onDeleted: () => void }) {
  const del = useDeleteDeck()
  return (
    <FcSheet open={open} onOpenChange={(o) => { if (!o) onClose() }} title={`Delete ${title}?`} alert>
      <p className="text-[14px] leading-[1.4] text-on-surface-variant">
        All {cardCount} card{cardCount === 1 ? "" : "s"} and their progress go. This can’t be undone.
      </p>
      {del.isError ? <div role="alert" className="rounded-xl bg-error-container px-3 py-2.5 text-[13.5px] font-semibold text-on-error-container">Couldn’t delete the deck. It’s still here.</div> : null}
      <button type="button" disabled={del.isPending} onClick={() => del.mutate(deckId, { onSuccess: () => { onClose(); onDeleted() } })}
        className="min-h-[50px] w-full rounded-[18px] bg-on-error-container px-7 text-[15.5px] font-bold text-on-primary">
        {del.isPending ? "Deleting…" : "Delete deck"}
      </button>
      <button type="button" onClick={onClose} className="min-h-11 justify-self-center px-3.5 text-[15px] font-bold text-primary">Keep it</button>
    </FcSheet>
  )
}
```

- [ ] **Step 3: Write `DeckMenu.tsx`**

`DeckMenu` serves two triggers:
- the DOTS button in a deck header, rendered by `DeckBody` with the kit `Popover` (`label="Deck options"`, items Rename and Delete deck)
- long-press from the list, where `deckId` is set and the menu opens as a small sheet listing the same two items

```tsx
import { useState } from "react"
import { DotsThree } from "@phosphor-icons/react"
import { Popover } from "@/components/ui/popover"
import { useFlashcardDeck } from "@/lib/hooks/useFlashcardApi"
import { DeleteDeckSheet } from "./DeleteDeckSheet"
import { RenameDeckSheet } from "./RenameDeckSheet"
import { FcSheet } from "./parts/FcSheet"

const ITEM = "block min-h-11 w-full rounded-md px-3 py-2 text-start text-[15px] font-semibold text-on-surface hover:bg-surface-container-low"

function useDeckActions(deckId: string | null, onDeleted?: () => void) {
  const deck = useFlashcardDeck(deckId ?? "")
  const [which, setWhich] = useState<"rename" | "delete" | null>(null)
  const sheets = deckId && deck.data ? (
    <>
      <RenameDeckSheet deckId={deckId} title={deck.data.title} open={which === "rename"} onClose={() => setWhich(null)} />
      <DeleteDeckSheet deckId={deckId} title={deck.data.title} cardCount={deck.data.cards.length}
        open={which === "delete"} onClose={() => setWhich(null)} onDeleted={() => onDeleted?.()} />
    </>
  ) : null
  return { setWhich, sheets }
}

/** DOTS button + popover, for deck headers. */
export function DeckOptionsButton({ deckId, onDeleted }: { deckId: string; onDeleted?: () => void }) {
  const [open, setOpen] = useState(false)
  const { setWhich, sheets } = useDeckActions(deckId, onDeleted)
  return (
    <>
      <Popover label="Deck options" open={open} onOpenChange={setOpen} align="end"
        renderTrigger={({ triggerProps }) => (
          <button {...triggerProps} type="button" aria-label="Deck options"
            className="grid size-11 flex-none place-items-center rounded-[14px] bg-primary text-on-primary">
            <DotsThree size={20} weight="bold" aria-hidden />
          </button>
        )}>
        <button type="button" className={ITEM} onClick={() => { setOpen(false); setWhich("rename") }}>Rename</button>
        <button type="button" className={`${ITEM} text-on-error-container`} onClick={() => { setOpen(false); setWhich("delete") }}>Delete deck</button>
      </Popover>
      {sheets}
    </>
  )
}

/** Long-press menu from the decks list (live K15). */
export function DeckMenu({ deckId, onClose, onDeleted }: { deckId: string | null; onClose: () => void; onDeleted?: () => void }) {
  const { setWhich, sheets } = useDeckActions(deckId, onDeleted)
  return (
    <>
      <FcSheet open={deckId !== null} onOpenChange={(o) => { if (!o) onClose() }} title="Deck">
        <button type="button" className={ITEM} onClick={() => { setWhich("rename"); onClose() }}>Rename</button>
        <button type="button" className={`${ITEM} text-on-error-container`} onClick={() => { setWhich("delete"); onClose() }}>Delete deck</button>
      </FcSheet>
      {sheets}
    </>
  )
}
```

Problem: `onClose` sets `deckId` to null, which unmounts the rename/delete sheet data. Fix it by keeping the last non-null id in a ref (`const lastId = useRef(deckId); if (deckId) lastId.current = deckId`) and passing `lastId.current` to `useDeckActions`. The designer verifies in the browser that long-press → Delete deck opens FX.

- [ ] **Step 4: Write `DeckBody.tsx`**

```tsx
import { PencilSimple, Plus } from "@phosphor-icons/react"
import { useEffect, useRef, useState } from "react"
import { useNavigate } from "react-router-dom"
import { useToast } from "@/components/ui/toast"
import { SkeletonBlock } from "@/components/ui/skeleton"
import { useFlashcardDeck, useGenerationStatus } from "@/lib/hooks/useFlashcardApi"
import { useOverview } from "@/lib/hooks/useStudentApi"
import { useSubjectName } from "@/lib/hooks/useReferenceApi"
import { CardSheet } from "./CardSheet"
import { DeckOptionsButton } from "./DeckMenu"
import { NewDeckSheet, type NewDeckSeed } from "./NewDeckSheet"
import { WritingState } from "./WritingState"
import { deckDetailView, type CardRowView } from "./deckView"
import { subjectDot } from "./flashcardsView"
import { GENERATION_FAILED_TEXT } from "./newDeckView"
import { generationOutcome } from "./reviewView"
import { AiMark } from "./parts/AiMark"
import { MasteryBar, MasteryLegend } from "./parts/MasteryBar"
import { OriginTag } from "./parts/OriginTag"
import { SubjectDot } from "./parts/SubjectDot"

export function DeckBody({
  deckId, variant, onDeleted, header,
}: { deckId: string; variant: "page" | "panel"; onDeleted: () => void; header?: (opts: { title: string; sub: React.ReactNode; options: React.ReactNode }) => React.ReactNode }) {
  const navigate = useNavigate()
  const { toast } = useToast()
  const deck = useFlashcardDeck(deckId)
  const overview = useOverview()
  const subjectName = useSubjectName(deck.data?.subjectCode ?? "")
  const writing = deck.data?.generationStatus === "writing"
  const gen = useGenerationStatus(deckId, writing || deck.data?.generationStatus === "failed")
  const [cardSheet, setCardSheet] = useState<{ mode: "add" | "edit"; card: CardRowView | null } | null>(null)
  const [retrySeed, setRetrySeed] = useState<NewDeckSeed | null>(null)
  const [shortfall, setShortfall] = useState<string | null>(null)

  const prev = useRef(gen.data?.status)
  useEffect(() => {
    if (prev.current === "writing" && gen.data?.status === "ready") {
      const outcome = generationOutcome(gen.data)
      toast({ title: outcome.text, variant: outcome.shortfall ? "info" : "success" })
      setShortfall(outcome.shortfall ? outcome.text : null)
    }
    prev.current = gen.data?.status
  }, [gen.data, toast])

  if (deck.isPending) {
    return <div className="grid w-full gap-3"><SkeletonBlock className="h-8 w-40 rounded-[10px]" /><SkeletonBlock className="h-14 rounded-2xl" />{[0, 1, 2].map((i) => <SkeletonBlock key={i} className="h-12 rounded-[14px]" />)}</div>
  }
  if (deck.isError || !deck.data) {
    return (
      <div role="alert" className="grid w-full justify-items-center gap-3 py-6 text-center">
        <p className="text-[15px] text-on-surface-variant">Couldn’t load this deck.</p>
        <button type="button" onClick={() => void deck.refetch()} className="min-h-11 px-3.5 text-[15px] font-bold text-primary">Try again</button>
      </div>
    )
  }

  const order = (overview.data?.subjects ?? []).map((s) => s.code)
  const v = deckDetailView(deck.data, subjectName, subjectDot(deck.data.subjectCode, order))
  const options = <DeckOptionsButton deckId={deckId} onDeleted={onDeleted} />
  const sub = <span className="inline-flex items-center gap-1.5"><SubjectDot color={v.dot} />{v.sub}</span>

  return (
    <div className="flex w-full flex-col gap-3.5">
      {header ? header({ title: v.title, sub, options }) : (
        <div className="flex items-center justify-between gap-2.5">
          <div><h2 className="font-sans text-[22px] font-extrabold text-on-surface">{v.title}</h2><span className="text-[13px] font-medium text-on-surface-variant">{sub}</span></div>
          {options}
        </div>
      )}
      {v.state === "writing" ? <WritingState deck={deck.data} variant={variant} /> : null}
      {v.state === "failed" ? (
        <div className="grid gap-3">
          <div role="alert" className="rounded-xl bg-error-container px-3 py-2.5 text-[13.5px] font-semibold text-on-error-container">{GENERATION_FAILED_TEXT}</div>
          <button type="button" onClick={() => setRetrySeed({ mode: deck.data.origin === "manual" ? null : deck.data.origin, subjectCode: deck.data.subjectCode, topic: deck.data.topic, failedDeckId: deckId })}
            className="min-h-[50px] w-full rounded-[18px] bg-primary px-7 text-[15.5px] font-bold text-on-primary">Try again</button>
        </div>
      ) : null}
      {v.state === "ready" ? (
        <>
          <div className="grid gap-2">
            <OriginTag icon={v.originIcon}>{v.originLine}</OriginTag>
            <MasteryBar mastery={v.mastery} size="detail" />
            <MasteryLegend legend={v.legend} />
            {shortfall ? <span className="text-[13px] text-on-surface-variant">{shortfall}</span> : null}
          </div>
          <button type="button" disabled={!v.review.enabled} onClick={() => navigate(`/student/flashcards/review?deck=${deckId}`)}
            className="min-h-[50px] w-full rounded-[18px] bg-primary px-7 text-[15.5px] font-bold text-on-primary disabled:cursor-not-allowed disabled:bg-surface-container-high disabled:text-on-surface-variant disabled:shadow-none">
            {v.review.label}
          </button>
          <div className="flex items-center justify-between gap-2.5">
            <h3 className="font-sans text-[18px] font-extrabold tracking-[-0.01em] text-on-surface">Cards</h3>
            <button type="button" onClick={() => setCardSheet({ mode: "add", card: null })} className="inline-flex min-h-11 items-center gap-1.5 font-bold text-primary">
              <Plus size={18} weight="bold" aria-hidden /> Add card
            </button>
          </div>
          {v.emptyCards ? <p className="text-[14px] text-on-surface-variant">No cards in this deck yet.</p> : (
            <ul className={variant === "panel" ? "min-h-0 overflow-auto [scrollbar-width:none]" : ""}>
              {v.cards.map((c) => (
                <li key={c.id} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 py-2.5 shadow-[0_-1px_0_var(--color-outline-variant)]">
                  <span className="grid">
                    <b className="text-[15px] font-bold text-on-surface">{c.front}</b>
                    <span className="text-[13px] text-on-surface-variant">{c.back}</span>
                    {c.ai ? <AiMark label={c.sourceLabel} /> : null}
                  </span>
                  <button type="button" aria-label={`Edit card: ${c.front}`} onClick={() => setCardSheet({ mode: "edit", card: c })}
                    className="grid size-11 place-items-center rounded-[14px] text-on-surface-variant focus-visible:outline-[2.5px] focus-visible:outline-primary">
                    <PencilSimple size={16} aria-hidden />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </>
      ) : null}
      <CardSheet deckId={deckId} mode={cardSheet?.mode ?? null} card={cardSheet?.card ?? null} onClose={() => setCardSheet(null)} />
      <NewDeckSheet seed={retrySeed} onClose={() => setRetrySeed(null)} onStarted={() => setRetrySeed(null)} />
    </div>
  )
}

/** FDD `.sside`: white r22, 20px padding, gap 14, soft shadow. */
export function DeckPanel({ deckId, onDeleted }: { deckId: string; onDeleted: () => void }) {
  return (
    <div className="flex w-full flex-col gap-3.5 self-start rounded-[22px] bg-surface-container-lowest p-5 shadow-[0_1px_3px_oklch(0.3_0.05_240/0.1)]">
      <DeckBody key={deckId} deckId={deckId} variant="panel" onDeleted={onDeleted} />
    </div>
  )
}
```

The delete-deck error path (K14): the deck stays and `DeleteDeckSheet` shows the error. On success the panel clears `?deck=` and the page navigates back.

- [ ] **Step 5: Write `DeckScreen.tsx`**

```tsx
import { CaretLeft } from "@phosphor-icons/react"
import { useEffect } from "react"
import { useNavigate, useParams } from "react-router-dom"
import { DeckBody } from "./DeckBody"
import { isWide } from "./FlashcardsScreen"

/** FV (phone/tablet). On desktop the deck lives in the list's side panel, so redirect there. */
export function DeckScreen() {
  const { deckId = "" } = useParams<{ deckId: string }>()
  const navigate = useNavigate()
  useEffect(() => {
    if (isWide()) navigate(`/student/flashcards?deck=${deckId}`, { replace: true })
  }, [deckId, navigate])
  return (
    <div className="mx-auto flex w-full max-w-[640px] flex-col gap-6 px-[18px] pb-24 pt-2">
      <DeckBody deckId={deckId} variant="page" onDeleted={() => navigate("/student/flashcards", { replace: true })}
        header={({ title, sub, options }) => (
          <div className="-mx-[2px] flex items-center gap-2.5 pt-3">
            <button type="button" aria-label="Back" onClick={() => navigate(-1)} className="grid size-11 flex-none place-items-center rounded-[14px] bg-primary-container text-primary">
              <CaretLeft size={20} aria-hidden />
            </button>
            <div className="min-w-0 flex-1">
              <h1 className="font-display text-[28px] font-extrabold leading-[1.1] tracking-[-0.03em] text-primary">{title}</h1>
              <span className="text-[13px] font-medium text-on-surface-variant">{sub}</span>
            </div>
            {options}
          </div>
        )} />
    </div>
  )
}
```

If the shell's back control already renders on this route (`components/ui/back-control.tsx`), drop the in-page Back button so it appears once. The shell wins.

- [ ] **Step 6: Verify**

Run: `cd $WT/web && npx tsc -b --noEmit && npx oxlint src/portals/student/screens/flashcards && npm run check:copy && npm run check:native`
Manual at 390 and 1280:
- FV
- add card
- edit card
- delete card confirm
- rename
- FX delete
- long-press menu (DevTools touch emulation)
- writing and failed decks (failed: generate without an API key)

- [ ] **Step 7: Commit**

```bash
pre-commit run --files web/src/portals/student/screens/flashcards/DeckBody.tsx web/src/portals/student/screens/flashcards/DeckScreen.tsx web/src/portals/student/screens/flashcards/DeckMenu.tsx web/src/portals/student/screens/flashcards/CardSheet.tsx web/src/portals/student/screens/flashcards/RenameDeckSheet.tsx web/src/portals/student/screens/flashcards/DeleteDeckSheet.tsx
git commit -S -m "feat(web): flashcard deck detail, panel, card and deck sheets (L10)" -- web/src/portals/student/screens/flashcards/DeckBody.tsx web/src/portals/student/screens/flashcards/DeckScreen.tsx web/src/portals/student/screens/flashcards/DeckMenu.tsx web/src/portals/student/screens/flashcards/CardSheet.tsx web/src/portals/student/screens/flashcards/RenameDeckSheet.tsx web/src/portals/student/screens/flashcards/DeleteDeckSheet.tsx
```

---

### Task 13: Review (RF0/RF1/RF2, FR, FRD) and All caught up (RD)

**Files:**
- Overwrite: `ReviewScreen.tsx`
- Create: `ReviewCard.tsx`, `ReviewDone.tsx`
- Modify: `web/tests/unit/gestureWiring.test.ts`, `web/tests/unit/capabilityWiring.test.ts` (point the `FlashcardReview.tsx` blocks at the new files)
- Test: those two source tests; Task 15 Playwright

**Interfaces:**
- Consumes:
  - hooks: `useDueSession`, `useReviewCard`, `useFlashcardDeck`
  - session: `startSession`, `registerGrade`, `applyGradeOutcome`, `beginRetry`
  - swipe: `flashcardSwipeAction`, `swipeVisual`, `GRADE_SWIPE_THRESHOLD`, `REVEAL_SWIPE_THRESHOLD`
  - `reviewView.*`, plus `useDragGesture`, `haptic`, F1 `ComboChip`, `Binny`, `GoldRing`
- Produces: `ReviewScreen()`, `ReviewCard({ card, revealed, onReveal, onGrade, againDelayMinutes })`, `ReviewDone({ view, onBack })`

Rules carried over (R1–R18):
- The snapshot is taken once from the first successful due response (ref + state, as now).
- Grading is optimistic: `setIndex` comes before `reviewCard.mutate`. The source test pins this.
- Failed grades join `session.failed`; the banner Retry calls `beginRetry` and re-sends all of them.
- `haptic("success")` fires once at the finish.
- Scope comes from search params: `?deck=` → `{ deckId }`, `?subject=` → `{ subjectCode }`, otherwise all.

- [ ] **Step 1: Write `ReviewCard.tsx`**

```tsx
import { useRef, useState } from "react"
import { useDragGesture } from "@/lib/gestures/useDragGesture"
import { GESTURE_INTERACTIVE_SELECTOR } from "@/lib/gestures/interactiveSelector"
import { GRADE_SWIPE_THRESHOLD, REVEAL_SWIPE_THRESHOLD, flashcardSwipeAction, swipeVisual } from "@/lib/flashcardSwipe"
import type { CardDTO, ReviewGrade } from "@/lib/flashcardTypes"
import { cardSourceLabel } from "./deckView"
import { AiMark } from "./parts/AiMark"
import "./flashcards.css"

const reducedMotion = () => typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches

/** The stack: an under-card plus the live card (fc.css `.fstage`, `.fcard`, `.under`, `.stamp`). */
export function ReviewCard({
  card, revealed, onReveal, onGrade,
}: { card: CardDTO; revealed: boolean; onReveal: () => void; onGrade: (g: ReviewGrade) => void }) {
  const surface = useRef<HTMLDivElement>(null)
  const [dx, setDx] = useState(0)
  const [leaving, setLeaving] = useState<"left" | "right" | null>(null)
  const reduced = reducedMotion()
  const visual = swipeVisual(dx, revealed, reduced)

  useDragGesture(surface, {
    axis: "x",
    enabled: !leaving,
    commitThreshold: revealed ? GRADE_SWIPE_THRESHOLD : REVEAL_SWIPE_THRESHOLD,
    touchAction: "pan-y",
    startFilter: (e) => !(e.target instanceof Element && e.target.closest(GESTURE_INTERACTIVE_SELECTOR)),
    onProgress: (x) => setDx(x),
    onCancel: () => setDx(0),
    onCommit: (x) => {
      const action = flashcardSwipeAction({ dx: x, revealed })
      setDx(0)
      if (action === "reveal") onReveal()
      else if (action === "again" || action === "good") {
        if (reduced) { onGrade(action); return }
        setLeaving(action === "good" ? "right" : "left")
        window.setTimeout(() => { setLeaving(null); onGrade(action) }, 240)
      }
    },
  })

  const stampGood = visual.stamp === "good"
  return (
    <div className="relative mx-[22px] mb-2.5 mt-3.5 min-h-[320px] flex-1 [perspective:1200px]">
      <span aria-hidden className="absolute inset-0 translate-y-3 scale-[0.94] rounded-[28px] bg-surface-container-lowest opacity-60 shadow-[inset_0_0_0_1px_var(--color-outline-variant)]" />
      <div
        key={card.id}
        ref={surface}
        role="button"
        tabIndex={0}
        aria-label={revealed ? `${card.front}. Answer: ${card.back}` : `${card.front}. Tap to flip`}
        onClick={() => { if (!revealed) onReveal() }}
        style={{ transform: leaving ? undefined : `translateX(${dx}px) rotate(${visual.rotateDeg}deg)` }}
        className={[
          "absolute inset-0 flex flex-col items-center justify-center gap-[22px] rounded-[28px] bg-surface-container-lowest p-7 text-center",
          "shadow-[0_18px_36px_-18px_oklch(0.3_0.06_242/0.4),inset_0_0_0_1px_var(--color-outline-variant)]",
          visual.armed ? (stampGood ? "!shadow-[0_18px_36px_-18px_oklch(0.3_0.06_242/0.4),inset_0_0_0_3px_var(--color-success-text)]" : "!shadow-[0_18px_36px_-18px_oklch(0.3_0.06_242/0.4),inset_0_0_0_3px_var(--color-on-error-container)]") : "",
          revealed ? "animate-[fc-flip_450ms_var(--ease-out)_both] motion-reduce:animate-none" : "animate-[fc-rise_280ms_var(--ease-out)] motion-reduce:animate-none",
          leaving === "right" ? "animate-[fc-out-right_240ms_var(--ease-in-soft)_forwards]" : "",
          leaving === "left" ? "animate-[fc-out-left_240ms_var(--ease-in-soft)_forwards]" : "",
        ].join(" ")}
      >
        {visual.stamp ? (
          <span aria-hidden style={{ opacity: visual.opacity }}
            className={stampGood
              ? "absolute left-[22px] top-[22px] -rotate-[10deg] rounded-[10px] px-3 py-1 text-[18px] font-extrabold text-success-text shadow-[inset_0_0_0_2.5px_var(--color-success-text)]"
              : "absolute right-[22px] top-[22px] rotate-[10deg] rounded-[10px] px-3 py-1 text-[18px] font-extrabold text-on-error-container shadow-[inset_0_0_0_2.5px_var(--color-on-error-container)]"}>
            {stampGood ? "Good" : "Again"}
          </span>
        ) : null}
        {card.source === "ai" ? <span className="absolute bottom-4 right-5"><AiMark label={cardSourceLabel("ai")} /></span> : null}
        {revealed ? (
          <>
            <span className="text-balance text-[20px] font-bold leading-[1.35] text-on-surface-variant">{card.front}</span>
            <span className="font-mono text-[34px] font-bold leading-[1.2] text-on-surface">{card.back}</span>
          </>
        ) : (
          <>
            <span className="text-balance font-display text-[28px] font-extrabold leading-[1.2] tracking-[-0.02em] text-primary">{card.front}</span>
            <span className="text-[13px] font-semibold text-on-surface-variant">Tap to flip</span>
          </>
        )}
      </div>
    </div>
  )
}
```

Card answers are free text, so `fa` in Mono 34px can overflow on long answers. Clamp with `text-[clamp(18px,6vw,34px)] break-words` when `card.back.length > 24` (an edge case fix; list it in the PR).

- [ ] **Step 2: Write `ReviewDone.tsx`**

```tsx
import { X } from "@phosphor-icons/react"
import { Link } from "react-router-dom"
import { Binny, GoldRing } from "@/components/redesign"
import type { DoneView } from "./reviewView"

/** RD: green-to-surface wash, Binny 110 hop, "All caught up!", gain3, Coming back, Back to decks. */
export function ReviewDone({
  view, onBack, today, banner,
}: { view: DoneView; onBack: () => void; today: [number, number, number] | null; banner: React.ReactNode }) {
  const done = today ? today.filter((p) => p >= 1).length : 0
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-[18px] overflow-auto bg-[linear-gradient(180deg,var(--color-success-container),var(--color-surface)_45%)] px-5 pb-[26px] pt-4 [scrollbar-width:none] lg:mx-auto lg:w-full lg:max-w-[640px] lg:bg-none">
      <button type="button" aria-label="Close" onClick={onBack} className="grid size-11 place-items-center rounded-[14px] bg-surface-container-high text-on-surface"><X size={20} aria-hidden /></button>
      <div className="grid justify-items-center gap-1.5">
        <Binny mood={view.mood} size={110} motion="hop" />
        <h1 className="text-center font-display text-[34px] font-extrabold leading-[1.05] tracking-[-0.03em] text-primary">{view.title}</h1>
        <p className="text-center text-[14px] font-medium text-on-surface-variant">{view.sub}</p>
      </div>
      {banner}
      <div className={`grid text-center ${today ? "grid-cols-3" : "grid-cols-2"}`}>
        <span className="grid justify-items-center gap-0.5"><b className="font-mono text-[24px] font-extrabold text-success-text">{view.knew}</b><small className="text-[12.5px] font-medium text-on-surface-variant">knew it</small></span>
        <span className="grid justify-items-center gap-0.5"><b className="font-mono text-[24px] font-extrabold text-primary">+{view.xp}</b><small className="text-[12.5px] font-medium text-on-surface-variant">XP</small></span>
        {today ? (
          <span className="grid justify-items-center gap-0.5"><GoldRing parts={today} size={32} label={`Today ${done} of 3`} /><small className="text-[12.5px] font-medium text-on-surface-variant">Today {done} of 3</small></span>
        ) : null}
      </div>
      {view.stillDueLine || view.savingLine ? (
        <p className="text-center text-[13px] text-on-surface-variant">{[view.stillDueLine, view.savingLine].filter(Boolean).join(" · ")}</p>
      ) : null}
      <div className="grid">
        <h2 className="font-sans text-[18px] font-extrabold tracking-[-0.01em] text-on-surface">Coming back</h2>
        {view.comingBack.map((r) => (
          <div key={r.title} className="grid py-2.5 shadow-[0_-1px_0_var(--color-outline-variant)]">
            <b className="text-[15px] font-bold text-on-surface">{r.title}</b>
            {r.sub ? <span className="text-[13px] text-on-surface-variant">{r.sub}</span> : null}
          </div>
        ))}
      </div>
      <button type="button" onClick={onBack} className="min-h-[50px] w-full rounded-[18px] bg-primary px-7 text-[15.5px] font-bold text-on-primary">Back to decks</button>
      {view.practiceLink ? <Link to={view.practiceLink.to} className="inline-flex min-h-11 items-center justify-self-center px-3.5 text-[15px] font-bold text-primary">{view.practiceLink.label}</Link> : null}
    </div>
  )
}
```

`today` comes from L1's Home data (Needs user decision 5). `ReviewScreen` passes `null` until that data exists, and the grid then shows two stats.

- [ ] **Step 3: Write `ReviewScreen.tsx`**

```tsx
import { X } from "@phosphor-icons/react"
import { useEffect, useRef, useState } from "react"
import { useNavigate, useSearchParams } from "react-router-dom"
import { ComboChip } from "@/components/redesign"
import { Kbd } from "@/components/ui/kbd"
import { SkeletonBlock } from "@/components/ui/skeleton"
import { applyGradeOutcome, beginRetry, registerGrade, startSession, type FlashcardSessionState } from "@/lib/flashcardSession"
import type { CardDTO, ReviewGrade } from "@/lib/flashcardTypes"
import { haptic } from "@/lib/haptics"
import { useDueSession, useFlashcardDeck, useReviewCard } from "@/lib/hooks/useFlashcardApi"
import { ReviewCard } from "./ReviewCard"
import { ReviewDone } from "./ReviewDone"
import { comingBackLine, topicName } from "./flashcardsView"
import { doneView, gradeButtons, progressView, reviewKeyAction, syncBannerText } from "./reviewView"

const GRADE_TONE: Record<ReviewGrade, string> = {
  again: "bg-error-container text-on-error-container",
  hard: "bg-tertiary-container text-on-tertiary-container",
  good: "bg-success-container text-on-success-container",
  easy: "bg-primary-container text-primary",
}

export function ReviewScreen() {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const deckId = params.get("deck")
  const subjectCode = params.get("subject")
  const due = useDueSession({ deckId, subjectCode })
  const deck = useFlashcardDeck(deckId ?? "")
  const reviewCard = useReviewCard()
  const backTo = deckId ? `/student/flashcards/deck/${deckId}` : "/student/flashcards"

  // R1: snapshot once; a background refetch never reshuffles the session.
  const snapshotTaken = useRef(false)
  const [cards, setCards] = useState<CardDTO[] | null>(null)
  const [meta, setMeta] = useState({ totalDue: 0, nextDueAt: null as string | null, againDelay: 10 })
  if (!snapshotTaken.current && due.data) {
    snapshotTaken.current = true
    setCards(due.data.cards)
    setMeta({ totalDue: due.data.totalDue, nextDueAt: due.data.nextDueAt, againDelay: due.data.againDelayMinutes })
  }

  const [index, setIndex] = useState(0)
  const [revealed, setRevealed] = useState(false)
  const [session, setSession] = useState<FlashcardSessionState>(startSession)
  const current = cards?.[index] ?? null
  const finished = cards !== null && cards.length > 0 && index >= cards.length

  function send(cardId: string, front: string, g: ReviewGrade) {
    reviewCard.mutate(
      { cardId, grade: g },
      {
        onSuccess: (result) => setSession((s) => applyGradeOutcome(s, { kind: "settled", result })),
        onError: () => setSession((s) => applyGradeOutcome(s, { kind: "failed", cardId, front, grade: g })),
      },
    )
  }

  // R3: optimistic. The index moves before the request is sent.
  function grade(g: ReviewGrade) {
    if (!current) return
    const card = current
    setIndex((i) => i + 1)
    setRevealed(false)
    setSession((s) => registerGrade(s, g))
    reviewCard.mutate(
      { cardId: card.id, grade: g },
      {
        onSuccess: (result) => setSession((s) => applyGradeOutcome(s, { kind: "settled", result })),
        onError: () => setSession((s) => applyGradeOutcome(s, { kind: "failed", cardId: card.id, front: card.front, grade: g })),
      },
    )
  }

  function retryAll() {
    const { state, retries } = beginRetry(session)
    setSession(state)
    for (const r of retries) send(r.cardId, r.front, r.grade)
  }

  const celebrated = useRef(false)
  useEffect(() => {
    if (finished && !celebrated.current) { celebrated.current = true; haptic("success") }
  }, [finished])

  // R7: Space/Enter flip; 1-4 rate after the flip.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (!current || finished || e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return
      const action = reviewKeyAction(e.key, revealed)
      if (!action) return
      e.preventDefault()
      if (action.kind === "reveal") setRevealed(true)
      else grade(action.grade)
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [current, revealed, finished])

  const bannerText = syncBannerText(session.failed.length)
  const banner = bannerText ? (
    <div role="status" className="mx-[22px] mt-2 flex items-center justify-between gap-2.5 rounded-xl bg-tertiary-container px-3 text-[13.5px] font-semibold text-on-tertiary-container">
      <span>{bannerText}</span>
      <button type="button" onClick={retryAll} className="min-h-11 font-bold text-primary">Retry</button>
    </div>
  ) : null

  if (!cards) {
    if (due.isError) {
      return (
        <div role="alert" className="grid flex-1 content-center justify-items-center gap-3 px-6 text-center">
          <h1 className="font-display text-[28px] font-extrabold text-primary">Couldn’t load your cards</h1>
          <p className="text-[15px] text-on-surface-variant">Check your connection, then try again.</p>
          <button type="button" onClick={() => void due.refetch()} className="min-h-[50px] w-full max-w-[300px] rounded-[18px] bg-primary px-7 font-bold text-on-primary">Try again</button>
          <button type="button" onClick={() => navigate(backTo)} className="min-h-11 font-bold text-primary">Back to decks</button>
        </div>
      )
    }
    return <div className="grid gap-4 p-5" aria-busy="true" aria-label="Loading your cards"><SkeletonBlock className="h-2 rounded" /><SkeletonBlock className="h-[360px] rounded-[28px]" /></div>
  }

  if (cards.length === 0) {
    return (
      <div className="grid flex-1 content-center justify-items-center gap-3 px-6 text-center">
        <h1 className="font-display text-[28px] font-extrabold text-primary">Nothing due</h1>
        <p className="text-[15px] text-on-surface-variant">{comingBackLine(due.data?.upcoming ?? [], meta.nextDueAt, new Date())}</p>
        <button type="button" onClick={() => navigate(backTo)} className="min-h-[50px] w-full max-w-[300px] rounded-[18px] bg-primary px-7 font-bold text-on-primary">Back to decks</button>
      </div>
    )
  }

  if (finished) {
    const d = deck.data
    const practice = d && d.origin === "weakness" && d.topic && d.marksLost
      ? { subjectCode: d.subjectCode, topicName: topicName(d.topic), marksLost: d.marksLost }
      : null
    const view = doneView({
      session, totalCards: cards.length, stillDue: Math.max(meta.totalDue - cards.length, 0),
      upcoming: due.data?.upcoming ?? [], now: new Date(), practice,
    })
    return <ReviewDone view={view} onBack={() => navigate(backTo)} today={null} banner={banner} />
  }

  const progress = progressView(index, cards.length)
  const buttons = current ? gradeButtons(current, meta.againDelay) : []
  const deckLabel = deck.data?.title ?? null

  return (
    <div className="flex min-h-[100dvh] flex-col lg:mx-auto lg:w-full lg:max-w-[640px] lg:pt-3">
      {/* `.prtop`: end, progress bar, count */}
      <div className="flex items-center gap-3 px-4 pb-1.5 pt-4">
        <button type="button" aria-label="End review" onClick={() => navigate(backTo)} className="grid size-11 place-items-center rounded-[14px] bg-surface-container-high text-on-surface"><X size={20} aria-hidden /></button>
        <div className="h-2 flex-1 overflow-hidden rounded bg-surface-container-high" role="progressbar" aria-valuemin={0} aria-valuemax={cards.length} aria-valuenow={index + 1} aria-label="Cards reviewed">
          <i className="block h-full origin-left rounded bg-primary transition-transform duration-300 ease-out motion-reduce:transition-none" style={{ transform: `scaleX(${progress.fraction})` }} />
        </div>
        <span className="font-mono text-[13px] font-bold text-on-surface-variant">{progress.label}</span>
      </div>
      {/* `.prmeta`: combo + deck */}
      <div className="flex items-center gap-2.5 px-[18px] pb-1 pt-1.5 text-[13px] font-medium text-on-surface-variant">
        <ComboChip count={session.combo} />
        {deckLabel ? <span className="ml-auto text-[13px] font-semibold">{deckLabel}</span> : null}
      </div>
      {banner}
      {current ? <ReviewCard card={current} revealed={revealed} onReveal={() => setRevealed(true)} onGrade={grade} /> : null}
      {revealed ? (
        <div className="grid grid-cols-4 gap-2 px-[18px] pb-[26px] pt-2" role="group" aria-label="How well did you know it?">
          {buttons.map((b) => (
            <button key={b.grade} type="button" onClick={() => grade(b.grade)}
              className={`grid min-h-[62px] content-center justify-items-center gap-0.5 rounded-2xl transition-transform duration-150 ease-out active:scale-[0.96] motion-reduce:transition-none motion-reduce:active:scale-100 focus-visible:outline-[2.5px] focus-visible:outline-offset-2 focus-visible:outline-primary ${GRADE_TONE[b.tone]}`}>
              <b className="text-[15px] font-bold">{b.label} <Kbd className="ml-1 hidden bg-black/10 text-current lg:inline">{b.key}</Kbd></b>
              <span className="text-[12px] font-medium">{b.interval}</span>
            </button>
          ))}
        </div>
      ) : (
        <>
          <div aria-hidden className="flex justify-between px-[30px] text-[13px] font-semibold text-on-surface-variant"><span>← Again</span><span>Good →</span></div>
          <div className="px-[18px] pb-[26px] pt-2.5">
            <button type="button" onClick={() => setRevealed(true)} className="min-h-[50px] w-full rounded-[18px] bg-primary px-7 text-[15.5px] font-bold text-on-primary">Show answer</button>
          </div>
        </>
      )}
      <p className="hidden pb-6 text-center text-[13px] font-medium text-on-surface-variant lg:block">
        Press <Kbd>Space</Kbd> to flip · <Kbd>1</Kbd>–<Kbd>4</Kbd> to rate
      </p>
    </div>
  )
}
```

Clean-up the implementer must do before commit:
- `grade()` and `send()` duplicate the mutate call. Make `grade()` call `send(card.id, card.front, g)` after `setSession(registerGrade…)`. Then update `capabilityWiring.test.ts` to match `/setIndex[\s\S]{0,300}send\(/` instead of `reviewCard\.mutate`; the order is still pinned.
- The mock's front-face hint row is shown on the front only (matches RF0). The "Show answer" label replaces the live "Reveal answer". Update `gestureWiring.test.ts` to expect "Show answer" and `reviewKeyAction` instead of "Reveal answer" and `isRevealKey`, and to scan `ReviewCard.tsx` for `useDragGesture` and `flashcardSwipeAction`.
- The deck label in `.prmeta` shows the deck title for a deck scope, the subject name for a subject scope (`useSubjectName`), and nothing for all decks. The mock shows a subject dot + deck name.

- [ ] **Step 4: Repoint the source tests**

In `web/tests/unit/gestureWiring.test.ts`, change the `FlashcardReview.tsx` describe block to:

```ts
describe("flashcard review — swipe is additive to the buttons and keys", () => {
  const card = sourceOf("src/portals/student/screens/flashcards/ReviewCard.tsx")
  const screen = sourceOf("src/portals/student/screens/flashcards/ReviewScreen.tsx")

  it("the card uses useDragGesture and flashcardSwipeAction", () => {
    expect(card).toContain("useDragGesture")
    expect(card).toContain("flashcardSwipeAction")
  })

  it("still has the Show answer button and the keyboard path", () => {
    expect(screen).toContain("Show answer")
    expect(screen).toContain("reviewKeyAction")
  })

  it("renders the four grades from gradeButtons", () => {
    expect(screen).toContain("gradeButtons")
  })
})
```

In `web/tests/unit/capabilityWiring.test.ts`, change the `FlashcardReview.tsx` block to read `ReviewScreen.tsx` and assert `applyGradeOutcome`, `haptic`, and `toMatch(/setIndex[\s\S]{0,300}send\(/)`.

- [ ] **Step 5: Verify**

Run: `cd $WT/web && npx vitest run tests/unit/gestureWiring.test.ts tests/unit/capabilityWiring.test.ts tests/unit/reviewView.test.ts tests/unit/flashcardSession.test.ts tests/unit/flashcardSwipe.test.ts && npx tsc -b --noEmit && npx oxlint src/portals/student/screens/flashcards && npm run check:copy && npm run check:native`
Expected: PASS and clean.

Manual:
- 390 with touch emulation: flip by tap, swipe right reveals, swipe right/left on a flipped card stamps Good/Again, flies out, and the next card rises.
- Stop the backend mid-session: the FR banner appears; restart it and Retry clears it.
- 1280: Space/1–4 and the keys line.
- `prefers-reduced-motion` (DevTools rendering): no tilt, no flip, no fly.

- [ ] **Step 6: Commit**

```bash
pre-commit run --files web/src/portals/student/screens/flashcards/ReviewScreen.tsx web/src/portals/student/screens/flashcards/ReviewCard.tsx web/src/portals/student/screens/flashcards/ReviewDone.tsx web/tests/unit/gestureWiring.test.ts web/tests/unit/capabilityWiring.test.ts
git commit -S -m "feat(web): flashcard swipe review and all caught up (L10)" -- web/src/portals/student/screens/flashcards/ReviewScreen.tsx web/src/portals/student/screens/flashcards/ReviewCard.tsx web/src/portals/student/screens/flashcards/ReviewDone.tsx web/tests/unit/gestureWiring.test.ts web/tests/unit/capabilityWiring.test.ts
```

---

### Task 14: Copy and accessibility pass

**Files:** any of `web/src/portals/student/screens/flashcards/**` and the view models; tests updated in lockstep.

- [ ] **Step 1: Copy.** Run `/humanizer` over every user-facing string in the four view models and the sheets. Rules: Binny lines 2–4 words, no eyebrow labels, "cost you N marks" phrasing, no "AI-generated" shouting outside `AiMark`'s label. When a view-model string changes, change its Vitest expectation in the same edit. Then run `cd $WT/web && npm run check:copy`.
- [ ] **Step 2: Accessibility.** In the browser with axe (`npx playwright test e2e/flashcards.spec.ts` from Task 15 has an axe step), check that:
  - every interactive element is at least 44×44
  - no text is under 12px
  - each sheet has exactly one title
  - the radio group, `aria-pressed` chips, `role="progressbar"` and `role="status"` (writing and sync banner) are announced
  - the grade buttons' text on their containers passes AA (mock Hard `oklch(.38 .08 70)` on `oklch(.95 .05 80)` maps to `on-tertiary-container` on `tertiary-container`, which `test_design_tokens.py` already pins AA)
- [ ] **Step 3: Commit** with explicit paths, as the earlier tasks do: `git commit -S -m "fix(web): flashcard copy and a11y pass (L10)" -- <paths>`.

---

### Task 15: Playwright happy paths (decks, deck, review)

**Files:**
- Create: `web/e2e/flashcards.spec.ts`

**Interfaces:**
- Consumes: `readSeed`, `injectSession` (`web/e2e/seed.ts`), `watchConsole` (`web/e2e/console-errors.ts`), the seeded `practice.students.active` account.

The spec makes its own deck through the API on every run, so it is safe under retries. Reviews move cards out of "due", and the seed deck alone would not survive a retry.

- [ ] **Step 1: Write the spec**

```ts
// web/e2e/flashcards.spec.ts
import { test, expect, type Page, type APIRequestContext } from "@playwright/test"
import AxeBuilder from "@axe-core/playwright"
import { watchConsole } from "./console-errors"
import { injectSession, readSeed, type SeedAccount } from "./seed"

const BACKEND_URL = "http://127.0.0.1:8000"

/*
 * L10 flashcards: one happy path per screen (decks, deck, review). Each test makes a fresh
 * manual deck through the API, so a retry never meets cards an earlier attempt already reviewed.
 */

async function makeDeck(request: APIRequestContext, account: SeedAccount, cards: number): Promise<{ id: string; title: string }> {
  const headers = { Authorization: `Bearer ${account.accessToken}` }
  const title = `L10 e2e ${Date.now()}`
  const deck = await request.post(`${BACKEND_URL}/api/student/flashcards/decks`, {
    headers, data: { subjectCode: readSeed().practice.subjectCode, title, origin: "manual" },
  })
  expect(deck.status()).toBe(201)
  const { id } = (await deck.json()) as { id: string }
  for (let i = 1; i <= cards; i++) {
    const card = await request.post(`${BACKEND_URL}/api/student/flashcards/decks/${id}/cards`, {
      headers, data: { front: `L10 front ${i}`, back: `L10 back ${i}` },
    })
    expect(card.status()).toBe(201)
  }
  return { id, title }
}

async function asStudent(page: Page, account: SeedAccount) {
  await injectSession(page, { accessToken: account.accessToken, userId: account.userId, role: "student" })
}

test.describe("flashcards on a phone", () => {
  test.use({ viewport: { width: 390, height: 844 } })

  test("decks: the new deck shows under its subject with cards due", async ({ page, request }) => {
    const account = readSeed().practice.students.active
    const errors = watchConsole(page)
    const deck = await makeDeck(request, account, 2)
    await asStudent(page, account)

    await page.goto("/student/flashcards")
    await expect(page.getByRole("heading", { level: 1, name: "Flashcards" })).toBeVisible({ timeout: 15_000 })
    await expect(page.getByText(/cards? due$/).first()).toBeVisible()
    await expect(page.getByRole("button", { name: /^Review \d+ cards?$/ })).toBeVisible()
    await expect(page.getByRole("button", { name: new RegExp(deck.title) })).toBeVisible()

    const axe = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze()
    expect(axe.violations.filter((v) => v.impact === "serious" || v.impact === "critical")).toEqual([])
    expect(errors, JSON.stringify(errors, null, 2)).toEqual([])
  })

  test("deck: add a card, rename the deck, then delete it", async ({ page, request }) => {
    const account = readSeed().practice.students.active
    const errors = watchConsole(page)
    const deck = await makeDeck(request, account, 1)
    await asStudent(page, account)

    await page.goto(`/student/flashcards/deck/${deck.id}`)
    await expect(page.getByRole("heading", { level: 1, name: deck.title })).toBeVisible({ timeout: 15_000 })

    await page.getByRole("button", { name: "Add card" }).click()
    await page.getByLabel("Front").fill("L10 added front")
    await page.getByLabel("Back").fill("L10 added back")
    await page.getByRole("button", { name: "Add card" }).last().click()
    await expect(page.getByText("L10 added front")).toBeVisible()

    await page.getByRole("button", { name: "Deck options" }).click()
    await page.getByRole("button", { name: "Rename" }).click()
    await page.getByLabel("Name").fill(`${deck.title} renamed`)
    await page.getByRole("button", { name: "Save" }).click()
    await expect(page.getByRole("heading", { level: 1, name: `${deck.title} renamed` })).toBeVisible()

    await page.getByRole("button", { name: "Deck options" }).click()
    await page.getByRole("button", { name: "Delete deck" }).click()
    await expect(page.getByRole("alertdialog", { name: new RegExp(`Delete ${deck.title}`) })).toBeVisible()
    await page.getByRole("button", { name: "Delete deck" }).last().click()
    await expect(page).toHaveURL(/\/student\/flashcards$/)
    await expect(page.getByText(deck.title)).toHaveCount(0)
    expect(errors, JSON.stringify(errors, null, 2)).toEqual([])
  })

  test("review: flip, rate both cards, all caught up", async ({ page, request }) => {
    const account = readSeed().practice.students.active
    const errors = watchConsole(page)
    const deck = await makeDeck(request, account, 2)
    await asStudent(page, account)

    await page.goto(`/student/flashcards/deck/${deck.id}`)
    await page.getByRole("button", { name: "Review 2 due" }).click()
    await expect(page).toHaveURL(new RegExp(`/student/flashcards/review\\?deck=${deck.id}`))
    await expect(page.getByText("1/2")).toBeVisible({ timeout: 15_000 })

    await page.getByRole("button", { name: "Show answer" }).click()
    await expect(page.getByText("L10 back 1")).toBeVisible()
    await page.getByRole("group", { name: "How well did you know it?" }).getByRole("button", { name: /Good/ }).click()

    await expect(page.getByText("2/2")).toBeVisible()
    await page.keyboard.press("Space")
    await page.keyboard.press("4")

    await expect(page.getByRole("heading", { name: "All caught up!" })).toBeVisible()
    await expect(page.getByText("knew it")).toBeVisible()
    await page.getByRole("button", { name: "Back to decks" }).click()
    await expect(page).toHaveURL(new RegExp(`/student/flashcards/deck/${deck.id}`))
    expect(errors, JSON.stringify(errors, null, 2)).toEqual([])
  })
})

test("desktop: list with a side panel and review keys", async ({ page, request }) => {
  const account = readSeed().practice.students.active
  const errors = watchConsole(page)
  await page.setViewportSize({ width: 1280, height: 900 })
  const deck = await makeDeck(request, account, 1)
  await asStudent(page, account)

  await page.goto(`/student/flashcards?deck=${deck.id}`)
  const panel = page.getByRole("complementary", { name: "Deck" })
  await expect(panel.getByRole("heading", { name: deck.title })).toBeVisible({ timeout: 15_000 })
  await panel.getByRole("button", { name: "Review 1 due" }).click()
  await expect(page.getByText("Press")).toBeVisible()
  await page.keyboard.press("Space")
  await page.keyboard.press("3")
  await expect(page.getByRole("heading", { name: "All caught up!" })).toBeVisible()
  expect(errors, JSON.stringify(errors, null, 2)).toEqual([])
})
```

- [ ] **Step 2: Run it**

Run: `cd $WT/web && npx playwright test e2e/flashcards.spec.ts`
Expected: 4 passed. Playwright boots the backend and Vite itself (`playwright.config.ts` webServer) and seeds through `global-setup.ts`.

If the "Add card" sheet button name collides with the header link, use `page.getByRole("dialog").getByRole("button", { name: "Add card" })` instead of `.last()`. Do the same for "Delete deck" with `getByRole("alertdialog")`.

- [ ] **Step 3: Commit**

```bash
pre-commit run --files web/e2e/flashcards.spec.ts
git commit -S -m "test(e2e): flashcards decks, deck and review happy paths (L10)" -- web/e2e/flashcards.spec.ts
```

---

### Task 16: Side-by-side fidelity screenshots and drift fixes

**Files:**
- Scratch only, not committed: `reports/.scratch/l10/fidelity.mjs` and the PNGs under `reports/.scratch/l10/` (`reports/` is not exported or committed; see memory "scratch exports exclude reports/").
- Fixes land in the screen files.

- [ ] **Step 1: Serve the mock and start the app**

```bash
cd $WT && python3 -m http.server 8765 --directory .impeccable/mocks &   # mock at http://127.0.0.1:8765/student-r2/cards-final.html
cd $WT/web && npx playwright test e2e/flashcards.spec.ts --list >/dev/null   # sanity: e2e harness works
```

Run the app with the e2e servers (backend on 8000 with the seeded DB, `npm run dev` on 5173). Save the `practice.students.active` token from `reports/.scratch/e2e-seed.json` (path printed by `web/e2e/seed.ts::readSeed`).

- [ ] **Step 2: Capture script**

```js
// reports/.scratch/l10/fidelity.mjs   (run: node reports/.scratch/l10/fidelity.mjs <seed.json>)
import fs from "node:fs"
import { chromium } from "@playwright/test"

const seed = JSON.parse(fs.readFileSync(process.argv[2], "utf8"))
const acct = seed.practice.students.active
const OUT = "reports/.scratch/l10"
const MOCK = "http://127.0.0.1:8765/student-r2/cards-final.html"
const APP = "http://127.0.0.1:5173"
// mock frame id → app path (phone frames at 390, desk frames at 1280)
const PAIRS = [
  ["FD", "/student/flashcards", 390], ["FZ", null, 390], ["FS", null, 390],
  ["FL", null, 390], ["FE", null, 390], ["FN", null, 390], ["FV", "deck", 390],
  ["RF0", "review", 390], ["RD", null, 390], ["FDD", "/student/flashcards", 1280], ["FRD", "review", 1280],
]
const browser = await chromium.launch()
const mock = await browser.newPage({ viewport: { width: 1400, height: 1000 } })
await mock.goto(MOCK)
for (const [id] of PAIRS) await mock.locator(`#${id}`).screenshot({ path: `${OUT}/${id}.mock.png` })
for (const width of [390, 1280]) {
  const ctx = await browser.newContext({ viewport: { width, height: width === 390 ? 844 : 900 } })
  await ctx.addInitScript(([t, u]) => {
    localStorage.setItem("lemely.session", JSON.stringify({ accessToken: t, userId: u, role: "student" }))
  }, [acct.accessToken, acct.userId])
  const app = await ctx.newPage()
  for (const [id, path, w] of PAIRS) {
    if (w !== width || !path) continue
    const url = path === "deck" ? `/student/flashcards/deck/${acct.deckId}` : path === "review" ? `/student/flashcards/review?deck=${acct.deckId}` : path
    await app.goto(APP + url)
    await app.waitForLoadState("networkidle")
    await app.screenshot({ path: `${OUT}/${id}.app.${width}.png`, fullPage: false })
  }
  await ctx.close()
}
await browser.close()
```

Check `web/e2e/seed.ts::injectSession` for the real localStorage key and shape, and mirror it in `addInitScript`. Do not guess the key name.

Frames without a route (FZ, FS, FL, FE, FN, RD) are captured by hand with the Playwright MCP or DevTools:
- FZ: the `bare` account
- FS: a fresh account with one 6-card deck, made via the API
- FL: throttle the network to "Slow 3G"
- FE: block `**/flashcards/decks` with DevTools request blocking
- FN: tap `+`
- RD: finish a 1-card review

- [ ] **Step 3: Compare and fix**

For each pair, put mock and app side by side (`compare` from ImageMagick or a quick HTML page) and list visible drift: spacing, type size and weight, colour, radius, order, missing elements. Fix every drift in the screen files. Mock-vs-app differences that are deliberate go into the PR's "Small changes from the mock" list:
- tide `.lnk` → primary, for contrast
- violet → secondary-container
- subject dot colours
- `AiMark`
- "Show answer" stays the mock's label
- the long-answer clamp
- "<1 min" in the mock → "10 min", the real scheduler step

There is no pixel-diff gate (master plan).

- [ ] **Step 4: Commit the fixes** with explicit paths: `git commit -S -m "fix(web): flashcards fidelity drift (L10)" -- <paths>`.

---

### Task 17: `/impeccable polish`

- [ ] **Step 1:** The designer runs `/impeccable polish` on `web/src/portals/student/screens/flashcards/` with the craft floor loaded. Apply its fixes, then re-take the 390 and 1280 shots for FD, FV, RF1 and RD from Task 16 to confirm nothing regressed.
- [ ] **Step 2:** Re-run `cd $WT/web && npx vitest run tests/unit/flashcard*.test.ts tests/unit/deckView.test.ts tests/unit/newDeckView.test.ts tests/unit/reviewView.test.ts tests/unit/gestureWiring.test.ts tests/unit/capabilityWiring.test.ts tests/unit/navigation.test.ts && npx tsc -b --noEmit && npm run check:copy && npm run check:native`.
- [ ] **Step 3:** Commit with explicit paths: `git commit -S -m "style(web): flashcards polish (L10)" -- <paths>`.

---

### Task 18: Keep-list check and delete the old code

**Files:**
- Delete: `web/src/portals/student/screens/flashcards/FlashcardDecks.tsx`, `FlashcardReview.tsx`, `flashcardData.ts`, `web/tests/unit/flashcards.test.ts`
- Modify: the PR body draft (scratch)

- [ ] **Step 1: Confirm nothing imports the old files**

Use `tokensave_search` with `literal: true` for each of `FlashcardDecks`, `FlashcardReview`, `flashcardData` and `flashcards.test`. Search for `flashcardData`, not `flashcardData.ts`, so imports without extensions are caught. The only hits allowed are the files being deleted. Also check `web/scripts/audit.mjs` and `web/e2e/screenshots.spec.ts` for the old copy ("Flashcards for", "Review due cards", "Session complete") and update their identifying strings to the new ones ("Flashcards", `Review N cards`, "All caught up!").

- [ ] **Step 2: Delete and verify**

```bash
cd $WT && git rm web/src/portals/student/screens/flashcards/FlashcardDecks.tsx web/src/portals/student/screens/flashcards/FlashcardReview.tsx web/src/portals/student/screens/flashcards/flashcardData.ts web/tests/unit/flashcards.test.ts
cd web && npx tsc -b --noEmit && npx vitest run tests/unit/flashcardApi.test.ts tests/unit/flashcardsView.test.ts tests/unit/deckView.test.ts tests/unit/newDeckView.test.ts tests/unit/reviewView.test.ts tests/unit/flashcardSession.test.ts tests/unit/flashcardSwipe.test.ts tests/unit/gestureWiring.test.ts tests/unit/capabilityWiring.test.ts tests/unit/persistAllowlist.test.ts tests/unit/navigation.test.ts && npm run check:copy && npm run check:native && npm run lint
```

Expected: clean. Every function the old unit test covered now lives in a new module with its own tests:
- `manualDeckRequest` in newDeckView
- `cardSourceLabel` in deckView
- `gradeForKey`/`isRevealKey` in `reviewKeyAction`
- `generateDeckSummary` in `generationOutcome`
- `nextDueMessage` in `comingBackLine`
- `dueStateView`/`sessionProgress` in `decksScreenView`/`progressView`

- [ ] **Step 3: Placeholder scan**

Search the changed files for `TODO`, `FIXME`, `test.skip`, `.only`, `return null` placeholders (Task 10 stubs) and `eslint-disable` lines added without a reason (`git diff develop --stat` lists the files). Each one is either fixed or reported as a blocker.

- [ ] **Step 4: Keep-list**

Copy the Keep-list (K1–K27, R1–R18, B1–B13, N1–N5) into the PR body draft at `reports/.scratch/l10/pr-body.md`. Tick each item only after confirming it in the running app or by naming its test. Leave items under a Needs user decision unticked, with the decision noted.

- [ ] **Step 5: Commit**

```bash
git commit -S -m "refactor(web): remove the old flashcard screens (L10)" -- web/src/portals/student/screens/flashcards/FlashcardDecks.tsx web/src/portals/student/screens/flashcards/FlashcardReview.tsx web/src/portals/student/screens/flashcards/flashcardData.ts web/tests/unit/flashcards.test.ts
```

Add `web/scripts/audit.mjs` and `web/e2e/screenshots.spec.ts` to the path list if Step 1 changed them.

---

### Task 19: Final gate sweep, push and PR to `develop`

- [ ] **Step 1: Rebase and fix the migration head**

```bash
cd $WT && git fetch origin && git rebase origin/develop
ls lemely/db/migrations/versions | sort | tail -3
```

If `develop` gained a migration after `0054`, rename the file and the revision to the next free number and set `down_revision` to the new head. Update `REVISION`/`DOWN_REVISION` in `tests/test_migration_flashcard_generation.py`, then commit (`fix(db): rebase flashcard migration onto develop head`).

- [ ] **Step 2: Gate sweep (last, on the final tree)**

Derive the list from `.github/workflows/ci.yml` (memory "derive gate lists from ci.yml"): run every job step that touches the changed areas, but only on the touched files and tests. At minimum:

```bash
cd $WT && PYTHONPATH=$WT /home/sico/Code/Lemely/.venv/bin/python -m pytest tests/test_migration_flashcard_generation.py tests/test_flashcard_repo.py tests/test_web_flashcards.py tests/test_authz_matrix_complete.py tests/test_flashcard_schema.py tests/test_db_schema.py $(ls tests | grep -E '^test_.*lint.*\.py$' | sed 's|^|tests/|') -q
pre-commit run --files $(git diff --name-only origin/develop...HEAD)
cd web && npx tsc -b --noEmit && npm run lint && npm run check:copy && npx vitest run tests/unit/flashcardApi.test.ts tests/unit/flashcardsView.test.ts tests/unit/deckView.test.ts tests/unit/newDeckView.test.ts tests/unit/reviewView.test.ts tests/unit/flashcardSession.test.ts tests/unit/flashcardSwipe.test.ts tests/unit/gestureWiring.test.ts tests/unit/capabilityWiring.test.ts tests/unit/persistAllowlist.test.ts tests/unit/navigation.test.ts && npx playwright test e2e/flashcards.spec.ts
```

Never run the full suite locally. If any later commit lands, re-run the sweep (memory "gate sweep goes last"). `pre-commit` autofixes, so re-check `git status` after it and commit what it changed.

- [ ] **Step 3: Update the graph**

Run `graphify update .` (project CLAUDE.md). Commit `graphify-out/` if it is tracked.

- [ ] **Step 4: Push and open the PR**

```bash
git push -u origin redesign/l10-flashcards
gh pr create --base develop --head redesign/l10-flashcards --title "L10: flashcards redesign" --body-file reports/.scratch/l10/pr-body.md
```

The PR body holds:
- summary
- the migration note (**user approval needed before it runs on any shared DB**)
- the ticked Keep-list
- the frame-to-state table reference
- "Small changes from the mock"
- the open decisions
- the fidelity screenshot pairs, attached or linked

Never target `main`.

- [ ] **Step 5:** Hand off for the Opus review. Fix its findings, wait for green CI, then merge (master plan per-lane workflow).

---

## Needs user decision

1. **The migration and model edit in a lane not allowed to touch models.** "You can leave, the deck shows up" needs a stored status, so `flashcard_decks` gets four columns (`0055_flashcard_generation`). The master plan only lets L1, L6, L9, L11 and L12 edit `lemely/db/models/*`. *Recommendation:* allow it for L10. The change is additive, has a full downgrade, and no other lane touches `flashcards.py`. The fallback without it: generation stays synchronous, FG shows only while the request is pending, and the copy "You can leave" is dropped.
2. **Weakness decks may target a chosen weak topic.** The mock lets the student pick among weak topics (Vectors 41%, Algebra 58%…). The live API refused any caller-supplied topic for `origin=weakness` and always took the top one. *Recommendation:* accept a topic only if it is one of the student's recorded weak topics (Task 2). This keeps the honesty rule's intent.
3. **Picking a subject in the new-deck sheet.** The mock shows no subject control, but decks are now cross-subject. *Recommendation:* add a row of subject chips at the top of the sheet only when the student has two or more subjects, defaulting to the filtered subject or the subject with the top weak topic.
4. **Marking AI cards.** The mock's card rows and review card show no source, but P4.9 rule 1 says every card surface must show whether a card is AI-written. *Recommendation:* a small muted sparkle "AI" mark on AI cards only (row, review card corner), with the full "AI-generated" label for screen readers. The deck's origin tag already says who made the deck.
5. **"Today 2 of 3" ring on All caught up.** The ring needs today's practice, flashcards and paper status, which L1's `GET /student/home` provides. *Recommendation:* show the ring from L1's data once L1 has merged. Read it through L1's `useStudentHome()` (`STUDENT_HOME_KEY = ["student","home"]`, its `today` field; see the L1 plan, Task "home api") and map the three goals to `GoldRing` parts. Until then, show two stats (knew it, XP) with no ring rather than a partly invented ring. This is a dependency on L1 beyond the master plan.
6. **End-of-session summary content.** The live summary listed the grade distribution and every card's interval before and after. The mock replaces these with knew it, XP and "Coming back". *Recommendation:* drop both. The grade buttons now show each interval before rating, which is a stronger form of "show the scheduler's effect", and the knew-it count covers the distribution.
7. **What counts as "known".** The mastery bar needs a threshold. *Recommendation:* an interval of 7 days or more (`KNOWN_INTERVAL_DAYS = 7`), matching the mock's own tip "Easy sends it away for a week". Anki uses 21 days, which would leave most GCSE decks showing almost nothing known.
8. **Failed generation cleanup.** "Couldn't write the cards. Nothing was saved." *Recommendation:* closing the FGX sheet without retrying deletes the failed (empty) deck. A failed deck found later in the list shows "Couldn't write the cards" and opens to Try again or Delete. This deck row state is not in the mock.
9. **Subject dot colours.** The mock uses blue and violet values that are not tokens. *Recommendation:* use existing tokens (grade-a green, tide, grade-d orange, primary, grade-b), with no token changes. If L9 lands a shared subject-dot helper first, both lanes use it.

## Dependencies beyond the master plan

- **F1:**
  - `Binny`, `ComboChip`, `GoldRing`, `HairRows` and `Walkthrough` from `web/src/components/redesign`
  - the restyled kit `Sheet`/`SkeletonBlock`/`Kbd`
  - the shell treating `/student/flashcards*` as the Practice section in the rail and tab bar. The mock's rail shows Practice selected on flashcards. If F1 does not, raise it with F1/L4; L10 does not edit the shell.
- **L1:** the "today" ring data (decision 5).
- **L4:** the Practice tab's Flashcards tile should link to `/student/flashcards` (now a real route) and can read the due count from `useDueSession({})`.
- **L9:** links to `/student/flashcards/:subjectCode` keep working; nothing to change. Agree on one subject-dot helper if both lanes need it (decision 9).

## Self-review

- Spec coverage:
  - decks due first by subject with origin tags and mastery bars: Tasks 2, 6, 10
  - new-deck sheet: Tasks 8, 11
  - deck detail with card edit and delete: Task 12
  - rename and delete deck, each confirmed: Tasks 2, 4, 12
  - swipe review with combo, intervals and stamps: Tasks 2, 7, 13
  - "All caught up": Tasks 7, 13
  - every state, including ratings not saved and writing: Tasks 6, 7, 10–13
  - desktop list and panel, with Space and 1–4: Tasks 10, 12, 13
  - generation status: Tasks 1, 3, 4, 5
- Names used across tasks:
  - from Task 6: `decksScreenView`, `deckRowView`, `masteryView`, `originView`, `subjectDot`, `topicName`, `comingBackLine`
  - from Task 7: `gradeButtons`, `reviewKeyAction`, `progressView`, `syncBannerText`, `doneView`, `generationOutcome`, `startSession`, `registerGrade`, `beginRetry`, `swipeVisual`
  - from Task 8: `deckDetailView`, `writingView`, `writingProgress`, `cardSourceLabel`, `newDeckOptions`, `weaknessChips`, `topicChips`, `submitLabel`, `buildNewDeckRequest`, `newDeckErrorMessage`, `manualDeckRequest`, `GENERATION_FAILED_TEXT`
  - from Task 5: `useGenerationStatus`, `useRetryGeneration`, `useRenameDeck`, `useWeakTopics`, `useDueSession(scope)`
  - service, Tasks 2–4: `start_generation`, `run_generation`, `generation_status`, `retry_generation`, `rename_deck`, `weak_topics`, `due_session(deck_id=)`
- Placeholders: the Task 10 component stubs are deliberate, short-lived, overwritten in Tasks 11–13, and caught by Task 18 Step 3.

