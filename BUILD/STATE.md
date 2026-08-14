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
CURRENT PHASE:      **4 COMPLETE — all 10 surfaces built.** Next is Phase 5.
CURRENT SURFACE:    admin views DONE (10 of 10). D1.6 delivered in full.
NEXT ACTION:        **Phase 5 - Motion & data-viz pass.** Phase 4 is closed;
                    nothing in Phase 5 depends on the admin surface.

                    Read REDESIGN-MISSION.md Phase 5 before starting. Four
                    parts: the motion sweep across every surface, the
                    celebration register end to end, every chart on the shared
                    Nivo theme, and a `prefers-reduced-motion` audit.

                    **Nivo is not installed yet.** §4 decided it
                    (`@nivo/*`, animated by default, themed from DESIGN.md
                    tokens) and Phase 5.3 needs `nivoTheme.ts` built from the
                    token block. Verify the dependency lands in package.json
                    before importing it (taste-skill dependency rule).
                    `components/ui/chart-frame.tsx` and `trend-sparkline.tsx`
                    already exist and are what a Nivo chart has to sit inside
                    or replace, so read both first.

                    Standing from surface 7, binding on Phase 5 and 6:
                    - **A guard can be right about permissions and wrong about
                      data.** `TEACHER_ROLES` admitted `platform_admin`
                      correctly (the API admits the role) onto screens whose
                      every service returns empty for it. Passing typecheck,
                      lint and the design hook proves nothing about whether a
                      role can *see* anything. `adminRoutes.test.ts` is the
                      gate; extend it rather than writing a second.
                    - **The accent is the alert register AND the link colour,
                      and those collide.** Four panels on this surface painted
                      an alarm in the same terracotta as the links beside them.
                      Alarms belong in `warn` with a labelled chip. Sixth and
                      seventh occurrence of the accent finding.
                    - **`lib/adminOutcome.ts` makes the failure-copy family
                      eight**, and its header states the endpoint evidence that
                      forced it (machine-text details rule out detail-first;
                      two 409s that mean "this changed under you" rule out a
                      single status sentence). The family rule is still *decide
                      per endpoint*, not *one per surface*.
                    - **`formatAdminDate` in `portals/admin/data.ts`.** A bare
                      `toLocaleDateString()` renders `8/11/2026`, which is two
                      different dates three months apart depending on the
                      reader. Name the month.
                    - **A comment describing an intention is not evidence the
                      code has it.** Fifth time this phase.
                    - **`tests/test_authz_matrix_complete.py` fails at
                      collection** when a route mounts with no `EXPECTED` row.
                      That is the drift gate working; add the row, do not
                      widen the guard vocabulary to make it pass.

                    Standing from surface 10, still binding:
                    - **A screen no surface claimed is a screen no gate reads.**
                      The three file lists only grow by hand. Surface 7's two
                      portals were in none of them until added by hand, which
                      is the same mechanism, one surface later.
                    - **The harness switches identity per SURFACE, not per
                      state.** Both admin lanes carry their own `session` and
                      `profile` for exactly this reason.
                    - **A capture fixture can be wrong and look like a bug.**

                    Standing rules Phases 5-7 inherit:
                    - `npm run check:copy` is at **0**. It must stay there.
                    - Add each migrated file to RTL_CLEAN_FILES,
                      MIGRATED_FILES and SCANNED_FILES.
                    - Stamp every emitted surface with the hallmark pre-emit
                      critique (§9.1).
                    - **A defect fixed on one surface is often live on
                      another.**

                    Deferred, not blocking, carried into Phase 6:
                    - B4's own proposed fix, a `GET /__e2e__` marker route
                      asserted in `e2e/global-setup.ts`.
                      `reuseExistingServer: !process.env.CI` is still the real
                      bug and today only works because nothing else holds the
                      port.
                    - **The compat layer cannot die yet.** Every *screen* is
                      migrated; 17 kit components still name build-era aliases
                      in their own source, none in MIGRATED_FILES, so no gate
                      reads them. Phase 6 hardening.
LAST UPDATED:       2026-08-14T08:05+03:00
LAST STEERING TS:   1786673052   (poll http://home-server:7532/lemely-ErBPK7TIRGD1sQP5-in/json?poll=1&since=<this>)
                    NOTE: the human replied on 2026-08-14 for the first time in
                    this mission — three messages, resolving D1.6 (build the
                    admin screens fully and wire them) and B4 (port freed).
                    Both logged in STEERING.md and acted on.
```


### Phase ledger

| Phase | Status | Completed | Notes |
|---|---|---|---|
| 0. Setup & Verification | DONE | 2026-08-13 | All 9 skills loadable; nothing needed installing. Node 26.6.0, Python 3.13.5, Playwright 1.62.1 (web/), Gemini key in gitignored `.env`, spend $0.204/$8 (image budget for this mission ≤$3). impeccable hook already `enabled`; `context.mjs` clean apart from one stale-context finding, fixed. PRODUCT.md already existed from the build era and was corrected rather than regenerated (see notes). ntfy verified in **both** directions. |
| 1. Audit | DONE | 2026-08-13 | Three legs, all read-only, `web/` verified untouched after each. Merged into `BUILD/DESIGN-AUDIT.md`; leg reports in `BUILD/audit/`. 6 critical, 14 major, 3 minor. Root cause is one thing: every token is still the build-era Material-3 palette, so zero pages are Study Notebook yet. Worse than that and independently confirmed by me: 3 fabrications on the landing page, no error boundary anywhere, no skeleton component anywhere. **Coverage is partial and stated so — nothing was verified against a rendered viewport, and 34 of 48 routes were reached by grep only.** |
| 2. Brand & Design System | DONE | 2026-08-13 | All 6 steps done. Brand strategy at `BUILD/BRAND.md`; logo hand-authored as SVG after the Gemini refine pass failed on all five named defects (D2 defaulted to ship it). DESIGN.md rewritten from scratch as the Study Notebook; index.css is its implementation with a documented temporary compatibility layer so un-migrated screens pick up the new palette instead of staying Material-3. `tests/test_design_tokens.py` pins every contrast claim and caught two real AA failures plus one greyscale failure in my own draft. Landing-page fabrications C1/C2 fixed, plus a third the audit missed (a stated 0.70 review threshold that is really 0.90). Component kit: 19 components, all 8 states, preview page at `web/dev-previews/` with its own Vite entry so the product can never ship it. Closed the audit's "no skeleton component" and "no error boundary" gaps. Three defects found by verifying rather than trusting the agent reports: RadioGroup did not actually have 8 states; the preview page was silently missing every utility used only inside a component (Tailwind source detection is rooted at the entry CSS, fixed with `@source`, CSS went 28KB→69KB); and a hover-pinning device I built emitted zero CSS and was removed rather than left to quietly pass review. |
| 3. IA & UX Flows | DONE | 2026-08-13 | All four parts done, D1.1-5 implemented. The headline is what the audit could not see from source: **neither the student nor teacher portal had ANY navigation below 820px/768px** — sidebars simply `hidden`, nothing replacing them, on a product whose own brief says students live on phones. Fixed with a shared `NavDrawer` rendering the same list as the desktop aside. Also removed two cross-portal links `RequireAuth` bounces for every role that exists (dead for everyone), and 4 dead keys in the student `crumbs` map. First-run views for student + teacher (`GettingStarted`); the parent's was already right and was deliberately left alone. Four honesty defects fixed in passing: a fabricated school name and hardcoded date on the teacher dashboard, hardcoded greetings on both, and two 'Coming soon' buttons for features that shipped. Three rules got gates rather than sweeps (`check:copy`, `rtlSafety`, `navigation`), and each found a real defect while being written. 646 unit tests (+59), typecheck/lint/both builds/pre-commit clean, no horizontal scroll at 320/375/1440. **e2e blocked by B4** — environmental, verified pre-existing at `0451e5e`, not a Phase 3 regression. See D3.22. |
| 4. Surface redesign | **DONE** | 2026-08-14 | **All 10 surfaces built.** Surface 7 (admin views) closed the phase. Its headline is that `TEACHER_ROLES` bundled two roles that are opposites: a `school_admin` genuinely holds the teacher API's data (every staff service scopes them to the schools they administer), while a `platform_admin` holds **none** of it by design (`no super-role bypass`, D1.6/D1.10, stated in four repos), so the console they landed in could only ever have been blank, which is indistinguishable on screen from a broken one. `platform_admin` left `TEACHER_ROLES`; `school_admin` stayed and gained `/school` as a home rather than a cage. Nothing could have caught it: a guard admitting a role the API also admits passes every gate, and the defect is that the *data* behind it is empty. Pinned by `adminRoutes.test.ts`, verified by inversion. Second finding: **X-01/X-02/X-03 had no backend at all** — no `/api/admin/*` router existed and no service could answer a global question, because every service in `lemely/db` is tenant-scoped by construction. "Completely wired" therefore meant building `admin_repo.py` (the first service in the product with no tenant scope, reached by its own door rather than by widening an existing one), `school_admin_repo.py`, two routers, two DTO modules and migration `0019` (`activation_note` + a `rejected` status, because `cancelled` already means *the subscriber ended this* and conflating the two would destroy the one distinction an audit reads). Five spec items were refused rather than faked and say so on screen: K-01's subscription status (no school-level subscription exists in the schema), K-02's "last active" (nothing records a session or a login, so the column is "Last marked"), K-02's invited/active/inactive (none of the three exists; the column became "On a seat since", which put `assignedAt` on screen for the first time), K-04's create/reassign/archive (teacher-only routes, and no `archived` column at any level), and X-03's accuracy metrics (produced by the harness into `reports/`, unreachable from a request). See D4.10. Earlier: 9 of 10 built. **D1.6 was answered on 2026-08-14 ("fully build the required screens and completely wire them") and B4 was resolved the same day**, so the phase is unblocked and the e2e gate is green for the first time: 34 passed, 0 failed, after four assertion drifts against deliberate redesign changes were fixed in place per §9.7. Admin views are the one surface left. **Surface 10's headline is that "404 / misc" was not a tidy-up: the sweep found ten more product screens still in the build-era language, 181 compat call sites, including the whole of onboarding and the whole placement flow** — the first three screens a new account ever sees, none of which any row of this ledger had ever claimed, though MISSION §1 names "onboarding/placement test" in scope outright. The mechanism is worth more than the count: **the three gate lists only grow by hand, so a screen no surface claims is a screen no gate reads.** `text-body` and `text-title` sat on the notification inbox's own `<h1>` emitting zero CSS for the entire build; proved by inversion that `utilityExistence.test.ts` catches `text-title` the instant the file is listed, so the gate was never too narrow, the file was never in it. Individual findings: `DELETE /me/devices/{id}` never raises and answers `200 {removed:false}` for a device it did not remove, so the screen a reader opens *because* they think someone else is signed in ran `onSuccess`, refetched, showed the row again and said nothing; "Skip for now" in onboarding appeared only once you had answered and deleted the answer it offered to defer; the Subject topic map printed "73% / of 24 marks" from a hardcoded denominator that exists nowhere on the wire, under a heading promising marks-earned-over-marks-available; the weighted-mean delta was `text-ok` whatever its sign, so a student sliding backwards saw their decline in the success colour; `Parents.tsx`'s own comment claimed it kept the backend's detail, which is `f"Identifier must be a UUID, got {value!r}"`. Two outcome modules (`settingsOutcome`, `studentOutcome`) close the family at seven, each with its endpoint evidence. D4.8 defaulted: the design-directions gallery left the product bundle, verified by grep and a 129→127 precache drop. See D4.9. Earlier: 8 of 10 built (admin deferred behind D1.6). **Surface 9's headline is that the marketing page had no reader at all**: `/student/landing` sat inside `studentRoute`, which `App.tsx` wraps in `RequireAuth allowedRoles={["student"]}`, so a signed-out visitor went to `/login`, a signed-in *teacher* went to `/teacher` (the page's own eyebrow reads "For CAIE teachers and their students"), `/` sent every signed-out visitor to `/login` so the product had no public page of any kind, and the one reader who could reach it was the person who least needed selling, seeing it wrapped in the student sidebar, breadcrumbs and streak pill above a hero saying "Mark a paper". It was **known and half-fixed** — D1.1 called it "orphaned inside the authenticated app" and removed the nav entry, which fixed what a student saw and left the page with no audience. Nothing could have caught it: a guard around the wrong subtree passes typecheck, lint and the design hook, which is why the fix ships with `marketing.test.ts` asserting public-vs-guarded in both directions, and why the route table moved to `src/routes.tsx` (importing `@/App` in a node-env test throws on `document`). **The second finding is that the audit deleted the numbers and left the sentences**: C1/C2/C3 closed in Phase 2, and six fabrications were still live — "marked in 41s" (the exact figure C1 removed, four sections up the same file), a partnered-teacher free tier and "No card to start" one screen above the placeholder saying pricing is undecided, QR/face/2FA attendance and replayed-minute retention (both recorded in `schemas_teacher.py` as having no backend source), WhatsApp results (absent from the repo entirely) and course payments (out of scope per PRODUCT.md). Every bullet now cites the router that implements it. Also: `Reveal` (the scroll-entry motion DESIGN.md §9 specifies and nothing implemented), the page had two left edges 40px apart, `ruled-bg` was painted over by opaque cards and drew nothing, and the Parents link was hidden below 640px on the login route whose selling point is a phone number. The capture harness failed its own round twice and was right both times. See D4.8. **Surface 8's headline is that the OTP failure a parent read was an enum member**: `verify_otp` raises `AuthError(f"OTP verification failed: {result.value}")` and `ParentLogin` rendered `err.message` verbatim, so the screen said `OTP verification failed: wrong_code` — while that file's own docstring asserted the parent "reads the actual reason rather than a client-side guess". The distinction was real; the vocabulary was never fit to show anyone. Second time this phase a docstring described the fix rather than the behaviour. `authOutcome.ts` maps the four `OtpResult` members and, three lines away, deliberately *keeps* the 429's own wording, because there a human wrote a sentence for a human — which is the failure-copy family's real rule now that five modules exist. Also: `Login.tsx` had been scaffolding since the build era and said so in its docstring, shipping a card invisible against its own page colour, a form-level error in the one position §12 rules out, and a raw `error.message` that could print "401 Unauthorized"; the password 401 is now deliberately vague to close an account-enumeration oracle; the OTP boxes were set in the display face; and audit finding M9's placeholder logo turned out to be in **four** places, not the three it counted. See D4.7. Earlier: 6 of 10 surfaces done (student dashboard, past-paper correction flow, study surfaces, gamification, teacher portal, parent views). **Surface 6's headline is DESIGN.md's banned easing being in force on every transition in the product, with no call site naming it**: §3.2 item 14 forbids `ease-in-out`, and Tailwind's `--default-transition-timing-function` *is* that curve, so all 27 bare `transition-*` call sites inherited it. Verified in the shipped bundle before and after. It is D4.1's `--font-serif` shape a fourth time with one difference that matters — those classes resolved to nothing, which `utilityExistence.test.ts` can see, while these emit the *wrong* rules, which it cannot — so the deliverable is a gate that checks the value rather than the name. Found only because the first draft of the parent shell wrote `duration-instant` and I checked the assumption instead of trusting it: the durations live in `:root`, not `@theme`, so that class emits nothing either. **The second finding is every child screen carrying two back links to the same place** — P3.1 added the breadcrumb trail without removing the inline back links beneath it. Also: all four screens rendered a raw `error.message`, and the obvious fix (reuse `teacherOutcome.ts`) was wrong because every `detail` the parent API produces is machine text, UUIDs and stringified Python exceptions included; the "Last worked" card printed "1d ago" directly above "2 days ago" from one timestamp; "6 more marks for a A"; the boundary panel put the screen's most encouraging sentence in the alert register (surface 5's finding (d) again); and an unlabelled tone-coloured percentage appeared for the third surface running. See D4.6. **Surface 5's headline is the resolves-to-nothing shape recurring a third and fourth time, inside the gate written to stop it**: `utilityExistence.test.ts` checked the four families where Tailwind owns the vocabulary, and `lm-` is the one family the project owns outright, so `lm-head` and `lm-body` sat on the student shell's own `<header>` and `<main>` in a file the gate already listed by name. Widening it found `lm-cols` on nine more elements. All six emit zero rules in the shipped bundle. **The second headline is a review queue that painted doubt green**: the queue exists because a mark fell below the 0.90 review floor, and it bucketed with its own `confidenceTone` at 0.8, so a mark at 0.85 was shown to the teacher in the same green the product uses for marks it is sure about. The gate written to prevent exactly this missed because the parameter is called `score`, not `confidence` — D6.12's lesson, where the shared condition was an assumption about naming. Also: all fifteen screens rendered a raw `error.message` at 44 sites; four destructive actions were confirmed by `window.confirm`, including a class delete that removes it for every enrolled student; a duplicate circular `Avatar` violated §6 at six call sites while the kit's squircle had one; and the portal had no texture layer at all. See D4.5. **Surface 4's headline is D4.1's defect recurring in a second family: `text-display` is not a class.** Nothing defines it, the shipped bundle emits zero rules for it, and four `<h1>`s across Profile/Standings/Friends/Announcements carried it — so the product's page titles rendered at the browser's default heading in the body face, not §4.2's `display-lg` in Newsreader. Twice is a pattern, so the deliverable is a gate for the pattern (`utilityExistence.test.ts`) rather than four edits. Also: the **celebration register §9.3 describes had no implementation anywhere** and now does, with the honest omission recorded — a "leaderboard climb" cannot be celebrated because no `previousRank` exists on the wire, and inventing the movement was refused. C-9 `XPStreak` had **zero call sites product-wide**, the kit component built in Phase 2 for exactly this surface; it now fills the header pill P3.10 deleted for being a hardcoded lie, from data Phase 5 later built for real. Friends rendered `err.message` verbatim for all three mutations and put two of the three at the very bottom of the page, below every section. The leaderboard opt-out toggle's `isError` was rendered nowhere, so a failed "Hide me" left a student believing they were hidden. And **`check:copy` had never read a `.ts` file**, which hid 9 user-facing em-dashes, five of them on surface 3 after it was reported clean. See D4.4. **Surface 3's headline is two irreversible actions with no confirmation and no failure report**: deleting a flashcard deck destroyed it and every card in it on one tap, and both `useDeleteDeck`/`useDeleteCard` exposed an `isError` that nothing rendered, so a failed delete was indistinguishable on screen from one the student imagined pressing. The telling part is which mutations were covered: `addCard` and `editCard` both reported their failures carefully, and the two with no error path were the two *destructive* ones. `Modal`'s `dismissible={false}`, whose docstring names this exact case, had no call site in the product. Also: the study-plan week bar measured completed MINUTES while the count beside it counted SESSIONS, so "2 of 4 sessions done" sat next to a bar at 25% with nothing explaining the gap; that same bar animated `width`, which §9.2 forbids outright; the Read lane rendered at four different container widths; and the §8 texture classes `ruled-bg`/`dotted-bg`, written in Phase 2 *for the Read lane*, had zero call sites product-wide. See D4.3. **Surface 2's headline is a run that could fail in silence**: `streamActivity` never checked `res.ok`, so a 500 or 503 yielded zero frames, the loop fell out of the bottom, and the panel went back to reading "Ready when you are" — a student pressed the button, nothing happened, and the screen told them it was ready. Also: the student's confidence threshold was 0.85 against the backend's and the teacher's 0.90, so one mark was described two ways to the two people reading the same paper; and the mark and the grade, the two figures a student reads first, were both set in the heading face where DESIGN.md §4 puts the data face — `MarkDisplay`'s own docstring stated that rule while breaking it. See D4.2. Surface 1: Headline finding is one nothing in this build could have caught: **`--font-serif` was never a token, so ~20 call sites across five screens were rendering Georgia, not Newsreader** — the display face DESIGN.md mandates was on screen nowhere it was reached by that name. Verified in the shipped bundle before and after, not reasoned about. A missing definition fails silently where a wrong one would not: the token gate greps for raw values *bypassing* the block, and `font-serif` is a well-formed utility resolving to somebody else's default. Also: both dashboard charts drew a blank box where §11 mandates an empty state (the momentum panel's empty case is *every* student who just marked their first paper), the trend column told a one-paper student they were improving by "+0" in teal, and "Forecast" rendered a space-joined concatenation of per-subject grades under a label promising one value. See D4.1. |
| 5. Motion & data-viz | PENDING | — | |
| 6. Hardening & adaptation | PENDING | — | |
| 7. Final QA & report | PENDING | — | |

### Surface ledger (Phase 4 order)

| Surface | Status | Branch | Gates | Merged |
|---|---|---|---|---|
| Student dashboard | **DONE** | `redesign/student-dashboard` | typecheck / lint / 662 unit / check:copy 91 (flat) / both builds / pre-commit / 28 token tests: **green**. e2e: **now green** (B4 resolved 2026-08-14; whole suite 34 passed). Visual round: 10 captures, all distinct, 0 unexpected console errors. | pending |
| Past-paper correction flow | **DONE** | `redesign/correct-paper` | typecheck / lint / 694 unit (+32) / check:copy 90 (**down from 91**) / both builds / pre-commit / 30 Python token+constant tests: **green**. e2e: **now green** (B4 resolved 2026-08-14; whole suite 34 passed). Visual round: 28 captures across 3 surfaces, all distinct, console errors only from the deliberately-failing states. | pending |
| Study surfaces (classifieds, flashcards, plans) | **DONE** | `redesign/study-surfaces` | typecheck / lint / 752 unit (+58) / check:copy 69 (**down from 90**) / both builds / pre-commit / 30 Python token+constant tests: **green**. e2e: **now green** (B4 resolved 2026-08-14; whole suite 34 passed). Visual round: 28 captures across 4 registered sub-surfaces, all distinct, console errors only from the deliberately-failing state. | pending |
| Gamification (XP, streaks, leaderboards) | **DONE** | `redesign/study-surfaces` | typecheck / lint / 812 unit (+60) / check:copy 67 under a **widened** gate (64 like-for-like, down from 69) / both builds / pre-commit / 30 Python token+constant tests: **green**. e2e: **now green** (B4 resolved 2026-08-14; whole suite 34 passed). Visual round: 30 captures across 3 registered sub-surfaces, all distinct, console errors only from the deliberately-failing states. | pending |
| Teacher dashboard + quiz builder (whole portal) | **DONE** | `redesign/study-surfaces` | typecheck / lint / 927 unit (+115) / check:copy **18** (down from 67; none in the teacher portal) / both builds / pre-commit / 31 Python token+constant tests: **green**. e2e: **now green** (B4 resolved 2026-08-14; whole suite 34 passed). Visual round: 26 captures across 3 registered sub-surfaces, all distinct, console errors only from the deliberately-failing states. | pending |
| Parent views | **DONE** | `redesign/study-surfaces` | typecheck / lint / 980 unit (+53) / check:copy **14** (down from 18; none in the parent portal) / both builds / pre-commit / 31 Python token+constant tests: **green**. e2e: **now green** (B4 resolved 2026-08-14; whole suite 34 passed). Visual round: 32 captures across 4 registered sub-surfaces, all distinct, console errors only from the deliberately-failing states. | pending |
| Admin views | **DONE** | `redesign/study-surfaces` | typecheck / lint / 1,255 unit (+89) / check:copy 0 (flat) / both builds / pre-commit / full Python suite 3,573 rc=0 (**+33 new backend tests**): **green**. e2e: **34 passed, 0 failed**. Visual round: 78 captures across 7 registered sub-surfaces, all distinct, console errors only from the deliberately-failing states. | pending |
| Auth | **DONE** | `redesign/study-surfaces` | typecheck / lint / 1,013 unit (+33) / check:copy 14 (flat; none in auth) / both builds / pre-commit / 31 Python token+constant tests: **green**. e2e: **now green** (B4 resolved 2026-08-14; whole suite 34 passed). Visual round: 16 captures across 2 registered sub-surfaces, all distinct, console errors only from the deliberately-failing states. | pending |
| Marketing / landing | **DONE** | `redesign/study-surfaces` | typecheck / lint / 1,061 unit (+48) / check:copy 14 (flat; none in the marketing lane) / both builds / pre-commit / 31 Python token+constant tests: **green**. No horizontal scroll at 320/375/414/768/1024/1440. e2e: **now green** (B4 resolved 2026-08-14; whole suite 34 passed). Visual round: 4 captures + 4 in-harness assertions, all distinct, 0 console errors. | pending |
| 404 / misc | **DONE** | `redesign/study-surfaces` | typecheck / lint / 1,166 unit (+105) / check:copy **0** (down from 14; the product now has none) / both builds / pre-commit / 31 Python token+constant tests: **green**. No horizontal scroll at 320/375/414/768/1024/1440. e2e: **now green** (B4 resolved 2026-08-14; whole suite 34 passed). Visual round: 38 captures across 6 registered sub-surfaces, all distinct, plus 6 in-harness assertions; console errors only from the deliberately-failing states. | pending |

### Gate status (current surface only)

```
SURFACE:            Admin views (K-01..K-04, X-01..X-03) - `portals/admin/`
                    (shell + data + 7 screens), `lib/adminTypes.ts`,
                    `lib/adminOutcome.ts`, `lib/hooks/useAdminApi.ts`, the
                    `schoolTypes`/`useSchoolApi` extensions, and the backend
                    the platform console never had.
BUILD COMPLETE:     yes
INSPECTION ROUND:   1 (batched, desktop 1440 + 375 together)
FINDINGS TO FIX:    7, all fixed in one batch -
                    (a) the accent carried the alarm on four panels (seat
                        meter at quota, spend meter past its threshold, the
                        two fallback bars) in the same terracotta as the links
                        beside them, so one colour meant "this is wrong" and
                        "this is a link"; all four moved to `warn` and gained
                        a labelled chip;
                    (b) the stat-card links wrapped mid-link ("See" / "the
                        roll"), a two-line clickable target §6 bans outright;
                    (c) two class names in the seats table ran together into
                        one string with only a space between them;
                    (d) the "Status" column was a constant on every row, and
                        `assignedAt` was going unrendered; the column became
                        "On a seat since";
                    (e) `toLocaleDateString()` rendered `8/11/2026`, which is
                        11 August or 8 November depending on the reader;
                    (f) the invite form pushed the roll below the fold on the
                        screen whose job is showing the roll;
                    (g) a docstring claimed the school heading was suppressed
                        for the single-school case, which it never was - the
                        fifth time this phase.
CONFIRM ROUND:      1 - all seven confirmed fixed, no regression introduced.
                    Stopped there per §3.2 item 16.
HALLMARK STAMP:     present on all 9 emitted `.tsx` files.
HOOK FINDINGS:      0 (impeccable design hook, every touched file)
TESTS:              1,255 unit (+89), all green; full Python suite 3,573
                    rc=0 including 33 new backend tests; e2e 34 passed, 0
                    failed. check:copy **0** (flat).
NEW GATES:          `tests/unit/adminRoutes.test.ts` - each lane's guard and
                    its exact `allowedRoles`, that neither admin role can
                    enter the other's lane, that `platform_admin` has left
                    `TEACHER_ROLES` and `school_admin` has not, that every
                    role's home is a portal whose own guard admits them (the
                    infinite-redirect property P3.9 found the hard way), that
                    all five roles still reach `/settings/*`, and that no
                    admin screen renders a raw `error.message` while every one
                    of them routes failures through `adminOutcome`.
                    **Verified by inversion**: re-adding `platform_admin` to
                    `TEACHER_ROLES` fails exactly one test.
                    `navigation.test.ts` and `notFoundFallback.test.ts` were
                    *widened* rather than duplicated - both were blind to two
                    whole portals, which is surface 10's lesson arriving one
                    surface later.
                    `tests/test_authz_matrix_complete.py` gained 9 rows and
                    failed at collection the moment the admin router mounted.
NEW CAPABILITY:     `lemely/db/admin_repo.py` (the first service with no
                    tenant scope, behind its own door rather than a widened
                    one), `lemely/db/school_admin_repo.py`,
                    `routers/admin.py`, `schemas_admin.py`, migration
                    `0019_activation_review`, the enriched `SeatRow`,
                    `portals/admin/` (one shell, two lanes),
                    `lib/adminOutcome.ts`, `formatAdminDate`, and seven new
                    capture surfaces.
```

### Open DECISIONs

| ID | Question | Options | Default | Sent | Timeout | Status |
|---|---|---|---|---|---|---|
### Resolved

| ID | Outcome | When |
|---|---|---|
| D1.1–5 | **DEFAULTED — proceed as proposed.** 60-minute timeout elapsed with no reply. The five cost-free IA corrections are approved by default and are implemented in Phase 3.1. | 2026-08-13T18:10+03:00 |
| D1.6 | **ANSWERED by the human, 2026-08-14T05:37+03:00** (inbound `9gd0VBc0noOC`): *"fully build the required screens and completely wire them"*. Stronger than option A as written — real screens on real endpoints, not scaffolds. Surface 7 is the next work unit. | 2026-08-14T05:37+03:00 |
| D4.8 | **DEFAULTED — option A.** 30-minute timeout elapsed with no reply. The design-directions gallery moved to `web/dev-previews/` behind the kit's own Vite entry, out of the product route table. Verified rather than assumed: its marker string no longer appears anywhere in `dist/`, and the product precache dropped 129 → 127 entries. `navigation.test.ts` flips from "keeps it mounted" to "no longer mounts it" (documented per §9.7) and `audit.mjs`'s DEV-01 entry is retired with its reason recorded in place. | 2026-08-14T04:30+03:00 |
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
| Settings lane chrome | `web/src/portals/settings/SettingsFrame.tsx` | Mark, breadcrumb, skip link and the two-item section nav for the only top-level authenticated routes. Nav sits **above** the title; below it, the active pill reads as a filter. |
| All-roles failure copy | `web/src/lib/settingsOutcome.ts` | Sixth of seven. Status-first, because every `routers/me.py` `detail` is written for a client author. Its reader is all five roles at once, which is why it cannot borrow another module's register. Also owns `DEVICE_ALREADY_GONE`, which is not an error path. |
| Student failure copy | `web/src/lib/studentOutcome.ts` | Seventh and last. Covers onboarding, placement, Subject, Announcements and Parents. Deliberately NOT `correctionOutcome.ts` widened: that one is detail-first because the marking router writes its details for a human, and these routers do not. Leaves the placement 409 alone, because its `detail` is a structured DTO. |
| Portal-scoped 404 | `PortalNotFound` in `web/src/portals/misc/NotFound.tsx` | The body without the frame, mounted as a `*` child in all three portals. The split is about landmarks (two `<main>`s, two `MAIN_CONTENT_ID`s), not styling. `errorElement` stays top-level only: re-rendering chrome that may itself have thrown is how a crash becomes a crash loop. |
| Fallback + settings gate | `web/tests/unit/notFoundFallback.test.ts` | The portal-fallback defect cannot fail loudly, and `navigation.test.ts` only knows paths a nav entry names. Asserts the catch-all exists, is last, renders the right component, stays ungated at top level, and that the settings routes keep ALL_ROLES. |
| Captures | `reports/redesign/p4-{settings-devices,settings-notifications,not-found,not-found-teacher,onboarding,subject}/` | 38 states x 1440/375. `notFoundAct`'s `<main>`/`<nav>` count assertion is the only thing that distinguishes a portal 404 from a top-level one; both look right in a picture. Note the harness switches identity per **surface**, not per state. |
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
