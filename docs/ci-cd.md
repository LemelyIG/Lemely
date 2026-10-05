# CI/CD: staging & production

The automated counterpart to [`docs/deployment.md`](deployment.md)'s manual
cloud-deploy recipe. One GitHub Actions workflow
([`.github/workflows/deploy.yml`](../.github/workflows/deploy.yml)) deploys
both environments; everything below is what it needs and how it behaves.
Read `docs/deployment.md` first if you haven't — this doc assumes its
architecture (Supabase Cloud, no CORS, GCS-backed uploads, gated migrations)
rather than re-explaining it.

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
at [console.cloud.google.com](https://console.cloud.google.com).

Then run the bootstrap script once (Cloud Shell is easiest — gcloud is
already installed and authenticated there):

```bash
PROJECT_ID=<your-gcp-project-id> \
BILLING_ACCOUNT_ID=<your-billing-account-id> \
BUDGET_USD=<a-plain-number-of-dollars> \
./scripts/gcp-bootstrap.sh
```

`BILLING_ACCOUNT_ID` and `BUDGET_USD` are optional, but matter more than a
Cloud Run cost tripwire now: the web process enforces no Gemini spend cap of
its own (`docs/deployment.md` §5.1/§5.4; spec DS3), so the billing budget
this creates — alerts at 50/90/100%, named `lemely-<project-id>` — is the
*only* guard left on that spend. Leave either unset and the script skips the
budget and prints exactly what it skipped.

For each of `staging` and `production` the script also creates, idempotently:

- The upload bucket (`<project-id>-uploads-<env>`, `us-central1`, uniform
  bucket-level access, public-access prevention enforced, a 90-day object
  lifecycle from `scripts/gcs-lifecycle.json`).
- The runtime service account Cloud Run deploys the revision as
  (`lemely-backend-<env>@<project-id>.iam.gserviceaccount.com`), holding
  `roles/storage.objectAdmin` on that bucket only — never a project-level
  storage role.

Plus, once per project: the Artifact Registry repo, the Workload Identity
Federation pool + provider (locked to the `LemelyIG/Lemely` repo specifically
— no other repo can impersonate anything), and the deploy service account.

**No new GitHub secret or variable is needed for the buckets or the runtime
identities** — `deploy.yml` derives both names itself from `GCP_PROJECT_ID`
(step 4, below) and the environment it is deploying to, inputs it already
has. The script's final output prints the three values step 4 actually asks
you to set, plus the derived bucket/service-account names and the billing
budget's outcome, for the record.

**No GCP service-account key is ever created or stored anywhere.** WIF lets
GitHub Actions exchange its own OIDC token for short-lived GCP credentials
at run time — nothing long-lived to leak.

That one script covers both environments in a single run — there is no
separate object-storage bootstrap. It sets up how GitHub Actions *deploys*
(WIF, deployer roles, Artifact Registry) **and** what the deployed service
*stores*: it creates `<project-id>-uploads-<env>` and
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
| `uploads` storage bucket | created, now **unused** | created, now **unused** |

**The `uploads` Supabase Storage bucket in each project is unused.** Every upload this
app keeps now goes to the GCS bucket step 1 provisions instead — the Supabase Storage
client was removed from the codebase, not just deprecated (spec DS7). Supabase Cloud
still does real work here (Postgres, GoTrue auth); only the Storage bucket in each
project is dead weight. Deleting it (Dashboard → Storage → the `uploads` bucket) is
optional and safe — nothing reads or writes it — and left undone here since removing
it buys nothing at the free tier's storage allowance.

> **These Supabase buckets are no longer the ones the deployed backend
> writes to.** Object storage now defaults to Google Cloud Storage
> (`LEMELY_STORAGE__BACKEND=gcs`), and `deploy.yml` points each environment
> at its own pair of GCS buckets. The Supabase buckets above are kept because
> there is no Supabase Storage backend any more — DS7 deleted it, and the
> only backends are `gcs` and `local`. Create the buckets with
> `scripts/gcp-bootstrap.sh` — see the GCP section below and
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

#### `www` subdomains redirect to their root domain

A Custom Domain requires an exact hostname match, so the Worker attached to
the apex (`lemelyig.com`) never receives `www.lemelyig.com` traffic, and
likewise `staging.lemelyig.com` never receives `www.staging.lemelyig.com`
traffic — there is no DNS record for either `www` host by default, so
visitors who type one get an unreachable/`NXDOMAIN` error. This is exactly
the case Cloudflare's own docs call out ([Custom Domains → Redirect between
www and root
domain](https://developers.cloudflare.com/workers/configuration/routing/custom-domains/#redirect-between-www-and-root-domain)):
it's zone-level DNS + rules configuration, not something `wrangler deploy` or
a `custom_domain: true` route can fix, and not config this repo carries.

**Done** for both `www.lemelyig.com` and `www.staging.lemelyig.com`, via the
Cloudflare API against the `lemelyig.com` zone:

1. A proxied `A` record per `www` host, content `192.0.2.0` (the [reserved
   placeholder for an originless
   setup](https://developers.cloudflare.com/dns/manage-dns-records/how-to/create-dns-records/#originless-setups)
   — traffic never actually reaches it). Proxied is required — an unproxied
   (DNS-only) record can't be matched by a redirect rule.
2. One zone-level Redirect Rule per host in a single ruleset (`http_request_dynamic_redirect`
   phase, name "Redirect rules ruleset"): `www.lemelyig.com` → `https://lemelyig.com`
   and `www.staging.lemelyig.com` → `https://staging.lemelyig.com`, both 301,
   preserving path and query string.

If either ever needs recreating (e.g. the zone gets rebuilt), redo both
steps for the affected host — the dashboard equivalents are **DNS → Records
→ Add record** and **Rules → Redirect Rules → Create rule** (or start from
the built-in ["Redirect from www to
root"](https://developers.cloudflare.com/rules/url-forwarding/examples/redirect-www-to-root/)
template).

Verify with `curl -I https://www.lemelyig.com` and `curl -I
https://www.staging.lemelyig.com` — expect `301` with `Location:` pointing at
the corresponding root domain.

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

## Configuring the deployed service

The API reads its settings in this order: environment variables, then
`.env`, then `lemely.toml`, then built-in defaults
(`lemely/runtime/config.py`). The Docker image ships no `lemely.toml` and no
`.env`, so on Cloud Run a setting is either an environment variable or its
default.

**Naming.** Any setting maps to an environment variable: prefix `LEMELY_`,
section and key joined by `__`, in capitals. `[grading] equivalence_gate`
becomes `LEMELY_GRADING__EQUIVALENCE_GATE`; `[storage] bucket` becomes
`LEMELY_STORAGE__BUCKET`.

**Where the value comes from.** `deploy.yml` sets the service's environment
in the Cloud Run step's `env_vars` block. Each line takes its value from
GitHub:

- `${{ vars.NAME }}` for anything that is not a secret, such as feature
  flags, bucket names and URLs.
- `${{ secrets.NAME }}` for credentials.

Both are defined per environment under **Settings → Environments →
`staging` / `production`**. The deploy job runs inside the environment it
targets, so the same line picks up staging's value on a staging deploy and
production's value on a production deploy.

**Adding a new setting takes two steps.** Setting a GitHub variable alone
does nothing:

1. Add a line to `env_vars` in `deploy.yml`, with a default:
   `LEMELY_SECTION__KEY=${{ vars.SECTION_KEY || 'default' }}`.
2. Set `SECTION_KEY` in each environment where it should differ from the
   default, then redeploy that environment.

### Memory budget

The backend runs at `--memory=2Gi`. Scan work (#260, #271) runs in two
child processes, each under a hard memory limit, so the instance has to hold
both children at their limits at the same time as the web process, the
equivalence parse worker and the scan pages the web process holds while it
marks. At worst the sum does not fit in 2 GiB. The owner **accepted** that
worst case on 2026-10-05, at the corrected figure below (2993.0 MiB, a margin
of -945.0): keep 2 GiB, and cap marking runs at one at a time.
The measurements and the rule that sets the limits are in the docstring of
`lemely/runtime/sandbox.py`.

The worker returns a scan's pages to the web process, and the web process
holds all of them until the Gemini calls that read them are done
(`answer_extraction`), not just while the worker renders. Before the first
call it runs `scan_hygiene` on each page, one at a time, in the web process,
and that costs far more than the page itself: a float64 copy plus the
Laplacian arrays. This is a marking run.

**Runs are capped at one per process** (`lemely/io/run_cap.py`). Teacher
grading jobs, student corrections and every other caller of the extractor
share the one slot. A second run waits until the first has released its
pages, and never fails for waiting. While it waits, a student's progress
stream gets an `extraction_queued` frame that says so, and an
`extraction_dequeued` frame when its run has the slot. The container runs
one web process, so the cap is per instance.

A waiting run is heard from at least once a minute: it publishes
`extraction_queued` again every 60 s (`QUEUED_HEARTBEAT_SECONDS`). A teacher's
row is written on each one, so its `updated_at` stays inside the 900 s
stale window and a queued paper is not shown as a lost run, nor claimable by a
duplicate regrade. A student's stream gets a frame inside Cloud Run's 300 s
request timeout; a student who waits longer than that in total is still cut by
it (`--timeout=300`), and the cap has no answer for that, only the heartbeat
for the frames.

**Mark-scheme parse.** A user's mark-scheme PDF is parsed with pdfplumber, which inflates every content stream it reads with no bound of its own: the reviewer's 204 KB PDF took the parse to 475 MiB, and the same shape at 1 GiB needs 2.1 GiB. Both places that parse a user's scheme run it in the extraction worker (`lemely.io.scheme_parse`): `POST /api/schemes`, off the event loop, and a scheme attached alongside a scan, in the grading thread. The parse itself is cut at `scheme_parse_timeout_seconds`, 20 s, on both. That adds no child and no budget term. Real schemes peak at 47–71 MiB, and a synthetic 102-page scheme at 149 MiB, and parse in under 2 s, well inside 640 MiB. The memory limit does not bound CPU time, though: a 29 KB PDF of ruling-line grids takes 21 s, growing linearly with its pages, so the parse is cut at 20 s and not held for the extraction timeout (180 s). A scheme parse shares the worker's lock with scan extraction, which a marking run's render can hold for up to the extraction timeout. `POST /api/schemes` that arrives during an extraction longer than 20 s answers 503, as the scan upload check does, and the client retries. On the grading path a busy worker is not a failure of the scheme: the parse is asked again, 20 s at a time, for up to the extraction timeout (180 s) from the first attempt, and only a worker still busy then fails the paper (same fixed text; `scheme_parse_failed` logs `reason=busy`). Any other failure (timeout, memory, crash, error) is not retried. A failed parse is a 422 with the fixed text "Could not read this mark scheme"; the cause goes only to the `scheme_parse_failed` log line.

One run costs the web process the worst of three cases. The pages held
scale with the scan's total pixels (cap 160 Mpx), and the `scan_hygiene`
transient scales with its largest page (cap 16 Mpx), so the worst scan maxes
both at once: ten 16 Mpx pages.

| Case | Pages held | `scan_hygiene`, one page | Run |
|---|---|---|---|
| The adversarial 40-page PDF (4.1 Mpx pages) | 477.3 MiB | 129.2 MiB | 606.5 MiB |
| One 16 Mpx image page | 45.8 MiB (incompressible PNG) | 504.7 MiB | 550.5 MiB |
| **Ten 16 Mpx pages (160 Mpx, the worst)** | **458.0 MiB** (10 x 45.8, incompressible) | **501.0 MiB** | **959.0 MiB** |

The third row was measured on 2026-10-05, in the final review (R4, I1): ten
4000 x 4000 noise pages (200 DPI of a 20 in square), held as PNG, assumed as
incompressible as the 40-page case, and `scan_hygiene` on one of them as
`VmHWM` growth over the resident size. The budget first accepted counted the
run at 606.5 MiB (total 2640.5, margin -592.5), which was the 40-page row, not
the worst.

The budget, with every term at its worst at the same time:

| Part | Kind | Size |
|---|---|---|
| Extraction worker, `RLIMIT_DATA` (`RLIMIT_AS` 768 MiB) | limit | 640 MiB |
| Interactive worker, `RLIMIT_DATA` (`RLIMIT_AS` 768 MiB) | limit | 640 MiB |
| Web process, idle after start-up | measured peak | 226.4 MiB (237.4 MB) |
| One marking run in the web process (the worst case above) | measured peak | 959.0 MiB |
| Equivalence parse worker, at its `RLIMIT_AS` | limit | 512 MiB |
| `multiprocessing` resource tracker | measured peak | 15.6 MiB (16.4 MB) |
| **Total** | | **2993.0 MiB of 2048** |

The margin is **-945.0 MiB**: the instance can run out of memory. The
owner accepted this on 2026-10-05, at this corrected figure, keeping 2 GiB and
the cap of one run, because it needs every term at its worst at once: both
workers at their limits, the parse worker at its limit, and the run holding
ten 16 Mpx pages and running `scan_hygiene` on one. With the cap, a second run
adds nothing; without it, each run in flight would add 959.0 MiB.

The interactive worker went from 576 / 704 MiB to 640 / 768 MiB on
2026-10-05, by the 1.5x-growth rule: a crop of a whole page of a 160 Mpx
1-bit image peaks at 429 MiB `VmData` (431.5 MiB when it is transparent).

The table leaves out one transient, because it was not measured: the
re-reads decode whole pages in the web process, up to
`gemini.reread_concurrency` (4) at once. The budget the owner first accepted
(2003.9 MiB, a 44.1 MiB margin) counted the parse worker idle (68.6 MiB),
left out `scan_hygiene` and assumed one set of held pages with nothing
capping it.

The figures in the table were measured on 2026-10-04 and 2026-10-05:

- The web process, the held pages and the parse worker's idle size were
  measured in Task 11.
- `scan_hygiene` was measured on synthetic pages, as `VmHWM` growth over the
  starting RSS.

The OOM priority does not protect the web server from all of this. Every
worker child sets `oom_score_adj=1000`, so when the instance runs out, the
kernel kills a worker child first. When the pressure is in the web process,
though, killing an idle worker child frees only its resident size, about 70
to 80 MiB. The kernel's next choice is then the web process itself, and with
it every request and SSE stream in flight.

The extraction worker serves extraction and the upload check, and the
interactive worker serves preview and crop. Each handles one call at a time,
and a call's timeout includes the wait for the worker. That has three
consequences:

- **An upload check or a scheme parse can fail behind an extraction.** An
  upload arriving during an extraction waits up to its 20 s timeout and then
  gets 503 "Scan rendering is temporarily unavailable" (a scheme upload, 503
  "Reading mark schemes is temporarily unavailable"), though the file is
  fine. The slowest extraction measured takes 33 s.
- **An extraction can wait behind an upload check or a scheme parse.** With
  runs capped at one, an extraction no longer queues behind another
  extraction on the same instance. It can still wait behind an upload check
  or a scheme parse, at most 20 s each. If it outlives its 180 s, it fails
  with "Could not render this scan", and the paper is marked as failed rather
  than retried.
- **Thumbnails can come back busy.** One interactive worker serialises every
  preview and crop, so a page that asks for many thumbnails at once can get
  503 "busy" under load.

The service sets no `--concurrency` flag.

The limits and timeouts are settings, so each can be changed with an
environment variable (and a line in `env_vars`, as described above). The
defaults are the measured values. A timeout bounds one call, including any
wait for a busy worker; the extraction timeout is 180 s because the slowest
extraction measured takes 33 s. Starting a worker's child is not counted in
a call's timeout; it has its own bound.

| Environment variable | Default |
|---|---|
| `LEMELY_SANDBOX__EXTRACTION_DATA_LIMIT_BYTES` | 671088640 (640 MiB) |
| `LEMELY_SANDBOX__EXTRACTION_ADDRESS_LIMIT_BYTES` | 805306368 (768 MiB) |
| `LEMELY_SANDBOX__INTERACTIVE_DATA_LIMIT_BYTES` | 671088640 (640 MiB) |
| `LEMELY_SANDBOX__INTERACTIVE_ADDRESS_LIMIT_BYTES` | 805306368 (768 MiB) |
| `LEMELY_SANDBOX__START_TIMEOUT_SECONDS` | 30 |
| `LEMELY_SANDBOX__EXTRACTION_TIMEOUT_SECONDS` | 180 |
| `LEMELY_SANDBOX__UPLOAD_CHECK_TIMEOUT_SECONDS` | 20 |
| `LEMELY_SANDBOX__SCHEME_PARSE_TIMEOUT_SECONDS` | 20 |
| `LEMELY_SANDBOX__PREVIEW_TIMEOUT_SECONDS` | 15 |
| `LEMELY_SANDBOX__CROP_TIMEOUT_SECONDS` | 10 |

Raising a data limit raises the total above. `tests/test_sandbox.py` pins
the defaults to the measured growth rule, and pins the accepted total
(2993.0 MiB, one run): a raised limit or a second concurrent run fails it,
and should come with a new decision.

The sandbox settings are read by `sandbox_settings()`, which does not go
through the app's `get_settings` dependency, so a test that overrides
`dependency_overrides[get_settings]` does not change them; patch
`sandbox.sandbox_settings` instead (`tests/sandbox_fixtures.py`).

### The marking flags

Three settings change how answers are marked:

| Setting | GitHub variable | Default | Effect |
|---|---|---|---|
| `LEMELY_GRADING__EQUIVALENCE_GATE` | `GRADING_EQUIVALENCE_GATE` | `false` | Marks non-MCQ answers on the verdicts path with the SymPy award gate. |
| `LEMELY_GRADING__ECF_SUBSTITUTION` | `GRADING_ECF_SUBSTITUTION` | `false` | Applies error-carried-forward by substitution. Has no effect unless `GRADING_EQUIVALENCE_GATE` is also `true`. |
| `LEMELY_GRADING__REREAD_SUBSTITUTION` | `GRADING_REREAD_SUBSTITUTION` | `false` | Marks an answer on its second, cropped read when that read disagrees with the first read and is not blank. The teacher-review flag fires on the disagreement either way. |

All three apply to every marking path: paper uploads, the teacher grading job,
quiz marking and the CLI. Turning one on changes marks for real students, so
measure it first with an accuracy sweep. The harness reads the same
settings, and a flag-on sweep gets a different `params_fingerprint` from a
flag-off one, so the two can be compared.

To try a flag on staging only:

1. **Settings → Environments → `staging` → Environment variables → Add**:
   `GRADING_EQUIVALENCE_GATE` = `true`.
2. Re-run the deploy workflow for staging (`workflow_dispatch` with
   `environment: staging`, or push to `develop` — see "Triggers" above).
3. Confirm the new revision's mode in Cloud Run logs. Every revision logs one
   `marking_flags` line at startup with both values. Find it with the query
   `jsonPayload.event="marking_flags"`. If ECF is on without the gate, that
   entry's payload has `level: "warning"` and `ecf_inert: true` — our JSON
   logs carry a `level` field, not the `severity` field Cloud Logging reads
   for its own severity column, so the entry does not show at WARNING
   severity; look at the payload fields instead of filtering by severity.

Production is unaffected until its own `production` environment variable is
set and production is redeployed.

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

**No new secret or variable for GCS.** The upload bucket and the runtime service
account `deploy.yml` deploys as are both just names `deploy.yml` derives itself from
`GCP_PROJECT_ID` (already in the table above) and the environment it is running
against: `<GCP_PROJECT_ID>-uploads-<env>` and
`lemely-backend-<env>@<GCP_PROJECT_ID>.iam.gserviceaccount.com`. `scripts/gcp-bootstrap.sh`
provisions the real resources those two names point at (§1); nothing else to add here.

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
- **A budget alert is not a cap.** The web process enforces no Gemini spend
  ceiling of its own (`docs/deployment.md` §5.1/§5.4; spec DS3) — the Google
  Cloud billing budget §1 above provisions is the only guard on that spend,
  and it fires an alert at 50/90/100%, not a stop. Spend can pass it before
  anyone acts. The CLI and Gradio are unaffected and still enforce their own
  `$8.00` on-disk ledger.
- **Queued is per instance.** The teacher grading pool is one worker per
  Cloud Run instance (`docs/deployment.md` §5.1). With `--max-instances=3` a
  paper can queue on one instance while another sits idle. Every instance
  answers a paper's status from the same Postgres row, so this is a
  scheduling gap, not a correctness one — and it has not been observed
  either way, because this branch has not been deployed.
- Everything else in `docs/deployment.md` §5 (no scheduler,
  `/api/teacher/overview`'s N+1) is unchanged by this pipeline — it deploys
  the app as-is, it doesn't fix it.
