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
