# Uploads on Google Cloud Storage, and a Cloud Run backend that scales — Design

**Issue:** none filed; this document is the specification.
**Plan:** `docs/superpowers/plans/2026-09-03-gcs-uploads-and-cloud-run-scale-out.md`
(to be written from this spec)
**Date:** 2026-09-03

Two requests arrived together: move student and teacher file uploads to Google
Cloud Storage, and unpin `max-instances=1` on Cloud Run. Reading the code showed
they are one piece of work, not two — the single-instance pin is what currently
protects a set of in-process and on-disk state that the teacher upload path is
part of — so this is one spec with one rollout order. §3 records the interview
that fixed its scope.

---

## 1. Problem

### 1.1 Student uploads are already off local disk; teacher uploads are not

The student self-mark path stores scans through a `StorageBackend` Protocol
(`lemely/io/storage.py`) whose only real implementation talks to Supabase
Storage over its REST API, keyed `uploads/{user_id}/{paper_id}/{filename}` with an
optional `mark_scheme.pdf` sibling. The correction run downloads into a temporary
directory before handing paths to the pipeline. That seam is sound and is kept.

The teacher grading console is a different animal. `POST /api/papers/upload`
writes the scan under `output_dir/uploads/{paper_id}` on the container's own
disk, and — more importantly — the paper itself lives only in process memory:
`_PaperStore` in `lemely/web/routers/teacher.py` holds every field the grading
worker mutates (status, stage, per-question progress, detected metadata, the
resolved mark scheme, the report, the error). No database row exists for a
teacher paper. A cold start loses every one of them, and a second instance has
never heard of any of them. Moving only the bytes would fix nothing a teacher
could see.

### 1.2 The parsed mark-scheme corpus is also on local disk

`POST /api/schemes` parses a scheme PDF deterministically and writes both the PDF
and the parsed JSON under `output_dir/schemes`. `GET /api/schemes` lists that
directory, and `resolve_mark_scheme` in `routers/student.py` — used by *both*
portals — scans it for a JSON whose metadata matches a detected paper. Same
failure shape: per instance, gone on restart.

Meanwhile `lemely/db/models/academic.py` already defines `papers` and
`mark_schemes` tables with exactly the metadata columns the matcher compares and
a `parsed_payload` JSONB column, and `lemely/db/question_bank_repo.py` already has
a get-or-create helper for `papers` rows (`_resolve_paper`). Nothing in production
writes a `mark_schemes` row today.

### 1.3 The pin protects more than the two documented stores

`docs/deployment.md` §5.1 names two pieces of process-local state: the
`JobRegistry` (`lemely/web/jobs.py`) and the parent phone-OTP challenge store
(`lemely/auth/otp.py`). The code has more:

| State | Where | What breaks with N instances |
| --- | --- | --- |
| Teacher paper store | `routers/teacher.py::_PaperStore` | A paper is visible only on the instance that received it; lost on restart. |
| Grading pool + lock | `routers/teacher.py::_grading_pool`, `_jobs_lock` | A regrade on another instance starts a second run of the same paper. |
| Job registry | `lemely/web/jobs.py` | Nothing reads it — zero route callers. Dead weight, not a hazard. |
| OTP challenge store | `lemely/auth/otp.py::OtpStore` | Issued on one instance, verified on another: intermittent parent-login failure. |
| Cooldown store | `lemely/auth/cooldown.py::CooldownStore` | The only abuse defence on the public auth routes weakens by a factor of N. |
| Event bus | `lemely/runtime/events.py::bus` | Not an instance problem — a *same-instance* problem: no per-run scoping, so two concurrent SSE streams receive each other's frames and the first `publish_done()` ends both. The teacher pool is pinned to one worker because of it. |
| Spend ledger | `output_dir/gemini_spend.json` via `CostLedger` | The $8 cap already resets on every cold start; with N instances it becomes N caps. |
| Gemini response cache | `cache_dir/gemini` | A cache. Lower hit rate, no correctness issue. |
| Scheme corpus | `output_dir/schemes` | §1.2. |

### 1.4 Nothing deletes an upload, and the signed-URL method has no callers

No code path deletes an object from storage, and `StorageBackend.create_signed_url`
is implemented twice and called nowhere.

---

## 2. Goal

After this work:

- Every uploaded byte the web app keeps lives in a Google Cloud Storage bucket
  owned by the same GCP project Cloud Run deploys into. Supabase is used for
  GoTrue and Postgres only.
- No request-serving code path depends on process memory or the container
  filesystem surviving beyond the request, except the Gemini response cache,
  which is a cache.
- The Cloud Run service runs with `--max-instances=3 --min-instances=0`, and the
  deploy workflow's comment about the pin says it is a cost knob.
- The teacher console, the student self-mark flow, parent login and email
  verification behave identically whichever instance answers a request.

---

## 3. Decisions

Recorded from the interview that set this scope. Each row is a choice that was
put to the owner with alternatives and answered; the reasoning column is why the
chosen option won.

| # | Decision | Reasoning |
| --- | --- | --- |
| DS1 | **Driver is both consolidation on GCP and launch readiness.** | Neither alone would justify touching the auth stores; together they do. |
| DS2 | **Teacher scans go to GCS *and* the teacher paper becomes a Postgres row.** | Bytes-only would leave a console that still forgets every paper on restart (§1.1). |
| DS3 | **The web app's $8 cap and its file ledger are retired.** Production spend is guarded by a Google Cloud billing budget on the shared project. The CLI keeps its file ledger. The admin overview drops its spend panel. | The Gemini key bills to the same project as Cloud Run, so one budget covers everything. A per-instance file cap is not a cap. |
| DS4 | **OTP challenges and cooldowns move to Postgres.** | The cooldown store is the only abuse defence on public auth routes; parent OTP is a login path. Both must hold across instances. |
| DS5 | **The scheme corpus lands in the existing `papers`/`mark_schemes` tables; the PDF goes to the bucket.** | The tables already exist with the right columns; a directory scan becomes a query; the PDF is kept so a scheme can be re-parsed after a parser fix. |
| DS6 | **`max-instances=3`, `min-instances=0`.** | Enough to prove instance-agnosticism and absorb a spike; a runaway cannot fan out to 100 containers; still free-tier shaped. |
| DS7 | **Local dev and compose use a filesystem backend; the Supabase Storage client is deleted.** | Consolidation means one real backend. Tests keep the in-memory fake. |
| DS8 | **Nothing is migrated.** Buckets start empty. | No real uploads exist in either Supabase project. |
| DS9 | **Scans expire after 90 days by bucket lifecycle rule.** | Reports live in Postgres and survive; only bytes expire. Free-tier headroom is ~200 scans at the 25 MB cap. |
| DS10 | **Per-run event scoping is in scope.** | The bus cross-talk (§1.3) is what keeps the grading pool at one worker and truncates concurrent student streams. Unpinning without it spreads the bug. |
| DS11 | **Teacher papers are visible to the uploading teacher, admins of their school(s), and platform admins.** | Durable rows must not become permanent cross-school visibility. Matches the tenancy posture `routers/school.py` already uses. |
| DS12 | **The official `google-cloud-storage` SDK, not a hand-written client.** | Chosen over the thin-httpx precedent for library-managed retries and checksums; the client is built lazily to keep cold start honest. |
| DS13 | **Grading stays on a per-instance single-worker pool; run state lives on the paper row.** Cloud Tasks was declined. | Any instance answers the polled routes from the row. A queue, its IAM, a second request path and local emulation are not worth it at three instances. |
| DS14 | **The two teacher SSE routes (`/papers/{id}/extract`, `/papers/{id}/grade`) are deleted.** | Neither has a screen caller since the console moved to polling (D6.13). Keeping them correct across instances means a second stream implementation for endpoints nothing uses. |
| DS15 | **Email verification offers both a typed 6-digit code and the existing link.** | Added mid-design by the owner. The code lives in the same channel-aware OTP table as the parent phone code. |

### 3.1 Explicitly not in scope

- Real SMS and email delivery (issues #197, #198, #199). The provider seams are
  extended (DS15) but production still wires the mock providers.
- Durable job dispatch that survives instance death (Cloud Tasks, Pub/Sub). A
  run still dies with its instance; the row reports it (§4.2).
- Cloud Run session affinity.
- Per-IP rate limiting (unchanged from D7.12).
- Raising the grading pool above one worker per instance.
- The CLI and Gradio surfaces, which keep `HistoryStore`, the file ledger and
  local disk deliberately (D1.9/D6.11).
- Deleting the now-unused Supabase Storage buckets (a manual dashboard step,
  noted as optional in `docs/ci-cd.md`).
- The pre-existing 32 MB Cloud Run request limit versus a multipart body carrying
  a 25 MB scan plus a 25 MB scheme (§7).

---

## 4. Architecture

Seven units, in build order. Each has one purpose, one interface, and its own
tests.

### 4.1 Object storage seam

`lemely/io/storage.py`:

```python
class StorageBackend(Protocol):
    def upload(self, bucket: str, object_path: str, data: bytes, content_type: str | None) -> None: ...
    def download(self, bucket: str, object_path: str) -> bytes: ...
    def delete(self, bucket: str, object_path: str) -> None: ...
```

`create_signed_url` is removed (zero callers). `StorageObjectNotFoundError` and
the `ExternalServiceError` mapping are kept as the two failure types every
caller distinguishes.

**`GcsStorageBackend`** wraps one `google.cloud.storage.Client`, built lazily on
first use from application-default credentials (the Cloud Run runtime service
account in production, `gcloud auth application-default login` on a laptop that
opts in). The client is injectable for tests, the way `GeminiClient` takes
`_genai_client`.

- `upload` calls `blob.upload_from_string(data, content_type=..., if_generation_match=0, retry=DEFAULT_RETRY_IF_GENERATION_SPECIFIED, timeout=30)`.
  The zero-generation precondition makes the write create-only, which both
  refuses to overwrite an existing key and switches on the SDK's conditional
  retry policy. Every key this codebase writes carries a server-generated UUID,
  so a `PreconditionFailed` is a bug and surfaces as `ExternalServiceError`.
- `download` calls `blob.download_as_bytes(timeout=30)`; `NotFound` maps to
  `StorageObjectNotFoundError`; any other `GoogleAPICallError` or transport
  error maps to `ExternalServiceError`.
- `delete` ignores `NotFound` (idempotent).
- A `DefaultCredentialsError` is raised at first use, wrapped in
  `ExternalServiceError` with a message naming the missing credential, never at
  import or construction, so a misconfigured deploy fails on its first upload
  with a readable error rather than at startup with a traceback.

**`LocalFileStorageBackend`** writes to
`settings.paths.output_dir / "storage" / bucket / object_path`, creating parents,
with a resolve-inside-root check so no key can escape the root. Missing file →
`StorageObjectNotFoundError`. This is the dev and compose backend.

**Settings.** `StorageSettings` gains `backend: Literal["local", "gcs"] = "local"`
and keeps `bucket: str = "uploads"`. For `gcs` the bucket is the real bucket
name (`LEMELY_STORAGE__BUCKET`); for `local` it is a directory name. The
`get_storage_backend` dependency in `lemely/web/deps.py` selects on
`settings.storage.backend`.

**Object keys:**

```
uploads/{user_id}/{paper_id}/{safe_name}        student scan (unchanged)
uploads/{user_id}/{paper_id}/mark_scheme.pdf    student sibling scheme (unchanged)
teacher/{uploaded_by}/{paper_id}/{safe_name}    teacher scan
teacher/{uploaded_by}/{paper_id}/mark_scheme.pdf
schemes/{mark_scheme_id}/{safe_name}            corpus PDF
```

`safe_name` is `lemely/web/upload_utils.py::safe_upload_name`. The size cap is
`check_upload_cap` on the bytes before upload, as the student route already
does; `write_upload_capped` and the teacher router's private wrapper are
deleted with the last disk write.

**Consumers never see a filesystem path for a stored object.** Anything that
needs a local file (`ScanMetadataExtractor`, `extract_answers`, the
deterministic parser, PyMuPDF for the preview) downloads into a
`tempfile.TemporaryDirectory` for the duration of the call, exactly as the
student correction run does today. The preview route renders from bytes via
`pymupdf.open(stream=..., filetype=...)`.

**Removed:** `HttpStorageBackend`, `tests/test_storage_live.py` in its Supabase
form (rewritten, §5), the `[storage.buckets.uploads]` block in
`supabase/config.toml`, and every mention of Supabase Storage in the docs
listed in §4.7.

**Health.** `GET /api/health` gains `storage: {"backend": ..., "bucket": ...}`,
read from settings without a network call, so the deploy smoke test can assert
the right backend is live.

**Doctor.** `lemely doctor` gains a `storage_backend` check: for `local`, the
root is writable; for `gcs`, default credentials resolve and — unless
`--no-network` — the bucket is reachable.

### 4.2 Teacher papers

**Migration `0024_teacher_papers`** — one additive table:

| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid PK | The `paperId` the console already treats as opaque. |
| `uploaded_by` | uuid FK `users.id` ON DELETE CASCADE, not null | Visibility anchor (DS11). |
| `student_id` | uuid FK `users.id` ON DELETE SET NULL, nullable | Always null today (D1.12); kept so the column exists when class ownership lands. |
| `storage_path` | text, not null | Scan object key. |
| `scheme_storage_path` | text, nullable | Sibling scheme key when one was uploaded; avoids a probing download. |
| `original_filename`, `content_type` | text, nullable | As on `uploads`. |
| `byte_size` | integer, nullable | As on `uploads`. |
| `status` | `uploadstatus` enum (existing type, `create_type=False`), not null, default `pending` | `pending` renders as "Queued". |
| `stage` | text, nullable | One of `detect`/`scheme`/`extract`/`mark` while processing. |
| `progress_index`, `progress_total` | integer, nullable | Per-stage counter. |
| `metadata_json` | JSONB, nullable | Detected `ExamMetadata`. |
| `mark_scheme_json` | JSONB, nullable | Resolved `MarkScheme`, cached for regrades. |
| `report_json` | JSONB, nullable | `AccuracyReport`. |
| `error` | text, nullable | Terminal failure reason. |
| `run_started_at` | timestamptz, nullable | Set on claim. |
| `created_at`, `updated_at` | `TimestampMixin` | `updated_at` is the liveness signal. |

Indexes: `(uploaded_by, created_at)`.

`graded` versus `review` is derived at read time from `report_json`
(`needs_teacher_review`), exactly as `_entry_kind` derives it today — one source
of truth, no status value that can disagree with the report.

**`TeacherPaperRepository`** (`lemely/db/teacher_paper_repo.py`) is the only
writer. Its methods: `create`, `get_visible(paper_id, caller)`, `list_visible(caller)`,
`claim_run(paper_id, stale_after)`, `set_stage`, `set_progress`, `set_metadata`,
`set_mark_scheme`, `finish(report)`, `fail(error)`.

**Claiming a run** is one conditional `UPDATE`:

```sql
UPDATE teacher_papers
   SET status = 'processing', run_started_at = now(), stage = 'detect',
       progress_index = NULL, progress_total = NULL, error = NULL
 WHERE id = :id
   AND (status IN ('pending', 'failed', 'complete')
        OR (status = 'processing' AND updated_at < now() - :stale_after))
RETURNING id
```

One row returned: this instance owns the run and submits it to its own
single-worker pool. Zero rows: another instance is already running it; the
caller returns `202 {"status": "processing"}` and the console keeps polling.
This replaces `_jobs_lock`, the `Future` on the entry, and the job registry.
`stale_after` is a new `GradingSettings.stale_run_after_seconds`, default 900 —
a new settings group on `Settings` (`[grading]` in `lemely.toml`,
`LEMELY_GRADING__*` in the environment, `extra="forbid"` like every other group).

**The grading job** (`_run_grading_job`, kept as a function on the pool) reads
the row, downloads the scan (and sibling scheme if `scheme_storage_path` is set)
into a temporary directory, and writes every state change it makes today to the
row instead of to the entry: `set_stage` at each phase, `set_progress` from the
tracker on every progress event, `set_metadata`, `set_mark_scheme`, then
`finish` or `fail`. Because `updated_at` moves on every one of those writes, a
`processing` row that has not moved for fifteen minutes is a dead run, and the
list and detail routes report it as `failed` with a "run was lost, retry"
error, which re-enables the regrade button.

**Routes** (all under the existing staff guard):

| Route | Change |
| --- | --- |
| `POST /papers/upload` | Generates the paper id, uploads scan (+ scheme), inserts the row, claims, submits. `UploadResponseDTO.jobId` is set to the paper id for wire compatibility; `detected` stays empty (D6.13). |
| `GET /papers` | `list_visible(caller)`, newest first; `_batch_tabs` over the visible set. |
| `GET /papers/{id}` | `get_visible`; 404 for unknown *or* not-visible (never reveal existence). |
| `GET /papers/{id}/preview` | Downloads bytes, renders page 1 from a stream; 404 when the object has expired (DS9). |
| `POST /papers/{id}/regrade` | `claim_run` then submit, or 202 "processing". |
| `POST /papers/{id}/extract`, `POST /papers/{id}/grade` | **Deleted** (DS14), with `extractPaper` and `gradePaper` in `web/src/lib/hooks/useTeacherApi.ts`. |

**Visibility** (DS11), one query:

- `uploaded_by = caller`, or
- caller holds a `school_admin` membership in a school where `uploaded_by` holds
  a `teacher` membership (`school_memberships`, both roles from `MembershipRole`), or
- caller's platform role is `platform_admin`.

**Deleted:** `_PaperStore`, `_PaperEntry`, `papers_store`, `_jobs_lock`,
`lemely/web/jobs.py` and the `registry` import. The `_grading_pool` stays at
`max_workers=1` (DS13); its reason changes from "the bus cannot scope" to "Queued
should mean queued".

### 4.3 Scheme corpus

No migration. The teacher's `POST /schemes` becomes the first production writer
of `mark_schemes`:

1. Parse the PDF deterministically from a temporary file (unchanged; 422 on
   failure, nothing stored).
2. `_resolve_paper` (existing, `lemely/db/question_bank_repo.py`) gets or creates
   the `subjects` and `papers` rows from the parsed metadata.
3. Insert or replace the `mark_schemes` row for that paper (`paper_id` is
   unique): `parsed_payload` = the `MarkScheme` JSON, `maximum_mark` from the
   payload, `provenance = "teacher_upload:deterministic"`.
4. Upload the PDF to `schemes/{mark_scheme_id}/{safe_name}` and set
   `source_document` to that object key.

`GET /schemes` lists `mark_schemes` joined to `papers`, newest first. The
"Failed" stat card — which counted unreadable JSON files on disk — goes; only
"Parsed" remains, because there is no longer a failure state that persists.

**Matching** replaces the directory scan in `resolve_mark_scheme`: a query on
`papers` by `subject_code`, `paper_number`, `paper_variant`, and `session_year`
when the scan detected one, joined to `mark_schemes`, newest first, first row
wins. The resolver's signature changes from a scan path to an optional sibling
scheme path plus the corpus repository:

```python
def resolve_mark_scheme(
    sibling_scheme: Path | None,
    corpus: SchemeCorpusRepository,
    settings: Settings,
    gemini_client: GeminiClient,
    *,
    metadata: ExamMetadata | None,
) -> MarkScheme | None
```

Both portals call it the same way; the sibling still wins over the corpus. The
corpus stays globally visible — these are public exam documents, not tenant
data.

### 4.4 Auth stores, and email verification by code

**Migration `0025_otp_challenges`:**

| Column | Type | Notes |
| --- | --- | --- |
| `channel` | `otpchannel` enum (`phone`, `email`), PK part | New type. |
| `address_hash` | text, PK part | SHA-256 of the normalised phone or email. |
| `code_hash` | text, not null | SHA-256 of the code. |
| `expires_at`, `issued_at` | timestamptz, not null | |
| `attempts` | integer, not null, default 0 | |

**Migration `0026_auth_cooldowns`:**

| Column | Type | Notes |
| --- | --- | --- |
| `purpose` | text, PK part | `signup_and_reset` or `resend_verification` — the two stores `deps.py` builds today. |
| `key_hash` | text, PK part | SHA-256 of the key. |
| `stamped_at` | timestamptz, not null | |

Both follow the `auth_tokens` rule (D7.7): a row never holds a redeemable
credential or a raw contact.

**Protocols.** `OtpChallengeStore` with `issue(address, *, channel=OtpChannel.phone) -> str`
and `verify(address, code, *, channel=OtpChannel.phone) -> OtpResult`, and
`CooldownStoreProtocol` with `check_and_stamp(key)`. The channel keyword
defaults to `phone`, so `request_otp`/`verify_otp`, `lemely/db/seed.py` and the
nine test files that construct `OtpStore` do not change. The existing in-memory
`OtpStore` and `CooldownStore` keep their names and become the test and seed
implementations. Both gain the channel and a per-channel TTL:
`AuthSettings.email_otp_ttl_seconds`, default 600; length, attempt cap and
resend cooldown are shared with the phone code.

**`DbOtpStore`** runs `issue` and `verify` each in one transaction with the row
locked (`SELECT ... FOR UPDATE`), so the resend cooldown, the attempt counter,
lockout and single-use consumption hold across instances exactly as they hold
across threads today. `issue` also deletes expired rows opportunistically, since
there is no scheduler (`docs/deployment.md` §5.2).

**`DbCooldownStore.check_and_stamp`** is one statement:

```sql
INSERT INTO auth_cooldowns (purpose, key_hash, stamped_at) VALUES (:p, :k, now())
ON CONFLICT (purpose, key_hash) DO UPDATE SET stamped_at = EXCLUDED.stamped_at
  WHERE auth_cooldowns.stamped_at < now() - :min_seconds
RETURNING stamped_at
```

Zero rows returned → `CooldownError` with `retry_after` computed from a
follow-up read. Atomic across instances, no lock.

`get_auth_service`, `get_signup_and_reset_cooldown_store` and
`get_resend_verification_cooldown_store` in `deps.py` build the Postgres
implementations.

**Email verification offers both a code and a link (DS15).**

- `AuthService.signup` and `resend_verification` keep minting the link token via
  `AuthTokenService` and additionally issue an email-channel code for the same
  address. `EmailProvider.send_verification(email, link, code)` gains the third
  argument; `MockEmailProvider` logs both.
- `TokenResponseDTO` and `ResendVerificationResponseDTO` gain `devCode: str | None`,
  returned under the same D3.16 rule as `devLink`: only when no provider
  delivers out of band.
- New route `POST /auth/verify-email/code`, body `{"code": "..."}`, authenticated
  (any signed-in role, the `AUTH_ANY` class in the authorization matrix). The
  address comes from the caller's session via the user mirror, never from the
  body, so the route cannot probe or verify another address. Wrong, expired or
  locked-out codes map to **400** with the same non-revealing detail the link
  route uses. Success calls the same `mark_email_verified`.
- `AuthService.verify_email_code(user_id, code)` is the service method.
- The link and the code are independent credentials: whichever is used first
  verifies the account; the other expires on its own TTL. Verification is
  idempotent, so this is harmless.
- G-07 (`web/src/portals/auth/VerifyEmail.tsx`, signed-in variant) gains a
  six-digit code field and a verify button beside the resend control; the dev
  panel shows the code next to the link. `AuthContext` gains a `verifyEmailCode`
  mutation; `authTypes.ts` gains `devCode`. The signed-out variant, reached only
  by opening a link, is unchanged.

### 4.5 Per-run event scoping

`lemely/runtime/events.py`:

- `current_run_id: ContextVar[str | None]`, default `None`.
- `Event` gains `run_id: str | None`. `publish` stamps it from the context
  variable.
- `subscribe_queue(run_id: str | None = None)`. A scoped queue receives events
  whose `run_id` equals its own **plus** events with `run_id is None` (published
  outside any run — `BUDGET_*` from the CLI path, for instance). An unscoped
  queue receives everything, which is what `lemely/app/live_log.py` (Gradio) and
  the existing tests expect.
- `publish_done()` delivers the sentinel to queues scoped to the current run and
  to unscoped queues. Never to another run's queue.
- `subscribe(EventType, callback)` (synchronous callbacks) is unchanged and
  unscoped.

`lemely/web/sse.py::bus_event_stream` gains an optional `run_id` keyword — the
student route passes its paper id for readability; otherwise a fresh one is
minted per stream — subscribes scoped, and sets the context variable at the
top of the worker thread before calling `run`. The SSE frame payload does
**not** include `run_id`; the wire contract is unchanged.

`_run_grading_job` sets the variable to the paper id at the top of its pool
thread; its progress tracker subscribes scoped to it, so two papers on two
instances — or, later, two workers — cannot mix counters.

**Rule, pinned by a test:** any code that spawns a thread inside a run runs it
under `contextvars.copy_context()`. Threads do not inherit context variables by
default.

### 4.6 Spend cap retirement in the web app (DS3)

- `GeminiClient.__init__` gains a `ledger` keyword. Omitted means today's file
  ledger at `output_dir/gemini_spend.json` (CLI, Gradio, eval and scripts are
  untouched). `ledger=None` means: no ceiling check in `_check_cost_ceiling`, no
  `ledger.add`, no `BUDGET_WARNING`/`BUDGET_EXCEEDED` events. The per-call
  `gemini_call` log line with `usd_cost` stays — spend is still observable in
  Cloud Logging.
- `get_gemini_client` in `deps.py` passes `ledger=None`. `lemely/web/app.py` stops
  calling `register_budget_ntfy`.
- `PlatformOverviewDTO.spend` and `SpendDTO` are removed from
  `routers/admin.py`; `Spend` in `web/src/lib/adminTypes.ts` and the spend panel
  in `web/src/portals/admin/screens/PlatformConsole.tsx` go with them.
- `docs/deployment.md` §5.4, `docs/ci-cd.md` known gaps and `DELIVERY.md` §5.6
  say plainly: the web process enforces no USD cap; the billing budget is the
  guard, and it is an alert, not a stop.

### 4.7 Infrastructure, deploy and docs

**`scripts/gcp-bootstrap.sh`** (idempotent, re-runnable) gains, for each of
`staging` and `production`:

- Bucket `${PROJECT_ID}-uploads-${ENV}`, `us-central1`, uniform bucket-level
  access, public-access prevention enforced, lifecycle from
  `scripts/gcs-lifecycle.json` (delete, age 90 days).
- Runtime service account `lemely-backend-${ENV}` with
  `roles/storage.objectAdmin` bound **on that bucket only**. The deployer
  account's project-level `roles/iam.serviceAccountUser` already lets it deploy
  a revision as that identity. Container logs and metrics need no grant — Cloud
  Run collects them platform-side.
- `storage.googleapis.com` and `billingbudgets.googleapis.com` enabled.

And once per project: a billing budget with alert thresholds at 50/90/100 %,
created only when `BILLING_ACCOUNT_ID` and `BUDGET_USD` are set; otherwise the
script prints exactly what it skipped and that this budget is now the only
spend guard.

**`.github/workflows/deploy.yml`:** the Cloud Run step adds
`--service-account=lemely-backend-${ENV}@${PROJECT_ID}.iam.gserviceaccount.com`
and the env vars `LEMELY_STORAGE__BACKEND=gcs` and
`LEMELY_STORAGE__BUCKET=${GCP_PROJECT_ID}-uploads-${ENV}`; in the final rollout
step (§6) `--max-instances=1` becomes `--max-instances=3`. The comment block
that explains the pin is rewritten: max-instances is a cost knob; the only
per-instance state left is the Gemini response cache. `SUPABASE_SERVICE_ROLE_KEY`
stays — GoTrue admin calls still need it. The three migrations run through the
existing gated migrate job. The smoke test asserts `/api/health` reports
`gcs` and the expected bucket.

**Packaging:** `google-cloud-storage` joins the `web` extra in `pyproject.toml`
(CI and the Dockerfile both install `[web]`); the lockfile is regenerated with
the repo's tooling, never by hand.

**Local dev:** nothing to configure. `backend` defaults to `local`; compose and
`make up` keep working; `outputs/storage/` is created on first write.

**Docs touched:** `docs/deployment.md` §2 (new variables; the ceiling row
becomes "CLI only"), §5.1 (rewritten: the constraint is lifted, and what remains
per instance), §5.4, §6 checklist; `docs/ci-cd.md` one-time setup (bootstrap
outputs, `BILLING_ACCOUNT_ID`/`BUDGET_USD`), Supabase section (bucket unused;
optional deletion), credentials checklist, known gaps; `DELIVERY.md` §5.6; a new
D-series entry in `BUILD/DECISIONS.md` recording DS1–DS15 above.

**Rollback:** Cloud Run keeps prior revisions; rollback is a traffic switch.
Migrations are additive, so no downgrade is needed. Objects written during a
rolled-back window remain and resolve when the revision returns.

---

## 5. Testing

Hermetic by default; Postgres-backed where a unit touches the database, on the
throwaway database `tests/conftest.py` already provides (CI runs it against its
Postgres service; locally it skips cleanly when no server is reachable).

- **Storage seam.** `LocalFileStorageBackend`: round trip, missing object,
  traversal guard, idempotent delete. `GcsStorageBackend` with a stubbed client:
  create-only precondition and retry policy passed; `NotFound` →
  `StorageObjectNotFoundError`; `PreconditionFailed` → `ExternalServiceError`;
  credential failure deferred to first use. `tests/test_storage_live.py` is
  rewritten for GCS: skips unless `LEMELY_STORAGE__BACKEND=gcs` and default
  credentials resolve; writes a unique key, reads it back, deletes it.
  `tests/storage_fakes.py::FakeStorageBackend` gains `delete`.
- **Teacher papers.** Repository: two threads claiming one paper → exactly one
  wins (the `tests/test_concurrency.py` pattern); a stale `processing` row is
  reclaimable; the DS11 visibility matrix for teacher, school admin (own school,
  other school), platform admin. Router: `tests/test_web_teacher.py` (76 tests)
  rewired from `papers_store`/`registry` to the repository and the fake; the
  traversal test asserts the object key; new tests for 404-on-not-visible and
  for the lost-run rendering.
- **Scheme corpus.** Replace-per-paper; matcher precedence (session-specific
  first, newest wins); both portals resolving sibling versus corpus; the
  `/schemes` list and stats.
- **Auth stores.** The in-memory and Postgres implementations run the same
  parametrised cases through the Protocol (the `test_history_repo_parity.py`
  pattern) so they cannot drift; two simultaneous verifies → one `ok`; expired
  rows swept on issue. Email code: service tests for signup/resend issuing both
  credentials, `verify_email_code` outcomes, independence of link and code;
  route tests; `tests/test_authz_matrix_complete.py` gains the new route under
  `AUTH_ANY` and loses the two deleted teacher routes.
- **Bus scoping.** Two scoped subscribers see no cross-talk; the sentinel ends
  only its own run; an unscoped subscriber sees everything; unscoped events
  reach scoped queues; the context-copy rule for nested threads; two concurrent
  `bus_event_stream`s in `tests/test_web_app.py`.
- **Cap retirement.** A client with `ledger=None` makes no ceiling check and
  publishes no budget event; the default still does both; the admin overview
  DTO test drops `spend`.
- **Frontend.** Vitest for the G-07 logic additions and the removed admin
  type; `web/e2e/signup.spec.ts` extended to verify by code using `devCode`.
- **Deploy.** The smoke test's health assertion (§4.7).

Gates unchanged: `pre-commit run --all-files`, the full pytest suite with
Postgres, strict mypy, ruff, the generated authorization matrix.

---

## 6. Rollout order

Six steps. Each is merged to `develop`, deployed to staging by the existing
pipeline, verified there, then promoted. The unpin goes last because it is the
step that makes every earlier gap visible.

1. **Bootstrap** — run `scripts/gcp-bootstrap.sh` against the project so buckets
   and runtime identities exist before any deploy references them.
2. **Storage seam** (§4.1) — student path on GCS; `--service-account` and the
   storage env vars added to the deploy; Supabase Storage client removed.
3. **Teacher papers and scheme corpus** (§4.2, §4.3) — migration `0024`.
4. **Auth stores and email code** (§4.4) — migrations `0025`, `0026`.
5. **Bus scoping** (§4.5).
6. **Cap retirement** (§4.6), then the one-line `--max-instances=3` change with
   its rewritten comment.

---

## 7. Risks

- **Stale-run reclaim marks a paper twice.** A run that writes nothing for
  fifteen minutes is reclaimed. Progress is written at every stage and every
  question, and the Gemini client bounds its retries, so a silent fifteen
  minutes is a dead run in practice. The threshold is a setting
  (`GradingSettings.stale_run_after_seconds`).
- **Queued is per instance.** With one worker per instance and three instances,
  at most three teacher runs proceed at once, and a paper can queue on one
  instance while another is idle. Accepted at this scale (DS13); documented in
  `docs/deployment.md` §5.1.
- **A budget alert is not a cap.** Spend can pass it before anyone acts. That is
  the accepted trade of DS3 and the docs say so.
- **SDK weight on cold start.** `google-cloud-storage` adds import time. The
  client is built lazily on first use; the health route never touches it.
- **Scan expiry versus report.** After 90 days the preview 404s while the
  report lives on. The console already renders a card without a thumbnail for
  a scan it cannot fetch.
- **Pre-existing, unchanged:** one multipart request carrying a 25 MB scan plus a
  25 MB scheme exceeds Cloud Run's 32 MB HTTP/1 request limit. Not introduced
  here; recorded so nobody attributes it to this work.

---

## 8. Acceptance

The work is done when all of the following hold on staging, and then on
production:

1. `GET /api/health` reports `storage.backend == "gcs"` and the environment's
   bucket name; a student upload and a teacher upload each produce an object
   under the expected key, and neither writes under `output_dir`.
2. A teacher uploads a paper, the pod is restarted, and `GET /papers` still lists
   it with its status; two revisions serving traffic at once show the same list.
3. A parent OTP issued through one instance verifies through another; a resend
   inside the cooldown returns 429 from any instance.
4. Email verification succeeds by link and, separately, by typed code; the
   wrong code five times locks the challenge; the `AUTH_ANY` matrix row for the
   new route passes.
5. Two students run corrections concurrently on one instance and each stream
   carries only its own frames and ends only when its own run ends.
6. `POST /papers/{id}/regrade` fired twice within a second from two clients runs
   the paper once.
7. The admin overview has no spend fields; a Gemini call in the web process
   writes no `gemini_spend.json`; the billing budget exists on the project.
8. The Cloud Run service shows `maxScale: 3`, and the deploy workflow's comment
   no longer calls the pin load-bearing.
9. No file under `lemely/` imports `HttpStorageBackend`, `papers_store`,
   `JobRegistry`, or `create_signed_url`.
