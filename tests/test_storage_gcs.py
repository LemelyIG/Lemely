"""Hermetic tests for :class:`lemely.io.storage_gcs.GcsStorageBackend`.

The SDK client is injected (the ``_genai_client`` precedent in
``lemely.io.gemini``), so these pin the *contract* — create-only uploads,
the not-found mapping, deferred credential failure — without a network.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock

import pytest
from google.api_core.exceptions import (
    Forbidden,
    GoogleAPICallError,
    NotFound,
    PreconditionFailed,
)
from google.auth.exceptions import DefaultCredentialsError
from google.cloud import storage
from google.cloud.storage.retry import DEFAULT_RETRY_IF_GENERATION_SPECIFIED

from lemely.io.storage import StorageObjectNotFoundError
from lemely.io.storage_gcs import GcsStorageBackend
from lemely.runtime.config import StorageSettings
from lemely.runtime.errors import ConfigError, ExternalServiceError


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


def _workload_identity_client(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[MagicMock, MagicMock, MagicMock, Any]:
    """A Cloud Run-shaped setup: no ``signer``, a devstorage-scoped client token.

    Returns ``(client, blob, default, credentials)`` where ``default`` is the
    patched :func:`google.auth.default` that mints the *signing* credential.
    """
    import google.auth.compute_engine as compute_engine

    credentials = compute_engine.Credentials(
        service_account_email="sa@a-project.iam.gserviceaccount.com"
    )
    client, blob = _client_with_credentials(credentials)
    blob.generate_signed_url.return_value = "https://signed.example/x.png"

    def _fake_refresh(request: object) -> None:
        # What `storage.Client` itself holds: a token narrowed to
        # `Client.SCOPE` (devstorage.*), which IAM signBlob rejects.
        credentials.token = "devstorage-scoped-token"

    monkeypatch.setattr(credentials, "refresh", MagicMock(side_effect=_fake_refresh))
    monkeypatch.setattr("google.auth.transport.requests.Request", lambda: MagicMock())

    signing_credentials = MagicMock()
    signing_credentials.token = "cloud-platform-scoped-token"
    default = MagicMock(return_value=(signing_credentials, "a-project"))
    monkeypatch.setattr("google.auth.default", default)
    return client, blob, default, credentials


def test_signed_url_uses_iam_signblob_for_a_workload_identity_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Cloud Run credential carries no ``signer``, so it must sign via signBlob."""
    client, blob, _, _ = _workload_identity_client(monkeypatch)

    GcsStorageBackend(_client=client).create_signed_url("avatars", "x.png", 3600)

    _, kwargs = blob.generate_signed_url.call_args
    assert kwargs["service_account_email"] == "sa@a-project.iam.gserviceaccount.com"


def test_signed_url_signs_with_a_cloud_platform_token_not_the_storage_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The signBlob token must be minted for ``cloud-platform``, not reused from the client.

    ``storage.Client.SCOPE`` is the three ``devstorage.*`` scopes only, so on
    Cloud Run the credential the client holds refreshes to a token narrowed to
    those. Handing that token to IAM signBlob is refused:

        Error calling the IAM signBytes API: 403 "Request had insufficient
        authentication scopes." reason: ACCESS_TOKEN_SCOPE_INSUFFICIENT,
        method: google.iam.credentials.v1.IAMCredentials.SignBlob

    `_avatar_url_for` swallows that by design, so every profile in staging
    rendered its initials and a picture the user had just uploaded was never
    visible anywhere. Observed in `lemely-backend-staging` logs (2026-09-05
    and 2026-09-08), with `roles/iam.serviceAccountTokenCreator` bound and
    `iamcredentials.googleapis.com` enabled — the scope was the only thing
    missing.
    """
    client, blob, default, _ = _workload_identity_client(monkeypatch)

    GcsStorageBackend(_client=client).create_signed_url("avatars", "x.png", 3600)

    assert default.call_args.kwargs["scopes"] == ["https://www.googleapis.com/auth/cloud-platform"]
    _, kwargs = blob.generate_signed_url.call_args
    assert kwargs["access_token"] == "cloud-platform-scoped-token"
    assert kwargs["access_token"] != "devstorage-scoped-token"


def test_signed_url_reports_missing_adc_when_minting_the_signing_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No ADC at all for the signing token is a named error, not a bare traceback."""
    client, _, default, _ = _workload_identity_client(monkeypatch)
    default.side_effect = DefaultCredentialsError("no ADC")

    with pytest.raises(ExternalServiceError, match="signed URL"):
        GcsStorageBackend(_client=client).create_signed_url("avatars", "x.png", 3600)


def test_signed_url_disposition_attachment() -> None:
    """``disposition`` is signed into the URL as ``response-content-disposition`` (SC-22).

    Signed for real, offline, with a generated service-account key and a real
    ``storage.Client`` (explicit credentials: no network, no ADC), so the test
    reads the parameter out of the URL GCS would honour rather than out of a
    mock's call arguments. Without a disposition the URL carries none, so the
    avatar links are unchanged.
    """
    from urllib.parse import parse_qs, urlsplit

    from google.cloud import storage

    client = storage.Client(project="a-project", credentials=_real_service_account_credentials())
    backend = GcsStorageBackend(_client=client)
    disposition = "attachment; filename=\"degree.pdf\"; filename*=UTF-8''degree.pdf"

    attached = parse_qs(
        urlsplit(
            backend.create_signed_url(
                "lemely-tutor-evidence", "tutor-evidence/t/e.pdf", 300, disposition=disposition
            )
        ).query
    )
    plain = parse_qs(urlsplit(backend.create_signed_url("avatars", "x.png", 3600)).query)

    # V4 signs the whole canonical query string, so this parameter is covered
    # by X-Goog-Signature: an edited disposition fails GCS's signature check.
    assert attached["response-content-disposition"] == [disposition]
    assert attached["X-Goog-Expires"] == ["300"]
    assert attached["X-Goog-Signature"][0]
    assert "response-content-disposition" not in plain
    assert plain["X-Goog-Expires"] == ["3600"]


def test_signed_url_without_disposition_passes_no_response_disposition() -> None:
    """The mocked call shape: no ``response_disposition`` kwarg unless one is asked for."""
    client, blob = _client_with_credentials(_real_service_account_credentials())
    blob.generate_signed_url.return_value = "https://signed.example/x"
    backend = GcsStorageBackend(_client=client)

    backend.create_signed_url("avatars", "x.png", 3600)
    assert "response_disposition" not in blob.generate_signed_url.call_args.kwargs

    backend.create_signed_url("ev", "e.pdf", 300, disposition="attachment")
    assert blob.generate_signed_url.call_args.kwargs["response_disposition"] == "attachment"


def test_signed_url_content_type() -> None:
    """T10 review R8: ``content_type`` is signed in as ``response-content-type``.

    Signed for real, offline, like the disposition test above: GCS then answers
    with the DB row's sniffed type whatever the object's stored metadata says,
    and an edited type fails the V4 signature. Without one the URL has none.
    """
    from urllib.parse import parse_qs, urlsplit

    from google.cloud import storage

    client = storage.Client(project="a-project", credentials=_real_service_account_credentials())
    backend = GcsStorageBackend(_client=client)

    typed = parse_qs(
        urlsplit(
            backend.create_signed_url(
                "lemely-tutor-evidence",
                "tutor-evidence/t/e.png",
                300,
                disposition="attachment",
                content_type="image/png",
            )
        ).query
    )
    plain = parse_qs(urlsplit(backend.create_signed_url("avatars", "x.png", 3600)).query)

    assert typed["response-content-type"] == ["image/png"]
    assert typed["response-content-disposition"] == ["attachment"]
    assert "response-content-type" not in plain


def test_signed_url_content_type_call_shape() -> None:
    """The mocked call shape: ``response_type`` only when a type is asked for."""
    client, blob = _client_with_credentials(_real_service_account_credentials())
    blob.generate_signed_url.return_value = "https://signed.example/x"
    backend = GcsStorageBackend(_client=client)

    backend.create_signed_url("avatars", "x.png", 3600)
    assert "response_type" not in blob.generate_signed_url.call_args.kwargs

    backend.create_signed_url("ev", "e.pdf", 300, content_type="application/pdf")
    assert blob.generate_signed_url.call_args.kwargs["response_type"] == "application/pdf"


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


# ---------------------------------------------------------------------------
# The tutor evidence bucket (SC-22). GCS bucket names are global, so the
# settings default `lemely-tutor-evidence` is a name anyone can create: the gcs
# backend refuses it outright, and before its first use of whichever evidence
# bucket it is given it reads that bucket's settings and refuses one that does
# not enforce public access prevention and uniform bucket-level access. The
# bucket metadata below is a real `storage.Bucket` parsed from a buckets.get
# resource, so the attribute names are the SDK's, not a mock's.
# ---------------------------------------------------------------------------

_EVIDENCE = "proj-1234-tutor-evidence-staging"
_EVIDENCE_PATH = "tutor-evidence/t/e.pdf"

_EVIDENCE_OPS: dict[str, Callable[[GcsStorageBackend], object]] = {
    "upload": lambda b: b.upload(_EVIDENCE, _EVIDENCE_PATH, b"%PDF-1.4", "application/pdf"),
    "download": lambda b: b.download(_EVIDENCE, _EVIDENCE_PATH),
    "delete": lambda b: b.delete(_EVIDENCE, _EVIDENCE_PATH),
    "create_signed_url": lambda b: b.create_signed_url(
        _EVIDENCE, _EVIDENCE_PATH, 300, disposition="attachment"
    ),
}


def _bucket_metadata(public_access_prevention: str | None, *, uniform: bool) -> storage.Bucket:
    """What ``Client.get_bucket`` returns for a bucket with these two settings, offline."""
    iam_configuration: dict[str, object] = {"uniformBucketLevelAccess": {"enabled": uniform}}
    if public_access_prevention is not None:
        iam_configuration["publicAccessPrevention"] = public_access_prevention
    bucket = storage.Bucket(MagicMock(), name=_EVIDENCE)
    bucket._set_properties({"name": _EVIDENCE, "iamConfiguration": iam_configuration})
    return bucket


def _evidence_client(metadata: storage.Bucket) -> tuple[MagicMock, MagicMock]:
    client, blob = _client_with_blob()
    client.get_bucket.return_value = metadata
    blob.download_as_bytes.return_value = b"%PDF-1.4"
    blob.generate_signed_url.return_value = "https://signed.example/e.pdf"
    return client, blob


@pytest.mark.parametrize("spell", [str, lambda name: f" {name} ", str.upper])
def test_gcs_backend_refuses_default_evidence_bucket(spell: Callable[[str], str]) -> None:
    """The settings default, however it is written, is refused when the backend is built."""
    default = StorageSettings().tutor_evidence_bucket
    client = MagicMock()
    with pytest.raises(ConfigError, match="LEMELY_STORAGE__TUTOR_EVIDENCE_BUCKET") as caught:
        GcsStorageBackend(tutor_evidence_bucket=spell(default), _client=client)
    assert default in str(caught.value)
    # Refused before anything is built or called.
    assert client.mock_calls == []


def test_gcs_backend_accepts_a_project_owned_evidence_bucket_without_touching_it() -> None:
    """Construction stays offline (``get_storage_backend`` relies on it): nothing is called."""
    client = MagicMock()
    GcsStorageBackend(project="proj-1234", tutor_evidence_bucket=_EVIDENCE, _client=client)
    assert client.mock_calls == []


@pytest.mark.parametrize(
    ("public_access_prevention", "uniform"),
    [("unspecified", True), ("inherited", True), (None, True), ("enforced", False)],
)
@pytest.mark.parametrize("op", sorted(_EVIDENCE_OPS))
def test_evidence_bucket_public_access_prevention_enforced(
    op: str, public_access_prevention: str | None, uniform: bool
) -> None:
    client, blob = _evidence_client(_bucket_metadata(public_access_prevention, uniform=uniform))
    backend = GcsStorageBackend(tutor_evidence_bucket=_EVIDENCE, _client=client)

    with pytest.raises(
        ExternalServiceError, match=f"Refusing to use the tutor evidence bucket {_EVIDENCE}"
    ):
        _EVIDENCE_OPS[op](backend)

    client.get_bucket.assert_called_once_with(_EVIDENCE, timeout=30.0)
    # Fail closed: no object operation reached the bucket.
    client.bucket.assert_not_called()
    assert blob.mock_calls == []


@pytest.mark.parametrize("op", sorted(_EVIDENCE_OPS))
def test_private_evidence_bucket_is_checked_once_then_used(op: str) -> None:
    client, blob = _evidence_client(_bucket_metadata("enforced", uniform=True))
    backend = GcsStorageBackend(tutor_evidence_bucket=_EVIDENCE, _client=client)

    _EVIDENCE_OPS[op](backend)
    _EVIDENCE_OPS[op](backend)

    client.get_bucket.assert_called_once_with(_EVIDENCE, timeout=30.0)
    assert client.bucket.call_count == 2
    assert all(c.args == (_EVIDENCE,) for c in client.bucket.call_args_list)


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (NotFound("no such bucket"), "does not exist"),
        (Forbidden("caller lacks storage.buckets.get"), "storage.buckets.get"),
    ],
)
def test_unreadable_evidence_bucket_fails_closed_and_is_checked_again(
    error: GoogleAPICallError, message: str
) -> None:
    """A missing or unreadable bucket refuses the operation, and nothing is cached.

    Not cached so that once the operator runs ``scripts/gcp-bootstrap.sh`` the
    next upload succeeds without a restart.
    """
    client, blob = _client_with_blob()
    client.get_bucket.side_effect = error
    backend = GcsStorageBackend(tutor_evidence_bucket=_EVIDENCE, _client=client)

    for _ in range(2):
        with pytest.raises(ExternalServiceError, match=message):
            _EVIDENCE_OPS["upload"](backend)

    assert client.get_bucket.call_count == 2
    client.bucket.assert_not_called()


def test_evidence_check_leaves_the_other_buckets_alone() -> None:
    """Regression guard: uploads and avatars are not checked (their routes are unchanged)."""
    client, blob = _evidence_client(_bucket_metadata("unspecified", uniform=False))
    backend = GcsStorageBackend(tutor_evidence_bucket=_EVIDENCE, _client=client)

    backend.upload("proj-1234-avatars-staging", "a.png", b"png", "image/png")
    backend.download("proj-1234-uploads-staging", "k/scan.pdf")
    backend.delete("proj-1234-uploads-staging", "k/scan.pdf")

    client.get_bucket.assert_not_called()
    assert client.bucket.call_count == 3
