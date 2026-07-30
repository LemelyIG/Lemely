# Lemely — Repository Audit Dossier

**Scope:** read-only factual audit. No code was written, refactored, or fixed.
**Commit audited:** `main` @ `24b6c0f` (Merge PR #2 `feat/web-ui`), in sync with `origin/main`.
**Date:** 2026-07-30. **Auditor method:** every claim below was verified by reading files and/or running commands; anything not confirmed is marked **(unverified)**.
**Working-tree note:** two tracked files show local modifications not part of any commit — `Sources/Physics/MarkingSchemes/0625_m20_ms_12.json` and `0625_s20_ms_31.json`.

---

## 0. Executive summary

Lemely is a **Python CAIE-marking toolkit** (CLI + Gradio UI + FastAPI backend) with a **separate React SPA**. The Python core is genuinely engineered: strict typing (mypy strict, clean), layered architecture enforced by import-linter, 308 tests at 82% coverage, and real domain logic for parsing mark schemes, marking answers, predicting grades, and generating quizzes via Google Gemini.

The **product-facing story is much weaker than the code hygiene suggests**:

- The shipped **React SPA renders 100% hardcoded mock data** and never calls the backend (`lib/api.ts` is imported nowhere).
- **Authentication does not exist** — every request resolves to an anonymous caller; all data collapses into one shared bucket; two student endpoints are IDOR-shaped.
- **No deployment exists** — no Docker, no IaC, no hosting target, no production wiring between SPA and API.
- **CI is currently red** (`ruff format --check` fails on `main`).
- Several "accuracy-first" claims are hollow: the grade-boundary table ships with **no per-paper-variant boundaries** (only coarse subject-level defaults for 4 subjects), so predictions are never paper-exact; the `monthly_usd_ceiling` cost cap **is not actually monthly**; and a cleaner deterministic parser (`lemely/io/det/`, ~1,256 LOC) is **abandoned dead code**.

Verdict: **a strong engineering skeleton and a polished design prototype, not a shippable product.**

---

## 1. Stack, build & toolchain

| Layer | Technology | Version | Evidence |
|---|---|---|---|
| Backend language | Python | requires `>=3.12,<3.15`; active venv **3.13.12**; system **3.14.6** | `pyproject.toml:10`; `.venv/bin/python --version` |
| Build backend | Hatchling | `>=1.25`, single wheel package `lemely` | `pyproject.toml:1-3,47-48` |
| Core deps | pydantic 2.11–2.13, pydantic-settings 2.4+, click 8.3, rich 15, structlog 24–26, tenacity 9, google-genai 2.1–3, PyMuPDF 1.27, Pillow 12, jinja2 3.1, pdfplumber 0.11 | pinned ranges | `pyproject.toml:13-25` |
| Extra `ui` | gradio `>=6.1,<7` | | `pyproject.toml:27-28` |
| Extra `web` | fastapi `>=0.115,<1`, uvicorn[standard], python-multipart | | `pyproject.toml:29-33` |
| Extra `dev` | pytest 8+, pytest-cov 5+, ruff 0.7+, mypy 1.13+, pre-commit 4+, import-linter 2.1+, respx 0.21+ | | `pyproject.toml:34-42` |
| Frontend | React 19.2 + react-dom, TypeScript ~6.0.2, Vite ^8.1.1, Tailwind ^4.3.3 (`@tailwindcss/vite`), oxlint ^1.71, react-router-dom ^7.18, @tanstack/react-query ^5.101 | | `web/package.json` |
| Host toolchain (installed) | ruff **0.15.20**, mypy **2.1.0**, pytest **9.1.1**, import-linter **2.12**; Node **v26.4.0**, npm **12.0.1** | | direct `--version` probes |

**Package managers:** pip (editable install) is the documented path; **two lockfiles coexist** — `uv.lock` (uv, 95 packages) and `requirements.lock` (header says `uv pip compile … --extra ui --extra dev`, i.e. *not* `--extra web`). The `Makefile lock` target regenerates via `pip freeze` — a different mechanism than the recorded uv compile, so the two will drift (`requirements.lock:1-2`, `Makefile:31-32`).

**Layout:** *not* a formal monorepo tool (no workspaces/turbo/nx). It's a Python package (`lemely/`) plus a sibling standalone SPA (`web/`) with its own `package.json`/`node_modules`/`dist`.

### Build/dev/test commands — verified by actually running them

| Command | Source | Result this session |
|---|---|---|
| `pytest` | `Makefile:12-13`, `pyproject.toml:159` | ✅ **306 passed, 2 skipped, 12 subtests, coverage 82.39%** (gate 70%), exit 0 |
| `ruff check .` | `Makefile:15-16` | ✅ "All checks passed!" |
| `ruff format --check .` | `ci.yml:39-40` | ❌ **exit 1** — "Would reformat: `tests/test_cli_new_commands.py`" |
| `mypy lemely` | `Makefile:22-23` | ✅ "no issues found in 77 source files" |
| `lint-imports` | `Makefile:25-26` | ✅ 2 contracts kept |
| `npm run build` (`tsc -b && vite build`) | `web/package.json:7` | ✅ exit 0; 4642 modules; `dist/assets/index-*.js` ≈ 486 KB (142 KB gz) |
| `npm run lint` (oxlint) | `web/package.json:8` | ✅ exit 0; **6 warnings** (`react/only-export-components` fast-refresh) |
| `pip install -e ".[dev,ui]"`, `npm run dev`, `npm run typecheck`, `pre-commit run --all-files` | — | not run this session (dev-only / long-running) |

---

## 2. Directory map (annotated)

**Top level**

| Path | Purpose | Notes |
|---|---|---|
| `lemely/` | The product Python package | see subpackages below |
| `web/` | Standalone React 19 + Vite 8 SPA (Teacher/Student portals) | own tooling; **mock-data prototype** |
| `tests/` | pytest suite (+ `tests/architecture/`, `tests/golden/`) | 308 tests; `golden/` holds only `.gitkeep` |
| `Sources/` | Bundled CAIE past papers + marking schemes (PDF + JSON) | dir is gitignored but some JSON tracked |
| `outputs/` | Runtime output dir (history store, parsed schemes) | gitignored |
| `docs/` | Design specs + `exit-codes.md`; `docs/superpowers/` planning docs | |
| `design/`, `DESIGN.md`, `PRODUCT.md` | Product/design assets (HTML mockups, PNGs) | added in PR #2 |
| `.github/workflows/ci.yml` | The **only** CI config | |
| `Makefile` | Dev task runner mirroring CI | |
| `main.py` | Thin entrypoint → `lemely.app.cli:main` | `main.py:5-8` |
| `lemely.toml` / `lemely.toml.example` | Local config (real one gitignored) | |
| `pyproject.toml` | Single source of build/deps/tooling config | |
| `uv.lock`, `requirements.lock` | Two lockfiles (drift risk) | |
| `CHANGELOG.md`, `README.md` | Docs (CHANGELOG is **stale** — Phase-1 only) | |

**`lemely/` subpackages** — layered `core < io < app`; `runtime` is a leaf (import-linter enforced):

| Subpackage | Responsibility | Evidence |
|---|---|---|
| `lemely/core/` | Pure domain logic — no disk, no network | `core/__init__.py` |
| `lemely/io/` | Disk + Gemini adapters; deterministic parser (`io/det/`, `io/parsers_det.py`) | `io/__init__.py` |
| `lemely/app/` | CLI (`cli.py`) + Gradio (`gradio_app.py`) | `app/__init__.py` |
| `lemely/runtime/` | Config, logging, errors, events (may not import domain layers) | `pyproject.toml:191-195` |
| `lemely/web/` | FastAPI backend (meta/teacher/student routers, SSE, jobs) | `web/__init__.py` |
| `lemely/accuracy/` | Accuracy-evaluation harness | `accuracy/harness.py` |
| `lemely/data/` | Bundled static data (`grade_boundaries.json`) | `data/__init__.py` |

---

## 3. Data layer

**There is NO relational database, NO ORM, and NO migration system.** Repo-wide grep for `sqlalchemy|alembic|sqlite3|create table|migrat` in `lemely/` returns a single unrelated docstring hit (`cli.py:120`); `pyproject.toml` declares no DB/ORM dependency. Persistence is **plain JSON files**; the "schema" is the set of Pydantic models in `lemely/core/`.

**Persistence stores** (both in `lemely/io/`):

| Store | Layout | Model | Evidence |
|---|---|---|---|
| `HistoryStore` | one file per student: `{output_dir}/history/{student_id}.json`, `indent=2` | `StudentHistory` → `list[PaperRecord]` | `io/history_store.py:24,36-37` |
| `GradeBoundaryStore` | single bundled static `lemely/data/grade_boundaries.json` (read-only) | plain dict | `io/grade_boundaries.py:15,67` |

**HistoryStore mechanics:** `append()` is read-modify-write with **atomic replace** (`tempfile.mkstemp` + `os.replace`, `history_store.py:48-56`). Concurrency is documented last-writer-wins; `fcntl.flock` is left as an unimplemented "Future:" note (`:1-7`). ⚠️ `load()` **silently swallows every exception and returns an empty `StudentHistory`** (`:66-67`), so a corrupt/schema-drifted file reads as "no history."

**Model relationships:** `StudentHistory (1)→(N) PaperRecord`; `PaperRecord` embeds one `ExamMetadata` + `list[WeakArea]` + ISO `recorded_at` (`core/history.py:12-39`). `CorrectionResult → list[CorrectedQuestion]` with auto-summed totals and awarded≤max validators (`core/schemas.py:110-133`). `SubjectResult → list[CorrectionResult]` with cross-paper validators (`schemas.py:200-244`). `AccuracyReport` = `CorrectionResult` + `WeaknessReport` + `GradePrediction` (`schemas.py:169-172`).

**Migration state: NONE.** No `schema_version` on any persisted model; no upgrade path. Combined with `load()`'s blanket exception swallow, any model-shape change silently zeroes existing student files.

---

## 4. Auth

**Provider: none. Session model: none. Roles/permissions: none implemented.**

- `get_auth_context()` is a hardcoded no-op returning an anonymous `AuthContext(user_id="anonymous", role="anonymous")` — no token/session/header parsing (`web/deps.py:37-55`). Its own docstring admits it's a stub.
- `auth.role` is **never read anywhere** in `lemely/web/` → no RBAC.
- The dependency is injected into **only 6 student endpoints**; **zero teacher endpoints** have any auth dependency (`teacher.py` has no `get_auth_context` reference).
- Every student read does `history_store.load(auth.user_id)` = `load("anonymous")` → **all users share one history bucket** (`student.py:197,224,340,466,542`).
- **IDOR:** `POST /student/plan` and `POST /student/onboarding` take **no auth dependency** and act on client-supplied `payload.studentId` (`student.py:479-484,570-571`).

There are no exception handlers, no rate limiting, and **no CORS middleware** anywhere in `lemely/web/` (`app.py` mounts three routers and nothing else).

---

## 5. External services & environment variables

**Only external service: Google Gemini** via the `google-genai` SDK (`io/gemini.py:126,133`). No DB server, queue, or cloud SDK.

| Env var | Consumed at | Required | Default | Purpose |
|---|---|---|---|---|
| `GEMINI_API_KEY` (unprefixed) | `cli.py:460` (doctor); SDK env fallback when `api_key=None` | for real AI calls | — | Gemini auth. ⚠️ **Does not populate `settings.gemini_api_key`** |
| `GOOGLE_API_KEY` | google-genai SDK (priority over `GEMINI_API_KEY`) | alt | — | Gemini auth (undocumented here) **(unverified against SDK version)** |
| `LEMELY_GEMINI_API_KEY` | pydantic-settings `env_prefix="LEMELY_"` | alt | `None` | The **only** env var that sets `settings.gemini_api_key` (`config.py:133,145`) |
| `LEMELY_*` (nested `__`) | `config.py:132-137` | no | per-field | Override any settings field (e.g. `LEMELY_GRADIO__PORT`) |
| `LEMELY_WEB_HOST` / `LEMELY_WEB_PORT` | raw `os.environ` in `web/__main__.py:25,31` | no | `127.0.0.1` / `8000` | Uvicorn bind — **bypasses Settings**, invisible to `lemely doctor` |
| `XDG_CONFIG_HOME` | `config.py:169` | no | `~/.config` | TOML discovery fallback |
| `.env` file | `config.py:135` (`env_file=".env"`) | no | absent | dotenv source |

Precedence (verified `config.py:156-162`): `LEMELY_*` env > `.env` > TOML > file-secrets > defaults; every section is `extra="forbid"`.

**Missing / placeholder:**
- **No `.env` and no `.env.example`** — env vars documented only in README prose; only `lemely.toml.example` ships.
- `GEMINI_API_KEY` **not set** in this environment → all `live` tests skip; real Gemini path unverified here.
- ⚠️ **Env-mapping trap:** an unprefixed `GEMINI_API_KEY` authenticates CLI/Gradio (via SDK env fallback) but **web-portal AI features gate on `settings.gemini_api_key is None`** (`teacher.py:334,796`; `student.py:507`; `meta.py:19`) → the web portal silently degrades / returns 503 unless `LEMELY_GEMINI_API_KEY` or the TOML value is used.

---

## 6. Routes / endpoints inventory

### FastAPI backend — 24 routes, all `/api`-prefixed, all effectively unauthenticated

Legend: **working** = computes real results; **partial** = real data plus hardcoded/empty fields; **stubbed** = returns canned/no-op output.

| Method | Path | Function | Auth | Status | Evidence |
|---|---|---|---|---|---|
| GET | `/api/health` | `meta:health` | none | working | `meta.py:16-19` |
| POST | `/api/papers/upload` | `teacher:upload_paper` | none | working (disk write + metadata detect w/ key) | `teacher.py:300-352` |
| POST | `/api/papers/{id}/extract` | `teacher:extract_paper` | none | working (SSE, real extract) | `teacher.py:363-398` |
| POST | `/api/papers/{id}/grade` | `teacher:grade_paper_endpoint` | none | working (SSE, real marking + persist) | `teacher.py:401-476` |
| GET | `/api/papers` | `teacher:list_papers` | none | working (in-process store) | `teacher.py:522-529` |
| GET | `/api/papers/{id}` | `teacher:get_paper` | none | working (404/409) | `teacher.py:532-551` |
| GET | `/api/grading/queue` | `teacher:grading_queue` | none | working | `teacher.py:554-576` |
| GET | `/api/schemes` | `teacher:list_schemes` | none | **partial** — "Pending"/"Your own" stat cards hardcoded `"0"` | `teacher.py:612-637` |
| POST | `/api/schemes` | `teacher:upload_scheme` | none | working (parse+persist, 422 on fail) | `teacher.py:640-667` |
| GET | `/api/quizzes/pools` | `teacher:quiz_pools` | none | **partial** — `ai` pool count hardcoded `0` | `teacher.py:695-729` |
| GET | `/api/quizzes/topics` | `teacher:quiz_topics` | none | working | `teacher.py:732-751` |
| POST | `/api/quizzes/preview` | `teacher:quiz_preview` | none | working (degrades w/o key) | `teacher.py:845-863` |
| POST | `/api/quizzes/generate` | `teacher:quiz_generate` | none | working (503 on failure) | `teacher.py:866-888` |
| GET | `/api/teacher/classes` | `teacher:list_classes` | none | **partial** — no class model; one implicit cohort | `teacher.py:916-939` |
| GET | `/api/classes/{id}` | `teacher:get_class` | none | **partial** — `class_id` ignored; `national` always `None` | `teacher.py:942-997` |
| GET | `/api/teacher/overview` | `teacher:teacher_overview` | none | **partial** — `retention` always `[]` | `teacher.py:1005-1049` |
| GET | `/api/student/overview` | `student:student_overview` | anon stub | working (keyed on "anonymous") | `student.py:185-206` |
| GET | `/api/student/subject/{code}` | `student:student_subject` | anon stub | working (404 if none) | `student.py:212-303` |
| GET | `/api/student/result/{id}` | `student:student_result` | anon stub | **partial** — `theory` always `[]`; integrity reduced to 1 row | `student.py:323-375` |
| POST | `/api/student/correct` | `student:student_correct` | anon stub | **stubbed** — emits one WARNING frame + `[DONE]`, does no work | `student.py:405-431` |
| GET | `/api/student/plan` | `student:student_plan_get` | anon stub | working (`narrative=null`) | `student.py:455-476` |
| POST | `/api/student/plan` | `student:student_plan_post` | **NONE (IDOR)** | working but IDOR | `student.py:479-523` |
| GET | `/api/student/standings` | `student:student_standings` | anon stub | **partial** — every `rank=""`, no leaderboard | `student.py:529-564` |
| POST | `/api/student/onboarding` | `student:student_onboarding` | **NONE (IDOR)** | working but **not persisted** | `student.py:570-602` |

**Infra notes:** DI singletons via `@lru_cache` (`deps.py:18-34`). `JobRegistry` is in-memory, used only by `upload_paper`, and **exposed by no endpoint** (write-only; lost on restart, `jobs.py`). SSE bridges a **process-global** event bus — docstring warns only one stream is safe at a time and worker threads aren't cancelled on disconnect (`sse.py:83-96`). Uploads capped at 25 MB, filenames sanitized (`teacher.py:188-214`).

### CLI — 16 commands (`lemely.app.cli`)

Entry `lemely = lemely.app.cli:main`. Global options: `--config`, `--log-format {auto,json,console}`, `--log-level`, `-v/-q` (mutually exclusive → exit 2), `--json`.

Working (9): `estimate-cost`, `parse-mark-schemes`, `correct-paper`, `predict-grade`, `detect-weaknesses`, `version`, `extract-answers`, `aggregate-subject`, `ui`.
Partial (7):
- `doctor` — `gemini_reachable` is a **hardcoded stub** ("live ping not yet implemented", `cli.py:493-498`).
- `generate-quiz` (non-AI path) — emits **placeholder prompts** "Practice a targeted question on {topic}." (`analytics.py:110`); only `--use-ai` yields real questions.
- `compare-performance`, `study-plan`, `check-integrity`, `teacher-quiz` — payloads have **no Rich renderer**, so human mode falls through to raw JSON dump.
- `measure-accuracy` — **ignores `--json`**, writes bespoke text (`cli.py:730-737`).

Exit codes (`docs/exit-codes.md`) match `runtime/errors.py` exactly for 1–7 and 130.

---

## 7. Frontend (`web/`)

**Route/screen inventory** — React Router v7 `createBrowserRouter`; `/` → `/teacher` (`App.tsx:11-15`).

- **Teacher** (`/teacher`): Overview, Grading, Review, Classes, MarkSchemes, Quizzes.
- **Student** (`/student`): Overview, Subject, PaperResult, CorrectPaper, StudyPlan, Standings, Onboarding, Landing, Directions.
- **15 screens, ~3,018 lines of JSX.**

**Component library:** custom (`components/ui/*`) — `button`/`chip` via `class-variance-authority`, `card`/`primitives` plain. No shadcn/Radix. `Meter` is the only component with a11y attributes.
**Styling:** Tailwind v4 via `@tailwindcss/vite`; OKLCH design tokens scoped per-portal via `[data-portal]` + `@theme inline` (`index.css:24-73`); self-hosted `@fontsource` fonts; `cn() = twMerge(clsx())`.
**State management:** local `useState`/`useRef` + React Router only. No global store.

**⚠️ Data wiring — the headline frontend finding: every screen renders hardcoded mock data.**
- All 15 screens import from `../data` (`student/data.ts` 773 lines, `teacher/data.ts` 591 lines). The files say so: *"Screens render from this file; no live fetch in this run."*
- **`lib/api.ts` is dead code** — a complete typed `fetch`/SSE client whose exports (`request`, `streamActivity`, `ApiError`) are **referenced nowhere** outside the file (grep exit 1).
- **`@tanstack/react-query` is an unused dependency** — `QueryClientProvider` is set up in `main.tsx:8-16` but no `useQuery`/`useMutation` exists anywhere.
- The flagship **`CorrectPaper`** flow is theatre: a `setTimeout` progress animation that navigates to a hardcoded result screen (`CorrectPaper.tsx:34-47`); the "read from paper" MCQ answers are a static array with two intentionally-wrong entries (`data.ts:17-30`).
- The Vite `/api` → `127.0.0.1:8000` proxy exists but is never exercised.

By the harsh rubric, **all 15 screens are STUBBED regardless of visual polish.**

---

## 8. Feature status table

| Feature | Files | Status | Evidence |
|---|---|---|---|
| Deterministic mark-scheme parsing (monolith) | `io/parsers_det.py` | **working** | wired in CLI/Gradio/web; tested (`test_parsers_det.py`) |
| Modular DET parser (staged) | `io/det/*` (10 files) | **absent (dead)** | 0 importers, no `__init__.py`, 0% coverage |
| Gemini mark-scheme fallback + chain | `io/parsers.py` | **working** (needs `--use-gemini` + key) | `cli.py:225,230-239` |
| Answer extraction (Gemini vision) | `io/answer_extraction.py` | **working** (needs key) | `cli.py:509-560` |
| AI marking / correction | `io/correction_ai.py` | **working** (needs key; graceful fallback) | `correction_ai.py:293-296` |
| MCQ deterministic correction | `core/correction.py` | **working** | `correction.py:18-135` |
| Grade prediction + boundaries | `core/analytics.py`, `io/grade_boundaries.py`, `data/grade_boundaries.json` | **partial** — logic real; data has **zero per-paper-variant exact keys** (only 4 subject-level defaults: 0625/0580/0606/0450) → predictions never paper-exact | `grade_boundaries.py:92-105`; JSON verified |
| Weakness detection | `core/analytics.py` | **working** | `analytics.py:35-` |
| Quiz generation (AI) | `io/question_generation.py` | **working** (needs key) | `question_generation.py:55` |
| Quiz generation (non-AI) | `core/analytics.py:106-115` | **stubbed** — placeholder prompt text | `analytics.py:110` |
| Study plan (schedule) | `core/study_plan.py` | **working** | `study_plan.py:13-72` |
| Study plan AI narrative | `io/study_plan_ai.py` | **working** (needs key) | `study_plan_ai.py:45` |
| Plagiarism check | `core/plagiarism.py` | **partial** — only student-vs-model-answer, **not** cross-student | `plagiarism.py:31-61` |
| AI-generated-answer detection | `io/integrity.py` | **partial** — off by default (`ai_detection_enabled=False`) | `config.py:126` |
| History persistence | `io/history_store.py` | **partial** — works but silent-fail load, no lock, no migration | `history_store.py:48-67` |
| Compare performance / aggregate weaknesses | `core/analytics.py` | **working** | `analytics.py:118-214` |
| CLI (16 cmds) | `app/cli.py` | **partial** — 9 working, 7 partial (see §6) | `cli.py` |
| Gradio UI | `app/gradio_app.py` | **working** (but omitted from coverage) | `pyproject.toml:168` |
| FastAPI backend (24 routes) | `web/routers/*` | **partial** — mostly real; 1 stubbed, several hollow fields | §6 |
| Auth / RBAC | `web/deps.py` | **stubbed** — no-op anonymous; IDOR | `deps.py:53-55` |
| React SPA (Teacher/Student) | `web/src/**` | **stubbed** — 100% mock data; API client dead | §7 |
| Cost cap: per-run tokens | `io/gemini.py:163-176` | **working** (per-process) | `test_gemini_client.py:138` |
| Cost cap: monthly USD | `io/gemini.py:171-176` | **stubbed/misleading** — not monthly; resets each process | `gemini.py:175`; reset only in test |
| Accuracy harness | `accuracy/harness.py` | **working** — but **no committed golden fixtures** | `tests/golden/*` = `.gitkeep` only |
| Frontend↔backend integration | — | **absent** | no fetch calls; dev-only proxy |
| Deployment / containerization | — | **absent** | no Docker/IaC/hosting |

---

## 9. Tests & CI

- **Framework:** pytest (installed **9.1.1**) + pytest-cov + coverage, branch coverage on. Style is mixed (`unittest.TestCase` in several files alongside pytest functions).
- **Count:** **308 collected** (306 passed, 2 skipped this run). `addopts`: `-ra -q --strict-markers --cov=lemely --cov-report=term-missing --cov-fail-under=70` (`pyproject.toml:159`).
- **What's asserted (highlights):** deterministic parser (`test_parsers_det.py`, ~51 cases), FastAPI routes via `TestClient` with Gemini mocked (`test_web_teacher.py` 24, `test_web_student.py` 16, `test_web_app.py` 4), CLI dispatch + JSON contract, schema validation, config loading + example-drift guard, grade boundaries, io adapters (all mocked), core domain, renderers.
- **Architecture tests:** `test_import_linter.py` shells out to `lint-imports`; `test_no_print_in_core.py` AST-walks `core/` asserting zero `print()`.
- **Coverage reality — 82.39% is an adjusted figure:** `lemely/app/gradio_app.py` is **omitted** from the denominator (`pyproject.toml:168`); `web/__main__.py` (51 LOC) and `web/services/grading.py` are **0%** covered.
- **Corrections to earlier assumptions (verified):** `respx>=0.21` is declared but **unused** (grep = 0 hits) and not installed; the registered `live` pytest marker is **used nowhere** — the 2 skips come from `@unittest.skip` on `LiveParserTests`, which needs **real PDFs, not an API key** (`test_parsers_det.py:518,531`). `tests/golden/` holds only `.gitkeep` — **no golden fixtures committed**.
- **CI (`.github/workflows/ci.yml`, the only workflow):** `test` job matrix Python **3.12/3.13/3.14**, steps ruff → **ruff format --check** → mypy → lint-imports → pytest; plus a `pre-commit` job on 3.13. Installs `.[dev,ui]` — the **`web` extra and the React SPA are never installed, built, or tested in CI.**

---

## 10. Known breakage

| Item | Severity | Evidence |
|---|---|---|
| **CI red on `main`** — `ruff format --check .` exits 1 (`tests/test_cli_new_commands.py` unformatted) | High | direct run, exit 1; `ci.yml:39-40` |
| `POST /api/student/correct` does nothing (stub) | High | `student.py:405-431` |
| `monthly_usd_ceiling` never tracks a month (per-process reset only in tests) | High | `gemini.py:171-176`, reset at `test_gemini_client.py:89` |
| Grade-boundary table has **zero per-paper-variant exact keys** (only 4 subject-level defaults) → predictions never paper-exact | Medium | `data/grade_boundaries.json` (exact keys `[]`; `_defaults`: 0625/0580/0606/0450) |
| `HistoryStore.load()` swallows all exceptions → corrupt file reads as empty | High | `history_store.py:66-67` |
| oxlint: 6 fast-refresh warnings (non-blocking) | Low | `web` lint run |

Everything else builds, type-checks, and lints clean. mypy strict, ruff check, import-linter, pytest, and `npm run build` all pass.

---

## 11. Dead code, duplication, abandoned approaches

- **CONFIRMED DEAD (largest finding): the entire `lemely/io/det/` package** — 10 modules, ~1,256 LOC (`parser.py`, `rows.py`, `metadata.py`, `reconcile.py`, `tables.py`, `marks.py`, `profiles.py`, `mcq.py`, `columns.py`, `gmp.py`). No app/test imports it (grep `lemely.io.det` outside the dir = 0), it has **no `__init__.py`**, and 0% coverage. It's a completed-but-never-wired refactor (git `53e843a`). The wired monolith `io/parsers_det.py` **ignores `DetParserSettings` entirely** and has **no reconciliation stage**, so `[det_parser]` config is inert and mis-parses aren't caught on the default (`--use-gemini` off) path.
- **`lib/api.ts` (frontend)** — complete typed API/SSE client, imported nowhere → dead.
- **`@tanstack/react-query`** — provider mounted, no consumers → unused dependency.
- **`respx`** — declared dev dep, used nowhere → dead/aspirational.
- **`live` pytest marker** — registered, referenced nowhere.
- **NOT duplicates (cleared):** `parsers.py` (AI parser + chain glue) vs `parsers_det.py` (monolith) are distinct and both used; `schemas.py`/`loose_schemas.py`/`integrity_schemas.py` are three distinct, actively-used modules; `core/correction.py` vs `io/correction_ai.py` are domain-vs-adapter.
- **Minor genuine duplication:** near-identical `_meta`/`_metadata`/`_make_metadata` test helpers across ~6 test files — candidates for a shared conftest fixture.
- **Tooling false positives (do not action):** `tokensave_dead_code` flags `gemini.py:124 _client` (an `@property` used at `:351/:363`); `tokensave_redundancy` 1.0-similarity React pairs are AST-isomorphic but semantically distinct.

---

## 12. AI / LLM integration

- **Provider/SDK:** Google Gemini via `google-genai` (single `GeminiClient`, `io/gemini.py:118,126,133`).
- **Models:** global default `gemini-2.5-flash` (`config.py:35`) with 7 per-task override slots resolved by `model_for()` (mark_scheme, extraction, correction, generation, study_plan, integrity, scan_metadata). Note `correction_borderline` is used for a call/thinking-budget but is **absent from `model_for`'s map** → silently uses the global model.
- **Prompt locations:** versioned modules in `lemely/io/prompts/` — `mark_scheme_parsing.py` (v3, ~27 KB), `answer_extraction.py` (v5), `correction_ai.py` (v4), `integrity.py`, `question_generation.py`, `scan_metadata.py`, `study_plan.py`. The VERSION string is folded into the Gemini disk-cache key.
- **Reliability:** tenacity retry (`max_retries+1` = 4 attempts, exponential backoff 2.0s, only `_TransientError`); one-shot JSON validation-correction re-prompt before `ParseError`; hard `max_output_tokens=65536`; persistent JSON disk cache keyed on model+prompt+file bytes.
- **Escalation:** confidence-based (thinking-retry, then `escalation_model`) is fully coded but **inert by default** (`escalation_model=None`; no `correction_borderline` thinking budget).
- **Cost controls:**
  - `per_run_token_ceiling` — **works** as a per-process cumulative token cap (`gemini.py:163-170`; test at `test_gemini_client.py:138`).
  - `monthly_usd_ceiling` — ⚠️ **misnomer.** Enforced against a process-lifetime global reset only by `_reset_process_counters()`, which is called **solely from a test**. Each CLI run starts at $0; no persistence → **no real monthly/cross-run cap.** Error text even says "this process" (`gemini.py:175`).
  - Both default `None` and are commented out in `lemely.toml.example` → **no cost guard active out of the box.**

---

## 13. Git reality

- **102 commits**, span **2026-05-17 → 2026-07-30** (~2.5 months). Essentially single-author (Yassin Diab, 100/102). **Bursty cadence** (16 on 05-17, 23 on 05-22, sparse June, 24 on the 07-30 merge day) — not steady daily work.
- **Branches:** `main` (deployable-ish, see below), `feat/web-ui` (merged via PR #2), `phase-2-multi-paper-extraction` (stale, last 06-30), `worktree-phase-1-foundations` (merged via PR #1). Remotes mirror these.
- **PRs:** **0 open.** PR #1 (Phase 1) and PR #2 (web UI + backend + AI features) both **merged**.
- **Is `main` deployable?** It builds, type-checks, and passes tests — **but CI is currently red** (`ruff format --check`), there is **no deploy target**, and the shipped SPA is mock-only. So `main` is *runnable locally* (CLI/Gradio/dev-server) but **not deployable as a product**.
- **CHANGELOG.md is stale** — only documents Phase 1 under "Unreleased"; nothing about the web SPA, FastAPI backend, DET parser, integrity, study plans, or history that landed since. Version pinned at `0.1.0`.

---

## 14. Deployment

**None present.** Verified absent (via `find`, excluding `.venv`/`node_modules`): Dockerfile, docker-compose, `.dockerignore`, Terraform/Bicep/CloudFormation, Procfile, `vercel.json`, `netlify.toml`, `fly.toml`, `render.yaml`.

- **CI/CD:** a single `ci.yml` that gates quality only — no build-artifact, publish, or deploy step; no npm/web steps.
- **Runtime:** backend launched ad-hoc via `python -m lemely.web` (uvicorn, `127.0.0.1:8000`); SPA via `vite`/`vite preview`. **No server serves the built `web/dist/` bundle**, and there is **no CORS** — the SPA's `/api` calls only work through the dev-only Vite proxy (and, per §7, no screen calls the API anyway).
- **Hosting target: undefined.**

---

## Top 15 blockers to shipping (ranked by severity)

1. **No authentication or authorization (CRITICAL).** Every endpoint is anonymous; all 15 teacher routes have no auth dependency; all users share one `"anonymous"` history bucket; `POST /student/plan` and `/student/onboarding` are IDOR-shaped. *`web/deps.py:53-55`, `student.py:479,570`.*
2. **The shipped React UI is 100% fake (CRITICAL).** Every screen renders hardcoded mock data; `lib/api.ts` and react-query are unused. The product a user would see is a design prototype, not a functioning app. *§7.*
3. **No frontend↔backend integration and no production serving (CRITICAL).** No server serves `web/dist/`; no CORS; dev-only proxy. *§14.*
4. **No deployment path at all (CRITICAL).** No Docker/IaC/hosting/CD. *§14.*
5. **`monthly_usd_ceiling` provides no real cost cap (HIGH).** On a paid API, the advertised monthly spend cap resets every process and never persists — unbounded monthly spend is possible. *`gemini.py:171-176`.*
6. **Grade-boundary data has no per-paper granularity (MEDIUM–HIGH).** For an "accuracy-first" grading tool, the boundary table has **zero per-paper-variant exact entries**; only coarse subject-level defaults exist (0625/0580/0606/0450). Since CAIE boundaries move every session, every prediction uses an averaged fallback and is never session-accurate. *`data/grade_boundaries.json` (verified: exact keys `[]`).*
7. **CI is red on `main` (HIGH).** `ruff format --check` fails; the merged branch does not pass its own gate. *`ci.yml:39-40`.*
8. **`POST /student/correct` is a stub (HIGH).** The student "correct my paper" path emits a warning and does nothing. *`student.py:405-431`.*
9. **Silent data-loss risk in `HistoryStore` (HIGH).** `load()` swallows all exceptions → corrupt/drifted files read as empty; no file locking; no schema versioning/migration. *`history_store.py:48-67`.*
10. **~1,256 LOC of dead parser code + inert config (MEDIUM-HIGH).** The cleaner `io/det/` package is orphaned; the wired monolith ignores `DetParserSettings` and has **no mark reconciliation**, so silent mis-parses aren't caught when `--use-gemini` is off. *§11.*
11. **`GEMINI_API_KEY` env-mapping trap (MEDIUM).** Unprefixed key works for CLI/Gradio but leaves the web portal degraded/503; only `LEMELY_GEMINI_API_KEY`/TOML reaches `settings`. No `.env.example` to warn users. *§5.*
12. **Hollow backend fields masquerading as features (MEDIUM).** `retention=[]`, `theory=[]`, ignored `class_id`, empty `rank`, hardcoded `0` counts — endpoints look implemented but return placeholders. *§6.*
13. **React SPA has zero CI coverage (MEDIUM).** No build/lint/typecheck/test of `web/` in CI; regressions ship undetected. *§9.*
14. **Coverage headline overstates reality (MEDIUM).** 82% excludes Gradio (`omit`) and leaves `web/__main__.py`, `web/services/grading.py` at 0%; no committed golden fixtures for the accuracy harness. *§9.*
15. **Operational rough edges (MEDIUM/LOW).** SSE bus is process-global (one safe concurrent stream; no cancel on disconnect); `JobRegistry` is write-only/in-memory; `doctor`'s Gemini ping is stubbed; two drifting lockfiles; stale CHANGELOG. *§6, §12, §1, §13.*

---

*End of dossier. All command results reproducible from a `.venv` with `.[dev,ui,web]` installed and `web/node_modules` present.*
