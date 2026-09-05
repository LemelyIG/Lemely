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

    def __init__(self, *, project: str | None = None, _client: Any = None) -> None:
        """Optionally inject a client (tests); otherwise one is built on first use.

        ``project`` is ``settings.storage.gcs_project``: Application Default
        Credentials usually carry or infer a project on their own, so this is
        only needed when that inference is wrong or absent (a user-account
        credential with no associated quota project).
        """
        self._raw_client: Any = _client
        self._project = project

    def _client(self) -> Any:
        if self._raw_client is None:
            try:
                self._raw_client = storage.Client(project=self._project)
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
            raise StorageObjectNotFoundError(f"No object at {bucket}/{object_path}: {exc}") from exc
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

    def create_signed_url(self, bucket: str, object_path: str, expires_in: int) -> str:
        """Create a V4 signed URL for ``{bucket}/{object_path}``.

        A service-account JSON key credential exposes a ``signer`` and can sign
        entirely locally; ``google-cloud-storage`` uses it automatically. A
        workload-identity credential (Cloud Run/GCE/GKE) has no ``signer`` at
        all, so passing ``service_account_email``/``access_token`` explicitly
        makes the library sign through the IAM ``signBlob`` API instead — the
        documented workaround for that credential shape. The token must be
        fresh, hence the explicit ``refresh`` first.

        ``hasattr(credentials, "signer")`` is the discriminator, and the choice
        matters: ``getattr(credentials, "private_key", None)`` is not a valid
        test, because no google-auth credential exposes a public
        ``private_key`` (``service_account.Credentials`` keeps it behind
        ``signer``). That check was always falsy, so an earlier version always
        took the signBlob branch even for a JSON key that could have signed
        offline.

        Plain user credentials (``gcloud auth application-default login``) have
        neither, and cannot sign at all — raised here by name rather than left
        to fail later with an ``AttributeError`` on ``service_account_email``.

        Ported from the implementation #220 added; on Cloud Run the runtime
        service account additionally needs ``roles/iam.serviceAccountTokenCreator``
        for the signBlob call to succeed.
        """
        from datetime import timedelta

        import google.auth.transport.requests

        client = self._client()
        credentials = getattr(client, "_credentials", None)
        try:
            blob = client.bucket(bucket).blob(object_path)
            sign_kwargs: dict[str, Any] = {}
            if credentials is not None and not hasattr(credentials, "signer"):
                if not hasattr(credentials, "service_account_email"):
                    raise ExternalServiceError(
                        "Cannot create a signed URL: the configured Application "
                        "Default Credentials are user credentials (e.g. from "
                        "`gcloud auth application-default login`), which can "
                        "neither sign locally nor use IAM signBlob. Configure a "
                        "service-account JSON key or an attached service account."
                    )
                credentials.refresh(google.auth.transport.requests.Request())
                sign_kwargs["service_account_email"] = credentials.service_account_email
                sign_kwargs["access_token"] = credentials.token
            signed: str = blob.generate_signed_url(
                version="v4",
                expiration=timedelta(seconds=expires_in),
                method="GET",
                **sign_kwargs,
            )
        except GoogleAPICallError as exc:
            raise ExternalServiceError(f"GCS sign failed: {exc}") from exc
        return signed


__all__ = ["GcsStorageBackend"]
