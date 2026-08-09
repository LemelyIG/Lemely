# BUILD STATE — single source of truth

status: RUNNING            # RUNNING | COMPLETE | HALTED
current_phase: 5            # Phases 0-4 complete, merged and reported; Phase 5 in progress
last_updated: 2026-08-09T22:10:00Z   # **Fortieth session, continued — P5.3 (leaderboards backend) is COMPLETE.** Both chunks committed (`e5c945b` chunk A, `3a2c445` chunk B) after a full **foreground** `./scripts/check.sh`: **all 13 gates PASS, 0 skipped, coverage 90.43%** (develop 90.18% — no drop). 4/12 Phase-5 tasks done. Branch `feature/phase-5-engagement`, not yet merged to develop.
#                                    **Two defects were caught by reading the model/spec rather than trusting the orchestrator's brief, and both are the same failure mode.** D5.4: the brief scoped the school board on `school_memberships`, which is **staff-only** — no student ever has a row there, so the board would have been permanently empty and read as a data problem rather than a code defect. Students reach a school through `Seat`. D5.5: `display_names_for()` copied the codebase-wide `display_name or email` fallback, which is safe where the audience is one class but broadcasts a real contact address to the whole platform on the **global** board. Neither would have failed a gate. Together with D5.2 (`subject_id` vs `subject_code`) and D5.3 (the paper-seam dedupe key) that is **four in Phase 5 alone**: *a brief that paraphrases the schema or the spec from memory is not a source of truth about either — read the model, and where a brief restates a spec, the spec wins.*
#                                    **Method note worth keeping:** `pytest --collect-only` still runs the coverage plugin unless given `--no-cov`, and it will clobber `.coverage` if you forget. Read the precise coverage figure off the run `check.sh` just did with `.venv/bin/coverage report --precision=2` rather than re-running pytest — a second run costs ~10 minutes and risks the concurrent-`.coverage` corruption noted below.
#                                    **Next: P5.4** (friends backend + migration), which also owns the leaderboard's fourth scope. Read the P5.3 and P5.4 checklist lines before starting.
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
- [ ] **doing** — **P5.4** Friends backend + migration (requests in/out, accept, remove, privacy).
      **Also lands the leaderboard's fourth scope**: add `LeaderboardScope.friends` to
      `lemely/db/leaderboard_repo.py` once the friendships table exists. Everything else it
      needs is built — follow the existing `_membership_subquery` shape, keep the opt-out in
      the WHERE clause, and extend the D5.1 §0 emitted-SQL guard test to the new scope.
      **Resume note (forty-first session):** both chunks were found already COMMITTED with a
      clean tree — the fortieth session died after committing chunk B but before running
      `./scripts/check.sh` and before updating this file. Nothing was re-implemented; the only
      outstanding work is the full-gate verification, which is running now. Do not re-plan the
      chunks; read the two commit messages (`7397df0`, `71d1a9b`) for what they contain and why.
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
- [ ] todo — **P5.5** Announcements: student-facing read + read-receipts, school-admin audience,
      auto-populated official CAIE session dates for the exam calendar.
- [ ] todo — **P5.6** Notifications inbox + web push (VAPID) with a headless-testable transport,
      and make `notification_preferences` actually gate delivery.
- [ ] todo — **P5.7** 3-device limit enforced in the UI (G-10) + device management (G-11).
- [ ] todo — **P5.8** Screens S-28, S-29, S-30, S-31.
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
