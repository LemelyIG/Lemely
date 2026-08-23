# Lemely — Delivery Document

**Status of this document:** it is the final record of what this build produced,
what it did not, and what a reader must not assume works. Every figure in it is
measured off committed artifacts rather than carried forward by hand — this
build was burned several times by hand-copied numbers that nothing regenerates,
and §6 says where each number comes from so it can be re-derived.

**The one thing to read if you read nothing else:** §5, *Honest limitations*.
It carries every limitation recorded in Phases 2 through 5, whether or not
Phase 6 fixed it. A feature listed as `Delivered` in §3 may still appear there
with a constraint on what "delivered" means.

---

## 1. What Lemely is

A SaaS platform for IGCSE/O-Level/AS/A-Level students, their parents and their
teachers, scoped for launch in Egypt (English-only UI). A student photographs or
uploads an attempted past paper; Lemely extracts the answers, marks them against
the official marking scheme with method-mark awareness, and returns per-question
marks, a letter and numerical grade, a predicted grade after boundaries,
mistakes, weakness topics and performance trends. Around that core loop sit
student/teacher/parent dashboards, AI content generation, adaptive study plans
and a Duolingo-style engagement layer.

**Board scope for this build:** CAIE only — Mathematics 0580, Additional
Mathematics 0606, Physics 0625. The architecture is board-agnostic; Edexcel and
Oxford AQA would arrive as data plus parser plugins.

**Explicitly out of scope, by decision, not by omission** (MISSION §1 and §9):
payment processing (the subscription/seat data model and plan gating exist;
activation is a manual platform-admin toggle), the igclub calculator, Arabic UI,
a real SMS provider, and live cloud hosting.

## 2. Phase reports

Each phase has its own report with the command outputs, screenshots and test
counts that back it. This document links rather than restates them.

| Phase | Scope | Report |
| --- | --- | --- |
| 0 | Foundation repair | [`reports/phase-0/REPORT.md`](reports/phase-0/REPORT.md) |
| 1 | Database, auth, tenancy | [`reports/phase-1/REPORT.md`](reports/phase-1/REPORT.md) |
| 2 | The core correction loop | [`reports/phase-2/REPORT.md`](reports/phase-2/REPORT.md) |
| 2.5 | Design system + frontend quality foundation | [`reports/phase-2.5/REPORT.md`](reports/phase-2.5/REPORT.md) |
| 3 | Teacher + parent surfaces | [`reports/phase-3/REPORT.md`](reports/phase-3/REPORT.md) |
| 4 | Content generation + study plans | [`reports/phase-4/REPORT.md`](reports/phase-4/REPORT.md) |
| 5 | Engagement layer | [`reports/phase-5/REPORT.md`](reports/phase-5/REPORT.md) |
| 6 | Hardening + ship | [`reports/phase-6/REPORT.md`](reports/phase-6/REPORT.md) |

Design and product truth live in [`docs/LEMELY_UI_SPEC.md`](docs/LEMELY_UI_SPEC.md),
[`DESIGN.md`](DESIGN.md) and [`PRODUCT.md`](PRODUCT.md); decisions in
[`BUILD/DECISIONS.md`](BUILD/DECISIONS.md); deployment in
[`docs/deployment.md`](docs/deployment.md).

## 3. Feature inventory

Every item in MISSION §9's inventory appears below exactly once, with the files
that implement it and the tests that prove it. `Delivered (limited)` means the
feature works but with a stated constraint — the constraint is in the feature
cell, and the fuller version is in §5.

| Feature | Phase | Status | Key implementation files | Proving tests |
| --- | --- | --- | --- | --- |
| **Correction** | | | | |
| In-app PDF scanner (never live-tested — no camera in the build sandbox) | 2 | Delivered (limited) | `web/src/components/CameraCapture.tsx` | `web/e2e/screenshots.spec.ts` |
| File upload | 2 | Delivered | `lemely/io/storage.py`, `lemely/web/routers/student.py` | `tests/test_storage.py`, `tests/test_web_student.py` |
| Metadata detection | 2 | Delivered | `lemely/io/scan_metadata.py`, `lemely/io/metadata.py` | `tests/test_scan_metadata.py` |
| Mark-scheme fetch / parse / store (32 of 72 papers parse for 0625) | 2 | Delivered (limited) | `lemely/io/mark_schemes.py`, `lemely/io/det/` | `tests/test_mark_schemes.py`, `tests/test_parsers_det.py` |
| Method-mark marking + confidence (83.8% agreement vs a ≥95% target, historical — §5.1) | 2 | Delivered (limited) | `lemely/core/correction.py`, `lemely/io/correction_ai.py` | `tests/test_correction.py`, `tests/test_accuracy_synth.py`, `tests/test_accuracy_real_papers.py` |
| Plagiarism flag (advisory signal, never modifies a mark) | 2 | Delivered | `lemely/core/plagiarism.py`, `lemely/io/integrity.py` | `tests/test_integrity.py` |
| AI-detection flag (advisory signal, never modifies a mark) | 2 | Delivered | `lemely/io/integrity.py`, `lemely/core/integrity_schemas.py` | `tests/test_integrity.py` |
| Letter / numerical / total grade | 2 | Delivered | `lemely/core/analytics.py` (`grade_for_percentage`) | `tests/test_grade_boundaries.py` |
| Predicted grade after boundary | 2 | Delivered | `lemely/core/analytics.py` (`predict_grade`), `lemely/io/grade_boundaries.py` | `tests/test_grade_boundaries.py` |
| Mistakes + weakness identification | 2 | Delivered | `lemely/core/analytics.py`, `lemely/core/topics.py` | `tests/test_topics.py`, `tests/test_compare_performance.py` |
| Performance vs past papers | 2 | Delivered | `lemely/core/history.py`, `lemely/core/analytics.py` | `tests/test_compare_performance.py` |
| Custom exam + custom mark-scheme correction (via teacher override + quiz marking) | 3 | Delivered | `lemely/db/review_repo.py`, `lemely/web/routers/review.py` | `tests/test_review_repo.py`, `tests/test_web_review.py` |
| **Student surfaces** | | | | |
| Overall performance | 2 | Delivered | `lemely/web/routers/student.py`, `web/src/portals/student/screens/Overview.tsx` | `tests/test_web_student.py`, `web/e2e/student-journey.spec.ts` |
| Per-subject performance | 2 | Delivered | `web/src/portals/student/screens/Subject.tsx` | `web/e2e/student-journey.spec.ts` |
| Single-subject overview (per-paper performance, boundaries, final grade) | 2 | Delivered | `lemely/web/routers/student.py`, `web/src/portals/student/screens/PaperResult.tsx` | `tests/test_student_correct.py`, `web/e2e/correct-paper.spec.ts` |
| Announcements calendar (ships with no CAIE dates — §5.4) | 5 | Delivered (limited) | `lemely/db/announcement_repo.py`, `lemely/web/routers/exam_calendar.py` | `tests/test_web_announcements_student.py`, `tests/test_exam_calendar_repo.py` |
| Push notifications (no VAPID keys on this machine — §5.3) | 5 | Delivered (limited) | `lemely/web/push.py`, `lemely/db/notification_repo.py` | `tests/test_push_transport.py`, `tests/test_web_notifications.py` |
| **Teacher surfaces** | | | | |
| At-risk flagging (rule 3, inactivity, cannot fire — §5.3) | 3 | Delivered (limited) | `lemely/core/at_risk.py`, `lemely/db/at_risk_repo.py` | `tests/test_at_risk.py`, `web/e2e/at-risk-flags.spec.ts` |
| Overall / individual performance + weakness points | 3 | Delivered | `lemely/core/class_analytics.py`, `lemely/web/routers/teacher.py` | `tests/test_class_analytics.py`, `tests/test_web_teacher.py` |
| Academic statistics | 3 | Delivered | `lemely/core/class_analytics.py` | `tests/test_class_analytics.py` |
| Review queue with override-and-annotate | 3 | Delivered | `lemely/db/review_repo.py`, `lemely/web/routers/review.py` | `tests/test_review_repo.py`, `tests/test_web_review.py` |
| Quiz creation with difficulty / material / pool controls | 3 | Delivered | `lemely/io/teacher_quiz.py`, `lemely/db/quiz_repo.py`, `lemely/web/routers/quiz.py` | `tests/test_teacher_quiz.py`, `tests/test_quiz_repo.py`, `tests/test_web_quiz.py` |
| **Parent surfaces** | | | | |
| Child performance + weaknesses (read-only) | 3 | Delivered | `lemely/db/parent_repo.py`, `lemely/web/routers/parent.py` | `tests/test_parent_repo.py`, `web/e2e/parent-journey.spec.ts` |
| Phone login (mock SMS provider, logs the OTP) | 3 | Delivered | `lemely/auth/service.py` | `tests/test_otp.py`, `tests/test_web_parent.py` |
| **Content generation** | | | | |
| Classified practice targeting weaknesses (0580 and 0606 have no questions — §5.2) | 4 | Delivered (limited) | `lemely/db/practice_repo.py`, `lemely/core/topics.py`, `lemely/web/routers/practice.py` | `tests/test_practice_repo.py`, `tests/test_web_practice.py`, `web/e2e/phase4-practice.spec.ts` |
| Flashcards + spaced repetition | 4 | Delivered | `lemely/io/flashcard_generation.py`, `lemely/core/spaced_repetition.py` | `tests/test_flashcard_repo.py`, `tests/test_spaced_repetition.py` |
| Quiz generation | 3/4 | Delivered | `lemely/io/question_generation.py`, `lemely/core/generation.py` | `tests/test_question_generation.py` |
| Question-stem extraction (closed the empty question bank, D4.1) | 4 | Delivered | `lemely/io/question_papers.py`, `lemely/core/question_papers.py` | `tests/test_question_papers_io.py`, `tests/test_question_bank_repo.py` |
| **Study plan** | | | | |
| Placement test (~15 min, real past-paper questions; 0580 and 0606 have no questions, so it refuses for two of three subjects — §5.2) | 4 | Delivered (limited) | `lemely/core/placement.py`, `lemely/db/placement_repo.py` | `tests/test_placement_assembly.py`, `tests/test_web_placement.py` |
| Onboarding questionnaire | 4 | Delivered | `lemely/db/student_profile_repo.py`, `web/src/portals/student/screens/Onboarding.tsx` | `tests/test_student_profile_repo.py`, `web/tests/unit/onboarding.test.ts` |
| Data-collection fields (subjects, session, school, target grades) | 4 | Delivered | `lemely/db/student_profile_repo.py` (migration 0009) | `tests/test_student_profile_repo.py` |
| Adaptive study plan (week-scoped, concrete sessions; regeneration is student-triggered, not timed — §5.3) | 4 | Delivered | `lemely/core/study_plan.py`, `lemely/db/study_plan_repo.py` | `tests/test_study_plan.py`, `tests/test_web_study_plan.py` |
| **Engagement** | | | | |
| XP + streaks with anti-farming caps | 5 | Delivered | `lemely/db/xp_repo.py`, `lemely/web/xp_awards.py` | `tests/test_xp_repo.py`, `tests/test_web_xp_awards.py`, `tests/test_concurrency.py` |
| Leaderboards (friends / class / school / global / per-subject / total, weekly XP, opt-out) | 5 | Delivered | `lemely/db/leaderboard_repo.py`, `lemely/web/routers/leaderboard.py` | `tests/test_leaderboard_repo.py`, `tests/test_web_leaderboard.py`, `web/e2e/engagement.spec.ts` |
| Announcements (teacher → class, school_admin → school) | 3/5 | Delivered | `lemely/db/announcement_repo.py`, `lemely/web/routers/announcements.py` | `tests/test_announcement_repo.py`, `tests/test_web_announcements.py` |
| **Accounts + platform** | | | | |
| Personalized accounts (5 roles) | 1 | Delivered | `lemely/auth/service.py`, `lemely/web/routers/auth.py` | `tests/test_auth_service.py`, `tests/test_auth_e2e_roles.py` |
| RBAC on every route | 1 | Delivered | `lemely/web/deps.py` | `tests/test_authz_matrix_complete.py`, `tests/test_authz_matrix.py`, `web/e2e/rbac.spec.ts` |
| Subscriptions / seats / manual activation (no payment processing, by scope) | 1 | Delivered | `lemely/db/seat_repo.py` | `tests/test_seat_repo.py` |
| 3-device limit + sharing friction | 1/5 | Delivered | `lemely/db/device_repo.py`, `web/src/portals/settings/DeviceSettings.tsx` | `tests/test_device_repo.py`, `tests/test_web_devices.py`, `web/tests/unit/devices.test.ts` |
| Design system + component library (C-1..C-13) | 2.5 | Delivered | `web/src/index.css`, `docs/COMPONENT_CATALOGUE.md` | `web/tests/unit/design-tokens.test.ts` |
| Docker Compose one-command stack + deployment docs | 6 | Delivered | `docker-compose.yml`, `Dockerfile`, `web/Dockerfile`, `docs/deployment.md` | `none found` — verified by a manual `make up` bring-up (P6.4), not by an automated test |

## 4. Deferred, and why

These were named as out of scope at the start of the build and were not built.
They are listed so that "absent" is never mistaken for "missed".

| Deferred | Why |
| --- | --- |
| Payments (Paymob / Fawry) | Out of scope by MISSION §1. The subscription and seat data model exists and plan gating is enforced; account activation is a manual platform-admin toggle. |
| igclub calculator | Out of scope for v1. |
| Edexcel / Oxford AQA | Architecture is board-agnostic; these arrive as data plus parser plugins, not as a rewrite. |
| Arabic UI | v1 is English-only. |
| Real SMS provider | Parent phone-OTP ships behind a provider abstraction with a mock provider that logs the OTP. One config switch changes it. |
| Cloud hosting | The definition of done was a one-command local stack plus written deployment docs. No live hosting was in scope. |

## 5. Honest limitations

Carried forward in full from every phase, whether or not a later phase fixed
them. Struck-through entries were closed and are kept so the record stays
readable rather than quietly rewritten.

### 5.1 Marking accuracy — the most important limitation in this document

- **The synthetic accuracy gate is NOT met (D2.5).** Mark-level agreement is
  **83.8% against a ≥95% target** (historical — 10-fixture corpus, n=68 rows;
  see BUILD/DECISIONS.md DA8 for the current, honest baseline: 90.1% raw
  n=71 / 77.4% DA6-collapsed n=31, `run_id=run-ef443fc2931e`), and flag recall
  is **27.3%** (historical, same 10-fixture corpus; the current honest baseline
is **14.29%**, n=71, `run_id=run-ef443fc2931e` — the honest figure is worse,
not better) against a target of flagging 100% of disagreements. Threshold
  tuning (D2.2/D2.3) and deterministic calculated-answer verification (D2.4)
  are both exhausted; the remaining gap is free-form algebraic method
  verification, which is materially harder and was never in scope. This
  number did not move in Phases 3, 4 or 5, and this build does not claim
  examiner-level accuracy.
- **Real past-paper measurement (D3.21), reported separately and never
  averaged:** paper 22 predicted **37 vs 34** actual, paper 41 predicted
  **63 vs 66**. Both landed inside the stated ±10%-of-max tolerance, which was
  fixed before any result was seen.
- **Paper 22 was confidently wrong, and that is the finding worth acting on.**
  All 40 marks came back at confidence 1.0, band high, with zero review flags —
  and it was still 3 marks off. MCQ marking is deterministic string comparison
  against the official key, so no marking-judgement error is possible there:
  every one of those 3 marks is **vision/transcription** error. The confidence
  number is measuring the marker while the mistake happened in the extractor.
  Propagating extraction confidence into per-question confidence on the
  deterministic MCQ path changes the marking contract and was deliberately not
  patched unattended.

### 5.2 Content corpus

- **The question bank could not be filled from mark schemes alone (D3.7),** and
  Phase 4 built the stem extractor that closed it (D4.1/D4.2) — 72 papers into
  273 banked 0625 stems.
- **0580 and 0606 have zero ingested questions.** Placement and practice
  therefore honestly refuse for two of three subjects rather than fabricating
  content. The ceiling is **mark-scheme parse coverage (32/72 for 0625)**, not
  stem extraction — that is the highest-leverage thing to improve next.
- **A practice set is marked but its result cannot be read.** Marking runs and
  the marks are in the database; no route exposes them for `kind=practice`.
  Only the read is missing.

### 5.3 Notifications, scheduling and push

- **No scheduler exists in this build (D5.9).** `streak_warning` and
  `study_plan_reminder` are service methods that nothing invokes on a timer, and
  **at-risk rule 3 (≥14 days inactive) cannot fire at its seam** — the alert
  fires on correction, and a student who just uploaded is by definition active.
  These are not delivered notification types.
- **The study plan is week-*scoped*, not weekly-*regenerated*.** A plan carries a
  `week_start` and `POST /api/study-plan` supersedes the current week's row
  (`lemely/db/study_plan_repo.py:243-253`), but the only caller is the student
  (`lemely/web/routers/study_plan.py:112`). Nothing advances the plan when a new
  week begins: the student sees the honest "not generated yet" state until they
  ask. Earlier drafts of this file and the CHANGELOG said "regenerates weekly",
  which reads as a timer that does not exist.
- **No VAPID keys exist on the build machine,** so the push transport is
  unavailable by design and no real push can be delivered in any harness here.
  What is assertable is the notification inbox row and G-12's unavailable state.
- **Push is payload-less (D5.10),** so an offline arrival renders a generic
  "You have a new notification" — browsers require some notification per push.

### 5.4 Deliberately absent, because the honest source does not exist

Each of these ships as an explicit empty or unavailable state rather than as
invented data (UI spec §1.4, *never invent precision*):

- Exam-calendar dates — no CAIE timetable on this machine, and no CLI wrapper
  around `ExamCalendarService.ingest`.
- S-31 lifetime stats — a count of `xp_events` is wrong by construction: caps
  write no row, and dedupe writes one row for two markings.
- S-29 avatar image — no avatar storage; a monogram ships instead.
- G-10 rough location — no geo-IP and no stored IP.
- G-12's `weekly_summary` toggle — no backend enum value for it.

**None of these is a gap to be "filled" later without first building the
source.**

### 5.5 Frontend, accessibility and measurement

- ~~**`web/e2e/` and `web/playwright.config.ts` are in no tsconfig `include`
  (D3.20)**~~ — **CLOSED in Phase 6 (D6.1)**. The most expensive gate is now
  typechecked for the first time, via a separate `web/tsconfig.e2e.json`
  project.
- ~~**The Lighthouse performance floor is not enforced (D4.25)**~~ — **CLOSED in
  Phase 6 (D6.2)**, and the routes were fixed rather than the bar lowered: a
  single 1.3 MB bundle serving all 44 routes was split into 90 lazy chunks
  (entry 397 kB), taking the student-route performance minimum from 70 to 89.
- **Teacher routes are deliberately not performance-gated.** MISSION §11 states
  a floor for student routes only; inventing one for the others at the moment it
  would fail would be a scope change, not diligence.
- **Lighthouse runs on `default` states only** (deliberate, D3.17); axe runs on
  every audited state.
- **G-10 declines Lighthouse on purpose** — the Lighthouse runner drives its own
  navigation and would score the plain login form under G-10's slug, i.e.
  measure a state it never reached. `/login` is scored on its own entry.
- **The visual comparison can never be pixel-clean.** The E2E seed's `run_tag`
  is random per run, so every screen rendering a class name changes on every
  re-baseline. **`removed` (which must be 0) carries the regression gate; a
  nonzero `changed` count is not by itself a signal.**
- **PWA Lighthouse and camera capture were never live-tested** (no Chromium and
  no camera in the build sandbox, P2.9) — verified by inspection and manual
  trace only. See `reports/phase-2/pwa-limitations.md`. A real-device pass is
  needed before claiming a hard pass.
- **Component-library gaps deferred at Phase 2.5** (report §8): a sub-44px touch
  target, non-heading empty/error tags, no mobile BottomNav, raw `max-[1180px]:`
  literals outside the retrofitted screens, and a momentum-chart/TrendSparkline
  duplication blocked on a DTO change.
- **Two frontend gaps measured at P6.7 and left open on purpose**
  (`reports/phase-6/visual-qa.md` §3, from the `/impeccable audit` pass that
  scored 15/20 Good):
  - **[P1] ~600 arbitrary Tailwind literals across 41 files bypass tokens that
    already exist for them.** Not a cosmetic tidy — it is the Phase-2.5
    acceptance criterion ("the token file is the only source of design values")
    holding for the retrofitted screens but not across the whole surface. Left
    because a 600-site rewrite at ship time has no honest acceptance signal:
    the only check that would catch a mistake is a screenshot compare that
    **cannot be pixel-clean** (see the `run_tag` note above). It wants its own
    pass with a stable seed, not a ship-day sweep.
  - **[P2] 54 `size="sm"` controls sit near 31px.** WCAG 2.2 **AA (24px) is
    met; AAA (44px) is not.** This is the Phase-2.5 §8 touch-target gap
    re-confirmed by measurement, not a newly discovered one.
  - Counterweight, from the same audit: **zero hardcoded colours anywhere in
    `web/src`.**

### 5.6 Operational

- **The backend cannot run more than one replica (D6.6).** `JobRegistry`
  (`lemely/web/jobs.py`) — every in-flight correction job and its SSE stream —
  and the parent OTP challenge store (`lemely/auth/service.py`) are
  **process-local**. Two replicas mean a student reconnects to a replica that
  never heard of their job, and a parent's OTP is issued on one instance and
  verified on another. Intermittent, unreproducible, tripped silently by any
  host that autoscales by default, and caught by no test in this build.
- **The container entrypoint runs `alembic upgrade head` on every start.** Right
  for a one-command local bring-up, wrong for production, where migration must
  be a separate gated step. `docs/deployment.md` says so.
- **The $8 Gemini ledger lives on the container filesystem** under
  `/app/.lemely-cache`. A host that recycles containers resets measured spend to
  zero while the real bill climbs — mount a volume or the hard cap stops being
  a cap.
- **`/api/teacher/overview` is 10–40× slower than everything else measured**
  (p50 396 ms / p95 458 ms against 8–150 ms elsewhere) — the shape of an N+1
  across a teacher's classes and students. Observed on seeded data during the
  Phase-6 load-sanity pass; not chased, but it is the first place to look if the
  teacher console feels slow.
- **The CLI and Gradio surfaces use the JSON `HistoryStore` rather than Postgres —
  deliberately, not as unfinished work (D1.9, closed by D6.11).** The product
  surface is fully on Postgres: `get_history_store()` returns `DbHistoryStore`
  unconditionally, so every student, teacher and parent route is DB-backed, and
  parity between the two backends is proven by `tests/test_history_repo_parity.py`.
  The two stores are kept because they have **incompatible id contracts**:
  `DbHistoryStore` requires a UUID that already exists in `users` (the FK is
  enforced), while the CLI's `--student-id` is a free-form local label. Migrating
  the CLI would therefore give three offline commands (`correct --record`,
  `compare-performance`, `study-plan`) a hard dependency on a running Postgres and
  a provisioned user row — a regression traded for a deletion. Gradio is an
  internal debug tool, not a product surface. Reopening this is a product decision
  about whether the CLI shares the product's identity model.
- **A blank credential env var used to read as a configured one, and the health
  endpoint said so (D6.8).** Fixed in Phase 6 — `${VAR:-}` in `docker-compose.yml`
  made pydantic build `SecretStr("")`, which is not `None`, so `/api/health`
  answered `apiKeyConfigured: true` on a stack with no Gemini key at all and
  GoTrue's explicit "key is not configured" error never fired. Recorded here
  rather than deleted because the *shape* survives the fix: any check of the form
  `if value is None` is a claim about presence, not about usability, and this
  build has been bitten by that family repeatedly.
- **No CORS middleware exists, and that is the intended state (D6.5).** nginx
  proxies `/api` to the backend on the same origin the SPA was loaded from, so
  the browser issues no cross-origin request. A split-origin deploy would need a
  config-driven allowlist with `allow_credentials=False`, since auth is
  bearer-token and not cookie-based.

## 6. Evidence

Every figure in this document is re-derivable from a committed artifact. This
section says which artifact, and with what command. That is not ceremony: this
build was burned repeatedly by numbers that were hand-carried between documents
until nothing regenerated them — an axe count that was double the truth (146
against a 73-row summary), a Gemini spend line that read `$0.1612` against a
real ledger of `$0.18429`, an e2e suite reported as 30 tests that `playwright
test --list` put at 34, and a "regenerates weekly" study plan with no scheduler
anywhere in the codebase. **Re-derive before quoting; do not copy from
`BUILD/STATE.md` prose, including this file's own earlier drafts.**

### 6.1 Measured from committed artifacts

Verified on the Phase-6 tree at the time of writing, by running the command in
the right-hand column — not carried forward.

| Claim | Value | Artifact / re-derivation |
| --- | --- | --- |
| Route operations, all guarded | **121** — 5 public (4 auth entrypoints + `/api/health`), 12 authenticated-but-role-agnostic, 104 role-gated | `tests/test_authz_matrix_complete.py` derives the route set *from the app* and asserts it equals the declared `EXPECTED` table, so an undeclared route and a stale declaration both fail. `pytest tests/test_authz_matrix_complete.py` |
| Schema migrations | **18**, additive-only | `ls lemely/db/migrations/versions/*.py`; `alembic check` clean in both directions |
| Backend test files | **128** | `ls tests/test_*.py \| wc -l` |
| Web unit test files | **16** | `find web -path web/node_modules -prune -o -name '*.test.*' -print \| grep -v '^web/e2e'` |
| Playwright E2E | **13 spec files / 34 tests** | `cd web && npx playwright test --list` — the count, not the file count, is the one that drifted |
| API load sanity | 8 endpoints, concurrency 10, ~10k requests, **zero errors**; `/api/teacher/overview` p50 **395.73 ms** / p95 **458.1 ms** against 8–150 ms elsewhere | [`reports/phase-6/load-sanity.json`](reports/phase-6/load-sanity.json) and its rendered [`.md`](reports/phase-6/load-sanity.md). No verdict is printed — MISSION states no latency threshold, and grading against an invented one would be manufactured precision (§5.6) |
| Gemini spend against the $8 cap | read the ledger, never this document | `outputs/gemini_spend.json` (`cumulative_usd`) |

### 6.2 The UI baseline this build is measured against

Phase 5's committed audit artifacts, recomputed from the JSON this session
rather than quoted from the phase report — and they agree with it:

- **73 axe route-states, zero violations at any impact** — `reports/phase-5/axe/_summary.json`, one row per audited state.
- **44 Lighthouse route reports** — `reports/phase-5/lighthouse/*.json`. The directory holds 45 files; the 45th is `_summary.json` and is not a route.
- **Accessibility floor 96** (`teacher-review`; 100 on the rest), against the ≥95 gate.
- **8 routes below performance 80** at Phase 5 (floor 65, `teacher-quiz-detail`) — the gap P6.1 closed for the student routes, which MISSION §11's floor actually covers. See §5.5.

```bash
# recompute the a11y floor and the sub-80 performance list from the artifacts
python3 - <<'PY'
import json, pathlib
rows = []
for f in sorted(pathlib.Path('reports/phase-5/lighthouse').glob('*.json')):
    j = json.loads(f.read_text())
    if not isinstance(j, dict) or not isinstance(j.get('categories'), dict):
        continue  # _summary.json is a list, not a route report
    c = j['categories']
    pick = lambda k: round(c[k]['score'] * 100) if isinstance(c.get(k, {}).get('score'), (int, float)) else None
    rows.append((f.stem, pick('accessibility'), pick('performance')))
print('route reports:', len(rows))
print('a11y floor:', min(r[1] for r in rows))
print('perf < 80:', sorted(((r[0], r[2]) for r in rows if r[2] is not None and r[2] < 80), key=lambda t: t[1]))
PY
```

### 6.3 The Phase-6 closing runs — all filled

This table was written with **every row deliberately blank**, because the recurring
defect of this build is a figure whose source no longer exists. Each row named the
task that would fill it and the artifact the number had to come from, and nothing
was estimated in the meantime. **All five rows are now closed from their own
artifacts**, and each is struck through rather than deleted so the discipline stays
readable:

| Figure | Filled by | Source |
| --- | --- | --- |
| ~~Test count and coverage on the final tree~~ | ~~P6.11~~ | **Filled: 3,508 tests — 3,502 passed / 6 skipped / 0 failed — at 90.92% coverage**, up from Phase 5's 2,927 / 90.91%, so coverage never dropped (MISSION §6 gate 2). From a **separate serial** `pytest -q` run (`EXIT=0`), *not* from `scripts/check.sh`'s log, which prints nothing for a passing gate and therefore holds no count and no coverage figure at all. All 6 skips are opt-in and are itemised in [`reports/phase-6/REPORT.md`](reports/phase-6/REPORT.md) §3 — 2 live billed accuracy tests, 4 gated on Supabase keys being exported |
| ~~The 13-gate verdict on the final tree~~ | ~~P6.11~~ | **Filled, and it is a pass: `EXIT=0`, all 13 gates PASS, 0 skipped.** `0 skipped` is load-bearing — `check.sh` skips the three live-stack UI gates when Supabase is down and still exits 0. Launched detached on the tree at `66950f3`; the only commits between that tree and the shipped one are documentation, verified by `git diff 66950f3..HEAD -- lemely web scripts tests Makefile pyproject.toml …` being **empty**. That check is why this verdict is true of the shipped code where P6.6's `EXIT=0` was not (three commits landed after it, one of them product code). Gate table in [`reports/phase-6/REPORT.md`](reports/phase-6/REPORT.md) §4 |
| ~~Phase-6 axe / Lighthouse / screenshot corpus~~ | ~~P6.7~~ | **Filled.** [`reports/phase-6/visual-qa.md`](reports/phase-6/visual-qa.md), recounted from the JSON in [`reports/phase-6/REPORT.md`](reports/phase-6/REPORT.md) §5: **73 axe route-states, 0 violations at any impact**; **44 Lighthouse route reports, a11y floor 96** (`teacher-review`), **performance floor 80** (`teacher-quiz-detail`) with **zero routes below 80** where Phase 5 had eight; 0 console errors; 0 horizontal-scroll violations; **48 screens / 246 screenshots** plus per-role contact sheets (`contact-sheet-index.html`) |
| ~~Fresh-clone acceptance~~ | ~~P6.10~~ | **Filled.** [`reports/phase-6/fresh-clone.md`](reports/phase-6/fresh-clone.md) — `make up` from a clone of `be49d34` reached `EXIT=0` with both containers healthy, and all five demo roles authenticate **through nginx on :8080**, each confirmed by reading `/api/me/profile` back. Four defects the thirteen gates could not see came out of it, fixed in `310fade` (D6.8) |
| ~~Visual regression against the Phase-2.5 baselines~~ | ~~P6.7~~ | **Filled, and it is a pass: `removed: 0` against both baselines.** [`compare-vs-phase-2.5.json`](reports/phase-6/compare-vs-phase-2.5.json) — 207 added / **0 removed** / 39 changed; [`compare-vs-phase-5.json`](reports/phase-6/compare-vs-phase-5.json) — 0 added / **0 removed** / 112 changed / 134 unchanged. `changed` is not a regression signal — the seed's `run_tag` is random per run, so every screen rendering a class name changes on every re-baseline (§5.5). One trap the run hit and the report records: **the corpus has three producers**, and running only the audit runner reported the other seven screens as `removed` — the exact blocker signal, from screens that had never been asked for |

## 7. Running it

See [`README.md`](README.md) for local development and
[`docs/deployment.md`](docs/deployment.md) for the containerised stack and the
cloud recipe. The short version:

```bash
make db-up          # supabase start
make db-migrate     # alembic upgrade head
make seed           # reference data + demo accounts
make up             # backend + built SPA, one command
```

`make seed` is idempotent and creates one demo account per role. The full
credential table is in [`README.md`](README.md); the short version is
`<role>@demo.lemely.local` / `Demo-Lemely-1!` for the four password roles, and
phone `+10000000000` (mock-SMS one-time code, printed to the backend log) for
the parent. They are local demo credentials on a reserved `.local` domain, not
secrets, and must never be seeded into a real deployment.

The accounts are empty by design. `scripts/seed_e2e.py` is what populates a
database with realistic marked papers, classes and analytics — but it tags every
run randomly, so its credentials cannot be written down.

> Until Phase 6 this section carried a warning that `make seed` inserted zero
> rows and created zero accounts while logging a successful `db.seed.done` —
> `seed_reference_data`/`seed_demo_accounts` were Phase-0 stubs with a bare
> `pass`. P6.10 made them real; the warning is retired rather than deleted
> because the shape of that bug is worth remembering: a command that logs
> success while doing nothing is invisible to every gate in this build.
