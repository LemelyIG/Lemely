# Database & local Supabase stack

Lemely's data layer is **PostgreSQL**, run locally via the **Supabase** stack
(Docker) and, in production, via any managed Postgres. The relational schema is
owned by **SQLAlchemy 2 + Alembic** (in `lemely/db/`). Supabase additionally
provides **Auth (GoTrue)** and **Storage**; those own the `auth` and `storage`
schemas respectively, while everything in `public` is defined by our models.

## Prerequisites

- Docker (daemon running)
- Supabase CLI (`supabase --version`) — install: <https://supabase.com/docs/guides/cli>
- Python deps: `make dev` (installs the `db` extra: SQLAlchemy, Alembic, psycopg, PyJWT)

## One-time / everyday commands

| Command | What it does |
| --- | --- |
| `make db-up` | `supabase start` (boots Postgres/Auth/Storage/Studio), then `alembic upgrade head` |
| `make db-status` | Show local stack URLs + keys (`supabase status`) |
| `make db-migrate` | Apply pending Alembic migrations to the running DB |
| `make db-revision m="msg"` | Autogenerate a migration from model changes |
| `make db-downgrade` | Roll back one migration |
| `make db-reset` | Wipe Postgres, re-apply migrations, re-seed demo data |
| `make seed` | Seed reference data + demo accounts (idempotent) |
| `make db-down` | `supabase stop` |

First `supabase start` downloads several container images (a few hundred MB) and
can take a few minutes. Subsequent starts are fast.

## Local endpoints (defaults)

| Service | URL / port |
| --- | --- |
| API gateway (Kong) | `http://127.0.0.1:54321` |
| Postgres | `127.0.0.1:54322` (user `postgres`, password `postgres`, db `postgres`) |
| Studio (DB UI) | `http://127.0.0.1:54323` |
| Inbucket/Mailpit (local email) | `http://127.0.0.1:54324` |

Run `make db-status` to print the current anon key, service-role key, and JWT
secret. These local-dev values are **well-known and non-secret**; production
values must be supplied via environment variables (never committed).

## Configuration

Settings live under `[database]` and `[supabase]` in `lemely.toml` (see
`lemely.toml.example`) or via env vars:

- `LEMELY_DATABASE__URL` — full SQLAlchemy URL (default targets local Supabase).
- `LEMELY_SUPABASE__URL` / `LEMELY_SUPABASE__JWT_SECRET` /
  `LEMELY_SUPABASE__ANON_KEY` / `LEMELY_SUPABASE__SERVICE_ROLE_KEY`.

Precedence is the same everywhere: env > `.env` > `lemely.toml` > defaults.

## Migrations

- Models: `lemely/db/models/` — every model module is registered in
  `import_all_models()` so Alembic autogenerate and `create_all` never miss one.
- Config: `alembic.ini` + `lemely/db/migrations/env.py`. The DB URL is taken
  from `Settings` (not `alembic.ini`), so migrations honour the same precedence
  as the app.
- Constraint/index names follow a fixed naming convention (`lemely/db/base.py`)
  so later migrations can reference them by name — this underpins the
  **additive-only** migration guarantee for Phases 2–5.

Workflow: change a model → `make db-revision m="describe change"` → review the
generated file in `lemely/db/migrations/versions/` → `make db-migrate`.

## Why Alembic owns `public`, not Supabase migrations

Supabase's own migration mechanism (`supabase/migrations/*.sql`) is left unused
for `public` so the Python backend is the single source of truth for the schema
(typed models, autogenerate, one review surface). `supabase/seed.sql` is
therefore intentionally empty — it would run before Alembic during
`supabase db reset` and cannot reference app tables. App seeding is Python-side
(`make seed`).
