# Decisions log
(orchestrator records every non-trivial decision here: what, why, alternatives)

## Phase 1

### D1.12 — Teacher paper upload drops the caller-supplied `student_id` (cross-tenant write kill)
- **What:** `POST /api/papers/upload` (`lemely/web/routers/teacher.py::upload_paper`) no longer
  accepts a `student_id` form field. The interim paper bucket is keyed solely on the
  server-generated `paper_id` (`resolved_student = paper_id`). Found by the Phase-1 acceptance
  adversarial review as finding **H2**.
- **Why:** The old code did `resolved_student = student_id.strip() or paper_id`, trusting a
  caller-supplied identity to decide whose history a graded paper is written into. With the
  teacher→class↔student ownership model still deferred (D1.6), no teacher can be *authorized* to
  write into a specific student's bucket, so honoring a supplied id is an unauthenticated
  cross-tenant write vector (a teacher — or a smuggled value — could target any student key).
  Removing the field makes the contract honest: the upload lands in its own paper-keyed bucket
  and nothing is attributed to a real student account until verified ownership exists.
- **Association deferred, not lost:** binding a graded paper to a real student account lands with
  the DB-backed class model (Phase 2/3), gated on a verified teacher→student ownership check —
  the same boundary D1.6 records as deferred. This is the correct place for it; faking it now
  would re-introduce the IDOR D1.6 closed on the student routes.
- **Blast radius:** existing `test_web_teacher.py` uploads still send `student_id` in the form
  body; FastAPI ignores undeclared form fields (no 422) and those tests only assert on
  `paper_id`/job status/sandbox containment, so they stay green. No DTO/JSON contract changed.
- **Alternatives:** keep the field but ignore it server-side (rejected: a trusted-looking field
  silently dropped is a footgun — the same reasoning that removed `studentId` from the student
  DTOs in D1.6); gate it behind a teacher→student ownership check now (rejected: the class model
  it needs does not exist until Phase 2/3 — this is deferral, not a shortcut).

### D1.11 — Device/session registry: sid-claim + sid-gated DB liveness check (immediate eviction)
- **What:** Max **3** concurrent devices per account. Each real login (email/password,
  parent OTP, and self-service signup) registers a `Device` row and embeds its id in the
  minted access token as a top-level `session_id` claim. `get_auth_context` decodes the
  token offline as before, then — **only when a `session_id` claim is present** — performs a
  single indexed DB read to confirm that device row is not revoked; an evicted/unknown
  session → **401**. Tokens without a `session_id` (hermetic tests, seat-invite signup with
  no device context) skip the check entirely, preserving the offline path.
- **Device identity (the client-vs-server fork):** the client sends an optional stable opaque
  `deviceId` (the SPA mints one once and keeps it in localStorage) plus its `User-Agent`. If a
  non-revoked device row matches `(user_id, client_device_id)`, that row is **reused** — a
  re-login on the same device is NOT a new slot; its `last_seen_at` is refreshed. If no
  `deviceId` is supplied, every login mints a fresh device (a distinct session).
- **Eviction:** after registering, if the user holds > 3 non-revoked devices, the **oldest by
  `last_seen_at`** (tie-break `created_at`) is revoked (`revoked_at = now()`) until 3 remain.
  Because eviction sets `revoked_at`, the evicted session's next request fails the liveness
  check → immediate, real invalidation (faithful to "silently invalidates the oldest session").
- **Enforcement fork resolution — chose (a) request-time DB check, scoped:** the STATE fork
  weighed (a) a per-request DB lookup vs (b) refresh-boundary-only revocation with a short TTL.
  Chose (a). D1.5's rejected cost was an **external** JWKS network hop + kid-rotation dependency
  in the token hot path; a `session_id` liveness lookup is one indexed read against Postgres,
  already a hard runtime dependency of every data-serving route — so it does NOT reintroduce the
  dependency class D1.5 avoided, and it delivers immediate invalidation that (b) cannot (no
  refresh flow exists yet, so under (b) an evicted token would stay valid up to its 3600s TTL).
  Scoping the check to sid-bearing tokens keeps the hermetic auth-dependency suite offline.
- **Schema:** additive migration `0003_device_client_id` adds `devices.client_device_id`
  (nullable String) + index `ix_devices_user_id_client_device_id`. Additive-only per D1.2; the
  STATE note "no migration needed" assumed the friendly `device_label`/`user_agent` columns
  sufficed, but a stable client fingerprint needs its own column so "same device" dedupe does
  not collide with the human label. `refresh_token_id` stays reserved for the future refresh flow.
- **last_seen_at semantics:** refreshed only at login (register), not on every request — keeping
  the per-request path a single read, no write. Eviction by login-recency is the correct
  "concurrent devices" notion; a Phase-5 device-management UI can later add explicit sign-out.
- **Alternatives:** (b) refresh-boundary revocation (rejected: weak/eventual invalidation, and
  no refresh flow exists to trigger it); reuse `refresh_token_id`/`device_label` for the client
  id (rejected: conflates distinct concerns, blocks the future refresh flow / friendly label).

### D1.6 — RBAC model: least-privilege role gating + token-derived ownership; teacher tenancy deferred
- **What:** Authorization is enforced by a `require_role(*roles)` dependency factory
  (`lemely/web/deps.py`) layered on `get_auth_context`. It authenticates first (401 on
  missing/invalid token) then 403s any caller whose `AuthContext.role` is not in the allowed
  set. Application: (a) every **student** route depends on `require_role(Role.student)` and
  keys all data off `auth.user_id` (a student can only ever read/write their own history
  bucket); (b) the **teacher** router is gated at the router level with
  `require_role(Role.teacher, Role.school_admin, Role.platform_admin)` so every current and
  future teacher route inherits the staff guard; (c) `/api/health` and the `/api/auth/*`
  routes stay public by design.
- **IDOR kill:** POST /student/plan and POST /student/onboarding previously trusted a
  caller-supplied `studentId` (any caller could act as any student). Both now require a
  student token and derive identity from `auth.user_id`; `studentId` was **removed** from
  `StudyPlanRequest`/`OnboardingRequest`, so under `extra="forbid"` a smuggled id is a 422,
  not an impersonation. Covered by tests/test_authz_matrix.py.
- **Least privilege, no super-role:** each portal names exactly the roles allowed; there is
  no implicit "admin sees all" bypass at the route layer (a platform_admin reaching student
  data will come via dedicated admin surfaces later, not by hitting /student/*). This keeps
  the authz matrix explicit and testable.
- **Teacher per-tenant ownership DEFERRED (honest limitation):** "a teacher sees only their
  own classes/students" cannot be enforced yet because the teacher routes still read the
  shared single-bucket interim `HistoryStore` (no class↔teacher / student↔teacher mapping is
  wired to routes). P1.6 enforces the *role* boundary (students/parents are fully locked out
  of teacher routes); row-level teacher→class ownership lands when these routes move onto the
  DB-backed class model (Phase 2/3). Recorded so this is not mistaken for complete tenancy.
- **Alternatives:** per-route `Depends` on every teacher handler (rejected: 15 signatures to
  touch, easy to forget one; router-level guard is defense-in-depth and future-proof);
  keeping `studentId` in the body but ignoring it (rejected: a trusted-looking field that is
  silently dropped is a footgun — removing it makes the contract honest).

### D1.5 — Backend is the sole token issuer to clients (HS256 self-signed), revising D1.4
- **What:** The FastAPI backend mints **every** access token it hands to a client, self-signed
  HS256 with the shared `SupabaseSettings.jwt_secret`, in the GoTrue claim shape (`sub`,
  `aud="authenticated"`, `role="authenticated"`, `exp`, `app_metadata.role`, `phone`/`email`).
  This applies to BOTH email/password login and parent phone-OTP. GoTrue is still the identity +
  password-hashing + account-lifecycle authority: `AuthService.signup` admin-creates the user in
  GoTrue and `login` calls the GoTrue password grant to **verify the password** — but GoTrue's own
  access token is discarded, not forwarded. `decode_token` stays HS256-only (one validation path).
- **Why (evidence, not assumption):** The live integration test (`test_auth_live.py`) caught that
  the local Supabase stack's GoTrue signs access tokens with **ES256** (asymmetric, JWKS + `kid`
  header: `{'alg':'ES256','kid':'b812…','typ':'JWT'}`), NOT the shared HS256 secret that D1.4
  assumed. This is the current Supabase CLI default (asymmetric JWT signing keys). D1.4's premise
  — "both token kinds validate identically under the shared HS256 secret" — was therefore false in
  reality; the hermetic `FakeGoTrueBackend` had signed HS256 and masked the gap.
- **Fork + tiebreaker:** Two viable fixes: (A) validate real ES256 GoTrue tokens via the JWKS
  endpoint (canonical, but adds a networked fetch+cache+kid-rotation path to token validation AND
  still needs HS256 for the self-signed OTP tokens → two validation paths); (B) have the backend
  re-mint all client tokens as HS256. Because our SPA only ever talks to FastAPI (never GoTrue
  directly), FastAPI is already both issuer-proxy and validator, so re-minting is transparent.
  MISSION's undecidable-fork rule (simplest, cheapest, most reversible) selects **B**: one uniform,
  fully-offline-verifiable token path; no JWKS network dependency in the hot path; version-
  independent of the Supabase CLI's key management (survives `supabase db reset`).
- **Phase-2 compatibility:** Supabase Storage/PostgREST still accept HS256 tokens signed with the
  shared `jwt_secret` (the anon/service keys are themselves such tokens), so direct SPA→Storage
  uploads in Phase 2 keep working with our minted token (`aud=authenticated`, `role=authenticated`).
- **Reversible:** to adopt GoTrue's ES256 tokens later, add JWKS/ES256 validation to `decode_token`
  and stop re-minting in `AuthService`; nothing else changes because the claim shape is identical.
- **Supersedes:** D1.4's statement that email/password uses GoTrue's token and only OTP is
  self-signed. Everything else in D1.4 (GoTrue for password/identity, `SmsProvider` seam, in-memory
  OTP store, mirroring to `public.users`, deps) stands.

### D1.4 — Auth backend split: GoTrue for email/password, self-signed HS256 for mock parent OTP
- **What:** A new `lemely/auth/` package owns identity. Email/password signup+login go
  through Supabase **GoTrue** (local stack): admin-create the user (service-role key,
  email pre-confirmed for dev, `role` in `user_metadata`) and password grant for login;
  every GoTrue user is mirrored 1:1 into `public.users` (id = `auth.users.id`, per D1.1)
  with role/email/phone. Parent **phone-OTP** runs behind an `SmsProvider` protocol whose
  `MockSmsProvider` logs the code; `AuthService` owns the OTP challenge lifecycle (generate
  → store → deliver → verify) and, on successful verify, **mints a Supabase-compatible
  access token self-signed with the shared HS256 `jwt_secret`** carrying the same claims
  GoTrue issues (`sub`, `aud="authenticated"`, `role="authenticated"`, `exp`,
  `app_metadata.role`, `phone`). Both token kinds therefore validate identically under the
  (next task) JWT middleware.
- **Why:** GoTrue's native phone OTP requires a real SMS provider (Twilio/etc.); the MISSION
  mandates a MOCK provider now with "one config switch to a real provider later." Owning the
  OTP challenge ourselves keeps the mock fully functional and testable offline, while the
  `SmsProvider` seam is the exact switch point. Self-signing the OTP session token with the
  same secret + claim shape GoTrue uses means the downstream validator needs no special case
  — email/password and OTP tokens are indistinguishable to RBAC. We already hold the local
  secret in `SupabaseSettings.jwt_secret`; this is a local-dev convenience, not a production
  key-management pattern (a real deploy switches parent OTP to GoTrue+real SMS and drops the
  self-signer).
- **OTP challenge store is in-memory (TTL, default 300s, max 5 attempts), NOT a DB table:**
  OTP challenges are ephemeral; adding a table would be a non-additive schema change outside
  the P1.3 schema and buys nothing (a single-process dev/test server). Recorded so a later
  multi-worker deploy knows to move it to Redis/DB. Deterministic in tests via injected
  clock + RNG.
- **Deps:** `httpx` added to the `web` extra (GoTrue REST client; already installed,
  matches the async-free sync-httpx call style); `pyjwt[crypto]` stays in the `db` extra and
  CI's test job now installs `db` too (needed to import `lemely.db`/`lemely.auth` at all).
- **Testing:** hermetic unit tests use a `FakeAuthBackend` + `MockSmsProvider` + injected
  clock/RNG and never touch the network; a live integration test hits the real local GoTrue
  + Postgres and **skips cleanly when either is unreachable** (mirrors `test_db_schema.py`),
  so CI stays green until a Supabase service block is added before the E2E acceptance task.
- **Alternatives:** GoTrue admin `generate_link` magic-link exchange for the OTP session
  (rejected: convoluted for phone, still needs an SMS-less verify hack, more moving parts);
  a real DB OTP table (rejected: non-additive, unnecessary for single-process dev);
  self-signing ALL tokens incl. email/password (rejected: throws away GoTrue's real
  password hashing, refresh-token rotation, and account lifecycle we get for free).

### D1.1 — Auth identity mapping: `public.users.id` == Supabase `auth.users.id`, no cross-schema FK
- **What:** Our application-owned `public.users` table uses a `UUID` primary key
  that is set to the Supabase GoTrue user id (`auth.users.id`) at signup time.
  We do NOT declare a SQL foreign key from `public.users.id` to `auth.users.id`.
  GoTrue owns the `auth` schema; our Alembic migrations own `public`. Role, active
  flag, and profile fields live on `public.users`.
- **Why:** Supabase manages the `auth` schema out-of-band (its own migrations); a
  cross-schema FK into a table Alembic doesn't control is fragile (reset/upgrade
  ordering, `supabase db reset` wipes auth) and is the officially discouraged
  pattern. Mirroring the id gives a stable 1:1 join without coupling migration
  ownership. Every other table FKs to `public.users.id` (which we own), so
  referential integrity across the app schema is fully enforced.
- **Alternatives:** Real FK to `auth.users` (rejected: brittle across resets, and
  Alembic autogenerate would try to manage a table it must not touch); a separate
  `profiles` table keyed by auth id (deferred — Phase-4 onboarding fields are
  additive columns; one `users` table is simpler now).

### D1.2 — Schema conventions (additive-only guarantee for Phases 2-5)
- **What:** (a) UUID primary keys everywhere via server default `gen_random_uuid()`;
  (b) all timestamps `TIMESTAMP(timezone=True)` with `created_at`/`updated_at`
  server-defaulted to `now()`; (c) role/enumerations as Postgres `ENUM` types
  (extended later with `ALTER TYPE ... ADD VALUE`, which is additive); (d) money as
  integer minor units + ISO currency code (never float); (e) confidence persisted
  as BOTH a band enum and a float score, mirroring `core.schemas`; method-mark
  breakdown persisted as JSONB; (f) sync SQLAlchemy 2.0 `Mapped`/`mapped_column`
  matching the sync engine in `lemely/db/session.py`.
- **Why:** Phases 2-5 must need only additive migrations (MISSION §4). UUIDs are
  merge/import-safe and let us mirror auth ids; timezone-aware timestamps avoid the
  classic naive-datetime trap; ENUM-add and column-add are additive whereas type
  changes are not; integer money avoids rounding drift in billing.

### D1.3 — Enum `server_default`s rendered with an explicit `::type` cast
- **What:** ENUM-typed columns that carry a server default (e.g. `subjects.board`,
  `seats.status`, `subscriptions.status`, `uploads.status`, `review_queue.status`)
  set it as `sa.text("'value'::enumname")` in BOTH the ORM model and the migration,
  rather than a bare `sa.literal("value")`.
- **Why:** With a bare string literal the model renders the default as `'value'`
  while Postgres stores it as `'value'::enumname`. `alembic check`/autogenerate then
  compares them by running `SELECT 'value'::enumname = 'value'::VARCHAR`, which errors
  (`no operator matches ... enum = varchar`) and, worse, produces a spurious drift
  diff on every future autogenerate — directly threatening the additive-only guarantee
  (D1.2). The explicit cast makes model and DB defaults render identically, so
  `alembic check` reports "No new upgrade operations detected". Verified live against
  the local Supabase Postgres.
- **Also fixed here:** the model modules imported `uuid`/`datetime`/`date` only under
  `TYPE_CHECKING`, but SQLAlchemy 2.0 resolves `Mapped[...]` annotations at runtime, so
  every model failed to configure (`MappedAnnotationError: Could not resolve ...
  Mapped[uuid.UUID]`). Those types are now imported at runtime; a scoped
  `per-file-ignores` entry (`lemely/db/models/** = TC001/TC002/TC003`) stops ruff from
  moving them back — mirroring the existing exemption for the pydantic web DTOs.

## Phase 0

### D0.1 — Single lockfile: keep `uv.lock`, delete `requirements.lock`
- **What:** Standardise on `uv.lock` (uv's native universal lockfile) as the one
  dependency lock. Deleted `requirements.lock`. `Makefile` `lock` target changed
  from `pip freeze --exclude-editable > requirements.lock` to `uv lock`.
- **Why:** The two lockfiles drifted (audit §1): `requirements.lock` was compiled
  via `uv pip compile ... --extra ui --extra dev` (missing the `web` extra) while
  the Makefile regenerated it via `pip freeze` — a different mechanism. `uv` is
  installed (0.11.29) and `uv.lock` already resolves all extras (ui+web+dev).
  CI installs from `pyproject.toml` (not a lockfile), so removing the pip-format
  lock costs nothing operationally while killing the drift.
- **Alternatives:** Keep only `requirements.lock` (rejected: pip-freeze output is
  environment-specific and lossy); keep both (rejected: guaranteed drift).

### D0.2 — GEMINI_API_KEY env-mapping trap fix (validation_alias + populate_by_name)
- **What:** `Settings.gemini_api_key` now uses
  `validation_alias=AliasChoices("LEMELY_GEMINI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY")`
  and the model enables `populate_by_name=True`.
- **Why:** Audit blocker #11: an unprefixed `GEMINI_API_KEY` authenticated the
  CLI/Gradio (google-genai SDK env fallback) but left the web portal degraded/503
  because web AI gates read `settings.gemini_api_key`, which only
  `LEMELY_GEMINI_API_KEY` populated. Now one env var works everywhere.
  `populate_by_name=True` is required so `Settings.model_validate(model_dump())`
  round-trips (test fixtures rebuild Settings from a dump) don't reject the
  field-name key under `extra="forbid"`.
- **Alternatives:** Custom env source override (rejected: more code, less idiomatic);
  reading the SDK vars manually in each gate (rejected: scattered, error-prone).

### D0.3 — Test hermeticity against a developer's repo `.env`
- **What:** Added `tests/conftest.py` (session autouse) that disables `.env` file
  discovery in `Settings.model_config` for the test session; hardened
  `_IsolatedEnv` in `test_runtime_config.py` to also clear the unprefixed keys and
  chdir into a temp dir.
- **Why:** `Settings(env_file=".env")` reads a repo-root `.env` at every
  instantiation. A developer keeping a real `.env` (with a Gemini key) for local
  runs flipped 3 "without key" assertions (doctor, config defaults, web plan 503).
  CI has no `.env` and always passed; this makes the suite green everywhere so the
  unattended `pytest` gate is trustworthy. No `os.environ` mutation, no assertion
  weakened — only the stray file source is neutralised.

### D0.4 — CI now installs the `web` extra and adds a `web` job
- **What:** Test job installs `.[dev,ui,web]` (was `.[dev,ui]`); new `web` CI job
  runs `npm ci`, `typecheck`, `oxlint`, `build` for the SPA.
- **Why:** The FastAPI tests import `fastapi` (web extra) — CI omitting it was a
  latent failure once CI got past the (previously red) ruff-format step. Audit §9
  flagged the SPA has zero CI coverage.

### D0.5 — DET parser: wire the modular `lemely/io/det/`, delete the monolith `parsers_det.py`
- **What:** Adopt the staged modular package `lemely/io/det/` as the one
  `DeterministicMarkSchemeParser`; delete `lemely/io/parsers_det.py`; rewire the
  3 call sites (cli, gradio, teacher router) and rewrite the parser test suite to
  target the modular package. Both expose the same
  `DeterministicMarkSchemeParser.__call__(pdf_path) -> MarkScheme`; the modular one
  additionally takes `cfg: DetParserSettings | None`.
- **Why (evidence, not assumption):** Ran BOTH parsers head-to-head on the 4 real
  Physics mark-scheme PDFs in `Sources/`:
  - MCQ (`0625_m20_ms_12`) and alternative-practical (`0625_m21_ms_62`): identical,
    correct output — leaf-mark total == `maximum_mark` (40 == 40) for both parsers.
  - Theory (`0625_s19_ms_43`, `0625_s20_ms_31`): the **monolith silently returns
    wrong totals** (88 and 76 vs the stated 80) with no error — audit blocker #10,
    the exact "silent mis-parse" that poisons marking accuracy. The **modular parser
    runs its Stage-4 reconciler**, detects the mismatch, and raises `ParseError` so
    `ChainedMarkSchemeParser` routes the paper to Gemini instead of persisting
    garbage. It also honors `DetParserSettings` (the monolith ignores it entirely).
  - The modular package is already `mypy --strict` clean.
- **Consequence (recorded honestly):** With the modular parser, theory papers can
  no longer be "deterministically parsed" into a (wrong) scheme — they escalate to
  Gemini via the chain. On the raw no-Gemini path (`parse-mark-schemes` without
  `--use-gemini`) a theory paper now raises `ParseError` (fail-loud) instead of
  writing a silently-wrong JSON. For an accuracy-first product this is the correct
  trade: MCQ/practical stay fully deterministic; complex theory uses Gemini (the
  intended chain design) rather than emitting numbers that don't sum to the max.
- **Alternatives:** Keep the monolith and bolt reconciliation onto it (rejected:
  duplicates work the modular package already does cleanly, and the monolith still
  ignores `DetParserSettings`); keep both (rejected: MISSION requires picking one).

### D0.6 — Gemini cost cap: persistent file-backed USD ledger, $8 hard ceiling
- **What:** New `lemely/io/cost_ledger.py` (`CostLedger`) persists cumulative USD to
  `{output_dir}/gemini_spend.json` (atomic write, survives process restarts).
  Renamed `GeminiSettings.monthly_usd_ceiling` → `total_usd_ceiling` (default now
  **8.0**, active); added `usd_warning_thresholds=[4.0, 6.0]`. `GeminiClient` checks
  the ledger total before/after calls and publishes `BUDGET_WARNING`/`BUDGET_EXCEEDED`
  bus events on threshold crossings (each fires once, tracked in the ledger).
  `lemely/runtime/notify.py` (`post_ntfy`, stdlib urllib, no-op unless
  `LEMELY_NTFY_TOPIC` set) + `budget_notify.register_budget_ntfy()` (idempotent)
  deliver those events to ntfy, registered from the CLI and web entrypoints.
- **Why:** Audit blocker #5 — `monthly_usd_ceiling` reset every process, so there was
  no real cross-run cap. Verified fix with two separate OS processes sharing one
  ledger file: proc2 reads proc1's spend; $4/$6 warnings fire exactly once across
  the boundary. `lemely.runtime` stays free of domain imports (notify uses only
  stdlib) so the import-linter contract holds.
- **Test hermeticity:** `tests/conftest.py` now also neutralises ambient `lemely.toml`
  discovery (repo-root + ~/.config/lemely), needed because the rename would make a
  developer's local `monthly_usd_ceiling` key an `extra=forbid` error. Explicit
  `toml_path`/temp-cwd discovery still works.

### D0.7 — `lemely doctor` real Gemini reachability (acceptance criterion)
- **What:** Added `GeminiClient.check_reachable()` — a zero-token `models.list()`
  round-trip that raises `ExternalServiceError` on missing key / auth failure /
  network error. `doctor` (without `--no-network`) now calls it and reports the
  actual result, replacing the hardcoded `gemini_reachable=False` "not yet
  implemented" stub (audit §6/§10 #15). `--no-network` still skips it.
- **Why:** Phase 0 acceptance requires "`lemely doctor` reports the real Gemini
  reachability." `models.list()` validates credentials + connectivity without
  generation, so it costs nothing against the $8 ledger.
- **Tests:** live-ping reachable→all_passed; unreachable→exit 3 + gemini_reachable
  false (both mock `check_reachable`, no real network in the suite).

### D1.7 — Adversarial auth-surface hardening (signup RBAC, OTP resend cooldown, history-key guard)
- **What:** Three defensive fixes to the Phase-1 auth surface, found by an
  adversarial review pass:
  1. **Self-service signup is student-only.** `POST /api/auth/signup` now 403s any
     role other than `student` (`_SELF_SERVICE_SIGNUP_ROLES = {student}`). Elevated
     roles (teacher/school_admin/platform_admin) are minted only by an authenticated
     admin via the seat/invite flow (later task), never by an anonymous caller.
  2. **OTP resend cooldown.** `OtpStore.issue` raises `OtpRateLimitError` if a *live*
     challenge for the same phone was issued < `otp_min_resend_seconds` (default 30)
     ago; the router maps it to **429**. Without this, a caller could reset the
     `max_attempts` brute-force counter by re-requesting before lockout.
  3. **History-store key guard.** `HistoryStore` runs every `student_id` through
     `_safe_key`, rejecting path separators, `.`/`..` segments, and NUL bytes before
     it becomes a `{root}/{id}.json` path — closing a traversal vector for the
     request-supplied ids some callers pass.
- **Why:** All three are unauthenticated/low-privilege escalation or abuse vectors on
  routes that are now publicly reachable. Cheapest correct fix at each layer; no schema
  or API-shape change (signup DTO unchanged — the 403 is behavioural).
- **Tests:** `test_signup_elevated_role_forbidden` (3 roles → 403) + student→200;
  `test_resend_within_cooldown_is_rate_limited` / `_allowed_after_cooldown` /
  `_once_prior_challenge_expired` + router `test_otp_resend_within_cooldown_returns_429`;
  `test_unsafe_student_id_rejected` (7 hostile keys) + a dotted-id allow test.
- **Alternatives:** Map the resend cooldown to 401 (rejected: 429 is the correct
  semantic and lets clients back off); allow-list roles at the DTO layer (rejected: the
  behavioural 403 keeps one signup DTO and a clear audit log line).

### D1.8 — HistoryStore → Postgres via an interface-preserving repository
- **What:** `lemely/db/history_repo.py` (`DbHistoryStore`) replaces the JSON
  `HistoryStore` behind the *same* surface (`load(user_id) -> StudentHistory`,
  `append(user_id, record)`, `list_students()`), so all downstream analytics that
  consume `StudentHistory`/`PaperRecord` are untouched. A `PaperRecord` maps to one
  `Attempt` row (+ its `WeaknessRecord` rows from `weak_areas`); `load` reconstructs
  `PaperRecord`s from those rows.
- **Impedance mismatches resolved (recorded honestly):**
  1. `student_id` (free-form str) → `Attempt.user_id` (UUID FK → `users.id`). The repo
     requires a real user row (post-P1.4 every authed caller is mirrored into
     `public.users`, so `auth.user_id` is a valid UUID). Legacy non-UUID JSON keys
     (e.g. "anonymous") cannot be migrated and are reported/skipped, not forced.
  2. `ExamMetadata.session_month` ("May/June"…) ↔ `SessionMonth` enum via the inverse
     of `SESSION_MONTH_LABELS`.
  3. `recorded_at` ISO **string** ↔ tz-aware `DateTime`: parsed on write, `isoformat()`
     on read. Canonical UTC strings (`now_iso()`) round-trip exactly.
  4. `PaperRecord` carries **no** per-question data, so migrated attempts have zero
     `question_results` (those come from the live marking pipeline, not history).
- **Ordering (intentional improvement over the JSON store):** `load` returns records
  in `recorded_at` order (JSON preserved append order); `weak_areas` within a record are
  sorted by `topic`. Both are deterministic and semantically correct for trend/aggregation
  code; parity tests normalise on the same keys.
- **Migration:** `migrate_json_history(json_store, db_store)` walks every JSON student
  file and re-appends each record through the repo; returns a per-key result so unmigratable
  legacy keys are surfaced. `outputs/history/` is currently EMPTY (the interim store was only
  dev/test-written), so there is no production data at risk.
- **Rollout:** additive first (repo + parity tests, routers untouched, JSON store intact),
  then swap `get_history_store` → DB repo + relocate `now_iso` + delete `io/history_store.py`.
- **Alternatives:** async SQLAlchemy (rejected: whole stack is sync, D-session.py); a new
  wire/DTO shape for history (rejected: preserving `PaperRecord` keeps the blast radius to
  the storage layer only).

### D1.9 — Web/product history moves to Postgres; CLI + Gradio keep the JSON store
- **What:** `get_history_store` (the web dependency) now returns `DbHistoryStore`
  (D1.8), so every FastAPI route and the web grading service persist/read student
  history in Postgres. `now_iso()` and a structural `HistoryStoreProtocol`
  (`load`/`append`/`list_students`) move to `lemely/core/history.py`; routers and the
  grading service are annotated against the Protocol so both stores satisfy them.
- **Deviation from the STATE task, recorded honestly:** the task said "delete the JSON
  store after parity proven." The audit assumed the web routers were its only consumers —
  they are NOT: `app/cli.py` and `app/gradio_app.py`/`gradio_callbacks.py` also use the
  JSON `HistoryStore`. The CLI and Gradio are local, single-process, **unauthenticated**
  tools with no tenancy and no UUID user ids; forcing a Supabase-Postgres round-trip on
  them is heavy, out of the task's "web routers" scope, and less reversible.
- **Decision (simplest / cheapest / most reversible per MISSION):** migrate only the
  web/product surface to the DB now; **retain `lemely/io/history_store.py` for the CLI +
  Gradio internal tools.** Full deletion of the JSON store is DEFERRED until those tools are
  either retired or given their own migration — a separate, explicit scope decision, not a
  silent side effect of the web migration. Parity between the two stores is already proven
  (D1.8), so a future switch is low-risk.
- **Consequences:** web tests are unaffected (they override `get_history_store` with an
  in-tmp JSON store as a hermetic test double at runtime — the DB is never touched in the
  web suite). `test_history_store.py` stays valid (the JSON store still ships). No web route
  reads history without an override, so no web test silently starts requiring Postgres.

### D1.10 — Seat model: on-demand allocation, locked quota check, membership-based ownership
- **What:** `lemely/db/seat_repo.py` (`SeatService`) owns seat allocation. A school buys a
  fixed `seat_quota`; each occupied slot is a non-revoked `Seat` row. Seats are allocated
  **on demand** — there is no pre-provisioning step: `invite_student` creates a student
  account and, in the same locked transaction, inserts an `assigned` seat *iff* the school
  has headroom. `revoke_seat` flips a seat to `revoked` (freeing quota) without deleting the
  student's account (idempotent). Introspection: `list_admin_schools` / `seat_usage`. The
  HTTP surface is `lemely/web/routers/school.py` under `/api/school/seats` (list / invite /
  {id}/revoke), gated at the router level to `school_admin` alone.
- **TOCTOU-safe quota:** `invite_student` locks the school row `FOR UPDATE` for the duration,
  so two concurrent invites serialise — the second sees the first's committed seat and is
  rejected once the quota is full, instead of both slipping past a stale count. Ownership and
  quota are checked *before* account creation, so a rejected invite never leaves an orphaned
  account (proven by `test_invite_beyond_quota_is_rejected_without_creating_account`).
- **Ownership is membership-based, no super-role (mirrors D1.6):** every mutating call
  re-verifies the caller holds a `school_admin` `SchoolMembership` for the target school (or
  the seat's school); anyone else gets a `SeatOwnershipError` → 403, never data or a
  mutation. Even `platform_admin` is 403 on this surface (dedicated admin surface later).
- **Account-creation seam:** `StudentAccountCreator` is a Protocol so the pure seat/quota/
  ownership logic is Postgres-testable without the live GoTrue stack. The real adapter
  (`AuthServiceStudentCreator`, in `web/deps.py` — the one layer that already imports both
  `lemely.auth` and `lemely.db`, keeping the import graph acyclic) wraps `AuthService.signup`
  pinned to `Role.student`; the invite route generates a one-time temporary password when the
  admin omits one and returns it once (no student email provider in v1, exactly as the mock
  SMS provider surfaces the parent OTP).
- **Personal subscription coexists:** a seated student may *also* hold a personal
  `Subscription` — the schema enforces no exclusivity and the seat service touches neither
  table (proven by `test_seated_student_may_also_hold_a_personal_subscription`), satisfying
  the MISSION §4 requirement.
- **Alternatives:** pre-provision N empty seats at school creation then claim them (rejected:
  an extra lifecycle state and migration for no gain — an occupied-seat count against the
  quota is the same invariant with less machinery); advisory application-level locking instead
  of `FOR UPDATE` (rejected: the row lock is the simplest correct serialisation and needs no
  external coordinator).

### D2.1 — Grade-boundary data stays JSON-file-based, not a new DB table
- **What:** P2.2 (real per-paper-variant CAIE grade-threshold ingestion) populates
  `lemely/data/grade_boundaries.json` with scraped official data and replaces the
  hardcoded `_defaults` guesses with **real per-subject historical averages** computed
  from the scraped exact entries. `GradeBoundaryStore` (`lemely/io/grade_boundaries.py`)
  and its `resolve()` fallback chain (exact → subject_default → global_default) are
  **unchanged** — only the data backing it changes from guessed to real+provenanced.
- **Why not a DB table:** the `papers` table (P1.3) could host boundaries, but
  `GradeBoundaryStore` is used by three surfaces — the web API, the CLI, and Gradio
  (`app/cli.py`, `app/gradio_app.py`) — and only the web surface has a DB session (CLI/
  Gradio are the same local/unauthenticated tools D1.9 kept off Postgres). Moving
  boundaries into the DB would mean either giving CLI/Gradio a DB dependency they don't
  otherwise need, or forking the resolver into DB-backed (web) and file-backed (CLI/
  Gradio) implementations that must be kept in sync — both more machinery for no
  behavioural gain over the existing file-backed resolver, which is already
  injectable/testable (`GradeBoundaryStore(data_path)`) and consistent with how the
  mark-scheme corpus is stored (files, not DB rows).
- **Provenance:** each scraped exact entry's source document URL is recorded in a
  sibling `lemely/data/grade_boundaries_provenance.json` keyed by the same boundary key,
  so the JSON data file itself stays a clean grade→percentage map (matching the existing
  reader) while still giving full traceability to the official CAIE document each number
  came from.
- **"Estimated" flag:** `boundary_source` already encodes this — `"exact"` vs
  `"subject_default"`/`"global_default"` — and the student-facing integrity copy in
  `lemely/web/routers/student.py::_integrity_summary` already reads as an estimate
  disclosure for the non-exact cases. No new field was needed; the existing Literal is
  the "estimated" flag the MISSION §4 P2.2 acceptance asks for.
- **Source: official cambridgeinternational.org, NOT the three mirrors MISSION §4 named
  — recorded deviation.** Before scraping, checked all three: `gceguide.com` now
  resolves to an unrelated Indonesian gambling-slot site (the domain has been squatted
  since the mission was written — confirmed via `curl`, page title/meta is
  "AGUNG11 - Situs Slot..."), so it is unusable and was NOT fetched again beyond that one
  identifying request. `papacambridge.com` and `xtremepape.rs` both resolved to their
  expected past-papers content and were viable, but Cambridge International's own site
  (`cambridgeinternational.org/.../grade-threshold-tables`) publishes the same official
  per-subject grade-threshold PDFs directly, with a predictable per-session index page —
  strictly better provenance (primary source, not a re-host) for the same data, so that
  was used instead of the fan mirrors. Flagging the squatted domain here so no future
  session wastes a request on it or, worse, trusts its content.
- **No workflow/subagent fan-out — direct script instead, recorded deviation from the
  MISSION §5 "use a workflow for boundary-document scraping/parsing" guidance.** That
  guidance was written before reconnaissance; once the actual page/PDF structure was
  known (one small index page per session, one PDF per subject, a clean fixed-width
  table per PDF), the task is fully deterministic pattern-matching, not judgment work —
  spinning up agents to read PDF text and transcribe numbers would be slower, costlier,
  and less accurate than a parser regex. Wrote `scripts/ingest_grade_boundaries.py`
  instead: discovers the published session list, finds each subject's PDF per session,
  downloads, and parses the per-component threshold table with `pdfplumber`. Simpler,
  cheaper, and fully reversible/rerunnable — the reversible-fork tiebreaker in MISSION §1.
- **Scope of "all available sessions":** Cambridge's own grade-threshold-tables index
  currently lists exactly 13 published sessions: March/June/November 2022 through 2025,
  plus March 2026 (results not yet published for these 3 subjects as of ingestion, so it
  contributed 0 entries). That is the full available history on the authoritative source
  — not an arbitrary cutoff. The script fetched all 13 for all 3 subjects (39 candidate
  documents; 36 existed and parsed, 3 were not-yet-published), yielding 347 real
  per-component exact entries, from which `_defaults` (per-subject historical averages)
  are now genuinely computed rather than guessed. Extending coverage later is additive:
  re-running the script picks up newly published sessions automatically (it derives the
  session list from the live index each run) and merges into the same JSON + provenance
  files without touching existing keys.
