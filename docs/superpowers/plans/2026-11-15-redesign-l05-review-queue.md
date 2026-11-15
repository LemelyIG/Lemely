# L5 Teacher Review Queue Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `Review.tsx` and `ReviewItem.tsx` with the approved review queue (`.impeccable/mocks/review-r1/final2.html` + `final2.css` + `review3.js`, plus the review-queue frames `RQ1`–`RQ3` in `.impeccable/mocks/states-r1/s.js`). Also add the backend it needs: a whole-page image route, and sort, multi-filter and search on the queue list. Every live feature stays.

**Architecture:** One screen component, `review/ReviewQueue.tsx`, is mounted on both existing routes (`/teacher/review` and `/teacher/review/:itemId`). The URL holds the focused item plus every filter and the sort. At 721px and up it renders a list column and a sticky side panel. Below 721px the list is full-width, and `/teacher/review/:itemId` is a full-screen answer page (the route is already `immersive`). All decisions live in pure modules with Vitest coverage: `reviewQueueModel.ts` for the queue, `markModel.ts` for the tick stepper, `answerView.ts` for the panel, and `pendingDecisions.ts` for collapse and undo. The components stay thin. The answer panel is exported from `review/index.ts` so L8 can reuse it read-only for a student's paper.

**Tech Stack:**
- FastAPI and SQLAlchemy (`lemely/web/routers/review.py`, `lemely/db/review_repo.py`, `lemely/web/schemas_review.py`), plus PyMuPDF and Pillow in the interactive sandbox (`lemely/io/scan_render.py`)
- React 19, react-router 7, TanStack Query and Tailwind 4
- F1 kit from `web/src/components/redesign`
- Vitest (node environment, no jsdom) and Playwright

## Global Constraints

Inherits master plan Global Constraints (`docs/superpowers/plans/2026-11-15-redesign-00-master.md`). Lane-specific additions:

- **Owned files:**
  - `web/src/portals/teacher/screens/Review.tsx` and `ReviewItem.tsx` (both deleted in Task 13)
  - `web/src/portals/teacher/screens/review/**`
  - `web/src/lib/reviewQueueQuery.ts` and `web/src/lib/reviewApi.ts` (new)
  - the review block of `web/src/lib/hooks/useTeacherApi.ts`, `useReviewQueue` through `useDismissReviewItem` (currently lines 332–606)
  - the review block of `web/src/lib/teacherTypes.ts` (lines 650–end of the review types)
  - `lemely/web/routers/review.py`, `lemely/web/schemas_review.py`, `lemely/db/review_repo.py` (list, detail and crop-source paths only)
  - the new `page_*` functions in `lemely/io/scan_render.py`
  - `tests/test_web_review.py` (append only), `tests/test_scan_render.py` (append only)
  - `web/e2e/teacher-review.spec.ts`, `web/e2e/review-queue.spec.ts` (new), and the unit tests named in each task
- **Shared-file edits:** in `web/src/portals/teacher/index.tsx`, only lines 62–63 (the two lazy imports) and the two route entries at 522–531. This app keeps its teacher routes there, not in `web/src/routes.tsx`.
- **Breakpoints:** the shell's own. The phone layout is below 721px (`PHONE_MEDIA` in `web/src/lib/useNativeFrame.ts`, Tailwind `shell-sm:` at 721px and up). The mock's 768px phone edge maps to 721px. The mock's 1280px rail edge maps to the shell's `sidebar` behaviour, which `PortalShell` owns.
- **No migration.** Every field the screen needs already exists in the database (`question_result_points.tariff/mark_type/group_key/group_max_marks/ordinal`, `question_results.review_reason/source_box_page`).
- **Confidence colours:** `CLEAR_CONFIDENCE = 0.7`, defined once in `review/reviewQueueModel.ts`. Below it the ring is error red; from it the ring is gold. Null means a neutral ring with "–". "Approve clear" counts only non-integrity items at 0.7 or above. See Needs user decision #1.
- **Teacher Binny:** a small head-crop, at most once per screen state, and only in calm states (first run, nothing waiting, queue clear). Never on a busy queue.
- **Vitest is node-only.** Hooks and components are covered by Playwright. Every decision lives in a pure module that Vitest tests.
- Run `graphify update .` after code changes (project CLAUDE.md).

**Run commands used throughout** (from the worktree root):
- pytest: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/python -m pytest tests/test_web_review.py -k l5_ -v`. This needs local Postgres; without it the tests are skipped, so make sure Postgres is up.
- Vitest: `cd web && npx vitest run tests/unit/<file>.test.ts`
- Types: `cd web && npx tsc -b --noEmit`
- Lint: `cd web && npx oxlint src/portals/teacher/screens/review src/lib/reviewQueueQuery.ts src/lib/reviewApi.ts && npm run check:native && npm run check:copy`
- pre-commit: `PYTHONPATH=$PWD pre-commit run --files <touched files>`

---

## File structure

| File | Responsibility |
|---|---|
| `lemely/db/review_repo.py` | `ReviewQueueRow.review_reason`; `ReviewItemPoint` structure fields; `ReviewItemDetail.source_page`; `review_sort_key`; `list_queue` multi-filter, search, sort, facets and `has_history` |
| `lemely/web/schemas_review.py` | DTO fields `reviewReason`, point structure, `sourcePage`, `subjectCodes`, `hasHistory` |
| `lemely/web/routers/review.py` | list params (`class_id`/`reason`/`subject` repeatable, `q`, `sort`), per-sort cursor, shared scan renderer, `GET /{item_id}/page` |
| `lemely/io/scan_render.py` | `outline_box_png`, `page_pdf_scan`, `page_image_scan` |
| `web/src/lib/teacherTypes.ts` | wire types for the new fields |
| `web/src/lib/reviewQueueQuery.ts` | pure URL and filter codec, plus the API path builder |
| `web/src/lib/reviewApi.ts` | `ReviewDecision` and `postReviewDecision` (keepalive capable) |
| `web/src/lib/hooks/useTeacherApi.ts` | `useReviewQueuePage`, `useReviewItemImage` (crop and page), and `useReviewItemCrop` kept as a thin wrapper |
| `review/reviewLabels.ts` | labels and predicates moved out of `Review.tsx` (reason labels, integrity, console, paper identity, confidence tone, page merge, filter options, skip labels) |
| `review/reviewQueueModel.ts` | every queue decision: ring tone, row copy, plain "why" line, clear set, bulk label, screen state, Binny, header, chips, menus, sort, focus |
| `review/markModel.ts` | ticks, either/or and pool caps, stepper, total, delta line, action label, breakdown, resolve body |
| `review/answerView.ts` | `AnswerView` adapter from `ReviewItemDetail` (the L8 seam) |
| `review/pendingDecisions.ts` | reducer for collapse, undo, commit, conflict, failure and tally |
| `review/usePendingDecisions.ts` | timers, flush on leave, keepalive commit |
| `review/useAnswerImages.ts` | crop always, whole page on demand |
| `review/ReviewQueue.tsx` | route screen: data, URL, focus, keyboard, bulk, layout switch |
| `review/QueueColumn.tsx` | the left column: header, tools, filters, rows, Load more, inline states |
| `review/QueueHeader.tsx` | big count, title, progress bar |
| `review/FilterBar.tsx`, `SortMenu.tsx`, `FilterMenu.tsx` | M3 filters and the themed sort menu |
| `review/QueueRow.tsx` | one row: select box, KeyRing, name, why, mark |
| `review/QueueStates.tsx` | `FirstRun`, `SparseNote`, `NoMatch`, `QueueLoading`, `QueueError`, `Cleared`, `NothingWaiting` |
| `review/AnswerPanel.tsx` | the panel (exported) |
| `review/AnswerPage.tsx` | phone full-screen wrapper (exported) |
| `review/MarkControls.tsx` | stepper and tick list |
| `review/UndoBar.tsx` | the dark undo toast tied to the 5s commit timer |
| `review/review.css` | the keyframes `lm-rq-bump` and `lm-rq-skel`, plus the ruled answer card. No tokens. |
| `review/index.ts` | public exports for L8 |

---

## Keep-list (live features that must survive)

The final task (Task 13) ticks each item off in the PR body. An item marked "→" carries over in a new form.

### `web/src/portals/teacher/screens/Review.tsx`
- [ ] **K1** Filters are server-side and kept in the URL, never re-filtered client-side (`Review.tsx:277-286, 329-339`) → `reviewQueueQuery.ts`, which adds `q`, `subject` and `sort`.
- [ ] **K2** The reason filter offers only reasons the pipeline produces: Low confidence, Matches mark-scheme wording, Student challenged a mark (`:218-225`). It never offers `manual` or `random_audit`.
- [ ] **K3** The waiting-age filter: 6+ hours, 24+ hours, 3+ days, 7+ days (`:227-233`) → the "Waiting" category in "+ Filter".
- [ ] **K4** Class options come from `useTeacherClasses()` (`:433-445`) → the "Class" category.
- [ ] **K5** `REASON_LABEL` and `reasonLabel` fall back to the raw value, and include "Student challenged a mark" (`:88-105`) → `reviewLabels.ts`.
- [ ] **K6** Integrity flags can never be bulk-selected (`:350-369, 668-680`) → `selectable()`. The row box is dimmed and the tap does nothing.
- [ ] **K7** Console-paper rows get no student link, no avatar, and "Grading console" as their identity (`:125-127, 691-719`) → `rowSubtitle()`.
- [ ] **K8** An item with no subject reads "Quiz question" (`:133-149`).
- [ ] **K9** One confidence threshold; a null score is "warn" (`:209-216`) → `confidenceTone` is kept in `reviewLabels.ts`. The ring uses `ringTone` (see Needs user decision #1).
- [ ] **K10** Bulk approve is skip-and-report. A snapshot resolves the skipped ids to "Name — Q4" plus the skip reason (`:235-239, 371-379, 571-601`) → the bulk result notice in `QueueColumn`.
- [ ] **K11** A failed bulk approve shows "Couldn't approve: …" (`:565-569`).
- [ ] **K12** Bulk shows a pending label (`:553-555`) → "Approving…".
- [ ] **K13** The selection resets when filters change (`:324-327`).
- [ ] **K14** "Load more" cursor pagination, with pages merged and deduped by id (`:267-274, 288-320, 830-841`).
- [ ] **K15** Empty states: "nothing waiting" versus "no matches", the latter with Clear filters (`:517-530`) → `NothingWaiting`, `FirstRun` and `NoMatch`.
- [ ] **K16** The load error uses `teacherLoadFailureMessage` and has a skeleton (`:383-396`) → `QueueError` and `QueueLoading`.
- [ ] **K17** A native filter modal with an applied-count badge (`:409-430, 478-504`) → the M3 filter row works on phone too. Chips show what is applied.
- [ ] **K18** Opening a row carries the filter query string to the detail URL (`:609, 806-810`).
- [ ] **K19** The student link goes to `/teacher/students/:id` (`:759-765`) → the panel title links to the student (attempt rows only).
- [ ] **K20** Waiting time (`:780-782`) → the "Waiting" filter and the "Oldest" sort. The row no longer shows it (Needs user decision #10).
- [ ] **K21** The AI mark x/y and the confidence % (`:790-800`) → the row's mark and its ring.
- [ ] **K22** The table/list view toggle with `storageKey` (`:536-537`) → dropped. The single list replaces both views (Needs user decision #10).

### `web/src/portals/teacher/screens/ReviewItem.tsx`
- [ ] **I1** The detail fetch. 403, 404 and 422 render "Couldn't load this answer" with Try again and Back to queue (`:647-684`).
- [ ] **I2** No item selected (`:665-671`) → on desktop the first visible item is focused; on phone the list shows.
- [ ] **I3** The crop is fetched only when `hasSourceBox` is set. Any failure, decode errors included, renders as absence (`:592-595, 799-812`).
- [ ] **I4** The transcription is labelled as Lemely's reading, not the scan (`:778-825`) → the caption "Lemely's reading of the answer" on the transcription card.
- [ ] **I5** The expected answer (`:826-837`) → inside "Mark scheme wording".
- [ ] **I6** The topic (`:839`) → inside "Mark scheme wording".
- [ ] **I7** The confidence %, or "unavailable" (`:848-854`) → the ring in the row, and "64% sure" in the panel subtitle.
- [ ] **I8** The raw review reason (`:856-865`) → inside "Lemely's notes".
- [ ] **I9** Lemely's feedback (`:866-875`) → inside "Lemely's notes".
- [ ] **I10** Per-point marker verdicts (awarded, withheld, unverifiable), the evidence span, ECF and the rationale (`:251-308`) → each tick row carries a verdict label, a "Carried forward" tag and a note line.
- [ ] **I11** The `matchedPointIds` fallback and "No points matched" (`:886-906`) → shown under the stepper when `points` is empty.
- [ ] **I12** The student's self-review per point: claim, judge verdict, evidence (`:193-231`) → the "Student said" block.
- [ ] **I13** The integrity panel says the flag is a signal, not a verdict; Dismiss takes an internal note; the closed status shows (`:911-931, 319-350`).
- [ ] **I14** Accept as-is with an internal note (`:425-447`).
- [ ] **I15** Adjust marks: 0..max validation, the method/accuracy/other breakdown, breakdown notes, a note to the student (`:449-513`) → the tick stepper is clamped by construction and the breakdown is derived from the ticks (Needs user decision #6).
- [ ] **I16** The reasons a mark can't be adjusted: console paper, or no question result (`:381-384`) → stepper and ticks disabled, with the same copy.
- [ ] **I17** A failed resolve shows "Couldn't save: …" (`:515-519`) → an error notice in the undo bar, and the row comes back.
- [ ] **I18** The resolved or dismissed chip and the resolution note (`:730-734, 938-940`) → the panel's read-only mode.
- [ ] **I19** The teacher correction on record (`:942-958`) → the panel's read-only mode.
- [ ] **I20** "Item N of M" with prev/next carrying the filter query string (`:535-571, 740-746`) → the panel nav "2 of 6" with ‹ ›.
- [ ] **I21** Shortcuts A, N and Esc, inert in inputs and with modifier keys, plus a visible hint (`:622-643, 748-766`) → A, N, J, K, / and Esc, with a quiet hint line at 1280px and up.
- [ ] **I22** After a decision, move to the next item, falling back to the queue (`:614-620`) → desktop focuses the next row; phone returns to the list (Needs user decision #14).
- [ ] **I23** The header shows name, class, paper and question (`:702-737`).
- [ ] **I24** The deep link `/teacher/review/:itemId` with the `immersive` handle (`portals/teacher/index.tsx:528-531`).

### Backend and hooks
- [ ] **B1** The staff role gate, roster-union tenancy and no `platform_admin` bypass (`review.py:80-85`; `review_repo.py:400-535`).
- [ ] **B2** `limit` outside 1..200 is a 422; a malformed cursor is a 422; a malformed `class_id` is a 422 (`review.py:264-278`).
- [ ] **B3** `total` ignores cursor and limit.
- [ ] **B4** The crop route: 403 parity with detail, one uniform 404 for absence, `no-store`, sandboxed render (`review.py:346-484`). The page route matches it.
- [ ] **B5** Resolve answers 409 and 422 correctly, and dismiss answers 422 for non-integrity items (`review.py:516-575`).
- [ ] **B6** The resolve invalidation fan-out covers review, student, class, classes, at-risk and overview (`useTeacherApi.ts:566-585`).
- [ ] **B7** The sidebar and tab badge from `useReviewQueueCount` are unchanged.
- [ ] **B8** The R8 unshare filter (`review_repo.py:466-475`).
- [ ] **B9** Console items are left out when a class filter is set (`review_repo.py:478-485`).

---

## Frame-to-state table

| Mock frame (file → id or state) | Real state | Breakpoint | Trigger |
|---|---|---|---|
| final2 `kit: Queue` | `queue`: column plus panel | 721px and up: split. Below 721: list only | `queueScreenState() === 'queue'` |
| final2 row `.row.on` | focused row (`aria-current="true"`, 2px primary ring, white background) | 721px and up | URL `:itemId`, or the first visible row |
| final2 `#panel` (Answer view) | `AnswerPanel view="crop"` | 721px and up in the column; below 721 as `AnswerPage` | focus set |
| final2 `#panel` "Whole page" | `AnswerPanel view="page"` with an outlined page image | all | toggle; shown only when `hasScan` |
| final2 `body.detail #panelwrap` | `AnswerPage` full screen, with "Queue" back and sticky actions | below 721 | `/teacher/review/:itemId` on phone |
| final2 `body.sel` | select mode: boxes visible, bulk reads "Approve N selected" or "Pick answers to approve" | all | "Select" pressed |
| final2 `#menu step=cat` | filter menu, category step | all | "+ Filter" |
| final2 `#menu step=<cat>` | filter menu, value step with ticks and "‹ Category" | all | category picked |
| final2 `#sortmenu` | sort menu open, `menuitemradio` items | all | sort button |
| final2 `#chips .rm` | applied filter chips with × | all | any filter set |
| final2 `#shown` | "Showing N of M" | all | filters active and items open |
| final2 `#nomatch` | `no-match` | all | filters active, open > 0, none shown |
| final2 `kit: Loading` | `loading`: 4 skeleton rows plus a panel block | panel block at 721px and up only | query pending |
| final2 `kit: Error` | `error`: "Couldn't load the review queue." | all | query error |
| final2 `.toast` | `UndoBar`, 5s | all | single decision |
| final2 toast "N approved." | `UndoBar` without Undo, 4s | all | bulk success |
| final2 `#done` | `cleared`: big number, "Queue clear.", summary, "Mark another class set", head-crop Binny (happy) | all | no open items and at least one decision this session |
| states-r1 `RQ1` | `first-run`: head-crop Binny (open), Walkthrough of 3 steps, "Mark papers", ghost rows | 721px and up | total 0, `hasHistory` false |
| states-r1 `RQ3` | `first-run` phone layout (no ghost rows, shorter copy) | below 721 | same |
| states-r1 `RQ2` | `sparse`: one row plus the "That's the only one." note, panel open | 721px and up (phone: row plus note) | open total === 1, no filters |
| (not in mock; live K15) | `nothing-waiting`: head-crop Binny (happy), "Nothing to review." | all | total 0, `hasHistory` true, 0 decisions this session |
| final2 tablet `.tbar` and drawer | `PortalShell` top bar and drawer (the shell wins) | 721–1247px | shell |
| final2 `.rail` | `PortalShell` rail | 1248px and up | shell |

---

## Interactions and motion

The mock's ease `--ease: cubic-bezier(.2,.8,.2,1)` equals the token `--ease-out`. The bump ease `cubic-bezier(.16,1,.3,1)` equals the token `--ease-expo`.

| Interaction | Exact values (source) | Reduced motion |
|---|---|---|
| Row collapse on decide | `opacity 0; transform translateX(24px); max-height 0; padding-block 0; border 0`; transitions `opacity .3s, transform .3s, max-height .35s` with `--ease-out`; base row `max-height: 100px` (`final2.css` `.row`, `.row.gone`) | no transition; the row is removed at once |
| Row restore on Undo | the same transition in reverse (class removed) | instant |
| Count bump when the left count changes | `@keyframes bump {0%{transform:translateY(8px) scale(.9);opacity:.4}60%{transform:scale(1.08)}100%{transform:none;opacity:1}}`, `.35s cubic-bezier(.16,1,.3,1)` | no animation |
| Progress bar | `width` transition `.5s` `--ease-out` | instant |
| Queue clear number | the bump keyframes, `.6s cubic-bezier(.16,1,.3,1)`, 120px display | static |
| Undo toast | from `translate(-50%,20px); opacity 0` to `translate(-50%,0); opacity 1`, `.25s` `--ease-out` | opacity only, no translate |
| Button press | `transform: scale(.97)`, `.15s` `--ease-out` (`base.css .btn:active`) | none |
| Tick toggle | background `.15s` | none |
| Skeleton pulse | `@keyframes skp {50%{opacity:.55}}`, `1.6s ease-in-out infinite` | no animation |
| Menus (sort, filter) | no motion in the mock: display toggle | none |
| Phone row → answer page | the shell's native push (`nativePushDefault`) | the shell's own fallback |

Keyboard (inert in inputs, textareas and selects, and with Meta, Ctrl or Alt):
- `/` focuses search
- `j` and `k` move focus down and up
- `a` accepts the focused item at its current mark (non-integrity, open only)
- `n` goes to the next item
- `Esc` closes an open menu first, then on phone goes back to the list

---

## Task 1: Backend: queue reason line, point structure, source page

**Files:**
- Modify: `lemely/db/review_repo.py` (`ReviewQueueRow` ~182-220, `ReviewItemPoint` ~277-310, `ReviewItemDetail` ~312-340, `get_item` ~537-618, `_to_row` ~1290-1325, `_to_console_row` ~1410-1449)
- Modify: `lemely/web/schemas_review.py`
- Modify: `lemely/web/routers/review.py` (`_row_to_dto`, `_point_to_dto`, `_detail_to_dto`)
- Test: `tests/test_web_review.py` (append)

**Interfaces:**
- Produces:
  - `ReviewQueueRow.review_reason: str | None = None`
  - `ReviewItemPoint.ordinal: int = 0`, `.mark_type: str | None = None`, `.tariff: int = 1`, `.group_key: str | None = None`, `.group_max_marks: int | None = None`
  - `ReviewItemDetail.source_page: int | None = None` (0-based)
  - Wire: `ReviewQueueItemDTO.reviewReason: str | None`; `ReviewItemPointDTO.ordinal/markType/tariff/groupKey/groupMaxMarks`; `ReviewItemDetailDTO.sourcePage: int | None` (1-based)

- [ ] **Step 1: Write the failing tests**

Add `MathMarkType` to the existing `from lemely.core.loose_schemas import (...)` block at the top of `tests/test_web_review.py`, then append:

```python
# ---------------------------------------------------------------------------
# L5 redesign: queue reason line, point structure, source page.
# ---------------------------------------------------------------------------


def _l5_grouped_scheme() -> MarkScheme:
    """p1 stands alone (M1); p2/p3 are an either/or pair (A1 or B1)."""
    return MarkScheme(
        metadata=_point_scheme().metadata,
        questions=[
            SchemeQuestion(
                id="1",
                marks=2,
                type=SchemeQuestionType.RECALL,
                answer_points=[
                    AnswerPoint(
                        id="p1", point="Expands the bracket", marks=1, math_mark_type=MathMarkType.M
                    ),
                    AnswerPoint(
                        id="p2", point="Constant -4 (exact)", marks=1, math_mark_type=MathMarkType.A
                    ),
                    AnswerPoint(
                        id="p3",
                        point="Follow-through quadratic",
                        marks=1,
                        math_mark_type=MathMarkType.B,
                        is_alternative=True,
                    ),
                ],
            ),
        ],
    )


def test_l5_queue_row_carries_the_markers_review_reason(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    student = _seed_user(pg_sessionmaker, Role.student, display_name="Layla")
    cls = class_service.create_class(teacher, "Maths 10B")
    assert cls.join_code is not None
    class_service.join_by_code(student, cls.join_code)
    question = _question("1", awarded=1, maximum=2)
    question.review_reason = "confidence 0.30 below review threshold 0.90"
    AttemptRepository(pg_sessionmaker).persist_correction(
        user_id=str(student), report=_report([question])
    )
    _use_review_service(client, review_service)
    _auth_as(client, teacher, Role.teacher)

    row = client.get("/api/teacher/review").json()["items"][0]
    assert row["reviewReason"] == "confidence 0.30 below review threshold 0.90"


def test_l5_detail_points_carry_tariff_type_order_and_either_or_group(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    student = _seed_user(pg_sessionmaker, Role.student, display_name="Layla")
    cls = class_service.create_class(teacher, "Maths 10B")
    assert cls.join_code is not None
    class_service.join_by_code(student, cls.join_code)
    AttemptRepository(pg_sessionmaker).persist_correction(
        user_id=str(student),
        report=_report([_question("1", awarded=1, maximum=2)]),
        mark_scheme=_l5_grouped_scheme(),
    )
    _use_review_service(client, review_service)
    _auth_as(client, teacher, Role.teacher)
    item_id = client.get("/api/teacher/review").json()["items"][0]["itemId"]

    points = client.get(f"/api/teacher/review/{item_id}").json()["points"]
    assert [p["markPointId"] for p in points] == ["p1", "p2", "p3"]
    assert [p["ordinal"] for p in points] == [0, 1, 2]
    assert [p["markType"] for p in points] == ["M", "A", "B"]
    assert [p["tariff"] for p in points] == [1, 1, 1]
    assert points[0]["groupKey"] is None
    assert points[0]["groupMaxMarks"] is None
    assert points[1]["groupKey"] is not None
    assert points[1]["groupKey"].startswith("alt:")
    assert points[2]["groupKey"] == points[1]["groupKey"]
    assert points[1]["groupMaxMarks"] == 1


def test_l5_detail_reports_the_one_based_source_page_only_when_a_box_exists(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
    storage_backend: FakeStorageBackend,
) -> None:
    boxed_teacher, boxed_id = _seed_boxed_review_item(
        pg_sessionmaker, class_service, storage=storage_backend, scan=_synthetic_scan()
    )
    boxless_teacher, boxless_id = _seed_boxed_review_item(
        pg_sessionmaker, class_service, storage=storage_backend, scan=_synthetic_scan(), page=None
    )
    _use_review_service(client, review_service)

    _auth_as(client, boxed_teacher, Role.teacher)
    assert client.get(f"/api/teacher/review/{boxed_id}").json()["sourcePage"] == _MARKED_PAGE + 1
    _auth_as(client, boxless_teacher, Role.teacher)
    assert client.get(f"/api/teacher/review/{boxless_id}").json()["sourcePage"] is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/python -m pytest tests/test_web_review.py -k l5_ -v`
Expected: FAIL. You get `KeyError: 'reviewReason'`, `KeyError: 'ordinal'` and `KeyError: 'sourcePage'`.

- [ ] **Step 3: Implement**

In `lemely/db/review_repo.py`:

1. `ReviewQueueRow`: append a last field.
```python
    review_reason: str | None = None
```
2. `_to_row(...)`: add the keyword `review_reason=qr.review_reason if qr is not None else None,` after `confidence_score=...`.
3. `_to_console_row(...)`: add `review_reason=question.review_reason if question is not None else None,` after `confidence_score=...`.
4. `ReviewItemPoint`: append the fields after `rationale`, with the docstring note shown.
```python
    # L5: the scheme structure the tick stepper needs. Snapshotted on
    # `QuestionResultPoint` (see its docstring); defaults keep every existing
    # constructor valid.
    ordinal: int = 0
    mark_type: str | None = None
    tariff: int = 1
    group_key: str | None = None
    group_max_marks: int | None = None
```
5. `ReviewItemDetail`: append after `has_source_box: bool = False`.
```python
    source_page: int | None = None
    """0-based page the answer box sits on, set only when ``has_source_box``.
    The page number is not a coordinate: the box itself never leaves the server."""
```
6. In `get_item`, inside the `ReviewItemPoint(...)` comprehension, add:
```python
                        ordinal=p.ordinal,
                        mark_type=p.mark_type,
                        tariff=p.tariff,
                        group_key=p.group_key,
                        group_max_marks=p.group_max_marks,
```
   After the `has_source_box = (...)` assignment (still inside the `with` block), add:
```python
            source_page = qr.source_box_page if has_source_box and qr is not None else None
```
   and pass `source_page=source_page,` to the `ReviewItemDetail(...)` return.

In `lemely/web/schemas_review.py`:
- `ReviewQueueItemDTO`: append
```python
    reviewReason: str | None = None
    """The marker's own reason text (``QuestionResult.review_reason``). Technical;
    the client maps it to a short plain line and never shows it raw in a row."""
```
- `ReviewItemPointDTO`: append
```python
    ordinal: int = 0
    markType: str | None = None
    tariff: int = 1
    groupKey: str | None = None
    groupMaxMarks: int | None = None
```
- `ReviewItemDetailDTO`: append after `hasSourceBox`
```python
    sourcePage: int | None = None
    """1-based page the answer is on, when ``hasSourceBox``. Labels the whole-page view."""
```
`ReviewItemDetailDTO` already has `reviewReason`, so do not add it twice.

In `lemely/web/routers/review.py`:
- `_row_to_dto`: add `reviewReason=row.review_reason,`
- `_point_to_dto`: add
```python
        ordinal=point.ordinal,
        markType=point.mark_type,
        tariff=point.tariff,
        groupKey=point.group_key,
        groupMaxMarks=point.group_max_marks,
```
- `_detail_to_dto`: add `sourcePage=detail.source_page + 1 if detail.source_page is not None else None,`

- [ ] **Step 4: Run the tests to verify they pass, plus the existing review suite**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/python -m pytest tests/test_web_review.py tests/test_review_repo.py -v`
Expected: PASS, including every pre-existing test.

- [ ] **Step 5: Commit**

```bash
PYTHONPATH=$PWD pre-commit run --files lemely/db/review_repo.py lemely/web/schemas_review.py lemely/web/routers/review.py tests/test_web_review.py
git commit -S -m "feat(review): reason line, point structure and source page on review DTOs" -- lemely/db/review_repo.py lemely/web/schemas_review.py lemely/web/routers/review.py tests/test_web_review.py
```

---

## Task 2: Backend: sort, multi-filters, search, facets, hasHistory

**Files:**
- Modify: `lemely/db/review_repo.py` (`list_queue`, `ReviewQueuePage`, `visible_rosters`, `_visible_rosters`, plus the new `review_sort_key`, `_search_text`, `_paper_code` and `_any_item_ever`)
- Modify: `lemely/web/routers/review.py` (`list_review_queue`, `_encode_cursor`, `_decode_cursor`)
- Modify: `lemely/web/schemas_review.py` (`ReviewQueueListDTO`)
- Test: `tests/test_web_review.py` (append), `tests/test_review_repo.py` (existing tests must still pass)

**Interfaces:**
- Consumes: `ReviewQueueRow.review_reason` (Task 1).
- Produces:
  - `ReviewSort = Literal["oldest", "lost", "confidence"]`
  - `SortKey = tuple[int, float, datetime, uuid.UUID]`
  - `review_sort_key(row, sort) -> SortKey`
  - `ReviewService.list_queue(..., class_ids=None, reasons=None, subject_codes=None, search=None, sort="oldest", cursor: SortKey | tuple[datetime, uuid.UUID] | None)`
  - `ReviewQueuePage.subject_codes: list[str]`, `.has_history: bool`
  - Wire: `GET /api/teacher/review?class_id=…&class_id=…&reason=…&reason=…&subject=…&q=…&min_age_hours=…&sort=oldest|lost|confidence&limit=&cursor=` returning `{items, nextCursor, total, subjectCodes, hasHistory}`

- [ ] **Step 1: Write the failing tests**

Give `_metadata` and `_report` an optional subject code. Existing callers keep `"9999"`:

```python
def _metadata(subject_code: str = "9999") -> ExamMetadata:
    return ExamMetadata(
        subject_code=subject_code,
        paper_number=1,
        paper_variant=1,
        session_month="May/June",
        session_year=2020,
    )


def _report(questions: list[CorrectedQuestion], subject_code: str = "9999") -> AccuracyReport:
    correction = CorrectionResult(metadata=_metadata(subject_code), questions=questions)
    # ...the rest of the body unchanged...
```

Append:

```python
def _l5_seed(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    *,
    teacher: uuid.UUID | None = None,
    class_name: str = "Maths 10B",
    student_name: str = "Layla",
    subject_code: str = "9999",
    questions: list[CorrectedQuestion],
) -> tuple[uuid.UUID, uuid.UUID, dict[str, uuid.UUID]]:
    """One student in one (new) class with one attempt. Returns
    ``(teacher, class_id, {question_id: review_item_id})``; the map holds the
    low-confidence row per question (a plagiarism question maps to its flag row)."""
    teacher = teacher or _seed_user(pg_sessionmaker, Role.teacher)
    student = _seed_user(pg_sessionmaker, Role.student, display_name=student_name)
    cls = class_service.create_class(teacher, class_name)
    assert cls.join_code is not None
    class_service.join_by_code(student, cls.join_code)
    attempt_id = AttemptRepository(pg_sessionmaker).persist_correction(
        user_id=str(student), report=_report(questions, subject_code)
    )
    ids: dict[str, uuid.UUID] = {}
    with pg_sessionmaker() as session:
        rows = session.execute(
            sa.select(ReviewQueueItem.id, QuestionResult.question_id)
            .join(QuestionResult, ReviewQueueItem.question_result_id == QuestionResult.id)
            .where(ReviewQueueItem.attempt_id == attempt_id)
        ).all()
        for item_id, question_id in rows:
            ids[question_id] = item_id
    return teacher, cls.class_id, ids


def _l5_three(pg_sessionmaker: sessionmaker[Session], class_service: ClassService) -> tuple[uuid.UUID, dict[str, uuid.UUID]]:
    teacher, _, ids = _l5_seed(
        pg_sessionmaker,
        class_service,
        questions=[
            _question("1", awarded=1, maximum=5, confidence_score=0.64),  # lost 4
            _question("2", awarded=3, maximum=4, confidence_score=0.58),  # lost 1
            _question("3", awarded=0, maximum=3, confidence_score=0.69),  # lost 3
        ],
    )
    return teacher, ids


def _l5_ids(body: dict[str, object]) -> list[str]:
    items = body["items"]
    assert isinstance(items, list)
    return [str(i["itemId"]) for i in items]


def test_l5_sort_by_marks_lost_puts_the_biggest_loss_first(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], class_service: ClassService, review_service: ReviewService
) -> None:
    teacher, ids = _l5_three(pg_sessionmaker, class_service)
    _use_review_service(client, review_service)
    _auth_as(client, teacher, Role.teacher)
    body = client.get("/api/teacher/review", params={"sort": "lost"}).json()
    assert _l5_ids(body) == [str(ids["1"]), str(ids["3"]), str(ids["2"])]


def test_l5_sort_by_confidence_puts_the_least_sure_first(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], class_service: ClassService, review_service: ReviewService
) -> None:
    teacher, ids = _l5_three(pg_sessionmaker, class_service)
    _use_review_service(client, review_service)
    _auth_as(client, teacher, Role.teacher)
    body = client.get("/api/teacher/review", params={"sort": "confidence"}).json()
    assert _l5_ids(body) == [str(ids["2"]), str(ids["1"]), str(ids["3"])]


def test_l5_cursor_walks_a_sorted_queue_without_gaps_or_repeats(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], class_service: ClassService, review_service: ReviewService
) -> None:
    teacher, ids = _l5_three(pg_sessionmaker, class_service)
    _use_review_service(client, review_service)
    _auth_as(client, teacher, Role.teacher)
    seen: list[str] = []
    cursor: str | None = None
    for _ in range(5):
        params: dict[str, str | int] = {"sort": "lost", "limit": 1}
        if cursor:
            params["cursor"] = cursor
        body = client.get("/api/teacher/review", params=params).json()
        assert body["total"] == 3
        seen += _l5_ids(body)
        cursor = body["nextCursor"]
        if cursor is None:
            break
    assert seen == [str(ids["1"]), str(ids["3"]), str(ids["2"])]


def test_l5_a_cursor_from_another_sort_is_a_422(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], class_service: ClassService, review_service: ReviewService
) -> None:
    teacher, _ = _l5_three(pg_sessionmaker, class_service)
    _use_review_service(client, review_service)
    _auth_as(client, teacher, Role.teacher)
    cursor = client.get("/api/teacher/review", params={"sort": "lost", "limit": 1}).json()["nextCursor"]
    assert cursor is not None
    resp = client.get("/api/teacher/review", params={"sort": "confidence", "limit": 1, "cursor": cursor})
    assert resp.status_code == 422


def test_l5_unknown_sort_is_a_422(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], class_service: ClassService, review_service: ReviewService
) -> None:
    teacher, _ = _l5_three(pg_sessionmaker, class_service)
    _use_review_service(client, review_service)
    _auth_as(client, teacher, Role.teacher)
    assert client.get("/api/teacher/review", params={"sort": "newest"}).status_code == 422


def test_l5_repeated_reason_and_class_params_are_a_union(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], class_service: ClassService, review_service: ReviewService
) -> None:
    teacher, class_a, _ = _l5_seed(
        pg_sessionmaker, class_service, class_name="10A", questions=[_question("1", awarded=0, maximum=2)]
    )
    _, class_b, _ = _l5_seed(
        pg_sessionmaker,
        class_service,
        teacher=teacher,
        class_name="10B",
        student_name="Omar",
        questions=[
            _question("1", awarded=0, maximum=2, confidence_score=1.0, needs_review=False, plagiarism_flagged=True)
        ],
    )
    _use_review_service(client, review_service)
    _auth_as(client, teacher, Role.teacher)

    both_classes = client.get("/api/teacher/review", params=[("class_id", str(class_a)), ("class_id", str(class_b))]).json()
    assert both_classes["total"] == 2
    one_class = client.get("/api/teacher/review", params={"class_id": str(class_a)}).json()
    assert one_class["total"] == 1

    both_reasons = client.get(
        "/api/teacher/review", params=[("reason", "low_confidence"), ("reason", "plagiarism_flag")]
    ).json()
    assert both_reasons["total"] == 2
    unknown_only = client.get("/api/teacher/review", params={"reason": "not_a_reason"}).json()
    assert unknown_only["total"] == 0


def test_l5_a_malformed_class_id_among_several_is_a_422(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], class_service: ClassService, review_service: ReviewService
) -> None:
    teacher, class_a, _ = _l5_seed(pg_sessionmaker, class_service, questions=[_question("1", awarded=0, maximum=2)])
    _use_review_service(client, review_service)
    _auth_as(client, teacher, Role.teacher)
    resp = client.get("/api/teacher/review", params=[("class_id", str(class_a)), ("class_id", "nope")])
    assert resp.status_code == 422


def test_l5_subject_filter_and_subject_codes_facet(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], class_service: ClassService, review_service: ReviewService
) -> None:
    teacher, _, _ = _l5_seed(
        pg_sessionmaker, class_service, subject_code="0580", questions=[_question("1", awarded=0, maximum=2)]
    )
    _l5_seed(
        pg_sessionmaker,
        class_service,
        teacher=teacher,
        class_name="11C",
        student_name="Youssef",
        subject_code="0625",
        questions=[_question("1", awarded=0, maximum=2)],
    )
    _use_review_service(client, review_service)
    _auth_as(client, teacher, Role.teacher)

    everything = client.get("/api/teacher/review").json()
    assert everything["subjectCodes"] == ["0580", "0625"]
    physics = client.get("/api/teacher/review", params={"subject": "0625"}).json()
    assert physics["total"] == 1
    assert physics["items"][0]["subjectCode"] == "0625"
    # The facet lists what the other filters allow, not just the chosen subject,
    # so a teacher can widen the subject choice without clearing it first.
    assert physics["subjectCodes"] == ["0580", "0625"]


def test_l5_search_matches_name_question_and_paper_code_case_insensitively(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], class_service: ClassService, review_service: ReviewService
) -> None:
    teacher, _, ids = _l5_seed(
        pg_sessionmaker,
        class_service,
        student_name="Layla Hassan",
        questions=[_question("4", awarded=0, maximum=2), _question("7", awarded=0, maximum=2)],
    )
    _use_review_service(client, review_service)
    _auth_as(client, teacher, Role.teacher)

    assert client.get("/api/teacher/review", params={"q": "layla"}).json()["total"] == 2
    assert _l5_ids(client.get("/api/teacher/review", params={"q": "Q7"}).json()) == [str(ids["7"])]
    assert client.get("/api/teacher/review", params={"q": "9999/11"}).json()["total"] == 2
    assert client.get("/api/teacher/review", params={"q": "nobody"}).json()["total"] == 0
    assert client.get("/api/teacher/review", params={"q": "x" * 101}).status_code == 422


def test_l5_has_history_is_false_for_a_new_teacher_and_true_once_anything_was_reviewed(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], class_service: ClassService, review_service: ReviewService
) -> None:
    fresh = _seed_user(pg_sessionmaker, Role.teacher)
    class_service.create_class(fresh, "Empty 9A")
    _use_review_service(client, review_service)
    _auth_as(client, fresh, Role.teacher)
    empty = client.get("/api/teacher/review").json()
    assert empty["total"] == 0
    assert empty["hasHistory"] is False

    teacher, _, ids = _l5_seed(pg_sessionmaker, class_service, questions=[_question("1", awarded=0, maximum=2)])
    _auth_as(client, teacher, Role.teacher)
    assert client.get("/api/teacher/review").json()["hasHistory"] is True
    assert client.post(f"/api/teacher/review/{ids['1']}/resolve", json={}).status_code == 200
    after = client.get("/api/teacher/review").json()
    assert after["total"] == 0
    assert after["hasHistory"] is True


def test_l5_default_sort_and_legacy_cursor_still_work(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], class_service: ClassService, review_service: ReviewService
) -> None:
    teacher, _ = _l5_three(pg_sessionmaker, class_service)
    _use_review_service(client, review_service)
    _auth_as(client, teacher, Role.teacher)
    first = client.get("/api/teacher/review", params={"limit": 1}).json()
    second = client.get("/api/teacher/review", params={"limit": 1, "cursor": first["nextCursor"]}).json()
    assert _l5_ids(first) != _l5_ids(second)
    assert first["total"] == second["total"] == 3
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/python -m pytest tests/test_web_review.py -k "l5_sort or l5_cursor or l5_unknown or l5_repeated or l5_malformed or l5_subject or l5_search or l5_has_history or l5_default" -v`
Expected: FAIL. The sort tests get oldest order, `subjectCodes` and `hasHistory` raise KeyErrors, and `sort=newest` returns 200.

- [ ] **Step 3: Implement the repository**

In `lemely/db/review_repo.py`:

Imports: change `from dataclasses import dataclass` to `from dataclasses import dataclass, field`. Change `from typing import TYPE_CHECKING, get_args` to `from typing import TYPE_CHECKING, Literal, cast, get_args`. Add `from collections.abc import Sequence` under `TYPE_CHECKING`, or at runtime if the module already uses it at runtime.

Above `ReviewQueuePage`:

```python
ReviewSort = Literal["oldest", "lost", "confidence"]
#: Every sort the queue accepts; the route validates against the Literal.
REVIEW_SORTS: tuple[ReviewSort, ...] = ("oldest", "lost", "confidence")
#: One shape for every sort, so one keyset cursor compares across pages:
#: ``(missing-value flag, value, created_at, item_id)``. A row with no value for
#: the chosen sort (no marks, no confidence) sorts after every row that has one.
SortKey = tuple[int, float, datetime, uuid.UUID]


def review_sort_key(row: ReviewQueueRow, sort: ReviewSort) -> SortKey:
    """The total order ``list_queue`` sorts by and pages over.

    ``lost`` is marks lost (maximum minus Lemely's mark), biggest first;
    ``confidence`` is the confidence score, least sure first; ``oldest`` is
    longest-waiting first. Every key ends in ``(created_at, item_id)``, so ties
    are stable and the oldest-first behaviour is unchanged for ``oldest``.
    """
    if sort == "lost":
        if row.maximum_marks is None or row.ai_awarded_marks is None:
            return (1, 0.0, row.created_at, row.item_id)
        return (0, -float(row.maximum_marks - row.ai_awarded_marks), row.created_at, row.item_id)
    if sort == "confidence":
        if row.confidence_score is None:
            return (1, 0.0, row.created_at, row.item_id)
        return (0, float(row.confidence_score), row.created_at, row.item_id)
    return (0, 0.0, row.created_at, row.item_id)


def _normalise_cursor(cursor: SortKey | tuple[datetime, uuid.UUID]) -> SortKey:
    """Accept the legacy ``(created_at, item_id)`` cursor (oldest sort) as well."""
    if len(cursor) == 2:
        created_at, item_id = cast("tuple[datetime, uuid.UUID]", cursor)
        return (0, 0.0, created_at, item_id)
    return cast("SortKey", cursor)


def _paper_code(row: ReviewQueueRow) -> str | None:
    """CAIE paper code as teachers write it: ``0580/42`` (paper 4, variant 2)."""
    if row.subject_code and row.paper_number is not None:
        variant = "" if row.paper_variant is None else str(row.paper_variant)
        return f"{row.subject_code}/{row.paper_number}{variant}"
    return None


def _search_text(row: ReviewQueueRow) -> str:
    """Everything the queue's search box matches, case-folded."""
    question = row.question_id or ""
    parts = [
        row.student_display_name,
        row.class_name or "",
        row.subject_code or "",
        _paper_code(row) or "",
        question,
        f"q{question}" if question else "",
        row.review_reason or "",
    ]
    return " ".join(parts).casefold()
```

`ReviewQueuePage`: append the fields.

```python
    subject_codes: list[str] = field(default_factory=list)
    """Distinct subject codes among the rows the class/reason/age filters allow,
    before the subject and search filters: what the "Paper" filter can offer."""
    has_history: bool = True
    """False only when the caller has never had a review item at all (any status):
    the client's first-run walkthrough. Computed only for an empty result."""
```

`visible_rosters` (module function) gets a new keyword. Thread it through `_visible_rosters`.

```python
def visible_rosters(
    class_service: ClassService,
    caller_id: uuid.UUID | str,
    caller_role: Role | str,
    *,
    class_id_filter: uuid.UUID | str | None = None,
    class_ids_filter: frozenset[uuid.UUID] | None = None,
) -> tuple[dict[uuid.UUID, tuple[uuid.UUID, str, str]], dict[uuid.UUID, set[uuid.UUID]]]:
    # ...docstring unchanged; add: ``class_ids_filter`` narrows to any of several
    # classes (the queue's multi-class filter); both filters may be given.
    mapping: dict[uuid.UUID, tuple[uuid.UUID, str, str]] = {}
    student_classes: dict[uuid.UUID, set[uuid.UUID]] = {}
    rows = class_service.list_classes(caller_id, caller_role)
    if class_id_filter is not None:
        class_uuid = _as_uuid(class_id_filter)
        rows = [row for row in rows if row.class_id == class_uuid]
    if class_ids_filter is not None:
        rows = [row for row in rows if row.class_id in class_ids_filter]
    for row in rows:
        for entry in class_service.roster(caller_id, caller_role, row.class_id):
            mapping[entry.student_id] = (row.class_id, row.name, entry.display_name)
            student_classes.setdefault(entry.student_id, set()).add(row.class_id)
    return mapping, student_classes
```

```python
    def _visible_rosters(
        self,
        caller_id: uuid.UUID | str,
        caller_role: Role | str,
        *,
        class_id_filter: uuid.UUID | str | None = None,
        class_ids_filter: frozenset[uuid.UUID] | None = None,
    ) -> tuple[dict[uuid.UUID, tuple[uuid.UUID, str, str]], dict[uuid.UUID, set[uuid.UUID]]]:
        # docstring unchanged
        return visible_rosters(
            self._class_service,
            caller_id,
            caller_role,
            class_id_filter=class_id_filter,
            class_ids_filter=class_ids_filter,
        )
```

Replace `list_queue` with the version below. The docstring keeps its existing paragraphs and appends the new ones. The attempt and console query bodies are the current ones; only the parts named here change.

```python
    def list_queue(
        self,
        caller_id: uuid.UUID | str,
        caller_role: Role | str,
        *,
        class_id: uuid.UUID | str | None = None,
        class_ids: Sequence[uuid.UUID | str] | None = None,
        reason: str | None = None,
        reasons: Sequence[str] | None = None,
        subject_codes: Sequence[str] | None = None,
        search: str | None = None,
        min_age_hours: float | None = None,
        sort: ReviewSort = "oldest",
        limit: int | None = None,
        cursor: SortKey | tuple[datetime, uuid.UUID] | None = None,
    ) -> ReviewQueuePage:
        """...existing docstring...

        L5 additions. ``class_ids``/``reasons``/``subject_codes`` are unions
        (any of), combined with the single ``class_id``/``reason`` kept for
        existing callers. An unknown reason among several is ignored; only
        unknown reasons yields no rows. ``search`` is a case-insensitive
        substring over name, class, subject, paper code (``0580/42``), question
        (``4`` or ``Q4``) and the marker's reason text. ``sort`` picks
        :func:`review_sort_key`; ``cursor`` is that key (the legacy
        ``(created_at, item_id)`` pair is accepted for ``oldest``).
        """
        wanted_classes: set[uuid.UUID] = {_as_uuid(c) for c in (class_ids or [])}
        if class_id is not None:
            wanted_classes.add(_as_uuid(class_id))
        class_filter = frozenset(wanted_classes) if wanted_classes else None
        visible, student_classes = self._visible_rosters(
            caller_id, caller_role, class_ids_filter=class_filter
        )
        reason_values = [*(reasons or []), *([reason] if reason is not None else [])]
        reason_enums: list[ReviewReason] = []
        for value in reason_values:
            try:
                reason_enums.append(ReviewReason(value))
            except ValueError:
                continue
        if reason_values and not reason_enums:
            return ReviewQueuePage(rows=[], total=0, has_history=True)
        now = datetime.now(UTC)
        results: list[ReviewQueueRow] = []
        with self._sessionmaker() as session:
            if visible:
                stmt = (
                    select(ReviewQueueItem, Attempt, QuestionResult)
                    .join(Attempt, ReviewQueueItem.attempt_id == Attempt.id)
                    .outerjoin(
                        QuestionResult, ReviewQueueItem.question_result_id == QuestionResult.id
                    )
                    .where(
                        ReviewQueueItem.status == ReviewStatus.open,
                        Attempt.user_id.in_(visible.keys()),
                    )
                    .order_by(ReviewQueueItem.created_at, ReviewQueueItem.id)
                )
                if reason_enums:
                    stmt = stmt.where(ReviewQueueItem.reason.in_(reason_enums))
                # ...the existing R8 loop, unchanged...
            if class_filter is None and _as_role(caller_role) is not Role.platform_admin:
                # ...the existing console query, with
                # `if reason_enums: paper_stmt = paper_stmt.where(ReviewQueueItem.reason.in_(reason_enums))`
                # in place of the single-reason `where`...
        if min_age_hours is not None:
            results = [row for row in results if row.waiting_hours >= min_age_hours]
        facet_codes = sorted({row.subject_code for row in results if row.subject_code})
        if subject_codes:
            wanted_subjects = set(subject_codes)
            results = [row for row in results if row.subject_code in wanted_subjects]
        needle = (search or "").strip().casefold()
        if needle:
            results = [row for row in results if needle in _search_text(row)]
        results.sort(key=lambda row: review_sort_key(row, sort))
        total = len(results)
        page = results
        if cursor is not None:
            boundary = _normalise_cursor(cursor)
            page = [row for row in page if review_sort_key(row, sort) > boundary]
        if limit is not None:
            page = page[: limit + 1]
        has_history = total > 0 or self._any_item_ever(caller_id, caller_role)
        return ReviewQueuePage(
            rows=page, total=total, subject_codes=facet_codes, has_history=has_history
        )

    def _any_item_ever(self, caller_id: uuid.UUID | str, caller_role: Role | str) -> bool:
        """Whether the caller has ever been shown a review item, in any status.

        Ignores every filter: it answers "has this teacher used the queue
        before", which picks the first-run walkthrough over "Nothing to
        review". Same tenancy as :meth:`list_queue`, including no console half
        for ``platform_admin``. Runs only when a listing came back empty.
        """
        visible, _ = self._visible_rosters(caller_id, caller_role)
        with self._sessionmaker() as session:
            if visible:
                hit = session.execute(
                    select(ReviewQueueItem.id)
                    .join(Attempt, ReviewQueueItem.attempt_id == Attempt.id)
                    .where(Attempt.user_id.in_(visible.keys()))
                    .limit(1)
                ).first()
                if hit is not None:
                    return True
            if _as_role(caller_role) is Role.platform_admin:
                return False
            hit = session.execute(
                select(ReviewQueueItem.id)
                .join(TeacherPaper, ReviewQueueItem.teacher_paper_id == TeacherPaper.id)
                .where(teacher_paper_visible(_as_uuid(caller_id), _as_role(caller_role)))
                .limit(1)
            ).first()
            return hit is not None
```

The removed line `results.sort(key=lambda row: (row.created_at, row.item_id))` is now the `review_sort_key` sort. Keep its comment and move it above the new sort. `min_age_hours` now runs before the facet, so the facet respects age.

- [ ] **Step 4: Implement the route and DTO**

`lemely/web/schemas_review.py`, in `ReviewQueueListDTO`. Add `from pydantic import Field` if it isn't imported already.

```python
    subjectCodes: list[str] = Field(default_factory=list)
    """Subject codes the "Paper" filter can offer (see ``ReviewQueuePage.subject_codes``)."""
    hasHistory: bool = True
    """False only for a caller who has never had a review item: first run."""
```

`lemely/web/routers/review.py`. Import `Query` from fastapi, and `REVIEW_SORTS`, `ReviewSort`, `SortKey` and `review_sort_key` from `lemely.db.review_repo`. Replace the cursor helpers:

```python
_CURSOR_SEP = "|"
_CURSOR_V2 = "v2"


def _encode_cursor(row: ReviewQueueRow, sort: ReviewSort) -> str:
    """Opaque keyset cursor for ``row`` under ``sort``.

    ``oldest`` keeps the original urlsafe-base64 ``"<iso created_at>|<uuid>"``
    so a cursor issued before L5 still continues. The other sorts carry the
    full :data:`~lemely.db.review_repo.SortKey` and the sort it belongs to, so a
    cursor can never be replayed under a different order.
    """
    if sort == "oldest":
        raw = f"{row.created_at.isoformat()}{_CURSOR_SEP}{row.item_id}"
    else:
        flag, value, created_at, item_id = review_sort_key(row, sort)
        raw = _CURSOR_SEP.join(
            [_CURSOR_V2, sort, str(flag), repr(value), created_at.isoformat(), str(item_id)]
        )
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str, sort: ReviewSort) -> SortKey:
    """Inverse of :func:`_encode_cursor`; a 422 for anything that does not round-trip
    or that was issued for another sort."""
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        parts = raw.split(_CURSOR_SEP)
        if parts[0] == _CURSOR_V2:
            _, cursor_sort, flag, value, created_at_str, item_id_str = parts
            if cursor_sort != sort:
                raise ValueError("cursor belongs to another sort")
            return (
                int(flag),
                float(value),
                datetime.fromisoformat(created_at_str),
                uuid.UUID(item_id_str),
            )
        if sort != "oldest":
            raise ValueError("cursor belongs to another sort")
        created_at_str, item_id_str = raw.split(_CURSOR_SEP, 1)
        return (0, 0.0, datetime.fromisoformat(created_at_str), uuid.UUID(item_id_str))
    except (ValueError, UnicodeDecodeError, binascii.Error) as exc:
        raise HTTPException(status_code=422, detail="Malformed cursor") from exc
```

Replace `list_review_queue`:

```python
@router.get("", response_model=ReviewQueueListDTO)
def list_review_queue(
    auth: Annotated[AuthContext, Depends(require_role(*_STAFF_ROLES))],
    service: Annotated[ReviewService, Depends(get_review_service)],
    class_id: Annotated[list[str] | None, Query()] = None,
    reason: Annotated[list[str] | None, Query()] = None,
    subject: Annotated[list[str] | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    min_age_hours: float | None = None,
    sort: ReviewSort = "oldest",
    limit: int = 50,
    cursor: str | None = None,
) -> ReviewQueueListDTO:
    """T-07: every open review item across the caller's own students, paginated.

    ...existing paragraphs kept...

    L5: ``class_id``, ``reason`` and ``subject`` may repeat (any of). ``q``
    searches name, class, paper code and question. ``sort`` is ``oldest``
    (default, unchanged), ``lost`` or ``confidence``; an unknown value is a
    422. ``cursor`` is tied to the sort it was issued under. ``subjectCodes``
    feeds the Paper filter; ``hasHistory`` is false only on first run.
    """
    if not 1 <= limit <= 200:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 200")
    parsed_cursor = _decode_cursor(cursor, sort) if cursor is not None else None
    try:
        result = service.list_queue(
            auth.user_id,
            auth.role,
            class_ids=class_id,
            reasons=reason,
            subject_codes=subject,
            search=q,
            min_age_hours=min_age_hours,
            sort=sort,
            limit=limit,
            cursor=parsed_cursor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    has_more = len(result.rows) > limit
    page = result.rows[:limit]
    next_cursor = _encode_cursor(page[-1], sort) if has_more else None
    return ReviewQueueListDTO(
        items=[_row_to_dto(row) for row in page],
        nextCursor=next_cursor,
        total=result.total,
        subjectCodes=result.subject_codes,
        hasHistory=result.has_history,
    )
```

`REVIEW_SORTS` is exported for the frontend contract docstring; FastAPI validates the `Literal`.

- [ ] **Step 5: Run the new and existing tests**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/python -m pytest tests/test_web_review.py tests/test_review_repo.py tests/test_teacher_review_total.py -v`
Expected: PASS. The existing cursor tests in `test_review_repo.py:440-482` pass 2-tuples and must stay green.

- [ ] **Step 6: Commit**

```bash
PYTHONPATH=$PWD pre-commit run --files lemely/db/review_repo.py lemely/web/routers/review.py lemely/web/schemas_review.py tests/test_web_review.py
git commit -S -m "feat(review): sort, multi-filters, search and facets on the review queue" -- lemely/db/review_repo.py lemely/web/routers/review.py lemely/web/schemas_review.py tests/test_web_review.py
```

---

## Task 3: Backend: whole-page image endpoint

**Files:**
- Modify: `lemely/io/scan_render.py` (new `PAGE_OUTLINE_RGB`, `outline_box_png`, `page_pdf_scan`, `page_image_scan`, and `__all__`)
- Modify: `lemely/web/routers/review.py`: extract `_render_item_scan`, keep `get_review_item_crop` on top of it, add `get_review_item_page`
- Test: `tests/test_scan_render.py` (append), `tests/test_web_review.py` (append)

**Interfaces:**
- Consumes: `ReviewService.get_item_crop_source` (unchanged; it is the one ownership check).
- Produces: `GET /api/teacher/review/{item_id}/page` returns `image/png` of the whole page, with the answer region outlined in the error colour and `Cache-Control: private, no-store`. Statuses: 403 out of scope (parity with detail); 404 with `CROP_ABSENT_DETAIL` for every absence; 422 for an unrenderable scan; 503 when no worker is free. Sandbox targets: `lemely.io.scan_render.page_pdf_scan` and `page_image_scan`.

- [ ] **Step 1: Write the failing unit test** (`tests/test_scan_render.py`, append)

```python
def test_outline_box_png_draws_the_outline_around_the_box_and_leaves_the_rest() -> None:
    import io as _io

    from PIL import Image

    from lemely.io.scan_render import PAGE_OUTLINE_RGB, outline_box_png

    blank = Image.new("RGB", (1000, 500), (255, 255, 255))
    buf = _io.BytesIO()
    blank.save(buf, format="PNG")
    # box = [ymin, xmin, ymax, xmax] on a 0-1000 grid -> x 200..400, y 50..150 px
    out = Image.open(_io.BytesIO(outline_box_png(buf.getvalue(), [100, 200, 300, 400]))).convert("RGB")

    assert out.size == (1000, 500)
    stroke = max(3, round(500 / 220))
    pad = stroke * 2
    left_edge = (200 - pad + stroke // 2, 100)
    assert out.getpixel(left_edge) == PAGE_OUTLINE_RGB
    assert out.getpixel((300, 100)) == (255, 255, 255), "the box interior stays untouched"
    assert out.getpixel((800, 400)) == (255, 255, 255), "the page outside stays untouched"
```

- [ ] **Step 2: Write the failing route tests** (`tests/test_web_review.py`, append)

```python
def _outline_pixels(image: Image.Image) -> int:
    from lemely.io.scan_render import PAGE_OUTLINE_RGB

    tr, tg, tb = PAGE_OUTLINE_RGB
    colours = image.getcolors(maxcolors=image.width * image.height) or []
    return sum(
        n for n, (r, g, b) in colours if abs(r - tr) < 12 and abs(g - tg) < 12 and abs(b - tb) < 12
    )


def test_l5_page_route_refuses_a_caller_who_cannot_see_the_student(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
    storage_backend: FakeStorageBackend,
) -> None:
    intruder = _seed_user(pg_sessionmaker, Role.teacher)
    owner, item_id = _seed_boxed_review_item(
        pg_sessionmaker, class_service, storage=storage_backend, scan=_synthetic_scan()
    )
    _use_review_service(client, review_service)
    _use_storage(client, storage_backend)

    _auth_as(client, intruder, Role.teacher)
    detail = client.get(f"/api/teacher/review/{item_id}")
    denied = client.get(f"/api/teacher/review/{item_id}/page")
    assert denied.status_code == detail.status_code
    assert not denied.content.startswith(b"\x89PNG\r\n\x1a\n")

    _auth_as(client, owner, Role.teacher)
    allowed = client.get(f"/api/teacher/review/{item_id}/page")
    assert allowed.status_code == 200
    assert allowed.headers["content-type"] == "image/png"
    assert allowed.headers["cache-control"] == "private, no-store"


def test_l5_page_route_serves_the_whole_page_with_the_answer_outlined(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
    storage_backend: FakeStorageBackend,
) -> None:
    teacher, item_id = _seed_boxed_review_item(
        pg_sessionmaker, class_service, storage=storage_backend, scan=_synthetic_scan()
    )
    _use_review_service(client, review_service)
    _use_storage(client, storage_backend)
    _auth_as(client, teacher, Role.teacher)

    resp = client.get(f"/api/teacher/review/{item_id}/page")
    assert resp.status_code == 200
    got = Image.open(io.BytesIO(resp.content)).convert("RGB")
    page_aspect = _PAGE_WIDTH_PT / _PAGE_HEIGHT_PT
    assert abs(got.width / got.height - page_aspect) < 0.02 * page_aspect, "this is the page, not a crop"
    reddish, bluish, _ = _colour_counts(got)
    assert reddish > 0, "the answer region is on the page"
    assert bluish > 0, "the rest of the page is there too"
    assert _outline_pixels(got) > 200, "the answer is outlined"


def test_l5_page_route_404s_like_the_crop_for_a_boxless_item(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
    storage_backend: FakeStorageBackend,
) -> None:
    teacher, item_id = _seed_boxed_review_item(
        pg_sessionmaker, class_service, storage=storage_backend, scan=_synthetic_scan(), page=None
    )
    _use_review_service(client, review_service)
    _use_storage(client, storage_backend)
    _auth_as(client, teacher, Role.teacher)
    crop = client.get(f"/api/teacher/review/{item_id}/crop")
    page = client.get(f"/api/teacher/review/{item_id}/page")
    assert page.status_code == crop.status_code == 404
    assert page.json() == crop.json()


def test_l5_page_route_404s_when_the_stored_object_has_gone(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
    storage_backend: FakeStorageBackend,
) -> None:
    teacher, item_id = _seed_boxed_review_item(
        pg_sessionmaker,
        class_service,
        storage=storage_backend,
        scan=_synthetic_scan(),
        store_object=False,
    )
    _use_review_service(client, review_service)
    _use_storage(client, storage_backend)
    _auth_as(client, teacher, Role.teacher)
    assert client.get(f"/api/teacher/review/{item_id}/page").status_code == 404


def test_l5_page_route_serves_an_upright_image_scan(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
    storage_backend: FakeStorageBackend,
) -> None:
    scan = _synthetic_image_scan()
    teacher, item_id = _seed_boxed_review_item(
        pg_sessionmaker,
        class_service,
        storage=storage_backend,
        scan=scan,
        page=0,
        content_type="image/png",
    )
    _use_review_service(client, review_service)
    _use_storage(client, storage_backend)
    _auth_as(client, teacher, Role.teacher)

    resp = client.get(f"/api/teacher/review/{item_id}/page")
    assert resp.status_code == 200
    got = Image.open(io.BytesIO(resp.content)).convert("RGB")
    source = Image.open(io.BytesIO(scan))
    assert abs(got.width / got.height - source.width / source.height) < 0.02
    assert _outline_pixels(got) > 100
```

- [ ] **Step 3: Run them to verify they fail**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/python -m pytest tests/test_scan_render.py -k outline tests/test_web_review.py -k l5_page -v`
Expected: FAIL. You get an ImportError for `outline_box_png`, and 404/405 from the missing route.

- [ ] **Step 4: Implement the renderer** (`lemely/io/scan_render.py`, after `crop_image_scan`)

```python
#: The answer's outline on a whole-page render: ``--md-error`` (oklch 0.53 0.20 25)
#: in sRGB, so the page view uses the same red the review queue uses for "look here".
PAGE_OUTLINE_RGB = (192, 38, 45)


def outline_box_png(png: bytes, box: list[int]) -> bytes:
    """Draw ``box`` (normalised 0-1000, ``[ymin, xmin, ymax, xmax]``) onto ``png``.

    Run only on this module's own whole-page output (already bounded by
    :data:`MAX_CROP_PX`), inside the same sandbox call that rendered it. The box
    is padded by two strokes so the outline never covers the student's ink.
    """
    from PIL import Image, ImageDraw

    with Image.open(io.BytesIO(png)) as opened:
        image = opened.convert("RGB")
    width, height = image.size
    ymin, xmin, ymax, xmax = box
    stroke = max(3, round(min(width, height) / 220))
    pad = stroke * 2
    rect = (
        max(0, round(xmin / 1000 * width) - pad),
        max(0, round(ymin / 1000 * height) - pad),
        min(width - 1, round(xmax / 1000 * width) + pad),
        min(height - 1, round(ymax / 1000 * height) + pad),
    )
    ImageDraw.Draw(image).rounded_rectangle(
        rect, radius=stroke * 3, outline=PAGE_OUTLINE_RGB, width=stroke
    )
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def page_pdf_scan(data: bytes, page: int, box: list[int]) -> bytes:
    """The whole of page ``page`` of a PDF scan, with ``box`` outlined.

    Rendered through :func:`crop_pdf_scan` with :data:`WHOLE_REGION`, so the same
    page checks, content check and pixel ceiling apply as for the crop.
    """
    return outline_box_png(crop_pdf_scan(data, page, list(WHOLE_REGION)), list(box))


def page_image_scan(data: bytes, box: list[int], *, page: int = 0) -> bytes:
    """The whole upright image scan, with ``box`` outlined (see :func:`crop_image_scan`)."""
    return outline_box_png(crop_image_scan(data, list(WHOLE_REGION), page=page), list(box))
```

Add `"PAGE_OUTLINE_RGB"`, `"outline_box_png"`, `"page_image_scan"` and `"page_pdf_scan"` to `__all__`.

- [ ] **Step 5: Implement the route** (`lemely/web/routers/review.py`)

Below `CROP_IMAGE_TARGET` add:
```python
PAGE_PDF_TARGET = "lemely.io.scan_render.page_pdf_scan"
PAGE_IMAGE_TARGET = "lemely.io.scan_render.page_image_scan"
```
Change `_RENDER_REFUSED_EVENTS` to suffixes:
```python
_RENDER_REFUSED_EVENTS = {
    "page_out_of_range": "page_out_of_range",
    "page_too_large": "page_too_large",
}
```
Move the body of `get_review_item_crop`, from `try: object_path, box = service.get_item_crop_source(...)` through the final `return Response(...)`, into:

```python
def _render_item_scan(
    item_id: str,
    auth: AuthContext,
    settings: Settings,
    service: ReviewService,
    storage: StorageBackend,
    *,
    pdf_target: str,
    image_target: str,
    event: str,
) -> Response:
    """Shared body of the crop and page routes: one ownership check, one render path.

    ``event`` prefixes every log line (``review_crop`` / ``review_page``) so the
    crop's existing events keep their exact names. Every docstring paragraph of
    :func:`get_review_item_crop` about authorization, the uniform 404 and
    ``no-store`` applies to both routes.
    """
```
In that body:
- replace each `"review_crop_..."` string literal with `f"{event}_..."`
- replace `CROP_PDF_TARGET`/`CROP_IMAGE_TARGET` with `pdf_target`/`image_target`
- replace `_RENDER_REFUSED_EVENTS.get(exc.reason, "review_crop_render_refused")` with `f"{event}_{_RENDER_REFUSED_EVENTS.get(exc.reason, 'render_refused')}"`

Then:

```python
@router.get(
    "/{item_id}/crop",
    responses={200: {"content": {"image/png": {}}, "description": "The boxed region of the scan"}},
)
def get_review_item_crop(
    item_id: str,
    auth: Annotated[AuthContext, Depends(require_role(*_STAFF_ROLES))],
    settings: Annotated[Settings, Depends(get_settings)],
    service: Annotated[ReviewService, Depends(get_review_service)],
    storage: Annotated[StorageBackend, Depends(get_storage_backend)],
) -> Response:
    """...existing docstring unchanged..."""
    return _render_item_scan(
        item_id, auth, settings, service, storage,
        pdf_target=CROP_PDF_TARGET, image_target=CROP_IMAGE_TARGET, event="review_crop",
    )


@router.get(
    "/{item_id}/page",
    responses={200: {"content": {"image/png": {}}, "description": "The whole page, answer outlined"}},
)
def get_review_item_page(
    item_id: str,
    auth: Annotated[AuthContext, Depends(require_role(*_STAFF_ROLES))],
    settings: Annotated[Settings, Depends(get_settings)],
    service: Annotated[ReviewService, Depends(get_review_service)],
    storage: Annotated[StorageBackend, Depends(get_storage_backend)],
) -> Response:
    """The whole page this answer is on, with its region outlined (L5 "Whole page").

    Same ownership rule, absences, status codes, sandbox and ``no-store`` as
    :func:`get_review_item_crop`: both go through :func:`_render_item_scan` and
    :meth:`ReviewService.get_item_crop_source`. The box is drawn server-side so
    the client still never receives coordinates.
    """
    return _render_item_scan(
        item_id, auth, settings, service, storage,
        pdf_target=PAGE_PDF_TARGET, image_target=PAGE_IMAGE_TARGET, event="review_page",
    )
```

- [ ] **Step 6: Run the new tests and every existing crop test**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/python -m pytest tests/test_scan_render.py tests/test_web_review.py -k "crop or page or outline" -v`
Expected: PASS. In particular the existing log-event assertions (`review_crop_object_missing` and the others) are unchanged.

- [ ] **Step 7: Commit**

```bash
PYTHONPATH=$PWD pre-commit run --files lemely/io/scan_render.py lemely/web/routers/review.py tests/test_scan_render.py tests/test_web_review.py
git commit -S -m "feat(review): whole-page image route with the answer outlined" -- lemely/io/scan_render.py lemely/web/routers/review.py tests/test_scan_render.py tests/test_web_review.py
```

---

## Task 4: Frontend data layer: types, URL codec, hooks, decision API

**Files:**
- Modify: `web/src/lib/teacherTypes.ts` (review block)
- Create: `web/src/lib/reviewQueueQuery.ts`
- Create: `web/src/lib/reviewApi.ts`
- Modify: `web/src/lib/hooks/useTeacherApi.ts` (review block)
- Test: `web/tests/unit/reviewQueueQuery.test.ts`

**Interfaces:**
- Consumes: the wire shapes from Tasks 1–3.
- Produces:
  - `type ReviewSort = "oldest" | "lost" | "confidence"`
  - `interface ReviewQueueFilters { q: string; classIds: string[]; reasons: string[]; subjects: string[]; minAgeHours: number | null; sort: ReviewSort }`
  - `EMPTY_FILTERS`, `DEFAULT_SORT: ReviewSort = "lost"`
  - `filtersFromSearch(sp: URLSearchParams): ReviewQueueFilters`
  - `filtersToSearch(f: ReviewQueueFilters): URLSearchParams`
  - `filtersActive(f): boolean`, `filterKey(f): string`
  - `reviewQueuePath(f, page?: { limit?: number; cursor?: string }): string`
  - `type ReviewDecision`, `postReviewDecision(d, opts?)`
  - `useReviewQueuePage(filters, cursor?)`
  - `useReviewItemImage(itemId, kind: "crop" | "page", enabled): ReviewItemCrop`
  - `useReviewItemCrop` (unchanged signature, now a wrapper)

- [ ] **Step 1: Write the failing test** (`web/tests/unit/reviewQueueQuery.test.ts`)

```ts
import { describe, expect, it } from "vitest"
import {
  DEFAULT_SORT,
  EMPTY_FILTERS,
  filterKey,
  filtersActive,
  filtersFromSearch,
  filtersToSearch,
  reviewQueuePath,
} from "@/lib/reviewQueueQuery"

describe("reviewQueueQuery", () => {
  it("defaults to marks lost with nothing filtered", () => {
    expect(filtersFromSearch(new URLSearchParams())).toEqual(EMPTY_FILTERS)
    expect(EMPTY_FILTERS.sort).toBe(DEFAULT_SORT)
    expect(DEFAULT_SORT).toBe("lost")
  })

  it("reads repeated params, the search, age and sort", () => {
    const sp = new URLSearchParams(
      "q=layla&class_id=a&class_id=b&reason=low_confidence&subject=0580&min_age_hours=24&sort=confidence",
    )
    expect(filtersFromSearch(sp)).toEqual({
      q: "layla",
      classIds: ["a", "b"],
      reasons: ["low_confidence"],
      subjects: ["0580"],
      minAgeHours: 24,
      sort: "confidence",
    })
  })

  it("ignores an unknown sort and a non-numeric age", () => {
    const f = filtersFromSearch(new URLSearchParams("sort=newest&min_age_hours=soon"))
    expect(f.sort).toBe("lost")
    expect(f.minAgeHours).toBeNull()
  })

  it("round-trips and omits defaults", () => {
    const f = { ...EMPTY_FILTERS, classIds: ["a"], q: " x " }
    expect(filtersToSearch(f).toString()).toBe("q=x&class_id=a")
    expect(filtersFromSearch(filtersToSearch(f))).toEqual({ ...f, q: "x" })
    expect(filtersToSearch(EMPTY_FILTERS).toString()).toBe("")
  })

  it("keeps a non-default sort in the URL", () => {
    expect(filtersToSearch({ ...EMPTY_FILTERS, sort: "oldest" }).toString()).toBe("sort=oldest")
  })

  it("knows when filters are active (sort alone is not a filter)", () => {
    expect(filtersActive(EMPTY_FILTERS)).toBe(false)
    expect(filtersActive({ ...EMPTY_FILTERS, sort: "oldest" })).toBe(false)
    expect(filtersActive({ ...EMPTY_FILTERS, q: "a" })).toBe(true)
    expect(filtersActive({ ...EMPTY_FILTERS, minAgeHours: 6 })).toBe(true)
  })

  it("builds the API path with the sort always explicit, plus limit and cursor", () => {
    expect(reviewQueuePath(EMPTY_FILTERS, { limit: 50 })).toBe("/teacher/review?sort=lost&limit=50")
    expect(reviewQueuePath({ ...EMPTY_FILTERS, reasons: ["plagiarism_flag"] }, { limit: 50, cursor: "abc" })).toBe(
      "/teacher/review?reason=plagiarism_flag&sort=lost&limit=50&cursor=abc",
    )
  })

  it("gives order-independent filter keys", () => {
    const a = { ...EMPTY_FILTERS, classIds: ["b", "a"] }
    const b = { ...EMPTY_FILTERS, classIds: ["a", "b"] }
    expect(filterKey(a)).toBe(filterKey(b))
    expect(filterKey(a)).not.toBe(filterKey({ ...b, sort: "oldest" }))
  })
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd web && npx vitest run tests/unit/reviewQueueQuery.test.ts`
Expected: FAIL with "Cannot find module '@/lib/reviewQueueQuery'".

- [ ] **Step 3: Implement**

`web/src/lib/teacherTypes.ts`, review block:
- add `reviewReason: string | null` to `ReviewQueueItem`, after `confidenceScore`. `ReviewItemDetail` extends `ReviewQueueItem` and already declares `reviewReason: string | null`; leave that declaration as it is.
- `ReviewQueueList`: add `subjectCodes: string[]` and `hasHistory: boolean`.
- `ReviewItemPoint`: add `ordinal: number`, `markType: string | null`, `tariff: number`, `groupKey: string | null`, `groupMaxMarks: number | null`.
- `ReviewItemDetail`: add `sourcePage: number | null`.
- add `export type ReviewSort = "oldest" | "lost" | "confidence"`.

`web/src/lib/reviewQueueQuery.ts`:

```ts
import type { ReviewSort } from "@/lib/teacherTypes"

/**
 * The review queue's filters, sort and search, as one value. The URL is the
 * source of truth (K1: filters live in the query string and travel into the
 * answer URL), and the same names are the API's query params, so one codec
 * serves both the address bar and `GET /teacher/review`.
 */
export interface ReviewQueueFilters {
  q: string
  classIds: string[]
  reasons: string[]
  subjects: string[]
  minAgeHours: number | null
  sort: ReviewSort
}

/** The approved mock opens on "Marks lost". The API's own default stays `oldest`. */
export const DEFAULT_SORT: ReviewSort = "lost"

export const EMPTY_FILTERS: ReviewQueueFilters = {
  q: "",
  classIds: [],
  reasons: [],
  subjects: [],
  minAgeHours: null,
  sort: DEFAULT_SORT,
}

const SORTS: readonly ReviewSort[] = ["oldest", "lost", "confidence"]

export function filtersFromSearch(sp: URLSearchParams): ReviewQueueFilters {
  const sortRaw = sp.get("sort")
  const ageRaw = sp.get("min_age_hours")
  const age = ageRaw !== null && ageRaw.trim() !== "" ? Number(ageRaw) : NaN
  return {
    q: (sp.get("q") ?? "").trim(),
    classIds: sp.getAll("class_id").filter(Boolean),
    reasons: sp.getAll("reason").filter(Boolean),
    subjects: sp.getAll("subject").filter(Boolean),
    minAgeHours: Number.isFinite(age) ? age : null,
    sort: SORTS.includes(sortRaw as ReviewSort) ? (sortRaw as ReviewSort) : DEFAULT_SORT,
  }
}

function appendFilters(sp: URLSearchParams, f: ReviewQueueFilters): void {
  const q = f.q.trim()
  if (q) sp.set("q", q)
  for (const id of f.classIds) sp.append("class_id", id)
  for (const r of f.reasons) sp.append("reason", r)
  for (const s of f.subjects) sp.append("subject", s)
  if (f.minAgeHours !== null) sp.set("min_age_hours", String(f.minAgeHours))
}

/** For the address bar: defaults are left out so a clean queue has a clean URL. */
export function filtersToSearch(f: ReviewQueueFilters): URLSearchParams {
  const sp = new URLSearchParams()
  appendFilters(sp, f)
  if (f.sort !== DEFAULT_SORT) sp.set("sort", f.sort)
  return sp
}

/** Sort is an ordering, not a filter: it never makes "Clear filters" appear. */
export function filtersActive(f: ReviewQueueFilters): boolean {
  return (
    f.q.trim() !== "" ||
    f.classIds.length > 0 ||
    f.reasons.length > 0 ||
    f.subjects.length > 0 ||
    f.minAgeHours !== null
  )
}

export function filterKey(f: ReviewQueueFilters): string {
  const sorted = (xs: string[]) => [...xs].sort().join(",")
  return [f.q.trim(), sorted(f.classIds), sorted(f.reasons), sorted(f.subjects), f.minAgeHours ?? "", f.sort].join("|")
}

/** For the API: the sort is always explicit, because the server defaults to `oldest`. */
export function reviewQueuePath(f: ReviewQueueFilters, page: { limit?: number; cursor?: string } = {}): string {
  const sp = new URLSearchParams()
  appendFilters(sp, f)
  sp.set("sort", f.sort)
  if (page.limit !== undefined) sp.set("limit", String(page.limit))
  if (page.cursor) sp.set("cursor", page.cursor)
  return `/teacher/review?${sp.toString()}`
}
```

`web/src/lib/reviewApi.ts`:

```ts
import { request } from "@/lib/api"
import type { DismissReviewRequest, ResolveReviewRequest, ReviewQueueItem } from "@/lib/teacherTypes"

/**
 * One teacher decision on one review item, held for the undo window before it
 * is sent (`portals/teacher/screens/review/pendingDecisions.ts`). `label` is
 * the toast copy subject ("Q4(b)"); `changed` says the mark moved.
 */
export type ReviewDecision =
  | { kind: "resolve"; itemId: string; label: string; changed: boolean; body: ResolveReviewRequest }
  | { kind: "dismiss"; itemId: string; label: string; body: DismissReviewRequest }

/**
 * POST the decision. `keepalive` is set when the page is being hidden or left
 * (`pagehide`), so a decision still inside its undo window is not lost when
 * the teacher closes the tab. The browser caps keepalive bodies at 64 KB;
 * these are a few hundred bytes.
 */
export function postReviewDecision(d: ReviewDecision, opts: { keepalive?: boolean } = {}): Promise<ReviewQueueItem> {
  const path = d.kind === "dismiss" ? `/teacher/review/${d.itemId}/dismiss` : `/teacher/review/${d.itemId}/resolve`
  return request<ReviewQueueItem>(path, {
    method: "POST",
    body: JSON.stringify(d.body),
    keepalive: opts.keepalive,
  })
}
```

`web/src/lib/hooks/useTeacherApi.ts`, review block. Add imports for `reviewQueuePath`, `filterKey` and `ReviewQueueFilters` from `@/lib/reviewQueueQuery`. Then:

```ts
/**
 * L5: one page of the redesigned queue (`GET /teacher/review` with repeatable
 * `class_id`/`reason`/`subject`, `q`, `sort`, `limit`, `cursor`). The key starts
 * `["teacher", "review", ...]` so every resolve/dismiss/bulk invalidation that
 * already targets `["teacher", "review"]` refreshes it too.
 */
export function useReviewQueuePage(
  filters: ReviewQueueFilters,
  cursor: string | undefined,
): UseQueryResult<ReviewQueueList, Error> {
  return useQuery({
    queryKey: ["teacher", "review", "queue-page", filterKey(filters), cursor ?? null],
    queryFn: () => request<ReviewQueueList>(reviewQueuePath(filters, { limit: 50, cursor })),
    placeholderData: (previous) => previous,
  })
}
```

Generalise the crop hook. Keep `FetchedCrop`, `cropUrlFor` and `ReviewItemCrop` exactly as they are; their unit tests pin them.

```ts
/**
 * The crop's object-URL lifecycle, for either image the review item serves:
 * `crop` (the boxed region) or `page` (the whole page with the region
 * outlined, L5). Same rules as before: fetched only when `enabled`, tagged
 * with the item id it belongs to (`cropUrlFor`), any failure is absence, and
 * a decode error drops the URL.
 */
export function useReviewItemImage(
  itemId: string | undefined,
  kind: "crop" | "page",
  enabled: boolean,
): ReviewItemCrop {
  const [fetched, setFetched] = useState<FetchedCrop | null>(null)

  useEffect(() => {
    setFetched(null)
    if (!enabled || !itemId) return

    let cancelled = false
    let objectUrl: string | null = null

    fetchBlobUrl(`/teacher/review/${itemId}/${kind}`)
      .then((fetchedUrl) => {
        if (cancelled) {
          URL.revokeObjectURL(fetchedUrl)
          return
        }
        objectUrl = fetchedUrl
        setFetched({ itemId, url: fetchedUrl })
      })
      .catch(() => {
        if (!cancelled) setFetched(null)
      })

    return () => {
      cancelled = true
      if (objectUrl !== null) URL.revokeObjectURL(objectUrl)
    }
  }, [itemId, kind, enabled])

  const onDecodeError = useCallback(() => {
    setFetched((current) => {
      if (current !== null) URL.revokeObjectURL(current.url)
      return null
    })
  }, [])

  return { url: cropUrlFor(itemId, fetched), onDecodeError }
}

export function useReviewItemCrop(itemId: string | undefined, enabled: boolean): ReviewItemCrop {
  return useReviewItemImage(itemId, "crop", enabled)
}
```

The existing long doc comments on `useReviewItemCrop` move onto `useReviewItemImage`.

Also export the resolve-invalidation fan-out so the deferred commit reuses it (B6):

```ts
/** Everything a resolved mark can change (B6). Shared by `useResolveReviewItem`
 * and the review queue's deferred commit. */
export function invalidateAfterResolve(
  queryClient: ReturnType<typeof useQueryClient>,
  row: Pick<ReviewQueueItem, "studentId" | "classId">,
): void {
  queryClient.invalidateQueries({ queryKey: ["teacher", "review"] })
  queryClient.invalidateQueries({ queryKey: ["teacher", "student", row.studentId] })
  queryClient.invalidateQueries({ queryKey: ["teacher", "class", row.classId] })
  queryClient.invalidateQueries({ queryKey: ["teacher", "classes"] })
  queryClient.invalidateQueries({ queryKey: ["teacher", "at-risk"] })
  queryClient.invalidateQueries({ queryKey: ["teacher", "overview"] })
}
```

Then make `useResolveReviewItem`'s `onSuccess` call `invalidateAfterResolve(queryClient, row)`.

- [ ] **Step 4: Run the tests and the typecheck**

Run: `cd web && npx vitest run tests/unit/reviewQueueQuery.test.ts tests/unit/reviewItemMarkerVerdicts.test.ts tests/unit/reviewBadge.test.ts && npx tsc -b --noEmit`
Expected: PASS. `reviewItemMarkerVerdicts.test.ts` still finds `cropUrlFor`.

- [ ] **Step 5: Commit**

```bash
cd web && npx oxlint src/lib/reviewQueueQuery.ts src/lib/reviewApi.ts src/lib/hooks/useTeacherApi.ts && cd ..
PYTHONPATH=$PWD pre-commit run --files web/src/lib/teacherTypes.ts web/src/lib/reviewQueueQuery.ts web/src/lib/reviewApi.ts web/src/lib/hooks/useTeacherApi.ts web/tests/unit/reviewQueueQuery.test.ts
git commit -S -m "feat(web): review queue filters codec, page hook and decision API" -- web/src/lib/teacherTypes.ts web/src/lib/reviewQueueQuery.ts web/src/lib/reviewApi.ts web/src/lib/hooks/useTeacherApi.ts web/tests/unit/reviewQueueQuery.test.ts
```

---

## Task 5: Labels move and the queue view model

**Files:**
- Create: `web/src/portals/teacher/screens/review/reviewLabels.ts`. Move these from `Review.tsx` verbatim, doc comments included: `REASON_LABEL`, `reasonLabel`, `isIntegrityReason` (with `INTEGRITY_REASONS`), `isConsolePaperItem`, `paperIdentityLabel`, `confidenceTone`, `mergeReviewPages`, `REASON_FILTER_OPTIONS`, `AGE_FILTER_OPTIONS`, `SKIP_REASON_LABEL`. Export all of them.
- Modify: `web/src/portals/teacher/screens/Review.tsx` and `ReviewItem.tsx`. Delete the moved definitions and import them from `./review/reviewLabels`. Review.tsx re-exports nothing; it is deleted in Task 13.
- Modify the unit-test imports to `@/portals/teacher/screens/review/reviewLabels`: `web/tests/unit/confidenceTone.test.ts`, `reviewReasonLabels.test.ts`, `reviewAdvisoryCopy.test.ts`, `reviewPaging.test.ts`, `selfReviewTeacherWiring.test.ts`. In the last file, change its `readSource("src/portals/teacher/screens/Review.tsx")` (the REASON_FILTER_OPTIONS test) to `readSource("src/portals/teacher/screens/review/reviewLabels.ts")`.
- Create: `web/src/portals/teacher/screens/review/reviewQueueModel.ts`
- Test: `web/tests/unit/reviewQueueModel.test.ts`

**Interfaces:**
- Consumes: `ReviewQueueItem`, `ReviewQueueFilters`, `BinnyMood` (F1).
- Produces (all named exports of `reviewQueueModel.ts`):
  - `CLEAR_CONFIDENCE`, `ringTone`, `ringValue`, `ringText`, `ringLabel`
  - `sessionShort`, `paperCode`, `paperLine`, `questionLabel`, `rowSubtitle`, `plainWhy`, `marksLost`
  - `isClearItem`, `selectable`, `bulkButton`
  - `QueueScreenState`, `queueScreenState`, `binnyFor`
  - `headerTitle`, `progressOf`, `clearedSummary`, `shownLine`
  - `FilterCategory`, `FilterOptions`, `FilterChip`, `filterChips`, `filterCategories`, `filterValues`, `toggleFilter`, `removeFilter`, `clearFilters`
  - `SORT_OPTIONS`, `sortLabel`
  - `nextFocusAfter`, `positionOf`, `SKIP_LINE`

- [ ] **Step 1: Write the failing test** (`web/tests/unit/reviewQueueModel.test.ts`)

```ts
import { describe, expect, it } from "vitest"
import type { ReviewQueueItem } from "@/lib/teacherTypes"
import { EMPTY_FILTERS } from "@/lib/reviewQueueQuery"
import {
  CLEAR_CONFIDENCE,
  SORT_OPTIONS,
  binnyFor,
  bulkButton,
  clearedSummary,
  clearFilters,
  filterCategories,
  filterChips,
  filterValues,
  headerTitle,
  isClearItem,
  marksLost,
  nextFocusAfter,
  paperLine,
  plainWhy,
  positionOf,
  progressOf,
  queueScreenState,
  removeFilter,
  ringLabel,
  ringText,
  ringTone,
  ringValue,
  rowSubtitle,
  selectable,
  sessionShort,
  shownLine,
  sortLabel,
  toggleFilter,
} from "@/portals/teacher/screens/review/reviewQueueModel"

function item(over: Partial<ReviewQueueItem> = {}): ReviewQueueItem {
  return {
    itemId: "i1",
    source: "student_attempt",
    attemptId: "a1",
    paperId: null,
    questionResultId: "qr1",
    studentId: "s1",
    studentDisplayName: "Layla Hassan",
    classId: "c1",
    className: "10B",
    subjectCode: "0580",
    paperNumber: 4,
    paperVariant: 2,
    sessionMonth: "May/June",
    sessionYear: 2025,
    questionId: "4(b)",
    reason: "low_confidence",
    status: "open",
    createdAt: "2026-11-14T10:00:00Z",
    waitingHours: 3,
    aiAwardedMarks: 4,
    maximumMarks: 5,
    confidenceScore: 0.64,
    reviewReason: null,
    ...over,
  }
}

const OPTS = {
  classes: [
    { id: "c1", label: "10B" },
    { id: "c2", label: "11C" },
  ],
  subjects: ["0580", "0625"],
  subjectName: (code: string) => ({ "0580": "Mathematics", "0625": "Physics" })[code] ?? code,
}

describe("ring", () => {
  it("is red under 70%, gold from 70%, neutral without a score", () => {
    expect(CLEAR_CONFIDENCE).toBe(0.7)
    expect(ringTone(0.69)).toBe("warn")
    expect(ringTone(0.7)).toBe("gold")
    expect(ringTone(null)).toBe("neutral")
  })
  it("shows a whole percent, or a dash", () => {
    expect(ringText(0.644)).toBe("64")
    expect(ringText(null)).toBe("–")
    expect(ringValue(null)).toBe(0)
    expect(ringValue(0.64)).toBe(0.64)
    expect(ringLabel(0.64)).toBe("64% sure")
    expect(ringLabel(null)).toBe("No confidence score")
  })
})

describe("row copy", () => {
  it("abbreviates the session and builds the paper code", () => {
    expect(sessionShort("May/June")).toBe("m/j")
    expect(sessionShort("Oct/Nov")).toBe("o/n")
    expect(sessionShort("Feb/Mar")).toBe("f/m")
    expect(sessionShort(null)).toBeNull()
    expect(paperLine(item())).toBe("0580/42 · m/j 2025")
    expect(paperLine(item({ subjectCode: null }))).toBe("Quiz question")
  })
  it("puts class and question under the name, and says Grading console for console rows (K7)", () => {
    expect(rowSubtitle(item())).toBe("10B · Q4(b)")
    expect(rowSubtitle(item({ source: "console_paper", className: null, questionId: "9" }))).toBe("Grading console · Q9")
    expect(rowSubtitle(item({ questionId: null }))).toBe("10B · Question")
  })
  it("turns reasons into one short plain line", () => {
    expect(plainWhy(item({ reason: "plagiarism_flag" }))).toBe("Matches mark-scheme wording")
    expect(plainWhy(item({ reason: "student_evidence_unjudged" }))).toBe("Student challenged a mark")
    expect(plainWhy(item({ reviewReason: "missing answer" }))).toBe("No answer found")
    expect(plainWhy(item({ reviewReason: "invalid MCQ answer" }))).toBe("Unclear choice")
    expect(plainWhy(item({ reviewReason: "mark scheme has no mcq_answer for this question" }))).toBe(
      "Scheme has no answer key",
    )
    expect(plainWhy(item({ reviewReason: "unverified accuracy mark(s): A1" }))).toBe("Final answer not confirmed")
    expect(plainWhy(item({ reviewReason: "extraction confidence 0.41 below review threshold 0.90" }))).toBe(
      "Hard to read",
    )
    expect(plainWhy(item({ reviewReason: "2 mark(s) awarded but point_verdicts is empty" }))).toBe(
      "Marks and points don't match",
    )
    expect(plainWhy(item({ reviewReason: "confidence 0.62 below review threshold 0.90" }))).toBe("Lemely wasn't sure")
    expect(plainWhy(item({ reviewReason: null }))).toBe("Lemely wasn't sure")
  })
  it("computes marks lost", () => {
    expect(marksLost(item())).toBe(1)
    expect(marksLost(item({ aiAwardedMarks: null }))).toBeNull()
  })
})

describe("bulk", () => {
  it("treats only non-integrity answers at 70% or more as clear", () => {
    expect(isClearItem(item({ confidenceScore: 0.72 }))).toBe(true)
    expect(isClearItem(item({ confidenceScore: 0.69 }))).toBe(false)
    expect(isClearItem(item({ confidenceScore: null }))).toBe(false)
    expect(isClearItem(item({ confidenceScore: 0.95, reason: "plagiarism_flag" }))).toBe(false)
  })
  it("never lets an integrity flag be selected (K6)", () => {
    expect(selectable(item())).toBe(true)
    expect(selectable(item({ reason: "plagiarism_flag" }))).toBe(false)
  })
  it("labels the bulk button for both modes", () => {
    expect(bulkButton({ selecting: false, picked: 0, clearCount: 3, pending: false })).toEqual({
      label: "Approve 3 clear",
      disabled: false,
    })
    expect(bulkButton({ selecting: false, picked: 0, clearCount: 0, pending: false })).toEqual({
      label: "No clear answers",
      disabled: true,
    })
    expect(bulkButton({ selecting: true, picked: 0, clearCount: 3, pending: false })).toEqual({
      label: "Pick answers to approve",
      disabled: true,
    })
    expect(bulkButton({ selecting: true, picked: 2, clearCount: 3, pending: false })).toEqual({
      label: "Approve 2 selected",
      disabled: false,
    })
    expect(bulkButton({ selecting: true, picked: 2, clearCount: 3, pending: true })).toEqual({
      label: "Approving…",
      disabled: true,
    })
  })
})

describe("screen state", () => {
  const base = {
    status: "success" as const,
    visibleCount: 3,
    openTotal: 3,
    filtersActive: false,
    hasHistory: true,
    decidedThisSession: 0,
  }
  it("loads, errors, then picks the queue", () => {
    expect(queueScreenState({ ...base, status: "pending" })).toBe("loading")
    expect(queueScreenState({ ...base, status: "error" })).toBe("error")
    expect(queueScreenState(base)).toBe("queue")
  })
  it("shows first run only to a teacher with no history", () => {
    expect(queueScreenState({ ...base, visibleCount: 0, openTotal: 0, hasHistory: false })).toBe("first-run")
    expect(queueScreenState({ ...base, visibleCount: 0, openTotal: 0 })).toBe("nothing-waiting")
  })
  it("celebrates only after decisions made here", () => {
    expect(queueScreenState({ ...base, visibleCount: 0, openTotal: 0, decidedThisSession: 2 })).toBe("cleared")
  })
  it("tells no-match from empty", () => {
    expect(queueScreenState({ ...base, visibleCount: 0, openTotal: 0, filtersActive: true })).toBe("no-match")
  })
  it("calls a single unfiltered answer sparse", () => {
    expect(queueScreenState({ ...base, visibleCount: 1, openTotal: 1 })).toBe("sparse")
    expect(queueScreenState({ ...base, visibleCount: 1, openTotal: 1, filtersActive: true })).toBe("queue")
  })
  it("gives Binny only to calm states", () => {
    expect(binnyFor("first-run")).toEqual({ mood: "open" })
    expect(binnyFor("nothing-waiting")).toEqual({ mood: "happy" })
    expect(binnyFor("cleared")).toEqual({ mood: "happy" })
    for (const s of ["loading", "error", "queue", "sparse", "no-match"] as const) expect(binnyFor(s)).toBeNull()
  })
})

describe("header and summary", () => {
  it("says answers left and done", () => {
    expect(headerTitle(1, 0)).toBe("answer left · 0 done")
    expect(headerTitle(6, 2)).toBe("answers left · 2 done")
    expect(progressOf(6, 2)).toBeCloseTo(0.25)
    expect(progressOf(0, 0)).toBe(0)
  })
  it("summarises the session", () => {
    expect(clearedSummary({ decided: 6, changed: 1, dismissed: 0 })).toBe("6 decided · 1 mark changed · 0 dismissed")
    expect(clearedSummary({ decided: 2, changed: 2, dismissed: 1 })).toBe("2 decided · 2 marks changed · 1 dismissed")
    expect(shownLine(3, 6)).toBe("Showing 3 of 6")
  })
})

describe("filters", () => {
  it("lists the four categories with counts", () => {
    const f = { ...EMPTY_FILTERS, reasons: ["low_confidence"] }
    expect(filterCategories(f)).toEqual([
      { key: "reason", label: "Reason", count: 1 },
      { key: "class", label: "Class", count: 0 },
      { key: "paper", label: "Paper", count: 0 },
      { key: "waiting", label: "Waiting", count: 0 },
    ])
  })
  it("offers only producible reasons (K2), the teacher's classes (K4), queue subjects and ages (K3)", () => {
    expect(filterValues("reason", EMPTY_FILTERS, OPTS).map((v) => v.label)).toEqual([
      "Low confidence",
      "Matches mark-scheme wording",
      "Student challenged a mark",
    ])
    expect(filterValues("class", EMPTY_FILTERS, OPTS).map((v) => v.label)).toEqual(["10B", "11C"])
    expect(filterValues("paper", EMPTY_FILTERS, OPTS).map((v) => v.label)).toEqual(["0580 Mathematics", "0625 Physics"])
    expect(filterValues("waiting", EMPTY_FILTERS, OPTS).map((v) => v.label)).toEqual([
      "6+ hours",
      "24+ hours",
      "3+ days",
      "7+ days",
    ])
  })
  it("toggles multi-value categories and makes waiting single-choice", () => {
    let f = toggleFilter(EMPTY_FILTERS, "class", "c1")
    f = toggleFilter(f, "class", "c2")
    expect(f.classIds).toEqual(["c1", "c2"])
    f = toggleFilter(f, "class", "c1")
    expect(f.classIds).toEqual(["c2"])
    f = toggleFilter(f, "waiting", "24")
    expect(f.minAgeHours).toBe(24)
    f = toggleFilter(f, "waiting", "72")
    expect(f.minAgeHours).toBe(72)
    f = toggleFilter(f, "waiting", "72")
    expect(f.minAgeHours).toBeNull()
  })
  it("builds removable chips and removes them", () => {
    const f = { ...EMPTY_FILTERS, reasons: ["plagiarism_flag"], classIds: ["c2"], subjects: ["0625"], minAgeHours: 6 }
    const chips = filterChips(f, OPTS)
    expect(chips.map((c) => c.label)).toEqual([
      "Reason: Matches mark-scheme wording",
      "Class: 11C",
      "Paper: 0625 Physics",
      "Waiting: 6+ hours",
    ])
    expect(removeFilter(f, "class", "c2").classIds).toEqual([])
    expect(removeFilter(f, "waiting", "6").minAgeHours).toBeNull()
    expect(clearFilters({ ...f, sort: "oldest" })).toEqual({ ...EMPTY_FILTERS, sort: "oldest" })
  })
  it("names the sorts in the mock's order", () => {
    expect(SORT_OPTIONS.map((s) => s.label)).toEqual(["Marks lost", "Confidence", "Oldest"])
    expect(sortLabel("confidence")).toBe("Confidence")
  })
})

describe("focus", () => {
  it("moves to the next row after a decision, else the previous, else nothing", () => {
    expect(nextFocusAfter(["a", "b", "c"], "b")).toBe("c")
    expect(nextFocusAfter(["a", "b", "c"], "c")).toBe("b")
    expect(nextFocusAfter(["a"], "a")).toBeNull()
    expect(nextFocusAfter(["a", "b"], "zz")).toBe("a")
  })
  it("reports a 1-based position", () => {
    expect(positionOf(["a", "b", "c"], "b")).toEqual({ pos: 2, total: 3 })
    expect(positionOf(["a"], "x")).toEqual({ pos: 0, total: 1 })
  })
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd web && npx vitest run tests/unit/reviewQueueModel.test.ts`
Expected: FAIL (module not found).

- [ ] **Step 3: Move the labels.** Create `review/reviewLabels.ts` holding the moved code. Its imports are `confidenceTierFor` and `markerScored` from `@/lib/markingConfidence`, and `ReviewQueueItem` from `@/lib/teacherTypes`. Update `Review.tsx` and `ReviewItem.tsx` to import from it, and update the five unit-test imports listed above.

- [ ] **Step 4: Implement `review/reviewQueueModel.ts`**

```ts
import type { BinnyMood } from "@/components/redesign"
import type { ReviewQueueFilters } from "@/lib/reviewQueueQuery"
import { EMPTY_FILTERS } from "@/lib/reviewQueueQuery"
import type { ReviewQueueItem, ReviewSort } from "@/lib/teacherTypes"
import {
  AGE_FILTER_OPTIONS,
  REASON_FILTER_OPTIONS,
  isConsolePaperItem,
  isIntegrityReason,
  reasonLabel,
} from "./reviewLabels"

/**
 * The review queue's "clear" band, from the approved design (review-r1
 * final2: red ring under 70%, gold from 70%; "Approve clear" takes only
 * these). It is deliberately NOT the backend's single review threshold
 * (0.90, `lib/markingConfidence.ts`): every row here is already below that
 * one. This is the product's second, named band for "unsure, but probably
 * fine", and it is used for exactly two things: the ring colour and the
 * "Approve N clear" set. See the L5 plan, Needs user decision #1.
 */
export const CLEAR_CONFIDENCE = 0.7

export type RingTone = "warn" | "gold" | "neutral"

export function ringTone(score: number | null): RingTone {
  if (score == null) return "neutral"
  return score >= CLEAR_CONFIDENCE ? "gold" : "warn"
}
export function ringValue(score: number | null): number {
  return score == null ? 0 : Math.min(1, Math.max(0, score))
}
export function ringText(score: number | null): string {
  return score == null ? "–" : String(Math.round(score * 100))
}
export function ringLabel(score: number | null): string {
  return score == null ? "No confidence score" : `${Math.round(score * 100)}% sure`
}

const SESSION_SHORT: Record<string, string> = {
  "May/June": "m/j",
  "Oct/Nov": "o/n",
  "Feb/Mar": "f/m",
  Specimen: "specimen",
}
export function sessionShort(month: string | null): string | null {
  if (!month) return null
  return SESSION_SHORT[month] ?? month
}

type PaperBits = Pick<ReviewQueueItem, "subjectCode" | "paperNumber" | "paperVariant" | "sessionMonth" | "sessionYear">

export function paperCode(item: PaperBits): string | null {
  if (!item.subjectCode || item.paperNumber == null) return item.subjectCode ?? null
  return `${item.subjectCode}/${item.paperNumber}${item.paperVariant ?? ""}`
}

/** "0580/42 · m/j 2025": the panel subtitle's paper part (K8: "Quiz question"). */
export function paperLine(item: PaperBits): string {
  if (!item.subjectCode) return "Quiz question"
  const code = paperCode(item) ?? item.subjectCode
  const month = sessionShort(item.sessionMonth)
  return month && item.sessionYear ? `${code} · ${month} ${item.sessionYear}` : code
}

export function questionLabel(item: Pick<ReviewQueueItem, "questionId">): string {
  return item.questionId ? `Q${item.questionId}` : "Question"
}

export function rowSubtitle(item: ReviewQueueItem): string {
  const who = isConsolePaperItem(item) ? "Grading console" : (item.className ?? "")
  return [who, questionLabel(item)].filter(Boolean).join(" · ")
}

/**
 * One short plain line for why an answer is here. The marker's `reviewReason`
 * is technical ("confidence 0.62 below review threshold 0.90"); teachers get
 * words, never the raw string (it stays in the panel's "Lemely's notes").
 */
export function plainWhy(item: Pick<ReviewQueueItem, "reason" | "reviewReason">): string {
  if (item.reason !== "low_confidence") {
    if (item.reason === "manual") return "Flagged by hand"
    if (item.reason === "random_audit") return "Random check"
    return reasonLabel(item.reason)
  }
  const r = (item.reviewReason ?? "").toLowerCase()
  if (r.includes("missing answer")) return "No answer found"
  if (r.includes("invalid mcq")) return "Unclear choice"
  if (r.includes("mcq_answer")) return "Scheme has no answer key"
  if (r.includes("unverified accuracy")) return "Final answer not confirmed"
  if (r.includes("extraction confidence")) return "Hard to read"
  if (r.includes("point_verdicts") || r.includes("mark point id")) return "Marks and points don't match"
  return "Lemely wasn't sure"
}

export function marksLost(item: Pick<ReviewQueueItem, "aiAwardedMarks" | "maximumMarks">): number | null {
  if (item.aiAwardedMarks == null || item.maximumMarks == null) return null
  return item.maximumMarks - item.aiAwardedMarks
}

export function selectable(item: Pick<ReviewQueueItem, "reason">): boolean {
  return !isIntegrityReason(item.reason)
}
export function isClearItem(item: Pick<ReviewQueueItem, "reason" | "confidenceScore">): boolean {
  return selectable(item) && item.confidenceScore != null && item.confidenceScore >= CLEAR_CONFIDENCE
}

export function bulkButton(s: { selecting: boolean; picked: number; clearCount: number; pending: boolean }): {
  label: string
  disabled: boolean
} {
  if (s.pending) return { label: "Approving…", disabled: true }
  if (s.selecting) {
    return s.picked > 0
      ? { label: `Approve ${s.picked} selected`, disabled: false }
      : { label: "Pick answers to approve", disabled: true }
  }
  return s.clearCount > 0
    ? { label: `Approve ${s.clearCount} clear`, disabled: false }
    : { label: "No clear answers", disabled: true }
}

export type QueueScreenState =
  | "loading"
  | "error"
  | "first-run"
  | "nothing-waiting"
  | "cleared"
  | "no-match"
  | "sparse"
  | "queue"

export function queueScreenState(s: {
  status: "pending" | "error" | "success"
  visibleCount: number
  openTotal: number
  filtersActive: boolean
  hasHistory: boolean
  decidedThisSession: number
}): QueueScreenState {
  if (s.status === "pending") return "loading"
  if (s.status === "error") return "error"
  if (s.visibleCount === 0) {
    if (s.filtersActive) return "no-match"
    if (s.decidedThisSession > 0) return "cleared"
    return s.hasHistory ? "nothing-waiting" : "first-run"
  }
  if (s.visibleCount === 1 && s.openTotal === 1 && !s.filtersActive) return "sparse"
  return "queue"
}

/** Teacher Binny: a small head-crop, calm states only, one per screen. */
export function binnyFor(state: QueueScreenState): { mood: BinnyMood } | null {
  if (state === "first-run") return { mood: "open" }
  if (state === "nothing-waiting" || state === "cleared") return { mood: "happy" }
  return null
}

export function headerTitle(left: number, done: number): string {
  return `${left === 1 ? "answer" : "answers"} left · ${done} done`
}
export function progressOf(left: number, done: number): number {
  const all = left + done
  return all === 0 ? 0 : done / all
}

export interface Tally {
  decided: number
  changed: number
  dismissed: number
}
export function clearedSummary(t: Tally): string {
  return `${t.decided} decided · ${t.changed} ${t.changed === 1 ? "mark" : "marks"} changed · ${t.dismissed} dismissed`
}
export function shownLine(shown: number, total: number): string {
  return `Showing ${shown} of ${total}`
}

export type FilterCategory = "reason" | "class" | "paper" | "waiting"
export interface FilterOptions {
  classes: { id: string; label: string }[]
  subjects: string[]
  subjectName: (code: string) => string
}
export interface FilterChip {
  category: FilterCategory
  value: string
  label: string
}
const CATEGORY_LABEL: Record<FilterCategory, string> = {
  reason: "Reason",
  class: "Class",
  paper: "Paper",
  waiting: "Waiting",
}
const REASONS = REASON_FILTER_OPTIONS.filter((o) => o.value !== "")
const AGES = AGE_FILTER_OPTIONS.filter((o) => o.value !== "")

function valuesOf(f: ReviewQueueFilters, c: FilterCategory): string[] {
  if (c === "reason") return f.reasons
  if (c === "class") return f.classIds
  if (c === "paper") return f.subjects
  return f.minAgeHours === null ? [] : [String(f.minAgeHours)]
}

function labelOf(c: FilterCategory, v: string, o: FilterOptions): string {
  if (c === "reason") return REASONS.find((r) => r.value === v)?.label ?? reasonLabel(v)
  if (c === "class") return o.classes.find((k) => k.id === v)?.label ?? "Class"
  if (c === "paper") {
    const name = o.subjectName(v)
    return name && name !== v ? `${v} ${name}` : v
  }
  return AGES.find((a) => a.value === v)?.label ?? `${v}+ hours`
}

export function filterCategories(f: ReviewQueueFilters): { key: FilterCategory; label: string; count: number }[] {
  return (Object.keys(CATEGORY_LABEL) as FilterCategory[]).map((key) => ({
    key,
    label: CATEGORY_LABEL[key],
    count: valuesOf(f, key).length,
  }))
}

export function filterValues(
  c: FilterCategory,
  f: ReviewQueueFilters,
  o: FilterOptions,
): { value: string; label: string; checked: boolean }[] {
  const chosen = new Set(valuesOf(f, c))
  const values =
    c === "reason"
      ? REASONS.map((r) => r.value)
      : c === "class"
        ? o.classes.map((k) => k.id)
        : c === "paper"
          ? o.subjects
          : AGES.map((a) => a.value)
  return values.map((value) => ({ value, label: labelOf(c, value, o), checked: chosen.has(value) }))
}

function toggled(xs: string[], v: string): string[] {
  return xs.includes(v) ? xs.filter((x) => x !== v) : [...xs, v]
}

export function toggleFilter(f: ReviewQueueFilters, c: FilterCategory, v: string): ReviewQueueFilters {
  if (c === "reason") return { ...f, reasons: toggled(f.reasons, v) }
  if (c === "class") return { ...f, classIds: toggled(f.classIds, v) }
  if (c === "paper") return { ...f, subjects: toggled(f.subjects, v) }
  const hours = Number(v)
  return { ...f, minAgeHours: f.minAgeHours === hours ? null : hours }
}

export function removeFilter(f: ReviewQueueFilters, c: FilterCategory, v: string): ReviewQueueFilters {
  if (c === "waiting") return { ...f, minAgeHours: null }
  return valuesOf(f, c).includes(v) ? toggleFilter(f, c, v) : f
}

/** Clears every filter and the search; keeps the teacher's chosen sort. */
export function clearFilters(f: ReviewQueueFilters): ReviewQueueFilters {
  return { ...EMPTY_FILTERS, sort: f.sort }
}

export function filterChips(f: ReviewQueueFilters, o: FilterOptions): FilterChip[] {
  const chips: FilterChip[] = []
  for (const c of ["reason", "class", "paper", "waiting"] as const) {
    for (const v of valuesOf(f, c)) chips.push({ category: c, value: v, label: `${CATEGORY_LABEL[c]}: ${labelOf(c, v, o)}` })
  }
  return chips
}

export const SORT_OPTIONS: { value: ReviewSort; label: string }[] = [
  { value: "lost", label: "Marks lost" },
  { value: "confidence", label: "Confidence" },
  { value: "oldest", label: "Oldest" },
]
export function sortLabel(s: ReviewSort): string {
  return SORT_OPTIONS.find((o) => o.value === s)?.label ?? "Marks lost"
}

export function nextFocusAfter(ids: string[], decidedId: string): string | null {
  const at = ids.indexOf(decidedId)
  if (at === -1) return ids[0] ?? null
  return ids[at + 1] ?? ids[at - 1] ?? null
}
export function positionOf(ids: string[], id: string | null): { pos: number; total: number } {
  return { pos: id ? ids.indexOf(id) + 1 : 0, total: ids.length }
}

/** K10: the skip reasons, worded for a teacher. */
export const SKIP_LINE: Record<string, string> = {
  not_found: "no longer exists",
  forbidden: "outside your classes",
  already_closed: "already decided",
}
```

- [ ] **Step 5: Run the tests and the typecheck**

Run: `cd web && npx vitest run tests/unit/reviewQueueModel.test.ts tests/unit/confidenceTone.test.ts tests/unit/reviewReasonLabels.test.ts tests/unit/reviewAdvisoryCopy.test.ts tests/unit/reviewPaging.test.ts tests/unit/selfReviewTeacherWiring.test.ts && npx tsc -b --noEmit`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git commit -S -m "feat(web): review queue view model and shared review labels" -- web/src/portals/teacher/screens/review/reviewLabels.ts web/src/portals/teacher/screens/review/reviewQueueModel.ts web/src/portals/teacher/screens/Review.tsx web/src/portals/teacher/screens/ReviewItem.tsx web/tests/unit/reviewQueueModel.test.ts web/tests/unit/confidenceTone.test.ts web/tests/unit/reviewReasonLabels.test.ts web/tests/unit/reviewAdvisoryCopy.test.ts web/tests/unit/reviewPaging.test.ts web/tests/unit/selfReviewTeacherWiring.test.ts
```
(Run `pre-commit run --files` on those paths first.)

---

## Task 6: Mark model (tick-per-point stepper with either/or and pool limits)

**Files:**
- Create: `web/src/portals/teacher/screens/review/markModel.ts`
- Test: `web/tests/unit/reviewMarkModel.test.ts`

**Interfaces:**
- Consumes:
  - `ReviewItemPoint` (Task 4 fields), `ReviewBreakdown`, `ResolveReviewRequest`
  - `groupPoints` and `PointGroup` from `@/lib/selfReview`; `groupPoints` needs `markPointId`, `groupKey`, `groupMaxMarks` and `tariff`
- Produces:
  - `interface MarkPoint { markPointId; code; text; tariff; groupKey; groupMaxMarks; awarded; verdictLabel: string | null; note: string | null; ecf: boolean }`
  - `markPointsFrom(points)`
  - `interface MarkState { ticked: string[]; touched: boolean; raw: number }`
  - `initialMarkState(points, lemely)`, `totalOf(points, state, max, lemely)`, `isBlocked(points, state, id, max)`
  - `toggleTick(points, state, id, max)`, `stepUp(points, state, max)`, `stepDown(points, state)`
  - `canStep(points, state, max, lemely)`, `deltaLine(total, lemely)`, `primaryActionLabel(total, max, lemely)`, `notePlaceholder(changed)`
  - `orBefore(points, index)`, `poolHeader(points, index)`
  - `breakdownOf(points, state)`, `resolveBody(args)`

- [ ] **Step 1: Write the failing test** (`web/tests/unit/reviewMarkModel.test.ts`)

```ts
import { describe, expect, it } from "vitest"
import type { ReviewItemPoint } from "@/lib/teacherTypes"
import {
  breakdownOf,
  canStep,
  deltaLine,
  initialMarkState,
  isBlocked,
  markPointsFrom,
  notePlaceholder,
  orBefore,
  poolHeader,
  primaryActionLabel,
  resolveBody,
  stepDown,
  stepUp,
  toggleTick,
  totalOf,
} from "@/portals/teacher/screens/review/markModel"

function wire(over: Partial<ReviewItemPoint> & { markPointId: string }): ReviewItemPoint {
  return {
    pointText: over.markPointId,
    awarded: false,
    studentSelfmark: null,
    studentEvidence: null,
    evidenceVerdict: null,
    verdict: null,
    evidenceSpan: "",
    ecfApplied: false,
    rationale: null,
    ordinal: 0,
    markType: "M",
    tariff: 1,
    groupKey: null,
    groupMaxMarks: null,
    ...over,
  }
}

// The mock's Q4(b): M1 M1 [A1 OR B1] M1 A1, max 5, Lemely gave 4 (p1 p2 p4 p5).
const Q4 = markPointsFrom([
  wire({ markPointId: "p1", awarded: true, ordinal: 0 }),
  wire({ markPointId: "p2", awarded: true, ordinal: 1 }),
  wire({ markPointId: "p3", markType: "A", groupKey: "alt:2", groupMaxMarks: 1, ordinal: 2 }),
  wire({ markPointId: "p4", markType: "B", groupKey: "alt:2", groupMaxMarks: 1, awarded: true, ordinal: 3 }),
  wire({ markPointId: "p5", awarded: true, ordinal: 4 }),
  wire({ markPointId: "p6", markType: "A", ordinal: 5 }),
])

describe("markPointsFrom", () => {
  it("codes points like the scheme and carries verdict notes", () => {
    const [p] = markPointsFrom([
      wire({ markPointId: "p1", verdict: "unverifiable", evidenceSpan: "a = 5", ecfApplied: true }),
    ])
    expect(p.code).toBe("M1")
    expect(p.verdictLabel).toBe("Couldn't confirm")
    expect(p.note).toBe("“a = 5”")
    expect(p.ecf).toBe(true)
    const [w] = markPointsFrom([wire({ markPointId: "x", verdict: "withheld", rationale: "No unit." })])
    expect(w.verdictLabel).toBe("Judged absent")
    expect(w.note).toBe("No unit.")
    const [n] = markPointsFrom([wire({ markPointId: "p9", markType: null })])
    expect(n.code).toBe("p9")
  })
})

describe("totals", () => {
  it("starts at Lemely's own mark", () => {
    const s = initialMarkState(Q4, 4)
    expect(s.ticked).toEqual(["p1", "p2", "p4", "p5"])
    expect(totalOf(Q4, s, 5, 4)).toBe(4)
  })
  it("recomputes from ticks once touched, and caps either/or groups", () => {
    let s = initialMarkState(Q4, 4)
    s = toggleTick(Q4, s, "p6", 5)
    expect(totalOf(Q4, s, 5, 4)).toBe(5)
  })
  it("blocks the other branch of an either/or", () => {
    const s = initialMarkState(Q4, 4)
    expect(isBlocked(Q4, s, "p3", 5)).toBe(true)
    expect(toggleTick(Q4, s, "p3", 5)).toBe(s)
  })
  it("blocks unticked points once the question maximum is reached", () => {
    let s = initialMarkState(Q4, 4)
    s = toggleTick(Q4, s, "p6", 5)
    s = toggleTick(Q4, s, "p4", 5)
    expect(isBlocked(Q4, s, "p3", 5)).toBe(false)
    s = toggleTick(Q4, s, "p3", 5)
    expect(totalOf(Q4, s, 5, 4)).toBe(5)
  })
  it("caps pools at the group maximum", () => {
    const pool = markPointsFrom([
      wire({ markPointId: "a", groupKey: "pool:1", groupMaxMarks: 2 }),
      wire({ markPointId: "b", groupKey: "pool:1", groupMaxMarks: 2 }),
      wire({ markPointId: "c", groupKey: "pool:1", groupMaxMarks: 2 }),
    ])
    let s = initialMarkState(pool, 0)
    s = toggleTick(pool, s, "a", 3)
    s = toggleTick(pool, s, "b", 3)
    expect(totalOf(pool, s, 3, 0)).toBe(2)
    expect(isBlocked(pool, s, "c", 3)).toBe(true)
    expect(poolHeader(pool, 0)).toBe("Up to 2 marks from these")
    expect(poolHeader(pool, 1)).toBeNull()
  })
})

describe("stepper", () => {
  it("adds the next eligible point and removes the last ticked", () => {
    let s = initialMarkState(Q4, 4)
    s = stepUp(Q4, s, 5)
    expect(s.ticked.at(-1)).toBe("p6")
    expect(totalOf(Q4, s, 5, 4)).toBe(5)
    expect(canStep(Q4, s, 5, 4)).toEqual({ down: true, up: false })
    s = stepDown(Q4, s)
    s = stepDown(Q4, s)
    expect(totalOf(Q4, s, 5, 4)).toBe(3)
  })
  it("steps a raw number when there are no points", () => {
    let s = initialMarkState([], 1)
    expect(totalOf([], s, 3, 1)).toBe(1)
    s = stepUp([], s, 3)
    s = stepUp([], s, 3)
    s = stepUp([], s, 3)
    expect(totalOf([], s, 3, 1)).toBe(3)
    expect(canStep([], s, 3, 1)).toEqual({ down: true, up: false })
    s = stepDown([], stepDown([], stepDown([], stepDown([], s))))
    expect(totalOf([], s, 3, 1)).toBe(0)
    expect(canStep([], s, 3, 1)).toEqual({ down: false, up: true })
  })
})

describe("copy", () => {
  it("states the change against Lemely", () => {
    expect(deltaLine(4, 4)).toBe("as marked by Lemely")
    expect(deltaLine(5, 4)).toBe("+1 from Lemely")
    expect(deltaLine(2, 4)).toBe("−2 from Lemely")
    expect(primaryActionLabel(4, 5, 4)).toBe("Accept 4/5")
    expect(primaryActionLabel(3, 5, 4)).toBe("Save 3/5")
    expect(notePlaceholder(false)).toBe("Note for your records (optional)")
    expect(notePlaceholder(true)).toBe("Note to student (optional)")
  })
  it("draws OR between members of an either/or", () => {
    expect(orBefore(Q4, 3)).toBe(true)
    expect(orBefore(Q4, 2)).toBe(false)
    expect(orBefore(Q4, 4)).toBe(false)
  })
})

describe("resolve body", () => {
  it("accepts as-is with an internal note when unchanged", () => {
    const s = initialMarkState(Q4, 4)
    expect(resolveBody({ points: Q4, state: s, max: 5, lemely: 4, note: " ok ", canAdjust: true })).toEqual({ note: "ok" })
  })
  it("overrides with a tick-derived breakdown and a student note when changed", () => {
    const s = stepDown(Q4, initialMarkState(Q4, 4))
    expect(resolveBody({ points: Q4, state: s, max: 5, lemely: 4, note: "", canAdjust: true })).toEqual({
      overrideMarks: 3,
      breakdown: { methodMarks: 2, accuracyMarks: 0, otherMarks: 1, notes: null },
    })
    expect(breakdownOf(Q4, s)).toEqual({ methodMarks: 2, accuracyMarks: 0, otherMarks: 1, notes: null })
  })
  it("never overrides when the item cannot be adjusted (I16)", () => {
    const s = stepDown(Q4, initialMarkState(Q4, 4))
    expect(resolveBody({ points: Q4, state: s, max: 5, lemely: 4, note: "", canAdjust: false })).toEqual({})
  })
  it("sends no breakdown for a raw-number change", () => {
    const s = stepUp([], initialMarkState([], 1))
    expect(resolveBody({ points: [], state: s, max: 3, lemely: 1, note: "", canAdjust: true })).toEqual({ overrideMarks: 2 })
  })
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd web && npx vitest run tests/unit/reviewMarkModel.test.ts`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement `review/markModel.ts`**

```ts
import { groupPoints } from "@/lib/selfReview"
import type { ResolveReviewRequest, ReviewBreakdown, ReviewItemPoint } from "@/lib/teacherTypes"

/** One scheme point as the tick list shows it. `code` is "M1", "A1", "B1"... */
export interface MarkPoint {
  markPointId: string
  code: string
  text: string
  tariff: number
  groupKey: string | null
  groupMaxMarks: number | null
  awarded: boolean
  verdictLabel: string | null
  note: string | null
  ecf: boolean
}

const CODED_TYPES = new Set(["M", "A", "B", "C", "SC"])
const VERDICT_LABEL: Record<string, string> = { withheld: "Judged absent", unverifiable: "Couldn't confirm" }

export function markPointsFrom(points: readonly ReviewItemPoint[]): MarkPoint[] {
  return [...points]
    .sort((a, b) => a.ordinal - b.ordinal)
    .map((p) => ({
      markPointId: p.markPointId,
      code: p.markType && CODED_TYPES.has(p.markType) ? `${p.markType}${p.tariff}` : p.markPointId,
      text: p.pointText,
      tariff: p.tariff,
      groupKey: p.groupKey,
      groupMaxMarks: p.groupMaxMarks,
      awarded: p.awarded,
      verdictLabel: p.verdict ? (VERDICT_LABEL[p.verdict] ?? null) : null,
      note: p.evidenceSpan ? `“${p.evidenceSpan}”` : (p.rationale ?? null),
      ecf: p.ecfApplied,
    }))
}

/** `ticked` keeps tick order (the stepper's − removes the latest). `raw` is the
 * number used when an item has no points (console papers, quizzes). */
export interface MarkState {
  ticked: string[]
  touched: boolean
  raw: number
}

export function initialMarkState(points: readonly MarkPoint[], lemely: number | null): MarkState {
  return { ticked: points.filter((p) => p.awarded).map((p) => p.markPointId), touched: false, raw: lemely ?? 0 }
}

function computed(points: readonly MarkPoint[], ticked: readonly string[]): number {
  const on = new Set(ticked)
  return groupPoints(points).reduce((sum, g) => {
    const got = g.points.filter((p) => on.has(p.markPointId)).reduce((s, p) => s + p.tariff, 0)
    return sum + Math.min(g.maxMarks, got)
  }, 0)
}

/**
 * Untouched, the total is Lemely's own mark even when its ticks don't add up
 * to it (that disagreement is often why the answer is here). The first tick
 * or step hands the total to the ticks.
 */
export function totalOf(points: readonly MarkPoint[], s: MarkState, max: number | null, lemely: number | null): number {
  const cap = max ?? Number.POSITIVE_INFINITY
  if (points.length === 0) return Math.min(cap, Math.max(0, s.raw))
  if (!s.touched && lemely != null) return lemely
  return Math.min(cap, computed(points, s.ticked))
}

export function isBlocked(points: readonly MarkPoint[], s: MarkState, id: string, max: number | null): boolean {
  if (s.ticked.includes(id)) return false
  const point = points.find((p) => p.markPointId === id)
  if (!point) return true
  if (point.groupKey) {
    const members = points.filter((p) => p.groupKey === point.groupKey)
    const tickedMembers = members.filter((p) => s.ticked.includes(p.markPointId))
    if (point.groupKey.startsWith("alt:") && tickedMembers.length > 0) return true
    const cap = point.groupMaxMarks ?? point.tariff
    if (tickedMembers.reduce((x, p) => x + p.tariff, 0) >= cap) return true
  }
  return max != null && computed(points, s.ticked) >= max
}

export function toggleTick(points: readonly MarkPoint[], s: MarkState, id: string, max: number | null): MarkState {
  if (s.ticked.includes(id)) return { ...s, touched: true, ticked: s.ticked.filter((x) => x !== id) }
  if (isBlocked(points, s, id, max)) return s
  return { ...s, touched: true, ticked: [...s.ticked, id] }
}

export function stepUp(points: readonly MarkPoint[], s: MarkState, max: number | null): MarkState {
  if (points.length === 0) return { ...s, touched: true, raw: Math.min(max ?? Number.POSITIVE_INFINITY, s.raw + 1) }
  const next = points.find((p) => !isBlocked(points, s, p.markPointId, max) && !s.ticked.includes(p.markPointId))
  return next ? { ...s, touched: true, ticked: [...s.ticked, next.markPointId] } : s
}

export function stepDown(points: readonly MarkPoint[], s: MarkState): MarkState {
  if (points.length === 0) return { ...s, touched: true, raw: Math.max(0, s.raw - 1) }
  if (s.ticked.length === 0) return s
  return { ...s, touched: true, ticked: s.ticked.slice(0, -1) }
}

export function canStep(
  points: readonly MarkPoint[],
  s: MarkState,
  max: number | null,
  lemely: number | null,
): { down: boolean; up: boolean } {
  const total = totalOf(points, s, max, lemely)
  if (points.length === 0) return { down: total > 0, up: max == null || total < max }
  const up = (max == null || total < max) && points.some((p) => !s.ticked.includes(p.markPointId) && !isBlocked(points, s, p.markPointId, max))
  return { down: s.ticked.length > 0, up }
}

export function deltaLine(total: number, lemely: number | null): string {
  if (lemely == null || total === lemely) return "as marked by Lemely"
  const d = total - lemely
  return `${d > 0 ? "+" : "−"}${Math.abs(d)} from Lemely`
}

export function primaryActionLabel(total: number, max: number | null, lemely: number | null): string {
  const verb = lemely == null || total === lemely ? "Accept" : "Save"
  return `${verb} ${total}/${max ?? "–"}`
}

/** I14/I15: on accept-as-is the note is stored internally, never shown to the student. */
export function notePlaceholder(changed: boolean): string {
  return changed ? "Note to student (optional)" : "Note for your records (optional)"
}

export function orBefore(points: readonly MarkPoint[], index: number): boolean {
  const here = points[index]
  const prev = points[index - 1]
  return !!here?.groupKey && here.groupKey.startsWith("alt:") && prev?.groupKey === here.groupKey
}

export function poolHeader(points: readonly MarkPoint[], index: number): string | null {
  const here = points[index]
  if (!here?.groupKey || !here.groupKey.startsWith("pool:")) return null
  if (points[index - 1]?.groupKey === here.groupKey) return null
  const cap = here.groupMaxMarks ?? here.tariff
  return `Up to ${cap} ${cap === 1 ? "mark" : "marks"} from these`
}

/** The method/accuracy/other split the old adjust form asked for, read off the ticks. */
export function breakdownOf(points: readonly MarkPoint[], s: MarkState): ReviewBreakdown | undefined {
  if (points.length === 0) return undefined
  const on = points.filter((p) => s.ticked.includes(p.markPointId))
  const sum = (pred: (p: MarkPoint) => boolean) => on.filter(pred).reduce((x, p) => x + p.tariff, 0)
  const type = (p: MarkPoint) => p.code.replace(/\d+$/, "")
  return {
    methodMarks: sum((p) => type(p) === "M" || type(p) === "C"),
    accuracyMarks: sum((p) => type(p) === "A"),
    otherMarks: sum((p) => !["M", "C", "A"].includes(type(p))),
    notes: null,
  }
}

export function resolveBody(a: {
  points: readonly MarkPoint[]
  state: MarkState
  max: number | null
  lemely: number | null
  note: string
  canAdjust: boolean
}): ResolveReviewRequest {
  const note = a.note.trim() || undefined
  const total = totalOf(a.points, a.state, a.max, a.lemely)
  const body: ResolveReviewRequest = {}
  if (a.canAdjust && a.lemely != null && total !== a.lemely) {
    body.overrideMarks = total
    const breakdown = breakdownOf(a.points, a.state)
    if (breakdown) body.breakdown = breakdown
  }
  if (note) body.note = note
  return body
}
```

`ResolveReviewRequest` fields are optional (`overrideMarks?`, `breakdown?`, `note?`). If the type declares them `| null` instead, adjust the test's `toEqual` objects to match. Do not change the type.

- [ ] **Step 4: Run the test**

Run: `cd web && npx vitest run tests/unit/reviewMarkModel.test.ts && npx tsc -b --noEmit`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git commit -S -m "feat(web): tick-per-point mark model with either/or and pool caps" -- web/src/portals/teacher/screens/review/markModel.ts web/tests/unit/reviewMarkModel.test.ts
```

---

## Task 7: Answer view adapter and the pending-decision controller

**Files:**
- Create: `web/src/portals/teacher/screens/review/answerView.ts`
- Create: `web/src/portals/teacher/screens/review/pendingDecisions.ts`
- Create: `web/src/portals/teacher/screens/review/usePendingDecisions.ts`
- Create: `web/src/portals/teacher/screens/review/useAnswerImages.ts`
- Test: `web/tests/unit/reviewAnswerView.test.ts`, `web/tests/unit/reviewPendingDecisions.test.ts`

**Interfaces:**
- Consumes: `ReviewItemDetail`, `markPointsFrom`, `paperLine`, `questionLabel`, `ringLabel`, `isConsolePaperItem`, `isIntegrityReason`, `ReviewDecision`, `postReviewDecision`, `useReviewItemImage`.
- Produces:
  - `interface AnswerView` (below)
  - `answerViewFromReviewItem(d): AnswerView`
  - `decisionsReducer`, `INITIAL_DECISIONS`, `UNDO_WINDOW_MS = 5000`, `BULK_TOAST_MS = 4000`
  - `usePendingDecisions(commit, onCommitted)` returning `{ state, decide, undo, flush, bulkApproved, clearNotice }`
  - `useAnswerImages(itemId, hasScan)` returning `{ crop, page, requestPage }`

- [ ] **Step 1: Write the failing tests**

`web/tests/unit/reviewAnswerView.test.ts`:

```ts
import { describe, expect, it } from "vitest"
import type { ReviewItemDetail } from "@/lib/teacherTypes"
import { answerViewFromReviewItem } from "@/portals/teacher/screens/review/answerView"

function detail(over: Partial<ReviewItemDetail> = {}): ReviewItemDetail {
  return {
    itemId: "i1", source: "student_attempt", attemptId: "a1", paperId: null, questionResultId: "qr1",
    studentId: "s1", studentDisplayName: "Layla Hassan", classId: "c1", className: "10B",
    subjectCode: "0580", paperNumber: 4, paperVariant: 2, sessionMonth: "May/June", sessionYear: 2025,
    questionId: "4(b)", reason: "low_confidence", status: "open", createdAt: "2026-11-14T10:00:00Z",
    waitingHours: 2, aiAwardedMarks: 4, maximumMarks: 5, confidenceScore: 0.64, reviewReason: "confidence 0.64 below review threshold 0.90",
    studentAnswer: "x = 3y + 2", expectedAnswer: "y = 1/3 or -5/3", topic: "Quadratics", matchedPointIds: ["p1"],
    feedback: "Sign slip in the constant.", markerSource: "ai", isOverridden: false, teacherAwardedMarks: null,
    teacherNote: null, teacherBreakdown: null, overriddenBy: null, overriddenAt: null, resolutionNote: null,
    resolvedBy: null, resolvedAt: null, points: [], hasSourceBox: true, sourcePage: 6,
    ...over,
  } as ReviewItemDetail
}

describe("answerViewFromReviewItem", () => {
  it("builds the header, page label and scheme wording", () => {
    const v = answerViewFromReviewItem(detail())
    expect(v.title).toBe("Layla Hassan · Q4(b)")
    expect(v.subtitle).toBe("10B · 0580/42 · m/j 2025 · 64% sure")
    expect(v.pageLabel).toBe("Page 6 · 0580/42")
    expect(v.studentHref).toBe("/teacher/students/s1")
    expect(v.scheme).toEqual({ expected: "y = 1/3 or -5/3", topic: "Quadratics" })
    expect(v.notes).toEqual({ reason: "confidence 0.64 below review threshold 0.90", feedback: "Sign slip in the constant." })
    expect(v.canAdjust).toBe(true)
    expect(v.cannotAdjustReason).toBeNull()
  })
  it("treats console papers honestly (K7, I16)", () => {
    const v = answerViewFromReviewItem(detail({ source: "console_paper", studentId: null, className: null, questionResultId: null, hasSourceBox: false, sourcePage: null }))
    expect(v.studentHref).toBeNull()
    expect(v.subtitle.startsWith("Grading console · ")).toBe(true)
    expect(v.hasScan).toBe(false)
    expect(v.pageLabel).toBeNull()
    expect(v.canAdjust).toBe(false)
    expect(v.cannotAdjustReason).toBe(
      "Papers marked in the grading console store no per-question result to record a new mark on. Accept as-is, or re-run the paper from the console.",
    )
  })
  it("lists only self-marked points as Student said lines (I12)", () => {
    const v = answerViewFromReviewItem(
      detail({
        points: [
          { markPointId: "p1", pointText: "Expands", awarded: true, studentSelfmark: null, studentEvidence: null, evidenceVerdict: null, verdict: null, evidenceSpan: "", ecfApplied: false, rationale: null, ordinal: 0, markType: "M", tariff: 1, groupKey: null, groupMaxMarks: null },
          { markPointId: "p2", pointText: "Constant", awarded: false, studentSelfmark: true, studentEvidence: "I wrote -4.", evidenceVerdict: null, verdict: null, evidenceSpan: "", ecfApplied: false, rationale: null, ordinal: 1, markType: "A", tariff: 1, groupKey: null, groupMaxMarks: null },
        ],
      }),
    )
    expect(v.selfReview).toEqual([{ code: "A1", claim: "Claims earned", evidence: "I wrote -4.", judge: "Not yet judged" }])
  })
  it("carries the read-only record for a closed item (I18, I19)", () => {
    const v = answerViewFromReviewItem(detail({ status: "resolved", isOverridden: true, teacherAwardedMarks: 3, teacherNote: "Unit missing", overriddenAt: "2026-11-14T11:00:00Z", resolutionNote: "checked" }))
    expect(v.status).toBe("resolved")
    expect(v.correction).toEqual({ marks: 3, note: "Unit missing", at: "2026-11-14T11:00:00Z" })
    expect(v.resolutionNote).toBe("checked")
  })
  it("flags integrity items", () => {
    expect(answerViewFromReviewItem(detail({ reason: "plagiarism_flag", confidenceScore: null })).integrity).toBe(true)
  })
})
```

`web/tests/unit/reviewPendingDecisions.test.ts`:

```ts
import { describe, expect, it } from "vitest"
import type { ReviewDecision } from "@/lib/reviewApi"
import { INITIAL_DECISIONS, decisionsReducer } from "@/portals/teacher/screens/review/pendingDecisions"

const accept: ReviewDecision = { kind: "resolve", itemId: "a", label: "Q4(b)", changed: false, body: {} }
const change: ReviewDecision = { kind: "resolve", itemId: "b", label: "Q8", changed: true, body: { overrideMarks: 3 } }
const dismiss: ReviewDecision = { kind: "dismiss", itemId: "c", label: "Q9", body: {} }

describe("decisionsReducer", () => {
  it("hides the row, counts it and makes it undoable", () => {
    const s = decisionsReducer(INITIAL_DECISIONS, { type: "decide", decision: change })
    expect(s.hidden).toEqual(["b"])
    expect(s.undoable).toBe(change)
    expect(s.tally).toEqual({ decided: 1, changed: 1, dismissed: 0 })
    expect(s.notice).toEqual({ kind: "decided", text: "Q8 saved at 3.", undo: true })
  })
  it("undo restores the row and the tally", () => {
    let s = decisionsReducer(INITIAL_DECISIONS, { type: "decide", decision: dismiss })
    expect(s.notice?.text).toBe("Q9 dismissed.")
    s = decisionsReducer(s, { type: "undo" })
    expect(s.hidden).toEqual([])
    expect(s.undoable).toBeNull()
    expect(s.tally).toEqual({ decided: 0, changed: 0, dismissed: 0 })
    expect(s.notice).toBeNull()
  })
  it("starting the commit ends the undo window", () => {
    let s = decisionsReducer(INITIAL_DECISIONS, { type: "decide", decision: accept })
    expect(s.notice?.text).toBe("Q4(b) accepted.")
    s = decisionsReducer(s, { type: "commit-start", decision: accept })
    expect(s.undoable).toBeNull()
    expect(s.hidden).toEqual(["a"])
  })
  it("a failed commit brings the row back with an error", () => {
    let s = decisionsReducer(INITIAL_DECISIONS, { type: "decide", decision: change })
    s = decisionsReducer(s, { type: "commit-start", decision: change })
    s = decisionsReducer(s, { type: "commit-failed", decision: change, message: "Offline." })
    expect(s.hidden).toEqual([])
    expect(s.tally.decided).toBe(0)
    expect(s.notice).toEqual({ kind: "error", text: "Couldn't save Q8. Offline.", undo: false })
  })
  it("a conflict keeps the row hidden but uncounted", () => {
    let s = decisionsReducer(INITIAL_DECISIONS, { type: "decide", decision: accept })
    s = decisionsReducer(s, { type: "commit-conflict", decision: accept })
    expect(s.hidden).toEqual(["a"])
    expect(s.tally.decided).toBe(0)
    expect(s.notice).toEqual({ kind: "info", text: "Q4(b) was already decided.", undo: false })
  })
  it("bulk approval hides and counts every approved id, with no undo", () => {
    const s = decisionsReducer(INITIAL_DECISIONS, { type: "bulk-ok", approved: ["x", "y"], skipped: 1 })
    expect(s.hidden).toEqual(["x", "y"])
    expect(s.tally.decided).toBe(2)
    expect(s.notice).toEqual({ kind: "bulk", text: "2 approved · 1 skipped.", undo: false })
  })
})
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd web && npx vitest run tests/unit/reviewAnswerView.test.ts tests/unit/reviewPendingDecisions.test.ts`
Expected: FAIL (modules not found).

- [ ] **Step 3: Implement `answerView.ts`**

```ts
import type { ReviewItemDetail } from "@/lib/teacherTypes"
import { markPointsFrom, type MarkPoint } from "./markModel"
import { isConsolePaperItem, isIntegrityReason } from "./reviewLabels"
import { paperCode, paperLine, questionLabel, ringLabel } from "./reviewQueueModel"

/**
 * Everything the answer panel shows, as plain data. The review queue builds it
 * from `ReviewItemDetail`; L8 builds one from a student's marked question and
 * renders the same `AnswerPanel` read-only (`marking={null}`).
 */
export interface AnswerView {
  key: string
  title: string
  subtitle: string
  studentHref: string | null
  pageLabel: string | null
  hasScan: boolean
  transcription: string | null
  selfReview: { code: string; claim: string; evidence: string | null; judge: string }[]
  scheme: { expected: string | null; topic: string | null }
  notes: { reason: string | null; feedback: string | null }
  points: MarkPoint[]
  matchedPointIds: string[]
  maximumMarks: number | null
  lemelyMarks: number | null
  status: "open" | "resolved" | "dismissed"
  integrity: boolean
  canAdjust: boolean
  cannotAdjustReason: string | null
  correction: { marks: number | null; note: string | null; at: string | null } | null
  resolutionNote: string | null
}

const JUDGE: Record<string, string> = {
  accepted: "Lemely's judge agreed",
  rejected: "Lemely's judge disagreed",
  not_required: "No reason needed",
}

export function answerViewFromReviewItem(d: ReviewItemDetail): AnswerView {
  const console = isConsolePaperItem(d)
  const who = console ? "Grading console" : (d.className ?? "")
  const points = markPointsFrom(d.points)
  const codeOf = new Map(points.map((p) => [p.markPointId, p.code]))
  const canAdjust = d.questionResultId != null
  return {
    key: d.itemId,
    title: `${d.studentDisplayName} · ${questionLabel(d)}`,
    subtitle: [who, paperLine(d), ringLabel(d.confidenceScore)].filter(Boolean).join(" · "),
    studentHref: !console && d.studentId ? `/teacher/students/${d.studentId}` : null,
    pageLabel: d.hasSourceBox && d.sourcePage != null ? `Page ${d.sourcePage} · ${paperCode(d) ?? "scan"}` : null,
    hasScan: d.hasSourceBox,
    transcription: d.studentAnswer,
    selfReview: d.points
      .filter((p) => p.studentSelfmark !== null)
      .map((p) => ({
        code: codeOf.get(p.markPointId) ?? p.markPointId,
        claim: p.studentSelfmark ? "Claims earned" : "Claims not earned",
        evidence: p.studentEvidence,
        judge: p.evidenceVerdict ? (JUDGE[p.evidenceVerdict] ?? p.evidenceVerdict) : "Not yet judged",
      })),
    scheme: { expected: d.expectedAnswer, topic: d.topic },
    notes: { reason: d.reviewReason, feedback: d.feedback },
    points,
    matchedPointIds: d.matchedPointIds,
    maximumMarks: d.maximumMarks,
    lemelyMarks: d.aiAwardedMarks,
    status: d.status === "resolved" || d.status === "dismissed" ? d.status : "open",
    integrity: isIntegrityReason(d.reason),
    canAdjust,
    cannotAdjustReason: canAdjust
      ? null
      : console
        ? "Papers marked in the grading console store no per-question result to record a new mark on. Accept as-is, or re-run the paper from the console."
        : "No mark data on this item to adjust",
    correction: d.isOverridden ? { marks: d.teacherAwardedMarks, note: d.teacherNote, at: d.overriddenAt } : null,
    resolutionNote: d.resolutionNote,
  }
}
```

- [ ] **Step 4: Implement `pendingDecisions.ts`**

```ts
import type { ReviewDecision } from "@/lib/reviewApi"
import type { Tally } from "./reviewQueueModel"

/** The mock's toast lifetimes: 5s for one decision (the undo window), 4s for bulk. */
export const UNDO_WINDOW_MS = 5000
export const BULK_TOAST_MS = 4000

export interface DecisionNotice {
  kind: "decided" | "bulk" | "error" | "info"
  text: string
  undo: boolean
}

export interface DecisionsState {
  /** Rows collapsed in this session: pending, in flight or committed. */
  hidden: string[]
  undoable: ReviewDecision | null
  tally: Tally
  notice: DecisionNotice | null
}

export const INITIAL_DECISIONS: DecisionsState = {
  hidden: [],
  undoable: null,
  tally: { decided: 0, changed: 0, dismissed: 0 },
  notice: null,
}

export type DecisionsAction =
  | { type: "decide"; decision: ReviewDecision }
  | { type: "undo" }
  | { type: "commit-start"; decision: ReviewDecision }
  | { type: "commit-ok"; decision: ReviewDecision }
  | { type: "commit-conflict"; decision: ReviewDecision }
  | { type: "commit-failed"; decision: ReviewDecision; message: string }
  | { type: "bulk-ok"; approved: string[]; skipped: number }
  | { type: "clear-notice" }

function bump(t: Tally, d: ReviewDecision, by: 1 | -1): Tally {
  return {
    decided: t.decided + by,
    changed: t.changed + (d.kind === "resolve" && d.changed ? by : 0),
    dismissed: t.dismissed + (d.kind === "dismiss" ? by : 0),
  }
}

function decidedText(d: ReviewDecision): string {
  if (d.kind === "dismiss") return `${d.label} dismissed.`
  return d.body.overrideMarks != null ? `${d.label} saved at ${d.body.overrideMarks}.` : `${d.label} accepted.`
}

export function decisionsReducer(s: DecisionsState, a: DecisionsAction): DecisionsState {
  switch (a.type) {
    case "decide":
      return {
        ...s,
        hidden: s.hidden.includes(a.decision.itemId) ? s.hidden : [...s.hidden, a.decision.itemId],
        undoable: a.decision,
        tally: bump(s.tally, a.decision, 1),
        notice: { kind: "decided", text: decidedText(a.decision), undo: true },
      }
    case "undo": {
      const d = s.undoable
      if (!d) return s
      return { ...s, hidden: s.hidden.filter((id) => id !== d.itemId), undoable: null, tally: bump(s.tally, d, -1), notice: null }
    }
    case "commit-start":
      return s.undoable?.itemId === a.decision.itemId
        ? { ...s, undoable: null, notice: s.notice ? { ...s.notice, undo: false } : null }
        : s
    case "commit-ok":
      return s
    case "commit-conflict":
      return {
        ...s,
        tally: bump(s.tally, a.decision, -1),
        undoable: s.undoable?.itemId === a.decision.itemId ? null : s.undoable,
        notice: { kind: "info", text: `${a.decision.label} was already decided.`, undo: false },
      }
    case "commit-failed":
      return {
        ...s,
        hidden: s.hidden.filter((id) => id !== a.decision.itemId),
        tally: bump(s.tally, a.decision, -1),
        undoable: s.undoable?.itemId === a.decision.itemId ? null : s.undoable,
        notice: { kind: "error", text: `Couldn't save ${a.decision.label}. ${a.message}`, undo: false },
      }
    case "bulk-ok":
      return {
        ...s,
        hidden: [...s.hidden, ...a.approved.filter((id) => !s.hidden.includes(id))],
        tally: { ...s.tally, decided: s.tally.decided + a.approved.length },
        notice: {
          kind: "bulk",
          text: a.skipped > 0 ? `${a.approved.length} approved · ${a.skipped} skipped.` : `${a.approved.length} approved.`,
          undo: false,
        },
      }
    case "clear-notice":
      return { ...s, notice: null }
  }
}
```

- [ ] **Step 5: Implement `usePendingDecisions.ts`** (no unit test, because hooks need a DOM; Playwright covers it in Task 11)

```ts
import { useCallback, useEffect, useReducer, useRef } from "react"
import { ApiError } from "@/lib/api"
import type { ReviewDecision } from "@/lib/reviewApi"
import { teacherMutationFailureMessage } from "@/lib/teacherOutcome"
import { BULK_TOAST_MS, INITIAL_DECISIONS, UNDO_WINDOW_MS, decisionsReducer } from "./pendingDecisions"

type Commit = (d: ReviewDecision, opts: { keepalive: boolean }) => Promise<unknown>

/**
 * Deferred commit for the queue's collapse-and-undo (approved mock, the review
 * queue's "row collapses with undo"). The backend has no reopen, so a decision
 * waits UNDO_WINDOW_MS before it is sent. Only one decision is undoable at a
 * time: deciding again commits the previous one at once. Leaving the page
 * (`pagehide`) or unmounting flushes with `keepalive`, so nothing is lost.
 * `commit` and `onCommitted` are read through refs, so callers need not memoise them.
 */
export function usePendingDecisions(commit: Commit, onCommitted: (d: ReviewDecision, row: unknown) => void) {
  const [state, dispatch] = useReducer(decisionsReducer, INITIAL_DECISIONS)
  const commitRef = useRef(commit)
  const committedRef = useRef(onCommitted)
  commitRef.current = commit
  committedRef.current = onCommitted
  const pending = useRef<ReviewDecision | null>(null)
  const timer = useRef<number | null>(null)
  const noticeTimer = useRef<number | null>(null)

  const fire = useCallback((d: ReviewDecision, keepalive: boolean) => {
    dispatch({ type: "commit-start", decision: d })
    commitRef
      .current(d, { keepalive })
      .then((row) => {
        dispatch({ type: "commit-ok", decision: d })
        committedRef.current(d, row)
      })
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.status === 409) dispatch({ type: "commit-conflict", decision: d })
        else dispatch({ type: "commit-failed", decision: d, message: teacherMutationFailureMessage(err) })
      })
  }, [])

  const flush = useCallback(
    (keepalive = false) => {
      if (timer.current !== null) window.clearTimeout(timer.current)
      timer.current = null
      const d = pending.current
      pending.current = null
      if (d) fire(d, keepalive)
    },
    [fire],
  )

  const hideNoticeAfter = useCallback((ms: number) => {
    if (noticeTimer.current !== null) window.clearTimeout(noticeTimer.current)
    noticeTimer.current = window.setTimeout(() => dispatch({ type: "clear-notice" }), ms)
  }, [])

  const decide = useCallback(
    (d: ReviewDecision) => {
      flush()
      pending.current = d
      dispatch({ type: "decide", decision: d })
      timer.current = window.setTimeout(() => flush(), UNDO_WINDOW_MS)
      hideNoticeAfter(UNDO_WINDOW_MS)
    },
    [flush, hideNoticeAfter],
  )

  const undo = useCallback(() => {
    if (!pending.current) return
    if (timer.current !== null) window.clearTimeout(timer.current)
    timer.current = null
    pending.current = null
    dispatch({ type: "undo" })
  }, [])

  const bulkApproved = useCallback(
    (approved: string[], skipped: number) => {
      dispatch({ type: "bulk-ok", approved, skipped })
      hideNoticeAfter(BULK_TOAST_MS)
    },
    [hideNoticeAfter],
  )

  const clearNotice = useCallback(() => dispatch({ type: "clear-notice" }), [])

  useEffect(() => {
    const onHide = () => flush(true)
    window.addEventListener("pagehide", onHide)
    return () => {
      window.removeEventListener("pagehide", onHide)
      flush(true)
      if (noticeTimer.current !== null) window.clearTimeout(noticeTimer.current)
    }
  }, [flush])

  return { state, decide, undo, flush, bulkApproved, clearNotice }
}
```

If `teacherMutationFailureMessage` is not exported from `@/lib/teacherOutcome` (it is used by `ReviewItem.tsx:31`), import it from where `ReviewItem.tsx` gets it.

- [ ] **Step 6: Implement `useAnswerImages.ts`**

```ts
import { useState } from "react"
import { useReviewItemImage } from "@/lib/hooks/useTeacherApi"

/**
 * The crop loads with the answer (I3: only when the item has a box). The
 * whole page is fetched only once the teacher asks for it, then kept for that
 * item. Any failure is absence: the panel falls back to the transcription, or
 * to "Couldn't show the page."
 */
export function useAnswerImages(itemId: string | undefined, hasScan: boolean) {
  const [pageFor, setPageFor] = useState<string | null>(null)
  const crop = useReviewItemImage(itemId, "crop", hasScan)
  const page = useReviewItemImage(itemId, "page", hasScan && pageFor === itemId)
  return { crop, page, requestPage: () => itemId && setPageFor(itemId), pageRequested: pageFor === itemId }
}
```

- [ ] **Step 7: Run the tests**

Run: `cd web && npx vitest run tests/unit/reviewAnswerView.test.ts tests/unit/reviewPendingDecisions.test.ts && npx tsc -b --noEmit`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git commit -S -m "feat(web): answer view adapter and deferred review decisions with undo" -- web/src/portals/teacher/screens/review/answerView.ts web/src/portals/teacher/screens/review/pendingDecisions.ts web/src/portals/teacher/screens/review/usePendingDecisions.ts web/src/portals/teacher/screens/review/useAnswerImages.ts web/tests/unit/reviewAnswerView.test.ts web/tests/unit/reviewPendingDecisions.test.ts
```

---

## Mock-to-token mapping (Tasks 8–10)

| Mock (`base.css`/`final2.css`) | App token / Tailwind |
|---|---|
| `--p` #042f4f | `primary` (`bg-primary`, `text-primary`) |
| `--ph` | `primary-hover` |
| `--pc` | `primary-container` |
| `--s` | `surface` |
| `--l` #fff | `surface-container-lowest` |
| `--sl` | `surface-container-low` |
| `--sc` | `surface-container` |
| `--sh` | `surface-container-high` |
| `--ink` | `on-surface` |
| `--v` | `on-surface-variant` |
| `--o` | `outline` (borders as `shadow-[inset_0_0_0_1px_var(--color-outline)]`) |
| `--ov` | `outline-variant` |
| `--okc` / `--okf` | `success-container` / `success` |
| `--err` / `--errc` / `--onerrc` | `error` / `error-container` / `on-error-container` |
| `--gold` | `tertiary` |
| `--night` | `inverse-surface` (text `inverse-on-surface`) |
| `--tide` | `inverse-primary` |
| `--ease` | `ease-[var(--ease-out)]` |
| bump ease | `var(--ease-expo)` |
| Bricolage 800 | `font-display font-extrabold` |
| JetBrains Mono 600 | `font-mono font-semibold tabular-nums` |
| Schibsted | `font-sans` (default) |
| radius 14 | `rounded-[var(--radius-button)]` (14px) |
| radius 12 | `rounded-[var(--radius-chip)]` |
| radius 16 | `rounded-2xl` |
| radius 18 | `rounded-[var(--radius-inner)]` |
| menu shadow `0 30px 60px -40px oklch(.3 .06 242/.45), 0 0 0 1px var(--ov)` | `shadow-[0_30px_60px_-40px_oklch(0.3_0.06_242/0.45),0_0_0_1px_var(--color-outline-variant)]` |

Exact sizes (copy them as arbitrary values):
- **Header count:** 56px at 1248px and up, 48px at 721–1247, 44px below 721. `font-display`, tracking `-0.04em`, `text-primary`.
- **Header title:** 32px/1.15, weight 800, tracking `-0.02em`; 24px below 1248.
- **Progress bar:** 8px tall, radius 4, track `surface-container-high`, fill `primary`.
- **Tools buttons:** padding 9×14, 13px.
- **Search:** radius 14, inset 1px outline, padding-inline 12; the input is 14px weight 600 with padding-block 10. On focus: inset 1.5px primary plus a 3px primary-container ring. The `/` kbd is mono 11 on `surface-container-high`, radius 6, padding 1×6.
- **Sort button:** 13.5px weight 600, padding-inline 12, radius 14, inset 1px outline. The menu is `min-w-[180px]`, radius 16, padding 6; each item is 14px with padding 9×10, radius 10, the selected one on `primary-container`.
- **Chips:** `rounded-pill bg-primary-container text-primary` 12.5px weight 600, padding 3/4/3/10. The × circle is 18px (28px on coarse pointers) on `surface-container-lowest`.
- **"+ Filter":** 1.5px dashed outline, pill, padding 3×12, 12.5px; on hover the text and border turn primary. Its menu is absolute, full width, radius 18, padding 8.
- **Group label:** mono 10.5, tracking 0.08em, uppercase.
- **Value checkbox:** 18px, radius 6.
- **Row:** grid `auto auto 1fr auto` in select mode (`auto 1fr auto` otherwise), padding 12, radius 14, gap 10, `max-h-[100px]`. Focused: `bg-surface-container-lowest` with an inset 2px primary ring.
- **Row ring:** KeyRing size 52; its inner disc matches the row background.
- **Row text:** name 15px/1.25 weight 700; subtitle 13px `on-surface-variant`; why 14px/1.35 with an 8px dot in the ring tone; mark is `font-display` 28px weight 800, tracking `-0.03em`, tabular.
- **List gap:** 4px.
- **Queue column:** `minmax(340px,400px)` at 1248px and up and `minmax(300px,360px)` at 721–1247. Padding 22/16/22/22 (18/14/18/18 at 721–1247, 16 below 721). Background `surface-container-low` with a 1px `outline-variant` right border.
- **Panel:** padding 24×36 (20×24 at 721–1247), `max-w-[780px]`, gap 14.
- **Panel title:** 21px/1.25 weight 700. The subtitle is mono 12.5. Nav buttons are 44px, radius 12, on `primary-container`, with a mono `min-w-16` position between them.
- **View toggle:** `bg-surface-container` radius 12 padding 3. Buttons are 13px weight 700, padding 6×14, radius 9. The on state is `bg-surface-container-lowest text-primary` with a 1px `outline-variant` ring.
- **Answer card:** radius 16, inset 1px outline, white, ruled with `repeating-linear-gradient(transparent 0 33px, var(--color-primary-container) 33px 34px)`, padding 14×18, `min-h-[210px]`. Transcription text is 22px/36px below 721.
- **Student said:** `bg-surface-container-low` radius 14 padding 10×14.
- **Stepper:** `bg-primary-container` radius 16 padding 4. Buttons are 40px (48px coarse), radius 12, on `surface-container-lowest`, 22px weight 700 primary. The value is mono 20 with `min-w-[76px]`. The delta line is mono 12.5 `on-surface-variant`.
- **Tick row:** padding 10×12, radius 12, `bg-surface-container-low`, hover `bg-surface-container`, `min-h-12` on coarse pointers. Its box is 20px radius 6. Ticked: `bg-success-container`, box `bg-success`. Disabled: opacity 0.4. The tariff pill is mono 12 on `surface-container-lowest`, radius 8, padding 1×7. The code is mono 12.5. "OR" is mono 10.5, tracking 0.08em.
- **Scheme disclosure:** `bg-surface-container-low` radius 14 padding 10×14. The summary is 14px weight 700 primary; the body is 14px/1.5 `max-w-[68ch]`.
- **Note textarea:** radius 12, inset 1px outline.
- **Actions bar:** sticky bottom, `bg-surface`, padding-block 10/4, shadow `0 -12px 14px -10px var(--color-surface)`. The primary button is `flex-1`.
- **Queue clear:** number 120px `font-display` primary; h2 32px/1.15 weight 800; p 16px/1.5 `on-surface-variant`.
- **Undo toast:** fixed, bottom 24 (plus the bottom-nav height on phone), centred, `bg-inverse-surface text-inverse-on-surface`, radius 16, padding 12×16, gap 16. "Undo" is `text-inverse-primary` 14px weight 700.
- **Skeleton rows:** 76px, radius 14, `bg-surface-container-high`.
- **Ticks:** the geometric tick SVG `M3.5 8.5 6.5 11.5 12.5 4.5`, stroke 2.25, square cap, miter join, 14px (16px in the sort menu).

Copy, verbatim from the mock unless a keep-list item says otherwise:
- **Tools:** "Select" / "Cancel"
- **Search:** placeholder "Search", aria-label "Search students, papers or questions"
- **Filters:** "+ Filter", "Filter by", "‹ Reason"
- **No match:** "No answers match these filters." / "Clear filters"
- **Loading:** aria-label "Loading the review queue"
- **Error:** "Couldn't load the review queue." plus the body from `teacherLoadFailureMessage` (falling back to "Check your connection and try again.") and "Try again"
- **Panel:** "Answer" / "Whole page", "Student said", "No self-review yet.", "Mark scheme wording", "Lemely's notes", "Dismiss flag", back "Queue", aria labels "Previous answer" / "Next answer" / "One mark less" / "One mark more"
- **Queue clear:** "Queue clear." / "Mark another class set"
- **First run:** "Nothing to review yet" / "When Lemely isn't sure about a mark, the answer comes here for you to decide." Steps: "Mark a class set" ("Drop the PDFs on Papers. Names are read off the covers."), "Lemely flags the unsure answers" ("Most papers come back with two or three."), "You decide here" ("Tick or change the mark. Usually under a minute each."). Button "Mark papers"; ghost caption "Answers to check will look like this".
- **Phone first run:** "When Lemely isn't sure about a mark, the answer lands here for you." Steps "Mark a class set" ("Names are read off the covers."), "Lemely flags unsure answers" ("Usually two or three a paper."), "You decide" ("Under a minute each.").
- **Sparse:** "That's the only one." / "Each class set you mark adds a few answers here. Checking them keeps every grade honest." / "Mark another class set"
- **Nothing waiting:** "Nothing to review." / "Every mark is confident or already decided."
- **Integrity line:** "A signal to look at, not a verdict. Dismissing never changes the student's mark."

---

## Task 8: Queue column UI (designer)

**Agent:** `designer`. Invoke the impeccable skill and read `.claude/skills/impeccable/reference/craft-floor.md` first. Read the taste memories (see Global Constraints).

**Files:**
- Create: `review/QueueHeader.tsx`, `review/SortMenu.tsx`, `review/FilterMenu.tsx`, `review/FilterBar.tsx`, `review/QueueRow.tsx`, `review/QueueStates.tsx`, `review/QueueColumn.tsx`, `review/review.css`
- Test: `web/tests/unit/reviewQueueSource.test.ts`. This is a source-scan guard: every `review/*.tsx` file uses tokens, not raw hex, and every motion class has a reduced-motion fallback in `review.css`.

**Interfaces:**
- Consumes:
  - Task 5 model functions
  - F1 `KeyRing`, `Binny`, `Walkthrough`, `GhostRows` from `@/components/redesign`
  - `ReviewQueueItem`, `ReviewQueueFilters`, `FilterOptions`
- Produces:

```ts
// QueueHeader.tsx
export function QueueHeader(p: { left: number; done: number }): JSX.Element
// SortMenu.tsx
export function SortMenu(p: { value: ReviewSort; onChange: (s: ReviewSort) => void }): JSX.Element
// FilterMenu.tsx
export function FilterMenu(p: { filters: ReviewQueueFilters; options: FilterOptions; onToggle: (c: FilterCategory, v: string) => void; onClose: () => void }): JSX.Element
// FilterBar.tsx
export function FilterBar(p: {
  filters: ReviewQueueFilters; options: FilterOptions; shownLine: string | null
  onSearch: (q: string) => void; onSort: (s: ReviewSort) => void
  onToggle: (c: FilterCategory, v: string) => void; onRemove: (c: FilterCategory, v: string) => void
  searchRef: React.RefObject<HTMLInputElement | null>
}): JSX.Element
// QueueRow.tsx
export function QueueRow(p: {
  item: ReviewQueueItem; focused: boolean; gone: boolean; selecting: boolean; picked: boolean
  onOpen: (id: string) => void; onPick: (id: string) => void
}): JSX.Element
// QueueStates.tsx
export function QueueLoading(): JSX.Element
export function QueueError(p: { message: string; onRetry: () => void }): JSX.Element
export function NoMatch(p: { onClear: () => void }): JSX.Element
export function SparseNote(p: { markHref: string }): JSX.Element
export function FirstRun(p: { markHref: string; phone: boolean }): JSX.Element
export function NothingWaiting(): JSX.Element
export function Cleared(p: { tally: Tally; markHref: string }): JSX.Element
export function TeacherBinny(p: { mood: BinnyMood; size?: number }): JSX.Element // head-crop wrapper
// QueueColumn.tsx
export function QueueColumn(p: QueueColumnProps): JSX.Element // props below
```

- [ ] **Step 1: Write the source guard test** (`web/tests/unit/reviewQueueSource.test.ts`)

```ts
import { readdirSync, readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"

const DIR = join(import.meta.dirname, "../../src/portals/teacher/screens/review")
const tsx = readdirSync(DIR).filter((f) => f.endsWith(".tsx"))

describe("review screens source", () => {
  it("uses design tokens, never raw colours", () => {
    for (const f of tsx) {
      const src = readFileSync(join(DIR, f), "utf8")
      expect(src, f).not.toMatch(/#[0-9a-fA-F]{3,8}\b/)
      expect(src, f).not.toMatch(/\boklch\(\s*0?\.\d/)
    }
  })
  it("gives every animation a reduced-motion fallback", () => {
    const css = readFileSync(join(DIR, "review.css"), "utf8")
    expect(css).toMatch(/@media \(prefers-reduced-motion: reduce\)/)
    for (const name of ["lm-rq-bump", "lm-rq-skel"]) {
      expect(css).toContain(`@keyframes ${name}`)
    }
    expect(css).toMatch(/prefers-reduced-motion: reduce\)[\s\S]*animation: none/)
  })
  it("never shows Binny outside the calm states", () => {
    const col = readFileSync(join(DIR, "QueueColumn.tsx"), "utf8")
    expect(col).not.toMatch(/<Binny\b/)
  })
})
```

The shadow token `oklch(0.3_0.06_242/0.45)` is allowed. The regex only rejects `oklch(0.` or `oklch(.` followed by digits with no underscore. If the guard trips on that shadow, define it once in `review.css` as `--lm-rq-menu-shadow` and use `shadow-[var(--lm-rq-menu-shadow)]`. That is a local custom property, not a design token change.

- [ ] **Step 2: Run it to verify it fails**

Run: `cd web && npx vitest run tests/unit/reviewQueueSource.test.ts`
Expected: FAIL (`review.css` missing).

- [ ] **Step 3: Write `review/review.css`**

```css
/* L5 review queue: motion and the ruled answer card, from review-r1/final2.css.
   No colours are defined here; every colour is a design token. */
@keyframes lm-rq-bump {
  0% { transform: translateY(8px) scale(0.9); opacity: 0.4; }
  60% { transform: scale(1.08); }
  100% { transform: none; opacity: 1; }
}
@keyframes lm-rq-skel {
  50% { opacity: 0.55; }
}
.lm-rq-bump { animation: lm-rq-bump 0.35s var(--ease-expo); }
.lm-rq-bump-lg { animation: lm-rq-bump 0.6s var(--ease-expo); }
.lm-rq-skel { animation: lm-rq-skel 1.6s ease-in-out infinite; }
.lm-rq-row {
  transition: opacity 0.3s var(--ease-out), transform 0.3s var(--ease-out),
    max-height 0.35s var(--ease-out), background-color 0.15s;
  max-height: 100px;
  overflow: hidden;
}
.lm-rq-row[data-gone] {
  opacity: 0;
  transform: translateX(24px);
  max-height: 0;
  padding-block: 0 !important;
  border: 0 !important;
  pointer-events: none;
}
.lm-rq-ruled {
  background-image: repeating-linear-gradient(
    transparent 0 33px,
    var(--color-primary-container) 33px 34px
  );
}
.lm-rq-toast {
  transition: opacity 0.25s var(--ease-out), transform 0.25s var(--ease-out);
}
@media (prefers-reduced-motion: reduce) {
  .lm-rq-bump, .lm-rq-bump-lg, .lm-rq-skel { animation: none; }
  .lm-rq-row, .lm-rq-toast { transition: none; }
  .lm-rq-toast { transform: translateX(-50%) !important; }
}
```

- [ ] **Step 4: Build the components.** The JSX skeletons below are the contract. The designer fills the classes from the token mapping and sizes above. Every state branch is shown.

`QueueHeader.tsx`:

```tsx
import { useEffect, useRef, useState } from "react"
import { headerTitle, progressOf } from "./reviewQueueModel"

export function QueueHeader({ left, done }: { left: number; done: number }) {
  const [bumpKey, setBumpKey] = useState(0)
  const prev = useRef(left)
  useEffect(() => {
    if (prev.current !== left) setBumpKey((k) => k + 1)
    prev.current = left
  }, [left])
  return (
    <div className="grid gap-3">
      <div className="flex items-baseline gap-2.5">
        <span key={bumpKey} className="lm-rq-bump inline-block font-display text-[44px] font-extrabold leading-none tracking-[-0.04em] text-primary tabular-nums shell-sm:text-[48px] shell-lg:text-[56px]" aria-hidden="true">
          {left}
        </span>
        <h1 className="text-[24px] font-extrabold leading-[1.15] tracking-[-0.02em] shell-lg:text-[32px]">
          <span className="sr-only">{left} </span>
          {headerTitle(left, done)}
        </h1>
      </div>
      <div className="h-2 overflow-hidden rounded-[4px] bg-surface-container-high" role="progressbar" aria-label="Answers decided" aria-valuemin={0} aria-valuemax={left + done} aria-valuenow={done}>
        <b className="block h-full rounded-[4px] bg-primary transition-[width] duration-500 ease-[var(--ease-out)] motion-reduce:transition-none" style={{ width: `${progressOf(left, done) * 100}%` }} />
      </div>
    </div>
  )
}
```

`shell-lg:` is the 1248px variant (`--breakpoint-shell-lg`) and `shell-sm:` is 721px. If Tailwind doesn't generate those variants from the custom breakpoints, use `min-[1248px]:` and `min-[721px]:`.

`SortMenu.tsx`. It is a themed button and menu with keyboard support:
- Esc closes it.
- ArrowUp and ArrowDown move between items.
- An outside click closes it.
- Each item is a `menuitemradio`.

```tsx
import { useEffect, useRef, useState } from "react"
import type { ReviewSort } from "@/lib/teacherTypes"
import { SORT_OPTIONS, sortLabel } from "./reviewQueueModel"
import { Tick } from "./Tick"

export function SortMenu({ value, onChange }: { value: ReviewSort; onChange: (s: ReviewSort) => void }) {
  const [open, setOpen] = useState(false)
  const wrap = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const onDoc = (e: MouseEvent) => { if (!wrap.current?.contains(e.target as Node)) setOpen(false) }
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false) }
    document.addEventListener("mousedown", onDoc)
    document.addEventListener("keydown", onKey)
    return () => { document.removeEventListener("mousedown", onDoc); document.removeEventListener("keydown", onKey) }
  }, [open])
  return (
    <div ref={wrap} className="relative flex flex-none">
      <button type="button" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen((o) => !o)} className="inline-flex items-center gap-2 whitespace-nowrap rounded-[14px] bg-surface-container-lowest px-3 text-[13.5px] font-semibold shadow-[inset_0_0_0_1px_var(--color-outline)] hover:shadow-[inset_0_0_0_1px_var(--color-primary)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary">
        <span>{sortLabel(value)}</span>
        <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true"><path d="M2.5 4.5 6 8l3.5-3.5" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" /></svg>
      </button>
      {open ? (
        <div role="menu" aria-label="Sort answers" className="absolute end-0 top-[calc(100%+6px)] z-20 min-w-[180px] rounded-2xl bg-surface-container-lowest p-1.5 shadow-[var(--lm-rq-menu-shadow)]">
          {SORT_OPTIONS.map((o) => (
            <button key={o.value} type="button" role="menuitemradio" aria-checked={value === o.value} onClick={() => { onChange(o.value); setOpen(false) }} className="flex w-full items-center gap-2.5 rounded-[10px] px-2.5 py-[9px] text-start text-[14px] font-semibold hover:bg-primary-container aria-checked:bg-primary-container aria-checked:text-primary">
              {o.label}
              <span className="ms-auto">{value === o.value ? <Tick size={16} /> : null}</span>
            </button>
          ))}
        </div>
      ) : null}
    </div>
  )
}
```

Add `review/Tick.tsx`, the geometric tick shared by the sort menu, filter values, select boxes and tick rows:

```tsx
export function Tick({ size = 14 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" aria-hidden="true" className="block fill-none stroke-current [stroke-linecap:square] [stroke-linejoin:miter]" strokeWidth={2.25}>
      <path d="M3.5 8.5 6.5 11.5 12.5 4.5" />
    </svg>
  )
}
```

`FilterMenu.tsx` is the two-step menu (category, then values):

```tsx
import { useState } from "react"
import type { ReviewQueueFilters } from "@/lib/reviewQueueQuery"
import { filterCategories, filterValues, type FilterCategory, type FilterOptions } from "./reviewQueueModel"
import { Tick } from "./Tick"

export function FilterMenu({ filters, options, onToggle, onClose }: { filters: ReviewQueueFilters; options: FilterOptions; onToggle: (c: FilterCategory, v: string) => void; onClose: () => void }) {
  const [step, setStep] = useState<FilterCategory | null>(null)
  return (
    <div role="menu" aria-label="Add a filter" onKeyDown={(e) => e.key === "Escape" && onClose()} className="absolute inset-x-0 top-[calc(100%+6px)] z-20 rounded-[18px] bg-surface-container-lowest p-2 shadow-[var(--lm-rq-menu-shadow)]">
      {step === null ? (
        <>
          <div className="px-2.5 pb-0.5 pt-1.5 font-mono text-[10.5px] font-semibold uppercase tracking-[0.08em] text-on-surface-variant">Filter by</div>
          {filterCategories(filters).map((c) => (
            <button key={c.key} type="button" role="menuitem" onClick={() => setStep(c.key)} className="flex w-full items-center gap-2.5 rounded-[10px] px-2.5 py-[9px] text-start text-[14px] font-semibold hover:bg-primary-container">
              {c.label}
              {c.count > 0 ? <span className="rounded-pill bg-primary px-[7px] py-px font-mono text-[11px] text-on-primary">{c.count}</span> : null}
              <span className="ms-auto text-on-surface-variant" aria-hidden="true">›</span>
            </button>
          ))}
        </>
      ) : (
        <>
          <button type="button" role="menuitem" onClick={() => setStep(null)} className="flex w-full items-center gap-2.5 rounded-[10px] px-2.5 py-[9px] text-start text-[14px] font-semibold hover:bg-primary-container">
            ‹ {filterCategories(filters).find((c) => c.key === step)?.label}
          </button>
          {filterValues(step, filters, options).map((v) => (
            <button key={v.value} type="button" role="menuitemcheckbox" aria-checked={v.checked} onClick={() => onToggle(step, v.value)} className="flex w-full items-center gap-2.5 rounded-[10px] px-2.5 py-[9px] text-start text-[14px] font-semibold hover:bg-primary-container">
              <span className={`inline-grid size-[18px] flex-none place-items-center rounded-[6px] text-on-primary ${v.checked ? "bg-primary" : "bg-surface-container-lowest shadow-[inset_0_0_0_1.5px_var(--color-outline)]"}`}>{v.checked ? <Tick size={12} /> : null}</span>
              {v.label}
            </button>
          ))}
        </>
      )}
    </div>
  )
}
```

`FilterBar.tsx`:
- The search updates the URL debounced by 250ms. It keeps a local value, applies it on change through a timeout, and applies it at once on Enter.
- The row holds search and sort, then chips and "+ Filter", then "Showing N of M".
- "+ Filter" toggles `FilterMenu`. An outside click and Esc close it.

```tsx
export function FilterBar(p: FilterBarProps) {
  const [q, setQ] = useState(p.filters.q)
  const [menuOpen, setMenuOpen] = useState(false)
  const wrap = useRef<HTMLDivElement>(null)
  useEffect(() => setQ(p.filters.q), [p.filters.q])
  useEffect(() => {
    if (q === p.filters.q) return
    const t = window.setTimeout(() => p.onSearch(q), 250)
    return () => window.clearTimeout(t)
  }, [q]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!menuOpen) return
    const onDoc = (e: MouseEvent) => { if (!wrap.current?.contains(e.target as Node)) setMenuOpen(false) }
    document.addEventListener("mousedown", onDoc)
    return () => document.removeEventListener("mousedown", onDoc)
  }, [menuOpen])
  const chips = filterChips(p.filters, p.options)
  return (
    <div className="grid min-w-0 gap-2">
      <div className="flex min-w-0 gap-2">
        <label className="flex min-w-0 flex-1 items-center gap-2 rounded-[14px] bg-surface-container-lowest px-3 text-on-surface-variant shadow-[inset_0_0_0_1px_var(--color-outline)] focus-within:shadow-[inset_0_0_0_1.5px_var(--color-primary),0_0_0_3px_var(--color-primary-container)]">
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" aria-hidden="true"><circle cx="7" cy="7" r="4.5" /><path d="m10.5 10.5 3 3" /></svg>
          <input ref={p.searchRef} type="search" value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && p.onSearch(q)} placeholder="Search" aria-label="Search students, papers or questions" className="w-full min-w-0 flex-1 border-0 bg-transparent py-2.5 text-[14px] font-semibold text-on-surface caret-primary outline-0" />
          <span className="rounded-[6px] bg-surface-container-high px-1.5 py-px font-mono text-[11px]" aria-hidden="true">/</span>
        </label>
        <SortMenu value={p.filters.sort} onChange={p.onSort} />
      </div>
      <div ref={wrap} className="relative min-w-0">
        <div className="flex flex-wrap items-center gap-1.5">
          {chips.map((c) => (
            <span key={`${c.category}|${c.value}`} className="inline-flex items-center gap-1.5 rounded-pill bg-primary-container py-[3px] pe-1 ps-2.5 text-[12.5px] font-semibold text-primary">
              {c.label}
              <button type="button" aria-label={`Remove ${c.label}`} onClick={() => p.onRemove(c.category, c.value)} className="inline-grid size-[18px] place-items-center rounded-pill bg-surface-container-lowest pointer-coarse:size-7">×</button>
            </span>
          ))}
          <button type="button" aria-haspopup="menu" aria-expanded={menuOpen} onClick={() => setMenuOpen((o) => !o)} className="rounded-pill border-[1.5px] border-dashed border-outline px-3 py-[3px] text-[12.5px] font-semibold text-on-surface-variant hover:border-primary hover:text-primary pointer-coarse:min-h-9">+ Filter</button>
        </div>
        {menuOpen ? <FilterMenu filters={p.filters} options={p.options} onToggle={p.onToggle} onClose={() => setMenuOpen(false)} /> : null}
      </div>
      {p.shownLine ? <div className="text-[13px] text-on-surface-variant" role="status">{p.shownLine}</div> : null}
    </div>
  )
}
```

`QueueRow.tsx`:

```tsx
import { KeyRing } from "@/components/redesign"
import type { ReviewQueueItem } from "@/lib/teacherTypes"
import { plainWhy, ringLabel, ringText, ringTone, ringValue, rowSubtitle, selectable } from "./reviewQueueModel"
import { Tick } from "./Tick"

const DOT: Record<ReturnType<typeof ringTone>, string> = { warn: "bg-error", gold: "bg-tertiary", neutral: "bg-outline" }

export function QueueRow({ item, focused, gone, selecting, picked, onOpen, onPick }: QueueRowProps) {
  const tone = ringTone(item.confidenceScore)
  const canPick = selectable(item)
  return (
    <li>
      <button
        type="button"
        data-review-row={item.itemId}
        data-gone={gone || undefined}
        aria-current={!selecting && focused ? "true" : undefined}
        aria-pressed={selecting ? picked : undefined}
        aria-disabled={selecting && !canPick ? true : undefined}
        title={selecting && !canPick ? "Integrity flags aren't selectable for bulk-approve. Open this item instead" : undefined}
        onClick={() => (selecting ? canPick && onPick(item.itemId) : onOpen(item.itemId))}
        className={`lm-rq-row grid w-full items-center gap-2.5 rounded-[14px] p-3 text-start ${selecting ? "grid-cols-[auto_auto_1fr_auto]" : "grid-cols-[auto_1fr_auto]"} ${focused && !selecting ? "bg-surface-container-lowest shadow-[inset_0_0_0_2px_var(--color-primary)]" : "hover:bg-surface-container"} focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary`}
      >
        {selecting ? (
          <span className={`grid size-[22px] place-items-center rounded-[7px] text-on-primary ${picked ? "bg-primary" : "bg-surface-container-lowest shadow-[inset_0_0_0_1.5px_var(--color-outline)]"} ${canPick ? "" : "opacity-35"}`} aria-hidden="true">{picked ? <Tick /> : null}</span>
        ) : null}
        <KeyRing value={ringValue(item.confidenceScore)} size={52} tone={tone === "gold" ? "gold" : "warn"} label={ringLabel(item.confidenceScore)} center={<span className="font-mono text-[14px] font-semibold tabular-nums tracking-[-0.02em]">{ringText(item.confidenceScore)}{item.confidenceScore != null ? <small className="text-[9px] opacity-70">%</small> : null}</span>} />
        <span className="grid min-w-0 gap-[3px]">
          <span className="truncate"><b className="text-[15px] font-bold leading-[1.25] tracking-[-0.005em]">{item.studentDisplayName}</b> <span className="whitespace-nowrap text-[13px] text-on-surface-variant">{rowSubtitle(item)}</span></span>
          <span className="flex items-center gap-[7px] text-[14px] leading-[1.35]"><i className={`size-2 flex-none rounded-full ${DOT[tone]}`} aria-hidden="true" />{plainWhy(item)}</span>
        </span>
        <span className="font-display text-[28px] font-extrabold leading-none tracking-[-0.03em] tabular-nums" aria-label={`Lemely gave ${item.aiAwardedMarks ?? "–"} of ${item.maximumMarks ?? "–"}`}>
          {item.aiAwardedMarks ?? "–"}/{item.maximumMarks ?? "–"}
        </span>
      </button>
    </li>
  )
}
```

For a null score, if F1's `KeyRing` has no neutral tone, pass `tone="warn"` with `value={0}`. The track then shows empty and the centre shows "–". List this as a small deviation in the PR.

`QueueStates.tsx`:

```tsx
import { Binny, GhostRows, Walkthrough, type BinnyMood } from "@/components/redesign"
import { CheckCircle, Flag, Stack } from "@phosphor-icons/react"
import { Link } from "react-router-dom"
import { clearedSummary, type Tally } from "./reviewQueueModel"

/** The teacher head-crop: Binny clipped to his head (F1 head-crop prop if present, else this mask). */
export function TeacherBinny({ mood, size = 56 }: { mood: BinnyMood; size?: number }) {
  return (
    <span className="relative inline-block flex-none overflow-hidden rounded-full" style={{ width: size, height: size }} aria-hidden="true">
      <Binny mood={mood} size={Math.round(size * 1.45)} motion="idle" className="absolute start-1/2 top-0 -translate-x-1/2" aria-hidden />
    </span>
  )
}

export function QueueLoading() {
  return (
    <div className="grid gap-2" aria-busy="true" aria-label="Loading the review queue">
      {[0, 1, 2, 3].map((i) => <div key={i} className="lm-rq-skel h-[76px] rounded-[14px] bg-surface-container-high" />)}
    </div>
  )
}

export function QueueError({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div role="alert" className="grid justify-items-start gap-2.5 px-1 py-7">
      <h2 className="text-[24px] font-extrabold leading-[1.2] tracking-[-0.02em]">Couldn't load the review queue.</h2>
      <p className="text-on-surface-variant">{message}</p>
      <button type="button" onClick={onRetry} className="rounded-[14px] bg-primary px-[18px] py-[11px] text-[14px] font-bold text-on-primary active:scale-[.97]">Try again</button>
    </div>
  )
}

export function NoMatch({ onClear }: { onClear: () => void }) {
  return (
    <div role="status" className="grid justify-items-center gap-3 px-3 py-7 text-center text-on-surface-variant">
      <b className="text-[16px] font-bold text-on-surface">No answers match these filters.</b>
      <button type="button" onClick={onClear} className="rounded-[14px] bg-primary-container px-[18px] py-[11px] text-[14px] font-bold text-primary">Clear filters</button>
    </div>
  )
}

export function SparseNote({ markHref }: { markHref: string }) {
  return (
    <div className="grid gap-1.5 rounded-[18px] bg-primary-container px-[18px] py-4">
      <b className="text-[16px] font-bold text-primary">That's the only one.</b>
      <p className="text-[14px] text-primary opacity-85">Each class set you mark adds a few answers here. Checking them keeps every grade honest.</p>
      <Link to={markHref} className="justify-self-start rounded-[14px] bg-surface-container-lowest px-3.5 py-2 text-[13px] font-bold text-primary">Mark another class set</Link>
    </div>
  )
}

export function FirstRun({ markHref, phone }: { markHref: string; phone: boolean }) {
  const steps = phone
    ? [
        { icon: Stack, title: "Mark a class set", body: "Names are read off the covers." },
        { icon: Flag, title: "Lemely flags unsure answers", body: "Usually two or three a paper." },
        { icon: CheckCircle, title: "You decide", body: "Under a minute each." },
      ]
    : [
        { icon: Stack, title: "Mark a class set", body: "Drop the PDFs on Papers. Names are read off the covers." },
        { icon: Flag, title: "Lemely flags the unsure answers", body: "Most papers come back with two or three." },
        { icon: CheckCircle, title: "You decide here", body: "Tick or change the mark. Usually under a minute each." },
      ]
  return (
    <div className="grid gap-6">
      <section className="grid max-w-[820px] gap-[22px] rounded-[28px] bg-surface-container-lowest p-7 shadow-[inset_0_0_0_1px_var(--color-outline-variant)] max-shell-sm:gap-4 max-shell-sm:p-5">
        <div className="flex items-center gap-4">
          <TeacherBinny mood="open" size={phone ? 48 : 56} />
          <div>
            <h2 className="font-display text-[28px] font-extrabold leading-[1.15] tracking-[-0.03em] text-primary">Nothing to review yet</h2>
            {phone ? null : <p className="mt-1 max-w-[46ch] text-on-surface-variant">When Lemely isn't sure about a mark, the answer comes here for you to decide.</p>}
          </div>
        </div>
        {phone ? <p className="text-[14.5px] text-on-surface-variant">When Lemely isn't sure about a mark, the answer lands here for you.</p> : null}
        <Walkthrough steps={steps} />
        <Link to={markHref} className="justify-self-start rounded-[14px] bg-primary px-[18px] py-[11px] text-[14px] font-bold text-on-primary">Mark papers</Link>
      </section>
      {phone ? null : (
        <div className="grid max-w-[820px] gap-2.5 opacity-75" aria-hidden="true">
          <span className="text-[13px] font-semibold text-on-surface-variant">Answers to check will look like this</span>
          <GhostRows rows={2} withLeading />
        </div>
      )}
    </div>
  )
}

export function NothingWaiting() {
  return (
    <div className="grid justify-items-center gap-3 px-6 py-16 text-center">
      <TeacherBinny mood="happy" size={48} />
      <h2 className="text-[24px] font-extrabold tracking-[-0.02em]">Nothing to review.</h2>
      <p className="text-on-surface-variant">Every mark is confident or already decided.</p>
    </div>
  )
}

export function Cleared({ tally, markHref }: { tally: Tally; markHref: string }) {
  return (
    <div role="status" className="grid justify-items-center px-6 py-16 text-center">
      <div className="lm-rq-bump-lg font-display text-[120px] font-extrabold leading-none tracking-[-0.05em] text-primary tabular-nums">{tally.decided}</div>
      <div className="mt-1.5 flex items-center gap-3">
        <TeacherBinny mood="happy" size={40} />
        <h2 className="text-[32px] font-extrabold leading-[1.15] tracking-[-0.02em]">Queue clear.</h2>
      </div>
      <p className="mb-5 mt-2 text-[16px] leading-[1.5] text-on-surface-variant">{clearedSummary(tally)}</p>
      <Link to={markHref} className="rounded-[14px] bg-primary px-[18px] py-[11px] text-[14px] font-bold text-on-primary">Mark another class set</Link>
    </div>
  )
}
```

`QueueColumn.tsx`:

```tsx
export interface QueueColumnProps {
  state: QueueScreenState
  items: ReviewQueueItem[]            // visible (server rows; hidden ids still passed for the collapse)
  hiddenIds: ReadonlySet<string>
  focusId: string | null
  left: number
  done: number
  filters: ReviewQueueFilters
  options: FilterOptions
  shownLine: string | null
  selecting: boolean
  picked: ReadonlySet<string>
  bulk: { label: string; disabled: boolean }
  bulkSkips: { label: string; reason: string }[] | null
  bulkError: string | null
  hasMore: boolean
  loadingMore: boolean
  errorMessage: string
  phone: boolean
  markHref: string
  searchRef: React.RefObject<HTMLInputElement | null>
  onOpen(id: string): void
  onPick(id: string): void
  onToggleSelect(): void
  onBulk(): void
  onDismissSkips(): void
  onFilters(f: ReviewQueueFilters): void
  onLoadMore(): void
  onRetry(): void
}

export function QueueColumn(p: QueueColumnProps) {
  const set = (f: ReviewQueueFilters) => p.onFilters(f)
  const showChrome = p.state === "queue" || p.state === "sparse" || p.state === "no-match"
  return (
    <section aria-label="Review queue" className="grid min-w-0 content-start gap-3 bg-surface-container-low p-4 shell-sm:border-e shell-sm:border-outline-variant shell-sm:p-[18px] shell-lg:p-[22px] shell-lg:pe-4">
      {p.state === "loading" ? <QueueLoading /> : null}
      {p.state === "error" ? <QueueError message={p.errorMessage} onRetry={p.onRetry} /> : null}
      {p.state === "first-run" ? <FirstRun markHref={p.markHref} phone={p.phone} /> : null}
      {p.state === "nothing-waiting" ? <NothingWaiting /> : null}
      {showChrome ? (
        <>
          <QueueHeader left={p.left} done={p.done} />
          <div className="flex items-center gap-2">
            <button type="button" onClick={p.onToggleSelect} aria-pressed={p.selecting} className="rounded-[14px] bg-surface-container-lowest px-3.5 py-[9px] text-[13px] font-bold shadow-[inset_0_0_0_1.5px_var(--color-outline)] active:scale-[.97]">
              {p.selecting ? "Cancel" : "Select"}
            </button>
            <span className="flex-1" />
            <button type="button" onClick={p.onBulk} disabled={p.bulk.disabled} className="rounded-[14px] bg-primary px-3.5 py-[9px] text-[13px] font-bold text-on-primary active:scale-[.97] disabled:cursor-not-allowed disabled:bg-outline">
              {p.bulk.label}
            </button>
          </div>
          {p.bulkError ? <div role="alert" className="text-[13px] text-error">Couldn't approve: {p.bulkError}</div> : null}
          {p.bulkSkips && p.bulkSkips.length > 0 ? (
            <div role="status" className="grid gap-1.5 rounded-[14px] bg-surface-container px-3.5 py-2.5 text-[13px]">
              <div className="flex items-center justify-between gap-3"><b>Some answers were skipped</b><button type="button" onClick={p.onDismissSkips} className="text-primary">Dismiss</button></div>
              <ul className="m-0 list-disc ps-4 text-on-surface-variant">{p.bulkSkips.map((s) => <li key={s.label}>{s.label}: {s.reason}</li>)}</ul>
            </div>
          ) : null}
          <FilterBar
            filters={p.filters}
            options={p.options}
            shownLine={p.shownLine}
            searchRef={p.searchRef}
            onSearch={(q) => set({ ...p.filters, q })}
            onSort={(sort) => set({ ...p.filters, sort })}
            onToggle={(c, v) => set(toggleFilter(p.filters, c, v))}
            onRemove={(c, v) => set(removeFilter(p.filters, c, v))}
          />
          {p.state === "no-match" ? (
            <NoMatch onClear={() => set(clearFilters(p.filters))} />
          ) : (
            <ul className="m-0 grid list-none gap-1 p-0" aria-label="Answers to check">
              {p.items.map((item) => (
                <QueueRow key={item.itemId} item={item} focused={item.itemId === p.focusId} gone={p.hiddenIds.has(item.itemId)} selecting={p.selecting} picked={p.picked.has(item.itemId)} onOpen={p.onOpen} onPick={p.onPick} />
              ))}
            </ul>
          )}
          {p.state === "sparse" ? <SparseNote markHref={p.markHref} /> : null}
          {p.hasMore ? (
            <div className="flex justify-center">
              <button type="button" onClick={p.onLoadMore} disabled={p.loadingMore} className="rounded-[14px] px-3.5 py-2 text-[13px] font-bold text-primary">{p.loadingMore ? "Loading…" : "Load more"}</button>
            </div>
          ) : null}
        </>
      ) : null}
    </section>
  )
}
```

A row that is `gone` stays mounted with `data-gone`, so the collapse animates. Under reduced motion the CSS transition is off and the row is effectively gone at once.

- [ ] **Step 5: Run the guard and the typecheck**

Run: `cd web && npx vitest run tests/unit/reviewQueueSource.test.ts && npx tsc -b --noEmit && npx oxlint src/portals/teacher/screens/review`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git commit -S -m "feat(web): review queue column, filters, sort menu and states" -- web/src/portals/teacher/screens/review/QueueHeader.tsx web/src/portals/teacher/screens/review/SortMenu.tsx web/src/portals/teacher/screens/review/FilterMenu.tsx web/src/portals/teacher/screens/review/FilterBar.tsx web/src/portals/teacher/screens/review/QueueRow.tsx web/src/portals/teacher/screens/review/QueueStates.tsx web/src/portals/teacher/screens/review/QueueColumn.tsx web/src/portals/teacher/screens/review/Tick.tsx web/src/portals/teacher/screens/review/review.css web/tests/unit/reviewQueueSource.test.ts
```

---

## Task 9: Answer panel, mark controls and the phone answer page (designer)

**Agent:** `designer` (impeccable skill plus the craft floor, as in Task 8).

**Files:**
- Create: `review/MarkControls.tsx`, `review/AnswerPanel.tsx`, `review/AnswerPage.tsx`, `review/index.ts`

**Interfaces:**
- Consumes: `AnswerView` (Task 7), `markModel` (Task 6), `useAnswerImages` (Task 7).
- Produces (exported from `review/index.ts` for L8):

```ts
export interface AnswerImages {
  cropUrl: string | null
  onCropError: () => void
  pageUrl: string | null
  onPageError: () => void
  pageRequested: boolean
  requestPage: () => void
}
export interface AnswerNav { pos: number; total: number; onPrev: () => void; onNext: () => void }
export interface AnswerMarking {
  state: MarkState
  onChange: (s: MarkState) => void
  note: string
  onNote: (s: string) => void
  onAccept: () => void          // Accept or Save, at the current total
  onDismiss: (note: string) => void // integrity flags only
}
export function AnswerPanel(p: {
  view: AnswerView
  images: AnswerImages
  nav?: AnswerNav
  onBack?: () => void           // phone only
  marking: AnswerMarking | null // null = read-only (closed item, or L8)
  showShortcuts?: boolean
}): JSX.Element
export function AnswerPage(p: Parameters<typeof AnswerPanel>[0]): JSX.Element
export { answerViewFromReviewItem, type AnswerView } from "./answerView"
export { useAnswerImages } from "./useAnswerImages"
export { initialMarkState, type MarkState } from "./markModel"
```

- [ ] **Step 1: Build `MarkControls.tsx`**

```tsx
import type { MarkPoint, MarkState } from "./markModel"
import { canStep, deltaLine, isBlocked, orBefore, poolHeader, stepDown, stepUp, toggleTick, totalOf } from "./markModel"
import { Tick } from "./Tick"

export function MarkControls({ points, state, max, lemely, disabled, disabledReason, matchedPointIds, onChange }: {
  points: MarkPoint[]; state: MarkState; max: number | null; lemely: number | null
  disabled: boolean; disabledReason: string | null; matchedPointIds: string[]
  onChange: (s: MarkState) => void
}) {
  const total = totalOf(points, state, max, lemely)
  const step = canStep(points, state, max, lemely)
  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-3.5 shell-sm:justify-start">
        <div className="inline-flex items-center gap-0.5 rounded-2xl bg-primary-container p-1">
          <button type="button" aria-label="One mark less" disabled={disabled || !step.down} onClick={() => onChange(stepDown(points, state))} className="size-10 rounded-[12px] bg-surface-container-lowest text-[22px] font-bold text-primary disabled:opacity-35 pointer-coarse:size-12">−</button>
          <span className="min-w-[76px] text-center font-mono text-[20px] font-semibold tabular-nums" aria-live="polite">{total}/{max ?? "–"}</span>
          <button type="button" aria-label="One mark more" disabled={disabled || !step.up} onClick={() => onChange(stepUp(points, state, max))} className="size-10 rounded-[12px] bg-surface-container-lowest text-[22px] font-bold text-primary disabled:opacity-35 pointer-coarse:size-12">+</button>
        </div>
        <span className="font-mono text-[12.5px] font-semibold tracking-[-0.01em] text-on-surface-variant">{deltaLine(total, lemely)}</span>
      </div>
      {disabled && disabledReason ? <p className="text-[13px] text-on-surface-variant">{disabledReason}</p> : null}
      {points.length > 0 ? (
        <div role="group" aria-label="Marking points" className="grid gap-1.5">
          {points.map((p, i) => {
            const on = state.ticked.includes(p.markPointId)
            const blocked = disabled || isBlocked(points, state, p.markPointId, max)
            const pool = poolHeader(points, i)
            return (
              <div key={p.markPointId} className="contents">
                {pool ? <div className="pt-1 text-center font-mono text-[10.5px] font-semibold uppercase tracking-[0.08em] text-on-surface-variant">{pool}</div> : null}
                {orBefore(points, i) ? <div className="-my-0.5 text-center font-mono text-[10.5px] font-semibold tracking-[0.08em] text-on-surface-variant" aria-hidden="true">OR</div> : null}
                <button type="button" data-testid="marker-verdict-row" aria-pressed={on} disabled={!on && blocked} onClick={() => onChange(toggleTick(points, state, p.markPointId, max))} className={`flex w-full items-start gap-2.5 rounded-[12px] px-3 py-2.5 text-start text-[14px] leading-[1.4] transition-colors duration-150 motion-reduce:transition-none disabled:cursor-not-allowed disabled:opacity-40 pointer-coarse:min-h-12 ${on ? "bg-success-container" : "bg-surface-container-low hover:bg-surface-container"}`}>
                  <span className={`mt-px grid size-5 flex-none place-items-center rounded-[6px] text-on-primary ${on ? "bg-success" : "bg-surface-container-lowest shadow-[inset_0_0_0_1.5px_var(--color-outline)]"}`} aria-hidden="true">{on ? <Tick size={12} /> : null}</span>
                  <span className="grid min-w-0 gap-0.5">
                    <span><b className="font-mono text-[12.5px] font-semibold">{p.code}</b> {p.text}</span>
                    {p.verdictLabel || p.ecf ? (
                      <span className="flex flex-wrap gap-2 text-[12.5px] text-on-surface-variant">
                        {p.verdictLabel ? <span>{p.verdictLabel}</span> : null}
                        {p.ecf ? <span>Carried forward</span> : null}
                      </span>
                    ) : null}
                    {p.note ? <span data-testid="point-note" className="line-clamp-2 text-[12.5px] text-on-surface-variant" title={p.note}>{p.note}</span> : null}
                  </span>
                  <span className="ms-auto flex-none rounded-[8px] bg-surface-container-lowest px-[7px] py-px font-mono text-[12px] font-semibold">{p.tariff}</span>
                </button>
              </div>
            )
          })}
        </div>
      ) : (
        <p className="text-[13px] text-on-surface-variant">
          {matchedPointIds.length > 0 ? `Matched scheme points: ${matchedPointIds.join(", ")}` : "No points matched."}
        </p>
      )}
    </>
  )
}
```

- [ ] **Step 2: Build `AnswerPanel.tsx`**

```tsx
import { useState } from "react"
import { Link } from "react-router-dom"
import { Flag } from "@phosphor-icons/react"
import type { AnswerView } from "./answerView"
import { MarkControls } from "./MarkControls"
import { notePlaceholder, primaryActionLabel, totalOf } from "./markModel"
import { relativeTime } from "@/lib/utils"

const ICON_BACK = <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M11 4 6 9l5 5" /></svg>
const ICON_NEXT = <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="m7 4 5 5-5 5" /></svg>

export function AnswerPanel({ view, images, nav, onBack, marking, showShortcuts }: AnswerPanelProps) {
  const [mode, setMode] = useState<"crop" | "page">("crop")
  const [dismissNote, setDismissNote] = useState("")
  const total = marking ? totalOf(view.points, marking.state, view.maximumMarks, view.lemelyMarks) : view.lemelyMarks ?? 0
  const changed = view.lemelyMarks != null && total !== view.lemelyMarks
  const showPage = mode === "page" && view.hasScan
  return (
    <article aria-label={view.title} className="grid w-full max-w-[780px] gap-3.5">
      <header className="flex flex-wrap items-center gap-3 shell-sm:flex-nowrap">
        {onBack ? (
          <button type="button" onClick={onBack} aria-label="Back to the queue" className="inline-flex items-center gap-1.5 rounded-[14px] bg-surface-container-lowest px-3 py-2 text-[14px] font-bold shadow-[inset_0_0_0_1.5px_var(--color-outline)]">{ICON_BACK}Queue</button>
        ) : null}
        <div className="order-3 min-w-0 flex-[1_1_100%] shell-sm:order-none shell-sm:flex-1">
          <h2 className="text-[21px] font-bold leading-[1.25] tracking-[-0.01em]">
            {view.studentHref ? <Link to={view.studentHref} className="hover:underline">{view.title}</Link> : view.title}
          </h2>
          <div className="mt-0.5 font-mono text-[12.5px] font-semibold leading-[1.3] text-on-surface-variant">{view.subtitle}</div>
        </div>
        {nav ? (
          <div className="ms-auto flex items-center gap-1.5">
            <button type="button" aria-label="Previous answer" disabled={nav.pos <= 1} onClick={nav.onPrev} className="grid size-11 place-items-center rounded-[12px] bg-primary-container text-primary disabled:opacity-35">{ICON_BACK}</button>
            <span className="min-w-16 text-center font-mono text-on-surface-variant tabular-nums">{nav.pos || "–"} of {nav.total}</span>
            <button type="button" aria-label="Next answer" disabled={nav.pos >= nav.total} onClick={nav.onNext} className="grid size-11 place-items-center rounded-[12px] bg-primary-container text-primary disabled:opacity-35">{ICON_NEXT}</button>
          </div>
        ) : null}
      </header>

      {view.hasScan ? (
        <div role="tablist" aria-label="Answer view" className="inline-flex justify-self-start rounded-[12px] bg-surface-container p-[3px]">
          {(["crop", "page"] as const).map((m) => (
            <button key={m} type="button" role="tab" aria-selected={mode === m} onClick={() => { setMode(m); if (m === "page") images.requestPage() }} className="rounded-[9px] px-3.5 py-1.5 text-[13px] font-bold text-on-surface-variant aria-selected:bg-surface-container-lowest aria-selected:text-primary aria-selected:shadow-[0_0_0_1px_var(--color-outline-variant)]">
              {m === "crop" ? "Answer" : "Whole page"}
            </button>
          ))}
        </div>
      ) : null}

      {showPage ? (
        <figure className="m-0 grid min-h-[300px] gap-1.5 rounded-2xl bg-surface-container-lowest p-3.5 shadow-[inset_0_0_0_1px_var(--color-outline)]">
          {view.pageLabel ? <figcaption className="font-mono text-[11px] font-semibold uppercase tracking-[0.08em] text-on-surface-variant">{view.pageLabel}</figcaption> : null}
          {images.pageUrl ? (
            <img src={images.pageUrl} alt="The whole page this answer is on" onError={images.onPageError} decoding="async" className="max-h-[70vh] w-full rounded-[10px] object-contain" />
          ) : images.pageRequested ? (
            <div className="lm-rq-skel h-[300px] rounded-[10px] bg-surface-container-high" aria-label="Loading the page" />
          ) : (
            <p className="text-on-surface-variant">Couldn't show the page.</p>
          )}
        </figure>
      ) : images.cropUrl ? (
        <figure className="m-0 grid gap-1.5 rounded-2xl bg-surface-container-lowest p-3.5 shadow-[inset_0_0_0_1px_var(--color-outline)]">
          <img src={images.cropUrl} alt="The region of the student's scan this question's answer was read from" onError={images.onCropError} decoding="async" className="max-h-[420px] w-auto max-w-full rounded-[10px] object-contain" />
          <figcaption className="text-[12.5px] text-on-surface-variant">From the student's scan</figcaption>
        </figure>
      ) : (
        <figure className="lm-rq-ruled relative m-0 min-h-[210px] overflow-hidden rounded-2xl bg-surface-container-lowest px-[18px] py-3.5 shadow-[inset_0_0_0_1px_var(--color-outline)]">
          <p className="m-0 whitespace-pre-wrap text-[22px] leading-[36px] text-on-surface shell-sm:text-[28px] shell-sm:leading-[42px]">{view.transcription ?? "No transcription recorded for this question."}</p>
          <figcaption className="mt-2 text-[12.5px] text-on-surface-variant">Lemely's reading of the answer</figcaption>
        </figure>
      )}

      <section className="grid gap-0.5 rounded-[14px] bg-surface-container-low px-3.5 py-2.5">
        <span className="font-mono text-[11px] font-semibold uppercase tracking-[0.08em] text-on-surface-variant">Student said</span>
        {view.selfReview.length === 0 ? (
          <div className="text-[14px] leading-[1.45] text-on-surface-variant">No self-review yet.</div>
        ) : (
          view.selfReview.map((s) => (
            <div key={s.code} className="text-[14px] leading-[1.45]">
              <b className="font-mono text-[12.5px]">{s.code}</b> {s.claim}{s.evidence ? <> · “{s.evidence}”</> : null}
              <span className="text-on-surface-variant"> · {s.judge}</span>
            </div>
          ))
        )}
      </section>

      {view.status === "open" && marking && !view.integrity ? (
        <MarkControls points={view.points} state={marking.state} max={view.maximumMarks} lemely={view.lemelyMarks} disabled={!view.canAdjust} disabledReason={view.cannotAdjustReason} matchedPointIds={view.matchedPointIds} onChange={marking.onChange} />
      ) : null}

      {view.scheme.expected || view.scheme.topic ? (
        <details className="rounded-[14px] bg-surface-container-low px-3.5 py-2.5">
          <summary className="cursor-pointer text-[14px] font-bold text-primary">Mark scheme wording</summary>
          {view.scheme.expected ? <p className="mt-2 max-w-[68ch] whitespace-pre-wrap text-[14px] leading-[1.5] text-on-surface-variant">{view.scheme.expected}</p> : null}
          {view.scheme.topic ? <p className="mt-1 text-[13px] text-on-surface-variant">Topic: {view.scheme.topic}</p> : null}
        </details>
      ) : null}

      {view.notes.reason || view.notes.feedback ? (
        <details className="rounded-[14px] bg-surface-container-low px-3.5 py-2.5">
          <summary className="cursor-pointer text-[14px] font-bold text-primary">Lemely's notes</summary>
          {view.notes.feedback ? <p className="mt-2 max-w-[68ch] text-[14px] leading-[1.5] text-on-surface-variant">{view.notes.feedback}</p> : null}
          {view.notes.reason ? <p className="mt-1 max-w-[68ch] font-mono text-[12.5px] text-on-surface-variant">{view.notes.reason}</p> : null}
        </details>
      ) : null}

      {view.status !== "open" ? (
        <section role="status" className="grid gap-1.5 rounded-[14px] bg-surface-container px-3.5 py-2.5 text-[14px]">
          <b>{view.status === "dismissed" ? "Dismissed" : "Resolved"}</b>
          {view.correction ? <span>Changed to <span className="font-mono">{view.correction.marks}/{view.maximumMarks ?? "–"}</span>{view.correction.note ? ` · “${view.correction.note}”` : ""}{view.correction.at ? ` · ${relativeTime(view.correction.at)}` : ""}</span> : null}
          {view.resolutionNote ? <span className="text-on-surface-variant">Note: “{view.resolutionNote}”</span> : null}
        </section>
      ) : null}

      {view.status === "open" && marking ? (
        <>
          {view.integrity ? (
            <p className="flex items-start gap-2 text-[13px] text-on-surface-variant"><Flag weight="fill" className="mt-0.5 size-4 flex-none text-on-tertiary-container" aria-hidden />A signal to look at, not a verdict. Dismissing never changes the student's mark.</p>
          ) : null}
          <textarea rows={2} value={view.integrity ? dismissNote : marking.note} onChange={(e) => (view.integrity ? setDismissNote(e.target.value) : marking.onNote(e.target.value))} placeholder={view.integrity ? "Note for your records (optional)" : notePlaceholder(changed)} aria-label={view.integrity ? "Note for your records" : notePlaceholder(changed)} className="w-full resize-none rounded-[12px] bg-surface-container-lowest px-3 py-2.5 text-[14px] leading-[1.45] shadow-[inset_0_0_0_1px_var(--color-outline)] caret-primary" />
          <div className="sticky bottom-0 z-[1] flex gap-2 bg-surface pb-1 pt-2.5 shadow-[0_-12px_14px_-10px_var(--color-surface)] max-shell-sm:pb-[max(4px,env(safe-area-inset-bottom))]">
            {view.integrity ? (
              <button type="button" onClick={() => marking.onDismiss(dismissNote)} className="flex-1 rounded-[14px] bg-primary px-[18px] py-[11px] text-[14px] font-bold text-on-primary active:scale-[.97]">Dismiss flag</button>
            ) : (
              <button type="button" onClick={marking.onAccept} className="flex-1 rounded-[14px] bg-primary px-[18px] py-[11px] text-[14px] font-bold text-on-primary active:scale-[.97]">{primaryActionLabel(total, view.maximumMarks, view.lemelyMarks)}</button>
            )}
          </div>
          {showShortcuts ? (
            <p className="hidden font-mono text-[11px] text-on-surface-variant shell-lg:block" aria-hidden="true">A accept · N next · J/K move · / search</p>
          ) : null}
        </>
      ) : null}
    </article>
  )
}
```

If `relativeTime` is not exported from `@/lib/utils`, use the same import `ReviewItem.tsx:12` uses.

- [ ] **Step 3: Build `AnswerPage.tsx` and `index.ts`**

```tsx
import { AnswerPanel } from "./AnswerPanel"

/** Phone (< 721px): the answer as its own full-screen page, on the immersive
 * route `/teacher/review/:itemId`. The shell hides the tab bar on native. */
export function AnswerPage(props: Parameters<typeof AnswerPanel>[0]) {
  return (
    <div className="min-h-[100dvh] bg-surface px-4 pb-6 pt-3">
      <AnswerPanel {...props} />
    </div>
  )
}
```

```ts
// review/index.ts — the paper view L8 reuses (master plan: L8 imports L5's paper view)
export { AnswerPanel } from "./AnswerPanel"
export type { AnswerImages, AnswerMarking, AnswerNav } from "./AnswerPanel"
export { AnswerPage } from "./AnswerPage"
export { answerViewFromReviewItem, type AnswerView } from "./answerView"
export { useAnswerImages } from "./useAnswerImages"
export { initialMarkState, markPointsFrom, type MarkPoint, type MarkState } from "./markModel"
```

`AnswerPanel.tsx` must `export interface AnswerImages`, `AnswerNav`, `AnswerMarking` and `AnswerPanelProps` with the shapes in Interfaces.

- [ ] **Step 4: Typecheck and lint**

Run: `cd web && npx tsc -b --noEmit && npx oxlint src/portals/teacher/screens/review && npx vitest run tests/unit/reviewQueueSource.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git commit -S -m "feat(web): review answer panel, tick stepper and phone answer page" -- web/src/portals/teacher/screens/review/MarkControls.tsx web/src/portals/teacher/screens/review/AnswerPanel.tsx web/src/portals/teacher/screens/review/AnswerPage.tsx web/src/portals/teacher/screens/review/index.ts
```

---

## Task 10: Screen assembly: routes, URL focus, keyboard, bulk, undo (designer)

**Agent:** `designer`.

**Files:**
- Create: `review/ReviewQueue.tsx`, `review/UndoBar.tsx`
- Modify: `web/src/portals/teacher/index.tsx` (lines 62–63 and the route entries at 522–531 only)

**Interfaces:**
- Consumes: everything above, plus:
  - `useTeacherClasses` and `useBulkApproveReview` from `useTeacherApi`
  - `useReference` and `subjectNameFor` (`@/lib/hooks/useReferenceApi`, `@/lib/reference`)
  - `useNativeFrame`
- Produces: `export function ReviewQueue(): JSX.Element`, the element for both `review` and `review/:itemId`.

- [ ] **Step 1: Build `UndoBar.tsx`**

```tsx
import type { DecisionNotice } from "./pendingDecisions"

export function UndoBar({ notice, onUndo, onClose }: { notice: DecisionNotice | null; onUndo: () => void; onClose: () => void }) {
  const on = notice !== null
  return (
    <div role={notice?.kind === "error" ? "alert" : "status"} aria-live="polite" className={`lm-rq-toast fixed bottom-6 start-1/2 z-40 flex items-center gap-4 rounded-2xl bg-inverse-surface px-4 py-3 text-inverse-on-surface shadow-[0_30px_60px_-40px_oklch(0.3_0.06_242/0.45)] max-sidebar:bottom-[calc(var(--bottom-nav-h,64px)+16px)] ${on ? "pointer-events-auto -translate-x-1/2 translate-y-0 opacity-100" : "pointer-events-none -translate-x-1/2 translate-y-5 opacity-0"}`}>
      <span>{notice?.text}</span>
      {notice?.undo ? <button type="button" onClick={onUndo} className="text-[14px] font-bold text-inverse-primary">Undo</button> : null}
      {notice && !notice.undo ? <button type="button" onClick={onClose} aria-label="Close" className="text-inverse-primary">×</button> : null}
    </div>
  )
}
```

Use the shell's real bottom-nav height custom property if one exists. Check `index.css` for `--bottom-nav` and `pb-bottom-nav`.

- [ ] **Step 2: Build `ReviewQueue.tsx`**

```tsx
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { useNavigate, useParams, useSearchParams } from "react-router-dom"
import { useQueryClient } from "@tanstack/react-query"
import { useBulkApproveReview, useReviewItem, useReviewQueuePage, useTeacherClasses, invalidateAfterResolve } from "@/lib/hooks/useTeacherApi"
import { useReference } from "@/lib/hooks/useReferenceApi"
import { subjectNameFor } from "@/lib/reference"
import { filtersActive, filtersFromSearch, filtersToSearch, filterKey, type ReviewQueueFilters } from "@/lib/reviewQueueQuery"
import { postReviewDecision, type ReviewDecision } from "@/lib/reviewApi"
import { teacherLoadFailureMessage, teacherMutationFailureMessage } from "@/lib/teacherOutcome"
import { useNativeFrame } from "@/lib/useNativeFrame"
import type { ReviewQueueItem } from "@/lib/teacherTypes"
import { AnswerPage } from "./AnswerPage"
import { AnswerPanel } from "./AnswerPanel"
import { answerViewFromReviewItem } from "./answerView"
import { initialMarkState, resolveBody, totalOf, type MarkState } from "./markModel"
import { QueueColumn } from "./QueueColumn"
import { UndoBar } from "./UndoBar"
import { useAnswerImages } from "./useAnswerImages"
import { usePendingDecisions } from "./usePendingDecisions"
import { mergeReviewPages } from "./reviewLabels"
import { SKIP_LINE, bulkButton, isClearItem, nextFocusAfter, positionOf, queueScreenState, questionLabel, shownLine } from "./reviewQueueModel"
import "./review.css"

/** Where "Mark papers" and "Mark another class set" go until L6/L8 settle the class-set upload route. */
const MARK_HREF = "/teacher/grading"

export function ReviewQueue() {
  const { itemId } = useParams<{ itemId?: string }>()
  const [sp, setSp] = useSearchParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { phone } = useNativeFrame()
  const filters = useMemo(() => filtersFromSearch(sp), [sp])
  const key = filterKey(filters)
  const qs = filtersToSearch(filters).toString()
  const suffix = qs ? `?${qs}` : ""

  // K14: Load more, merged and deduped; reset on any filter change.
  const [cursor, setCursor] = useState<string | undefined>(undefined)
  const [pages, setPages] = useState<{ key: string; items: ReviewQueueItem[] }>({ key: "", items: [] })
  const [merged, setMerged] = useState<unknown>(undefined)
  const queue = useReviewQueuePage(filters, cursor)
  if (queue.data && queue.data !== merged) {
    setMerged(queue.data)
    setPages((prev) => mergeReviewPages(prev, { key, items: queue.data!.items }))
  }
  useEffect(() => { setCursor(undefined) }, [key])

  const classes = useTeacherClasses()
  const reference = useReference()
  const options = useMemo(() => ({
    classes: (classes.data?.classes ?? []).map((c) => ({ id: c.id, label: c.label })),
    subjects: queue.data?.subjectCodes ?? [],
    subjectName: (code: string) => subjectNameFor(reference.data, code),
  }), [classes.data, queue.data?.subjectCodes, reference.data])

  const decisions = usePendingDecisions(
    (d, o) => postReviewDecision(d, o),
    (d, row) => {
      if (d.kind === "resolve") invalidateAfterResolve(queryClient, row as ReviewQueueItem)
      else queryClient.invalidateQueries({ queryKey: ["teacher", "review"] })
    },
  )
  const hidden = useMemo(() => new Set(decisions.state.hidden), [decisions.state.hidden])
  const rows = pages.key === key ? pages.items : []
  const open = rows.filter((r) => !hidden.has(r.itemId))
  const openIds = open.map((r) => r.itemId)
  const total = Math.max(0, (queue.data?.total ?? 0) - rows.filter((r) => hidden.has(r.itemId)).length)

  const state = queueScreenState({
    status: queue.isPending && !queue.data ? "pending" : queue.isError && !queue.data ? "error" : "success",
    visibleCount: open.length,
    openTotal: total,
    filtersActive: filtersActive(filters),
    hasHistory: queue.data?.hasHistory ?? true,
    decidedThisSession: decisions.state.tally.decided,
  })

  // Focus: the URL item, else (desktop) the first open row.
  const focusId = itemId ?? (phone ? null : (openIds[0] ?? null))
  const detail = useReviewItem(focusId ?? undefined)
  const view = detail.data ? answerViewFromReviewItem(detail.data) : null
  const images = useAnswerImages(focusId ?? undefined, view?.hasScan ?? false)
  const [mark, setMark] = useState<{ id: string; state: MarkState; note: string } | null>(null)
  const markState = view && mark?.id === view.key ? mark.state : view ? initialMarkState(view.points, view.lemelyMarks) : null
  const note = view && mark?.id === view.key ? mark.note : ""

  const go = useCallback((id: string | null, opts: { replace?: boolean } = {}) => {
    navigate(id ? `/teacher/review/${id}${suffix}` : `/teacher/review${suffix}`, { replace: opts.replace ?? !phone })
  }, [navigate, suffix, phone])

  const setFilters = useCallback((f: ReviewQueueFilters) => {
    setSelecting(false); setPicked(new Set())               // K13
    setSp(filtersToSearch(f), { replace: true })
  }, [setSp])

  const [selecting, setSelecting] = useState(false)
  const [picked, setPicked] = useState<Set<string>>(new Set())
  const bulk = useBulkApproveReview()
  const [skips, setSkips] = useState<{ label: string; reason: string }[] | null>(null)
  const clearIds = open.filter(isClearItem).map((r) => r.itemId)

  function decideFocused() {
    if (!view || !markState || view.status !== "open") return
    const d: ReviewDecision = view.integrity
      ? { kind: "dismiss", itemId: view.key, label: questionLabel(detail.data!), body: { note: note.trim() || undefined } }
      : {
          kind: "resolve",
          itemId: view.key,
          label: questionLabel(detail.data!),
          changed: totalOf(view.points, markState, view.maximumMarks, view.lemelyMarks) !== view.lemelyMarks,
          body: resolveBody({ points: view.points, state: markState, max: view.maximumMarks, lemely: view.lemelyMarks, note, canAdjust: view.canAdjust }),
        }
    const next = nextFocusAfter(openIds, view.key)
    decisions.decide(d)
    setMark(null)
    if (phone) go(null, { replace: false })                 // I22 / Needs decision #14: phone returns to the list
    else go(next, { replace: true })
  }

  function runBulk() {
    decisions.flush()
    const ids = selecting ? [...picked] : clearIds
    const snapshot = rows
    bulk.mutate(ids, {
      onSuccess: (res) => {
        decisions.bulkApproved(res.approved, res.skipped.length)
        setSkips(res.skipped.length ? res.skipped.map((s) => {
          const r = snapshot.find((x) => x.itemId === s.itemId)
          return { label: r ? `${r.studentDisplayName} — ${questionLabel(r)}` : s.itemId, reason: SKIP_LINE[s.reason] ?? s.reason }
        }) : null)
        setSelecting(false); setPicked(new Set())
        if (focusId && res.approved.includes(focusId)) go(null, { replace: true })
      },
    })
  }

  // Keyboard (I21).
  const searchRef = useRef<HTMLInputElement | null>(null)
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const t = e.target as HTMLElement | null
      if (t && (["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName) || t.isContentEditable)) return
      if (e.metaKey || e.ctrlKey || e.altKey) return
      if (e.key === "/") { e.preventDefault(); searchRef.current?.focus(); return }
      if (e.key === "Escape" && phone && itemId) { e.preventDefault(); go(null, { replace: false }); return }
      const at = focusId ? openIds.indexOf(focusId) : -1
      if (e.key === "j" || e.key === "n" || e.key === "N") { const n = openIds[at + 1]; if (n) { e.preventDefault(); go(n) } }
      if (e.key === "k") { const p = openIds[at - 1]; if (p) { e.preventDefault(); go(p) } }
      if ((e.key === "a" || e.key === "A") && view && !view.integrity && view.status === "open") { e.preventDefault(); decideFocused() }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  })

  const pos = positionOf(openIds, focusId)
  const panelProps = view && markState ? {
    view,
    images: { cropUrl: images.crop.url, onCropError: images.crop.onDecodeError, pageUrl: images.page.url, onPageError: images.page.onDecodeError, pageRequested: images.pageRequested, requestPage: images.requestPage },
    nav: { pos: pos.pos, total: pos.total, onPrev: () => go(openIds[pos.pos - 2] ?? null), onNext: () => go(openIds[pos.pos] ?? null) },
    marking: view.status === "open" ? {
      state: markState,
      onChange: (s: MarkState) => setMark({ id: view.key, state: s, note }),
      note,
      onNote: (n: string) => setMark({ id: view.key, state: markState, note: n }),
      onAccept: decideFocused,
      onDismiss: (n: string) => { setMark({ id: view.key, state: markState, note: n }); decideFocused() },
    } : null,
    showShortcuts: true,
  } : null

  const detailError = detail.isError ? (
    <div role="alert" className="grid justify-items-start gap-2.5 py-7">
      <h2 className="text-[24px] font-extrabold tracking-[-0.02em]">Couldn't load this answer.</h2>
      <p className="text-on-surface-variant">{teacherLoadFailureMessage(detail.error)}</p>
      <div className="flex gap-2">
        <button type="button" onClick={() => void detail.refetch()} className="rounded-[14px] bg-primary px-[18px] py-[11px] text-[14px] font-bold text-on-primary">Try again</button>
        <button type="button" onClick={() => go(null, { replace: false })} className="rounded-[14px] bg-surface-container-lowest px-[18px] py-[11px] text-[14px] font-bold shadow-[inset_0_0_0_1.5px_var(--color-outline)]">Back to queue</button>
      </div>
    </div>
  ) : null

  // Phone answer page.
  if (phone && itemId) {
    return (
      <>
        {detailError ?? (panelProps ? <AnswerPage {...panelProps} onBack={() => go(null, { replace: false })} /> : <div className="lm-rq-skel m-4 h-[60vh] rounded-[18px] bg-surface-container-high" aria-label="Loading the answer" />)}
        <UndoBar notice={decisions.state.notice} onUndo={decisions.undo} onClose={decisions.clearNotice} />
      </>
    )
  }

  const cleared = state === "cleared"
  const column = (
    <QueueColumn
      state={state}
      items={rows}
      hiddenIds={hidden}
      focusId={focusId}
      left={total}
      done={decisions.state.tally.decided}
      filters={filters}
      options={options}
      shownLine={filtersActive(filters) && total > 0 ? shownLine(open.length, total) : null}
      selecting={selecting}
      picked={picked}
      bulk={bulkButton({ selecting, picked: picked.size, clearCount: clearIds.length, pending: bulk.isPending })}
      bulkSkips={skips}
      bulkError={bulk.isError ? teacherMutationFailureMessage(bulk.error) : null}
      hasMore={!!queue.data?.nextCursor}
      loadingMore={queue.isFetching && !!cursor}
      errorMessage={queue.error ? teacherLoadFailureMessage(queue.error) : "Check your connection and try again."}
      phone={phone}
      markHref={MARK_HREF}
      searchRef={searchRef}
      onOpen={(id) => go(id, { replace: !phone })}
      onPick={(id) => setPicked((p) => { const n = new Set(p); n.has(id) ? n.delete(id) : n.add(id); return n })}
      onToggleSelect={() => { setSelecting((s) => !s); setPicked(new Set()) }}
      onBulk={runBulk}
      onDismissSkips={() => setSkips(null)}
      onFilters={setFilters}
      onLoadMore={() => setCursor(queue.data?.nextCursor ?? undefined)}
      onRetry={() => void queue.refetch()}
    />
  )

  return (
    <div className="-mx-3.5 grid min-h-[calc(100dvh-56px)] min-w-0 grid-cols-1 shell-sm:grid-cols-[minmax(300px,360px)_minmax(0,1fr)] shell-lg:-mx-[72px] shell-lg:grid-cols-[minmax(340px,400px)_minmax(0,1fr)]">
      {cleared ? (
        <div className="col-span-full grid place-items-center"><Cleared tally={decisions.state.tally} markHref={MARK_HREF} /></div>
      ) : (
        <>
          {column}
          {phone ? null : (
            <div className="sticky top-0 grid max-h-[100dvh] content-start self-start overflow-auto px-6 py-5 [scrollbar-width:thin] shell-lg:px-9 shell-lg:py-6">
              {state === "loading" ? <div className="lm-rq-skel h-[min(420px,60vh)] rounded-[18px] bg-surface-container-high" /> : null}
              {state !== "loading" && state !== "error" ? (detailError ?? (panelProps ? <AnswerPanel {...panelProps} /> : null)) : null}
            </div>
          )}
        </>
      )}
      <UndoBar notice={decisions.state.notice} onUndo={decisions.undo} onClose={decisions.clearNotice} />
    </div>
  )
}
```

Import `Cleared` from `./QueueStates`. On phone the cleared state also renders through this branch.

Notes for the designer:
- The negative margins `-mx-3.5` and `shell-lg:-mx-[72px]` cancel `PortalShell`'s `<main>` padding (`px-[72px]`, `max-shell-lg:px-3.5`), so the column is flush like the mock. Check them against the shell and adjust to the real paddings.
- The `useState` declarations for `selecting` and `picked` must come before `setFilters` in the final file. The order above is for reading only. Reorder so hooks are declared first.
- Keep the keyboard effect dependency-free: it re-binds each render on purpose, so its closure is never stale.
- The focused row scrolls into view on change: `document.querySelector(`[data-review-row="${focusId}"]`)?.scrollIntoView({ block: "nearest" })` in an effect keyed on `focusId`.

- [ ] **Step 3: Wire the routes** (`web/src/portals/teacher/index.tsx`)

Replace lines 62–63:
```tsx
const ReviewQueue = lazy(() => import("./screens/review/ReviewQueue").then((m) => ({ default: m.ReviewQueue })))
```
Route entries:
```tsx
    {
      path: "review",
      element: <ReviewQueue />,
      handle: { title: "Review queue", skeleton: "list" },
    },
    {
      path: "review/:itemId",
      element: <ReviewQueue />,
      handle: { title: "Review a mark", skeleton: "list", immersive: true },
    },
```

- [ ] **Step 4: Typecheck, lint and run every touched unit test**

Run: `cd web && npx tsc -b --noEmit && npx oxlint src/portals/teacher && npm run check:native && npm run check:copy && npx vitest run tests/unit/review*.test.ts tests/unit/navigation.test.ts tests/unit/screenKey.test.ts tests/unit/scrollRestorationKey.test.ts tests/unit/historyPaths.test.ts tests/unit/backgroundLocation.test.ts`
Expected: PASS. Any source-scanning test that names `Review.tsx` or `ReviewItem.tsx` still passes because the files exist until Task 13.

- [ ] **Step 5: Manual smoke** (`run` skill or `npm run dev`). Log in as the e2e teacher and check:
- desktop: list plus panel, focus, sort, filter, tick, accept, undo, bulk
- 390px: list, full-screen answer page, back, accept returns to the list

- [ ] **Step 6: Commit**

```bash
git commit -S -m "feat(web): review queue screen on both review routes" -- web/src/portals/teacher/screens/review/ReviewQueue.tsx web/src/portals/teacher/screens/review/UndoBar.tsx web/src/portals/teacher/index.tsx
```

---

## Task 11: Playwright: the happy path and the updated review-item spec

**Files:**
- Create: `web/e2e/review-queue.spec.ts`
- Modify: `web/e2e/teacher-review.spec.ts`

**Interfaces:**
- Consumes: the seed contract (`web/e2e/seed.ts`: `teacher`, `reviewItem.itemId`, `legacyItemId`, `rationaleOnlyItemId`).

- [ ] **Step 1: Write `web/e2e/review-queue.spec.ts`**

```ts
import { test, expect, type Page } from "@playwright/test"
import { watchConsole } from "./console-errors"
import { readSeed } from "./seed"

async function login(page: Page) {
  const { teacher } = readSeed()
  await page.goto("/login")
  await page.getByLabel("Email").fill(teacher.email)
  await page.getByLabel("Password").fill(teacher.password)
  await page.getByRole("button", { name: /sign in/i }).click()
  await expect(page).toHaveURL(/\/teacher$/, { timeout: 15_000 })
}

test("a teacher sorts, opens, re-marks, undoes and accepts an answer", async ({ page }, info) => {
  test.skip(info.project.name !== "chromium", "desktop layout")
  const errors = watchConsole(page)
  const { reviewItem } = readSeed()
  await login(page)

  // The decision is intercepted: the seeded rows stay open for every other spec.
  const posts: string[] = []
  await page.route("**/api/teacher/review/*/resolve", async (route) => {
    posts.push(route.request().url())
    const id = route.request().url().split("/").at(-2)
    await route.fulfill({ json: { itemId: id, status: "resolved", studentId: null, classId: null } })
  })

  await page.goto("/teacher/review")
  await expect(page.getByRole("heading", { level: 1 })).toContainText("left")
  await page.getByRole("button", { name: "Marks lost" }).click()
  await page.getByRole("menuitemradio", { name: "Confidence" }).click()
  await expect(page).toHaveURL(/sort=confidence/)

  await page.locator(`[data-review-row="${reviewItem.itemId}"]`).click()
  await expect(page).toHaveURL(new RegExp(`/teacher/review/${reviewItem.itemId}`))
  const panel = page.getByRole("article")
  await expect(panel.getByRole("group", { name: "Marking points" }).getByTestId("marker-verdict-row")).toHaveCount(3)

  // Untick an awarded point: the action turns into Save.
  const awarded = panel.getByTestId("marker-verdict-row").and(page.locator('[aria-pressed="true"]')).first()
  await awarded.click()
  await expect(panel.getByRole("button", { name: /^Save \d+\/\d+$/ })).toBeVisible()
  await expect(panel.getByText(/−1 from Lemely/)).toBeVisible()

  // Decide, then undo inside the window: nothing is sent.
  await panel.getByRole("button", { name: /^Save/ }).click()
  await expect(page.locator(`[data-review-row="${reviewItem.itemId}"]`)).toHaveAttribute("data-gone", "")
  await page.getByRole("button", { name: "Undo" }).click()
  await expect(page.locator(`[data-review-row="${reviewItem.itemId}"]`)).not.toHaveAttribute("data-gone", "")
  expect(posts).toEqual([])

  // Decide again and let the window pass: exactly one POST.
  await page.locator(`[data-review-row="${reviewItem.itemId}"]`).click()
  await page.getByRole("article").getByRole("button", { name: /^(Accept|Save)/ }).click()
  await expect.poll(() => posts.length, { timeout: 8_000 }).toBe(1)

  expect(errors, JSON.stringify(errors, null, 2)).toEqual([])
})

test("on a phone an answer opens full screen and Queue goes back", async ({ page }, info) => {
  test.skip(info.project.name !== "iphone-15", "phone layout")
  const { reviewItem } = readSeed()
  await login(page)
  await page.goto("/teacher/review")
  await page.locator(`[data-review-row="${reviewItem.itemId}"]`).click()
  await expect(page.getByRole("button", { name: "Back to the queue" })).toBeVisible()
  await expect(page.getByRole("region", { name: "Review queue" })).toHaveCount(0)
  await page.getByRole("button", { name: "Back to the queue" }).click()
  await expect(page).toHaveURL(/\/teacher\/review(\?|$)/)
})

test("filters live in the URL and Clear filters resets them", async ({ page }, info) => {
  test.skip(info.project.name !== "chromium", "desktop layout")
  await login(page)
  await page.goto("/teacher/review?q=zzzz-no-such-student")
  await expect(page.getByText("No answers match these filters.")).toBeVisible()
  await page.getByRole("button", { name: "Clear filters" }).click()
  await expect(page).not.toHaveURL(/q=/)
})
```

- [ ] **Step 2: Update `web/e2e/teacher-review.spec.ts`** to the new DOM, keeping every test's intent:
- Test 1 (verdicts):
  - replace `getByRole("region", { name: "Marker's per-point verdicts" })` with `page.getByRole("article").getByRole("group", { name: "Marking points" })`
  - keep `getByTestId("marker-verdict-row")` with count 3
  - the labels become: the awarded point is `[aria-pressed="true"]`, `getByText("Judged absent")` and `getByText("Couldn't confirm")`
  - the evidence assertion becomes `getByText("“a = (v - u) / t = (20 - 0) / 4 = 5 m/s^2”")`
  - the ECF chip becomes `getByText("Carried forward")`
- Test 2 (legacy): assert `getByTestId("point-note")` has count 0, and that `Judged absent` and `Couldn't confirm` each have count 0.
- Test 3 (rationale-only): assert `getByTestId("point-note")` is visible and contains the seeded rationale text the old test asserted.
- Boxless test:
  - keep `watchCropRequests`, still expecting `[]`
  - assert `getByRole("tab", { name: "Whole page" })` has count 0
  - assert the transcription caption "Lemely's reading of the answer" is visible
- Box-bearing test:
  - keep the `naturalWidth` poll on `getByAltText(SCAN_CROP_ALT)` (the alt text is unchanged)
  - replace the banner text assertion with `getByText("From the student's scan")`
  - keep `cropRequests` at length 1
  - then click the "Whole page" tab, poll `getByAltText("The whole page this answer is on")` `naturalWidth > 0`, and assert exactly one `/page` request via a second watcher on `/review/${itemId}/page`
- Crop 404 test: absence now means the transcription card ("Lemely's reading of the answer") is visible and no `img` with `SCAN_CROP_ALT` exists.
- Navigation test: replace the "Next item" control with `getByRole("button", { name: "Next answer" })`. Keep the browser back step. On desktop the panel navigation uses `replace`, so change the back step to `getByRole("button", { name: "Previous answer" })` and say so in the test comment.
- Every `page.goto('/teacher/review/<id>')` stays: deep links are preserved (I24).

- [ ] **Step 3: Run the specs**

Run: `cd web && npx playwright test e2e/review-queue.spec.ts e2e/teacher-review.spec.ts`
Expected: PASS on `chromium` and `iphone-15`; tests that don't apply are skipped by project.

- [ ] **Step 4: Commit**

```bash
git commit -S -m "test(e2e): review queue happy path and updated review item coverage" -- web/e2e/review-queue.spec.ts web/e2e/teacher-review.spec.ts
```

---

## Task 12: Fidelity screenshots, drift fixes, polish

**Agent:** `designer` (impeccable).

**Files:**
- Create: screenshots under `.omc/artifacts/l5-fidelity/` (not committed)
- Modify: `review/*.tsx` and `review.css` for drift fixes only

- [ ] **Step 1: Serve the mock.** Run `cd .impeccable/mocks && python3 -m http.server 8765`. Open `http://127.0.0.1:8765/review-r1/final2.html` and `http://127.0.0.1:8765/states-r1/index.html`.
- [ ] **Step 2: Capture pairs at 390×844 and 1280×800** (Playwright `page.screenshot`):
- the queue with a row focused
- select mode
- the filter menu at both steps
- the sort menu open
- no-match
- loading (add `?` plus a throttled network, or `page.route` delaying `/teacher/review`)
- error (`page.route` returning 500)
- the undo toast
- queue clear
- phone answer page
- the Whole page view
- first run (RQ1/RQ3: a fresh teacher account, or `page.route` returning `{items:[], total:0, hasHistory:false, subjectCodes:[]}`)
- sparse (RQ2: route one item)

Also capture 820×1180 (tablet) for the queue and the panel.
- [ ] **Step 3: Fix the drift** you see: spacing, sizes, colours, type, motion. Record each small fix for the PR's "Changes from the mock" list. Layout, flow or content changes are not allowed here; add them to Needs user decision instead.
- [ ] **Step 4: Run `/impeccable polish`** on `web/src/portals/teacher/screens/review/`. Check contrast (the ring text on `surface-container-low`, gold `tertiary` against white), 44px tap targets, no text under 12px apart from the mock's 10.5/11px mono labels (keep them; they match the approved mock and are uppercase tracked), focus rings and reduced motion.
- [ ] **Step 5: Re-run the unit and e2e checks from Tasks 8–11.** Commit the fixes:

```bash
git commit -S -m "fix(web): review queue fidelity drift and polish" -- web/src/portals/teacher/screens/review
```

---

## Task 13: Keep-list check and deleting the old code

**Files:**
- Delete: `web/src/portals/teacher/screens/Review.tsx`, `web/src/portals/teacher/screens/ReviewItem.tsx`
- Modify the source-scanning tests that name the old files:
  - `web/tests/unit/rtlSafety.test.ts:71-72` and `web/tests/unit/utilityExistence.test.ts:121-122`: replace both entries with `src/portals/teacher/screens/review/ReviewQueue.tsx`, `review/AnswerPanel.tsx`, `review/QueueColumn.tsx` and `review/MarkControls.tsx`
  - `web/tests/unit/sectionHead.test.ts:23`: remove the `Review.tsx` entry from `MIGRATED_SCREENS`; the new screen has no `SectionHead`
  - `web/tests/unit/tableOrList.test.ts:46`: remove `"portals/teacher/screens/Review.tsx"` from the "Review and ClassRoster use it" list and rename the test to "ClassRoster uses it"
  - `web/tests/unit/selfReviewTeacherWiring.test.ts:56-75`: retarget the `ReviewItem.tsx` describe block to `review/answerView.ts`, asserting it reads `p.studentSelfmark`, `p.studentEvidence` and `p.evidenceVerdict`
  - `web/tests/unit/reviewItemMarkerVerdicts.test.ts:29`: retarget it to `review/MarkControls.tsx` plus `review/markModel.ts`. Keep the `cropUrlFor` suite unchanged. Replace the `MarkerVerdicts` guard assertions with assertions that `markPointsFrom` maps `verdict`, `evidenceSpan`, `ecfApplied` and `rationale`, and that `MarkControls` renders `data-testid="marker-verdict-row"` inside `points.map`
  - `web/src/components/ui/confidence-indicator.tsx:31`: comment only; point it at `review/QueueRow.tsx`
  - `web/tests/unit/reviewBadge.test.ts`, `navigation.test.ts`, `screenKey.test.ts`, `scrollRestorationKey.test.ts`, `historyPaths.test.ts`, `backgroundLocation.test.ts`, `web/src/lib/nav/scrollRestorationKey.ts`, `web/src/lib/meta/documentMeta.ts` and `web/src/portals/teacher/data.ts`: grep for `Review.tsx`, `ReviewItem` and `/teacher/review`. Update only references to the deleted files; routes and breadcrumbs keep working unchanged.
  - `web/e2e/paper-deletion.spec.ts`: run it; if it selects old Review DOM, update its selectors to the new row (`[data-review-row]`)

- [ ] **Step 1:** Grep for every importer: `grep -rn "screens/Review\b\|screens/ReviewItem\|from \"./Review\"" web/src web/tests web/e2e` (with `TOKENSAVE_DISABLE_GREP_HOOK=1`, since these are file paths, not symbols). Fix each one as listed above.
- [ ] **Step 2:** Delete the two files. Run `cd web && npx tsc -b --noEmit && npx vitest run tests/unit/rtlSafety.test.ts tests/unit/utilityExistence.test.ts tests/unit/sectionHead.test.ts tests/unit/tableOrList.test.ts tests/unit/selfReviewTeacherWiring.test.ts tests/unit/reviewItemMarkerVerdicts.test.ts tests/unit/reviewBadge.test.ts tests/unit/navigation.test.ts tests/unit/screenKey.test.ts tests/unit/scrollRestorationKey.test.ts tests/unit/historyPaths.test.ts tests/unit/backgroundLocation.test.ts && npm run check:native && npm run check:copy && npx playwright test e2e/teacher-review.spec.ts e2e/review-queue.spec.ts e2e/paper-deletion.spec.ts`
- [ ] **Step 3:** Walk the keep-list (K1–K22, I1–I24, B1–B9). For each item, name the file and line in the new code, or the test that proves it, and paste the ticked list into the PR body. An unticked item is a blocker: implement it, or move it to Needs user decision with the user's answer.
- [ ] **Step 4:** Scan the changed files for placeholders: `grep -rn "TODO\|FIXME\|test.skip\|\.only(" web/src/portals/teacher/screens/review web/e2e/review-queue.spec.ts`. The only allowed `test.skip` calls are the per-project ones in `review-queue.spec.ts`.
- [ ] **Step 5:** Run `graphify update .`
- [ ] **Step 6: Commit**

```bash
git rm web/src/portals/teacher/screens/Review.tsx web/src/portals/teacher/screens/ReviewItem.tsx
git commit -S -m "refactor(web): remove the old review queue and review item screens" -- web/src/portals/teacher/screens/Review.tsx web/src/portals/teacher/screens/ReviewItem.tsx web/tests/unit web/src/components/ui/confidence-indicator.tsx web/e2e/paper-deletion.spec.ts
```

---

## Task 14: Gate sweep, push and PR

- [ ] **Step 1:** Rebase on `develop`: `git fetch origin && git rebase origin/develop`. Resolve shared-file conflicts with the master plan's rules: in `portals/teacher/index.tsx`, keep only this lane's two route entries.
- [ ] **Step 2: Gate sweep last.** It must run on the final tree, after every fix commit. Derive the list from `.github/workflows/ci.yml`. Run each listed check on the touched files only:
  - pytest: `tests/test_web_review.py tests/test_review_repo.py tests/test_scan_render.py tests/test_teacher_review_total.py`
  - ruff and mypy via `PYTHONPATH=$PWD pre-commit run --files <every touched file>`
  - web: `npx tsc -b --noEmit`, `npx oxlint`, `npm run check:native`, `npm run check:copy`, `npx vitest run` on every unit test touched or named above, and the Playwright specs from Task 13
  - any repo lint test that scans `lemely/` or `web/src` (`tests/test_*lint*`)
- [ ] **Step 3:** Push and open the PR to `develop` (never `main`):

```bash
git push -u origin redesign/l05-review-queue
gh pr create --base develop --title "feat: redesigned teacher review queue (L5)" --body-file .omc/artifacts/l5-pr-body.md
```
The PR body contains:
- the keep-list, ticked
- the frame-to-state table
- "Changes from the mock" (the small fixes from Task 12)
- the Needs user decision answers
- the 390 and 1280 screenshot pairs
- the run commands and their results

---

## Needs user decision

Each item has a recommendation. Work proceeds on the recommendation unless the user says otherwise.

1. **The 70% "clear" band.** The mock colours the ring red under 70% and gold from 70%, and "Approve clear" takes the gold ones. The codebase deliberately has only one confidence threshold (0.90, `lib/markingConfidence.ts`), and every queue row is below it. **Recommendation:** adopt `CLEAR_CONFIDENCE = 0.7` as a named product band, used only for the ring colour and the clear set, as approved in the mock.
2. **Gold for a confidence ring.** This conflicts with the rule "gold only for earned things". **Recommendation:** keep it. You approved it in the review-queue mock.
3. **Dismiss on low-confidence answers.** The mock shows "Dismiss…" on every answer, but the backend rejects dismissing anything that isn't an integrity flag (422). **Recommendation:** integrity flags get "Dismiss flag" only; every other answer gets Accept/Save only.
4. **Undo.** The backend has no reopen. **Recommendation:** delay the commit by 5s, matching the mock's toast. It flushes immediately on the next decision, on leaving the page, or on closing the tab (keepalive). No new endpoint.
5. **"Note to student".** On accept-as-is, the backend stores the note internally, not for the student. **Recommendation:** the placeholder reads "Note for your records" until the mark changes, then "Note to student".
6. **Breakdown inputs.** The live adjust form has method, accuracy and other fields, plus "breakdown notes". **Recommendation:** derive method/accuracy/other from the ticked points' M/A/B codes, and drop the free-text breakdown notes.
7. **The "why" line.** The mock's specific phrases ("Unit missing", "Sign error in constant") would need new marker output. **Recommendation:** map today's reason data to short plain lines ("Lemely wasn't sure", "Final answer not confirmed", "Hard to read", …). Richer reasons can come later as pipeline work.
8. **"Mark scheme wording".** Full scheme prose is not stored anywhere. **Recommendation:** the disclosure shows the scheme's expected answer and the topic, and is hidden when both are absent. Point wording already appears on each tick row.
9. **Default sort.** The live queue sorts oldest first; the mock opens on "Marks lost". **Recommendation:** default to Marks lost. Oldest stays one tap away.
10. **Dropped row details.** The table/list toggle, avatars and the per-row waiting time go. **Recommendation:** drop them. Waiting time is still reachable via the Oldest sort and the "Waiting" filter.
11. **Keyboard hint.** The live screen had a visible shortcut strip; the mock has only "/". **Recommendation:** one quiet mono line under the actions, shown at 1248px and up only.
12. **"See a sample answer".** RQ1's link has nothing behind it. **Recommendation:** drop it.
13. **Binny on "Queue clear." and "Nothing to review."** The mock shows Binny only on first run. **Recommendation:** add the small head-crop Binny to those two calm states too, at most once per screen.
14. **Phone, after deciding.** The mock returns to the list; the live screen opened the next answer. **Recommendation:** follow the mock. The teacher sees the row collapse and the Undo toast.
15. **"Mark papers" / "Mark another class set" destination.** **Recommendation:** `/teacher/grading` for now, switched once L6 or L8 settle where a class set is uploaded.

---

## Self-review

- **Spec coverage** (spec "5. Teacher review queue"):
  - sort: Tasks 2, 5 and 8
  - M3 filters: Tasks 2, 4, 5 and 8
  - Approve clear and Tap-Select: Tasks 5, 8 and 10
  - collapse with undo: Tasks 7, 8 and 10
  - big ring: Task 8 (KeyRing)
  - tick stepper with either/or limits: Tasks 1, 6 and 9
  - prev/next, Answer/Whole page, self-review, scheme wording: Tasks 7 and 9
  - Queue clear: Tasks 8 and 10
  - phone full-screen: Tasks 9 and 10
  - whole-page endpoint: Task 3
  - sort and filter params: Task 2
  - first-run and sparse states (`design-empty-sparse-states`): Task 8
  - L8 export: Task 9 (`review/index.ts`)
- **Placeholder scan:** none. The only deferral is `MARK_HREF`, an explicit constant with a decision item (#15).
- **Type consistency:**
  - `ReviewQueueFilters`/`filtersFromSearch`/`filtersToSearch` are used the same way in Tasks 4, 5, 8 and 10
  - `MarkState`/`MarkPoint` are the same in Tasks 6, 7 and 9
  - `ReviewDecision` is the same in Tasks 4, 7 and 10
  - `DecisionNotice` is the same in Tasks 7 and 10
  - `AnswerView` is the same in Tasks 7 and 9
  - `useReviewItemImage(id, kind, enabled)` is the same in Tasks 4 and 7
