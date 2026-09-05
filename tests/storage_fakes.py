"""Hermetic fake for StorageBackend tests (no network).

Shared by any test that needs a :class:`~lemely.io.storage.StorageBackend`
double, mirroring the role ``tests/auth_fakes.py`` plays for
:class:`~lemely.auth.gotrue.GoTrueBackend`.
"""

from __future__ import annotations

from lemely.io.storage import StorageObjectNotFoundError
from lemely.runtime.errors import ExternalServiceError


class FakeStorageBackend:
    """In-memory :class:`~lemely.io.storage.StorageBackend`: dict-backed store.

    ``upload`` is create-only, matching :class:`~lemely.io.storage_gcs.
    GcsStorageBackend`'s ``if_generation_match=0`` (spec §4.1: every key this
    codebase writes carries a server-generated UUID, so a write to an
    existing key is a bug, not a legitimate overwrite). An earlier version of
    this fake silently overwrote any key, which is why a real create-only
    violation in ``upload_scheme``'s re-upload path (task-8 review) reached
    production without a single test catching it — nothing in this suite
    could fail the way the real backend does. Callers that need to replace an
    object's bytes must ``delete`` the old key first, exactly as the real
    backend requires.
    """

    def __init__(self) -> None:
        self._objects: dict[tuple[str, str], bytes] = {}

    def upload(
        self,
        bucket: str,
        object_path: str,
        data: bytes,
        content_type: str | None,
    ) -> None:
        if (bucket, object_path) in self._objects:
            raise ExternalServiceError(
                f"Object {bucket}/{object_path} already exists; keys must be unique."
            )
        self._objects[(bucket, object_path)] = data

    def download(self, bucket: str, object_path: str) -> bytes:
        try:
            return self._objects[(bucket, object_path)]
        except KeyError as exc:
            raise StorageObjectNotFoundError(f"No object at {bucket}/{object_path}") from exc

    def delete(self, bucket: str, object_path: str) -> None:
        """Idempotent, matching the Protocol: a missing object is not an error.

        The merge with #220 briefly carried two definitions of this method with
        opposite contracts — its seam raised on a missing object, this one does
        not — and Python silently kept the second. This one matches the
        Protocol both real backends implement.
        """
        self._objects.pop((bucket, object_path), None)

    def create_signed_url(self, bucket: str, object_path: str, expires_in: int) -> str:
        """Return a deterministic stand-in URL.

        Deliberately does not check that the object exists: real GCS will sign
        a URL for a key that was never written (the 404 arrives when someone
        follows it), and a fake that raised here would let a test pass that
        production would fail.
        """
        return f"fake://{bucket}/{object_path}?expires_in={expires_in}"


__all__ = ["FakeStorageBackend", "StorageObjectNotFoundError"]
