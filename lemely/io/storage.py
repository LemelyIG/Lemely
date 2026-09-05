"""Supabase Storage backend seam (P2.5).

The student self-mark upload path stores scans (and optional mark-scheme
siblings) in Supabase Storage rather than on local disk. :class:`StorageBackend`
is the Protocol both the real HTTP client and the test fake implement, mirroring
the precedent set by :mod:`lemely.auth.gotrue` for GoTrue: a thin sync ``httpx``
client authenticated with the service-role key, raising
:class:`~lemely.runtime.errors.ExternalServiceError` on any non-2xx response.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, cast

import httpx

from lemely.runtime.errors import AuthError, ExternalServiceError

if TYPE_CHECKING:
    from lemely.runtime.config import Settings

_TIMEOUT_SECONDS = 10.0
# Uploads/downloads move whole PDFs (up to the 25MB cap) rather than small JSON
# bodies, so they get a longer timeout than the GoTrue-style metadata calls.
_TRANSFER_TIMEOUT_SECONDS = 30.0


def _is_missing_key(response: httpx.Response) -> bool:
    """Detect a missing-object response the real Supabase Storage API's way.

    The local/self-hosted Storage API answers a missing object with HTTP
    **400** (not 404) and a JSON body like ``{"statusCode": "404", "error":
    "not_found", "message": "Object not found", "code": "NoSuchKey"}`` —
    confirmed against a live local stack (D2.8). Checking only the outer HTTP
    status therefore never actually distinguishes "no such object" from any
    other 4xx failure. ``code == "NoSuchKey"`` specifically (not
    ``"NoSuchBucket"``, a real misconfiguration that should still surface as
    :class:`~lemely.runtime.errors.ExternalServiceError`) is the reliable
    signal. Defensive against a non-JSON or differently-shaped body — treated
    as "not the missing-key case" rather than raising here.
    """
    if response.status_code != 400:
        return False
    try:
        body = response.json()
    except ValueError:
        return False
    return isinstance(body, dict) and body.get("code") == "NoSuchKey"


class StorageObjectNotFoundError(KeyError):
    """Raised by :meth:`StorageBackend.download` for a missing object.

    Distinct from :class:`~lemely.runtime.errors.ExternalServiceError` so
    callers can distinguish "no such object" (an expected, handled case — e.g.
    an optional sibling mark-scheme upload) from a genuine backend failure.
    Both :class:`HttpStorageBackend` and the hermetic fake raise this same
    type, matching the shared-fake precedent set for GoTrue.
    """


class StorageBackend(Protocol):
    """Upload, download, and signed-URL operations against object storage."""

    def upload(
        self,
        bucket: str,
        object_path: str,
        data: bytes,
        content_type: str | None,
    ) -> None:
        """Write ``data`` to ``object_path`` in ``bucket``."""
        ...

    def download(self, bucket: str, object_path: str) -> bytes:
        """Return the bytes stored at ``object_path`` in ``bucket``."""
        ...

    def create_signed_url(self, bucket: str, object_path: str, expires_in: int) -> str:
        """Return a time-limited signed URL for ``object_path`` in ``bucket``."""
        ...


class HttpStorageBackend:
    """Real :class:`StorageBackend` backed by the Supabase Storage REST API.

    Uses synchronous ``httpx`` to match the codebase's sync call style (see
    :class:`~lemely.auth.gotrue.HttpGoTrueBackend`). Requires the service-role
    key to be present in :class:`~lemely.runtime.config.SupabaseSettings`; a
    missing key raises :class:`~lemely.runtime.errors.AuthError` at call time via
    :meth:`_service_key`, matching the GoTrue precedent.
    """

    def __init__(self, settings: Settings) -> None:
        """Initialise the client against ``settings.supabase``."""
        self._settings = settings
        self._base_url = settings.supabase.url.rstrip("/")

    def _service_key(self) -> str:
        key = self._settings.supabase.service_role_key
        if key is None:
            raise AuthError("Supabase service-role key is not configured.")
        return key.get_secret_value()

    def upload(
        self,
        bucket: str,
        object_path: str,
        data: bytes,
        content_type: str | None,
    ) -> None:
        """Upload ``data`` to ``{bucket}/{object_path}`` (service-role key)."""
        service_key = self._service_key()
        try:
            response = httpx.post(
                f"{self._base_url}/storage/v1/object/{bucket}/{object_path}",
                content=data,
                headers={
                    "Authorization": f"Bearer {service_key}",
                    "apikey": service_key,
                    "Content-Type": content_type or "application/octet-stream",
                },
                timeout=_TRANSFER_TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as exc:
            raise ExternalServiceError(f"Storage upload request failed: {exc}") from exc
        if response.status_code >= 300:
            raise ExternalServiceError(
                f"Storage upload failed ({response.status_code}): {response.text}"
            )

    def download(self, bucket: str, object_path: str) -> bytes:
        """Download the bytes at ``{bucket}/{object_path}`` (service-role key)."""
        service_key = self._service_key()
        try:
            response = httpx.get(
                f"{self._base_url}/storage/v1/object/{bucket}/{object_path}",
                headers={
                    "Authorization": f"Bearer {service_key}",
                    "apikey": service_key,
                },
                timeout=_TRANSFER_TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as exc:
            raise ExternalServiceError(f"Storage download request failed: {exc}") from exc
        if response.status_code == 404 or _is_missing_key(response):
            raise StorageObjectNotFoundError(f"No object at {bucket}/{object_path}")
        if response.status_code >= 300:
            raise ExternalServiceError(
                f"Storage download failed ({response.status_code}): {response.text}"
            )
        return response.content

    def create_signed_url(self, bucket: str, object_path: str, expires_in: int) -> str:
        """Create a signed URL for ``{bucket}/{object_path}`` (service-role key)."""
        service_key = self._service_key()
        try:
            response = httpx.post(
                f"{self._base_url}/storage/v1/object/sign/{bucket}/{object_path}",
                json={"expiresIn": expires_in},
                headers={
                    "Authorization": f"Bearer {service_key}",
                    "apikey": service_key,
                },
                timeout=_TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as exc:
            raise ExternalServiceError(f"Storage sign request failed: {exc}") from exc
        if response.status_code >= 300:
            raise ExternalServiceError(
                f"Storage sign failed ({response.status_code}): {response.text}"
            )
        body = cast("dict[str, object]", response.json())
        try:
            signed_url = str(body["signedURL"])
        except KeyError as exc:
            raise ExternalServiceError(f"Malformed Storage sign response: {exc}") from exc
        if signed_url.startswith("/"):
            return f"{self._base_url}{signed_url}"
        return signed_url


class GcsStorageBackend:
    """Real :class:`StorageBackend` backed by Google Cloud Storage.

    The alternative production backend selected by
    ``StorageSettings.provider == "gcs"`` (see
    :func:`~lemely.web.deps.get_storage_backend`) — Supabase Storage remains the
    default. Authenticates via Application Default Credentials (ADC): a service
    account attached to the Cloud Run/GCE/GKE workload in production, or
    ``gcloud auth application-default login`` locally for :meth:`upload` and
    :meth:`download`. No key is read from
    :class:`~lemely.runtime.config.StorageSettings` for this path.

    :meth:`create_signed_url` is stricter: it requires an actual service-account
    credential — either a service-account JSON key (which can sign locally) or
    an attached/workload-identity service account (which signs via IAM
    ``signBlob``, see that method's docstring). Local user credentials from
    ``gcloud auth application-default login`` are neither, so a deployment that
    needs to sign avatar/upload URLs needs a real service account configured,
    not just any ADC.

    The ``google-cloud-storage``/``google-auth``/``google-api-core`` imports are
    deliberately **lazy** — inside :meth:`_client_and_credentials` and
    :meth:`create_signed_url` rather than at module scope — so a deployment
    running the default Supabase backend never imports this dependency at all,
    matching :class:`HttpStorageBackend`'s zero-cost-when-unused shape.
    """

    def __init__(self, settings: Settings) -> None:
        """Initialise against ``settings.storage`` (``gcs_project``, if set)."""
        self._settings = settings
        self._cached_client: object | None = None
        self._cached_credentials: object | None = None

    def _client_and_credentials(
        self,
    ) -> tuple[object, object]:
        """Return a GCS client and the ADC credentials that back it.

        Cached on the instance after the first call — ADC discovery and
        ``storage.Client`` construction are both work worth doing once per
        backend instance rather than once per operation.

        Returning the credentials alongside the client (rather than reaching
        into a private client attribute later) is what lets
        :meth:`create_signed_url` decide, without any further Google-API call,
        whether this credential can sign locally or must go through IAM
        signBlob.
        """
        if self._cached_client is None or self._cached_credentials is None:
            import google.auth
            from google.cloud import storage

            credentials, discovered_project = google.auth.default()
            project = self._settings.storage.gcs_project or discovered_project
            self._cached_client = storage.Client(project=project, credentials=credentials)
            self._cached_credentials = credentials
        return self._cached_client, self._cached_credentials

    def upload(
        self,
        bucket: str,
        object_path: str,
        data: bytes,
        content_type: str | None,
    ) -> None:
        """Upload ``data`` to ``{bucket}/{object_path}`` via the GCS client library."""
        from google.api_core import exceptions as gcs_exceptions

        client, _ = self._client_and_credentials()
        try:
            blob = client.bucket(bucket).blob(object_path)  # type: ignore[attr-defined]
            blob.upload_from_string(data, content_type=content_type or "application/octet-stream")
        except gcs_exceptions.GoogleAPICallError as exc:
            raise ExternalServiceError(f"GCS upload failed: {exc}") from exc

    def download(self, bucket: str, object_path: str) -> bytes:
        """Download the bytes at ``{bucket}/{object_path}`` via the GCS client library."""
        from google.api_core import exceptions as gcs_exceptions

        client, _ = self._client_and_credentials()
        try:
            blob = client.bucket(bucket).blob(object_path)  # type: ignore[attr-defined]
            return cast("bytes", blob.download_as_bytes())
        except gcs_exceptions.NotFound as exc:
            raise StorageObjectNotFoundError(f"No object at {bucket}/{object_path}") from exc
        except gcs_exceptions.GoogleAPICallError as exc:
            raise ExternalServiceError(f"GCS download failed: {exc}") from exc

    def create_signed_url(self, bucket: str, object_path: str, expires_in: int) -> str:
        """Create a V4 signed URL for ``{bucket}/{object_path}``.

        A service-account JSON key credential (:class:`google.oauth2.service_account.Credentials`)
        can sign a URL entirely locally — it exposes a ``signer`` that can sign
        bytes offline, and ``google-cloud-storage`` uses that automatically. A
        workload-identity credential (e.g. :class:`google.auth.compute_engine.Credentials`
        on Cloud Run/GCE/GKE) has no ``signer`` at all, so
        ``google-cloud-storage`` cannot sign locally; passing
        ``service_account_email``/``access_token`` explicitly instead makes the
        library sign through the IAM ``signBlob`` API using that access token,
        which is the documented workaround for exactly this credential shape.
        The access token must be fresh, hence the explicit
        :meth:`~google.auth.credentials.Credentials.refresh` before checking it.

        Note that ``getattr(credentials, "private_key", None)`` is **not** a
        valid way to tell these apart — no google-auth credential type exposes
        a public ``private_key`` attribute (``service_account.Credentials``
        keeps it behind ``signer``), so that check was always true and this
        method always took the IAM signBlob branch, even for a real JSON-key
        credential that could have signed locally. ``hasattr(credentials,
        "signer")`` is the real discriminator.

        Neither shape applies to plain user credentials
        (:class:`google.oauth2.credentials.Credentials`, e.g. from
        ``gcloud auth application-default login``) — no ``signer`` and no
        ``service_account_email`` — which cannot sign a URL at all; that raises
        :class:`~lemely.runtime.errors.ExternalServiceError` naming the problem
        rather than failing later with an ``AttributeError`` on
        ``service_account_email``.
        """
        from datetime import timedelta

        import google.auth.transport.requests
        from google.api_core import exceptions as gcs_exceptions

        client, credentials = self._client_and_credentials()
        try:
            blob = client.bucket(bucket).blob(object_path)  # type: ignore[attr-defined]
            sign_kwargs: dict[str, object] = {}
            if not hasattr(credentials, "signer"):
                if not hasattr(credentials, "service_account_email"):
                    raise ExternalServiceError(
                        "Cannot create a signed URL: the configured Application "
                        "Default Credentials are user credentials (e.g. from "
                        "`gcloud auth application-default login`), which can "
                        "neither sign locally nor use IAM signBlob. Configure a "
                        "service-account JSON key or an attached service account."
                    )
                credentials.refresh(google.auth.transport.requests.Request())  # type: ignore[attr-defined]
                sign_kwargs["service_account_email"] = credentials.service_account_email
                sign_kwargs["access_token"] = credentials.token  # type: ignore[attr-defined]
            return cast(
                "str",
                blob.generate_signed_url(
                    version="v4",
                    expiration=timedelta(seconds=expires_in),
                    method="GET",
                    **sign_kwargs,
                ),
            )
        except gcs_exceptions.GoogleAPICallError as exc:
            raise ExternalServiceError(f"GCS sign failed: {exc}") from exc


__all__ = [
    "GcsStorageBackend",
    "HttpStorageBackend",
    "StorageBackend",
    "StorageObjectNotFoundError",
]
