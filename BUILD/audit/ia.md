# Information Architecture — current map and proposed changes

Scope: `web/src` SPA only. Route source of truth: `web/src/App.tsx:66-125` (top-level) +
`web/src/portals/{student,teacher,parent}/index.tsx` (per-portal `RouteObject` trees).
Cross-checked against `docs/LEMELY_UI_SPEC.md` (screen IDs quoted below, e.g. `S-06`, `K-01`)
and `web/e2e/*.spec.ts` (13 files) for which routes have test coverage riding on their
current shape.

## 1. Current IA — full page tree per role

### Top level (outside any portal), `web/src/App.tsx:66-125`

| Path | Element | Guard | Notes |
|---|---|---|---|
| `/` | `Root` → redirect | none (reads session) | Redirects to the caller's portal home, or `/login` if signed out. `App.tsx:55-58`. |
| `/login` | `Login` | `LoginRoute` (redirects away if already signed in) | Email/password. Explicitly "not final UI" per its own author comment (`Login.tsx:11-14`). |
| `/login/parent` | `ParentLogin` | `LoginRoute` | Phone-OTP entry point (G-05). |
| `/settings/devices` | `DeviceSettings` | `RequireAuth`, `ALL_ROLES` | 3-device registry (G-11), shared by every role. |
| `/settings/notifications` | `NotificationSettings` | `RequireAuth`, `ALL_ROLES` | At-risk alert preference (G-12), scoped in practice to teacher+parent per backend, but the route itself admits all roles. |
| *(no `*` / catch-all)* | — | — | Confirmed absent — see diagnose.md. |

### Student portal — `web/src/portals/student/index.tsx:259-289`, guard `RequireAuth(["student"])`

Base path `/student`, sidebar nav defined in `web/src/portals/student/data.ts:53-85`
(`navGroups`: **Student**, **Marking**, **Elsewhere**).

```
/student                                  Overview (index)                [nav: Student > Overview]
/student/subject/:code                    Subject drilldown                [nav: Student > Physics 0625, hardcoded to one subject]
/student/result/:paperId                  PaperResult
/student/correct                          CorrectPaper                    [nav: Marking > Correct a paper; also global header CTA every screen]
/student/plan/:subjectCode                StudyPlanWeek                   [nav: Student > Study plan, hardcoded 0625]
/student/plan/:subjectCode/session/:sessionId   StudyPlanSession
/student/board                            Standings                      [nav: Student > Standings]
/student/announcements                    Announcements                  [nav: Student > Announcements]
/student/notifications                    Notifications                  [NOT in navGroups — see gap below]
/student/friends                          Friends                        [nav: Student > Friends]
/student/profile                          Profile                        [nav: Student > Your profile]
/student/parents                          Parents (link a parent)        [nav: Student > Your parents]
/student/onboard                          Onboarding                     [nav: Elsewhere > Onboarding]
/student/placement/:subjectCode           PlacementInvite                [NOT in navGroups]
/student/placement/test/:assignmentId     PlacementTest                  [NOT in navGroups]
/student/placement/result/:assignmentId   PlacementResult                [NOT in navGroups]
/student/practice/:subjectCode            PracticeGenerator              [nav: Student > Practice, hardcoded 0625]
/student/practice/set/:assignmentId       PracticeSet                    [NOT in navGroups]
/student/practice/result/:assignmentId    PracticeResult                 [NOT in navGroups]
/student/practice/print/:assignmentId     PracticePrint                  [NOT in navGroups]
/student/flashcards/:subjectCode          FlashcardDecks                 [nav: Student > Flashcards, hardcoded 0625]
/student/flashcards/review/:subjectCode   FlashcardReview                [NOT in navGroups]
/student/landing                          Landing (public marketing page)[nav: Elsewhere > Landing page]
/student/directions                       Directions (design gallery A/B/C)[nav: Elsewhere > Directions]
```

Chrome: fixed left sidebar (`Sidebar()`, `index.tsx:134-192`) + sticky header with
breadcrumb + global "Correct a paper" CTA (`Header()`, `index.tsx:194-230`) + a hardcoded
link out to `/teacher` at the bottom of the sidebar (`index.tsx:185-187`, `"Open the
teacher portal →"` — present on every student screen regardless of whether the signed-in
account holds a teacher role).

**Sidebar nav item count:** 10 items across "Student" + 1 under "Marking" + 3 under
"Elsewhere" = 14 links, against 24 actual routes. 10 routes have no persistent nav entry at
all (notifications, both placement sub-flows' 3 sub-steps, practice's 3 sub-steps,
flashcard review) — all reached only by CTA/deep-link from within another screen, which is
fine for step-flow routes (placement test, practice set) but not for `notifications`, a
persistent-utility screen with no obvious in-flow entry point other than presumably a bell
icon that was not found in the header (`Header()` renders only the breadcrumb and the
"Correct a paper" button, `index.tsx:218-229` — no notification bell/link).

**The "Elsewhere" group is dev/QA navigation shipping in the production sidebar**: every
signed-in student sees links labelled "Landing page" and "Directions" (a static
three-treatment design-comparison gallery, per its own comment "this screen is a static
design gallery, not live data" — `Directions.tsx:6-11`) between their real study links and
sign-out. `grep -rn "student/landing\|student/directions" web/src --include=*.tsx` outside
`data.ts`/`index.tsx` returns nothing — i.e., nothing in the product *itself* links to
these two routes; they exist solely as this sidebar entry.

### Teacher portal — `web/src/portals/teacher/index.tsx:254-284`, guard `RequireAuth(["teacher","school_admin","platform_admin"])`

Base path `/teacher`, sidebar nav defined in `web/src/portals/teacher/data.ts:38-46`
(`navItems`, flat list, no groups) + a dynamic "Your classes" section
(`ClassesNavSection`, `index.tsx:98-143`, capped at 5 + "See all").

```
/teacher                                          Overview (index)          [nav: Overview]
/teacher/grading                                  Grading                   [nav: Grading]
/teacher/review                                    Review (queue, T-07)     [NOT in navItems — CTA-only, see gap below]
/teacher/review/:itemId                            ReviewItem (T-08)
/teacher/classes                                   Classes                  [nav: Classes]
/teacher/classes/:classId (layout)                 ClassDetailLayout
  → index                                          ClassRoster
  → /analytics                                     ClassAnalytics
/teacher/students/:studentId                       StudentDetail            [NOT in navItems — reached from roster/at-risk only]
/teacher/at-risk                                   AtRiskList               [nav: At-risk students]
/teacher/schemes                                   MarkSchemes              [nav: Mark schemes]
/teacher/quizzes                                   Quizzes                  [nav: AI quizzes]
/teacher/quizzes/:quizId                           QuizBuilder
/teacher/quizzes/:quizId/assignments/:assignmentId/results  QuizResults
/teacher/announcements                             Announcements            [nav: Announcements]
```

Chrome: fixed left sidebar (no breadcrumb header, unlike student — `TeacherLayout`,
`index.tsx:239-252`, content area has no `Header()` equivalent at all), a class list, and
footer links to `/settings/devices` and `/student` (`index.tsx:216-227`).

**`/teacher/review` has no sidebar entry.** Per PRODUCT.md, the review queue is one of the
product's three positioning pillars ("the system knows when it doesn't know... low-confidence
results are flagged into a human-review queue surfaced to teachers", `PRODUCT.md:47`) and
per the UI spec it is screen T-07. It is reachable only via an inline CTA on `Overview`
(`Overview.tsx:129`) and `Grading` (`Grading.tsx:305`) — a teacher who is not currently on
one of those two screens has no persistent path to it. Confirmed via
`grep -rn "teacher/review" web/src --include=*.tsx`: two CTA `navigate()` calls, zero
`NavLink`/sidebar entries.

### Parent portal — `web/src/portals/parent/index.tsx:156-165`, guard `RequireAuth(["parent"])`

Base path `/parent`. Deliberately nav-less by design, per an inline citation of the UI
spec: *"Total depth from login to the answer a parent came for: two taps... there is no
sidebar and no nav list"* (`index.tsx:26-31`, quoting UI spec §4.8).

```
/parent                                    Children (list, index)
/parent/children/:childId                  ChildOverview
/parent/children/:childId/subjects/:code   SubjectDetail
/parent/children/:childId/weaknesses       Weaknesses
```

Chrome: header only (logo/home link, child switcher `<select>` shown only when >1 child,
Settings link, Sign out) — `Header()`, `index.tsx:84-136`. No footer, no breadcrumb. This
is the leanest of the three portals and matches its spec intent closely.

### School admin and platform admin — **do not exist in the frontend**

Verified, not assumed. `find web/src -iname "*admin*"` returns zero files. The only two
appearances of `school_admin`/`platform_admin` anywhere in `src` are role strings inside
the teacher-portal's `RequireAuth` allow-list (`App.tsx:49`) and a comment in
`RequireAuth.tsx:39-42` explicitly stating the deferral:

> *"`school_admin` and `platform_admin` still resolve to `/teacher`, which is deliberate...
> Their dedicated surfaces (K-01, X-01) are Phase-5/6 work."*

The UI spec defines 7 admin screens that have no route, no component, and no nav anywhere
in the SPA: `docs/LEMELY_UI_SPEC.md:264-270` —

| Spec ID | Screen | Role |
|---|---|---|
| K-01 | School dashboard | School admin |
| K-02 | Seats & student accounts | School admin |
| K-03 | Teachers | School admin |
| K-04 | Classes (school-wide) | School admin |
| X-01 | Platform admin console | Platform admin |
| X-02 | Account activation queue | Platform admin |
| X-03 | Pipeline & corpus health | Platform admin |

An account with `role: "school_admin"` or `role: "platform_admin"` today lands, on login,
inside the *teacher* dashboard (`portalPathForRole()`, `RequireAuth.tsx:44-48`), sees the
teacher sidebar, and every panel operates against `/api/teacher/*` endpoints — which
PRODUCT.md confirms those two roles "genuinely hold... so the screens there genuinely serve
them" for now (`App.tsx:46-48` comment), i.e. this is a documented interim stand-in, not a
silent bug, but it is a real product gap against the UI spec's 5-role scope and against
REDESIGN-MISSION's explicit inclusion of "school-admin and platform-admin views" in scope
(`BUILD/REDESIGN-MISSION.md:25`).

## 2. Key task-path walkthroughs (step counts from a cold landing)

**Student: "get a paper marked" (the core loop).**
`/` → (session exists) redirect to `/student` (Overview) → click "Correct a paper" header
CTA (present on every student screen) → `/student/correct` (CorrectPaper: capture/upload) →
on completion, presumably navigates to `/student/result/:paperId`.
**Steps from portal-home to the marking screen: 1 tap** (the CTA is globally present in the
header, not just on Overview — `Header()`, `index.tsx:221-227`). This is genuinely good and
matches the "one obvious step away" bar the mission asks Phase 3 to hit; no IA change is
proposed for this path.
**Steps from a cold `/` with no session: 1 more** (must pass through `/login` first) — 3
steps total (login → land on Overview → tap CTA), which is unavoidable and not an IA
defect.

**Student: reach `/student/notifications`.**
Not in `navGroups` at all (see IA map above). No bell icon or equivalent was found in
`Header()`. The only route found linking to it is presumably an announcement/push-tap deep
link (`pushDecision.ts:62` comment says push notifications resolve here as "the one
destination that cannot 404 for the reader") — meaning a student who never receives a push
has **no in-app path to their own notifications screen at all**. This is a genuine dead
end, not merely an extra click.

**Teacher: "review a low-confidence marking" (T-07/T-08, a core positioning pillar).**
`/` → `/teacher` (Overview) → the queue is surfaced only as a conditional CTA that appears
when there's something to review (`Overview.tsx:24,129`) — if a teacher navigates away
(e.g. to Grading, Classes, Schemes) there is **no path back to Review except browser Back
or re-visiting Overview**, since it is absent from the persistent sidebar. Once on
`/teacher/review`, opening an item is 1 more tap → `/teacher/review/:itemId`.
**Steps when the CTA is visible: 2. Steps once the teacher has navigated elsewhere in the
app: return-to-Overview-first, i.e. effectively 3+ with a wrong turn.**

**Parent: "check on a linked child's weak topics" (the spec's own 2-tap bar).**
`/login/parent` (OTP) → `/parent` (Children list, or auto-skip to the one child's
`ChildOverview` — behavior not independently verified, see Not-reached in diagnose.md) →
tap into `/parent/children/:id` → tap "Weaknesses" → `/parent/children/:id/weaknesses`.
**As built this is 2 taps after landing on the child's overview** (child list → overview is
tap 1, only needed with >1 child; overview → weaknesses is tap 2), matching the spec's
explicit 2-tap requirement (`index.tsx:26-27` quoting UI spec §4.8). No IA change proposed
here — this path is already correctly shaped.

**School admin / platform admin: any task.**
No path exists. `role: school_admin` or `role: platform_admin` → redirected into
`/teacher`, a dashboard built for a different job. There is no task path to audit because
the destination screens do not exist (see §1).

## 3. Proposed IA changes

| # | Change | Rationale | Cost | Breaks a deep link? |
|---|---|---|---|---|
| 1 | Remove the "Elsewhere" nav group (`Landing page`, `Directions`) from the student production sidebar (`web/src/portals/student/data.ts:79-84`). Keep the routes themselves reachable at their current paths for internal/QA use, or move them behind a dev-only flag, but stop surfacing them to real signed-in students. | These are internal QA artifacts (a static design-comparison gallery and an orphaned marketing page) shipping as top-level nav items visible to every real student account between their study tools and sign-out. Confuses the "one obvious step away" goal by adding noise that leads nowhere useful for a student. | Trivial: a 6-line edit to `data.ts`. No screen deletion required (mission's non-destructive rail is satisfied — routes can stay mounted, just unlinked). | No. Nothing else in the app links to `/student/landing` or `/student/directions` (confirmed by grep); no e2e spec visits either path (`grep -rn "goto(" e2e` has no hit for `landing` or `directions`). |
| 2 | Add `/teacher/review` to the teacher sidebar `navItems` (`web/src/portals/teacher/data.ts:38-46`), with a badge/count for open items if the API returns one (`Review.tsx` already fetches `GET /teacher/review?...`). | Review is one of the product's three named positioning pillars (PRODUCT.md's method-mark/confidence pillar) and a T-07 spec screen, currently reachable only via a conditional CTA on two other screens. A teacher who has navigated to Classes, Schemes, or Quizzes has no way back to the queue except Overview. | Small: 1 new `NavItem` entry + 1 new Phosphor icon mapping in `NAV_ICON` (`index.tsx:49-57`). No route change. | No. Adding a nav entry to an existing route cannot break a deep link; `at-risk-flags.spec.ts` and others that `goto("/teacher/review"... )`-adjacent routes are unaffected since the path itself is unchanged. |
| 3 | Give the student portal a notifications entry point: either add `/student/notifications` to `navGroups` or add a bell affordance to the sticky `Header()` (`web/src/portals/student/index.tsx:194-230`). | Currently the only path in is a push-notification deep link (`pushDecision.ts:62`); a student who has push disabled or dismissed the OS prompt has zero in-app way to reach their own notifications screen. A genuine dead end for a subset of users. | Small: either a 1-line nav entry or a small header component addition; if a badge/unread-count is added it needs a data source (`useNotifications`-shaped hook may already exist — not verified in this pass). | No. Additive only; existing tests that `goto("/student/notifications")` directly (`engagement.spec.ts:174`, `correct-paper.spec.ts:127`) are unaffected since the path is unchanged. |
| 4 | Scaffold minimal K-01 (School dashboard) and X-01 (Platform admin console) landing screens, and stop resolving `school_admin`/`platform_admin` into `/teacher` once real screens exist — currently `portalPathForRole()` (`RequireAuth.tsx:44-48`) sends both roles into the teacher portal as an explicit, documented interim measure. | REDESIGN-MISSION §1 lists "school-admin and platform-admin views" as in scope, and PRODUCT.md confirms these are "real accounts with real screens, not implementation details." Today those two roles get a UI built for a different job (teacher's `/api/teacher/*` surface), which is functionally workable per the existing comment but is not the product's real shape. This is the single largest IA gap found. | Large — this is new screen construction (K-01–K-04, X-01–X-03: 7 screens per the spec table), a new top-level route subtree (`adminRoute`/`schoolAdminRoute` analogous to the existing three), a new `RequireAuth` split (today `TEACHER_ROLES` bundles all three — `App.tsx:49` — and would need to un-bundle), and new sidebar/nav components. This is explicitly out of this Phase-1 diagnose scope (build work, not audit), flagged here as the top structural finding for Phase 3/4 planning. | Not a "break" in the deep-link sense (adds routes, doesn't move any), but changing `portalPathForRole()`'s fallback for these two roles **would** change where a `school_admin`/`platform_admin` session lands on `/` and on login — any bookmark, test fixture, or seeded account currently expecting `/teacher` for those roles needs updating. `rbac.spec.ts` was not read in this pass and should be checked for role-to-portal assertions before this ships (see diagnose.md "Not reached"). |
| 5 | Add a shared 404/catch-all route (`path: "*"`) and a router-level `errorElement`/`ErrorBoundary` to `web/src/App.tsx`'s route array. | Confirmed missing (diagnose.md, Strategic Omissions). Any typo'd URL or render exception currently shows react-router's default unstyled fallback or a white screen — a dead end with zero brand voice and zero recovery path. | Small: one new lazy-loaded `NotFound` screen + one `errorElement` prop per top-level route group (or one shared boundary if react-router v7's data router supports a single root-level one — needs a quick check against the installed 7.18.1 API before implementation). | No. A catch-all only intercepts paths that currently match nothing; it cannot shadow an existing route. |
| 6 | Add a persistent, low-friction "back" affordance across the teacher and parent portals (student already has a breadcrumb). Not necessarily `navigate(-1)` everywhere — a consistent pattern (breadcrumb for teacher to match student, or a "back to overview" convention for parent's 3 non-index screens) is the actual proposal; the exact mechanism is a Phase 3 design decision, not resolved here. | Confirmed: `navigate(-1)` back-navigation exists in exactly 1 of ~40 screens (`StudentDetail.tsx`). Teacher has no breadcrumb at all; parent has no back control on `ChildOverview`/`SubjectDetail`/`Weaknesses` beyond the header's child switcher and sign-out. | Medium: touches every non-index screen's chrome across two portals, though it can likely be solved once at the layout level (add a breadcrumb component to `TeacherLayout` the way `StudentLayout` already has one) rather than per-screen. | No. Purely additive UI; no path changes. |

## 4. What this audit did not reach

- `rbac.spec.ts` and `seed-contract.spec.ts` (2 of the 13 e2e files) were not opened; any
  test that asserts a specific role → portal mapping should be checked before change #4
  above is scheduled.
- The actual behavior of the parent portal's "skip straight to overview when there's only
  one child" claim (`index.tsx:26-31` cites the spec but the redirect logic itself,
  presumably in `Children.tsx`, was not read) was not independently verified.
- Whether `/student/onboard`, the 3 placement sub-routes, and the 4 practice sub-routes are
  reachable from anywhere other than a first-run flow or another in-flow screen was not
  fully traced — they were assessed as acceptable step-flow routes (no persistent nav
  needed) based on naming and spec convention, not by reading every screen that might link
  into them.
- Backend route/permission definitions (`routers/teacher.py`, `routers/me.py`, etc.,
  referenced in comments) were not opened; all role-gating claims above are taken from the
  frontend `RequireAuth` call sites and from comments citing those backend files, not from
  reading the backend itself.
