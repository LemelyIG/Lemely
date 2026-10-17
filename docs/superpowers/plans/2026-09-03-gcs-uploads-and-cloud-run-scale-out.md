# Uploads on Google Cloud Storage, and a Cloud Run backend that scales — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Spec:** `docs/superpowers/specs/2026-09-03-gcs-uploads-and-cloud-run-scale-out-design.md` — **read it before Task 1.** Its fifteen interview decisions (DS1–DS15) are binding on this plan, its §1.3 table is the inventory of state this plan exists to move, and its §6 rollout order is the order the stages below are merged and deployed.

**Goal:** Every uploaded byte the web app keeps lives in a Google Cloud Storage bucket; no request-serving path depends on process memory or the container filesystem outliving the request; email verification works by code as well as link; and the Cloud Run service runs at `--max-instances=3`.

**Architecture:** One `StorageBackend` seam with a GCS implementation (official SDK) and a local-filesystem implementation for dev. Three additive migrations (`0024`–`0026`) give the teacher paper, the OTP challenge and the auth cooldown a Postgres row each; the parsed scheme corpus lands in the existing `papers`/`mark_schemes` tables. The event bus gains a per-run channel carried in a context variable. The web process stops enforcing the USD cap. The bootstrap script provisions buckets, runtime identities and a billing budget; the deploy workflow passes them and, last of all, raises the instance cap.

**Tech Stack:** FastAPI + SQLAlchemy 2 + Alembic + `google-cloud-storage` (backend); React 19 + TypeScript + Vite (frontend); pytest against a throwaway Postgres, vitest, Playwright; `gcloud` in the bootstrap script.

## Plan fidelity — read this before judging the shape

Backend tasks (1–12, 14–17) carry real code, real test bodies and real assertions. That is where the irreversible decisions live: schema, the claim query, the hashing rules, the scoping semantics. The frontend task (13), the admin-panel removal half of Task 17, and the infrastructure and docs tasks (18–21) are written as **precise specifications** — exact files, exact interfaces, exact test names, exact acceptance — but not line-by-line JSX, YAML or prose. The screens must be built against `DESIGN.md` and the existing component kit by someone reading both; the workflow and script edits are small and the exact flags are given.

## Global Constraints

- **Signed commits: `git commit -S`.** Conventional messages with scopes (`feat(storage):`, `feat(db):`, `feat(teacher):`, `feat(auth):`, `feat(events):`, `refactor(gemini):`, `feat(ci):`, `docs(deploy):`).
- **Run `pre-commit run --all-files` and fix every failure before each commit.** Not once at the end. The `import-linter` hook enforces the layer order `app → io → core` under `lemely/`; `lemely.db` and `lemely.web` are outside that contract but `lemely.runtime` may import none of `core`, `io`, `app`.
- **Additive-only schema.** No column dropped, none made NOT NULL, no enum loses a member. Enum `server_default`s render with an explicit `::type` cast. Alembic revision ids ≤ 32 characters (`alembic_version.version_num` is `varchar(32)`); the three here are 19 each.
- **Postgres-dependent tests skip cleanly** via the per-file `pg_sessionmaker` fixture pattern (`pytest.skip("local Postgres not reachable")`). Copy the fixture body from `tests/test_auth_token_repo.py` verbatim into any new test module that needs it; never invent a new shape.
- **Consumers never see a filesystem path for a stored object** (spec §4.1). Anything that needs a file downloads into a `tempfile.TemporaryDirectory` for the duration of the call.
- **A row never holds a redeemable credential or a raw contact** (spec §4.4, D7.7): OTP codes, addresses and cooldown keys are stored as SHA-256 hex digests only.
- **Never claim a mail or SMS was delivered.** `delivers_out_of_band` on the provider is the only thing that decides whether `devLink`/`devCode` is returned (D3.16).
- **Object keys are exactly the five shapes in spec §4.1.** Server-generated UUIDs only; client filenames pass through `safe_upload_name`.
- **The SSE wire contract is unchanged.** Frames never carry `run_id`.
- **Logical CSS properties only** in any new styles.
- **`lemely.toml.example` is generated** by `lemely/runtime/example_toml.py`; edit the generator, not the file.

---

## File structure

New files, each with one responsibility:

| File | Responsibility |
| --- | --- |
| `lemely/io/storage_local.py` | `LocalFileStorageBackend` — dev/compose backend under `output_dir/storage/`. |
| `lemely/io/storage_gcs.py` | `GcsStorageBackend` — the official SDK, lazily built, injectable client. |
| `lemely/db/models/teacher_papers.py` | `TeacherPaper` ORM model. |
| `lemely/db/teacher_paper_repo.py` | `TeacherPaperRepository`, `TeacherPaperRow`. Only writer of `teacher_papers`. |
| `lemely/db/scheme_corpus_repo.py` | `SchemeCorpusRepository`, `SchemeCorpusRow`. First production writer of `mark_schemes`. |
| `lemely/db/models/otp_challenges.py` | `OtpChallenge` ORM model. |
| `lemely/db/models/auth_cooldowns.py` | `AuthCooldown` ORM model. |
| `lemely/db/otp_repo.py` | `DbOtpStore`. |
| `lemely/db/cooldown_repo.py` | `DbCooldownStore`. |
| `lemely/db/migrations/versions/0024_teacher_papers.py`, `0025_otp_challenges.py`, `0026_auth_cooldowns.py` | One table each. |
| `scripts/gcs-lifecycle.json` | The 90-day delete rule the bootstrap script applies. |
| `tests/test_storage_local.py`, `tests/test_storage_gcs.py`, `tests/test_teacher_paper_repo.py`, `tests/test_scheme_corpus_repo.py`, `tests/test_otp_store_parity.py`, `tests/test_cooldown_store_parity.py`, `tests/test_events_scoping.py` | One test module per new unit. |

Modified, with the responsibility that changes: `lemely/io/storage.py` (Protocol only), `lemely/runtime/config.py` (three settings), `lemely/web/deps.py` (backend selection, Postgres auth stores, ledgerless Gemini), `lemely/web/routers/teacher.py` (repository-backed; loses its stores), `lemely/web/routers/student.py` (resolver signature), `lemely/auth/otp.py`, `lemely/auth/cooldown.py`, `lemely/auth/service.py`, `lemely/auth/email.py`, `lemely/web/routers/auth.py`, `lemely/web/schemas_auth.py`, `lemely/runtime/events.py`, `lemely/web/sse.py`, `lemely/io/gemini.py`, `lemely/web/app.py`, `lemely/web/routers/admin.py`, `lemely/web/schemas_admin.py`, `lemely/web/routers/meta.py`, `lemely/web/schemas.py`, `lemely/app/cli.py`, `scripts/gcp-bootstrap.sh`, `.github/workflows/deploy.yml`, `supabase/config.toml`, `pyproject.toml`, `uv.lock`.

Deleted: `lemely/web/jobs.py`, `tests/test_storage.py` (Supabase-specific), the `HttpStorageBackend` class, the two teacher SSE routes.

---

## Stage A — the storage seam (spec §4.1; rollout step 2)

## Task 1: Protocol change and the local filesystem backend

The seam gains `delete`, loses `create_signed_url`, and gets the backend dev and compose will run on. Nothing production-facing changes yet: `get_storage_backend` still returns the Supabase client until Task 3.

**Files:**
- Modify: `lemely/io/storage.py` (Protocol: add `delete`, remove `create_signed_url`; leave `HttpStorageBackend` in place until Task 2 removes it — but delete its `create_signed_url` method now so the class still satisfies the Protocol)
- Create: `lemely/io/storage_local.py`
- Modify: `lemely/runtime/config.py:416-427` (`StorageSettings`)
- Modify: `tests/storage_fakes.py` (add `delete`, drop `create_signed_url`)
- Test: `tests/test_storage_local.py`

**Interfaces:**
- Produces `StorageBackend` with exactly: `upload(bucket, object_path, data, content_type) -> None`, `download(bucket, object_path) -> bytes`, `delete(bucket, object_path) -> None`. Consumed by every later task.
- Produces `LocalFileStorageBackend(root: Path)`. Consumed by Task 3.
- Produces `StorageSettings.backend: Literal["local", "gcs"]` (default `"local"`) and keeps `StorageSettings.bucket: str` (default `"uploads"`). `signed_url_ttl_seconds` is removed. Consumed by Tasks 2, 3.

- [ ] **Step 1: Write the failing tests**

`tests/test_storage_local.py`:

```python
"""Hermetic tests for :class:`lemely.io.storage_local.LocalFileStorageBackend`."""

from __future__ import annotations

from pathlib import Path

import pytest

from lemely.io.storage import StorageObjectNotFoundError
from lemely.io.storage_local import LocalFileStorageBackend


def test_round_trip(tmp_path: Path) -> None:
    backend = LocalFileStorageBackend(tmp_path)
    backend.upload("uploads", "u/p/scan.pdf", b"%PDF-1.4", "application/pdf")
    assert backend.download("uploads", "u/p/scan.pdf") == b"%PDF-1.4"
    assert (tmp_path / "uploads" / "u" / "p" / "scan.pdf").read_bytes() == b"%PDF-1.4"


def test_missing_object_raises_not_found(tmp_path: Path) -> None:
    backend = LocalFileStorageBackend(tmp_path)
    with pytest.raises(StorageObjectNotFoundError):
        backend.download("uploads", "u/p/missing.pdf")


def test_delete_is_idempotent(tmp_path: Path) -> None:
    backend = LocalFileStorageBackend(tmp_path)
    backend.upload("uploads", "u/p/scan.pdf", b"x", None)
    backend.delete("uploads", "u/p/scan.pdf")
    backend.delete("uploads", "u/p/scan.pdf")  # second call must not raise
    with pytest.raises(StorageObjectNotFoundError):
        backend.download("uploads", "u/p/scan.pdf")


@pytest.mark.parametrize("bad_key", ["../escape.pdf", "u/../../escape.pdf", "/abs/escape.pdf"])
def test_key_cannot_escape_root(tmp_path: Path, bad_key: str) -> None:
    backend = LocalFileStorageBackend(tmp_path)
    with pytest.raises(ValueError, match="escapes"):
        backend.upload("uploads", bad_key, b"x", None)
    assert not (tmp_path.parent / "escape.pdf").exists()


def test_settings_default_backend_is_local() -> None:
    from lemely.runtime.config import StorageSettings

    assert StorageSettings().backend == "local"
    assert StorageSettings().bucket == "uploads"
    assert not hasattr(StorageSettings(), "signed_url_ttl_seconds")
```

- [ ] **Step 2: Run to verify they fail**

`pytest tests/test_storage_local.py -v` → FAIL with `ModuleNotFoundError: lemely.io.storage_local`.

- [ ] **Step 3: Change the Protocol**

In `lemely/io/storage.py`, replace the `create_signed_url` method on `StorageBackend` with:

```python
    def delete(self, bucket: str, object_path: str) -> None:
        """Remove ``object_path`` from ``bucket``. A missing object is not an error."""
        ...
```

Delete `HttpStorageBackend.create_signed_url` entirely (the class goes in Task 2; until then it must still satisfy the Protocol, so add a `delete` that issues `httpx.delete` against `/storage/v1/object/{bucket}/{object_path}` with the same headers and error mapping as `download`, ignoring a 404). Update the module docstring's first line to "Object storage seam." and `__all__` accordingly.

In `tests/storage_fakes.py`, replace `create_signed_url` with:

```python
    def delete(self, bucket: str, object_path: str) -> None:
        self._objects.pop((bucket, object_path), None)
```

- [ ] **Step 4: Write the local backend**

`lemely/io/storage_local.py`:

```python
"""Filesystem :class:`~lemely.io.storage.StorageBackend` for dev and compose (DS7).

Objects live under ``<root>/<bucket>/<object_path>``. This is the default
backend (``StorageSettings.backend == "local"``) so a fresh clone, ``make up``
and the hermetic test-suite need no cloud credentials. Production selects
:class:`~lemely.io.storage_gcs.GcsStorageBackend` instead.

The one rule that matters here is the same one the routers already apply to
client filenames: a key must never resolve outside the root. Keys are built
from server-generated UUIDs and ``safe_upload_name`` output, so an escape is
a bug — it raises rather than being silently rewritten.
"""

from __future__ import annotations

from pathlib import Path

from lemely.io.storage import StorageObjectNotFoundError


class LocalFileStorageBackend:
    """Dict-of-files: one file per object under ``root``."""

    def __init__(self, root: Path) -> None:
        """Bind to ``root``; created lazily on first write."""
        self._root = root.resolve()

    def _path(self, bucket: str, object_path: str) -> Path:
        candidate = (self._root / bucket / object_path).resolve()
        if not candidate.is_relative_to(self._root / bucket):
            raise ValueError(f"Object key {object_path!r} escapes the storage root.")
        return candidate

    def upload(
        self,
        bucket: str,
        object_path: str,
        data: bytes,
        content_type: str | None,
    ) -> None:
        """Write ``data`` to ``<root>/<bucket>/<object_path>``; ``content_type`` is unused."""
        target = self._path(bucket, object_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def download(self, bucket: str, object_path: str) -> bytes:
        """Return the stored bytes, or raise :class:`StorageObjectNotFoundError`."""
        target = self._path(bucket, object_path)
        try:
            return target.read_bytes()
        except FileNotFoundError as exc:
            raise StorageObjectNotFoundError(f"No object at {bucket}/{object_path}") from exc

    def delete(self, bucket: str, object_path: str) -> None:
        """Remove the file if present. Missing is not an error."""
        target = self._path(bucket, object_path)
        target.unlink(missing_ok=True)


__all__ = ["LocalFileStorageBackend"]
```

`Path.is_relative_to` exists from Python 3.9; `requires-python` is `>=3.12`.

- [ ] **Step 5: Change the settings group**

Replace `StorageSettings` in `lemely/runtime/config.py`:

```python
class StorageSettings(BaseModel):
    """Object storage for every upload the web app keeps (spec 2026-09-03, DS7/DS12).

    ``backend`` selects the implementation ``lemely.web.deps.get_storage_backend``
    builds: ``local`` (the default — files under ``paths.output_dir/storage``,
    for dev, compose and CI) or ``gcs`` (Google Cloud Storage via the official
    SDK, authenticated with application-default credentials — the Cloud Run
    runtime service account in production). ``bucket`` is the real bucket name
    for ``gcs`` and a directory name for ``local``. Overrides via ``[storage]``
    in ``lemely.toml`` or ``LEMELY_STORAGE__*`` env vars.
    """

    model_config = ConfigDict(extra="forbid")
    backend: Literal["local", "gcs"] = "local"
    bucket: str = "uploads"
```

`Literal` is already imported in that module (check the header; add it to the `typing` import if not).

- [ ] **Step 6: Run to verify they pass**

`pytest tests/test_storage_local.py tests/test_storage.py -v` → all PASS (the Supabase tests still pass because only `create_signed_url` was removed).

- [ ] **Step 7: pre-commit, then commit**

```
pre-commit run --all-files
git commit -S -m "feat(storage): add delete to the seam and a local filesystem backend

StorageBackend gains delete and loses create_signed_url (zero callers).
LocalFileStorageBackend writes under output_dir/storage for dev and compose
and refuses any key that resolves outside its root. StorageSettings gains
backend (local|gcs), default local, so nothing changes for a fresh clone."
```

---

## Task 2: The GCS backend, and the Supabase client's removal

**Files:**
- Modify: `pyproject.toml:41-46` (`web` extra)
- Modify: `uv.lock` (regenerated — `make lock`, never by hand)
- Create: `lemely/io/storage_gcs.py`
- Modify: `lemely/io/storage.py` (delete `HttpStorageBackend`, `_is_missing_key`, the `httpx` import and the two timeout constants; keep `StorageBackend`, `StorageObjectNotFoundError`)
- Delete: `tests/test_storage.py`
- Rewrite: `tests/test_storage_live.py`
- Modify: `supabase/config.toml:118-127` (remove the `[storage.buckets.uploads]` block and its comment)
- Test: `tests/test_storage_gcs.py`

**Interfaces:**
- Produces `GcsStorageBackend(*, _client: Any = None)` satisfying `StorageBackend`. Consumed by Task 3.

- [ ] **Step 1: Add the dependency**

In `pyproject.toml`, append to the `web` list:

```toml
  "google-cloud-storage>=3.1,<4",
```

Then `make lock`. Commit the lockfile with the code in Step 7.

- [ ] **Step 2: Write the failing tests**

`tests/test_storage_gcs.py`:

```python
"""Hermetic tests for :class:`lemely.io.storage_gcs.GcsStorageBackend`.

The SDK client is injected (the ``_genai_client`` precedent in
``lemely.io.gemini``), so these pin the *contract* — create-only uploads,
the not-found mapping, deferred credential failure — without a network.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from google.api_core.exceptions import NotFound, PreconditionFailed
from google.auth.exceptions import DefaultCredentialsError
from google.cloud.storage.retry import DEFAULT_RETRY_IF_GENERATION_SPECIFIED

from lemely.io.storage import StorageObjectNotFoundError
from lemely.io.storage_gcs import GcsStorageBackend
from lemely.runtime.errors import ExternalServiceError


def _client_with_blob() -> tuple[MagicMock, MagicMock]:
    client = MagicMock()
    blob = MagicMock()
    client.bucket.return_value.blob.return_value = blob
    return client, blob


def test_upload_is_create_only_and_retried_conditionally() -> None:
    client, blob = _client_with_blob()
    GcsStorageBackend(_client=client).upload("b", "k/scan.pdf", b"data", "application/pdf")
    client.bucket.assert_called_once_with("b")
    client.bucket.return_value.blob.assert_called_once_with("k/scan.pdf")
    blob.upload_from_string.assert_called_once_with(
        b"data",
        content_type="application/pdf",
        if_generation_match=0,
        retry=DEFAULT_RETRY_IF_GENERATION_SPECIFIED,
        timeout=30.0,
    )


def test_upload_without_content_type_sends_octet_stream() -> None:
    client, blob = _client_with_blob()
    GcsStorageBackend(_client=client).upload("b", "k", b"d", None)
    assert blob.upload_from_string.call_args.kwargs["content_type"] == "application/octet-stream"


def test_existing_key_is_a_bug_not_an_overwrite() -> None:
    client, blob = _client_with_blob()
    blob.upload_from_string.side_effect = PreconditionFailed("exists")
    with pytest.raises(ExternalServiceError, match="already exists"):
        GcsStorageBackend(_client=client).upload("b", "k", b"d", None)


def test_download_missing_maps_to_not_found() -> None:
    client, blob = _client_with_blob()
    blob.download_as_bytes.side_effect = NotFound("nope")
    with pytest.raises(StorageObjectNotFoundError):
        GcsStorageBackend(_client=client).download("b", "k")


def test_download_returns_bytes() -> None:
    client, blob = _client_with_blob()
    blob.download_as_bytes.return_value = b"pdf"
    assert GcsStorageBackend(_client=client).download("b", "k") == b"pdf"
    blob.download_as_bytes.assert_called_once_with(timeout=30.0)


def test_delete_ignores_missing() -> None:
    client, blob = _client_with_blob()
    blob.delete.side_effect = NotFound("gone")
    GcsStorageBackend(_client=client).delete("b", "k")  # must not raise


def test_credentials_failure_is_deferred_to_first_use(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*_: Any, **__: Any) -> Any:
        raise DefaultCredentialsError("no adc")

    monkeypatch.setattr("lemely.io.storage_gcs.storage.Client", _boom)
    backend = GcsStorageBackend()  # constructing must not touch credentials
    with pytest.raises(ExternalServiceError, match="application-default credentials"):
        backend.download("b", "k")
```

- [ ] **Step 3: Run to verify they fail**

`pytest tests/test_storage_gcs.py -v` → FAIL with `ModuleNotFoundError: lemely.io.storage_gcs`.

- [ ] **Step 4: Write the backend**

`lemely/io/storage_gcs.py`:

```python
"""Google Cloud Storage :class:`~lemely.io.storage.StorageBackend` (DS12).

The official SDK rather than a thin httpx client — chosen for library-managed
retries and checksums. The client is built lazily on first use, never at
construction or import, so a misconfigured deploy fails on its first upload
with a readable ``ExternalServiceError`` instead of at startup with a
traceback, and the health route never touches it.

Uploads are **create-only**: ``if_generation_match=0`` refuses to overwrite an
existing key and, as a side effect, switches on the SDK's conditional retry
policy. Every key this codebase writes carries a server-generated UUID, so a
precondition failure is a bug and is surfaced as one.
"""

from __future__ import annotations

from typing import Any

from google.api_core.exceptions import GoogleAPICallError, NotFound, PreconditionFailed
from google.auth.exceptions import DefaultCredentialsError
from google.cloud import storage
from google.cloud.storage.retry import DEFAULT_RETRY_IF_GENERATION_SPECIFIED

from lemely.io.storage import StorageObjectNotFoundError
from lemely.runtime.errors import ExternalServiceError

_TRANSFER_TIMEOUT_SECONDS = 30.0


class GcsStorageBackend:
    """Real :class:`StorageBackend` over ``google.cloud.storage``."""

    def __init__(self, *, _client: Any = None) -> None:
        """Optionally inject a client (tests); otherwise one is built on first use."""
        self._raw_client: Any = _client

    def _client(self) -> Any:
        if self._raw_client is None:
            try:
                self._raw_client = storage.Client()
            except DefaultCredentialsError as exc:
                raise ExternalServiceError(
                    "Google Cloud Storage needs application-default credentials: "
                    "on Cloud Run attach a runtime service account; locally run "
                    "`gcloud auth application-default login` or set "
                    "LEMELY_STORAGE__BACKEND=local."
                ) from exc
        return self._raw_client

    def _blob(self, bucket: str, object_path: str) -> Any:
        return self._client().bucket(bucket).blob(object_path)

    def upload(
        self,
        bucket: str,
        object_path: str,
        data: bytes,
        content_type: str | None,
    ) -> None:
        """Create ``object_path`` in ``bucket``. An existing key is an error."""
        try:
            self._blob(bucket, object_path).upload_from_string(
                data,
                content_type=content_type or "application/octet-stream",
                if_generation_match=0,
                retry=DEFAULT_RETRY_IF_GENERATION_SPECIFIED,
                timeout=_TRANSFER_TIMEOUT_SECONDS,
            )
        except PreconditionFailed as exc:
            raise ExternalServiceError(
                f"Object {bucket}/{object_path} already exists; keys must be unique."
            ) from exc
        except GoogleAPICallError as exc:
            raise ExternalServiceError(f"Storage upload failed: {exc}") from exc

    def download(self, bucket: str, object_path: str) -> bytes:
        """Return the bytes at ``object_path``; missing → :class:`StorageObjectNotFoundError`."""
        try:
            data: bytes = self._blob(bucket, object_path).download_as_bytes(
                timeout=_TRANSFER_TIMEOUT_SECONDS
            )
        except NotFound as exc:
            raise StorageObjectNotFoundError(f"No object at {bucket}/{object_path}") from exc
        except GoogleAPICallError as exc:
            raise ExternalServiceError(f"Storage download failed: {exc}") from exc
        return data

    def delete(self, bucket: str, object_path: str) -> None:
        """Delete ``object_path``; a missing object is not an error."""
        try:
            self._blob(bucket, object_path).delete()
        except NotFound:
            return
        except GoogleAPICallError as exc:
            raise ExternalServiceError(f"Storage delete failed: {exc}") from exc


__all__ = ["GcsStorageBackend"]
```

`google.auth.exceptions.DefaultCredentialsError` is raised by `storage.Client()` when no ADC is available; the SDK's transport (`requests`) and `google-auth` both arrive with the package.

- [ ] **Step 5: Remove the Supabase client**

In `lemely/io/storage.py` delete `HttpStorageBackend`, `_is_missing_key`, `_TIMEOUT_SECONDS`, `_TRANSFER_TIMEOUT_SECONDS`, the `httpx` import, the `AuthError` import and the `TYPE_CHECKING` block; `__all__ = ["StorageBackend", "StorageObjectNotFoundError"]`. Rewrite the module docstring: "Object storage seam. :class:`StorageBackend` is the Protocol the GCS backend, the local backend and the test fake implement." Delete `tests/test_storage.py`.

Rewrite `tests/test_storage_live.py`:

```python
"""Live round trip against a real GCS bucket. Skips unless opted in.

Runs only when ``LEMELY_STORAGE__BACKEND=gcs`` and application-default
credentials resolve, matching the skip discipline of ``test_auth_live.py``.
Writes one unique key, reads it back, deletes it — nothing is left behind.
"""

from __future__ import annotations

import os
import uuid

import pytest

from lemely.io.storage import StorageObjectNotFoundError
from lemely.io.storage_gcs import GcsStorageBackend
from lemely.runtime.config import Settings


def _live_settings() -> Settings | None:
    settings = Settings()
    if settings.storage.backend != "gcs":
        return None
    try:
        import google.auth

        google.auth.default()
    except Exception:  # noqa: BLE001 — any ADC failure means "not opted in"
        return None
    return settings


@pytest.mark.skipif(_live_settings() is None, reason="GCS not configured (backend/ADC)")
def test_gcs_round_trip() -> None:
    settings = _live_settings()
    assert settings is not None
    backend = GcsStorageBackend()
    key = f"_live_tests/{uuid.uuid4().hex}/probe.txt"
    backend.upload(settings.storage.bucket, key, b"probe", "text/plain")
    try:
        assert backend.download(settings.storage.bucket, key) == b"probe"
    finally:
        backend.delete(settings.storage.bucket, key)
    with pytest.raises(StorageObjectNotFoundError):
        backend.download(settings.storage.bucket, key)
    assert os.environ.get("LEMELY_STORAGE__BACKEND") == "gcs"
```

In `supabase/config.toml`, delete the comment block and `[storage.buckets.uploads]` table (lines 118–127); keep `[storage]` itself.

- [ ] **Step 6: Run to verify they pass**

`pytest tests/test_storage_gcs.py tests/test_storage_local.py tests/test_storage_live.py -v` → the GCS and local suites PASS; the live test SKIPs. `grep -rn "HttpStorageBackend\|create_signed_url\|signed_url_ttl" lemely tests` → no matches.

- [ ] **Step 7: pre-commit, then commit**

```
pre-commit run --all-files
git commit -S -m "feat(storage): GCS backend over the official SDK; drop Supabase Storage

GcsStorageBackend builds its client lazily, uploads create-only with the
conditional retry policy, and maps NotFound to StorageObjectNotFoundError
and everything else to ExternalServiceError. The Supabase Storage client,
its tests and the local bucket config go: Supabase is auth and Postgres
only from here (DS7)."
```

---

## Task 3: Backend selection, health, doctor

**Files:**
- Modify: `lemely/web/deps.py:122-129` (`get_storage_backend`)
- Modify: `lemely/web/schemas.py:65-69` (`HealthDTO`)
- Modify: `lemely/web/routers/meta.py`
- Modify: `lemely/io/storage.py` (add `check_storage`)
- Modify: `lemely/app/cli.py:475-481` (doctor — after the `cache_dir_writable` record)
- Test: `tests/test_web_app.py`, `tests/test_storage_local.py`

**Interfaces:**
- Produces `check_storage(settings, *, no_network: bool) -> tuple[bool, str]` in `lemely/io/storage.py`. Consumed by `lemely doctor`.
- Produces `HealthDTO.storage: StorageHealthDTO` with `backend: str`, `bucket: str`. Consumed by Task 19's smoke test.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_web_app.py`:

```python
def test_health_reports_storage_backend_without_touching_it(monkeypatch: pytest.MonkeyPatch) -> None:
    """DS12: the health route names the backend and bucket from settings only."""
    monkeypatch.setenv("LEMELY_STORAGE__BACKEND", "gcs")
    monkeypatch.setenv("LEMELY_STORAGE__BUCKET", "proj-uploads-staging")
    from lemely.web.deps import reset_singletons

    reset_singletons()
    body = TestClient(create_app()).get("/api/health").json()
    assert body["storage"] == {"backend": "gcs", "bucket": "proj-uploads-staging"}
    reset_singletons()
```

Append to `tests/test_storage_local.py`:

```python
def test_check_storage_local_reports_root(tmp_path: Path) -> None:
    from lemely.io.storage import check_storage
    from lemely.runtime.config import Settings

    settings = Settings().model_copy(
        update={"paths": Settings().paths.model_copy(update={"output_dir": tmp_path})}
    )
    ok, detail = check_storage(settings, no_network=True)
    assert ok is True
    assert detail == str(tmp_path / "storage")
```

- [ ] **Step 2: Run to verify they fail**

`pytest tests/test_web_app.py::test_health_reports_storage_backend_without_touching_it tests/test_storage_local.py::test_check_storage_local_reports_root -v` → FAIL (`KeyError: 'storage'`; `ImportError: check_storage`).

- [ ] **Step 3: Implement**

`lemely/web/deps.py`:

```python
@lru_cache(maxsize=1)
def get_storage_backend() -> StorageBackend:
    """Return the process-wide :class:`StorageBackend` singleton.

    Selected on ``settings.storage.backend`` (DS7/DS12): ``gcs`` in staging and
    production, ``local`` everywhere else. Tests override this with the
    in-memory ``FakeStorageBackend`` (``tests/storage_fakes.py``).
    """
    settings = get_settings()
    if settings.storage.backend == "gcs":
        from lemely.io.storage_gcs import GcsStorageBackend

        return GcsStorageBackend()
    from lemely.io.storage_local import LocalFileStorageBackend

    return LocalFileStorageBackend(settings.paths.output_dir / "storage")
```

`lemely/web/schemas.py`:

```python
class StorageHealthDTO(ApiModel):
    """Which object-storage backend this process is configured for (DS12)."""

    backend: str
    bucket: str


class HealthDTO(ApiModel):
    """Health-check payload for ``GET /api/health``."""

    status: Literal["ok"] = "ok"
    apiKeyConfigured: bool
    storage: StorageHealthDTO
```

`lemely/web/routers/meta.py`:

```python
    return HealthDTO(
        apiKeyConfigured=settings.gemini_api_key is not None,
        storage=StorageHealthDTO(
            backend=settings.storage.backend, bucket=settings.storage.bucket
        ),
    )
```

(no network call — the smoke test in Task 19 relies on that.)

`lemely/io/storage.py`, appended:

```python
def check_storage(settings: Settings, *, no_network: bool) -> tuple[bool, str]:
    """``lemely doctor``'s storage check: ``(passed, detail)``.

    ``local``: the root is writable. ``gcs``: application-default credentials
    resolve and — unless ``no_network`` — the bucket answers a metadata read.
    """
    if settings.storage.backend == "local":
        root = settings.paths.output_dir / "storage"
        try:
            root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return False, str(exc)
        return os.access(root, os.W_OK), str(root)
    try:
        import google.auth

        google.auth.default()
    except Exception as exc:  # noqa: BLE001 — surface any ADC failure as the detail
        return False, f"application-default credentials: {exc}"
    if no_network:
        return True, f"gcs://{settings.storage.bucket} (not probed: --no-network)"
    try:
        from google.cloud import storage

        storage.Client().get_bucket(settings.storage.bucket)
    except Exception as exc:  # noqa: BLE001
        return False, f"bucket {settings.storage.bucket}: {exc}"
    return True, f"gcs://{settings.storage.bucket}"
```

(add `import os` and a `TYPE_CHECKING` import of `Settings`.) In `lemely/app/cli.py`, after the `cache_dir_writable` block:

```python
    from lemely.io.storage import check_storage

    storage_ok, storage_detail = check_storage(settings, no_network=no_network)
    record("storage_backend", storage_ok, detail=storage_detail)
```

- [ ] **Step 4: Run to verify they pass**

`pytest tests/test_web_app.py tests/test_storage_local.py tests/test_student_correct.py tests/test_web_notify_seams.py tests/test_web_xp_awards.py -q` → PASS (the student tests already use the fake).

- [ ] **Step 5: pre-commit, then commit**

```
pre-commit run --all-files
git commit -S -m "feat(storage): select the backend from settings; report it on /api/health and in doctor"
```

---

## Stage B — teacher papers (spec §4.2; rollout step 3)

## Task 4: Migration `0024` — `teacher_papers`, the ORM model, and `GradingSettings`

**Files:**
- Create: `lemely/db/models/teacher_papers.py`
- Modify: `lemely/db/models/__init__.py` (import + `__all__`)
- Create: `lemely/db/migrations/versions/0024_teacher_papers.py`
- Modify: `lemely/runtime/config.py` (new `GradingSettings`; `Settings.grading`)
- Modify: `lemely/runtime/example_toml.py` (emit `[grading]` with `stale_run_after_seconds`)
- Test: `tests/test_db_schema.py`

**Interfaces:**
- Produces `TeacherPaper` (columns as in spec §4.2). Consumed by Task 5.
- Produces `GradingSettings.stale_run_after_seconds: int = 900`, `Settings.grading`. Consumed by Tasks 5, 6.

- [ ] **Step 1: Write the failing schema test**

Add to `tests/test_db_schema.py`:

```python
def test_teacher_paper_row_defaults(pg_engine: sa.Engine) -> None:
    """Spec §4.2: a fresh row is pending, unstaged, and reuses the uploadstatus enum."""
    from lemely.db.models import TeacherPaper, User
    from lemely.db.models.enums import Role, UploadStatus

    with Session(pg_engine) as session:
        teacher = User(id=uuid.uuid4(), email="tp@example.com", role=Role.teacher)
        session.add(teacher)
        session.flush()
        paper = TeacherPaper(
            uploaded_by=teacher.id,
            storage_path=f"teacher/{teacher.id}/{uuid.uuid4().hex}/scan.pdf",
        )
        session.add(paper)
        session.commit()
        session.refresh(paper)
        assert paper.status is UploadStatus.pending
        assert paper.stage is None
        assert paper.report_json is None
        assert paper.run_started_at is None
        enum_name = session.execute(
            sa.text(
                "SELECT udt_name FROM information_schema.columns "
                "WHERE table_name = 'teacher_papers' AND column_name = 'status'"
            )
        ).scalar_one()
        assert enum_name == "uploadstatus"
```

- [ ] **Step 2: Run to verify it fails**

`pytest tests/test_db_schema.py::test_teacher_paper_row_defaults -v` → FAIL (`ImportError: TeacherPaper`), or SKIP without Postgres.

- [ ] **Step 3: Write the model**

`lemely/db/models/teacher_papers.py`:

```python
"""ORM model for a teacher-console paper (spec 2026-09-03 §4.2, DS2/DS11/DS13)."""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from lemely.db.base import Base
from lemely.db.models.enums import TimestampMixin, UploadStatus


class TeacherPaper(TimestampMixin, Base):
    """One scan uploaded through the grading console, and its run state.

    Replaces the in-process ``_PaperStore``. Every field the grading worker
    used to mutate on an in-memory entry is a column, so any instance can
    answer the polled routes from the row and a restart loses nothing.
    ``graded`` versus ``review`` is *derived* from ``report_json`` at read time
    — ``status`` records only the run's lifecycle.
    """

    __tablename__ = "teacher_papers"
    __table_args__ = (sa.Index("ix_teacher_papers_uploaded_by_created_at", "uploaded_by", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
    )
    uploaded_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    student_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    storage_path: Mapped[str] = mapped_column(sa.String, nullable=False)
    scheme_storage_path: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    original_filename: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    content_type: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    byte_size: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    status: Mapped[UploadStatus] = mapped_column(
        # Same Postgres type ``uploads.status`` already uses; SQLAlchemy dedups
        # enum types by name at ``create_all``, and the migration below passes
        # ``create_type=False`` so Alembic never tries to re-create it.
        sa.Enum(UploadStatus, name="uploadstatus"),
        nullable=False,
        server_default=sa.text("'pending'::uploadstatus"),
    )
    stage: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    progress_index: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    progress_total: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # type: ignore[type-arg]
    mark_scheme_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # type: ignore[type-arg]
    report_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # type: ignore[type-arg]
    error: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    run_started_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)


__all__ = ["TeacherPaper"]
```

Register it in `lemely/db/models/__init__.py` (import line beside the others; add `"TeacherPaper"` to `__all__`).

- [ ] **Step 4: Write the migration**

`lemely/db/migrations/versions/0024_teacher_papers.py`:

```python
"""teacher_papers: the grading console's paper, as a row (spec 2026-09-03 §4.2)

Revision ID: 0024_teacher_papers
Revises: 0023_invites
Create Date: 2026-09-03 00:00:00.000000

One additive table. It replaces ``_PaperStore`` in ``routers/teacher.py`` — a
process-local dict that lost every teacher paper on restart and was invisible
to a second instance, the single largest reason the Cloud Run service was
pinned to one instance (DS2, DS13).

``status`` reuses the existing ``uploadstatus`` type (``create_type=False``):
a teacher paper's lifecycle is the same four states a student upload has, and
a second enum with the same members would be a type the schema could not
explain. ``graded``/``review`` are not states — they are read off
``report_json``. ``run_started_at`` plus ``TimestampMixin.updated_at`` are the
liveness signal for the claim query (a ``processing`` row whose
``updated_at`` is stale is a dead run). ``student_id`` is nullable and, today,
always NULL (D1.12) — kept so the column exists when class ownership lands.

Reversible: ``downgrade`` drops the table only. The enum type predates this
migration and is not ours to drop.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0024_teacher_papers"
down_revision: str | Sequence[str] | None = "0023_invites"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "teacher_papers",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("uploaded_by", sa.UUID(), nullable=False),
        sa.Column("student_id", sa.UUID(), nullable=True),
        sa.Column("storage_path", sa.String(), nullable=False),
        sa.Column("scheme_storage_path", sa.String(), nullable=True),
        sa.Column("original_filename", sa.String(), nullable=True),
        sa.Column("content_type", sa.String(), nullable=True),
        sa.Column("byte_size", sa.Integer(), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(
                "pending", "processing", "complete", "failed",
                name="uploadstatus", create_type=False,
            ),
            server_default=sa.text("'pending'::uploadstatus"),
            nullable=False,
        ),
        sa.Column("stage", sa.String(), nullable=True),
        sa.Column("progress_index", sa.Integer(), nullable=True),
        sa.Column("progress_total", sa.Integer(), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("mark_scheme_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("report_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("run_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["uploaded_by"], ["users.id"], name=op.f("fk_teacher_papers_uploaded_by_users"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["student_id"], ["users.id"], name=op.f("fk_teacher_papers_student_id_users"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_teacher_papers")),
    )
    op.create_index("ix_teacher_papers_uploaded_by_created_at", "teacher_papers", ["uploaded_by", "created_at"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_teacher_papers_uploaded_by_created_at", table_name="teacher_papers")
    op.drop_table("teacher_papers")
```

- [ ] **Step 5: Add `GradingSettings`**

In `lemely/runtime/config.py`, after `IntegritySettings`:

```python
class GradingSettings(BaseModel):
    """Teacher grading run tuning (spec 2026-09-03 §4.2).

    ``stale_run_after_seconds``: a ``teacher_papers`` row in ``processing``
    whose ``updated_at`` is older than this is a dead run — its instance died
    — and may be reclaimed by the next regrade. Progress is written at every
    stage and every question, so a silent quarter-hour is not a slow run.
    """

    model_config = ConfigDict(extra="forbid")
    stale_run_after_seconds: int = Field(default=900, ge=60)
```

and on `Settings`, after `integrity`: `grading: GradingSettings = GradingSettings()`. In `lemely/runtime/example_toml.py` emit a `[grading]` section with `stale_run_after_seconds = {s.grading.stale_run_after_seconds}` beside the other groups, then regenerate `lemely.toml.example` with the command the module's docstring names.

- [ ] **Step 6: Run to verify it passes, both migration directions**

```
pytest tests/test_db_schema.py::test_teacher_paper_row_defaults -v
alembic upgrade head && alembic downgrade -1 && alembic upgrade head
```

- [ ] **Step 7: pre-commit, then commit**

```
pre-commit run --all-files
git commit -S -m "feat(db): add teacher_papers (migration 0024) and GradingSettings

The grading console's paper becomes a row: identity, object keys, run
lifecycle on the shared uploadstatus enum, stage and progress, and JSONB
for detected metadata, the resolved scheme and the report. Replaces the
process-local _PaperStore that lost every paper on restart (DS2)."
```

---

## Task 5: `TeacherPaperRepository`

**Files:**
- Create: `lemely/db/teacher_paper_repo.py`
- Test: `tests/test_teacher_paper_repo.py` (copy the `pg_sessionmaker` fixture from `tests/test_auth_token_repo.py`)

**Interfaces:**
- Produces:

```python
@dataclass(frozen=True, slots=True)
class TeacherPaperRow:
    id: uuid.UUID
    uploaded_by: uuid.UUID
    student_id: uuid.UUID | None
    storage_path: str
    scheme_storage_path: str | None
    original_filename: str | None
    content_type: str | None
    status: UploadStatus
    stage: str | None
    progress: tuple[int, int] | None
    metadata: ExamMetadata | None
    mark_scheme: MarkScheme | None
    report: AccuracyReport | None
    error: str | None
    run_started_at: datetime | None
    created_at: datetime
    updated_at: datetime
    stale: bool          # status is processing AND updated_at < now - stale_after

class TeacherPaperRepository:
    def __init__(self, session_factory: sessionmaker[Session], *, stale_after: timedelta) -> None: ...
    def create(self, *, paper_id: uuid.UUID, uploaded_by: uuid.UUID, storage_path: str, scheme_storage_path: str | None, original_filename: str | None, content_type: str | None, byte_size: int | None) -> uuid.UUID: ...
    def get(self, paper_id: uuid.UUID) -> TeacherPaperRow | None: ...          # no visibility filter: for the worker
    def get_visible(self, paper_id: uuid.UUID, *, viewer_id: uuid.UUID, viewer_role: Role) -> TeacherPaperRow | None: ...
    def list_visible(self, *, viewer_id: uuid.UUID, viewer_role: Role) -> list[TeacherPaperRow]: ...
    def claim_run(self, paper_id: uuid.UUID) -> bool: ...
    def set_stage(self, paper_id: uuid.UUID, stage: str) -> None: ...
    def set_progress(self, paper_id: uuid.UUID, index: int, total: int) -> None: ...
    def set_metadata(self, paper_id: uuid.UUID, metadata: ExamMetadata) -> None: ...
    def set_mark_scheme(self, paper_id: uuid.UUID, scheme: MarkScheme) -> None: ...
    def finish(self, paper_id: uuid.UUID, report: AccuracyReport) -> None: ...
    def fail(self, paper_id: uuid.UUID, error: str) -> None: ...
```

Consumed by Task 6.

- [ ] **Step 1: Write the failing tests**

`tests/test_teacher_paper_repo.py` (fixture body copied from `tests/test_auth_token_repo.py`, then):

```python
def _user(sm: sessionmaker[Session], role: Role) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as s:
        s.add(User(id=uid, email=f"{uid.hex}@example.com", role=role))
    return uid


def _school_with(sm: sessionmaker[Session], *, admin: uuid.UUID, teachers: list[uuid.UUID]) -> uuid.UUID:
    sid = uuid.uuid4()
    with sm.begin() as s:
        s.add(School(id=sid, name=f"School {sid.hex[:6]}"))
        s.flush()
        s.add(SchoolMembership(school_id=sid, user_id=admin, membership_role=MembershipRole.school_admin))
        for t in teachers:
            s.add(SchoolMembership(school_id=sid, user_id=t, membership_role=MembershipRole.teacher))
    return sid


def _repo(sm: sessionmaker[Session], *, stale_seconds: int = 900) -> TeacherPaperRepository:
    return TeacherPaperRepository(sm, stale_after=timedelta(seconds=stale_seconds))


def _paper(repo: TeacherPaperRepository, owner: uuid.UUID) -> uuid.UUID:
    pid = uuid.uuid4()
    repo.create(
        paper_id=pid, uploaded_by=owner, storage_path=f"teacher/{owner}/{pid.hex}/scan.pdf",
        scheme_storage_path=None, original_filename="scan.pdf", content_type="application/pdf", byte_size=3,
    )
    return pid


def test_exactly_one_of_two_concurrent_claims_wins(pg_sessionmaker: sessionmaker[Session]) -> None:
    repo = _repo(pg_sessionmaker)
    pid = _paper(repo, _user(pg_sessionmaker, Role.teacher))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: repo.claim_run(pid), range(2)))
    assert sorted(results) == [False, True]


def test_processing_row_cannot_be_reclaimed_until_stale(pg_sessionmaker: sessionmaker[Session]) -> None:
    repo = _repo(pg_sessionmaker, stale_seconds=60)
    pid = _paper(repo, _user(pg_sessionmaker, Role.teacher))
    assert repo.claim_run(pid) is True
    assert repo.claim_run(pid) is False
    with pg_sessionmaker.begin() as s:
        s.execute(
            sa.update(TeacherPaper).where(TeacherPaper.id == pid)
            .values(updated_at=datetime.now(UTC) - timedelta(seconds=120))
        )
    assert repo.claim_run(pid) is True


def test_finished_and_failed_rows_can_be_reclaimed(pg_sessionmaker: sessionmaker[Session]) -> None:
    repo = _repo(pg_sessionmaker)
    pid = _paper(repo, _user(pg_sessionmaker, Role.teacher))
    assert repo.claim_run(pid)
    repo.fail(pid, "boom")
    assert repo.claim_run(pid)
    repo.finish(pid, _report())
    assert repo.claim_run(pid)


def test_visibility_matrix(pg_sessionmaker: sessionmaker[Session]) -> None:
    repo = _repo(pg_sessionmaker)
    t1, t2, t3 = (_user(pg_sessionmaker, Role.teacher) for _ in range(3))
    admin_a = _user(pg_sessionmaker, Role.school_admin)
    admin_b = _user(pg_sessionmaker, Role.school_admin)
    platform = _user(pg_sessionmaker, Role.platform_admin)
    _school_with(pg_sessionmaker, admin=admin_a, teachers=[t1, t2])
    _school_with(pg_sessionmaker, admin=admin_b, teachers=[t3])
    p1, p2, p3 = (_paper(repo, t) for t in (t1, t2, t3))

    ids = lambda rows: {r.id for r in rows}  # noqa: E731
    assert ids(repo.list_visible(viewer_id=t1, viewer_role=Role.teacher)) == {p1}
    assert ids(repo.list_visible(viewer_id=admin_a, viewer_role=Role.school_admin)) == {p1, p2}
    assert ids(repo.list_visible(viewer_id=admin_b, viewer_role=Role.school_admin)) == {p3}
    assert ids(repo.list_visible(viewer_id=platform, viewer_role=Role.platform_admin)) == {p1, p2, p3}
    assert repo.get_visible(p3, viewer_id=admin_a, viewer_role=Role.school_admin) is None
    assert repo.get_visible(p1, viewer_id=t1, viewer_role=Role.teacher) is not None
    # The worker reads without a viewer: it is not a person, it is the run.
    assert repo.get(p3) is not None
    assert repo.get(uuid.uuid4()) is None


def test_progress_and_report_round_trip(pg_sessionmaker: sessionmaker[Session]) -> None:
    repo = _repo(pg_sessionmaker)
    owner = _user(pg_sessionmaker, Role.teacher)
    pid = _paper(repo, owner)
    repo.claim_run(pid)
    repo.set_stage(pid, "mark")
    repo.set_progress(pid, 3, 12)
    row = repo.get_visible(pid, viewer_id=owner, viewer_role=Role.teacher)
    assert row is not None and row.stage == "mark" and row.progress == (3, 12)
    assert row.status is UploadStatus.processing and row.stale is False
    repo.finish(pid, _report())
    row = repo.get_visible(pid, viewer_id=owner, viewer_role=Role.teacher)
    assert row is not None and row.status is UploadStatus.complete
    assert row.report is not None and row.report.correction.awarded_marks == 7
```

`_report()` builds a minimal `AccuracyReport` exactly as `tests/test_web_teacher.py`'s existing `_report` helper does (copy it; `awarded_marks=7`). Imports: `School`, `SchoolMembership` from `lemely.db.models`, `MembershipRole`, `Role`, `UploadStatus` from `lemely.db.models.enums`, `TeacherPaper` from `lemely.db.models`, `ThreadPoolExecutor` from `concurrent.futures`.

- [ ] **Step 2: Run to verify they fail**

`pytest tests/test_teacher_paper_repo.py -v` → FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

`lemely/db/teacher_paper_repo.py`:

```python
"""Teacher paper persistence (spec 2026-09-03 §4.2). Only writer of ``teacher_papers``."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy import or_, select

from lemely.core.loose_schemas import MarkScheme
from lemely.core.schemas import AccuracyReport, ExamMetadata
from lemely.db.models.enums import MembershipRole, Role, UploadStatus
from lemely.db.models.orgs import SchoolMembership
from lemely.db.models.teacher_papers import TeacherPaper

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker
    from sqlalchemy.sql import ColumnElement


@dataclass(frozen=True, slots=True)
class TeacherPaperRow:
    """Detached snapshot of a paper. ``stale`` is computed against the repo's window."""

    id: uuid.UUID
    uploaded_by: uuid.UUID
    student_id: uuid.UUID | None
    storage_path: str
    scheme_storage_path: str | None
    original_filename: str | None
    content_type: str | None
    status: UploadStatus
    stage: str | None
    progress: tuple[int, int] | None
    metadata: ExamMetadata | None
    mark_scheme: MarkScheme | None
    report: AccuracyReport | None
    error: str | None
    run_started_at: datetime | None
    created_at: datetime
    updated_at: datetime
    stale: bool


class TeacherPaperRepository:
    """CRUD plus the cross-instance run claim for :class:`TeacherPaper`."""

    def __init__(self, session_factory: sessionmaker[Session], *, stale_after: timedelta) -> None:
        """Bind to a ``sessionmaker``; ``stale_after`` is ``GradingSettings.stale_run_after_seconds``."""
        self._sm = session_factory
        self._stale_after = stale_after

    # -- visibility (DS11) --------------------------------------------------

    def _visible(self, viewer_id: uuid.UUID, viewer_role: Role) -> ColumnElement[bool]:
        if viewer_role is Role.platform_admin:
            return sa.true()
        own = TeacherPaper.uploaded_by == viewer_id
        if viewer_role is not Role.school_admin:
            return own
        admin_schools = select(SchoolMembership.school_id).where(
            SchoolMembership.user_id == viewer_id,
            SchoolMembership.membership_role == MembershipRole.school_admin,
        )
        teachers = select(SchoolMembership.user_id).where(
            SchoolMembership.school_id.in_(admin_schools),
            SchoolMembership.membership_role == MembershipRole.teacher,
        )
        return or_(own, TeacherPaper.uploaded_by.in_(teachers))

    def get(self, paper_id: uuid.UUID) -> TeacherPaperRow | None:
        """The paper with no visibility filter — for the grading worker, never a route."""
        with self._sm() as session:
            row = session.get(TeacherPaper, paper_id)
            return None if row is None else self._snapshot(row)

    def get_visible(
        self, paper_id: uuid.UUID, *, viewer_id: uuid.UUID, viewer_role: Role
    ) -> TeacherPaperRow | None:
        """The paper if the viewer may see it, else ``None`` (never an existence oracle)."""
        stmt = select(TeacherPaper).where(TeacherPaper.id == paper_id, self._visible(viewer_id, viewer_role))
        with self._sm() as session:
            row = session.scalars(stmt).one_or_none()
            return None if row is None else self._snapshot(row)

    def list_visible(self, *, viewer_id: uuid.UUID, viewer_role: Role) -> list[TeacherPaperRow]:
        """Every paper the viewer may see, newest first."""
        stmt = (
            select(TeacherPaper)
            .where(self._visible(viewer_id, viewer_role))
            .order_by(TeacherPaper.created_at.desc())
        )
        with self._sm() as session:
            return [self._snapshot(r) for r in session.scalars(stmt)]

    # -- lifecycle ------------------------------------------------------------

    def create(
        self,
        *,
        paper_id: uuid.UUID,
        uploaded_by: uuid.UUID,
        storage_path: str,
        scheme_storage_path: str | None,
        original_filename: str | None,
        content_type: str | None,
        byte_size: int | None,
    ) -> uuid.UUID:
        """Insert a ``pending`` row under the caller-generated ``paper_id``."""
        with self._sm.begin() as session:
            session.add(
                TeacherPaper(
                    id=paper_id,
                    uploaded_by=uploaded_by,
                    storage_path=storage_path,
                    scheme_storage_path=scheme_storage_path,
                    original_filename=original_filename,
                    content_type=content_type,
                    byte_size=byte_size,
                )
            )
        return paper_id

    def claim_run(self, paper_id: uuid.UUID) -> bool:
        """Atomically move the row to ``processing``; ``True`` iff this caller now owns the run.

        One conditional UPDATE, so two instances (or two threads) racing for
        the same paper cannot both win — the database decides, not a lock.
        A ``processing`` row is reclaimable only once its ``updated_at`` is
        older than the stale window (a dead run).
        """
        cutoff = datetime.now(UTC) - self._stale_after
        stmt = (
            sa.update(TeacherPaper)
            .where(
                TeacherPaper.id == paper_id,
                or_(
                    TeacherPaper.status.in_([UploadStatus.pending, UploadStatus.failed, UploadStatus.complete]),
                    sa.and_(TeacherPaper.status == UploadStatus.processing, TeacherPaper.updated_at < cutoff),
                ),
            )
            .values(
                status=UploadStatus.processing,
                run_started_at=sa.func.now(),
                stage="detect",
                progress_index=None,
                progress_total=None,
                error=None,
            )
        )
        with self._sm.begin() as session:
            result = session.execute(stmt)
            return result.rowcount == 1

    def set_stage(self, paper_id: uuid.UUID, stage: str) -> None:
        """Move to ``stage`` and clear the counter (``updated_at`` moves — liveness)."""
        self._update(paper_id, stage=stage, progress_index=None, progress_total=None)

    def set_progress(self, paper_id: uuid.UUID, index: int, total: int) -> None:
        """Record the per-stage counter."""
        self._update(paper_id, progress_index=index, progress_total=total)

    def set_metadata(self, paper_id: uuid.UUID, metadata: ExamMetadata) -> None:
        """Cache the detected exam metadata."""
        self._update(paper_id, metadata_json=metadata.model_dump(mode="json"))

    def set_mark_scheme(self, paper_id: uuid.UUID, scheme: MarkScheme) -> None:
        """Cache the resolved scheme so a regrade need not re-parse."""
        self._update(paper_id, mark_scheme_json=scheme.model_dump(mode="json"))

    def finish(self, paper_id: uuid.UUID, report: AccuracyReport) -> None:
        """Terminal success."""
        self._update(
            paper_id,
            status=UploadStatus.complete,
            report_json=report.model_dump(mode="json"),
            error=None,
            progress_index=None,
            progress_total=None,
        )

    def fail(self, paper_id: uuid.UUID, error: str) -> None:
        """Terminal failure, with the reason the console shows."""
        self._update(paper_id, status=UploadStatus.failed, error=error)

    # -- helpers --------------------------------------------------------------

    def _update(self, paper_id: uuid.UUID, **values: object) -> None:
        with self._sm.begin() as session:
            session.execute(sa.update(TeacherPaper).where(TeacherPaper.id == paper_id).values(**values))

    def _snapshot(self, row: TeacherPaper) -> TeacherPaperRow:
        progress = (
            (row.progress_index, row.progress_total)
            if row.progress_index is not None and row.progress_total is not None
            else None
        )
        stale = (
            row.status is UploadStatus.processing
            and row.updated_at < datetime.now(UTC) - self._stale_after
        )
        return TeacherPaperRow(
            id=row.id,
            uploaded_by=row.uploaded_by,
            student_id=row.student_id,
            storage_path=row.storage_path,
            scheme_storage_path=row.scheme_storage_path,
            original_filename=row.original_filename,
            content_type=row.content_type,
            status=row.status,
            stage=row.stage,
            progress=progress,
            metadata=ExamMetadata.model_validate(row.metadata_json) if row.metadata_json else None,
            mark_scheme=MarkScheme.model_validate(row.mark_scheme_json) if row.mark_scheme_json else None,
            report=AccuracyReport.model_validate(row.report_json) if row.report_json else None,
            error=row.error,
            run_started_at=row.run_started_at,
            created_at=row.created_at,
            updated_at=row.updated_at,
            stale=stale,
        )


__all__ = ["TeacherPaperRepository", "TeacherPaperRow"]
```

- [ ] **Step 4: Run to verify they pass**

`pytest tests/test_teacher_paper_repo.py -v` → PASS.

- [ ] **Step 5: pre-commit, then commit**

```
pre-commit run --all-files
git commit -S -m "feat(db): TeacherPaperRepository with an atomic cross-instance run claim

claim_run is one conditional UPDATE: pending, failed and complete rows are
claimable, a processing row only once its updated_at is older than
GradingSettings.stale_run_after_seconds. Visibility is a query on
uploaded_by joined through school memberships (DS11)."
```

---

## Task 6: The teacher router on the repository and the storage seam

This is the largest task and the one the 76 existing router tests exercise. It deletes the in-process stores, the job registry and the two SSE routes (DS14), and rewires every paper route.

**Files:**
- Modify: `lemely/web/routers/teacher.py` (the whole "In-process paper store", "Background grading", "Grading console", "Mark schemes" — the latter only where it touched `papers_store` — and preview sections)
- Modify: `lemely/web/deps.py` (new `get_teacher_paper_repo`, `reset_singletons`)
- Delete: `lemely/web/jobs.py`
- Modify: `web/src/lib/hooks/useTeacherApi.ts:895-935` (delete `extractPaper`, `gradePaper` and their `TeacherPipelineFrame` import if now unused)
- Modify: `tests/test_authz_matrix_complete.py:193-194` (delete the two rows), `tests/test_web_teacher.py`
- Test: `tests/test_web_teacher.py`

**Interfaces:**
- Consumes `TeacherPaperRepository` (Task 5), `StorageBackend` (Task 1), `GradingSettings` (Task 4).
- Produces `get_teacher_paper_repo() -> TeacherPaperRepository` in `deps.py`.
- Produces module functions in `teacher.py` that Task 8 reuses: `_download_to(storage, bucket, key, dest: Path) -> Path`, `_run_grading_job(paper_id, settings, repo, storage, history_store, gemini_client, corpus)` — with `corpus` typed `SchemeCorpusRepository | None` **until Task 8**, where it becomes required.

- [ ] **Step 1: Rewire the test fixtures**

In `tests/test_web_teacher.py`, replace the `client` fixture and every `papers_store`/`_PaperEntry` use:

```python
@pytest.fixture
def pg_sessionmaker() -> Iterator[sessionmaker[Session]]:
    ...  # verbatim from tests/test_auth_token_repo.py


@pytest.fixture
def teacher_user(pg_sessionmaker: sessionmaker[Session]) -> uuid.UUID:
    uid = uuid.uuid4()
    with pg_sessionmaker.begin() as s:
        s.add(User(id=uid, email=f"{uid.hex}@example.com", role=Role.teacher))
    return uid


@pytest.fixture
def paper_repo(pg_sessionmaker: sessionmaker[Session]) -> TeacherPaperRepository:
    return TeacherPaperRepository(pg_sessionmaker, stale_after=timedelta(seconds=900))


@pytest.fixture
def storage_backend() -> FakeStorageBackend:
    return FakeStorageBackend()


@pytest.fixture
def client(
    settings: Settings,
    history_store: HistoryStore,
    gemini_client: MagicMock,
    paper_repo: TeacherPaperRepository,
    storage_backend: FakeStorageBackend,
    teacher_user: uuid.UUID,
) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_history_store] = lambda: history_store
    app.dependency_overrides[get_gemini_client] = lambda: gemini_client
    app.dependency_overrides[get_teacher_paper_repo] = lambda: paper_repo
    app.dependency_overrides[get_storage_backend] = lambda: storage_backend
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(user_id=str(teacher_user), role="teacher")
    yield TestClient(app)
    app.dependency_overrides.clear()
```

Replace the "attach a pre-built report" idiom (`papers_store.put(_PaperEntry(..., report=report))`) with a helper:

```python
def _seed_graded_paper(repo: TeacherPaperRepository, storage: FakeStorageBackend, owner: uuid.UUID, report: AccuracyReport) -> str:
    pid = uuid.uuid4()
    key = f"teacher/{owner}/{pid.hex}/scan.pdf"
    storage.upload("uploads", key, b"%PDF-1.4 seeded", "application/pdf")
    repo.create(paper_id=pid, uploaded_by=owner, storage_path=key, scheme_storage_path=None,
                original_filename="scan.pdf", content_type="application/pdf", byte_size=15)
    repo.claim_run(pid)
    repo.finish(pid, report)
    return str(pid)
```

Change the traversal test to assert the object key:

```python
def test_upload_filename_cannot_escape_sandbox(client, storage_backend, teacher_user) -> None:
    resp = client.post("/api/papers/upload", files={"scan": ("../../../../etc/evil.pdf", b"%PDF-1.4 data", "application/pdf")})
    assert resp.status_code == 200
    paper_id = resp.json()["paperId"]
    keys = [k for (_b, k) in storage_backend._objects]
    assert keys == [f"teacher/{teacher_user}/{uuid.UUID(paper_id).hex}/evil.pdf"]
```

Add two new tests:

```python
def test_paper_of_another_teacher_is_404(client, paper_repo, storage_backend, pg_sessionmaker) -> None:
    other = uuid.uuid4()
    with pg_sessionmaker.begin() as s:
        s.add(User(id=other, email=f"{other.hex}@example.com", role=Role.teacher))
    pid = _seed_graded_paper(paper_repo, storage_backend, other, _report())
    assert client.get(f"/api/papers/{pid}").status_code == 404
    assert client.get("/api/papers").json()["papers"] == []


def test_stale_processing_paper_renders_as_failed_with_retry(client, paper_repo, storage_backend, teacher_user, pg_sessionmaker) -> None:
    pid = _seed_graded_paper(paper_repo, storage_backend, teacher_user, _report())
    paper_repo.claim_run(uuid.UUID(pid))
    with pg_sessionmaker.begin() as s:
        s.execute(sa.update(TeacherPaper).where(TeacherPaper.id == uuid.UUID(pid)).values(updated_at=datetime.now(UTC) - timedelta(hours=1)))
    body = client.get(f"/api/papers/{pid}").json()
    assert body["kind"] == "failed"
    assert "lost" in body["error"]
```

Delete the tests for `/papers/{id}/extract` and `/papers/{id}/grade` streams. Run `pytest tests/test_web_teacher.py -q` → they fail on the missing dependency/repository names.

- [ ] **Step 2: Add the dependency**

In `lemely/web/deps.py`:

```python
@lru_cache(maxsize=1)
def get_teacher_paper_repo() -> TeacherPaperRepository:
    """Return the process-wide :class:`TeacherPaperRepository` singleton (spec §4.2)."""
    settings = get_settings()
    return TeacherPaperRepository(
        get_sessionmaker(settings),
        stale_after=timedelta(seconds=settings.grading.stale_run_after_seconds),
    )
```

Import it, add `get_teacher_paper_repo.cache_clear()` to `reset_singletons`.

- [ ] **Step 3: Rewrite the router's paper sections**

Delete from `teacher.py`: `_PaperStore`, `_PaperEntry`, `papers_store`, `_jobs_lock`, `_ensure_grading_job`, `_track_progress`'s entry parameter (see below), the `registry` import and `lemely/web/jobs.py`, `extract_paper`, `grade_paper_endpoint`, `_write_upload_capped`, and the `Future`/`queue`/`threading` imports that become unused. Keep `_grading_pool` at `max_workers=1` and rewrite its comment: "One worker so Queued means queued — a paper genuinely waiting behind another on this instance. Raising it is a one-line change once per-run event scoping (spec §4.5) lands." Keep `_JOB_STAGES`, `_paper_kind`, `_detection_available`, `_detected_fields`, `_session_label`, `_graded_pipeline_steps`.

New helpers (module level):

```python
def _viewer(auth: AuthContext) -> tuple[uuid.UUID, Role]:
    return parse_user_id(auth.user_id), Role(auth.role)


def _require_paper(repo: TeacherPaperRepository, auth: AuthContext, paper_id: str) -> TeacherPaperRow:
    """The visible paper or a 404 — unknown and not-visible are indistinguishable."""
    try:
        target = uuid.UUID(paper_id)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Unknown paper: {paper_id}") from None
    viewer_id, viewer_role = _viewer(auth)
    row = repo.get_visible(target, viewer_id=viewer_id, viewer_role=viewer_role)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Unknown paper: {paper_id}")
    return row


def _download_to(storage: StorageBackend, bucket: str, key: str, dest: Path) -> Path:
    """Materialise one object as a file for the pipeline; the caller owns ``dest``'s directory."""
    dest.write_bytes(storage.download(bucket, key))
    return dest


_LOST_RUN_ERROR = "This run was lost when its server instance stopped. Re-run marking to try again."


def _row_kind(row: TeacherPaperRow) -> PaperKind:
    if row.report is not None and row.status is UploadStatus.complete:
        return _paper_kind(row.report)
    if row.stale or row.status is UploadStatus.failed:
        return "failed"
    return "processing" if row.status is UploadStatus.processing else "queued"


def _row_error(row: TeacherPaperRow) -> str | None:
    return _LOST_RUN_ERROR if row.stale else row.error


def _paper_label(row: TeacherPaperRow) -> str:
    metadata = row.metadata or (row.report.correction.metadata if row.report else None)
    if metadata is None:
        return row.original_filename or str(row.id)
    session = metadata.session_month
    if metadata.session_year is not None:
        session = f"{session} {metadata.session_year}"
    return f"Paper {metadata.paper_number} V{metadata.paper_variant} {session} - {row.created_at.date().isoformat()}"
```

`_paper_summary`, `_batch_tabs`, `_live_pipeline_steps`, `get_paper` and `grading_queue` take `TeacherPaperRow` instead of `_PaperEntry`, using `_row_kind`, `_row_error`, `row.stage`, `row.progress` — same logic, same DTOs. `_live_pipeline_steps` treats `row.stage is None` as index 0 and `running = row.status is UploadStatus.processing and not row.stale`.

Upload route:

```python
@router.post("/papers/upload", response_model=UploadResponseDTO)
async def upload_paper(
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    settings: Annotated[Settings, Depends(get_settings)],
    repo: Annotated[TeacherPaperRepository, Depends(get_teacher_paper_repo)],
    storage: Annotated[StorageBackend, Depends(get_storage_backend)],
    history_store: Annotated[HistoryStoreProtocol, Depends(get_history_store)],
    gemini_client: Annotated[GeminiClient, Depends(get_gemini_client)],
    scan: Annotated[UploadFile, File()],
    mark_scheme: Annotated[UploadFile | None, File()] = None,
) -> UploadResponseDTO:
    """Store the scan (+ optional scheme) in object storage, insert the row, start marking.

    Keys: ``teacher/{uploaded_by}/{paper_id}/{safe_name}`` and a fixed
    ``mark_scheme.pdf`` sibling (spec §4.1). ``jobId`` equals ``paperId`` —
    the job registry is gone, the row is the job. ``detected`` stays empty
    (D6.13): detection runs inside the job.
    """
    uploaded_by, _ = _viewer(auth)
    paper_id = uuid.uuid4()
    prefix = f"teacher/{uploaded_by}/{paper_id.hex}"
    scan_bytes = await scan.read()
    check_upload_cap(scan_bytes, max_bytes=_MAX_UPLOAD_BYTES)
    scan_key = f"{prefix}/{_safe_upload_name(scan.filename, 'scan.pdf')}"
    storage.upload(settings.storage.bucket, scan_key, scan_bytes, scan.content_type)
    scheme_key: str | None = None
    if mark_scheme is not None:
        scheme_bytes = await mark_scheme.read()
        check_upload_cap(scheme_bytes, max_bytes=_MAX_UPLOAD_BYTES)
        scheme_key = f"{prefix}/mark_scheme.pdf"
        storage.upload(settings.storage.bucket, scheme_key, scheme_bytes, mark_scheme.content_type)
    repo.create(
        paper_id=paper_id, uploaded_by=uploaded_by, storage_path=scan_key,
        scheme_storage_path=scheme_key, original_filename=_safe_upload_name(scan.filename, "scan.pdf"),
        content_type=scan.content_type, byte_size=len(scan_bytes),
    )
    _start_run_if_claimed(paper_id, settings, repo, storage, history_store, gemini_client)
    return UploadResponseDTO(jobId=str(paper_id), paperId=str(paper_id), detected=[])


def _start_run_if_claimed(paper_id, settings, repo, storage, history_store, gemini_client) -> bool:
    """Claim the run on the row; if this instance won, submit it to the local pool."""
    if not repo.claim_run(paper_id):
        return False
    _grading_pool.submit(_run_grading_job, paper_id, settings, repo, storage, history_store, gemini_client, None)
    return True
```

The `_MAX_UPLOAD_BYTES` monkeypatch test keeps working because the cap is read at call time.

Grading job — the same phases as today, every state write to the row:

```python
def _run_grading_job(paper_id, settings, repo, storage, history_store, gemini_client, corpus) -> None:
    """Detect, resolve, extract and mark one paper on this instance's pool. Never raises."""
    from lemely.web.services.grading import extract_answers, grade_paper

    progress_queue = bus.subscribe_queue()
    stop = threading.Event()
    tracker = threading.Thread(target=_track_progress, args=(repo, paper_id, progress_queue, stop), daemon=True)
    tracker.start()
    try:
        row = repo.get(paper_id)
        if row is None:
            return
        with tempfile.TemporaryDirectory() as tmp:
            scan_path = _download_to(storage, settings.storage.bucket, row.storage_path, Path(tmp) / Path(row.storage_path).name)
            sibling = None
            if row.scheme_storage_path is not None:
                sibling = _download_to(storage, settings.storage.bucket, row.scheme_storage_path, Path(tmp) / "mark_scheme.pdf")
            metadata = row.metadata
            if metadata is None and _detection_available(settings):
                try:
                    metadata = ScanMetadataExtractor(gemini_client)(scan_path)
                    repo.set_metadata(paper_id, metadata)
                except Exception as exc:
                    log.exception("teacher_detection_failed", paper_id=str(paper_id))
                    bus.publish(EventType.WARNING, paper_id=str(paper_id), message=f"Could not read this scan's exam details: {exc}")
            repo.set_stage(paper_id, "scheme")
            # Today's resolver signature: it looks for ``mark_scheme.pdf`` beside
            # ``scan_path``, which is exactly where ``sibling`` was downloaded.
            # Task 8 switches this call to the corpus-backed signature.
            scheme = row.mark_scheme or resolve_mark_scheme(scan_path, settings, gemini_client, metadata=metadata)
            if scheme is None:
                repo.fail(paper_id, "No mark scheme could be resolved for this paper — nothing was marked. Attach one on upload, or add it under Mark schemes and re-run.")
                return
            repo.set_mark_scheme(paper_id, scheme)
            repo.set_stage(paper_id, "extract")
            extracted = extract_answers(scan_path, scheme, gemini_client=gemini_client)
            repo.set_stage(paper_id, "mark")
            report = grade_paper(scheme, extracted, gemini_client=gemini_client, student_id=None, history_store=None)
            repo.finish(paper_id, report)
    except Exception as exc:
        log.exception("teacher_grade_failed", paper_id=str(paper_id))
        repo.fail(paper_id, f"Grading failed: {exc}")
    finally:
        bus.unsubscribe_queue(progress_queue)
        stop.set()
```

`resolve_mark_scheme` keeps today's signature in this task; the `corpus` parameter is threaded through as `None` and unused until Task 8 makes it required. The `sibling` download still matters now: today's resolver finds the scheme as `scan_path.parent / "mark_scheme.pdf"`, which is where `_download_to` put it. `_track_progress` writes `repo.set_progress(paper_id, index, total)` and `repo.set_stage` on the two progress event types, filtered to events whose `paper_id` payload equals `str(paper_id)` (until Task 15 makes the queue itself scoped).

Regrade:

```python
@router.post("/papers/{paper_id}/regrade", status_code=202)
def regrade_paper(paper_id: str, auth, settings, repo, storage, history_store, gemini_client) -> dict[str, str]:
    row = _require_paper(repo, auth, paper_id)
    _start_run_if_claimed(row.id, settings, repo, storage, history_store, gemini_client)
    return {"paperId": paper_id, "status": "processing"}
```

Preview renders from bytes:

```python
    row = _require_paper(repo, auth, paper_id)
    try:
        data = storage.download(settings.storage.bucket, row.storage_path)
    except StorageObjectNotFoundError:
        raise HTTPException(status_code=404, detail=f"No stored scan for paper {paper_id}") from None
    with pymupdf.open(stream=data, filetype=_pymupdf_filetype(row.content_type)) as doc:
```

with `_pymupdf_filetype` returning `"pdf"` for `application/pdf`/`None` and the subtype (`"png"`, `"jpeg"`) for images.

List and queue use `repo.list_visible(viewer_id=..., viewer_role=...)`. In `web/src/lib/hooks/useTeacherApi.ts` delete `extractPaper` and `gradePaper`; run `npm run typecheck` in `web/` to confirm no caller. Delete the two rows from `tests/test_authz_matrix_complete.py` and lower the `- 10` in `test_the_sweeps_actually_cover_the_surface` only if the two were counted there (they are STAFF routes, so the public count is unchanged — leave it).

- [ ] **Step 4: Run to verify they pass**

`pytest tests/test_web_teacher.py tests/test_authz_matrix_complete.py tests/test_teacher_paper_repo.py -q` → PASS. `grep -rn "papers_store\|_PaperEntry\|lemely.web.jobs\|registry" lemely tests` → no matches (the `DeviceRegistry` name is unrelated; check the grep output by eye).

- [ ] **Step 5: pre-commit, then commit**

```
pre-commit run --all-files
git commit -S -m "feat(teacher): papers live in Postgres and object storage; drop the in-process stores

The grading console reads and writes teacher_papers through
TeacherPaperRepository and stores scans behind the StorageBackend seam. The
job registry, _PaperStore, the process lock and the two SSE routes nothing
called (DS14) are deleted. A run is claimed with one conditional UPDATE, so
a regrade from any instance runs a paper once; a stale processing row is
shown as failed with a retry."
```

---

## Stage C — the scheme corpus (spec §4.3; rollout step 3)

## Task 7: `SchemeCorpusRepository`

**Files:**
- Create: `lemely/db/scheme_corpus_repo.py`
- Modify: `lemely/db/question_bank_repo.py` (make `_resolve_paper` and `_PaperIdentity` importable as `resolve_paper`, `PaperIdentity` — rename, keep the old names as aliases)
- Test: `tests/test_scheme_corpus_repo.py`

**Interfaces:**
- Produces:

```python
@dataclass(frozen=True, slots=True)
class SchemeCorpusRow:
    id: uuid.UUID
    doc: str                    # basename of source_document, or "<paper label>.json" when None
    paper_number: int
    paper_variant: int
    session_month: SessionMonth
    session_year: int | None
    maximum_mark: int
    question_count: int
    created_at: datetime

class SchemeCorpusRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None: ...
    def store(self, scheme: MarkScheme, *, provenance: str) -> uuid.UUID | None: ...   # None: no subject taxonomy
    def set_source_document(self, scheme_id: uuid.UUID, key: str) -> None: ...
    def list_rows(self) -> list[SchemeCorpusRow]: ...
    def find_for(self, metadata: ExamMetadata) -> MarkScheme | None: ...
```

Consumed by Task 8.

- [ ] **Step 1: Write the failing tests**

`tests/test_scheme_corpus_repo.py` (fixture copied; `_scheme(subject="0625", paper=1, variant=1, month="May/June", year=2023)` builds a `MarkScheme` with two questions the way `tests/test_web_teacher.py` builds one):

```python
def test_store_then_find_by_detected_metadata(pg_sessionmaker) -> None:
    repo = SchemeCorpusRepository(pg_sessionmaker)
    sid = repo.store(_scheme(), provenance="teacher_upload:deterministic")
    assert sid is not None
    found = repo.find_for(ExamMetadata(subject_code="0625", paper_number=1, paper_variant=1, session_month="May/June", session_year=2023))
    assert found is not None and len(found.questions) == 2


def test_store_replaces_the_row_for_the_same_paper(pg_sessionmaker) -> None:
    repo = SchemeCorpusRepository(pg_sessionmaker)
    first = repo.store(_scheme(), provenance="a")
    second = repo.store(_scheme(), provenance="b")
    assert first == second
    assert len(repo.list_rows()) == 1


def test_find_without_year_prefers_the_newest(pg_sessionmaker) -> None:
    repo = SchemeCorpusRepository(pg_sessionmaker)
    repo.store(_scheme(year=2022), provenance="x")
    repo.store(_scheme(year=2023), provenance="x")
    found = repo.find_for(ExamMetadata(subject_code="0625", paper_number=1, paper_variant=1, session_month="May/June", session_year=None))
    assert found is not None and found.metadata.session_year == 2023


def test_unknown_subject_is_not_stored(pg_sessionmaker) -> None:
    repo = SchemeCorpusRepository(pg_sessionmaker)
    assert repo.store(_scheme(subject="9999"), provenance="x") is None
    assert repo.list_rows() == []
```

- [ ] **Step 2: Run to verify they fail** — `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

```python
class SchemeCorpusRepository:
    """The parsed mark-scheme corpus on ``papers``/``mark_schemes`` (spec §4.3, DS5)."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._sm = session_factory

    def store(self, scheme: MarkScheme, *, provenance: str) -> uuid.UUID | None:
        """Insert or replace the ``mark_schemes`` row for the scheme's paper; ``None`` if the subject has no taxonomy."""
        identity = _identity_from(scheme.metadata)
        if identity is None:
            return None
        with self._sm.begin() as session:
            resolved = resolve_paper(session, identity)
            if resolved is None:
                return None
            paper_id, _created = resolved
            existing = session.scalars(select(MarkSchemeRecord).where(MarkSchemeRecord.paper_id == paper_id)).one_or_none()
            payload = scheme.model_dump(mode="json")
            maximum = sum(q.maximum_marks for q in scheme.questions)
            if existing is None:
                existing = MarkSchemeRecord(paper_id=paper_id, maximum_mark=maximum, parsed_payload=payload, provenance=provenance)
                session.add(existing)
                session.flush()
            else:
                existing.maximum_mark = maximum
                existing.parsed_payload = payload
                existing.provenance = provenance
            return existing.id

    def set_source_document(self, scheme_id: uuid.UUID, key: str) -> None:
        with self._sm.begin() as session:
            row = session.get(MarkSchemeRecord, scheme_id)
            if row is not None:
                row.source_document = key

    def list_rows(self) -> list[SchemeCorpusRow]:
        stmt = select(MarkSchemeRecord, Paper).join(Paper, Paper.id == MarkSchemeRecord.paper_id).order_by(MarkSchemeRecord.created_at.desc())
        with self._sm() as session:
            return [_row(ms, paper) for ms, paper in session.execute(stmt)]

    def find_for(self, metadata: ExamMetadata) -> MarkScheme | None:
        month = _SESSION_MONTH_BY_LABEL.get(metadata.session_month)
        conditions = [Paper.subject_code == metadata.subject_code, Paper.paper_number == metadata.paper_number, Paper.paper_variant == metadata.paper_variant]
        if month is not None:
            conditions.append(Paper.session_month == month)
        if metadata.session_year is not None:
            conditions.append(Paper.session_year == metadata.session_year)
        stmt = (
            select(MarkSchemeRecord).join(Paper, Paper.id == MarkSchemeRecord.paper_id)
            .where(*conditions).order_by(Paper.session_year.desc().nulls_last(), MarkSchemeRecord.created_at.desc()).limit(1)
        )
        with self._sm() as session:
            row = session.scalars(stmt).one_or_none()
            return None if row is None else MarkScheme.model_validate(row.parsed_payload)
```

`_identity_from(meta: ExamMetadata) -> PaperIdentity | None` maps `meta.session_month` through the label map and fills `board=ExamBoard.caie`. `_SESSION_MONTH_BY_LABEL` is the inverse of `SESSION_MONTH_LABELS` (derive it here the same way `question_bank_repo` does). `resolve_paper` is the renamed `_resolve_paper`; it already creates the `subjects` row from the bundled taxonomy and returns `None` when there is none. `MarkSchemeRecord` is `lemely.db.models.academic.MarkScheme` imported under that alias, as `question_bank_repo` does. `_row` builds `SchemeCorpusRow` with `question_count = len(parsed_payload["questions"])`, `doc = Path(source_document).name if source_document else f"{subject}_{paper}{variant}.json"`.

- [ ] **Step 4: Run to verify they pass** — `pytest tests/test_scheme_corpus_repo.py tests/test_question_bank_repo.py -q`.

- [ ] **Step 5: pre-commit, then commit** — `feat(db): SchemeCorpusRepository on papers/mark_schemes`.

---

## Task 8: Scheme routes and the shared resolver on the corpus

**Files:**
- Modify: `lemely/web/routers/teacher.py` (`_schemes_dir`, `_load_scheme`, `_scheme_row`, `list_schemes`, `upload_scheme`; the `corpus` parameter of `_run_grading_job` becomes required)
- Modify: `lemely/web/routers/student.py:731-800` (`_metadata_matches` deleted; `resolve_mark_scheme` new signature; the `student_correct` run closure passes the sibling path and the corpus)
- Modify: `lemely/web/deps.py` (`get_scheme_corpus_repo`)
- Test: `tests/test_web_teacher.py` (scheme tests), `tests/test_student_correct.py` (resolver tests)

**Interfaces:**
- Produces `resolve_mark_scheme(sibling_scheme: Path | None, corpus: SchemeCorpusRepository, settings, gemini_client, *, metadata: ExamMetadata | None) -> MarkScheme | None` in `routers/student.py`. Consumed by both portals.
- Produces `get_scheme_corpus_repo() -> SchemeCorpusRepository`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_web_teacher.py`, replace the `/schemes` tests that assert on `schemes_dir` files with:

```python
def test_upload_scheme_persists_row_and_pdf(client, corpus_repo, storage_backend, scheme_pdf_bytes) -> None:
    resp = client.post("/api/schemes", files={"scheme_pdf": ("0625_s23_ms_11.pdf", scheme_pdf_bytes, "application/pdf")})
    assert resp.status_code == 200
    rows = corpus_repo.list_rows()
    assert len(rows) == 1 and rows[0].doc == "0625_s23_ms_11.pdf"
    keys = [k for (_b, k) in storage_backend._objects]
    assert keys == [f"schemes/{rows[0].id}/0625_s23_ms_11.pdf"]
    listing = client.get("/api/schemes").json()
    assert [s["key"] for s in listing["stats"]] == ["Parsed"]
    assert listing["stats"][0]["value"] == "1"
```

`scheme_pdf_bytes` is the fixture the existing scheme-upload test already uses (a real parseable scheme from `Sources/`; keep it). Add a `corpus_repo` fixture (`SchemeCorpusRepository(pg_sessionmaker)`) overriding `get_scheme_corpus_repo`. In `tests/test_student_correct.py` add:

```python
def test_resolver_prefers_sibling_then_corpus(tmp_path, corpus_repo, settings, gemini_client) -> None:
    corpus_repo.store(_scheme(), provenance="t")
    meta = ExamMetadata(subject_code="0625", paper_number=1, paper_variant=1, session_month="May/June", session_year=2023)
    assert resolve_mark_scheme(None, corpus_repo, settings, gemini_client, metadata=meta) is not None
    assert resolve_mark_scheme(None, corpus_repo, settings, gemini_client, metadata=None) is None
```

- [ ] **Step 2: Run to verify they fail.**

- [ ] **Step 3: Implement**

`upload_scheme`:

```python
    pdf_bytes = await scheme_pdf.read()
    check_upload_cap(pdf_bytes, max_bytes=_MAX_UPLOAD_BYTES)
    filename = _safe_upload_name(scheme_pdf.filename, "scheme.pdf")
    with tempfile.TemporaryDirectory() as tmp:
        pdf_path = Path(tmp) / filename
        pdf_path.write_bytes(pdf_bytes)
        try:
            scheme = DeterministicMarkSchemeParser(cfg=settings.det_parser)(pdf_path)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"Mark scheme parse failed: {exc}") from exc
    scheme_id = corpus.store(scheme, provenance="teacher_upload:deterministic")
    if scheme_id is None:
        raise HTTPException(status_code=422, detail=f"No bundled syllabus for subject {scheme.metadata.subject_code}; cannot file this scheme.")
    key = f"schemes/{scheme_id}/{filename}"
    storage.upload(settings.storage.bucket, key, pdf_bytes, scheme_pdf.content_type)
    corpus.set_source_document(scheme_id, key)
    return _scheme_row_dto(next(r for r in corpus.list_rows() if r.id == scheme_id))
```

`list_schemes` returns `SchemeListDTO(schemes=[_scheme_row_dto(r) for r in corpus.list_rows()], stats=[StatCardDTO(key="Parsed", value=str(len(rows)), unit="schemes")])` — the "Failed" card goes (nothing on disk can fail to load any more). `_scheme_row_dto` maps `SchemeCorpusRow` to `SchemeRowDTO` using `_session_label(SESSION_MONTH_LABELS[row.session_month], row.session_year)`, `maxMarks=row.maximum_mark`, `questionCount=row.question_count`, `status="parsed"`. Delete `_schemes_dir`, `_load_scheme`, `_scheme_row`.

`resolve_mark_scheme` in `student.py`:

```python
def resolve_mark_scheme(
    sibling_scheme: Path | None,
    corpus: SchemeCorpusRepository,
    settings: Settings,
    gemini_client: GeminiClient,
    *,
    metadata: ExamMetadata | None,
) -> MarkScheme | None:
    """Sibling PDF first (deterministic parser with Gemini fallback), then the corpus by detected metadata."""
    if sibling_scheme is not None:
        from lemely.io.det import DeterministicMarkSchemeParser

        parser = ChainedMarkSchemeParser(
            DeterministicMarkSchemeParser(cfg=settings.det_parser), GeminiMarkSchemeParser(gemini_client)
        )
        return parser(sibling_scheme)
    if metadata is None:
        return None
    return corpus.find_for(metadata)
```

Delete `_metadata_matches`. In `student_correct`'s `run()`, the sibling download already lands at `tmp_path / "mark_scheme.pdf"`; pass that path (or `None` when `StorageObjectNotFoundError`) and the injected `corpus` dependency. In `teacher.py`'s `_run_grading_job`, the call becomes `resolve_mark_scheme(sibling, corpus, settings, gemini_client, metadata=metadata)` and `corpus` is now required (`_start_run_if_claimed`, `upload_paper` and `regrade_paper` gain the dependency). `write_upload_capped` in `lemely/web/upload_utils.py` has no caller left after this task — delete it and its test.

In `lemely/web/deps.py`:

```python
@lru_cache(maxsize=1)
def get_scheme_corpus_repo() -> SchemeCorpusRepository:
    """Return the process-wide :class:`SchemeCorpusRepository` singleton (spec §4.3)."""
    return SchemeCorpusRepository(get_sessionmaker(get_settings()))
```

with `get_scheme_corpus_repo.cache_clear()` added to `reset_singletons`.

- [ ] **Step 4: Run to verify they pass** — `pytest tests/test_web_teacher.py tests/test_student_correct.py tests/test_scheme_corpus_repo.py -q`. `grep -rn '"schemes"' lemely/web` → no `output_dir / "schemes"` left.

- [ ] **Step 5: pre-commit, then commit** — `feat(schemes): the parsed corpus lives in mark_schemes; matching is a query (DS5)`.

---

## Stage D — auth stores and email verification by code (spec §4.4; rollout step 4)

## Task 9: Migration `0025` — `otp_challenges`; channel-aware `OtpStore`

**Files:**
- Modify: `lemely/auth/otp.py` (`OtpChannel`, `OtpChallengeStore` Protocol, channel + per-channel TTL on `OtpStore`)
- Create: `lemely/db/models/otp_challenges.py`; register in `lemely/db/models/__init__.py`
- Create: `lemely/db/migrations/versions/0025_otp_challenges.py`
- Modify: `lemely/runtime/config.py` (`AuthSettings.email_otp_ttl_seconds: int = Field(default=600, ge=60)`)
- Test: `tests/test_otp.py`, `tests/test_db_schema.py`

**Interfaces:**
- Produces `OtpChannel(Enum)` with `phone = "phone"`, `email = "email"`.
- Produces `OtpChallengeStore` Protocol: `issue(address: str, *, channel: OtpChannel = OtpChannel.phone) -> str`, `verify(address: str, code: str, *, channel: OtpChannel = OtpChannel.phone) -> OtpResult`.
- Produces `OtpStore(..., email_ttl_seconds: int = 600)`; the dict key becomes `(channel, address)`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_otp.py`:

```python
def test_channels_are_independent_and_email_has_its_own_ttl() -> None:
    clock = _FrozenClock(datetime(2026, 9, 3, tzinfo=UTC))
    store = OtpStore(clock=clock, rng=random.Random(1), ttl_seconds=300, email_ttl_seconds=600, min_resend_seconds=0)
    phone_code = store.issue("+201000000000")
    email_code = store.issue("a@example.com", channel=OtpChannel.email)
    assert store.verify("a@example.com", phone_code, channel=OtpChannel.email) is OtpResult.wrong_code
    clock.advance(400)
    assert store.verify("+201000000000", phone_code) is OtpResult.expired
    assert store.verify("a@example.com", email_code, channel=OtpChannel.email) is OtpResult.ok
```

Add to `tests/test_db_schema.py` a `test_otp_challenge_row_round_trip` that inserts an `OtpChallenge(channel=OtpChannel.email, address_hash="a"*64, code_hash="b"*64, expires_at=..., issued_at=...)` and reads it back.

- [ ] **Step 2: Run to verify they fail.**

- [ ] **Step 3: Implement the in-memory side**

In `lemely/auth/otp.py` add:

```python
class OtpChannel(Enum):
    """Where a challenge's code is delivered; part of the challenge's identity."""

    phone = "phone"
    email = "email"


class OtpChallengeStore(Protocol):
    """Issue and verify single-use codes, keyed by (channel, address)."""

    def issue(self, address: str, *, channel: OtpChannel = OtpChannel.phone) -> str: ...
    def verify(self, address: str, code: str, *, channel: OtpChannel = OtpChannel.phone) -> OtpResult: ...
```

On `OtpStore`: constructor gains `email_ttl_seconds: int = 600`; `_challenges: dict[tuple[OtpChannel, str], OtpChallenge]`; `issue`/`verify` gain the keyword and use `self._ttl_for(channel)`; every existing positional call site (`AuthService.request_otp`/`verify_otp`, seed, tests) is unchanged.

- [ ] **Step 4: Model and migration**

`lemely/db/models/otp_challenges.py`: `OtpChallenge(Base)` with `channel` (`sa.Enum(OtpChannel, name="otpchannel")`, PK), `address_hash` (String, PK), `code_hash` (String, not null), `expires_at`, `issued_at` (DateTime tz, not null), `attempts` (Integer, not null, server default `0`). No `TimestampMixin` — `issued_at` is the timestamp.

`0025_otp_challenges.py`: `down_revision = "0024_teacher_papers"`; `op.create_table` with `sa.Enum("phone", "email", name="otpchannel")`, composite `PrimaryKeyConstraint("channel", "address_hash", name=op.f("pk_otp_challenges"))`; `downgrade` drops the table then `op.execute("DROP TYPE otpchannel")` — the 0023 trap, documented in the docstring.

- [ ] **Step 5: Run, both migration directions, then commit**

```
pytest tests/test_otp.py tests/test_db_schema.py -q
alembic upgrade head && alembic downgrade -1 && alembic upgrade head
pre-commit run --all-files
git commit -S -m "feat(auth): channel-aware OTP challenges (migration 0025)"
```

---

## Task 10: `DbOtpStore`, and the parity suite

**Files:**
- Create: `lemely/db/otp_repo.py`
- Modify: `lemely/web/deps.py:202-214` (`get_auth_service` builds `DbOtpStore`)
- Test: `tests/test_otp_store_parity.py`

**Interfaces:**
- Produces `DbOtpStore(session_factory, *, clock, rng, ttl_seconds, email_ttl_seconds, max_attempts, code_length, min_resend_seconds)` satisfying `OtpChallengeStore`.

- [ ] **Step 1: Write the failing parity tests**

`tests/test_otp_store_parity.py` — the cases in `tests/test_otp.py` that matter across processes, parametrised over both implementations:

```python
@pytest.fixture(params=["memory", "postgres"])
def store(request, pg_sessionmaker_or_skip, clock) -> OtpChallengeStore:
    kwargs = dict(clock=clock, rng=random.Random(7), ttl_seconds=300, email_ttl_seconds=600, max_attempts=3, code_length=6, min_resend_seconds=30)
    if request.param == "memory":
        return OtpStore(**kwargs)
    return DbOtpStore(pg_sessionmaker_or_skip, **kwargs)


PHONE = "+201000000000"


def test_issue_then_verify_consumes(store, clock) -> None:
    code = store.issue(PHONE)
    assert store.verify(PHONE, code) is OtpResult.ok
    assert store.verify(PHONE, code) is OtpResult.no_challenge


def test_wrong_code_counts_and_locks_out_after_max(store, clock) -> None:
    code = store.issue(PHONE)
    assert store.verify(PHONE, "000000") is OtpResult.wrong_code
    assert store.verify(PHONE, "000000") is OtpResult.wrong_code
    assert store.verify(PHONE, "000000") is OtpResult.locked_out   # max_attempts=3
    assert store.verify(PHONE, code) is OtpResult.no_challenge


def test_expired_challenge_is_reported_and_removed(store, clock) -> None:
    code = store.issue(PHONE)
    clock.advance(301)
    assert store.verify(PHONE, code) is OtpResult.expired
    assert store.verify(PHONE, code) is OtpResult.no_challenge


def test_resend_inside_cooldown_raises(store, clock) -> None:
    store.issue(PHONE)
    with pytest.raises(OtpRateLimitError):
        store.issue(PHONE)
    clock.advance(31)
    store.issue(PHONE)  # cooldown elapsed: a fresh challenge


def _db_store(sm, clock, **overrides) -> DbOtpStore:
    kwargs = dict(clock=clock, rng=random.Random(7), ttl_seconds=300, email_ttl_seconds=600, max_attempts=3, code_length=6, min_resend_seconds=0)
    kwargs.update(overrides)
    return DbOtpStore(sm, **kwargs)


def test_code_is_never_stored_in_plaintext(pg_sessionmaker_or_skip, clock):
    store = _db_store(pg_sessionmaker_or_skip, clock)
    code = store.issue("+201000000000")
    with pg_sessionmaker_or_skip() as s:
        row = s.scalars(select(OtpChallenge)).one()
    assert code not in (row.code_hash, row.address_hash)
    assert row.address_hash == hashlib.sha256(b"+201000000000").hexdigest()


def test_two_concurrent_verifies_yield_one_ok(pg_sessionmaker_or_skip, clock):
    store = _db_store(pg_sessionmaker_or_skip, clock)
    code = store.issue("+201000000000")
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: store.verify("+201000000000", code), range(2)))
    assert sorted(r.value for r in results) == ["no_challenge", "ok"]
```

`pg_sessionmaker_or_skip` is the standard fixture under a name that makes the memory param not require Postgres: for `memory` it is unused, so implement the fixture to skip only when `request.param == "postgres"` and no server is reachable.

- [ ] **Step 2: Run to verify they fail.**

- [ ] **Step 3: Implement**

`lemely/db/otp_repo.py`:

```python
class DbOtpStore:
    """Postgres-backed :class:`OtpChallengeStore` (spec §4.4, DS4)."""

    def __init__(self, session_factory, *, clock, rng, ttl_seconds=300, email_ttl_seconds=600, max_attempts=5, code_length=6, min_resend_seconds=30) -> None: ...

    def issue(self, address: str, *, channel: OtpChannel = OtpChannel.phone) -> str:
        now = self._clock()
        key = _hash(address)
        with self._sm.begin() as session:
            session.execute(sa.delete(OtpChallenge).where(OtpChallenge.expires_at < now))  # opportunistic sweep
            row = session.execute(
                select(OtpChallenge).where(OtpChallenge.channel == channel, OtpChallenge.address_hash == key).with_for_update()
            ).scalar_one_or_none()
            if row is not None and now < row.expires_at and now - row.issued_at < self._min_resend:
                remaining = int((self._min_resend - (now - row.issued_at)).total_seconds())
                raise OtpRateLimitError(f"OTP already sent; retry in {remaining}s.")
            code = self._generate_code()
            if row is None:
                session.add(OtpChallenge(channel=channel, address_hash=key, code_hash=_hash(code), expires_at=now + self._ttl_for(channel), issued_at=now, attempts=0))
            else:
                row.code_hash, row.expires_at, row.issued_at, row.attempts = _hash(code), now + self._ttl_for(channel), now, 0
        return code

    def verify(self, address: str, code: str, *, channel: OtpChannel = OtpChannel.phone) -> OtpResult:
        now = self._clock()
        key = _hash(address)
        with self._sm.begin() as session:
            row = session.execute(
                select(OtpChallenge).where(OtpChallenge.channel == channel, OtpChallenge.address_hash == key).with_for_update()
            ).scalar_one_or_none()
            if row is None:
                return OtpResult.no_challenge
            if now >= row.expires_at:
                session.delete(row)
                return OtpResult.expired
            if hmac.compare_digest(row.code_hash, _hash(code)):
                session.delete(row)
                return OtpResult.ok
            row.attempts += 1
            if row.attempts >= self._max_attempts:
                session.delete(row)
                return OtpResult.locked_out
            return OtpResult.wrong_code
```

`_hash(s) = hashlib.sha256(s.encode()).hexdigest()`. `SELECT ... FOR UPDATE` serialises the two concurrent verifies: the second waits, then sees no row. Wire it in `get_auth_service`:

```python
    otp_store = DbOtpStore(
        get_sessionmaker(settings),
        clock=lambda: datetime.now(UTC), rng=random.SystemRandom(),
        ttl_seconds=settings.auth.otp_ttl_seconds, email_ttl_seconds=settings.auth.email_otp_ttl_seconds,
        max_attempts=settings.auth.otp_max_attempts, code_length=settings.auth.otp_length,
        min_resend_seconds=settings.auth.otp_min_resend_seconds,
    )
```

`AuthService.__init__`'s `otp_store` annotation becomes `OtpChallengeStore`. `lemely/db/seed.py` keeps the in-memory `OtpStore`.

- [ ] **Step 4: Run to verify they pass** — `pytest tests/test_otp_store_parity.py tests/test_otp.py tests/test_auth_service.py tests/test_web_auth.py -q`.

- [ ] **Step 5: pre-commit, then commit** — `feat(auth): Postgres-backed OTP challenge store, at parity with the in-memory one`.

---

## Task 11: Migration `0026` — `auth_cooldowns`; `DbCooldownStore`

**Files:**
- Modify: `lemely/auth/cooldown.py` (`CooldownStoreProtocol`)
- Create: `lemely/db/models/auth_cooldowns.py`; register; `lemely/db/migrations/versions/0026_auth_cooldowns.py`
- Create: `lemely/db/cooldown_repo.py`
- Modify: `lemely/web/deps.py:158-186` (both factories build `DbCooldownStore`); `lemely/web/routers/auth.py` type hints to the Protocol
- Test: `tests/test_cooldown_store_parity.py`, `tests/test_db_schema.py`

**Interfaces:**
- Produces `CooldownStoreProtocol` with `check_and_stamp(key: str) -> None`.
- Produces `DbCooldownStore(session_factory, *, clock, purpose: str, min_seconds: int)`.

- [ ] **Step 1: Write the failing tests** — `tests/test_cooldown_store_parity.py` parametrises the six cases of `tests/test_auth_cooldown.py` over `CooldownStore` and `DbCooldownStore(purpose="resend_verification")`, plus:

```python
def test_purposes_do_not_interfere(pg_sessionmaker_or_skip, clock):
    a = DbCooldownStore(pg_sessionmaker_or_skip, clock=clock, purpose="signup_and_reset", min_seconds=30)
    b = DbCooldownStore(pg_sessionmaker_or_skip, clock=clock, purpose="resend_verification", min_seconds=30)
    a.check_and_stamp("x@example.com")
    b.check_and_stamp("x@example.com")  # different purpose: passes


def test_key_is_stored_hashed(pg_sessionmaker_or_skip, clock):
    store = DbCooldownStore(pg_sessionmaker_or_skip, clock=clock, purpose="signup_and_reset", min_seconds=30)
    store.check_and_stamp("x@example.com")
    with pg_sessionmaker_or_skip() as s:
        row = s.scalars(select(AuthCooldown)).one()
    assert row.key_hash == hashlib.sha256(b"x@example.com").hexdigest()
```

- [ ] **Step 2: Run to verify they fail.**

- [ ] **Step 3: Implement**

Model: `AuthCooldown(Base)` with `purpose` (String, PK), `key_hash` (String, PK), `stamped_at` (DateTime tz, not null). Migration `0026_auth_cooldowns` (`down_revision = "0025_otp_challenges"`), table with composite PK; downgrade drops the table; no enum.

`DbCooldownStore.check_and_stamp`:

```python
    def check_and_stamp(self, key: str) -> None:
        now = self._clock()
        cutoff = now - self._min_interval
        stmt = (
            pg_insert(AuthCooldown)
            .values(purpose=self._purpose, key_hash=_hash(key), stamped_at=now)
            .on_conflict_do_update(
                index_elements=[AuthCooldown.purpose, AuthCooldown.key_hash],
                set_={"stamped_at": now},
                where=AuthCooldown.stamped_at < cutoff,
            )
            .returning(AuthCooldown.stamped_at)
        )
        with self._sm.begin() as session:
            stamped = session.execute(stmt).scalar_one_or_none()
            if stamped is not None:
                return
            last = session.execute(
                select(AuthCooldown.stamped_at).where(AuthCooldown.purpose == self._purpose, AuthCooldown.key_hash == _hash(key))
            ).scalar_one()
        raise CooldownError(key, (self._min_interval - (now - last)).total_seconds())
```

(`from sqlalchemy.dialects.postgresql import insert as pg_insert`.) The two `deps.py` factories become `DbCooldownStore(get_sessionmaker(settings), clock=..., purpose="signup_and_reset", min_seconds=...)` and `purpose="resend_verification"`.

- [ ] **Step 4: Run, both migration directions, then commit** — `feat(auth): Postgres-backed cooldowns (migration 0026)`.

---

## Task 12: Email verification by code — service, DTOs, route

**Files:**
- Modify: `lemely/auth/email.py` (`send_verification(email, link, code)`), `tests/auth_fakes.py::FakeEmailProvider` (record `(email, link, code)`)
- Modify: `lemely/auth/service.py` (`AuthResult.verification_dev_code`; `signup`, `resend_verification` issue a code; new `verify_email_code`; `_try_send_verification(email, link, code)`; `_dev_code_for(code)`)
- Modify: `lemely/web/schemas_auth.py` (`devCode` on `TokenResponseDTO` and `ResendVerificationResponseDTO`; `VerifyEmailCodeRequestDTO`)
- Modify: `lemely/web/routers/auth.py` (`_to_token_dto` maps `devCode`; `resend_verification` returns both; new route)
- Modify: `tests/test_authz_matrix_complete.py` (add `("POST", "/api/auth/verify-email/code"): AUTH_ANY`)
- Test: `tests/test_auth_service.py`, `tests/test_web_auth.py`

**Interfaces:**
- Produces `AuthService.verify_email_code(user_id: uuid.UUID, code: str) -> uuid.UUID` (raises `AuthError`).
- Produces `AuthService.resend_verification(user_id) -> tuple[str | None, str | None]` (dev link, dev code).
- Produces route `POST /api/auth/verify-email/code`, body `{"code": str}`, `VerifyEmailResponseDTO`, authenticated (any role).

- [ ] **Step 1: Write the failing tests**

`tests/test_auth_service.py`:

```python
def test_signup_issues_link_and_code_and_returns_both_dev_values(service_with_email) -> None:
    service, email_provider, otp_store = service_with_email
    result = service.signup("s@example.com", "pw-123456", Role.student, accepted_terms=True)
    assert result.verification_dev_link is not None
    assert result.verification_dev_code is not None
    assert email_provider.sent_verifications == [("s@example.com", result.verification_dev_link, result.verification_dev_code)]


def test_verify_email_code_stamps_verified_and_is_single_use(service_with_email) -> None:
    service, _e, _o = service_with_email
    result = service.signup("s@example.com", "pw-123456", Role.student, accepted_terms=True)
    assert service.verify_email_code(result.user_id, result.verification_dev_code) == result.user_id
    with pytest.raises(AuthError):
        service.verify_email_code(result.user_id, result.verification_dev_code)


def test_wrong_code_five_times_locks(service_with_email) -> None:
    service, _e, _o = service_with_email
    result = service.signup("s@example.com", "pw-123456", Role.student, accepted_terms=True)
    for _ in range(5):
        with pytest.raises(AuthError):
            service.verify_email_code(result.user_id, "000000")
    with pytest.raises(AuthError, match="no_challenge|locked_out"):
        service.verify_email_code(result.user_id, result.verification_dev_code)


def test_link_still_verifies_after_code_was_used(service_with_email) -> None:
    """The two credentials are independent; verification is idempotent (spec §4.4)."""
    service, _e, _o = service_with_email
    result = service.signup("s@example.com", "pw-123456", Role.student, accepted_terms=True)
    service.verify_email_code(result.user_id, result.verification_dev_code)
    token = result.verification_dev_link.rsplit("/", 1)[1]
    assert service.verify_email(token) == result.user_id  # no error, same user


def test_dev_code_is_none_when_provider_delivers(service_with_delivering_email) -> None:
    """D3.16 applied to the code: a real provider never leaks it back through the API."""
    service, email_provider, _o = service_with_delivering_email
    assert email_provider.delivers_out_of_band is True
    result = service.signup("s@example.com", "pw-123456", Role.student, accepted_terms=True)
    assert result.verification_dev_link is None
    assert result.verification_dev_code is None
    (_addr, _link, code), = email_provider.sent_verifications
    assert len(code) == 6  # it was still issued and handed to the provider
```

`service_with_email` builds `AuthService` exactly as the module's existing email fixtures do (`FakeGoTrueBackend`, `FakeUserMirror`, `MockSmsProvider`, in-memory `OtpStore(min_resend_seconds=0, max_attempts=5)`, `FakeEmailProvider`, `FakeAuthTokenService`). `tests/test_web_auth.py`:

```python
def test_verify_email_code_route(context) -> None:
    client, service, mirror = context
    signup = client.post("/api/auth/signup", json={...}).json()
    headers = {"Authorization": f"Bearer {signup['accessToken']}"}
    assert signup["devCode"] is not None
    assert client.post("/api/auth/verify-email/code", json={"code": "000000"}, headers=headers).status_code == 400
    assert client.post("/api/auth/verify-email/code", json={"code": signup["devCode"]}, headers=headers).status_code == 200
    assert mirror.get_by_id(uuid.UUID(signup["userId"])).email_verified_at is not None


def test_verify_email_code_requires_a_session(context) -> None:
    client, _s, _m = context
    assert client.post("/api/auth/verify-email/code", json={"code": "123456"}).status_code == 401
```

- [ ] **Step 2: Run to verify they fail.**

- [ ] **Step 3: Implement**

`EmailProvider.send_verification(self, email: str, link: str, code: str) -> None`; `MockEmailProvider` logs `"Mock email to %s: verify at %s or enter code %s"`. `FakeEmailProvider.sent_verifications: list[tuple[str, str, str]]`.

`AuthService`:

```python
    def _issue_email_code(self, email: str) -> str:
        return self._otp_store.issue(email, channel=OtpChannel.email)

    def _dev_code_for(self, code: str) -> str | None:
        delivers = self._email.delivers_out_of_band if self._email is not None else False
        return None if delivers else code
```

In `signup`, beside the link: `code = self._issue_email_code(created.email)`; `self._try_send_verification(created.email, link, code)`; `verification_dev_code=self._dev_code_for(code)` on the `AuthResult`. `resend_verification` returns `(self._dev_link_for(link), self._dev_code_for(code))`.

```python
    def verify_email_code(self, user_id: uuid.UUID, code: str) -> uuid.UUID:
        """Verify the caller's email by the code sent beside the link (DS15).

        The address is the caller's own, from the mirror — never a body field —
        so this cannot probe or verify another address. Every failure collapses
        into one ``AuthError`` (same non-revealing rule as :meth:`verify_email`).
        """
        user = self._mirror.get_by_id(user_id)
        if user is None:
            raise AuthError("Unknown user.")
        result = self._otp_store.verify(user.email, code, channel=OtpChannel.email)
        if result is not OtpResult.ok:
            raise AuthError(f"Email verification failed: {result.value}")
        self._mirror.mark_email_verified(user_id, verified_at=_utcnow())
        return user_id
```

DTOs: `TokenResponseDTO.devCode: str | None = None`, `ResendVerificationResponseDTO.devCode: str | None = None`, `VerifyEmailCodeRequestDTO(code: str)`. Route:

```python
@router.post("/auth/verify-email/code", response_model=VerifyEmailResponseDTO)
def verify_email_code(
    body: VerifyEmailCodeRequestDTO,
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> VerifyEmailResponseDTO:
    """Verify the **authenticated caller's** email by code (DS15). 400 on any failure."""
    try:
        service.verify_email_code(uuid.UUID(auth.user_id), body.code)
    except AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return VerifyEmailResponseDTO()
```

`_to_token_dto` maps `devCode=result.verification_dev_code`; `resend_verification` unpacks the tuple into `ResendVerificationResponseDTO(devLink=..., devCode=...)`. Authorization matrix: add the row under `AUTH_ANY`; it is not public, so the `- 10` count is unchanged.

- [ ] **Step 4: Run to verify they pass** — `pytest tests/test_auth_service.py tests/test_web_auth.py tests/test_auth_router.py tests/test_authz_matrix_complete.py -q`.

- [ ] **Step 5: pre-commit, then commit** — `feat(auth): email verification by typed code alongside the link (DS15)`.

---

## Task 13: G-07 accepts a code (frontend)

Precise specification; build against `DESIGN.md` and the existing kit.

**Files:**
- Modify: `web/src/lib/authTypes.ts` (`devCode: string | null` on `TokenResponse` and `ResendVerificationResponse`; `VerifyEmailCodeBody { code: string }`)
- Modify: `web/src/lib/auth/AuthContext.tsx` (`verifyEmailCode: UseMutationResult<VerifyEmailResponse, Error, { code: string }>` posting to `/auth/verify-email/code`; add to `AuthContextValue` and the provider value)
- Modify: `web/src/portals/auth/VerifyEmail.tsx` (`SignedInPending` only), `web/src/portals/auth/verifyEmailLogic.ts`, `web/src/portals/auth/verifyEmail.test.ts`
- Modify: `web/e2e/signup.spec.ts`

**Acceptance:**
- `SignedInPending` gains, above the resend control, a labelled six-digit code field (`inputMode="numeric"`, `autoComplete="one-time-code"`, `maxLength={6}`, `id="verify-code"`) and a "Verify code" button, disabled until six digits are present or while the mutation is pending. On success it navigates to `postVerifyPath(session)`; on error it renders `verificationFailureMessage(err)` in the existing `role="status"` slot. No raw `error.message`.
- `DevLinkPanel` becomes `DevPanel({ link, code })`, rendering the code in a `text-data-md` span next to the existing anchor, labelled "Code" — only when `devCode !== null`. `ResendOutcome` gains `code: string | null` on its `devLink` variant.
- `verifyEmailLogic.ts` gains `canSubmitCode(code: string, isPending: boolean): boolean` (`/^\d{6}$/` and not pending) with vitest cases in `verifyEmail.test.ts`: five digits false, six digits true, six digits while pending false, non-digits false.
- `web/e2e/signup.spec.ts`: after the existing resend step, a new test signs up, clicks resend, reads the dev code from the panel, types it into `#verify-code`, clicks "Verify code", and expects the URL to leave `/verify-email` for the student portal. The existing link-based test is kept.
- Copy: the field label is "Verification code"; helper text "Enter the 6-digit code from the email, or open the link." Logical CSS only.

- [ ] Run `npm run typecheck && npm run test && npx playwright test e2e/signup.spec.ts` in `web/`; all green.
- [ ] pre-commit, then commit — `feat(web): G-07 verifies by code as well as link`.

---

## Stage E — per-run event scoping (spec §4.5; rollout step 5)

## Task 14: The bus gains a run channel

**Files:**
- Modify: `lemely/runtime/events.py`
- Test: `tests/test_events_scoping.py`

**Interfaces:**
- Produces `current_run_id: ContextVar[str | None]`, `Event.run_id: str | None`, `EventBus.subscribe_queue(run_id: str | None = None)`, unchanged `publish(...)` and `publish_done()` semantics per spec §4.5.

- [ ] **Step 1: Write the failing tests**

```python
"""Per-run scoping on the process-global bus (spec §4.5, DS10)."""

from __future__ import annotations

import contextvars
import threading

from lemely.runtime.events import EventBus, EventType, current_run_id


def _drain(q):
    out = []
    while True:
        try:
            out.append(q.get_nowait())
        except Exception:  # noqa: BLE001 — queue.Empty
            return out


def test_scoped_queues_do_not_cross_talk() -> None:
    bus = EventBus()
    qa, qb, q_all = bus.subscribe_queue("a"), bus.subscribe_queue("b"), bus.subscribe_queue()
    token = current_run_id.set("a")
    try:
        bus.publish(EventType.WARNING, message="from a")
    finally:
        current_run_id.reset(token)
    token = current_run_id.set("b")
    try:
        bus.publish(EventType.WARNING, message="from b")
    finally:
        current_run_id.reset(token)
    assert [e.payload["message"] for e in _drain(qa)] == ["from a"]
    assert [e.payload["message"] for e in _drain(qb)] == ["from b"]
    assert [e.payload["message"] for e in _drain(q_all)] == ["from a", "from b"]


def test_unscoped_events_reach_every_queue() -> None:
    bus = EventBus()
    qa, q_all = bus.subscribe_queue("a"), bus.subscribe_queue()
    bus.publish(EventType.BUDGET_WARNING, threshold=4.0)
    assert len(_drain(qa)) == 1 and len(_drain(q_all)) == 1


def test_sentinel_ends_only_its_own_run() -> None:
    bus = EventBus()
    qa, qb, q_all = bus.subscribe_queue("a"), bus.subscribe_queue("b"), bus.subscribe_queue()
    token = current_run_id.set("a")
    try:
        bus.publish_done()
    finally:
        current_run_id.reset(token)
    assert _drain(qa) == [None]
    assert _drain(qb) == []
    assert _drain(q_all) == [None]


def test_child_threads_must_copy_context() -> None:
    """The rule the spec pins: a bare Thread does not inherit the run id; copy_context does."""
    seen: list[str | None] = []
    token = current_run_id.set("run-1")
    try:
        t1 = threading.Thread(target=lambda: seen.append(current_run_id.get()))
        t1.start(); t1.join()
        ctx = contextvars.copy_context()
        t2 = threading.Thread(target=ctx.run, args=(lambda: seen.append(current_run_id.get()),))
        t2.start(); t2.join()
    finally:
        current_run_id.reset(token)
    assert seen == [None, "run-1"]
```

- [ ] **Step 2: Run to verify they fail** — `ImportError: current_run_id`.

- [ ] **Step 3: Implement**

```python
from contextvars import ContextVar

current_run_id: ContextVar[str | None] = ContextVar("lemely_current_run_id", default=None)
"""The run (SSE stream or grading job) the current thread is working for.
Set once at the top of a worker thread; child threads must run under
``contextvars.copy_context()`` — threads do not inherit it otherwise."""


class Event:
    __slots__ = ("payload", "run_id", "type")

    def __init__(self, type: EventType, payload: dict[str, Any], run_id: str | None = None) -> None:
        self.type = type
        self.payload = payload
        self.run_id = run_id
```

`EventBus._queues: list[tuple[queue.SimpleQueue[Event | None], str | None]]`; `subscribe_queue(run_id=None)` appends `(q, run_id)`; `unsubscribe_queue` removes by queue identity; `publish` stamps `run_id=current_run_id.get()` and delivers to a queue when `scope is None or event.run_id is None or scope == event.run_id`; `publish_done` delivers `None` when `scope is None or scope == current_run_id.get()`. Callbacks unchanged.

- [ ] **Step 4: Run** — `pytest tests/test_events_scoping.py tests/test_web_app.py -q` (the existing `_fake_publisher` test still passes: unscoped queue, run id `None`).

- [ ] **Step 5: pre-commit, then commit** — `feat(events): per-run channels on the bus via a context variable (DS10)`.

---

## Task 15: The SSE bridge and both workers set the run id

**Files:**
- Modify: `lemely/web/sse.py` (`bus_event_stream(run, *, poll_seconds=0.15, run_id: str | None = None)`)
- Modify: `lemely/web/routers/student.py` (`bus_event_stream(run, run_id=payload.paperId)`)
- Modify: `lemely/web/routers/teacher.py` (`_run_grading_job` sets `current_run_id` to `str(paper_id)` first; its tracker subscribes with that id and drops the payload filter added in Task 6; the `_grading_pool` comment loses "once scoping lands")
- Test: `tests/test_web_app.py`

- [ ] **Step 1: Write the failing test**

```python
def test_two_concurrent_streams_are_isolated() -> None:
    """Two runs at once: each stream sees only its frames and ends only with its own sentinel."""
    app = FastAPI()

    def _publisher(tag: str, delay: float):
        def run() -> None:
            try:
                time.sleep(delay)
                bus.publish(EventType.MARKING_PROGRESS, question_id=tag, marker_source="deterministic", confidence=1.0)
            finally:
                bus.publish_done()
        return run

    @app.get("/s/{tag}")
    async def stream(tag: str) -> StreamingResponse:
        delay = 0.05 if tag == "fast" else 0.4
        return StreamingResponse(bus_event_stream(_publisher(tag, delay), poll_seconds=0.02, run_id=tag), media_type="text/event-stream")

    client = TestClient(app)
    with ThreadPoolExecutor(2) as pool:
        fast, slow = pool.map(lambda t: client.get(f"/s/{t}").text, ["fast", "slow"])
    assert '"question_id": "fast"' in fast and '"slow"' not in fast
    assert '"question_id": "slow"' in slow and '"fast"' not in slow
    assert fast.count("[DONE]") == 1 and slow.count("[DONE]") == 1
```

- [ ] **Step 2: Run to verify it fails** (the slow stream ends early or carries the fast frame).

- [ ] **Step 3: Implement**

```python
async def bus_event_stream(run, *, poll_seconds: float = 0.15, run_id: str | None = None) -> AsyncIterator[str]:
    scope = run_id or uuid.uuid4().hex
    q = bus.subscribe_queue(scope)

    def _scoped_run() -> None:
        token = current_run_id.set(scope)
        try:
            run()
        finally:
            current_run_id.reset(token)

    worker = threading.Thread(target=_scoped_run, daemon=True)
```

Rewrite the module docstring's warning: cross-talk is gone; the remaining rule is "a `run` must still call `publish_done()` and must copy the context into any thread it spawns". `_format_frame` is unchanged (no `run_id` on the wire — assert that in the test above by checking `"run_id"` is absent from both bodies).

- [ ] **Step 4: Run** — `pytest tests/test_web_app.py tests/test_web_teacher.py tests/test_student_correct.py -q`.

- [ ] **Step 5: pre-commit, then commit** — `feat(web): SSE streams and grading jobs are scoped to their run`.

---

## Stage F — retire the cap in the web app (spec §4.6; rollout step 6)

## Task 16: `GeminiClient` takes a ledger; the web app passes none

**Files:**
- Modify: `lemely/io/gemini.py:153-170, 288-305, 548-570`
- Modify: `lemely/web/deps.py:95-97`, `lemely/web/app.py:14,49`
- Test: `tests/test_gemini_client.py`

**Interfaces:**
- Produces `GeminiClient(settings, *, _genai_client=None, default_cache_mode="read_write", ledger: CostLedger | _DefaultLedger | None = DEFAULT_LEDGER)`; `DEFAULT_LEDGER` sentinel exported from `lemely.io.gemini`.

- [ ] **Step 1: Write the failing tests**

`tests/test_gemini_client.py` is `unittest.TestCase` style and already has `_make_settings(tmp, **gemini_overrides)`, `_mock_response(json_text)` and `_SimpleSchema`. Add two methods to `GeminiClientTests`:

```python
    def _one_call(self, client: GeminiClient) -> None:
        client.generate_structured(
            system_prompt="sys",
            user_prompt="user",
            response_schema=_SimpleSchema,
            prompt_version="1",
        )

    def test_default_client_enforces_the_file_ledger_ceiling(self) -> None:
        """Unchanged behaviour for the CLI/Gradio/eval path: a zero ceiling stops the call."""
        mock_genai = MagicMock()
        mock_genai.models.generate_content.return_value = _mock_response('{"value": "hi"}')
        settings = _make_settings(self.tmp, total_usd_ceiling=0.0)
        client = GeminiClient(settings, _genai_client=mock_genai)
        with self.assertRaisesRegex(ExternalServiceError, "USD ceiling"):
            self._one_call(client)

    def test_ledgerless_client_neither_checks_nor_records(self) -> None:
        """DS3: ledger=None means no ceiling check, no ledger file, no budget events."""
        mock_genai = MagicMock()
        mock_genai.models.generate_content.return_value = _mock_response('{"value": "hi"}')
        settings = _make_settings(self.tmp, total_usd_ceiling=0.0)
        events: list[EventType] = []
        on_warning = lambda **_: events.append(EventType.BUDGET_WARNING)  # noqa: E731
        on_exceeded = lambda **_: events.append(EventType.BUDGET_EXCEEDED)  # noqa: E731
        bus.subscribe(EventType.BUDGET_WARNING, on_warning)
        bus.subscribe(EventType.BUDGET_EXCEEDED, on_exceeded)
        try:
            client = GeminiClient(settings, _genai_client=mock_genai, ledger=None)
            self._one_call(client)  # succeeds despite a zero ceiling
        finally:
            bus.unsubscribe(EventType.BUDGET_WARNING, on_warning)
            bus.unsubscribe(EventType.BUDGET_EXCEEDED, on_exceeded)
        self.assertEqual(events, [])
        self.assertFalse((settings.paths.output_dir / "gemini_spend.json").exists())
        self.assertEqual(mock_genai.models.generate_content.call_count, 1)
```

(`from lemely.runtime.events import EventType, bus` and `from lemely.runtime.errors import ExternalServiceError` at the top if not already imported.)

- [ ] **Step 2: Run to verify they fail.**

- [ ] **Step 3: Implement**

```python
class _DefaultLedger:
    """Sentinel: build the file ledger under ``paths.output_dir`` (CLI, Gradio, eval)."""


DEFAULT_LEDGER = _DefaultLedger()
```

Constructor: `self._ledger = CostLedger(settings.paths.output_dir / "gemini_spend.json") if isinstance(ledger, _DefaultLedger) else ledger`. `_check_cost_ceiling`: the USD branch runs only `if g.total_usd_ceiling is not None and self._ledger is not None`. The post-call block: `if self._ledger is not None:` around `ledger.add` and the two `bus.publish(BUDGET_*)` calls; the `gemini_call` log line stays unconditional. `deps.get_gemini_client` returns `GeminiClient(get_settings(), ledger=None)`; delete the `register_budget_ntfy` import and call from `lemely/web/app.py`.

- [ ] **Step 4: Run** — `pytest tests/test_gemini_client.py tests/test_cost_ledger.py tests/test_web_app.py -q`.

- [ ] **Step 5: pre-commit, then commit** — `refactor(gemini): the web process runs with no spend ledger (DS3)`.

---

## Task 17: The admin overview loses its spend panel

**Files:**
- Modify: `lemely/web/schemas_admin.py` (delete `SpendDTO`; drop `spend` from `PlatformOverviewDTO`), `lemely/web/routers/admin.py:118-135`, `tests/test_web_platform_admin.py`
- Modify: `web/src/lib/adminTypes.ts` (delete `Spend`, drop `spend`), `web/src/portals/admin/screens/PlatformConsole.tsx` (delete `SpendPanel` and its render), `web/src/lib/hooks/useAdminApi.ts` docstrings ("zero spend")

- [ ] Backend first: delete the `CostLedger` import and ledger read in `platform_overview`; update the overview test to assert `"spend" not in body`. `pytest tests/test_web_platform_admin.py -q`.
- [ ] Frontend: remove the type, the panel, the import; `npm run typecheck && npm run test` in `web/`; the screenshot corpus for X-01 is re-baselined in Task 20's docs pass only if the visual-qa gate is run.
- [ ] pre-commit, then commit — `feat(admin): drop the spend panel; the billing budget is the guard (DS3)`.

---

## Stage G — infrastructure, deploy, docs (spec §4.7; rollout steps 1, 2 and 6)

## Task 18: Bootstrap script — buckets, runtime identities, budget

**Files:**
- Create: `scripts/gcs-lifecycle.json`
- Modify: `scripts/gcp-bootstrap.sh`

**Acceptance (every step idempotent; re-running prints "already exists, skipping" where it applies):**

`scripts/gcs-lifecycle.json`:

```json
{ "rule": [ { "action": { "type": "Delete" }, "condition": { "age": 90 } } ] }
```

Appended to the script after the deployer-role loop, before the WIF binding:

```bash
echo "== Enabling storage + budget APIs =="
gcloud services enable storage.googleapis.com billingbudgets.googleapis.com --quiet

for ENV in staging production; do
  BUCKET="${PROJECT_ID}-uploads-${ENV}"
  RUNTIME_SA_ID="lemely-backend-${ENV}"
  RUNTIME_SA="${RUNTIME_SA_ID}@${PROJECT_ID}.iam.gserviceaccount.com"

  echo "== Bucket gs://$BUCKET (uniform access, no public access, 90-day lifecycle) =="
  if ! gcloud storage buckets describe "gs://$BUCKET" >/dev/null 2>&1; then
    gcloud storage buckets create "gs://$BUCKET" --location="$REGION" \
      --uniform-bucket-level-access --public-access-prevention
  else
    echo "   already exists, skipping"
  fi
  gcloud storage buckets update "gs://$BUCKET" --lifecycle-file="$(dirname "$0")/gcs-lifecycle.json"

  echo "== Runtime service account $RUNTIME_SA_ID =="
  if ! gcloud iam service-accounts describe "$RUNTIME_SA" >/dev/null 2>&1; then
    gcloud iam service-accounts create "$RUNTIME_SA_ID" --display-name="Lemely backend ($ENV)"
  else
    echo "   already exists, skipping"
  fi
  # Object access on THIS bucket only — never a project-level storage role.
  gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" \
    --member="serviceAccount:${RUNTIME_SA}" --role="roles/storage.objectAdmin" >/dev/null
done

echo "== Billing budget (the only spend guard once the in-app cap is retired) =="
if [ -n "${BILLING_ACCOUNT_ID:-}" ] && [ -n "${BUDGET_USD:-}" ]; then
  if ! gcloud billing budgets list --billing-account="$BILLING_ACCOUNT_ID" --format='value(displayName)' | grep -qx "lemely-${PROJECT_ID}"; then
    gcloud billing budgets create --billing-account="$BILLING_ACCOUNT_ID" \
      --display-name="lemely-${PROJECT_ID}" \
      --budget-amount="${BUDGET_USD}USD" \
      --filter-projects="projects/${PROJECT_ID}" \
      --threshold-rule=percent=0.5 --threshold-rule=percent=0.9 --threshold-rule=percent=1.0
  else
    echo "   already exists, skipping"
  fi
else
  echo "   SKIPPED: set BILLING_ACCOUNT_ID and BUDGET_USD to create the budget."
  echo "   Without it nothing stops Gemini spend — the web app enforces no cap (spec DS3)."
fi
```

The closing `cat <<EOF` block additionally prints the two bucket names and the two runtime SA emails, and notes that `deploy.yml` derives both from `GCP_PROJECT_ID` so no new GitHub variable is needed. The header comment lists `BILLING_ACCOUNT_ID`/`BUDGET_USD` as optional inputs. `gcloud storage buckets update --lifecycle-file` is idempotent.

- [ ] `bash -n scripts/gcp-bootstrap.sh`; `shellcheck scripts/gcp-bootstrap.sh` if available.
- [ ] pre-commit, then commit — `feat(ci): bootstrap provisions upload buckets, runtime identities and a billing budget`.

---

## Task 19: Deploy workflow — identity, storage, smoke assertion (not yet the unpin)

**Files:**
- Modify: `.github/workflows/deploy.yml:144-190, 220`

**Acceptance:**
- The `flags:` line gains `--service-account=lemely-backend-${{ needs.resolve-env.outputs.environment }}@${{ vars.GCP_PROJECT_ID }}.iam.gserviceaccount.com`. `--max-instances=1` is **unchanged in this task**.
- `env_vars:` gains `LEMELY_STORAGE__BACKEND=gcs` and `LEMELY_STORAGE__BUCKET=${{ vars.GCP_PROJECT_ID }}-uploads-${{ needs.resolve-env.outputs.environment }}`.
- "Verify health directly against Cloud Run" becomes:

```yaml
      - name: Verify health and the storage backend directly against Cloud Run
        run: |
          BODY="$(curl --fail --silent --show-error --retry 5 --retry-delay 5 "${{ steps.deploy.outputs.url }}/api/health")"
          echo "$BODY"
          echo "$BODY" | grep -q '"backend":"gcs"' || { echo "health does not report the gcs backend"; exit 1; }
          echo "$BODY" | grep -q "\"bucket\":\"${{ vars.GCP_PROJECT_ID }}-uploads-${{ needs.resolve-env.outputs.environment }}\"" || { echo "health reports the wrong bucket"; exit 1; }
```

- The comment above the deploy step gains one sentence: the runtime identity holds object access on its own bucket only; the deployer's project-level `iam.serviceAccountUser` is what lets it deploy as that identity.
- Precondition stated in the PR body: Task 18 has been run against the project before this merges, or the revision fails to start with a missing-service-account error.

- [ ] `pre-commit run --all-files` (check-yaml), then commit — `feat(ci): deploy as the runtime identity with GCS storage; assert it on /api/health`.

---

## Task 20: Documentation and the decision record

**Files:**
- Modify: `docs/deployment.md` §2 table (add `LEMELY_STORAGE__BACKEND`, reword `LEMELY_STORAGE__BUCKET` — "created by `scripts/gcp-bootstrap.sh`", mark `LEMELY_GEMINI__TOTAL_USD_CEILING` "CLI/Gradio only — the web process enforces no cap", add `LEMELY_GRADING__STALE_RUN_AFTER_SECONDS`); §5.1 rewritten under the same heading to say the constraint is lifted, what moved where (a table mirroring spec §1.3 with a "now" column), and that the only per-instance state is the Gemini response cache; §5.4 spend bullet replaced with the budget sentence; §6 checklist lines for storage and budget.
- Modify: `docs/ci-cd.md` §1 (bootstrap inputs and outputs), §2 (the Supabase buckets are unused; optional deletion), credentials checklist (no new secrets; two derived names), "Known gaps" (drop the ledger bullet and the single-replica bullet; add "Queued is per instance" and "a budget alert is not a cap").
- Modify: `DELIVERY.md` §5.6 (replace the first and third bullets accordingly).
- Modify: `BUILD/DECISIONS.md` — one new D-series entry, "Uploads on GCS and the instance pin lifted", that records DS1–DS15 by reference to the spec and states the two accepted trades (budget-not-cap; Queued-per-instance).
- Modify: `docs/deployment.md` §5.4 also loses the "$8 Gemini spend is capped" bullet.

- [ ] Every claim in the edited sections is checked against the merged code, not the plan. `grep -rn "max-instances=1\|Supabase Storage\|gemini_spend" docs DELIVERY.md` → only historical mentions remain, each marked as such.
- [ ] pre-commit, then commit — `docs(deploy): record the storage move, the lifted pin, and the retired cap`.

---

## Task 21: The unpin

Merged only after Tasks 1–20 are on staging and spec §8 items 1–7 have been exercised there.

**Files:**
- Modify: `.github/workflows/deploy.yml:144-150, 179`

**Acceptance:**
- `--max-instances=1` → `--max-instances=3`.
- The comment block is replaced:

```yaml
      # max-instances=3 is a COST knob, not a correctness one. Every piece of
      # state that once required a single replica now lives in Postgres or
      # object storage (docs/deployment.md §5.1); the only per-instance state
      # left is the Gemini response cache, which is a cache. Three is enough to
      # absorb a spike and prove the app is instance-agnostic while a runaway
      # cannot fan out to 100 containers on a free-tier project. min-instances=0
      # keeps idle time free at the price of a cold start.
```

- [ ] After the staging deploy: `gcloud run services describe lemely-backend-staging --region=us-central1 --format='value(spec.template.metadata.annotations."autoscaling.knative.dev/maxScale")'` prints `3`; spec §8 item 2 (two revisions, one list) is exercised by driving load until a second instance starts (`gcloud run services describe ... --format='value(status.traffic)'` and the Cloud Run metrics explorer show instance count ≥ 2) and reading `GET /papers` through the Worker repeatedly.
- [ ] pre-commit, then commit — `feat(ci): lift the Cloud Run instance pin to 3`.

---

## Verification checklist

Mapped to spec §8. Every line is a behaviour to exercise on staging, then production.

- [ ] `GET /api/health` reports `storage.backend == "gcs"` and the environment's bucket; a student upload and a teacher upload each create an object under the spec §4.1 key, and `output_dir` on the container stays empty of uploads.
- [ ] A teacher uploads a paper; the revision is restarted (redeploy); `GET /papers` still lists it with its status. With two instances serving, both answer the same list.
- [ ] A parent OTP issued through one instance verifies through another; a resend inside the cooldown is 429 from any instance.
- [ ] Email verification succeeds by link and, separately, by typed code; five wrong codes lock the challenge; the `AUTH_ANY` matrix row for `/auth/verify-email/code` passes.
- [ ] Two students run corrections concurrently on one instance; each stream carries only its own frames and ends only when its own run ends (`tests/test_web_app.py::test_two_concurrent_streams_are_isolated` is the hermetic proof; the live check is two browsers).
- [ ] `POST /papers/{id}/regrade` fired twice within a second from two clients marks the paper once (one `processing` claim; one Gemini bill).
- [ ] The admin overview has no spend fields; no `gemini_spend.json` appears under the web process's output directory; the billing budget exists on the project.
- [ ] The Cloud Run service shows `maxScale: 3`; the deploy workflow's comment calls it a cost knob.
- [ ] `grep -rn "HttpStorageBackend\|papers_store\|JobRegistry\|create_signed_url" lemely` returns nothing.
