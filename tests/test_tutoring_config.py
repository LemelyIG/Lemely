"""Tutoring settings: ``[tutoring]`` and the tutor-evidence storage keys."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

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


def test_example_file_contains_new_keys() -> None:
    text = _EXAMPLE.read_text(encoding="utf-8")
    assert "[tutoring]" in text
    assert "email_daily_cap = 60" in text
    assert 'tutor_evidence_bucket = "lemely-tutor-evidence"' in text
    assert "tutor_evidence_signed_url_ttl_seconds = 300" in text
