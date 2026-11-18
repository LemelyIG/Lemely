# L7: Student Paper Result S1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `web/src/portals/student/screens/PaperResult.tsx` with the approved S1 result: a full-screen hold-to-reveal, then a celebration where Binny reacts to the grade, the next-step card, the "Marks you can win" rows (crop, scheme wording on low-confidence losses only), and the challenge flow. Add the backend it needs: a per-attempt result read, a crop route scoped by ownership or parent link, and mark challenges (at most 3 per paper). Add a read-only parent view of the same paper.

**Architecture:** A new `PaperResultService` (`lemely/db/paper_result_repo.py`) owns one visibility rule (owner student or linked parent) for the result read, the crop source and the challenge write. A new router `lemely/web/routers/paper_result.py` serves `/api/attempts/{attempt_id}/...` to students and parents. Challenges are a new `mark_challenges` table, and each opens a `review_queue` row with a new reason `student_challenge`, so they land in the teacher queue L5 is rebuilding. On the web side, a typed API module and TanStack hooks feed one pure view model (`resultModel.ts`) and one pure motion module (`revealChoreography.ts`). The screen is split into focused files under `web/src/portals/student/screens/result/`. `PaperResult.tsx` stays the route root, so existing source gates still find it.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, pytest (throwaway Postgres), React 19, react-router 7, TanStack Query 5, Tailwind 4, Vitest (node env, no jsdom), Playwright, phosphor icons, F1 kit (`@/components/redesign`).

**Spec:** `docs/superpowers/specs/2026-11-14-redesign-implementation-design.md` (Wave 2, item 7)
**Master plan:** `docs/superpowers/plans/2026-11-15-redesign-00-master.md`
**Mock:** `.impeccable/mocks/student-r1/s1.html`, `s1.css`, `student.js`, `reveal.js`, `student.css`, `base.css`, plus the states `SR1`/`SR2` in `.impeccable/mocks/states-r1/s.js` and `t.css`.

## Global Constraints

Inherits master plan Global Constraints. In particular: signed commits with explicit paths (`git commit -S -- <paths>`), `pre-commit run --files <touched>` with `PYTHONPATH=<worktree>` before every commit, only touched test files run locally, no token or Abyss changes, PRs to `develop`, and Binny at most once on screen at any moment.

Lane-specific constraints:
- **Branch and worktree:** `redesign/l07-result-s1`, cut from `develop` after F1 merges.
- **Migration:** `0055_mark_challenges` must be approved by the user before it runs on any shared database. Writing it and running it on the throwaway test database (the `migrated_sessionmaker` fixture) is allowed. Before merge, rebase its `down_revision` onto the `develop` head (L1, L6, L9, L11 and L12 also add migrations).
- **Model edits:** the master plan does not list L7 as a lane allowed to touch `lemely/db/models/*`. This plan adds one new file (`models/challenges.py`), one enum member (`ReviewReason.student_challenge`) and one import line. This needs user approval: see "Needs user decision" item 1. Do not start Task 1 until it's approved.
- **No confetti.** Celebration motion only: grade pop, pulses for A*/A, Binny hops.
- **Reveal honesty:** the hold-to-reveal plays only on a path that can show the student hasn't seen this mark yet: the live `location.state` from `CorrectPaper`, or the first open of an attempt on this device. `web/tests/unit/celebration.test.ts`'s `REVEAL_CALL_SITES` must name the new call site and its proof.
- **Thresholds live on the server.** The 0.70 confidence line (scheme wording, the confirm step, and the 20 or 40 character minimum) is decided in `paper_result_repo.py` and sent per question. The client never re-derives it.
- **Copy:** sentence case, no eyebrows, no exclamation marks except the two the mock approved ("An A!"). Numbers in Mono. Gold (`tertiary`) only for an earned thing: the confidence colour of 70% and above, and nothing else.
- **Fonts and sizes the kit lacks** (96px and 88px display numbers, 84px grade box) go in the lane stylesheet `result/result.css` as component CSS using `var(--font-display)`. That file declares no new custom properties on `:root`.
- **Dark overlay colours** come from tokens only: Night is `--md-inverse-surface`, Tide is `--md-inverse-primary`. Under `:root[data-theme="dark"]` the overlay switches to `--md-surface` and `--md-primary`, so it stays dark in both themes.
- **Shell rule:** the `PortalShell` top bar wins. The mock's back button is dropped (the shell has one). The page's first row holds the subject `h1`, the paper meta line and the share icon.

## Search notes for implementers

The tokensave index serves another branch of the main checkout, so it may be stale for this worktree. Run `graphify query "<question>"` from the worktree before your first grep. Read raw files only where a search pointed you.

## File map

Backend (create):
- `lemely/db/models/challenges.py`: `MarkChallenge` ORM model and its bounds
- `lemely/db/migrations/versions/0055_mark_challenges.py`: table and enum value
- `lemely/db/paper_result_repo.py`: `PaperResultService` (read, crop source, challenge)
- `lemely/web/scan_crop.py`: shared PNG crop renderer (lifted from the teacher route)
- `lemely/web/schemas_paper_result.py`: DTOs
- `lemely/web/routers/paper_result.py`: the three routes
- `tests/test_migration_mark_challenges.py`, `tests/test_scan_crop.py`, `tests/test_paper_result_repo.py`, `tests/test_web_paper_result.py`, `tests/test_web_paper_result_challenge.py`

Backend (modify, narrow edits):
- `lemely/db/models/enums.py`: one `ReviewReason` member
- `lemely/db/models/__init__.py`: one import in `import_all_models`
- `lemely/web/deps.py`: `get_paper_result_service` and its `reset_singletons` line
- `lemely/web/app.py`: one `include_router` line and its import
- `lemely/db/review_repo.py`, `lemely/web/routers/review.py`, `lemely/web/schemas_review.py`: `challengeReason` on the teacher item detail
- `lemely/web/schemas_parent.py`, `lemely/web/routers/parent.py`: `attemptId` on `SubjectPaperDTO`
- `tests/test_db_schema.py`, `tests/test_migration_waitlist_email_confirmation.py`, `tests/test_authz_matrix_complete.py`, `tests/test_web_parent.py`
- `scripts/seed_e2e.py`: one appended S1 fixture block. `web/e2e/seed.ts` and `web/e2e/seed-contract.spec.ts`: its keys

Web (create):
- `web/src/lib/paperResultTypes.ts`, `web/src/lib/paperResultApi.ts`, `web/src/lib/hooks/usePaperResultApi.ts`
- `web/src/portals/student/screens/result/resultModel.ts`: pure view model
- `web/src/portals/student/screens/result/revealChoreography.ts`: pure motion values and the "seen" store
- `web/src/portals/student/screens/result/result.css`
- `web/src/portals/student/screens/result/ResultTitleRow.tsx`, `ResultHero.tsx`, `NextStepCard.tsx`, `FirstPaperNote.tsx`, `FullMarksNote.tsx`, `NoDetailNote.tsx`, `ResultStates.tsx`
- `web/src/portals/student/screens/result/WinRows.tsx`, `WinRow.tsx`, `AnswerCrop.tsx`, `ChallengeConfirm.tsx`, `ChallengeSheet.tsx`, `SelfReviewSheet.tsx`, `DeletePaperButton.tsx`
- `web/src/portals/student/screens/result/RevealOverlay.tsx`, `HoldButton.tsx`, `RevealFlight.tsx`
- `web/src/portals/student/screens/result/PaperResultBody.tsx`: the shared body for the student and parent roots
- `web/src/portals/student/screens/result/markerSource.ts`: `markerSourceLabel`, moved out of the old screen
- `web/src/portals/parent/screens/ChildPaperResult.tsx`
- `web/tests/unit/paperResultApi.test.ts`, `resultModel.test.ts`, `revealChoreography.test.ts`, `paperResultWiring.test.ts`
- `web/e2e/paper-result-s1.spec.ts`

Web (modify):
- `web/src/portals/student/screens/PaperResult.tsx`: rewritten as a thin root
- `web/src/portals/parent/index.tsx`: one route entry
- Source gates retargeted (Task 16): `celebration`, `capabilityWiring`, `selfReviewWiring`, `recentlyDeletedWiring`, `printStyles`, `redPen`, `screenEntrance`, `rtlSafety`, `utilityExistence`, `markerSourceLabel`
- `web/e2e/self-review.spec.ts`, `web/e2e/correct-paper.spec.ts`: selectors for the new screen

Not touched (owned elsewhere): `CorrectPaper.tsx` (L6), `parent/screens/SubjectDetail.tsx` (L11, which links rows using the new `attemptId`), `teacher/screens/Review*.tsx` (L5, which renders `challengeReason` and the `student_challenge` label).

## Keep-list: the live screen and its endpoints

The final task (Task 19) ticks every row in the PR body. "Where in S1" names the task that carries it.

| # | Live feature, state or rule | Source | Where in S1 |
|---|---|---|---|
| K1 | Live source: `location.state` from `CorrectPaper` (result plus `questions`) renders with no fetch | `PaperResult.tsx:74-78, 657, 700-723`; `CorrectPaper.tsx:572-594` | Root reads `live.attemptId`, fetches the new result, and plays the reveal (Task 14) |
| K2 | History source: `GET /student/result/{paperId}` by history index | `PaperResult.tsx:659`; `routers/student.py:560-614` | Root keeps `useResult(paperId)` for the attempt id (Task 14) |
| K3 | Per-question rows from `GET /student/attempts/{id}/questions` when the record has an attempt id | `PaperResult.tsx:592-650` | Replaced by `GET /api/attempts/{id}/result`, which carries the same rows plus crop, scheme and challenge fields (Tasks 3, 5) |
| K4 | File-store record (`attemptId` null): honest "No per-question detail for this paper" | `PaperResult.tsx:92-95, 480-489` | `NoDetailNote` state (Tasks 11, 14) |
| K5 | Gated 404 on the questions read reads as no detail, never as an error | `PaperResult.tsx:607-628` | A 404 from the new result read on the history path renders `NoDetailNote` (Task 14) |
| K6 | Non-404 failure of the questions read: `ErrorState` with "Try again" | `PaperResult.tsx:619-628` | `ResultError` with Try again (Task 11) |
| K7 | Paper 404: "No paper recorded at this address" with "Correct a paper" and "Back to overview" | `PaperResult.tsx:735-747` | `ResultNotFound`, same copy and actions (Task 11) |
| K8 | Load failure: "We couldn't load this result", `studentLoadFailureMessage` body, "Back to overview" secondary | `PaperResult.tsx:769-790` | `ResultError`: mock heading "Couldn't load your result.", body from `studentLoadFailureMessage`, Try again, and Back to overview (Task 11) |
| K9 | Loading: skeletons shaped like the page (no layout jump) | `PaperResult.tsx:763-768` | Mock `#skel` blocks (Task 11) |
| K10 | Score as hero number, accessible label "N out of M marks, P percent" (e2e relies on it) | `MarkDisplay` via `PaperResult.tsx:338` | `ResultHero` `aria-label` from `scoreAriaLabel` (Tasks 9, 11) |
| K11 | Grade badge, accessible name "Predicted grade X" (e2e relies on it) | `GradeBadge basis="predicted"`, `PaperResult.tsx:339` | Grade chip `role="img"` with `gradeAriaLabel` (Tasks 9, 11) |
| K12 | Count-up only on the live path | `PaperResult.tsx:338`; `celebration.test.ts:216-227` | The reveal count-up runs only when `shouldReveal` is true (Tasks 10, 13, 16) |
| K13 | Share (Web Share, falling back to a toast) on history results only; the live path has no permalink | `PaperResult.tsx:291-312, 686-698` | Share icon in `ResultTitleRow`, shown only with a history `paperId` (Task 11) |
| K14 | Delete paper with `ConfirmModal`, refusal copy via `deletionRefusal`, 404 copy, navigate to subject after the invalidation settles; only when `attemptId` is set | `PaperResult.tsx:193-263, 316-318` | `DeletePaperButton`, same logic, quiet text button at the foot of the page (Task 14; "Needs user decision" 6) |
| K15 | Interactive controls carry `data-print="hide"` | `PaperResult.tsx:238, 296`; `printStyles.test.ts` | Same attribute on share, delete, challenge, practise and the hold button (Tasks 11-14) |
| K16 | Integrity flags are never shown to a student; `review_reason` is sanitised | `PaperResult.tsx:438-444`; `schemas.py:158-180` | The new DTO carries no integrity field and no `review_reason` (Task 5) |
| K17 | Per-point verdict (`matchedPointIds`) withheld while self-review is pending | `student_self_review.py:189-235` | The new DTO carries scheme wording (point text) only, never `awarded` per point (Tasks 3, 5) |
| K18 | Self-review panel on rows with a `questionResultId` | `PaperResult.tsx:565-567` | "Mark it yourself" in the open row opens `SelfReviewSheet` wrapping `SelfReviewPanel` unchanged (Task 12; "Needs user decision" 4) |
| K19 | "Needs review: reason" when `needsTeacherReview !== false` | `PaperResult.tsx:549-564` | `pendingTeacher` gives the row the "Teacher will check this one" chip and blocks a challenge (Tasks 3, 12) |
| K20 | Marker source label maps `missing`, `dropped` and `blank` to "not marked" | `PaperResult.tsx:124-126`; `markerSourceLabel.test.ts` | The function moves to `result/markerSource.ts`. Rows show "Not marked" as the reason line when unscored. The deterministic/AI chip is dropped, per the taste memory (Tasks 9, 16) |
| K21 | Practice link per topic: `/student/practice/{subject}?topic=` | `PaperResult.tsx:532-536` | Row "Practise {topic}" and the next-step primary (Tasks 9, 12) |
| K22 | All / Lost / Flagged tabs in `?q=`, with empty copy per filter | `PaperResult.tsx:416-430, 500-521, 576-581, 667-679` | Replaced by the mock's lost-first rows with "Show all answers". `?q=all` keeps the expanded list across a round trip ("Needs user decision" 5) |
| K23 | Confidence summary (confident, uncertain, needs review, not marked) | `PaperResult.tsx:630-639, 701-712` | Dropped as a strip. Confidence now drives the confirm step and the scheme wording ("Needs user decision" 5) |
| K24 | Integrity and provenance sidebar (boundary source row, source document) | `PaperResult.tsx:375-403`; `student.py:617-646` | Boundary honesty kept as `boundaryEstimated`, with the line "Grade estimated from past boundaries." under the hero. Provenance text dropped for students ("Needs user decision" 7) |
| K25 | Boundary bar "not available" and `railNote` | `PaperResult.tsx:358-369` | Replaced by the real "N marks to an X" line from the boundary table (Tasks 5, 9) |
| K26 | Long-press "Share" on each row | `PaperResult.tsx:463-469, 537` | Dropped. The title-row share covers it ("Needs user decision" 5) |
| K27 | Screen entrance `lm-screen` only on the live result | `PaperResult.tsx:156-177`; `screenEntrance.test.ts` | The reveal overlay replaces the entrance on the live path. The gate is updated (Tasks 13, 16) |
| K28 | Red-pen register on wrong rows | `PaperResult.tsx:538`; `redPen.test.ts` | Dropped. The mock's rows are neutral and frame a lost mark as "+N to win" (taste memory). The gate is retargeted (Task 16) |
| K29 | Route `student/result/:paperId`, title "Paper result", `page-header` skeleton | `portals/student/index.tsx:249-257` | Unchanged route. Same element name (Task 14) |
| K30 | Parent access to a paper result | none exists today | New read-only parent route (Task 15; "Needs user decision" 2) |

## Frame-to-state table

Breakpoints: phone below 820px (`sidebar`), tablet 820-1247px, desktop 1248px and up (`shell-lg`). The mock is phone-only. Tablet is the phone column centred at `max-w-(--container-read)`. Desktop is two columns (see "Needs user decision" 3).

| Mock frame or class | Component state | Phone | Tablet | Desktop | Trigger |
|---|---|---|---|---|---|
| `.ov.dark` + `.holdui` | `RevealOverlay` phase `hold` | full viewport, portal over the shell | same | same, content centred in a 390px stage | `shouldReveal` true when data arrives |
| `#hold` + `--hp` progress, `#hint` | `HoldButton` progress 0..1 | 112px button | same | same | pointer down (900ms to full); Enter or Space reveals at once |
| `.susp` digits scramble, `.gq` "?" | hold phase, `p > 0.02` | 96px digits | same | same | progress |
| `.ov.shake` | hold phase, `p > 0.6` | stage shakes | same | same | progress, not reduced-motion |
| `.ov.go.tier-*` + `.flash` + `.res` | phase `celebrate` | count-up, grade pop, line rise | same | same | progress reaches 1 |
| `.pz .pulse` x3 | celebrate, tier `a` only | rings behind the score | same | same | grade A* or A |
| `.fly` hops | `RevealFlight` | hops in the free zone below "See my result" | same | same | celebrate plus 900ms |
| `.ov.ready .go2` | phase `ready` | "See my result" fades up | same | same | hops finished |
| `.ov.out` then `.gone` | phase `out`, then unmounted | overlay fades, Binny fades in place | same | same | "See my result" pressed |
| `.slotb.pop` | `NextStepCard` Binny pop-in | 72x79 Binny | same | same | overlay gone (or at once when no reveal) |
| `.hero` (navy) | `ResultHero` variant `dark` | score 88px, grade chip, delta, line | same | left column | layout `full` |
| `.nx` | `NextStepCard` | under the hero | same | left column, under the hero | layout `full` |
| `h2.sec` + `#rows` `.lr` | `WinRows` | below the card | same | right column | layout `full` or `first_paper` |
| `.lr.open` + `.lb` (`.cr`, `.sch`, `.ra`) | `WinRow` open | inline expand | same | same, inline in the right column | row tap |
| `.chip.ok` "Challenge sent" | `WinRow` action `sent` | in `.ra` | same | same | after a successful challenge |
| `.chip` "No challenges left" | `WinRow` action `no_challenges_left` | in `.ra` | same | same | `challengesUsed >= challengeLimit` |
| `[data-more]` "Show all answers" | `WinRows` collapsed with more than 6 rows | under the rows | same | same | more than 6 lost rows |
| `#confirm` | `ChallengeConfirm` alertdialog | bottom sheet | centred dialog | centred dialog | Challenge pressed on a `confirmChallenge` row |
| `#sheet` | `ChallengeSheet` dialog | bottom sheet | adaptive sheet | adaptive sheet | Challenge (low confidence) or "Yes, challenge" |
| `#tickrow` | `ChallengeSheet` with `needsSchemeTick` | shown | same | same | row confidence 70% or more |
| `#cnt` "n/20 min" or "n/40 min" | counter | live region | same | same | typing |
| `#toast` | `useToast` toast | bottom | same | same | send success, a refusal, practise and share fallbacks |
| `#skel` | `ResultSkeleton` | stacked blocks | same | two-column ghost | queries pending |
| `#err` | `ResultError` | card | same | same | non-404 failure |
| states-r1 `SR1` | layout `first_paper`: light hero, "Your first paper" chip, `FirstPaperNote` | stacked | same | left column hero and note, right rows | `isFirstPaper` and lost > 0 |
| states-r1 `SR2` | layout `full_marks`: light hero, "Full marks" chip, `FullMarksNote` with Binny | stacked | same | single centred column | lost marks = 0 |
| none (live keep-list K4, K5) | layout `no_detail`: light hero, `NoDetailNote` | stacked | same | single centred column | no questions, or a gated 404 |
| none (K7) | `ResultNotFound` | `EmptyState` | same | same | history 404 |
| none (Task 15) | parent `ChildPaperResult`: no reveal, no Binny, no challenge, no self-review, no delete | stacked | same | two columns | parent route |

## Interactions and motion

All values are copied from `s1.css`, `reveal.js`, `student.js` and `student.css`. Reduced motion is read through `prefersReducedMotion()` (`lib/celebration.ts`) at call time and through `@media (prefers-reduced-motion: reduce)` in CSS.

| Interaction | Exact values | Reduced motion |
|---|---|---|
| Hold progress | `p = min((now - t0) / 900, 1)` per animation frame. Release before 1 resets `p` to 0. `conic-gradient(Tide calc(p*360deg), track 0)` | Same (the user still holds). No heartbeat |
| Heartbeat `beat` | `--hb = (1.4 - p*0.95)s`, ease-in-out infinite: 0%,100% scale(1); 12% 1.06; 24% 1; 36% 1.04 | none |
| Echo ring `echo` | `--hb`, ease-out infinite: 0% scale(1) opacity .6; 70%,100% scale(1.28) opacity 0 | none |
| Hint copy | `p > .85` "Here it comes"; `> .6` "Almost…"; `> .02` "Keep holding"; else "Hold to reveal" | same copy |
| Digit scramble | random 0-9 in each digit every `150 - p*110` ms while `p > .02`; "?" at rest | digits stay "?" |
| Suspense opacity | digits `.35 + p*.65`; grade box `.5 + p*.5` | same |
| Shake | `p > .6`: `.12s linear infinite`, 25% translate(1px,-1px), 75% translate(-1px,1px) | none |
| Hold UI fade | `.holdui` opacity to 0 over .35s on reveal | instant |
| Background | `.ovbg` background .5s `var(--ease-out)` from Night to `primary-container` (tier d: `surface-container`) | instant |
| Flash | `filter: brightness(2.2)` to none, .6s ease-out | none |
| Result fade | `.res` opacity .4s `var(--ease-out)` | instant |
| Count-up | 0 to score over 1100ms, `1 - (1-t)^3` | jumps to the score |
| Grade pop `gpop` | .7s `cubic-bezier(.16,1,.3,1)`, delay .5s: scale(0) rotate(-8deg), 60% scale(1.25) rotate(2deg), 100% scale(1) | shown at scale(1) |
| Line rise | .5s `var(--ease-out)`, delay 1.1s, translateY(8px) opacity 0 to none | shown |
| Pulses (tier a) | 3 rings, 200px, 3px Tide border, 1.8s `cubic-bezier(.2,.8,.2,1)` infinite, delays 0/.6/1.2s, scale .4 (opacity .9) to 3.2 (0). Clipped to the result stack height with mask `linear-gradient(#000 55%, transparent)` | none |
| Binny entrance | starts at x = centre, y = viewport + 56. First hop after 900ms | placed at the rest point at once |
| Hop keyframes | offsets 0 `scale(1.14,.84)`; .12 `scale(.92,1.12)`; .5 mid point `y = min(from,to) - h`, `scale(.94,1.1) rotate((to.x-from.x)/18 deg)`; .9 at target `scale(1.16,.82)`; 1 `scale(1)`. Easing `cubic-bezier(.3,.6,.3,1)`. `h` clamped so the peak never rises above the free zone top | none |
| Hop plan A*/A | 5 hops of 640ms, h 170, to track fractions .052, .948, .074, .926, .5 (y: rest, rest-30, rest, rest-60, rest) | none |
| Hop plan B | 2 hops of 720ms, h 100, fractions .259 then .741, 120ms pause after each | none |
| Hop plan C-U | 1 hop of 1000ms, h 70, to .5 | none |
| Settle | final hop to the rest point, 600ms, h 90, then the idle bob | none |
| Free zone | top = bottom of "See my result" + 44px; bottom = viewport height - 132 - 8 - safe-area bottom. Binny (120x132) never enters the result stack | n/a |
| "See my result" | rise .5s `var(--ease-out)` once hops finish | shown |
| Dock | Binny fades out in place, opacity 1 to 0 over 320ms ease-out. Overlay `.out` fades over .42s. Then unmount and pop the card Binny | instant |
| Card Binny pop `popin` | .6s `cubic-bezier(.16,1,.3,1)`: translateY(14px) scale(.4) opacity 0; 60% scale(1.12); 100% none | none |
| Idle bob | 2.4s ease-in-out infinite, 50% translateY(-7px) (F1 `motion="idle"`) | `none` (F1 handles it) |
| Content rise | `.rise` opacity and translateY(8px) .4s `var(--ease-out)`, delay .15s, after the overlay leaves | instant |
| Row toggle | one open row at a time. The chevron flips. The open row takes `surface-container-low` and radius 20px | same, no transition |
| Skeleton pulse | 1.6s ease-in-out infinite, 50% opacity .55 | none |
| Toast | existing `useToast`, 3.5s | existing |
| Button press | existing `Button` press scale | existing |
| Focus | 2px `primary` outline, offset 2px. On the dark overlay the outline is Tide | same |
| Escape | closes the confirm and the sheet and returns focus to the Challenge button; after a send, focus goes to the row header | same |

---

## Backend tasks

### Task 1: `mark_challenges` table, the `student_challenge` reason, migration 0055

**Blocked on "Needs user decision" item 1** (L7 touching `lemely/db/models/*`).

**Files:**
- Create: `lemely/db/models/challenges.py`
- Modify: `lemely/db/models/enums.py` (the `ReviewReason` class, after `student_evidence_unjudged = ...`)
- Modify: `lemely/db/models/__init__.py` (`import_all_models`)
- Create: `lemely/db/migrations/versions/0055_mark_challenges.py`
- Create: `tests/test_migration_mark_challenges.py`
- Modify: `tests/test_db_schema.py:40-157` (`EXPECTED_TABLES`) and `:289` (the head)
- Modify: `tests/test_migration_waitlist_email_confirmation.py` (`test_revision_chains_from_0053_and_is_the_head`)

**Interfaces:**
- Produces: `MarkChallenge` with columns `id, attempt_id, question_result_id, student_id, review_queue_id, reason, confidence_at_send, compared_with_scheme, created_at, updated_at`; the constants `CHALLENGES_PER_PAPER = 3`, `REASON_MIN_CHARS = 20`, `REASON_MAX_CHARS = 1000`; and `ReviewReason.student_challenge = "student_challenge"`.

- [ ] **Step 1: Write the failing migration test**

```python
# tests/test_migration_mark_challenges.py
"""Migration 0055_mark_challenges: one table plus one ``reviewreason`` member (lane L7).

A student's challenge to one marked answer. One per question (unique), cascade with
the attempt, the question and the student, and a SET NULL link to the queue row it
opened. The downgrade drops the table and rewrites any ``student_challenge`` queue
rows to ``manual``. Postgres cannot drop an enum value, so the member stays, and
``ADD VALUE IF NOT EXISTS`` makes the re-upgrade idempotent.
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
from lemely.db.models import import_all_models
from tests.test_migration_tutoring_enums import current_revision, upgrade_head

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.orm import Session, sessionmaker

import_all_models()

REVISION = "0055_mark_challenges"
DOWN_REVISION = "0054_waitlist_email_confirmation"
TABLE = "mark_challenges"


def _seed_question(session: Session) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """One student, one attempt, one question. Returns (student, attempt, question)."""
    student, attempt, question = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    session.execute(
        sa.text("INSERT INTO users (id, email, role) VALUES (:id, :e, 'student')"),
        {"id": student, "e": f"{student}@example.com"},
    )
    session.execute(
        sa.text(
            "INSERT INTO attempts (id, user_id, awarded_marks, maximum_marks, percentage, "
            "recorded_at, origin, needs_teacher_review) "
            "VALUES (:id, :u, 1, 4, 25.0, now(), 'past_paper', false)"
        ),
        {"id": attempt, "u": student},
    )
    session.execute(
        sa.text(
            "INSERT INTO question_results (id, attempt_id, question_id, awarded_marks, "
            "maximum_marks, confidence_band, confidence_score, needs_teacher_review, "
            "marker_source, matched_point_ids) "
            "VALUES (:id, :a, '1', 1, 4, 'high', 0.82, false, 'ai', '[]'::jsonb)"
        ),
        {"id": question, "a": attempt},
    )
    return student, attempt, question


def _insert_challenge(
    session: Session, student: uuid.UUID, attempt: uuid.UUID, question: uuid.UUID, reason: str
) -> None:
    session.execute(
        sa.text(
            "INSERT INTO mark_challenges (attempt_id, question_result_id, student_id, reason, "
            "confidence_at_send) VALUES (:a, :q, :s, :r, 0.82)"
        ),
        {"a": attempt, "q": question, "s": student, "r": reason},
    )


def test_revision_chains_from_0054() -> None:
    script_dir = ScriptDirectory.from_config(Config("alembic.ini"))
    revision = script_dir.get_revision(REVISION)
    assert revision is not None
    assert revision.down_revision == DOWN_REVISION
    assert len(REVISION) <= 32


def test_table_matches_the_orm_and_the_enum_has_the_member(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    with migrated_sessionmaker.begin() as session:
        members = set(
            session.execute(
                sa.text("SELECT unnest(enum_range(NULL::reviewreason))::text")
            ).scalars()
        )
        assert "student_challenge" in members
        diff = compare_metadata(
            MigrationContext.configure(session.connection(), opts={"compare_type": True}),
            Base.metadata,
        )
    assert [d for d in diff if TABLE in repr(d)] == []


def test_one_challenge_per_question(migrated_sessionmaker: sessionmaker[Session]) -> None:
    with migrated_sessionmaker.begin() as session:
        student, attempt, question = _seed_question(session)
        _insert_challenge(session, student, attempt, question, "x" * 40)
    with pytest.raises(IntegrityError), migrated_sessionmaker.begin() as session:
        _insert_challenge(session, student, attempt, question, "y" * 40)


@pytest.mark.parametrize("length", [19, 1001])
def test_reason_length_is_bounded(
    migrated_sessionmaker: sessionmaker[Session], length: int
) -> None:
    with migrated_sessionmaker.begin() as session:
        student, attempt, question = _seed_question(session)
    with pytest.raises(IntegrityError), migrated_sessionmaker.begin() as session:
        _insert_challenge(session, student, attempt, question, "z" * length)


def test_deleting_the_attempt_cascades(migrated_sessionmaker: sessionmaker[Session]) -> None:
    with migrated_sessionmaker.begin() as session:
        student, attempt, question = _seed_question(session)
        _insert_challenge(session, student, attempt, question, "x" * 40)
    with migrated_sessionmaker.begin() as session:
        session.execute(sa.text("DELETE FROM attempts WHERE id = :a"), {"a": attempt})
    with migrated_sessionmaker() as session:
        assert session.execute(sa.text("SELECT count(*) FROM mark_challenges")).scalar_one() == 0


def test_upgrade_downgrade_upgrade_round_trip(
    migrated_sessionmaker_with_downgrade: tuple[sessionmaker[Session], Callable[[str], None]],
) -> None:
    sm, downgrade_to = migrated_sessionmaker_with_downgrade
    with sm.begin() as session:
        student, attempt, question = _seed_question(session)
        session.execute(
            sa.text(
                "INSERT INTO review_queue (attempt_id, question_result_id, reason) "
                "VALUES (:a, :q, 'student_challenge')"
            ),
            {"a": attempt, "q": question},
        )

    downgrade_to(DOWN_REVISION)

    with sm() as session:
        assert current_revision(session) == DOWN_REVISION
        tables = set(
            session.execute(
                sa.text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            ).scalars()
        )
        assert TABLE not in tables
        assert session.execute(
            sa.text("SELECT reason::text FROM review_queue WHERE attempt_id = :a"), {"a": attempt}
        ).scalar_one() == "manual"

    upgrade_head()

    with sm() as session:
        assert current_revision(session) == REVISION
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONPATH=$PWD pytest tests/test_migration_mark_challenges.py -v`
Expected: FAIL. `get_revision("0055_mark_challenges")` raises or returns None, and the other tests fail on the missing table.

- [ ] **Step 3: Add the enum member**

In `lemely/db/models/enums.py`, inside `class ReviewReason`, after the line `student_evidence_unjudged = "student_evidence_unjudged"`, add:

```python
    student_challenge = "student_challenge"
    """A student challenged this mark from the result screen (lane L7, migration ``0055``).

    The student's reason lives on :class:`lemely.db.models.challenges.MarkChallenge`,
    whose ``review_queue_id`` points at this row.
    """
```

- [ ] **Step 4: Write the model**

```python
# lemely/db/models/challenges.py
"""ORM model for a student's challenge to one marked answer (lane L7, S1 result).

A challenge is friction on purpose: a written reason (longer when the marker was
confident), at most :data:`CHALLENGES_PER_PAPER` per paper, and one per question.
Each opens a ``review_queue`` row with ``ReviewReason.student_challenge`` so it
reaches the student's teacher in the existing queue; ``review_queue_id`` links the
two, and its status is the challenge's status.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from lemely.db.base import Base
from lemely.db.models.enums import TimestampMixin

#: The most challenges a student may send on one paper.
CHALLENGES_PER_PAPER = 3
#: The shortest reason the table accepts. The service asks for 40 characters on a
#: mark the marker was at least 70% sure of; 20 is the floor for any mark.
REASON_MIN_CHARS = 20
#: The longest reason the table accepts.
REASON_MAX_CHARS = 1000


class MarkChallenge(TimestampMixin, Base):
    """One student's challenge to one ``question_results`` row."""

    __tablename__ = "mark_challenges"
    __table_args__ = (
        sa.UniqueConstraint("question_result_id"),
        sa.Index("ix_mark_challenges_attempt_id", "attempt_id"),
        sa.Index("ix_mark_challenges_student_id", "student_id"),
        sa.CheckConstraint(
            f"char_length(reason) BETWEEN {REASON_MIN_CHARS} AND {REASON_MAX_CHARS}",
            name="reason_length",
        ),
        sa.CheckConstraint("confidence_at_send BETWEEN 0 AND 1", name="confidence_range"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
    )
    attempt_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("attempts.id", ondelete="CASCADE"), nullable=False
    )
    question_result_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("question_results.id", ondelete="CASCADE"),
        nullable=False,
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    review_queue_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("review_queue.id", ondelete="SET NULL"), nullable=True
    )
    reason: Mapped[str] = mapped_column(sa.Text, nullable=False)
    confidence_at_send: Mapped[float] = mapped_column(sa.Float, nullable=False)
    compared_with_scheme: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=False, server_default=sa.false()
    )
```

In `lemely/db/models/__init__.py`, inside `import_all_models`, add `challenges,` to the alphabetical import list (between `catalogue,` and `deletion,`).

- [ ] **Step 5: Write the migration**

```python
# lemely/db/migrations/versions/0055_mark_challenges.py
"""mark challenges: a student's challenge to one marked answer (lane L7).

Revision ID: 0055_mark_challenges
Revises: 0054_waitlist_email_confirmation
Create Date: 2026-11-15 00:00:00.000000

Adds ``reviewreason`` member ``student_challenge`` and the ``mark_challenges`` table.

``downgrade`` drops the table and rewrites ``review_queue`` rows that carry
``student_challenge`` to ``manual``, so the downgraded code never reads a member it
does not know. Postgres cannot drop an enum value, so the member stays in the type;
the upgrade uses ``ADD VALUE IF NOT EXISTS`` and is idempotent on a re-run.

NEEDS USER APPROVAL before it runs against any shared database.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0055_mark_challenges"
down_revision: str | Sequence[str] | None = "0054_waitlist_email_confirmation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "mark_challenges"


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("ALTER TYPE reviewreason ADD VALUE IF NOT EXISTS 'student_challenge'")
    op.create_table(
        TABLE,
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("attempt_id", sa.UUID(), nullable=False),
        sa.Column("question_result_id", sa.UUID(), nullable=False),
        sa.Column("student_id", sa.UUID(), nullable=False),
        sa.Column("review_queue_id", sa.UUID(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("confidence_at_send", sa.Float(), nullable=False),
        sa.Column(
            "compared_with_scheme", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "char_length(reason) BETWEEN 20 AND 1000",
            name=op.f("ck_mark_challenges_reason_length"),
        ),
        sa.CheckConstraint(
            "confidence_at_send BETWEEN 0 AND 1",
            name=op.f("ck_mark_challenges_confidence_range"),
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id"],
            ["attempts.id"],
            name=op.f("fk_mark_challenges_attempt_id_attempts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["question_result_id"],
            ["question_results.id"],
            name=op.f("fk_mark_challenges_question_result_id_question_results"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["student_id"],
            ["users.id"],
            name=op.f("fk_mark_challenges_student_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["review_queue_id"],
            ["review_queue.id"],
            name=op.f("fk_mark_challenges_review_queue_id_review_queue"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mark_challenges")),
        sa.UniqueConstraint(
            "question_result_id", name=op.f("uq_mark_challenges_question_result_id")
        ),
    )
    op.create_index("ix_mark_challenges_attempt_id", TABLE, ["attempt_id"])
    op.create_index("ix_mark_challenges_student_id", TABLE, ["student_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_mark_challenges_student_id", table_name=TABLE)
    op.drop_index("ix_mark_challenges_attempt_id", table_name=TABLE)
    op.drop_table(TABLE)
    op.execute(
        "UPDATE review_queue SET reason = 'manual' WHERE reason = 'student_challenge'"
    )
```

- [ ] **Step 6: Update the schema pins**

In `tests/test_db_schema.py`, add `"mark_challenges",` to `EXPECTED_TABLES` (alphabetical position), and change line 289 to:

```python
    assert script_dir.get_heads() == ["0055_mark_challenges"]
```

In `tests/test_migration_waitlist_email_confirmation.py`, rename `test_revision_chains_from_0053_and_is_the_head` to `test_revision_chains_from_0053` and replace its last line `assert head_revision() == REVISION` with:

```python
    # No longer the head: 0055_mark_challenges (lane L7) chains from it.
    assert script_dir.get_revision("0055_mark_challenges").down_revision == REVISION
```

Remove `head_revision` from that file's import if it is now unused.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD pytest tests/test_migration_mark_challenges.py tests/test_db_schema.py tests/test_migration_waitlist_email_confirmation.py -v`
Expected: PASS. A local Postgres is needed, otherwise the DB tests skip.

- [ ] **Step 8: Commit**

```bash
pre-commit run --files lemely/db/models/challenges.py lemely/db/models/enums.py lemely/db/models/__init__.py lemely/db/migrations/versions/0055_mark_challenges.py tests/test_migration_mark_challenges.py tests/test_db_schema.py tests/test_migration_waitlist_email_confirmation.py
git commit -S -m "feat(db): mark_challenges table and student_challenge review reason" -- lemely/db/models/challenges.py lemely/db/models/enums.py lemely/db/models/__init__.py lemely/db/migrations/versions/0055_mark_challenges.py tests/test_migration_mark_challenges.py tests/test_db_schema.py tests/test_migration_waitlist_email_confirmation.py
```

### Task 2: Shared scan-crop renderer

**Files:**
- Create: `lemely/web/scan_crop.py`
- Test: `tests/test_scan_crop.py`

**Interfaces:**
- Consumes: `SourceBox` (`lemely/core/schemas.py:555`), `StorageBackend`, `sandbox.INTERACTIVE_WORKER`.
- Produces: `render_scan_crop(storage, bucket, object_path, box, *, event_prefix: str, absent_detail: str, **fields: object) -> bytes` (raises `HTTPException` 404, 422 or 503), `require_renderable_box(box, *, event: str, **fields) -> None`, and `NO_STORE_HEADERS: dict[str, str]`.

The teacher route (`lemely/web/routers/review.py:307-470`) keeps its own copy. Lane L5 owns that router and may move onto this helper ("Dependencies" below). The behaviour must match it line for line: same refusal statuses, same `Cache-Control`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_scan_crop.py
"""The shared crop renderer (``lemely.web.scan_crop``), on synthetic scans only."""

from __future__ import annotations

import io

import pytest
from fastapi import HTTPException
from PIL import Image

from lemely.core.schemas import SourceBox
from lemely.web.scan_crop import NO_STORE_HEADERS, render_scan_crop
from tests.sandbox_fixtures import in_process_sandbox  # noqa: F401
from tests.storage_fakes import FakeStorageBackend
from tests.test_web_review import _MARK_BOX, _MARKED_PAGE, _synthetic_scan

BUCKET = "test-bucket"
PATH = "students/x/scan.pdf"


def _colour_counts(png: bytes) -> tuple[int, int, int]:
    image = Image.open(io.BytesIO(png)).convert("RGB")
    pixels = list(image.getdata())
    red = sum(1 for r, g, b in pixels if r > 200 and g < 80 and b < 80)
    blue = sum(1 for r, g, b in pixels if b > 200 and r < 80 and g < 80)
    return red, blue, len(pixels)


@pytest.mark.usefixtures("in_process_sandbox")
def test_renders_only_the_boxed_region() -> None:
    storage = FakeStorageBackend()
    storage.upload(BUCKET, PATH, _synthetic_scan(), "application/pdf")
    png = render_scan_crop(
        storage, BUCKET, PATH, SourceBox(page=_MARKED_PAGE, box=list(_MARK_BOX)),
        event_prefix="test_crop", absent_detail="absent",
    )
    red, blue, total = _colour_counts(png)
    assert blue == 0
    assert red / total > 0.6


@pytest.mark.usefixtures("in_process_sandbox")
def test_a_missing_object_is_the_absent_404() -> None:
    with pytest.raises(HTTPException) as exc:
        render_scan_crop(
            FakeStorageBackend(), BUCKET, PATH, SourceBox(page=0, box=list(_MARK_BOX)),
            event_prefix="test_crop", absent_detail="No scan crop for this answer",
        )
    assert exc.value.status_code == 404
    assert exc.value.detail == "No scan crop for this answer"


@pytest.mark.usefixtures("in_process_sandbox")
def test_an_unrenderable_box_is_422_before_any_download() -> None:
    box = SourceBox.model_construct(page=0, box=[300, 100, 100, 400])  # inverted, unvalidated
    with pytest.raises(HTTPException) as exc:
        render_scan_crop(
            FakeStorageBackend(), BUCKET, PATH, box, event_prefix="test_crop", absent_detail="a"
        )
    assert exc.value.status_code == 422


@pytest.mark.usefixtures("in_process_sandbox")
def test_a_page_past_the_end_is_422() -> None:
    storage = FakeStorageBackend()
    storage.upload(BUCKET, PATH, _synthetic_scan(), "application/pdf")
    with pytest.raises(HTTPException) as exc:
        render_scan_crop(
            storage, BUCKET, PATH, SourceBox(page=40, box=list(_MARK_BOX)),
            event_prefix="test_crop", absent_detail="a",
        )
    assert exc.value.status_code == 422


def test_crops_are_never_cached() -> None:
    assert NO_STORE_HEADERS == {"Cache-Control": "private, no-store"}
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONPATH=$PWD pytest tests/test_scan_crop.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'lemely.web.scan_crop'`.

- [ ] **Step 3: Write the implementation**

```python
# lemely/web/scan_crop.py
"""Render the boxed region of a stored scan as PNG bytes.

Lifted from ``lemely.web.routers.review.get_review_item_crop`` for lane L7's
student and parent crop route. The two must refuse the same way: 422 for a box
or page no renderer will accept, 404 (with the caller's own fixed body) for a
stored object that has gone, 503 when no worker could take the render.
Authorization is never decided here; the caller resolves the object path and
box through its own service first.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog
from fastapi import HTTPException

from lemely.io.rasterise import looks_like_pdf
from lemely.io.scan_limits import ScanRejectedError
from lemely.io.scan_render import RenderRefused, require_page_in_range
from lemely.io.storage import StorageObjectNotFoundError
from lemely.runtime import sandbox
from lemely.web.upload_utils import SANDBOX_FAILED_DETAIL, sandbox_failure_to_http

if TYPE_CHECKING:
    from lemely.core.schemas import SourceBox
    from lemely.io.storage import StorageBackend

log = structlog.get_logger(__name__)

#: The renders, run in the interactive worker and named by dotted path (#260).
CROP_PDF_TARGET = "lemely.io.scan_render.crop_pdf_scan"
CROP_IMAGE_TARGET = "lemely.io.scan_render.crop_image_scan"

#: Who may see a crop changes (a link removed, a sign-out on a shared device);
#: its URL does not. The browser cache is keyed by URL, so a crop is never stored.
NO_STORE_HEADERS: dict[str, str] = {"Cache-Control": "private, no-store"}


def require_renderable_box(box: SourceBox, *, event: str, **fields: object) -> None:
    """Fail closed on a box that would crop to an empty or wrong image.

    ``SourceBox``'s validator runs at construction only, and ``PIL.Image.crop``
    does not raise on an inverted rectangle; ``page=-1`` would load the last page.
    """
    ymin, xmin, ymax, xmax = box.box
    if box.page < 0 or not (0 <= ymin < ymax <= 1000 and 0 <= xmin < xmax <= 1000):
        log.warning(event, page=box.page, box=box.box, **fields)
        raise HTTPException(status_code=422, detail="Stored crop region is not renderable")


def render_scan_crop(
    storage: StorageBackend,
    bucket: str,
    object_path: str,
    box: SourceBox,
    *,
    event_prefix: str,
    absent_detail: str,
    **fields: object,
) -> bytes:
    """The PNG bytes of ``box`` on the scan at ``object_path``."""
    require_renderable_box(box, event=f"{event_prefix}_box_unusable", **fields)
    try:
        data = storage.download(bucket, object_path)
    except StorageObjectNotFoundError:
        log.warning(f"{event_prefix}_object_missing", object_path=object_path, **fields)
        raise HTTPException(status_code=404, detail=absent_detail) from None

    target: str
    args: tuple[object, ...]
    try:
        timeout = sandbox.sandbox_settings().crop_timeout_seconds
        if looks_like_pdf(data):
            target, args = CROP_PDF_TARGET, (data, box.page, list(box.box))
        else:
            require_page_in_range(box.page, 1)
            target, args = CROP_IMAGE_TARGET, (data, list(box.box))
        crop: bytes = sandbox.INTERACTIVE_WORKER.call(
            target, *args, timeout=timeout, result_type=bytes
        )
    except RenderRefused as exc:
        log.warning(f"{event_prefix}_{exc.reason}", page=box.page, **exc.fields, **fields)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ScanRejectedError as exc:
        log.warning(f"{event_prefix}_scan_rejected", page=box.page, reason=exc.reason, **fields)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except sandbox.SandboxFailure as exc:
        raise sandbox_failure_to_http(exc, event=f"{event_prefix}_render_failed", **fields) from exc
    except Exception as exc:
        # The in-process path (sandbox disabled): the renderer's own exceptions.
        # A scan that cannot be rendered is a stored-file problem, not a server fault.
        log.warning(f"{event_prefix}_render_failed", error=str(exc), **fields)
        raise HTTPException(status_code=422, detail=SANDBOX_FAILED_DETAIL) from exc
    return crop
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD pytest tests/test_scan_crop.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
pre-commit run --files lemely/web/scan_crop.py tests/test_scan_crop.py
git commit -S -m "feat(web): shared scan crop renderer" -- lemely/web/scan_crop.py tests/test_scan_crop.py
```

### Task 3: `PaperResultService`, the read side (result view and crop source)

**Files:**
- Create: `lemely/db/paper_result_repo.py`
- Test: `tests/test_paper_result_repo.py`

**Interfaces:**
- Consumes: `MarkChallenge`, `CHALLENGES_PER_PAPER` (Task 1); `question_sort_key` (`lemely/db/self_review_repo.py:297`); `points_are_settleable` (`self_review_repo.py:967`); `self_review_withheld_ids` (`lemely/db/attempt_repo.py:691`).
- Produces (later tasks use these exact names):
  - `class PaperResultService(sessionmaker)`
  - `get_result(caller_id, caller_role, attempt_id) -> PaperResultView`
  - `get_crop_source(caller_id, caller_role, attempt_id, question_result_id) -> tuple[str, SourceBox]`
  - dataclasses `PaperResultView`, `ResultQuestion` (property `lost`), `ChallengeView`, `Reviewer`
  - `challenge_rule(confidence: float) -> ChallengeRule` (fields `confirm`, `min_chars`, `needs_tick`)
  - `challenge_block(question: ResultQuestion, view: PaperResultView) -> RefusalCode | None`
  - errors `PaperResultError`, `PaperResultNotFoundError`, `PaperResultValidationError`
  - constants `LOW_CONFIDENCE = 0.70`, `CONFIDENT_REASON_CHARS = 40`
  - types `Viewer = Literal["student", "parent"]`, `ChallengeState = Literal["open", "kept", "changed"]`, `RefusalCode = Literal["already_sent", "no_loss", "pending_teacher", "limit", "no_reviewer"]`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_paper_result_repo.py
"""``PaperResultService`` read side (lane L7): visibility, rows, scheme wording, history."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa

from lemely.core.schemas import (
    AccuracyReport,
    ConfidenceBand,
    CorrectedQuestion,
    CorrectionResult,
    ExamMetadata,
    GradePrediction,
    SourceBox,
    WeaknessReport,
)
from lemely.db.attempt_repo import AttemptRepository
from lemely.db.class_repo import ClassService
from lemely.db.models import ParentChildLink
from lemely.db.models.attempts import Attempt, QuestionResult, Upload
from lemely.db.models.enums import ReviewReason, ReviewStatus, Role
from lemely.db.models.ops import ReviewQueueItem
from lemely.db.paper_result_repo import (
    PaperResultNotFoundError,
    PaperResultService,
    challenge_rule,
)
from tests import test_web_review as _review
from tests.conftest import _scheme

pg_sessionmaker = _review.pg_sessionmaker
_seed_user = _review._seed_user

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker


def _q(
    question_id: str,
    *,
    awarded: int,
    maximum: int,
    confidence: float,
    needs_review: bool = False,
    topic: str = "Algebra · simultaneous equations",
    feedback: str | None = "Sign error in the constant",
    marker_source: str = "ai",
) -> CorrectedQuestion:
    return CorrectedQuestion(
        question_id=question_id,
        awarded_marks=awarded,
        maximum_marks=maximum,
        confidence=ConfidenceBand.HIGH if confidence >= 0.9 else ConfidenceBand.LOW,
        confidence_score=confidence,
        needs_teacher_review=needs_review,
        student_answer=f"answer-{question_id}",
        topic=topic,
        feedback=feedback,
        marker_source=marker_source,
        matched_point_ids=[],
    )


def _report(
    questions: list[CorrectedQuestion], *, subject: str = "0580", paper: int = 2, grade: str = "B"
) -> AccuracyReport:
    correction = CorrectionResult(
        metadata=ExamMetadata(
            subject_code=subject,
            paper_number=paper,
            paper_variant=1,
            session_month="May/June",
            session_year=2024,
        ),
        questions=questions,
    )
    awarded, maximum = correction.awarded_marks, correction.maximum_marks
    return AccuracyReport(
        correction=correction,
        weaknesses=WeaknessReport(weak_areas=[]),
        grade_prediction=GradePrediction(
            awarded_marks=awarded,
            maximum_marks=maximum,
            percentage=round(awarded / maximum * 100, 2) if maximum else 0.0,
            grade=grade,
            confidence=ConfidenceBand.LOW,
            boundary_source="global_default",
        ),
    )


def _persist(
    sm: sessionmaker[Session],
    owner: uuid.UUID,
    questions: list[CorrectedQuestion],
    *,
    recorded_at: datetime | None = None,
    with_scheme: bool = False,
    upload: bool = False,
    **report_kwargs: object,
) -> uuid.UUID:
    upload_id: uuid.UUID | None = None
    if upload:
        upload_id = uuid.uuid4()
        with sm.begin() as session:
            session.add(
                Upload(
                    id=upload_id,
                    user_id=owner,
                    storage_path=f"students/{owner}/{upload_id.hex}/scan.pdf",
                    original_filename="scan.pdf",
                    content_type="application/pdf",
                    byte_size=10,
                )
            )
    return AttemptRepository(sm).persist_correction(
        user_id=str(owner),
        report=_report(questions, **report_kwargs),  # type: ignore[arg-type]
        upload_id=upload_id,
        recorded_at=(recorded_at or datetime.now(UTC)).isoformat(),
        mark_scheme=_scheme() if with_scheme else None,
    )


def _qr(sm: sessionmaker[Session], attempt_id: uuid.UUID, question_id: str) -> uuid.UUID:
    with sm() as session:
        return session.scalars(
            sa.select(QuestionResult.id).where(
                QuestionResult.attempt_id == attempt_id, QuestionResult.question_id == question_id
            )
        ).one()


@pytest.fixture
def service(pg_sessionmaker: sessionmaker[Session]) -> PaperResultService:
    return PaperResultService(pg_sessionmaker)


def test_owner_reads_rows_in_paper_order_with_lost_marks(
    pg_sessionmaker: sessionmaker[Session], service: PaperResultService
) -> None:
    owner = _seed_user(pg_sessionmaker, Role.student)
    attempt = _persist(
        pg_sessionmaker,
        owner,
        [
            _q("10", awarded=1, maximum=3, confidence=0.88),
            _q("2", awarded=2, maximum=2, confidence=0.97),
            _q("1a", awarded=0, maximum=4, confidence=0.62),
        ],
    )
    view = service.get_result(owner, "student", attempt)
    assert [q.question_id for q in view.questions] == ["1a", "2", "10"]
    assert [q.lost for q in view.questions] == [4, 0, 2]
    assert view.viewer == "student"
    assert view.awarded == 3 and view.maximum == 9


def test_scheme_wording_only_on_low_confidence_losses(
    pg_sessionmaker: sessionmaker[Session], service: PaperResultService
) -> None:
    owner = _seed_user(pg_sessionmaker, Role.student)
    low = _persist(
        pg_sessionmaker, owner, [_q("1a", awarded=1, maximum=3, confidence=0.55)], with_scheme=True
    )
    high = _persist(
        pg_sessionmaker, owner, [_q("1a", awarded=1, maximum=3, confidence=0.82)], with_scheme=True
    )
    full = _persist(
        pg_sessionmaker, owner, [_q("1a", awarded=3, maximum=3, confidence=0.40)], with_scheme=True
    )
    assert service.get_result(owner, "student", low).questions[0].scheme_text == (
        "Correct method; Answer to 3sf; Units stated"
    )
    assert service.get_result(owner, "student", high).questions[0].scheme_text is None
    assert service.get_result(owner, "student", full).questions[0].scheme_text is None


def test_challenge_rule_turns_at_seventy_percent() -> None:
    assert challenge_rule(0.6999) == challenge_rule(0.0)
    assert challenge_rule(0.6999).confirm is False
    assert challenge_rule(0.6999).min_chars == 20
    assert challenge_rule(0.6999).needs_tick is False
    assert challenge_rule(0.70).confirm is True
    assert challenge_rule(0.70).min_chars == 40
    assert challenge_rule(0.70).needs_tick is True


def test_delta_and_first_paper_follow_the_same_subject_and_paper(
    pg_sessionmaker: sessionmaker[Session], service: PaperResultService
) -> None:
    owner = _seed_user(pg_sessionmaker, Role.student)
    now = datetime.now(UTC)
    first = _persist(
        pg_sessionmaker, owner, [_q("1", awarded=4, maximum=8, confidence=0.9)],
        recorded_at=now - timedelta(days=9),
    )
    _persist(  # another paper number: not "the last paper" for paper 2
        pg_sessionmaker, owner, [_q("1", awarded=1, maximum=8, confidence=0.9)],
        recorded_at=now - timedelta(days=5), paper=4,
    )
    latest = _persist(
        pg_sessionmaker, owner, [_q("1", awarded=6, maximum=8, confidence=0.9)], recorded_at=now
    )
    first_view = service.get_result(owner, "student", first)
    latest_view = service.get_result(owner, "student", latest)
    assert first_view.is_first_paper is True
    assert first_view.previous_awarded is None
    assert latest_view.is_first_paper is False
    assert latest_view.previous_awarded == 4


def test_has_crop_needs_a_box_and_an_upload(
    pg_sessionmaker: sessionmaker[Session], service: PaperResultService
) -> None:
    owner = _seed_user(pg_sessionmaker, Role.student)
    boxed = _q("1", awarded=1, maximum=3, confidence=0.6)
    boxed.source_box = SourceBox(page=0, box=[100, 100, 300, 400])
    with_upload = _persist(pg_sessionmaker, owner, [boxed], upload=True)
    no_upload = _persist(pg_sessionmaker, owner, [boxed.model_copy()])
    assert service.get_result(owner, "student", with_upload).questions[0].has_crop is True
    assert service.get_result(owner, "student", no_upload).questions[0].has_crop is False


def test_pending_teacher_comes_from_an_open_marker_review(
    pg_sessionmaker: sessionmaker[Session], service: PaperResultService
) -> None:
    owner = _seed_user(pg_sessionmaker, Role.student)
    attempt = _persist(
        pg_sessionmaker, owner, [_q("1", awarded=1, maximum=3, confidence=0.3, needs_review=True)]
    )
    assert service.get_result(owner, "student", attempt).questions[0].pending_teacher is True


def test_linked_parent_reads_without_student_only_fields(
    pg_sessionmaker: sessionmaker[Session], service: PaperResultService
) -> None:
    owner = _seed_user(pg_sessionmaker, Role.student)
    parent = _seed_user(pg_sessionmaker, Role.parent)
    with pg_sessionmaker.begin() as session:
        session.add(ParentChildLink(parent_id=parent, child_id=owner))
    attempt = _persist(
        pg_sessionmaker, owner, [_q("1a", awarded=1, maximum=3, confidence=0.55)], with_scheme=True
    )
    view = service.get_result(parent, "parent", attempt)
    assert view.viewer == "parent"
    assert view.reviewer is None
    assert all(q.self_reviewable is False for q in view.questions)


@pytest.mark.parametrize("who", ["other_student", "other_parent", "teacher"])
def test_anyone_else_gets_the_same_not_found(
    pg_sessionmaker: sessionmaker[Session], service: PaperResultService, who: str
) -> None:
    owner = _seed_user(pg_sessionmaker, Role.student)
    attempt = _persist(pg_sessionmaker, owner, [_q("1", awarded=1, maximum=3, confidence=0.6)])
    role = {"other_student": Role.student, "other_parent": Role.parent, "teacher": Role.teacher}[who]
    caller = _seed_user(pg_sessionmaker, role)
    with pytest.raises(PaperResultNotFoundError) as exc:
        service.get_result(caller, role.value, attempt)
    assert str(exc.value) == "No such paper"


def test_a_soft_deleted_attempt_is_not_found(
    pg_sessionmaker: sessionmaker[Session], service: PaperResultService
) -> None:
    owner = _seed_user(pg_sessionmaker, Role.student)
    attempt = _persist(pg_sessionmaker, owner, [_q("1", awarded=1, maximum=3, confidence=0.6)])
    with pg_sessionmaker.begin() as session:
        session.get(Attempt, attempt).deleted_at = datetime.now(UTC)  # type: ignore[union-attr]
    with pytest.raises(PaperResultNotFoundError):
        service.get_result(owner, "student", attempt)


def test_malformed_ids_are_not_found(service: PaperResultService) -> None:
    with pytest.raises(PaperResultNotFoundError):
        service.get_result(uuid.uuid4(), "student", "not-a-uuid")


def test_reviewer_prefers_the_class_for_this_subject(
    pg_sessionmaker: sessionmaker[Session], service: PaperResultService
) -> None:
    owner = _seed_user(pg_sessionmaker, Role.student)
    other_teacher = _seed_user(pg_sessionmaker, Role.teacher, display_name="Mr. Adel")
    maths_teacher = _seed_user(pg_sessionmaker, Role.teacher, display_name="Ms. Hanna")
    classes = ClassService(pg_sessionmaker)
    for teacher, name, code in [(other_teacher, "9A Physics", "0625"), (maths_teacher, "10B", "0580")]:
        cls = classes.create_class(teacher, name, subject_code=code)
        assert cls.join_code is not None
        classes.join_by_code(owner, cls.join_code)
    attempt = _persist(pg_sessionmaker, owner, [_q("1", awarded=1, maximum=3, confidence=0.6)])
    reviewer = service.get_result(owner, "student", attempt).reviewer
    assert reviewer is not None
    assert (reviewer.teacher_name, reviewer.class_name) == ("Ms. Hanna", "10B")


def test_crop_source_scopes_the_question_to_the_attempt(
    pg_sessionmaker: sessionmaker[Session], service: PaperResultService
) -> None:
    owner = _seed_user(pg_sessionmaker, Role.student)
    boxed = _q("1", awarded=1, maximum=3, confidence=0.6)
    boxed.source_box = SourceBox(page=1, box=[100, 100, 300, 400])
    attempt = _persist(pg_sessionmaker, owner, [boxed], upload=True)
    other = _persist(pg_sessionmaker, owner, [boxed.model_copy()], upload=True)
    path, box = service.get_crop_source(owner, "student", attempt, _qr(pg_sessionmaker, attempt, "1"))
    assert path.startswith(f"students/{owner}/")
    assert (box.page, box.box) == (1, [100, 100, 300, 400])
    with pytest.raises(PaperResultNotFoundError):
        service.get_crop_source(owner, "student", attempt, _qr(pg_sessionmaker, other, "1"))


def test_challenge_state_reads_the_queue_row(
    pg_sessionmaker: sessionmaker[Session], service: PaperResultService
) -> None:
    from lemely.db.models.challenges import MarkChallenge

    owner = _seed_user(pg_sessionmaker, Role.student)
    attempt = _persist(pg_sessionmaker, owner, [_q("1", awarded=1, maximum=4, confidence=0.82)])
    qr_id = _qr(pg_sessionmaker, attempt, "1")
    with pg_sessionmaker.begin() as session:
        item = ReviewQueueItem(
            attempt_id=attempt, question_result_id=qr_id, reason=ReviewReason.student_challenge
        )
        session.add(item)
        session.flush()
        session.add(
            MarkChallenge(
                attempt_id=attempt, question_result_id=qr_id, student_id=owner,
                review_queue_id=item.id, reason="x" * 40, confidence_at_send=0.82,
            )
        )
        item_id = item.id
    assert service.get_result(owner, "student", attempt).questions[0].challenge.state == "open"  # type: ignore[union-attr]
    with pg_sessionmaker.begin() as session:
        session.get(ReviewQueueItem, item_id).status = ReviewStatus.resolved  # type: ignore[union-attr]
        session.get(QuestionResult, qr_id).teacher_awarded_marks = 3  # type: ignore[union-attr]
    view = service.get_result(owner, "student", attempt)
    assert view.questions[0].challenge.state == "changed"  # type: ignore[union-attr]
    assert view.challenges_used == 1
```

- [ ] **Step 2: Run them to verify they fail**

Run: `PYTHONPATH=$PWD pytest tests/test_paper_result_repo.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'lemely.db.paper_result_repo'`.

- [ ] **Step 3: Write the implementation**

```python
# lemely/db/paper_result_repo.py
"""Read, crop and challenge one marked paper for the S1 result screen (lane L7).

A caller is a student (their own attempts) or a parent (attempts of a linked
child). One rule, :func:`_visible_attempt`, decides visibility for every method,
and every "not yours", "deleted", "no such id" and "malformed id" is the same
:class:`PaperResultNotFoundError` with the same message, so no route built on
this service can be used to learn which attempt ids exist.

The 0.70 confidence line is decided here and nowhere else: it picks which losses
show the scheme wording, whether a challenge needs a confirm step, and how long
the reason must be. The web layer forwards the decision per question.

Nothing here reads or returns an integrity flag, ``review_reason`` or the per-point
``awarded`` verdict (QUALITY-BAR.md; the self-review reveal contract).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime  # noqa: TC003 - dataclass field type, read at runtime
from typing import TYPE_CHECKING, Literal

from pydantic import ValidationError
from sqlalchemy import func, select

from lemely.core.schemas import SourceBox
from lemely.db.attempt_repo import self_review_withheld_ids
from lemely.db.models.attempts import Attempt, QuestionResult, QuestionResultPoint, Upload
from lemely.db.models.challenges import CHALLENGES_PER_PAPER, MarkChallenge
from lemely.db.models.enums import (
    AttemptOrigin,
    BoundarySource,
    MarkerSource,
    ReviewReason,
    ReviewStatus,
    SessionMonth,
)
from lemely.db.models.ops import ReviewQueueItem
from lemely.db.models.orgs import ClassEnrollment, SchoolClass
from lemely.db.models.users import ParentChildLink, User
from lemely.db.self_review_repo import points_are_settleable, question_sort_key

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker

#: At or above this, the marker was sure: a challenge needs a confirm step, a
#: 40-character reason and the scheme tick, and the loss shows no scheme wording.
LOW_CONFIDENCE = 0.70
#: The reason length asked for on a confident mark.
CONFIDENT_REASON_CHARS = 40
#: The reason length asked for on a low-confidence mark (the table's own floor).
LOW_CONFIDENCE_REASON_CHARS = 20
#: The one message every visibility failure carries.
NOT_FOUND_MESSAGE = "No such paper"

Viewer = Literal["student", "parent"]
ChallengeState = Literal["open", "kept", "changed"]
RefusalCode = Literal["already_sent", "no_loss", "pending_teacher", "limit", "no_reviewer"]

_SCORED_SOURCES = frozenset({MarkerSource.deterministic, MarkerSource.ai})


class PaperResultError(Exception):
    """Base class for result-screen failures."""


class PaperResultNotFoundError(PaperResultError):
    """Not visible to this caller, deleted, absent or malformed. One message for all."""

    def __init__(self) -> None:
        super().__init__(NOT_FOUND_MESSAGE)


class PaperResultValidationError(PaperResultError):
    """Stored data that cannot be served (a box that is not renderable)."""


@dataclass(frozen=True, slots=True)
class ChallengeRule:
    """What sending a challenge on one question takes."""

    confirm: bool
    min_chars: int
    needs_tick: bool


@dataclass(frozen=True, slots=True)
class Reviewer:
    """The teacher a challenge goes to, and the class that makes them the reviewer."""

    teacher_id: uuid.UUID
    teacher_name: str
    class_name: str


@dataclass(frozen=True, slots=True)
class ChallengeView:
    """A challenge already sent on one question."""

    state: ChallengeState
    sent_at: datetime


@dataclass(frozen=True, slots=True)
class ResultQuestion:
    """One question row of the result screen."""

    question_result_id: uuid.UUID
    question_id: str
    topic: str | None
    awarded: int
    maximum: int
    confidence: float
    feedback: str | None
    scheme_text: str | None
    has_crop: bool
    marker_scored: bool
    pending_teacher: bool
    self_reviewable: bool
    challenge: ChallengeView | None

    @property
    def lost(self) -> int:
        """Marks to win back on this question, never negative."""
        return max(self.maximum - self.awarded, 0)


@dataclass(frozen=True, slots=True)
class PaperResultView:
    """Everything the result screen shows for one attempt."""

    attempt_id: uuid.UUID
    viewer: Viewer
    subject_code: str | None
    paper_number: int | None
    paper_variant: int | None
    session_month: SessionMonth | None
    session_year: int | None
    awarded: int
    maximum: int
    percentage: float
    grade: str | None
    boundary_source: BoundarySource | None
    recorded_at: datetime
    previous_awarded: int | None
    is_first_paper: bool
    questions: list[ResultQuestion]
    challenges_used: int
    reviewer: Reviewer | None

    @property
    def challenge_limit(self) -> int:
        """Challenges allowed on one paper."""
        return CHALLENGES_PER_PAPER


def challenge_rule(confidence: float) -> ChallengeRule:
    """The friction for challenging a mark the marker was ``confidence`` sure of."""
    if confidence >= LOW_CONFIDENCE:
        return ChallengeRule(confirm=True, min_chars=CONFIDENT_REASON_CHARS, needs_tick=True)
    return ChallengeRule(confirm=False, min_chars=LOW_CONFIDENCE_REASON_CHARS, needs_tick=False)


def challenge_block(question: ResultQuestion, view: PaperResultView) -> RefusalCode | None:
    """Why this question cannot be challenged now, or ``None`` when it can.

    The order is the order a student would want to hear it in. The write path
    (:meth:`PaperResultService.send_challenge`) checks the same function under a
    row lock, so the screen and the server never disagree.
    """
    if question.challenge is not None:
        return "already_sent"
    if question.lost <= 0:
        return "no_loss"
    if question.pending_teacher:
        return "pending_teacher"
    if view.challenges_used >= view.challenge_limit:
        return "limit"
    if view.reviewer is None:
        return "no_reviewer"
    return None


def _as_uuid(value: uuid.UUID | str) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        raise PaperResultNotFoundError from None


def _viewer(role: str) -> Viewer:
    if role == "student":
        return "student"
    if role == "parent":
        return "parent"
    raise PaperResultNotFoundError


def _visible_attempt(
    session: Session, caller: uuid.UUID, viewer: Viewer, attempt_id: uuid.UUID, *, lock: bool = False
) -> Attempt:
    """The attempt, if this caller may see it. The one visibility rule."""
    stmt = select(Attempt).where(Attempt.id == attempt_id)
    if lock:
        stmt = stmt.with_for_update()
    attempt = session.scalars(stmt).first()
    if attempt is None or attempt.deleted_at is not None:
        raise PaperResultNotFoundError
    if viewer == "student" and attempt.user_id == caller:
        return attempt
    if viewer == "parent":
        linked = session.scalar(
            select(ParentChildLink.parent_id).where(
                ParentChildLink.parent_id == caller, ParentChildLink.child_id == attempt.user_id
            )
        )
        if linked is not None:
            return attempt
    raise PaperResultNotFoundError


def _reviewer(session: Session, student_id: uuid.UUID, subject_code: str | None) -> Reviewer | None:
    """The teacher of the student's class for this subject, else of their first class by name."""
    row = session.execute(
        select(SchoolClass.teacher_id, SchoolClass.name, User.display_name, User.email)
        .join(ClassEnrollment, ClassEnrollment.class_id == SchoolClass.id)
        .join(User, User.id == SchoolClass.teacher_id)
        .where(ClassEnrollment.student_id == student_id)
        .order_by(
            (SchoolClass.subject_code == subject_code).desc().nulls_last(), SchoolClass.name
        )
        .limit(1)
    ).first()
    if row is None:
        return None
    teacher_id, class_name, display_name, email = row
    return Reviewer(teacher_id=teacher_id, teacher_name=display_name or email, class_name=class_name)


def _open_marker_reviews(session: Session, question_ids: list[uuid.UUID]) -> set[uuid.UUID]:
    if not question_ids:
        return set()
    rows = session.execute(
        select(ReviewQueueItem.question_result_id).where(
            ReviewQueueItem.question_result_id.in_(question_ids),
            ReviewQueueItem.status == ReviewStatus.open,
            ReviewQueueItem.reason != ReviewReason.student_challenge,
        )
    ).scalars()
    return {qr_id for qr_id in rows if qr_id is not None}


def _challenge_state(
    challenge: MarkChallenge, item_status: ReviewStatus | None, qr: QuestionResult
) -> ChallengeState:
    if item_status == ReviewStatus.open:
        return "open"
    if qr.teacher_awarded_marks is not None and qr.teacher_awarded_marks != qr.awarded_marks:
        return "changed"
    return "kept"


class PaperResultService:
    """The S1 result read, its crop source and its challenge write."""

    def __init__(self, sessionmaker: sessionmaker[Session]) -> None:
        self._sessionmaker = sessionmaker

    def get_result(
        self, caller_id: uuid.UUID | str, caller_role: str, attempt_id: uuid.UUID | str
    ) -> PaperResultView:
        """The result view of one attempt for a student owner or a linked parent."""
        viewer = _viewer(caller_role)
        caller, attempt_uuid = _as_uuid(caller_id), _as_uuid(attempt_id)
        with self._sessionmaker() as session:
            attempt = _visible_attempt(session, caller, viewer, attempt_uuid)
            return self._build_view(session, attempt, viewer)

    def get_crop_source(
        self,
        caller_id: uuid.UUID | str,
        caller_role: str,
        attempt_id: uuid.UUID | str,
        question_result_id: uuid.UUID | str,
    ) -> tuple[str, SourceBox]:
        """The stored object path and box for one answer's crop.

        Every absence (no such question on this attempt, no upload, no box, no
        upload row) is :class:`PaperResultNotFoundError`, like a visibility failure.
        """
        viewer = _viewer(caller_role)
        caller = _as_uuid(caller_id)
        attempt_uuid, qr_uuid = _as_uuid(attempt_id), _as_uuid(question_result_id)
        with self._sessionmaker() as session:
            attempt = _visible_attempt(session, caller, viewer, attempt_uuid)
            qr = session.get(QuestionResult, qr_uuid)
            if qr is None or qr.attempt_id != attempt.id or attempt.upload_id is None:
                raise PaperResultNotFoundError
            coords = [qr.source_box_ymin, qr.source_box_xmin, qr.source_box_ymax, qr.source_box_xmax]
            page = qr.source_box_page
            if page is None or any(c is None for c in coords):
                raise PaperResultNotFoundError
            upload = session.get(Upload, attempt.upload_id)
            if upload is None:
                raise PaperResultNotFoundError
            storage_path = upload.storage_path
        try:
            box = SourceBox(page=page, box=[int(c) for c in coords if c is not None])
        except ValidationError as exc:
            raise PaperResultValidationError("Stored crop region is not usable") from exc
        return storage_path, box

    def _build_view(self, session: Session, attempt: Attempt, viewer: Viewer) -> PaperResultView:
        results = sorted(
            session.scalars(
                select(QuestionResult).where(QuestionResult.attempt_id == attempt.id)
            ).all(),
            key=lambda qr: question_sort_key(qr.question_id),
        )
        ids = [qr.id for qr in results]
        points: dict[uuid.UUID, list[QuestionResultPoint]] = {}
        if ids:
            for point in session.scalars(
                select(QuestionResultPoint)
                .where(QuestionResultPoint.question_result_id.in_(ids))
                .order_by(QuestionResultPoint.ordinal)
            ).all():
                points.setdefault(point.question_result_id, []).append(point)
        pending = _open_marker_reviews(session, ids)
        challenges = {
            c.question_result_id: c
            for c in session.scalars(
                select(MarkChallenge).where(MarkChallenge.attempt_id == attempt.id)
            ).all()
        }
        item_ids = [c.review_queue_id for c in challenges.values() if c.review_queue_id is not None]
        statuses: dict[uuid.UUID, ReviewStatus] = (
            dict(
                session.execute(
                    select(ReviewQueueItem.id, ReviewQueueItem.status).where(
                        ReviewQueueItem.id.in_(item_ids)
                    )
                ).tuples().all()
            )
            if item_ids
            else {}
        )
        withheld = self_review_withheld_ids(session, attempt.id) if viewer == "student" else set()

        questions: list[ResultQuestion] = []
        for qr in results:
            effective = qr.effective_marks
            lost = max(qr.maximum_marks - effective, 0)
            qr_points = points.get(qr.id, [])
            scheme_text = (
                "; ".join(p.point_text for p in qr_points)
                if qr_points and lost > 0 and qr.confidence_score < LOW_CONFIDENCE
                else None
            )
            challenge = challenges.get(qr.id)
            questions.append(
                ResultQuestion(
                    question_result_id=qr.id,
                    question_id=qr.question_id,
                    topic=qr.topic,
                    awarded=effective,
                    maximum=qr.maximum_marks,
                    confidence=qr.confidence_score,
                    feedback=qr.feedback,
                    scheme_text=scheme_text,
                    has_crop=qr.source_box_page is not None and attempt.upload_id is not None,
                    marker_scored=qr.marker_source in _SCORED_SOURCES,
                    pending_teacher=qr.id in pending,
                    self_reviewable=viewer == "student"
                    and bool(qr_points)
                    and points_are_settleable(qr_points)
                    and qr.id not in withheld,
                    challenge=None
                    if challenge is None
                    else ChallengeView(
                        state=_challenge_state(
                            challenge,
                            statuses.get(challenge.review_queue_id)
                            if challenge.review_queue_id is not None
                            else None,
                            qr,
                        ),
                        sent_at=challenge.created_at,
                    ),
                )
            )

        same_subject = (
            Attempt.user_id == attempt.user_id,
            Attempt.id != attempt.id,
            Attempt.deleted_at.is_(None),
            Attempt.origin == AttemptOrigin.past_paper,
            Attempt.subject_code.is_not_distinct_from(attempt.subject_code),
            Attempt.recorded_at < attempt.recorded_at,
        )
        earlier = session.scalar(select(func.count()).select_from(Attempt).where(*same_subject)) or 0
        previous = session.execute(
            select(Attempt.awarded_marks, Attempt.maximum_marks)
            .where(*same_subject, Attempt.paper_number.is_not_distinct_from(attempt.paper_number))
            .order_by(Attempt.recorded_at.desc())
            .limit(1)
        ).first()
        return PaperResultView(
            attempt_id=attempt.id,
            viewer=viewer,
            subject_code=attempt.subject_code,
            paper_number=attempt.paper_number,
            paper_variant=attempt.paper_variant,
            session_month=attempt.session_month,
            session_year=attempt.session_year,
            awarded=attempt.awarded_marks,
            maximum=attempt.maximum_marks,
            percentage=attempt.percentage,
            grade=attempt.grade,
            boundary_source=attempt.boundary_source,
            recorded_at=attempt.recorded_at,
            previous_awarded=previous[0]
            if previous is not None and previous[1] == attempt.maximum_marks
            else None,
            is_first_paper=earlier == 0,
            questions=questions,
            challenges_used=len(challenges),
            reviewer=_reviewer(session, attempt.user_id, attempt.subject_code)
            if viewer == "student"
            else None,
        )
```

Note for the implementer: `points_are_settleable` takes anything with the four group fields (`is_alternative`, `is_optional`, `group_key`, `group_max_marks`). `QuestionResultPoint` rows have them, so pass the ORM rows. If mypy rejects the protocol match, wrap the rows as `self_review_repo` does (its private `_PointFlags`) rather than adding a `type: ignore`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD pytest tests/test_paper_result_repo.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
pre-commit run --files lemely/db/paper_result_repo.py tests/test_paper_result_repo.py
git commit -S -m "feat(db): paper result read and crop source for students and parents" -- lemely/db/paper_result_repo.py tests/test_paper_result_repo.py
```

### Task 4: `PaperResultService.send_challenge`

**Files:**
- Modify: `lemely/db/paper_result_repo.py` (append errors and the method)
- Test: `tests/test_paper_result_repo.py` (append)

**Interfaces:**
- Consumes: everything from Task 3.
- Produces: `send_challenge(student_id, attempt_id, question_result_id, *, reason: str, compared_with_scheme: bool) -> PaperResultView`; `ChallengeRefusedError(code: RefusalCode)` with `.code`; `ChallengeInvalidError(message)`.

- [ ] **Step 1: Append the failing tests**

```python
# appended to tests/test_paper_result_repo.py
from lemely.db.models.challenges import MarkChallenge
from lemely.db.paper_result_repo import ChallengeInvalidError, ChallengeRefusedError


def _student_in_class(sm: sessionmaker[Session]) -> tuple[uuid.UUID, uuid.UUID]:
    student = _seed_user(sm, Role.student)
    teacher = _seed_user(sm, Role.teacher, display_name="Ms. Hanna")
    classes = ClassService(sm)
    cls = classes.create_class(teacher, "10B", subject_code="0580")
    assert cls.join_code is not None
    classes.join_by_code(student, cls.join_code)
    return student, teacher


def test_send_challenge_opens_a_queue_row_for_the_teacher(
    pg_sessionmaker: sessionmaker[Session], service: PaperResultService
) -> None:
    student, teacher = _student_in_class(pg_sessionmaker)
    attempt = _persist(pg_sessionmaker, student, [_q("1", awarded=1, maximum=4, confidence=0.82)])
    qr_id = _qr(pg_sessionmaker, attempt, "1")
    view = service.send_challenge(
        student, attempt, qr_id, reason="  " + "I wrote the unit on the next line, see ρ." + "  ",
        compared_with_scheme=True,
    )
    assert view.challenges_used == 1
    assert view.questions[0].challenge is not None
    assert view.questions[0].challenge.state == "open"
    with pg_sessionmaker() as session:
        challenge = session.scalars(sa.select(MarkChallenge)).one()
        item = session.get(ReviewQueueItem, challenge.review_queue_id)
        assert challenge.reason == "I wrote the unit on the next line, see ρ."
        assert challenge.compared_with_scheme is True
        assert item is not None
        assert item.reason == ReviewReason.student_challenge
        assert item.assigned_teacher_id == teacher


@pytest.mark.parametrize(
    ("confidence", "reason", "tick", "ok"),
    [
        (0.82, "x" * 39, True, False),
        (0.82, "x" * 40, False, False),
        (0.82, "x" * 40, True, True),
        (0.55, "x" * 19, False, False),
        (0.55, "x" * 20, False, True),
        (0.55, " " * 30 + "x" * 5, False, False),
    ],
)
def test_reason_length_and_tick_follow_confidence(
    pg_sessionmaker: sessionmaker[Session],
    service: PaperResultService,
    confidence: float,
    reason: str,
    tick: bool,
    ok: bool,
) -> None:
    student, _ = _student_in_class(pg_sessionmaker)
    attempt = _persist(
        pg_sessionmaker, student, [_q("1", awarded=1, maximum=4, confidence=confidence)]
    )
    qr_id = _qr(pg_sessionmaker, attempt, "1")
    if ok:
        service.send_challenge(student, attempt, qr_id, reason=reason, compared_with_scheme=tick)
    else:
        with pytest.raises(ChallengeInvalidError):
            service.send_challenge(student, attempt, qr_id, reason=reason, compared_with_scheme=tick)


def test_refusals_carry_their_code(
    pg_sessionmaker: sessionmaker[Session], service: PaperResultService
) -> None:
    student, _ = _student_in_class(pg_sessionmaker)
    attempt = _persist(
        pg_sessionmaker,
        student,
        [
            _q("1", awarded=1, maximum=4, confidence=0.55),
            _q("2", awarded=1, maximum=4, confidence=0.55),
            _q("3", awarded=1, maximum=4, confidence=0.55),
            _q("4", awarded=1, maximum=4, confidence=0.55),
            _q("5", awarded=4, maximum=4, confidence=0.55),
            _q("6", awarded=0, maximum=4, confidence=0.3, needs_review=True),
        ],
    )
    reason = "y" * 25

    def send(question_id: str) -> None:
        service.send_challenge(
            student, attempt, _qr(pg_sessionmaker, attempt, question_id),
            reason=reason, compared_with_scheme=False,
        )

    def refused(question_id: str) -> str:
        with pytest.raises(ChallengeRefusedError) as exc:
            send(question_id)
        return exc.value.code

    assert refused("5") == "no_loss"
    assert refused("6") == "pending_teacher"
    send("1")
    assert refused("1") == "already_sent"
    send("2")
    send("3")
    assert refused("4") == "limit"


def test_no_class_means_no_reviewer(
    pg_sessionmaker: sessionmaker[Session], service: PaperResultService
) -> None:
    student = _seed_user(pg_sessionmaker, Role.student)
    attempt = _persist(pg_sessionmaker, student, [_q("1", awarded=1, maximum=4, confidence=0.55)])
    with pytest.raises(ChallengeRefusedError) as exc:
        service.send_challenge(
            student, attempt, _qr(pg_sessionmaker, attempt, "1"),
            reason="z" * 25, compared_with_scheme=False,
        )
    assert exc.value.code == "no_reviewer"


def test_another_students_attempt_is_not_found(
    pg_sessionmaker: sessionmaker[Session], service: PaperResultService
) -> None:
    owner, _ = _student_in_class(pg_sessionmaker)
    intruder, _ = _student_in_class(pg_sessionmaker)
    attempt = _persist(pg_sessionmaker, owner, [_q("1", awarded=1, maximum=4, confidence=0.55)])
    with pytest.raises(PaperResultNotFoundError):
        service.send_challenge(
            intruder, attempt, _qr(pg_sessionmaker, attempt, "1"),
            reason="z" * 25, compared_with_scheme=False,
        )
```

- [ ] **Step 2: Run them to verify they fail**

Run: `PYTHONPATH=$PWD pytest tests/test_paper_result_repo.py -k "challenge or refusal or reviewer or another" -v`
Expected: FAIL with `ImportError: cannot import name 'ChallengeInvalidError'`.

- [ ] **Step 3: Append the implementation to `lemely/db/paper_result_repo.py`**

Add next to the other error classes:

```python
class ChallengeRefusedError(PaperResultError):
    """The question cannot be challenged now. ``code`` says why (409)."""

    def __init__(self, code: RefusalCode) -> None:
        super().__init__(code)
        self.code: RefusalCode = code


class ChallengeInvalidError(PaperResultError):
    """The reason or the tick does not meet the rule for this question (422)."""
```

Add `from lemely.db.models.challenges import REASON_MAX_CHARS` to the existing `challenges` import line, and add this method to `PaperResultService`:

```python
    def send_challenge(
        self,
        student_id: uuid.UUID | str,
        attempt_id: uuid.UUID | str,
        question_result_id: uuid.UUID | str,
        *,
        reason: str,
        compared_with_scheme: bool,
    ) -> PaperResultView:
        """Record one challenge and open its queue row for the student's teacher.

        The attempt row is locked ``FOR UPDATE`` first, so two sends on one paper
        cannot both pass the limit or both pass the one-per-question check.
        """
        student = _as_uuid(student_id)
        attempt_uuid, qr_uuid = _as_uuid(attempt_id), _as_uuid(question_result_id)
        text = reason.strip()
        with self._sessionmaker.begin() as session:
            attempt = _visible_attempt(session, student, "student", attempt_uuid, lock=True)
            qr = session.get(QuestionResult, qr_uuid)
            if qr is None or qr.attempt_id != attempt.id:
                raise PaperResultNotFoundError
            view = self._build_view(session, attempt, "student")
            question = next(q for q in view.questions if q.question_result_id == qr.id)
            code = challenge_block(question, view)
            if code is not None:
                raise ChallengeRefusedError(code)
            rule = challenge_rule(qr.confidence_score)
            if len(text) < rule.min_chars:
                raise ChallengeInvalidError(f"Write at least {rule.min_chars} characters.")
            if len(text) > REASON_MAX_CHARS:
                raise ChallengeInvalidError(f"Keep it under {REASON_MAX_CHARS} characters.")
            if rule.needs_tick and not compared_with_scheme:
                raise ChallengeInvalidError(
                    "Tick that you compared your answer with the mark scheme."
                )
            assert view.reviewer is not None  # noqa: S101 - challenge_block returned None
            item = ReviewQueueItem(
                attempt_id=attempt.id,
                question_result_id=qr.id,
                reason=ReviewReason.student_challenge,
                assigned_teacher_id=view.reviewer.teacher_id,
            )
            session.add(item)
            session.flush()
            session.add(
                MarkChallenge(
                    attempt_id=attempt.id,
                    question_result_id=qr.id,
                    student_id=student,
                    review_queue_id=item.id,
                    reason=text,
                    confidence_at_send=qr.confidence_score,
                    compared_with_scheme=compared_with_scheme,
                )
            )
        return self.get_result(student, "student", attempt_uuid)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD pytest tests/test_paper_result_repo.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
pre-commit run --files lemely/db/paper_result_repo.py tests/test_paper_result_repo.py
git commit -S -m "feat(db): mark challenges with the 3-per-paper limit" -- lemely/db/paper_result_repo.py tests/test_paper_result_repo.py
```

### Task 5: DTOs, router, dependency wiring and the full authz matrix

**Files:**
- Create: `lemely/web/schemas_paper_result.py`
- Create: `lemely/web/routers/paper_result.py`
- Modify: `lemely/web/deps.py` (add `get_paper_result_service` after `get_self_review_service`, and its `cache_clear()` in `reset_singletons`)
- Modify: `lemely/web/routers/__init__.py` if it re-exports router modules (add `paper_result` the same way the others are listed), and `lemely/web/app.py` (one `app.include_router(paper_result.router)` line)
- Modify: `tests/test_authz_matrix_complete.py` (three `EXPECTED` rows)
- Test: `tests/test_web_paper_result.py`

**Interfaces:**
- Consumes: `PaperResultService` (Tasks 3, 4), `render_scan_crop` and `NO_STORE_HEADERS` (Task 2), `GradeBoundaryStore`, `get_profile`, `GRADE_ORDER`.
- Produces HTTP:
  - `GET /api/attempts/{attempt_id}/result` (student or parent) returns `PaperResultDTO`
  - `GET /api/attempts/{attempt_id}/questions/{question_result_id}/crop` (student or parent) returns `image/png`, `Cache-Control: private, no-store`
  - `POST /api/attempts/{attempt_id}/questions/{question_result_id}/challenge` (student only) takes `ChallengeRequestDTO` and returns 201 `PaperResultDTO`; 409 `{"detail": {"code": RefusalCode, "message": str}}`; 422 `{"detail": str}`
  - Every visibility failure is 404 `{"detail": "No such paper"}`. Every crop absence is 404 `{"detail": "No scan crop for this answer"}`.
- Produces Python: `get_paper_result_service() -> PaperResultService`.

- [ ] **Step 1: Write the failing route tests (the authz matrix)**

```python
# tests/test_web_paper_result.py
"""``/api/attempts/...`` (lane L7): the result read and the crop, as an authz matrix.

Callers: the owner, another student, a linked parent, an unlinked parent, the
student's teacher, a school admin, a platform admin, and nobody. Targets: the
owner's attempt, a soft-deleted attempt, another student's attempt, a question id
from another attempt, an unknown id and a malformed id. Every cell is asserted.
All scans are synthetic (``tests/test_web_review.py``'s generator).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from lemely.core.schemas import SourceBox
from lemely.db.attempt_repo import AttemptRepository
from lemely.db.class_repo import ClassService
from lemely.db.models import ParentChildLink
from lemely.db.models.attempts import Attempt, QuestionResult, Upload
from lemely.db.models.enums import Role
from lemely.db.paper_result_repo import PaperResultService
from lemely.db.review_repo import ReviewService
from lemely.web import create_app
from lemely.web.deps import (
    AuthContext,
    get_auth_context,
    get_paper_result_service,
    get_review_service,
    get_settings,
    get_storage_backend,
)
from tests import test_web_review as _review
from tests.sandbox_fixtures import in_process_sandbox  # noqa: F401
from tests.storage_fakes import FakeStorageBackend

pg_sessionmaker = _review.pg_sessionmaker
_seed_user = _review._seed_user
_question = _review._question
_report = _review._report
_synthetic_scan = _review._synthetic_scan
_MARK_BOX = _review._MARK_BOX
_MARKED_PAGE = _review._MARKED_PAGE

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker

NOT_FOUND = {"detail": "No such paper"}
CROP_ABSENT = {"detail": "No scan crop for this answer"}


@pytest.fixture
def storage() -> FakeStorageBackend:
    return FakeStorageBackend()


@pytest.fixture
def client(
    pg_sessionmaker: sessionmaker[Session], storage: FakeStorageBackend
) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_paper_result_service] = lambda: PaperResultService(pg_sessionmaker)
    app.dependency_overrides[get_review_service] = lambda: ReviewService(
        pg_sessionmaker, ClassService(pg_sessionmaker)
    )
    app.dependency_overrides[get_storage_backend] = lambda: storage
    yield TestClient(app)
    app.dependency_overrides.clear()


def _as(client: TestClient, user: uuid.UUID, role: Role) -> None:
    client.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[union-attr]
        user_id=str(user), role=role.value
    )


def seed_scanned_attempt(
    sm: sessionmaker[Session],
    storage: FakeStorageBackend,
    owner: uuid.UUID,
    questions: list,  # list[CorrectedQuestion]
    *,
    with_box: bool = True,
    store_object: bool = True,
) -> uuid.UUID:
    """An attempt with an uploaded synthetic scan and (optionally) a box per question."""
    upload_id = uuid.uuid4()
    object_path = f"students/{owner}/{upload_id.hex}/scan.pdf"
    scan = _synthetic_scan()
    with sm.begin() as session:
        session.add(
            Upload(
                id=upload_id,
                user_id=owner,
                storage_path=object_path,
                original_filename="scan.pdf",
                content_type="application/pdf",
                byte_size=len(scan),
            )
        )
    if store_object:
        storage.upload(get_settings().storage.bucket, object_path, scan, "application/pdf")
    if with_box:
        for question in questions:
            question.source_box = SourceBox(page=_MARKED_PAGE, box=list(_MARK_BOX))
    return AttemptRepository(sm).persist_correction(
        user_id=str(owner), report=_report(questions), upload_id=upload_id
    )


def qr_id(sm: sessionmaker[Session], attempt: uuid.UUID, question_id: str = "1") -> uuid.UUID:
    with sm() as session:
        return session.scalars(
            sa.select(QuestionResult.id).where(
                QuestionResult.attempt_id == attempt, QuestionResult.question_id == question_id
            )
        ).one()


@dataclass(frozen=True)
class World:
    users: dict[str, uuid.UUID]
    attempt: uuid.UUID
    qr: uuid.UUID
    deleted_attempt: uuid.UUID
    deleted_qr: uuid.UUID
    other_attempt: uuid.UUID
    other_qr: uuid.UUID


ROLES = {
    "owner": Role.student,
    "other_student": Role.student,
    "linked_parent": Role.parent,
    "other_parent": Role.parent,
    "teacher": Role.teacher,
    "school_admin": Role.school_admin,
    "platform_admin": Role.platform_admin,
}


@pytest.fixture
def world(pg_sessionmaker: sessionmaker[Session], storage: FakeStorageBackend) -> World:
    users = {name: _seed_user(pg_sessionmaker, role) for name, role in ROLES.items()}
    classes = ClassService(pg_sessionmaker)
    cls = classes.create_class(users["teacher"], "10B")
    assert cls.join_code is not None
    classes.join_by_code(users["owner"], cls.join_code)
    with pg_sessionmaker.begin() as session:
        session.add(ParentChildLink(parent_id=users["linked_parent"], child_id=users["owner"]))
        session.add(ParentChildLink(parent_id=users["other_parent"], child_id=users["other_student"]))
    q = lambda: _question("1", awarded=1, maximum=4, confidence_score=0.82, needs_review=False)  # noqa: E731
    attempt = seed_scanned_attempt(pg_sessionmaker, storage, users["owner"], [q()])
    deleted = seed_scanned_attempt(pg_sessionmaker, storage, users["owner"], [q()])
    other = seed_scanned_attempt(pg_sessionmaker, storage, users["other_student"], [q()])
    with pg_sessionmaker.begin() as session:
        session.get(Attempt, deleted).deleted_at = datetime.now(UTC)  # type: ignore[union-attr]
    return World(
        users=users,
        attempt=attempt,
        qr=qr_id(pg_sessionmaker, attempt),
        deleted_attempt=deleted,
        deleted_qr=qr_id(pg_sessionmaker, deleted),
        other_attempt=other,
        other_qr=qr_id(pg_sessionmaker, other),
    )


def _target(world: World, name: str) -> tuple[str, str]:
    return {
        "own": (str(world.attempt), str(world.qr)),
        "deleted": (str(world.deleted_attempt), str(world.deleted_qr)),
        "other": (str(world.other_attempt), str(world.other_qr)),
        "mismatch": (str(world.attempt), str(world.other_qr)),
        "unknown": (str(uuid.uuid4()), str(uuid.uuid4())),
        "malformed": ("not-a-uuid", "nope"),
    }[name]


MATRIX = [
    ("owner", "own", 200),
    ("linked_parent", "own", 200),
    ("other_student", "own", 404),
    ("other_parent", "own", 404),
    ("teacher", "own", 403),
    ("school_admin", "own", 403),
    ("platform_admin", "own", 403),
    ("owner", "deleted", 404),
    ("linked_parent", "deleted", 404),
    ("owner", "other", 404),
    ("linked_parent", "other", 404),
    ("owner", "mismatch", 404),
    ("owner", "unknown", 404),
    ("owner", "malformed", 404),
    ("linked_parent", "malformed", 404),
]


@pytest.mark.usefixtures("in_process_sandbox")
@pytest.mark.parametrize(("caller", "target", "status"), MATRIX)
def test_crop_matrix(client: TestClient, world: World, caller: str, target: str, status: int) -> None:
    _as(client, world.users[caller], ROLES[caller])
    attempt, question = _target(world, target)
    resp = client.get(f"/api/attempts/{attempt}/questions/{question}/crop")
    assert resp.status_code == status
    if status == 200:
        assert resp.headers["content-type"] == "image/png"
        assert resp.headers["cache-control"] == "private, no-store"
    if status == 404:
        assert resp.json() == NOT_FOUND


@pytest.mark.parametrize(("caller", "target", "status"), [m for m in MATRIX if m[1] != "mismatch"])
def test_result_matrix(client: TestClient, world: World, caller: str, target: str, status: int) -> None:
    _as(client, world.users[caller], ROLES[caller])
    attempt, _ = _target(world, target)
    resp = client.get(f"/api/attempts/{attempt}/result")
    assert resp.status_code == status
    if status == 404:
        assert resp.json() == NOT_FOUND


def test_unauthenticated_is_401_on_both_reads(client: TestClient, world: World) -> None:
    client.app.dependency_overrides.pop(get_auth_context, None)  # type: ignore[union-attr]
    assert client.get(f"/api/attempts/{world.attempt}/result").status_code == 401
    assert client.get(f"/api/attempts/{world.attempt}/questions/{world.qr}/crop").status_code == 401


@pytest.mark.usefixtures("in_process_sandbox")
def test_crop_absences_share_one_body(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], storage: FakeStorageBackend
) -> None:
    owner = _seed_user(pg_sessionmaker, Role.student)
    q = lambda: _question("1", awarded=1, maximum=4, confidence_score=0.82, needs_review=False)  # noqa: E731
    no_box = seed_scanned_attempt(pg_sessionmaker, storage, owner, [q()], with_box=False)
    expired = seed_scanned_attempt(pg_sessionmaker, storage, owner, [q()], store_object=False)
    _as(client, owner, Role.student)
    first = client.get(f"/api/attempts/{no_box}/questions/{qr_id(pg_sessionmaker, no_box)}/crop")
    second = client.get(f"/api/attempts/{expired}/questions/{qr_id(pg_sessionmaker, expired)}/crop")
    assert first.status_code == 404 and first.json() == NOT_FOUND  # no box: visibility-shaped
    assert second.status_code == 404 and second.json() == CROP_ABSENT  # stored object gone


def test_student_payload_shape(client: TestClient, world: World) -> None:
    _as(client, world.users["owner"], Role.student)
    body = client.get(f"/api/attempts/{world.attempt}/result").json()
    assert body["viewer"] == "student"
    assert body["challengeLimit"] == 3
    assert body["challengesUsed"] == 0
    assert body["reviewer"]["className"] == "10B"
    question = body["questions"][0]
    assert question["lostMarks"] == 3
    assert question["hasCrop"] is True
    assert question["canChallenge"] is True
    assert question["challengeBlock"] is None
    assert question["confirmChallenge"] is True
    assert question["minReasonChars"] == 40
    assert question["needsSchemeTick"] is True
    # Never on a student payload: integrity, the raw reason, the per-point verdict.
    flat = str(body)
    for banned in ("plagiarism", "reviewReason", "matchedPointIds", "awardedPoints"):
        assert banned not in flat


def test_parent_payload_cannot_challenge(client: TestClient, world: World) -> None:
    _as(client, world.users["linked_parent"], Role.parent)
    body = client.get(f"/api/attempts/{world.attempt}/result").json()
    assert body["viewer"] == "parent"
    assert body["reviewer"] is None
    assert body["questions"][0]["canChallenge"] is False
    assert body["questions"][0]["selfReviewable"] is False
```

- [ ] **Step 2: Run them to verify they fail**

Run: `PYTHONPATH=$PWD pytest tests/test_web_paper_result.py -v`
Expected: FAIL with `ImportError: cannot import name 'get_paper_result_service'`.

- [ ] **Step 3: Write the DTOs**

```python
# lemely/web/schemas_paper_result.py
"""API DTOs for ``/api/attempts/...`` (lane L7, S1 result).

No field carries an integrity flag, ``review_reason`` or a per-point verdict.
``schemeText`` is point wording only, and only on a low-confidence loss.
"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - pydantic needs the runtime type
from typing import Literal

from pydantic import Field, field_validator

from lemely.db.models.challenges import REASON_MAX_CHARS
from lemely.web.schemas import ApiModel

ChallengeStateWire = Literal["open", "kept", "changed"]
ChallengeBlockWire = Literal["already_sent", "no_loss", "pending_teacher", "limit", "no_reviewer"]


class ResultChallengeDTO(ApiModel):
    state: ChallengeStateWire
    sentAt: datetime


class ResultReviewerDTO(ApiModel):
    teacherName: str
    className: str


class ResultQuestionDTO(ApiModel):
    questionResultId: str
    questionId: str
    topic: str | None
    awardedMarks: int
    maxMarks: int
    lostMarks: int
    confidence: float
    feedback: str | None
    schemeText: str | None
    hasCrop: bool
    markerScored: bool
    pendingTeacher: bool
    selfReviewable: bool
    challenge: ResultChallengeDTO | None
    canChallenge: bool
    challengeBlock: ChallengeBlockWire | None
    confirmChallenge: bool
    minReasonChars: int
    needsSchemeTick: bool


class PaperResultDTO(ApiModel):
    attemptId: str
    viewer: Literal["student", "parent"]
    subjectCode: str | None
    subjectName: str | None
    paperNumber: int | None
    paperVariant: int | None
    sessionLabel: str | None
    awardedMarks: int
    maxMarks: int
    percentage: int
    grade: str | None
    boundaryEstimated: bool
    nextGrade: str | None
    marksToNextGrade: int | None
    deltaVsLast: int | None
    isFirstPaper: bool
    recordedAt: datetime
    questions: list[ResultQuestionDTO]
    challengeLimit: int
    challengesUsed: int
    reviewer: ResultReviewerDTO | None


class ChallengeRequestDTO(ApiModel):
    reason: str = Field(min_length=1, max_length=REASON_MAX_CHARS)
    comparedWithScheme: bool = False

    @field_validator("reason")
    @classmethod
    def _no_nul(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("reason must not contain NUL characters")
        return value


__all__ = [
    "ChallengeRequestDTO",
    "PaperResultDTO",
    "ResultChallengeDTO",
    "ResultQuestionDTO",
    "ResultReviewerDTO",
]
```

- [ ] **Step 4: Write the router**

```python
# lemely/web/routers/paper_result.py
"""The S1 result read, the answer crop and mark challenges (lane L7).

``/api/attempts/{attempt_id}/...``, for a student (their own attempts) and a parent
(a linked child's attempts). Visibility is decided once, in
:class:`~lemely.db.paper_result_repo.PaperResultService`; this module only maps
errors to statuses and views to DTOs. An image route that resolves its own
ownership is where IDOR gets written, so the crop asks the service too.

Every visibility failure is the same 404 body (no oracle for other students'
attempt ids). The challenge route is student-only.
"""

from __future__ import annotations

import math
from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Response

from lemely.core.history import GRADE_ORDER
from lemely.core.schemas import ExamMetadata
from lemely.db.models.enums import SESSION_MONTH_LABELS, BoundarySource, Role, SessionMonth
from lemely.db.paper_result_repo import (
    ChallengeInvalidError,
    ChallengeRefusedError,
    PaperResultError,
    PaperResultNotFoundError,
    PaperResultService,
    PaperResultView,
    RefusalCode,
    ResultQuestion,
    challenge_block,
    challenge_rule,
)
from lemely.io.det.profiles import get_profile
from lemely.io.grade_boundaries import GradeBoundaryStore
from lemely.io.storage import StorageBackend  # noqa: TC001 - FastAPI resolves it at runtime
from lemely.runtime.config import Settings  # noqa: TC001 - FastAPI resolves it at runtime
from lemely.web.deps import (
    AuthContext,
    get_paper_result_service,
    get_settings,
    get_storage_backend,
    require_role,
)
from lemely.web.scan_crop import NO_STORE_HEADERS, render_scan_crop
from lemely.web.schemas_paper_result import (
    ChallengeRequestDTO,
    PaperResultDTO,
    ResultChallengeDTO,
    ResultQuestionDTO,
    ResultReviewerDTO,
)

router = APIRouter(prefix="/api/attempts")

NOT_FOUND_DETAIL = "No such paper"
CROP_ABSENT_DETAIL = "No scan crop for this answer"

#: The copy a student reads for each refusal. Kept beside the codes so the two cannot drift.
REFUSAL_COPY: dict[RefusalCode, str] = {
    "already_sent": "You already challenged this mark.",
    "no_loss": "This answer got full marks.",
    "pending_teacher": "Your teacher is already checking this one.",
    "limit": "You have used all 3 challenges on this paper.",
    "no_reviewer": "Join a class so a teacher can check your challenges.",
}

_SHORT_MONTH: dict[SessionMonth, str] = {
    SessionMonth.may_june: "May/Jun",
    SessionMonth.oct_nov: "Oct/Nov",
    SessionMonth.feb_mar: "Feb/Mar",
    SessionMonth.specimen: "Specimen",
}


def _raise_for(exc: PaperResultError) -> NoReturn:
    if isinstance(exc, PaperResultNotFoundError):
        raise HTTPException(status_code=404, detail=NOT_FOUND_DETAIL) from exc
    if isinstance(exc, ChallengeRefusedError):
        raise HTTPException(
            status_code=409, detail={"code": exc.code, "message": REFUSAL_COPY[exc.code]}
        ) from exc
    raise HTTPException(status_code=422, detail=str(exc)) from exc


def _session_label(view: PaperResultView) -> str | None:
    if view.session_month is None:
        return None
    month = _SHORT_MONTH[view.session_month]
    return f"{month} {view.session_year}" if view.session_year else month


def _next_grade(view: PaperResultView) -> tuple[str | None, int | None]:
    """The grade above this one and the marks still needed, from the boundary table.

    The same arithmetic as ``routers/parent.py::_grade_boundary_distance``
    (``ceil`` of the threshold, clamped at zero). ``(None, None)`` when the
    grade is the top one, unknown, or the metadata is incomplete.
    """
    if view.grade not in GRADE_ORDER or GRADE_ORDER.index(view.grade) == 0 or view.maximum <= 0:
        return None, None
    if (
        view.subject_code is None
        or view.paper_number is None
        or view.paper_variant is None
        or view.session_month is None
    ):
        return None, None
    try:
        metadata = ExamMetadata(
            subject_code=view.subject_code,
            paper_number=view.paper_number,
            paper_variant=view.paper_variant,
            session_month=SESSION_MONTH_LABELS[view.session_month],
            session_year=view.session_year,
        )
    except ValueError:
        return None, None
    next_grade = GRADE_ORDER[GRADE_ORDER.index(view.grade) - 1]
    boundaries, _ = GradeBoundaryStore().resolve(metadata)
    threshold = boundaries.get(next_grade)
    if threshold is None:
        return None, None
    needed = max(math.ceil(threshold / 100.0 * view.maximum) - view.awarded, 0)
    return next_grade, needed


def _question_dto(question: ResultQuestion, view: PaperResultView) -> ResultQuestionDTO:
    rule = challenge_rule(question.confidence)
    block = challenge_block(question, view) if view.viewer == "student" else None
    return ResultQuestionDTO(
        questionResultId=str(question.question_result_id),
        questionId=question.question_id,
        topic=question.topic,
        awardedMarks=question.awarded,
        maxMarks=question.maximum,
        lostMarks=question.lost,
        confidence=question.confidence,
        feedback=question.feedback,
        schemeText=question.scheme_text,
        hasCrop=question.has_crop,
        markerScored=question.marker_scored,
        pendingTeacher=question.pending_teacher,
        selfReviewable=question.self_reviewable,
        challenge=None
        if question.challenge is None
        else ResultChallengeDTO(state=question.challenge.state, sentAt=question.challenge.sent_at),
        canChallenge=view.viewer == "student" and block is None,
        challengeBlock=block,
        confirmChallenge=rule.confirm,
        minReasonChars=rule.min_chars,
        needsSchemeTick=rule.needs_tick,
    )


def _dto(view: PaperResultView) -> PaperResultDTO:
    next_grade, marks_to_next = _next_grade(view)
    return PaperResultDTO(
        attemptId=str(view.attempt_id),
        viewer=view.viewer,
        subjectCode=view.subject_code,
        subjectName=(get_profile(view.subject_code).name or None) if view.subject_code else None,
        paperNumber=view.paper_number,
        paperVariant=view.paper_variant,
        sessionLabel=_session_label(view),
        awardedMarks=view.awarded,
        maxMarks=view.maximum,
        percentage=round(view.percentage),
        grade=view.grade or None,
        boundaryEstimated=view.boundary_source != BoundarySource.exact,
        nextGrade=next_grade,
        marksToNextGrade=marks_to_next,
        deltaVsLast=None if view.previous_awarded is None else view.awarded - view.previous_awarded,
        isFirstPaper=view.is_first_paper,
        recordedAt=view.recorded_at,
        questions=[_question_dto(q, view) for q in view.questions],
        challengeLimit=view.challenge_limit,
        challengesUsed=view.challenges_used,
        reviewer=None
        if view.reviewer is None
        else ResultReviewerDTO(
            teacherName=view.reviewer.teacher_name, className=view.reviewer.class_name
        ),
    )


@router.get("/{attempt_id}/result", response_model=PaperResultDTO)
def get_paper_result(
    attempt_id: str,
    auth: Annotated[AuthContext, Depends(require_role(Role.student, Role.parent))],
    service: Annotated[PaperResultService, Depends(get_paper_result_service)],
) -> PaperResultDTO:
    """The S1 result of one attempt, for its student or a linked parent."""
    try:
        view = service.get_result(auth.user_id, auth.role, attempt_id)
    except PaperResultError as exc:
        _raise_for(exc)
    return _dto(view)


@router.get(
    "/{attempt_id}/questions/{question_result_id}/crop",
    responses={200: {"content": {"image/png": {}}, "description": "The boxed answer region"}},
)
def get_answer_crop(
    attempt_id: str,
    question_result_id: str,
    auth: Annotated[AuthContext, Depends(require_role(Role.student, Role.parent))],
    settings: Annotated[Settings, Depends(get_settings)],
    service: Annotated[PaperResultService, Depends(get_paper_result_service)],
    storage: Annotated[StorageBackend, Depends(get_storage_backend)],
) -> Response:
    """The region of the scan this answer was read from. A ``def`` route: storage blocks."""
    try:
        object_path, box = service.get_crop_source(
            auth.user_id, auth.role, attempt_id, question_result_id
        )
    except PaperResultError as exc:
        _raise_for(exc)
    png = render_scan_crop(
        storage,
        settings.storage.bucket,
        object_path,
        box,
        event_prefix="answer_crop",
        absent_detail=CROP_ABSENT_DETAIL,
        attempt_id=attempt_id,
        question_result_id=question_result_id,
    )
    return Response(content=png, media_type="image/png", headers=NO_STORE_HEADERS)


@router.post(
    "/{attempt_id}/questions/{question_result_id}/challenge",
    response_model=PaperResultDTO,
    status_code=201,
)
def send_challenge(
    attempt_id: str,
    question_result_id: str,
    payload: ChallengeRequestDTO,
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    service: Annotated[PaperResultService, Depends(get_paper_result_service)],
) -> PaperResultDTO:
    """Challenge one mark. 409 with a code when it cannot be challenged; 422 on the reason."""
    try:
        view = service.send_challenge(
            auth.user_id,
            attempt_id,
            question_result_id,
            reason=payload.reason,
            compared_with_scheme=payload.comparedWithScheme,
        )
    except (ChallengeRefusedError, ChallengeInvalidError, PaperResultError) as exc:
        _raise_for(exc)
    return _dto(view)


__all__ = ["router"]
```

- [ ] **Step 5: Wire the dependency and the router**

In `lemely/web/deps.py`, import `from lemely.db.paper_result_repo import PaperResultService` with the other repo imports, and add after `get_self_review_service`:

```python
@lru_cache(maxsize=1)
def get_paper_result_service() -> PaperResultService:
    """Return the process-wide :class:`PaperResultService` singleton (lane L7, S1 result).

    Session factory only: visibility (owner student or linked parent) is decided
    inside the service against ``parent_child_links`` directly.
    """
    return PaperResultService(get_sessionmaker(get_settings()))
```

Add `get_paper_result_service.cache_clear()` to `reset_singletons()`, after `get_self_review_service.cache_clear()`.

In `lemely/web/app.py`, add `paper_result,` to the `from lemely.web.routers import (...)` list, and `app.include_router(paper_result.router)` after `app.include_router(admin_tutoring_reports.router)`.

In `tests/test_authz_matrix_complete.py`, add to `EXPECTED` beside the self-review rows:

```python
    ("GET", "/api/attempts/{attempt_id}/result"): STUDENT_OR_PARENT,
    ("GET", "/api/attempts/{attempt_id}/questions/{question_result_id}/crop"): STUDENT_OR_PARENT,
    ("POST", "/api/attempts/{attempt_id}/questions/{question_result_id}/challenge"): STUDENT,
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD pytest tests/test_web_paper_result.py tests/test_authz_matrix_complete.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
pre-commit run --files lemely/web/schemas_paper_result.py lemely/web/routers/paper_result.py lemely/web/deps.py lemely/web/app.py tests/test_web_paper_result.py tests/test_authz_matrix_complete.py
git commit -S -m "feat(web): attempt result and answer crop routes for students and parents" -- lemely/web/schemas_paper_result.py lemely/web/routers/paper_result.py lemely/web/deps.py lemely/web/app.py tests/test_web_paper_result.py tests/test_authz_matrix_complete.py
```

(Add `lemely/web/routers/__init__.py` to both lists if Step 5 edited it.)

### Task 6: Challenge route tests, the teacher's view of a challenge, and the parent `attemptId`

**Files:**
- Test: `tests/test_web_paper_result_challenge.py`
- Modify: `lemely/db/review_repo.py` (`ReviewItemDetail` at `:312-338`; `get_item`, where `has_source_box` is computed, around `:583-593`)
- Modify: `lemely/web/schemas_review.py` (`ReviewItemDetailDTO`, after `hasSourceBox` at `:205`)
- Modify: `lemely/web/routers/review.py` (`_detail_to_dto` at `:186-230`)
- Modify: `lemely/web/schemas_parent.py:257-263` (`SubjectPaperDTO`) and `lemely/web/routers/parent.py:486-491`
- Modify: `tests/test_web_parent.py` (one test)

**Interfaces:**
- Produces: `ReviewItemDetail.challenge_reason: str | None` and `ReviewItemDetailDTO.challengeReason: str | None` (L5 renders it); `SubjectPaperDTO.attemptId: str | None` (L11 links rows with it, Task 15 routes it).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_web_paper_result_challenge.py
"""``POST /api/attempts/{a}/questions/{q}/challenge`` (lane L7) and what the teacher sees."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa

from lemely.db.class_repo import ClassService
from lemely.db.models import ParentChildLink
from lemely.db.models.enums import Role
from lemely.db.models.ops import ReviewQueueItem
from tests import test_web_paper_result as _routes

client = _routes.client
pg_sessionmaker = _routes.pg_sessionmaker
storage = _routes.storage
_as = _routes._as
seed_scanned_attempt = _routes.seed_scanned_attempt
qr_id = _routes.qr_id
_seed_user = _routes._seed_user
_question = _routes._question

if TYPE_CHECKING:
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session, sessionmaker

    from tests.storage_fakes import FakeStorageBackend


def _setup(
    sm: sessionmaker[Session], storage: FakeStorageBackend, *, in_class: bool = True, **q: object
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
    """Returns (student, teacher, attempt, question)."""
    student = _seed_user(sm, Role.student)
    teacher = _seed_user(sm, Role.teacher, display_name="Ms. Hanna")
    if in_class:
        classes = ClassService(sm)
        cls = classes.create_class(teacher, "10B")
        assert cls.join_code is not None
        classes.join_by_code(student, cls.join_code)
    defaults: dict[str, object] = {"awarded": 1, "maximum": 4, "confidence_score": 0.82, "needs_review": False}
    defaults.update(q)
    attempt = seed_scanned_attempt(sm, storage, student, [_question("1", **defaults)])  # type: ignore[arg-type]
    return student, teacher, attempt, qr_id(sm, attempt)


def _path(attempt: uuid.UUID, question: uuid.UUID) -> str:
    return f"/api/attempts/{attempt}/questions/{question}/challenge"


GOOD = "I wrote g/cm³ under the answer line, it is on the page."


def test_a_challenge_is_created_and_the_teacher_sees_the_reason(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], storage: FakeStorageBackend
) -> None:
    student, teacher, attempt, question = _setup(pg_sessionmaker, storage)
    _as(client, student, Role.student)
    resp = client.post(_path(attempt, question), json={"reason": GOOD, "comparedWithScheme": True})
    assert resp.status_code == 201
    body = resp.json()
    assert body["challengesUsed"] == 1
    assert body["questions"][0]["challenge"]["state"] == "open"
    assert body["questions"][0]["challengeBlock"] == "already_sent"

    with pg_sessionmaker() as session:
        item_id = session.scalars(
            sa.select(ReviewQueueItem.id).where(ReviewQueueItem.attempt_id == attempt)
        ).one()
    _as(client, teacher, Role.teacher)
    detail = client.get(f"/api/teacher/review/{item_id}")
    assert detail.status_code == 200
    assert detail.json()["reason"] == "student_challenge"
    assert detail.json()["challengeReason"] == GOOD


@pytest.mark.parametrize(
    ("payload", "status"),
    [
        ({"reason": "x" * 39, "comparedWithScheme": True}, 422),
        ({"reason": "x" * 40, "comparedWithScheme": False}, 422),
        ({"reason": "x" * 40 + "\x00", "comparedWithScheme": True}, 422),
        ({"reason": "x" * 1001, "comparedWithScheme": True}, 422),
        ({"reason": "x" * 40, "comparedWithScheme": True}, 201),
    ],
)
def test_confident_mark_needs_forty_characters_and_the_tick(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    storage: FakeStorageBackend,
    payload: dict[str, object],
    status: int,
) -> None:
    student, _, attempt, question = _setup(pg_sessionmaker, storage)
    _as(client, student, Role.student)
    assert client.post(_path(attempt, question), json=payload).status_code == status


def test_low_confidence_mark_needs_twenty_and_no_tick(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], storage: FakeStorageBackend
) -> None:
    student, _, attempt, question = _setup(pg_sessionmaker, storage, confidence_score=0.55)
    _as(client, student, Role.student)
    assert client.post(_path(attempt, question), json={"reason": "x" * 19}).status_code == 422
    assert client.post(_path(attempt, question), json={"reason": "x" * 20}).status_code == 201


def test_refusals_are_409_with_a_code(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], storage: FakeStorageBackend
) -> None:
    student, _, attempt, question = _setup(pg_sessionmaker, storage)
    _as(client, student, Role.student)
    payload = {"reason": GOOD, "comparedWithScheme": True}
    assert client.post(_path(attempt, question), json=payload).status_code == 201
    again = client.post(_path(attempt, question), json=payload)
    assert again.status_code == 409
    assert again.json()["detail"] == {
        "code": "already_sent",
        "message": "You already challenged this mark.",
    }


def test_no_class_is_no_reviewer(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], storage: FakeStorageBackend
) -> None:
    student, _, attempt, question = _setup(pg_sessionmaker, storage, in_class=False)
    _as(client, student, Role.student)
    resp = client.post(_path(attempt, question), json={"reason": GOOD, "comparedWithScheme": True})
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "no_reviewer"


def test_who_may_challenge(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], storage: FakeStorageBackend
) -> None:
    student, teacher, attempt, question = _setup(pg_sessionmaker, storage)
    parent = _seed_user(pg_sessionmaker, Role.parent)
    other = _seed_user(pg_sessionmaker, Role.student)
    with pg_sessionmaker.begin() as session:
        session.add(ParentChildLink(parent_id=parent, child_id=student))
    payload = {"reason": GOOD, "comparedWithScheme": True}
    for caller, role, status in [
        (parent, Role.parent, 403),
        (teacher, Role.teacher, 403),
        (other, Role.student, 404),
    ]:
        _as(client, caller, role)
        assert client.post(_path(attempt, question), json=payload).status_code == status
    _as(client, student, Role.student)
    assert client.post(f"/api/attempts/not-a-uuid/questions/{question}/challenge", json=payload).status_code == 404
```

Append to `tests/test_web_parent.py` (it already has `client`, `pg_sessionmaker`, `history_store`, `_seed_user`, `_link`, `_paper` and `_auth_as`):

```python
def test_subject_papers_carry_the_attempt_id_for_the_result_link(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    history_store: HistoryStore,
) -> None:
    parent = _seed_user(pg_sessionmaker, Role.parent)
    student = _seed_user(pg_sessionmaker, Role.student)
    _link(pg_sessionmaker, parent_id=parent, child_id=student)
    attempt_id = str(uuid.uuid4())
    history_store.append(str(student), _paper(student_id=student).model_copy(update={"attempt_id": attempt_id}))
    _auth_as(client, parent, Role.parent)
    papers = client.get(f"/api/parent/children/{student}/subjects/0625").json()["papers"]
    assert papers[0]["attemptId"] == attempt_id
```

- [ ] **Step 2: Run them to verify they fail**

Run: `PYTHONPATH=$PWD pytest tests/test_web_paper_result_challenge.py tests/test_web_parent.py -k "challenge or reviewer or who_may or attempt_id or confident or low_confidence or refusals" -v`
Expected: FAIL. `challengeReason` and `attemptId` are missing (KeyError). The route tests pass already if Task 5 is in.

- [ ] **Step 3: Expose the reason to the teacher**

In `lemely/db/review_repo.py`:
- Add `from lemely.db.models.challenges import MarkChallenge` to the model imports.
- In `@dataclass class ReviewItemDetail`, after `has_source_box: bool = False`, add:

```python
    challenge_reason: str | None = None
    """The student's written reason when this row is a ``student_challenge`` (lane L7)."""
```

- In `get_item`, right after the `has_source_box = (...)` assignment (still inside the `with` block), add:

```python
            # Lane L7: a student challenge carries the student's own reason. Read
            # while the session is open, next to the other per-item reads.
            challenge_reason = session.scalar(
                select(MarkChallenge.reason).where(MarkChallenge.review_queue_id == item.id)
            )
```

(Use the name `_find_any_item` binds the review row to in that method. It is `item` in `get_item_crop_source`; check `get_item` and match it.)
- In the `return ReviewItemDetail(...)` call, add `challenge_reason=challenge_reason,` after `has_source_box=has_source_box,`.

In `lemely/web/schemas_review.py`, after `hasSourceBox: bool = False` and its docstring, add:

```python
    challengeReason: str | None = None
    """The student's reason, for a ``student_challenge`` row only (lane L7). Plain text."""
```

In `lemely/web/routers/review.py` `_detail_to_dto`, add `challengeReason=detail.challenge_reason,` after `hasSourceBox=detail.has_source_box,`.

- [ ] **Step 4: Add `attemptId` to the parent paper rows**

In `lemely/web/schemas_parent.py` `SubjectPaperDTO`, after `recordedAt: str`:

```python
    attemptId: str | None = None
    """``attempts.id`` for a relationally stored paper, the address of the read-only
    result (``/api/attempts/{id}/result``, lane L7). ``None`` for a file-store record."""
```

In `lemely/web/routers/parent.py`, in the `SubjectPaperDTO(...)` constructor, add `attemptId=r.attempt_id,` after `recordedAt=r.recorded_at,`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD pytest tests/test_web_paper_result_challenge.py tests/test_web_parent.py tests/test_web_review.py -v`
Expected: PASS. `test_web_review.py` is touched source (`review_repo.py`, `review.py`), so it runs in full.

- [ ] **Step 6: Commit**

```bash
pre-commit run --files tests/test_web_paper_result_challenge.py lemely/db/review_repo.py lemely/web/schemas_review.py lemely/web/routers/review.py lemely/web/schemas_parent.py lemely/web/routers/parent.py tests/test_web_parent.py
git commit -S -m "feat(web): teacher sees a challenge reason; parent papers carry attempt ids" -- tests/test_web_paper_result_challenge.py lemely/db/review_repo.py lemely/web/schemas_review.py lemely/web/routers/review.py lemely/web/schemas_parent.py lemely/web/routers/parent.py tests/test_web_parent.py
```

### Task 7: E2E seed fixture for S1

**Files:**
- Modify: `scripts/seed_e2e.py`: a new `s1_report()` after `self_review_report()` (around `:1361`), a seed block after the self-review block (around `:2708`), and an `"s1"` entry in the returned `students` dict (around `:3095`)
- Modify: `web/e2e/seed.ts`: `SeedStudent.s1AttemptId?`, `students.s1`
- Modify: `web/e2e/seed-contract.spec.ts`: the new keys

**Interfaces:**
- Produces: `seed.students.s1` (a `SeedStudent` with `s1AttemptId`). Its own teacher and class, never the roster class, so no existing spec's counts move. The paper (subject `0625`, paper 3/1) has three questions:
  - "1": 2/2 at 0.97
  - "2": 1/3 at 0.55, with scheme points, `needs_teacher_review=False`. Shows the scheme wording, no confirm step, and "Mark it yourself".
  - "3": 1/4 at 0.82, no points. Takes the confirm step, a 40-character reason and the tick.

- [ ] **Step 1: Add the report builder**

```python
# scripts/seed_e2e.py, after self_review_report()
S1_HIGH_CONFIDENCE_SCORE = 0.82


def s1_report() -> AccuracyReport:
    """A 4/9 paper for ``paper-result-s1.spec.ts`` (lane L7).

    "1" full marks; "2" a low-confidence loss with scheme points (scheme wording,
    no confirm step); "3" a confident loss without points (confirm step, 40
    characters and the tick). No question opens a review row, so nothing here
    reaches any teacher's queue until the spec sends its own challenge.
    """
    base = self_review_report()
    one, two = base.correction.questions
    questions = [
        one,
        two.model_copy(update={"needs_teacher_review": False, "review_reason": None}),
        CorrectedQuestion(
            question_id="3",
            awarded_marks=1,
            maximum_marks=4,
            confidence=ConfidenceBand.MEDIUM,
            confidence_score=S1_HIGH_CONFIDENCE_SCORE,
            needs_teacher_review=False,
            student_answer="rho = m / V = 54 / 20 = 2.7",
            expected_answer="2.7 g/cm3",
            topic="Density and units",
            marker_source="ai",
            feedback="Unit missing in the final answer",
            matched_point_ids=[],
        ),
    ]
    correction = base.correction.model_copy(update={"questions": questions})
    return AccuracyReport(
        correction=correction,
        weaknesses=summarize_weaknesses(correction),
        grade_prediction=GradePrediction(
            awarded_marks=4,
            maximum_marks=9,
            percentage=44.44,
            grade="D",
            confidence=ConfidenceBand.LOW,
            needs_teacher_review=False,
            boundary_source="subject_default",
        ),
    )
```

- [ ] **Step 2: Seed the account inside `seed()`**

After the `self_review_attempt_id = attempt_repo.persist_correction(...)` call:

```python
    # Lane L7 (S1 result). Its own teacher and class, so no roster count an
    # existing spec asserts can move, and the challenge the spec sends lands in a
    # queue no other spec reads.
    s1_student = _signup_account("s1", Role.student, run_tag)
    s1_teacher = _signup_account("s1-teacher", Role.teacher, run_tag)
    s1_uuid = uuid.UUID(s1_student["userId"])
    student_profile_service.mark_onboarding_complete(s1_uuid)
    s1_class_row = class_service.create_class(
        uuid.UUID(s1_teacher["userId"]), f"L7 S1 Class {run_tag}", subject_code=SUBJECT_CODE
    )
    assert s1_class_row.join_code is not None  # noqa: S101 - always generated, see create_class
    class_service.join_by_code(s1_uuid, s1_class_row.join_code)
    _log("Persisting the S1 student's three-question paper")
    s1_attempt_id = attempt_repo.persist_correction(
        user_id=s1_student["userId"],
        report=s1_report(),
        recorded_at=corrected_recorded_at(now).isoformat(),
        mark_scheme=self_review_scheme(),
    )
```

In the returned `students` dict, after the `"selfReview"` entry:

```python
        "s1": {
            **s1_student,
            "expectedAtRiskReasons": [],
            "s1AttemptId": str(s1_attempt_id),
        },
```

- [ ] **Step 3: Type and pin the new keys**

In `web/e2e/seed.ts`, add to `SeedStudent`:

```ts
  /** Only present on `students.s1`: the S1 result paper's `attempts.id` (lane L7). */
  s1AttemptId?: string
```

and inside `students: { ... }` after `selfReview`:

```ts
    /** Lane L7: three questions (full, low-confidence loss, confident loss), own class and teacher. */
    s1: SeedStudent
```

In `web/e2e/seed-contract.spec.ts`, add `...account("students.s1"),` after `...account("students.selfReview"),`, and beside the `selfReviewAttemptId` assertion:

```ts
  expect(typeof resolve(seed, "students.s1.s1AttemptId")).toBe("string")
  expect(resolve(seed, "students.s1.expectedAtRiskReasons")).toEqual([])
```

- [ ] **Step 4: Run the seed contract**

Run (needs the local stack the e2e suite uses): `cd web && npx playwright test e2e/seed-contract.spec.ts --project=chromium`
Expected: PASS. Without a stack, run `PYTHONPATH=$PWD python -c "import scripts.seed_e2e as s; r = s.s1_report(); assert r.correction.awarded_marks == 4 and r.correction.maximum_marks == 9"`. Expected: no output.

- [ ] **Step 5: Commit**

```bash
pre-commit run --files scripts/seed_e2e.py web/e2e/seed.ts web/e2e/seed-contract.spec.ts
git commit -S -m "test(e2e): seed an S1 result student with a class teacher" -- scripts/seed_e2e.py web/e2e/seed.ts web/e2e/seed-contract.spec.ts
```

---

## Frontend data layer

### Task 8: Types, API functions and query hooks

**Files:**
- Create: `web/src/lib/paperResultTypes.ts`, `web/src/lib/paperResultApi.ts`, `web/src/lib/hooks/usePaperResultApi.ts`
- Test: `web/tests/unit/paperResultApi.test.ts`

**Interfaces:**
- Consumes: `request`, `fetchBlobUrl`, `ApiError` (`web/src/lib/api.ts`).
- Produces:
  - Types `PaperResult`, `ResultQuestion`, `ResultChallenge`, `ResultReviewer`, `ChallengeBlock`, `ChallengeState`, `ResultViewer`, `ChallengeInput`, `ChallengeRefusal`
  - `paperResultPath(attemptId)`, `answerCropPath(attemptId, questionResultId)`, `getPaperResult(attemptId)`, `sendChallenge(input)`, `challengeRefusal(err): ChallengeRefusal | null`
  - `paperResultKey(attemptId)`, `paperResultQuery(attemptId)`, `usePaperResult(attemptId)`, `useSendChallenge()`, `useAnswerCrop(attemptId, questionResultId, enabled)`, `answerCropUrlFor(key, fetched)`

- [ ] **Step 1: Write the failing test**

```ts
// web/tests/unit/paperResultApi.test.ts
import { afterEach, describe, expect, it, vi } from "vitest"

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>()
  return { ...actual, request: vi.fn() }
})

import { ApiError, request } from "@/lib/api"
import {
  answerCropPath,
  challengeRefusal,
  getPaperResult,
  paperResultPath,
  sendChallenge,
} from "@/lib/paperResultApi"
import { answerCropUrlFor, paperResultKey, paperResultQuery } from "@/lib/hooks/usePaperResultApi"

const requestMock = vi.mocked(request)

afterEach(() => {
  requestMock.mockReset()
})

describe("paths", () => {
  it("encodes both ids", () => {
    expect(paperResultPath("a/b")).toBe("/attempts/a%2Fb/result")
    expect(answerCropPath("a", "q 1")).toBe("/attempts/a/questions/q%201/crop")
  })
})

describe("getPaperResult", () => {
  it("reads the attempt result route", async () => {
    requestMock.mockResolvedValueOnce({ attemptId: "a1" })
    await expect(getPaperResult("a1")).resolves.toEqual({ attemptId: "a1" })
    expect(requestMock).toHaveBeenCalledWith("/attempts/a1/result")
  })
})

describe("sendChallenge", () => {
  it("posts the reason and the tick as JSON", async () => {
    requestMock.mockResolvedValueOnce({ attemptId: "a1" })
    await sendChallenge({
      attemptId: "a1",
      questionResultId: "q1",
      reason: "I wrote the unit on the next line",
      comparedWithScheme: true,
    })
    expect(requestMock).toHaveBeenCalledWith("/attempts/a1/questions/q1/challenge", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason: "I wrote the unit on the next line", comparedWithScheme: true }),
    })
  })
})

describe("challengeRefusal", () => {
  it("reads a 409 refusal body", () => {
    const err = new ApiError(409, "409 Conflict", { code: "limit", message: "You have used all 3 challenges on this paper." })
    expect(challengeRefusal(err)).toEqual({ code: "limit", message: "You have used all 3 challenges on this paper." })
  })

  it("ignores anything else", () => {
    expect(challengeRefusal(new ApiError(422, "422", "Write at least 40 characters."))).toBeNull()
    expect(challengeRefusal(new ApiError(409, "409", { code: "mystery", message: "x" }))).toBeNull()
    expect(challengeRefusal(new Error("boom"))).toBeNull()
  })
})

describe("query options", () => {
  it("keys by attempt and stays disabled without one", () => {
    expect(paperResultKey("a1")).toEqual(["attempts", "a1", "result"])
    expect(paperResultQuery("a1").enabled).toBe(true)
    expect(paperResultQuery(null).enabled).toBe(false)
    expect(paperResultQuery(undefined).queryKey).toEqual(["attempts", "", "result"])
  })
})

describe("answerCropUrlFor", () => {
  it("only returns a URL fetched for the current answer", () => {
    expect(answerCropUrlFor("a:q1", { key: "a:q1", url: "blob:1" })).toBe("blob:1")
    expect(answerCropUrlFor("a:q2", { key: "a:q1", url: "blob:1" })).toBeNull()
    expect(answerCropUrlFor("a:q1", null)).toBeNull()
  })
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd web && npx vitest run tests/unit/paperResultApi.test.ts`
Expected: FAIL. `Failed to resolve import "@/lib/paperResultApi"`.

- [ ] **Step 3: Write the types**

```ts
// web/src/lib/paperResultTypes.ts
/*
 * Wire types for `/api/attempts/...` (lane L7), mirroring
 * `lemely/web/schemas_paper_result.py`. No field carries an integrity flag,
 * a raw review reason or a per-point verdict, by construction on the server.
 */

export type ResultViewer = "student" | "parent"
export type ChallengeState = "open" | "kept" | "changed"
export type ChallengeBlock = "already_sent" | "no_loss" | "pending_teacher" | "limit" | "no_reviewer"

export const CHALLENGE_BLOCKS: readonly ChallengeBlock[] = [
  "already_sent",
  "no_loss",
  "pending_teacher",
  "limit",
  "no_reviewer",
]

export interface ResultChallenge {
  state: ChallengeState
  sentAt: string
}

export interface ResultReviewer {
  teacherName: string
  className: string
}

export interface ResultQuestion {
  questionResultId: string
  questionId: string
  topic: string | null
  awardedMarks: number
  maxMarks: number
  lostMarks: number
  /** 0..1, the marker's confidence in this mark. */
  confidence: number
  feedback: string | null
  /** Scheme wording, present only on a low-confidence loss. */
  schemeText: string | null
  hasCrop: boolean
  markerScored: boolean
  pendingTeacher: boolean
  selfReviewable: boolean
  challenge: ResultChallenge | null
  canChallenge: boolean
  challengeBlock: ChallengeBlock | null
  confirmChallenge: boolean
  minReasonChars: number
  needsSchemeTick: boolean
}

export interface PaperResult {
  attemptId: string
  viewer: ResultViewer
  subjectCode: string | null
  subjectName: string | null
  paperNumber: number | null
  paperVariant: number | null
  sessionLabel: string | null
  awardedMarks: number
  maxMarks: number
  percentage: number
  grade: string | null
  boundaryEstimated: boolean
  nextGrade: string | null
  marksToNextGrade: number | null
  deltaVsLast: number | null
  isFirstPaper: boolean
  recordedAt: string
  questions: ResultQuestion[]
  challengeLimit: number
  challengesUsed: number
  reviewer: ResultReviewer | null
}

export interface ChallengeInput {
  attemptId: string
  questionResultId: string
  reason: string
  comparedWithScheme: boolean
}

export interface ChallengeRefusal {
  code: ChallengeBlock
  message: string
}
```

- [ ] **Step 4: Write the API module**

```ts
// web/src/lib/paperResultApi.ts
import { ApiError, request } from "@/lib/api"
import {
  CHALLENGE_BLOCKS,
  type ChallengeInput,
  type ChallengeRefusal,
  type PaperResult,
} from "@/lib/paperResultTypes"

/* Lane L7 (S1 result). One function per route in `lemely/web/routers/paper_result.py`. */

const enc = encodeURIComponent

export const paperResultPath = (attemptId: string): string => `/attempts/${enc(attemptId)}/result`

export const answerCropPath = (attemptId: string, questionResultId: string): string =>
  `/attempts/${enc(attemptId)}/questions/${enc(questionResultId)}/crop`

export function getPaperResult(attemptId: string): Promise<PaperResult> {
  return request<PaperResult>(paperResultPath(attemptId))
}

export function sendChallenge(input: ChallengeInput): Promise<PaperResult> {
  return request<PaperResult>(
    `/attempts/${enc(input.attemptId)}/questions/${enc(input.questionResultId)}/challenge`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason: input.reason, comparedWithScheme: input.comparedWithScheme }),
    },
  )
}

function isRefusal(value: unknown): value is ChallengeRefusal {
  if (!value || typeof value !== "object") return false
  const v = value as Record<string, unknown>
  return (
    typeof v.message === "string" &&
    typeof v.code === "string" &&
    (CHALLENGE_BLOCKS as readonly string[]).includes(v.code)
  )
}

/** The server's 409 refusal, or `null` for any other failure. */
export function challengeRefusal(err: unknown): ChallengeRefusal | null {
  return err instanceof ApiError && err.status === 409 && isRefusal(err.detail) ? err.detail : null
}
```

- [ ] **Step 5: Write the hooks**

```ts
// web/src/lib/hooks/usePaperResultApi.ts
import { useEffect, useState } from "react"
import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query"
import { fetchBlobUrl } from "@/lib/api"
import { answerCropPath, getPaperResult, sendChallenge } from "@/lib/paperResultApi"
import type { ChallengeInput, PaperResult } from "@/lib/paperResultTypes"

/* L7 query keys: `["attempts", attemptId, "result"]`. */
export const paperResultKey = (attemptId: string) => ["attempts", attemptId, "result"] as const

export function paperResultQuery(attemptId: string | null | undefined) {
  return {
    queryKey: paperResultKey(attemptId ?? ""),
    queryFn: () => getPaperResult(attemptId ?? ""),
    enabled: !!attemptId,
  }
}

export function usePaperResult(
  attemptId: string | null | undefined,
): UseQueryResult<PaperResult, Error> {
  return useQuery(paperResultQuery(attemptId))
}

/** Sends one challenge. The response is the fresh result, written straight into the cache. */
export function useSendChallenge(): UseMutationResult<PaperResult, Error, ChallengeInput> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: sendChallenge,
    onSuccess: (data) => {
      queryClient.setQueryData(paperResultKey(data.attemptId), data)
    },
  })
}

export interface FetchedAnswerCrop {
  key: string
  url: string
}

/** A fetched URL is valid only for the answer it was fetched for (the C1 rule of `cropUrlFor`). */
export function answerCropUrlFor(key: string, fetched: FetchedAnswerCrop | null): string | null {
  return fetched !== null && fetched.key === key ? fetched.url : null
}

export interface AnswerCrop {
  url: string | null
  onDecodeError: () => void
}

/**
 * The answer's crop as an object URL (`<img src>` cannot send the bearer token).
 * Any failure (404 absent, 422 unrenderable, network, decode) resolves to `null`,
 * which the row renders as absence, never as a broken image.
 * Same lifecycle as `useReviewItemCrop` in `useTeacherApi.ts`.
 */
export function useAnswerCrop(
  attemptId: string,
  questionResultId: string,
  enabled: boolean,
): AnswerCrop {
  const key = `${attemptId}:${questionResultId}`
  const [fetched, setFetched] = useState<FetchedAnswerCrop | null>(null)

  useEffect(() => {
    setFetched(null)
    if (!enabled || !attemptId || !questionResultId) return
    let cancelled = false
    let objectUrl: string | null = null
    fetchBlobUrl(answerCropPath(attemptId, questionResultId))
      .then((url) => {
        if (cancelled) {
          URL.revokeObjectURL(url)
          return
        }
        objectUrl = url
        setFetched({ key, url })
      })
      .catch(() => {
        if (!cancelled) setFetched(null)
      })
    return () => {
      cancelled = true
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [attemptId, questionResultId, enabled, key])

  return { url: answerCropUrlFor(key, fetched), onDecodeError: () => setFetched(null) }
}
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `cd web && npx vitest run tests/unit/paperResultApi.test.ts`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
pre-commit run --files web/src/lib/paperResultTypes.ts web/src/lib/paperResultApi.ts web/src/lib/hooks/usePaperResultApi.ts web/tests/unit/paperResultApi.test.ts
git commit -S -m "feat(web): paper result API, query hooks and crop hook" -- web/src/lib/paperResultTypes.ts web/src/lib/paperResultApi.ts web/src/lib/hooks/usePaperResultApi.ts web/tests/unit/paperResultApi.test.ts
```

### Task 9: The view model, `resultModel.ts`

**Files:**
- Create: `web/src/portals/student/screens/result/resultModel.ts`
- Test: `web/tests/unit/resultModel.test.ts`

**Interfaces:**
- Consumes: `PaperResult`, `ResultQuestion` (Task 8); `BinnyMood` (F1 contract, `@/components/redesign`).
- Produces (screens import only these, with no decisions in the JSX):
  - `SHOWN_ROWS = 6`
  - `gradeTier(grade): GradeTier`, `binnyMoodFor(grade): BinnyMood`, `heroLine(r): string`, `deltaLabel(delta): string | null`
  - `subjectTitle(r): string`, `paperMeta(r): string`, `scoreAriaLabel(r): string`, `gradeAriaLabel(grade): string`
  - `lostTotal(r): number`, `resultLayout(r): ResultLayout`
  - `questionLabel(id): string`, `topicFamily(topic): string | null`, `whyLine(q): string`, `practiceHref(subjectCode, topic): string | null`
  - `winRows(r): WinRow[]`, `visibleRows(rows, expanded): { shown: WinRow[]; hasMore: boolean }`
  - `nextStep(r, rows): NextStep | null`
  - `challengesLeft(r): number`, `sheetSubtitle(r): string`, `confirmCopy(row, r): { title: string; body: string }`
  - `reasonCounter(length, min): string`, `canSend(length, min, needsTick, ticked): boolean`
  - `firstPaperChip`, `fullMarksChip`, `BOUNDARY_ESTIMATED_LINE`
  - types `GradeTier`, `ResultLayout`, `RowAction`, `WinRow`, `NextStep`

- [ ] **Step 1: Write the failing test**

```ts
// web/tests/unit/resultModel.test.ts
import { describe, expect, it } from "vitest"
import type { PaperResult, ResultQuestion } from "@/lib/paperResultTypes"
import {
  binnyMoodFor,
  canSend,
  challengesLeft,
  confirmCopy,
  deltaLabel,
  gradeAriaLabel,
  gradeTier,
  heroLine,
  lostTotal,
  nextStep,
  paperMeta,
  practiceHref,
  questionLabel,
  reasonCounter,
  resultLayout,
  scoreAriaLabel,
  sheetSubtitle,
  subjectTitle,
  topicFamily,
  visibleRows,
  whyLine,
  winRows,
} from "@/portals/student/screens/result/resultModel"

function q(over: Partial<ResultQuestion> = {}): ResultQuestion {
  return {
    questionResultId: "qr-" + (over.questionId ?? "1"),
    questionId: "1",
    topic: "Algebra · simultaneous equations",
    awardedMarks: 2,
    maxMarks: 5,
    lostMarks: 3,
    confidence: 0.64,
    feedback: "Sign error in the constant",
    schemeText: "A1 needs the constant −4",
    hasCrop: true,
    markerScored: true,
    pendingTeacher: false,
    selfReviewable: false,
    challenge: null,
    canChallenge: true,
    challengeBlock: null,
    confirmChallenge: false,
    minReasonChars: 20,
    needsSchemeTick: false,
    ...over,
  }
}

function r(over: Partial<PaperResult> = {}): PaperResult {
  return {
    attemptId: "a1",
    viewer: "student",
    subjectCode: "0580",
    subjectName: "Mathematics",
    paperNumber: 4,
    paperVariant: 2,
    sessionLabel: "May/Jun 2025",
    awardedMarks: 61,
    maxMarks: 80,
    percentage: 76,
    grade: "B",
    boundaryEstimated: false,
    nextGrade: "A",
    marksToNextGrade: 4,
    deltaVsLast: 4,
    isFirstPaper: false,
    recordedAt: "2026-11-15T10:00:00Z",
    questions: [
      q({ questionId: "8", topic: "Density and units", lostMarks: 3, confidence: 0.58, feedback: "Unit missing in the final answer" }),
      q({ questionId: "4(b)", lostMarks: 3, confidence: 0.64 }),
      q({ questionId: "7", topic: "Geometry · area", lostMarks: 3, confidence: 0.82, schemeText: null, confirmChallenge: true, minReasonChars: 40, needsSchemeTick: true }),
      q({ questionId: "1", lostMarks: 0, awardedMarks: 3, maxMarks: 3, canChallenge: false, challengeBlock: "no_loss" }),
    ],
    challengeLimit: 3,
    challengesUsed: 0,
    reviewer: { teacherName: "Ms. Hanna", className: "10B" },
    ...over,
  }
}

describe("grade copy and Binny", () => {
  it("maps grades to tiers and moods", () => {
    expect(["A*", "A", "B", "C", "D", "E", "U", null].map(gradeTier)).toEqual(["a", "a", "b", "c", "d", "d", "d", "d"])
    expect(["A*", "A", "B", "C", "D", "U"].map(binnyMoodFor)).toEqual(["happy", "happy", "wink", "open", "sad", "sad"])
  })

  it("writes the mock's lines and uses the real gap", () => {
    expect(heroLine(r())).toBe("Solid B. 4 marks to an A.")
    expect(heroLine(r({ grade: "B", marksToNextGrade: 1 }))).toBe("Solid B. 1 mark to an A.")
    expect(heroLine(r({ grade: "B", marksToNextGrade: null }))).toBe("Solid B.")
    expect(heroLine(r({ grade: "A", nextGrade: "A*", marksToNextGrade: 3 }))).toBe("An A! 3 marks from an A*.")
    expect(heroLine(r({ grade: "A*", nextGrade: null }))).toBe("An A*. Your examiner would be proud. Probably.")
    expect(heroLine(r({ grade: "C" }))).toBe("A C, and a clear route up.")
    expect(heroLine(r({ grade: "D" }))).toBe("Tough one. Here is exactly where the marks are.")
    expect(heroLine(r({ grade: "U" }))).toBe("Not this time. Every lost mark shows you what to practise.")
    expect(heroLine(r({ grade: null }))).toBe("Here is where the marks are.")
  })

  it("labels the delta with a real minus sign", () => {
    expect(deltaLabel(4)).toBe("+4 vs last paper")
    expect(deltaLabel(-3)).toBe("−3 vs last paper")
    expect(deltaLabel(0)).toBe("Same as last paper")
    expect(deltaLabel(null)).toBeNull()
  })
})

describe("identity and accessible labels", () => {
  it("builds the title and the meta line from what is known", () => {
    expect(subjectTitle(r())).toBe("Mathematics")
    expect(subjectTitle(r({ subjectName: null }))).toBe("0580")
    expect(subjectTitle(r({ subjectName: null, subjectCode: null }))).toBe("Your paper")
    expect(paperMeta(r())).toBe("0580/42 · Paper 4 · May/Jun 2025")
    expect(paperMeta(r({ sessionLabel: null, paperVariant: null }))).toBe("Paper 4")
  })

  it("keeps the labels the e2e suite reads", () => {
    expect(scoreAriaLabel(r())).toBe("61 out of 80 marks, 76 percent")
    expect(gradeAriaLabel("B")).toBe("Predicted grade B")
  })
})

describe("layout", () => {
  it("picks one layout, most specific first", () => {
    expect(resultLayout(r())).toBe("full")
    expect(resultLayout(r({ isFirstPaper: true }))).toBe("first_paper")
    expect(resultLayout(r({ awardedMarks: 80, isFirstPaper: true }))).toBe("full_marks")
    expect(resultLayout(r({ questions: [] }))).toBe("no_detail")
    expect(lostTotal(r())).toBe(19)
  })
})

describe("rows", () => {
  it("lists losses only, biggest first, least sure first on a tie", () => {
    expect(winRows(r()).map((row) => row.questionId)).toEqual(["8", "4(b)", "7"])
  })

  it("labels questions, topics and reasons", () => {
    expect(questionLabel("8")).toBe("Q8")
    expect(questionLabel("Q2(b)")).toBe("Q2(b)")
    expect(topicFamily("Algebra · simultaneous equations")).toBe("Algebra")
    expect(topicFamily(null)).toBeNull()
    expect(whyLine(q({ feedback: null, markerScored: false }))).toBe("Not marked")
    expect(whyLine(q({ feedback: null }))).toBe("Marks lost here")
    expect(practiceHref("0580", "Geometry · area")).toBe("/student/practice/0580?topic=Geometry%20%C2%B7%20area")
    expect(practiceHref(null, "x")).toBeNull()
  })

  it("shows scheme wording only when the server sent it", () => {
    const [eight, , seven] = winRows(r())
    expect(eight.showScheme).toBe(true)
    expect(seven.showScheme).toBe(false)
  })

  it("turns the server's challenge state into one action", () => {
    const rows = (over: Partial<ResultQuestion>) => winRows(r({ questions: [q(over)] }))[0].action
    expect(rows({})).toEqual({ kind: "challenge", confirm: false, minChars: 20, needsTick: false })
    expect(rows({ canChallenge: false, challengeBlock: "already_sent", challenge: { state: "open", sentAt: "x" } })).toEqual({ kind: "sent" })
    expect(rows({ canChallenge: false, challengeBlock: "already_sent", challenge: { state: "kept", sentAt: "x" } })).toEqual({ kind: "kept" })
    expect(rows({ canChallenge: false, challengeBlock: "already_sent", challenge: { state: "changed", sentAt: "x" } })).toEqual({ kind: "changed" })
    expect(rows({ canChallenge: false, challengeBlock: "pending_teacher", pendingTeacher: true })).toEqual({ kind: "teacher_checking" })
    expect(rows({ canChallenge: false, challengeBlock: "limit" })).toEqual({ kind: "no_challenges_left" })
    expect(rows({ canChallenge: false, challengeBlock: "no_reviewer" })).toEqual({ kind: "join_class" })
    expect(winRows(r({ viewer: "parent", questions: [q({ canChallenge: false })] }))[0].action).toEqual({ kind: "none" })
  })

  it("folds after six rows", () => {
    const many = r({ questions: Array.from({ length: 8 }, (_, i) => q({ questionId: String(i + 1) })) })
    const rows = winRows(many)
    expect(visibleRows(rows, false)).toEqual({ shown: rows.slice(0, 6), hasMore: true })
    expect(visibleRows(rows, true)).toEqual({ shown: rows, hasMore: false })
  })
})

describe("next step", () => {
  it("names the top two answers, their topics and the share of lost marks", () => {
    const step = nextStep(r(), winRows(r()))
    expect(step).toEqual({
      headline: "Win back Q8 and Q4(b) with a 10-minute density and units and algebra set.",
      body: "Those two answers hold 6 of your 19 lost marks.",
      primary: { label: "Practise density and units", href: "/student/practice/0580?topic=Density%20and%20units" },
      studyPlanHref: "/student/plan/0580",
      scanHref: "/student/correct",
    })
  })

  it("says full marks when the two answers are everything", () => {
    const small = r({ awardedMarks: 74, questions: [q({ questionId: "8", lostMarks: 3 }), q({ questionId: "4", lostMarks: 3 })] })
    expect(nextStep(small, winRows(small))?.body).toBe("Win those two back for full marks.")
  })

  it("speaks of one answer when there is one", () => {
    const one = r({ awardedMarks: 77, questions: [q({ questionId: "8", topic: null, lostMarks: 3 })] })
    expect(nextStep(one, winRows(one))).toMatchObject({
      headline: "Win back Q8 with a 5-minute set.",
      body: "Win that one back for full marks.",
      primary: { label: "Practise these" },
    })
  })

  it("is absent without losses", () => {
    expect(nextStep(r({ awardedMarks: 80 }), [])).toBeNull()
  })
})

describe("challenge copy and the send gate", () => {
  it("names the teacher and what is left", () => {
    expect(challengesLeft(r({ challengesUsed: 1 }))).toBe(2)
    expect(sheetSubtitle(r({ challengesUsed: 1 }))).toBe("Goes to Ms. Hanna (10B). 2 of 3 challenges left on this paper.")
    expect(sheetSubtitle(r({ reviewer: null }))).toBe("3 of 3 challenges left on this paper.")
  })

  it("confirms with the marker's confidence", () => {
    const row = winRows(r())[2]
    expect(confirmCopy(row, r())).toEqual({
      title: "Sure about Q7?",
      body: "Lemely was 82% sure on this one. You get 3 challenges per paper.",
    })
  })

  it("counts toward the minimum and gates on the tick", () => {
    expect(reasonCounter(12, 40)).toBe("12/40 min")
    expect(reasonCounter(55, 40)).toBe("40/40 min")
    expect(canSend(39, 40, false, false)).toBe(false)
    expect(canSend(40, 40, true, false)).toBe(false)
    expect(canSend(40, 40, true, true)).toBe(true)
    expect(canSend(20, 20, false, false)).toBe(true)
  })
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd web && npx vitest run tests/unit/resultModel.test.ts`
Expected: FAIL. `Failed to resolve import "@/portals/student/screens/result/resultModel"`.

- [ ] **Step 3: Write the implementation**

```ts
// web/src/portals/student/screens/result/resultModel.ts
import type { BinnyMood } from "@/components/redesign"
import type { PaperResult, ResultQuestion } from "@/lib/paperResultTypes"

/*
 * The S1 view model (lane L7). Every decision the result screen makes lives
 * here: which layout, which copy, which Binny mood, which action a row offers.
 * Components render what this returns and decide nothing. The server decides the
 * 0.70 confidence line; this module only reads its per-question verdict.
 */

export const SHOWN_ROWS = 6
export const BOUNDARY_ESTIMATED_LINE = "Grade estimated from past boundaries."
export const firstPaperChip = "Your first paper"
export const fullMarksChip = "Full marks"

export type GradeTier = "a" | "b" | "c" | "d"
export type ResultLayout = "full" | "first_paper" | "full_marks" | "no_detail"

export type RowAction =
  | { kind: "challenge"; confirm: boolean; minChars: number; needsTick: boolean }
  | { kind: "sent" }
  | { kind: "kept" }
  | { kind: "changed" }
  | { kind: "teacher_checking" }
  | { kind: "no_challenges_left" }
  | { kind: "join_class" }
  | { kind: "none" }

export interface WinRow {
  id: string
  questionId: string
  title: string
  why: string
  lost: number
  confidence: number
  schemeText: string | null
  showScheme: boolean
  hasCrop: boolean
  topic: string | null
  practiceLabel: string | null
  practiceHref: string | null
  selfReviewable: boolean
  action: RowAction
}

export interface NextStep {
  headline: string
  body: string
  primary: { label: string; href: string | null }
  studyPlanHref: string | null
  scanHref: string
}

export function gradeTier(grade: string | null): GradeTier {
  if (grade === "A*" || grade === "A") return "a"
  if (grade === "B") return "b"
  if (grade === "C") return "c"
  return "d"
}

export function binnyMoodFor(grade: string | null): BinnyMood {
  return ({ a: "happy", b: "wink", c: "open", d: "sad" } as const)[gradeTier(grade)]
}

const marks = (n: number) => (n === 1 ? "mark" : "marks")

export function heroLine(r: PaperResult): string {
  const n = r.marksToNextGrade
  const gap = n !== null && n > 0 && r.nextGrade ? n : null
  switch (r.grade) {
    case "A*":
      return "An A*. Your examiner would be proud. Probably."
    case "A":
      return gap !== null ? `An A! ${gap} ${marks(gap)} from an ${r.nextGrade}.` : "An A!"
    case "B":
      return gap !== null ? `Solid B. ${gap} ${marks(gap)} to an ${r.nextGrade}.` : "Solid B."
    case "C":
      return "A C, and a clear route up."
    case "U":
      return "Not this time. Every lost mark shows you what to practise."
    case null:
    case "":
      return "Here is where the marks are."
    default:
      return "Tough one. Here is exactly where the marks are."
  }
}

export function deltaLabel(delta: number | null): string | null {
  if (delta === null) return null
  if (delta === 0) return "Same as last paper"
  return delta > 0 ? `+${delta} vs last paper` : `−${Math.abs(delta)} vs last paper`
}

export function subjectTitle(r: PaperResult): string {
  return r.subjectName ?? r.subjectCode ?? "Your paper"
}

export function paperMeta(r: PaperResult): string {
  const parts: string[] = []
  if (r.subjectCode && r.paperNumber !== null && r.paperVariant !== null) {
    parts.push(`${r.subjectCode}/${r.paperNumber}${r.paperVariant}`)
  }
  if (r.paperNumber !== null) parts.push(`Paper ${r.paperNumber}`)
  if (r.sessionLabel) parts.push(r.sessionLabel)
  return parts.join(" · ")
}

export function scoreAriaLabel(r: PaperResult): string {
  return `${r.awardedMarks} out of ${r.maxMarks} marks, ${r.percentage} percent`
}

export function gradeAriaLabel(grade: string): string {
  return `Predicted grade ${grade}`
}

export function lostTotal(r: PaperResult): number {
  return Math.max(r.maxMarks - r.awardedMarks, 0)
}

export function resultLayout(r: PaperResult): ResultLayout {
  if (r.questions.length === 0) return "no_detail"
  if (lostTotal(r) === 0) return "full_marks"
  if (r.isFirstPaper) return "first_paper"
  return "full"
}

export function questionLabel(id: string): string {
  return /^q/i.test(id) ? id : `Q${id}`
}

export function topicFamily(topic: string | null): string | null {
  if (!topic) return null
  return topic.split(" · ")[0].trim() || null
}

export function whyLine(q: ResultQuestion): string {
  if (q.feedback) return q.feedback
  return q.markerScored ? "Marks lost here" : "Not marked"
}

export function practiceHref(subjectCode: string | null, topic: string | null): string | null {
  if (!subjectCode || !topic) return null
  return `/student/practice/${subjectCode}?topic=${encodeURIComponent(topic)}`
}

function actionFor(q: ResultQuestion, r: PaperResult): RowAction {
  if (r.viewer !== "student") return { kind: "none" }
  if (q.canChallenge) {
    return { kind: "challenge", confirm: q.confirmChallenge, minChars: q.minReasonChars, needsTick: q.needsSchemeTick }
  }
  if (q.challenge) return { kind: q.challenge.state === "open" ? "sent" : q.challenge.state }
  switch (q.challengeBlock) {
    case "pending_teacher":
      return { kind: "teacher_checking" }
    case "limit":
      return { kind: "no_challenges_left" }
    case "no_reviewer":
      return { kind: "join_class" }
    default:
      return { kind: "none" }
  }
}

export function winRows(r: PaperResult): WinRow[] {
  return r.questions
    .map((q, order) => ({ q, order }))
    .filter(({ q }) => q.lostMarks > 0)
    .sort((a, b) => b.q.lostMarks - a.q.lostMarks || a.q.confidence - b.q.confidence || a.order - b.order)
    .map(({ q }) => {
      const family = topicFamily(q.topic)
      return {
        id: q.questionResultId,
        questionId: questionLabel(q.questionId),
        title: q.topic ? `${questionLabel(q.questionId)} · ${q.topic}` : questionLabel(q.questionId),
        why: whyLine(q),
        lost: q.lostMarks,
        confidence: q.confidence,
        schemeText: q.schemeText,
        showScheme: q.schemeText !== null,
        hasCrop: q.hasCrop,
        topic: q.topic,
        practiceLabel: family ? `Practise ${family}` : null,
        practiceHref: r.viewer === "student" ? practiceHref(r.subjectCode, q.topic) : null,
        selfReviewable: q.selfReviewable,
        action: actionFor(q, r),
      }
    })
}

export function visibleRows(rows: WinRow[], expanded: boolean): { shown: WinRow[]; hasMore: boolean } {
  if (expanded || rows.length <= SHOWN_ROWS) return { shown: rows, hasMore: false }
  return { shown: rows.slice(0, SHOWN_ROWS), hasMore: true }
}

const joinAnd = (items: string[]) => items.join(" and ")

export function nextStep(r: PaperResult, rows: WinRow[]): NextStep | null {
  if (rows.length === 0) return null
  const top = rows.slice(0, 2)
  const families = [
    ...new Set(top.map((row) => topicFamily(row.topic)?.toLowerCase()).filter((f): f is string => !!f)),
  ]
  const minutes = 5 * top.length
  const what = families.length > 0 ? `${joinAnd(families)} set` : "set"
  const held = top.reduce((sum, row) => sum + row.lost, 0)
  const total = lostTotal(r)
  const one = top.length === 1
  const body =
    held >= total
      ? one
        ? "Win that one back for full marks."
        : "Win those two back for full marks."
      : one
        ? `That answer holds ${held} of your ${total} lost marks.`
        : `Those two answers hold ${held} of your ${total} lost marks.`
  return {
    headline: `Win back ${joinAnd(top.map((row) => row.questionId))} with a ${minutes}-minute ${what}.`,
    body,
    primary: {
      label: families[0] ? `Practise ${families[0]}` : "Practise these",
      href: practiceHref(r.subjectCode, top[0].topic) ?? (r.subjectCode ? `/student/practice/${r.subjectCode}` : null),
    },
    studyPlanHref: r.subjectCode ? `/student/plan/${r.subjectCode}` : null,
    scanHref: "/student/correct",
  }
}

export function challengesLeft(r: PaperResult): number {
  return Math.max(r.challengeLimit - r.challengesUsed, 0)
}

export function sheetSubtitle(r: PaperResult): string {
  const left = `${challengesLeft(r)} of ${r.challengeLimit} challenges left on this paper.`
  return r.reviewer ? `Goes to ${r.reviewer.teacherName} (${r.reviewer.className}). ${left}` : left
}

export function confirmCopy(row: WinRow, r: PaperResult): { title: string; body: string } {
  return {
    title: `Sure about ${row.questionId}?`,
    body: `Lemely was ${Math.round(row.confidence * 100)}% sure on this one. You get ${r.challengeLimit} challenges per paper.`,
  }
}

export function reasonCounter(length: number, min: number): string {
  return `${Math.min(length, min)}/${min} min`
}

export function canSend(length: number, min: number, needsTick: boolean, ticked: boolean): boolean {
  return length >= min && (!needsTick || ticked)
}
```

Note: the test expects `"density and units and algebra"` for the mock's first two rows. That is the literal rule (unique families of the top two, lower-cased, joined with "and"). The mock's hand-written "algebra and units" can't come from data. This wording is listed in "Needs user decision" item 8.

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd web && npx vitest run tests/unit/resultModel.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
pre-commit run --files web/src/portals/student/screens/result/resultModel.ts web/tests/unit/resultModel.test.ts
git commit -S -m "feat(web): S1 result view model" -- web/src/portals/student/screens/result/resultModel.ts web/tests/unit/resultModel.test.ts
```

### Task 10: Reveal choreography and the "seen" store, `revealChoreography.ts`

**Files:**
- Create: `web/src/portals/student/screens/result/revealChoreography.ts`
- Test: `web/tests/unit/revealChoreography.test.ts`

**Interfaces:**
- Consumes: `GradeTier` (Task 9).
- Produces:
  - `HOLD_MS = 900`, `COUNT_MS = 1100`, `HOP_EASING`, `TIMINGS`, `BINNY_BOX = { width: 120, height: 132 }`
  - `holdProgress(elapsedMs)`, `holdHint(p)`, `heartbeatSeconds(p)`, `scrambleIntervalMs(p)`, `shouldShake(p, reduced)`, `suspenseOpacity(p)`, `countValue(to, t)`
  - `freeZone(input)`, `restPoint(zone, trackWidth)`, `hopPlan(tier, rest, trackWidth)`, `hopKeyframes(from, to, height)`, `clampHop(height, from, to, zoneTop)`
  - `shouldReveal({ justMarked, seen })`
  - `hasRevealed(attemptId, store?)`, `markRevealed(attemptId, store?)`, `REVEALED_KEY`, `RevealStore`

- [ ] **Step 1: Write the failing test**

```ts
// web/tests/unit/revealChoreography.test.ts
import { describe, expect, it } from "vitest"
import {
  clampHop,
  countValue,
  freeZone,
  hasRevealed,
  heartbeatSeconds,
  holdHint,
  holdProgress,
  hopKeyframes,
  hopPlan,
  markRevealed,
  restPoint,
  scrambleIntervalMs,
  shouldReveal,
  shouldShake,
  suspenseOpacity,
  REVEALED_KEY,
  type RevealStore,
} from "@/portals/student/screens/result/revealChoreography"

function memoryStore(): RevealStore & { data: Map<string, string> } {
  const data = new Map<string, string>()
  return {
    data,
    getItem: (k) => data.get(k) ?? null,
    setItem: (k, v) => void data.set(k, v),
  }
}

describe("hold", () => {
  it("fills over 900ms and clamps", () => {
    expect(holdProgress(0)).toBe(0)
    expect(holdProgress(450)).toBeCloseTo(0.5)
    expect(holdProgress(2000)).toBe(1)
  })

  it("matches the mock's hint thresholds", () => {
    expect([0, 0.03, 0.61, 0.86].map(holdHint)).toEqual(["Hold to reveal", "Keep holding", "Almost…", "Here it comes"])
  })

  it("speeds the heartbeat and the scramble as tension rises", () => {
    expect(heartbeatSeconds(0)).toBe("1.40s")
    expect(heartbeatSeconds(1)).toBe("0.45s")
    expect(scrambleIntervalMs(0)).toBe(150)
    expect(scrambleIntervalMs(1)).toBe(40)
    expect(suspenseOpacity(0)).toEqual({ digits: 0.35, grade: 0.5 })
    expect(suspenseOpacity(1)).toEqual({ digits: 1, grade: 1 })
  })

  it("shakes past 60% unless motion is reduced", () => {
    expect(shouldShake(0.6, false)).toBe(false)
    expect(shouldShake(0.61, false)).toBe(true)
    expect(shouldShake(0.9, true)).toBe(false)
  })

  it("counts up with an ease-out cubic", () => {
    expect(countValue(61, 0)).toBe(0)
    expect(countValue(61, 0.5)).toBe(53)
    expect(countValue(61, 1)).toBe(61)
  })
})

describe("flight", () => {
  const zone = freeZone({ stackBottom: 400, viewportHeight: 844, safeBottom: 0 })

  it("keeps Binny below the result stack and above the bottom edge", () => {
    expect(zone).toEqual({ top: 444, bottom: 704 })
    expect(restPoint(zone, 270)).toEqual({ x: 135, y: 684 })
  })

  it("plans the mock's hops per tier", () => {
    const rest = restPoint(zone, 270)
    expect(hopPlan("a", rest, 270).map((h) => [h.x, h.y, h.duration, h.height])).toEqual([
      [14, 684, 640, 170],
      [256, 654, 640, 170],
      [20, 684, 640, 170],
      [250, 624, 640, 170],
      [135, 684, 640, 170],
      [135, 684, 600, 90],
    ])
    expect(hopPlan("b", rest, 270).map((h) => [h.x, h.duration, h.height, h.pauseAfter])).toEqual([
      [70, 720, 100, 120],
      [200, 720, 100, 120],
      [135, 600, 90, 0],
    ])
    expect(hopPlan("d", rest, 270).map((h) => [h.x, h.duration, h.height])).toEqual([
      [135, 1000, 70],
      [135, 600, 90],
    ])
  })

  it("never peaks above the zone top", () => {
    expect(clampHop(170, { x: 0, y: 500 }, { x: 0, y: 480 }, 444)).toBe(36)
    expect(clampHop(170, { x: 0, y: 900 }, { x: 0, y: 700 }, 444)).toBe(170)
    expect(clampHop(170, { x: 0, y: 400 }, { x: 0, y: 450 }, 444)).toBe(0)
  })

  it("squashes and stretches with the mock's offsets", () => {
    const frames = hopKeyframes({ x: 0, y: 700 }, { x: 180, y: 700 }, 100)
    expect(frames.map((f) => f.offset)).toEqual([0, 0.12, 0.5, 0.9, 1])
    expect(frames[2].transform).toBe("translate(90px, 600px) scale(.94, 1.1) rotate(10deg)")
    expect(frames[4].transform).toBe("translate(180px, 700px) scale(1)")
  })
})

describe("when the reveal plays", () => {
  it("plays straight off marking or on the first open", () => {
    expect(shouldReveal({ justMarked: true, seen: true })).toBe(true)
    expect(shouldReveal({ justMarked: false, seen: false })).toBe(true)
    expect(shouldReveal({ justMarked: false, seen: true })).toBe(false)
  })

  it("remembers revealed attempts, capped and fault tolerant", () => {
    const store = memoryStore()
    expect(hasRevealed("a1", store)).toBe(false)
    markRevealed("a1", store)
    expect(hasRevealed("a1", store)).toBe(true)
    for (let i = 0; i < 60; i += 1) markRevealed(`x${i}`, store)
    expect(JSON.parse(store.data.get(REVEALED_KEY) ?? "[]")).toHaveLength(50)
    store.data.set(REVEALED_KEY, "{not json")
    expect(hasRevealed("a1", store)).toBe(false)
    const throwing: RevealStore = {
      getItem: () => {
        throw new Error("blocked")
      },
      setItem: () => {
        throw new Error("blocked")
      },
    }
    expect(hasRevealed("a1", throwing)).toBe(true)
    expect(() => markRevealed("a1", throwing)).not.toThrow()
  })
})
```

`hasRevealed` returns `true` when storage throws (private mode, blocked site data). Then a blocked store never replays the reveal on every visit, and the reveal still plays on the live path.

- [ ] **Step 2: Run it to verify it fails**

Run: `cd web && npx vitest run tests/unit/revealChoreography.test.ts`
Expected: FAIL. `Failed to resolve import ".../revealChoreography"`.

- [ ] **Step 3: Write the implementation**

```ts
// web/src/portals/student/screens/result/revealChoreography.ts
import type { GradeTier } from "./resultModel"

/*
 * Every number the S1 reveal moves by, copied from the approved mock
 * (`.impeccable/mocks/student-r1/reveal.js`, `student.js`, `s1.css`). Pure, so the
 * motion is testable in Vitest's node environment; the components only feed it
 * time and geometry.
 */

export const HOLD_MS = 900
export const COUNT_MS = 1100
export const HOP_EASING = "cubic-bezier(.3,.6,.3,1)"
export const BINNY_BOX = { width: 120, height: 132 } as const

export const TIMINGS = {
  firstHopDelay: 900,
  fadeOut: 320,
  overlayOut: 420,
} as const

export interface Point {
  x: number
  y: number
}

export interface Zone {
  top: number
  bottom: number
}

export interface Hop extends Point {
  duration: number
  height: number
  pauseAfter: number
}

export function holdProgress(elapsedMs: number): number {
  return Math.min(Math.max(elapsedMs / HOLD_MS, 0), 1)
}

export function holdHint(p: number): string {
  if (p > 0.85) return "Here it comes"
  if (p > 0.6) return "Almost…"
  if (p > 0.02) return "Keep holding"
  return "Hold to reveal"
}

export function heartbeatSeconds(p: number): string {
  return `${(1.4 - p * 0.95).toFixed(2)}s`
}

export function scrambleIntervalMs(p: number): number {
  return 150 - p * 110
}

export function shouldShake(p: number, reduced: boolean): boolean {
  return !reduced && p > 0.6
}

export function suspenseOpacity(p: number): { digits: number; grade: number } {
  return { digits: +(0.35 + p * 0.65).toFixed(2), grade: +(0.5 + p * 0.5).toFixed(2) }
}

export function countValue(to: number, t: number): number {
  const clamped = Math.min(Math.max(t, 0), 1)
  return Math.round(to * (1 - Math.pow(1 - clamped, 3)))
}

/** The space below "See my result" that Binny may use. It never overlaps the result stack. */
export function freeZone(input: { stackBottom: number; viewportHeight: number; safeBottom: number }): Zone {
  return { top: input.stackBottom + 44, bottom: input.viewportHeight - BINNY_BOX.height - 8 - input.safeBottom }
}

export function restPoint(zone: Zone, trackWidth: number): Point {
  return { x: Math.round(0.5 * trackWidth), y: Math.min(Math.max(zone.top + 30, zone.bottom - 20), zone.bottom) }
}

/** `trackWidth` is the stage width minus Binny's width; fractions come from the 390px mock (track 270). */
const PLANS: Record<GradeTier, { fractions: [number, number][]; duration: number; height: number; pause: number }> = {
  a: {
    fractions: [
      [14 / 270, 0],
      [256 / 270, -30],
      [20 / 270, 0],
      [250 / 270, -60],
      [0.5, 0],
    ],
    duration: 640,
    height: 170,
    pause: 0,
  },
  b: {
    fractions: [
      [70 / 270, 0],
      [200 / 270, 0],
    ],
    duration: 720,
    height: 100,
    pause: 120,
  },
  c: { fractions: [[0.5, 0]], duration: 1000, height: 70, pause: 0 },
  d: { fractions: [[0.5, 0]], duration: 1000, height: 70, pause: 0 },
}

export function hopPlan(tier: GradeTier, rest: Point, trackWidth: number): Hop[] {
  const plan = PLANS[tier]
  const hops: Hop[] = plan.fractions.map(([fx, dy]) => ({
    x: Math.round(fx * trackWidth),
    y: rest.y + dy,
    duration: plan.duration,
    height: plan.height,
    pauseAfter: plan.pause,
  }))
  hops.push({ x: rest.x, y: rest.y, duration: 600, height: 90, pauseAfter: 0 })
  return hops
}

export function clampHop(height: number, from: Point, to: Point, zoneTop: number): number {
  return Math.max(0, Math.min(height, Math.min(from.y, to.y) - zoneTop))
}

export function hopKeyframes(from: Point, to: Point, height: number): Keyframe[] {
  const mx = (from.x + to.x) / 2
  const my = Math.min(from.y, to.y) - height
  const r = (to.x - from.x) / 18
  return [
    { offset: 0, transform: `translate(${from.x}px, ${from.y}px) scale(1.14, .84)` },
    { offset: 0.12, transform: `translate(${from.x}px, ${from.y}px) scale(.92, 1.12)` },
    { offset: 0.5, transform: `translate(${mx}px, ${my}px) scale(.94, 1.1) rotate(${r}deg)` },
    { offset: 0.9, transform: `translate(${to.x}px, ${to.y}px) scale(1.16, .82)` },
    { offset: 1, transform: `translate(${to.x}px, ${to.y}px) scale(1)` },
  ]
}

export function shouldReveal(input: { justMarked: boolean; seen: boolean }): boolean {
  return input.justMarked || !input.seen
}

export const REVEALED_KEY = "lemely.s1.revealed.v1"
const REVEALED_CAP = 50

export interface RevealStore {
  getItem(key: string): string | null
  setItem(key: string, value: string): void
}

function defaultStore(): RevealStore | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage
  } catch {
    return null
  }
}

function readIds(store: RevealStore): string[] {
  const raw = store.getItem(REVEALED_KEY)
  if (!raw) return []
  try {
    const parsed: unknown = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed.filter((v): v is string => typeof v === "string") : []
  } catch {
    return []
  }
}

/** True when this device already revealed the attempt. True when storage is unusable (see the test). */
export function hasRevealed(attemptId: string, store: RevealStore | null = defaultStore()): boolean {
  if (!store) return true
  try {
    return readIds(store).includes(attemptId)
  } catch {
    return true
  }
}

export function markRevealed(attemptId: string, store: RevealStore | null = defaultStore()): void {
  if (!store) return
  try {
    const ids = readIds(store).filter((id) => id !== attemptId)
    ids.push(attemptId)
    store.setItem(REVEALED_KEY, JSON.stringify(ids.slice(-REVEALED_CAP)))
  } catch {
    // A blocked store costs only a replay; never break the screen over it.
  }
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd web && npx vitest run tests/unit/revealChoreography.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
pre-commit run --files web/src/portals/student/screens/result/revealChoreography.ts web/tests/unit/revealChoreography.test.ts
git commit -S -m "feat(web): S1 reveal choreography values and seen store" -- web/src/portals/student/screens/result/revealChoreography.ts web/tests/unit/revealChoreography.test.ts
```

---

## Screen tasks (agent: `designer`)

Before any UI edit, the designer invokes the `impeccable` skill, reads `.claude/skills/impeccable/reference/craft-floor.md` and the three taste memories, and opens `.impeccable/mocks/student-r1/s1.html` in a browser at 390px beside the work. Components take props from the view model and decide nothing. Vitest has no DOM here, so behaviour is proven by the view-model tests (Tasks 9, 10), the source gates (Task 16) and the Playwright spec (Task 17). Each screen task ends with `npm run typecheck`, `npm run lint` and `npm run check:copy` (from `web/`), plus its own commit.

Token mapping used throughout (mock variable to app class):

| Mock | App |
|---|---|
| `--p` #042f4f | `primary` (`bg-primary`, `text-primary`) |
| `--pc` | `primary-container` |
| `--s` | `surface` |
| `--l` #fff | `surface-container-lowest` |
| `--sl` | `surface-container-low` |
| `--sc` | `surface-container` |
| `--sh` | `surface-container-high` |
| `--ink` | `on-surface` |
| `--v` | `on-surface-variant` |
| `--o` | `outline` |
| `--ov` | `outline-variant` |
| `--ok` / `--okc` | `success-text` / `success-container` |
| `--err` | `error` |
| `--gold` | `tertiary` |
| `--night` | `inverse-surface` (light theme); `surface` under `[data-theme=dark]` (in `result.css`) |
| `--tide` | `inverse-primary` (light theme); `primary` under `[data-theme=dark]` |
| hero lab `oklch(.77 .015 240)` | `text-inverse-on-surface/70` |
| hero line `oklch(.95 .006 240)` | `text-inverse-on-surface` |
| `.nx p` `oklch(.3 .02 240)` | `text-on-surface/80` |
| grade colours (`G[...]`.c) | `--grade-a-star`, `--grade-a`, `--grade-b`, `--grade-c`, `--grade-d`, `--grade-u` (exact matches) |
| 'Schibsted Grotesk' / 'Bricolage Grotesque' / 'JetBrains Mono' | `font-sans` / `font-display` / `font-mono` |
| `h1` 800 21px | `text-display-sm font-extrabold` |
| `h2.sec` 800 24px | `result.css .s1-sec` |
| `.nx h3` 800 22px | `result.css .s1-nx-title` |
| `.score` 800 88px, `.res .sc` 96px, `.susp` 96px, `.gq b` 52px, `.gchip` 36px | `result.css` classes `.s1-score`, `.s1-res-score`, `.s1-susp`, `.s1-gq`, `.s1-gchip` |
| `.lab` 600 11px mono caps | `text-label-sm uppercase` |
| `.win b` 600 20px mono | `font-mono text-[20px]` is banned in parent and components. Use `result.css .s1-win` |
| radius 32 / 24 / 20 / 18 / 14 | `rounded-[32px]` and the like are banned in `components/` and parent. Every radius lives in `result.css` |

### Task 11: Title row, hero, next-step card, state notes and page states

**Files:**
- Create: `web/src/portals/student/screens/result/ResultTitleRow.tsx`, `ResultHero.tsx`, `NextStepCard.tsx`, `FirstPaperNote.tsx`, `FullMarksNote.tsx`, `NoDetailNote.tsx`, `ResultStates.tsx`
- Create: `web/src/portals/student/screens/result/result.css` (first part. Tasks 12 and 13 append to it)

**Interfaces:**
- Consumes: Task 9 functions; `Binny` (F1); `Button`, `Chip`, `EmptyState`, `SkeletonBlock` from `@/components/ui/*`; `studentLoadFailureMessage`.
- Produces:
  - `ResultTitleRow({ title, meta, onShare? })`
  - `ResultHero({ result, variant: "dark" | "light", chip?: { label; tone: "info" | "ok" } })`
  - `NextStepCard({ step, binnyMood, binnyPop, showBinny, onPractise, onPlan, onScan })`
  - `FirstPaperNote({ onScan })`
  - `FullMarksNote({ onScan, onShare?, showBinny })`
  - `NoDetailNote()`
  - `ResultSkeleton()`, `ResultError({ error, onRetry, onBack })`, `ResultNotFound({ onCorrect, onBack })`

- [ ] **Step 1: Write `result.css` (page part)**

```css
/* web/src/portals/student/screens/result/result.css
 * Lane L7, S1 result. Component CSS for what the token classes can't express
 * (the mock's display sizes, radii, keyframes, conic rings). No :root custom
 * properties are declared here. Values copied from .impeccable/mocks/student-r1. */

.s1-title { font: 800 21px/1.2 var(--font-sans); letter-spacing: -0.01em; }
.s1-meta { font: 600 12px var(--font-mono); letter-spacing: 0.02em; }
.s1-sec { font: 800 24px/1.2 var(--font-sans); letter-spacing: -0.02em; text-wrap: balance; }

.s1-hero { border-radius: 32px; padding: 22px 20px; display: grid; gap: 14px; overflow: hidden; }
.s1-hero[data-variant="dark"] { background: var(--color-primary); color: var(--color-on-primary); }
.s1-hero[data-variant="light"] { padding: 4px 0 0; }
.s1-score { font: 800 88px/0.9 var(--font-display); letter-spacing: -0.05em; font-variant-numeric: tabular-nums; }
.s1-score small { font-size: 34px; opacity: 0.7; letter-spacing: -0.03em; }
.s1-hero[data-variant="light"] .s1-score { font-size: 76px; line-height: 1; color: var(--color-primary); }
.s1-hero[data-variant="light"] .s1-score small { font-size: 30px; color: var(--color-on-surface-variant); opacity: 1; }
.s1-gchip { display: inline-block; color: var(--color-white); border-radius: 12px; padding: 2px 14px; font: 800 36px/1.2 var(--font-display); }
.s1-hero[data-variant="light"] .s1-gchip { min-width: 52px; height: 44px; font-size: 26px; padding: 0 10px; display: inline-grid; place-items: center; }
.s1-line { font: 600 16px/1.35 var(--font-sans); max-width: 24ch; text-wrap: balance; }

.s1-nx { border-radius: 24px; padding: 18px; display: grid; gap: 12px; background: var(--color-primary-container); }
.s1-nx-title { font: 800 22px/1.2 var(--font-sans); letter-spacing: -0.01em; color: var(--color-primary); text-wrap: balance; }
.s1-nx-binny { width: 72px; height: 79px; flex: none; }
.s1-nx-more { min-height: 44px; padding: 0 14px; border-radius: 12px; }

.s1-note { display: grid; gap: 6px; padding: 16px; border-radius: 22px; }
.s1-note[data-tone="first"] { background: var(--color-surface-container-lowest); box-shadow: inset 0 0 0 1px var(--color-outline-variant); }
.s1-note[data-tone="full"] { background: var(--color-primary-container); display: flex; gap: 14px; align-items: center; }
.s1-ghostline { width: 100%; height: 60px; }

.s1-skel { border-radius: 14px; animation: s1-skp 1.6s ease-in-out infinite; }
@keyframes s1-skp { 50% { opacity: 0.55; } }
.s1-err { border-radius: 24px; padding: 28px 20px; display: grid; gap: 10px; box-shadow: inset 0 0 0 1px var(--color-outline); background: var(--color-surface-container-lowest); }
.s1-err h2 { font: 800 24px/1.2 var(--font-sans); letter-spacing: -0.02em; }

.s1-rise { opacity: 0; transform: translateY(8px); transition: opacity 0.4s var(--ease-out) 0.15s, transform 0.4s var(--ease-out) 0.15s; }
.s1-rise[data-shown="true"] { opacity: 1; transform: none; }

@media (prefers-reduced-motion: reduce) {
  .s1-skel { animation: none; }
  .s1-rise { transition: none; }
}
```

- [ ] **Step 2: Write the title row and the hero**

```tsx
// web/src/portals/student/screens/result/ResultTitleRow.tsx
import { Export } from "@phosphor-icons/react"

export function ResultTitleRow({ title, meta, onShare }: { title: string; meta: string; onShare?: () => void }) {
  return (
    <div className="flex items-center gap-2.5">
      <div className="grid min-w-0 flex-1 gap-px">
        <h1 className="s1-title truncate text-on-surface">{title}</h1>
        {meta ? <span className="s1-meta truncate text-on-surface-variant">{meta}</span> : null}
      </div>
      {onShare ? (
        <button
          type="button"
          data-print="hide"
          aria-label="Share result"
          onClick={onShare}
          className="grid size-11 place-items-center rounded-2xl bg-surface-container-lowest text-primary shadow-[inset_0_0_0_1px_var(--color-outline)] transition-colors hover:bg-surface-container-low focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
        >
          <Export size={20} weight="bold" aria-hidden />
        </button>
      ) : null}
    </div>
  )
}
```

```tsx
// web/src/portals/student/screens/result/ResultHero.tsx
import type { PaperResult } from "@/lib/paperResultTypes"
import { Chip } from "@/components/ui/chip"
import { BOUNDARY_ESTIMATED_LINE, deltaLabel, gradeAriaLabel, heroLine, scoreAriaLabel } from "./resultModel"

const GRADE_VAR: Record<string, string> = {
  "A*": "var(--grade-a-star)", A: "var(--grade-a)", B: "var(--grade-b)", C: "var(--grade-c)",
  D: "var(--grade-d)", E: "var(--grade-e)", F: "var(--grade-f)", G: "var(--grade-g)", U: "var(--grade-u)",
}

export function gradeColour(grade: string | null): string {
  return (grade && GRADE_VAR[grade]) || "var(--color-outline)"
}

export function ResultHero({
  result,
  variant,
  chip,
}: {
  result: PaperResult
  variant: "dark" | "light"
  chip?: { label: string; tone: "info" | "ok" }
}) {
  const delta = deltaLabel(result.deltaVsLast)
  const dark = variant === "dark"
  return (
    <section className="s1-hero" data-variant={variant} aria-label="Your mark">
      <div>
        <p className="s1-score" aria-label={scoreAriaLabel(result)}>
          {result.awardedMarks}
          <small aria-hidden>/{result.maxMarks}</small>
        </p>
        <div className="mt-2.5 flex items-center gap-3">
          {result.grade ? (
            <span role="img" aria-label={gradeAriaLabel(result.grade)} className="s1-gchip" style={{ background: gradeColour(result.grade) }}>
              <span aria-hidden>{result.grade}</span>
            </span>
          ) : null}
          {chip ? <Chip tone={chip.tone}>{chip.label}</Chip> : null}
          {dark && delta ? <span className="font-mono text-data-md text-inverse-primary">{delta}</span> : null}
        </div>
      </div>
      {dark ? <p className="s1-line text-inverse-on-surface">{heroLine(result)}</p> : null}
      {result.boundaryEstimated ? (
        <p className={dark ? "text-body-sm text-inverse-on-surface/70" : "text-body-sm text-on-surface-variant"}>
          {BOUNDARY_ESTIMATED_LINE}
        </p>
      ) : null}
    </section>
  )
}
```

Note: the `shadow-[inset_...]` utility in `ResultTitleRow` is a colour arbitrary value, not a banned font size or radius literal. If `design-tokens.test.ts` flags it once `portals/student` joins the scan, move it into `result.css` as `.s1-ic`.

- [ ] **Step 3: Write the next-step card and the three notes**

```tsx
// web/src/portals/student/screens/result/NextStepCard.tsx
import { Binny, type BinnyMood } from "@/components/redesign"
import { Button } from "@/components/ui/button"
import type { NextStep } from "./resultModel"

export function NextStepCard({
  step,
  binnyMood,
  binnyPop,
  showBinny,
  onPractise,
  onPlan,
  onScan,
}: {
  step: NextStep
  binnyMood: BinnyMood
  /** True for the frame the overlay hands over: the card Binny pops in. */
  binnyPop: boolean
  /** False while the reveal's flying Binny is still on screen (one Binny at a time). */
  showBinny: boolean
  onPractise: () => void
  onPlan: () => void
  onScan: () => void
}) {
  return (
    <section className="s1-nx" aria-labelledby="s1-next">
      <div className="flex items-end gap-3">
        <h2 id="s1-next" className="s1-nx-title flex-1">{step.headline}</h2>
        <div className="s1-nx-binny" data-pop={binnyPop || undefined}>
          {showBinny ? <Binny mood={binnyMood} motion={binnyPop ? "pop" : "idle"} size={72} aria-hidden /> : null}
        </div>
      </div>
      <p className="text-body-md text-pretty text-on-surface/80">{step.body}</p>
      {step.primary.href ? (
        <div className="flex flex-wrap gap-2">
          <Button variant="primary" data-print="hide" onClick={onPractise}>{step.primary.label}</Button>
        </div>
      ) : null}
      <div className="flex flex-wrap gap-1.5">
        {step.studyPlanHref ? (
          <button type="button" data-print="hide" onClick={onPlan} className="s1-nx-more bg-surface-container-lowest text-label text-primary transition-colors hover:bg-surface-container-low">
            Today’s study session
          </button>
        ) : null}
        <button type="button" data-print="hide" onClick={onScan} className="s1-nx-more bg-surface-container-lowest text-label text-primary transition-colors hover:bg-surface-container-low">
          Mark another paper
        </button>
      </div>
    </section>
  )
}
```

```tsx
// web/src/portals/student/screens/result/FirstPaperNote.tsx
import { Button } from "@/components/ui/button"

/* states-r1 SR1: the starting line. No Binny on this layout (the mock has none). */
export function FirstPaperNote({ onScan }: { onScan: () => void }) {
  return (
    <section className="s1-note" data-tone="first">
      <svg viewBox="0 0 320 70" className="s1-ghostline" aria-hidden>
        <polyline fill="none" stroke="var(--color-outline)" strokeWidth={3} strokeDasharray="7 7" points="20,52 110,44 200,36 300,20" />
        <circle cx={20} cy={52} r={6} fill="var(--color-primary)" />
      </svg>
      <p className="text-display-xs text-primary">This is your starting line.</p>
      <p className="text-body-md text-on-surface-variant">
        Mark your next paper and Lemely shows how you’re moving, and which topics keep costing you marks.
      </p>
      <Button variant="primary" size="sm" className="justify-self-start" data-print="hide" onClick={onScan}>
        Mark another paper
      </Button>
    </section>
  )
}
```

```tsx
// web/src/portals/student/screens/result/FullMarksNote.tsx
import { Binny } from "@/components/redesign"
import { Button } from "@/components/ui/button"

/* states-r1 SR2. The mock's paper-specific tip ("Try a Paper 4 next") is not derivable; see
   "Needs user decision" 8. */
export function FullMarksNote({ onScan, onShare, showBinny }: { onScan: () => void; onShare?: () => void; showBinny: boolean }) {
  return (
    <>
      <section className="s1-note" data-tone="full">
        {showBinny ? <Binny mood="happy" size={56} motion="idle" aria-hidden /> : <span className="size-14 flex-none" aria-hidden />}
        <div>
          <p className="text-display-xs text-primary">Nothing to win back on this one.</p>
          <p className="mt-0.5 text-body-md text-primary/85">Mark another paper to keep it going.</p>
        </div>
      </section>
      <div className="grid gap-2">
        <Button variant="primary" data-print="hide" onClick={onScan}>Mark another paper</Button>
        {onShare ? <Button variant="secondary" data-print="hide" onClick={onShare}>Share result</Button> : null}
      </div>
    </>
  )
}
```

```tsx
// web/src/portals/student/screens/result/NoDetailNote.tsx
/* Keep-list K4/K5: a record with no per-question detail says so plainly. */
export function NoDetailNote() {
  return (
    <section className="s1-note" data-tone="first">
      <p className="text-display-xs text-primary">No per-question detail for this paper</p>
      <p className="text-body-md text-on-surface-variant">Per-question detail is only kept for papers marked in Lemely.</p>
    </section>
  )
}
```

- [ ] **Step 4: Write the page states**

```tsx
// web/src/portals/student/screens/result/ResultStates.tsx
import { Button } from "@/components/ui/button"
import { EmptyState } from "@/components/ui/state-views"
import { studentLoadFailureMessage } from "@/lib/studentOutcome"

/* Mock #skel: hero 250/32, card 210/24, heading 28x60%, two rows 76/20. Desktop adds the right column. */
export function ResultSkeleton() {
  return (
    <div role="status" aria-label="Loading your result" aria-busy="true" className="grid gap-3.5 shell-lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] shell-lg:gap-8">
      <div className="grid content-start gap-3.5">
        <div className="s1-skel h-[250px] rounded-[32px] bg-surface-container-high" />
        <div className="s1-skel h-[210px] rounded-[24px] bg-surface-container-high" />
      </div>
      <div className="grid content-start gap-3.5">
        <div className="s1-skel h-7 w-3/5 bg-surface-container-high" />
        <div className="s1-skel h-[76px] rounded-[20px] bg-surface-container-high" />
        <div className="s1-skel h-[76px] rounded-[20px] bg-surface-container-high" />
      </div>
    </div>
  )
}

export function ResultError({ error, onRetry, onBack }: { error: unknown; onRetry: () => void; onBack: () => void }) {
  return (
    <div role="alert" className="s1-err">
      <h2 className="text-on-surface">Couldn’t load your result.</h2>
      <p className="text-body-md text-on-surface-variant">{studentLoadFailureMessage(error)}</p>
      <div className="flex flex-wrap gap-2">
        <Button variant="primary" onClick={onRetry}>Try again</Button>
        <Button variant="ghost" onClick={onBack}>Back to overview</Button>
      </div>
    </div>
  )
}

export function ResultNotFound({ onCorrect, onBack }: { onCorrect: () => void; onBack: () => void }) {
  return (
    <EmptyState
      heading="No paper recorded at this address"
      body="We don't have a result stored under this link. It may have been removed, or the address may be wrong."
      marginalia="Nothing filed here"
      action={{ label: "Correct a paper", onClick: onCorrect }}
      secondaryAction={{ label: "Back to overview", onClick: onBack }}
    />
  )
}
```

`rounded-[32px]` and the `h-[...]` values here are allowed: `design-tokens.test.ts` doesn't scan `portals/student/screens`. If the polish pass prefers it, move them into `.s1-skel-*` classes in `result.css`.

- [ ] **Step 5: Verify and commit**

Run: `cd web && npm run typecheck && npm run lint && npm run check:copy`
Expected: no errors. The components are not mounted yet. Task 14 mounts them.

```bash
pre-commit run --files web/src/portals/student/screens/result/ResultTitleRow.tsx web/src/portals/student/screens/result/ResultHero.tsx web/src/portals/student/screens/result/NextStepCard.tsx web/src/portals/student/screens/result/FirstPaperNote.tsx web/src/portals/student/screens/result/FullMarksNote.tsx web/src/portals/student/screens/result/NoDetailNote.tsx web/src/portals/student/screens/result/ResultStates.tsx web/src/portals/student/screens/result/result.css
git commit -S -m "feat(web): S1 hero, next-step card, notes and page states" -- web/src/portals/student/screens/result/ResultTitleRow.tsx web/src/portals/student/screens/result/ResultHero.tsx web/src/portals/student/screens/result/NextStepCard.tsx web/src/portals/student/screens/result/FirstPaperNote.tsx web/src/portals/student/screens/result/FullMarksNote.tsx web/src/portals/student/screens/result/NoDetailNote.tsx web/src/portals/student/screens/result/ResultStates.tsx web/src/portals/student/screens/result/result.css
```

### Task 12: "Marks you can win" rows, crop, self-review sheet and the challenge flow

**Files:**
- Create: `web/src/portals/student/screens/result/WinRows.tsx`, `WinRow.tsx`, `AnswerCrop.tsx`, `ChallengeConfirm.tsx`, `ChallengeSheet.tsx`, `SelfReviewSheet.tsx`
- Modify: `web/src/portals/student/screens/result/result.css` (append the rows part)

**Interfaces:**
- Consumes: `WinRow`, `RowAction`, `visibleRows`, `confirmCopy`, `sheetSubtitle`, `reasonCounter`, `canSend`, `lostTotal` (Task 9); `useAnswerCrop`, `useSendChallenge`, `paperResultKey` (Task 8); `challengeRefusal`; `ConfirmModal`, `Sheet*`, `Button`, `Chip`, `useToast`; `SelfReviewPanel` (`portals/student/components/SelfReviewPanel.tsx`, unchanged); `HairRows` (F1).
- Produces: `WinRows({ result, rows, expanded, onExpand })`. It owns the open row, the confirm, the sheet and the self-review sheet.

- [ ] **Step 1: Append the rows CSS**

```css
/* result.css: rows part */
.s1-row { border-bottom: 1px solid var(--color-outline-variant); }
.s1-row[data-open="true"] { background: var(--color-surface-container-low); border-radius: 20px; border-bottom-color: transparent; }
.s1-row-head { display: grid; grid-template-columns: auto 1fr auto; gap: 12px; align-items: center; width: 100%; min-height: 76px; padding: 12px 4px; text-align: start; }
.s1-row[data-open="true"] .s1-row-head { padding-inline: 14px; }
.s1-win { width: 60px; height: 60px; border-radius: 18px; display: grid; place-items: center; align-content: center; background: var(--color-primary-container); color: var(--color-primary); }
.s1-win b { font: 600 20px/1 var(--font-mono); }
.s1-win small { font: 600 11px var(--font-mono); letter-spacing: 0.06em; text-transform: uppercase; }
.s1-row-body { padding: 0 14px 14px; display: grid; gap: 10px; }
.s1-crop { margin-inline: -14px; border-block: 1px solid var(--color-outline-variant); background: var(--color-surface-container-lowest); min-height: 120px; display: grid; place-items: center; }
.s1-crop img { display: block; width: 100%; height: auto; }
.s1-row-actions .s1-btn { min-height: 44px; }
```

- [ ] **Step 2: Write the crop, the confirm and the sheets**

```tsx
// web/src/portals/student/screens/result/AnswerCrop.tsx
import { useAnswerCrop } from "@/lib/hooks/usePaperResultApi"

/* Absence is absence: no crop renders nothing, never a broken image (useAnswerCrop's contract). */
export function AnswerCrop({ attemptId, questionResultId, label }: { attemptId: string; questionResultId: string; label: string }) {
  const crop = useAnswerCrop(attemptId, questionResultId, true)
  if (!crop.url) return null
  return (
    <div className="s1-crop">
      <img src={crop.url} alt={`Your answer to ${label}`} onError={crop.onDecodeError} />
    </div>
  )
}
```

```tsx
// web/src/portals/student/screens/result/ChallengeConfirm.tsx
import { ConfirmModal } from "@/components/ui/confirm-modal"

/* Mock #confirm: friction before challenging a confident mark. Reuses the kit's confirm. */
export function ChallengeConfirm({
  open, title, body, onKeep, onSure,
}: { open: boolean; title: string; body: string; onKeep: () => void; onSure: () => void }) {
  return (
    <ConfirmModal
      open={open}
      title={title}
      consequence={body}
      destructive={false}
      confirmLabel="Yes, challenge"
      cancelLabel="Keep my mark"
      onConfirm={onSure}
      onCancel={onKeep}
    />
  )
}
```

```tsx
// web/src/portals/student/screens/result/ChallengeSheet.tsx
import { useId, useState } from "react"
import { Button } from "@/components/ui/button"
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet"
import { canSend, reasonCounter } from "./resultModel"

export function ChallengeSheet({
  open, title, subtitle, minChars, needsTick, pending, error, onCancel, onSend,
}: {
  open: boolean
  title: string
  subtitle: string
  minChars: number
  needsTick: boolean
  pending: boolean
  error: string | null
  onCancel: () => void
  onSend: (reason: string, ticked: boolean) => void
}) {
  const [reason, setReason] = useState("")
  const [ticked, setTicked] = useState(false)
  const countId = useId()
  const length = reason.trim().length
  const ready = canSend(length, minChars, needsTick, ticked) && !pending
  return (
    <Sheet
      open={open}
      onOpenChange={(next) => {
        if (!next) {
          setReason("")
          setTicked(false)
          onCancel()
        }
      }}
    >
      <SheetContent side="adaptive" showCloseButton={false} nativeBodyClassName="grid gap-3 p-5">
        <SheetTitle className="text-display-sm font-extrabold">{title}</SheetTitle>
        <SheetDescription className="text-body-md text-on-surface-variant">{subtitle}</SheetDescription>
        <textarea
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          autoComplete="off"
          autoFocus
          aria-label="Justification"
          aria-describedby={countId}
          placeholder="Tell your marker why this answer deserves more. Be specific."
          className="min-h-[110px] resize-none rounded-2xl bg-surface-container-lowest p-3 text-body-md caret-primary shadow-[inset_0_0_0_1px_var(--color-outline)] focus-visible:outline-2 focus-visible:outline-primary"
        />
        {needsTick ? (
          <label className="flex items-start gap-2.5 text-body-md text-on-surface">
            <input type="checkbox" checked={ticked} onChange={(e) => setTicked(e.target.checked)} className="mt-px size-5 flex-none accent-primary" />
            <span>I have compared my answer with the mark scheme.</span>
          </label>
        ) : null}
        {error ? <p role="alert" className="text-body-sm text-error">{error}</p> : null}
        <div className="flex gap-2">
          <Button variant="secondary" className="flex-1" onClick={onCancel}>Cancel</Button>
          <Button variant="primary" className="flex-[2]" disabled={!ready} onClick={() => onSend(reason.trim(), ticked)}>
            {pending ? "Sending…" : "Send challenge"}
          </Button>
        </div>
        <span id={countId} aria-live="polite" className="text-label-sm uppercase text-on-surface-variant">
          {reasonCounter(length, minChars)}
        </span>
      </SheetContent>
    </Sheet>
  )
}
```

```tsx
// web/src/portals/student/screens/result/SelfReviewSheet.tsx
import { useQueryClient } from "@tanstack/react-query"
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet"
import { SelfReviewPanel } from "@/portals/student/components/SelfReviewPanel"
import { paperResultKey } from "@/lib/hooks/usePaperResultApi"

/* Keep-list K18: the self-review panel, unchanged, opened from the row. Closing it refreshes the
   result, because a granted self-mark moves the marks. */
export function SelfReviewSheet({
  open, attemptId, questionResultId, title, onClose,
}: { open: boolean; attemptId: string; questionResultId: string; title: string; onClose: () => void }) {
  const queryClient = useQueryClient()
  return (
    <Sheet
      open={open}
      onOpenChange={(next) => {
        if (!next) {
          void queryClient.invalidateQueries({ queryKey: paperResultKey(attemptId) })
          onClose()
        }
      }}
    >
      <SheetContent side="adaptive" nativeBodyClassName="grid gap-3 p-5">
        <SheetTitle className="text-display-sm font-extrabold">{title}</SheetTitle>
        <SelfReviewPanel attemptId={attemptId} questionResultId={questionResultId} />
      </SheetContent>
    </Sheet>
  )
}
```

- [ ] **Step 3: Write the row and the list**

```tsx
// web/src/portals/student/screens/result/WinRow.tsx
import { CaretDown, CaretUp } from "@phosphor-icons/react"
import { Button } from "@/components/ui/button"
import { Chip } from "@/components/ui/chip"
import { AnswerCrop } from "./AnswerCrop"
import type { WinRow as Row } from "./resultModel"

const ACTION_CHIP: Partial<Record<Row["action"]["kind"], { label: string; tone: "ok" | "neutral" | "info" }>> = {
  sent: { label: "Challenge sent", tone: "ok" },
  kept: { label: "Mark kept", tone: "neutral" },
  changed: { label: "Mark changed", tone: "ok" },
  teacher_checking: { label: "Teacher will check this one", tone: "info" },
  no_challenges_left: { label: "No challenges left", tone: "neutral" },
}

export function WinRow({
  row, attemptId, open, onToggle, onChallenge, onPractise, onSelfReview,
}: {
  row: Row
  attemptId: string
  open: boolean
  onToggle: () => void
  onChallenge: (trigger: HTMLButtonElement) => void
  onPractise: () => void
  onSelfReview: () => void
}) {
  const chip = ACTION_CHIP[row.action.kind]
  return (
    <li className="s1-row" data-open={open}>
      <button
        type="button"
        className="s1-row-head focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
        aria-expanded={open}
        data-row-toggle={row.id}
        onClick={onToggle}
      >
        <span className="s1-win">
          <b>+{row.lost}</b>
          <small>to win</small>
        </span>
        <span className="grid min-w-0 gap-px">
          <b className="text-display-xs text-on-surface">{row.title}</b>
          <span className="text-body-sm text-on-surface-variant">{row.why}</span>
        </span>
        <span className="grid size-8 place-items-center text-on-surface-variant" aria-hidden>
          {open ? <CaretUp size={16} weight="bold" /> : <CaretDown size={16} weight="bold" />}
        </span>
      </button>
      {open ? (
        <div className="s1-row-body">
          {row.hasCrop ? <AnswerCrop attemptId={attemptId} questionResultId={row.id} label={row.questionId} /> : null}
          {row.showScheme ? (
            <div>
              <span className="text-label-sm uppercase text-on-surface-variant">Mark scheme</span>
              <p className="mt-0.5 text-body-md text-pretty text-on-surface">{row.schemeText}</p>
            </div>
          ) : null}
          <div className="s1-row-actions flex flex-wrap gap-2">
            {row.action.kind === "challenge" ? (
              <Button variant="secondary" className="s1-btn bg-primary-container text-primary" data-print="hide" onClick={(e) => onChallenge(e.currentTarget)}>
                Challenge this mark
              </Button>
            ) : null}
            {row.action.kind === "join_class" ? (
              <p className="text-body-sm text-on-surface-variant">Join a class so a teacher can check your challenges.</p>
            ) : null}
            {chip ? <Chip tone={chip.tone}>{chip.label}</Chip> : null}
            {row.selfReviewable ? (
              <Button variant="secondary" className="s1-btn" data-print="hide" onClick={onSelfReview}>Mark it yourself</Button>
            ) : null}
            {row.practiceHref && row.practiceLabel ? (
              <Button variant="primary" className="s1-btn" data-print="hide" onClick={onPractise}>{row.practiceLabel}</Button>
            ) : null}
          </div>
        </div>
      ) : null}
    </li>
  )
}
```

```tsx
// web/src/portals/student/screens/result/WinRows.tsx
import { useRef, useState } from "react"
import { useNavigate } from "react-router-dom"
import { HairRows } from "@/components/redesign"
import { Button } from "@/components/ui/button"
import { useToast } from "@/components/ui/toast"
import type { PaperResult } from "@/lib/paperResultTypes"
import { challengeRefusal } from "@/lib/paperResultApi"
import { useSendChallenge } from "@/lib/hooks/usePaperResultApi"
import { ApiError } from "@/lib/api"
import { ChallengeConfirm } from "./ChallengeConfirm"
import { ChallengeSheet } from "./ChallengeSheet"
import { SelfReviewSheet } from "./SelfReviewSheet"
import { WinRow } from "./WinRow"
import { confirmCopy, lostTotal, sheetSubtitle, visibleRows, type WinRow as Row } from "./resultModel"

export function WinRows({
  result, rows, expanded, onExpand,
}: { result: PaperResult; rows: Row[]; expanded: boolean; onExpand: () => void }) {
  const navigate = useNavigate()
  const { toast } = useToast()
  const send = useSendChallenge()
  const trigger = useRef<HTMLButtonElement | null>(null)
  const [openId, setOpenId] = useState<string | null>(null)
  const [confirmFor, setConfirmFor] = useState<Row | null>(null)
  const [sheetFor, setSheetFor] = useState<Row | null>(null)
  const [selfReviewFor, setSelfReviewFor] = useState<Row | null>(null)
  const [sendError, setSendError] = useState<string | null>(null)
  const { shown, hasMore } = visibleRows(rows, expanded)

  function startChallenge(row: Row, button: HTMLButtonElement) {
    trigger.current = button
    if (row.action.kind !== "challenge") return
    if (row.action.confirm) setConfirmFor(row)
    else setSheetFor(row)
  }

  function closeAll(focusRow?: string) {
    setConfirmFor(null)
    setSheetFor(null)
    setSendError(null)
    if (focusRow) document.querySelector<HTMLButtonElement>(`[data-row-toggle="${focusRow}"]`)?.focus()
    else trigger.current?.focus()
  }

  async function submit(row: Row, reason: string, ticked: boolean) {
    setSendError(null)
    try {
      await send.mutateAsync({ attemptId: result.attemptId, questionResultId: row.id, reason, comparedWithScheme: ticked })
      closeAll(row.id)
      toast({ title: result.reviewer ? `Challenge sent. ${result.reviewer.teacherName} will take a look.` : "Challenge sent." })
    } catch (err) {
      const refusal = challengeRefusal(err)
      if (refusal) {
        closeAll()
        toast({ title: refusal.message })
      } else if (err instanceof ApiError && err.status === 422 && typeof err.detail === "string") {
        setSendError(err.detail)
      } else {
        setSendError("Couldn’t send your challenge. Try again.")
      }
    }
  }

  const action = sheetFor?.action.kind === "challenge" ? sheetFor.action : null
  return (
    <section aria-labelledby="s1-win">
      <h2 id="s1-win" className="s1-sec text-on-surface">Marks you can win</h2>
      <p className="mt-0.5 text-body-md text-on-surface-variant">
        <span className="font-mono">{lostTotal(result)}</span> marks to win back. Biggest answers first.
      </p>
      <div className="mt-3">
        <HairRows aria-label="Answers with marks to win">
          {shown.map((row) => (
            <WinRow
              key={row.id}
              row={row}
              attemptId={result.attemptId}
              open={openId === row.id}
              onToggle={() => setOpenId((cur) => (cur === row.id ? null : row.id))}
              onChallenge={(button) => startChallenge(row, button)}
              onPractise={() => row.practiceHref && navigate(row.practiceHref)}
              onSelfReview={() => setSelfReviewFor(row)}
            />
          ))}
        </HairRows>
        {hasMore ? (
          <Button variant="secondary" className="mt-2.5 w-full bg-primary-container text-primary" onClick={onExpand}>
            Show all answers
          </Button>
        ) : null}
      </div>

      {confirmFor ? (
        <ChallengeConfirm
          open
          {...confirmCopy(confirmFor, result)}
          onKeep={() => closeAll()}
          onSure={() => {
            setSheetFor(confirmFor)
            setConfirmFor(null)
          }}
        />
      ) : null}
      {sheetFor && action ? (
        <ChallengeSheet
          open
          title={sheetFor.title}
          subtitle={sheetSubtitle(result)}
          minChars={action.minChars}
          needsTick={action.needsTick}
          pending={send.isPending}
          error={sendError}
          onCancel={() => closeAll()}
          onSend={(reason, ticked) => void submit(sheetFor, reason, ticked)}
        />
      ) : null}
      {selfReviewFor ? (
        <SelfReviewSheet
          open
          attemptId={result.attemptId}
          questionResultId={selfReviewFor.id}
          title={selfReviewFor.title}
          onClose={() => setSelfReviewFor(null)}
        />
      ) : null}
    </section>
  )
}
```

`HairRows` renders a `<ul>` (F1 contract), so `WinRow` renders an `<li>`. If F1's `HairRows` styles its children as `HairRow` only, keep the `<ul>` semantics and apply the `.s1-row` hairline yourself.

- [ ] **Step 4: Verify and commit**

Run: `cd web && npm run typecheck && npm run lint && npm run check:copy`
Expected: no errors.

```bash
pre-commit run --files web/src/portals/student/screens/result/WinRows.tsx web/src/portals/student/screens/result/WinRow.tsx web/src/portals/student/screens/result/AnswerCrop.tsx web/src/portals/student/screens/result/ChallengeConfirm.tsx web/src/portals/student/screens/result/ChallengeSheet.tsx web/src/portals/student/screens/result/SelfReviewSheet.tsx web/src/portals/student/screens/result/result.css
git commit -S -m "feat(web): S1 win rows, crop, self-review and challenge flow" -- web/src/portals/student/screens/result/WinRows.tsx web/src/portals/student/screens/result/WinRow.tsx web/src/portals/student/screens/result/AnswerCrop.tsx web/src/portals/student/screens/result/ChallengeConfirm.tsx web/src/portals/student/screens/result/ChallengeSheet.tsx web/src/portals/student/screens/result/SelfReviewSheet.tsx web/src/portals/student/screens/result/result.css
```

### Task 13: The reveal overlay: hold, suspense, celebration, flight, dock

**Files:**
- Create: `web/src/portals/student/screens/result/HoldButton.tsx`, `RevealFlight.tsx`, `RevealOverlay.tsx`
- Modify: `web/src/portals/student/screens/result/result.css` (append the reveal part)

**Interfaces:**
- Consumes: Task 10 (all of it), `gradeTier`, `binnyMoodFor`, `heroLine`, `subjectTitle`, `paperMeta` (Task 9), `gradeColour` (Task 11), `prefersReducedMotion` (`lib/celebration.ts`), `Binny` (F1).
- Produces: `RevealOverlay({ result, onDocked })`. It renders through a portal on `document.body` and calls `onDocked()` once it has faded out. The root (Task 14) then mounts the card Binny with `binnyPop`.

Phases: `hold` → `celebrate` (progress hit 1) → `ready` (hops done) → `out` ("See my result") → unmounted. The flying Binny and the card Binny are never on screen together.

- [ ] **Step 1: Append the reveal CSS**

```css
/* result.css: reveal part. Night/Tide come from tokens: inverse in light, plain in dark. */
.s1-ov { --s1-night: var(--color-inverse-surface); --s1-tide: var(--color-inverse-primary); position: fixed; inset: 0; z-index: 60; overflow: hidden; }
:root[data-theme="dark"] .s1-ov { --s1-night: var(--color-surface); --s1-tide: var(--color-primary); }
.s1-ovbg { position: absolute; inset: 0; background: var(--color-primary-container); transition: background 0.5s var(--ease-out), opacity 0.5s var(--ease-out); }
.s1-ov[data-phase="hold"] .s1-ovbg { background: var(--s1-night); }
.s1-ov[data-tier="d"]:not([data-phase="hold"]) .s1-ovbg { background: var(--color-surface-container); }
.s1-ov[data-phase="out"] .s1-ovbg, .s1-ov[data-phase="out"] .s1-res { opacity: 0; }
.s1-ov[data-phase="out"] { pointer-events: none; }
.s1-ov[data-flash="true"] { animation: s1-flash 0.6s ease-out; }
@keyframes s1-flash { 0% { filter: brightness(2.2); } 100% { filter: none; } }

.s1-stage { position: absolute; inset: 0; z-index: 2; margin-inline: auto; max-width: 390px; padding: 64px 24px calc(56px + env(safe-area-inset-bottom)); text-align: center; }
.s1-holdui { height: 100%; display: grid; grid-template-rows: auto 1fr auto; justify-items: center; transition: opacity 0.35s; }
.s1-ov:not([data-phase="hold"]) .s1-holdui { opacity: 0; pointer-events: none; }
.s1-ov[data-shake="true"] .s1-stage { animation: s1-shake 0.12s linear infinite; }
@keyframes s1-shake { 25% { transform: translate(1px, -1px); } 75% { transform: translate(-1px, 1px); } }
.s1-subj { display: grid; gap: 10px; justify-items: center; }
.s1-subj h2 { font: 800 32px/1.15 var(--font-sans); letter-spacing: -0.02em; color: var(--color-white); max-width: 14ch; text-wrap: balance; }
.s1-subj span { font: 600 12px var(--font-mono); letter-spacing: 0.04em; color: color-mix(in oklch, var(--color-white) 72%, var(--s1-night)); }
.s1-midb { align-self: center; display: grid; gap: 22px; justify-items: center; }
.s1-susp { display: flex; align-items: baseline; gap: 2px; font: 800 96px/0.9 var(--font-display); letter-spacing: -0.04em; color: var(--color-white); font-variant-numeric: tabular-nums; }
.s1-susp small { font-size: 32px; opacity: 0.5; margin-left: 4px; }
.s1-gq { display: grid; gap: 6px; justify-items: center; }
.s1-gq b { width: 84px; height: 84px; border-radius: 24px; display: grid; place-items: center; font: 800 52px/1 var(--font-display); color: var(--s1-tide); box-shadow: inset 0 0 0 2px color-mix(in oklch, var(--s1-tide) 35%, var(--s1-night)); }
.s1-bot { display: grid; gap: 32px; justify-items: center; }
.s1-hint { font: 800 26px/1.15 var(--font-sans); letter-spacing: -0.02em; color: var(--color-white); min-height: 30px; }

.s1-hold { --hp: 0; width: 112px; height: 112px; border-radius: 50%; border: 0; position: relative; cursor: pointer; touch-action: none;
  background: conic-gradient(var(--s1-tide) calc(var(--hp) * 360deg), color-mix(in oklch, var(--s1-tide) 14%, var(--s1-night)) 0);
  animation: s1-beat var(--hb, 1.4s) ease-in-out infinite; }
.s1-hold::after { content: ""; position: absolute; inset: 8px; border-radius: 50%; background: color-mix(in oklch, var(--color-white) 3%, var(--s1-night)); }
.s1-hold::before { content: ""; position: absolute; inset: 0; border-radius: 50%; border: 2px solid var(--s1-tide); opacity: 0; animation: s1-echo var(--hb, 1.4s) ease-out infinite; }
.s1-hold span { position: relative; z-index: 1; font: 700 14px var(--font-sans); color: var(--color-white); }
.s1-hold:focus-visible { outline: 2px solid var(--s1-tide); outline-offset: 2px; }
@keyframes s1-beat { 0%, 100% { transform: scale(1); } 12% { transform: scale(1.06); } 24% { transform: scale(1); } 36% { transform: scale(1.04); } }
@keyframes s1-echo { 0% { transform: scale(1); opacity: 0.6; } 70%, 100% { transform: scale(1.28); opacity: 0; } }

.s1-res { position: absolute; inset: 0; z-index: 2; display: grid; place-content: start center; justify-items: center; gap: 6px; opacity: 0; pointer-events: none; text-align: center; padding: 72px 24px 24px; transition: opacity 0.4s var(--ease-out); }
.s1-ov:not([data-phase="hold"]) .s1-res { opacity: 1; }
.s1-res-score { font: 800 96px/0.95 var(--font-display); letter-spacing: -0.04em; color: var(--color-primary); font-variant-numeric: tabular-nums; }
.s1-res-score small { font-size: 40px; opacity: 0.6; letter-spacing: -0.03em; }
.s1-res-grade { display: inline-block; color: var(--color-white); border-radius: 20px; padding: 4px 30px; font: 800 96px/1.15 var(--font-display); letter-spacing: -0.03em; transform: scale(0); margin-top: 8px; }
.s1-ov:not([data-phase="hold"]) .s1-res-grade { animation: s1-gpop 0.7s cubic-bezier(0.16, 1, 0.3, 1) 0.5s forwards; }
@keyframes s1-gpop { 0% { transform: scale(0) rotate(-8deg); } 60% { transform: scale(1.25) rotate(2deg); } 100% { transform: scale(1); } }
.s1-res-line { font: 700 20px/1.3 var(--font-sans); color: var(--color-on-surface); max-width: 19ch; opacity: 0; transform: translateY(8px); margin-top: 10px; text-wrap: balance; }
.s1-ov:not([data-phase="hold"]) .s1-res-line { animation: s1-rise 0.5s var(--ease-out) 1.1s forwards; }
.s1-res-go { margin-top: 18px; opacity: 0; pointer-events: none; }
.s1-ov[data-phase="ready"] .s1-res-go { animation: s1-rise 0.5s var(--ease-out) forwards; pointer-events: auto; }
@keyframes s1-rise { to { opacity: 1; transform: none; } }

.s1-pz { position: absolute; z-index: 1; inset-inline: 0; top: 0; height: var(--cb, 440px); overflow: hidden; pointer-events: none; mask-image: linear-gradient(#000 55%, transparent); }
.s1-pulse { position: absolute; left: 50%; top: 210px; width: 200px; height: 200px; margin: -100px 0 0 -100px; border-radius: 50%; border: 3px solid var(--s1-tide); opacity: 0; }
.s1-ov[data-tier="a"]:not([data-phase="hold"]) .s1-pulse { animation: s1-pulse 1.8s cubic-bezier(0.2, 0.8, 0.2, 1) infinite; }
.s1-ov[data-tier="a"]:not([data-phase="hold"]) .s1-pulse:nth-child(2) { animation-delay: 0.6s; }
.s1-ov[data-tier="a"]:not([data-phase="hold"]) .s1-pulse:nth-child(3) { animation-delay: 1.2s; }
@keyframes s1-pulse { 0% { transform: scale(0.4); opacity: 0.9; } 100% { transform: scale(3.2); opacity: 0; } }

.s1-fly { position: absolute; left: 0; top: 0; width: 120px; height: 132px; z-index: 1; transform-origin: 50% 100%; will-change: transform; pointer-events: none; }

@media (prefers-reduced-motion: reduce) {
  .s1-hold, .s1-hold::before, .s1-pulse, .s1-ov[data-shake="true"] .s1-stage, .s1-ov[data-flash="true"] { animation: none !important; }
  .s1-ov:not([data-phase="hold"]) .s1-res-grade { animation: none; transform: none; }
  .s1-ov:not([data-phase="hold"]) .s1-res-line { animation: none; opacity: 1; transform: none; }
  .s1-ov[data-phase="ready"] .s1-res-go { animation: none; opacity: 1; }
  .s1-ovbg, .s1-res, .s1-holdui { transition: none; }
}
```

- [ ] **Step 2: Write the hold button**

```tsx
// web/src/portals/student/screens/result/HoldButton.tsx
import { useEffect, useRef } from "react"
import { holdProgress } from "./revealChoreography"

/**
 * Press and hold for 900ms. Releasing early resets to 0. Enter or Space reveals at
 * once (the mock's keyboard path), so the reveal never needs a pointer.
 * Progress is reported every frame and written to `--hp` for the conic ring.
 */
export function HoldButton({
  onProgress, onComplete, heartbeat,
}: { onProgress: (p: number) => void; onComplete: () => void; heartbeat: string }) {
  const ref = useRef<HTMLButtonElement>(null)
  const raf = useRef(0)
  const done = useRef(false)

  useEffect(() => () => cancelAnimationFrame(raf.current), [])

  function set(p: number) {
    ref.current?.style.setProperty("--hp", String(p))
    onProgress(p)
  }

  function start(e: React.PointerEvent) {
    if (done.current) return
    e.preventDefault()
    ref.current?.setPointerCapture?.(e.pointerId)
    const t0 = performance.now()
    const step = () => {
      const p = holdProgress(performance.now() - t0)
      set(p)
      if (p >= 1) {
        done.current = true
        onComplete()
        return
      }
      raf.current = requestAnimationFrame(step)
    }
    raf.current = requestAnimationFrame(step)
  }

  function stop() {
    if (done.current) return
    cancelAnimationFrame(raf.current)
    set(0)
  }

  return (
    <button
      ref={ref}
      type="button"
      className="s1-hold"
      data-print="hide"
      aria-label="Hold to reveal your grade"
      style={{ ["--hb" as string]: heartbeat }}
      onPointerDown={start}
      onPointerUp={stop}
      onPointerLeave={stop}
      onPointerCancel={stop}
      onKeyDown={(e) => {
        if ((e.key === "Enter" || e.key === " ") && !e.repeat && !done.current) {
          e.preventDefault()
          done.current = true
          set(1)
          onComplete()
        }
      }}
    >
      <span>Hold</span>
    </button>
  )
}
```

- [ ] **Step 3: Write the flight**

```tsx
// web/src/portals/student/screens/result/RevealFlight.tsx
import { useEffect, useRef } from "react"
import { Binny, type BinnyMood } from "@/components/redesign"
import type { GradeTier } from "./resultModel"
import {
  BINNY_BOX, HOP_EASING, TIMINGS, clampHop, freeZone, hopKeyframes, hopPlan, restPoint, type Point,
} from "./revealChoreography"

/**
 * Binny's celebration hops, inside the free zone below "See my result". Never
 * crosses the result stack. `phase` "out" fades him where he stands, then calls
 * `onGone`. Reduced motion: he is placed at the rest point and fades instantly.
 */
export function RevealFlight({
  tier, mood, stackBottom, active, leaving, reduced, onSettled, onGone,
}: {
  tier: GradeTier
  mood: BinnyMood
  stackBottom: number
  active: boolean
  leaving: boolean
  reduced: boolean
  onSettled: () => void
  onGone: () => void
}) {
  const ref = useRef<HTMLDivElement>(null)
  const settledAt = useRef<Point | null>(null)

  useEffect(() => {
    const el = ref.current
    if (!active || !el) return
    const stage = el.parentElement?.getBoundingClientRect()
    const width = (stage?.width ?? 390) - BINNY_BOX.width
    const safeBottom = Number.parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--sab")) || 0
    const zone = freeZone({ stackBottom, viewportHeight: window.innerHeight, safeBottom })
    const rest = restPoint(zone, width)
    let cancelled = false
    const animations: Animation[] = []

    if (reduced) {
      el.style.transform = `translate(${rest.x}px, ${rest.y}px)`
      settledAt.current = rest
      onSettled()
      return
    }

    let cur: Point = { x: Math.round(width / 2), y: window.innerHeight + 56 }
    el.style.transform = `translate(${cur.x}px, ${cur.y}px)`
    const run = async () => {
      await new Promise((r) => setTimeout(r, TIMINGS.firstHopDelay))
      for (const hop of hopPlan(tier, rest, width)) {
        if (cancelled) return
        const to = { x: hop.x, y: Math.min(Math.max(hop.y, zone.top), zone.bottom) }
        const anim = el.animate(hopKeyframes(cur, to, clampHop(hop.height, cur, to, zone.top)), {
          duration: hop.duration, easing: HOP_EASING, fill: "forwards",
        })
        animations.push(anim)
        await anim.finished.catch(() => undefined)
        cur = to
        if (hop.pauseAfter) await new Promise((r) => setTimeout(r, hop.pauseAfter))
      }
      if (!cancelled) {
        settledAt.current = cur
        onSettled()
      }
    }
    void run()
    return () => {
      cancelled = true
      animations.forEach((a) => a.cancel())
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- runs once per activation
  }, [active])

  useEffect(() => {
    const el = ref.current
    if (!leaving || !el) return
    if (reduced) {
      onGone()
      return
    }
    const fade = el.animate([{ opacity: 1 }, { opacity: 0 }], { duration: TIMINGS.fadeOut, easing: "ease-out", fill: "forwards" })
    void fade.finished.then(onGone, onGone)
    // eslint-disable-next-line react-hooks/exhaustive-deps -- runs once per leave
  }, [leaving])

  if (!active) return null
  return (
    <div ref={ref} className="s1-fly" aria-hidden>
      <Binny mood={mood} size={BINNY_BOX.width} motion={settledAt.current && !leaving ? "idle" : "none"} aria-hidden />
    </div>
  )
}
```

If F1 exposes a safe-area custom property under another name than `--sab`, use F1's (check `PortalShell` and `index.css` for the safe-area variable). Otherwise read `env(safe-area-inset-bottom)` through a hidden probe element.

- [ ] **Step 4: Write the overlay**

```tsx
// web/src/portals/student/screens/result/RevealOverlay.tsx
import { useEffect, useLayoutEffect, useRef, useState } from "react"
import { createPortal } from "react-dom"
import { Button } from "@/components/ui/button"
import { prefersReducedMotion } from "@/lib/celebration"
import type { PaperResult } from "@/lib/paperResultTypes"
import { HoldButton } from "./HoldButton"
import { RevealFlight } from "./RevealFlight"
import { gradeColour } from "./ResultHero"
import { binnyMoodFor, gradeTier, heroLine, paperMeta, subjectTitle } from "./resultModel"
import {
  COUNT_MS, TIMINGS, countValue, heartbeatSeconds, holdHint, scrambleIntervalMs, shouldShake, suspenseOpacity,
} from "./revealChoreography"

type Phase = "hold" | "celebrate" | "ready" | "out"

/* Mock .ov: the suspense hold (no Binny on it), then the celebration where Binny reacts. No confetti. */
export function RevealOverlay({ result, onDocked }: { result: PaperResult; onDocked: () => void }) {
  const reduced = prefersReducedMotion()
  const [phase, setPhase] = useState<Phase>("hold")
  const [p, setP] = useState(0)
  const [digits, setDigits] = useState(["?", "?"])
  const [score, setScore] = useState(0)
  const [flash, setFlash] = useState(false)
  const [stackBottom, setStackBottom] = useState(440)
  const goRef = useRef<HTMLButtonElement>(null)
  const holdRef = useRef<HTMLDivElement>(null)
  const lastScramble = useRef(0)
  const tier = gradeTier(result.grade)

  // Lock page scroll under the overlay; focus the hold button for keyboard users.
  useEffect(() => {
    const prev = document.body.style.overflow
    document.body.style.overflow = "hidden"
    holdRef.current?.querySelector<HTMLButtonElement>("button")?.focus()
    return () => {
      document.body.style.overflow = prev
    }
  }, [])

  // Digit scramble follows tension.
  useEffect(() => {
    if (phase !== "hold" || reduced || p <= 0.02) {
      setDigits(["?", "?"])
      return
    }
    const now = performance.now()
    if (now - lastScramble.current > scrambleIntervalMs(p)) {
      lastScramble.current = now
      setDigits([String(Math.floor(Math.random() * 10)), String(Math.floor(Math.random() * 10))])
    }
  }, [p, phase, reduced])

  // Count-up on reveal.
  useEffect(() => {
    if (phase !== "celebrate") return
    if (reduced) {
      setScore(result.awardedMarks)
      return
    }
    const t0 = performance.now()
    let raf = 0
    const step = () => {
      const t = (performance.now() - t0) / COUNT_MS
      setScore(countValue(result.awardedMarks, t))
      if (t < 1) raf = requestAnimationFrame(step)
    }
    raf = requestAnimationFrame(step)
    return () => cancelAnimationFrame(raf)
  }, [phase, reduced, result.awardedMarks])

  // Measure where the result stack ends: Binny's free zone starts below it.
  useLayoutEffect(() => {
    if (phase === "hold") return
    const rect = goRef.current?.getBoundingClientRect()
    if (rect) setStackBottom(rect.bottom)
  }, [phase])

  const opacity = suspenseOpacity(p)
  const overlay = (
    <div
      className="s1-ov"
      data-phase={phase}
      data-tier={tier}
      data-shake={phase === "hold" && shouldShake(p, reduced)}
      data-flash={flash}
      style={{ ["--cb" as string]: `${stackBottom}px` }}
      role="dialog"
      aria-modal="true"
      aria-label={`Your ${subjectTitle(result)} result`}
    >
      <div className="s1-ovbg" />
      <div className="s1-stage">
        <div className="s1-holdui" ref={holdRef}>
          <div className="s1-subj">
            <h2>Your {subjectTitle(result)} result is in</h2>
            <span>{paperMeta(result)}</span>
          </div>
          <div className="s1-midb" aria-hidden>
            <div className="s1-susp" style={{ opacity: opacity.digits }}>
              <span>{digits[0]}</span>
              <span>{digits[1]}</span>
              <small>/{result.maxMarks}</small>
            </div>
            <div className="s1-gq">
              <span className="text-label-sm uppercase text-inverse-on-surface/70">Grade</span>
              <b style={{ opacity: opacity.grade }}>?</b>
            </div>
          </div>
          <div className="s1-bot">
            <HoldButton
              heartbeat={heartbeatSeconds(p)}
              onProgress={setP}
              onComplete={() => {
                setFlash(!reduced)
                setPhase("celebrate")
              }}
            />
            <p className="s1-hint" aria-live="polite">{holdHint(p)}</p>
          </div>
        </div>
      </div>
      <div className="s1-pz" aria-hidden>
        <div className="s1-pulse" />
        <div className="s1-pulse" />
        <div className="s1-pulse" />
      </div>
      <div className="s1-res">
        <p className="s1-res-score" aria-live="polite">
          {score}
          <small>/{result.maxMarks}</small>
        </p>
        {result.grade ? (
          <p className="s1-res-grade" style={{ background: gradeColour(result.grade) }}>{result.grade}</p>
        ) : null}
        <p className="s1-res-line">{heroLine(result)}</p>
        <Button ref={goRef} variant="primary" size="lg" className="s1-res-go" onClick={() => setPhase("out")} tabIndex={phase === "ready" ? 0 : -1}>
          See my result
        </Button>
      </div>
      <RevealFlight
        tier={tier}
        mood={binnyMoodFor(result.grade)}
        stackBottom={stackBottom}
        active={phase !== "hold"}
        leaving={phase === "out"}
        reduced={reduced}
        onSettled={() => {
          setPhase((cur) => (cur === "celebrate" ? "ready" : cur))
          requestAnimationFrame(() => goRef.current?.focus())
        }}
        onGone={() => {
          window.setTimeout(onDocked, reduced ? 0 : TIMINGS.overlayOut)
        }}
      />
    </div>
  )
  return createPortal(overlay, document.body)
}
```

- [ ] **Step 5: Verify and commit**

Run: `cd web && npm run typecheck && npm run lint`
Expected: no errors.

```bash
pre-commit run --files web/src/portals/student/screens/result/HoldButton.tsx web/src/portals/student/screens/result/RevealFlight.tsx web/src/portals/student/screens/result/RevealOverlay.tsx web/src/portals/student/screens/result/result.css
git commit -S -m "feat(web): S1 hold-to-reveal overlay and Binny celebration" -- web/src/portals/student/screens/result/HoldButton.tsx web/src/portals/student/screens/result/RevealFlight.tsx web/src/portals/student/screens/result/RevealOverlay.tsx web/src/portals/student/screens/result/result.css
```

### Task 14: The student root, the shared body, delete and share, and the layouts

**Files:**
- Create: `web/src/portals/student/screens/result/PaperResultBody.tsx`, `DeletePaperButton.tsx`, `markerSource.ts`
- Modify (rewrite): `web/src/portals/student/screens/PaperResult.tsx`
- Modify: `web/src/portals/student/screens/result/resultModel.ts` (add `headerOnlyResult`), `web/tests/unit/resultModel.test.ts` (one test)

**Interfaces:**
- Consumes: everything from Tasks 8-13; `useResult` (`lib/hooks/useStudentApi.ts:46`); `useDeletePaper`; `deletionRefusal`, `isDeletionRefusal`; `shareResult`; `ApiError`; `Result`, `QuestionResult` (`lib/studentTypes.ts`).
- Produces:
  - `PaperResultBody({ result, shareHandler?, deleteAttemptId?, revealing, docked, onDocked, expanded, onExpand })`
  - `headerOnlyResult(res: Result): PaperResult`
  - `markerSourceLabel(source)` (moved verbatim from the old `PaperResult.tsx:124-126`)
  - `PaperResult()` (route element, same export name)

- [ ] **Step 1: Add `headerOnlyResult` with its test**

Append to `web/tests/unit/resultModel.test.ts`:

```ts
import { headerOnlyResult } from "@/portals/student/screens/result/resultModel"
import type { Result } from "@/lib/studentTypes"

describe("headerOnlyResult", () => {
  it("turns a file-store or live record into a no-detail result", () => {
    const res = {
      code: "0580", paper: "Paper 2 - Variant 1", session: "May/June 2024", markerLabel: "", headline: "",
      summary: "", awarded: 3, max: 5, pct: 60, grade: "C", boundaryYear: "2024", railLeft: 60, railFoot: "",
      railNote: "", theory: [], integrity: [], provenance: "", attemptId: null,
    } satisfies Result
    const out = headerOnlyResult(res)
    expect(out).toMatchObject({ subjectCode: "0580", awardedMarks: 3, maxMarks: 5, percentage: 60, grade: "C", questions: [], viewer: "student" })
    expect(resultLayout(out)).toBe("no_detail")
    expect(paperMeta(out)).toBe("May/June 2024")
  })
})
```

Append to `resultModel.ts`:

```ts
import type { Result } from "@/lib/studentTypes"

/** Keep-list K4/K5: the old header DTO (file-store record, or a gated 404) as a no-detail result. */
export function headerOnlyResult(res: Result): PaperResult {
  return {
    attemptId: res.attemptId ?? "",
    viewer: "student",
    subjectCode: res.code || null,
    subjectName: null,
    paperNumber: null,
    paperVariant: null,
    sessionLabel: res.session || null,
    awardedMarks: res.awarded,
    maxMarks: res.max,
    percentage: res.pct,
    grade: res.grade || null,
    boundaryEstimated: false,
    nextGrade: null,
    marksToNextGrade: null,
    deltaVsLast: null,
    isFirstPaper: false,
    recordedAt: "",
    questions: [],
    challengeLimit: 3,
    challengesUsed: 0,
    reviewer: null,
  }
}
```

Run: `cd web && npx vitest run tests/unit/resultModel.test.ts`
Expected: PASS.

- [ ] **Step 2: Move the marker source label and the delete control**

```ts
// web/src/portals/student/screens/result/markerSource.ts
import { markerScored } from "@/lib/markingConfidence"
import type { QuestionResult } from "@/lib/studentTypes"

/**
 * Moved verbatim from the old `PaperResult.tsx` (US-038/US-039, task #36): a
 * question no method marked reads "not marked", never the raw token.
 */
export function markerSourceLabel(source: QuestionResult["markerSource"]): string {
  return markerScored(source) ? source : "not marked"
}
```

`DeletePaperButton.tsx` is the old `DeletePaperControl` (`PaperResult.tsx:193-263`), moved verbatim. It keeps the function name `DeletePaperControl` and the inner `handleConfirm` (the `recentlyDeletedWiring` gate reads both). It keeps `deletionRefusal(err.body)` and `isDeletionRefusal(err.body)`. The one change is the button: `variant="ghost"`, `className="justify-self-start text-on-surface-variant"`, label "Delete this paper", still `data-print="hide"`, with no `disabled`.

```tsx
// web/src/portals/student/screens/result/DeletePaperButton.tsx
import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { Trash } from "@phosphor-icons/react"
import { Button } from "@/components/ui/button"
import { ConfirmModal } from "@/components/ui/confirm-modal"
import { ApiError } from "@/lib/api"
import { useDeletePaper } from "@/lib/hooks/usePaperDeletionApi"
import { deletionRefusal, isDeletionRefusal } from "@/lib/paperDeletion"
import { studentLoadFailureMessage } from "@/lib/studentOutcome"

/* Moved from the old PaperResult.tsx (spec 2026-09-22, Task 14). Same for every paper: no
   pre-signalling, no disabled state. The refusal is discovered on the request. */
export function DeletePaperControl({ attemptId, subjectCode }: { attemptId: string; subjectCode: string }) {
  const navigate = useNavigate()
  const deletePaper = useDeletePaper()
  const [open, setOpen] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleConfirm() {
    setError(null)
    try {
      await deletePaper.mutateAsync({ attemptId })
      navigate(`/student/subject/${subjectCode}`)
    } catch (err) {
      if (err instanceof ApiError && err.status === 409 && isDeletionRefusal(err.body)) {
        setError(deletionRefusal(err.body))
      } else if (err instanceof ApiError && err.status === 404) {
        setError("This paper isn't here anymore.")
      } else {
        setError(studentLoadFailureMessage(err))
      }
    }
  }

  return (
    <>
      <Button
        variant="ghost"
        size="sm"
        data-print="hide"
        className="justify-self-start text-on-surface-variant"
        onClick={() => {
          setError(null)
          setOpen(true)
        }}
      >
        <Trash size={16} weight="bold" />
        Delete this paper
      </Button>
      <ConfirmModal
        open={open}
        title="Delete this paper?"
        consequence="It moves to Recently deleted, where you can restore it for a while."
        confirmLabel="Delete"
        pendingLabel="Deleting…"
        pending={deletePaper.isPending}
        error={error}
        onConfirm={handleConfirm}
        onCancel={() => {
          setOpen(false)
          setError(null)
        }}
      />
    </>
  )
}
```

- [ ] **Step 3: Write the shared body**

```tsx
// web/src/portals/student/screens/result/PaperResultBody.tsx
import { useNavigate } from "react-router-dom"
import type { PaperResult } from "@/lib/paperResultTypes"
import { FirstPaperNote } from "./FirstPaperNote"
import { FullMarksNote } from "./FullMarksNote"
import { NextStepCard } from "./NextStepCard"
import { NoDetailNote } from "./NoDetailNote"
import { ResultHero } from "./ResultHero"
import { ResultTitleRow } from "./ResultTitleRow"
import { RevealOverlay } from "./RevealOverlay"
import { WinRows } from "./WinRows"
import { DeletePaperControl } from "./DeletePaperButton"
import {
  binnyMoodFor, firstPaperChip, fullMarksChip, nextStep, paperMeta, resultLayout, subjectTitle, winRows,
} from "./resultModel"
import "./result.css"

/*
 * The S1 page for a loaded result, shared by the student root and the parent
 * root. Phone: one column. Tablet: the same column, centred at the reading width.
 * Desktop (shell-lg): the title row on top, then hero and next step on the left
 * (sticky) and the rows on the right.
 */
export function PaperResultBody({
  result, shareHandler, deleteAttemptId, revealing, docked, onDocked, expanded, onExpand,
}: {
  result: PaperResult
  shareHandler?: () => void
  deleteAttemptId?: string | null
  /** The reveal overlay is up. */
  revealing: boolean
  /** The overlay just handed over: the card Binny pops in. */
  docked: boolean
  onDocked: () => void
  expanded: boolean
  onExpand: () => void
}) {
  const navigate = useNavigate()
  const layout = resultLayout(result)
  const rows = winRows(result)
  const step = nextStep(result, rows)
  const isStudent = result.viewer === "student"
  const shown = !revealing

  const left = (
    <div className="grid content-start gap-4 shell-lg:sticky shell-lg:top-4">
      {layout === "full" ? (
        <ResultHero result={result} variant="dark" />
      ) : (
        <ResultHero
          result={result}
          variant="light"
          chip={
            layout === "first_paper"
              ? { label: firstPaperChip, tone: "info" }
              : layout === "full_marks"
                ? { label: fullMarksChip, tone: "ok" }
                : undefined
          }
        />
      )}
      {layout === "full" && step && isStudent ? (
        <NextStepCard
          step={step}
          binnyMood={binnyMoodFor(result.grade)}
          binnyPop={docked}
          showBinny={!revealing}
          onPractise={() => step.primary.href && navigate(step.primary.href)}
          onPlan={() => step.studyPlanHref && navigate(step.studyPlanHref)}
          onScan={() => navigate(step.scanHref)}
        />
      ) : null}
      {layout === "first_paper" && isStudent ? <FirstPaperNote onScan={() => navigate("/student/correct")} /> : null}
      {layout === "full_marks" && isStudent ? (
        <FullMarksNote showBinny={!revealing} onScan={() => navigate("/student/correct")} onShare={shareHandler} />
      ) : null}
      {layout === "full_marks" && !isStudent ? (
        <p className="text-display-xs text-primary">Nothing to win back on this one.</p>
      ) : null}
      {layout === "no_detail" ? <NoDetailNote /> : null}
    </div>
  )

  const right =
    layout === "full" || layout === "first_paper" ? (
      <div className="grid content-start gap-4">
        <WinRows result={result} rows={rows} expanded={expanded} onExpand={onExpand} />
      </div>
    ) : null

  return (
    <>
      <div className="s1-rise" data-shown={shown}>
        <div
          className={
            right
              ? "mx-auto grid w-full max-w-(--container-read) gap-4 shell-lg:max-w-none shell-lg:grid-cols-[minmax(0,5fr)_minmax(0,6fr)] shell-lg:items-start shell-lg:gap-x-8"
              : "mx-auto grid w-full max-w-(--container-read) gap-4"
          }
        >
          <div className={right ? "shell-lg:col-span-2" : undefined}>
            <ResultTitleRow title={subjectTitle(result)} meta={paperMeta(result)} onShare={shareHandler} />
          </div>
          {left}
          {right}
          {isStudent && deleteAttemptId && result.subjectCode ? (
            <div className={right ? "shell-lg:col-start-2" : undefined}>
              <DeletePaperControl attemptId={deleteAttemptId} subjectCode={result.subjectCode} />
            </div>
          ) : null}
        </div>
      </div>
      {revealing && isStudent ? <RevealOverlay result={result} onDocked={onDocked} /> : null}
    </>
  )
}
```

- [ ] **Step 4: Rewrite the route root**

```tsx
// web/src/portals/student/screens/PaperResult.tsx
import { useEffect, useState } from "react"
import { useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom"
import { useToast } from "@/components/ui/toast"
import { ApiError } from "@/lib/api"
import { usePaperResult } from "@/lib/hooks/usePaperResultApi"
import { useResult } from "@/lib/hooks/useStudentApi"
import { shareResult } from "@/lib/share"
import type { PaperResult as PaperResultData } from "@/lib/paperResultTypes"
import type { QuestionResult, Result } from "@/lib/studentTypes"
import { PaperResultBody } from "./result/PaperResultBody"
import { ResultError, ResultNotFound, ResultSkeleton } from "./result/ResultStates"
import { headerOnlyResult } from "./result/resultModel"
import { hasRevealed, markRevealed, shouldReveal } from "./result/revealChoreography"

/*
 * S1 paper result (lane L7). Two sources, as before:
 *   - live: `location.state` from CorrectPaper right after marking (justMarked);
 *   - history: `GET /student/result/{paperId}` (history index) for the attempt id.
 * Either way the page itself comes from `GET /api/attempts/{attemptId}/result`.
 * The hold-to-reveal plays only on proof the student has not seen this mark:
 * straight off marking, or the first open of the attempt on this device.
 */

type LiveResult = Result & { questions: QuestionResult[] }

function isLiveResult(state: unknown): state is LiveResult {
  return !!state && typeof state === "object" && "questions" in state
}

const is404 = (err: unknown) => err instanceof ApiError && err.status === 404

export function PaperResult() {
  const { paperId } = useParams<{ paperId: string }>()
  const location = useLocation()
  const navigate = useNavigate()
  const { toast } = useToast()
  const [searchParams, setSearchParams] = useSearchParams()
  const live = isLiveResult(location.state) ? location.state : null
  const history = useResult(live ? "" : (paperId ?? ""))
  const header: Result | undefined = live ?? history.data
  const attemptId = header?.attemptId ?? null
  const query = usePaperResult(attemptId)
  const [revealing, setRevealing] = useState<boolean | null>(null)
  const [docked, setDocked] = useState(false)
  const expanded = searchParams.get("q") === "all"

  useEffect(() => {
    if (revealing !== null || !query.data || !attemptId) return
    setRevealing(shouldReveal({ justMarked: !!live, seen: hasRevealed(attemptId) }))
  }, [query.data, attemptId, live, revealing])

  const back = () => navigate("/student")
  const shareHandler = (res: PaperResultData) =>
    !live && paperId
      ? () =>
          void shareResult(
            {
              url: `${window.location.origin}/student/result/${paperId}`,
              title: `${res.subjectCode ?? ""} result`.trim(),
              text: `${res.awardedMarks}/${res.maxMarks}${res.grade ? `, ${res.grade}` : ""}`,
            },
            { toast: (msg) => toast({ title: msg }) },
          )
      : undefined

  if (!live && history.isError) {
    return is404(history.error) ? (
      <ResultNotFound onCorrect={() => navigate("/student/correct")} onBack={back} />
    ) : (
      <ResultError error={history.error} onRetry={() => void history.refetch()} onBack={back} />
    )
  }
  if (!header) return <ResultSkeleton />

  // K4/K5: no attempt id (file store), or the result read 404s on a record we know exists.
  if (!attemptId || (query.isError && is404(query.error))) {
    const res = headerOnlyResult(header)
    return (
      <PaperResultBody
        result={res}
        shareHandler={shareHandler(res)}
        revealing={false}
        docked={false}
        onDocked={() => undefined}
        expanded={false}
        onExpand={() => undefined}
      />
    )
  }
  if (query.isError) return <ResultError error={query.error} onRetry={() => void query.refetch()} onBack={back} />
  if (!query.data || revealing === null) return <ResultSkeleton />

  return (
    <PaperResultBody
      result={query.data}
      shareHandler={shareHandler(query.data)}
      deleteAttemptId={attemptId}
      revealing={revealing}
      docked={docked}
      onDocked={() => {
        markRevealed(attemptId)
        setRevealing(false)
        setDocked(true)
      }}
      expanded={expanded}
      onExpand={() =>
        setSearchParams(
          (prev) => {
            const next = new URLSearchParams(prev)
            next.set("q", "all")
            return next
          },
          { replace: true },
        )
      }
    />
  )
}
```

The route entry in `web/src/portals/student/index.tsx:249-257` is unchanged (same element, title and skeleton).

- [ ] **Step 5: Verify in the browser, then commit**

Run: `cd web && npm run typecheck && npm run lint && npm run check:copy && npx vitest run tests/unit/resultModel.test.ts`
Expected: no errors. Then run the app (`run` skill) with the seeded `s1` student at 390, 1024 and 1280:
- `/student/result/0` plays the hold the first time and not on reload
- the rows expand
- the challenge flow runs end to end
- `?q=all` survives a round trip

Several old source gates fail until Task 16. That is expected, and Task 16 must land in the same PR.

```bash
pre-commit run --files web/src/portals/student/screens/PaperResult.tsx web/src/portals/student/screens/result/PaperResultBody.tsx web/src/portals/student/screens/result/DeletePaperButton.tsx web/src/portals/student/screens/result/markerSource.ts web/src/portals/student/screens/result/resultModel.ts web/tests/unit/resultModel.test.ts
git commit -S -m "feat(web): S1 paper result replaces the old result screen" -- web/src/portals/student/screens/PaperResult.tsx web/src/portals/student/screens/result/PaperResultBody.tsx web/src/portals/student/screens/result/DeletePaperButton.tsx web/src/portals/student/screens/result/markerSource.ts web/src/portals/student/screens/result/resultModel.ts web/tests/unit/resultModel.test.ts
```

### Task 15: The parent's read-only paper result

**Files:**
- Create: `web/src/portals/parent/screens/ChildPaperResult.tsx`
- Modify: `web/src/portals/parent/index.tsx` (a lazy import beside `SubjectDetail` at `:34`, and a route after `children/:childId/subjects/:code` at `:414-418`)

**Interfaces:**
- Consumes: `usePaperResult` (Task 8), `PaperResultBody` (Task 14), `ResultSkeleton`, `ResultError` (Task 11).
- Produces: route `/parent/children/:childId/papers/:attemptId`. L11 links `SubjectDetail` paper rows to it with `SubjectPaperDTO.attemptId` (Task 6).

No Binny, no reveal, no next-step card, no challenge, no self-review, no delete. `PaperResultBody` gates each of these on `result.viewer === "student"`, and the server sends `viewer: "parent"` with `canChallenge: false`. The parent `components` and `portals/parent` paths are scanned by `design-tokens.test.ts`, so this file uses no arbitrary font-size or radius literals.

- [ ] **Step 1: Write the screen**

```tsx
// web/src/portals/parent/screens/ChildPaperResult.tsx
import { useNavigate, useParams } from "react-router-dom"
import { EmptyState } from "@/components/ui/state-views"
import { ApiError } from "@/lib/api"
import { usePaperResult } from "@/lib/hooks/usePaperResultApi"
import { PaperResultBody } from "@/portals/student/screens/result/PaperResultBody"
import { ResultError, ResultSkeleton } from "@/portals/student/screens/result/ResultStates"

/* Lane L7: a linked child's marked paper, read-only. The server scopes it to the parent link. */
export function ChildPaperResult() {
  const { childId, attemptId } = useParams<{ childId: string; attemptId: string }>()
  const navigate = useNavigate()
  const query = usePaperResult(attemptId)
  const back = () => navigate(`/parent/children/${childId}`)

  if (query.isError) {
    return query.error instanceof ApiError && query.error.status === 404 ? (
      <EmptyState
        heading="This paper isn't available"
        body="It may have been deleted, or it belongs to a child you're not linked to."
        action={{ label: "Back to progress", onClick: back }}
      />
    ) : (
      <ResultError error={query.error} onRetry={() => void query.refetch()} onBack={back} />
    )
  }
  if (!query.data) return <ResultSkeleton />
  return (
    <PaperResultBody
      result={query.data}
      revealing={false}
      docked={false}
      onDocked={() => undefined}
      expanded
      onExpand={() => undefined}
    />
  )
}
```

`ResultError`'s secondary button says "Back to overview". For a parent, that sends them to the child's progress page, which is the parent's overview, so the copy holds.

- [ ] **Step 2: Register the route**

In `web/src/portals/parent/index.tsx`:

```tsx
const ChildPaperResult = lazy(() =>
  import("./screens/ChildPaperResult").then((m) => ({ default: m.ChildPaperResult })),
)
```

and after the `children/:childId/subjects/:code` route:

```tsx
    {
      path: "children/:childId/papers/:attemptId",
      element: <ChildPaperResult />,
      handle: { title: "Paper result", skeleton: "page-header" },
    },
```

- [ ] **Step 3: Verify and commit**

Run: `cd web && npm run typecheck && npm run lint && npx vitest run tests/unit/design-tokens.test.ts`
Expected: no errors, and the design-token scan passes for the new parent file.

```bash
pre-commit run --files web/src/portals/parent/screens/ChildPaperResult.tsx web/src/portals/parent/index.tsx
git commit -S -m "feat(web): parent read-only paper result" -- web/src/portals/parent/screens/ChildPaperResult.tsx web/src/portals/parent/index.tsx
```

### Task 16: Retarget the source gates and delete the old code

**Files:**
- Modify: `web/tests/unit/celebration.test.ts:216-227` and the `REVEAL_CALL_SITES` text for `mark-display.tsx`
- Modify: `web/tests/unit/capabilityWiring.test.ts:60-65`
- Modify: `web/tests/unit/selfReviewWiring.test.ts:43-100`
- Modify: `web/tests/unit/recentlyDeletedWiring.test.ts:65-100`
- Modify: `web/tests/unit/printStyles.test.ts:125-133`
- Modify: `web/tests/unit/redPen.test.ts:60-71`
- Modify: `web/tests/unit/screenEntrance.test.ts:27-41`
- Modify: `web/tests/unit/rtlSafety.test.ts:126` and `web/tests/unit/utilityExistence.test.ts:88`: add every `src/portals/student/screens/result/*.tsx` file and `src/portals/parent/screens/ChildPaperResult.tsx`
- Modify: `web/tests/unit/markerSourceLabel.test.ts:3`: import from `@/portals/student/screens/result/markerSource`
- Create: `web/tests/unit/paperResultWiring.test.ts`
- Delete code: the old `PaperResult.tsx` internals went in Task 14. Now check for orphans.

**Interfaces:** none new. Gates only.

Every retargeted gate must still go red when its rule breaks. After each edit, mutate the source the gate protects (delete the line it pins), see the gate fail, then restore. That's the "Verification needs a failing case" rule.

- [ ] **Step 1: Write the new wiring gate**

```ts
// web/tests/unit/paperResultWiring.test.ts
import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"

const ROOT = join(import.meta.dirname, "..", "..")
const read = (p: string) => readFileSync(join(ROOT, p), "utf8")
const DIR = "src/portals/student/screens/result"

describe("S1 result wiring (lane L7)", () => {
  const root = read("src/portals/student/screens/PaperResult.tsx")
  const body = read(`${DIR}/PaperResultBody.tsx`)

  it("gates the reveal on proof the mark is unseen", () => {
    expect(root).toContain("shouldReveal({ justMarked: !!live, seen: hasRevealed(attemptId) })")
    expect(root).toContain("markRevealed(attemptId)")
    expect(body).toMatch(/\{revealing && isStudent \? <RevealOverlay/)
  })

  it("never shows confetti", () => {
    for (const file of ["RevealOverlay.tsx", "RevealFlight.tsx", "result.css"]) {
      expect(read(`${DIR}/${file}`).toLowerCase()).not.toContain("confetti")
    }
  })

  it("keeps one Binny on screen: the card Binny waits for the flight to leave", () => {
    expect(body).toContain("showBinny={!revealing}")
  })

  it("asks the server, not a constant, for the challenge friction", () => {
    const model = read(`${DIR}/resultModel.ts`)
    expect(model).not.toMatch(/0\.7\b|\b70\b/)
    expect(model).toContain("q.confirmChallenge")
    expect(model).toContain("q.minReasonChars")
  })

  it("hides every on-screen action from print", () => {
    for (const file of ["ResultTitleRow.tsx", "WinRow.tsx", "NextStepCard.tsx", "DeletePaperButton.tsx", "HoldButton.tsx"]) {
      expect(read(`${DIR}/${file}`)).toContain('data-print="hide"')
    }
  })

  it("renders crop failures as absence", () => {
    const crop = read(`${DIR}/AnswerCrop.tsx`)
    expect(crop).toContain("if (!crop.url) return null")
    expect(crop).toContain("onError={crop.onDecodeError}")
  })

  it("keeps the parent view read-only", () => {
    expect(body).toContain('const isStudent = result.viewer === "student"')
    const parent = read("src/portals/parent/screens/ChildPaperResult.tsx")
    expect(parent).toContain("revealing={false}")
    expect(parent).not.toContain("deleteAttemptId")
    expect(parent).not.toContain("shareHandler")
  })
})
```

- [ ] **Step 2: Retarget the existing gates**

Make these edits, one test file at a time:
- **`celebration.test.ts`:** replace the body of `"reveals the live result and not the one opened from history"` with assertions on `PaperResult.tsx` containing `shouldReveal({ justMarked: !!live, seen: hasRevealed(attemptId) })`, and on `PaperResultBody.tsx` rendering `<RevealOverlay` only under `revealing && isStudent`. Rename the test to `"reveals only when the student has not seen the mark"`. Change the `mark-display.tsx` `REVEAL_CALL_SITES` reason to name `PracticeResult` and any remaining caller (check with `graphify query "MarkDisplay reveal callers"`). If `MarkDisplay`'s `reveal` prop has no caller left, keep the entry, since the component still owns the branch, and say so in the reason. The S1 count-up is not `<CountUp from=...>`, so the allowlist walk stays green without a new entry. Add a comment naming `result/RevealOverlay.tsx` and its proof (`shouldReveal`) so the next reader finds it.
- **`capabilityWiring.test.ts`:** read `src/portals/student/screens/PaperResult.tsx` and still expect `shareResult`.
- **`selfReviewWiring.test.ts`:** replace the `HistoryQuestions`, `useAttemptQuestions` and `questions={rows}` assertions with:
  - `result/SelfReviewSheet.tsx` contains `<SelfReviewPanel attemptId={attemptId} questionResultId={questionResultId} />`
  - `result/WinRow.tsx` contains `row.selfReviewable ?`
  - `PaperResult.tsx` contains `usePaperResult(attemptId)`, where `attemptId` comes from `header?.attemptId` (live or history: one wiring for both, replacing the two branch-anchored gates)
  - `PaperResult.tsx` contains `is404(query.error)`, the honest-empty path, and `<ResultError`

  Keep the Task 13/14 hook gates below them unchanged.
- **`recentlyDeletedWiring.test.ts`:** point `readSource` at `src/portals/student/screens/result/DeletePaperButton.tsx` for the `DeletePaperControl` and `handleConfirm` gates. Replace `toContain("res.attemptId ? (")` with a check on `PaperResultBody.tsx` for `isStudent && deleteAttemptId && result.subjectCode ? (`, plus `<DeletePaperControl`.
- **`printStyles.test.ts` (`PaperResult.tsx` block):** read `result/ResultTitleRow.tsx` and assert the share `<button` tag carries `data-print="hide"`.
- **`redPen.test.ts` (`PaperResult.tsx` block):** S1 drops the red-pen register on purpose (K28). Replace the block with one test asserting `result/WinRow.tsx` does not contain `lm-red-pen` and does contain `+{row.lost}` (the opportunity framing). Name it in the PR's mock-deviation list.
- **`screenEntrance.test.ts`:** `PaperResult.tsx` no longer carries `lm-screen` (the overlay is its entrance). Remove the exception: delete the `endsWith("PaperResult.tsx")` skip and the "still carries lm-screen" test. Add `expect(sourceOf("src/portals/student/screens/PaperResult.tsx")).not.toContain("lm-screen")`.
- **`rtlSafety.test.ts` and `utilityExistence.test.ts`:** append the new files under a `// Lane L7: S1 result` comment.
- **`markerSourceLabel.test.ts`:** change the import path only.

- [ ] **Step 3: Find orphans and delete them**

Run: `graphify query "who imports confidenceSummaryOf ConfidenceIndicatorSummary filterQuestions markState useAttemptQuestions BoundaryBar QuestionRow"`, then confirm with `tokensave_search` (`literal: true`) or `grep -rn` under `web/src`.
- Delete any of these that `PaperResult.tsx` was the last caller of, with their own unit tests: `lib/questionFilter.ts`, `components/ui/confidence-indicator.tsx`, `components/ui/boundary-bar.tsx`.
- Keep anything another screen still imports (`QuestionRow` is shared with practice; `useAttemptQuestions` and the self-review hooks stay for `SelfReviewPanel`).
- List each deletion in the PR.

Run: `cd web && npm run typecheck`
Expected: no unresolved imports.

- [ ] **Step 4: Run every touched gate and prove each can fail**

Run: `cd web && npx vitest run tests/unit/paperResultWiring.test.ts tests/unit/celebration.test.ts tests/unit/capabilityWiring.test.ts tests/unit/selfReviewWiring.test.ts tests/unit/recentlyDeletedWiring.test.ts tests/unit/printStyles.test.ts tests/unit/redPen.test.ts tests/unit/screenEntrance.test.ts tests/unit/rtlSafety.test.ts tests/unit/utilityExistence.test.ts tests/unit/markerSourceLabel.test.ts tests/unit/design-tokens.test.ts tests/unit/a11yRules.test.ts tests/unit/hoverTransition.test.ts tests/unit/checkCopy.test.ts && npm run check:copy && npm run check:native`
Expected: PASS.

Then, for each retargeted gate, remove the line it pins from the source, re-run that one test file to see it FAIL, and restore with `git checkout -- <file>`. Record the pairs in the PR body.

- [ ] **Step 5: Commit**

```bash
pre-commit run --files web/tests/unit/paperResultWiring.test.ts web/tests/unit/celebration.test.ts web/tests/unit/capabilityWiring.test.ts web/tests/unit/selfReviewWiring.test.ts web/tests/unit/recentlyDeletedWiring.test.ts web/tests/unit/printStyles.test.ts web/tests/unit/redPen.test.ts web/tests/unit/screenEntrance.test.ts web/tests/unit/rtlSafety.test.ts web/tests/unit/utilityExistence.test.ts web/tests/unit/markerSourceLabel.test.ts <deleted files>
git commit -S -m "test(web): retarget result-screen gates to S1 and delete orphans" -- web/tests/unit/paperResultWiring.test.ts web/tests/unit/celebration.test.ts web/tests/unit/capabilityWiring.test.ts web/tests/unit/selfReviewWiring.test.ts web/tests/unit/recentlyDeletedWiring.test.ts web/tests/unit/printStyles.test.ts web/tests/unit/redPen.test.ts web/tests/unit/screenEntrance.test.ts web/tests/unit/rtlSafety.test.ts web/tests/unit/utilityExistence.test.ts web/tests/unit/markerSourceLabel.test.ts <deleted files>
```

Replace `<deleted files>` with the exact paths removed in Step 3 (`git rm` them first). If none were removed, drop it.

### Task 17: Playwright: the S1 happy path, plus the two specs that read the old screen

**Files:**
- Create: `web/e2e/paper-result-s1.spec.ts`
- Modify: `web/e2e/self-review.spec.ts` (opens `/student/result/0`, then clicks the row button matching `ROW_2`)
- Modify: `web/e2e/correct-paper.spec.ts:60-90` (score label, grade badge, eight row buttons)

**Interfaces:** consumes `seed.students.s1` (Task 7) and `seed.students.selfReview`.

- [ ] **Step 1: Write the S1 spec**

```ts
// web/e2e/paper-result-s1.spec.ts
import { test, expect } from "@playwright/test"
import { watchConsole } from "./console-errors"
import { readSeed } from "./seed"

/*
 * Lane L7. The seeded `s1` student opens their one paper from history (index 0),
 * holds to reveal, sees the celebration, lands on the result, opens the confident
 * loss (Q3, 82%), confirms, writes a 40-character reason with the tick and sends.
 * The low-confidence loss (Q2) shows the scheme wording and no confirm step.
 */

const REASON = "I wrote g/cm3 on the line under my answer, see Q3."

test("a student reveals their result and challenges a confident mark", async ({ page }) => {
  const seed = readSeed()
  const errors = watchConsole(page)
  const student = seed.students.s1

  await page.goto("/login")
  await page.getByLabel("Email").fill(student.email)
  await page.getByLabel("Password").fill(student.password)
  await page.getByRole("button", { name: /sign in/i }).click()
  await expect(page).toHaveURL(/\/student$/, { timeout: 15_000 })

  await page.goto("/student/result/0")

  // Suspense: full-screen, no Binny, hold to reveal.
  const hold = page.getByRole("button", { name: "Hold to reveal your grade" })
  await expect(hold).toBeVisible({ timeout: 15_000 })
  await expect(page.getByText("Hold to reveal")).toBeVisible()
  const box = await hold.boundingBox()
  if (!box) throw new Error("hold button has no box")
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
  await page.mouse.down()
  await page.waitForTimeout(1100)
  await page.mouse.up()

  const go = page.getByRole("button", { name: "See my result" })
  await expect(go).toBeVisible({ timeout: 10_000 })
  await go.click()
  await expect(go).toHaveCount(0, { timeout: 5_000 })

  // The page.
  await expect(page.getByLabel("4 out of 9 marks, 44 percent")).toBeVisible()
  await expect(page.getByRole("img", { name: "Predicted grade D" })).toBeVisible()
  await expect(page.getByRole("heading", { name: "Marks you can win" })).toBeVisible()

  // Q2: low confidence, scheme wording, no confirm.
  await page.getByRole("button", { name: /^\+2 to win Q2/ }).click()
  await expect(page.getByText("Mark scheme")).toBeVisible()

  // Q3: confident, confirm, then the 40-character reason and the tick.
  await page.getByRole("button", { name: /^\+3 to win Q3/ }).click()
  await page.getByRole("button", { name: "Challenge this mark" }).click()
  await expect(page.getByText("Lemely was 82% sure on this one. You get 3 challenges per paper.")).toBeVisible()
  await page.getByRole("button", { name: "Yes, challenge" }).click()

  const send = page.getByRole("button", { name: "Send challenge" })
  await expect(send).toBeDisabled()
  await page.getByLabel("Justification").fill(REASON.slice(0, 39))
  await expect(page.getByText("39/40 min")).toBeVisible()
  await expect(send).toBeDisabled()
  await page.getByLabel("Justification").fill(REASON)
  await expect(send).toBeDisabled()
  await page.getByLabel("I have compared my answer with the mark scheme.").check()
  await expect(send).toBeEnabled()
  await send.click()

  await expect(page.getByText("Challenge sent", { exact: true })).toBeVisible({ timeout: 10_000 })

  // A reload does not replay the reveal (seen on this device).
  await page.reload()
  await expect(page.getByRole("heading", { name: "Marks you can win" })).toBeVisible({ timeout: 15_000 })
  await expect(page.getByRole("button", { name: "Hold to reveal your grade" })).toHaveCount(0)

  expect(errors()).toEqual([])
})
```

The row button's accessible name is its text content: "+3 to win Q3 · Density and units Unit missing in the final answer". If the `WinRow` markup changes, update the two `/^\+N to win QN/` regexes to match.

- [ ] **Step 2: Update the two specs that read the old screen**

`self-review.spec.ts`: after `page.goto("/student/result/0")`, the first visit now shows the reveal. Add the same press-and-hold block, then `See my result`. Replace the `3 out of 5 marks, 60 percent` label check (unchanged text; it still holds). Replace `page.getByRole("button", { name: ROW_2 })` with:
- `page.getByRole("button", { name: /^\+2 to win 2|^\+2 to win Q2/ })`, which expands the row
- then `page.getByRole("button", { name: "Mark it yourself" })`
- then the existing `getByTestId("self-review-form")` assertions, unchanged

`correct-paper.spec.ts`: the live path plays the reveal straight after marking. After the URL assertion, hold and press "See my result", then:
- keep `getByLabel("5 out of 8 marks, 63 percent")`
- keep the grade `getByRole("img", { name: /^Predicted grade / })`
- replace the eight `QuestionRow` buttons with the lost-marks rows: count the buttons matching `/to win Q/` and compare against the seeded wrong answers. Read the seed's canned extraction (`_extracted()` in `tests/test_student_correct.py` mirrors it) to get the exact count. If the rows fold at six, press "Show all answers" first.

- [ ] **Step 3: Run the three specs**

Run: `cd web && npx playwright test e2e/paper-result-s1.spec.ts e2e/self-review.spec.ts e2e/correct-paper.spec.ts --project=chromium`
Expected: 3 passed. Also run `--project=iphone-15` for `paper-result-s1.spec.ts`. Expected: pass.

- [ ] **Step 4: Commit**

```bash
pre-commit run --files web/e2e/paper-result-s1.spec.ts web/e2e/self-review.spec.ts web/e2e/correct-paper.spec.ts
git commit -S -m "test(e2e): S1 reveal and challenge happy path" -- web/e2e/paper-result-s1.spec.ts web/e2e/self-review.spec.ts web/e2e/correct-paper.spec.ts
```

---

## Final tasks

### Task 18: Side-by-side fidelity screenshots, drift fixes, `/impeccable polish`

**Files:** screenshots in `.omc/artifacts/l07/` (not committed). Drift fixes touch only `web/src/portals/student/screens/result/*` and `result.css`.

- [ ] **Step 1: Serve the mock and the app**

```bash
cd /path/to/worktree && npx --yes http-server .impeccable/mocks -p 4410 -s &
cd web && npm run dev &
```

Use bounded waits only (`timeout 60 bash -c 'until curl -sf localhost:4410/student-r1/s1.html; do sleep 1; done'`).

- [ ] **Step 2: Capture pairs**

With Playwright (the `webapp-testing` skill), log in as `seed.students.s1` and capture at 390x844 and 1280x800:

| Pair | Mock | App |
|---|---|---|
| hold | `s1.html` on load | `/student/result/0` first visit |
| hold 70% | `s1.html`, hold for 650ms then screenshot | same |
| celebrate | `s1.html` after `#hold` reaches 1, wait 2.5s | same |
| result | `s1.html` after "See my result" | same |
| open row | `s1.html`, row Q8 open | the app, row Q2 open |
| confirm | `s1.html`, Q7 challenge | the app, Q3 challenge |
| sheet | `s1.html` sheet, high confidence | same |
| loading | kit `STATE: Loading` | throttled network |
| error | kit `STATE: Error` | route the API to 500 in Playwright |
| first paper | `states-r1/index.html#SR1` | a first-paper attempt (seed a second student locally or mock the route) |
| full marks | `states-r1/index.html#SR2` | a full-marks attempt (mocked route) |

Also capture the app at 1024x768 (tablet) for each "result" frame. Save them as `.omc/artifacts/l07/<pair>-<width>-{mock,app}.png`.

- [ ] **Step 3: Fix the drift**

Compare each pair by eye. Fix spacing, size, weight, colour and motion drift in `result.css` and the components. Note every small fix for the PR's "Changes from the mock" list. Stop and ask before any layout, flow or content change.

- [ ] **Step 4: Polish**

Invoke `/impeccable polish` on `web/src/portals/student/screens/result/` and `ChildPaperResult.tsx`. Apply its fixes. Re-run Task 16 Step 4's Vitest command and Task 17's spec.

- [ ] **Step 5: Commit**

```bash
pre-commit run --files <changed files>
git commit -S -m "fix(web): S1 fidelity drift and polish" -- <changed files>
```

### Task 19: Keep-list check

- [ ] **Step 1:** Walk K1-K30 in the running app (student and parent) and in the code. Tick each row in the PR body with the file and line that now carries it, or the decision that dropped it.
- [ ] **Step 2:** Walk every row of the frame-to-state table at 390, 1024 and 1280, and every row of the motion table with `prefers-reduced-motion: reduce` emulated (Playwright `page.emulateMedia({ reducedMotion: "reduce" })`). Confirm the fallback column.
- [ ] **Step 3:** Grep the changed files for `TODO`, `FIXME`, `test.skip`, `.only` and `it.todo`. Expected: none.

### Task 20: Signed commits, push, PR to `develop`

- [ ] **Step 1:** `git status --short --branch` shows `redesign/l07-result-s1` and nothing unstaged.
- [ ] **Step 2:** Rebase on `origin/develop`. Point `0055_mark_challenges.down_revision` at the current `develop` head, and update `tests/test_migration_mark_challenges.py::DOWN_REVISION`, the head pin in `tests/test_db_schema.py` and the chain assertion in the waitlist test to match. Re-run `PYTHONPATH=$PWD pytest tests/test_migration_mark_challenges.py tests/test_db_schema.py -v`.
- [ ] **Step 3:** Run the gate sweep last, derived from `.github/workflows/ci.yml` (never a hand list):
  - every touched pytest file
  - `tests/test_authz_matrix_complete.py`
  - every touched Vitest file plus the source-scanning gates in Task 16 Step 4
  - `npm run typecheck`, `npm run lint`, `npm run check:copy`, `npm run check:native`, `npm run build`
  - `pre-commit run --files <every changed file>`

  Check `git diff` after pre-commit: the ruff hook autofixes, so commit what it changed.
- [ ] **Step 4:** `git push -u origin redesign/l07-result-s1`.
- [ ] **Step 5:** Open the PR to `develop` (never `main`) with:
  - the keep-list table, ticked
  - the frame-to-state checklist
  - the screenshot pairs
  - "Changes from the mock"
  - the gate mutation pairs
  - the migration note: "0055 needs user approval before it runs on a shared database"
  - the dependency notes for L5, L6 and L11

  End with the attribution lines from the system reminder.

---

## Dependencies on other lanes

- **F1 (blocking):** `Binny`, `HairRows` and the `BinnyMood` type from `@/components/redesign`. The `RevealFlight` free-zone code needs F1's Binny to render at `size={120}` in a 120x132 box with the paper sheet clipped under (official geometry).
- **L5 (teacher review queue), beyond the master plan:**
  - L5 must add the label for `reason === "student_challenge"` ("Student challenged a mark") to its filter and row copy.
  - L5 must render `ReviewItemDetailDTO.challengeReason` in the side panel.
  - Task 6 edits `review_repo.py`, `review.py` and `schemas_review.py` additively. If L5 merges first, rebase.
  - Task 2's `lemely/web/scan_crop.py` duplicates the teacher crop route's render block. L5 (which adds the whole-page image endpoint) should move both teacher routes onto it, so there is one renderer.
- **L6 (upload):** `CorrectPaper.tsx` keeps navigating with `location.state` (K1). If L6 changes that state's shape, it must keep `attemptId` in it, or the live reveal falls back to the history path.
- **L11 (parent):** link `SubjectDetail` paper rows to `/parent/children/:childId/papers/:attemptId` using `SubjectPaperDTO.attemptId` (Task 6). Until then, the parent result route exists but nothing links to it.
- **L1 (Home):** the "result" moment and "Last paper" link should point at `/student/result/{index}` as today. Their first open plays the reveal.
- **Migrations:** L1, L6, L9, L11 and L12 may add migrations. Whoever merges after another rebases `down_revision` and the head pins (Task 20 Step 2).

## Needs user decision

1. **L7 edits `lemely/db/models/*`.** The master plan doesn't allow it, but the challenge needs a new table, an enum member and an import line. *Recommendation:* allow exactly these three edits. There is no existing challenge backend: self-review is per-point and judge-led, not a free-text appeal.
2. **Parent view.** No parent route renders a paper result today. *Recommendation:* build the read-only parent route in L7 (Task 15: no Binny, no reveal, no challenge), with L11 linking to it.
3. **Tablet and desktop layout.** The mock is phone-only. *Recommendation:*
   - tablet: the phone column centred at 680px
   - desktop: title row on top, then hero and next step (sticky) on the left, rows on the right
   - the reveal stays full-screen, with its content centred in a 390px stage
4. **Self-review placement.** The mock doesn't show it. *Recommendation:* a "Mark it yourself" button in the open row, opening the existing `SelfReviewPanel` in a sheet.
5. **Dropped live features:** the All/Lost/Flagged tabs (replaced by lost-first rows plus "Show all answers", kept in `?q=all`), the confidence summary strip, and long-press share on rows. *Recommendation:* drop all three as the mock does. Correct answers are no longer listed on the student screen.
6. **Delete paper placement.** The mock has no delete. *Recommendation:* a quiet "Delete this paper" text button at the foot of the page, with the same confirm and refusal copy.
7. **Integrity and provenance sidebar.** *Recommendation:* drop it for students and keep only the honesty line "Grade estimated from past boundaries." when the boundary isn't exact.
8. **Copy that can't come from data:**
   - the mock's hand-written "10-minute algebra and units set" becomes a rule: 5 minutes per answer, the topic families of the top two rows joined with "and"
   - SR2's "Try a Paper 4 next…" becomes "Mark another paper to keep it going." with the button "Mark another paper"

   *Recommendation:* accept both rules.
9. **When the reveal replays.** *Recommendation:* straight off marking, or the first open of an attempt on this device (localStorage, 50 most recent). A server-side "seen" flag would need another migration.
10. **Challenge with no class teacher.** *Recommendation:* hide the button and show "Join a class so a teacher can check your challenges." The server refuses with `no_reviewer`.
11. **Reason minimum.** The brief says 40 characters with a tick. The mock asks for 20 on low-confidence marks (below 70%) and 40 plus the tick from 70%. *Recommendation:* follow the mock (the server enforces both).

## Self-review

- **Spec coverage:**
  - full-screen hold with no Binny: Task 13
  - celebration where Binny reacts to the grade, no confetti: Tasks 10, 13, 16
  - next-step card: Tasks 9, 11
  - "Marks you can win" with scheme wording on low-confidence losses only: Tasks 3, 9, 12
  - challenge flow (confirm from 70%, 40 characters plus tick, 3 per paper): Tasks 1, 4, 5, 6, 12
  - crop route for students and parents with the full authz matrix: Tasks 2, 3, 5
  - first-run and sparse states (SR1, SR2): Tasks 9, 11, 14
  - loading and error states: Task 11
  - parent: Tasks 6, 15
  - Playwright: Task 17
  - fidelity and polish: Task 18
  - keep-list: Task 19
  - deletion: Task 16
  - PR: Task 20
- **Placeholder scan:** done. The intentional variables are `<changed files>` and `<deleted files>` in commit commands; those lists are only known once the step runs.
- **Type consistency:** checked across tasks:
  - `PaperResultService.get_result`, `get_crop_source` and `send_challenge`
  - `challenge_rule` and `challenge_block`
  - DTO fields against `paperResultTypes.ts`
  - `winRows`, `nextStep` and `visibleRows` against the components
  - `RevealOverlay({ result, onDocked })` against `PaperResultBody`
  - `useAnswerCrop` and `answerCropUrlFor`
