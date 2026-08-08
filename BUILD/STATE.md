# BUILD STATE — single source of truth

status: RUNNING            # RUNNING | COMPLETE | HALTED
current_phase: 4            # Phase 3 complete, merged (49d9750) and reported; Phase 4 not started
last_updated: 2026-08-08T04:15:00Z
gemini_spend_usd: 0.1612

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
- [x] done — (D1.6) Teacher per-tenant ownership (own-classes-only). Closed across P3.1
      (`ClassService` replaced the implicit "all students are one cohort" endpoints) and
      P3.3 (`/api/teacher/overview` stopped enumerating every student in the store; pinned
      by a two-teacher disjoint-class regression test). Row-level ownership is now real.

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

## Phase 3 — Teacher + Parent surfaces — DONE (2026-08-07)
Real class model + teacher tenancy closing the last cross-tenant leak (P3.1, D3.1), the
at-risk flagging engine (P3.2, D3.3), teacher analytics T-04/T-05/T-06 (P3.3, D3.4), review
queue override-and-annotate + evidence-scoped acknowledgement (P3.4/P3.4b, D3.5), the quiz
builder end to end — bank, builder, assignment, student take/submit, auto-marking through the
*existing* engine, class results (P3.5, D3.6–D3.10, design fixed in `docs/quiz-model.md`),
parent portal backend + notification preferences (P3.6, D3.11), sixteen frontend screens
across three portals all on real data (P3.7 T-01..T-06, P3.8 T-07..T-10 + T-12 + the
announcements backend, P3.9 G-05 + P-01..P-04), and the acceptance/UI-gate pass that turned
`audit.mjs` from a 4-route single-journey script into a 24-route/34-state registry
(P3.10, D3.17/D3.18/D3.20). Plus the INBOX real-past-paper accuracy directive (D3.21) and the
MCQ integrity guard (D3.19). Blockers B1/B2/B3 all raised and resolved.
**1939 tests (1933 passed / 6 skipped / 0 failed) / 89.42% cov** (from develop's 609 /
85.54%); **all 13 gates green, 0 skipped**; 5 additive migrations, `alembic check` clean both
directions; 24 routes / 34 states audited with zero axe violations at any severity, zero
console errors, zero horizontal-scroll violations, Lighthouse a11y floor 96. Merged to develop
(49d9750), pushed. PR #3 updated (title "Phases 0–3"; its body had never actually carried a
Phase-2.5 section despite that phase's STATE line claiming so — added in the same edit), NOT
merged. Report: `reports/phase-3/REPORT.md`. Gemini cumulative spend **$0.1586 / $8.00**.

### Honest limitations carried forward from Phase 3 (must appear in DELIVERY.md, not silently resolved)
Full text in `reports/phase-3/REPORT.md` §7. The ones that change what a later phase may
assume:
- **The question bank is empty and corpus growth cannot change that (D3.7).** A mark scheme
  holds marking points; the question *stem* lives in the question paper and no stem extractor
  exists. This is a **P4 prerequisite**, not an assumption — do not re-run the measurement.
- ~~**At-risk rule 2 cannot fire until P4 supplies target grades (D3.3)**~~ — **CLOSED by P4.3**
  (D4.5). Targets are real and per-subject, the rule fires, and `below_target` is now in the T-06
  reason filter. The *not evaluable* state survives and got stricter, not weaker.
- **Teacher-route Lighthouse performance floors at 67** (`teacher-quiz-detail`). MISSION §11's
  ≥80 floor covers the student routes (met, floor 82) and never covered these.
- **Lighthouse runs on `default` states only**; axe runs on all 34 (deliberate, D3.17).
- **`web/e2e/` + `playwright.config.ts` are in no tsconfig `include`** — the most expensive
  gate has never been typechecked (D3.20).
- **Students cannot see announcements**; `notification_preferences` is written and read by
  nothing. Both are **P5's**, and P5 must not assume Phase 3 left it a helper.
- **Paper 22 was confidently wrong (D3.21):** all 40 marks at confidence 1.0, zero review
  flags, 3 marks of pure vision/transcription error. Propagating extraction confidence into
  per-question confidence on the deterministic MCQ path changes the marking contract and was
  deliberately not patched at phase end.
- **Phase 2's synthetic-golden-set accuracy gate is unchanged** (83.8% vs ≥95%). The
  real-paper measurement is on top of it, not a replacement.

### Task checklist
- [x] done — P3.1 / P3.1b / P3.2 / P3.3 / P3.4 / P3.4b / P3.5 (chunks C,A,G,B,D,E,F1,F2) /
      P3.6 (a,b) / P3.7 (a–d) / P3.8 (a–d) / P3.9 (a–d) / P3.10 (a–e) / P3.10-B3 /
      INBOX-2026-08-07-ACC. Per-task rationale is pruned per MISSION §8b now that the report
      is committed and merged — see `reports/phase-3/REPORT.md`, `BUILD/DECISIONS.md`
      (D3.1–D3.21), `BUILD/BLOCKERS.md` (B1–B3), or this file's git history.
- [x] done — **P3.11** Phase-3 report, merge to develop, push, update PR #3, ntfy.

## Phase 4 — Content generation + study plans — IN PROGRESS (started 2026-08-07)
Branch: `feature/phase-4-content-study-plans`. See MISSION §4 + UI spec §4.2 (S-01..S-05),
§4.5 (S-20..S-25). Read the Phase-3 limitations above before planning: the question-stem
extractor and the target-grade column are both P4 prerequisites that P3 established, not
open questions.

**What Phase 3 already left that P4 composes rather than rebuilds:** `QuestionBank` +
`QuestionBankService` (`lemely/db/question_bank_repo.py`, incl. `survey_past_paper_questions`),
the quiz take/submit/auto-mark path (`quiz_taking_repo`/`quiz_marking_repo`), `core/difficulty.py`,
`core/generation.py` (`GeneratedQuestion`), `io/question_generation.py`, `core/study_plan.py`
(a naive proportional scheduler) + `io/study_plan_ai.py` narration, and the `StudyPlan.tsx`
screen. The placement test and practice sets are quiz-shaped: reuse that engine, do not fork it.

### Task checklist
- [x] done — **P4.1** Question-stem extractor (D4.1) + all five content defects closed (D4.2).
      `lemely/io/det/question_papers.py` (deterministic, zero Gemini) + the new shared
      `lemely/io/det/symbols.py` (Adobe SymbolEncoding recovery, also wired into `tables.py`
      so the **marking engine** stops reading mangled mark points) + `lemely/io/question_papers.py`
      pairing/writer + `lemely question-bank ingest-question-papers`.
      **Orchestrator-measured yield (0625): 72 papers → 2018 leaves → 273 banked**, 654
      figure/unmapped-excluded, re-ingest idempotent. Bank is no longer empty — D3.7 closed.
      Yield fell 298 → 273 **deliberately**: leaves with unmappable glyphs are now excluded
      rather than banked corrupt. All six quality counters are now 0 (see D4.2 table).
      **Ceiling worth knowing:** only 32/72 0625 mark schemes parse deterministically, and a
      stem needs its scheme to be bankable — mark-scheme parse coverage, not stem extraction,
      is what caps bank size. Improving the det mark-scheme parser is the highest-leverage
      way to grow the bank.
      Re-measure any time with `/tmp/p41_quality.py` (purge `question_bank where
      source='past_paper'` first — ingest is idempotent and will skip).
      **Also fixed here (D4.3):** the test suite could make *billed* Gemini calls when a key
      was exported — `tests/conftest.py` now blocks real client construction suite-wide.
- [x] done — **P4.2** Syllabus topic taxonomy + classification of bank questions (D4.4).
      `lemely/data/syllabus_topics.json` (topic/subtopic **codes and names transcribed from
      the three official CAIE syllabus PDFs**, not from memory — 0625 2023-25 `595430`,
      0580 2025-27 `662466`, 0606 2025-27 `662470`; matching vocabulary is authored and the
      file says so) + `lemely/core/topics.py` (pure classifier) + `lemely/io/syllabus_topics.py`
      (loader) + `classify_bank_topics` in `question_bank_repo.py` + `lemely question-bank
      classify-topics [--subject|--reclassify|--dry-run]`. Deterministic, **$0.00, zero Gemini**.
      **Measured: 245/273 (89.7%) classified, 211/273 (77.3%) written** — 108 high, 103 medium,
      across 29 distinct topics spanning all 6 physics topics. **D3.7's empty-topic gap is closed.**
      The 34 `low`-band matches are counted and **discarded**: `question_bank.topic` has no
      companion confidence column, so writing them would launder a guess into apparent fact
      (hand-check found e.g. an alpha/beta/gamma question labelled "4.2 Electrical quantities").
      Label format is `"<code> <name>"`, e.g. `"4.3 Electric circuits"`.
      Two real defects the corpus exposed and one measurement worth keeping: hyphens never
      matched (`double-insulated` vs `double insulated`); including `mcq_options` in the
      classified text moved coverage 78.8% → 89.4%.
      **P4.4 MUST also fill the marking side.** `CorrectedQuestion.topic` comes from
      `topic_hint`, which is `None` on **all 637 questions across all 33** parsed 0625 schemes
      — so the weakness engine reports no topics for real papers, and **practice-targets-weakness
      (P4.5) does not join up until both sides use this vocabulary.** Not done in P4.2 because
      `core.topics` cannot import the `io` loader without a layering violation; the fill belongs
      at the db/io boundary where a `CorrectionResult` is persisted. See D4.4 §6.
- [x] done — **P4.3** Student profile + onboarding data model (D4.5). Migration **0009**, four
      additive tables (`student_profiles`, `student_subject_enrolments`,
      `student_enrolment_papers`, `student_confidence_ratings`) + `QualificationLevel` enum +
      `lemely/db/student_profile_repo.py` + student-only onboarding routes on `/api/me`.
      Every S-02-skippable field is nullable: a skipped answer is `NULL`, never a defaulted
      sentinel that would read back as an answer the student gave. Confidence ratings are keyed
      on the **P4.2 topic-label vocabulary**, so questionnaire/bank/weakness engine share one
      language. Commits `189a292` (schema+service+routes) and `99bf086` (chunk C).
      **At-risk rule 2 is live — it has never once been able to fire before now.** `assess_at_risk`
      took a scalar `target_grade`; it now takes `targets: Mapping[str, str]` (subject code →
      grade) and resolves against the subject of the latest grade-bearing record. That keying is
      the point: a scalar would have compared a physics paper against a maths target the moment a
      student enrolled in two subjects — a false at-risk flag on a teacher's dashboard. All nine
      call sites (teacher×5, classes×2, parent×2) pass real targets via
      `StudentProfileService.target_grades_for{,_many}`; the multi-student routes use the bulk
      form so a class overview is not N+1. `below_target` added to the T-06 reason filter and
      given a real rendering branch in the parent `ChildOverview`.
      **The tri-state got sharper, not looser:** `NOT_EVALUABLE` now also covers "targets supplied
      but none for this student's subject" — an enrolled student with no target there is
      *not checked*, never *cleared*. Orchestrator-verified by direct execution, not from the
      subagent's report: no-targets / empty / wrong-subject all → `not_evaluable`; right-subject
      2 grades below → `fired`; right-subject 1 grade below → `not_fired`.
      All 13 gates green, 0 skipped; `alembic check` clean upgrade **and** downgrade; coverage
      **89.57%** (pre-chunk baseline 89.56%, Phase-3 89.42% — flat, no regression). $0.00 Gemini.
      **Stale docstring left for whoever owns E2E next:** `web/e2e/at-risk-flags.spec.ts:21` still
      says rule 2 "cannot fire in Phase 3". Seeding a real below-target scenario in
      `scripts/seed_e2e.py` is a P4.11 job, not silently done here.
- [x] done — **P4.4** Placement test backend (chunks A, B-1, B-2, B-3, B-4 — D4.6/D4.7/D4.8/D4.9): ~15-min per-subject assembly from the bank across
      topics, serve/resume/submit, mark through the existing engine, initialise weakness profile.
      **Includes the marking-side topic fill carried over from P4.2 (D4.4 §6)** — classify
      `CorrectedQuestion.topic` at the db/io persistence boundary when `topic_hint` is absent,
      so weakness topics and bank topics share one vocabulary. Re-verify the accuracy harness
      (MISSION §6 gate 5) since it touches the marking output.
      **Chunk plan (2026-08-08):**
      - [x] chunk A — **done** — marking-side topic fill (D4.4 §6, now **D4.7**).
        `fill_correction_topics` + `_resolve_topic_labels` in `lemely/db/attempt_repo.py`,
        called from `grade_paper` and `QuizMarkingService.mark_submission` **before**
        `summarize_weaknesses` (the flagged trap — filling only in `_persist` would fix the
        column and leave the grouping on `"unknown"`). Deterministic, $0.00, zero Gemini.
        **Orchestrator-measured on the real corpus, not from a subagent report:** the first
        implementation classified each node's own fields only and reached **108/1329 marked
        nodes (8.1%)** — two structural defects found by measuring: it ignored the `parts`
        subtree (parents carry no prose of their own) and had no ancestor inheritance.
        Both fixed → **428 nodes (32.2%) across 26 topics spanning all six 0625 topics**.
        **Do not re-measure and do not read the 32.2% as a shortfall:** 520 of the 1329 nodes
        are MCQ and a CAIE MCQ scheme carries only the answer letter, so they are
        unclassifiable *from a mark scheme* at any depth (D3.7's wall). The reachable
        population is the 809 non-MCQ nodes and the fill reaches **52.9%** of them. Each rule
        verified by inversion. 5 new tests + the 4 already written; 21/21 in
        `tests/test_attempt_repo.py`.
      - [x] chunk B-1 — **done** (`3c765e3`) — the ownership schema. Details below, kept
        because B-2/B-3 build directly on them.
      - [x] chunk B-2 — **done** (`fce3231`) — the two `quiz_taking_repo` sites D4.6 §3 named.
        `_load_enrolled` → `_load_permitted` (two-branch predicate on whichever target column
        the XOR CHECK left populated; exactly two returns, no fallthrough), `get_take` resolves
        `SchoolClass`/`User` conditionally, and `QuizTakeHeader`/`AssignedQuizRow`
        `class_name`/`teacher_name` + their wire DTOs became `str | None` — S-04 renders the
        absence, not `_display_name`'s empty string. 11 tests; the 239 existing quiz tests
        unchanged. **The owning student can now take a class-less assignment at all**, which
        no code path allowed before.
      - [x] chunk B-3 — **done** (`5809814` + the paper-link commit) — the assembler and its data.
        `lemely/data/paper_timing.json` (12 papers × `duration_minutes`/`total_marks`,
        transcribed from the **Assessment overview** of the same three syllabus PDFs D4.4
        cites; **no rate is stored** — `minutes_per_mark` is division on read, and a test
        pins the file's key set so a derived figure cannot creep in), `lemely/io/paper_timing.py`
        (loader; excludes 0625 practical papers 5/6 from placement — apparatus), and
        `lemely/core/placement.py` (pure: breadth-first select, 15-min target / 18 ceiling /
        12 floor, `Unavailable` with a machine-readable reason). 20 tests.
        **Three real defects the orchestrator found by measuring against the live bank, not
        from a report — do not re-derive these:**
        1. **All 273 banked questions had `paper_id IS NULL`**, and `papers`/`subjects` were
           both empty. P4.1 never created `Paper` rows (its own docstring says so) and nothing
           needed the link until placement made it load-bearing. Placement returned
           `no_eligible_questions` for **0625 too**. Fixed by
           `QuestionBankService.link_past_paper_rows` + `lemely question-bank link-papers`:
           the identity is *parsed* from `source_question_id` (`"0625_s23_qp_11#22"` → the
           source PDF's filename) by the same parser the ingest used, never inferred; the
           `subjects.name` comes from the bundled taxonomy, never invented to satisfy the FK.
           **Measured: 273 considered → 273 linked, 26 papers, 1 subject, 0 unparseable**;
           re-run considers 0. Backfill already applied to the local DB.
        2. **Breadth counted subtopics as topics.** D4.2's classifier writes whichever level
           it matched, so the bank mixes `"3 Waves"` with `"1.2 Motion"`. First real assembly
           reported "13 topics" for a set with **nine of 13 questions under physics topic 1**.
           Breadth is now measured on the top-level code (`_syllabus_group`), depth on the full
           label, and `Assembly` carries `syllabus_topic_count` separately from `len(topics)`.
        3. The greedy fill stopped dead on the 15-minute target even when that left it below
           the 6-question floor, then refused a set one question short of viable.
        **Measured after all three fixes (the number to quote, not re-derive): 0625 assembles
        9 questions / 15.2 min / all 6 physics topics / 2 difficulty bands. 0580 and 0606
        return `no_questions` — correct, they have zero ingested questions (D4.6 §5).**
      - [x] chunk B-4 — **done** (D4.9) — the DB service + the three routes.
        `lemely/db/placement_repo.py` (`PlacementService`: availability / create / result),
        `lemely/web/routers/placement.py` + `schemas_placement.py`, wired in `app.py`/`deps.py`.
        Take/resume/submit are the **existing** `/api/student/quizzes/...` endpoints — that
        reuse is the whole point and no parallel set was added. `core/study.py::PlacementResult`
        deleted per D4.6 §6. No migration (0010 already covers it). $0.00 Gemini.
        **One real defect the orchestrator found by reading against D4.6 §5, not from the
        subagent's report — do not re-derive:** the first pass ignored the
        `student_enrolment_papers` clause entirely, so a 0625 **Core** student (papers 1/3)
        would have been assembled from **Extended** questions (2/4) — every topic in that
        sample reporting a weakness the student does not have, and P4.7 builds the study plan
        out of exactly those `WeaknessRecord` rows. Invisible to the suite, because the seeded
        bank is single-paper. Fixed by narrowing the **timings** mapping (so `assemble` keeps
        being the one site that decides "ineligible"), with the empty case deliberately
        **not** a restriction: every S-02 field is skippable (D4.5), so no rows means "not
        answered", never "sits no papers". 4 tests, each verified by its inverse.
        **Live-bank measurement, matching D4.8 exactly:** 0625 → available, 9 questions,
        **6 syllabus topics** (`syllabus_topic_count`, not `len(topics)`≈13), 15.19 min;
        0580/0606 → `no_questions`.
        **2121 tests / 6 skipped / 0 failed / 89.68% cov** (P4.3 baseline 89.57%); all 13
        gates green, 0 skipped.
      - chunk B (superseded planning note, kept for the rationale) — per D4.6. **Unblocked:**
        the schema fork is decided and **B-1 (the schema half) is landed** — migration
        **0010**, `QuizKind` enum, `quizzes.student_id` + `kind`, `quiz_assignments.student_id`,
        both XOR CHECKs, `ck_quizzes_kind_owner`, and the partial unique index. `alembic check`
        clean **both** directions. `tests/test_placement_quiz_ownership.py` (8 tests) pins the
        DB invariants *and* the D4.6 §3 fail-closed reads (a placement quiz is invisible to
        `list_quizzes`, 403s on `get_quiz`, and is absent from `list_assigned`).
        **Making `teacher_id` nullable produced exactly 5 mypy errors, all on teacher-scoped
        paths D4.6 §3 predicted** — fixed with explicit narrowing, not casts: `list_assignments`
        now positively skips student-targeted rows, `assignment_results` 404s a self-assignment
        (no probe leak), `_to_quiz_row` raises on a NULL teacher owner as an invariant.
        **Still to do in chunk B (B-2):** the two `quiz_taking_repo` sites D4.6 §3 named —
        `_load_enrolled`→`_load_permitted` and `get_take`'s unconditional
        `session.get(SchoolClass, …)`/`session.get(User, …)`, which now receive `None`; plus
        `QuizTakeHeader.class_name`/`.teacher_name` and the same two on `AssignedQuizRow`
        becoming `str | None` (S-04 must *render the absence*, not `_display_name`'s empty
        string). Then assembly/serve/resume/submit and the availability endpoint.
        **Do not re-derive the availability answer:** 0625 only; 0580/0606 have zero ingested
        questions, so the honest `not available` path with a machine-readable `reason` is
        required behaviour, not a gap to code around (D4.6 §5).
      - Assembly constraint already known, do not re-measure: the 0625 bank is 273 rows / 211
        topic-labelled (D4.4), and **0580/0606 have zero ingested questions** — placement is
        un-assemblable for two of three subjects and needs an honest "not available" path.
        (Confirmed by the chunk-B-3 measurement above, which is the authoritative one now.)
- [ ] doing — **P4.5** Practice generator backend (started 2026-08-08): topic/difficulty/count/
      source filtering, persisted practice sets, "not enough questions" honesty path,
      export/print payload. UI spec S-20/S-21.
      **Design is already settled by D4.6 — do not re-open it.** A practice set is
      `Quiz(kind=QuizKind.practice, student_id=caller, teacher_id=None)` + a self-
      `QuizAssignment`, exactly like placement; the enum member already exists (migration
      0010 shipped `quizkind` with all four members) so **no migration is needed**.
      Take/resume/submit stay the existing `/api/student/quizzes/...` endpoints.
      `lemely/db/placement_repo.py` is the worked example to mirror.
      **The one site D4.6 §3 explicitly defers to P4.5:** `quiz_taking_repo.list_assigned`
      currently returns only class-assigned rows, so a practice set is invisible in S-25/S-26.
      P4.5 adds a second branch scoped by `QuizAssignment.student_id == caller` and narrowed
      by a **positive** `kind IN (...)` allowlist — never `kind != 'teacher'`, which fails
      open the day a fifth kind is added. A placement quiz must stay excluded from that list
      (pinned today by `test_a_placement_quiz_is_not_an_assigned_quiz`).
      **Targeting weakness is the acceptance criterion, not a nice-to-have** (MISSION §4:
      "generated practice demonstrably targets seeded weaknesses"). The join vocabulary is
      P4.2's `"<code> <name>"` labels, which D4.7 made real on the marking side — read weak
      topics from `WeaknessRecord`, not from a re-derivation.
      **Honesty path:** when the filtered pool cannot fill the requested count, return what
      exists **and say so** with a machine-readable reason — never pad, never silently
      shorten (spec §1.4). The 0625 bank is 273 rows / 211 topic-labelled and 0580/0606 are
      empty, so this path is the common case, not an edge case.
      **Carry D4.9's lesson:** narrow to the papers `student_enrolment_papers` names when the
      student has rows, and do **not** narrow when they have none.
- [ ] todo — **P4.6** Flashcards backend: decks by subject/topic, AI deck generation from a
      weakness, SM-2-style spaced repetition, review sessions.
- [ ] todo — **P4.7** Adaptive study plan: rebuild the scheduler on placement + questionnaire +
      rolling performance; weekly regeneration; concrete sessions (topic, activity type,
      duration); completion + XP hook (XP itself is P5 — leave a seam, do not build it).
- [ ] todo — **P4.8** Frontend S-01..S-05 (onboarding steps + placement in-progress/results).
- [ ] todo — **P4.9** Frontend S-20/S-21 (practice) + S-22/S-23 (flashcards).
- [ ] todo — **P4.10** Frontend S-24/S-25 (study-plan week view + session detail), replacing the
      current placeholder `StudyPlan.tsx`.
- [ ] todo — **P4.11** Acceptance + standing UI gate: E2E (onboard → placement → plan; practice
      targets seeded weaknesses), axe/Lighthouse, screenshot corpus for every new screen × state ×
      breakpoint, **maths notation + diagram rendering verified visually in screenshots, not
      assumed** (MISSION §4 names this explicitly).
- [ ] todo — **P4.12** Phase-4 report, merge to develop, push, update PR #3, ntfy.

### Environment facts worth not re-deriving (cost real work to find)
- Run gates as `./scripts/check.sh` in the **foreground** — it exports `$HOME/.local/bin`
  onto PATH itself, so all 13 gates run. A backgrounded run that a session dies on has
  happened repeatedly; the audit leg alone takes ~11 minutes.
- `pytest -q` emits **no `N passed` line** (a reporter plugin eats it). Count the progress
  characters in the `^[.sFEx]+ +\[ NN%\]` lines, or read the `Total coverage:` line.
- `GEMINI_API_KEY` lives in `/home/sico/Lemely/.env` and is **not** exported into a
  non-interactive shell — `set -a && . ./.env && set +a`.
- The UI gates write to gitignored `reports/.scratch` (D3.2). Re-baseline explicitly with
  `LEMELY_REPORT_DIR`; never commit into a previous phase's report dir.
- The E2E backend is `scripts/e2e_server.py` on port 8000 — there is no module-level `app`
  attribute on `lemely.web.app`.
- `scripts/seed_e2e.py` is the ONE seeding path for both harnesses, all 5 roles.
- **The past-paper corpus is outside this repo**: `/home/sico/PaperScraper/papers/CAIE/igcse/
  <subject>-<code>/<year>/<session>/` (648 PDFs, 0580/0606/0625). `Sources/` holds only mark
  schemes and the 4 solved scripts — no question papers. Read-only from here.
- Re-parse mark schemes with `lemely parse-mark-schemes <corpus-dir> --output-root
  outputs/schemes --force --on-error continue` (~54s for 0625; 32/72 parse).

## Session journal
See `BUILD/JOURNAL.md` for the dated 3-6 line entries; decisions and rationale live in
`BUILD/DECISIONS.md` (D0.x/D1.x/D2.x). Superseded per-task narrative for Phases 0-2 has been
pruned from this file per MISSION §8b now that their reports are committed — see the git
history of this file, or the phase REPORT.md files, if the detail is ever needed again.
