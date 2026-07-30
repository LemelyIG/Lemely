export const meta = {
  name: 'lemely-audit',
  description: 'Read-only per-area inventory of the Lemely repo for a factual audit dossier',
  phases: [
    { title: 'Analyze', detail: '7 parallel read-only analyzers, one per area, evidence-bound' },
  ],
}

// ---- Shared structured-output schema ----
const SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    markdown: {
      type: 'string',
      description: 'Polished GitHub-flavored markdown for this audit area. Use tables where asked. Every non-obvious claim must cite file:line evidence inline. Be harsh and factual: "renders hardcoded data" = stubbed, not working.',
    },
    key_facts: {
      type: 'array',
      description: 'Discrete verified facts with evidence.',
      items: {
        type: 'object',
        additionalProperties: false,
        properties: {
          claim: { type: 'string' },
          evidence: { type: 'string', description: 'file:line or command output that proves it' },
          confidence: { type: 'string', enum: ['verified', 'unverified'] },
        },
        required: ['claim', 'evidence', 'confidence'],
      },
    },
    stubs_or_gaps: {
      type: 'array',
      description: 'Things that are stubbed, partial, hardcoded, or absent (with evidence).',
      items: { type: 'string' },
    },
  },
  required: ['markdown', 'key_facts', 'stubs_or_gaps'],
}

const GROUND = `
REPO: /home/sico/Code/Lemely (branch main @ 24b6c0f, in sync with origin/main). Python venv at .venv (activate: source .venv/bin/activate). 207 tracked files.
Read-only audit — DO NOT write, edit, format, or run any mutating command. Read/grep/ls/tokensave/pytest-collect only.
Tokensave is initialised: PREFER tokensave_context / tokensave_search for code structure; use Read + Bash(grep/ls/wc) to verify exact specifics (routes, decorators, line numbers). Cite file:line for every non-obvious claim; mark anything you could not verify as "unverified".
Already-verified baseline (do NOT re-run, just reference): pytest = 306 passed / 2 skipped / coverage 82.39% (gate 70%); ruff check clean; mypy clean (77 files); import-linter 2 contracts kept; ruff format --check FAILS on tests/test_cli_new_commands.py (exit 1); web build exit 0 (486KB bundle); oxlint 6 fast-refresh warnings; auth is an anonymous stub in lemely/web/deps.py; no Dockerfile/compose/IaC; no .env.example.
Architecture: lemely/core (pure domain) < lemely/io (adapters+Gemini) < lemely/app (CLI+Gradio); lemely/runtime (config/logging/errors leaf); lemely/web (FastAPI); lemely/accuracy; lemely/data. Separate SPA in web/ (React 19 + Vite 8 + TS 6 + Tailwind 4).
`

phase('Analyze')

const tasks = [
  {
    label: 'backend-api-auth',
    prompt: `${GROUND}
AREA: FastAPI backend — lemely/web/ (app.py, __main__.py, deps.py, jobs.py, sse.py, schemas*.py, services/grading.py, routers/{meta,student,teacher}.py).
Produce:
1. A COMPLETE endpoint inventory TABLE: | method | path | router:function | auth requirement | request body | response model | status (working/partial/stubbed) | evidence(file:line) |. Read every @router decorator in routers/*.py. teacher.py is ~1080 lines and student.py ~600 — enumerate ALL routes, do not sample.
2. Auth & session model: exactly what get_auth_context returns, AuthContext shape, how role/user_id are (not) enforced. Quote deps.py.
3. DI singletons (get_settings/get_history_store/etc.), background jobs (jobs.py), SSE (sse.py), grading service (services/grading.py), app mounting/CORS/static (app.py, __main__.py).
4. For each endpoint judge harshly: does it compute real results from stores/Gemini, or return hardcoded/placeholder DTOs? Note any endpoint returning literal demo data.
Fill stubs_or_gaps with every stubbed/placeholder/hardcoded endpoint or auth gap.`,
  },
  {
    label: 'cli-commands',
    prompt: `${GROUND}
AREA: CLI — lemely/app/cli.py (~800+ lines after merge), plus main.py entrypoint, docs/exit-codes.md.
Produce:
1. COMPLETE command inventory TABLE: | command | key options/flags | what it does | needs GEMINI_API_KEY? | --json contract? | status(working/partial/stubbed) | evidence(file:line) |. Enumerate EVERY click command/subcommand (look for @cli.command / @click / add_command). Include: doctor, version, estimate-cost, parse-mark-schemes, correct-paper, predict-grade, detect-weaknesses, generate-quiz, compare-performance, and any others actually present.
2. Global options (--json, --config, --log-format, --log-level, -v/-q) and how they wire into runtime.
3. Exit-code scheme (cross-check docs/exit-codes.md vs lemely/runtime/errors.py).
Judge each command working vs stubbed by reading its body. stubs_or_gaps = any command that is a placeholder or not fully wired.`,
  },
  {
    label: 'core-domain-data',
    prompt: `${GROUND}
AREA: Core domain + data layer — lemely/core/*.py (analytics, correction, generation, history, integrity_schemas, loose_schemas, schemas, study, study_plan, plagiarism) and lemely/data/ + lemely/io/history_store.py + lemely/io/grade_boundaries.py.
Produce:
1. DATA LAYER section: There is NO SQL DB/ORM — confirm and describe the actual persistence: what is stored, in what format (JSON files? where?), the "schema" as pydantic models, and relationships (PaperRecord/StudentHistory/etc). Describe HistoryStore + GradeBoundaryStore persistence mechanics and file layout. State migration system status (likely none — confirm).
2. Per-module purpose table: | module | responsibility | key models/functions | status | evidence |. Note schemas.py vs loose_schemas.py distinction, analytics (compare_performance, aggregate_weaknesses), study vs study_plan, plagiarism algorithm.
3. Judge each: real logic vs placeholder.
stubs_or_gaps = anything partial/placeholder.`,
  },
  {
    label: 'io-llm-det',
    prompt: `${GROUND}
AREA: IO adapters, LLM integration, deterministic parser — lemely/io/ (gemini.py, answer_extraction.py, correction_ai.py, question_generation.py, scan_metadata.py, study_plan_ai.py, teacher_quiz.py, integrity.py, mark_schemes.py, metadata.py, parsers.py, parsers_det.py, subject.py, validation.py, det/*.py, prompts/*.py).
Produce:
1. LLM INTEGRATION section (audit item 12): provider (google-genai), models used + per-task model slots + escalation config (read runtime/config.py Gemini settings + gemini.py), where prompts live (enumerate lemely/io/prompts/*.py, one line each on what it builds), ret/retry/backoff/thinking-budget, and COST CONTROLS (per_run_token_ceiling, monthly_usd_ceiling — are they actually enforced? find the enforcement code or say unverified).
2. DET pipeline (det/*.py + parsers_det.py): describe the deterministic mark-scheme parsing stages (columns, rows, tables, mcq, gmp, marks, metadata, reconcile, profiles, parser). Is it wired into the CLI? working vs partial?
3. parsers.py vs parsers_det.py: what's the relationship, is one legacy?
stubs_or_gaps = placeholders, unenforced cost ceilings, unused parsers.`,
  },
  {
    label: 'frontend-spa',
    prompt: `${GROUND}
AREA: Frontend SPA — web/ (React 19 + Vite 8 + TS 6 + Tailwind v4). Files: web/src/App.tsx, main.tsx, index.css, lib/{api.ts,types.ts,utils.ts}, components/ui/*, portals/student/** and portals/teacher/** (index.tsx, screens/*, components/*, data.ts).
Produce (audit item 7 + feeds feature-status):
1. ROUTE/SCREEN inventory TABLE for BOTH portals: | portal | route path | screen component | renders from | status | evidence |. Read App.tsx / portals/*/index.tsx for react-router routes.
2. THE KEY QUESTION — data wiring: read web/src/lib/api.ts fully. Is it actually CALLED by any screen? Or do screens import from portals/*/data.ts (student data.ts=773 lines, teacher data.ts=591 lines — likely mock constants)? grep for imports of api.ts vs data.ts across screens. Determine for EACH screen whether it renders hardcoded/mock data or live API data. Be harsh: mock-data screens are STUBBED regardless of visual polish.
3. Component library (components/ui/*: button/card/chip/primitives — custom, using class-variance-authority + tailwind-variants), styling approach (Tailwind v4 via @tailwindcss/vite, fontsource fonts, index.css tokens), state management (tanstack react-query? react-router? local useState?). Is react-query actually used or just a dependency?
stubs_or_gaps = every screen not wired to the backend, unused deps, dead api client.`,
  },
  {
    label: 'config-env-deploy',
    prompt: `${GROUND}
AREA: Config, env vars, external services, deployment, stack/build (audit items 1,5,13,14 + directory map item 2).
Produce:
1. STACK table: languages + versions (python requires 3.12-3.15; venv is 3.13.12; node v26 / npm 12), build backend (hatchling), package managers (pip + uv.lock + requirements.lock — note both exist; explain), frontend toolchain. Verified build/dev/test commands (Makefile targets + web scripts) — mark which were actually run (see baseline) vs not.
2. ANNOTATED DIRECTORY MAP of every top-level dir and lemely/ subpackage.
3. EXTERNAL SERVICES + ENV VARS table: | env var | where consumed(file:line) | required? | default | purpose |. Cover GEMINI_API_KEY / LEMELY_GEMINI_API_KEY, LEMELY_* (pydantic-settings env_prefix in runtime/config.py), LEMELY_WEB_HOST/PORT (web/__main__.py), XDG_CONFIG_HOME. Read runtime/config.py fully for the settings surface. List MISSING/PLACEHOLDER env separately (no .env, no .env.example, GEMINI_API_KEY not set in this environment).
4. DEPLOYMENT/CI/IaC: describe .github/workflows/ci.yml (matrix 3.12/3.13/3.14; steps), pre-commit config. Confirm NO Docker/compose/IaC/hosting config exists (already grep-verified) — state hosting target is undefined.
stubs_or_gaps = missing env, missing deploy artifacts, uv.lock vs requirements.lock drift risk.`,
  },
  {
    label: 'tests-deadcode',
    prompt: `${GROUND}
AREA: Tests + dead code/duplication/abandoned approaches (audit items 9, 11).
Produce:
1. TESTS section: framework (pytest + pytest-cov + respx + subtests), count (baseline: 306 passed/2 skipped — verify with 'source .venv/bin/activate && pytest --co -q | tail -5' for collected count, read-only collection only), test dirs (tests/, tests/architecture/, tests/golden/). What is actually ASSERTED — categorize the test files by target. Note the 'live' marker (skipped by default, needs GEMINI_API_KEY). Coverage reality: overall 82% BUT lemely/app/gradio_app.py is OMITTED from coverage (pyproject omit) and lemely/web/__main__.py is 0% — call this out. Architecture tests (import-linter test, no-print-in-core). CI: same checks on 3.12/3.13/3.14.
2. DEAD CODE / DUPLICATION: use tokensave_dead_code, tokensave_redundancy, tokensave_similar, and grep. Investigate specifically: parsers.py vs parsers_det.py (is parsers.py legacy?), det/marks.py vs det/gmp.py, schemas.py vs loose_schemas.py, any unused prompts, any module not imported anywhere. For each candidate give evidence (tokensave_callers count or grep of imports). Distinguish TRUE dead code from intentional public API.
stubs_or_gaps = confirmed dead/duplicated/abandoned code with evidence.`,
  },
]

const results = await parallel(tasks.map(t => () => agent(t.prompt, { label: t.label, schema: SCHEMA })))

return tasks.map((t, i) => ({ area: t.label, result: results[i] }))
