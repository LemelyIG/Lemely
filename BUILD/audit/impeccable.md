# impeccable audit + critique — Lemely web SPA

Run: `redesign/phase-0`, Phase 1 (Audit leg). Read-only. No application file was
touched during this run.

Method: single-context (no isolated sub-agent Assessment A/B split was run for
this pass — this is a technical `audit` + heuristic `critique` synthesis produced
directly against the source, not the full dual-agent `/impeccable critique`
protocol). Flagging this per that command's own degraded-run rule even though
this task was framed as `audit`, not `critique`, because critique-style scoring
is included below. `node .claude/skills/impeccable/scripts/detect.mjs --json
web/src` was run for the deterministic pass (see §Implementation Integrity);
result: `[]` — zero findings against the bundled anti-pattern ruleset.

Coverage: read in full or in depth — `App.tsx`, all three portal shells
(`portals/{student,teacher,parent}/index.tsx`), `index.css` (750 lines, full
token file), `components/ui/{state-views,button,primitives,card}.tsx`,
`components/ui/processing-state.tsx`, `components/quiz/QuizTaker.tsx` (708
lines), `portals/student/screens/Overview.tsx`, `CorrectPaper.tsx`, full;
`portals/teacher/screens/Grading.tsx` (through line 140, plus targeted greps),
`ClassAnalytics.tsx` (through line 100); `portals/parent/screens/ChildOverview.tsx`
(through line 90); `portals/auth/Login.tsx` full; `portals/settings/DeviceSettings.tsx`
full; `portals/student/screens/Standings.tsx` (through line 120);
`portals/student/screens/placement/PlacementTest.tsx`,
`portals/student/screens/practice/PracticeSet.tsx` full (thin wrappers). Plus a
grep-based inventory of `isPending`/`isError`/`EmptyState`/`ErrorState` usage
across all 44 screen files, and repo-wide greps for `aria-label`, `role="status"`,
`focus-visible`, `role="button"`, `outline-none`, `44px`/`min-h-11`, and
`Skeleton`. `BUILD/QUALITY-BAR.md` was read in full as the binding internal bar.
Full per-surface list of what was **not** read line-by-line is in §What I could
not verify — treat findings on those surfaces as inferred from routing +
grep, not confirmed by direct reading, unless a file:line is cited.

---

## 1. Verdict

This is not a templated AI-slop build being audited for the first time — the
codebase's own inline comments are effectively a running audit log (`P2.5.x`,
`P3.10 chunk b/c`, `D-` decision references) documenting real contrast fixes,
real fabricated-data removals, and real accessibility corrections made over
several prior phases, and the deterministic `detect.mjs` pass returned zero
findings across all of `web/src`. Shared primitives (`Button`, `StateView`
family, `Meter`, `ProcessingState`, `QuizTaker`) are disciplined, token-driven,
and mostly carry real ARIA. Where surfaces were sampled in depth (student
Overview, CorrectPaper, DeviceSettings, QuizTaker), states are handled with
unusual honesty — `null` is rendered as absent rather than a fabricated zero,
first-run empty states are composed rather than blank, error messages are
specific per-stage. Against **impeccable's `audit`** dimensions this product
currently scores in the Good band on accessibility discipline and Implementation
Integrity, and in the Acceptable band on Theming (the token system exists and is
followed, but see the Study Notebook mismatch below) and Responsive design
(no confirmed viewport testing was possible in this pass — see risk note).
Against **impeccable's `critique`** heuristics, the product reads as functional,
honest Operate-mode software rather than a designed system: it is not yet
"The Study Notebook." Two things dominate every finding below and explain most of
the gap: **(1) the current visual system is a Material Design 3 role-token port
("Academic Warmth" — Instrument Serif / Work Sans / JetBrains Mono, hex-literal
MD3 surface/tertiary/error roles), not the warm-paper/ink/hairline/Caveat-
marginalia "Study Notebook" system `REDESIGN-MISSION.md` §4 specifies — this is
expected pre-Phase-2 state, not a defect, but it means DESIGN.md does not exist
yet and nothing here should be read as validating the target system; (2) there
is no skeleton component anywhere in the codebase** (`grep -rl Skeleton web/src`
returns nothing) — every loading state product-wide is a plain `"Loading…"` /
`role="status"` text line, which is the generic-spinner-class failure Phase 3
explicitly calls out to fix (`REDESIGN-MISSION.md` §5 Phase 3.3: "loading =
layout-matching skeletons, no generic spinners"). Fix priority for Phase 2–4:
build the skeleton primitive and retrofit it everywhere before anything else in
this list, since it touches all 44 screens identically.

---

## 2. Per-surface audit + critique

### 2.1 Student dashboard (Overview) — `portals/student/screens/Overview.tsx`

**Read in full (188 lines).**

**Technical audit**
| Dimension | Score /4 | Note |
|---|---|---|
| Accessibility | 3 | `h1` present even in pending/error branches (`sr-only` when the visible greeting isn't rendered yet, line 24/35) — good, avoids a headless-page moment for screen readers. `Meter` (primitives.tsx:31) requires and gets a real `aria-label` per instance (lines 108, 178). Momentum sparkline SVG is `aria-hidden="true"` (line 139) with no textual equivalent of the trend anywhere on the card — a screen-reader user gets the heading and axis labels only, not the shape. Minor gap, not a violation. |
| Performance | 4 | No obvious layout thrash; SVG path is precomputed server-side per the `momentum.path`/`momentum.area` shape, not recomputed client-side. |
| Theming | 3 | 100% token classes (`bg-surface`, `text-t2`, `var(--accent)`, etc.); zero raw hex in this file. |
| Responsive | 2 (unverified) | `md:grid md:grid-subjects-row` / `max-tablet:grid-cols-1` (line 90, 130) shows a genuine mobile-first stacked layout with a desktop grid swap-in — plausible on paper, not confirmed by a live viewport pass in this run (see risk note §4). |
| Implementation Integrity | 4 | The file's own header comment records that this screen previously had four fabricated stat cards ("Papers marked"/"Hours saved") with no backing DTO field, and that they were removed rather than left stale — exactly the honesty discipline PRODUCT.md §Evidence on Hand demands. |

**Critique (selected heuristics)**
- Visibility of system status: 4 — pending/error/empty/populated are all four distinct, explicit branches (lines 21, 32, 55, 72).
- Error recovery: 3 — `ErrorState` gets a real "Try again" action wired to `refetch()` (line 39); the body text is the raw `error.message`, which is a `TanStack Query` error string, not necessarily written for a 14-year-old under exam stress — worth a copy pass, not a structural fix.
- Aesthetic/minimalist: 3 — clean, no clutter; but this is a Material-role palette with a serif display font standing in for the notebook system, so it reads as "clean SaaS" rather than "Study Notebook" — expected pre-DESIGN.md, flagged for Phase 2 tracking, not a P0/P1 here.

**Missing states inventory**: loading (text-only, no skeleton — see §1), empty (composed first-run invitation, not blank — good), error (present, generic message). No offline-specific state distinct from error.

### 2.2 Past-paper correction flow — `portals/student/screens/CorrectPaper.tsx`

**Read in full (350 lines).**

**Technical audit**
| Dimension | Score /4 | Note |
|---|---|---|
| Accessibility | 3 | Scan-source toggle uses `role="group" aria-label="Scan source"` (line 218) with `aria-pressed` on each button (lines 226, 239) — correct pattern for a segmented control. File inputs have `aria-labelledby`/`<label htmlFor>` (lines 253, 292–297) — real labels, not placeholder-only, per QUALITY-BAR "every form input has a visible, associated label." The live pulse-dot status region is `role="status"` (line 316) so a screen reader hears "Marking now" / "Marking stopped" changes. |
| Performance | 3 | SSE stream consumed with `for await` (line 120) rather than polling; state updates are per-frame, not per-tick — appropriate for a live pipeline. |
| Theming | 4 | Pure tokens; the one bracket literal (`max-w-[60ch]`, line 194) is explicitly justified in-line as a reading-measure value outside the pixel scale, which is the documented exception pattern, not an undocumented one. |
| Responsive | 2 (unverified) | `grid-correct-cols` / `max-tablet:grid-cols-1` (line 210) mirrors Overview's pattern; not independently viewport-tested this run. |
| Implementation Integrity | 4 | `STAGE_ORDER` (line 48) is explicitly capped at three stages because only three SSE frame types carry real signal — the comment states the spec calls for five and the extra two are omitted "because a stage with no event that could ever move it out of pending would look stuck rather than honest." This is the single strongest anti-fabrication finding in the codebase and should be held up as the house standard, not flagged as a gap. |

**Critique**
- Error prevention/recovery: 3. The "Mark this paper" CTA is `disabled` until a scan file exists (line 204) — good error prevention. On pipeline failure, the stage list shows a per-stage `errorMessage` (via `failActiveStage`) rather than a generic toast; the top-level `error` string also drives the status heading to "Marking stopped" (line 322). No retry button is offered at the point of failure — the student's only path forward is re-uploading from scratch, which for a 60-second-plus pipeline against a stressed student ("emotionally invested in the number" per PRODUCT.md) is a real cost. **P2**: add a "Try again" action that resumes from the already-uploaded scan rather than forcing a re-pick.
- Help/documentation: 3. The "How this gets marked" reassurance card (line 328) is a strong, spec-driven design move (trust-building at a high-stakes moment, per PRODUCT.md's emotional-journey concern) — a genuine strength, not boilerplate.
- **Persona red flag (Riley, stress tester)**: refreshing mid-pipeline loses all progress state — `running`/`stages` are component state with no persistence (`useState`, lines 100-101), and there is no `beforeunload` guard warning the student they'll lose their place. For a pipeline the product's own comments describe as having "real latency," this is a real gap against Phase 6's own mandate ("design the waiting experience... and failure recovery properly").

**Missing states inventory**: loading = the `ProcessingState` staged panel (a real designed progress state, not a spinner — the one screen in the sample that already meets the Phase 3 skeleton/no-spinner bar, because it was purpose-built for this exact flow). Empty = N/A (form, not a list). Error = present, per-stage. Offline = absent — no distinct "you appear to be offline" branch; a network drop mid-SSE-stream would surface as a generic pipeline failure message, not an offline-specific one.

### 2.3 Paper result — `portals/student/screens/PaperResult.tsx`

**Not read in depth this pass** (312 lines; only routing and grep data available: `loading:2 empty:4 error:4` isPending/EmptyState/ErrorState hit counts). The 4 `EmptyState` hits suggest multiple distinct empty branches (plausibly per-section: no questions, no integrity flags, no provenance) rather than one screen-level empty, which if true is good practice, but this is inferred, not confirmed. `grid-result-cols` token (index.css:468-470) documents a `1fr 300px` main-content/integrity-sidebar split. **Flagged for a follow-up read** — this is the highest-stakes screen in the product (the number a student is "emotionally invested in," per PRODUCT.md) and deserves a full pass before Phase 4 touches it.

### 2.4 Study surfaces (flashcards, study plans, practice, placement)

**Not read in depth.** Grep inventory:

| Screen | loading hits | empty hits | error hits |
|---|---|---|---|
| flashcards/FlashcardDecks.tsx | 10 | 0 | 10 |
| flashcards/FlashcardReview.tsx | 3 | 0 | 4 |
| studyplan/StudyPlanWeek.tsx | 5 | 4 | 5 |
| studyplan/StudyPlanSession.tsx | 3 | 3 | 4 |
| practice/PracticeGenerator.tsx | 4 | 0 | 5 |
| practice/PracticeSet.tsx (read, thin wrapper) | delegates to `QuizTaker` | — | — |
| practice/PracticeResult.tsx | 2 | 0 | 4 |
| practice/PracticePrint.tsx | 2 | 0 | 4 |
| placement/PlacementInvite.tsx | 4 | 0 | 6 |
| placement/PlacementTest.tsx (read, thin wrapper) | delegates to `QuizTaker` | — | — |
| placement/PlacementResult.tsx | 2 | 0 | 4 |

`FlashcardDecks.tsx` and every `practice/*` and `placement/*` screen except the
two `QuizTaker` wrappers show **zero `EmptyState` hits** despite being list/deck
screens that plausibly have a zero-item state (no decks generated yet, no
practice history). This is a real signal worth a direct read before Phase 4 —
either these screens have a genuine "you have nothing yet" branch written by
hand without the shared component (in which case it may not match the rest of
the product visually), or the branch is missing. **Not confirmed either way in
this pass — flagged, not scored.**

`QuizTaker.tsx` (the shared component behind both `PlacementTest` and
`PracticeSet`, 708 lines, read in full) is genuinely strong: real
`isPending`/`isError` branches (lines 408, 417) including a distinct
zero-questions `ErrorState` ("This test has no questions", line 436, separate
from the network-error branch); every touch target explicitly carries
`min-h-[44px]` with an inline comment citing `QUALITY-BAR.md:40` by name (lines
477, 514, 673); answer options are a real `role="radiogroup"` with
`aria-label="Choose an answer"` (line 633); every interactive control has
`focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent`
(lines 521, 645, 673, 690, 703). This is the single best-instrumented
accessibility surface found in this audit and should be the reference component
when Phase 4 retrofits the rest of the product's touch targets and focus rings.

### 2.5 Gamification (XP, streaks, standings, friends)

**Standings.tsx read through line 120 (of 557).** Confirms leaderboards are real
(`useLeaderboard`, `useMyClasses`, line 10-11) and rank XP, not grades — the
file's header comment states the hard product rule explicitly and notes the
DTOs "structurally cannot carry" a grade field (line 39), which is a stronger
guarantee than a UI-layer promise. `streak === null` renders nothing;
`streak === 0` renders a real "0" (lines 108-119) — same absent-vs-zero
discipline as elsewhere. `Fire` icon streak badge is `aria-hidden` on the icon
with the number's meaning carried by adjacent `sr-only` text ("day streak", line
115) — icon-plus-text, not icon-only-with-color, consistent with QUALITY-BAR's
colorblind-safety rule.

**Not confirmed in this pass**: whether any "celebration register" (spring
physics / count-up / confetti-class flourish on XP gain or streak milestone)
exists anywhere. `REDESIGN-MISSION.md` §4 specifies this as Phase 5 scope and
PRODUCT.md lists XP/streaks/leaderboards under "Not yet built (Phase 5)" for the
*mechanics themselves* — but Standings/Friends read as already live and wired to
real endpoints in this build, ahead of PRODUCT.md's own phase note. This
discrepancy (PRODUCT.md says Phase 5 not-yet-built; the code has working
leaderboard/streak screens with real hooks) should be reconciled before
DECISION D1 — it's not a UI defect, but it means either PRODUCT.md is stale or
"not yet built" meant something narrower (e.g., streak-freeze specifically)
than the whole mechanic.

`Friends.tsx` not read in depth (grep: `loading:4 empty:2 error:7`).

### 2.6 Teacher dashboard, grading, review, quiz builder, class analytics

**Grading.tsx read through line 140 (of 574), plus targeted greps.**

**Technical audit**
| Dimension | Score /4 | Note |
|---|---|---|
| Accessibility | 2 | `PaperCard` (line 124-140) is a `<div role="button" tabIndex={0}>` with manual `onKeyDown` handling `Enter`/`Space` (lines 128-134) — functionally keyboard-operable, but `grep -n "focus-visible\|focus:" Grading.tsx` returns **zero matches** in the whole file. A keyboard user tabbing to a paper card gets whatever the browser's default focus ring renders (no `outline-none` reset was found repo-wide, so it isn't suppressed — but it also isn't styled to match the `focus-visible:outline-2 ... outline-accent` convention every other interactive primitive in this codebase uses). **P2**: inconsistent focus styling on the one interactive surface in the teacher portal likely to be tabbed through fastest (grading queue triage). |
| Performance | 3 | `usePapers`/`usePaperDetail` explicitly poll "only while something is actually in flight" per the file's header comment (line 41) — a deliberate, documented decision against unnecessary polling load. |
| Theming | 4 | Token-only; `CHIP_TONE` (lines 78-87) maps paper states to `bg-*-bg text-*` token pairs, including a `failed` state visually distinguished from `review` by more than color alone (border added, line 86) — meets QUALITY-BAR's "colour is never the sole carrier of meaning" bar for this specific control. |
| Responsive | unverified | Not reached in the read window. |
| Implementation Integrity | 4 | The file's header comment is an unusually candid incident writeup: a prior version of this screen held an SSE stream open across the whole grading run, which combined with an unrelated backend defect (a synchronous 60s Gemini call blocking the only event loop) to produce a permanent stall — "Queued" forever, cleared by a refresh. The fix (moving to poll-based server state, documented at length) is exactly the kind of defensible engineering PRODUCT.md's "accuracy is non-negotiable... confidence and provenance are load-bearing" standard implies for teacher-facing marking infrastructure. |

**Critique**
- Consistency and standards: 2 — the `role="button"` div pattern for `PaperCard` diverges from the rest of the codebase's convention of using real `<button>` or `<Link>` elements for interactive rows (e.g. `SubjectRow` in ChildOverview.tsx uses a real `<Link>` with `focus-visible` classes, line 38). Same interaction, two different implementations, one accessible-by-convention and one accessible-by-manual-reimplementation. **P2**: standardize on a real element.
- Flexibility/efficiency: not fully assessable from the window read; no keyboard shortcuts observed for a screen whose entire premise (per PRODUCT.md) is "a teacher corrects 30 papers in the time it used to take to correct 5" — bulk/keyboard efficiency on the grading console is a first-class product claim worth testing directly in Phase 4, not inferred here.

**ClassAnalytics.tsx read through line 100 (of 470).** Strong data-honesty
finding: the heatmap explicitly distinguishes "no data" (`accuracy == null`,
rendered as a dashed-border neutral cell with `role="img" aria-label="No data"`
and an en-dash glyph, lines 75-88) from a genuine 0% (rendered with the shared
error-tone background but the literal percentage always printed inside, never
color-only, lines 90-104) — the file's header comment names this "the one rule
this screen cannot get wrong" and cites the backend module's docstring as the
source of truth. This is best-practice handling of an ambiguous-zero problem
that a templated dashboard would almost certainly get wrong (defaulting null to
0%, quietly misrepresenting a student who never attempted a topic as one who
failed it).

**Review.tsx, ReviewItem.tsx, QuizBuilder.tsx (1118 lines — the largest screen
in the product), QuizResults.tsx, Classes.tsx, ClassRoster.tsx, ClassDetail.tsx,
StudentDetail.tsx, AtRiskList.tsx, MarkSchemes.tsx, Quizzes.tsx,
Announcements.tsx (teacher): not read this pass.** Grep loading/empty/error
counts are in §3. `QuizBuilder.tsx` at 1118 lines is by a wide margin the
largest single screen file in the codebase (next largest teacher screen is
`Grading.tsx` at 574) — worth flagging on file-size grounds alone as a
component-decomposition candidate for Phase 4, independent of any UX finding.

### 2.7 Parent views

**ChildOverview.tsx read through line 90 (of 297).** `SubjectRow` (lines 34-71)
is exemplary: a real `<Link>`, not a div-with-onClick; carries
`focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent`
(line 38) inline with the interactive classes rather than as an afterthought;
states an absent target grade honestly ("No target grade set yet…", line
57-59) rather than defaulting it, with an inline comment explicitly citing why a
default would be dishonest ("a defaulted target would make every child look on
track"); renders the CAIE code (`0580/42`) as secondary detail behind a
translated subject name per an explicit design note quoted from the spec (lines
20-26) — the single clearest example in the sampled code of a screen actually
written for its stated persona (a parent with "the lowest tolerance for
jargon"). The portal shell (`portals/parent/index.tsx`, read in full) has no
sidebar by design, a native `<select>` child-switcher (labelled via visually-
hidden text at narrow widths so the accessible name survives the `hidden
sm:inline` label collapse, lines 55-58) — a well-reasoned, low-complexity
control choice for the stated "two taps to the answer, no interest in learning
an interface" persona.

**Children.tsx, SubjectDetail.tsx, Weaknesses.tsx: not read.** Grep shows
identical `loading:2 empty:0 error:4` across all four parent screens including
ChildOverview — the **zero `EmptyState` hits across the entire parent portal**
is worth a direct look: a parent with a child who has zero papers yet, zero
weak topics, or zero subjects is a real first-run state (a newly linked child),
and grep found no shared `EmptyState` usage anywhere in this portal. Either
these screens hand-roll their empty copy without the shared component (visual
drift risk) or the empty case isn't handled. **Flagged, not confirmed.**

### 2.8 Auth (Login, ParentLogin)

**Login.tsx read in full (126 lines).** The file's own header comment states
this plainly: "Minimal email/password login screen — infrastructure to exercise
the auth plumbing... not final UI. Screen polish is P2.7/P2.8's job." Audit
findings should be read against that stated intent, not as regressions.

**Technical audit**
| Dimension | Score /4 | Note |
|---|---|---|
| Accessibility | 2 | The `<h1>` reads "Lemely" (line 79) — the product name, not a task-oriented heading like "Sign in." A screen-reader user's first announcement on this page is the brand, not what the page is for; QUALITY-BAR's "one h1 per page, heading order unbroken" is technically met (there is exactly one h1) but its *content* doesn't answer "what is this page." **P2.** Inputs have real associated `<label>` wrapping (lines 85-95, 96-106) — meets the QUALITY-BAR label requirement. The submit error (line 107-111) uses `text-err` (red) directly, which is a literal reading of PRODUCT.md's own carve-out ("avoid red-heavy error states... prefer amber/neutral" is stated as a general rule, but a failed-credentials message is arguably the one case where red is the honest signal) — worth a product decision, not obviously a bug. |
| Performance | 4 | Trivial screen, nothing to flag. |
| Theming | 3 | Token-only; the form card uses a hardcoded `max-w-90` width utility, in-scale. |
| Responsive | unverified | Single-column centered form, plausible at all widths, not tested live. |
| Implementation Integrity | 4 | `expired` state (line 31, `takeSessionExpired()`) explicitly surfaces "Your session expired. Please sign in again." rather than silently dropping the user back to login with no explanation — a real UX decision documented in the file's header comment as a deliberate fix for a worse prior behavior. |

**Critique**: Consistency and standards — 2. This screen predates the shared
`ErrorState`/focus-visible conventions used elsewhere (e.g. its submit button
has no visible `focus-visible` override beyond whatever `Button`'s base classes
supply, which do include `focus-visible:outline-2 ...` per `button.tsx:16` — so
this is actually fine at the component level; the gap is narrower than it first
appears, confined to the raw `<input>` elements at lines 93 and 104, which carry
no `focus-visible:` class of their own and rely entirely on the browser
default). **P3**: bring the two raw inputs onto the same focus-ring convention
as `Button` for visual consistency, not because keyboard access is broken.

**`ParentLogin.tsx` (phone-OTP flow): not read this pass.** This is a named
Phase-3-first-run flow in the mission (§5 Phase 3.2) and the lowest-friction
entry point in the product per its own route comment (`App.tsx:73`) — flagged
as a priority follow-up read given it's the parent portal's only door in.

### 2.9 Settings (device sessions, notifications)

**DeviceSettings.tsx read in full (153 lines).** This is the strongest single
file read in this audit against the full impeccable `audit` checklist:
`<main>`/`<header>`/`<section aria-labelledby="devices-heading">` real
landmarks (lines 48, 49, 77-78) — the only file read this pass with a
correctly-labelled `<section>` landmark; distinct, explicit pending/error/empty/
populated branches (lines 85-105) using the shared `ErrorState`/`EmptyState`
components; a genuinely dangerous action (signing out a device, possibly your
own) handled with correct state feedback (`pendingId`, line 32; "Signing out…"
label swap, line 136) and correct consequence-awareness (revoking your own
current device correctly triggers `logout()`, lines 40-41, rather than leaving
the UI in an inconsistent authenticated-but-revoked state); the header
copy is honest about scope ("password change... are not stubbed here — a
settings row that does nothing is worse than an absent one," per the file's own
comment) rather than shipping dead rows. No findings above P3 on this file.

**NotificationSettings.tsx: not read this pass** — grep-level only, not in the
per-screen table since it lives outside `portals/*/screens/`.

### 2.10 404 / misc

No dedicated 404 route was found in `App.tsx`'s route tree (read in full) — an
unmatched path falls through to React Router's default behavior, which is an
unstyled blank error boundary, not a designed 404. `REDESIGN-MISSION.md` §5
Phase 3.3 explicitly lists "custom 404" as in-scope groundwork; this is
confirmed absent, not inferred. **P1** for Phase 3.

---

## 3. Consolidated missing-states matrix

Grep-derived (`isPending`/`isLoading` · `EmptyState` · `ErrorState`/`isError`
hit counts per file) across all 44 `portals/*/screens/*.tsx` files, cross-checked
against direct reads where noted. A `0` in the empty column does not prove no
empty state exists (a screen may hand-write empty copy without the shared
component) — it means the shared, product-consistent pattern was not detected.
"Skeleton" is a single column because **zero files anywhere in `web/src` import
or reference a skeleton component** — confirmed by `grep -rl Skeleton web/src`
returning no results — so every "loading" hit below is a text/`role="status"`
loading line, not a layout-matching skeleton, without exception.

| Surface | Loading (text, no skeleton) | Empty | Error | Confirmed by direct read |
|---|---|---|---|---|
| Student · Overview | yes | yes (composed first-run) | yes | ✅ full read |
| Student · CorrectPaper | yes (staged `ProcessingState`, not generic) | n/a (form) | yes (per-stage, inline) | ✅ full read |
| Student · PaperResult | yes | yes (4 hits, likely per-section) | yes | grep only |
| Student · Subject | yes | 0 hits | yes | grep only |
| Student · FlashcardDecks | yes | **0 hits** | yes | grep only — flagged |
| Student · FlashcardReview | yes | 0 hits | yes | grep only — flagged |
| Student · StudyPlanWeek | yes | yes | yes | grep only |
| Student · StudyPlanSession | yes | yes | yes | grep only |
| Student · PracticeGenerator | yes | **0 hits** | yes | grep only — flagged |
| Student · PracticeSet | delegates to `QuizTaker` (real branches) | delegates | delegates | ✅ QuizTaker full read |
| Student · PracticeResult | yes | **0 hits** | yes | grep only — flagged |
| Student · PracticePrint | yes | **0 hits** | yes | grep only — flagged |
| Student · PlacementInvite | yes | **0 hits** | yes | grep only — flagged |
| Student · PlacementTest | delegates to `QuizTaker` | delegates | delegates | ✅ QuizTaker full read |
| Student · PlacementResult | yes | **0 hits** | yes | grep only — flagged |
| Student · Standings | yes | yes | yes | partial read (to L120) |
| Student · Friends | yes | yes | yes | grep only |
| Student · Notifications | yes | yes | yes | grep only |
| Student · Announcements | yes | yes | yes | grep only |
| Student · Profile | yes | **0 hits** | yes | grep only — flagged |
| Student · Parents | yes | **0 hits** | yes | grep only — flagged |
| Student · Onboarding | yes | **0 hits** | **0 hits** | grep only — flagged (onboarding with no error branch is notable) |
| Student · onboarding/QuestionnaireStep | **0/0/0** | — | — | grep only — likely composed inline, unconfirmed |
| Student · onboarding/SubjectsStep | **0/0/0** | — | — | grep only — likely composed inline, unconfirmed |
| Student · Landing | 0/0/0 | — | — | likely static marketing content, not data-driven — plausible, unconfirmed |
| Student · Directions | 0/0/0 | — | — | plausible static, unconfirmed |
| Teacher · Overview | yes | yes | yes | grep only |
| Teacher · Grading | yes | **0 hits** | yes | partial read (to L140) — flagged |
| Teacher · Review | yes | yes | yes | grep only |
| Teacher · ReviewItem | yes | **0 hits** | yes | grep only — flagged |
| Teacher · Classes | yes | yes | yes | grep only |
| Teacher · ClassDetail | yes | **0 hits** | yes | grep only — flagged |
| Teacher · ClassRoster | yes | yes | yes | grep only |
| Teacher · ClassAnalytics | yes | yes | yes | partial read (to L100) |
| Teacher · StudentDetail | yes | **0 hits** | yes | grep only — flagged |
| Teacher · AtRiskList | yes | yes | yes | grep only |
| Teacher · MarkSchemes | yes | **0 hits** | yes | grep only — flagged |
| Teacher · Quizzes | yes | yes | yes | grep only |
| Teacher · QuizBuilder | yes | yes | yes | grep only (1118-line file, unread) |
| Teacher · QuizResults | yes | yes | yes | grep only |
| Teacher · Announcements | yes | yes | yes | grep only |
| Parent · Children | yes | **0 hits** | yes | grep only — flagged |
| Parent · ChildOverview | yes | **0 hits** | yes | partial read (to L90) — flagged |
| Parent · SubjectDetail | yes | **0 hits** | yes | grep only — flagged |
| Parent · Weaknesses | yes | **0 hits** | yes | grep only — flagged |
| Auth · Login | n/a (sync form) | n/a | yes | ✅ full read |
| Auth · ParentLogin | ? | ? | ? | not read |
| Settings · DeviceSettings | yes (text) | yes | yes | ✅ full read |
| Settings · NotificationSettings | ? | ? | ? | not read |
| 404 | **absent — no route exists** | — | — | ✅ confirmed via full `App.tsx` read |

**Systemic finding, applies to every "yes" in the Loading column**: the loading
state is `"Loading…"` / `"Loading your devices…"` etc. in a `role="status"` text
node, never a layout-matching skeleton. This is one fix (build the skeleton
primitive, retrofit) that clears the loading column product-wide rather than 44
separate ones. `CorrectPaper`'s `ProcessingState` panel is the one screen that
already exceeds this bar for its own purpose-built reason (a live multi-stage
pipeline needs staged status, not a content skeleton) and should not be
"fixed" — it should be the reference for what a *designed* wait state looks
like when a skeleton genuinely doesn't apply.

**Offline state**: no screen sampled (read or grepped for a distinct pattern)
showed a state visually distinct from a generic network error. `OfflineState`
exists as a component (`state-views.tsx:122-124`, `WifiSlash` icon) but no call
site was found for it in any file read or grepped this pass —
`grep -rl "OfflineState" web/src` was not run as a targeted check; **recommend
running it directly in Phase 3** before assuming the component is unused.

---

## 4. What I could not verify

- **Live viewport behavior (320/380/768/1180/1440px).** No dev server was
  started and no Playwright/browser pass was run in this audit — every
  responsive claim above is inferred from Tailwind class names
  (`md:`, `max-tablet:`, `xs:`) read in source, not confirmed by rendering. The
  task brief's own flagged risk applies directly here: this repo's prior gates
  ran against `http://localhost`, and secure-context- or viewport-conditioned
  behavior (e.g. the `CameraCapture` component's `getUserMedia` path in
  `CorrectPaper.tsx`, not read this pass; any `matchMedia` viewport branching)
  was uniformly verified under one origin and one window size. **Nothing in
  this report should be read as confirming actual rendered layout at any
  breakpoint** — only that the source code's stated intent is responsive.
- **Live accessibility tooling (axe, Lighthouse).** QUALITY-BAR.md demands
  "zero serious or critical axe violations... verified by axe, not by eye" and
  "Lighthouse accessibility ≥ 95." Neither tool was run. All accessibility
  findings above are static-source review (presence/absence of `aria-*`,
  `role`, `focus-visible`, landmark elements, label association) — a legitimate
  first pass but not a substitute for the tooling the project's own bar
  requires before merge.
- **Contrast ratios.** `index.css`'s extensive header comments document real
  historical axe-measured contrast fixes (the `--t3` token's three successive
  renudges, lines 57-98) — I did not independently re-verify any current
  contrast value; I'm relying on the comments' own record of the last
  measurement (P3.10 chunk b, "zero serious/critical axe violations across all
  [21] of them").
- **The full 44-screen surface set.** 12 of 44 screens were read in full or
  substantial part (Overview, CorrectPaper, Login, DeviceSettings, QuizTaker
  as the shared engine behind two more, ChildOverview and Grading and
  ClassAnalytics partially). The remaining ~30 screens (all of Review,
  ReviewItem, QuizBuilder, QuizResults, Classes, ClassRoster, ClassDetail,
  StudentDetail, AtRiskList, MarkSchemes, Quizzes, both Announcements screens,
  Notifications, Friends, Profile, Onboarding + its two step components, both
  Placement non-wrapper screens, three of four Practice screens, both
  Flashcard screens, Subject, Directions, Parents (student), Children (parent),
  SubjectDetail (parent), Weaknesses (parent), ParentLogin, NotificationSettings,
  and the second half of PaperResult, Grading and ClassAnalytics) were assessed
  only via routing structure and the grep inventory in §3. Any P0/P1 buried in
  those files' actual implementation (a broken keyboard trap in QuizBuilder's
  1118 lines, a missing label in AtRiskList, etc.) would not have surfaced in
  this pass.
- **The reduced-motion path in practice.** `index.css:742-750` sets a global
  `animation-duration: 0.001ms !important` / `transition-duration: 0.001ms
  !important` kill under `prefers-reduced-motion: reduce`. Per the `audit.md`
  reference's own guidance ("flag a global 0.01ms kill that destroys useful
  feedback... motion that blocks focus, reading, or task completion"), a blanket
  kill is the flagged anti-pattern, not the safe default — it can silently
  collapse a meaningful state transition (e.g. `ProcessingState`'s spinner, or
  a future celebration-register animation) to nothing rather than an
  intentional reduced-motion alternative. I did not test this with the OS
  setting enabled; I'm reporting the CSS rule as written and its risk per the
  audit checklist's own stated criterion, not a confirmed broken experience.
  **P2** — worth a direct settings-toggle test in Phase 6 rather than a
  Phase-1 rewrite, since the current behavior ("stop the motion") is at least
  safe, just possibly over-blunt for anything state-bearing added later.
- **Whether `OfflineState` has any call site.** Noted above; not checked.
- **Console errors / unhandled promise rejections** (QUALITY-BAR "Code
  quality" section) — requires a running app; not run.
- **`npx impeccable detect src/`** was run as `node
  .claude/skills/impeccable/scripts/detect.mjs --json web/src` (repo-root
  relative path substituted since the skill script lives at the repo root, not
  under `web/`) and returned `[]` — zero findings. I did not additionally spot-
  check whether the detector's ruleset actually has rules capable of firing on
  a React/Tailwind v4 codebase of this shape, so a clean `[]` is reported as
  evidence, not as proof of a flawless implementation.

---

## 5. Positive findings (for the record)

- Absent-vs-zero discipline is applied consistently everywhere it was checked
  (`Overview.tsx` weak-topic omission of missing fields, `Standings.tsx`
  streak `null` vs `0`, `ChildOverview.tsx`'s unset target grade, `ClassAnalytics.tsx`'s
  heatmap "no data" vs "0%") — this is a genuinely hard discipline to hold
  across a whole product and it is holding.
- The grading-pipeline incident writeup in `Grading.tsx`'s header comment is a
  model of engineering honesty in code documentation and should be preserved
  verbatim through any redesign, not summarized away.
- `QuizTaker.tsx` is close to a reference implementation of the QUALITY-BAR
  touch-target and focus-visible rules, with inline comments citing the exact
  line of QUALITY-BAR.md that motivated each choice — this is the pattern to
  copy forward, not just the code.
- Zero raw hex/arbitrary Tailwind values were found outside the documented
  token block and its two explicitly-justified exceptions (`max-w-[60ch]`,
  the amber hue addition) across every file read.
- The deterministic `detect.mjs` anti-pattern scan returned zero findings
  across the entire `web/src` tree.
