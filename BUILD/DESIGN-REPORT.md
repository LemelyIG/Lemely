# DESIGN-REPORT.md — the Lemely redesign

> Final report for `BUILD/REDESIGN-MISSION.md`. Written at the end of Phase 7,
> against the tree on `redesign/study-surfaces`.
>
> **How to read it.** §1 is what changed and whether the mission's own
> definition of done is met. §2 is the design system. §3 is the IA. §4 is every
> surface. §5 is the gates, with the numbers and their caveats. §6 is every
> exception and refusal, including the things this redesign deliberately did not
> build. §7 is the maintenance note — read that one before adding a page.
>
> Numbers in this report are from runs on this tree. Where a number cannot be
> reproduced from this tree, it says so instead of being quoted.

---

## 1. What this was, and what it did

The brief (§1 of the mission) was a full redesign of Lemely's UI and UX —
marketing, auth, onboarding, student, teacher, parent, school-admin and
platform-admin surfaces — with the current UI treated as disposable except for
**one protected quality: the warmth and notebook feel**. Not a reskin: empty
states, error handling, form validation, loading states and navigation were in
scope, and IA changes were permitted where they genuinely improved the
experience.

Seven phases ran: audit, brand and design system, IA and UX flows, ten surface
loops, motion and data-viz, hardening and adaptation, and this final QA pass.

**The headline is not a visual one.** The redesign replaced every token, every
face and every screen, and the notebook feel is stronger than it was — but the
most valuable thing it produced is the set of defects it found on the way, most
of which had nothing to do with appearance and none of which any gate in the
build era could see. A representative few:

- The product's **display typeface was rendering nowhere**. `--font-serif` was
  never a token, so ~20 `font-serif` call sites across five screens drew
  Georgia. A missing token definition fails silently where a wrong one would
  not, because `font-serif` is a well-formed utility that resolves to somebody
  else's default (D4.1).
- The **marketing page had no reader**. It sat inside the student portal's
  authenticated subtree, so a signed-out visitor was sent to `/login`, a signed-
  in teacher was sent to `/teacher`, and the only person who could reach it was
  the one who least needed selling (D4.8).
- **Neither the student nor the teacher portal had any navigation below
  820/768px** — the sidebars were simply `hidden`, with nothing replacing them,
  in a product whose own brief says students live on phones (D3.22).
- `UploadStatus.processing` **had never been written by any code path**, so for
  the whole duration of a mark the database said `pending`, which is also what
  it says about a scan somebody abandoned. The platform console's "uploads in
  flight" therefore counted every abandoned scan forever (D6.3).
- **`TEACHER_ROLES` bundled two roles that are opposites**, routing
  `platform_admin` onto screens whose every service returns empty for it by
  design — a blank console being indistinguishable on screen from a broken one
  (D4.10).

The recurring mechanism is worth more than any single finding: **a defect that
passes typecheck, lint, the design hook and every screenshot is invisible to
this build's gates**, and most of the above are that shape. Where a class of
defect was found, the deliverable was usually a gate that walks the tree rather
than a list of fixes, because a list only ever covers what somebody remembered
to put in it.

### Definition of done (§12), item by item

| Item | State |
|---|---|
| Every in-scope surface in the Study Notebook system; zero pages in the old language | **Met.** 10 surface loops; the compat layer's last screen migrated in surface 10. See §4 and the caveat in §6.7. |
| `DESIGN.md`, `PRODUCT.md`, logo and brand assets, component kit with 8-state previews, shared Nivo theme | **Met.** See §2. |
| All Hard Gates green product-wide; tests green; nothing functional regressed | **Met.** See §5. |
| Onboarding, empty, loading and error experiences for every role and major flow, including the marking wait | **Met.** See §4 and §6.3. |
| RTL-safe styles throughout new and edited code; light-mode tokens structured for a future dark theme | **Met**, and Phase 7 found the one class of direction-dependence that styles cannot express. See §5.4. |
| `BUILD/DESIGN-REPORT.md` and before/after gallery delivered; final PR open; completion ntfy sent | This document, plus `reports/phase-7/gallery/`. |

---

## 2. The design system

Canonical file: **`DESIGN.md`** at the repo root, 590 lines, written in Phase 2
and amended only by recorded decision since. `PRODUCT.md` holds audience, voice
and the three product lanes. `BUILD/BRAND.md` holds the brand strategy the mark
came from.

**Identity: "The Study Notebook."** Warm editorial product UI — Notion's calm
information density crossed with the physical artefact the product is actually
about, a student's exam paper and a teacher's marks on it.

- **Colour.** OKLCH throughout. Warm bone paper (`--paper`, `--paper-raised`,
  `--paper-sunk`), charcoal ink at three weights, hairlines, one warm
  terracotta accent, a washed pastel set, semantic states, product scales
  (grade bands, confidence), subject colours, and a focus ring. Every contrast
  claim in the file is pinned by `tests/test_design_tokens.py`, which parses
  `index.css` rather than restating it — a lesson from D6.7, where a hand-
  transcribed copy of the palette meant the contrast authority could measure one
  palette while the browser painted another.
- **Type.** Four faces, each with one job: **Newsreader** (display),
  **Geist** (UI and body), **JetBrains Mono** (all data, always
  `tabular-nums`), and **Caveat** for marginalia only, under a hard rule — if
  losing the text would be a problem, it is not Caveat. Inter, Roboto, Arial,
  Open Sans and Helvetica are banned outright.
- **Layout.** Flat bento with 1px hairlines, generous internal padding, a
  1200–1440px container, macro-whitespace between sections. No resting shadows;
  ultra-diffuse shadows only on floating layers. Radius 8–12px. A published
  z-index scale, which Phase 6.3 discovered had never been enforced.
- **Texture (§8).** The protected quality, made concrete: a fixed paper-grain
  overlay at 0.035 opacity, ruled and dotted background patterns for the Read
  lane, hand-drawn SVG accents, sticker-like badges.
- **Motion (§9).** Custom easings, no `linear` or `ease-in-out` on a designed
  transition, `transform`/`opacity` only, IntersectionObserver rather than
  scroll listeners, and a **celebration register** reserved for genuine wins.
  Every animation has a reduced-motion path.
- **Charts (§11).** One shared Nivo theme resolved from `:root` at runtime,
  failing closed — no chart draws until real token values resolve, because a
  chart in the wrong colours is far harder to notice than a missing one.
- **Icons (§10).** Phosphor, one weight, product-wide. No other icon library,
  and (as of Phase 7) no glyph substitutes either.

**Component kit:** 19 components with all 8 states, plus the later additions,
each with an entry on the preview page at `web/dev-previews/` — which has its
own Vite entry so it cannot ship in the product bundle.

---

## 3. IA changes, with rationale

Six IA proposals went to the human as DECISION D1 with the full page trees and
task-path step counts (`BUILD/audit/ia.md`). Items 1–5 carried a default and
were applied on timeout; item 6 was deliberately not defaulted, because it was a
scope decision rather than a correction, and was answered later.

| # | Change | Why | Outcome |
|---|---|---|---|
| 1 | Remove the "Elsewhere" nav group from the student sidebar | It linked an internal design-comparison gallery and an orphaned marketing page to every real student; nothing else linked to either | Applied, P3.1 |
| 2 | Add `/teacher/review` to the teacher sidebar | The confidence-review queue is a named positioning pillar in `PRODUCT.md` and was reachable only through conditional CTAs on two screens | Applied, P3.1 |
| 3 | Give students an in-app path to `/student/notifications` | The only entry was a push deep link, so a student without push had no way in at all | Applied, P3.1 |
| 4 | Add a 404 route and a router-level error boundary | Neither existed; a render exception white-screened the product | Applied, P3.1 |
| 5 | Consistent back/breadcrumb affordance in the teacher and parent portals | Back navigation existed on 1 of ~40 screens | Applied, P3.1. Surface 6 then found the other half of it: every child screen had ended up with *two* back links to the same place, because the breadcrumb trail was added without removing the inline back links beneath it |
| 6 | Build real school-admin and platform-admin screens | Both roles were routed into `/teacher` as an interim the mission's own scope says should end | **Answered by the human** ("fully build the required screens and completely wire them"). Built in surface 7: 7 screens, a new route subtree, `admin_repo.py` (the first service in the product with no tenant scope), `school_admin_repo.py`, two routers, two DTO modules and migration `0019` |

**Two IA changes were not in the proposal and were made because a surface loop
found them.** The marketing page moved out of the authenticated subtree into a
genuinely public route, and `/` stopped redirecting every signed-out visitor to
`/login`, because until then the product had no public page of any kind (D4.8).
The route table also moved to `src/routes.tsx`, so a node-environment test can
assert public-vs-guarded in both directions without importing `App.tsx` and
throwing on `document`.

---

## 4. Every surface

Order is the mission's own (§5 Phase 4): highest daily-use impact first. Each
row's detail is in the decision record named at the end of it.

### 4.1 Student dashboard — D4.1
Migrated the shell and `Overview`. Found that `--font-serif` was never a token,
so the display face was on screen nowhere it was reached by that name. Both
dashboard charts drew a blank box where §11 mandates an empty state — and the
momentum panel's empty case is *every* student who has just marked their first
paper. The trend column told a one-paper student they were improving by "+0" in
teal. "Forecast" rendered a space-joined concatenation of per-subject grades
under a label promising one value.

### 4.2 Past-paper correction flow — D4.2
`streamActivity` never checked `res.ok`, so a 500 or 503 yielded zero frames and
the panel returned to "Ready when you are": a student pressed the button,
nothing happened, and the screen told them it was ready. The student's
confidence threshold was 0.85 against the backend's and the teacher's 0.90, so
one mark was described two ways to the two people reading the same paper. The
mark and the grade, the two figures a student reads first, were both set in the
heading face where DESIGN.md puts the data face — in a component whose own
docstring stated that rule while breaking it.

### 4.3 Study surfaces: practice, flashcards, study plans — D4.3
Deleting a flashcard deck destroyed it and every card in it on one tap, and both
delete mutations exposed an `isError` that nothing rendered — so a failed delete
was indistinguishable from one the student imagined pressing. The telling part
is which mutations were covered: add and edit both reported their failures
carefully, and the two with no error path were the two destructive ones. The
study-plan week bar measured completed *minutes* while the count beside it
counted *sessions*. The §8 texture classes, written in Phase 2 for this lane,
had zero call sites product-wide.

### 4.4 Gamification: XP, streaks, leaderboards — D4.4
`text-display` is not a class: nothing defines it, and four page titles carried
it, so they rendered at the browser default in the body face. Twice is a
pattern, so the deliverable was `utilityExistence.test.ts` rather than four
edits. The celebration register §9.3 describes had no implementation anywhere
and now does — with the honest omission recorded: a leaderboard climb cannot be
celebrated because no `previousRank` exists on the wire, and inventing the
movement was refused. `XPStreak`, built in Phase 2 for exactly this surface, had
zero call sites.

### 4.5 Teacher dashboard and quiz builder — D4.5
`lm-head` and `lm-body` sat on the student shell's own `<header>` and `<main>`
emitting zero rules — the resolves-to-nothing shape recurring inside the gate
written to stop it, because `lm-` is the one class family the project owns
outright and the gate checked the four families Tailwind owns. The review queue
**painted doubt green**: it exists because a mark fell below the 0.90 review
floor, and it bucketed with a helper whose green band starts at 0.8. Fifteen
screens rendered a raw `error.message` at 44 sites. Four destructive actions
were confirmed by `window.confirm`, including a class delete that removes it for
every enrolled student.

### 4.6 Parent views — D4.6
DESIGN.md's banned easing was in force on every transition in the product, with
no call site naming it: Tailwind's `--default-transition-timing-function` *is*
`ease-in-out`, so all 27 bare `transition-*` call sites inherited it. Every
child screen carried two back links to the same place. All four screens rendered
a raw `error.message`, and the obvious fix (reuse the teacher's outcome module)
was wrong, because every `detail` the parent API produces is machine text,
stringified Python exceptions included.

### 4.7 Admin views — D4.10
See §3 item 6. Five spec items were refused rather than faked, and say so on
screen: school-level subscription status (no such thing exists in the schema),
"last active" (nothing records a session or a login, so the column is "Last
marked"), invited/active/inactive (none of the three exists), create/reassign/
archive (teacher-only routes, and no `archived` column at any level), and
accuracy metrics (produced by the harness into `reports/`, unreachable from a
request).

### 4.8 Auth — D4.7
The OTP failure a parent read was an enum member: the API raises
`AuthError(f"OTP verification failed: {result.value}")` and the screen rendered
`err.message` verbatim, so it said `OTP verification failed: wrong_code` — while
that file's own docstring asserted the parent "reads the actual reason rather
than a client-side guess". `Login.tsx` had been scaffolding since the build era
and said so in its docstring, shipping a card invisible against its own page
colour and a raw `error.message` that could print "401 Unauthorized" to a
fifteen-year-old. The password 401 is now deliberately vague, to close an
account-enumeration oracle.

### 4.9 Marketing and landing — D4.8
See §3. Beyond the routing, the Phase-1 audit had deleted the fabricated
*numbers* and left the *sentences*: six fabrications were still live, including
the exact "marked in 41s" figure the audit removed four sections up the same
file, a partnered-teacher free tier one screen above the placeholder saying
pricing is undecided, and WhatsApp results, which are absent from the repo
entirely. Every bullet now cites the router that implements it.

### 4.10 404 and misc — D4.9
Not a tidy-up. The sweep found **ten more product screens still in the build-era
language and 181 compat call sites**, including the whole of onboarding and the
whole placement flow — the first three screens a new account ever sees, none of
which any ledger row had claimed, though the mission names onboarding in scope
outright. The mechanism is the finding: **the gate lists only grow by hand, so a
screen no surface claims is a screen no gate reads.** Also: `DELETE
/me/devices/{id}` answered `200 {removed:false}` for a device it did not remove,
so the screen a reader opens *because* they think someone else is signed in ran
`onSuccess`, refetched, showed the row again and said nothing.

### 4.11 Motion and data-viz — D5.1, D5.2
DESIGN.md's hover rule was unimplemented on **26 elements**: they changed colour
on hover with no transition at all, so they snapped in a single frame —
invisible from every direction, because only the frames *between* two states
were wrong. Nivo hands series colours to react-spring, which parses them, so the
token-disciplined implementation would have drawn nothing; the theme resolves
off `:root` and fails closed. `MomentumDTO` shipped pre-rendered SVG path data
whose transform **clipped**, so a struggling student's line escaped the panel
and drew over the labels below.

### 4.12 Hardening and adaptation — D6.1 through D6.10
The adapt gate's first pass wrote the record without running the gate to green;
running it produced 198 findings, **three of the four defects being in the gate
itself**. The largest render-blocker in the product turned out to be 403 bytes
of nobody's code — `vite-plugin-pwa`'s default injected registration script, on
41 of 41 routes, for the whole redesign, in nobody's diff. The favicon was still
the build-era purple mark three phases after Phase 2 replaced the identity, and
the PWA manifest painted a near-black address bar over a paper page on all 48
routes: both are read by an operating system, not by a browser running our code,
so no test and no screenshot could see them.

### 4.13 Final QA — this phase
See §5.4.

---

## 5. Gates

### 5.1 The §9 Hard Gates

| # | Gate | Result |
|---|---|---|
| 1 | hallmark slop-test; pre-emit stamp on every emitted surface, every axis ≥3 | **Green**, and mechanised this phase. Two screens were found unstamped; `tests/unit/hallmarkStamp.test.ts` now enforces it |
| 2 | impeccable design-detector: zero unresolved findings on touched files | **Green.** Three standing findings on `index.css` are deliberately left; see §6.1 |
| 3 | Token discipline: no raw colours or font-families outside the token block | **Green.** Every remaining grep hit is a comment describing a fix |
| 4 | 8-state completeness on every interactive component introduced or touched | **Green**; preview page at `web/dev-previews/` |
| 5 | Responsive: four mobile widths plus desktop | **Green.** See 5.2 |
| 6 | full-output-enforcement: no placeholder patterns in the diff | **Green.** The remaining "Coming soon" chips are honest labels on features that genuinely do not exist, not placeholders for ones that do |
| 7 | Functional safety: existing tests green, nothing regressed | **Green.** See 5.3 |
| 8 | Copy rules | **Green.** `check:copy` reports 0 |

### 5.2 The adapt sweep

<!--ADAPT-->

### 5.3 Test and build gates, this tree

<!--GATES-->

### 5.4 What Phase 7 itself found

Seven findings, and the shape of them is the point: **six were in gates rather
than in screens**, and the seventh was a vocabulary defect that every gate was
structurally unable to see. Two of the six were in the gate that had been fixed
last session, and one was in the fix itself.

#### 0. The guard against measuring the wrong server could never fire

This is the one to read. BLOCKERS.md **B4** recorded that the e2e suite silently
ran against whatever already held its port. The lesson was written down, and the
same defect has now appeared twice more *inside the gates written after it*:

- **D6.10** (last session) found `adapt_audit.mjs` serving `dist/` on 4321 while
  six callbacks it imports navigated to 4319, so it only ever completed when
  something else was holding 4319 for it. The fix imported the port instead of
  restating it, and added a guard reading the spawned server's exit code before
  believing any fetch.
- **This phase** found that guard **cannot fire**. With a foreign server on the
  port and `--strictPort`, the imposter answers a `fetch` at **+164ms**, while
  our own vite needs **+577ms** to fail its bind, print `Error: Port 4319 is
  already in use`, and exit 1. The wait loop polls every 300ms and checks the
  exit code *first*: on its first pass the code is still `null`, the fetch is
  answered by the squatter, and it returns success. The exit code goes non-null
  a third of a second after nobody is looking. Measured twice on this machine
  rather than argued from the source.

It was found by this phase's own sweep quietly adopting a `vite preview` that
had been **orphaned on 4319 for an hour and forty minutes**, left behind by the
previous session, and measuring 36 surfaces against it without a word.

**Two things must be said precisely here.** First, on this occasion the adopted
server happened to serve the same `dist/` path from disk, so the bytes measured
were in fact the current build — that is luck, not the guarantee the gate
advertises, and the same process started from another branch's checkout would
have produced a clean green run about a build nobody made. Second, and for the
same reason, **the Phase 6.5 adapt number quoted in `STATE.md` (765 page-states,
0 findings) was produced while that same orphaned server held the port**; its
committed artifact exists and its numbers are internally consistent, but it
cannot claim to have measured a server it started either. §5.2's run is the
first adapt result in this project that can.

The fix is not a better post-spawn check, because an already-running server will
always answer faster than an honest one can discover it has lost. It is to
establish the precondition **before** anything is spawned, where there is no
race: if the port answers at all, refuse. That lives in
`web/scripts/serve_guard.mjs` and all four harnesses that start a preview server
call it.

**Where the orphan came from, which had to be fixed in the same breath.** The
server on 4319 was not left there by hand: **every one of these harnesses leaks
its own preview server on every run.** They spawned `npx vite preview` and, in
their `finally`, killed the handle they held — which is `npx`. `npx` runs vite
as a *child*, so vite survived, was reparented to init, and kept the port until
the machine restarted. Confirmed by measurement rather than inferred: after a
clean 25-minute adapt run, `ss -ltnp` showed a `vite preview --port 4319` with
PPID 1 and an elapsed time exactly equal to that run.

This mattered more after the guard than before it. A leaked server used to make
the *next* run silently wrong; with the guard it makes the next run fail
outright, so shipping one without the other would have traded a quiet wrong
answer for a gate that blocks every second run and reads as flakiness.
`startPreview` spawns vite's own binary, so the process the code can kill is the
process holding the port.

**And the reason it survived a phase: the pin asserted the guard's source text,
not its behaviour.** `adaptRules.test.ts` contained
`it("refuses to measure a server it did not start")`, which checked that the
string `server.exitCode !== null` appeared in the file. It did appear. It was
spelled correctly, well commented, and unreachable. The replacement starts a
real listener and asserts the harness refuses, asserts the healthy path
resolves, and asserts the guard is called *before* the spawn in all four
scripts.

#### 0b. The adapt gate counted an inline icon as a second line

The sweep that followed the guard fix reported **35 two-line-clickable findings**
that were all a single line on screen, and they were caused by this phase's own
arrow change. The rule collapses a text range's client rects into lines, because
an inline icon beside a label produces two rects on one line — and it did that
by bucketing on `Math.round(r.top)`, which is an equality on the top edge. An
icon vertically centred against text does not share the text's top: a 14px icon
on a 20px line box sits about 3px lower, so it landed in its own bucket. The
rule's own comment states the case it was meant to handle; the implementation
did not handle it.

It was latent for as long as every arrow was a `"→"` character, because a text
glyph *does* share its run's top. Replacing fourteen of them with real icons
made it visible.

**Three product "fixes" were written against those findings before the gate was
suspected**, and all three have been reverted: they were changes to real screens
made to satisfy a measurement error. That is the cost of trusting a gate's
output over its subject, and it is worth recording because the instinct that
produced it — the gate is old and the code is new, so the code is wrong — is
usually correct and was not here.

Grouping by vertical overlap is what the comment always meant. Measured in
Chromium against both implementations on the same fixtures:

| fixture | old | fixed |
|---|---|---|
| label + 14px inline icon, one line | 2 | 1 |
| label + 28px inline icon, one line | 2 | 1 |
| long label wrapping to four lines | 4 | **4** |
| wrapping label that also has an icon | 3 | **3** |

The false positives go and every true positive stays, including the case that
has both.

#### The other four

1. **The lexer six gates read the product through was partially blind.** Its
   `stripComments` treats `'` as opening a JavaScript string wherever it
   appears, and in a `.tsx` file an apostrophe also appears in JSX text — this
   product's own error idiom is "Couldn't load your classes". So it opened a
   string that ran until the next stray apostrophe anywhere below, and between
   those two points comments were not blanked and prose was scanned as code.
   **Measured before fixing: 25 of 125 `.tsx` files desynchronise**, several
   ending the file still inside a phantom string. `a11yRules.test.ts`'s own
   header warns about exactly this failure and believed it fixed — it was fixed
   for apostrophes *inside comments*, which blanking removes; the one in
   `Couldn't` is not in a comment. A second gap on the way: comments inside
   `${…}` interpolations were read as string content too. There is now one
   shared `tests/unit/support/jsxSource.ts`, where there had been four divergent
   copies across six gates, and all 125 files lex cleanly.
   **Correcting it surfaced no hidden product defect.** That is worth stating
   plainly rather than dressing up: the blindness was real, and the code
   underneath it was clean.
2. **§9 Hard Gate 1 had no reader.** The mission names a reviewer subagent as
   the stamp's enforcer, so nothing mechanical ever checked it, and two screens
   shipped unstamped under ledger rows reading DONE. The gap was already known —
   D3 recorded it and handed the fix to a convention ("stamp each as it is
   touched, rather than back-fill scores nobody re-derived", which is the right
   instruction) — and **the population it was meant to drain went from 19 to
   33**, because nothing was watching. Both screens are now critiqued and
   stamped for real; the 33 kit components are frozen in a list that can only
   shrink.
3. **A `→` in a string cannot be mirrored.** Fourteen teacher-portal labels
   ended in a literal arrow character. `rtl:-scale-x-100` transforms a box, and
   a character in a text node has no box; the bidi algorithm does not mirror
   U+2192 either. So these were not merely unflagged direction-dependent icons,
   they were the one form of direction-dependence a future `dir="rtl"` flip
   **could not have repaired** — with the gate that exists to prevent exactly
   that reporting green, because it reads styles and this is a character. The
   new rule walks the tree, and **found nine more `"← Back"` sites on its first
   run** that the hand sweep behind it had missed.
4. **`Grading.tsx` drew its pipeline in dingbats** — `"✓"`, `"●"` and `""` in a
   hand-built circle — while the kit's `ProcessingState` rendered the live run
   100 lines below and the copy under it pointed the teacher back up to the
   dingbat one. One screen, two visual languages for one concept, which
   `pipelineStages.ts`'s own docstring already names as the "roughly true" UI
   the spec forbids. `StageGlyph` is shared now, and every state carries an
   accessible name: done, not-started and failed had been announced identically.

**And one Phase-1 finding that survived the whole redesign.** Audit finding
**M12**, the full-viewport centred auth hero, "the most recognisable AI auth
shape", was still live on both signed-out screens. The P4.7 auth pass fixed the
card's colour, the error's position and the error's copy, and its docstring
lists exactly those three — so the one finding that was about the *shape of the
page* was never in that loop's list. Fixing it found that `ParentLogin.tsx`
opened with "The frame is `AuthFrame`, shared with the password screen" above
its own copy of that frame's markup, because `AuthFrame` took no prop for the
`data-portal` it needed.

Every other Phase-1 finding (C1–C6, M1–M11, M13, M14, N1, N2) was verified
closed rather than assumed; each remaining grep hit is a comment recording the
fix.

---

## 6. Exceptions, refusals and known gaps

Everything here is deliberate and recorded. None of it is an oversight.

### 6.1 Three impeccable findings on `index.css`, left standing
`--ease-spring` and `--ease-celebrate` overshoot on purpose (the celebration
register), and `ruled-bg`/`dotted-bg` are the notebook texture, which §1 names
as the one protected quality of this redesign. The mission's §3 says it wins
where it conflicts with a skill. They are not suppressed either, because a
waiver needs the human.

### 6.2 Four chart surfaces that stayed off Nivo (D5.1)
The topic-weakness heatmap (its no-data-vs-0% distinction is the one thing on
that screen that must not be got wrong, and Nivo's heatmap has no notion of it),
two labelled meters whose rows already print their value as text, `BoundaryBar`
(a bespoke positional scale), and `TrendSparkline` in table rows (one Nivo
canvas per row is a real cost, and a table cell is not a chart).

### 6.3 Things this product cannot honestly celebrate
There is **no flourish at any mark**, because confetti would require the product
to decide a mark is good, and any threshold makes its absence read as
disappointment. **A correct answer has no celebration moment**, because every
assessment path here is submit-then-mark and flashcard review is self-graded, so
there is no moment where the product tells a student they were right. **A
leaderboard climb cannot be celebrated**, because no `previousRank` exists on
the wire. Inventing any of the three was refused.

### 6.4 `Reveal` is scoped to the marketing lane
A deliberate narrowing of the mission's literal "sweep every surface" (D5.2). If
the human wants it literal, it is one prop on a handful of screens.

### 6.5 Legal links: one factual page, no policy
DECISION D6.8 timed out unanswered after nine polls and its default was applied:
`/data`, "How your data is handled", one factual page describing verifiable code
behaviour, with no terms of service and no privacy policy. The reasoning is
worth keeping: **facts about this product can be derived from this repo;
promises cannot**, and a policy is mostly promises. Found while writing it, and
recorded rather than fixed: the product has **no account-deletion path and no
retention rule** anywhere in `lemely/` — nothing purges, anonymises or expires a
scan, an attempt or an account, in a product whose users are minors.

### 6.6 No deployment of this code can send an SMS
`deps.py` wires `sms=MockSmsProvider()` unconditionally, and that provider logs
the code. This is the only route a parent has into the product. Not fixed — it
needs a gateway and credentials from the human — and deliberately not implied
anywhere in the new copy or metadata (D6.9).

### 6.7 The compatibility layer cannot die yet
Every *screen* is migrated. **17 kit components still name build-era aliases in
their own source**, none of them in the migration file lists, so no gate reads
them. This is the same "a file no list claims is a file no gate reads" mechanism
as surface 10's finding, one layer down.

### 6.8 N3, the one audit finding the redesign did not close
The Phase-1 audit's minor finding N3 — no offline state distinct from a generic
error, in a PWA — is still open. `QuizTaker` handles going offline mid-quiz;
there is no product-wide offline experience.

### 6.9 Dark mode
Not implemented and not tested, per §3.2 item 8. The tokens are structured so a
future dark theme is a token swap.

### 6.10 Numbers that cannot be reproduced from this tree
D6.1 recorded the Phase-6.1 adapt run as "745 page-states across 35 surfaces, 0
findings" and committed no artifact, so that number cannot be re-derived here
and is not carried forward. The Phase-6.5 run (765 page-states) does have a
committed artifact, but per §5.4 item 0 it ran while an orphaned server held the
port, so it cannot claim to have measured a server it started. The adapt
baseline this report quotes is §5.2's run, which is the first in this project
that can.
The Lighthouse composite score is likewise **not** used to support any claim in
this report: build-era D6.9 established that one run cannot separate *fixed*
from *fast*, and Phase 6.3 measured ±11-point swings on routes it never touched,
in both directions. Structural audits carry the performance claims instead.

---

## 7. Maintenance — how to add a page without breaking the system

**Read `DESIGN.md` first.** It is the only source of truth for tokens, faces,
spacing, motion and the chart theme; `PRODUCT.md` holds voice and lanes. Then:

1. **Pick a lane** (§2 of DESIGN.md): Persuade, Operate, or Read. The lane
   decides the page skeleton and the variation knobs you may turn (§13).
2. **Reference tokens, never values.** A raw hex, `oklch()` or `font-family`
   outside the token block is a gate failure. If you need a value that does not
   exist, lift it into the token block first.
3. **Use the kit.** If a primitive exists, use it — do not hand-roll a second
   version of a thing the kit already draws. Phase 7 found a screen drawing its
   own pipeline in dingbats a hundred lines above the kit component for it.
4. **All eight states**, and add the surface to `dev-previews/` if it introduces
   a component.
5. **Register the screen in the lists.** This is the single most repeated
   failure in this whole redesign: the capture registry
   (`web/scripts/capture_surface.mjs`), `RTL_CLEAN_FILES`, and the migration
   lists only grow by hand. A screen in none of them is a screen no gate reads,
   and that is how ten screens spent the redesign in the old language.
6. **Stamp it.** `/* Hallmark · pre-emit critique: P_ H_ E_ S_ R_ V_ */`, from a
   critique you actually performed. `hallmarkStamp.test.ts` requires it on
   anything under `src/portals/`, and a copied stamp is worse than none.
7. **Write copy that is true.** No invented metrics, no promises the code cannot
   keep, no em-dashes (`npm run check:copy`), sentence case, active-voice
   errors, and a specific failure message rather than "something went wrong".
   Where the product cannot do something, say so on screen — §6 above is full of
   places this product does exactly that, and they are among its better moments.
8. **Run the gates**: `npm test`, `npm run typecheck`, `npm run lint`,
   `npm run check:copy`, both builds, and
   `node scripts/adapt_audit.mjs --json=<path>` if you moved a layout. The adapt
   sweep takes ~25 minutes, so batch it per the mission's bounded-pass rule
   rather than running it per edit — and **always pass `--json`**, because a
   gate number with no committed artifact cannot be re-derived by the next
   person, which is how two earlier adapt results became unquotable.
   If it refuses to start, something is holding port 4319: stop it rather than
   working around it (`pkill -f "vite preview --port 4319"`). That refusal is
   deliberate and took three attempts to make real — see §5.4 item 0.

**And the meta-lesson, if you only keep one thing.** Most of what this redesign
found was invisible to every automated check the project had, and was caught by
asking a specific question of the actual artifact: what does the *shipped
bundle* contain, what does the *browser* paint, what does the *operating system*
read, what does a *screen reader* announce, and *when* was the measurement
taken. When a gate reports zero, the useful question is not whether it passed —
it is what it looked at.
