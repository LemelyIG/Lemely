# CI/CD: staging & production

The automated counterpart to [`docs/deployment.md`](deployment.md)'s manual
cloud-deploy recipe. One GitHub Actions workflow
([`.github/workflows/deploy.yml`](../.github/workflows/deploy.yml)) deploys
both environments; everything below is what it needs and how it behaves.
Read `docs/deployment.md` first if you haven't — this doc assumes its
architecture (Supabase Cloud, no CORS, single backend replica, gated
migrations) rather than re-explaining it.

```
   push to `develop`                      push to `main`
         |                                       |
         v                                       v
   ┌──────────────────────── deploy.yml ────────────────────────┐
   │ resolve-env → approve* → migrate → deploy-backend →         │
   │                                    deploy-frontend → smoke-test │
   └───────────────────────────────────────────────────────────┘
         |                                       |
         v                                       v
   staging.lemelyig.com                     lemelyig.com
   Cloud Run: lemely-backend-staging        Cloud Run: lemely-backend-production
   Supabase: Lemely-staging                 Supabase: Lemely

   * production only — pauses for one manual approval click, see below.
```

**Frontend and backend are different origins in this deploy** (Cloudflare
vs. Cloud Run), unlike the local Docker Compose stack where nginx makes them
one origin. That would normally force a CORS decision
([`docs/deployment.md` §4](deployment.md#4-when-you-actually-do-need-cors)).
It doesn't here: [`web/worker/index.ts`](../web/worker/index.ts) is a
Cloudflare Worker deployed alongside the built SPA (Workers Static Assets)
that reverse-proxies `/api/*` to Cloud Run, so the browser still only ever
talks to one origin. `lemely/web/app.py` needed no CORS middleware and still
doesn't.

## Triggers

| Trigger | Environment | Notes |
| --- | --- | --- |
| Push to `develop` | staging | Automatic, no approval |
| Push to `main` | production | Pauses for one manual approval (see below) |
| Manual run (Actions tab → "deploy" → Run workflow) | your choice | Redeploy either environment on demand — no new commit needed. Good for prototyping/iteration or re-running a flaky step. |
| Manual run with **"Also ingest CAIE grade thresholds"** ticked | your choice | Additionally runs `scripts/ingest_thresholds.py` against that environment's database (`docs/deployment.md` §3.5). Off by default and never on a push: it fetches from two small third-party hosts. Required once per environment before any grading works. |

Both environments are fully separate resources top to bottom: their own
Supabase project, their own Cloud Run service, their own Worker/domain. A
bad staging deploy cannot touch production data.

## Why a separate gate job

GitHub's environment "required reviewers" protection is enforced per *job*,
not per workflow run. If `migrate`, `deploy-backend`, and `deploy-frontend`
each declared `environment: production` directly, approving a production
deploy would mean clicking Approve three separate times. Instead, one small
`approve` job targets a dedicated `production-gate` environment (protection
rule lives there, no secrets in it); once approved, `migrate` /
`deploy-backend` / `deploy-frontend` proceed against the real `production`
environment (holding the actual secrets, no protection rule of its own) with
no further prompts. Staging's `approve` job targets an unprotected
`no-gate` environment and passes through instantly.

`production-gate` is the only environment you must remember to protect by
hand (see checklist below) — every other environment referenced in the
workflow (`staging`, `production`, `no-gate`) is created automatically,
unprotected, the first time the workflow runs.

## One-time setup

Do these once, in order. Nothing here recurs per-deploy.

### 1. GCP project + billing

Cloud Run requires a billing account linked even to stay within the Always
Free tier (2M requests, 360k GiB-seconds, 180k vCPU-seconds/month — free
only in `us-central1`/`us-east1`/`us-west1`, which is why `deploy.yml`
targets `us-central1`). Create a project and link/create a billing account
at [console.cloud.google.com](https://console.cloud.google.com). A budget
alert (Billing → Budgets & alerts) is a good idea as a tripwire, not because
this setup is expected to cost anything at low traffic.

Then run the bootstrap script once (Cloud Shell is easiest — gcloud is
already installed and authenticated there):

```bash
PROJECT_ID=<your-gcp-project-id> ./scripts/gcp-bootstrap.sh
```

It creates the Artifact Registry repo, the Workload Identity Federation pool
+ provider (locked to the `LemelyIG/Lemely` repo specifically — no other
repo can impersonate anything), and the deploy service account, then prints
three values for step 4.

**No GCP service-account key is ever created or stored anywhere.** WIF lets
GitHub Actions exchange its own OIDC token for short-lived GCP credentials
at run time — nothing long-lived to leak.

Then run the object-storage bootstrap, once per environment:

```bash
PROJECT_ID=<your-gcp-project-id> ENVIRONMENT=staging    ./scripts/gcs_bootstrap.sh
PROJECT_ID=<your-gcp-project-id> ENVIRONMENT=production ./scripts/gcs_bootstrap.sh
```

Different script, different identity: `gcp-bootstrap.sh` sets up how GitHub
Actions *deploys*; `gcs_bootstrap.sh` sets up what the deployed service
*stores*. It creates `<project-id>-uploads-<env>` and
`<project-id>-avatars-<env>` — the names `deploy.yml` computes by default, so
no new GitHub variables are needed — and grants the Cloud Run **runtime**
service account (the default compute SA, since `deploy.yml` pins none)
`roles/storage.objectAdmin` on each plus `roles/iam.serviceAccountTokenCreator`
on itself, which is what lets it sign avatar and upload URLs. Both scripts
are idempotent.

### 2. Supabase — already provisioned

Both projects exist already (created via the Supabase MCP tools available
in this session, org `LemelyIG`):

| | Production (`Lemely`) | Staging (`Lemely-staging`) |
| --- | --- | --- |
| Project ref | `ynrmqjiqcvmcakondjbp` | `respcqftujbbyvsbkibk` |
| URL | `https://ynrmqjiqcvmcakondjbp.supabase.co` | `https://respcqftujbbyvsbkibk.supabase.co` |
| Region | eu-west-1 | eu-west-1 |
| `uploads` storage bucket | created (private, 50MiB, pdf/png/jpeg) | created (private, 50MiB, pdf/png/jpeg) |

> **These Supabase buckets are no longer the ones the deployed backend
> writes to.** Object storage now defaults to Google Cloud Storage
> (`LEMELY_STORAGE__PROVIDER=gcs`), and `deploy.yml` points each environment
> at its own pair of GCS buckets. The Supabase buckets above are kept because
> the Supabase backend is still supported and switching back is one
> environment variable. Create the GCS side with
> `scripts/gcs_bootstrap.sh` — see the GCP section below and
> `docs/deployment.md` §3.2 step 5.

Both are on the free tier (2 free projects/org — this uses both slots; a
third project needs either Pro ($25/mo) or a separate organization). Free
projects pause after 7 days with no database activity — a week of nobody
touching staging will pause it; restore it from the dashboard, or just push
to `develop` again.

What's *not* provisioned (can't be, via the tools available here — these
need the dashboard): the JWT secret, the service_role key, and the database
password for each project. See the credentials table below.

### 3. Cloudflare

`lemelyig.com` is already on Cloudflare, so no nameserver/registrar changes
are needed — `wrangler deploy` (via the `custom_domain: true` routes in
[`web/wrangler.jsonc`](../web/wrangler.jsonc)) provisions the DNS + TLS for
`lemelyig.com` and `staging.lemelyig.com` itself on first deploy.

**The hostname must have no existing DNS record of its own.** A Custom
Domain is Cloudflare creating the record, and it refuses rather than
overwrite one that is already there:

```
Hostname 'lemelyig.com' already has externally managed DNS records
(A, CNAME, etc). Delete them first or try a different hostname. [code: 100117]
```

That is what happened on the first production deploy — the apex still
carried the A record of an older static deployment, and `deploy-frontend`
failed on it. The Worker script uploads fine and only the trigger fails, so
the job goes red with the Worker deployed but routed nowhere; wrangler says
as much (`Successful trigger changes were not rolled back`). Delete the
existing record in Cloudflare DNS, re-run the job, and it succeeds.

Worth stating plainly because the opposite is easy to assume: **wrangler
will not take a hostname away from whatever is already serving it.** There
is no `--force`, and being non-interactive in CI does not change it.

You need an API token: [dash.cloudflare.com/profile/api-tokens](https://dash.cloudflare.com/profile/api-tokens)
→ **Create Token** → start from the **"Edit Cloudflare Workers"** template
→ scope it to the account holding the `lemelyig.com` zone, and to that zone.

**The template alone is not enough.** It grants Account: Workers Scripts
Edit and Zone: Workers Routes Edit, which cover deploying the script — but
`custom_domain: true` also creates a DNS record, so the token additionally
needs **Zone → DNS → Edit** on `lemelyig.com`. Add it before the first
deploy; without it the script uploads and the Custom Domain step fails.

**A User API Token can only carry permissions its user actually holds.** If
the zone lives in an account you are a *member* of rather than own, check
your membership roles there first — a member with only domain/zone roles
cannot mint a Workers-capable token, and `wrangler deploy` fails its very
first call with `Authentication error [code: 10000]` against
`/accounts/<id>/workers/services/<name>`. Either have the account's super
admin grant a Workers role, or have them create an **Account API Token**,
which is owned by the account and not tied to any member's roles.

### 4. GitHub — environments, secrets, variables

Repo → **Settings → Environments**:

- Create **`production-gate`** → enable **Required reviewers** → add
  yourself (or whoever should approve prod deploys). This is the only
  environment you must create by hand; the rest auto-create on first run.
- Create **`staging`** and **`production`** (or let the first workflow run
  auto-create them) and add the secrets listed below to each — **the same
  secret *names* in both, different *values***, which is the whole point of
  GitHub Environments: `deploy.yml` doesn't hardcode which environment's
  value it gets, the environment it's running against decides.

Repo → **Settings → Secrets and variables → Actions**:

- **Variables** tab (repo-level, shared by both environments — nothing
  below is sensitive):
  `GCP_PROJECT_ID`, `GCP_WORKLOAD_IDENTITY_PROVIDER`, `GCP_SERVICE_ACCOUNT`
  (all three printed by `gcp-bootstrap.sh`), `CLOUDFLARE_ACCOUNT_ID`.
- **Secrets** tab (repo-level): `CLOUDFLARE_API_TOKEN`.

## Credentials checklist

Everything the pipeline needs, where to get it, and where it goes. Add
these directly in GitHub — nothing here needs to be typed anywhere else.

| Name | Scope | Where to get it |
| --- | --- | --- |
| `GCP_PROJECT_ID` | Repo variable | Output of `scripts/gcp-bootstrap.sh` |
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | Repo variable | Output of `scripts/gcp-bootstrap.sh` |
| `GCP_SERVICE_ACCOUNT` | Repo variable | Output of `scripts/gcp-bootstrap.sh` |
| `CLOUDFLARE_ACCOUNT_ID` | Repo variable | [dash.cloudflare.com](https://dash.cloudflare.com) → any domain's overview page → right sidebar "Account ID" |
| `CLOUDFLARE_API_TOKEN` | Repo secret | [dash.cloudflare.com/profile/api-tokens](https://dash.cloudflare.com/profile/api-tokens) → Create Token → "Edit Cloudflare Workers" template |
| `SUPABASE_URL` | Env secret (staging + production) | Already known — see table above (`https://<ref>.supabase.co`) |
| `SUPABASE_ANON_KEY` | Env secret (staging + production) | Already known — see below. **Not as harmless as "anon keys are public-facing" suggests — read the note under the values before relying on that.** |
| `SUPABASE_JWT_SECRET` | Env secret (staging + production) | Dashboard → project → Settings → API → **JWT Secret** (click reveal). **The one thing that will silently break auth if left wrong** — `docs/deployment.md` §2 explains why. |
| `SUPABASE_SERVICE_ROLE_KEY` | Env secret (staging + production) | Dashboard → project → Settings → API → **service_role** key (click reveal) |
| `SUPABASE_DB_URL` | Env secret (staging + production) | Dashboard → project → Settings → Database → Connection string → **Session pooler** tab (not "Direct connection" — GitHub Actions runners are IPv4-only and the direct connection is IPv6-only). Paste it exactly as shown, including your DB password; `deploy.yml` rewrites the `postgresql://` prefix itself. If you don't have the DB password (these two projects were created via API, so it was never shown to anyone), reset it from the same Database settings page. |
| `GEMINI_API_KEY` | Env secret (staging + production) | Reuse the key from your local `.env`, or mint a new one at [aistudio.google.com/apikey](https://aistudio.google.com/apikey). Fine to reuse the same key for both environments. |
| `RESEND_API_KEY` | Env secret (staging + production) — **optional** | [resend.com](https://resend.com) → API Keys → Create, with *Sending access* only. Leave it unset and the deploy still succeeds: an absent secret renders as the empty string, which the backend reads as *not configured* and falls back to the offline mock provider, so nothing sends. Setting it is the entire switch-on. **Reusing one key across both environments shares one 100/day free-tier allowance** — a staging smoke test spends production's quota, so mint a second Resend account for staging or leave staging unset. See `docs/email-delivery.md`. |

Dashboard links for the two Supabase projects, since you'll need both pages
open: [staging settings](https://supabase.com/dashboard/project/respcqftujbbyvsbkibk/settings/api) ·
[production settings](https://supabase.com/dashboard/project/ynrmqjiqcvmcakondjbp/settings/api)
(Database → Connection string is the tab next to API on the same project's
Settings page).

Already-known `SUPABASE_URL` / `SUPABASE_ANON_KEY` values, to save you a
lookup:

```
# staging
SUPABASE_URL=https://respcqftujbbyvsbkibk.supabase.co
SUPABASE_ANON_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InJlc3BjcWZ0dWpiYnl2c2JraWJrIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODcwNjkwNzAsImV4cCI6MjEwMjY0NTA3MH0._2p6zahQF03VcfF7brWPVH4WWFK_x8l4K2kHzlDGSPM

# production
SUPABASE_URL=https://ynrmqjiqcvmcakondjbp.supabase.co
SUPABASE_ANON_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inlucm1xamlxY3ZtY2Frb25kamJwIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODcwNTMxODAsImV4cCI6MjEwMjYyOTE4MH0.rOYMoHqZ5lB3Wvqq3FtA4AOpCxxm3dMwckcZdsM5pLE
```

> ### An anon key is only public-safe when RLS is on
>
> The usual advice — anon keys are meant to be shipped to browsers — assumes
> Row Level Security is enabled and policied. **This schema has neither.**
> Alembic creates plain tables; nothing turns RLS on, and there are no
> policies. Supabase's stock default privileges then grant `anon` and
> `authenticated` full `SELECT, INSERT, UPDATE, DELETE, TRUNCATE` on every
> table it creates.
>
> With RLS off and those grants in place, the anon key is not a public
> identifier — it is an unauthenticated read/write credential for the entire
> database, reachable over PostgREST by anyone who can read this file. Both
> keys above are committed to a public repository.
>
> **What closes it**, and what has been applied to both projects:
>
> ```sql
> REVOKE ALL ON ALL TABLES IN SCHEMA public FROM anon, authenticated;
> ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM anon, authenticated;
> ```
>
> The second statement is the load-bearing half: without it the next
> migration that adds a table hands `anon` full access to it again. Alembic
> connects as `postgres`, and that is the role the default-privilege revoke
> is recorded against, so new tables it creates are covered. Verify with:
>
> ```sql
> SELECT pg_get_userbyid(defaclrole), defaclacl FROM pg_default_acl d
> JOIN pg_namespace n ON n.oid = d.defaclnamespace
> WHERE n.nspname = 'public' AND d.defaclobjtype = 'r';
> ```
>
> The `postgres` row must not list `anon` or `authenticated`. (A
> `supabase_admin` row still grants them — that is Supabase's own default for
> tables *it* creates, and application migrations do not run as that role.)
>
> This is safe for this application because nothing in it talks to
> PostgREST: the backend reaches Postgres through SQLAlchemy, and uses
> Supabase only for GoTrue auth and Storage. Revoking these grants breaks
> nothing here. **It would break a project that uses `supabase-js` against
> the database** — enable RLS with policies instead, in that case.
>
> Rotating both keys in the Supabase dashboard remains worthwhile regardless:
> removing them from this file does not remove them from git history.

## First deploy

Once section 4's environments/secrets/variables are in place:

```bash
git push origin develop   # or: Actions tab → deploy → Run workflow → staging
```

Watch it in the **Actions** tab. `smoke-test` (the last job) hitting
`https://staging.lemelyig.com/api/health` through the real domain is the
signal the whole chain is wired correctly — DNS, the Worker's proxy, and
the backend behind it, not just each piece in isolation
(`docs/deployment.md`'s own "verified, not inferred" standard). Once
staging looks right, merge `develop` → `main` to exercise the production
path (approval click included).

Both environments have since been deployed this way. Three things the first
runs turned up, none of which are obvious from the config:

- **`--execution-environment=gen2` is load-bearing, not a preference.** On
  gen1 the container died 55s into startup with `Uncaught signal: 7`
  (SIGBUS, from gVisor's sentry) before uvicorn ever bound. On gen2 the same
  image reports healthy in under 7s. `deploy.yml` carries the full reasoning
  — including that memory was *not* the cause, despite an early commit
  saying so.
- **The Custom Domain step fails on a hostname that already has a DNS
  record** — see §3. Clear the record first.
- **A `docker push` can return a bare 502 from Artifact Registry** and fail
  the job mid-upload with no revision created. That one is genuinely
  transient; re-running the failed jobs is the fix, and the `Why the rollout
  failed` step in `deploy-backend` will say `latest revision: <none
  created>`, which is how you tell it apart from a container that started
  and then died.

## Known gaps this setup doesn't close

Carried over from `docs/deployment.md` §5, still true here — not
regressions this pipeline introduced, just not solved by it:

- **The Cloud Run backend is reachable directly**, not only through the
  Worker (`--allow-unauthenticated` is what lets the Worker's plain
  `fetch()` reach it at all). The backend's own per-route auth
  (401/403 — see `docs/deployment.md` §5.5) still applies either way, so
  this isn't an authorization bypass, just a loss of Cloudflare's edge
  protections (rate limiting, WAF) for anyone who finds the `*.run.app`
  URL. Tightening this means either Cloud Run domain mapping + a load
  balancer (not free-tier) or a shared-secret header the Worker adds and
  a small FastAPI middleware checks — worth doing before this is handling
  real user traffic, deliberately left out here to avoid an app-code change
  beyond what a CI/CD setup needs.
- **The $8 Gemini spend ledger resets on every Cloud Run cold start**
  (`docs/deployment.md` §5.4) — it lives at `/app/.lemely-cache` on the
  container's ephemeral filesystem, and `min-instances=0` means that
  filesystem is thrown away constantly. A Cloud Run
  [Cloud Storage volume mount](https://cloud.google.com/run/docs/configuring/services/cloud-storage-volume-mounts)
  at that path (a small GCS bucket is free-tier eligible) would fix it;
  not wired up here.
- Everything else in `docs/deployment.md` §5 (single-replica constraint, no
  scheduler, `/api/teacher/overview`'s N+1) is unchanged by this pipeline —
  it deploys the app as-is, it doesn't fix it.
- **The `migrate` job runs `alembic upgrade head` only — it does not run
  `scripts/ingest_thresholds.py`** (`docs/deployment.md` §3.5). Migrations
  create `component_thresholds`/`option_thresholds` empty; grading stays
  refused (`GradeBoundaryStore` raises `EmptyGradeBoundaryStoreError` rather
  than invent boundaries) until someone runs the ingest script by hand
  against the target database, same as any other manual one-time step this
  pipeline doesn't yet automate. `GET /api/health`'s `gradeBoundariesLoaded`
  field is the way to confirm it before declaring a fresh environment ready.
  Deliberately not wired into `deploy.yml` here — adding an ingest step to
  the pipeline is a deploy-pipeline decision, not a doc change.
