"""Tutoring settings: ``[tutoring]`` and the tutor-evidence storage keys."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from lemely.io.storage_local import LocalFileStorageBackend
from lemely.runtime.config import Settings, StorageSettings, TutoringSettings

_EXAMPLE = Path(__file__).resolve().parent.parent / "lemely.toml.example"


def test_tutoring_defaults() -> None:
    assert TutoringSettings().email_daily_cap == 60
    assert Settings().tutoring.email_daily_cap == 60


def test_storage_evidence_defaults() -> None:
    storage = StorageSettings()
    assert storage.tutor_evidence_bucket == "lemely-tutor-evidence"
    assert storage.tutor_evidence_signed_url_ttl_seconds == 300
    assert storage.tutor_evidence_bucket not in {storage.bucket, storage.avatar_bucket}


def test_local_backend_keeps_default_evidence_bucket(tmp_path: Path) -> None:
    """Only the gcs backend refuses the default name (SC-22): for ``local`` it is a directory.

    Dev, Compose and CI run on ``local`` with no evidence bucket configured, so the
    default must keep working there.
    """
    storage = StorageSettings()
    assert storage.backend == "local"
    backend = LocalFileStorageBackend(tmp_path)
    backend.upload(storage.tutor_evidence_bucket, "tutor-evidence/t/e.pdf", b"%PDF-1.4", None)
    assert backend.download(storage.tutor_evidence_bucket, "tutor-evidence/t/e.pdf") == b"%PDF-1.4"
    assert (tmp_path / storage.tutor_evidence_bucket / "tutor-evidence/t/e.pdf").is_file()


def test_tutoring_forbids_extra_keys() -> None:
    with pytest.raises(ValidationError):
        TutoringSettings.model_validate({"email_daily_cap": 5, "nope": 1})


def test_tutoring_cap_rejects_negative() -> None:
    with pytest.raises(ValidationError):
        TutoringSettings(email_daily_cap=-1)


def test_tutoring_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMELY_TUTORING__EMAIL_DAILY_CAP", "7")
    assert Settings().tutoring.email_daily_cap == 7


def test_storage_evidence_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMELY_STORAGE__TUTOR_EVIDENCE_BUCKET", "proj-evidence-stg")
    monkeypatch.setenv("LEMELY_STORAGE__TUTOR_EVIDENCE_SIGNED_URL_TTL_SECONDS", "120")
    storage = Settings().storage
    assert storage.tutor_evidence_bucket == "proj-evidence-stg"
    assert storage.tutor_evidence_signed_url_ttl_seconds == 120


@pytest.mark.parametrize("ttl", [0, -5])
def test_evidence_ttl_must_be_positive(ttl: int) -> None:
    with pytest.raises(ValidationError):
        StorageSettings(tutor_evidence_signed_url_ttl_seconds=ttl)


def test_evidence_bucket_must_be_non_empty() -> None:
    with pytest.raises(ValidationError):
        StorageSettings(tutor_evidence_bucket="")


def test_gcs_project_number_is_unset_by_default() -> None:
    """Unset: the gcs backend cannot show the evidence bucket is ours, so it fails closed."""
    assert StorageSettings().gcs_project_number is None
    assert Settings().storage.gcs_project_number is None


def test_gcs_project_number_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMELY_STORAGE__GCS_PROJECT_NUMBER", "123456789012")
    assert Settings().storage.gcs_project_number == 123456789012


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_gcs_project_number_reads_as_unset(
    monkeypatch: pytest.MonkeyPatch, blank: str
) -> None:
    """An unset GitHub Actions output renders as the empty string: that is "not set", not 0."""
    monkeypatch.setenv("LEMELY_STORAGE__GCS_PROJECT_NUMBER", blank)
    assert Settings().storage.gcs_project_number is None


@pytest.mark.parametrize("bad", ["0", "-5", "my-project", "proj-1234"])
def test_gcs_project_number_must_be_a_positive_number(bad: str) -> None:
    """A project id or a non-positive value is refused at load, not compared at first use."""
    with pytest.raises(ValidationError):
        StorageSettings.model_validate({"gcs_project_number": bad})


def test_example_file_contains_new_keys() -> None:
    text = _EXAMPLE.read_text(encoding="utf-8")
    assert "[tutoring]" in text
    assert "email_daily_cap = 60" in text
    assert 'tutor_evidence_bucket = "lemely-tutor-evidence"' in text
    assert "tutor_evidence_signed_url_ttl_seconds = 300" in text
