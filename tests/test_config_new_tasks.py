"""Tests for Phase 0: new GeminiSettings task_tags and IntegritySettings."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from lemely.runtime.config import (
    GeminiSettings,
    IntegritySettings,
    Settings,
    find_removed_config_keys,
    load_settings,
)


class TestModelForNewTags:
    def test_generation_default_is_f1_3x(self) -> None:
        """F1: generation_model has its own explicit 3.x default, not a fallback."""
        s = GeminiSettings()
        assert s.model_for("generation") == "gemini-3.5-flash-lite"

    def test_generation_falls_back_to_global_when_unset(self) -> None:
        s = GeminiSettings(model="gemini-2.5-flash", generation_model=None)
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

    def test_scan_metadata_default_is_f1_3x(self) -> None:
        """F1: scan_metadata_model has its own explicit 3.x default, not a fallback."""
        s = GeminiSettings()
        assert s.model_for("scan_metadata") == "gemini-3.5-flash-lite"

    def test_scan_metadata_falls_back_to_global_when_unset(self) -> None:
        s = GeminiSettings(model="gemini-2.5-flash", scan_metadata_model=None)
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


class TestSecondReaderSettings:
    """I3 (US-010, label-free half). Default must stay "none" so every
    existing path is behaviour-unchanged until an AUROC selection (needs
    Phase-A transcription labels, US-008) picks a variant."""

    def test_default_is_none(self) -> None:
        s = GeminiSettings()
        assert s.second_reader == "none"

    def test_default_second_read_model_is_3_8_flash(self) -> None:
        """Plan: cross_model pairs primary 3.5-flash-lite with second 3.8-flash."""
        s = GeminiSettings()
        assert s.second_read_model == "gemini-3.8-flash"

    def test_second_reader_rejects_unknown_variant(self) -> None:
        import pydantic

        with pytest.raises(pydantic.ValidationError):
            GeminiSettings(second_reader="bogus")

    def test_second_reader_accepts_cross_model_and_structural(self) -> None:
        assert GeminiSettings(second_reader="cross_model").second_reader == "cross_model"
        assert GeminiSettings(second_reader="structural").second_reader == "structural"

    def test_f1_defaults(self) -> None:
        """F1 acceptance (1): model_for() resolves every tag to the migration defaults."""
        s = GeminiSettings()
        assert s.model_for("correction") == "gemini-3.8-flash"
        assert s.model_for("correction_borderline") == "gemini-3.8-flash"
        assert s.model_for("escalation") == "gemini-3.8-flash"
        assert s.model_for("extraction") == "gemini-3.5-flash-lite"
        assert s.model_for("generation") == "gemini-3.5-flash-lite"
        assert s.model_for("scan_metadata") == "gemini-3.5-flash-lite"
        assert s.model_for("mark_scheme") == "gemini-2.5-flash"

    def test_f1_total_usd_ceiling_default(self) -> None:
        assert GeminiSettings().total_usd_ceiling == 14.0

    def test_f1_correction_borderline_resolves_to_correction_model(self) -> None:
        """Before F1's fix, the borderline retry fell through to the global model."""
        s = GeminiSettings(correction_model="gemini-3.8-flash")
        assert s.model_for("correction_borderline") == s.model_for("correction")

    def test_f1_escalation_resolves_to_escalation_model_not_correction(self) -> None:
        s = GeminiSettings(correction_model="gemini-3.8-flash", escalation_model="gemini-2.5-pro")
        assert s.model_for("escalation") == "gemini-2.5-pro"

    def test_f1_thinking_level_for_rejects_a_typo(self) -> None:
        """FIX 3 (review): a bare `dict[str, str]` accepted "hgih" silently —
        it reached types.ThinkingConfig unchanged (a case-insensitive str-enum,
        no coercion error) and every correction call would have failed at the
        API while the ordered gate ranked it as "minimal" (0). Literal makes
        config load reject it instead."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            GeminiSettings(thinking_level_for={"correction": "hgih"})

    def test_f1_thinking_level_for_accepts_every_valid_level(self) -> None:
        for level in ("minimal", "low", "medium", "high"):
            s = GeminiSettings(thinking_level_for={"correction": level})
            assert s.thinking_level_for["correction"] == level


class TestEcfSubstitutionSettings:
    """I7 (US-013, D19): defaults must stay False, independently of
    ``equivalence_gate``, until the funded US-018 sweep measures the batch."""

    def test_default_is_off(self) -> None:
        from lemely.runtime.config import GradingSettings

        assert GradingSettings().ecf_substitution is False

    def test_independent_of_equivalence_gate(self) -> None:
        from lemely.runtime.config import GradingSettings

        s = GradingSettings(equivalence_gate=True)
        assert s.ecf_substitution is False  # not implied by equivalence_gate
        s2 = GradingSettings(ecf_substitution=True)
        assert s2.equivalence_gate is False  # not implied the other way either

    def test_extra_fields_forbidden(self) -> None:
        from pydantic import ValidationError

        from lemely.runtime.config import GradingSettings

        with pytest.raises(ValidationError):
            GradingSettings(ecf_substituton=True)  # type: ignore[call-arg]


class TestUnwiredFlagsAreDisclosedInProse:
    """Whole-branch review Minor C: ``equivalence_gate``/``ecf_substitution``
    are declared here (US-005b, US-013) but no ``correct_paper`` caller
    reads ``GradingSettings.equivalence_gate``/``.ecf_substitution`` off a
    loaded config -- they are only ever passed as explicit keyword
    arguments by tests and by the accuracy harness. US-040 records this
    unreachability; what this pins is that the comment BESIDE each field
    also says so, so an operator reading ``lemely.toml.example`` (or the
    source) does not set ``equivalence_gate = true`` expecting an effect
    and get a silent no-op.
    """

    def _comment_block_before(self, field_line: str) -> str:
        """Return the contiguous ``#``-comment block immediately above
        *field_line* in ``GradingSettings``'s source -- i.e. just that
        field's own prose, not the whole class or a neighbouring field's."""
        import inspect

        from lemely.runtime import config as config_module

        lines = inspect.getsource(config_module.GradingSettings).splitlines()
        idx = next(i for i, line in enumerate(lines) if field_line in line)
        block: list[str] = []
        i = idx - 1
        while i >= 0 and lines[i].strip().startswith("#"):
            block.insert(0, lines[i])
            i -= 1
        return "\n".join(block)

    def test_equivalence_gate_names_us040(self) -> None:
        block = self._comment_block_before("equivalence_gate: bool = False")
        assert "US-040" in block
        assert "not read by any" in block

    def test_ecf_substitution_names_us040(self) -> None:
        block = self._comment_block_before("ecf_substitution: bool = False")
        assert "US-040" in block
        assert "not read by any" in block

    def test_ecf_substitution_gate_population_figure_is_current(self) -> None:
        """`4759d116` dropped `\\bdep\\b` from `_ECF_MARKER_RE`, narrowing the
        measured gate population from 28 points/11 schemes to 26 points/10
        schemes (`lemely.io.correction_ai._ECF_MARKER_RE`'s docstring, and
        `_maybe_apply_ecf_substitution`'s activation-ceiling docstring, were
        both updated to match). This is a CURRENT-state claim about the
        deployed gate's measured ceiling, not a historical note (contrast
        `correction_ai.py`'s two deliberately-kept `28` references, which
        narrate the re-measurement itself) -- it must stay in sync with the
        live figure, not the stale one from before the `dep`-token fix.
        """
        block = self._comment_block_before("ecf_substitution: bool = False")
        # The pre-fix, now-stale figure must not survive as a current claim.
        assert "28 points" not in block
        assert "26 points" in block
        assert "10 of 289" in block or "10 schemes" in block


class TestIntegritySettings:
    def test_defaults(self) -> None:
        s = IntegritySettings()
        assert s.plagiarism_enabled is True
        assert s.plagiarism_threshold == pytest.approx(0.85)

    def test_override_threshold(self) -> None:
        s = IntegritySettings(plagiarism_threshold=0.90)
        assert s.plagiarism_threshold == pytest.approx(0.90)

    def test_disable_plagiarism(self) -> None:
        s = IntegritySettings(plagiarism_enabled=False)
        assert s.plagiarism_enabled is False

    def test_extra_fields_forbidden(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            IntegritySettings(unknown_field=True)  # type: ignore[call-arg]

    def test_f4_removed_ai_detection_fields(self) -> None:
        """F4: the AI-generated-answer detector's knobs no longer exist at all —
        not just disabled by default. A stale config setting either one hits
        extra='forbid', not a silently-ignored field."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            IntegritySettings(ai_detection_enabled=True)  # type: ignore[call-arg]
        with pytest.raises(ValidationError):
            IntegritySettings(ai_detection_threshold=0.5)  # type: ignore[call-arg]


class TestSettingsIntegrityWired:
    def test_integrity_section_loads(self) -> None:
        s = Settings()
        assert isinstance(s.integrity, IntegritySettings)
        assert s.integrity.plagiarism_threshold == pytest.approx(0.85)


class TestFindRemovedConfigKeys:
    """F4 acceptance (5): ``lemely doctor`` warns if ``lemely.toml`` still sets
    a removed key, by reading the raw TOML — before ``Settings(**toml_data)``
    would fail on it with a bare ``extra='forbid'`` ``ValidationError``."""

    def test_no_toml_file_returns_empty(self, tmp_path: Path) -> None:
        assert find_removed_config_keys(cwd=tmp_path) == []

    def test_clean_toml_returns_empty(self, tmp_path: Path) -> None:
        toml = tmp_path / "lemely.toml"
        toml.write_text("[integrity]\nplagiarism_enabled = true\n")
        assert find_removed_config_keys(toml_path=toml) == []

    def test_finds_removed_integrity_key(self, tmp_path: Path) -> None:
        toml = tmp_path / "lemely.toml"
        toml.write_text("[integrity]\nai_detection_enabled = true\n")
        assert find_removed_config_keys(toml_path=toml) == ["integrity.ai_detection_enabled"]

    def test_finds_removed_gemini_key(self, tmp_path: Path) -> None:
        toml = tmp_path / "lemely.toml"
        toml.write_text('[gemini]\nintegrity_model = "gemini-2.5-pro"\n')
        assert find_removed_config_keys(toml_path=toml) == ["gemini.integrity_model"]

    def test_finds_multiple_removed_keys(self, tmp_path: Path) -> None:
        toml = tmp_path / "lemely.toml"
        toml.write_text(
            '[gemini]\nintegrity_model = "gemini-2.5-pro"\n\n'
            "[integrity]\n"
            "ai_detection_enabled = true\n"
            "ai_detection_threshold = 0.5\n"
        )
        found = find_removed_config_keys(toml_path=toml)
        assert set(found) == {
            "gemini.integrity_model",
            "integrity.ai_detection_enabled",
            "integrity.ai_detection_threshold",
        }

    def test_finds_removed_key_set_as_an_env_var(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Review finding F-6: a removed key deserves the same warning
        whether it arrives via lemely.toml or an env var — not a crash one
        way and silence the other."""
        monkeypatch.setenv("LEMELY_INTEGRITY__AI_DETECTION_ENABLED", "true")
        assert find_removed_config_keys(cwd=tmp_path) == ["integrity.ai_detection_enabled"]

    def test_env_var_match_is_case_insensitive(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("lemely_gemini__integrity_model", "gemini-2.5-pro")
        assert find_removed_config_keys(cwd=tmp_path) == ["gemini.integrity_model"]

    def test_key_set_both_ways_is_reported_once(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        toml = tmp_path / "lemely.toml"
        toml.write_text("[integrity]\nai_detection_enabled = true\n")
        monkeypatch.setenv("LEMELY_INTEGRITY__AI_DETECTION_ENABLED", "true")
        found = find_removed_config_keys(toml_path=toml)
        assert found == ["integrity.ai_detection_enabled"]


class TestLoadSettingsDropsRemovedKeys:
    """F-6: ``load_settings`` must not crash on a removed key however it is
    supplied — TOML and env var get the same (silent-drop) outcome."""

    def test_toml_removed_key_does_not_crash(self, tmp_path: Path) -> None:
        toml = tmp_path / "lemely.toml"
        toml.write_text("[integrity]\nai_detection_enabled = true\n")
        settings = load_settings(toml_path=toml)
        assert settings.integrity.plagiarism_enabled is True

    def test_env_var_removed_key_does_not_crash(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LEMELY_INTEGRITY__AI_DETECTION_ENABLED", "true")
        settings = load_settings(cwd=tmp_path)
        assert settings.integrity.plagiarism_enabled is True

    def test_env_var_removed_key_is_restored_after_loading(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The pop-and-restore in ``load_settings`` must not leak: the env
        var a caller set is still there afterwards, for the next caller
        (including ``find_removed_config_keys``, which needs to still see
        it) to observe."""
        monkeypatch.setenv("LEMELY_INTEGRITY__AI_DETECTION_ENABLED", "true")
        load_settings(cwd=tmp_path)
        assert os.environ.get("LEMELY_INTEGRITY__AI_DETECTION_ENABLED") == "true"

    def test_a_typo_env_var_still_crashes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The removed-key drop must not mask an unrelated typo — only the
        exact removed names are dropped."""
        from pydantic import ValidationError

        monkeypatch.setenv("LEMELY_INTEGRITY__AI_DETECTION_ENABLD", "true")
        with pytest.raises(ValidationError):
            load_settings(cwd=tmp_path)
