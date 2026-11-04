# Student home (dashboard) design

Date: 2026-11-05
Branch: `design/student-home-variants` (cut from `design/teacher-home-variants` at `fed8a895`)
Visual authority: `DESIGN.md` on this branch (v5 Abyss, Material 3 roles, light and dark)
Product authority: `PRODUCT.md`
Route: `/student` (today `web/src/portals/student/screens/Overview.tsx`)

## 1. Job and audience

- **Who:** an IGCSE / O-Level / AS / A-Level student, usually on a phone at home, often anxious
  about a result they care about.
- **Mode:** Operate. Scanability and task speed come first; the student surfaces may use the
  louder parts of v5 (Binny, XP, streaks, Bricolage at full size).
- **Main job:** tell the student what to do next. Grades and trends are context for that
  action, not the headline.
- **Audience line:** "From paper to A*." (DESIGN.md §6).

The current Overview shows a greeting, a subjects ledger, a momentum chart and weak topics. Study
plans, practice, flashcards, placement, XP and streaks have all shipped since, and none of them
appear on home. The new home brings them together around one next action.

## 2. Outcome and proof

- **Success:** within one glance the student knows their next action and can start it with one
  tap, and can see their streak, level and predicted grade per subject.
- **Product truth this page must keep:**
  - Predicted grades come from real per-paper-variant boundaries. A grade without an exact
    boundary shows the word "estimated" (PRODUCT.md, Positioning 3).
  - Grades are private. Nothing on this page compares grades with other students.
  - Every number connects to a next step (PRODUCT.md, Principle 1).

## 3. Next action (hero)

A pure frontend function `deriveNextAction(facts)` picks one action. It has no side effects, so a
unit test can cover each branch. Order of precedence:

1. **Marking in progress.** `GET /student/uploads/active` returns a run. Action: open the
   progress view ("Marking 0580/42…").
2. **Study session due.** The first entry of `upcomingSessions` is scheduled for today or
   earlier and is not complete. Action: start that session
   (`/student/plan/{subjectCode}/session/{sessionId}`).
3. **No papers yet.** Every subject row has `papers === 0`, or there are no subjects. The page
   shows the onboarding view (section 7, state "new student") with "Correct your first paper".
4. **Weak topic exists.** `weakGlobal` is not empty. Action: practise the weakest topic in its
   subject (`/student/practice/{subjectCode}`, with the topic passed in router state). If
   `PracticeGenerator` cannot preselect a topic from router state yet, the port adds that.
5. **Fallback.** Action: correct another paper (`/student/correct`).

The hero shows one action only. Other candidates do not appear as a list in variants A and B.
Variant C may show up to three items (section 6).

## 4. Reward layer (front and centre)

The user chose a loud reward layer. It must still avoid the consumer-edtech pastiche that
PRODUCT.md bans (emoji as UI, confetti, cheerleader copy).

- **Binny** appears on every visit, next to the hero, one per screen, never next to the logo.
  Its expression comes from a pure function `binnyMood(facts)`:

  | Condition (first match wins) | Expression |
  |---|---|
  | Marking in progress | Marking… |
  | `latestResult` recorded in the last 24 h and its grade is above the previous grade for that subject | Grade improved |
  | `latestResult` recorded in the last 24 h | Paper marked |
  | XP earned today (`calendar` entry for today has `xp > 0`) | Streak kept |
  | Otherwise | Idle |

  "Lost marks" is never used on home.
- **Level and XP:** level number and XP-to-next-level progress in Bricolage 800 (28px or larger),
  with a primary progress bar. Data: `useXpProfile()` (`level`, `totalXp`, `levelStartXp`,
  `nextLevelXp`).
- **Streak:** current streak and a 7-day strip from `calendar`. Gold marks only the days with
  XP (the Gold Is Earned rule). Freezes available show as a count.
- **Copy:** warm and plain. A streak of 0 says how to start one, never that the student lost it.
- **Motion:** Binny idle loop and one reward entrance per visit, both off under
  `prefers-reduced-motion`.

## 5. Context below the hero

- **Subjects ledger:** one row per subject with the Jewel grade chip (letter always shown),
  predicted grade, change since the previous grade, "estimated" when `gradeEstimated` is true,
  papers corrected, and days until the next exam when `nextExamOn` is set. Each row links to
  `/student/subject/{code}`.
- **Weak topics:** v5 mark rows (topic, subject code, accuracy as a percentage in JetBrains
  Mono). Each row links to practice for that topic, using the same route as rule 4 of section 3.
- **Latest result:** paper label (for example "0580/42 · m/j 2024"), marks awarded over total,
  grade chip, and a link to `/student/result/{paperId}`.
- **Join a class prompt:** kept from today's Overview, shown only when the student has zero
  classes.

## 6. Variants for the dev preview

All three use the same data and the same states (section 7).

- **A. Today's page.** First row: the next-action card with Binny beside it, then the reward
  block (level, XP, 7-day streak). Below: subjects ledger, weak topics, latest result. On
  mobile: action, reward, subjects, weak topics, latest result.
- **B. Exam runway.** The page is organised around exam dates: a timeline to each exam, one lane
  per subject with predicted grade, next session and days left. Binny, level and streak sit in
  a header band. The next action prefers the subject with the closest exam when rules 2 or 4
  of section 3 apply. With no `nextExamOn` on any subject, B renders as A.
- **C. Training log.** Hero: Binny with level and XP at display size and the weekly streak.
  The next action becomes a short "today" list of up to three items, built from the same rules
  in section 3 (for example: session, weak-topic practice, correct a paper). Grades move lower
  on the page. This variant tests the loud extreme; it is the one most at risk of the banned
  gamification look and must be judged against that.

## 7. States and data ranges

Each variant must render all of these in the preview's state switcher:

| State | Data |
|---|---|
| Populated | 3 subjects (0580, 0606, 0625), 2–14 papers each, grades C to A*, one "estimated" grade, 2 upcoming sessions, 4 weak topics, streak 9, level 7 |
| New student | 0 subjects, 0 papers, streak 0, level 1. Onboarding view with Binny Idle |
| One paper | 1 subject, 1 paper, no previous grade, no momentum |
| Marking in progress | Populated data plus an active upload |
| No study plan | `upcomingSessions` empty |
| No exam dates | `nextExamOn` null on every subject |
| Streak 0 | Populated, but no XP in the last 2 days |
| Loading | Skeleton shapes for hero, reward block and ledger |
| Error | `role="alert"` message using `studentLoadFailureMessage`, with a retry button |
| Dark mode | Same states on the dark scheme (Tide accent, never Abyss on dark) |
| Mobile | 390px wide with the student bottom bar |
| Reduced motion | All motion off, Binny static |

Ranges: 0–3 subjects in v1 (CAIE 0580, 0606, 0625), 0–8 weak topics (show at most 4, then a
"See all" link to the subject page), 0–3 upcoming sessions, streak 0–365.

Demo data in the preview is labelled as demo data on the page. It must use real subject codes
and plausible paper labels, and it never appears in the React build.

## 8. Backend additions

Additive, read-only fields on `GET /api/student/overview` (`lemely/web/schemas_student.py`).
No new endpoint and no migration.

- `OverviewDTO.upcomingSessions: list[UpcomingSessionDTO]`: at most 3 incomplete study-plan
  sessions across all subjects, earliest first. Fields: `sessionId`, `subjectCode`, `title`,
  `minutes`, `scheduledFor` (ISO date).
- `OverviewDTO.latestResult: LatestResultDTO | None`: the most recent marked paper. Fields:
  `paperId`, `subjectCode`, `paperLabel`, `awarded`, `total`, `grade`, `gradeEstimated`,
  `recordedAt` (UTC ISO-8601).
- `SubjectRowDTO.previousGrade: str | None`: the grade from the paper before the latest one in
  that subject.
- `SubjectRowDTO.gradeEstimated: bool`: true when the predicted grade used the per-subject
  average fallback instead of an exact boundary entry.
- `SubjectRowDTO.nextExamOn: str | None`: the next exam date for that subject from the student's
  exam calendar (`lemely/web/routers/exam_calendar.py`), ISO date.
- `WeakThreadDTO.subjectCode: str`: the subject the topic belongs to, so the row can link to
  practice.

XP, streak and classes keep their own hooks (`useXpProfile`, `useMyClasses`). The active upload
keeps its own endpoint.

## 9. Pipeline

1. Commit this spec on `design/student-home-variants`.
2. Build a static preview `web/dev-previews/student-home.html` (with
   `web/dev-previews/student-home/*.css|js`), using the v5 tokens in
   `web/dev-previews/teacher-home/tokens.css`. It has a variant switcher (A, B, C) and a state
   switcher (section 7).
3. Run impeccable live mode on the preview. Every live request produces variants, not direct
   edits.
4. The user picks a direction. A writing-plans step then covers the React port under
   `web/src/portals/student/home/`, the backend fields in section 8, and tests.

## 10. Testing (for the port)

- Vitest: `deriveNextAction` and `binnyMood` truth tables, one case per row.
- Vitest: each home block's loading, error, empty and data states.
- Pytest: the new `OverviewDTO` fields, including `gradeEstimated` true and false,
  `previousGrade` null for a single paper, and `upcomingSessions` capped at 3 and sorted.
- Axe and contrast checks in light and dark, and a 390px screenshot.

## 11. Constraints and boundaries

- v5 Material 3 roles only, no raw colour values in components.
- Bricolage only at 28px or larger. Marks, codes, percentages and dates in JetBrains Mono.
- Gold only for XP, streak and reward. Crimson only for lost marks and genuine errors; home
  shows no crimson in normal states.
- Logical CSS properties only (`margin-inline-start`, `padding-inline`), so a future RTL flip
  works.
- Tap targets at least 44px on coarse pointers.
- Never say "cram", "hack", "easy A" or "guaranteed grade".

**Out of scope:** leaderboards on home, an announcements feed (an unread count in the shell is
enough), the teacher, parent and admin homes, and any change to how grades or XP are computed.
