"""Live integration test against the real local Supabase Storage.

Skips cleanly (never fails) when either of the following is true, matching the
skip condition ``test_auth_live.py`` uses for GoTrue:

* Storage is unreachable at ``supabase.url``.
* The service-role key is absent from the environment
  (``LEMELY_SUPABASE__SERVICE_ROLE_KEY``).

Secrets are never hardcoded — the key comes only from the environment.
"""

from __future__ import annotations

import os
import uuid

import httpx
import pytest
from pydantic import SecretStr

from lemely.io.storage import HttpStorageBackend, StorageObjectNotFoundError
from lemely.runtime.config import Settings


def _storage_reachable(url: str) -> bool:
    try:
        resp = httpx.get(f"{url.rstrip('/')}/storage/v1/status", timeout=2.0)
    except httpx.HTTPError:
        return False
    return resp.status_code < 500


def _live_settings() -> Settings | None:
    service_key = os.environ.get("LEMELY_SUPABASE__SERVICE_ROLE_KEY")
    if not service_key:
        return None
    settings = Settings()
    return settings.model_copy(
        update={
            "supabase": settings.supabase.model_copy(
                update={"service_role_key": SecretStr(service_key)}
            )
        }
    )


@pytest.fixture
def live_backend() -> HttpStorageBackend:
    settings = _live_settings()
    if settings is None:
        pytest.skip("Supabase service-role key not set in environment")
    if not _storage_reachable(settings.supabase.url):
        pytest.skip("local Supabase Storage not reachable")
    return HttpStorageBackend(settings)


def test_live_upload_download_roundtrip(live_backend: HttpStorageBackend) -> None:
    settings = _live_settings()
    assert settings is not None
    object_path = f"live-test/{uuid.uuid4().hex}.pdf"
    payload = b"%PDF-1.4 live storage roundtrip"

    live_backend.upload(settings.storage.bucket, object_path, payload, "application/pdf")
    try:
        assert live_backend.download(settings.storage.bucket, object_path) == payload
    finally:
        live_backend.delete(settings.storage.bucket, object_path)


def test_live_download_missing_object_raises_not_found(
    live_backend: HttpStorageBackend,
) -> None:
    settings = _live_settings()
    assert settings is not None
    with pytest.raises(StorageObjectNotFoundError):
        live_backend.download(settings.storage.bucket, f"live-test/{uuid.uuid4().hex}-missing.pdf")
