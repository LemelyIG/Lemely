# L8 · Teacher Papers, Heatmap and StudentDetail Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the teacher class-papers tab, the Grading paper grid and StudentDetail with the approved `teacher-r1/final.html` screens: exam tiles per class, then an exam screen with a calm Summary (default) and an airy Heatmap plus Download marks, then StudentDetail in two columns with a trend. Back them with per-exam spread and heatmap data on the class analytics routes.

**Architecture:**
- **Backend.** A pure core module groups a class's grade-bearing attempts into exams and computes the spread, per-question averages and heatmap rows. A small repository reads `question_results` and open review items for those attempts. A new router extends `/api/classes/{class_id}/analytics` with `/exams`, `/exams/{exam_key}`, `/exams/{exam_key}/questions/{question_id}` and `/exams/{exam_key}/marks.csv`, plus `/api/teacher/students/{student_id}/papers/{attempt_id}` for the paper view. Tenancy reuses `ClassService.get_class`/`roster` and `_visible_students`. `StudentDetailDTO` gains optional fields for the trend and paper rows.
- **Frontend.** One typed API module, TanStack hooks under `["teacher","class",classId,...]` (so the existing unshare/reshare invalidation already covers them), and pure view models that make every decision. Screens under `web/src/portals/teacher/papers/` and `web/src/portals/teacher/screens/student/` stay thin.
- **Order.** Backend first, then the data layer, then the screens. The student-paper view that uses L5's review-queue layout goes last, after L5 merges.

**Tech Stack:** FastAPI, SQLAlchemy, pytest with throwaway Postgres; React 19, react-router 7, TanStack Query, Tailwind 4, Vitest (node env, pure modules only), Playwright.

**Spec:** `docs/superpowers/specs/2026-11-14-redesign-implementation-design.md` §Wave 2 item 8. **Master plan:** `docs/superpowers/plans/2026-11-15-redesign-00-master.md`.

## Global Constraints

Inherits the master plan's Global Constraints in full. Lane-specific additions:

- **Owned files:** `web/src/portals/teacher/screens/ClassPapers.tsx`, `Grading.tsx`, `StudentDetail.tsx`. New directories owned by L8: `web/src/portals/teacher/papers/`, `web/src/portals/teacher/screens/student/`. New backend files: `lemely/core/class_exams.py`, `lemely/db/exam_cells_repo.py`, `lemely/web/schemas_class_exams.py`, `lemely/web/routers/class_exams.py`. New frontend data files: `web/src/lib/classExamTypes.ts`, `web/src/lib/classExamApi.ts`, `web/src/lib/hooks/useClassExams.ts`.
- **Narrow edits outside owned files**, each listed in its task: `lemely/web/app.py` (one `include_router` line and its import), `lemely/web/deps.py` (append one `get_exam_cells_repo` provider), `lemely/web/schemas_analytics.py` (optional fields only), `lemely/web/routers/teacher.py` (the student-detail DTO builders and route signature), `lemely/web/student_detail_view.py` (tutor projection strips the new teacher-only fields), `web/src/lib/teacherTypes.ts` (optional fields only), `web/src/portals/teacher/index.tsx` (teacher route entries and the bottom tab; this file is the teacher portal's `routes.tsx`), `web/src/portals/teacher/screens/ClassDetail.tsx` (tab label only).
- **Do not touch:** `web/src/portals/teacher/screens/review/*`, `Review.tsx`, `ReviewItem.tsx` (L5); `CorrectPaper.tsx`, `components/CameraCapture.tsx` (L6); `lemely/io/correction_ai.py` (L12); `TutorStudentDetail.tsx` (keeps importing `StudentDetailView` from `../StudentDetail`).
- **No migration.** Every number comes from existing `attempts`, `question_results`, `review_queue_items` and `class_paper_exclusions` rows.
- **Blank answers** are `question_results.marker_source = 'blank'` (enum member exists since migration 0040). A cell's mark is `teacher_awarded_marks` when set, else `awarded_marks`.
- **Unshared papers** (D9) stay visible in the exam screen, dimmed, with Reshare. They never count towards averages, the histogram, question averages or the heatmap gate.
- **Heatmap gate:** the Heatmap tab is enabled at 5 or more shared papers (`HEATMAP_MIN_PAPERS = 5`). Below that it is disabled with the title "Shows once 5 papers are marked" (frame `Z_exam_sparse`).
- **Copy:** plain words before numbers. No summary sentences under charts. No eyebrows. Every user-visible string in this plan is final copy.
- **Teacher Binny:** small head-crop only, on calm moments only: the class first-run card (`Z_class`, `M_empty`). Nowhere else in this lane.
- **Breakpoints:** phone `<768px` (`md:` off), tablet `768–1279px` (`md:`), desktop `≥1280px` (`xl:`). The merged `PortalShell` supplies the rail, top bar and tab bar; page content follows the mock.
- **Pre-commit / test commands** are always run from the worktree root with `PYTHONPATH=$(pwd)`.

## File structure

```
lemely/core/class_exams.py                 pure: exam identity, grouping, spread, question stats, CSV rows
lemely/db/exam_cells_repo.py               reads question_results + open review items for attempt ids
lemely/web/schemas_class_exams.py          DTOs for the new routes
lemely/web/routers/class_exams.py          /api/classes/{id}/analytics/exams/* + /api/teacher/students/{id}/papers/{attemptId}
lemely/web/deps.py                         + get_exam_cells_repo()
lemely/web/schemas_analytics.py            + optional StudentDetail fields
lemely/web/routers/teacher.py              StudentDetail builders fill the new fields
lemely/web/student_detail_view.py          tutor projection strips attemptId / openReviews
tests/test_class_exams_core.py
tests/test_exam_cells_repo.py
tests/test_web_class_exams.py
tests/test_web_student_detail_redesign.py

web/src/lib/classExamTypes.ts              wire types
web/src/lib/classExamApi.ts                paths + fetchers + CSV download
web/src/lib/hooks/useClassExams.ts         TanStack hooks and keys
web/src/lib/teacherTypes.ts                + optional StudentDetail fields
web/src/portals/teacher/papers/papersViewModel.ts
web/src/portals/teacher/papers/heatmapScale.ts
web/src/portals/teacher/papers/studentDetailViewModel.ts
web/src/portals/teacher/papers/components/*.tsx     GradeChip, GradeBar, NeedsStrip, ExamTile, SectionTitle,
                                                     ClassFirstRun, GhostExamTiles, Spread, LostMarks,
                                                     StudentRows, QuestionBars, Heatmap, AnswerPreview, ExamHeader
web/src/portals/teacher/papers/PapersHome.tsx       /teacher/papers (class tiles)
web/src/portals/teacher/papers/ClassExams.tsx       /teacher/classes/:classId/papers (exam tiles)
web/src/portals/teacher/papers/ExamScreen.tsx       /teacher/classes/:classId/papers/:examKey
web/src/portals/teacher/papers/ExamSummary.tsx
web/src/portals/teacher/papers/ExamHeatmap.tsx
web/src/portals/teacher/papers/QuestionAnswers.tsx
web/src/portals/teacher/papers/MarkPapersConsole.tsx  the Grading console, moved verbatim (see decision D1)
web/src/portals/teacher/papers/StudentPaper.tsx       last task, L5 layout
web/src/portals/teacher/papers/PaperAnswerPanel.tsx   last task, adapter onto L5's panel
web/src/portals/teacher/screens/StudentDetail.tsx     rewritten screen; re-exports StudentDetailView for tutoring
web/src/portals/teacher/screens/student/StudentDetailView.tsx   the legacy shared view, moved verbatim
web/src/portals/teacher/screens/student/*.tsx          StudentHeader, RiskBanner, TrendCard, WeakTopics, PaperRows, StudentFirstRun
web/tests/unit/classExamApi.test.ts
web/tests/unit/papersViewModel.test.ts
web/tests/unit/heatmapScale.test.ts
web/tests/unit/studentDetailViewModel.test.ts
web/e2e/teacher-papers.spec.ts
```

## Routes

| Path | Element | Notes |
|---|---|---|
| `/teacher/papers` | `PapersHome` | Class tiles. Exactly one class: `<Navigate replace>` to its papers. |
| `/teacher/classes/:classId/papers` | `ClassExams` | Replaces `ClassPapers` inside `ClassDetailLayout` (tab label "Papers" stays). |
| `/teacher/classes/:classId/papers/:examKey` | `ExamScreen` | Top-level sibling of `classes/:classId`, so it has its own header. URL state: `?view=heatmap`, `?q=<questionId>`, `?a=<attemptId>`. |
| `/teacher/students/:studentId` | `StudentDetail` | Rewritten. |
| `/teacher/students/:studentId/papers/:attemptId` | `StudentPaper` | Last task (L5). |
| `/teacher/grading` | `MarkPapersConsole` | The existing console, moved; the "Mark papers" target until L6 replaces it. |

Exam keys are URL-safe: `{subject}-{paper}{variant}-{mj|on|fm|sp}-{year|x}`, for example `0580-42-mj-2025`.

---

## Keep-list

Every item is ticked in the PR body by Task 17. "→" says where it lives after this lane.

### `ClassPapers.tsx` (and `GET /classes/{id}/papers`, unshare routes)
- [ ] K1 Every rostered student's paper is listed, newest first (`ClassPapers.tsx:126-188`, `classes.py:895-946`) → exam tiles group them; every paper appears as a student row in its exam (`ExamSummary` "Students", all rows behind "Show all N").
- [ ] K2 The unshared state stays visible (`ClassPapers.tsx:141,174-178`) → unshared rows render dimmed with an "Unshared" chip in Students and the heatmap (`un` rows, mock `t.js` STUS / `final.js` HM2).
- [ ] K3 Unshare asks for confirmation with `unshareConsequence(classPaperLabel(row))`, title "Unshare this paper from the class?", labels "Unshare"/"Unsharing…", `destructive={false}` (`ClassPapers.tsx:72-108`) → `StudentRows` row menu "Unshare from class" opens the same `ConfirmModal` with the same copy helpers.
- [ ] K4 Reshare is one tap, no confirm, inline `role="alert"` error (`ClassPapers.tsx:46-69`) → "Reshare" small tonal button on an unshared row (mock `STUS`).
- [ ] K5 Action errors use `classPaperActionFailureMessage` (`ClassPapers.tsx:57,98`) → same helper.
- [ ] K6 Empty state "No papers yet" (`ClassPapers.tsx:127-130`) → `Z_class` first-run card "Mark 10B's first paper".
- [ ] K7 Load error "Couldn't load this class's papers" + `teacherLoadFailureMessage` (`ClassPapers.tsx:120-123`) → `ClassExams` error keeps heading and body helper.
- [ ] K8 Skeleton while loading (`ClassPapers.tsx:119`) → exam-tile skeleton.
- [ ] K9 Phone list vs desktop table (`TableOrList`, `ClassPapers.tsx:132-188`) → exam tiles wrap to one column on phone; the students list is hairline rows at every width (the merged table-or-list phone behaviour applies to tables; this screen has none left). StudentDetail papers keep `TableOrList` (S8).
- [ ] K10 Recorded time shown relatively (`ClassPapers.tsx:141,171`) → student rows in the exam and StudentDetail paper rows use `relativeTime`.
- [ ] K11 Unshare/reshare invalidate class, classes and review keys (`useTeacherApi.ts:1178-1225`) → reused hooks; new query keys sit under `["teacher","class",classId]`.

### `Grading.tsx` (`GET /papers`, `/papers/{id}`, upload, regrade, delete, preview)
- [ ] G1 Upload a scan + optional mark scheme, one-stage upload stepper, server-side marking note (`Grading.tsx:443-471,668-785`) → `MarkPapersConsole` (moved verbatim).
- [ ] G2 Camera capture behind a tap (`Grading.tsx:678-704`) → `MarkPapersConsole`.
- [ ] G3 Share-target / file-handling scan pickup (`Grading.tsx:366-379`) → `MarkPapersConsole`.
- [ ] G4 Files handed over from teacher home, one-at-a-time notice (`Grading.tsx:388-411,707-711`) → `MarkPapersConsole` (route path `/teacher/grading` unchanged, so `TeacherHome`'s `navigate("/teacher/grading", { state })` still works).
- [ ] G5 Unsubmitted-scan reload guard (`Grading.tsx:419-422`) → `MarkPapersConsole`.
- [ ] G6 Paper grid with All/Review/Graded/Processing tabs and counts (`Grading.tsx:790-828`) → `MarkPapersConsole`.
- [ ] G7 Lazy server-rendered thumbnail (`Grading.tsx:213-337`) → `MarkPapersConsole`.
- [ ] G8 Delete own paper with confirm, `canDelete` only (`Grading.tsx:164-211,334`) → `MarkPapersConsole`.
- [ ] G9 Detected-fields panel (`Grading.tsx:527-556`) → `MarkPapersConsole`.
- [ ] G10 Auto-grading ring with confirmed/need-review counts (`Grading.tsx:558-591`) → `MarkPapersConsole`.
- [ ] G11 Pipeline panel, queued note, error + "Try again" regrade with its own error (`Grading.tsx:593-666`) → `MarkPapersConsole`.
- [ ] G12 "Open review queue" (`Grading.tsx:519-521`) → `MarkPapersConsole`; the exam needs strip adds "Review" per exam.
- [ ] G13 Polling only while something is in flight (`usePapers`/`usePaperDetail`) → unchanged hooks.
- [ ] G14 Load error "Couldn't load papers", card-grid skeleton, one `h1` (`Grading.tsx:486-494,514`) → `MarkPapersConsole`.

### `StudentDetail.tsx` (`GET /teacher/students/{id}`)
- [ ] S1 Name `h1`, paper count, "active … / never active" (`StudentDetail.tsx:256-268`) → `StudentHeader`: name, subjects, "active 2 h ago" (mock `SDH`).
- [ ] S2 At-risk vs not-flagged chip (`StudentDetail.tsx:270-274`) → `RiskBanner` shows when at risk; not-flagged shows nothing (decision D6).
- [ ] S3 Every at-risk flag summary, acknowledged flags tagged and never hidden (`StudentDetail.tsx:281-301`) → `RiskBanner` lists every flag; unacknowledged ones get "Acknowledge" (`useAcknowledgeAtRisk`), acknowledged ones an "Acknowledged" chip.
- [ ] S4 Subjects with predicted grade, latest %, paper count; empty copy (`StudentDetail.tsx:304-329`) → `TrendCard` subject rows ("predicted · up from C").
- [ ] S5 Trend chart + accessible data table + empty copy (`StudentDetail.tsx:117-187`) → `TrendCard` SVG trend with `aria-label` and a visually hidden `<table>` of the same points; empty/sparse frames.
- [ ] S6 Engagement: total papers, last active, days since last submission (`StudentDetail.tsx:335-361`) → `eng` row under Papers.
- [ ] S7 Weaknesses with lost/max marks, accuracy, question count; empty copy (`StudentDetail.tsx:88-99,365-376`) → `WeakTopics`.
- [ ] S8 Attempt history, newest first, `TableOrList` with `storageKey="lemely.studentAttempts.view"` (`StudentDetail.tsx:379-463`) → `PaperRows` keeps `TableOrList` and the storage key.
- [ ] S9 "View / remark" disabled with "Coming soon" (`StudentDetail.tsx:484-499`) → real "Open" to the student-paper route (Task 15).
- [ ] S10 "Assign practice" disabled (`StudentDetail.tsx:502-516`) → header "Assign practice" links to `/teacher/quizzes?new=1` (decision D5).
- [ ] S11 Idle state "No student selected" with Go back (`StudentDetail.tsx:539-545`) → kept.
- [ ] S12 Error "Couldn't load this student" with Go back (`StudentDetail.tsx:550-554`) → kept.
- [ ] S13 Skeleton (`StudentDetail.tsx:528-533`) → two-column skeleton.
- [ ] S14 Back control (`StudentDetail.tsx:470-481`) → shell trail/back (PortalShell) plus `BackControl` on phone.
- [ ] S15 `StudentDetailView` + `StudentDetailDates` shared with tutoring (`StudentDetail.tsx:194-468`; `TutorStudentDetail.tsx:27,158`) → moved to `screens/student/StudentDetailView.tsx`, re-exported from `StudentDetail.tsx`.
- [ ] S16 Teacher date formatting (`StudentDetail.tsx:207-220`) → `teacherDates` moves with the view and is reused.
- [ ] S17 Tenancy: 403 outside the caller's rosters, 404 unknown, 422 malformed (`teacher.py:2405-2468`) → unchanged route; new fields only.

---

## Frame-to-state table

| Frame (`teacher-r1/final.html`) | Component and state | Breakpoint | Trigger |
|---|---|---|---|
| `E3` Class · exams | `ClassExams` normal: needs strip + 3-column exam tiles | desktop (2 cols tablet, 1 col phone) | ≥2 exams |
| `Z_class` Class · first run | `ClassExams` `firstRun`: `ClassFirstRun` (head-crop Binny `open`, 3 steps, Mark papers, sample link) + 3 ghost tiles | desktop/tablet | 0 exams |
| `M_empty` Class · first run phone | same, compact card (`fm`), no ghost tiles | phone | 0 exams |
| `Z_class_sparse` Class · one exam | `ClassExams` `sparse`: one tile + "Your next paper" ghost + dim "Trends" ghost | all | exactly 1 exam |
| `X5` Exam · Summary | `ExamScreen` view `summary`: needs strip, `Spread`, `LostMarks` cards, lowest 3 students | desktop | default view |
| `T_X5` Exam · Summary tablet | same, needs strip stacked (`col`), `LostMarks` as rows (`wqr`), lowest 4 | tablet | width 768–1279 |
| `M_exam` Exam phone | needs strip stacked, compact spread, Questions/Students seg, `QuestionBars` | phone | width <768 |
| `X6` Exam · answer open | Summary split: list + 400px side; `LostMarks` rows with selected row, "Lowest on Qn", side `AnswerPreview` (Task 11) → L5 panel (Task 15) | desktop | `?q=` set (See answers / tap row) |
| `M_answer` Answer full screen | `QuestionAnswers` phone full-screen answer | phone | tap an answer row |
| `F_X7` Exam · Heatmap | `ExamHeatmap`: legend, sticky table (52×38 cells, row break every 5), side panel when a cell is selected | desktop/tablet | `?view=heatmap` |
| Q1 behaviour (round 1, approved in decisions) | `QuestionAnswers` list for one question, lowest first / highest first | desktop/tablet | tap a heatmap column header, or See answers |
| `Z_exam_sparse` Exam · 3 of 28 | Summary `sparse`: sparse bar "3 of 28 papers marked" + Add papers, spread with ghost histogram, "Marked so far"; Heatmap tab disabled | all | shared papers < 5 |
| `L_exam` Loading | `ExamScreen` skeleton | all | query pending |
| `R_exam` Error | `ExamScreen` error card "Couldn't load this exam." | all | query error |
| `S4` Student | `StudentDetail` normal: header, risk, wide trend box with subject seg, Weak topics, Papers + engagement | desktop | ≥2 papers |
| `T_S4` Student tablet | single column: risk, trend box, weak topics, papers | tablet | width 768–1279 |
| `M_student` Student phone | app bar with message icon omitted (D4), risk, grade + trend, weak topics, then papers | phone | width <768 |
| `Z_student_empty` Student · no papers | `StudentFirstRun` (avatar, 2 steps, Mark papers) | all | 0 papers |
| `Z_student_sparse` Student · one paper | trend box with ghost trend + "One more paper draws Omar's trend.", 1 weak topic + hint, 1 paper + "Mark another paper" | all | exactly 1 paper |
| `O1` Student's paper | `StudentPaper` (Task 15, L5 layout) | desktop | Open on a paper row |

---

## Interactions and motion

Values from `t.css` / `base.css`. `--ease` is `cubic-bezier(.2,.8,.2,1)`; Tailwind class `ease-out-soft` already maps the app ease. Every animation below is wrapped in `motion-safe:`; the reduced-motion fallback is "no transition, final state immediately".

| Interaction | Behaviour | Values | Reduced motion |
|---|---|---|---|
| Button press | scale on `:active` | existing `Button` (`active:scale-[0.98]`, `--dur-fast`) | existing |
| Exam tile hover | background to `surface-container-lowest`, lift 2px | `transition-[background,transform] 150ms ease-out-soft`, `hover:-translate-y-0.5` guarded by `[@media(hover:hover)]` | no lift |
| Seg control (Summary/Heatmap, Questions/Students, Lowest/Highest, subject) | `ToggleGroup`; on item gets `bg-surface-container-lowest text-primary shadow-[0_1px_2px_#0001]` | `transition-colors 150ms` | none |
| Selected row (`wqr.on`, `st.sel2`, `qr.on`) | `bg-surface-container-lowest shadow-[inset_0_0_0_2px_var(--color-primary)]` | instant | same |
| Selected heatmap cell | `shadow-[0_0_0_2px_var(--color-primary),0_0_0_4px_var(--color-surface-container-lowest)]` | instant | same |
| Selected heatmap column (`selc`) | `shadow-[inset_0_0_0_2px_var(--color-primary)]` on the `th` | instant | same |
| Side panel opens (X6/F_X7) | fade + 8px slide in from the end side (small fix, listed in PR) | no new CSS (index.css is frozen): the panel wrapper starts `opacity-0 translate-x-2`, a `useLayoutEffect` sets `data-in` on mount, and `data-[in]:opacity-100 data-[in]:translate-x-0 motion-safe:transition-[opacity,transform] motion-safe:duration-200 ease-out-soft` animates it | `motion-reduce:` classes render it at full opacity and position at once |
| Histogram bars on data change | height transition (small fix, listed in PR) | `motion-safe:transition-[height] duration-300 ease-out-soft` | instant |
| Skeleton shimmer | existing `SkeletonBlock` (mock `.sk` 1.4s linear) | existing | existing (`motion-reduce` already handled in kit) |
| Heatmap scroll | both axes, `overscroll-contain`, `scrollbar-width:thin`; names column sticky left, header sticky top, totals sticky right | CSS sticky | same |
| Heatmap cell tap | selects `(student, question)` → `?a=<attemptId>&q=<questionId>` | instant | same |
| Heatmap column tap | opens `QuestionAnswers` for that question (`?q=`) | instant | same |
| Download marks | fetch CSV blob, click a temporary `<a download>`; button shows `loading` while fetching; failure shows a toast "Couldn't download the marks. Try again." | — | — |
| Unshare / Reshare | as live (K3/K4) | `ConfirmModal` kit motion | kit |
| Acknowledge at-risk | button `loading` → flag shows "Acknowledged" chip | kit | kit |
| Binny (class first run) | `<Binny mood="open" size={56} motion="none" />` head crop (see decision D3) | none | none |

---

## Tasks

### Task 1: Core exam grouping and stats (pure)

**Files:**
- Create: `lemely/core/class_exams.py`
- Test: `tests/test_class_exams_core.py`

**Interfaces:**
- Consumes: `lemely.core.history.PaperRecord`, `GRADE_ORDER`, `is_grade_bearing`.
- Produces (used by Tasks 3 and 4):
  - `HEATMAP_MIN_PAPERS: int = 5`, `WEAK_QUESTION_PERCENT: int = 40`
  - `@dataclass(frozen=True) ExamIdentity(subject_code: str, paper_number: int, paper_variant: int, session_month: str, session_year: int | None)` with properties `key: str`, `code_label: str` ("0580/42"), `session_label: str` ("May/Jun 2025")
  - `identity_of(record: PaperRecord) -> ExamIdentity`
  - `parse_exam_key(key: str) -> ExamIdentity | None`
  - `@dataclass(frozen=True) QuestionCell(question_id: str, topic: str | None, awarded: int | None, maximum: int, question_result_id: str)` (`awarded is None` means blank)
  - `@dataclass(frozen=True) ExamPaper(student_id: str, display_name: str, record: PaperRecord, unshared: bool, cells: tuple[QuestionCell, ...] = (), previous_percentage: float | None = None)` with properties `attempt_id: str`, `delta: int | None`
  - `@dataclass(frozen=True) QuestionStat(question_id: str, topic: str | None, maximum: int, average_percent: int, blank_count: int, answered_count: int)`
  - `@dataclass(frozen=True) ExamSummary(identity, paper_count, unshared_count, average, highest, lowest, grade_counts: tuple[tuple[str, int], ...], questions: tuple[QuestionStat, ...], students: tuple[ExamPaper, ...], heatmap_ready: bool)`
  - `natural_question_key(question_id: str) -> tuple[tuple[int, int | str], ...]`
  - `previous_in_subject(records: Sequence[PaperRecord], record: PaperRecord) -> float | None`
  - `group_by_exam(papers: Iterable[ExamPaper]) -> dict[str, list[ExamPaper]]` (latest attempt per student per exam)
  - `summarise_exam(identity: ExamIdentity, papers: Sequence[ExamPaper]) -> ExamSummary`
  - `csv_rows(summary: ExamSummary) -> list[list[str]]`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_class_exams_core.py
"""Pure per-exam grouping and stats for the teacher papers screens (L8)."""

from __future__ import annotations

from lemely.core.class_exams import (
    HEATMAP_MIN_PAPERS,
    ExamIdentity,
    ExamPaper,
    QuestionCell,
    csv_rows,
    group_by_exam,
    identity_of,
    natural_question_key,
    parse_exam_key,
    previous_in_subject,
    summarise_exam,
)
from lemely.core.history import PaperRecord
from lemely.core.schemas import ExamMetadata


def _record(
    pct: float,
    grade: str,
    *,
    attempt: str,
    student: str = "s1",
    recorded_at: str = "2025-06-10T10:00:00+00:00",
    paper: int = 4,
    variant: int = 2,
    month: str = "May/June",
    year: int | None = 2025,
    subject: str = "0580",
) -> PaperRecord:
    return PaperRecord(
        student_id=student,
        metadata=ExamMetadata(
            subject_code=subject,
            paper_number=paper,
            paper_variant=variant,
            session_month=month,
            session_year=year,
        ),
        awarded_marks=round(pct * 0.8),
        maximum_marks=80,
        percentage=pct,
        grade=grade,
        weak_areas=[],
        recorded_at=recorded_at,
        attempt_id=attempt,
    )


def _cell(qid: str, awarded: int | None, maximum: int, topic: str = "Algebra") -> QuestionCell:
    return QuestionCell(
        question_id=qid,
        topic=topic,
        awarded=awarded,
        maximum=maximum,
        question_result_id=f"qr-{qid}-{awarded}",
    )


def _paper(
    name: str,
    pct: float,
    grade: str,
    *,
    attempt: str,
    unshared: bool = False,
    cells: tuple[QuestionCell, ...] = (),
    previous: float | None = None,
    recorded_at: str = "2025-06-10T10:00:00+00:00",
) -> ExamPaper:
    return ExamPaper(
        student_id=name.lower(),
        display_name=name,
        record=_record(pct, grade, attempt=attempt, student=name.lower(), recorded_at=recorded_at),
        unshared=unshared,
        cells=cells,
        previous_percentage=previous,
    )


def test_exam_key_round_trips_and_labels() -> None:
    identity = identity_of(_record(60, "B", attempt="a1"))
    assert identity.key == "0580-42-mj-2025"
    assert identity.code_label == "0580/42"
    assert identity.session_label == "May/Jun 2025"
    assert parse_exam_key(identity.key) == identity


def test_exam_key_without_year_and_specimen() -> None:
    identity = identity_of(_record(60, "B", attempt="a1", month="Specimen", year=None))
    assert identity.key == "0580-42-sp-x"
    assert identity.session_label == "Specimen"
    assert parse_exam_key("0580-42-sp-x") == identity


def test_parse_exam_key_rejects_garbage() -> None:
    assert parse_exam_key("0580-42-xx-2025") is None
    assert parse_exam_key("../etc") is None
    assert parse_exam_key("0580-02-mj-2025") is None


def test_natural_question_order() -> None:
    ids = ["10", "2b", "1", "2a", "9"]
    assert sorted(ids, key=natural_question_key) == ["1", "2a", "2b", "9", "10"]


def test_previous_in_subject_skips_other_subjects_and_later_records() -> None:
    first = _record(48, "D", attempt="a1", recorded_at="2025-01-01T00:00:00+00:00")
    other = _record(90, "A*", attempt="a2", subject="0625", recorded_at="2025-02-01T00:00:00+00:00")
    current = _record(63, "B", attempt="a3", recorded_at="2025-06-01T00:00:00+00:00")
    later = _record(70, "A", attempt="a4", recorded_at="2025-09-01T00:00:00+00:00")
    assert previous_in_subject([first, other, current, later], current) == 48
    assert previous_in_subject([current], current) is None


def test_group_by_exam_keeps_latest_attempt_per_student() -> None:
    old = _paper("Omar", 40, "D", attempt="old", recorded_at="2025-06-01T00:00:00+00:00")
    new = _paper("Omar", 61, "B", attempt="new", recorded_at="2025-06-20T00:00:00+00:00")
    layla = _paper("Layla", 80, "A", attempt="l1")
    groups = group_by_exam([old, new, layla])
    assert list(groups) == ["0580-42-mj-2025"]
    assert {p.attempt_id for p in groups["0580-42-mj-2025"]} == {"new", "l1"}


def test_summary_excludes_unshared_from_every_number_but_lists_them() -> None:
    q = (_cell("1", 3, 4), _cell("2", 0, 4))
    papers = [
        _paper("Layla", 80, "A", attempt="a", cells=q, previous=72),
        _paper("Omar", 50, "C", attempt="b", cells=(_cell("1", 1, 4), _cell("2", None, 4))),
        _paper("Nour", 10, "U", attempt="c", unshared=True, cells=(_cell("1", 0, 4), _cell("2", 0, 4))),
    ]
    summary = summarise_exam(identity_of(papers[0].record), papers)
    assert summary.paper_count == 2
    assert summary.unshared_count == 1
    assert summary.average == 65
    assert summary.highest == 80
    assert summary.lowest == 50
    counts = dict(summary.grade_counts)
    assert counts["A"] == 1 and counts["C"] == 1 and counts["U"] == 0
    assert [g for g, _ in summary.grade_counts] == ["A*", "A", "B", "C", "D", "E", "F", "G", "U"]
    q1, q2 = summary.questions
    assert (q1.question_id, q1.average_percent, q1.blank_count) == ("1", 50, 0)
    assert (q2.question_id, q2.average_percent, q2.blank_count, q2.answered_count) == ("2", 0, 1, 1)
    # lowest first, unshared last
    assert [s.display_name for s in summary.students] == ["Omar", "Layla", "Nour"]
    assert summary.students[1].delta == 8
    assert summary.students[0].delta is None


def test_heatmap_gate_counts_shared_papers_only() -> None:
    shared = [_paper(f"S{i}", 50, "C", attempt=f"a{i}") for i in range(HEATMAP_MIN_PAPERS - 1)]
    hidden = _paper("Hidden", 50, "C", attempt="h", unshared=True)
    identity = identity_of(shared[0].record)
    assert summarise_exam(identity, [*shared, hidden]).heatmap_ready is False
    extra = _paper("Extra", 50, "C", attempt="x")
    assert summarise_exam(identity, [*shared, extra]).heatmap_ready is True


def test_empty_summary_has_no_average() -> None:
    identity = ExamIdentity("0580", 4, 2, "May/June", 2025)
    summary = summarise_exam(identity, [])
    assert summary.average is None and summary.highest is None and summary.lowest is None
    assert summary.questions == ()


def test_csv_rows_guard_formula_injection_and_mark_blanks() -> None:
    papers = [
        _paper("=HYPERLINK(1)", 50, "C", attempt="a", cells=(_cell("1", 2, 4), _cell("2", None, 4))),
        _paper("Nour", 10, "U", attempt="b", unshared=True, cells=(_cell("1", 0, 4), _cell("2", 0, 4))),
    ]
    rows = csv_rows(summarise_exam(identity_of(papers[0].record), papers))
    assert rows[0] == ["Student", "Q1", "Q2", "Total", "Out of", "Percentage", "Grade", "Shared with class"]
    assert rows[1] == ["'=HYPERLINK(1)", "2", "", "40", "80", "50", "C", "yes"]
    assert rows[2][-1] == "no"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=$(pwd) .venv/bin/pytest tests/test_class_exams_core.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'lemely.core.class_exams'`.

- [ ] **Step 3: Write the implementation**

```python
# lemely/core/class_exams.py
"""Per-exam class views for the teacher papers screens (redesign lane L8).

An *exam* is one paper sitting: subject code, paper number, variant, session
month and year. A class's exam is every rostered student's latest
grade-bearing attempt at that sitting. Everything here is pure so the router
and its tests share one computation.

Unshared papers (D9) are carried so a teacher can still see and reshare them,
but they never feed an average, the histogram, a question average or the
heatmap gate.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from lemely.core.history import GRADE_ORDER, PaperRecord, is_grade_bearing

HEATMAP_MIN_PAPERS = 5
"""Shared papers needed before the heatmap tab unlocks (frame Z_exam_sparse)."""

WEAK_QUESTION_PERCENT = 40
"""A question whose class average sits below this is drawn as weak."""

_SESSION_SLUG = {"May/June": "mj", "Oct/Nov": "on", "Feb/Mar": "fm", "Specimen": "sp"}
_SLUG_SESSION = {slug: month for month, slug in _SESSION_SLUG.items()}
_SESSION_SHORT = {"May/June": "May/Jun", "Oct/Nov": "Oct/Nov", "Feb/Mar": "Feb/Mar", "Specimen": "Specimen"}
_KEY_RE = re.compile(
    r"^(?P<code>\d{4})-(?P<paper>[1-9])(?P<variant>[1-9])-(?P<slug>mj|on|fm|sp)-(?P<year>\d{4}|x)$"
)
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


@dataclass(frozen=True)
class ExamIdentity:
    """One paper sitting."""

    subject_code: str
    paper_number: int
    paper_variant: int
    session_month: str
    session_year: int | None

    @property
    def key(self) -> str:
        """URL-safe id, e.g. ``0580-42-mj-2025``."""
        year = str(self.session_year) if self.session_year is not None else "x"
        slug = _SESSION_SLUG[self.session_month]
        return f"{self.subject_code}-{self.paper_number}{self.paper_variant}-{slug}-{year}"

    @property
    def code_label(self) -> str:
        """``0580/42``."""
        return f"{self.subject_code}/{self.paper_number}{self.paper_variant}"

    @property
    def session_label(self) -> str:
        """``May/Jun 2025`` or ``Specimen``."""
        short = _SESSION_SHORT[self.session_month]
        return f"{short} {self.session_year}" if self.session_year is not None else short


def identity_of(record: PaperRecord) -> ExamIdentity:
    """The sitting ``record`` belongs to."""
    m = record.metadata
    return ExamIdentity(m.subject_code, m.paper_number, m.paper_variant, m.session_month, m.session_year)


def parse_exam_key(key: str) -> ExamIdentity | None:
    """Inverse of :attr:`ExamIdentity.key`; ``None`` for anything malformed."""
    match = _KEY_RE.fullmatch(key)
    if match is None:
        return None
    year = match["year"]
    return ExamIdentity(
        subject_code=match["code"],
        paper_number=int(match["paper"]),
        paper_variant=int(match["variant"]),
        session_month=_SLUG_SESSION[match["slug"]],
        session_year=None if year == "x" else int(year),
    )


@dataclass(frozen=True)
class QuestionCell:
    """One student's mark on one question. ``awarded is None`` means left blank."""

    question_id: str
    topic: str | None
    awarded: int | None
    maximum: int
    question_result_id: str


@dataclass(frozen=True)
class ExamPaper:
    """One rostered student's attempt at one exam."""

    student_id: str
    display_name: str
    record: PaperRecord
    unshared: bool
    cells: tuple[QuestionCell, ...] = ()
    previous_percentage: float | None = None

    @property
    def attempt_id(self) -> str:
        return self.record.attempt_id or ""

    @property
    def delta(self) -> int | None:
        """Whole-percent change since this student's previous paper in the subject."""
        if self.previous_percentage is None:
            return None
        return round(self.record.percentage - self.previous_percentage)


@dataclass(frozen=True)
class QuestionStat:
    """Class average on one question, over shared papers."""

    question_id: str
    topic: str | None
    maximum: int
    average_percent: int
    blank_count: int
    answered_count: int


@dataclass(frozen=True)
class ExamSummary:
    """Everything the Summary and Heatmap views draw for one exam."""

    identity: ExamIdentity
    paper_count: int
    unshared_count: int
    average: int | None
    highest: int | None
    lowest: int | None
    grade_counts: tuple[tuple[str, int], ...]
    questions: tuple[QuestionStat, ...]
    students: tuple[ExamPaper, ...]
    heatmap_ready: bool


def natural_question_key(question_id: str) -> tuple[tuple[int, int | str], ...]:
    """Sort key so ``2a`` < ``2b`` < ``10``."""
    parts = re.findall(r"\d+|\D+", question_id)
    return tuple((0, int(p)) if p.isdigit() else (1, p.lower()) for p in parts)


def previous_in_subject(records: Sequence[PaperRecord], record: PaperRecord) -> float | None:
    """Percentage of the latest grade-bearing paper in the same subject before ``record``."""
    earlier = [
        r
        for r in records
        if is_grade_bearing(r)
        and r.metadata.subject_code == record.metadata.subject_code
        and r.recorded_at < record.recorded_at
        and r.attempt_id != record.attempt_id
    ]
    if not earlier:
        return None
    return max(earlier, key=lambda r: r.recorded_at).percentage


def group_by_exam(papers: Iterable[ExamPaper]) -> dict[str, list[ExamPaper]]:
    """Group by exam key, keeping each student's latest attempt at that exam."""
    latest: dict[tuple[str, str], ExamPaper] = {}
    for paper in papers:
        slot = (identity_of(paper.record).key, paper.student_id)
        held = latest.get(slot)
        if held is None or paper.record.recorded_at > held.record.recorded_at:
            latest[slot] = paper
    groups: dict[str, list[ExamPaper]] = {}
    for (key, _student), paper in latest.items():
        groups.setdefault(key, []).append(paper)
    return groups


def _question_stats(shared: Sequence[ExamPaper]) -> tuple[QuestionStat, ...]:
    awarded: dict[str, int] = {}
    possible: dict[str, int] = {}
    maximum: dict[str, int] = {}
    blanks: dict[str, int] = {}
    answered: dict[str, int] = {}
    topics: dict[str, str | None] = {}
    for paper in shared:
        for cell in paper.cells:
            qid = cell.question_id
            topics.setdefault(qid, cell.topic)
            maximum[qid] = max(maximum.get(qid, 0), cell.maximum)
            possible[qid] = possible.get(qid, 0) + cell.maximum
            if cell.awarded is None:
                blanks[qid] = blanks.get(qid, 0) + 1
            else:
                awarded[qid] = awarded.get(qid, 0) + cell.awarded
                answered[qid] = answered.get(qid, 0) + 1
    stats = [
        QuestionStat(
            question_id=qid,
            topic=topics[qid],
            maximum=maximum[qid],
            average_percent=round(awarded.get(qid, 0) / possible[qid] * 100) if possible[qid] else 0,
            blank_count=blanks.get(qid, 0),
            answered_count=answered.get(qid, 0),
        )
        for qid in possible
    ]
    stats.sort(key=lambda s: natural_question_key(s.question_id))
    return tuple(stats)


def summarise_exam(identity: ExamIdentity, papers: Sequence[ExamPaper]) -> ExamSummary:
    """Spread, question averages and ordered students for one exam."""
    shared = [p for p in papers if not p.unshared]
    hidden = [p for p in papers if p.unshared]
    pcts = [p.record.percentage for p in shared]
    counts = dict.fromkeys(GRADE_ORDER, 0)
    for paper in shared:
        if paper.record.grade in counts:
            counts[paper.record.grade] += 1
    ordered = sorted(shared, key=lambda p: (p.record.percentage, p.display_name)) + sorted(
        hidden, key=lambda p: p.display_name
    )
    return ExamSummary(
        identity=identity,
        paper_count=len(shared),
        unshared_count=len(hidden),
        average=round(sum(pcts) / len(pcts)) if pcts else None,
        highest=round(max(pcts)) if pcts else None,
        lowest=round(min(pcts)) if pcts else None,
        grade_counts=tuple(counts.items()),
        questions=_question_stats(shared),
        students=tuple(ordered),
        heatmap_ready=len(shared) >= HEATMAP_MIN_PAPERS,
    )


def _csv_safe(value: str) -> str:
    """Stop a spreadsheet from running a cell as a formula (CSV injection)."""
    return f"'{value}" if value.startswith(_FORMULA_PREFIXES) else value


def csv_rows(summary: ExamSummary) -> list[list[str]]:
    """Header plus one row per student, in question order; blanks are empty cells."""
    qids = [q.question_id for q in summary.questions]
    for paper in summary.students:
        for cell in paper.cells:
            if cell.question_id not in qids:
                qids.append(cell.question_id)
    qids.sort(key=natural_question_key)
    header = ["Student", *(f"Q{q}" for q in qids), "Total", "Out of", "Percentage", "Grade", "Shared with class"]
    rows = [header]
    for paper in sorted(summary.students, key=lambda p: p.display_name.lower()):
        by_q = {c.question_id: c for c in paper.cells}
        marks = [
            "" if (c := by_q.get(q)) is None or c.awarded is None else str(c.awarded) for q in qids
        ]
        rows.append(
            [
                _csv_safe(paper.display_name),
                *marks,
                str(paper.record.awarded_marks),
                str(paper.record.maximum_marks),
                str(round(paper.record.percentage)),
                paper.record.grade,
                "no" if paper.unshared else "yes",
            ]
        )
    return rows
```

Note: the `csv_rows` test sorts by name lowercase: `'=hyperlink(1)'` < `'nour'`, so the injected row is row 1. Keep that ordering.

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=$(pwd) .venv/bin/pytest tests/test_class_exams_core.py -q`
Expected: PASS (11 passed).

- [ ] **Step 5: Commit**

```bash
PYTHONPATH=$(pwd) pre-commit run --files lemely/core/class_exams.py tests/test_class_exams_core.py
git add lemely/core/class_exams.py tests/test_class_exams_core.py
git commit -S -m "feat(core): per-exam class grouping, spread and question stats" -- lemely/core/class_exams.py tests/test_class_exams_core.py
```

---

### Task 2: Exam cells repository

**Files:**
- Create: `lemely/db/exam_cells_repo.py`
- Modify: `lemely/web/deps.py` (append `get_exam_cells_repo`)
- Test: `tests/test_exam_cells_repo.py`

**Interfaces:**
- Consumes: `QuestionCell` (Task 1); ORM `Attempt`, `QuestionResult`, `ReviewQueueItem`; enums `MarkerSource`, `ReviewStatus`.
- Produces:
  - `class ExamCellsRepository(session_factory: sessionmaker[Session])`
    - `cells_for_attempts(attempt_ids: Sequence[str]) -> dict[str, tuple[QuestionCell, ...]]`
    - `open_review_counts(attempt_ids: Sequence[str]) -> dict[str, int]`
    - `open_review_items(attempt_ids: Sequence[str]) -> dict[str, str]` (question_result_id → review item id)
    - `answers_for_question(attempt_ids: Sequence[str], question_id: str) -> dict[str, AnswerRow]`
    - `paper_questions(attempt_id: str) -> list[PaperQuestionRow]`
  - `@dataclass(frozen=True) AnswerRow(question_result_id: str, awarded: int | None, maximum: int, student_answer: str | None, review_item_id: str | None)`
  - `@dataclass(frozen=True) PaperQuestionRow(question_result_id: str, question_id: str, topic: str | None, awarded: int | None, maximum: int, review_reason: str | None, review_item_id: str | None, student_answer: str | None, expected_answer: str | None, feedback: str | None)`
  - `lemely.web.deps.get_exam_cells_repo() -> ExamCellsRepository`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_exam_cells_repo.py
"""Reads per-question cells and open review items for class exams (L8)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.db.base import Base
from lemely.db.exam_cells_repo import ExamCellsRepository
from lemely.db.models import User
from lemely.db.models.attempts import Attempt, QuestionResult
from lemely.db.models.enums import (
    ConfidenceBand,
    MarkerSource,
    ReviewReason,
    ReviewStatus,
    Role,
    SessionMonth,
)
from lemely.db.models.ops import ReviewQueueItem
from lemely.runtime.config import DatabaseSettings

if TYPE_CHECKING:
    from collections.abc import Iterator


def _reachable(url: str) -> bool:
    engine = create_engine(make_url(url).set(database="postgres"))
    try:
        with engine.connect():
            return True
    except OperationalError:
        return False
    finally:
        engine.dispose()


@pytest.fixture
def sm() -> Iterator[sessionmaker[Session]]:
    base_url = DatabaseSettings().url
    if not _reachable(base_url):
        pytest.skip("local Postgres not reachable")
    admin = create_engine(make_url(base_url).set(database="postgres"), isolation_level="AUTOCOMMIT")
    name = f"lemely_test_{uuid.uuid4().hex[:12]}"
    with admin.connect() as conn:
        conn.execute(sa.text(f'CREATE DATABASE "{name}"'))
    engine = create_engine(make_url(base_url).set(database=name))
    Base.metadata.create_all(engine)
    try:
        yield sessionmaker(bind=engine, expire_on_commit=False, future=True)
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


def _attempt(sm: sessionmaker[Session]) -> uuid.UUID:
    student = uuid.uuid4()
    attempt_id = uuid.uuid4()
    with sm.begin() as s:
        s.add(User(id=student, email=f"{student}@example.com", role=Role.student, display_name="Omar"))
        s.flush()
        s.add(
            Attempt(
                id=attempt_id,
                user_id=student,
                subject_code="0580",
                session_month=SessionMonth.may_june,
                session_year=2025,
                paper_number=4,
                paper_variant=2,
                awarded_marks=7,
                maximum_marks=12,
                percentage=58.3,
                grade="C",
                recorded_at=datetime.now(UTC),
            )
        )
    return attempt_id


def _qr(
    sm: sessionmaker[Session],
    attempt_id: uuid.UUID,
    qid: str,
    awarded: int,
    maximum: int,
    *,
    source: MarkerSource = MarkerSource.ai,
    teacher: int | None = None,
    answer: str | None = "2.7",
) -> uuid.UUID:
    row_id = uuid.uuid4()
    with sm.begin() as s:
        s.add(
            QuestionResult(
                id=row_id,
                attempt_id=attempt_id,
                question_id=qid,
                awarded_marks=awarded,
                maximum_marks=maximum,
                confidence_band=ConfidenceBand.high,
                confidence_score=0.9,
                marker_source=source,
                topic="Density and units",
                student_answer=answer,
                teacher_awarded_marks=teacher,
            )
        )
    return row_id


def _review(sm: sessionmaker[Session], attempt_id: uuid.UUID, qr_id: uuid.UUID, status: ReviewStatus) -> uuid.UUID:
    item = uuid.uuid4()
    with sm.begin() as s:
        s.add(
            ReviewQueueItem(
                id=item,
                attempt_id=attempt_id,
                question_result_id=qr_id,
                question_id="8",
                reason=ReviewReason.low_confidence,
                status=status,
            )
        )
    return item


def test_cells_use_teacher_mark_and_blank_flag(sm: sessionmaker[Session]) -> None:
    attempt = _attempt(sm)
    _qr(sm, attempt, "10", 1, 5)
    _qr(sm, attempt, "2", 1, 4, teacher=3)
    _qr(sm, attempt, "3", 0, 3, source=MarkerSource.blank, answer=None)
    cells = ExamCellsRepository(sm).cells_for_attempts([str(attempt)])[str(attempt)]
    assert [(c.question_id, c.awarded, c.maximum) for c in cells] == [("2", 3, 4), ("3", None, 3), ("10", 1, 5)]
    assert cells[0].topic == "Density and units"


def test_unknown_and_malformed_ids_are_ignored(sm: sessionmaker[Session]) -> None:
    repo = ExamCellsRepository(sm)
    assert repo.cells_for_attempts(["not-a-uuid", str(uuid.uuid4())]) == {}
    assert repo.open_review_counts([]) == {}


def test_open_review_counts_only_open_items(sm: sessionmaker[Session]) -> None:
    attempt = _attempt(sm)
    a = _qr(sm, attempt, "8", 1, 4)
    b = _qr(sm, attempt, "9", 0, 3)
    open_item = _review(sm, attempt, a, ReviewStatus.open)
    _review(sm, attempt, b, ReviewStatus.resolved)
    repo = ExamCellsRepository(sm)
    assert repo.open_review_counts([str(attempt)]) == {str(attempt): 1}
    assert repo.open_review_items([str(attempt)]) == {str(a): str(open_item)}


def test_answers_for_question_and_paper_questions(sm: sessionmaker[Session]) -> None:
    attempt = _attempt(sm)
    qr = _qr(sm, attempt, "8", 1, 4, answer="ρ = 54 / 20 = 2.7")
    _qr(sm, attempt, "9", 0, 3, source=MarkerSource.blank, answer=None)
    item = _review(sm, attempt, qr, ReviewStatus.open)
    repo = ExamCellsRepository(sm)
    answers = repo.answers_for_question([str(attempt)], "8")
    row = answers[str(attempt)]
    assert (row.awarded, row.maximum, row.student_answer, row.review_item_id) == (1, 4, "ρ = 54 / 20 = 2.7", str(item))
    questions = repo.paper_questions(str(attempt))
    assert [(q.question_id, q.awarded, q.review_item_id) for q in questions] == [("8", 1, str(item)), ("9", None, None)]
    assert questions[0].review_reason is None
    assert questions[0].student_answer == "ρ = 54 / 20 = 2.7"
    assert repo.paper_questions("nope") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=$(pwd) .venv/bin/pytest tests/test_exam_cells_repo.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'lemely.db.exam_cells_repo'`.

- [ ] **Step 3: Write the implementation**

```python
# lemely/db/exam_cells_repo.py
"""Per-question cells and open review items for class exam views (L8).

Read-only. Attempt ids arrive as strings from the history store; malformed
ids are skipped rather than raised, because they can only come from a store
row that never addressed a database attempt.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from lemely.core.class_exams import QuestionCell, natural_question_key
from lemely.db.models.attempts import QuestionResult
from lemely.db.models.enums import MarkerSource, ReviewStatus
from lemely.db.models.ops import ReviewQueueItem


@dataclass(frozen=True)
class AnswerRow:
    """One student's answer to one question."""

    question_result_id: str
    awarded: int | None
    maximum: int
    student_answer: str | None
    review_item_id: str | None


@dataclass(frozen=True)
class PaperQuestionRow:
    """One question of one paper, for the student-paper view."""

    question_result_id: str
    question_id: str
    topic: str | None
    awarded: int | None
    maximum: int
    review_reason: str | None
    review_item_id: str | None
    student_answer: str | None = None
    expected_answer: str | None = None
    feedback: str | None = None


def _uuids(ids: Sequence[str]) -> list[uuid.UUID]:
    out: list[uuid.UUID] = []
    for raw in ids:
        try:
            out.append(uuid.UUID(raw))
        except (ValueError, TypeError):
            continue
    return out


def _mark(qr: QuestionResult) -> int | None:
    if qr.marker_source == MarkerSource.blank:
        return None
    return qr.teacher_awarded_marks if qr.teacher_awarded_marks is not None else qr.awarded_marks


class ExamCellsRepository:
    """Reads ``question_results`` and open ``review_queue_items`` for attempts."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._sm = session_factory

    def _rows(self, session: Session, ids: list[uuid.UUID]) -> list[QuestionResult]:
        return list(
            session.scalars(
                select(QuestionResult)
                .where(QuestionResult.attempt_id.in_(ids))
                .order_by(QuestionResult.attempt_id, QuestionResult.created_at, QuestionResult.id)
            )
        )

    def cells_for_attempts(self, attempt_ids: Sequence[str]) -> dict[str, tuple[QuestionCell, ...]]:
        """``attempt_id -> cells`` in natural question order; first row wins per question."""
        ids = _uuids(attempt_ids)
        if not ids:
            return {}
        out: dict[str, dict[str, QuestionCell]] = {}
        with self._sm() as session:
            for qr in self._rows(session, ids):
                per = out.setdefault(str(qr.attempt_id), {})
                per.setdefault(
                    qr.question_id,
                    QuestionCell(
                        question_id=qr.question_id,
                        topic=qr.topic,
                        awarded=_mark(qr),
                        maximum=qr.maximum_marks,
                        question_result_id=str(qr.id),
                    ),
                )
        return {
            attempt: tuple(sorted(cells.values(), key=lambda c: natural_question_key(c.question_id)))
            for attempt, cells in out.items()
        }

    def open_review_counts(self, attempt_ids: Sequence[str]) -> dict[str, int]:
        """``attempt_id -> open review items`` (attempts with none are absent)."""
        ids = _uuids(attempt_ids)
        if not ids:
            return {}
        with self._sm() as session:
            rows = session.execute(
                select(ReviewQueueItem.attempt_id, func.count())
                .where(ReviewQueueItem.attempt_id.in_(ids), ReviewQueueItem.status == ReviewStatus.open)
                .group_by(ReviewQueueItem.attempt_id)
            ).all()
        return {str(attempt): int(count) for attempt, count in rows}

    def open_review_items(self, attempt_ids: Sequence[str]) -> dict[str, str]:
        """``question_result_id -> open review item id``."""
        ids = _uuids(attempt_ids)
        if not ids:
            return {}
        with self._sm() as session:
            rows = session.execute(
                select(ReviewQueueItem.question_result_id, ReviewQueueItem.id).where(
                    ReviewQueueItem.attempt_id.in_(ids),
                    ReviewQueueItem.status == ReviewStatus.open,
                    ReviewQueueItem.question_result_id.is_not(None),
                )
            ).all()
        return {str(qr): str(item) for qr, item in rows}

    def answers_for_question(self, attempt_ids: Sequence[str], question_id: str) -> dict[str, AnswerRow]:
        """``attempt_id -> answer`` for one question."""
        ids = _uuids(attempt_ids)
        if not ids:
            return {}
        items = self.open_review_items(attempt_ids)
        out: dict[str, AnswerRow] = {}
        with self._sm() as session:
            for qr in self._rows(session, ids):
                if qr.question_id != question_id:
                    continue
                out.setdefault(
                    str(qr.attempt_id),
                    AnswerRow(
                        question_result_id=str(qr.id),
                        awarded=_mark(qr),
                        maximum=qr.maximum_marks,
                        student_answer=qr.student_answer,
                        review_item_id=items.get(str(qr.id)),
                    ),
                )
        return out

    def paper_questions(self, attempt_id: str) -> list[PaperQuestionRow]:
        """Every question of one attempt, natural order."""
        ids = _uuids([attempt_id])
        if not ids:
            return []
        items = self.open_review_items([attempt_id])
        seen: dict[str, PaperQuestionRow] = {}
        with self._sm() as session:
            for qr in self._rows(session, ids):
                seen.setdefault(
                    qr.question_id,
                    PaperQuestionRow(
                        question_result_id=str(qr.id),
                        question_id=qr.question_id,
                        topic=qr.topic,
                        awarded=_mark(qr),
                        maximum=qr.maximum_marks,
                        review_reason=qr.review_reason,
                        review_item_id=items.get(str(qr.id)),
                        student_answer=qr.student_answer,
                        expected_answer=qr.expected_answer,
                        feedback=qr.feedback,
                    ),
                )
        return sorted(seen.values(), key=lambda q: natural_question_key(q.question_id))
```

Append to `lemely/web/deps.py` (after `get_class_exclusion_repository`), with the import at the top beside the other `lemely.db` imports:

```python
from lemely.db.exam_cells_repo import ExamCellsRepository
```

```python
@lru_cache(maxsize=1)
def get_exam_cells_repo() -> ExamCellsRepository:
    """Return the process-wide :class:`ExamCellsRepository` singleton (redesign L8).

    Read-only per-question cells for the class exam screens. Tests override
    this with a repo bound to a throwaway Postgres database.
    """
    return ExamCellsRepository(get_sessionmaker(get_settings()))
```

Also add `get_exam_cells_repo.cache_clear()` inside `reset_singletons()` next to the other `cache_clear()` calls.

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=$(pwd) .venv/bin/pytest tests/test_exam_cells_repo.py -q`
Expected: PASS (4 passed). If local Postgres is down the tests skip; CI runs them.

- [ ] **Step 5: Commit**

```bash
PYTHONPATH=$(pwd) pre-commit run --files lemely/db/exam_cells_repo.py lemely/web/deps.py tests/test_exam_cells_repo.py
git commit -S -m "feat(db): read exam cells and open review items for class exams" -- lemely/db/exam_cells_repo.py lemely/web/deps.py tests/test_exam_cells_repo.py
```

---

### Task 3: Class exam routes on the analytics surface

**Files:**
- Create: `lemely/web/schemas_class_exams.py`
- Create: `lemely/web/routers/class_exams.py`
- Modify: `lemely/web/app.py` (import `class_exams` in the `from lemely.web.routers import (...)` block; add `app.include_router(class_exams.router)` directly after `app.include_router(classes.router)`)
- Test: `tests/test_web_class_exams.py`

**Interfaces:**
- Consumes: Task 1 core, Task 2 repo, `ClassService`, `ClassExclusionRepository`, `load_roster_histories`, `grade_bearing`, `_raise_for` and `_class_subject_name` from `lemely.web.routers.classes`, `_visible_students` from `lemely.web.routers.teacher`.
- Produces (the frontend types in Task 5 mirror these exactly):
  - `GET /api/classes/{class_id}/analytics/exams` → `ClassExamListDTO`
  - `GET /api/classes/{class_id}/analytics/exams/{exam_key}` → `ClassExamDTO`
  - `GET /api/classes/{class_id}/analytics/exams/{exam_key}/questions/{question_id}` → `ExamQuestionAnswersDTO`
  - `GET /api/classes/{class_id}/analytics/exams/{exam_key}/marks.csv` → `text/csv`
  - `GET /api/teacher/students/{student_id}/papers/{attempt_id}` → `StudentPaperDTO`
  - Errors: foreign class 403, unknown class 404, malformed class id 422, malformed exam key 422, exam with no papers in class 404, unknown question 404, student outside rosters 403, unknown student 404, attempt not this student's 404.

- [ ] **Step 1: Write the schemas (no behaviour, needed by the tests)**

```python
# lemely/web/schemas_class_exams.py
"""DTOs for the teacher papers screens: class exams, spread, heatmap (redesign L8)."""

from __future__ import annotations

from pydantic import Field

from lemely.web.schemas import ApiModel


class GradeCountDTO(ApiModel):
    grade: str
    count: int


class ClassExamTileDTO(ApiModel):
    """One exam tile (frame E3)."""

    examKey: str
    title: str
    code: str
    session: str
    paperCount: int
    unsharedCount: int
    average: int | None = None
    gradeCounts: list[GradeCountDTO] = Field(default_factory=list)
    answersToReview: int = 0
    latestRecordedAt: str


class ClassExamListDTO(ApiModel):
    classId: str
    className: str
    studentCount: int
    exams: list[ClassExamTileDTO] = Field(default_factory=list)


class ExamQuestionDTO(ApiModel):
    questionId: str
    topic: str | None = None
    maximumMarks: int
    averagePercent: int
    blankCount: int


class ExamStudentDTO(ApiModel):
    studentId: str
    displayName: str
    attemptId: str
    awardedMarks: int
    maximumMarks: int
    percentage: float
    grade: str
    deltaPercent: int | None = None
    unshared: bool
    recordedAt: str


class HeatmapCellValueDTO(ApiModel):
    questionId: str
    awarded: int | None = None
    maximum: int
    questionResultId: str


class HeatmapRowDTO(ApiModel):
    studentId: str
    attemptId: str
    cells: list[HeatmapCellValueDTO] = Field(default_factory=list)


class ClassExamDTO(ApiModel):
    """The exam screen (X5, X6, F_X7, Z_exam_sparse)."""

    classId: str
    className: str
    studentCount: int
    examKey: str
    title: str
    code: str
    session: str
    paperCount: int
    unsharedCount: int
    average: int | None = None
    highest: int | None = None
    lowest: int | None = None
    gradeCounts: list[GradeCountDTO] = Field(default_factory=list)
    heatmapReady: bool
    heatmapMinPapers: int
    answersToReview: int = 0
    questions: list[ExamQuestionDTO] = Field(default_factory=list)
    students: list[ExamStudentDTO] = Field(default_factory=list)
    heatmap: list[HeatmapRowDTO] = Field(default_factory=list)


class ExamAnswerDTO(ApiModel):
    studentId: str
    displayName: str
    attemptId: str
    questionResultId: str
    awarded: int | None = None
    maximum: int
    studentAnswer: str | None = None
    reviewItemId: str | None = None


class ExamQuestionAnswersDTO(ApiModel):
    """Every shared answer to one question (tap a column / See answers)."""

    examKey: str
    questionId: str
    topic: str | None = None
    maximumMarks: int
    averagePercent: int
    answers: list[ExamAnswerDTO] = Field(default_factory=list)


class StudentPaperQuestionDTO(ApiModel):
    questionResultId: str
    questionId: str
    topic: str | None = None
    awarded: int | None = None
    maximum: int
    marksLost: int
    reviewReason: str | None = None
    reviewItemId: str | None = None
    studentAnswer: str | None = None
    expectedAnswer: str | None = None
    feedback: str | None = None


class StudentPaperDTO(ApiModel):
    """One student's paper in the review-queue layout (frame O1)."""

    studentId: str
    displayName: str
    attemptId: str
    title: str
    code: str
    session: str
    awardedMarks: int
    maximumMarks: int
    percentage: float
    grade: str
    recordedAt: str
    answersToReview: int
    questions: list[StudentPaperQuestionDTO] = Field(default_factory=list)
```

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_web_class_exams.py
"""Class exam routes: tenancy, spread, heatmap, answers, CSV, student paper (L8)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.db.base import Base
from lemely.db.class_exclusion_repo import ClassExclusionRepository
from lemely.db.class_repo import ClassService
from lemely.db.exam_cells_repo import ExamCellsRepository
from lemely.db.history_repo import DbHistoryStore
from lemely.db.models import User
from lemely.db.models.attempts import Attempt, QuestionResult
from lemely.db.models.enums import (
    ConfidenceBand,
    MarkerSource,
    ReviewReason,
    ReviewStatus,
    Role,
    SessionMonth,
)
from lemely.db.models.ops import ReviewQueueItem
from lemely.runtime.config import DatabaseSettings
from lemely.web import create_app
from lemely.web.deps import (
    AuthContext,
    get_auth_context,
    get_class_exclusion_repository,
    get_class_service,
    get_exam_cells_repo,
    get_history_store,
)

if TYPE_CHECKING:
    from collections.abc import Iterator


def _reachable(url: str) -> bool:
    engine = create_engine(make_url(url).set(database="postgres"))
    try:
        with engine.connect():
            return True
    except OperationalError:
        return False
    finally:
        engine.dispose()


@pytest.fixture
def sm() -> Iterator[sessionmaker[Session]]:
    base_url = DatabaseSettings().url
    if not _reachable(base_url):
        pytest.skip("local Postgres not reachable")
    admin = create_engine(make_url(base_url).set(database="postgres"), isolation_level="AUTOCOMMIT")
    name = f"lemely_test_{uuid.uuid4().hex[:12]}"
    with admin.connect() as conn:
        conn.execute(sa.text(f'CREATE DATABASE "{name}"'))
    engine = create_engine(make_url(base_url).set(database=name))
    Base.metadata.create_all(engine)
    try:
        yield sessionmaker(bind=engine, expire_on_commit=False, future=True)
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture
def classes(sm: sessionmaker[Session]) -> ClassService:
    return ClassService(sm)


@pytest.fixture
def client(sm: sessionmaker[Session], classes: ClassService) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_history_store] = lambda: DbHistoryStore(sm)
    app.dependency_overrides[get_class_service] = lambda: classes
    app.dependency_overrides[get_class_exclusion_repository] = lambda: ClassExclusionRepository(sm)
    app.dependency_overrides[get_exam_cells_repo] = lambda: ExamCellsRepository(sm)
    yield TestClient(app)
    app.dependency_overrides.clear()


def _user(sm: sessionmaker[Session], role: Role, name: str | None = None) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as s:
        s.add(User(id=uid, email=f"{uid}@example.com", role=role, display_name=name))
    return uid


def _as(client: TestClient, user: uuid.UUID, role: Role = Role.teacher) -> None:
    client.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[union-attr]
        user_id=str(user), role=role.value
    )


def _paper(
    sm: sessionmaker[Session],
    student: uuid.UUID,
    marks: list[int | None],
    *,
    grade: str,
    days_ago: int = 1,
    paper: int = 4,
    review_q: int | None = None,
) -> uuid.UUID:
    """One 0580/4x May/June 2025 attempt with three 4-mark questions."""
    attempt = uuid.uuid4()
    awarded = sum(m or 0 for m in marks)
    with sm.begin() as s:
        s.add(
            Attempt(
                id=attempt,
                user_id=student,
                subject_code="0580",
                session_month=SessionMonth.may_june,
                session_year=2025,
                paper_number=paper,
                paper_variant=2,
                awarded_marks=awarded,
                maximum_marks=12,
                percentage=round(awarded / 12 * 100, 2),
                grade=grade,
                recorded_at=datetime.now(UTC) - timedelta(days=days_ago),
            )
        )
        s.flush()
        for i, mark in enumerate(marks, start=1):
            qr = QuestionResult(
                id=uuid.uuid4(),
                attempt_id=attempt,
                question_id=str(i),
                awarded_marks=mark or 0,
                maximum_marks=4,
                confidence_band=ConfidenceBand.high,
                confidence_score=0.9,
                marker_source=MarkerSource.blank if mark is None else MarkerSource.ai,
                topic=["Percentages", "Density and units", "Vectors"][i - 1],
                student_answer=None if mark is None else f"answer {i}",
            )
            s.add(qr)
            s.flush()
            if review_q == i:
                s.add(
                    ReviewQueueItem(
                        attempt_id=attempt,
                        question_result_id=qr.id,
                        question_id=str(i),
                        reason=ReviewReason.low_confidence,
                        status=ReviewStatus.open,
                    )
                )
    return attempt


def _class_with(
    sm: sessionmaker[Session], classes: ClassService, n: int
) -> tuple[uuid.UUID, str, list[uuid.UUID]]:
    teacher = _user(sm, Role.teacher)
    cls = classes.create_class(teacher, "10B")
    assert cls.join_code is not None
    students = []
    for i in range(n):
        student = _user(sm, Role.student, f"Student {i}")
        classes.join_by_code(student, cls.join_code)
        students.append(student)
    return teacher, str(cls.class_id), students


KEY = "0580-42-mj-2025"


def test_exam_list_groups_attempts_into_tiles(client: TestClient, sm, classes) -> None:
    teacher, class_id, (a, b) = _class_with(sm, classes, 2)
    _paper(sm, a, [4, 4, 4], grade="A*", review_q=2)
    _paper(sm, b, [2, 0, None], grade="E")
    _paper(sm, b, [1, 1, 1], grade="E", paper=2, days_ago=40)
    _as(client, teacher)
    body = client.get(f"/api/classes/{class_id}/analytics/exams").json()
    assert body["className"] == "10B"
    assert body["studentCount"] == 2
    assert [e["examKey"] for e in body["exams"]] == [KEY, "0580-22-mj-2025"]
    tile = body["exams"][0]
    assert tile["code"] == "0580/42"
    assert tile["session"] == "May/Jun 2025"
    assert tile["paperCount"] == 2
    assert tile["average"] == 58
    assert tile["answersToReview"] == 1
    assert tile["title"].endswith("Paper 4")


def test_exam_detail_spread_questions_heatmap(client: TestClient, sm, classes) -> None:
    teacher, class_id, students = _class_with(sm, classes, 5)
    marks = [[4, 4, 4], [4, 2, 0], [2, 1, None], [3, 0, 4], [1, 0, 2]]
    for student, row in zip(students, marks, strict=True):
        _paper(sm, student, row, grade="C")
    _as(client, teacher)
    body = client.get(f"/api/classes/{class_id}/analytics/exams/{KEY}").json()
    assert body["paperCount"] == 5
    assert body["heatmapReady"] is True
    assert body["heatmapMinPapers"] == 5
    assert [q["questionId"] for q in body["questions"]] == ["1", "2", "3"]
    assert body["questions"][1]["averagePercent"] == 35
    assert body["questions"][2]["blankCount"] == 1
    assert len(body["heatmap"]) == 5
    blank_row = next(r for r in body["heatmap"] if any(c["awarded"] is None for c in r["cells"]))
    assert blank_row["cells"][2]["questionResultId"]
    assert body["students"][0]["percentage"] <= body["students"][-1]["percentage"]


def test_unshared_paper_listed_but_not_counted(client: TestClient, sm, classes) -> None:
    teacher, class_id, (a, b) = _class_with(sm, classes, 2)
    _paper(sm, a, [4, 4, 4], grade="A*")
    hidden = _paper(sm, b, [0, 0, 0], grade="U")
    _as(client, teacher)
    assert client.post(f"/api/classes/{class_id}/papers/{hidden}/unshare").status_code == 204
    body = client.get(f"/api/classes/{class_id}/analytics/exams/{KEY}").json()
    assert body["paperCount"] == 1
    assert body["unsharedCount"] == 1
    assert body["average"] == 100
    assert body["students"][-1]["unshared"] is True
    assert body["students"][-1]["attemptId"] == str(hidden)
    assert body["heatmapReady"] is False


def test_question_answers_lowest_first(client: TestClient, sm, classes) -> None:
    teacher, class_id, (a, b) = _class_with(sm, classes, 2)
    _paper(sm, a, [4, 4, 4], grade="A*")
    _paper(sm, b, [2, None, 1], grade="E", review_q=2)
    _as(client, teacher)
    body = client.get(f"/api/classes/{class_id}/analytics/exams/{KEY}/questions/2").json()
    assert body["topic"] == "Density and units"
    assert body["maximumMarks"] == 4
    assert [x["awarded"] for x in body["answers"]] == [None, 4]
    assert body["answers"][0]["reviewItemId"]
    assert client.get(f"/api/classes/{class_id}/analytics/exams/{KEY}/questions/99").status_code == 404


def test_marks_csv(client: TestClient, sm, classes) -> None:
    teacher, class_id, (a,) = _class_with(sm, classes, 1)
    _paper(sm, a, [4, None, 1], grade="C")
    _as(client, teacher)
    res = client.get(f"/api/classes/{class_id}/analytics/exams/{KEY}/marks.csv")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/csv")
    assert 'filename="10B 0580-42 May-Jun 2025.csv"' in res.headers["content-disposition"]
    lines = res.text.strip().splitlines()
    assert lines[0] == "Student,Q1,Q2,Q3,Total,Out of,Percentage,Grade,Shared with class"
    assert lines[1] == "Student 0,4,,1,5,12,42,C,yes"


def test_tenancy_and_validation(client: TestClient, sm, classes) -> None:
    teacher, class_id, (a,) = _class_with(sm, classes, 1)
    _paper(sm, a, [4, 4, 4], grade="A*")
    stranger = _user(sm, Role.teacher)
    _as(client, stranger)
    assert client.get(f"/api/classes/{class_id}/analytics/exams").status_code == 403
    assert client.get(f"/api/classes/{class_id}/analytics/exams/{KEY}").status_code == 403
    assert client.get(f"/api/classes/{class_id}/analytics/exams/{KEY}/marks.csv").status_code == 403
    _as(client, teacher)
    assert client.get(f"/api/classes/{uuid.uuid4()}/analytics/exams").status_code == 404
    assert client.get("/api/classes/not-a-uuid/analytics/exams").status_code == 422
    assert client.get(f"/api/classes/{class_id}/analytics/exams/garbage").status_code == 422
    assert client.get(f"/api/classes/{class_id}/analytics/exams/0625-11-on-2020").status_code == 404
    student = _user(sm, Role.student)
    _as(client, student, Role.student)
    assert client.get(f"/api/classes/{class_id}/analytics/exams").status_code == 403
    admin = _user(sm, Role.platform_admin)
    _as(client, admin, Role.platform_admin)
    assert client.get(f"/api/classes/{class_id}/analytics/exams").status_code == 403


def test_empty_class_lists_no_exams(client: TestClient, sm, classes) -> None:
    teacher, class_id, _ = _class_with(sm, classes, 0)
    _as(client, teacher)
    body = client.get(f"/api/classes/{class_id}/analytics/exams").json()
    assert body["exams"] == []
    assert body["studentCount"] == 0


def test_student_paper_view(client: TestClient, sm, classes) -> None:
    teacher, _class_id, (a,) = _class_with(sm, classes, 1)
    attempt = _paper(sm, a, [4, 1, None], grade="C", review_q=2)
    _as(client, teacher)
    body = client.get(f"/api/teacher/students/{a}/papers/{attempt}").json()
    assert body["code"] == "0580/42"
    assert body["answersToReview"] == 1
    assert [(q["questionId"], q["marksLost"]) for q in body["questions"]] == [("1", 0), ("2", 3), ("3", 4)]
    assert body["questions"][1]["reviewItemId"]
    assert client.get(f"/api/teacher/students/{a}/papers/{uuid.uuid4()}").status_code == 404
    stranger = _user(sm, Role.teacher)
    _as(client, stranger)
    assert client.get(f"/api/teacher/students/{a}/papers/{attempt}").status_code == 403
    _as(client, teacher)
    assert client.get(f"/api/teacher/students/{uuid.uuid4()}/papers/{attempt}").status_code == 404
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `PYTHONPATH=$(pwd) .venv/bin/pytest tests/test_web_class_exams.py -q`
Expected: FAIL (404 on every route; module `lemely.web.routers.class_exams` missing once imported in `app.py`).

- [ ] **Step 4: Write the router**

```python
# lemely/web/routers/class_exams.py
"""Per-exam class analytics for the teacher papers screens (redesign L8).

Extends ``/api/classes/{class_id}/analytics`` with exam tiles, one exam's
spread / question averages / heatmap, every answer to one question, a CSV of
marks, and one student's paper for the review-queue layout.

Tenancy mirrors ``classes.class_analytics`` exactly: router-level staff
guard, then ``ClassService.get_class``/``roster`` (foreign class 403, unknown
404, malformed 422). The student-paper route uses ``_visible_students``, the
gate ``GET /teacher/students/{id}`` already uses.

Records come from the **unscoped** history store so an unshared paper stays
visible (marked ``unshared``), the same reason ``list_class_papers`` reads
unscoped; :func:`lemely.core.class_exams.summarise_exam` keeps it out of
every number.
"""

from __future__ import annotations

import csv
import io
from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from lemely.core.class_exams import (
    HEATMAP_MIN_PAPERS,
    ExamIdentity,
    ExamPaper,
    ExamSummary,
    csv_rows,
    group_by_exam,
    identity_of,
    parse_exam_key,
    previous_in_subject,
    summarise_exam,
)
from lemely.core.history import HistoryStoreProtocol, grade_bearing
from lemely.db.class_exclusion_repo import ClassExclusionRepository
from lemely.db.class_history import load_roster_histories
from lemely.db.class_repo import ClassNotFoundError, ClassOwnershipError, ClassRow, ClassService, RosterEntry
from lemely.db.exam_cells_repo import ExamCellsRepository
from lemely.db.models.enums import Role
from lemely.web.deps import (
    AuthContext,
    get_class_exclusion_repository,
    get_class_service,
    get_exam_cells_repo,
    get_history_store,
    require_role,
)
from lemely.web.routers.classes import _class_subject_name, _raise_for
from lemely.web.routers.teacher import _visible_students
from lemely.web.schemas_class_exams import (
    ClassExamDTO,
    ClassExamListDTO,
    ClassExamTileDTO,
    ExamAnswerDTO,
    ExamQuestionAnswersDTO,
    ExamQuestionDTO,
    ExamStudentDTO,
    GradeCountDTO,
    HeatmapCellValueDTO,
    HeatmapRowDTO,
    StudentPaperDTO,
    StudentPaperQuestionDTO,
)

_STAFF_ROLES = (Role.teacher, Role.school_admin, Role.platform_admin)

router = APIRouter(prefix="/api", dependencies=[Depends(require_role(*_STAFF_ROLES))])

Auth = Annotated[AuthContext, Depends(require_role(*_STAFF_ROLES))]
Classes = Annotated[ClassService, Depends(get_class_service)]
History = Annotated[HistoryStoreProtocol, Depends(get_history_store)]
Exclusions = Annotated[ClassExclusionRepository, Depends(get_class_exclusion_repository)]
Cells = Annotated[ExamCellsRepository, Depends(get_exam_cells_repo)]


def _scope(service: ClassService, auth: AuthContext, class_id: str) -> tuple[ClassRow, list[RosterEntry]]:
    try:
        row = service.get_class(auth.user_id, auth.role, class_id)
        roster = service.roster(auth.user_id, auth.role, class_id)
    except (ClassNotFoundError, ClassOwnershipError) as exc:
        _raise_for(exc)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return row, roster


def _papers(
    row: ClassRow, roster: list[RosterEntry], history: HistoryStoreProtocol, exclusions: ClassExclusionRepository
) -> list[ExamPaper]:
    excluded = exclusions.excluded_attempt_ids(row.class_id)
    out: list[ExamPaper] = []
    for entry, student_history in load_roster_histories(history, roster):
        records = grade_bearing(student_history.records)
        for record in records:
            if record.attempt_id is None:
                continue
            out.append(
                ExamPaper(
                    student_id=str(entry.student_id),
                    display_name=entry.display_name,
                    record=record,
                    unshared=record.attempt_id in excluded,
                    previous_percentage=previous_in_subject(records, record),
                )
            )
    return out


def _title(identity: ExamIdentity) -> str:
    name = _class_subject_name(identity.subject_code) or identity.subject_code
    return f"{name} Paper {identity.paper_number}"


def _not_found(detail: str) -> NoReturn:
    raise HTTPException(status_code=404, detail=detail)


def _exam(
    exam_key: str, row: ClassRow, roster: list[RosterEntry], history: HistoryStoreProtocol,
    exclusions: ClassExclusionRepository, cells: ExamCellsRepository,
) -> ExamSummary:
    identity = parse_exam_key(exam_key)
    if identity is None:
        raise HTTPException(status_code=422, detail=f"Malformed exam key: {exam_key!r}")
    papers = group_by_exam(_papers(row, roster, history, exclusions)).get(identity.key, [])
    if not papers:
        _not_found(f"No marked papers for {identity.code_label} {identity.session_label} in this class")
    by_attempt = cells.cells_for_attempts([p.attempt_id for p in papers])
    with_cells = [
        ExamPaper(
            student_id=p.student_id,
            display_name=p.display_name,
            record=p.record,
            unshared=p.unshared,
            cells=by_attempt.get(p.attempt_id, ()),
            previous_percentage=p.previous_percentage,
        )
        for p in papers
    ]
    return summarise_exam(identity, with_cells)


def _grade_counts(summary: ExamSummary) -> list[GradeCountDTO]:
    return [GradeCountDTO(grade=g, count=c) for g, c in summary.grade_counts]


@router.get("/classes/{class_id}/analytics/exams", response_model=ClassExamListDTO)
def list_class_exams(
    class_id: str, auth: Auth, service: Classes, history: History, exclusions: Exclusions, cells: Cells
) -> ClassExamListDTO:
    """Exam tiles for one class, newest first (frame E3)."""
    row, roster = _scope(service, auth, class_id)
    groups = group_by_exam(_papers(row, roster, history, exclusions))
    reviews = cells.open_review_counts([p.attempt_id for ps in groups.values() for p in ps if not p.unshared])
    tiles: list[ClassExamTileDTO] = []
    for papers in groups.values():
        identity = identity_of(papers[0].record)
        summary = summarise_exam(identity, papers)
        tiles.append(
            ClassExamTileDTO(
                examKey=identity.key,
                title=_title(identity),
                code=identity.code_label,
                session=identity.session_label,
                paperCount=summary.paper_count,
                unsharedCount=summary.unshared_count,
                average=summary.average,
                gradeCounts=_grade_counts(summary),
                answersToReview=sum(reviews.get(p.attempt_id, 0) for p in papers if not p.unshared),
                latestRecordedAt=max(p.record.recorded_at for p in papers),
            )
        )
    tiles.sort(key=lambda t: t.latestRecordedAt, reverse=True)
    return ClassExamListDTO(classId=str(row.class_id), className=row.name, studentCount=len(roster), exams=tiles)


@router.get("/classes/{class_id}/analytics/exams/{exam_key}", response_model=ClassExamDTO)
def get_class_exam(
    class_id: str, exam_key: str, auth: Auth, service: Classes, history: History,
    exclusions: Exclusions, cells: Cells,
) -> ClassExamDTO:
    """One exam: spread, question averages, students, heatmap (X5/X6/F_X7)."""
    row, roster = _scope(service, auth, class_id)
    summary = _exam(exam_key, row, roster, history, exclusions, cells)
    shared_ids = [p.attempt_id for p in summary.students if not p.unshared]
    reviews = cells.open_review_counts(shared_ids)
    identity = summary.identity
    return ClassExamDTO(
        classId=str(row.class_id),
        className=row.name,
        studentCount=len(roster),
        examKey=identity.key,
        title=_title(identity),
        code=identity.code_label,
        session=identity.session_label,
        paperCount=summary.paper_count,
        unsharedCount=summary.unshared_count,
        average=summary.average,
        highest=summary.highest,
        lowest=summary.lowest,
        gradeCounts=_grade_counts(summary),
        heatmapReady=summary.heatmap_ready,
        heatmapMinPapers=HEATMAP_MIN_PAPERS,
        answersToReview=sum(reviews.values()),
        questions=[
            ExamQuestionDTO(
                questionId=q.question_id,
                topic=q.topic,
                maximumMarks=q.maximum,
                averagePercent=q.average_percent,
                blankCount=q.blank_count,
            )
            for q in summary.questions
        ],
        students=[
            ExamStudentDTO(
                studentId=p.student_id,
                displayName=p.display_name,
                attemptId=p.attempt_id,
                awardedMarks=p.record.awarded_marks,
                maximumMarks=p.record.maximum_marks,
                percentage=p.record.percentage,
                grade=p.record.grade,
                deltaPercent=p.delta,
                unshared=p.unshared,
                recordedAt=p.record.recorded_at,
            )
            for p in summary.students
        ],
        heatmap=[
            HeatmapRowDTO(
                studentId=p.student_id,
                attemptId=p.attempt_id,
                cells=[
                    HeatmapCellValueDTO(
                        questionId=c.question_id,
                        awarded=c.awarded,
                        maximum=c.maximum,
                        questionResultId=c.question_result_id,
                    )
                    for c in p.cells
                ],
            )
            for p in summary.students
            if p.cells
        ],
    )


@router.get(
    "/classes/{class_id}/analytics/exams/{exam_key}/questions/{question_id}",
    response_model=ExamQuestionAnswersDTO,
)
def get_exam_question_answers(
    class_id: str, exam_key: str, question_id: str, auth: Auth, service: Classes,
    history: History, exclusions: Exclusions, cells: Cells,
) -> ExamQuestionAnswersDTO:
    """Every shared answer to one question, lowest mark first, blanks first."""
    row, roster = _scope(service, auth, class_id)
    summary = _exam(exam_key, row, roster, history, exclusions, cells)
    stat = next((q for q in summary.questions if q.question_id == question_id), None)
    if stat is None:
        _not_found(f"No question {question_id!r} in this exam")
    shared = [p for p in summary.students if not p.unshared]
    answers = cells.answers_for_question([p.attempt_id for p in shared], question_id)
    rows = [
        ExamAnswerDTO(
            studentId=p.student_id,
            displayName=p.display_name,
            attemptId=p.attempt_id,
            questionResultId=a.question_result_id,
            awarded=a.awarded,
            maximum=a.maximum,
            studentAnswer=a.student_answer,
            reviewItemId=a.review_item_id,
        )
        for p in shared
        if (a := answers.get(p.attempt_id)) is not None
    ]
    rows.sort(key=lambda r: (-1 if r.awarded is None else r.awarded, r.displayName))
    return ExamQuestionAnswersDTO(
        examKey=summary.identity.key,
        questionId=question_id,
        topic=stat.topic,
        maximumMarks=stat.maximum,
        averagePercent=stat.average_percent,
        answers=rows,
    )


def _filename(class_name: str, identity: ExamIdentity) -> str:
    raw = f"{class_name} {identity.code_label} {identity.session_label}"
    safe = "".join(ch if ch.isalnum() or ch in " -_" else "-" for ch in raw)
    return f"{safe.strip()}.csv"


@router.get("/classes/{class_id}/analytics/exams/{exam_key}/marks.csv")
def download_exam_marks(
    class_id: str, exam_key: str, auth: Auth, service: Classes, history: History,
    exclusions: Exclusions, cells: Cells,
) -> Response:
    """Marks per question for every student in the exam, as CSV."""
    row, roster = _scope(service, auth, class_id)
    summary = _exam(exam_key, row, roster, history, exclusions, cells)
    buffer = io.StringIO()
    csv.writer(buffer, lineterminator="\n").writerows(csv_rows(summary))
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{_filename(row.name, summary.identity)}"'},
    )


@router.get("/teacher/students/{student_id}/papers/{attempt_id}", response_model=StudentPaperDTO)
def get_student_paper(
    student_id: str, attempt_id: str, auth: Auth, service: Classes, history: History, cells: Cells
) -> StudentPaperDTO:
    """One student's paper for the review-queue layout (frame O1)."""
    try:
        visible = _visible_students(service, auth)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    entry = visible.get(student_id)
    if entry is None:
        try:
            exists = service.user_exists(student_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if not exists:
            _not_found(f"Unknown student: {student_id}")
        raise HTTPException(status_code=403, detail=f"Student {student_id} is not in any of the caller's classes")
    record = next((r for r in history.load(student_id).records if r.attempt_id == attempt_id), None)
    if record is None:
        _not_found(f"No paper {attempt_id} for this student")
    identity = identity_of(record)
    questions = cells.paper_questions(attempt_id)
    return StudentPaperDTO(
        studentId=student_id,
        displayName=entry.display_name,
        attemptId=attempt_id,
        title=_title(identity),
        code=identity.code_label,
        session=identity.session_label,
        awardedMarks=record.awarded_marks,
        maximumMarks=record.maximum_marks,
        percentage=record.percentage,
        grade=record.grade,
        recordedAt=record.recorded_at,
        answersToReview=sum(1 for q in questions if q.review_item_id is not None),
        questions=[
            StudentPaperQuestionDTO(
                questionResultId=q.question_result_id,
                questionId=q.question_id,
                topic=q.topic,
                awarded=q.awarded,
                maximum=q.maximum,
                marksLost=q.maximum - (q.awarded or 0),
                reviewReason=q.review_reason,
                reviewItemId=q.review_item_id,
                studentAnswer=q.student_answer,
                expectedAnswer=q.expected_answer,
                feedback=q.feedback,
            )
            for q in questions
        ],
    )
```

`ClassRow.name` and `service.user_exists` are the names `classes.py` and `teacher.py` already use. If `ClassRow`'s name attribute differs, read `lemely/db/class_repo.py:ClassRow` and use its field.

- [ ] **Step 5: Register the router in `app.py`** (import `class_exams` in the routers import block; `app.include_router(class_exams.router)` after `app.include_router(classes.router)`).

- [ ] **Step 6: Run tests to verify they pass**

Run: `PYTHONPATH=$(pwd) .venv/bin/pytest tests/test_web_class_exams.py tests/test_web_classes.py -q`
Expected: PASS (new 8 tests; existing class tests unchanged).

- [ ] **Step 7: Commit**

```bash
PYTHONPATH=$(pwd) pre-commit run --files lemely/web/schemas_class_exams.py lemely/web/routers/class_exams.py lemely/web/app.py tests/test_web_class_exams.py
git commit -S -m "feat(web): class exam spread, heatmap, answers and marks CSV routes" -- lemely/web/schemas_class_exams.py lemely/web/routers/class_exams.py lemely/web/app.py tests/test_web_class_exams.py
```

---

### Task 4: StudentDetail data for the two-column screen

**Files:**
- Modify: `lemely/web/schemas_analytics.py` (`SubjectPredictionDTO`, `AttemptDTO`, `StudentTrendPointDTO`)
- Modify: `lemely/web/routers/teacher.py` (`_subject_predictions`, `_attempt_dto`, trend in `_student_detail_dto`, `teacher_student_detail` signature)
- Modify: `lemely/web/student_detail_view.py` (`project_for_tutor`)
- Test: `tests/test_web_student_detail_redesign.py`

**Interfaces:**
- Produces new optional DTO fields (all default so tutor and old clients keep working):
  - `SubjectPredictionDTO.subjectName: str | None`, `.previousGrade: str | None`, `.gradeLinePercent: float | None`
  - `AttemptDTO.attemptId: str | None`, `.sessionMonth: str | None`, `.sessionYear: int | None`, `.openReviews: int = 0`
  - `StudentTrendPointDTO.subjectCode: str | None`
- `_student_detail_dto(entry, history, *, now, acks, targets=None, boundaries=None, open_reviews=None)`; `boundaries` is any object with `resolve(metadata) -> (dict[str, float], str)` (percent thresholds, `GradeBoundaryStore.resolve`), `open_reviews` is `Mapping[str, int]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_web_student_detail_redesign.py
"""StudentDetail fields the redesigned screen reads (L8)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from lemely.core.history import PaperRecord, StudentHistory
from lemely.core.schemas import ExamMetadata
from lemely.db.class_repo import RosterEntry
from lemely.web.routers.teacher import _student_detail_dto
from lemely.web.student_detail_view import project_for_tutor


class _Boundaries:
    def resolve(self, metadata: ExamMetadata) -> tuple[dict[str, float], str]:
        return {"A*": 85.0, "A": 72.0, "B": 60.0, "C": 48.0}, "exact"


def _rec(pct: float, grade: str, days_ago: int, attempt: str, subject: str = "0580") -> PaperRecord:
    return PaperRecord(
        student_id="s",
        metadata=ExamMetadata(
            subject_code=subject, paper_number=4, paper_variant=2, session_month="May/June", session_year=2025
        ),
        awarded_marks=round(pct * 0.8),
        maximum_marks=80,
        percentage=pct,
        grade=grade,
        weak_areas=[],
        recorded_at=(datetime.now(UTC) - timedelta(days=days_ago)).isoformat(),
        attempt_id=attempt,
    )


def _dto():
    history = StudentHistory(
        student_id="s",
        records=[_rec(48, "C", 90, "a1"), _rec(63, "B", 2, "a2"), _rec(50, "C", 10, "p1", subject="0625")],
    )
    history.records.sort(key=lambda r: r.recorded_at)
    entry = RosterEntry(student_id=uuid.uuid4(), display_name="Omar Saleh")
    return _student_detail_dto(
        entry, history, now=datetime.now(UTC), acks={}, boundaries=_Boundaries(), open_reviews={"a2": 2}
    )


def test_subjects_carry_name_previous_grade_and_line() -> None:
    dto = _dto()
    maths = next(s for s in dto.subjects if s.subjectCode == "0580")
    assert maths.predictedGrade == "B"
    assert maths.previousGrade == "C"
    assert maths.gradeLinePercent == 60.0
    assert maths.subjectName
    physics = next(s for s in dto.subjects if s.subjectCode == "0625")
    assert physics.previousGrade is None


def test_attempts_and_trend_carry_ids_sessions_subjects() -> None:
    dto = _dto()
    newest = dto.attempts[0]
    assert newest.attemptId == "a2"
    assert newest.sessionMonth == "May/June"
    assert newest.sessionYear == 2025
    assert newest.openReviews == 2
    assert {p.subjectCode for p in dto.trend} == {"0580", "0625"}


def test_tutor_projection_strips_teacher_only_fields() -> None:
    projected = project_for_tutor(_dto(), zone="Africa/Cairo", now=datetime.now(UTC))
    assert all(a.attemptId is None and a.openReviews == 0 for a in projected.attempts)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=$(pwd) .venv/bin/pytest tests/test_web_student_detail_redesign.py -q`
Expected: FAIL (`_student_detail_dto() got an unexpected keyword argument 'boundaries'`).

- [ ] **Step 3: Implement**

`lemely/web/schemas_analytics.py`, add fields:

```python
class SubjectPredictionDTO(ApiModel):
    subjectCode: str
    predictedGrade: str
    latestPercentage: float
    paperCount: int
    subjectName: str | None = None
    previousGrade: str | None = None
    gradeLinePercent: float | None = None


class AttemptDTO(ApiModel):
    paperId: str
    subjectCode: str
    paperNumber: int
    paperVariant: int
    awardedMarks: int
    maximumMarks: int
    percentage: float
    grade: str
    recordedAt: str
    attemptId: str | None = None
    sessionMonth: str | None = None
    sessionYear: int | None = None
    openReviews: int = 0


class StudentTrendPointDTO(ApiModel):
    recordedAt: str
    percentage: float
    subjectCode: str | None = None
```

(Keep each class's existing docstring.)

`lemely/web/routers/teacher.py`:

```python
def _subject_predictions(
    history: StudentHistory, boundaries: _BoundaryResolver | None = None
) -> list[SubjectPredictionDTO]:
    # docstring unchanged, plus: previousGrade is the grade of the paper before
    # the latest in that subject; gradeLinePercent is the boundary for the
    # predicted grade on the latest paper's own sitting.
    by_subject: dict[str, list[PaperRecord]] = {}
    for record in grade_bearing(history.records):
        by_subject.setdefault(record.metadata.subject_code, []).append(record)
    out = []
    for code, records in by_subject.items():
        latest = records[-1]
        line = None
        if boundaries is not None:
            thresholds, _source = boundaries.resolve(latest.metadata)
            line = thresholds.get(latest.grade)
        out.append(
            SubjectPredictionDTO(
                subjectCode=code,
                predictedGrade=latest.grade,
                latestPercentage=latest.percentage,
                paperCount=len(records),
                subjectName=get_profile(code).name or code,
                previousGrade=records[-2].grade if len(records) > 1 else None,
                gradeLinePercent=line,
            )
        )
    return out
```

Add near the top of `teacher.py`:

```python
class _BoundaryResolver(Protocol):
    def resolve(self, metadata: ExamMetadata) -> tuple[dict[str, float], str]: ...
```

(import `Protocol` from `typing`, `ExamMetadata` from `lemely.core.schemas`, `get_profile` from `lemely.io.det.profiles` if not already imported; keep any existing return-statement ordering of the old comprehension.)

```python
def _attempt_dto(record: PaperRecord, open_reviews: Mapping[str, int] | None = None) -> AttemptDTO:
    """Convert one recorded paper into its T-05 attempt-history row."""
    m = record.metadata
    return AttemptDTO(
        paperId=_paper_id(record),
        subjectCode=m.subject_code,
        paperNumber=m.paper_number,
        paperVariant=m.paper_variant,
        awardedMarks=record.awarded_marks,
        maximumMarks=record.maximum_marks,
        percentage=record.percentage,
        grade=record.grade,
        recordedAt=record.recorded_at,
        attemptId=record.attempt_id,
        sessionMonth=m.session_month,
        sessionYear=m.session_year,
        openReviews=(open_reviews or {}).get(record.attempt_id or "", 0),
    )
```

In `_student_detail_dto` add keyword params `boundaries: _BoundaryResolver | None = None, open_reviews: Mapping[str, int] | None = None`, and change the three builders:

```python
        subjects=_subject_predictions(history, boundaries),
        attempts=[_attempt_dto(r, open_reviews) for r in reversed(paper_records)],
        ...
        trend=[
            StudentTrendPointDTO(
                recordedAt=r.recorded_at, percentage=r.percentage, subjectCode=r.metadata.subject_code
            )
            for r in paper_records
        ],
```

`teacher_student_detail` gains two dependencies and passes them:

```python
    boundaries: Annotated[GradeBoundaryStore, Depends(get_boundary_store)],
    cells: Annotated[ExamCellsRepository, Depends(get_exam_cells_repo)],
...
        history = history_store.load(student_id)
        acks = _acknowledgement_index(ack_service, auth, student_ids=[student_id])
        targets = profile_service.target_grades_for(student_id)
        open_reviews = cells.open_review_counts([r.attempt_id for r in history.records if r.attempt_id])
        return _student_detail_dto(
            entry, history, now=datetime.now(UTC), acks=acks, targets=targets,
            boundaries=boundaries, open_reviews=open_reviews,
        )
```

Every other caller of `_subject_predictions`/`_attempt_dto` keeps working because the new params default to `None`. Run `grep -n "_subject_predictions(\|_attempt_dto(\|_student_detail_dto(" lemely` to confirm; `build_student_detail_for_tutor` passes neither, so tutors get no grade line and no review counts.

`lemely/web/student_detail_view.py` `project_for_tutor`: change the attempts line to

```python
            "attempts": [
                attempt.model_copy(
                    update={"recordedAt": tutor_day(attempt.recordedAt, tz), "attemptId": None, "openReviews": 0}
                )
                for attempt in dto.attempts
            ],
```

Existing teacher-detail tests that override dependencies (`tests/test_web_teacher.py`) must also override `get_boundary_store` and `get_exam_cells_repo`. Add to that file's client fixture:

```python
    app.dependency_overrides[get_boundary_store] = lambda: _NoBoundaries()
    app.dependency_overrides[get_exam_cells_repo] = lambda: ExamCellsRepository(class_service._sessionmaker)
```

with

```python
class _NoBoundaries:
    def resolve(self, metadata):  # noqa: ANN001, ANN201
        return {}, "global_default"
```

- [ ] **Step 4: Run tests**

Run: `PYTHONPATH=$(pwd) .venv/bin/pytest tests/test_web_student_detail_redesign.py tests/test_student_detail_view.py tests/test_web_teacher.py tests/test_web_tutor_students.py -q`
Expected: PASS. (If `tests/test_web_tutor_students.py` does not exist, run `ls tests | grep tutor_student` and run that file instead.)

- [ ] **Step 5: Commit**

```bash
FILES="lemely/web/schemas_analytics.py lemely/web/routers/teacher.py lemely/web/student_detail_view.py tests/test_web_student_detail_redesign.py tests/test_web_teacher.py"
PYTHONPATH=$(pwd) pre-commit run --files $FILES
git commit -S -m "feat(web): student detail carries trend subject, grade line and paper ids" -- $FILES
```

---

### Task 5: Frontend types, API and hooks

**Files:**
- Create: `web/src/lib/classExamTypes.ts`
- Create: `web/src/lib/classExamApi.ts`
- Create: `web/src/lib/hooks/useClassExams.ts`
- Modify: `web/src/lib/teacherTypes.ts` (optional fields on `SubjectPrediction`, `Attempt`, `StudentTrendPoint`)
- Test: `web/tests/unit/classExamApi.test.ts`

**Interfaces:**
- Produces:
  - Types `GradeCount`, `ClassExamTile`, `ClassExamList`, `ExamQuestion`, `ExamStudent`, `HeatmapCellValue`, `HeatmapRow`, `ClassExam`, `ExamAnswer`, `ExamQuestionAnswers`, `StudentPaperQuestion`, `StudentPaper` (fields exactly as the DTOs in Task 3).
  - `classExamPaths = { list(classId), exam(classId, examKey), question(classId, examKey, questionId), marksCsv(classId, examKey), studentPaper(studentId, attemptId) }` returning paths relative to `/api`.
  - `classExamKeys = { list(classId), exam(classId, examKey), question(classId, examKey, questionId), studentPaper(studentId, attemptId) }`
  - `downloadExamMarks(classId: string, examKey: string, fileName: string): Promise<void>`
  - Hooks `useClassExams(classId)`, `useClassExam(classId, examKey)`, `useExamQuestionAnswers(classId, examKey, questionId | null)`, `useStudentPaper(studentId, attemptId)`.

- [ ] **Step 1: Write the failing test**

```ts
// web/tests/unit/classExamApi.test.ts
import { describe, expect, it } from "vitest"
import { classExamKeys, classExamPaths, marksFileName } from "@/lib/classExamApi"

describe("classExamPaths", () => {
  it("builds analytics exam paths with encoded segments", () => {
    expect(classExamPaths.list("c1")).toBe("/classes/c1/analytics/exams")
    expect(classExamPaths.exam("c1", "0580-42-mj-2025")).toBe("/classes/c1/analytics/exams/0580-42-mj-2025")
    expect(classExamPaths.question("c1", "0580-42-mj-2025", "2 a")).toBe(
      "/classes/c1/analytics/exams/0580-42-mj-2025/questions/2%20a",
    )
    expect(classExamPaths.marksCsv("c1", "k")).toBe("/classes/c1/analytics/exams/k/marks.csv")
    expect(classExamPaths.studentPaper("s1", "a1")).toBe("/teacher/students/s1/papers/a1")
  })
})

describe("classExamKeys", () => {
  it("nests every exam key under the class prefix the unshare hooks invalidate", () => {
    const prefix = ["teacher", "class", "c1"]
    expect(classExamKeys.list("c1").slice(0, 3)).toEqual(prefix)
    expect(classExamKeys.exam("c1", "k").slice(0, 3)).toEqual(prefix)
    expect(classExamKeys.question("c1", "k", "2").slice(0, 3)).toEqual(prefix)
    expect(classExamKeys.studentPaper("s1", "a1")).toEqual(["teacher", "student", "s1", "paper", "a1"])
  })
})

describe("marksFileName", () => {
  it("names the CSV after the class, code and session", () => {
    expect(marksFileName("10B", "0580/42", "May/Jun 2025")).toBe("10B 0580-42 May-Jun 2025.csv")
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `cd web && npx vitest run tests/unit/classExamApi.test.ts`
Expected: FAIL (cannot resolve `@/lib/classExamApi`).

- [ ] **Step 3: Implement**

```ts
// web/src/lib/classExamTypes.ts
/* Wire types for `lemely/web/schemas_class_exams.py` (redesign L8). */

export interface GradeCount {
  grade: string
  count: number
}

export interface ClassExamTile {
  examKey: string
  title: string
  code: string
  session: string
  paperCount: number
  unsharedCount: number
  average: number | null
  gradeCounts: GradeCount[]
  answersToReview: number
  latestRecordedAt: string
}

export interface ClassExamList {
  classId: string
  className: string
  studentCount: number
  exams: ClassExamTile[]
}

export interface ExamQuestion {
  questionId: string
  topic: string | null
  maximumMarks: number
  averagePercent: number
  blankCount: number
}

export interface ExamStudent {
  studentId: string
  displayName: string
  attemptId: string
  awardedMarks: number
  maximumMarks: number
  percentage: number
  grade: string
  deltaPercent: number | null
  unshared: boolean
  recordedAt: string
}

export interface HeatmapCellValue {
  questionId: string
  awarded: number | null
  maximum: number
  questionResultId: string
}

export interface HeatmapRow {
  studentId: string
  attemptId: string
  cells: HeatmapCellValue[]
}

export interface ClassExam {
  classId: string
  className: string
  studentCount: number
  examKey: string
  title: string
  code: string
  session: string
  paperCount: number
  unsharedCount: number
  average: number | null
  highest: number | null
  lowest: number | null
  gradeCounts: GradeCount[]
  heatmapReady: boolean
  heatmapMinPapers: number
  answersToReview: number
  questions: ExamQuestion[]
  students: ExamStudent[]
  heatmap: HeatmapRow[]
}

export interface ExamAnswer {
  studentId: string
  displayName: string
  attemptId: string
  questionResultId: string
  awarded: number | null
  maximum: number
  studentAnswer: string | null
  reviewItemId: string | null
}

export interface ExamQuestionAnswers {
  examKey: string
  questionId: string
  topic: string | null
  maximumMarks: number
  averagePercent: number
  answers: ExamAnswer[]
}

export interface StudentPaperQuestion {
  questionResultId: string
  questionId: string
  topic: string | null
  awarded: number | null
  maximum: number
  marksLost: number
  reviewReason: string | null
  reviewItemId: string | null
  studentAnswer: string | null
  expectedAnswer: string | null
  feedback: string | null
}

export interface StudentPaper {
  studentId: string
  displayName: string
  attemptId: string
  title: string
  code: string
  session: string
  awardedMarks: number
  maximumMarks: number
  percentage: number
  grade: string
  recordedAt: string
  answersToReview: number
  questions: StudentPaperQuestion[]
}
```

```ts
// web/src/lib/classExamApi.ts
// L8 — class exam analytics (`lemely/web/routers/class_exams.py`).
import { fetchBlobUrl, request } from "@/lib/api"
import type { ClassExam, ClassExamList, ExamQuestionAnswers, StudentPaper } from "@/lib/classExamTypes"

const enc = encodeURIComponent

export const classExamPaths = {
  list: (classId: string) => `/classes/${enc(classId)}/analytics/exams`,
  exam: (classId: string, examKey: string) => `/classes/${enc(classId)}/analytics/exams/${enc(examKey)}`,
  question: (classId: string, examKey: string, questionId: string) =>
    `/classes/${enc(classId)}/analytics/exams/${enc(examKey)}/questions/${enc(questionId)}`,
  marksCsv: (classId: string, examKey: string) =>
    `/classes/${enc(classId)}/analytics/exams/${enc(examKey)}/marks.csv`,
  studentPaper: (studentId: string, attemptId: string) =>
    `/teacher/students/${enc(studentId)}/papers/${enc(attemptId)}`,
}

export const classExamKeys = {
  list: (classId: string) => ["teacher", "class", classId, "exams"] as const,
  exam: (classId: string, examKey: string) => ["teacher", "class", classId, "exam", examKey] as const,
  question: (classId: string, examKey: string, questionId: string) =>
    ["teacher", "class", classId, "exam", examKey, "question", questionId] as const,
  studentPaper: (studentId: string, attemptId: string) =>
    ["teacher", "student", studentId, "paper", attemptId] as const,
}

export const fetchClassExams = (classId: string) => request<ClassExamList>(classExamPaths.list(classId))
export const fetchClassExam = (classId: string, examKey: string) =>
  request<ClassExam>(classExamPaths.exam(classId, examKey))
export const fetchExamQuestionAnswers = (classId: string, examKey: string, questionId: string) =>
  request<ExamQuestionAnswers>(classExamPaths.question(classId, examKey, questionId))
export const fetchStudentPaper = (studentId: string, attemptId: string) =>
  request<StudentPaper>(classExamPaths.studentPaper(studentId, attemptId))

/** Mirrors the server's Content-Disposition name so the saved file matches. */
export function marksFileName(className: string, code: string, session: string): string {
  const raw = `${className} ${code} ${session}`
  return `${raw.replace(/[^A-Za-z0-9 _-]/g, "-").trim()}.csv`
}

/** Fetch the CSV with the session's auth, then save it through a temporary link. */
export async function downloadExamMarks(classId: string, examKey: string, fileName: string): Promise<void> {
  const url = await fetchBlobUrl(classExamPaths.marksCsv(classId, examKey))
  try {
    const a = document.createElement("a")
    a.href = url
    a.download = fileName
    document.body.appendChild(a)
    a.click()
    a.remove()
  } finally {
    URL.revokeObjectURL(url)
  }
}
```

```ts
// web/src/lib/hooks/useClassExams.ts
// L8 — class exam query hooks. Keys sit under ["teacher","class",classId] so
// useUnshareClassPaper / useReshareClassPaper already invalidate them.
import { useQuery, type UseQueryResult } from "@tanstack/react-query"
import {
  classExamKeys,
  fetchClassExam,
  fetchClassExams,
  fetchExamQuestionAnswers,
  fetchStudentPaper,
} from "@/lib/classExamApi"
import type { ClassExam, ClassExamList, ExamQuestionAnswers, StudentPaper } from "@/lib/classExamTypes"

export function useClassExams(classId: string | undefined): UseQueryResult<ClassExamList, Error> {
  return useQuery({
    queryKey: classExamKeys.list(classId ?? ""),
    queryFn: () => fetchClassExams(classId as string),
    enabled: !!classId,
  })
}

export function useClassExam(
  classId: string | undefined,
  examKey: string | undefined,
): UseQueryResult<ClassExam, Error> {
  return useQuery({
    queryKey: classExamKeys.exam(classId ?? "", examKey ?? ""),
    queryFn: () => fetchClassExam(classId as string, examKey as string),
    enabled: !!classId && !!examKey,
  })
}

export function useExamQuestionAnswers(
  classId: string | undefined,
  examKey: string | undefined,
  questionId: string | null,
): UseQueryResult<ExamQuestionAnswers, Error> {
  return useQuery({
    queryKey: classExamKeys.question(classId ?? "", examKey ?? "", questionId ?? ""),
    queryFn: () => fetchExamQuestionAnswers(classId as string, examKey as string, questionId as string),
    enabled: !!classId && !!examKey && !!questionId,
  })
}

export function useStudentPaper(
  studentId: string | undefined,
  attemptId: string | undefined,
): UseQueryResult<StudentPaper, Error> {
  return useQuery({
    queryKey: classExamKeys.studentPaper(studentId ?? "", attemptId ?? ""),
    queryFn: () => fetchStudentPaper(studentId as string, attemptId as string),
    enabled: !!studentId && !!attemptId,
  })
}
```

`web/src/lib/teacherTypes.ts` additions:

```ts
export interface SubjectPrediction {
  subjectCode: string
  predictedGrade: string
  latestPercentage: number
  paperCount: number
  subjectName?: string | null
  previousGrade?: string | null
  gradeLinePercent?: number | null
}

export interface Attempt {
  paperId: string
  subjectCode: string
  paperNumber: number
  paperVariant: number
  awardedMarks: number
  maximumMarks: number
  percentage: number
  grade: string
  recordedAt: string
  attemptId?: string | null
  sessionMonth?: string | null
  sessionYear?: number | null
  openReviews?: number
}

export interface StudentTrendPoint {
  recordedAt: string
  percentage: number
  subjectCode?: string | null
}
```

(Keep the existing doc comments above each interface.)

- [ ] **Step 4: Run to verify pass**

Run: `cd web && npx vitest run tests/unit/classExamApi.test.ts && npx tsc --noEmit -p .`
Expected: PASS; tsc clean.

- [ ] **Step 5: Commit**

```bash
FILES="web/src/lib/classExamTypes.ts web/src/lib/classExamApi.ts web/src/lib/hooks/useClassExams.ts web/src/lib/teacherTypes.ts web/tests/unit/classExamApi.test.ts"
PYTHONPATH=$(pwd) pre-commit run --files $FILES
git commit -S -m "feat(web): class exam API client, query keys and hooks" -- $FILES
```

---

### Task 6: Papers view model and heatmap scale

**Files:**
- Create: `web/src/portals/teacher/papers/papersViewModel.ts`
- Create: `web/src/portals/teacher/papers/heatmapScale.ts`
- Test: `web/tests/unit/papersViewModel.test.ts`, `web/tests/unit/heatmapScale.test.ts`

**Interfaces:**
- Consumes: Task 5 types.
- Produces:
  - `GRADE_BG: Record<string, string>` (grade → Tailwind bg class)
  - `type ClassExamsState = "first-run" | "sparse" | "normal"`; `classExamsState(list: ClassExamList): ClassExamsState`
  - `examTileModel(tile: ClassExamTile): ExamTileModel` with `{ key, title, codeLine, big, bigUnit, sub, chip: { label, tone: "low" } | null, segments: GradeSegment[] }`
  - `type GradeSegment = { grade: string; count: number; className: string }`; `gradeSegments(counts: GradeCount[]): GradeSegment[]`
  - `histogramColumns(counts: GradeCount[]): HistogramColumn[]` with `{ grade, count, heightPct, className }` (A*,A,B,C,D,E,U always; F,G only when non-zero; min height 6)
  - `type ExamScreenState = "sparse" | "normal"`; `examScreenState(exam: ClassExam): ExamScreenState`
  - `needsItems(exam: { answersToReview: number }, classId: string): NeedsItem[]` with `{ count, label, action, to }`
  - `lostMarks(exam: ClassExam, n?: number): LostMarkModel[]` with `{ questionId, label ("Q8"), topic, averagePercent, weak }`
  - `questionBars(exam: ClassExam): LostMarkModel[]` (all questions in order)
  - `studentRows(exam: ClassExam): StudentRowModel[]` with `{ studentId, attemptId, name, initials, marks, outOf, grade, delta: { text, tone: "up" | "down" } | null, unshared }`
  - `lowestStudents(exam: ClassExam, n: number): StudentRowModel[]` (shared only)
  - `answerSort(answers: ExamAnswer[], order: "lowest" | "highest"): ExamAnswer[]`
  - `sparseLine(exam: ClassExam): { title: string; body: string }`
  - `initials(name: string): string`
  - `heatmapFill(awarded: number | null, maximum: number): HeatmapFill` with `{ kind: "blank" | "zero" | "low" | "mid" | "high" | "full", background: string | null }`
  - `HEATMAP_LEGEND: { lost: string; full: string; ramp: string }`

- [ ] **Step 1: Write the failing tests**

```ts
// web/tests/unit/heatmapScale.test.ts
import { describe, expect, it } from "vitest"
import { heatmapFill } from "@/portals/teacher/papers/heatmapScale"

describe("heatmapFill", () => {
  it("buckets a mark into the five-step colour ramp", () => {
    expect(heatmapFill(4, 4).kind).toBe("full")
    expect(heatmapFill(3, 4).kind).toBe("high")
    expect(heatmapFill(2, 4).kind).toBe("mid")
    expect(heatmapFill(1, 4).kind).toBe("low")
    expect(heatmapFill(0, 4).kind).toBe("zero")
  })
  it("draws a blank as an outline with no fill", () => {
    expect(heatmapFill(null, 4)).toEqual({ kind: "blank", background: null })
  })
  it("treats a zero-mark question as full when awarded matches", () => {
    expect(heatmapFill(0, 0).kind).toBe("full")
  })
  it("uses tokens, never literal colours", () => {
    for (const a of [0, 1, 2, 3, 4]) expect(heatmapFill(a, 4).background).toMatch(/var\(--color-/)
  })
})
```

```ts
// web/tests/unit/papersViewModel.test.ts
import { describe, expect, it } from "vitest"
import type { ClassExam, ClassExamList, ClassExamTile, GradeCount } from "@/lib/classExamTypes"
import {
  answerSort,
  classExamsState,
  examScreenState,
  examTileModel,
  histogramColumns,
  initials,
  lostMarks,
  lowestStudents,
  needsItems,
  questionBars,
  sparseLine,
  studentRows,
} from "@/portals/teacher/papers/papersViewModel"

const ladder = (pairs: Record<string, number>): GradeCount[] =>
  ["A*", "A", "B", "C", "D", "E", "F", "G", "U"].map((grade) => ({ grade, count: pairs[grade] ?? 0 }))

const tile = (over: Partial<ClassExamTile> = {}): ClassExamTile => ({
  examKey: "0580-42-mj-2025",
  title: "Mathematics Paper 4",
  code: "0580/42",
  session: "May/Jun 2025",
  paperCount: 28,
  unsharedCount: 2,
  average: 63,
  gradeCounts: ladder({ A: 5, B: 10, C: 8, U: 1 }),
  answersToReview: 3,
  latestRecordedAt: "2025-06-10T00:00:00Z",
  ...over,
})

const exam = (over: Partial<ClassExam> = {}): ClassExam => ({
  classId: "c1",
  className: "10B",
  studentCount: 28,
  examKey: "0580-42-mj-2025",
  title: "Mathematics Paper 4",
  code: "0580/42",
  session: "May/Jun 2025",
  paperCount: 6,
  unsharedCount: 1,
  average: 63,
  highest: 92,
  lowest: 31,
  gradeCounts: ladder({ A: 2, B: 2, C: 1, U: 1 }),
  heatmapReady: true,
  heatmapMinPapers: 5,
  answersToReview: 5,
  questions: [
    { questionId: "1", topic: "Percentages", maximumMarks: 3, averagePercent: 80, blankCount: 0 },
    { questionId: "8", topic: "Density and units", maximumMarks: 4, averagePercent: 32, blankCount: 1 },
    { questionId: "12", topic: "Quadratics", maximumMarks: 7, averagePercent: 38, blankCount: 0 },
    { questionId: "4", topic: "Simultaneous eq.", maximumMarks: 4, averagePercent: 49, blankCount: 0 },
  ],
  students: [
    { studentId: "a", displayName: "Omar Saleh", attemptId: "t1", awardedMarks: 25, maximumMarks: 80, percentage: 31, grade: "U", deltaPercent: -6, unshared: false, recordedAt: "x" },
    { studentId: "b", displayName: "Layla Hassan", attemptId: "t2", awardedMarks: 70, maximumMarks: 80, percentage: 88, grade: "A*", deltaPercent: 4, unshared: false, recordedAt: "x" },
    { studentId: "c", displayName: "Nour Adel", attemptId: "t3", awardedMarks: 10, maximumMarks: 80, percentage: 12, grade: "U", deltaPercent: null, unshared: true, recordedAt: "x" },
  ],
  heatmap: [],
  ...over,
})

describe("classExamsState", () => {
  const list = (n: number): ClassExamList => ({
    classId: "c1",
    className: "10B",
    studentCount: 28,
    exams: Array.from({ length: n }, (_, i) => tile({ examKey: `k${i}` })),
  })
  it("picks first-run, sparse and normal by exam count", () => {
    expect(classExamsState(list(0))).toBe("first-run")
    expect(classExamsState(list(1))).toBe("sparse")
    expect(classExamsState(list(2))).toBe("normal")
  })
})

describe("examTileModel", () => {
  it("leads with the paper name, then code and session", () => {
    const m = examTileModel(tile())
    expect(m.title).toBe("Mathematics Paper 4")
    expect(m.codeLine).toBe("0580/42 · May/Jun 2025")
    expect(m.big).toBe("63")
    expect(m.bigUnit).toBe("%")
    expect(m.sub).toBe("average · 28 papers")
    expect(m.chip).toEqual({ label: "3 need you", tone: "low" })
  })
  it("drops the chip when nothing needs the teacher and pluralises one paper", () => {
    const m = examTileModel(tile({ answersToReview: 0, paperCount: 1 }))
    expect(m.chip).toBeNull()
    expect(m.sub).toBe("average · 1 paper")
  })
  it("draws only non-zero grade segments, in ladder order", () => {
    expect(examTileModel(tile()).segments.map((s) => s.grade)).toEqual(["A", "B", "C", "U"])
  })
})

describe("histogramColumns", () => {
  it("always shows A* to E and U, F and G only when present", () => {
    expect(histogramColumns(ladder({ B: 3 })).map((c) => c.grade)).toEqual(["A*", "A", "B", "C", "D", "E", "U"])
    expect(histogramColumns(ladder({ F: 1 })).map((c) => c.grade)).toContain("F")
  })
  it("scales to the tallest bar with a 6% floor", () => {
    const cols = histogramColumns(ladder({ A: 10, B: 5 }))
    expect(cols.find((c) => c.grade === "A")?.heightPct).toBe(100)
    expect(cols.find((c) => c.grade === "B")?.heightPct).toBe(50)
    expect(cols.find((c) => c.grade === "U")?.heightPct).toBe(6)
  })
})

describe("examScreenState and sparseLine", () => {
  it("is sparse under the heatmap gate", () => {
    expect(examScreenState(exam({ heatmapReady: false, paperCount: 3 }))).toBe("sparse")
    expect(examScreenState(exam())).toBe("normal")
  })
  it("says how many of the class are marked", () => {
    expect(sparseLine(exam({ paperCount: 3, studentCount: 28 }))).toEqual({
      title: "3 of 28 papers marked",
      body: "The class picture fills in as more come in. Add the rest of the set when it’s ready.",
    })
  })
})

describe("needsItems", () => {
  it("links answers to review into the class-filtered queue", () => {
    expect(needsItems({ answersToReview: 5 }, "c1")).toEqual([
      { count: 5, label: "answers to review", action: "Review", to: "/teacher/review?class_id=c1" },
    ])
    expect(needsItems({ answersToReview: 1 }, "c1")[0].label).toBe("answer to review")
    expect(needsItems({ answersToReview: 0 }, "c1")).toEqual([])
  })
})

describe("lostMarks and questionBars", () => {
  it("takes the three weakest questions, flagging under 40% as weak", () => {
    expect(lostMarks(exam()).map((q) => [q.label, q.weak])).toEqual([
      ["Q8", true],
      ["Q12", true],
      ["Q4", false],
    ])
  })
  it("keeps every question in paper order for phone bars", () => {
    expect(questionBars(exam()).map((q) => q.label)).toEqual(["Q1", "Q8", "Q12", "Q4"])
  })
})

describe("student rows", () => {
  it("formats marks, grade and delta, unshared last", () => {
    const rows = studentRows(exam())
    expect(rows.map((r) => r.name)).toEqual(["Omar Saleh", "Layla Hassan", "Nour Adel"])
    expect(rows[0]).toMatchObject({ initials: "OS", marks: 25, outOf: 80, delta: { text: "−6%", tone: "down" } })
    expect(rows[1].delta).toEqual({ text: "+4%", tone: "up" })
    expect(rows[2]).toMatchObject({ unshared: true, delta: null })
  })
  it("lowestStudents never includes unshared papers", () => {
    expect(lowestStudents(exam(), 5).map((r) => r.name)).toEqual(["Omar Saleh", "Layla Hassan"])
  })
  it("initials take the first letter of each word, max two", () => {
    expect(initials("Mariam Fawzy Adel")).toBe("MF")
    expect(initials("Cher")).toBe("C")
  })
})

describe("answerSort", () => {
  const a = (name: string, awarded: number | null) => ({
    studentId: name, displayName: name, attemptId: name, questionResultId: name,
    awarded, maximum: 4, studentAnswer: null, reviewItemId: null,
  })
  it("puts blanks first when lowest first, last when highest first", () => {
    const list = [a("b", 3), a("a", null), a("c", 1)]
    expect(answerSort(list, "lowest").map((x) => x.displayName)).toEqual(["a", "c", "b"])
    expect(answerSort(list, "highest").map((x) => x.displayName)).toEqual(["b", "c", "a"])
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `cd web && npx vitest run tests/unit/papersViewModel.test.ts tests/unit/heatmapScale.test.ts`
Expected: FAIL (modules missing).

- [ ] **Step 3: Implement**

```ts
// web/src/portals/teacher/papers/heatmapScale.ts
/*
 * The heatmap ramp from `teacher-r1/t.css` (`cellBg`): lost marks in soft
 * red, full marks in muted primary, a near-neutral middle. Built from existing
 * tokens with color-mix so it follows the theme; no new tokens (master plan).
 */
export type HeatmapKind = "blank" | "zero" | "low" | "mid" | "high" | "full"

export interface HeatmapFill {
  kind: HeatmapKind
  background: string | null
}

const BASE = "var(--color-surface-container-lowest)"
const mix = (token: string, pct: number) => `color-mix(in oklch, var(${token}) ${pct}%, ${BASE})`

const FILLS: Record<Exclude<HeatmapKind, "blank">, string> = {
  zero: mix("--color-error", 55),
  low: mix("--color-error", 22),
  mid: mix("--color-surface-container-high", 100),
  high: mix("--color-primary", 22),
  full: mix("--color-primary", 70),
}

export function heatmapFill(awarded: number | null, maximum: number): HeatmapFill {
  if (awarded === null) return { kind: "blank", background: null }
  const f = maximum > 0 ? awarded / maximum : 1
  const kind: Exclude<HeatmapKind, "blank"> =
    f >= 0.999 ? "full" : f >= 0.66 ? "high" : f >= 0.34 ? "mid" : f > 0 ? "low" : "zero"
  return { kind, background: FILLS[kind] }
}

export const HEATMAP_LEGEND = {
  lost: FILLS.zero,
  full: FILLS.full,
  ramp: `linear-gradient(90deg, ${FILLS.zero}, ${FILLS.low}, ${FILLS.mid}, ${FILLS.high}, ${FILLS.full})`,
}
```

```ts
// web/src/portals/teacher/papers/papersViewModel.ts
/*
 * Every decision the teacher papers screens make (L8). Screens render what
 * this returns and decide nothing themselves.
 */
import type {
  ClassExam,
  ClassExamList,
  ClassExamTile,
  ExamAnswer,
  ExamStudent,
  GradeCount,
} from "@/lib/classExamTypes"

export const GRADE_BG: Record<string, string> = {
  "A*": "bg-grade-a-star",
  A: "bg-grade-a",
  B: "bg-grade-b",
  C: "bg-grade-c",
  D: "bg-grade-d",
  E: "bg-grade-e",
  F: "bg-grade-f",
  G: "bg-grade-g",
  U: "bg-grade-u",
}

const ALWAYS = ["A*", "A", "B", "C", "D", "E", "U"]
const WEAK = 40
const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`

export type ClassExamsState = "first-run" | "sparse" | "normal"
export function classExamsState(list: ClassExamList): ClassExamsState {
  if (list.exams.length === 0) return "first-run"
  return list.exams.length === 1 ? "sparse" : "normal"
}

export interface GradeSegment {
  grade: string
  count: number
  className: string
}
export function gradeSegments(counts: GradeCount[]): GradeSegment[] {
  return counts
    .filter((c) => c.count > 0)
    .map((c) => ({ grade: c.grade, count: c.count, className: GRADE_BG[c.grade] ?? "bg-outline" }))
}

export interface ExamTileModel {
  key: string
  title: string
  codeLine: string
  big: string
  bigUnit: string
  sub: string
  chip: { label: string; tone: "low" } | null
  segments: GradeSegment[]
}
export function examTileModel(tile: ClassExamTile): ExamTileModel {
  return {
    key: tile.examKey,
    title: tile.title,
    codeLine: `${tile.code} · ${tile.session}`,
    big: tile.average === null ? "–" : String(tile.average),
    bigUnit: tile.average === null ? "" : "%",
    sub: `average · ${plural(tile.paperCount, "paper", "papers")}`,
    chip: tile.answersToReview > 0 ? { label: `${tile.answersToReview} need you`, tone: "low" } : null,
    segments: gradeSegments(tile.gradeCounts),
  }
}

export interface HistogramColumn {
  grade: string
  count: number
  heightPct: number
  className: string
}
export function histogramColumns(counts: GradeCount[]): HistogramColumn[] {
  const shown = counts.filter((c) => ALWAYS.includes(c.grade) || c.count > 0)
  const tallest = Math.max(1, ...shown.map((c) => c.count))
  return shown.map((c) => ({
    grade: c.grade,
    count: c.count,
    heightPct: Math.max(6, Math.round((c.count / tallest) * 100)),
    className: GRADE_BG[c.grade] ?? "bg-outline",
  }))
}

export type ExamScreenState = "sparse" | "normal"
export function examScreenState(exam: ClassExam): ExamScreenState {
  return exam.heatmapReady ? "normal" : "sparse"
}

export function sparseLine(exam: ClassExam): { title: string; body: string } {
  return {
    title: `${exam.paperCount} of ${exam.studentCount} papers marked`,
    body: "The class picture fills in as more come in. Add the rest of the set when it’s ready.",
  }
}

export interface NeedsItem {
  count: number
  label: string
  action: string
  to: string
}
export function needsItems(exam: { answersToReview: number }, classId: string): NeedsItem[] {
  if (exam.answersToReview <= 0) return []
  return [
    {
      count: exam.answersToReview,
      label: exam.answersToReview === 1 ? "answer to review" : "answers to review",
      action: "Review",
      to: `/teacher/review?class_id=${encodeURIComponent(classId)}`,
    },
  ]
}

export interface LostMarkModel {
  questionId: string
  label: string
  topic: string
  averagePercent: number
  weak: boolean
}
const toLost = (q: ClassExam["questions"][number]): LostMarkModel => ({
  questionId: q.questionId,
  label: `Q${q.questionId}`,
  topic: q.topic ?? "Untitled topic",
  averagePercent: q.averagePercent,
  weak: q.averagePercent < WEAK,
})
export function lostMarks(exam: ClassExam, n = 3): LostMarkModel[] {
  return [...exam.questions].sort((a, b) => a.averagePercent - b.averagePercent).slice(0, n).map(toLost)
}
export function questionBars(exam: ClassExam): LostMarkModel[] {
  return exam.questions.map(toLost)
}

export function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase() ?? "")
    .join("")
}

export interface StudentRowModel {
  studentId: string
  attemptId: string
  name: string
  initials: string
  marks: number
  outOf: number
  grade: string
  delta: { text: string; tone: "up" | "down" } | null
  unshared: boolean
}
const toRow = (s: ExamStudent): StudentRowModel => ({
  studentId: s.studentId,
  attemptId: s.attemptId,
  name: s.displayName,
  initials: initials(s.displayName),
  marks: s.awardedMarks,
  outOf: s.maximumMarks,
  grade: s.grade,
  delta:
    s.deltaPercent === null || s.unshared
      ? null
      : s.deltaPercent >= 0
        ? { text: `+${s.deltaPercent}%`, tone: "up" }
        : { text: `−${Math.abs(s.deltaPercent)}%`, tone: "down" },
  unshared: s.unshared,
})
export function studentRows(exam: ClassExam): StudentRowModel[] {
  return exam.students.map(toRow)
}
export function lowestStudents(exam: ClassExam, n: number): StudentRowModel[] {
  return exam.students.filter((s) => !s.unshared).slice(0, n).map(toRow)
}

export function answerSort(answers: ExamAnswer[], order: "lowest" | "highest"): ExamAnswer[] {
  const score = (a: ExamAnswer) => (a.awarded === null ? -1 : a.awarded)
  const sorted = [...answers].sort((a, b) => score(a) - score(b) || a.displayName.localeCompare(b.displayName))
  return order === "lowest" ? sorted : sorted.reverse()
}
```

Note on the `answerSort` "highest" expectation `["b","c","a"]`: reversing the lowest list `["a","c","b"]` gives exactly that.

- [ ] **Step 4: Run to verify pass**

Run: `cd web && npx vitest run tests/unit/papersViewModel.test.ts tests/unit/heatmapScale.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
FILES="web/src/portals/teacher/papers/papersViewModel.ts web/src/portals/teacher/papers/heatmapScale.ts web/tests/unit/papersViewModel.test.ts web/tests/unit/heatmapScale.test.ts"
PYTHONPATH=$(pwd) pre-commit run --files $FILES
git commit -S -m "feat(web): teacher papers view model and heatmap colour ramp" -- $FILES
```

---

### Task 7: StudentDetail view model

**Files:**
- Create: `web/src/portals/teacher/papers/studentDetailViewModel.ts`
- Test: `web/tests/unit/studentDetailViewModel.test.ts`

**Interfaces:**
- Consumes: `StudentDetail`, `Attempt`, `AtRiskFlag` from `teacherTypes.ts` (with Task 5's optional fields).
- Produces:
  - `type StudentDetailState = "empty" | "sparse" | "normal"`; `studentDetailState(s): StudentDetailState`
  - `headerSub(s: StudentDetail, activeSummary: string): string` (e.g. "Mathematics, Physics · active 2 h ago")
  - `subjectRows(s): SubjectRowModel[]` with `{ code, name, grade, line }` where line is "predicted · up from C" | "predicted · down from A" | "predicted · steady" | "from 1 paper"
  - `trendFor(s, subjectCode): TrendModel` with `{ points: { x: string; pct: number }[]; last: number | null; gradeLine: { pct: number; label: string } | null; ariaLabel: string }`
  - `riskModel(s): { flags: { reason: string; summary: string; acknowledged: boolean }[] } | null`
  - `weakTopics(s, n): WeakTopicModel[]` with `{ topic, lost: string ("−14"), evidence }`
  - `paperRows(s, recorded: (iso: string) => string): PaperRowModel[]` with `{ key, attemptId, title, when, toReview: string | null, marks, outOf, grade }`
  - `engagement(s, lastActive: string): { value: string; label: string }[]`
  - `SESSION_SHORT: Record<string, string>`

- [ ] **Step 1: Write the failing test**

```ts
// web/tests/unit/studentDetailViewModel.test.ts
import { describe, expect, it } from "vitest"
import type { StudentDetail } from "@/lib/teacherTypes"
import {
  engagement,
  headerSub,
  paperRows,
  riskModel,
  studentDetailState,
  subjectRows,
  trendFor,
  weakTopics,
} from "@/portals/teacher/papers/studentDetailViewModel"

const base = (over: Partial<StudentDetail> = {}): StudentDetail => ({
  studentId: "s1",
  displayName: "Omar Saleh",
  subjects: [
    { subjectCode: "0580", subjectName: "Mathematics", predictedGrade: "B", latestPercentage: 63, paperCount: 3, previousGrade: "C", gradeLinePercent: 60 },
    { subjectCode: "0625", subjectName: "Physics", predictedGrade: "C", latestPercentage: 50, paperCount: 1, previousGrade: null, gradeLinePercent: null },
  ],
  attempts: [
    { paperId: "0580/42", attemptId: "a3", subjectCode: "0580", paperNumber: 4, paperVariant: 2, awardedMarks: 50, maximumMarks: 80, percentage: 63, grade: "B", recordedAt: "2025-05-20T00:00:00Z", sessionMonth: "May/June", sessionYear: 2025, openReviews: 2 },
    { paperId: "0625/42", attemptId: "p1", subjectCode: "0625", paperNumber: 4, paperVariant: 2, awardedMarks: 40, maximumMarks: 80, percentage: 50, grade: "C", recordedAt: "2025-03-01T00:00:00Z", sessionMonth: "Feb/Mar", sessionYear: 2025, openReviews: 0 },
  ],
  weaknesses: [
    { topic: "Vectors", lostMarks: 4, maximumMarks: 10, accuracy: 0.6, questionIds: ["11"] },
    { topic: "Algebra", lostMarks: 14, maximumMarks: 24, accuracy: 0.41, questionIds: ["2", "4", "7", "9"] },
  ],
  trend: [
    { recordedAt: "2024-10-01T00:00:00Z", percentage: 48, subjectCode: "0580" },
    { recordedAt: "2025-03-01T00:00:00Z", percentage: 50, subjectCode: "0625" },
    { recordedAt: "2025-05-20T00:00:00Z", percentage: 63, subjectCode: "0580" },
  ],
  isAtRisk: true,
  atRiskFlags: [
    { reason: "declining", summary: "Score dropped 8% over the last 2 papers.", evidence: {}, acknowledged: null },
    { reason: "inactive", summary: "No practice for 4 days.", evidence: {}, acknowledged: { acknowledgedAt: "x", acknowledgedBy: "t", note: null } as never },
  ],
  engagement: { totalPapers: 12, lastActiveAt: "2025-05-20T00:00:00Z", daysSinceLastSubmission: 4 },
  ...over,
})

describe("studentDetailState", () => {
  it("is empty with no papers, sparse with one, normal after", () => {
    expect(studentDetailState(base({ attempts: [] }))).toBe("empty")
    expect(studentDetailState(base({ attempts: base().attempts.slice(0, 1) }))).toBe("sparse")
    expect(studentDetailState(base())).toBe("normal")
  })
})

describe("header and subjects", () => {
  it("lists subject names then activity", () => {
    expect(headerSub(base(), "active 2 h ago")).toBe("Mathematics, Physics · active 2 h ago")
  })
  it("says which way the predicted grade moved", () => {
    expect(subjectRows(base()).map((s) => s.line)).toEqual(["predicted · up from C", "from 1 paper"])
    const down = base({ subjects: [{ ...base().subjects[0], predictedGrade: "C", previousGrade: "A" }] })
    expect(subjectRows(down)[0].line).toBe("predicted · down from A")
    const same = base({ subjects: [{ ...base().subjects[0], previousGrade: "B" }] })
    expect(subjectRows(same)[0].line).toBe("predicted · steady")
  })
})

describe("trendFor", () => {
  it("keeps one subject's points with the grade line", () => {
    const t = trendFor(base(), "0580")
    expect(t.points.map((p) => p.pct)).toEqual([48, 63])
    expect(t.last).toBe(63)
    expect(t.gradeLine).toEqual({ pct: 60, label: "B from 60%" })
    expect(t.ariaLabel).toBe("Percentage per paper, from 48% to 63%")
  })
  it("has no line when the subject has no boundary", () => {
    expect(trendFor(base(), "0625").gradeLine).toBeNull()
  })
})

describe("riskModel", () => {
  it("lists every flag and marks acknowledged ones", () => {
    expect(riskModel(base())?.flags).toEqual([
      { reason: "declining", summary: "Score dropped 8% over the last 2 papers.", acknowledged: false },
      { reason: "inactive", summary: "No practice for 4 days.", acknowledged: true },
    ])
  })
  it("is null when not at risk", () => {
    expect(riskModel(base({ isAtRisk: false, atRiskFlags: [] }))).toBeNull()
  })
})

describe("weakTopics", () => {
  it("orders by marks lost and writes plain evidence", () => {
    expect(weakTopics(base(), 3)).toEqual([
      { topic: "Algebra", lost: "−14", evidence: "41% accuracy · 4 questions" },
      { topic: "Vectors", lost: "−4", evidence: "60% accuracy · 1 question" },
    ])
  })
})

describe("paperRows and engagement", () => {
  it("names papers by code and short session, newest first", () => {
    const rows = paperRows(base(), () => "2 days ago")
    expect(rows[0]).toMatchObject({ attemptId: "a3", title: "0580/42 · May/Jun 2025", toReview: "2 to review", marks: 50, outOf: 80, grade: "B" })
    expect(rows[1].toReview).toBeNull()
  })
  it("reports days since practice, papers and last active", () => {
    expect(engagement(base(), "2 days ago")).toEqual([
      { value: "4", label: "days since practice" },
      { value: "12", label: "papers marked" },
      { value: "2 days ago", label: "last active" },
    ])
    expect(engagement(base({ engagement: { totalPapers: 0, lastActiveAt: null, daysSinceLastSubmission: null } }), "Never")[0].value).toBe("—")
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `cd web && npx vitest run tests/unit/studentDetailViewModel.test.ts`
Expected: FAIL (module missing).

- [ ] **Step 3: Implement**

```ts
// web/src/portals/teacher/papers/studentDetailViewModel.ts
/* Decisions for the redesigned StudentDetail (L8, frames S4/T_S4/M_student/Z_student_*). */
import type { StudentDetail } from "@/lib/teacherTypes"

const LADDER = ["A*", "A", "B", "C", "D", "E", "F", "G", "U"]

export const SESSION_SHORT: Record<string, string> = {
  "May/June": "May/Jun",
  "Oct/Nov": "Oct/Nov",
  "Feb/Mar": "Feb/Mar",
  Specimen: "Specimen",
}

export type StudentDetailState = "empty" | "sparse" | "normal"
export function studentDetailState(s: StudentDetail): StudentDetailState {
  if (s.attempts.length === 0) return "empty"
  return s.attempts.length === 1 ? "sparse" : "normal"
}

const subjectName = (s: StudentDetail["subjects"][number]) => s.subjectName ?? s.subjectCode

export function headerSub(s: StudentDetail, activeSummary: string): string {
  const names = s.subjects.map(subjectName)
  return names.length ? `${names.join(", ")} · ${activeSummary}` : activeSummary
}

export interface SubjectRowModel {
  code: string
  name: string
  grade: string
  line: string
}
export function subjectRows(s: StudentDetail): SubjectRowModel[] {
  return s.subjects.map((sub) => {
    let line: string
    if (sub.paperCount <= 1 || !sub.previousGrade) line = `from ${sub.paperCount} paper${sub.paperCount === 1 ? "" : "s"}`
    else {
      const now = LADDER.indexOf(sub.predictedGrade)
      const before = LADDER.indexOf(sub.previousGrade)
      line =
        now === before || now < 0 || before < 0
          ? "predicted · steady"
          : now < before
            ? `predicted · up from ${sub.previousGrade}`
            : `predicted · down from ${sub.previousGrade}`
    }
    return { code: sub.subjectCode, name: subjectName(sub), grade: sub.predictedGrade, line }
  })
}

export interface TrendModel {
  points: { x: string; pct: number }[]
  last: number | null
  gradeLine: { pct: number; label: string } | null
  ariaLabel: string
}
export function trendFor(s: StudentDetail, subjectCode: string): TrendModel {
  const points = s.trend
    .filter((p) => (p.subjectCode ?? subjectCode) === subjectCode)
    .map((p) => ({ x: p.recordedAt, pct: Math.round(p.percentage) }))
  const sub = s.subjects.find((x) => x.subjectCode === subjectCode)
  const line =
    sub && sub.gradeLinePercent != null
      ? { pct: Math.round(sub.gradeLinePercent), label: `${sub.predictedGrade} from ${Math.round(sub.gradeLinePercent)}%` }
      : null
  const first = points[0]?.pct
  const last = points.at(-1)?.pct ?? null
  return {
    points,
    last,
    gradeLine: line,
    ariaLabel:
      points.length > 1 ? `Percentage per paper, from ${first}% to ${last}%` : points.length === 1 ? `One paper, ${last}%` : "No papers yet",
  }
}

export function riskModel(s: StudentDetail): { flags: { reason: string; summary: string; acknowledged: boolean }[] } | null {
  if (!s.isAtRisk && s.atRiskFlags.length === 0) return null
  return {
    flags: s.atRiskFlags.map((f) => ({ reason: f.reason, summary: f.summary, acknowledged: f.acknowledged != null })),
  }
}

export interface WeakTopicModel {
  topic: string
  lost: string
  evidence: string
}
export function weakTopics(s: StudentDetail, n: number): WeakTopicModel[] {
  return [...s.weaknesses]
    .sort((a, b) => b.lostMarks - a.lostMarks)
    .slice(0, n)
    .map((w) => ({
      topic: w.topic,
      lost: `−${w.lostMarks}`,
      evidence: `${Math.round(w.accuracy * 100)}% accuracy · ${w.questionIds.length} question${w.questionIds.length === 1 ? "" : "s"}`,
    }))
}

export interface PaperRowModel {
  key: string
  attemptId: string | null
  title: string
  when: string
  toReview: string | null
  marks: number
  outOf: number
  grade: string
}
export function paperRows(s: StudentDetail, recorded: (iso: string) => string): PaperRowModel[] {
  return s.attempts.map((a, i) => {
    const session = a.sessionMonth ? `${SESSION_SHORT[a.sessionMonth] ?? a.sessionMonth}${a.sessionYear ? ` ${a.sessionYear}` : ""}` : null
    return {
      key: `${a.attemptId ?? a.paperId}-${a.recordedAt}-${i}`,
      attemptId: a.attemptId ?? null,
      title: session ? `${a.paperId} · ${session}` : a.paperId,
      when: recorded(a.recordedAt),
      toReview: a.openReviews ? `${a.openReviews} to review` : null,
      marks: a.awardedMarks,
      outOf: a.maximumMarks,
      grade: a.grade,
    }
  })
}

export function engagement(s: StudentDetail, lastActive: string): { value: string; label: string }[] {
  return [
    { value: s.engagement.daysSinceLastSubmission == null ? "—" : String(s.engagement.daysSinceLastSubmission), label: "days since practice" },
    { value: String(s.engagement.totalPapers), label: "papers marked" },
    { value: lastActive, label: "last active" },
  ]
}
```

`paperId` is already `"0580/42"` (`teacher.py:_paper_id`), so titles read "0580/42 · May/Jun 2025".

- [ ] **Step 4: Run to verify pass**

Run: `cd web && npx vitest run tests/unit/studentDetailViewModel.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
FILES="web/src/portals/teacher/papers/studentDetailViewModel.ts web/tests/unit/studentDetailViewModel.test.ts"
PYTHONPATH=$(pwd) pre-commit run --files $FILES
git commit -S -m "feat(web): student detail view model for the two-column screen" -- $FILES
```

---

## Screen tasks (designer)

Every screen task is for the `designer` agent. Before any edit: invoke the `impeccable` skill, read `.claude/skills/impeccable/reference/craft-floor.md`, read the three taste memories, open `.impeccable/mocks/teacher-r1/final.html` in a browser (serve with `npx serve .impeccable/mocks -l 4599`) and keep it beside the app.

### Mock class → token/Tailwind mapping (applies to Tasks 8–14)

| Mock | App |
|---|---|
| `--p` | `text-primary` / `bg-primary` |
| `--pc` | `bg-primary-container` (text `text-on-primary-container` or `text-primary`) |
| `--s` page | shell surface (`bg-surface`) |
| `--l` | `bg-surface-container-lowest` |
| `--sl` | `bg-surface-container-low` |
| `--sc` | `bg-surface-container` |
| `--sh` | `bg-surface-container-high` |
| `--ink` | `text-on-surface` |
| `--v` | `text-on-surface-variant` |
| `--o` | `outline` / `border-outline` |
| `--ov` hairline | `border-outline-variant`, `shadow-[0_-1px_0_var(--color-outline-variant)]` for row dividers |
| `--ok` / `--okc` | `text-success-text` / `bg-success-container` |
| `--err` / `--errc` / `--onerrc` | `text-error` / `bg-error-container` / `text-on-error-container` |
| `--ga … --gU` | `bg-grade-a-star … bg-grade-u` (`GRADE_BG`) |
| `font: 800 'Bricolage Grotesque'` | `font-display font-extrabold tracking-[-0.03em]` |
| `font: 'Schibsted Grotesk'` | `font-sans` |
| `font: 'JetBrains Mono'` | `font-mono tabular-nums` |
| `.btn` | `<Button variant="primary">` |
| `.btn.t` (tonal) | `<Button variant="secondary" className="border-0 bg-primary-container text-on-primary-container hover:bg-primary-container">` |
| `.btn.o` | `<Button variant="secondary">` |
| `.btn.sm` | `size="sm"` |
| `.chip` / `.chip.low` | `<Chip tone="neutral">` / `<Chip tone="err">` |
| `.seg` | `ToggleGroup` with item classes from the motion table |
| `.hd h1` 800 32px | `PageHeading` `className="text-[32px] leading-[1.1] font-extrabold tracking-[-0.02em]"` |
| `.hd .s` | `font-mono text-[12.5px] text-on-surface-variant mt-1` |
| `.h3` 800 18px + `small` | `SectionTitle` (Task 8) |
| radii 18/20/22/24/28px | `rounded-[18px]`, `rounded-[20px]`, `rounded-[22px]`, `rounded-[24px]`, `rounded-[28px]` |

### Task 8: Papers building blocks

**Files (create all):** `web/src/portals/teacher/papers/components/GradeChip.tsx`, `GradeBar.tsx`, `SectionTitle.tsx`, `NeedsStrip.tsx`, `ExamTile.tsx`, `GhostExamTiles.tsx`, `ClassFirstRun.tsx`, `Spread.tsx`, `StudentRows.tsx`, `QuestionBars.tsx`, `LostMarks.tsx`.

**Interfaces:**
- Consumes: Task 6 view-model types; F1 `Binny`, `Walkthrough`, `HairRows`, `HairRow` from `@/components/redesign`; kit `Button`, `Chip`, `ConfirmModal`.
- Produces components with these props:
  - `GradeChip({ grade: string; size?: "md" | "lg" })`
  - `GradeBar({ segments: GradeSegment[]; marking?: { done: number; total: number } })`
  - `SectionTitle({ title: string; hint?: string; as?: "h2" | "h3" })`
  - `NeedsStrip({ items: NeedsItem[]; stacked?: boolean })`
  - `ExamTile({ model: ExamTileModel; to: string })`
  - `GhostExamTiles({ variant: "first-run" | "sparse"; onMark: () => void })`
  - `ClassFirstRun({ className: string; compact?: boolean; onMark: () => void })`
  - `Spread({ average: number | null; caption: string; columns: HistogramColumn[]; ghost?: boolean; compact?: boolean })`
  - `StudentRows({ rows: StudentRowModel[]; classId: string; onOpen: (row: StudentRowModel) => void; selectedAttemptId?: string; showUnshare?: boolean })`
  - `QuestionBars({ bars: LostMarkModel[]; onSelect: (questionId: string) => void })`
  - `LostMarks({ items: LostMarkModel[]; layout: "cards" | "rows"; selectedId?: string; onSeeAnswers: (questionId: string) => void; onAssign: () => void })`

- [ ] **Step 1:** Build each component with this JSX (complete; adjust only spacing nits during polish).

```tsx
// GradeChip.tsx
import { cn } from "@/lib/utils"
import { GRADE_BG } from "../papersViewModel"

export function GradeChip({ grade, size = "md" }: { grade: string; size?: "md" | "lg" }) {
  return (
    <span
      className={cn(
        "inline-grid place-items-center text-white font-display font-extrabold",
        size === "lg" ? "min-w-16 h-14 rounded-[14px] text-[32px]" : "min-w-[34px] h-7 px-[7px] rounded-[9px] text-[15px]",
        GRADE_BG[grade] ?? "bg-outline",
      )}
      aria-label={`Grade ${grade}`}
    >
      {grade}
    </span>
  )
}
```

```tsx
// GradeBar.tsx
import type { GradeSegment } from "../papersViewModel"

export function GradeBar({ segments, marking }: { segments: GradeSegment[]; marking?: { done: number; total: number } }) {
  if (marking) {
    return (
      <div className="flex h-3.5 rounded-[7px] overflow-hidden gap-0.5 bg-surface-container-high" aria-label={`${marking.done} of ${marking.total} marked`}>
        <i className="block h-full bg-primary" style={{ flex: marking.done }} />
        <i className="block h-full" style={{ flex: Math.max(0, marking.total - marking.done) }} />
      </div>
    )
  }
  return (
    <div
      className="flex h-3.5 rounded-[7px] overflow-hidden gap-0.5"
      role="img"
      aria-label={segments.map((s) => `${s.grade}: ${s.count}`).join(", ")}
    >
      {segments.map((s) => (
        <i key={s.grade} className={`block h-full ${s.className}`} style={{ flex: s.count }} title={`${s.grade}: ${s.count}`} />
      ))}
    </div>
  )
}
```

```tsx
// SectionTitle.tsx
export function SectionTitle({ title, hint, as: Tag = "h2" }: { title: string; hint?: string; as?: "h2" | "h3" }) {
  return (
    <Tag className="flex items-baseline gap-2.5 text-[18px] font-extrabold tracking-[-0.01em] text-on-surface">
      {title}
      {hint ? <small className="font-mono text-[12px] font-semibold text-on-surface-variant">{hint}</small> : null}
    </Tag>
  )
}
```

```tsx
// NeedsStrip.tsx
import { Link } from "react-router-dom"
import { cn } from "@/lib/utils"
import type { NeedsItem } from "../papersViewModel"

export function NeedsStrip({ items, stacked }: { items: NeedsItem[]; stacked?: boolean }) {
  if (items.length === 0) return null
  return (
    <section aria-label="Needs you" className={cn("flex gap-1 rounded-[18px] bg-error-container p-1.5", stacked ? "flex-col" : "flex-col md:flex-row")}>
      {items.map((n, i) => (
        <div
          key={n.label}
          className={cn(
            "flex flex-1 items-center gap-2.5 rounded-[13px] px-3 py-2 min-w-0",
            i > 0 && (stacked ? "shadow-[0_-1px_0_color-mix(in_oklch,var(--color-on-error-container)_12%,transparent)]" : "md:shadow-[-1px_0_0_color-mix(in_oklch,var(--color-on-error-container)_15%,transparent)]"),
          )}
        >
          <b className="font-display text-[26px] leading-none font-extrabold text-on-error-container">{n.count}</b>
          <span className="flex-1 text-[13.5px] leading-tight font-semibold text-on-error-container">{n.label}</span>
          <Link to={n.to} className="inline-flex min-h-11 items-center rounded-[14px] bg-surface-container-lowest px-3 text-body-sm font-bold text-primary">
            {n.action}
          </Link>
        </div>
      ))}
    </section>
  )
}
```

```tsx
// ExamTile.tsx
import { Link } from "react-router-dom"
import { Chip } from "@/components/ui/chip"
import type { ExamTileModel } from "../papersViewModel"
import { GradeBar } from "./GradeBar"

export function ExamTile({ model, to }: { model: ExamTileModel; to: string }) {
  return (
    <Link
      to={to}
      className="grid gap-3 rounded-[22px] bg-surface-container-lowest p-[18px] shadow-[inset_0_0_0_1px_var(--color-outline-variant)] motion-safe:transition-[background,transform] motion-safe:duration-150 ease-out-soft [@media(hover:hover)]:hover:-translate-y-0.5"
    >
      <div className="min-w-0">
        <div className="flex items-baseline justify-between gap-2">
          <b className="block truncate text-[17px] leading-[1.2] font-extrabold tracking-[-0.01em]">{model.title}</b>
          {model.chip ? <Chip tone="err" className="flex-none">{model.chip.label}</Chip> : null}
        </div>
        <div className="mt-[3px] font-mono text-[12px] font-semibold text-on-surface-variant">{model.codeLine}</div>
      </div>
      <div className="flex items-baseline gap-2.5">
        <span className="font-display text-[44px] leading-none font-extrabold tracking-[-0.02em] text-primary">
          {model.big}
          <span className="text-[22px] text-on-surface-variant">{model.bigUnit}</span>
        </span>
        <span className="font-mono text-[12.5px] font-semibold text-on-surface-variant">{model.sub}</span>
      </div>
      <GradeBar segments={model.segments} />
    </Link>
  )
}
```

```tsx
// GhostExamTiles.tsx
import { Button } from "@/components/ui/button"

export function GhostExamTiles({ variant, onMark }: { variant: "first-run" | "sparse"; onMark: () => void }) {
  if (variant === "first-run") {
    return (
      <div className="grid max-w-[820px] gap-2.5 opacity-75" aria-hidden="true">
        <span className="text-[13px] font-semibold text-on-surface-variant">Your exams will appear here</span>
        <div className="grid grid-cols-1 gap-3.5 md:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <div key={i} className="grid min-h-[120px] content-start gap-1.5 rounded-[22px] p-[18px] outline-2 outline-dashed outline-outline -outline-offset-2">
              <i className="block h-3.5 w-3/5 rounded-md bg-surface-container-high" />
              <i className="mt-1.5 block h-[34px] w-[35%] rounded-md bg-surface-container-high" />
              <i className="mt-1.5 block h-3 w-full rounded-md bg-surface-container-high" />
            </div>
          ))}
        </div>
      </div>
    )
  }
  return (
    <>
      <div className="grid content-start gap-3 rounded-[22px] p-[18px] outline-2 outline-dashed outline-outline -outline-offset-2">
        <b className="text-[17px] font-extrabold">Your next paper</b>
        <p className="text-[14px] text-on-surface-variant">Mark a second paper and you’ll see who is improving and who is slipping.</p>
        <Button size="sm" variant="secondary" className="justify-self-start border-0 bg-primary-container text-on-primary-container" onClick={onMark}>
          Mark papers
        </Button>
      </div>
      <div className="grid content-start gap-3 rounded-[22px] p-[18px] opacity-70 outline-2 outline-dashed outline-outline -outline-offset-2">
        <b className="text-[17px] font-extrabold">Trends</b>
        <p className="text-[14px] text-on-surface-variant">After 3 papers, the class gets a trend line and its weakest topics.</p>
      </div>
    </>
  )
}
```

```tsx
// ClassFirstRun.tsx
import { FileArrowUp, ScanSmiley, CheckSquare } from "@phosphor-icons/react"
import { Binny, Walkthrough } from "@/components/redesign"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

export function ClassFirstRun({ className, compact, onMark }: { className: string; compact?: boolean; onMark: () => void }) {
  const steps = compact
    ? [
        { icon: FileArrowUp, title: "Upload the class set", body: "One PDF, or one per student." },
        { icon: ScanSmiley, title: "Lemely reads names and marks", body: "About 2 minutes a paper." },
        { icon: CheckSquare, title: "You check what needs you", body: "Usually a handful of answers." },
      ]
    : [
        { icon: FileArrowUp, title: "Upload the class set", body: "One PDF of every paper, or one per student." },
        { icon: ScanSmiley, title: "Lemely reads names and marks", body: "About 2 minutes a paper. Close the tab if you like." },
        { icon: CheckSquare, title: "You check what needs you", body: "Only the answers Lemely is unsure of. Usually a handful." },
      ]
  return (
    <section
      aria-labelledby="class-first-run"
      className={cn(
        "grid max-w-[820px] rounded-[28px] bg-surface-container-lowest shadow-[inset_0_0_0_1px_var(--color-outline-variant)]",
        compact ? "gap-4 p-5" : "gap-[22px] p-7",
      )}
    >
      <div className="flex items-center gap-4">
        <Binny mood="open" size={compact ? 48 : 56} motion="none" aria-hidden />
        <div>
          <h2 id="class-first-run" className="font-display text-[28px] leading-[1.15] font-extrabold tracking-[-0.03em] text-primary">
            Mark {className}’s first paper
          </h2>
          {compact ? null : (
            <p className="mt-1 max-w-[46ch] text-on-surface-variant">Drop a class set and Lemely does the rest. Here’s how it goes.</p>
          )}
        </div>
      </div>
      <Walkthrough steps={steps} />
      <div className={cn("flex gap-2.5", compact ? "flex-col" : "items-center")}>
        <Button variant="primary" onClick={onMark}>Mark papers</Button>
      </div>
    </section>
  )
}
```

The mock's "Try it with a sample class set" link has no backend; it is left out (decision D7).

```tsx
// Spread.tsx
import { cn } from "@/lib/utils"
import type { HistogramColumn } from "../papersViewModel"

export function Spread({
  average,
  caption,
  columns,
  ghost,
  compact,
}: {
  average: number | null
  caption: string
  columns: HistogramColumn[]
  ghost?: boolean
  compact?: boolean
}) {
  const ghostHeights = [30, 55, 80, 65, 45, 25, 12]
  return (
    <section
      aria-label="Spread of grades"
      className={cn("grid items-end", compact ? "grid-cols-[auto_minmax(0,1fr)] gap-4" : "grid-cols-[auto_minmax(0,1fr)] gap-9 pt-11 pb-2")}
    >
      <div className="grid gap-2.5">
        <div className={cn("font-display font-extrabold leading-none tracking-[-0.04em] text-primary", compact ? "text-[48px]" : "text-[56px]")}>
          {average ?? "–"}
          <small className="text-[24px] text-on-surface-variant">%</small>
        </div>
        <div className="font-mono text-[12.5px] font-semibold text-on-surface-variant">{caption}</div>
      </div>
      <div
        className={cn("grid gap-2.5", compact ? "h-[76px] gap-1.5" : "h-[104px]")}
        style={{ gridTemplateColumns: `repeat(${columns.length}, minmax(0,1fr))` }}
        role="img"
        aria-label={columns.map((c) => `${c.grade}: ${c.count}`).join(", ")}
      >
        {columns.map((c, i) => (
          <div key={c.grade} className="grid h-full grid-rows-[minmax(0,1fr)_auto] items-end">
            <div
              className={cn(
                "w-full self-end motion-safe:transition-[height] motion-safe:duration-300 ease-out-soft",
                compact ? "rounded-t-[6px] rounded-b-[3px]" : "rounded-t-[8px] rounded-b-[3px]",
                ghost ? "outline-2 outline-dashed outline-outline -outline-offset-2" : c.className,
              )}
              style={{ height: `${ghost ? ghostHeights[i] ?? 20 : c.heightPct}%` }}
            />
            <span className="justify-self-center text-center font-display text-[14px] font-extrabold text-on-surface-variant">
              {c.grade}
              {ghost || compact ? null : <small className="mt-px block font-mono text-[11.5px] font-semibold">{c.count}</small>}
            </span>
          </div>
        ))}
      </div>
    </section>
  )
}
```

```tsx
// StudentRows.tsx
import { useState } from "react"
import { CaretRight } from "@phosphor-icons/react"
import { HairRow, HairRows } from "@/components/redesign"
import { Button } from "@/components/ui/button"
import { Chip } from "@/components/ui/chip"
import { ConfirmModal } from "@/components/ui/confirm-modal"
import { useReshareClassPaper, useUnshareClassPaper } from "@/lib/hooks/useTeacherApi"
import { classPaperActionFailureMessage } from "@/lib/teacherOutcome"
import { unshareConsequence } from "@/lib/teacherPaperDeletion"
import { cn } from "@/lib/utils"
import type { StudentRowModel } from "../papersViewModel"
import { GradeChip } from "./GradeChip"

function Reshare({ classId, row }: { classId: string; row: StudentRowModel }) {
  const reshare = useReshareClassPaper()
  const [error, setError] = useState<string | null>(null)
  return (
    <div className="flex flex-col items-end gap-1">
      <Button
        size="sm"
        variant="secondary"
        className="border-0 bg-primary-container text-on-primary-container"
        loading={reshare.isPending}
        onClick={() => {
          setError(null)
          reshare.mutate({ classId, attemptId: row.attemptId }, { onError: (e) => setError(classPaperActionFailureMessage(e)) })
        }}
      >
        Reshare
      </Button>
      {error ? <p role="alert" className="text-body-sm text-error">{error}</p> : null}
    </div>
  )
}

function Unshare({ classId, row }: { classId: string; row: StudentRowModel }) {
  const unshare = useUnshareClassPaper()
  const [open, setOpen] = useState(false)
  const [error, setError] = useState<string | null>(null)
  return (
    <>
      <Button size="sm" variant="ghost" onClick={() => { setError(null); setOpen(true) }}>
        Unshare
      </Button>
      <ConfirmModal
        destructive={false}
        open={open}
        title="Unshare this paper from the class?"
        consequence={unshareConsequence(`${row.name}’s paper`)}
        confirmLabel="Unshare"
        pendingLabel="Unsharing…"
        pending={unshare.isPending}
        error={error}
        onConfirm={() =>
          unshare.mutate(
            { classId, attemptId: row.attemptId },
            { onSuccess: () => setOpen(false), onError: (e) => setError(classPaperActionFailureMessage(e)) },
          )
        }
        onCancel={() => { setOpen(false); setError(null) }}
      />
    </>
  )
}

export function StudentRows({
  rows,
  classId,
  onOpen,
  selectedAttemptId,
  showUnshare,
}: {
  rows: StudentRowModel[]
  classId: string
  onOpen: (row: StudentRowModel) => void
  selectedAttemptId?: string
  showUnshare?: boolean
}) {
  return (
    <HairRows aria-label="Students">
      {rows.map((row) => (
        <HairRow
          key={row.attemptId}
          selected={row.attemptId === selectedAttemptId}
          onClick={row.unshared ? undefined : () => onOpen(row)}
          leading={
            <span className={cn("grid size-7 place-items-center rounded-full bg-primary-container text-[11px] font-bold text-primary", row.unshared && "opacity-50")}>
              {row.initials}
            </span>
          }
          title={
            <span className={cn("flex items-center gap-1.5", row.unshared && "opacity-50")}>
              <span className="truncate">{row.name}</span>
              {row.unshared ? <Chip tone="neutral">Unshared</Chip> : null}
            </span>
          }
          trailing={
            <span className="flex items-center gap-3.5">
              <span className={cn("font-mono text-[15px] font-bold tabular-nums", row.unshared && "opacity-50")}>
                {row.marks}
                <small className="font-semibold text-on-surface-variant">/{row.outOf}</small>
              </span>
              <GradeChip grade={row.grade} />
              <span className={cn("w-12 font-mono text-[12.5px] font-semibold max-md:hidden", row.delta?.tone === "up" ? "text-success-text" : "text-error")}>
                {row.delta?.text ?? ""}
              </span>
              {row.unshared ? (
                <Reshare classId={classId} row={row} />
              ) : showUnshare ? (
                <Unshare classId={classId} row={row} />
              ) : (
                <CaretRight aria-hidden className="text-on-surface-variant" />
              )}
            </span>
          }
        />
      ))}
    </HairRows>
  )
}
```

`unshareConsequence` currently takes `classPaperLabel(row)` of a `ClassPaperRow`; check its signature in `web/src/lib/teacherPaperDeletion.ts`. It takes a string label, so passing the student-named label is valid. If it needs the paper code, pass `` `${row.name}’s ${examCode}` `` by adding an `examLabel: string` prop to `StudentRows` and threading the exam's `code · session` through.

```tsx
// QuestionBars.tsx
import { cn } from "@/lib/utils"
import type { LostMarkModel } from "../papersViewModel"

export function QuestionBars({ bars, onSelect }: { bars: LostMarkModel[]; onSelect: (questionId: string) => void }) {
  return (
    <ul aria-label="By question" className="grid">
      {bars.map((q) => (
        <li key={q.questionId}>
          <button
            type="button"
            onClick={() => onSelect(q.questionId)}
            className="grid w-full min-h-11 grid-cols-[44px_minmax(0,1fr)_46px] items-center gap-3 px-1 py-2 text-start"
          >
            <span className={cn("font-mono text-[14px] font-bold", q.weak && "text-error")}>{q.label}</span>
            <span>
              <span className="block truncate text-[12.5px] font-semibold text-on-surface-variant">{q.topic}</span>
              <span className="mt-1 block h-2.5 overflow-hidden rounded-[5px] bg-surface-container-high">
                <b className={cn("block h-full rounded-[5px]", q.weak ? "bg-error" : "bg-primary")} style={{ width: `${q.averagePercent}%` }} />
              </span>
            </span>
            <span className="text-end font-mono text-[13px] font-bold tabular-nums">{q.averagePercent}%</span>
          </button>
        </li>
      ))}
    </ul>
  )
}
```

```tsx
// LostMarks.tsx
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import type { LostMarkModel } from "../papersViewModel"

const tonal = "border-0 bg-primary-container text-on-primary-container"

export function LostMarks({
  items,
  layout,
  selectedId,
  onSeeAnswers,
  onAssign,
}: {
  items: LostMarkModel[]
  layout: "cards" | "rows"
  selectedId?: string
  onSeeAnswers: (questionId: string) => void
  onAssign: () => void
}) {
  if (layout === "rows") {
    return (
      <ul className="grid">
        {items.map((q) => (
          <li key={q.questionId}>
            <button
              type="button"
              aria-pressed={q.questionId === selectedId}
              onClick={() => onSeeAnswers(q.questionId)}
              className={cn(
                "grid w-full min-h-11 grid-cols-[44px_minmax(0,1fr)_56px] items-center gap-3 rounded-[14px] px-3 py-2.5 text-start",
                q.questionId === selectedId && "bg-surface-container-lowest shadow-[inset_0_0_0_2px_var(--color-primary)]",
              )}
            >
              <span className="font-mono text-[15px] font-bold text-primary">{q.label}</span>
              <span className="min-w-0">
                <span className="block truncate text-[15px] font-bold">{q.topic}</span>
                <span className="mt-1.5 block h-2 overflow-hidden rounded bg-surface-container-high">
                  <b className={cn("block h-full rounded", q.weak ? "bg-error" : "bg-primary")} style={{ width: `${q.averagePercent}%` }} />
                </span>
              </span>
              <span className={cn("text-end font-display text-[24px] leading-none font-extrabold", q.weak ? "text-error" : "text-primary")}>
                {q.averagePercent}%
              </span>
            </button>
          </li>
        ))}
      </ul>
    )
  }
  return (
    <div className="grid grid-cols-1 gap-3.5 md:grid-cols-3">
      {items.map((q) => (
        <div key={q.questionId} className="grid gap-2.5 rounded-[20px] bg-surface-container-lowest p-4 shadow-[inset_0_0_0_1px_var(--color-outline-variant)]">
          <div className="flex items-baseline gap-2">
            <span className="font-mono text-[15px] font-bold text-primary">{q.label}</span>
            <span className="flex-1 text-[15px] font-bold">{q.topic}</span>
            <span className={cn("font-display text-[24px] leading-none font-extrabold", q.weak ? "text-error" : "text-primary")}>{q.averagePercent}%</span>
          </div>
          <div className="h-2 overflow-hidden rounded bg-surface-container-high">
            <b className={cn("block h-full rounded", q.weak ? "bg-error" : "bg-primary")} style={{ width: `${q.averagePercent}%` }} />
          </div>
          <div className="flex gap-1.5">
            <Button size="sm" variant="secondary" className={cn("flex-1", tonal)} onClick={() => onSeeAnswers(q.questionId)}>See answers</Button>
            <Button size="sm" variant="secondary" className="flex-1" onClick={onAssign}>Assign practice</Button>
          </div>
        </div>
      ))}
    </div>
  )
}
```

- [ ] **Step 2: Type-check and lint.** Run: `cd web && npx tsc --noEmit -p . && npx eslint src/portals/teacher/papers/components`. Expected: clean.
- [ ] **Step 3: Copy check.** Run: `cd web && npm run check:copy && npm run check:native`. Expected: pass (no eyebrows, no banned words).
- [ ] **Step 4: Commit**

```bash
FILES=$(git ls-files -o -m web/src/portals/teacher/papers/components)
PYTHONPATH=$(pwd) pre-commit run --files $FILES
git commit -S -m "feat(web): teacher papers building blocks" -- $FILES
```

---

### Task 9: Papers home and class exam tiles

**Files:**
- Create: `web/src/portals/teacher/papers/PapersHome.tsx`, `web/src/portals/teacher/papers/ClassExams.tsx`
- Create: `web/src/portals/teacher/papers/MarkPapersConsole.tsx` (move `Grading.tsx` body verbatim; rename the exported function to `MarkPapersConsole`; change the `PageHeading` text to `Mark papers` and the `srHeading` to `"Mark papers"`; no other change)
- Modify: `web/src/portals/teacher/index.tsx` (lazy imports and routes below; bottom tab)
- Modify: `web/src/portals/teacher/data.ts` (the "Grading" nav item becomes "Papers" → `/teacher/papers`, decision D2)
- Modify: `web/tests/unit/navShells.test.ts:99`, `web/tests/unit/navigation.test.ts:277-279,384,456` (labels and paths)

**Interfaces:**
- Consumes: `useClassExams`, `useTeacherClasses`, `useClassDetailContext` (from `../screens/ClassDetail`), Task 6, Task 8.
- Produces: routes `/teacher/papers`, `/teacher/classes/:classId/papers` (now `ClassExams`), `/teacher/grading` (now `MarkPapersConsole`).

- [ ] **Step 1: Build `ClassExams`** (E3, Z_class, Z_class_sparse, M_empty, loading, error)

```tsx
// web/src/portals/teacher/papers/ClassExams.tsx
import { useNavigate } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { QueryState } from "@/components/ui/query-state"
import { SkeletonBlock } from "@/components/ui/skeleton"
import { useClassExams } from "@/lib/hooks/useClassExams"
import { teacherLoadFailureMessage } from "@/lib/teacherOutcome"
import { useClassDetailContext } from "../screens/ClassDetail"
import { classExamsState, examTileModel, needsItems } from "./papersViewModel"
import { ClassFirstRun } from "./components/ClassFirstRun"
import { ExamTile } from "./components/ExamTile"
import { GhostExamTiles } from "./components/GhostExamTiles"
import { NeedsStrip } from "./components/NeedsStrip"

function TilesSkeleton() {
  return (
    <div className="grid grid-cols-1 gap-3.5 md:grid-cols-2 xl:grid-cols-3" aria-busy="true">
      {[0, 1, 2].map((i) => <SkeletonBlock key={i} className="h-[150px] rounded-[22px]" />)}
    </div>
  )
}

export function ClassExams() {
  const { classId } = useClassDetailContext()
  const navigate = useNavigate()
  const query = useClassExams(classId)
  const mark = () => navigate("/teacher/grading")

  return (
    <QueryState
      query={query}
      srHeading="Class papers"
      skeleton={<TilesSkeleton />}
      error={{ heading: "Couldn't load this class's papers", body: teacherLoadFailureMessage }}
    >
      {(data) => {
        const state = classExamsState(data)
        if (state === "first-run") {
          return (
            <div className="grid gap-[18px]">
              <div className="md:hidden"><ClassFirstRun className={data.className} compact onMark={mark} /></div>
              <div className="max-md:hidden grid gap-[18px]">
                <ClassFirstRun className={data.className} onMark={mark} />
                <GhostExamTiles variant="first-run" onMark={mark} />
              </div>
            </div>
          )
        }
        const review = data.exams.reduce((n, e) => n + e.answersToReview, 0)
        return (
          <div className="grid gap-[18px]">
            <div className="flex items-center justify-between gap-4">
              <p className="font-mono text-[12.5px] font-semibold text-on-surface-variant">
                {data.studentCount} students · {data.exams.length} exam{data.exams.length === 1 ? "" : "s"} marked
              </p>
              <Button variant="primary" onClick={mark}>Mark papers</Button>
            </div>
            <NeedsStrip items={needsItems({ answersToReview: review }, data.classId)} />
            <div className="grid grid-cols-1 gap-3.5 md:grid-cols-2 xl:grid-cols-3">
              {data.exams.map((e) => (
                <ExamTile key={e.examKey} model={examTileModel(e)} to={`/teacher/classes/${classId}/papers/${e.examKey}`} />
              ))}
              {state === "sparse" ? <GhostExamTiles variant="sparse" onMark={mark} /> : null}
            </div>
          </div>
        )
      }}
    </QueryState>
  )
}
```

The class header ("10B") is drawn by `ClassDetailLayout`; the E3 sub-line ("28 students · 6 exams marked") sits above the tiles here.

- [ ] **Step 2: Build `PapersHome`** (class tiles; no mock frame, uses the E3 tile language — decision D2)

```tsx
// web/src/portals/teacher/papers/PapersHome.tsx
import { Link, Navigate } from "react-router-dom"
import { PageHeading } from "@/components/ui/page-heading"
import { QueryState } from "@/components/ui/query-state"
import { SkeletonBlock } from "@/components/ui/skeleton"
import { useTeacherClasses } from "@/lib/hooks/useTeacherApi"
import { teacherLoadFailureMessage } from "@/lib/teacherOutcome"

export function PapersHome() {
  const query = useTeacherClasses()
  return (
    <div className="grid gap-[18px]">
      <PageHeading repeatsTitle className="text-[32px] leading-[1.1] font-extrabold tracking-[-0.02em]">Papers</PageHeading>
      <QueryState
        query={query}
        srHeading="Papers"
        skeleton={<div className="grid grid-cols-1 gap-3.5 md:grid-cols-2 xl:grid-cols-3">{[0, 1, 2].map((i) => <SkeletonBlock key={i} className="h-[120px] rounded-[22px]" />)}</div>}
        error={{ heading: "Couldn't load your classes", body: teacherLoadFailureMessage }}
      >
        {({ classes }) => {
          if (classes.length === 0) return <Navigate to="/teacher/first-class" replace />
          if (classes.length === 1) return <Navigate to={`/teacher/classes/${classes[0].id}/papers`} replace />
          return (
            <div className="grid grid-cols-1 gap-3.5 md:grid-cols-2 xl:grid-cols-3">
              {classes.map((c) => (
                <Link
                  key={c.id}
                  to={`/teacher/classes/${c.id}/papers`}
                  className="grid gap-2 rounded-[22px] bg-surface-container-lowest p-[18px] shadow-[inset_0_0_0_1px_var(--color-outline-variant)] motion-safe:transition-transform motion-safe:duration-150 [@media(hover:hover)]:hover:-translate-y-0.5"
                >
                  <b className="truncate text-[19px] font-extrabold tracking-[-0.01em]">{c.name}</b>
                  <span className="font-mono text-[12px] font-semibold text-on-surface-variant">
                    {c.subjectName ?? c.subjectCode ?? "No subject"} · {c.studentCount} students
                  </span>
                  <span className="font-display text-[44px] leading-none font-extrabold text-primary">
                    {c.averageMark == null ? "–" : Math.round(c.averageMark)}
                    <span className="text-[22px] text-on-surface-variant">{c.averageMark == null ? "" : "%"}</span>
                  </span>
                </Link>
              ))}
            </div>
          )
        }}
      </QueryState>
    </div>
  )
}
```

Before writing, open `web/src/lib/teacherTypes.ts` `ClassSummary` and use its exact field names for id, name, subject name/code, student count and average (the names above are the expected ones; change any that differ).

- [ ] **Step 3: Wire routes** in `web/src/portals/teacher/index.tsx`:

```tsx
const PapersHome = lazy(() => import("./papers/PapersHome").then((m) => ({ default: m.PapersHome })))
const ClassExams = lazy(() => import("./papers/ClassExams").then((m) => ({ default: m.ClassExams })))
const MarkPapersConsole = lazy(() =>
  import("./papers/MarkPapersConsole").then((m) => ({ default: m.MarkPapersConsole })),
)
```

Replace `const Grading = …` and `const ClassPapers = …`. Routes:

```tsx
    {
      path: "papers",
      element: <PapersHome />,
      handle: { title: "Papers", skeleton: "card-grid" },
    },
    {
      path: "grading",
      element: <MarkPapersConsole />,
      handle: { title: "Mark papers", skeleton: "page-header" },
    },
```

and inside `classes/:classId` children replace the `papers` element with `<ClassExams />` (`handle: { title: "Class papers", skeleton: "card-grid" }`). Bottom tab: `{ id: "papers", label: "Papers", to: "/teacher/papers", icon: FileText }` replacing the Grading entry. Update the doc comment above `TEACHER_BOTTOM_TABS` to name "Papers". The top-bar "Upload papers" link stays on `/teacher/grading`.

Update the nav tests: `navShells.test.ts:99` regex to `/"Overview"[\s\S]*"Papers"[\s\S]*"Review"[\s\S]*"Classes"/`; `navigation.test.ts:277-279` to assert Review directly after `/teacher/papers`; `:384` and `:456` replace `/teacher/grading` with `/teacher/papers` where they describe the nav item (leave any assertion that the grading route is mounted).

- [ ] **Step 4: Run**

`cd web && npx vitest run tests/unit/navShells.test.ts tests/unit/navigation.test.ts tests/unit/teacherPaperDeletionWiring.test.ts tests/unit/activeScanGuard.test.ts && npx tsc --noEmit -p .`
Expected: PASS. If `teacherPaperDeletionWiring.test.ts` or `activeScanGuard.test.ts` read `screens/Grading.tsx` source, point them at `papers/MarkPapersConsole.tsx`.

- [ ] **Step 5: Manual check** at 390, 834 and 1280 against `E3`, `Z_class`, `Z_class_sparse`, `M_empty` (`npm run dev`, seeded teacher).

- [ ] **Step 6: Commit**

```bash
FILES="web/src/portals/teacher/papers/PapersHome.tsx web/src/portals/teacher/papers/ClassExams.tsx web/src/portals/teacher/papers/MarkPapersConsole.tsx web/src/portals/teacher/index.tsx web/src/portals/teacher/data.ts web/tests/unit/navShells.test.ts web/tests/unit/navigation.test.ts"
PYTHONPATH=$(pwd) pre-commit run --files $FILES
git commit -S -m "feat(web): papers home, class exam tiles and the moved marking console" -- $FILES
```

(`Grading.tsx` and `ClassPapers.tsx` are deleted in Task 17 after the keep-list check; until then they are unreferenced.)

---

### Task 10: Exam screen and Summary

**Files:**
- Create: `web/src/portals/teacher/papers/components/ExamHeader.tsx`, `web/src/portals/teacher/papers/ExamScreen.tsx`, `web/src/portals/teacher/papers/ExamSummary.tsx`
- Modify: `web/src/portals/teacher/index.tsx` (route)

**Interfaces:**
- Consumes: `useClassExam`, `downloadExamMarks`, `marksFileName`, Task 6/8.
- Produces: `ExamScreen` route `classes/:classId/papers/:examKey`; URL params `view` (`summary` default | `heatmap`), `q`, `a`. `ExamSummary({ exam, onSelectQuestion, onOpenStudent, selectedQuestion })`.

- [ ] **Step 1: `ExamHeader`**

```tsx
// web/src/portals/teacher/papers/components/ExamHeader.tsx
import { useState } from "react"
import { Link } from "react-router-dom"
import { CaretLeft, DownloadSimple } from "@phosphor-icons/react"
import { Button } from "@/components/ui/button"
import { PageHeading } from "@/components/ui/page-heading"
import { useToast } from "@/components/ui/toast"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { downloadExamMarks, marksFileName } from "@/lib/classExamApi"
import type { ClassExam } from "@/lib/classExamTypes"

const SEG_ITEM =
  "rounded-[9px] px-3 py-1.5 text-[13px] font-bold text-on-surface-variant min-h-11 md:min-h-0 data-[state=on]:bg-surface-container-lowest data-[state=on]:text-primary data-[state=on]:shadow-[0_1px_2px_#0001] motion-safe:transition-colors disabled:opacity-45 disabled:cursor-not-allowed"

export function ExamHeader({
  exam,
  view,
  onView,
}: {
  exam: ClassExam
  view: "summary" | "heatmap"
  onView: (v: "summary" | "heatmap") => void
}) {
  const toast = useToast()
  const [busy, setBusy] = useState(false)
  const download = async () => {
    setBusy(true)
    try {
      await downloadExamMarks(exam.classId, exam.examKey, marksFileName(exam.className, exam.code, exam.session))
    } catch {
      toast.show({ tone: "error", message: "Couldn't download the marks. Try again." })
    } finally {
      setBusy(false)
    }
  }
  const sub = [exam.code, exam.session, `${exam.paperCount} papers`, exam.unsharedCount ? `${exam.unsharedCount} unshared` : null]
    .filter(Boolean)
    .join(" · ")
  return (
    <header className="flex flex-wrap items-end gap-4 pb-2.5">
      <div className="min-w-0 flex-1">
        <Link to={`/teacher/classes/${exam.classId}/papers`} className="mb-1.5 inline-flex min-h-11 items-center gap-1.5 text-[13px] font-semibold text-primary max-md:hidden">
          <CaretLeft aria-hidden /> {exam.className}
        </Link>
        <PageHeading repeatsTitle={false} className="text-[21px] leading-[1.2] font-extrabold md:text-[32px] md:leading-[1.1] md:tracking-[-0.02em]">
          {exam.title}
        </PageHeading>
        <div className="mt-1 font-mono text-[12px] font-semibold text-on-surface-variant md:text-[12.5px]">{sub}</div>
      </div>
      <ToggleGroup
        type="single"
        value={view}
        onValueChange={(v) => v && onView(v as "summary" | "heatmap")}
        aria-label="Exam view"
        className="inline-flex rounded-xl bg-surface-container p-[3px] max-md:hidden"
      >
        <ToggleGroupItem value="summary" className={SEG_ITEM}>Summary</ToggleGroupItem>
        <ToggleGroupItem
          value="heatmap"
          className={SEG_ITEM}
          disabled={!exam.heatmapReady}
          title={exam.heatmapReady ? undefined : `Shows once ${exam.heatmapMinPapers} papers are marked`}
        >
          Heatmap
        </ToggleGroupItem>
      </ToggleGroup>
      <Button
        variant="secondary"
        className="border-0 bg-primary-container text-on-primary-container max-md:hidden"
        loading={busy}
        onClick={() => void download()}
      >
        Download marks
      </Button>
      <button
        type="button"
        aria-label="Download marks"
        onClick={() => void download()}
        className="grid size-11 place-items-center rounded-[14px] bg-primary-container text-primary md:hidden"
      >
        <DownloadSimple aria-hidden />
      </button>
    </header>
  )
}
```

Check `web/src/components/ui/toast.tsx` for the real hook/API name (`useToast().show({...})` above); use whatever it exports.

- [ ] **Step 2: `ExamSummary`** (X5, T_X5, M_exam, Z_exam_sparse, X6 list side)

```tsx
// web/src/portals/teacher/papers/ExamSummary.tsx
import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import type { ClassExam } from "@/lib/classExamTypes"
import {
  examScreenState,
  histogramColumns,
  lostMarks,
  lowestStudents,
  needsItems,
  questionBars,
  sparseLine,
  studentRows,
} from "./papersViewModel"
import { LostMarks } from "./components/LostMarks"
import { NeedsStrip } from "./components/NeedsStrip"
import { QuestionBars } from "./components/QuestionBars"
import { SectionTitle } from "./components/SectionTitle"
import { Spread } from "./components/Spread"
import { StudentRows } from "./components/StudentRows"

export function ExamSummary({
  exam,
  selectedQuestion,
  onSelectQuestion,
}: {
  exam: ClassExam
  selectedQuestion: string | null
  onSelectQuestion: (questionId: string) => void
}) {
  const navigate = useNavigate()
  const [showAll, setShowAll] = useState(false)
  const [phoneTab, setPhoneTab] = useState<"questions" | "students">("questions")
  const sparse = examScreenState(exam) === "sparse"
  const cols = histogramColumns(exam.gradeCounts)
  const openStudent = (studentId: string) => navigate(`/teacher/students/${studentId}`)
  const assign = () => navigate("/teacher/quizzes?new=1")
  const needs = needsItems(exam, exam.classId)
  const all = studentRows(exam)

  if (sparse) {
    const line = sparseLine(exam)
    return (
      <div className="grid max-w-[1000px] gap-6">
        <div className="flex flex-col gap-4 rounded-[20px] bg-primary-container px-[18px] py-4 md:flex-row md:items-center">
          <div className="flex-1">
            <b className="text-[16px] font-bold text-primary">{line.title}</b>
            <p className="mt-0.5 text-[14px] text-primary opacity-85">{line.body}</p>
          </div>
          <Button variant="primary" onClick={() => navigate("/teacher/grading")}>Add papers</Button>
        </div>
        <Spread average={exam.average} caption={`average so far · ${exam.paperCount} paper${exam.paperCount === 1 ? "" : "s"}`} columns={cols} ghost />
        <section className="grid gap-1">
          <SectionTitle title="Marked so far" />
          <StudentRows rows={all} classId={exam.classId} onOpen={(r) => openStudent(r.studentId)} showUnshare />
        </section>
      </div>
    )
  }

  return (
    <div className="grid max-w-[1000px] gap-6">
      <NeedsStrip items={needs} stacked={false} />
      <div className="max-md:hidden">
        <Spread average={exam.average} caption="class average" columns={cols} />
      </div>
      <div className="md:hidden">
        <Spread average={exam.average} caption="average" columns={cols} compact />
      </div>

      <section className="grid gap-2.5 max-md:hidden">
        <SectionTitle title="Where the class lost marks" />
        <div className="xl:hidden">
          <LostMarks items={lostMarks(exam)} layout="rows" selectedId={selectedQuestion ?? undefined} onSeeAnswers={onSelectQuestion} onAssign={assign} />
        </div>
        <div className="max-xl:hidden">
          <LostMarks items={lostMarks(exam)} layout="cards" onSeeAnswers={onSelectQuestion} onAssign={assign} />
        </div>
      </section>

      <section className="grid gap-1 max-md:hidden">
        <SectionTitle title="Students" hint={showAll ? `all ${exam.paperCount}` : "lowest first"} />
        <StudentRows
          rows={showAll ? all : lowestStudents(exam, 3)}
          classId={exam.classId}
          onOpen={(r) => openStudent(r.studentId)}
          showUnshare={showAll}
        />
        <Button variant="text" size="sm" className="justify-self-start" onClick={() => setShowAll((v) => !v)}>
          {showAll ? "Show fewer" : `Show all ${exam.paperCount + exam.unsharedCount}`}
        </Button>
      </section>

      <section className="grid gap-3 md:hidden">
        <ToggleGroup
          type="single"
          value={phoneTab}
          onValueChange={(v) => v && setPhoneTab(v as "questions" | "students")}
          aria-label="Show"
          className="inline-flex justify-self-start rounded-xl bg-surface-container p-[3px]"
        >
          <ToggleGroupItem value="questions" className="min-h-11 rounded-[9px] px-3 text-[13px] font-bold text-on-surface-variant data-[state=on]:bg-surface-container-lowest data-[state=on]:text-primary">Questions</ToggleGroupItem>
          <ToggleGroupItem value="students" className="min-h-11 rounded-[9px] px-3 text-[13px] font-bold text-on-surface-variant data-[state=on]:bg-surface-container-lowest data-[state=on]:text-primary">Students</ToggleGroupItem>
        </ToggleGroup>
        {phoneTab === "questions" ? (
          <QuestionBars bars={questionBars(exam)} onSelect={onSelectQuestion} />
        ) : (
          <StudentRows rows={all} classId={exam.classId} onOpen={(r) => openStudent(r.studentId)} showUnshare />
        )}
      </section>
    </div>
  )
}
```

- [ ] **Step 3: `ExamScreen`** (shell, loading, error, view routing, X6 split)

```tsx
// web/src/portals/teacher/papers/ExamScreen.tsx
import { useParams, useSearchParams } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { QueryState } from "@/components/ui/query-state"
import { SkeletonBlock } from "@/components/ui/skeleton"
import { useClassExam } from "@/lib/hooks/useClassExams"
import { ExamHeader } from "./components/ExamHeader"
import { ExamHeatmap } from "./ExamHeatmap"
import { ExamSummary } from "./ExamSummary"
import { QuestionAnswers } from "./QuestionAnswers"

function ExamSkeleton() {
  return (
    <div className="grid max-w-[1000px] gap-[22px]" aria-busy="true">
      <SkeletonBlock className="h-[34px] w-[360px] max-w-full" />
      <SkeletonBlock className="h-[62px] rounded-[18px]" />
      <SkeletonBlock className="h-[120px] rounded-[20px]" />
      <div className="grid grid-cols-1 gap-3.5 md:grid-cols-3">
        {[0, 1, 2].map((i) => <SkeletonBlock key={i} className="h-[120px] rounded-[20px]" />)}
      </div>
    </div>
  )
}

export function ExamScreen() {
  const { classId, examKey } = useParams<{ classId: string; examKey: string }>()
  const [params, setParams] = useSearchParams()
  const query = useClassExam(classId, examKey)
  const view = params.get("view") === "heatmap" ? "heatmap" : "summary"
  const q = params.get("q")
  const a = params.get("a")
  const set = (patch: Record<string, string | null>) => {
    const next = new URLSearchParams(params)
    for (const [k, v] of Object.entries(patch)) (v === null ? next.delete(k) : next.set(k, v))
    setParams(next)
  }

  return (
    <QueryState
      query={query}
      srHeading="Exam"
      skeleton={<ExamSkeleton />}
      error={{
        heading: "Couldn’t load this exam.",
        body: () => "Check your connection and try again. Your marks are safe.",
      }}
    >
      {(exam) => {
        const heatmap = view === "heatmap" && exam.heatmapReady
        return (
          <div className="grid gap-4">
            <ExamHeader exam={exam} view={heatmap ? "heatmap" : "summary"} onView={(v) => set({ view: v === "summary" ? null : v, q: null, a: null })} />
            {q ? (
              <QuestionAnswers
                exam={exam}
                questionId={q}
                attemptId={a}
                onSelectAnswer={(attemptId) => set({ a: attemptId })}
                onClose={() => set({ q: null, a: null })}
              />
            ) : heatmap ? (
              <ExamHeatmap
                exam={exam}
                selected={a && q ? { attemptId: a, questionId: q } : null}
                onSelectCell={(attemptId, questionId) => set({ a: attemptId, q: questionId })}
                onSelectQuestion={(questionId) => set({ q: questionId, a: null })}
              />
            ) : (
              <ExamSummary exam={exam} selectedQuestion={q} onSelectQuestion={(questionId) => set({ q: questionId, a: null })} />
            )}
          </div>
        )
      }}
    </QueryState>
  )
}
```

Check `QueryState`'s `error.body` type in `query-state.tsx:118-150` (it takes `teacherLoadFailureMessage`, a function of the error); the arrow above matches that shape. Keep `Button` import only if used; remove otherwise.

Heatmap cell taps set both `a` and `q`, which renders `QuestionAnswers` with the answer selected — this is the F_X7 "panel follows the cell" behaviour; the heatmap stays visible on desktop because `QuestionAnswers` renders it as the left column when `from=heatmap` (see Task 11, Step 2). Pass `from: "heatmap"` by adding `view` to the set call: `onSelectCell={(attemptId, questionId) => set({ a: attemptId, q: questionId })}` keeps `view=heatmap` in the URL already.

- [ ] **Step 4: Route** in `web/src/portals/teacher/index.tsx`, as a top-level teacher child **before** `classes/:classId`:

```tsx
const ExamScreen = lazy(() => import("./papers/ExamScreen").then((m) => ({ default: m.ExamScreen })))
…
    {
      path: "classes/:classId/papers/:examKey",
      element: <ExamScreen />,
      handle: { title: "Exam", skeleton: "page-header" },
    },
```

- [ ] **Step 5:** `cd web && npx tsc --noEmit -p .` (ExamHeatmap and QuestionAnswers come in Task 11; do Tasks 10 and 11 in one designer session and commit once tsc is clean), then compare X5/T_X5/M_exam/Z_exam_sparse/L_exam/R_exam side by side.

- [ ] **Step 6: Commit** together with Task 11.

---

### Task 11: Heatmap and question answers

**Files:**
- Create: `web/src/portals/teacher/papers/components/Heatmap.tsx`, `web/src/portals/teacher/papers/components/AnswerPreview.tsx`, `web/src/portals/teacher/papers/ExamHeatmap.tsx`, `web/src/portals/teacher/papers/QuestionAnswers.tsx`

**Interfaces:**
- Consumes: `heatmapFill`, `HEATMAP_LEGEND`, `answerSort`, `useExamQuestionAnswers`.
- Produces:
  - `Heatmap({ exam: ClassExam; selected: { attemptId: string; questionId: string } | null; selectedQuestion?: string | null; onSelectCell; onSelectQuestion; maxHeight?: number })`
  - `ExamHeatmap({ exam, selected, onSelectCell, onSelectQuestion })`
  - `AnswerPreview({ answer: ExamAnswer; topic: string | null; code: string; onPrev?: () => void; onNext?: () => void })` — read-only until Task 15 swaps in L5's panel
  - `QuestionAnswers({ exam, questionId, attemptId, onSelectAnswer, onClose })`

- [ ] **Step 1: `Heatmap`** (F_X7: 52×38 cells, `border-spacing: 8px 7px`, a row break every 5, sticky names/header/totals)

```tsx
// web/src/portals/teacher/papers/components/Heatmap.tsx
import type { ClassExam } from "@/lib/classExamTypes"
import { cn } from "@/lib/utils"
import { heatmapFill } from "../heatmapScale"
import { GradeChip } from "./GradeChip"

export function Heatmap({
  exam,
  selected,
  selectedQuestion,
  onSelectCell,
  onSelectQuestion,
  maxHeight = 580,
}: {
  exam: ClassExam
  selected: { attemptId: string; questionId: string } | null
  selectedQuestion?: string | null
  onSelectCell: (attemptId: string, questionId: string) => void
  onSelectQuestion: (questionId: string) => void
  maxHeight?: number
}) {
  const rows = exam.students
  const byAttempt = new Map(exam.heatmap.map((r) => [r.attemptId, new Map(r.cells.map((c) => [c.questionId, c]))]))
  return (
    <div
      className="overflow-auto overscroll-contain rounded-2xl bg-surface-container-lowest py-1 shadow-[inset_0_0_0_1px_var(--color-outline-variant)] [scrollbar-width:thin]"
      style={{ maxHeight }}
      tabIndex={0}
      role="region"
      aria-label="Every answer, scrollable both ways"
    >
      <table className="border-separate [border-spacing:8px_7px] font-mono text-[12px] font-semibold">
        <caption className="sr-only">Marks per student per question. Colour shows marks kept; the cell title gives the exact mark.</caption>
        <thead>
          <tr>
            <th scope="col" className="sticky left-0 top-0 z-[3] min-w-[180px] bg-surface-container-lowest px-4 pt-3 pb-2 text-start text-on-surface-variant">Student</th>
            {exam.questions.map((q) => (
              <th
                key={q.questionId}
                scope="col"
                className={cn(
                  "sticky top-0 z-[2] min-w-[52px] cursor-pointer px-0 pt-3 pb-2",
                  q.averagePercent < 40 ? "rounded-[10px] bg-error-container text-on-error-container" : "bg-surface-container-lowest",
                  selectedQuestion === q.questionId && "shadow-[inset_0_0_0_2px_var(--color-primary)]",
                )}
              >
                <button type="button" onClick={() => onSelectQuestion(q.questionId)} className="grid w-full min-h-11 justify-items-center" aria-label={`Q${q.questionId}, class average ${q.averagePercent}%. Show every answer`}>
                  <span className="block text-[12.5px] font-bold">Q{q.questionId}</span>
                  <span className="mt-0.5 block text-[11px] font-medium opacity-80">{q.averagePercent}%</span>
                </button>
              </th>
            ))}
            <th scope="col" className="sticky right-0 top-0 z-[3] bg-surface-container-lowest px-2.5 text-on-surface-variant">/{exam.students[0]?.maximumMarks ?? ""}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((s, i) => {
            const cells = byAttempt.get(s.attemptId)
            const gap = (i + 1) % 5 === 0 ? "pb-2.5" : ""
            return (
              <tr key={s.attemptId} className={cn(s.unshared && "opacity-45")}>
                <th scope="row" className={cn("sticky left-0 z-[1] min-w-[180px] max-w-[200px] whitespace-nowrap bg-surface-container-lowest px-4 text-start font-sans text-[14px] font-semibold", gap)}>
                  <span className="truncate">{s.displayName}</span>
                </th>
                {exam.questions.map((q) => {
                  const c = cells?.get(q.questionId)
                  const fill = heatmapFill(c ? c.awarded : null, c?.maximum ?? q.maximumMarks)
                  const isSel = selected?.attemptId === s.attemptId && selected.questionId === q.questionId
                  const label = c ? (c.awarded === null ? "blank" : `${c.awarded}/${c.maximum}`) : "no answer"
                  return (
                    <td key={q.questionId} className={cn("p-0", gap)}>
                      <button
                        type="button"
                        disabled={!c || s.unshared}
                        onClick={() => onSelectCell(s.attemptId, q.questionId)}
                        title={`${s.displayName} Q${q.questionId}: ${label}`}
                        aria-label={`${s.displayName}, Q${q.questionId}: ${label}`}
                        className={cn(
                          "block h-[38px] w-[52px] rounded-[11px]",
                          fill.kind === "blank" && "outline-[1.5px] outline-dashed outline-outline -outline-offset-[1.5px]",
                          isSel && "shadow-[0_0_0_2px_var(--color-primary),0_0_0_4px_var(--color-surface-container-lowest)]",
                        )}
                        style={fill.background ? { background: fill.background } : undefined}
                      />
                    </td>
                  )
                })}
                <td className={cn("sticky right-0 bg-surface-container-lowest px-2.5", gap)}>
                  <span className="flex h-[38px] items-center gap-2.5 whitespace-nowrap">
                    <span className="min-w-[22px] text-end text-[13px] font-bold">{s.awardedMarks}</span>
                    <GradeChip grade={s.grade} />
                  </span>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
```

The mock's 44px tap floor: cells are 52×38 visually; the `<th>` question buttons are 44px high. Cells stay 38px tall as approved (airy grid beats a 44px row there); list this in the PR as an accessibility note — keyboard and the column view give the same access.

- [ ] **Step 2: `ExamHeatmap`** (legend + heatmap + side panel slot)

```tsx
// web/src/portals/teacher/papers/ExamHeatmap.tsx
import type { ClassExam } from "@/lib/classExamTypes"
import { HEATMAP_LEGEND } from "./heatmapScale"
import { Heatmap } from "./components/Heatmap"
import { SectionTitle } from "./components/SectionTitle"

export function ExamHeatmap({
  exam,
  selected,
  onSelectCell,
  onSelectQuestion,
}: {
  exam: ClassExam
  selected: { attemptId: string; questionId: string } | null
  onSelectCell: (attemptId: string, questionId: string) => void
  onSelectQuestion: (questionId: string) => void
}) {
  return (
    <section className="grid gap-3.5">
      <div className="grid gap-2">
        <SectionTitle title="Every answer" hint="tap a question for the whole class" />
        <div className="flex flex-wrap items-center gap-3.5 font-mono text-[12px] font-semibold text-on-surface-variant">
          <span>Lost</span>
          <span className="h-2.5 w-[120px] rounded-[5px]" style={{ background: HEATMAP_LEGEND.ramp }} aria-hidden />
          <span>Full</span>
          <span className="inline-flex items-center gap-1.5"><i className="h-3 w-3.5 rounded-[3px] outline-[1.5px] outline-dashed outline-outline" aria-hidden />Blank</span>
          <span className="inline-flex items-center gap-1.5"><i className="h-3 w-3.5 rounded-[3px] bg-error-container" aria-hidden />Weak question</span>
        </div>
      </div>
      <Heatmap exam={exam} selected={selected} onSelectCell={onSelectCell} onSelectQuestion={onSelectQuestion} />
    </section>
  )
}
```

- [ ] **Step 3: `AnswerPreview`** (the read-only side panel until L5)

```tsx
// web/src/portals/teacher/papers/components/AnswerPreview.tsx
import { CaretLeft, CaretRight } from "@phosphor-icons/react"
import type { ExamAnswer } from "@/lib/classExamTypes"

export function AnswerPreview({
  answer,
  topic,
  code,
  onPrev,
  onNext,
}: {
  answer: ExamAnswer
  topic: string | null
  code: string
  onPrev?: () => void
  onNext?: () => void
}) {
  return (
    <aside aria-label="Answer" className="flex min-h-0 flex-col gap-2.5 bg-surface-container-lowest p-5 md:border-s md:border-outline-variant">
      <div className="flex items-center gap-2.5">
        <div className="flex-1">
          <h2 className="text-[21px] leading-[1.25] font-bold">{answer.displayName}</h2>
          <div className="font-mono text-[12.5px] font-semibold text-on-surface-variant">
            {topic ?? "Question"} · {answer.awarded === null ? "blank" : `${answer.awarded}/${answer.maximum}`} · {code}
          </div>
        </div>
        <button type="button" aria-label="Previous" disabled={!onPrev} onClick={onPrev} className="grid size-11 place-items-center rounded-[14px] bg-primary-container text-primary disabled:opacity-45"><CaretLeft aria-hidden /></button>
        <button type="button" aria-label="Next" disabled={!onNext} onClick={onNext} className="grid size-11 place-items-center rounded-[14px] bg-primary-container text-primary disabled:opacity-45"><CaretRight aria-hidden /></button>
      </div>
      <div className="grid gap-0.5 rounded-[14px] bg-surface-container-lowest px-3.5 py-2.5 shadow-[inset_0_0_0_1px_var(--color-outline)]">
        <p className="whitespace-pre-wrap font-sans text-[16px] italic leading-6 text-on-surface">
          {answer.studentAnswer ?? (answer.awarded === null ? "Left blank" : "No transcript for this answer")}
        </p>
      </div>
      <div className="font-display text-[34px] leading-none font-extrabold text-primary">
        {answer.awarded ?? "–"}
        <small className="text-[18px] text-on-surface-variant">/{answer.maximum}</small>
      </div>
    </aside>
  )
}
```

- [ ] **Step 4: `QuestionAnswers`** (Q1 behaviour, X6 list + panel, M_answer)

```tsx
// web/src/portals/teacher/papers/QuestionAnswers.tsx
import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { CaretLeft } from "@phosphor-icons/react"
import { Button } from "@/components/ui/button"
import { QueryState } from "@/components/ui/query-state"
import { SkeletonBlock } from "@/components/ui/skeleton"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import type { ClassExam } from "@/lib/classExamTypes"
import { useExamQuestionAnswers } from "@/lib/hooks/useClassExams"
import { teacherLoadFailureMessage } from "@/lib/teacherOutcome"
import { cn } from "@/lib/utils"
import { answerSort, initials } from "./papersViewModel"
import { AnswerPreview } from "./components/AnswerPreview"
import { SectionTitle } from "./components/SectionTitle"

export function QuestionAnswers({
  exam,
  questionId,
  attemptId,
  onSelectAnswer,
  onClose,
}: {
  exam: ClassExam
  questionId: string
  attemptId: string | null
  onSelectAnswer: (attemptId: string) => void
  onClose: () => void
}) {
  const navigate = useNavigate()
  const [order, setOrder] = useState<"lowest" | "highest">("lowest")
  const query = useExamQuestionAnswers(exam.classId, exam.examKey, questionId)
  return (
    <QueryState
      query={query}
      srHeading={`Q${questionId} answers`}
      skeleton={<SkeletonBlock className="h-[320px] rounded-[20px]" />}
      error={{ heading: "Couldn't load these answers", body: teacherLoadFailureMessage }}
    >
      {(data) => {
        const list = answerSort(data.answers, order)
        const index = list.findIndex((x) => x.attemptId === attemptId)
        const current = index >= 0 ? list[index] : null
        return (
          <div className={cn("grid min-h-0 gap-0", current && "xl:grid-cols-[minmax(0,1fr)_400px]")}>
            <div className={cn("grid content-start gap-3.5 xl:pe-5", current && "max-md:hidden")}>
              <div className="flex flex-wrap items-center gap-3">
                <Button variant="text" size="sm" onClick={onClose}><CaretLeft aria-hidden /> Summary</Button>
                <SectionTitle title={`Q${data.questionId} · ${data.topic ?? "Question"}`} hint={`${data.maximumMarks} marks · class average ${data.averagePercent}% · ${data.answers.length} answers`} />
                <ToggleGroup type="single" value={order} onValueChange={(v) => v && setOrder(v as "lowest" | "highest")} aria-label="Order" className="ms-auto inline-flex rounded-xl bg-surface-container p-[3px]">
                  <ToggleGroupItem value="lowest" className="min-h-11 rounded-[9px] px-3 text-[13px] font-bold text-on-surface-variant data-[state=on]:bg-surface-container-lowest data-[state=on]:text-primary md:min-h-0 md:py-1.5">Lowest first</ToggleGroupItem>
                  <ToggleGroupItem value="highest" className="min-h-11 rounded-[9px] px-3 text-[13px] font-bold text-on-surface-variant data-[state=on]:bg-surface-container-lowest data-[state=on]:text-primary md:min-h-0 md:py-1.5">Highest first</ToggleGroupItem>
                </ToggleGroup>
              </div>
              <div className="flex items-center gap-3.5 rounded-[18px] bg-primary-container px-4 py-3.5">
                <p className="flex-1 text-[14.5px] leading-[1.35] font-semibold text-primary">
                  {data.answers.filter((x) => (x.awarded ?? 0) < data.maximumMarks / 2).length} students scored under half.
                </p>
                <Button variant="primary" onClick={() => navigate("/teacher/quizzes?new=1")}>Assign practice</Button>
              </div>
              <ul className="grid">
                {list.map((x) => (
                  <li key={x.attemptId}>
                    <button
                      type="button"
                      aria-pressed={x.attemptId === attemptId}
                      onClick={() => onSelectAnswer(x.attemptId)}
                      className={cn(
                        "grid w-full min-h-11 grid-cols-[28px_minmax(0,1fr)_minmax(0,1.4fr)_70px] items-center gap-4 rounded-xl px-2 py-2.5 text-start max-md:grid-cols-[28px_minmax(0,1fr)_60px]",
                        x.attemptId === attemptId && "bg-surface-container-lowest shadow-[inset_0_0_0_2px_var(--color-primary)]",
                      )}
                    >
                      <span className="grid size-7 place-items-center rounded-full bg-primary-container text-[11px] font-bold text-primary">{initials(x.displayName)}</span>
                      <b className="truncate text-[14px] font-semibold">{x.displayName}</b>
                      <span className="truncate rounded-lg bg-surface-container-lowest px-2.5 py-1.5 text-[13px] italic shadow-[inset_0_0_0_1px_var(--color-outline)] max-md:hidden">
                        {x.studentAnswer ?? (x.awarded === null ? "Blank" : "—")}
                      </span>
                      <span className={cn("text-end font-display text-[24px] leading-none font-extrabold", x.awarded === x.maximum ? "text-success-text" : (x.awarded ?? 0) < x.maximum / 2 ? "text-error" : "text-on-surface")}>
                        {x.awarded ?? "–"}<small className="text-[14px] text-on-surface-variant">/{x.maximum}</small>
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </div>
            {current ? (
              <div className="motion-safe:animate-none">
                <Button variant="text" size="sm" className="md:hidden" onClick={() => onSelectAnswer("")}><CaretLeft aria-hidden /> Answers</Button>
                <AnswerPreview
                  answer={current}
                  topic={data.topic}
                  code={exam.code}
                  onPrev={index > 0 ? () => onSelectAnswer(list[index - 1].attemptId) : undefined}
                  onNext={index < list.length - 1 ? () => onSelectAnswer(list[index + 1].attemptId) : undefined}
                />
              </div>
            ) : null}
          </div>
        )
      }}
    </QueryState>
  )
}
```

`onSelectAnswer("")` clears `a` because `ExamScreen.set` treats an empty value as present; change that call site in `ExamScreen` to `onSelectAnswer={(id) => set({ a: id || null })}`.

The mock's Q1 sentence "Most of the class lost the unit mark." is a summary sentence the user dislikes; the plain count stays, the interpretive half is dropped (listed in PR).

- [ ] **Step 5:** `cd web && npx tsc --noEmit -p . && npx eslint src/portals/teacher/papers && npm run check:copy`. Expected: clean.
- [ ] **Step 6: Side-by-side check** at 1280 (X5, X6, F_X7), 834 (T_X5), 390 (M_exam, M_answer). Fix drift.
- [ ] **Step 7: Commit (Tasks 10 + 11)**

```bash
FILES="web/src/portals/teacher/papers/ExamScreen.tsx web/src/portals/teacher/papers/ExamSummary.tsx web/src/portals/teacher/papers/ExamHeatmap.tsx web/src/portals/teacher/papers/QuestionAnswers.tsx web/src/portals/teacher/papers/components/ExamHeader.tsx web/src/portals/teacher/papers/components/Heatmap.tsx web/src/portals/teacher/papers/components/AnswerPreview.tsx web/src/portals/teacher/index.tsx"
PYTHONPATH=$(pwd) pre-commit run --files $FILES
git commit -S -m "feat(web): exam screen with calm summary, airy heatmap and question answers" -- $FILES
```

---

### Task 12: StudentDetail in two columns

**Files:**
- Create: `web/src/portals/teacher/screens/student/StudentDetailView.tsx` (move `StudentDetailView`, `StudentDetailViewProps`, `StudentDetailDates`, `teacherDates`, `StudentTrendPanel`, `WeaknessRow`, `subjectPercent`, `accuracyTone` verbatim from `StudentDetail.tsx:78-468`; export `teacherDates` too)
- Create: `web/src/portals/teacher/screens/student/StudentHeader.tsx`, `RiskBanner.tsx`, `TrendCard.tsx`, `WeakTopics.tsx`, `PaperRows.tsx`, `StudentFirstRun.tsx`
- Modify (rewrite): `web/src/portals/teacher/screens/StudentDetail.tsx`

**Interfaces:**
- Consumes: Task 7, `useStudentDetail`, `useAcknowledgeAtRisk`, `GradeChip`, `SectionTitle`.
- Produces: `StudentDetail` screen; `StudentDetail.tsx` still exports `StudentDetailView` and `type StudentDetailDates` (re-export) for `TutorStudentDetail.tsx`.

- [ ] **Step 1: Move the legacy view.** Create `screens/student/StudentDetailView.tsx` with lines 2-468 of the old file's imports and bodies (drop `useNavigate`/`useParams`/`useStudentDetail` imports it no longer needs). Run `cd web && npx vitest run tests/unit/tutorStudentView.test.ts`; if it reads `StudentDetail.tsx` source, point it at the new path.

- [ ] **Step 2: Components**

```tsx
// StudentHeader.tsx
import { Link } from "react-router-dom"
import { PageHeading } from "@/components/ui/page-heading"
import { buttonClasses } from "@/components/ui/button"
import { initials } from "../../papers/papersViewModel"

export function StudentHeader({ name, sub, showAssign }: { name: string; sub: string; showAssign: boolean }) {
  return (
    <header className="flex items-center gap-4 pb-3">
      <span className="grid size-14 flex-none place-items-center rounded-full bg-primary-container text-[20px] font-extrabold text-primary max-md:size-11 max-md:text-[16px]">{initials(name)}</span>
      <div className="min-w-0 flex-1">
        <PageHeading repeatsTitle={false} className="text-[21px] leading-[1.2] font-extrabold md:text-[32px] md:leading-[1.1] md:tracking-[-0.02em]">{name}</PageHeading>
        <div className="mt-1 font-mono text-[12px] font-semibold text-on-surface-variant md:text-[12.5px]">{sub}</div>
      </div>
      {showAssign ? (
        <Link to="/teacher/quizzes?new=1" className={buttonClasses({ variant: "primary" }) + " max-md:hidden"}>Assign practice</Link>
      ) : null}
    </header>
  )
}
```

`button.tsx:134` exports "the variant class recipe on its own"; open it and use its real name in place of `buttonClasses`.

```tsx
// RiskBanner.tsx
import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Chip } from "@/components/ui/chip"
import { useAcknowledgeAtRisk } from "@/lib/hooks/useTeacherApi"
import { teacherMutationFailureMessage } from "@/lib/teacherOutcome"

export function RiskBanner({ studentId, flags }: { studentId: string; flags: { reason: string; summary: string; acknowledged: boolean }[] }) {
  const ack = useAcknowledgeAtRisk(studentId)
  const [error, setError] = useState<string | null>(null)
  return (
    <section aria-label="At risk" className="grid gap-1 rounded-[18px] bg-error-container px-3.5 py-3">
      {flags.map((f) => (
        <div key={f.reason} className="flex items-center gap-3">
          <p className="flex-1 text-[14px] leading-[1.4] font-semibold text-on-error-container">At risk: {f.summary}</p>
          {f.acknowledged ? (
            <Chip tone="neutral">Acknowledged</Chip>
          ) : (
            <Button
              size="sm"
              variant="secondary"
              className="border-0 bg-surface-container-lowest text-primary"
              loading={ack.isPending && ack.variables?.reason === f.reason}
              onClick={() => {
                setError(null)
                ack.mutate({ reason: f.reason }, { onError: (e) => setError(teacherMutationFailureMessage(e)) })
              }}
            >
              Acknowledge
            </Button>
          )}
        </div>
      ))}
      {error ? <p role="alert" className="text-body-sm text-error">{error}</p> : null}
    </section>
  )
}
```

```tsx
// TrendCard.tsx
import { useId, useState } from "react"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { cn } from "@/lib/utils"
import { GradeChip } from "../../papers/components/GradeChip"
import type { SubjectRowModel, TrendModel } from "../../papers/studentDetailViewModel"

function TrendSvg({ model, width, height, label }: { model: TrendModel; width: number; height: number; label: (iso: string) => string }) {
  const pts = model.points
  const x = (i: number) => 30 + (i * (width - 60)) / Math.max(1, pts.length - 1)
  const y = (v: number) => height - 26 - ((v - 40) / 40) * (height - 46)
  const clampY = (v: number) => y(Math.min(100, Math.max(0, v)))
  return (
    <svg className="w-full" style={{ height }} viewBox={`0 0 ${width} ${height}`} role="img" aria-label={model.ariaLabel}>
      {model.gradeLine ? (
        <>
          <line x1={30} x2={width - 30} y1={clampY(model.gradeLine.pct)} y2={clampY(model.gradeLine.pct)} stroke="var(--color-grade-b)" strokeDasharray="4 5" strokeWidth={1.5} />
          <text x={30} y={clampY(model.gradeLine.pct) - 7} className="fill-on-surface-variant font-mono text-[11px]">{model.gradeLine.label}</text>
        </>
      ) : null}
      <polyline fill="none" stroke="var(--color-primary)" strokeWidth={3} strokeLinejoin="round" points={pts.map((p, i) => `${x(i)},${clampY(p.pct)}`).join(" ")} />
      {pts.map((p, i) => (
        <g key={p.x}>
          <circle cx={x(i)} cy={clampY(p.pct)} r={i === pts.length - 1 ? 5.5 : 3.5} fill="var(--color-primary)" />
          <text x={x(i)} y={height - 6} textAnchor="middle" className="fill-on-surface-variant font-mono text-[11px]">{label(p.x)}</text>
        </g>
      ))}
      {model.last !== null && pts.length ? (
        <text x={x(pts.length - 1)} y={clampY(model.last) - 12} textAnchor="middle" className="fill-primary font-mono text-[12px] font-bold">{model.last}%</text>
      ) : null}
    </svg>
  )
}

export function TrendCard({
  subjects,
  trendFor,
  monthLabel,
  sparseName,
}: {
  subjects: SubjectRowModel[]
  trendFor: (code: string) => TrendModel
  monthLabel: (iso: string) => string
  sparseName?: string
}) {
  const [code, setCode] = useState(subjects[0]?.code ?? "")
  const model = trendFor(code)
  const tableId = useId()
  return (
    <section className="grid items-center gap-6 rounded-[24px] bg-surface-container-lowest px-5 py-[18px] shadow-[inset_0_0_0_1px_var(--color-outline-variant)] xl:grid-cols-[240px_minmax(0,1fr)]">
      <div className="grid content-center gap-3 max-xl:flex max-xl:flex-wrap max-xl:gap-[18px]">
        {subjects.map((s, i) => (
          <div key={s.code} className="flex items-center gap-3">
            <GradeChip grade={s.grade} size={i === 0 ? "lg" : "md"} />
            <div>
              <div className="text-[15px] font-bold">{s.name}</div>
              <div className="font-mono text-[12px] font-semibold text-on-surface-variant">{s.line}</div>
            </div>
          </div>
        ))}
        {subjects.length > 1 ? (
          <ToggleGroup type="single" value={code} onValueChange={(v) => v && setCode(v)} aria-label="Subject" className="inline-flex justify-self-start rounded-xl bg-surface-container p-[3px]">
            {subjects.map((s) => (
              <ToggleGroupItem key={s.code} value={s.code} className="min-h-11 rounded-[9px] px-3 text-[13px] font-bold text-on-surface-variant data-[state=on]:bg-surface-container-lowest data-[state=on]:text-primary md:min-h-0 md:py-1.5">{s.name}</ToggleGroupItem>
            ))}
          </ToggleGroup>
        ) : null}
      </div>
      {model.points.length <= 1 ? (
        <div className="relative">
          <svg viewBox="0 0 820 150" className="w-full" style={{ height: 150 }} aria-hidden="true">
            <polyline fill="none" stroke="var(--color-outline)" strokeWidth={3} strokeDasharray="8 8" points="40,110 200,92 360,96 520,70 680,64 780,52" />
            <circle cx={40} cy={110} r={6} fill="var(--color-primary)" />
          </svg>
          <p className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 rounded-xl bg-surface-container-lowest px-3.5 py-2 text-[15px] font-bold text-primary shadow-[0_0_0_1px_var(--color-outline-variant)]">
            One more paper draws {sparseName ?? "the"} trend.
          </p>
        </div>
      ) : (
        <div>
          <div className="max-md:hidden"><TrendSvg model={model} width={820} height={170} label={monthLabel} /></div>
          <div className="md:hidden"><TrendSvg model={model} width={358} height={130} label={monthLabel} /></div>
          <table id={tableId} className="sr-only">
            <caption>Percentage per paper</caption>
            <thead><tr><th>Date</th><th>Percentage</th></tr></thead>
            <tbody>{model.points.map((p) => <tr key={p.x}><td>{monthLabel(p.x)}</td><td>{p.pct}%</td></tr>)}</tbody>
          </table>
        </div>
      )}
    </section>
  )
}
```

`sparseName` is passed as `"Omar’s"` style (`${firstName}’s`), giving "One more paper draws Omar’s trend."

```tsx
// WeakTopics.tsx
import { Link } from "react-router-dom"
import { SectionTitle } from "../../papers/components/SectionTitle"
import type { WeakTopicModel } from "../../papers/studentDetailViewModel"

export function WeakTopics({ items, hint }: { items: WeakTopicModel[]; hint?: string }) {
  return (
    <section className="grid content-start gap-2.5 rounded-[24px] bg-surface-container-lowest px-5 py-[18px] shadow-[inset_0_0_0_1px_var(--color-outline-variant)]">
      <SectionTitle title="Weak topics" hint="by marks lost" />
      {items.length === 0 ? (
        <p className="text-[13.5px] text-on-surface-variant">No weak topics yet.</p>
      ) : (
        <ul className="grid">
          {items.map((w, i) => (
            <li key={w.topic} className={i ? "shadow-[0_-1px_0_var(--color-outline-variant)]" : ""}>
              <div className="grid grid-cols-[76px_minmax(0,1fr)_auto] items-center gap-3.5 px-1.5 py-2.5">
                <span className="grid justify-items-center rounded-[14px] bg-error-container px-1 py-2 text-on-error-container">
                  <b className="font-display text-[24px] leading-none font-extrabold">{w.lost}</b>
                  <small className="text-[10.5px] font-semibold">marks</small>
                </span>
                <div className="min-w-0">
                  <b className="block text-[15px] font-bold">{w.topic}</b>
                  <div className="text-[13px] text-on-surface-variant">{w.evidence}</div>
                </div>
                <Link to="/teacher/quizzes?new=1" className="inline-flex min-h-11 items-center rounded-[14px] bg-primary-container px-3 text-[13px] font-bold text-on-primary-container">Assign practice</Link>
              </div>
            </li>
          ))}
        </ul>
      )}
      {hint ? <p className="text-[13.5px] text-on-surface-variant">{hint}</p> : null}
    </section>
  )
}
```

```tsx
// PaperRows.tsx
import { type ReactNode } from "react"
import { ListGroup, ListRow } from "@/components/ui/list-group"
import { TableOrList } from "@/components/ui/table-or-list"
import { SectionTitle } from "../../papers/components/SectionTitle"
import { GradeChip } from "../../papers/components/GradeChip"
import type { PaperRowModel } from "../../papers/studentDetailViewModel"

export function PaperRows({
  rows,
  footer,
  action,
}: {
  rows: PaperRowModel[]
  footer?: ReactNode
  action?: (row: PaperRowModel) => ReactNode
}) {
  return (
    <section className="grid content-start gap-2.5 rounded-[24px] bg-surface-container-lowest px-5 py-[18px] shadow-[inset_0_0_0_1px_var(--color-outline-variant)]">
      <SectionTitle title="Papers" />
      <TableOrList
        label="Papers"
        storageKey="lemely.studentAttempts.view"
        list={
          <ListGroup>
            {rows.map((p) => (
              <ListRow
                key={p.key}
                title={p.title}
                subtitle={`${p.when}${p.toReview ? ` · ${p.toReview}` : ""}`}
                trailing={<span className="flex items-center gap-2"><span className="font-mono text-[15px] font-bold">{p.marks}<small className="text-on-surface-variant">/{p.outOf}</small></span><GradeChip grade={p.grade} />{action?.(p)}</span>}
              />
            ))}
          </ListGroup>
        }
        table={
          <ul className="grid">
            {rows.map((p, i) => (
              <li key={p.key} className={i ? "shadow-[0_-1px_0_var(--color-outline-variant)]" : ""}>
                <div className="grid grid-cols-[minmax(0,1fr)_90px_44px_auto] items-center gap-3.5 px-1.5 py-2.5">
                  <div className="min-w-0">
                    <b className="block truncate text-[15px] font-bold">{p.title}</b>
                    <div className="font-mono text-[12px] font-semibold text-on-surface-variant">
                      {p.when}{p.toReview ? <> · <span className="text-error">{p.toReview}</span></> : null}
                    </div>
                  </div>
                  <span className="text-end font-mono text-[15px] font-bold">{p.marks}<small className="text-on-surface-variant">/{p.outOf}</small></span>
                  <GradeChip grade={p.grade} />
                  <span>{action?.(p)}</span>
                </div>
              </li>
            ))}
          </ul>
        }
      />
      {footer}
    </section>
  )
}
```

Read `TableOrList`'s props (`web/src/components/ui/table-or-list.tsx:8`) and match them; the old screen passes `label`, `storageKey`, `list`, `table`.

```tsx
// StudentFirstRun.tsx
import { FileArrowUp, DeviceMobile } from "@phosphor-icons/react"
import { useNavigate } from "react-router-dom"
import { Walkthrough } from "@/components/redesign"
import { Button } from "@/components/ui/button"
import { initials } from "../../papers/papersViewModel"

export function StudentFirstRun({ name }: { name: string }) {
  const navigate = useNavigate()
  const first = name.split(/\s+/)[0] ?? name
  return (
    <section className="grid max-w-[820px] gap-[22px] rounded-[28px] bg-surface-container-lowest p-7 shadow-[inset_0_0_0_1px_var(--color-outline-variant)] max-md:gap-4 max-md:p-5">
      <div className="flex items-center gap-4">
        <span className="grid size-14 place-items-center rounded-full bg-primary-container text-[20px] font-extrabold text-primary">{initials(name)}</span>
        <div>
          <h2 className="font-display text-[28px] leading-[1.15] font-extrabold tracking-[-0.03em] text-primary">No marked papers for {first} yet</h2>
          <p className="mt-1 max-w-[46ch] text-on-surface-variant">Their grade, trend and weak topics appear here once a paper is marked.</p>
        </div>
      </div>
      <Walkthrough
        steps={[
          { icon: FileArrowUp, title: `Mark a paper ${first} sat`, body: "From a class set, or upload their paper on its own." },
          { icon: DeviceMobile, title: `Or let ${first} upload their own`, body: "Students can scan practice papers from their phone." },
        ]}
      />
      <div className="flex gap-2.5">
        <Button variant="primary" onClick={() => navigate("/teacher/grading")}>Mark papers</Button>
      </div>
    </section>
  )
}
```

("Invite Omar to upload" is left out: no invite-to-upload feature exists — decision D7.)

- [ ] **Step 3: Rewrite `StudentDetail.tsx`**

```tsx
// web/src/portals/teacher/screens/StudentDetail.tsx
/* Student detail, teacher view (L8 redesign of T-05). The shared tutor view lives in ./student/StudentDetailView. */
import { useNavigate, useParams } from "react-router-dom"
import { EmptyState } from "@/components/ui/state-views"
import { QueryState } from "@/components/ui/query-state"
import { SkeletonBlock } from "@/components/ui/skeleton"
import { Button } from "@/components/ui/button"
import { useStudentDetail } from "@/lib/hooks/useTeacherApi"
import { teacherLoadFailureMessage } from "@/lib/teacherOutcome"
import {
  engagement,
  headerSub,
  paperRows,
  riskModel,
  studentDetailState,
  subjectRows,
  trendFor,
  weakTopics,
} from "../papers/studentDetailViewModel"
import { PaperRows } from "./student/PaperRows"
import { RiskBanner } from "./student/RiskBanner"
import { StudentFirstRun } from "./student/StudentFirstRun"
import { StudentHeader } from "./student/StudentHeader"
import { teacherDates } from "./student/StudentDetailView"
import { TrendCard } from "./student/TrendCard"
import { WeakTopics } from "./student/WeakTopics"

export { StudentDetailView, type StudentDetailDates, type StudentDetailViewProps } from "./student/StudentDetailView"

const month = (iso: string) => new Date(iso).toLocaleDateString(undefined, { month: "short" })

function Skeleton() {
  return (
    <div className="grid gap-4" aria-busy="true">
      <SkeletonBlock className="h-14 w-[320px] max-w-full rounded-full" />
      <SkeletonBlock className="h-[200px] rounded-[24px]" />
      <div className="grid gap-[22px] xl:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)]">
        <SkeletonBlock className="h-[220px] rounded-[24px]" />
        <SkeletonBlock className="h-[220px] rounded-[24px]" />
      </div>
    </div>
  )
}

export function StudentDetail() {
  const { studentId } = useParams<{ studentId: string }>()
  const navigate = useNavigate()
  const query = useStudentDetail(studentId)
  return (
    <div className="grid min-w-0 gap-4">
      <QueryState
        query={query}
        srHeading="Student detail"
        skeleton={<Skeleton />}
        idle={
          <EmptyState
            heading="No student selected"
            body="Choose a student from a class roster or the at-risk list to see their detail."
            action={{ label: "Go back", onClick: () => navigate(-1) }}
          />
        }
        error={{
          heading: "Couldn't load this student",
          body: teacherLoadFailureMessage,
          secondaryAction: { label: "Go back", onClick: () => navigate(-1) },
        }}
      >
        {(s) => {
          const state = studentDetailState(s)
          const risk = riskModel(s)
          const first = s.displayName.split(/\s+/)[0] ?? s.displayName
          const sub = headerSub(s, teacherDates.activeSummary(s.engagement.lastActiveAt))
          if (state === "empty") {
            return (
              <>
                <StudentHeader name={s.displayName} sub={sub} showAssign={false} />
                {risk ? <RiskBanner studentId={s.studentId} flags={risk.flags} /> : null}
                <StudentFirstRun name={s.displayName} />
              </>
            )
          }
          const rows = paperRows(s, teacherDates.recorded)
          const eng = engagement(s, teacherDates.lastActive(s.engagement.lastActiveAt))
          return (
            <>
              <StudentHeader name={s.displayName} sub={sub} showAssign />
              {risk ? <RiskBanner studentId={s.studentId} flags={risk.flags} /> : null}
              <TrendCard
                subjects={subjectRows(s)}
                trendFor={(code) => trendFor(s, code)}
                monthLabel={month}
                sparseName={state === "sparse" ? `${first}’s` : undefined}
              />
              <div className="grid min-h-0 gap-[22px] xl:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)]">
                <WeakTopics
                  items={weakTopics(s, state === "sparse" ? 1 : 3)}
                  hint={state === "sparse" ? "Weak topics firm up after 2 or 3 papers. One paper can be a bad day." : undefined}
                />
                <PaperRows
                  rows={rows}
                  footer={
                    state === "sparse" ? (
                      <Button size="sm" variant="secondary" className="justify-self-start border-0 bg-primary-container text-on-primary-container" onClick={() => navigate("/teacher/grading")}>
                        Mark another paper
                      </Button>
                    ) : (
                      <div className="flex gap-[22px] pt-2 shadow-[0_-1px_0_var(--color-outline-variant)]">
                        {eng.map((e) => (
                          <div key={e.label} className="font-mono text-[12px] font-semibold text-on-surface-variant">
                            <b className="mb-0.5 block font-display text-[26px] leading-none font-extrabold text-primary">{e.value}</b>
                            {e.label}
                          </div>
                        ))}
                      </div>
                    )
                  }
                />
              </div>
            </>
          )
        }}
      </QueryState>
    </div>
  )
}
```

Phone order (M_student): header, risk, trend, weak topics, papers — the grid stacks in that order below `xl`.

- [ ] **Step 4:** `cd web && npx tsc --noEmit -p . && npx vitest run tests/unit/studentDetailViewModel.test.ts tests/unit/tutorStudentView.test.ts tests/unit/teacherTables.test.ts tests/unit/tableOrList.test.ts && npm run check:copy`. Update any source-scan test that names the old `StudentDetail.tsx` structure to the new files.
- [ ] **Step 5: Side-by-side** S4 (1280), T_S4 (834), M_student (390), Z_student_empty, Z_student_sparse.
- [ ] **Step 6: Commit**

```bash
FILES="web/src/portals/teacher/screens/StudentDetail.tsx $(git ls-files -o -m web/src/portals/teacher/screens/student) web/tests/unit/tutorStudentView.test.ts web/tests/unit/teacherTables.test.ts web/tests/unit/tableOrList.test.ts"
PYTHONPATH=$(pwd) pre-commit run --files $FILES
git commit -S -m "feat(web): student detail in two columns with the trend" -- $FILES
```

(Commit only the test files you actually changed.)

---

### Task 13: Playwright happy paths

**Files:**
- Create: `web/e2e/teacher-papers.spec.ts`

**Interfaces:** Consumes the seeded teacher, class and students from `web/e2e/seed.ts` (`readSeed()`), the same seed `teacher-journey.spec.ts` uses. The seed gives three students with marked papers, so the exam is in the sparse state (fewer than 5 papers); the heatmap gate is covered by Vitest and pytest.

- [ ] **Step 1: Write the spec**

```ts
// web/e2e/teacher-papers.spec.ts
import { expect, test } from "@playwright/test"
import { watchConsole } from "./console-errors"
import { readSeed } from "./seed"

async function login(page: import("@playwright/test").Page) {
  const { teacher } = readSeed()
  await page.goto("/login")
  await page.getByLabel("Email").fill(teacher.email)
  await page.getByLabel("Password").fill(teacher.password)
  await page.getByRole("button", { name: /sign in/i }).click()
  await expect(page).toHaveURL(/\/teacher$/, { timeout: 15_000 })
}

test("teacher opens class exams, an exam summary and downloads marks", async ({ page }) => {
  const seed = readSeed()
  const errors = watchConsole(page)
  await login(page)

  await page.goto(`/teacher/classes/${seed.class.classId}/papers`)
  const tile = page.locator("main a").filter({ hasText: /Paper \d/ }).first()
  await expect(tile).toBeVisible({ timeout: 15_000 })
  await expect(tile).toContainText("average")
  await tile.click()

  await expect(page).toHaveURL(/\/papers\/\d{4}-\d{2}-(mj|on|fm|sp)-(\d{4}|x)/)
  await expect(page.getByRole("heading", { level: 1 })).toContainText(/Paper \d/)
  await expect(page.getByText(/papers marked/)).toBeVisible()
  await expect(page.getByRole("radio", { name: "Heatmap" }).or(page.getByRole("button", { name: "Heatmap" }))).toBeDisabled()
  await expect(page.getByText(seed.students.declining.displayName)).toBeVisible()

  const download = page.waitForEvent("download")
  await page.getByRole("button", { name: "Download marks" }).first().click()
  expect((await download).suggestedFilename()).toMatch(/\.csv$/)

  expect(errors()).toEqual([])
})

test("teacher opens a student in two columns", async ({ page }) => {
  const seed = readSeed()
  const errors = watchConsole(page)
  await login(page)
  await page.goto(`/teacher/students/${seed.students.declining.studentId}`)
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(seed.students.declining.displayName, { timeout: 15_000 })
  await expect(page.getByRole("heading", { name: "Weak topics" })).toBeVisible()
  await expect(page.getByRole("heading", { name: "Papers" })).toBeVisible()
  await expect(page.getByRole("img", { name: /Percentage per paper|One paper/ })).toBeVisible()
  await expect(page.getByText(/^At risk:/).first()).toBeVisible()
  expect(errors()).toEqual([])
})

test("phone shows question bars", async ({ page }) => {
  const seed = readSeed()
  await page.setViewportSize({ width: 390, height: 844 })
  await login(page)
  await page.goto(`/teacher/classes/${seed.class.classId}/papers`)
  await page.locator("main a").filter({ hasText: /Paper \d/ }).first().click()
  await expect(page.getByRole("button", { name: "Download marks" })).toBeVisible()
})
```

Check `web/e2e/seed.ts` for the real field names (`students.declining.studentId`, `.displayName`, `class.classId`) and `watchConsole`'s return shape in `console-errors.ts`; align before running. The seeded "declining" student must have papers and an at-risk flag (it does in `teacher-journey.spec.ts`).

- [ ] **Step 2: Run** (needs the local e2e stack as `teacher-journey.spec.ts` does): `cd web && npx playwright test e2e/teacher-papers.spec.ts`. Expected: 3 passed.
- [ ] **Step 3: Commit**

```bash
PYTHONPATH=$(pwd) pre-commit run --files web/e2e/teacher-papers.spec.ts
git commit -S -m "test(e2e): teacher papers and student detail happy paths" -- web/e2e/teacher-papers.spec.ts
```

---

### Task 14: Fidelity screenshots, drift fixes, polish

**Files:** any file under the lane's owned paths; screenshots to `/tmp/claude-1000/-home-sico-Code-Lemely/<session>/scratchpad/l8-fidelity/` (never committed).

- [ ] **Step 1:** Serve the mock: `npx serve .impeccable/mocks -l 4599`. Run the app (`npm run dev` in `web/`, seeded backend).
- [ ] **Step 2:** For each pair below, screenshot the mock frame element and the app at 390 and 1280 (and 834 for the tablet frames) with Playwright or Chrome DevTools, and put them side by side:
  - `E3` ↔ `/teacher/classes/:id/papers`
  - `X5`, `T_X5`, `M_exam` ↔ exam Summary
  - `X6`, `M_answer` ↔ `?q=8&a=…`
  - `F_X7` ↔ `?view=heatmap` (needs ≥5 papers: use a local class with 5+ seeded papers)
  - `S4`, `T_S4`, `M_student` ↔ StudentDetail
  - `Z_class`, `M_empty`, `Z_class_sparse`, `Z_exam_sparse`, `Z_student_empty`, `Z_student_sparse`, `L_exam`, `R_exam` ↔ the matching states (use route mocking `page.route` to force empty/sparse/error responses where seed data cannot produce them)
- [ ] **Step 3:** Fix every visible drift (spacing, sizes, weights, colours, order). Layout, flow or content changes go to "Needs user decision" instead.
- [ ] **Step 4:** Run `/impeccable polish` on `web/src/portals/teacher/papers/` and `web/src/portals/teacher/screens/student/`. Verify: no text under 12px, 44px tap targets (heatmap cells noted), contrast passes in light and dark, reduced motion removes the panel/bar transitions, Binny appears once (class first run only).
- [ ] **Step 5:** Re-run the lane's tests: `cd web && npx vitest run tests/unit/classExamApi.test.ts tests/unit/papersViewModel.test.ts tests/unit/heatmapScale.test.ts tests/unit/studentDetailViewModel.test.ts tests/unit/navShells.test.ts tests/unit/navigation.test.ts && npx tsc --noEmit -p . && npm run check:copy && npm run check:native`.
- [ ] **Step 6:** Commit the polish with explicit paths: `git commit -S -m "fix(web): teacher papers fidelity and polish" -- <changed paths>`.

---

### Task 15: Student paper in the review-queue layout (after L5 merges)

**Blocked on:** L5 merged into `develop` and this branch rebased onto it. L5's plan (`2026-11-15-redesign-l05-review-queue.md`, Task 9) exports from `web/src/portals/teacher/screens/review/index.ts`: `AnswerPanel`, `AnswerPage`, `type AnswerView`, `useAnswerImages(itemId, hasScan)` and `initialMarkState`. L8 renders `AnswerPanel` **read-only** (`marking={null}`). The scan crop and whole page are served per review item (`/teacher/review/{itemId}/crop|page`), so an answer with an open review item shows its scan and links to the queue for remarking; any other answer shows its transcription only (decision D8).

**Files:**
- Create: `web/src/portals/teacher/papers/StudentPaper.tsx`, `web/src/portals/teacher/papers/PaperAnswerPanel.tsx`, `web/src/portals/teacher/papers/paperAnswerView.ts`, `web/src/portals/teacher/papers/useIsPhone.ts`
- Test: `web/tests/unit/paperAnswerView.test.ts`
- Modify: `web/src/portals/teacher/papers/QuestionAnswers.tsx` (swap `AnswerPreview` for `PaperAnswerPanel`), `web/src/portals/teacher/screens/StudentDetail.tsx` (Open action), `web/src/portals/teacher/index.tsx` (route), `web/e2e/teacher-papers.spec.ts` (open a paper); delete `web/src/portals/teacher/papers/components/AnswerPreview.tsx`

**Interfaces:**
- Consumes: `useStudentPaper` (Task 5), `StudentPaper`/`ExamAnswer` types (Task 5), L5's `AnswerPanel`, `AnswerPage`, `AnswerView`, `useAnswerImages`.
- Produces:
  - `interface PaperAnswer { key: string; reviewItemId: string | null; title: string; subtitle: string; studentHref: string | null; transcription: string | null; expected: string | null; topic: string | null; feedback: string | null; awarded: number | null; maximum: number }`
  - `toAnswerView(a: PaperAnswer): AnswerView` (pure, in `paperAnswerView.ts`)
  - `PaperAnswerPanel({ answer: PaperAnswer; pos: number; total: number; onPrev: () => void; onNext: () => void; onBack?: () => void; phone?: boolean })`
  - route `/teacher/students/:studentId/papers/:attemptId`

- [ ] **Step 1: Write the failing test for the view adapter**

```ts
// web/tests/unit/paperAnswerView.test.ts
import { describe, expect, it } from "vitest"
import { toAnswerView, type PaperAnswer } from "@/portals/teacher/papers/paperAnswerView"

const base: PaperAnswer = {
  key: "qr1",
  reviewItemId: null,
  title: "Omar Saleh · Q8",
  subtitle: "Density and units · 1/4 · 0580/42",
  studentHref: "/teacher/students/s1",
  transcription: "ρ = 54 / 20 = 2.7",
  expected: "2.7 g/cm³",
  topic: "Density and units",
  feedback: "Unit missing",
  awarded: 1,
  maximum: 4,
}

describe("toAnswerView", () => {
  it("builds a read-only view with no scan when there is no review item", () => {
    const v = toAnswerView(base)
    expect(v).toMatchObject({
      key: "qr1",
      title: "Omar Saleh · Q8",
      transcription: "ρ = 54 / 20 = 2.7",
      scheme: { expected: "2.7 g/cm³", topic: "Density and units" },
      notes: { reason: null, feedback: "Unit missing" },
      maximumMarks: 4,
      lemelyMarks: 1,
      hasScan: false,
      status: "resolved",
      canAdjust: false,
      points: [],
      selfReview: [],
    })
    expect(v.cannotAdjustReason).toBe("Marks change in the review queue.")
  })
  it("shows the scan and an open status when the answer is in the queue", () => {
    const v = toAnswerView({ ...base, reviewItemId: "item-1" })
    expect(v.hasScan).toBe(true)
    expect(v.status).toBe("open")
  })
  it("labels a blank answer", () => {
    expect(toAnswerView({ ...base, transcription: null, awarded: null }).transcription).toBe("Left blank")
  })
})
```

Run: `cd web && npx vitest run tests/unit/paperAnswerView.test.ts` → FAIL (module missing).

- [ ] **Step 2: Implement the adapter and the panel seam**

```ts
// web/src/portals/teacher/papers/paperAnswerView.ts
/* Builds L5's AnswerView from one marked question (the L8 side of the seam L5's answerView.ts names). */
import type { AnswerView } from "../screens/review"

export interface PaperAnswer {
  key: string
  reviewItemId: string | null
  title: string
  subtitle: string
  studentHref: string | null
  transcription: string | null
  expected: string | null
  topic: string | null
  feedback: string | null
  awarded: number | null
  maximum: number
}

export function toAnswerView(a: PaperAnswer): AnswerView {
  return {
    key: a.key,
    title: a.title,
    subtitle: a.subtitle,
    studentHref: a.studentHref,
    pageLabel: null,
    hasScan: a.reviewItemId !== null,
    transcription: a.transcription ?? (a.awarded === null ? "Left blank" : null),
    selfReview: [],
    scheme: { expected: a.expected, topic: a.topic },
    notes: { reason: null, feedback: a.feedback },
    points: [],
    matchedPointIds: [],
    maximumMarks: a.maximum,
    lemelyMarks: a.awarded,
    status: a.reviewItemId ? "open" : "resolved",
    integrity: false,
    canAdjust: false,
    cannotAdjustReason: "Marks change in the review queue.",
    correction: null,
    resolutionNote: null,
  }
}
```

If L5's merged `AnswerView` differs from its plan (fields added or renamed), `tsc` fails here and only this function changes.

```tsx
// web/src/portals/teacher/papers/PaperAnswerPanel.tsx
/* The single seam onto L5's review-queue answer panel, read-only. */
import { Link } from "react-router-dom"
import { AnswerPage, AnswerPanel, useAnswerImages } from "../screens/review"
import { toAnswerView, type PaperAnswer } from "./paperAnswerView"

export function PaperAnswerPanel({
  answer,
  pos,
  total,
  onPrev,
  onNext,
  onBack,
  phone,
}: {
  answer: PaperAnswer
  pos: number
  total: number
  onPrev: () => void
  onNext: () => void
  onBack?: () => void
  phone?: boolean
}) {
  const view = toAnswerView(answer)
  const images = useAnswerImages(answer.reviewItemId ?? undefined, view.hasScan)
  const props = {
    view,
    images: {
      cropUrl: images.crop.url,
      onCropError: images.crop.onDecodeError,
      pageUrl: images.page.url,
      onPageError: images.page.onDecodeError,
      pageRequested: images.pageRequested,
      requestPage: images.requestPage,
    },
    nav: { pos, total, onPrev, onNext },
    onBack,
    marking: null,
  }
  return (
    <div className="grid min-h-0 gap-2">
      {phone ? <AnswerPage {...props} /> : <AnswerPanel {...props} />}
      {answer.reviewItemId ? (
        <Link
          to={`/teacher/review/${answer.reviewItemId}`}
          className="mx-5 mb-4 inline-flex min-h-11 items-center justify-center rounded-[14px] bg-primary px-4 text-label font-bold text-on-primary"
        >
          Review this answer
        </Link>
      ) : null}
    </div>
  )
}
```

The `images` mapping is copied from L5's `ReviewQueue.tsx` (L5 plan line "images: { cropUrl: images.crop.url, … }").

Run: `cd web && npx vitest run tests/unit/paperAnswerView.test.ts && npx tsc --noEmit -p .` → PASS.

- [ ] **Step 3: `useIsPhone` and `StudentPaper`** (O1: 420px question list + panel; phone: list, then L5's full-screen `AnswerPage`)

```ts
// web/src/portals/teacher/papers/useIsPhone.ts
import { useSyncExternalStore } from "react"

const QUERY = "(max-width: 767px)"
const subscribe = (cb: () => void) => {
  const mq = window.matchMedia(QUERY)
  mq.addEventListener("change", cb)
  return () => mq.removeEventListener("change", cb)
}

/** True below the 768px shell breakpoint, where an answer opens full screen. */
export function useIsPhone(): boolean {
  return useSyncExternalStore(subscribe, () => window.matchMedia(QUERY).matches, () => false)
}
```


```tsx
// web/src/portals/teacher/papers/StudentPaper.tsx
import { useState } from "react"
import { Link, useParams, useSearchParams } from "react-router-dom"
import { CaretLeft } from "@phosphor-icons/react"
import { PageHeading } from "@/components/ui/page-heading"
import { QueryState } from "@/components/ui/query-state"
import { SkeletonBlock } from "@/components/ui/skeleton"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { useStudentPaper } from "@/lib/hooks/useClassExams"
import { useIsPhone } from "./useIsPhone"
import { teacherLoadFailureMessage } from "@/lib/teacherOutcome"
import { cn } from "@/lib/utils"
import { GradeChip } from "./components/GradeChip"
import { PaperAnswerPanel } from "./PaperAnswerPanel"

export function StudentPaper() {
  const { studentId, attemptId } = useParams<{ studentId: string; attemptId: string }>()
  const [params, setParams] = useSearchParams()
  const [order, setOrder] = useState<"lost" | "paper">("lost")
  const isPhone = useIsPhone()
  const query = useStudentPaper(studentId, attemptId)
  return (
    <QueryState
      query={query}
      srHeading="Student paper"
      skeleton={<SkeletonBlock className="h-[480px] rounded-[24px]" />}
      error={{ heading: "Couldn't load this paper", body: teacherLoadFailureMessage }}
    >
      {(p) => {
        const lost = p.questions.filter((q) => q.marksLost > 0)
        const full = p.questions.length - lost.length
        const list = order === "lost" ? [...lost].sort((a, b) => b.marksLost - a.marksLost) : p.questions
        const selectedId = params.get("q") ?? list[0]?.questionResultId ?? null
        const index = list.findIndex((q) => q.questionResultId === selectedId)
        const current = index >= 0 ? list[index] : null
        const select = (id: string | null) => setParams(id ? { q: id } : {})
        return (
          <div className="grid gap-3">
            <header className="flex items-end gap-4 pb-2.5">
              <div className="min-w-0 flex-1">
                <Link to={`/teacher/students/${p.studentId}`} className="mb-1.5 inline-flex min-h-11 items-center gap-1.5 text-[13px] font-semibold text-primary">
                  <CaretLeft aria-hidden /> {p.displayName}
                </Link>
                <PageHeading repeatsTitle={false} className="text-[21px] font-extrabold md:text-[32px] md:leading-[1.1]">{p.code} · {p.session}</PageHeading>
                <div className="mt-1 font-mono text-[12.5px] font-semibold text-on-surface-variant">
                  {p.awardedMarks}/{p.maximumMarks}{p.answersToReview ? ` · ${p.answersToReview} answers to review` : ""}
                </div>
              </div>
              <GradeChip grade={p.grade} size="lg" />
            </header>
            <div className="grid min-h-0 md:grid-cols-[420px_minmax(0,1fr)]">
              <div className={cn("grid content-start gap-1 border-outline-variant bg-surface-container-low px-3.5 py-[18px] md:border-e", current && "max-md:hidden")}>
                <ToggleGroup type="single" value={order} onValueChange={(v) => v && setOrder(v as "lost" | "paper")} aria-label="Order" className="mb-1.5 inline-flex justify-self-start rounded-xl bg-surface-container p-[3px]">
                  <ToggleGroupItem value="lost" className="min-h-11 rounded-[9px] px-3 text-[13px] font-bold text-on-surface-variant data-[state=on]:bg-surface-container-lowest data-[state=on]:text-primary md:min-h-0 md:py-1.5">Marks lost</ToggleGroupItem>
                  <ToggleGroupItem value="paper" className="min-h-11 rounded-[9px] px-3 text-[13px] font-bold text-on-surface-variant data-[state=on]:bg-surface-container-lowest data-[state=on]:text-primary md:min-h-0 md:py-1.5">Question order</ToggleGroupItem>
                </ToggleGroup>
                {list.map((q) => (
                  <button
                    key={q.questionResultId}
                    type="button"
                    aria-pressed={q.questionResultId === selectedId}
                    onClick={() => select(q.questionResultId)}
                    className={cn(
                      "grid min-h-11 grid-cols-[44px_minmax(0,1fr)_auto] items-center gap-3 rounded-[14px] p-2.5 text-start",
                      q.questionResultId === selectedId && "bg-surface-container-lowest shadow-[inset_0_0_0_2px_var(--color-primary)]",
                    )}
                  >
                    <span className="font-mono text-[14px] font-bold text-primary">Q{q.questionId}</span>
                    <span className="min-w-0">
                      <b className="block truncate text-[14px] font-semibold">{q.topic ?? "Question"}</b>
                      <span className="flex items-center gap-1.5 text-[12.5px] text-on-surface-variant">
                        <i className={cn("size-2 rounded-full", q.awarded === null ? "bg-on-surface-variant" : q.marksLost > 0 ? "bg-error" : "bg-success")} aria-hidden />
                        {q.awarded === null ? "Blank" : q.reviewItemId ? "To review" : q.marksLost > 0 ? `${q.marksLost} lost` : "Full marks"}
                      </span>
                    </span>
                    <span className={cn("font-display text-[24px] leading-none font-extrabold", q.marksLost === 0 && "text-success-text")}>
                      {q.awarded ?? "–"}<small className="text-[13px] text-on-surface-variant">/{q.maximum}</small>
                    </span>
                  </button>
                ))}
                {order === "lost" && full > 0 ? (
                  <div className="px-2.5 py-2 text-[13px] font-semibold text-on-surface-variant">+ {full} questions with full marks</div>
                ) : null}
              </div>
              {current ? (
                <PaperAnswerPanel
                  phone={isPhone}
                  onBack={() => select(null)}
                  pos={index + 1}
                  total={list.length}
                  onPrev={() => index > 0 && select(list[index - 1].questionResultId)}
                  onNext={() => index < list.length - 1 && select(list[index + 1].questionResultId)}
                  answer={{
                    key: current.questionResultId,
                    reviewItemId: current.reviewItemId,
                    title: `${p.displayName} · Q${current.questionId}`,
                    subtitle: `${current.topic ?? "Question"} · ${current.awarded ?? "–"}/${current.maximum} · ${p.code}`,
                    studentHref: `/teacher/students/${p.studentId}`,
                    transcription: current.studentAnswer,
                    expected: current.expectedAnswer,
                    topic: current.topic,
                    feedback: current.feedback,
                    awarded: current.awarded,
                    maximum: current.maximum,
                  }}
                />
              ) : null}
            </div>
          </div>
        )
      }}
    </QueryState>
  )
}
```

- [ ] **Step 4: Wire it.**
  - `index.tsx`: `const StudentPaper = lazy(() => import("./papers/StudentPaper").then((m) => ({ default: m.StudentPaper })))` and route `{ path: "students/:studentId/papers/:attemptId", element: <StudentPaper />, handle: { title: "Student paper", skeleton: "page-header" } }`.
  - `StudentDetail.tsx`: pass `action={(row) => row.attemptId ? <Link to={`/teacher/students/${s.studentId}/papers/${row.attemptId}`} className="inline-flex min-h-11 items-center rounded-[14px] px-3 text-[13px] font-bold shadow-[inset_0_0_0_1.5px_var(--color-outline)]">Open</Link> : null}` to `PaperRows` (import `Link`).
  - `QuestionAnswers.tsx`: replace the `<AnswerPreview … />` element with

    ```tsx
    <PaperAnswerPanel
      phone={isPhone}
      onBack={() => onSelectAnswer("")}
      pos={index + 1}
      total={list.length}
      onPrev={() => index > 0 && onSelectAnswer(list[index - 1].attemptId)}
      onNext={() => index < list.length - 1 && onSelectAnswer(list[index + 1].attemptId)}
      answer={{
        key: current.questionResultId,
        reviewItemId: current.reviewItemId,
        title: `${current.displayName} · Q${data.questionId}`,
        subtitle: `${data.topic ?? "Question"} · ${current.awarded ?? "–"}/${current.maximum} · ${exam.code}`,
        studentHref: `/teacher/students/${current.studentId}`,
        transcription: current.studentAnswer,
        expected: null,
        topic: data.topic,
        feedback: null,
        awarded: current.awarded,
        maximum: current.maximum,
      }}
    />
    ```

    with `const isPhone = useIsPhone()` at the top of the component; remove the phone-only "Answers" back button (L5's `AnswerPage` draws its own back). Then delete `components/AnswerPreview.tsx`.
  - The panel is read-only, so no invalidation is needed here; a remark happens in the review queue, whose own mutations invalidate `["teacher","review"]`. Add `["teacher","class"]` and `["teacher","student"]` invalidation to L5's resolve hook only if L5 has not (coordinate in L5's PR, do not edit L5's files from this lane).
- [ ] **Step 5: e2e.** Append to `web/e2e/teacher-papers.spec.ts`:

```ts
test("teacher opens a student's paper in the review layout", async ({ page }) => {
  const seed = readSeed()
  await login(page)
  await page.goto(`/teacher/students/${seed.students.declining.studentId}`)
  await page.getByRole("link", { name: "Open" }).first().click()
  await expect(page).toHaveURL(/\/papers\/[0-9a-f-]{36}/)
  await expect(page.getByRole("radio", { name: "Marks lost" }).or(page.getByRole("button", { name: "Marks lost" }))).toBeVisible()
  await expect(page.getByRole("button", { name: "Next" })).toBeVisible()
})
```

- [ ] **Step 6: Run** `cd web && npx tsc --noEmit -p . && npx playwright test e2e/teacher-papers.spec.ts`; side-by-side `O1` at 1280 and the phone flow at 390.
- [ ] **Step 7: Commit** with explicit paths: `git commit -S -m "feat(web): open a student's paper and answers in the review-queue layout" -- <paths>`.

---

### Task 16: Keep-list check

- [ ] **Step 1:** Walk every K, G and S item above in the running app (phone and desktop). Tick each in the PR body with where it now lives.
- [ ] **Step 2:** Any item that fails becomes a fix in the owning task's files before Task 17. Do not proceed with an unticked item.

### Task 17: Delete the old code

**Files:** Delete `web/src/portals/teacher/screens/ClassPapers.tsx`, `web/src/portals/teacher/screens/Grading.tsx`. (`StudentDetail.tsx` was rewritten in Task 12; its legacy view now lives in `screens/student/StudentDetailView.tsx` for tutoring.)

- [ ] **Step 1:** `git rm web/src/portals/teacher/screens/ClassPapers.tsx web/src/portals/teacher/screens/Grading.tsx`
- [ ] **Step 2:** Find every remaining reference: `grep -rn "screens/ClassPapers\|screens/Grading\|ClassPapers\b" web/src web/tests web/e2e web/scripts`. Update the source-scanning tests that name these files to the new ones: `web/tests/unit/teacherTables.test.ts`, `tableOrList.test.ts`, `teacherPaperDeletionWiring.test.ts`, `utilityExistence.test.ts`, `rtlSafety.test.ts`, `progressRing.test.ts`, `formsMigration.test.ts`, `activeScanGuard.test.ts` (each only where it reads a deleted path; `Grading.tsx` content now lives in `papers/MarkPapersConsole.tsx`). Also check `web/scripts/check-native-invariants.mjs` and `check_copy.mjs` for hard-coded paths.
- [ ] **Step 3:** Run every touched test plus the source scanners: `cd web && npx vitest run tests/unit/teacherTables.test.ts tests/unit/tableOrList.test.ts tests/unit/teacherPaperDeletionWiring.test.ts tests/unit/utilityExistence.test.ts tests/unit/rtlSafety.test.ts tests/unit/progressRing.test.ts tests/unit/formsMigration.test.ts tests/unit/activeScanGuard.test.ts tests/unit/navShells.test.ts tests/unit/navigation.test.ts tests/unit/tutorStudentView.test.ts && npx tsc --noEmit -p . && npm run check:copy && npm run check:native`. Backend source scanners: `PYTHONPATH=$(pwd) .venv/bin/pytest tests -q -k "lint" --co -q | head` to list them, then run the ones that scan `lemely/web` or `lemely/core`.
- [ ] **Step 4:** `graphify update .`
- [ ] **Step 5:** Commit: `git commit -S -m "refactor(web): remove the replaced class papers and grading screens" -- <deleted and edited paths>`.

### Task 18: Push and PR

- [ ] **Step 1:** Rebase on `origin/develop`; re-run Task 17 Step 3's commands and the lane's pytest files (`tests/test_class_exams_core.py tests/test_exam_cells_repo.py tests/test_web_class_exams.py tests/test_web_student_detail_redesign.py tests/test_web_teacher.py tests/test_web_classes.py tests/test_student_detail_view.py`).
- [ ] **Step 2:** `PYTHONPATH=$(pwd) pre-commit run --files $(git diff --name-only origin/develop...HEAD)`; fix, commit with explicit paths.
- [ ] **Step 3:** `git push -u origin redesign/l08-teacher-papers`.
- [ ] **Step 4:** `gh pr create --base develop --title "feat: teacher papers, heatmap and StudentDetail redesign (L8)"` with a body containing: the ticked keep-list, the frame-to-state table, the side-by-side screenshot pairs (attached), the small fixes made versus the mock (panel fade, histogram height transition, heatmap cell height note, dropped Q1 interpretive sentence, dropped sample-set and invite links), and the "Needs user decision" outcomes.
- [ ] **Step 5:** Request the Opus review; fix; wait for green CI; merge only per the master plan.

---

## Dependencies on other lanes

- **F1 (beyond the master plan):** `Binny` needs a head-crop rendering for teacher screens (the master contract has `size` and `motion` only). Until F1 confirms, Task 8 renders `<Binny mood="open" size={56} motion="none" />`; if F1 adds a `crop="head"` prop, pass it.
- **L5 (beyond "L5 merges first"):** Task 15 relies on L5's planned exports from `review/index.ts` (`AnswerPanel`, `AnswerPage`, `type AnswerView`, `useAnswerImages`) keeping the shapes in L5's plan, Task 9. L5's crop and whole-page routes are keyed by review item, so only answers with an open review item show a scan in L8. If L5 changes `AnswerView`, only `papers/paperAnswerView.ts` changes.
- **L6:** `MarkPapersConsole` is the interim "Mark papers" target. When L6 ships the teacher upload flow, L6 repoints `/teacher/grading` and deletes `papers/MarkPapersConsole.tsx` (that file moves to L6's ownership at that point).
- **L12:** the needs strip shows only "answers to review" today. "Names to confirm" and "Marking stopped · Start again", and the "Marking · 11 of 28" exam tile, need L12's class-set cover reading and a class-scoped marking run status; `NeedsItem` and `ClassExamTile` are where L12 adds them.

## Needs user decision

- **D1 · The Grading console.** The mock has no upload console; "Mark papers" leads to L6's upload flow. Recommendation: keep today's console intact at `/teacher/grading` as `MarkPapersConsole` (every Grading feature kept) until L6 replaces it, rather than rebuilding upload in L8.
- **D2 · Top-level Papers.** The mock rail has "Papers" but no frame for a teacher with several classes. Recommendation: rename the "Grading" tab to "Papers" (`/teacher/papers`), show class tiles in the E3 tile style, and skip straight to the class when there is only one.
- **D3 · Teacher Binny head crop.** Needs an F1 prop. Recommendation: F1 adds `crop="head"`; L8 uses it on the class first-run card only.
- **D4 · Message parent.** No teacher-to-parent messaging exists. Recommendation: leave the button and the phone message icon out until a messaging route exists, rather than shipping a disabled "Coming soon" control.
- **D5 · Assign practice.** No topic-practice assignment exists; quizzes do. Recommendation: every "Assign practice" opens the new-quiz flow (`/teacher/quizzes?new=1`); a prefilled topic waits for a quiz-builder parameter.
- **D6 · "Not currently flagged" chip.** The mock shows nothing when a student isn't at risk. Recommendation: drop the chip (calmer), keep the at-risk banner.
- **D7 · Sample class set, Invite to upload, and "challenges" stat.** None has a backend. Recommendation: leave out the "Try it with a sample class set" link, the "Invite Omar to upload" button and the "challenges" count (replaced by "last active").
- **D8 · Remarking from the papers screens.** L5 shares its panel read-only, and scans are served per review item. Recommendation: in the heatmap, question view and student paper, show the answer read-only, with "Review this answer" into the queue when it has an open item. Remarking any answer in place (and showing scans for answers not in the queue) needs a crop and remark route keyed by question result, which is a follow-up for L5 or a later lane.
- **D9 · Heatmap cell size vs the 44px tap floor.** Approved cells are 52×38. Recommendation: keep 38px (approved airiness); column headers are 44px and every answer is also reachable from the question view and by keyboard.
