# Lemely Production Hardening — Design Spec

**Date:** 2026-05-17
**Author:** Yassin Diab (lemelyig@gmail.com)
**Status:** Approved — ready for implementation planning
**Revised:** 2026-05-22 — multi-paper-type extraction, AI correction for non-MCQ, subject-level aggregation

---

## Domain model: a CAIE subject is a set of papers

A Cambridge IGCSE / O-Level / A-Level **subject** is graded as a *weighted combination of multiple papers* — not a single exam. A typical science subject has three components:

| Paper | Type | Length | Typical max | Question shape |
|---|---|---|---|---|
| Paper 2 | MCQ | ~45 min | 40 | A/B/C/D per question |
| Paper 4 | Theory / Structured | 1h15–2h | 80 | Short answers, calculations, explanations, diagrams, graphs, levels-based extended responses |
| Paper 6 | Alternative to Practical (ATP) | ~1h | 40 | Experimental design, data analysis, error identification, diagrams |

Maths splits into non-calculator + calculator papers; languages add listening/reading/writing/speaking components; computer-science papers are theory + programming. Coursework and oral components exist for some subjects but are out of scope (no scan to extract from).

A **paper** is the unit of correction (one mark scheme, one scan, one `CorrectionResult`). A **subject** is the unit of grade prediction (sum of awarded marks across all papers a student sat in the same subject + session, against CAIE-style boundaries).

This shapes everything downstream: extraction must produce per-part answers for any question type the mark scheme defines (not just MCQ letters); correction must mark theory/ATP responses against rubrics where the question is not MCQ; the UI must surface both per-paper and per-subject views.

## Summary

Take the Week 1/2 MVP from a working CLI/Gradio prototype to a hardened production-grade single-user tool. Same problem domain (CAIE mark-scheme migration, paper correction across MCQ/theory/ATP, weakness analytics, subject-level grade prediction, quizzes), but with three install paths (`pipx`, source clone, Docker), strict configuration, structured logging, documented exit codes, enforced layered architecture, AI as a first-class production dependency (vision-based scanned-answer extraction, rubric-based correction for non-MCQ questions, interactive AI-marked quizzes), and a CI/release pipeline.

The deterministic core — MCQ correction against parsed mark schemes, weakness aggregation, grade-boundary arithmetic — remains the trust anchor. AI handles everything around it: parsing raw mark-scheme PDFs, extracting student answers from scanned papers of any type, marking non-MCQ responses against the mark scheme's `answer_points` / `level_descriptors` / `drawing_criteria` / rubrics, generating quizzes targeted to student weaknesses, and marking written quiz responses. AI-marked outcomes carry a `marker_source: "ai"` flag and a confidence score so teachers can distinguish them from deterministic results.

## Goals

1. **Hardened, distributable single-user tool** — runs identically from `pipx install lemely[ui]`, a source clone, or `docker run lemely`.
2. **AI as a first-class production feature** — vision OCR for scanned student papers, AI-generated and AI-marked quizzes, with cost-guard / retry / cache / structured logging on every call.
3. **Structural enforcement of architecture** — pure/IO/app/runtime layering is mechanical via `import-linter`; stdout/stderr discipline mechanical via ruff `T20`; type drift caught by mypy strict.
4. **Honest production surface** — documented exit codes, `lemely doctor`, structured logs, secret redaction, healthcheck, lockfile, semver releases.

## Non-Goals

- Multi-tenant, multi-user, or SaaS deployment.
- Persistent database — `outputs/` filesystem is the source of truth.
- Authentication (Gradio is localhost-only by default; exposure is the user's reverse-proxy concern).
- Mobile / iOS app.
- Real-time collaboration.

---

## Architecture

### Package layout

Rename `lemely_mvp` → `lemely`. Reorganise by responsibility into four subpackages:

```
lemely/
  __init__.py            # public re-exports + __version__ via importlib.metadata
  core/                  # PURE LOGIC — no disk, no network, no env
    __init__.py
    schemas.py           # All Pydantic models (correction + quiz + extraction)
    correction.py        # Deterministic MCQ correction
    analytics.py         # Weakness aggregation, grade prediction
  io/                    # TOUCHES DISK / EXTERNAL APIS
    __init__.py
    gemini.py            # Shared genai.Client factory + retry/backoff/cost-guard/cache
    metadata.py          # CAIE filename parsing
    mark_schemes.py      # Library indexing + batch processing
    parsers.py           # Gemini mark-scheme parser (existing)
    answer_extraction.py # NEW — Gemini vision extractor for scanned papers (any paper type)
    correction_ai.py     # NEW — AI rubric marker for non-MCQ questions; hybrid orchestrator
    subject.py           # NEW — multi-paper aggregation into SubjectResult
    quiz_generation.py   # NEW — Gemini quiz generator
    quiz_marking.py      # NEW — Hybrid deterministic/AI quiz marker
    loose_schemas.py     # was models/mark_scheme.py — disk-read JSON shape
    prompts/             # was prompts/ — Gemini prompt strings
      __init__.py
      mark_scheme_parsing.py
      answer_extraction.py
      quiz_generation.py
      quiz_marking.py
  app/                   # USER-FACING ENTRYPOINTS
    __init__.py
    cli.py               # click-based CLI
    renderers.py         # Rich-rendered human output for CLI
    gradio_app.py        # build_app(), launch()
    gradio_callbacks.py  # Pure callback functions (testable without gradio)
    html_report.py       # Jinja-rendered downloadable accuracy reports
  runtime/               # CROSS-CUTTING INFRASTRUCTURE (new)
    __init__.py
    config.py            # pydantic-settings + TOML loader
    logging.py           # structlog setup, TTY auto-detect, secret redaction
    errors.py            # Exception hierarchy + exit-code mapping
tests/
  unit/
    core/  io/  runtime/
  integration/
  architecture/
  live/                  # @pytest.mark.live — skipped by default
  fixtures/
```

### Dependency rules (enforced by `import-linter`)

- `core` depends on **nothing internal** — pure functions of Pydantic models.
- `io` may depend on `core` + `runtime`.
- `app` may depend on `core` + `io` + `runtime`.
- `runtime` depends on **nothing internal**.

This is the same boundary the MVP follows informally; the refactor makes it structural and CI-enforced. Violations break the build, not just code review.

---

## Configuration (`lemely/runtime/config.py` + `lemely.toml`)

Single `Settings` class via `pydantic-settings`. Precedence: **CLI flags → env vars (prefix `LEMELY_`) → `.env` → `lemely.toml` → defaults**. Secrets are env/`.env` only — never in TOML.

```python
class GradioSettings(BaseModel):
    host: str = "127.0.0.1"           # localhost-only by default
    port: int = 7860
    max_file_size_mb: int = 25

class PathsSettings(BaseModel):
    sources_dir: Path = Path("Sources")
    output_dir: Path = Path("outputs")
    cache_dir: Path = Path(".lemely-cache")
    # Parsed JSON co-locates next to PDFs (not configurable — H1)

class LoggingSettings(BaseModel):
    level: Literal["DEBUG","INFO","WARNING","ERROR"] = "INFO"
    format: Literal["auto","json","console"] = "auto"

class GeminiSettings(BaseModel):
    model: str = "gemini-2.5-flash"
    max_retries: int = 3
    backoff_seconds: float = 2.0
    monthly_usd_ceiling: float | None = None  # None = no ceiling
    per_run_token_ceiling: int | None = None

class GradingSettings(BaseModel):
    grade_boundaries: list[GradeBoundary] = DEFAULT_CAIE_BOUNDARIES

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LEMELY_",
        env_nested_delimiter="__",
        env_file=".env",
        toml_file=("lemely.toml", Path.home() / ".config" / "lemely" / "lemely.toml"),
        extra="forbid",
    )
    gradio: GradioSettings = GradioSettings()
    paths: PathsSettings = PathsSettings()
    logging: LoggingSettings = LoggingSettings()
    gemini: GeminiSettings = GeminiSettings()
    grading: GradingSettings = GradingSettings()
    gemini_api_key: SecretStr | None = None   # env/.env only — REQUIRED in prod
```

**TOML discovery order:** `--config <path>` → `./lemely.toml` → `$XDG_CONFIG_HOME/lemely/lemely.toml`. First match wins; no merging.

**Env nesting:** `LEMELY_GRADIO__PORT=8080` overrides `gradio.port`.

**Validation:** `extra="forbid"` everywhere. Unit-tested with typo'd keys, conflicting env+TOML, missing required (`gemini_api_key`).

A `lemely.toml.example` ships in the repo, fully commented, documenting every key with its default. Generated from the `Settings` schema in a test-enforced way (the test rebuilds the example and fails if it drifts).

---

## Logging (`lemely/runtime/logging.py`)

`structlog` configured once at process start (CLI `main`, Gradio `launch`).

- **Output target:** stderr only. Stdout is whatever the command emits; only `--json` mode imposes a parseability contract.
- **Format selection:**
  - `auto` (default) — JSON if stderr is not a TTY, Rich-rendered console otherwise.
  - `json` — force structured JSON.
  - `console` — force Rich-rendered.
- **Level:** from `LoggingSettings.level`. `--verbose` / `-v` → DEBUG; `--quiet` / `-q` → WARNING.
- **Bound context per command:** every CLI invocation binds `command` + `run_id = uuid4().hex[:8]`. Sub-loggers inherit.
- **Stdlib bridge:** route third-party `logging.getLogger(...)` output (Gradio, PyMuPDF, httpx) through structlog. No duplicate output.
- **Secret redaction:** processor redacts `api_key`, `gemini_api_key`, `password`, `token`, `authorization` at any depth before rendering. Unit-tested.

Test enforcement: a pytest fixture for every CLI command running with `--json` asserts stdout is parseable JSON validating the documented schema. No assertion on plain (human) stdout — that is intentionally free-form.

---

## Errors & exit codes (`lemely/runtime/errors.py`)

```python
class LemelyError(Exception):
    exit_code: int = 1

class UsageError(LemelyError):           exit_code = 2  # bad CLI args
class ConfigError(LemelyError):          exit_code = 3  # bad TOML/env, missing api key
class InputError(LemelyError):           exit_code = 4  # malformed user-supplied file
class NotFoundError(LemelyError):        exit_code = 5  # file/mark-scheme/topic missing
class ParseError(LemelyError):           exit_code = 6  # PDF/JSON parse failure
class ExternalServiceError(LemelyError): exit_code = 7  # Gemini API failure
class PartialFailureError(LemelyError):  exit_code = 1  # batch had per-item errors
```

CLI top-level handler maps every `LemelyError` to its declared exit code; `KeyboardInterrupt` → 130; anything else → 1 with stack at DEBUG. Documented in `docs/exit-codes.md` and surfaced under `lemely --help`.

**Batch `--on-error` policy:**
- `parse-mark-schemes` defaults to `continue` — per-PDF errors land in result `errors: [...]`; exit 0 on full success, 1 (`PartialFailureError`) on partial.
- All single-item commands default to `fail`.
- Both flags accept `continue|fail` for explicit override.

---

## CLI surface (`lemely/app/cli.py`, click-based)

### Global options

```
--config PATH
--json / --no-json            (default human-friendly Rich output)
--log-format auto|json|console
--log-level DEBUG|INFO|WARNING|ERROR
-v, --verbose                 alias for --log-level DEBUG
-q, --quiet                   alias for --log-level WARNING
--version
```

### Subcommands

| Command | Required | Notable options | Default `--on-error` |
|---|---|---|---|
| `estimate-cost` | `SOURCE_ROOT` | — | n/a |
| `parse-mark-schemes` | `SOURCE_ROOT` | `--output-root`, `--force`, `--use-gemini`, `--gemini-model`, `--on-error` | `continue` |
| `extract-answers` | — | `--mark-scheme PATH`, `--scan PATH`, `--on-error` | `fail` |
| `correct-paper` | — | `--mark-scheme PATH`, `--answers PATH`, `--mcq-only`, `--on-error` | `fail` |
| `aggregate-subject` | `CORRECTION_JSON...` (1..N) | `--subject-code`, `--session`, `--on-error` | `fail` |
| `predict-grade` | `CORRECTION_JSON` | `--on-error` | `fail` |
| `detect-weaknesses` | `CORRECTION_JSON` | `--on-error` | `fail` |
| `generate-quiz` | `CORRECTION_JSON` | `--count`, `--mix balance\|mcq\|writing` | `fail` |
| `mark-quiz-attempt` | — | `--quiz PATH`, `--attempt PATH` | `fail` |
| `ui` | — | `--host`, `--port` *(no `--share` flag)* | n/a |
| `doctor` | — | — | n/a |
| `version` | — | — | n/a |

`--use-gemini` on `parse-mark-schemes` is retained as a per-invocation cost gate: omitting it makes the command a pure validation/index pass over existing JSON (no API calls, free); passing it actually parses missing PDFs via Gemini.

`extract-answers` is paper-type-agnostic: it builds its extraction prompt from the question manifest in the supplied mark scheme, so theory and ATP papers extract free-text / numerical / drawing-description responses per question part (e.g. `1(a)(i)`), while MCQ papers extract single letters. The output schema (`ExtractedAnswers`) is uniform — `answer: str` carries whatever was written.

`correct-paper` routes by question type: MCQ questions take the deterministic path (`core.correction.correct_mcq_answers`); non-MCQ questions are marked by `io.correction_ai` against the mark scheme's `answer_points` / `level_descriptors` / `drawing_criteria` / `plot_requirements` / `marking_guidance`. A paper with mixed types runs both passes and merges results into one `CorrectionResult`. The `--mcq-only` flag skips AI marking entirely (non-MCQ questions emit `marker_source: "missing"` with zero marks). Non-MCQ marking requires a valid `gemini_api_key`; absence is a `ConfigError` unless `--mcq-only` is set.

`aggregate-subject` takes one or more per-paper `CorrectionResult` JSON files (all sharing the same `subject_code` + session) and produces a `SubjectResult`: summed awarded/maximum marks, weighted percentage, predicted subject grade against CAIE-style boundaries, and a weakness report aggregated across components. Mismatched subject codes or sessions are a `UsageError`.

### Rendering (human mode, `app/renderers.py`)

- `estimate-cost` → Rich totals table.
- `parse-mark-schemes` → Rich progress bar + summary table.
- `correct-paper` → grade banner + per-question table (color-coded) + weakness summary.
- `extract-answers` → table of `(question, extracted, confidence)`.
- `predict-grade`, `detect-weaknesses` → compact table.
- `generate-quiz` → quiz preview list.
- `doctor` → checklist with ✓/✗ per check. Specifically checks: config file loads and validates; `gemini_api_key` is set; `paths.sources_dir` exists and is readable; `paths.output_dir` is writable (or creatable); `paths.cache_dir` is writable; `gradio` extra is importable (warn-only, not fatal); the configured Gemini model responds to a 1-token ping (skippable with `--no-network`).

### JSON mode

`--json` preserves the existing `model.model_dump(mode="json")` shape. No breaking changes to the JSON contract. CI test asserts every command emits parseable JSON validating its documented schema.

### Shell completion

`lemely --install-completion bash|zsh|fish` (click extra).

---

## Gradio app (`lemely/app/gradio_app.py`)

Real working MVP — full teacher workflow, not a demo surface.

### Launch defaults (enforced, not just documented)

- `server_name = settings.gradio.host` (default `127.0.0.1`)
- `server_port = settings.gradio.port`
- `share = False`, **hard-coded** — no CLI flag, removed entirely.
- `show_api = False`
- `max_file_size = f"{settings.gradio.max_file_size_mb}mb"`
- `allowed_paths = [settings.paths.sources_dir.resolve()]`
- Startup warning logged at WARNING level when `server_name != "127.0.0.1"`.

### Tabs

1. **Library** — browse mark-scheme PDFs, filter by subject/session/paper. Per-row "Parse" button for missing JSON; bulk "Parse all missing". Single concurrent parse job (Gradio queue `concurrency_count=1`). Cancel button. Job survives tab close for process lifetime; killed process loses in-progress work.

2. **Correct a paper** — only file upload in the app.
   - Select mark scheme (dropdown, typeahead from library). The selected scheme determines paper type; the UI adapts.
   - Upload **scanned student paper** (PDF / PNG / JPG, multi-page allowed, up to `max_file_size_mb`).
   - **Extract** → `GeminiAnswerExtractor` → editable table `(question_id, answer, confidence, marker_hint)`. For MCQ papers the `answer` column is constrained to A/B/C/D + blank. For theory/ATP papers the cells are free-text (single line for short answers, expandable multi-line for long responses; calculations show as text with unit hint). The table sorts by `question_id` following the mark scheme's hierarchical IDs (`1`, `1(a)`, `1(a)(i)` …).
   - Teacher reviews/edits low-confidence rows. Rows below 0.7 confidence are highlighted; teachers must confirm or edit before grading.
   - **Grade** → hybrid `correct_paper` (deterministic for MCQ questions, `io.correction_ai` for non-MCQ).
   - Result panel: per-paper grade banner, per-question table (with `marker_source` column showing ✓ deterministic / 🤖 AI / — missing), weakness summary, paper-level grade prediction.
   - Save → writes `outputs/<subject_code>/<session>/<paper_code>__<YYYY-MM-DD-HHMMSS>/` containing `extracted_answers.json` (audit trail), `reviewed_answers.json`, `accuracy_report.json`. The session directory groups all papers of the same subject + session.
   - Download JSON / Download HTML report.

3. **Subject result** — assemble a multi-paper subject grade.
   - Source: pick subject_code + session from the dropdown (built from `outputs/`).
   - Lists all per-paper `CorrectionResult`s in that subject+session. Allows including/excluding individual papers.
   - **Aggregate** → runs `io.subject.aggregate_subject` → `SubjectResult` (sum awarded/max, weighted percentage, predicted subject grade, merged weakness report).
   - Save → `outputs/<subject_code>/<session>/subject_result__<timestamp>.json`.
   - Download JSON / Download HTML report (rolls up per-paper tables and a subject banner).

4. **Past results** — directory browser of `outputs/`. Sortable by date / subject / paper code / subject_result. Click any row to re-render its saved `AccuracyReport` or `SubjectResult` identically to Tabs 2/3. Delete with confirmation. Nested expander per paper shows its quizzes and attempts.

5. **Quiz** — interactive, solvable in-UI.
   - Source: dropdown of past corrections in `outputs/` only. **No upload.**
   - Generate quiz → Gemini call → mixed-type questions targeting weak topics.
   - Distribution preset: `balance` (default) / `mcq` / `writing`. Count slider (default 8).
   - Quiz renders **in-place** with type-appropriate widgets (radio for MCQ, single-line text for short answer, multi-line + char counter for long form). Each shows marks + topic.
   - **Submit** marks every question:
     - MCQ → deterministic against `correct_option` (instant). `marker_confidence` is always `1.0`.
     - Short answer → deterministic match against `acceptable_variants` first (normalised case/whitespace) → instant on hit; else Gemini rubric judgment.
     - Long form → batched Gemini call with rubric (one call per quiz submission carrying all written-response questions).
     - Each `QuestionMark` records `marker_source` (`deterministic` | `ai` | `failed`) + `marker_confidence`.
     - **Per-question failure isolation:** if the Gemini marking call fails for the whole batch, all AI-marked questions get `marker_source = "failed"`, `marks_awarded = 0`, `feedback = "<reason>"`, and `marker_confidence = 0.0`. Deterministic marks still apply. The result panel surfaces a "Some questions could not be marked — retry?" banner with a single retry button that re-marks only the failed questions.
   - Per-question feedback rendered inline; overall score banner.
   - "Generate follow-up quiz" button (targets `derived_weaknesses` from this attempt).
   - Saves `quiz.json`, `quiz_attempt.json`, `quiz_result.json` under `outputs/<subject>/<paper_code>__<correction_timestamp>/quizzes/<quiz_timestamp>/`.

6. **Settings (read-only)** — table of every effective setting with value + source (`default` / `lemely.toml` / `env` / `cli`). `gemini_api_key` masked. Critical for debugging "why isn't my config taking effect."

### No uploads anywhere else

No paste-text answers. No upload weakness JSON. No upload quiz JSON. The CLI is the scriptable seam; the UI is the integrated workflow.

### Callback discipline

All callbacks live in `gradio_callbacks.py` as pure functions of primitives + `Settings`, returning primitives / `Path`s / dicts. Unit-testable without `gradio`. `gradio_app.py` is the thin wiring file.

---

## Gemini integration layer (`lemely/io/gemini.py`)

Shared infrastructure for every AI call in `lemely.io`.

- **Client factory** — single `genai.Client` constructed lazily from `Settings.gemini_api_key`. Re-used across calls in a process.
- **Retry/backoff** — `tenacity`-based; configurable max retries and base backoff. Only retries transient errors (`5xx`, network, rate limit). Each retry logged with attempt number.
- **Cost guard** — per-process token + USD ceiling from `GeminiSettings`. Raises `ExternalServiceError` (exit 7) when exceeded. Token counts and USD estimates structured-logged per call.
- **Persistent cache** — keyed on `(model, prompt_hash, input_files_hash)`, stored under `paths.cache_dir`. Stored as JSON; small enough that filesystem is fine. Cache hits are free + instant. Invalidated by prompt version (each prompt module exposes a `VERSION` constant included in the hash).
- **Structured logging** — every call emits one INFO event with `model`, `input_tokens`, `output_tokens`, `latency_ms`, `usd_cost`, `cache_hit`, `request_hash`.
- **Response-schema enforcement** — every consumer passes a Pydantic schema; the client uses Gemini's structured-output feature so responses validate against that schema before returning. Validation failures retry once with a "your previous response did not match the schema" prompt addendum, then raise `ParseError`.

### Consumer modules

| Module | Schema | Default model | Cache key includes |
|---|---|---|---|
| `parsers.py` (mark scheme PDF → JSON) | `MarkScheme` (loose) | `gemini-2.5-flash` | file content hash, prompt version |
| `answer_extraction.py` (scan → answers, any paper type) | `ExtractedAnswers` | `gemini-2.5-flash` | scan content hash, MS question manifest hash, prompt version |
| `correction_ai.py` (non-MCQ question + student answer → mark) | `AIMarkResponse` | `gemini-2.5-flash` | question subtree hash, student answer hash, prompt version |
| `quiz_generation.py` (weakness → quiz) | `Quiz` | `gemini-2.5-flash` | correction id, count, mix, prompt version |
| `quiz_marking.py` (attempt → result) | `QuizResult` | `gemini-2.5-flash` | quiz id, responses hash, prompt version |

Every cache key includes the corresponding prompt module's `VERSION` constant, so bumping a prompt invalidates the cache automatically.

---

## New schemas (in `lemely/core/schemas.py`, all `extra="forbid"`)

- `ExtractedAnswer` — `question_id` (hierarchical, matches `Question.id` in the mark scheme), `answer: str` (the student's response: MCQ letter, free text, calculated value+unit, or description of a drawing), `confidence: float` (0–1), `source_region: str | None` (optional positional hint for debugging)
- `ExtractedAnswers` — `paper_id`, `source_scan: str`, `answers: list[ExtractedAnswer]`
- `AIMarkResponse` — `awarded_marks: int`, `confidence: float`, `matched_point_ids: list[str]`, `feedback: str`. Returned by `correction_ai` per-question; merged into `CorrectedQuestion`.
- `SubjectResult` — `subject_code`, `session_month`, `session_year`, `paper_results: list[CorrectionResult]`, computed `awarded_marks`/`maximum_marks`/`percentage`/`grade`, aggregated `weaknesses: WeaknessReport`, `needs_teacher_review`.
- `QuizQuestion` — discriminated union on `type` (`mcq` | `short_answer` | `long_form`); each variant has type-specific fields (`options`/`correct_option` for MCQ, `reference_answer`/`acceptable_variants`/`rubric` for short, `reference_answer`/`rubric` for long).
- `Quiz` — `id`, `generated_at`, `source_correction_id`, `target_topics`, `questions`
- `QuizResponse` — `question_id`, `student_answer` (typed per question)
- `QuizAttempt` — `quiz_id`, `started_at`, `submitted_at`, `responses`
- `QuestionMark` — `question_id`, `marks_awarded`, `max_marks`, `feedback`, `marker_confidence`, `marker_source: Literal["deterministic","ai","failed"]`
- `QuizResult` — `quiz_id`, `attempt_id`, `marks`, `total_awarded`, `total_max`, `percentage`, `derived_weaknesses`, `suggested_followup_topics`

### Extension to `CorrectedQuestion`

The existing `CorrectedQuestion` gains three optional fields to carry AI-marking metadata uniformly across MCQ + non-MCQ paths:

- `marker_source: Literal["deterministic","ai","missing"]` (default `"deterministic"`) — `"missing"` when `--mcq-only` is set and the question is non-MCQ.
- `feedback: str | None` — short teacher-readable explanation (populated only for AI-marked questions).
- `matched_point_ids: list[str]` — IDs of `AnswerPoint`s / `LevelDescriptor`s / `DrawingCriterion`s that earned marks (populated only by AI marker).

These extensions are backwards-compatible: existing deterministic MCQ paths leave the new fields at their defaults.

---

## Packaging (`pyproject.toml`)

Replaces `requirements.txt`. PEP 621 metadata + `hatchling` build backend.

- **Core install:** `pipx install lemely` → CLI only.
- **UI install:** `pipx install 'lemely[ui]'` → adds `gradio`; `lemely ui` works.
- **Dev install:** `pip install -e '.[ui,dev]'` from a clone.
- **Console script:** `[project.scripts] lemely = "lemely.app.cli:main"`.
- **Pinning:** direct deps in compatible-major ranges; `requirements.lock` produced via `uv pip compile`, committed, CI-verified in sync.
- **Version source:** `lemely/__init__.py` reads `importlib.metadata.version("lemely")`.

---

## Docker

Multi-stage, slim, `~80MB` final.

- Builder stage: `python:3.13-slim` + `uv`, installs from `requirements.lock`.
- Runtime stage: `python:3.13-slim`, non-root `lemely` user, copies installed packages + console script.
- Default env: `LEMELY_LOGGING__FORMAT=json`, `LEMELY_PATHS__SOURCES_DIR=/data/Sources`, `LEMELY_PATHS__OUTPUT_DIR=/data/outputs`, `LEMELY_GRADIO__HOST=0.0.0.0` (exposure warning still fires).
- `VOLUME ["/data"]`, `EXPOSE 7860`.
- `HEALTHCHECK CMD lemely doctor || exit 1`.
- `ENTRYPOINT ["lemely"]`, `CMD ["--help"]`.

A minimal `docker-compose.yml` ships in the repo; `GEMINI_API_KEY` required via env (`${GEMINI_API_KEY:?…}`).

---

## CI & quality tooling

### Local gates (`.pre-commit-config.yaml`)

`ruff` (with `--fix`) + `ruff-format` + standard pre-commit-hooks (trailing whitespace, EOF, YAML/TOML check, merge conflicts, private-key detection) + `mypy lemely` + `lint-imports` (both as local hooks).

### `ruff` configuration

`target-version = "py312"`, `line-length = 100`. Lint selection: `E, W, F, I, B, UP, SIM, TCH, RUF, ANN, D, T20, S`. `T20` (no `print()` in source) is the structural enforcement of the stderr discipline; `tests/` ignores it. `lemely/app/cli.py` ignores `T20` (click's CLI handlers can print).

### `mypy` strict

`strict = true`, `warn_unreachable = true`, `warn_redundant_casts = true`, `disallow_any_explicit = true`, `pydantic.mypy` plugin. External stubs missing for `gradio.*`, `fitz.*` (ignored).

### `import-linter`

Layers contract: `app → io → core, runtime` (and `runtime` independent). Plus `core is pure` forbidden contract. Violations break CI.

### `pytest`

`addopts = "-ra -q --strict-markers --cov=lemely --cov-report=term-missing --cov-fail-under=85"`. `@pytest.mark.live` skipped by default.

### GitHub Actions (`.github/workflows/ci.yml`)

- `test` job: matrix Python 3.12 / 3.13 / 3.14 — runs `ruff check`, `ruff format --check`, `mypy`, `lint-imports`, `pytest`.
- `docker` job: builds image, smoke-tests `--version`, `doctor`, `--help`.
- `release` job: triggered on `vX.Y.Z` tags — publishes wheel/sdist to PyPI (trusted publishing, no token) + pushes Docker image to GHCR.

`Makefile` shortcuts: `make install | dev | test | lint | typecheck | imports | lock | pre-commit | fmt | docker | docker-run | clean`.

---

## Testing strategy

### Tier 1 — Unit tests (`tests/unit/`)

Coverage target ≥ 90 % on `lemely.core`; ≥ 85 % on `lemely.io` and `lemely.runtime`. Every Gemini call mocked at the `httpx` layer via `respx`.

New unit-test files for: quiz schemas, Gemini client (retry/cost/cache), answer extraction, quiz generation, quiz marking, config (precedence + forbid + secret redaction), logging (TTY auto-detect + redaction + stdlib bridge), errors (exit-code mapping).

### Tier 2 — Integration tests (`tests/integration/`)

End-to-end CLI and Gradio-callback workflows on real filesystem with fixture PDFs/scans; Gemini still mocked.

Includes: `correct-paper` CLI e2e (both human + `--json`), `extract-answers` CLI e2e, full quiz chain CLI e2e (`generate-quiz → submit → mark-quiz-attempt`), batch `parse-mark-schemes` with mixed valid/invalid PDFs and `--on-error` semantics, Gradio Tab 2 + Tab 4 callback workflows, **stdout JSON-contract test** (every CLI command with `--json` validates against its documented schema), `doctor` failure modes.

### Tier 3 — Architecture tests (`tests/architecture/`)

- `test_import_linter.py` — programmatic invocation, fails CI on contract violation.
- `test_no_print_in_core.py` — AST walk; complements ruff `T20`.
- `test_pyproject_lock_in_sync.py` — compares committed `requirements.lock` against a fresh `uv pip compile`.
- `test_settings_example_in_sync.py` — regenerates `lemely.toml.example` and asserts no diff.

### Tier 4 — Live smoke tests (`tests/live/`, `@pytest.mark.live`)

Skipped by default; run via `pytest --run-live` only when `GEMINI_API_KEY` is set. Separate manually-triggered GHA workflow.

Includes: real Gemini answer extraction on a sample scan, quiz generation, quiz marking (assert good > bad), cost guard enforcement.

### Fixtures (`tests/fixtures/`)

- `mark_schemes/*.json` — small real-shape mark schemes.
- `answers/*.{txt,json}` — clean, malformed, partial.
- `scans/synthetic_bubble_sheet.png` + `tests/fixtures/generate_scans.py` (synthesises bubble sheets for extraction tests).
- `pdfs/two_page_ms.pdf` — minimal real PDF for batch processor.
- `gemini_responses/*.json` — recorded response bodies for `respx` replay.

### Coverage configuration

`branch = true`, `omit = ["lemely/app/gradio_app.py"]` (smoke-tested only — UI assembly coverage gives a false signal; callbacks are unit-tested via `gradio_callbacks.py`).

---

## File list (additive view)

**New files:**

```
pyproject.toml
requirements.lock
Dockerfile
docker-compose.yml
Makefile
.pre-commit-config.yaml
.github/workflows/ci.yml
.github/workflows/live-tests.yml
lemely.toml.example
.env.example
docs/exit-codes.md
docs/contributing.md
CHANGELOG.md
lemely/runtime/__init__.py
lemely/runtime/config.py
lemely/runtime/logging.py
lemely/runtime/errors.py
lemely/io/gemini.py
lemely/io/answer_extraction.py
lemely/io/quiz_generation.py
lemely/io/quiz_marking.py
lemely/io/prompts/answer_extraction.py
lemely/io/prompts/quiz_generation.py
lemely/io/prompts/quiz_marking.py
lemely/app/renderers.py
lemely/app/gradio_callbacks.py
lemely/app/html_report.py
tests/unit/.../*  (mirrors lemely/)
tests/integration/*
tests/architecture/*
tests/live/*
tests/fixtures/*
```

**Renamed / moved:**

```
lemely_mvp/ → lemely/  (full subpackage restructure per Architecture)
models/mark_scheme.py → lemely/io/loose_schemas.py
prompts/__init__.py, prompts/mark_scheme_parsing.py → lemely/io/prompts/...
requirements.txt → REMOVED (replaced by pyproject.toml + requirements.lock)
main.py → REMOVED (console script replaces it)
```

**Edited:**

```
lemely/* — imports updated; click CLI replaces argparse; renderers extracted;
           settings/logging/errors plumbed in; new schemas; new IO modules.
```

---

## Open questions / explicit non-decisions

- **Synthetic bubble-sheet fixture generation** — `generate_scans.py` will use `Pillow` to draw simple multi-question bubble sheets. The fidelity of the synthetic image vs. real scanned papers is a known limitation; live tests cover the real-world gap.
- **Long-form rubric quality** — quality of AI-generated rubrics for long-form questions depends on prompt iteration. Initial release ships with CAIE-style level-of-response rubrics; tuning happens post-launch based on observed marking quality.
- **Cost-guard defaults** — `monthly_usd_ceiling` and `per_run_token_ceiling` default to `None` (no enforcement). Documented as recommended-to-set in `lemely.toml.example`.
- **Concurrency model in Gradio** — single parse job at a time is enforced; Gemini-backed marking calls run sequentially per quiz submission (no inter-question parallelism). Acceptable trade-off for single-user MVP.
- **PyPI publish target** — assumes the `lemely` name is available; if not, fallback name to be chosen at release time.

---

## Out of scope (explicit reminders)

- No DB / persistent server-side state beyond the filesystem.
- No multi-user / auth / RBAC.
- No background worker queue beyond Gradio's in-process queue.
- No telemetry to external services beyond Gemini.
- No mobile / web-app frontend separate from Gradio.

---

## Implementation plan structure (note for writing-plans)

This spec is broad on purpose — it captures the full target shape. The implementation should be decomposed into a phased plan that ships value incrementally and keeps any single phase reviewable. A reasonable phasing:

1. **Phase 1 — Foundations:** package rename + restructure to `lemely/{core,io,app,runtime}`, runtime modules (config, logging, errors), `pyproject.toml` + `requirements.lock`, click-based CLI with renderers covering the *existing* commands only, ruff + mypy + import-linter + pre-commit + CI. No new features; same behaviour, harder shell. All current tests pass after migration.

2. **Phase 2 — Multi-paper-type extraction, correction, and subject aggregation:** `lemely/io/gemini.py` (shared client + retry + cost-guard + cache + schema enforcement); `ExtractedAnswer` / `ExtractedAnswers` / `SubjectResult` schemas; `CorrectedQuestion` extended with `marker_source` / `feedback` / `matched_point_ids`; `lemely/io/answer_extraction.py` (works for MCQ, theory, ATP — prompt is built from the mark scheme's question manifest); `lemely/io/correction_ai.py` (rubric-driven AI marker for non-MCQ + hybrid orchestrator routing MCQ→deterministic, non-MCQ→AI); `lemely/io/subject.py` (paper aggregation into `SubjectResult`); CLI subcommands `extract-answers`, `correct-paper` (updated for hybrid), `aggregate-subject`; Gradio Tab 2 reshaped around the scan → extract → review → grade flow with paper-type-aware editable cells; Gradio Tab 3 added for subject result assembly. No quiz changes yet.

3. **Phase 3 — Interactive quizzes:** quiz schemas (discriminated unions for question types), `quiz_generation.py`, `quiz_marking.py` (deterministic fast-path + AI fallback), CLI subcommands (`generate-quiz` AI version, `mark-quiz-attempt`), Gradio Tab 5 interactive flow, Past Results nested quiz expander, follow-up quiz generation.

4. **Phase 4 — Packaging & release:** Dockerfile + compose, GHCR release workflow, PyPI trusted publishing, `CHANGELOG.md`, `docs/exit-codes.md`, `docs/contributing.md`, smoke-test workflow.

Each phase produces a working, releasable artefact; nothing in a later phase blocks shipping an earlier one. The writing-plans skill should adopt this phasing (or propose a better one) and produce one executable plan per phase.

---

## Acceptance criteria

- `pipx install 'lemely[ui]'` from a built wheel produces a working `lemely` command on PATH.
- `docker run lemely doctor` succeeds with a valid `GEMINI_API_KEY` env, fails (exit 3) without one.
- CI green on Python 3.12 / 3.13 / 3.14 with: ruff, ruff-format, mypy strict, import-linter, pytest (≥ 85 % coverage), Docker build + smoke tests.
- `lemely correct-paper --mark-scheme ... --answers ...` produces identical JSON to the current MVP under `--json`, and a Rich table under default human mode.
- `lemely ui` launches Gradio on `127.0.0.1:7860`; all five tabs are functional end-to-end against real `Sources/` data and a valid `GEMINI_API_KEY`.
- Every documented exit code is reachable by a corresponding CLI failure mode and covered by an integration test.
- `import-linter` would fail CI if a `lemely.core` module imported from `lemely.io`.
- `lemely.toml.example` regenerates identically to the committed copy (drift test).
