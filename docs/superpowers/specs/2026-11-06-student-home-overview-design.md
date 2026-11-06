# Student home: Overview page from design A

Date: 2026-11-06 (revised the same day for design commit `c880a54c`)
Branch: `design/student-home-variants`
Design source (commit `c880a54c`): `web/dev-previews/student-home-a.html`,
`web/dev-previews/student-home/variant-a.css`, `variant-a.js`, `shell.css`, `tokens.css`, `fixtures.ts`,
`controller.ts`. `controller.ts` sets `data-garden="1"` on every state, so the "Mistakes beaten"
card and the mirrored next-step row are the default design. The CSS comments name each live-session
decision (sessions 48a34cc4, 105c3b38, 43f5fae0, dd403405, afe76ac6, 2fb62992).

Revision 2026-11-06 (design `c880a54c`), what changed in this spec:

- The Garden is gone. The progress card is "Mistakes beaten" (`MistakesBeaten.tsx`), backed by a new
  `mistakes` field on `GET /student/overview`. The Exam Pace and Topic Map directions were rejected
  and are not built.
- The next-step row is two mirrored halves at 900px and wider.
- Your grades: hover replays the climb, rows are more relaxed, each subject is its own card on
  phones, and the "What do the labels mean?" key is removed.
- Weak topics rows are more relaxed. The hero uses the same card surface as every other card.
- Anti-pattern fixes: sentence text is at least 14px, section subtitles stop at 70ch.
- `lastPaperOn` is dropped: only the Garden read it. `firstPct` stays because the grades trail
  starts at the first paper.

## Goal

Replace the student Overview page (`web/src/portals/student/screens/Overview.tsx`) with design A.
Keep every function, look and interaction of the design. Changes are allowed only where they
improve on the design and the user approves them (see "Drift gate").

## Scope

In scope:

- The Overview page content: hero, Mistakes beaten, next-step card, grades, practice targets,
  exams, loading skeleton, error banner, all 14 design states.
- Backend fields and one endpoint that the design needs and the API does not provide yet.

Out of scope (next spec, "student shell"): sidebar, floating top bar, settings dialog, account
drawer, notifications panel. The new page sits inside today's student shell. The floating top
bar's translucency (`variant-a.css` "Floating top bar: semi-translucent", 86% surface + 14px
blur) belongs to the portal-shell plan (`docs/superpowers/plans/2026-11-06-portal-shell.md`),
not to this page.

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
- On `SubjectRowDTO`: `firstPct: number | null` (the first paper's score, where the grades
  trail starts), `previousGrade: string | null`,
  `nextExamOn: string | null` (ISO date) and `examAvailability` (the exam calendar's existing
  `no_session` / `no_timetable` / `dated` reason, so the page can say why a date is missing).
- `upcomingSessions: [{sessionId, subjectCode, title, minutes, scheduledFor}]`: study-plan
  sessions for the next 7 days across all enrolled subjects.
- `mistakes` for the Mistakes beaten card (below).

#### `mistakes`: what the card needs and where it comes from

```
mistakes: {
  beatenCount: number,
  toBeatCount: number,
  beaten: [{topic, subjectCode}],          // newest beaten first, at most 4
  toBeat: [{topic, subjectCode}],          // newest loss first, at most 4
  lastBeaten: {topic, subjectCode, paperCode, onLatestPaper} | null,
  practise: {topic, subjectCode} | null,
}
```

The source is `question_results`, which already stores, for every marked question, its `topic`
(nullable string from the mark scheme), `maximum_marks` and the marks via
`QuestionResult.effective_marks` (teacher override, else the student's self-mark, else the AI
mark). Nothing new is stored. `weakness_records` and `PaperRecord.weak_areas` are not enough on
their own: they only list topics that lost marks, so they cannot tell "got full marks on this
topic" apart from "this topic was not on the paper".

Derivation, per student:

1. Papers: the grade-bearing records (`is_grade_bearing`: past papers with a real grade) that come
   from a live (not deleted) attempt, oldest `recorded_at` first. File-store records have no
   attempt and no question rows, so they add nothing.
2. Per paper and per `(subject code, topic)`: sum `effective_marks` and `maximum_marks` over that
   attempt's question rows. Rows with a null or blank topic are skipped. A topic with
   `maximum = 0` on a paper is skipped for that paper. `lost = maximum - awarded`.
3. Each `(subject code, topic)` now has a sequence of outcomes, one per paper that tested it.
   - **Beaten**: the latest outcome has `lost = 0` and some earlier outcome had `lost > 0`. This is
     the card's "Lost once, right since": a topic lost again later is not beaten.
   - **To beat**: the latest outcome has `lost > 0`.
   - The paper that beat a topic is the first paper after its last loss.
4. `beaten` is ordered by that paper's `recorded_at`, newest first (ties: subject code, then
   topic). `toBeat` is ordered by its latest paper's `recorded_at`, newest first (ties: more marks
   lost, then subject code, then topic). Both lists stop at 4; the counts are the full totals.
5. `lastBeaten` is `beaten[0]` with `paperCode` (`"0625/42"`: code, paper number and variant,
   no session) and `onLatestPaper` (that paper is the student's newest paper in that subject).
6. `practise` is the to-beat topic that lost the most marks on its latest paper (ties: newer paper,
   then subject code, then topic). Null when nothing is to beat.

The repository read is one new method, `AttemptRepository.topic_marks(user_id)`, which returns
the per-attempt, per-topic sums of step 2. Everything after that is a pure function next to the
other overview builders. No migration.

Known limits, stated rather than hidden: topics are matched by exact string within a subject.
Most labels come from the syllabus taxonomy (`lemely.core.topics.classify`), so they are
canonical, but two mark schemes that spell an unclassified topic differently count as two topics; a "dropped" question
(marker could not read the answer) counts as lost marks, as it does in weak topics today.

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
  type in `home/model.ts`. Add `firstPct`, `examAvailability`, upload `progress` and `mistakes` to
  the model types where the components need them (the plan puts them on `HomeView` in `facts.ts`,
  so the shared `HomeFacts` decision type and the preview fixtures stay unchanged).
- `deriveNextAction`, `binnyMood` and `streakStrip` in `home/model.ts` decide the next step,
  Binny's mood and the week strip. The page does not call the API anywhere else.
- `facts.ts` also exports `homeState(facts)`, which returns one of the 14 design states (section 3).

## 2. Components and layout

Folder: `web/src/portals/student/home/`. One component per design section. Markup order,
element types, headings and visible text match the design.

| Component | Design source | Notes |
|---|---|---|
| `StudentHome.tsx` | `#sh-root` | Route element. Sets `data-state`, `data-mood`, `data-action`. Keeps pull-to-refresh. |
| `HomeHero.tsx` | `.ah-hero` | Binny, greeting, level and XP bar, week strip. Same card surface as every other card: no border, the card-edge ring, card radius; Binny tile `radius-inner`, caption `radius-chip` at every width. Hero height stays the same in every state at a given width (395 / 368 / 239px at the 390 / 768 / 1440 windows). |
| `MistakesBeaten.tsx` | `section.a-prog-dir.a-prog-ladder` | The progress card (replaces the Garden). Label row "Mistakes beaten" + "Lost once, right since"; a big count and its line; one context line; chips for recently beaten topics (solid, tick, subject code) and topics still to beat (outlined); a footer with the remaining count and a secondary "Practise {topic}" button. One copy shape per state (section 3, "Mistakes beaten copy"). Also rendered in the `new` page block. |
| `NextStepCard.tsx` | `.a-action-card` | One layout per next-step kind (marking with stages, result, session, first paper, practice, correct), plus the sparse0 "While you wait" link beside the button. Only the active kind renders. |
| `GradesList.tsx` | grades section | Rows and waiting slots. Hovering a row replays the climb. On phones each subject is its own card. No labels key. |
| `PracticeTargets.tsx` | weak-topics section | List and dashed empty slot. |
| `ExamsTimeline.tsx` | exams section | Squeezed Nov–Apr timeline, day counts, reason when there are no dates. |
| `HomeSkeleton.tsx` | loading skeleton | Same layout as the real page. |
| `HomeError.tsx` | error banner | `role="status"`. |

- Use `@/components/ui` pieces (buttons, icons) only where they render identically to the design.
  Otherwise the component owns its Tailwind classes.
- Behaviour from `variant-a.js` and the CSS becomes React state and hooks: marking stage walk,
  motion levels, count-up and reveal animations, the Mistakes beaten chip pop, the grades hover
  replay. All motion stops under `prefers-reduced-motion`.

### Layout decisions from the live sessions (binding)

- **Next-step row, mirrored halves** (session 105c3b38, polish dd403405). At a content width of
  900px or more the row is two equal columns (`minmax(0,1fr) minmax(0,1fr)`, stretched) in every
  state, and both cards pad `20px 24px`. Both cards open with the same 24px label row (700, 14px,
  line-height 1.3): "Mistakes beaten" on the left, the next step's meta line on the right, then the
  same 12px space. The big lines start at the same height: the count is 32px (`fs-headline`,
  line-height 1.05) to match the next step's title. Each card's action sits on one shared bottom
  line: the active next-step block is a flex column with its primary button pushed down
  (`margin-top: auto`), and the progress card's footer is pushed down the same way. The progress
  card's "Practise {topic}" link is a 44px secondary button (`md-secondary-container`,
  `radius-button`). Chips grow on wide screens (16px text, 40px tall, 8px × 12px gaps). Below
  900px the row stacks with the next step first, as before. Only the active next-step block is
  ever shown; nothing may override the per-action gate.
- **Your grades** (sessions 43f5fae0, 2fb62992). Hovering a row replays the climb: the trail grows
  from the first paper (0.8s), each passed grade stone pops in order C, B, A, A* (delays 0.15s,
  0.35s, 0.55s, 0.75s), and the marker lands (0.5s at 0.6s). Only with
  `prefers-reduced-motion: no-preference`. Rows are more relaxed: list inset 8px, row padding
  12px block, journey 48px tall, stones 32px, marker 16px. At a content width of 560px or less each
  subject is a separate card (`radius-inner`, card-edge ring, 12px between cards, 16px padding,
  name and distance on two lines, the track full width below, 44px tall). The "What do the labels
  mean?" key is removed.
- **Weak topics**: rows at least 56px tall, padding 12px 16px, 20px gaps; on phones 52px, 4px
  row gap.
- **Anti-pattern fixes**: every sentence is at least 14px (`fs-body-sm`): the week meta on phones,
  the exam "today" flag, the new card context lines. `.a-est` stays an 11px label chip. Section
  subtitles (`.a-sec-sub`) stop at 70ch; the dashed weak-topics slot at 60ch; the secure note
  takes 12px inline padding at 760px and below, lining up with the card content.
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

### Mistakes beaten copy, per state

The preview authors four data sets (`data-gs` in the markup, picked by `controller.ts` GSTATE):
`pop`, `sp0`, `sp1`, `sp2`. Every state maps to one copy shape:

| Shape | States | Count | Line next to the count | Context line | Chips | Footer |
|---|---|---|---|---|---|---|
| `pop` | populated, result-in, marking, no-plan, no-exams, streak-zero, error (cached page) | `beatenCount` | "mistakes you don't make anymore" | "Last one beaten: {topic}, on {paperCode}" | up to 4 beaten, then up to 2 to beat | "{toBeatCount} still to beat" + "Practise {topic}" |
| `sp0` | sparse0 | none | "Your first paper is being marked" | "Every mark it loses becomes a mistake to beat" | none | none |
| `sp1` | sparse1, **one-paper** (A1) | `toBeatCount` | "mistakes to beat from your first paper" | "Get one right on your next paper and it counts" | up to 4 to beat | "{toBeatCount − shown} more on the paper" + "Practise {topic}" |
| `sp2` | sparse2 | `beatenCount` | "mistakes beaten · {toBeatCount} to go" | "{topic} beaten on your last {subject short name} paper" (when `onLatestPaper`, else "{topic} beaten on {paperCode}") | up to 4 beaten, then up to 2 to beat | "{toBeatCount − shown} more still to beat" + "Practise {topic}" |
| `sp3` | **sparse3** (A1) | `beatenCount` | "mistakes you don't make anymore" | "They stay beaten while you're away. Last one: {topic}, on {paperCode}" | as `pop` | as `pop` |
| `new` | **new** (A1) | none | "Your first paper starts the count" | "Every mark it loses becomes a mistake to beat" | none | none |

Rules shared by every shape: chips show the subject code only when the shown chips span more than
one subject (sparse1's all-Maths chips have none). The chip list's accessible name is "Recently
beaten and still to beat" (`pop`, `sp3`), "Beaten and still to beat" (`sp2`) or "Mistakes to beat"
(`sp1`). A footer count of 0 is left out. "Practise {topic}" links to
`/student/practice/{subjectCode}` and is left out when `practise` is null.

Fallbacks the design never shows (copy added, needs the user's approval before the route
switch): no topic data at all in a state that expects some → no count, "No mistakes to beat yet",
"Topics you lose marks on show up here after marking"; nothing beaten but something to beat in a
`pop`, `sp2` or `sp3` state → count `toBeatCount`, "mistakes to beat", "Get one right on your next
paper and it counts", up to 4 to-beat chips, footer "{n} more still to beat"; a count of 1 uses
"mistake" ("1 mistake you don't make anymore").

**A1 (assumption, the user confirms before the card is built).** The preview covers only `pop`,
`sp0`, `sp1`, `sp2`. `one-paper` and `sparse3` still show the old Garden there (gstate `none`),
and `new` still shows a "Grade ladder" sample card left over from a rejected direction. This spec
proposes Mistakes beaten everywhere, with no new visual pieces: one-paper uses the `sp1` shape,
sparse3 the `pop` shape with a "come back" context line, new the `sp0` shape with its own lead
line. Once confirmed, the preview gets matching `data-gs` blocks (the plan gives the exact markup)
so those states have a drift reference.

Design copy the user may want to revisit now that the Garden is gone (kept word for word until
told otherwise): the sparse2 hero kicker "Physics is still to plant" and the sparse3 practice body
"…waters your Add Maths plant". In the preview, sparse1's footer says "Practise Logarithms", a
0606 topic, for a student with no 0606 paper; the build prints the student's own top to-beat topic
("Practise Bearings", `/student/practice/0580`). **A2 (assumption, confirmed with A1):** the
preview's one shared link is split per data set so the reference matches; without A2 this is a
drift-log row.

- XP or upload query failure hides only the piece that depends on it.
- Edge cases: long subject names, 0, 1 and 3+ subjects, exam with no start time, stale upload,
  offline (cached data plus the existing offline banner).
- Accessibility: one h2 per section as in the design ("Mistakes beaten" is the progress card's);
  each chip carries a hidden "Beaten: " or "To beat: " prefix and the tick is `aria-hidden`; the
  chip list has an accessible name; marking progress is a polite live region; hidden labels on
  days; touch targets at least 44px; visible focus outlines. Known gap in the design: below 900px
  the "Practise {topic}" footer link is a 14px inline text link (about 17px tall). The build
  keeps the design's look but gives the link a 44px hit area with a transparent `::before`
  overlay (no layout change, so no pixel drift); if that proves impossible without drift, the
  plan stops and asks.

## 4. Testing and drift gate

### Drift gate

- Script: `web/scripts/home-drift.mjs` (Playwright and pixelmatch).
- For each pair it renders the preview at `student-home-a.html?state=X&motion=reduce` and the
  real `/student` page with the API mocked from the matching `fixtures.ts` scenario.
- It captures the page content area only. Before the capture it resizes each window until both
  content areas have the same width.
- Matrix: 14 states × content widths of the 390, 768, 1024, 1440 and 1920 windows × light and
  dark = 140 pairs. Plus interaction pairs: mid marking-stage walk, an exam pick, after a result
  is opened. (The Garden pick pair is gone with the Garden. The grades hover replay and the chip
  pop are motion, checked by eye with motion on, because the gate runs with reduced motion.)
- The Mistakes beaten card is its own part (`overview:progress`) in every ready state, and is
  compared inside the `new` part for the new state. For one-paper, sparse3 and new the reference
  exists only after A1 is confirmed and the preview carries the matching `data-gs` blocks.
- Pass rule: 0 differing pixels. A pair may differ by up to 15% of its pixels only when every
  difference has a written justification in the drift log below. Over 15% always fails.
- A component is done only when all its pairs pass. On a failure, read the diff image, fix the
  drift, re-run the pair.
- Improvements on the design need the user's approval and a drift-log entry.

### Other tests

Run only the touched test files, never the full suite.

- Vitest: `facts.ts` (each state trigger, edge cases), the Mistakes beaten copy rules (every shape
  and fallback), component roles and labels.
- Playwright: keyboard reaches the Mistakes beaten "Practise" link with a visible focus outline;
  mark-seen on open; axe per state.
- Pytest: new overview fields, `mistakes` (beaten, lost again, to beat, ordering, caps, teacher
  override counted, deleted attempt and null topic ignored, another student's rows never read),
  the seen endpoint (including a request for another student's paper), upload progress, both
  migrations forward and back.
- axe on the real page for each state.

### Rollout

The router switches `/student` to `StudentHome` once every gate passes.

## Drift log

| Pair | Difference | % pixels | Justification | Approved |
|---|---|---|---|---|
| (none yet) | | | | |

Expected candidates for the Mistakes beaten card and the revised sections (each needs a measured
row and the user's approval before it counts; none is approved yet):

- `overview:progress:sparse1:*` (and `one-paper`): footer button "Practise Logarithms" →
  "Practise Bearings" / "Practise Vectors" (the preview's shared link names a topic these
  students have never sat). Not needed if A2 is approved and the preview link is split.
- `overview:progress:{one-paper,sparse3}:*` and `overview:new:new:*`: only if A1 is confirmed and
  the preview is updated first; otherwise these scenes have no reference and are reported, not
  passed.
- `overview:grades:sparse{0..3}:*` at the 390 window: the preview draws a 1px line above cards 2
  and later, because `.sh-root[data-state^="sparse"] .a-gj > li + li` (0,3,2) out-ranks the phone
  reset `.a-grades .a-gj > li + li` (0,2,2). The build reproduces it (0 px). Removing it is an
  improvement that needs approval.

Acceptance for the Mistakes beaten card: `overview:progress` passes at 0 px in every ready state
covered by the preview, light and dark, at all five widths; at 900px and wider the card's label
row, big line and bottom action line up with the next-step card's (checked in the `page` part);
the copy-rule unit tests cover every shape and fallback; the backend tests prove each derivation
rule above.
