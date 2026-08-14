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
CURRENT SURFACE:    Marketing / landing DONE (8 of 10 built; admin deferred
                    behind D1.6). Next: **404 / misc** -> admin.
NEXT ACTION:        Phase 4, surface 10: **404 / misc**
                    (`portals/misc/NotFound.tsx`, plus whatever the sweep
                    finds unmigrated: `portals/settings/DeviceSettings.tsx`
                    and `NotificationSettings.tsx` are top-level routes that
                    no surface has claimed).

                    `NotFound` is the router's `errorElement` on every
                    top-level route AND the `path: "*"` catch-all, so it is
                    two screens in one file and both need states. It is a
                    **static** import on purpose (P3.1/D1.4: a lazily-loaded
                    error screen has to fetch a chunk from the origin that
                    just failed to serve one) — do not make it lazy while
                    tidying.

                    Known and deliberately left for this surface (App.tsx's
                    own note): a 404 *inside* a portal subtree loses the
                    sidebar, because the portal routes enumerate their
                    children and unmatched paths fall to the top-level
                    catch-all. The note says rebuilding it as a per-portal
                    child route is Phase 4 work "once each portal layout is
                    its final shape" — after surface 9 they all are.

                    After 404/misc, surface 7 (admin views) is the ONLY thing
                    left in Phase 4, and D1.6 is still unanswered and
                    undefaulted. **That is the point at which Phase 4 blocks
                    rather than proceeds.** Do not guess D1.6; re-ask it and
                    say plainly that the phase cannot close without it.

                    New since surface 9, and binding on every later surface:
                    - **A guard around the wrong subtree is invisible to every
                      gate.** The marketing page spent the whole build behind
                      `RequireAuth allowedRoles={["student"]}`, so the only
                      reader who could open it was a student who had already
                      signed up. Typecheck, lint and the audit all passed.
                      `tests/unit/marketing.test.ts` now asserts which
                      top-level routes are public and which are guarded, in
                      both directions; extend it rather than writing a second.
                    - **`src/routes.tsx` owns the route table now**, and
                      `App.tsx` is one line. `createBrowserRouter` touches
                      `document` at import and vitest runs the node
                      environment on purpose, so importing `@/App` in a unit
                      test throws. Import `appRoutes` from `@/routes`.
                    - **`components/ui/reveal.tsx` is the scroll-entry
                      motion**, and it did not exist before surface 9 despite
                      DESIGN.md §9 and §4 both specifying it. `lm-screen` is
                      not the same thing (it fires once on mount, so below-fold
                      content finishes animating before anyone arrives). Do not
                      build a second one. It reads reduced motion in JS at
                      mount, deliberately.
                    - **A `fullPage` capture does not scroll**, so anything
                      inside a `Reveal` photographs blank. `capture_surface`'s
                      landing surface scrolls before the shutter; any later
                      surface using `Reveal` needs the same.
                    - **The audit deleted the numbers and left the sentences.**
                      C1/C2/C3 were closed in Phase 2 and six fabrications were
                      still live on the landing page, including the exact
                      figure C1 removed, in a different slot of the same file.
                      When a claim is deleted, grep the repo for the claim, not
                      the line.

                    Standing from surface 8, still binding:
                    - **`lib/authOutcome.ts` completes the failure-copy family
                      at five.** The rule, now that all five exist: *keep the
                      backend's `detail` where a human wrote it for a human*,
                      decided per endpoint by reading the endpoint. This one
                      module does both, three lines apart. Do not copy any
                      single module's policy into a sixth.
                    - **A docstring asserting an intention is not evidence the
                      code meets it.** Second time this phase (surface 2's
                      `MarkDisplay`, now `ParentLogin`). Read what the code
                      renders, not what its comment claims.
                    - **`AuthFrame`** (exported from `portals/auth/Login.tsx`)
                      owns the signed-out frame: mark, paper, grain, column.
                    - **M9's placeholder logo was in FOUR places**, not the
                      three the audit counted. All four are now the real mark.
                    - **`capture_surface.mjs` accepts `session: null`** for
                      signed-out routes; without it the fixture session makes
                      `/login` a redirect.

                    New since surface 6, and binding on every later surface:
                    - **The motion defaults are fixed product-wide.** A bare
                      `transition-colors` now runs on `ease-out-soft` at 120ms
                      because `--default-transition-timing-function` and
                      `--default-transition-duration` were repointed in
                      `@theme`. Before that, all 27 call sites ran on
                      Tailwind's `cubic-bezier(0.4,0,0.2,1)` — the ease-in-out
                      §3.2 item 14 bans. **Do not write a named duration
                      utility**: the `--dur-*` tokens live in `:root`, not
                      `@theme`, so `duration-instant` emits nothing. Use the
                      corrected default, or `duration-[var(--dur-fast)]`.
                      Gated by `tests/unit/motionDefaults.test.ts`.
                    - **`lib/parentOutcome.ts`** completes the failure-copy
                      family. Read its header before writing a fifth: the four
                      modules differ by *audience*, and the parent one is
                      status-first rather than detail-first because every
                      `detail` the parent API emits is machine text.
                    - **A number in a coloured chip needs a label.** Third
                      occurrence in three surfaces. If the reader can plausibly
                      read it as a score, say what it counts.
                    - **Accent is the alert register on this palette.**
                      Second occurrence. Good news on `--accent-wash` reads as
                      an error; `info` is the neutral notice.
                    - `design-tokens.test.ts` does **not** strip comments, so a
                      hex value quoted in prose fails it. Reword the comment;
                      do not loosen the gate.

                    Standing from surface 5, still binding:
                    - **`utilityExistence.test.ts` now scans a FIFTH family,
                      `lm-`.** The resolves-to-nothing shape recurred a third
                      and fourth time (`lm-head`, `lm-body`, `lm-cols`), in the
                      one family the project owns outright and the gate did not
                      check. Append migrated files to `SCANNED_FILES` as usual.
                    - **`lib/teacherOutcome.ts`** joins `correctionOutcome.ts`
                      and `friendOutcome.ts`. Two entry points: a failed read
                      asks "can I retry", a failed write asks "did it save".
                      The parent surface has its own raw `error.message` sites;
                      it needs the same treatment, not a fourth ad-hoc copy.
                    - **`components/ui/confirm-modal.tsx` (C-24) is the
                      confirmation pattern.** Do not call `window.confirm` and
                      do not hand-roll a second one. Its `consequence` prop is
                      overridable *because not every destructive action is
                      irreversible* — say what is really lost.
                    - **`GradeBadge` has a third basis, `target`.** A grade
                      someone is aiming for is neither achieved nor predicted.
                    - **`Chip` is migrated and has an `info` tone.** `accent`
                      no longer means "live": on this palette it is the alert
                      register, so a healthy live state rendered as alarm.
                    - **`text-label-sm` is a real rung now**, not build-era: it
                      is `eyebrow` without the uppercase transform, for tags
                      that carry a sentence rather than a kicker. Note that
                      `normal-case` cannot override `.text-eyebrow` — equal
                      specificity, emitted earlier. Verified by byte offset in
                      the bundle.
                    - **The confidence-floor gate now matches aliases.** It
                      was defeated by a parameter named `score`. Any new
                      bucketing goes through `lib/markingConfidence.ts`.
                    - **`capture_surface.mjs` takes a per-surface `session`
                      and `profile`.** Both were hardcoded to `role: "student"`,
                      which silently redirects any non-student route.
                    - `check_copy`'s placeholder classifier was widened twice
                      (two dashes on one line; a dash alone on its line). Both
                      widenings are pinned in the strict direction too.

                    Standing rules Phase 4 inherits, all of them enforced:
                    - `npm run check:copy` must not grow. **14** prose
                      em-dashes remain, all on un-migrated surfaces (student
                      placement, announcements, parents, onboarding). §9.8 binds the gate to
                      new/edited copy, so each surface clears its own.
                    - Add each migrated file to RTL_CLEAN_FILES, MIGRATED_FILES
                      and SCANNED_FILES. The lists only grow.
                    - Stamp every emitted surface with the hallmark pre-emit
                      critique (§9.1).
                    - Replace text loaders with `loading-shapes.tsx` as each
                      surface's geometry settles.
                    - **A defect fixed on one surface is often live on
                      another.** Confirmed again on surface 5, four times over.

                    **D1.6 re-asked 2026-08-14T02:45+03:00**, logged in
                    STEERING.md. Still open, still undefaulted. Do not guess
                    it; do not idle on it either.

                    **B4 blocks the e2e gate** (BUILD/BLOCKERS.md). One
                    command from the human clears it; do not kill the
                    port-8000 process unattended, it belongs to another user.
LAST UPDATED:       2026-08-14T04:05+03:00
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
| 4. Surface redesign | IN PROGRESS | — | 8 of 10 built (admin deferred behind D1.6). **Surface 9's headline is that the marketing page had no reader at all**: `/student/landing` sat inside `studentRoute`, which `App.tsx` wraps in `RequireAuth allowedRoles={["student"]}`, so a signed-out visitor went to `/login`, a signed-in *teacher* went to `/teacher` (the page's own eyebrow reads "For CAIE teachers and their students"), `/` sent every signed-out visitor to `/login` so the product had no public page of any kind, and the one reader who could reach it was the person who least needed selling, seeing it wrapped in the student sidebar, breadcrumbs and streak pill above a hero saying "Mark a paper". It was **known and half-fixed** — D1.1 called it "orphaned inside the authenticated app" and removed the nav entry, which fixed what a student saw and left the page with no audience. Nothing could have caught it: a guard around the wrong subtree passes typecheck, lint and the design hook, which is why the fix ships with `marketing.test.ts` asserting public-vs-guarded in both directions, and why the route table moved to `src/routes.tsx` (importing `@/App` in a node-env test throws on `document`). **The second finding is that the audit deleted the numbers and left the sentences**: C1/C2/C3 closed in Phase 2, and six fabrications were still live — "marked in 41s" (the exact figure C1 removed, four sections up the same file), a partnered-teacher free tier and "No card to start" one screen above the placeholder saying pricing is undecided, QR/face/2FA attendance and replayed-minute retention (both recorded in `schemas_teacher.py` as having no backend source), WhatsApp results (absent from the repo entirely) and course payments (out of scope per PRODUCT.md). Every bullet now cites the router that implements it. Also: `Reveal` (the scroll-entry motion DESIGN.md §9 specifies and nothing implemented), the page had two left edges 40px apart, `ruled-bg` was painted over by opaque cards and drew nothing, and the Parents link was hidden below 640px on the login route whose selling point is a phone number. The capture harness failed its own round twice and was right both times. See D4.8. **Surface 8's headline is that the OTP failure a parent read was an enum member**: `verify_otp` raises `AuthError(f"OTP verification failed: {result.value}")` and `ParentLogin` rendered `err.message` verbatim, so the screen said `OTP verification failed: wrong_code` — while that file's own docstring asserted the parent "reads the actual reason rather than a client-side guess". The distinction was real; the vocabulary was never fit to show anyone. Second time this phase a docstring described the fix rather than the behaviour. `authOutcome.ts` maps the four `OtpResult` members and, three lines away, deliberately *keeps* the 429's own wording, because there a human wrote a sentence for a human — which is the failure-copy family's real rule now that five modules exist. Also: `Login.tsx` had been scaffolding since the build era and said so in its docstring, shipping a card invisible against its own page colour, a form-level error in the one position §12 rules out, and a raw `error.message` that could print "401 Unauthorized"; the password 401 is now deliberately vague to close an account-enumeration oracle; the OTP boxes were set in the display face; and audit finding M9's placeholder logo turned out to be in **four** places, not the three it counted. See D4.7. Earlier: 6 of 10 surfaces done (student dashboard, past-paper correction flow, study surfaces, gamification, teacher portal, parent views). **Surface 6's headline is DESIGN.md's banned easing being in force on every transition in the product, with no call site naming it**: §3.2 item 14 forbids `ease-in-out`, and Tailwind's `--default-transition-timing-function` *is* that curve, so all 27 bare `transition-*` call sites inherited it. Verified in the shipped bundle before and after. It is D4.1's `--font-serif` shape a fourth time with one difference that matters — those classes resolved to nothing, which `utilityExistence.test.ts` can see, while these emit the *wrong* rules, which it cannot — so the deliverable is a gate that checks the value rather than the name. Found only because the first draft of the parent shell wrote `duration-instant` and I checked the assumption instead of trusting it: the durations live in `:root`, not `@theme`, so that class emits nothing either. **The second finding is every child screen carrying two back links to the same place** — P3.1 added the breadcrumb trail without removing the inline back links beneath it. Also: all four screens rendered a raw `error.message`, and the obvious fix (reuse `teacherOutcome.ts`) was wrong because every `detail` the parent API produces is machine text, UUIDs and stringified Python exceptions included; the "Last worked" card printed "1d ago" directly above "2 days ago" from one timestamp; "6 more marks for a A"; the boundary panel put the screen's most encouraging sentence in the alert register (surface 5's finding (d) again); and an unlabelled tone-coloured percentage appeared for the third surface running. See D4.6. **Surface 5's headline is the resolves-to-nothing shape recurring a third and fourth time, inside the gate written to stop it**: `utilityExistence.test.ts` checked the four families where Tailwind owns the vocabulary, and `lm-` is the one family the project owns outright, so `lm-head` and `lm-body` sat on the student shell's own `<header>` and `<main>` in a file the gate already listed by name. Widening it found `lm-cols` on nine more elements. All six emit zero rules in the shipped bundle. **The second headline is a review queue that painted doubt green**: the queue exists because a mark fell below the 0.90 review floor, and it bucketed with its own `confidenceTone` at 0.8, so a mark at 0.85 was shown to the teacher in the same green the product uses for marks it is sure about. The gate written to prevent exactly this missed because the parameter is called `score`, not `confidence` — D6.12's lesson, where the shared condition was an assumption about naming. Also: all fifteen screens rendered a raw `error.message` at 44 sites; four destructive actions were confirmed by `window.confirm`, including a class delete that removes it for every enrolled student; a duplicate circular `Avatar` violated §6 at six call sites while the kit's squircle had one; and the portal had no texture layer at all. See D4.5. **Surface 4's headline is D4.1's defect recurring in a second family: `text-display` is not a class.** Nothing defines it, the shipped bundle emits zero rules for it, and four `<h1>`s across Profile/Standings/Friends/Announcements carried it — so the product's page titles rendered at the browser's default heading in the body face, not §4.2's `display-lg` in Newsreader. Twice is a pattern, so the deliverable is a gate for the pattern (`utilityExistence.test.ts`) rather than four edits. Also: the **celebration register §9.3 describes had no implementation anywhere** and now does, with the honest omission recorded — a "leaderboard climb" cannot be celebrated because no `previousRank` exists on the wire, and inventing the movement was refused. C-9 `XPStreak` had **zero call sites product-wide**, the kit component built in Phase 2 for exactly this surface; it now fills the header pill P3.10 deleted for being a hardcoded lie, from data Phase 5 later built for real. Friends rendered `err.message` verbatim for all three mutations and put two of the three at the very bottom of the page, below every section. The leaderboard opt-out toggle's `isError` was rendered nowhere, so a failed "Hide me" left a student believing they were hidden. And **`check:copy` had never read a `.ts` file**, which hid 9 user-facing em-dashes, five of them on surface 3 after it was reported clean. See D4.4. **Surface 3's headline is two irreversible actions with no confirmation and no failure report**: deleting a flashcard deck destroyed it and every card in it on one tap, and both `useDeleteDeck`/`useDeleteCard` exposed an `isError` that nothing rendered, so a failed delete was indistinguishable on screen from one the student imagined pressing. The telling part is which mutations were covered: `addCard` and `editCard` both reported their failures carefully, and the two with no error path were the two *destructive* ones. `Modal`'s `dismissible={false}`, whose docstring names this exact case, had no call site in the product. Also: the study-plan week bar measured completed MINUTES while the count beside it counted SESSIONS, so "2 of 4 sessions done" sat next to a bar at 25% with nothing explaining the gap; that same bar animated `width`, which §9.2 forbids outright; the Read lane rendered at four different container widths; and the §8 texture classes `ruled-bg`/`dotted-bg`, written in Phase 2 *for the Read lane*, had zero call sites product-wide. See D4.3. **Surface 2's headline is a run that could fail in silence**: `streamActivity` never checked `res.ok`, so a 500 or 503 yielded zero frames, the loop fell out of the bottom, and the panel went back to reading "Ready when you are" — a student pressed the button, nothing happened, and the screen told them it was ready. Also: the student's confidence threshold was 0.85 against the backend's and the teacher's 0.90, so one mark was described two ways to the two people reading the same paper; and the mark and the grade, the two figures a student reads first, were both set in the heading face where DESIGN.md §4 puts the data face — `MarkDisplay`'s own docstring stated that rule while breaking it. See D4.2. Surface 1: Headline finding is one nothing in this build could have caught: **`--font-serif` was never a token, so ~20 call sites across five screens were rendering Georgia, not Newsreader** — the display face DESIGN.md mandates was on screen nowhere it was reached by that name. Verified in the shipped bundle before and after, not reasoned about. A missing definition fails silently where a wrong one would not: the token gate greps for raw values *bypassing* the block, and `font-serif` is a well-formed utility resolving to somebody else's default. Also: both dashboard charts drew a blank box where §11 mandates an empty state (the momentum panel's empty case is *every* student who just marked their first paper), the trend column told a one-paper student they were improving by "+0" in teal, and "Forecast" rendered a space-joined concatenation of per-subject grades under a label promising one value. See D4.1. |
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
| Teacher dashboard + quiz builder (whole portal) | **DONE** | `redesign/study-surfaces` | typecheck / lint / 927 unit (+115) / check:copy **18** (down from 67; none in the teacher portal) / both builds / pre-commit / 31 Python token+constant tests: **green**. e2e: **still blocked, B4**. Visual round: 26 captures across 3 registered sub-surfaces, all distinct, console errors only from the deliberately-failing states. | pending |
| Parent views | **DONE** | `redesign/study-surfaces` | typecheck / lint / 980 unit (+53) / check:copy **14** (down from 18; none in the parent portal) / both builds / pre-commit / 31 Python token+constant tests: **green**. e2e: **still blocked, B4**. Visual round: 32 captures across 4 registered sub-surfaces, all distinct, console errors only from the deliberately-failing states. | pending |
| Admin views | **DEFERRED — D1.6** | — | — | — |
| Auth | **DONE** | `redesign/study-surfaces` | typecheck / lint / 1,013 unit (+33) / check:copy 14 (flat; none in auth) / both builds / pre-commit / 31 Python token+constant tests: **green**. e2e: **still blocked, B4**. Visual round: 16 captures across 2 registered sub-surfaces, all distinct, console errors only from the deliberately-failing states. | pending |
| Marketing / landing | **DONE** | `redesign/study-surfaces` | typecheck / lint / 1,061 unit (+48) / check:copy 14 (flat; none in the marketing lane) / both builds / pre-commit / 31 Python token+constant tests: **green**. No horizontal scroll at 320/375/414/768/1024/1440. e2e: **still blocked, B4**. Visual round: 4 captures + 4 in-harness assertions, all distinct, 0 console errors. | pending |
| 404 / misc | QUEUED | — | — | — |

### Gate status (current surface only)

```
SURFACE:            Marketing / landing — a new public lane
                    (`portals/marketing/`: frame, screen, data), the route
                    table split out of `App.tsx`, the `Reveal` kit component,
                    and the design-directions gallery migrated in place.
BUILD COMPLETE:     yes
INSPECTION ROUND:   1 (batched, desktop 1440 + 375 together)
FINDINGS TO FIX:    6, all fixed in one batch —
                    (a) the page had two left edges: `Section` took a `wide`
                        prop, so hero and proof sat at 1280 and loop, pillars
                        and close at 1200, jogging 40px on alternate sections;
                    (b) three proof stats in a two-column grid left the third
                        beside an empty cell, in the one band on the page that
                        has to look considered;
                    (c) `ruled-bg` drew nothing — the loop cards are opaque
                        `--paper-raised` and cover every pixel of their
                        parent, so the texture was a claim in the markup and
                        nowhere on screen;
                    (d) the Parents link was `hidden sm:inline-flex`, hiding
                        it below 640px on the phone, for the login route whose
                        entire selling point is that a phone number is the
                        whole of it;
                    (e) both hero CTAs pointed at `/login`, so "For centres
                        and teachers" was not a choice; it now scrolls to the
                        teacher case, the only destination that honestly
                        exists;
                    (f) the `full` capture photographed four blank sections,
                        because `fullPage` does not scroll and `Reveal`'s
                        observer never fired.
CONFIRM ROUND:      1 — all six confirmed fixed, no regression introduced.
                    Stopped there per §3.2 item 16.
HALLMARK STAMP:     present on all 4 emitted files (marketing frame, Landing,
                    Reveal, Directions).
HOOK FINDINGS:      0 (impeccable design hook, every touched file)
TESTS:              1,061 unit (+48), all green; 31 Python token+constant
                    tests. No horizontal scroll at 320/375/414/768/1024/1440.
NEW GATES:          `tests/unit/marketing.test.ts` — which top-level routes
                    are public and which are guarded, asserted in BOTH
                    directions (the marketing route carries no `RequireAuth`;
                    all three portals still do), ten banned copy claims pinned
                    literally, the empty pricing list, and the hero card's
                    three statements of one fact (grid, score, note) asserted
                    to agree. The three file lists grew by 5.
NEW CAPABILITY:     `portals/marketing/` (public Persuade lane, frame +
                    screen + honest data), `components/ui/reveal.tsx`
                    (scroll-entry motion, reduced-motion read in JS),
                    `src/routes.tsx` (route table, testable in node env),
                    `capture_surface` landing surface (scroll-before-shutter,
                    plus two in-harness assertions the images cannot make).
```

### Open DECISIONs

| ID | Question | Options | Default | Sent | Timeout | Status |
|---|---|---|---|---|---|---|
| D4.8 | Should the internal design-directions gallery (`/student/directions`) ship in the product? Reachable by any signed-in student, mock data, no nav entry; same shape as the kit preview Phase 2 moved behind its own Vite entry. Migrated in place either way. | A move to `web/dev-previews/` / B leave mounted / C delete | **A** | 2026-08-14T04:00+03:00 | 30 min | OPEN |
| D1.6 | **Re-asked 2026-08-14T02:45.** Build real school-admin + platform-admin screens? None exist; both roles are routed into `/teacher` today. ~7 screens, new route subtree, un-bundles the `TEACHER_ROLES` guard `rbac.spec.ts` asserts against. | A build now / B defer, stay on `/teacher` / C scaffold routes+shells only | **none — deliberately not defaulted** | 2026-08-13T15:05Z | none | OPEN |

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
| Motion defaults | `--default-transition-*` in `web/src/index.css` | A bare `transition-*` is now correct by default. Named duration utilities do not exist; use `duration-[var(--dur-fast)]`. |
| Motion gate | `web/tests/unit/motionDefaults.test.ts` | Checks the *value*, not the name — the one defect shape `utilityExistence` cannot see. |
| Parent-facing failure copy | `web/src/lib/parentOutcome.ts` | Status-first, never detail-first: every parent-API `detail` is machine text. No write helper, because the portal has no write route. |
| Cache-only subject read | `useCachedChildSubject` in `web/src/lib/hooks/useParentApi.ts` | Subscribes to the cache without ever fetching. `getQueryData` does not subscribe and is wrong for a crumb. |
| Captures | `reports/redesign/p4-parent-{children,overview,subject,weaknesses}/` | 32 states x 1440/375. Fixture numbers, not product data. |
| Public marketing lane | `web/src/portals/marketing/` | Frame + Landing + data. No `RequireAuth` anywhere in the subtree, on purpose. `/landing` is the stable path; `/` renders it for a signed-out visitor. |
| Honest marketing copy | `web/src/portals/marketing/data.ts` | Every claim carries the router that implements it. Read the header before adding a sentence. |
| Route table | `web/src/routes.tsx` | `appRoutes`, importable in a node-env test. `@/App` is not — `createBrowserRouter` touches `document`. |
| Scroll-entry motion | `web/src/components/ui/reveal.tsx` | DESIGN.md §9's fade-up, which nothing implemented before. IntersectionObserver only; reduced motion read in JS at mount. Do not build a second. |
| Public-route gate | `web/tests/unit/marketing.test.ts` | Which routes are guarded and which are not, both directions. Plus the banned-claim list. |
| Captures | `reports/redesign/p4-landing/` | 2 states x 1440/375, plus two in-harness assertions (`/` renders the page signed-out; reduced motion leaves nothing hidden) that no image could make. |

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
