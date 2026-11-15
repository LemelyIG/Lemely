# L11 Parent Subject, Topics and Emails Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the parent subject screen, the parent weak-topics screen and the email part of notification preferences with the approved SB redesign (`.impeccable/mocks/student-r2/parent-final.html`), with the backend data those screens need and no live feature lost.

**Architecture:** Backend first. A pure core module ranks a child's topics by marks lost on each subject's last three papers, with trend, per-paper losses and this week's practice. A read-only repo reads study-plan, flashcard and teacher-assignment activity for a linked child. Both feed new fields on the existing `GET /api/parent/children/{child_id}/weaknesses` and `.../subjects/{code}` routes, which keep every current field. A new `parent_weekly_email_prefs` table (one migration) backs per-child, per-subject weekly flags on `GET`/`PUT /api/me/notification-preferences`. Frontend: typed API additions, then three pure view-model modules (all decisions live there), then thin screens built from the F1 kit.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, pytest (Postgres-backed), React 19, react-router 7, TanStack Query, Tailwind 4, Vitest (node env, `web/tests/unit/**`), Playwright.

**Spec:** `docs/superpowers/specs/2026-11-14-redesign-implementation-design.md` (wave 3, item 11). **Master plan:** `docs/superpowers/plans/2026-11-15-redesign-00-master.md`.

## Global Constraints

Inherits master plan Global Constraints (signed commits with explicit paths, touched tests only, no `main`, no token changes, migration downgrade plus user approval before any shared-DB run, shell wins, fidelity at 390/tablet/1280, reduced motion, taste memories, Binny rules, Mono for numbers, gold only for earned things, short copy, deps.py auth and tenancy, parent access through the parent link).

Lane-specific:
- **No Binny anywhere in this lane.** Parent screens never import `Binny` or `BinnyLine`.
- **Read-only parent API stays read-only.** No new mutation under `/api/parent/*`. The only write this lane adds is the weekly-email flag on `/api/me/notification-preferences`, scoped to `auth.user_id` and checked against the parent link.
- **Every existing response field stays on the wire, unchanged.** New fields are additive. `weakTopics` keeps its worst-accuracy-first order because `ChildOverview` and existing tests read it.
- **Settings controls never appear on the dashboard.** The weekly-email switch exists only on the Emails screen (`/parent/emails`).
- **Copy rules:** no em dashes, no exclamation marks (`npm run check:copy`). Minus sign in marks is U+2212 (`−9`). Curly apostrophe `’` in new copy, matching the mock.
- **Owned files:** `web/src/portals/parent/screens/SubjectDetail.tsx`, `Weaknesses.tsx`, `Emails.tsx`, and the new directories `web/src/portals/parent/screens/{subject,topics,emails,model,shared}/`. Backend: `lemely/core/parent_topics.py`, `lemely/db/child_topic_activity_repo.py`, `lemely/db/parent_weekly_email_repo.py`, `lemely/db/models/parent_prefs.py`, `lemely/web/weekly_summaries.py`, migration `0055_parent_weekly_email_prefs.py`. Narrow edits only to: `lemely/web/routers/parent.py`, `lemely/web/schemas_parent.py`, `lemely/web/routers/me.py`, `lemely/web/schemas_me.py`, `lemely/web/deps.py` (two getters), `lemely/db/models/__init__.py` (one import, one list entry), `web/src/lib/parentTypes.ts`, `web/src/lib/notificationPrefs.ts`, `web/src/portals/parent/index.tsx` (route entries and lazy imports for this lane's three screens only), `tests/test_web_parent.py` (one override line), `web/tests/unit/parentOutcome.test.ts` (one import path), `web/e2e/parent-journey.spec.ts` (journey b assertions).
- **Run Python** from the lane worktree root with `PYTHONPATH=$(pwd) /home/sico/Code/Lemely/.venv/bin/python -m pytest …` (the venv is shared across worktrees; pinning `PYTHONPATH` stops it importing another worktree's `lemely`). Postgres-backed tests skip when local Postgres is down; start it before running them.
- **Run web tests** from `web/`: `npx vitest run <files>`, `npx playwright test <spec>`.

---

## Keep-list (every live feature, checked off in Task 17)

Subject screen, `web/src/portals/parent/screens/SubjectDetail.tsx`:
- [ ] K1 Route params `childId`, `code` (`SubjectDetail.tsx:67`).
- [ ] K2 Loading skeleton while the query is pending (`:76-81`). Becomes FL1.
- [ ] K3 Load error heading "We couldn't load this subject" with a status-specific body from `parentLoadFailureMessage` (403 not linked, 404, network, 5xx) and a retry (`:82`, `lib/parentOutcome.ts`). Becomes FE1 with the same bodies and "Try again".
- [ ] K4 Subject name as the headline, level plus code as secondary, secondary omitted when empty (`:86-108`, `subjectIdentifier`).
- [ ] K5 Predicted grade from the latest grade-bearing paper (`:97`). Becomes "Predicted A" in the summary line.
- [ ] K6 Predicted-basis copy for one paper (`:58-59`). Becomes FS1's basis line. The many-paper sentence is dropped by the approved mock.
- [ ] K7 Boundary distance panel, "N more marks for an A" / "On track for an A" (`:121-146`). Superseded by the approved mock's goal block ("N to go" against the target, or A*). `boundaryDistance` stays on the wire.
- [ ] K8 `gradeArticle` ("an A", "a B") (`:51-53`). Moves to `model/subjectModel.ts`; `web/tests/unit/parentOutcome.test.ts` import updated.
- [ ] K9 Every marked paper, newest first, with grade, marks, paper id and when (`:148-175`). Becomes "Papers they’ve done": first 3 rows, "All N" expands in place to every paper. Row key stays `${paperId}-${recordedAt}`.
- [ ] K10 No-papers state (`:150-153`). Becomes FZ1, reached by the 404 "No papers for subject …".
- [ ] K11 Link from the topics section to the all-subjects list (`:180-185`). Becomes "All topics", opening the Topics tab filtered to this subject.
- [ ] K12 "Nothing stands out as a weak topic in this subject yet." (`:187-190`). Becomes FN1 with the subject name.
- [ ] K13 Weak topics with marks lost out of available (`:192-201`). Becomes ranked rows with "−N marks" and a bar.
- [ ] K14 No write on the screen (`:20-23`).
- [ ] K15 The shell crumb reads the cached subject name through `useCachedChildSubject` (`portals/parent/index.tsx`, `ParentTrail`). Query key `["parent","children",childId,"subjects",code]` unchanged.
- [ ] K16 Screen-reader heading while loading or failing (`:75`).

Topics screen, `web/src/portals/parent/screens/Weaknesses.tsx`:
- [ ] W1 Rows render in backend order and are never re-sorted client-side (`:36-38`). Applies to the new `topics` list.
- [ ] W2 Ordered-list semantics with the printed rank hidden from screen readers (`:53-59`, `:131`).
- [ ] W3 Opportunity framing, not failure framing (`:63-69`). Mock copy "−N marks", "Topics to work on".
- [ ] W4 Accuracy share labelled (`:83-90`). Superseded by marks lost (approved mock).
- [ ] W5 Page heading and intro (`:117-122`). Becomes "Topics to work on" plus the basis line.
- [ ] W6 "Nothing stands out yet. Weak topics appear here once a few papers have been marked." (`:125-129`). Kept as the "papers but nothing weak" state; TZ covers "no papers at all".
- [ ] W7 The honest gap note about practice (`:139-142`). Replaced by real "What they’re doing" data.
- [ ] W8 Loading skeleton and "We couldn't load this" with status body (`:101-111`). Becomes the topics loading state and TE.
- [ ] W9 Child switch keeps the topics tail (`portals/parent/index.tsx` `ChildSwitcher`). F1 owns the switcher; Task 15 checks the tail survives.

Backend:
- [ ] B1 403 unlinked, 404 unknown child, 422 malformed id on both routes (`lemely/web/routers/parent.py:114-133`).
- [ ] B2 Router-level `require_role(Role.parent)` (`parent.py:106`).
- [ ] B3 Papers, predicted grade and boundary distance are grade-bearing only (`parent.py:481`).
- [ ] B4 Quiz-only activity still reaches the weakness list (`tests/test_web_parent.py::test_quiz_only_subject_still_contributes_to_p04_weaknesses`). `weakTopics` unchanged; `topics` falls back to any-origin records for a quiz-only subject.
- [ ] B5 404 when a subject has no grade-bearing paper (`parent.py:482-483`).
- [ ] B6 `weakTopics` on all three parent routes unchanged.
- [ ] B7 `boundaryDistance` unchanged.

Notification preferences:
- [ ] N1 PUT is a partial update, omitted fields untouched (`lemely/web/routers/me.py:211`).
- [ ] N2 Role-gated fields 422 for a role that may not set them (`me.py:212-227`).
- [ ] N3 A `null` toggle is hidden, never shown as off (`web/src/lib/notificationPrefs.ts:231-238`).
- [ ] N4 Quiet hours both-or-neither and the generic `/settings/notifications` screen keep working for every role (unchanged files).
- [ ] N5 A failed save names the preference it failed on (`portals/settings/NotificationSettings.tsx:194`). The Emails screen shows the error on that row.
- [ ] N6 One key per PUT, never the whole object (`notificationPrefs.ts:89-94`). A weekly flip sends one `weeklySummaries` item.

---

## Frame-to-state table

Breakpoints follow the merged shell: phone < 768 (drawer, native tab bar), tablet 768–1279 (top-bar tabs), desktop ≥ 1280 (rail). Tailwind `md:` = 768, `xl:` = 1280.

| Frame | Component state | Breakpoint | Trigger |
|---|---|---|---|
| FA | `SubjectDetail` `ready`: summary line, Marks per paper (toggle when ≥ 2 series), Topics costing marks (≤ 4 rows, bars), Papers they’ve done (3 + "All N") | phone, tablet single column | `GET …/subjects/{code}` 200, `papers.length ≥ 2`, `topics.length ≥ 1` |
| FS1 | `ready` + sparse: one bar, basis "Based on the one paper they’ve had marked in {Subject} so far. More papers make this steadier.", no trend line | all | `papers.length === 1` |
| FZ1 | `first-run`: "Predicted –", "No papers yet", ghost path, basis "No marked {Subject} papers yet. Each paper {Child} scans adds a bar here.", 3-step walkthrough | all | 404 with detail starting "No papers for subject" and the child is in `useChildren()` |
| FN1 | `ready` + no topics: "Nothing stands out as a weak topic in {Subject} yet." under the Topics heading | all | `topics.length === 0` |
| FL1 | `loading`: skeleton title, 5 skeleton bars (38/50/56/84/100%), summary block, 3 rows | all | query pending |
| FE1 | `error`: "We couldn’t load this subject", status body, "Try again" (refetch), "All subjects" link to overview | all | query error other than first-run 404 |
| FDK | `ready` in two columns: left summary + Marks per paper, right Topics + Papers | ≥ 1280 | same as FA |
| WA | `Weaknesses` `ready`: subject filter chips (when ≥ 2 subjects), basis line, ranked rows with subject and "doing" | phone, tablet | `GET …/weaknesses` 200, `topics.length ≥ 1` |
| WS | `ready` + topic sheet open (bottom sheet, `side="adaptive"`): title, "{Subject} · −N marks on the last K papers", per-paper loss bars, "What {Child} is doing", message-teacher (see Needs user decision 1) | phone, tablet | tap a row |
| TZ | `first-run`: "Nothing to rank yet", "Topics costing {Child} marks show up here after his first marked paper." with 3 ghost rows | all | `topics.length === 0 && paperCount === 0` |
| (live W6) | `nothing-weak`: "Nothing stands out yet. Weak topics appear here once a few papers have been marked." | all | `topics.length === 0 && paperCount > 0` |
| TE | `error`: "We couldn’t load this", status body, "Try again" | all | query error |
| TDK | `ready` list + side panel: first row selected (`selected` on `RankRow`), panel shows the sheet content; filter chips sit in the page head | ≥ 1280 | same as WA |
| FM | `Emails` `ready`: "Emails", account email, "Weekly summary · {Child}" per linked child with a switch per subject, "Right away" with the parent-firing alerts | all (desktop centred, max 640px) | `GET /me/notification-preferences` 200 |
| (Emails loading/error) | skeleton rows / "We couldn’t load your email settings" + Try again | all | query pending / error |

Tablet: every screen is the phone layout at a 640px content column, centred; Topics uses the sheet. The fidelity pass (Task 16) screenshots 390, 768 and 1280.

---

## Interactions and motion

All values from `t.css`, `pa.css`, `sp.css`, `pr.css`, `ph.css`. `--ease` = `cubic-bezier(.2,.8,.2,1)`, which is the existing `--ease-out` token (`ease-out` utility).

| # | Interaction | Values | Owner | Reduced motion |
|---|---|---|---|---|
| M1 | Steps bars grow on mount and on paper switch | `grow2` from `scaleY(.4)`, `.7s var(--ease) both`, `transform-origin: bottom`; delays `0, .06, .12, .18, .26s` | F1 `StepsPath`. L11 sets `key={paperNumber}` so a switch remounts and replays | no animation (F1) |
| M2 | Bar hover lift | `translate: 0 -3px; filter: saturate(1.15)`, `.2s var(--ease)` | F1 `StepsPath` | no translate |
| M3 | Skeleton shimmer | `skm` `1.4s linear infinite`, gradient `surface-container-high → surface-container → surface-container-high`, `background-size: 200% 100%` | existing `SkeletonBlock` | static (existing) |
| M4 | Switch thumb | `transform .2s var(--ease)`, track 48×28, thumb 22, on `primary`, off `oklch(.72 .03 240)` | existing `Switch` (F1 restyle) | no transition |
| M5 | Topic sheet rise | `rvup` from `translateY(40%); opacity .4`, `.45s var(--ease) both`; scrim `oklch(.2 .03 245/.25)`; radius `28px 28px 0 0`, padding `22px 20px 26px`, gap 14 | merged shell `Sheet side="adaptive"` (shell wins); designer checks the shell's sheet matches and lists any difference in the PR | instant (shell) |
| M6 | Row hover | title colour → `primary` | `RankRow` (F1), paper rows `hover:[&_b]:text-primary` | n/a (colour only) |
| M7 | Focus ring | `outline: 2.5px solid primary; outline-offset: 2px; border-radius: 14px` on rows, chips, toggle, kid switcher | `focus-visible:outline-[2.5px] focus-visible:outline-offset-2 focus-visible:outline-primary rounded-[14px]` | n/a |
| M8 | Desktop selected row | `background: primary-container; border-radius: 14px; padding-inline: 8px`, no hairline | `RankRow selected` (F1) | n/a |
| M9 | Paper toggle | selected segment `bg-surface-container-lowest text-primary shadow-[0_1px_3px_oklch(0.3_0.05_240/0.18)]`, no movement animation in the mock | `subject/PaperToggle.tsx` | n/a |
| M10 | "All N" papers expand | instant in the mock; L11 adds nothing | `PapersDone` | n/a |

No other animation exists in the mock. Do not add any.

---

## Mock class to token map

| Mock | Tailwind / token |
|---|---|
| `--p` / `--pc` | `primary` / `primary-container` |
| `--v` | `on-surface-variant` |
| `--ink` | `on-surface` |
| `--ov` hairline | `outline-variant` (`shadow-[0_-1px_0_var(--color-outline-variant)]` or `border-t border-outline-variant`) |
| `--o` | `outline` |
| `--ok` | `success-text` |
| `--onerrc` | `on-error-container` |
| `--sh` | `surface-container-high` |
| `--ga --gA --gB --gC --gD` | `grade-a-star grade-a grade-b grade-c grade-d` (and `e f g u`) |
| `.sjhd h1` | `font-display text-[28px] font-extrabold leading-[1.1] tracking-[-0.03em] text-primary` |
| `.sjhd .s`, `.dtop .t2 .s` | `text-[13px] font-medium text-on-surface-variant` |
| `.sjpad` | `flex flex-col gap-6 px-[18px] pt-2` (shell adds tab-bar padding) |
| `.tgt` | `flex flex-wrap gap-4 text-[14px] font-medium text-on-surface-variant`; `b`: `ms-1 font-display text-[18px] font-extrabold`; separator `·` `me-4 text-outline` |
| `.sjh2` | `text-[18px] font-extrabold tracking-[-0.01em] text-on-surface` (via `H2Row`) |
| `.ptog` | `inline-flex gap-0.5 rounded-xl bg-surface-container-high p-[3px]`; button `min-h-9 rounded-[9px] px-3 text-[13px] font-semibold text-on-surface-variant` |
| `.trend2` | `m-0 text-[14px] font-medium text-on-surface-variant` |
| `.basis` | `mt-1 text-[13.5px] font-medium leading-[1.4] text-on-surface-variant` |
| `.rp` paper row | `HairRow` with `leading` = grade letter `font-display text-[28px] font-extrabold leading-none` coloured by grade |
| `.err2` | `flex flex-1 flex-col items-center justify-center gap-3 px-2 py-6 text-center`; h2 `font-display text-[28px] font-extrabold leading-[1.15] tracking-[-0.02em] text-primary text-balance`; p `max-w-[30ch] text-[15px] font-medium leading-[1.4] text-on-surface-variant` |
| `.btn.big4.go2` | `Button variant="primary" className="min-h-[50px] w-full rounded-[18px] text-[15.5px]"` |
| `.walk2` | F1 `Walkthrough` |
| `.sk2c`, `.skbars` | `grid gap-3.5`; bars `grid h-[108px] grid-cols-5 items-end gap-2`, each `SkeletonBlock rounded-[14px_14px_4px_4px]` |
| `.sfilt` | `-mx-[18px] flex gap-1.5 overflow-x-auto px-[18px] [scrollbar-width:none]`; chip `min-h-10 rounded-xl bg-surface-container-lowest px-3.5 text-[13.5px] font-semibold text-on-surface shadow-[inset_0_0_0_1.5px_var(--color-outline-variant)]`; selected `bg-primary text-on-primary shadow-none` |
| `.sdot` | `inline-block size-2 flex-none rounded-full` with the subject tone |
| `.lostp` | grid `gap-2`; row `grid grid-cols-[120px_minmax(0,1fr)_36px] items-center gap-2.5 text-[13px] font-medium text-on-surface-variant`; bar `h-2 rounded bg-[color-mix(in_oklch,var(--color-on-error-container),white_55%)]`; value `text-right font-mono text-[14px] font-bold text-on-error-container` |
| `.doing` | `grid gap-2 text-[14px] font-medium leading-[1.4] text-on-surface`; tick `text-success-text` |
| `.asg` | `rounded-md bg-primary-container px-1.5 py-[3px] text-[12px] font-bold leading-none text-primary whitespace-nowrap` |
| `.sside` | `flex flex-col gap-3.5 rounded-[22px] bg-surface-container-lowest p-5 shadow-[0_1px_3px_oklch(0.3_0.05_240/0.1)]` |
| `.spd` | `xl:grid xl:grid-cols-[minmax(0,1fr)_320px] xl:gap-6` |
| `.sjd` | `xl:grid xl:grid-cols-[minmax(0,1.05fr)_minmax(0,1fr)] xl:items-start xl:gap-12` |
| `.emr` | `grid min-h-16 grid-cols-[40px_minmax(0,1fr)_auto] items-center gap-3 py-3` + hairline |
| `.pti` | `grid size-10 place-items-center rounded-[13px] bg-primary-container text-primary` |

Subject dot tones (mock used three ad-hoc oklch values; this lane maps them to tokens, a small listed change): index of the subject in rank order, cycling `bg-grade-a`, `bg-primary`, `bg-tertiary`.

---

## File structure

Backend:
- `lemely/core/parent_topics.py` (new): pure ranking, trend, per-paper losses, practice tally.
- `lemely/db/child_topic_activity_repo.py` (new): study plan, flashcards due, open teacher assignment per `(subject, topic)` for one child.
- `lemely/db/models/parent_prefs.py` (new): `ParentWeeklyEmailPref` model.
- `lemely/db/migrations/versions/0055_parent_weekly_email_prefs.py` (new).
- `lemely/db/parent_weekly_email_repo.py` (new): read and upsert flags.
- `lemely/web/weekly_summaries.py` (new): builds the `weeklySummaries` list and applies updates, so `me.py` stays a thin router.
- `lemely/web/schemas_parent.py`, `lemely/web/routers/parent.py`, `lemely/web/schemas_me.py`, `lemely/web/routers/me.py`, `lemely/web/deps.py`, `lemely/db/models/__init__.py` (narrow edits).

Frontend:
- `web/src/lib/parentTypes.ts`, `web/src/lib/notificationPrefs.ts` (additive types and one helper).
- `web/src/portals/parent/screens/model/parentPaths.ts`, `topicCopy.ts`, `subjectModel.ts`, `topicsModel.ts`, `emailsModel.ts` (pure).
- `web/src/portals/parent/screens/shared/ParentPageHead.tsx`, `SubjectDot.tsx`, `LoadError.tsx`.
- `web/src/portals/parent/screens/SubjectDetail.tsx` + `subject/{SubjectSummary,PaperToggle,MarksPerPaper,TopicsCosting,PapersDone,SubjectStates}.tsx`.
- `web/src/portals/parent/screens/Weaknesses.tsx` + `topics/{SubjectFilter,TopicList,TopicDetail,TopicsStates,useWideLayout}.tsx|ts`.
- `web/src/portals/parent/screens/Emails.tsx` + `emails/EmailRow.tsx`.
- Tests: `web/tests/unit/parentTopicCopy.test.ts`, `parentSubjectModel.test.ts`, `parentTopicsModel.test.ts`, `parentEmailsModel.test.ts`, `notificationPrefsWeekly.test.ts`; `web/e2e/parent-redesign.spec.ts`.

---

### Task 1: Core topic ranking

**Files:**
- Create: `lemely/core/parent_topics.py`
- Test: `tests/test_parent_topics.py`

**Interfaces:**
- Produces: `rank_topics(records: Sequence[PaperRecord], *, now: datetime) -> list[RankedTopic]`; `paper_id(record) -> str`; dataclasses `RankedTopic(subject_code, topic, lost_marks, basis_papers, trend, papers, practice)`, `TopicPaperLoss(paper_id, recorded_at, lost_marks)`, `PracticeTally(count, awarded_marks, maximum_marks)`; `Trend = Literal["better","worse","same"]`; constants `RECENT_PAPERS = 3`, `PRACTICE_WINDOW = timedelta(days=7)`, `TREND_DEAD_BAND = 0.02`.

- [ ] **Step 1: Write the failing tests**

```python
"""Pure tests for :mod:`lemely.core.parent_topics` (lane L11)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from lemely.core.history import PaperRecord
from lemely.core.parent_topics import PracticeTally, rank_topics
from lemely.core.schemas import ExamMetadata, WeakArea

NOW = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)


def _area(topic: str, lost: int, maximum: int = 10) -> WeakArea:
    return WeakArea(
        topic=topic,
        lost_marks=lost,
        maximum_marks=maximum,
        accuracy=1 - lost / maximum,
        question_ids=["1"],
    )


def _rec(
    *areas: WeakArea,
    days_ago: int,
    subject: str = "0580",
    paper: int = 4,
    variant: int = 2,
    origin: str = "past_paper",
) -> PaperRecord:
    is_quiz = origin != "past_paper"
    return PaperRecord(
        student_id="s",
        metadata=ExamMetadata(
            subject_code=subject,
            paper_number=1 if is_quiz else paper,
            paper_variant=1 if is_quiz else variant,
            session_month="Specimen" if is_quiz else "May/June",
            session_year=None if is_quiz else 2024,
        ),
        awarded_marks=50,
        maximum_marks=80,
        percentage=62.5,
        grade="" if is_quiz else "B",
        weak_areas=list(areas),
        recorded_at=(NOW - timedelta(days=days_ago)).isoformat(),
        origin=origin,  # type: ignore[arg-type]
    )


def test_ranks_by_marks_lost_on_the_last_three_papers_only() -> None:
    records = [
        _rec(_area("Algebra", 9), days_ago=40),  # 4th newest: outside the basis
        _rec(_area("Vectors", 2), _area("Algebra", 1), days_ago=30),
        _rec(_area("Vectors", 3), days_ago=20),
        _rec(_area("Vectors", 4), _area("Algebra", 2), days_ago=10),
    ]
    ranked = rank_topics(records, now=NOW)
    assert [(t.topic, t.lost_marks) for t in ranked] == [("Vectors", 9), ("Algebra", 3)]
    assert ranked[0].basis_papers == 3


def test_per_paper_losses_are_newest_first_and_name_the_paper() -> None:
    records = [
        _rec(_area("Vectors", 2), days_ago=30, variant=3),
        _rec(_area("Vectors", 4), days_ago=10, variant=2),
    ]
    vectors = rank_topics(records, now=NOW)[0]
    assert [(p.paper_id, p.lost_marks) for p in vectors.papers] == [("0580/42", 4), ("0580/43", 2)]


def test_trend_compares_the_last_two_records_carrying_the_topic() -> None:
    better = rank_topics(
        [_rec(_area("T", 6), days_ago=20), _rec(_area("T", 3), days_ago=10)], now=NOW
    )[0]
    worse = rank_topics(
        [_rec(_area("T", 3), days_ago=20), _rec(_area("T", 6), days_ago=10)], now=NOW
    )[0]
    same = rank_topics(
        [_rec(_area("T", 3), days_ago=20), _rec(_area("T", 3), days_ago=10)], now=NOW
    )[0]
    single = rank_topics([_rec(_area("T", 3), days_ago=10)], now=NOW)[0]
    assert (better.trend, worse.trend, same.trend, single.trend) == (
        "better",
        "worse",
        "same",
        "same",
    )


def test_practice_counts_this_weeks_quizzes_on_the_topic_and_sums_marks() -> None:
    records = [
        _rec(_area("Vectors", 4), days_ago=10),
        _rec(_area("Vectors", 1, maximum=5), days_ago=2, origin="quiz"),
        _rec(_area("Vectors", 1, maximum=4), days_ago=6, origin="quiz"),
        _rec(_area("Vectors", 0, maximum=5), days_ago=9, origin="quiz"),  # older than 7 days
        _rec(_area("Algebra", 2), days_ago=1, origin="quiz"),  # other topic
    ]
    vectors = next(t for t in rank_topics(records, now=NOW) if t.topic == "Vectors")
    assert vectors.practice == PracticeTally(count=2, awarded_marks=7, maximum_marks=9)


def test_quiz_only_subject_falls_back_to_any_origin_records() -> None:
    records = [_rec(_area("Waves", 3), days_ago=3, subject="0625", origin="quiz")]
    ranked = rank_topics(records, now=NOW)
    assert [(t.subject_code, t.topic, t.lost_marks) for t in ranked] == [("0625", "Waves", 3)]


def test_topics_with_no_lost_marks_in_the_basis_are_left_out() -> None:
    records = [_rec(_area("Vectors", 0), _area("Algebra", 2), days_ago=5)]
    assert [t.topic for t in rank_topics(records, now=NOW)] == ["Algebra"]


def test_ties_break_by_subject_then_topic_across_subjects() -> None:
    records = [
        _rec(_area("Waves", 4), days_ago=5, subject="0625"),
        _rec(_area("Vectors", 4), _area("Algebra", 4), days_ago=5, subject="0580"),
    ]
    assert [(t.subject_code, t.topic) for t in rank_topics(records, now=NOW)] == [
        ("0580", "Algebra"),
        ("0580", "Vectors"),
        ("0625", "Waves"),
    ]


def test_no_records_ranks_nothing() -> None:
    assert rank_topics([], now=NOW) == []
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `PYTHONPATH=$(pwd) /home/sico/Code/Lemely/.venv/bin/python -m pytest tests/test_parent_topics.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'lemely.core.parent_topics'`.

- [ ] **Step 3: Write the module**

```python
"""Parent topic ranking for the redesigned parent screens (lane L11).

:func:`rank_topics` turns a child's history into the "Topics costing marks"
list. For every subject it takes the topics that lost marks on that subject's
last three papers, ranks them by marks lost, and adds a Better/Worse/Same
trend and the child's own practice on the topic this week. Pure: no I/O, and
``now`` is injected.

**Basis.** Past papers only (:func:`~lemely.core.history.is_paper`). A
subject with no past paper falls back to its last three records of any
origin, so a quiz-only subject still has a list (the P-04 screen this
replaces surfaced quiz-only topics too).

**Trend.** The topic's accuracy on the latest record in the basis pool that
carries it, against the one before, with
:func:`~lemely.core.analytics.compare_performance`'s ±0.02 dead band. One
record reads as "same".

**Practice.** Quiz-origin records of the same subject from the last seven
days whose ``weak_areas`` carry the topic. ``awarded_marks`` and
``maximum_marks`` sum that topic's marks across those records.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Literal

from lemely.core.history import PaperRecord, is_paper

if TYPE_CHECKING:
    from collections.abc import Sequence

    from lemely.core.schemas import WeakArea

RECENT_PAPERS = 3
PRACTICE_WINDOW = timedelta(days=7)
TREND_DEAD_BAND = 0.02

Trend = Literal["better", "worse", "same"]


@dataclass(frozen=True, slots=True)
class TopicPaperLoss:
    """Marks a topic lost on one basis paper."""

    paper_id: str
    recorded_at: str
    lost_marks: int


@dataclass(frozen=True, slots=True)
class PracticeTally:
    """This week's practice on a topic."""

    count: int = 0
    awarded_marks: int = 0
    maximum_marks: int = 0


@dataclass(frozen=True, slots=True)
class RankedTopic:
    """One ranked row: a topic in a subject and what it is costing."""

    subject_code: str
    topic: str
    lost_marks: int
    basis_papers: int
    trend: Trend
    papers: tuple[TopicPaperLoss, ...]
    practice: PracticeTally


def paper_id(record: PaperRecord) -> str:
    """Human paper identity, ``"0580/42"`` (subject/paper+variant)."""
    m = record.metadata
    return f"{m.subject_code}/{m.paper_number}{m.paper_variant}"


def _parse(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _area(record: PaperRecord, topic: str) -> WeakArea | None:
    return next((a for a in record.weak_areas if a.topic == topic), None)


def _trend(pool: list[PaperRecord], topic: str) -> Trend:
    accuracies = [area.accuracy for r in pool if (area := _area(r, topic)) is not None]
    if len(accuracies) < 2:
        return "same"
    delta = accuracies[-1] - accuracies[-2]
    if delta > TREND_DEAD_BAND:
        return "better"
    if delta < -TREND_DEAD_BAND:
        return "worse"
    return "same"


def _practice(records: list[PaperRecord], topic: str, now: datetime) -> PracticeTally:
    count = awarded = maximum = 0
    for record in records:
        if is_paper(record):
            continue
        when = _parse(record.recorded_at)
        if when is None or not (now - PRACTICE_WINDOW <= when <= now):
            continue
        area = _area(record, topic)
        if area is None:
            continue
        count += 1
        awarded += area.maximum_marks - area.lost_marks
        maximum += area.maximum_marks
    return PracticeTally(count=count, awarded_marks=awarded, maximum_marks=maximum)


def rank_topics(records: Sequence[PaperRecord], *, now: datetime) -> list[RankedTopic]:
    """Rank every subject's costly topics, most marks lost first.

    ``records`` is a child's history in recorded order (oldest first), as
    :class:`~lemely.core.history.StudentHistory` stores it.
    """
    by_subject: dict[str, list[PaperRecord]] = {}
    for record in records:
        by_subject.setdefault(record.metadata.subject_code, []).append(record)

    ranked: list[RankedTopic] = []
    for subject, subject_records in by_subject.items():
        papers = [r for r in subject_records if is_paper(r)]
        pool = papers or subject_records
        basis = pool[-RECENT_PAPERS:]
        losses: dict[str, list[TopicPaperLoss]] = {}
        for record in reversed(basis):
            for area in record.weak_areas:
                if area.lost_marks > 0:
                    losses.setdefault(area.topic, []).append(
                        TopicPaperLoss(paper_id(record), record.recorded_at, area.lost_marks)
                    )
        for topic, paper_losses in losses.items():
            ranked.append(
                RankedTopic(
                    subject_code=subject,
                    topic=topic,
                    lost_marks=sum(p.lost_marks for p in paper_losses),
                    basis_papers=len(basis),
                    trend=_trend(pool, topic),
                    papers=tuple(paper_losses),
                    practice=_practice(subject_records, topic, now),
                )
            )
    ranked.sort(key=lambda t: (-t.lost_marks, t.subject_code, t.topic))
    return ranked


__all__ = [
    "PRACTICE_WINDOW",
    "RECENT_PAPERS",
    "TREND_DEAD_BAND",
    "PracticeTally",
    "RankedTopic",
    "TopicPaperLoss",
    "Trend",
    "paper_id",
    "rank_topics",
]
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `PYTHONPATH=$(pwd) /home/sico/Code/Lemely/.venv/bin/python -m pytest tests/test_parent_topics.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
PYTHONPATH=$(pwd) pre-commit run --files lemely/core/parent_topics.py tests/test_parent_topics.py
git add lemely/core/parent_topics.py tests/test_parent_topics.py
git commit -S -m "feat(parent): rank topics by marks lost on the last three papers" -- lemely/core/parent_topics.py tests/test_parent_topics.py
```

---

### Task 2: Child topic activity reader

**Files:**
- Create: `lemely/db/child_topic_activity_repo.py`
- Modify: `lemely/web/deps.py` (add one getter after `get_parent_link_service`)
- Test: `tests/test_child_topic_activity_repo.py`

**Interfaces:**
- Consumes: models `StudyPlan`, `StudyPlanSession` (`lemely/db/models/study_plan.py`), `FlashcardDeck`, `Flashcard` (`flashcards.py`), `Quiz`, `QuizAssignment`, `QuizSubmission` (`quizzes.py`), `ClassEnrollment` (`orgs.py`), `User` (`users.py`), enums `QuizKind`, `QuizStatus`, `QuizSubmissionStatus`.
- Produces: `TopicKey = tuple[str, str]` (subject_code, topic); `TopicAssignment(teacher_name: str | None, due_at: datetime | None)`; `TopicActivity(in_plan_this_week: bool = False, flashcards_due: int = 0, assignment: TopicAssignment | None = None)`; `ChildTopicActivityReader(sessionmaker).activity_for(child_id, keys, *, now) -> dict[TopicKey, TopicActivity]` (every requested key present; topic match is case-insensitive); `get_child_topic_activity_reader() -> ChildTopicActivityReader` in `lemely/web/deps.py`.

Tenancy: every query is scoped by `child_id`, which callers only pass after `_authorized_child` proved the parent link. Assignments are found through the child's own enrolments or a direct student target, never by subject alone. Teacher name is `users.display_name` only (never the email fallback, so a teacher's email never reaches a parent); `None` when unset.

- [ ] **Step 1: Write the failing tests**

```python
"""Postgres-backed tests for :mod:`lemely.db.child_topic_activity_repo` (lane L11)."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING

from lemely.db.child_topic_activity_repo import (
    ChildTopicActivityReader,
    TopicActivity,
    TopicAssignment,
)
from lemely.db.class_repo import ClassService
from lemely.db.models.enums import QuizKind, QuizStatus, QuizSubmissionStatus, Role
from lemely.db.models.flashcards import CardSource, DeckOrigin, Flashcard, FlashcardDeck
from lemely.db.models.quizzes import Quiz, QuizAssignment, QuizSubmission
from lemely.db.models.study_plan import StudyPlan, StudyPlanActivityType, StudyPlanSession
from tests.test_web_parent import _seed_user, pg_sessionmaker  # noqa: F401

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker

NOW = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)  # a Wednesday
MONDAY = date(2026, 11, 16)


def _plan(sm: sessionmaker[Session], child: uuid.UUID, topic: str, *, week: date = MONDAY,
          superseded: bool = False, subject: str = "0580") -> None:
    with sm.begin() as s:
        plan = StudyPlan(
            user_id=child,
            subject_code=subject,
            week_start=week,
            weekly_hours=3.0,
            available=True,
            generated_at=NOW,
            superseded_at=NOW if superseded else None,
        )
        s.add(plan)
        s.flush()
        s.add(
            StudyPlanSession(
                plan_id=plan.id,
                date=week + timedelta(days=2),
                topic=topic,
                activity_type=StudyPlanActivityType.practice,
                duration_minutes=20,
                focus="Practice",
            )
        )


def _deck(sm: sessionmaker[Session], child: uuid.UUID, topic: str, due_offsets: list[int]) -> None:
    with sm.begin() as s:
        deck = FlashcardDeck(
            user_id=child, subject_code="0580", topic=topic, title=topic, origin=DeckOrigin.topic
        )
        s.add(deck)
        s.flush()
        for i, offset in enumerate(due_offsets):
            s.add(
                Flashcard(
                    deck_id=deck.id,
                    front=f"f{i}",
                    back=f"b{i}",
                    position=i,
                    source=CardSource.manual,
                    due_at=NOW + timedelta(days=offset),
                )
            )


def _assign(sm: sessionmaker[Session], teacher: uuid.UUID, topics: list[str], *,
            class_id: uuid.UUID | None = None, student_id: uuid.UUID | None = None,
            due: datetime | None = None, closes: datetime | None = None,
            status: QuizStatus = QuizStatus.assigned) -> uuid.UUID:
    with sm.begin() as s:
        quiz = Quiz(
            teacher_id=teacher,
            kind=QuizKind.teacher,
            subject_code="0580",
            title="Set",
            status=status,
            included_topics=topics,
        )
        s.add(quiz)
        s.flush()
        assignment = QuizAssignment(
            quiz_id=quiz.id,
            class_id=class_id,
            student_id=student_id,
            assigned_by=teacher,
            due_at=due,
            closes_at=closes,
        )
        s.add(assignment)
        s.flush()
        return assignment.id


def test_unknown_activity_reads_as_all_defaults_for_every_key(
    pg_sessionmaker: sessionmaker[Session],  # noqa: F811
) -> None:
    child = _seed_user(pg_sessionmaker, Role.student)
    reader = ChildTopicActivityReader(pg_sessionmaker)
    keys = [("0580", "Vectors"), ("0625", "Waves")]
    assert reader.activity_for(child, keys, now=NOW) == {k: TopicActivity() for k in keys}
    assert reader.activity_for(child, [], now=NOW) == {}


def test_this_weeks_active_plan_marks_the_topic_case_insensitively(
    pg_sessionmaker: sessionmaker[Session],  # noqa: F811
) -> None:
    child = _seed_user(pg_sessionmaker, Role.student)
    _plan(pg_sessionmaker, child, "vectors")
    _plan(pg_sessionmaker, child, "Algebra", week=MONDAY - timedelta(days=7))  # last week
    _plan(pg_sessionmaker, child, "Trigonometry", superseded=True)
    got = ChildTopicActivityReader(pg_sessionmaker).activity_for(
        child, [("0580", "Vectors"), ("0580", "Algebra"), ("0580", "Trigonometry")], now=NOW
    )
    assert got[("0580", "Vectors")].in_plan_this_week is True
    assert got[("0580", "Algebra")].in_plan_this_week is False
    assert got[("0580", "Trigonometry")].in_plan_this_week is False


def test_flashcards_due_counts_only_cards_due_now_in_topic_decks(
    pg_sessionmaker: sessionmaker[Session],  # noqa: F811
) -> None:
    child = _seed_user(pg_sessionmaker, Role.student)
    other = _seed_user(pg_sessionmaker, Role.student)
    _deck(pg_sessionmaker, child, "Algebra", [-1, 0, 3])
    _deck(pg_sessionmaker, other, "Algebra", [-1])
    got = ChildTopicActivityReader(pg_sessionmaker).activity_for(child, [("0580", "Algebra")], now=NOW)
    assert got[("0580", "Algebra")].flashcards_due == 2


def test_open_class_assignment_names_the_teacher_and_due_date(
    pg_sessionmaker: sessionmaker[Session],  # noqa: F811
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher, display_name="Ms Adel")
    child = _seed_user(pg_sessionmaker, Role.student)
    classes = ClassService(pg_sessionmaker)
    cls = classes.create_class(teacher, "Maths 10B", subject_code="0580")
    assert cls.join_code is not None
    classes.join_by_code(child, cls.join_code)
    due = NOW + timedelta(days=2)
    _assign(pg_sessionmaker, teacher, ["Vectors"], class_id=cls.class_id, due=due)
    got = ChildTopicActivityReader(pg_sessionmaker).activity_for(child, [("0580", "Vectors")], now=NOW)
    assert got[("0580", "Vectors")].assignment == TopicAssignment(teacher_name="Ms Adel", due_at=due)


def test_submitted_closed_draft_and_other_childs_assignments_are_ignored(
    pg_sessionmaker: sessionmaker[Session],  # noqa: F811
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher, display_name="Ms Adel")
    child = _seed_user(pg_sessionmaker, Role.student)
    stranger = _seed_user(pg_sessionmaker, Role.student)
    done = _assign(pg_sessionmaker, teacher, ["Vectors"], student_id=child)
    with pg_sessionmaker.begin() as s:
        s.add(QuizSubmission(assignment_id=done, student_id=child, status=QuizSubmissionStatus.submitted))
    _assign(pg_sessionmaker, teacher, ["Algebra"], student_id=child, closes=NOW - timedelta(days=1))
    _assign(pg_sessionmaker, teacher, ["Moments"], student_id=child, status=QuizStatus.draft)
    _assign(pg_sessionmaker, teacher, ["Waves"], student_id=stranger)
    got = ChildTopicActivityReader(pg_sessionmaker).activity_for(
        child,
        [("0580", "Vectors"), ("0580", "Algebra"), ("0580", "Moments"), ("0580", "Waves")],
        now=NOW,
    )
    assert all(a.assignment is None for a in got.values())


def test_teacher_without_display_name_reads_as_none_never_an_email(
    pg_sessionmaker: sessionmaker[Session],  # noqa: F811
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    child = _seed_user(pg_sessionmaker, Role.student)
    _assign(pg_sessionmaker, teacher, ["Vectors"], student_id=child)
    got = ChildTopicActivityReader(pg_sessionmaker).activity_for(child, [("0580", "Vectors")], now=NOW)
    assignment = got[("0580", "Vectors")].assignment
    assert assignment is not None
    assert assignment.teacher_name is None
```

- [ ] **Step 2: Run to see them fail**

Run: `PYTHONPATH=$(pwd) /home/sico/Code/Lemely/.venv/bin/python -m pytest tests/test_child_topic_activity_repo.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'lemely.db.child_topic_activity_repo'`.

- [ ] **Step 3: Write the reader**

```python
"""What a child is doing about each costly topic (lane L11, "What they’re doing").

Read-only, keyed by a child id the caller has already authorised through the
parent link (:func:`lemely.web.routers.parent._authorized_child`). Three
signals, one query each:

* **In this week's plan:** a session on the topic in the child's active
  (``superseded_at IS NULL``) study plan for the current ISO week.
* **Flashcards due:** cards due now in the child's decks whose ``topic``
  matches.
* **Assigned:** an open teacher quiz (``kind = teacher``, ``status =
  assigned``, not closed) that targets the child directly or one of the
  child's classes, includes the topic, and has no submitted or marked
  submission from the child. The earliest due date wins.

Topic matching is case-insensitive (study-plan and deck topics are typed by
different code paths). The teacher's name is ``users.display_name`` only, never
the email fallback ``ClassService.display_name_for`` uses, so a teacher's
address never reaches a parent.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import func, or_, select

from lemely.db.models.enums import QuizKind, QuizStatus, QuizSubmissionStatus
from lemely.db.models.flashcards import Flashcard, FlashcardDeck
from lemely.db.models.orgs import ClassEnrollment
from lemely.db.models.quizzes import Quiz, QuizAssignment, QuizSubmission
from lemely.db.models.study_plan import StudyPlan, StudyPlanSession
from lemely.db.models.users import User

if TYPE_CHECKING:
    from collections.abc import Iterable

    from sqlalchemy.orm import Session, sessionmaker

TopicKey = tuple[str, str]


@dataclass(frozen=True, slots=True)
class TopicAssignment:
    teacher_name: str | None
    due_at: datetime | None


@dataclass(frozen=True, slots=True)
class TopicActivity:
    in_plan_this_week: bool = False
    flashcards_due: int = 0
    assignment: TopicAssignment | None = None


def _fold(key: TopicKey) -> TopicKey:
    return (key[0], key[1].casefold())


class ChildTopicActivityReader:
    """Reads plan, flashcard and assignment activity for one child."""

    def __init__(self, sessionmaker: sessionmaker[Session]) -> None:
        self._sessionmaker = sessionmaker

    def activity_for(
        self, child_id: uuid.UUID | str, keys: Iterable[TopicKey], *, now: datetime
    ) -> dict[TopicKey, TopicActivity]:
        wanted = list(dict.fromkeys(keys))
        if not wanted:
            return {}
        child = child_id if isinstance(child_id, uuid.UUID) else uuid.UUID(str(child_id))
        subjects = sorted({subject for subject, _ in wanted})
        week_start = now.date() - timedelta(days=now.weekday())

        with self._sessionmaker() as session:
            plan_rows = session.execute(
                select(StudyPlan.subject_code, StudyPlanSession.topic)
                .join(StudyPlanSession, StudyPlanSession.plan_id == StudyPlan.id)
                .where(
                    StudyPlan.user_id == child,
                    StudyPlan.week_start == week_start,
                    StudyPlan.superseded_at.is_(None),
                    StudyPlan.subject_code.in_(subjects),
                )
            ).all()
            card_rows = session.execute(
                select(FlashcardDeck.subject_code, FlashcardDeck.topic, func.count(Flashcard.id))
                .join(Flashcard, Flashcard.deck_id == FlashcardDeck.id)
                .where(
                    FlashcardDeck.user_id == child,
                    FlashcardDeck.subject_code.in_(subjects),
                    FlashcardDeck.topic.is_not(None),
                    Flashcard.due_at <= now,
                )
                .group_by(FlashcardDeck.subject_code, FlashcardDeck.topic)
            ).all()
            class_ids = select(ClassEnrollment.class_id).where(ClassEnrollment.student_id == child)
            finished = select(QuizSubmission.assignment_id).where(
                QuizSubmission.student_id == child,
                QuizSubmission.status.in_(
                    [QuizSubmissionStatus.submitted, QuizSubmissionStatus.marked]
                ),
            )
            assignment_rows = session.execute(
                select(Quiz.subject_code, Quiz.included_topics, QuizAssignment.due_at, User.display_name)
                .join(QuizAssignment, QuizAssignment.quiz_id == Quiz.id)
                .join(User, User.id == QuizAssignment.assigned_by)
                .where(
                    Quiz.kind == QuizKind.teacher,
                    Quiz.status == QuizStatus.assigned,
                    Quiz.subject_code.in_(subjects),
                    or_(QuizAssignment.student_id == child, QuizAssignment.class_id.in_(class_ids)),
                    or_(QuizAssignment.closes_at.is_(None), QuizAssignment.closes_at > now),
                    QuizAssignment.id.not_in(finished),
                )
                .order_by(QuizAssignment.due_at.asc().nulls_last())
            ).all()

        in_plan = {_fold((subject, topic)) for subject, topic in plan_rows}
        due_cards: dict[TopicKey, int] = {}
        for subject, topic, count in card_rows:
            key = _fold((subject, topic))
            due_cards[key] = due_cards.get(key, 0) + int(count)
        assigned: dict[TopicKey, TopicAssignment] = {}
        for subject, topics, due_at, teacher_name in assignment_rows:
            for topic in topics or []:
                if isinstance(topic, str):
                    assigned.setdefault(
                        _fold((subject, topic)),
                        TopicAssignment(teacher_name=teacher_name, due_at=due_at),
                    )

        return {
            key: TopicActivity(
                in_plan_this_week=_fold(key) in in_plan,
                flashcards_due=due_cards.get(_fold(key), 0),
                assignment=assigned.get(_fold(key)),
            )
            for key in wanted
        }


__all__ = ["ChildTopicActivityReader", "TopicActivity", "TopicAssignment", "TopicKey"]
```

Add to `lemely/web/deps.py`, directly after `get_parent_link_service`, and add `from lemely.db.child_topic_activity_repo import ChildTopicActivityReader` to the import block in alphabetical position:

```python
@lru_cache(maxsize=1)
def get_child_topic_activity_reader() -> ChildTopicActivityReader:
    """Return the process-wide :class:`ChildTopicActivityReader` (lane L11).

    Read-only and keyed by a child id the parent router has already authorised
    through the parent link. Tests override this dependency.
    """
    return ChildTopicActivityReader(get_sessionmaker(get_settings()))
```

- [ ] **Step 4: Run to see them pass**

Run: `PYTHONPATH=$(pwd) /home/sico/Code/Lemely/.venv/bin/python -m pytest tests/test_child_topic_activity_repo.py -v`
Expected: 6 passed (or 6 skipped with "local Postgres not reachable": start Postgres and rerun; a skip is not a pass).

- [ ] **Step 5: Commit**

```bash
PYTHONPATH=$(pwd) pre-commit run --files lemely/db/child_topic_activity_repo.py lemely/web/deps.py tests/test_child_topic_activity_repo.py
git commit -S -m "feat(parent): read plan, flashcard and assignment activity per topic" -- lemely/db/child_topic_activity_repo.py lemely/web/deps.py tests/test_child_topic_activity_repo.py
```

---

### Task 3: Weaknesses endpoint gains ranked topics and "what they're doing"

**Files:**
- Modify: `lemely/web/schemas_parent.py` (new DTOs before `ChildWeaknessesDTO`, new fields on it, `__all__`)
- Modify: `lemely/web/routers/parent.py` (imports, `_topic_dtos` helper, `parent_child_weaknesses`)
- Modify: `tests/test_web_parent.py` (client fixture overrides the activity reader)
- Test: `tests/test_web_parent_topics.py`

**Interfaces:**
- Consumes: `rank_topics`, `RankedTopic` (Task 1); `ChildTopicActivityReader`, `TopicActivity`, `get_child_topic_activity_reader` (Task 2).
- Produces (wire, camelCase): `ParentTopicDTO {subjectCode, subjectName, topic, lostMarks, basisPapers, trend: "better"|"worse"|"same", papers: TopicPaperLossDTO[], doing: TopicDoingDTO}`; `TopicPaperLossDTO {paperId, recordedAt, lostMarks}`; `TopicDoingDTO {practisedThisWeek, practiceAwarded, practiceMaximum, inPlanThisWeek, flashcardsDue, assignment: TopicAssignmentDTO | null}`; `TopicAssignmentDTO {teacherName: string | null, dueAt: ISO string | null}`. `ChildWeaknessesDTO` adds `displayName: str`, `paperCount: int`, `topics: ParentTopicDTO[]`. Router helper `_topic_dtos(history, *, child_id: str, reader, now, subject_code: str | None = None) -> list[ParentTopicDTO]` (Task 4 reuses it).

- [ ] **Step 1: Write the failing tests**

```python
"""``GET /api/parent/children/{id}/weaknesses`` ranked topics (lane L11).

Reuses ``tests/test_web_parent.py``'s Postgres fixtures and seed helpers. The
activity reader is stubbed so these tests pin the router's mapping; the reader
itself is covered by ``tests/test_child_topic_activity_repo.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from lemely.core.schemas import WeakArea
from lemely.db.child_topic_activity_repo import TopicActivity, TopicAssignment
from lemely.db.models.enums import Role
from lemely.web.deps import get_child_topic_activity_reader
from tests.test_web_parent import (  # noqa: F401
    _auth_as,
    _link,
    _paper,
    _quiz,
    _recent,
    _seed_user,
    class_service,
    client,
    history_store,
    parent_link_service,
    pg_sessionmaker,
    profile_service,
    settings,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session, sessionmaker

    from lemely.io.history_store import HistoryStore


class StubReader:
    def __init__(self, by_key: dict[tuple[str, str], TopicActivity]) -> None:
        self.by_key = by_key
        self.calls: list[tuple[str, list[tuple[str, str]]]] = []

    def activity_for(
        self, child_id: str, keys: Iterable[tuple[str, str]], *, now: datetime
    ) -> dict[tuple[str, str], TopicActivity]:
        wanted = list(keys)
        self.calls.append((str(child_id), wanted))
        return {k: self.by_key.get(k, TopicActivity()) for k in wanted}


@pytest.fixture
def stub_reader(client: TestClient) -> StubReader:  # noqa: F811
    reader = StubReader({})
    client.app.dependency_overrides[get_child_topic_activity_reader] = lambda: reader  # type: ignore[union-attr]
    return reader


def _areas(*pairs: tuple[str, int]) -> list[WeakArea]:
    return [
        WeakArea(topic=t, lost_marks=lost, maximum_marks=10, accuracy=1 - lost / 10, question_ids=["1"])
        for t, lost in pairs
    ]


def test_topics_rank_by_marks_lost_with_subject_names_and_doing(
    client: TestClient,  # noqa: F811
    stub_reader: StubReader,
    pg_sessionmaker: sessionmaker[Session],  # noqa: F811
    history_store: HistoryStore,  # noqa: F811
) -> None:
    parent = _seed_user(pg_sessionmaker, Role.parent)
    child = _seed_user(pg_sessionmaker, Role.student, display_name="Omar")
    _link(pg_sessionmaker, parent_id=parent, child_id=child)
    paper = _paper(student_id=child, recorded_at=_recent(days_ago=4))
    history_store.append(str(child), paper.model_copy(update={"weak_areas": _areas(("Vectors", 6), ("Waves", 2))}))
    due = datetime(2026, 11, 20, 9, tzinfo=UTC)
    stub_reader.by_key[("0625", "Vectors")] = TopicActivity(
        in_plan_this_week=True,
        flashcards_due=3,
        assignment=TopicAssignment(teacher_name="Ms Adel", due_at=due),
    )

    _auth_as(client, parent, Role.parent)
    body = client.get(f"/api/parent/children/{child}/weaknesses").json()

    assert body["displayName"] == "Omar"
    assert body["paperCount"] == 1
    assert [t["topic"] for t in body["topics"]] == ["Vectors", "Waves"]
    vectors = body["topics"][0]
    assert vectors["subjectCode"] == "0625"
    assert vectors["subjectName"] == "Physics"
    assert vectors["lostMarks"] == 6
    assert vectors["basisPapers"] == 1
    assert vectors["trend"] == "same"
    assert vectors["papers"] == [{"paperId": "0625/12", "recordedAt": paper.recorded_at, "lostMarks": 6}]
    assert vectors["doing"] == {
        "practisedThisWeek": 0,
        "practiceAwarded": 0,
        "practiceMaximum": 0,
        "inPlanThisWeek": True,
        "flashcardsDue": 3,
        "assignment": {"teacherName": "Ms Adel", "dueAt": "2026-11-20T09:00:00Z"},
    }
    assert stub_reader.calls == [(str(child), [("0625", "Vectors"), ("0625", "Waves")])]


def test_practice_this_week_comes_from_quiz_records(
    client: TestClient,  # noqa: F811
    stub_reader: StubReader,
    pg_sessionmaker: sessionmaker[Session],  # noqa: F811
    history_store: HistoryStore,  # noqa: F811
) -> None:
    parent = _seed_user(pg_sessionmaker, Role.parent)
    child = _seed_user(pg_sessionmaker, Role.student)
    _link(pg_sessionmaker, parent_id=parent, child_id=child)
    history_store.append(str(child), _paper(student_id=child, topic="Vectors", recorded_at=_recent(days_ago=9)))
    history_store.append(str(child), _quiz(student_id=child, topic="Vectors", recorded_at=_recent(days_ago=1)))

    _auth_as(client, parent, Role.parent)
    doing = client.get(f"/api/parent/children/{child}/weaknesses").json()["topics"][0]["doing"]
    assert (doing["practisedThisWeek"], doing["practiceAwarded"], doing["practiceMaximum"]) == (1, 6, 10)


def test_weak_topics_stay_on_the_wire_unchanged(
    client: TestClient,  # noqa: F811
    stub_reader: StubReader,
    pg_sessionmaker: sessionmaker[Session],  # noqa: F811
    history_store: HistoryStore,  # noqa: F811
) -> None:
    parent = _seed_user(pg_sessionmaker, Role.parent)
    child = _seed_user(pg_sessionmaker, Role.student)
    _link(pg_sessionmaker, parent_id=parent, child_id=child)
    history_store.append(str(child), _paper(student_id=child))

    _auth_as(client, parent, Role.parent)
    body = client.get(f"/api/parent/children/{child}/weaknesses").json()
    assert body["weakTopics"] == [
        {"topic": "Thermal physics", "lostMarks": 4, "maximumMarks": 10, "accuracy": 0.6}
    ]


def test_no_history_reads_as_zero_papers_and_no_topics(
    client: TestClient,  # noqa: F811
    stub_reader: StubReader,
    pg_sessionmaker: sessionmaker[Session],  # noqa: F811
) -> None:
    parent = _seed_user(pg_sessionmaker, Role.parent)
    child = _seed_user(pg_sessionmaker, Role.student)
    _link(pg_sessionmaker, parent_id=parent, child_id=child)

    _auth_as(client, parent, Role.parent)
    body = client.get(f"/api/parent/children/{child}/weaknesses").json()
    assert (body["paperCount"], body["topics"], stub_reader.calls) == (0, [], [])


def test_unlinked_child_is_403_before_any_activity_read(
    client: TestClient,  # noqa: F811
    stub_reader: StubReader,
    pg_sessionmaker: sessionmaker[Session],  # noqa: F811
    history_store: HistoryStore,  # noqa: F811
) -> None:
    parent = _seed_user(pg_sessionmaker, Role.parent)
    stranger = _seed_user(pg_sessionmaker, Role.student)
    history_store.append(str(stranger), _paper(student_id=stranger))

    _auth_as(client, parent, Role.parent)
    assert client.get(f"/api/parent/children/{stranger}/weaknesses").status_code == 403
    assert stub_reader.calls == []
```

`_paper` builds subject `0625`, paper 1 variant 2 → paper id `0625/12`. `_quiz` builds a 10-mark weak area losing 4, so practice is 6 of 10. Note the `dueAt` serialisation: pydantic v2 writes a UTC datetime as `Z`. If the project's serializer writes `+00:00`, change only that literal.

- [ ] **Step 2: Run to see them fail**

Run: `PYTHONPATH=$(pwd) /home/sico/Code/Lemely/.venv/bin/python -m pytest tests/test_web_parent_topics.py -v`
Expected: FAIL (`ImportError: cannot import name 'get_child_topic_activity_reader'` if Task 2 is not merged on this branch, otherwise `KeyError: 'displayName'`).

- [ ] **Step 3: Add the DTOs**

In `lemely/web/schemas_parent.py`, add `from datetime import datetime` and `from typing import Literal` to the imports, then insert directly above `class ChildWeaknessesDTO`:

```python
class TopicPaperLossDTO(ApiModel):
    """Marks one topic lost on one basis paper (L11 topic sheet)."""

    paperId: str
    recordedAt: str
    lostMarks: int


class TopicAssignmentDTO(ApiModel):
    """An open teacher assignment on the topic. ``teacherName`` is the display name only."""

    teacherName: str | None = None
    dueAt: datetime | None = None


class TopicDoingDTO(ApiModel):
    """What the child is doing about a topic (L11). Every count is real; zero means none."""

    practisedThisWeek: int
    practiceAwarded: int
    practiceMaximum: int
    inPlanThisWeek: bool
    flashcardsDue: int
    assignment: TopicAssignmentDTO | None = None


class ParentTopicDTO(ApiModel):
    """One ranked topic: marks lost on the subject's last ``basisPapers`` papers (L11).

    Ranked by :func:`lemely.core.parent_topics.rank_topics`; the client renders
    the order as given and never re-sorts.
    """

    subjectCode: str
    subjectName: str
    topic: str
    lostMarks: int
    basisPapers: int
    trend: Literal["better", "worse", "same"]
    papers: list[TopicPaperLossDTO] = Field(default_factory=list)
    doing: TopicDoingDTO
```

Replace the body fields of `ChildWeaknessesDTO` (keep its docstring, and add one paragraph to it: "**L11** adds ``topics``, the marks-lost ranking with real 'what they're doing' data from :class:`~lemely.db.child_topic_activity_repo.ChildTopicActivityReader`, plus ``displayName`` and ``paperCount``. ``weakTopics`` is unchanged."):

```python
    childId: str
    displayName: str
    paperCount: int = 0
    weakTopics: list[WeakTopicDTO] = Field(default_factory=list)
    topics: list[ParentTopicDTO] = Field(default_factory=list)
```

Add `"ParentTopicDTO"`, `"TopicAssignmentDTO"`, `"TopicDoingDTO"`, `"TopicPaperLossDTO"` to `__all__` in alphabetical order.

- [ ] **Step 4: Wire the router**

In `lemely/web/routers/parent.py`:
1. Imports: add `from lemely.core.parent_topics import RankedTopic, rank_topics`, `from lemely.db.child_topic_activity_repo import ChildTopicActivityReader, TopicActivity`, add `get_child_topic_activity_reader` to the `lemely.web.deps` import, and add `ParentTopicDTO, TopicAssignmentDTO, TopicDoingDTO, TopicPaperLossDTO` to the `schemas_parent` import.
2. Replace the module docstring paragraph that begins "**Omitted from the wire on purpose (say so, never stub):**" with:

```
**What the child is doing (L11).** P-04's "constructive framing on what the
child is doing about it" now has a source: :mod:`lemely.core.parent_topics`
reads practice from the child's own quiz records, and
:class:`~lemely.db.child_topic_activity_repo.ChildTopicActivityReader` reads
this week's study plan, due flashcards and open teacher assignments, always
for a child id :func:`_authorized_child` has already cleared. Acknowledgement
state (D3.5) is still never surfaced here; it is teacher-facing only.
```

3. Add this helper after `_ranked_weak_topics`:

```python
def _topic_dto(topic: RankedTopic, activity: TopicActivity) -> ParentTopicDTO:
    assignment = activity.assignment
    return ParentTopicDTO(
        subjectCode=topic.subject_code,
        subjectName=_subject_name(topic.subject_code),
        topic=topic.topic,
        lostMarks=topic.lost_marks,
        basisPapers=topic.basis_papers,
        trend=topic.trend,
        papers=[
            TopicPaperLossDTO(paperId=p.paper_id, recordedAt=p.recorded_at, lostMarks=p.lost_marks)
            for p in topic.papers
        ],
        doing=TopicDoingDTO(
            practisedThisWeek=topic.practice.count,
            practiceAwarded=topic.practice.awarded_marks,
            practiceMaximum=topic.practice.maximum_marks,
            inPlanThisWeek=activity.in_plan_this_week,
            flashcardsDue=activity.flashcards_due,
            assignment=(
                TopicAssignmentDTO(teacherName=assignment.teacher_name, dueAt=assignment.due_at)
                if assignment is not None
                else None
            ),
        ),
    )


def _topic_dtos(
    history: StudentHistory,
    *,
    child_id: str,
    reader: ChildTopicActivityReader,
    now: datetime,
    subject_code: str | None = None,
) -> list[ParentTopicDTO]:
    """Rank a child's topics (optionally one subject's) and attach their activity.

    Callers pass ``child_id`` only after :func:`_authorized_child`. No ranked
    topic means no activity query at all.
    """
    records = [
        r
        for r in history.records
        if subject_code is None or r.metadata.subject_code == subject_code
    ]
    ranked = rank_topics(records, now=now)
    if not ranked:
        return []
    activity = reader.activity_for(child_id, [(t.subject_code, t.topic) for t in ranked], now=now)
    return [
        _topic_dto(t, activity.get((t.subject_code, t.topic), TopicActivity())) for t in ranked
    ]
```

4. Replace `parent_child_weaknesses` with:

```python
@router.get("/children/{child_id}/weaknesses", response_model=ChildWeaknessesDTO)
def parent_child_weaknesses(
    child_id: str,
    auth: Annotated[AuthContext, Depends(require_role(Role.parent))],
    parent_link_service: Annotated[ParentLinkService, Depends(get_parent_link_service)],
    class_service: Annotated[ClassService, Depends(get_class_service)],
    history_store: Annotated[HistoryStoreProtocol, Depends(get_history_store)],
    activity_reader: Annotated[
        ChildTopicActivityReader, Depends(get_child_topic_activity_reader)
    ],
) -> ChildWeaknessesDTO:
    """Return P-04: ranked weak topics for a linked child.

    Authz per :func:`_authorized_child`. ``weakTopics`` keeps its
    worst-accuracy-first order; ``topics`` is L11's marks-lost ranking with
    "what they're doing". ``paperCount`` counts real past papers only.
    """
    child = _authorized_child(parent_link_service, class_service, auth, child_id)
    history = history_store.load(str(child.child_id))
    return ChildWeaknessesDTO(
        childId=str(child.child_id),
        displayName=child.display_name,
        paperCount=sum(1 for r in history.records if is_paper(r)),
        weakTopics=_ranked_weak_topics(history),
        topics=_topic_dtos(
            history,
            child_id=str(child.child_id),
            reader=activity_reader,
            now=datetime.now(UTC),
        ),
    )
```

5. In `tests/test_web_parent.py`, inside the `client` fixture, add after the profile-service override (and import `get_child_topic_activity_reader` from `lemely.web.deps` plus `ChildTopicActivityReader` from `lemely.db.child_topic_activity_repo`):

```python
    app.dependency_overrides[get_child_topic_activity_reader] = lambda: ChildTopicActivityReader(
        parent_link_service._sessionmaker  # noqa: SLF001 - same throwaway DB as the other services
    )
```

If `ParentLinkService` names its attribute differently, read `lemely/db/parent_repo.py:157-161` and use that name; the point is to bind the reader to the fixture's throwaway database, never the dev database.

- [ ] **Step 5: Run the new and the existing parent tests**

Run: `PYTHONPATH=$(pwd) /home/sico/Code/Lemely/.venv/bin/python -m pytest tests/test_web_parent_topics.py tests/test_web_parent.py -v`
Expected: all pass (5 new, existing unchanged).

- [ ] **Step 6: Commit**

```bash
PYTHONPATH=$(pwd) pre-commit run --files lemely/web/schemas_parent.py lemely/web/routers/parent.py tests/test_web_parent.py tests/test_web_parent_topics.py
git commit -S -m "feat(parent): ranked topics with what the child is doing on weaknesses" -- lemely/web/schemas_parent.py lemely/web/routers/parent.py tests/test_web_parent.py tests/test_web_parent_topics.py
```

---

### Task 4: Subject endpoint gains paper series, goal, target and topics

**Files:**
- Modify: `lemely/web/schemas_parent.py` (two DTOs before `SubjectDetailDTO`, new fields on it, `__all__`)
- Modify: `lemely/web/routers/parent.py` (`_goal_line`, `_paper_series`, `parent_child_subject`)
- Test: `tests/test_web_parent_subject_series.py`

**Interfaces:**
- Consumes: `_topic_dtos` (Task 3), `GradeBoundaryStore`, `StudentProfileService.target_grades_for`.
- Produces (wire): `SeriesPointDTO {paperId, grade, awardedMarks, maximumMarks, percentage, recordedAt}`; `PaperSeriesDTO {paperNumber, maximumMarks, goalLine: int | null, points: SeriesPointDTO[]}` (points oldest first, at most 5; series ordered most recently sat first). `SubjectDetailDTO` adds `childName: str`, `targetGrade: str | null`, `goalGrade: str` (the target when it is on the grade ladder, else `"A*"`), `series: PaperSeriesDTO[]`, `topics: ParentTopicDTO[]` (this subject only).

- [ ] **Step 1: Write the failing tests**

```python
"""``GET /api/parent/children/{id}/subjects/{code}`` series and goal (lane L11)."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import pytest

from lemely.core.schemas import ExamMetadata
from lemely.db.child_topic_activity_repo import TopicActivity
from lemely.db.models.enums import Role
from lemely.io.grade_boundaries import GradeBoundaryStore
from lemely.web.deps import get_child_topic_activity_reader
from tests.test_web_parent import (  # noqa: F401
    _auth_as,
    _link,
    _paper,
    _recent,
    _seed_subject,
    _seed_user,
    class_service,
    client,
    history_store,
    parent_link_service,
    pg_sessionmaker,
    profile_service,
    settings,
)

if TYPE_CHECKING:
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session, sessionmaker

    from lemely.db.student_profile_repo import StudentProfileService
    from lemely.io.history_store import HistoryStore


class _NoActivity:
    def activity_for(self, child_id, keys, *, now):  # type: ignore[no-untyped-def]
        return {k: TopicActivity() for k in keys}


@pytest.fixture(autouse=True)
def _stub_reader(client: TestClient) -> None:  # noqa: F811
    client.app.dependency_overrides[get_child_topic_activity_reader] = _NoActivity  # type: ignore[union-attr]


def _setup(sm: sessionmaker[Session]) -> tuple[object, object]:
    parent = _seed_user(sm, Role.parent)
    child = _seed_user(sm, Role.student, display_name="Omar")
    _link(sm, parent_id=parent, child_id=child)
    return parent, child


def test_series_group_by_paper_number_newest_series_first_oldest_point_first(
    client: TestClient,  # noqa: F811
    pg_sessionmaker: sessionmaker[Session],  # noqa: F811
    history_store: HistoryStore,  # noqa: F811
) -> None:
    parent, child = _setup(pg_sessionmaker)
    for days, number, awarded in [(40, 2, 44), (30, 4, 45), (20, 2, 47), (10, 4, 61)]:
        history_store.append(
            str(child),
            _paper(student_id=child, paper_number=number, awarded=awarded, maximum=80,
                   percentage=awarded / 80 * 100, grade="B", recorded_at=_recent(days_ago=days)),
        )

    _auth_as(client, parent, Role.parent)
    body = client.get(f"/api/parent/children/{child}/subjects/0625").json()

    assert body["childName"] == "Omar"
    assert [s["paperNumber"] for s in body["series"]] == [4, 2]
    assert [p["awardedMarks"] for p in body["series"][0]["points"]] == [45, 61]
    assert body["series"][0]["maximumMarks"] == 80
    assert body["series"][0]["points"][0]["paperId"] == "0625/42"


def test_a_series_keeps_its_last_five_points(
    client: TestClient,  # noqa: F811
    pg_sessionmaker: sessionmaker[Session],  # noqa: F811
    history_store: HistoryStore,  # noqa: F811
) -> None:
    parent, child = _setup(pg_sessionmaker)
    for i in range(7):
        history_store.append(
            str(child), _paper(student_id=child, awarded=40 + i, recorded_at=_recent(days_ago=30 - i))
        )
    _auth_as(client, parent, Role.parent)
    points = client.get(f"/api/parent/children/{child}/subjects/0625").json()["series"][0]["points"]
    assert [p["awardedMarks"] for p in points] == [42, 43, 44, 45, 46]


def test_goal_is_a_star_without_a_target_and_the_line_comes_from_the_boundary_table(
    client: TestClient,  # noqa: F811
    pg_sessionmaker: sessionmaker[Session],  # noqa: F811
    history_store: HistoryStore,  # noqa: F811
) -> None:
    parent, child = _setup(pg_sessionmaker)
    paper = _paper(student_id=child, paper_number=2, awarded=44, maximum=80, percentage=55.0, grade="C")
    history_store.append(str(child), paper)

    _auth_as(client, parent, Role.parent)
    body = client.get(f"/api/parent/children/{child}/subjects/0625").json()

    boundaries, _ = GradeBoundaryStore().resolve(paper.metadata)
    expected = math.ceil(boundaries["A*"] / 100 * 80) if "A*" in boundaries else None
    assert (body["targetGrade"], body["goalGrade"]) == (None, "A*")
    assert body["series"][0]["goalLine"] == expected


def test_a_target_grade_becomes_the_goal(
    client: TestClient,  # noqa: F811
    pg_sessionmaker: sessionmaker[Session],  # noqa: F811
    history_store: HistoryStore,  # noqa: F811
    profile_service: StudentProfileService,  # noqa: F811
) -> None:
    parent, child = _setup(pg_sessionmaker)
    _seed_subject(pg_sessionmaker)
    profile_service.upsert_enrolment(child, "0625", target_grade="B")
    history_store.append(
        str(child),
        _paper(student_id=child, paper_number=2, awarded=44, maximum=80, percentage=55.0, grade="C"),
    )

    _auth_as(client, parent, Role.parent)
    body = client.get(f"/api/parent/children/{child}/subjects/0625").json()

    # 0625 paper 2's subject-default B boundary is 57.82% -> 47 of 80 (see
    # tests/test_web_parent.py::test_subject_detail_reports_the_distance_to_the_next_grade_up).
    assert (body["targetGrade"], body["goalGrade"]) == ("B", "B")
    assert body["series"][0]["goalLine"] == 47


def test_goal_line_is_null_when_the_paper_cannot_award_the_goal(
    client: TestClient,  # noqa: F811
    pg_sessionmaker: sessionmaker[Session],  # noqa: F811
    history_store: HistoryStore,  # noqa: F811
) -> None:
    parent, child = _setup(pg_sessionmaker)
    # 0625 paper 1 is Core: its fallback carries no A*.
    history_store.append(str(child), _paper(student_id=child, paper_number=1, grade="C"))
    _auth_as(client, parent, Role.parent)
    body = client.get(f"/api/parent/children/{child}/subjects/0625").json()
    meta = ExamMetadata(subject_code="0625", paper_number=1, paper_variant=2, session_month="May/June", session_year=2020)
    assert "A*" not in GradeBoundaryStore().resolve(meta)[0]
    assert body["series"][0]["goalLine"] is None


def test_subject_topics_are_this_subject_only_and_old_fields_remain(
    client: TestClient,  # noqa: F811
    pg_sessionmaker: sessionmaker[Session],  # noqa: F811
    history_store: HistoryStore,  # noqa: F811
) -> None:
    parent, child = _setup(pg_sessionmaker)
    history_store.append(str(child), _paper(student_id=child, topic="Waves"))
    history_store.append(str(child), _paper(student_id=child, subject_code="0580", topic="Vectors"))
    _auth_as(client, parent, Role.parent)
    body = client.get(f"/api/parent/children/{child}/subjects/0625").json()
    assert [t["topic"] for t in body["topics"]] == ["Waves"]
    for kept in ("papers", "predictedGrade", "boundaryDistance", "weakTopics", "subjectName"):
        assert kept in body


def test_no_papers_for_the_subject_is_still_404_with_its_detail(
    client: TestClient,  # noqa: F811
    pg_sessionmaker: sessionmaker[Session],  # noqa: F811
) -> None:
    parent, child = _setup(pg_sessionmaker)
    _auth_as(client, parent, Role.parent)
    res = client.get(f"/api/parent/children/{child}/subjects/0580")
    assert res.status_code == 404
    assert res.json()["detail"] == "No papers for subject 0580"
```

- [ ] **Step 2: Run to see them fail**

Run: `PYTHONPATH=$(pwd) /home/sico/Code/Lemely/.venv/bin/python -m pytest tests/test_web_parent_subject_series.py -v`
Expected: FAIL with `KeyError: 'childName'` / `'series'`.

- [ ] **Step 3: Add the DTOs**

In `lemely/web/schemas_parent.py`, directly above `class SubjectDetailDTO`:

```python
class SeriesPointDTO(ApiModel):
    """One grade-bearing paper in a paper-number series (L11 Steps path)."""

    paperId: str
    grade: str
    awardedMarks: int
    maximumMarks: int
    percentage: float
    recordedAt: str


class PaperSeriesDTO(ApiModel):
    """Every grade-bearing paper with one paper number, oldest first, last five (L11).

    ``goalLine`` is the goal grade's threshold in marks on the latest paper,
    ``ceil`` like ``GradeBoundaryDistanceDTO``; ``null`` when the boundary table
    has no threshold for that grade on this paper (a Core paper has no A*).
    """

    paperNumber: int
    maximumMarks: int
    goalLine: int | None = None
    points: list[SeriesPointDTO] = Field(default_factory=list)
```

Add to `SubjectDetailDTO` after its existing fields (and one docstring paragraph: "**L11** adds ``childName``, ``targetGrade`` (the enrolment's target, ``null`` when unset), ``goalGrade`` (the target when it is on the grade ladder, else ``A*``), ``series`` and this subject's ``topics``."):

```python
    childName: str
    targetGrade: str | None = None
    goalGrade: str = "A*"
    series: list[PaperSeriesDTO] = Field(default_factory=list)
    topics: list[ParentTopicDTO] = Field(default_factory=list)
```

`ParentTopicDTO` is defined further down the file (Task 3). Move the four Task 3 DTOs above `SubjectDetailDTO` so the class exists when it is referenced. Add `"PaperSeriesDTO"`, `"SeriesPointDTO"` to `__all__`.

- [ ] **Step 4: Router helpers and endpoint**

In `lemely/web/routers/parent.py`, import `PaperSeriesDTO, SeriesPointDTO` and `get_child_topic_activity_reader` (already imported in Task 3). Add after `_grade_boundary_distance`:

```python
SERIES_POINTS = 5


def _goal_line(record: PaperRecord, goal_grade: str) -> int | None:
    """The goal grade's threshold in marks on ``record``, or ``None`` when unknowable."""
    boundaries, _ = GradeBoundaryStore().resolve(record.metadata)
    threshold_pct = boundaries.get(goal_grade)
    if threshold_pct is None or record.maximum_marks <= 0:
        return None
    return math.ceil((threshold_pct / 100.0) * record.maximum_marks)


def _paper_series(records: list[PaperRecord], goal_grade: str) -> list[PaperSeriesDTO]:
    """Group grade-bearing ``records`` by paper number for the Steps path (L11)."""
    by_number: dict[int, list[PaperRecord]] = {}
    for record in records:
        by_number.setdefault(record.metadata.paper_number, []).append(record)
    series = [
        PaperSeriesDTO(
            paperNumber=number,
            maximumMarks=number_records[-1].maximum_marks,
            goalLine=_goal_line(number_records[-1], goal_grade),
            points=[
                SeriesPointDTO(
                    paperId=_paper_id(r),
                    grade=r.grade,
                    awardedMarks=r.awarded_marks,
                    maximumMarks=r.maximum_marks,
                    percentage=r.percentage,
                    recordedAt=r.recorded_at,
                )
                for r in number_records[-SERIES_POINTS:]
            ],
        )
        for number, number_records in by_number.items()
    ]
    series.sort(key=lambda s: s.points[-1].recordedAt, reverse=True)
    return series
```

In `parent_child_subject`, add the parameter `activity_reader: Annotated[ChildTopicActivityReader, Depends(get_child_topic_activity_reader)]` after `profile_service`, and replace the `return SubjectDetailDTO(...)` with:

```python
    target = profile_service.target_grades_for(child.child_id).get(code)
    goal_grade = target if target in GRADE_ORDER else "A*"
    return SubjectDetailDTO(
        childId=str(child.child_id),
        childName=child.display_name,
        subjectCode=code,
        subjectName=_subject_name(code),
        qualificationLevel=_qualification_level(enrolment),
        predictedGrade=records[-1].grade,
        targetGrade=target,
        goalGrade=goal_grade,
        papers=papers,
        series=_paper_series(records, goal_grade),
        boundaryDistance=_grade_boundary_distance(records[-1]),
        weakTopics=_ranked_weak_topics(subject_history),
        topics=_topic_dtos(
            history,
            child_id=str(child.child_id),
            reader=activity_reader,
            now=datetime.now(UTC),
            subject_code=code,
        ),
    )
```

Update the endpoint docstring with one sentence: "L11 adds ``series`` (grade-bearing, by paper number), the goal and target, and this subject's ranked ``topics``."

- [ ] **Step 5: Run the subject, topics and existing parent tests**

Run: `PYTHONPATH=$(pwd) /home/sico/Code/Lemely/.venv/bin/python -m pytest tests/test_web_parent_subject_series.py tests/test_web_parent_topics.py tests/test_web_parent.py -v`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
PYTHONPATH=$(pwd) pre-commit run --files lemely/web/schemas_parent.py lemely/web/routers/parent.py tests/test_web_parent_subject_series.py
git commit -S -m "feat(parent): paper series, goal line and topics on subject detail" -- lemely/web/schemas_parent.py lemely/web/routers/parent.py tests/test_web_parent_subject_series.py
```

---

### Task 5: Weekly-email flags table, model and repo (migration)

> **User approval gate:** writing and testing this migration on a throwaway test database is allowed. Running it against any shared database (staging, production, a teammate's DB) needs the user's explicit approval first.

**Files:**
- Create: `lemely/db/models/parent_prefs.py`
- Modify: `lemely/db/models/__init__.py` (re-export and `import_all_models` entry)
- Create: `lemely/db/migrations/versions/0055_parent_weekly_email_prefs.py`
- Create: `lemely/db/parent_weekly_email_repo.py`
- Modify: `lemely/web/deps.py` (one getter)
- Test: `tests/test_migration_parent_weekly_email_prefs.py`, `tests/test_parent_weekly_email_repo.py`

**Interfaces:**
- Produces: table `parent_weekly_email_prefs(parent_id uuid FK users ON DELETE CASCADE, child_id uuid FK users ON DELETE CASCADE, subject_code varchar(4), enabled bool NOT NULL, created_at, updated_at, PK(parent_id, child_id, subject_code))`; model `ParentWeeklyEmailPref`; `DEFAULT_WEEKLY_ENABLED = True`; `ParentWeeklyEmailService(sessionmaker)` with `flags_for(parent_id) -> dict[tuple[uuid.UUID, str], bool]` and `set_flags(parent_id, updates: Iterable[tuple[uuid.UUID, str, bool]]) -> None` (upsert); `get_parent_weekly_email_service()` in deps.

Before merge, rebase `down_revision` onto the `develop` head (L1, L6, L9 and L12 may land migrations first). Update the revision test's `DOWN_REVISION` with it.

- [ ] **Step 1: Write the failing tests**

`tests/test_migration_parent_weekly_email_prefs.py`:

```python
"""Migration 0055_parent_weekly_email_prefs: per-child, per-subject weekly email flags."""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory

from lemely.db.base import Base
from lemely.db.models import import_all_models
from tests.test_migration_tutoring_enums import current_revision, head_revision, upgrade_head

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.orm import Session, sessionmaker

import_all_models()

REVISION = "0055_parent_weekly_email_prefs"
DOWN_REVISION = "0054_waitlist_email_confirmation"
TABLE = "parent_weekly_email_prefs"
_EXISTS = sa.text("SELECT to_regclass(:t) IS NOT NULL")


def test_revision_chains_from_its_parent() -> None:
    revision = ScriptDirectory.from_config(Config("alembic.ini")).get_revision(REVISION)
    assert revision is not None
    assert revision.down_revision == DOWN_REVISION
    assert len(REVISION) <= 32


def test_table_matches_the_orm(migrated_sessionmaker: sessionmaker[Session]) -> None:
    with migrated_sessionmaker.begin() as session:
        assert session.execute(_EXISTS, {"t": TABLE}).scalar_one() is True
        diff = compare_metadata(
            MigrationContext.configure(session.connection(), opts={"compare_type": True}),
            Base.metadata,
        )
    assert [d for d in diff if TABLE in repr(d)] == []


def test_upgrade_downgrade_upgrade_round_trip(
    migrated_sessionmaker_with_downgrade: tuple[sessionmaker[Session], Callable[[str], None]],
) -> None:
    sm, downgrade_to = migrated_sessionmaker_with_downgrade
    downgrade_to(DOWN_REVISION)
    with sm() as session:
        assert current_revision(session) == DOWN_REVISION
        assert session.execute(_EXISTS, {"t": TABLE}).scalar_one() is False
    upgrade_head()
    with sm() as session:
        assert current_revision(session) == head_revision()
        assert session.execute(_EXISTS, {"t": TABLE}).scalar_one() is True
```

`tests/test_parent_weekly_email_repo.py`:

```python
""":class:`ParentWeeklyEmailService` (lane L11)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from lemely.db.models.enums import Role
from lemely.db.parent_weekly_email_repo import ParentWeeklyEmailService
from tests.test_web_parent import _seed_user, pg_sessionmaker  # noqa: F401

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker


def test_no_rows_reads_as_empty(pg_sessionmaker: sessionmaker[Session]) -> None:  # noqa: F811
    parent = _seed_user(pg_sessionmaker, Role.parent)
    assert ParentWeeklyEmailService(pg_sessionmaker).flags_for(parent) == {}


def test_set_flags_upserts_and_reads_back_only_this_parent(
    pg_sessionmaker: sessionmaker[Session],  # noqa: F811
) -> None:
    parent = _seed_user(pg_sessionmaker, Role.parent)
    other = _seed_user(pg_sessionmaker, Role.parent)
    child = _seed_user(pg_sessionmaker, Role.student)
    service = ParentWeeklyEmailService(pg_sessionmaker)

    service.set_flags(parent, [(child, "0580", False), (child, "0625", True)])
    service.set_flags(parent, [(child, "0580", True)])
    service.set_flags(other, [(child, "0580", False)])

    assert service.flags_for(parent) == {(child, "0580"): True, (child, "0625"): True}
    assert service.flags_for(other) == {(child, "0580"): False}


def test_deleting_the_child_removes_its_flags(pg_sessionmaker: sessionmaker[Session]) -> None:  # noqa: F811
    from lemely.db.models import User

    parent = _seed_user(pg_sessionmaker, Role.parent)
    child = _seed_user(pg_sessionmaker, Role.student)
    service = ParentWeeklyEmailService(pg_sessionmaker)
    service.set_flags(parent, [(child, "0580", False)])
    with pg_sessionmaker.begin() as session:
        session.delete(session.get(User, child))
    assert service.flags_for(parent) == {}
```

- [ ] **Step 2: Run to see them fail**

Run: `PYTHONPATH=$(pwd) /home/sico/Code/Lemely/.venv/bin/python -m pytest tests/test_migration_parent_weekly_email_prefs.py tests/test_parent_weekly_email_repo.py -v`
Expected: FAIL (`ModuleNotFoundError: lemely.db.parent_weekly_email_repo`, revision not found).

- [ ] **Step 3: Model**

`lemely/db/models/parent_prefs.py`:

```python
"""Parent-only preferences (lane L11): the weekly summary email, per child and subject.

One row per ``(parent, child, subject)`` that the parent has ever switched.
No row means :data:`lemely.db.parent_weekly_email_repo.DEFAULT_WEEKLY_ENABLED`.
Rows survive an unlink on purpose (a re-link restores the parent's choice);
readers filter to currently linked children. Deleting either user removes the
row (``ON DELETE CASCADE``).
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from lemely.db.base import Base
from lemely.db.models.enums import TimestampMixin


class ParentWeeklyEmailPref(TimestampMixin, Base):
    """Whether a parent gets the Sunday summary for one child's subject."""

    __tablename__ = "parent_weekly_email_prefs"

    parent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    child_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    subject_code: Mapped[str] = mapped_column(sa.String(4), primary_key=True)
    enabled: Mapped[bool] = mapped_column(sa.Boolean, nullable=False)
```

`lemely/db/models/__init__.py`: add `from lemely.db.models.parent_prefs import ParentWeeklyEmailPref` in the alphabetised re-export block (after `orgs`), and `parent_prefs,` in `import_all_models`'s import list (after `otp_challenges`).

- [ ] **Step 4: Migration**

`lemely/db/migrations/versions/0055_parent_weekly_email_prefs.py`:

```python
"""parent weekly email prefs: per-child, per-subject weekly summary flags (lane L11).

Revision ID: 0055_parent_weekly_email_prefs
Revises: 0054_waitlist_email_confirmation
Create Date: 2026-11-15 00:00:00.000000

One new table, ``parent_weekly_email_prefs``, keyed ``(parent_id, child_id,
subject_code)``, both user columns cascading on delete. Additive: no existing
table changes. ``downgrade`` drops the table and nothing else.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
# Kept to <=32 chars: alembic_version.version_num is varchar(32).
revision: str = "0055_parent_weekly_email_prefs"
down_revision: str | Sequence[str] | None = "0054_waitlist_email_confirmation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "parent_weekly_email_prefs"


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        TABLE,
        sa.Column("parent_id", sa.UUID(), nullable=False),
        sa.Column("child_id", sa.UUID(), nullable=False),
        sa.Column("subject_code", sa.String(length=4), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["parent_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["child_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("parent_id", "child_id", "subject_code"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table(TABLE)
```

- [ ] **Step 5: Repo and getter**

`lemely/db/parent_weekly_email_repo.py`:

```python
"""The single ``parent_weekly_email_prefs`` query surface (lane L11)."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Final

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from lemely.db.models.parent_prefs import ParentWeeklyEmailPref

if TYPE_CHECKING:
    from collections.abc import Iterable

    from sqlalchemy.orm import Session, sessionmaker

#: What a ``(parent, child, subject)`` with no stored row reads as.
DEFAULT_WEEKLY_ENABLED: Final = True


def _as_uuid(value: uuid.UUID | str) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


class ParentWeeklyEmailService:
    def __init__(self, sessionmaker: sessionmaker[Session]) -> None:
        self._sessionmaker = sessionmaker

    def flags_for(self, parent_id: uuid.UUID | str) -> dict[tuple[uuid.UUID, str], bool]:
        """Every stored flag for ``parent_id``, keyed ``(child_id, subject_code)``."""
        pid = _as_uuid(parent_id)
        with self._sessionmaker() as session:
            rows = session.execute(
                select(
                    ParentWeeklyEmailPref.child_id,
                    ParentWeeklyEmailPref.subject_code,
                    ParentWeeklyEmailPref.enabled,
                ).where(ParentWeeklyEmailPref.parent_id == pid)
            ).all()
        return {(child, subject): enabled for child, subject, enabled in rows}

    def set_flags(
        self, parent_id: uuid.UUID | str, updates: Iterable[tuple[uuid.UUID | str, str, bool]]
    ) -> None:
        """Upsert each ``(child_id, subject_code, enabled)`` for ``parent_id`` in one transaction."""
        pid = _as_uuid(parent_id)
        values = [
            {"parent_id": pid, "child_id": _as_uuid(child), "subject_code": subject, "enabled": enabled}
            for child, subject, enabled in updates
        ]
        if not values:
            return
        statement = insert(ParentWeeklyEmailPref).values(values)
        statement = statement.on_conflict_do_update(
            index_elements=["parent_id", "child_id", "subject_code"],
            set_={"enabled": statement.excluded.enabled, "updated_at": func.now()},
        )
        with self._sessionmaker.begin() as session:
            session.execute(statement)


__all__ = ["DEFAULT_WEEKLY_ENABLED", "ParentWeeklyEmailService"]
```

Add to `lemely/web/deps.py` after `get_notification_prefs_service` (with the import `from lemely.db.parent_weekly_email_repo import ParentWeeklyEmailService`):

```python
@lru_cache(maxsize=1)
def get_parent_weekly_email_service() -> ParentWeeklyEmailService:
    """Return the process-wide :class:`ParentWeeklyEmailService` (lane L11)."""
    return ParentWeeklyEmailService(get_sessionmaker(get_settings()))
```

- [ ] **Step 6: Run to see them pass**

Run: `PYTHONPATH=$(pwd) /home/sico/Code/Lemely/.venv/bin/python -m pytest tests/test_migration_parent_weekly_email_prefs.py tests/test_parent_weekly_email_repo.py tests/test_db_schema.py -v`
Expected: all pass. If `tests/test_db_schema.py` pins a table list, add `parent_weekly_email_prefs` there in the same commit.

- [ ] **Step 7: Commit**

```bash
PYTHONPATH=$(pwd) pre-commit run --files lemely/db/models/parent_prefs.py lemely/db/models/__init__.py lemely/db/migrations/versions/0055_parent_weekly_email_prefs.py lemely/db/parent_weekly_email_repo.py lemely/web/deps.py tests/test_migration_parent_weekly_email_prefs.py tests/test_parent_weekly_email_repo.py
git commit -S -m "feat(db): parent weekly email flags per child and subject" -- lemely/db/models/parent_prefs.py lemely/db/models/__init__.py lemely/db/migrations/versions/0055_parent_weekly_email_prefs.py lemely/db/parent_weekly_email_repo.py lemely/web/deps.py tests/test_migration_parent_weekly_email_prefs.py tests/test_parent_weekly_email_repo.py
```

---

### Task 6: `weeklySummaries` on notification preferences GET and PUT

**Files:**
- Create: `lemely/web/weekly_summaries.py`
- Modify: `lemely/web/schemas_me.py`, `lemely/web/routers/me.py`
- Test: `tests/test_web_me_weekly_summaries.py`

**Interfaces:**
- Consumes: `ParentWeeklyEmailService`, `DEFAULT_WEEKLY_ENABLED` (Task 5); `ParentLinkService.linked_children/get_child`; `ClassService.student_classes`; `StudentProfileService.list_enrolments`; `HistoryStoreProtocol.load`; `get_profile`.
- Produces (wire): `WeeklySummaryDTO {childId, childName, subjectCode, subjectName, enabled}`; `WeeklySummaryUpdateDTO {childId, subjectCode (4 digits), enabled}`. `NotificationPreferencesDTO.weeklySummaries: WeeklySummaryDTO[] | null` (null for every role but parent). `NotificationPreferencesUpdateDTO.weeklySummaries: WeeklySummaryUpdateDTO[] | None` (max 50 items). PUT rules: non-parent sending the field → 422; an unlinked child → 403; malformed id → 422; a subject the child does not have → 422; omitted → untouched.
- Python: `child_subject_codes(child_id, *, classes, profiles, history) -> list[str]`; `weekly_summary_dtos(parent_id, *, links, classes, profiles, history, flags) -> list[WeeklySummaryDTO]`; `apply_weekly_updates(parent_id, updates, *, links, classes, profiles, history, flags) -> None` raising `HTTPException`.

A child's subjects = enrolment codes ∪ class subject codes ∪ subject codes in the child's history, sorted by subject name.

- [ ] **Step 1: Write the failing tests**

```python
"""``weeklySummaries`` on ``/api/me/notification-preferences`` (lane L11)."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from lemely.db.class_repo import ClassService
from lemely.db.models.enums import Role
from lemely.db.notification_prefs_repo import NotificationPreferencesService
from lemely.db.parent_repo import ParentLinkService
from lemely.db.parent_weekly_email_repo import ParentWeeklyEmailService
from lemely.db.student_profile_repo import StudentProfileService
from lemely.web import create_app
from lemely.web.deps import (
    get_class_service,
    get_history_store,
    get_notification_prefs_service,
    get_parent_link_service,
    get_parent_weekly_email_service,
    get_settings,
    get_student_profile_service,
)
from tests.test_web_parent import (  # noqa: F401
    _auth_as,
    _link,
    _paper,
    _seed_user,
    history_store,
    pg_sessionmaker,
    settings,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker

    from lemely.io.history_store import HistoryStore
    from lemely.runtime.config import Settings

PATH = "/api/me/notification-preferences"


@pytest.fixture
def me_client(
    settings: Settings,  # noqa: F811
    history_store: HistoryStore,  # noqa: F811
    pg_sessionmaker: sessionmaker[Session],  # noqa: F811
) -> Iterator[TestClient]:
    app = create_app()
    overrides = {
        get_settings: lambda: settings,
        get_history_store: lambda: history_store,
        get_class_service: lambda: ClassService(pg_sessionmaker),
        get_parent_link_service: lambda: ParentLinkService(pg_sessionmaker),
        get_student_profile_service: lambda: StudentProfileService(pg_sessionmaker),
        get_notification_prefs_service: lambda: NotificationPreferencesService(pg_sessionmaker),
        get_parent_weekly_email_service: lambda: ParentWeeklyEmailService(pg_sessionmaker),
    }
    app.dependency_overrides.update(overrides)
    yield TestClient(app)
    app.dependency_overrides.clear()


def _family(sm: sessionmaker[Session], history: HistoryStore) -> tuple[uuid.UUID, uuid.UUID]:
    parent = _seed_user(sm, Role.parent)
    child = _seed_user(sm, Role.student, display_name="Omar")
    _link(sm, parent_id=parent, child_id=child)
    history.append(str(child), _paper(student_id=child))  # 0625 Physics
    history.append(str(child), _paper(student_id=child, subject_code="0580", topic="Vectors"))
    return parent, child


def test_parent_gets_one_row_per_child_subject_defaulting_on(
    me_client: TestClient,
    pg_sessionmaker: sessionmaker[Session],  # noqa: F811
    history_store: HistoryStore,  # noqa: F811
) -> None:
    parent, child = _family(pg_sessionmaker, history_store)
    _auth_as(me_client, parent, Role.parent)
    rows = me_client.get(PATH).json()["weeklySummaries"]
    assert [(r["childName"], r["subjectCode"], r["enabled"]) for r in rows] == [
        ("Omar", "0580", True),
        ("Omar", "0625", True),
    ]
    assert {r["childId"] for r in rows} == {str(child)}
    assert rows[1]["subjectName"] == "Physics"


def test_put_flips_one_flag_and_leaves_the_rest(
    me_client: TestClient,
    pg_sessionmaker: sessionmaker[Session],  # noqa: F811
    history_store: HistoryStore,  # noqa: F811
) -> None:
    parent, child = _family(pg_sessionmaker, history_store)
    _auth_as(me_client, parent, Role.parent)
    before = me_client.get(PATH).json()
    res = me_client.put(
        PATH,
        json={"weeklySummaries": [{"childId": str(child), "subjectCode": "0625", "enabled": False}]},
    )
    assert res.status_code == 200
    flags = {r["subjectCode"]: r["enabled"] for r in res.json()["weeklySummaries"]}
    assert flags == {"0580": True, "0625": False}
    assert res.json()["atRiskAlert"] == before["atRiskAlert"]


def test_put_without_the_field_does_not_touch_weekly_flags(
    me_client: TestClient,
    pg_sessionmaker: sessionmaker[Session],  # noqa: F811
    history_store: HistoryStore,  # noqa: F811
) -> None:
    parent, child = _family(pg_sessionmaker, history_store)
    ParentWeeklyEmailService(pg_sessionmaker).set_flags(parent, [(child, "0580", False)])
    _auth_as(me_client, parent, Role.parent)
    res = me_client.put(PATH, json={"atRiskAlert": False})
    flags = {r["subjectCode"]: r["enabled"] for r in res.json()["weeklySummaries"]}
    assert flags["0580"] is False


def test_unlinked_child_is_403_and_nothing_is_stored(
    me_client: TestClient,
    pg_sessionmaker: sessionmaker[Session],  # noqa: F811
    history_store: HistoryStore,  # noqa: F811
) -> None:
    parent, _ = _family(pg_sessionmaker, history_store)
    stranger = _seed_user(pg_sessionmaker, Role.student)
    _auth_as(me_client, parent, Role.parent)
    res = me_client.put(
        PATH,
        json={"weeklySummaries": [{"childId": str(stranger), "subjectCode": "0580", "enabled": False}]},
    )
    assert res.status_code == 403
    assert ParentWeeklyEmailService(pg_sessionmaker).flags_for(parent) == {}


def test_a_subject_the_child_does_not_have_is_422(
    me_client: TestClient,
    pg_sessionmaker: sessionmaker[Session],  # noqa: F811
    history_store: HistoryStore,  # noqa: F811
) -> None:
    parent, child = _family(pg_sessionmaker, history_store)
    _auth_as(me_client, parent, Role.parent)
    res = me_client.put(
        PATH,
        json={"weeklySummaries": [{"childId": str(child), "subjectCode": "9709", "enabled": False}]},
    )
    assert res.status_code == 422


def test_malformed_child_id_is_422(
    me_client: TestClient,
    pg_sessionmaker: sessionmaker[Session],  # noqa: F811
    history_store: HistoryStore,  # noqa: F811
) -> None:
    parent, _ = _family(pg_sessionmaker, history_store)
    _auth_as(me_client, parent, Role.parent)
    res = me_client.put(
        PATH,
        json={"weeklySummaries": [{"childId": "nope", "subjectCode": "0580", "enabled": False}]},
    )
    assert res.status_code == 422


@pytest.mark.parametrize("role", [Role.student, Role.teacher])
def test_other_roles_read_null_and_cannot_set_it(
    me_client: TestClient,
    pg_sessionmaker: sessionmaker[Session],  # noqa: F811
    role: Role,
) -> None:
    user = _seed_user(pg_sessionmaker, role)
    _auth_as(me_client, user, role)
    assert me_client.get(PATH).json()["weeklySummaries"] is None
    res = me_client.put(
        PATH,
        json={"weeklySummaries": [{"childId": str(uuid.uuid4()), "subjectCode": "0580", "enabled": True}]},
    )
    assert res.status_code == 422
```

- [ ] **Step 2: Run to see them fail**

Run: `PYTHONPATH=$(pwd) /home/sico/Code/Lemely/.venv/bin/python -m pytest tests/test_web_me_weekly_summaries.py -v`
Expected: FAIL with `KeyError: 'weeklySummaries'`.

- [ ] **Step 3: DTOs**

In `lemely/web/schemas_me.py` add above `NotificationPreferencesDTO`:

```python
class WeeklySummaryDTO(ApiModel):
    """One weekly summary email switch: a linked child's subject (lane L11)."""

    childId: str
    childName: str
    subjectCode: str
    subjectName: str
    enabled: bool


class WeeklySummaryUpdateDTO(ApiModel):
    """One weekly summary flip in a ``PUT``. The child must be linked to the caller."""

    childId: str
    subjectCode: str = Field(pattern=r"^\d{4}$")
    enabled: bool
```

Add to `NotificationPreferencesDTO` (after `quietHoursEnd`), with a docstring sentence "``weeklySummaries`` is ``null`` for every role but parent (lane L11).":

```python
    weeklySummaries: list[WeeklySummaryDTO] | None = None
```

Add to `NotificationPreferencesUpdateDTO`:

```python
    weeklySummaries: list[WeeklySummaryUpdateDTO] | None = Field(default=None, max_length=50)
```

Add both names to `__all__`.

- [ ] **Step 4: The helper module**

`lemely/web/weekly_summaries.py`:

```python
"""Weekly summary email flags for a parent's linked children (lane L11).

Kept out of :mod:`lemely.web.routers.me` so that router stays a thin
translation of the preference row. Authz: every child id comes from
:meth:`ParentLinkService.linked_children` on read, and is checked with
:meth:`ParentLinkService.get_child` on write, so a parent can never read or
set a flag for a child who is not linked to them.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from fastapi import HTTPException

from lemely.db.parent_weekly_email_repo import DEFAULT_WEEKLY_ENABLED
from lemely.io.det.profiles import get_profile
from lemely.web.schemas_me import WeeklySummaryDTO

if TYPE_CHECKING:
    from collections.abc import Sequence

    from lemely.core.history import HistoryStoreProtocol
    from lemely.db.class_repo import ClassService
    from lemely.db.parent_repo import ParentLinkService
    from lemely.db.parent_weekly_email_repo import ParentWeeklyEmailService
    from lemely.db.student_profile_repo import StudentProfileService
    from lemely.web.schemas_me import WeeklySummaryUpdateDTO


def _subject_name(code: str) -> str:
    return get_profile(code).name or code


def child_subject_codes(
    child_id: uuid.UUID,
    *,
    classes: ClassService,
    profiles: StudentProfileService,
    history: HistoryStoreProtocol,
) -> list[str]:
    """Enrolments, class subjects and history subjects, sorted by subject name."""
    codes = {e.subject_code for e in profiles.list_enrolments(child_id)}
    codes |= {c.subject_code for c in classes.student_classes(child_id) if c.subject_code}
    codes |= {r.metadata.subject_code for r in history.load(str(child_id)).records}
    return sorted(codes, key=lambda code: (_subject_name(code), code))


def weekly_summary_dtos(
    parent_id: str,
    *,
    links: ParentLinkService,
    classes: ClassService,
    profiles: StudentProfileService,
    history: HistoryStoreProtocol,
    flags: ParentWeeklyEmailService,
) -> list[WeeklySummaryDTO]:
    stored = flags.flags_for(parent_id)
    rows: list[WeeklySummaryDTO] = []
    for child in links.linked_children(parent_id):
        for code in child_subject_codes(
            child.child_id, classes=classes, profiles=profiles, history=history
        ):
            rows.append(
                WeeklySummaryDTO(
                    childId=str(child.child_id),
                    childName=child.display_name,
                    subjectCode=code,
                    subjectName=_subject_name(code),
                    enabled=stored.get((child.child_id, code), DEFAULT_WEEKLY_ENABLED),
                )
            )
    return rows


def apply_weekly_updates(
    parent_id: str,
    updates: Sequence[WeeklySummaryUpdateDTO],
    *,
    links: ParentLinkService,
    classes: ClassService,
    profiles: StudentProfileService,
    history: HistoryStoreProtocol,
    flags: ParentWeeklyEmailService,
) -> None:
    """Validate every update first (422/403), then store them in one transaction."""
    checked: list[tuple[uuid.UUID, str, bool]] = []
    subjects_by_child: dict[uuid.UUID, set[str]] = {}
    for update in updates:
        try:
            child = links.get_child(parent_id, update.childId)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if child is None:
            raise HTTPException(
                status_code=403, detail=f"Child {update.childId} is not linked to this parent"
            )
        if child.child_id not in subjects_by_child:
            subjects_by_child[child.child_id] = set(
                child_subject_codes(child.child_id, classes=classes, profiles=profiles, history=history)
            )
        if update.subjectCode not in subjects_by_child[child.child_id]:
            raise HTTPException(
                status_code=422,
                detail=f"{update.subjectCode} is not one of this child's subjects.",
            )
        checked.append((child.child_id, update.subjectCode, update.enabled))
    flags.set_flags(parent_id, checked)


__all__ = ["apply_weekly_updates", "child_subject_codes", "weekly_summary_dtos"]
```

- [ ] **Step 5: Router**

In `lemely/web/routers/me.py`:
1. Imports: `from lemely.core.history import HistoryStoreProtocol`, `from lemely.db.class_repo import ClassService`, `from lemely.db.parent_repo import ParentLinkService`, `from lemely.db.parent_weekly_email_repo import ParentWeeklyEmailService`, `from lemely.web.weekly_summaries import apply_weekly_updates, weekly_summary_dtos`; add `get_class_service`, `get_history_store`, `get_parent_link_service`, `get_parent_weekly_email_service` to the deps import.
2. Add, after `_TUTORING_TOGGLE_ROLES`:

```python
# Lane L11: weekly summary emails belong to the parent alone. Every other
# role's GET has the field null, and a PUT that supplies it is a 422.
_WEEKLY_SUMMARY_ROLES = frozenset({Role.parent.value})


class _WeeklyDeps:
    """The services the weekly-summary helpers need, resolved once per request."""

    def __init__(
        self,
        links: Annotated[ParentLinkService, Depends(get_parent_link_service)],
        classes: Annotated[ClassService, Depends(get_class_service)],
        profiles: Annotated[StudentProfileService, Depends(get_student_profile_service)],
        history: Annotated[HistoryStoreProtocol, Depends(get_history_store)],
        flags: Annotated[ParentWeeklyEmailService, Depends(get_parent_weekly_email_service)],
    ) -> None:
        self.kw = {
            "links": links,
            "classes": classes,
            "profiles": profiles,
            "history": history,
            "flags": flags,
        }


def _with_weekly(
    dto: NotificationPreferencesDTO, auth: AuthContext, deps: _WeeklyDeps
) -> NotificationPreferencesDTO:
    if auth.role not in _WEEKLY_SUMMARY_ROLES:
        return dto
    return dto.model_copy(
        update={"weeklySummaries": weekly_summary_dtos(auth.user_id, **deps.kw)}
    )
```

3. `get_notification_preferences`: add parameter `weekly: Annotated[_WeeklyDeps, Depends()]` and return `_with_weekly(_to_dto(row, role=auth.role), auth, weekly)`.
4. `put_notification_preferences`: add the same parameter. Directly after the `_TUTORING_TOGGLE_ROLES` refusal loop, add:

```python
    if "weeklySummaries" in provided and auth.role not in _WEEKLY_SUMMARY_ROLES:
        raise HTTPException(
            status_code=422,
            detail="weeklySummaries is only settable for the parent role.",
        )
    if "weeklySummaries" in provided:
        apply_weekly_updates(auth.user_id, payload.weeklySummaries or [], **weekly.kw)
```

and change its final line to `return _with_weekly(_to_dto(row, role=auth.role), auth, weekly)`. The weekly write happens before `service.set(...)`; both are idempotent upserts, so a later 422 from quiet hours leaves a weekly flip stored. Note this in the PUT docstring: "``weeklySummaries`` (parent only, lane L11) is validated in full, then stored, before the toggle row."

- [ ] **Step 6: Run the new and the existing me tests**

Run: `PYTHONPATH=$(pwd) /home/sico/Code/Lemely/.venv/bin/python -m pytest tests/test_web_me_weekly_summaries.py $(ls tests/test_web_me*.py tests/test_*notification_pref*.py 2>/dev/null | tr '\n' ' ') -v`
Expected: all pass. Existing me tests that build their own app now also need the four new dependencies overridden: if one fails with a dev-database connection error, add the overrides for `get_class_service`, `get_parent_link_service`, `get_history_store`, `get_parent_weekly_email_service` to that test file's client fixture in this commit.

- [ ] **Step 7: Commit**

```bash
PYTHONPATH=$(pwd) pre-commit run --files lemely/web/weekly_summaries.py lemely/web/schemas_me.py lemely/web/routers/me.py tests/test_web_me_weekly_summaries.py
git commit -S -m "feat(me): weekly summary flags per child subject on notification preferences" -- lemely/web/weekly_summaries.py lemely/web/schemas_me.py lemely/web/routers/me.py tests/test_web_me_weekly_summaries.py
```

---

### Task 7: Frontend types, weekly update helper and paths

**Files:**
- Modify: `web/src/lib/parentTypes.ts`, `web/src/lib/notificationPrefs.ts`
- Create: `web/src/portals/parent/screens/model/parentPaths.ts`
- Test: `web/tests/unit/notificationPrefsWeekly.test.ts`

**Interfaces:**
- Produces TS types: `TopicTrend`, `TopicPaperLoss`, `TopicAssignment`, `TopicDoing`, `ParentTopic`, `SeriesPoint`, `PaperSeries`; `SubjectDetail` gains `childName`, `targetGrade`, `goalGrade`, `series`, `topics`; `ChildWeaknesses` gains `displayName`, `paperCount`, `topics`. `WeeklySummary`, `WeeklySummaryUpdate`; `NotificationPreferences.weeklySummaries: WeeklySummary[] | null`; `NotificationPreferencesUpdate.weeklySummaries?: WeeklySummaryUpdate[]`; `weeklySummaryUpdate(childId, subjectCode, enabled): NotificationPreferencesUpdate`. Paths: `parentOverviewPath(childId)`, `parentSubjectPath(childId, code)`, `parentTopicsPath(childId, subjectCode?)`, `PARENT_EMAILS_PATH`.

- [ ] **Step 1: Write the failing test**

```ts
import { describe, expect, it } from "vitest"
import { weeklySummaryUpdate } from "@/lib/notificationPrefs"
import {
  PARENT_EMAILS_PATH,
  parentOverviewPath,
  parentSubjectPath,
  parentTopicsPath,
} from "@/portals/parent/screens/model/parentPaths"

describe("weeklySummaryUpdate", () => {
  it("sends exactly one weekly item and no other key", () => {
    expect(weeklySummaryUpdate("c1", "0580", false)).toEqual({
      weeklySummaries: [{ childId: "c1", subjectCode: "0580", enabled: false }],
    })
  })
})

describe("parent paths", () => {
  it("builds the screens' links", () => {
    expect(parentOverviewPath("c1")).toBe("/parent/children/c1")
    expect(parentSubjectPath("c1", "0580")).toBe("/parent/children/c1/subjects/0580")
    expect(parentTopicsPath("c1")).toBe("/parent/c1/topics")
    expect(parentTopicsPath("c1", "0580")).toBe("/parent/c1/topics?subject=0580")
    expect(PARENT_EMAILS_PATH).toBe("/parent/emails")
  })
})
```

- [ ] **Step 2: Run to see it fail**

Run: `cd web && npx vitest run tests/unit/notificationPrefsWeekly.test.ts`
Expected: FAIL (`weeklySummaryUpdate` is not exported; module not found).

- [ ] **Step 3: Implement**

Append to `web/src/lib/parentTypes.ts` (inside the P-03 and P-04 sections; keep every existing field):

```ts
// ── L11: ranked topics, paper series ───────────────────────────────────────

export type TopicTrend = "better" | "worse" | "same"

export interface TopicPaperLoss {
  paperId: string
  recordedAt: string
  lostMarks: number
}

export interface TopicAssignment {
  /** Display name only; null when the teacher has none. Never an email. */
  teacherName: string | null
  dueAt: string | null
}

export interface TopicDoing {
  practisedThisWeek: number
  practiceAwarded: number
  practiceMaximum: number
  inPlanThisWeek: boolean
  flashcardsDue: number
  assignment: TopicAssignment | null
}

/** Ranked by the backend (marks lost on the last `basisPapers` papers). Never re-sort. */
export interface ParentTopic {
  subjectCode: string
  subjectName: string
  topic: string
  lostMarks: number
  basisPapers: number
  trend: TopicTrend
  /** Newest first. */
  papers: TopicPaperLoss[]
  doing: TopicDoing
}

export interface SeriesPoint {
  paperId: string
  grade: string
  awardedMarks: number
  maximumMarks: number
  percentage: number
  recordedAt: string
}

export interface PaperSeries {
  paperNumber: number
  maximumMarks: number
  /** Goal grade threshold in marks on the latest paper; null when the paper cannot award it. */
  goalLine: number | null
  /** Oldest first, at most five. */
  points: SeriesPoint[]
}
```

Add to `interface SubjectDetail`:

```ts
  childName: string
  targetGrade: string | null
  goalGrade: string
  /** Most recently sat series first. */
  series: PaperSeries[]
  topics: ParentTopic[]
```

Add to `interface ChildWeaknesses`:

```ts
  displayName: string
  /** Real past papers only. */
  paperCount: number
  topics: ParentTopic[]
```

In `web/src/lib/notificationPrefs.ts`, add after `NotificationPreferences`:

```ts
/** One weekly summary switch (lane L11): a linked child's subject. Parent only. */
export interface WeeklySummary {
  childId: string
  childName: string
  subjectCode: string
  subjectName: string
  enabled: boolean
}

export interface WeeklySummaryUpdate {
  childId: string
  subjectCode: string
  enabled: boolean
}
```

Add `weeklySummaries: WeeklySummary[] | null` to `NotificationPreferences` (doc comment: "`null` for every role but parent."), add `weeklySummaries: WeeklySummaryUpdate[]` to the `Partial<{…}>` of `NotificationPreferencesUpdate`, and append:

```ts
/**
 * The PUT body for one weekly summary flip. One item, never the whole list,
 * for the same reason a toggle sends one key (see `NotificationPreferencesUpdate`).
 */
export function weeklySummaryUpdate(
  childId: string,
  subjectCode: string,
  enabled: boolean,
): NotificationPreferencesUpdate {
  return { weeklySummaries: [{ childId, subjectCode, enabled }] }
}
```

`web/src/portals/parent/screens/model/parentPaths.ts`:

```ts
/*
 * L11 · the parent screens' links in one place. The Topics path follows the F1
 * contract (`/parent/:childId/topics`); if F1 registered a different path,
 * change it here and nowhere else.
 */

export function parentOverviewPath(childId: string): string {
  return `/parent/children/${childId}`
}

export function parentSubjectPath(childId: string, code: string): string {
  return `/parent/children/${childId}/subjects/${code}`
}

export function parentTopicsPath(childId: string, subjectCode?: string): string {
  const base = `/parent/${childId}/topics`
  return subjectCode ? `${base}?subject=${encodeURIComponent(subjectCode)}` : base
}

export const PARENT_EMAILS_PATH = "/parent/emails"
```

- [ ] **Step 4: Run the test and the existing prefs test**

Run: `cd web && npx vitest run tests/unit/notificationPrefsWeekly.test.ts tests/unit/notificationPrefs.test.ts && npx tsc -b --noEmit`
Expected: PASS; typecheck clean apart from the screens Task 11–13 replace (if `tsc` reports `SubjectDetail.tsx`/`Weaknesses.tsx` errors, they are about to be rewritten; anything else must be fixed here).

- [ ] **Step 5: Commit**

```bash
cd web && npx oxlint src/lib/parentTypes.ts src/lib/notificationPrefs.ts src/portals/parent/screens/model/parentPaths.ts tests/unit/notificationPrefsWeekly.test.ts && cd ..
PYTHONPATH=$(pwd) pre-commit run --files web/src/lib/parentTypes.ts web/src/lib/notificationPrefs.ts web/src/portals/parent/screens/model/parentPaths.ts web/tests/unit/notificationPrefsWeekly.test.ts
git commit -S -m "feat(web): parent topic, series and weekly summary types" -- web/src/lib/parentTypes.ts web/src/lib/notificationPrefs.ts web/src/portals/parent/screens/model/parentPaths.ts web/tests/unit/notificationPrefsWeekly.test.ts
```

Query keys: unchanged. `useChildSubject` (`["parent","children",id,"subjects",code]`), `useChildWeaknesses` (`["parent","children",id,"weaknesses"]`) and `useNotificationPreferences` (`["me","notification-preferences"]`) already fetch these routes; only their types grew. No new hook is needed. `useUpdateNotificationPreferences` already writes the PUT echo into the cache.

---

### Task 8: Shared topic copy (view model)

**Files:**
- Create: `web/src/portals/parent/screens/model/topicCopy.ts`
- Test: `web/tests/unit/parentTopicCopy.test.ts`

**Interfaces:**
- Consumes: `ParentTopic`, `TopicDoing` (Task 7); `Trend` type from `@/components/redesign` (F1).
- Produces: `monthLabel(iso)`, `timesWord(n)`, `dueWords(dueIso, now)`, `practiceLine(doing, withMarks)`, `rowDoing(doing)`, `doingLines(doing, topic, now): DoingLine[]`, `topicKey(t)`, `rankRows(topics, opts): RankRowModel[]`, `subjectTone(index)`; types `DoingLine { kind: "practice" | "plan" | "flashcards" | "assigned"; text: string }`, `RankRowModel { key, rank, title, sub, marksLost, trend, assigned, bar?, subjectCode, subjectName, topic }`.

- [ ] **Step 1: Write the failing tests**

```ts
import { describe, expect, it } from "vitest"
import type { ParentTopic, TopicDoing } from "@/lib/parentTypes"
import {
  doingLines,
  dueWords,
  monthLabel,
  practiceLine,
  rankRows,
  rowDoing,
  subjectTone,
  timesWord,
  topicKey,
} from "@/portals/parent/screens/model/topicCopy"

const NOW = new Date(2026, 10, 18, 12) // Wednesday 18 Nov 2026, local time
const NONE: TopicDoing = {
  practisedThisWeek: 0,
  practiceAwarded: 0,
  practiceMaximum: 0,
  inPlanThisWeek: false,
  flashcardsDue: 0,
  assignment: null,
}

function topic(over: Partial<ParentTopic> = {}): ParentTopic {
  return {
    subjectCode: "0580",
    subjectName: "Maths",
    topic: "Vectors",
    lostMarks: 9,
    basisPapers: 3,
    trend: "worse",
    papers: [],
    doing: NONE,
    ...over,
  }
}

describe("monthLabel", () => {
  it("names the month in three letters", () => {
    expect(monthLabel(new Date(2026, 3, 9).toISOString())).toBe("Apr")
    expect(monthLabel("not a date")).toBe("")
  })
})

describe("timesWord", () => {
  it("reads once, twice, then a count", () => {
    expect([timesWord(1), timesWord(2), timesWord(5)]).toEqual(["once", "twice", "5 times"])
  })
})

describe("dueWords", () => {
  it("speaks of today, tomorrow, a weekday this week, then a date", () => {
    expect(dueWords(new Date(2026, 10, 18, 20).toISOString(), NOW)).toBe("due today")
    expect(dueWords(new Date(2026, 10, 19, 9).toISOString(), NOW)).toBe("due tomorrow")
    expect(dueWords(new Date(2026, 10, 20, 9).toISOString(), NOW)).toBe("due Friday")
    expect(dueWords(new Date(2026, 11, 2, 9).toISOString(), NOW)).toBe("due 2 Dec")
    expect(dueWords(new Date(2026, 10, 16, 9).toISOString(), NOW)).toBe("was due 16 Nov")
    expect(dueWords(null, NOW)).toBeNull()
  })
})

describe("practiceLine", () => {
  const doing = { ...NONE, practisedThisWeek: 2, practiceAwarded: 7, practiceMaximum: 9 }
  it("adds marks back only when asked", () => {
    expect(practiceLine(doing, false)).toBe("Practised twice this week")
    expect(practiceLine(doing, true)).toBe("Practised twice this week · 7 of 9 back")
    expect(practiceLine(NONE, true)).toBeNull()
  })
})

describe("rowDoing", () => {
  it("prefers practice, then plan, then cards, then the assignment's due date", () => {
    expect(rowDoing({ ...NONE, practisedThisWeek: 1, inPlanThisWeek: true })).toBe(
      "Practised once this week",
    )
    expect(rowDoing({ ...NONE, inPlanThisWeek: true, flashcardsDue: 3 })).toBe("In this week’s plan")
    expect(rowDoing({ ...NONE, flashcardsDue: 1 })).toBe("1 flashcard due")
    expect(rowDoing({ ...NONE, flashcardsDue: 12 })).toBe("12 flashcards due")
    expect(rowDoing({ ...NONE, assignment: { teacherName: "Ms Adel", dueAt: null } })).toBe(
      "Set by their teacher",
    )
    expect(rowDoing(NONE)).toBe("Nothing yet")
  })
})

describe("doingLines", () => {
  it("lists every signal, the assignment last with teacher and due date", () => {
    const lines = doingLines(
      {
        ...NONE,
        practisedThisWeek: 2,
        practiceAwarded: 7,
        practiceMaximum: 9,
        inPlanThisWeek: true,
        flashcardsDue: 4,
        assignment: { teacherName: "Ms Adel", dueAt: new Date(2026, 10, 20, 9).toISOString() },
      },
      "Vectors",
      NOW,
    )
    expect(lines).toEqual([
      { kind: "practice", text: "Practised twice this week · 7 of 9 back" },
      { kind: "plan", text: "In this week’s plan" },
      { kind: "flashcards", text: "4 flashcards due" },
      { kind: "assigned", text: "Ms Adel set a Vectors set, due Friday" },
    ])
  })
  it("falls back to their teacher when the name is unknown", () => {
    expect(
      doingLines({ ...NONE, assignment: { teacherName: null, dueAt: null } }, "Waves", NOW),
    ).toEqual([{ kind: "assigned", text: "Their teacher set a Waves set" }])
  })
  it("is empty when nothing is happening", () => {
    expect(doingLines(NONE, "Waves", NOW)).toEqual([])
  })
})

describe("rankRows", () => {
  const topics = [
    topic({ topic: "Vectors", lostMarks: 9, doing: { ...NONE, assignment: { teacherName: null, dueAt: null } } }),
    topic({ topic: "Algebra", lostMarks: 3, trend: "better" }),
    topic({ topic: "Waves", subjectCode: "0625", subjectName: "Physics", lostMarks: 2 }),
  ]
  it("keeps backend order, ranks from 1, scales bars to the top row", () => {
    const rows = rankRows(topics, { withSubject: false, withBar: true, limit: 2 })
    expect(rows.map((r) => [r.rank, r.title, r.marksLost, r.bar, r.assigned])).toEqual([
      [1, "Vectors", 9, 1, true],
      [2, "Algebra", 3, 3 / 9, false],
    ])
    expect(rows[1].sub).toBe("Nothing yet")
  })
  it("prefixes the subject when the list spans subjects and omits bars", () => {
    const rows = rankRows(topics, { withSubject: true, withBar: false })
    expect(rows[2].sub).toBe("Physics · Nothing yet")
    expect(rows[2].bar).toBeUndefined()
    expect(rows[2].key).toBe(topicKey(topics[2]))
  })
})

describe("subjectTone", () => {
  it("cycles three token tones", () => {
    expect([0, 1, 2, 3].map(subjectTone)).toEqual(["bg-grade-a", "bg-primary", "bg-tertiary", "bg-grade-a"])
  })
})
```

- [ ] **Step 2: Run to see them fail**

Run: `cd web && npx vitest run tests/unit/parentTopicCopy.test.ts`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement**

```ts
/*
 * L11 · the words the parent topic rows, sheet and side panel use. Pure, so
 * vitest (node environment) pins every copy pick. Dates read in the viewer's
 * local time: "due Friday" means the parent's Friday.
 */
import type { Trend } from "@/components/redesign"
import type { ParentTopic, TopicDoing } from "@/lib/parentTypes"

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
const WEEKDAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
const DAY_MS = 86_400_000
const TONES = ["bg-grade-a", "bg-primary", "bg-tertiary"] as const

export function monthLabel(iso: string): string {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? "" : MONTHS[d.getMonth()]
}

export function timesWord(n: number): string {
  if (n === 1) return "once"
  if (n === 2) return "twice"
  return `${n} times`
}

function dayStart(d: Date): number {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()
}

function shortDate(d: Date): string {
  return `${d.getDate()} ${MONTHS[d.getMonth()]}`
}

export function dueWords(dueIso: string | null, now: Date): string | null {
  if (!dueIso) return null
  const due = new Date(dueIso)
  if (Number.isNaN(due.getTime())) return null
  const days = Math.round((dayStart(due) - dayStart(now)) / DAY_MS)
  if (days < 0) return `was due ${shortDate(due)}`
  if (days === 0) return "due today"
  if (days === 1) return "due tomorrow"
  if (days < 7) return `due ${WEEKDAYS[due.getDay()]}`
  return `due ${shortDate(due)}`
}

export function practiceLine(doing: TopicDoing, withMarks: boolean): string | null {
  if (doing.practisedThisWeek < 1) return null
  const line = `Practised ${timesWord(doing.practisedThisWeek)} this week`
  return withMarks && doing.practiceMaximum > 0
    ? `${line} · ${doing.practiceAwarded} of ${doing.practiceMaximum} back`
    : line
}

const PLAN_LINE = "In this week’s plan"

function flashcardsLine(doing: TopicDoing): string | null {
  if (doing.flashcardsDue < 1) return null
  return `${doing.flashcardsDue} ${doing.flashcardsDue === 1 ? "flashcard" : "flashcards"} due`
}

function capitalise(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1)
}

/** The one line a ranked row shows under its title. */
export function rowDoing(doing: TopicDoing, now: Date = new Date()): string {
  const practice = practiceLine(doing, false)
  if (practice) return practice
  if (doing.inPlanThisWeek) return PLAN_LINE
  const cards = flashcardsLine(doing)
  if (cards) return cards
  if (doing.assignment) {
    const due = dueWords(doing.assignment.dueAt, now)
    return due ? capitalise(due) : "Set by their teacher"
  }
  return "Nothing yet"
}

export interface DoingLine {
  kind: "practice" | "plan" | "flashcards" | "assigned"
  text: string
}

/** Every signal for the sheet and side panel. Empty means "Nothing yet". */
export function doingLines(doing: TopicDoing, topic: string, now: Date): DoingLine[] {
  const lines: DoingLine[] = []
  const practice = practiceLine(doing, true)
  if (practice) lines.push({ kind: "practice", text: practice })
  if (doing.inPlanThisWeek) lines.push({ kind: "plan", text: PLAN_LINE })
  const cards = flashcardsLine(doing)
  if (cards) lines.push({ kind: "flashcards", text: cards })
  if (doing.assignment) {
    const who = doing.assignment.teacherName ?? "Their teacher"
    const due = dueWords(doing.assignment.dueAt, now)
    lines.push({
      kind: "assigned",
      text: due ? `${who} set a ${topic} set, ${due}` : `${who} set a ${topic} set`,
    })
  }
  return lines
}

export function topicKey(t: Pick<ParentTopic, "subjectCode" | "topic">): string {
  return `${t.subjectCode}::${t.topic}`
}

export interface RankRowModel {
  key: string
  rank: number
  title: string
  sub: string
  marksLost: number
  trend: Trend
  assigned: boolean
  bar?: number
  subjectCode: string
  subjectName: string
  topic: string
}

export function rankRows(
  topics: ParentTopic[],
  opts: { withSubject: boolean; withBar: boolean; limit?: number; now?: Date },
): RankRowModel[] {
  const list = opts.limit === undefined ? topics : topics.slice(0, opts.limit)
  const top = Math.max(1, ...list.map((t) => t.lostMarks))
  return list.map((t, i) => {
    const doing = rowDoing(t.doing, opts.now)
    return {
      key: topicKey(t),
      rank: i + 1,
      title: t.topic,
      sub: opts.withSubject ? `${t.subjectName} · ${doing}` : doing,
      marksLost: t.lostMarks,
      trend: t.trend,
      assigned: t.doing.assignment !== null,
      bar: opts.withBar ? t.lostMarks / top : undefined,
      subjectCode: t.subjectCode,
      subjectName: t.subjectName,
      topic: t.topic,
    }
  })
}

export function subjectTone(index: number): (typeof TONES)[number] {
  return TONES[index % TONES.length]
}
```

- [ ] **Step 4: Run to see them pass**

Run: `cd web && npx vitest run tests/unit/parentTopicCopy.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
PYTHONPATH=$(pwd) pre-commit run --files web/src/portals/parent/screens/model/topicCopy.ts web/tests/unit/parentTopicCopy.test.ts
git commit -S -m "feat(web): parent topic copy view model" -- web/src/portals/parent/screens/model/topicCopy.ts web/tests/unit/parentTopicCopy.test.ts
```

---

### Task 9: Subject view model

**Files:**
- Create: `web/src/portals/parent/screens/model/subjectModel.ts`
- Modify: `web/tests/unit/parentOutcome.test.ts` (import `gradeArticle` from the model)
- Test: `web/tests/unit/parentSubjectModel.test.ts`

**Interfaces:**
- Consumes: `SubjectDetail`, `PaperSeries` (Task 7); `monthLabel`, `rankRows` (Task 8); `ApiError`; `parentLoadFailureMessage`.
- Produces: `gradeArticle(grade)`; `subjectState(q, ctx): SubjectState`; `summaryLine(d)`; `seriesTabs(d)`; `barHeight(awarded, maximum, goalLine)`; `stepsModel(series, goalGrade): StepsModel`; `trendLine(series): TrendLine | null`; `subjectTopicRows(d)`; `paperRows(d, expanded)`; `sparseBasis(subjectName)`; `firstRunBasis(subjectName, childName)`; `nothingWeakCopy(subjectName)`; `PAPERS_FOLDED = 3`; `TOPICS_ON_SUBJECT = 4`; `FIRST_RUN_STEPS`.

`stepsModel` returns `papers: { id, label, grade, pct }[]` for F1 `StepsPath`, where `pct` is the bar height in percent of the goal block (mock formula `(m − 0.4·out) / (line − 0.4·out)`), plus `captions` (`"61/80"`) and `goalCaption` (`"68/80"`), `toGo` and the full `ariaLabel` from the mock.

- [ ] **Step 1: Write the failing tests**

```ts
import { describe, expect, it } from "vitest"
import { ApiError } from "@/lib/api"
import type { PaperSeries, SubjectDetail } from "@/lib/parentTypes"
import {
  barHeight,
  firstRunBasis,
  gradeArticle,
  nothingWeakCopy,
  paperRows,
  seriesTabs,
  sparseBasis,
  stepsModel,
  subjectState,
  subjectTopicRows,
  summaryLine,
  trendLine,
} from "@/portals/parent/screens/model/subjectModel"

const iso = (y: number, m: number, d = 10) => new Date(y, m, d, 12).toISOString()

const P4: PaperSeries = {
  paperNumber: 4,
  maximumMarks: 80,
  goalLine: 68,
  points: [
    { paperId: "0580/41", grade: "C", awardedMarks: 45, maximumMarks: 80, percentage: 56, recordedAt: iso(2023, 9) },
    { paperId: "0580/43", grade: "B", awardedMarks: 48, maximumMarks: 80, percentage: 60, recordedAt: iso(2024, 0) },
    { paperId: "0580/42", grade: "A", awardedMarks: 61, maximumMarks: 80, percentage: 76, recordedAt: iso(2024, 3) },
  ],
}

function detail(over: Partial<SubjectDetail> = {}): SubjectDetail {
  return {
    childId: "c1",
    childName: "Omar",
    subjectCode: "0580",
    subjectName: "Mathematics",
    qualificationLevel: "igcse",
    predictedGrade: "A",
    targetGrade: "A*",
    goalGrade: "A*",
    papers: [
      { paperId: "0580/42", marks: "61/80", grade: "A", recordedAt: iso(2024, 3) },
      { paperId: "0580/21", marks: "53/70", grade: "A", recordedAt: iso(2024, 2) },
      { paperId: "0580/42", marks: "50/80", grade: "B", recordedAt: iso(2024, 1) },
      { paperId: "0580/43", marks: "48/80", grade: "B", recordedAt: iso(2024, 0) },
    ],
    boundaryDistance: null,
    weakTopics: [],
    series: [P4, { ...P4, paperNumber: 2 }],
    topics: [],
    ...over,
  }
}

describe("gradeArticle", () => {
  it("uses the spoken letter name", () => {
    expect(["A", "A*", "E", "F", "B", "U"].map(gradeArticle)).toEqual(["an", "an", "an", "an", "a", "a"])
  })
})

describe("subjectState", () => {
  const ctx = { childName: "Omar", childKnown: true, subjectName: "Mathematics" }
  it("maps pending, success and generic errors", () => {
    expect(subjectState({ status: "pending" }, ctx)).toEqual({ kind: "loading" })
    const d = detail()
    expect(subjectState({ status: "success", data: d }, ctx)).toEqual({ kind: "ready", detail: d })
    const err = subjectState({ status: "error", error: new ApiError(500, "x") }, ctx)
    expect(err).toMatchObject({ kind: "error", heading: "We couldn’t load this subject" })
  })
  it("treats 'No papers for subject' as the first run, only for a linked child", () => {
    const noPapers = new ApiError(404, "x", "No papers for subject 0580")
    expect(subjectState({ status: "error", error: noPapers }, ctx)).toEqual({
      kind: "first-run",
      childName: "Omar",
      subjectName: "Mathematics",
    })
    expect(subjectState({ status: "error", error: noPapers }, { ...ctx, childKnown: false }).kind).toBe(
      "error",
    )
    const unknownChild = new ApiError(404, "x", "Unknown child: c9")
    expect(subjectState({ status: "error", error: unknownChild }, ctx).kind).toBe("error")
  })
})

describe("summaryLine", () => {
  it("names predicted, target and paper count", () => {
    expect(summaryLine(detail())).toEqual({ predicted: "A", target: "A*", papers: "4 papers" })
    expect(summaryLine(detail({ targetGrade: null, papers: detail().papers.slice(0, 1) }))).toEqual({
      predicted: "A",
      target: null,
      papers: "1 paper",
    })
  })
})

describe("seriesTabs", () => {
  it("labels every series, newest first", () => {
    expect(seriesTabs(detail())).toEqual([
      { paperNumber: 4, label: "Paper 4" },
      { paperNumber: 2, label: "Paper 2" },
    ])
  })
})

describe("barHeight", () => {
  it("follows the mock's goal-relative formula and clamps", () => {
    expect(barHeight(61, 80, 68)).toBe(81)
    expect(barHeight(20, 80, 68)).toBe(0)
    expect(barHeight(80, 80, 68)).toBe(100)
    expect(barHeight(40, 80, null)).toBe(50)
    expect(barHeight(1, 0, null)).toBe(0)
  })
})

describe("stepsModel", () => {
  it("builds bars, captions, goal and the screen-reader sentence", () => {
    const m = stepsModel(P4, "A*")
    expect(m.papers.map((p) => [p.label, p.grade, p.pct])).toEqual([
      ["Oct", "C", 36],
      ["Jan", "B", 44],
      ["Apr", "A", 81],
    ])
    expect(m.captions).toEqual(["45/80", "48/80", "61/80"])
    expect(m.goal).toBe("A*")
    expect(m.goalCaption).toBe("68/80")
    expect(m.toGo).toBe(7)
    expect(m.ariaLabel).toBe(
      "Paper 4: C, 45 out of 80 in Oct; B, 48 out of 80 in Jan; A, 61 out of 80 in Apr. A* line 68, 7 marks to go.",
    )
  })
  it("drops the goal caption and distance when the paper cannot award the goal", () => {
    const m = stepsModel({ ...P4, goalLine: null }, "A*")
    expect([m.goalCaption, m.toGo]).toEqual([null, null])
    expect(m.ariaLabel.endsWith("in Apr.")).toBe(true)
  })
})

describe("trendLine", () => {
  it("says where they are heading and the change since the first paper", () => {
    expect(trendLine(P4)).toEqual({ article: "an", grade: "A", change: "up 16 marks since Oct" })
    const down = { ...P4, points: [P4.points[2], { ...P4.points[0], recordedAt: iso(2024, 5) }] }
    expect(trendLine(down)?.change).toBe("down 16 marks since Apr")
    const one = { ...P4, points: [P4.points[1]] }
    expect(trendLine(one)).toEqual({ article: "a", grade: "B", change: null })
    expect(trendLine({ ...P4, points: [] })).toBeNull()
  })
})

describe("subject topics, papers and copy", () => {
  it("shows at most four topic rows with bars and no subject prefix", () => {
    const t = {
      subjectCode: "0580",
      subjectName: "Maths",
      topic: "Vectors",
      lostMarks: 9,
      basisPapers: 3,
      trend: "worse" as const,
      papers: [],
      doing: { practisedThisWeek: 0, practiceAwarded: 0, practiceMaximum: 0, inPlanThisWeek: false, flashcardsDue: 0, assignment: null },
    }
    const rows = subjectTopicRows(detail({ topics: [t, t, t, t, t].map((x, i) => ({ ...x, topic: `T${i}` })) }))
    expect(rows).toHaveLength(4)
    expect(rows[0]).toMatchObject({ bar: 1, sub: "Nothing yet" })
  })
  it("folds papers to three with an All N link, and expands", () => {
    const folded = paperRows(detail(), false)
    expect(folded.rows.map((r) => r.sub)).toEqual(["61/80 · Apr", "53/70 · Mar", "50/80 · Feb"])
    expect(folded.moreLabel).toBe("All 4")
    expect(paperRows(detail(), true)).toMatchObject({ moreLabel: null })
    expect(paperRows(detail(), true).rows).toHaveLength(4)
    expect(folded.rows[0].key).toBe(`0580/42-${iso(2024, 3)}`)
  })
  it("words the sparse, first-run and nothing-weak states", () => {
    expect(sparseBasis("Mathematics")).toBe(
      "Based on the one paper they’ve had marked in Mathematics so far. More papers make this steadier.",
    )
    expect(firstRunBasis("Mathematics", "Omar")).toBe(
      "No marked Mathematics papers yet. Each paper Omar scans adds a bar here.",
    )
    expect(nothingWeakCopy("Mathematics")).toBe("Nothing stands out as a weak topic in Mathematics yet.")
  })
})
```

- [ ] **Step 2: Run to see them fail**

Run: `cd web && npx vitest run tests/unit/parentSubjectModel.test.ts`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement**

```ts
/*
 * L11 · every decision the parent subject screen makes, as pure functions.
 * The screen picks a state from `subjectState` and renders the strings and
 * numbers these return; it decides nothing itself.
 */
import { MagnifyingGlass, Scan, ChartBar } from "@phosphor-icons/react"
import { ApiError } from "@/lib/api"
import { parentLoadFailureMessage } from "@/lib/parentOutcome"
import type { PaperSeries, SubjectDetail } from "@/lib/parentTypes"
import { monthLabel, rankRows, type RankRowModel } from "./topicCopy"

export const PAPERS_FOLDED = 3
export const TOPICS_ON_SUBJECT = 4
const FLOOR = 0.4

/** "a" or "an" by the letter's spoken name (A, A*, E, F take "an"). Moved from SubjectDetail.tsx. */
export function gradeArticle(grade: string): "a" | "an" {
  return /^[AEF]/.test(grade.trim()) ? "an" : "a"
}

export interface QueryLike<T> {
  status: "pending" | "error" | "success"
  data?: T
  error?: unknown
}

export type SubjectState =
  | { kind: "loading" }
  | { kind: "error"; heading: string; body: string }
  | { kind: "first-run"; childName: string; subjectName: string }
  | { kind: "ready"; detail: SubjectDetail }

function isNoPapers(error: unknown): boolean {
  return (
    error instanceof ApiError &&
    error.status === 404 &&
    typeof error.detail === "string" &&
    error.detail.startsWith("No papers for subject")
  )
}

export function subjectState(
  q: QueryLike<SubjectDetail>,
  ctx: { childName: string; childKnown: boolean; subjectName: string },
): SubjectState {
  if (q.status === "pending") return { kind: "loading" }
  if (q.status === "error") {
    if (ctx.childKnown && isNoPapers(q.error)) {
      return { kind: "first-run", childName: ctx.childName, subjectName: ctx.subjectName }
    }
    return {
      kind: "error",
      heading: "We couldn’t load this subject",
      body: parentLoadFailureMessage(q.error),
    }
  }
  return { kind: "ready", detail: q.data as SubjectDetail }
}

export interface SummaryLine {
  predicted: string
  target: string | null
  papers: string
}

export function summaryLine(d: SubjectDetail): SummaryLine {
  const n = d.papers.length
  return { predicted: d.predictedGrade, target: d.targetGrade, papers: n === 1 ? "1 paper" : `${n} papers` }
}

export function seriesTabs(d: SubjectDetail): { paperNumber: number; label: string }[] {
  return d.series.map((s) => ({ paperNumber: s.paperNumber, label: `Paper ${s.paperNumber}` }))
}

function clampPct(value: number): number {
  return Math.min(100, Math.max(0, Math.round(value)))
}

export function barHeight(awarded: number, maximum: number, goalLine: number | null): number {
  if (maximum <= 0) return 0
  const floor = maximum * FLOOR
  if (goalLine === null || goalLine <= floor) return clampPct((awarded / maximum) * 100)
  return clampPct(((awarded - floor) / (goalLine - floor)) * 100)
}

export interface StepsModel {
  papers: { id: string; label: string; grade: string; pct: number }[]
  captions: string[]
  goal: string
  goalCaption: string | null
  toGo: number | null
  ariaLabel: string
}

export function stepsModel(series: PaperSeries, goalGrade: string): StepsModel {
  const out = series.maximumMarks
  const last = series.points.at(-1)
  const toGo =
    series.goalLine !== null && last ? Math.max(series.goalLine - last.awardedMarks, 0) : null
  const spoken = series.points
    .map((p) => `${p.grade}, ${p.awardedMarks} out of ${p.maximumMarks} in ${monthLabel(p.recordedAt)}`)
    .join("; ")
  const goalSentence =
    series.goalLine !== null ? ` ${goalGrade} line ${series.goalLine}, ${toGo} marks to go.` : ""
  return {
    papers: series.points.map((p) => ({
      id: `${p.paperId}-${p.recordedAt}`,
      label: monthLabel(p.recordedAt),
      grade: p.grade,
      pct: barHeight(p.awardedMarks, p.maximumMarks, series.goalLine),
    })),
    captions: series.points.map((p) => `${p.awardedMarks}/${p.maximumMarks}`),
    goal: goalGrade,
    goalCaption: series.goalLine !== null ? `${series.goalLine}/${out}` : null,
    toGo,
    ariaLabel: `Paper ${series.paperNumber}: ${spoken}.${goalSentence}`,
  }
}

export interface TrendLine {
  article: "a" | "an"
  grade: string
  change: string | null
}

export function trendLine(series: PaperSeries): TrendLine | null {
  const first = series.points[0]
  const last = series.points.at(-1)
  if (!first || !last) return null
  let change: string | null = null
  if (series.points.length > 1) {
    const delta = last.awardedMarks - first.awardedMarks
    const since = monthLabel(first.recordedAt)
    const marks = (n: number) => `${n} ${n === 1 ? "mark" : "marks"}`
    change =
      delta > 0
        ? `up ${marks(delta)} since ${since}`
        : delta < 0
          ? `down ${marks(-delta)} since ${since}`
          : `level since ${since}`
  }
  return { article: gradeArticle(last.grade), grade: last.grade, change }
}

export function subjectTopicRows(d: SubjectDetail, now?: Date): RankRowModel[] {
  return rankRows(d.topics, { withSubject: false, withBar: true, limit: TOPICS_ON_SUBJECT, now })
}

export interface PaperRowModel {
  key: string
  grade: string
  title: string
  sub: string
}

export function paperRows(
  d: SubjectDetail,
  expanded: boolean,
): { rows: PaperRowModel[]; moreLabel: string | null } {
  const all = d.papers.map((p) => ({
    key: `${p.paperId}-${p.recordedAt}`,
    grade: p.grade,
    title: p.paperId,
    sub: `${p.marks} · ${monthLabel(p.recordedAt)}`,
  }))
  const folded = !expanded && all.length > PAPERS_FOLDED
  return {
    rows: folded ? all.slice(0, PAPERS_FOLDED) : all,
    moreLabel: folded ? `All ${all.length}` : null,
  }
}

export function sparseBasis(subjectName: string): string {
  return `Based on the one paper they’ve had marked in ${subjectName} so far. More papers make this steadier.`
}

export function firstRunBasis(subjectName: string, childName: string): string {
  return `No marked ${subjectName} papers yet. Each paper ${childName} scans adds a bar here.`
}

export function nothingWeakCopy(subjectName: string): string {
  return `Nothing stands out as a weak topic in ${subjectName} yet.`
}

export function firstRunSteps(subjectName: string, childName: string) {
  return [
    { icon: Scan, title: `${childName} scans a ${subjectName} paper`, body: "Any past paper, from a phone." },
    { icon: MagnifyingGlass, title: "Lemely marks it", body: "Every question, in about two minutes." },
    { icon: ChartBar, title: "You see the path", body: "Grade, topics costing marks, and papers." },
  ]
}
```

Add the first-run steps to the test file's last `describe`:

```ts
  it("walks the first run in three steps", () => {
    expect(firstRunSteps("Mathematics", "Omar").map((s) => s.title)).toEqual([
      "Omar scans a Mathematics paper",
      "Lemely marks it",
      "You see the path",
    ])
  })
```

(and import `firstRunSteps`). In `web/tests/unit/parentOutcome.test.ts` change `import { gradeArticle } from "@/portals/parent/screens/SubjectDetail"` to `import { gradeArticle } from "@/portals/parent/screens/model/subjectModel"`.

- [ ] **Step 4: Run to see them pass**

Run: `cd web && npx vitest run tests/unit/parentSubjectModel.test.ts tests/unit/parentOutcome.test.ts`
Expected: PASS. (Bar heights follow `(m − 32) / (68 − 32)` for an 80-mark paper with a 68 line: 45 → 36, 48 → 44, 61 → 81.)

- [ ] **Step 5: Commit**

```bash
PYTHONPATH=$(pwd) pre-commit run --files web/src/portals/parent/screens/model/subjectModel.ts web/tests/unit/parentSubjectModel.test.ts web/tests/unit/parentOutcome.test.ts
git commit -S -m "feat(web): parent subject view model" -- web/src/portals/parent/screens/model/subjectModel.ts web/tests/unit/parentSubjectModel.test.ts web/tests/unit/parentOutcome.test.ts
```

---

### Task 10: Topics and Emails view models

**Files:**
- Create: `web/src/portals/parent/screens/model/topicsModel.ts`, `web/src/portals/parent/screens/model/emailsModel.ts`
- Test: `web/tests/unit/parentTopicsModel.test.ts`, `web/tests/unit/parentEmailsModel.test.ts`

**Interfaces:**
- Topics produces: `TOPICS_BASIS`, `topicsState(q): TopicsState`, `topicsSub(name, topics)`, `subjectFilters(topics): FilterChip[]`, `initialFilter(param, topics)`, `applyFilter(topics, code)`, `sheetModel(topic, childName, now): SheetModel`, `nothingToRank(childName)`; `TopicsState = loading | error{heading, body} | first-run{childName} | nothing-weak | ready{data}`.
- Emails produces: `WEEKLY_SUB`, `RIGHT_AWAY`, `emailsView(prefs): EmailsView`, `rowChecked(row, pending)`; `EmailsView { weekly: WeeklyGroup[] | null; rightAway: RightAwayRow[] }`, `WeeklyGroup { childId; heading; rows: WeeklyRow[] }`, `WeeklyRow { key; childId; subjectCode; label; sub; checked }`, `RightAwayRow { key: NotificationPrefKey; label; sub; checked }`.

- [ ] **Step 1: Write the failing tests**

`web/tests/unit/parentTopicsModel.test.ts`:

```ts
import { describe, expect, it } from "vitest"
import { ApiError } from "@/lib/api"
import type { ChildWeaknesses, ParentTopic } from "@/lib/parentTypes"
import {
  TOPICS_BASIS,
  applyFilter,
  initialFilter,
  nothingToRank,
  sheetModel,
  subjectFilters,
  topicsState,
  topicsSub,
} from "@/portals/parent/screens/model/topicsModel"

const NOW = new Date(2026, 10, 18, 12)
const NONE = { practisedThisWeek: 0, practiceAwarded: 0, practiceMaximum: 0, inPlanThisWeek: false, flashcardsDue: 0, assignment: null }

function t(topic: string, code: string, name: string, lost: number, over: Partial<ParentTopic> = {}): ParentTopic {
  return { subjectCode: code, subjectName: name, topic, lostMarks: lost, basisPapers: 3, trend: "same", papers: [], doing: NONE, ...over }
}

const TOPICS = [t("Vectors", "0580", "Maths", 9), t("Waves", "0625", "Physics", 6), t("Algebra", "0580", "Maths", 3)]

function data(over: Partial<ChildWeaknesses> = {}): ChildWeaknesses {
  return { childId: "c1", displayName: "Omar", paperCount: 4, weakTopics: [], topics: TOPICS, ...over }
}

describe("topicsState", () => {
  it("separates loading, error, first run, nothing weak and ready", () => {
    expect(topicsState({ status: "pending" })).toEqual({ kind: "loading" })
    expect(topicsState({ status: "error", error: new ApiError(403, "x") })).toMatchObject({
      kind: "error",
      heading: "We couldn’t load this",
    })
    expect(topicsState({ status: "success", data: data({ topics: [], paperCount: 0 }) })).toEqual({
      kind: "first-run",
      childName: "Omar",
    })
    expect(topicsState({ status: "success", data: data({ topics: [] }) })).toEqual({ kind: "nothing-weak" })
    expect(topicsState({ status: "success", data: data() }).kind).toBe("ready")
  })
})

describe("header, basis and filters", () => {
  it("counts subjects in the sub line", () => {
    expect(topicsSub("Omar", TOPICS)).toBe("Omar · 2 subjects")
    expect(topicsSub("Omar", TOPICS.slice(0, 1))).toBe("Omar · 1 subject")
    expect(TOPICS_BASIS).toBe("Ranked by marks lost on the last 3 papers. Their teachers see the same list.")
  })
  it("offers All plus each subject in rank order, only when there are two or more", () => {
    expect(subjectFilters(TOPICS)).toEqual([
      { code: "all", label: "All", tone: null },
      { code: "0580", label: "Maths", tone: "bg-grade-a" },
      { code: "0625", label: "Physics", tone: "bg-primary" },
    ])
    expect(subjectFilters([TOPICS[0], TOPICS[2]])).toEqual([])
  })
  it("starts from a valid ?subject= and filters without re-sorting", () => {
    expect(initialFilter("0625", TOPICS)).toBe("0625")
    expect(initialFilter("9709", TOPICS)).toBe("all")
    expect(initialFilter(null, TOPICS)).toBe("all")
    expect(applyFilter(TOPICS, "0580").map((x) => x.topic)).toEqual(["Vectors", "Algebra"])
    expect(applyFilter(TOPICS, "all")).toBe(TOPICS)
  })
  it("words the first run", () => {
    expect(nothingToRank("Omar")).toEqual({
      heading: "Nothing to rank yet",
      body: "Topics costing Omar marks show up here after their first marked paper.",
    })
  })
})

describe("sheetModel", () => {
  it("builds the title, basis sub, loss bars and doing list", () => {
    const vectors = t("Vectors", "0580", "Maths", 9, {
      papers: [
        { paperId: "0580/42", recordedAt: new Date(2024, 3, 9).toISOString(), lostMarks: 4 },
        { paperId: "0580/42", recordedAt: new Date(2024, 1, 9).toISOString(), lostMarks: 3 },
        { paperId: "0580/43", recordedAt: new Date(2024, 0, 9).toISOString(), lostMarks: 2 },
      ],
      doing: { ...NONE, practisedThisWeek: 2, practiceAwarded: 7, practiceMaximum: 9 },
    })
    const m = sheetModel(vectors, "Omar", NOW)
    expect(m.title).toBe("Vectors")
    expect(m.sub).toBe("Maths · −9 marks on the last 3 papers")
    expect(m.losses.map((l) => [l.label, l.lost, l.width])).toEqual([
      ["0580/42 · Apr", 4, 100],
      ["0580/42 · Feb", 3, 75],
      ["0580/43 · Jan", 2, 50],
    ])
    expect(m.doingHeading).toBe("What Omar is doing")
    expect(m.doing).toEqual([{ kind: "practice", text: "Practised twice this week · 7 of 9 back" }])
    expect(m.nothingDoing).toBe("Nothing yet")
  })
  it("words one basis paper and one mark", () => {
    const m = sheetModel(t("Waves", "0625", "Physics", 1, { basisPapers: 1 }), "Omar", NOW)
    expect(m.sub).toBe("Physics · −1 mark on the last paper")
  })
})
```

`web/tests/unit/parentEmailsModel.test.ts`:

```ts
import { describe, expect, it } from "vitest"
import type { NotificationPreferences } from "@/lib/notificationPrefs"
import { RIGHT_AWAY, WEEKLY_SUB, emailsView, rowChecked } from "@/portals/parent/screens/model/emailsModel"

function prefs(over: Partial<NotificationPreferences> = {}): NotificationPreferences {
  return {
    gradeReady: true,
    announcement: true,
    streakWarning: true,
    studyPlanReminder: true,
    atRiskAlert: false,
    reviewWithdrawn: null,
    bookingRequest: null,
    bookingUpdate: true,
    bookingNote: true,
    tutorAccess: true,
    tutorReview: null,
    tutorListing: null,
    parentLink: true,
    tutoringReport: null,
    quietHoursStart: null,
    quietHoursEnd: null,
    weeklySummaries: [
      { childId: "c1", childName: "Omar", subjectCode: "0580", subjectName: "Maths", enabled: true },
      { childId: "c1", childName: "Omar", subjectCode: "0625", subjectName: "Physics", enabled: false },
      { childId: "c2", childName: "Nour", subjectCode: "0580", subjectName: "Maths", enabled: true },
    ],
    ...over,
  }
}

describe("emailsView", () => {
  it("groups weekly switches per child in server order", () => {
    const view = emailsView(prefs())
    expect(view.weekly?.map((g) => [g.heading, g.rows.map((r) => [r.label, r.checked])])).toEqual([
      ["Weekly summary · Omar", [["Maths", true], ["Physics", false]]],
      ["Weekly summary · Nour", [["Maths", true]]],
    ])
    expect(view.weekly?.[0].rows[0]).toMatchObject({ key: "c1::0580", childId: "c1", subjectCode: "0580", sub: WEEKLY_SUB })
  })
  it("hides weekly for a role without it and keeps an empty list as empty", () => {
    expect(emailsView(prefs({ weeklySummaries: null })).weekly).toBeNull()
    expect(emailsView(prefs({ weeklySummaries: [] })).weekly).toEqual([])
  })
  it("shows only the right-away alerts this role actually has", () => {
    expect(emailsView(prefs()).rightAway).toEqual([
      { key: "atRiskAlert", label: "Something to look at", sub: "Marks falling or no work in a while", checked: false },
    ])
    expect(emailsView(prefs({ atRiskAlert: null })).rightAway).toEqual([])
    expect(RIGHT_AWAY.map((r) => r.key)).toEqual(["atRiskAlert"])
  })
})

describe("rowChecked", () => {
  it("shows the pending value while a save is in flight", () => {
    expect(rowChecked({ key: "k", checked: true }, new Map([["k", false]]))).toBe(false)
    expect(rowChecked({ key: "k", checked: true }, new Map())).toBe(true)
  })
})
```

- [ ] **Step 2: Run to see them fail**

Run: `cd web && npx vitest run tests/unit/parentTopicsModel.test.ts tests/unit/parentEmailsModel.test.ts`
Expected: FAIL (modules not found).

- [ ] **Step 3: Implement**

`web/src/portals/parent/screens/model/topicsModel.ts`:

```ts
/*
 * L11 · every decision the parent Topics screen makes. Rows stay in backend
 * order (W1); filtering only removes rows.
 */
import { parentLoadFailureMessage } from "@/lib/parentOutcome"
import type { ChildWeaknesses, ParentTopic } from "@/lib/parentTypes"
import type { QueryLike } from "./subjectModel"
import { doingLines, monthLabel, subjectTone, type DoingLine } from "./topicCopy"

export const TOPICS_BASIS =
  "Ranked by marks lost on the last 3 papers. Their teachers see the same list."

export type TopicsState =
  | { kind: "loading" }
  | { kind: "error"; heading: string; body: string }
  | { kind: "first-run"; childName: string }
  | { kind: "nothing-weak" }
  | { kind: "ready"; data: ChildWeaknesses }

export function topicsState(q: QueryLike<ChildWeaknesses>): TopicsState {
  if (q.status === "pending") return { kind: "loading" }
  if (q.status === "error") {
    return { kind: "error", heading: "We couldn’t load this", body: parentLoadFailureMessage(q.error) }
  }
  const data = q.data as ChildWeaknesses
  if (data.topics.length === 0) {
    return data.paperCount === 0 ? { kind: "first-run", childName: data.displayName } : { kind: "nothing-weak" }
  }
  return { kind: "ready", data }
}

function subjectsInOrder(topics: ParentTopic[]): { code: string; name: string }[] {
  const seen = new Map<string, string>()
  for (const t of topics) if (!seen.has(t.subjectCode)) seen.set(t.subjectCode, t.subjectName)
  return [...seen].map(([code, name]) => ({ code, name }))
}

export function topicsSub(name: string, topics: ParentTopic[]): string {
  const n = subjectsInOrder(topics).length
  return `${name} · ${n} ${n === 1 ? "subject" : "subjects"}`
}

export interface FilterChip {
  code: string
  label: string
  tone: string | null
}

export function subjectFilters(topics: ParentTopic[]): FilterChip[] {
  const subjects = subjectsInOrder(topics)
  if (subjects.length < 2) return []
  return [
    { code: "all", label: "All", tone: null },
    ...subjects.map((s, i) => ({ code: s.code, label: s.name, tone: subjectTone(i) })),
  ]
}

export function initialFilter(param: string | null, topics: ParentTopic[]): string {
  return param && topics.some((t) => t.subjectCode === param) ? param : "all"
}

export function applyFilter(topics: ParentTopic[], code: string): ParentTopic[] {
  return code === "all" ? topics : topics.filter((t) => t.subjectCode === code)
}

export function nothingToRank(childName: string): { heading: string; body: string } {
  return {
    heading: "Nothing to rank yet",
    body: `Topics costing ${childName} marks show up here after their first marked paper.`,
  }
}

export interface SheetModel {
  title: string
  sub: string
  losses: { key: string; label: string; lost: number; width: number }[]
  doingHeading: string
  doing: DoingLine[]
  nothingDoing: string
}

export function sheetModel(topic: ParentTopic, childName: string, now: Date): SheetModel {
  const top = Math.max(1, ...topic.papers.map((p) => p.lostMarks))
  const marks = topic.lostMarks === 1 ? "mark" : "marks"
  const basis = topic.basisPapers === 1 ? "the last paper" : `the last ${topic.basisPapers} papers`
  return {
    title: topic.topic,
    sub: `${topic.subjectName} · −${topic.lostMarks} ${marks} on ${basis}`,
    losses: topic.papers.map((p) => ({
      key: `${p.paperId}-${p.recordedAt}`,
      label: `${p.paperId} · ${monthLabel(p.recordedAt)}`,
      lost: p.lostMarks,
      width: Math.round((p.lostMarks / top) * 100),
    })),
    doingHeading: `What ${childName} is doing`,
    doing: doingLines(topic.doing, topic.topic, now),
    nothingDoing: "Nothing yet",
  }
}
```

The mock's TZ copy said "after his first marked paper"; the plan uses "their", because the app does not know the child's pronouns (small listed copy fix).

`web/src/portals/parent/screens/model/emailsModel.ts`:

```ts
/*
 * L11 · the Emails settings screen's decisions. Right-away rows exist only
 * for alerts the backend actually sends to a parent: today that is
 * `atRiskAlert` (see "Needs user decision" 3 in the L11 plan before adding
 * `gradeReady` or `announcement`).
 */
import type { NotificationPreferences, NotificationPrefKey } from "@/lib/notificationPrefs"

export const WEEKLY_SUB = "Sundays · grade, topics, papers"

export const RIGHT_AWAY: readonly { key: NotificationPrefKey; label: string; sub: string }[] = [
  { key: "atRiskAlert", label: "Something to look at", sub: "Marks falling or no work in a while" },
]

export interface WeeklyRow {
  key: string
  childId: string
  subjectCode: string
  label: string
  sub: string
  checked: boolean
}

export interface WeeklyGroup {
  childId: string
  heading: string
  rows: WeeklyRow[]
}

export interface RightAwayRow {
  key: NotificationPrefKey
  label: string
  sub: string
  checked: boolean
}

export interface EmailsView {
  weekly: WeeklyGroup[] | null
  rightAway: RightAwayRow[]
}

export function emailsView(prefs: NotificationPreferences): EmailsView {
  let weekly: WeeklyGroup[] | null = null
  if (prefs.weeklySummaries !== null) {
    const groups = new Map<string, WeeklyGroup>()
    for (const s of prefs.weeklySummaries) {
      const group = groups.get(s.childId) ?? {
        childId: s.childId,
        heading: `Weekly summary · ${s.childName}`,
        rows: [],
      }
      group.rows.push({
        key: `${s.childId}::${s.subjectCode}`,
        childId: s.childId,
        subjectCode: s.subjectCode,
        label: s.subjectName,
        sub: WEEKLY_SUB,
        checked: s.enabled,
      })
      groups.set(s.childId, group)
    }
    weekly = [...groups.values()]
  }
  const rightAway = RIGHT_AWAY.flatMap((r) => {
    const value = prefs[r.key]
    return value === null ? [] : [{ ...r, checked: value }]
  })
  return { weekly, rightAway }
}

export function rowChecked(row: { key: string; checked: boolean }, pending: ReadonlyMap<string, boolean>): boolean {
  return pending.get(row.key) ?? row.checked
}
```

- [ ] **Step 4: Run to see them pass**

Run: `cd web && npx vitest run tests/unit/parentTopicsModel.test.ts tests/unit/parentEmailsModel.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
PYTHONPATH=$(pwd) pre-commit run --files web/src/portals/parent/screens/model/topicsModel.ts web/src/portals/parent/screens/model/emailsModel.ts web/tests/unit/parentTopicsModel.test.ts web/tests/unit/parentEmailsModel.test.ts
git commit -S -m "feat(web): parent topics and emails view models" -- web/src/portals/parent/screens/model/topicsModel.ts web/src/portals/parent/screens/model/emailsModel.ts web/tests/unit/parentTopicsModel.test.ts web/tests/unit/parentEmailsModel.test.ts
```

---

### Task 11: Subject screen (designer)

**Agent:** `designer`. Invoke the impeccable skill and read `.claude/skills/impeccable/reference/craft-floor.md` first. Read the taste memories listed in the master plan. Open `.impeccable/mocks/student-r2/parent-final.html` in a browser beside the app.

**Files:**
- Create: `web/src/portals/parent/screens/shared/ParentPageHead.tsx`, `shared/SubjectDot.tsx`, `shared/LoadError.tsx`
- Create: `web/src/portals/parent/screens/subject/SubjectSummary.tsx`, `PaperToggle.tsx`, `MarksPerPaper.tsx`, `TopicsCosting.tsx`, `PapersDone.tsx`, `SubjectStates.tsx`
- Rewrite: `web/src/portals/parent/screens/SubjectDetail.tsx` (keeps the `SubjectDetail` named export the route imports)

**Interfaces:**
- Consumes: Task 9 model; Task 8 `RankRowModel`; F1 `StepsPath`, `RankRow`, `H2Row`, `HairRows`, `HairRow`, `Walkthrough`, `GhostRows` from `@/components/redesign`; `useChildSubject`, `useChildren`, `useReference`, `subjectIdentifier`; `SkeletonBlock`; `Button`.
- Produces: `ParentPageHead({ title, sub, trailing? })`, `SubjectDot({ tone })`, `LoadError({ heading, body, onRetry, extra? })` reused by Tasks 12–13.

Component tree:

```
SubjectDetail
├─ ParentPageHead (h1 subject name, sub "IGCSE · 0580")   [message icon: see Needs user decision 1]
└─ state switch
   ├─ loading   → SubjectLoading (FL1)
   ├─ error     → LoadError + "All subjects" link (FE1)
   ├─ first-run → SubjectFirstRun (FZ1)
   └─ ready     → div.xl:grid two columns (FDK)
       ├─ left:  SubjectSummary (tgt) + MarksPerPaper (PaperToggle, StepsPath, trend line or sparse basis)
       └─ right: TopicsCosting (RankRow ×≤4 with bars, or FN1 copy) + PapersDone
```

- [ ] **Step 1: Shared parts**

`shared/ParentPageHead.tsx`:

```tsx
import type { ReactNode } from "react"

/** The mock's `.sjhd` / desktop `.dtop` head: title, quiet sub line, optional trailing control. */
export function ParentPageHead({ title, sub, trailing }: { title: string; sub?: string; trailing?: ReactNode }) {
  return (
    <header className="flex items-center gap-2.5 pt-3.5 pb-1.5 xl:gap-5 xl:pt-6 xl:pb-2">
      <div className="grid min-w-0 flex-1">
        <h1 className="font-display text-[28px] leading-[1.1] font-extrabold tracking-[-0.03em] text-primary">
          {title}
        </h1>
        {sub ? <span className="text-[13px] font-medium text-on-surface-variant">{sub}</span> : null}
      </div>
      {trailing}
    </header>
  )
}
```

`shared/SubjectDot.tsx`:

```tsx
import { cn } from "@/lib/utils"

export function SubjectDot({ tone, className }: { tone: string; className?: string }) {
  return <i aria-hidden="true" className={cn("inline-block size-2 flex-none rounded-full", tone, className)} />
}
```

`shared/LoadError.tsx`:

```tsx
import type { ReactNode } from "react"
import { Button } from "@/components/ui/button"

/** The mock's `.err2` block: FE1 and TE. */
export function LoadError({
  heading,
  body,
  onRetry,
  extra,
}: {
  heading: string
  body: string
  onRetry: () => void
  extra?: ReactNode
}) {
  return (
    <div role="alert" className="flex flex-1 flex-col items-center justify-center gap-3 px-2 py-6 text-center">
      <h2 className="mt-1.5 font-display text-[28px] leading-[1.15] font-extrabold tracking-[-0.02em] text-balance text-primary">
        {heading}
      </h2>
      <p className="mb-1.5 max-w-[30ch] text-[15px] leading-[1.4] font-medium text-on-surface-variant">{body}</p>
      <Button variant="primary" className="min-h-[50px] w-full max-w-[300px] rounded-[18px] text-[15.5px]" onClick={onRetry}>
        Try again
      </Button>
      {extra}
    </div>
  )
}
```

- [ ] **Step 2: Subject sections**

`subject/SubjectSummary.tsx`:

```tsx
import type { SummaryLine } from "../model/subjectModel"
import { gradeTextClass } from "./gradeTone"

export function SubjectSummary({ line }: { line: SummaryLine }) {
  const parts = [
    <span key="p">
      Predicted <b className={`ms-1 font-display text-[18px] font-extrabold ${gradeTextClass(line.predicted)}`}>{line.predicted}</b>
    </span>,
    line.target ? (
      <span key="t">
        Target <b className={`ms-1 font-display text-[18px] font-extrabold ${gradeTextClass(line.target)}`}>{line.target}</b>
      </span>
    ) : null,
    <span key="n">{line.papers}</span>,
  ].filter(Boolean)
  return (
    <p className="m-0 flex flex-wrap items-baseline gap-x-4 gap-y-1 text-[14px] font-medium text-on-surface-variant">
      {parts.map((part, i) => (
        <span key={i} className="inline-flex items-baseline">
          {i > 0 ? <span aria-hidden="true" className="me-4 text-outline">·</span> : null}
          {part}
        </span>
      ))}
    </p>
  )
}
```

Add `subject/gradeTone.ts` (part of this task's files):

```ts
const TEXT: Record<string, string> = {
  "A*": "text-grade-a-star",
  A: "text-grade-a",
  B: "text-grade-b",
  C: "text-grade-c-shell",
  D: "text-grade-d",
  E: "text-grade-e",
  F: "text-grade-f",
  G: "text-grade-g",
  U: "text-grade-u",
}

/** Grade letter colour. C uses the darker shell tone for text contrast, as the live grade badge does. */
export function gradeTextClass(grade: string): string {
  return TEXT[grade] ?? "text-on-surface-variant"
}
```

`subject/PaperToggle.tsx`:

```tsx
export function PaperToggle({
  tabs,
  value,
  onChange,
}: {
  tabs: { paperNumber: number; label: string }[]
  value: number
  onChange: (paperNumber: number) => void
}) {
  if (tabs.length < 2) return null
  return (
    <div role="tablist" aria-label="Choose a paper" className="inline-flex gap-0.5 rounded-xl bg-surface-container-high p-[3px]">
      {tabs.map((tab) => {
        const selected = tab.paperNumber === value
        return (
          <button
            key={tab.paperNumber}
            type="button"
            role="tab"
            aria-selected={selected}
            onClick={() => onChange(tab.paperNumber)}
            className={
              "relative min-h-9 cursor-pointer rounded-[9px] border-0 px-3 text-[13px] font-semibold before:absolute before:inset-x-0 before:-inset-y-1 before:content-[''] focus-visible:outline-[2.5px] focus-visible:outline-offset-2 focus-visible:outline-primary " +
              (selected
                ? "bg-surface-container-lowest text-primary shadow-[0_1px_3px_oklch(0.3_0.05_240/0.18)]"
                : "bg-transparent text-on-surface-variant")
            }
          >
            {tab.label}
          </button>
        )
      })}
    </div>
  )
}
```

`subject/MarksPerPaper.tsx`:

```tsx
import { useState } from "react"
import { H2Row, StepsPath } from "@/components/redesign"
import type { SubjectDetail } from "@/lib/parentTypes"
import { seriesTabs, sparseBasis, stepsModel, trendLine } from "../model/subjectModel"
import { gradeTextClass } from "./gradeTone"
import { PaperToggle } from "./PaperToggle"

export function MarksPerPaper({ detail, subjectName }: { detail: SubjectDetail; subjectName: string }) {
  const tabs = seriesTabs(detail)
  const [paper, setPaper] = useState(tabs[0]?.paperNumber ?? 0)
  const series = detail.series.find((s) => s.paperNumber === paper) ?? detail.series[0]
  if (!series) return null
  const steps = stepsModel(series, detail.goalGrade)
  const trend = trendLine(series)
  const sparse = detail.papers.length === 1

  return (
    <section className="grid gap-2.5" aria-labelledby="marks-per-paper">
      <H2Row title="Marks per paper" />
      {/* H2Row renders the h2; the toggle sits on the same row on the right. If F1's H2Row has no
          trailing slot, wrap: <div className="flex items-center justify-between gap-2.5"><H2Row …/><PaperToggle …/></div> */}
      <div className="flex justify-end">
        <PaperToggle tabs={tabs} value={series.paperNumber} onChange={setPaper} />
      </div>
      <div role="group" aria-label={steps.ariaLabel}>
        <StepsPath key={series.paperNumber} papers={steps.papers} goal={steps.goal} />
      </div>
      {sparse ? (
        <p className="mt-1 text-[13.5px] leading-[1.4] font-medium text-on-surface-variant">{sparseBasis(subjectName)}</p>
      ) : trend ? (
        <p className="m-0 text-[14px] font-medium text-on-surface-variant">
          Heading for {trend.article}{" "}
          <b className={gradeTextClass(trend.grade)}>{trend.grade}</b>
          {trend.change ? ` · ${trend.change}` : null}
        </p>
      ) : null}
    </section>
  )
}
```

The mock shows marks (`61/80`) and the goal caption (`68/80 A* line`, `7 to go`) under the bars. Those come from `steps.captions`, `steps.goalCaption` and `steps.toGo`. Pass them through F1's `StepsPath` optional props if F1 provides them (see "Dependencies on other lanes"); if F1 does not, raise it with F1 rather than drawing a second baseline here.

`subject/TopicsCosting.tsx`:

```tsx
import { useNavigate } from "react-router-dom"
import { H2Row, RankRow } from "@/components/redesign"
import type { RankRowModel } from "../model/topicCopy"
import { parentTopicsPath } from "../model/parentPaths"

export function TopicsCosting({
  rows,
  childId,
  subjectCode,
  emptyCopy,
}: {
  rows: RankRowModel[]
  childId: string
  subjectCode: string
  emptyCopy: string
}) {
  const navigate = useNavigate()
  const allTopics = parentTopicsPath(childId, subjectCode)
  return (
    <section className="grid" aria-labelledby="topics-costing">
      <H2Row
        title="Topics costing marks"
        link={rows.length > 0 ? { label: "All topics", to: allTopics } : undefined}
      />
      {rows.length === 0 ? (
        <p className="py-3 text-[13.5px] leading-[1.4] font-medium text-on-surface-variant">{emptyCopy}</p>
      ) : (
        <ol className="m-0 list-none p-0" aria-label="Topics costing marks">
          {rows.map((row) => (
            <li key={row.key}>
              <RankRow
                rank={row.rank}
                title={row.title}
                sub={row.sub}
                marksLost={row.marksLost}
                trend={row.trend}
                assigned={row.assigned}
                bar={row.bar}
                onClick={() => navigate(`${allTopics}&topic=${encodeURIComponent(row.topic)}`)}
              />
            </li>
          ))}
        </ol>
      )}
    </section>
  )
}
```

`subject/PapersDone.tsx`:

```tsx
import { useState } from "react"
import { H2Row, HairRow, HairRows } from "@/components/redesign"
import type { SubjectDetail } from "@/lib/parentTypes"
import { paperRows } from "../model/subjectModel"
import { gradeTextClass } from "./gradeTone"

export function PapersDone({ detail }: { detail: SubjectDetail }) {
  const [expanded, setExpanded] = useState(false)
  const { rows, moreLabel } = paperRows(detail, expanded)
  return (
    <section className="grid" aria-labelledby="papers-done">
      <H2Row
        title="Papers they’ve done"
        link={moreLabel ? { label: moreLabel, onClick: () => setExpanded(true) } : undefined}
      />
      <HairRows aria-label="Papers they’ve done">
        {rows.map((row) => (
          <HairRow
            key={row.key}
            leading={
              <b className={`block w-9 text-center font-display text-[28px] leading-none font-extrabold ${gradeTextClass(row.grade)}`}>
                {row.grade}
              </b>
            }
            title={row.title}
            sub={<span className="font-mono">{row.sub}</span>}
          />
        ))}
      </HairRows>
    </section>
  )
}
```

Paper rows are not links (live rows were not either, and parents have no paper result screen yet; see Needs user decision 2). The mock's chevron is left off.

`subject/SubjectStates.tsx`:

```tsx
import { GhostRows, Walkthrough } from "@/components/redesign"
import { SkeletonBlock } from "@/components/ui/skeleton"
import { firstRunBasis, firstRunSteps } from "../model/subjectModel"

export function SubjectLoading({ label }: { label: string }) {
  return (
    <div className="grid gap-3.5" aria-busy="true" aria-label={`Loading ${label}`}>
      <SkeletonBlock className="h-[22px] w-[150px]" />
      <div className="grid h-[108px] grid-cols-5 items-end gap-2">
        {[38, 50, 56, 84, 100].map((h) => (
          <SkeletonBlock key={h} className="rounded-[14px_14px_4px_4px]" style={{ height: `${h}%` }} />
        ))}
      </div>
      <SkeletonBlock className="h-[54px] rounded-[18px]" />
      <GhostRows rows={3} />
    </div>
  )
}

export function SubjectFirstRun({ childName, subjectName }: { childName: string; subjectName: string }) {
  return (
    <div className="grid gap-6">
      <p className="m-0 flex flex-wrap gap-x-4 text-[14px] font-medium text-on-surface-variant">
        <span>
          Predicted <b className="ms-1 font-display text-[18px] font-extrabold text-on-surface-variant">–</b>
        </span>
        <span>
          <span aria-hidden="true" className="me-4 text-outline">·</span>No papers yet
        </span>
      </p>
      <section className="grid gap-2.5">
        <h2 className="m-0 text-[18px] font-extrabold tracking-[-0.01em] text-on-surface">Marks per paper</h2>
        <div aria-hidden="true" className="grid h-[108px] grid-cols-5 items-end gap-2 border-b-2 border-outline-variant">
          {[30, 45, 52, 70].map((h) => (
            <span key={h} className="mx-auto w-[min(100%,64px)] rounded-[14px_14px_4px_4px] shadow-[inset_0_0_0_2px_var(--color-outline-variant)]" style={{ height: `${h}%` }} />
          ))}
          <span className="mx-auto flex h-full w-[min(100%,64px)] flex-col items-center rounded-[14px_14px_4px_4px] bg-[color-mix(in_oklch,var(--color-grade-a-star)_10%,white)] pt-2 shadow-[inset_0_0_0_2px_color-mix(in_oklch,var(--color-grade-a-star)_40%,white)]">
            <b className="font-display text-[22px] leading-none font-extrabold text-grade-a-star">A*</b>
          </span>
        </div>
        <p className="mt-1 text-[13.5px] leading-[1.4] font-medium text-on-surface-variant">
          {firstRunBasis(subjectName, childName)}
        </p>
      </section>
      <Walkthrough steps={firstRunSteps(subjectName, childName)} />
    </div>
  )
}
```

The ghost path's goal tint uses `color-mix` on the existing `grade-a-star` token (the mock's `--gat`/`--gal` are not tokens). If F1's `StepsPath` offers a ghost mode, use it instead and delete this block.

- [ ] **Step 3: The screen**

`web/src/portals/parent/screens/SubjectDetail.tsx`:

```tsx
/*
 * L11 · Parent subject (SB, `.impeccable/mocks/student-r2/parent-final.html`
 * frames FA, FS1, FZ1, FN1, FL1, FE1, FDK). Read-only: no mutation exists for
 * any parent route. Every decision lives in `model/subjectModel.ts`.
 */
import { Link, useParams } from "react-router-dom"
import { useChildSubject, useChildren } from "@/lib/hooks/useParentApi"
import { useReference } from "@/lib/hooks/useReferenceApi"
import { subjectIdentifier } from "@/lib/subjectIdentifier"
import { parentOverviewPath } from "./model/parentPaths"
import { nothingWeakCopy, subjectState, subjectTopicRows, summaryLine } from "./model/subjectModel"
import { LoadError } from "./shared/LoadError"
import { ParentPageHead } from "./shared/ParentPageHead"
import { MarksPerPaper } from "./subject/MarksPerPaper"
import { PapersDone } from "./subject/PapersDone"
import { SubjectFirstRun, SubjectLoading } from "./subject/SubjectStates"
import { SubjectSummary } from "./subject/SubjectSummary"
import { TopicsCosting } from "./subject/TopicsCosting"

export function SubjectDetail() {
  const { childId = "", code = "" } = useParams<{ childId: string; code: string }>()
  const query = useChildSubject(childId, code)
  const { data: children } = useChildren()
  const { data: reference } = useReference()
  const child = children?.children.find((c) => c.childId === childId)

  const ident = subjectIdentifier(
    reference?.qualificationLevels,
    query.data?.subjectName ?? code,
    code,
    query.data?.qualificationLevel ?? null,
  )
  const state = subjectState(query, {
    childName: child?.displayName ?? "Your child",
    childKnown: child !== undefined,
    subjectName: ident.primary,
  })

  return (
    <div className="mx-auto flex w-full max-w-[640px] flex-col gap-6 xl:max-w-none">
      <ParentPageHead title={ident.primary} sub={ident.secondary || undefined} />
      {state.kind === "loading" ? <SubjectLoading label={ident.primary} /> : null}
      {state.kind === "error" ? (
        <>
          <h1 className="sr-only">Subject {code}</h1>
          <LoadError
            heading={state.heading}
            body={state.body}
            onRetry={() => void query.refetch()}
            extra={
              <Link to={parentOverviewPath(childId)} className="inline-flex min-h-11 items-center px-3.5 text-[14px] font-semibold text-on-surface-variant">
                All subjects
              </Link>
            }
          />
        </>
      ) : null}
      {state.kind === "first-run" ? (
        <SubjectFirstRun childName={state.childName} subjectName={state.subjectName} />
      ) : null}
      {state.kind === "ready" ? (
        <div className="flex flex-col gap-6 xl:grid xl:grid-cols-[minmax(0,1.05fr)_minmax(0,1fr)] xl:items-start xl:gap-12">
          <div className="flex flex-col gap-6">
            <SubjectSummary line={summaryLine(state.detail)} />
            <MarksPerPaper detail={state.detail} subjectName={ident.primary} />
          </div>
          <div className="flex flex-col gap-6">
            <TopicsCosting
              rows={subjectTopicRows(state.detail)}
              childId={childId}
              subjectCode={code}
              emptyCopy={nothingWeakCopy(ident.primary)}
            />
            <PapersDone detail={state.detail} />
          </div>
        </div>
      ) : null}
    </div>
  )
}
```

The page heading is rendered in content because the mock puts it there; if F1's parent shell already shows the route title as a large title on this route, keep this head and set the route `handle.title` so the shell's collapsed title matches (shell wins on chrome).

- [ ] **Step 4: Verify**

Run: `cd web && npx tsc -b --noEmit && npx oxlint src/portals/parent/screens && npm run check:copy && npm run check:native && npx vitest run tests/unit/parentSubjectModel.test.ts tests/unit/parentTopicCopy.test.ts tests/unit/parentOutcome.test.ts`
Expected: clean. Then run the app (`npm run dev` with the seeded stack), sign in as the e2e parent, open a subject at 390, 768 and 1280, and check FA, FL1 (throttle), FE1 (block `/api/parent/*` in devtools), FN1 (seed child has no weak areas) against the mock.

- [ ] **Step 5: Commit**

```bash
PYTHONPATH=$(pwd) pre-commit run --files web/src/portals/parent/screens/SubjectDetail.tsx web/src/portals/parent/screens/shared/*.tsx web/src/portals/parent/screens/subject/*
git commit -S -m "feat(web): redesigned parent subject screen" -- web/src/portals/parent/screens/SubjectDetail.tsx web/src/portals/parent/screens/shared web/src/portals/parent/screens/subject
```

---

### Task 12: Topics screen with sheet and side panel (designer)

**Agent:** `designer` (impeccable skill, craft floor first).

**Files:**
- Rewrite: `web/src/portals/parent/screens/Weaknesses.tsx` (keeps the `Weaknesses` named export F1's Topics route renders)
- Create: `web/src/portals/parent/screens/topics/useWideLayout.ts`, `SubjectFilter.tsx`, `TopicList.tsx`, `TopicDetail.tsx`, `TopicsStates.tsx`

**Interfaces:**
- Consumes: Task 10 topics model, Task 8 `rankRows`/`topicKey`/`DoingLine`, `useChildWeaknesses`, F1 `RankRow`, `GhostRows`, `Sheet`/`SheetContent`/`SheetTitle`/`SheetDescription` from `@/components/ui/sheet`, shared parts from Task 11.
- URL state: `?subject=<code>` (filter) and `?topic=<name>` (open sheet / selected row). Both replace history entries (`setSearchParams(…, { replace: true })`) except opening the sheet, which pushes so the device back button closes it.

Component tree:

```
Weaknesses
├─ ParentPageHead ("Topics to work on", "Omar · 3 subjects", trailing: SubjectFilter on xl)
└─ state switch
   ├─ loading      → GhostRows rows=5 (aria-busy)
   ├─ error        → LoadError (TE)
   ├─ first-run    → TopicsFirstRun (TZ)
   ├─ nothing-weak → live W6 copy
   └─ ready
       ├─ < xl: SubjectFilter, basis, TopicList (tap → Sheet with TopicDetail) (WA, WS)
       └─ ≥ xl: grid [list | aside.sside TopicDetail] (TDK), first row selected by default
```

- [ ] **Step 1: Parts**

`topics/useWideLayout.ts`:

```ts
import { useSyncExternalStore } from "react"

const QUERY = "(min-width: 1280px)"

function subscribe(onChange: () => void): () => void {
  const mql = window.matchMedia(QUERY)
  mql.addEventListener("change", onChange)
  return () => mql.removeEventListener("change", onChange)
}

/** True at the rail breakpoint, where Topics shows a side panel instead of a sheet. */
export function useWideLayout(): boolean {
  return useSyncExternalStore(subscribe, () => window.matchMedia(QUERY).matches, () => false)
}
```

`topics/SubjectFilter.tsx`:

```tsx
import type { FilterChip } from "../model/topicsModel"
import { SubjectDot } from "../shared/SubjectDot"

export function SubjectFilter({
  chips,
  value,
  onChange,
}: {
  chips: FilterChip[]
  value: string
  onChange: (code: string) => void
}) {
  if (chips.length === 0) return null
  return (
    <div role="tablist" aria-label="Subject" className="-mx-[18px] flex flex-none gap-1.5 overflow-x-auto px-[18px] [scrollbar-width:none] xl:mx-0 xl:px-0">
      {chips.map((chip) => {
        const selected = chip.code === value
        return (
          <button
            key={chip.code}
            type="button"
            role="tab"
            aria-selected={selected}
            onClick={() => onChange(chip.code)}
            className={
              "relative inline-flex min-h-10 flex-none cursor-pointer items-center gap-1.5 rounded-xl border-0 px-3.5 text-[13.5px] font-semibold before:absolute before:inset-x-0 before:-inset-y-0.5 before:content-[''] focus-visible:outline-[2.5px] focus-visible:outline-offset-2 focus-visible:outline-primary " +
              (selected
                ? "bg-primary text-on-primary"
                : "bg-surface-container-lowest text-on-surface shadow-[inset_0_0_0_1.5px_var(--color-outline-variant)]")
            }
          >
            {chip.tone ? <SubjectDot tone={chip.tone} /> : null}
            {chip.label}
          </button>
        )
      })}
    </div>
  )
}
```

`topics/TopicList.tsx`:

```tsx
import { RankRow } from "@/components/redesign"
import type { RankRowModel } from "../model/topicCopy"

export function TopicList({
  rows,
  selectedKey,
  onSelect,
}: {
  rows: RankRowModel[]
  selectedKey: string | null
  onSelect: (row: RankRowModel) => void
}) {
  return (
    <ol className="m-0 grid list-none p-0" aria-label="Topics to work on">
      {rows.map((row) => (
        <li key={row.key}>
          <RankRow
            rank={row.rank}
            title={row.title}
            sub={row.sub}
            marksLost={row.marksLost}
            trend={row.trend}
            assigned={row.assigned}
            selected={row.key === selectedKey}
            onClick={() => onSelect(row)}
          />
        </li>
      ))}
    </ol>
  )
}
```

`topics/TopicDetail.tsx`:

```tsx
import { Check } from "@phosphor-icons/react"
import type { SheetModel } from "../model/topicsModel"

/** The sheet body (WS) and the desktop side panel (TDK) share this. */
export function TopicDetail({ model, titleAs: Title = "h2" }: { model: SheetModel; titleAs?: "h2" | "span" }) {
  return (
    <div className="flex flex-col gap-3.5">
      <div>
        <Title className="m-0 font-display text-[24px] leading-[1.15] font-extrabold tracking-[-0.02em] text-primary">
          {model.title}
        </Title>
        <span className="inline-flex items-center gap-1.5 text-[13px] font-medium text-on-surface-variant">{model.sub}</span>
      </div>
      <ul className="m-0 grid list-none gap-2 p-0" aria-label="Marks lost per paper">
        {model.losses.map((loss) => (
          <li key={loss.key} className="grid grid-cols-[120px_minmax(0,1fr)_36px] items-center gap-2.5 text-[13px] font-medium text-on-surface-variant">
            <span>{loss.label}</span>
            <i aria-hidden="true" className="h-2 rounded bg-[color-mix(in_oklch,var(--color-on-error-container),white_55%)]" style={{ width: `${loss.width}%` }} />
            <b className="text-right font-mono text-[14px] font-bold text-on-error-container">−{loss.lost}</b>
          </li>
        ))}
      </ul>
      <h3 className="m-0 text-[18px] font-extrabold tracking-[-0.01em] text-on-surface">{model.doingHeading}</h3>
      <ul className="m-0 grid list-none gap-2 p-0 text-[14px] leading-[1.4] font-medium text-on-surface">
        {model.doing.length === 0 ? <li className="text-on-surface-variant">{model.nothingDoing}</li> : null}
        {model.doing.map((line) => (
          <li key={line.kind} className="flex items-center gap-2">
            {line.kind === "assigned" ? (
              <em className="rounded-md bg-primary-container px-1.5 py-[3px] text-[12px] leading-none font-bold whitespace-nowrap text-primary not-italic">
                Assigned
              </em>
            ) : (
              <Check size={16} weight="bold" aria-hidden="true" className="flex-none text-success-text" />
            )}
            {line.text}
          </li>
        ))}
      </ul>
    </div>
  )
}
```

The mock's tick is a drawn 16px path (`M3.5 8.3 6.5 11l6-6.5`, stroke 2.2). Phosphor `Check` bold is the codebase's equivalent; the designer may swap in the drawn path if the side-by-side shows a visible difference.

`topics/TopicsStates.tsx`:

```tsx
import { GhostRows } from "@/components/redesign"
import { nothingToRank } from "../model/topicsModel"

export function TopicsFirstRun({ childName }: { childName: string }) {
  const copy = nothingToRank(childName)
  return (
    <div className="grid gap-4">
      <div className="flex flex-col items-center gap-3 px-2 pt-5 text-center">
        <h2 className="mt-1.5 font-display text-[28px] leading-[1.15] font-extrabold tracking-[-0.02em] text-balance text-primary">
          {copy.heading}
        </h2>
        <p className="max-w-[30ch] text-[15px] leading-[1.4] font-medium text-on-surface-variant">{copy.body}</p>
      </div>
      <div aria-hidden="true" className="opacity-50">
        <GhostRows rows={3} withLeading />
      </div>
    </div>
  )
}

export function TopicsNothingWeak() {
  return (
    <p className="py-3 text-[15px] leading-[1.4] font-medium text-on-surface-variant">
      Nothing stands out yet. Weak topics appear here once a few papers have been marked.
    </p>
  )
}
```

- [ ] **Step 2: The screen**

`web/src/portals/parent/screens/Weaknesses.tsx`:

```tsx
/*
 * L11 · Parent "Topics to work on" (SB frames WA, WS, TZ, TE, TDK). One ranked
 * list across subjects, in backend order (W1), filtered by subject chips. Tap
 * a row: a sheet below 1280px, the side panel at 1280px and above.
 */
import { useMemo } from "react"
import { useParams, useSearchParams } from "react-router-dom"
import { GhostRows } from "@/components/redesign"
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet"
import { useChildWeaknesses } from "@/lib/hooks/useParentApi"
import { rankRows, topicKey } from "./model/topicCopy"
import {
  TOPICS_BASIS,
  applyFilter,
  initialFilter,
  sheetModel,
  subjectFilters,
  topicsState,
  topicsSub,
} from "./model/topicsModel"
import { LoadError } from "./shared/LoadError"
import { ParentPageHead } from "./shared/ParentPageHead"
import { SubjectFilter } from "./topics/SubjectFilter"
import { TopicDetail } from "./topics/TopicDetail"
import { TopicList } from "./topics/TopicList"
import { TopicsFirstRun, TopicsNothingWeak } from "./topics/TopicsStates"
import { useWideLayout } from "./topics/useWideLayout"

export function Weaknesses() {
  const { childId = "" } = useParams<{ childId: string }>()
  const query = useChildWeaknesses(childId)
  const [params, setParams] = useSearchParams()
  const wide = useWideLayout()
  const state = topicsState(query)
  const now = useMemo(() => new Date(), [])

  const topics = state.kind === "ready" ? state.data.topics : []
  const childName = state.kind === "ready" ? state.data.displayName : ""
  const chips = subjectFilters(topics)
  const filter = initialFilter(params.get("subject"), topics)
  const visible = applyFilter(topics, filter)
  const rows = rankRows(visible, { withSubject: true, withBar: false, now })
  const requested = params.get("topic")
  const openTopic =
    visible.find((t) => t.topic === requested) ?? (wide ? visible[0] : undefined)

  const setFilter = (code: string) => {
    const next = new URLSearchParams(params)
    if (code === "all") next.delete("subject")
    else next.set("subject", code)
    next.delete("topic")
    setParams(next, { replace: true })
  }
  const select = (topic: string | null) => {
    const next = new URLSearchParams(params)
    if (topic === null) next.delete("topic")
    else next.set("topic", topic)
    setParams(next, { replace: wide || topic === null })
  }

  const filterRow = <SubjectFilter chips={chips} value={filter} onChange={setFilter} />

  return (
    <div className="mx-auto flex w-full max-w-[640px] flex-col gap-6 xl:max-w-none">
      <ParentPageHead
        title="Topics to work on"
        sub={state.kind === "ready" ? topicsSub(childName, topics) : undefined}
        trailing={wide ? <div className="ms-auto">{filterRow}</div> : undefined}
      />
      {state.kind === "loading" ? (
        <div aria-busy="true" aria-label="Loading topics">
          <h1 className="sr-only">Topics to work on</h1>
          <GhostRows rows={5} withLeading />
        </div>
      ) : null}
      {state.kind === "error" ? (
        <LoadError heading={state.heading} body={state.body} onRetry={() => void query.refetch()} />
      ) : null}
      {state.kind === "first-run" ? <TopicsFirstRun childName={state.childName} /> : null}
      {state.kind === "nothing-weak" ? <TopicsNothingWeak /> : null}
      {state.kind === "ready" ? (
        <div className="flex flex-col gap-6 xl:grid xl:grid-cols-[minmax(0,1fr)_320px] xl:gap-6">
          <div className="flex min-h-0 flex-col gap-5">
            {wide ? null : filterRow}
            <p className="mt-1 text-[13.5px] leading-[1.4] font-medium text-on-surface-variant">{TOPICS_BASIS}</p>
            <TopicList
              rows={rows}
              selectedKey={wide && openTopic ? topicKey(openTopic) : null}
              onSelect={(row) => select(row.topic)}
            />
          </div>
          {wide && openTopic ? (
            <aside className="flex flex-col gap-3.5 self-start rounded-[22px] bg-surface-container-lowest p-5 shadow-[0_1px_3px_oklch(0.3_0.05_240/0.1)]" aria-label={openTopic.topic}>
              <TopicDetail model={sheetModel(openTopic, childName, now)} />
            </aside>
          ) : null}
        </div>
      ) : null}
      {!wide && openTopic ? (
        <Sheet open onOpenChange={(open) => (open ? undefined : select(null))}>
          <SheetContent side="adaptive" className="rounded-t-[28px] px-5 pt-[22px] pb-[26px]">
            <SheetTitle className="sr-only">{openTopic.topic}</SheetTitle>
            <SheetDescription className="sr-only">{sheetModel(openTopic, childName, now).sub}</SheetDescription>
            <TopicDetail model={sheetModel(openTopic, childName, now)} titleAs="span" />
          </SheetContent>
        </Sheet>
      ) : null}
    </div>
  )
}
```

Closing the sheet on phone uses the shell sheet's swipe, scrim tap and Escape, all of which call `onOpenChange(false)`; the device back button pops the pushed `?topic=` entry.

- [ ] **Step 3: Verify**

Run: `cd web && npx tsc -b --noEmit && npx oxlint src/portals/parent/screens && npm run check:copy && npm run check:native && npx vitest run tests/unit/parentTopicsModel.test.ts tests/unit/parentTopicCopy.test.ts`
Expected: clean. In the browser: 390 (sheet, back button closes it), 768 (sheet), 1280 (panel, first row selected, chip in the head), keyboard (Tab to a row, Enter opens, Escape closes and focus returns to the row), reduced motion (sheet appears without the rise).

- [ ] **Step 4: Commit**

```bash
PYTHONPATH=$(pwd) pre-commit run --files web/src/portals/parent/screens/Weaknesses.tsx web/src/portals/parent/screens/topics/*
git commit -S -m "feat(web): redesigned parent topics screen with sheet and side panel" -- web/src/portals/parent/screens/Weaknesses.tsx web/src/portals/parent/screens/topics
```

---

### Task 13: Emails settings screen and routes (designer)

**Agent:** `designer`.

**Files:**
- Create: `web/src/portals/parent/screens/Emails.tsx`, `web/src/portals/parent/screens/emails/EmailRow.tsx`
- Modify: `web/src/portals/parent/index.tsx` (one lazy import, one route entry for `emails`; confirm the Topics route renders `Weaknesses`; add one account-menu entry "Emails" pointing at `PARENT_EMAILS_PATH` in F1's parent account menu or child switcher)

**Interfaces:**
- Consumes: Task 10 emails model; `useNotificationPreferences`, `useUpdateNotificationPreferences`; `weeklySummaryUpdate`; `settingsSaveFailureMessage`, `settingsLoadFailureMessage` (`web/src/lib/settingsOutcome.ts`); `useProfile`; `Switch`; `SkeletonBlock`; shared parts.

- [ ] **Step 1: Row**

`emails/EmailRow.tsx`:

```tsx
import type { ReactNode } from "react"
import { Switch } from "@/components/ui/switch"

/** The mock's `.emr`: icon tile, label and sub, switch. One switch saves as it is pressed. */
export function EmailRow({
  icon,
  label,
  sub,
  checked,
  onChange,
  error,
  busy,
}: {
  icon: ReactNode
  label: ReactNode
  sub: string
  checked: boolean
  onChange: (next: boolean) => void
  error: string | null
  busy: boolean
}) {
  return (
    <li className="grid min-h-16 grid-cols-[40px_minmax(0,1fr)_auto] items-center gap-3 py-3 shadow-[0_-1px_0_var(--color-outline-variant)]">
      <span aria-hidden="true" className="grid size-10 place-items-center rounded-[13px] bg-primary-container text-primary">
        {icon}
      </span>
      <span className="grid min-w-0">
        <b className="text-[15px] font-bold text-on-surface">{label}</b>
        <span className="text-[13px] font-medium text-on-surface-variant">{sub}</span>
        {error ? (
          <span role="alert" className="text-[13px] font-medium text-error">
            {error}
          </span>
        ) : null}
      </span>
      <Switch
        label={typeof label === "string" ? label : sub}
        labelClassName="sr-only"
        checked={checked}
        onCheckedChange={onChange}
        aria-busy={busy || undefined}
      />
    </li>
  )
}
```

If `Switch` has no `labelClassName` prop, read `web/src/components/ui/switch.tsx` and use whatever it offers to keep the label visually hidden while it stays the accessible name (for weekly rows pass `` `Weekly ${subject} email` ``, as the mock's `aria-label` does).

- [ ] **Step 2: Screen**

`web/src/portals/parent/screens/Emails.tsx`:

```tsx
/*
 * L11 · Emails settings (SB frame FM). The weekly summary switches per child
 * and subject, and the right-away alerts a parent actually receives. The
 * weekly switch lives only here, never on the dashboard. Each switch saves on
 * press with one key (N6); a failure names its row (N5) and reverts.
 */
import { useState } from "react"
import { ChatTeardrop, EnvelopeSimple } from "@phosphor-icons/react"
import { SkeletonBlock } from "@/components/ui/skeleton"
import { useProfile } from "@/lib/hooks/useMeApi"
import {
  useNotificationPreferences,
  useUpdateNotificationPreferences,
} from "@/lib/hooks/useNotificationPrefsApi"
import { weeklySummaryUpdate, type NotificationPreferencesUpdate } from "@/lib/notificationPrefs"
import { settingsLoadFailureMessage, settingsSaveFailureMessage } from "@/lib/settingsOutcome"
import { EmailRow } from "./emails/EmailRow"
import { emailsView, rowChecked } from "./model/emailsModel"
import { LoadError } from "./shared/LoadError"
import { ParentPageHead } from "./shared/ParentPageHead"
import { SubjectDot } from "./shared/SubjectDot"
import { subjectTone } from "./model/topicCopy"

export function Emails() {
  const prefs = useNotificationPreferences()
  const update = useUpdateNotificationPreferences()
  const { data: profile } = useProfile()
  const [pending, setPending] = useState<Map<string, boolean>>(new Map())
  const [errors, setErrors] = useState<Map<string, string>>(new Map())

  const save = (key: string, next: boolean, body: NotificationPreferencesUpdate) => {
    setPending((m) => new Map(m).set(key, next))
    setErrors((m) => {
      const copy = new Map(m)
      copy.delete(key)
      return copy
    })
    update.mutate(body, {
      onError: (error) => setErrors((m) => new Map(m).set(key, settingsSaveFailureMessage(error))),
      onSettled: () =>
        setPending((m) => {
          const copy = new Map(m)
          copy.delete(key)
          return copy
        }),
    })
  }

  return (
    <div className="mx-auto flex w-full max-w-[640px] flex-col gap-6">
      <ParentPageHead title="Emails" sub={profile?.email} />
      {prefs.status === "pending" ? (
        <div className="grid gap-3" aria-busy="true" aria-label="Loading email settings">
          <h1 className="sr-only">Emails</h1>
          {[0, 1, 2, 3].map((i) => (
            <SkeletonBlock key={i} className="h-16" />
          ))}
        </div>
      ) : null}
      {prefs.status === "error" ? (
        <LoadError
          heading="We couldn’t load your email settings"
          body={settingsLoadFailureMessage(prefs.error)}
          onRetry={() => void prefs.refetch()}
        />
      ) : null}
      {prefs.status === "success"
        ? (() => {
            const view = emailsView(prefs.data)
            return (
              <>
                {view.weekly?.length === 0 ? (
                  <p className="text-[13.5px] font-medium text-on-surface-variant">
                    Weekly summaries start once your child has a subject on Lemely.
                  </p>
                ) : null}
                {view.weekly?.map((group) => (
                  <section key={group.childId} className="grid" aria-label={group.heading}>
                    <h2 className="m-0 mb-1 text-[18px] font-extrabold tracking-[-0.01em] text-on-surface">{group.heading}</h2>
                    <ul className="m-0 list-none p-0">
                      {group.rows.map((row, i) => (
                        <EmailRow
                          key={row.key}
                          icon={<EnvelopeSimple size={18} aria-hidden="true" />}
                          label={
                            <span className="inline-flex items-center gap-1.5">
                              <SubjectDot tone={subjectTone(i)} />
                              {row.label}
                            </span>
                          }
                          sub={row.sub}
                          checked={rowChecked(row, pending)}
                          busy={pending.has(row.key)}
                          error={errors.get(row.key) ?? null}
                          onChange={(next) => save(row.key, next, weeklySummaryUpdate(row.childId, row.subjectCode, next))}
                        />
                      ))}
                    </ul>
                  </section>
                ))}
                {view.rightAway.length > 0 ? (
                  <section className="grid" aria-label="Right away">
                    <h2 className="m-0 mb-1 text-[18px] font-extrabold tracking-[-0.01em] text-on-surface">Right away</h2>
                    <ul className="m-0 list-none p-0">
                      {view.rightAway.map((row) => (
                        <EmailRow
                          key={row.key}
                          icon={<ChatTeardrop size={18} aria-hidden="true" />}
                          label={row.label}
                          sub={row.sub}
                          checked={rowChecked(row, pending)}
                          busy={pending.has(row.key)}
                          error={errors.get(row.key) ?? null}
                          onChange={(next) => save(row.key, next, { [row.key]: next })}
                        />
                      ))}
                    </ul>
                  </section>
                ) : null}
              </>
            )
          })()
        : null}
    </div>
  )
}
```

Weekly rows: the `aria-label` the mock uses is "Weekly {Subject} email"; pass it through `EmailRow`'s switch label (adjust `EmailRow` to take an explicit `switchLabel` prop if needed).

- [ ] **Step 3: Routes and entry point**

In `web/src/portals/parent/index.tsx` (after F1 has landed its parent shell):
1. Add `const Emails = lazy(() => import("./screens/Emails").then((m) => ({ default: m.Emails })))` beside the other lazy screens.
2. Add the route entry before the `notifications` route:

```tsx
    {
      path: "emails",
      element: <Emails />,
      handle: { title: "Emails", skeleton: "list" },
    },
```

3. Confirm F1's Topics route (`:childId/topics` per the contract) renders `<Weaknesses />` and keep `children/:childId/weaknesses` as `<Navigate replace to={parentTopicsPath(childId)} />` (a tiny wrapper reading `useParams`) so old links and the switcher tail still land on Topics.
4. Add one entry to F1's parent account menu (or the child switcher sheet, wherever F1 put "Settings"): label "Emails", icon `EnvelopeSimple`, `to={PARENT_EMAILS_PATH}`.

- [ ] **Step 4: Verify**

Run: `cd web && npx tsc -b --noEmit && npx oxlint src/portals/parent && npm run check:copy && npm run check:native && npx vitest run tests/unit/parentEmailsModel.test.ts tests/unit/notificationPrefsWeekly.test.ts tests/unit/notificationPrefs.test.ts`
Expected: clean. In the browser: toggle a weekly switch (network tab shows one PUT with one `weeklySummaries` item), block the PUT and toggle (row shows the error, switch reverts), check `/settings/notifications` still works for the parent.

- [ ] **Step 5: Commit**

```bash
PYTHONPATH=$(pwd) pre-commit run --files web/src/portals/parent/screens/Emails.tsx web/src/portals/parent/screens/emails/EmailRow.tsx web/src/portals/parent/index.tsx
git commit -S -m "feat(web): parent Emails settings screen and routes" -- web/src/portals/parent/screens/Emails.tsx web/src/portals/parent/screens/emails web/src/portals/parent/index.tsx
```

---

### Task 14: Playwright happy paths

**Agent:** `test-engineer`.

**Files:**
- Create: `web/e2e/parent-redesign.spec.ts`
- Modify: `web/e2e/parent-journey.spec.ts` (journey b's P-03/P-04 assertions)

- [ ] **Step 1: Update journey b**

In `web/e2e/parent-journey.spec.ts`, replace the P-03 and P-04 blocks of the second test with:

```ts
  // P-03: subject detail (0625 — scripts/seed_e2e.py's SUBJECT_CODE).
  await page.getByRole("link", { name: /0625|Physics/ }).first().click()
  await expect(page.getByText("Papers they’ve done")).toBeVisible({ timeout: 15_000 })
  await expect(page.getByText("Predicted")).toBeVisible()
  await expect(page.getByText("Marks per paper")).toBeVisible()

  // P-04: the seed persists every attempt with `weak_areas=[]`, so the honest
  // render is "nothing weak yet" on the subject and on Topics.
  await expect(page.getByText(/Nothing stands out as a weak topic in .+ yet\./)).toBeVisible()
  await page.goto(`/parent/${declining.userId}/topics`)
  await expect(page.getByRole("heading", { name: "Topics to work on" })).toBeVisible({ timeout: 15_000 })
  await expect(page.getByText("Nothing stands out yet.")).toBeVisible()
```

- [ ] **Step 2: Write the new spec**

```ts
import { test, expect } from "@playwright/test"
import { watchConsole } from "./console-errors"
import { injectSession, readSeed } from "./seed"

/*
 * L11 · parent subject, topics and Emails happy paths. The seeded child has
 * no weak areas, so the Topics list is served from a fixture through
 * page.route; the subject and Emails screens run against the real stack.
 */

async function asParent(page: import("@playwright/test").Page) {
  const seed = readSeed()
  await injectSession(page, { accessToken: seed.parent.accessToken, userId: seed.parent.userId, role: "parent" })
  return seed
}

test("subject shows the summary line, marks per paper and papers", async ({ page }) => {
  const errors = watchConsole(page)
  const seed = await asParent(page)
  const child = seed.students.declining
  await page.goto(`/parent/children/${child.userId}/subjects/0625`)
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible({ timeout: 15_000 })
  await expect(page.getByText("Predicted")).toBeVisible()
  await expect(page.getByRole("heading", { name: "Marks per paper" })).toBeVisible()
  await expect(page.getByRole("group", { name: /^Paper \d:/ })).toBeVisible()
  await expect(page.getByRole("heading", { name: "Papers they’ve done" })).toBeVisible()
  await expect(page.getByRole("switch")).toHaveCount(0) // no settings on the dashboard
  expect(errors).toEqual([])
})

test("topics lists ranked rows, filters by subject and opens the topic sheet", async ({ page }) => {
  const errors = watchConsole(page)
  const seed = await asParent(page)
  const child = seed.students.declining
  const doing = { practisedThisWeek: 2, practiceAwarded: 7, practiceMaximum: 9, inPlanThisWeek: false, flashcardsDue: 0, assignment: null }
  await page.route(`**/api/parent/children/${child.userId}/weaknesses`, (route) =>
    route.fulfill({
      json: {
        childId: child.userId,
        displayName: child.displayName,
        paperCount: 3,
        weakTopics: [],
        topics: [
          { subjectCode: "0580", subjectName: "Mathematics", topic: "Vectors", lostMarks: 9, basisPapers: 3, trend: "worse",
            papers: [{ paperId: "0580/42", recordedAt: "2026-04-10T10:00:00Z", lostMarks: 4 }], doing },
          { subjectCode: "0625", subjectName: "Physics", topic: "Waves", lostMarks: 6, basisPapers: 3, trend: "same", papers: [],
            doing: { ...doing, practisedThisWeek: 0, practiceMaximum: 0, practiceAwarded: 0, inPlanThisWeek: true } },
        ],
      },
    }),
  )
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto(`/parent/${child.userId}/topics`)
  await expect(page.getByRole("heading", { name: "Topics to work on" })).toBeVisible({ timeout: 15_000 })
  const list = page.getByRole("list", { name: "Topics to work on" })
  await expect(list.getByRole("listitem")).toHaveCount(2)

  await page.getByRole("tab", { name: "Physics" }).click()
  await expect(list.getByRole("listitem")).toHaveCount(1)
  await page.getByRole("tab", { name: "All" }).click()

  await list.getByText("Vectors").click()
  const sheet = page.getByRole("dialog", { name: "Vectors" })
  await expect(sheet.getByText(`What ${child.displayName} is doing`)).toBeVisible()
  await expect(sheet.getByText("Practised twice this week · 7 of 9 back")).toBeVisible()
  await page.keyboard.press("Escape")
  await expect(sheet).toBeHidden()
  expect(errors).toEqual([])
})

test("Emails flips one weekly summary with a one-item PUT", async ({ page }) => {
  const errors = watchConsole(page)
  const seed = await asParent(page)
  await page.goto("/parent/emails")
  await expect(page.getByRole("heading", { name: "Emails" })).toBeVisible({ timeout: 15_000 })
  await expect(page.getByRole("heading", { name: new RegExp(`Weekly summary · ${seed.students.declining.displayName}`) })).toBeVisible()
  const firstWeekly = page.getByRole("switch").first()
  const before = await firstWeekly.getAttribute("aria-checked")
  const put = page.waitForRequest((r) => r.url().endsWith("/api/me/notification-preferences") && r.method() === "PUT")
  await firstWeekly.click()
  const body = (await put).postDataJSON() as { weeklySummaries: unknown[] }
  expect(Object.keys(body)).toEqual(["weeklySummaries"])
  expect(body.weeklySummaries).toHaveLength(1)
  await expect(firstWeekly).toHaveAttribute("aria-checked", before === "true" ? "false" : "true")
  await firstWeekly.click() // restore for other specs
  expect(errors).toEqual([])
})
```

- [ ] **Step 3: Run**

Run: `cd web && npx playwright test e2e/parent-redesign.spec.ts e2e/parent-journey.spec.ts`
Expected: all pass against the seeded stack (the suite's `global-setup.ts` seeds it).

- [ ] **Step 4: Commit**

```bash
PYTHONPATH=$(pwd) pre-commit run --files web/e2e/parent-redesign.spec.ts web/e2e/parent-journey.spec.ts
git commit -S -m "test(e2e): parent subject, topics and Emails happy paths" -- web/e2e/parent-redesign.spec.ts web/e2e/parent-journey.spec.ts
```

---

### Task 15: Delete the old code and dead references

**Files:**
- Modify: anything still importing the removed helpers.

- [ ] **Step 1: Find leftovers**

Run: `cd web && grep -rn "WeaknessChip\|PredictedBasis\|accuracyTone\|TONE_TO_SEVERITY\|TONE_CLASS\|What to work on next\|All subjects" src/portals/parent tests e2e`
Expected: no hit in the parent screens (the old `SubjectDetail.tsx`/`Weaknesses.tsx` bodies were replaced in Tasks 11–12). Shared components (`WeaknessChip`, `severity.ts`) stay if any other screen imports them; check with `grep -rln "weakness-chip\|lib/severity" src` and delete a file only when it has no importer left.

- [ ] **Step 2: Check the switcher tail (W9)**

Open a child's Topics screen, switch child with F1's switcher, confirm it lands on the other child's Topics screen. If F1's switcher keeps a tail list, make sure `/topics` is in it (F1's file: report to F1 if it is missing rather than editing it).

- [ ] **Step 3: Run the lane's checks**

Run: `cd web && npx tsc -b --noEmit && npm run lint && npm run check:copy && npx vitest run tests/unit/parentTopicCopy.test.ts tests/unit/parentSubjectModel.test.ts tests/unit/parentTopicsModel.test.ts tests/unit/parentEmailsModel.test.ts tests/unit/notificationPrefsWeekly.test.ts tests/unit/notificationPrefs.test.ts tests/unit/parentOutcome.test.ts`
Expected: clean.

- [ ] **Step 4: Commit** (only if something changed)

```bash
git commit -S -m "refactor(web): drop the old parent subject and weaknesses code" -- <exact paths changed>
```

---

### Task 16: Fidelity screenshots, drift fixes, polish

**Agent:** `designer`.

- [ ] **Step 1: Serve the mock and capture side by side**

```bash
python3 -m http.server 4599 --directory .impeccable/mocks &
```

Write a throwaway Playwright script in the scratchpad (not committed) that, for each frame id in `FA FS1 FZ1 FN1 FL1 FE1 WA WS TZ TE FM`, screenshots `#<id>` from `http://localhost:4599/student-r2/parent-final.html` and the matching app state at 390 wide; and `#FDK`, `#TDK` against the app at 1280. Drive app states with `page.route` fixtures for FS1 (one paper), FN1 (no topics), FL1 (delayed response), FE1/TE (500), TZ (`paperCount: 0`). Save pairs to `reports/redesign/l11/<frame>-{mock,app}.png` locally (do not commit `reports/`). Also capture 768 for each app state.

- [ ] **Step 2: Fix drift**

List every visible difference per pair. Fix spacing, type, colour and alignment drift in the lane's files. Anything that would change layout, flow or content goes to "Needs user decision" instead.

- [ ] **Step 3: Polish**

Run `/impeccable polish` on `web/src/portals/parent/screens/{SubjectDetail,Weaknesses,Emails}.tsx` and their folders. Check: no text under 12px, 44px targets, contrast, focus rings, reduced motion (DevTools emulation), no Binny, no horizontal scroll at 320.

- [ ] **Step 4: Commit**

```bash
PYTHONPATH=$(pwd) pre-commit run --files <changed files>
git commit -S -m "style(web): parent screens fidelity and polish" -- <changed files>
```

---

### Task 17: Keep-list check, gates, push and PR

- [ ] **Step 1: Keep-list**

Tick every K, W, B and N item above against the running app and the tests, with the commit or test that proves it. Paste the ticked list into the PR body.

- [ ] **Step 2: Gates (lane-touched files only)**

Derive the list from `.github/workflows/ci.yml`, then run the parts that cover this lane:

```bash
PYTHONPATH=$(pwd) /home/sico/Code/Lemely/.venv/bin/python -m pytest tests/test_parent_topics.py tests/test_child_topic_activity_repo.py tests/test_web_parent_topics.py tests/test_web_parent_subject_series.py tests/test_web_parent.py tests/test_migration_parent_weekly_email_prefs.py tests/test_parent_weekly_email_repo.py tests/test_web_me_weekly_summaries.py tests/test_db_schema.py $(ls tests/test_*lint*.py)
cd web && npx tsc -b --noEmit && npm run lint && npm run check:copy && npx vitest run tests/unit/parentTopicCopy.test.ts tests/unit/parentSubjectModel.test.ts tests/unit/parentTopicsModel.test.ts tests/unit/parentEmailsModel.test.ts tests/unit/notificationPrefsWeekly.test.ts tests/unit/notificationPrefs.test.ts tests/unit/parentOutcome.test.ts && npx playwright test e2e/parent-redesign.spec.ts e2e/parent-journey.spec.ts
cd .. && PYTHONPATH=$(pwd) pre-commit run --files $(git diff --name-only origin/develop...HEAD)
```

Expected: all green. `pre-commit`'s ruff hook autofixes: after it runs, `git status` must be clean, or the fix must be committed before the push.

- [ ] **Step 3: Rebase the migration**

`git fetch origin && git rebase origin/develop`. If another lane added a migration, set `down_revision` in `0055_parent_weekly_email_prefs.py` (rename the revision number if needed) and `DOWN_REVISION` in its test to the new head, rerun the migration test, and commit.

- [ ] **Step 4: Push and open the PR**

```bash
git push -u origin redesign/l11
gh pr create --base develop --title "feat(parent): redesigned subject, topics and Emails (L11)" --body-file <scratch PR body with: summary, keep-list ticked, frame screenshots, small changes from the mock (listed below), Needs user decision items, migration note "needs approval before running on a shared DB">
```

Small changes from the mock to list in the PR: subject dots mapped to tokens; "his" → "their" in TZ; Target segment hidden when no target; FZ1 shows no Target (the 404 carries none); paper rows without chevron; "Right away" shows only the alert parents receive; Phosphor icons in place of the mock's inline SVGs where equivalent.

---

## Dependencies on other lanes

- **F1 `StepsPath`** must accept per-bar captions and a goal caption to show the mock's `61/80` and `68/80 · A* line · 7 to go` row on the same baseline. The contract has `papers: {id,label,grade,pct}[]` and `goal` only. L11 needs optional `papers[i].sub?: string`, `goalSub?: string` and `goalNote?: string` (or equivalent). L11 passes `pct` as height relative to the goal block (100 = goal line). Raise with F1 before Task 11.
- **F1 `RankRow`** `sub` is a string, so the mock's coloured subject dot inside the row's sub line cannot be drawn. Either F1 accepts `sub?: React.ReactNode` (compatible widening) or the dot is dropped on rows (it stays on filter chips).
- **F1 `H2Row`** needs a trailing slot for the Paper 4 / Paper 2 toggle, or L11 wraps it (Task 11 notes the wrap).
- **F1 parent shell** owns the Topics route path, the child switcher (must keep the `/topics` tail) and the account menu where L11 adds "Emails".
- **L1, L6, L9, L12 migrations:** rebase `0055`'s `down_revision` before merge.
- **L7 (S1 result + parent crop route):** if L7 ships a parent paper view, paper rows here can link to it (Needs user decision 2).

## Needs user decision

1. **"Message Ms Adel" has no backend.** There is no parent-to-teacher messaging anywhere in the app. Recommendation: leave the header icon and the sheet's button out of this lane and track parent messaging as its own feature. A `mailto:` would expose teacher emails to parents, which is a privacy call this lane should not make.
2. **Paper rows go nowhere.** Parents have no paper result screen (the mock's rows open "Result"). Recommendation: ship rows without a chevron now, and link them once a parent paper view exists (possibly from L7's parent crop route).
3. **"Right away" alerts mostly do not reach parents.** `gradeReady` and `announcement` are only ever sent to the student, and no teacher message exists. Only `atRiskAlert` reaches a parent. Recommendation: show only "Something to look at" now. A small follow-up can notify linked parents on `grade_ready`, after which "New marked paper" can be added to `RIGHT_AWAY`.
4. **No weekly summary email is sent yet.** This lane stores the per-subject flags (as briefed), but nothing sends the Sunday email. A switch that sends nothing is what the codebase's honesty rule (UI spec §1.4) forbids. Recommendation: approve a follow-up lane for the weekly sender (a sweeper job writing to the existing `email_outbox`) before this reaches `main`. Or hide the weekly section behind a config flag until it ships.
5. **These are not emails today.** Right-away alerts are push and inbox notifications, but the screen is titled "Emails". Recommendation: keep "Emails" for the weekly summary, and rename the second heading to "Right away · notifications" (or retitle the screen "Emails and alerts") so parents are not misled.
6. **Weekly flags default to on.** The mock shows them mostly on. Recommendation: on by default (it is the parent's own child's data and they opted into the portal). Change `DEFAULT_WEEKLY_ENABLED` if you prefer opt-in.
7. **Topics route path.** The F1 contract says `/parent/:childId/topics`, but every live parent route is `/parent/children/:childId/...`. Recommendation: use `/parent/children/:childId/topics` for consistency, with a redirect from `/weaknesses`. Either way, it is one constant in `model/parentPaths.ts`.
8. **Boundary distance and accuracy share dropped.** The mock replaces "N more marks for an A" with the goal block, and the topic accuracy percentage with marks lost. Both stay on the API. Recommendation: accept, as the mock was approved.
