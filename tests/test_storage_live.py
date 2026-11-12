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
    except Exception:  # any ADC failure means "not opted in"
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
