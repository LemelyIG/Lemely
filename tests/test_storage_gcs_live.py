"""Live integration test against a real Google Cloud Storage bucket.

The counterpart to ``test_storage_live.py`` (Supabase Storage), for the
backend that is now the default. Everything else in the suite mocks
``google.cloud.storage``, which proves the code calls the client library
correctly but says nothing about whether the *deployment* works: whether the
buckets exist, whether the credential can write to them, and — the one that
has no hermetic equivalent at all — whether a V4 signed URL this process
produces is actually accepted by Google's servers. That last check is why
this file exists: signing on Cloud Run goes through the IAM ``signBlob`` API,
which fails with a 403 unless the runtime service account holds
``roles/iam.serviceAccountTokenCreator`` on itself, and no amount of local
mocking can tell you whether that binding is in place.

**Opt-in, never automatic.** These tests touch a real bucket and cost real
(fractional) money, so they are skipped unless ``LEMELY_LIVE_GCS=1`` is set —
the same shape as ``test_auth_live.py``'s and ``test_storage_live.py``'s
skip gating, so an ordinary ``pytest`` run is unaffected on any machine.

Running them::

    gcloud auth application-default login \\
        --impersonate-service-account=<RUNTIME_SA>
    LEMELY_LIVE_GCS=1 \\
    LEMELY_STORAGE__AVATAR_BUCKET=<project-id>-avatars-staging \\
    python -m pytest tests/test_storage_gcs_live.py -v --no-cov

The impersonation flag is load-bearing for the signed-URL test: plain user
ADC can upload and download but cannot sign at all (see
``GcsStorageBackend.create_signed_url``). Impersonating the runtime service
account both makes signing work locally *and* exercises the exact IAM path
production uses.

Every object written here is namespaced under ``live-test/`` and deleted in a
``finally``, so a failed run leaves at most one small object behind in a
clearly-labelled prefix.
"""

from __future__ import annotations

import os
import uuid

import httpx
import pytest

from lemely.io.storage import StorageObjectNotFoundError
from lemely.io.storage_gcs import GcsStorageBackend
from lemely.runtime.config import Settings

_LIVE_ENV_VAR = "LEMELY_LIVE_GCS"


def _live_settings() -> Settings:
    """Settings forced to the GCS provider, with buckets from the environment."""
    base = Settings()
    return base.model_copy(update={"storage": base.storage.model_copy(update={"provider": "gcs"})})


@pytest.fixture
def live_bucket() -> str:
    if os.environ.get(_LIVE_ENV_VAR) != "1":
        pytest.skip(f"live GCS tests are opt-in; set {_LIVE_ENV_VAR}=1 to run them")
    return _live_settings().storage.avatar_bucket


@pytest.fixture
def live_backend(live_bucket: str) -> GcsStorageBackend:
    backend = GcsStorageBackend(project=_live_settings().storage.gcs_project)
    try:
        # Resolving ADC is the cheapest way to turn "no credentials on this
        # machine" into a skip rather than an error inside the first test.
        backend._client_and_credentials()
    except Exception as exc:  # any ADC/API failure is "not configured for live runs"
        pytest.skip(f"Google Application Default Credentials unavailable: {exc}")
    return backend


def test_live_upload_download_sign_and_delete_roundtrip(
    live_backend: GcsStorageBackend, live_bucket: str
) -> None:
    """The whole production path end to end, against the real bucket.

    Deliberately one test rather than four: each step needs the object the
    previous one wrote, and splitting them would either upload four times or
    make the tests order-dependent. The ``finally`` is what keeps the bucket
    clean when an assertion in the middle fails.
    """
    object_path = f"live-test/{uuid.uuid4().hex}.png"
    payload = b"\x89PNG\r\n\x1a\n live gcs roundtrip"

    live_backend.upload(live_bucket, object_path, payload, "image/png")
    try:
        assert live_backend.download(live_bucket, object_path) == payload

        # The check with no hermetic equivalent: a URL this process signed is
        # honoured by Google's own servers. A 403 here means the runtime
        # service account is missing roles/iam.serviceAccountTokenCreator on
        # itself; a 404 means the object or bucket name is wrong.
        signed_url = live_backend.create_signed_url(live_bucket, object_path, 300)
        assert signed_url.startswith("https://")
        response = httpx.get(signed_url, timeout=30.0)
        assert response.status_code == 200, response.text
        assert response.content == payload
    finally:
        live_backend.delete(live_bucket, object_path)

    # The delete really removed it, rather than reporting success on a no-op.
    with pytest.raises(StorageObjectNotFoundError):
        live_backend.download(live_bucket, object_path)


def test_live_download_missing_object_raises_not_found(
    live_backend: GcsStorageBackend, live_bucket: str
) -> None:
    with pytest.raises(StorageObjectNotFoundError):
        live_backend.download(live_bucket, f"live-test/{uuid.uuid4().hex}-missing.png")


def test_live_delete_missing_object_raises_not_found(
    live_backend: GcsStorageBackend, live_bucket: str
) -> None:
    """Confirms the real ``NotFound`` shape reaches the app's own error type.

    ``DELETE /api/me/avatar`` swallows this exception to stay idempotent, so
    if the client library ever raised something else the route would log a
    spurious warning on every re-delete instead.
    """
    with pytest.raises(StorageObjectNotFoundError):
        live_backend.delete(live_bucket, f"live-test/{uuid.uuid4().hex}-missing.png")
