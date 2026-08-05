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
- [ ] doing — **P3.3** Teacher analytics. Per-class and per-student analytics, aggregate/ranked
      weakness topics (T-04 heatmap data), grade distribution, trend series. Backend.
      Also closes a tenancy hole P3.1 missed: `/api/teacher/overview` still enumerates
      `history_store.list_students()` (every student in the store) instead of the caller's
      own rosters, and labels at-risk rows with the raw `history.student_id`.
- [ ] todo — **P3.4** Review queue override-and-annotate (T-08). Accept / adjust marks with
      method+accuracy breakdown / note to student; overrides recorded as teacher corrections
      that supersede the AI mark on the student's result; integrity-flag dismissal leaves no
      student-visible record. Backend + tests.
- [ ] todo — **P3.5** Teacher quiz builder backend (T-09/T-10). Difficulty targeting by expected
      grade, material selection, pool from past-paper/generated questions, assign to class,
      auto-mark, results feed analytics.
- [ ] todo — **P3.6** Parent portal backend (P-01..P-04). Linked children, child overview /
      subject detail / weaknesses (read-only), notification preferences. Parent authz: only
      own linked children.
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
