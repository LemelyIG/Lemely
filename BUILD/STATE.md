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
CURRENT PHASE:      **6 IN PROGRESS. 6.1 (`adapt`), 6.2 (`harden`) and 6.3
                    (`optimize`) DONE.** 6.4-6.5 remain.
CURRENT SURFACE:    Phase 6 is a sweep, not a surface.
NEXT ACTION:        **Phase 6.4 part 2.** Part 1 is DONE and committed (the
                    46 of 47 axe violations that were unambiguous, plus two
                    gates). What remains is one open decision and one
                    unfinished sweep.

                    **D6.6 needs the human, and it is the largest finding of
                    the phase.** `tests/test_design_tokens.py` asserts contrast
                    ratios the browser does not render:

                        oklch(0.576 0.146 33) -> our conversion  #c0523c
                        the same token, Chromium renders         #c25741
                        white on #c0523c (the test's number)     4.658  PASSES
                        white on #c25741 (what a user sees)      4.436  FAILS

                    So **`--accent-on`, the token block's "ONE permitted pure
                    white" at a stated 4.65:1, is 4.436:1 on screen** - below
                    the 4.5 floor it was picked to clear. The error is 2-5/255
                    per channel and that is exactly why it bites: every value
                    in this system was chosen to *just* clear its threshold.
                    The repair is not a nudge to one token - it is reconciling
                    the conversion, re-deriving **every** contrast claim
                    against corrected values, and then whatever token changes
                    fall out, on the brand accent that is present on every
                    surface. **Refused unattended** and left red rather than
                    loosened. See D6.5 §3 for the full arithmetic.

                    Also still open:
                    - **Run the audit again.** Part 1 changed both chart
                      wrappers and 12 call sites; nothing has re-measured. That
                      run is also the first to emit `route-failures.json`
                      (6.3 could not, because the change was written while its
                      own run was in flight).
                    - **Five routes die mid-run on their `loading` state**
                      (T-08, T-09-detail, T-10, S-21, S-22, "Waiting failed:
                      15000ms exceeded"), identically in both 6.3 corpora and
                      so pre-existing. **Not diagnosed** - the harness drives a
                      `loading` state by holding a request open, so the timeout
                      may be the fixture's rather than the product's.
                    - §6.4's remaining items, none yet swept: focus-visible
                      everywhere, keyboard-completable flows, alt text,
                      aria-labels on icon-only buttons, semantic landmarks.
                    - `text-ink-faint` on the **other** pastels is unmeasured.
                      The wash case was fixed where axe caught it
                      (`--accent-wash`, 4.47:1); the token test pins
                      ink-on-**paper** only, so the ink x pastel matrix is
                      still a hole and belongs with D6.6's re-derivation.

                    Then 6.5 strategic omissions.

                    **6.5 is scoped and waiting** - verified, not guessed:
                    `index.html` still carries the build-era `favicon.svg` and
                    `theme-color: #1e1310` while D2's real mark sits unused at
                    `web/public/brand/`; `vite.config.ts`'s manifest still has
                    the build-era `theme_color`/`background_color`; **no screen
                    in the product sets a `document.title`**, so all 48 routes
                    are "Lemely"; there are no `og:`/description meta tags at
                    all; and the marketing frame states in a comment that it
                    has no legal links and invented none.

                    What 6.2 leaves for the rest of Phase 6 (D6.3):
                    - **A premise carried in a docstring is not evidence.**
                      M4 said a reload "loses the run"; the run was never lost.
                      `POST /student/correct` works on a background thread that
                      does not stop when the client disconnects. What was
                      missing was the *record* that a run was in flight, and
                      that made the fix look architectural when it was a read.
                    - **An enum member nothing writes is a defect with a wide
                      blast radius.** `UploadStatus.processing` had never been
                      written by any code path, which is why the reload could
                      not recover AND why the platform console's "uploads in
                      flight" counted every abandoned scan forever. Phase 6.3
                      and 6.4 both touch vocabularies (z-index scale, ARIA
                      roles) where the same shape is available.
                    - **A gate that reports good copy is worse than the defect
                      it looks for**, because it teaches people to launder good
                      copy through a module to make a test go quiet.
                      `failureCopy.test.ts`'s first draft did exactly that.
                    - **The failure-copy family took six passes to close** and
                      the mechanism was that the outcome modules were written
                      surface by surface, so a screen redesigned before its
                      module existed was never revisited. Any Phase 6 sweep
                      that fixes a class of thing should end in a gate that
                      walks the tree, not in a list.

                    **6.1 is closed and its gate is green: 745 page-states
                    across 35 surfaces at 320/375/414/768/1440, 0 findings, 66
                    exemptions all from the one OTP row that states its
                    reason.** Re-run it with
                    `npm run build && node scripts/adapt_audit.mjs` after any
                    layout change in 6.2-6.5; it takes ~25 minutes, so batch it
                    per §3.2 item 16 rather than running it per edit.

                    What 6.1 leaves for the rest of Phase 6 (D6.1, D6.2):
                    - **A gate reporting zero and a gate reporting nonsense are
                      both consistent with a green ledger row.** D6.1 recorded
                      `adapt` as finished without ever running it to green;
                      running it produced 198 findings, and three of the four
                      defects were in the gate, not the product. Phase 6.3 and
                      6.4 are both gate-heavy. Look at what a check *names*,
                      not just its count.
                    - **A gate whose answer changes between identical runs is
                      worse than a vacuous one**, because it teaches people to
                      re-run until it passes. Chromium lays out in 1/64px
                      units, so sub-pixel tolerance is required wherever a
                      measurement is compared to a CSS floor.
                    - **A waiver has to cover every rule it is a waiver from.**
                      The OTP exemption was honoured on size and then failed
                      the same six inputs on spacing 30 times.
                    - **Three impeccable design-hook findings on `index.css`
                      are deliberately left**: `--ease-spring`/`--ease-celebrate`
                      overshoot on purpose (§4's celebration register) and
                      `ruled-bg`/`dotted-bg` are §4's notebook texture, which §1
                      names as the one protected quality of this redesign. §3
                      says this mission wins over a skill when they conflict.
                      Not suppressed either - a waiver needs the human.

                    Phase 5 closed with D5.1 (charts) and D5.2 (motion). Two
                    things from it bind on the rest of Phase 6:

                    - **A value handed to a JS library cannot be a `var()`
                      string**, because the library parses it. That is D5.1's
                      headline and it generalises: any easing, duration or
                      colour passed to JS rather than set as a CSS class needs
                      a resolved value. `nivoTheme.ts` shows the pattern
                      (resolve off `:root`, fail closed).
                    - **A rule that looks like it covers a case may not.**
                      D5.2: `scroll-behavior: auto !important` under
                      `prefers-reduced-motion` does not reach an explicit
                      `scrollIntoView({behavior:"smooth"})`, because the JS
                      option wins by spec. Phase 6 touches performance and
                      a11y, where reassuring-looking rules are everywhere.

                    Carried into the rest of Phase 6 from earlier phases:
                    - B4's own proposed fix, a `GET /__e2e__` marker route
                      asserted in `e2e/global-setup.ts`.
                      `reuseExistingServer: !process.env.CI` is still the real
                      bug and today only works because nothing else holds the
                      port.
                    - **The compat layer cannot die yet.** Every *screen* is
                      migrated; 17 kit components still name build-era aliases
                      in their own source (`stepper.tsx`'s `hover:bg-surface-2`
                      is one, seen again this phase), none in MIGRATED_FILES,
                      so no gate reads them.
                    - **`Reveal` is scoped to the marketing lane on purpose**
                      (D5.2's last section), which is a deliberate narrowing of
                      §5.1's literal "sweep every surface". If the human wants
                      it literal, it is one prop on a handful of screens.
                    - **A correct answer has no honest celebration moment**
                      and a leaderboard climb still cannot be celebrated (no
                      `previousRank` on the wire). Do not invent either.

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
LAST UPDATED:       2026-08-14T18:15+03:00
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
| 5. Motion & data-viz | **DONE** | 2026-08-14 | **5.3 (charts) DONE.** Nivo 0.99 installed (`core`/`line`/`bar`/`theming`; `@nivo/theming` was transitive and is now declared, per the dependency rule). One shared theme, two wrappers, four charts moved: student momentum, the cohort trend, the at-risk trend, and XP-per-day. **The headline is that the obvious token-disciplined implementation would have drawn nothing** — Nivo hands series colours to react-spring, which *parses* them, so `var(--accent)` arrives as nothing, and SVG presentation attributes do not substitute custom properties either. That is D4.1/D4.4/D4.5/D4.6's shape a fifth time, by a route none of those four gates watch; found by reading Nivo's compiled source before building on it. The theme resolves tokens off `:root` at runtime and **fails closed** (no chart draws until real values resolve, because a chart in the wrong colours is much harder to notice than a missing one). **Second finding: `MomentumDTO` shipped pre-rendered SVG path data, and its transform clipped** — `y = 88 - ((pct-55)/45)*78` puts 40% at y=114, outside an 88-tall `overflow-visible` viewbox, so a struggling student's line escaped the panel and drew over the labels below. Proved arithmetically before changing anything. The wire now carries `points`, which also removed a **third** copy of that transform from the capture harness. Its `labels` were `recorded_at[:7]`, so five papers in a month were five identical ticks — and five points sharing one key on a Nivo point scale collapse into one, which blocked the migration outright; the x-axis is the paper ordinal now, dates in the tooltip. **Third: the grade panel's empty state could never fire**, because `grade_distribution` always returns every rung with zero counts, so `length === 0` is unreachable and an unmarked class drew nine empty tracks. **Two more only a rendered capture could find**: a count axis asked for four ticks produced an axis reading "0 0 0 1 1 1", and the last x-tick clipped **"Aug 11" into "Aug 1"** — a plausible date ten days out, with the table three lines below disagreeing. The XP heatmap became a bar chart because its quantity arrived in colour intensity alone. Four §11 exceptions logged with reasons (the weakness heatmap, two meter panels, `BoundaryBar`, row sparklines). **`ClassAnalytics` and `StudentDetail` had no capture surface at all** — P4.10's lesson one phase later — and both are now registered. New gate `chartTheme.test.ts` walks the tree rather than adding a fourth hand-maintained list; verified by inversion. See D5.1. **5.1/5.2/5.4 (motion) also DONE.** Headline is DESIGN.md §9.2's one rule stated in units being unimplemented on **26 elements**: they changed colour on hover with no `transition-*` at all, so they snapped in a single frame. Invisible from every direction — the classes resolve, the values are tokens, the easing is never the banned one because there is no easing, and a screenshot of a hover state is pixel-identical whether it took 120ms or 0ms; only the frames *between* two states were wrong. `hoverTransition.test.ts` parses **balanced class-expression groups**, because the naive line-based version reported `Button` as broken (its base holds the transition, its variants the hovers, twelve lines apart, correctly). **Second: §9.3's result reveal needed `useCountUp` to do the thing it deliberately refuses** — animate a first observation. It gained an explicit `from`, and the honesty lives in which call sites may pass it: `PaperResult` reveals on its `live` state and not on the by-id history fetch, and `PracticeResult` could not tell the two apart at all until `PracticeSet` began passing `justSubmitted`. **No flourish at any mark**, because confetti would need the product to decide a mark is good, and any threshold makes its absence read as disappointment. **Third: an `!important` that did nothing** — `scroll-behavior: auto !important` under `prefers-reduced-motion` does not reach an explicit `scrollIntoView({behavior:"smooth"})`, because the JS option wins by spec, so the landing CTA scrolled a reduced-motion reader across the whole page with a rule sitting right above it appearing to prevent that. §9.3's "correct answer" is **not** implemented and says why: every assessment path here is submit-then-mark, and flashcard review is self-graded, so there is no moment where the product tells a student they were right. Scroll entries stayed in the Persuade lane, stated as a deliberate narrowing of §5.1's literal wording. Three gates, all verified by inversion. See D5.2. |
| 6. Hardening & adaptation | **IN PROGRESS** (6.1, 6.2, 6.3 done) | — | **6.3 `optimize` DONE, and the record corrects itself before it reports anything.** The phase was started against a stale Lighthouse corpus (`reports/phase-6/`, 2026-08-12) showing two teacher routes at CLS 0.2427 and 0.1807 — and the font-preload plugin was written *before* measuring. Measured against HEAD: **41 routes, 0 over CLS 0.1**, and both of those routes measure 0.0000. The stale corpus names `instrument-serif`, a face Phase 2 replaced with Newsreader; the crisis was three phases dead. The work still ships for a smaller, better-stated reason (one real 0.098 on the product's most-visited screen) and because a preload **removes the race rather than winning it**, which is an argument that does not depend on which run you look at. **The headline finding is that the largest render-blocker in the product was 403 bytes of nobody's code**: `vite-plugin-pwa`'s default `injectRegister: "auto"` emits a bare parser-blocking `<script src="/registerSW.js">` as the last thing in `<head>`, measured at 301ms on **41 of 41 routes**, for the whole redesign. It was in nobody's diff — every gate this build runs reads code the project wrote, and this was generated at build time by a dependency default, visible only to a measurement of the built artifact. **Second: "lazy images" could not be done by making the image lazy.** The one content image is the grading console's scan thumbnail, and `loading="lazy"` would have done nothing, because `useScanPreview` fetches a `blob:` URL before any element exists. Worse, `GET /papers/{id}/preview` renders page 1 with PyMuPDF **on demand** and `GET /papers` is unpaginated, so opening the console re-rendered every scan the school has ever uploaded, server-side, at once, to fill a 64px strip. The cost was known and answered in the wrong place — the endpoint's own comment records shrinking the image rather than not asking for it. `useInViewOnce` defers the *fetch*, fires a screen-height early, and **fails open**. **Third: the z-index scale was a gate that had never existed** — `index.css` has said "a raw z-index outside this scale is a gate failure" since Phase 2 and nothing read it. Four raw values had accumulated and **one was live**: `ConfidenceIndicator`'s tooltip declared `z-10`, which is exactly `--z-index-sticky` (verified in the shipped bundle: `.z-sticky{z-index:10}`), so a floating layer sat in the band reserved for sticky headers and portal top bars, on the screen a student reads their marks on. It resolves to the *wrong* thing rather than to nothing, which is D4.6's shape and invisible to `utilityExistence.test.ts`. Also: four navbars spelled the one permitted `backdrop-blur` two ways, and the precache glob named nine non-latin font subsets that `unicode-range` makes free — **187KB of glyphs no English page can display, on every first visit** (146 -> 137 entries, 2621.92 -> 2435.27 KiB, verified by building both ways). **The new gate's first run flagged the best comment in the file**: `elevationScale.test.ts`'s first draft reported six offenders, all six prose, five of them this phase's own explanatory comments and the sixth `celebration.tsx` reasoning its way to the right answer — D6.3's finding arriving one phase later inside the gate written to honour it, hence a real comment lexer. Its allowlist is **derived from `index.css` every run**. **Confirm round: the Lighthouse mean went *down* 1.61 points, reported first because it is the number a reader would expect to be hidden** — ±11 swings on routes this phase never touched, in both directions, which is build-era D6.9 exactly: one run cannot separate *fixed* from *fast*. So the composite score is set aside and the structural audits carry the claims: `registerSW.js` off the render-blocking list on **all 41 routes** (the stylesheet remains and must), dashboard CLS **0.098 -> 0**, dashboard unused JS **103KB/2 chunks -> 53KB/1** with the 50KB `nivoTheme` chunk gone from first paint. Gate-failing routes fell 6 -> 3, **not claimed as an improvement** given the noise. **The confirm round also found five routes that die mid-run** (T-08, T-09-detail, T-10, S-21, S-22), all on their `loading` state, identically in both corpora and so pre-existing — invisible because a route that dies on its *last* state has already written its axe and Lighthouse rows, leaving a corpus that reads as a clean sweep. `audit.mjs` threw and named them on stdout, but the run's output is not the corpus and nothing that survived recorded it. `audit.mjs` now writes `route-failures.json` always (including `[]`) and `check_ui_gates.py` reads it with the convention it already applies to the other two summaries: **missing is "not checked", not "clean"**. 1,372 web unit tests (+25). See D6.4. | **6.2 `harden` DONE. The headline is that audit M4's premise was wrong, and that is the finding.** M4 has said since P4.2 that "a refresh mid-run loses the marking run", and it was deferred here as architectural. The run was never lost: `POST /student/correct` works on a background thread that does not stop when the client disconnects, and it persists the attempt, completes the upload, awards the XP and sends the notification whether or not anyone is still reading the stream. What was missing was far smaller and worse — **`UploadStatus.processing` shipped in the first migration and no code path in the product had ever written it**, so for the entire duration of a mark the database said `pending`, which is also exactly what it says about a scan somebody uploaded and abandoned. Two things followed, and only one was known: the reload could not recover (there was no state to recover *from*, which is why the fix looked architectural when it was a read), and **the platform console's "Uploads in flight" counted `pending`, so every abandoned scan was in flight forever** on the one panel whose job is answering "is anything stuck?". Recovery is now `GET /student/uploads/active` + `/{paper_id}` — two endpoints because they end differently: `active` stops naming a paper the instant it goes terminal, so a client polling only that would watch its run vanish without learning whether it was marked or failed. Three refusals are recorded in code: the recovered screen **does not redraw the stage panel** (the SSE frames go to a process-global bus with no replay, so a recovered reader knows the run is going and nothing else, and ticking stages off a status word is the invented progress S-14 bans), **does not re-POST `/correct`** (a second run over one scan means double spend against a hard-capped budget, a second attempt row, and cross-talk on a single-stream bus), and **does not animate the result** (the reveal is for a figure that arrived while this reader watched). `stale` is computed server-side because the server owns the clock. **Second finding: the failure-copy family was never closed, and this was the sixth pass at it** — 15 live sites still rendered an `Error`'s own `message`, including `Overview` and `PaperResult`, surfaces **1 and 2**, which answered a dropped connection with the browser's "Failed to fetch", and two in `CameraCapture` where the leaked text was **pdf-lib's**, so a student who photographed a paper page by page could be told "Input image is not a JPEG" at the end of the longest task the product asks of them. The mechanism is the point: the outcome modules were written surface by surface, and a screen redesigned before its module existed was never revisited — `studentOutcome.ts` arrived on surface 10. **Third: the long-content pass found that one long student name pushed the per-row "Review →" button off the card at 1440**, because the review table is `table-layout: auto`; the action every row exists for left the screen because of one name, and no gate could see it (the adapt gate correctly exempts a deliberately scrollable region). **Fourth: `CameraCapture.tsx` was in neither gate list** and failed `rtlSafety` on the first run it was ever subjected to. Deliverable is `failureCopy.test.ts`, which **walks `src/` rather than reading a list** — and whose own first draft reported the quiet-hours validator's human-written sentence, i.e. a gate that reports good copy and teaches people to launder it through a module to stay quiet. 1,347 web unit tests, adapt gate 755/0, Python suite green. See D6.3. |
| | | | **6.1 `adapt` DONE, and it took two passes.** The first pass wrote the record and never ran the gate to green; running it produced **198 findings**, and three of the four defects were **in the gate itself**, which is the point worth carrying: a check reporting zero and a check reporting nonsense are both consistent with a green ledger row, and only looking at what it *named* separates them. (a) `aimedAt` resolved a control's label with `querySelector`, i.e. by document order, and `FileDrop` binds two labels to one input — a 13px caption and the drop zone a finger lands on — so **the product's largest tap target was reported as its smallest, 40 times, on the flow the whole product exists for**; choosing by area rather than markup order took `correct-paper` from 40 findings to 0 with no product change at all. (b) The comparison ran on the raw float while the finding printed `Math.round`, so a link hand-padded to 43.7px was reported as "44", a finding that appears to contradict its own rule; printing tenths is what made the next defect visible. (c) **It gave a different answer on identical runs** — three runs of `teacher-analytics` gave one finding, then two, then a different element, always at 43.95-44.0 on an element whose CSS floor is exactly 44px, because Chromium lays out in 1/64px LayoutUnits. A gate that changes its answer between identical runs is worse than the vacuous one it replaced, which was at least consistently wrong; fixed with 0.5px of tolerance, pinned so it cannot be widened, and applied to the spacing rule too so a control that clears the size rule cannot still count as `tiny`. (d) **A waiver that covered one rule and not the other**: the six-box OTP row is exempt from the size floor because six 44px boxes plus five gaps need 284px in a ~248px card, and that same arithmetic is exactly why they sit 4px apart — so the gate honoured the waiver on size and failed the same six inputs on **spacing** 30 times, findings no edit could clear without undoing the reason for the exemption. Now honoured on both rules, but only when **both** sides share the same waiver, and reported as `exemptPair` rather than dropped. The product defects underneath were real: `py-[11px]` is 43.7px not 44 at two hand-tuned call sites (both now state `min-h-11`, with `truncate` moved to an inner span because on a flex container the text is an anonymous flex item and `text-overflow` has nothing to apply to); the **bulk-approve checkboxes were 18px wide** — a bare `Checkbox` carries an `aria-label` and no visible text, so its label row collapses to the painted box, a target twice as tall as it is wide in the one place a teacher taps repeatedly; the only way out of a class on a phone was 19.5px tall; and three standalone controls had the block axis floored and not the inline one. **Final run: 745 page-states across 35 surfaces at 320/375/414/768/1440, 0 findings, 66 exemptions all from the OTP row.** `adaptRules.test.ts` is 14 tests (up from 9), the three new pins verified by inversion against the spelling that would actually be reached for. See D6.1 and D6.2 (redesign-era; they share IDs with build-era records and are disambiguated by title). |
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

### Gate status (current work unit)

```
WORK UNIT:          Phase 6.3 `optimize` - §5's six items (transform/opacity
                    animation, no blur on scrolling content, the z-index scale,
                    lazy images, skeletons that reserve space, a font-display
                    strategy). Two were already true, one was true for a reason
                    nobody had written down, and three led somewhere other than
                    where they pointed.
BUILD COMPLETE:     yes
INSPECTION ROUND:   1 (the 41-route audit IS the round here; a full before
                    corpus at `reports/phase-6.3-before/` measured against HEAD
                    before any edit)
FINDINGS TO FIX:    6, all fixed in one batch -
                    (a) **the phase's own premise was stale.** The
                        `reports/phase-6/` corpus (2026-08-12) showed CLS
                        0.2427/0.1807 on two teacher routes and the preload was
                        written before measuring; HEAD measures **41 routes, 0
                        over 0.1**, and the face it blamed
                        (`instrument-serif`) left the bundle in Phase 2.
                        Recorded as the first thing in D6.4 rather than
                        quietly dropped;
                    (b) **`registerSW.js` blocked first paint on 41 of 41
                        routes** - 403 bytes emitted by `vite-plugin-pwa`'s
                        default `injectRegister: "auto"`, parser-blocking in
                        `<head>`, for the whole redesign. In nobody's diff:
                        no gate here reads a dependency's build-time output;
                    (c) **the scan thumbnail could not be made lazy by making
                        the image lazy** - the bytes arrive as a `blob:` URL
                        before the element exists, and behind it
                        `GET /papers/{id}/preview` is an on-demand PyMuPDF
                        render while `GET /papers` is unpaginated, so opening
                        the grading console re-rendered every scan the school
                        has ever uploaded, at once;
                    (d) **`ConfidenceIndicator`'s tooltip declared a raw
                        `z-10`**, which is exactly `--z-index-sticky`
                        (`.z-sticky{z-index:10}` in the shipped bundle), so a
                        floating layer sat in the band reserved for the two
                        things most likely to cover it - live on the screen a
                        student reads their marks on. Three more raw values in
                        kit components; the scale was also being spelled two
                        ways (`z-nav` vs `z-[var(--z-index-sticky)]`);
                    (e) **four navbars, two blur values**, for a rule (§3.2
                        item 6) that permits exactly one thing, plus the
                        marketing header sitting in `z-sticky` while the other
                        three sat in `z-nav`;
                    (f) **nine non-latin font subsets were precached** -
                        `unicode-range` makes them free to a browser and a
                        service-worker install ignores it, so every first
                        visit downloaded 187KB of glyphs no English page in
                        this product can display.
CONFIRM ROUND:      1 - full 41-route after corpus at
                    `reports/phase-6.3-after/`. **Its composite Lighthouse mean
                    fell 1.61 and that is reported first**: ±11 swings landed
                    on routes this phase never touched, in both directions,
                    which is build-era D6.9 as written - one run cannot
                    separate *fixed* from *fast*. The claims rest on the
                    structural audits instead, each checked as a before/after
                    pair. Stopped per §3.2 item 16.
HALLMARK STAMP:     present on every touched `.tsx` (all edits to already-
                    stamped files, plus the new `lazy-chart.tsx`).
HOOK FINDINGS:      0 new (the three standing `index.css` findings from D6.2
                    remain deliberately left and are unchanged).
TESTS:              1,372 web unit (+25), all green; typecheck / lint (0
                    errors) / both builds / check:copy 0 (flat) / 28 Python
                    design-token tests / pre-commit: clean.
STRUCTURAL RESULT:  `registerSW.js` off the render-blocking list on **all 41
                    routes** (the stylesheet remains and must, so the audit
                    still fails 41/41 and "render-blocking fixed" would be
                    false); student-dashboard **CLS 0.098 -> 0**, the only
                    route that was over the ceiling; dashboard **unused JS
                    103KB/2 chunks -> 53KB/1**, the 50KB `nivoTheme` chunk gone
                    from first paint; **precache 146 -> 137 entries,
                    2621.92 -> 2435.27 KiB**, verified by building both ways.
                    Gate-failing routes 6 -> 3, **not claimed as an
                    improvement** given the noise above.
NEW GATES:          `tests/unit/elevationScale.test.ts` (8 tests) and
                    `tests/unit/fontPreload.test.ts` (11). Both **walk `src/`
                    rather than reading a file list** - three of the four
                    z-index offenders were in kit components no surface-derived
                    list would contain. The elevation gate's allowlist is
                    **derived from `index.css` every run**, so a renamed token
                    cannot leave it checking names the product no longer has.
                    Its blur/scroll rule parses **balanced class-expression
                    groups**, not lines: the four navbars are one-liners today,
                    so a line-based version would pass now and fail the first
                    time one was wrapped, on a diff that changed no behaviour
                    (proved by running the old logic against a wrapped-but-
                    correct navbar). **All verified by inversion**, both
                    directions.
NEW CAPABILITY:     `web/vite/fontPreload.ts` (build-time preload injection
                    that **throws** rather than silently emitting nothing),
                    `components/ui/lazy-chart.tsx`, `lib/hooks/useInViewOnce.ts`,
                    `--blur-nav`, `injectRegister: "script-defer"`,
                    `globIgnores` on the non-latin subsets,
                    `web/scripts/compare_audit.mjs` (before/after run
                    comparison, which mirrors `check_ui_gates.py`'s
                    student-routes-only performance floor rather than inventing
                    a uniform one), and `route-failures.json`.
HARNESS FINDING:    **Five routes die mid-run and no corpus had ever recorded
                    it** - T-08, T-09-detail, T-10, S-21, S-22, all on their
                    `loading` state, identically in the before and after runs,
                    so pre-existing. A route that dies on its *last* state has
                    already written its axe and Lighthouse rows, so the corpus
                    reads as a clean sweep; `audit.mjs` threw and named them on
                    stdout, but the run's output is not the corpus. Now written
                    to `route-failures.json` always (including `[]`), and read
                    by `check_ui_gates.py` under the convention it already
                    applies to the other two summaries: **missing is "not
                    checked", not "clean"**. The file lands on 6.4's run - the
                    change was written while 6.3's own run was in flight, and a
                    harness artefact must not be authored by hand.
```

### Gate status (Phase 6.2 harden, frozen)

```
WORK UNIT:          Phase 6.2 `harden` - the paper-upload and marking wait
                    (§6.2 names it outright), plus the error pass the same
                    sweep turned up.
BUILD COMPLETE:     yes
INSPECTION ROUND:   1 (batched, desktop 1440 + 375, correct-paper's two new
                    states)
FINDINGS TO FIX:    4, all fixed in one batch -
                    (a) **`UploadStatus.processing` had never been written by
                        any code path in the product.** A paper being marked
                        right now was indistinguishable in the database from a
                        scan somebody uploaded and abandoned, which is why
                        audit M4 (a reload loses the run) looked architectural
                        and was not: the run was never lost, only the record
                        that one was in flight;
                    (b) the platform console's "Uploads in flight" was
                        `pending + processing`, so it counted every abandoned
                        scan, forever, on the one panel whose job is answering
                        "is anything stuck?";
                    (c) **fifteen live sites still rendered an `Error`'s own
                        `message` to a reader**, six phases after the family
                        was first reported closed - including `Overview` and
                        `PaperResult`, surfaces 1 and 2, which answered a
                        dropped connection with "Failed to fetch", and two in
                        `CameraCapture` where the leaked text was pdf-lib's;
                    (d) a stopped run could not be restarted after a reload,
                        because the retry required the local `File` and the
                        `File` is what a reload destroys. The scan is on the
                        server; `canRetryInPlace` is the real test;
                    (e) **one long student name pushed the per-row "Review →"
                        button off the card at 1440.** The review table is
                        `w-full` with `table-layout: auto`, so a long name
                        grows its own column; the action every row exists for
                        left the screen because of one name. Found by the
                        first capture in this corpus that ever rendered a long
                        string, and invisible to the adapt gate by design (its
                        overflow rule correctly exempts a deliberately
                        scrollable region);
                    (f) `src/components/CameraCapture.tsx` was in **neither**
                        `rtlSafety` nor `utilityExistence` - surface 10's "a
                        file no gate reads", now on the camera half of the
                        flagship flow. Adding it failed on the first run:
                        `left-1` against §3.4.
CONFIRM ROUND:      1 - both new states captured at 1440 and 375 and read;
                    the recovered panel renders prose and no stage list, which
                    is the claim that needed a picture. Stopped per §3.2
                    item 16.
HALLMARK STAMP:     present on every touched `.tsx` (all were edits to
                    already-stamped files).
HOOK FINDINGS:      0 (impeccable design hook, every touched file)
TESTS:              1,347 web unit (+22), all green; typecheck / lint / build
                    clean; check:copy 0 (flat); full Python suite **3,699
                    tests, rc=0**, including 6 new backend tests.
ADAPT GATE:         re-run after the layout change: **755 page-states, 35
                    surfaces, 0 findings, 66 exempt** (the +10 are the two new
                    `correct-paper` states x 5 widths).
VISUAL ROUND:       24 captures - 14 on `correct-paper` (2 new states x 2
                    widths) and 10 on `teacher-review` (the new long-content
                    state), all distinct, console errors only from the
                    deliberately failing states.
NEW GATES:          `tests/unit/failureCopy.test.ts` - **walks `src/` rather
                    than reading a file list**, because the reason this defect
                    survived five fixes is that the outcome modules were
                    written surface by surface and a screen redesigned before
                    its module existed was never revisited. Its own first
                    draft reported `setQuietError(result.message)`, which is
                    this codebase's own validator writing a sentence for that
                    exact reader - **a gate that reports good copy teaches
                    people to launder good copy through a module to silence
                    it**, so it now requires an error-shaped receiver, and it
                    found a sixteenth site the manual grep had missed.
                    `tests/unit/uploadRun.test.ts` - the recovery decision as
                    logic (`lib/uploadRun.ts`), not as source text, because the
                    web runner is node-only and a source-reading gate cannot
                    tell a rule that works from one that still has the right
                    words in it. The two rules that are not expressible as a
                    function are read off the source and **stated as the
                    weaker evidence they are**.
                    **All verified by inversion**, on both sides.
NEW CAPABILITY:     `GET /student/uploads/active` and
                    `GET /student/uploads/{paper_id}`, `UploadRun` +
                    `get_run`/`get_active_run` on the upload repo,
                    `MARKING_RUN_STALE_AFTER`, `lib/uploadRun.ts`
                    (`runPhase`/`canStartRun`), `studentActionFailureMessage`,
                    and the `recovered` / `recovered-stale` capture states.
```

### Gate status (Phase 6.1 adapt, frozen)

```
WORK UNIT:          Phase 6.1 `adapt`, second pass - the gate's own three
                    defects, and the six product controls left once it was
                    measuring the right things.
BUILD COMPLETE:     yes
INSPECTION ROUND:   1 (batched - the gate IS the round here, 745 page-states
                    at 320/375/414/768/1440 in one run)
FINDINGS TO FIX:    4, all fixed in one batch -
                    (a) `aimedAt` picked a control's label by document order,
                        so `FileDrop`'s 13px caption stood in for the drop
                        zone and the product's largest tap target was
                        reported as its smallest, 40 times;
                    (b) the floor compared raw floats and printed
                        `Math.round`, so a 43.7px miss reported as "44";
                    (c) identical runs gave different answers, because a CSS
                        44px floor measures 43.95-44.0 in Chromium's 1/64px
                        LayoutUnits;
                    (d) the OTP row's stated waiver was honoured on the size
                        rule and not the spacing rule, producing 30 findings
                        no edit could clear.
CONFIRM ROUND:      1 - full run green (0 findings). Stopped per §3.2 item 16.
HALLMARK STAMP:     present on every touched `.tsx` (all four were edits to
                    already-stamped files).
HOOK FINDINGS:      3 on `index.css`, all deliberately left and stated in
                    D6.2: `--ease-spring`/`--ease-celebrate` overshoot by
                    design (§4 celebration register) and `ruled-bg`/`dotted-bg`
                    are §4's notebook texture, the one quality §1 protects.
                    Not suppressed - a waiver needs the human.
TESTS:              1,325 web unit (+14), all green; typecheck / lint /
                    build clean; check:copy 0 (flat).
ADAPT GATE:         **745 page-states, 35 surfaces, 0 findings, 66 exempt
                    (`six-digit-code-row`, stated).**
NEW GATES:          `adaptRules.test.ts` 9 -> 14 tests. The three new pins
                    (label chosen by area, sub-pixel tolerance on both rules,
                    waiver honoured only within itself) are **verified by
                    inversion against the spelling that would actually be
                    reached for**: reverting to `querySelector`, widening the
                    tolerance to 2px, and relaxing the pair waiver to "either
                    side is exempt" each fail exactly one intended test.
NEW CAPABILITY:     `exemptPair` reporting, `min-inline-size` on the bare-
                    checkbox label row (a no-op on every labelled checkbox in
                    the product), and inline-axis floors on the breadcrumb
                    crumbs, the landing sign-in links and the parent
                    overview's "See all".
```

### Gate status (Phase 5 motion, frozen)

```
WORK UNIT:          Phase 5.1/5.2/5.4 - motion. 26 snapping hovers, the result
                    reveal on two screens, press feedback on three controls,
                    and the one piece of motion the global reduced-motion block
                    could not reach.
BUILD COMPLETE:     yes
INSPECTION ROUND:   1 (batched, desktop 1440 + 375, three surfaces)
FINDINGS TO FIX:    4, all fixed in one batch -
                    (a) 26 elements changed colour on hover with no
                        `transition-*` at all, against §9.2's one rule stated
                        in units;
                    (b) §9.3's marked-paper result reveal had no
                        implementation, and `useCountUp` deliberately refuses
                        the first-observation animation it needs;
                    (c) `PracticeResult` could not distinguish a just-submitted
                        set from a revisited one, so it could not honestly
                        animate either;
                    (d) an explicit `scrollIntoView({behavior:"smooth"})`
                        overrode the global reduced-motion rule by spec.
CONFIRM ROUND:      1 - all four confirmed, no regression. Stopped per §3.2
                    item 16.
HALLMARK STAMP:     present on every touched `.tsx`.
HOOK FINDINGS:      0 (impeccable design hook, every touched file)
TESTS:              1,311 web unit (+7 beyond 5.3), all green; check:copy 0
                    (flat); typecheck / lint / both builds clean; full Python
                    suite green.
NEW GATES:          `tests/unit/hoverTransition.test.ts` (balanced
                    class-expression parsing, one named exemption),
                    `celebration.test.ts`'s reveal section (which path reveals,
                    hero-only, the `from` allowlist, and that each listed call
                    site actually gates rather than revealing unconditionally),
                    and `motionDefaults.test.ts`'s reduced-motion section (the
                    global block's three declarations; no unguarded literal
                    smooth scroll). **All three verified by inversion.**
NEW CAPABILITY:     `CountUp`'s `from`, `MarkDisplay`'s `reveal`,
                    `PracticeSet`'s `justSubmitted` navigation state, and press
                    feedback on `Tabs`/`Stepper`/`FileDrop`.
```

### Gate status (Phase 5.3, frozen)

```
WORK UNIT:          Phase 5.3 - charts. `lib/nivoTheme.ts`,
                    `components/ui/{line,bar}-chart.tsx`, the four chart call
                    sites (student momentum, cohort trend, at-risk trend, XP
                    per day), `MomentumDTO`'s wire change, and two new capture
                    surfaces.
BUILD COMPLETE:     yes
INSPECTION ROUND:   1 (batched, desktop 1440 + 375 together, four surfaces)
FINDINGS TO FIX:    6, all fixed in one batch -
                    (a) `var(--token)` would have drawn nothing, because Nivo
                        parses colours through react-spring; theme now resolves
                        off `:root` at runtime and fails closed;
                    (b) `MomentumDTO`'s 55-100% band clipped every percentage
                        under 55% outside its own viewbox, in an
                        `overflow-visible` element;
                    (c) `labels` was a year-month, so a month's papers shared
                        one point-scale key and collapsed to one point;
                    (d) the grade panel's `length === 0` empty test was
                        unreachable by construction;
                    (e) a count axis with four ticks rendered "0 0 0 1 1 1";
                    (f) the final x-tick clipped "Aug 11" to "Aug 1".
                    (e) and (f) were found only by looking at a capture.
CONFIRM ROUND:      1 - all six confirmed fixed against fresh captures, no
                    regression introduced. Stopped there per §3.2 item 16.
HALLMARK STAMP:     present on both emitted `.tsx` files.
HOOK FINDINGS:      0 (impeccable design hook, every touched file)
TESTS:              1,304 web unit (+49 incl. 37 new chart-theme tests), all
                    green; full Python suite green; check:copy **0** (flat);
                    typecheck / lint / both builds clean.
NEW GATES:          `tests/unit/chartTheme.test.ts` - every chart token exists
                    in `index.css`, no `var()` or colour literal survives in
                    any chart source, §11's series order holds, the accent
                    stays out of the categorical set, and no file under `src/`
                    imports `@nivo/*` outside the two wrappers. **Walks the
                    tree rather than reading a file list**, deliberately:
                    P4.10's finding was that the gate lists only grow by hand.
                    **Verified by inversion**: renaming a token, reinstating a
                    `var()` string, and importing Nivo directly in a screen
                    each fail exactly one intended test.
                    `test_overview_momentum_percentages_are_never_rescaled`
                    pins the clipping regression on the Python side.
NEW CAPABILITY:     `lib/nivoTheme.ts` (the theme, `SERIES_TOKENS`,
                    `useNivoTheme`, `useChartAnimation`),
                    `components/ui/line-chart.tsx`,
                    `components/ui/bar-chart.tsx`, `MomentumPointDTO`, and the
                    `teacher-analytics` / `teacher-student` capture surfaces.
```

### Gate status (Phase 4's last surface, frozen)

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

- **Decision IDs collide between the build era and the redesign.** `BUILD/DECISIONS.md`
  holds a build-era `D6.1`-`D6.12` and a redesign-era `D6.1`/`D6.2`, and the same is true
  of `D4.*` and `D5.*`. Every redesign record names its phase in its own title
  ("Redesign Phase 6.1 …"), so nothing is ambiguous when read, but a bare cross-reference
  to "D6.2" is. Not renumbered here: rewriting committed decision IDs unattended would
  break every citation already written into STATE and the phase notes. Phase 7's report
  should either adopt an `R`-prefix going forward or state the convention explicitly.
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

### Phase 6 deliverables (for later phases to read)

| Artefact | Path | Note |
|---|---|---|
| Run recovery (wire) | `GET /api/student/uploads/active` + `/{paper_id}` in `lemely/web/routers/student.py` | Two endpoints, not one, and the difference is the point: `active` stops naming a paper the instant it reaches a terminal status, so a client polling only that watches its run vanish without learning whether it was marked or failed. Discovery finds it, polling follows it. |
| The status that did not exist | `UploadStatus.processing`, written in `student_correct`'s `run()` | It shipped in the first migration and **nothing had ever written it**. Written at the top of the worker (not in the endpoint body) so the status is only ever set when a thread exists to clear it, and inside the `try` so a throw still reaches `bus.publish_done()`. |
| Staleness bound | `MARKING_RUN_STALE_AFTER` in `routers/student.py` | Not a timeout and it cancels nothing. It is the point past which "still marking" is a claim with nothing behind it, because the only way a row stays `processing` is a process that died holding it. Computed server-side: the server owns the clock the timestamp came from. |
| Recovery decision | `web/src/lib/uploadRun.ts` | `runPhase`/`canStartRun`. Extracted from the screen so it can be tested as logic — the web runner is `environment: "node"` with no jsdom, so anything left inside a component can only be pinned by reading its source. `canStartRun` is the guard against a second run over one scan (double spend, second attempt row, cross-talk on a single-stream bus). |
| Recovery hooks | `useActiveUpload` / `useUploadRun` in `useStudentApi.ts` | `RUN_POLL_MS` is 4s and pinned not to drop below 2s: every poll is a request from a phone on the connection this path exists to survive. |
| Failure-copy gate | `web/tests/unit/failureCopy.test.ts` | No `Error.message` reaches a render, anywhere under `src/`. **Walks the tree; do not give it a file list** — a list is what let this survive five previous fixes. Requires an error-shaped receiver, because its first draft reported the quiet-hours validator's own human-written sentence. |
| Action failure copy | `studentActionFailureMessage` in `studentOutcome.ts` | For a button, not a form. The save helper leads with "Nothing you typed has been lost", which is right for a form and confusing after a tap. Keeps the action in the sentence because two actions can fail on one screen. |
| Recovered-run captures | `reports/redesign/p4-correct-paper/correct--recovered*` | The claim needing a picture is what is **absent**: no three-stage panel. A recovered reader knows the run is going and nothing else, so ticking stages off a status word would be S-14's invented progress. |
| Adapt gate | `web/scripts/adapt_audit.mjs` | §6.1's five mobile non-negotiables, **measured**, not screenshotted — four of the five are invisible in a picture. Walks `capture_surface.mjs`'s `SURFACES` registry by import rather than a list of its own, deliberately (P4.10). `npm run build` first; it serves `dist/` and takes ~25 minutes for the full 745 page-states. Read its header before changing a rule: the obvious horizontal-scroll test can never fire in this codebase, because `overflow-x: clip` suppresses the scroll it asks about. |
| Adapt gate's pins | `web/tests/unit/adaptRules.test.ts` | 14 tests over the gate's own source. Exists because the gate is the only thing checking the gate. Three pins guard defects the second pass found: the label is chosen by **area** (not document order), the floor carries **0.5px** of tolerance on *both* rules and may never be widened past it, and a call-site waiver is honoured on spacing only when **both** sides share the same one. |
| Touch-floor waiver | `data-touch-floor-exempt="<reason>"` | The only way out of the 44x44 floor, and it must state its reason at the call site. Reported as `exemptTarget`/`exemptPair` on every run, never hidden: a gate that conceals its carve-outs is the vacuous-gate defect wearing a different hat. One user today, the six-digit OTP row. |
| Bare-checkbox floor | `min-inline-size` in `web/src/index.css` | A `Checkbox` with an `aria-label` and no visible text collapses its label row to the painted box (18px). The inline floor is a no-op on every labelled checkbox in the product and exists solely for that case, which is the teacher review queue's bulk-approve column. |

### Phase 5 deliverables (for later phases to read)

| Artefact | Path | Note |
|---|---|---|
| Chart theme | `web/src/lib/nivoTheme.ts` | DESIGN.md §11 in code. **Resolves tokens off `:root` at runtime, and this is not optional**: Nivo hands colours to react-spring, which parses them, so `var(--accent)` arrives as nothing. Read the header before touching it. Fails closed via `ready`. |
| Chart wrappers | `web/src/components/ui/{line,bar}-chart.tsx` | The only two places a chart may be configured. Both sit inside `ChartFrame`, which owns §11's mandatory empty state so there is no children-only path that skips it. Focusable, labelled points. Do not import `@nivo/*` anywhere else. |
| Chart motion | `useChartAnimation()` in `nivoTheme.ts` | Reads `prefers-reduced-motion` **live**, unlike `Reveal`, which reads once at mount. A chart is long-lived and re-renders as its data changes; a scroll entry is not. |
| Semantic bar colour | `colorFor` on `BarChart` | For a chart whose colour means something (the grade bands). Must return a resolved value, never `var()`. Not a hook for hand-picking a palette. |
| Chart gate | `web/tests/unit/chartTheme.test.ts` | Token existence, no `var()`/literals, §11 series order, no stray `@nivo` imports. **Walks `src/` rather than reading a list** — do not add a file list to it. |
| Momentum wire | `MomentumDTO` in `lemely/web/schemas_student.py` | Now `points: [{recordedAt, percentage}]`. It shipped SVG path data until P5.3, and that transform clipped everything under 55% out of its own viewbox. Its docstring records both defects; do not put geometry back on the wire. |
| Chart captures | `reports/redesign/p5-{student-dashboard,profile,teacher-analytics,teacher-student}/` | 36 states x 1440/375. `teacher-analytics` and `teacher-student` are **new surfaces** — neither screen had ever been captured. |
| Snapping-hover gate | `web/tests/unit/hoverTransition.test.ts` | §9.2's hover rule, as a check. Parses **balanced class-expression groups**, not lines — a line-based version reports `Button` as broken. Ignores hovers nothing can animate. One named exemption. |
| Result reveal | `CountUp`'s `from` + `MarkDisplay`'s `reveal` | §9.3's marked-paper reveal. `from` opts a **first** observation into animating, which the default refuses on purpose. Only for a value that arrived while this reader watched, and only on a path that can prove it. No flourish at any mark, ever — see the prop's docstring for why. |
| Just-submitted signal | `justSubmitted` in `PracticeSet` → `PracticeResult` | The evidence that distinguishes a result the student waited for from one they reopened. A screen without it must not animate. |
| Reveal allowlist | `celebration.test.ts` | Two call sites, each with its reason, and a test that each one actually *gates* rather than sitting on the list revealing unconditionally. Adding a third needs the same proof. |
| Reduced-motion gate | `motionDefaults.test.ts` | The global block's three declarations, plus: no literal `behavior: "smooth"` without `prefersReducedMotion`. The CSS `!important` does not reach an explicit JS scroll. |
| Motion captures | `reports/redesign/p5-{paper-result,practice-result,landing}/` | Note the count-up is transient and not in any image; the unit gates cover the wiring. |

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
