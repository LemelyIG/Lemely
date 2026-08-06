# BUILD STATE — single source of truth

status: RUNNING            # RUNNING | COMPLETE | HALTED
current_phase: 3
last_updated: 2026-08-06T00:00:00Z
gemini_spend_usd: 0.0580

## Rules for maintaining this file
- Update BEFORE starting and AFTER finishing every task. Assume sudden death.
- Keep exactly one task `doing` at a time.
- When all Phase-6 acceptance criteria pass and DELIVERY.md is committed,
  set `status: COMPLETE` — the supervisor stops on this value.
- Prune a phase's detail to a single summary line once its `reports/phase-N/REPORT.md`
  is committed and merged to develop (MISSION §8b) — full rationale lives in
  `BUILD/DECISIONS.md` and the phase report, not here.

## Phase 0 — Foundation repair — DONE (2026-07-30)
All 8 tasks complete: CI green (ruff/web), `lemely/io/det/` wired + monolith deleted (D0.5),
persistent Gemini cost ledger ($8 cap, D0.6), HistoryStore corruption surfaced, single lockfile,
`lemely doctor` real reachability. 395 passed / 84.56% cov. Merged to develop.
Report: `reports/phase-0/REPORT.md`. PR #3 (rolling develop→main, NOT merged).

## Phase 1 — Database + Auth + Tenancy — DONE (2026-08-01)
Local Supabase stack, 22-table schema (additive-only, D1.2/D1.3), GoTrue auth + backend-issued
HS256 JWTs (D1.4/D1.5), RBAC on every route + both IDORs killed (D1.6), HistoryStore→Postgres
for the web surface (D1.8/D1.9 — CLI/Gradio kept on JSON store), seat model (D1.10), 3-device
session registry (D1.11). Adversarial review: no Critical/High bypass (D1.12). 548 passed /
85.44% cov. Merged to develop. Report: `reports/phase-1/REPORT.md`.

### Carried backlog from Phase 1 (non-blocking, do opportunistically)
- [ ] todo — (D1.9) Migrate CLI + Gradio history to the DB (or retire Gradio), then delete
      `lemely/io/history_store.py` + `tests/test_history_store.py`. Parity already proven.
- [ ] todo — (D1.6) Teacher per-tenant ownership (own-classes-only) — lands with the Phase 3
      class model; role boundary is already enforced, row-level ownership is not yet.

## Phase 2 — The core loop, real and end-to-end — DONE (2026-08-05)
Real SSE correction pipeline (P2.1), grade-boundary ingestion from cambridgeinternational.org
(P2.2, D2.1), accuracy harness + 10 golden fixtures across 0580/0606/0625 (P2.3), plagiarism/
AI-detection advisory flags (P2.4), Supabase Storage upload path (P2.5, D2.6), frontend
resurrected from dead code + auth/session foundation (P2.6), student + teacher surfaces wired
to real data (P2.7/P2.8), PWA foundation + camera capture (P2.9), Playwright E2E acceptance
verified against the live Supabase stack with an independent Postgres persistence check
(P2.10). 609 passed / 3 skipped (live-only) / 86.38% cov. Merged to develop (6254879), pushed.
PR #3 updated (title "Phases 0–2", body extended), NOT merged. ntfy sent.
Report: `reports/phase-2/REPORT.md`. Gemini cumulative spend $0.058/$8.00.

### Honest limitations carried forward from Phase 2 (must appear in DELIVERY.md, not silently resolved)
- **Accuracy gate NOT met (D2.5):** mark-level agreement 83.8% vs ≥95% target; flag_recall
  27.3% vs the 100%-disagreements-flagged target. Threshold tuning (D2.2/D2.3) and
  deterministic calculated-answer verification (D2.4) are both exhausted; the remaining gap
  is free-form algebraic method-verification — materially harder, out of scope so far.
- **PWA Lighthouse + camera-capture** not live-tested (no Chromium/camera in this sandbox,
  P2.9) — verified by inspection/manual trace only; see `reports/phase-2/pwa-limitations.md`.
  Needs a real-device/browser pass before claiming a hard pass.

## Phase 2.5 — Design system + frontend quality foundation — DONE (2026-08-05)
Token layer sourced from DESIGN.md (P2.5.1), C-1..C-13 component library + catalogue
(P2.5.2), Phase-2 screen retrofit onto tokens/components (P2.5.3), Impeccable audit+polish
(P2.5.4, D2.11), Playwright screenshot corpus (P2.5.5, D2.12), Puppeteer axe/Lighthouse
audit runner (P2.5.6), `scripts/check.sh` created from scratch — a Phase-0 mandate that had
never actually existed — plus a real CI-breaking `ruff`/`.claude` exclusion bug fixed along
the way (P2.5.7, D2.13), full QUALITY-BAR.md pass to zero serious/critical axe violations +
Lighthouse a11y 100 across all 4 in-scope routes (P2.5.8, D2.14). 609 passed / 85.54% cov
(zero backend files touched this phase; coverage delta from Phase 2 is environmental
live-test-skip variance, not a regression — see report §4). Merged to develop (fcc3e07),
pushed. PR #3 updated (title "Phases 0–2.5"), NOT merged. ntfy sent.
Report: `reports/phase-2.5/REPORT.md`. Gemini cumulative spend $0.058/$8.00 (unchanged —
pure frontend/tooling phase, zero LLM calls).
Decisions: D2.10–D2.14. Deferred/flagged component-library gaps for a future pass: see
report §8 (sub-44px touch target, non-heading empty/error tags, no mobile BottomNav, raw
`max-[1180px]:` literals outside the retrofitted screens, momentum-chart/TrendSparkline
duplication blocked on a DTO change).

## Phase 3 — Teacher + Parent surfaces — IN PROGRESS
Branch: `feature/phase-3-teacher-parent` (from develop @ faef29c).

Starting facts (established 2026-08-06, do not re-derive):
- Tables already exist from Phase 1: `classes`, `class_enrollments`, `parent_child_links`,
  `review_queue`, `announcements`, `notifications`, `seats`, `school_memberships`.
  Phase 3 builds the *routes + screens* on top; schema changes are additive-only (D1.2/D1.3).
- ~~`GET /teacher/classes` / `GET /classes/{id}` derive an implicit class from history~~ —
  **done in P3.1**; they now serve the real class model from `lemely/web/routers/classes.py`
  via `ClassService`. Other teacher routes still in `lemely/web/routers/teacher.py` (~1100
  LOC): papers upload/extract/grade/list/detail, grading/queue, schemes, quizzes
  pools/topics/preview/generate, teacher/overview.
- Reusable seams P3.3+ should build on rather than re-derive: `ClassService.roster()` for
  "which students am I allowed to see", `lemely.core.at_risk.assess_at_risk()` for at-risk,
  `lemely.core.at_risk.GRADE_ORDER` for the ladder, and `teacher.py`'s `_mean`/`_student_row`/
  `_student_delta`/`_AT_RISK_GRADES` helpers.
- The UI gates write to gitignored `reports/.scratch` (D3.2). Never commit anything under
  `reports/phase-2/` or `reports/phase-2.5/`; re-baseline explicitly with `LEMELY_REPORT_DIR`.
- **Test-count numbers in the P3.1–P3.4b lines above are undercounts — ignore them, do not try
  to reconcile.** `pytest -q` in this repo emits no `N passed` summary line (a reporter plugin
  eats it), so earlier sessions guessed. Real counts come from the progress characters:
  `pytest -q --tb=short > /tmp/p.log` then count `.`/`s`/`F` in the `^[.sFEx]+ +\[ NN%\]` lines.
  Measured at chunk A: **1485 tests, 1481 passed, 4 skipped (live-only), 0 failed, 87.46% cov.**
- Both P3.1 and P3.2 subagents stalled waiting on background runs instead of reporting.
  Brief future agents to run `./scripts/check.sh` in the **foreground**, and verify their
  work yourself regardless (MISSION §5).
- Frontend teacher portal screens exist (Overview, Classes, Grading, MarkSchemes, Quizzes,
  Review) under `web/src/portals/teacher/`; hooks in `web/src/lib/hooks/useTeacherApi.ts`.
  No parent portal exists at all.
- Parent phone-OTP auth backend exists from P1.4 (`/auth/otp/request`, `/auth/otp/verify`).
- T-11 (custom paper + mark-scheme upload) is scoped by MISSION §9 to be delivered *via
  review/override + teacher quiz marking*, not as a standalone upload screen.

### Task checklist
- [x] done — **P3.1** Real class model + teacher tenancy (D3.1). `lemely/db/class_repo.py`
      (`ClassService`, modelled on `SeatService`), migration `0004_class_model` (nullable
      `classes.school_id` for independent teachers + `classes.join_code`), new
      `lemely/web/routers/classes.py` (CRUD/roster/enrol) + student join-by-code on the
      student router. The implicit "all students are one cohort" endpoints are gone — the
      cross-tenant leak D1.6 recorded as outstanding is closed. 687 tests (683 passed / 4
      skipped live-only) / 85.76% cov (up from develop's 85.54%). All 12 gates green;
      `alembic check` reports no drift.
- [x] done — **P3.1b** Fixed the self-defeating visual baseline gate (D3.2). All four
      runners (`audit.mjs`, both Playwright specs, `check_ui_gates.py`) hardcoded a
      committed phase report dir, so every `./scripts/check.sh` run overwrote the
      baselines the "no unintended visual regression" gate compares against — making
      that gate vacuous. Now behind `LEMELY_REPORT_DIR`, defaulting to gitignored
      `reports/.scratch`; re-baselining is explicit and names its phase. Verified: 12/12
      gates green with a clean tree afterwards.
- [x] done — **P3.2** At-risk flagging engine (D3.3). `lemely/core/at_risk.py` — pure, no I/O,
      injected clock; three rules OR'd (declining trend N=3 with a 5pp floor / predicted ≥2
      grades below target / ≥14 days inactive), each flag carrying reason + evidence.
      `GRADE_ORDER` now defined once in core and aliased by the web layer. Replaced the old
      "grade in {D,E,U} or any negative delta" heuristic on `/api/teacher/overview` and made
      `/api/classes/{id}`'s "At risk" card mean the same thing (they had diverged).
      **Honest limitation:** rule 2 is fully implemented and unit-tested but cannot fire in
      production — no target-grade column exists until P4's onboarding questionnaire; the
      engine reports it as *not evaluable*, never as a pass. 711 tests (707 passed / 4
      live-only skips), at_risk.py at 100% cov, total 86.11%. All 12 gates green.
- [x] done — **P3.3** Teacher analytics (D3.4). `lemely/core/class_analytics.py` (pure,
      injected clock): ranked topic weaknesses, topic×student heatmap, grade distribution,
      cohort trend, per-paper comparison, engagement stats. Three read-only routes —
      `GET /api/classes/{id}/analytics` (T-04), `GET /api/teacher/students/{id}` (T-05),
      `GET /api/teacher/at-risk` (T-06, `?reason=` filter) — all scoped through one
      `_visible_students()` helper delegating to `ClassService`. **Closed the last
      cross-tenant leak:** `/api/teacher/overview` was still enumerating
      `history_store.list_students()` (every student in the store) and naming at-risk rows
      from the raw uuid; now roster-scoped with real display names, pinned by a two-teacher
      disjoint-class regression. Also corrected four docstrings across `classes.py`/
      `teacher.py`/`class_repo.py` that claimed "never a 404-vs-403 existence oracle" while
      implementing exactly that — behaviour kept, false security claim replaced with an
      honest one (D3.4). No migration (`alembic check` clean). 752 passed / 4 skipped
      (live-only) / 87% cov, up from 711 and 86.11%. All 12 gates green.
      Honest gaps: heatmap no-data cells are `None` not 0%; T-05 integrity signals omitted
      (no per-question data persisted); T-06 flag-dismissal deferred to P3.4.
- [x] done — **P3.4** Review queue override-and-annotate (T-07/T-08). Migration 0005 adds
      teacher-override columns to `question_results` without touching the AI's own
      `awarded_marks`; `ReviewService` (`lemely/db/review_repo.py`) serves queue list/filter,
      detail, resolve (accept-or-override with method+accuracy breakdown + note to student),
      integrity-flag dismiss (structurally never writes to a `QuestionResult`, so no
      student-visible record can survive), and bulk-approve — all through the same
      `ClassService` roster tenancy. Routes in `lemely/web/routers/review.py`. Handed item
      (a) fixed in the same commit: `/api/teacher/overview`'s "Need your eyes" now counts the
      caller's own open review items, not the whole global `papers_store`.
      **Follow-up (9159947):** an override recomputed the attempt total but left
      `weakness_records` at the AI's values, so a question a teacher restored still counted
      as "lost" on the student's weakness list and the T-04 heatmap. Now recomputed through
      `analytics.group_weak_areas`, extracted so marking-time and override-time run
      identical topic-bucketing. 794 tests (790 passed / 4 live-only skips) / 87.15% cov.
      All 12 gates green.
- [x] done — **P3.4b** At-risk flag acknowledge-with-a-note (T-06, D3.5) — the second item
      P3.3 handed to P3.4. `at_risk.flag_fingerprint()` (pure) canonicalises the *stable*
      part of each evidence type — notably `last_active_at` only, never `days_inactive`,
      which would un-acknowledge an unresolved flag every 24h. New table
      `at_risk_acknowledgements` (additive migration 0006) unique on
      (teacher, student, reason), served by `AtRiskAckService` (`lemely/db/at_risk_repo.py`,
      bulk load, no N+1). Acks are per-teacher and evidence-scoped, so further decline
      re-raises the flag unacknowledged; acknowledged flags are tagged, never removed
      (`?acknowledged=` is a caller filter). `_at_risk_flag_dto` is the single population
      point across T-01/T-05/T-06. Routes: POST/DELETE
      `/api/teacher/at-risk/{student_id}/acknowledge[/{reason}]`. 826 tests (822 passed /
      4 live-only skips) / 87.18% cov. All 12 gates green, `alembic check` clean.
      Known test-only wart: `_use_class_service` in `tests/test_web_teacher.py` reads
      `class_service._sessionmaker` to auto-wire the ack service for 15+ pre-existing
      tests rather than changing every call site. Documented in the helper's docstring.
- [x] done — **P3.5** Teacher quiz builder backend (T-09/T-10). All eight chunks
      (C, A, G, B, D, E, F1, F2) landed; see each chunk line below for what it built and
      what must not be reintroduced. **Design is DONE and fixed:
      `docs/quiz-model.md` (822 lines) + D3.6. Do not redesign — implement it.** There was no
      quiz persistence of any kind before this; the existing `/quizzes/*` routes build an
      ephemeral preview and save nothing.
      Build in this order (D3.6 / `docs/quiz-model.md` §6), one commit per chunk:
      - [x] **C** done (e1cfa34) — `lemely/core/difficulty.py`, 100% covered, total 87.25%.
            `Band = Literal["foundation","standard","challenge"]` agrees with
            `GeneratedQuestion.difficulty` (pinned by a test). Fallback mix
            `(0.20, 0.60, 0.20)` for `None`/unrecognised grade. `infer_difficulty`:
            multi_step/levels_based/indicative_content → challenge regardless of marks;
            else mcq or marks<=1 → foundation, marks<=3 → standard, else challenge.
            Ties beyond the spec's "toward standard" rule break by fixed priority
            standard > foundation > challenge. Import-time table/GRADE_ORDER check is a
            real `raise`, not an `assert` (`python -O` strips asserts).
      - [x] **A** done — migration `0007_quiz_model` + `lemely/db/models/quizzes.py` (6 tables:
            `question_bank`, `quizzes`, `quiz_questions`, `quiz_assignments`, `quiz_submissions`,
            `quiz_answers`) + 7 new enums + `attempts.origin`. Schema only, zero behaviour —
            nothing reads or writes these tables yet. Additive-only (D1.2/D1.3): `attempts.origin`
            carries `server_default 'past_paper'` so no backfill is needed, proven by a test that
            inserts an Attempt *without* the column and reads the default back.
            Migration creates its 7 enum types explicitly with `checkfirst=True` before any column
            references them and drops them in `downgrade` (autogenerate omits both); `examboard` is
            reused with `create_type=False` since 0002 owns it. Verified against the live stack:
            `alembic upgrade head` → `downgrade -1` → `upgrade head` all clean, `alembic check`
            reports no drift in either direction. `uq_question_bank_paper_question` is a *partial*
            unique index (`WHERE paper_id IS NOT NULL`) so the chunk-B past-paper ingest is
            idempotent while generated/teacher-upload rows (paper_id NULL) never collide — pinned
            by a test that asserts both halves. `QuestionDifficulty` is pinned equal to
            `core.difficulty.Band` and `GeneratedQuestion.difficulty`'s Literal by a
            three-way vocabulary test, so a fourth band cannot be invented on one side only.
            All 12 gates green.
      - [x] **G** done — `PaperRecord.origin` (`PaperOrigin` literal, defaulted `past_paper`) +
            `is_grade_bearing`, wired into all nine `docs/quiz-model.md` §5 consumers, plus
            `HISTORY_SCHEMA_VERSION` 1→2 and `origin` round-tripping through `DbHistoryStore`
            in **both** directions (`_to_attempt` as well as `_to_record` — writing only the
            read side would have let a quiz record load back as a past paper).
            `GRADE_ORDER` moved `at_risk` → `history` so the schema module could reach it
            without importing the rules engine; all four importers repointed, no re-export
            shim (mypy strict rejects implicit re-export anyway). Verified behavioural no-op:
            every pre-existing test green, unchanged.
            **Two real defects found and fixed while wiring, neither in the design doc:**
            (a) `StudentHistory.schema_version` defaults to `HISTORY_SCHEMA_VERSION`, so after
            the bump a *pre-versioning* file (no key) loaded claiming to be v2 — destroying the
            "detect an older file" signal the field exists for. `HistoryStore.load` now feeds
            its already-resolved absent-means-1 version back into `model_validate`.
            (b) `grade_distribution` would have silently changed behaviour today: filtering
            straight on `is_grade_bearing` makes a student whose *latest* paper has a malformed
            grade fall back to their older, likely better grade instead of being skipped.
            Kept as "latest paper, skipped if its grade is unreadable" — no current standing to
            report beats overstating it. 1519 tests (1515 passed / 4 live-only skips), 87.48%
            cov (from 87.46%). All 12 gates green.
            **Prerequisite handed to F — the §5 table only covers `lemely/core/`.** These
            web-layer consumers derive a grade/percentage claim straight off `history.records`
            and are still unfiltered; they are behaviourally fine until the first quiz attempt
            exists and become live corruption the moment F lands, so F must filter them in the
            same commit that starts writing quiz attempts:
            `classes.py:125` (`_average_for`), `classes.py:187`, `teacher.py:1090`,
            `teacher.py:1300-1301` (`predictedGrade`/`latestPercentage`), `teacher.py:1541`
            (at-risk row grade), and `student.py:144-193` (`_momentum`), `:263`, `:280`.
            `analytics.aggregate_weaknesses_from_history` and `classes.py:173` are
            topic-bearing and correctly take all records — do not filter those.
      - [x] **B** done (82cafb9) — `lemely/db/question_bank_repo.py` +
            `lemely question-bank {survey-past-papers,import-generated}`. 1537 tests
            (1533 passed / 4 live-only skips), 87.83% cov (from 87.48%), repo file at 100%.
            All 12 gates green, `alembic check` clean, no schema change.
            **The mandated measurement came back zero, and that is the finding (D3.7).**
            122 leaf questions across the entire 4-mark-scheme corpus, **0 with prompt text,
            0 with a topic hint** — because `loose_schemas.Question` has no question-stem
            field at all: a mark scheme holds marking points, the stem lives in the question
            paper, which this codebase only ever consumes as a scanned student submission.
            `mark_schemes` holds 0 rows and `outputs/questions/` does not exist, so both
            ingest paths yield 0 today. **Do not re-run this measurement or treat it as a
            parsing bug** — corpus growth cannot change it.
            Consequently the past-paper ingest ships as `survey_past_paper_questions()`,
            a reporting function with no write path (an unreachable persist branch would be
            dead code testable only by stubbing a field the schema lacks).
            `uq_question_bank_paper_question` stays — it is what makes the real writer
            idempotent when the stem extractor arrives (P4's natural home, now a
            prerequisite of its "questions from the past-paper corpus" work, not an
            assumption).
            Shipped: `visible_bank_filter` (three tiers; degrades to shared-only, never to
            everything and never to always-false) and `QuestionBankService.count_by_band` /
            `.select_questions` sharing one `_filters()` so §1.3's count-40-build-12
            divergence is structurally excluded; `import_generated_quiz_files` (malformed
            file reported and skipped, never fatal).
            One design-doc correction: §2's "GeneratedQuestion maps field-for-field" cannot
            hold — `GeneratedQuestion` has no `question_type` and the column is NOT NULL. It
            is a documented default (`explanation`), not an inferred type; safe because
            `correction`/`correction_ai` branch only on MCQ vs non-MCQ and generated
            questions are never MCQ.
      - [x] **D** done (d19c32d) — `lemely/db/quiz_repo.py` (`QuizService`),
            `lemely/web/routers/quiz.py` (prefix `/api/teacher/quizzes`),
            `lemely/web/schemas_quiz.py`. 1595 tests (1591 passed / 4 live-only skips),
            88.00% cov (from 87.83%). All 12 gates green, `alembic check` clean, no schema
            change. Quiz CRUD + draft PATCH (row created at step 1, every later field
            nullable), the `draft→assigned→closed→archived` lifecycle with no backwards
            transition and no question edits on a non-draft, `quiz_questions` materialized
            by **copying** text (`question_bank_id` is provenance only, §1.5) with stable
            never-renumbered `question_ref` and removed-not-deleted rows, and
            `GET /api/teacher/quizzes/pool-count` deriving `byBand` from the same
            `allocate_difficulty` the builder uses. All bank reads go through chunk B's
            `visible_bank_filter`/`count_by_band`/`select_questions` — do not add a second
            WHERE clause for the bank in E or F.
            Also added: `ClassService.member_school_ids` (any membership role, for the
            school visibility tier) and `QuestionBankService.has_inferred_difficulty` /
            `generated_questions_to_bank_rows`.
            **Two defects found while wiring, both now pinned by tests — do not
            reintroduce either shape in E/F:** (a) moving only the *write* side off disk
            left `_existing_questions` reading a directory nothing writes, i.e. a reuse
            path that always returned nothing while its docstring claimed a working pool;
            it now reads the bank. (b) That then made `/quizzes/generate` re-insert every
            reused question on each call, inflating the pool count — generated rows have
            no `paper_id`, so `uq_question_bank_paper_question` does not cover them, and
            the write path must filter. `_build_quiz` returns `(quiz, reused_prompts)`.
            Out of scope, deliberately, and **not** to be quietly inferred later: no
            `school_admin`/co-teacher view into a quiz (`QuizService` is scoped strictly
            by `teacher_id`); nothing in the design supports one.
            Note: §2's illustrative pool-count numbers do not arithmetically reproduce
            `allocate_difficulty`'s real output — the prose is authoritative, the example
            numbers are not.
      - [x] **E** done — assignment endpoints + student take/submit (S-26) + `quiz_answers`
            (D3.8). `lemely/db/quiz_taking_repo.py` (`QuizTakingService`, injected clock) +
            three assignment methods on `QuizService` + `student_router`
            (`/api/student/quizzes`, student-role gated) as a **second router in
            `lemely/web/routers/quiz.py`** — the role gate differs from the staff triple so
            the two cannot share one `APIRouter`. New seam
            `ClassService.enrolled_class_ids` is the *only* student-side scoping query;
            do not write a second `ClassEnrollment` query in F.
            1668 tests (1664 passed / 4 live-only skips), 88.35% cov (from 88.00%).
            All 12 gates green, `alembic check` clean, no schema change.
            Endpoints: POST/GET `/api/teacher/quizzes/{id}/assignments`, DELETE
            `.../assignments/{aid}`; GET `/api/student/quizzes`, GET
            `/api/student/quizzes/{aid}`, PUT `.../answers/{question_ref}`, POST
            `.../submit`.
            **Read D3.8 before starting F** — it fixes: closed = quiz status terminal OR
            `closes_at` passed (and a closed quiz is read-only, minting no submission row);
            overdue = a flag, never a block; "not yet open" has no column and needs none;
            and the unassign guard is in practice "refuse if any submission row exists"
            because lazily-created rows are born `in_progress`, never `not_started`.
            `QuizService.create_assignment`/`list_assignments` take a `caller_role` (only to
            reach the role-scoped `ClassService.get_class`/`roster`) — quiz *ownership* is
            still strictly `teacher_id`, still no `school_admin` view.
            Answer leakage is excluded **structurally**: `QuizTakeQuestionRow` has no
            `model_answer`/`mark_scheme_points`/`mcq_answer` field at all. F must not add one
            to any student-facing row; the guard is the absent field, not a DTO omission.
            Known minor: `list_assigned`/`list_assignments` call `roster`/count per
            assignment (bounded N+1, tens of rows per student/quiz) — fine now, revisit only
            if T-10 makes it hot.
      - [x] **F1** done — marking core. `AttemptRepository._persist` is now the single
            writer behind both `persist_correction` (past paper, carries a
            `GradePrediction`, `origin=past_paper`) and the new `persist_quiz_correction`
            (no prediction, `origin=quiz`) — review-queue fan-out shared, not copied.
            `lemely/db/quiz_marking_repo.py` (`QuizMarkingService`, injected clock +
            `IntegritySettings`) adapts each `quiz_questions` row through the pure
            module-level `quiz_question_to_scheme_question`, runs the **existing**
            `correct_paper` + `apply_integrity_checks`, and persists through that shared
            writer, so a low-confidence quiz answer lands in the P3.4 review queue with no
            new engine and no new prompt. Every DB read happens in one short session that
            is **closed before** the Gemini round trip; the persist/status writes are fresh
            short transactions afterwards. `submit` triggers it on a daemon thread
            (`_trigger_marking_in_background`), so `submissionStatus` is always
            `"submitted"` on the wire, never `"marked"`. Idempotent (re-marking a `marked`
            submission is a no-op); a marking failure sets `quiz_submissions.marking_error`
            and leaves status at `submitted`, while a bad id / wrong state still raises.
            **The `_recompute_attempt_totals` quiz guard is in** (`review_repo.py`): for
            `origin=quiz` it recomputes `awarded_marks`/`percentage` but never calls
            `_boundaries_for` and never writes `grade`/`predicted_grade`/`boundary_source`
            — without it the first teacher override on a quiz would invent a grade the
            marking path deliberately never wrote. Paper-level `confidence_band` for a quiz
            is the *weakest* per-question band, ordered by an explicit table, not enum
            declaration order. The synthetic `paper_number=1`/`variant=1`/`Specimen`
            metadata `ExamMetadata` forces on the in-memory marking call is **never
            persisted** — `_persist` NULLs all four session/paper columns when
            `prediction is None`.
            **Chunk G's handed prerequisite is discharged in the same commit (D3.9).** All
            the web-layer sites that derived a grade/percentage/paper-comparison straight
            off `history.records` now filter: `classes._average_for` + class-detail
            `latest`; `teacher._student_row`/`_student_delta`/`_subject_predictions`/
            `_at_risk`/T-05 `attempts`+`trend`/overview mean; `student._momentum`/
            `_subjects`/`GET /student/subject/{code}`. A third predicate `is_paper`
            (origin only) was needed for the three counts that say *papers* — see D3.9 for
            why `is_grade_bearing` is wrong for those. Topic aggregation, `streakDays`,
            `lastActiveAt` and every weakness surface stay unfiltered, deliberately.
            **Do not "tidy" a quiz record back into any of these** — 16 of the 18 tests in
            `tests/test_web_quiz_origin_filtering.py` were verified to fail against the
            pre-filter routers.
            1703 tests (1699 passed / 4 live-only skips), 88.48% cov (from 88.35%).
            All 12 gates green, `alembic check` clean, no schema change. Zero pre-existing
            past-paper tests changed — the `_persist` refactor is a proven behavioural
            no-op on that path.
      - [x] **F2** done — T-10 class results. `lemely/db/quiz_results_repo.py`
            (`QuizResultsService`, 100% cov) + one route, `GET
            /api/teacher/quizzes/{quiz_id}/assignments/{assignment_id}/results`.
            **Per assignment, never per quiz** (§1.6). All five §4.6 panels are pure
            projections over *one* load of that assignment's submissions and their
            attempts, so no two panels can disagree and there is no sixth aggregation
            path. The three §4.6 traps each have a test that fails against the naive
            version (verified by inverting the code, not assumed): (a) per-question
            analysis sums **`effective_marks`** — proven by flipping it to
            `awarded_marks` and watching
            `test_per_question_analysis_uses_effective_marks_not_awarded` fail; (b)
            score distribution is ten **percentage** bands, top band inclusive of 100;
            (c) the roster is re-read live on every call, so a student who joins after
            assignment moves the denominator immediately.
            Reused, never re-derived: ownership is `QuizService.get_quiz` (which also
            supplies the materialized question snapshot), scope is
            `ClassService.roster`, ranking is T-04's own `rank_topic_weaknesses`.
            `history_repo._to_record` → **`attempt_to_record`** (made public) is the
            single attempt→`PaperRecord` projection feeding it — a second projection
            here would have silently dropped the `origin` round-trip chunk G added.
            Still strictly `teacher_id`-scoped: `caller_role` reaches `ClassService`
            only, pinned by `test_school_admin_has_no_view_into_a_quizs_results`.
            **New decision D3.10** — §4.6 fixes the completion *denominator* as the live
            roster but is silent on a student who submits and is then removed, where the
            literal numerator can exceed 100%. Every panel is roster-scoped and the
            excluded work is reported as `offRosterSubmissionCount` rather than silently
            dropped. Do not "simplify" this away.
            Also: `pyproject.toml` gained `TC001/2/3` per-file ignores for
            `lemely/web/routers/quiz.py` + `schemas_quiz.py` — the same exemption every
            other web DTO/DI module already carries (FastAPI + pydantic need those names
            at runtime); it only fired now because the new import statement's members are
            *all* annotation-only, which is when ruff will move a whole statement.
            1721 tests (1717 passed / 4 live-only skips), 88.75% cov (from 88.48%).
            All 12 gates green, `alembic check` clean, no schema change.
- [ ] doing — **P3.6** Parent portal backend (P-01..P-04). Linked children, child overview /
      subject detail / weaknesses (read-only), notification preferences. Parent authz: only
      own linked children.
      **Design fixed 2026-08-06 (D3.11) — implement it, do not redesign.** Established facts,
      do not re-derive:
      - `parent_child_links` already exists (`lemely/db/models/users.py:63`, unique
        (parent_id, child_id), no status column) — a link row IS the grant, there is no
        pending state and none is being added.
      - `AuthService.verify_otp` (`lemely/auth/service.py:228`) **auto-creates** a
        `role=parent` user on first OTP verify, keyed by phone, with a
        `_phone_placeholder_email` placeholder. So a parent user row exists only after that
        parent has proven control of the phone.
      - **Linking direction (D3.11): the student invites, by phone, and only an
        already-OTP-authenticated parent can be linked.** `POST /api/student/parent-links`
        {phone} links to the existing `role=parent` user with that phone; if none exists it
        is a clean 404 telling the student the parent must log in first. This deliberately
        does NOT mint a user from a student-supplied phone — that would be an
        account-creation spam vector and would let one typo hand a stranger a child's
        grades. `DELETE /api/student/parent-links/{parent_id}` revokes; `GET` lists. The
        student owns the consent on both ends. No new schema, no new enum.
      - Reuse, never re-derive: `history_store.load(child_id)`,
        `lemely.core.history.{grade_bearing,is_grade_bearing,is_paper,latest_grade_bearing}`
        (every grade/percentage/paper claim filters — D3.9), `lemely.core.at_risk.assess_at_risk`
        (the only at-risk engine), `lemely.core.analytics.aggregate_weaknesses_from_history`
        (topic-bearing: takes ALL records, unfiltered), `GradeBoundaryStore().resolve()` for
        boundary distance, `lemely.io.det.profiles.get_profile(code).name` for the plain
        subject name (empty string for an unknown code → fall back to the code, never invent).
      - **Honest gaps that must be reported as absent, never faked:** target grade does not
        exist until P4's onboarding questionnaire (P-02's "predicted vs target" ships with
        target `null`, exactly as at-risk rule 2 is *not evaluable* — D3.3); P-04's "what the
        child is doing about it" has no data source beyond the existing study plan.
      - [x] **a** done (3ee592c) — scoping seam + read surface. `lemely/db/parent_repo.py`
            (`ParentLinkService`: `linked_children`, `get_child`, `link`, `unlink` — the ONE
            `parent_child_links` query; every parent route scopes through it, no second
            query anywhere), `lemely/web/schemas_parent.py`, `lemely/web/routers/parent.py`
            (prefix `/api/parent`, gated `require_role(Role.parent)`), plus the three
            student-side link routes above. Routes: `GET /api/parent/children` (P-01),
            `GET /api/parent/children/{child_id}` (P-02),
            `GET /api/parent/children/{child_id}/subjects/{code}` (P-03),
            `GET /api/parent/children/{child_id}/weaknesses` (P-04). Unlinked child = 403,
            unknown user = 404, non-UUID = 422 (matches `teacher_student_detail`).
            **Shipped:** `ParentLinkService` (100% cov) + `lemely/web/routers/parent.py`
            (97%) + `schemas_parent.py`, the three student link routes, and one new
            `ClassService.student_classes()` (the only "a student's classes, with names"
            query — do not write a second). 1768 tests (1764 passed / 4 live-only skips),
            89.04% cov (from 88.75%). All 12 gates green, `alembic check` clean, no schema
            change.
            **Facts established here, do not re-derive:** `is_grade_bearing` is *defined* as
            past-paper origin AND `grade in GRADE_ORDER`, so any "grade not on the ladder"
            guard downstream of `grade_bearing()` is unreachable from a route — keep such
            guards as preconditions, cover them with direct unit tests, do not invent an
            HTTP test that cannot fire. `assess_at_risk` can never emit `BelowTargetEvidence`
            until P4 (D3.3), so its converter branch is likewise unit-tested directly rather
            than by seeding a fake target.
            **Handed to P3.9 (frontend):** P-01's empty state must render the "how to link"
            explanation — the API returns a plain empty list and deliberately carries no
            copy. The link flow the UI must present is D3.11's: the parent OTP-logs-in
            **first**, then the student invites them by phone.
      - [ ] **b** — notification preferences (G-12). Additive migration 0008 +
            `notification_preferences` (one row per user, one explicit NOT NULL boolean
            column per `NotificationType`, defaulting true, + nullable
            `quiet_hours_start`/`quiet_hours_end`). A vocabulary test pins every
            `NotificationType` member to a column so the two cannot drift (the chunk-A
            three-way-pin pattern). Absent row = all defaults. Routes
            `GET/PUT /api/me/notification-preferences` for **any** authenticated role, not
            parent-only — same work, and P5 owns the delivery side. `at_risk_alert` is
            teacher/parent-only per the spec: filtered out of a student's response and a
            422 on PUT. G-12's "weekly summary" toggle has no `NotificationType` and is
            NOT invented here — deferred to P5, which owns notification delivery.
- [ ] todo — **P3.7** Teacher frontend T-01..T-06 (dashboard, classes list, class detail roster,
      class analytics, student detail, at-risk list).
- [ ] todo — **P3.8** Teacher frontend T-07/T-08 (review queue + remark), T-09/T-10 (quiz
      builder + class results), T-12 (announcement composer).
- [ ] todo — **P3.9** Parent frontend G-05 (phone+OTP login screen) + P-01..P-04.
- [ ] todo — **P3.10** Acceptance: Playwright E2E per role, at-risk flags verified against
      seeded scenarios, plus the standing UI gate (QUALITY-BAR, axe 0 serious/critical,
      Lighthouse a11y ≥95, screenshot corpus for every new screen × state × breakpoint,
      Impeccable audit+polish, no regression vs Phase-2.5 baselines).
- [ ] todo — **P3.11** Phase-3 report, merge to develop, push, update PR #3, ntfy.


## Session journal
See `BUILD/JOURNAL.md` for the dated 3-6 line entries; decisions and rationale live in
`BUILD/DECISIONS.md` (D0.x/D1.x/D2.x). Superseded per-task narrative for Phases 0-2 has been
pruned from this file per MISSION §8b now that their reports are committed — see the git
history of this file, or the phase REPORT.md files, if the detail is ever needed again.
