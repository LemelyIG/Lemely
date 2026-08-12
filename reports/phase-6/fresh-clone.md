# Fresh-clone acceptance run (P6.10)

MISSION.md §4, Phase 6's last acceptance line:

> fresh-clone test — `git clone` → documented commands → working product with
> seeded demo accounts for all 5 roles.

**Result: PASS.** `make up` from a clone brought the product up and all five demo
roles authenticate through it. The run also found four defects that all thirteen
quality gates — green, 0 skipped, on this same tree — could not see; they are
fixed in `310fade` and reasoned about in `BUILD/DECISIONS.md` D6.8.

| | |
| --- | --- |
| Date | 2026-08-12 |
| Clone source | this repository, branch `feature/phase-6-hardening` at `be49d34` |
| Clone target | `/tmp/lemely-fresh-1` (outside the working tree, so nothing local leaks in) |
| Fixes that came out of it | `310fade` |

Everything below was executed from the clone and checked against the running
containers. Nothing here is inferred from source.

## 1. What a fresh clone actually contains

`lemely.toml`, `.env`, `outputs/`, `.venv/` and `web/node_modules/` are absent —
gitignored, as intended. `lemely.toml.example`, `docker-compose.yml`,
`Dockerfile`, `web/Dockerfile`, `scripts/up.sh`, `docs/deployment.md` and
`supabase/config.toml` are all present, so the documented paths have something to
run.

`Sources/` **is** present: four solved scripts and four mark schemes (10 files,
19 MB) committed before `Sources/` was gitignored. The two mark schemes fetched
for the B1 accuracy work are correctly *not* in the clone.

## 2. The packaged product — `make up`

```
make up   →   EXIT=0
            Container lemely-fresh-1-backend-1  Healthy
            Container lemely-fresh-1-web-1      Started
            Lemely is up: http://localhost:8080
```

| Check | Result |
| --- | --- |
| `GET http://localhost:8080/` | `200`, `text/html` — nginx serving the built SPA |
| `GET http://localhost:8080/api/health` | `{"status":"ok","apiKeyConfigured":true}` — the proxy forwards to the backend |

That `apiKeyConfigured: true` is **finding 3** below: there was no Gemini key
anywhere on that stack.

## 3. All five roles, through the proxy

Verified through nginx on `:8080`, **not** against the backend on `:8000` — that
is the difference between testing the app and testing the deployment. One pass
exercises the proxy, `Authorization` forwarding, JWT validation and RBAC. P6.4
had only ever checked this chain with *backend-minted* tokens; a real GoTrue
password login through the packaged product had never been run before this.

Each role: log in, then read `/api/me/profile` back with the returned token.

| Role | Credential | `/api/me/profile` |
| --- | --- | --- |
| student | `student@demo.lemely.local` | `{"displayName":"Demo Student","email":"student@demo.lemely.local","role":"student"}` |
| teacher | `teacher@demo.lemely.local` | `{"displayName":"Demo Teacher",…,"role":"teacher"}` |
| school_admin | `school-admin@demo.lemely.local` | `{"displayName":"Demo School Admin",…,"role":"school_admin"}` |
| platform_admin | `platform-admin@demo.lemely.local` | `{"displayName":"Demo Platform Admin",…,"role":"platform_admin"}` |
| parent | phone `+10000000000` | `{"displayName":null,"email":"phone+10000000000@parents.lemely.local","role":"parent"}` |

The four password roles use `Demo-Lemely-1!`. The parent goes through
`POST /api/auth/otp/request` → `POST /api/auth/otp/verify`; the mock SMS provider
does not deliver out of band, so `request_otp` returns the code as `devCode` in
the response (D3.16's developer affordance — a real gateway never would).

Two behaviours worth recording as correct rather than surprising:

- A second `otp/request` inside the resend window answered
  `429 {"detail":"OTP already sent; retry in 11s."}`. That cooldown is deliberate
  (it stops a caller resetting the brute-force attempt counter by re-requesting),
  and the first code stayed valid.
- The parent's `displayName` is `null` where the other four carry their demo
  names. That is finding 4.

## 4. The documented development path

Run verbatim from `README.md`, which is the point — the value of this test is in
running the commands *as written* rather than the ones already known to work.

| Documented command | Result |
| --- | --- |
| `python -m venv .venv` | **fails**, `python: command not found` — finding 2 |
| `python3 -m venv .venv` | ok |
| `pip install -e ".[dev,ui]"` | ok, but installs no Alembic and no SQLAlchemy |
| `make db-migrate` | **fails**, `make: alembic: No such file or directory` — finding 1 |
| `make seed` | **fails**, `ModuleNotFoundError: No module named 'sqlalchemy'` |
| `pip install -e ".[dev,ui,web,db]"` | ok — the set `make dev` already used |
| `make db-migrate` | ok, `alembic.runtime.migration` reached the DB |
| `make seed` | ok, `{"reference_rows": 0, "demo_accounts": 0, "event": "db.seed.done"}` |

The final `0/0` is correct idempotent behaviour, not a failure: subjects and
demo accounts already existed, and the second run took the documented
422-recover-via-login path. `ensure_supabase_env` resolved the stack keys from
`supabase status` unprompted, so P6.10's earlier extraction works from a clone.

## 5. The four findings

Full reasoning in D6.8. In severity order:

1. **An empty environment variable is not "unset".** `docker-compose.yml`
   forwards optional credentials as `${GEMINI_API_KEY:-}`, so on a `make up`
   stack with nothing exported the variable is present and empty and pydantic
   built `SecretStr("")` — which is not `None`. Measured *inside the running
   container*: `gemini_api_key is None: False`, secret length 0. So
   `/api/health` reported `apiKeyConfigured: true` on a stack that cannot mark a
   paper, and `GoTrueClient._anon_key`'s explicit
   `AuthError("… is not configured.")` never fired — an empty `apikey` header
   went to GoTrue instead, which **local Kong tolerates**, so it works locally
   and every test stays green while Supabase Cloud would reject it as an
   unrelated-looking 401. Fixed with a blank→`None` validator on the optional
   credential fields only.
2. **The documented install omits the `db` and `web` extras**, so the next two
   documented commands fail outright from a clone.
3. **`python` is not a command** on Debian-family systems — the README and the
   Makefile's `PYTHON` default both assumed it.
4. **`DEMO_PARENT.display_name` was declared and applied nowhere.** The parent is
   the one demo account created through the OTP flow rather than
   `AuthService.signup`, and `verify_otp` mirrors a nameless row. Fixed on the
   recognise path too, so an already-seeded database is corrected by the next
   `make seed`.

## 6. What this run did not prove

Stated rather than rounded off:

- **The Supabase stack was already running**, so `scripts/up.sh` took its
  documented already-running branch. `supabase start` from a cold machine is
  still unexercised here.
- **`make seed` created nothing on this run** because the accounts existed.
  Creation-from-empty was proven separately at session 101, on a deliberately
  cleared demo slate: `demo_accounts: 5`, then `0` on an immediate re-run, with
  all five roles present at the right role and `auth.users` consistent with the
  mirror.
- ~~**The mock-SMS log line is confirmed under the app's logging config, and
  unconfirmed inside the container.**~~ **RESOLVED 2026-08-12 (session 104,
  P6.10-followup) — measured, and the hypothesis above was right about the
  mechanism but understated the scope.**

  The container's entry point is `python -m lemely.web`, which never called
  `configure_logging()`. uvicorn's default `LOGGING_CONFIG` declares handlers
  for the `uvicorn*` loggers and **carries no `root` entry at all**, so
  `dictConfig` left the root logger handler-less; a bare
  `logging.getLogger("lemely.auth.sms").info(...)` propagated to that empty root
  and fell through to `logging.lastResort`, which is pinned at WARNING and drops
  it. Nothing raised. **So the defect was not the OTP line — it was that no
  `lemely.*` record below WARNING was emitted by the container at all.**

  Fixed by calling `configure_logging()` in `lemely/web/__main__.py` before
  `uvicorn.run`, which is where the gap was observed and not in `create_app()`
  (the test suite and `scripts/e2e_server.py` import that factory, and
  reconfiguring global logging as a side effect of building the app would reach
  into processes that never asked for it). `tests/test_web_entrypoint.py` pins
  it, and the fix was **inverted**: removing the call fails
  `test_main_configures_logging_before_starting_uvicorn`.

  Verified on a real container, not inferred: `docker compose up -d --build
  backend` → healthy → `POST /api/auth/otp/request` returned
  `{"status":"sent","devCode":"977289"}` and `docker compose logs backend` then
  carried `{"event": "Mock SMS to +10000000000: your Lemely code is 977289",
  "level": "info", …}` — the same code, through the documented command. README
  and DELIVERY.md §7 are now true as written; neither was weakened.

## 7. The transferable lesson

**A fresh-clone test is not a formality.** Every finding above was invisible to
all thirteen gates, which had gone green with 0 skipped on this same tree hours
earlier. The gates run inside an environment that is already correct; this
criterion is about that environment being *reachable* from a clone. The two
things that made it productive were running the documented commands as written,
and checking every claim against the running containers instead of the source.
