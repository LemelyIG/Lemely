"""Hermetic regression tests for :mod:`lemely.io.storage`.

``HttpStorageBackend`` previously had no hermetic coverage at all (only the
live-skip test in ``test_storage_live.py``, matching the precedent
``HttpGoTrueBackend`` set) — which is exactly how a real bug shipped
unnoticed for the whole build: the local/self-hosted Supabase Storage API
answers a missing object with HTTP 400 (not 404) and an embedded
``{"code": "NoSuchKey"}`` body, so ``download()``'s original
``response.status_code == 404`` check never actually fired against the real
API (confirmed live, D2.8 in BUILD/DECISIONS.md). These tests pin the fixed
behaviour so it can't silently regress again, live-Supabase or not.
"""

from __future__ import annotations

import httpx
import pytest
from pydantic import SecretStr

from lemely.io.storage import HttpStorageBackend, StorageObjectNotFoundError
from lemely.runtime.config import Settings
from lemely.runtime.errors import ExternalServiceError


def _settings() -> Settings:
    base = Settings()
    return base.model_copy(
        update={
            "supabase": base.supabase.model_copy(update={"service_role_key": SecretStr("svc-key")})
        }
    )


def _fake_response(status_code: int, json_body: dict[str, object] | None = None) -> httpx.Response:
    return httpx.Response(
        status_code,
        json=json_body,
        request=httpx.Request("GET", "http://example.invalid"),
    )


def test_download_missing_key_raises_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    """HTTP 400 + {"code": "NoSuchKey"} — the real API's actual missing-object shape."""
    monkeypatch.setattr(
        httpx,
        "get",
        lambda *a, **k: _fake_response(
            400,
            {
                "statusCode": "404",
                "error": "not_found",
                "message": "Object not found",
                "code": "NoSuchKey",
            },
        ),
    )
    backend = HttpStorageBackend(_settings())
    with pytest.raises(StorageObjectNotFoundError):
        backend.download("uploads", "missing.pdf")


def test_download_real_404_status_also_raises_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A literal HTTP 404 (if the API ever returns one) is still honoured."""
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _fake_response(404))
    backend = HttpStorageBackend(_settings())
    with pytest.raises(StorageObjectNotFoundError):
        backend.download("uploads", "missing.pdf")


def test_download_missing_bucket_raises_external_service_error_not_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """NoSuchBucket is a real misconfiguration, not an expected "no sibling" case."""
    monkeypatch.setattr(
        httpx,
        "get",
        lambda *a, **k: _fake_response(
            400,
            {
                "statusCode": "404",
                "error": "Bucket not found",
                "message": "Bucket not found",
                "code": "NoSuchBucket",
            },
        ),
    )
    backend = HttpStorageBackend(_settings())
    with pytest.raises(ExternalServiceError):
        backend.download("nonexistent-bucket", "any.pdf")


def test_download_success_returns_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    def _ok(*a: object, **k: object) -> httpx.Response:
        return httpx.Response(
            200, content=b"pdf-bytes", request=httpx.Request("GET", "http://example.invalid")
        )

    monkeypatch.setattr(httpx, "get", _ok)
    backend = HttpStorageBackend(_settings())
    assert backend.download("uploads", "scan.pdf") == b"pdf-bytes"
