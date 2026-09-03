"""Hermetic tests for :class:`lemely.io.storage_local.LocalFileStorageBackend`."""

from __future__ import annotations

from pathlib import Path

import pytest

from lemely.io.storage import StorageObjectNotFoundError
from lemely.io.storage_local import LocalFileStorageBackend


def test_round_trip(tmp_path: Path) -> None:
    backend = LocalFileStorageBackend(tmp_path)
    backend.upload("uploads", "u/p/scan.pdf", b"%PDF-1.4", "application/pdf")
    assert backend.download("uploads", "u/p/scan.pdf") == b"%PDF-1.4"
    assert (tmp_path / "uploads" / "u" / "p" / "scan.pdf").read_bytes() == b"%PDF-1.4"


def test_missing_object_raises_not_found(tmp_path: Path) -> None:
    backend = LocalFileStorageBackend(tmp_path)
    with pytest.raises(StorageObjectNotFoundError):
        backend.download("uploads", "u/p/missing.pdf")


def test_delete_is_idempotent(tmp_path: Path) -> None:
    backend = LocalFileStorageBackend(tmp_path)
    backend.upload("uploads", "u/p/scan.pdf", b"x", None)
    backend.delete("uploads", "u/p/scan.pdf")
    backend.delete("uploads", "u/p/scan.pdf")  # second call must not raise
    with pytest.raises(StorageObjectNotFoundError):
        backend.download("uploads", "u/p/scan.pdf")


@pytest.mark.parametrize("bad_key", ["../escape.pdf", "u/../../escape.pdf", "/abs/escape.pdf"])
def test_key_cannot_escape_root(tmp_path: Path, bad_key: str) -> None:
    backend = LocalFileStorageBackend(tmp_path)
    with pytest.raises(ValueError, match="escapes"):
        backend.upload("uploads", bad_key, b"x", None)
    assert not (tmp_path.parent / "escape.pdf").exists()


def test_settings_default_backend_is_local() -> None:
    from lemely.runtime.config import StorageSettings

    assert StorageSettings().backend == "local"
    assert StorageSettings().bucket == "uploads"
    assert not hasattr(StorageSettings(), "signed_url_ttl_seconds")
