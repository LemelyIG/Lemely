# Redesign implementation: approved screens plus the backend they need

Date: 2026-11-14
Status: approved in brainstorming, waiting on the gate below

## Goal

Build every approved redesign screen in the real app, together with the backend work those screens need. Every screen keeps all the features of the live screen it replaces. Each screen matches its mock closely, including every state, interaction and animation. The work runs in parallel lanes so it finishes quickly, and quality stays high throughout.

The approved mocks are in `.impeccable/mocks/`, on branch `design/redesign-mocks`. The decisions behind them are recorded in the redesign decisions memory and in the "UI taste, first try" profile. The mocks below are the source of truth.

| Group | Mock (approved final) | Live screens replaced |
|---|---|---|
| Student Home hub and Me | `student-r2/home4.html` (+ `h4.js`, `h5.js`, `h6.js`) | `student/screens/Overview.tsx`, `Profile.tsx` |
| Subject | `student-r2/final.html` (`sjf.js`) | `student/screens/Subject.tsx` |
| Practice run and result | `student-r2/practice-final.html` (`pr.js`, `pr.css`) | `practice/PracticeSet.tsx`, `PracticeResult.tsx`, `PracticeGenerator.tsx` |
| Practice tab | `student-r2/practice-hub-final.html` (`ph.js`, `ph.css`) | new screen (Practice tab root) |
| Study plan | `student-r2/plan-final.html` (`sp.js`, `sp.css`) | `student/screens/studyplan/*` |
| Flashcards | `student-r2/cards-final.html` (`fc.js`, `fc.css`) | `student/screens/flashcards/*` |
| Teacher review queue | `review-r1/final2.html` | `teacher/screens/Review.tsx`, `ReviewItem.tsx` |
| Student paper result S1 | `student-r1/s1.html` | `student/screens/PaperResult.tsx` |
| Upload, camera, processing | `upload-r1/final.html` | the upload and processing flow, the camera, `CorrectPaper.tsx` where it overlaps |
| Teacher papers, heatmap, StudentDetail | `teacher-r1/final.html` | `ClassPapers.tsx`, `Grading.tsx`, `StudentDetail.tsx` |
| Empty and sparse states | `states-r1/*` | the first-run and sparse frames of every screen above |
| Parent subject, topics, Emails | `student-r2/parent-final.html` (`pa.js`, `pa.css`) | `parent/screens/SubjectDetail.tsx`, `Weaknesses.tsx`, plus the email part of notification preferences |

The teacher overview is already done and is out of scope. So are the screens tracked in issues #333–#362.

## Gate

No lane starts until the user confirms that `design/student-home-variants` has been merged into `develop`. That branch holds the shell work this project builds on:
- `PortalShell`, the top bar, the sidebar and the native tab bar
- native sheets and pull-to-refresh
- list rows on phones for the teacher table screens

Until the merge, the branch is read-only for this project. The mocks branch `design/redesign-mocks` is merged into `develop` in wave 0, so every lane can see the mocks.

## Decisions

- **Split:** a foundation first, then waves of vertical-slice lanes. Each lane owns one screen group end to end: endpoints, hooks, view model, screen, states and tests.
- **Parallelism:** 4 lanes at a time, each in its own worktree and on its own branch, `redesign/<lane>`, cut from `develop`.
- **Rollout:** each new screen replaces the live one directly. There are no flags. The old screen's code is deleted in the same PR, once every live feature has been confirmed carried over.
- **Shell conflicts:** the shell from the merged branch wins, and the page content inside it follows the mock exactly. Shell differences shown in the mocks are added to that shell rather than replacing it. Examples: Scan in the centre of the student tab bar, and the desktop rail's "Scan a paper".
- **Fidelity:** no screenshot-diff gate and no other slow gates. Each screen gets one side-by-side screenshot of mock and app at 390 px and 1280 px, any visible drift is fixed, and then `/impeccable polish` is run.
- **Changes from the mock:** small fixes are allowed and must be listed in the PR: spacing, accessibility, contrast, motion, typos and edge cases. Any change to layout, flow or content needs the user's approval first.
- **Tests:** Vitest for view models and every state, pytest for every new or changed endpoint, and one Playwright happy path per screen. Locally, run only the touched test files. CI runs the full suite.
- **Landing:** a PR per lane into `develop`. Each PR gets an Opus review pass, the fixes, a green CI run, and then a merge. Nothing goes to `main`.
- **Exam countdown:** the pill stays neutral until 30 days before the exam. Inside 30 days it turns Tide, and Binny's line mentions the exam.
- **Model cost:** blank detection rides on the existing marking call, which returns a `blank` flag per question. Cover names use one Haiku call per class-set cover page. Both together must stay well under the $0.10-per-paper ceiling, and cost is reported per paper.

## Waves

### Wave 0: foundation (2 lanes)

**F1, the UI kit, built with the impeccable skill.**
- A Binny component built from the official geometry (`portals/marketing/Binny.tsx`, `binny.svg`).
  - Moods: happy, wink, open, thinking, sad.
  - Motion: idle bob, hop, roam inside a free zone that never overlaps content, pop-in, fade.
  - A reduced-motion fallback.
- Shared parts:
  - the Steps grade path (one bar per paper, a solid goal block, letters on one baseline)
  - the gold three-part ring
  - tinted tiles
  - hairline rows and the `h2row` header with a link
  - topic chips (Work on, Getting there, Secure, with icons)
  - ranked rows (rank, marks lost, a trend of Better, Worse or Same, and the "Assigned" tag)
  - the walkthrough list and ghost skeletons
  - the combo chip, level bar, stepper and switch
  - the countdown pill
- Shell additions:
  - Scan in the centre of the student tab bar and the rail's "Scan a paper", added to the existing shell
  - a parent shell: a child switcher plus Overview, Topics, Inbox and Tutoring tabs, and a rail with the child switcher on desktop

**F2, backend groundwork and shared hook-up points.**
- Route registration, API client sections, `schemas.py` sections and query keys, so later lanes only add their own files.
- Merge `design/redesign-mocks` into `develop`.

### Wave 1: student daily screens (4 lanes)

1. **Home and Me.**
   - Add `GET /student/home`. It returns:
     - the moments: result, teacher reply, tough paper, streak at risk, goal done, back after a break, marking
     - the weekly strip, today's ring, the grade floor, "win marks back", recent papers and the class rows
   - The client picks Binny's mood and line from the moment.
   - The Me screen: level ring, streak strip, stats, people doors, badges, subjects, activity, and the tutoring and account rows.
2. **Subject.**
   - Marks per paper and the A* line from the boundary table, with Paper 4 / Paper 2 switching.
   - The trend line and "more marks to win".
   - Topic chips with secure topics folded.
   - Papers, plus the first-run, sparse, loading and error states, on phone, tablet and desktop.
3. **Practice run and result.**
   - Check one question at a time: multiple choice instantly, typed answers through the marker.
   - Combo, XP and level, autosave and resume, flags.
   - The reveal sheets: right, part marks, checking.
   - States: leave, offline, blank question, error.
   - The result screen, and the start screen choice between "answer here" and "print and scan".
4. **Practice tab.**
   - Tinted tiles and the homework row, shown only when homework is set.
   - Binny's line, "win marks back", and recent runs with resume.
   - The set builder sheet and its states: checking, too few match, no questions for this subject, couldn't make the set.
   - Past papers and the past paper sheet.
   - Add `GET /student/practice/runs`. Reuse the availability check that already exists.

### Wave 2: the paper loop (4 lanes)

5. **Teacher review queue.**
   - Sort by marks lost, confidence or oldest. M3 filters. Approve all clear answers. Tap-Select bulk mode.
   - A row collapses with undo. A big confidence ring. A tick-per-point mark stepper with either/or limits.
   - A side panel with previous and next, an Answer / Whole page toggle, the student's self-review, and the scheme wording.
   - "Queue clear." On phone, a full-screen answer page.
   - Add the whole-page image endpoint and the sort and filter parameters.
6. **Upload, camera, processing.**
   - Phone opens on the camera, desktop on upload, and desktop never gets a camera.
   - Scanner-style capture: a live page outline, auto-capture plus a manual shutter, a page stack. A bad page blocks and must be retaken.
   - "Your pages" with fix-crop (corners, rotate, retake, delete) and Download PDF.
   - The marking board (tiles labelled Blank, Page missing or Marking).
   - All the approved states: no mark scheme, camera permission and errors, landscape hint, upload progress, offline queue, next in line, marking stopped with re-mark, came back mid-run, status error, the drop veil, skipped files.
   - Backend: marking progress per question over SSE with a polling fallback, the paper found, a time estimate, a server-side PDF and saved crops.
7. **Student result S1.**
   - Full-screen suspense hold-to-reveal with no Binny on it, then the celebration. Binny reacts to the grade.
   - The next-step card, "Marks you can win" rows, and the scheme wording only on low-confidence losses.
   - The challenge flow: confirm above 70% confidence, a 40-character reason with a tick, 3 per paper.
   - Add a crop route for students and parents, scoped by ownership or parent link.
8. **Teacher papers, heatmap, StudentDetail.**
   - Class tiles, then the exam screen with Summary (default) and Heatmap plus Download marks (CSV).
   - The calm spread and "Where the class lost marks".
   - The heatmap: colour only, airy, scrolls both ways with pinned edges.
   - Question bars on phone.
   - StudentDetail in two columns with the trend.
   - A student's paper opens in the review-queue layout.
   - Add heatmap and spread data per exam.

### Wave 3 (4 lanes)

9. **Study plan.**
   - Today first, then the gold ring, missed sessions with "Move to today", the "Any day this week" strip, later days, folded done sessions, and "Built from…" with Rebuild.
   - The session sheet. A subject filter that shows that subject's target, countdown and reasons.
   - All states. Desktop as a list plus a side panel.
   - Add moving a session to a day, and a week across all subjects.
10. **Flashcards.**
    - Decks due first, grouped by subject, with origin tags and mastery bars.
    - The new-deck sheet. Deck detail with editing and deleting cards. Rename and delete a deck with confirmations.
    - The swipe review with combo, rating intervals and swipe stamps. "All caught up".
    - All states, including "ratings not saved" with Retry and "Writing 12 cards…".
    - Desktop as a list plus a side panel, and review keys Space and 1–4.
    - Extend the existing deck and card endpoints with a generation status.
11. **Parent subject, topics, Emails (SB).**
    - The predicted, target and paper-count line, the Steps path, and the message-teacher icon.
    - Ranked topic rows with marks-lost bars, then papers.
    - "Topics to work on" as one ranked list with filters, plus the topic sheet.
    - The Emails settings screen: weekly summary per subject and right-away alerts.
    - All states, with no Binny.
    - Extend notification preferences with weekly flags per subject, and add a "what they're doing" field on weaknesses.
12. **Pipeline.**
    - A `blank` flag per question from the marking call.
    - Reading names off class-set covers with Haiku, and the teacher fix-it list for misses.
    - Wire the Blank tile and the fix-it list into the screens from lane 6.

A lane whose files don't overlap with open lanes may start before its wave.

## How a lane works

1. **Brief.**
   - The mock files and frames, and the live screens being replaced.
   - The files the lane owns and the files it must not touch.
   - The memories to read: the redesign decisions, the "UI taste, first try" profile, and the rule on empty and sparse states.
2. **Agents.**
   - The `designer` agent (Sonnet) does UI work and invokes the impeccable skill: read the craft floor, build, polish.
   - The `implementer` agent (Sonnet) does the backend.
   - An Opus reviewer reviews the PR.
3. **List what must be kept.** Before writing code, read the live screen and its API, and list every feature, state and error. The PR shows that each one has been kept.
4. **Build order.** Endpoints and pytest first, then hooks, the view model and Vitest, then the screen.
5. **Every mock frame becomes a real state.** That includes first run, sparse, loading, error, offline, sheets and dialogs, on phone, tablet and desktop. Every mock animation is built and honours `prefers-reduced-motion`.
6. **Check fidelity.** Take the side-by-side screenshots, fix the drift, then run `/impeccable polish`.
7. **Land.** Signed commits with explicit paths (`git commit -S -- <paths>`). Push the branch and open a PR to `develop`. The Opus review comes next, then fixes, a green CI run, and the merge.

Shared files such as the router, API types, `schemas.py` and query keys get their hook-up points from F2. When two lanes must edit the same file, the brief names an owner and the order.

## Backend rules

- Lanes extend what exists. That includes the deck and card CRUD, generate and review, completing a session, notification preferences, parent weaknesses and class analytics.
- Every new route uses the existing auth and tenancy dependencies. Parent access is checked through the parent link. Students and parents can only fetch crops of papers they own or are linked to.
- Any database change ships as a migration with a downgrade. A lane stops for the user's approval before running a migration.
- Error responses map to the mocks' error states.
- Model calls report their cost per paper.

## Errors and states

Every screen ships these states from its mock where relevant:
- normal, first-run walkthrough, sparse (encouraging and instructional)
- loading skeleton, couldn't load with Try again, offline
- action failures (couldn't save, couldn't mark done, ratings not saved, couldn't make the set)

Destructive actions ask for confirmation first.

## Out of scope

- The screens in issues #333–#362
- The teacher overview
- Any change to tokens or to Abyss v5
- Pushing to `main`

## Success

- All 12 groups are live on `develop`, matching their mocks at phone, tablet and desktop.
- No live feature is lost. Every state and animation from the mocks is built.
- CI is green.
- Model cost stays well under $0.10 per paper.
