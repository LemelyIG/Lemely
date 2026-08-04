# BUILD STATE — single source of truth

status: RUNNING            # RUNNING | COMPLETE | HALTED
current_phase: 2
last_updated: 2026-08-04T14:50:00Z
gemini_spend_usd: 0.0580

## Rules for maintaining this file
- Update BEFORE starting and AFTER finishing every task. Assume sudden death.
- Keep exactly one task `doing` at a time.
- When all Phase-6 acceptance criteria pass and DELIVERY.md is committed,
  set `status: COMPLETE` — the supervisor stops on this value.

## Phase 0 — Foundation repair
- [x] done — Read LEMELY_AUDIT.md fully; verify repo builds & tests pass locally
- [x] done — Fix ruff format on main-derived develop branch; create develop branch
- [x] done — Add web/ (typecheck, lint, build) + web extra to CI
- [x] done — Decide det parser: wire io/det/ OR keep monolith; delete the loser
       (D0.5: wired io/det/, deleted monolith. 371 passed, 84.13% cov. MCQ/practical
       parse correct; theory escalates via reconciliation ParseError — verified on 4 PDFs)
- [x] done — Persistent file-backed Gemini USD tracker, $8 hard cap, $4/$6 ntfy warnings
       (D0.6: CostLedger at {output_dir}/gemini_spend.json; verified cross-process
       persistence + once-per-threshold with 2 real OS processes; 388 passed, 84.62%)
- [x] done — HistoryStore: surface corruption, add schema_version
       (load() now raises ParseError on unreadable/invalid-JSON/schema-mismatch/
       future-version files; missing file still returns empty. schema_version=1
       persisted. Also fixed example_toml trailing-newline drift. 393 passed, 84.66%)
- [x] done — Single lockfile mechanism; .env.example; fix GEMINI_API_KEY mapping trap
- [x] done — Remove dead: respx, live marker; leave lib/api.ts for Phase 2
- [x] done — Acceptance: doctor real Gemini reachability (models.list zero-token ping)
- [x] done — Quality gates green; phase report; merged develop; PR #3 develop→main; ntfy
       (PHASE 0 COMPLETE. reports/phase-0/REPORT.md; 395 passed/84.56%; PR #3 open,
       NOT merged — human reviews main. Gemini spend $0.00.)

## Phase 1 — Database + Auth + Tenancy
Branch from `develop` as `feature/phase-1-db-auth-tenancy`. Expanded from MISSION §4.
- [x] done — Local Supabase stack committed: `supabase/` config, `supabase init/start`
       (Docker), seed scripts, Makefile targets (db-up/db-down/db-reset/seed), docs
       (P1.1: supabase/config.toml + seed.sql; Makefile db-* + seed targets; docs/database.md.
       DatabaseSettings/SupabaseSettings added to config. Static gates + suite green.)
- [x] done — SQLAlchemy 2 + Alembic wired to local Postgres; base config + first migration
       (P1.2: lemely/db/{base,session,seed}.py + migrations/env.py; empty 0001_baseline head;
       Base w/ naming convention; alembic reads Settings.database.url. Live boot verified:
       supabase start + alembic upgrade head applied against local Postgres.)
- [x] done — Full relational schema (additive-only for later phases): users/profiles(role),
       schools, school_memberships(teacher↔school), seats, subscriptions+plan_tiers
       (manual activation flag), parent↔child links, classes, class_enrollments, subjects,
       papers(board/subject/session/year/variant/paper#), mark_schemes, uploads, attempts,
       question_results(marks,max,confidence,method-mark breakdown), weakness_records,
       review_queue, announcements, notifications, devices/sessions, xp_events, streaks
       (P1.3: 22 tables across 8 model modules + enums.py; migration 0002_core_schema.
       Fixed a blocking bug in the WIP: uuid/datetime/date were TYPE_CHECKING-only so
       every model failed to configure (MappedAnnotationError) — now runtime-imported.
       Enum server_defaults cast as ::type so alembic check is drift-free (D1.3). Verified
       live: downgrade base→upgrade head applies against local Supabase PG; `alembic check`
       = "No new upgrade operations detected". Added tests/test_db_schema.py (metadata +
       real-PG integration, skips if PG down). Gates green: 402 passed / 84.92% cov;
       ruff/mypy/lint-imports clean.)
- [x] done — Supabase Auth (GoTrue): email/password signup+login per role; parent phone-OTP
       behind provider abstraction with a MOCK SMS provider (logs OTP; one switch to real)
       (P1.4: lemely/auth/ — GoTrue REST client (admin create + password grant), SmsProvider
       protocol + MockSmsProvider, in-memory OTP store, AuthService mirroring GoTrue users →
       public.users, FastAPI /api/auth router. D1.5 recorded AND IMPLEMENTED: backend is the
       sole token issuer — signup/login/OTP all mint self-signed HS256 tokens; GoTrue's ES256
       token is discarded, one offline validation path. The live test (test_auth_live.py)
       initially FAILED — signup forwarded GoTrue's ES256 token which HS256 decode rejects
       ("alg not allowed"); D1.5 was a recorded-but-unimplemented decision. Fixed:
       tokens.mint_access_token(provider=...) generalises the minter; service.signup/login
       call _mint_email_token(provider="email"). Hermetic tests that asserted the old
       `gotrue-access-` prefix now decode+validate claims. Verified LIVE vs real GoTrue+PG:
       429 passed / 12 subtests / 0 skip (keys set) / 85.80% cov; static gates clean.)
- [x] done — FastAPI JWT validation middleware; replace the anonymous get_auth_context stub
       (P1.5: lemely/web/deps.py get_auth_context is now a real dependency — HTTPBearer +
       decode_token (HS256, shared jwt_secret) → AuthContext(user_id=sub, role=app_metadata.role,
       email, phone). Every failure (no header, bad sig, expired, wrong aud, missing/unknown
       role) → 401 with WWW-Authenticate: Bearer. AuthContext is now a frozen dataclass; the
       anonymous default is GONE. Existing web tests already override get_auth_context via
       dependency_overrides so they stayed green. tests/test_auth_dependency.py added (8 tests:
       valid/all-5-roles/missing-header/garbage/wrong-secret/expired/unknown-role/missing-role).
       437 passed / 12 subtests / 85.88% cov; static gates clean. NOTE: routes are not yet
       role-gated — that is P1.6 RBAC.)
- [x] done — RBAC dependency on EVERY route; kill both IDOR endpoints
       (POST /student/plan, POST /student/onboarding); row-level ownership checks
       (student=self; parent=linked children; teacher=their classes; school_admin=their
       school; platform_admin=all)
       (P1.6, D1.6: require_role(*roles) factory in deps.py (401 then 403). Student routes →
       require_role(Role.student), all keyed off auth.user_id (self-ownership inherent).
       Teacher router → router-level require_role(teacher, school_admin, platform_admin).
       IDOR killed: studentId removed from StudyPlanRequest/OnboardingRequest; identity is
       auth.user_id, smuggled id → 422. /health + /auth/* stay public. tests/test_authz_matrix.py
       (31 tests: no-token→401, wrong-role→403, IDOR-kill, real-token e2e). 468 passed / 12
       subtests / 86% cov; ruff/mypy/lint-imports clean. HONEST LIMITATION (D1.6): teacher
       per-tenant ownership (own classes only) is DEFERRED — teacher routes still read the
       shared interim HistoryStore; role boundary IS enforced (students/parents locked out),
       row-level teacher→class ownership lands when routes move to the DB class model.
       Parent routes: none exist yet (parent portal is Phase 3). ADVERSARIAL REVIEW still
       pending — run reviewer subagent on this diff at phase acceptance.)
- [x] done — Migrate HistoryStore JSON → Postgres; migration script + parity tests; the
       WEB/product surface now reads/writes history in Postgres (D1.8/D1.9).
       (D1.8: lemely/db/history_repo.py DbHistoryStore preserves the load/append/list_students
       surface over StudentHistory/PaperRecord (→ Attempt + WeaknessRecord rows); migrate_json_history()
       walks JSON students, reports unmigratable legacy keys. tests/test_history_repo_parity.py:
       6 PG-integration parity tests (model_dump parity vs JSON store, ordering, list_students,
       non-UUID rejection, migration incl. skipped legacy key). D1.9: get_history_store → DB store;
       HistoryStoreProtocol + now_iso moved to core/history.py; student/teacher routers + web
       grading service annotate the Protocol. 488 passed / 1 skipped / 12 subtests / 84.92% cov;
       ruff/format/mypy/lint-imports clean. THREE commits: 26b0b0d (repo+parity), 5cabb58 (web swap).
       DEVIATION (D1.9): io/history_store.py NOT deleted — it is ALSO used by app/cli.py and
       app/gradio_* (local, unauthenticated, no-UUID tools). Deleting it would force Postgres on
       those; out of the task's "web routers" scope. Web migrated now; JSON store retained for
       CLI/Gradio; full deletion deferred to the explicit follow-up below.)
- [ ] todo — (deferred, D1.9) Migrate CLI + Gradio history to the DB (or retire Gradio), THEN
       delete lemely/io/history_store.py + tests/test_history_store.py. Parity already proven, so
       low-risk. Not blocking Phase 1.
- [x] done — Seat model: school_admin invites/creates N students against seat quota; a
       student may ALSO hold a personal subscription simultaneously
       (P1.10/D1.10: SeatService (lemely/db/seat_repo.py) — on-demand seat allocation w/
       FOR UPDATE quota lock (TOCTOU-safe); ownership+quota checked before account creation so
       no orphaned accounts; revoke frees a slot, keeps the account, idempotent. Account creation
       via StudentAccountCreator seam; real AuthServiceStudentCreator (web/deps.py) wraps
       AuthService.signup pinned Role.student; invite generates one-time temp password when
       omitted. /api/school/seats router (list/invite/{id}/revoke) gated school_admin-only at
       router level (even platform_admin → 403). get_seat_service wired in deps + reset_singletons.
       Coexistence with personal Subscription proven. tests/test_seat_repo.py (12 PG-integration:
       quota/ownership/revoke/coexistence/non-uuid) + 6 new /api/school authz-matrix cases.
       509 passed / 1 skipped / 12 subtests / 85.00% cov; ruff/format/mypy/lint-imports clean.)
- [x] done — Device/session registry: max 3 concurrent devices; 4th login silently
       invalidates the oldest session (P1.11, D1.11 — chose fork (a) sid-gated request-time
       DB liveness check).
       (lemely/db/device_repo.py DeviceRegistry: register_login locks the user row FOR UPDATE
       (TOCTOU-safe like SeatService), reuses the row for a matching (user, client_device_id)
       or mints a fresh device, then evicts the oldest-by-last_seen_at beyond MAX_DEVICES=3 by
       setting revoked_at. tokens.mint_access_token gained an optional session_id claim;
       decode_token surfaces it. get_auth_context does a single indexed liveness read ONLY when
       a session_id claim is present (offline path preserved for hermetic/seat-invite tokens) →
       401 on evicted/unknown session. AuthService.signup/login/verify_otp take an optional
       DeviceContext; the /api/auth router builds it from body.deviceId + User-Agent. Additive
       migration 0003_device_client_id adds devices.client_device_id + index; applied live +
       `alembic check` drift-free. get_device_registry singleton wired in deps (+ reset_singletons).
       tests/test_device_repo.py: 10 PG-integration (3-coexist, 4th-evicts-oldest-only, same/distinct
       client-id dedupe, no-id fresh, liveness unknown/garbage, revoke ownership+idempotent,
       active_devices ordering, unknown-user, non-uuid). test_auth_dependency.py +3 hermetic
       (no-sid skips check; live→200; evicted→401). 522 passed / 1 skipped (live auth, no keys) /
       12 subtests / 85.41% cov (>85.00% prior); ruff/format/mypy/lint-imports clean.)
- [x] done — Acceptance: E2E auth tests for all 5 roles; adversarial security review
       (reviewer subagent) finds no unauthenticated/cross-tenant access; every route has
       an authz test. Quality gates (§6) green; report reports/phase-1/REPORT.md; merge
       develop; PR develop→main; ntfy
       (PHASE 1 COMPLETE 2026-08-01. tests/test_auth_e2e_roles.py: 5-role RBAC matrix (allowed→200,
       denied→403, no-super-role invariant) + parent OTP E2E through get_auth_context. Live
       tests/test_seat_invite_live.py PASSES vs real Supabase+GoTrue (seat-invite→login→app_role=
       student) — verified this session (both live tests green with keys). Reviewer adversarial
       sweep: NO Critical/High auth bypass; verified-clean on alg-confusion/session-liveness/
       signup-escalation/seat-IDOR/token-aud-exp/role-forgery. Fixed 3 findings, recorded D1.12:
       H2 teacher-upload cross-tenant-write kill (dropped caller student_id → paper_id key),
       M1 non-UUID schoolId/seat_id → 422 not 500 (typed uuid.UUID + regression tests),
       M2 removed fabricated "0" scheme stat cards (honesty). Gates: 548 passed / 2 skipped
       (live-only, pass with keys) / 12 subtests / 85.44% hermetic cov (>84.56% baseline);
       ruff/format/mypy(111 files)/lint-imports clean; web inherited-green (untouched since
       develop). reports/phase-1/REPORT.md committed. Merged develop; PR develop→main opened
       (NOT merged); ntfy sent.)

## Phase 2 — The core loop, real and end-to-end
Branch from `develop` as `feature/phase-2-core-loop`. Expanded from MISSION §4/§9. Order
front-loads pytest-verifiable BACKEND work (safest unattended) then frontend then E2E.
Each task: update STATE before/after, commit small, run §6 gates before merge.

- [x] done — P2.1 Real correction pipeline: make `POST /api/student/correct` the real
       SSE-driven pipeline (currently a stub that emits one WARNING + [DONE]). Keyed off
       auth.user_id (student token, RBAC already enforced). Flow: accept an uploaded
       paper (by paper_id from the upload route) → metadata detect → fetch/parse mark
       scheme (stored corpus; escalate to Gemini per chain) → answer extraction → marking
       w/ method-mark awareness → per-question + per-paper confidence → grade + boundary
       prediction → weakness detection → PERSIST (Attempt + QuestionResult rows incl.
       marks/max/confidence/method-mark JSONB + WeaknessRecord) via the DB repos → return
       result the dashboard reads. Low-confidence → review_queue row. Gemini MOCKED in all
       tests. Integration test (real local PG) proving persistence + SSE frames + confidence.
- [x] done — P2.2 Grade-boundary ingestion: scrape historical per-paper-variant thresholds
       for 0580/0606/0625 (all available sessions) from public mirrors (gceguide/
       papacambridge/xtremepapers) with provenance; parse into the `papers`/boundary table;
       prediction = exact per-variant lookup → fallback to per-subject historical average
       with an "estimated" flag surfaced in the API/UI. Use a small checkpointed workflow
       for the scrape/parse fan-out; commit parsed data + provenance. Tests for lookup +
       fallback-flag.
       (D2.1: kept `GradeBoundaryStore`/`resolve()` file-backed, not a DB table — CLI/Gradio
       have no DB session (D1.9). Deviation: sourced from cambridgeinternational.org directly
       (official primary source) instead of the 3 named mirrors — gceguide.com is now a
       squatted gambling-slot site (flagged so no future session trusts it); papacambridge/
       xtremepapers were viable but a re-host is worse provenance than the primary CAIE PDFs.
       Deviation: no workflow fan-out — once the page/PDF structure was known the task was
       deterministic parsing, not judgment work, so a direct script
       (`scripts/ingest_grade_boundaries.py`, pdfplumber) was simpler/cheaper/rerunnable.
       Script fetched all 13 published sessions (Mar/Jun/Nov 2022–2025 + Mar 2026 not-yet-
       published) × 3 subjects = 347 real per-component exact entries into
       lemely/data/grade_boundaries.json (was: 0 exact, hand-guessed identical 80/70/60/50/40
       defaults for all 3 subjects) + lemely/data/grade_boundaries_provenance.json (source URL
       per key). `_defaults` now genuinely computed per-subject averages from the scraped data
       (verified distinct per subject). "Estimated" flag: `boundary_source` Literal already
       encoded exact/subject_default/global_default — reworded the two non-exact
       `_integrity_summary` copy strings in lemely/web/routers/student.py to read as an
       estimate disclosure (no new field needed). Tests: 4 new cases in
       tests/test_grade_boundaries.py (defaults are distinct+real not identical guesses,
       monotonically ordered, a known scraped session resolves exact, an unscraped year falls
       back) + a provenance-completeness test (every exact key has a source_url starting
       https://cambridgeinternational.org). Also fixed a pre-existing uv.lock drift (the `db`
       extra's alembic/sqlalchemy/psycopg/pyjwt were declared in pyproject but never resolved
       into the lock). Gates (orchestrator-verified, Postgres unreachable this session so
       DB-integration tests skip as usual): ruff/format/mypy(114 lemely + 1 scripts)/
       lint-imports clean; full suite green, cov-fail-under=70 met (81.28% with DB tests
       skipped, consistent with prior skip-pattern sessions). 20/20 test_grade_boundaries.py
       pass standalone.)
- [x] done (with a documented gate deviation, see D2.5) — P2.3 Accuracy harness + golden
       fixtures: obtain real past papers + mark schemes for the 3 subjects; generate synthetic
       handwritten answer sheets (handwriting fonts, ink variation, scan noise/skew/blur/
       rotation) with known ground-truth spanning correct / partial (method marks) / wrong.
       COMMIT fixtures. Gate thresholds: ≥99% MCQ agreement; ≥95% mark-level on structured;
       100% of disagreements carry confidence below the review threshold. Calibrate the review
       threshold from harness data. Live-Gemini validation obeys §8 budget (mock in CI).
       CLOSED 2026-08-04 per **D2.5**: measured state is mark_accuracy 83.8% / flag_recall
       27.3%, below the §4 target. Threshold tuning (D2.3) and the deterministic
       calculated-answer fix (D2.4) are both exhausted as approaches; the remaining gap
       (0625 `5b`-style method-credit errors) needs free-form algebraic method verification,
       out of scope for this pass. NOT silently marked passing — carry into DELIVERY.md at
       P2.10 as an explicit honest limitation.
       SUB-PLAN (this session, recorded so a killed session can resume mid-task):
       1. [x] Vendored 3 OFL handwriting fonts (Caveat/IndieFlower/PatrickHand) at
          lemely/data/fonts/handwriting/ + LICENSE-OFL.txt attribution.
       2. [x] lemely/accuracy/synth.py: render (question_id,text) pairs onto a
          handwriting-font page image + scan-noise augmentation (rotation/blur/noise)
          → multi-page scan.pdf via Pillow. Deterministic per-seed (pinned PDF
          metadata). 7 hermetic tests green. Added numpy>=2,<3 as a direct dependency.
       3. [x] Extended lemely/accuracy/harness.py: measure_accuracy() previously
          BYPASSED extraction entirely (fed ground-truth text straight into
          correct_paper; id_match_rate was always None) — confirmed gap vs the design
          doc. Fixed: cases with scan_path now call the real extract_answers() seam
          (lemely.web.services.grading) → id_match_rate computed for real + EXTRACTED
          (not ground-truth) answers feed correct_paper for true end-to-end
          mark_accuracy. Cases without scan_path keep the old correction-only bypass.
          19 hermetic tests green (15 pre-existing + 4 new, Gemini/extraction mocked).
       4. [x] Authored 4 real golden fixtures under tests/golden/ for 0625 (Physics)
          from the 2 real mark schemes already on disk (0625_s20_ms_31.json theory +
          0625_m20_ms_12.json MCQ): theory_correct/partial/wrong (7 questions each,
          1a_i/1b/4a/5b/11b/12b/12c — picked because their answer_points are
          self-contained formula+number M/A mark points, no diagram dependency I
          couldn't verify) + mcq (8 questions, 5 matching the real scheme answer / 3
          deliberately not, for genuine MCQ-agreement signal). scan.pdf rendered via
          synth.py (verified visually — realistic). All 4 mark_scheme.json subsets
          validated against the real MarkScheme pydantic model. Full suite green:
          0 failures, 45 skips (Postgres/live-auth, as usual), 81.89% cov; ruff/
          format/mypy(115)/lint-imports clean. COMMITTED this checkpoint before any
          live-Gemini spend.
       5. [x] Ran live-Gemini measure-accuracy batch (2026-08-04) against the 4 committed
          fixtures: `lemely doctor` confirmed gemini_reachable=true first; ran
          `lemely measure-accuracy --golden tests/golden --results-dir tests/golden/results`.
          All calls hit the disk cache (real Gemini responses cached from an earlier
          live run in this same output_dir — outputs/gemini_spend.json cumulative_usd
          stayed at 0.0102 across the run, i.e. genuinely-real cached data, zero new
          spend). Result → tests/golden/results/2026-08-04-2a9af42.json (now gitignored
          as a regenerable artifact — added `tests/golden/results/*.json` to .gitignore,
          .gitkeep still tracked). n=29 questions across 4 fixtures.
             Metrics: mark_accuracy 89.7% (target >95%, MISS) · mark_accuracy_theory 85.7%
             (MISS) · id_match_rate 100% (target >99%, PASS) · flag_precision_HIGH 89.3%
             (target >99%, MISS) · flag_recall 0.0% (target >85%, MISS).
             3 wrong (all theory, all the SAME failure mode: method-mark partial-credit
             off-by-one, predicted 3 vs truth 2 on questions 1b/5b/12c) with confidence
             scores 0.85, 0.98, 0.98. Correct-question confidences range 0.65-1.00, with
             11 correct answers ALSO at 0.98 and 8 at 1.00 — i.e. confidence score does
             NOT cleanly separate correct from wrong at this fixture's scale; 0.98 is the
             stated confidence for both 11 correct and 2 of the 3 wrong answers.
       6. [x] done — Delegated the design decision to the `architect` subagent (Opus-tier),
          since this orchestrator run is on Sonnet not Opus — satisfies the MISSION §5
          reservation without requiring a supervisor relaunch. D2.2 recorded in
          DECISIONS.md. Decision: single shared constant `REVIEW_CONFIDENCE_THRESHOLD =
          0.90` in `lemely/core/schemas.py` (not wired to config — an accuracy-gate
          invariant, not an operator knob); dedupe of (B) AND a 4th undiscovered duplicate
          (`teacher.py:119 _REVIEW_CONFIDENCE`) into this constant; (C) confirmed as the
          correct gate to calibrate against; proposed `awarded_marks != question.marks`
          secondary signal evaluated and REJECTED on the data (anti-correlated with itself
          across the 3 failure cases); added instead a zero-false-positive structural
          signal (out-of-range award flags independent of confidence, fires 0x on current
          corpus) + `review_reason` (was always None). Recomputed metrics on stored results
          (no new Gemini spend): flag_recall 0.0%→33.3%, flag_precision_HIGH 89.3%→91.7%.
          Value is explicitly PROVISIONAL (Physics-only, n=29); mandatory revisit trigger
          recorded for first 0580/0606 harness run. Orchestrator verified (did not just
          trust the subagent): ruff/ruff-format/mypy(115)/lint-imports clean; full pytest
          green (0 failures, 45 skips — Postgres/live-auth, consistent pattern), 81.92% cov
          (>70% floor; in line with the 81.28–81.89% range this skip-pattern has shown all
          P2.2/P2.3, not a regression). One test intentionally rewritten (documented, not
          weakened): `test_review_false_at_0_80` encoded the dead literal and cannot
          survive the fix; replaced with threshold-relative tests + an explicit regression
          guard. Phase-2 accuracy gate (§4) still does NOT pass — flagged honestly in D2.2,
          NOT fixed by this task (root cause is a marking-quality defect: A-marks awarded
          despite wrong final numeric value on genuine partial-credit questions — a future
          accuracy task, not a threshold task). Also flagged: `flag_recall_target` in config
          is 0.85 vs MISSION's stated 100%, a pre-existing config/mission mismatch, left
          unchanged. Superseded sub-brief kept below for provenance:
             THREE independent threshold values exist today (only coincidentally equal):
             (A) `gemini.escalation_confidence_threshold` (lemely/runtime/config.py:46,
                 default 0.80) — mid-marking retry trigger inside AICorrector.mark_question
                 (lemely/io/correction_ai.py:74,96): confidence < threshold + escalation
                 budget available → re-ask Gemini (thinking retry, then Pro escalation)
                 BEFORE the mark is finalized. Purpose: spend more budget to IMPROVE the
                 answer.
             (B) hardcoded literal `0.80` in `_build_ai_corrected`
                 (lemely/io/correction_ai.py:179): `needs_teacher_review=mark.confidence
                 < 0.80`. Sets the per-question review flag on the finalized
                 CorrectedQuestion — feeds the paper-level `needs_teacher_review`
                 aggregate (core/schemas.py), teacher UI badges (web/routers/teacher.py,
                 app/renderers.py), AND is the exact field the accuracy harness's
                 flag_recall/flag_precision metrics measure. This is a DUPLICATE literal,
                 NOT wired to config (g.escalation_confidence_threshold is in scope at
                 that call site) — numerically equal to (A)'s default today by accident;
                 will silently drift if (A) is ever tuned without updating this line.
             (C) `REVIEW_CONFIDENCE_THRESHOLD = 0.90` (lemely/db/attempt_repo.py:41) — the
                 real DB persist-time gate: `if qr.needs_teacher_review or
                 qr.confidence_score < REVIEW_CONFIDENCE_THRESHOLD` decides ReviewQueueItem
                 insertion (P2.1). This is what ACTUALLY determines whether a mark reaches
                 a human reviewer in production; it ORs with (B)'s flag.
             Consequence on this fixture: (B) flags 0/3 wrong (all confidences >= 0.80).
             (C)'s OR-with-confidence<0.90 catches 1/3 (the 0.85 one). The two 0.98-
             confidence wrong answers pass BOTH gates uncaught — they would reach the
             student/teacher dashboard as unflagged, 98%-stated-confidence WRONG marks.
             This is exactly the failure mode the Phase-2 gate exists to prevent
             ("100% of disagreements must carry confidence below the review threshold"),
             and it is currently NOT met.
             To make that gate literally true against this data, whichever value is "the
             review threshold" must exceed 0.98 (e.g. 0.99) — which would ALSO flag most
             of the 19 correct answers at 0.98-1.00, a severe precision hit. This fixture
             is ONE Physics paper/session, n=29, only 3 disagreements, all the identical
             failure mode (method-mark off-by-one) — too thin to responsibly calibrate a
             global production threshold; a number picked from these 3 points risks
             overfitting before 0580/0606 fixtures exist (see step 7, also unresolved).
             Questions for the Opus design pass to resolve and record in DECISIONS.md
             (D2.2): (1) dedupe (B) into config (wire to g.escalation_confidence_threshold,
             or give it its own named config field) rather than a silent literal; (2) is
             (C) — the only gate that actually reaches a human — the right thing to
             calibrate against the mission's "review threshold" gate criterion; (3) given
             the systematic-overconfidence finding (wrong method-mark answers score
             identically to correct ones), is a single global confidence threshold even
             sufficient, or does closing the gap need a secondary signal (e.g. treat any
             awarded_marks != question.marks with high stated confidence as inherently
             flaggable) — record the honest limitation either way, don't over-engineer in
             one pass; (4) pick and record the actual numeric value(s), explicitly labeled
             provisional/Physics-only if step 7's broader corpus isn't folded in first;
             (5) decide whether to resolve step 7 (0580/0606 sourcing) in the same pass
               before finalizing the number, or ship a documented provisional threshold now
               and revisit once broader fixtures land — either is fine per MISSION §1, just
               don't leave it silently undecided.
             Raw data + result JSON: tests/golden/results/2026-08-04-2a9af42.json
             (gitignored but present on disk this session; regenerate via
             `lemely measure-accuracy --golden tests/golden --results-dir tests/golden/results`
             if the file is gone — it's a cache-hit, so it costs ~$0).
       7. [x] done — Verified and committed the two `data-engineer` outputs from the prior
          (crashed) session: real 0580 Mathematics (s23 qp22) + 0606 Additional Mathematics
          (s23 qp12) mark schemes/papers under `Sources/` (gitignored) and 6 new golden
          fixtures `tests/golden/{0580_s23_qp_22,0606_s23_qp_12}_theory_{correct,partial,
          wrong}` mirroring the 0625 pattern. Verification done before trusting (MISSION §5):
          confirmed real Cambridge headers in all 4 sourced PDFs via pdfplumber (not
          fabricated); validated all 6 mark_scheme.json against MarkScheme; spot-checked
          answer points against fixture answers; confirmed wrong/partial variants carry
          genuinely altered answers. Fixed a latent bug the dispatch surfaced: `0580` had no
          `SubjectProfile` in `lemely/io/det/profiles.py`, so it fell through to
          `_DEFAULT_PROFILE` (paper 1 → MCQ, wrong for 0580 which has no MCQ component) —
          added `_MATHEMATICS_PROFILE` (1/3 Core, 2/4 Extended) and fixed a comment that
          incorrectly asserted 0580 paper 1 is MCQ. Gates: ruff/format/mypy(115)/
          lint-imports clean; pytest 100% pass (usual Postgres/live-auth skips — local
          Supabase stack could not be started this session, stale root-owned files under
          `supabase/.temp/start-secrets/` from a prior crashed container, not removable
          without root; flagged for a session with shell access to clean up, does not affect
          this step). Ran the mandatory D2.2 revisit (full `measure-accuracy` across all 10
          fixtures, n=68); recorded as **D2.3** in DECISIONS.md — full threshold-sweep table
          there. Result: metrics got WORSE with more data (mark_accuracy 89.7%→80.9%,
          theory 85.7%→78.3%, flag_precision_HIGH 91.7%→82.5%, flag_recall 33.3%→23.1%);
          13 theory disagreements now (was 3) across 3 papers/2 subjects; 0.90 threshold
          only catches 3/13 (23%); no non-degenerate threshold (<0.99) gets close to the §4
          100% target. `REVIEW_CONFIDENCE_THRESHOLD` kept at 0.90 (D2.3: raising it further
          is not supported by the data, confirms D2.2 more strongly than it changes it).
          Gemini spend +$0.0150 (cumulative $0.0502 / $8.00 ceiling). P2.3's accuracy gate is
          now measurable-and-failing (not measurement-limited) — the next step is the
          marking-quality fix, not more fixtures or threshold tuning.
       8. [x] done — Marking-quality fix: deterministic calculated-answer verification.
          Full detail + 3-iteration design history (two broken versions caught by live
          re-runs, not inspection) in **D2.4** (DECISIONS.md). Resumed on a dirty,
          untracked, uncommitted WIP diff with zero tests; added 20 unit tests before
          trusting any of it (MISSION §5). Final: `mark_accuracy` 80.9%→**83.8%**,
          `mark_accuracy_theory` 78.3%→**81.7%**, `flag_precision_HIGH` 82.5%→**85.5%**,
          `flag_recall` 23.1%→**27.3%**; diffed all 68 question results vs the D2.3
          baseline — exactly 2 changed, both fixes (0625 `1b`, `12c`), **zero regressions**.
          Gemini spend +$0.006 (cumulative $0.058/$8.00). Full suite green (0 failures,
          cov 81.95%); ruff/format/mypy/lint-imports clean.
          **§4 accuracy gate still NOT met** (83.8% < 95% target) — honest, not silently
          patched over. Remaining known gap: 0625 `5b` — Gemini credits a *method* point
          with no `calculated_answer` attached despite the shown working being wrong
          (omitted a subtraction step); this backstop only verifies stated numeric values,
          not free-form algebraic method correctness, which is a materially harder problem
          (see D2.4's "honest limitation" section). Threshold tuning is separately exhausted
          (D2.3). Two undone options remain, both explicitly still on the table: (a) a cheap
          second-pass "verify only the final value/method" Gemini call gated behind the
          existing escalation budget (MISSION-suggested alternative, not yet tried), or
          (b) accept the current state as a documented Phase-2 gate deviation and proceed to
          P2.4+. Next session: make that call explicitly (don't silently drift past it) —
          see "Next action" below.
- [x] done — P2.4 Plagiarism (answer≈mark-scheme) + AI-detection advisory flags wired into
       results as teacher-review signals ONLY (never auto-penalize; UI copy = signals not
       verdicts). Enable integrity path; surface in result payload + review_queue.
       PLAN (recorded before dispatch so a killed session can resume): PlagiarismChecker
       (core/plagiarism.py) + AIContentDetector (io/integrity.py) + IntegritySettings
       (runtime/config.py) + ReviewReason.plagiarism_flag/ai_detection_flag (db enums) ALL
       already existed but were completely unwired (only reachable via `check-integrity` CLI
       command + hermetic tests) — confirmed via tokensave search, zero callers in the web/db
       layers. Design: (1) add `plagiarism_flagged`/`ai_detection_flagged: bool = False` to
       `CorrectedQuestion` (core/schemas.py) — flat bools, not embedded IntegrityFinding, to
       dodge a schemas.py↔integrity_schemas.py circular import; (2) new
       `apply_integrity_checks(correction, mark_scheme, *, gemini_client, settings) ->
       CorrectionResult` in lemely/io/integrity.py: plagiarism via existing
       student_answer/expected_answer already on CorrectedQuestion (no mark-scheme lookup
       needed), ai_detection (opt-in, default OFF per IntegritySettings.ai_detection_enabled)
       via MarkScheme.get_question_by_id + AnswerPoint.point text as mark_scheme_points
       (no verbatim question-stem field exists in the mark-scheme model — question_command
       is the closest proxy, documented as best-effort); flagged findings append into
       review_reason (existing " | ".join pattern from D2.2) + needs_teacher_review=True,
       NEVER touch awarded_marks/maximum_marks; rebuild via `CorrectionResult(metadata=...,
       questions=...)` (not model_copy) so calculate_totals re-validates; (3) wire into
       `grade_paper` (web/services/grading.py) with a new optional `integrity_settings`
       param, called from web/routers/student.py's `run()` closure with `settings.integrity`;
       (4) db/attempt_repo.py: zip `correction.questions` with `attempt.question_results`
       (same order) to add extra ReviewQueueItem rows (reason=plagiarism_flag /
       ai_detection_flag) alongside the existing low_confidence check — no migration needed,
       enum values already exist from P1.3; (5) web/schemas.py QuestionResultDTO gets
       `plagiarismFlagged`/`aiDetectionFlagged` bools surfaced in the result payload. Teacher
       review-queue UI consumption is P2.8 (not touched — teacher.py has zero ReviewReason
       references today, confirmed). Frontend wiring is P2.6/P2.7 (SPA still all mock), out
       of scope here — DTO fields are the P2.4 finish line per the phase checklist wording
       ("surface in result payload + review_queue"). Dispatching to `implementer` (Sonnet).
- [x] done — P2.5 Upload path: plain file upload (25MB cap kept) + Supabase Storage +
       backend job. Scope narrowed to backend Storage wiring this session — camera-capture
       UI + client-side PDF assembly deferred to P2.7 (screen-by-screen wiring, CorrectPaper
       owns this flow); see **D2.6** in DECISIONS.md for full rationale. PLAN (recorded before
       dispatch so a killed session can resume): (1) `StorageSettings` (runtime/config.py):
       `bucket: str = "uploads"`, `signed_url_ttl_seconds: int = 3600`; add `Settings.storage`.
       (2) NEW `lemely/io/storage.py` mirroring `lemely/auth/gotrue.py`'s exact pattern:
       `StorageBackend` Protocol (`upload(bucket, object_path, data, content_type) -> None`,
       `download(bucket, object_path) -> bytes`, `create_signed_url(bucket, object_path,
       expires_in) -> str`); `HttpStorageBackend(settings: Settings)` — sync httpx against
       `{settings.supabase.url}/storage/v1/object/{bucket}/{path}` (POST upload, GET download)
       and `/storage/v1/object/sign/{bucket}/{path}` (POST, body `{"expiresIn": ...}`) using
       the service-role key (same `_service_key()` pattern as gotrue.py), raising
       `ExternalServiceError` on non-2xx like gotrue.py does; `FakeStorageBackend` (in-memory
       dict) for hermetic tests, same role as the existing `FakeGoTrueBackend` test double —
       check `tests/test_auth_service.py` or wherever that fake lives for the exact shape to
       match. (3) `get_storage_backend` singleton in `web/deps.py` (+ `reset_singletons`),
       returning `HttpStorageBackend(settings)`; tests override via
       `app.dependency_overrides[get_storage_backend] = lambda: FakeStorageBackend()`
       (same pattern as `get_gemini_client`/`get_attempt_repo` in test_student_correct.py).
       (4) `student_upload` (web/routers/student.py:420-457): replace `write_upload_capped`
       disk write with a `check_upload_cap(data, max_bytes=...)` size check (new tiny helper
       in upload_utils.py, extracted from `write_upload_capped`'s cap logic — keep
       `write_upload_capped` itself unchanged, teacher.py still uses it, OUT of scope per
       D2.6) + `storage_backend.upload(settings.storage.bucket, f"uploads/{user_id}/
       {paper_id.hex}/{filename}", data, content_type)`; `Upload.storage_path` now stores the
       Storage object key (same column, repurposed semantics, no migration). (5) `run()`
       closure (student.py, the `/student/correct` SSE pipeline, currently `scan_path =
       Path(owned.storage_path)` around line 560): download the object bytes via
       `storage_backend.download(...)` into a `tempfile.NamedTemporaryFile` (cleaned up in a
       `finally`), pass that local Path into the unchanged `extract_answers`/
       `resolve_mark_scheme` pipeline — keeps every downstream function filesystem-Path-based,
       minimal diff. (6) Tests: hermetic `lemely/io/storage.py` unit tests against
       `HttpStorageBackend` using a mocked httpx transport (`httpx.MockTransport`, matching
       whatever pattern `test_gotrue.py`/similar already uses for `HttpGoTrueBackend` — check
       first) covering upload/download/sign success + non-2xx error paths; a live-skip
       integration test (skip when `supabase.service_role_key` unset, matching
       `test_auth_live.py`'s skip condition) that round-trips a real object through the local
       stack IF reachable (it currently is not — will skip, that's fine per D2.6); updated
       `test_student_correct.py`/upload endpoint tests using `FakeStorageBackend` instead of
       asserting a local file was written to disk (check what those tests currently assert on
       disk paths and adapt); confirm the 25MB cap 413 test still passes against the new
       `check_upload_cap` helper. Dispatching to `implementer` (Sonnet).
- [x] done — P2.6 Frontend API foundation: resurrect web/src/lib/api.ts + @tanstack/
       react-query (remove dead-code status); auth login/token storage (deviceId minting
       per D1.11), bearer on every request; typed hooks. Vite proxy verified end-to-end.
       PLAN (recorded before dispatch so a killed session can resume): (1) NEW
       `web/src/lib/auth/storage.ts`: `getDeviceId()` (crypto.randomUUID(), minted once,
       persisted in localStorage key `lemely.deviceId`, per D1.11's client_device_id
       semantics); `Session` type `{accessToken, refreshToken, userId, role}`;
       `getSession()/setSession()/clearSession()` over localStorage key `lemely.session`
       (JSON). (2) NEW `web/src/lib/authTypes.ts`: TS interfaces mirroring
       `lemely/web/schemas_auth.py` field-for-field camelCase (SignupRequest, LoginRequest,
       OtpRequestBody, OtpVerifyBody, TokenResponse, OtpRequestResponse; Role union of the
       5 role strings). (3) `web/src/lib/api.ts`: `request()`/`streamActivity()` merge an
       `Authorization: Bearer <token>` header from `getSession()?.accessToken` (when
       present) ahead of caller-supplied headers; keep the existing generic `fallback`
       param on `request()` (still useful once P2.7/8 wire screens) but the new auth calls
       below never pass one — auth failures must surface, not silently succeed. (4) NEW
       `web/src/lib/queryClient.ts`: `new QueryClient()` (retry:1, refetchOnWindowFocus:
       false). Wire `QueryClientProvider` in `main.tsx` around the router. (5) NEW
       `web/src/lib/auth/AuthContext.tsx`: React context + provider exposing
       `{session, login(email,pw), signup(...), requestOtp(phone), verifyOtp(phone,code),
       logout()}`; each network call is a react-query `useMutation` wrapping
       `request<TokenResponse>('/auth/...', {method:'POST', body: JSON.stringify({...,
       deviceId: getDeviceId()})})`, on success `setSession(...)`; hydrates initial state
       from `getSession()` on mount; `logout()` calls `clearSession()`. (6) NEW minimal
       `web/src/portals/auth/Login.tsx` (email/password form using `useAuth().login`; on
       success navigate to `/student` or `/teacher` by resolved role) + `/login` route in
       `App.tsx` + a `RequireAuth` wrapper gating `teacherRoute`/`studentRoute` children on
       `session` presence + role match (student session→student portal only;
       teacher/school_admin/platform_admin→teacher portal; redirect unauthenticated to
       `/login`, redirect already-authenticated away from `/login`). Parent has no portal
       yet (Phase 3) — `verifyOtp` is wired in AuthContext but has no screen this task,
       consistent with P2.6 being foundation not full screen wiring (P2.7/8 own screens).
       No backend changes — DTOs already match `lemely/web/schemas_auth.py` exactly.
       Verification: `npm run typecheck && npm run lint && npm run build` clean (§6.3);
       manual Vite-proxy check by running `uvicorn` + `npm run dev` and confirming a
       request against `/api/...` through the proxy reaches FastAPI (local Supabase stack
       is down this session — same documented root-owned-dir issue, sudo unavailable in
       this sandbox too, confirmed again this session — so a full DB-backed login
       round-trip cannot be live-verified; proxy routing + payload shape is what gets
       verified, not a DB round trip; this is a carried environment limitation, not new
       scope creep). Dispatching to `implementer` (Sonnet).
       DONE + VERIFIED (2026-08-04). Implementer built exactly the plan: NEW
       `web/src/lib/auth/storage.ts` (deviceId mint+persist, Session get/set/clear over
       localStorage), `web/src/lib/authTypes.ts` (DTOs mirroring schemas_auth.py),
       `web/src/lib/queryClient.ts`, `web/src/lib/auth/AuthContext.tsx` (login/signup/
       requestOtp/verifyOtp react-query mutations, hydrated from storage, logout),
       `web/src/lib/auth/RequireAuth.tsx` (route guard + portalPathForRole: student→
       /student, everything else incl. parent/school_admin/platform_admin→/teacher as
       the closest existing surface pre-Phase-3), `web/src/portals/auth/Login.tsx`
       (minimal functional form, not final UI — P2.7/8's job). Edited `web/src/lib/
       api.ts` (request()/streamActivity() now merge Authorization: Bearer <token> via
       a shared authHeaders() helper; existing `fallback` param untouched), `web/src/
       main.tsx` (QueryClientProvider + AuthProvider — the AuthProvider addition was a
       correct, necessary deviation from the plan's literal text since useAuth() calls
       in App.tsx/Login.tsx cannot resolve without it; verified this is right, not a
       scope creep), `web/src/App.tsx` (/ and /login now resolve against session;
       teacherRoute/studentRoute wrapped in RequireAuth). Did not touch student/data.ts,
       teacher/data.ts, or any screen files — confirmed via git diff --stat (only the 6
       new + 3 edited files listed above). Orchestrator verified independently, not just
       trusted: re-ran `npm run typecheck` (clean) / `npm run lint` (oxlint exit 0, only
       pre-existing `only-export-components` fast-refresh warnings, same pattern already
       present on teacher/student index.tsx before this change) / `npm run build`
       (clean, dist/ produced, gitignored) myself; also independently started uvicorn +
       vite and curled through the Vite proxy myself (not trusting the subagent's
       report): `POST /api/auth/otp/request` → 200 (round-trips fully, no DB dependency);
       `POST /api/auth/login` missing password → 422 (DTO validation live); `POST
       /api/auth/login` well-formed → 401 "Supabase anon key is not configured" (proxy +
       routing + payload shape confirmed reaching the real auth handler; fails only on
       the already-documented down Supabase/GoTrue dependency, not a proxy/DTO issue).
       Killed both dev servers after, confirmed no leftover processes. `ruff check .`
       also re-run (no Python touched, sanity-only) — clean. No backend changes. No new
       dependencies added (`@tanstack/react-query` was already listed); `npm install`
       was needed since `web/node_modules` wasn't present this session — package-lock.json
       diff (npm-metadata-only, no dependency change) was reverted by the implementer, left
       untouched. Committing on feature/phase-2-core-loop.
- [ ] doing — P2.7 Student surface on real data (screen-by-screen delete student/data.ts):
       Overview (overall + per-subject), Subject (per-paper history + predicted boundaries/
       final grade + estimated flag), PaperResult (marks/method-marks/mistakes/weakness/
       confidence/integrity flags), CorrectPaper (real SSE upload→correct, kill setTimeout
       theatre), Onboarding/StudyPlan/Standings as far as Phase-2 scope needs.
       PLAN (recorded before dispatch so a killed session can resume; **D2.7** covers the two
       backend prerequisite changes). Executed SEQUENTIALLY (not a parallel workflow fan-out —
       every screen touches shared files: `index.tsx` route registration/crumbs/nav, and
       `data.ts`; concurrent agents editing those would conflict). Each sub-step: dispatch to
       `implementer`, orchestrator-verify gates, commit, tick off here.
       1. [x] done — Backend prereqs (D2.7): `PaperHistoryRowDTO.id` (index) + SSE `complete`
          frame `questions` key. Extend existing student-router tests for both new fields.
          Small, mechanical, backend-only — no frontend touch.
          (commit 48d125c. Also fixed a filtered-vs-full-index bug in `_subject_records`
          caught before shipping — now returns `(original_index, record)` pairs; regression
          test with an interleaved-subject fixture. Orchestrator-verified independently:
          re-ran ruff/format/mypy/lint-imports/pytest myself, matched implementer's claims —
          555 passed / 50 skipped Postgres-live, 0 failed.)
       2. [x] done — Frontend API foundation for this task: NEW `web/src/lib/studentTypes.ts`
          (TS interfaces mirroring `lemely/web/schemas_student.py` DTOs 1:1 camelCase:
          OverviewDTO, SubjectDTO incl. PaperHistoryRow.id, ResultDTO incl. TheoryQuestion/
          IntegrityRow, StudyPlanDTO, StandingsDTO, StudentProfileDTO, StudentUploadResponse);
          NEW `web/src/lib/hooks/useStudentApi.ts`: react-query `useQuery` hooks —
          `useOverview()`, `useSubject(code)`, `useResult(paperId)` — GET wrappers over
          `request()` from `lib/api.ts`; `useStudyPlan()` (GET) + a plan-post mutation;
          `useStandings()`; an onboarding-post mutation. Upload + correct are NOT react-query
          (multipart POST + SSE stream) — expose as plain async functions
          (`uploadScan(formData)`, and a `runCorrection(paperId)` async generator wrapping
          `streamActivity`) for CorrectPaper to call directly. No screen/data.ts/route changes
          in this step — foundation only, mirrors the P2.6 pattern.
          (commit 89531ad. Naming: Python DTO class minus `DTO` suffix, e.g. OverviewDTO ->
          Overview. IMPORTANT finding for later steps: SSE frame payloads from
          student_correct are snake_case at the top level (paper_id/attempt_id/max_marks/
          needs_review), NOT camelCase -- EventBus.publish forwards raw kwargs, bypassing the
          ApiModel alias layer; only the nested `questions` array is camelCase.
          StudentCorrectFrame in studentTypes.ts documents every frame shape observed across
          the full run() call graph. api.ts::authHeaders gained an isFormData flag so
          request() skips the JSON content-type for multipart uploads. Orchestrator-verified:
          re-ran typecheck/lint/build myself, clean, matches implementer's report.)
       3. [x] done — Overview screen + Subject routing skeleton: wire `Overview.tsx` to
          `useOverview()` (studentName/forecast/subjects/weakGlobal/momentum are real).
          Remove the `nextUp`/`agenda`/`igCalculator` cards and the hardcoded "Papers marked"/
          "Hours saved" stat cards + hardcoded greeting body text — none are backed by
          `OverviewDTO` and MISSION's honesty precedent (D1.6 finding M2: remove fabricated
          content, don't invent an empty state for it) applies. Subject row click navigates to
          `/student/subject/${s.code}` (was hardcoded `/student/subject`). Update
          `studentRoute` in `index.tsx`: `subject` → `subject/:code`; generalize the static
          `crumbs` lookup (currently an exact-pathname map, breaks on dynamic segments) to fall
          back to a computed crumb for `/student/subject/:code` and (step 5) `/student/result/
          :paperId`. Leave the sidebar's static "Physics 0625" nav item as a reasonable
          placeholder (no live subject list at sidebar-render time without an extra fetch —
          out of scope) OR drop it if the implementer judges that cleaner; record the call made.
          (commit ce573f4. Removed nextUp/agenda/igCalculator + hardcoded stat cards/greeting
          body per D1.6 M2 precedent; greeting falls back to "there" since studentName is a raw
          user id, not a display name (no name store yet). Fixed the static Physics nav link to
          /student/subject/0625 rather than dropping it. resolveCrumb() added with a marked
          slot for step 5's result route. Orchestrator-verified: re-ran typecheck/lint/build,
          clean.)
       4. [x] done — Subject screen: wire `Subject.tsx` to `useSubject(code)` via `useParams`.
          Paper-history rows link to `/student/result/${row.id}` using the new `id` field
          from step 1. 404 (no history for subject) → simple empty state, not a crash.
          (commit ceee575. Mechanical DTO swap — every section here was already data-backed
          in the DTO, structure unchanged. 404 gets a neutral empty state distinct from a
          generic error. Row nav target intentionally 404s until step 5 registers the route.
          Orchestrator-verified: typecheck/lint/build clean.)
       5. [ ] todo — CorrectPaper + PaperResult (coupled by D2.7's state-passing design — do
          together, one dispatch): CorrectPaper gets a real file input (scan required, optional
          mark-scheme file) → `uploadScan()` (multipart POST /student/uploads) →
          `runCorrection(paperId)` consuming `streamActivity` frames to drive the existing
          progress-step UI for real (marking_progress/warning/error frames — kill the
          `setTimeout` theatre and `progressSteps`/`detected`/`scanMeta`/`readChips`/`reassure`
          mock reliance where now-superseded by real frame data; `reassure` copy (explainer
          text, not data) may stay). On the `complete` frame, assemble a `ResultData`-shaped
          object from the frame's scalars + new `questions` key and `navigate(`/student/result/
          ${paperId}`, { state: assembled })`. PaperResult reads `useParams().paperId`; prefers
          `location.state` when present (full theory/integrity); else calls `useResult
          (paperId)` (history-sourced, structurally-empty theory/integrity — existing, honest,
          documented behavior, not a regression). Route registration: `result` →
          `result/:paperId`.
       6. [ ] todo — StudyPlan + Standings + Onboarding (bundle — phase wording says "as far as
          Phase-2 scope needs", partial wiring is sanctioned): StudyPlan wired to
          `useStudyPlan()`/post-mutation (`planRows`/`days`/`planCards` grid mock replaced by
          the real `sessions` list — implementer's call on layout, doesn't need to preserve the
          exact 7-day-grid visual if `StudyPlanDTO.sessions` doesn't map onto it 1:1, just needs
          to render real data honestly). Standings: wire `subjectRanks`/`paperCount`/
          `streakDays` (real); REMOVE the friends/school/global leaderboard tables entirely —
          `StandingsDTO` has no `boards` field (leaderboards are Phase 5/XP, no backend exists
          yet) — do not leave mock names on screen. Onboarding: wire the subject-confidence
          sliders to `OnboardingRequest.sliders` (`OnboardSliderInput{label,code,pct}`) +
          `gradeLevel`/`school`/`weeklyHours` on submit; the `onboardChips` multi-select reasons
          have no backing field on `OnboardingRequest` — drop them (don't submit fabricated
          data); document what's deferred vs P2.4-onward's full onboarding wizard.
       7. [ ] todo — `data.ts` cleanup pass: delete every export now fully superseded by a live
          fetch; KEEP `navGroups`, `crumbs` (or its replacement), `studentMeta`, and every
          Landing/Directions export (`landingHero`, `pillars`, `pillarsIntro`, `pricing`,
          `landingProofIntro`, `proof`, `directionsIntro`) — those two screens are marketing
          pages outside P2.7's scope, not touched. Run `tsc --noUnusedLocals`-equivalent (the
          existing `npm run typecheck`) to catch anything still importing a deleted export.
       8. [ ] todo — Gates (§6.3: typecheck/oxlint/build clean) + orchestrator-verify (re-run
          gates myself, don't trust subagent claims) + commit + STATE.md update per step above
          (already folded into steps 1-7, this line is the final full-suite confirmation) +
          `reports/phase-2/` note if anything is a documented deviation worth carrying to
          P2.10's DELIVERY.md section.
- [ ] todo — P2.8 Teacher surface wiring where Phase-2 data exists (delete teacher/data.ts
       incrementally): Grading, Review (low-confidence/integrity queue), MarkSchemes,
       Overview. Fill audit "partial" hollow fields honestly or mark deferred.
- [ ] todo — P2.9 PWA: manifest + service worker + installable + offline shell; camera
       capture UX; Lighthouse PWA checks pass. Gradio stays internal debug only.
- [ ] todo — P2.10 Acceptance: Playwright E2E — seeded student uploads a fixture scan and
       sees correct marks/grade/weaknesses on the dashboard; accuracy thresholds met;
       screenshots in reports/phase-2/screens/. §6 gates green; reports/phase-2/REPORT.md;
       merge feature→develop; push; open develop→main PR via gh (DO NOT MERGE); ntfy.

## Next action
**P2.1 DONE + VERIFIED (2026-08-03).** New: lemely/db/attempt_repo.py (AttemptRepository.
persist_correction → Attempt+QuestionResult+WeaknessRecord+ReviewQueueItem, 1 txn, review
threshold 0.90), lemely/db/upload_repo.py (StudentUploadRepository), lemely/web/upload_utils.py
(shared safe_upload_name/write_upload_capped; teacher.py dedup'd, monkeypatch seam preserved).
Rewired POST /api/student/correct (JSON {paperId}; pre-stream ownership 404; metadata→resolve
mark scheme (sibling pdf|corpus)→extract→grade(student_id=None)→persist→SSE marking_progress +
phase:complete + [DONE]; error/warning frames; publish_done in finally). New POST /api/student/
uploads. deps: get_attempt_repo/get_student_upload_repo (+reset_singletons). NO migration (all
columns from P1.3). Tests: test_attempt_repo.py (5 PG-integration), test_student_correct.py (7
real-PG through TestClient: SSE frames+persisted Attempt/QuestionResult/ReviewQueue+confidence;
unknown/malformed/foreign 404; teacher 403; upload status/file). Replaced obsolete stub test in
test_web_student.py with the new contract (422 body-less, 404 ownership) — honest evolution, full
path covered by real-PG test. GATES (orchestrator-verified): ruff/format/mypy(114)/lint-imports
clean; 561 passed / 2 skipped (live-only, no keys) / 12 subtests; cov 85.10%.
CARRIED DEBT: cov 85.44%→85.10% (−0.34pp; above 70% hard gate but §6 gate-2 (no drop vs develop)
bites at the P2.10 develop merge). Restore before P2.10 by covering: upload_repo.set_status no-op,
mid-stream metadata-detection-failure branch (key present), resolve_mark_scheme corpus fallback,
upload_utils 413 branch. Non-blocking for P2.2.

**P2.2 DONE + VERIFIED (2026-08-04).** See checklist entry above for full detail.

**P2.3 CLOSED 2026-08-04 (with a documented gate deviation).** Step 8 (deterministic
marking-quality fix) done — see checklist entry above and **D2.4** in DECISIONS.md for full
detail, including the 3-iteration design history (two broken versions caught by live harness
re-runs, not inspection). Result: `mark_accuracy` 80.9%→83.8%, exactly 2 fixes / 0 regressions
vs the D2.3 baseline across all 68 questions. `REVIEW_CONFIDENCE_THRESHOLD` stays at 0.90
(unchanged from D2.2/D2.3). **§4 accuracy gate is NOT met (83.8% < 95%)** — closed anyway per
**D2.5**: threshold tuning (D2.3) and the deterministic fix (D2.4) are both exhausted as
approaches; the remaining gap needs free-form algebraic method verification (0625 `5b`-class
errors), out of scope for this pass. NOT silently marked passing — this must be carried into
`DELIVERY.md` at P2.10 as an explicit, honest limitation with the measured numbers at that
time. `tests/golden/results/2026-08-04-9a7f4c8.json` (gitignored) is the final result of this
work; regenerating without further code changes is a pure cache hit, effectively free.

**P2.4 DONE + VERIFIED (2026-08-04, commit d31a5ba).** Resumed on a dirty tree carrying the
prior session's un-committed P2.4 implementer output (matched the recorded PLAN exactly —
verified before trusting, not just assumed). New: `apply_integrity_checks` (lemely/io/
integrity.py) wired into `grade_paper` (web/services/grading.py) via a new optional
`integrity_settings` param, called from student.py's `run()` with `settings.integrity`.
`CorrectedQuestion` gained `plagiarism_flagged`/`ai_detection_flagged: bool = False`;
flagged questions get `review_reason` appended + `needs_teacher_review=True`, marks
untouched, result rebuilt via `CorrectionResult(...)` (not model_copy) so
`calculate_totals` reruns. `attempt_repo.persist_correction` now zips `question_results`
with `correction.questions` to add independent `ReviewQueueItem` rows per flag reason
(plagiarism_flag / ai_detection_flag), additive alongside the existing low_confidence
check — a question can get multiple rows. `web/schemas.py` DTO surfaces
`plagiarismFlagged`/`aiDetectionFlagged`. AI-detection stays opt-in
(`IntegritySettings.ai_detection_enabled` default False) — zero extra Gemini calls unless
explicitly enabled. GATES (orchestrator-verified, all from a clean run): ruff/format/mypy
(115 files)/lint-imports clean; pytest exit 0, 0 FAILED/ERROR, cov 82.04% (local — DB-
integration tests still skip, see environment note below, not a regression); pre-commit
--all-files clean. Tests added: 6 in test_integrity.py (apply_integrity_checks unit,
incl. AI-detection-disabled never calls Gemini), 1 PG-integration in test_attempt_repo.py
(3 independent review-queue rows for one doubly-flagged question), test_student_correct.py
updated for the now-real plagiarism flag on the fixture's verbatim MCQ answer, 2 in
test_web_app.py (DTO round-trip). Frontend/teacher-queue consumption is P2.6/P2.8 by design
(out of scope here, DTO fields are the P2.4 finish line per phase-checklist wording).
NOTE: `scripts/check.sh` (mandated by MISSION §Phase-0 and referenced by MISSION §8b as
"the single quality-gate command") does NOT exist on disk — Phase 0 was marked done without
creating it; gates were run as individual commands this session instead. Not blocking P2.4,
but worth creating opportunistically (cheap, ~10 lines) before it causes repeated
individual-command overhead in future sessions.

**P2.5 DONE + VERIFIED (2026-08-04).** Resumed on a dirty tree carrying a prior session's
PARTIAL P2.5 implementer output — steps 1-3 of the recorded PLAN (`StorageSettings`,
`lemely/io/storage.py` with `StorageBackend`/`HttpStorageBackend`, `tests/storage_fakes.py`
with `FakeStorageBackend`, `get_storage_backend` singleton in `web/deps.py`,
`check_upload_cap` extracted in `upload_utils.py`) matched the PLAN exactly and were sound;
steps 4-6 (router wiring, tests) were NOT started. Completed the unit: wired
`student_upload` to `storage_backend.upload` (object key
`uploads/{user_id}/{paperId}/{filename}`, `storage_path` repurposed to hold that key) and
`student_correct`'s `run()` closure to `storage_backend.download` into a
`tempfile.TemporaryDirectory`. Two deliberate deviations from the literal PLAN text, both
recorded in **D2.6**'s completion note: (1) also download an optional sibling
`mark_scheme.pdf` object (the PLAN only mentioned the scan; skipping the sibling would have
silently regressed the existing student-supplied-mark-scheme feature) — added
`StorageObjectNotFoundError` (shared by `HttpStorageBackend` on HTTP 404 and
`FakeStorageBackend`, moved out of test-local scope into `lemely/io/storage.py`) to
distinguish "no sibling" from a real Storage failure; (2) `tests/test_storage_live.py` is a
live-skip integration test only (mirroring `test_auth_live.py`'s skip condition), not a
`httpx.MockTransport` hermetic test — confirmed `HttpGoTrueBackend` itself has zero hermetic
tests, only live-skip coverage, so matched the actual precedent instead of the PLAN's
unverified assumption. Also fixed `tests/test_student_correct.py`'s `client` fixture to share
one `FakeStorageBackend()` instance across the override lambda (a fresh instance per call
would silently break the upload→correct flow across requests — caught before running);
rewrote `test_upload_sets_status_and_writes_file` against the fake store instead of a local
disk path; added `test_upload_over_size_cap_is_413` for the new `check_upload_cap` call site.
GATES (orchestrator-verified): `ruff check`/`ruff format --check`/`mypy lemely`/`lint-imports`
all clean; full pytest run exit 0, 0 failed/errored, 49 skipped (all Postgres/Supabase-live,
env-gated, same as every session this stack has been down), coverage gate (70%) passed at
81.45%. Committing on `feature/phase-2-core-loop`.
Separate environment note (not blocking, needs a session with shell/root access, UNCHANGED
this session — sudo unavailable in this sandbox too): local Supabase stack is down and won't
start — `supabase/.temp/start-secrets/supabase_db_Lemely/` contains root-owned directories
from a prior crashed container that a non-privileged shell cannot remove (`rm -rf` fails
EACCES even recursively, since deleting requires write access to those root-owned dirs, not
just their parent). Fix: as a user with root/docker-group cleanup rights, `sudo rm -rf
supabase/.temp/start-secrets/` then `supabase start`. Until then, Postgres-backed integration
tests keep skipping locally (CI is unaffected — it provisions its own Postgres service).

**P2.6 DONE + VERIFIED (2026-08-04).** See checklist entry above for full detail. Frontend
auth/session/query-client foundation built (storage.ts, authTypes.ts, AuthContext, RequireAuth,
queryClient, a minimal Login screen, api.ts bearer-header wiring, App.tsx/main.tsx routing).
No screen wired to real data yet — student/data.ts and teacher/data.ts are untouched by design
(P2.7/P2.8). typecheck/lint/build all clean (orchestrator-reran, not just trusted); Vite-proxy
routing independently confirmed reaching FastAPI's real auth handlers (otp/request 200,
malformed login 422, well-formed login 401 on the already-documented down Supabase dependency).
Confirmed again this session: local Supabase stack still down, same root-owned-dir issue, sudo
still unavailable in this sandbox — unchanged environment note, not re-litigated further.
Next: P2.7 Student surface on real data (screen-by-screen, delete student/data.ts).

## Superseded — P2.1 scope (kept for provenance)
Scope COMPLETE (2026-08-03). Design locked:
- NEW lemely/db/attempt_repo.py: AttemptRepository.persist_correction(user_id, AccuracyReport,
  upload_id) → Attempt (+confidence_band/predicted_grade/boundary_source/needs_review) +
  QuestionResult rows (matched_point_ids = method-mark JSONB) + WeaknessRecord rows +
  ReviewQueueItem rows for low-confidence (<0.90) / flagged questions. One txn. Reuses
  parse_user_id/month_to_enum (promote to public in history_repo).
- NEW lemely/web/upload_utils.py: shared safe_upload_name/write_upload_capped (dedupe teacher.py;
  keep teacher._MAX_UPLOAD_BYTES call-time cap so its monkeypatch test stays green).
- NEW student uploads repo + POST /api/student/uploads (student-only): stores scan (+optional
  mark_scheme.pdf sibling) under output_dir/uploads/{uid}/{paperId}; persists Upload row;
  returns {paperId}=upload.id.
- REWIRE POST /api/student/correct: JSON {paperId}; owner-check Upload (404 if foreign) BEFORE
  streaming; run(): metadata detect → resolve_mark_scheme (sibling pdf via ChainedMarkScheme
  parser, else stored corpus by metadata) → extract_answers → grade_paper(student_id=None) →
  attempt_repo.persist_correction → Upload=complete → SSE frames + [DONE]. Pipeline seams
  (ScanMetadataExtractor, extract_answers, resolve_mark_scheme) module-level for monkeypatch.
- get_attempt_repo + get_student_upload_repo singletons in deps.py (+reset_singletons).
- NO new migration (all columns exist from P1.3). Gemini MOCKED in tests.
- Tests: test_attempt_repo.py (PG-integration, throwaway DB) + test_student_correct.py
  (real-PG through TestClient: SSE frames + persisted Attempt/QuestionResult/ReviewQueue +
  confidence; ownership/unknown 404) + upload endpoint tests (role 403, 413 cap).
Delegated code+tests to implementer(opus); orchestrator verifies §6 gates then commits.

## Superseded — Phase-1 next action (kept for provenance)
**PHASE 1 COMPLETE** (2026-08-01) — merged to develop, pushed, develop→main PR opened (DO NOT MERGE),
ntfy sent. **Next: Phase 2** (branch `feature/phase-2-core-loop` from develop). Per MISSION §4 Phase 2:
wire the SPA to the API (resurrect web/lib/api.ts + react-query, delete student/data.ts + teacher/data.ts
mocks screen-by-screen), real SSE pipeline for CorrectPaper, PWA camera→multi-page-PDF→Supabase Storage
upload path, full metadata→mark-scheme→extraction→marking→confidence→grade/boundary→weakness pipeline,
grade-boundary ingestion (0580/0606/0625 per-variant), accuracy harness w/ golden fixtures (≥99% MCQ,
≥95% mark-level, 100% disagreements below review threshold), student dashboard on real data, plagiarism/
AI-detection advisory flags, PWA installable (Lighthouse). START by reading LEMELY_AUDIT.md's web section
+ web/lib/api.ts + web/**/data.ts to scope the mock→real migration; use a workflow for the screen-by-screen
sweep and for boundary scraping/fixture generation (keep each workflow < ~30 agents, checkpoint to disk).

### (carried, non-blocking) Deferred Phase-1 follow-ups
- (D1.9) Migrate CLI + Gradio history to the DB (or retire Gradio), THEN delete lemely/io/history_store.py
  + tests/test_history_store.py. Parity already proven; low-risk. Do opportunistically.
- (D1.6) Teacher per-tenant ownership (own-classes-only) lands with the DB class model in Phase 2/3.
- GoTrue is not run in CI (live auth/seat tests skip there); hermetic tests cover the logic.

## Superseded — Phase-1 acceptance detail (kept for provenance)
Device/session registry DONE (P1.11/D1.11 — ready to commit). Next non-done task: the FINAL
Phase-1 task — **Phase-1 acceptance**:
  1. E2E auth tests for all 5 roles (student/parent/teacher/school_admin/platform_admin): a full
     signup/login (or OTP for parent) → authed request → correct RBAC outcome path. Some of this
     is covered by test_authz_matrix.py + test_auth_router.py already; audit for the gap (esp. a
     real end-to-end parent OTP flow and a school_admin seat-invited student logging in) and fill it.
  2. Adversarial security review of the WHOLE auth surface via the `reviewer` subagent (the D1.7
     pass was only ONE partial review; the acceptance sweep is still owed). Give it: lemely/auth/**,
     lemely/web/deps.py, lemely/web/routers/{auth,student,teacher,school}.py, lemely/db/{seat_repo,
     device_repo,history_repo}.py. Verify findings yourself; address them.
  3. [DONE this session, commit 9b287a9] "Every route has an authz test" — authz matrix is now
     exhaustive: added /student/correct, student-POST wrong-role→403, and the two missing teacher
     GETs. Teacher/school routers are router-level gated so their POSTs are covered by the guard
     proof. If the adversarial review (item 2) flags a specific untested route, add it then.
  4. [DONE this session, commit 35aec2a] CI now runs the real-DB tests: postgres:16 service on
     port 54322 + `alembic upgrade head` added to .github/workflows/ci.yml test job. (GoTrue is
     still not run in CI, so test_auth_live.py stays skipped — that's fine; hermetic tests cover it.)
  5. Quality gates (§6) green; write reports/phase-1/REPORT.md; merge feature→develop; push;
     open develop→main PR via `gh` (DO NOT MERGE it); ntfy phase-complete.
The deferred CLI/Gradio history→DB deletion (D1.9) is NOT blocking; do it opportunistically or at
Gradio retirement. Revisit BUILD/BLOCKERS.md (none currently).

CI HEADS-UP (unchanged): DB/auth integration tests skip when Postgres unreachable, so CI is
green today; before the acceptance task add a Postgres services block + `alembic upgrade head`
to .github/workflows/ci.yml so real-DB auth/authz tests actually run in CI.

HEADS-UP for CI: the new DB integration tests (tests/test_db_schema.py) skip when Postgres
is unreachable, so CI stays green today. Before the auth E2E task, CI (.github/workflows/
ci.yml) needs a Postgres `services:` block (or a Supabase step) + `alembic upgrade head`,
otherwise the real-DB auth/authz tests will silently skip in CI.

## Session handoff notes
- 2026-07-31 (Device/session registry DONE, P1.11/D1.11): resumed on a dirty tree carrying a
  prior session's PARTIAL device-registry work — modified auth/service.py (DeviceContext + wiring),
  auth/tokens.py (session_id claim), db/models/users.py (client_device_id column + index), an
  untracked db/device_repo.py (complete, well-crafted DeviceRegistry), and D1.11 recorded in
  DECISIONS. Verified before trusting: the WIP was INCOMPLETE — no migration 0003 (model had the
  new column but no migration → DB drift), get_auth_context had NO liveness check (the whole point
  of the feature was unwired), the router passed no DeviceContext, and there were ZERO tests.
  Completed the unit: wrote migration 0003_device_client_id (additive; applied live; `alembic check`
  drift-free); added get_device_registry singleton + wired it into get_auth_service AND the
  get_auth_context liveness check (sid-gated, offline path preserved) + reset_singletons; added
  optional deviceId to the 3 auth DTOs and User-Agent extraction in the router → DeviceContext;
  exported DeviceContext; wrote tests/test_device_repo.py (10 PG-integration) + 3 hermetic liveness
  tests in test_auth_dependency.py. Gates: 522 passed / 1 skipped (live auth, no keys) / 12 subtests
  / 85.41% cov (>85.00% prior); ruff/format/mypy/lint-imports clean. Supabase stack UP; migrations
  at 0003 head. Committing on feature/phase-1-db-auth-tenancy. Next: Phase-1 acceptance (final task).
- 2026-07-31 (Seat model DONE, P1.10/D1.10): resumed on a dirty tree carrying a prior
  session's PARTIAL, UNRUN seat work — three untracked files (lemely/db/seat_repo.py,
  lemely/web/routers/school.py, lemely/web/schemas_school.py). Verified before trusting:
  the WIP was INCOMPLETE — the router imported `get_seat_service` from deps.py which did
  NOT exist, the school router was NOT registered in app.py, and there were NO tests.
  The service/router/DTO code itself was sound and matched the P1.3 models. Completed the
  unit: added `AuthServiceStudentCreator` + `get_seat_service` (+ reset_singletons) to
  web/deps.py; registered school.router in app.py; added schemas_school to the mypy
  disallow-any-explicit override list (same false-positive class as the other DTO modules).
  Wrote tests/test_seat_repo.py (12 PG-integration tests: quota boundary + no-orphaned-account,
  ownership on invite/usage/list/revoke, revoke frees+keeps-account+idempotent, unknown-seat
  404, personal-subscription coexistence, non-UUID rejection) + 6 /api/school authz cases in
  test_authz_matrix.py. NOTE this FastAPI version registers included routers lazily as
  `_IncludedRouter`, so `app.routes` inspection shows no seat paths — TestClient requests
  (401/403) are the real proof. Gates: 509 passed / 1 skipped (live auth, no keys) / 12
  subtests / 85.00% cov (>84.92% prior); ruff/format/mypy/lint-imports clean. Supabase stack
  UP. Committing on feature/phase-1-db-auth-tenancy. Next: device/session registry (max 3).
- 2026-07-31 (HistoryStore→Postgres web migration DONE, same session as D1.7): after the D1.7
  hardening, executed the HistoryStore→Postgres task in two committed increments against LIVE
  Postgres (supabase stack up). Increment A (26b0b0d): lemely/db/history_repo.py DbHistoryStore
  (interface-preserving) + migrate_json_history() + 6 PG parity tests — parity proven via
  model_dump equality vs the JSON store. Increment B (5cabb58): get_history_store → DB store;
  extracted HistoryStoreProtocol + now_iso into core/history.py; student/teacher routers + web
  grading service annotate the Protocol. KEY DEVIATION recorded as D1.9: did NOT delete
  io/history_store.py — it is also used by app/cli.py + app/gradio_* (local, unauthenticated,
  no-UUID tools); deleting it would force Postgres on them, out of the task's web-routers scope.
  Web migrated; JSON store retained for CLI/Gradio; deletion deferred to an explicit follow-up
  todo. Web tests untouched (they override get_history_store with a JSON store double at runtime,
  so the web suite never hits PG). 488 passed / 1 skipped (live auth, no keys) / 12 subtests /
  84.92% cov; ruff/format/mypy/lint-imports clean. STATE task marked done. Next: Seat model.
- 2026-07-31 (D1.7 hardening committed on resume): resumed on a dirty tree carrying a
  prior session's *incomplete, unrun* adversarial-security fixes (otp.py resend cooldown,
  history_store.py _safe_key guard, auth.py signup-role restriction, config/deps wiring).
  Verified before trusting: the OtpRateLimitError raise had NO caller handling it (would
  500, not 429) and the source change silently BROKE two existing tests
  (test_signup_endpoint signed up as teacher; test_reissue_resets reissued same-instant).
  Completed the unit: router maps OtpRateLimitError→429; added cooldown tests, signup
  elevated-role 403 tests (3 roles), history unsafe-key rejection tests (7 hostile keys);
  fixed the 2 broken tests; recorded D1.7 in DECISIONS.md. 482 passed / 1 skipped (live
  auth, no keys) / 12 subtests / 84.77% cov; ruff/format/mypy/lint-imports clean. Committed
  (2596ddf) on feature/phase-1-db-auth-tenancy. NOTE the full adversarial reviewer pass over
  the whole auth surface is STILL due at Phase-1 acceptance (this was one prior partial pass).
  Next: HistoryStore→Postgres migration (unchanged).
- 2026-07-31 (P1.5 + P1.6 DONE, same session): after P1.4, implemented the JWT bearer
  dependency (P1.5) then RBAC (P1.6). deps.py get_auth_context validates HS256 tokens →
  AuthContext or 401; require_role(*roles) adds 403 role-gating. Student routes gated to
  Role.student (self-owned via auth.user_id); teacher router gated at router level to
  {teacher, school_admin, platform_admin}. Killed both IDORs (removed studentId from the two
  request DTOs; identity = auth.user_id). Existing web tests override get_auth_context so they
  stayed green after the DTO changes. New: test_auth_dependency.py (8), test_authz_matrix.py
  (31). Full suite 468 passed / 12 subtests / 86% cov; all static gates clean. Two focused
  commits (P1.5, P1.6). Adversarial reviewer pass over the auth surface is deferred to the
  Phase-1 acceptance task (still enforce it there). Next: HistoryStore→Postgres migration.
- 2026-07-31 (P1.4 auth DONE): resumed on a dirty tree carrying the full P1.4 auth work
  (lemely/auth/ + router + tests) plus a recorded D1.5 decision. Verified before trusting:
  static gates clean, hermetic auth tests green — BUT the live test (test_auth_live.py) had
  been SKIPPING (no keys in env). Ran it with the `supabase status` service-role/anon keys
  against the running stack and it FAILED: signup returned GoTrue's ES256 token, which the
  HS256-only decode_token rejects. D1.5 (backend re-mints all tokens HS256) was recorded but
  NOT implemented — signup/login still forwarded `token.access_token`. Implemented D1.5:
  generalised tokens.mint_otp_token → mint_access_token(provider=...); signup/login now mint
  self-signed HS256 via _mint_email_token(provider="email"); GoTrue token discarded. Updated
  the 2 hermetic tests that asserted the old `gotrue-access-` prefix to decode+validate claims
  (they had masked the gap by never decoding). Gitignored BUILD/.supervisor_notify_state.
  Full suite LIVE (keys set): 429 passed / 12 subtests / 0 skip / 85.80% cov (> 84.92% prior);
  ruff+mypy+lint-imports clean. Supabase stack UP; migrations at 0002_core_schema head.
  Committing on feature/phase-1-db-auth-tenancy. Next: JWT validation middleware (P1.5).
- 2026-07-30 (P1.4 auth START): resumed clean tree (ahead 2, unpushed). No auth code on
  disk yet — only D1.4 decision recorded. Supabase stack UP (GoTrue = supabase_auth_Lemely).
  Local keys via `supabase status`: SERVICE_ROLE_KEY + ANON_KEY are the JWT-form keys GoTrue
  wants for admin (Bearer) + apikey; JWT_SECRET matches SupabaseSettings default. Dispatched
  implementer(opus) to build lemely/auth/ per D1.4 + FastAPI /api/auth router + hermetic
  tests + live-skip integration test. Verifying gates before commit.
- 2026-07-30 (P1.3 schema DONE): resumed on a dirty tree that was the WIP schema (8 model
  modules + migration 0002). It did NOT actually work — models were TYPE_CHECKING-only for
  uuid/datetime/date, so SQLAlchemy could not resolve Mapped[...] at runtime (nothing had
  ever loaded them). Fixed the imports, cast enum server_defaults (D1.3) for drift-free
  autogenerate, added tests/test_db_schema.py, verified live against local Supabase PG.
  Committed on feature/phase-1-db-auth-tenancy. Supabase stack is UP (docker). 402 passed /
  84.92% cov. Gemini spend still $0.00. Next: Supabase Auth (GoTrue) + JWT/RBAC.
- 2026-07-30 (Phase 0 COMPLETE): all 8 tasks + doctor-reachability acceptance done.
  On `develop` (Phase 0 merged, pushed). PR #3 develop→main OPEN — DO NOT MERGE.
  Gates green: 395 passed / 84.56% cov; ruff/mypy/lint-imports clean; web ok.
  Gemini live spend $0.00 (all mocked). Next: Phase 1 (branch from develop).
  Reminder: run pytest with dev `.env`/`lemely.toml` present is fine now — conftest
  isolates them. Real PDFs: Sources/Physics/MarkingSchemes/ (4). Signed commits (-S),
  pre-commit before each commit, never merge the develop→main PR.
- 2026-07-30: Started Phase 0. Created `develop` + `feature/phase-0-foundation-repair`
  branches off main (e091c81). Verified suite: 306 passed / 2 skipped / 82.39% cov
  ONLY when local dev `.env` + `lemely.toml` are absent. Those files carry a real
  GEMINI key that makes 3 "without-key" tests fail locally (test_cli_doctor,
  test_runtime_config defaults, test_web_student plan_post 503). CI is clean (no
  .env/toml), so this is a local-only artifact — DO NOT "fix" those tests.
- Reverted trivial EOF-newline diffs on 2 tracked Sources/*.json; gitignored BUILD/logs/.
