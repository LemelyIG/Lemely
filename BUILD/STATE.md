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
- [x] done — **P3.6** Parent portal backend (P-01..P-04). Linked children, child overview /
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
      - [x] **b** done (622a692) — notification preferences (G-12). Additive migration 0008 +
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
            **Shipped:** `NotificationPreferencesService` (99%), `lemely/web/routers/me.py`
            (100%), `schemas_me.py` (100%). Migration verified on the live stack:
            `upgrade → check → downgrade -1 → upgrade → check`, clean both directions.
            1805 tests (1801 passed / 4 live-only skips), 89.16% cov (from 89.04%).
            All 12 gates green.
            **Do not reintroduce these shapes:** a GET must never materialise a row
            (absent = `DEFAULTS`, returned without a write); `set()`'s `UNSET` sentinel
            exists because `None` legitimately *clears* a quiet-hours bound and so cannot
            also mean "omitted"; an explicit `null` on a toggle is a 422, not a silent
            reset to the default (which would re-enable a notification the user turned
            off). Nothing anywhere reads this table to decide whether to send — including
            against the quiet-hours window. That interpretation is **P5's to write**, and
            P5 must not assume this chunk left it a helper.
- [x] done — **P3.7** Teacher frontend T-01..T-06 (dashboard, classes list, class detail roster,
      class analytics, student detail, at-risk list). Split into four chunks, one commit each.

      **Established facts (2026-08-06, do not re-derive):**
      - Backend routes for all six screens already exist. T-01 `GET /api/teacher/overview`;
        T-02 `GET /api/teacher/classes` (+ `POST /api/classes`, `PATCH`/`DELETE
        /api/classes/{id}`); T-03 `GET /api/classes/{id}` and `/roster` (+ `POST
        .../enroll`, `DELETE .../students/{sid}`); T-04 `GET /api/classes/{id}/analytics`;
        T-05 `GET /api/teacher/students/{id}`; T-06 `GET /api/teacher/at-risk?reason=` +
        `POST`/`DELETE /api/teacher/at-risk/{sid}/acknowledge[/{reason}]`.
      - Frontend today: `Overview.tsx` (T-01) is the ONLY teacher screen on real data
        (`useTeacherOverview`). `Grading`/`Review`/`MarkSchemes` are wired to the P2
        grading-console endpoints. **`Classes.tsx` and `Quizzes.tsx` still render
        `web/src/portals/teacher/data.ts` mock data.** So does the sidebar in
        `portals/teacher/index.tsx`: `recentClasses` (3 fake classes), the hardcoded
        `badge: "12"` on Grading, and the hardcoded "Mr H. Sabry / Physics dept · CAIE"
        user block. All four are hardcoded values masquerading as features — kill them in
        chunk b, do not carry them into a new screen.
      - `useTeacherApi.ts` covers only the 7 P2 grading-console endpoints. Nothing for
        classes, analytics, student detail, or at-risk exists on the client yet.
      - `web/scripts/audit.mjs` is scoped to exactly 4 student routes (D2.10). Extending it
        to the teacher routes is **P3.10's** job, not P3.7's — do not expand it here.
      - **`supabase` is not on `PATH` in a non-interactive shell**, so `scripts/check.sh`
        silently reports the stack down and SKIPS the three live UI gates. Always run it as
        `PATH="$HOME/.local/bin:$PATH" ./scripts/check.sh` or you get 9 gates, not 12.
        (The stack itself is up — `docker ps` shows the twelve `supabase_*_Lemely`
        containers.)
      - **Spec-vs-DTO gaps found before starting (D3.12).** Three T-screens name contents
        the DTOs do not carry, so chunk a adds them additively rather than letting a screen
        omit a spec-required column or invent one client-side:
        T-01 "recent activity: submissions across their classes" has no field at all;
        T-01 class summary cards want top weakness + activity level, T-02 wants last
        activity + at-risk count, but `ClassSummaryDTO` carries neither;
        T-03 wants papers-submitted, last-active and the at-risk **reason**, but
        `StudentRowDTO` has only a bare `gradeAtRisk` bool.
        **Deliberately NOT added: a class-level "average predicted grade."** T-01/T-02 both
        ask for one, but averaging letter grades invents precision the data does not support
        (spec §1.4). `ClassSummaryDTO.average` (mean latest percentage) is rendered and
        labelled as exactly that. This is a knowing deviation from the spec's wording —
        report it, do not quietly "fix" it later by inventing the mean grade.
      - [x] **a** done (c95c52f) — backend additive DTO enrichment. All three gaps closed
            from data the routes already load (no new query): `OverviewDTO.recentActivity`
            (+ `RecentActivityDTO`, cap 8, `_RECENT_ACTIVITY_LIMIT`); `ClassSummaryDTO`
            **and** `ClassDetailDTO` + `atRiskCount`/`lastActivityAt`/`topWeakness`;
            `StudentRowDTO` + `paperCount`/`lastActiveAt`/`flags`. 1817 tests (1813 passed
            / 4 live-only skips), 89.19% cov (from 89.16%). All 12 gates green, `alembic
            check` clean, no schema change.
            **Signature changes chunks b–d must not trip over:** `_student_row` now takes
            required kwargs `now` + `acks`; `_class_row_to_summary`/`_class_row_to_detail`
            take `now` (and detail takes `acks`); **`_average_for` now takes
            `list[StudentHistory]`, not `(student_ids, history_store)`**.
            **Do not reintroduce these shapes:** (a) `datetime.now(UTC)` called per student
            inside a roster loop — the "At risk" card and that roster's per-row flags then
            evaluate against different instants; one hoisted `now` per request. (b)
            Inlining the class mean in `_class_row_to_summary` instead of calling
            `_average_for` — that leaves `_average_for` called only by its own tests, i.e.
            a D3.9 regression guard protecting no production path (this was caught in
            review of the chunk, not by the gates). (c) A second `_at_risk_flag_dto`-shaped
            converter for the roster's `flags`.
            `AtRiskAcknowledgementDTO`/`AtRiskFlagDTO` moved earlier in
            `schemas_teacher.py` so `StudentRowDTO.flags` is an in-order reference — do not
            reorder them back. `pyproject.toml` gained the standard `TC001/2/3` per-file
            ignore for `classes.py` (FastAPI `Depends` needs the names at runtime).
      - [x] **b** done (3b0eb3c) — client API/types layer + T-01 + T-02. 1825 tests (1821
            passed / 4 live-only skips), 89.18% cov. All 12 gates green.
            **New seams c/d must reuse, not re-derive:** `useTeacherClasses`/`useCreateClass`
            /`useUpdateClass`/`useDeleteClass` in `useTeacherApi.ts`; the DTO mirror types in
            `lib/teacherTypes.ts` (~~types for T-03..T-06's endpoints are already written
            there~~ — **wrong, corrected in chunk c**: chunk b added only the T-01/T-02
            shapes and its module header said so explicitly. Chunk c added the T-03/T-04
            types; **T-05/T-06's are still missing and chunk d must write them**);
            `lib/meTypes.ts` + `useMeApi.ts::useProfile()`
            (shared `/api/me/*`, deliberately NOT portal-scoped — P3.9's parent shell uses
            the same one); `relativeTime`/`initialsOf` in `lib/utils.ts`.
            New backend route `GET /api/me/profile` (+ `ProfileDTO`, `deps.get_user_mirror`).
            **Do not reintroduce:** the sidebar's fabricated "Mr H. Sabry / Physics dept ·
            CAIE" identity, `recentClasses`, or the hardcoded Grading `badge: "12"` — all
            three were fiction with no data source and are gone.
            **Two real defects fixed here — do not "tidy" either away:** (a) `request()` in
            `lib/api.ts` called `res.json()` unconditionally, which throws on a 204;
            `useDeleteClass` is the app's first DELETE caller, so every successful delete
            would have surfaced a fake error. (b) `overflow-x-hidden` on the teacher layout
            wrapper in `portals/teacher/index.tsx` + `min-w-0` on the flex chain fixes real
            page-level horizontal scroll at 380px (scrollWidth 644 vs clientWidth 380) — it
            is load-bearing, not cosmetic.
            **Known, accepted:** `Classes.tsx` links rows to `/teacher/classes/:classId`,
            which 404s until chunk c adds the route. Coverage dipped 0.01pp on one line,
            `deps.get_user_mirror()`'s singleton body, always dependency-overridden in tests
            exactly like the ten sibling providers already uncovered in that file.
            **`web/` has no test runner configured at all** — every teacher screen so far has
            shipped without frontend unit tests; behaviour is covered by Playwright E2E
            instead. Do not brief a future chunk to "add the missing frontend unit tests"
            without first standing up a runner; that is P3.10-shaped work.
            **Pre-existing, NOT this chunk's to fix:** all five teacher screens use arbitrary
            px/oklch literals rather than the DESIGN.md token scale. It is a portal-wide
            convention predating P3.7 (P2.5.3 retrofitted the *student* screens only).
            Migrating them is its own task — see the P3.10 note.
      - [x] **c** done (e789dc7) — T-03 roster + T-04 analytics. New:
            `screens/ClassDetail.tsx` (shared shell: header, join code, stat strip, tabs),
            `ClassRoster.tsx`, `ClassAnalytics.tsx`; routes `/teacher/classes/:classId`
            and `.../analytics`. 1825 tests / 89.18% cov (both unchanged — zero backend
            files touched). All 12 gates green.
            **Do not "tidy" any of these:** (a) `ClassDetailDTO.mastery`/`distribution` are
            populated but deliberately UNRENDERED on T-03 — they are a second,
            differently-derived version of what T-04 shows authoritatively, and rendering
            both recreates the "same label, two numbers" divergence D3.3/D3.4/D3.5 each had
            to fix once. (b) `StudentRow.mark`/`grade` are latest-paper values shown under
            "Latest mark"/"Predicted grade"; do not restore the spec's literal "average"
            wording without re-deriving why it was changed. (c) The three scroll regions'
            `tabIndex`/`role="region"`/`aria-label` fix a real serious axe finding
            (`scrollable-region-focusable`). (d) Links to `/teacher/students/:studentId`
            (roster names, weakness drill-down) 404 until chunk d — expected, do not
            "fix" by deleting the links.
            **Fixed here beyond scope:** `initialsOf` was duplicated verbatim in
            `Overview.tsx` + `Review.tsx` → now in `lib/utils.ts`, both repointed; the same
            latent `scrollable-region-focusable` on chunk b's `Classes.tsx` table; and two
            **raw NUL bytes** in `ClassAnalytics.tsx` (a Map composite-key separator written
            as literal 0x00, which made git/grep treat the file as binary) → now `backslash-u-0000`
            escapes. Watch for that last shape recurring — it passes typecheck and build
            silently.
      - [x] **d** done — T-05 student detail + T-06 at-risk list. New:
            `screens/StudentDetail.tsx` (route `/teacher/students/:studentId`, drill-down
            only, no nav entry) and `screens/AtRiskList.tsx` (route `/teacher/at-risk`,
            added to the sidebar). Closes the T-03/T-04 404s chunk c documented as
            expected. `lib/teacherTypes.ts` gained the `StudentDetailDTO`/`AtRiskListDTO`
            families; `useTeacherApi.ts` gained `useStudentDetail`/`useAtRiskList`/
            `useAcknowledgeAtRisk`/`useUnacknowledgeAtRisk`. 1826 tests (1822 passed / 4
            live-only skips), 89.18% cov. All 12 gates green, `alembic check` clean, no
            migration.
            **The enum bugfix below ships with a standing structural guard** added in
            review: `test_every_enum_column_binds_its_value_not_its_member_name`
            (`tests/test_db_schema.py`, metadata layer, no DB needed) asserts every
            `sa.Enum` column either satisfies `name == value` or passes `values_callable`.
            Verified by inversion — it fails against the unfixed declaration. **This is the
            only thing standing between the build and a silent repeat of D3.13; do not
            delete it as a "trivial metadata assertion".**
            **T-05 integrity signals confirmed absent, not stubbed** — `StudentDetailDTO`
            carries no such field (verified against `schemas_analytics.py` and the
            router's own docstring, D3.4); nothing renders in that panel's place, per the
            brief. "Open any attempt"/"assign practice" render visibly disabled with a
            "Coming soon" tag (T-08/P4); "contact route if configured" has no config
            source anywhere and is omitted entirely, same treatment as the integrity gap.
            **T-06 severity is the backend's own order, not a client invention** —
            `_at_risk_severity_key` (`teacher.py`) already sorts the response (flag count
            desc, then worst grade first); the screen's re-sortable "Severity" column
            mirrors that exact two-key definition client-side (documented inline) so
            sorting by Name/Class/Grade and back to Severity doesn't lose it. `below_target`
            is deliberately absent from the reason filter (D3.3: not evaluable until P4).
            Acknowledge is worded "Acknowledge"/"Undo", never "Dismiss"/"Mute", with an
            inline note form whose copy says plainly it "stays visible and reappears... never
            a permanent mute" (D3.5); `acknowledgedBy` is never rendered (every ack visible
            to a caller is provably their own — `_acknowledgement_index` scopes
            `load_for_teacher(auth.user_id, ...)` — and there is no display-name source to
            resolve it against honestly, so the id is simply not shown rather than shown as
            if it were a person).
            **Real defect found and fixed, discovered only by running against the live
            Alembic-migrated stack (not by `pytest`, which never catches this class of
            bug — see below): `AtRiskAcknowledgement.reason`'s `sa.Enum(AtRiskReason, ...)`
            had no `values_callable`, so SQLAlchemy bound acknowledge/unacknowledge queries
            using the enum's `.name` (`"DECLINING_TREND"`) while the real migrated Postgres
            type only accepts the `.value`s migration 0006 actually created
            (`"declining_trend"`, lowercase) — every acknowledge call 500'd
            (`DataError: invalid input value for enum atriskreason`) against any real
            stack. Every other native enum in this package sidesteps the same SQLAlchemy
            default by using lowercase member names equal to their values
            (`low_confidence = "low_confidence"`); `AtRiskReason` is the one enum reused
            directly from `lemely.core` with ordinary SCREAMING_SNAKE_CASE members, so it
            alone needed `values_callable` spelled out. `tests/test_at_risk_repo.py` (826
            tests green since P3.4b) never caught it because its Postgres schema comes
            from `Base.metadata.create_all()`, which derives the enum's DDL from this same
            class using the same default — self-consistently wrong against itself. Fixed
            with `values_callable=lambda enum_cls: [e.value for e in enum_cls]` in
            `lemely/db/models/ops.py`; no migration needed (the real DB type already had
            the correct values), `alembic check` stays clean (its default comparator
            doesn't diff enum labels either way — this is exactly why the bug was
            invisible to that gate too). **This was a real, standing gap in every gate this
            build relies on**: neither `pytest` nor `alembic check` can catch a
            Python-enum-binding/DB-enum-value mismatch on a native enum column, and a
            `create_all()`-based fixture actively hides it; the only thing that caught it
            was a Playwright run against the real Alembic-migrated stack exercising the
            actual mutation. **Now closed structurally** by the metadata test noted above
            (all 25 enums audited: `AtRiskReason` was the only unsafe one) and recorded as
            **D3.13**. Treat "unit tests pass against a `create_all()` schema" as no
            evidence at all that a column works against the migrated database.
            **Second, smaller defect found and fixed in this chunk's own new code**:
            `AttemptDTO.paperId` (`_paper_id` in `teacher.py`) is documented as a "human
            paper identity" (`subjectCode/paperNumber+Variant`), not a unique id — a
            student who resits the same paper produces multiple attempt rows sharing one
            `paperId`. Using it alone as the attempt-history table's React `key` produced a
            real duplicate-key console error against seeded multi-attempt data;
            `` `${paperId}-${recordedAt}` `` disambiguates. **Also fixed**: T-06's "Latest
            grade" column initially rendered `basis="achieved"`; `AtRiskListEntryDTO.grade`
            is the same "latest recorded grade" value `StudentRowDTO.grade` (T-03) and
            `SubjectPredictionDTO.predictedGrade` (T-05) already render `basis="predicted"`
            for — corrected for consistency (same value must not read differently on two
            screens). `request()` in `lib/api.ts` previously discarded every backend error's
            real `detail` message in favour of a generic `"422 Unprocessable Entity"`-style
            status line — silently, across every existing screen's `error.message` render,
            not just this chunk's. Now parses the JSON body's `detail` when present,
            falling back to the status text otherwise; this is what makes T-06's mandated
            "handle the 422 as a real error state" show the actual reason rather than a
            meaningless generic string.
            Verified end-to-end against the real local stack (teacher minted via
            `AuthService.signup` directly, since self-service signup is student-only):
            populated + empty states at 380/768/1440 for both screens, zero
            serious/critical axe violations, no page-level horizontal scroll at 380px, the
            reason filter as a real server-side query param, and the acknowledge round
            trip (acknowledge with a note → flag stays listed and tagged, never
            disappears → persists across reload → undo reverts to unacknowledged, still
            never disappears). Throwaway spec + seed script deleted after verification, per
            brief.
            **P3.7 is now done — all six teacher screens (T-01..T-06) on real data.**
- [x] done — **P3.8** Teacher frontend T-07/T-08 (review queue + remark), T-09/T-10 (quiz
      builder + class results), T-12 (announcement composer). Four chunks, one commit each.

      **Established facts (2026-08-06, do not re-derive):**
      - **T-07/T-08 backend is complete** (P3.4, `lemely/web/routers/review.py`, prefix
        `/api/teacher/review`): `GET ""`, `GET /{item_id}`, `POST /bulk-approve`,
        `POST /{item_id}/resolve`, `POST /{item_id}/dismiss`. DTOs in
        `lemely/web/schemas_review.py`.
      - **T-09/T-10 backend is complete** (P3.5 chunks D/E/F2, `lemely/web/routers/quiz.py`,
        prefix `/api/teacher/quizzes`): POST/GET `""`, `GET /pool-count`, `GET|PATCH /{id}`,
        `POST /{id}/status`, `POST /{id}/questions/generate`, `DELETE
        /{id}/questions/{question_ref}`, POST/GET `/{id}/assignments`, `DELETE
        /{id}/assignments/{aid}`, `GET /{id}/assignments/{aid}/results`. DTOs in
        `lemely/web/schemas_quiz.py`.
      - **T-12 has NO backend at all.** The `announcements` table exists from Phase 1
        (`lemely/db/models/ops.py:75` — `author_id`, nullable `school_id`, nullable
        `class_id`, `title`, `body`, nullable `publish_at`) but nothing reads or writes it
        and there are no routes. Chunk a builds them. **No migration needed.**
      - **Two spec-vs-reality gaps that must be reported, never faked (D3.14):**
        (i) T-08 mandates "the student's actual scan crop side by side with the mark scheme
        extract". **Neither is persisted** — `ReviewItemDetailDTO`'s own docstring already
        records this; `studentAnswer` (what Lemely transcribed) + `matchedPointIds` +
        `expectedAnswer` are the honest substitutes. Do not render a placeholder image or
        invent a mark-scheme excerpt.
        (ii) T-12 wants "optional attachment" — there is no attachment column and no
        storage wiring. Omit it entirely (same treatment as T-05's absent integrity
        signals and "contact route"), do not stub a disabled upload control.
      - **Nothing delivers an announcement to a student.** There is no student-facing
        announcement surface and no notification send path — MISSION §4 puts both in Phase 5
        (which also owns `notification_preferences`, written but never read — P3.6 chunk b).
        P3.8 ships compose/list/delete only; the phase report must say students cannot see
        these yet.
      - `Review.tsx` today is wired to the **P2 grading-console** endpoints, not to P3.4's
        real review queue — chunk b replaces it. `Quizzes.tsx` still renders
        `portals/teacher/data.ts` mock data — chunk c replaces it, and `data.ts` should be
        gone by the end of chunk c.
      - Reuse, never re-derive: `useTeacherApi.ts` hooks + `lib/teacherTypes.ts` DTO mirrors
        + `lib/api.ts::request()` (which now surfaces the backend's real `detail` — P3.7d),
        `relativeTime`/`initialsOf` in `lib/utils.ts`, `ClassService` for every tenancy
        question (`list_classes`, `get_class`, `roster`, `member_school_ids`).
      - **`supabase` is not on `PATH` non-interactively** — always run
        `PATH="$HOME/.local/bin:$PATH" ./scripts/check.sh` or you silently get 9 gates, not 12.
      - `pytest -q` prints no `N passed` line; count progress characters (see the P3.1–P3.4b
        note above). Baseline entering P3.8: **1826 tests / 89.18% cov, all 12 gates green.**
      - [x] **a** done (4db0a5d + 9c9c0bb) — announcements backend (T-12 prerequisite).
            `lemely/db/announcement_repo.py` (`AnnouncementService`),
            `lemely/web/routers/announcements.py` (prefix `/api/teacher/announcements`,
            gated `teacher`+`school_admin`), `schemas_announcements.py`,
            `deps.get_announcement_service()`. Routes: `POST ""`, `GET ""` (author-scoped,
            newest first), `DELETE /{id}` (204). 1863 tests (1859 passed / 4 live-only
            skips), 89.34% cov (from 89.18%). All 12 gates green, `alembic check` clean,
            **no migration** — the Phase-1 table was already the right shape.
            **Chunk d must not re-derive these:** tenancy is 100% delegated to
            `ClassService` (`get_class` per class id, `member_school_ids` for school-wide) —
            this module runs no `classes`/`school_memberships` query of its own, do not add
            one. Fan-out is **all-or-nothing**: every target is validated before any row is
            written, so a teacher owning 9 of 10 targeted classes gets a 403 and *zero*
            rows, never a partial send. `create()` takes an explicit `school_id` (a
            school_admin can administer several schools, so `school_wide=True` alone does
            not say which) validated against `member_school_ids`.
            **Follow-up 9c9c0bb (found in verification, not by the gates):** the service
            accepted `class_ids` *and* `school_wide` together and wrote `len+1` rows. The
            audiences overlap, so that hands Phase 5's unwritten delivery layer two rows for
            one recipient. Now a 422 — the audience is exclusive, enforced in the service so
            the composer UI cannot bypass it. Do not "restore" the union.
            `publish_at` is **stored but never read** — no scheduler exists; delivery is
            Phase 5's. No attachment field anywhere (D3.14 §2).
      - [x] **b** done (51425cd) — T-07 review queue + T-08 remark. `Review.tsx` rewritten
            (was the P2 grading console's paper-level `GET /grading/queue`) + new
            `screens/ReviewItem.tsx` at `/teacher/review/:itemId` + new C-14 `Checkbox`
            (`components/ui/checkbox.tsx`, catalogued). Removed `useGradingQueue`/`QueueRow`/
            `GradingQueue` — the replaced screen was their only consumer. **Zero backend files
            touched: 1863 tests / 89.34% cov, unchanged from chunk a.** All 12 gates green.
            **Do not reintroduce / do not "tidy" away:**
            (a) T-07's three filters live in the URL (`useSearchParams`), not component state —
            that is what lets T-08 carry the same querystring through so "next item" walks the
            *filtered* batch and "back to queue" restores the filters. All three are real
            server-side params; never re-filter an unfiltered fetch client-side.
            (b) The list is rendered in the server's own oldest-first order and never re-sorted
            client-side — `ReviewService.list_queue` already orders by `created_at` asc, and
            that IS the "prioritised list" the spec asks for.
            (c) Bulk-approve renders `skipped` from a `snapshotRef` of the rows taken at
            trigger time, because success invalidates and refetches the queue — by the time the
            banner renders the skipped rows may be gone from `queueQuery.data`.
            (d) A filter change clears the selection (a selection made under one filter must not
            get bulk-approved once the visible set changes underneath it).
            **Two judgment calls, documented in-file, neither spec-mandated — decide
            deliberately before changing either:** integrity items (`plagiarism_flag`/
            `ai_detection_flag`) get **dismiss only** on T-08, accept/adjust-marks renders for
            every other reason (the backend's `resolve` has no reason restriction, so without
            this an integrity flag could be closed via an anonymous multi-select, bypassing the
            "signal, not verdict" framing); and `manual` is excluded from the reason filter
            because nothing in the pipeline ever writes a `manual` row — same call
            `AtRiskList.tsx` documents for `below_target` (D3.3).
            **D3.14 §1 honoured literally:** T-08 states plainly that the scan image and the
            mark scheme's wording are not stored, and renders the honest substitutes
            (transcription labelled "not the scan", expected answer, matched point
            *identifiers* as bare chips). No placeholder image, no scheme prose reconstructed
            from point ids. The "note to the student" textarea appears **only** in the
            adjust-marks form — that is the only path where `note` becomes
            `QuestionResult.teacherNote`; on accept-as-is it is an internal resolution note.
            Neither path claims the student is notified (no delivery path exists).
            **New spec-vs-backend gap for the phase report:** T-07's spec names a fourth reason
            category, "student disputed the transcription". There is no `ReviewReason` value and
            no creation path for it anywhere. `manual` is a generic unused catch-all, not a
            dispute flow; labelling it "student disputed" would invent a meaning the backend
            does not assert. Reported, not faked, not built (no backend change was authorized).
            **Verified against the live Alembic-migrated stack** (throwaway seed + spec, deleted
            after use — do not look for them): 20/20 green across populated / filtered-empty /
            error at 380/768/1440, both T-08 panels, and every mutating flow, each asserting
            zero serious/critical axe violations, zero console errors, no horizontal scroll.
            **Independent Postgres check of the mutations** (the P3.7d/D3.13 lesson — a green UI
            is not evidence of a correct write): an override persists `teacher_awarded_marks`
            while leaving the AI's own `awarded_marks` untouched and recomputes the attempt
            total (2→4, 40%→80%); a dismiss writes **nothing at all** to the `QuestionResult`;
            accept-as-is closes the row with marks unchanged.
            Known, honest: no real `skipped` entry occurred in verification (nothing raced), so
            the skip-rendering path is exercised by code review and the DTO contract, not by an
            observed skip.
            **Environment note that cost real time — do not re-derive:** a throwaway spec placed
            in `web/e2e/` is picked up by `scripts/check.sh`'s Playwright gate, so a stale one
            fails the gate for reasons unrelated to the diff. Seeding directly against the stack
            needs `LEMELY_SUPABASE__SERVICE_ROLE_KEY`/`__ANON_KEY` exported from
            `supabase status -o env` (`playwright.config.ts` does this itself, standalone
            scripts do not); do **not** also export `LEMELY_AUTH__JWT_SECRET` — `Settings`
            rejects it as an extra input. And `./scripts/check.sh` needs
            `source .venv/bin/activate` as well as the `PATH` fix, or all five backend gates
            report "command not found" as FAIL.
      - [x] **c** done (7b80532) — T-09 quiz builder on the real quiz API, implementing
            D3.15's step map exactly. `Quizzes.tsx` rewritten as a real quiz list
            (`GET /teacher/quizzes`) whose "New quiz" form creates a real draft row
            immediately (no client-side unsaved state); new `screens/QuizBuilder.tsx`
            (route `/teacher/quizzes/:quizId`); new C-15 `Stepper`
            (`components/ui/stepper.tsx`), catalogued. **Zero backend files touched:
            1863 tests / 89.34% cov, unchanged from chunk a.** All 12 gates green.
            **Do not reintroduce / do not "tidy" away:**
            (a) The active step lives in `?step=n` and is persisted to `quiz.builderStep`
            by the *same* `PATCH` that saves the step's fields, through one
            `goToStep(next, extra?)`. That single-request coupling is what makes
            "draft saving throughout" real — leaving mid-flow resumes at the step left,
            not step 1. A failed PATCH shows an inline banner and does **not** roll the
            visible step back (only the resume point is at risk, never the teacher's
            unsaved form state).
            (b) `subjectCode` renders read-only on step 1: it is fixed at creation and has
            no `UpdateQuizDraftRequest` field, so an editable input would be wired to a
            PATCH that silently drops it.
            (c) A non-draft quiz is read-only on steps 1-5 (every write 422s once out of
            `draft`), but step 6 stays live — `create_assignment`/`delete_assignment` have
            their own independent preconditions. Narrower than "opens read-only" read
            literally; deliberate.
            (d) The builder never posts `/status`. `create_assignment` flips
            `draft→assigned` itself — **verified in Postgres** (`status = assigned` after
            assigning, with no status call made).
            **Verified end-to-end against the live Alembic-migrated stack** (throwaway seed
            + spec, both deleted after use — do not look for them): 6/6 green across the
            list empty state, the full six-step walk, draft-resume-at-`builderStep`, and
            all three breakpoints, each asserting zero serious/critical axe violations,
            zero console errors, and no horizontal scroll at 380/768/1440.
            **Independent Postgres check of the writes** (the D3.13 lesson — a green UI is
            not evidence of a correct write): every step's field landed —
            `time_limit_minutes 45`, `included_topics ["Thermal physics"]`,
            `target_grade C`, `pool_source past_paper`, `requested_count 6`,
            `builder_step 6`, `status assigned`; 6 `quiz_questions` rows, all `included`,
            6 distinct `question_ref`s, prompt text **copied** with `question_bank_id`
            retained as provenance only (§1.5); the `quiz_assignments` row carries the
            right class, `assigned_by`, `due_at` correctly converted local→UTC, and
            `closes_at` NULL because it was left blank; difficulty mix for target C came
            back 3 standard / 2 foundation / 1 challenge — three bands, honouring
            "every target keeps at least two difficulty bands in play".
            **`data.ts` is NOT gone — this line's own plan above was wrong.** It still
            exports `navItems` and the `StatCard` interface, which
            `portals/teacher/index.tsx` and `components/StatCard.tsx` import; deleting the
            file would break both. Every *mock-data* export it held is gone. The file's
            header records this.
            **`useSetQuizStatus` is implemented and exported but has no consumer yet** —
            quiz-level close/archive belongs to chunk d's results screen, not to the
            builder. Wire it there rather than deleting it.
            **Two pre-existing defects surfaced here, neither introduced by this chunk and
            neither in scope to fix:** (i) `text-t3` at 10-13px measures 4.36:1 against the
            default surface, below WCAG AA's 4.5:1 — this screen uses `text-t2` throughout
            to avoid emitting it, but `Classes.tsx`/`ReviewItem.tsx` and every other
            teacher screen still use `text-t3` for identical caption text and would fail
            the same check; they are simply outside D2.10's fixed 4-route audit scope.
            Fixing the `--t3` token or retrofitting those screens is **P3.10** work (it
            belongs with carried item (a) — extending `audit.mjs` past the 4 student
            routes is what would have caught this).
            (ii) `EmptyState` renders its heading as plain text, not a heading element —
            the "non-heading empty/error tags" gap already listed in the Phase-2.5 report
            §8 deferred set. Confirmed still present; still deferred.
      - [x] **d** done (b306f7f) — T-10 quiz results + T-12 announcement composer.
            New `screens/QuizResults.tsx` (route
            `/teacher/quizzes/:quizId/assignments/:assignmentId/results`, linked from
            T-09 step 6) and `screens/Announcements.tsx` (route
            `/teacher/announcements`, added to the sidebar). **Zero backend files
            touched: 1863 tests / 89.34% cov, unchanged.** All 12 gates green.
            **Do not reintroduce / do not "tidy" away:**
            (a) T-10 renders every panel straight from `QuizAssignmentResultsDTO` and
            **never re-derives one panel's number from another** (the class average is
            `averagePercentage`, not a mean over the student rows; completion is
            `completion.completedCount`, not a filter over `students`). That is what
            makes two panels structurally unable to disagree — computing one
            client-side "to save a field" undoes the whole §4.6 shape.
            (b) `null` is never 0%: an empty roster reads "No students on the roster
            yet", an unmarked question an em-dash. Pinned by a live assertion that the
            empty-assignment view contains **no** "0%" string anywhere.
            (c) T-12's audience is a **radio pair, not two checkboxes** — `classIds`
            and `schoolWide` together are a 422 by design (chunk a's follow-up), so the
            rejected state is unreachable rather than merely validated.
            (d) The composer states plainly that students cannot see announcements yet,
            and `publishAt` is labelled recorded-but-not-scheduled. No attachment
            control at all (D3.14 §2) — not even a disabled one.
            **No backend change was needed for T-12's school-wide option**: the
            pre-existing `school_admin`-gated `GET /api/school/seats` already returns
            `schoolId` + `schoolName` per administered school, and is now mirrored by
            `lib/schoolTypes.ts` + `useSchoolApi.ts::useAdminSchools(enabled)`.
            **Do not enrich `/api/me/profile` with school memberships to avoid it** —
            that was considered and rejected as a second source for the same fact.
            **Quiz close/archive lives on the results screen**, not the builder — it is
            the only screen that can see whether the class has finished. That gives
            chunk c's `useSetQuizStatus` its consumer; it is no longer unused.
            **Two shared helpers extracted, not copied** (the `initialsOf` lesson from
            P3.7 chunk c): `downloadCsv` → `lib/utils.ts` and the
            accuracy→tone→severity ladder → **`lib/severity.ts`**
            (`accuracyTone`/`TONE_TO_SEVERITY`/`TONE_CLASS`), both previously private to
            `ClassAnalytics.tsx`, which now imports them. **Never inline those
            thresholds into a screen** — a second copy is how a fourth "same label, two
            numbers" divergence (D3.3/D3.4/D3.5) starts.
            **Verified end-to-end against the live Alembic-migrated stack** (throwaway
            seed + spec, both deleted after use): 8/8 green — populated T-10 (completion
            measured against the *live* roster at 3 of 4, the off-roster submission
            reported, the overridden question counted, a `marking_error` row explained
            rather than blank, a no-submission roster student present as "Not started"),
            the nothing-marked-yet state, T-12 compose→list→delete, the disabled-without-
            an-audience guard, the T-09→T-10 link, and all three breakpoints — each
            asserting zero serious/critical axe violations, zero console errors, and no
            horizontal scroll at 380/768/1440.
            **Independent Postgres check:** the composed row carries the right
            `class_id` with `school_id` NULL (audience provably exclusive) and a
            `publish_at` correctly converted local→UTC; the delete round trip leaves
            **zero** rows, so the UI removing the row is a real delete and not a hidden
            list entry.
            Known, honest: T-10's populated state was reached by seeding
            `quiz_submissions`/`attempts`/`question_results` directly, because the e2e
            harness forces `gemini_api_key = None` and stubs the client, so real quiz
            marking cannot run there. The projection logic itself is covered by
            `QuizResultsService`'s own tests (100% cov, P3.5 chunk F2); what this pass
            proves is the rendering and the route, not the marking pipeline.
            **P3.8 is now done — T-07..T-10 and T-12 are all on real data.**
- [x] done — **P3.9** Parent frontend G-05 (phone+OTP login screen) + P-01..P-04.
      Four chunks, one commit each.

      **Established facts (2026-08-07, do not re-derive):**
      - **Parent backend is complete** (P3.6, `lemely/web/routers/parent.py`, prefix
        `/api/parent`, gated `require_role(Role.parent)`): `GET /children` (P-01),
        `GET /children/{child_id}` (P-02), `GET /children/{child_id}/subjects/{code}`
        (P-03), `GET /children/{child_id}/weaknesses` (P-04). DTOs in
        `lemely/web/schemas_parent.py` — read that file for the authoritative field
        docs, every field carries a provenance note. Student-side link routes:
        `GET|POST /api/student/parent-links`, `DELETE /api/student/parent-links/{pid}`.
      - **OTP backend is complete** (P1.4): `POST /auth/otp/request` (`{phone}` →
        `{status:"sent"}`, **429 inside the resend cooldown**), `POST /auth/otp/verify`
        (`{phone, code, deviceId}` → `TokenResponseDTO`, 401 on wrong/expired).
        `AuthContext.tsx` **already exposes `requestOtp`/`verifyOtp` mutations** — they
        have no consumer yet. Do not write a second OTP client.
      - **`verify_otp` auto-creates the `role=parent` user** (D3.11), so G-05's spec
        state *"no account found for this number"* is **unreachable by construction** —
        every verified phone gets an account. Its honest equivalent is P-01's
        no-children-linked empty state. Report that, do not fake an error path.
      - **Real defect to fix in chunk b, not carry:** `App.tsx`'s `TEACHER_ROLES`
        includes `"parent"` and `portalPathForRole` (`lib/auth/RequireAuth.tsx`) returns
        `/teacher` for every non-student — so a parent logging in **lands in the teacher
        portal today**. The comment there already names it as a Phase-3 placeholder.
      - `index.css` scopes tokens by `[data-portal="student"|"teacher"]` (lines ~399/431).
        A parent scope must be added there; never hardcode a colour outside it.
      - Reuse, never re-derive: `lib/api.ts::request()` (surfaces the backend's real
        `detail` — P3.7d), `relativeTime`/`initialsOf`/`downloadCsv` in `lib/utils.ts`,
        `lib/severity.ts`, `useMeApi.ts::useProfile()` (shared `/api/me/*`, deliberately
        NOT portal-scoped — the parent shell uses this same one), and the C-1..C-15
        component library in `components/ui/`.
      - **`supabase` is not on `PATH` non-interactively** and the venv must be active —
        always run `source .venv/bin/activate && PATH="$HOME/.local/bin:$PATH"
        ./scripts/check.sh` or you silently get 9 gates, not 12 (or 5 spurious FAILs).
      - `pytest -q` prints no `N passed` line; count progress characters. Baseline
        entering P3.9: **1863 tests / 89.34% cov, all 12 gates green.**
      - A throwaway Playwright spec left in `web/e2e/` is picked up by `check.sh` — delete
        verification specs after use.
      - [x] **a** done (454e334) — G-05's developer OTP affordance (D3.16).
            `SmsProvider.delivers_out_of_band` (False on `MockSmsProvider`) gates
            `AuthService.request_otp`'s new `str | None` return; the route surfaces it
            as `OtpRequestResponseDTO.devCode`, mirrored in `lib/authTypes.ts`.
            1866 tests (1862 passed / 4 live-only skips), 89.34% cov (unchanged —
            the two new tests cover new lines proportionally). All 12 gates green,
            no migration.
            **Chunk b consumes this:** `POST /auth/otp/request` now returns
            `devCode`; render it in an explicitly-labelled developer panel and treat
            `null` as "a real provider is configured" (hide the panel entirely),
            never as an error. Do not add an env check on the client to decide
            whether to show it — the backend already made that decision.
      - [x] **b** done (b20a9c6) — parent portal shell + role split + G-05 + P-01 + **P-02**.
            **The split changed from the original plan:** P-02 moved into b because P-01's
            spec-mandated single-child skip redirects straight to it — shipping P-01 without
            it would have made the default parent journey land on a 404. c is now P-03 + P-04.
            New: `[data-portal="parent"]` scope in `index.css` (accent `--md-secondary`, the
            third accent role already in the palette), `portals/parent/index.tsx` (shell +
            `parentRoute`), `screens/Children.tsx`, `screens/ChildOverview.tsx`,
            `portals/auth/ParentLogin.tsx` (route `/login/parent`), `lib/parentTypes.ts`,
            `lib/hooks/useParentApi.ts`. **Zero backend files touched: 1866 tests / 89.34%
            cov, unchanged.** All 12 gates green.
            **Real defect fixed, not carried:** `App.tsx` had `"parent"` in `TEACHER_ROLES`
            and `portalPathForRole` returned `/teacher` for every non-student, so a parent
            completing OTP landed in the teacher console where every panel 403s.
            `school_admin`/`platform_admin` still resolve there deliberately — they hold
            those roles; K-01/X-01 are later phases.
            **Do not reintroduce / do not "tidy" away:**
            (a) `statusLine` is rendered **verbatim** from the backend. Reassembling it
            client-side from `subjects` would be a second source for the same claim.
            (b) P-02's at-risk copy is rephrased from the flag's **structured evidence**,
            not from `summary` (which says "14pp drop" — jargon to a parent). Unknown
            reasons fall back to `summary`; `below_target` deliberately has no hand-written
            parent copy because it cannot fire until P4 (D3.3).
            (c) `target` renders as "no target grade set yet", never defaulted or
            back-derived from `predictedGrade`.
            (d) `predictedGrade` renders `basis="predicted"` — same value, same reading as
            T-03/T-05/T-06 (P3.7 chunk d had to correct exactly this once).
            (e) The child switcher hides at one child and on the list itself; both the
            switcher and the sign-out button carry an `aria-label` that is **never hidden**
            — their visible text is `hidden sm:inline`, and without it axe reports a real
            serious `button-name`/unlabelled-control violation below 640px. Found in
            verification, not by the gates.
            (f) G-05's "no account found" and separate "expired code" states are
            **unreachable by construction** (D3.11 auto-create; one 401 carrying a real
            detail) and are documented as absent rather than stubbed.
            Verified end-to-end against the live stack (throwaway seed + specs, deleted —
            do not look for them): 3/3 green over empty state / single-child skip /
            two-child list + switcher, each asserting zero serious/critical axe, zero
            console errors, no horizontal scroll at 380/768/1440. Independent Postgres
            check: both phones minted `role=parent` rows, the linked parent holds exactly
            two children.
            **Seeding facts chunk c/d should not re-derive:** `WeakArea` requires
            `question_ids`; `ExamMetadata` lives in `lemely.core.schemas`, NOT
            `lemely.io.det.schemas`; `ParentLinkService.link(student_id, phone)` is
            student-initiated by phone; and at-risk **rule 1 reads the last three
            grade-bearing records across ALL subjects**, so a second subject's paper
            interleaved into a declining run stops the flag firing (cost one debug cycle).
            The 30s OTP resend cooldown means a seed script and the test that follows it
            cannot both request a challenge for the same phone without a wait.
      - [x] **c** done (26a390f) — P-03 subject detail + P-04 weaknesses, closing chunk b's
            two expected 404s. New `screens/SubjectDetail.tsx` + `screens/Weaknesses.tsx`,
            routes `children/:childId/subjects/:code` and `children/:childId/weaknesses`.
            **Zero backend files touched: 1866 tests / 89.34% cov, unchanged.** All 12
            gates green.
            **Do not reintroduce / do not "tidy" away:**
            (a) `boundaryDistance` null omits the whole panel. Never render "0 marks from" —
            null means the distance was never computed (top grade, or no threshold for the
            next grade up), not that the distance is zero.
            (b) P-04 renders the backend's ranking and never re-sorts —
            `ChildWeaknessesDTO` documents worst-accuracy-first as its own contract.
            (c) P-04's closing note names the absent "what the child is doing about it"
            signal. Do not replace it with a "sessions planned: 0" stat (D3.11) — a zero
            there reads as an accusation the data does not make.
            (d) P-03's basis sentence has singular/plural branches; both were verified.
            Verified on the live stack (throwaway seeds + specs, deleted): 2/2 green — the
            P-02→P-03→P-04 walk asserting the ranking, the absent-signal note present and
            "sessions planned" absent; plus a **separately seeded child with a reachable
            boundary** proving the populated "4 more marks for a C" panel. Both the null and
            populated boundary paths are covered. Zero serious/critical axe, zero console
            errors at 380/768/1440.
            **Fact worth not re-deriving:** `SubjectPaperDTO.marks`/`RecentPaperDTO.marks`
            are `"63/80"` — no spaces around the slash (cost one test iteration).
      - [x] **d** done (11eb8a2) — student-side parent-link management. New
            `portals/student/screens/Parents.tsx` (route `/student/parents`, nav entry
            "Your parents" + crumb) + `useParentLinks`/`useLinkParent`/`useUnlinkParent`
            in `useStudentApi.ts`. 1868 tests (1864 passed / 4 live-only skips), 89.35%
            cov (from 89.34%), `parent_repo.py` at 100%. All 12 gates green, no migration.
            **Real defect found in verification and fixed at the source:** `verify_otp`
            mints a phone-only parent with a synthesised
            `phone+20…@parents.lemely.local` email (`users.email` is NOT NULL + unique),
            and **both** `ParentRow` sites fell back to it — so a student saw that
            machine-generated string where their parent's name belongs. New
            `_parent_display_name` prefers a real name, then the **phone**, and only
            then the address. The placeholder domain is duplicated in `parent_repo.py`
            rather than imported (import-linter forbids `lemely.db` → `lemely.auth`);
            `test_placeholder_domain_matches_the_auth_services_synthesised_address` pins
            the two so `_phone_placeholder_email` cannot drift. **Verified by inversion**
            — the test fails against `display_name or email`. Do not "simplify" it back.
            **Do not reintroduce:** a generic error render for POST's 404. It means
            exactly "that parent has not signed in yet" and is the only actionable
            message on the screen; it has its own branch keyed on `ApiError.status`.
            Verified end to end on the live stack (throwaway spec, deleted) **with no
            seed script in the loop**: parent OTP-signs-in → empty state → signs out;
            student signs up → 404 message for an unknown number → links the real one and
            sees the phone, not the placeholder; parent signs back in → child present.
            Axe clean and no horizontal scroll at 380/768/1440.
            **Test-writing facts:** a deliberately-provoked 404 shows up as a browser
            console error, so clear the buffer after that step rather than weakening the
            assertion to ignore 404s; and any spec that exercises the empty state must
            use a **per-run unique phone**, or the previous run's link makes the
            single-child skip bypass the state under test.
            **Pre-existing, NOT this chunk's to fix:** the student sidebar still renders
            hardcoded `studentName`/`studentMeta` ("Maya Rahman / Year 11 - Helwan Science
            Centre") and "MR" initials from `portals/student/data.ts` — the same fiction
            P3.7 chunk b killed in the teacher sidebar, still live on the student side.
            `useProfile()` already exists and is the fix. Carried to P3.10.
            **P3.9 is now done — G-05 and P-01..P-04 are all on real data, and the link
            that makes them reachable exists.**
- [ ] doing — **P3.10** Acceptance: Playwright E2E per role, at-risk flags verified against
      seeded scenarios, plus the standing UI gate (QUALITY-BAR, axe 0 serious/critical,
      Lighthouse a11y ≥95, screenshot corpus for every new screen × state × breakpoint,
      Impeccable audit+polish, no regression vs Phase-2.5 baselines).

      **Five-chunk split (2026-08-07), one commit each. Established facts, do not re-derive:**
      - Baseline at chunk-a start: working tree clean at `fadab58`, all 12 gates green,
        1868 tests (1864 passed / 4 live-only skips) / 89.35% cov. Supabase stack UP
        (`supabase status` OK; `supabase_imgproxy_Lemely`/`supabase_pooler_Lemely` are
        stopped and that is normal — the other twelve containers are what matter).
        `node -v` = **v26.6.0**, so `npx impeccable detect` (needs 24+) is fine.
      - **Always run gates as `./scripts/check.sh`** — it already exports
        `$HOME/.local/bin` onto PATH itself (line 28), so the P3.7-era warning about
        `PATH=... ./scripts/check.sh` is obsolete; the 12-vs-9 gate split is fixed.
      - Full route inventory (from `web/src/App.tsx` + the three `portals/*/index.tsx`).
        In Phase-3 scope for the gate — **19 routes, of which `audit.mjs` covers 4**:
        covered today `/login`, `/student`, `/student/correct`, `/student/result/:paperId`;
        MISSING `/login/parent`, `/parent`, `/parent/children/:childId`,
        `.../subjects/:code`, `.../weaknesses`, `/student/parents`, `/teacher`,
        `/teacher/classes`, `/teacher/classes/:classId`, `.../analytics`,
        `/teacher/students/:studentId`, `/teacher/at-risk`, `/teacher/review`,
        `/teacher/review/:itemId`, `/teacher/quizzes`, `/teacher/quizzes/:quizId`,
        `/teacher/quizzes/:quizId/assignments/:assignmentId/results`,
        `/teacher/announcements`, `/teacher/grading`, `/teacher/schemes`.
        Out of Phase-3 scope (P4/P5 screens still on mock data — do NOT add them to the
        gate, that would be gating unbuilt work): `/student/subject/:code` is real but
        P2's, `/student/plan`, `/student/board`, `/student/onboard`, `/student/landing`,
        `/student/directions`.
      - `web/scripts/audit.mjs` is a **linear 506-line script**, not a route table: it
        hardcodes one student journey inline. Chunk b converts it to a declarative
        registry; that restructure is the work, not an afterthought.
      - Every screen verification in P3.7–P3.9 used a *throwaway* seed script deleted
        afterwards. Chunk a makes that permanent and shared — Phase 6's acceptance
        ("seeded demo accounts for all 5 roles") needs it anyway.
      - [x] **a** done — shared multi-role seed fixture `scripts/seed_e2e.py` (478 LOC) +
            `tests/test_seed_e2e.py` (25 hermetic unit tests over the pure parts). The one
            seeding path for both harnesses; all 5 roles, emitting the documented JSON
            contract on stdout (progress goes to stderr, so stdout stays machine-readable)
            and optionally to `--json-out`. 1892 tests (1888 passed / 4 live-only skips),
            89.35% cov (unchanged — the new tests cover `scripts/`, which is outside the
            measured package). All 12 gates green, no migration, zero `lemely/` files
            touched.
            **Verified against the live stack, not asserted** — the whole point of this
            chunk. Ran the seed, then queried the *real* API with the seeded tokens:
            `GET /api/teacher/at-risk` reproduces exactly `declining→[declining_trend]`,
            `inactive→[inactive]`, `control→[]`, `correctedPaper→[]`, and
            `GET /api/parent/children` returns exactly the one linked child. Backend for
            that check is `scripts/e2e_server.py` on port 8000 (**not**
            `uvicorn lemely.web.app:app` — there is no module-level `app` attribute; that
            costs a cycle to rediscover).
            **`ensure_supabase_env()` added here (the script's only non-obvious part):**
            `LEMELY_SUPABASE__SERVICE_ROLE_KEY`/`__ANON_KEY` are per-stack secrets that
            live in neither `lemely.toml` nor `.env`, so running the seed bare died on
            `AuthError: Supabase service-role key is not configured` — which reads as a
            broken script, not "export two variables". It now resolves them from
            `supabase status -o json` exactly as `web/scripts/audit.mjs::resolveSupabaseEnv`
            already does, via `shutil.which("supabase", path=~/.local/bin:$PATH)`. An
            already-exported value always wins. Verified by running with both vars
            explicitly unset. **Do not "simplify" this to a bare `["supabase", ...]`** —
            that is ruff S607, and the `which` lookup is also what makes the missing-CLI
            case a clear message instead of an `OSError`.
            **Ruff trap worth one line:** a comment beginning with the four letters `noqa`
            is parsed by ruff as a *blanket* directive (RUF100 "unused blanket noqa"), even
            when it is plain prose explaining an adjacent real `# noqa: S603`. Word such
            comments to start some other way.
            Scenario facts already encoded as module constants — do not fork them:
            declining is 3 same-subject papers 82→68→55 (rule 1 reads the last three
            grade-bearing records across ALL subjects, so a second subject interleaved
            stops the flag firing, per P3.9b); inactive is one paper ≥14 days old; control
            is a recent improving run that must stay unflagged. Rule 2 (predicted ≥2 below
            target) is **not exercised and not faked** — no target-grade column until P4
            (D3.3). Every attempt is `origin=past_paper` (D3.9). Per-run `runTag`
            namespaces every email + the parent phone, so reruns never collide and there
            is deliberately no teardown. One OTP challenge is requested per run and the
            token it yields is returned — a consumer must reuse it rather than starting a
            second challenge for the same phone (30s cooldown).
      - [x] **b** done — `audit.mjs` rebuilt from a linear 4-route journey into a
            declarative **21-route** `ROUTE_REGISTRY` (D3.17), plus every defect it
            newly found. 1892 tests (1888 passed / 4 live-only skips), 89.35% cov
            (unchanged — zero `lemely/` files touched). All 12 gates green, 0 skipped.
            **Final measurement, all 21 routes: zero axe violations at ANY severity**
            (not just zero serious/critical), Lighthouse accessibility **100** on every
            route, performance floor 86 (`/login`), **0** console errors, **0**
            horizontal-scroll violations.
            `check_ui_gates.py` now also gates console errors and horizontal scroll,
            and treats a *missing* summary file as "not checked" (a failure), never as
            "clean".
            **Five real defects found and fixed — three of them in product code that
            every previous gate run had passed over:**
            (a) `--t3` was below AA at 4.48:1 against `--md-surface-container-highest`;
            mix moved `outline 65/35` → `35/65` (#76615e → #67534f), a token fix, not a
            per-screen retrofit. **The 4.36:1 figure P3.8c reported was never
            root-caused** and `index.css`'s claim that axe measures glyph
            rasterization was wrong — corrected in-file and in D3.17, not explained
            away.
            (b) `/student/result/:paperId` overflowed 380px by 10px: the student header
            is one non-wrapping flex row whose fixed items summed to 391px. Crumb now
            `min-w-0 truncate`, padding tightens below 640px, streak pill hides there
            (same treatment the search affordance already had at 1080px).
            (c) `/teacher/grading` and `/teacher/schemes` had **no `<h1>` at all**
            (`page-has-heading-one`) — found *only* because this chunk stopped
            excluding them.
            (d) `/login/parent` was unreachable in-harness: `localStorage` is
            per-origin, so the student journey's session made `LoginRoute` redirect it
            away. Each session key now gets its own **incognito browser context**.
            (e) 13 `SecurityError` page errors were the harness's own —
            `evaluateOnNewDocument` fired on the `about:blank` Lighthouse navigates
            through. The injection now skips opaque origins explicitly (not a bare
            try/catch, which would also hide a real storage failure).
            **Do not reintroduce / do not "tidy" away:**
            (i) A route that cannot be reached is collected and the run **continues**,
            failing non-zero at the end. Fail-fast costs one ~11-minute run per broken
            route; this pass found T-02's wrong readiness predicate (`"Create class"`
            is the submit button *inside* the create form — the loaded view shows
            `"+ New class"`) and defect (e) together.
            (ii) The exclusion rule is now "the seed cannot reach the route at all",
            **not** "no populated fixture". `/teacher/grading` + `/teacher/schemes` are
            audited empty — which is exactly how (c) surfaced. Only
            `/teacher/review/:itemId` and `/teacher/quizzes/:quizId` (+ results) remain
            out (seed creates no review item and no quiz, so both 404). P4/P5 mock-data
            screens stay out deliberately.
            (iii) `checkNoHorizontalScroll` names the offending elements, widest
            overhang first, and only walks the DOM once a violation is known. Defect
            (b) was pinpointed to `<button>"Correct a paper" w=138 left=253` in one
            run; without it the report is "something is 10px too wide".
            Ready-predicate rule worth not re-deriving: never wait on text the sidebar
            nav or an `sr-only` pending-state `h1` also renders — wait on a
            **loaded-only** eyebrow (`"Grading console"`, `"Library"`,
            `"Flagged by trajectory"`, `"core recurring task"`).
            Left alone deliberately: `index.css:663`'s 6px radius is off the DESIGN.md
            scale (impeccable hook), pre-existing and untouched by this diff; and the
            student header's `"24 day streak"` is still hardcoded — same fiction class
            as carried item (d), which is chunk c's.
      - [x] **c** done — token retrofit + the twMerge defect it uncovered (D3.18).
            **598 literals replaced**; teacher portal, shared `components/` and the
            student shell are now at **zero** `text-[Npx]`/`rounded-[Npx]`/`oklch()`.
            1892 tests (1888 passed / 4 live-only skips), 89.35% cov — both **unchanged**,
            and necessarily so: zero `lemely/` files touched (diff is `web/`, `scripts/`,
            `BUILD/` only). **All 13 gates green, 0 skipped** (12 + the new
            `design-tokens` gate). Post-retrofit audit over all 21 routes: **0 axe
            violations at ANY severity**, Lighthouse a11y **100** on every route, perf
            floor 85 (`/login`), **0** console errors, **0** horizontal-scroll violations.

            **The inherited premise was wrong — do not re-derive it.** P3.7 chunk b's
            carried item (b) said "the teacher portal's *five screens*… (P2.5.3
            retrofitted only the student screens)". Measured: it is **18 teacher files /
            482 font-size literals** + 57 radii + 34 `oklch()`. The **parent portal and
            `portals/auth/` were already clean (0)** — nothing to retrofit there, so the
            chunk title's "+ parent" is satisfied by the teacher half alone. And P2.5.3
            did **not** fail: every student screen in scope then is clean
            (`Overview`/`CorrectPaper`/`PaperResult`, plus P3.9's `Parents`).

            **Real defect found and fixed at the source — this is the important part.**
            D2.9 found that a `text-`-prefixed custom class falls into tailwind-merge's
            *text-color* group so `cn()` silently drops it or the colour beside it, and
            fixed only the button rungs by renaming them `.btn-text*`. **The composite
            type classes were left in the trap and the bug was live**: verified
            empirically, `twMerge("text-display-md text-t1")` returned `"text-t1"` — the
            font-size, family and line-height dropped entirely. **Five shared C-*
            components hit exactly that shape** (`trend-sparkline` ×2, `boundary-bar`,
            `confidence-indicator`, `paper-identity`), so it shipped on every student and
            parent screen composing them. **No gate in this build can see it** — a
            dropped type class degrades to *inherited* type: not a type error, lint
            error, console error, axe violation or overflow. `lib/utils.ts` now builds
            `cn()` from `extendTailwindMerge` registering every custom `text-*` class as
            a font-size. **D2.9's rule ("never name a custom class `text-anything`") is
            superseded by "register it"** — `.btn-text*` keep their names only because
            `button.tsx`'s cva variants depend on them.

            **Token layer gained (all traceable, none invented):** `--fs-display-sm: 24px`
            + `--fs-display-xs: 19px` — DESIGN.md's `typography:` jumps 15px → 30px with
            nothing between, which is *why* 18 screens invented 19/20/22/24/26/34px ad
            hoc; the two new rungs continue the table's own ~1.25 ratio. Size-only
            `--text-dense{,-sm,-lg}` (aliasing the existing `--fs-button-text*`) and
            `--text-md` (aliasing `--fs-body-lg`) exist because those numbers were only
            reachable through *composite* classes that also force weight/leading/family.
            Per-portal `--accent-subtle-on` fills a real gap (badges on `bg-accent-subtle`
            had a hand-picked foreground and no defined on-colour).

            **Do not reintroduce / do not "tidy" away:**
            (a) `web/scripts/check-design-tokens.mjs`, wired into `check.sh` as the
            `design-tokens` gate. Both invariants it guards fail *silently*, and `web/`
            still has no unit-test runner. It asserts every registered class survives
            `cn()` beside a colour **in both orders**, that two sizes still collapse, that
            `lib/utils.ts` and `index.css` agree in **both** directions, and that no
            arbitrary literal reappeared. **Verified by inversion** (fails against an
            unregistered class and against a reintroduced `text-[13px]`) — not assumed.
            If a runner lands in chunk e, move these checks into it verbatim.
            (b) Adopting a composite type class means adopting its line-height: the class
            is **unlayered CSS and beats any `leading-*` utility beside it**, so the
            conversion drops the ad-hoc `leading-none`/`leading-[1.08]` overrides that
            could never have won. Size and leading travel together — that is what a scale
            is. Re-adding a `leading-*` next to a `text-display-*` does nothing.
            (c) The 34 teacher `oklch()` literals were the **student** palette (hue
            78/60/68 terracotta) hardcoded into a teal portal. They now follow
            `[data-portal]`.

            **Item (d) and two of the same class beside it, all removed:** the student
            sidebar's "Maya Rahman / Year 11 - Helwan Science Centre" + "MR" now render
            the real caller via `useProfile()` (the twin of the teacher fiction P3.7
            chunk b killed). The header's `<span>`-as-search-box (no handler, no search
            endpoint anywhere) is gone, and so is the "24 day streak" pill. **The streak
            was deliberately NOT wired to real data**: the only streak-shaped field is
            `StandingsDTO.streakDays` = `len({distinct dates})` — active days, *not*
            consecutive. Wiring it swaps a hardcoded lie for a mislabelled one. **Flagged
            for P5, which owns streaks: `streakDays` is misnamed at the source
            (`student.py:904`) and `Standings.tsx` renders it as a streak too.**

            **Measured debt left, with numbers so the report need not hand-wave (141
            literals, 6 student screens):** `Subject.tsx` **37 — the one genuine gap**, a
            real API-backed P2 screen (`useSubject`) P2.5.3 never reached and chunk b
            excluded from the registry as "real but P2's". The other 104 are in the five
            P4/P5 mock surfaces `Landing` 30 / `Directions` 19 / `StudyPlan` 15 /
            `Standings` 14 / `Onboarding` 13 — retrofitting unbuilt work is the same
            mistake as gating it. Also untouched deliberately: **spacing** literals
            (`p-[34px]`, `w-[246px]`, …) portal-wide — DESIGN.md's `spacing:` block covers
            container padding/gutters but no sidebar or max-width dimensions, so that is a
            scale decision, not a substitution. `Avatar.tsx`'s `accent`/`err`/`warn` tones
            are **dead** (every `<Avatar>` renders `neutral`; the `tone="warn"` hits
            belong to `Chip`) — documented in-file, not pruned, since deleting unused
            public variants is a simplification pass.
      - [x] **d** done (92056dc) — Playwright E2E per role + at-risk flags asserted against
            chunk a's seeded scenarios (the phase's **named acceptance criterion**). Five new
            specs; the suite is now **18 tests, 18 passed**. Zero `lemely/` files touched:
            1892 tests (1888 passed / 4 live-only skips), 89.35% cov — both **unchanged**, as
            they must be. **All 13 gates green, 0 skipped.**
            **Seeding is a Playwright `globalSetup`** (`web/e2e/global-setup.ts`) running
            chunk a's `scripts/seed_e2e.py` once per run into
            `<reportDir()>/e2e-seed.json`; specs read it back via `readSeed()`
            (`web/e2e/seed.ts`, which also carries `injectSession`, mirroring
            `audit.mjs::injectSession`). **This cannot be a cached promise in a helper** —
            Playwright forks a worker process per test file even at `workers: 1`, so module
            state is not shared and such a helper would silently re-seed per file instead of
            memoizing. Do not "simplify" it back.
            **Verified by inversion, not assumed:** expecting the `control` student to be
            present fails *both* the API assertion and the T-06 assertion — the control
            student really is absent from both, so the at-risk assertions are load-bearing
            rather than vacuously true.
            **Do not reintroduce / do not "tidy" away:**
            (a) The parent OTP spec uses a **fresh, never-challenged phone**. The seeded
            parent's own number already spent its one challenge inside the seed script and
            the 30s resend cooldown makes a second request a real 429 — this is not a flake
            to race, and reusing the seeded number would make the spec time-dependent.
            (b) `rbac.spec.ts`'s school_admin case asserts the teacher's own token **does**
            see the class. Without that second half, an empty result proves nothing — a
            broken route or a broken seed would pass just as well.
            (c) `watchConsole` now lives in `e2e/console-errors.ts` (extracted from
            `screenshots.spec.ts`, its only copy) — a sixth inline copy is how the
            `initialsOf`/`downloadCsv` duplication started.
            (d) The teacher journey logs in through the **real UI**; session injection is for
            the other roles' routes only.
            Known, honest: `_student_delta`'s "Trend" column reads "No prior paper" for the
            declining student and the spec asserts exactly that — `compare_performance`
            matches on subject_code + paper_number, and the seed's three attempts are paper
            numbers 1/2/3, so there is no same-paper prior. The 27pp decline is a separate,
            real signal asserted through the at-risk flag's own evidence sentence.
            **Noticed, NOT this chunk's to fix (carried to the phase report):** the teacher
            Overview greets `"Good morning."` unconditionally, as the student Overview does
            with `"Good afternoon,"` — hardcoded, not time-aware. Cosmetic, but the same
            "hardcoded value masquerading as a feature" class P3.7b and P3.10c each removed
            once. Not fixed here (would be a product change inside a test chunk).
      - [ ] **e** todo — screenshot corpus for every new screen × state × breakpoint
            re-baselined into `reports/phase-3/`, contact sheet, regression check against
            the Phase-2.5 baselines, and the item-(c) frontend-runner decision.

      Carried in from P3.7 chunk b, both genuinely P3.10-shaped:
      (a) `web/scripts/audit.mjs` is still scoped to the 4 *student* routes (D2.10). Every
      teacher/parent route added in P3.7–P3.9 needs adding here, or the axe/Lighthouse/
      screenshot gate is vacuous for all of them — it passes by never looking.
      **This is now evidenced, not theoretical:** P3.8 chunk c measured `text-t3` at
      10-13px as **4.36:1**, under WCAG AA's 4.5:1, on the default surface. Every teacher
      screen except chunk c's/chunk d's uses `text-t3` for exactly that caption text. The
      gate has never seen it. Fixing it is either a `--t3` token change or a per-screen
      retrofit — decide here, and do the retrofit in the same pass as (b).
      (b) The teacher portal's five screens use arbitrary px/oklch literals instead of the
      DESIGN.md token scale (P2.5.3 retrofitted only the student screens). Decide: retrofit
      them, or record it as accepted debt in the phase report. Do not leave it unstated.
      (c) `web/` has no frontend test runner configured. Either stand one up or state
      plainly in the report that frontend behaviour is covered by Playwright E2E only.
      Carried in from P3.9:
      (d) The **student** sidebar still renders hardcoded `studentName`/`studentMeta`
      ("Maya Rahman / Year 11 - Helwan Science Centre") and "MR" initials from
      `portals/student/data.ts` — the identical fiction P3.7 chunk b removed from the
      teacher sidebar, never done for the student side. `useProfile()` already exists.
      (e) Item (a) is now **three times** evidenced: P3.8c's `text-t3` contrast finding,
      and two real serious axe violations P3.9 found only by hand-verifying (icon-only
      `button-name` on the parent shell below 640px). Every teacher AND parent route is
      still outside `audit.mjs`'s four student routes; the gate passes by never looking.
      P3.9 added six routes (`/login/parent`, `/parent`, `/parent/children/:id`,
      `.../subjects/:code`, `.../weaknesses`, `/student/parents`).
- [ ] **blocked** — **INBOX-2026-08-07** Real past-paper accuracy fixtures (two genuine solved
      0625 scripts, ground truth 34/40 and 66/80). **Blocked on the human by the directive's
      own item 6:** the matching official mark schemes (`0625_s23_ms_22`, `0625_w24_ms_41`)
      are not in the repo and **no code path can obtain them** — `resolve_mark_scheme`
      (`lemely/web/routers/student.py:588`) reads only a sibling `mark_scheme.pdf` or a parsed
      JSON in `outputs/schemes/` (which is empty); Phase 2's scraper fetches *grade boundaries*,
      not schemes. Blocks the MCQ paper too — `correct_mcq_answers` is deterministic but still
      needs the official answer key. Full detail, including what I deliberately did **not** do
      (no reconstructed scheme, no back-derived per-question marks, no mirror scrape, $0.00
      spent), in `BUILD/BLOCKERS.md` **B1**. Unblocks the moment the two scheme PDFs land in
      `Sources/Physics/MarkingSchemes/`. The fixtures are gitignored meanwhile (real student
      handwriting; reversible in one line, unlike committing it).
      **Do not start this task until B1 is resolved, and do not resolve it by inventing a
      scheme.**
- [ ] todo — **P3.11** Phase-3 report, merge to develop, push, update PR #3, ntfy.


## Session journal
See `BUILD/JOURNAL.md` for the dated 3-6 line entries; decisions and rationale live in
`BUILD/DECISIONS.md` (D0.x/D1.x/D2.x). Superseded per-task narrative for Phases 0-2 has been
pruned from this file per MISSION §8b now that their reports are committed — see the git
history of this file, or the phase REPORT.md files, if the detail is ever needed again.
