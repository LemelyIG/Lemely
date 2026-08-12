# BUILD STATE — single source of truth

status: COMPLETE           # RUNNING | COMPLETE | HALTED
current_phase: 6            # ALL PHASES COMPLETE — Phase 6 merged to develop, reported, PR #3 updated
last_updated: 2026-08-12T06:20:00Z
#
# ## Session 107 — CI fixed, and the drift behind it was a PATTERN, not one bad pin
# **Read this before touching `pyproject.toml`: every gate tool is now upper-bounded on purpose.**
# The red took TWO commits because fixing it moved the failure rather than clearing it, and the
# third instance is what turned it from a bug into a pattern: `ruff>=0.7` → runner got 0.16.2
# (10 × RUF036); then the `pre-commit` job's `.[dev]` → `mypy lemely` could not import fastapi
# (291 errors); then `gradio>=6.1,<7` → runner got **6.23.1**, whose event-listener typing gives
# 12 × `"Button" has no attribute "click"`. Same shape all three times: **CI installs fresh and
# resolves latest, this venv does not, so the two disagree about an identical tree with no commit
# in between.** Caps now: `gradio<6.20`, `pytest<10`, `pytest-cov<8`, `mypy>=2.1,<2.2` (minor —
# mypy adds checks in minors), `pre-commit<5`, `import-linter<3`, `ruff==0.15.20` in lockstep with
# the pre-commit rev. Raising one is a deliberate commit that re-runs the gates; that is the point.
# **Proved by resolving, not by reasoning:** `uv pip compile` for 3.12/3.13/3.14 all exit 0 and
# all select `gradio==6.19.0`, `mypy==2.1.0`, `ruff==0.15.20` — the versions this tree is green on.
# (`mypy>=1.13` had been admitting a whole major the build has never gated on; the venv is 2.1.0.)
#
# ## Session 107 — session 106's finding was FIXED, and the deferral it rested on was wrong
# P6.12 (`7f11f58`, D6.10) closed the CI red session 106 diagnosed. Both defects were toolchain,
# not product: `ruff>=0.7` let the runner resolve **0.16.2** against this venv's and the
# pre-commit rev's **0.15.20** (10 × RUF036), and the `pre-commit` CI job installed `.[dev]` only,
# so its `entry: mypy lemely` hook could not import fastapi — **291 errors that are an environment
# answer, not a verdict on the code** (the identical step is green in the `test` job, which
# installs the web/db extras). Fixed by pinning `ruff==0.15.20` in lockstep with the pre-commit
# rev, reordering the 10 annotations so a future bump is unblocked, and giving the pre-commit job
# `.[dev,ui,web,db]`.
# **Session 106 deferred this to Copilot's PR #4 because a fix was "in flight". It was not:
# PR #4 has been stale since 2026-08-05 and predates the failure it is named after** — RUF036
# shipped with ruff 0.16, days later — so it could never have fixed this red, and two of its four
# changes would have hurt (it narrows the format gate to `lemely tests`, dropping `web/` and
# `scripts/`, and uses `if: matrix.python-version == "3.13"`, which GHA cannot parse — expressions
# require single-quoted strings). **Check whether a fix-it PR predates the failure before treating
# it as a reason to leave a gate red.** PR #4 is still open and unmerged — Habeeby's call.
# **Verified with the version CI actually resolves, not the local one** (`uvx ruff@0.16.2 check .`
# → All checks passed), which is the only check that could prove this. The same probe is why the
# fix pins instead of upgrading: `uvx ruff@0.16.2 format --check .` says **6 files would be
# reformatted and the file set widens 340 → 387**, so bumping would have traded a red lint gate
# for a red format gate on a shipped tree.
#
# ## Session 106 — resumed on a complete build, nothing to continue, ONE thing found
# Tree clean, INBOX has no unhandled item, B1–B3 all RESOLVED, `origin/develop` up to date, PR #3
# open and unmerged. No task was started: the first non-done item in this file is Phase 1's
# opportunistic D1.9 backlog, and beginning it would put product code after P6.11's closing
# `EXIT=0` — the one property that run went out of its way to establish (`git diff 66950f3..HEAD
# -- lemely web scripts tests …` empty). Docs-only is the safe work on a shipped tree.
# **The finding, which nothing on disk recorded: GitHub Actions has been RED on PR #3 since at
# least 2026-08-09, while all 13 local gates are green — and both statements are true.** The CI
# job installs the `dev` extra fresh, `pyproject.toml:45` pins only `ruff>=0.7`, so runner 3.14
# resolved **ruff 0.16.2** where this venv holds **0.15.20**. 0.16 enforces **RUF036** (`None` not
# last in a type union), which 0.15 does not: `lemely/db/notification_prefs_repo.py:110-111` and
# `lemely/db/student_profile_repo.py:164+` carry `X | None | _UnsetType`. Locally
# `.venv/bin/ruff check .` says *All checks passed* and `ruff format --check .` says 340 files
# formatted. **So this is toolchain drift, not a code defect — an unpinned linter is a gate whose
# verdict changes without a commit**, the same shape as P6.6's dated VAPID assertion (a red that
# arrives on a calendar, not on a change). Not fixed here: **PR #4 already exists** from Copilot
# ("align pre-commit dependencies and normalize formatter outputs") targeting develop, so touching
# the same files would collide with a fix in flight, and merging a PR is never mine (MISSION §4).
# The fix is one line either way — pin an upper bound on `ruff` in the dev extra, or apply the two
# `RUF036` autofixes. Habeeby's call.
#
# ## THE BUILD IS COMPLETE. What the last session established
# - **`/tmp/check_p611.log` LANDED: `EXIT=0`, all 13 gates PASS, 0 skipped**, 06:53 local on
#   2026-08-12, on the tree at `66950f3`. `git diff 66950f3..HEAD -- lemely web scripts tests
#   Makefile pyproject.toml` is **empty** (everything after it is docs), so unlike P6.6's run
#   this verdict is a true statement about the shipped code. That one command is the whole
#   difference between the two, and it is why the report writes it out.
# - **Counts came from a SEPARATE, SERIAL `pytest` run** (`/tmp/pytest_p611.log`, `EXIT=0`),
#   because `check.sh` prints nothing for a passing gate and holds neither a count nor a
#   coverage figure: **3508 tests — 3502 passed / 6 skipped / 0 failed — 90.92% coverage**
#   (from Phase 5's 2927 / 90.91%, so coverage never dropped). Serial matters — a concurrent
#   pytest + check.sh pair has already produced a convincing but wrong coverage regression here.
#   All 6 skips were re-derived, not carried: 2 live *billed* accuracy tests
#   (`LEMELY_LIVE_ACCURACY`), 4 live Supabase tests gated on keys being exported. None broken.
# - Merged to develop (`dd260f2`), pushed. PR #3 retitled "Phases 0–6" with a full Phase-6
#   section, **still OPEN and NOT merged** (MISSION §4 — never merge it yourself).
# - P6.7 closed the last known gate failure: `student-standings` CLS 0.386 -> **0.000** (zero
#   shifts recorded, not a smaller number), performance 74 -> 93, and `ui-thresholds` EXIT=0 on
#   the committed phase-6 corpus. The run before it (`/tmp/check_p610b.log`, tree at `310fade`)
#   ended `EXIT=1` with 12 gates PASS and that single failure; nothing else in it was red.
# - **`/tmp/check_p610.log` LANDED: `EXIT=0`, all 13 gates PASS, 0 skipped, 04:29 on 2026-08-12.**
#   The second fully green full-suite run of the build, and the first covering `lemely/db/seed.py`
#   + `lemely/runtime/supabase_env.py`. It ran on the tree at `b5bc7c7`, but
#   `git diff b5bc7c7..HEAD -- lemely web scripts tests Makefile pyproject.toml` is **empty** —
#   every commit since is docs/BUILD only — so the verdict holds for HEAD's code. It still holds
#   no test count and no coverage figure (`check.sh` prints nothing for a passing gate).
# - **An 84-byte log stuck after the four backend gates is the NORMAL shape of a healthy run
#   mid-`pytest`, not a stall.** `check.sh` prints nothing for a passing gate. Decide liveness
#   from `pgrep -af bin/pytest`, never from the log size or from a `FAIL` line (the script does
#   not abort on a failed gate). Five consecutive sessions correctly declined to relaunch on
#   this evidence; that discipline is what produced P6.6's first fully green run.
# - **While a gate run is in flight, touch no code.** Editing `lemely/` or `web/` mid-run makes
#   the verdict a statement about a tree that no longer exists, and nothing in the log shows it.
#   Docs are the safe work.
# - **`check.sh`'s log holds a verdict and nothing else** — no test count, no coverage figure.
#   Any number quoted anywhere must come from an artifact that actually holds it.
#
# Session 103: **P6.10's fresh-clone acceptance run is DONE and it passed** — `make up` from a
# real clone brought the product up and all five demo roles authenticate through nginx on :8080.
# It also found four defects no gate could see, fixed in `310fade` (D6.8). The one to carry:
# **an empty env var is not an unset one.** `${VAR:-}` in compose made pydantic build
# `SecretStr("")`, so every `is None` "not configured" check answered *configured* — `/api/health`
# said `apiKeyConfigured: true` on a stack that cannot mark a paper, and GoTrue's explicit
# "key is not configured" AuthError never fired, sending an empty `apikey` that local Kong
# accepts and Supabase Cloud would not. **A fresh-clone test earns its keep by running the
# documented commands as written rather than the ones you know work.**
# It also re-ran the full suite on `310fade`: **`EXIT=1`, the first non-green run since P6.6.**
# The config fix is clean (pytest, mypy, import-linter, all five web gates, playwright-e2e);
# the single failure is `ui-thresholds` on `student-standings`, and it is **CLS 0.386, not
# bundle weight**. Diagnosed on the P6.7 entry so that task starts with it.
# Session 102: cleaned the tree (harness MCP config only), then closed **P6.9** — DELIVERY.md
# §6 Evidence, the last open hole. Built as three tables: what is measured today with the
# command that re-derives each figure, the Phase-5 UI baseline recomputed from the committed
# JSON, and the run-dependent figures left deliberately blank with the task that fills them.
# Re-ran rather than carried: `playwright test --list` says **34 tests in 13 files** (STATE
# carried 30 for a phase), and the Phase-5 Lighthouse directory holds **45 files but 44 route
# reports** — the extra is `_summary.json`. a11y floor 96 (`teacher-review`) and the 8 sub-80
# performance routes both reconfirmed from the JSON, so the phase report was right.
# Session 101: P6.6 closed green, P6.8 closed, P6.10's seeder made real. Its lesson is on the
# P6.10 entry below and is the one worth carrying: **a hermetic test of an entry point tests
# everything except that it is an entry point** — 12 green tests, then `make seed` died on the
# live stack. Verify an entry point by running it, and on a clean slate.
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
- [x] done — **P6.1** Gate-affecting hardening fixes. Both carried limitations CLOSED — D3.20 by
      `3eb0c5e`, D4.25 by `23a5261`. Decisions D6.1/D6.2.
      **(a) `web/e2e/` is typechecked for the first time.** New `web/tsconfig.e2e.json`, referenced
      from `tsconfig.json`, so the existing `web-typecheck` gate covers it with no `check.sh` change.
      It is a *separate* project rather than a line added to `tsconfig.test.json` — that one declares
      `vitest/globals`, so a Playwright spec compiled under it would typecheck against vitest's
      ambient `expect`/`test` instead of the ones it imports. It found exactly one error and it was
      real (`webServer.env` spread from `process.env`, `string | undefined` into a `string` field;
      fixed by filtering, not casting). The gate is now `tsc -b --force` — incremental `tsc -b` is
      how `tsconfig.test.json` shipped without `jsx` for a whole phase while the build stayed green.
      **The real count is 34 tests in 13 files, not the 30 STATE has carried since P5.11** —
      measured with `playwright test --list`.
      **(b) The Lighthouse performance floor is now enforced, and the routes were fixed rather than
      the bar lowered.** Root cause was a **single 1.3 MB `index-*.js` serving all 44 routes** — zero
      code splitting, which is why every score sat in a 65–87 band regardless of the route. Screens
      are now `React.lazy` behind one `Suspense` per portal around the `<Outlet />`.
      **Measured on a full audit run (`AUDIT_EXIT=0`), not estimated: entry chunk 1.3 MB → 397 kB
      across 90 chunks; student-route performance minimum 70 → 89 with none below 80**
      (`student-standings` 70→92, `student-result` 73→90, `student-placement-test` 79→92,
      `student-announcements` 78→89). Teacher routes improved too though they are deliberately NOT
      gated (`teacher-quiz-detail` 65→81, `teacher-schemes` 74→88) — MISSION §11 states a floor for
      student routes only, and inventing one for the others at the moment it would fail is a scope
      change, not diligence. `ui-thresholds` EXIT=0 on that run: 73 axe route-states zero
      serious/critical, 44 Lighthouse reports a11y ≥ 95, zero console errors, zero horizontal scroll.
      **Two things a later session must not misread.** The audit that produced those numbers built
      the tree *before* the `RouteFallback` consolidation that followed it (a refactor merging four
      already-drifted local copies into the C-11 family — no runtime effect), so P6.6's full run is
      the figure of record for the final tree. And three bespoke journey steps in `audit.mjs` call
      `runLighthouseAudit` outside the route registry; they were missing the new `path` field and
      silently riding the slug-prefix fallback meant for old corpora. Fixed — but that is the shape
      of hole to check for whenever a gate grows a new per-route field.
      **E2E re-verified after the split (MISSION §6 gate 4 — this change touches every flow):
      34/34 passed, `E2E_EXIT=0`, 3.7m.** Lazy routes broke nothing.
- [x] done — **P6.2** Concurrency + load sanity (`1cad838`, D6.3). `tests/test_concurrency.py`
      (3 tests, real thread pools + separate sessions) and `scripts/load_sanity.py`.
      **It found a real defect: `XpService.award` could be defeated by concurrency.** The D5.1 §3
      daily anti-farming caps were a read-then-write with no lock — 8 concurrent awards against a
      cap of 3 all succeeded, and distinct `dedupe_key`s mean migration 0013's unique constraint
      cannot save it. Fixed with `with_for_update=True` on the `users` row, the idiom
      `DeviceRegistry.register_login` already uses on the same table for the same TOCTOU.
      **The inverted run failed with a *different* symptom than the one that motivated the fix** —
      a `uq_streaks_user_id` UniqueViolation from concurrent streak-row creation, not the cap
      bypass. One missing lock, two failure modes, and which surfaces depends on thread timing;
      a later session seeing only one should not conclude the other was misdiagnosed. The streak
      symptom is the worse one in production, because `award_xp_safely` is fail-open: the error is
      swallowed and a real student silently loses XP with every gate green.
      **The pass also caught one of its own tests being decoration**, which is the transferable
      lesson: `test_device_cap_holds_under_concurrent_logins` *passed* with the lock it claimed to
      verify removed (4 unsynchronised threads rarely overlap — 8 pass / 12 fail over 20 runs).
      Fixed in the test only (`threading.Barrier`, 11 threads); re-measured independently at
      **0 pass / 10 fail with the lock removed**. **Rule for the rest of Phase 6: a test asserting
      a concurrency guarantee must be shown to fail repeatedly when that guarantee is removed, and
      a single inversion run is not enough to clear one — count, don't eyeball.**
      Load sanity reports numbers and **no verdict** (MISSION states no API latency threshold;
      grading against an invented one is manufactured precision). Real output committed at
      `reports/phase-6/load-sanity.{json,md}` — 8 endpoints, concurrency 10, ~10k requests, zero
      errors. **Carry to DELIVERY.md: `/api/teacher/overview` is 10–40× slower than everything else
      measured** (p50 396ms / p95 458ms vs 8–150ms) — the shape of an N+1 across a teacher's classes
      and students. Not chased (an observation on seeded data, not a failing test), but it is the
      first place to look if the teacher console feels slow.
- [x] done — **P6.3** Security re-review (`b8913cb`, `7e3e012`, D6.4). **No production code
      changed — the sweep found nothing to fix, and that is the result, not a shortfall.**
      **(a) The matrix is now generated, not hand-listed.** `tests/test_authz_matrix_complete.py`
      derives the route set from the app and asserts it **equals** a declared table, so adding a
      route with no declaration fails and a stale declaration fails too — the drift gate P1.6's
      hand-list never had, and the reason its coverage silently stopped growing at Phase 3 (the
      whole Phase-4/5 surface was unrepresented). The old file is kept: it carries per-route
      rationale a generated file cannot.
      **Measured, all 121 route operations:** 5 public (4 auth entrypoints + `/api/health`), 12
      authenticated-but-deliberately-role-agnostic (`/api/me`, notifications), 104 role-gated.
      **Nothing unguarded.** 573 new test cases across the two files.
      **(b) Two gaps the `reviewer` sweep named, both closed.** The 403 sweep overrides
      `get_auth_context`, so it proves `require_role` given a correct context but is blind to a
      break in token decoding — *the code building the context is the code it replaces*. 21
      real-minted-token cases across all six guard classes plus 4 malformed-credential cases now
      cover the chain. And `extra="forbid"` was declared on four `ApiModel` bases but never proven
      to reach every body; `tests/test_request_schema_hardening.py` walks the dependency tree
      **transitively** (a strict outer model with a lax nested element type still takes unknown
      keys) — 39 models, all strict — and proves pydantic acts on the flag.
      **(c) Row-level ownership traced clean.** Every caller-supplied identifier on the Phase-4/5
      routers goes route → service → SQL keyed on `auth.user_id`; ownership failures collapse to
      404 where a 403 would be an existence oracle.
      **Everything inverted and counted (P6.2's rule):** guard disabled → 333/333 role-gated and
      21/21 real-token cases fail while the 401 sweeps correctly still pass; one undeclared route
      → all three structural tests fail; one nested model made lax → exactly its two cases fail.
      **Process trap worth not repeating:** the `reviewer` ran concurrently with inversion A, read
      `deps.py` while the guard was deliberately off, and filed a Critical "something is mutating
      the auth guard on disk". Correct observation, wrong conclusion. **Never run a read-only
      reviewer against the same checkout as an in-flight inversion.**
- [x] done — **P6.4** Docker Compose (`e81f2f9`, D6.5). `Dockerfile` (backend, multi-stage,
      non-root, binds 0.0.0.0), `web/Dockerfile` (npm build → nginx serving `dist/` + proxying
      `/api`), `web/nginx.conf`, `docker-compose.yml`, two `.dockerignore`s, `docker-entrypoint.sh`,
      `scripts/up.sh` behind **`make up`** as the single command. No application code changed.
      **Two design points a later session must not undo.** The backend joins Supabase's own
      **`supabase_network_Lemely`** as an `external` network and addresses `supabase_db_Lemely:5432`
      / `supabase_kong_Lemely:8000` by container name — *not* the host-published 54322/54321, which
      do not exist inside a container. Declaring the network instead of joining it would silently
      stand up an empty one the backend cannot reach Postgres through; `external: true` fails loudly
      when Supabase is down, which is the correct behaviour.
      **And no CORS middleware was added — deliberately.** nginx proxies `/api` to the backend on
      the same origin the SPA was loaded from, so the browser issues no cross-origin request and
      there is nothing for CORS to permit; adding `allow_origins` would widen the attack surface
      without enabling anything. Full reasoning (and what a real split-origin deploy would need:
      config-driven allowlist, `allow_credentials=False` since auth is bearer-token not cookie)
      is a comment block at the top of `docker-compose.yml`. **`grep -rn CORSMiddleware lemely/`
      is still empty and that is the intended state, not an omission to be "fixed".**
      **Verified by me on a `make up` stack, not taken on the subagent's report:** health 200 direct
      *and* 200 through the nginx proxy; SPA index served; `alembic upgrade head` runs in the
      entrypoint with the DB at `0018` and the container reaching Postgres over the Supabase
      network (1610 seeded users read from inside the container); and the whole auth chain works
      behind the proxy — **401 no token / 200 real minted student token / 403 teacher token on a
      student route**, which also proves nginx forwards `Authorization`. The hardcoded local JWT
      secret was checked against the *running* `supabase_auth_Lemely`'s `GOTRUE_JWT_SECRET` rather
      than assumed to match.
      **One snag worth not rediscovering:** `npm ci` fails in a slim node image because puppeteer's
      postinstall downloads Chrome and there is no `unzip`. Fixed with `ENV PUPPETEER_SKIP_DOWNLOAD=true`
      in the builder stage — puppeteer is audit-runner tooling only and nothing at build time imports it.
      **Carry to P6.5/DELIVERY.md:** the entrypoint runs `alembic upgrade head` on every start. Right
      for a one-command local bring-up, wrong for a production deploy where migration is a separate
      gated step — the deployment doc must say so.
- [x] done — **P6.5** Deployment docs (`882f983`, D6.6). `docs/deployment.md` — the working
      local `make up` stack, a Supabase-Cloud + container-host recipe, the configuration
      reference (env precedence `LEMELY_` + `__`, the variables a deploy actually sets), the
      CORS-only-if-split-origin case, and a copy-paste checklist. **The cloud half has never
      been executed and the document opens by saying so**; every claim is anchored to a
      file:line so a reader can check rather than trust. P6.4's two handoffs are discharged.
      **Writing it found two facts nothing had stated, both from reading code:**
      **(a) The backend cannot run more than one replica.** `JobRegistry`
      (`lemely/web/jobs.py:31-37`, every in-flight correction job + its SSE stream) and the
      parent OTP challenge store (`lemely/auth/service.py:107`) are **process-local**. Two
      replicas ⇒ a student reconnects to a replica that never heard of their job, and a
      parent's OTP is issued on one instance and verified on another. Intermittent and
      unreproducible — the worst failure shape, tripped silently by any host that autoscales
      by default, and caught by no test in this build.
      **(b) `lemely/db/seed.py` creates nothing — this is a P6.10 problem, see that task.**
      Not fixed deliberately: the `LEMELY_RUN_MIGRATIONS` guard for the entrypoint's
      unconditional `alembic upgrade head` is *described* but not implemented — P6.5 is a
      docs task and an untested branch in the container start path would risk the `make up`
      P6.4 just verified.
      **One containerisation consequence worth carrying:** the $8 Gemini ledger lives under
      `/app/.lemely-cache` on the **ephemeral container filesystem**, so a host that recycles
      containers resets measured spend to zero while the real bill climbs. Mount a volume or
      the hard cap stops being a cap.
- [x] done — **P6.6** Full-suite pass. **`/tmp/check_p66c.log` ended `EXIT=0` at 02:44 on
      2026-08-12: all 13 gates PASS, 0 skipped**, on the tree at `6005b20` — the first fully green
      full-suite run of the build. Session 101 confirmed it (four sessions in a row had correctly
      declined to relaunch while it ran; the discipline paid).
      **Two caveats a later session must carry rather than round off.**
      (a) `check.sh` prints nothing for a passing gate, so **that log contains no test count and no
      coverage figure** — only the verdict. Any number quoted in DELIVERY.md/the phase report must
      come from an artifact that actually holds it, not from this log.
      (b) **Three commits landed after the run** — `2266841` (supervisor.sh, not shipped code),
      `33270b4`/`818e269` (docs) and **`7e5a999`, which touched real code** (`lemely/web/app.py`
      now imports `__version__` instead of hardcoding it) plus both version manifests. So EXIT=0 is
      a true statement about `6005b20`, **not about HEAD**. P6.11 re-runs the suite on the final
      tree; that run, not this one, is the figure of record.
      Green here: ruff-check, ruff-format, mypy, import-linter, pytest, web-typecheck, web-lint,
      web-build, web-test, impeccable-detect, playwright-e2e, puppeteer-audit, ui-thresholds.
      **The failure was `tests/test_push_transport.py:170`, and it was a TIME BOMB, not a flake.**
      The test signs a VAPID assertion at the injected `FIXED_NOW = 2026-08-10 12:00 UTC` and then
      verified it with `jwt.decode` against the **real wall clock**; RFC 8292 caps the assertion at
      24h, so it was green on the day it was written (P5.6) and red in every run after
      2026-08-11 12:00 UTC. Phase 5's own closing run predates the expiry, which is why the phase
      shipped "all gates green" honestly and this still surfaced. Product code is correct and was
      not touched. Fixed with `verify_exp: False` on that one decode, **inverted twice** (wrong
      audience → `InvalidAudienceError`, foreign key → `InvalidSignatureError`) so it is not a
      weakened test. **Generalise it: any test that pins a clock on the write path and reads back
      with the real clock is a dated assertion whose failure arrives on a calendar, not on a code
      change** — invisible to per-commit CI, and exactly what a phase-end full run is for.
      Previous session's note follows. **Session 96: a run is IN FLIGHT — `/tmp/check_p66b.log`, launched detached (PPID 1) on the
      clean tree at `179f9f6`. Do not launch a second one; poll for the `EXIT=` line.** Session 95
      had launched `/tmp/check_p66.log` and died immediately; I killed it 5 minutes in on a **wrong
      diagnosis** and relaunched, which is the lesson worth carrying:
      **`supabase` is NOT on PATH in a non-interactive shell — a bare `supabase status` returns
      `command not found`, which looks exactly like "the stack is down".** It is not. The binary is
      `~/.local/bin/supabase` (a symlink into the npm global lib), the containers were running the
      whole time, and **`check.sh` exports `$HOME/.local/bin` itself** (`scripts/check.sh:34`)
      precisely so its `STACK_UP` probe works — so the run I killed would have run all 13 gates.
      Prefix with `export PATH="$HOME/.local/bin:$PATH"` before believing any stack verdict from
      your own shell. This is the same failure mode STATE already records for `pre-commit`/`mypy`,
      hit a second time on a different binary: **"executable not found" is an environment answer,
      never a verdict** — and here it nearly became a verdict about *Docker containers*, one level
      further from the missing binary than the earlier case, which is why it was convincing.
- [x] done — **P6.7** (2026-08-12, session 104). **`AUDIT_EXIT=0`, `check_ui_gates.py` EXIT=0,
      `removed: 0` against both baselines.** Full write-up `reports/phase-6/visual-qa.md`;
      the source audit is `reports/phase-6/impeccable-audit.md` (15/20, Good).
      **The headline number: every route in the product is now ≥80 Lighthouse performance
      (floor 80, `teacher-quiz-detail`), where Phase 5 had EIGHT routes below 80 and a floor of
      65.** 73 axe route-states, **0 violations at any impact**; 44 Lighthouse reports, a11y floor
      96; 0 console errors; 0 horizontal-scroll violations; 48 screens / 246 screenshots.
      **The live defect and its fix:** `student-standings` at performance 74 on **CLS 0.386 and
      nothing else**. Fixed in `Standings.tsx` (`46bd5f7`) → **CLS 0.000, zero shifts recorded,
      performance 93.** Zero shifts rather than a smaller number is what makes it a fixed defect
      instead of a luckier run. Detail is on the P6.1 note below and in `visual-qa.md` §4.
      **Three things a later session must not re-derive.**
      (a) **The corpus has THREE producers and running one silently drops the others.** The audit
      runner covers 43 screen ids; `web/e2e/screenshots.spec.ts` owns S-06/S-10/S-14/S-15/S-17 and
      `web/e2e/correct-paper.spec.ts` owns the two `p2.10-*` captures. The first pass here ran only
      the audit runner and the compare reported those seven as **`removed`** — the exact signal
      MISSION §4 defines a blocker by, from screens that had not regressed but had never been asked
      for. `TOKENSAVE_DISABLE_GREP_HOOK=1 grep -ln "SCREENS_DIR" web/e2e/*.ts` names every producer
      in one line; run it before believing any `removed` count.
      (b) **`compare_screens.mjs --json` takes a REPO-relative path and rejects `../`** even when
      your cwd is `web/`. It fails *after* printing the whole comparison, so the lists scroll past
      and look like a successful run that wrote nothing.
      (c) **Per-role contact sheets did not exist.** `audit.mjs` writes one flat sheet; MISSION §4
      asks for per-role. New `web/scripts/contact_sheets.mjs` (`npm run contact-sheets`) reads only
      what is on disk, so sheets regenerate from a committed corpus without an 11-minute audit.
      `G-` gets its own sheet rather than being copied into all three roles, and an id matching no
      prefix lands on **Unclassified** and is named on stdout — which caught `DEV-01` immediately.
      **Left undone deliberately, both in DELIVERY.md rather than silently fixed:** the ~600
      arbitrary Tailwind literals across 41 files (a 600-site rewrite at ship time whose only
      acceptance signal is a compare that cannot be pixel-clean), and the 54 sub-44px `size="sm"`
      controls (WCAG 2.2 AA met, AAA not — the Phase-2.5 §8 gap, re-confirmed not rediscovered).
      Superseded task text follows for the record. Full-product visual QA sweep: regenerate the **entire** screenshot corpus,
      per-role contact sheets, `/impeccable audit` across frontend source, `npx impeccable detect
      src/` with every finding resolved, axe + Lighthouse over every route. Regression against the
      Phase-2.5 baselines is a blocker (MISSION §4). Read `removed` (must be 0), not `changed`.
      **START HERE — session 103's gate run handed P6.7 its first finding, already diagnosed.**
      `/tmp/check_p610b.log` ended **`EXIT=1`: 12 gates PASS, `ui-thresholds` FAIL** —
      `lighthouse: student-standings performance score 74 < 80`. Do not re-derive the cause; the
      breakdown was pulled from the JSON before `reports/.scratch` was overwritten:

      | metric | score | value |
      |---|---|---|
      | cumulative-layout-shift | **0.27** | **0.386** |
      | first-contentful-paint | 0.76 | 2.3 s |
      | largest-contentful-paint | 0.84 | 2.8 s |
      | total-blocking-time | 0.97 | 120 ms |
      | speed-index | 0.99 | 2.3 s |

      **It is CLS, not bundle weight.** TBT/LCP/SI are all healthy, so this is *not* a regression
      of P6.1's code-splitting fix in the direction P6.1 was measuring — and 0.386 against the
      0.1 "good" threshold is a real defect, not noise near a floor. **The likely cause is P6.1's
      own fix**: `React.lazy` behind one `Suspense` per portal means the fallback is swapped for
      real content after paint, and a fallback that does not reserve the content's height shifts
      the page. `student-standings` (the leaderboard) is the plausible worst case — rows arrive
      in bulk. Check `RouteFallback`'s sizing first.
      **The honest framing for the report: P6.1 raised this route 70→92 by fixing the metric it
      was looking at, and the same change plausibly cost CLS on the same route.** The previous
      run (`/tmp/check_p610.log`, 04:29, same web tree) passed `ui-thresholds`, so either it is
      genuinely intermittent or the earlier run got a luckier layout — **measure the spread
      before calling it either**, and never by loosening the threshold (D4.25 exists because this
      floor went unenforced for two phases; re-disabling it now would be worse than never having
      enforced it).

      **Session 104 — the CLS was attributed from a committed artifact, not from a re-run, and the
      previous session's stated hypothesis was WRONG.** `reports/phase-5/lighthouse/
      student-standings.json` already carried the `layout-shifts` audit for this route (CLS 0.220
      there, so the defect predates P6.1 and is not a regression *caused* by the code split — P6.1
      raised the other four metrics and left this one, which is why the route could score 92 on one
      run and 74 on another: **the shifts only count when the skeleton paints before the data
      arrives, so a fast run hides them entirely**). Both recorded shifts name the same element:
      `<section aria-labelledby="s29-subjects">`, i.e. "Your subjects" being pushed down the page —
      **not `RouteFallback`**, which the previous entry told this session to check first. Three
      blocks above it grow after first paint: the board card (one "Loading the board…" line → a real
      board, ~335px on seeded data at 380px wide), `OptOutControl` (rendered `null` while its
      profile read is in flight, then ~124px), and the XP-basis tab row (~34px).
      **Fixed in `web/src/portals/student/screens/Standings.tsx` by reserving the space, never by
      touching the threshold.** The two null-until-loaded blocks now render their own frame with the
      real copy `invisible` + `aria-hidden` + `inert` while pending — reserving with the actual text
      rather than a `min-h-*` guess is what makes the reservation correct at every breakpoint,
      because the height comes from the same wrapping in the same box. The board card gets a
      `min-h-96` floor **in every state, not only while loading**: 384px is the height of the
      smallest real board on seeded data (a C-11 empty panel plus the pinned viewer row), so it is a
      measurement of the content, and it also stops the page jumping when the student switches
      Friends/Class/School/Everyone — the same defect seen by a person instead of by Lighthouse.
      Typecheck, oxlint and the 113 standings/design-token unit tests all green on the change.
      **Second finding, and it is about a gate rather than the product: `npx impeccable detect` is
      VACUOUS on this machine.** impeccable 3.5.0 returns `[]` for `src/`, and also for a file
      deliberately written to trip it (inline `style={{color:"#ff0000"}}`), for a CSS file with an
      off-scale `font-size: 13.7px`, and for an em-dash-overuse file — with `--json`, `--quiet` and
      `--no-config` alike, exit 0 and zero bytes every time. No `.impeccable` config suppresses
      anything (`config.local.json` holds only hook consent). So MISSION §4's "resolve every
      finding" is satisfied trivially and **a green `impeccable-detect` gate is not evidence of
      anything** — it must be reported that way in the phase report and DELIVERY.md rather than
      counted as a pass. Not chased further: it is third-party tooling, the deterministic checks
      that do bite (axe, Lighthouse, console-error, horizontal-scroll) are unaffected, and the
      `/impeccable audit` skill pass is a separate, non-vacuous leg of this task.
- [x] done — **P6.8** README + CHANGELOG rewritten for the shipped product (`12dff56` draft, made
      true across `2bee4cb`/`818e269`/`33270b4` as each claim was verified), version bumped to
      **1.0.0** in `pyproject.toml` and `web/package.json`, and `lemely/web/app.py` now imports
      `__version__` rather than carrying a hand-copied `"0.1.0"` (`7e5a999`). Verified at HEAD.
      **Note the editable install:** `__version__` reads installed metadata, so the CLI/API keep
      reporting the old number until `pip install -e .` is re-run.
- [x] done — **P6.9** `DELIVERY.md`. Written across three sessions: §1/§2/§4/§5/§7 at 98
      (`ed0f6b7`), the feature table at 99 (`af87de7`, every path `ls`-checked before listing),
      and **§6 Evidence at session 102 (`2b0e506`) — the last hole**. §5 carries every
      Phase-2..5 limitation plus P6.5/P6.6's operational ones, with D6.1/D6.2 struck-through-
      and-closed rather than deleted.
      **§6 is built as three tables, not prose, because the recurring failure here is a figure
      with no source left.** §6.1 pairs each measured number with the command that re-derives it;
      §6.2 recomputes the Phase-5 UI baseline from the committed JSON (it agrees with the phase
      report); §6.3 lists the run-dependent figures as **deliberately blank**, naming the task
      that fills each and the artifact it must come from.
      **Two corrections that came out of re-running instead of copying:** `playwright test
      --list` reports **34 tests in 13 files** (STATE carried 30 for a whole phase), and
      `reports/phase-5/lighthouse/` holds **45 files but 44 route reports** — `_summary.json` is
      a list, not a route, and a naive `ls | wc -l` reads as 45. a11y floor 96 (`teacher-review`)
      and the 8 sub-80 performance routes both reconfirmed.
      **P6.7 and P6.11 must fill §6.3 from their own artifacts** — that is the only thing left
      in this file, and it is structural, not a hole.
- [x] done — **P6.10** Fresh-clone acceptance: `git clone` → the documented commands → working
      product with seeded demo accounts for all 5 roles. **RUN FOR REAL AND PASSED**
      (session 103, `310fade`, D6.8) — a clone of this branch at `be49d34` into
      `/tmp/lemely-fresh-1`, the documented commands executed verbatim from it, every claim
      checked against the running containers.
      **`make up` from the clone: `EXIT=0`, both containers healthy, SPA served on :8080.**
      All five roles authenticate **through nginx, not against the backend directly** — four by
      password login, the parent by phone-OTP — each confirmed by reading `/api/me/profile` back
      with the returned token and seeing the right role. That chain (DNS → proxy →
      `Authorization` forwarding → JWT validation → RBAC) had **never been exercised with a real
      GoTrue login before**; P6.4 only ever used backend-minted tokens.
      **Four defects found, all invisible to the 13 gates that had just gone green on this same
      tree** — the gates run inside an environment that is already correct, and this criterion is
      about reaching it from a clone. Full text in D6.8; the one that matters:
      **an empty env var is not an unset one.** `docker-compose.yml` forwards optional credentials
      as `${VAR:-}`, so pydantic built `SecretStr("")` — not `None` — and every "is not
      configured" check answered *configured*. `/api/health` returned **`apiKeyConfigured: true`
      on a stack with no Gemini key at all**, and `GoTrueClient._anon_key`'s explicit AuthError
      never fired, sending an empty `apikey` header that **local Kong tolerates and Supabase Cloud
      would reject as an unrelated-looking 401**. Fixed with a blank→None `BeforeValidator` on the
      optional credential fields only (both Supabase keys, Gemini, the three VAPID fields).
      Also fixed: `DEMO_PARENT.display_name` was declared and applied nowhere (the parent answered
      `displayName: null` while the other four carried theirs), README's
      `pip install -e ".[dev,ui]"` omitted the `db`/`web` extras so `make db-migrate` and
      `make seed` both failed outright from a clone, and `python` is not a command on
      Debian-family systems (README + the Makefile's `PYTHON` default).
      **What it did NOT prove, stated rather than rounded off:** the Supabase stack was already
      running, so `up.sh` took its already-running branch and a cold `supabase start` is still
      unexercised; and `make seed` reported `demo_accounts: 0` because the accounts existed —
      correct idempotent behaviour, with creation-from-empty proven separately at session 101.
      Session 101's groundwork (the real seeder, the `supabase_env` extraction, 12 hermetic
      tests, `b5bc7c7`/`e2ed097`) is what made this run possible; its lesson stands —
      **a hermetic test of an entry point tests everything except that it is an entry point.**
      **Known before you start (found at P6.5, D6.6 — do not re-derive): the seeding path this
      criterion names does not exist.** `seed_reference_data` and `seed_demo_accounts` in
      `lemely/db/seed.py:26-51` are **stubs with a bare `pass`**, so `make seed` inserts zero
      rows and creates zero accounts while logging a cheerful `db.seed.done`. The only working
      path is `scripts/seed_e2e.py`, which does create all five roles — but under a **per-run
      random `run_tag`**, so emails and passwords differ every run. Fine for tests, useless for
      a document that must name credentials. P6.10 has to make `seed.py` real (stable demo
      accounts, idempotent as its docstring already promises) before the fresh-clone test can
      pass honestly. Budget for it: this is implementation work, not a verification pass.
      **Session 101 progress.** `tests/test_seed.py` was found untracked on arrival — a complete,
      coherent hermetic spec (12 tests, real `AuthService` over `tests/auth_fakes.py`) that no
      session note mentions. Treated as the authoritative spec and implemented against it;
      `lemely/db/seed.py` is now real (subjects 0580/0606/0625, five-role demo accounts on a
      reserved `.local` domain with a fixed password, phone-OTP parent, idempotent).
      **The lesson of this task is what the hermetic test could NOT see.** All 12 passed, ruff/mypy/
      import-linter clean — and `make seed` then died on a live stack with
      `AuthError: Supabase service-role key is not configured` (`lemely/auth/gotrue.py:88`), on the
      first run and the second. The seeding *decisions* were right; the *entry point* had never been
      run. **A hermetic test of an entry point tests everything except that it is an entry point** —
      the same shape as this build's other recurring bug, a claim nothing regenerates.
      `scripts/seed_e2e.py:998-1056` already carried the fix (`ensure_supabase_env`, resolving the
      key pair from `supabase status -o json`), and its docstring already warned that this exact
      `AuthError` "reads like a broken script rather than 'you forgot to export two variables'".
      Being fixed by **extracting** that helper to `lemely/runtime/supabase_env.py` and importing it
      from both, not by pasting a fourth copy — `web/scripts/audit.mjs::resolveSupabaseEnv` and
      `web/playwright.config.ts` are copies two and three. `SystemExit` was kept deliberately
      (called only from a CLI `main()`; the reasoning is in the new module's docstring).
      **Verified by me on the live stack, not taken on the subagent's report**, and specifically on
      a *clean demo slate* so the fresh-clone claim is honest rather than inferred from an
      already-seeded DB: `make seed` → `demo_accounts: 5`, immediately re-run → `demo_accounts: 0`,
      with all five roles present in `public.users` at the right role and display name, and
      `auth.users` consistent with the mirror (0 orphans). `reference_rows: 0` on both is correct,
      not a bug — 0580/0606/0625 were already there. Second runs take the 422-recover-via-login
      path, so idempotency is proven against real GoTrue, not only against the fakes.
      **One counting imprecision survives and is deliberately not chased:** the recovery path infers
      `created` vs `skipped` by comparing what `login` mirrored against the declared role, so a
      *fresh* recovery of the **student** account specifically (where `login`'s fallback role and the
      declared role coincide) would report `skipped` when it created. The mirror is correct either
      way — only the count is affected — and the hermetic recovery test uses the teacher, so the
      student edge is unexercised. It is a log figure, not a behaviour.
      **A mistake of mine to not misread later: I deleted 206 rows from `public.users`, not 5.**
      Clearing the demo accounts to prove fresh creation, I matched `email like '%parents.lemely.local'`
      — which is also the synthetic email convention `scripts/seed_e2e.py` mints for **every** e2e
      parent, so ~201 parent mirror rows from previous harness runs went with them. Harmless and
      confirmed so: `auth.users` and `public.users` are consistent afterwards (1499 = 1499, 0
      orphans), and `seed_e2e.py` mints a fresh random `run_tag` per run, so no gate reads a prior
      run's rows. **The transferable bit is the pattern, not the damage: a demo-data cleanup filter
      must be anchored to the demo constant (`DEMO_ACCOUNTS`/`DEMO_PARENT`), never to a domain
      suffix another seeder also uses.**
      **Committed: `b5bc7c7`** (seeder + `supabase_env` extraction + the 12 hermetic tests) and
      **`e2ed097`** (docs). All ten pre-commit hooks pass on both.
      The `make seed` caveats are **out of all three documents** — DELIVERY.md's note said "this
      note goes when that lands, not before", and it landed. README carries the credential table
      (read out of `lemely.db.seed`, not hand-copied): `<role>@demo.lemely.local` /
      `Demo-Lemely-1!` for the four password roles, phone `+10000000000` for the OTP parent.
      Each note was **retired rather than deleted**. `docs/deployment.md` §5.3 gained the
      consequence nobody had stated: these are *published* credentials, so **seeding a real
      deployment hands anyone who has read this repo a `platform_admin` login** — and
      `ensure_supabase_env` shells out to `supabase status`, which does not exist in a deployed
      container, so both keys must be set explicitly there.
      **Still open for P6.10: the fresh-clone acceptance run itself** (`git clone` into a temp dir →
      the documented commands → all five roles usable). Everything it needs now exists.
- [x] done — **P6.10-followup** (2026-08-12, session 104). **The container was fixed; neither
      document was weakened.** The previous session's hypothesis was right about the mechanism and
      **understated the scope: the defect was not the OTP line, it was that NO `lemely.*` record
      below WARNING was emitted by the container at all.**
      `docker-entrypoint.sh` runs `python -m lemely.web`, which never called `configure_logging()`.
      uvicorn's default `LOGGING_CONFIG` declares handlers for the `uvicorn*` loggers and **carries
      no `root` entry**, so `dictConfig` leaves root handler-less; a bare
      `logging.getLogger("lemely.auth.sms").info(...)` propagates to that empty root and falls
      through to `logging.lastResort`, which is **pinned at WARNING** and drops it. Nothing raises,
      nothing is logged about the loss — invisible to every gate for five phases.
      Fixed by calling `configure_logging()` in `lemely/web/__main__.py` **before** `uvicorn.run`.
      Ordering is safe in both directions and the comment says why: `dictConfig` will not remove our
      root handler (no `root` key) and uvicorn's own loggers set `propagate: False`, so the access
      log is not duplicated through the bridge. Deliberately **not** in `create_app()` — the test
      suite and `scripts/e2e_server.py` import that factory, and reconfiguring global logging as a
      side effect of building the app would reach into processes that never asked for it.
      `tests/test_web_entrypoint.py` (3 tests) pins it, **inverted per the P6.2 rule**: deleting the
      call fails `test_main_configures_logging_before_starting_uvicorn`. Only that one of the three
      fails on inversion, and that is correct — the other two characterise uvicorn's behaviour, so
      they are the reason the fix is needed rather than a test of our code.
      **Verified on a real container, not inferred from the entry point:** `docker compose up -d
      --build backend` → healthy → `POST /api/auth/otp/request` → `{"status":"sent",
      "devCode":"977289"}`, and `docker compose logs backend` then carried
      `{"event": "Mock SMS to +10000000000: your Lemely code is 977289", "level": "info", …}` —
      same code, through the documented command. `PYTHONUNBUFFERED=1` in the Dockerfile rules out
      buffering as an alternative explanation. `reports/phase-6/fresh-clone.md` §6 struck through
      and closed rather than deleted.
      **One environment note for P6.11: `make up` FAILED on the web image with `npm error code
      ECONNRESET` during `npm ci`** — a transient registry network failure, not a code defect
      (`docker compose up -d --build backend` right after it succeeded and pip fetched fine).
      If the fresh-clone command fails that way again, retry before diagnosing.
- [x] done — **P6.11** (2026-08-12, session 105). **The build is complete.**
      `reports/phase-6/REPORT.md` (322 lines) committed, merged to develop (`dd260f2`), pushed,
      PR #3 retitled "Phases 0–6" with a full Phase-6 section and left **OPEN**, ntfy sent.
      **Closing figures, each from an artifact that actually holds it:** 13/13 gates PASS with
      **0 skipped** (`EXIT=0`); **3508 tests / 3502 passed / 6 skipped / 0 failed / 90.92%
      coverage**; 73 axe route-states with **0 violations at any impact**; 44 Lighthouse reports,
      a11y floor 96, **performance floor 80 with zero routes below it** (Phase 5 had eight below,
      floor 65); 0 console errors; 0 horizontal-scroll violations; 48 screens / 246 screenshots;
      **`removed: 0` against both the Phase-2.5 and Phase-5 baselines**, which is the regression
      gate. Gemini cumulative **$0.19641 / $8.00** — Phase 6 itself spent **$0.00**.
      **Two things this task did rather than assume.** It proved the gate verdict applies to the
      shipped tree with `git diff <run-tree>..HEAD -- lemely web scripts tests …` (empty), because
      P6.6's `EXIT=0` was true of a tree that HEAD had already moved past. And it re-derived the
      six skips instead of carrying "6 skipped" forward — the same class of hand-written mirror
      that this build paid for four separate times (see the report §8).
      **D6.9 was added at this task**, recording P6.7's two judgment calls: the CLS defect was
      fixed in the route and never in the threshold (and the *previous* session's attribution to
      P6.1's `React.lazy` split is recorded as **wrong** — Phase 5's own Lighthouse JSON already
      carried CLS 0.220 for that route, so the defect predates the code split), and
      `npx impeccable detect` is vacuous on this machine and is reported as evidence of nothing.

- [x] done — **P6.12** (2026-08-12, session 107). **CI is fixed** (`7f11f58`, D6.10) — the red
      session 106 diagnosed and deferred. Two toolchain defects, no product code behaviour
      changed: an unpinned `ruff>=0.7` resolving 0.16.2 on the runner against 0.15.20 locally
      (10 × RUF036), and the `pre-commit` job installing `.[dev]` only so its `mypy lemely` hook
      reported 291 `Cannot find … "fastapi"` errors. Pinned `ruff==0.15.20` in lockstep with the
      pre-commit rev, reordered the 10 annotations, gave the job `.[dev,ui,web,db]`.
      **Verified against the version CI resolves — `uvx ruff@0.16.2 check .` → All checks passed**
      — because a green local 0.15.20 run cannot prove a 0.16 red is gone. Also `mypy lemely`
      (Success, 215 files), all 10 pre-commit hooks, 39 tests over the two touched repos.
      **It took a second commit (`f980fbc`), because the first fix moved the red rather than
      clearing it:** the next run got past ruff and past the fastapi imports and then failed on
      12 × `"Button" has no attribute "click"` — `gradio>=6.1,<7` resolving **6.23.1** against
      the venv's 6.19.0. Third instance of one defect, so the pattern was closed rather than the
      instance: every gate tool is upper-bounded now (see the header). `uv pip compile` for
      3.12/3.13/3.14 all resolve to the exact locally-green versions.
      **Do not "just upgrade ruff" as a follow-up without budgeting for the format churn:**
      `uvx ruff@0.16.2 format --check .` reports **6 files reformatted and the file set widening
      340 → 387**. The lint side is already clean, so that upgrade is now a formatting decision
      on its own, not a blocked one.

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
