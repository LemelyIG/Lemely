# Live run I9 (T33): UI audit of the tutoring marketplace on the live stack

Lock owner T33 (held for the lead; not released by T33). Browser: system Chromium (`PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium`).
All numbers are from the dedicated-database runs of `scripts/tutoring/live_audit.sh dedicated`
(`lemely_tutoring_e2e`, shared `postgres` stayed at `0043_merge_heads`, verified each run).

## Verdict

- **Tutoring routes: green.** 23 of 23 SPEC §d gate routes registered and audited in 141 states (axe on every state):
  **0 critical, 0 serious, 0 moderate, 0 minor** in every state; Lighthouse accessibility **100** on all 23 routes;
  Lighthouse performance >= 80 on every gated route (`/tutors`, `/tutors/:id`, every `/student/*` one); 0 console errors;
  0 horizontal-scroll violations at 320 px; 0 route failures. Scoped run (`LEMELY_AUDIT_SCOPE=tutoring`, report dir
  `reports/.scratch/t33-run2`) ended `PASS (exit 0)` with `check_ui_gates.py` clean.
- **Whole-product run (`reports/.scratch`, the acceptance command): still FAIL, on 21 gate violations that are all outside the
  tutoring files** (listed under "What remains"). Before T33 this command could not run at all (five stale entries and a broken
  signup step, see "Audit runner repairs"), so these were invisible; none can be attributed to this branch without a
  `develop` run, and none is in a file T33 owns.

## Per route (full run, final HEAD)

| Route | Slug | Perf | A11y | Gated perf |
|---|---|---|---|---|
| `/tutors` | tutors-directory | 86 | 100 | yes (slug) |
| `/tutors/:id` | tutors-public-card | 85 | 100 | yes (slug) |
| `/student/tutors` | student-tutors | 84 | 100 | yes |
| `/student/tutors/:id` | student-tutor-profile | 81 | 100 | yes |
| `/student/tutors/:id/book` | student-tutor-book | 87 | 100 | yes |
| `/student/sessions` | student-sessions | 83 | 100 | yes |
| `/student/sessions/:id` | student-session-detail | **80** | 100 | yes, no margin |
| `/student/tutor-access` | student-tutor-access | 81 | 100 | yes |
| `/teacher/tutoring` | teacher-tutoring-home | 85 | 100 | no |
| `/teacher/tutoring/profile` | teacher-tutoring-profile | 87 | 100 | no |
| `/teacher/tutoring/availability` | teacher-tutoring-availability | 83 | 100 | no |
| `/teacher/tutoring/sessions/:id` | teacher-tutoring-session | 86 | 100 | no |
| `/teacher/tutoring/students` | teacher-tutoring-students | 84 | 100 | no |
| `/teacher/tutoring/students/:id` | teacher-tutoring-student | 74 | 100 | no |
| `/teacher/tutoring/preview` | teacher-tutoring-preview | 82 | 100 | no |
| `/parent/children/:id/tutoring` | parent-child-tutoring | 82 | 100 | no |
| `/parent/children/:id/sessions/:id` | parent-child-session | 78 | 100 | no |
| `/parent/tutors` | parent-tutors | 79 | 100 | no |
| `/parent/children/:id/tutor-access` | parent-child-tutor-access | 81 | 100 | no |
| `/platform/tutors` | platform-tutors | 82 | 100 | no |
| `/platform/tutors/:id` | platform-tutor | 82 | 100 | no |
| `/platform/moderation` | platform-moderation | 86 | 100 | no |
| `/platform/reports` | platform-reports | 86 | 100 | no |

`/platform/reports/:id` (X-07 detail) is audited for axe and screenshots only (not on the SPEC list). Lighthouse runs on each
route's default state only (SPEC D3.17).

Performance is thin everywhere on this machine: the older student routes score 70 to 80 in the same run (phase 6 had 92 to 95),
so the floor is an environment-borderline gate for the whole product. S-37 sits at 80 (79 in a run that shared the CPU with a
test run, 80 in two idle runs). Every score is dominated by the shared shell (FCP 2.5 s, one 0.064 layout shift on all student
routes, 62 KiB unused JS, 750 ms render-blocking CSS); the tutoring chunks are 1 to 4 KB each. Do not re-run the audit while
anything else is using the CPU.

## What T33 built

- `web/scripts/audit_tutoring_registry.mjs` (new): 47 entries, 141 states for the 24 screens. States per screen: default,
  loading, error, offline (aborted request, so the screen's own offline panel), dark, plus the SPEC ones: G-16 empty, G-17
  unlisted, S-33 empty, S-34 results-table / insufficient / not-listed, S-35 safety-notice (C-24 open), S-36 past / empty, S-37
  completed / cancelled-late / awaiting-outcome / expired, S-38 stop-sharing-sheet / empty, T-15 no-profile / draft, T-16
  onboarding, T-18 requested / completed, T-19 empty, T-20 access-ended (403), X-04 listed. Sessions: `platform_admin`
  (`seed.tutoring.platformAdmin`), signed-out (G-16, G-17), student (booking student, and the "new" student for empties),
  tutor (sufficient, insufficient, draft), teacher with no profile, parent.
- Every `ready` is built from an `expect` (heading, text, alert, status, loading) by `waitForExpectation`, which also requires the
  route's own pathname, no `alert` on a non-error state and no loading skeleton on a non-loading state. A login redirect,
  a 404 or a crash page can never satisfy one (P28). The same function found two real defects while being written: a G-17
  loading state with no `h1`, and an S-34 "loading" that was only the route chunk's fallback.
- `web/scripts/audit.mjs`: imports the registry; `breakpoints` per entry or state (320/768/1280 for tutoring, 380/768/1440
  unchanged elsewhere); `--dark` suffix on dark captures (`default--1280--dark.png`); animations settled before each shot
  (the first S-38 sheet was captured half transparent); fixed bottom nav hidden for tutoring full-page shots;
  `LEMELY_AUDIT_SCOPE=tutoring` and `LEMELY_AUDIT_SCREENS=S-33,S-37` for fast re-runs (partial reports, never evidence for the
  whole product).
- `scripts/check_ui_gates.py`: `PERF_GATED_TUTORING_SLUGS = ("tutors-directory", "tutors-public-card")`; student routes are gated by path.
- Tests: `web/tests/unit/auditTutoringRegistry.test.ts` (30; parses the SPEC list, asserts 23, set equality with the registry,
  one Lighthouse default per route, per-state expectations, and runs the real predicate over a fake page), additions to
  `tests/test_check_ui_gates.py` (25 total) and `web/tests/unit/tutoringSessionScreens.test.ts`, `gradeChangeSummary.test.ts`.

## Fixes in the tutoring files

| Defect | Fix |
|---|---|
| S-38 focus fell to `body` after Stop sharing | `TutorAccess.tsx`: `useFocusWhenRowGone` on the live grants, sheet unmounted, focus to the Sharing heading. Checked in a browser: `activeElement` is `H2#tutor-access-sharing` |
| G-17 loading state had no `h1` (axe `page-has-heading-one`) | `TutorPublicCard.tsx`: sr-only "Tutor profile" above the skeleton |
| C-18 "lower grade" segment (hairline token as a fill, about 1.4:1 light, 1.6:1 dark) | `grade-change-summary.tsx`: solid `ink-faint` / hollow `paper-sunk` with `ink-muted` outline / solid `ink`; legend wraps whole items |
| Touch targets under 44 px on back links, the ranking disclosure, the meeting link and grant-row names | `min-h-11` / `py-3` in `TutorProfileEditor`, `Availability`, `MyStudents`, `TutorSessionDetail`, `TutorStudentDetail`, `FindTutor`, `ParentFindTutor`, `session-detail-view`, student and parent `TutorAccess` |
| Attempt-history table at 320 px (T-20) | Already contained: no overflow at 320, 768, 1280 (screenshot read) |
| Design tokens | No raw colour, `px` or `rem` literal and no inline `style` in any owned file (grep); none to fix |

## Audit runner repairs outside the tutoring registry (pre-existing)

The acceptance command failed before any tutoring route was reached. Repaired in `web/scripts/audit.mjs`: signup needed
`acceptedTerms` (422, since D7.11), and the fresh student needs its email verified and onboarding completed through the API
(as `web/e2e/screenshots.spec.ts` does) before it can mark a paper; G-05 `/login/parent` was retired with phone login (404), so its
entry is removed (a parent signs in on `/login`, G-04); G-01 `/student/landing` redirects to `/landing` (new ready text);
S-32 heading is now "Parent access"; T-01 empty is redirected to `/teacher/first-class`; T-01 offline now aborts the overview request
because current Chromium applies CDP offline emulation to a service-worker navigation (`ERR_INTERNET_DISCONNECTED` on the goto).

## What remains, and why (ranked)

All outside T33's files; none is a tutoring screen.

1. **Critical axe, 8 states on 5 screens** (shared components): `aria-valid-attr-value` on the paper result's tab button
   (`aria-controls` pointing at a panel that is not rendered; student-result, -print, -dark, -print-dark); `aria-allowed-attr`
   on the card `div.outline-none` with `aria-haspopup="dialog"` (flashcards due and settled, notifications populated) and on a
   `span` chip inside the onboarding questionnaire's skipped state (3 nodes).
2. **Lighthouse perf < 80 on 10 older gated routes** (student-result 79, practice-generator 78, flashcards-due 78 and a11y 94,
   flashcard-review 79, study-plan-week 79, announcements 79, standings 77, friends 77, profile 70, landing 78) and
   teacher-class-analytics 68. Same shell cost as above; phase 6 recorded 92 to 95.
3. **4 console errors**: `navigator.vibrate` called before a user gesture on `/student/flashcards/review/0625`
   (`lib/haptics.ts` should check `navigator.userActivation.hasBeenActive`).
4. Moderate only (not gated): `heading-order` and `landmark-unique` on teacher quiz detail; `page-has-heading-one` on
   practice-generator (3 states) and study-plan states.
5. **Shared primitives, tap targets** (not owned): with touch emulation (`pointer: coarse`) every `Button` reaches 44 px
   (`pointer-coarse:min-h-11`), so the 32 px figures seen with a mouse are the primitive's fine-pointer size. Still under 44 px on
   touch: Radio and checkbox rows (41 px), the marketing wordmark link (32 x 44), the parent header icon buttons (32 x 28),
   the email-verification banner link and dismiss (20 and 22 px). `StateView` retry and `BackControl` pass on touch.
6. **Backend, report only**: `lemely/web/student_detail_view.py:187` prints an ISO date in the inactive-flag sentence
   ("last active 2026-10-11"). The at-risk summary text also uses `->` arrows (`82% -> 68% -> 55%` on T-20).
7. **X-07 detail** shows the report snapshot raw (`in_person`, `2026-10-17T15:00:00+00:00`, `false`). `snapshotRows` is
   pinned by `adminTutoring.test.ts` to plain values, so it was left; humanise the values if the admin should read dates.
8. The two shared `TutorFailure` sr-only h1s: no defect found (each failure state has exactly one `h1`; the gate's `anyH1` check
   passes on all of them). Fonts: the live run uses the real build, type renders correctly in the screenshots (Newsreader, Geist, JetBrains Mono).
9. Full-page captures: the fixed desktop sidebar is painted once at the viewport height, so tall 1280 shots show it stopping
   at 900 px. A capture artefact, not a layout defect.

## Mutation proofs

On export `T33-m1` (deleted): G-16 default `ready` pointed at `/login` -> `auditTutoringRegistry.test.ts` "makes every ready wait on its
own route's pathname" red; `waitForExpectation` without the pathname test -> "rejects a login redirect" red; X-06 path changed ->
3 tests red; S-38 `markStopped` removed -> `tutoringSessionScreens.test.ts` red; C-18 lower segment back to `fill-rule-strong` -> 2 tests
red; `tutors-directory` removed from the perf slugs -> 3 pytest cases red. Each restored green.
**Live:** the same G-16 mutation on the export, run through `audit.mjs` (`LEMELY_AUDIT_SCREENS=G-16`): `!! G-16 /tutors FAILED:
Waiting failed: 20000ms exceeded`, `route-failures.json` holds the entry, `check_ui_gates.py` exits 1 ("route: G-16 /tutors could not be
audited"). Restored: exit 0, route-failures `[]`.

## Evidence paths (gitignored)

- Full run: `reports/.scratch/` (`axe/`, `lighthouse/`, `screens/`, `contact-sheet.html`, `console-errors.json`), log `reports/.scratch/t33-full.log`.
- Tutoring-only passing run: `reports/.scratch/t33-run2/`, log `reports/.scratch/t33-run2.log`.
- Screenshots: `reports/.scratch/screens/<screen-id>/<state>--<320|768|1280>[--dark].png`, 375 PNGs for the 24 tutoring screens.
  Read and checked: T-20 and S-34 dark, S-35 safety notice at 320, S-38 sheet at 768, X-07 detail, T-16/T-17/P-08/S-33 at 320. No clipping,
  overlap or unreadable dark mode; defects seen were the three artefacts and the C-18 ramp above.
