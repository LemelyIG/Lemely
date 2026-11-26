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
`LEMELY_SUPABASE__JWT_SECRET`. `GEMINI_API_KEY` and `ANTHROPIC_API_KEY` are the
un-prefixed exceptions (each also accepts a `LEMELY_`-prefixed spelling).

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
| `GEMINI_API_KEY` | `None` | Required only when a task tag resolves to a `gemini-` model (`lemely doctor` fails when one does and no key is set). Every default task tag except `mark_scheme` is a `claude-` model since sub-project C; `gemini.mark_scheme_model` stays `gemini-2.5-flash` (Haiku's parse failed parity with the deterministic parser), so a Claude deployment still needs this key for the schemes the deterministic parser rejects. The web gates for scan-metadata detection, the self-review judge, quiz generation and `/api/health` `apiKeyConfigured` read the key of the provider their task tag's model needs (`llm_key_configured`). Absent is a *documented* state — `/api/health` reports `apiKeyConfigured: false` rather than crashing (`lemely/web/routers/meta.py:17-19`). |
| `ANTHROPIC_API_KEY` | `None` | Required: every task tag except `mark_scheme` defaults to a `claude-` model since sub-project C (`BUILD/accuracy-runs/claude-c-2026-10-26-live3/FLIP.md`): `claude-haiku-5-5` for `gemini.model` and every per-task model but `mark_scheme_model`, the binder's `read_model` and the adjudication model, and `claude-sonnet-5-5` for the binder's `retry_model`; there is no default escalation model. A tag moved back to a `gemini-` model by config is the only way a deployment can leave it out. Every `claude-` call goes through `lemely/io/providers/anthropic_adapter.py` behind the same cache, retry and spend ledger as Gemini. Absent, a call to a `claude-` model fails with `ExternalServiceError` (not retried). `lemely doctor` fails and the web process logs an error at startup when any configured `claude-` model lacks a key: both check one table (`lemely/io/model_table.py`), which covers every `model_for` tag (`correction`, `correction_borderline`, `escalation`, `extraction`, `generation`, `mark_scheme`, `scan_metadata`, `study_plan`), `gemini.cascade_strong_model` when the cascade is on, and the binding step's models. Secret, env-only like `GEMINI_API_KEY` — never put it in `lemely.toml`. Student work goes only through the synchronous Messages API; the Message Batches API is not used (data-protection decision). A file call on a `claude-` model raises `ValueError`; page images are supported. **Claude Files API (page images).** With `gemini.claude_files_api` on (the default), page images for `claude-` calls are uploaded to Anthropic's Files API once per job, with a one-hour expiry, and deleted when the job ends. Files API storage is not covered by zero data retention, and any API key of the workspace can read an uploaded file, so the Anthropic key must belong to a dedicated Lemely workspace. Claude code execution (any task tag, by user decision 2026-10-20) is likewise not covered by zero data retention. Turn the flag off to send pages inline instead (limited to 30 MB of base64 per request). |
| `LEMELY_WEB_HOST` / `LEMELY_WEB_PORT` | `0.0.0.0` / `8000` **in the image** | Already correct in the Dockerfile. The *application* default is `127.0.0.1`, right for a bare-metal dev run and unreachable from outside a container — the image overrides it (`Dockerfile:51-52`). |
| `LEMELY_PUSH__VAPID_PUBLIC_KEY` / `__VAPID_PRIVATE_KEY` / `__VAPID_SUBJECT` | `None` | To enable web push. All three absent is a **supported** state (D5.9 §4): the transport reports itself unavailable and the notification inbox keeps working. Generate with `lemely push-keygen`; `deploy.yml` reads the public key from the `VAPID_PUBLIC_KEY` repository variable and the private key from the `VAPID_PRIVATE_KEY` secret. Rotating the pair invalidates every stored subscription — see `docs/push-notifications.md`. |
| `LEMELY_NOTIFICATIONS__SWEEPER_ENABLED` | `true` | Set `false` to run an API instance that never sweeps (a second replica behind a load balancer, or a one-off maintenance container). `deploy.yml` sets it `false` on Cloud Run once that environment's Cloud Scheduler sweep job is in place, and `true` until then (see §5.2); the test suite sets it too. See §5.2 for the Cloud Run caveat; `__SWEEP_POLL_SECONDS` (60), `__STREAK_WARNING_HOUR` (19) and `__STUDY_PLAN_REMINDER_HOUR` (8) are its companions. |
| `LEMELY_NOTIFICATIONS__JOBS_SECRET` | `None` | Shared secret for `POST /api/internal/jobs/sweep`, which Cloud Scheduler calls every minute (`X-Cron-Secret` header) to run one sweeper pass. Unset, the endpoint answers 503. `deploy.yml` reads it from the `SWEEP_JOBS_SECRET` environment secret. See §5.2. |
| `LEMELY_NOTIFICATIONS__JOBS_SECRET_PREVIOUS` | `None` | Only during a staged rotation of the sweep secret: the old value, accepted beside `JOBS_SECRET` (constant-time, every candidate compared). `deploy.yml` reads it from the optional `SWEEP_JOBS_SECRET_PREVIOUS` environment secret. See §5.2 "Rotating the secret". |
| `LEMELY_NOTIFICATIONS__SWEEP_PASS_BUDGET_SECONDS` | `60` | Wall-clock budget of one sweep pass (loop or trigger); jobs not started when it is spent are skipped until the next tick. Keep it at least 30 s under the Scheduler job's 90 s attempt deadline. Settings refuse a budget that, plus one saved-card charge's worst case, would pass 210 s (the sweep lock's 240 s idle timeout less 30 s). See §5.2. |
| `LEMELY_NOTIFICATIONS__SWEEP_ROW_SECONDS` / `__SWEEP_PAYMOB_REQUEST_SECONDS` / `__SWEEP_ROW_HARD_SECONDS` | `1.0` / `7.0` / `5.0` | How long the sweep expects one row's database work and one Paymob request to take, and the most a row's database work may take. A unit of work starts only while its expected time fits the pass budget and its worst case ends inside the 210 s limit. See §5.2. |
| `LEMELY_PAYMOB__TIMEOUT_SECONDS` / `__CONNECT_TIMEOUT_SECONDS` / `__WRITE_TIMEOUT_SECONDS` / `__POOL_TIMEOUT_SECONDS` | `20` / `5` / `5` / `5` | Paymob client timeouts (read, connect, write, pool). Their sum is the worst case of one request, which the sweep's time limits are built on; raising them can make the settings check above fail at startup. |
| `LEMELY_EMAIL__APP_BASE_URL` | `https://lemelyig.com` | The origin emailed verification/reset links are built on. Links are minted as frontend routes (`/verify-email/<token>`), so without an origin a mail client resolves them to `http:///…` — unreachable. `deploy.yml` sets it per environment (`staging.lemelyig.com` vs `lemelyig.com`). Rejected at startup unless it has both a scheme and a host. |
| `LEMELY_EMAIL__API_KEY` | `None` | To actually send verification / password-reset mail (Resend). Absent is a **supported** state: `lemely.web.deps` wires the offline mock, which logs the link and code and lets the auth routes return them, so sign-up works with no mail service. Setting it flips both halves — mail sends *and* the routes stop returning the live credentials. Optional companions: `__FROM_ADDRESS` (`noreply@lemelyig.com`), `__FROM_NAME` (`Lemely`), `__REPLY_TO`, `__CONTACT_ADDRESS` (`contact@lemelyig.com`, the inbox that receives landing-page FAQ questions from `POST /api/contact`). On the deployed pipeline this is not set by hand: it is the `RESEND_API_KEY` Actions environment secret, which `deploy.yml` passes through as this variable. See `docs/email-delivery.md` for the Cloudflare DNS records and `docs/ci-cd.md` for the secret. |
| `LEMELY_STORAGE__BACKEND` | `local` | Set `gcs` for any deploy that isn't local dev/Compose/CI — see [§5.1](#51-the-single-replica-constraint-is-lifted). `local` writes under `paths.output_dir/storage` on the container's own disk. There is no Supabase Storage backend; that code was deleted (DS7). |
| `LEMELY_STORAGE__BUCKET` | `lemely-uploads` | **Always on a real deploy.** The bucket (`gcs`) or directory name (`local`) for scans and mark schemes. `deploy.yml` sets it per environment to `<project-id>-uploads-<env>`; GCS bucket names are one global namespace, so the default is a placeholder no project owns. **The bucket must already exist** — no application code path creates it; `scripts/gcp-bootstrap.sh` does. Empty is rejected at startup. |
| `LEMELY_STORAGE__AVATAR_BUCKET` | `lemely-avatars` | Same rules, for profile pictures — a separate bucket because avatars are meant to persist and the uploads bucket carries a 90-day delete rule. `deploy.yml` sets `<project-id>-avatars-<env>`. |
| `LEMELY_STORAGE__TUTOR_EVIDENCE_BUCKET` | `lemely-tutor-evidence` | **Always on a real deploy that lets tutors upload documents.** A separate private bucket for tutor qualification documents (personal data, opened only by a platform admin through a `LEMELY_STORAGE__TUTOR_EVIDENCE_SIGNED_URL_TTL_SECONDS` (default `300`) link). Same rules as the other buckets: it must already exist, and the default is a placeholder no project owns. `deploy.yml` sets it per environment to `<project-id>-tutor-evidence-<env>` (override: the `GCS_TUTOR_EVIDENCE_BUCKET` environment variable) and `scripts/gcp-bootstrap.sh` creates that bucket private, but only when an operator runs the script. Unlike the other two, the `gcs` backend refuses the default name outright and checks that the bucket is private and owned by `LEMELY_STORAGE__GCS_PROJECT_NUMBER` before its first use; see §5.10. |
| `LEMELY_STORAGE__GCS_PROJECT_NUMBER` | `None` | **Always on a `gcs` deploy that lets tutors upload documents.** This project's number (not its id): the `gcs` backend uses the evidence bucket only if this project owns it, and refuses it while this is unset (uploads and avatars are unaffected). `deploy.yml` derives it from the `GCP_WORKLOAD_IDENTITY_PROVIDER` variable (`projects/<number>/...`); by hand, `gcloud projects describe <project-id> --format='value(projectNumber)'`. Ignored by the `local` backend. See §5.10. |
| `LEMELY_TUTORING__EMAIL_DAILY_CAP` | `60` | At most this many tutoring emails are sent in any 24 hours, because the free Resend tier allows 100 a day and shares them with sign-up mail. Sent rows beyond it are recorded as skipped. See §5.10 and `docs/email-delivery.md`. |
| `LEMELY_STORAGE__SIGNED_URL_TTL_SECONDS` | `3600` | How long an avatar URL stays readable. Ignored by the `local` backend, which returns the bytes inline and so has nothing to expire. |
| `LEMELY_STORAGE__GCS_PROJECT` | `None` | Only if Application Default Credentials cannot infer a project on their own (rare — a workload identity usually carries one). |
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
5. Create the two object-storage buckets — one for scans and mark schemes,
   one for profile pictures. **No application code path creates either**, and
   uploads or avatar sets fail against a missing bucket.

   Which kind depends on `LEMELY_STORAGE__BACKEND` (§2). `local` needs no
   bucket at all, writing under `paths.output_dir/storage`. `gcs` needs two
   real Google Cloud Storage buckets the runtime identity can write, which
   `scripts/gcp-bootstrap.sh` creates for both environments in one run — along
   with the runtime service accounts, the 90-day lifecycle rule on uploads, the
   `serviceAccountTokenCreator` grant that avatar signed URLs need, and
   (optionally) the billing budget:

   ```bash
   PROJECT_ID=<gcp-project-id> BILLING_ACCOUNT_ID=<id> BUDGET_USD=25 \
     ./scripts/gcp-bootstrap.sh
   ```

   There is no longer a Supabase Storage backend; that code was deleted (DS7).
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
| Any instance count | Used to be pinned to exactly one — see [§5.1](#51-the-single-replica-constraint-is-lifted) for what changed and what the deploy still sets today. |
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

### 3.5 Grade thresholds must be ingested separately — migrations do not seed them

`alembic upgrade head` creates `component_thresholds` and `option_thresholds`
(`0025_thresholds`, `0026_component_max_mark_positive`) but inserts **zero rows into
either**. Unlike `0024_reference_catalogue`'s subjects/papers/topics, CAIE grade
thresholds are not embedded as migration literals — they come from a live ingest
(`scripts/ingest_thresholds.py`) that fetches ciegt.pooruli.com's transcription and
verifies every row against the official Cambridge PDF before storing it (D2/D8 of
the design spec). A migration can't do that: it would either embed unverified
numbers as literals or make schema replay depend on a live network call, both wrong.

**This means `alembic upgrade head` alone leaves grading unusable.**
`GradeBoundaryStore` (`lemely/io/grade_boundaries.py`) raises
`EmptyGradeBoundaryStoreError` rather than grade against invented boundaries when
`component_thresholds` has zero verified rows — a deliberate regression fix: an
earlier version of this store silently fell back to a hardcoded, wrong global
default (e.g. it would award a Core paper, capped at C, a fabricated A). The refusal
is correct, but it is also loud: every grading request 500s until ingest has run.

Run once per environment, after migrations and before any grading traffic:

```bash
python scripts/ingest_thresholds.py
```

Or from CI, which is the same script with the environment's `SUPABASE_DB_URL`
already to hand: Actions tab → **deploy** → Run workflow → pick the environment
and tick **"Also ingest CAIE grade thresholds"**. That job is dispatch-only and
off by default, and it asserts afterwards that at least one *verified* row
landed — the script itself exits 0 even when every document was unreadable
(`verified=0`), so the exit code alone is not evidence the environment can
grade.

It targets the three subjects this build supports (`--subjects 0580 0606 0625` is
the default) and reads `LEMELY_DATABASE__URL` the same way Alembic does. It makes
real HTTP requests to ciegt.pooruli.com and pastpapers.papacambridge.com (one
syllabus request plus one PDF per session, paced 2s apart — see the script's own
docstring), so run it from a machine with outbound internet access to the database,
not from inside a network-isolated container. It is safe to re-run: every write is
an `ON CONFLICT DO UPDATE` keyed on the row's identity, so a second run updates in
place rather than duplicating.

> **Any database ingested by a build older than this release must re-run this
> once.** Earlier builds marked a row `verified` after checking only its
> threshold *values* against the PDF — the row's `max_mark` came from ciegt's
> transcription and was never verified, while the row cites the Cambridge PDF as
> its source. Because every grade is a percentage of `max_mark`, a wrong
> denominator moves every boundary on that paper. The fix lives in
> `scripts/ingest_thresholds.py::verify_row`, **not** in a migration, so
> `alembic_version` cannot tell you whether a given database is affected —
> `alembic upgrade head` does not repair the stored rows. Count the exposure with
> `SELECT count(*) FROM component_thresholds WHERE verified;`: every one of those
> rows was verified under the old rule until the ingest is re-run. Re-running
> `scripts/ingest_thresholds.py` re-verifies and updates every row in place.

**Verify it worked** with `GET /api/health` — `gradeBoundariesLoaded: true` means at
least one verified row exists. `false` has two causes, and the backend log
distinguishes them: a line reading `health: could not read grade boundaries from
the database` means the **database could not be read**, not that ingest is missing;
without it, ingest either has not run or failed partway (check the run's own
printed report: `components=… verified=… options=… `). That line is written on
**every** failing poll, so it is present in any recent log window, not only at the
moment the outage began.

> Scope: the boundary store is cached for the life of the process, so this flag
> reports the state at **first load**. A database that becomes unreachable *after*
> boundaries have loaded leaves `gradeBoundariesLoaded: true` — this is a deploy-time
> readiness signal, not a live database monitor.

This is not wired into `docs/ci-cd.md`'s `deploy.yml` pipeline (deliberately left
alone here — see that doc's own notes on this gap). Until it is, treat this as a
manual one-time step per environment, same as creating the Storage bucket in §3.2.

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

`.github/workflows/deploy.yml` now sets `--max-instances=3`. That number is a
cost ceiling, not a correctness one: nothing below depends on the instance
count, and three is simply enough to absorb a spike while a runaway cannot fan
out to a hundred containers. `--min-instances=0` is unchanged, so idle time
still costs nothing and the first request after idle still pays a cold start.

The multi-instance behaviour described here has not yet been observed against
a real deployment — this branch has never been deployed. The verification
checklist in the design spec's §8 exists to exercise it on staging, and until
someone runs it, everything below is what the code is built to do rather than
what has been seen to happen.

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
| OTP challenge store | `lemely/auth/otp.py::OtpStore` | In-memory — issued on one replica, verified on another, verification fails. | Postgres-backed (`DbOtpStore`, migration `0025`) — a code minted on one instance verifies on any other, keyed by channel. Parent sign-up and email verification both key off `channel=email`, which is the live path since `BUILD/DECISIONS.md` D-2026-09-08; the phone channel still shares this table but backs a kept-but-unused seam that no route reaches. |
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

### 5.2 The notification sweeper runs inside the API process, and Cloud Run can scale it to nothing

`create_app` starts one asyncio task (`lemely/web/app.py`, `_lifespan`) that every
`[notifications] sweep_poll_seconds` (60) runs the sweeper's jobs: five notification jobs
from `lemely/web/scheduled_notifications.py` (below) alongside the billing, usage and seat
sweeps. It publishes announcements whose `publish_at`
has passed, sends `streak_warning` at `streak_warning_hour` (19:00) and
`study_plan_reminder` at `study_plan_reminder_hour` (08:00) (each in the recipient's
**own** time zone, `users.timezone`), and purges expired student and console papers
(`purge_expired_papers`, `purge_expired_teacher_papers`) past their retention window.
There is no separate worker to deploy, and no cron to add. Two replicas are safe — the
announcement claim is `FOR UPDATE SKIP LOCKED` and every notification is deduped by
the unique index on `notifications` — but §5.1 still limits you to one for other
reasons.

**The loop alone cannot work at `--min-instances=0`, which is what `deploy.yml` sets.**
At zero instances the container is not running, and while an instance is warm but idle
Cloud Run throttles its CPU, so no sweep happens. That covers more than notifications:
the sweeper also runs the billing and usage jobs (payment reconcile, subscription
period-end, overdue and drift sweeps, grant and hold expiry, auto top-up, the fallback
seat charge, signup-grant repair, manual-subscription expiry and the daily usage
reconcile at or after 02:00 UTC). A 19:00 streak warning missed that way is **skipped for
that day** (the per-zone memo and the dedupe key are scoped to the user's civil date), and
a payment that was paid but never reconciled stays pending.

**Decision: Cloud Scheduler calls an authenticated endpoint, instead of an always-on
instance (`--min-instances=1` with CPU always allocated).** Scheduler runs one sweep pass
through `POST /api/internal/jobs/sweep` every minute. The request wakes the service and
keeps its CPU allocated for the length of the pass, so the platform stays scale-to-zero and
costs a request a minute rather than a permanently billed instance. The in-process loop is
**switched off on Cloud Run** once the Scheduler job is in place: once its request ends an
instance's CPU is throttled, so a loop pass could stall mid-pass while holding the pass lock and
hold off the Scheduler calls behind it. The loop stays on by default for local runs and hosts
with always-on CPU.

- **Who drives the sweep is decided at each deploy.** Before the new revision is created, the
  `Decide who drives the sweeper` step in `deploy-backend`
  (`scripts/scheduler_reconcile.py --sweep-driver`) lists the environment's Scheduler jobs and
  sets `LEMELY_NOTIFICATIONS__SWEEPER_ENABLED=false` only when `lemely-<environment>-sweep`
  exists, is `ENABLED`, carries the `managed-by=lemely-deploy` marker and calls this
  environment's `/api/internal/jobs/sweep`. Otherwise it sets `true`. On the first deploy that
  introduces the job, the revision therefore keeps its loop (the job is created only at the end
  of that deploy), and the next deploy turns the loop off. A failed listing also keeps the loop
  on: two drivers are safe, because the pass lock lets one pass run at a time, while no driver
  is not. The check reads no secret and ignores the job's header, so rotating the secret never
  changes the setting and never recreates the job.
- **If the reconcile fails while the loop is off**, the job may be missing or broken and nothing
  runs billing passes. The deploy then fails with `billing sweep driver absent` and prints the
  command that turns the loop back on until a later deploy reconciles the job:
  `gcloud run services update lemely-backend-<environment> --region=us-central1 --project=PROJECT_ID --update-env-vars=LEMELY_NOTIFICATIONS__SWEEPER_ENABLED=true`.
  The next successful deploy sets the value again from the job's state.
- **Open question: CPU after the caller disconnects.** Whether Cloud Run keeps CPU allocated to a
  request after Cloud Scheduler stops waiting for it at the 90 s attempt deadline has not been
  verified for this service. A pass is built to end well inside 90 s; if it ever runs on without
  CPU, the lock's 240 s idle timeout (below) still frees the lock.

- **What one pass is:** exactly what one loop tick runs (`Sweeper.sweep_exclusive`, the one
  entry point of both the loop and the endpoint), including the
  time-of-day-gated daily usage reconcile once it is due, and nothing the loop does not run.
  Without Paymob configured the Paymob-backed jobs are simply not part of the pass, as in the
  loop. A job that raises is logged as `sweep_job_failed` (the event alerts key on), reported
  as `null` in the response, and does not stop the others.
- **Response** (200, no customer data, job names and counts only):
  `{"status": "completed", "jobs": {"billing.reconcile_pending": 2, ...}, "failed": [], "skipped": []}`.
  `failed` lists the jobs that raised; the status stays 200 so Scheduler does not retry a whole
  pass because one job is unhealthy. `skipped` lists the jobs not started because the pass
  budget was already spent (below): not failed, the next pass runs them again in the usual order.
- **Time budget.** One pass is bounded to `[notifications] sweep_pass_budget_seconds` (default
  **60 s**) of wall clock, counted from the start of the call, before the pass waits for a
  database connection or the lock. The Scheduler job has a 90 s attempt deadline and Cloud Run's
  request timeout is 300 s, so 60 s leaves 30 s for a cold start, the proxy and the unit in flight
  when the budget ends (a test keeps the budget at least 30 s under the deadline). Jobs not
  started when it is spent are skipped (`sweep_pass_budget_spent` warning, listed in `skipped`).
- **Units of work.** The batches stop *between* units, never inside one: a subscription row, a
  payment inquiry, a database-only row, or a saved-card charge, which is never interrupted once
  claimed. A unit starts only if its expected time fits what is left of the budget
  (`sweep_row_seconds` plus `sweep_paymob_request_seconds` for each Paymob request it usually
  makes: 15 s for a charge's two requests) and if its worst case (`sweep_row_hard_seconds` plus
  the sum of the Paymob timeouts for each request it can make) would end within 210 s of the
  start, the lock's 240 s idle timeout less 30 s. That worst case is planning arithmetic, not a
  wall-clock guarantee: it assumes the instance keeps its CPU (a read timeout also bounds each
  read, not a whole slow response), and Cloud Run's documentation does not promise CPU to a
  request-billed instance once Scheduler has disconnected. The one limit enforced whatever the
  instance does is Postgres ending the lock transaction after 240 s idle (below). Batches that
  call Paymob under the auth token renew a token about to expire before their first row, so the
  renewal is timed before any row starts. A pass that still runs past its budget (one slow
  charge) logs `sweep_pass_overran` with the elapsed time; that is not a job failure.
- **Fairness.** Each batch also has a slice of the budget from its own start (`RECONCILE_SHARE`
  13 %, `EXPIRE_OVERDUE_SHARE` and `PERIOD_END_SHARE` 10 %, `DRIFT_CHECK_SHARE` 15 %,
  `EXTRA_SEAT_RENEWAL_SHARE` 10 %), after which it starts no further unit; its first unit always
  starts while the budget admits it. With every backlog full, the two saved-card batches (the
  extra-seat renewal, then the auto top-up) do not both fit one 60 s pass, so they alternate
  priority in five-minute windows (`PAYMENT_TURN_MINUTES`) counted from the pass's own clock:
  the extra-seat renewal has priority in the even windows, the top-up in the odd ones. The
  priority needs no stored state, so every replica agrees on it. Every batch before the one with
  priority leaves a 16 s planning reserve free, the estimated time of one database row (for the
  top-up, one refusal row) and one charge; on its own windows the seat batch leaves only the
  charge's 15 s free while it works through its rows. The other saved-card batch still runs in
  its place and uses whatever is left. Priority is not a minimum charge per pass. The reserve
  holds only under the modelled timings: a top-up refusal step with more rows than one, or a
  job after the reserve is set that does not check the budget, can use it up, and the batch
  with priority then starts no charge on that pass. A test runs passes on a fake clock with
  every unit at its expected time and shows the batch with priority starting a charge when the
  jobs before the reconcile take up to about 44 s. Priority also depends on the trigger
  cadence: the shipped Scheduler job fires every minute, so each window gets several passes,
  but a trigger aligned to every 10 minutes would land in the same window parity each time and
  one batch would never get priority. The price is that the subscription batches give up their
  later units to that reserve first: once the jobs before the reconcile take more than about
  5 s, the drift check starts no row on a full-backlog pass under those timings. None of this is
  a throughput guarantee: a queue that grows faster than its batch charges on its own windows
  still drains too slowly, and the extra-seat grace can end before an attempt reaches it. The
  rows a batch leaves are still due and are taken by a later
  pass. The job order itself is load-bearing (an expired plan's seats are handled before the
  next month's grant), so it is fixed and never rotated. A persistent `skipped` list, or batches
  that never drain, are the signal to raise the budget and the Scheduler attempt deadline
  together (the settings check above bounds how far), or to shorten the batches.
- **Per-process memory.** The daily usage reconcile's memo and the signup repair's cursor live in
  each process's sweeper, not in the database. A cold start, or a pass that lands on another
  replica, repeats the daily check and restarts the repair scan from the beginning, inside the
  pass budget like any job. That repeats idempotent work and changes no result.
- **No retries.** The Scheduler job is created with `--max-retry-attempts=0` and
  `--attempt-deadline=90s` (per-job policy in `.github/scheduler-jobs.json`; the digest keeps
  its 3 retries and 6-minute backoff, which its claim lease needs). A retry of a pass that
  overran would land while the first pass still holds the lock, and Scheduler skips later runs
  while an execution is outstanding; the next minute's call is the retry.
- **Overlap.** A pass holds the Postgres advisory lock `lemely.sweeper.pass`
  (`pg_try_advisory_xact_lock`, `Sweeper.sweep_exclusive`) for its whole length. The in-process
  loop, where it is enabled, takes the same lock, so a loop pass and a trigger never run side by
  side. A second call,
  on this instance or another, returns at once with
  `{"status": "skipped", "jobs": {}, "failed": [], "skipped": []}` (200) and logs
  `sweep_pass_skipped`. The lock is released however the pass ends (an exception included), or
  when its connection dies. It is an overlap guard, not a correctness guard: every job is
  idempotent by row state, exactly as with two replicas' loops, so a lock lost to a dropped
  connection costs a duplicate pass, not a duplicate effect. The lock's transaction sets
  `idle_in_transaction_session_timeout = '240s'` for itself only (`SET LOCAL`): if a pass stalls
  (a hung worker, throttled CPU), Postgres ends that transaction and frees the lock within four
  minutes, under Cloud Run's 300 s request timeout, so one stalled pass cannot block every later
  call. The stalled pass is then reported as failed; the jobs it already ran stay done.
- **Connection pool.** The lock holds one pooled connection, idle in its transaction, for the
  whole pass while every job opens its own session, so `[database] pool_size + max_overflow`
  must be at least **2**. Settings refuse a smaller value at startup (a pool of 1 with no
  overflow would make every pass wait out `pool_timeout_seconds` for a connection it holds
  itself). The defaults are 5 and 10.
- **Auth.** Header `X-Cron-Secret`, the digest endpoint's scheme, compared in constant time.
  Missing or wrong: 403. No secret configured: **503**, not the digest's 404 (the Scheduler job
  exists and is failing, which should be visible). The secret is
  `LEMELY_NOTIFICATIONS__JOBS_SECRET` on the service, GitHub environment secret
  `SWEEP_JOBS_SECRET` (a random string, separate from `WAITLIST_DIGEST_SECRET`): at least 32
  characters from letters, digits and `_ . ~ + / : = @ -`, no whitespace (for example
  `openssl rand -hex 32`).
- **A missing secret stops the deploy.** The new revision answers 503 on this route without it,
  and nothing else would ever run the billing sweeps at zero instances, so the
  `Preflight the sweep secret` step in the `migrate` job
  (`scripts/scheduler_reconcile.py --preflight`, before Alembic runs, so before any migration,
  image build, frontend deploy or traffic switch) fails the deploy while the old revision still
  serves when `SWEEP_JOBS_SECRET` is missing,
  blank, shorter than 32 characters, or has characters that are not header-safe. It prints
  which check failed, never the value. The reconcile step treats a missing secret for this job
  as an error too (the digest's missing secret is still only a warning).
- **Rotating the secret (two phases, no failed run).** The service and the Scheduler job learn
  a new value at different points of one deploy (the revision takes traffic first, the job is
  updated last), so a plain swap would send the old value to the new revision. Stage it:
  1. Set GitHub environment secret `SWEEP_JOBS_SECRET_PREVIOUS` to the **old** value and
     `SWEEP_JOBS_SECRET` to the **new** one. Deploy. The service accepts either
     (`LEMELY_NOTIFICATIONS__JOBS_SECRET_PREVIOUS`, every candidate compared in constant time,
     none short-circuited), and the reconcile step rewrites the Scheduler job with the new value.
  2. Confirm one Scheduler run succeeded with the new value: run
     `gcloud scheduler jobs run lemely-<environment>-sweep --project=PROJECT_ID --location=us-central1`
     and read the job log for a 200 **timestamped after the reconcile step updated the job**. A
     200 from before that update was made with the old value and proves nothing.
  3. Only then delete `SWEEP_JOBS_SECRET_PREVIOUS` (or blank it) and deploy again. The old value
     is refused from then on. The preflight rejects a `PREVIOUS` equal to the current secret, so
     a rotation cannot be half-staged by mistake.

  **Rolling back mid-rotation.** Once step 1's reconcile has written the new value into the
  job, rolling the service back to a revision that knows only the old value makes every
  scheduled call fail with 403. Re-run the reconcile with the old value as `SWEEP_JOBS_SECRET`
  (restore the secret and redeploy, or run `scripts/scheduler_reconcile.py` with it set) so the
  job and the serving revision agree again, then start the rotation over.
- **Who can read the secret.** Whoever can read the Scheduler job can read the sweep credential:
  the job carries `X-Cron-Secret` in its HTTP headers, and `gcloud scheduler jobs describe`
  returns them. Restrict `cloudscheduler.jobs.get` / `list` (Cloud Scheduler Viewer and up, and
  anything broader that includes them) to the deploy account and the owners, and treat a leaked
  job description as a leaked secret: rotate as above. The same holds for the digest job.

**Scheduler job.** `deploy.yml` creates it for you: the `sweep` entry in
`.github/scheduler-jobs.json` is reconciled on every deploy (see `docs/ci-cd.md`, "Cloud
Scheduler jobs"), as `lemely-<environment>-sweep`, in `us-central1` like the digest job, once
`SWEEP_JOBS_SECRET` is set for that environment. The schedule is **`* * * * *` UTC**: one
minute is Cloud Scheduler's shortest interval and matches the loop's `sweep_poll_seconds`
(60 s), so scheduled announcements and the 19:00 / 08:00 notifications are as timely on Cloud
Run as the loop makes them elsewhere. A call that finds a pass already running costs
almost nothing, and the schedule can be relaxed (`*/5 * * * *`) if the request count matters
more than minute-level timing. The equivalent manual commands, for a project where the
reconcile step has not run (replace `PROJECT_ID`, and `SECRET` with the value of
`SWEEP_JOBS_SECRET`; staging first, then production):

```
gcloud scheduler jobs create http lemely-staging-sweep \
  --project=STAGING_PROJECT_ID --location=us-central1 \
  --schedule="* * * * *" --time-zone=UTC \
  --uri="https://staging.lemelyig.com/api/internal/jobs/sweep" --http-method=POST \
  --headers="X-Cron-Secret=SECRET" \
  --max-retry-attempts=0 --attempt-deadline=90s \
  --description="managed-by=lemely-deploy; id=sweep; Billing and notification sweeper pass"

gcloud scheduler jobs create http lemely-production-sweep \
  --project=PRODUCTION_PROJECT_ID --location=us-central1 \
  --schedule="* * * * *" --time-zone=UTC \
  --uri="https://lemelyig.com/api/internal/jobs/sweep" --http-method=POST \
  --headers="X-Cron-Secret=SECRET" \
  --max-retry-attempts=0 --attempt-deadline=90s \
  --description="managed-by=lemely-deploy; id=sweep; Billing and notification sweeper pass"
```

These are the flags the reconcile step issues, and the `managed-by=lemely-deploy` description
marker lets the next deploy adopt and update the job instead of failing on a name clash. Run one
by hand with
`gcloud scheduler jobs run lemely-<environment>-sweep --project=PROJECT_ID --location=us-central1`
and read the job log: 200 is a completed or skipped pass, 403 a wrong secret, 503 an unset one.
A pass is bounded to 60 s so it finishes inside the 90 s attempt deadline and Cloud Run's
300 s request timeout (see "Time budget" above); there are no Scheduler retries.

The same gap affected purge before this endpoint: a paper past its retention cutoff was not
deleted from storage until the next sweep ran. The purge query is idempotent and its cutoff is
inclusive, so a missed sweep is never a *skip*, only a late purge. The admin pipeline health
screen's `purgeBacklog` metric (`lemely/db/admin_repo.py`, `pipeline_health`) is the check
that the Scheduler job is actually running: a count that runs persistently above zero means
it is not.

At-risk rule 3 (≥14 days inactive) is still **not** delivered by anything: the alert
fires on correction, and a student who just uploaded is by definition active.

### 5.3 `make seed` seeds demo credentials — never run it against production

**Resolved in P6.10** (this section previously recorded that `seed_reference_data`
and `seed_demo_accounts` were stubs with a bare `pass`, so `make seed` inserted zero
rows and created zero accounts while logging a cheerful `db.seed.done`).

`make seed` now inserts the three supported subjects and creates one account per
role, with **fixed, published credentials** — `<role>@demo.lemely.local` /
`Demo-Lemely-1!`, including the parent, created through the same email signup
path as the other demo roles and linked directly to the demo student — no
invite is minted or redeemed for it. The full table is in
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

### 5.5 Profile pictures go missing quietly when a signed URL cannot be signed

`GET /api/me/profile` answers `avatarUrl: null` both when no picture is set
and when object storage could not sign a URL for the one that is
(`_avatar_url_for` in `lemely/web/routers/me.py` never fails a profile read).
The UI cannot tell the two apart, so a signing failure looks exactly like "I
never uploaded a picture" — the upload returns 200, and the avatar is the
initials monogram everywhere, forever.

Nothing surfaces it except the log line. Check for it first:

```bash
gcloud logging read \
  'resource.type="cloud_run_revision"
   AND resource.labels.service_name="lemely-backend-<env>"
   AND jsonPayload.event="avatar_signed_url_failed"' \
  --project=<gcp-project-id> --limit=5 --freshness=7d
```

Signing on Cloud Run goes through the IAM `signBlob` API, because a
workload-identity credential has no local signer. That needs **two** separate
things, and only the first is an IAM grant:

* `roles/iam.serviceAccountTokenCreator` on the runtime service account, for
  itself — `scripts/gcp-bootstrap.sh` grants it.
* An access token scoped for `cloud-platform`. `storage.Client.SCOPE` is the
  three `devstorage.*` scopes only, so the credential the storage client holds
  refreshes to a storage-only token that `signBlob` refuses with
  `ACCESS_TOKEN_SCOPE_INSUFFICIENT` — a 403 no IAM policy change can fix.
  `GcsStorageBackend._signing_token` mints a second, correctly scoped
  credential for the signature; the storage client's own token is never reused.

### 5.6 Security posture as shipped

Good already: the backend image runs **non-root** (`Dockerfile:45,67`), carries no
compiler toolchain and no dev/test dependencies, and all 121 route operations are
authz-guarded with a generated matrix test that fails on drift (P6.3). Secrets are
`SecretStr` and are never hardcoded in the compose file — only the local-dev JWT
secret is, and §2 says why that must be overridden.

Still needed for anything public-facing, none of it built here: TLS termination
(nginx listens on plain `:80`), a rate limiter on the auth endpoints, and log
shipping. `LEMELY_LOGGING__FORMAT=json` is the one lever that already exists.

### 5.7 Rollback

**Rolling back past the paper-deletion release (migration `0039_paper_soft_delete`)
needs a forward fix, not a Cloud Run revision rollback.** Pre-0039 code cannot read
the two new enum values a revision rollback leaves in place: a teacher who has
received a `review_withdrawn` notice gets a `LookupError` (500) opening their inbox,
and every place that used to apply the soft-delete loader criterion stops applying
it, so deleted papers — including any already purged from storage — reappear in
history, averages and parent views. A schema-only `alembic downgrade` doesn't avoid
this either: dropping `deleted_at` makes deleted papers visible again on its own,
regardless of which code is running.

If a Cloud Run revision rollback is genuinely unavoidable, run these two statements
against the database **before** rolling back, and expect deleted papers to stay
visible until the roll-forward:

```sql
DELETE FROM notifications WHERE type = 'review_withdrawn';
UPDATE review_queue SET status = 'dismissed' WHERE status = 'withdrawn';
```

The safe path is always a forward fix on top of `0039`, not a rollback under it.

**Rolling back past the tutoring marketplace (migrations `0044_tutoring_enums_ext` to
`0051_tutor_evidence_uploads`) has the same shape.** Pre-0044 code cannot read the eight
tutoring notification types (`booking_request`, `booking_update`, `booking_note`,
`tutor_access`, `tutor_review`, `tutor_listing`, `parent_link`, `tutoring_report`), so
anyone holding one gets a `LookupError` (500) opening their inbox. If a Cloud Run
revision rollback across that release is unavoidable, run this **before** rolling back:

```sql
DELETE FROM notifications WHERE type IN ('booking_request','booking_update','booking_note','tutor_access',
  'tutor_review','tutor_listing','parent_link','tutoring_report');
```

Tutoring profiles, bookings and grants are then invisible, not lost, until the
roll-forward. A schema downgrade past `0044` also drops the eight tutoring
notification toggles from `notification_preferences`. On the roll-forward they come
back as `true` for everyone, so users who had opted out of one of those notices start
receiving it again. Downgrading past `0049` destroys the tutor access audit log:
snapshot `tutor_access_audit` first. As with `0039`, the safe path is a forward fix.

### 5.8 Answer binding: the settings, what changes on first start, the way back

Marking a scanned script now ties each answer to its question by the question
labels the model sees, then checks that tie before anything is marked
(`lemely/io/binding`, `lemely/core/binding_gate.py`). A paper whose answers cannot
be trusted to sit on the right questions is **held**: not marked, not stored, no XP,
no "your paper is marked" notification, and the upload ends `failed` with a fixed
sentence. A question whose answer could not be tied to it at all is stored as an
unmarked zero, flagged for the teacher.

**Settings** (`[binding]` in `lemely.toml`, or the environment):

| Variable | Default | Meaning |
|---|---|---|
| `LEMELY_BINDING__BINDER` | `label` | `label`: the model lists labels and writing, and the code binds them to the mark scheme. `legacy`: the model hands out question ids itself, as before this change. |
| `LEMELY_BINDING__GATE` | `enforce` | `enforce`: a paper that fails the checks is held. `observe`: the checks run and are logged, nothing is held and the check after marking does not run. `off`: no checks. |
| `LEMELY_BINDING__READ_MODEL` | `gemini-3.8-flash` | The label binder's model. Only this model returned a usable list when it was measured; the extraction default is a cheaper model that did not. |
| `LEMELY_BINDING__SECOND_READ` | `true` | Read the script a second time (task tag `binding_second_read`) so two reads can be compared and a bad first read replaced. Doubles the binding step's cost. |
| `LEMELY_BINDING__RETRY_MODEL` | `gemini-3.8-flash` | The model of the legacy binder's one retry. |

**What changes on first start.** Nothing needs migrating, and the defaults are the new
behaviour: every scanned paper except one that is all multiple choice (next
paragraph) goes through the label binder, with two reads of the script on
`gemini-3.8-flash`, and every marker cache entry is cold once (the marker prompt
changed). The cost and time that were measured: one pilot
paper (a 19-page theory script) ran the whole sequence (extraction with both reads,
the checks, marking) in 572 s for $0.197, and used 157,824 tokens
(`.superpowers/sdd/task-13-report.md`). That is one paper; there is no distribution
behind it. The paper shapes read live so far are **one theory paper**: other
subjects, multiple-choice papers and handwriting styles have not been read with the
label binder against a real scan, so watch the hold rate (below) after the first
real traffic.

**A paper that is all multiple choice keeps the legacy binder.** When every marked
question of the mark scheme is multiple choice, the paper is read by the legacy
binder under the configured gate (one read, and one retry on
`LEMELY_BINDING__RETRY_MODEL` if the checks fail), whatever `LEMELY_BINDING__BINDER`
says. The reason is that the label binder is unmeasured on that shape: it has been
read live on one theory paper and on no multiple-choice scan, so the shape keeps the
behaviour it had before. Such a paper's `binding_gate_result` line carries
`binder="legacy"` and `binder_by_paper_shape=true` (the field is `false` when
`legacy` is what was configured). The rule is in code
(`lemely/io/binding/orchestrate.py`, `binder_for`), not a setting; what lifts it is a
live read of a multiple-choice scan by the label binder that passes, followed by a
code change.

**The way back is configuration, not a revision rollback.** Set
`LEMELY_BINDING__BINDER=legacy` and `LEMELY_BINDING__GATE=off` and restart: extraction
is then what it was before this change. The gate cannot be off under the label
binder (startup refuses `binder="label"` with `gate` other than `enforce`, because
its coverage and lost-item checks are what stops lost writing being published as a
blank), so switch both together. `gate="observe"` with `binder="legacy"` keeps the
checks running and logged without holding anything, which is the way to watch the
gate before trusting it. Rolling the Cloud Run revision back is not needed to
undo this: the console's stored reports (`teacher_papers.report_json`) are kept in
the pre-change shape, so older code still loads them, but that is a safety net, not
the plan.

**Two log lines to watch.**

- `binding_gate_result`: one per scanned paper. Carries the binder, the gate mode,
  the failed check ids (`G1` to `G9`), whether the second read replaced the first
  (`retried`), the items the reader's reply lost (`drops`) and the unaligned leaf
  count and reasons.
- `binding_held`: one per held paper, from the student upload job (`upload_id`) and
  the teacher console job (`paper_id`). Carries the verdict, the `stage`
  (`before_marking` or `after_marking`), the failed check ids and the reasons.

A rising share of `binding_held` among scanned papers means scans are arriving with
pages missing or out of order (the usual cause, and the sentence the student sees
says so), or that the reader is failing on a paper shape it has not been measured
on. Group by `failed_checks` first: a single check dominating points at one cause.
If the rate stays high on ordinary scans, switch to the legacy binder by
configuration while it is investigated. A held paper has no queue yet (that is plan
1B): the student uploads again, the teacher re-runs or uploads again. A held paper,
whether it was held before marking or after, is read afresh on a re-run: its reads
are removed from the response cache when it is held, so the same reads cannot bring
the same hold back (the marker's cached replies are kept).

### 5.9 Roll back to Gemini (config only)

Since sub-project C every task tag defaults to `claude-haiku-5-5`. To run the pre-flip
Gemini configuration with no code change and no Anthropic key, put this in `lemely.toml`
(or set the same keys as `LEMELY_GEMINI__*` / `LEMELY_BINDING__*` variables). TOML cannot
write `None`, so `adjudication_model = ""` is how adjudication is turned off (and
escalation is back on, as it was). `lemely doctor` then passes without `ANTHROPIC_API_KEY`
and needs `GEMINI_API_KEY`. `tests/test_claude_default_flip.py` loads this exact block.

```toml
[gemini]
model = "gemini-2.5-flash"
mark_scheme_model = "gemini-2.5-flash"
extraction_model = "gemini-3.5-flash-lite"
correction_model = "gemini-3.1-flash-lite"
generation_model = "gemini-3.5-flash-lite"
scan_metadata_model = "gemini-3.5-flash-lite"
escalation_model = "gemini-3.8-flash"
escalation_confidence_threshold = 0.80
correction_shared_prefix = false
claude_cache_for = {}
claude_effort_for = {}
review_confidence_threshold_for = {}
adjudication_model = ""
adjudication_max_leaves = 3
adjudication_confidence_threshold = 0.80
adjudication_drawing_leaves = false
adjudication_drawing_max_leaves = 3
adjudication_reread_disagreed = false
correction_retry_median = false

[binding]
read_model = "gemini-3.8-flash"
retry_model = "gemini-3.8-flash"
```

`correction_retry_keep_higher = true` now also needs `correction_retry_median = false`
(median is on by default); a config with only the first fails at startup.

---

### 5.10 Tutoring marketplace: what a deploy needs

The feature ships as migrations `0044` to `0051` and adds no new service. What it
asks of a deploy, in the order you will meet it:

**Run the bootstrap script before the first deploy: it creates the evidence
bucket.** Tutors upload qualification documents and evidence of teaching (not identity documents) to a private bucket named
by `LEMELY_STORAGE__TUTOR_EVIDENCE_BUCKET`. `.github/workflows/deploy.yml` sets it
per environment to `<project-id>-tutor-evidence-<env>`, the same rule as the other
two buckets (override with the `GCS_TUTOR_EVIDENCE_BUCKET` environment variable).
`scripts/gcp-bootstrap.sh` creates the staging and the production bucket with
uniform bucket-level access and public access prevention, enforces both settings
again on every run (so a bucket made by hand earlier is brought into line), grants
the runtime service account `roles/storage.objectAdmin` and
`roles/storage.legacyBucketReader` on that bucket only, grants the deploy account
(`lemely-deployer`) `roles/storage.legacyBucketReader` on that bucket only (for
the deploy-time check below), and leaves the 90-day delete rule on uploads only.
Nothing runs the script for you: an operator runs it once per project, and again
after this change on a project bootstrapped before it. If creating the bucket
fails because the name is taken, another project owns it and the script stops
there. Do not deploy: create a private bucket under another name by hand in this
project (the same settings and the three grants above), set
`GCS_TUTOR_EVIDENCE_BUCKET` for that environment to its name, and expect the
script to keep stopping at that step, because it does not read the override.

**Confirm the project number before the first production deploy.** The backend
uses the evidence bucket only if this project owns it, so it needs this project's
number in `LEMELY_STORAGE__GCS_PROJECT_NUMBER`. `deploy.yml` reads the number out
of the `GCP_WORKLOAD_IDENTITY_PROVIDER` variable
(`projects/<number>/locations/global/workloadIdentityPools/...`), which the
bootstrap prints, and stops before the rollout if the variable has another shape. The script also prints the
project's number at the end: the variable must start with
`projects/<that number>/`. No new variable is needed.

The default name `lemely-tutor-evidence` is a bucket name anyone can create in
GCS's global namespace, so a deploy that used it would send tutors' documents to
that bucket's owner. The `gcs` backend therefore refuses it when it is built
(`ConfigError`), and before its first use of the evidence bucket reads the
bucket's settings and refuses it unless public access prevention is `enforced`,
uniform bucket-level access is on, and the bucket's owning project number is
`LEMELY_STORAGE__GCS_PROJECT_NUMBER`. The owner check matters because the other
two settings are the owner's to set: a stranger who registered the
per-environment name first could enforce both and grant our runtime account
access. With the number unset the bucket is refused without a read. The read
needs `storage.buckets.get`, which is why the script grants `legacyBucketReader`.
A refusal makes document uploads answer 503 ("storage unavailable") and the
admin's document links come back empty; scans and avatars are unaffected. A
failed check is not remembered, so fixing the bucket or the setting takes effect
on the next request. The `local` backend keeps the default, where it is only a
directory name, and ignores the number. The signed links use the same signing
path as avatars, which the script already enables with
`roles/iam.serviceAccountTokenCreator` on the runtime account.

**Two places show a bad evidence bucket before a tutor does.** The last step of
`deploy.yml`'s `deploy-backend` job reads the bucket as the deploy account and
fails the deploy unless it is private and owned by the number the service was
given, so a deploy whose bootstrap was not re-run is red, not green with uploads
answering 503. `lemely doctor` reports the same decision on its
`tutor_evidence_storage` line (advisory, like `storage_backend`): with `local`,
that the evidence directory is writable; with `gcs`, the placeholder name or an
unset number offline, and otherwise the backend's own privacy-and-owner check
(`--no-network` skips that read).

**Email is in mock mode until a key is set.** Without `[email] api_key`
(`RESEND_API_KEY` in the pipeline), queued tutoring emails are recorded as
`skipped` with reason `mock_provider`, startup logs a warning, and the admin
approval queue (X-04) shows "Email delivery: mock". A deploy can look healthy while
no booking email goes out. At most `[tutoring] email_daily_cap` (60) are sent a
day; a failed email is not retried; delivery is one more job on the in-process
sweeper (§5.2), so at `--min-instances=0` queued emails wait for the next
Cloud Scheduler sweep call (every minute) or the next instance. See `docs/email-delivery.md`.

**Search indexing needs a staging check after the first deploy with the worker
change (decision-log row 17; checklist not yet run).** Tutor cards are indexable by
default and the edge worker decides per card; the directory page is never indexed.
After deploying `web/worker/robots.ts` and the `run_worker_first` change in
`web/wrangler.jsonc` to staging, with one seeded tutor who is indexable and one who
opted out, run:

```bash
curl -sI https://staging.lemelyig.com/tutors                       # expect X-Robots-Tag: noindex, follow
curl -sI https://staging.lemelyig.com/tutors/<indexable-tutor-id>  # expect no X-Robots-Tag; content-type: text/html
curl -sI https://staging.lemelyig.com/tutors/<opted-out-tutor-id>  # expect X-Robots-Tag: noindex, nofollow
curl -sI https://staging.lemelyig.com/tutors/not-a-uuid            # expect X-Robots-Tag: noindex, nofollow
curl -s  https://staging.lemelyig.com/robots.txt                   # expect no Disallow line for /tutors, and "Allow: /api/public/tutors/" above "Disallow: /api/"
```

If the indexable card carries a `noindex` header, the worker lookup is failing and
the card is failing closed; check the API's `GET /api/public/tutors/<id>` first, and that `web/public/robots.txt` still allows `/api/public/tutors/` ahead of `Disallow: /api/` (a crawler that cannot fetch that lookup sees every card error). A
`web/public/_headers` rule for `/tutors` would mark every card `noindex` and is
deliberately absent. The self-hosted nginx deploy (`web/nginx.conf`) cannot look
tutors up, so it marks every `/tutors` page `noindex, nofollow`. There is no
sitemap. An opt-out reaches the edge within 60 seconds, but a search engine drops
a card only when it next visits it, which can take weeks.

**Rate limiting the public directory is an ops step, not application code.** The
application has no per-IP limit on `/api/public/*` (its limiter is process-local).
The worker caches `GET /api/public/tutors*` and `/api/public/tutoring-areas` for 60
seconds, which spares the database but does not slow a scraper. Add a Cloudflare
WAF rate-limiting rule on `/api/public/*`. Whether the Cloudflare plan in use offers
rate-limiting rules has not been checked (`docs/tutoring/SPEC.md` section h); if it
does not, the 60-second cache is the only protection. The threshold is not decided.

**Retention: there is none.** No job deletes tutoring records. The tutor access
audit log (`tutor_access_audit`), the platform-admin read log
(`tutoring_admin_access`), `parent_link_events` and `email_outbox` grow without
bound; `tutor_evidence_uploads` (the append-only log of upload attempts, no personal
data) is never pruned either; tutor profiles are closed, never deleted; blocks and reports are kept; and
an account that owns a tutor profile or is part of a booking cannot be deleted
until an offboarding procedure exists. A retention period for these tables is
undecided (ADR-T02). Evidence files stay in the bucket; a schema downgrade does
not delete storage objects.

Rollback across the release is in §5.7.

### 5.11 Runbook: a payment held for a foreign integration

Alert: log event `paymob_unexpected_integration` (`alert=True`). Check `path` first. For a
`callback` or `inquiry`, a transaction on a real order used an integration not allowed for that
payment. A callback is signed; an inquiry comes from Paymob. Checkout accepts configured card and
Apple Pay IDs, a saved-card charge accepts MOTO, and a renewal accepts configured IDs. The rejected
transaction does not settle the payment; an open payment stays open. A rejected callback does not
clear `next_reconcile_at`; a rejected scheduled inquiry clears it and stops polling.

#### Path `callback` or `inquiry`

1. Identify the payment from the alert's `payment_id` (and `txn_id` / order id if present):

   ```sql
   SELECT id, status, amount_minor, currency, paymob_order_id, paymob_txn_id,
          next_reconcile_at, created_at
   FROM payments
   WHERE id = '<payment_id>' OR paymob_order_id = <order_id>;

   SELECT dedupe_key, created_at FROM paymob_events
   WHERE dedupe_key LIKE 'rejected_integration:%' ORDER BY created_at DESC LIMIT 20;
   ```

2. Compare the integration with the Paymob account, environment and how this payment was started.
   If it is the appropriate integration for that payment and config is wrong, correct the matching
   `LEMELY_PAYMOB__CARD_INTEGRATION_ID`, `..._MOTO_INTEGRATION_ID` or
   `..._APPLE_PAY_INTEGRATION_ID` with the approved configuration and redeploy. Use the audited
   Admin Reconcile action with a reason for a guarded inquiry, then verify the payment and financial
   outcome. Stop and investigate a 409 or any unverified outcome before further action. Do not
   configure a MOTO ID as a card ID to bypass the checkout guard.

3. Otherwise escalate to the authorized finance and database operators. Identify the exact
   transaction, account and mode; compare local and Paymob records, including prior, in-flight,
   disputed and ambiguous refunds. Do not refund solely because of this alert. If funds were
   captured, a partial refund can leave money outstanding: establish that the transaction is fully
   refunded and net exposure is zero before deciding how to resolve the local payment. Separately
   confirm any noncapture. Resolve unknown outcomes and coordinate any in-flight reconcile first.
   Prefer the audited inquiry workflow where applicable; it may be unable to resolve a rejected
   foreign integration. Do not mark the payment failed by direct SQL: that bypasses the audited
   flow, and a later verified success can still settle it. Escalate unresolved local state for a
   safe, authorized resolution; do not repeat an ambiguous financial operation.

#### Path `subscription_webhook`

The renewal check also emits this event with `subscription_id`, `txn_id` and `integration_id`,
without `payment_id`. It reads Paymob's last successful charge and rejects a present integration ID
that differs from the configured MOTO ID. No renewal payment is recorded and no period is granted
by that check, even though the charge succeeded. The event can also come from the drift check; it
uses the same path label.

1. Find the local subscription and Paymob subscription ID with
   `SELECT id, status, paymob_subscription_id, current_period_end, paymob_cancelled_at FROM subscriptions WHERE id = '<subscription_id>';`
   Check the alerted transaction in the correct Paymob account and mode. Compare its integration,
   amount and state with the subscription and intended MOTO configuration. Check for an existing
   payment by `paymob_txn_id` before deciding how to resolve the charge.
2. If the configured MOTO ID is wrong, correct it using approved configuration for the intended
   account and mode and redeploy.
   The drift check can revisit eligible subscriptions once per UTC day and applies an eligible
   missed charge through the same guarded renewal rules; it can also make other drift repairs.
   Confirm the resulting payment and period. Ended rows with `paymob_cancelled_at` set are not
   drift candidates. Do not reset stamps or invoke payment reconcile for this path.
3. If the transaction belongs to another integration or cannot safely be applied, escalate to
   authorized finance and database operators under the same account, mode, prior-refund and
   financial-outcome checks in step 3 above. A local payment may not exist, so also verify the
   transaction and its refund history at Paymob. Do not refund solely because of the alert or replay
   an ambiguous financial operation. Escalate any record or entitlement correction.

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
[ ] ANTHROPIC_API_KEY set (every task tag defaults to a claude- model); a spend limit exists on the
    Anthropic workspace, and the key belongs to a dedicated workspace (Files API storage and code
    execution are not ZDR-eligible)
[ ] GEMINI_API_KEY set (mark_scheme parsing stays on a gemini- model by default)
[ ] LEMELY_STORAGE__BACKEND=gcs -- the "local" default writes to per-container
    disk, invisible across instances (§5.1)
[ ] A spend guard exists on the Gemini project (a billing budget or equivalent) --
    the web process itself enforces no USD cap (§5.4)
[ ] RESEND_API_KEY set (or accept the mock provider and no mail sent)
[ ] Tutoring: gcp-bootstrap.sh run since the evidence bucket owner check was
    added, so <project-id>-tutor-evidence-<env> exists, private, readable by the
    deploy account, before the first deploy (deploy.yml sets
    LEMELY_STORAGE__TUTOR_EVIDENCE_BUCKET to it, §5.10)
[ ] Tutoring: LEMELY_STORAGE__GCS_PROJECT_NUMBER is this project's number
    (deploy.yml: GCP_WORKLOAD_IDENTITY_PROVIDER starts with projects/<number>/,
    the number gcp-bootstrap.sh prints; §5.10)
[ ] Tutoring: the staging curl -sI checklist in §5.10 run after the first worker deploy
[ ] Tutoring: a Cloudflare WAF rate-limit rule on /api/public/* (or accept the 60 s cache only)
[ ] scripts/gcp-bootstrap.sh run once (creates the three buckets per
    environment, grants objectAdmin, grants serviceAccountTokenCreator for
    signed URLs, applies the 90-day rule to uploads, and creates the billing budget)
[ ] LEMELY_STORAGE__BUCKET + __AVATAR_BUCKET + __TUTOR_EVIDENCE_BUCKET match the
    buckets that exist (deploy.yml sets <project-id>-{uploads,avatars,tutor-evidence}-<env>
    by default)
[ ] alembic upgrade head run as an explicit step, NOT via the entrypoint
[ ] python scripts/ingest_thresholds.py run once against this database (§3.5) --
    migrations create component_thresholds/option_thresholds empty; grading
    stays refused (GradeBoundaryStore raises) until this has run
[ ] Upgrading an EXISTING database, not creating one: ingest_thresholds.py
    re-run so every verified row's max_mark is checked against the PDF (§3.5)
[ ] Backend pinned to max 1 instance
[ ] Volume mounted at /app/.lemely-cache so the $8 spend ledger survives
[ ] web/nginx.conf proxy_pass repointed if the host has no Compose DNS
[ ] TLS terminated in front of nginx
[ ] Verified: 401 no token / 200 valid token / 403 wrong role on a real route
[ ] Verified: GET /api/health reports gradeBoundariesLoaded: true
```

That last line is the cheapest end-to-end proof that the deploy is wired correctly —
it exercises DNS, the proxy, `Authorization` forwarding, JWT validation against the
right secret, and RBAC in a single pass. It is exactly what was run against the local
stack in P6.4.
