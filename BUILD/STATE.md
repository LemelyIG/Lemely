# BUILD STATE — single source of truth

status: RUNNING            # RUNNING | COMPLETE | HALTED
current_phase: 6            # Phases 0-5 complete, merged and reported; Phase 6 STARTED
last_updated: 2026-08-11T09:00:00Z   # **Ninety-fourth session: PHASE 6 STARTED.** Tree was clean, INBOX had no
#                                    unhandled items, BLOCKERS B1-B3 all resolved, no orphaned pytest. Branched
#                                    `feature/phase-6-hardening` off develop at `76450ff` and did P6.0 — the
#                                    reconnaissance and the twelve-task plan below. The headline recon finding is
#                                    that **Phase 6 is mostly greenfield, not a polish pass**: there is no
#                                    Dockerfile, no compose file, no deployment doc and no DELIVERY.md anywhere in
#                                    the repo, and README/CHANGELOG still describe the 2026-08-04 (Phase-0/1)
#                                    product. Plan ordering is deliberate — gate-affecting code fixes (P6.1) land
#                                    before the full-suite (P6.6) and visual sweep (P6.7) so those runs exercise
#                                    the shipping tree, and the ~25-minute gate run is spent once, not twice.
#                                    Previous session's note follows. **Ninety-third session: PHASE 5 IS COMPLETE. P5.12 landed — the report is committed (`1f6354a`), `feature/phase-5-engagement` is merged to develop (`322118b`) and pushed, and PR #3 is retitled "Phases 0–5" with a Phase-5 section APPENDED (all seven phase sections verified present afterwards; P3.11's silent-section-loss trap did not fire).** Nothing was re-implemented and no gate was re-run: session 92's `EXIT=0` run is the tree that merged, and every figure in the report is measured off that run's own committed artifacts.
#                                    **The one substantive finding of this session is a number correction, and it is recorded because this build keeps getting burned by hand-copied figures.** STATE and the session-92 note carried **146** axe route-states; `reports/phase-5/axe/_summary.json` has **73** rows and `audit.mjs` writes exactly one row per audited state (`axeSummary.length`, its own comment says so). 146 is double the truth. Phase 4's report carries the same shape (122 against a 61-row summary), so it is a propagated arithmetic error, not a Phase-5 coverage regression. **The verdict is unaffected — zero violations at every impact however the states are counted** — but a figure nobody can reproduce from the committed artifacts is exactly what this build has been paying for all phase, so the report states 73 and says why. Two other report figures were likewise recomputed from the JSON rather than copied: Lighthouse **44** route reports, a11y floor **96** (`teacher-review`, 100 on the other 43), and **8** routes below performance 80 (not the 9 STATE carried).
#                                    Also corrected while writing the appendix: `xp_awards.py` is in `lemely/web/`, not `lemely/db/`, and the settings screen is `DeviceSettings.tsx`, not `DeviceManagement.tsx`. Both were caught by testing every path in the appendix for existence before committing — a 20-second check that a phase report should always get.
#                                    **Next session starts Phase 6 on a fresh `feature/phase-6-*` branch off develop.** Read MISSION §4 Phase 6 and the carried limitations below before planning; several of them (the unenforced Lighthouse performance floor, the untypechecked `web/e2e/`, the synthetic accuracy gap) are explicitly Phase-6-shaped work, and DELIVERY.md must carry every one of them whether or not they are fixed.
gemini_spend_usd: 0.19641   # MEASURED from the real ledger `outputs/gemini_spend.json`
# (cumulative_usd 0.1964076, updated 2026-08-10T13:15:19Z), not carried forward. Phase 4 closed
# at $0.18429, so **Phase 5 spent $0.0121** across the whole phase — nothing in the engagement
# layer calls a model, and every automated test mocks Gemini (D4.3 made that structural).
# This field is a hand-copied mirror of the ledger and has drifted before (it read 0.1612
# against a real 0.18429). Re-read the ledger rather than this line before quoting a spend.

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

## Phase 4 — Content generation + study plans — DONE (2026-08-09)
Question-stem extractor closing D3.7 (P4.1, D4.1/D4.2 — 72 papers → 273 banked 0625 stems),
syllabus taxonomy transcribed from the three official CAIE PDFs + classification (P4.2, D4.4),
student profile/onboarding data model that finally activates at-risk rule 2 (P4.3, D4.5,
migration 0009), placement backend reusing the *existing* quiz engine behind an XOR-checked
student-owned-quiz shape (P4.4, D4.6–D4.9, migration 0010), practice generator with tri-state
availability (P4.5, D4.10), flashcards + clock-injected SM-2 (P4.6, D4.11, migration 0011),
the adaptive study plan — pure scheduler, persisted, superseding weekly regeneration (P4.7,
D4.12/D4.13, migration 0012), and the ten screens S-01..S-05 / S-20..S-25 (P4.8/P4.9/P4.10,
D4.14–D4.22), closed by the acceptance + UI-gate pass (P4.11, D4.23–D4.25) that took `web/e2e/`
from 8 files/14 tests to 11/25.
**2350 tests (2344 passed / 6 skipped / 0 failed) / 90.18% cov** (from develop's 1939 /
89.42%); **all 13 gates green, 0 skipped**; 4 additive migrations, both directions clean;
122 axe route-states with zero violations at any severity, zero console errors, zero
horizontal-scroll violations, Lighthouse a11y floor 96; cross-phase compare 81 added /
**0 removed** / 78 changed. Merged to develop (321fdfc), pushed. PR #3 updated (title
"Phases 0–4"), NOT merged. Report: `reports/phase-4/REPORT.md`. Gemini cumulative
**$0.18429 / $8.00** (Phase 4 itself $0.0257 — everything built with Gemini mocked).

### Honest limitations carried forward from Phase 4 (must appear in DELIVERY.md, not silently resolved)
Full text in `reports/phase-4/REPORT.md` §7. The ones that change what a later phase may assume:
- **The Lighthouse performance floor MISSION §11 claims is gated is NOT enforced (D4.25).**
  `scripts/check_ui_gates.py` has no performance check at all; a student route sits at **79**
  and `ui-thresholds` passes. Do not cite MISSION §11's "performance ≥ 80" as a met gate.
  The specific failing route is not stable between runs; the gap is.
- **0580 and 0606 have zero ingested questions**, so placement and practice honestly refuse for
  two of three subjects. The ceiling is **mark-scheme parse coverage (32/72 for 0625)**, not
  stem extraction — that is the highest-leverage thing to improve, and it is not a P5 blocker.
- **A practice set is marked but its result cannot be read** — marking runs, marks are in the DB,
  no route exposes them for `kind=practice`. Only the *read* is missing.
- **`web/e2e/` + `playwright.config.ts` are still in no tsconfig `include` (D3.20)** — now
  covering 25 test blocks, none of them ever typechecked.
- **XP is entirely P5's and the seam is `completed_at`** (D4.17/D4.19). S-23 and S-25 deliberately
  ship with no XP number. ~~No points or streak column exists~~ — **CORRECTED 2026-08-09 at P5.0
  by reading the migrations rather than trusting this line: the schema DOES exist.** `xp_events`
  (user_id, source, amount, awarded_on, metadata, indexed on user_id+awarded_on) and `streaks`
  (current_length, longest_length, last_active_on, freezes_available, unique per user) were both
  created in **migration 0002**, Phase 1's core schema, with an `xpsource` enum whose four values
  — `paper_corrected`, `quiz_completed`, `flashcard_reviewed`, `study_session_completed` — are
  exactly MISSION §4 Phase-5's four XP sources. `lemely/db/models/engagement.py` maps both and
  `models/__init__.py` exports them. **What is genuinely absent is every line of behaviour**: no
  repo, no service, no route, no award call site, nothing reads or writes either table. So P5 needs
  no migration for core XP/streak, and the accurate form of this limitation is *"XP has schema and
  zero behaviour."* Same failure mode as the `gemini_spend_usd` and `SeedContract` drifts — a
  hand-written mirror of a fact that nothing regenerates. Verify against the migrations.
- **Phase 2's synthetic accuracy gate is unchanged** (83.8% vs ≥95%) and **D3.21's paper 22 is
  still confidently wrong** (40/40 marks at confidence 1.0, zero flags, 3 marks of pure
  vision/transcription error).
- **The visual compare can never be pixel-clean:** the seed's `run_tag` is random per run, so
  every screen rendering a class name changes on every re-baseline. `0 removed` is the number
  that carries the gate; a nonzero `changed` count is not by itself a regression signal.

### Task checklist
- [x] done — P4.1 / P4.2 / P4.3 / P4.4 (chunks A, B-1..B-4) / P4.5 / P4.6 (A,B,C) / P4.7 (A,B,C) /
      P4.8 (0,A,B,C) / P4.9 (0,A,B,C) / P4.10 (A,B,C,D) / P4.11 (A,B,C,D,E). Per-task rationale is
      pruned per MISSION §8b now that the report is committed and merged — see
      `reports/phase-4/REPORT.md`, `BUILD/DECISIONS.md` (D4.1–D4.25), or this file's git history.
- [x] done — **P4.12** Phase-4 report, merge to develop, push, update PR #3, ntfy.


## Phase 5 — Engagement layer — DONE (2026-08-11)
XP engine with anti-farming caps and Cairo civil-date streaks (P5.2, D5.1–D5.3, migration 0013),
weekly-XP leaderboards across friends/class/school/global and per-subject with an opt-out flag
(P5.3, D5.4/D5.5, migration 0014), friends by friend code with one canonical row per pair (P5.4,
D5.6/D5.7, migration 0015), student-facing announcements + read-receipts + the exam calendar
(P5.5, D5.8, migrations 0016/0017), the notification inbox and payload-less VAPID web push with
`notification_preferences` actually gating delivery (P5.6, D5.9–D5.11, migration 0018), the
3-device limit made visible by a 409 login challenge + device management (P5.7, D5.12), the four
student screens S-28..S-31 (P5.8, D5.13/D5.14), the four cross-cutting screens G-10..G-13 plus
the service worker (P5.9, D5.15/D5.16), the `prefers-reduced-motion` proof test (P5.10), and the
acceptance + UI-gate pass (P5.11, D5.17) that took `web/e2e/` from 11 files/25 tests to 13/30.
**2927 tests / 90.91% cov** (from develop's 2350 / 90.18% — no drop at any commit in the phase);
456 web unit tests over 15 files; **all 13 gates green, 0 skipped**; 6 additive migrations;
**73 axe route-states with zero violations at any impact**, zero console errors, zero
horizontal-scroll violations, Lighthouse a11y floor 96 over 44 route reports; cross-phase compare
34 added / **0 removed** / 127 changed (all one intended nav change, verified by opening the
largest diff). Merged to develop (`322118b`), pushed. PR #3 updated (title "Phases 0–5"),
NOT merged. Report: `reports/phase-5/REPORT.md`. Gemini cumulative **$0.19641 / $8.00**
(Phase 5 itself $0.0121 — nothing in this phase calls a model).

### Honest limitations carried forward from Phase 5 (must appear in DELIVERY.md, not silently resolved)
Full text in `reports/phase-5/REPORT.md` §7. The ones that change what Phase 6 may assume:
- **No scheduler exists in this build (D5.9 §5).** `streak_warning` and `study_plan_reminder` are
  service methods nothing invokes on a timer, and **at-risk rule 3 (≥14 days inactive) cannot
  fire at its seam** — the alert fires on correction, and a student who just uploaded is by
  definition active. Do not report these as delivered notification types.
- **No VAPID keys on this machine**, so the transport is unavailable by design and **no real push
  can be delivered in any harness here**. The assertable facts are the inbox row and G-12's
  unavailable state. A payload-less push (D5.10) also means an offline arrival renders a generic
  "You have a new notification" — browsers require *some* notification per push.
- **Ships deliberately absent, each because the honest source does not exist:** the exam-calendar
  dates (no CAIE timetable on this machine; also no CLI wrapper around `ExamCalendarService.ingest`),
  S-31's lifetime stats (a count of `xp_events` is wrong by construction — caps write no row,
  dedupe writes one row for two markings), S-29's avatar image (no avatar storage; a monogram
  ships instead), G-10's rough location (no geo-IP, no stored IP), and UI spec §G-12's
  `weekly_summary` toggle (no backend enum value). **None of these is a gap to be "filled" later
  without first building the source** — the audit registry entries say so too.
- **G-10 declines Lighthouse on purpose.** `runLighthouseAudit` drives its own navigation and never
  replays the entry's `ready`, so it would score the plain login form under G-10's slug — a
  measurement of a state it never reached. `/login` is scored on its own entry.
- **The Lighthouse performance floor MISSION §11 claims is gated is STILL not enforced (D4.25).**
  This run has **8 routes below 80** (floor 65 `teacher-quiz-detail`; `student-standings` 70,
  `student-result` 73, `teacher-schemes` 74, `settings-notifications` 75, `teacher-review-detail`
  76, `student-announcements` 78, `student-placement-test` 79) and `ui-thresholds` passes.
  Three are new Phase-5 student routes, so this phase widened the gap. **Never cite a green
  `ui-thresholds` as a performance pass.**
- **`web/e2e/` + `playwright.config.ts` are still in no tsconfig `include` (D3.20)** — now 30 test
  blocks, none ever typechecked. Phase 2's synthetic accuracy gate is unchanged (83.8% vs ≥95%),
  D3.21's paper 22 is still confidently wrong, 0580/0606 still have zero ingested questions, and
  a practice set is still marked but unreadable.

### Two operational rules this phase paid twelve sessions for — do not re-derive them
- **A `FAIL` line in `check.sh`'s log is NOT the end of the run.** The script does not abort on a
  failed gate. Decide liveness from `ps` and the absence of the `EXIT=` line, never from a gate
  verdict. Session 82 inferred deadness from a failure message and set up session 83 to relaunch
  into a live run, which would have re-seeded the database underneath an in-flight audit.
- **Commit the screenshot corpus only after `EXIT=0`, and never wip-commit a dirty `reports/`
  while a run is in flight.** A crashed audit leaves a *partial* corpus, and the resume protocol's
  "clean up a dirty tree with a wip commit" would freeze that mid-run snapshot as if it were a
  curated baseline — which is exactly what produced session 73's misleading 75-file partial.
  `pytest` is the long pole at ~12–19 minutes, so a flat gate count before ~19 minutes is the
  normal shape of a healthy run, not a stall.

### Task checklist
- [x] done — P5.0 / P5.1 / P5.2 (A,B) / P5.3 (A,B) / P5.4 (A,B,C) / P5.5 (A,B,C) /
      P5.6 (spec,A,B,C1,C2a/b/c) / P5.7 (A,B) / P5.8 (A,B,C,D) / P5.9 (A,B,C,D) / P5.10 /
      P5.11 (A,B,C,D,E). Per-task rationale is pruned per MISSION §8b now that the report is
      committed and merged — see `reports/phase-5/REPORT.md`, `BUILD/DECISIONS.md` (D5.1–D5.17),
      or this file's git history.
- [x] done — **P5.12** Phase-5 report, merge to develop, push, update PR #3, ntfy.

## Phase 6 — Hardening + ship — IN PROGRESS (started 2026-08-11, session 94)
Branch: `feature/phase-6-hardening` (off develop at `76450ff`). See MISSION §4 (Phase 6).

### What P6.0 reconnaissance established (do not re-derive)
Measured, not assumed — every line below was checked on disk this session:
- **There is no Docker Compose file, no Dockerfile, and no deployment doc anywhere in the repo.**
  `find -maxdepth 2` for `*compose*`/`Dockerfile*` returns nothing; `docs/` holds only
  COMPONENT_CATALOGUE, database, exit-codes, LEMELY_UI_SPEC, quiz-model, superpowers. So MISSION
  §3's "definition of done for deployment" is **entirely unbuilt** — P6 builds it from zero, it is
  not a hardening pass over something existing. `supabase/` (config.toml + seed.sql) is the only
  container-adjacent asset.
- **`DELIVERY.md` does not exist.** README.md and CHANGELOG.md are both dated **2026-08-04** —
  i.e. Phase-0/1 era, describing a product five phases out of date.
- **Version is `0.1.0`** (`pyproject.toml:7`) and `web/package.json` is `0.0.0` — never bumped.
- **`tests/test_authz_matrix.py` exists**, so P6's authz re-verification extends a real matrix
  rather than inventing one. No concurrency or load test exists (`grep` for
  `concurren|asyncio.gather` hits only `test_device_repo.py`/`test_friend_repo.py`, both
  incidental).
- **`node -v` is v26.6.0**, so `npx impeccable detect src/` (needs 24+, MISSION §10) is runnable —
  no blocker there.

### Task checklist
- [x] done — **P6.0** Reconnaissance + phase plan (this block), branch created.
- [ ] todo — **P6.1** Gate-affecting hardening fixes, done FIRST so every later gate run exercises
      the final tree. (a) Put `web/e2e/` + `playwright.config.ts` into a tsconfig `include` and fix
      what 30 never-typechecked test blocks turn up (D3.20, carried since Phase 3). (b) Add the
      Lighthouse **performance** check to `scripts/check_ui_gates.py` — MISSION §11 scopes the ≥80
      floor to **student routes only**, so gate exactly that, then fix the student routes now
      failing it (`student-standings` 70, `student-result` 73, `student-announcements` 78,
      `student-placement-test` 79). The teacher-route figures are outside MISSION's stated floor and
      get recorded in DELIVERY.md, not silently gated away. **Do not close D4.25 by deleting the
      claim** — the fix is enforcement, not a reworded limitation.
- [ ] todo — **P6.2** Concurrency + load sanity (MISSION §4 P6 bullet 1). Parallel
      uploads/markings against the real DB proving no cross-request state bleed or lost update, and
      a basic API load-sanity script with recorded numbers. Gemini stays mocked.
- [ ] todo — **P6.3** Security re-review: authz matrix re-verified over **every** route including
      all Phase 4/5 additions, plus a `reviewer` adversarial sweep (authz, tenancy, IDOR,
      injection). Findings fixed or recorded.
- [ ] todo — **P6.4** Docker Compose: one command brings up Supabase-local + backend + the built
      SPA served with correct CORS/proxy. Backend + web Dockerfiles, compose file, Makefile target.
- [ ] todo — **P6.5** Deployment docs for a future free-tier cloud deploy (Supabase cloud +
      container host) at `docs/deployment.md`. Written, not hosted — MISSION §3 says no live hosting.
- [ ] todo — **P6.6** Full-suite pass: all 13 gates green on the final tree, E2E across all 5 roles
      on seeded realistic data. Launch with `setsid` per the environment note below.
- [ ] todo — **P6.7** Full-product visual QA sweep: regenerate the **entire** screenshot corpus,
      per-role contact sheets, `/impeccable audit` across frontend source, `npx impeccable detect
      src/` with every finding resolved, axe + Lighthouse over every route. Regression against the
      Phase-2.5 baselines is a blocker (MISSION §4). Read `removed` (must be 0), not `changed`.
- [ ] todo — **P6.8** README + CHANGELOG rewritten for the shipped product; version bumped in both
      `pyproject.toml` and `web/package.json`.
- [ ] todo — **P6.9** `DELIVERY.md`: every feature in MISSION §9's inventory with status, files and
      the tests that prove it, links to all seven phase reports, and an honest limitations section
      carrying **every** `### Honest limitations` item from Phases 2–5 whether or not P6 fixed it.
- [ ] todo — **P6.10** Fresh-clone acceptance: `git clone` → the documented commands → working
      product with seeded demo accounts for all 5 roles.
- [ ] todo — **P6.11** Phase-6 report, merge to develop, push, update PR #3, ntfy, then set
      `status: COMPLETE` (the supervisor stops on that value — it is the last write of the build).

### Environment facts worth not re-deriving (cost real work to find)
- **`pre-commit` needs `.venv/bin` on `PATH`, or two hooks fail for the wrong reason.**
  CLAUDE.md mandates `pre-commit run --all-files` before every commit. A bare
  `pre-commit` is **not on PATH at all** (use `.venv/bin/pre-commit`), and running it that
  way still fails `mypy` and `import-linter` with **`Executable 'mypy' not found` /
  `Executable 'lint-imports' not found`** — both are `language: system` hooks that resolve
  their binary off `PATH`, and invoking the venv's pre-commit by absolute path does not put
  the venv's `bin` there. Run it as
  `PATH="/home/sico/Lemely/.venv/bin:$PATH" .venv/bin/pre-commit run --all-files`
  (or `source .venv/bin/activate` first) and all ten hooks pass.
  **The failure mode that matters: it is a false red, not a code failure**, and the two
  hooks it fakes are exactly two of the gates — so it invites either a bogus "the tree is
  broken" diagnosis or a `--no-verify` habit. Session 62 caught it only because the
  concurrently-running `check.sh` had already printed `PASS mypy` / `PASS import-linter`
  on the same tree. **An "executable not found" is an environment answer, never a verdict
  on the code.**
- **A gate run must be launched with `setsid`, or it dies with the session. This note has
  now been wrong twice; the third version is the one backed by timestamps.** Five sessions
  (47, 48, 49, 50) produced **five `/tmp/check_p58*.log` files of exactly 84 bytes**, each
  stopping after the same four backend gates, i.e. mid-`pytest` (gate 5, `check.sh:65`).
  - *First theory (sessions 47–49): bad luck.* Wrong — identical byte counts across
    independent sessions is a deterministic cutoff.
  - *Second theory (session 50): the 600 s foreground Bash cap.* **Also wrong, and it cost
    a sixth run.** The logs are stamped 11:15 / 11:20 / 11:23 / 11:25 / 11:27 — **2 to 5
    minutes apart** — so each session died ~2–4 minutes in, nowhere near 600 s. Decisively,
    session 50 *did* follow that advice and ran it as a harness-tracked background task,
    and it died in exactly the same place. A foreground-only cap cannot kill a background
    task. **Check the timestamps before accepting a duration-based explanation** — the gaps
    between the logs falsified the cap theory using evidence that was already on disk when
    the theory was written.
  - *Third version, what actually holds:* the agent **session** is dying (cause not fully
    pinned; this box has 7.8 GB RAM and was already 3.7 GB into swap, and `pytest` with
    coverage over 2767 tests is the heaviest thing in the run — resource pressure, not a
    tool timeout). Whatever kills the session also kills anything in its process group,
    background or not, and that is what manufactures the orphaned-pytest trap below.
  **So: launch the run in its own detached session with `setsid`**, which puts it outside
  the agent's process group and lets it survive:
  `setsid nohup bash -c './scripts/check.sh > /tmp/LOG 2>&1; echo "EXIT=$?" >> /tmp/LOG' </dev/null >/dev/null 2>&1 & disown`
  Then poll the log; a session that dies mid-run costs nothing, because the next session
  reads a log that kept growing. Append `EXIT=$?` so the status is readable afterwards.
  - *Confirmed by session 52*, which resumed 3 minutes after session 51 launched the run
    and found it **still alive** — the first run in five to get past the 2–4 minute mark.
  - **Corollary that cost four sessions: an 84-byte log is the NORMAL appearance of a
    healthy run mid-`pytest`, not a symptom.** `check.sh` prints nothing for a passing
    gate, so between the four backend gates and pytest returning there is nothing to
    write. Sessions 47–50 each read that byte count as a crash. **Before diagnosing a
    stalled run, `pgrep -af check.sh` or `kill -0 <pid>`** — a stopped log plus a live
    process means "working", and the only honest wait is to poll the PID, not the file.
  A full run is ~25 minutes (pytest ~10, the audit leg ~11). The original note's real
  content still holds and is why the script is the entry point: `check.sh` exports
  `$HOME/.local/bin` onto PATH itself, so all 13 gates run.
- `pytest -q` emits **no `N passed` line** (a reporter plugin eats it). Count the progress
  characters in the `^[.sFEx]+ +\[ NN%\]` lines, or read the `Total coverage:` line.
- **A dead session leaves an ORPHANED `pytest` behind, and the next session's `check.sh`
  then runs concurrently with it — springing the coverage trap below without anyone
  starting a second run deliberately.** Seen for real at the start of the forty-eighth
  session: the forty-seventh's `check.sh` died with the session, but its `pytest` child was
  re-parented to PID 1 and kept running (`/tmp/check_p58.log`, 11:15); the new run started
  11:20 and its pytest was contending within one second. **Before starting any gate run,
  `pgrep -af "check.sh|bin/pytest"` and kill anything with `PPID 1`.** The resume protocol's
  "verify the working tree is clean" does not cover this — an orphan leaves no trace in
  `git status`.
- **Never run `pytest` concurrently with `./scripts/check.sh`.** Both drive `pytest-cov` and
  they contend on the same `.coverage` data file, so the *coverage figure* comes back badly
  wrong while the run still exits 0 — a concurrent run reported **89.67% with
  `practice_repo.py` at 68%**, where a clean serial run of the identical tree reported
  **90.37% and 99%**. The test counts stayed correct (2331/6/0 both times), which is what
  makes it convincing: it reads as a real coverage regression to be chased. Re-measure
  serially before believing any coverage drop.
- **`pre-commit` is not on PATH, and the fix is one PATH entry — not, as this note
  previously claimed, an unfixable hook-environment defect.** The binary is
  `.venv/bin/pre-commit` (no bare `pre-commit`, and `$HOME/.local/bin` does not have it).
  Invoking it as `.venv/bin/pre-commit` is *not enough*: its `mypy` and `import-linter`
  hooks are `system`-language, so they resolve their executable off **PATH**, which still
  lacks the venv — both then fail *"Executable ... not found"*. **Run it as
  `PATH="$PWD/.venv/bin:$PATH" .venv/bin/pre-commit run --all-files`** and all ten hooks
  pass (verified 2026-08-10, session 55, on the P5.8 tree). The old note's "verify in
  `check.sh` instead" advice still works but is the expensive path — it reaches those two
  tools by the same mechanism, having exported a bin dir onto PATH first.
- **`tsc -b` is incremental and a stale `node_modules/.tmp` hides real errors.**
  `web/tsconfig.test.json` was missing `jsx` since P5.8 chunk B — every test importing
  a `.tsx` fails TS6142 — and `npm run build` reported success anyway because the
  tsbuildinfo predated the test. **`rm -rf web/node_modules/.tmp` before believing a
  green build.** Related: a bare `npx tsc --noEmit -p tsconfig.json` is NOT the web
  typecheck; `tsc -b` covers a different (larger) project set and is the stricter gate.
- **`cd` in one Bash call persists into the next.** A `cd web` for an npx run leaves the
  following command running from `web/`, where `.venv/` and `.pre-commit-config.yaml` do not
  exist — which reads as "the venv is gone". Prefix with an absolute `cd /home/sico/Lemely`.
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
- **The ntfy server has attachments DISABLED — do not keep retrying them.** MISSION §7 says to
  PUT a file with a `Filename:` header; that endpoint returns **HTTP 400 `{"code":40014,
  "error":"invalid request: attachments not allowed"}`** on this instance (server-side config,
  not a request the orchestrator can fix). The JSON publish endpoint itself works fine (200).
  So: put the substance **in the message body** and use `click`/`actions` to link the artifact
  on GitHub instead of attaching it.
- **`ruff` excludes `lemely/db/migrations/versions` via `extend-exclude`** (pyproject), and
  **naming a migration file explicitly on the ruff command line overrides that exclusion** —
  so `ruff check lemely/db/migrations/versions/00NN_x.py` reports TC003 on the standard
  `from collections.abc import Sequence` header that *every* migration has and that
  `./scripts/check.sh` correctly ignores. Verified by running it against the already-merged
  `0012_study_plans` and getting the identical error. Lint migrations only through `check.sh`.
- **`pytest --collect-only` still runs the coverage plugin** and will clobber `.coverage` —
  pass `--no-cov`. Its `-q` output is one `path: N` line per file, so the total is
  `... | grep -E "^tests/.*: [0-9]+$" | awk -F': ' '{s+=$2} END {print s}'` (2350 at Phase 4).
- **The visual compare can never be pixel-clean**: `scripts/seed_e2e.py`'s `run_tag` is random
  per run, so every screen rendering a class name changes on every re-baseline. Read **`removed`**
  (must be 0), not `changed`, as the regression signal.

## Session journal
See `BUILD/JOURNAL.md` for the dated 3-6 line entries; decisions and rationale live in
`BUILD/DECISIONS.md` (D0.x/D1.x/D2.x). Superseded per-task narrative for Phases 0-2 has been
pruned from this file per MISSION §8b now that their reports are committed — see the git
history of this file, or the phase REPORT.md files, if the detail is ever needed again.
