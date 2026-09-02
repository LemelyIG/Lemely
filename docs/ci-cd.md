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

### 2. Supabase — already provisioned

Both projects exist already (created via the Supabase MCP tools available
in this session, org `LemelyIG`):

| | Production (`Lemely`) | Staging (`Lemely-staging`) |
| --- | --- | --- |
| Project ref | `ynrmqjiqcvmcakondjbp` | `respcqftujbbyvsbkibk` |
| URL | `https://ynrmqjiqcvmcakondjbp.supabase.co` | `https://respcqftujbbyvsbkibk.supabase.co` |
| Region | eu-west-1 | eu-west-1 |
| `uploads` storage bucket | created (private, 50MiB, pdf/png/jpeg) | created (private, 50MiB, pdf/png/jpeg) |

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

You need an API token: [dash.cloudflare.com/profile/api-tokens](https://dash.cloudflare.com/profile/api-tokens)
→ **Create Token** → the **"Edit Cloudflare Workers"** template → scope it
to your account and the `lemelyig.com` zone. That template's permissions
(Account: Workers Scripts Edit, Zone: Workers Routes Edit) are exactly what
`wrangler deploy` needs, nothing more.

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
| `SUPABASE_ANON_KEY` | Env secret (staging + production) | Already known — see below (safe to paste; anon keys are meant to be public-facing) |
| `SUPABASE_JWT_SECRET` | Env secret (staging + production) | Dashboard → project → Settings → API → **JWT Secret** (click reveal). **The one thing that will silently break auth if left wrong** — `docs/deployment.md` §2 explains why. |
| `SUPABASE_SERVICE_ROLE_KEY` | Env secret (staging + production) | Dashboard → project → Settings → API → **service_role** key (click reveal) |
| `SUPABASE_DB_URL` | Env secret (staging + production) | Dashboard → project → Settings → Database → Connection string → **Session pooler** tab (not "Direct connection" — GitHub Actions runners are IPv4-only and the direct connection is IPv6-only). Paste it exactly as shown, including your DB password; `deploy.yml` rewrites the `postgresql://` prefix itself. If you don't have the DB password (these two projects were created via API, so it was never shown to anyone), reset it from the same Database settings page. |
| `GEMINI_API_KEY` | Env secret (staging + production) | Reuse the key from your local `.env`, or mint a new one at [aistudio.google.com/apikey](https://aistudio.google.com/apikey). Fine to reuse the same key for both environments. |

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
