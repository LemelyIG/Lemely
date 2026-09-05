"""Object storage seam.

:class:`StorageBackend` is the Protocol the Google Cloud Storage backend
(:mod:`lemely.io.storage_gcs`), the local filesystem backend
(:mod:`lemely.io.storage_local`) and the test fake implement.

The deployed backend is Google Cloud Storage. The public "How Lemely handles
your data" page says so in as many words, and
``web/tests/unit/dataHandling.test.ts`` asserts that this module and that
copy still agree — so if this seam is ever pointed somewhere else, fix
``web/src/portals/marketing/dataHandling.ts`` in the same change rather than
relaxing the test. Where a user's scan is kept is a disclosure, not an
implementation detail.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from lemely.runtime.config import Settings


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


def check_storage(settings: Settings, *, no_network: bool) -> tuple[bool, str]:
    """``lemely doctor``'s storage check: ``(passed, detail)``.

    ``local``: the root is writable. ``gcs``: application-default credentials
    resolve and — unless ``no_network`` — the bucket answers a metadata read.
    """
    if settings.storage.backend == "local":
        root = settings.paths.output_dir / "storage"
        try:
            root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return False, str(exc)
        return os.access(root, os.W_OK), str(root)
    try:
        import google.auth

        google.auth.default()
    except Exception as exc:  # any ADC failure surfaces as the detail
        return False, f"application-default credentials: {exc}"
    if no_network:
        return True, f"gcs://{settings.storage.bucket} (not probed: --no-network)"
    try:
        from google.cloud import storage

        storage.Client().get_bucket(settings.storage.bucket)
    except Exception as exc:  # any bucket-probe failure surfaces as the detail
        return False, f"bucket {settings.storage.bucket}: {exc}"
    return True, f"gcs://{settings.storage.bucket}"


__all__ = ["StorageBackend", "StorageObjectNotFoundError", "check_storage"]
