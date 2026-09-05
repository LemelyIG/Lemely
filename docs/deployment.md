# Deploying Lemely

Two deployments are described here:

1. **[Local packaged run](#1-local-packaged-run)** — the one-command Docker Compose
   stack that exists today and is verified working (`make up`).
2. **[Cloud deploy recipe](#3-cloud-deploy-supabase-cloud--a-container-host)** — Supabase
   Cloud plus a container host, written from the real configuration surface of the
   code rather than from a deploy that happened. Every step is derived from a file
   in this repo and cites it, so you can check the claim rather than trust it.

   **[`docs/ci-cd.md`](ci-cd.md) is the automated, opinionated version of this
   recipe** — GitHub Actions, Cloud Run, and Cloudflare specifically, with staging
   and production environments wired up. The two Supabase Cloud projects it uses
   are provisioned for real (not hypothetical); the pipeline itself has not been
   run end-to-end yet, pending the credentials `docs/ci-cd.md` asks for. Read this
   section for the *why* behind the remaining constraints (gated migrations, the
   JWT secret trap); read `docs/ci-cd.md` for the concrete, automated *how*.

MISSION §3 fixes the definition of done as *"one-command local run via Docker Compose
… plus written deployment docs for a future free-tier cloud deploy. No live hosting."*
Section 1 is the first half; sections 3–6 are the second.

Read [§5 What will bite you](#5-what-will-bite-you-in-a-real-deploy) before deploying
anywhere real. It is the part of this document with the highest value per line: §5.1
tracks what state is safe across instances and what still isn't, and the container
entrypoint runs migrations on every start regardless of instance count.

---

## 1. Local packaged run

### Prerequisites

| Requirement | Why | Check |
|---|---|---|
| Docker + Compose v2 | Runs Supabase-local, the backend, and nginx | `docker compose version` |
| Supabase CLI on `PATH` | `scripts/up.sh` starts the stack; it is *not* managed by `docker-compose.yml` | `supabase --version` |
| ~4 GB free RAM | Supabase-local alone is ~10 containers | `free -h` |

`scripts/up.sh` prepends `$HOME/.local/bin` to `PATH` itself, which is where the
Supabase CLI lives in this environment; it fails with an explicit install pointer if
the CLI is still not found (`scripts/up.sh:14-18`).

### The command

```bash
make up          # -> ./scripts/up.sh
```

That does three things, in order (`scripts/up.sh`):

1. `supabase start` if the stack is not already running (idempotent — an
   already-running stack is detected and left alone).
2. `docker compose up --build -d` for the `backend` and `web` services.
3. Polls both containers' healthchecks for up to 120 s, so when the command returns
   successfully the product is actually *usable*, not merely *started*. This matters:
   `docker compose up -d` returns as soon as containers exist, and a caller who
   `curl`s immediately after it races the app's own startup.

When it finishes:

| URL | What |
|---|---|
| <http://localhost:8080> | **The product.** nginx serving the built SPA, proxying `/api` to the backend |
| <http://localhost:8000/api/health> | Backend directly — debugging and health only; the SPA never uses this port |
| <http://localhost:54323> | Supabase Studio (published by `supabase start`, untouched by this repo) |

Tear down with `make down` (`docker compose down` — leaves Supabase running, since
this repo does not own it) and `make db-down` (`supabase stop`) for the rest.

### What was verified (P6.4)

Not inferred from the config — executed against a running `make up` stack:

- `/api/health` returns 200 both directly and through the nginx proxy.
- The SPA `index.html` is served.
- `alembic upgrade head` runs in the entrypoint, reaching Supabase's Postgres over
  the shared Docker network (schema at `0018`; 1610 seeded users read from *inside*
  the container).
- The full auth chain works behind the proxy: **401** with no token, **200** with a
  real minted student token, **403** with a teacher token on a student route — which
  also proves nginx forwards the `Authorization` header.
- The hardcoded local JWT secret was compared against the *running*
  `supabase_auth_Lemely`'s `GOTRUE_JWT_SECRET` rather than assumed to match.

### Two design points not to undo

**The backend joins Supabase's own network as `external`.**
`docker-compose.yml` declares `supabase_network_Lemely` with `external: true` and
addresses `supabase_db_Lemely:5432` / `supabase_kong_Lemely:8000` **by container
name**. The host-published ports (54322 Postgres, 54321 API) do not exist inside a
container's network namespace. Declaring the network instead of joining it would
silently stand up an empty network the backend cannot reach Postgres through;
`external: true` instead fails loudly when Supabase-local is down, which is correct.

**No CORS middleware is installed, deliberately.**
nginx proxies `/api` to the backend on the same origin the SPA was loaded from, so
the browser issues no cross-origin request and there is nothing for CORS to permit.
`grep -rn CORSMiddleware lemely/` is empty and **that is the intended state, not an
omission to fix.** See [§4](#4-when-you-actually-do-need-cors) for the one case that
changes this.

---

## 2. Configuration

All settings live in `lemely/runtime/config.py` as a nested pydantic-settings model.

**Precedence** (highest first): environment variable → `lemely.toml` → default.
The env prefix is `LEMELY_` and the nested delimiter is `__`
(`config.py:262-263`), so `SupabaseSettings.jwt_secret` is
`LEMELY_SUPABASE__JWT_SECRET`. `GEMINI_API_KEY` is the one un-prefixed exception.

Every settings group declares `extra="forbid"`, so a **typo'd key in `lemely.toml`
is a startup error, not a silently ignored line.** Env vars that do not match a
field are ignored by pydantic-settings, so a typo'd *env var* is silent — check
`lemely doctor` after setting them.

### The variables a deployment actually sets

| Variable | Default | Set it when |
|---|---|---|
| `LEMELY_DATABASE__URL` | `postgresql+psycopg://postgres:postgres@127.0.0.1:54322/postgres` | **Always in a container.** The default points at a host-published port that does not exist inside one. |
| `LEMELY_SUPABASE__URL` | `http://127.0.0.1:54321` | **Always in a container.** Same reason. |
| `LEMELY_SUPABASE__JWT_SECRET` | the well-known local-dev secret | **Always outside local dev.** See the warning below. |
| `LEMELY_SUPABASE__ANON_KEY` | `None` | Any real Supabase project. |
| `LEMELY_SUPABASE__SERVICE_ROLE_KEY` | `None` | Any real Supabase project (server-side admin: user creation, Storage). |
| `GEMINI_API_KEY` | `None` | To enable marking/extraction at all. Absent is a *documented* state — `/api/health` reports `apiKeyConfigured: false` rather than crashing (`lemely/web/routers/meta.py:17-19`). |
| `LEMELY_WEB_HOST` / `LEMELY_WEB_PORT` | `0.0.0.0` / `8000` **in the image** | Already correct in the Dockerfile. The *application* default is `127.0.0.1`, right for a bare-metal dev run and unreachable from outside a container — the image overrides it (`Dockerfile:51-52`). |
| `LEMELY_PUSH__VAPID_PUBLIC_KEY` / `__VAPID_PRIVATE_KEY` / `__VAPID_SUBJECT` | `None` | To enable web push. All three absent is a **supported** state (D5.9 §4): the transport reports itself unavailable and the notification inbox keeps working. |
| `LEMELY_STORAGE__BACKEND` | `local` | Set `gcs` for any deploy that isn't local dev/Compose/CI — see [§5.1](#51-the-single-replica-constraint-is-lifted). `local` writes under `paths.output_dir/storage` on the container's own disk. |
| `LEMELY_STORAGE__BUCKET` | `uploads` | The bucket (`gcs`) or directory name (`local`) to use. For `gcs`, the bucket is **created by `scripts/gcp-bootstrap.sh`**, one per environment (`${PROJECT_ID}-uploads-${ENV}`) — not by this app. |
| `LEMELY_GEMINI__TOTAL_USD_CEILING` | `8.0` | **CLI/Gradio only** — to change the hard spend cap those surfaces enforce (MISSION §8). The web process enforces no cap; see [§5.4](#54-performance-and-cost). |
| `LEMELY_GRADING__STALE_RUN_AFTER_SECONDS` | `900` | To change how long a teacher paper stuck in `processing` must go silent before the next regrade may reclaim it (its instance died mid-run). |
| `LEMELY_LOGGING__FORMAT` | `auto` | Set `json` for a log aggregator. |

> **The JWT secret is the one that will burn you.**
> `docker-compose.yml:62` hardcodes
> `super-secret-jwt-token-with-at-least-32-characters-long`. That is the
> **published, well-known default** every local Supabase project uses — it is in
> Supabase's public documentation. It is correct for a laptop and catastrophic
> anywhere reachable: anyone can mint a valid token for any user and any role,
> because the backend validates HS256 tokens against exactly this shared secret
> (`config.py:171`). **A cloud deploy MUST set `LEMELY_SUPABASE__JWT_SECRET` to the
> project's real secret** (Supabase dashboard → Settings → API → JWT Secret).
> Nothing in the code refuses to boot with the default value, so no error will tell
> you that you forgot.

---

## 3. Cloud deploy: Supabase Cloud + a container host

**Never executed.** Written from the configuration surface. Expect to debug.

### 3.1 Shape

```
   browser
     |  HTTPS, one origin
     v
[ container host ]  nginx (web image)  --/api-->  uvicorn (backend image)
                                                       |
                                                       v
                                          [ Supabase Cloud project ]
                                          Postgres · GoTrue · Storage
```

Keeping nginx in front of the backend is what makes the whole CORS question
disappear in the cloud too. Deploy **both** images, or serve the SPA from a static
host and accept the [CORS work in §4](#4-when-you-actually-do-need-cors).

### 3.2 Supabase Cloud

1. Create a project. Note the region — put the container host in the same one, since
   every request pays the round trip.
2. From **Settings → API** collect: Project URL, `anon` key, `service_role` key, and
   the **JWT Secret**.
3. From **Settings → Database** collect the connection string. Use the **connection
   pooler** (port 6543), not the direct connection (5432), on any host that scales
   or recycles containers — Supabase's direct connection limit is small and a
   restarting container leaks connections faster than it reclaims them.
4. Rewrite the driver prefix: Supabase gives you `postgresql://…`; this app needs
   **`postgresql+psycopg://…`** (SQLAlchemy 2 + psycopg 3, as in the default at
   `config.py:148`). A plain `postgresql://` URL will pick the wrong DBAPI.
5. Create the Storage bucket named in `LEMELY_STORAGE__BUCKET` (default `uploads`).
   **No code path creates it.** Uploads fail against a missing bucket.
6. Apply the schema — see [§3.4](#34-migrations-are-a-separate-gated-step), and do
   **not** simply let the container do it.

### 3.3 The container host

The images are ordinary and portable — no host-specific assumptions. What a host
must provide:

| Requirement | Why |
|---|---|
| Builds a `Dockerfile`, or accepts a pushed image | Both images are plain multi-stage Dockerfiles |
| Injects env vars / secrets | Everything in §2 |
| Listens on the port the app binds | Backend `8000`, web `80`; both configurable |
| Any instance count | Used to be pinned to exactly one — see [§5.1](#51-the-single-replica-constraint-is-lifted) for what changed. **§3.2 step 5 below predates that change and is now wrong**: the storage backend it describes (a Supabase Storage bucket) no longer exists in this codebase — only `local` and `gcs` (`LEMELY_STORAGE__BACKEND`, §2) do. Do not follow step 5 as written; use the `gcs` backend and a real bucket instead. |
| ~512 MB RAM per container | PyMuPDF + SQLAlchemy; not measured under load |

Free tiers change often enough that naming one here would be wrong within months.
Check current terms yourself. The two properties that actually matter for *this*
app, whichever host you pick:

- **Scale-to-zero is fine; scale-to-many now is too.** A cold start still costs a
  request's latency, but a second replica no longer breaks correction progress or
  parent login — see [§5.1](#51-the-single-replica-constraint-is-lifted) for what
  moved off process memory and the one thing (a cache) that didn't.
- **A host that sleeps idle containers will drop in-flight correction jobs**, since
  they live in process memory. Not a data-loss bug — the attempt is already
  committed — but a student watching the progress stream sees it stall.

Deploy order: backend first (it must be healthy for the web image's healthcheck
model to make sense), then web with `proxy_pass` pointed at the backend's internal
address. `web/nginx.conf:20` hardcodes `http://backend:8000/api/` — the Compose
service name. **On a host without Compose DNS this is the one line you must
change**, to whatever internal hostname the host gives the backend service.

### 3.4 Migrations are a separate, gated step

`docker-entrypoint.sh:11` runs `alembic upgrade head` on **every container start**.

That is right for a one-command local bring-up and **wrong for production**, where
schema change must be a deliberate, reviewed, separately-triggered step. In
production it means an image rollout is also, silently, a schema migration — with
no review gate, and with N containers potentially racing the same upgrade on a
multi-replica host.

For a real deploy, do one of:

- **Preferred:** run `alembic upgrade head` as an explicit release/job step against
  the production database, then start containers with `LEMELY_RUN_MIGRATIONS=0` so
  the entrypoint skips its own migration line (`docker-entrypoint.sh`). This is
  exactly what `docs/ci-cd.md`'s pipeline does: a dedicated `migrate` job runs
  first, and the Cloud Run deploy step sets `LEMELY_RUN_MIGRATIONS=0`.
- Or run migrations from an operator machine before rolling the image, and accept
  the entrypoint's re-run as a no-op (it is idempotent at head).

Alembic's own config reads the same `LEMELY_DATABASE__URL`, so an operator run needs
only that variable set.

---

## 4. When you actually do need CORS

Only if the browser loads the SPA from a **different origin** than it calls the API
on — a static host for the SPA, split subdomains, or a mobile WebView. Then, and
only then:

- Add `CORSMiddleware` in `lemely/web/app.py` with a **config-driven explicit
  allowlist**. Never `allow_origins=["*"]`.
- Set **`allow_credentials=False`**. This app authenticates with a bearer token in
  the `Authorization` header, never a cookie, so credentialed CORS is never needed —
  and `allow_credentials=True` combined with a permissive origin is the classic
  account-takeover shape.
- Remember the SSE path: `text/event-stream` responses need the same treatment, and
  any intermediate proxy needs `proxy_buffering off` (`web/nginx.conf:30`) or live
  progress arrives in one lump at the end.

This is a code change in `lemely/web/app.py`, not a compose-file change.

---

## 5. What will bite you in a real deploy

Honest constraints. Each is a real property of the code today, not a hypothetical.

### 5.1 The single-replica constraint is lifted

This section used to name two pieces of process-local state and pin the backend to one
instance because of them. Both are gone, and so are several more this document never
named — the design spec for this work
(`docs/superpowers/specs/2026-09-03-gcs-uploads-and-cloud-run-scale-out-design.md` §1.3)
found a longer list by reading the code. The table below is that same state inventory,
with a "now" column added:

| State | Where | Then | Now |
|---|---|---|---|
| Teacher paper store | `routers/teacher.py::_PaperStore` | In-process dict — a paper was visible only on the instance that received it, and lost on restart. | A `teacher_papers` Postgres row (migration `0024`). Every state change the grading worker makes is written to the row, so any instance's `GET /papers/{id}` sees it — including one that never ran the job. |
| Grading pool + lock | `routers/teacher.py::_grading_pool` | Pinned to one worker per instance because the event bus had no per-run scoping — a regrade landing on another instance could start a second run of the same paper. | Still one worker per instance, for a different reason: run state now lives on the row, not the pool, so raising the worker count is a one-line change later (DS13). A `processing` row silent past `LEMELY_GRADING__STALE_RUN_AFTER_SECONDS` (default 900s) is reclaimable by the next regrade — its instance died mid-run. |
| Job registry | `lemely/web/jobs.py` | An in-process `dict` behind a lock. Zero route callers — nothing ever read it. | **Deleted.** It backed nothing: `POST /student/correct` has always streamed over the event bus on the one HTTP connection the correction runs on, with no separate reconnect to lose. |
| Parent phone-OTP challenge store | `lemely/auth/otp.py::OtpStore` | In-memory — issued on one replica, verified on another, verification fails. | Postgres-backed (`DbOtpStore`, migration `0025`) — a code minted on one instance verifies on any other. Email verification's own 6-digit code (alongside the existing link) shares the same table, keyed by channel. |
| Auth cooldown store | `lemely/auth/cooldown.py::CooldownStore` | In-memory — the only abuse defence on public auth routes weakened by a factor of N instances. | Postgres-backed (`DbCooldownStore`, migration `0026`). |
| Event bus | `lemely/runtime/events.py::bus` | Unscoped — two concurrent SSE streams on the same instance received each other's frames, and the first stream to finish ended both. This, not instance count, is why the grading pool above was pinned to one worker. | Per-run channels via a context variable. Still an in-process bus, not a cross-instance one — irrelevant to `/student/correct` (one HTTP connection, start to finish, never reconnected) and the reason the grading pool stays one worker per instance above. |
| Scheme corpus | `output_dir/schemes` | A directory scan, per instance. | The existing `papers`/`mark_schemes` Postgres tables; the PDF itself lives in the storage bucket next to the scan. |
| Spend ledger | `output_dir/gemini_spend.json` via `CostLedger` | The $8 cap reset on every cold start; with N instances it would have become N independent caps. | Retired in the web process — see [§5.4](#54-performance-and-cost). The CLI and Gradio are unchanged and still enforce it. |
| Gemini response cache | `cache_dir/gemini` | Per instance. A cache, not a correctness issue. | **Unchanged — the only state left on this list.** More instances mean a lower hit rate, nothing else. |

Two trades were accepted deliberately here, not overlooked:

- **A budget alert is not a cap.** The web process enforces no USD ceiling on Gemini spend; a
  Google Cloud billing budget on the project (provisioned by `scripts/gcp-bootstrap.sh`, alerts at
  50/90/100%) is the only guard, and spend can pass it before anyone acts. See §5.4.
- **Queued is per instance.** The grading pool is one worker per instance. With three instances,
  at most three teacher runs proceed at once, and a paper can queue on one instance while another
  sits idle. Not a correctness bug — every instance answers a paper's status from the same row —
  just a scheduling one, accepted at this scale.

The nginx/web image never had this constraint and scales freely regardless.

### 5.2 There is no scheduler

`streak_warning` and `study_plan_reminder` are service methods **nothing invokes on a
timer** (D5.9 §5). At-risk rule 3 (≥14 days inactive) cannot fire at its seam — the
alert fires on correction, and a student who just uploaded is by definition active.
Deploying does not create a scheduler. If you need these, add a cron/worker that
calls them; do not report them as delivered notification types.

### 5.3 `make seed` seeds demo credentials — never run it against production

**Resolved in P6.10** (this section previously recorded that `seed_reference_data`
and `seed_demo_accounts` were stubs with a bare `pass`, so `make seed` inserted zero
rows and created zero accounts while logging a cheerful `db.seed.done`).

`make seed` now inserts the three supported subjects and creates one account per
role, with **fixed, published credentials** — `<role>@demo.lemely.local` /
`Demo-Lemely-1!`, plus a phone-OTP parent on `+10000000000`. The full table is in
[`README.md`](../README.md).

That is the deployment-relevant part: **these are documented credentials, so seeding
a real deployment hands anyone who has read this repository a `platform_admin`
login.** `make seed` is a local-development and demo convenience. A production
bring-up runs `alembic upgrade head` and nothing else; create real accounts through
the normal signup/invite path.

`scripts/seed_e2e.py` remains the path that populates a database with realistic
marked papers, classes and analytics. Its accounts carry a **per-run random
`run_tag`**, so its emails and passwords differ on every run — fine for tests, and
the reason it cannot be the thing a document names.

One containerisation note: `ensure_supabase_env` (`lemely/runtime/supabase_env.py`)
resolves the stack keys by shelling out to `supabase status`, which does not exist in
a deployed container. Set `LEMELY_SUPABASE__SERVICE_ROLE_KEY` and
`LEMELY_SUPABASE__ANON_KEY` explicitly there — an already-exported value always wins,
so the helper is a no-op when they are set.

### 5.4 Performance and cost

- **`/api/teacher/overview` is 10–40× slower than everything else measured** — p50
  396 ms / p95 458 ms against 8–150 ms elsewhere (`reports/phase-6/load-sanity.md`,
  seeded data, concurrency 10). The shape of an N+1 across a teacher's classes and
  students. Not a failing test; it is the first place to look if the teacher console
  feels slow.
- **Load sanity reports numbers and no verdict**, deliberately. No latency threshold
  is specified anywhere in this build, and grading against an invented one would be
  manufactured precision.
- **The web process enforces no cap on Gemini spend (DS3).** A Google Cloud billing
  budget on the project — created by `scripts/gcp-bootstrap.sh` when
  `BILLING_ACCOUNT_ID` and `BUDGET_USD` are set, with alerts at 50/90/100% — is the
  only guard, and it is an alert, not a stop: spend can pass it before anyone acts.
  The CLI and Gradio are unchanged and still enforce the on-disk `$8.00` ledger.

### 5.5 Security posture as shipped

Good already: the backend image runs **non-root** (`Dockerfile:45,67`), carries no
compiler toolchain and no dev/test dependencies, and all 121 route operations are
authz-guarded with a generated matrix test that fails on drift (P6.3). Secrets are
`SecretStr` and are never hardcoded in the compose file — only the local-dev JWT
secret is, and §2 says why that must be overridden.

Still needed for anything public-facing, none of it built here: TLS termination
(nginx listens on plain `:80`), a rate limiter on the auth endpoints, and log
shipping. `LEMELY_LOGGING__FORMAT=json` is the one lever that already exists.

---

## 6. Deployment checklist

Copy this. Every line maps to something above. It's written for the generic
"nginx + any container host" shape — if you're using the automated GitHub
Actions pipeline (`docs/ci-cd.md`, Cloud Run + Cloudflare Workers), most of
this is handled by the workflow itself; use `docs/ci-cd.md`'s own credentials
checklist instead, which maps to this one but names exact secrets and skips
the nginx-specific lines (there is no nginx in that path — Cloudflare Workers
replaces it).

```
[ ] Supabase Cloud project created; region matches the container host
[ ] LEMELY_DATABASE__URL set, pooler port 6543, prefix postgresql+psycopg://
[ ] LEMELY_SUPABASE__URL set to the project URL
[ ] LEMELY_SUPABASE__JWT_SECRET set to the REAL secret  <-- nothing warns you
[ ] LEMELY_SUPABASE__ANON_KEY + __SERVICE_ROLE_KEY set
[ ] GEMINI_API_KEY set (or accept apiKeyConfigured:false and no marking)
[ ] LEMELY_STORAGE__BACKEND=gcs and LEMELY_STORAGE__BUCKET set to a real bucket --
    the "local" default writes to per-container disk, invisible across instances (§5.1)
[ ] alembic upgrade head run as an explicit step, NOT via the entrypoint
[ ] A spend guard exists on the Gemini project (a billing budget or equivalent) --
    the web process itself enforces no USD cap (§5.4)
[ ] web/nginx.conf proxy_pass repointed if the host has no Compose DNS
[ ] TLS terminated in front of nginx
[ ] Verified: 401 no token / 200 valid token / 403 wrong role on a real route
```

That last line is the cheapest end-to-end proof that the deploy is wired correctly —
it exercises DNS, the proxy, `Authorization` forwarding, JWT validation against the
right secret, and RBAC in a single pass. It is exactly what was run against the local
stack in P6.4.
