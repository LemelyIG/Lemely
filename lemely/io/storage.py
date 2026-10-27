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
    """Upload, download, delete and signed-URL operations against object storage."""

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

    def create_signed_url(
        self,
        bucket: str,
        object_path: str,
        expires_in: int,
        *,
        disposition: str | None = None,
        content_type: str | None = None,
    ) -> str:
        """Return a URL that reads ``object_path`` for ``expires_in`` seconds.

        Exists for two consumers whose bytes must be reachable without the
        caller's session, for a limited time: profile pictures (the browser
        fetches the image directly) and tutor evidence files, which a platform
        admin downloads through a 300 s link (SPEC §b.2 A2, THREAT-MODEL SC-22).
        Every other consumer downloads through the backend instead, which is
        why this is the only read that produces a URL rather than bytes.

        ``disposition`` is a ``Content-Disposition`` value the response must
        carry (``attachment; filename=...`` for evidence, so a browser saves the
        file rather than rendering it). ``None`` leaves the response as the
        object is stored, which is what avatars need. ``content_type`` is the
        ``Content-Type`` the response must carry whatever the object's stored
        metadata says (SC-22: an evidence file's type from its database row,
        which was sniffed from its bytes); ``None`` leaves the stored type.

        Raises :class:`~lemely.runtime.errors.ExternalServiceError` when the
        configured credentials cannot sign. Callers that merely *display* an
        avatar treat any failure as "no avatar" rather than an error — see
        ``lemely.web.routers.me._avatar_url_for`` — because a profile read
        must not fail just because object storage is unreachable.
        """
        ...


def check_storage(settings: Settings, *, no_network: bool) -> tuple[bool, str]:
    """``lemely doctor``'s storage check: ``(passed, detail)``.

    ``local``: the root is writable. ``gcs``: application-default credentials
    resolve and — unless ``no_network`` — both buckets answer a metadata read.
    Both, because uploads and avatars live in separate buckets and a deploy
    that provisioned only one fails on whichever route touches the other.
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
    buckets = (settings.storage.bucket, settings.storage.avatar_bucket)
    if no_network:
        return True, f"gcs://{' + '.join(buckets)} (not probed: --no-network)"
    try:
        from google.cloud import storage

        client = storage.Client(project=settings.storage.gcs_project)
        for name in buckets:
            client.get_bucket(name)
    except Exception as exc:  # any bucket-probe failure surfaces as the detail
        return False, f"buckets {' + '.join(buckets)}: {exc}"
    return True, f"gcs://{' + '.join(buckets)}"


def check_tutor_evidence_storage(settings: Settings, *, no_network: bool) -> tuple[bool, str]:
    """``lemely doctor``'s tutor evidence check: ``(passed, detail)``.

    Separate from :func:`check_storage` because the evidence bucket is judged
    differently: ``local``: its directory under the storage root is writable.
    ``gcs``: the checks the backend runs before its first evidence operation
    (:mod:`lemely.io.storage_gcs`, SC-22). The placeholder name and an unset
    ``storage.gcs_project_number`` fail offline; unless ``no_network``, the
    bucket must then enforce public access prevention and uniform access and
    belong to that project. The result is the privacy-and-owner decision the
    upload route would get, not merely that the bucket answers, so a deploy
    whose bootstrap was never re-run shows here instead of as a 503 on upload.
    """
    bucket = settings.storage.tutor_evidence_bucket
    if settings.storage.backend == "local":
        directory = settings.paths.output_dir / "storage" / bucket
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return False, str(exc)
        return os.access(directory, os.W_OK), str(directory)

    from lemely.io.storage_gcs import GcsStorageBackend
    from lemely.runtime.errors import ConfigError

    number = settings.storage.gcs_project_number
    try:
        backend = GcsStorageBackend(
            project=settings.storage.gcs_project,
            tutor_evidence_bucket=bucket,
            project_number=number,
        )
    except ConfigError as exc:
        return False, str(exc)
    if number is None:
        return False, (
            f"gcs://{bucket}: LEMELY_STORAGE__GCS_PROJECT_NUMBER is not set, so every "
            "evidence upload is refused (the bucket cannot be shown to be this project's)"
        )
    if no_network:
        return True, f"gcs://{bucket} (privacy and owner not probed: --no-network)"
    try:
        backend.check_tutor_evidence_bucket()
    except Exception as exc:  # any probe failure (refusal, ADC, network) surfaces as the detail
        return False, f"gcs://{bucket}: {exc}"
    return True, f"gcs://{bucket} (private; owned by project {number})"


__all__ = [
    "StorageBackend",
    "StorageObjectNotFoundError",
    "check_storage",
    "check_tutor_evidence_storage",
]
