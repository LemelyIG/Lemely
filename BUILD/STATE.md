# STATE.md — Lemely Checkpoint File

> This file is the single resume point. On every session start (fresh or after a
> usage-limit reset), read this file FIRST, then `BUILD/STEERING.md`, then continue
> from `NEXT ACTION`. Update this file after every completed work unit, every gate
> result, every DECISION sent or resolved, and every steering message processed.
> Never rewrite history sections; only update the live fields and append to logs.

---

## BUILD (MISSION.md) — COMPLETE

The MISSION.md build is finished. On first redesign session, fill this table from the
actual build outcome (read the prior STATE content / BUILD reports / merged PRs), then
treat it as frozen history.

| Phase | Status | Milestone PR |
|---|---|---|
| (fill from completed build) | DONE | |

Do not reopen build phases. Any build-era bug found during redesign: fix in place
if trivial, otherwise log under REDESIGN → Deferred Issues.

---

## REDESIGN (REDESIGN-MISSION.md) — ACTIVE

### Live status

```
MISSION:            BUILD/REDESIGN-MISSION.md
CURRENT PHASE:      4 — Surface-by-surface redesign (Phases 0-3 DONE)
CURRENT SURFACE:    Gamification DONE (4 of 10). Next: **Teacher dashboard +
                    quiz builder** -> Parent -> Admin -> Auth -> Marketing ->
                    404/misc.
CURRENT BRANCH:     redesign/study-surfaces  (off redesign/correct-paper; per §11)
NEXT ACTION:        Phase 4, surface 5: **teacher dashboard + quiz builder**.
                    Read DESIGN.md, D4.1-D4.4 before emitting anything.

                    New since surface 4, and binding on every later surface:
                    - **`tests/unit/utilityExistence.test.ts` is the
                      resolves-to-nothing gate.** Append each migrated file to
                      `SCANNED_FILES`; the list only grows. It exists because
                      D4.1's `--font-serif` recurred as `text-display`, a class
                      defined nowhere that four `<h1>`s carried, rendering the
                      browser's default heading instead of §4.2's `display-lg`.
                      A well-formed class that resolves to nothing is invisible
                      to the token gate, the migration gate, contrast tests,
                      screenshots and axe alike.
                    - **`lib/celebration.ts` + `components/ui/celebration.tsx`
                      are the celebration register (§9.3), now implemented.**
                      Do not build a second count-up. `Celebrate` fires only on
                      an increase and never on a first observation; the
                      count-up clamps the spring's overshoot so no frame shows
                      a figure the student has not earned; reduced motion is
                      read in **JS** because index.css's global rule cannot
                      reach a rAF loop. Remaining §9.3 moments to wire in Phase
                      5: the correct-answer and marked-paper-result reveals.
                      The **leaderboard climb cannot be built** — no
                      `previousRank` on the wire (D4.4).
                    - **`npm run check:copy` now reads `.ts` as well as
                      `.tsx`.** The baseline is **67**, not comparable to the
                      pre-change 69: the like-for-like figure is 64. Widening
                      it found 9 user-facing em-dashes the gate had never seen,
                      five on surface 3, which had been reported clean.
                    - `lib/friendOutcome.ts` joins `lib/correctionOutcome.ts`:
                      thrown errors become sentences a student can act on.
                      Still never render `err.message` to a reader, and put the
                      message in the section whose action produced it.
                    - The student header now renders `XPStreak` compact from
                      real `/api/student/xp`. It is **shape-checked**, not
                      presence-checked: chrome that reads a nested field can
                      blank all 24 student routes if the body is malformed, and
                      `request<T>` is a cast, not a validation.

                    Also inherited from surface 3, and worth checking first:
                    - `tests/unit/studyNotebookMigration.test.ts` is the
                      **compat-layer gate**. Append each migrated file to
                      `MIGRATED_FILES`; the list only grows. It reads source,
                      not pixels, because a compat alias renders IDENTICALLY
                      to its Study Notebook counterpart — no screenshot or
                      contrast check can catch one.
                    - `.lm-read` (680px) and `.lm-prose` (65ch) in index.css
                      are the Read lane's column and prose measure. Gamification
                      is closer to Operate; do not reach for these by habit.
                    - `ruled-bg`/`dotted-bg`/`margin-rule`/`sticker` are the
                      §8 texture classes. `sticker` (±2° rotation) is written
                      for **achievement badges specifically** and, like the
                      celebration register, has no call site yet. §8 item 4
                      permits rotation only on genuinely decorative badges,
                      never on a status chip that must be scanned.
                    - `EmptyState`/`ErrorState` take a `marginalia` prop (the
                      Caveat layer). Use it; §12 says empty states are composed,
                      never blank.
                    - **A defect fixed on one surface is often live on
                      another** (P4.2 lesson 2, confirmed twice more on surface
                      3). Before shipping, grep the other portals for the shape
                      of anything found.
                    - **Destructive actions:** `Modal`'s `dismissible={false}`
                      is the confirmation pattern, and mutation `isError` must
                      be rendered. Surface 3 found both missing on the two
                      irreversible actions in the product while the reversible
                      ones beside them reported failure correctly.

                    New since Phase 3, inherited by every later surface:
                    - `scripts/capture_surface.mjs` is the batched visual
                      round while B4 blocks the real corpus. It STUBS the API:
                      its images are evidence about layout, never behaviour.
                      It hashes every capture and fails when two states that
                      must differ are identical — do not remove that check,
                      it caught a round where all ten images were the same
                      error screen. **P4.2 generalised it**: it now takes a
                      surface name (`node scripts/capture_surface.mjs
                      <surface> [outDir]`) and each surface registers its
                      route, states, stubs and an optional interaction in the
                      `SURFACES` map. Add an entry; do not copy the file.
                    - `toneFill()` (badge.tsx) and `subjectToneForCode()`
                      (subject-tag.tsx) are the sanctioned ways to reach a
                      pastel outside `<Badge>`/`<SubjectTag>`.
                    - `resolveCrumbTrail` (student/data.ts) feeds the student
                      header's real `<Breadcrumbs>`. Derived from
                      `resolveCrumb` so the two cannot disagree.
                    - `FileDrop` (`components/ui/file-drop.tsx`) is the kit's
                      upload control, 8 states, `default`/`compact`. Use it
                      rather than a styled `<input type="file">`.
                    - `confidenceTierFor` / `confidenceSummaryOf`
                      (`lib/markingConfidence.ts`) own confidence bucketing
                      product-wide. A bare `confidence < 0.8x` anywhere else
                      in `web/src` now fails a Python test.
                    - `correctionFailureMessage` (`lib/correctionOutcome.ts`)
                      is how a thrown error becomes a sentence for a student.
                      Do not render `err.message` to a reader.

                    **Two lessons from P4.2 that generalise, and are the
                    things to look for on every remaining surface:**
                    1. A component's docstring can state a rule the component
                       breaks. `MarkDisplay` said "numeric figures use
                       JetBrains Mono" and rendered its hero in Newsreader.
                       Read what the code does, not what it says it does.
                    2. A defect fixed on one portal can still be live on
                       another. The student marking run still has D6.13's
                       lost-on-refresh problem that the teacher console had
                       fixed architecturally. When a finding lands, grep for
                       its shape in the other three portals.

                    Standing rules Phase 4 inherits, all of them enforced:
                    - `npm run check:copy` must not grow. **67** prose
                      em-dashes remain on un-migrated screens, under the
                      widened `.ts`+`.tsx` scope P4.4 introduced (64 under the
                      old `.tsx`-only scope, down from 69); §9.8 binds the gate to
                      new/edited copy, so each surface clears its own as it
                      lands. It is not a silent exemption.
                    - Add each migrated file to RTL_CLEAN_FILES in
                      `tests/unit/rtlSafety.test.ts`. The list only grows.
                    - Stamp every emitted surface with the hallmark pre-emit
                      critique (§9.1). **13 of the 45 files in
                      `components/ui/` carry it** (counted, not estimated) —
                      stamp each as you touch it, and do not back-fill scores
                      nobody re-derived.
                    - Replace text loaders with `loading-shapes.tsx` as each
                      surface's geometry settles. ~23 remain, deliberately:
                      a skeleton must match the layout that replaces it, and
                      Phase 4 is what changes those layouts.
                    - Build-era screens still consume the compat token aliases
                      in index.css. Phase 4 migrates them surface by surface.

                    **Re-ask D1.6 before admin views.** Still open, still
                    deliberately undefaulted. Block there rather than guess.

                    **B4 blocks the e2e gate** (BUILD/BLOCKERS.md). One
                    command from the human clears it; do not kill the
                    port-8000 process unattended, it belongs to another user.
LAST UPDATED:       2026-08-14T00:05+03:00
LAST STEERING TS:   1786629365   (poll http://home-server:7532/lemely-ErBPK7TIRGD1sQP5-in/json?poll=1&since=<this>)
                    NOTE: still no inbound message from the human, ever. The only
                    entry on the topic remains my own Phase-0 selftest.
```


### Phase ledger

| Phase | Status | Completed | Notes |
|---|---|---|---|
| 0. Setup & Verification | DONE | 2026-08-13 | All 9 skills loadable; nothing needed installing. Node 26.6.0, Python 3.13.5, Playwright 1.62.1 (web/), Gemini key in gitignored `.env`, spend $0.204/$8 (image budget for this mission ≤$3). impeccable hook already `enabled`; `context.mjs` clean apart from one stale-context finding, fixed. PRODUCT.md already existed from the build era and was corrected rather than regenerated (see notes). ntfy verified in **both** directions. |
| 1. Audit | DONE | 2026-08-13 | Three legs, all read-only, `web/` verified untouched after each. Merged into `BUILD/DESIGN-AUDIT.md`; leg reports in `BUILD/audit/`. 6 critical, 14 major, 3 minor. Root cause is one thing: every token is still the build-era Material-3 palette, so zero pages are Study Notebook yet. Worse than that and independently confirmed by me: 3 fabrications on the landing page, no error boundary anywhere, no skeleton component anywhere. **Coverage is partial and stated so — nothing was verified against a rendered viewport, and 34 of 48 routes were reached by grep only.** |
| 2. Brand & Design System | DONE | 2026-08-13 | All 6 steps done. Brand strategy at `BUILD/BRAND.md`; logo hand-authored as SVG after the Gemini refine pass failed on all five named defects (D2 defaulted to ship it). DESIGN.md rewritten from scratch as the Study Notebook; index.css is its implementation with a documented temporary compatibility layer so un-migrated screens pick up the new palette instead of staying Material-3. `tests/test_design_tokens.py` pins every contrast claim and caught two real AA failures plus one greyscale failure in my own draft. Landing-page fabrications C1/C2 fixed, plus a third the audit missed (a stated 0.70 review threshold that is really 0.90). Component kit: 19 components, all 8 states, preview page at `web/dev-previews/` with its own Vite entry so the product can never ship it. Closed the audit's "no skeleton component" and "no error boundary" gaps. Three defects found by verifying rather than trusting the agent reports: RadioGroup did not actually have 8 states; the preview page was silently missing every utility used only inside a component (Tailwind source detection is rooted at the entry CSS, fixed with `@source`, CSS went 28KB→69KB); and a hover-pinning device I built emitted zero CSS and was removed rather than left to quietly pass review. |
| 3. IA & UX Flows | DONE | 2026-08-13 | All four parts done, D1.1-5 implemented. The headline is what the audit could not see from source: **neither the student nor teacher portal had ANY navigation below 820px/768px** — sidebars simply `hidden`, nothing replacing them, on a product whose own brief says students live on phones. Fixed with a shared `NavDrawer` rendering the same list as the desktop aside. Also removed two cross-portal links `RequireAuth` bounces for every role that exists (dead for everyone), and 4 dead keys in the student `crumbs` map. First-run views for student + teacher (`GettingStarted`); the parent's was already right and was deliberately left alone. Four honesty defects fixed in passing: a fabricated school name and hardcoded date on the teacher dashboard, hardcoded greetings on both, and two 'Coming soon' buttons for features that shipped. Three rules got gates rather than sweeps (`check:copy`, `rtlSafety`, `navigation`), and each found a real defect while being written. 646 unit tests (+59), typecheck/lint/both builds/pre-commit clean, no horizontal scroll at 320/375/1440. **e2e blocked by B4** — environmental, verified pre-existing at `0451e5e`, not a Phase 3 regression. See D3.22. |
| 4. Surface redesign | IN PROGRESS | — | 4 of 10 surfaces done (student dashboard, past-paper correction flow, study surfaces, gamification). **Surface 4's headline is D4.1's defect recurring in a second family: `text-display` is not a class.** Nothing defines it, the shipped bundle emits zero rules for it, and four `<h1>`s across Profile/Standings/Friends/Announcements carried it — so the product's page titles rendered at the browser's default heading in the body face, not §4.2's `display-lg` in Newsreader. Twice is a pattern, so the deliverable is a gate for the pattern (`utilityExistence.test.ts`) rather than four edits. Also: the **celebration register §9.3 describes had no implementation anywhere** and now does, with the honest omission recorded — a "leaderboard climb" cannot be celebrated because no `previousRank` exists on the wire, and inventing the movement was refused. C-9 `XPStreak` had **zero call sites product-wide**, the kit component built in Phase 2 for exactly this surface; it now fills the header pill P3.10 deleted for being a hardcoded lie, from data Phase 5 later built for real. Friends rendered `err.message` verbatim for all three mutations and put two of the three at the very bottom of the page, below every section. The leaderboard opt-out toggle's `isError` was rendered nowhere, so a failed "Hide me" left a student believing they were hidden. And **`check:copy` had never read a `.ts` file**, which hid 9 user-facing em-dashes, five of them on surface 3 after it was reported clean. See D4.4. **Surface 3's headline is two irreversible actions with no confirmation and no failure report**: deleting a flashcard deck destroyed it and every card in it on one tap, and both `useDeleteDeck`/`useDeleteCard` exposed an `isError` that nothing rendered, so a failed delete was indistinguishable on screen from one the student imagined pressing. The telling part is which mutations were covered: `addCard` and `editCard` both reported their failures carefully, and the two with no error path were the two *destructive* ones. `Modal`'s `dismissible={false}`, whose docstring names this exact case, had no call site in the product. Also: the study-plan week bar measured completed MINUTES while the count beside it counted SESSIONS, so "2 of 4 sessions done" sat next to a bar at 25% with nothing explaining the gap; that same bar animated `width`, which §9.2 forbids outright; the Read lane rendered at four different container widths; and the §8 texture classes `ruled-bg`/`dotted-bg`, written in Phase 2 *for the Read lane*, had zero call sites product-wide. See D4.3. **Surface 2's headline is a run that could fail in silence**: `streamActivity` never checked `res.ok`, so a 500 or 503 yielded zero frames, the loop fell out of the bottom, and the panel went back to reading "Ready when you are" — a student pressed the button, nothing happened, and the screen told them it was ready. Also: the student's confidence threshold was 0.85 against the backend's and the teacher's 0.90, so one mark was described two ways to the two people reading the same paper; and the mark and the grade, the two figures a student reads first, were both set in the heading face where DESIGN.md §4 puts the data face — `MarkDisplay`'s own docstring stated that rule while breaking it. See D4.2. Surface 1: Headline finding is one nothing in this build could have caught: **`--font-serif` was never a token, so ~20 call sites across five screens were rendering Georgia, not Newsreader** — the display face DESIGN.md mandates was on screen nowhere it was reached by that name. Verified in the shipped bundle before and after, not reasoned about. A missing definition fails silently where a wrong one would not: the token gate greps for raw values *bypassing* the block, and `font-serif` is a well-formed utility resolving to somebody else's default. Also: both dashboard charts drew a blank box where §11 mandates an empty state (the momentum panel's empty case is *every* student who just marked their first paper), the trend column told a one-paper student they were improving by "+0" in teal, and "Forecast" rendered a space-joined concatenation of per-subject grades under a label promising one value. See D4.1. |
| 5. Motion & data-viz | PENDING | — | |
| 6. Hardening & adaptation | PENDING | — | |
| 7. Final QA & report | PENDING | — | |

### Surface ledger (Phase 4 order)

| Surface | Status | Branch | Gates | Merged |
|---|---|---|---|---|
| Student dashboard | **DONE** | `redesign/student-dashboard` | typecheck / lint / 662 unit / check:copy 91 (flat) / both builds / pre-commit / 28 token tests: **green**. e2e: **still blocked, B4**. Visual round: 10 captures, all distinct, 0 unexpected console errors. | pending |
| Past-paper correction flow | **DONE** | `redesign/correct-paper` | typecheck / lint / 694 unit (+32) / check:copy 90 (**down from 91**) / both builds / pre-commit / 30 Python token+constant tests: **green**. e2e: **still blocked, B4** (port 8000 re-verified occupied). Visual round: 28 captures across 3 surfaces, all distinct, console errors only from the deliberately-failing states. | pending |
| Study surfaces (classifieds, flashcards, plans) | **DONE** | `redesign/study-surfaces` | typecheck / lint / 752 unit (+58) / check:copy 69 (**down from 90**) / both builds / pre-commit / 30 Python token+constant tests: **green**. e2e: **still blocked, B4** (port 8000 re-verified occupied). Visual round: 28 captures across 4 registered sub-surfaces, all distinct, console errors only from the deliberately-failing state. | pending |
| Gamification (XP, streaks, leaderboards) | **DONE** | `redesign/study-surfaces` | typecheck / lint / 812 unit (+60) / check:copy 67 under a **widened** gate (64 like-for-like, down from 69) / both builds / pre-commit / 30 Python token+constant tests: **green**. e2e: **still blocked, B4**. Visual round: 30 captures across 3 registered sub-surfaces, all distinct, console errors only from the deliberately-failing states. | pending |
| Teacher dashboard + quiz builder | QUEUED | — | — | — |
| Parent views | QUEUED | — | — | — |
| Admin views | QUEUED | — | — | — |
| Auth | QUEUED | — | — | — |
| Marketing / landing | QUEUED | — | — | — |
| 404 / misc | QUEUED | — | — | — |

### Gate status (current surface only)

```
SURFACE:            Gamification — XP, streaks, leaderboards
                    (Standings.tsx, Friends.tsx, Profile.tsx, xp-streak.tsx,
                    plus the student header pill and Announcements.tsx's h1
                    as a cross-surface fix)
BUILD COMPLETE:     yes
INSPECTION ROUND:   1 (batched, desktop 1440 + 375 together; 30 captures across
                    3 registered sub-surfaces)
FINDINGS TO FIX:    4, all fixed in one batch —
                    (a) the Level and Streak cards labelled their figures in
                        opposite orders (LEVEL above 7, but 21 above DAY
                        STREAK) while sitting side by side in one row;
                    (b) the "Your subjects" rank column had no label, so a
                        tone-coloured "3" sat beside "9 papers" inviting the
                        two figures to be read as a pair;
                    (c) the Send request button was aligned to the field
                        *wrapper*, which grows a line on error, so pressing it
                        with a bad code dropped the button below its field;
                    (d) the friend-code field spanned the full card width,
                        ~1350px at 1440, for an eight-character value.
CONFIRM ROUND:      1, all four confirmed fixed. Stopped there (§3.2 item 16).
HALLMARK STAMP:     present on Standings.tsx, Friends.tsx, Profile.tsx,
                    xp-streak.tsx, celebration.tsx. `portals/student/index.tsx`
                    already carried one and keeps it (a component was added,
                    the file was not re-emitted).
HOOK FINDINGS:      0 (impeccable design hook, every touched file)
TESTS:              812 unit (+60), all green; 30 Python token+constant tests
NEW GATE:           `tests/unit/utilityExistence.test.ts` — the
                    resolves-to-nothing gate. Every `text-`/`bg-`/`border-`/
                    `font-` name a migrated file uses must resolve through one
                    of the legitimate routes (a literal `.class` in index.css,
                    a theme variable Tailwind generates from, a Tailwind
                    built-in, an arbitrary value, an opacity modifier).
                    Written because D4.1's `--font-serif` recurred as
                    `text-display`: a class defined nowhere, emitting nothing
                    in the shipped bundle, carried by four `<h1>`s. Verified by
                    inversion on the real string. Comments are stripped before
                    scanning — the first draft failed a file on its own fix
                    note.
NEW CAPABILITY:     the celebration register (§9.3) exists in code for the
                    first time: `lib/celebration.ts` (rules, DOM-free) +
                    `components/ui/celebration.tsx` + `lm-pop`/`lm-confetti`
                    keyframes. 20 of the 60 new tests are its rules.
```

### Open DECISIONs

| ID | Question | Options | Default | Sent | Timeout | Status |
|---|---|---|---|---|---|---|
| D1.6 | Build real school-admin + platform-admin screens? None exist; both roles are routed into `/teacher` today. ~7 screens, new route subtree, un-bundles the `TEACHER_ROLES` guard `rbac.spec.ts` asserts against. | A build now / B defer, stay on `/teacher` / C scaffold routes+shells only | **none — deliberately not defaulted** | 2026-08-13T15:05Z | none | OPEN |

D1.6 carries no default on purpose: §10 says a question with no sane default must not be a
timeout question. It does not block Phase 2 or 3. Re-ask before Phase 4 reaches admin views;
if still unanswered then, that is the point to block rather than guess.

### Resolved

| ID | Outcome | When |
|---|---|---|
| D1.1–5 | **DEFAULTED — proceed as proposed.** 60-minute timeout elapsed with no reply. The five cost-free IA corrections are approved by default and are implemented in Phase 3.1. | 2026-08-13T18:10+03:00 |
| D2 | **DEFAULTED — option A, ship the hand-authored SVG mark.** 30-minute timeout elapsed with no reply. Assets are at `web/public/brand/` (mark, mono, favicon cuts). Not yet wired into `index.html`; that is Phase 6.5's strategic-omissions closeout. | 2026-08-13T18:10+03:00 |

### Steering log pointer

Full log: `BUILD/STEERING.md` (created in Phase 0).
Last processed inbound message: none from the human. The only entry on the inbound topic is
my own Phase-0 selftest (`IOd08AgAn9Hf`, ts 1786629363), and `LAST STEERING TS` is set past
it so it can never be replayed as a directive.

### Deferred issues (found during redesign, not blocking)

- **Phase 0 note — PRODUCT.md was corrected, not regenerated.** `/impeccable init` would have
  overwritten a build-era file that already carries five roles, the real product loop, the
  binding anti-references, and the evidence-on-hand list. Four edits were made instead:
  the deprecated `## Register` section became `## Modes` (impeccable v4 dropped register for
  the four visitor modes; nothing reads `## Register` any more), §4's anti-references and the
  protected notebook quality were added, and the line "layouts need not solve RTL yet" was
  replaced — it directly contradicted Phase 3.4's RTL-safety rule.
- **`DESIGN.md` at the repo root is build-era and predates the Study Notebook direction.**
  Phase 2 replaces it. Until then no surface work should read it as the token source.

---

## Update rules (for the agent)

1. Update `Live status` block on every work-unit boundary; `LAST UPDATED` always current.
2. Phase/surface ledgers: flip status only, append notes; never delete rows.
3. Gate status block is scratch space for the current surface; reset it when a surface
   merges (copy its outcome into the surface ledger first).
4. DECISIONs: add on send, move to Resolved with the answer on resolution or timeout
   (mark timeouts as "DEFAULTED").
5. `LAST STEERING TS` advances only after the message is logged AND acted on or queued.
6. Commit STATE.md with the work it describes, same commit.

### Phase 4 deliverables (for later surfaces to read)

| Artefact | Path | Note |
|---|---|---|
| Visual round | `web/scripts/capture_surface.mjs` | Batched capture while B4 blocks the real corpus. **Stubs the API** — layout evidence, never behaviour. Fails when two states that must differ are identical. **P4.2**: takes a surface name; register a new surface in `SURFACES` rather than copying the file. |
| Upload control | `components/ui/file-drop.tsx` | C-21. Real focusable `<input>` under a drop target, 8 states, `default`/`compact`. Never hand-roll a file input again. |
| Confidence bucketing | `lib/markingConfidence.ts` | The 0.90 review floor, mirrored from `lemely.core.schemas` and pinned by `tests/test_web_shared_constants.py`. The only place in `web/src` allowed to compare a confidence to a number. |
| Student-facing failure copy | `lib/correctionOutcome.ts` | Turns a thrown error into a sentence a fifteen-year-old can act on. Never render `err.message`. |
| Cross-language pins | `tests/test_web_shared_constants.py` | Python test reading web sources, for constants both languages must agree on. |
| Captures | `reports/redesign/p4-student-dashboard/` | 5 states x 1440/375. Fixture numbers, not product data. |
| Tone escape hatch | `toneFill` in `components/ui/badge.tsx` | Pastel fill+text pairing without `Badge`'s pill shape. |
| Subject colour by code | `subjectToneForCode` in `components/ui/subject-tag.tsx` | §3.8, for surfaces whose data carries a syllabus code rather than a name. |
| Student crumb trail | `resolveCrumbTrail` in `portals/student/data.ts` | Derived from `resolveCrumb`; feeds the header's real `<Breadcrumbs>`. |
| Ledger grid | `grid-subject-ledger` in `index.css` | Flex share on the meter, not the text column. |
| Celebration register | `lib/celebration.ts` + `components/ui/celebration.tsx` | §9.3 in code. `Celebrate`/`CountUp`/`Flourish`/`MilestoneSticker`. Fires only on an increase, never on a first observation, never above the target figure, reduced-motion read in JS. Do not build a second count-up. |
| Resolves-to-nothing gate | `tests/unit/utilityExistence.test.ts` | Append each migrated file to `SCANNED_FILES`. Catches a class name that emits no CSS — the one defect shape invisible to every other gate. |
| Friend-action failure copy | `lib/friendOutcome.ts` | Sibling of `correctionOutcome.ts`. Keeps the backend's own sentence where it wrote one for a human; replaces the machine text. |
| Header streak pill | `HeaderStreak` in `portals/student/index.tsx` | Real `/api/student/xp`. Shape-checked, hidden below 640px, absent while loading and on failure. |
| Captures | `reports/redesign/p4-{standings,friends,profile}/` | 30 states x 1440/375. Fixture numbers, not product data. |

### Phase 3 deliverables (for later phases to read)

| Artefact | Path | Note |
|---|---|---|
| Mobile nav | `web/src/components/ui/nav-drawer.tsx` | The only navigation that exists below 820/768px. Same list as the desktop aside, from the same code. |
| Breadcrumbs | `web/src/components/ui/breadcrumbs.tsx` | D1.5's back affordance. Collapses to one back link below `sm`. |
| Skip link | `web/src/components/ui/skip-link.tsx` | Wired in all three portals. `MAIN_CONTENT_ID` is the `<main>` target. |
| First-run panel | `web/src/components/ui/getting-started.tsx` | `done` only with evidence — no endpoint reports onboarding progress. |
| Loading shapes | `web/src/components/ui/loading-shapes.tsx` | Composed skeletons. Use these as each surface's geometry settles. |
| 404 + error screen | `web/src/portals/misc/NotFound.tsx` | Router `errorElement` on every top-level route, plus `path: "*"`. Static import on purpose. |
| Copy gate | `web/scripts/check_copy.mjs` | `npm run check:copy`. Classifier unit-tested; do not let the count grow. |
| RTL gate | `web/tests/unit/rtlSafety.test.ts` | Append each migrated file to `RTL_CLEAN_FILES`. |
| Nav gate | `web/tests/unit/navigation.test.ts` | Cross-checks every nav destination and crumb against mounted routes. |
| Greeting | `greetingFor` in `web/src/lib/utils.ts` | Both dashboards previously hardcoded the time of day. |

### Phase 2 deliverables (for later phases to read)

| Artefact | Path | Note |
|---|---|---|
| Design system | `DESIGN.md` | The source of truth. Read before emitting any UI. |
| Brand strategy | `BUILD/BRAND.md` | Meaning, not values. Wins over DESIGN.md on meaning only. |
| Tokens | `web/src/index.css` | Implementation of DESIGN.md, plus a documented temporary compat layer. |
| Contrast guarantees | `tests/test_design_tokens.py` | 28 tests. Pins every ratio DESIGN.md claims. |
| Logo | `web/public/brand/` | mark / mark-mono / mark-favicon. NOT yet wired into `index.html` — that is Phase 6.5. |
| Logo candidates | `BUILD/brand/` | 4 Gemini renders + 1 refine + the D2 contact sheet. |
| Component kit | `web/src/components/ui/` | 19 components, 8 states each. |
| Kit preview | `web/dev-previews/` | `npm run preview:kit`. Separate Vite entry; never shipped. |
| Generation script | `scripts/gen_brand_images.py` | Books spend into the real cost ledger and refuses to breach the ceiling. |

**Budget correction, carried forward:** the mission assumed an $8 Gemini ceiling.
The real one is **$4.99** (`lemely.toml:20`). Image spend this phase was $0.195 of
the $3 allowance; cumulative is **$0.399 / $4.99**.
