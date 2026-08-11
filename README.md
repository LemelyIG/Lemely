# Lemely

An assessment platform for CAIE (Cambridge) IGCSE / O-Level students, their
parents, and their teachers.

A student photographs or uploads an attempted past paper. Lemely extracts the
handwritten answers, marks them against the official mark scheme with
method-mark awareness, and returns per-question marks with a **confidence value
on every one of them**, a letter and numerical grade, a predicted grade after
the session's boundaries, the mistakes made, and the topics they cluster into.
Around that loop sit student, teacher, parent and school-admin surfaces:
analytics, at-risk flagging, a human-review queue, a quiz builder, generated
practice and flashcards, adaptive study plans, and an XP/streak engagement
layer.

Subjects in scope: **Mathematics 0580, Additional Mathematics 0606, Physics
0625**. The architecture is board-agnostic; other boards arrive as data and
parser plugins.

## Status

All six build phases are complete. What is built, which files implement it,
which tests prove it, and — equally — what is **not** built and why, is in
[`DELIVERY.md`](DELIVERY.md). Read that before assuming a feature works; it
carries the honest limitations, not a marketing list.

Payments are deliberately out of scope: the subscription and seat model exists
and gates plans, but account activation is a manual platform-admin toggle.

## Shape of the system

```
lemely/            Python backend
├── core/          pure domain logic — no I/O, no Gemini, no Rich
├── io/            disk + Gemini adapters; depends on core only
├── db/            SQLAlchemy 2 models, repositories, Alembic migrations
├── auth/          JWT verification, roles, device registry
├── web/           FastAPI routers, services, SSE correction pipeline
├── app/           CLI + Gradio (Gradio is an internal debug tool only)
└── runtime/       config, logging, errors — leaf module (no domain imports)

web/               React 19 + Vite + Tailwind v4 SPA (the real product UI)
supabase/          local Supabase stack (Postgres, GoTrue auth, Storage)
```

The `core → io → app` layering is enforced by import-linter contracts in
`pyproject.toml`.

- **Database:** PostgreSQL via a local Supabase stack. Schema and migrations are
  owned by the Python backend (SQLAlchemy 2 + Alembic), and every migration is
  additive.
- **Auth:** Supabase GoTrue for identity; the backend issues and validates its
  own HS256 JWTs. Roles: `student`, `parent`, `teacher`, `school_admin`,
  `platform_admin`. RBAC is enforced server-side on every route — see
  [`docs/database.md`](docs/database.md) and the generated authz matrix in
  `tests/test_authz_matrix_complete.py`.
- **LLM:** Google Gemini (`gemini-2.5-flash` by default), behind a persistent
  cost ledger with a hard spend ceiling. **Every automated test mocks Gemini.**

## Running it

One command brings up the whole stack — Supabase local, the backend, and the
built SPA served by nginx:

```bash
make up      # http://localhost:8080
make down
```

Full instructions, the configuration reference, and a recipe for a future
cloud deploy are in [`docs/deployment.md`](docs/deployment.md).

### Local development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,ui]"     # ui extra adds Gradio
pre-commit install

make db-up                     # supabase start
make db-migrate                # alembic upgrade head
make seed                      # reference data + demo accounts

cd web && npm ci && npm run dev
```

Supported Python: 3.12, 3.13, 3.14. Node 24+ is required for the frontend
tooling.

Set `GEMINI_API_KEY` (or `LEMELY_GEMINI_API_KEY`) in the environment — never in
the TOML.

## Configuration

Settings load with precedence **env > `.env` > `lemely.toml` > defaults**.
Every section uses `extra='forbid'`, so a typo is rejected at startup rather
than silently ignored. Nested keys use a `__` separator
(`LEMELY_GEMINI__MODEL`).

`lemely.toml.example` is the full surface and is kept in sync with the schema by
a drift test. `lemely doctor` validates config, paths and API-key reachability.

## CLI

The CLI predates the web product and remains the way to drive the parsing and
marking core directly:

```bash
lemely doctor                                    # config + env + path readiness
lemely estimate-cost Sources/
lemely parse-mark-schemes Sources/ --use-gemini
lemely correct-paper --mark-scheme scheme.json --answers answers.txt
lemely predict-grade correction.json
lemely detect-weaknesses correction.json
lemely generate-quiz weakness.json --count 5
```

Global options: `--json`, `--config PATH`, `--log-format {auto,json,console}`,
`--log-level`, `-v/-q`. JSON mode is the contract for scripts; human mode uses
Rich tables. Exit codes are documented in
[`docs/exit-codes.md`](docs/exit-codes.md) — `0` success, `2` usage, `3` config,
`6` parse, `7` Gemini failure, `1` partial batch.

## Quality gates

`./scripts/check.sh` is the single entry point and runs all thirteen gates:
ruff check, ruff format, mypy strict, import-linter, pytest with coverage, the
web typecheck, oxlint, the web build, frontend unit tests, Playwright E2E, the
Puppeteer axe/Lighthouse audit runner, the UI threshold check, and the visual
comparison against committed baselines.

```bash
./scripts/check.sh          # everything; prints only failures
make test                   # pytest with coverage gate
make lint fmt typecheck imports
make pre-commit
```

Standing thresholds: zero serious or critical axe violations on every route
state, Lighthouse accessibility ≥ 95 on every route, Lighthouse performance
≥ 80 on the student routes, zero console errors, and no horizontal scroll at any
breakpoint from 320px up. The screenshot corpus and per-phase contact sheets
live under `reports/`.

CI runs the backend checks across Python 3.12 / 3.13 / 3.14.

## Documentation

| Document | What it covers |
| --- | --- |
| [`DELIVERY.md`](DELIVERY.md) | Every feature, its status, files, proving tests, and the honest limitations |
| [`docs/deployment.md`](docs/deployment.md) | Local stack, cloud recipe, configuration reference |
| [`docs/database.md`](docs/database.md) | Schema, tenancy model, migration policy |
| [`docs/LEMELY_UI_SPEC.md`](docs/LEMELY_UI_SPEC.md) | The authoritative product and UI specification |
| [`docs/COMPONENT_CATALOGUE.md`](docs/COMPONENT_CATALOGUE.md) | Cross-cutting component library and states |
| [`docs/quiz-model.md`](docs/quiz-model.md) | Quiz, placement and practice data model |
| [`docs/exit-codes.md`](docs/exit-codes.md) | CLI exit-code contract |
| [`DESIGN.md`](DESIGN.md) / [`PRODUCT.md`](PRODUCT.md) | Brand source of truth — colour, type, voice |

## Licence

Proprietary. Past papers, mark schemes and student scripts under `Sources/` and
`tests/fixtures/real-papers/` are third-party copyright material used for
development and testing only; they are never served to users and never included
in a shipped bundle.
