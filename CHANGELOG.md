# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Self-service sign-up (issue [#10](https://github.com/LemelyIG/Lemely/issues/10)), closing the gap
recorded in `DELIVERY.md` §5: `POST /api/auth/signup` existed and every marketing CTA still pointed
at `/login`. Full detail, decisions and screenshots are in `BUILD/DECISIONS.md` (`D7.1`–`D7.12`);
this entry is the user-visible summary.

### Added

#### Accounts and sign-up

- Nine new public screens: role selection, student/teacher sign-up details, email verification
  pending and confirm, password reset (request/confirm), and join-with-invite-code
  (preview/redeem) — `/signup`, `/signup/student`, `/signup/teacher`, `/verify-email(/:token)`,
  `/reset(/:token)`, `/join(/:code)`.
- **Self-service sign-up now admits `teacher`, not only `student`.** A self-registered teacher is
  always independent (no school field, no `School` row) — school membership arrives later, by
  invite or platform-admin provisioning. `school_admin` and `platform_admin` remain unobtainable by
  an anonymous caller, unchanged.
- Email verification, gating exactly one route — submitting a paper for marking — and nothing
  else; an unverified account can sign in, browse and upload normally *(limited: no configured mail
  provider actually sends anything in this build — see below)*.
- Password reset by email link, which revokes every outstanding token **and every signed-in
  device** on success.
- Redeemable invite codes: a school admin can mint a seat invite, a teacher can mint a class
  invite; a visitor holding either sees what they're joining before committing. Coexists with the
  pre-existing direct-create/temporary-password flow rather than replacing it.
- Platform-admin surface for schools: create a school with a seat quota, edit it, and create a
  school_admin for it — the missing first link that made `POST /api/school/teachers/invite`
  unreachable in any real deployment before this.
- First-run gates: a student with no completed onboarding is routed to the onboarding wizard from
  anywhere in the portal; a teacher with zero classes is routed to a create-first-class step that
  ends on the class's join code.
- Marketing CTAs and the login screen now point at `/signup` and `/reset` instead of dead-ending
  at `/login`.

#### Deployment and CI/CD

- Automated CI/CD: GitHub Actions deploys staging (`develop`) and production
  (`main`, behind a manual approval gate) to Google Cloud Run (backend) and
  Cloudflare Workers (frontend — static assets plus a `/api/*` reverse proxy
  that preserves the existing same-origin, no-CORS architecture). Database
  migrations run as their own gated job ahead of each deploy rather than on
  container start. See [`docs/ci-cd.md`](docs/ci-cd.md).

### Known limitations, stated rather than discovered later

- **No configured provider sends mail.** The email seam (`EmailProvider`, mirroring the existing
  SMS seam) ships with only an offline mock, exactly like parent phone-OTP. No screen claims a
  mail was sent.
- **The sign-up/resend/reset-request cooldown is in-process and per-worker** — a real deterrent
  against casual abuse from one process, not a distributed rate limit.
- **The invite-code *mint* action has no screen yet.** The redemption side (`/join`) is fully
  wired; a school admin or teacher can mint a code today only via a direct API call, not a button
  in the product. See `BUILD/BLOCKERS.md` B8.

## [1.0.0] — 2026-08-12

The first complete product. Lemely went from a CLI around a marking core to a
multi-role platform: PostgreSQL, authentication and tenancy, a real correction
pipeline, four portals, content generation, an engagement layer, and a
one-command deployment.

Per-phase detail, command outputs and screenshots are in `reports/phase-*/`;
the feature-by-feature status — including what was deliberately **not** built —
is in [`DELIVERY.md`](DELIVERY.md).

Entries below are marked *(limited)* where the feature exists and is tested but
cannot fully operate in this build; `DELIVERY.md` §5 says why in each case. An
unmarked entry is not thereby proof of anything — read §5 before relying on any
line here.

### Added

#### Data, identity and tenancy

- PostgreSQL via a local Supabase stack; SQLAlchemy 2 models and an
  additive-only Alembic migration chain owned by the backend.
- Supabase GoTrue identity with backend-issued HS256 JWTs; five roles
  (`student`, `parent`, `teacher`, `school_admin`, `platform_admin`) enforced
  server-side on every route.
- Subscription and seat model with manual platform-admin activation, and a
  three-device session registry with a 409 login challenge and a device
  management screen.
- Parent phone-OTP login behind a provider abstraction, with a mock SMS
  provider that logs the code.
- Supabase Storage for uploaded scans and PDFs.
- `make seed` creates reference data and one demo account per role with fixed,
  documented credentials, and is idempotent. It had been a stub since Phase 0 —
  inserting nothing while logging success. Credentials are in `README.md`; they
  are local demo logins and must never be seeded into a real deployment.

#### The correction loop

- Server-sent-events correction pipeline: upload or in-app scan → answer
  extraction → method-mark-aware marking → grade → predicted grade after
  boundaries → mistakes and weakness topics.
- **A confidence value on every mark and every paper**, with low-confidence
  results routed into a teacher review queue.
- Grade-boundary ingestion from cambridgeinternational.org, per paper variant.
- Plagiarism and AI-detection advisory flags (signals, never verdicts).
- Accuracy harness with ten golden fixtures across 0580 / 0606 / 0625, plus an
  end-to-end measurement against two real solved scripts *(limited)*: the
  synthetic accuracy target is **not met** — 83.8% mark-level agreement against
  a ≥95% goal, with flag recall 27.3%. Both real papers landed inside the stated
  tolerance, but one of them was confidently wrong (all 40 marks at confidence
  1.0, zero flags, three marks of pure transcription error), because MCQ
  confidence measures the marker while the error happens in the extractor.
- Question-stem extractor and a syllabus taxonomy transcribed from the official
  CAIE documents, which together populate the question bank — 72 papers into 273
  banked 0625 stems. The ceiling is mark-scheme parse coverage (32 of 72), not
  stem extraction.

#### Teacher, parent and school surfaces

- Class model with real per-teacher row-level ownership.
- At-risk flagging on three labelled rules: declining trend, predicted grade
  below target, and prolonged inactivity — the third *(limited)*: it is
  implemented and tested, but no scheduler exists to fire it, and its current
  seam (correction upload) can never observe an inactive student.
- Teacher analytics — per class, per student, and aggregate weakness topics.
- Review queue with an override-and-annotate flow; overrides are recorded
  corrections.
- Quiz builder: question pool, difficulty targeting by expected grade, material
  selection, class assignment, auto-marking through the existing engine, and
  results feeding analytics.
- Parent portal: linked children, read-only performance and weakness views,
  notification preferences.
- Announcements from teachers to their classes and school admins to their
  school, plus an exam calendar.

#### Content and study plans

- Topic-classified practice generation targeting a student's weak topics
  *(limited)*: only 0625 has ingested questions, so 0580 and 0606 honestly
  refuse; and a generated set is marked but no route exposes its result yet.
- Flashcards with SM-2 spaced repetition.
- A ~15-minute placement test assembled from real past-paper questions, reusing
  the quiz engine *(limited)*: 0625 only, for the same reason.
- Onboarding questionnaire capturing subjects, session, school, study time,
  grade level and target grades.
- Adaptive study plan with concrete sessions, scoped to an ISO week.
  Regeneration is student-triggered and supersedes that week's plan; nothing
  advances it on a timer, so a new week starts in the "not generated yet" state.

#### Engagement

- XP engine with anti-farming caps and Cairo-civil-date streaks.
- Weekly-XP leaderboards across friends, class, school, global and per subject,
  with an opt-out flag. **Leaderboards show effort, never grades.**
- Friends by friend code.
- Notification inbox and payload-less VAPID web push, gated by per-user
  preferences *(limited)*: no VAPID keys exist on the build machine, so the
  transport is unavailable by design and no real push has been delivered in any
  harness here. The inbox row and the unavailable state are what is assertable.

#### Frontend

- The React 19 + Vite SPA became the real product: every screen wired to the
  API through react-query, all mock data deleted.
- Design-token layer sourced from `DESIGN.md` (Tailwind v4 theme plus CSS custom
  properties) and a documented cross-cutting component library.
- PWA foundation: manifest, service worker, installability, and camera capture
  producing a multi-page PDF client-side *(limited)*: installability and the
  camera path were verified by inspection and manual trace only — there is no
  Chromium with a camera in this environment, so neither has had a real-device
  pass.
- Route-level code splitting.

#### Build, test and deploy

- `scripts/check.sh` — one command running all thirteen quality gates.
- Playwright E2E across all five roles and the screenshot corpus; Puppeteer
  audit runner with axe-core and Lighthouse; per-phase contact sheets.
- Persistent Gemini cost ledger with a hard spend ceiling.
- Concurrency tests and an API load-sanity script.
- Authz matrix generated from the application, so an undeclared route fails a
  test.
- `Dockerfile`, `web/Dockerfile`, `docker-compose.yml` and `make up` — one
  command for Supabase-local plus the backend plus the served SPA.
- [`docs/deployment.md`](docs/deployment.md) and [`DELIVERY.md`](DELIVERY.md).

### Changed

- History for the web surface moved from JSON files to PostgreSQL; the CLI and
  Gradio kept the JSON store.
- Gradio is now an internal debug tool, not a user surface.
- `lemely/io/det/` was wired in and the parsing monolith deleted.
- Two table-extraction defects were fixed in mark-scheme parsing: only the first
  table on a page was read, and CAIE compensatory C-marks were summed on top of
  the A-marks they replace.

### Fixed

- Two IDOR-shaped endpoints and the implicit "all students are one cohort"
  teacher queries.
- The Gemini monthly cost ceiling, which reset per process.
- `HistoryStore.load()` swallowing corruption.
- A concurrency hole in `XpService.award` where the daily anti-farming cap could
  be defeated by simultaneous requests.
- The MCQ plagiarism check, which flagged every *correct* answer.
- `ruff format --check` failing in CI, and a `ruff` exclusion bug that hid it.

## [0.1.0] — 2026-08-04

Foundations: a production-structured package with strict typing, layered
architecture, pre-commit and CI gates, and a stable CLI contract.

### Added

- Layered package layout `lemely/{core,io,app,runtime}` enforced by import-linter.
- `lemely/runtime/config.py`: pydantic-settings loader with precedence
  env > `.env` > TOML > defaults; `extra='forbid'` on every section.
- `lemely/runtime/logging.py`: structlog with TTY auto-detect, JSON-in-CI,
  secret-redaction processor for `*_api_key` / `*_token` keys.
- `lemely/runtime/errors.py`: typed exception hierarchy with documented exit codes
  (see `docs/exit-codes.md`).
- Click-based CLI (`lemely.app.cli`) replacing the legacy argparse entrypoint,
  with global `--json`, `--config`, `--log-level`, `--log-format`, `-v/-q`.
- New subcommands: `doctor` (config + env + path readiness) and `version`.
- `parse-mark-schemes --on-error continue|fail` and a dedicated
  `PartialFailureError` exit code path.
- Rich-based renderers for human-mode CLI output; JSON mode unchanged for scripts.
- `lemely.toml.example` plus a generator (`lemely/runtime/example_toml.py`) and
  drift test that fails CI when the example falls behind the schema.
- Pre-commit hooks (ruff, ruff-format, mypy, import-linter, basic hygiene,
  detect-private-key).
- GitHub Actions CI matrix (Python 3.12 / 3.13 / 3.14) plus pre-commit job.
- `Makefile` mirroring CI targets (`make dev test lint typecheck imports fmt`).
- Architecture tests: import-linter contract runner and `no-print-in-core`.

### Changed

- `BatchParseResult` now exposes `total`, `parsed`, `skipped`, `failed` as
  Pydantic computed fields instead of ad-hoc attributes.
- CLI error messages routed through `LemelyError.exit_code` so shell scripts and
  CI can branch on a stable contract.

### Removed

- Legacy `lemely_mvp/` package (migrated to `lemely/`).
