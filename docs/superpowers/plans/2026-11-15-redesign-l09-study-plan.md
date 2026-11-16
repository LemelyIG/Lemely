# L9 · Study Plan Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the two study-plan screens (`StudyPlanWeek`, `StudyPlanSession`) with the approved WA design: one week across all subjects, today first, a session sheet (a side panel on desktop), a subject filter, and every state. Add the backend it needs: move a session to a day, and one week view across all subjects.

**Architecture:**
- **Backend.** `StudyPlanService` (`lemely/db/study_plan_repo.py`) gains `move_session`, `generate(..., next_week=True)` and `get_week`. `get_week` returns every enrolled subject's current plan plus honest per-session reasons, computed at read time from rows that already exist. No migration.
- **Router.** `lemely/web/routers/study_plan.py` gains `GET /api/student/study-plan` (the week) and `POST /api/student/study-plan/sessions/{id}/move`.
- **Frontend.** A thin `StudyPlanScreen` sits on one query (`useStudyPlanWeek`). Two pure modules hold every decision: `planCopy.ts` (strings, dates, reasons) and `planModel.ts` (state selection, sections, ring, strip). Small presentational files render it with the F1 kit.

**Tech Stack:**
- Backend: FastAPI, SQLAlchemy 2, pytest on a throwaway Postgres
- Frontend: React 19, react-router 7, TanStack Query 5, Tailwind 4, Radix `Sheet`, F1 kit (`@/components/redesign`)
- Tests: Vitest (node environment, pure modules only), Playwright

**Spec:** `docs/superpowers/specs/2026-11-14-redesign-implementation-design.md` (Wave 3, item 9). **Master:** `docs/superpowers/plans/2026-11-15-redesign-00-master.md`. **Mock:** `.impeccable/mocks/student-r2/plan-final.html` + `sp.js`, `sp.css`, `t.js`/`t.css` (`h4.js` `ring4`, `h6.js` `TAB6`/`DRAIL6`, `h.js` `BIN`).

## Global Constraints

Inherits the master plan Global Constraints, unchanged. Lane-specific additions:

- **One clock.** The service's injected `now` is the only clock on the backend. Routers never read the wall clock for this feature (the lesson of commit `7ba50165`, where the widget router read `datetime.now` while its services ran on a pinned clock). The frontend takes "today" from the response's `today` field and never from `new Date()`. That keeps UTC day boundaries the same on both sides.
- **Copy gate.** `npm run check:copy` bans `!` in product copy (`web/scripts/check_copy.mjs`, `EXCLAMATION_ALLOWLIST = []`). Mock lines ending in `!` ship with a full stop ("Week done.", "15 minutes today."). See Needs user decision #1.
- **No token changes.** Mock colours that are not tokens are mapped onto existing tokens (table in Task 7). Subject dots use a fixed rotation of existing tokens.
- **Binny once per screen.** On desktop the side panel carries Binny. While a rebuild runs, the rebuild banner carries Binny and the panel hides its own.
- **Lane-owned files:** `web/src/portals/student/screens/studyplan/*`, `web/src/lib/studyPlanTypes.ts`, `web/src/lib/studyPlanCache.ts` (new), `web/src/lib/hooks/useStudyPlanApi.ts`, `lemely/db/study_plan_repo.py`, `lemely/web/routers/study_plan.py`, `lemely/web/schemas_study_plan.py`, `tests/test_study_plan_repo.py`, `tests/test_web_study_plan.py`, `web/tests/unit/studyPlan*.test.ts`, `web/e2e/study-plan.spec.ts` (new).
- **Narrow edits outside the lane** (each named in its task): `web/src/portals/student/index.tsx` (the study-plan route entries only), `tests/test_authz_matrix_complete.py` (two `EXPECTED` rows), `web/e2e/phase4-journey.spec.ts` (the S-24 test only), `web/scripts/audit.mjs` (the S-24/S-25 registry entries only), `web/tests/unit/utilityExistence.test.ts` and `web/tests/unit/rtlSafety.test.ts` (swap the studyplan file paths).
- **Run commands** assume the lane worktree as the working directory and the shared venv: `source /home/sico/Code/Lemely/.venv/bin/activate`. Python tests always run with `PYTHONPATH=$PWD`, because the shared venv's editable install can point at another worktree.

---

## File structure

**Backend (modify)**
- `lemely/db/study_plan_repo.py`: `StudyPlanMoveError`, `move_session`, `generate(next_week=)`, `get_week` with its dataclasses (`SessionReason`, `WeakTopicView`, `SubjectWeekView`, `WeekOverview`) and private readers `_paper_stats` and `_cards_due`.
- `lemely/web/schemas_study_plan.py`: `SessionReasonDTO`, `WeakTopicDTO`, `SubjectWeekDTO`, `StudyPlanOverviewDTO`, `MoveSessionRequestDTO`, `anyDay`/`reason` on `StudyPlanSessionDTO`, `week` on `CreateStudyPlanRequestDTO`.
- `lemely/web/routers/study_plan.py`: `GET ""`, `POST /sessions/{id}/move`, and `week` on `POST ""`.

**Frontend (create)**, under `web/src/portals/student/screens/studyplan/`:
- `planCopy.ts`: pure strings, dates, reasons, start actions, exam lines.
- `planModel.ts`: pure state selection and section building.
- `planStyles.ts`: token class maps for tiles and subject dots.
- `useWide.ts`: a `(min-width: 1280px)` hook.
- `icons.tsx`: the mock's drawn SVG glyphs.
- `SessionRow.tsx`: `ActivityTile`, `SubjectDot`, `SessionRow`.
- `PlanHeader.tsx`: `PlanHeader`, `SubjectFilter`.
- `WeekStrip.tsx`
- `MissedGroup.tsx`
- `BasedOn.tsx`
- `SessionDetail.tsx`: `SessionDetail`, `SessionSheet`, `SessionPanel`.
- `PlanList.tsx`: the plan body.
- `PlanStates.tsx`: loading, error, first run, need a paper, nothing scheduled, no subjects, week done, rebuilding banner, not-in-week note.
- `StudyPlanScreen.tsx`: the orchestrator.

Also: `web/src/lib/studyPlanCache.ts` (pure cache patchers).

**Frontend (modify):** `web/src/lib/studyPlanTypes.ts`, `web/src/lib/hooks/useStudyPlanApi.ts`, `web/src/portals/student/index.tsx`.

**Delete (Task 14):**
- `studyplan/StudyPlanWeek.tsx`, `studyplan/StudyPlanSession.tsx`, `studyplan/studyPlanData.ts`
- `web/tests/unit/studyPlan.test.ts`, `web/tests/unit/studyPlanHeader.test.ts`, `web/tests/unit/activityIcon.test.ts`
- the hooks `useCurrentStudyPlan` and `useRebuildStudyPlan`

---

## Keep-list

Every live behaviour, with where it lives now and where it goes. Task 14 ticks each one.

**`web/src/portals/student/screens/studyplan/StudyPlanWeek.tsx`**

| # | Live behaviour | Where | Becomes |
|---|---|---|---|
| K1 | No plan generated this week, as its own state | `:300-319`, `studyPlanData.ts:44-50` | `firstRun` (Z0) |
| K2 | Build button shows "Building…" while pending | `:308` | `FirstRun` button `loading` |
| K3 | "Take the placement test" secondary action | `:311-314`, `:330-333` | `NeedPaper` link to `/student/placement/:code` |
| K4 | Honest refusal, with copy per reason and a named fallback for unknown reasons | `:321-342`, `studyPlanData.ts:63-78` | `needPaper` (Z1) + `refusalCopy()` |
| K5 | A real plan with zero sessions is a third, distinct state | `:360-373` | `nothingScheduled` |
| K6 | Rebuild control with a pending label | `:54`, `:100-104` | `BasedOn` "Rebuild" + `RebuildingBanner` (PR) |
| K7 | Rebuild failure message, naming the action | `:289-293` | `errl` row under the header |
| K8 | Mark-complete failure message, naming the action | `:294-298` | sheet `errl` (PX) |
| K9 | Target grade + exam countdown in the header | `:233-244`, `studyPlanData.ts:330-369` | filtered `subjectTop` line + `CountdownPill` |
| K10 | "N of M sessions done" | `:110-115` | header sub "N of M done · 1 h 40 min" |
| K11 | Planned minutes (never conflated with stated hours) | `:127-136` | header sub carries the planned total. Stated hours are dropped, per the mock (Needs user decision #6) |
| K12 | Week fully complete message | `:154-158` | `weekDone` (PD) |
| K13 | "What this plan is based on" explanation | `:60-73` | "Built from your N papers and weak topics · Rebuild", plus walkthrough step 2 |
| K14 | Days grouped ascending by ISO string (no TZ parsing) | `studyPlanData.ts:140-150` | `planModel` groups by ISO string compare |
| K15 | Row: activity icon, topic, activity label, duration, link to the session | `:165-205` | `SessionRow` opens the sheet or panel |
| K16 | Per-session "Mark complete" with "Saving…" | `:210-218` | sheet "Mark done" with "Saving…" (the row no longer has an inline button, per the mock) |
| K17 | Completed state shown as a fact | `:206-209` | tick tile, struck title, done fold, sheet "Done" |
| K18 | Missing subject in link → "No subject selected" | `:264-271` | `/student/plan` is now the all-subjects view. An unknown code redirects to it |
| K19 | Load failure, with a real error state | `:276-279` | `PlanLoadError` (PE) |
| K20 | Loading skeleton | `:254-259` | `PlanLoading` (PL) |
| K21 | Timezone-safe date formatting (`T00:00:00`) | `studyPlanData.ts:381-392` | `planCopy.parseDay` |
| K22 | No invented XP on completion | `:44-49` | unchanged. XP appears only on week done, read from the real XP profile |

**`web/src/portals/student/screens/studyplan/StudyPlanSession.tsx`**

| # | Live behaviour | Where | Becomes |
|---|---|---|---|
| K23 | Session located inside the current week (no per-session GET) | `:115`, `studyPlanData.ts:178-184` | selected from the week overview by id |
| K24 | `noCurrentPlan`: the link opens, but there is no plan | `:117-132` | the screen state (first run or need a paper) + `NotInWeekNote` |
| K25 | `notInCurrentWeek`: "your plan moved on", never a 404 | `:134-146` | `NotInWeekNote` ("That session isn’t in this week’s plan. Your plan was rebuilt.") |
| K26 | Honest "why": weakness, not a weakness, or unknown | `:150-154`, `studyPlanData.ts:215-255` | server `reason` (marks lost, cards due, last paper) or the honest null copy "Picked from your placement test or your topic ratings." |
| K27 | Detail facts: topic, activity, planned time, day, status | `:167-177` | sheet header (topic; subject · activity · minutes). Day and status show through section placement and the Done state |
| K28 | Start action per activity, with none for `review` | `:155`, `:203-207`, `studyPlanData.ts:273-287` | `startAction()`, which returns `null` for review |
| K29 | Mark complete → "Marked complete" | `:208-220` | sheet "Mark done" → "Done" |
| K30 | Completion error text | `:193-197` | PX `errl` + "Try again" |
| K31 | "Back to your week" | `:221-223` | sheet close (back gesture, scrim, Escape) |
| K32 | Load error | `:109-112` | `PlanLoadError` |

**Hooks and backend**

| # | Live behaviour | Where | Becomes |
|---|---|---|---|
| K33 | No `fallback` on `request()`, so an error is never confused with "empty" | `useStudyPlanApi.ts:16-33` | same in `useStudyPlanWeek` |
| K34 | Rebuild result written as `{generated: true, plan}` | `useStudyPlanApi.ts:53-67` | per-subject cache write kept + week invalidation |
| K35 | Completion patches the cache with the server's session, not a client timestamp | `useStudyPlanApi.ts:80-103` | `patchOverviewSession` / `patchCurrentSession` |
| K36 | Student-only router gate | `routers/study_plan.py:52-54` | unchanged, and covers both new routes |
| K37 | Another student's session id → byte-identical 404 | `routers/study_plan.py:57-66` | same on `/move` |
| K38 | Malformed session id → 422, not 500 | `routers/study_plan.py:152-153` | same on `/move` |
| K39 | XP on completion, deduped per session | `routers/study_plan.py:154-161` | unchanged |
| K40 | `GET /{subject_code}`: three wire states | `routers/study_plan.py:94-109` | unchanged (the widget and push rely on the per-subject plan) |
| K41 | POST supersedes. Identity comes from the token, `extra=forbid` | `routers/study_plan.py:112-127` | unchanged, plus optional `week` |
| K42 | Completion is idempotent and keeps the first `completed_at` | `study_plan_repo.py:308-337` | unchanged. A moved session still completes (test) |

**Inbound links and gates**

| # | Live behaviour | Where | Becomes |
|---|---|---|---|
| K43 | Sidebar "Study plan" per subject → `/student/plan/:code` | `web/src/portals/student/shell.tsx:98` | opens the screen filtered to that subject |
| K44 | Push and inbox deep links → `/student/plan/:code/session/:id` | `web/src/lib/push/pushClientBridge.ts:80`, `web/src/lib/studentInbox.ts:19`, `web/src/portals/student/home/model.ts:124` | open the sheet (or select the panel) |
| K45 | Placement and practice results link to the plan | `PlacementResult.tsx:200`, `PracticeResult.tsx:211` | unchanged URL, filtered view |
| K46 | Widget "next session" reads plan dates | `lemely/web/routers/widget.py:58-89` | a move changes the date the widget reads. `tests/test_widget_router.py` stays green |
| K47 | Audit registry S-24/S-25 entries + e2e S-24 | `web/scripts/audit.mjs:2279-2385`, `web/e2e/phase4-journey.spec.ts:241-264` | updated to the new copy |

---

## Frame-to-state table

Mock frame ids are from `plan-final.html`. The `WB` variant in `sp.js` is not mounted in the final HTML, so it is not a frame.

| Frame | Component state | Breakpoint | Trigger |
|---|---|---|---|
| `WA` | `planScreen → {kind: "plan"}`, filter All | 390, tablet (single column, max 640px) | at least one available plan with an open session |
| `WM` | `plan` with `filter = code` (subject top line, why-topics, done fold open) | 390, tablet | `/student/plan/:code`, or tapping a subject chip |
| `SS` | `SessionSheet` open over the list | < 1280 | tapping a row → `/student/plan[/:code]/session/:id` |
| `Z0` | `firstRun` | all | no subject in scope has a plan this week |
| `Z1` | `needPaper` | all | every generated plan in scope is a refusal and none is missing |
| `PD` | `weekDone` | all | every session in scope is done |
| `PR` | `RebuildingBanner` + dimmed list | all | `useRebuildStudyPlans` pending (current week) |
| `PX` | sheet with `completeError` | < 1280 (panel at 1280) | `useCompleteStudyPlanSession` error for that session |
| `PL` | `PlanLoading` | all | week query pending |
| `PE` | `PlanLoadError` | all | week query error |
| `SD` | list + `SessionPanel` | ≥ 1280 | the same model. The panel follows the selected row, defaulting to `firstOpenId` |

States with no mock frame, built in the same visual language (listed in the PR as edge-case additions):
- `noSubjects`
- `nothingScheduled`
- `NotInWeekNote`
- the move-failure toast
- the "Missed N sessions · Move all to today" bar (when more than 2 are missed)
- the "pending subject" row (a subject with no plan, or a refusal, inside a plan view)
- the "Next week is ready" toast

---

## Interactions and motion

| Interaction | Mock value | Build | Reduced motion |
|---|---|---|---|
| Session sheet in/out | `.rvl` `rvup .45s var(--ease)`: from `translateY(40%)`, opacity .4. `--ease` = `cubic-bezier(.2,.8,.2,1)` | Shell rule: the kit `SheetContent side="adaptive"` and its native sheet motion (`--native-sheet-ease`, `--native-sheet-dur`). Listed as a shell-wins change | kit `motion-reduce:animate-none` |
| Scrim | `.scrim` `oklch(.2 .03 245/.25)` | kit `SheetOverlay` (`bg-scrim` / `native:bg-scrim-dialog`) | kit |
| Skeleton shimmer | `.sk` `skm 1.4s linear infinite`, `background-position → -200% 0` | kit `SkeletonBlock` | kit (none) |
| Countdown pill press | `.pill4:active{transform:scale(.97)}` | wrapper `Link` `active:scale-[.97] transition-transform duration-150 ease-[cubic-bezier(.2,.8,.2,1)]` | `motion-reduce:transition-none motion-reduce:active:scale-100` |
| Row hover | `.srow2:hover .at b{color:var(--p)}` | `group-hover:text-primary` on the title | n/a (colour only) |
| Focus | `outline:2.5px solid var(--p);outline-offset:2px;border-radius:14px` | `focus-visible:outline-[2.5px] focus-visible:outline-primary focus-visible:outline-offset-2 rounded-[14px]` on strip cells, rows and missed bars | n/a |
| Day cell tap | `data-go="Day: Thu"` | scroll to `#plan-day-<date>` (a done day opens `#plan-done`, a missed day scrolls to `#plan-missed`) | `behavior: "smooth"` → `"auto"` |
| Rebuilding dim | `.dimmed{opacity:.5}` | `opacity-50` + `aria-busy` on the list | n/a (no transition) |
| Done fold | `<details class=dsec>` | native `<details>`, no animation | n/a |
| Binny | `BIN()` (`h.js`) bob/blink keyframes | F1 `Binny`/`BinnyLine` with `motion`: Z0 `open`+`idle`, Z1 `thinking`+`idle`, PD `happy`+`hop`, PR `thinking`+`idle`, PE `sad`+`idle`, SD panel `happy`+`idle` | F1 turns every motion into `none` |
| Today ring | `ring4` segments gold when done | F1 `GoldRing` (its own fill motion) | F1 |

---

# Backend tasks

### Task 1: Repo writes: move a session, generate next week

**Files:**
- Modify: `lemely/db/study_plan_repo.py` (imports `:66-92`, `generate` `:187-277`, new error class after `:130`, new method after `complete_session` `:337`, `__all__` `:559-566`)
- Test: `tests/test_study_plan_repo.py` (append)

**Interfaces:**
- Produces:
  - `class StudyPlanMoveError(StudyPlanError)` with `.code: Literal["completed", "superseded", "past_day", "outside_week"]`
  - `StudyPlanService.move_session(student_id, session_id, to_date: date, *, now: datetime | None = None) -> SessionView`
  - `StudyPlanService.generate(student_id, subject_code, *, weekly_hours=None, now=None, next_week: bool = False) -> PlanView`

- [ ] **Step 1: Write the failing tests.** Append this to `tests/test_study_plan_repo.py`, and add `time` to its `datetime` import and `StudyPlanMoveError` to its `lemely.db.study_plan_repo` import:

```python
# ---------------------------------------------------------------------------
# L9 · moving a session and planning next week.
# ---------------------------------------------------------------------------

_WED = _THIS_WEEK.date()  # 2026-08-05, "today" for study_plan_service
_MON = _WED - timedelta(days=2)  # 2026-08-03, this ISO week's Monday
_SUN = _MON + timedelta(days=6)  # 2026-08-09, this ISO week's Sunday


def _seed_plan(
    sm: sessionmaker[Session], service: StudyPlanService, *, topic: str = "1 Motion"
) -> tuple[uuid.UUID, object]:
    """One weak topic and the default 11-hour week: 7 blocks, Wed..Tue (spills past Sunday)."""
    student = _seed_user(sm)
    _seed_weakness(sm, student, topic=topic, lost_marks=5)
    return student, service.generate(student, "0625")


def test_move_session_to_a_later_day_persists_and_leaves_the_rest_alone(
    pg_sessionmaker: sessionmaker[Session], study_plan_service: StudyPlanService
) -> None:
    student, plan = _seed_plan(pg_sessionmaker, study_plan_service)
    first = plan.sessions[0]
    assert first.date == _WED

    moved = study_plan_service.move_session(student, first.id, _SUN)

    assert moved.date == _SUN
    reread = study_plan_service.get_current(student, "0625")
    assert reread is not None
    assert next(s for s in reread.sessions if s.id == first.id).date == _SUN
    # Inverse: every other session kept its date.
    before = {s.id: s.date for s in plan.sessions if s.id != first.id}
    after = {s.id: s.date for s in reread.sessions if s.id != first.id}
    assert before == after


def test_a_missed_session_moves_to_today(pg_sessionmaker: sessionmaker[Session]) -> None:
    monday = datetime(2026, 8, 3, 9, 0, tzinfo=UTC)
    on_monday = StudyPlanService(pg_sessionmaker, now=lambda: monday)
    student = _seed_user(pg_sessionmaker)
    _seed_weakness(pg_sessionmaker, student, topic="1 Motion", lost_marks=5)
    plan = on_monday.generate(student, "0625")
    missed = plan.sessions[0]
    assert missed.date == _MON

    on_wednesday = StudyPlanService(pg_sessionmaker, now=lambda: _THIS_WEEK)
    assert on_wednesday.move_session(student, missed.id, _WED).date == _WED


def test_moving_to_a_past_day_is_refused(
    pg_sessionmaker: sessionmaker[Session], study_plan_service: StudyPlanService
) -> None:
    student, plan = _seed_plan(pg_sessionmaker, study_plan_service)

    with pytest.raises(StudyPlanMoveError) as exc:
        study_plan_service.move_session(student, plan.sessions[1].id, _WED - timedelta(days=1))
    assert exc.value.code == "past_day"

    # Inverse: today itself is allowed.
    assert study_plan_service.move_session(student, plan.sessions[1].id, _WED).date == _WED


def test_moving_past_the_plans_last_day_is_refused(
    pg_sessionmaker: sessionmaker[Session], study_plan_service: StudyPlanService
) -> None:
    student, plan = _seed_plan(pg_sessionmaker, study_plan_service)
    last_day = max(max(s.date for s in plan.sessions), _SUN)

    with pytest.raises(StudyPlanMoveError) as exc:
        study_plan_service.move_session(student, plan.sessions[0].id, last_day + timedelta(days=1))
    assert exc.value.code == "outside_week"

    # Inverse: the last day itself is allowed.
    assert study_plan_service.move_session(student, plan.sessions[0].id, last_day).date == last_day


def test_a_completed_session_cannot_be_moved(
    pg_sessionmaker: sessionmaker[Session], study_plan_service: StudyPlanService
) -> None:
    student, plan = _seed_plan(pg_sessionmaker, study_plan_service)
    study_plan_service.complete_session(student, plan.sessions[0].id)

    with pytest.raises(StudyPlanMoveError) as exc:
        study_plan_service.move_session(student, plan.sessions[0].id, _SUN)
    assert exc.value.code == "completed"

    # Inverse: an open session in the same plan still moves.
    assert study_plan_service.move_session(student, plan.sessions[1].id, _SUN).date == _SUN


def test_a_session_on_a_superseded_plan_cannot_be_moved(
    pg_sessionmaker: sessionmaker[Session], study_plan_service: StudyPlanService
) -> None:
    student, old = _seed_plan(pg_sessionmaker, study_plan_service)
    fresh = study_plan_service.generate(student, "0625")

    with pytest.raises(StudyPlanMoveError) as exc:
        study_plan_service.move_session(student, old.sessions[0].id, _SUN)
    assert exc.value.code == "superseded"

    # Inverse: the active plan's session moves.
    assert study_plan_service.move_session(student, fresh.sessions[0].id, _SUN).date == _SUN


def test_move_session_is_owner_scoped(
    pg_sessionmaker: sessionmaker[Session], study_plan_service: StudyPlanService
) -> None:
    owner, plan = _seed_plan(pg_sessionmaker, study_plan_service)
    other = _seed_user(pg_sessionmaker)

    with pytest.raises(StudyPlanOwnershipError):
        study_plan_service.move_session(other, plan.sessions[0].id, _SUN)
    with pytest.raises(StudyPlanNotFoundError):
        study_plan_service.move_session(owner, uuid.uuid4(), _SUN)

    # Inverse: the owner moves it.
    assert study_plan_service.move_session(owner, plan.sessions[0].id, _SUN).date == _SUN


def test_a_moved_session_still_completes(
    pg_sessionmaker: sessionmaker[Session], study_plan_service: StudyPlanService
) -> None:
    student, plan = _seed_plan(pg_sessionmaker, study_plan_service)
    study_plan_service.move_session(student, plan.sessions[0].id, _SUN)

    done = study_plan_service.complete_session(student, plan.sessions[0].id)

    assert done.completed_at == _THIS_WEEK
    assert done.date == _SUN


def test_next_week_generation_lands_on_next_mondays_week(
    pg_sessionmaker: sessionmaker[Session], study_plan_service: StudyPlanService
) -> None:
    student = _seed_user(pg_sessionmaker)
    _seed_weakness(pg_sessionmaker, student, topic="1 Motion", lost_marks=5)
    next_monday = _MON + timedelta(days=7)

    upcoming = study_plan_service.generate(student, "0625", next_week=True)

    assert upcoming.week_start == next_monday
    assert min(s.date for s in upcoming.sessions) == next_monday
    assert upcoming.generated_at == _THIS_WEEK  # stamped with the real clock, not the future
    # Inverse: this week still has no plan, and next week's lookup finds it.
    assert study_plan_service.get_current(student, "0625") is None
    found = study_plan_service.get_current(
        student, "0625", now=datetime.combine(next_monday, time(9), tzinfo=UTC)
    )
    assert found is not None
    assert found.id == upcoming.id
```

- [ ] **Step 2: Run the tests and watch them fail.**

Run: `PYTHONPATH=$PWD pytest tests/test_study_plan_repo.py -q -k "move or next_week"`
Expected: an ImportError on `StudyPlanMoveError` (collection error).

- [ ] **Step 3: Implement.** In `lemely/db/study_plan_repo.py`:

Change the datetime import line to:

```python
from datetime import UTC, date, datetime, time, timedelta
```

After `_week_start` add:

```python
def _next_week_moment(now: datetime) -> datetime:
    """Midnight UTC on the Monday after ``now``'s ISO week: the clock "Plan next week" schedules on."""
    return datetime.combine(_week_start(now) + timedelta(days=7), time.min, tzinfo=UTC)
```

After `StudyPlanOwnershipError` add:

```python
class StudyPlanMoveError(StudyPlanError):
    """A move the plan does not allow.

    ``code`` is machine-readable for the HTTP layer:

    * ``"completed"``: the session is done, and a completion record is history.
    * ``"superseded"``: a rebuild replaced the plan, so the id is stale.
    * ``"past_day"``: the target is before today.
    * ``"outside_week"``: the target is after the plan's last day.

    The plan's last day is its ISO Sunday, or its latest session if the scheduler
    placed one past Sunday (sessions start at ``now.date()``).
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
```

Replace `generate` with:

```python
    def generate(
        self,
        student_id: uuid.UUID | str,
        subject_code: str,
        *,
        weekly_hours: float | None = None,
        now: datetime | None = None,
        next_week: bool = False,
    ) -> PlanView:
        """Build a week's plan from the three live signals and persist it.

        Supersedes (never mutates) any existing active plan for the same
        ``(student, subject, week)`` — see the module docstring. Persists
        even a ``no_signal`` refusal, so "the student has no plan generated
        yet this week" and "the student was refused a plan this week" are
        both real, queryable states via :meth:`get_current`.

        ``next_week=True`` plans the ISO week after the clock's ("Plan next
        week" on the week-done screen): sessions are laid out from next
        Monday, and :meth:`get_current` finds the plan once that week
        arrives. ``generated_at``/``superseded_at`` still record the real
        clock, never the future Monday.

        ``weekly_hours`` defaults to the caller's ``StudentProfile
        .weekly_study_hours`` when omitted, falling back to
        :data:`_DEFAULT_WEEKLY_HOURS` when the caller has no profile row or
        left it unset.
        """
        student_uuid = _as_uuid(student_id)
        clock = now if now is not None else self._now()
        moment = _next_week_moment(clock) if next_week else clock
        week_start = _week_start(moment)

        with self._sessionmaker() as session, session.begin():
            weaknesses = self._weaknesses(session, student_uuid, subject_code)
            placement_results = self._placement_results(session, student_uuid, subject_code)
            confidence_ratings = self._confidence_ratings(session, student_uuid, subject_code)
            resolved_hours = (
                weekly_hours
                if weekly_hours is not None
                else self._weekly_hours(session, student_uuid)
            )
            topics = (
                {w.topic for w in weaknesses}
                | {p.topic for p in placement_results}
                | {c.topic for c in confidence_ratings}
            )
            availability = self._availability(session, student_uuid, subject_code, topics)

            plan = build_study_plan(
                str(student_uuid),
                subject_code,
                weekly_hours=resolved_hours,
                now=moment,
                weaknesses=weaknesses,
                placement_results=placement_results,
                confidence_ratings=confidence_ratings,
                availability=availability,
            )

            existing = session.scalars(
                select(DbStudyPlan).where(
                    DbStudyPlan.user_id == student_uuid,
                    DbStudyPlan.subject_code == subject_code,
                    DbStudyPlan.week_start == week_start,
                    DbStudyPlan.superseded_at.is_(None),
                )
            ).first()
            if existing is not None:
                existing.superseded_at = clock

            row = DbStudyPlan(
                user_id=student_uuid,
                subject_code=subject_code,
                week_start=week_start,
                weekly_hours=resolved_hours,
                available=plan.available,
                reason=plan.reason,
                generated_at=clock,
            )
            session.add(row)
            session.flush()

            session_rows = [
                DbStudyPlanSession(
                    plan_id=row.id,
                    date=s.date,
                    topic=s.topic,
                    activity_type=DbActivityType(s.activity_type.value),
                    duration_minutes=s.duration_minutes,
                    focus=s.focus,
                )
                for s in plan.sessions
            ]
            for session_row in session_rows:
                session.add(session_row)
            session.flush()

            return self._to_view(row, session_rows)
```

After `complete_session` add:

```python
    def move_session(
        self,
        student_id: uuid.UUID | str,
        session_id: uuid.UUID | str,
        to_date: date,
        *,
        now: datetime | None = None,
    ) -> SessionView:
        """Move one of the caller's own open sessions to another day of its plan.

        The one edit a plan's sessions take besides ``completed_at``. A
        rebuild still supersedes the whole plan (moves included), exactly as
        it supersedes completions — the module's "never mutate history" rule
        is about superseded plans, and a superseded plan refuses moves.

        Raises:
            StudyPlanNotFoundError / StudyPlanOwnershipError: as
                :meth:`complete_session` (both rendered 404).
            StudyPlanMoveError: ``completed``, ``superseded``, ``past_day``
                or ``outside_week`` — see the class docstring.
        """
        student_uuid = _as_uuid(student_id)
        session_uuid = _as_uuid(session_id)
        moment = now if now is not None else self._now()
        today = moment.date()
        with self._sessionmaker() as session, session.begin():
            row, plan = self._owned_session(session, student_uuid, session_uuid)
            if plan.superseded_at is not None:
                raise StudyPlanMoveError("superseded", "This session's plan has been rebuilt")
            if row.completed_at is not None:
                raise StudyPlanMoveError("completed", "A completed session cannot be moved")
            if to_date < today:
                raise StudyPlanMoveError("past_day", "A session cannot be moved to a past day")
            latest = session.scalar(
                select(func.max(DbStudyPlanSession.date)).where(
                    DbStudyPlanSession.plan_id == plan.id
                )
            )
            last_day = max(plan.week_start + timedelta(days=6), latest or plan.week_start)
            if to_date > last_day:
                raise StudyPlanMoveError(
                    "outside_week", "A session can only move within its own week"
                )
            row.date = to_date
            session.flush()
            return self._to_session_view(row, plan.subject_code)
```

Add `"StudyPlanMoveError",` to `__all__`, in alphabetical position.

- [ ] **Step 4: Run the tests and watch them pass.** Also run the whole repo file and the widget suite (K42, K46).

Run: `PYTHONPATH=$PWD pytest tests/test_study_plan_repo.py tests/test_widget_router.py tests/test_soft_delete_readers.py -q`
Expected: all pass. The repo file shows 9 new tests.

- [ ] **Step 5: Commit.**

```bash
pre-commit run --files lemely/db/study_plan_repo.py tests/test_study_plan_repo.py
git commit -S -m "feat(study-plan): move a session within its week and plan next week" -- lemely/db/study_plan_repo.py tests/test_study_plan_repo.py
```

---

### Task 2: Repo read: one week across subjects, with honest reasons

**Files:**
- Modify: `lemely/db/study_plan_repo.py` (imports, new dataclasses after `PlanView`, `get_week` after `get_current`, private readers after `_weekly_hours`, module function `_session_reasons`, `__all__`)
- Test: `tests/test_study_plan_repo.py` (append)

**Interfaces:**
- Consumes: Task 1's module.
- Produces:

```python
@dataclass(frozen=True, slots=True)
class SessionReason:
    kind: str  # "marks_lost" | "cards_due" | "last_paper"
    count: int

@dataclass(frozen=True, slots=True)
class WeakTopicView:
    topic: str
    accuracy_pct: int

@dataclass(frozen=True, slots=True)
class SubjectWeekView:
    subject_code: str
    plan: PlanView | None
    reasons: dict[uuid.UUID, SessionReason]
    paper_count: int
    weak_topics: list[WeakTopicView]

@dataclass(frozen=True, slots=True)
class WeekOverview:
    today: date
    week_start: date
    week_end: date
    subjects: list[SubjectWeekView]

StudyPlanService.get_week(student_id, subject_codes: Iterable[str], *, now: datetime | None = None) -> WeekOverview
```

- [ ] **Step 1: Write the failing tests.** Append this to `tests/test_study_plan_repo.py`. Add `Flashcard` and `CardSource` to the `lemely.db.models.flashcards` import, and `SessionReason` and `WeakTopicView` to the `lemely.db.study_plan_repo` import:

```python
# ---------------------------------------------------------------------------
# L9 · the week across subjects.
# ---------------------------------------------------------------------------


def _seed_card(
    sm: sessionmaker[Session], student_id: uuid.UUID, *, topic: str, due_at: datetime
) -> None:
    with sm.begin() as session:
        deck = session.scalars(
            sa.select(FlashcardDeck).where(
                FlashcardDeck.user_id == student_id, FlashcardDeck.topic == topic
            )
        ).first()
        assert deck is not None, "seed the deck first"
        position = session.scalar(
            sa.select(sa.func.count()).select_from(Flashcard).where(Flashcard.deck_id == deck.id)
        )
        session.add(
            Flashcard(
                deck_id=deck.id,
                front="Q",
                back="A",
                position=position or 0,
                source=CardSource.manual,
                due_at=due_at,
            )
        )


def _seed_paper(
    sm: sessionmaker[Session],
    student_id: uuid.UUID,
    *,
    subject_code: str = "0625",
    recorded_at: datetime,
    origin: AttemptOrigin = AttemptOrigin.past_paper,
) -> None:
    with sm.begin() as session:
        session.add(
            Attempt(
                user_id=student_id,
                subject_code=subject_code,
                awarded_marks=40,
                maximum_marks=80,
                percentage=50.0,
                recorded_at=recorded_at,
                origin=origin,
            )
        )


def test_get_week_reports_the_clock_week_and_subjects_in_the_given_order(
    pg_sessionmaker: sessionmaker[Session], study_plan_service: StudyPlanService
) -> None:
    student = _seed_user(pg_sessionmaker)
    _seed_weakness(pg_sessionmaker, student, topic="1 Motion", lost_marks=5)
    plan = study_plan_service.generate(student, "0625")

    week = study_plan_service.get_week(student, ["0625", "0580"])

    assert week.today == _WED
    assert week.week_start == _MON
    assert week.week_end == _SUN
    assert [s.subject_code for s in week.subjects] == ["0625", "0580"]
    assert week.subjects[0].plan is not None
    assert week.subjects[0].plan.id == plan.id
    # Inverse: a subject with no plan this week is listed with plan None, not dropped.
    assert week.subjects[1].plan is None
    assert week.subjects[1].reasons == {}


def test_get_week_returns_the_active_plan_not_a_superseded_one(
    pg_sessionmaker: sessionmaker[Session], study_plan_service: StudyPlanService
) -> None:
    student = _seed_user(pg_sessionmaker)
    _seed_weakness(pg_sessionmaker, student, topic="1 Motion", lost_marks=5)
    old = study_plan_service.generate(student, "0625")
    fresh = study_plan_service.generate(student, "0625")

    plan = study_plan_service.get_week(student, ["0625"]).subjects[0].plan

    assert plan is not None
    assert plan.id == fresh.id
    assert plan.id != old.id


def test_marks_lost_reason_sums_the_topics_lost_marks(
    pg_sessionmaker: sessionmaker[Session], study_plan_service: StudyPlanService
) -> None:
    student = _seed_user(pg_sessionmaker)
    _seed_profile(pg_sessionmaker, student, weekly_study_hours=1)
    _seed_weakness(pg_sessionmaker, student, topic="1 Motion", lost_marks=3)
    _seed_weakness(pg_sessionmaker, student, topic="1 Motion", lost_marks=4)
    plan = study_plan_service.generate(student, "0625")  # review (no bank, no deck)

    subject = study_plan_service.get_week(student, ["0625"]).subjects[0]

    assert plan.sessions
    for s in plan.sessions:
        assert subject.reasons[s.id] == SessionReason("marks_lost", 7)


def test_a_session_with_no_recorded_weakness_has_no_reason(
    pg_sessionmaker: sessionmaker[Session], study_plan_service: StudyPlanService
) -> None:
    """Confidence-only: the planner scheduled it, and nothing provable says why."""
    student = _seed_user(pg_sessionmaker)
    _seed_confidence(pg_sessionmaker, student, topic="2 Waves", rating=1)
    plan = study_plan_service.generate(student, "0625")

    subject = study_plan_service.get_week(student, ["0625"]).subjects[0]

    assert plan.sessions
    assert subject.reasons == {}


def test_cards_due_counts_cards_due_by_the_end_of_today(
    pg_sessionmaker: sessionmaker[Session], study_plan_service: StudyPlanService
) -> None:
    student = _seed_user(pg_sessionmaker)
    _seed_weakness(pg_sessionmaker, student, topic="1 Motion", lost_marks=5)
    _seed_flashcard_deck(pg_sessionmaker, student, topic="1 Motion")
    _seed_card(pg_sessionmaker, student, topic="1 Motion", due_at=_THIS_WEEK - timedelta(days=1))
    _seed_card(pg_sessionmaker, student, topic="1 Motion", due_at=_THIS_WEEK + timedelta(hours=2))
    _seed_card(pg_sessionmaker, student, topic="1 Motion", due_at=_THIS_WEEK + timedelta(days=1))
    plan = study_plan_service.generate(student, "0625")
    assert all(s.activity_type == StudyPlanActivityType.flashcards for s in plan.sessions)

    subject = study_plan_service.get_week(student, ["0625"]).subjects[0]

    assert {subject.reasons[s.id] for s in plan.sessions} == {SessionReason("cards_due", 2)}


def test_flashcards_with_nothing_due_fall_back_to_marks_lost(
    pg_sessionmaker: sessionmaker[Session], study_plan_service: StudyPlanService
) -> None:
    student = _seed_user(pg_sessionmaker)
    _seed_weakness(pg_sessionmaker, student, topic="1 Motion", lost_marks=5)
    _seed_flashcard_deck(pg_sessionmaker, student, topic="1 Motion")
    _seed_card(pg_sessionmaker, student, topic="1 Motion", due_at=_THIS_WEEK + timedelta(days=3))
    plan = study_plan_service.generate(student, "0625")

    subject = study_plan_service.get_week(student, ["0625"]).subjects[0]

    assert {subject.reasons[s.id] for s in plan.sessions} == {SessionReason("marks_lost", 5)}


def test_past_paper_reason_counts_days_since_the_last_paper(
    pg_sessionmaker: sessionmaker[Session], study_plan_service: StudyPlanService
) -> None:
    student = _seed_user(pg_sessionmaker)
    _seed_weakness(pg_sessionmaker, student, topic="1 Motion", lost_marks=5)
    _seed_bank_question(pg_sessionmaker, topic="1 Motion", source=QuestionSource.past_paper)
    _seed_paper(pg_sessionmaker, student, recorded_at=_THIS_WEEK - timedelta(days=9))
    plan = study_plan_service.generate(student, "0625")
    assert all(s.activity_type == StudyPlanActivityType.past_paper for s in plan.sessions)

    subject = study_plan_service.get_week(student, ["0625"]).subjects[0]

    assert {subject.reasons[s.id] for s in plan.sessions} == {SessionReason("last_paper", 9)}
    # The weakness attempt is a quiz and does not count as a paper.
    assert subject.paper_count == 1


def test_past_paper_with_no_paper_yet_falls_back_to_marks_lost(
    pg_sessionmaker: sessionmaker[Session], study_plan_service: StudyPlanService
) -> None:
    student = _seed_user(pg_sessionmaker)
    _seed_weakness(pg_sessionmaker, student, topic="1 Motion", lost_marks=5)
    _seed_bank_question(pg_sessionmaker, topic="1 Motion", source=QuestionSource.past_paper)
    plan = study_plan_service.generate(student, "0625")

    subject = study_plan_service.get_week(student, ["0625"]).subjects[0]

    assert {subject.reasons[s.id] for s in plan.sessions} == {SessionReason("marks_lost", 5)}
    assert subject.paper_count == 0


def test_paper_count_is_per_subject_and_excludes_quizzes(
    pg_sessionmaker: sessionmaker[Session], study_plan_service: StudyPlanService
) -> None:
    student = _seed_user(pg_sessionmaker)
    _seed_paper(pg_sessionmaker, student, recorded_at=_THIS_WEEK)
    _seed_paper(pg_sessionmaker, student, recorded_at=_THIS_WEEK, origin=AttemptOrigin.custom_paper)
    _seed_paper(pg_sessionmaker, student, recorded_at=_THIS_WEEK, origin=AttemptOrigin.quiz)
    _seed_paper(pg_sessionmaker, student, subject_code="0580", recorded_at=_THIS_WEEK)

    week = study_plan_service.get_week(student, ["0625", "0580"])

    assert [s.paper_count for s in week.subjects] == [2, 1]


def test_weak_topics_are_the_three_weakest_first_as_whole_percent(
    pg_sessionmaker: sessionmaker[Session], study_plan_service: StudyPlanService
) -> None:
    student = _seed_user(pg_sessionmaker)
    _seed_weakness(pg_sessionmaker, student, topic="A", lost_marks=6)  # 40%
    _seed_weakness(pg_sessionmaker, student, topic="B", lost_marks=4)  # 60%
    _seed_weakness(pg_sessionmaker, student, topic="C", lost_marks=1)  # 90%
    _seed_weakness(pg_sessionmaker, student, topic="D", lost_marks=5)  # 50%

    subject = study_plan_service.get_week(student, ["0625"]).subjects[0]

    assert subject.weak_topics == [
        WeakTopicView("A", 40),
        WeakTopicView("D", 50),
        WeakTopicView("B", 60),
    ]
```

- [ ] **Step 2: Run the tests and watch them fail.**

Run: `PYTHONPATH=$PWD pytest tests/test_study_plan_repo.py -q -k "get_week or reason or paper_count or weak_topics or cards_due or flashcards_with or past_paper_with"`
Expected: an ImportError on `SessionReason`.

- [ ] **Step 3: Implement.** In `lemely/db/study_plan_repo.py`:

Imports:

```python
from lemely.db.models.enums import AttemptOrigin, QuestionSource, QuizKind, QuizSubmissionStatus
from lemely.db.models.flashcards import Flashcard, FlashcardDeck
```

After `PlanView` add:

```python
@dataclass(frozen=True, slots=True)
class SessionReason:
    """Why a session is in the plan, stated only from rows that prove it.

    ``kind`` is one of:

    * ``"marks_lost"``: ``count`` is the topic's summed net lost marks.
    * ``"cards_due"``: ``count`` is the topic's cards due by the end of today.
    * ``"last_paper"``: ``count`` is the days since the subject's last marked paper.

    A session with no provable reason has no entry at all. The planner's
    placement and confidence signals are not recorded per session, so nothing
    here guesses at them.
    """

    kind: str
    count: int


@dataclass(frozen=True, slots=True)
class WeakTopicView:
    """One recorded weak topic for a subject, as a whole-number accuracy percent."""

    topic: str
    accuracy_pct: int


@dataclass(frozen=True, slots=True)
class SubjectWeekView:
    """One enrolled subject's current plan plus what the study-plan screen shows beside it."""

    subject_code: str
    plan: PlanView | None
    reasons: dict[uuid.UUID, SessionReason]
    paper_count: int
    weak_topics: list[WeakTopicView]


@dataclass(frozen=True, slots=True)
class WeekOverview:
    """Every requested subject's week, on one clock: ``today`` is ``now.date()`` (UTC)."""

    today: date
    week_start: date
    week_end: date
    subjects: list[SubjectWeekView]
```

After `get_current` add:

```python
    def get_week(
        self,
        student_id: uuid.UUID | str,
        subject_codes: Iterable[str],
        *,
        now: datetime | None = None,
    ) -> WeekOverview:
        """This ISO week across ``subject_codes``, in the order given.

        Each subject carries its active plan (or ``None``), the honest
        per-session reasons (:class:`SessionReason`), its marked-paper count
        and its three weakest recorded topics. Everything is read on the one
        injected clock, so ``today`` here and the plans' week agree.
        """
        student_uuid = _as_uuid(student_id)
        moment = now if now is not None else self._now()
        today = moment.date()
        week_start = _week_start(moment)
        subjects: list[SubjectWeekView] = []
        for code in subject_codes:
            plan = self.get_current(student_uuid, code, now=moment)
            with self._sessionmaker() as session:
                weaknesses = self._weaknesses(session, student_uuid, code)
                paper_count, last_paper_on = self._paper_stats(session, student_uuid, code)
                due = self._cards_due(session, student_uuid, code, today) if plan else {}
            reasons = (
                _session_reasons(plan, weaknesses, due, last_paper_on, today) if plan else {}
            )
            weakest = sorted(weaknesses, key=lambda w: (w.accuracy, w.topic))[:3]
            subjects.append(
                SubjectWeekView(
                    subject_code=code,
                    plan=plan,
                    reasons=reasons,
                    paper_count=paper_count,
                    weak_topics=[
                        WeakTopicView(topic=w.topic, accuracy_pct=round(w.accuracy * 100))
                        for w in weakest
                    ],
                )
            )
        return WeekOverview(
            today=today,
            week_start=week_start,
            week_end=week_start + timedelta(days=6),
            subjects=subjects,
        )
```

After `_weekly_hours` add:

```python
    def _paper_stats(
        self, session: Session, student_uuid: uuid.UUID, subject_code: str
    ) -> tuple[int, date | None]:
        """Marked papers (past or custom, never quizzes) for this subject: count and latest day."""
        count, latest = session.execute(
            select(func.count(Attempt.id), func.max(Attempt.recorded_at)).where(
                Attempt.user_id == student_uuid,
                Attempt.subject_code == subject_code,
                Attempt.origin.in_((AttemptOrigin.past_paper, AttemptOrigin.custom_paper)),
            )
        ).one()
        return int(count), (latest.astimezone(UTC).date() if latest is not None else None)

    def _cards_due(
        self, session: Session, student_uuid: uuid.UUID, subject_code: str, today: date
    ) -> dict[str, int]:
        """Cards due by the end of ``today`` (UTC), per deck topic, in the caller's own decks."""
        cutoff = datetime.combine(today + timedelta(days=1), time.min, tzinfo=UTC)
        rows = session.execute(
            select(FlashcardDeck.topic, func.count(Flashcard.id))
            .join(Flashcard, Flashcard.deck_id == FlashcardDeck.id)
            .where(
                FlashcardDeck.user_id == student_uuid,
                FlashcardDeck.subject_code == subject_code,
                Flashcard.due_at < cutoff,
            )
            .group_by(FlashcardDeck.topic)
        ).all()
        return {topic: int(n) for topic, n in rows if topic is not None}
```

Before `_as_uuid` add:

```python
def _session_reasons(
    plan: PlanView,
    weaknesses: list[WeakArea],
    cards_due: dict[str, int],
    last_paper_on: date | None,
    today: date,
) -> dict[uuid.UUID, SessionReason]:
    """The provable reason per session. See :class:`SessionReason`.

    Flashcards prefer "cards due" and past papers prefer "days since your last
    paper". Every activity falls back to the topic's lost marks, and a topic
    with none gets no reason.
    """
    lost = {w.topic: w.lost_marks for w in weaknesses}
    out: dict[uuid.UUID, SessionReason] = {}
    for s in plan.sessions:
        if s.activity_type is DbActivityType.flashcards and cards_due.get(s.topic, 0) > 0:
            out[s.id] = SessionReason("cards_due", cards_due[s.topic])
        elif s.activity_type is DbActivityType.past_paper and last_paper_on is not None:
            out[s.id] = SessionReason("last_paper", max(0, (today - last_paper_on).days))
        elif lost.get(s.topic, 0) > 0:
            out[s.id] = SessionReason("marks_lost", lost[s.topic])
    return out
```

Add `"SessionReason"`, `"SubjectWeekView"`, `"WeakTopicView"` and `"WeekOverview"` to `__all__`.

- [ ] **Step 4: Run the tests and watch them pass.**

Run: `PYTHONPATH=$PWD pytest tests/test_study_plan_repo.py tests/test_soft_delete_readers.py -q`
Expected: all pass.

- [ ] **Step 5: Commit.**

```bash
pre-commit run --files lemely/db/study_plan_repo.py tests/test_study_plan_repo.py
git commit -S -m "feat(study-plan): week overview across subjects with provable session reasons" -- lemely/db/study_plan_repo.py tests/test_study_plan_repo.py
```

---

### Task 3: Schemas and router: the week route, the move route, next week

**Files:**
- Modify: `lemely/web/schemas_study_plan.py`
- Modify: `lemely/web/routers/study_plan.py`
- Modify: `tests/test_authz_matrix_complete.py:501-503` (add two rows)
- Test: `tests/test_web_study_plan.py` (append)

**Interfaces:**
- Consumes: `StudyPlanService.get_week`, `.move_session`, `.generate(next_week=)`, `StudyPlanMoveError`, `SessionReason`, `WeekOverview` (Tasks 1–2). Also `StudentProfileService.list_enrolled_subject_codes` (`lemely/db/student_profile_repo.py:259`) and `get_student_profile_service` (`lemely/web/deps.py:834`).
- Produces (wire, camelCase):
  - `GET /api/student/study-plan` → `StudyPlanOverviewDTO {today, weekStart, weekEnd, subjects: SubjectWeekDTO[]}`
  - `SubjectWeekDTO {subjectCode, generated, plan: StudyPlanWeekDTO | null, paperCount, weakTopics: {topic, accuracyPct}[]}`
  - `StudyPlanSessionDTO` gains `anyDay: bool` (true for `past_paper`) and `reason: {kind, count} | null`. `reason` is only filled on the week route and is `null` elsewhere.
  - `POST /api/student/study-plan/sessions/{session_id}/move` with body `{date: "YYYY-MM-DD"}` → 200 `StudyPlanSessionDTO`. Errors:
    - 404: unknown or someone else's session (byte-identical)
    - 422: malformed id, or `detail.code` `past_day` / `outside_week`
    - 409: `detail.code` `completed` / `superseded`
  - `POST /api/student/study-plan` body gains `week: "current" | "next"` (default `"current"`).

- [ ] **Step 1: Write the failing tests.** Append this to `tests/test_web_study_plan.py`. Add the imports `from lemely.db.models.academic import Subject`, `from lemely.db.models.profiles import StudentSubjectEnrolment`, `from lemely.db.student_profile_repo import StudentProfileService`, and `get_student_profile_service` to the `lemely.web.deps` import:

```python
# ---------------------------------------------------------------------------
# L9 · the week across subjects, moving a session, planning next week.
# ---------------------------------------------------------------------------


def _enrol(sm: sessionmaker[Session], student_id: uuid.UUID, code: str) -> None:
    with sm.begin() as session:
        if session.get(Subject, code) is None:
            session.add(Subject(code=code, name=f"Subject {code}"))
            session.flush()
        session.add(StudentSubjectEnrolment(user_id=student_id, subject_code=code))


def _use_profile_service(client: TestClient, sm: sessionmaker[Session]) -> None:
    client.app.dependency_overrides[get_student_profile_service] = (  # type: ignore[union-attr]
        lambda: StudentProfileService(sm)
    )


def test_week_lists_every_enrolled_subject_in_one_call(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    study_plan_service: StudyPlanService,
) -> None:
    _use_study_plan_service(client, study_plan_service)
    _use_profile_service(client, pg_sessionmaker)
    student = _seed_user(pg_sessionmaker)
    _enrol(pg_sessionmaker, student, "0625")
    _enrol(pg_sessionmaker, student, "0580")
    _seed_weakness(pg_sessionmaker, student, topic="1 Motion", lost_marks=5)
    study_plan_service.generate(student, "0625")
    study_plan_service.generate(student, "9709")  # a plan for a subject they are not enrolled in
    _auth_as(client, student, Role.student)

    resp = client.get("/api/student/study-plan")

    assert resp.status_code == 200
    body = resp.json()
    assert body["today"] == "2026-08-05"
    assert body["weekStart"] == "2026-08-03"
    assert body["weekEnd"] == "2026-08-09"
    assert [s["subjectCode"] for s in body["subjects"]] == ["0580", "0625"]
    maths, physics = body["subjects"]
    assert maths == {
        "subjectCode": "0580",
        "generated": False,
        "plan": None,
        "paperCount": 0,
        "weakTopics": [],
    }
    assert physics["generated"] is True
    assert physics["weakTopics"] == [{"topic": "1 Motion", "accuracyPct": 50}]
    session = physics["plan"]["sessions"][0]
    assert session["anyDay"] is False
    assert session["reason"] == {"kind": "marks_lost", "count": 5}
    # Inverse: the un-enrolled subject's plan is not in the week.
    assert "9709" not in [s["subjectCode"] for s in body["subjects"]]


def test_week_is_owner_scoped(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    study_plan_service: StudyPlanService,
) -> None:
    _use_study_plan_service(client, study_plan_service)
    _use_profile_service(client, pg_sessionmaker)
    owner = _seed_user(pg_sessionmaker)
    other = _seed_user(pg_sessionmaker)
    for uid in (owner, other):
        _enrol(pg_sessionmaker, uid, "0625")
    _seed_weakness(pg_sessionmaker, owner, topic="1 Motion", lost_marks=5)
    study_plan_service.generate(owner, "0625")

    _auth_as(client, other, Role.student)
    assert client.get("/api/student/study-plan").json()["subjects"][0]["plan"] is None
    # Inverse: the owner sees it.
    _auth_as(client, owner, Role.student)
    assert client.get("/api/student/study-plan").json()["subjects"][0]["plan"] is not None


@pytest.mark.parametrize("role", [Role.teacher, Role.parent])
def test_week_route_rejects_non_students(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    study_plan_service: StudyPlanService,
    role: Role,
) -> None:
    _use_study_plan_service(client, study_plan_service)
    _use_profile_service(client, pg_sessionmaker)
    _auth_as(client, _seed_user(pg_sessionmaker, role), role)

    assert client.get("/api/student/study-plan").status_code == 403
    # Inverse.
    _auth_as(client, _seed_user(pg_sessionmaker), Role.student)
    assert client.get("/api/student/study-plan").status_code == 200


def _student_with_plan(
    client: TestClient, sm: sessionmaker[Session], service: StudyPlanService
) -> tuple[uuid.UUID, str]:
    _use_study_plan_service(client, service)
    student = _seed_user(sm)
    _seed_weakness(sm, student, topic="1 Motion", lost_marks=5)
    plan = service.generate(student, "0625")
    _auth_as(client, student, Role.student)
    return student, str(plan.sessions[0].id)


def test_move_owner_gets_the_new_date(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    study_plan_service: StudyPlanService,
) -> None:
    _, session_id = _student_with_plan(client, pg_sessionmaker, study_plan_service)

    resp = client.post(
        f"/api/student/study-plan/sessions/{session_id}/move", json={"date": "2026-08-09"}
    )

    assert resp.status_code == 200
    assert resp.json()["date"] == "2026-08-09"
    assert resp.json()["reason"] is None
    sessions = client.get("/api/student/study-plan/0625").json()["plan"]["sessions"]
    assert next(s for s in sessions if s["id"] == session_id)["date"] == "2026-08-09"


def test_move_unknown_and_other_students_sessions_are_byte_identical_404s(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    study_plan_service: StudyPlanService,
) -> None:
    _, session_id = _student_with_plan(client, pg_sessionmaker, study_plan_service)
    unknown = client.post(
        f"/api/student/study-plan/sessions/{uuid.uuid4()}/move", json={"date": "2026-08-09"}
    )
    _auth_as(client, _seed_user(pg_sessionmaker), Role.student)
    foreign = client.post(
        f"/api/student/study-plan/sessions/{session_id}/move", json={"date": "2026-08-09"}
    )

    assert unknown.status_code == foreign.status_code == 404
    assert unknown.content == foreign.content


def test_move_refusals_carry_a_machine_readable_code(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    study_plan_service: StudyPlanService,
) -> None:
    _, session_id = _student_with_plan(client, pg_sessionmaker, study_plan_service)
    url = f"/api/student/study-plan/sessions/{session_id}/move"

    past = client.post(url, json={"date": "2026-08-04"})
    assert past.status_code == 422
    assert past.json()["detail"]["code"] == "past_day"

    far = client.post(url, json={"date": "2026-09-30"})
    assert far.status_code == 422
    assert far.json()["detail"]["code"] == "outside_week"

    client.post(f"/api/student/study-plan/sessions/{session_id}/complete")
    done = client.post(url, json={"date": "2026-08-09"})
    assert done.status_code == 409
    assert done.json()["detail"]["code"] == "completed"


def test_move_with_a_malformed_id_or_date_is_422(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    study_plan_service: StudyPlanService,
) -> None:
    _, session_id = _student_with_plan(client, pg_sessionmaker, study_plan_service)

    bad_id = client.post(
        "/api/student/study-plan/sessions/not-a-uuid/move", json={"date": "2026-08-09"}
    )
    bad_date = client.post(
        f"/api/student/study-plan/sessions/{session_id}/move", json={"date": "Friday"}
    )

    assert bad_id.status_code == 422
    assert bad_date.status_code == 422


@pytest.mark.parametrize("role", [Role.teacher, Role.parent])
def test_move_route_rejects_non_students(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    study_plan_service: StudyPlanService,
    role: Role,
) -> None:
    _, session_id = _student_with_plan(client, pg_sessionmaker, study_plan_service)
    url = f"/api/student/study-plan/sessions/{session_id}/move"
    _auth_as(client, _seed_user(pg_sessionmaker, role), role)

    assert client.post(url, json={"date": "2026-08-09"}).status_code == 403


def test_post_week_next_plans_next_week_without_touching_this_one(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    study_plan_service: StudyPlanService,
) -> None:
    _use_study_plan_service(client, study_plan_service)
    student = _seed_user(pg_sessionmaker)
    _seed_weakness(pg_sessionmaker, student, topic="1 Motion", lost_marks=5)
    _auth_as(client, student, Role.student)

    nxt = client.post("/api/student/study-plan", json={"subjectCode": "0625", "week": "next"})

    assert nxt.status_code == 201
    assert nxt.json()["weekStart"] == "2026-08-10"
    assert client.get("/api/student/study-plan/0625").json()["generated"] is False
    # Inverse: the default is this week.
    cur = client.post("/api/student/study-plan", json={"subjectCode": "0625"})
    assert cur.json()["weekStart"] == "2026-08-03"
    # And an unknown value is refused.
    bad = client.post("/api/student/study-plan", json={"subjectCode": "0625", "week": "later"})
    assert bad.status_code == 422


def test_complete_still_returns_the_session_with_the_new_keys(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    study_plan_service: StudyPlanService,
) -> None:
    _, session_id = _student_with_plan(client, pg_sessionmaker, study_plan_service)

    resp = client.post(f"/api/student/study-plan/sessions/{session_id}/complete")

    assert resp.status_code == 200
    assert resp.json()["completedAt"] is not None
    assert resp.json()["anyDay"] is False
    assert resp.json()["reason"] is None
```

- [ ] **Step 2: Run the tests and watch them fail.**

Run: `PYTHONPATH=$PWD pytest tests/test_web_study_plan.py -q -k "week or move or new_keys"`
Expected: FAIL. `GET /api/student/study-plan` is 405 and `/move` is 404.

- [ ] **Step 3: Implement the schemas.** Change the `lemely/web/schemas_study_plan.py` import block and add or extend these classes:

```python
from __future__ import annotations

from datetime import date, datetime  # noqa: TC003 - pydantic needs the real type at runtime
from typing import Literal

from lemely.web.schemas import ApiModel


class SessionReasonDTO(ApiModel):
    """Why a session is in the plan, from rows that prove it (L9).

    ``count`` is marks lost (``marks_lost``), cards due by the end of today
    (``cards_due``), or days since the last marked paper (``last_paper``).
    """

    kind: Literal["marks_lost", "cards_due", "last_paper"]
    count: int
```

Add these two fields to the end of `StudyPlanSessionDTO`:

```python
    anyDay: bool = False
    """True for a past paper: the screen offers it on any day of the week."""
    reason: SessionReasonDTO | None = None
    """Filled on ``GET /api/student/study-plan`` only; ``None`` on every other route."""
```

Add this field to `CreateStudyPlanRequestDTO`:

```python
    week: Literal["current", "next"] = "current"
```

Append these classes:

```python
class WeakTopicDTO(ApiModel):
    topic: str
    accuracyPct: int


class SubjectWeekDTO(ApiModel):
    """One enrolled subject inside :class:`StudyPlanOverviewDTO`.

    ``generated``/``plan`` keep :class:`CurrentStudyPlanDTO`'s three states
    (no plan / refusal / real plan) per subject.
    """

    subjectCode: str
    generated: bool
    plan: StudyPlanWeekDTO | None
    paperCount: int
    weakTopics: list[WeakTopicDTO]


class StudyPlanOverviewDTO(ApiModel):
    """``GET /api/student/study-plan``: this ISO week across every enrolled subject (L9)."""

    today: date
    weekStart: date
    weekEnd: date
    subjects: list[SubjectWeekDTO]


class MoveSessionRequestDTO(ApiModel):
    date: date
```

- [ ] **Step 4: Implement the router.** In `lemely/web/routers/study_plan.py`, replace the imports and converters, extend `create_study_plan`, and add the two routes:

```python
from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, NoReturn

from fastapi import APIRouter, Depends, HTTPException

from lemely.db.models.enums import Role, XpSource
from lemely.db.models.study_plan import StudyPlanActivityType
from lemely.db.student_profile_repo import StudentProfileService  # noqa: TC001
from lemely.db.study_plan_repo import (
    StudyPlanError,
    StudyPlanMoveError,
    StudyPlanNotFoundError,
    StudyPlanOwnershipError,
    StudyPlanService,
)
from lemely.db.xp_repo import XpService
from lemely.web.deps import (
    AuthContext,
    get_student_profile_service,
    get_study_plan_service,
    get_xp_service,
    require_role,
)
from lemely.web.schemas_study_plan import (
    CreateStudyPlanRequestDTO,
    CurrentStudyPlanDTO,
    MoveSessionRequestDTO,
    SessionReasonDTO,
    StudyPlanOverviewDTO,
    StudyPlanSessionDTO,
    StudyPlanWeekDTO,
    SubjectWeekDTO,
    WeakTopicDTO,
)
from lemely.web.xp_awards import award_xp_safely

if TYPE_CHECKING:
    import uuid
    from collections.abc import Mapping

    from lemely.db.study_plan_repo import PlanView, SessionReason, SessionView, WeekOverview

#: Move refusals that describe the session's state (409) rather than a bad target (422).
_MOVE_CONFLICTS = frozenset({"completed", "superseded"})
```

```python
def _session_to_dto(
    session: SessionView, reason: SessionReason | None = None
) -> StudyPlanSessionDTO:
    return StudyPlanSessionDTO(
        id=str(session.id),
        date=session.date,
        topic=session.topic,
        activityType=session.activity_type.value,
        durationMinutes=session.duration_minutes,
        focus=session.focus,
        completedAt=session.completed_at,
        anyDay=session.activity_type is StudyPlanActivityType.past_paper,
        reason=SessionReasonDTO(kind=reason.kind, count=reason.count) if reason else None,  # type: ignore[arg-type]
    )


def _plan_to_dto(
    plan: PlanView, reasons: Mapping[uuid.UUID, SessionReason] | None = None
) -> StudyPlanWeekDTO:
    found = reasons or {}
    return StudyPlanWeekDTO(
        id=str(plan.id),
        subjectCode=plan.subject_code,
        weekStart=plan.week_start,
        weeklyHours=plan.weekly_hours,
        available=plan.available,
        reason=plan.reason,
        generatedAt=plan.generated_at,
        sessions=[_session_to_dto(s, found.get(s.id)) for s in plan.sessions],
    )


def _overview_to_dto(overview: WeekOverview) -> StudyPlanOverviewDTO:
    return StudyPlanOverviewDTO(
        today=overview.today,
        weekStart=overview.week_start,
        weekEnd=overview.week_end,
        subjects=[
            SubjectWeekDTO(
                subjectCode=s.subject_code,
                generated=s.plan is not None,
                plan=_plan_to_dto(s.plan, s.reasons) if s.plan is not None else None,
                paperCount=s.paper_count,
                weakTopics=[
                    WeakTopicDTO(topic=w.topic, accuracyPct=w.accuracy_pct) for w in s.weak_topics
                ],
            )
            for s in overview.subjects
        ],
    )
```

```python
@router.get("", response_model=StudyPlanOverviewDTO)
def get_study_plan_week(
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    service: Annotated[StudyPlanService, Depends(get_study_plan_service)],
    profile_service: Annotated[StudentProfileService, Depends(get_student_profile_service)],
) -> StudyPlanOverviewDTO:
    """This ISO week across every subject the caller is enrolled in (L9).

    Takes no parameters: identity and the subject list both come from the
    token's user. The service's injected clock decides "today" and the week,
    never this router (see commit 7ba50165 for what a second clock costs).
    """
    codes = profile_service.list_enrolled_subject_codes(auth.user_id)
    return _overview_to_dto(service.get_week(auth.user_id, codes))
```

In `create_study_plan`, replace the generate line with:

```python
    plan = service.generate(auth.user_id, body.subjectCode, next_week=body.week == "next")
```

```python
@router.post("/sessions/{session_id}/move", response_model=StudyPlanSessionDTO)
def move_study_plan_session(
    session_id: str,
    body: MoveSessionRequestDTO,
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    service: Annotated[StudyPlanService, Depends(get_study_plan_service)],
) -> StudyPlanSessionDTO:
    """Move one of the caller's own open sessions to another day of its week.

    404 (byte-identical) for an unknown or another student's id, 422 for a
    malformed id or a ``past_day``/``outside_week`` target, 409 for a
    ``completed`` or ``superseded`` session. Refusals carry
    ``{"code", "message"}`` so the screen can say which.
    """
    try:
        session = service.move_session(auth.user_id, session_id, body.date)
    except StudyPlanMoveError as exc:
        status = 409 if exc.code in _MOVE_CONFLICTS else 422
        raise HTTPException(
            status_code=status, detail={"code": exc.code, "message": str(exc)}
        ) from exc
    except StudyPlanError as exc:
        _raise_for(exc)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _session_to_dto(session)
```

The `reason=...` line has a `type: ignore[arg-type]` because `SessionReason.kind` is `str` and the DTO's is a `Literal`. If mypy in CI does not flag it, drop the ignore. Run `pre-commit` to find out.

In `tests/test_authz_matrix_complete.py`, next to the existing study-plan rows (`:501-503`), add:

```python
    ("GET", "/api/student/study-plan"): STUDENT,
    ("POST", "/api/student/study-plan/sessions/{session_id}/move"): STUDENT,
```

- [ ] **Step 5: Run the tests and watch them pass.**

Run: `PYTHONPATH=$PWD pytest tests/test_web_study_plan.py tests/test_authz_matrix_complete.py tests/test_widget_router.py tests/test_authz_matrix.py -q`
Expected: all pass.

- [ ] **Step 6: Commit.**

```bash
pre-commit run --files lemely/web/schemas_study_plan.py lemely/web/routers/study_plan.py tests/test_web_study_plan.py tests/test_authz_matrix_complete.py
git commit -S -m "feat(study-plan): week route across subjects, move route, plan next week" -- lemely/web/schemas_study_plan.py lemely/web/routers/study_plan.py tests/test_web_study_plan.py tests/test_authz_matrix_complete.py
```

---

# Frontend data layer

### Task 4: Types, cache patchers and hooks

**Files:**
- Modify: `web/src/lib/studyPlanTypes.ts` (append)
- Create: `web/src/lib/studyPlanCache.ts`
- Modify: `web/src/lib/hooks/useStudyPlanApi.ts`
- Test: `web/tests/unit/studyPlanCache.test.ts`

**Interfaces:**
- Consumes: the Task 3 wire.
- Produces:

```ts
// studyPlanTypes.ts
export type SessionReasonKind = "marks_lost" | "cards_due" | "last_paper"
export interface SessionReasonDTO { kind: SessionReasonKind; count: number }
// StudyPlanSessionDTO gains: anyDay: boolean; reason: SessionReasonDTO | null
export interface WeakTopicDTO { topic: string; accuracyPct: number }
export interface SubjectWeekDTO { subjectCode: string; generated: boolean; plan: StudyPlanWeekDTO | null; paperCount: number; weakTopics: WeakTopicDTO[] }
export interface StudyPlanOverviewDTO { today: string; weekStart: string; weekEnd: string; subjects: SubjectWeekDTO[] }
export interface MoveSessionRequest { date: string }
// CreateStudyPlanRequest gains: week?: "current" | "next"

// studyPlanCache.ts
export function patchOverviewSession(o: StudyPlanOverviewDTO | undefined, s: StudyPlanSessionDTO): StudyPlanOverviewDTO | undefined
export function patchCurrentSession(c: CurrentStudyPlanDTO | undefined, s: StudyPlanSessionDTO): CurrentStudyPlanDTO | undefined

// useStudyPlanApi.ts
export const studyPlanKeys: { all; week; current(code) }
export function useStudyPlanWeek(): UseQueryResult<StudyPlanOverviewDTO, Error>
export function useCompleteStudyPlanSession(): UseMutationResult<StudyPlanSessionDTO, Error, { sessionId: string; subjectCode: string }>
export function useMoveStudyPlanSession(): UseMutationResult<StudyPlanSessionDTO, Error, { sessionId: string; subjectCode: string; date: string }>
export function useRebuildStudyPlans(): UseMutationResult<StudyPlanWeekDTO[], Error, { subjectCodes: string[]; week?: "current" | "next" }>
```

- [ ] **Step 1: Write the failing test** at `web/tests/unit/studyPlanCache.test.ts`:

```ts
import { describe, expect, it } from "vitest"
import { patchCurrentSession, patchOverviewSession } from "@/lib/studyPlanCache"
import type {
  CurrentStudyPlanDTO,
  StudyPlanOverviewDTO,
  StudyPlanSessionDTO,
} from "@/lib/studyPlanTypes"

const s = (id: string, date: string, extra: Partial<StudyPlanSessionDTO> = {}): StudyPlanSessionDTO => ({
  id,
  date,
  topic: "Vectors",
  activityType: "practice",
  durationMinutes: 10,
  focus: "",
  completedAt: null,
  anyDay: false,
  reason: null,
  ...extra,
})

const overview = (sessions: StudyPlanSessionDTO[]): StudyPlanOverviewDTO => ({
  today: "2026-08-06",
  weekStart: "2026-08-03",
  weekEnd: "2026-08-09",
  subjects: [
    {
      subjectCode: "0580",
      generated: true,
      paperCount: 4,
      weakTopics: [],
      plan: {
        id: "p1",
        subjectCode: "0580",
        weekStart: "2026-08-03",
        weeklyHours: 2,
        available: true,
        reason: null,
        generatedAt: "2026-08-03T09:00:00Z",
        sessions,
      },
    },
    { subjectCode: "0625", generated: false, plan: null, paperCount: 0, weakTopics: [] },
  ],
})

describe("patchOverviewSession", () => {
  it("replaces the matching session with the server's copy", () => {
    const before = overview([s("a", "2026-08-06", { reason: { kind: "marks_lost", count: 9 } })])
    const server = s("a", "2026-08-06", { completedAt: "2026-08-06T10:00:00Z" })
    const after = patchOverviewSession(before, server)!
    const patched = after.subjects[0].plan!.sessions[0]
    expect(patched.completedAt).toBe("2026-08-06T10:00:00Z")
    // The server sends reason null on complete/move; the computed one stays.
    expect(patched.reason).toEqual({ kind: "marks_lost", count: 9 })
  })

  it("re-sorts by date after a move", () => {
    const before = overview([s("a", "2026-08-06"), s("b", "2026-08-07")])
    const after = patchOverviewSession(before, s("a", "2026-08-09"))!
    expect(after.subjects[0].plan!.sessions.map((x) => x.id)).toEqual(["b", "a"])
  })

  it("returns the same object when the id is not in the week", () => {
    const before = overview([s("a", "2026-08-06")])
    expect(patchOverviewSession(before, s("zzz", "2026-08-06"))).toBe(before)
  })

  it("passes undefined through", () => {
    expect(patchOverviewSession(undefined, s("a", "2026-08-06"))).toBeUndefined()
  })
})

describe("patchCurrentSession", () => {
  it("patches a per-subject plan and leaves a missing plan alone", () => {
    const current: CurrentStudyPlanDTO = { generated: true, plan: overview([s("a", "2026-08-06")]).subjects[0].plan }
    const after = patchCurrentSession(current, s("a", "2026-08-06", { completedAt: "x" }))!
    expect(after.plan!.sessions[0].completedAt).toBe("x")
    const none: CurrentStudyPlanDTO = { generated: false, plan: null }
    expect(patchCurrentSession(none, s("a", "2026-08-06"))).toBe(none)
  })
})
```

- [ ] **Step 2: Run the test and watch it fail.**

Run: `cd web && npx vitest run tests/unit/studyPlanCache.test.ts`
Expected: FAIL, because `@/lib/studyPlanCache` cannot be resolved.

- [ ] **Step 3: Implement the types.** In `web/src/lib/studyPlanTypes.ts`, add two fields to `StudyPlanSessionDTO` (after `completedAt`):

```ts
  /** True for a past paper: offered on any day of the week (L9). */
  anyDay: boolean
  /** Why this session is here, from rows that prove it. Only the week route
   * (`GET /api/student/study-plan`) fills it; complete and move return `null`,
   * and the cache patcher keeps the computed one. */
  reason: SessionReasonDTO | null
```

Add `week?: "current" | "next"` to `CreateStudyPlanRequest`, and append:

```ts
/** L9 · see `lemely/web/schemas_study_plan.py` `SessionReasonDTO`. */
export type SessionReasonKind = "marks_lost" | "cards_due" | "last_paper"

export interface SessionReasonDTO {
  kind: SessionReasonKind
  /** Marks lost, cards due by the end of today, or days since the last paper. */
  count: number
}

export interface WeakTopicDTO {
  topic: string
  accuracyPct: number
}

/** One enrolled subject in the week. `generated`/`plan` keep the three
 * per-subject states of `CurrentStudyPlanDTO`. */
export interface SubjectWeekDTO {
  subjectCode: string
  generated: boolean
  plan: StudyPlanWeekDTO | null
  paperCount: number
  weakTopics: WeakTopicDTO[]
}

/** `GET /api/student/study-plan`. `today` is the server's UTC day and the
 * only "today" the screen uses. */
export interface StudyPlanOverviewDTO {
  today: string
  weekStart: string
  weekEnd: string
  subjects: SubjectWeekDTO[]
}

export interface MoveSessionRequest {
  date: string
}
```

- [ ] **Step 4: Implement `web/src/lib/studyPlanCache.ts`:**

```ts
import type {
  CurrentStudyPlanDTO,
  StudyPlanOverviewDTO,
  StudyPlanSessionDTO,
} from "@/lib/studyPlanTypes"

/*
 * Pure cache patchers for the study-plan queries (L9). Kept out of the hooks
 * module so Vitest's node runner can import them without react-query.
 *
 * Every patch writes the session the SERVER returned (its completion
 * timestamp, its new date), never a client-side guess. The one field kept
 * from the cached copy is `reason`: complete and move return `null` there,
 * and the week route computed the real one.
 */

function merge(cached: StudyPlanSessionDTO, server: StudyPlanSessionDTO): StudyPlanSessionDTO {
  return { ...cached, ...server, reason: server.reason ?? cached.reason ?? null }
}

/** ISO dates sort lexically in calendar order; `sort` is stable, so ties keep order. */
function byDate(sessions: StudyPlanSessionDTO[]): StudyPlanSessionDTO[] {
  return [...sessions].sort((a, b) => a.date.localeCompare(b.date))
}

export function patchOverviewSession(
  overview: StudyPlanOverviewDTO | undefined,
  session: StudyPlanSessionDTO,
): StudyPlanOverviewDTO | undefined {
  if (!overview) return overview
  let changed = false
  const subjects = overview.subjects.map((subject) => {
    const plan = subject.plan
    if (!plan || !plan.sessions.some((s) => s.id === session.id)) return subject
    changed = true
    const sessions = byDate(plan.sessions.map((s) => (s.id === session.id ? merge(s, session) : s)))
    return { ...subject, plan: { ...plan, sessions } }
  })
  return changed ? { ...overview, subjects } : overview
}

export function patchCurrentSession(
  current: CurrentStudyPlanDTO | undefined,
  session: StudyPlanSessionDTO,
): CurrentStudyPlanDTO | undefined {
  if (!current?.plan) return current
  if (!current.plan.sessions.some((s) => s.id === session.id)) return current
  return {
    ...current,
    plan: {
      ...current.plan,
      sessions: byDate(current.plan.sessions.map((s) => (s.id === session.id ? merge(s, session) : s))),
    },
  }
}
```

- [ ] **Step 5: Implement the hooks.** Replace `web/src/lib/hooks/useStudyPlanApi.ts` with this. It keeps `useCurrentStudyPlan` and `useRebuildStudyPlan` until Task 14, because the old screens still import them:

```ts
import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query"
import { ApiError, request } from "@/lib/api"
import { patchCurrentSession, patchOverviewSession } from "@/lib/studyPlanCache"
import type {
  CreateStudyPlanRequest,
  CurrentStudyPlanDTO,
  StudyPlanOverviewDTO,
  StudyPlanSessionDTO,
  StudyPlanWeekDTO,
} from "@/lib/studyPlanTypes"

/*
 * React-query hooks for `/api/student/study-plan/*`. One hook per endpoint,
 * and no `fallback` passed to `request()`: a real failure surfaces as an
 * error the screen renders, never as empty data that would read as "no plan
 * yet".
 */

export const studyPlanKeys = {
  all: ["studyPlan"] as const,
  week: ["studyPlan", "week"] as const,
  current: (subjectCode: string) => ["studyPlan", "current", subjectCode] as const,
}

/** `GET /api/student/study-plan`: this week across every enrolled subject. */
export function useStudyPlanWeek(): UseQueryResult<StudyPlanOverviewDTO, Error> {
  return useQuery({
    queryKey: studyPlanKeys.week,
    queryFn: () => request<StudyPlanOverviewDTO>("/student/study-plan"),
  })
}

/** `GET /api/student/study-plan/{subjectCode}`. Deleted in Task 14 once no screen reads it. */
export function useCurrentStudyPlan(subjectCode: string): UseQueryResult<CurrentStudyPlanDTO, Error> {
  return useQuery({
    queryKey: studyPlanKeys.current(subjectCode),
    queryFn: () => request<CurrentStudyPlanDTO>(`/student/study-plan/${subjectCode}`),
    enabled: !!subjectCode,
  })
}

/** Single-subject rebuild used by the old week screen. Deleted in Task 14. */
export function useRebuildStudyPlan(): UseMutationResult<StudyPlanWeekDTO, Error, CreateStudyPlanRequest> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: CreateStudyPlanRequest) =>
      request<StudyPlanWeekDTO>("/student/study-plan", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: (plan) => {
      queryClient.setQueryData<CurrentStudyPlanDTO>(studyPlanKeys.current(plan.subjectCode), {
        generated: true,
        plan,
      })
      return queryClient.invalidateQueries({ queryKey: studyPlanKeys.week })
    },
  })
}

/**
 * Build or rebuild several subjects' plans, one POST each, in order.
 *
 * For the current week, each response is written to its per-subject cache
 * (wrapped as `{generated: true, plan}`, since a fresh refusal is still a
 * generated plan), then the week is refetched. A POST response carries no
 * reasons, paper counts or weak topics, so the week has to come from its own
 * route. Returning the invalidation promise keeps the mutation pending until
 * the refetch lands, which is what keeps the "Rebuilding…" banner up.
 * `week: "next"` writes nothing: next week is invisible until it starts.
 */
export function useRebuildStudyPlans(): UseMutationResult<
  StudyPlanWeekDTO[],
  Error,
  { subjectCodes: string[]; week?: "current" | "next" }
> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ subjectCodes, week = "current" }) => {
      const plans: StudyPlanWeekDTO[] = []
      for (const subjectCode of subjectCodes) {
        plans.push(
          await request<StudyPlanWeekDTO>("/student/study-plan", {
            method: "POST",
            body: JSON.stringify({ subjectCode, week } satisfies CreateStudyPlanRequest),
          }),
        )
      }
      return plans
    },
    onSuccess: (plans, { week = "current" }) => {
      if (week === "next") return undefined
      for (const plan of plans) {
        queryClient.setQueryData<CurrentStudyPlanDTO>(studyPlanKeys.current(plan.subjectCode), {
          generated: true,
          plan,
        })
      }
      return queryClient.invalidateQueries({ queryKey: studyPlanKeys.week })
    },
  })
}

/**
 * `POST /api/student/study-plan/sessions/{sessionId}/complete`. Idempotent
 * server-side. Patches both caches with the session the server returned.
 */
export function useCompleteStudyPlanSession(): UseMutationResult<
  StudyPlanSessionDTO,
  Error,
  { sessionId: string; subjectCode: string }
> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ sessionId }) =>
      request<StudyPlanSessionDTO>(`/student/study-plan/sessions/${sessionId}/complete`, { method: "POST" }),
    onSuccess: (session, { subjectCode }) => {
      queryClient.setQueryData<StudyPlanOverviewDTO>(studyPlanKeys.week, (o) => patchOverviewSession(o, session))
      queryClient.setQueryData<CurrentStudyPlanDTO>(studyPlanKeys.current(subjectCode), (c) =>
        patchCurrentSession(c, session),
      )
    },
  })
}

/**
 * `POST /api/student/study-plan/sessions/{sessionId}/move`. On a 409 (the
 * plan was rebuilt, or the session is already done) the week is refetched,
 * so the screen shows the truth rather than a stale row.
 */
export function useMoveStudyPlanSession(): UseMutationResult<
  StudyPlanSessionDTO,
  Error,
  { sessionId: string; subjectCode: string; date: string }
> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ sessionId, date }) =>
      request<StudyPlanSessionDTO>(`/student/study-plan/sessions/${sessionId}/move`, {
        method: "POST",
        body: JSON.stringify({ date }),
      }),
    onSuccess: (session, { subjectCode }) => {
      queryClient.setQueryData<StudyPlanOverviewDTO>(studyPlanKeys.week, (o) => patchOverviewSession(o, session))
      queryClient.setQueryData<CurrentStudyPlanDTO>(studyPlanKeys.current(subjectCode), (c) =>
        patchCurrentSession(c, session),
      )
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 409) {
        return queryClient.invalidateQueries({ queryKey: studyPlanKeys.week })
      }
      return undefined
    },
  })
}
```

- [ ] **Step 6: Run the test and typecheck.**

Run: `cd web && npx vitest run tests/unit/studyPlanCache.test.ts && npx tsc -p tsconfig.app.json --noEmit`
Expected: 5 passing, and no type errors. The two new required session fields may flag fixtures elsewhere. Fix any fixture that builds a `StudyPlanSessionDTO` by adding `anyDay: false, reason: null`. The old `studyPlan.test.ts` builds them and is deleted in Task 14, so patch it for now.

- [ ] **Step 7: Commit.**

```bash
cd web && npx oxlint src/lib/studyPlanCache.ts src/lib/hooks/useStudyPlanApi.ts src/lib/studyPlanTypes.ts && cd ..
pre-commit run --files web/src/lib/studyPlanTypes.ts web/src/lib/studyPlanCache.ts web/src/lib/hooks/useStudyPlanApi.ts web/tests/unit/studyPlanCache.test.ts
git commit -S -m "feat(web): study plan week, move and multi-subject rebuild hooks" -- web/src/lib/studyPlanTypes.ts web/src/lib/studyPlanCache.ts web/src/lib/hooks/useStudyPlanApi.ts web/tests/unit/studyPlanCache.test.ts
```

Add `web/tests/unit/studyPlan.test.ts` to the commit paths if Step 6 patched it.

---

### Task 5: `planCopy.ts`: strings, dates, reasons, start actions

**Files:**
- Create: `web/src/portals/student/screens/studyplan/planCopy.ts`
- Test: `web/tests/unit/studyPlanCopy.test.ts`

**Interfaces:**
- Consumes: `SessionReasonDTO`, `ActivityType` (Task 4). Also `StudentExamCalendar` (`web/src/lib/announcementTypes.ts:95`) and `daysUntil` (`web/src/lib/countdown.ts:17`).
- Produces:

```ts
export function activityLabel(activity: string): string
export function formatMinutes(minutes: number): string        // "10 min" | "1 h" | "1 h 55 min"
export function spokenMinutes(minutes: number): string        // "15 minutes" | "1 h 15 min"
export function parseDay(iso: string): Date
export function weekdayShort(iso: string): string             // "Thu"
export function weekdayLong(iso: string): string              // "Thursday"
export function addDays(iso: string, days: number): string
export function daysAgo(n: number): string                    // "today" | "yesterday" | "9 days ago"
export function reasonLine(reason: SessionReasonDTO | null | undefined): string | null
export function whyBody(input: { reason: SessionReasonDTO | null | undefined; topic: string; targetGrade: string | null }): string
export interface StartAction { label: string; path: string }
export function startAction(activity: string, subjectCode: string, reason: SessionReasonDTO | null | undefined): StartAction | null
export interface NextExam { date: string; paperNumber: number }
export function nextExamForSubject(calendar: StudentExamCalendar | undefined, subjectCode: string, today: Date): NextExam | null
export function examLine(exam: NextExam, today: Date): string // "Paper 4 in 188 days"
export function basedOnLine(paperCount: number): string
export function whyTopicsHint(subjectName: string, paperCount: number): string
export interface RefusalCopy { heading: string; body: string }
export function refusalCopy(reason: string | null): RefusalCopy
export const COPY: { ... }                                     // every fixed string, listed in the code below
```

- [ ] **Step 1: Write the failing test** at `web/tests/unit/studyPlanCopy.test.ts`:

```ts
import { describe, expect, it } from "vitest"
import type { StudentExamCalendar } from "@/lib/announcementTypes"
import {
  activityLabel,
  addDays,
  basedOnLine,
  daysAgo,
  examLine,
  formatMinutes,
  nextExamForSubject,
  reasonLine,
  refusalCopy,
  spokenMinutes,
  startAction,
  weekdayLong,
  weekdayShort,
  whyBody,
  whyTopicsHint,
} from "@/portals/student/screens/studyplan/planCopy"

const calendar = (entries: { code: string; paper: number; dates: string[] }[]): StudentExamCalendar => ({
  availability: "available",
  entries: entries.map((e) => ({
    subjectCode: e.code,
    sessionMonth: null,
    sessionYear: null,
    paperNumber: e.paper,
    availability: "dated",
    dates: e.dates.map((d) => ({ paperVariant: "42", examDate: d, startsAtLocal: null, durationMinutes: null, source: "t" })),
  })),
})
const THU = new Date("2026-08-06T12:00:00")

describe("labels and minutes", () => {
  it("labels activities and keeps an unknown one verbatim", () => {
    expect(activityLabel("practice")).toBe("Practice set")
    expect(activityLabel("flashcards")).toBe("Flashcards")
    expect(activityLabel("past_paper")).toBe("Past paper")
    expect(activityLabel("review")).toBe("Review")
    expect(activityLabel("mystery")).toBe("mystery")
  })
  it("formats minutes", () => {
    expect(formatMinutes(0)).toBe("0 min")
    expect(formatMinutes(10)).toBe("10 min")
    expect(formatMinutes(60)).toBe("1 h")
    expect(formatMinutes(115)).toBe("1 h 55 min")
    expect(spokenMinutes(1)).toBe("1 minute")
    expect(spokenMinutes(15)).toBe("15 minutes")
    expect(spokenMinutes(75)).toBe("1 h 15 min")
  })
})

describe("dates", () => {
  it("names weekdays from bare ISO dates without a timezone shift", () => {
    expect(weekdayShort("2026-08-06")).toBe("Thu")
    expect(weekdayLong("2026-08-06")).toBe("Thursday")
    expect(weekdayShort("not-a-date")).toBe("not-a-date")
  })
  it("adds days across a month end", () => {
    expect(addDays("2026-08-31", 1)).toBe("2026-09-01")
    expect(addDays("2026-08-06", -3)).toBe("2026-08-03")
  })
  it("says how long ago", () => {
    expect(daysAgo(0)).toBe("today")
    expect(daysAgo(1)).toBe("yesterday")
    expect(daysAgo(9)).toBe("9 days ago")
  })
})

describe("reasons", () => {
  it("writes the short row line per kind, singular and plural", () => {
    expect(reasonLine({ kind: "marks_lost", count: 9 })).toBe("Cost you 9 marks")
    expect(reasonLine({ kind: "marks_lost", count: 1 })).toBe("Cost you 1 mark")
    expect(reasonLine({ kind: "cards_due", count: 12 })).toBe("12 cards due")
    expect(reasonLine({ kind: "cards_due", count: 1 })).toBe("1 card due")
    expect(reasonLine({ kind: "last_paper", count: 9 })).toBe("Your last paper was 9 days ago")
    expect(reasonLine(null)).toBeNull()
  })
  it("writes the sheet's why, never guessing when there is no reason", () => {
    expect(whyBody({ reason: { kind: "marks_lost", count: 9 }, topic: "Vectors", targetGrade: "A*" })).toBe(
      "Vectors has cost you 9 marks so far. Win them back on the way to your A*.",
    )
    expect(whyBody({ reason: { kind: "marks_lost", count: 9 }, topic: "Vectors", targetGrade: null })).toBe(
      "Vectors has cost you 9 marks so far.",
    )
    expect(whyBody({ reason: { kind: "cards_due", count: 12 }, topic: "Waves", targetGrade: null })).toBe(
      "12 Waves cards are due today.",
    )
    expect(whyBody({ reason: { kind: "cards_due", count: 1 }, topic: "Waves", targetGrade: null })).toBe(
      "1 Waves card is due today.",
    )
    expect(whyBody({ reason: { kind: "last_paper", count: 9 }, topic: "x", targetGrade: null })).toBe(
      "A full paper keeps your timing sharp. Your last one was 9 days ago.",
    )
    expect(whyBody({ reason: null, topic: "x", targetGrade: "A" })).toBe(
      "Picked from your placement test or your topic ratings.",
    )
  })
})

describe("startAction", () => {
  it("routes each activity and offers nothing for review", () => {
    expect(startAction("practice", "0580", { kind: "marks_lost", count: 9 })).toEqual({
      label: "Start · +9 marks",
      path: "/student/practice/0580",
    })
    expect(startAction("practice", "0580", { kind: "marks_lost", count: 1 })?.label).toBe("Start · +1 mark")
    expect(startAction("practice", "0580", null)).toEqual({ label: "Start", path: "/student/practice/0580" })
    expect(startAction("flashcards", "0625", { kind: "cards_due", count: 12 })).toEqual({
      label: "Start · 12 cards",
      path: "/student/flashcards/0625",
    })
    expect(startAction("past_paper", "0625", null)).toEqual({ label: "Start", path: "/student/correct" })
    expect(startAction("review", "0625", { kind: "marks_lost", count: 3 })).toBeNull()
  })
})

describe("exams", () => {
  it("finds the soonest future date for one subject", () => {
    const cal = calendar([
      { code: "0580", paper: 2, dates: ["2027-03-01"] },
      { code: "0580", paper: 4, dates: ["2027-02-10", "2026-07-01"] },
      { code: "0625", paper: 4, dates: ["2026-09-01"] },
    ])
    expect(nextExamForSubject(cal, "0580", THU)).toEqual({ date: "2027-02-10", paperNumber: 4 })
    expect(nextExamForSubject(cal, "0606", THU)).toBeNull()
    expect(nextExamForSubject(undefined, "0580", THU)).toBeNull()
  })
  it("words the countdown", () => {
    expect(examLine({ date: "2027-02-10", paperNumber: 4 }, THU)).toBe("Paper 4 in 188 days")
    expect(examLine({ date: "2026-08-06", paperNumber: 2 }, THU)).toBe("Paper 2 today")
    expect(examLine({ date: "2026-08-07", paperNumber: 2 }, THU)).toBe("Paper 2 tomorrow")
  })
})

describe("plan lines", () => {
  it("says what the plan is built from", () => {
    expect(basedOnLine(4)).toBe("Built from your 4 papers and weak topics")
    expect(basedOnLine(1)).toBe("Built from your 1 paper and weak topics")
    expect(basedOnLine(0)).toBe("Built from your weak topics and ratings")
    expect(whyTopicsHint("Mathematics", 4)).toBe("Your weakest Mathematics topics from 4 papers.")
    expect(whyTopicsHint("Mathematics", 0)).toBe("Your weakest Mathematics topics so far.")
  })
  it("words each refusal, naming the unknown one rather than hiding it", () => {
    expect(refusalCopy("no_signal").heading).toBe("I need a paper first")
    expect(refusalCopy("quota").heading).toBe("I couldn’t plan this week")
    expect(refusalCopy(null).heading).toBe("I couldn’t plan this week")
  })
})
```

- [ ] **Step 2: Run the test and watch it fail.**

Run: `cd web && npx vitest run tests/unit/studyPlanCopy.test.ts`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement `planCopy.ts`:**

```ts
/*
 * L9 · every string and date rule the study plan shows. Pure: no React and
 * no DOM. Vitest runs it in node.
 *
 * Copy follows the approved mock (`.impeccable/mocks/student-r2/sp.js`) with
 * two deliberate edits, both listed in the PR:
 *   - no "!" anywhere, because `npm run check:copy` bans it in product copy;
 *   - "Cost you 9 marks", not "on Paper 4", because the reason is summed over
 *     every paper and naming one would be false precision.
 */

import type { StudentExamCalendar } from "@/lib/announcementTypes"
import { daysUntil } from "@/lib/countdown"
import type { ActivityType, SessionReasonDTO } from "@/lib/studyPlanTypes"

const plural = (n: number, one: string, many: string) => (n === 1 ? one : many)

const ACTIVITY_LABELS: Record<ActivityType, string> = {
  practice: "Practice set",
  flashcards: "Flashcards",
  past_paper: "Past paper",
  review: "Review",
}

/** An unknown activity from a newer backend renders verbatim, never remapped. */
export function activityLabel(activity: string): string {
  return ACTIVITY_LABELS[activity as ActivityType] ?? activity
}

export function formatMinutes(minutes: number): string {
  if (minutes < 60) return `${minutes} min`
  const hours = Math.floor(minutes / 60)
  const rest = minutes % 60
  return rest === 0 ? `${hours} h` : `${hours} h ${rest} min`
}

/** Binny's spoken form ("15 minutes today."). */
export function spokenMinutes(minutes: number): string {
  return minutes < 60 ? `${minutes} ${plural(minutes, "minute", "minutes")}` : formatMinutes(minutes)
}

/** A bare `YYYY-MM-DD` as LOCAL midnight. `new Date("2026-08-06")` is UTC
 * midnight, which shows as the 5th west of Greenwich (K21). */
export function parseDay(iso: string): Date {
  return new Date(`${iso}T00:00:00`)
}

function weekday(iso: string, style: "short" | "long"): string {
  const d = parseDay(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString("en-GB", { weekday: style })
}

export const weekdayShort = (iso: string) => weekday(iso, "short")
export const weekdayLong = (iso: string) => weekday(iso, "long")

export function addDays(iso: string, days: number): string {
  const d = parseDay(iso)
  d.setDate(d.getDate() + days)
  const mm = String(d.getMonth() + 1).padStart(2, "0")
  const dd = String(d.getDate()).padStart(2, "0")
  return `${d.getFullYear()}-${mm}-${dd}`
}

export function daysAgo(n: number): string {
  if (n <= 0) return "today"
  if (n === 1) return "yesterday"
  return `${n} days ago`
}

/** The short reason under a row. `null` when nothing proves one. */
export function reasonLine(reason: SessionReasonDTO | null | undefined): string | null {
  if (!reason) return null
  switch (reason.kind) {
    case "marks_lost":
      return `Cost you ${reason.count} ${plural(reason.count, "mark", "marks")}`
    case "cards_due":
      return `${reason.count} ${plural(reason.count, "card", "cards")} due`
    case "last_paper":
      return `Your last paper was ${daysAgo(reason.count)}`
  }
}

/** The sheet's "Why this?" body. The no-reason line is true by
 * construction: with no weakness behind it, the planner's other two inputs
 * are placement and ratings, and which one is not recorded (K26). */
export function whyBody(input: {
  reason: SessionReasonDTO | null | undefined
  topic: string
  targetGrade: string | null
}): string {
  const { reason, topic, targetGrade } = input
  if (!reason) return "Picked from your placement test or your topic ratings."
  switch (reason.kind) {
    case "marks_lost": {
      const base = `${topic} has cost you ${reason.count} ${plural(reason.count, "mark", "marks")} so far.`
      return targetGrade ? `${base} Win them back on the way to your ${targetGrade}.` : base
    }
    case "cards_due":
      return reason.count === 1
        ? `1 ${topic} card is due today.`
        : `${reason.count} ${topic} cards are due today.`
    case "last_paper":
      return `A full paper keeps your timing sharp. Your last one was ${daysAgo(reason.count)}.`
  }
}

export interface StartAction {
  label: string
  path: string
}

/** `null` for review: nothing in the product renders revision material, so a
 * Start button would go nowhere (K28). */
export function startAction(
  activity: string,
  subjectCode: string,
  reason: SessionReasonDTO | null | undefined,
): StartAction | null {
  switch (activity) {
    case "practice":
      return {
        label:
          reason?.kind === "marks_lost"
            ? `Start · +${reason.count} ${plural(reason.count, "mark", "marks")}`
            : "Start",
        path: `/student/practice/${subjectCode}`,
      }
    case "flashcards":
      return {
        label: reason?.kind === "cards_due" ? `Start · ${reason.count} ${plural(reason.count, "card", "cards")}` : "Start",
        path: `/student/flashcards/${subjectCode}`,
      }
    case "past_paper":
      return { label: "Start", path: "/student/correct" }
    default:
      return null
  }
}

export interface NextExam {
  date: string
  paperNumber: number
}

/** The soonest future exam date for one subject, from the same calendar the
 * Announcements countdown reads (K9). */
export function nextExamForSubject(
  calendar: StudentExamCalendar | undefined,
  subjectCode: string,
  today: Date,
): NextExam | null {
  if (!calendar) return null
  let best: (NextExam & { days: number }) | null = null
  for (const entry of calendar.entries) {
    if (entry.subjectCode !== subjectCode) continue
    for (const d of entry.dates) {
      const days = daysUntil(d.examDate, today)
      if (days < 0) continue
      if (best === null || days < best.days) best = { date: d.examDate, paperNumber: entry.paperNumber, days }
    }
  }
  return best ? { date: best.date, paperNumber: best.paperNumber } : null
}

export function examLine(exam: NextExam, today: Date): string {
  const days = daysUntil(exam.date, today)
  const when = days === 0 ? "today" : days === 1 ? "tomorrow" : `in ${days} days`
  return `Paper ${exam.paperNumber} ${when}`
}

export function basedOnLine(paperCount: number): string {
  return paperCount > 0
    ? `Built from your ${paperCount} ${plural(paperCount, "paper", "papers")} and weak topics`
    : "Built from your weak topics and ratings"
}

export function whyTopicsHint(subjectName: string, paperCount: number): string {
  return paperCount > 0
    ? `Your weakest ${subjectName} topics from ${paperCount} ${plural(paperCount, "paper", "papers")}.`
    : `Your weakest ${subjectName} topics so far.`
}

export interface RefusalCopy {
  heading: string
  body: string
}

/** One message per refusal reason. An unknown reason still gets its own
 * heading, never the no-signal one (K4). */
export function refusalCopy(reason: string | null): RefusalCopy {
  if (reason === "no_signal") {
    return {
      heading: "I need a paper first",
      body: "Mark one past paper, or take the 10-minute placement test, and I’ll plan your week.",
    }
  }
  return { heading: "I couldn’t plan this week", body: "Mark a paper or take the placement test, then rebuild." }
}

/** Every fixed string on the screen, in one place for review and the copy gate. */
export const COPY = {
  title: "This week",
  noPlanSub: "No plan yet",
  anyDay: "Any day this week",
  later: "Later this week",
  whyTopics: "Why these topics",
  whyThis: "Why this?",
  markDone: "Mark done",
  saving: "Saving…",
  tryAgain: "Try again",
  done: "Done",
  move: "Move",
  moveToday: "Move to today",
  moveAllToday: "Move all to today",
  moving: "Moving…",
  rebuild: "Rebuild",
  rebuilding: "Rebuilding…",
  rebuildingTitle: "Rebuilding your week…",
  rebuildingBody: "Using your latest papers.",
  completeError: "Couldn’t mark this done. Check your connection and try again.",
  moveError: "Couldn’t move it. Try again.",
  moveSuperseded: "Your plan was rebuilt. Here’s the new one.",
  moveCompleted: "That one’s already done.",
  notInWeek: "That session isn’t in this week’s plan. Your plan was rebuilt.",
  firstRunTitle: "Let’s plan your week",
  firstRunBody: "Lemely builds it from your papers and weak topics. Takes a second.",
  firstRunCta: "Build my week",
  building: "Building…",
  walk: [
    { title: "Short sessions", body: "10 minutes of practice, 5 of flashcards." },
    { title: "Weakest topics first", body: "The ones that cost you the most marks." },
    { title: "Rebuilt each week", body: "Every new paper sharpens the plan." },
  ],
  needPaperCta: "Scan a paper",
  placementCta: "Take the placement test",
  nothingTitle: "Nothing to plan this week",
  nothingBody: "You’re on top of it. Practise to stay sharp.",
  nothingCta: "Practise",
  noSubjectsTitle: "Pick your subjects",
  noSubjectsBody: "Your plan is built per subject.",
  noSubjectsCta: "Add subjects",
  weekDoneTitle: "Week done.",
  planNextWeek: "Plan next week",
  nextWeekReady: "Next week is ready for Monday",
  bonusPractice: "Bonus practice",
  loadErrorTitle: "We couldn’t load your week",
  loadErrorBody: "Check your connection, then try again.",
  backHome: "Back to Home",
  rebuildConfirmTitle: "Rebuild your week?",
  rebuildConfirmBody: "Your plan starts fresh. Done sessions keep their XP.",
  rebuildConfirmCta: "Rebuild",
  rebuildKeep: "Keep this week",
} as const
```

- [ ] **Step 4: Run the test and watch it pass.**

Run: `cd web && npx vitest run tests/unit/studyPlanCopy.test.ts`
Expected: all pass.

- [ ] **Step 5: Commit.**

```bash
pre-commit run --files web/src/portals/student/screens/studyplan/planCopy.ts web/tests/unit/studyPlanCopy.test.ts
git commit -S -m "feat(web): study plan copy and date rules" -- web/src/portals/student/screens/studyplan/planCopy.ts web/tests/unit/studyPlanCopy.test.ts
```

---

### Task 6: `planModel.ts`: state selection and sections

**Files:**
- Create: `web/src/portals/student/screens/studyplan/planModel.ts`
- Test: `web/tests/unit/studyPlanModel.test.ts`

**Interfaces:**
- Consumes: Task 4 types and Task 5 `planCopy`.
- Produces (the exact names the screen tasks use):

```ts
export type SessionStatus = "done" | "missed" | "today" | "later" | "anyDay"
export interface MoveDay { date: string; label: string }
export interface SessionVM {
  id: string; subjectCode: string; subjectName: string; dotIndex: number
  activity: string; activityLabel: string; title: string; minutes: number; minutesLabel: string
  date: string; dayShort: string; anyDay: boolean; status: SessionStatus
  why: string | null; whyBody: string; start: StartAction | null
  canMove: boolean; moveDays: MoveDay[]
}
export interface DayCell { date: string; letter: string; label: string; count: number; isToday: boolean; allDone: boolean; hasMissed: boolean }
export interface FilterChip { code: string | null; label: string; dotIndex: number | null; selected: boolean }
export interface HeaderModel { title: string; sub: string; examDate: string | null; filters: FilterChip[] }
export interface PendingSubject { subjectCode: string; subjectName: string; kind: "notGenerated" | "refused" }
export interface DayGroup { date: string; label: string; sessions: SessionVM[] }
export interface PlanBody {
  ring: [number, number, number]; ringLabel: string
  today: { date: string; heading: string; sub: string; sessions: SessionVM[] }
  missed: SessionVM[]
  week: { show: boolean; days: DayCell[]; anyDay: SessionVM[] }
  later: DayGroup[]
  done: { count: number; title: string; daysLabel: string; openByDefault: boolean; sessions: SessionVM[] }
  basedOn: string
  subjectTop: { targetGrade: string | null; exam: string | null } | null
  whyTopics: { topic: string; pct: number; tone: "w" | "m" }[]
  whyHint: string | null
  pending: PendingSubject[]
  firstOpenId: string | null
  binnyLine: string
}
export interface WeekDoneStat { value: string; label: string; tone: "ok" | "primary" }
export type PlanScreen =
  | { kind: "noSubjects" }
  | { kind: "firstRun"; header: HeaderModel; codesToBuild: string[] }
  | { kind: "needPaper"; header: HeaderModel; placementCode: string; copy: RefusalCopy }
  | { kind: "nothingScheduled"; header: HeaderModel; practiceCode: string; basedOn: string; scopeCodes: string[]; pending: PendingSubject[] }
  | { kind: "weekDone"; header: HeaderModel; body: string; stats: WeekDoneStat[]; practiceCode: string; scopeCodes: string[]; all: SessionVM[] }
  | { kind: "plan"; header: HeaderModel; body: PlanBody; scopeCodes: string[]; all: SessionVM[] }
export interface PlanModelInput {
  overview: StudyPlanOverviewDTO
  filter: string | null
  subjectName: (code: string) => string
  targetGrade: (code: string) => string | null
  nextExam: (code: string) => NextExam | null
  now: Date
  xp: { weekXp: number; streak: number } | null
}
export function resolveFilter(overview: StudyPlanOverviewDTO, code: string | undefined): string | null
export function planScreen(input: PlanModelInput): PlanScreen
export function ringParts(sessions: SessionVM[], today: string): [number, number, number]
```

- [ ] **Step 1: Write the failing test** at `web/tests/unit/studyPlanModel.test.ts`. The fixture mirrors the mock's week (`sp.js` `S`) on Thursday 2026-08-06:

```ts
import { describe, expect, it } from "vitest"
import type {
  StudyPlanOverviewDTO,
  StudyPlanSessionDTO,
  StudyPlanWeekDTO,
  SubjectWeekDTO,
} from "@/lib/studyPlanTypes"
import { planScreen, resolveFilter, ringParts, type PlanModelInput } from "@/portals/student/screens/studyplan/planModel"

const S = (id: string, date: string, extra: Partial<StudyPlanSessionDTO> = {}): StudyPlanSessionDTO => ({
  id, date, topic: id, activityType: "practice", durationMinutes: 10, focus: "", completedAt: null,
  anyDay: false, reason: null, ...extra,
})
const P = (code: string, sessions: StudyPlanSessionDTO[], extra: Partial<StudyPlanWeekDTO> = {}): StudyPlanWeekDTO => ({
  id: `plan-${code}`, subjectCode: code, weekStart: "2026-08-03", weeklyHours: 2, available: true, reason: null,
  generatedAt: "2026-08-03T09:00:00Z", sessions, ...extra,
})
const SUB = (code: string, plan: StudyPlanWeekDTO | null, extra: Partial<SubjectWeekDTO> = {}): SubjectWeekDTO => ({
  subjectCode: code, generated: plan !== null, plan, paperCount: 4, weakTopics: [], ...extra,
})
const O = (subjects: SubjectWeekDTO[], extra: Partial<StudyPlanOverviewDTO> = {}): StudyPlanOverviewDTO => ({
  today: "2026-08-06", weekStart: "2026-08-03", weekEnd: "2026-08-09", subjects, ...extra,
})
const DONE = "2026-08-04T10:00:00Z"
const NAMES: Record<string, string> = { "0580": "Mathematics", "0606": "Additional Maths", "0625": "Physics" }

function mockWeek(): StudyPlanOverviewDTO {
  return O([
    SUB("0580", P("0580", [
      S("Algebra", "2026-08-03", { completedAt: DONE, reason: { kind: "marks_lost", count: 7 } }),
      S("Vectors", "2026-08-06", { reason: { kind: "marks_lost", count: 9 } }),
      S("Trigonometry", "2026-08-07", { reason: { kind: "marks_lost", count: 5 } }),
    ]), { weakTopics: [{ topic: "Vectors", accuracyPct: 41 }, { topic: "Algebra", accuracyPct: 58 }, { topic: "Trigonometry", accuracyPct: 62 }] }),
    SUB("0606", P("0606", [
      S("Quadratic inequalities", "2026-08-05", { reason: { kind: "marks_lost", count: 6 } }),
      S("Functions", "2026-08-08", { activityType: "flashcards", durationMinutes: 5, reason: { kind: "cards_due", count: 9 } }),
    ])),
    SUB("0625", P("0625", [
      S("Forces", "2026-08-04", { activityType: "flashcards", durationMinutes: 5, completedAt: DONE }),
      S("Waves", "2026-08-06", { activityType: "flashcards", durationMinutes: 5, reason: { kind: "cards_due", count: 12 } }),
      S("0625/42", "2026-08-06", { activityType: "past_paper", durationMinutes: 45, anyDay: true, reason: { kind: "last_paper", count: 9 } }),
    ])),
  ])
}

function input(overview: StudyPlanOverviewDTO, extra: Partial<PlanModelInput> = {}): PlanModelInput {
  return {
    overview,
    filter: null,
    subjectName: (c) => NAMES[c] ?? c,
    targetGrade: (c) => (c === "0580" ? "A*" : null),
    nextExam: (c) => (c === "0580" ? { date: "2027-02-10", paperNumber: 4 } : c === "0625" ? { date: "2027-02-01", paperNumber: 4 } : null),
    now: new Date("2026-08-06T12:00:00"),
    xp: { weekXp: 260, streak: 7 },
    ...extra,
  }
}

function asPlan(screen: ReturnType<typeof planScreen>) {
  if (screen.kind !== "plan") throw new Error(`expected plan, got ${screen.kind}`)
  return screen
}

describe("state selection", () => {
  it("noSubjects when the student is enrolled in nothing", () => {
    expect(planScreen(input(O([]))).kind).toBe("noSubjects")
  })
  it("firstRun when no subject has a plan, building every subject", () => {
    const s = planScreen(input(O([SUB("0580", null), SUB("0625", null)])))
    expect(s.kind).toBe("firstRun")
    if (s.kind === "firstRun") {
      expect(s.codesToBuild).toEqual(["0580", "0625"])
      expect(s.header.sub).toBe("No plan yet")
    }
  })
  it("firstRun builds only the missing subjects when the rest were refused", () => {
    const s = planScreen(input(O([SUB("0580", null), SUB("0625", P("0625", [], { available: false, reason: "no_signal" }))])))
    expect(s.kind === "firstRun" && s.codesToBuild).toEqual(["0580"])
  })
  it("needPaper when every plan is a refusal", () => {
    const s = planScreen(input(O([SUB("0625", P("0625", [], { available: false, reason: "no_signal" }))])))
    expect(s.kind).toBe("needPaper")
    if (s.kind === "needPaper") {
      expect(s.placementCode).toBe("0625")
      expect(s.copy.heading).toBe("I need a paper first")
    }
  })
  it("an unknown refusal reason keeps its own copy", () => {
    const s = planScreen(input(O([SUB("0625", P("0625", [], { available: false, reason: "quota" }))])))
    expect(s.kind === "needPaper" && s.copy.heading).toBe("I couldn’t plan this week")
  })
  it("nothingScheduled for a real plan with zero sessions", () => {
    const s = planScreen(input(O([SUB("0625", P("0625", []))])))
    expect(s.kind).toBe("nothingScheduled")
    expect(s.kind === "nothingScheduled" && s.practiceCode).toBe("0625")
  })
  it("weekDone when every session is done, with real XP and streak", () => {
    const s = planScreen(input(O([SUB("0625", P("0625", [S("a", "2026-08-04", { completedAt: DONE }), S("b", "2026-08-05", { completedAt: DONE, durationMinutes: 45 })]))])))
    expect(s.kind).toBe("weekDone")
    if (s.kind === "weekDone") {
      expect(s.body).toBe("All 2 sessions, 55 min.")
      expect(s.stats).toEqual([
        { value: "2", label: "sessions", tone: "ok" },
        { value: "+260", label: "XP", tone: "primary" },
        { value: "7", label: "days in a row", tone: "ok" },
      ])
      expect(s.header.sub).toBe("2 of 2 done · 55 min")
    }
  })
  it("weekDone without XP shows only what is known", () => {
    const s = planScreen(input(O([SUB("0625", P("0625", [S("a", "2026-08-04", { completedAt: DONE })]))]), { xp: null }))
    expect(s.kind === "weekDone" && s.stats).toEqual([{ value: "1", label: "session", tone: "ok" }])
  })
})

describe("the all-subjects week (WA)", () => {
  const screen = asPlan(planScreen(input(mockWeek())))
  const b = screen.body

  it("sums the header and lists the filter chips", () => {
    expect(screen.header.title).toBe("This week")
    expect(screen.header.sub).toBe("2 of 8 done · 1 h 40 min")
    expect(screen.header.examDate).toBe("2027-02-01")
    expect(screen.header.filters.map((f) => [f.label, f.selected, f.dotIndex])).toEqual([
      ["All", true, null], ["Mathematics", false, 0], ["Additional Maths", false, 1], ["Physics", false, 2],
    ])
  })
  it("puts today first, with the open sessions and a ring", () => {
    expect(b.today.heading).toBe("Today · Thursday")
    expect(b.today.sub).toBe("2 sessions · 15 min")
    expect(b.today.sessions.map((s) => s.title)).toEqual(["Vectors", "Waves"])
    expect(b.ring).toEqual([0, 0, 0])
    expect(b.ringLabel).toBe("Today: 0 of 3 goals done")
  })
  it("writes each row's reason and start action", () => {
    const [vectors, waves] = b.today.sessions
    expect(vectors.why).toBe("Cost you 9 marks")
    expect(vectors.start).toEqual({ label: "Start · +9 marks", path: "/student/practice/0580" })
    expect(vectors.whyBody).toBe("Vectors has cost you 9 marks so far. Win them back on the way to your A*.")
    expect(waves.why).toBe("12 cards due")
    expect(waves.subjectName).toBe("Physics")
    expect(waves.dotIndex).toBe(2)
  })
  it("lists missed sessions with today as a move day", () => {
    expect(b.missed.map((s) => [s.title, s.dayShort])).toEqual([["Quadratic inequalities", "Wed"]])
    expect(b.missed[0].moveDays.map((d) => d.label)).toEqual(["Today", "Fri", "Sat", "Sun"])
  })
  it("offers a today session every later day, never its own", () => {
    expect(b.today.sessions[0].moveDays.map((d) => d.label)).toEqual(["Fri", "Sat", "Sun"])
    expect(b.today.sessions[0].canMove).toBe(true)
  })
  it("draws the Mon–Sun strip and the any-day list", () => {
    expect(b.week.show).toBe(true)
    expect(b.week.days.map((d) => [d.letter, d.count, d.isToday, d.allDone, d.hasMissed])).toEqual([
      ["M", 1, false, true, false], ["T", 1, false, true, false], ["W", 1, false, false, true],
      ["T", 3, true, false, false], ["F", 1, false, false, false], ["S", 1, false, false, false], ["S", 0, false, false, false],
    ])
    expect(b.week.anyDay.map((s) => s.title)).toEqual(["0625/42"])
    expect(b.week.anyDay[0].canMove).toBe(false)
    expect(b.week.anyDay[0].why).toBe("Your last paper was 9 days ago")
  })
  it("groups later days and folds done sessions", () => {
    expect(b.later.map((g) => [g.label, g.sessions.map((s) => s.title)])).toEqual([["Fri", ["Trigonometry"]], ["Sat", ["Functions"]]])
    expect(b.done.count).toBe(2)
    expect(b.done.title).toBe("2 done this week")
    expect(b.done.daysLabel).toBe("Mon · Tue")
    expect(b.done.openByDefault).toBe(false)
    expect(b.done.sessions.every((s) => !s.canMove)).toBe(true)
  })
  it("says what it is built from and picks the panel's first session", () => {
    expect(b.basedOn).toBe("Built from your 12 papers and weak topics")
    expect(b.firstOpenId).toBe("Vectors")
    expect(b.binnyLine).toBe("15 minutes today.")
    expect(b.subjectTop).toBeNull()
    expect(b.whyTopics).toEqual([])
    expect(screen.all).toHaveLength(8)
  })
})

describe("one subject (WM)", () => {
  const screen = asPlan(planScreen(input(mockWeek(), { filter: "0580" })))
  it("scopes the header, adds the target line and why-these-topics", () => {
    expect(screen.header.sub).toBe("Mathematics · 3 sessions · 30 min")
    expect(screen.header.examDate).toBe("2027-02-10")
    expect(screen.header.filters.find((f) => f.selected)?.label).toBe("Mathematics")
    expect(screen.body.subjectTop).toEqual({ targetGrade: "A*", exam: "Paper 4 in 188 days" })
    expect(screen.body.whyTopics).toEqual([
      { topic: "Vectors", pct: 41, tone: "w" }, { topic: "Algebra", pct: 58, tone: "w" }, { topic: "Trigonometry", pct: 62, tone: "m" },
    ])
    expect(screen.body.whyHint).toBe("Your weakest Mathematics topics from 4 papers.")
    expect(screen.body.today.sub).toBe("1 session · 10 min")
  })
  it("opens the done fold and hides the strip when nothing is any-day", () => {
    expect(screen.body.done.title).toBe("1 done")
    expect(screen.body.done.openByDefault).toBe(true)
    expect(screen.body.week.show).toBe(false)
  })
})

describe("edges", () => {
  it("labels a session the scheduler placed past Sunday", () => {
    const s = asPlan(planScreen(input(O([SUB("0625", P("0625", [S("a", "2026-08-06"), S("b", "2026-08-10")]))]))))
    expect(s.body.later.map((g) => g.label)).toEqual(["Next Mon"])
    expect(s.body.week.days.reduce((n, d) => n + d.count, 0)).toBe(1)
  })
  it("says done for today, or nothing today", () => {
    const doneToday = asPlan(planScreen(input(O([SUB("0625", P("0625", [S("a", "2026-08-06", { completedAt: DONE }), S("b", "2026-08-07")]))]))))
    expect(doneToday.body.today.sub).toBe("Done for today")
    expect(doneToday.body.binnyLine).toBe("Done for today.")
    const freeToday = asPlan(planScreen(input(O([SUB("0625", P("0625", [S("b", "2026-08-07")]))]))))
    expect(freeToday.body.today.sub).toBe("Nothing planned today")
    expect(freeToday.body.firstOpenId).toBe("b")
  })
  it("lists subjects without a usable plan as pending rows", () => {
    const s = asPlan(planScreen(input(O([SUB("0580", null), SUB("0625", P("0625", [S("a", "2026-08-06")])), SUB("0606", P("0606", [], { available: false, reason: "no_signal" }))]))))
    expect(s.body.pending).toEqual([
      { subjectCode: "0580", subjectName: "Mathematics", kind: "notGenerated" },
      { subjectCode: "0606", subjectName: "Additional Maths", kind: "refused" },
    ])
  })
  it("hides the filter chips for a single subject", () => {
    expect(asPlan(planScreen(input(O([SUB("0625", P("0625", [S("a", "2026-08-06")]))])))).header.filters).toEqual([])
  })
  it("fills the ring per goal as sessions are done", () => {
    const vms = asPlan(planScreen(input(mockWeek()))).all.map((v) => (v.title === "Vectors" ? { ...v, status: "done" as const } : v))
    expect(ringParts(vms, "2026-08-06")).toEqual([1, 0, 0])
  })
  it("resolves an unknown subject filter to all", () => {
    expect(resolveFilter(mockWeek(), "0580")).toBe("0580")
    expect(resolveFilter(mockWeek(), "9999")).toBeNull()
    expect(resolveFilter(mockWeek(), undefined)).toBeNull()
  })
})
```

- [ ] **Step 2: Run the test and watch it fail.**

Run: `cd web && npx vitest run tests/unit/studyPlanModel.test.ts`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement `planModel.ts`:**

```ts
/*
 * L9 · the study plan's every decision, as one pure function of the week
 * overview. The screen renders what this returns and decides nothing.
 *
 * "Today" is `overview.today`, the server's day, never the browser clock.
 * Dates are compared as ISO strings, which sort in calendar order (K14).
 */

import type { StudyPlanOverviewDTO, StudyPlanSessionDTO, SubjectWeekDTO } from "@/lib/studyPlanTypes"
import {
  activityLabel,
  addDays,
  basedOnLine,
  examLine,
  formatMinutes,
  reasonLine,
  refusalCopy,
  spokenMinutes,
  startAction,
  weekdayLong,
  weekdayShort,
  whyBody,
  whyTopicsHint,
  COPY,
  type NextExam,
  type RefusalCopy,
  type StartAction,
} from "./planCopy"

export type SessionStatus = "done" | "missed" | "today" | "later" | "anyDay"
export interface MoveDay { date: string; label: string }
export interface SessionVM {
  id: string
  subjectCode: string
  subjectName: string
  dotIndex: number
  activity: string
  activityLabel: string
  title: string
  minutes: number
  minutesLabel: string
  date: string
  dayShort: string
  anyDay: boolean
  status: SessionStatus
  why: string | null
  whyBody: string
  start: StartAction | null
  canMove: boolean
  moveDays: MoveDay[]
}
export interface DayCell { date: string; letter: string; label: string; count: number; isToday: boolean; allDone: boolean; hasMissed: boolean }
export interface FilterChip { code: string | null; label: string; dotIndex: number | null; selected: boolean }
export interface HeaderModel { title: string; sub: string; examDate: string | null; filters: FilterChip[] }
export interface PendingSubject { subjectCode: string; subjectName: string; kind: "notGenerated" | "refused" }
export interface DayGroup { date: string; label: string; sessions: SessionVM[] }
export interface PlanBody {
  ring: [number, number, number]
  ringLabel: string
  today: { date: string; heading: string; sub: string; sessions: SessionVM[] }
  missed: SessionVM[]
  week: { show: boolean; days: DayCell[]; anyDay: SessionVM[] }
  later: DayGroup[]
  done: { count: number; title: string; daysLabel: string; openByDefault: boolean; sessions: SessionVM[] }
  basedOn: string
  subjectTop: { targetGrade: string | null; exam: string | null } | null
  whyTopics: { topic: string; pct: number; tone: "w" | "m" }[]
  whyHint: string | null
  pending: PendingSubject[]
  firstOpenId: string | null
  binnyLine: string
}
export interface WeekDoneStat { value: string; label: string; tone: "ok" | "primary" }
export type PlanScreen =
  | { kind: "noSubjects" }
  | { kind: "firstRun"; header: HeaderModel; codesToBuild: string[] }
  | { kind: "needPaper"; header: HeaderModel; placementCode: string; copy: RefusalCopy }
  | { kind: "nothingScheduled"; header: HeaderModel; practiceCode: string; basedOn: string; scopeCodes: string[]; pending: PendingSubject[] }
  | { kind: "weekDone"; header: HeaderModel; body: string; stats: WeekDoneStat[]; practiceCode: string; scopeCodes: string[]; all: SessionVM[] }
  | { kind: "plan"; header: HeaderModel; body: PlanBody; scopeCodes: string[]; all: SessionVM[] }

export interface PlanModelInput {
  overview: StudyPlanOverviewDTO
  filter: string | null
  subjectName: (code: string) => string
  targetGrade: (code: string) => string | null
  nextExam: (code: string) => NextExam | null
  /** Noon of `overview.today`, for day counts. */
  now: Date
  xp: { weekXp: number; streak: number } | null
}

/** Below this accuracy a why-topic chip uses the "work on" tone (`.tm.w`). */
const WEAK_PCT = 60

const plural = (n: number, one: string, many: string) => (n === 1 ? one : many)
const minutesOf = (list: { minutes: number }[]) => list.reduce((t, s) => t + s.minutes, 0)

export function resolveFilter(overview: StudyPlanOverviewDTO, code: string | undefined): string | null {
  if (!code) return null
  return overview.subjects.some((s) => s.subjectCode === code) ? code : null
}

function statusOf(s: StudyPlanSessionDTO, today: string): SessionStatus {
  if (s.completedAt !== null) return "done"
  if (s.anyDay) return "anyDay"
  if (s.date < today) return "missed"
  if (s.date === today) return "today"
  return "later"
}

function moveDaysFor(date: string, today: string, weekEnd: string): MoveDay[] {
  const days: MoveDay[] = []
  for (let d = today; d <= weekEnd; d = addDays(d, 1)) {
    if (d !== date) days.push({ date: d, label: d === today ? "Today" : weekdayShort(d) })
  }
  return days
}

function buildSession(
  s: StudyPlanSessionDTO,
  subject: SubjectWeekDTO,
  dotIndex: number,
  input: PlanModelInput,
): SessionVM {
  const { overview } = input
  const status = statusOf(s, overview.today)
  const moveDays = moveDaysFor(s.date, overview.today, overview.weekEnd)
  const movable = status === "today" || status === "later" || status === "missed"
  return {
    id: s.id,
    subjectCode: subject.subjectCode,
    subjectName: input.subjectName(subject.subjectCode),
    dotIndex,
    activity: s.activityType,
    activityLabel: activityLabel(s.activityType),
    title: s.topic,
    minutes: s.durationMinutes,
    minutesLabel: formatMinutes(s.durationMinutes),
    date: s.date,
    dayShort: weekdayShort(s.date),
    anyDay: s.anyDay,
    status,
    why: reasonLine(s.reason),
    whyBody: whyBody({ reason: s.reason, topic: s.topic, targetGrade: input.targetGrade(subject.subjectCode) }),
    start: startAction(s.activityType, subject.subjectCode, s.reason),
    canMove: movable && moveDays.length > 0,
    moveDays: movable ? moveDays : [],
  }
}

export function ringParts(sessions: SessionVM[], today: string): [number, number, number] {
  const part = (list: SessionVM[]) =>
    list.length === 0 ? 0 : list.filter((v) => v.status === "done").length / list.length
  const todays = sessions.filter((v) => v.date === today && !v.anyDay)
  return [
    part(todays.filter((v) => v.activity === "practice" || v.activity === "review")),
    part(todays.filter((v) => v.activity === "flashcards")),
    part(sessions.filter((v) => v.activity === "past_paper")),
  ]
}

function earliest(dates: (string | null)[]): string | null {
  const real = dates.filter((d): d is string => d !== null).sort()
  return real[0] ?? null
}

function buildHeader(input: PlanModelInput, scope: SubjectWeekDTO[], sessions: SessionVM[] | null): HeaderModel {
  const { overview, filter } = input
  const filters: FilterChip[] =
    overview.subjects.length < 2
      ? []
      : [
          { code: null, label: "All", dotIndex: null, selected: filter === null },
          ...overview.subjects.map((s, i) => ({
            code: s.subjectCode,
            label: input.subjectName(s.subjectCode),
            dotIndex: i,
            selected: filter === s.subjectCode,
          })),
        ]
  let sub: string = COPY.noPlanSub
  if (sessions) {
    const planned = formatMinutes(minutesOf(sessions))
    sub = filter
      ? `${input.subjectName(filter)} · ${sessions.length} ${plural(sessions.length, "session", "sessions")} · ${planned}`
      : `${sessions.filter((v) => v.status === "done").length} of ${sessions.length} done · ${planned}`
  }
  return {
    title: COPY.title,
    sub,
    examDate: earliest(scope.map((s) => input.nextExam(s.subjectCode)?.date ?? null)),
    filters,
  }
}

function sortVMs(list: SessionVM[]): SessionVM[] {
  return [...list].sort((a, b) => a.date.localeCompare(b.date) || a.dotIndex - b.dotIndex)
}

export function planScreen(input: PlanModelInput): PlanScreen {
  const { overview, filter } = input
  if (overview.subjects.length === 0) return { kind: "noSubjects" }

  const scope = filter ? overview.subjects.filter((s) => s.subjectCode === filter) : overview.subjects
  const scopeCodes = scope.map((s) => s.subjectCode)
  const available = scope.filter((s) => s.generated && s.plan?.available)
  const notGenerated = scope.filter((s) => !s.generated)
  const refused = scope.filter((s) => s.generated && s.plan && !s.plan.available)
  const dotIndex = (code: string) => overview.subjects.findIndex((s) => s.subjectCode === code)

  if (available.length === 0) {
    const header = buildHeader(input, scope, null)
    if (notGenerated.length > 0) {
      return { kind: "firstRun", header, codesToBuild: notGenerated.map((s) => s.subjectCode) }
    }
    const first = refused[0]
    return { kind: "needPaper", header, placementCode: first.subjectCode, copy: refusalCopy(first.plan?.reason ?? null) }
  }

  const pending: PendingSubject[] = [
    ...notGenerated.map((s) => ({ subjectCode: s.subjectCode, subjectName: input.subjectName(s.subjectCode), kind: "notGenerated" as const })),
    ...refused.map((s) => ({ subjectCode: s.subjectCode, subjectName: input.subjectName(s.subjectCode), kind: "refused" as const })),
  ]
  const all = sortVMs(
    available.flatMap((subject) =>
      (subject.plan?.sessions ?? []).map((s) => buildSession(s, subject, dotIndex(subject.subjectCode), input)),
    ),
  )
  const header = buildHeader(input, scope, all)
  const paperCount = scope.reduce((n, s) => n + s.paperCount, 0)

  if (all.length === 0) {
    return { kind: "nothingScheduled", header, practiceCode: available[0].subjectCode, basedOn: basedOnLine(paperCount), scopeCodes, pending }
  }

  if (all.every((v) => v.status === "done")) {
    const stats: WeekDoneStat[] = [{ value: String(all.length), label: plural(all.length, "session", "sessions"), tone: "ok" }]
    if (input.xp) {
      stats.push({ value: `+${input.xp.weekXp}`, label: "XP", tone: "primary" })
      stats.push({ value: String(input.xp.streak), label: plural(input.xp.streak, "day in a row", "days in a row"), tone: "ok" })
    }
    return {
      kind: "weekDone",
      header,
      body: `All ${all.length} ${plural(all.length, "session", "sessions")}, ${formatMinutes(minutesOf(all))}.`,
      stats,
      practiceCode: available[0].subjectCode,
      scopeCodes,
      all,
    }
  }

  return { kind: "plan", header, body: buildBody(input, scope, all, pending, paperCount), scopeCodes, all }
}

function buildBody(
  input: PlanModelInput,
  scope: SubjectWeekDTO[],
  all: SessionVM[],
  pending: PendingSubject[],
  paperCount: number,
): PlanBody {
  const { overview, filter } = input
  const today = overview.today
  const openToday = all.filter((v) => v.status === "today")
  const anyToday = all.filter((v) => v.date === today && !v.anyDay)
  const missed = all.filter((v) => v.status === "missed")
  const anyDay = all.filter((v) => v.status === "anyDay")
  const later = all.filter((v) => v.status === "later")
  const done = all.filter((v) => v.status === "done")
  const ring = ringParts(all, today)
  const goalsDone = ring.filter((p) => p === 1).length

  const days: DayCell[] = []
  for (let d = overview.weekStart; d <= overview.weekEnd; d = addDays(d, 1)) {
    const on = all.filter((v) => v.date === d)
    days.push({
      date: d,
      letter: weekdayShort(d).charAt(0),
      label: weekdayLong(d),
      count: on.length,
      isToday: d === today,
      allDone: on.length > 0 && on.every((v) => v.status === "done"),
      hasMissed: on.some((v) => v.status === "missed"),
    })
  }

  const laterGroups: DayGroup[] = []
  for (const v of later) {
    const last = laterGroups[laterGroups.length - 1]
    if (last && last.date === v.date) last.sessions.push(v)
    else laterGroups.push({ date: v.date, label: v.date > overview.weekEnd ? `Next ${v.dayShort}` : v.dayShort, sessions: [v] })
  }

  const doneDays = [...new Set(done.map((v) => v.date))].sort().map(weekdayShort)
  const focus = filter ? scope[0] : null
  const exam = focus ? input.nextExam(focus.subjectCode) : null
  const target = focus ? input.targetGrade(focus.subjectCode) : null

  return {
    ring,
    ringLabel: `Today: ${goalsDone} of 3 goals done`,
    today: {
      date: today,
      heading: `Today · ${weekdayLong(today)}`,
      sub:
        openToday.length > 0
          ? `${openToday.length} ${plural(openToday.length, "session", "sessions")} · ${formatMinutes(minutesOf(openToday))}`
          : anyToday.length > 0
            ? "Done for today"
            : "Nothing planned today",
      sessions: openToday,
    },
    missed,
    week: { show: filter === null || anyDay.length > 0, days, anyDay },
    later: laterGroups,
    done: {
      count: done.length,
      title: filter ? `${done.length} done` : `${done.length} done this week`,
      daysLabel: doneDays.join(" · "),
      openByDefault: filter !== null,
      sessions: done,
    },
    basedOn: basedOnLine(paperCount),
    subjectTop: focus && (target || exam) ? { targetGrade: target, exam: exam ? examLine(exam, input.now) : null } : null,
    whyTopics: focus
      ? focus.weakTopics.map((t) => ({ topic: t.topic, pct: t.accuracyPct, tone: t.accuracyPct < WEAK_PCT ? ("w" as const) : ("m" as const) }))
      : [],
    whyHint: focus && focus.weakTopics.length > 0 ? whyTopicsHint(input.subjectName(focus.subjectCode), focus.paperCount) : null,
    pending,
    firstOpenId: (openToday[0] ?? missed[0] ?? anyDay[0] ?? later[0] ?? null)?.id ?? null,
    binnyLine:
      openToday.length > 0
        ? `${spokenMinutes(minutesOf(openToday))} today.`
        : anyToday.length > 0
          ? "Done for today."
          : "Nothing due today.",
  }
}
```

- [ ] **Step 4: Run the test and watch it pass.**

Run: `cd web && npx vitest run tests/unit/studyPlanModel.test.ts tests/unit/studyPlanCopy.test.ts`
Expected: all pass.

- [ ] **Step 5: Commit.**

```bash
pre-commit run --files web/src/portals/student/screens/studyplan/planModel.ts web/tests/unit/studyPlanModel.test.ts
git commit -S -m "feat(web): study plan view model with every state" -- web/src/portals/student/screens/studyplan/planModel.ts web/tests/unit/studyPlanModel.test.ts
```

---

# Screen tasks (designer)

Before any UI edit, the `designer` agent:
1. invokes the `impeccable` skill;
2. reads `.claude/skills/impeccable/reference/craft-floor.md`;
3. reads the three taste memories (master Global Constraints);
4. opens `.impeccable/mocks/student-r2/plan-final.html` in a browser to see every frame.

**F1 kit used** (from `@/components/redesign`, signatures in the master F1 contract):
- `GoldRing`
- `CountdownPill`
- `Binny`
- `BinnyLine`
- `Walkthrough`
- `HairRows`
- `HairRow`
- `H2Row`

**Existing kit used:**
- `Sheet`, `SheetContent`, `SheetTitle` (`@/components/ui/sheet`)
- `Button` (`variant="primary"`, `loading`)
- `SkeletonBlock` (`@/components/ui/skeleton`)
- `ConfirmModal`
- `useToast`
- `PageHeading`

**Mock token → app token** (applies to every screen task):

| Mock | App (Tailwind) |
|---|---|
| `--p` | `primary` |
| `--pc` | `primary-container` |
| `--s` | `surface` |
| `--l` / `#fff` | `surface-container-lowest` |
| `--sl` | `surface-container-low` |
| `--sc` | `surface-container` |
| `--sh` | `surface-container-high` |
| `--ink` | `on-surface` |
| `--v` | `on-surface-variant` |
| `--o` | `outline` |
| `--ov` | `outline-variant` |
| `--ok` | `success-text` |
| `--okc` | `success-container` |
| `--errc` / `--onerrc` | `error-container` / `on-error-container` |
| `--gold` | `tertiary` (GoldRing only) |
| `--ga` | `grade-a-star` |
| `--gA` | `grade-a` |
| `--ease` `cubic-bezier(.2,.8,.2,1)` | `--ease-out` (identical) |
| `'Schibsted Grotesk'` | `font-sans` |
| `'Bricolage Grotesque'` | `font-display` |
| `'JetBrains Mono'` | `font-mono` |
| `.sic.cards` `oklch(.94 .04 300)` / `oklch(.42 .1 300)` | `secondary-container` / `on-secondary-container` (no violet token) |
| `.sic.review` `oklch(.95 .04 80)` / `oklch(.42 .09 70)` | `surface-container-high` / `on-surface-variant` (keeps gold for earned) |
| `.missr` / `.wk8 .miss` amber `oklch(.96 .03 80)` / `oklch(.38 .08 70)` | `tertiary-container` / `on-tertiary-container` (the mock's own hue) |
| `.sjpad` gradient | dropped: the shell owns the canvas |
| subject dots (`--gA`, `oklch(.55 .1 250)`, `oklch(.55 .1 300)`) | rotation `grade-a`, `primary`, `secondary`, then `on-surface-variant` (Needs user decision #2) |

### Task 7: Atoms: icons, styles, rows, filter, strip, missed bar, header, based-on

**Files:**
- Create in `web/src/portals/student/screens/studyplan/`:
  - `icons.tsx`
  - `planStyles.ts`
  - `useWide.ts`
  - `SessionRow.tsx`
  - `PlanHeader.tsx`
  - `WeekStrip.tsx`
  - `MissedGroup.tsx`
  - `BasedOn.tsx`

**Interfaces:**
- Consumes: `SessionVM`, `DayCell`, `HeaderModel`, `FilterChip` (Task 6). F1 `HairRow`, `CountdownPill`.
- Produces:

```tsx
ActivityGlyph({ activity: string, size?: number })
TickGlyph({ size?: number })
CalendarGlyph({ size?: number })
RebuildGlyph({ size?: number })
ChevronGlyph()
subjectDotClass(index: number | null): string
ACTIVITY_TILE: Record<string, string>
DONE_TILE: string
useWide(): boolean
ActivityTile({ session })
SubjectDot({ index })
SessionRow({ session, big?, selected?, onOpen })
PlanHeader({ header, wide, now, onFilter })
SubjectFilter({ filters, onFilter, inline? })
WeekStrip({ days, onDay })
MissedGroup({ missed, movingId, onOpen, onMoveToday, onMoveAllToday })
BasedOn({ line, rebuilding, onRebuild, className? })
```

- [ ] **Step 1: Create `icons.tsx`.** These are the mock's own drawn glyphs (`sp.js` `IC`/`TK`, `h6.js` `CAL`, `t.js` `CHEV`):

```tsx
type GlyphProps = { size?: number }

export function ActivityGlyph({ activity, size = 20 }: GlyphProps & { activity: string }) {
  switch (activity) {
    case "flashcards":
      return (
        <svg width={size} height={size} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinejoin="round" aria-hidden>
          <rect x={3} y={5} width={11} height={12} rx={2} />
          <path d="M7 3h8a2 2 0 0 1 2 2v9" />
        </svg>
      )
    case "past_paper":
      return (
        <svg width={size} height={size} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinejoin="round" strokeLinecap="round" aria-hidden>
          <path d="M5 2.5h7l3.5 3.5v11.5h-10.5zM12 2.5V6h3.5M8 10h5M8 13h5" />
        </svg>
      )
    case "review":
      return <RebuildGlyph size={size} />
    default:
      return (
        <svg width={size} height={size} viewBox="0 0 22 22" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" aria-hidden>
          <path d="M5 4h12v14H5zM8 8h6M8 12h6" />
        </svg>
      )
  }
}

export function TickGlyph({ size = 16 }: GlyphProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth={2.2} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M3.5 8.3 6.5 11l6-6.5" />
    </svg>
  )
}

export function CalendarGlyph({ size = 14 }: GlyphProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth={1.8} aria-hidden>
      <rect x={3} y={4.5} width={14} height={12} rx={2.5} />
      <path d="M3 8.5h14M7 2.5v4M13 2.5v4" />
    </svg>
  )
}

export function RebuildGlyph({ size = 16 }: GlyphProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M3.5 10a6.5 6.5 0 1 0 2-4.7M3.5 3v3.5H7" />
    </svg>
  )
}

export function ChevronGlyph() {
  return (
    <svg width={18} height={18} viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" aria-hidden className="text-on-surface-variant">
      <path d="M7 4l5 5-5 5" />
    </svg>
  )
}
```

- [ ] **Step 2: Create `planStyles.ts`:**

```ts
/* Token-only colour maps for the study plan (no new tokens; see the plan's mapping table). */

/** Subject dots by enrolment order. The mock's two oklch hues are not tokens. */
const SUBJECT_DOTS = ["bg-grade-a", "bg-primary", "bg-secondary"] as const

export function subjectDotClass(index: number | null): string {
  if (index === null || index < 0) return "bg-on-surface-variant"
  return SUBJECT_DOTS[index] ?? "bg-on-surface-variant"
}

/** `.sic` tiles: 40px, radius 13px. */
export const ACTIVITY_TILE: Record<string, string> = {
  practice: "bg-primary-container text-primary",
  flashcards: "bg-secondary-container text-on-secondary-container",
  past_paper: "bg-success-container text-success-text",
  review: "bg-surface-container-high text-on-surface-variant",
}

export const DONE_TILE = "bg-success-container text-success-text"
```

- [ ] **Step 3: Create `useWide.ts`.** The shell shows its rail at ≥ 1280px, and so does the side panel:

```ts
import { useSyncExternalStore } from "react"

const QUERY = "(min-width: 1280px)"

function subscribe(onChange: () => void): () => void {
  const media = window.matchMedia(QUERY)
  media.addEventListener("change", onChange)
  return () => media.removeEventListener("change", onChange)
}

/** True at the desktop breakpoint, where the session sheet becomes a side panel. */
export function useWide(): boolean {
  return useSyncExternalStore(subscribe, () => window.matchMedia(QUERY).matches, () => false)
}
```

- [ ] **Step 4: Create `SessionRow.tsx`.** It maps `.srow2` / `.srow2.big` / `.srow2.sdone` / `.sic`:

```tsx
import { HairRow } from "@/components/redesign"
import { cn } from "@/lib/utils"
import { ActivityGlyph, ChevronGlyph, TickGlyph } from "./icons"
import { ACTIVITY_TILE, DONE_TILE, subjectDotClass } from "./planStyles"
import type { SessionVM } from "./planModel"

export function SubjectDot({ index }: { index: number | null }) {
  return <i aria-hidden className={cn("inline-block size-2 shrink-0 rounded-full not-italic", subjectDotClass(index))} />
}

export function ActivityTile({ session }: { session: SessionVM }) {
  const done = session.status === "done"
  return (
    <span className={cn("grid size-10 shrink-0 place-items-center rounded-[13px]", done ? DONE_TILE : (ACTIVITY_TILE[session.activity] ?? ACTIVITY_TILE.review))}>
      {done ? <TickGlyph /> : <ActivityGlyph activity={session.activity} />}
    </span>
  )
}

export function SessionRow({
  session,
  big = false,
  selected = false,
  onOpen,
}: {
  session: SessionVM
  big?: boolean
  selected?: boolean
  onOpen: (id: string) => void
}) {
  const done = session.status === "done"
  return (
    <HairRow
      leading={<ActivityTile session={session} />}
      title={
        <span className={cn("font-sans text-[15px] font-bold group-hover:text-primary", done ? "text-on-surface-variant line-through decoration-outline" : "text-on-surface")}>
          {session.title}
        </span>
      }
      sub={
        <span className="flex flex-col">
          <span className="inline-flex items-center gap-1.5 font-sans text-[13px] text-on-surface-variant">
            <SubjectDot index={session.dotIndex} />
            {session.subjectName} · {session.activityLabel} · {session.minutesLabel}
          </span>
          {big && session.why ? <span className="font-sans text-[13px] font-semibold text-primary">{session.why}</span> : null}
        </span>
      }
      trailing={<ChevronGlyph />}
      onClick={() => onOpen(session.id)}
      selected={selected}
    />
  )
}
```

Geometry from `.srow2` is a `40px / 1fr / 18px` grid, gap 12, `min-h-14`. Padding is `py-2.5`, or `py-3.5` when `big`. If F1 `HairRow` padding differs, fix it in Task 13 drift by passing `className` through F1's optional props. Do not fork HairRow.

- [ ] **Step 5: Create `PlanHeader.tsx`.** It maps `.sjhd` and `.dtop`, `.sfilt` and `.pill4`. The back button is the shell's:

```tsx
import { Link } from "react-router-dom"
import { CountdownPill } from "@/components/redesign"
import { PageHeading } from "@/components/ui/page-heading"
import { cn } from "@/lib/utils"
import { SubjectDot } from "./SessionRow"
import type { FilterChip, HeaderModel } from "./planModel"

export function SubjectFilter({
  filters,
  onFilter,
  inline = false,
}: {
  filters: FilterChip[]
  onFilter: (code: string | null) => void
  inline?: boolean
}) {
  return (
    <div role="tablist" aria-label="Subject" className={cn("flex flex-none gap-1.5 overflow-x-auto [scrollbar-width:none]", !inline && "-mx-4 px-4")}>
      {filters.map((f) => (
        <button
          key={f.code ?? "all"}
          type="button"
          role="tab"
          aria-selected={f.selected}
          aria-controls="plan-list"
          onClick={() => onFilter(f.code)}
          className={cn(
            "relative inline-flex min-h-10 flex-none items-center gap-1.5 rounded-xl px-3.5 font-sans text-[13.5px] font-semibold before:absolute before:inset-x-0 before:-inset-y-0.5 before:content-['']",
            "focus-visible:outline-[2.5px] focus-visible:outline-primary focus-visible:outline-offset-2",
            f.selected ? "bg-primary text-on-primary" : "bg-surface-container-lowest text-on-surface shadow-[inset_0_0_0_1.5px_var(--color-outline-variant)]",
          )}
        >
          {f.dotIndex !== null ? <SubjectDot index={f.dotIndex} /> : null}
          {f.label}
        </button>
      ))}
    </div>
  )
}

function Countdown({ examDate, now }: { examDate: string; now: Date }) {
  return (
    <Link
      to="/student/announcements"
      aria-label="Exam dates"
      className="shrink-0 transition-transform duration-150 ease-[cubic-bezier(.2,.8,.2,1)] active:scale-[.97] motion-reduce:transition-none motion-reduce:active:scale-100"
    >
      <CountdownPill examDate={examDate} now={now} />
    </Link>
  )
}

export function PlanHeader({
  header,
  wide,
  now,
  onFilter,
}: {
  header: HeaderModel
  wide: boolean
  now: Date
  onFilter: (code: string | null) => void
}) {
  const title = (size: string) => (
    <PageHeading repeatsTitle className={cn("font-display font-extrabold leading-[1.1] tracking-[-0.03em] text-primary", size)}>
      {header.title}
    </PageHeading>
  )
  const sub = <span className="font-sans text-[13px] font-medium text-on-surface-variant">{header.sub}</span>
  if (wide) {
    return (
      <header className="flex items-center gap-5 pb-2">
        <div className="grid flex-1">{title("text-[32px]")}{sub}</div>
        {header.filters.length > 0 ? <SubjectFilter filters={header.filters} onFilter={onFilter} inline /> : null}
        {header.examDate ? <Countdown examDate={header.examDate} now={now} /> : null}
      </header>
    )
  }
  return (
    <header className="flex flex-col gap-4">
      <div className="flex items-center gap-2.5">
        <div className="min-w-0 flex-1">{title("text-[28px]")}{sub}</div>
        {header.examDate ? <Countdown examDate={header.examDate} now={now} /> : null}
      </div>
      {header.filters.length > 0 ? <SubjectFilter filters={header.filters} onFilter={onFilter} /> : null}
    </header>
  )
}
```

- [ ] **Step 6: Create `WeekStrip.tsx`.** It maps `.wk8`:

```tsx
import { cn } from "@/lib/utils"
import { TickGlyph } from "./icons"
import type { DayCell } from "./planModel"

export function WeekStrip({ days, onDay }: { days: DayCell[]; onDay: (date: string) => void }) {
  return (
    <ol aria-label="This week by day" className="grid grid-cols-7 gap-1.5">
      {days.map((d) => (
        <li key={d.date}>
          <button
            type="button"
            onClick={() => onDay(d.date)}
            aria-current={d.isToday ? "date" : undefined}
            aria-label={`${d.label}: ${d.allDone ? "all done" : `${d.count} ${d.count === 1 ? "session" : "sessions"}`}${d.hasMissed ? ", missed" : ""}`}
            className={cn(
              "grid min-h-14 w-full justify-items-center gap-1 rounded-[14px] py-2 font-sans text-xs font-semibold",
              "focus-visible:outline-[2.5px] focus-visible:outline-primary focus-visible:outline-offset-2",
              d.isToday ? "bg-primary text-on-primary" : "text-on-surface-variant",
            )}
          >
            <span aria-hidden>{d.letter}</span>
            <i
              aria-hidden
              className={cn(
                "grid size-[26px] place-items-center rounded-full font-mono text-[13px] font-bold not-italic",
                d.isToday
                  ? "bg-surface-container-lowest text-primary"
                  : d.allDone
                    ? "bg-success-container text-success-text"
                    : d.hasMissed
                      ? "bg-tertiary-container text-on-tertiary-container"
                      : "bg-surface-container-high text-on-surface",
              )}
            >
              {d.allDone ? <TickGlyph /> : d.count}
            </i>
          </button>
        </li>
      ))}
    </ol>
  )
}
```

- [ ] **Step 7: Create `MissedGroup.tsx`.** It maps `.missr`. With more than two missed sessions it collapses to one bar (an edge case with no frame):

```tsx
import { COPY } from "./planCopy"
import type { SessionVM } from "./planModel"

const bar =
  "flex min-h-12 items-center justify-between gap-2.5 rounded-[14px] bg-tertiary-container pl-3 pr-1 font-sans text-[13.5px] font-medium text-on-tertiary-container"
const action =
  "inline-flex min-h-11 items-center whitespace-nowrap rounded-[14px] px-2 font-bold text-primary focus-visible:outline-[2.5px] focus-visible:outline-primary focus-visible:outline-offset-2 disabled:opacity-60"

export function MissedGroup({
  missed,
  movingId,
  onOpen,
  onMoveToday,
  onMoveAllToday,
}: {
  missed: SessionVM[]
  movingId: string | null
  onOpen: (id: string) => void
  onMoveToday: (id: string) => void
  onMoveAllToday: (ids: string[]) => void
}) {
  if (missed.length === 0) return null
  if (missed.length > 2) {
    return (
      <div id="plan-missed" className={bar}>
        <span>Missed {missed.length} sessions</span>
        <button type="button" className={action} disabled={movingId !== null} onClick={() => onMoveAllToday(missed.map((s) => s.id))}>
          {movingId !== null ? COPY.moving : COPY.moveAllToday}
        </button>
      </div>
    )
  }
  return (
    <div id="plan-missed" className="grid gap-2">
      {missed.map((s) => (
        <div key={s.id} className={bar}>
          <button type="button" onClick={() => onOpen(s.id)} className="min-h-11 flex-1 text-start">
            Missed {s.dayShort} · {s.title}
          </button>
          <button type="button" className={action} disabled={movingId !== null} onClick={() => onMoveToday(s.id)}>
            {movingId === s.id ? COPY.moving : COPY.moveToday}
          </button>
        </div>
      ))}
    </div>
  )
}
```

- [ ] **Step 8: Create `BasedOn.tsx`.** It maps `.based` and `.based.d`:

```tsx
import { cn } from "@/lib/utils"
import { RebuildGlyph } from "./icons"
import { COPY } from "./planCopy"

export function BasedOn({
  line,
  rebuilding,
  onRebuild,
  className,
}: {
  line: string
  rebuilding: boolean
  onRebuild: () => void
  className?: string
}) {
  return (
    <button
      type="button"
      onClick={onRebuild}
      disabled={rebuilding}
      className={cn("flex min-h-11 items-center gap-1.5 text-start font-sans text-[13px] leading-[1.4] font-medium text-on-surface-variant", className)}
    >
      <RebuildGlyph />
      <span>
        {line} · <b className="text-primary">{rebuilding ? COPY.rebuilding : COPY.rebuild}</b>
      </span>
    </button>
  )
}
```

- [ ] **Step 9: Typecheck and lint.**

Run: `cd web && npx tsc -p tsconfig.app.json --noEmit && npx oxlint src/portals/student/screens/studyplan && npm run check:copy && npm run check:native`
Expected: clean. (`tsc` needs F1 merged. This lane starts after F1, per the master's merge order.)

- [ ] **Step 10: Commit.**

```bash
pre-commit run --files web/src/portals/student/screens/studyplan/{icons.tsx,planStyles.ts,useWide.ts,SessionRow.tsx,PlanHeader.tsx,WeekStrip.tsx,MissedGroup.tsx,BasedOn.tsx}
git commit -S -m "feat(web): study plan rows, filter, week strip and missed bar" -- web/src/portals/student/screens/studyplan/icons.tsx web/src/portals/student/screens/studyplan/planStyles.ts web/src/portals/student/screens/studyplan/useWide.ts web/src/portals/student/screens/studyplan/SessionRow.tsx web/src/portals/student/screens/studyplan/PlanHeader.tsx web/src/portals/student/screens/studyplan/WeekStrip.tsx web/src/portals/student/screens/studyplan/MissedGroup.tsx web/src/portals/student/screens/studyplan/BasedOn.tsx
```

---

### Task 8: Session detail: sheet (SS, PX) and desktop panel (SD)

**Files:**
- Create: `web/src/portals/student/screens/studyplan/SessionDetail.tsx`

**Interfaces:**
- Consumes: `SessionVM` (Task 6). `ActivityTile`, `SubjectDot`, glyphs (Task 7). Kit `Sheet`, `SheetContent`, `SheetTitle`, `Button`. F1 `BinnyLine`.
- Produces:

```tsx
interface SessionActions {
  completing: boolean
  completeError: string | null
  movingTo: string | null
  onStart: (path: string) => void
  onComplete: () => void
  onMove: (date: string) => void
}
SessionDetail(props: { session: SessionVM; titleWrap?: (h: ReactElement) => ReactNode; footer?: ReactNode } & SessionActions)
SessionSheet(props: { session: SessionVM | null; onClose: () => void } & SessionActions)
SessionPanel(props: { session: SessionVM | null; binnyLine: string | null } & SessionActions)
```

- [ ] **Step 1: Create the file:**

```tsx
import { useEffect, useState, type ReactElement, type ReactNode } from "react"
import { BinnyLine } from "@/components/redesign"
import { Button } from "@/components/ui/button"
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet"
import { cn } from "@/lib/utils"
import { CalendarGlyph, TickGlyph } from "./icons"
import { COPY } from "./planCopy"
import type { SessionVM } from "./planModel"
import { ActivityTile, SubjectDot } from "./SessionRow"

export interface SessionActions {
  completing: boolean
  completeError: string | null
  /** The day a move is in flight to, or null. */
  movingTo: string | null
  onStart: (path: string) => void
  onComplete: () => void
  onMove: (date: string) => void
}

/** `.sa`: the two secondary actions. */
const actionClass =
  "inline-flex min-h-12 items-center justify-center gap-2 rounded-[14px] bg-surface-container-high font-sans text-sm font-bold text-primary disabled:opacity-60 focus-visible:outline-[2.5px] focus-visible:outline-primary focus-visible:outline-offset-2"

export function SessionDetail({
  session,
  titleWrap,
  footer,
  completing,
  completeError,
  movingTo,
  onStart,
  onComplete,
  onMove,
}: { session: SessionVM; titleWrap?: (h: ReactElement) => ReactNode; footer?: ReactNode } & SessionActions) {
  const [moveOpen, setMoveOpen] = useState(false)
  useEffect(() => setMoveOpen(false), [session.id])
  const done = session.status === "done"
  const heading = <h2 className="m-0 font-sans text-[22px] font-extrabold text-on-surface">{session.title}</h2>

  return (
    <div className="flex flex-1 flex-col gap-3.5">
      <div className="flex items-center gap-3">
        <ActivityTile session={session} />
        <div className="min-w-0">
          {titleWrap ? titleWrap(heading) : heading}
          <span className="inline-flex items-center gap-1.5 font-sans text-[13px] font-medium text-on-surface-variant">
            <SubjectDot index={session.dotIndex} />
            {session.subjectName} · {session.activityLabel} · {session.minutesLabel}
          </span>
        </div>
      </div>

      {completeError ? (
        <div role="alert" className="rounded-xl bg-error-container px-3 py-2.5 font-sans text-[13.5px] leading-[1.35] font-semibold text-on-error-container">
          {completeError}
        </div>
      ) : (
        <p className="m-0 font-sans text-[15px] leading-[1.45] font-medium text-on-surface">
          <b className="text-primary">{COPY.whyThis}</b> {session.whyBody}
        </p>
      )}

      {session.start && !done ? (
        <Button
          variant="primary"
          onClick={() => onStart(session.start!.path)}
          className="min-h-[50px] w-full rounded-[18px] text-[15.5px] shadow-[0_14px_24px_-16px_oklch(0.3_0.07_242/0.7)]"
        >
          {session.start.label}
        </Button>
      ) : null}

      <div className={cn("grid gap-2.5", session.canMove ? "grid-cols-2" : "grid-cols-1")}>
        {done ? (
          <span className={cn(actionClass, "text-success-text")}>
            <TickGlyph /> {COPY.done}
          </span>
        ) : (
          <button type="button" className={actionClass} onClick={onComplete} disabled={completing}>
            <TickGlyph /> {completing ? COPY.saving : completeError ? COPY.tryAgain : COPY.markDone}
          </button>
        )}
        {session.canMove ? (
          <button
            type="button"
            className={actionClass}
            aria-expanded={moveOpen}
            aria-controls={`move-${session.id}`}
            onClick={() => setMoveOpen((o) => !o)}
          >
            <CalendarGlyph /> {COPY.move}
          </button>
        ) : null}
      </div>

      {moveOpen && session.canMove ? (
        <div id={`move-${session.id}`} role="group" aria-label="Move to" className="flex gap-2">
          {session.moveDays.map((d) => (
            <button
              key={d.date}
              type="button"
              onClick={() => onMove(d.date)}
              disabled={movingTo !== null}
              aria-pressed={movingTo === d.date}
              className={cn(
                "min-h-11 flex-1 rounded-xl font-sans text-sm font-semibold",
                movingTo === d.date
                  ? "bg-primary-container text-primary shadow-[inset_0_0_0_2px_var(--color-primary)]"
                  : "bg-surface-container-lowest text-on-surface shadow-[inset_0_0_0_1.5px_var(--color-outline)]",
              )}
            >
              {d.label}
            </button>
          ))}
        </div>
      ) : null}

      {footer}
    </div>
  )
}

/** < 1280px: the session as a sheet (SS, PX). Bottom on phones, floating from `sm`. */
export function SessionSheet({ session, onClose, ...actions }: { session: SessionVM | null; onClose: () => void } & SessionActions) {
  return (
    <Sheet open={session !== null} onOpenChange={(open) => !open && onClose()}>
      {session ? (
        <SheetContent side="adaptive" showCloseButton={false} aria-describedby={undefined} className="gap-3 pt-3">
          <SessionDetail session={session} titleWrap={(h) => <SheetTitle asChild>{h}</SheetTitle>} {...actions} />
        </SheetContent>
      ) : null}
    </Sheet>
  )
}

/** ≥ 1280px: the side panel that follows the selected row (SD). */
export function SessionPanel({ session, binnyLine, ...actions }: { session: SessionVM | null; binnyLine: string | null } & SessionActions) {
  return (
    <aside
      aria-label="Session"
      className="sticky top-6 flex min-h-[420px] flex-col gap-3.5 self-start rounded-[22px] bg-surface-container-lowest p-5 shadow-[0_1px_3px_oklch(0.3_0.05_240/0.1)]"
    >
      {session ? (
        <SessionDetail
          session={session}
          footer={binnyLine ? <div className="mt-auto"><BinnyLine mood="happy" line={binnyLine} size={56} motion="idle" /></div> : null}
          {...actions}
        />
      ) : binnyLine ? (
        <div className="mt-auto"><BinnyLine mood="happy" line={binnyLine} size={56} motion="idle" /></div>
      ) : null}
    </aside>
  )
}
```

`SheetContent`'s native header and grabber come from the kit (`BottomSheetSurface`/`SheetGrabber`). If the kit sheet does not render a grabber on non-native phones, add `<SheetGrabber />` as the first child (`.grab` is 40×5px, radius 3px, `bg-outline`).

- [ ] **Step 2: Typecheck and lint.**

Run: `cd web && npx tsc -p tsconfig.app.json --noEmit && npx oxlint src/portals/student/screens/studyplan && npm run check:copy`
Expected: clean.

- [ ] **Step 3: Commit.**

```bash
pre-commit run --files web/src/portals/student/screens/studyplan/SessionDetail.tsx
git commit -S -m "feat(web): study plan session sheet and desktop side panel" -- web/src/portals/student/screens/studyplan/SessionDetail.tsx
```

---

### Task 9: The plan body: today, ring, missed, any day, later, done, why, based-on

**Files:**
- Create: `web/src/portals/student/screens/studyplan/PlanList.tsx`

**Interfaces:**
- Consumes: `PlanBody`, `SessionVM` (Task 6), Task 7 atoms, F1 `GoldRing`, `HairRows`, `H2Row`.
- Produces:

```tsx
PlanList(props: {
  body: PlanBody
  wide: boolean
  selectedId: string | null
  movingId: string | null
  rebuilding: boolean
  onOpen(id: string): void
  onMoveToday(id: string): void
  onMoveAllToday(ids: string[]): void
  onDay(date: string): void
  onRebuild(): void
  onBuild(code: string): void
})
```

- [ ] **Step 1: Create the file:**

```tsx
import { Link } from "react-router-dom"
import { GoldRing, H2Row, HairRows } from "@/components/redesign"
import { cn } from "@/lib/utils"
import { BasedOn } from "./BasedOn"
import { TickGlyph } from "./icons"
import { MissedGroup } from "./MissedGroup"
import { COPY } from "./planCopy"
import type { PlanBody, SessionVM } from "./planModel"
import { SessionRow } from "./SessionRow"
import { WeekStrip } from "./WeekStrip"

interface PlanListProps {
  body: PlanBody
  wide: boolean
  selectedId: string | null
  movingId: string | null
  rebuilding: boolean
  onOpen: (id: string) => void
  onMoveToday: (id: string) => void
  onMoveAllToday: (ids: string[]) => void
  onDay: (date: string) => void
  onRebuild: () => void
  onBuild: (code: string) => void
}

export function PlanList(p: PlanListProps) {
  const { body } = p
  const rows = (list: SessionVM[], big: boolean, label: string) => (
    <HairRows aria-label={label}>
      {list.map((s) => (
        <SessionRow key={s.id} session={s} big={big} selected={p.wide && p.selectedId === s.id} onOpen={p.onOpen} />
      ))}
    </HairRows>
  )

  return (
    <div id="plan-list" aria-busy={p.rebuilding || undefined} className={cn("flex flex-col gap-6 xl:gap-[22px]", p.rebuilding && "opacity-50")}>
      {body.subjectTop ? (
        <p className="m-0 flex flex-wrap gap-x-3.5 font-sans text-[13.5px] font-medium text-on-surface-variant [&>span+span]:before:mr-3.5 [&>span+span]:before:text-outline [&>span+span]:before:content-['·']">
          {body.subjectTop.targetGrade ? (
            <span>
              <b className="font-sans text-[15px] font-extrabold text-grade-a-star">{body.subjectTop.targetGrade}</b> target
            </span>
          ) : null}
          {body.subjectTop.exam ? <span>{body.subjectTop.exam}</span> : null}
        </p>
      ) : null}

      <section id={`plan-day-${body.today.date}`} aria-label={body.today.heading} className="flex flex-col">
        <div className="flex items-center gap-3">
          <GoldRing parts={body.ring} size={32} label={body.ringLabel} />
          <div>
            <h2 className="m-0 font-sans text-lg font-extrabold tracking-[-0.01em] text-on-surface">{body.today.heading}</h2>
            <span className="font-sans text-[13px] font-medium text-on-surface-variant">{body.today.sub}</span>
          </div>
        </div>
        {body.today.sessions.length > 0 ? rows(body.today.sessions, true, "Today's sessions") : null}
      </section>

      <MissedGroup
        missed={body.missed}
        movingId={p.movingId}
        onOpen={p.onOpen}
        onMoveToday={p.onMoveToday}
        onMoveAllToday={p.onMoveAllToday}
      />

      {body.week.show ? (
        <section aria-label={COPY.anyDay} className="grid gap-2.5">
          <H2Row title={COPY.anyDay} />
          <WeekStrip days={body.week.days} onDay={p.onDay} />
          {body.week.anyDay.length > 0 ? rows(body.week.anyDay, true, COPY.anyDay) : null}
        </section>
      ) : null}

      {body.later.length > 0 ? (
        <section aria-label={COPY.later} className="mt-1 grid">
          <H2Row title={COPY.later} />
          {body.later.map((g) => (
            <div key={g.date} id={`plan-day-${g.date}`} className="grid">
              <span className="pt-2.5 pb-0.5 font-sans text-[12.5px] font-bold text-on-surface-variant">{g.label}</span>
              {rows(g.sessions, false, g.label)}
            </div>
          ))}
        </section>
      ) : null}

      {body.done.count > 0 ? (
        <details id="plan-done" open={body.done.openByDefault}>
          <summary className="flex min-h-11 cursor-pointer list-none items-center gap-2 font-sans text-sm font-bold text-success-text [&::-webkit-details-marker]:hidden">
            <TickGlyph /> {body.done.title} <span className="font-medium text-on-surface-variant">{body.done.daysLabel}</span>
          </summary>
          {rows(body.done.sessions, false, body.done.title)}
        </details>
      ) : null}

      {body.whyTopics.length > 0 ? (
        <section aria-label={COPY.whyTopics} className="grid gap-2.5">
          <H2Row title={COPY.whyTopics} />
          <div className="flex flex-wrap gap-1.5">
            {body.whyTopics.map((t) => (
              <Link
                key={t.topic}
                to={`/student/practice/${body.today.sessions[0]?.subjectCode ?? ""}`}
                className={cn(
                  "relative inline-flex min-h-11 items-center gap-2 rounded-xl px-3 font-sans text-[13.5px] font-semibold xl:min-h-10",
                  t.tone === "w"
                    ? "bg-error-container text-on-error-container"
                    : "bg-surface-container-low text-on-surface shadow-[inset_0_0_0_1px_var(--color-outline-variant)]",
                )}
              >
                <span>{t.topic}</span>
                <b className="font-mono text-xs font-bold">{t.pct}%</b>
              </Link>
            ))}
          </div>
          {body.whyHint ? <p className="m-0 font-sans text-sm leading-[1.4] font-medium text-on-surface-variant">{body.whyHint}</p> : null}
        </section>
      ) : null}

      {body.pending.map((s) => (
        <p key={s.subjectCode} className="m-0 flex min-h-11 items-center gap-1.5 font-sans text-[13px] text-on-surface-variant">
          {s.subjectName}: {s.kind === "refused" ? "needs a paper first" : "no plan yet"} ·
          <button type="button" className="min-h-11 font-bold text-primary" onClick={() => p.onBuild(s.subjectCode)}>
            {s.kind === "refused" ? COPY.rebuild : "Build"}
          </button>
        </p>
      ))}

      {!p.wide ? <BasedOn line={body.basedOn} rebuilding={p.rebuilding} onRebuild={p.onRebuild} /> : null}
    </div>
  )
}
```

The why-topic chips link to the filtered subject's practice route. In the filtered view the subject is `subjectTop`'s subject. Pass it explicitly if `today.sessions` is empty: add `subjectCode` to `PlanBody.subjectTop` if review asks. Practice routes may move under L4. If L4 has merged by then, re-point to its topic practice entry.

- [ ] **Step 2: Typecheck, lint and commit.**

Run: `cd web && npx tsc -p tsconfig.app.json --noEmit && npx oxlint src/portals/student/screens/studyplan && npm run check:copy && npm run check:native`

```bash
pre-commit run --files web/src/portals/student/screens/studyplan/PlanList.tsx
git commit -S -m "feat(web): study plan body with today first and the any-day strip" -- web/src/portals/student/screens/studyplan/PlanList.tsx
```

---

### Task 10: States: Z0, Z1, PD, PR, PL, PE, plus the frameless ones

**Files:**
- Create: `web/src/portals/student/screens/studyplan/PlanStates.tsx`

**Interfaces:**
- Consumes: F1 `Binny`, `Walkthrough`. Kit `Button`, `SkeletonBlock`. `COPY`, `RefusalCopy`, `WeekDoneStat`.
- Produces:

```tsx
PlanLoading()
PlanLoadError({ onRetry })
FirstRun({ building, error, onBuild })
NeedPaper({ copy, placementCode })
NothingScheduled({ practiceCode })
NoSubjects()
WeekDone({ body, stats, practiceCode, planning, nextWeekReady, onPlanNextWeek })
RebuildingBanner()
NotInWeekNote()
ActionError({ message })
```

- [ ] **Step 1: Create the file.** `.err2` is the shared centred stack for every full state:

```tsx
import type { ReactNode } from "react"
import { Link } from "react-router-dom"
import { ArrowsClockwise, Target, Timer } from "@phosphor-icons/react"
import { Binny, Walkthrough, type BinnyMood, type BinnyMotion } from "@/components/redesign"
import { Button } from "@/components/ui/button"
import { SkeletonBlock } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"
import { COPY, type RefusalCopy } from "./planCopy"
import type { WeekDoneStat } from "./planModel"

const go = "min-h-[50px] w-full rounded-[18px] text-[15.5px] shadow-[0_14px_24px_-16px_oklch(0.3_0.07_242/0.7)]"
const quiet = "inline-flex min-h-11 items-center px-3.5 font-sans text-sm font-semibold text-on-surface-variant"

/** `.err2`: centred Binny, display heading, one line, one action. */
function StateStack({
  mood,
  motion = "idle",
  size = 96,
  title,
  body,
  children,
  className,
}: {
  mood: BinnyMood
  motion?: BinnyMotion
  size?: number
  title: string
  body?: string
  children?: ReactNode
  className?: string
}) {
  return (
    <section className={cn("grid flex-1 content-center justify-items-center gap-3 px-2 py-6 text-center", className)}>
      <Binny mood={mood} size={size} motion={motion} aria-hidden />
      <h2 className="mt-1.5 mb-0 font-display text-[28px] leading-[1.15] font-extrabold tracking-[-0.02em] text-balance text-primary">{title}</h2>
      {body ? <p className="m-0 mb-1.5 max-w-[30ch] font-sans text-[15px] leading-[1.4] font-medium text-on-surface-variant">{body}</p> : null}
      {children}
    </section>
  )
}

/** PL: geometry copied from the mock's skeleton (`sk2c`). */
export function PlanLoading() {
  return (
    <div aria-busy="true" aria-label="Loading your week" className="grid gap-3.5">
      <SkeletonBlock className="h-10 rounded-xl" />
      <SkeletonBlock className="h-6 w-[180px]" />
      <SkeletonBlock className="h-16 rounded-[14px]" />
      <SkeletonBlock className="h-16 rounded-[14px]" />
      <SkeletonBlock className="h-14 rounded-[14px]" />
      <SkeletonBlock className="h-[52px] rounded-[14px]" />
      <SkeletonBlock className="h-[52px] rounded-[14px]" />
      <SkeletonBlock className="h-[52px] rounded-[14px]" />
    </div>
  )
}

/** PE. */
export function PlanLoadError({ onRetry }: { onRetry: () => void }) {
  return (
    <StateStack mood="sad" title={COPY.loadErrorTitle} body={COPY.loadErrorBody}>
      <Button variant="primary" className={go} onClick={onRetry}>{COPY.tryAgain}</Button>
      <Link to="/student" className={quiet}>{COPY.backHome}</Link>
    </StateStack>
  )
}

/** Z0 · first run: one action, then the three tips. */
export function FirstRun({ building, error, onBuild }: { building: boolean; error: string | null; onBuild: () => void }) {
  return (
    <>
      <StateStack mood="open" title={COPY.firstRunTitle} body={COPY.firstRunBody} className="pt-5">
        <Button variant="primary" className={go} loading={building} onClick={onBuild}>
          {building ? COPY.building : COPY.firstRunCta}
        </Button>
        {error ? <ActionError message={error} /> : null}
      </StateStack>
      <Walkthrough
        steps={[
          { icon: Timer, title: COPY.walk[0].title, body: COPY.walk[0].body },
          { icon: Target, title: COPY.walk[1].title, body: COPY.walk[1].body },
          { icon: ArrowsClockwise, title: COPY.walk[2].title, body: COPY.walk[2].body },
        ]}
      />
    </>
  )
}

/** Z1 · not enough to plan from (or an unknown refusal, with its own copy). */
export function NeedPaper({ copy, placementCode }: { copy: RefusalCopy; placementCode: string }) {
  return (
    <StateStack mood="thinking" title={copy.heading} body={copy.body} className="pt-5">
      <Link to="/student/correct" className="w-full">
        <Button variant="primary" className={go}>{COPY.needPaperCta}</Button>
      </Link>
      <Link to={`/student/placement/${placementCode}`} className={quiet}>{COPY.placementCta}</Link>
    </StateStack>
  )
}

/** A real plan with nothing in it (K5). No mock frame. */
export function NothingScheduled({ practiceCode }: { practiceCode: string }) {
  return (
    <StateStack mood="happy" title={COPY.nothingTitle} body={COPY.nothingBody}>
      <Link to={`/student/practice/${practiceCode}`} className="w-full">
        <Button variant="primary" className={go}>{COPY.nothingCta}</Button>
      </Link>
    </StateStack>
  )
}

/** No enrolments. No mock frame. */
export function NoSubjects() {
  return (
    <StateStack mood="thinking" title={COPY.noSubjectsTitle} body={COPY.noSubjectsBody}>
      <Link to="/student/onboard" className="w-full">
        <Button variant="primary" className={go}>{COPY.noSubjectsCta}</Button>
      </Link>
    </StateStack>
  )
}

/** PD · week done. */
export function WeekDone({
  body,
  stats,
  practiceCode,
  planning,
  nextWeekReady,
  onPlanNextWeek,
}: {
  body: string
  stats: WeekDoneStat[]
  practiceCode: string
  planning: boolean
  nextWeekReady: boolean
  onPlanNextWeek: () => void
}) {
  return (
    <StateStack mood="happy" motion="hop" size={110} title={COPY.weekDoneTitle} body={body} className="pt-3">
      <div className="grid w-full text-center" style={{ gridTemplateColumns: `repeat(${stats.length}, minmax(0, 1fr))` }}>
        {stats.map((s) => (
          <span key={s.label} className="grid justify-items-center gap-0.5">
            <b className={cn("font-mono text-2xl font-extrabold", s.tone === "ok" ? "text-success-text" : "text-primary")}>{s.value}</b>
            <small className="font-sans text-[12.5px] font-medium text-on-surface-variant">{s.label}</small>
          </span>
        ))}
      </div>
      <Button variant="primary" className={go} loading={planning} disabled={nextWeekReady} onClick={onPlanNextWeek}>
        {nextWeekReady ? COPY.nextWeekReady : COPY.planNextWeek}
      </Button>
      <Link to={`/student/practice/${practiceCode}`} className={quiet}>{COPY.bonusPractice}</Link>
    </StateStack>
  )
}

/** PR · `.rebuild`. Carries the screen's one Binny while it shows. */
export function RebuildingBanner() {
  return (
    <div role="status" className="flex items-center gap-3 rounded-2xl bg-surface-container-lowest px-3.5 py-3 shadow-[inset_0_0_0_1.5px_var(--color-outline-variant)]">
      <Binny mood="thinking" size={52} motion="idle" aria-hidden />
      <p className="m-0 font-sans text-[14.5px] leading-[1.4] font-medium text-on-surface">
        <b>{COPY.rebuildingTitle}</b>
        <br />
        <span className="text-on-surface-variant">{COPY.rebuildingBody}</span>
      </p>
    </div>
  )
}

/** K25: a deep link to a session this week's plan no longer has. Not a 404. */
export function NotInWeekNote() {
  return (
    <p role="status" className="m-0 rounded-xl bg-surface-container-high px-3 py-2.5 font-sans text-[13.5px] leading-[1.35] font-semibold text-on-surface">
      {COPY.notInWeek}
    </p>
  )
}

/** `.errl`: an action failure under the header (K7). */
export function ActionError({ message }: { message: string }) {
  return (
    <div role="alert" className="w-full rounded-xl bg-error-container px-3 py-2.5 text-start font-sans text-[13.5px] leading-[1.35] font-semibold text-on-error-container">
      {message}
    </div>
  )
}
```

`NeedPaper`, `NothingScheduled` and `NoSubjects` wrap a `Button` in a router `Link`. If `components/ui/button.tsx` supports `asChild`, switch all three to `<Button asChild><Link …/></Button>` so there is one focusable element, not a link around a button.

- [ ] **Step 2: Typecheck, lint and commit.**

Run: `cd web && npx tsc -p tsconfig.app.json --noEmit && npx oxlint src/portals/student/screens/studyplan && npm run check:copy && npm run check:native`

```bash
pre-commit run --files web/src/portals/student/screens/studyplan/PlanStates.tsx
git commit -S -m "feat(web): study plan first-run, sparse, done, loading and error states" -- web/src/portals/student/screens/studyplan/PlanStates.tsx
```

---

### Task 11: The orchestrator and routes

**Files:**
- Create: `web/src/portals/student/screens/studyplan/StudyPlanScreen.tsx`
- Modify: `web/src/portals/student/index.tsx` (the lazy imports at `:44-49` and the route entries at `:264-272`)

**Interfaces:**
- Consumes: everything above. Also `useStudentProfile` (`@/lib/hooks/useMeApi`), `useExamCalendar` (`@/lib/hooks/useAnnouncementApi`), `useXpProfile` (`@/lib/hooks/useXpApi`), `useReference` + `subjectNameFor` (`@/lib/reference`), `studentActionFailureMessage` (`@/lib/studentOutcome`) and `ApiError`.
- Produces routes (all render `StudyPlanScreen`):
  - `/student/plan`: all subjects
  - `/student/plan/:subjectCode`: filtered
  - `/student/plan/session/:sessionId`: all, with a session open
  - `/student/plan/:subjectCode/session/:sessionId`: filtered, with a session open (K44)

- [ ] **Step 1: Create `StudyPlanScreen.tsx`:**

```tsx
import { useEffect, useMemo, useState } from "react"
import { useLocation, useNavigate, useParams } from "react-router-dom"
import { ConfirmModal } from "@/components/ui/confirm-modal"
import { useToast } from "@/components/ui/toast"
import { ApiError } from "@/lib/api"
import { useExamCalendar } from "@/lib/hooks/useAnnouncementApi"
import { useStudentProfile } from "@/lib/hooks/useMeApi"
import { useReference } from "@/lib/hooks/useReferenceApi"
import {
  useCompleteStudyPlanSession,
  useMoveStudyPlanSession,
  useRebuildStudyPlans,
  useStudyPlanWeek,
} from "@/lib/hooks/useStudyPlanApi"
import { useXpProfile } from "@/lib/hooks/useXpApi"
import { subjectNameFor } from "@/lib/reference"
import { studentActionFailureMessage } from "@/lib/studentOutcome"
import type { StudyPlanOverviewDTO } from "@/lib/studyPlanTypes"
import { BasedOn } from "./BasedOn"
import { COPY, nextExamForSubject, weekdayShort } from "./planCopy"
import { planScreen, resolveFilter, type SessionVM } from "./planModel"
import { PlanHeader } from "./PlanHeader"
import { PlanList } from "./PlanList"
import {
  ActionError,
  FirstRun,
  NeedPaper,
  NoSubjects,
  NotInWeekNote,
  NothingScheduled,
  PlanLoadError,
  PlanLoading,
  RebuildingBanner,
  WeekDone,
} from "./PlanStates"
import { SessionPanel, SessionSheet } from "./SessionDetail"
import { useWide } from "./useWide"

/*
 * L9 · the study plan: one week across subjects (mock WA/WM/SS/SD and the
 * states). The screen fetches, routes and runs mutations. `planModel`
 * decides everything shown.
 *
 * URL is state: the filter lives in `:subjectCode` and an open session in
 * `:sessionId`, so a push or inbox link lands on the right sheet (K44) and
 * the back gesture closes the sheet.
 */
export function StudyPlanScreen() {
  const weekQuery = useStudyPlanWeek()
  return (
    <div className="flex flex-col gap-6 md:mx-auto md:w-full md:max-w-[640px] xl:max-w-none">
      {weekQuery.isPending ? (
        <>
          <h1 className="sr-only">{COPY.title}</h1>
          <PlanLoading />
        </>
      ) : weekQuery.isError ? (
        <>
          <h1 className="sr-only">{COPY.title}</h1>
          <PlanLoadError onRetry={() => void weekQuery.refetch()} />
        </>
      ) : (
        <PlanContent overview={weekQuery.data} />
      )}
    </div>
  )
}

function PlanContent({ overview }: { overview: StudyPlanOverviewDTO }) {
  const { subjectCode, sessionId } = useParams<{ subjectCode?: string; sessionId?: string }>()
  const navigate = useNavigate()
  const location = useLocation()
  const wide = useWide()
  const { toast } = useToast()
  const reference = useReference()
  const profile = useStudentProfile()
  const calendar = useExamCalendar()
  const xp = useXpProfile()
  const complete = useCompleteStudyPlanSession()
  const move = useMoveStudyPlanSession()
  const rebuild = useRebuildStudyPlans()
  const [panelId, setPanelId] = useState<string | null>(null)
  const [confirmCodes, setConfirmCodes] = useState<string[] | null>(null)
  const [nextWeekReady, setNextWeekReady] = useState(false)
  const [missingNote, setMissingNote] = useState(false)
  const [movingAll, setMovingAll] = useState(false)

  const filter = resolveFilter(overview, subjectCode)
  const listUrl = filter ? `/student/plan/${filter}` : "/student/plan"
  const sessionUrl = (id: string) => (filter ? `/student/plan/${filter}/session/${id}` : `/student/plan/session/${id}`)
  const now = useMemo(() => new Date(`${overview.today}T12:00:00`), [overview.today])

  const screen = useMemo(
    () =>
      planScreen({
        overview,
        filter,
        subjectName: (code) => subjectNameFor(reference.data, code),
        targetGrade: (code) => profile.data?.enrolments.find((e) => e.subjectCode === code)?.targetGrade ?? null,
        nextExam: (code) => nextExamForSubject(calendar.data, code, now),
        now,
        xp: xp.data ? { weekXp: xp.data.week.total, streak: xp.data.streak.current } : null,
      }),
    [overview, filter, reference.data, profile.data, calendar.data, xp.data, now],
  )

  const all: SessionVM[] = screen.kind === "plan" || screen.kind === "weekDone" ? screen.all : []
  const fromParam = sessionId ? (all.find((s) => s.id === sessionId) ?? null) : null
  const firstOpenId = screen.kind === "plan" ? screen.body.firstOpenId : null
  const selected = wide ? (fromParam ?? all.find((s) => s.id === (panelId ?? firstOpenId)) ?? null) : null
  const sheetSession = wide ? null : fromParam

  // An unknown subject in the URL falls back to all subjects (K18).
  useEffect(() => {
    if (subjectCode && filter === null) navigate("/student/plan", { replace: true })
  }, [subjectCode, filter, navigate])

  // A session id this week's plan does not hold: say so, then drop it (K24/K25).
  useEffect(() => {
    if (sessionId && !fromParam) {
      setMissingNote(true)
      navigate(listUrl, { replace: true })
    }
  }, [sessionId, fromParam, listUrl, navigate])

  // A fresh session starts with a clean error.
  const activeId = (sheetSession ?? selected)?.id ?? null
  useEffect(() => {
    complete.reset()
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reset only when the session changes
  }, [activeId])

  const openSession = (id: string) => {
    if (wide) setPanelId(id)
    else navigate(sessionUrl(id), { state: { fromList: true } })
  }
  const closeSheet = () => {
    if ((location.state as { fromList?: boolean } | null)?.fromList) navigate(-1)
    else navigate(listUrl, { replace: true })
  }
  const onFilter = (code: string | null) => navigate(code ? `/student/plan/${code}` : "/student/plan", { replace: true })

  const moveError = (error: Error) => {
    const code = error instanceof ApiError ? (error.detail as { code?: string } | undefined)?.code : undefined
    if (code === "superseded") return COPY.moveSuperseded
    if (code === "completed") return COPY.moveCompleted
    return COPY.moveError
  }
  const runMove = (s: SessionVM, date: string) =>
    move.mutate(
      { sessionId: s.id, subjectCode: s.subjectCode, date },
      {
        onSuccess: () => {
          toast({ title: `Moved to ${date === overview.today ? "today" : weekdayShort(date)}`, variant: "success" })
          if (!wide && sheetSession) closeSheet()
        },
        onError: (e) => toast({ title: moveError(e), variant: "error" }),
      },
    )
  const moveToday = (id: string) => {
    const s = all.find((x) => x.id === id)
    if (s) runMove(s, overview.today)
  }
  const moveAllToday = async (ids: string[]) => {
    setMovingAll(true)
    try {
      for (const id of ids) {
        const s = all.find((x) => x.id === id)
        if (s) await move.mutateAsync({ sessionId: s.id, subjectCode: s.subjectCode, date: overview.today })
      }
      toast({ title: "Moved to today", variant: "success" })
    } catch (e) {
      toast({ title: moveError(e as Error), variant: "error" })
    } finally {
      setMovingAll(false)
    }
  }

  const runRebuild = (codes: string[]) => rebuild.mutate({ subjectCodes: codes })
  const askRebuild = (codes: string[]) => {
    const scope = all.filter((s) => codes.includes(s.subjectCode))
    if (scope.some((s) => s.status === "done")) setConfirmCodes(codes)
    else runRebuild(codes)
  }
  const planNextWeek = (codes: string[]) =>
    rebuild.mutate(
      { subjectCodes: codes, week: "next" },
      {
        onSuccess: () => {
          setNextWeekReady(true)
          toast({ title: COPY.nextWeekReady, variant: "success" })
        },
      },
    )

  const onDay = (date: string) => {
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches
    const day = all.filter((s) => s.date === date)
    let target = document.getElementById(`plan-day-${date}`)
    if (day.length > 0 && day.every((s) => s.status === "done")) {
      const fold = document.getElementById("plan-done") as HTMLDetailsElement | null
      if (fold) fold.open = true
      target = fold
    } else if (day.some((s) => s.status === "missed")) {
      target = document.getElementById("plan-missed")
    }
    target?.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" })
  }

  const completeErrorFor = (s: SessionVM | null) =>
    s && complete.isError && complete.variables?.sessionId === s.id ? COPY.completeError : null
  const actionsFor = (s: SessionVM | null) => ({
    completing: !!s && complete.isPending && complete.variables?.sessionId === s.id,
    completeError: completeErrorFor(s),
    movingTo: s && move.isPending && move.variables?.sessionId === s.id ? move.variables.date : null,
    onStart: (path: string) => navigate(path),
    onComplete: () => s && complete.mutate({ sessionId: s.id, subjectCode: s.subjectCode }),
    onMove: (date: string) => s && runMove(s, date),
  })

  if (screen.kind === "noSubjects") {
    return (
      <>
        <h1 className="sr-only">{COPY.title}</h1>
        <NoSubjects />
      </>
    )
  }

  const rebuilding = rebuild.isPending && rebuild.variables?.week !== "next"
  const rebuildError = rebuild.isError ? studentActionFailureMessage(rebuild.error, "rebuild your plan") : null

  return (
    <>
      <PlanHeader header={screen.header} wide={wide} now={now} onFilter={onFilter} />
      {missingNote ? <NotInWeekNote /> : null}
      {rebuilding && screen.kind === "plan" ? <RebuildingBanner /> : null}
      {rebuildError && screen.kind !== "firstRun" ? <ActionError message={rebuildError} /> : null}

      {screen.kind === "firstRun" ? (
        <FirstRun building={rebuild.isPending} error={rebuildError} onBuild={() => runRebuild(screen.codesToBuild)} />
      ) : null}
      {screen.kind === "needPaper" ? <NeedPaper copy={screen.copy} placementCode={screen.placementCode} /> : null}
      {screen.kind === "nothingScheduled" ? (
        <>
          <NothingScheduled practiceCode={screen.practiceCode} />
          <BasedOn line={screen.basedOn} rebuilding={rebuilding} onRebuild={() => askRebuild(screen.scopeCodes)} />
        </>
      ) : null}
      {screen.kind === "weekDone" ? (
        <WeekDone
          body={screen.body}
          stats={screen.stats}
          practiceCode={screen.practiceCode}
          planning={rebuild.isPending && rebuild.variables?.week === "next"}
          nextWeekReady={nextWeekReady}
          onPlanNextWeek={() => planNextWeek(screen.scopeCodes)}
        />
      ) : null}
      {screen.kind === "plan" ? (
        <div className="xl:grid xl:grid-cols-[minmax(0,1fr)_340px] xl:gap-10">
          <PlanList
            body={screen.body}
            wide={wide}
            selectedId={selected?.id ?? null}
            movingId={movingAll ? "all" : move.isPending ? (move.variables?.sessionId ?? null) : null}
            rebuilding={rebuilding}
            onOpen={openSession}
            onMoveToday={moveToday}
            onMoveAllToday={(ids) => void moveAllToday(ids)}
            onDay={onDay}
            onRebuild={() => askRebuild(screen.scopeCodes)}
            onBuild={(code) => runRebuild([code])}
          />
          {wide ? <SessionPanel session={selected} binnyLine={rebuilding ? null : screen.body.binnyLine} {...actionsFor(selected)} /> : null}
        </div>
      ) : null}
      {screen.kind === "plan" && wide ? (
        <BasedOn line={screen.body.basedOn} rebuilding={rebuilding} onRebuild={() => askRebuild(screen.scopeCodes)} className="pb-5" />
      ) : null}

      <SessionSheet session={sheetSession} onClose={closeSheet} {...actionsFor(sheetSession)} />
      <ConfirmModal
        open={confirmCodes !== null}
        title={COPY.rebuildConfirmTitle}
        consequence={COPY.rebuildConfirmBody}
        destructive={false}
        confirmLabel={COPY.rebuildConfirmCta}
        pendingLabel={COPY.rebuilding}
        cancelLabel={COPY.rebuildKeep}
        pending={rebuild.isPending}
        onConfirm={() => {
          if (confirmCodes) runRebuild(confirmCodes)
          setConfirmCodes(null)
        }}
        onCancel={() => setConfirmCodes(null)}
      />
    </>
  )
}
```

If oxlint flags the `eslint-disable` comment as unknown, drop it. The project lints with oxlint, which has its own exhaustive-deps rule: check `.oxlintrc*` and use its disable syntax. Confirm `subjectNameFor` is exported from `@/lib/reference` (it is used by `useSubjectName` in `useReferenceApi.ts:34`).

- [ ] **Step 2: Wire the routes.** In `web/src/portals/student/index.tsx`, replace the two studyplan lazy imports (`:44-49`) with:

```tsx
const StudyPlanScreen = lazy(() =>
  import("./screens/studyplan/StudyPlanScreen").then((m) => ({ default: m.StudyPlanScreen })),
)
```

Replace the two route entries (`:264-272`) with:

```tsx
    {
      path: "plan",
      element: <StudyPlanScreen />,
      handle: { title: "This week", skeleton: "page-header" },
    },
    {
      path: "plan/session/:sessionId",
      element: <StudyPlanScreen />,
      handle: { title: "This week", skeleton: "page-header" },
    },
    {
      path: "plan/:subjectCode",
      element: <StudyPlanScreen />,
      handle: { title: "This week", skeleton: "page-header" },
    },
    {
      path: "plan/:subjectCode/session/:sessionId",
      element: <StudyPlanScreen />,
      handle: { title: "This week", skeleton: "page-header" },
    },
```

React Router ranks the static `plan/session/:sessionId` above `plan/:subjectCode/...`, and the segment counts differ, so the routes cannot collide.

- [ ] **Step 3: Check it in the real app.** Run the web dev server against a local backend that has the seed (`web/README.md`). Visit `/student/plan`, `/student/plan/0625` and `/student/plan/0625/session/<id>` at 390, 834 and 1280. Check:
- every state in the frame table is reachable;
- the sheet opens and back closes it;
- Mark done, Move and Rebuild work end to end.

Run: `cd web && npx tsc -p tsconfig.app.json --noEmit && npx oxlint src/portals/student && npm run check:copy && npm run check:native && npx vitest run tests/unit/studyPlanModel.test.ts tests/unit/studyPlanCopy.test.ts tests/unit/studyPlanCache.test.ts tests/unit/navigation.test.ts tests/unit/studentShell.test.ts`
Expected: clean and green. (`navigation`/`studentShell` scan the student routes.)

- [ ] **Step 4: Commit.**

```bash
pre-commit run --files web/src/portals/student/screens/studyplan/StudyPlanScreen.tsx web/src/portals/student/index.tsx
git commit -S -m "feat(web): study plan screen across subjects with sheet and side panel" -- web/src/portals/student/screens/studyplan/StudyPlanScreen.tsx web/src/portals/student/index.tsx
```

---

# Tests

### Task 12: Playwright happy path, S-24 update, audit registry

**Files:**
- Create: `web/e2e/study-plan.spec.ts`
- Modify: `web/e2e/phase4-journey.spec.ts:241-264` (the S-24 test only)
- Modify: `web/scripts/audit.mjs:2279-2385` (the S-24/S-25 entries only)

**Interfaces:**
- Consumes: the seed contract `readSeed().practice.students.active` and `seed.studyPlan.{subjectCode, activeSessionId, activeSessionTopic, activeSessionCount, completedSessionCount}` (`web/e2e/seed.ts:244-250`), plus `injectSession` (`web/e2e/seed.ts:435`) and `watchConsole` (`web/e2e/console-errors.ts`).

- [ ] **Step 1: Write `web/e2e/study-plan.spec.ts`:**

```ts
import { test, expect, type Page } from "@playwright/test"
import { watchConsole } from "./console-errors"
import { injectSession, readSeed, type SeedAccount } from "./seed"

/*
 * L9 · the study plan's happy path on the account the seed gives a real
 * week (`practice.students.active`, enrolled in 0625, one weak topic).
 * The seed builds its plan on the real clock, so the week starts today.
 */

async function asStudent(page: Page, account: SeedAccount): Promise<void> {
  await injectSession(page, { accessToken: account.accessToken, userId: account.userId, role: "student" })
}

test("phone · today first, open a session, mark it done", async ({ page }) => {
  const seed = readSeed()
  const errors = watchConsole(page)
  await page.setViewportSize({ width: 390, height: 844 })
  await asStudent(page, seed.practice.students.active)

  await page.goto("/student/plan")
  await expect(page.getByRole("heading", { name: /^Today · / })).toBeVisible({ timeout: 15_000 })
  await expect(page.getByText(new RegExp(`\\d+ of ${seed.studyPlan.activeSessionCount} done`))).toBeVisible()

  const row = page.getByRole("button", { name: new RegExp(seed.studyPlan.activeSessionTopic) }).first()
  await row.click()
  const sheet = page.getByRole("dialog")
  await expect(sheet.getByText("Why this?")).toBeVisible()
  await expect(page).toHaveURL(/\/student\/plan\/session\//)

  await sheet.getByRole("button", { name: "Mark done" }).click()
  await expect(sheet.getByText("Done", { exact: true })).toBeVisible()

  await page.keyboard.press("Escape")
  await expect(page).toHaveURL(/\/student\/plan$/)
  expect(errors, JSON.stringify(errors, null, 2)).toEqual([])
})

test("phone · a deep link opens the sheet, filtered to its subject", async ({ page }) => {
  const seed = readSeed()
  const errors = watchConsole(page)
  await page.setViewportSize({ width: 390, height: 844 })
  await asStudent(page, seed.practice.students.active)

  await page.goto(`/student/plan/${seed.studyPlan.subjectCode}/session/${seed.studyPlan.activeSessionId}`)
  await expect(page.getByRole("dialog").getByText("Why this?")).toBeVisible({ timeout: 15_000 })

  // An id that is not in this week says so, and is not an error.
  await page.goto(`/student/plan/${seed.studyPlan.subjectCode}/session/00000000-0000-4000-8000-000000000000`)
  await expect(page.getByText("That session isn’t in this week’s plan.", { exact: false })).toBeVisible({ timeout: 15_000 })
  expect(errors, JSON.stringify(errors, null, 2)).toEqual([])
})

test("phone · move an open session to a later day", async ({ page }) => {
  const seed = readSeed()
  const errors = watchConsole(page)
  await page.setViewportSize({ width: 390, height: 844 })
  await asStudent(page, seed.practice.students.active)

  await page.goto("/student/plan")
  await expect(page.getByRole("heading", { name: /^Today · / })).toBeVisible({ timeout: 15_000 })
  const openRow = page.getByRole("list", { name: /Today's sessions|Later/ }).getByRole("button").first()
  await openRow.click()
  const sheet = page.getByRole("dialog")
  const moveButton = sheet.getByRole("button", { name: "Move" })
  // On a Sunday nothing is left in the week to move to, and the control is absent.
  if ((await moveButton.count()) > 0) {
    await moveButton.click()
    const target = sheet.getByRole("group", { name: "Move to" }).getByRole("button").last()
    const label = (await target.textContent())?.trim() ?? ""
    await target.click()
    await expect(page.getByText(`Moved to ${label}`)).toBeVisible()
  } else {
    await expect(moveButton).toHaveCount(0)
  }
  expect(errors, JSON.stringify(errors, null, 2)).toEqual([])
})

test("desktop · list with a side panel that follows the row", async ({ page }) => {
  const seed = readSeed()
  const errors = watchConsole(page)
  await page.setViewportSize({ width: 1280, height: 820 })
  await asStudent(page, seed.practice.students.active)

  await page.goto("/student/plan")
  const panel = page.getByRole("complementary", { name: "Session" })
  await expect(panel.getByText("Why this?")).toBeVisible({ timeout: 15_000 })
  await expect(page.getByRole("dialog")).toHaveCount(0)
  expect(errors, JSON.stringify(errors, null, 2)).toEqual([])
})
```

- [ ] **Step 2: Update the S-24 test** in `web/e2e/phase4-journey.spec.ts`. Replace the body of `test("S-24 · the student receives a study plan with concrete sessions", …)` (`:241-264`) with:

```ts
  const seed = readSeed()
  const errors = watchConsole(page)
  await asStudent(page, seed.practice.students.active)

  await page.goto(`/student/plan/${seed.studyPlan.subjectCode}`)

  // Not pinned to 0 done: study-plan.spec.ts marks a session done on this
  // same seeded account and runs in the same suite.
  await expect(
    page.getByText(new RegExp(`· ${seed.studyPlan.activeSessionCount} sessions? ·`)),
  ).toBeVisible({ timeout: 15_000 })
  await expect(page.getByText(seed.studyPlan.activeSessionTopic).first()).toBeVisible()

  // Neither honest not-a-plan state.
  await expect(page.getByText("I need a paper first")).toHaveCount(0)
  await expect(page.getByText("Let’s plan your week")).toHaveCount(0)

  expect(errors, `console/page errors: ${JSON.stringify(errors, null, 2)}`).toEqual([])
```

The filtered header reads "Physics · N sessions · …". If `activeSessionCount` is 1 the "sessions?" regex still matches. The old file-header comment's "Trap 1" note (`:28-32`) now refers to a deleted string. Update that sentence to point at the new header regex.

- [ ] **Step 3: Update the audit registry** (`web/scripts/audit.mjs`) ready predicates, keeping slugs and screen ids:
  - S-24 default: `` waitForText(page, `0 of ${seed.studyPlan.activeSessionCount} done`) ``. The path stays `studyPlanWeekUrl`, which is filtered, so use `` `· ${seed.studyPlan.activeSessionCount} session` `` if `0 of` is absent there. Check the filtered header against Task 6 (`"Physics · N sessions · …"`) and use that.
  - `refused`: `waitForText(page, "I need a paper first")`
  - `not-generated`: `waitForText(page, "Let’s plan your week")`
  - `week-complete`: `waitForText(page, "Week done.")`
  - S-25 default: `waitForText(page, "has cost you")` (the seeded session's topic is a recorded weakness, so the reason is `marks_lost`)
  - `not-in-current-week`: `waitForText(page, "isn’t in this week’s plan")`
  - Update the S-24/S-25 comment block at `:1349-1367`, which describes "four states", to name the new copy.

- [ ] **Step 4: Run.**

Run: `cd web && npx playwright test e2e/study-plan.spec.ts e2e/phase4-journey.spec.ts -g "S-24|study"` (needs the seeded backend that `playwright.config.ts`'s global setup starts).
Expected: all pass.

- [ ] **Step 5: Commit.**

```bash
pre-commit run --files web/e2e/study-plan.spec.ts web/e2e/phase4-journey.spec.ts web/scripts/audit.mjs
git commit -S -m "test(web): study plan happy paths and updated S-24/S-25 registry" -- web/e2e/study-plan.spec.ts web/e2e/phase4-journey.spec.ts web/scripts/audit.mjs
```

---

# Final tasks

### Task 13: Fidelity screenshots, drift fixes, polish

**Files:**
- Modify: any file under `web/src/portals/student/screens/studyplan/` that drift calls for.
- Artifacts: `.omc/artifacts/l09/` (not committed).

- [ ] **Step 1: Serve the mock.** Run `python3 -m http.server 4174 --directory .impeccable/mocks` and open `http://localhost:4174/student-r2/plan-final.html`.

- [ ] **Step 2: Capture side by side.** For each frame, capture mock and app at 390 and at 1280 (SD, and a desktop capture of each full state). Use Playwright, or the `webapp-testing` skill, against the mock element `#<frame id>` and the app route in the matching state. Frames and states:
  - WA, WM, SS, Z0, Z1, PD, PR, PX, PL, PE: phone
  - SD: desktop

Save pairs as `.omc/artifacts/l09/<frame>-<width>-{mock,app}.png`.

- [ ] **Step 3: Fix visible drift.** Fix spacing, type sizes, row padding (HairRow `big`), radii, the strip, the missed bar and the sheet paddings. Note each fix for the PR's "small changes" list. Do not change layout, flow or content. Anything of that kind goes to Needs user decision.

- [ ] **Step 4: Polish.** Run `/impeccable polish` on the studyplan directory, then re-capture the pairs that changed.

- [ ] **Step 5: Re-run the touched tests and gates, then commit.**

Run: `cd web && npx tsc -p tsconfig.app.json --noEmit && npx oxlint src/portals/student/screens/studyplan && npm run check:copy && npm run check:native && npx vitest run tests/unit/studyPlanModel.test.ts tests/unit/studyPlanCopy.test.ts tests/unit/studyPlanCache.test.ts`

```bash
git commit -S -m "fix(web): study plan fidelity drift and polish" -- web/src/portals/student/screens/studyplan
```

---

### Task 14: Keep-list check and deleting the old code

**Files:**
- Delete:
  - `web/src/portals/student/screens/studyplan/StudyPlanWeek.tsx`
  - `web/src/portals/student/screens/studyplan/StudyPlanSession.tsx`
  - `web/src/portals/student/screens/studyplan/studyPlanData.ts`
  - `web/tests/unit/studyPlan.test.ts`
  - `web/tests/unit/studyPlanHeader.test.ts`
  - `web/tests/unit/activityIcon.test.ts`
- Modify: `web/src/lib/hooks/useStudyPlanApi.ts` (remove `useCurrentStudyPlan` and `useRebuildStudyPlan`)
- Modify: `web/tests/unit/utilityExistence.test.ts:99-100` and `web/tests/unit/rtlSafety.test.ts:142-143`, replacing the two old paths with the new `.tsx` files:
  - `PlanHeader.tsx`
  - `PlanList.tsx`
  - `PlanStates.tsx`
  - `SessionDetail.tsx`
  - `SessionRow.tsx`
  - `StudyPlanScreen.tsx`
  - `WeekStrip.tsx`
  - `MissedGroup.tsx`
  - `BasedOn.tsx`
  - `icons.tsx`
- Modify: the comments only in `web/tests/unit/countdown.test.ts:6` and `web/tests/unit/announcements.test.ts:70`, which name `StudyPlanWeek.tsx`. Point them at `planCopy.ts`.

- [ ] **Step 1: Confirm nothing else imports the old code.**

Run: `grep -rn "StudyPlanWeek\|StudyPlanSession\b\|studyPlanData\|useCurrentStudyPlan\|useRebuildStudyPlan\b" web/src web/tests web/e2e web/scripts`
Expected: hits only in the files being deleted or edited in this task.

- [ ] **Step 2: Delete, edit, and run the gates.**

Run: `cd web && npx tsc -p tsconfig.app.json --noEmit && npx oxlint src && npm run check:copy && npm run check:native && npx vitest run tests/unit/utilityExistence.test.ts tests/unit/rtlSafety.test.ts tests/unit/countdown.test.ts tests/unit/announcements.test.ts tests/unit/navigation.test.ts tests/unit/studentShell.test.ts tests/unit/studyPlanModel.test.ts tests/unit/studyPlanCopy.test.ts tests/unit/studyPlanCache.test.ts`
Expected: green.

Then the Python sweep for every touched backend file and the lint tests that scan it:

Run: `PYTHONPATH=$PWD pytest tests/test_study_plan_repo.py tests/test_web_study_plan.py tests/test_authz_matrix_complete.py tests/test_authz_matrix.py tests/test_widget_router.py tests/test_soft_delete_readers.py tests/test_study_plan_schema.py tests/test_seed_e2e.py -q`
Expected: green.

- [ ] **Step 3: Tick the keep-list.** Go through K1–K47 in this plan one by one against the running app and the code. Paste the ticked table into the PR body, with the evidence for each (a screenshot path, a test name, or file:line).

- [ ] **Step 4: Scan for placeholders.** Search the changed files for `TODO`, `FIXME`, `test.skip`, `.only` and stub bodies.

Run: `git diff origin/develop --name-only | xargs grep -n "TODO\|FIXME\|test\.skip\|\.only(" || true`
Expected: no hits.

- [ ] **Step 5: Commit.**

```bash
git rm web/src/portals/student/screens/studyplan/StudyPlanWeek.tsx web/src/portals/student/screens/studyplan/StudyPlanSession.tsx web/src/portals/student/screens/studyplan/studyPlanData.ts web/tests/unit/studyPlan.test.ts web/tests/unit/studyPlanHeader.test.ts web/tests/unit/activityIcon.test.ts
pre-commit run --files web/src/lib/hooks/useStudyPlanApi.ts web/tests/unit/utilityExistence.test.ts web/tests/unit/rtlSafety.test.ts web/tests/unit/countdown.test.ts web/tests/unit/announcements.test.ts
git commit -S -m "refactor(web): remove the old study plan week and session screens" -- web/src/portals/student/screens/studyplan/StudyPlanWeek.tsx web/src/portals/student/screens/studyplan/StudyPlanSession.tsx web/src/portals/student/screens/studyplan/studyPlanData.ts web/tests/unit/studyPlan.test.ts web/tests/unit/studyPlanHeader.test.ts web/tests/unit/activityIcon.test.ts web/src/lib/hooks/useStudyPlanApi.ts web/tests/unit/utilityExistence.test.ts web/tests/unit/rtlSafety.test.ts web/tests/unit/countdown.test.ts web/tests/unit/announcements.test.ts
```

---

### Task 15: Push and open the PR

- [ ] **Step 1: Update the graph and rebase.** Run `graphify update .`, then rebase on `origin/develop` and resolve any conflicts in the shared files (`web/src/portals/student/index.tsx`, `tests/test_authz_matrix_complete.py`). Re-run Task 14's two sweep commands after the rebase.

- [ ] **Step 2: Push the branch.** Run `git push -u origin redesign/l09-study-plan`. Never push to `main`.

- [ ] **Step 3: Open the PR to `develop`.** The body includes:
  - a summary;
  - the ticked keep-list;
  - the frame-to-state table;
  - the small changes from the mock: the token mappings, "!" → ".", "Cost you N marks", the shell sheet motion, the dropped canvas gradient, and the frameless states with their copy;
  - the fidelity pairs (paths);
  - the run commands used;
  - "no migration";
  - the open items from Needs user decision.

  Run: `gh pr create --base develop --title "feat: study plan redesign (L9)" --body-file <scratch file>`

- [ ] **Step 4: Review.** Request the Opus review (the master's per-lane workflow), fix what it finds, get CI green, then merge.

---

## Needs user decision

None of these block the lane. Each has a recommendation, and the plan builds the recommended option.

1. **"!" in Binny and celebration lines** ("Week done!", "15 minutes today!"). `npm run check:copy` bans `!` in product copy, and its allowlist is empty. **Recommend:** ship full stops now, and decide `!` once at master level for every lane, because L1, L3 and L10 have the same problem.
2. **Subject dots and two tile hues are not tokens.** DESIGN.md says subjects are not colour-coded. The mock uses three hues, plus a violet tile for flashcards. **Recommend:** keep the dots, using a token rotation (`grade-a`, `primary`, `secondary`). Map flashcard tiles to `secondary-container` and review tiles to `surface-container-high`. No token changes.
3. **"7 marks to go" in the filtered top line.** This needs the A* line from the boundary table, which is L2's domain. **Recommend:** drop it here (target + "Paper 4 in 188 days" only). Add it when L2 exposes a per-subject gap.
4. **Week-done stats.** "+21 marks back" and "Vectors and Waves moved up" are not tracked anywhere. **Recommend:** show sessions done, XP this week and the streak (all real). Drop the "moved up" sentence.
5. **The today ring's three parts.** The plan computes them as practice today, flashcards today, and a past paper this week, done over planned. A goal with nothing planned stays grey. **Recommend:** align with L1's Home ring once `GET /student/home` lands, so the two rings never disagree.
6. **Stated weekly hours are gone.** The live header said "1h 35m planned of the 11h you said you had" (K11). The mock shows only the planned total. **Recommend:** follow the mock.
7. **"Plan next week"** needed a small backend addition (`week: "next"`), and next week's plan stays invisible until Monday (a toast says "Next week is ready for Monday"). **Recommend:** keep it as built. The alternative is to drop the button and make "Bonus practice" primary.
8. **"Any day this week" means past papers.** The backend has no flexible-day concept, so `anyDay` is derived server-side from `activity_type == past_paper`, which is what the mock shows. **Recommend:** keep it. A real per-session flag would need a migration.
9. **The scheduler spills past Sunday.** Sessions start at `now.date()`, so a plan built on Thursday runs to next Wednesday. The plan shows those days as "Next Mon" groups and allows moves up to the plan's last day. On Monday those sessions disappear with the old week. **Recommend:** clamp `build_study_plan` to the ISO week in a follow-up core change, outside this lane.
10. **Rebuild now asks first** when any session in scope is done, because a rebuild starts the week's view fresh. **Recommend:** keep the confirmation (the spec says destructive actions confirm).
