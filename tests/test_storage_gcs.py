"""Hermetic tests for :class:`lemely.io.storage_gcs.GcsStorageBackend`.

The SDK client is injected (the ``_genai_client`` precedent in
``lemely.io.gemini``), so these pin the *contract* — create-only uploads,
the not-found mapping, deferred credential failure — without a network.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from google.api_core.exceptions import GoogleAPICallError, NotFound, PreconditionFailed
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


def test_upload_generic_api_error_maps_to_external_service_error() -> None:
    client, blob = _client_with_blob()
    blob.upload_from_string.side_effect = GoogleAPICallError("boom")
    with pytest.raises(ExternalServiceError, match="Storage upload failed"):
        GcsStorageBackend(_client=client).upload("b", "k", b"d", None)


def test_download_missing_maps_to_not_found() -> None:
    client, blob = _client_with_blob()
    blob.download_as_bytes.side_effect = NotFound("nope")
    with pytest.raises(StorageObjectNotFoundError, match="No object at b/k"):
        GcsStorageBackend(_client=client).download("b", "k")


def test_download_generic_api_error_maps_to_external_service_error() -> None:
    client, blob = _client_with_blob()
    blob.download_as_bytes.side_effect = GoogleAPICallError("boom")
    with pytest.raises(ExternalServiceError, match="Storage download failed"):
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


def test_delete_generic_api_error_maps_to_external_service_error() -> None:
    client, blob = _client_with_blob()
    blob.delete.side_effect = GoogleAPICallError("boom")
    with pytest.raises(ExternalServiceError, match="Storage delete failed"):
        GcsStorageBackend(_client=client).delete("b", "k")


def test_credentials_failure_is_deferred_to_first_use(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*_: Any, **__: Any) -> Any:
        raise DefaultCredentialsError("no adc")

    monkeypatch.setattr("lemely.io.storage_gcs.storage.Client", _boom)
    backend = GcsStorageBackend()  # constructing must not touch credentials
    with pytest.raises(ExternalServiceError, match="application-default credentials"):
        backend.download("b", "k")


# ---------------------------------------------------------------------------
# Signed URLs. Ported from the tests #220 added alongside its own GCS backend,
# adapted to this backend's injected client (no `google.auth` monkeypatching
# needed). They are kept verbatim in substance because they encode a real bug:
# the original discriminator was `getattr(credentials, "private_key", None)`,
# which no google-auth credential exposes, so every credential took the IAM
# signBlob branch — including JSON keys that could sign offline.
# ---------------------------------------------------------------------------


def _real_service_account_credentials() -> Any:
    """A genuine ``service_account.Credentials`` from a freshly generated RSA key.

    Deliberately not ``MagicMock(private_key=...)``: no real google-auth
    credential exposes a public ``private_key`` at all (it lives behind
    ``signer``), so a mock shaped that way would validate a discriminator no
    real credential could satisfy.
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
    return service_account.Credentials.from_service_account_info(
        {
            "type": "service_account",
            "project_id": "a-project",
            "private_key_id": "key-id-1",
            "private_key": pem,
            "client_email": "sa@a-project.iam.gserviceaccount.com",
            "client_id": "123",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    )


def _client_with_credentials(credentials: Any) -> tuple[MagicMock, MagicMock]:
    client, blob = _client_with_blob()
    client._credentials = credentials
    return client, blob


def test_signed_url_signs_locally_for_a_service_account_json_key() -> None:
    """A JSON-key credential has a ``signer`` and needs no IAM signBlob kwargs."""
    credentials = _real_service_account_credentials()
    client, blob = _client_with_credentials(credentials)
    blob.generate_signed_url.return_value = "https://signed.example/x.png"

    url = GcsStorageBackend(_client=client).create_signed_url("avatars", "x.png", 3600)

    assert url == "https://signed.example/x.png"
    _, kwargs = blob.generate_signed_url.call_args
    assert "service_account_email" not in kwargs
    assert "access_token" not in kwargs
    assert kwargs["version"] == "v4"
    assert kwargs["method"] == "GET"


def test_signed_url_uses_iam_signblob_for_a_workload_identity_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Cloud Run credential carries no ``signer``, so it must sign via signBlob."""
    import google.auth.compute_engine as compute_engine

    credentials = compute_engine.Credentials(
        service_account_email="sa@a-project.iam.gserviceaccount.com"
    )
    client, blob = _client_with_credentials(credentials)
    blob.generate_signed_url.return_value = "https://signed.example/x.png"

    def _fake_refresh(request: object) -> None:
        credentials.token = "fresh-access-token"

    refresh = MagicMock(side_effect=_fake_refresh)
    monkeypatch.setattr(credentials, "refresh", refresh)
    monkeypatch.setattr("google.auth.transport.requests.Request", lambda: MagicMock())

    GcsStorageBackend(_client=client).create_signed_url("avatars", "x.png", 3600)

    refresh.assert_called_once()
    _, kwargs = blob.generate_signed_url.call_args
    assert kwargs["service_account_email"] == "sa@a-project.iam.gserviceaccount.com"
    assert kwargs["access_token"] == "fresh-access-token"


def test_signed_url_for_user_adc_raises_rather_than_attribute_error() -> None:
    """`gcloud auth application-default login` credentials cannot sign at all.

    They have neither ``signer`` nor ``service_account_email``. The failure
    must be a named :class:`ExternalServiceError`, not an ``AttributeError``
    from reaching for an address that isn't there.
    """
    from google.oauth2 import credentials as user_credentials

    credentials = user_credentials.Credentials(
        token="tok",
        refresh_token="r",
        client_id="id",
        client_secret="secret",
        token_uri="https://oauth2.googleapis.com/token",
    )
    client, _ = _client_with_credentials(credentials)

    with pytest.raises(ExternalServiceError, match="signed URL"):
        GcsStorageBackend(_client=client).create_signed_url("avatars", "x.png", 3600)
