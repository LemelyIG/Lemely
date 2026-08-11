# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.0] — 2026-08-12

The first complete product. Lemely went from a CLI around a marking core to a
multi-role platform: PostgreSQL, authentication and tenancy, a real correction
pipeline, four portals, content generation, an engagement layer, and a
one-command deployment.

Per-phase detail, command outputs and screenshots are in `reports/phase-*/`;
the feature-by-feature status — including what was deliberately **not** built —
is in [`DELIVERY.md`](DELIVERY.md).

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

#### The correction loop

- Server-sent-events correction pipeline: upload or in-app scan → answer
  extraction → method-mark-aware marking → grade → predicted grade after
  boundaries → mistakes and weakness topics.
- **A confidence value on every mark and every paper**, with low-confidence
  results routed into a teacher review queue.
- Grade-boundary ingestion from cambridgeinternational.org, per paper variant.
- Plagiarism and AI-detection advisory flags (signals, never verdicts).
- Accuracy harness with ten golden fixtures across 0580 / 0606 / 0625, plus an
  end-to-end measurement against two real solved scripts.
- Question-stem extractor and a syllabus taxonomy transcribed from the official
  CAIE documents, which together populate the question bank.

#### Teacher, parent and school surfaces

- Class model with real per-teacher row-level ownership.
- At-risk flagging on three labelled rules: declining trend, predicted grade
  below target, and prolonged inactivity.
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

- Topic-classified practice generation targeting a student's weak topics.
- Flashcards with SM-2 spaced repetition.
- A ~15-minute placement test assembled from real past-paper questions, reusing
  the quiz engine.
- Onboarding questionnaire capturing subjects, session, school, study time,
  grade level and target grades.
- Adaptive study plan with concrete sessions, regenerated weekly.

#### Engagement

- XP engine with anti-farming caps and Cairo-civil-date streaks.
- Weekly-XP leaderboards across friends, class, school, global and per subject,
  with an opt-out flag. **Leaderboards show effort, never grades.**
- Friends by friend code.
- Notification inbox and VAPID web push, gated by per-user preferences.

#### Frontend

- The React 19 + Vite SPA became the real product: every screen wired to the
  API through react-query, all mock data deleted.
- Design-token layer sourced from `DESIGN.md` (Tailwind v4 theme plus CSS custom
  properties) and a documented cross-cutting component library.
- PWA foundation: manifest, service worker, installability, and camera capture
  producing a multi-page PDF client-side.
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
