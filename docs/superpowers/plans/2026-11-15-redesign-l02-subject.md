# Redesign L2: Subject Screen Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the live student Subject screen (`web/src/portals/student/screens/Subject.tsx`) with the approved redesign: the steps path per paper up to the real A* line (Paper 4 / Paper 2 switch), the trend line, Binny's tip, "More marks to win", topic chips with secure topics folded, papers, and the first-run, sparse, loading and error states on phone, tablet and desktop.

**Architecture:** The existing `GET /api/student/subject/{code}` is extended in place (no new route). Each paper card gains its attempts in marks, a per-paper goal line resolved from the `component_thresholds` boundary table through the existing `GradeBoundaryStore`, and each topic gains a numeric accuracy and "marks to win". The frontend keeps the existing `useSubject` hook and adds one pure view-model module that makes every decision (state, copy, Binny mood, links, bar heights). The screen is a thin container plus focused section files in a new `screens/subject/` directory, styled by one co-located `subject.css` ported from the mock.

**Tech Stack:** FastAPI + Pydantic DTOs (`lemely/web/schemas_student.py`), pytest; React 19, react-router 7, TanStack Query, Tailwind 4, the F1 kit (`web/src/components/redesign`), Vitest (node environment, `renderToStaticMarkup` for components), Playwright.

**Spec:** `docs/superpowers/specs/2026-11-14-redesign-implementation-design.md` (Wave 1, item 2). **Master plan:** `docs/superpowers/plans/2026-11-15-redesign-00-master.md`.

**Mocks:** `.impeccable/mocks/student-r2/final.html` + `sjf.js` + `t.css` (the "subject final" block, lines 461–569) + `base.css` (tokens). Earlier rounds `subject3.html` / `sj2.js` are context only. `states-r1/` has **no Subject frames** (it covers the review queue, student result and upload); the Subject first-run and sparse frames live in `final.html` itself (`Z_P`, `Z_D`, `S_P`).

## Global Constraints

Inherits master plan Global Constraints (`2026-11-15-redesign-00-master.md` § Global Constraints) verbatim. Lane-specific additions:

- **Owned files:** `web/src/portals/student/screens/Subject.tsx` and the new directory `web/src/portals/student/screens/subject/`. New backend module `lemely/web/subject_paths.py`. New test files `tests/test_subject_paths.py`, `tests/test_web_student_subject_path.py`, `web/tests/unit/subjectModel.test.ts`, `web/tests/unit/subjectScreen.test.ts`, `web/e2e/subject.spec.ts`.
- **Narrow edits outside owned files:** only the `student_subject` function body and one import line in `lemely/web/routers/student.py`; only the `# ── Subject ──` section of `lemely/web/schemas_student.py`; only the `// ── Subject ──` section of `web/src/lib/studentTypes.ts`; the four source-scanning unit tests named in Task 8. L1 edits the Overview parts of the same three files, so rebase on `develop` before merge and resolve by keeping both sections.
- **Additive API only:** existing `SubjectDTO` fields stay and keep their meaning. The 404 for "no grade-bearing papers" stays (the frontend turns it into first run). Role stays `require_role(Role.student)`; identity stays `auth.user_id`.
- **Copy gate:** `npm run check:copy` bans `!` and em dashes in product copy under `web/src`. The mock's Binny lines end in `!`; this plan ships them without it (see Needs user decision 1). Curly apostrophes (`’`) as in the mock.
- **Units:** marks are the only unit on this screen (approved decision). No percentages on bars, rows or the trend line. Topic chips keep their accuracy percent (it is what the mock shows and what the live topic map shows).
- **Styling:** mock values go in `web/src/portals/student/screens/subject/subject.css` as `sj-*` classes built only from `index.css` roles (`--md-*`, `--grade-*`, `--font-*`, `--ease-out`) and `color-mix()` of two roles, the same pattern as `web/src/portals/teacher/home/home.css`. No raw colours, no new tokens, no arbitrary `text-[NNpx]` utilities.
- **Breakpoints (from the mock):** phone `< 768px` one column; tablet `768–1279px` two columns `1.1fr / 1fr`, gap 32px; desktop `>= 1280px` two columns `1.05fr / 1fr`, gap 48px.
- **Binny:** at most once per screen (tip on full, sparse and first run; the error Binny on error; none while loading).

### Token map (mock `base.css` / `t.css` → app `index.css`)

| Mock | App role | Note |
|---|---|---|
| `--p` `#042f4f` | `--md-primary` | |
| `--pc` | `--md-primary-container` | |
| `--v` | `--md-on-surface-variant` | |
| `--ink` | `--md-on-surface` | |
| `--o` / `oklch(.88 .012 240)` | `--md-outline` | path baseline |
| `--ov` | `--md-outline-variant` | hairlines, ghost outlines |
| `--sh` | `--md-surface-container-high` | toggle track |
| `--l`, `#fff` | `--md-surface-container-lowest` | toggle thumb, bubble |
| `--errc` / `--onerrc` | `--md-error-container` / `--md-on-error-container` | "Work on" chip (F1 owns) |
| `--ga --gA --gB --gC --gD --gE --gU` | `--grade-a-star --grade-a --grade-b --grade-c --grade-d --grade-e --grade-u` | identical values |
| `--gat` (goal fill) | `color-mix(in oklch, var(--grade-a-star) 12%, var(--md-surface-container-lowest))` | |
| `--gal` (goal edge) | `color-mix(in oklch, var(--grade-a-star) 35%, var(--md-surface-container-lowest))` | |
| `--ease` `cubic-bezier(.2,.8,.2,1)` | `--ease-out` | identical value |
| `'Bricolage Grotesque'` | `--font-display` | |
| `'Schibsted Grotesk'` | `--font-sans` | |
| `'JetBrains Mono'` | `--font-mono` | |

---

## Keep-list (live screen and endpoint)

Every row is checked off in Task 11 and copied into the PR body.

| # | Live feature, state or rule | Source | Where it lives after L2 |
|---|---|---|---|
| K1 | Route `student/subject/:code`, code from the route param, lazy import of `Subject` | `web/src/portals/student/index.tsx:31,245-248`, `Subject.tsx:56` | unchanged route; `Subject.tsx` stays the export |
| K2 | 404 = "nothing recorded yet", not an error, with one action to the upload route | `Subject.tsx:76-90` | first-run state (`Z_P`/`Z_D`), action "Scan a {name} paper" to `/student/correct?subject={code}` |
| K3 | The page identifies itself (an `h1`) in every state, including 404, pending and error | `Subject.tsx:82,96` | `SubjectHeader` renders `PageHeading` in every state |
| K4 | Loading skeleton | `Subject.tsx:97-102` | `SubjectLoading` (`L_P`) |
| K5 | Generic error with a retry that refetches, and the student failure message | `Subject.tsx:103`, `QueryState` | `SubjectError` (`E_P`) with "Try again" calling `query.refetch()` |
| K6 | Subject name primary, "level · code" secondary via `subjectIdentifier` + `useReference` | `Subject.tsx:64,107-112,136-138` | `SubjectHeader` title + subtitle (adds tier: "IGCSE · 0580 · Extended") |
| K7 | Forecast grade from the weighted mean against the latest paper's boundaries | `Subject.tsx:154`, `routers/student.py:406-410,481` | trend line "Heading for an A" (`header.forecast`) |
| K8 | Change since first paper, tone from its sign (a decline is never shown in success colour) | `Subject.tsx:114-118,163-165` | trend line "up N marks / down N marks / level since {month}", per paper, in marks; no success colour anywhere |
| K9 | Weighted mean percentage | `Subject.tsx:157-166` | dropped: approved decision "marks are the only unit" (Needs user decision 9 confirms) |
| K10 | Intro line "N papers corrected." | `Subject.tsx:143-145` | dropped: approved decision "intro paragraph dropped"; the count survives as "All N papers" |
| K11 | One breakdown per paper number, one bar per attempt, latest highlighted | `Subject.tsx:170-226`, `routers/student.py:412-441` | steps path per paper with the Paper 4 / Paper 2 switch; latest bar solid grade colour |
| K12 | Predicted boundary and position per paper (boundary was always `""`) | `Subject.tsx:208-224`, `routers/student.py:435` | goal block "68/80 A* line · 7 to go" from the real boundary table; `boundary` string now filled |
| K13 | Paper history newest first, each row opens `/student/result/{id}` | `Subject.tsx:229-251` | Papers rows (`HairRow`, `to=/student/result/{id}`), newest first |
| K14 | History row id is the index into the FULL history (round-trips to the result route) | `routers/student.py:398-401,458`, `tests/test_web_student.py:600-625` | unchanged; attempts reuse the same index |
| K15 | Topic map: accuracy per syllabus unit, weakest first, weak highlighted, no invented denominator | `Subject.tsx:253-280`, `routers/student.py:443-452` | topic chips with `%`, three states, weakest first |
| K16 | Topic map includes quiz evidence; every paper claim (bars, boundary, forecast, history) is grade-bearing only | `routers/student.py:385-391,401,443` | unchanged; `marksToWin` also counts grade-bearing papers only |
| K17 | 404 when the subject has history but only quizzes | `routers/student.py:403-404` | unchanged → first run |
| K18 | Enrolment lookup failure (`ValueError`, malformed id) still returns 200 | `routers/student.py:470-474`, `tests/test_web_student.py:491-519` | unchanged |
| K19 | Student role only; identity from `auth.user_id` | `routers/student.py:375`, `tests/test_authz_matrix*.py` | unchanged |
| K20 | Shell title for the route is the subject name | `web/src/portals/student/data.ts:263-265` | unchanged |
| K21 | `EmptyGradeBoundaryStoreError` surfaces as the app's 503, never as invented boundaries | `lemely/io/grade_boundaries.py:200-205` | unchanged (store is still the only boundary source) |
| K22 | RTL-safe classes (`text-start/end`, logical props) | `web/tests/unit/rtlSafety.test.ts:26` | new files added to that list; `subject.css` uses logical properties |
| K23 | Only token-backed utilities | `web/tests/unit/utilityExistence.test.ts:52` | new files added to that list |
| K24 | `SubjectGlyph` beside the name | `Subject.tsx:140`, `web/tests/unit/subjectGlyph.test.ts:96-98` | dropped: the approved mock has no glyph (Needs user decision 8); test assertion removed |
| K25 | Stat tiles opt out of native bleed | `Subject.tsx:148,157`, `web/tests/unit/listGroup.test.ts:170-173` | tiles no longer exist; test assertion removed |
| K26 | Pull-to-refresh refetches the page's queries | `components/shell/ShellPullToRefresh.tsx` | unchanged (shell-owned) |

## File structure

| File | Responsibility |
|---|---|
| `lemely/web/subject_paths.py` (new) | Pure helpers: session and paper labels, the goal line from a boundary map, attempt DTOs, marks to win per topic |
| `lemely/web/schemas_student.py` (Subject section) | `GoalLineDTO`, `PaperAttemptDTO`; new fields on `PaperBreakdownDTO`, `PaperHistoryRowDTO`, `TopicTileDTO` |
| `lemely/web/routers/student.py` (`student_subject`) | Resolve a boundary per paper, fill the new fields |
| `web/src/lib/studentTypes.ts` (Subject section) | Mirrors the DTO additions |
| `web/src/portals/student/screens/subject/subjectModel.ts` | Every decision: state, steps, trend, tip, win rows, chips, papers, subtitle, countdown, links |
| `web/src/portals/student/screens/subject/fixtures.ts` | The mock's Mathematics data as a `Subject` DTO, for tests |
| `web/src/portals/student/screens/subject/useMinWidth.ts` | `matchMedia` hook for the two layout breakpoints |
| `web/src/portals/student/screens/subject/subject.css` | Mock CSS ported to roles |
| `web/src/portals/student/screens/subject/SubjectSteps.tsx` | The steps bars, labels and goal block (real and ghost) |
| `web/src/portals/student/screens/subject/PathSection.tsx` | "Your path to A*", paper switch, steps, trend line, goal note |
| `web/src/portals/student/screens/subject/TipSection.tsx` | Binny line plus the big action button (and optional secondary link) |
| `web/src/portals/student/screens/subject/WinList.tsx` | "More marks to win" rows with practice and flashcard targets |
| `web/src/portals/student/screens/subject/TopicsSection.tsx` | Topic chips, legend, hint |
| `web/src/portals/student/screens/subject/PapersList.tsx` | Papers rows and "All N papers" |
| `web/src/portals/student/screens/subject/SubjectHeader.tsx` | `h1`, subtitle, countdown pill |
| `web/src/portals/student/screens/subject/SubjectBody.tsx` | Full and sparse layout (two columns from 768px) |
| `web/src/portals/student/screens/subject/SubjectFirstRun.tsx` | First-run state |
| `web/src/portals/student/screens/subject/SubjectLoading.tsx` | Loading skeleton |
| `web/src/portals/student/screens/subject/SubjectError.tsx` | Error state |
| `web/src/portals/student/screens/Subject.tsx` (rewritten) | Container: queries, state selection, wiring |

## Frame-to-state table

| Mock frame id | Component state | Breakpoint | Trigger |
|---|---|---|---|
| `F_P` | `full` → `SubjectBody` one column: path, tip, win, topics (secure folded), papers (4) | phone `< 768` | `GET /student/subject/{code}` 200 with `paperHistory.length >= 2` |
| `F_P` toggle | same, other paper selected; bars remount and replay the grow animation | phone | tap a `Paper N` tab (or arrow keys); `?paper=N` written with `replace` |
| `F_T` | `full` two columns: left path, tip (Binny 64), win; right topics (secure folded), papers (4) | tablet 768–1279 | as `F_P` |
| `F_D` | `full` two columns: left path, tip (Binny 72), win; right topics (all unfolded), papers (5) | desktop `>= 1280` | as `F_P` |
| `Z_P` | `first-run`: ghost path, Binny "Let’s find your first step" + "Scan a {name} paper" + "Upload a PDF instead", walkthrough (3 steps) | phone | 404 from the endpoint, or 200 with zero papers |
| `Z_D` | `first-run` two columns: left as `Z_P` (Binny 72); right Topics hint + 8 ghost chips, Papers hint | desktop | as `Z_P` |
| (no frame) | `first-run` tablet: `Z_D` layout with tablet columns, Binny 64 | tablet | as `Z_P` |
| `S_P` | `sparse`: steps with 1 bar + 3 ghost "next" slots + goal, "One step so far. Two more papers show your trend.", Binny "Great start. Next paper?" + "Scan your next paper", "Marks to win" (top 2), topics unfolded + "4 of 10 topics so far. Each paper fills in more.", Papers (1 row) | phone | 200 with `paperHistory.length === 1` |
| (no frame) | `sparse` tablet/desktop: same sections in the `F_T`/`F_D` two-column split | tablet, desktop | as `S_P` |
| `L_P` | `loading`: header, 150×22 title bar, 5 skeleton bars (38/50/56/84/100%), a 50px block, three 52px rows | phone | query `pending` |
| (no frame) | `loading` two columns: left as `L_P`, right three 52px rows | tablet, desktop | query `pending` |
| `E_P` | `error`: Binny sad 96, "We couldn’t load {name}", body, "Try again", "Back to Home" | all (centred column, max 300px button) | query `error` with status other than 404 |

## Interactions and motion

| Interaction / animation | Exact values (from `t.css`, `sjf.js`) | Reduced-motion fallback |
|---|---|---|
| Steps bars grow in | `animation: sj-grow .7s var(--ease-out) both`, `@keyframes sj-grow { from { transform: scaleY(.4) } }`, `transform-origin: bottom`; delays by child: 2nd `.06s`, 3rd `.12s`, 4th `.18s`, 5th `.26s` | `animation: none` |
| Paper switch | tablist; the selected tab gets the white thumb `0 1px 3px` shadow; the panel remounts (`key={paperNumber}`) so the grow animation replays; ArrowLeft/ArrowRight move selection (mirrored under `dir="rtl"`) | thumb change only; no grow |
| Bar hover (pointer devices) | `transition: translate .2s var(--ease-out), filter .2s`; hover `translate: 0 -3px; filter: saturate(1.15)` inside `@media (hover: hover)` | `translate: none`, no transition |
| Topic chip hover | F1 `TopicChip` owns: `translate 0 -2px`, `.2s var(--ease-out)` | F1 owns: none |
| Press feedback (pill, heading links, rows, buttons) | `scale(.97)` on `:active` via the app's `lm-press lm-press-scale` | already reduced by `lm-press` rules |
| Win row / paper row hover | row title turns `--md-primary` (`.sj-wmain:hover .sj-at b`), HairRow hover owned by F1 | colour only (no motion) |
| Skeleton shimmer | existing `SkeletonBlock` shimmer (mock: `skm 1.4s linear infinite`) | existing kit rule stops it |
| Binny | F1 `Binny` owns mood motion (mock: happy `hop 1.1s cubic-bezier(.3,.7,.4,1) infinite`, sad `sway 4s ease-in-out infinite`, base `bob 3.2s ease-in-out infinite`, blink `4.6s`, ears `5s`) | F1: every motion becomes `none` |
| Goal block tap | toggles the goal note ("A* line from the May/Jun 2024 boundary.") below the trend line, `aria-expanded` | no motion involved |
| "All N papers" | expands the list in place; focus stays on the list | no motion involved |

---

## Task 1: Backend helpers for the steps path

**Files:**
- Create: `lemely/web/subject_paths.py`
- Modify: `lemely/web/schemas_student.py` (Subject section, after `PaperBarDTO`)
- Test: `tests/test_subject_paths.py`

**Interfaces:**
- Consumes: `PaperRecord`, `is_grade_bearing` (`lemely/core/history.py`), `ExamMetadata` (`lemely/core/schemas.py`), `BoundarySource` (`lemely/io/grade_boundaries.py`).
- Produces (used by Task 2):
  - `GoalLineDTO(grade: str, marks: int, outOf: int, source: Literal["exact","subject_default","global_default"], sourceLabel: str)`
  - `PaperAttemptDTO(id: str, recordedAt: str, grade: str, awarded: int, maximum: int, label: str)`
  - `GOAL_GRADE: str = "A*"`
  - `session_label(metadata: ExamMetadata) -> str` → `"May/Jun 2024"`
  - `paper_code_label(metadata: ExamMetadata) -> str` → `"0580/42 · May/Jun 2024"`
  - `goal_line(boundaries: dict[str, float], source: BoundarySource, metadata: ExamMetadata, maximum: int) -> GoalLineDTO | None`
  - `attempt_dto(index: int, record: PaperRecord) -> PaperAttemptDTO`
  - `marks_to_win(records: list[PaperRecord]) -> dict[str, int]`

- [ ] **Step 1: Write the failing test**

Create `tests/test_subject_paths.py`:

```python
"""Pure helpers behind the Subject screen's steps path (redesign L2)."""

from __future__ import annotations

from lemely.core.history import PaperRecord
from lemely.core.schemas import ExamMetadata, WeakArea
from lemely.web.subject_paths import (
    GOAL_GRADE,
    attempt_dto,
    goal_line,
    marks_to_win,
    paper_code_label,
    session_label,
)


def _meta(
    *, paper: int = 4, variant: int = 2, month: str = "May/June", year: int | None = 2024
) -> ExamMetadata:
    return ExamMetadata(
        subject_code="0580",
        paper_number=paper,
        paper_variant=variant,
        session_month=month,  # type: ignore[arg-type]
        session_year=year,
    )


def _weak(topic: str, lost: int, maximum: int) -> WeakArea:
    return WeakArea(
        topic=topic,
        lost_marks=lost,
        maximum_marks=maximum,
        accuracy=round(1.0 - lost / maximum, 4),
        question_ids=["q1"],
    )


def _record(
    *,
    awarded: int = 61,
    maximum: int = 80,
    grade: str = "A",
    weak: list[WeakArea] | None = None,
    origin: str = "past_paper",
    recorded_at: str = "2024-04-15T10:00:00+00:00",
) -> PaperRecord:
    return PaperRecord(
        student_id="maya",
        metadata=_meta(),
        awarded_marks=awarded,
        maximum_marks=maximum,
        percentage=round(awarded / maximum * 100.0, 2),
        grade=grade,
        weak_areas=weak or [],
        recorded_at=recorded_at,
        origin=origin,  # type: ignore[arg-type]
    )


def test_session_label_shortens_the_month_and_keeps_the_year() -> None:
    assert session_label(_meta(month="May/June", year=2024)) == "May/Jun 2024"
    assert session_label(_meta(month="Oct/Nov", year=2023)) == "Oct/Nov 2023"
    assert session_label(_meta(month="Feb/Mar", year=2024)) == "Feb/Mar 2024"


def test_session_label_without_a_year_is_the_month_alone() -> None:
    assert session_label(_meta(month="Specimen", year=None)) == "Specimen"


def test_paper_code_label_is_code_paper_variant_then_session() -> None:
    assert paper_code_label(_meta(paper=4, variant=2)) == "0580/42 · May/Jun 2024"


def test_goal_line_is_the_a_star_line_in_raw_marks_for_an_exact_boundary() -> None:
    goal = goal_line({"A*": 85.0, "A": 72.0, "B": 60.0}, "exact", _meta(), 80)

    assert goal is not None
    assert goal.grade == GOAL_GRADE == "A*"
    assert goal.marks == 68  # 85% of 80
    assert goal.outOf == 80
    assert goal.source == "exact"
    assert goal.sourceLabel == "May/Jun 2024 boundary"


def test_goal_line_rounds_half_up_not_to_even() -> None:
    # 72.5% of 80 = 58.0; 85.625% of 80 = 68.5 -> 69 (Python's round() would give 68).
    goal = goal_line({"A*": 85.625}, "exact", _meta(), 80)
    assert goal is not None
    assert goal.marks == 69


def test_goal_line_falls_back_to_the_top_grade_when_the_paper_has_no_a_star() -> None:
    # A Core paper carries no A* (or A, or B) boundary; its top grade is C.
    goal = goal_line({"C": 60.0, "D": 45.0, "E": 30.0}, "subject_default", _meta(paper=1), 40)

    assert goal is not None
    assert goal.grade == "C"
    assert goal.marks == 24
    assert goal.sourceLabel == "Average of past boundaries"


def test_goal_line_labels_a_global_estimate_honestly() -> None:
    goal = goal_line({"A*": 80.0}, "global_default", _meta(), 80)
    assert goal is not None
    assert goal.sourceLabel == "Estimated boundary"


def test_goal_line_is_none_without_boundaries_or_marks() -> None:
    assert goal_line({}, "exact", _meta(), 80) is None
    assert goal_line({"A*": 85.0}, "exact", _meta(), 0) is None


def test_attempt_dto_carries_the_full_history_index_and_marks() -> None:
    dto = attempt_dto(6, _record(awarded=61, maximum=80, grade="A"))

    assert dto.id == "6"
    assert dto.awarded == 61
    assert dto.maximum == 80
    assert dto.grade == "A"
    assert dto.recordedAt == "2024-04-15T10:00:00+00:00"
    assert dto.label == "0580/42 · May/Jun 2024"


def test_marks_to_win_is_the_mean_marks_lost_per_paper_that_tested_the_topic() -> None:
    records = [
        _record(weak=[_weak("C2 Algebra", 6, 12), _weak("C7 Vectors", 9, 14)]),
        _record(weak=[_weak("C2 Algebra", 8, 12)]),
    ]

    assert marks_to_win(records) == {"C2 Algebra": 7, "C7 Vectors": 9}


def test_marks_to_win_ignores_quizzes_because_they_are_not_paper_marks() -> None:
    records = [
        _record(weak=[_weak("C2 Algebra", 4, 12)]),
        _record(weak=[_weak("C2 Algebra", 10, 10)], origin="quiz", grade=""),
    ]

    assert marks_to_win(records) == {"C2 Algebra": 4}


def test_marks_to_win_rounds_half_up() -> None:
    records = [
        _record(weak=[_weak("C5 Mensuration", 3, 10)]),
        _record(weak=[_weak("C5 Mensuration", 4, 10)]),
    ]

    assert marks_to_win(records) == {"C5 Mensuration": 4}  # mean 3.5 -> 4
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH="$PWD" /home/sico/Code/Lemely/.venv/bin/python -m pytest tests/test_subject_paths.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'lemely.web.subject_paths'`.

- [ ] **Step 3: Add the DTOs**

In `lemely/web/schemas_student.py`, insert directly after `class PaperBarDTO` (inside the `# ── Subject ──` section):

```python
class GoalLineDTO(ApiModel):
    """The goal block on one paper's steps path (redesign L2).

    ``grade`` is A* when the paper's boundary map carries one, else the paper's
    top grade (a Core paper tops out at C). ``marks`` is that grade's boundary
    in raw marks on the latest attempt's maximum, so it reads in the same unit
    as every bar beside it. ``source`` is the :class:`GradeBoundaryStore` rung
    that answered, and ``sourceLabel`` says it in words a student can check.
    """

    grade: str
    marks: int
    outOf: int
    source: Literal["exact", "subject_default", "global_default"]
    sourceLabel: str


class PaperAttemptDTO(ApiModel):
    """One grade-bearing attempt on a paper's steps path, oldest first.

    ``id`` is the index into the student's FULL history, the same addressing
    ``GET /api/student/result/{paper_id}`` uses (see ``PaperHistoryRowDTO``).
    """

    id: str
    recordedAt: str
    grade: str
    awarded: int
    maximum: int
    label: str
```

Check that `Literal` is already imported at the top of the file (`from typing import Literal`, line 23); it is.

- [ ] **Step 4: Write the helpers**

Create `lemely/web/subject_paths.py`:

```python
"""Pure helpers behind ``GET /api/student/subject/{code}``'s steps path (redesign L2).

Kept out of :mod:`lemely.web.routers.student` so every rule here is a plain
unit test with no app, store or database: the goal line from a boundary map,
the labels a student reads under each bar, and "marks to win" per topic.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import TYPE_CHECKING

from lemely.core.history import is_grade_bearing
from lemely.web.schemas_student import GoalLineDTO, PaperAttemptDTO

if TYPE_CHECKING:
    from lemely.core.history import PaperRecord
    from lemely.core.schemas import ExamMetadata
    from lemely.io.grade_boundaries import BoundarySource

GOAL_GRADE = "A*"

_SESSION_SHORT: dict[str, str] = {
    "May/June": "May/Jun",
    "Oct/Nov": "Oct/Nov",
    "Feb/Mar": "Feb/Mar",
    "Specimen": "Specimen",
}

_FALLBACK_SOURCE_LABEL: dict[str, str] = {
    "subject_default": "Average of past boundaries",
    "global_default": "Estimated boundary",
}


def _half_up(value: float) -> int:
    """Round half away from zero for non-negative values (``round`` rounds to even)."""
    return math.floor(value + 0.5)


def session_label(metadata: ExamMetadata) -> str:
    """``"May/Jun 2024"``; the short month alone when the session has no year."""
    short = _SESSION_SHORT[metadata.session_month]
    return f"{short} {metadata.session_year}" if metadata.session_year is not None else short


def paper_code_label(metadata: ExamMetadata) -> str:
    """``"0580/42 · May/Jun 2024"``: code, paper and variant, then the session."""
    return (
        f"{metadata.subject_code}/{metadata.paper_number}{metadata.paper_variant}"
        f" · {session_label(metadata)}"
    )


def goal_line(
    boundaries: dict[str, float],
    source: BoundarySource,
    metadata: ExamMetadata,
    maximum: int,
) -> GoalLineDTO | None:
    """The A* line (or the paper's top grade) in raw marks, or ``None``.

    ``boundaries`` is :meth:`GradeBoundaryStore.resolve`'s percentage map for
    the paper's latest attempt; ``maximum`` is that attempt's maximum marks.
    """
    if not boundaries or maximum <= 0:
        return None
    grade = GOAL_GRADE if GOAL_GRADE in boundaries else max(boundaries, key=boundaries.__getitem__)
    marks = _half_up(boundaries[grade] / 100.0 * maximum)
    label = (
        f"{session_label(metadata)} boundary"
        if source == "exact"
        else _FALLBACK_SOURCE_LABEL[source]
    )
    return GoalLineDTO(grade=grade, marks=marks, outOf=maximum, source=source, sourceLabel=label)


def attempt_dto(index: int, record: PaperRecord) -> PaperAttemptDTO:
    """One bar on the path. ``index`` is the record's FULL-history position."""
    return PaperAttemptDTO(
        id=str(index),
        recordedAt=record.recorded_at,
        grade=record.grade,
        awarded=record.awarded_marks,
        maximum=record.maximum_marks,
        label=paper_code_label(record.metadata),
    )


def marks_to_win(records: list[PaperRecord]) -> dict[str, int]:
    """Mean marks lost per paper on each topic, over the papers that tested it.

    Grade-bearing papers only: "+N marks" is a claim in paper marks, and a
    quiz's marks are on a different scale (``docs/quiz-model.md`` §5). A topic
    that only ever appeared in quizzes is absent (callers read it as 0).
    """
    lost: dict[str, list[int]] = defaultdict(list)
    for record in records:
        if not is_grade_bearing(record):
            continue
        for area in record.weak_areas:
            lost[area.topic].append(area.lost_marks)
    return {topic: _half_up(sum(values) / len(values)) for topic, values in lost.items()}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `PYTHONPATH="$PWD" /home/sico/Code/Lemely/.venv/bin/python -m pytest tests/test_subject_paths.py -q`
Expected: `13 passed`.

- [ ] **Step 6: Commit**

```bash
PYTHONPATH="$PWD" pre-commit run --files lemely/web/subject_paths.py lemely/web/schemas_student.py tests/test_subject_paths.py
git add lemely/web/subject_paths.py lemely/web/schemas_student.py tests/test_subject_paths.py
git commit -S -m "feat(student-api): goal line and marks-to-win helpers for the subject path" -- lemely/web/subject_paths.py lemely/web/schemas_student.py tests/test_subject_paths.py
```

---

## Task 2: Extend `GET /api/student/subject/{code}`

**Files:**
- Modify: `lemely/web/schemas_student.py` (`PaperBreakdownDTO`, `PaperHistoryRowDTO`, `TopicTileDTO`)
- Modify: `lemely/web/routers/student.py` (imports; `student_subject`, lines 372–491)
- Test: `tests/test_web_student_subject_path.py` (new; avoids L1's edits to `tests/test_web_student.py`)

**Interfaces:**
- Consumes: Task 1's `GoalLineDTO`, `PaperAttemptDTO`, `goal_line`, `attempt_dto`, `marks_to_win`, `paper_code_label`.
- Produces (wire contract for Task 3):
  - `PaperBreakdownDTO` adds `paperNumber: int`, `outOf: int`, `goal: GoalLineDTO | None`, `attempts: list[PaperAttemptDTO]`; `boundary` is now `"A* line 68/80"` (was always `""`).
  - `PaperHistoryRowDTO` adds `awarded: int`, `maximum: int`, `recordedAt: str`, `paperNumber: int`, `label: str`.
  - `TopicTileDTO` adds `accuracy: int` (0–100), `marksToWin: int`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_web_student_subject_path.py`:

```python
"""``GET /api/student/subject/{code}``: the redesign L2 additions.

The boundary store is replaced with a fixed fake so each assertion names the
exact boundary it was computed from; ``tests/test_web_student.py`` keeps the
real-store coverage of the fields that existed before.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from lemely.core.history import PaperRecord
from lemely.core.schemas import ExamMetadata, WeakArea
from lemely.io.history_store import HistoryStore
from lemely.web import create_app
from lemely.web.deps import (
    AuthContext,
    get_auth_context,
    get_history_store,
    get_student_profile_service,
)

if TYPE_CHECKING:
    from pathlib import Path

    from lemely.io.grade_boundaries import BoundarySource

STUDENT_ID = "maya"


class _FakeBoundaryStore:
    """Paper 4 resolves exactly, Paper 2 to the subject default."""

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        pass

    def resolve(self, metadata: ExamMetadata) -> tuple[dict[str, float], BoundarySource]:
        if metadata.paper_number == 4:
            return {"A*": 85.0, "A": 72.0, "B": 60.0, "C": 48.0}, "exact"
        return {"A*": 85.71, "A": 72.0, "B": 60.0}, "subject_default"


def _weak(topic: str, lost: int, maximum: int) -> WeakArea:
    return WeakArea(
        topic=topic,
        lost_marks=lost,
        maximum_marks=maximum,
        accuracy=round(1.0 - lost / maximum, 4),
        question_ids=["q1"],
    )


def _rec(
    *,
    paper: int,
    variant: int,
    awarded: int,
    maximum: int,
    grade: str,
    recorded_at: str,
    weak: list[WeakArea] | None = None,
    origin: str = "past_paper",
) -> PaperRecord:
    return PaperRecord(
        student_id=STUDENT_ID,
        metadata=ExamMetadata(
            subject_code="0580",
            paper_number=paper,
            paper_variant=variant,
            session_month="May/June",
            session_year=2024,
        ),
        awarded_marks=awarded,
        maximum_marks=maximum,
        percentage=round(awarded / maximum * 100.0, 2),
        grade=grade,
        weak_areas=weak or [],
        recorded_at=recorded_at,
        origin=origin,  # type: ignore[arg-type]
    )


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr("lemely.web.routers.student.GradeBoundaryStore", _FakeBoundaryStore)
    store = HistoryStore(tmp_path / "history")
    # Full-history indices: 0 P4, 1 P2, 2 quiz, 3 P4, 4 P2.
    store.append(STUDENT_ID, _rec(paper=4, variant=1, awarded=45, maximum=80, grade="C",
                                  recorded_at="2023-10-15T10:00:00+00:00",
                                  weak=[_weak("C7 Vectors", 10, 14), _weak("C2 Algebra", 6, 12)]))
    store.append(STUDENT_ID, _rec(paper=2, variant=2, awarded=44, maximum=70, grade="B",
                                  recorded_at="2023-11-15T10:00:00+00:00",
                                  weak=[_weak("C2 Algebra", 8, 12)]))
    store.append(STUDENT_ID, _rec(paper=1, variant=1, awarded=3, maximum=10, grade="",
                                  recorded_at="2023-12-15T10:00:00+00:00", origin="quiz",
                                  weak=[_weak("C9 Probability", 7, 10)]))
    store.append(STUDENT_ID, _rec(paper=4, variant=2, awarded=61, maximum=80, grade="A",
                                  recorded_at="2024-04-15T10:00:00+00:00",
                                  weak=[_weak("C7 Vectors", 8, 14)]))
    store.append(STUDENT_ID, _rec(paper=2, variant=1, awarded=53, maximum=70, grade="A",
                                  recorded_at="2024-03-15T10:00:00+00:00"))
    profile_service = MagicMock()
    profile_service.list_enrolments.return_value = []
    app = create_app()
    app.dependency_overrides[get_history_store] = lambda: store
    app.dependency_overrides[get_student_profile_service] = lambda: profile_service
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(
        user_id=STUDENT_ID, role="student"
    )
    return TestClient(app)


def _paper(body: dict, number: int) -> dict:
    return next(p for p in body["papersBreakdown"] if p["paperNumber"] == number)


def test_each_paper_carries_its_attempts_in_marks_oldest_first(client: TestClient) -> None:
    body = client.get("/api/student/subject/0580").json()

    p4 = _paper(body, 4)
    assert p4["outOf"] == 80
    assert [(a["id"], a["awarded"], a["maximum"], a["grade"]) for a in p4["attempts"]] == [
        ("0", 45, 80, "C"),
        ("3", 61, 80, "A"),
    ]
    assert p4["attempts"][-1]["label"] == "0580/42 · May/Jun 2024"
    assert p4["attempts"][0]["recordedAt"] == "2023-10-15T10:00:00+00:00"


def test_quizzes_never_become_attempts_or_papers(client: TestClient) -> None:
    body = client.get("/api/student/subject/0580").json()

    assert sorted(p["paperNumber"] for p in body["papersBreakdown"]) == [2, 4]
    ids = [a["id"] for p in body["papersBreakdown"] for a in p["attempts"]]
    assert "2" not in ids
    assert [row["id"] for row in body["paperHistory"]] == ["4", "3", "1", "0"]


def test_each_paper_has_its_own_goal_line_from_the_boundary_table(client: TestClient) -> None:
    body = client.get("/api/student/subject/0580").json()

    p4_goal = _paper(body, 4)["goal"]
    assert p4_goal == {
        "grade": "A*",
        "marks": 68,
        "outOf": 80,
        "source": "exact",
        "sourceLabel": "May/Jun 2024 boundary",
    }
    p2_goal = _paper(body, 2)["goal"]
    assert p2_goal["marks"] == 60  # 85.71% of 70 = 59.997
    assert p2_goal["sourceLabel"] == "Average of past boundaries"
    assert _paper(body, 4)["boundary"] == "A* line 68/80"


def test_history_rows_carry_structured_marks_and_labels(client: TestClient) -> None:
    row = client.get("/api/student/subject/0580").json()["paperHistory"][0]

    assert row["id"] == "4"
    assert row["awarded"] == 53
    assert row["maximum"] == 70
    assert row["paperNumber"] == 2
    assert row["recordedAt"] == "2024-03-15T10:00:00+00:00"
    assert row["label"] == "0580/21 · May/Jun 2024"
    assert row["marks"] == "53/70"  # the pre-existing field keeps its meaning


def test_topics_carry_numeric_accuracy_and_marks_to_win(client: TestClient) -> None:
    topics = {t["name"]: t for t in client.get("/api/student/subject/0580").json()["topicMap"]}

    # Vectors: lost 10/14 then 8/14 -> accuracy 1 - 18/28 = 36%; mean lost 9.
    assert topics["C7 Vectors"]["accuracy"] == 36
    assert topics["C7 Vectors"]["marksToWin"] == 9
    # Algebra: 6/12 on P4, 8/12 on P2 -> mean 7.
    assert topics["C2 Algebra"]["marksToWin"] == 7
    # Probability appears only in the quiz: on the map (K16), but no paper marks to win.
    assert topics["C9 Probability"]["accuracy"] == 30
    assert topics["C9 Probability"]["marksToWin"] == 0


def test_only_quizzes_is_still_a_404(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("lemely.web.routers.student.GradeBoundaryStore", _FakeBoundaryStore)
    store = HistoryStore(tmp_path / "history")
    store.append(STUDENT_ID, _rec(paper=1, variant=1, awarded=3, maximum=10, grade="",
                                  recorded_at="2024-01-15T10:00:00+00:00", origin="quiz"))
    app = create_app()
    app.dependency_overrides[get_history_store] = lambda: store
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(
        user_id=STUDENT_ID, role="student"
    )

    assert TestClient(app).get("/api/student/subject/0580").status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH="$PWD" /home/sico/Code/Lemely/.venv/bin/python -m pytest tests/test_web_student_subject_path.py -q`
Expected: FAIL with `KeyError: 'paperNumber'` (and missing-field failures) in the first five tests; `test_only_quizzes_is_still_a_404` passes already.

- [ ] **Step 3: Extend the DTOs**

In `lemely/web/schemas_student.py`, replace `PaperBreakdownDTO`, `PaperHistoryRowDTO` and `TopicTileDTO` with:

```python
class PaperBreakdownDTO(ApiModel):
    """Per-paper breakdown (mirrors ``PaperBreakdown``).

    ``title``/``sub``/``mean``/``position``/``positionOk``/``bars`` are the
    pre-redesign card fields, unchanged. Redesign L2 adds the steps path:
    ``attempts`` (grade-bearing, oldest first, in marks), ``outOf`` (the latest
    attempt's maximum) and ``goal`` (the A* line from the boundary table).
    ``boundary`` is now the goal in words, e.g. ``"A* line 68/80"``.
    """

    title: str
    sub: str
    mean: str
    boundary: str
    position: str
    positionOk: bool
    bars: list[PaperBarDTO]
    paperNumber: int
    outOf: int
    goal: GoalLineDTO | None
    attempts: list[PaperAttemptDTO]


class PaperHistoryRowDTO(ApiModel):
    """A row in the subject's paper history table (mirrors ``PaperHistoryRow``).

    ``id`` is the forward-position index into the student's full (unfiltered)
    :class:`~lemely.core.history.StudentHistory.records` — the same addressing
    scheme ``GET /api/student/result/{paper_id}`` uses — so a row can be passed
    straight through as ``paper_id`` to look up its full result.

    ``awarded``/``maximum``/``recordedAt``/``paperNumber``/``label`` (L2) are
    the structured form of ``marks``/``paper``, so the client never parses a
    display string.
    """

    id: str
    paper: str
    note: str
    marks: str
    pct: str
    grade: str
    gradeColor: VizColor
    tab: str
    awarded: int
    maximum: int
    recordedAt: str
    paperNumber: int
    label: str


class TopicTileDTO(ApiModel):
    """A tile in the topic map (mirrors ``TopicTile``).

    ``accuracy`` is ``acc`` as an integer 0–100. ``marksToWin`` is the mean
    marks lost per grade-bearing paper that tested the topic (0 when only a
    quiz did) — see :func:`lemely.web.subject_paths.marks_to_win`.
    """

    name: str
    acc: str
    color: VizColor
    weak: bool
    accuracy: int
    marksToWin: int
```

`GoalLineDTO` and `PaperAttemptDTO` (Task 1) sit above `PaperBreakdownDTO`, so no forward reference is needed.

- [ ] **Step 4: Wire the endpoint**

In `lemely/web/routers/student.py`, add after the existing `from lemely.web.schemas_student import (...)` block:

```python
from lemely.web.subject_paths import attempt_dto, goal_line, marks_to_win, paper_code_label
```

In `student_subject`, replace everything from the line `# One breakdown card per distinct paper number, each bar a recorded attempt.` down to the end of the `paper_history = [...]` list (currently lines 412–462) with:

```python
    # One breakdown per distinct paper number. Each attempt keeps its FULL-history
    # index (the result route's address); each paper resolves its own boundary
    # from its latest attempt, so Paper 2 and Paper 4 get their own A* lines.
    by_paper: dict[int, list[tuple[int, PaperRecord]]] = {}
    for index, record in indexed_records:
        by_paper.setdefault(record.metadata.paper_number, []).append((index, record))

    breakdowns: list[PaperBreakdownDTO] = []
    for paper_number, indexed_attempts in sorted(by_paper.items()):
        attempts = [record for _, record in indexed_attempts]
        bars = [
            PaperBarDTO(
                value=round(a.percentage),
                label=f"p{i + 1}",
                highlight=i == len(attempts) - 1,
            )
            for i, a in enumerate(attempts)
        ]
        mean_pct = round(sum(a.percentage for a in attempts) / len(attempts))
        latest = attempts[-1]
        paper_boundaries, paper_source = boundary_store.resolve(latest.metadata)
        goal = goal_line(paper_boundaries, paper_source, latest.metadata, latest.maximum_marks)
        breakdowns.append(
            PaperBreakdownDTO(
                title=f"Paper {paper_number}",
                sub=f"{latest.maximum_marks} marks",
                mean=f"{mean_pct}%",
                boundary=f"{goal.grade} line {goal.marks}/{goal.outOf}" if goal else "",
                position=f"{latest.awarded_marks}/{latest.maximum_marks} - {latest.grade}",
                positionOk=latest.grade in {"A*", "A", "B"},
                bars=bars,
                paperNumber=paper_number,
                outOf=latest.maximum_marks,
                goal=goal,
                attempts=[attempt_dto(index, record) for index, record in indexed_attempts],
            )
        )

    weaknesses = _subject_weaknesses([record for _, record in all_subject_records])
    to_win = marks_to_win(records)
    topic_map = [
        TopicTileDTO(
            name=area.topic,
            acc=f"{round(area.accuracy * 100.0)}%",
            color=_bar_color(area.accuracy * 100.0),
            weak=area.accuracy < 0.70,
            accuracy=round(area.accuracy * 100.0),
            marksToWin=to_win.get(area.topic, 0),
        )
        for area in sorted(weaknesses.weak_areas, key=lambda a: a.accuracy)
    ]

    paper_history = [
        PaperHistoryRowDTO(
            id=str(index),
            paper=_paper_label(record),
            note="",
            marks=f"{record.awarded_marks}/{record.maximum_marks}",
            pct=f"{round(record.percentage)}%",
            grade=record.grade,
            gradeColor=_bar_color(record.percentage),
            tab=f"p{record.metadata.paper_number}",
            awarded=record.awarded_marks,
            maximum=record.maximum_marks,
            recordedAt=record.recorded_at,
            paperNumber=record.metadata.paper_number,
            label=paper_code_label(record.metadata),
        )
        for index, record in reversed(indexed_records)
    ]
```

Leave the boundary-store construction, `pct`, `delta`, the header and the return unchanged. Update the docstring's first paragraph to add: "Each paper also carries its attempts in marks and its own A* line (redesign L2)."

- [ ] **Step 5: Run tests to verify they pass**

Run: `PYTHONPATH="$PWD" /home/sico/Code/Lemely/.venv/bin/python -m pytest tests/test_web_student_subject_path.py tests/test_subject_paths.py -q`
Expected: `19 passed`.

Then the pre-existing subject, quiz-origin and authz coverage (touched endpoint; these need the local test Postgres with ingested thresholds):

Run: `PYTHONPATH="$PWD" /home/sico/Code/Lemely/.venv/bin/python -m pytest tests/test_web_student.py -k subject tests/test_web_quiz_origin_filtering.py tests/test_authz_matrix.py tests/test_authz_matrix_complete.py -q`
Expected: all pass (the additions are additive).

- [ ] **Step 6: Commit**

```bash
PYTHONPATH="$PWD" pre-commit run --files lemely/web/schemas_student.py lemely/web/routers/student.py tests/test_web_student_subject_path.py
git add lemely/web/schemas_student.py lemely/web/routers/student.py tests/test_web_student_subject_path.py
git commit -S -m "feat(student-api): attempts, A* line and marks to win on the subject endpoint" -- lemely/web/schemas_student.py lemely/web/routers/student.py tests/test_web_student_subject_path.py
```

---

## Task 3: Frontend types and the core view model

**Files:**
- Modify: `web/src/lib/studentTypes.ts` (`// ── Subject ──` section, lines 75–133)
- Create: `web/src/portals/student/screens/subject/subjectModel.ts`
- Create: `web/src/portals/student/screens/subject/fixtures.ts`
- Test: `web/tests/unit/subjectModel.test.ts`

**Interfaces:**
- Consumes: Task 2's wire contract; `gradeTone` (`@/lib/grade`); `daysUntil` (`@/lib/countdown`); `StudentExamCalendar` (`@/lib/announcementTypes`); `CatalogueSubject` (`@/lib/referenceTypes`); F1 types `BinnyMood`, `TopicState` (`@/components/redesign`).
- Produces (used by Tasks 4–8):
  - `type SubjectScreenState = "loading" | "error" | "first-run" | "sparse" | "full"`
  - `selectScreenState(q: { status: "pending" | "error" | "success"; errorStatus: number | null; paperCount: number }): SubjectScreenState`
  - `links: { scan(code), upload(code), practice(code, topic?), flashcards(code, deckId), plan(code), result(id), home }`
  - `gradeColorVar(grade: string): string`, `gradeArticle(grade: string): "a" | "an"`, `monthLabel(iso: string): string`, `monthYearLabel(iso: string, now: Date): string`, `topicName(topic: string): string`, `plural(n: number, word: string): string`
  - `STEP_WINDOW = 4`, `SPARSE_GHOSTS = 3`, `barHeight(marks, outOf, line): number`
  - `interface StepBar`, `interface GoalStep`, `interface StepsView`, `stepsFor(paper: PaperBreakdown, opts?: { ghosts?: number }): StepsView`
  - `type TrendView`, `trendFor(paper: PaperBreakdown, forecast: string, subjectPaperCount: number): TrendView`
  - `interface PaperTab`, `paperTabs(papers): PaperTab[]`, `defaultPaper(papers): number | null`, `resolvePaper(papers, requested: string | null): number | null`
  - `interface PaperRowView`, `paperRows(history: PaperHistoryRow[], now: Date): PaperRowView[]`, `visiblePapers(count, wide, expanded): number`
  - `tierLabel(subject: CatalogueSubject | undefined, paperNumber: number | null): string | null`, `subtitleFor(secondary: string, tier: string | null): string`
  - `NEAR_EXAM_DAYS = 30`, `nextExamDate(calendar, code, now): string | null`
  - `MATHS: Subject` fixture (fixtures.ts), `MATHS_ONE: Subject` (sparse), `NOW: Date`

- [ ] **Step 1: Extend the TS types**

In `web/src/lib/studentTypes.ts`, inside the Subject section, add before `PaperBreakdown` and replace the three interfaces:

```ts
/** Which `GradeBoundaryStore` rung answered (mirrors `GoalLineDTO.source`). */
export type BoundarySource = "exact" | "subject_default" | "global_default"

/** The goal block on a paper's steps path (mirrors `GoalLineDTO`). */
export interface GoalLine {
  grade: string
  marks: number
  outOf: number
  source: BoundarySource
  sourceLabel: string
}

/** One grade-bearing attempt, oldest first (mirrors `PaperAttemptDTO`). `id`
 * addresses the same record `GET /student/result/{paperId}` looks up. */
export interface PaperAttempt {
  id: string
  recordedAt: string
  grade: string
  awarded: number
  maximum: number
  label: string
}

/** Per-paper breakdown (mirrors `PaperBreakdownDTO`). */
export interface PaperBreakdown {
  title: string
  sub: string
  mean: string
  boundary: string
  position: string
  positionOk: boolean
  bars: PaperBar[]
  paperNumber: number
  outOf: number
  goal: GoalLine | null
  attempts: PaperAttempt[]
}

/**
 * A row in the subject's paper history table (mirrors `PaperHistoryRowDTO`).
 * `id` addresses the same record `GET /student/result/{paperId}` looks up.
 */
export interface PaperHistoryRow {
  id: string
  paper: string
  note: string
  marks: string
  pct: string
  grade: string
  gradeColor: VizColor
  tab: string
  awarded: number
  maximum: number
  recordedAt: string
  paperNumber: number
  label: string
}

/** A tile in the topic map (mirrors `TopicTileDTO`). */
export interface TopicTile {
  name: string
  acc: string
  color: VizColor
  weak: boolean
  /** `acc` as an integer 0–100. */
  accuracy: number
  /** Mean marks lost per paper that tested the topic; 0 when only a quiz did. */
  marksToWin: number
}
```

- [ ] **Step 2: Write the fixtures**

Create `web/src/portals/student/screens/subject/fixtures.ts`:

```ts
/*
 * The approved mock's Mathematics data (`.impeccable/mocks/student-r2/sjf.js`)
 * as `Subject` DTOs. Tests only; dates are mid-month UTC so month labels are
 * the same in every time zone.
 */
import type { PaperAttempt, PaperHistoryRow, Subject, TopicTile } from "@/lib/studentTypes"

export const NOW = new Date(2024, 10, 20, 10, 0) // 2024-11-20 local

const at = (id: string, recordedAt: string, grade: string, awarded: number, maximum: number, label: string): PaperAttempt => ({
  id,
  recordedAt,
  grade,
  awarded,
  maximum,
  label,
})

const P4: PaperAttempt[] = [
  at("0", "2023-10-15T10:00:00+00:00", "C", 45, 80, "0580/41 · Oct/Nov 2023"),
  at("3", "2024-01-15T10:00:00+00:00", "B", 48, 80, "0580/43 · Oct/Nov 2023"),
  at("4", "2024-02-15T10:00:00+00:00", "B", 50, 80, "0580/42 · Feb/Mar 2024"),
  at("6", "2024-04-15T10:00:00+00:00", "A", 61, 80, "0580/42 · May/Jun 2024"),
]
const P2: PaperAttempt[] = [
  at("1", "2023-11-15T10:00:00+00:00", "B", 44, 70, "0580/22 · Oct/Nov 2023"),
  at("2", "2023-12-15T10:00:00+00:00", "B", 47, 70, "0580/22 · Oct/Nov 2023"),
  at("5", "2024-03-15T10:00:00+00:00", "A", 53, 70, "0580/21 · Feb/Mar 2024"),
]

const row = (a: PaperAttempt, paperNumber: number): PaperHistoryRow => ({
  id: a.id,
  paper: a.label,
  note: "",
  marks: `${a.awarded}/${a.maximum}`,
  pct: `${Math.round((a.awarded / a.maximum) * 100)}%`,
  grade: a.grade,
  gradeColor: "ok",
  tab: `p${paperNumber}`,
  awarded: a.awarded,
  maximum: a.maximum,
  recordedAt: a.recordedAt,
  paperNumber,
  label: a.label,
})

const topic = (name: string, accuracy: number, marksToWin: number): TopicTile => ({
  name,
  acc: `${accuracy}%`,
  color: accuracy >= 80 ? "ok" : accuracy >= 70 ? "accent" : "warn",
  weak: accuracy < 70,
  accuracy,
  marksToWin,
})

export const MATHS_TOPICS: TopicTile[] = [
  topic("C7 Vectors", 41, 9),
  topic("C2 Algebra", 58, 7),
  topic("C6 Trigonometry", 62, 5),
  topic("C5 Mensuration", 69, 4),
  topic("C3 Functions", 71, 3),
  topic("C9 Statistics", 74, 2),
  topic("C3.5 Coordinate geometry", 77, 1),
  topic("C4 Geometry", 80, 1),
  topic("C1 Number", 82, 1),
  topic("C8 Probability", 88, 1),
]

export const MATHS: Subject = {
  header: {
    name: "Mathematics",
    code: "0580",
    qualificationLevel: "igcse",
    intro: "7 papers corrected.",
    forecast: "A",
    weightedMean: "70",
    weightedMeanDelta: "+16 since first paper",
  },
  papersBreakdown: [
    {
      title: "Paper 2", sub: "70 marks", mean: "69%", boundary: "A* line 60/70", position: "53/70 - A", positionOk: true,
      bars: [], paperNumber: 2, outOf: 70, attempts: P2,
      goal: { grade: "A*", marks: 60, outOf: 70, source: "subject_default", sourceLabel: "Average of past boundaries" },
    },
    {
      title: "Paper 4", sub: "80 marks", mean: "64%", boundary: "A* line 68/80", position: "61/80 - A", positionOk: true,
      bars: [], paperNumber: 4, outOf: 80, attempts: P4,
      goal: { grade: "A*", marks: 68, outOf: 80, source: "exact", sourceLabel: "May/Jun 2024 boundary" },
    },
  ],
  topicMap: MATHS_TOPICS,
  paperHistory: [P4[3], P2[2], P4[2], P4[1], P2[1], P2[0], P4[0]].map((a) =>
    row(a, P4.includes(a) ? 4 : 2),
  ),
}

const ONE: PaperAttempt = at("0", "2024-04-15T10:00:00+00:00", "A", 61, 80, "0580/42 · May/Jun 2024")

export const MATHS_ONE: Subject = {
  ...MATHS,
  header: { ...MATHS.header, intro: "1 papers corrected.", weightedMeanDelta: "+0 since first paper" },
  papersBreakdown: [{ ...MATHS.papersBreakdown[1], attempts: [ONE] }],
  topicMap: [topic("C7 Vectors", 41, 9), topic("C2 Algebra", 58, 7), topic("C6 Trigonometry", 62, 5), topic("C1 Number", 82, 1)],
  paperHistory: [row(ONE, 4)],
}
```

- [ ] **Step 3: Write the failing test**

Create `web/tests/unit/subjectModel.test.ts`:

```ts
import { describe, expect, it } from "vitest"
import {
  barHeight,
  defaultPaper,
  gradeArticle,
  gradeColorVar,
  links,
  monthYearLabel,
  nextExamDate,
  paperRows,
  paperTabs,
  plural,
  resolvePaper,
  selectScreenState,
  stepsFor,
  subtitleFor,
  tierLabel,
  topicName,
  trendFor,
  visiblePapers,
} from "@/portals/student/screens/subject/subjectModel"
import { MATHS, MATHS_ONE, NOW } from "@/portals/student/screens/subject/fixtures"
import type { StudentExamCalendar } from "@/lib/announcementTypes"
import type { CatalogueSubject } from "@/lib/referenceTypes"

const p4 = MATHS.papersBreakdown.find((p) => p.paperNumber === 4)!
const p2 = MATHS.papersBreakdown.find((p) => p.paperNumber === 2)!

describe("selectScreenState", () => {
  it("is loading while pending", () => {
    expect(selectScreenState({ status: "pending", errorStatus: null, paperCount: 0 })).toBe("loading")
  })
  it("treats a 404 as first run, not an error (K2)", () => {
    expect(selectScreenState({ status: "error", errorStatus: 404, paperCount: 0 })).toBe("first-run")
  })
  it("treats any other failure as an error", () => {
    expect(selectScreenState({ status: "error", errorStatus: 500, paperCount: 0 })).toBe("error")
    expect(selectScreenState({ status: "error", errorStatus: null, paperCount: 0 })).toBe("error")
  })
  it("is first run on a 200 with no papers, sparse with one, full with two or more", () => {
    expect(selectScreenState({ status: "success", errorStatus: null, paperCount: 0 })).toBe("first-run")
    expect(selectScreenState({ status: "success", errorStatus: null, paperCount: 1 })).toBe("sparse")
    expect(selectScreenState({ status: "success", errorStatus: null, paperCount: 7 })).toBe("full")
  })
})

describe("small helpers", () => {
  it("maps grades to the grade tokens, unknown to U", () => {
    expect(gradeColorVar("A*")).toBe("var(--grade-a-star)")
    expect(gradeColorVar("B")).toBe("var(--grade-b)")
    expect(gradeColorVar("?")).toBe("var(--grade-u)")
  })
  it("picks the article a grade letter is read with", () => {
    expect(gradeArticle("A")).toBe("an")
    expect(gradeArticle("A*")).toBe("an")
    expect(gradeArticle("E")).toBe("an")
    expect(gradeArticle("F")).toBe("an")
    expect(gradeArticle("B")).toBe("a")
    expect(gradeArticle("U")).toBe("a")
  })
  it("strips the syllabus code from a topic label", () => {
    expect(topicName("C7 Vectors")).toBe("Vectors")
    expect(topicName("C3.5 Coordinate geometry")).toBe("Coordinate geometry")
    expect(topicName("Vectors")).toBe("Vectors")
    expect(topicName("unknown")).toBe("unknown")
  })
  it("pluralises marks", () => {
    expect(plural(1, "mark")).toBe("1 mark")
    expect(plural(7, "mark")).toBe("7 marks")
  })
  it("adds the year to a month only when it is not this year", () => {
    expect(monthYearLabel("2024-04-15T10:00:00+00:00", NOW)).toBe("Apr")
    expect(monthYearLabel("2023-10-15T10:00:00+00:00", NOW)).toBe("Oct 2023")
  })
  it("builds every link the screen uses", () => {
    expect(links.scan("0580")).toBe("/student/correct?subject=0580")
    expect(links.upload("0580")).toBe("/student/correct?subject=0580&source=file")
    expect(links.practice("0580")).toBe("/student/practice/0580")
    expect(links.practice("0580", "C7 Vectors")).toBe("/student/practice/0580?topic=C7%20Vectors")
    expect(links.flashcards("0580", "d1")).toBe("/student/flashcards/0580?deck=d1")
    expect(links.plan("0580")).toBe("/student/plan/0580")
    expect(links.result("6")).toBe("/student/result/6")
    expect(links.home).toBe("/student")
  })
})

describe("barHeight", () => {
  it("runs from 40% of the marks (0) to the A* line (100)", () => {
    expect(barHeight(32, 80, 68)).toBe(0)
    expect(barHeight(68, 80, 68)).toBe(100)
    expect(barHeight(61, 80, 68)).toBe(81)
    expect(barHeight(45, 80, 68)).toBe(36)
  })
  it("clamps below the floor and above the line", () => {
    expect(barHeight(10, 80, 68)).toBe(0)
    expect(barHeight(75, 80, 68)).toBe(100)
  })
  it("is full height when the line sits at or below the floor", () => {
    expect(barHeight(20, 80, 30)).toBe(100)
  })
})

describe("stepsFor", () => {
  it("draws the last four attempts with the latest one current", () => {
    const steps = stepsFor(p4)
    expect(steps.bars.map((b) => [b.grade, b.marks, b.month, b.heightPct, b.current])).toEqual([
      ["C", 45, "Oct", 36, false],
      ["B", 48, "Jan", 44, false],
      ["B", 50, "Feb", 50, false],
      ["A", 61, "Apr", 81, true],
    ])
    expect(steps.bars[3].resultTo).toBe("/student/result/6")
    expect(steps.bars[3].colorVar).toBe("var(--grade-a)")
    expect(steps.ghosts).toBe(0)
  })
  it("puts the real A* line and the gap in the goal block", () => {
    const goal = stepsFor(p4).goal!
    expect(goal).toMatchObject({ grade: "A*", marks: 68, outOf: 80, gap: 7, gapLabel: "7 to go" })
    expect(goal.sourceLabel).toBe("May/Jun 2024 boundary")
    expect(goal.ariaLabel).toBe("A* line, 68 out of 80. 7 marks to go")
  })
  it("says the line is reached once the latest attempt clears it", () => {
    const over = { ...p4, attempts: [...p4.attempts, { ...p4.attempts[3], id: "9", awarded: 70 }] }
    const goal = stepsFor(over).goal!
    expect(goal.gap).toBe(-2)
    expect(goal.gapLabel).toBe("Reached")
  })
  it("keeps only the last STEP_WINDOW attempts", () => {
    const many = { ...p4, attempts: [...p4.attempts, { ...p4.attempts[3], id: "9" }] }
    expect(stepsFor(many).bars.map((b) => b.id)).toEqual(["3", "4", "6", "9"])
  })
  it("adds ghost slots for the sparse path", () => {
    expect(stepsFor(MATHS_ONE.papersBreakdown[0], { ghosts: 3 }).ghosts).toBe(3)
  })
  it("describes the whole path for screen readers", () => {
    expect(stepsFor(p2).groupLabel).toBe(
      "Paper 2 marks so far: B, 44 out of 70 in Nov; B, 47 out of 70 in Dec; A, 53 out of 70 in Mar. The A* line is 60, 7 marks to go.",
    )
  })
  it("has no goal block when the paper has no boundary", () => {
    expect(stepsFor({ ...p4, goal: null }).goal).toBeNull()
  })
})

describe("trendFor", () => {
  it("carries the forecast and the change since the first attempt, in marks", () => {
    expect(trendFor(p4, "A", 7)).toEqual({
      kind: "trend",
      forecast: "A",
      article: "an",
      colorVar: "var(--grade-a)",
      change: "up 16 marks since Oct",
    })
    expect(trendFor(p2, "A", 7)).toMatchObject({ change: "up 9 marks since Nov" })
  })
  it("words a decline and no change plainly (K8)", () => {
    const down = { ...p4, attempts: [p4.attempts[3], { ...p4.attempts[0], recordedAt: "2024-05-15T10:00:00+00:00" }] }
    expect(trendFor(down, "B", 7)).toMatchObject({ change: "down 16 marks since Apr", article: "a" })
    const level = { ...p4, attempts: [p4.attempts[0], { ...p4.attempts[0], id: "8" }] }
    expect(trendFor(level, "C", 7)).toMatchObject({ change: "level since Oct" })
  })
  it("uses the sparse line when the subject has one paper", () => {
    expect(trendFor(MATHS_ONE.papersBreakdown[0], "A", 1)).toEqual({
      kind: "single",
      text: "One step so far. Two more papers show your trend.",
    })
  })
  it("names the paper when only this paper has a single attempt", () => {
    const single = { ...p2, attempts: [p2.attempts[0]] }
    expect(trendFor(single, "A", 5)).toEqual({ kind: "single", text: "One Paper 2 so far." })
  })
})

describe("paper switch", () => {
  it("orders tabs Paper 4 then Paper 2 like the mock", () => {
    expect(paperTabs(MATHS.papersBreakdown)).toEqual([
      { paperNumber: 4, name: "Paper 4" },
      { paperNumber: 2, name: "Paper 2" },
    ])
  })
  it("defaults to the paper with the most recent attempt", () => {
    expect(defaultPaper(MATHS.papersBreakdown)).toBe(4)
  })
  it("honours a valid ?paper= and ignores a bad one", () => {
    expect(resolvePaper(MATHS.papersBreakdown, "2")).toBe(2)
    expect(resolvePaper(MATHS.papersBreakdown, "7")).toBe(4)
    expect(resolvePaper(MATHS.papersBreakdown, null)).toBe(4)
    expect(resolvePaper([], null)).toBeNull()
  })
})

describe("papers", () => {
  it("builds rows newest first with marks and month, linking to the result (K13)", () => {
    const rows = paperRows(MATHS.paperHistory, NOW)
    expect(rows[0]).toEqual({
      id: "6",
      grade: "A",
      colorVar: "var(--grade-a)",
      title: "0580/42 · May/Jun 2024",
      sub: "61/80 · Apr",
      to: "/student/result/6",
    })
    expect(rows.at(-1)!.sub).toBe("45/80 · Oct 2023")
  })
  it("shows 4 rows below 1280px, 5 at desktop, all once expanded", () => {
    expect(visiblePapers(7, false, false)).toBe(4)
    expect(visiblePapers(7, true, false)).toBe(5)
    expect(visiblePapers(7, false, true)).toBe(7)
    expect(visiblePapers(2, true, false)).toBe(2)
  })
})

describe("header", () => {
  const catalogue: CatalogueSubject = {
    code: "0580",
    name: "Mathematics",
    board: "caie",
    qualificationLevel: "igcse",
    papers: [
      { number: 2, name: "Paper 2", tier: "extended", practical: false },
      { number: 1, name: "Paper 1", tier: "core", practical: false },
      { number: 9, name: "Paper 9", tier: null, practical: false },
    ],
    topics: [],
  }
  it("reads the tier of the selected paper", () => {
    expect(tierLabel(catalogue, 2)).toBe("Extended")
    expect(tierLabel(catalogue, 1)).toBe("Core")
    expect(tierLabel(catalogue, 9)).toBeNull()
    expect(tierLabel(undefined, 2)).toBeNull()
    expect(tierLabel(catalogue, null)).toBeNull()
  })
  it("joins level, code and tier", () => {
    expect(subtitleFor("IGCSE · 0580", "Extended")).toBe("IGCSE · 0580 · Extended")
    expect(subtitleFor("0580", null)).toBe("0580")
    expect(subtitleFor("", null)).toBe("")
  })
})

describe("nextExamDate", () => {
  const calendar = (dates: string[], availability: "dated" | "no_timetable" = "dated"): StudentExamCalendar => ({
    availability: "available",
    entries: [
      {
        subjectCode: "0580",
        sessionMonth: "may_june",
        sessionYear: 2025,
        paperNumber: 4,
        availability,
        dates: dates.map((examDate) => ({ paperVariant: "2", examDate, startsAtLocal: null, durationMinutes: 150, source: "CAIE" })),
      },
      {
        subjectCode: "0625",
        sessionMonth: "may_june",
        sessionYear: 2025,
        paperNumber: 4,
        availability: "dated",
        dates: [{ paperVariant: "2", examDate: "2024-11-25", startsAtLocal: null, durationMinutes: 75, source: "CAIE" }],
      },
    ],
  })
  it("is the earliest future date for this subject", () => {
    expect(nextExamDate(calendar(["2025-05-27", "2025-05-12"]), "0580", NOW)).toBe("2025-05-12")
  })
  it("skips past dates and undated papers, and is null without a calendar", () => {
    expect(nextExamDate(calendar(["2024-11-01"]), "0580", NOW)).toBeNull()
    expect(nextExamDate(calendar([], "no_timetable"), "0580", NOW)).toBeNull()
    expect(nextExamDate(undefined, "0580", NOW)).toBeNull()
  })
})
```

- [ ] **Step 4: Run test to verify it fails**

Run: `cd web && npx vitest run tests/unit/subjectModel.test.ts`
Expected: FAIL with `Failed to resolve import "@/portals/student/screens/subject/subjectModel"`.

- [ ] **Step 5: Write the core view model**

Create `web/src/portals/student/screens/subject/subjectModel.ts`:

```ts
/*
 * Subject screen decisions (redesign L2, mock `.impeccable/mocks/student-r2/sjf.js`).
 * Pure functions only: no React, no fetching, no clock reads (`now` is passed
 * in), so every branch is a unit test. The screen files only draw what this
 * module returns.
 */
import type { BinnyMood, TopicState } from "@/components/redesign"
import type { StudentExamCalendar } from "@/lib/announcementTypes"
import { daysUntil } from "@/lib/countdown"
import type { DeckSummaryDTO } from "@/lib/flashcardTypes"
import { gradeTone } from "@/lib/grade"
import type { CatalogueSubject } from "@/lib/referenceTypes"
import type { PaperBreakdown, PaperHistoryRow, Subject, TopicTile } from "@/lib/studentTypes"

/* ── State ─────────────────────────────────────────────────────────────── */

export type SubjectScreenState = "loading" | "error" | "first-run" | "sparse" | "full"

export interface QueryFacts {
  status: "pending" | "error" | "success"
  /** The HTTP status of an `ApiError`, else null. */
  errorStatus: number | null
  /** `paperHistory.length` (grade-bearing papers only, K16). */
  paperCount: number
}

/** A 404 is a subject with no papers yet, never a failure (K2). */
export function selectScreenState(q: QueryFacts): SubjectScreenState {
  if (q.status === "pending") return "loading"
  if (q.status === "error") return q.errorStatus === 404 ? "first-run" : "error"
  if (q.paperCount === 0) return "first-run"
  return q.paperCount === 1 ? "sparse" : "full"
}

/* ── Links ─────────────────────────────────────────────────────────────── */

const enc = encodeURIComponent

export const links = {
  scan: (code: string) => `/student/correct?subject=${enc(code)}`,
  upload: (code: string) => `/student/correct?subject=${enc(code)}&source=file`,
  practice: (code: string, topic?: string) =>
    topic ? `/student/practice/${enc(code)}?topic=${enc(topic)}` : `/student/practice/${enc(code)}`,
  flashcards: (code: string, deckId: string) => `/student/flashcards/${enc(code)}?deck=${enc(deckId)}`,
  plan: (code: string) => `/student/plan/${enc(code)}`,
  result: (id: string) => `/student/result/${enc(id)}`,
  home: "/student",
} as const

/* ── Small helpers ─────────────────────────────────────────────────────── */

export function gradeColorVar(grade: string): string {
  return `var(--grade-${gradeTone(grade) ?? "u"})`
}

export function gradeArticle(grade: string): "a" | "an" {
  return /^[AEF]/.test(grade.trim()) ? "an" : "a"
}

export function plural(n: number, word: string): string {
  return `${n} ${word}${n === 1 ? "" : "s"}`
}

const MONTH = new Intl.DateTimeFormat("en-US", { month: "short" })

export function monthLabel(iso: string): string {
  return MONTH.format(new Date(iso))
}

export function monthYearLabel(iso: string, now: Date): string {
  const d = new Date(iso)
  return d.getFullYear() === now.getFullYear() ? MONTH.format(d) : `${MONTH.format(d)} ${d.getFullYear()}`
}

/** `"C7 Vectors"` → `"Vectors"`: the weakness vocabulary is `"<code> <name>"`. */
export function topicName(topic: string): string {
  const match = /^(\S*\d\S*)\s+(.+)$/.exec(topic.trim())
  return match ? match[2] : topic.trim()
}

/* ── Steps path ────────────────────────────────────────────────────────── */

export const STEP_WINDOW = 4
export const SPARSE_GHOSTS = 3

/** Bars run from 40% of the marks (0) up to the A* line (100), clamped. */
export function barHeight(marks: number, outOf: number, line: number): number {
  const floor = outOf * 0.4
  if (line <= floor) return 100
  return Math.min(100, Math.max(0, Math.round(((marks - floor) / (line - floor)) * 100)))
}

export interface StepBar {
  id: string
  grade: string
  marks: number
  outOf: number
  month: string
  heightPct: number
  current: boolean
  colorVar: string
  ariaLabel: string
  resultTo: string
}

export interface GoalStep {
  grade: string
  marks: number
  outOf: number
  /** Marks from the latest attempt to the line; zero or negative once reached. */
  gap: number
  gapLabel: string
  sourceLabel: string
  ariaLabel: string
}

export interface StepsView {
  bars: StepBar[]
  ghosts: number
  goal: GoalStep | null
  groupLabel: string
}

export function stepsFor(paper: PaperBreakdown, { ghosts = 0 }: { ghosts?: number } = {}): StepsView {
  const shown = paper.attempts.slice(-STEP_WINDOW)
  const latest = paper.attempts.at(-1)
  const line = paper.goal?.marks ?? paper.outOf
  const bars: StepBar[] = shown.map((a, i) => {
    const month = monthLabel(a.recordedAt)
    return {
      id: a.id,
      grade: a.grade,
      marks: a.awarded,
      outOf: a.maximum,
      month,
      heightPct: barHeight(a.awarded, a.maximum, line),
      current: i === shown.length - 1,
      colorVar: gradeColorVar(a.grade),
      ariaLabel: `${a.grade}, ${a.awarded} out of ${a.maximum}, ${month}. Open this paper`,
      resultTo: links.result(a.id),
    }
  })
  let goal: GoalStep | null = null
  if (paper.goal && latest) {
    const gap = paper.goal.marks - latest.awarded
    goal = {
      grade: paper.goal.grade,
      marks: paper.goal.marks,
      outOf: paper.goal.outOf,
      gap,
      gapLabel: gap > 0 ? `${gap} to go` : "Reached",
      sourceLabel: paper.goal.sourceLabel,
      ariaLabel: `${paper.goal.grade} line, ${paper.goal.marks} out of ${paper.goal.outOf}. ${gap > 0 ? `${plural(gap, "mark")} to go` : "Reached"}`,
    }
  }
  const summary = bars.map((b) => `${b.grade}, ${b.marks} out of ${b.outOf} in ${b.month}`).join("; ")
  const goalText = goal
    ? ` The ${goal.grade} line is ${goal.marks}, ${goal.gap > 0 ? `${plural(goal.gap, "mark")} to go` : "reached"}.`
    : ""
  return { bars, ghosts, goal, groupLabel: `Paper ${paper.paperNumber} marks so far: ${summary}.${goalText}` }
}

/* ── Trend line (K7, K8) ───────────────────────────────────────────────── */

export type TrendView =
  | { kind: "trend"; forecast: string; article: "a" | "an"; colorVar: string; change: string }
  | { kind: "single"; text: string }

export function trendFor(paper: PaperBreakdown, forecast: string, subjectPaperCount: number): TrendView {
  const a = paper.attempts
  if (a.length < 2) {
    return {
      kind: "single",
      text: subjectPaperCount <= 1 ? "One step so far. Two more papers show your trend." : `One Paper ${paper.paperNumber} so far.`,
    }
  }
  const diff = a[a.length - 1].awarded - a[0].awarded
  const since = monthLabel(a[0].recordedAt)
  const change =
    diff > 0 ? `up ${plural(diff, "mark")} since ${since}` : diff < 0 ? `down ${plural(-diff, "mark")} since ${since}` : `level since ${since}`
  return { kind: "trend", forecast, article: gradeArticle(forecast), colorVar: gradeColorVar(forecast), change }
}

/* ── Paper switch ──────────────────────────────────────────────────────── */

export interface PaperTab {
  paperNumber: number
  name: string
}

export function paperTabs(papers: PaperBreakdown[]): PaperTab[] {
  return papers
    .filter((p) => p.attempts.length > 0)
    .sort((x, y) => y.paperNumber - x.paperNumber)
    .map((p) => ({ paperNumber: p.paperNumber, name: `Paper ${p.paperNumber}` }))
}

export function defaultPaper(papers: PaperBreakdown[]): number | null {
  let best: { n: number; t: number } | null = null
  for (const p of papers) {
    const last = p.attempts.at(-1)
    if (!last) continue
    const t = Date.parse(last.recordedAt)
    if (!best || t > best.t) best = { n: p.paperNumber, t }
  }
  return best?.n ?? null
}

export function resolvePaper(papers: PaperBreakdown[], requested: string | null): number | null {
  const n = Number(requested)
  return requested !== null && papers.some((p) => p.paperNumber === n && p.attempts.length > 0) ? n : defaultPaper(papers)
}

/* ── Papers (K13) ──────────────────────────────────────────────────────── */

export interface PaperRowView {
  id: string
  grade: string
  colorVar: string
  title: string
  sub: string
  to: string
}

export function paperRows(history: PaperHistoryRow[], now: Date): PaperRowView[] {
  return history.map((h) => ({
    id: h.id,
    grade: h.grade,
    colorVar: gradeColorVar(h.grade),
    title: h.label,
    sub: `${h.awarded}/${h.maximum} · ${monthYearLabel(h.recordedAt, now)}`,
    to: links.result(h.id),
  }))
}

export function visiblePapers(count: number, wide: boolean, expanded: boolean): number {
  return expanded ? count : Math.min(count, wide ? 5 : 4)
}

/* ── Header ────────────────────────────────────────────────────────────── */

export function tierLabel(subject: CatalogueSubject | undefined, paperNumber: number | null): string | null {
  if (paperNumber === null) return null
  const tier = subject?.papers.find((p) => p.number === paperNumber)?.tier
  return tier ? tier.charAt(0).toUpperCase() + tier.slice(1) : null
}

export function subtitleFor(secondary: string, tier: string | null): string {
  return [secondary || null, tier].filter(Boolean).join(" · ")
}

export const NEAR_EXAM_DAYS = 30

export function nextExamDate(calendar: StudentExamCalendar | undefined, code: string, now: Date): string | null {
  if (!calendar) return null
  const dates = calendar.entries
    .filter((e) => e.subjectCode === code && e.availability === "dated")
    .flatMap((e) => e.dates.map((d) => d.examDate))
    .filter((d) => daysUntil(d, now) >= 0)
    .sort()
  return dates[0] ?? null
}

/* Re-exported for Task 4's section of this module. */
export type { BinnyMood, DeckSummaryDTO, Subject, TopicState, TopicTile }
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd web && npx vitest run tests/unit/subjectModel.test.ts`
Expected: all tests pass.

- [ ] **Step 7: Typecheck and commit**

Run: `cd web && npm run typecheck`
Expected: exit 0. (The legacy `Subject.tsx` still compiles: it reads only fields that still exist.)

```bash
cd web && npx oxlint src/portals/student/screens/subject src/lib/studentTypes.ts tests/unit/subjectModel.test.ts && cd ..
PYTHONPATH="$PWD" pre-commit run --files web/src/lib/studentTypes.ts web/src/portals/student/screens/subject/subjectModel.ts web/src/portals/student/screens/subject/fixtures.ts web/tests/unit/subjectModel.test.ts
git add web/src/lib/studentTypes.ts web/src/portals/student/screens/subject/subjectModel.ts web/src/portals/student/screens/subject/fixtures.ts web/tests/unit/subjectModel.test.ts
git commit -S -m "feat(web): subject view model for steps, trend, papers and header" -- web/src/lib/studentTypes.ts web/src/portals/student/screens/subject/subjectModel.ts web/src/portals/student/screens/subject/fixtures.ts web/tests/unit/subjectModel.test.ts
```

---

## Task 4: View model for Binny's tip, marks to win, topics and the whole view

**Files:**
- Modify: `web/src/portals/student/screens/subject/subjectModel.ts` (append)
- Test: `web/tests/unit/subjectModel.test.ts` (append)

**Interfaces:**
- Consumes: Task 3's exports.
- Produces (used by Tasks 5–8):
  - `interface TipAction { label: string; detail: string | null; to: string }`, `interface TipView { mood: BinnyMood; line: string; action: TipAction; secondary: TipAction | null }`
  - `rankedWins(topics: TopicTile[]): TopicTile[]`
  - `fullTipLine(goal: GoalStep | null, examInDays: number | null): string`
  - `fullTip(code, goal, topics, examInDays): TipView`, `sparseTip(code): TipView`, `firstRunTip(code, subjectName): TipView`
  - `interface WinRowView { topic: string; name: string; marks: number; practiceTo: string; flashcardsTo: string | null }`, `interface WinView { heading: string; rows: WinRowView[] }`, `winRows(code, topics, decks, mode): WinView`
  - `SECURE_AT = 75`, `GETTING_AT = 60`, `topicState(accuracy): TopicState`
  - `interface TopicChipView { topic: string; label: string; state: TopicState; pct: number }`, `topicChips(topics): TopicChipView[]`
  - `topicsHint(mode: "full" | "sparse", shown: number, total: number | null): string | null`
  - `interface PathView { tabs: PaperTab[]; selected: number; goalGrade: string; steps: StepsView; trend: TrendView }`
  - `interface SubjectView { mode: "full" | "sparse"; path: PathView; tip: TipView; win: WinView; chips: TopicChipView[]; topicsHint: string | null; papers: PaperRowView[] }`
  - `buildSubjectView(input: SubjectViewInput): SubjectView` with `SubjectViewInput { data: Subject; catalogue: CatalogueSubject | undefined; decks: DeckSummaryDTO[]; examDate: string | null; now: Date; requestedPaper: string | null; mode: "full" | "sparse" }`
  - `FIRST_RUN_STEPS(name: string): { title: string; body: string }[]`
  - `GHOST_PATH_HEIGHTS = [30, 45, 52, 70]`, `GHOST_CHIPS: { state: TopicState; width: number }[]`

- [ ] **Step 1: Write the failing test**

Append to `web/tests/unit/subjectModel.test.ts`:

```ts
import {
  FIRST_RUN_STEPS,
  buildSubjectView,
  firstRunTip,
  fullTip,
  fullTipLine,
  rankedWins,
  sparseTip,
  topicChips,
  topicState,
  topicsHint,
  winRows,
} from "@/portals/student/screens/subject/subjectModel"
import { MATHS_TOPICS } from "@/portals/student/screens/subject/fixtures"
import type { DeckSummaryDTO } from "@/lib/flashcardTypes"

const deck = (topic: string | null, id = "d1"): DeckSummaryDTO => ({
  id,
  subjectCode: "0580",
  topic,
  title: "Deck",
  description: null,
  origin: "topic",
  cardCount: 10,
  dueCount: 0,
  createdAt: "2024-04-01T00:00:00Z",
})
const goal7 = { grade: "A*", marks: 68, outOf: 80, gap: 7, gapLabel: "7 to go", sourceLabel: "x", ariaLabel: "x" }

describe("Binny's tip", () => {
  it("points at the goal in 2–4 words", () => {
    expect(fullTipLine(goal7, null)).toBe("7 marks to A*")
    expect(fullTipLine({ ...goal7, gap: 1 }, null)).toBe("1 mark to A*")
    expect(fullTipLine({ ...goal7, gap: 0 }, null)).toBe("On the A* line")
    expect(fullTipLine({ ...goal7, gap: -3 }, null)).toBe("Above the A* line")
    expect(fullTipLine(null, null)).toBe("Next paper?")
  })
  it("mentions the exam inside 30 days (spec: exam countdown)", () => {
    expect(fullTipLine(goal7, 12)).toBe("12 days, 7 marks")
    expect(fullTipLine(goal7, 1)).toBe("1 day, 7 marks")
    expect(fullTipLine(goal7, 0)).toBe("Exam today")
    expect(fullTipLine(goal7, 31)).toBe("7 marks to A*")
    expect(fullTipLine({ ...goal7, gap: 0 }, 5)).toBe("On the A* line")
  })
  it("names the biggest win on the button", () => {
    expect(fullTip("0580", goal7, MATHS_TOPICS, null)).toEqual({
      mood: "happy",
      line: "7 marks to A*",
      action: { label: "Practise Vectors", detail: "+9 marks", to: "/student/practice/0580?topic=C7%20Vectors" },
      secondary: null,
    })
  })
  it("falls back to scanning when nothing has marks to win", () => {
    expect(fullTip("0580", goal7, [], null).action).toEqual({
      label: "Scan your next paper",
      detail: null,
      to: "/student/correct?subject=0580",
    })
  })
  it("encourages the next paper on the sparse screen", () => {
    expect(sparseTip("0580")).toEqual({
      mood: "happy",
      line: "Great start. Next paper?",
      action: { label: "Scan your next paper", detail: null, to: "/student/correct?subject=0580" },
      secondary: null,
    })
  })
  it("walks the first run to its first scan, with upload as the second way", () => {
    expect(firstRunTip("0580", "Mathematics")).toEqual({
      mood: "open",
      line: "Let’s find your first step",
      action: { label: "Scan a Mathematics paper", detail: null, to: "/student/correct?subject=0580" },
      secondary: { label: "Upload a PDF instead", detail: null, to: "/student/correct?subject=0580&source=file" },
    })
    expect(FIRST_RUN_STEPS("Mathematics").map((s) => s.title)).toEqual([
      "Scan a Mathematics paper",
      "Lemely marks it",
      "Your path appears",
    ])
  })
})

describe("marks to win", () => {
  it("ranks by marks, then weakest, and drops topics with nothing to win", () => {
    const ranked = rankedWins([...MATHS_TOPICS, { ...MATHS_TOPICS[0], name: "C0 Zero", marksToWin: 0 }])
    expect(ranked.slice(0, 4).map((t) => t.name)).toEqual(["C7 Vectors", "C2 Algebra", "C6 Trigonometry", "C5 Mensuration"])
    expect(ranked.some((t) => t.name === "C0 Zero")).toBe(false)
  })
  it("leaves out the topic already on Binny's button on the full screen", () => {
    const win = winRows("0580", MATHS_TOPICS, [deck("C2 Algebra", "alg")], "full")
    expect(win.heading).toBe("More marks to win")
    expect(win.rows).toEqual([
      { topic: "C2 Algebra", name: "Algebra", marks: 7, practiceTo: "/student/practice/0580?topic=C2%20Algebra", flashcardsTo: "/student/flashcards/0580?deck=alg" },
      { topic: "C6 Trigonometry", name: "Trigonometry", marks: 5, practiceTo: "/student/practice/0580?topic=C6%20Trigonometry", flashcardsTo: null },
      { topic: "C5 Mensuration", name: "Mensuration", marks: 4, practiceTo: "/student/practice/0580?topic=C5%20Mensuration", flashcardsTo: null },
    ])
  })
  it("starts with the biggest win on the sparse screen, two rows", () => {
    const win = winRows("0580", MATHS_TOPICS, [], "sparse")
    expect(win.heading).toBe("Marks to win")
    expect(win.rows.map((r) => r.name)).toEqual(["Vectors", "Algebra"])
  })
})

describe("topics", () => {
  it("bands accuracy into Work on, Getting there and Secure", () => {
    expect(topicState(41)).toBe("work")
    expect(topicState(59)).toBe("work")
    expect(topicState(60)).toBe("getting")
    expect(topicState(74)).toBe("getting")
    expect(topicState(75)).toBe("secure")
  })
  it("lists chips weakest first with their percent", () => {
    const chips = topicChips(MATHS_TOPICS)
    expect(chips[0]).toEqual({ topic: "C7 Vectors", label: "Vectors", state: "work", pct: 41 })
    expect(chips.filter((c) => c.state === "secure").map((c) => c.label)).toEqual([
      "Coordinate geometry",
      "Geometry",
      "Number",
      "Probability",
    ])
  })
  it("nudges the sparse screen toward more papers", () => {
    expect(topicsHint("sparse", 4, 10)).toBe("4 of 10 topics so far. Each paper fills in more.")
    expect(topicsHint("sparse", 4, null)).toBe("Each paper fills in more topics.")
    expect(topicsHint("sparse", 12, 10)).toBe("Each paper fills in more topics.")
    expect(topicsHint("full", 10, 10)).toBeNull()
  })
  it("explains an empty topic list instead of showing nothing", () => {
    expect(topicsHint("full", 0, 10)).toBe("Topics show up once a paper loses a mark.")
    expect(topicsHint("sparse", 0, 10)).toBe("Topics show up once a paper loses a mark.")
  })
})

describe("buildSubjectView", () => {
  const base = { catalogue: undefined, decks: [], examDate: null, now: NOW, requestedPaper: null }

  it("assembles the full screen around the most recent paper", () => {
    const view = buildSubjectView({ ...base, data: MATHS, mode: "full" })
    expect(view.path.selected).toBe(4)
    expect(view.path.goalGrade).toBe("A*")
    expect(view.path.tabs.map((t) => t.name)).toEqual(["Paper 4", "Paper 2"])
    expect(view.path.steps.ghosts).toBe(0)
    expect(view.tip.line).toBe("7 marks to A*")
    expect(view.win.rows.map((r) => r.name)).toEqual(["Algebra", "Trigonometry", "Mensuration"])
    expect(view.chips).toHaveLength(10)
    expect(view.topicsHint).toBeNull()
    expect(view.papers).toHaveLength(7)
  })
  it("switches the path, the tip's gap and the tier with ?paper=", () => {
    const view = buildSubjectView({ ...base, data: MATHS, mode: "full", requestedPaper: "2" })
    expect(view.path.selected).toBe(2)
    expect(view.path.steps.goal!.marks).toBe(60)
    expect(view.tip.line).toBe("7 marks to A*")
  })
  it("uses the exam date for Binny's line inside 30 days", () => {
    const view = buildSubjectView({ ...base, data: MATHS, mode: "full", examDate: "2024-12-02" })
    expect(view.tip.line).toBe("12 days, 7 marks")
  })
  it("assembles the sparse screen with ghosts, the scan tip and the hint", () => {
    const catalogue = { code: "0580", name: "Mathematics", board: "caie", qualificationLevel: "igcse", papers: [], topics: Array.from({ length: 10 }, (_, i) => `C${i} T`) }
    const view = buildSubjectView({ ...base, data: MATHS_ONE, mode: "sparse", catalogue })
    expect(view.path.tabs).toHaveLength(1)
    expect(view.path.steps.ghosts).toBe(3)
    expect(view.path.trend).toEqual({ kind: "single", text: "One step so far. Two more papers show your trend." })
    expect(view.tip.line).toBe("Great start. Next paper?")
    expect(view.win.heading).toBe("Marks to win")
    expect(view.topicsHint).toBe("4 of 10 topics so far. Each paper fills in more.")
    expect(view.papers).toHaveLength(1)
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run tests/unit/subjectModel.test.ts`
Expected: FAIL with `does not provide an export named 'FIRST_RUN_STEPS'` (and the other new names).

- [ ] **Step 3: Append the implementation**

Append to `web/src/portals/student/screens/subject/subjectModel.ts` (above the final `export type {...}` line, which stays last):

```ts
/* ── Binny's tip ───────────────────────────────────────────────────────── */

export interface TipAction {
  label: string
  /** Shown after the label as "· {detail}", e.g. "+9 marks". */
  detail: string | null
  to: string
}

export interface TipView {
  mood: BinnyMood
  /** 2–4 words. No exclamation marks: `check:copy` bans them (Needs user decision 1). */
  line: string
  action: TipAction
  secondary: TipAction | null
}

export function rankedWins(topics: TopicTile[]): TopicTile[] {
  return topics
    .filter((t) => t.marksToWin > 0)
    .sort((a, b) => b.marksToWin - a.marksToWin || a.accuracy - b.accuracy || a.name.localeCompare(b.name))
}

export function fullTipLine(goal: GoalStep | null, examInDays: number | null): string {
  if (!goal) return "Next paper?"
  const { gap, grade } = goal
  if (gap > 0 && examInDays !== null && examInDays >= 0 && examInDays <= NEAR_EXAM_DAYS) {
    return examInDays === 0 ? "Exam today" : `${plural(examInDays, "day")}, ${plural(gap, "mark")}`
  }
  if (gap > 0) return `${plural(gap, "mark")} to ${grade}`
  return gap === 0 ? `On the ${grade} line` : `Above the ${grade} line`
}

const scanAction = (code: string): TipAction => ({ label: "Scan your next paper", detail: null, to: links.scan(code) })

export function fullTip(code: string, goal: GoalStep | null, topics: TopicTile[], examInDays: number | null): TipView {
  const top = rankedWins(topics)[0]
  return {
    mood: "happy",
    line: fullTipLine(goal, examInDays),
    action: top
      ? { label: `Practise ${topicName(top.name)}`, detail: `+${plural(top.marksToWin, "mark")}`, to: links.practice(code, top.name) }
      : scanAction(code),
    secondary: null,
  }
}

export function sparseTip(code: string): TipView {
  return { mood: "happy", line: "Great start. Next paper?", action: scanAction(code), secondary: null }
}

export function firstRunTip(code: string, subjectName: string): TipView {
  return {
    mood: "open",
    line: "Let’s find your first step",
    action: { label: `Scan a ${subjectName} paper`, detail: null, to: links.scan(code) },
    secondary: { label: "Upload a PDF instead", detail: null, to: links.upload(code) },
  }
}

export function FIRST_RUN_STEPS(subjectName: string): { title: string; body: string }[] {
  return [
    { title: `Scan a ${subjectName} paper`, body: "Any past paper you have tried. Phone camera or PDF." },
    { title: "Lemely marks it", body: "Every question, with method marks. About two minutes." },
    { title: "Your path appears", body: "Each paper adds a step towards the A* line." },
  ]
}

export const GHOST_PATH_HEIGHTS = [30, 45, 52, 70] as const

export const GHOST_CHIPS: { state: TopicState; width: number }[] = [
  { state: "work", width: 96 },
  { state: "getting", width: 120 },
  { state: "secure", width: 88 },
  { state: "getting", width: 140 },
  { state: "secure", width: 104 },
  { state: "work", width: 92 },
  { state: "secure", width: 128 },
  { state: "getting", width: 110 },
]

/* ── Marks to win ──────────────────────────────────────────────────────── */

export interface WinRowView {
  topic: string
  name: string
  marks: number
  practiceTo: string
  flashcardsTo: string | null
}

export interface WinView {
  heading: string
  rows: WinRowView[]
}

/** Full: leave out the topic on Binny's button, then three rows. Sparse: the top two. */
export function winRows(code: string, topics: TopicTile[], decks: DeckSummaryDTO[], mode: "full" | "sparse"): WinView {
  const ranked = rankedWins(topics)
  const picked = mode === "full" ? ranked.slice(1, 4) : ranked.slice(0, 2)
  return {
    heading: mode === "full" ? "More marks to win" : "Marks to win",
    rows: picked.map((t) => {
      const deck = decks.find((d) => d.topic === t.name)
      return {
        topic: t.name,
        name: topicName(t.name),
        marks: t.marksToWin,
        practiceTo: links.practice(code, t.name),
        flashcardsTo: deck ? links.flashcards(code, deck.id) : null,
      }
    }),
  }
}

/* ── Topics ────────────────────────────────────────────────────────────── */

export const SECURE_AT = 75
export const GETTING_AT = 60

export function topicState(accuracy: number): TopicState {
  return accuracy >= SECURE_AT ? "secure" : accuracy >= GETTING_AT ? "getting" : "work"
}

export interface TopicChipView {
  topic: string
  label: string
  state: TopicState
  pct: number
}

export function topicChips(topics: TopicTile[]): TopicChipView[] {
  return [...topics]
    .sort((a, b) => a.accuracy - b.accuracy || a.name.localeCompare(b.name))
    .map((t) => ({ topic: t.name, label: topicName(t.name), state: topicState(t.accuracy), pct: t.accuracy }))
}

export function topicsHint(mode: "full" | "sparse", shown: number, total: number | null): string | null {
  if (shown === 0) return "Topics show up once a paper loses a mark."
  if (mode === "full") return null
  if (total !== null && shown < total) return `${shown} of ${total} topics so far. Each paper fills in more.`
  return "Each paper fills in more topics."
}

/* ── The whole view (full and sparse) ──────────────────────────────────── */

export interface PathView {
  tabs: PaperTab[]
  selected: number
  goalGrade: string
  steps: StepsView
  trend: TrendView
}

export interface SubjectView {
  mode: "full" | "sparse"
  path: PathView
  tip: TipView
  win: WinView
  chips: TopicChipView[]
  topicsHint: string | null
  papers: PaperRowView[]
}

export interface SubjectViewInput {
  data: Subject
  catalogue: CatalogueSubject | undefined
  decks: DeckSummaryDTO[]
  examDate: string | null
  now: Date
  requestedPaper: string | null
  mode: "full" | "sparse"
}

export function buildSubjectView(input: SubjectViewInput): SubjectView {
  const { data, catalogue, decks, examDate, now, requestedPaper, mode } = input
  const code = data.header.code
  const papers = data.papersBreakdown.filter((p) => p.attempts.length > 0)
  const selected = resolvePaper(papers, requestedPaper) ?? papers[0].paperNumber
  const paper = papers.find((p) => p.paperNumber === selected) ?? papers[0]
  const steps = stepsFor(paper, { ghosts: mode === "sparse" ? SPARSE_GHOSTS : 0 })
  const examInDays = examDate ? daysUntil(examDate, now) : null
  const chips = topicChips(data.topicMap)
  return {
    mode,
    path: {
      tabs: paperTabs(papers),
      selected: paper.paperNumber,
      goalGrade: steps.goal?.grade ?? "A*",
      steps,
      trend: trendFor(paper, data.header.forecast, data.paperHistory.length),
    },
    tip: mode === "full" ? fullTip(code, steps.goal, data.topicMap, examInDays) : sparseTip(code),
    win: winRows(code, data.topicMap, decks, mode),
    chips,
    topicsHint: topicsHint(mode, chips.length, catalogue ? catalogue.topics.length : null),
    papers: paperRows(data.paperHistory, now),
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npx vitest run tests/unit/subjectModel.test.ts`
Expected: all tests pass.

- [ ] **Step 5: Copy gate, typecheck and commit**

Run: `cd web && npm run check:copy && npm run typecheck`
Expected: both exit 0 (no `!`, no em dash in the new strings).

```bash
PYTHONPATH="$PWD" pre-commit run --files web/src/portals/student/screens/subject/subjectModel.ts web/tests/unit/subjectModel.test.ts
git add web/src/portals/student/screens/subject/subjectModel.ts web/tests/unit/subjectModel.test.ts
git commit -S -m "feat(web): subject view model for Binny tip, marks to win and topics" -- web/src/portals/student/screens/subject/subjectModel.ts web/tests/unit/subjectModel.test.ts
```

---

## Task 5: Steps path and paper switch (designer)

**Agent:** `designer`. Before any edit: invoke the `impeccable` skill, read `.claude/skills/impeccable/reference/craft-floor.md`, and read the three taste memories named in the master plan.

**Files:**
- Create: `web/src/portals/student/screens/subject/subject.css`
- Create: `web/src/portals/student/screens/subject/useMinWidth.ts`
- Create: `web/src/portals/student/screens/subject/SubjectSteps.tsx`
- Create: `web/src/portals/student/screens/subject/PathSection.tsx`
- Test: `web/tests/unit/subjectScreen.test.ts`

**Interfaces:**
- Consumes: `StepsView`, `PathView`, `TrendView`, `GHOST_PATH_HEIGHTS` (Tasks 3–4).
- Produces:
  - `useMinWidth(px: number): boolean`
  - `SubjectSteps(p: { steps: StepsView; goalExpanded?: boolean; onGoal?: () => void }): JSX.Element`
  - `GhostSteps(p: { goalGrade?: string }): JSX.Element`
  - `PathSection(p: { path: PathView; onSelect: (paperNumber: number) => void }): JSX.Element`
  - `SectionHeading(p: { id?: string; title: string; to?: string; children?: React.ReactNode }): JSX.Element` (exported from `PathSection.tsx`, reused by Tasks 6–7)

Class map (mock → this task): `.sec7` → `.sj-sec`; `.h2row` → `.sj-h2row`; `.sjh` + `.hlink.h` → `.sj-h2` (+ `a` inside when linked); `.ptog` → `.sj-ptog`; `.pbody` → `.sj-pbody`; `.gp2` → `.sj-steps`; `.gp2t.sp` → `.sj-track`; `.stp` / `.stp.cur` / `.stp.goal` / `.stp.ghost` → `.sj-stp` / `[data-current=true]` / `.sj-stp--goal` / `.sj-stp--ghost`; `.gp2l` → `.sj-labels`; `.gp2l .gl0` → `.sj-next`; `.gp2l .goal` → `.sj-goal-label`; `.trend2` → `.sj-trend`; `.ghostp` → `.sj-steps--ghost`.

- [ ] **Step 1: Write the failing test**

Create `web/tests/unit/subjectScreen.test.ts`:

```ts
import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { MemoryRouter } from "react-router-dom"
import { describe, expect, it } from "vitest"
import { GhostSteps, SubjectSteps } from "@/portals/student/screens/subject/SubjectSteps"
import { PathSection } from "@/portals/student/screens/subject/PathSection"
import { buildSubjectView } from "@/portals/student/screens/subject/subjectModel"
import { MATHS, MATHS_ONE, NOW } from "@/portals/student/screens/subject/fixtures"

const html = (node: Parameters<typeof createElement>[0], props: object) =>
  renderToStaticMarkup(createElement(MemoryRouter, null, createElement(node as never, props)))

const full = buildSubjectView({ data: MATHS, catalogue: undefined, decks: [], examDate: null, now: NOW, requestedPaper: null, mode: "full" })
const sparse = buildSubjectView({ data: MATHS_ONE, catalogue: undefined, decks: [], examDate: null, now: NOW, requestedPaper: null, mode: "sparse" })

describe("SubjectSteps", () => {
  it("draws one linked bar per attempt with its grade, height and colour", () => {
    const out = html(SubjectSteps, { steps: full.path.steps })
    expect(out.match(/class="sj-stp"/g)).toHaveLength(4)
    expect(out).toContain('href="/student/result/6"')
    expect(out).toContain("--h:81%")
    expect(out).toContain("--c:var(--grade-a)")
    expect(out).toContain('data-current="true"')
    expect(out).toContain('aria-label="A, 61 out of 80, Apr. Open this paper"')
  })
  it("draws the goal block with the gap and its label row", () => {
    const out = html(SubjectSteps, { steps: full.path.steps })
    expect(out).toContain("sj-stp--goal")
    expect(out).toContain("7 to go")
    expect(out).toContain("A* line")
    expect(out).toContain('aria-expanded="false"')
  })
  it("names the whole path as one group for screen readers", () => {
    expect(html(SubjectSteps, { steps: full.path.steps })).toContain('role="group" aria-label="Paper 4 marks so far:')
  })
  it("adds ghost slots labelled next on the sparse path", () => {
    const out = html(SubjectSteps, { steps: sparse.path.steps })
    expect(out.match(/sj-stp--ghost/g)).toHaveLength(3)
    expect(out.match(/>next</g)).toHaveLength(3)
  })
  it("draws a hidden ghost path for the first run", () => {
    const out = html(GhostSteps, {})
    expect(out).toContain('aria-hidden="true"')
    expect(out.match(/sj-stp--ghost/g)).toHaveLength(4)
    expect(out).toContain("A* line")
  })
})

describe("PathSection", () => {
  it("titles the section with the goal and offers a tab per paper", () => {
    const out = html(PathSection, { path: full.path, onSelect: () => {} })
    expect(out).toContain("Your path to A*")
    expect(out).toContain('role="tablist"')
    expect(out.match(/role="tab"/g)).toHaveLength(2)
    expect(out).toMatch(/aria-selected="true"[^>]*>Paper 4</)
    expect(out).toContain('role="tabpanel"')
  })
  it("prints the trend line with the forecast grade", () => {
    const out = html(PathSection, { path: full.path, onSelect: () => {} })
    expect(out).toContain("Heading for an")
    expect(out).toContain("up 16 marks since Oct")
  })
  it("hides the switch when there is one paper and prints the sparse line", () => {
    const out = html(PathSection, { path: sparse.path, onSelect: () => {} })
    expect(out).not.toContain('role="tablist"')
    expect(out).toContain("One step so far. Two more papers show your trend.")
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run tests/unit/subjectScreen.test.ts`
Expected: FAIL with `Failed to resolve import "@/portals/student/screens/subject/SubjectSteps"`.

- [ ] **Step 3: Write the stylesheet**

Create `web/src/portals/student/screens/subject/subject.css` (the whole file; Tasks 6–7 use the rest of it):

```css
/* Subject screen (redesign L2), ported from .impeccable/mocks/student-r2/t.css
   ("subject final", lines 461-569). Colours are roles from index.css, or mixes
   of two roles; no raw values. Logical properties only (rtlSafety). */

/* ---- Layout: one column, then two from 768px ---------------------------- */
.sj-layout { display: flex; flex-direction: column; gap: 24px; }
.sj-col { display: grid; gap: 24px; align-content: start; min-width: 0; }
@media (min-width: 768px) {
  .sj-layout { display: grid; grid-template-columns: minmax(0, 1.1fr) minmax(0, 1fr); gap: 32px; align-items: start; }
  .sj-col { gap: 26px; }
}
@media (min-width: 1280px) {
  .sj-layout { grid-template-columns: minmax(0, 1.05fr) minmax(0, 1fr); gap: 48px; }
}
.sj-col--aside-first-run { display: none; }
@media (min-width: 768px) { .sj-col--aside-first-run { display: grid; } }

/* ---- Header ------------------------------------------------------------- */
.sj-head { display: flex; align-items: center; gap: 10px; padding-block: 6px 6px; }
.sj-head .sj-head-t { flex: 1; min-width: 0; display: grid; }
.sj-title { margin: 0; font: 800 28px/1.1 var(--font-display); letter-spacing: -0.03em; color: var(--md-primary); }
@media (min-width: 1280px) { .sj-title { font-size: 32px; } }
.sj-sub { font: 500 13px var(--font-sans); color: var(--md-on-surface-variant); }

/* ---- Section headings --------------------------------------------------- */
.sj-sec { display: grid; gap: 10px; }
.sj-h2row { display: flex; align-items: center; gap: 10px; justify-content: space-between; }
.sj-h2 { margin: 0; font: 800 18px/1.2 var(--font-sans); letter-spacing: -0.01em; color: var(--md-on-surface); }
.sj-h2 a { position: relative; display: inline-flex; align-items: center; gap: 8px; padding-block: 4px; padding-inline: 0 6px; border-radius: 10px; color: inherit; }
.sj-h2 a::before { content: ""; position: absolute; inset: -8px -3px; }
.sj-h2 a svg { color: var(--md-on-surface-variant); }
.sj-h2 a:focus-visible { outline: 2px solid var(--md-primary); outline-offset: 2px; }

/* ---- Paper switch ------------------------------------------------------- */
.sj-ptog { display: inline-flex; padding: 3px; border-radius: 12px; background: var(--md-surface-container-high); gap: 2px; }
.sj-ptog button { position: relative; border: 0; background: none; min-height: 36px; padding-inline: 12px; border-radius: 9px; font: 600 13px var(--font-sans); color: var(--md-on-surface-variant); cursor: pointer; }
.sj-ptog button::before { content: ""; position: absolute; inset: -4px 0; }
.sj-ptog button[aria-selected="true"] { background: var(--md-surface-container-lowest); color: var(--md-primary); box-shadow: 0 1px 3px color-mix(in oklch, var(--md-shadow) 18%, transparent); }
.sj-ptog button:focus-visible { outline: 2px solid var(--md-primary); outline-offset: 2px; }

/* ---- Steps path --------------------------------------------------------- */
.sj-pbody { display: grid; gap: 10px; }
.sj-steps {
  display: grid; gap: 8px;
  --sj-goal: var(--grade-a-star);
  --sj-goal-fill: color-mix(in oklch, var(--sj-goal) 12%, var(--md-surface-container-lowest));
  --sj-goal-edge: color-mix(in oklch, var(--sj-goal) 35%, var(--md-surface-container-lowest));
}
.sj-track { position: relative; display: grid; grid-template-columns: repeat(var(--n, 5), minmax(0, 1fr)); height: 108px; margin-block-start: 4px; align-items: end; gap: 8px; border-block-end: 2px solid var(--md-outline); }
.sj-stp {
  width: min(100%, 64px); justify-self: center; height: var(--h); min-height: 44px;
  border-radius: 14px 14px 4px 4px; border: 0; padding: 8px 0 0; color: inherit; text-decoration: none; font: inherit;
  background: color-mix(in oklch, var(--c) 22%, var(--md-surface-container-lowest));
  display: flex; flex-direction: column; align-items: center; gap: 2px;
  transform-origin: bottom; animation: sj-grow 0.7s var(--ease-out) both;
}
.sj-stp b { font: 800 22px/1 var(--font-display); color: color-mix(in oklch, var(--c), var(--md-on-surface) 25%); }
.sj-stp[data-current="true"] { background: var(--c); }
.sj-stp[data-current="true"] b { color: var(--md-on-primary); font-size: 28px; }
.sj-stp--goal { background: var(--sj-goal-fill); box-shadow: inset 0 0 0 2px var(--sj-goal-edge); cursor: pointer; }
.sj-stp--goal b { color: var(--sj-goal); }
.sj-stp--goal span { font: 700 12px var(--font-sans); white-space: nowrap; color: var(--sj-goal); }
.sj-stp--ghost { background: transparent; box-shadow: inset 0 0 0 2px var(--md-outline-variant); height: var(--h, 34%); animation: none; }
.sj-steps--ghost .sj-stp--goal { animation: none; cursor: default; }
.sj-track > :nth-child(2) { animation-delay: 0.06s; }
.sj-track > :nth-child(3) { animation-delay: 0.12s; }
.sj-track > :nth-child(4) { animation-delay: 0.18s; }
.sj-track > :nth-child(5) { animation-delay: 0.26s; }
@keyframes sj-grow { from { transform: scaleY(0.4); } }
@media (hover: hover) {
  .sj-stp { transition: translate 0.2s var(--ease-out), filter 0.2s; }
  a.sj-stp:hover, button.sj-stp:hover { translate: 0 -3px; filter: saturate(1.15); }
}
.sj-stp:focus-visible { outline: 2px solid var(--md-primary); outline-offset: 3px; }
.sj-labels { display: grid; grid-template-columns: repeat(var(--n, 5), minmax(0, 1fr)); text-align: center; font: 500 12px var(--font-sans); color: var(--md-on-surface-variant); }
.sj-labels > span { display: grid; gap: 1px; }
.sj-labels b { font: 600 12.5px var(--font-mono); font-variant-numeric: tabular-nums; color: var(--md-on-surface); }
.sj-labels b small { font-weight: 500; font-size: 12px; color: var(--md-on-surface-variant); }
.sj-labels [data-current="true"] b { font-weight: 800; }
.sj-labels .sj-goal-label, .sj-labels .sj-goal-label b, .sj-labels .sj-goal-label b small { color: var(--sj-goal); font-weight: 600; }
.sj-labels .sj-next { align-self: end; }
.sj-trend { margin: 0; font: 500 14px var(--font-sans); color: var(--md-on-surface-variant); }
.sj-trend b { font: 800 15px var(--font-sans); }
@media (prefers-reduced-motion: reduce) {
  .sj-stp { animation: none; transition: none; }
  a.sj-stp:hover, button.sj-stp:hover { translate: none; }
}

/* ---- Binny tip ---------------------------------------------------------- */
.sj-tip { display: grid; gap: 10px; }
.sj-go { min-height: 50px; width: 100%; justify-content: center; border-radius: 18px; font: 700 15.5px/1 var(--font-sans); box-shadow: 0 14px 24px -16px color-mix(in oklch, var(--md-primary) 70%, transparent); }
.sj-go span { opacity: 0.75; font-weight: 600; }
.sj-upl { justify-self: center; display: inline-flex; align-items: center; min-height: 44px; font: 600 14px var(--font-sans); color: var(--md-primary); }

/* ---- Marks to win ------------------------------------------------------- */
.sj-win { display: grid; }
.sj-win > ul { list-style: none; margin: 0; padding: 0; }
.sj-wrow { display: grid; grid-template-columns: minmax(0, 1fr) 44px; align-items: center; gap: 6px; }
.sj-wrow + .sj-wrow { border-block-start: 1px solid var(--md-outline-variant); }
.sj-wmain { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 12px; align-items: center; padding: 11px 2px; min-height: 44px; color: var(--md-on-surface); }
.sj-at { display: grid; min-width: 0; }
.sj-at b { font: 700 15px var(--font-sans); }
.sj-at span { font: 400 13px var(--font-sans); color: var(--md-primary); }
.sj-wn { font: 700 17px/1 var(--font-mono); letter-spacing: -0.02em; color: var(--md-primary); font-variant-numeric: tabular-nums; }
.sj-wn small { font: 600 12px var(--font-sans); letter-spacing: 0; color: var(--md-on-surface-variant); }
.sj-fc { width: 44px; height: 44px; border-radius: 14px; display: grid; place-items: center; color: var(--md-primary); background: var(--md-primary-container); }
.sj-fcx { width: 44px; }
@media (hover: hover) { .sj-wmain:hover .sj-at b { color: var(--md-primary); } }
.sj-wmain:focus-visible, .sj-fc:focus-visible { outline: 2px solid var(--md-primary); outline-offset: 2px; border-radius: 12px; }

/* ---- Topics ------------------------------------------------------------- */
.sj-hint { margin: 0; font: 500 14px/1.4 var(--font-sans); color: var(--md-on-surface-variant); text-wrap: pretty; }
.sj-ghostchips { display: flex; flex-wrap: wrap; gap: 6px; }
.sj-ghostchip { min-height: 40px; border-radius: 12px; box-shadow: inset 0 0 0 2px var(--md-outline-variant); }

/* ---- Papers ------------------------------------------------------------- */
.sj-grade { width: 36px; text-align: center; font: 800 28px/1 var(--font-display); color: var(--c); }
.sj-more { display: inline-flex; align-items: center; gap: 6px; min-height: 44px; border: 0; background: none; padding: 0; cursor: pointer; font: 700 14px var(--font-sans); color: var(--md-primary); justify-self: start; }
.sj-more:focus-visible { outline: 2px solid var(--md-primary); outline-offset: 2px; border-radius: 8px; }

/* ---- Loading ------------------------------------------------------------ */
.sj-skel { display: grid; gap: 14px; }
.sj-skelbars { display: grid; grid-template-columns: repeat(5, 1fr); gap: 8px; align-items: end; height: 108px; }
.sj-skelbars > * { border-radius: 14px 14px 4px 4px; }

/* ---- Error -------------------------------------------------------------- */
.sj-err { display: grid; justify-items: center; align-content: center; text-align: center; gap: 12px; padding: 24px 8px; min-height: 60dvh; }
.sj-err h2 { margin: 6px 0 0; font: 800 28px/1.15 var(--font-display); letter-spacing: -0.02em; color: var(--md-primary); text-wrap: balance; }
.sj-err p { margin: 0 0 6px; max-width: 30ch; font: 500 15px/1.4 var(--font-sans); color: var(--md-on-surface-variant); }
.sj-err .sj-go { max-width: 300px; }
```

- [ ] **Step 4: Write the media hook**

Create `web/src/portals/student/screens/subject/useMinWidth.ts`:

```ts
import { useSyncExternalStore } from "react"

/** True while the viewport is at least `px` wide. False during SSR/tests. */
export function useMinWidth(px: number): boolean {
  const query = `(min-width: ${px}px)`
  return useSyncExternalStore(
    (onChange) => {
      if (typeof window === "undefined" || !window.matchMedia) return () => {}
      const list = window.matchMedia(query)
      list.addEventListener("change", onChange)
      return () => list.removeEventListener("change", onChange)
    },
    () => typeof window !== "undefined" && !!window.matchMedia && window.matchMedia(query).matches,
    () => false,
  )
}
```

- [ ] **Step 5: Write the steps component**

Create `web/src/portals/student/screens/subject/SubjectSteps.tsx`:

```tsx
import type { CSSProperties } from "react"
import { Link } from "react-router-dom"
import { GHOST_PATH_HEIGHTS, type StepsView } from "./subjectModel"

type Vars = CSSProperties & Record<`--${string}`, string | number>

/**
 * The approved Steps path: one solid bar per attempt on a single baseline, the
 * latest solid in its grade colour, then a soft green goal block (never a
 * dashed outline). Bars run from 40% of the marks up to the A* line.
 */
export function SubjectSteps({
  steps,
  goalExpanded = false,
  onGoal,
}: {
  steps: StepsView
  goalExpanded?: boolean
  onGoal?: () => void
}) {
  const n: Vars = { "--n": steps.bars.length + steps.ghosts + (steps.goal ? 1 : 0) }
  return (
    <div className="sj-steps" role="group" aria-label={steps.groupLabel}>
      <div className="sj-track" style={n}>
        {steps.bars.map((bar) => (
          <Link
            key={bar.id}
            to={bar.resultTo}
            className="sj-stp"
            data-current={bar.current}
            style={{ "--h": `${bar.heightPct}%`, "--c": bar.colorVar } as Vars}
            aria-label={bar.ariaLabel}
          >
            <b aria-hidden="true">{bar.grade}</b>
          </Link>
        ))}
        {Array.from({ length: steps.ghosts }, (_, i) => (
          <span key={`ghost-${i}`} className="sj-stp sj-stp--ghost" aria-hidden="true" />
        ))}
        {steps.goal ? (
          <button
            type="button"
            className="sj-stp sj-stp--goal"
            style={{ "--h": "100%" } as Vars}
            aria-label={steps.goal.ariaLabel}
            aria-expanded={goalExpanded}
            aria-controls="sj-goal-note"
            onClick={onGoal}
          >
            <b aria-hidden="true">{steps.goal.grade}</b>
            <span aria-hidden="true">{steps.goal.gapLabel}</span>
          </button>
        ) : null}
      </div>
      <div className="sj-labels" style={n} aria-hidden="true">
        {steps.bars.map((bar) => (
          <span key={bar.id} data-current={bar.current}>
            <b>
              {bar.marks}
              <small>/{bar.outOf}</small>
            </b>
            {bar.month}
          </span>
        ))}
        {Array.from({ length: steps.ghosts }, (_, i) => (
          <span key={`next-${i}`} className="sj-next">
            next
          </span>
        ))}
        {steps.goal ? (
          <span className="sj-goal-label">
            <b>
              {steps.goal.marks}
              <small>/{steps.goal.outOf}</small>
            </b>
            {steps.goal.grade} line
          </span>
        ) : null}
      </div>
    </div>
  )
}

/** The first-run outline of the path to come. Decorative only. */
export function GhostSteps({ goalGrade = "A*" }: { goalGrade?: string }) {
  const n: Vars = { "--n": GHOST_PATH_HEIGHTS.length + 1 }
  return (
    <div className="sj-steps sj-steps--ghost" aria-hidden="true">
      <div className="sj-track" style={n}>
        {GHOST_PATH_HEIGHTS.map((h) => (
          <span key={h} className="sj-stp sj-stp--ghost" style={{ "--h": `${h}%` } as Vars} />
        ))}
        <span className="sj-stp sj-stp--goal" style={{ "--h": "100%" } as Vars}>
          <b>{goalGrade}</b>
        </span>
      </div>
      <div className="sj-labels" style={n}>
        {GHOST_PATH_HEIGHTS.map((h) => (
          <span key={h} />
        ))}
        <span className="sj-goal-label">{goalGrade} line</span>
      </div>
    </div>
  )
}
```

- [ ] **Step 6: Write the path section**

Create `web/src/portals/student/screens/subject/PathSection.tsx`:

```tsx
import { useRef, useState, type KeyboardEvent, type ReactNode } from "react"
import { Link } from "react-router-dom"
import { CaretRight } from "@phosphor-icons/react"
import { SubjectSteps } from "./SubjectSteps"
import type { PaperTab, PathView, TrendView } from "./subjectModel"

/** An h2 that is a link (with the mock's chevron) only when it has somewhere to go. */
export function SectionHeading({ id, title, to, children }: { id?: string; title: string; to?: string; children?: ReactNode }) {
  return (
    <div className="sj-h2row">
      <h2 id={id} className="sj-h2">
        {to ? (
          <Link to={to} className="lm-press lm-press-scale">
            {title}
            <CaretRight size={14} weight="bold" aria-hidden="true" />
          </Link>
        ) : (
          title
        )}
      </h2>
      {children}
    </div>
  )
}

function PaperSwitch({ tabs, selected, onSelect }: { tabs: PaperTab[]; selected: number; onSelect: (n: number) => void }) {
  const refs = useRef<(HTMLButtonElement | null)[]>([])
  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return
    event.preventDefault()
    const rtl = event.currentTarget.closest('[dir="rtl"]') !== null
    const forward = event.key === (rtl ? "ArrowLeft" : "ArrowRight")
    const next = (index + (forward ? 1 : -1) + tabs.length) % tabs.length
    onSelect(tabs[next].paperNumber)
    refs.current[next]?.focus()
  }
  return (
    <div className="sj-ptog" role="tablist" aria-label="Choose a paper">
      {tabs.map((tab, i) => {
        const on = tab.paperNumber === selected
        return (
          <button
            key={tab.paperNumber}
            ref={(el) => {
              refs.current[i] = el
            }}
            type="button"
            role="tab"
            id={`sj-tab-${tab.paperNumber}`}
            aria-selected={on}
            aria-controls="sj-path-panel"
            tabIndex={on ? 0 : -1}
            onClick={() => onSelect(tab.paperNumber)}
            onKeyDown={(e) => onKeyDown(e, i)}
          >
            {tab.name}
          </button>
        )
      })}
    </div>
  )
}

function TrendLine({ trend }: { trend: TrendView }) {
  if (trend.kind === "single") return <p className="sj-trend">{trend.text}</p>
  return (
    <p className="sj-trend">
      Heading for {trend.article} <b style={{ color: trend.colorVar }}>{trend.forecast}</b> · {trend.change}
    </p>
  )
}

export function PathSection({ path, onSelect }: { path: PathView; onSelect: (paperNumber: number) => void }) {
  const [goalOpen, setGoalOpen] = useState(false)
  const switchable = path.tabs.length > 1
  return (
    <section className="sj-sec" aria-labelledby="sj-path-h">
      <SectionHeading id="sj-path-h" title={`Your path to ${path.goalGrade}`}>
        {switchable ? <PaperSwitch tabs={path.tabs} selected={path.selected} onSelect={onSelect} /> : null}
      </SectionHeading>
      <div
        className="sj-pbody"
        id="sj-path-panel"
        {...(switchable ? { role: "tabpanel", "aria-labelledby": `sj-tab-${path.selected}` } : {})}
      >
        {/* Keyed by paper so a switch remounts the bars and replays sj-grow. */}
        <SubjectSteps key={path.selected} steps={path.steps} goalExpanded={goalOpen} onGoal={() => setGoalOpen((v) => !v)} />
        <TrendLine trend={path.trend} />
        {path.steps.goal ? (
          <p id="sj-goal-note" className="sj-trend" hidden={!goalOpen}>
            {path.steps.goal.grade} line from the {path.steps.goal.sourceLabel.replace(/^Average/, "average").replace(/^Estimated/, "estimated")}.
          </p>
        ) : null}
      </div>
    </section>
  )
}
```

- [ ] **Step 7: Run test to verify it passes**

Run: `cd web && npx vitest run tests/unit/subjectScreen.test.ts`
Expected: all tests pass.

- [ ] **Step 8: Lint gates and commit**

Run: `cd web && npm run typecheck && npx oxlint src/portals/student/screens/subject && npm run check:copy && npm run check:native`
Expected: all exit 0.

```bash
PYTHONPATH="$PWD" pre-commit run --files web/src/portals/student/screens/subject/subject.css web/src/portals/student/screens/subject/useMinWidth.ts web/src/portals/student/screens/subject/SubjectSteps.tsx web/src/portals/student/screens/subject/PathSection.tsx web/tests/unit/subjectScreen.test.ts
git add web/src/portals/student/screens/subject/subject.css web/src/portals/student/screens/subject/useMinWidth.ts web/src/portals/student/screens/subject/SubjectSteps.tsx web/src/portals/student/screens/subject/PathSection.tsx web/tests/unit/subjectScreen.test.ts
git commit -S -m "feat(web): subject steps path and paper switch" -- web/src/portals/student/screens/subject/subject.css web/src/portals/student/screens/subject/useMinWidth.ts web/src/portals/student/screens/subject/SubjectSteps.tsx web/src/portals/student/screens/subject/PathSection.tsx web/tests/unit/subjectScreen.test.ts
```

---

## Task 6: Tip, marks to win, topics and papers sections (designer)

**Agent:** `designer` (impeccable skill + craft floor first).

**Files:**
- Create: `web/src/portals/student/screens/subject/TipSection.tsx`
- Create: `web/src/portals/student/screens/subject/WinList.tsx`
- Create: `web/src/portals/student/screens/subject/TopicsSection.tsx`
- Create: `web/src/portals/student/screens/subject/PapersList.tsx`
- Test: `web/tests/unit/subjectScreen.test.ts` (append)

**Interfaces:**
- Consumes: `TipView`, `WinView`, `TopicChipView`, `PaperRowView`, `visiblePapers` (Tasks 3–4); `SectionHeading` (Task 5); F1 `BinnyLine`, `TopicChips`, `HairRows`, `HairRow`; `buttonVariants` (`@/components/ui/button`).
- Produces:
  - `TipSection(p: { tip: TipView; size: number }): JSX.Element`
  - `WinList(p: { win: WinView; allTo: string }): JSX.Element`
  - `TopicsSection(p: { chips: TopicChipView[]; foldSecure: boolean; hint: string | null; onSelect: (topic: string) => void }): JSX.Element`
  - `TopicLegend(): JSX.Element`
  - `PapersList(p: { rows: PaperRowView[]; visible: number; onShowAll: () => void }): JSX.Element`

F1 dependency (see "Cross-lane dependencies"): `TopicChips` items accept an optional `pct?: number` rendered in Mono after the label, and with `foldSecure` the kit renders the "N secure" fold chip (`.tm.more`: transparent, `inset 0 0 0 1.5px` outline, check icon, chevron) that unfolds in place. If F1 lands without `pct`, this task adds it to `TopicChip`/`TopicChips` in `web/src/components/redesign` as an optional prop (signature-compatible) in its own commit and tells the F1 owner.

Class map: `.say2`/`.bub2`/`.bwrap` → F1 `BinnyLine`; `.btn.big4.go2` → `buttonVariants({ variant: "primary", size: "lg" })` + `.sj-go`; `.lnk.q.upl` → `.sj-upl`; `.win4` → `.sj-win`; `.wrow2` → `.sj-wrow`; `.wmain` → `.sj-wmain`; `.at` → `.sj-at`; `.wn` → `.sj-wn`; `.fc` / `.fcx` → `.sj-fc` / `.sj-fcx`; `.tmap` + `.tm.*` → F1 `TopicChips`; `.tleg` → `TopicLegend` (F1 icons via `TopicChip` states); `.hint2` → `.sj-hint`; `.rp` → F1 `HairRow` with `.sj-grade` leading; `.morel` → `.sj-more`.

- [ ] **Step 1: Write the failing test**

Append to `web/tests/unit/subjectScreen.test.ts`:

```ts
import { TipSection } from "@/portals/student/screens/subject/TipSection"
import { WinList } from "@/portals/student/screens/subject/WinList"
import { TopicsSection } from "@/portals/student/screens/subject/TopicsSection"
import { PapersList } from "@/portals/student/screens/subject/PapersList"
import { firstRunTip, winRows } from "@/portals/student/screens/subject/subjectModel"
import { MATHS_TOPICS } from "@/portals/student/screens/subject/fixtures"

describe("TipSection", () => {
  it("shows Binny's line and a button naming the action and its marks", () => {
    const out = html(TipSection, { tip: full.tip, size: 60 })
    expect(out).toContain("7 marks to A*")
    expect(out).toContain('href="/student/practice/0580?topic=C7%20Vectors"')
    expect(out).toContain("Practise Vectors")
    expect(out).toContain("· +9 marks")
  })
  it("adds the secondary link on the first run", () => {
    const out = html(TipSection, { tip: firstRunTip("0580", "Mathematics"), size: 60 })
    expect(out).toContain("Upload a PDF instead")
    expect(out).toContain('href="/student/correct?subject=0580&amp;source=file"')
  })
})

describe("WinList", () => {
  const win = winRows("0580", MATHS_TOPICS, [{ id: "alg", subjectCode: "0580", topic: "C2 Algebra", title: "", description: null, origin: "topic", cardCount: 1, dueCount: 0, createdAt: "" }], "full")
  it("lists each topic with its marks and a practice link, heading linked to practice", () => {
    const out = html(WinList, { win, allTo: "/student/practice/0580" })
    expect(out).toContain("More marks to win")
    expect(out).toContain('href="/student/practice/0580"')
    expect(out).toContain('href="/student/practice/0580?topic=C2%20Algebra"')
    expect(out).toContain("+7")
    expect(out.match(/<li/g)).toHaveLength(3)
  })
  it("offers flashcards only where a deck exists for the topic", () => {
    const out = html(WinList, { win, allTo: "/student/practice/0580" })
    expect(out).toContain('href="/student/flashcards/0580?deck=alg"')
    expect(out).toContain('aria-label="Algebra flashcards"')
    expect(out.match(/sj-fcx/g)).toHaveLength(2)
  })
})

describe("TopicsSection", () => {
  it("renders the chips, the legend and no hint on the full screen", () => {
    const out = html(TopicsSection, { chips: full.chips, foldSecure: true, hint: null, onSelect: () => {} })
    expect(out).toContain("Topics")
    expect(out).toContain("Vectors")
    expect(out).toContain("Work on")
    expect(out).toContain("Getting there")
    expect(out).toContain("Secure")
  })
  it("prints the sparse hint", () => {
    const out = html(TopicsSection, { chips: sparse.chips, foldSecure: false, hint: "4 of 10 topics so far. Each paper fills in more.", onSelect: () => {} })
    expect(out).toContain("4 of 10 topics so far. Each paper fills in more.")
  })
})

describe("PapersList", () => {
  it("shows the visible rows and an All N papers control", () => {
    const out = html(PapersList, { rows: full.papers, visible: 4, onShowAll: () => {} })
    expect(out).toContain("Papers")
    expect(out.match(/href="\/student\/result\//g)).toHaveLength(4)
    expect(out).toContain("All 7 papers")
    expect(out).toContain("0580/42 · May/Jun 2024")
    expect(out).toContain("61/80 · Apr")
  })
  it("drops the control once everything is visible", () => {
    const out = html(PapersList, { rows: full.papers, visible: 7, onShowAll: () => {} })
    expect(out).not.toContain("All 7 papers")
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run tests/unit/subjectScreen.test.ts`
Expected: FAIL with `Failed to resolve import "@/portals/student/screens/subject/TipSection"`.

- [ ] **Step 3: Write the four sections**

Create `web/src/portals/student/screens/subject/TipSection.tsx`:

```tsx
import { Link } from "react-router-dom"
import { BinnyLine } from "@/components/redesign"
import { buttonVariants } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import type { TipView } from "./subjectModel"

/** Binny's 2–4 words, then one button that names the action. Binny's only appearance on the screen. */
export function TipSection({ tip, size }: { tip: TipView; size: number }) {
  return (
    <section className="sj-tip" aria-label="Next step">
      <BinnyLine mood={tip.mood} line={tip.line} size={size} motion="idle" />
      <Link to={tip.action.to} className={cn(buttonVariants({ variant: "primary", size: "lg" }), "sj-go")}>
        {tip.action.label}
        {tip.action.detail ? <span> · {tip.action.detail}</span> : null}
      </Link>
      {tip.secondary ? (
        <Link to={tip.secondary.to} className="sj-upl">
          {tip.secondary.label}
        </Link>
      ) : null}
    </section>
  )
}
```

Create `web/src/portals/student/screens/subject/WinList.tsx`:

```tsx
import { Link } from "react-router-dom"
import { Cards } from "@phosphor-icons/react"
import { SectionHeading } from "./PathSection"
import type { WinView } from "./subjectModel"

export function WinList({ win, allTo }: { win: WinView; allTo: string }) {
  return (
    <section className="sj-win" aria-labelledby="sj-win-h">
      <SectionHeading id="sj-win-h" title={win.heading} to={allTo} />
      <ul>
        {win.rows.map((row) => (
          <li key={row.topic} className="sj-wrow">
            <Link to={row.practiceTo} className="sj-wmain lm-press">
              <span className="sj-at">
                <b>{row.name}</b>
                <span>Practise</span>
              </span>
              <span className="sj-wn">
                +{row.marks}
                <small> marks</small>
              </span>
            </Link>
            {row.flashcardsTo ? (
              <Link to={row.flashcardsTo} className="sj-fc lm-press lm-press-scale" aria-label={`${row.name} flashcards`}>
                <Cards size={18} aria-hidden="true" />
              </Link>
            ) : (
              <span className="sj-fcx" aria-hidden="true" />
            )}
          </li>
        ))}
      </ul>
    </section>
  )
}
```

(The subline reads "Practise", not the mock's "Practise · 10 min"; see Needs user decision 6.)

Create `web/src/portals/student/screens/subject/TopicsSection.tsx`:

```tsx
import { TopicChip, TopicChips } from "@/components/redesign"
import { SectionHeading } from "./PathSection"
import type { TopicChipView } from "./subjectModel"

/** The mock's legend: the three states with the kit's own icons. */
export function TopicLegend() {
  return (
    <div className="flex flex-wrap gap-3.5" aria-hidden="true">
      <TopicChip topic="Work on" state="work" />
      <TopicChip topic="Getting there" state="getting" />
      <TopicChip topic="Secure" state="secure" />
    </div>
  )
}

export function TopicsSection({
  chips,
  foldSecure,
  hint,
  onSelect,
}: {
  chips: TopicChipView[]
  foldSecure: boolean
  hint: string | null
  onSelect: (topic: string) => void
}) {
  const byLabel = new Map(chips.map((c) => [c.label, c.topic]))
  return (
    <section className="sj-sec" aria-labelledby="sj-topics-h">
      <SectionHeading id="sj-topics-h" title="Topics" />
      {chips.length > 0 ? (
        <TopicChips
          topics={chips.map((c) => ({ topic: c.label, state: c.state, pct: c.pct }))}
          foldSecure={foldSecure}
          onSelect={(label) => onSelect(byLabel.get(label) ?? label)}
        />
      ) : null}
      {hint ? <p className="sj-hint">{hint}</p> : null}
      {chips.length > 0 ? <TopicLegend /> : null}
    </section>
  )
}
```

Designer note: the mock legend (`.tleg`) is 12px text with 12px icons, gap 14px, no chip fill. If F1's `TopicChip` cannot render bare (no fill), replace `TopicLegend`'s chips with the kit's exported state icons; if F1 exports none, render the three phosphor icons F1 uses (`Target`, `Minus`, `Check`, per the F1 contract's "each with its icon") at 12px in `text-on-surface-variant`.

Create `web/src/portals/student/screens/subject/PapersList.tsx`:

```tsx
import type { CSSProperties } from "react"
import { CaretRight } from "@phosphor-icons/react"
import { HairRow, HairRows } from "@/components/redesign"
import { SectionHeading } from "./PathSection"
import type { PaperRowView } from "./subjectModel"

export function PapersList({ rows, visible, onShowAll }: { rows: PaperRowView[]; visible: number; onShowAll: () => void }) {
  return (
    <section className="sj-sec" aria-labelledby="sj-papers-h">
      <SectionHeading id="sj-papers-h" title="Papers" />
      <HairRows aria-label="Papers, newest first">
        {rows.slice(0, visible).map((row) => (
          <HairRow
            key={row.id}
            to={row.to}
            leading={
              <b className="sj-grade" style={{ "--c": row.colorVar } as CSSProperties}>
                {row.grade}
              </b>
            }
            title={row.title}
            sub={row.sub}
          />
        ))}
      </HairRows>
      {visible < rows.length ? (
        <button type="button" className="sj-more lm-press" onClick={onShowAll}>
          All {rows.length} papers
          <CaretRight size={12} weight="bold" aria-hidden="true" />
        </button>
      ) : null}
    </section>
  )
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npx vitest run tests/unit/subjectScreen.test.ts`
Expected: all tests pass.

- [ ] **Step 5: Lint gates and commit**

Run: `cd web && npm run typecheck && npx oxlint src/portals/student/screens/subject && npm run check:copy && npm run check:native`
Expected: all exit 0.

```bash
PYTHONPATH="$PWD" pre-commit run --files web/src/portals/student/screens/subject/TipSection.tsx web/src/portals/student/screens/subject/WinList.tsx web/src/portals/student/screens/subject/TopicsSection.tsx web/src/portals/student/screens/subject/PapersList.tsx web/tests/unit/subjectScreen.test.ts
git add web/src/portals/student/screens/subject/TipSection.tsx web/src/portals/student/screens/subject/WinList.tsx web/src/portals/student/screens/subject/TopicsSection.tsx web/src/portals/student/screens/subject/PapersList.tsx web/tests/unit/subjectScreen.test.ts
git commit -S -m "feat(web): subject tip, marks to win, topics and papers sections" -- web/src/portals/student/screens/subject/TipSection.tsx web/src/portals/student/screens/subject/WinList.tsx web/src/portals/student/screens/subject/TopicsSection.tsx web/src/portals/student/screens/subject/PapersList.tsx web/tests/unit/subjectScreen.test.ts
```

---

## Task 7: Header, body layout, first run, loading and error (designer)

**Agent:** `designer` (impeccable skill + craft floor first).

**Files:**
- Create: `web/src/portals/student/screens/subject/SubjectHeader.tsx`
- Create: `web/src/portals/student/screens/subject/SubjectBody.tsx`
- Create: `web/src/portals/student/screens/subject/SubjectFirstRun.tsx`
- Create: `web/src/portals/student/screens/subject/SubjectLoading.tsx`
- Create: `web/src/portals/student/screens/subject/SubjectError.tsx`
- Test: `web/tests/unit/subjectScreen.test.ts` (append)

**Interfaces:**
- Consumes: Tasks 3–6; F1 `CountdownPill`, `Walkthrough`, `Binny`; `PageHeading` (`@/components/ui/page-heading`); `SkeletonBlock` (`@/components/ui/skeleton`); `buttonVariants`.
- Produces:
  - `SubjectHeader(p: { title: string; subtitle: string; examDate: string | null; planTo: string; now: Date }): JSX.Element`
  - `SubjectBody(p: { view: SubjectView; code: string; wide: boolean; twoCol: boolean; onSelectPaper: (n: number) => void }): JSX.Element`
  - `SubjectFirstRun(p: { code: string; name: string; wide: boolean; twoCol: boolean }): JSX.Element`
  - `SubjectLoading(p: { name: string }): JSX.Element`
  - `SubjectError(p: { name: string; onRetry: () => void }): JSX.Element`

Class map: `.sjhd` / `.dtop` → `.sj-head` (the shell's top bar keeps title and back; this row keeps the `h1`, subtitle and pill); `.pill4` → F1 `CountdownPill` inside a `Link`; `.sjd` + `.sjl` / `.sjr` → `.sj-layout` + `.sj-col`; `.walk2` → F1 `Walkthrough`; `.sjh2` → `.sj-h2`; `.tmap.ghostc` → `.sj-ghostchips` + `.sj-ghostchip`; `.sk2c` / `.skbars` → `.sj-skel` / `.sj-skelbars` with `SkeletonBlock`; `.err2` → `.sj-err`.

- [ ] **Step 1: Write the failing test**

Append to `web/tests/unit/subjectScreen.test.ts`:

```ts
import { SubjectHeader } from "@/portals/student/screens/subject/SubjectHeader"
import { SubjectBody } from "@/portals/student/screens/subject/SubjectBody"
import { SubjectFirstRun } from "@/portals/student/screens/subject/SubjectFirstRun"
import { SubjectLoading } from "@/portals/student/screens/subject/SubjectLoading"
import { SubjectError } from "@/portals/student/screens/subject/SubjectError"

describe("SubjectHeader", () => {
  it("names the page in an h1 with the subtitle (K3, K6)", () => {
    const out = html(SubjectHeader, { title: "Mathematics", subtitle: "IGCSE · 0580 · Extended", examDate: null, planTo: "/student/plan/0580", now: NOW })
    expect(out).toMatch(/<h1[^>]*>Mathematics<\/h1>/)
    expect(out).toContain("IGCSE · 0580 · Extended")
    expect(out).not.toContain('href="/student/plan/0580"')
  })
  it("links the countdown pill to the study plan when an exam is dated", () => {
    const out = html(SubjectHeader, { title: "Mathematics", subtitle: "", examDate: "2025-05-27", planTo: "/student/plan/0580", now: NOW })
    expect(out).toContain('href="/student/plan/0580"')
  })
})

describe("SubjectBody", () => {
  it("renders every full-screen section in phone order", () => {
    const out = html(SubjectBody, { view: full, code: "0580", wide: false, twoCol: false, onSelectPaper: () => {} })
    const order = ["Your path to A*", "7 marks to A*", "More marks to win", "Topics", "Papers"].map((s) => out.indexOf(s))
    expect(order.every((i) => i >= 0)).toBe(true)
    expect([...order].sort((a, b) => a - b)).toEqual(order)
    expect(out.match(/class="sj-col"/g)).toHaveLength(2)
  })
  it("hides the win section when there is nothing to win", () => {
    const empty = { ...full, win: { heading: "More marks to win", rows: [] } }
    expect(html(SubjectBody, { view: empty, code: "0580", wide: false, twoCol: false, onSelectPaper: () => {} })).not.toContain("More marks to win")
  })
})

describe("first run, loading and error", () => {
  it("walks a new student through the first scan (K2)", () => {
    const out = html(SubjectFirstRun, { code: "0580", name: "Mathematics", wide: false, twoCol: false })
    expect(out).toContain("Your path to A*")
    expect(out).toContain("Let’s find your first step")
    expect(out).toContain("Scan a Mathematics paper")
    expect(out).toContain("Upload a PDF instead")
    expect(out).toContain("Lemely marks it")
    expect(out).toContain("Every Mathematics paper you mark lands here, newest first.")
  })
  it("marks the loading state busy and names it (K4)", () => {
    const out = html(SubjectLoading, { name: "Mathematics" })
    expect(out).toContain('aria-busy="true"')
    expect(out).toContain('aria-label="Loading Mathematics"')
  })
  it("offers a retry and a way home on error (K5)", () => {
    const out = html(SubjectError, { name: "Mathematics", onRetry: () => {} })
    expect(out).toContain("We couldn’t load Mathematics")
    expect(out).toContain("Check your connection, then try again. Your papers are safe.")
    expect(out).toContain("Try again")
    expect(out).toContain('href="/student"')
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run tests/unit/subjectScreen.test.ts`
Expected: FAIL with `Failed to resolve import "@/portals/student/screens/subject/SubjectHeader"`.

- [ ] **Step 3: Write the five components**

Create `web/src/portals/student/screens/subject/SubjectHeader.tsx`:

```tsx
import { Link } from "react-router-dom"
import { CountdownPill } from "@/components/redesign"
import { PageHeading } from "@/components/ui/page-heading"

/**
 * The page's own heading row. The shell's top bar keeps the title and back
 * (shell wins); on native the h1 is visually hidden because the shell's large
 * title repeats it (`repeatsTitle`).
 */
export function SubjectHeader({
  title,
  subtitle,
  examDate,
  planTo,
  now,
}: {
  title: string
  subtitle: string
  examDate: string | null
  planTo: string
  now: Date
}) {
  return (
    <div className="sj-head">
      <div className="sj-head-t">
        <PageHeading repeatsTitle={true} className="sj-title">
          {title}
        </PageHeading>
        {subtitle ? <span className="sj-sub">{subtitle}</span> : null}
      </div>
      {examDate ? (
        <Link to={planTo} className="lm-press lm-press-scale shrink-0" aria-label="Exam dates in your study plan">
          <CountdownPill examDate={examDate} now={now} />
        </Link>
      ) : null}
    </div>
  )
}
```

Create `web/src/portals/student/screens/subject/SubjectBody.tsx`:

```tsx
import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { PathSection } from "./PathSection"
import { PapersList } from "./PapersList"
import { TipSection } from "./TipSection"
import { TopicsSection } from "./TopicsSection"
import { WinList } from "./WinList"
import { links, visiblePapers, type SubjectView } from "./subjectModel"

/** Full and sparse. One column on phone; from 768px left = path, tip, win and right = topics, papers. */
export function SubjectBody({
  view,
  code,
  wide,
  twoCol,
  onSelectPaper,
}: {
  view: SubjectView
  code: string
  wide: boolean
  twoCol: boolean
  onSelectPaper: (n: number) => void
}) {
  const navigate = useNavigate()
  const [expanded, setExpanded] = useState(false)
  return (
    <div className="sj-layout">
      <div className="sj-col">
        <PathSection path={view.path} onSelect={onSelectPaper} />
        <TipSection tip={view.tip} size={wide ? 72 : twoCol ? 64 : 60} />
        {view.win.rows.length > 0 ? <WinList win={view.win} allTo={links.practice(code)} /> : null}
      </div>
      <div className="sj-col">
        <TopicsSection
          chips={view.chips}
          foldSecure={view.mode === "full" && !wide}
          hint={view.topicsHint}
          onSelect={(topic) => navigate(links.practice(code, topic))}
        />
        <PapersList rows={view.papers} visible={visiblePapers(view.papers.length, wide, expanded)} onShowAll={() => setExpanded(true)} />
      </div>
    </div>
  )
}
```

Create `web/src/portals/student/screens/subject/SubjectFirstRun.tsx`:

```tsx
import { Camera, ChartBar, Sparkle } from "@phosphor-icons/react"
import { Walkthrough } from "@/components/redesign"
import { GhostSteps } from "./SubjectSteps"
import { TipSection } from "./TipSection"
import { FIRST_RUN_STEPS, GHOST_CHIPS, firstRunTip } from "./subjectModel"

const ICONS = [Camera, Sparkle, ChartBar]

/** The live 404: no papers in this subject yet. */
export function SubjectFirstRun({ code, name, wide, twoCol }: { code: string; name: string; wide: boolean; twoCol: boolean }) {
  const steps = FIRST_RUN_STEPS(name).map((s, i) => ({ icon: ICONS[i], title: s.title, body: s.body }))
  return (
    <div className="sj-layout">
      <div className="sj-col">
        <section className="sj-sec" aria-labelledby="sj-path-h">
          <h2 id="sj-path-h" className="sj-h2">
            Your path to A*
          </h2>
          <GhostSteps />
        </section>
        <TipSection tip={firstRunTip(code, name)} size={wide ? 72 : twoCol ? 64 : 60} />
        <Walkthrough steps={steps} />
      </div>
      <div className="sj-col sj-col--aside-first-run">
        <section className="sj-sec" aria-labelledby="sj-topics-h">
          <h2 id="sj-topics-h" className="sj-h2">
            Topics
          </h2>
          <p className="sj-hint">Your strong and weak topics show up here after your first paper.</p>
          <div className="sj-ghostchips" aria-hidden="true">
            {GHOST_CHIPS.map((chip, i) => (
              <span key={i} className="sj-ghostchip" style={{ width: chip.width }} />
            ))}
          </div>
        </section>
        <section className="sj-sec" aria-labelledby="sj-papers-h">
          <h2 id="sj-papers-h" className="sj-h2">
            Papers
          </h2>
          <p className="sj-hint">Every {name} paper you mark lands here, newest first.</p>
        </section>
      </div>
    </div>
  )
}
```

Create `web/src/portals/student/screens/subject/SubjectLoading.tsx`:

```tsx
import { SkeletonBlock } from "@/components/ui/skeleton"

const BARS = [38, 50, 56, 84, 100]

/** Mock L_P: title bar, five bars, the tip block, three rows. Right column rows from 768px. */
export function SubjectLoading({ name }: { name: string }) {
  return (
    <div className="sj-layout" aria-busy="true" aria-label={`Loading ${name}`}>
      <div className="sj-col sj-skel">
        <SkeletonBlock announce={false} style={{ width: 150, height: 22 }} />
        <div className="sj-skelbars">
          {BARS.map((h) => (
            <SkeletonBlock key={h} announce={false} style={{ height: `${h}%` }} />
          ))}
        </div>
        <SkeletonBlock announce={false} style={{ height: 50, borderRadius: 16 }} />
        {[0, 1, 2].map((i) => (
          <SkeletonBlock key={i} announce={false} style={{ height: 52 }} />
        ))}
      </div>
      <div className="sj-col sj-skel sj-col--aside-first-run">
        {[0, 1, 2].map((i) => (
          <SkeletonBlock key={i} announce={false} style={{ height: 52 }} />
        ))}
      </div>
    </div>
  )
}
```

Before writing this file, open `web/src/components/ui/skeleton.tsx` and confirm the prop that silences the per-block status announcement (lines 23–30, `SkeletonBaseProps`); use that exact prop name in place of `announce` if it differs.

Create `web/src/portals/student/screens/subject/SubjectError.tsx`:

```tsx
import { Link } from "react-router-dom"
import { Binny } from "@/components/redesign"
import { buttonVariants } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import { links } from "./subjectModel"

/** Mock E_P. Any failure except 404 (which is the first run). */
export function SubjectError({ name, onRetry }: { name: string; onRetry: () => void }) {
  return (
    <div className="sj-err" role="alert">
      <Binny mood="sad" size={96} motion="idle" aria-hidden={true} />
      <h2>We couldn’t load {name}</h2>
      <p>Check your connection, then try again. Your papers are safe.</p>
      <button type="button" className={cn(buttonVariants({ variant: "primary", size: "lg" }), "sj-go")} onClick={onRetry}>
        Try again
      </button>
      <Link to={links.home} className="sj-upl">
        Back to Home
      </Link>
    </div>
  )
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npx vitest run tests/unit/subjectScreen.test.ts`
Expected: all tests pass.

- [ ] **Step 5: Lint gates and commit**

Run: `cd web && npm run typecheck && npx oxlint src/portals/student/screens/subject && npm run check:copy && npm run check:native`
Expected: all exit 0.

```bash
PYTHONPATH="$PWD" pre-commit run --files web/src/portals/student/screens/subject/SubjectHeader.tsx web/src/portals/student/screens/subject/SubjectBody.tsx web/src/portals/student/screens/subject/SubjectFirstRun.tsx web/src/portals/student/screens/subject/SubjectLoading.tsx web/src/portals/student/screens/subject/SubjectError.tsx web/tests/unit/subjectScreen.test.ts
git add web/src/portals/student/screens/subject/SubjectHeader.tsx web/src/portals/student/screens/subject/SubjectBody.tsx web/src/portals/student/screens/subject/SubjectFirstRun.tsx web/src/portals/student/screens/subject/SubjectLoading.tsx web/src/portals/student/screens/subject/SubjectError.tsx web/tests/unit/subjectScreen.test.ts
git commit -S -m "feat(web): subject header, layout and first-run, loading and error states" -- web/src/portals/student/screens/subject/SubjectHeader.tsx web/src/portals/student/screens/subject/SubjectBody.tsx web/src/portals/student/screens/subject/SubjectFirstRun.tsx web/src/portals/student/screens/subject/SubjectLoading.tsx web/src/portals/student/screens/subject/SubjectError.tsx web/tests/unit/subjectScreen.test.ts
```

---

## Task 8: Wire the screen and retire the old one (designer)

**Agent:** `designer`.

**Files:**
- Modify (full rewrite): `web/src/portals/student/screens/Subject.tsx`
- Modify: `web/tests/unit/subjectGlyph.test.ts:96-98` (remove the Subject assertion)
- Modify: `web/tests/unit/listGroup.test.ts:170-173` (remove the stat-tile assertion)
- Modify: `web/tests/unit/rtlSafety.test.ts:26` (add the new files)
- Modify: `web/tests/unit/utilityExistence.test.ts:52` (add the new files)

**Interfaces:**
- Consumes: everything above; `useSubject` (`@/lib/hooks/useStudentApi`), `useReference`, `useSubjectName` (`@/lib/hooks/useReferenceApi`), `useExamCalendar` (`@/lib/hooks/useAnnouncementApi`), `useFlashcardDecks` (`@/lib/hooks/useFlashcardApi`), `ApiError` (`@/lib/api`), `subjectIdentifier` (`@/lib/subjectIdentifier`).
- Produces: `export function Subject(): JSX.Element` (same export the route lazy-loads, K1).

Query keys used (all pre-existing, no new keys): `["student", "subject", code]`, `["reference"]` (`REFERENCE_KEY`), `["student", "exam-calendar"]`, `["flashcards", "decks", code]`.

- [ ] **Step 1: Update the source-scanning tests first (they go red against the new screen otherwise)**

In `web/tests/unit/subjectGlyph.test.ts`, delete the `it("the student Subject page's header renders SubjectGlyph beside the subject name", ...)` case (lines 96–98).

In `web/tests/unit/listGroup.test.ts`, delete the `it("Subject stat tiles opt out of the native bleed so they stay side by side", ...)` case (lines 170–173).

In `web/tests/unit/rtlSafety.test.ts` and `web/tests/unit/utilityExistence.test.ts`, directly under the existing `"src/portals/student/screens/Subject.tsx",` entry, add:

```ts
  "src/portals/student/screens/subject/SubjectSteps.tsx",
  "src/portals/student/screens/subject/PathSection.tsx",
  "src/portals/student/screens/subject/TipSection.tsx",
  "src/portals/student/screens/subject/WinList.tsx",
  "src/portals/student/screens/subject/TopicsSection.tsx",
  "src/portals/student/screens/subject/PapersList.tsx",
  "src/portals/student/screens/subject/SubjectHeader.tsx",
  "src/portals/student/screens/subject/SubjectBody.tsx",
  "src/portals/student/screens/subject/SubjectFirstRun.tsx",
  "src/portals/student/screens/subject/SubjectLoading.tsx",
  "src/portals/student/screens/subject/SubjectError.tsx",
```

- [ ] **Step 2: Rewrite the container**

Replace the whole of `web/src/portals/student/screens/Subject.tsx` with:

```tsx
/*
 * Subject (redesign L2, mock `.impeccable/mocks/student-r2/final.html`).
 * Wired to `GET /student/subject/{code}` via `useSubject(code)`. Thin on
 * purpose: `subject/subjectModel.ts` makes every decision (state, copy, Binny,
 * links, bar heights) and the `subject/*` files draw it. A 404 is a subject
 * with no papers yet and renders the first run, never an error (K2).
 */
import { useParams, useSearchParams } from "react-router-dom"
import { ApiError } from "@/lib/api"
import { useExamCalendar } from "@/lib/hooks/useAnnouncementApi"
import { useFlashcardDecks } from "@/lib/hooks/useFlashcardApi"
import { useReference, useSubjectName } from "@/lib/hooks/useReferenceApi"
import { useSubject } from "@/lib/hooks/useStudentApi"
import { subjectIdentifier } from "@/lib/subjectIdentifier"
import { SubjectBody } from "./subject/SubjectBody"
import { SubjectError } from "./subject/SubjectError"
import { SubjectFirstRun } from "./subject/SubjectFirstRun"
import { SubjectHeader } from "./subject/SubjectHeader"
import { SubjectLoading } from "./subject/SubjectLoading"
import { buildSubjectView, links, nextExamDate, selectScreenState, subtitleFor, tierLabel } from "./subject/subjectModel"
import { useMinWidth } from "./subject/useMinWidth"
import "./subject/subject.css"

export function Subject() {
  // The only route here is `subject/:code`, which cannot match without a code,
  // so `useSubject`'s `enabled: !!code` never parks this screen at idle.
  const { code = "" } = useParams<{ code: string }>()
  const query = useSubject(code)
  const fallbackName = useSubjectName(code)
  const { data: reference } = useReference()
  const { data: calendar } = useExamCalendar()
  const { data: decks = [] } = useFlashcardDecks(code)
  const [params, setParams] = useSearchParams()
  const wide = useMinWidth(1280)
  const twoCol = useMinWidth(768)
  const now = new Date()

  const catalogue = reference?.subjects.find((s) => s.code === code)
  const name = query.data?.header.name ?? fallbackName
  const state = selectScreenState({
    status: query.status,
    errorStatus: query.error instanceof ApiError ? query.error.status : null,
    paperCount: query.data?.paperHistory.length ?? 0,
  })
  const view =
    (state === "full" || state === "sparse") && query.data
      ? buildSubjectView({
          data: query.data,
          catalogue,
          decks,
          examDate: nextExamDate(calendar, code, now),
          now,
          requestedPaper: params.get("paper"),
          mode: state,
        })
      : null

  const { primary, secondary } = subjectIdentifier(
    reference?.qualificationLevels,
    name,
    code,
    query.data?.header.qualificationLevel ?? catalogue?.qualificationLevel,
  )
  const header = (
    <SubjectHeader
      title={primary}
      subtitle={subtitleFor(secondary, tierLabel(catalogue, view?.path.selected ?? null))}
      examDate={nextExamDate(calendar, code, now)}
      planTo={links.plan(code)}
      now={now}
    />
  )

  const selectPaper = (paperNumber: number) =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        next.set("paper", String(paperNumber))
        return next
      },
      { replace: true },
    )

  return (
    <div className="flex flex-col gap-4">
      {header}
      {state === "loading" ? <SubjectLoading name={name} /> : null}
      {state === "error" ? <SubjectError name={name} onRetry={() => void query.refetch()} /> : null}
      {state === "first-run" ? <SubjectFirstRun code={code} name={name} wide={wide} twoCol={twoCol} /> : null}
      {view ? <SubjectBody view={view} code={code} wide={wide} twoCol={twoCol} onSelectPaper={selectPaper} /> : null}
    </div>
  )
}
```

- [ ] **Step 3: Run the lane's unit tests and the source-scanning tests**

Run: `cd web && npx vitest run tests/unit/subjectModel.test.ts tests/unit/subjectScreen.test.ts tests/unit/subjectGlyph.test.ts tests/unit/listGroup.test.ts tests/unit/rtlSafety.test.ts tests/unit/utilityExistence.test.ts tests/unit/darkConsumers.test.ts tests/unit/navigation.test.ts tests/unit/studentShell.test.ts`
Expected: all pass. If `rtlSafety` or `utilityExistence` flag a class in a new file, fix the class in that file (logical property or a token-backed utility), never by removing the file from the list.

- [ ] **Step 4: Gates**

Run: `cd web && npm run typecheck && npm run lint && npm run check:copy`
Expected: all exit 0.

- [ ] **Step 5: See it run**

Run the dev stack (`/run` skill or the project's dev command) and open, logged in as a student with papers, `/student/subject/<code>` at 390px, 820px and 1280px; then a subject with no papers (first run) and with the API stopped (error). Confirm each state renders, the paper switch replays the bars, `?paper=` survives a reload, and `prefers-reduced-motion: reduce` (DevTools rendering panel) removes the grow and hover motion.

- [ ] **Step 6: Commit**

```bash
PYTHONPATH="$PWD" pre-commit run --files web/src/portals/student/screens/Subject.tsx web/tests/unit/subjectGlyph.test.ts web/tests/unit/listGroup.test.ts web/tests/unit/rtlSafety.test.ts web/tests/unit/utilityExistence.test.ts
git add web/src/portals/student/screens/Subject.tsx web/tests/unit/subjectGlyph.test.ts web/tests/unit/listGroup.test.ts web/tests/unit/rtlSafety.test.ts web/tests/unit/utilityExistence.test.ts
git commit -S -m "feat(web): ship the redesigned Subject screen" -- web/src/portals/student/screens/Subject.tsx web/tests/unit/subjectGlyph.test.ts web/tests/unit/listGroup.test.ts web/tests/unit/rtlSafety.test.ts web/tests/unit/utilityExistence.test.ts
```

---

## Task 9: Playwright happy path

**Agent:** `test-engineer`.

**Files:**
- Create: `web/e2e/subject.spec.ts`

**Interfaces:**
- Consumes: `readSeed()` (`web/e2e/seed.ts`), `watchConsole` (`web/e2e/console-errors.ts`); the seeded `correctedPaper` student (one persisted 0625 paper 1 attempt, 88%; `scripts/seed_e2e.py:2684-2688`), which lands on the **sparse** state; and 0580, where that student has nothing (**first run**).

- [ ] **Step 1: Write the spec**

Create `web/e2e/subject.spec.ts`:

```ts
import { expect, test } from "@playwright/test"
import { watchConsole } from "./console-errors"
import { readSeed } from "./seed"

/*
 * Subject (redesign L2). The seeded `correctedPaper` student has exactly one
 * 0625 paper, so 0625 is the sparse state; they have nothing in 0580, so it is
 * the first run (the endpoint's 404). Both are real API round trips.
 */

test("a student with one paper sees the sparse path and opens the paper", async ({ page }) => {
  const seed = readSeed()
  const errors = watchConsole(page)
  const student = seed.students.correctedPaper

  await page.goto("/login")
  await page.getByLabel("Email").fill(student.email)
  await page.getByLabel("Password").fill(student.password)
  await page.getByRole("button", { name: /sign in/i }).click()
  await expect(page).toHaveURL(/\/student$/, { timeout: 15_000 })

  await page.goto("/student/subject/0625")
  await expect(page.getByRole("heading", { level: 2, name: /^Your path to / })).toBeVisible({ timeout: 15_000 })
  await expect(page.getByRole("group", { name: /^Paper 1 marks so far:/ })).toBeVisible()
  await expect(page.getByText("One step so far. Two more papers show your trend.")).toBeVisible()
  await expect(page.getByText("Great start. Next paper?")).toBeVisible()
  await expect(page.getByRole("link", { name: "Scan your next paper" })).toHaveAttribute("href", "/student/correct?subject=0625")
  // One paper: no switch.
  await expect(page.getByRole("tablist", { name: "Choose a paper" })).toHaveCount(0)

  const papers = page.getByRole("list", { name: "Papers, newest first" })
  await expect(papers.getByRole("link")).toHaveCount(1)
  await papers.getByRole("link").click()
  await expect(page).toHaveURL(/\/student\/result\/\d+$/)

  await page.goto("/student/subject/0580")
  await expect(page.getByText("Let’s find your first step")).toBeVisible({ timeout: 15_000 })
  await expect(page.getByRole("link", { name: /^Scan a .+ paper$/ })).toHaveAttribute("href", "/student/correct?subject=0580")

  expect(errors()).toEqual([])
})
```

Before running, open `web/e2e/console-errors.ts` and match its exact API (the call returns either a getter function or an array; adapt the last assertion to that shape, as `student-journey.spec.ts` does).

- [ ] **Step 2: Run it**

Run: `cd web && npx playwright test e2e/subject.spec.ts`
Expected: `1 passed`. (Needs the e2e stack the config boots: Postgres, the seeded API and Vite. If the stack cannot boot locally, push and let CI run it; do not skip the test.)

- [ ] **Step 3: Commit**

```bash
PYTHONPATH="$PWD" pre-commit run --files web/e2e/subject.spec.ts
git add web/e2e/subject.spec.ts
git commit -S -m "test(e2e): subject sparse path and first run" -- web/e2e/subject.spec.ts
```

---

## Task 10: Fidelity screenshots, drift fixes, `/impeccable polish`

**Agent:** `designer` (impeccable skill + craft floor first).

**Files:**
- Modify: any `web/src/portals/student/screens/subject/*` file the drift fix touches.
- Scratch only (not committed): the screenshot script and images in the session scratchpad.

- [ ] **Step 1: Serve the mock**

Run (background): `python3 -m http.server 8765 --directory .impeccable/mocks`
Mock URL: `http://127.0.0.1:8765/student-r2/final.html`. Frames: `#F_P`, `#S_P`, `#Z_P`, `#L_P`, `#E_P` (390 wide), `#F_T` (tablet), `#F_D`, `#Z_D` (desktop).

- [ ] **Step 2: Capture pairs at 390 and 1280**

With Playwright (MCP browser tools or a scratch script), capture for each pair: the mock frame element screenshot, and the app page at the same viewport width (`390×844`, `1280×900`):

| Pair | Mock | App |
|---|---|---|
| full phone | `#F_P` | `/student/subject/<code with ≥2 papers>` at 390 |
| full desktop | `#F_D` | same at 1280 |
| sparse phone | `#S_P` | `/student/subject/0625` as `correctedPaper` at 390 |
| first run phone | `#Z_P` | `/student/subject/0580` at 390 |
| first run desktop | `#Z_D` | same at 1280 |
| loading phone | `#L_P` | throttle the subject request (DevTools/route delay) at 390 |
| error phone | `#E_P` | block `**/api/student/subject/**` with a 500 at 390 |

Save to `<scratchpad>/l02-fidelity/<pair>-{mock,app}.png` and put them side by side.

- [ ] **Step 3: Fix the drift**

Compare page content only (the shell's bar, rail and tab bar differ by design). Fix spacing, type, colour and alignment in `subject.css` or the section files. List every intentional difference for the PR body (expected: shell header instead of the mock's `.sjhd`; no page gradient background; "Practise" subline; no `!`; "Back to Home"; countdown pill text "N days" on desktop).

- [ ] **Step 4: Polish**

Run `/impeccable polish` on `web/src/portals/student/screens/subject/` and apply its fixes. Re-check dark mode (`data-theme="dark"`): current-bar letter contrast on `--md-on-primary` over each grade colour, the goal block tint, and the toggle thumb.

- [ ] **Step 5: Re-run the lane tests and commit the fixes**

Run: `cd web && npx vitest run tests/unit/subjectModel.test.ts tests/unit/subjectScreen.test.ts tests/unit/rtlSafety.test.ts tests/unit/utilityExistence.test.ts && npm run typecheck && npm run lint && npm run check:copy`
Expected: all pass.

```bash
PYTHONPATH="$PWD" pre-commit run --files $(git diff --name-only -- web/src/portals/student/screens/subject)
git commit -S -m "fix(web): subject fidelity drift and polish" -- web/src/portals/student/screens/subject
```

---

## Task 11: Keep-list check and old-code sweep

**Agent:** `verifier` (read-only) for the check; `implementer` for any fix it finds.

**Files:**
- Verify only, unless a gap is found.

- [ ] **Step 1: Walk the keep-list**

For each row K1–K26 above, open the new code or test that carries it and record the file:line in a checklist for the PR body. Any row without evidence is a blocker: fix it in its owning task's files and commit with explicit paths.

- [ ] **Step 2: Sweep for leftovers of the old screen**

Run each and expect no hits inside `web/src/portals/student/screens/Subject.tsx` or `web/src/portals/student/screens/subject/`:

```bash
git grep -n "QueryState\|PageHeaderSkeleton\|CardGridSkeleton\|SubjectGlyph\|vizText\|studentLoadFailureMessage\|data-native-bleed" -- web/src/portals/student/screens/Subject.tsx web/src/portals/student/screens/subject
git grep -n "TODO\|FIXME\|test\.skip\|\.only(" -- web/src/portals/student/screens/subject web/tests/unit/subjectModel.test.ts web/tests/unit/subjectScreen.test.ts web/e2e/subject.spec.ts lemely/web/subject_paths.py tests/test_subject_paths.py tests/test_web_student_subject_path.py
```

Expected: no output. (Shared imports such as `vizText` stay in their own modules; only their use on this screen is gone.)

- [ ] **Step 3: Final touched-file sweep**

Run:
```bash
PYTHONPATH="$PWD" /home/sico/Code/Lemely/.venv/bin/python -m pytest tests/test_subject_paths.py tests/test_web_student_subject_path.py tests/test_web_student.py -k "subject or paths" tests/test_web_quiz_origin_filtering.py tests/test_authz_matrix.py tests/test_authz_matrix_complete.py -q
cd web && npx vitest run tests/unit/subjectModel.test.ts tests/unit/subjectScreen.test.ts tests/unit/subjectGlyph.test.ts tests/unit/listGroup.test.ts tests/unit/rtlSafety.test.ts tests/unit/utilityExistence.test.ts tests/unit/darkConsumers.test.ts tests/unit/navigation.test.ts tests/unit/studentShell.test.ts && npm run typecheck && npm run lint && npm run check:copy
```
Expected: all pass. This sweep runs last; any later fix commit voids it and it is run again.

---

## Task 12: Push and open the PR

**Agent:** `git-master`.

- [ ] **Step 1: Rebase and re-verify**

```bash
git fetch origin && git rebase origin/develop
```
Resolve conflicts in `lemely/web/routers/student.py`, `lemely/web/schemas_student.py` and `web/src/lib/studentTypes.ts` by keeping both lanes' sections. Then re-run Task 11 Step 3.

- [ ] **Step 2: Push**

```bash
git push -u origin redesign/l02-subject
```

- [ ] **Step 3: Open the PR to `develop` (never `main`)**

```bash
gh pr create --base develop --head redesign/l02-subject --title "feat: redesigned student Subject screen (L2)" --body-file <scratchpad>/l02-pr-body.md
```

The body holds: what changed (endpoint additions, new screen, states); the keep-list K1–K26 with evidence; the frame-to-state table; the side-by-side screenshots (390 and 1280); the list of small deviations from the mock (Task 10 Step 3); the open "Needs user decision" items with the defaults this PR shipped; and the cross-lane dependencies. End with the attribution lines from the session's system reminder, if any.

---

## Cross-lane dependencies (beyond the master plan)

- **F1:** `TopicChips` items accept optional `pct?: number`, and `foldSecure` renders the "N secure" chip that unfolds in place; `BinnyLine` accepts `size`. Task 6 adds `pct` itself (optional, signature-compatible) if F1 lands without it.
- **L4 (practice set builder):** honours `/student/practice/:code?topic=<topic label>` to preselect that topic. Until then the link opens the subject's practice screen without the preselection.
- **L10 (flashcards):** honours `/student/flashcards/:code?deck=<id>` to open that deck. Until then it opens the deck list.
- **L6 (upload):** honours `/student/correct?subject=<code>` and `&source=file` (desktop upload). Until then both open the plain upload screen.
- **L1:** edits the same three shared files (`routers/student.py`, `schemas_student.py`, `studentTypes.ts`) in their Overview sections; L2 put its tests in a new file to stay out of `tests/test_web_student.py`.
- **L11 (parent subject):** draws the same Steps path (`pa.js` reuses `.stp`); L11 should reuse `SubjectSteps` rather than build a third copy (see Needs user decision 2).

## Migration

None. The boundary table (`component_thresholds`, read through `GradeBoundaryStore`) already holds the A* lines; everything else is derived from existing history records.

## Needs user decision

Each has a recommendation and the plan ships that default; none blocks the lane.

1. **Exclamation marks in Binny's lines.** The mock says "7 marks to A*!", "Let’s find your first step!", "Great start! Next paper?", but `check:copy` bans `!` in product copy. *Recommendation:* ship without `!` (as planned). Alternative: add an allowlist entry for Binny lines in `web/scripts/check_copy.mjs`.
2. **Where the Steps path component lives.** The F1 `StepsPath` contract has no marks, goal marks, gap or ghost slots, which this screen needs. *Recommendation:* L2 keeps `SubjectSteps` local now; promote it to `components/redesign` when L11 needs the same path.
3. **Topic chip tap.** The mock's chips go to an undefined "Topic: X". *Recommendation:* open practice for that topic (`?topic=`), the same target as the win rows.
4. **"All N papers".** No student papers list screen exists. *Recommendation:* expand the list in place.
5. **Section heading links.** The mock links every heading, but only practice has a destination. *Recommendation:* link "More marks to win" to the subject's practice screen and leave the other headings plain.
6. **"Practise · 10 min" subline.** No data backs "10 min". *Recommendation:* show "Practise" until L4 confirms the default set length.
7. **Error "Back to Subjects".** There is no Subjects tab route yet. *Recommendation:* "Back to Home" (`/student`) until F1 or L1 adds a Subjects route, then switch.
8. **Subject glyph.** The live screen shows `SubjectGlyph`; the approved mock does not. *Recommendation:* drop it (follow the mock) and remove the glyph test's Subject assertion.
9. **Weighted mean %.** It is dropped because the decision says "marks are the only unit". *Recommendation:* confirm the drop; the forecast grade stays in the trend line.
10. **Goal grade.** The goal is always the A* line (a Core paper's top grade, C). *Recommendation:* keep that, as the mock is approved; the student's own target grade could become a later option.
11. **Goal block tap.** The mock's "How the A* line is set" has no designed surface. *Recommendation:* an inline note under the trend line ("A* line from the May/Jun 2024 boundary."), toggled by the goal block.
12. **Copy using the full subject name.** The mock says "Scan a Maths paper". *Recommendation:* "Scan a Mathematics paper", using the catalogue name, with no hand-made short names.
