# BUILD STATE — single source of truth

status: RUNNING            # RUNNING | COMPLETE | HALTED
current_phase: 5            # Phases 0-4 complete, merged and reported; Phase 5 in progress
last_updated: 2026-08-11T03:30:00Z   # **Forty-sixth session (this one): P5.6 AND P5.7 are COMPLETE — 8/12 Phase-5 tasks done. Resume at P5.8 (screens S-28..S-31).**
#                                    **P5.7 in one line:** the 3-device policy (D1.11) was already correct and atomic; what was missing was any way for a user to *see* it. Backend `allow_eviction` + a 409 challenge on login + `GET`/`DELETE /api/me/devices`, then G-10 on the login screen and G-11 at `/settings/devices`. All 13 gates green at **90.83%** with the new screen at **axe 0 / Lighthouse a11y 100**. D5.12 recorded before the code.
#                                    **Two P5.7 gaps left deliberately for P5.11/P5.9, do not mistake them for covered:** G-10 has **no audit-registry entry** (it needs an account already holding three live devices — a seed precondition, not a navigation), and **no nav entry anywhere reaches `/settings/devices`** (the teacher sidebar needs an icon-map addition, the parent portal has no sidebar).
#                                    **New environment fact, cost real work: `npx prettier --write` is NOT this repo's formatter.** `web/` has no prettier config and does not depend on it, so a bare run silently reformatted 8 files with **semicolons** against the house semicolon-free style. The web gates are typecheck + oxlint + build + vitest + impeccable detect — **none of them formats**. Never run a formatter the gate chain does not run.
#                                    Prior: **P5.6 is COMPLETE.**
#                                    No code was written this session and nothing was re-implemented: every P5.6 chunk was already committed, and the single outstanding item was the first full gate run since chunk A. It came back **all 13 gates PASS, 0 skipped, exit 0, 2767 tests, coverage 90.78%** (develop 90.18%, P5.5 90.57% — no drop), `alembic check` clean. **Nothing was red.** Five chunks of notification work — a migration, a transport, seven routes and three award seams — landed green on first full contact, which is the return on the per-chunk targeted test runs that preceded it. Branch `feature/phase-5-engagement`, not yet merged to develop.
#                                    **P5.7 is next and it is the first Phase-5 task with a frontend leg** (G-10 device-limit UI + G-11 device management), so MISSION §6.8 applies to it and not to anything P5.6 did: axe, Lighthouse ≥95, screenshots, `/impeccable audit`, visual compare. The 3-device session registry itself is Phase-1 work (D1.11) and already exists — read it before assuming a backend gap.
#                                    Prior context: **Forty-fourth session — P5.5 (announcements + exam calendar) is COMPLETE.** All three chunks were committed by prior sessions; this session re-implemented nothing and only ran the outstanding gates. Full `./scripts/check.sh`: **all 13 gates PASS, 0 skipped, exit 0, 2623 tests, coverage 90.57%** (develop 90.18% — no drop); `alembic check` clean. 6/12 Phase-5 tasks done. Branch `feature/phase-5-engagement`, not yet merged to develop.
#                                    **P5.4's `EXPECTED_TABLES` trap did not fire** — both new tables went into the set in the same commit as their `create_table`, which is what P5.4 told the next session to do. A written-down trap that costs nothing on its next encounter is the point of writing it down.
#                                    **Forty-fifth session: P5.6 chunks B and C1 built and committed** (C2a/b/c followed in the same session).
#                                    **D5.10 recorded before chunk B's code: a push carries NO payload** — an empty RFC 8030 body plus a VAPID auth header, with the service worker fetching the inbox over the authenticated API. That is D5.9 §1 stated on the wire rather than contradicted by it, and it keeps student notification content off Google/Mozilla/Apple push infrastructure. Zero new dependencies; `pywebpush` was measured (11 packages, incl. aiohttp) and hand-rolled RFC 8291 was rejected because **it could not be honestly verified here** — no test vector, no live push service, and a self-generated vector proves only self-agreement.
#                                    **Two traps this session paid for, both cheap next time.** (1) `Settings`/`NotificationTransport` in a router's `Annotated[...]` must be **runtime** imports, not `TYPE_CHECKING` — otherwise FastAPI hands pydantic an unresolvable ForwardRef and the route raises `PydanticUserError` on its *first request*, not at import. (2) A new `lemely/web/schemas_*.py` must be added to the `disallow_any_explicit` override list in `pyproject.toml`; every existing schemas module is already there.
#                                    **Previous (forty-third) session:** **Forty-third session — P5.4 (friends backend) is COMPLETE.** Its three code chunks were already committed by the two prior sessions; the only outstanding work was the gate run, and nothing was re-implemented. Full `./scripts/check.sh`: **all 13 gates PASS, 0 skipped, 2532 tests / 6 live-only skips / 0 failures, coverage 90.48%** (develop 90.18% — no drop); `alembic check` clean. 5/12 Phase-5 tasks done. Branch `feature/phase-5-engagement`, not yet merged to develop.
#                                    **The gate run found one real defect** (`72330b8`): `tests/test_db_schema.py` asserts exact set equality against a hand-maintained `EXPECTED_TABLES`, and migration 0015's `friendships` was never added to it. Fixed by extending the set — exact equality is what forces a new table to be acknowledged deliberately. **The generalisable form: a new table costs two edits, the migration and that set.** 0013 and 0014 added only columns, so P5.4 was the first chance in this phase for the trap to fire, and it fires ~10 minutes into the run. Make the `EXPECTED_TABLES` edit in the same chunk as the `create_table`.
#                                    **Method note worth keeping:** `check.sh` suppresses output for gates that pass, so a green log contains no pytest counts at all — read coverage with `.venv/bin/coverage report --precision=2` off the run it just did, and get the test count from `pytest --collect-only -q --no-cov`. Never re-run the suite for a number; a second run costs ~10 minutes and risks the concurrent-`.coverage` corruption noted below.
#                                    **Then continued into P5.5 (announcements), chunk A of three committed as `446e7fa`.** Two things a resuming session must not redo. **(1) P5.0's recon was wrong: the school-admin whole-school audience is NOT missing** — it has been fully built since P3.8/D3.14 (`school_wide`/`school_id`, `school_admin`-only, exposed on the teacher POST). Verified by reading `announcement_repo.py` and `routers/announcements.py`, so P5.5 is three parts, not four. That is the **fifth** Phase-5 instance of a note paraphrasing the codebase from memory and being wrong — D5.2, D5.3, D5.4, D5.5 are the others, and the standing rule holds: *read the model; where a note restates the code, the code wins.* **(2) There is no CAIE timetable data anywhere on this machine** (checked `Sources/` and the PaperScraper corpus), so the exam calendar ships as table + ingestion path + honest empty state, never invented dates.
#                                    **Resume at P5.5 chunk B** — the student announcement endpoints. The service layer is built and tested; chunk B is router/DTO/deps wiring. Read the P5.5 checklist lines, which carry the full brief. `./scripts/check.sh` has NOT been run since chunk A — run it before P5.5 is marked done.
gemini_spend_usd: 0.18429   # MEASURED from the real ledger `outputs/gemini_spend.json`
# (cumulative_usd 0.18428610, updated 2026-08-09T12:01:17Z), not carried forward. This field
# had drifted: it read **0.1612** at the start of the thirty-ninth session while the ledger —
# the Phase-0 persistent tracker that actually enforces the $8 cap — read 0.18429. The field
# is a hand-copied mirror of the ledger and nothing generates one from the other, so it is the
# field that was wrong, never the ledger. Phase 3 closed at $0.1586, so **Phase 4 spent
# $0.0257** across the whole phase (every automated test mocks Gemini; D4.3 made that
# structural). Re-read the ledger rather than this line before quoting a spend figure.

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

## Phase 5 — Engagement layer — IN PROGRESS (started 2026-08-09, fortieth session)
See MISSION §4 (Phase 5) + UI spec §4.6 (S-28..S-31), §4.5 (G-10..G-13), T-12.

### What P5.0 reconnaissance established (measured, not assumed — do not re-derive)
- **XP/streak schema already exists** (migration 0002) — see the corrected Phase-4 limitation
  above. Tables `xp_events` + `streaks`, enum `xpsource` with exactly the four MISSION sources.
  Zero behaviour attached. **No migration needed for core XP or streaks.**
- **Tables that exist and P5 can build on:** `announcements`, `notifications`, `devices`,
  `xp_events`, `streaks`, plus the `notification_preferences` work from migration 0008.
- **Tables that genuinely do NOT exist and P5 must add:** friendships, push subscriptions,
  leaderboard opt-out flag, announcement read-receipts. (`grep create_table` over
  `lemely/db/migrations/versions/` is the cheap way to re-check this.)
- **Announcements are teacher-write-only today.** `lemely/web/routers/announcements.py` mounts
  at prefix `/api/teacher/announcements` and exposes exactly POST / GET / DELETE. There is **no
  student-facing read route at all** — that is what "students cannot see announcements" means.
  School-admin → whole-school audience is also absent.
- **`notification_preferences` is wired to a service and a DTO but gates nothing.**
  `NotificationPreferencesService` exists (`lemely/db/notification_prefs_repo.py`), `deps.py`
  provides it, `routers/me.py` reads/writes it. What is missing is any *consumer* — no send path
  consults it, because no send path exists.
- **The student leaderboard screen already exists and is honestly empty.**
  `web/src/portals/student/screens/Standings.tsx` (route `student/board`) is wired to
  `GET /student/standings`; its header comment records that the friends/school/global boards and
  the 28-cell streak heatmap were *deliberately removed* rather than mocked, because
  `StandingsDTO` has no `boards` field and no backend existed. **P5 fills that gap; it does not
  start from a mock.** Subject standings there is already real.

### Task checklist
- [x] done — **P5.0** Reconnaissance + phase plan (this section); Phase-4 XP limitation corrected.
- [x] done — **P5.1** XP + streak + leaderboard **spec** recorded in `BUILD/DECISIONS.md` (D5.1)
      **before any implementation** — MISSION §4 Phase 5 mandates this ordering explicitly. Must
      fix: per-source award amounts, anti-farming caps, the streak day boundary + timezone,
      streak-freeze grant/consume rules, the weekly leaderboard window + reset, and opt-out
      semantics. Constrained by UI spec §1.4 (XP public / grades private) and MISSION §3
      ("leaderboards show XP, never grades").
- [x] done — **P5.2** XP engine backend, both chunks. **Full suite on the committed tree:
      exit 0, 6 live-only skips, 90.30% cov** (develop 90.18% — no drop); ruff, ruff format,
      mypy (186 files), lint-imports, `alembic check` all clean. `xp_repo.py` and
      `xp_awards.py` both 100% covered.
      - [x] **chunk A** (`e786657`) — migration 0013 + `lemely/db/xp_repo.py` (`XpService`:
            award / total_xp / xp_breakdown / streak, Cairo civil-date helper, per-source +
            global daily caps, lazy streak resolution with freeze grant/consume) + 42 tests.
            D5.2 recorded: the column is **`subject_code`** (String FK to `subjects.code`), not
            D5.1 §7's `subject_id` UUID — eight other subject-scoped tables key on the code and
            every award seam already carries one. `alembic check` clean **both directions**.
            **Trap found and fixed, worth not repeating:** the dev DB had the *pre-amendment*
            0013 (`subject_id`) applied, so `alembic check` failed while `pytest` passed — the
            tests build their schema fresh, the dev DB does not. After amending an
            **uncommitted** migration, drop its artifacts, `alembic stamp` the previous
            revision, and re-upgrade; otherwise the file and the DB silently disagree.
      - [x] **chunk B** (`8fc3bc4`) — the four award seams, all wired at the **router** layer
            (not inside the repo services: `XpService` owns its own sessionmaker and would
            otherwise interleave transactions with a service that has just committed;
            `quiz.py` already composed two services per endpoint, so this follows the house
            pattern). Every seam goes through the single fail-open helper
            `lemely/web/xp_awards.py::award_xp_safely`, which logs and swallows an XP failure
            so an already-committed student action can never be turned into an error response
            (D5.1 §3, "the learning wins") — proven with an injected failing double.
            `get_xp_service()` added to `deps.py` + `reset_singletons()`. Three internal
            service dataclasses (`SubmitResultRow`, `SessionView`, `ReviewOutcome`) grew a
            `subject_code` field; **no wire DTO changed**, so the frontend is untouched.
            **D5.3 — the defect worth remembering.** The paper seam's first cut deduped on the
            *attempt* id. `persist_correction` inserts a fresh `Attempt` every call, so that key
            is re-minted on every re-correction and the unique index never fires: a student
            re-running `/student/correct` on one PDF could farm **250 XP/day** (the 5/day cap),
            which is exactly what D5.1 §8 ("a paper can be re-marked … none of those may
            re-award XP") exists to prevent. Now keyed on `owned.id`, the **upload**. Verified
            by inversion — reverting the key fails both regression tests on `2 != 1` xp_events
            rows, and those tests also assert two `Attempt` rows exist so they cannot pass by
            the pipeline having declined to re-run. **The brief, not the spec, was wrong:** the
            orchestrator's task table paraphrased §8 and lost its meaning. Where a brief
            restates a spec, the spec wins.
            `flashcard_reviewed` is deliberately NOT deduped between two reviews of one card
            (repeat review is the point of SM-2); its control is the 60/day cap. Pinned by a
            test so nobody "fixes" it into the paper seam's shape.
- [x] done — **P5.3** Leaderboards backend, both chunks. **Full `./scripts/check.sh` on the
      committed tree: all 13 gates PASS, 0 skipped; coverage 90.43%** (develop 90.18% — no
      drop). `routers/leaderboard.py` and `schemas_leaderboard.py` 100% covered,
      `leaderboard_repo.py` 98%.
      - [x] **chunk A** (`e5c945b`) — migration 0014 (`student_profiles.leaderboard_opt_out`)
            + `lemely/db/leaderboard_repo.py`: the weekly window (D5.1 §6, Monday 00:00 →
            Sunday 23:59:59 Cairo, summed from `xp_events` every time — no denormalized
            column), class/school/global scopes, per-subject basis on
            `xp_events.subject_code`, own-row pinning, opt-out in the query's WHERE clause.
            The D5.1 §0 guard test compiles the emitted SQL and asserts it joins no marking
            table. **D5.4 — the brief was wrong about the schema:** it specified the school
            scope on `school_memberships`, which is *staff only* (`MembershipRole` has exactly
            `teacher`/`school_admin`); no student ever has such a row, so the school board
            would have been permanently empty and read as a data problem, not a defect.
            Students reach a school through `Seat` (`school_id` + `assigned_user_id`, status
            not `revoked`), as `class_repo`/`seat_repo` already do. Same failure mode as D5.2.
            Two smaller catches in the same chunk: `RANK() OVER (ORDER BY xp DESC, user_id)`
            broke ties into 1 and 2 — the tiebreak moved to the outer `order_by` so equal
            effort reads as equal standing; and the opt-out join must be an **outer** join
            with `coalesce(..., false)`, since a student who never onboarded has no
            `student_profiles` row and an inner join would have erased exactly them.
      - [x] **chunk B** (`3a2c445`) — `GET /api/student/leaderboard`
            (`scope=class|school|global`, `basis=total|<subject code>`, `class_id`, `limit`),
            student-role-only, in its own thin router; `leaderboard_opt_out` threaded through
            `student_profile_repo` → `me.py` → `StudentProfileDTO`; `get_leaderboard_service()`
            in `deps.py` + `reset_singletons()`.
            **The DTOs are structurally answer-only (D5.1 §0)** — no field shaped like a mark,
            grade or percentage *exists* on them, and `tests/test_schemas_leaderboard.py`
            introspects the field sets, so a well-meaning future addition fails a test instead
            of reaching the wire. `leaderboard_opt_out` is NOT NULL on the model, so an
            explicit `null` in `PATCH /me/profile` is a 422, never a coerced `False`.
            **D5.5 — the defect worth remembering.** `display_names_for()` first copied the
            codebase-wide `display_name or email` fallback (`quiz_taking_repo` and siblings
            each re-declare it). `users.display_name` is nullable at signup, so it fires for
            real users. That fallback is safe where the audience is one class; the **global
            board's audience is every student on the platform**, so the identical line
            broadcasts a real contact address to strangers. The query no longer selects
            `users.email` at all — unnamed students rank normally as `"Student"`. Pinned by a
            test asserting over the **response body** that no `@` appears anywhere in it.
            Errors: not-enrolled-in-the-requested-class is **403 and never an existence
            oracle** (the service checks enrolment only, so "no such class" and "not your
            class" are indistinguishable); school-scope-with-no-school is a **successful
            `unavailable`** response, never a 404 and never a falsely empty board, which would
            assert the untrue "nobody scored this week".
            Judged and deliberately not fixed: `board()`'s three queries are not pinned to one
            snapshot, so a concurrent award can make the viewer's row disagree with the top-N
            by a few XP. Self-corrects next request; a leaderboard is an inherently stale read.
      - **Not done here, by design:** the **friends** scope waits on P5.4's table, and the
        consuming screen waits on P5.8. `web/src/portals/student/screens/Standings.tsx`
        (`student/board`) is still on `GET /student/standings`, whose `StandingsDTO` has no
        `boards` field — nothing frontend changed this task.
- [x] done — **P5.4** Friends backend + migration (requests in/out, accept, remove, privacy).
      **Full `./scripts/check.sh` on the committed tree: all 13 gates PASS, 0 skipped;
      2532 tests, 6 live-only skips, 0 failures; coverage 90.48%** (develop 90.18%,
      P5.3 90.43% — no drop). `alembic check` clean.
      **One defect the gate run found, fixed as `72330b8`:** `tests/test_db_schema.py`
      asserts *exact set equality* between `Base.metadata.tables` and a hand-maintained
      `EXPECTED_TABLES`; migration 0015's `friendships` was never added to it, so the
      suite failed on `Extra items in the left set: 'friendships'`. Fixed by extending the
      set, not by loosening the assertion — exact equality is the whole point of that test.
      **Worth not re-learning: a new table costs two edits, the migration and this set.**
      P5.2's and P5.3's migrations (0013, 0014) added only *columns*, so this is the first
      time in Phase 5 the trap could fire, and it fires ~10 minutes into the gate run.
      Add the table to `EXPECTED_TABLES` in the same chunk that writes the `create_table`.
      **Also lands the leaderboard's fourth scope**: add `LeaderboardScope.friends` to
      `lemely/db/leaderboard_repo.py` once the friendships table exists. Everything else it
      needs is built — follow the existing `_membership_subquery` shape, keep the opt-out in
      the WHERE clause, and extend the D5.1 §0 emitted-SQL guard test to the new scope.
      Three code chunks, all committed by earlier sessions and none re-implemented since:
      `7397df0` (chunk A), `71d1a9b` (chunk B), `63a4bbc` (the D5.7 race fix). The
      forty-third session ran the outstanding gates and closed the task.
      - [x] **D5.7 fix** (`63a4bbc`) — `FriendService.request`'s genuinely-new-pair INSERT had no
            `IntegrityError` handling, and sat bare inside `with session.begin()`, so a lost race
            on `uq_friendships_pair` surfaced at COMMIT — after `request()` returned, outside any
            frame `routers/friends.py` can catch. Two tabs POSTing the same first-ever friend code:
            one 201, one raw **500**. Now `session.begin_nested()` + catch, resolving the winner
            through the *same* `_resolve_existing_pair` helper the sequential path uses so the two
            cannot drift. Not an integrity defect — the constraint always won (D5.6 holds).
            **The prior session's inversion claim was wrong and D5.7 is corrected in place:**
            re-running it here (savepoint → `if True:`) fails both tests, but the `IntegrityError`
            never reaches COMMIT — the failing `flush()` **poisons the enclosing transaction**, so
            the recovery SELECT dies first with `InvalidRequestError`. Same 500; the lesson is
            different and worth keeping: **a savepoint is what makes the error recoverable, not
            merely catchable.** Once the outer transaction is poisoned there is nothing left to
            re-read with. *Verify an inherited "proven by inversion" note before repeating it —
            a claim about a test is not the test.*
      - [x] **chunk A** (`7397df0`) — migration 0015 (`friendships` + `users.friend_code`) +
            `lemely/db/friend_repo.py` (`FriendService`) + `LeaderboardScope.friends` + tests.
            D5.6 recorded. One friendship is one row (canonical `pair_low`/`pair_high`, unique
            index + three CHECKs), so the reciprocal row is a database error, pinned by a test
            that inserts through the session rather than the service.
      - [x] **chunk B** (`71d1a9b`) — `GET/POST/DELETE /api/student/friends` in its own thin
            router mirroring P5.3's `leaderboard.py`; `schemas_friends.py`; deps; tests.
            Identity is structurally the token's `sub` on every route — no caller-supplied user
            id exists on this router. Two defects found while wiring: `POST /requests` derived
            the other party from `addressee_id`, which is the *caller* in the crossed-requests
            case (now derived from whichever end the caller is not on, and the response reports
            `accepted` there); and `accept` matched the returned row against the raw path string,
            but `uuid.UUID` accepts uppercase/braces/`urn:uuid:` forms that normalise
            differently — those would have accepted and then fallen through to a 500.
      Design fixed before implementation (to be recorded as D5.6): **`users` has no
      `username` column**, so S-30's "add by username" is unbuildable as written; a
      nullable-unique `users.friend_code` (8 chars, ambiguity-free alphabet, minted lazily)
      serves both the typed code and the invite link, and avoids the two bad alternatives —
      searching by `display_name` (not unique, and lets a student enumerate strangers) and
      searching by email (the exact leak D5.5 killed). One row per pair, canonicalised into
      `pair_low`/`pair_high` with a unique index + three CHECK constraints, so a duplicate or
      reciprocal friendship is a database error rather than a service-layer convention
      (D5.1 §8's reasoning applied to a second table).
- [x] done — **P5.5** Announcements: student-facing read + read-receipts, school-admin audience,
      auto-populated official CAIE session dates for the exam calendar.
      Backend only — the consuming screens are P5.8/P5.9. UI spec §S-28 (line 725) is the
      product truth for what the student surface must eventually hold.
      **Closed by the forty-fourth session's gate run — nothing was re-implemented.** All three
      chunks were already committed; the only outstanding work was the gates. Full
      `./scripts/check.sh`: **all 13 gates PASS, 0 skipped, exit 0**; **2623 tests**;
      **coverage 90.57%** (develop 90.18%, P5.4 90.48% — no drop); `alembic check` clean.
      **P5.4's `EXPECTED_TABLES` trap did NOT fire this time** — chunks A and C each added
      their table (`announcement_reads`, `exam_dates`) to the set in the same commit as the
      `create_table`, which is exactly the fix P5.4 wrote down. The lesson held on first
      contact; keep doing it.
      **P5.0's reconnaissance was WRONG on one of the three bullets — corrected here by reading
      the code, and this is the fifth instance in Phase 5 of the same failure mode.** P5.0 wrote
      that the "school-admin → whole-school audience is also absent". **It is not: it has been
      fully built since P3.8/D3.14.** `AnnouncementService.create` takes `school_wide` +
      `school_id`, restricts it to `Role.school_admin`, validates the target through
      `ClassService.member_school_ids`, and writes the `school_id`-set/`class_id`-NULL row; the
      router exposes it as `schoolWide`/`schoolId` on `POST /api/teacher/announcements`. Do not
      rebuild it. Verified in `lemely/db/announcement_repo.py:141-230` and
      `lemely/web/routers/announcements.py:100-134`. **So P5.5 is a three-part task, not four.**
      What P5.0 got right, re-verified: `announcements`/`notifications` exist, the router mounts
      only at `/api/teacher/announcements` with exactly POST/GET/DELETE, and there is genuinely
      **no student-facing read route at all**.
      - [x] **chunk A** (`446e7fa`) — migration 0016 (`announcement_reads`) + the student read
            path on `AnnouncementService` (`list_for_student`, `unread_count_for_student`,
            `mark_read`, `StudentAnnouncementRow`, `DEFAULT_STUDENT_LIMIT`) + 17 tests.
            `alembic check` clean **both directions**; ruff/format/mypy(195 files) clean; the
            three related test files pass (57 tests). **Not yet run: the full suite / `check.sh`.**
            The school arm keys on **`Seat`, not `SchoolMembership`** (D5.4), and `publish_at`
            is now honoured for students but deliberately **not** for the author's own list.
            **Both guards verified by inversion, not asserted:** swapping the school arm back to
            `SchoolMembership` fails `test_school_wide_announcement_reaches_a_seated_student`
            with the student seeing an *empty list* — the exact "reads as a data problem"
            shape D5.4 warns about; replacing the `publish_at` predicate with `sa.true()` fails
            2 tests. `announcement_reads` went into `EXPECTED_TABLES` in the same commit.
            The clock is now injected (`now=`) and the docstring that asserted its absence was
            corrected rather than left contradicting the code.
      - [x] **chunk B** (`51657f8`) — the student announcement endpoints:
            `lemely/web/routers/student_announcements.py` (`GET ""`, `GET "/unread-count"`,
            `POST "/{id}/read"`), `schemas_announcements_student.py`, app wiring, 24 route
            tests + 11 schema-introspection tests. **`deps.py` needed no new entry** —
            `get_announcement_service` has existed since P3.8 and is reused, so the student
            and their teacher share one clock and cannot disagree about whether a scheduled
            announcement is published; `reset_singletons()` already covered it. The brief
            predicted a deps pair here and was wrong; the code won.
            Two guards **verified by inversion**: `publishedAt` is the *effective* time
            (`publish_at or created_at`) and the only time field on the wire — shipping
            `created_at` too would let a screen sort by typing time and disagree with the
            server's ordering; and the read receipt echoes the **canonical** id, because
            `uuid.UUID` accepts `urn:uuid:`/uppercase/braces forms and echoing the raw path
            hands back an id that never matches the list response (P5.4 chunk B's lesson,
            second sighting).
      - [x] **chunk C** (`5713238`) — the exam calendar. Migration 0017 (`exam_dates`)
            + `lemely/db/exam_calendar_repo.py` (`ExamCalendarService`: `ingest`,
            `parse_timetable_payload`, `calendar_for_student`) + `schemas_exam_calendar.py`
            + `routers/exam_calendar.py` (`GET /api/student/exam-calendar`, read-only) +
            deps/`reset_singletons`/app wiring + 41 tests. **D5.8 recorded** with the full
            rationale. `alembic check` clean both directions.
            **`exam_dates` went into `EXPECTED_TABLES` in the same edit as the
            `create_table`** — P5.4's trap, not re-sprung.
            **The table ships empty and that is the deliverable**, not a gap: no CAIE
            timetable exists on this machine, so ingestion is built and *nothing* populates
            a row. Three empty causes are kept apart (`no_enrolment` / `no_timetable` /
            per-paper `no_session`) because collapsing the first two would blame Cambridge
            for a blank the student can fill in themselves. The grain is the paper
            **variant**, with `paper_number` stored beside it (the only key the student's
            declared papers can join on) — number-grain storage would have forced the
            ingester to discard real dates. Past dates are deliberately **not** filtered and
            the service takes **no clock**: dropping them would empty a calendar mid-series
            and make `no_timetable` fire when we hold all the data.
            Two guards **verified by inversion**: collapsing `no_enrolment` into
            `no_timetable` fails 2 tests, and dropping the self-contradicting-batch rejection
            fails another. Two real traps found while building — `sa.Enum(..., create_type=
            False)` silently ignores the flag and re-`CREATE TYPE`s an existing enum (use
            `sa.dialects.postgresql.ENUM`; `pytest` passed while `alembic upgrade` failed),
            and **this FastAPI version wraps included routers in an opaque `_IncludedRouter`
            with no `.path`**, so a route-introspection test over `app.routes` finds nothing
            and passes for the wrong reason — read `app.openapi()["paths"]` instead.
            **Honest gap carried to the Phase-5 limitations:** there is no CLI wrapper around
            `ingest` yet (service + parser only), deliberately not built speculatively while
            no document exists to feed it.
- [x] done — **P5.6** Notifications inbox + web push (VAPID) with a headless-testable
      transport, and make `notification_preferences` actually gate delivery.
      **Closed by the forty-sixth session's gate run — nothing was re-implemented.** All
      five chunks (spec, A, B, C1, C2a/b/c) were already committed; the only outstanding
      work was the first full run since chunk A. Full `./scripts/check.sh`: **all 13 gates
      PASS, 0 skipped, exit 0**; **2767 tests**; **coverage 90.78%** (develop 90.18%,
      P5.5 90.57% — no drop); `alembic check` clean. **Nothing was red** — the three
      seams, the transport and the routes all landed green on first full contact, which
      is what the per-chunk targeted test runs were buying.
      Backend only — the consuming screens are P5.9 (G-12/G-13). MISSION §4 Phase-5 names the
      four triggers: grades ready, new announcement, streak about to break, study-plan reminder,
      plus at-risk alerts to the teacher and (if opted in) the parent.
      **Recon done 2026-08-10 by reading the models, not by paraphrasing a note** (this is the
      sixth Phase-5 task where that distinction mattered — D5.2/D5.4/D5.5, P5.5's own header, and
      the two deps predictions that were wrong):
      - **`notifications` exists and has ZERO writers.** `lemely/db/models/ops.py:140` —
        `id`/`user_id`/`type`/`title`/`body`/`payload` (JSONB, defaults `{}`)/`read_at`, indexed
        on `(user_id, read_at)`. `grep -rln "Notification("` over `lemely/` excluding `models/`
        returns **nothing**: no repo, no service, no route, no call site. So the inbox is a
        genuinely empty build, not a retrofit — but **no migration is needed for the inbox
        itself**, exactly like P5.2's XP tables.
      - **`NotificationType` has exactly five values** (`enums.py:164`): `grade_ready`,
        `announcement`, `streak_warning`, `study_plan_reminder`, `at_risk_alert`.
      - **`notification_preferences` already has one boolean per type, same five names**
        (`ops.py:335`), all `NOT NULL DEFAULT true`, **plus `quiet_hours_start`/`quiet_hours_end`
        (nullable `Time`)**. So "make preferences gate delivery" needs **no schema work** — the
        toggles are there and `NotificationPreferencesService.get/set`
        (`lemely/db/notification_prefs_repo.py`) already reads them. What is missing is a
        *consumer*, because no send path exists. The service's `get` returns an all-defaults row
        for a user with no row, so the gate must treat "never configured" as opted-**in**.
      - **Nothing anywhere mentions VAPID or push subscriptions** — `grep -rlin
        "vapid|push_subscription"` over `lemely/` and `web/src/` is empty. **The push
        subscription table is the one genuine migration this task needs** (P5.0 listed it, and
        that bullet is confirmed).
      **Design to fix in DECISIONS.md before implementing** (P5.1 set this precedent and MISSION
      §4 mandates it for the engagement layer): the transport seam. Web push cannot be sent from
      a headless test, so define a `NotificationTransport` protocol with a real VAPID
      implementation and a recording in-memory double, choose it in `deps.py`, and make the
      **inbox row the source of truth with push as a best-effort side effect** — a failed push
      must never lose a notification or fail the action that produced it (D5.1 §3's fail-open
      reasoning, already implemented once in `lemely/web/xp_awards.py::award_xp_safely`).
      Also decide: quiet-hours semantics (suppress the *push*, never the inbox row — the student
      must not silently lose a notification because it arrived at 2am), and whether
      `at_risk_alert` to a **parent** consults the parent's own preference row (it must — the
      opt-in in MISSION §4 is the parent's, not the student's).
      **Traps already paid for, do not re-spring:** a new table costs **two** edits, the
      migration and `EXPECTED_TABLES` in `tests/test_db_schema.py` (P5.4) — make both in the same
      chunk; use `sa.dialects.postgresql.ENUM` if a new enum is involved, because
      `sa.Enum(..., create_type=False)` silently re-`CREATE TYPE`s and passes pytest while
      `alembic upgrade` fails (P5.5 chunk C); and a route-introspection test must read
      `app.openapi()["paths"]`, not `app.routes`, which this FastAPI version wraps in an opaque
      `_IncludedRouter` with no `.path` so the test passes for the wrong reason (P5.5 chunk C).
      Check whether `get_notification_preferences_service` already exists in `deps.py` before
      adding one — the last two briefs predicted a deps entry that was already there.
      - [x] **spec** (`369ef68`) — **D5.9 recorded before any code**, per MISSION §4. Load-bearing
            calls: the inbox row is the source of truth and push is a best-effort side effect that
            can never fail the action producing it; **a type toggle off suppresses the row too**
            (content preference) while **quiet hours suppress only the push** (timing preference,
            row still written) — safe precisely because a notification is always a pointer and
            never the data; a missing prefs row means opted-**in**; parent at-risk alerts read the
            **parent's** prefs so a student cannot silence alerts about themselves; VAPID keys
            absent ⇒ transport reports itself unavailable rather than erroring (this machine has
            no keys); a 404/410 from a push service **deletes** the subscription; `grade_ready`
            dedupes on the **upload**, not the attempt (D5.3 written down before it can recur);
            and — **the honest gap** — `streak_warning`/`study_plan_reminder` are time-triggered
            with **no scheduler in this build**, so they ship as service methods nothing invokes
            on a timer. Do not build a scheduler daemon; carry it to the Phase-5 limitations.
      - [x] **chunk A** (`e9c3ca1`) — migration 0018 + `lemely/db/notification_repo.py`
            (`NotificationService`: create/mark_read/mark_all_read/list_for_user/counts,
            subscribe/unsubscribe/forget_endpoint/subscriptions_for) + 60 tests.
            ruff/format/mypy(203 files)/lint-imports clean; `alembic check` clean **both
            directions**; the three related test files pass (71 tests).
            **Not yet run: the full suite / `check.sh`.**
            **The brief was wrong that the inbox needs no migration** — it needs no *table*, but
            D5.9 §6's per-upload idempotency has nowhere to live on the existing row, so
            `notifications` gained a `dedupe_key` column mirroring 0013's `xp_events.dedupe_key`:
            nullable, **partial** unique index `WHERE dedupe_key IS NOT NULL` so the types with no
            natural key (two study-plan reminders a week apart are two real reminders) stay
            exempt. Sixth instance this phase of the code beating the note.
            **D5.9 §2's split verified by inversion, both halves:** forcing the preference gate
            to always-enabled fails 2 tests; making quiet hours drop the row as well as the push
            fails `test_quiet_hours_write_the_row_and_only_block_the_push`.
            `push_subscriptions` went into `EXPECTED_TABLES` **in the same commit** — third table
            running to avoid P5.4's trap.
            **Worth not re-deriving: Cairo is UTC+3 in August, not +2** (Egypt reinstated summer
            time in 2023), so quiet hours convert through `ZoneInfo` and the test pins an August
            *and* a January instant. A hardcoded offset is wrong by exactly one hour for half the
            year. Also: `Session.execute` is typed as returning `Result`, which has **no
            `rowcount`** — narrow through a one-attribute `Protocol`, since mypy here forbids
            explicit `Any` so `cast("CursorResult[Any]", ...)` fails the gate.
      - [x] **chunk B** (`58fa04c`) — the transport seam: `lemely/web/push.py`
            (`NotificationTransport` protocol, `VapidPushTransport`,
            `RecordingPushTransport`, `PushResult`/`PushOutcome`), `PushSettings` in
            `lemely/runtime/config.py`, `get_push_transport` + `get_notification_service`
            in `deps.py` + `reset_singletons()`, 37 tests.
            ruff/format/mypy(204 files)/lint-imports clean. **Not yet run: the full
            suite / `check.sh`.**
            **D5.10 recorded before the code, and it supersedes D5.9 §4's
            `send(subscription, payload)` sketch: a push carries NO payload.** Empty
            RFC 8030 body + RFC 8292 VAPID `Authorization` header; the service worker
            fetches the inbox over the authenticated API. That is D5.9 §1 (inbox row is
            the source of truth, push is one delivery of it) stated on the wire instead
            of contradicted by it, and it keeps student notification titles/bodies off
            Google/Mozilla/Apple push infrastructure entirely.
            **The alternative was measured:** `pywebpush` resolves cleanly here
            (`uv pip install --dry-run`) but adds **11 packages including `aiohttp`** — a
            second HTTP stack beside the existing `httpx`. Hand-rolling RFC 8291
            (ECDH/HKDF/AES128GCM) was rejected for the stronger reason that **it could
            not be honestly verified on this machine**: content encryption is only
            provable against a published test vector or a live push service, and a
            self-generated vector proves the code agrees with itself. Payload-less push
            needs neither — the ES256 assertion is verified *by decoding it with the
            public key*. **Zero new dependencies** (`pyjwt[crypto]` in the `db` extra,
            `httpx` in `web`).
            Absent VAPID keys are a supported state (D5.9 §4): `available` False, every
            send `unavailable`, one log line per process. `get_push_transport` returns the
            **real** transport even unconfigured — substituting a double there would leave
            the path this build actually runs untested.
            **Three guards verified by inversion:** attaching a payload fails
            `test_the_push_body_is_empty`; folding 5xx into `expired` fails 5 tests
            (a 503 must not evict a healthy device); signing the full endpoint instead of
            its origin fails 3 — the subscription path is the nearest thing a subscription
            has to a secret and must stay out of the assertion.
            `get_notification_service` composes the **existing**
            `get_notification_prefs_service` singleton (the brief's "check whether it
            already exists" warning was right, it did) so the delivery gate and the
            endpoint that edits it cannot disagree (D5.9 §2).
            **Carry to the Phase-5 limitations:** with no payload, a service worker must
            fetch before it can render, so a push arriving offline (or whose fetch fails)
            shows a generic "You have a new notification" — browsers require *some*
            notification per push. This is P5.9's service-worker brief.
      - [x] **chunk C1** (`dbc5d9f`) — the routes and the fail-open helper.
            `lemely/web/routers/notifications.py` (`GET ""`, `GET /counts`,
            `POST /{id}/read`, `POST /read-all`, `GET /push/config`,
            `POST /push/subscribe`, `POST /push/unsubscribe`),
            `schemas_notifications.py`, `lemely/web/notify.py` (`notify_safely`), app
            wiring, 49 tests (31 route + 18 helper). ruff/format/mypy(207)/lint-imports
            clean; the four notification test files pass together (126 tests).
            **Not yet run: the full suite / `check.sh`.**
            **The router is deliberately role-agnostic**, unlike every Phase-5 router it
            mirrors: `at_risk_alert` is addressed to a teacher and a parent, so a
            `Role.student` gate would have built an inbox two of its three intended
            readers cannot open. Pinned by a test over four roles.
            **New trap, cost real debugging, do not re-spring:** `Settings` and
            `NotificationTransport` must be imported at **runtime**, not under
            `TYPE_CHECKING`. FastAPI resolves every `Annotated[...]` parameter through
            pydantic, and with `from __future__ import annotations` a type-checking-only
            name leaves an unresolvable ForwardRef — the route then raises
            `PydanticUserError` **on its first request**, not at import, which is a much
            later and more confusing place to find out. `ruff`'s TC001 wants the
            opposite and is overridden with a reasoned `noqa`.
            Also: `lemely.web.schemas_notifications` had to join the
            `disallow_any_explicit` override list in `pyproject.toml` — pydantic's mypy
            plugin injects `Any` into generated `__init__`s, and **every** schemas module
            is already on that list. A new `schemas_*.py` costs that edit too.
            Behaviour worth keeping: subscribing is accepted with **no VAPID keys**
            (a subscription is a durable fact about a browser; refusing it would force
            every user to re-subscribe the day keys arrive); `removed: false` for someone
            else's endpoint is a **success**, not a 404 that would reveal ownership; the
            wire payload is `dict[str, str]` and **coerced, not rejected**, on read,
            because an inbox that 500s over one odd row is worse than a stringified id.
      - [x] **chunk C2a** (`78d58a0`) — the `grade_ready` seam. `notify_safely` in
            `/student/correct` immediately after `award_xp_safely`, dedupe on the
            **upload** (D5.9 §6 / D5.3). Verified by inversion: an attempt key fails
            `test_re_correcting_the_same_paper_does_not_re_notify`, which also asserts
            two `Attempt` rows so it cannot pass by the pipeline declining to re-run.
            Body says "Paper 4 Variant 1", never "Paper 4/1" — a slash between two
            small integers reads as a mark out of a total on a lock screen.
            New `tests/test_web_notify_seams.py` (6 tests here, 18 by end of C2).
            **Trap found: a substring scan over a payload containing a UUID is a test
            that fails on the seed** — "67" appears in a random UUID about a third of
            the time, which is what made the first run intermittently red. Assert the
            payload structurally; scan only the human-readable strings.
      - [x] **chunk C2b** (`965a242`) — the `announcement` seam, plus
            `AnnouncementService.student_recipients`: `list_for_student`'s predicate
            read in the other direction, so the seam and the student read path share
            one definition of "the audience". The recon was right that no such method
            existed for the school arm.
            Two guards **verified by inversion**: swapping the school arm to
            `SchoolMembership` fails the seated-student test with an empty audience
            (D5.4's "reads as a data problem" shape); dropping the future-`publish_at`
            guard fails `test_a_scheduled_announcement_notifies_nobody_yet`.
            Naive `publish_at` (the router parses an offset-less ISO string) is
            normalised to UTC — this runs **outside** `notify_safely`, so an
            unnormalised value would TypeError and 500 an announcement already written.
            **A first cut was removed for being justified by a false comment**: the key
            was `f"{announcement_id}:{recipient}"` on the reasoning that otherwise the
            first student notified suppresses the rest. Inversion disproved it —
            migration 0018's unique index is already `(user_id, type, dedupe_key)`, so
            the recipient half of D5.9 §6's pair comes from the index. Key is now the
            announcement id alone. **Generalisable: before writing the reason a guard
            exists, check whether something else already provides it.**
      - [x] **chunk C2c** (`c1792fd`) — the `at_risk_alert` seam and **D5.11**
            (recorded before the code, per MISSION §4). Seam is the post-correction
            point; dedupe on `(student, reason, Cairo civil date)` via
            `civil_date_in_zone` — at-risk is a *state*, so an upload key would send a
            teacher of thirty students one alert per upload. Two inversions, each
            landing on exactly one test: `flag.summary` as the body (it renders
            percentages and predicted grades) fails the no-evidence assertion; no
            dedupe key fails the second-paper-same-day test. D5.9 §3 pinned from both
            sides — a student turning `at_risk_alert` off does **not** silence their
            teacher or parent, and the parent's own row gates the parent's alert.
            **The recon was wrong about recipients (seventh time this phase the code
            beat a note): `ClassService.student_classes` does NOT reach the teacher
            id** — `StudentClassRow` is class_id/name/subject_code/school_name. Two
            narrow readers added instead (`teachers_for_student`, `display_name_for`)
            rather than widening a row the parent portal renders.
            **Rule 3 (≥14 days inactive) cannot fire at this seam** — a student who
            just uploaded is by definition active — so the reason most likely to
            matter for a *disengaging* student is the one this build cannot deliver.
            Joins D5.9 §5's no-scheduler limitation; **carry to the Phase-5
            limitations**.
            **Process trap that cost real work: `git checkout <file>` to revert an
            inversion also discarded ~80 lines of uncommitted real work in the same
            file.** Copy the file to /tmp before inverting, restore with `cp`, and
            invert one thing at a time — two simultaneous inversions produced a
            NameError that failed four tests and proved nothing about either.
      - [x] done — `./scripts/check.sh`, the first full run since chunk A: **13/13 PASS,
            0 skipped, exit 0, 2767 tests, 90.78% coverage**, `alembic check` clean.
            The C2 recon below is kept for reference; all of it is now spent.
            **Recon done 2026-08-10, use it rather than re-deriving:**
            - **`grade_ready`** — easiest, do it first. The seam is
              `lemely/web/routers/student.py:735`, immediately after the existing
              `award_xp_safely(..., seam="paper_corrected")` call. Recipient is
              `auth.user_id`; **dedupe on `str(owned.id)` — the upload, never the
              attempt** (D5.9 §6 / D5.3: `persist_correction` mints a fresh `Attempt`
              every run, so an attempt key re-fires on every re-correction of one PDF).
              Payload carries the upload id; **never a mark** (D5.9 §2).
            - **`announcement`** — the seam is `create_announcement` in
              `lemely/web/routers/announcements.py:100`, after `service.create` returns
              its rows. **Recipient resolution does not exist yet and is the real work
              here.** For a class row, `ClassService.roster(caller_id, caller_role,
              class_id)` works directly and the author's ownership is already proven by
              the create that just succeeded. **For a `school_wide` row there is no
              method at all** — the audience is every student holding a non-revoked
              `Seat` in that school (D5.4: students reach a school through `Seat`, never
              `SchoolMembership`), and `seat_repo.py` exposes only
              create/available/list_admin_schools/seat_usage/invite/revoke. Add one
              narrow reader (to `AnnouncementService`, beside `list_for_student`, whose
              audience logic is the same predicate in the other direction) rather than a
              second independently-derived query. Dedupe on
              `f"{announcement_id}:{user_id}"` (D5.9 §6).
            - **`at_risk_alert`** — the hardest, and **scope it honestly**. At-risk is
              computed **on read** today (`assess_at_risk` called from
              `routers/classes.py:203/306`), so there is no existing event to hang this
              on. The defensible seam is the same post-correction point as `grade_ready`:
              a new paper is exactly what can change rule 1 (declining trend) and rule 2
              (below target). **Rule 3 (≥14 days inactive) is time-triggered and cannot
              fire here** — it joins `streak_warning`/`study_plan_reminder` in D5.9 §5's
              no-scheduler limitation, and must be stated as such, not quietly omitted.
              Recipients: the student's teachers via `ClassService.student_classes(
              student_id)` (it joins `SchoolClass`, so the teacher id is reachable), and
              the parents via `ParentLinkService.list_parents(student_id)`.
              **The parent's own `notification_preferences.at_risk_alert` is what gates
              the parent's row (D5.9 §3)** — `notify_safely` already does this correctly
              because the gate reads the *recipient's* prefs, but a test must pin it, or
              a student could silence alerts about themselves.
            **If C2 turns out larger than one session, split it: C2a `grade_ready`
            (small, self-contained), C2b `announcement`, C2c `at_risk_alert`.** Committing
            `grade_ready` alone is a real increment; do not hold it hostage to the other
            two.
- [x] done — **P5.7** 3-device limit enforced in the UI (G-10) + device management (G-11).
      **Full `./scripts/check.sh` on the committed tree: all 13 gates PASS, 0 skipped,
      exit 0; 2789 tests; coverage 90.83%** (develop 90.18%, P5.6 90.78% — no drop);
      `alembic check` clean. **MISSION §6.8 satisfied for the new screen, measured not
      assumed:** `/settings/devices` audited as G-11 — **axe 0 violations at every
      severity** (critical/serious/moderate/minor all 0), **Lighthouse accessibility 100**
      (performance 87, best-practices 100), screenshots at all three breakpoints
      (380/768/1440), and the responsive summary carries **zero** horizontal-scroll
      violations. 8/12 Phase-5 tasks done.
      **Recon done 2026-08-10 by reading the code** (`lemely/db/device_repo.py`,
      `lemely/auth/service.py:123-140`, `lemely/web/routers/auth.py`): the **policy already
      exists and is correct** — D1.11's `DeviceRegistry.register_login` locks the user row
      `FOR UPDATE`, registers, and evicts the oldest beyond `MAX_DEVICES = 3` atomically;
      `deps.get_auth_context` checks liveness per request. **`MAX_DEVICES` needs no change and
      no migration is needed.** What is genuinely missing is exactly two things: **no route
      exposes a user's devices at all** (G-11's list + individual sign-out), and **eviction is
      silent** — `DeviceRegistration.evicted_session_ids` exists but `_register_device` drops it,
      so a client cannot know a device was signed out. The SPA already mints and sends
      `deviceId` (`web/src/lib/auth/storage.ts`), so the slot-reuse path is wired end to end.
      **D5.12 recorded before any code.** Load-bearing: the device list is **never** shown to an
      unauthenticated caller (that would enumerate a stranger's browsers from an email alone), so
      G-10 is a **409 challenge on the login itself** — credentials proven first, no token minted,
      nothing evicted — confirmed by re-sending the login with `confirmDeviceEviction: true`;
      "would this evict?" is answered **inside** the existing `FOR UPDATE` transaction via
      `allow_eviction: bool = True` (a preflight query would be a TOCTOU between two tabs); a
      re-login on a known `client_device_id` is never a challenge; and **rough location is
      deliberately absent** — no geo-IP source and no stored IP exist, and UI spec §1.4 forbids
      inventing the one field the user would decide on. Carry that to the Phase-5 limitations.
      - [x] **chunk A** (`5660cbf`) — `allow_eviction` + `DeviceLimitReachedError` in
            `device_repo.py`, threaded through `AuthService.login`
            (`confirm_device_eviction`), the **409** on `POST /api/auth/login`, and
            `GET`/`DELETE /api/me/devices` reusing the existing idempotent `revoke`.
            New `lemely/web/schemas_devices.py` + `lemely/web/devices.py` (one projector,
            shared by the challenge and the list, so the two surfaces cannot describe the
            same device differently). `AuthContext` grew `session_id` — it was already on
            the claims and already checked for liveness, but never carried, so nothing
            could mark "this device is the one you are using". 22 new tests (4 registry,
            18 route). ruff/format/mypy(209)/lint-imports clean; the seven related test
            files pass together (156 tests). **Not yet run: the full suite / `check.sh`.**
            **No migration and no `EXPECTED_TABLES` edit** — the `devices` table is
            Phase-1's and unchanged. `schemas_devices` **did** need the
            `disallow_any_explicit` override in `pyproject.toml` (P5.6 C1's trap, second
            sighting: every `schemas_*.py` costs that edit).
            **Two guards verified by inversion**, one file at a time with a `/tmp` copy
            (P5.6 C2c's process trap, not re-sprung): dropping the `allow_eviction` check
            fails the two registry tests; hardcoding the login's confirm flag fails three
            route tests. **The third inversion is the one worth keeping** — it exposed a
            test that passed for the wrong reason: `test_the_challenge_carries_no_location_
            field` scanned the response body for "location", and a 200 body trivially
            contains none either, so it would have stayed green with the challenge gone.
            It now asserts the 409 first. *A negative assertion needs a positive one
            beside it, or it proves only that the response was short.*
            **Scope call recorded in the code, not just here:** the OTP path keeps
            evicting silently, because the code is single-use and a challenge the caller
            re-sent confirmed would fail on a spent code and cost the parent a second SMS.
            Parents on a fourth device get D1.11's old behaviour — Phase-5 limitation.
      - [x] **chunk B** (`b4bb942`) — G-10 renders in place of the login form on the 409
            (`DeviceLimitNotice.tsx`), G-11 ships at **`/settings/devices`** guarded for all
            five roles (`portals/settings/DeviceSettings.tsx`), plus `lib/deviceTypes.ts`,
            `lib/devices.ts`, `lib/hooks/useDeviceApi.ts`, the `confirmDeviceEviction` flag
            through `AuthContext`/`authTypes`, the `App.tsx` route, and a **G-11 entry in
            `web/scripts/audit.mjs`'s registry**. 12 new vitest cases (336 total pass);
            typecheck, oxlint, build, `impeccable detect` clean.
            **Deliberately not stubbed:** G-11's profile/password/relationships/subscription
            rows have no P5.7 backend, and a settings row that does nothing is worse than an
            absent one. Stated in the screen's header comment, not just here.
            **Two things left for P5.11, recorded so they are not mistaken for covered:**
            (1) **G-10 has no audit-registry entry** — it needs an account already holding
            three live devices, which is a *seed precondition*, not a navigation; (2) **no
            nav entry anywhere reaches `/settings/devices`** — the teacher sidebar needs an
            icon-map addition and the parent portal has no sidebar at all, so wiring three
            portals' nav belongs with P5.9's screens rather than half-done here.
            **Trap that cost real work — `npx prettier --write` is NOT this repo's
            formatter.** `web/` has no prettier config and prettier is not a dependency, so
            a bare run reformatted 8 files with **semicolons**, against the house
            semicolon-free style, silently and across files I had only read. Reverted with
            `git checkout` on the three tracked files (re-applying the edits by hand) and
            `--no-semi` on the five new ones. The web gates are **typecheck + oxlint +
            build + vitest + impeccable detect** — none of them formats. Do not reach for a
            formatter that the gate chain does not run.
- [ ] doing — **P5.8** Screens S-28, S-29, S-30, S-31.
      **CORRECTION to this brief, made 2026-08-11 by reading the code — the eighth time
      this phase a note lost to the codebase. "Every backend these screens need is already
      built" is TRUE for S-28/S-29/S-30 and FALSE for S-31.** `XpService` is wired into the
      web layer at **write seams only**: `grep total_xp\|xp_breakdown\|streak` over
      `lemely/web/` returns `deps.py`, `xp_awards.py` and the four award call sites, and
      **nothing reads**. The service methods themselves exist and are 100%-covered
      (`xp_repo.py:342 total_xp`, `:353 xp_breakdown(start, end)`, `:377 streak(now)`), so
      S-31 needs **one thin read router**, not an engine. That is chunk A and it goes first.
      **D5.1 §10 pre-authorised two S-31 decisions and they are P5.8's to make:** the
      XP→level mapping is explicitly deferred here ("P5.8 fixes it and records it, so long
      as it is a pure function of total XP"), and **achievements/milestones are out of
      scope** unless the screen is unbuildable without them, in which case they get their
      own decision record. UI spec §1.4 (never invent precision) governs S-31's "lifetime
      stats" line — ship only the stats a table actually holds.
      Chunking: **A** = the XP read route + D5.13; **B** = S-28; **C** = S-29 + S-30
      (they are one navigation pair and share the friends DTOs); **D** = S-31.
      S-28 (announcements + exam calendar):
      `GET /api/student/announcements`, `/unread-count`, `POST /{id}/read` (P5.5 chunk B)
      and `GET /api/student/exam-calendar` (P5.5 chunk C) — **the calendar table ships
      empty and its three distinct empty causes (`no_enrolment`/`no_timetable`/
      `no_session`) must reach the screen as three different states, not one blank**
      (D5.8). Leaderboard: `GET /api/student/leaderboard` with all four scopes including
      `friends` (P5.3/P5.4); `web/src/portals/student/screens/Standings.tsx` is the
      existing honest-empty screen this fills — read its header comment first, it records
      what was deliberately removed rather than mocked. Friends: `GET/POST/DELETE
      /api/student/friends` (P5.4) — S-30's "add by username" is **unbuildable as
      written**, `users` has no username; the built mechanism is `friend_code` (D5.6).
      Follow P5.7's frontend conventions: no `fallback` in `request()`, one hook file per
      area under `lib/hooks/`, and **do not run `npx prettier`** (see the environment fact
      below). MISSION §6.8 applies in full again.
- [ ] todo — **P5.9** Screens G-10, G-11, G-12, G-13.
- [ ] todo — **P5.10** Motion pass + a real `prefers-reduced-motion` proof test (MISSION §4
      Phase-5 acceptance names this explicitly).
- [ ] todo — **P5.11** Acceptance + UI-gate pass: E2E for XP accrual, leaderboard ordering, push
      delivery (mock), announcement flow; axe/Lighthouse/screenshots/visual compare.
- [ ] todo — **P5.12** Phase-5 report, merge to develop, push, update PR #3, ntfy.

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
- **`pre-commit` is not on PATH and two of its hooks cannot run.** The binary is
  `.venv/bin/pre-commit` (no bare `pre-commit`, and `$HOME/.local/bin` does not have it).
  Its `mypy` and `import-linter` hooks then fail with *"Executable not found"* — a defect in
  the hook environment, **not a code failure**: `./scripts/check.sh` runs both tools directly
  and they pass on the same tree. Verify there before believing a pre-commit red on those two.
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
