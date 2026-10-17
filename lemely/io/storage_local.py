"""Filesystem :class:`~lemely.io.storage.StorageBackend` for dev and compose (DS7).

Objects live under ``<root>/<bucket>/<object_path>``. This is the default
backend (``StorageSettings.backend == "local"``) so a fresh clone, ``make up``
and the hermetic test-suite need no cloud credentials. Production selects
:class:`~lemely.io.storage_gcs.GcsStorageBackend` instead.

The one rule that matters here is the same one the routers already apply to
client filenames: a key must never resolve outside the root. Keys are built
from server-generated UUIDs and ``safe_upload_name`` output, so an escape is
a bug — it raises rather than being silently rewritten.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from lemely.io.storage import StorageObjectNotFoundError

if TYPE_CHECKING:
    from pathlib import Path


class LocalFileStorageBackend:
    """Dict-of-files: one file per object under ``root``."""

    def __init__(self, root: Path) -> None:
        """Bind to ``root``; created lazily on first write."""
        self._root = root.resolve()

    def _path(self, bucket: str, object_path: str) -> Path:
        candidate = (self._root / bucket / object_path).resolve()
        if not candidate.is_relative_to(self._root / bucket):
            raise ValueError(f"Object key {object_path!r} escapes the storage root.")
        return candidate

    def upload(
        self,
        bucket: str,
        object_path: str,
        data: bytes,
        content_type: str | None,
    ) -> None:
        """Write ``data`` to ``<root>/<bucket>/<object_path>``; ``content_type`` is unused."""
        target = self._path(bucket, object_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def download(self, bucket: str, object_path: str) -> bytes:
        """Return the stored bytes, or raise :class:`StorageObjectNotFoundError`."""
        target = self._path(bucket, object_path)
        try:
            return target.read_bytes()
        except FileNotFoundError as exc:
            raise StorageObjectNotFoundError(f"No object at {bucket}/{object_path}") from exc

    def create_signed_url(self, bucket: str, object_path: str, expires_in: int) -> str:
        """Return a ``data:`` URL carrying the object's bytes inline.

        A local directory has nothing to sign and no origin to serve from, so
        the honest options were to raise (dev and CI would then never render an
        avatar, and the feature would look broken everywhere but staging) or to
        hand the browser the bytes directly. This does the latter: a ``data:``
        URL renders in an ``<img>`` exactly like a signed one, with no extra
        route to maintain.

        ``expires_in`` is deliberately ignored — the URL *is* the content, so
        there is nothing to expire. That is acceptable only because this
        backend is dev, Compose and CI; the bytes never leave the machine that
        already has them on disk. The GCS backend is the one that signs.

        The response is `settings.storage.avatar_max_bytes` at most, inflated
        about a third by base64, and it rides in the profile JSON — fine at
        dev scale, and another reason this backend is not a deployment target.
        """
        import base64
        import mimetypes

        data = self.download(bucket, object_path)
        media_type = mimetypes.guess_type(object_path)[0] or "application/octet-stream"
        return f"data:{media_type};base64,{base64.b64encode(data).decode('ascii')}"

    def delete(self, bucket: str, object_path: str) -> None:
        """Remove the file if present. Missing is not an error."""
        target = self._path(bucket, object_path)
        target.unlink(missing_ok=True)


__all__ = ["LocalFileStorageBackend"]
