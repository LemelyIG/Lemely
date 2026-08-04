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
        if response.status_code == 404:
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


__all__ = ["HttpStorageBackend", "StorageBackend", "StorageObjectNotFoundError"]
