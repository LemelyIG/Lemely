# Student home: Overview page from design A

Date: 2026-11-06
Branch: `design/student-home-variants`
Design source: `web/dev-previews/student-home-a.html`, `web/dev-previews/student-home/variant-a.css`,
`variant-a.js`, `shell.css`, `tokens.css`, `fixtures.ts`, `controller.ts`.

## Goal

Replace the student Overview page (`web/src/portals/student/screens/Overview.tsx`) with design A.
Keep every function, look and interaction of the design. Changes are allowed only where they
improve on the design and the user approves them (see "Drift gate").

## Scope

In scope:

- The Overview page content: hero, Garden, next-step card, grades, practice targets, exams,
  loading skeleton, error banner, all 14 design states.
- Backend fields and one endpoint that the design needs and the API does not provide yet.

Out of scope (next spec, "student shell"): sidebar, floating top bar, settings dialog, account
drawer, notifications panel. The new page sits inside today's student shell.

Not changed: preview variants B and C stay in `web/dev-previews/`.

## Decisions

| Question | Decision |
|---|---|
| Scope | Overview first. The shell gets its own spec. |
| Data | Extend the backend so every design state is backed by real data. |
| Styling | Rebuild in Tailwind v4 using the existing `@theme` tokens in `web/src/index.css`. No ported stylesheet. |
| Fidelity | No unjustified drift. Screenshot comparison against the preview is the acceptance gate. |

## 1. Architecture and data

### Backend

`GET /student/overview` (`lemely/web/routers/student.py`, `OverviewDTO` in
`lemely/web/schemas_student.py`) keeps every current field and adds:

- `latestResult: {subjectCode, grade, paperId, paperLabel, recordedAt, seen} | null`
- On `SubjectRowDTO`: `firstPct: number | null`, `previousGrade: string | null`,
  `nextExamOn: string | null` (ISO date) and `examAvailability` (the exam calendar's existing
  `no_session` / `no_timetable` / `dated` reason, so the page can say why a date is missing).
- `upcomingSessions: [{sessionId, subjectCode, title, minutes, scheduledFor}]`: study-plan
  sessions for the next 7 days across all enrolled subjects.

`UploadRunDTO` adds `progress: {stage: 1 | 2 | 3, done: number, total: number} | null`. The
marking pipeline writes it while it runs, so a reload shows "Marking question 7 of 12".

New endpoint: `POST /student/results/{paperId}/seen`. It is idempotent and sets `seen_at` once.
It only accepts the calling student's own papers. Opening a result calls it.

Migrations (stop and show the user each one before it runs):

1. `seen_at` (nullable timestamp) on the results table.
2. Progress columns (stage, done, total) on the upload run table.

### Frontend data flow

- Queries: `useOverview`, `useXpProfile`, `useActiveUpload` (polls while `status` is
  `processing`). Add `useMarkResultSeen` (mutation that invalidates the overview).
- `web/src/portals/student/home/facts.ts` maps the three responses to the existing `HomeFacts`
  type in `home/model.ts`. Add `firstPct`, `examAvailability` and upload `progress` to the model
  types where the components need them.
- `deriveNextAction`, `binnyMood` and `streakStrip` in `home/model.ts` decide the next step,
  Binny's mood and the week strip. The page does not call the API anywhere else.
- `facts.ts` also exports `homeState(facts)`, which returns one of the 14 design states (section 3).

## 2. Components and layout

Folder: `web/src/portals/student/home/`. One component per design section. Markup order,
element types, headings and visible text match the design.

| Component | Design source | Notes |
|---|---|---|
| `StudentHome.tsx` | `#sh-root` | Route element. Sets `data-state`, `data-mood`, `data-action`. Keeps pull-to-refresh. |
| `HomeHero.tsx` | `.ah-hero` | Binny, greeting, level and XP bar, week strip. Hero height stays the same in every state at a given width. |
| `Garden.tsx` | `.a-mo` | Many-papers picker, solo, ghost, sparse0–3, streak-zero. Includes the sparse desktop layout (50/50 row, stacked Garden). |
| `NextStepCard.tsx` | `.a-action-card` | One layout per next-step kind (marking with stages, result, session, first paper, practice, correct), plus the sparse0 "While you wait" link beside the button. |
| `GradesList.tsx` | grades section | Rows, waiting slots, phone grade strip. |
| `PracticeTargets.tsx` | weak-topics section | List and dashed empty slot. |
| `ExamsTimeline.tsx` | exams section | Squeezed Nov–Apr timeline, day counts, reason when there are no dates. |
| `HomeSkeleton.tsx` | loading skeleton | Same layout as the real page. |
| `HomeError.tsx` | error banner | `role="status"`. |

- Use `@/components/ui` pieces (buttons, icons) only where they render identically to the design.
  Otherwise the component owns its Tailwind classes.
- Behaviour from `variant-a.js` becomes React state and hooks: Garden subject picker, marking
  stage walk, motion levels, count-up and reveal animations. All motion stops under
  `prefers-reduced-motion`.
- Light and dark themes both match the design.
- `screens/Overview.tsx` is deleted when the route switches. Its imports that nothing else uses
  are deleted too.

## 3. States, errors and accessibility

`homeState(facts)` returns:

| State | Trigger |
|---|---|
| `loading` | Any of the three queries pending with no cached data. Skeleton only. |
| `error` | Overview query failed. Banner with retry, using `studentLoadFailureMessage`. |
| `new` | 0 papers and no upload. |
| `sparse0` | First paper is marking. |
| `marking` | An upload is processing and at least one paper is already marked. |
| `result-in` | `latestResult.seen` is false. |
| `one-paper` | 1 marked paper, every subject has a paper. |
| `sparse1` | First result exists and at least one subject has no paper. |
| `sparse2` | 2–4 papers, at least one subject with no paper or no exam date. |
| `sparse3` | 1–5 papers, no paper in the last 7 days, streak reset. |
| `streak-zero` | Streak reset after at least one earned day, otherwise populated. |
| `no-plan` | Populated, no upcoming sessions. |
| `no-exams` | Populated, no exam dates. |
| `populated` | None of the above. |

The exact thresholds come from the scenarios in `web/dev-previews/student-home/fixtures.ts`. If
a threshold in this table conflicts with a fixture, the fixture wins and this table is updated.

- XP or upload query failure hides only the piece that depends on it.
- Edge cases: long subject names, 0, 1 and 3+ subjects, exam with no start time, stale upload,
  offline (cached data plus the existing offline banner).
- Accessibility: one h2 per section as in the design; Garden picker uses radio inputs with a
  legend; marking progress is a polite live region; hidden labels on plants and days; touch
  targets at least 44px; visible focus outlines.

## 4. Testing and drift gate

### Drift gate

- Script: `web/scripts/home-drift.mjs` (Playwright and pixelmatch).
- For each pair it renders the preview at `student-home-a.html?state=X&motion=reduce` and the
  real `/student` page with the API mocked from the matching `fixtures.ts` scenario.
- It captures the page content area only. Before the capture it resizes each window until both
  content areas have the same width.
- Matrix: 14 states × content widths of the 390, 768, 1024, 1440 and 1920 windows × light and
  dark = 140 pairs. Plus interaction pairs: after a Garden pick, mid marking-stage walk, after a
  result is opened.
- Pass rule: 0 differing pixels. A pair may differ by up to 15% of its pixels only when every
  difference has a written justification in the drift log below. Over 15% always fails.
- A component is done only when all its pairs pass. On a failure, read the diff image, fix the
  drift, re-run the pair.
- Improvements on the design need the user's approval and a drift-log entry.

### Other tests

Run only the touched test files, never the full suite.

- Vitest: `facts.ts` (each state trigger, edge cases), component roles and labels, keyboard use
  of the Garden radios.
- Pytest: new overview fields, the seen endpoint (including a request for another student's
  paper), upload progress, both migrations forward and back.
- axe on the real page for each state.

### Rollout

The router switches `/student` to `StudentHome` once every gate passes.

## Drift log

| Pair | Difference | % pixels | Justification | Approved |
|---|---|---|---|---|
| (none yet) | | | | |
