# BUILD STATE — single source of truth

status: RUNNING            # RUNNING | COMPLETE | HALTED
current_phase: 4            # Phase 3 complete, merged (49d9750) and reported; Phase 4 not started
last_updated: 2026-08-10T04:15:00Z   # P4.9 chunk B closed, 13 gates green. Next: chunk C (gate 8 for all four screens).
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
- [x] done — **P4.5** Practice generator backend (D4.10). `lemely/db/practice_repo.py`
      (`PracticeService`: preview / create / export) + `lemely/web/routers/practice.py` +
      `schemas_practice.py`; `enrolled_paper_numbers` hoisted into `student_profile_repo` and
      shared with placement. No migration (0010 already shipped `quizkind`). $0.00 Gemini.
      **Availability is tri-state, not binary** — a *short* set is not a *failed* set, so
      `available=True` covers the honest-shortfall case (`reason="insufficient_pool"`, true
      `available_count`) and `False` is reserved for `no_questions` / `no_weaknesses`. Never
      padded, never silently shortened. Given the corpus this is the normal path.
      **`list_assigned` grew the second branch D4.6 §3 deferred here**: owner-scoped on
      `QuizAssignment.student_id`, narrowed by a **positive** `kind IN (practice, study_plan)`
      allowlist. Placement stays out — `test_a_placement_quiz_is_not_an_assigned_quiz` passes
      unmodified. Export excludes `model_answer`/`mark_scheme_points`/`mcq_answer`
      **structurally** (asserted on the dataclass field set, not one response body).
      **Live-bank measurement:** 0625 unfiltered → 273 available; `"4.3 Electric circuits"` →
      10; 0580/0606 → `no_questions`; weak-only with no weakness rows → `no_weaknesses`. The
      273 (vs placement's 211) is deliberate — an untopiced question is unusable for a
      weakness *profile* but fine as practice *material*.
      **2153 tests / 6 skipped / 0 failed / 89.81% cov** (P4.4 baseline 89.68%); all 13 gates
      green, 0 skipped. The subagent reported done with `ruff format` red on two of its own
      files — caught by the orchestrator's own gate run, not its report.
      *(Original scope line: topic/difficulty/count/source filtering, persisted practice sets,
      "not enough questions" honesty path, export/print payload; UI spec S-20/S-21.)*
- [x] done — **P4.6** Flashcards backend: decks by subject/topic, AI deck generation from a
      weakness, SM-2-style spaced repetition, review sessions. (UI spec S-22/S-23.)
      All three chunks landed (`1fb49f7`, `03fee94`, `b1a44bf`); decisions D4.11.
      **2229 tests / 6 skipped / 0 failed / 90.08% cov** (P4.5 baseline 2153 / 89.81%);
      all 13 gates green, 0 skipped. Migration 0011, no `web/` diff, $0.00 Gemini.
      Chunk C was found **already on disk uncommitted** from a killed session and was
      verified by an independent gate run rather than trusted — the same pattern P4.5 and
      chunk B hit. It came back clean this time (`pre-commit run --all-files` exit 0), which
      is the first handover in this phase that did.
      **Chunk plan (2026-08-08), backend only — no `web/` diff, so gate 8 is not in play:**
      - [x] chunk A — **done** (`1fb49f7`) — schema + the pure scheduler, as planned below.
        Migration **0011** applied; `alembic check` clean on **upgrade and downgrade**
        (note: `alembic check` errors "Target database is not up to date" when the DB sits
        behind head — that is the check refusing, not a downgrade failure. Don't re-derive it).
        `lemely/core/spaced_repetition.py` is pure and clock-injected.
        **Four departures from canonical SM-2 are documented at the point of divergence**, each
        pinned by a test — do not "correct" them back to the paper without changing the test
        deliberately: (1) ease is penalised on a lapse (canonical SM-2 leaves EF untouched on
        q<3) because leaving it means a repeatedly-failed card keeps its optimistic multiplier;
        (2) `again` reschedules at **+10 min with `interval_days=0`** (a same-session relearning
        step, what every modern SRS ships) rather than canonical SM-2's 1 day; (3) the
        four-button grade maps onto 0/3/4/5 with **no invented quality 1 or 2**; (4) rounding is
        the built-in banker's rounding because SM-2 specifies no tie-break rule.
        **`ReviewGrade` is declared twice on purpose** — `core` as plain Python, `db` as the
        Postgres enum — because import-linter forbids `core`→`db`.
        `tests/test_flashcard_schema.py` pins the two against drift; **do not deduplicate it by
        importing across the boundary.** 39 tests across the two new files. $0.00 Gemini.
      - [ ] chunk A (original plan, kept for the rationale) — Migration **0011** (additive): `flashcard_decks`
        (owner `user_id`, `subject_code`, nullable `topic` in the **P4.2 `"<code> <name>"`
        vocabulary**, `origin` enum manual/weakness/topic), `flashcards` (deck FK CASCADE, front/back,
        `source` enum manual/ai, nullable `source_question_id`, and the SM-2 state:
        `repetitions`/`ease_factor`/`interval_days`/`due_at`/`last_reviewed_at`/`lapses`),
        `flashcard_reviews` (the audit log a self-graded scheduler needs to be checkable, and P5's
        XP seam). Plus `lemely/core/spaced_repetition.py` — pure SM-2, **clock injected**, never
        `datetime.now()` inside, so scheduling is testable by inversion.
        SM-2 state lives **on the card**, not in a join table, because a deck is owned by exactly
        one student — there is no shared-deck case to key around in this phase.
      - [x] chunk B — **done** (`03fee94`) — `FlashcardService` + AI generation, all three
        honesty rules pinned by tests. 36 tests, Gemini mocked, $0.00.
        **Found the chunk B work already on disk uncommitted** from a killed session and
        verified it rather than trusting it: 38 tests passed but `ruff` was **red on 8 findings**
        in `flashcard_repo.py` (the same "subagent reports done with its own gate red" pattern
        P4.5 hit — keep running the orchestrator's own gate pass, the handover's word is not
        evidence). Fixed, plus one real gap: **there was no `delete_deck`**, so a student handed
        an unwanted AI deck could only delete cards one at a time and keep the husk. Added with
        cascade proven at both ORM (`delete-orphan`) and DB (`ON DELETE CASCADE`) level, plus
        subject-filter and due-limit tests that had no coverage.
        **Weakness→topic resolution reads `WeaknessRecord` rows verbatim** (D4.10 §2), reduced
        to a single topic because `FlashcardDeck.topic` is singular; ties broken alphabetically
        so the choice is deterministic rather than whatever the planner returned.
      - [ ] chunk B (original plan, kept for the rationale) — `lemely/db/flashcard_repo.py` (`FlashcardService`) + AI generation
        (`lemely/core/flashcards.py` schemas + `lemely/io/flashcard_generation.py` mirroring
        `QuestionGenerator`, mocked in tests, $0.00 live spend).
        **Honesty rules, non-negotiable:** an AI-written card is stored `source='ai'` and stays
        distinguishable from a student's own card for its whole life; a weakness-generated deck
        records which topic it targeted; and "no weakness rows" is an honest refusal
        (`no_weaknesses`) exactly as P4.5 does it, never a silently empty deck.
      - [x] chunk C — **done** (D4.11) — `lemely/web/routers/flashcards.py` +
        `schemas_flashcards.py`, wired in `deps.py` (`get_flashcard_service`, the only P4
        service wired with a Gemini client) and `app.py`. Ten routes under
        `/api/student/flashcards`, student-only at the router level. No migration, no `web/`
        diff, $0.00 Gemini. 20 route tests + 47 across the P4.6 suite.
        **Two decisions worth not re-deriving (full text D4.11):**
        1. **Another student's deck is a 404 here, not P4.5's 403** — a deck exists for
           exactly one owner, so a 403 is an existence oracle over private study material.
           The service still raises both typed errors and both are still tested; only the
           HTTP rendering is flattened. The test asserts the real id and a random UUID return
           **byte-identical** bodies, then inverts it (owner gets 200).
        2. **`due_session` had to be added to the service** — the chunk plan requires S-22's
           "nothing due" to carry the next due date and `list_due_cards` could only return a
           list. `total_due` is the real backlog **regardless of `limit`**; a capped session
           reporting its cap as the whole backlog is invented precision.
        **The AI-relabel guard is stronger on the wire than in the service:** `ApiModel` is
        `extra="forbid"`, so `PATCH {"source": "manual"}` is a **422**, not a body silently
        dropped. Both halves pinned — "ignored" and "rejected" look identical to a test that
        only checks the stored value.
        **Two unguarded inputs the orchestrator found by reading the handover, not from its
        report (D4.11 §5) — do not re-derive:** `GET /due?limit=-1` was a **500** (a bare SQL
        `LIMIT`, which Postgres rejects when negative) → `Query(ge=1)`; and
        `POST /decks/generate` took an **unbounded `count` straight to a billed Gemini call**
        against the $8 ceiling → `Field(ge=1, le=50)`. The count test asserts on the
        **generator mock**, because a 422 that still called the model would already have spent
        the money. 22 route tests now.
      - [ ] chunk C (original plan, kept for the rationale) — `lemely/web/routers/flashcards.py` + `schemas_flashcards.py`, student-only
        and **owner-scoped on every read and write** (decks are per-student; a deck id from another
        student must 404, not 403-after-probe). S-22's "nothing due today" is a real state carrying
        the next due date, not an empty list.
- [x] done — **P4.7** Adaptive study plan: rebuild the scheduler on placement + questionnaire +
      rolling performance; weekly regeneration; concrete sessions (topic, activity type,
      duration); completion + XP hook (XP itself is P5 — leave a seam, do not build it).
      **What exists today and why it is not enough:** `lemely/core/study_plan.py`
      (`build_study_plan`) splits `weekly_hours` across weak topics proportionally to
      `lost_marks` and emits one `StudySession(week=1, hours=…, focus="Practice and review: X")`
      per topic. That is *vague advice with a number attached* — MISSION §4 requires **concrete
      sessions (topic, activity type, duration)**. It also ignores placement results, the S-02
      questionnaire, and rolling performance, has no notion of a week other than the literal
      constant `1`, and is never persisted: `GET/POST /api/student/plan`
      (`routers/student.py:790/814`) rebuild it from scratch on every request, so a plan cannot
      be completed, regenerated, or compared against the previous week.
      **Chunk plan (2026-08-08):**
      - [x] chunk A — **done** (`fc4dca9`). `lemely/core/study_plan.py` rewritten pure +
        clock-injected; `ActivityType`, `StudySession(date, activity_type, duration_minutes)`
        and `StudyPlanUnavailableReason` added to `core/study.py`. Weights **0.5 weakness /
        0.3 placement / 0.2 confidence**, documented at the point of divergence and pinned;
        a missing signal **renormalises** rather than zero-filling, which is what makes
        "questionnaire only, no placement yet" a real plan instead of a diluted one.
        All callers migrated in the same commit (`routers/student.py` GET+POST, `cli.py`,
        the narrator prompt). 28 tests in `tests/test_study_plan.py`; $0.00 Gemini.
        **2250 tests / 6 skipped / 0 failed / 90.13% cov** (P4.6 baseline 2229 / 90.08%);
        all 13 gates green, 0 skipped.
        **The defect the orchestrator found by measuring, not from the subagent's report —
        do not re-derive:** the first implementation clipped each topic's share to the
        90-minute session cap and dropped the remainder, so **a three-weak-topic ten-hour
        week scheduled 270 of 600 minutes** while `weekly_hours` still reported 10 for the
        S-24 header. Topics over the cap are now **split into several blocks on distinct
        days** (585/600 for that case, and no topic is ever sat twice in one day).
        The pre-fix figure is written into the regression test.
        Two `TestWeighting` tests read priority off session *position*, which stopped being
        a proxy once sessions sorted by date; rewritten to assert **total minutes per
        topic** — what the weighting actually decides. Nothing skipped or deleted.
        **Gap chunk C must close (not a regression — this state did not exist before):**
        `StudyPlanDTO` carries no `available`/`reason`, so the honest `no_signal` refusal
        and the real "nothing to schedule this week" both reach the frontend as an empty
        `sessions` list and are indistinguishable. Chunk A's whole distinction dies at the
        wire until chunk C decides the DTO. `activityType`/`date` are likewise not exposed
        yet — `hours` is a unit conversion of `duration_minutes`.
      - [ ] chunk A (original plan, kept for the rationale) — pure scheduler rewrite in `lemely/core/study_plan.py`: sessions carry an
        **activity type** (`practice` / `flashcards` / `past_paper` / `review`) and a **duration
        in minutes**, and are laid out across the days of one week. Inputs become explicit and
        weighted: weakness `lost_marks` (rolling performance), placement topic results, and the
        S-02 `student_confidence_ratings` — all three already keyed on the **P4.2
        `"<code> <name>"` topic vocabulary**, which is the whole reason those three files were
        made to share it. Pure, **clock-injected** (chunk A of P4.6 set that precedent), no I/O.
        `build_study_plan`'s current signature is kept working or its callers migrated in the
        same commit — `routers/student.py` and `io/study_plan_ai.py` both import it.
        **Honesty rule:** a student with no weakness rows, no placement, and no questionnaire
        gets an honest `no_signal` refusal, never a plausible-looking invented week (P4.5/P4.6
        precedent). Activity type must be *earned* — do not schedule `flashcards` for a topic
        with no deck or `practice` for a topic the bank cannot serve.
      - [x] chunk B — **done** (`27f6a16`). Migration **0012** (additive: `study_plans`,
        `study_plan_sessions`) + `lemely/db/models/study_plan.py` + `lemely/db/study_plan_repo.py`
        (`StudyPlanService`). `alembic check` clean on **upgrade and downgrade**, verified by
        actually running both, not from the report.
        **2273 tests / 6 skipped / 0 failed / 90.23% cov** (chunk A baseline 2250 / 90.13%);
        all 13 gates green, 0 skipped. $0.00 Gemini.
        **The week is the ISO week (Monday) of the injected clock**; regeneration **supersedes**
        (stamps `superseded_at`) rather than mutating, so last week stays auditable and a
        completed session stays a true record. A `no_signal` refusal **is persisted** — "no plan
        generated yet this week" and "refused a plan this week" are different facts and both
        stay queryable. D4.12's honesty rule survives the trip to Postgres.
        **Availability is real, which is the load-bearing part:** practice/past-paper counts come
        from the bank behind the **same `visible_bank_filter`** `PracticeService` uses, and deck
        presence from the student's own decks — so chunk A's "activity type must be earned" is
        enforced against the live bank instead of collapsing every session to `review`.
        XP correctly left as a seam (`completed_at`); no points/streak column was added.
        **Fifth handover this phase to report done with its own gate red** — `pytest` failed on
        `tests/test_db_schema.py::test_all_expected_tables_registered`, the deliberate
        unregistered-schema-drift guard, which the two new tables were never added to. Caught by
        the orchestrator's gate run. **Keep running it; the handover's word is still not evidence.**
      - [ ] chunk B (original plan, kept for the rationale) — migration **0012** + `lemely/db/study_plan_repo.py`: persist the plan and
        its sessions, weekly regeneration (a new week supersedes rather than mutates the old one,
        so last week stays auditable), and per-session completion. **XP is P5 — leave the
        completion record as the seam and build no XP.**
      - [x] chunk C — **done** (`5a28431`, D4.13). `lemely/web/routers/study_plan.py` at
        `/api/student/study-plan` (student-only at router level) + `schemas_study_plan.py`,
        wired in `deps.py` (`get_study_plan_service`) and `app.py`. Three routes:
        `GET /{subject_code}`, `POST ""` (201), `POST /sessions/{id}/complete`. No migration
        (0012 covers it), **no `web/` diff** so gate 8 was not in play, $0.00 Gemini.
        **2292 tests / 6 skipped / 0 failed / 90.29% cov** (chunk B baseline 2273 / 90.23%);
        all 13 gates green, 0 skipped.
        **D4.12 §5's gap is closed — that is the substance of the chunk.** The envelope
        (`CurrentStudyPlanDTO {generated, plan}`) makes three states distinguishable that
        previously all arrived as an empty `sessions` list: *no plan generated this ISO week*
        (`generated: false`), *generated and honestly refused* (`available: false`,
        `reason: "no_signal"`), and *a real plan* — which may itself legitimately carry
        `sessions: []`. **None of the three is a 404**; a 404 on state 1 would have conflated
        "you have no plan yet" with "no such subject" and with a network failure, and S-24
        would have had to guess. `activityType` and `date` reach the wire for the first time.
        Both `StudyPlanNotFoundError` and `StudyPlanOwnershipError` render **404 with a
        byte-identical body** (D4.11's existence-oracle precedent); a malformed non-UUID
        session id is **422**, not the 500 a bare `ValueError` would have given.
        **Found on disk uncommitted from a killed session and verified rather than trusted** —
        the sixth such handover this phase, and the **first to come back clean on every gate
        including its own `ruff`/`mypy`** (the five before it reported done with their own gate
        red). Verification was an independent full `check.sh` run plus reading the tests for
        vacuity: all 15 carry their inverse, including the two scoping pins D4.13 §3b names
        (another student's plan invisible / one subject's plan not served under another).
        Nothing needed fixing, which is worth recording precisely because it is the exception.
        *(Original chunk-C plan retained in git history of this file; D4.13 carries the full
        rationale.)*
- [x] done — **P4.8** Frontend S-01..S-05 (onboarding steps + placement in-progress/results).
      All four chunks landed (0, A, B, C); decisions D4.14/D4.15/D4.16. **Gate 8 is genuinely
      satisfied for the first time on Phase-4 screens** — not vacuously: the audit registry now
      carries 6 entries / 7 states for S-01..S-05 on four seeded accounts, and all 13 gates pass
      with 0 skipped. 41 route-states, **zero axe violations at any severity**, Lighthouse a11y
      100 on the four scored new routes, zero console errors, zero horizontal-scroll violations.
      **Two defects that only a real gate run could find, both fixed here — see D4.16:** every
      new screen shipped without an `<h1>` (QUALITY-BAR.md:45; axe *moderate*, so gate 8's
      serious/critical threshold passed over it), and the E2E seed still collided on rerun,
      failing `playwright-e2e` on a genuine `uq_question_bank_paper_question` IntegrityError.
      Impeccable audit **16/20 (Good)**, detector clean, three sub-44px touch targets raised.
      **First `web/` diff of Phase 4 — gate 8 comes back into play** (QUALITY-BAR.md,
      `/impeccable audit` on changed files, `npx impeccable detect` clean, axe zero
      serious/critical, Lighthouse a11y ≥ 95, screenshots per screen × state × breakpoint).
      Backends this composes, all landed and route-tested: `/api/me` onboarding (P4.3),
      `/api/student/placement/*` (P4.4 chunk B-4), and the **existing**
      `/api/student/quizzes/...` take/resume/submit path placement deliberately reuses.
      **Honesty states that must reach the screen, not be designed away:** placement
      availability is a real `not available` + machine-readable `reason` for 0580/0606
      (they have zero ingested questions — D4.6 §5, not a gap to code around), and every
      S-02 questionnaire field is skippable, where a skipped answer is `NULL` and must not
      render as an answer the student gave (D4.5).
      **Two scoping facts established by measurement before any chunk was briefed — do not
      re-derive:**
      1. **No maths renderer is needed, and adding one would be speculative work.** MISSION §4
         requires maths notation to render properly and be *verified in screenshots*. Measured
         the actual banked corpus: **1 of 273** stems contains anything LaTeX-shaped, and the
         maths that is present is **plain Unicode** (`Ω α β γ ρ θ ² ³ ⁵ × °`, 21 distinct
         non-ASCII chars) which every browser renders natively. **Do not add KaTeX/MathJax.**
         What the stems *do* need is `white-space: pre-line` — they carry real newlines that
         structure the question, and collapsing them is the actual rendering risk here.
      2. **No student quiz-taking screen exists anywhere in `web/`.** P3.5 built the take/
         submit *backend* and P3.8 built only the teacher side (`QuizBuilder`/`QuizResults`).
         So S-04 is not "reuse the quiz screen" — it is the first question-rendering +
         answer-input surface in the product, and P4.9/P5 will compose it. Build it as a
         reusable component, not as a screen-local one-off.
      **Chunk plan (2026-08-09):**
      - [x] chunk 0 — **done** (D4.14). `renderable_bank_filter()` in `question_bank_repo.py` —
        a pure Postgres `~*` predicate over the existing `prompt` column, applied at all four
        pool sites (`QuestionBankService._filters`, `PracticeService._matching_clauses`,
        `StudyPlanService._availability`, `PlacementService._load_candidates`). **No migration,
        $0.00, zero Gemini.** Exclusion from *serving*, not deletion — the row stays auditable.
        **2297 tests / 6 skipped / 0 failed / 90.30% cov** (P4.7 baseline 2292 / 90.29%);
        all 13 gates green, 0 skipped.
        **The load-bearing finding, which the obvious fix would have missed:** `PlacementService`
        **does not call `visible_bank_filter` at all** — it builds its own filter in
        `_load_candidates`. Folding the predicate into that shared seam would have been a clean
        one-line change that passed review and left **placement — the worst-affected path, the
        one that plants the false weakness — completely unfixed.**
        **Honest line drawn at 25 of 273, not 4 and not 32**, by reading all 32 loose matches
        individually: bare "image" (3) is the optics sense, and "draw a diagram of the circuit
        used" (4) is the student's own *answer*, not a dependency. Both kept servable.
        **Orchestrator-verified independently, not from the report** — the subagent signed off
        before its own gate run finished, and never measured the thing that could actually
        break. 25/273 excluded and all four provable IDs confirmed excluded by direct query;
        the NULL-prompt three-valued-logic trap (`NOT (NULL ~* …)` is NULL → silent drop)
        checked and closed (`prompt` is `NOT NULL`, zero NULLs).
        **Placement changed and the change is recorded rather than smoothed over: 0625 went
        9 q / 15.19 min → 10 q / 17.06 min, still 6 syllabus topics, still under the 18-min
        ceiling.** It got longer because the excluded questions had been counted toward the
        15-minute target. Practice pool 273 → 248. 0580/0606 unchanged (`no_questions`).
      - [ ] chunk 0 (original plan, kept for the rationale) — **the figure-dependency defect, found by measuring the live
        bank while scoping S-04.** `question_bank` has **no image/figure column at all** (verified
        against `information_schema`) — P4.1 excluded 654 figure-bearing leaves, but **4 stems
        that survived still say "The diagram shows …"** and are placement-eligible
        (`0625_w24_qp_13#39`, `0625_s24_qp_11#5`, `0625_w24_qp_11#36`, `0625_s24_qp_11#19`;
        a looser pattern flags up to 18, the 4 are the provable ones).
        **Why this is not cosmetic and not deferrable behind the frontend:** the 0625 placement
        assembles exactly **9** questions, so one such draw makes ~11% of the test unanswerable.
        The student loses those marks, the placement records a weakness they **do not have**, and
        that false weakness is precisely what seeds the P4.7 study plan and the P4.5
        weakness-targeted practice. It renders perfectly and screenshots clean — invisible to
        every gate this build runs, which is why it gets fixed before the screen that would
        display it. Same class as D3.21's confidently-wrong paper 22.
        Fix as **exclusion from serving, not deletion**: a deterministic detector, no Gemini, so
        placement/practice never draw a question the bank cannot fully render. Must be pinned by
        its inverse (a non-figure stem is still servable) or it will silently empty the pool.
      - [x] chunk A — **done**. `web/src/portals/student/screens/onboarding/` (`SubjectsStep.tsx`,
        `QuestionnaireStep.tsx`, `onboardingData.ts` — the pure payload builders, which is what
        made the honesty rule testable), `Onboarding.tsx` rewritten as the wizard shell,
        `meTypes.ts` + `useMeApi.ts` grown to cover the four P4.3 endpoints, new
        `components/ui/slider.tsx` added to the catalogue rather than inlined.
        **138 web unit tests (3 files) green; all 13 gates green, 0 skipped.** No backend diff,
        so the 2297/90.30% backend figures from chunk 0 stand. $0.00 Gemini.
        **D4.5's skip rule is pinned three ways, and the third is the subtle one:** a skipped
        field is **absent from the payload** (not `0`, not `null` — asserted on the serialised
        wire, not just the object); an **explicit** `null` on a touched field is preserved, so
        *clearing* an answer stays distinguishable from *never answering*; and
        `hasExternalLessons: false` is sent, **not** mistaken for a skip. A falsy-means-skipped
        bug would have silently discarded every "no" answer in the questionnaire.
        **Constraint 3 verified by the orchestrator, not from the report:** all 9 confidence
        topic labels checked against `lemely/data/syllabus_topics.json` — 9/9 are real taxonomy
        entries, no invented vocabulary. That mattered because an invented label would join
        against nothing in the bank or the weakness engine and fail silently.
        **Legacy-route decision:** the frontend `usePostOnboarding` hook and its
        `OnboardingRequest` type are deleted (their only caller was the screen this replaces);
        the backend `POST /api/student/onboarding` route **stays** — it is still covered by
        `tests/test_authz_matrix.py` and `tests/test_web_student.py`, so deleting it here would
        have been an unrelated backend change inside a frontend chunk. Its removal belongs with
        the legacy `/api/student/plan` pair in P4.10/P4.11.
        **Seventh handover this phase to sign off before its own gate run finished** — it was
        in fact green, but that was verified by the orchestrator's own run, not taken on trust.
      - [ ] chunk A (original plan, kept for the rationale) — S-01 + S-02: the real multi-step wizard on the **P4.3** backend
        (`PATCH /api/me/student-profile`, `PUT .../enrolments`, `PUT .../confidence-ratings`,
        `POST .../complete-onboarding`) + the TS types/hooks for them, which do not exist yet
        (`meTypes.ts` covers only `ProfileDTO`). **Replaces** the legacy single-step
        `Onboarding.tsx`, whose own docstring says "there is no multi-step wizard backend yet" —
        there is now. Whether the legacy `POST /api/student/onboarding` route and
        `usePostOnboarding` die here or in P4.11 is a chunk-A decision to record, not assume.
      - [x] chunk B — **done** (verified 2026-08-09, fourth session). The gate run that was
        "in flight" at the previous checkpoint has now **completed and is green**:
        **all 13 gates PASS, 0 skipped** (`ruff-check`, `ruff-format`, `mypy`, `import-linter`,
        `pytest`, `web-typecheck`, `web-lint`, `web-build`, `web-test`, `impeccable-detect`,
        `playwright-e2e`, `puppeteer-audit`, `ui-thresholds`). Run in the **foreground** per the
        environment note; exit 0.
        **Backend figures are unchanged and that is verified, not assumed:**
        `git diff --stat 27744b5..HEAD -- lemely tests alembic scripts` is **empty**, so chunk B
        carries **zero backend diff** and chunk 0's **2297 tests / 6 skipped / 0 failed /
        90.30% cov** still stand. The moving number is **224 web unit tests**, green. $0.00 Gemini.
        Narrative of what chunk B actually fixed follows.
        **`a690040` fixes a FOURTH answer-loss defect (D4.15), found by
        actually running gate 7 — the previous two sessions never ran an orchestrator gate pass
        at all.** Two saves for one question could be on the wire together (reconnect retry with
        the cached value, debounced edit with newer text — that overlap was deliberate, so a
        newer edit is never dropped as a duplicate). But arrival order is not dispatch order and
        `save_answer` is a last-write-wins upsert with no version guard, so the **older** save
        could land last at the server, and `onSuccess` then wrote its own captured value into the
        cache stamped `dirty: false`. The student sees the newer answer on screen; the next
        reload sees a clean entry, defers to the server, and **the paper is marked against text
        the student did not write.** D3.21's shape exactly; invisible to every gate.
        Fixed on two independent lines: saves serialized per question (`saveChains` —
        **coalescing, not cancelling**, so a queued save reads the cache when its turn comes and
        carries the newest value) plus `isCacheEntryUnchanged` gating the clean-commit by value
        equality. `buildAnswerSavePayload` deleted rather than left dead — a coalesced save has
        no single "field that changed"; both fields now go from the cache, which
        `SaveAnswerRequestDTO` handles as "set these, leave the rest" (checked against
        `schemas_quiz.py:312`, not assumed). `flushPendingSaves` — which had **zero coverage**
        despite being the fix for the worst of the three `c2d444f` defects — now also waits on
        busy-but-clean refs and blocks submit on the cache being dirty-free.
        Plus a latent S-02→S-03 routing bug: `Object.keys(drafts)[0]` is not selection order (JS
        hoists integer-like keys), invisible only because all three syllabus codes have a leading
        zero. `placementInviteSubject` orders by the S-01 catalogue.
        11 new tests, **each verified by inversion** (probes fail exactly 5 / 5 / 3).
        **224 web unit tests green, `tsc --noEmit` clean, `pre-commit run --all-files` clean.**
        (The full 13-gate run that was in flight at that checkpoint has since completed green —
        see the chunk-B header above.) $0.00 Gemini.
        Previous-session narrative follows.
        **The gaps the previous session recorded below are now closed and the extraction it
        described is on disk**: `placementData.ts` carries `placementInviteView`/
        `placementResultView` (both screens switch on the discriminated union rather than
        re-deriving in JSX) and `quizTakerData.ts` carries the injected-storage answer cache.
        66 unit tests green across the two files, `marked:false`, `spansMultipleBands:false`,
        `topic:null` and the reload-merge all pinned with their inverses.
        **Three real defects the orchestrator found by reading the wiring, not from any report
        — do not re-derive:**
        1. **The reconnect-retry effect resent every dirty answer on every render.** `doSave`
           depended on the whole `saveAnswer` object, and react-query returns
           `{ ...result, mutate }` — a **fresh object every render** (verified in the installed
           `node_modules/@tanstack/react-query/build/modern/useMutation.js`, where only `mutate`
           is `useCallback`-stable). So `doSave`'s identity changed every render, the effect's
           `[online, doSave]` deps re-fired every render, and every dirty answer was resent.
           With the 1s elapsed-time ticker already forcing a render a second, that was **a
           duplicate PUT per dirty answer per second on the ordinary typing path**, not just
           after a reconnect. Fixed by depending on the stable `saveAnswer.mutate`.
        2. **A restored-from-cache dirty answer was never resent after a reload.** The whole
           point of the reload-merge is that an edit which failed to save survives; it came
           back into the UI but stayed local, because the retry effect keyed only on `online`
           and `data` is undefined on first mount (the take query is still loading), so the
           seed never triggered it. Fixed with a `seedVersion` bump in the deps.
        3. **Submit did not flush unsaved answers.** A student who types and hits submit inside
           the 600ms debounce had that edit sitting in a timer nothing fired — **the answer
           exists on screen and on the device while the paper is marked without it**, and an
           online save failure had no other resend trigger before submit. Same
           confidently-wrong shape as D3.21. `flushPendingSaves` now awaits every dirty answer
           and **blocks the submit on failure** rather than submitting a script that is not the
           one the student wrote.
        Plus one honesty fix: the save-error text promised "we'll retry automatically" while
        online, which nothing did; it now states what is actually guaranteed (kept on this
        device, resent before submit) — true only *because* fix 3 exists.
        New pure `refsToRetry(cached, inFlight)` excludes in-flight refs from the retry pass
        (an entry stays dirty for the whole duration of its own save), deliberately **not**
        consulted by the edit path so a newer edit typed mid-flight is never dropped as a
        duplicate. 5 tests, **verified by inversion** (removing the exclusion fails exactly 2).
        Original handover note follows.
        **Code was on disk, uncommitted, gates not yet run by the orchestrator.** New:
        `web/src/lib/placementTypes.ts`,
        `lib/hooks/usePlacementApi.ts`, `components/quiz/{QuizTaker.tsx,quizTakerData.ts}`,
        `portals/student/screens/placement/{PlacementInvite,PlacementTest,PlacementResult}.tsx`
        + `placementData.ts`, `tests/unit/{placement,quizTaker}.test.ts`. Changed: `lib/api.ts`
        (`ApiError` now carries structured `.detail` — needed because placement's 409 detail is a
        whole `PlacementAvailabilityDTO`, not a string; backward compatible, orchestrator-reviewed),
        `portals/student/index.tsx` (3 routes), `Onboarding.tsx` (S-02 → S-03 exit).
        **The eighth handover this phase to sign off before its own gate run finished** — but the
        first to report its gaps *accurately* when asked instead of claiming green: it had extracted
        only the pure-logic modules and left `marked:false`, `spansMultipleBands:false`,
        `topic:null` and the offline/unsaved-answer cache implemented **but untested**.
        **Component tests are not the fix and must not be added:** `web/vitest.config.ts` records
        `environment: "node"` as a deliberate decision (D3.20) — no jsdom, no @testing-library,
        because component behaviour belongs to Playwright against a real browser. Gaps are being
        closed the repo's way instead: extract the decision out of the JSX into a pure function
        (the `onboardingData.ts` pattern) and inject storage rather than touching the
        `localStorage` global (the clock-injection precedent). Highest-value one is the
        reload-merge: **a local edit that failed to save before a reload must not be silently
        discarded in favour of the server's older value.**
        Verified by the orchestrator already: the S-05 "this page will update on its own" promise
        is backed by a real `refetchInterval` that stops when `marked` flips true (a claim the
        student can check), and `white-space: pre-line` is on the stem — the actual rendering risk
        per the P4.8 measurement, no maths renderer added.
        (original scope line) — S-03 + S-04 + S-05 on `/api/student/placement/*` + the existing
        `/api/student/quizzes/...` take/resume/submit path. S-03 must render the **honest
        `not available` + machine-readable reason** for 0580/0606; S-04 owns answer persistence
        across a lost connection and resume (UI spec §S-04 states both); S-05 is framed as a
        *baseline*, never a grade.
      - [x] done — chunk C (closed 2026-08-09, session 7 — D4.16) — the standing UI gate for all five screens
        (gate 8: QUALITY-BAR.md, `/impeccable audit` on the changed files, `npx impeccable
        detect` clean, axe zero serious/critical, Lighthouse a11y ≥ 95, screenshot corpus for
        every screen × state × breakpoint, no unintended regression against baselines).
        **Session 7 (2026-08-09) — the registry actually RAN for the first time, and it found a
        real defect the previous six sessions could not have found by reading.** Session 6's two
        fixes were on disk uncommitted; committed as `3bee1c3` after verifying their string
        matchers against the real components, then the audit leg was run standalone
        (`cd web && npm run -s audit`, exit 0, ~11 min). **Both session-6 fixes work:** all seven
        new states loaded, the `ready`-driven wizard survived the repeated navigation
        `pressToggleOnce` was written for, and S-04 was genuinely reachable — so the
        placement-eligible seed is real, not just green in isolation.
        **The defect (`b0e13ea`), which every gate had been passing over: all five new screens
        shipped without an `<h1>`.** Every one of the seven new states reported
        `page-has-heading-one` (**moderate**) while all 24 P3 routes reported zero at any
        severity. Each screen rendered its page title as a styled `<div>` — the visual heading
        existed, the semantic one did not. **This is a QUALITY-BAR.md:45 failure outright**
        ("one h1 per page, heading order unbroken, landmarks"), but gate 8's axe threshold only
        bars *serious/critical*, so `ui-thresholds` passed and would have kept passing forever.
        Same shape as the vacuous passes this chunk exists to remove: it screenshots perfectly
        clean, and a screen-reader user reached onboarding and the product's first
        question-rendering surface with nothing to orient by.
        Fixed by promoting each title div to `h1` (same classes + `m-0`; Tailwind preflight
        already zeroes heading margins and makes them inherit size, so it is **visually
        identical — confirmed against the re-captured screenshots, not assumed**).
        `QuestionShell` is safe as the single h1 because `steps[stepIndex]` renders exactly one
        question at a time. `QuizTaker` has no visible page title *by design* (mid-test a student
        needs "Question 3 of 10" and the countdown, not a banner) so it carries an `sr-only` h1
        with the real `quizTitle` — it is composed by placement now and practice/assigned quizzes
        in P4.9/P5, so the fix lands once for all three. Loading/error branches get `sr-only` h1s
        per the P3 ReviewItem/StudentDetail precedent, because `ErrorState` renders its heading as
        a non-heading element (the Phase-2.5 report §8 gap, still open).
        **Verified by a second full audit run, not by the first one's absence of complaint:** all
        seven new states **0/0/0/0 at every severity**, zero nonzero axe counts anywhere in the
        registry, **Lighthouse a11y 100** on all four scored new routes (perf 80–83, at/above the
        §11 student floor of 80), zero console errors, zero horizontal-scroll violations;
        `ui-thresholds` clean across **41 routes** (was 34 states). 224 web unit tests, typecheck
        and lint green. $0.00 Gemini.
        **Visually spot-checked by the orchestrator rather than trusted to the string assert:**
        the `questionnaire-skipped` capture shows the thumb at `min` with the readout reading
        **"Not set"**, not "0 hours/week" — D4.5's honesty rendering is real on screen, which is
        the whole reason that state was given its own capture. S-05 checked the same way: the
        title promotion is visually identical, and the screen really does render "This is a
        baseline, not a grade", the working-level refusal ("we're not estimating a working level
        from it yet") and **"Not enough data yet."** instead of a fabricated weakest topic.
        **Full 13-gate run: ALL PASS, 0 skipped, exit 0** — run three times this session, the
        last after every fix. **2308 passed / 6 skipped / 0 failed / 90.30% cov** (chunk-0
        baseline 2297 / 90.30% — +11 from `tests/test_seed_e2e.py` incl. the new
        stem-collision regression; coverage flat).
        Note for whoever reads a raw `pytest` log next: **the backend diff since chunk 0 is NOT
        empty** — earlier chunk-C sessions added `scripts/seed_e2e.py` (+398) and
        `tests/test_seed_e2e.py` (+192), so the carried-forward 2297 figure needed re-measuring
        rather than restating.
        **One measurement trap worth not re-deriving:** a bare `.venv/bin/pytest` reports
        **1 failed** — `tests/architecture/test_import_linter.py` shells out to `lint-imports`,
        which is not on PATH unless you export `.venv/bin` yourself. It is a `FileNotFoundError`
        in the harness, not a broken contract: with PATH set the test passes and `lint-imports`
        exits 0 ("Contracts: 2 kept, 0 broken"). `check.sh` exports PATH at its line 34, which is
        why its `pytest` gate is green. Verified both ways rather than assumed.
        **Session 5 progress (2026-08-09):** the seed was run standalone against the live stack
        and is green — exit 0, all four placement accounts created, `bankQuestionCount: 24` on
        paper 2, and every key `audit.mjs` dereferences (`assignmentId` on inProgress/completed,
        `subjectCode`) confirmed present in the emitted payload rather than assumed.
        **One real vacuity found by the orchestrator while reviewing the registry, not from any
        report — do not re-derive:** S-05's `ready` matched **`"starting picture"`**, which
        `PlacementInvite` also renders (`"Get a real starting picture in {subject}"`). The entry
        would have been satisfied by the *invite* screen and passed **without ever loading the
        result** — the exact vacuous pass this chunk exists to remove, on the one screen whose
        whole point is the honesty framing. Tightened to `"This is a baseline, not a grade"`,
        which is unique to `PlacementResult`'s **marked** branch (grep-verified: one hit in
        `web/src`) and is the UI-spec framing itself, so a regression that dropped it fails the
        gate instead of hiding. The other five `ready` strings were checked the same way and are
        each unique to their screen; S-03's refusal heading is specific to the `no_questions`
        reason alone (`placementData.ts:32`), so a different reason would fail rather than pass.
        **Session 6 (2026-08-09) — a second defect found by reading the on-disk registry against
        the runner's contract, before the gate run reached it:** `visitRoute` calls `st.setup`
        **once**, but then calls `gotoReady(page, url, …)` **again for every breakpoint and once
        more for axe** — so any state driven through the UI must survive a reload. It does not:
        `Onboarding.tsx:60` holds `wizardStep` in component state that always remounts as
        `"subjects"`, and the seeding effect (`:71-100`) restores *answers* from the server but
        **never which step you were on**. So S-02's `setup`-driven questionnaire state is undone
        by the first reload and its `ready` ("Which school") cannot match. Fix is to drive the
        wizard from `ready` (which runs after *every* navigation) rather than `setup`, and to make
        the drive **tolerant of Physics already being selected** — after the first pass the
        enrolment is real and the seeding effect restores it, so an unconditional click would
        *deselect* it and leave `Continue` disabled forever (`SubjectsStep.tsx:92` carries
        `aria-pressed`, which is how the drive tells the two apart).
        **Also found: D4.5's honesty rendering is the one thing chunk C's brief names that the
        on-disk registry does not actually cover.** The S-02 entry stops at the *school* step, but
        the skipped-field risk lives on the **sliders** — `SkippableSlider` renders `unsetLabel`
        ("Not set" / "Not rated yet") while the thumb sits at `min`
        (`QuestionnaireStep.tsx:47-63,173,209`). A regression to `formatValue(min)` would render
        "0 hours/week" — an answer the student never gave — and screenshot perfectly clean.
        That state gets its own capture.
        Plus the runtime summary line (`audit.mjs:1701`) still told a reader `/student/onboard`
        was "not covered by this registry" — stale in exactly the way the header note it sits
        beside warns about, and the log is what a human actually reads. Corrected.
        **`impeccable-detect` and `ui-thresholds` already pass — that is NOT evidence the new
        screens are covered.** The audit registry is P3.10's 24-route/34-state one (D3.17/D3.18)
        and predates S-01..S-05; a green `ui-thresholds` on a registry that never lists the new
        routes is a gate passing *vacuously*. First job of this chunk is to establish, by
        reading the registry rather than assuming, which of S-01..S-05 are absent from it, and
        to add them with their **real** states — including the honesty states P4.8 exists to
        keep on screen: placement `not available` + machine-readable reason for 0580/0606
        (D4.6 §5), and the skipped-questionnaire-field case where a skipped answer is `NULL`
        and must not render as an answer the student gave (D4.5).
        **Four facts established by measurement before briefing — do not re-derive:**
        1. **The registry does not mention placement or onboarding at all** (zero matches for
           either in `web/scripts/audit.mjs` and in `web/e2e/*.ts`). `audit.mjs`'s own header
           still lists `/student/onboard` under "Deliberately still NOT in this registry (P4/P5
           screens still on mock data)" — **stale since chunk A**, and the header is part of the
           fix. The five new routes are `/student/onboard`, `/student/placement/:subjectCode`,
           `/student/placement/test/:assignmentId`, `/student/placement/result/:assignmentId`
           (`portals/student/index.tsx:227-230`).
        2. **S-04 and S-05 are unreachable in the E2E DB as seeded today, and this is the real
           work of the chunk.** `scripts/seed_e2e.py` seeds exactly **5 teacher-authored MCQ
           `question_bank` rows with `paper_id=None`** (for the T-09/T-10 quiz).
           `PlacementService._load_candidates` takes only `source='past_paper'` rows,
           outer-joined to `Paper` for a `paper_number` that must have a `paper_timing.json`
           entry, and chunk 0's `renderable_bank_filter` applies on top. **Nothing in the seed
           satisfies any of that**, so every subject returns `no_questions` and there is no
           placement quiz to take or to have marked.
        3. **Therefore auditing only S-03's `not available` state would be the vacuous pass
           again**, in the exact shape `audit.mjs`'s header warns about ("an unlooked-at route
           is exactly how this gate became vacuous"). S-04 is the product's **first**
           question-rendering + answer-input surface and owns the answer-persistence behaviour
           four separate defects were just fixed in (D4.15) — leaving it unaudited is the least
           acceptable omission available. The seed must grow a genuinely placement-eligible
           past-paper bank (real `Subject`/`Paper` rows, `source='past_paper'`, topics in the
           P4.2 vocabulary, a paper number `paper_timing.json` actually carries).
        4. **Both S-03 states are required, not one or the other.** A subject with a viable bank
           (available) *and* one without (`no_questions`) are both real product states — 0580/
           0606 genuinely have zero ingested questions, and that honest refusal is behaviour
           P4.8 exists to keep on screen. `tests/test_placement_repo.py` already has the
           viable-bank fixture shape to copy from rather than invent.
### Carried forward from P4.8 chunk C's Impeccable audit (D4.16 §4) — must reach DELIVERY.md
Recorded rather than smoothed over. None is a regression; all three predate or exceed P4.8.
- **The global `prefers-reduced-motion` rule is a blanket kill.** `web/src/index.css:742` sets
  `animation-duration: 0.001ms !important` on `*`. On S-05's unmarked state the spinning
  `CircleNotch` is the *only* evidence marking is in progress, beside copy promising "This page
  will update on its own" — with reduced-motion on it freezes and working is indistinguishable
  from stalled. Affects all 41 routes; `processing-state.tsx:19` already acknowledges it.
  Deliberately not touched in a frontend chunk: editing the global rule risks visual regression
  everywhere. **P5 must handle this** — MISSION §4 Phase-5 already requires motion to respect
  `prefers-reduced-motion` *proven by a test*, and that test cannot honestly pass against a
  blanket kill.
- **`Button size="sm"` cannot meet QUALITY-BAR.md:40's 44px floor** (~31px: 12.5px text +
  `py-2`). Raised at the three new-screen call sites only; **33 call sites exist and 11 of the
  15 files are teacher screens**, where 44px would break dense layouts (counted, not assumed).
  The shared variant is a cross-portal decision. Same family as the Phase-2.5 report §8 gap.
- **Ad-hoc container widths** — `max-w-[560px]` ×3, `max-w-[720px]`, `max-w-[820px]` where a
  shared token belongs. (`min-h-[44px]` and `slider.tsx`'s `py-9px` are *not* this: both are
  documented repo-wide touch-target idioms.)
- **S-04 re-renders its whole question tree once per second** from the elapsed ticker, no
  memoization. Lighthouse perf 82, so not currently measurable — but this exact ticker is what
  turned an unstable react-query object identity into a duplicate-PUT-per-second bug (D4.15 §1).

- [ ] doing — **P4.9** Frontend S-20/S-21 (practice) + S-22/S-23 (flashcards).
      Backends this composes: `/api/student/practice/*` (P4.5, 3 routes: preview / create /
      export), `/api/student/flashcards/*` (P4.6 chunk C, 10 routes), and the **existing**
      `/api/student/quizzes/{assignment_id}` take/save/submit path — practice sets are
      quiz-shaped and `list_assigned` already carries `kind IN (practice, study_plan)`.
      **Five scoping facts established by measurement before any chunk was briefed — do not
      re-derive:**
      1. **A practice set is marked but its result cannot be read.** `POST .../submit`
         (`quiz.py:837`) triggers `QuizMarkingService.mark_submission` on a background thread
         for **every** kind, so a submitted practice set really is marked and the marks are in
         the DB. But `StudentQuizTakeDTO` carries **no score, no per-question marks and no
         feedback at all** (`schemas_quiz.py:303` — header + questions only), and the only
         result route in the product, `GET /api/student/placement/{id}/result`, is narrowed by
         `Quiz.kind == QuizKind.placement` (`placement_repo.py:476`) so a practice assignment
         404s there. **`practice.py` has exactly three routes and none of them is a result.**
         So S-21's "finish action producing a short summary" has no backend: a student can
         generate a set, work it, submit it, and there is nowhere in the product to see how
         they did. The marking already ran — only the *read* is missing. Same class as P4.8
         chunk 0: fix the data seam before building the screen that would display it.
      2. **S-20's topic-selection control has no data source.** There is **no topic-listing
         endpoint anywhere in `lemely/web/`** (checked every router). `survey_past_paper_
         questions` is CLI-level and unscoped; `QuestionBankService.count_by_band` is
         per-band and staff-scoped. The teacher builder (T-09) works around this with
         **free-text topic entry** plus a live `pool-count` — acceptable for a teacher, wrong
         for a student, who cannot be expected to type `"4.3 Electric circuits"` exactly.
         The list must be filtered through the *same* clauses `_preview` uses (enrolled
         papers, `visible_bank_filter`, chunk-0's `renderable_bank_filter`) or it will offer
         topics the pool cannot serve.
      3. **Weak-topic prefill must come from the server, not the client.** S-20 says "topic
         selection pre-filled with their weak topics", and there are **two different weak-topic
         vocabularies in this codebase**: `PracticeService._preview` resolves
         `weak_topics_only` from `WeaknessRecord` rows (D4.10 §2, P4.2 `"<code> <name>"`
         labels), while the student subject-overview `WeakThreadDTO`
         (`schemas_student.py:49`) comes from `aggregate_weaknesses_from_history`. Prefilling
         the chips from the screen's own weakness list would silently join against nothing.
         `preview` **returns** its resolved `topics` — read them back from there.
      4. **Reveal-answer (UI spec S-21) cannot be built honestly and is deliberately not
         built.** No route returns a model answer for a bank question, and
         `PracticeExportQuestionDTO` excludes `modelAnswer`/`markSchemePoints`/`mcqAnswer`
         **structurally** on purpose (D3.8). Adding a reveal route would put marking material
         on a student surface. The spec's "deliberate friction so it isn't the default" is
         satisfied by submitting and reading the marked result, where the answer arrives
         attributed and carrying its confidence — not by a raw model-answer dump. Recorded as
         a scope decision, not a silent omission.
      5. **The local dev DB has drifted from STATE's recorded figures — measure, do not
         restate.** `question_bank` now holds **801** `past_paper` 0625 rows (739 topiced, 29
         distinct topics) plus **745** `generated` and 1 `teacher_upload`, against the 273
         P4.1 recorded; 528 past-paper and 390 generated rows were added 2026-08-08. Any
         pool figure quoted for P4.9 must be re-measured live through the service filters,
         not carried forward from P4.1/P4.5.
      **Chunk plan (2026-08-09):**
      - [x] chunk 0 — **done** (`dc0c0ac`). Both read paths landed, plus a third defect the
        live measurement exposed. No migration, **no `web/` diff** so gate 8 was not in play,
        $0.00 Gemini. **All 13 gates PASS, 0 skipped, exit 0** (run twice; the second run
        carries the full diff). **2331 passed / 6 skipped / 0 failed / 90.37% cov**
        (P4.8 baseline 2308 / 90.30% — coverage up, `practice_repo.py` at 99%).
        `GET /api/student/practice/{assignment_id}/result` — owner-scoped, `kind` narrowed to
        practice, following `export`'s existing 404/403 split rather than inventing a third
        rendering. `marked` is explicit and every score field is `None` while unmarked, never
        a fabricated `0`; `submissionStatus` keeps "not submitted" distinct from "submitted,
        being marked". **The confidence is real, not defaulted** — verified
        `QuestionResult.confidence_band`/`.confidence_score` are both `nullable=False`
        (`models/attempts.py:162,166`) before making the DTO fields non-nullable, and
        `effective_marks` (teacher-override-aware) is the accessor used.
        `GET /api/student/practice/{subject_code}/topics` — reuses `_matching_clauses`, so it
        cannot drift from what `preview` will actually serve; untopiced rows counted
        separately rather than given an invented label; weak topics resolved server-side.
        **The third defect, found by measuring the live bank and not derivable by reading:
        the bank mixes taxonomy levels.** 0625 returns `"1 Motion, forces and energy"` (152)
        as a *peer* of `"1.2 Motion"` (6) and `"1.3 Mass and weight"` (5) — D4.2's classifier
        writes whichever level it matched, so each row carries exactly one label and the sets
        are **disjoint**. A flat chip list would offer the parent as though it covered its
        children; a student picking it silently loses them, and the screen would look
        perfectly correct. Topics now carry `syllabusGroup`, reusing `core.placement`'s
        helper (promoted to public `syllabus_group`/`topic_sort_key`) rather than a second
        parser being written client-side. **Same defect class as P4.4 chunk B-3 §2**, which is
        why the helper already existed. Sorted by syllabus code, so `"10.1"` follows `"2.1"`.
        **Measured live (quote, do not re-derive): 0625 → 28 topics / 765 topiced / 59
        untopiced; 0580 and 0606 → 0 topics, correctly** (no ingested questions).
        **The briefed structural-exclusion test was missing from the handover and was added by
        the orchestrator** — and deliberately in the stronger form: asserted on the **field
        sets** of both the dataclass and the wire DTO, because the existing
        `test_export_route_never_returns_marking_material` asserts on a response *body*, which
        passes vacuously the moment `questions` comes back empty (exactly what an unmarked set
        returns). The ninth handover this phase to sign off before its own gate run finished;
        it was in fact green, but that was established by the orchestrator's run, not trusted.
      - [ ] chunk 0 (original plan, kept for the rationale) — the two missing read paths.
        `GET /api/student/practice/{assignment_id}/result` (owner-scoped, `kind` narrowed to
        practice exactly as placement narrows to placement; must distinguish *not yet marked*
        from *marked* rather than collapsing both to an empty body — S-21 polls it the way
        S-05 polls placement) and `GET /api/student/practice/{subject_code}/topics` (distinct
        servable topics + **real** per-topic counts through the same clauses `_preview` uses).
        Both pinned by their inverses or they will silently offer/return nothing.
      - [x] chunk A — **done** (verified 2026-08-09, sixth session). The two wip commits
        (`dd37966`, `137e83d`) were on disk with gates never run; the orchestrator ran them.
        **All 13 gates PASS, 0 skipped, exit 0** — foreground-equivalent serial run, the audit
        leg included. **249 web unit tests / 6 files, green** (chunk-B-of-P4.8 baseline 224).
        **Zero backend diff** — `git diff --stat aa4daf2..HEAD -- lemely tests alembic scripts`
        is empty, so chunk 0's **2331 passed / 6 skipped / 0 failed / 90.37% cov** still stand
        and were not re-measured. $0.00 Gemini.
        Four screens + the plumbing: `screens/practice/` (`PracticeGenerator` S-20,
        `PracticeSet` S-21 working view, `PracticeResult` S-21 summary, `PracticePrint`,
        `practiceData.ts` pure logic), `lib/practiceTypes.ts`, `lib/hooks/usePracticeApi.ts`
        (one hook per endpoint, no `fallback`, `result` polls while `marked === false`), four
        routes + nav item + crumbs.
        **Every constraint the chunk plan named was verified by the orchestrator, not taken
        from the handover:** `QuizTaker`'s prop interface is **byte-unchanged** (`PracticeSet`
        is a 21-line wrapper, the same shape as `PlacementTest` — the composition seam held for
        its second caller, which was the test); topic chips nest by `syllabusGroup`;
        `untopicedCount` renders as prose, never as a selectable topic; the weak-topic prefill
        reads the **server's** `weakTopics`; and every screen carries an `<h1>` (`PracticeSet`
        inherits `QuizTaker`'s own `sr-only` one — D4.16's defect is not repeated).
        **The substantive fix of the chunk is `137e83d`, and it is not cosmetic:**
        `weakTopics` and `topics` are resolved **independently** server-side — the first from
        `WeaknessRecord` rows, the second from the servable bank pool — so neither is a subset
        of the other. **Measured live: 8 of 15 recorded weakness topics have no servable bank
        topic**, including the weakness engine's own `"unknown"` fallback label and
        older-vocabulary labels like `"Electricity"`. Prefilling verbatim would have applied a
        filter **with no checkbox on the screen**: sent to `preview`/`create`, narrowing or
        emptying the pool, with no chip checked and no way to clear it — rendering as a flat
        "no practice material" with no visible cause, on the majority of real students. The
        prefill is now the intersection, and the dropped labels are **named on screen** rather
        than silently swallowed. Same defect class as P4.8 chunk 0 and P4.4 chunk B-3 §2: it
        screenshots perfectly and no gate can see it.
        **Fact 6 honoured — the photo-answer route is still deliberately not built** (no image
        field exists anywhere on the quiz answer path), and fact 4's reveal-answer likewise.
        30 unit tests in `web/tests/unit/practice.test.ts`, each carrying its inverse.
      - [ ] chunk A (original plan, kept for the rationale) — S-20 + S-21 frontend. `QuizTaker` is **composed, not forked** (its
        own docstring names P4.9 as a caller); the finish summary reads chunk 0's result route.
        **Scoped by measurement 2026-08-09 (fifth session) — do not re-derive:**
        - The composition seam is already exactly right and needs no change: `QuizTaker` takes
          `{assignmentId, onSubmitted, onExit}` and nothing else (`PlacementTest.tsx` is a
          21-line wrapper proving it). S-21's working view is that same wrapper with a
          practice exit. **Adding a prop to `QuizTaker` is a signal the chunk is going wrong.**
        - **Nothing frontend-side for practice exists yet:** no `practiceTypes.ts`, no
          `usePracticeApi.ts`, no practice screen, no route, no nav entry, no crumb. Five
          backend routes are live and un-consumed (`preview`/`topics`/`POST ""`/`export`/
          `result` — `lemely/web/routers/practice.py`), DTOs in `schemas_practice.py`.
          Mirror `placementTypes.ts` + `usePlacementApi.ts` conventions (one hook per
          endpoint, no `fallback` to `request()`, poll `result` while `marked === false`
          exactly as `usePlacementResult` does).
        - **Sixth scoping fact, and the one that would otherwise be built as a fiction:**
          UI spec S-21 names "do it on paper and photograph it" as an answer route.
          `SaveAnswerRequest` is `{answerText?, workingText?}` — **text only, no image field
          anywhere on the quiz answer path** (`placementTypes.ts:134`, and the backend PUT
          matches). There is no route that attaches a photograph to a quiz answer. Building a
          camera affordance here would either dead-end or silently discard the student's
          work. **Deliberately not built**, recorded as a scope decision alongside fact 4's
          reveal-answer, not silently omitted. The photograph route that *does* exist is the
          S-10..S-14 correction flow, which marks a whole past paper, not a quiz answer.
        - Topic chips must nest by `syllabusGroup` (chunk 0's third defect — a flat list
          offers a parent as though it covered its disjoint children), prefill from the
          `weakTopics` the **server** returns (fact 3), and never render `untopicedCount` as
          a topic.
        - Routes/nav to add: `practice/:subjectCode` (S-20), `practice/set/:assignmentId`
          (S-21 working view), `practice/result/:assignmentId` (S-21 summary), in
          `portals/student/index.tsx`; nav item + `crumbs` entry in `portals/student/data.ts`.
        - `<h1>` on every new screen (D4.16's defect — it shipped five screens without one).
      - [x] chunk B — **done** (2026-08-10, sixth session). `web/src/lib/flashcardTypes.ts`,
        `lib/hooks/useFlashcardApi.ts` (10 hooks, one per route), `screens/flashcards/`
        (`FlashcardDecks` S-22, `FlashcardReview` S-23, `flashcardData.ts` pure logic), two
        routes + nav + crumbs, `web/tests/unit/flashcards.test.ts`.
        **All 13 gates PASS, 0 skipped, exit 0.** **279 web unit tests / 7 files** (chunk A
        baseline 249). **Zero backend diff** — `git status --porcelain -- lemely tests alembic
        scripts` empty, so chunk 0's **2331 / 6 skipped / 0 failed / 90.37% cov** stand
        unmeasured. $0.00 Gemini (generation is behind a live Gemini client but no live call
        was made).
        **Two defects the orchestrator found in the handover, neither self-reported as a
        defect — do not re-derive:**
        1. **`useEditCard` was defined and called nowhere**, so S-22's spec'd "edit" action
           could add and delete cards but never **reword** one. The hook was dead code and the
           action was half-built. Wired as an in-place row editor (`CardRow` owns its own draft
           state — a shared parent draft would carry one card's text into the next row opened).
           **The source chip stays rendered while the row is in edit mode**, deliberately: the
           label describes who *wrote* the card, and editing text is not authorship, so an AI
           card a student rewrites stays chipped AI-written.
        2. **A hand-made deck was being sent as `origin: "topic"` the moment the student typed
           a topic** — which renders as "Topic-generated", claiming a model wrote a deck the
           student built by hand. The backend never required it: `create_deck`'s own docstring
           is "`origin=manual`: `topic` is whatever the caller passes". Same honesty class as
           rule 1 (`source` on a card), one level up — provenance, and it screenshots
           perfectly. Fixed, and the decision **hoisted out of JSX into
           `manualDeckRequest`** in the pure module so a test pins it rather than a human
           reading JSX (chunk A's `onboardingData.ts` precedent). 4 tests with inverses; a
           blank topic is `null`, never `""`, which would read back as a topic the student chose.
        **The XP conflict below was honoured:** `summarizeSession` is pinned by a test asserting
        `Object.keys(summary)` is exactly `["reviewed", "gradeCounts", "intervalChanges"]` and
        that `"xp"`/`"points"`/`"streak"` are all absent — so P5 adding XP is a deliberate
        change to that test, not a silent drift.
        30 unit tests in `flashcards.test.ts`, each with its inverse; `<h1>` verified present in
        **every** render branch of both screens (5 and 3 respectively), not just the happy path.
        **Two API-shape limits worth carrying, both honest reflections of the backend rather
        than gaps to code around:** `GET /due` has **no `deck_id` filter** (only
        `subject_code`/`limit`), so "review due cards" is subject-scoped and there is no
        per-deck review entry point; and S-22's "edit" is an inline expansion, not a new
        S-numbered screen, because the spec lists it as one of S-22's actions.
        *(Original scoping block retained below.)*
      - [ ] chunk B (scoping, kept for the rationale) — S-22 + S-23 frontend on the existing 10 flashcard routes. No backend
        work expected. `source: "ai"` must stay visible on the card for its whole life, and
        `generatedCount` (not `requestedCount`) is what the screen reports.
        **Scoped by measurement 2026-08-10 (sixth session) — do not re-derive:**
        - **Starting position is identical to chunk A's:** ten routes live and
          **entirely un-consumed** (`lemely/web/routers/flashcards.py`, DTOs in
          `schemas_flashcards.py`), and **nothing frontend-side exists** — no
          `flashcardTypes.ts`, no `useFlashcardApi.ts`, no screen, no route, no nav entry,
          no crumb. Mirror `practiceTypes.ts` + `usePracticeApi.ts` (one hook per endpoint,
          no `fallback` to `request()`), which chunk A just established against this exact
          backend shape.
        - **The wire contract already encodes the honesty rules — the screens must not
          undo them, and each is verifiable:** `CardDTO.source` is present on every read
          while `EditCardRequestDTO` has **no `source` field at all**, so the API offers no
          relabel path and `ApiModel`'s `extra="forbid"` makes an attempted one a 422 (D4.11);
          `GenerateDeckResponseDTO` carries `requestedCount` **and** `generatedCount` because
          the model may return fewer and **nothing pads the difference**; `DueSessionDTO`
          carries `nextDueAt` and a `totalDue` that is the **whole backlog regardless of
          `limit`**, so S-22's "nothing due today" says *when* instead of rendering a void.
        - **`origin="weakness"` refuses with 409 `{"reason": "no_weaknesses"}`** — the same
          reason vocabulary P4.5/P4.9-chunk-A already render. Reuse that honest-refusal panel
          rather than inventing a third rendering; do **not** fall back to an untargeted deck.
        - **Product-truth conflict, decided rather than silently dropped (MISSION §12
          authority order):** UI spec S-23 says the end-of-session summary shows **XP**. XP is
          **P5** and does not exist — `study_plan` chunk B deliberately left `completed_at` as
          the seam and built no points/streak column. **An invented XP number on a student
          screen is exactly the fabricated precision spec §1.4 forbids**, so the summary
          reports only real session facts (cards reviewed, the again/hard/good/easy
          distribution, `intervalBeforeDays`→`intervalAfterDays`, next due time) and **no XP**.
          Not an omission — recorded here alongside P4.9's fact 4 (reveal-answer) and fact 6
          (photo answer). P5 adds XP to this summary; leave the seam, build no points.
        - `ReviewResultDTO` returns `intervalBeforeDays`/`intervalAfterDays` **so the student
          can see the scheduler's effect rather than trust it** — surface the change, don't
          discard it as internal.
        - `<h1>` on every new screen (D4.16), and S-23 must be keyboard-operable: the spec
          calls it a repeated micro-interaction where friction compounds, so the reveal and
          the four grade buttons need real key affordances, not mouse-only handlers.
      - [ ] doing — chunk C — the standing UI gate (gate 8) for all four screens: audit-registry
        entries with their **real** states (including the honest `no_questions` /
        `no_weaknesses` / `insufficient_pool` refusals and S-22's "nothing due today"), axe
        zero serious/critical, Lighthouse a11y ≥ 95, screenshot corpus, `<h1>` per screen
        (D4.16's defect — do not repeat it).
        **Opened 2026-08-10 (seventh session). The mutually-exclusive-state analysis STATE
        told this chunk to do BEFORE writing the seed is done — do not re-derive it:**
        - **Six routes, not four screens' worth** (`portals/student/index.tsx:250-255`):
          `practice/:subjectCode` (S-20), `practice/set/:assignmentId` (S-21 working),
          `practice/result/:assignmentId` (S-21 summary), `practice/print/:assignmentId`,
          `flashcards/:subjectCode` (S-22), `flashcards/review/:subjectCode` (S-23).
        - **`insufficient_pool` needs no created set — it is a *preview* state.**
          `PracticeGenerator.tsx:299` renders the shortfall panel ("Only N of M requested
          questions match") off `previewQuery`, so it is reachable by URL alone and is the
          **default** state given the small seeded bank. This kills the need to capture the
          post-create `created` branch, which is component state and could not have survived
          the runner's per-breakpoint reload anyway.
        - **Three new accounts, and the exclusivity that forces each one:** a student with
          weakness rows cannot demonstrate S-20/S-22's `no_weaknesses` refusal, and a student
          with cards due cannot demonstrate "nothing due today". So:
          `active` (weaknesses + 3 practice sets in 3 submission states + a deck due now),
          `settled` (a deck, every card reviewed `good` so `due_at` is in the future — a real
          scheduler outcome, not a hand-written date), `bare` (enrolled, no weaknesses, no
          decks). `no_questions` needs no account of its own — it is `/student/practice/0580`
          on any of them, because 0580 genuinely has zero ingested questions.
        - **One marked practice set does double duty**: answering one question wrong then
          submitting *and* marking it produces both S-21's `marked` capture and the
          `WeaknessRecord` rows S-20's weak-topic prefill needs. Same trick the placement
          `completed` account already uses; `quiz_taking_service.submit` does **not** mark
          (the route marks on a background thread), which is what makes the third set's
          `marking` state seedable at all rather than a race.
        - **S-22's weakness-generate 409 is free to capture**: `generate_deck`
          (`flashcard_repo.py:347`) resolves the topic — and raises
          `FlashcardUnavailableError(no_weaknesses)` — **before** `self._generator.generate`,
          verified by reading, so the refusal costs $0.00 Gemini against the $8 ceiling.
        - **Deliberately NOT captured, recorded rather than silently dropped:** S-23's
          end-of-session summary. Grading a card is irreversible and reschedules it, and
          `visitRoute` re-navigates for every breakpoint plus axe, so the second visit would
          render "Nothing due today" under a screenshot named `session-complete`. A capture
          that lies about which state it is is worse than an absent one. (Same reload
          constraint session 6 found for the S-02 wizard — the fix there was to drive from
          `ready`; here no drive is idempotent, so the state is out of scope for this gate.)
        **Scoped 2026-08-10 (sixth session), enough to start cold — do not re-derive:**
        - **This chunk has a `scripts/` diff, unlike A and B.** The registry is
          `web/scripts/audit.mjs` (~line 830 onward builds sessions, then a `return [...]`
          array of `{screenId, slug, path, session, ready, authed, states?}`); the data behind
          it is `scripts/seed_e2e.py`, the **one** seeding path for both harnesses. P4.8 chunk
          C's `// ── P4.8 chunk C · the four S-01..S-05 sessions ──` block is the worked
          example to copy, comment style included.
        - **Expect to need distinct seeded student accounts per state, for a reason specific
          to this data.** P4.8 needed four because `PlacementService.availability` excludes a
          student's own prior placement questions (D4.6 §4). The analogous traps here: a
          student with weakness rows cannot also demonstrate S-20's `no_weaknesses` refusal,
          and a student with cards due cannot demonstrate S-22's "nothing due today". **Work
          out which states are mutually exclusive before writing the seed**, or the registry
          will quietly capture the same state twice under two names.
        - **The refusal states are the point of this chunk, not the happy paths.** Screens
          that only ever screenshot populated are exactly how D3.21's and P4.8 chunk 0's
          defect classes survive. Capture: 0580/0606 `no_questions` (real — those subjects
          have zero ingested questions), `no_weaknesses`, `insufficient_pool` (the *normal*
          path given this corpus, per D4.10), S-21 not-submitted **and** marking **and**
          marked, and S-22 nothing-due.
        - **`<h1>` is already verified present in every render branch of all four screens**
          (Practice: Generator/Result/Print; Flashcards: Decks 3 branches, Review 5) — checked
          at chunk close, not assumed. D4.16's defect is not expected to recur here; the thing
          to watch for instead is what only a *run* finds (D4.16's own lesson: reading finds
          what is wrong with the code you are looking at, running finds what you did not think
          to look at). P4.8 chunk C's second defect was a seed that could not run twice.
        - `LEMELY_REPORT_DIR` re-baselines explicitly; the gates otherwise write to gitignored
          `reports/.scratch` (D3.2). Never commit into a previous phase's report dir.
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
- **Never run `pytest` concurrently with `./scripts/check.sh`.** Both drive `pytest-cov` and
  they contend on the same `.coverage` data file, so the *coverage figure* comes back badly
  wrong while the run still exits 0 — a concurrent run reported **89.67% with
  `practice_repo.py` at 68%**, where a clean serial run of the identical tree reported
  **90.37% and 99%**. The test counts stayed correct (2331/6/0 both times), which is what
  makes it convincing: it reads as a real coverage regression to be chased. Re-measure
  serially before believing any coverage drop.
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
