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

### D2.2 — One review threshold at 0.90 (provisional, Physics-only); confidence alone provably cannot satisfy the §4 flag gate
- **What:** The three coincidentally-equal confidence thresholds are collapsed to **two
  semantically distinct knobs**:
  1. `GeminiSettings.escalation_confidence_threshold` (`lemely/runtime/config.py:46`,
     unchanged at **0.80**) stays a *budget* knob only: `AICorrector.mark_question`
     (`lemely/io/correction_ai.py:75,97`) spends a thinking retry then a Pro call to try to
     **improve** a mark before it is final. Raising it costs Gemini dollars.
  2. **`REVIEW_CONFIDENCE_THRESHOLD = 0.90`, defined once** in `lemely/core/schemas.py`
     (immediately below `confidence_band_for_score`), is the *human-review* gate: a final
     mark may reach a student unreviewed only if confidence ≥ this. Raising it costs teacher
     time. It is now read by all three sites that previously carried their own literal:
     `lemely/io/correction_ai.py::_build_ai_corrected` (was a hardcoded `0.80` — the
     duplicate), `lemely/db/attempt_repo.py` (was its own `REVIEW_CONFIDENCE_THRESHOLD =
     0.90`, now a re-export so the module's public name is preserved), and
     `lemely/web/routers/teacher.py:119` (`_REVIEW_CONFIDENCE`, now an alias — a **fourth**
     copy the STATE note had not counted).
- **Why one constant and NOT a `lemely.toml` field (deviation from the STATE task's
  "e.g. `review_flag_confidence_threshold`" suggestion):** the value must be byte-identical
  in the marking layer (`io`), the persistence layer (`db`) and the web layer, and those three
  do not share a `Settings` injection path — `AttemptRepository` takes only a `sessionmaker`,
  and giving it a settings dependency to carry one float is more machinery than the problem.
  Worse, a per-machine TOML override of an *accuracy-gate* invariant would silently invalidate
  the harness numbers that justify it (the same class of footgun D0.3 closed for `.env`).
  Promoting the constant to config later is additive and touches one import. Its value
  coincides with the `ConfidenceBand.HIGH` cut-off, so the invariant states in one sentence:
  **only HIGH-confidence marks are auto-graded.**
- **Should (A) and (B) be allowed to diverge? Yes, and they now do — the coupling was the
  bug.** They answer different questions ("is it worth more money to re-ask?" vs "is it safe
  to show a student?"), and the correct ordering is escalate-low ≤ review-high: escalating at
  <0.90 would have fired on 5 of the 21 theory questions in the calibration batch and burned
  budget on questions the model was already right about, while flagging at <0.80 fired on
  exactly 1 of 21. Wiring (B) to (A) would have permanently welded a cost knob to a safety
  knob; a second config field would have kept the drift risk with extra surface. One shared
  domain constant kills the drift outright.
- **(B)'s old 0.80 was strictly dead in production, and that made the harness lie —
  the most important thing this decision fixes.** Because (C) was 0.90 and the persist gate
  is `needs_teacher_review OR confidence < (C)` (`lemely/db/attempt_repo.py:122`), a 0.80
  flag could never add a review item that 0.90 did not already add. Its only independent
  effects were the teacher UI badge and — critically — the accuracy harness, whose
  `flag_recall`/`flag_precision_HIGH` read `cq.needs_teacher_review`
  (`lemely/accuracy/harness.py:187,288`). So the 2026-08-04 batch reported **flag_recall
  0.0%** while the code that actually routes work to a human would have caught 1 of the 3
  disagreements. The harness was measuring a gate that does not exist. Post-change the harness
  measures exactly the production gate: same batch → **flag_recall 33.3%** (1/3),
  **flag_precision_HIGH 91.7%** (22/24, up from 89.3%). Answering the STATE question directly:
  **yes — MISSION §4's "review threshold" criterion is evaluated against this one constant
  from now on, and it is the same number (B) and (C) both use, so the distinction that made
  the question necessary no longer exists.**
- **Why 0.90 and not higher — the step function (this is the evidence, and it is robust to
  n=29):** the 21 theory confidences in `tests/golden/results/2026-08-04-2a9af42.json` take
  only six distinct values — 0.65 ×1, 0.85 ×4, 0.90 ×1, 0.95 ×1, 0.96 ×1, **0.98 ×13** — with
  the 3 disagreements at 0.98, 0.85, 0.98. Sweeping the threshold over that distribution:

  | threshold | theory questions flagged | disagreements caught |
  |---|---|---|
  | 0.80 (old (B)) | 1 / 21 | 0 / 3 |
  | **0.90 (chosen)** | **5 / 21** | **1 / 3** |
  | 0.91 – 0.98 | 6 → 8 / 21 | 1 / 3 |
  | 0.99 | 21 / 21 | 3 / 3 |

  Every value in (0.90, 0.98] buys **zero** additional recall for strictly more teacher work,
  and `flag_precision_HIGH` actively *degrades* across that range (0.9167 at 0.90 → 0.9130 at
  0.91 → 0.9091 at 0.96 → 0.9048 at 0.97) because raising the bar removes correct answers from
  the auto-graded set while both 0.98 errors stay in it. Strictly dominated on both metrics, so
  "tune it up a bit" is not an option that exists here. The only value
  that satisfies MISSION's literal "100% of disagreements carry confidence below the review
  threshold" is >0.98, which flags **every AI-marked question** and reduces the product to
  "auto-marks MCQs only". That is a degenerate pass, not a pass. 0.90 is the Pareto-optimal
  point on the frontier and is independently anchored (HIGH band, and the value (C) already
  shipped with in P2.1). The finding driving this is *where the probability mass sits* — 62%
  of theory marks report the identical 0.98 — not a fine boundary estimated from 3 points, so
  a bigger corpus can move the optimum but is unlikely to invert the ordering.
- **Answering "is a single global threshold sufficient?" — No, provably not, and the honest
  reason is that the fix does not live in the flagging layer.** Decomposing
  `mark_accuracy_theory` 85.7% by *ground-truth* mark shape: **15/15 (100%)** on
  all-or-nothing answers (7 full-credit + 7 zero-credit + one 1-mark question) but **3/6
  (50%)** on genuinely partial-credit answers. All 3 errors are the identical failure:
  the method (M) marks were correctly identified and the **accuracy (A) mark was awarded even
  though the final numeric value was wrong** (1b: 89 vs 8.9; 5b: 3.33 vs 3.0 N, also missing
  M3; 12c: 9 vs 4.5 mg). The model is not mis-reporting its confidence about a thing it
  half-knows — it is confidently failing to re-check arithmetic. Method-mark partial credit is
  exactly the capability MISSION §1 sells, and it is at 50%.
- **The proposed secondary signal (`awarded_marks != question.marks` + high confidence) was
  evaluated and REJECTED on the data — recorded so it is not re-proposed blind.** Neither
  direction of a mark-value rule separates these cases:
  - "flag when `0 < awarded < max`" (predicted partial credit): flags 4/21 theory, catches
    **1/3** — identical recall to the 0.90 threshold already achieved, for 4 extra flags.
  - "flag when `awarded == max` on a multi-mark question": flags 8/21, catches 2/3 — but 6 of
    those 8 flags are correct full-credit answers, i.e. it mostly penalises good students.
  - the union (≡ "flag any non-zero award") flags 14/21 for 3/3: flag-everything again.
  The reason it cannot work: 2 of the 3 errors awarded **full** marks and 1 awarded **partial**,
  so the observable award value is anti-correlated with itself across the failure set. Adding
  an unvalidated heuristic here would trade a measurable miss for an unmeasurable one.
- **What WAS added instead — a zero-false-positive structural signal.**
  `_build_ai_corrected` now flags on `mark.awarded_marks != clamp(mark.awarded_marks)`
  **independently of confidence**: a marker asking for 4 marks on a 3-mark question has
  misread the mark scheme, and the pre-existing `max(0, min(...))` clamp was silently
  repairing that and shipping it as a confident mark. It fires zero times on the current
  corpus (no over-award occurred), so it adds no review load, and it can only fire when the
  model is objectively wrong. `_build_ai_corrected` also now sets a human-readable
  `review_reason` (previously `None` for every AI-flagged question, so the teacher queue and
  `question_results.review_reason` showed a flag with no stated cause).
- **Numbers are PROVISIONAL — Physics-only, n=29 (8 MCQ + 21 theory), 3 disagreements, one
  paper (0625 s20 qp31 + m20 qp12), one session, all disagreements the same failure mode.**
  Recorded in the constant's docstring too, so nobody reads 0.90 as calibrated across boards
  or subjects.
- **Step-7 sequencing decision (0580/0606 fixtures): ship the threshold now, source the
  fixtures next, revisit the number once — do NOT block on broader evidence.** Three reasons:
  (a) the step-function above shows broader fixtures cannot change the *direction* of this
  call unless the confidence distribution itself changes shape across subjects; (b) the change
  is one constant plus one import per call site — the cheapest, most reversible option MISSION
  §1 asks for; (c) the actual blocker is `mark_accuracy_theory` 85.7% vs the ≥95% gate, which
  is a marking-quality defect that more fixtures will *measure*, not fix. Sourcing 0580/0606
  remains a required step, for **statistical power**: with only 24 auto-graded questions, a
  single wrong mark caps `flag_precision_HIGH` at 95.8%, so the §4 ≥99% target is
  **arithmetically unreachable at this corpus size regardless of the threshold** — the gate is
  currently unmeasurable, not merely unmet. Mandatory revisit trigger: the first harness run
  that includes 0580 or 0606 fixtures re-runs the threshold sweep above and amends this entry.
- **Flagged risks / follow-ups (accuracy constraint, MISSION §4):**
  1. **Phase-2 gate is still failing and this decision does not fix it:** `mark_accuracy`
     89.7% (<95%), `mark_accuracy_theory` 85.7% (<95%), `flag_recall` 33.3% (<85%),
     `flag_precision_HIGH` 91.7% (<99%). Only `id_match_rate` (100%) passes. The remaining
     work is a **marking** task, not a thresholds task: the marker must verify the final
     numeric value before awarding an A mark (a deterministic re-computation, or a cheap
     second-pass "recheck the final value only" call). That is the correct next accuracy task
     and is where the 50%-on-partial-credit number gets moved.
  2. `AccuracyEvalSettings.flag_recall_target` (`lemely/runtime/config.py`) is **0.85**, but
     MISSION §4 says *100%* of disagreements must fall below the review threshold. The config
     is the weaker of the two; the MISSION text is what gates the phase. Left unchanged
     (out of scope), flagged so the discrepancy is not read as a passing gate later.
  3. Calibration is measurably overconfident, not just noisy: the 0.90–1.00 bucket's actual
     accuracy is 87.5% (gap −0.075) and 0.80–0.90's is 75% (gap −0.10). Any future work that
     wants a *finer* threshold must first make the marker emit a spread of confidences at all
     — 62% of theory marks currently report the same 0.98.
- **Test changes (documented per MISSION §5, not weakened):** `tests/test_correction_ai.py`
  `ThresholdTests` previously asserted `test_review_false_at_0_80` — it encoded the old
  literal, so it necessarily fails under the new threshold. Replaced with tests written
  against the shared constant (`test_review_fires_just_below_threshold`,
  `test_review_false_at_threshold`), plus `test_old_0_80_threshold_now_flags` as an explicit
  regression guard for the behaviour change, and two clamp tests
  (`test_out_of_range_award_flags_despite_full_confidence`,
  `test_in_range_award_at_full_confidence_is_auto_graded`). No assertion was loosened; the
  boundary is pinned as inclusive-at-threshold (0.90 auto-grades, 0.899 flags).
- **Blast radius:** no schema change, no migration, no API/DTO shape change. Behavioural:
  marks with confidence in [0.80, 0.90) now carry `needs_teacher_review=True` (previously
  `False`) — this is a *widening* of the flag that the DB gate was already applying, so the
  review queue's contents are unchanged; what changes is that the per-question flag, the
  paper-level aggregate, the teacher badge and the harness metric finally agree with it.
- **Alternatives considered:** (i) wire (B) to `escalation_confidence_threshold` (rejected:
  welds a cost knob to a safety knob; also *lowers* the effective review bar to 0.80 in the
  UI/harness while the DB uses 0.90 — the drift stays); (ii) a new
  `review_flag_confidence_threshold` TOML field (rejected: three layers with no shared
  Settings path, and an operator-tunable accuracy-gate invariant is a footgun — see above);
  (iii) raise the threshold to 0.99 to make the §4 gate literally pass (rejected: flags 100%
  of AI-marked questions — a gate satisfied by deleting the feature is a faked pass, which
  MISSION §5 forbids); (iv) leave 0.90 and add the `awarded != max` heuristic (rejected on
  the data, quantified above); (v) block the decision on 0580/0606 fixtures (rejected: the
  step function makes the call insensitive to them, and this is the reversible option).

### D2.3 — 0580/0606 fixtures landed; mandatory D2.2 revisit confirms the gate is a marking-quality problem, not a threshold problem — 0.90 kept unchanged
- **What:** P2.3 step 7 completed. Verified and committed the two `data-engineer` outputs
  dispatched in the prior (crashed) session: real Cambridge IGCSE Mathematics 0580/22
  (May/June 2023) and Additional Mathematics 0606/12 (May/June 2023) mark schemes + question
  papers under `Sources/{Mathematics,AdditionalMathematics}/` (gitignored, consistent with
  `Sources/` policy), and 6 new committed golden fixtures mirroring the 0625 pattern exactly:
  `tests/golden/0580_s23_qp_22_theory_{correct,partial,wrong}` (7 questions each) and
  `tests/golden/0606_s23_qp_12_theory_{correct,partial,wrong}` (6 questions each). Also fixed
  a real latent bug the dispatch surfaced: `lemely/io/det/profiles.py` registered a 0606
  profile but never a 0580 one, so `get_profile("0580")` fell through to `_DEFAULT_PROFILE`,
  which maps paper 1 → MCQ — wrong for 0580 (no MCQ component at all; papers 1/3 are
  non-calculator/calculator Core, 2/4 are non-calculator/calculator Extended). Added
  `_MATHEMATICS_PROFILE` with the correct 1/2/3/4 → Core/Extended/Core/Extended mapping and
  corrected a comment on the 0606 profile that had incorrectly asserted "0580 paper 1 is MCQ".
- **Verification performed (not just trusting the subagents' prior claims, per MISSION §5):**
  read page 1 of all 4 sourced PDFs via `pdfplumber` — genuine Cambridge headers/watermarks
  confirm `MATHEMATICS 0580/22 Paper 2 (Extended) May/June 2023` and `ADDITIONAL MATHEMATICS
  0606/12 Paper 1 May/June 2023`, not fabricated; validated all 6 `mark_scheme.json` files
  against `lemely.core.loose_schemas.MarkScheme` (all pass); spot-checked answer points against
  the real mark scheme text (e.g. 0580 Q1 answer point "−13" matches "−5 − 8 = −13" in the
  `correct` fixture; Q12a point "53" matches the fixture's derivation) and confirmed the
  `wrong`/`partial` variants carry genuinely altered student answers and reduced
  `awarded_marks`, not copies. Ran full §6-relevant gates: ruff/ruff-format/mypy(115
  files)/lint-imports clean; pytest 100% pass (0 failures; the usual Postgres/live-auth skips —
  local Supabase stack could not be started this session, see Blast radius below, this is an
  environment gap not a regression). Gemini spend delta: **+$0.0150** (cumulative
  $0.0502 of the $8.00 ceiling) for the live `measure-accuracy` run below — sane and
  nowhere near budget pressure.
- **Mandatory revisit executed (D2.2's own trigger: "the first harness run that includes 0580
  or 0606 fixtures re-runs the threshold sweep and amends this entry").** Ran
  `lemely measure-accuracy` across all 10 committed fixtures (0625 MCQ + 3×0625 theory +
  3×0580 theory + 3×0606 theory), n=68 questions (60 theory, 8 MCQ) — saved to
  `tests/golden/results/2026-08-04-2473205.json` (gitignored, regenerable, cache-hits are free
  per the usual pattern).
  - **Metrics got materially worse, not better, with more data — this is signal, not noise:**
    `mark_accuracy` 89.7%→**80.9%**, `mark_accuracy_theory` 85.7%→**78.3%**, `id_match_rate`
    unchanged at 100%, `flag_precision_HIGH` 91.7%→**82.5%**, `flag_recall` 33.3%→**23.1%**.
    Theory disagreements went from 3 (one paper) to **13** (three papers, two subjects): a
    21.7% theory error rate on the broader corpus vs 14.3% on Physics alone.
  - **Threshold sweep at n=68 (vs D2.2's n=29) — the honest re-run of D2.2's own table:**

    | threshold | theory questions flagged (of 60) | disagreements caught (of 13) |
    |---|---|---|
    | 0.80 | 5 | 1 |
    | 0.85 | 5 | 1 |
    | **0.90 (current)** | **11** | **3 (23%)** |
    | 0.95 | 16 | 7 (54%) |
    | 0.96–0.98 | 30–35 | 9 (69%) |
    | 0.99 | 59 | 13 (100%) |

    At n=29 (D2.2), 0.90 already looked weak (1/3 caught) but was read as a thin-sample
    artifact possibly fixable by more data. At n=68 it is now unambiguous: **no threshold
    below 0.99 gets anywhere close to the MISSION §4 "100% of disagreements below threshold"
    requirement**, and 0.99 remains the same degenerate "flag 98% of theory questions" case
    D2.2 already rejected as a faked pass (MISSION §5). The broader corpus did not change the
    *direction* of D2.2's call (predicted correctly: no non-degenerate threshold clears the
    gate) but it does sharpen the diagnosis: this is not a calibration problem that more data
    fixes, it is a **structural ceiling** — confidence and correctness are close to
    independent on this task as currently implemented.
  - **Calibration confirms systemic, worsening overconfidence:** the 0.90–1.00 confidence
    bucket (49 of 68 predictions) is only 79.6% actually correct (gap **−0.154**, vs D2.2's
    thinner −0.075 reading); 0.80–0.90 is 66.7% correct (gap −0.183). The model states high
    confidence at roughly the same rate whether it is right or wrong.
- **Decision: `REVIEW_CONFIDENCE_THRESHOLD` stays at 0.90, unchanged.** The sweep above proves
  raising it further only trades teacher-review load for marginal recall while the honest
  ceiling (0.99 = flag-everything) is still off the table for the reasons D2.2 already gave.
  Moving it would be re-litigating an already-answered question with data that confirms the
  original answer more strongly, not new evidence against it.
- **P2.3's accuracy gate remains unmet, now with statistically adequate evidence (n=68, 3
  papers, 2 subjects) instead of D2.2's provisional n=29/1-subject caveat — the "sourcing
  0580/0606 gets us to a measurable gate" reasoning is now resolved: the gate is measurable
  and it fails.** The path to closing it is unchanged from D2.2's diagnosis and is now the
  clear next P2.3 step: a marking-quality fix that verifies the final numeric/algebraic value
  before awarding the accuracy (A) mark on partial-credit questions, not further threshold or
  fixture work. Recorded as the explicit next action in `BUILD/STATE.md` (P2.3 step 8).
- **Blast radius:** fixtures + one profile registry entry + one comment fix; no schema,
  migration, or API change. `REVIEW_CONFIDENCE_THRESHOLD` numerically unchanged, so no
  behavioural change to what reaches the review queue. Local Supabase stack was down this
  session (stale root-owned files under `supabase/.temp/start-secrets/` from a prior crashed
  container, not removable without root — outside this session's write access) so
  Postgres-backed integration tests skipped as usual; this is an environment gap, not
  introduced by this change, and does not affect the accuracy-harness work (no DB dependency).
  Flagged here so a future session with shell/root access cleans it up rather than
  re-diagnosing it.

### D2.4 — Deterministic calculated-answer verification (P2.3 step 8, the marking-quality fix)

- **What:** `lemely/io/correction_ai.py` gained a deterministic backstop that runs after
  every AI marking call, independent of stated confidence (D2.3 proved confidence cannot
  substitute for this). For every point the AI claims was matched, if the mark scheme
  attaches a `calculated_answer.value` to that point (a specific numerical result is
  required, any M/A/B/C code), the point — and its marks — are rejected unless that value
  is actually present in the student's text. `needs_teacher_review` gets a third
  independent trigger (`value_mismatch`) alongside D2.2's existing two (low confidence,
  out-of-range award).
- **Resumed on a dirty tree:** this session inherited an untracked, uncommitted WIP diff to
  `lemely/io/correction_ai.py` implementing the first version of this idea. Verified before
  trusting (MISSION §5): static gates had one lint issue (fixed); no tests existed for the
  new logic at all — added 20 unit tests before treating any of this as done.
- **Design iterated three times against the real golden corpus, not just unit tests — each
  iteration caught by a live `measure-accuracy` re-run, not by inspection:**
  1. First cut: extract every number (decimals + naive `a/b` fractions) from
     `student_answer + " " + student_working` concatenated, check for a match. Net effect on
     the 10-fixture corpus: **zero** — it fixed 2 of the known D2.2/D2.3 disagreements
     (0625 `1b`, `12c`) but broke 2 previously-*correct* answers (0606 `q1`, both variants),
     because the student wrote `b = 3/8` and the naive extractor never evaluates fractions.
     `mark_accuracy` was unchanged at 80.9% — fixes and regressions cancelled exactly.
  2. Added fraction evaluation, but the regex still matched *any* `a/b` substring anywhere in
     the combined text, including intermediate division shown as working. Re-running
     surfaced a worse bug: `148 / 16.6 = 89` (mark scheme expects `8.9`, student's decimal-slip
     wrong-answer is `89`) — the fix evaluated `148/16.6 ≈ 8.9` itself and "corrected" the
     student's arithmetic, validating a wrong answer as if the fraction were the stated value.
     Same for `36 / 8 = 9` (expects `4.5`). This is worse than doing nothing: it launders
     exactly the failure class D2.3 was written to catch. Full re-run reverted to the
     pre-fix baseline exactly (0 diffs vs the original bug) because the false-accept on
     `1b`/`12c` cancelled the true-reject that was working before.
  3. Final design: (a) fraction *evaluation* is applied ONLY to `student_answer` — never to
     `student_working` — because working legitimately contains a division whose correct
     result differs from what the student actually wrote as their final answer; evaluating it
     ourselves re-does their arithmetic instead of checking their claim. (b) fraction operands
     must be plain integers not adjacent to a decimal point (blocks `148/16.6`) and not
     immediately followed by `= <number>` (blocks `36/8 = 9`, a division-with-shown-result).
     (c) plain-decimal *matching* (no evaluation, pure string search) is safe and IS applied to
     both `student_answer` and `student_working` combined, because extraction commonly splits
     a question's final requested value into `answer` while an intermediate quantity that
     still carries its own mark-scheme point (e.g. a B-mark checkpoint like `AC = 28.89` inside
     a shaded-area question) lands in `working` — restricting the first (broken) iteration's
     "answer-only, fall back to working only if answer is empty" idea to decimals-only fixed a
     third regression (0606 `4b`) that the answer-only restriction had introduced.
- **Final verification (live, real Gemini, cached from the D2.3 run — near-zero incremental
  cost since only the deterministic post-processing changed, not the marking prompt):** full
  10-fixture re-run, n=68. `mark_accuracy` 80.9%→**83.8%**, `mark_accuracy_theory`
  78.3%→**81.7%**, `flag_precision_HIGH` 82.5%→**85.5%**, `flag_recall` 23.1%→**27.3%**.
  Diffed every one of the 68 question results against the D2.3 baseline: **exactly 2 changed,
  both fixes (0625 `1b` and `12c`, wrong→correct), zero regressions.** Gemini spend delta
  ~$0.006 (cumulative $0.058 of the $8.00 ceiling) — a few live calls during interactive
  debugging of the intermediate broken iterations, not from the harness re-runs themselves
  (those were cache hits).
- **Honest limitation, not fixed by this change:** 0625 `5b` (the third original D2.2/D2.3
  disagreement) is still wrong and still unflagged. Root cause differs from the other two:
  Gemini's marker credits point `p3` (a *method* point — "F = (200-20)/60 OR 180/60", the
  student instead wrote `F = 200/60`, omitting the −20 step) despite the shown method being
  wrong; `p3` carries no `calculated_answer`, so this backstop has nothing to check. Verifying
  *method* correctness (did the student's working match the mark scheme's required algebraic
  form, not just produce a number) is a materially harder problem — comparing free-form
  algebra against a mark-scheme pattern, not a numeric-tolerance check — and is explicitly out
  of scope for this deterministic pass. Recorded here rather than silently left for a future
  session to rediscover from scratch.
- **P2.3's §4 accuracy gate (`>95%` mark-level, `100%` of disagreements below the review
  threshold) is still NOT met** — 83.8% and partial flag coverage are real improvement, not a
  pass. Whether to pursue the harder method-verification problem, accept a documented
  deviation on this gate, or find another lever is the next P2.3 judgment call, not resolved
  by this entry.
- **Blast radius:** `lemely/io/correction_ai.py` (new functions + `_build_ai_corrected` wiring)
  and `tests/test_correction_ai.py` (+20 tests: 3 baseline-behavior classes reused, 6 new
  calculated-answer-verification cases including the 3 regression guards that pin the
  iteration-2/3 bugs described above so they cannot silently reappear). No schema, API, or
  migration change — `matched_point_ids`/`awarded_marks`/`needs_teacher_review`/`review_reason`
  are all pre-existing `CorrectedQuestion` fields. Full suite green (0 failures, cov 81.95%,
  ruff/format/mypy/lint-imports clean).

### D2.5 — P2.3 accepted with a documented, unresolved §4 accuracy-gate deviation; proceeding to P2.4

- **What:** Closing P2.3 (accuracy harness + golden fixtures) and moving to P2.4 without the
  MISSION §4 gate (`≥95% mark-level`, `100% of disagreements below the review threshold`)
  being met. Current measured state: `mark_accuracy` 83.8%, `flag_recall` 27.3% (D2.4).
- **Why this is a genuinely undecidable fork, not a corner being cut:** the two approaches
  available at this point are (a) a second-pass Gemini "verify final value/method" call gated
  behind the escalation budget, or (b) accept the current state as documented and move on.
  Neither is obviously correct, so per MISSION §1 ("pick the option that is simplest, cheapest,
  and most reversible... and continue — never stop to wait for a human"), this records the
  choice rather than leaving it silently undecided or blocking the build indefinitely.
- **Reasoning for (b) over (a):**
  - Threshold tuning is exhausted (D2.3: no non-degenerate threshold clears the gate).
  - The deterministic value-check backstop (D2.4) has closed every case it structurally can —
    the one remaining known disagreement (0625 `5b`) fails because the AI credits a *method*
    point that carries no `calculated_answer`, not because a stated numeric value is wrong.
    Catching it needs judging whether free-form algebraic working matches a mark scheme's
    required method shape — a materially different, harder problem than a numeric-tolerance
    check.
  - A second Gemini self-review call is not obviously going to fix that: D2.3 already found
    "confidence and correctness are close to independent" for this model on this task — i.e.
    the model's own self-assessment is not reliably calibrated, which is exactly the capability
    a second self-review pass would need to lean on. There's no evidence a second pass avoids
    the same miscalibration as the first, only a hope.
  - Accuracy work here is genuinely open-ended (this could easily become an entire second
    workstream — prompt engineering, per-subject calibration, structured method-matching
    against parsed mark-scheme algebra), which is a different shape of problem than "build the
    core loop" (MISSION §1's framing for Phase 2). Continuing to sink unbounded effort into one
    accuracy percentage point risks starving the rest of Phase 2 (P2.4–P2.10) and the phases
    behind it of any session time at all.
  - This is reversible: nothing about (b) forecloses (a). A future session (or a dedicated
    accuracy-improvement pass, potentially after the DB-backed review queue from P2.1 has
    accumulated real teacher corrections to learn from) can pick the second-pass idea back up
    with no rework of what D2.4 already built.
- **What "accepted" means concretely:** the §4 gate is NOT silently marked as passing anywhere.
  `REVIEW_CONFIDENCE_THRESHOLD` and the calculated-answer backstop stay exactly as D2.4 left
  them — no threshold was raised to fake a pass, no fixture was altered or dropped to change
  the measured rate. This gap must be carried into `DELIVERY.md` at Phase-2 acceptance (P2.10)
  as an explicit, honest limitation: current measured accuracy (83.8% mark-level; the numbers
  from whatever the last `measure-accuracy` run before P2.10 shows) vs the §4 target, with the
  method-verification gap named as the reason, not glossed over as "in progress."
- **Blast radius:** documentation only — no code change. `BUILD/STATE.md`'s P2.3 checklist
  entries are marked done with this deviation noted; P2.4 begins next.

### D2.6 — P2.5 scoped to backend Supabase Storage wiring only; camera-capture UI + client-side PDF assembly deferred to P2.7/P2.9

- **What:** MISSION §4's P2.5 line item reads "Upload path: plain file upload (25MB cap kept)
  + PWA camera capture → client-side multi-page PDF assembly → Supabase Storage → backend
  job," which reads as one task spanning both the frontend camera/PDF-assembly UI and the
  backend Storage wiring. This session scopes P2.5 to the backend half only: migrate the
  existing (working, tested) local-disk student upload path to real Supabase Storage
  (bucket, signed access, backend pipeline reads the stored object), keep the 25MB cap.
  The camera-capture UI component and client-side multi-page PDF assembly library land
  with the screen-by-screen frontend wiring already scoped to P2.7 (whose checklist entry
  explicitly lists "CorrectPaper (real SSE upload→correct, kill setTimeout theatre)" as the
  screen that owns this upload flow), with PWA installability/manifest/service-worker polish
  around it staying in P2.9 as already scoped.
- **Why this is a genuinely undecidable fork, not a corner being cut:** building camera-capture
  UI now would require either (a) wiring it against `web/lib/api.ts`, which does not exist yet
  as a real client (P2.6, not done) — meaning the component would ship against a mock and need
  rework once P2.6 lands, or (b) building the API client scaffolding early, out of order,
  duplicating what P2.6 is explicitly scoped to do properly (react-query, typed hooks, auth
  bearer wiring). Both are worse than doing backend Storage now (independently testable, no
  frontend dependency) and the camera UI once P2.6's real client exists to wire it against.
- **Reasoning:** P2.5's backend half is self-contained and matches the existing P2.1/P2.4
  pattern (repo/router/DTO changes with hermetic + live-skip tests) with no cross-phase
  ordering problem. Splitting also keeps each unit small and independently verifiable, per
  MISSION §5's "small, committed, checkpointed units."
- **What "backend-only" means concretely:** `StudentUploadRepository`/`student_upload`
  endpoint/`run()` correction closure move from local-disk paths to a `StorageBackend`
  Protocol (Storage object key stored in `Upload.storage_path`, same column, new semantics);
  teacher.py's own upload usage (mark-scheme uploads in the grading console) is explicitly
  OUT of scope for P2.5 — it stays on local disk since MISSION's P2.5 wording only mentions
  the student self-mark path, and touching it would widen blast radius for no phase-checklist
  benefit. This exclusion is deliberate, not an oversight, and can be revisited if a later
  phase needs teacher uploads on Storage too.
- **Testing reality carried forward, not new:** the local Supabase stack is still down this
  session (root-owned dirs from a prior crashed container, needs sudo — see the recurring
  environment note in STATE.md), and CI's Postgres-only service (`.github/workflows/ci.yml`)
  does not run the Storage API either — this mirrors the EXISTING GoTrue precedent
  (`HttpGoTrueBackend` is only exercised by a live-skip test; hermetic tests use a
  `Protocol`-conforming fake). The new `HttpStorageBackend` follows the identical pattern:
  real HTTP client tested live-only (skips everywhere until Storage is reachable), business
  logic tested via a `FakeStorageBackend` double. Not a new gap — the same one Phase 1 already
  accepted for auth, applied consistently to storage.
- **Blast radius:** `lemely/io/storage.py` (new), `lemely/web/deps.py` (new singleton +
  reset), `lemely/web/routers/student.py` (upload + correct endpoints), `lemely/runtime/
  config.py` (new `StorageSettings`), tests for all of the above. No DB migration (the
  `storage_path` column already exists from P1.3 and is repurposed, not renamed, to avoid an
  unnecessary migration for a semantic-only change).
- **Completion note (same session, resumed on the WIP described above):** the PLAN as recorded
  had `StorageSettings`/`HttpStorageBackend`/`FakeStorageBackend`/`get_storage_backend`
  already implemented and dirty on disk (steps 1–3) — verified correct before trusting (matches
  the recorded design exactly, gates were not yet run). Completed steps 4–6: wired
  `student_upload` to `storage_backend.upload` (object key
  `uploads/{user_id}/{paperId}/{filename}`, `storage_path` now stores that key) and
  `student_correct`'s `run()` closure to `storage_backend.download` into a
  `tempfile.TemporaryDirectory` (not the PLAN's literal `NamedTemporaryFile` — deviation
  explained below). **Deviation from the literal PLAN text:** the PLAN only described
  downloading the scan; it didn't address the optional sibling `mark_scheme.pdf` that
  `student_upload` has always accepted and `resolve_mark_scheme` looks for next to the scan on
  disk. Downloading only the scan would have silently regressed that existing, tested feature
  (a student-supplied mark scheme would stop being found, always falling back to corpus lookup
  or `None`) — not acceptable for a "no behavior change beyond storage location" migration. Added
  `StorageObjectNotFoundError` (moved from being test-local in `tests/storage_fakes.py` into
  `lemely/io/storage.py` so production code and the fake raise the identical type;
  `HttpStorageBackend.download` now raises it on HTTP 404, `ExternalServiceError` on other
  non-2xx) so `run()` can distinguish "no sibling scheme" (expected, silently skipped) from a
  genuine Storage failure, and download the sibling into the same temp directory under the
  original `mark_scheme.pdf` name so `resolve_mark_scheme`'s sibling-file check keeps working
  unchanged. Also added `tests/test_storage_live.py` (live-skip, mirrors `test_auth_live.py`'s
  skip condition) rather than a `httpx.MockTransport` hermetic test for `HttpStorageBackend` —
  the PLAN's step 6 asked to match "whatever pattern test_gotrue.py/similar already uses," but
  no such file/pattern exists: `HttpGoTrueBackend` itself has zero hermetic unit tests, only
  live-skip integration coverage (confirmed via grep). Matched that actual precedent instead of
  the PLAN's untested assumption. Updated `tests/test_student_correct.py`: `client` fixture now
  overrides `get_storage_backend` with one shared `FakeStorageBackend()` instance (a fresh
  instance per lambda call would have broken the upload→correct flow across requests);
  `test_upload_sets_status_and_writes_file` now asserts against the fake store instead of a
  local disk path; added `test_upload_over_size_cap_is_413` for the new `check_upload_cap` call
  site (the equivalent gap already existed pre-P2.5 for `write_upload_capped`, tracked as
  non-blocking debt in STATE.md — this closes it for the new call site only, not retroactively).
  Gates green (see STATE.md Next-action entry for numbers); Postgres-backed tests skip locally
  (Supabase stack still down, same root-owned-dir issue, sudo unavailable in this session too —
  unchanged from the dispatch session, CI unaffected).

### D2.7 — P2.7 result delivery: SSE `complete` frame carries full per-question data; two small additive backend DTO changes precede the frontend wiring

- **What:** Before wiring the student screens, two small additive backend changes:
  1. `PaperHistoryRowDTO` (`lemely/web/schemas_student.py`) gains an `id: str` field — the
     forward-position index into `history.records` (same addressing scheme
     `GET /student/result/{paper_id}` already uses). Populated in `student_subject()`
     (`lemely/web/routers/student.py`) by enumerating `records` *before* reversing for display
     order (the current code does `for record in reversed(records)` with no index tracked).
  2. The `complete`-phase `MARKING_PROGRESS` event published at the end of `student_correct`'s
     `run()` gains a `questions` key: `[question_to_dto(q).model_dump(by_alias=True) for q in
     report.correction.questions]`, reusing the existing `question_to_dto` converter from
     `lemely/web/schemas.py`. Bus event payloads are free-form dicts (no schema), so this is a
     non-breaking additive key.
- **Why:** Two gaps surfaced while planning the frontend wiring, both would have made honest
  wiring impossible without a backend touch: (1) `PaperHistoryRowDTO` had no addressable id, so
  Subject's paper-history table (real, data-backed rows) had nothing to link to a result page
  with — a UI dead end, not a frontend bug. (2) `ResultDTO.theory`/`.integrity` are
  **documented as structurally empty** when served via the index-based
  `GET /student/result/{paper_id}` route (history records persist totals + weak-areas only, not
  per-question theory/mark-points/integrity flags — see that endpoint's docstring). The *only*
  place the full per-question `CorrectionResult` exists is inside `student_correct`'s live SSE
  closure, and it was being discarded after computing scalar totals for the `complete` frame.
  Without forwarding it, the flagship "just corrected a paper, see the real marks/method-marks/
  weaknesses" moment (P2.10's literal E2E acceptance wording) would be unbuildable — the richest
  screen in the product would only ever be able to show structurally-empty theory data.
- **Design:** CorrectPaper consumes the `complete` frame's `questions` (+ existing scalars) and
  assembles a client-side `ResultData`-shaped object, navigating to `/student/result/:paperId`
  via React Router state (`navigate(path, { state })`) rather than triggering a second fetch.
  PaperResult prefers `location.state` when present (the "just corrected" case, full theory/
  integrity) and falls back to `GET /student/result/:paperId` otherwise (browsing an older paper
  from Subject's history table via its new `id` — still honestly structurally-empty for
  theory/integrity, unchanged, already-documented behavior, not a regression). This avoids
  widening `HistoryStoreProtocol`/`DbHistoryStore` to persist and re-serve full per-question
  detail, which is out of scope for a frontend-wiring phase task.
- **Alternatives rejected:** (a) Have `GET /student/result/{id}` return full theory data by
  querying `QuestionResult` rows directly (they exist in Postgres from P2.1) instead of going
  through the reduced `HistoryStoreProtocol` abstraction — rejected as a larger, riskier change
  (bypassing the interim history abstraction entirely) for a phase whose task list says
  "screen-by-screen wiring," not "redesign the result-retrieval data path"; worth revisiting in
  a later phase once `HistoryStoreProtocol` itself is reconsidered. (b) Re-fetch
  `GET /student/subject/{code}` after correction completes and infer the new paper's index —
  rejected: fragile (race with the row actually landing, ordering assumptions) versus the SSE
  frame already holding the exact data needed.
- **Blast radius:** `lemely/web/schemas_student.py` (1 field), `lemely/web/routers/student.py`
  (`student_subject`'s history-row loop + `student_correct`'s `complete` publish call) — both
  additive, no field removed/renamed. Existing tests asserting on `PaperHistoryRowDTO`/the SSE
  `complete` frame shape need their expected-shape assertions extended, not rewritten.

**Addendum (P2.7 step 5 planning) — header fields on the complete frame, and a deliberate
per-question rendering simplification:**

- **Gap found while planning CorrectPaper/PaperResult:** the `complete` frame (as landed in
  step 1) carries only `awarded`/`max_marks`/`grade`/`confidence`/`needs_review`/`questions` —
  no exam metadata (subject/paper/session) and no grade-boundary rail data (`railLeft`/
  `railFoot`/`boundaryYear`), both of which `ResultDTO`'s header needs and both of which
  `GET /student/result/{id}` computes from a `PaperRecord.metadata` that doesn't exist yet at
  SSE-completion time (the record is written *by* `attempt_repo.persist_correction`, from
  inputs the router already has in scope — nothing new to fetch).
- **Decision:** extract a small shared helper, `_result_header_fields(metadata: ExamMetadata,
  awarded: int, maximum: int) -> dict`, computing code/paper/session/boundaryYear/railLeft/
  railFoot exactly as `student_result` already does (same boundary-store call, same format
  strings) — refactor `student_result` to call it too, so the two paths are provably
  consistent rather than duplicated. `student_correct`'s `run()` calls it with
  `mark_scheme.metadata` (the resolved scheme's own metadata — reliable whenever a scheme was
  successfully resolved, unlike the separately-detected `metadata` variable which can be
  `None` when a student supplies their own scheme and Gemini extraction is skipped/unavailable)
  and adds the resulting fields as new top-level SSE kwargs, plus `pct=round(report
  .grade_prediction.percentage)`. `markerLabel`/`summary`/`railNote` are deliberately left
  unpopulated ("") on BOTH paths, matching the existing GET-path convention — this keeps
  fresh-correction and history-browsing visually consistent (no path looks "more narrated"
  than the other) rather than inventing generated copy for one path only.
- **`QuestionResultDTO` gains `topic: str | None`:** `CorrectedQuestion` (core schema) already
  carries `topic`, it just was never surfaced on the DTO. Free, additive, zero new logic —
  add it and populate it in `question_to_dto`.
- **Deliberate scope cut — NOT building `TheoryQuestionDTO`-shaped fresh data:** the mock's
  `TheoryQuestion` shape needs a per-point `text`/`got` breakdown (`MarkPointDTO[]`), which
  requires resolving `matched_point_ids` against the full `MarkScheme`'s `answer_points` per
  question — a real, non-trivial new converter, not a screen-wiring task. Building it now would
  expand this phase task ("wire screens to already-designed DTOs") into "design and implement a
  new per-question-detail data path." Decision: PaperResult's per-question section renders the
  flatter `QuestionResult` list (id/awarded/max/markerSource/confidence/feedback/topic/
  matchedPointIds-as-a-count-not-a-breakdown/reviewReason/flags) directly — a simpler list/row
  layout, not the mock's split MCQ-grid-vs-theory-points-cards UI (which also assumed two
  separate fixed papers via a tab switcher; a real result is one paper, so the tab switcher and
  its `resultP1`/`resultP3`/`mcq`/`dropped`/`theory`/`theoryWeak`/`paperTabs` mock data are
  dropped entirely, not adapted). This is honest given the real data available, and the richer
  per-point UI can be built in a later phase once/if a converter for it is scoped. History-
  browsed results (no `questions` available, GET-only) render the header with an explicit "per-
  question detail is only available right after a paper is corrected" note instead of an empty
  section that looks broken.
- **Blast radius (addendum):** `lemely/web/schemas.py` (1 field), `lemely/web/routers/
  student.py` (new shared helper + both call sites), tests extended for the new frame/DTO
  fields.
