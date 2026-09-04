"""Object storage seam.

:class:`StorageBackend` is the Protocol the GCS backend, the local backend
and the test fake implement.
"""

from __future__ import annotations

from typing import Protocol


class StorageObjectNotFoundError(KeyError):
    """Raised by :meth:`StorageBackend.download` for a missing object.

    Distinct from :class:`~lemely.runtime.errors.ExternalServiceError` so
    callers can distinguish "no such object" (an expected, handled case — e.g.
    an optional sibling mark-scheme upload) from a genuine backend failure.
    Every :class:`StorageBackend` implementation raises this same type,
    matching the shared-fake precedent set for GoTrue.
    """


class StorageBackend(Protocol):
    """Upload, download, and delete operations against object storage."""

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

    def delete(self, bucket: str, object_path: str) -> None:
        """Remove ``object_path`` from ``bucket``. A missing object is not an error."""
        ...


__all__ = ["StorageBackend", "StorageObjectNotFoundError"]
