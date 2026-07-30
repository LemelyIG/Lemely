"""Tests for Phase 0: new GeminiSettings task_tags and IntegritySettings."""

from __future__ import annotations

import pytest

from lemely.runtime.config import GeminiSettings, IntegritySettings, Settings


class TestModelForNewTags:
    def test_generation_falls_back_to_global(self) -> None:
        s = GeminiSettings(model="gemini-2.5-flash")
        assert s.model_for("generation") == "gemini-2.5-flash"

    def test_generation_override(self) -> None:
        s = GeminiSettings(generation_model="gemini-2.5-pro")
        assert s.model_for("generation") == "gemini-2.5-pro"

    def test_study_plan_falls_back_to_global(self) -> None:
        s = GeminiSettings(model="gemini-2.5-flash")
        assert s.model_for("study_plan") == "gemini-2.5-flash"

    def test_study_plan_override(self) -> None:
        s = GeminiSettings(study_plan_model="gemini-2.5-pro")
        assert s.model_for("study_plan") == "gemini-2.5-pro"

    def test_integrity_falls_back_to_global(self) -> None:
        s = GeminiSettings(model="gemini-2.5-flash")
        assert s.model_for("integrity") == "gemini-2.5-flash"

    def test_integrity_override(self) -> None:
        s = GeminiSettings(integrity_model="gemini-2.5-pro")
        assert s.model_for("integrity") == "gemini-2.5-pro"

    def test_scan_metadata_falls_back_to_global(self) -> None:
        s = GeminiSettings(model="gemini-2.5-flash")
        assert s.model_for("scan_metadata") == "gemini-2.5-flash"

    def test_scan_metadata_override(self) -> None:
        s = GeminiSettings(scan_metadata_model="gemini-2.5-pro")
        assert s.model_for("scan_metadata") == "gemini-2.5-pro"

    def test_unknown_tag_falls_back_to_global(self) -> None:
        s = GeminiSettings(model="gemini-2.5-flash")
        assert s.model_for("unknown_tag") == "gemini-2.5-flash"

    def test_existing_tags_still_work(self) -> None:
        s = GeminiSettings(correction_model="gemini-2.5-pro")
        assert s.model_for("correction") == "gemini-2.5-pro"
        assert s.model_for("mark_scheme") == "gemini-2.5-flash"


class TestIntegritySettings:
    def test_defaults(self) -> None:
        s = IntegritySettings()
        assert s.plagiarism_enabled is True
        assert s.ai_detection_enabled is False
        assert s.plagiarism_threshold == pytest.approx(0.85)
        assert s.ai_detection_threshold == pytest.approx(0.80)

    def test_override_thresholds(self) -> None:
        s = IntegritySettings(plagiarism_threshold=0.90, ai_detection_threshold=0.70)
        assert s.plagiarism_threshold == pytest.approx(0.90)
        assert s.ai_detection_threshold == pytest.approx(0.70)

    def test_disable_plagiarism(self) -> None:
        s = IntegritySettings(plagiarism_enabled=False)
        assert s.plagiarism_enabled is False

    def test_enable_ai_detection(self) -> None:
        s = IntegritySettings(ai_detection_enabled=True)
        assert s.ai_detection_enabled is True

    def test_extra_fields_forbidden(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            IntegritySettings(unknown_field=True)  # type: ignore[call-arg]


class TestSettingsIntegrityWired:
    def test_integrity_section_loads(self) -> None:
        s = Settings()
        assert isinstance(s.integrity, IntegritySettings)
        assert s.integrity.plagiarism_threshold == pytest.approx(0.85)

    def test_integrity_field_accessible(self) -> None:
        s = Settings()
        assert s.integrity.ai_detection_enabled is False
