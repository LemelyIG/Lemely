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

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import httpx
import pytest
from pydantic import SecretStr

from lemely.io.storage import GcsStorageBackend, HttpStorageBackend, StorageObjectNotFoundError
from lemely.runtime.config import Settings
from lemely.runtime.errors import ExternalServiceError

if TYPE_CHECKING:
    from google.oauth2 import service_account


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


# ---------------------------------------------------------------------------
# GcsStorageBackend — hermetic, no network. The `google-cloud-storage`/
# `google-auth` client library is monkeypatched at its own module attributes
# (not at an import alias local to lemely.io.storage), which works precisely
# because GcsStorageBackend imports both lazily, per-call, rather than once at
# module scope — see that class's own docstring.
# ---------------------------------------------------------------------------


def _gcs_settings() -> Settings:
    base = Settings()
    return base.model_copy(update={"storage": base.storage.model_copy(update={"provider": "gcs"})})


def _wire_fake_client(monkeypatch: pytest.MonkeyPatch, credentials: object) -> MagicMock:
    """Patch ``google.auth.default``/``google.cloud.storage.Client``; return the fake blob."""
    monkeypatch.setattr("google.auth.default", lambda: (credentials, "a-project"))
    fake_blob = MagicMock(name="blob")
    fake_bucket = MagicMock(name="bucket")
    fake_bucket.blob.return_value = fake_blob
    fake_client = MagicMock(name="client")
    fake_client.bucket.return_value = fake_bucket
    monkeypatch.setattr("google.cloud.storage.Client", lambda **kwargs: fake_client)
    return fake_blob


def test_gcs_upload_passes_bucket_object_path_content_type_and_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_blob = _wire_fake_client(monkeypatch, MagicMock(private_key="a-private-key"))

    GcsStorageBackend(_gcs_settings()).upload("avatars", "avatars/u1/x.png", b"bytes", "image/png")

    fake_blob.upload_from_string.assert_called_once_with(b"bytes", content_type="image/png")


def test_gcs_upload_with_no_content_type_defaults_to_octet_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_blob = _wire_fake_client(monkeypatch, MagicMock(private_key="a-private-key"))

    GcsStorageBackend(_gcs_settings()).upload("uploads", "u1/scan.pdf", b"bytes", None)

    fake_blob.upload_from_string.assert_called_once_with(
        b"bytes", content_type="application/octet-stream"
    )


def test_gcs_upload_failure_raises_external_service_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from google.api_core import exceptions as gcs_exceptions

    fake_blob = _wire_fake_client(monkeypatch, MagicMock(private_key="a-private-key"))
    fake_blob.upload_from_string.side_effect = gcs_exceptions.ServiceUnavailable("down")

    with pytest.raises(ExternalServiceError):
        GcsStorageBackend(_gcs_settings()).upload("avatars", "x.png", b"bytes", "image/png")


def test_gcs_download_missing_object_raises_storage_object_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from google.api_core import exceptions as gcs_exceptions

    fake_blob = _wire_fake_client(monkeypatch, MagicMock(private_key="a-private-key"))
    fake_blob.download_as_bytes.side_effect = gcs_exceptions.NotFound("missing")

    with pytest.raises(StorageObjectNotFoundError):
        GcsStorageBackend(_gcs_settings()).download("avatars", "missing.png")


def test_gcs_download_success_returns_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_blob = _wire_fake_client(monkeypatch, MagicMock(private_key="a-private-key"))
    fake_blob.download_as_bytes.return_value = b"the-bytes"

    result = GcsStorageBackend(_gcs_settings()).download("avatars", "x.png")

    assert result == b"the-bytes"


def _real_service_account_credentials() -> service_account.Credentials:
    """Build a real ``service_account.Credentials`` from a freshly generated RSA key.

    Not a ``MagicMock(private_key=...)`` shape — no real google-auth credential
    exposes a public ``private_key`` attribute at all (the actual private key
    lives behind ``signer``), so a mock built that way would validate a
    discriminator no real credential could ever satisfy. This is a genuine
    instance of the class the production JSON-key deployment path constructs,
    built via the same ``from_service_account_info`` classmethod, so it
    exercises the real ``signer``/``service_account_email`` attributes.
    """
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from google.oauth2 import service_account

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    info = {
        "type": "service_account",
        "project_id": "a-project",
        "private_key_id": "key-id-1",
        "private_key": pem,
        "client_email": "sa@a-project.iam.gserviceaccount.com",
        "client_id": "123",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
    return service_account.Credentials.from_service_account_info(info)


def test_gcs_signed_url_signs_locally_for_a_real_service_account_json_key_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real service-account JSON key credential needs no IAM signBlob kwargs.

    Regression test for the original discriminator,
    ``getattr(credentials, "private_key", None) is None`` — no google-auth
    credential type (including this one) exposes a public ``private_key``
    attribute, so that check was always true and even this credential always
    took the IAM signBlob branch below. ``hasattr(credentials, "signer")`` is
    the real discriminator, and only this credential type has it.
    """
    credentials = _real_service_account_credentials()
    fake_blob = _wire_fake_client(monkeypatch, credentials)
    fake_blob.generate_signed_url.return_value = "https://signed.example/x.png"
    refresh = MagicMock()
    monkeypatch.setattr(credentials, "refresh", refresh)

    url = GcsStorageBackend(_gcs_settings()).create_signed_url("avatars", "x.png", 3600)

    assert url == "https://signed.example/x.png"
    refresh.assert_not_called()
    _, kwargs = fake_blob.generate_signed_url.call_args
    assert "service_account_email" not in kwargs
    assert "access_token" not in kwargs
    assert kwargs["version"] == "v4"
    assert kwargs["method"] == "GET"


def test_gcs_signed_url_uses_iam_signblob_kwargs_for_a_compute_engine_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real Cloud Run/GCE workload-identity credential carries no ``signer``.

    ``generate_signed_url`` must instead be handed ``service_account_email``
    and a freshly-refreshed ``access_token``, which routes the signature
    through the IAM ``signBlob`` API. Only the network-bound ``refresh`` call
    is mocked — everything else is the real
    :class:`google.auth.compute_engine.Credentials` class.
    """
    import google.auth.compute_engine as compute_engine

    credentials = compute_engine.Credentials(
        service_account_email="sa@a-project.iam.gserviceaccount.com"
    )
    fake_blob = _wire_fake_client(monkeypatch, credentials)
    fake_blob.generate_signed_url.return_value = "https://signed.example/x.png"

    def _fake_refresh(request: object) -> None:
        credentials.token = "fresh-access-token"

    refresh = MagicMock(side_effect=_fake_refresh)
    monkeypatch.setattr(credentials, "refresh", refresh)
    monkeypatch.setattr("google.auth.transport.requests.Request", lambda: MagicMock())

    GcsStorageBackend(_gcs_settings()).create_signed_url("avatars", "x.png", 3600)

    refresh.assert_called_once()
    _, kwargs = fake_blob.generate_signed_url.call_args
    assert kwargs["service_account_email"] == "sa@a-project.iam.gserviceaccount.com"
    assert kwargs["access_token"] == "fresh-access-token"


def test_gcs_signed_url_for_a_user_adc_credential_raises_external_service_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Local ``gcloud auth application-default login`` credentials cannot sign at all.

    A real :class:`google.oauth2.credentials.Credentials` has neither
    ``signer`` (it isn't a service-account key) nor ``service_account_email``
    (it isn't a workload-identity credential either) — the original code
    reached the IAM signBlob branch anyway (per the ``private_key`` bug above)
    and crashed with an uncaught ``AttributeError`` on
    ``credentials.service_account_email``. This must instead be a clean,
    named :class:`~lemely.runtime.errors.ExternalServiceError`.
    """
    from google.oauth2 import credentials as user_credentials

    credentials = user_credentials.Credentials(
        token="tok",
        refresh_token="r",
        client_id="id",
        client_secret="secret",
        token_uri="https://oauth2.googleapis.com/token",
    )
    _wire_fake_client(monkeypatch, credentials)

    with pytest.raises(ExternalServiceError):
        GcsStorageBackend(_gcs_settings()).create_signed_url("avatars", "x.png", 3600)


def test_gcs_client_and_credentials_are_cached_across_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADC discovery and ``storage.Client`` construction happen once per instance.

    A fresh ``google.auth.default()`` call and a fresh ``storage.Client(...)``
    per operation is wasted work on every avatar upload/download/sign — the
    backend should discover credentials once and reuse them.
    """
    credentials = MagicMock(name="credentials")
    auth_default_calls: list[None] = []

    def _fake_default() -> tuple[object, str]:
        auth_default_calls.append(None)
        return credentials, "a-project"

    monkeypatch.setattr("google.auth.default", _fake_default)

    client_ctor_calls: list[dict[str, object]] = []
    fake_blob = MagicMock(name="blob")
    fake_bucket = MagicMock(name="bucket")
    fake_bucket.blob.return_value = fake_blob
    fake_client = MagicMock(name="client")
    fake_client.bucket.return_value = fake_bucket

    def _fake_client_ctor(**kwargs: object) -> MagicMock:
        client_ctor_calls.append(kwargs)
        return fake_client

    monkeypatch.setattr("google.cloud.storage.Client", _fake_client_ctor)

    backend = GcsStorageBackend(_gcs_settings())
    backend.upload("avatars", "a/x.png", b"bytes", "image/png")
    backend.upload("avatars", "a/y.png", b"bytes", "image/png")

    assert len(auth_default_calls) == 1
    assert len(client_ctor_calls) == 1


def test_http_delete_success_issues_a_delete_request(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def _ok(url: str, **kwargs: object) -> httpx.Response:
        calls.append((url, kwargs))
        return httpx.Response(
            200, json={"message": "Successfully deleted"}, request=httpx.Request("DELETE", url)
        )

    monkeypatch.setattr(httpx, "delete", _ok)
    HttpStorageBackend(_settings()).delete("avatars", "u1/x.png")

    assert calls[0][0].endswith("/storage/v1/object/avatars/u1/x.png")


def test_http_delete_missing_key_raises_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    """Delete of a missing object gets the same HTTP 400 + NoSuchKey shape as download.

    The self-hosted Storage API does not answer 404 here either (D2.8), so a
    naive status check would report a missing object as a backend failure and
    the avatar-delete route would log a spurious warning on every re-delete.
    """
    monkeypatch.setattr(
        httpx,
        "delete",
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
    with pytest.raises(StorageObjectNotFoundError):
        HttpStorageBackend(_settings()).delete("avatars", "missing.png")


def test_http_delete_server_error_raises_external_service_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(httpx, "delete", lambda *a, **k: _fake_response(500))
    with pytest.raises(ExternalServiceError):
        HttpStorageBackend(_settings()).delete("avatars", "x.png")


def test_gcs_delete_calls_blob_delete(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_blob = _wire_fake_client(monkeypatch, MagicMock(name="credentials"))

    GcsStorageBackend(_gcs_settings()).delete("avatars", "u1/x.png")

    fake_blob.delete.assert_called_once_with()


def test_gcs_delete_missing_object_raises_storage_object_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from google.api_core import exceptions as gcs_exceptions

    fake_blob = _wire_fake_client(monkeypatch, MagicMock(name="credentials"))
    fake_blob.delete.side_effect = gcs_exceptions.NotFound("missing")

    with pytest.raises(StorageObjectNotFoundError):
        GcsStorageBackend(_gcs_settings()).delete("avatars", "missing.png")


def test_gcs_delete_failure_raises_external_service_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from google.api_core import exceptions as gcs_exceptions

    fake_blob = _wire_fake_client(monkeypatch, MagicMock(name="credentials"))
    fake_blob.delete.side_effect = gcs_exceptions.ServiceUnavailable("down")

    with pytest.raises(ExternalServiceError):
        GcsStorageBackend(_gcs_settings()).delete("avatars", "x.png")


# ---------------------------------------------------------------------------
# GCS is now the DEFAULT provider, which puts a new requirement on the wiring:
# a machine with no Google credentials at all (a fresh clone, CI, this repo's
# own hermetic suite) must still be able to build the app and serve every
# route that does not touch object storage.
# ---------------------------------------------------------------------------


def test_gcs_backend_construction_resolves_no_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Constructing the default backend must not call ``google.auth.default()``.

    ADC discovery raising in ``__init__`` would make `get_storage_backend`
    fail on a credential-less machine, and that dependency is imported by the
    whole `/api/me` router — so every profile and notification route would
    500 on a laptop that has never run `gcloud auth`.
    """
    import google.auth

    def _explode() -> tuple[object, str]:
        raise AssertionError("google.auth.default() must not be called at construction time")

    monkeypatch.setattr(google.auth, "default", _explode)

    backend = GcsStorageBackend(_gcs_settings())

    assert backend is not None


def test_get_storage_backend_defaults_to_gcs_without_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The FastAPI dependency itself is safe to resolve with no ADC present."""
    import google.auth

    from lemely.web.deps import get_storage_backend

    monkeypatch.setattr(
        google.auth,
        "default",
        lambda: (_ for _ in ()).throw(AssertionError("ADC must not be resolved eagerly")),
    )
    get_storage_backend.cache_clear()
    try:
        assert isinstance(get_storage_backend(), GcsStorageBackend)
    finally:
        get_storage_backend.cache_clear()
