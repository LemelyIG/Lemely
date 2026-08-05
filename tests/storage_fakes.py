"""Hermetic fake for StorageBackend tests (no network).

Shared by any test that needs a :class:`~lemely.io.storage.StorageBackend`
double, mirroring the role ``tests/auth_fakes.py`` plays for
:class:`~lemely.auth.gotrue.GoTrueBackend`.
"""

from __future__ import annotations

from lemely.io.storage import StorageObjectNotFoundError


class FakeStorageBackend:
    """In-memory :class:`~lemely.io.storage.StorageBackend`: dict-backed store."""

    def __init__(self) -> None:
        self._objects: dict[tuple[str, str], bytes] = {}

    def upload(
        self,
        bucket: str,
        object_path: str,
        data: bytes,
        content_type: str | None,
    ) -> None:
        self._objects[(bucket, object_path)] = data

    def download(self, bucket: str, object_path: str) -> bytes:
        try:
            return self._objects[(bucket, object_path)]
        except KeyError as exc:
            raise StorageObjectNotFoundError(f"No object at {bucket}/{object_path}") from exc

    def create_signed_url(self, bucket: str, object_path: str, expires_in: int) -> str:
        return f"fake://{bucket}/{object_path}?ttl={expires_in}"


__all__ = ["FakeStorageBackend", "StorageObjectNotFoundError"]
