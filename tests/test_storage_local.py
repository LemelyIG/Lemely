"""Hermetic tests for :class:`lemely.io.storage_local.LocalFileStorageBackend`."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

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
    # `lemely-` prefixed since the merge with #220: GCS bucket names are one
    # global namespace across all of Google Cloud, so a bare "uploads" default
    # could never be created. For `local` these are directory names, where the
    # prefix is merely harmless.
    assert StorageSettings().bucket == "lemely-uploads"
    assert StorageSettings().avatar_bucket == "lemely-avatars"
    # Present since the merge with #220: avatars are served as signed URLs.
    assert StorageSettings().signed_url_ttl_seconds == 3600


def test_check_storage_local_reports_root(tmp_path: Path) -> None:
    from lemely.io.storage import check_storage
    from lemely.runtime.config import Settings

    settings = Settings().model_copy(
        update={"paths": Settings().paths.model_copy(update={"output_dir": tmp_path})}
    )
    ok, detail = check_storage(settings, no_network=True)
    assert ok is True
    assert detail == str(tmp_path / "storage")


def test_check_storage_gcs_adc_failure_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    """No application-default credentials: fails before touching the network."""
    from lemely.io.storage import check_storage
    from lemely.runtime.config import Settings

    def _no_adc() -> None:
        raise OSError("could not find default credentials")

    monkeypatch.setattr("google.auth.default", _no_adc)
    settings = Settings().model_copy(
        update={
            "storage": Settings().storage.model_copy(
                update={"backend": "gcs", "bucket": "proj-uploads-staging"}
            )
        }
    )

    ok, detail = check_storage(settings, no_network=True)

    assert ok is False
    assert "application-default credentials" in detail


def test_check_storage_gcs_no_network_skips_the_bucket_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``no_network=True`` reports ADC health only — no client is ever built."""
    from lemely.io.storage import check_storage
    from lemely.runtime.config import Settings

    monkeypatch.setattr("google.auth.default", lambda: None)

    def _client_must_not_be_built(*_: object, **__: object) -> None:
        raise AssertionError("no_network must not construct a storage client")

    monkeypatch.setattr("google.cloud.storage.Client", _client_must_not_be_built)
    settings = Settings().model_copy(
        update={
            "storage": Settings().storage.model_copy(
                update={"backend": "gcs", "bucket": "proj-uploads-staging"}
            )
        }
    )

    ok, detail = check_storage(settings, no_network=True)

    assert ok is True
    assert "proj-uploads-staging" in detail
    assert "not probed" in detail


def test_check_storage_gcs_bucket_probe_failure_is_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADC resolves but the bucket read fails: reported with the bucket named."""
    from lemely.io.storage import check_storage
    from lemely.runtime.config import Settings

    monkeypatch.setattr("google.auth.default", lambda: None)
    client = MagicMock()
    client.get_bucket.side_effect = Exception("403 caller does not have access")
    # `**kw` so this fails on the bucket probe, not on constructing the client
    # — a zero-arg lambda would raise TypeError on `project=` and this test
    # would pass without ever exercising the probe.
    monkeypatch.setattr("google.cloud.storage.Client", lambda **kw: client)
    settings = Settings().model_copy(
        update={
            "storage": Settings().storage.model_copy(
                update={"backend": "gcs", "bucket": "proj-uploads-staging"}
            )
        }
    )

    ok, detail = check_storage(settings, no_network=False)

    assert ok is False
    assert "proj-uploads-staging" in detail


def test_check_storage_gcs_bucket_probe_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """ADC resolves and the bucket answers: reported as reachable."""
    from lemely.io.storage import check_storage
    from lemely.runtime.config import Settings

    monkeypatch.setattr("google.auth.default", lambda: None)
    client = MagicMock()
    # `**kw` because check_storage passes `project=`; a zero-arg lambda here
    # would fail for the wrong reason.
    monkeypatch.setattr("google.cloud.storage.Client", lambda **kw: client)
    settings = Settings().model_copy(
        update={
            "storage": Settings().storage.model_copy(
                update={
                    "backend": "gcs",
                    "bucket": "proj-uploads-staging",
                    "avatar_bucket": "proj-avatars-staging",
                }
            )
        }
    )

    ok, detail = check_storage(settings, no_network=False)

    assert ok is True
    # Both buckets are probed: a deploy that provisioned only one fails on
    # whichever route touches the other.
    assert client.get_bucket.call_count == 2
    assert "proj-avatars-staging" in detail
    assert "proj-uploads-staging" in detail
