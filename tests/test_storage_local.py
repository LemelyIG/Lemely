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


def test_signed_url_disposition_attachment(tmp_path: Path) -> None:
    """A ``data:`` URL has no headers, so an attachment is served as octet-stream (SC-22).

    Without a disposition (avatars) the media type still follows the key, so an
    ``<img>`` renders it; with one, no browser renders the bytes inline.
    """
    import base64

    backend = LocalFileStorageBackend(tmp_path)
    data = b"%PDF-1.7\n%evidence"
    backend.upload("evidence", "tutor-evidence/t/e.pdf", data, "application/pdf")

    inline = backend.create_signed_url("evidence", "tutor-evidence/t/e.pdf", 300)
    attached = backend.create_signed_url(
        "evidence", "tutor-evidence/t/e.pdf", 300, disposition='attachment; filename="e.pdf"'
    )

    assert inline.startswith("data:application/pdf;base64,")
    prefix = "data:application/octet-stream;base64,"
    assert attached.startswith(prefix)
    assert base64.b64decode(attached.removeprefix(prefix)) == data


def test_signed_url_content_type(tmp_path: Path) -> None:
    """T10 review R8: the caller's type (the DB row's sniffed one) wins over the key's suffix.

    A disposition still wins over both: a ``data:`` URL carries one media type
    and no headers, so a download must be ``application/octet-stream``.
    """
    import base64

    backend = LocalFileStorageBackend(tmp_path)
    data = b"\x89PNG\r\n\x1a\nnot-really"
    backend.upload("evidence", "tutor-evidence/t/e.pdf", data, "image/png")

    typed = backend.create_signed_url(
        "evidence", "tutor-evidence/t/e.pdf", 300, content_type="image/png"
    )
    attached = backend.create_signed_url(
        "evidence",
        "tutor-evidence/t/e.pdf",
        300,
        disposition='attachment; filename="e.png"',
        content_type="image/png",
    )

    assert typed.startswith("data:image/png;base64,")
    assert base64.b64decode(typed.removeprefix("data:image/png;base64,")) == data
    assert attached.startswith("data:application/octet-stream;base64,")


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
