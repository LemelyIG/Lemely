"""Cost-ladder lever settings: every lever defaults to today's behaviour."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from lemely.runtime.config import GeminiSettings, load_settings
from lemely.runtime.example_toml import render_example_toml

_NEW_KEYS = (
    "cache_mode_for",
    "cascade_enabled",
    "cascade_strong_model",
    "cascade_threshold_for",
    "cascade_two_pass_disagreement",
    "cascade_unaddressed_points",
    "correction_shared_prefix",
    "correction_prefix_cache",
)


def test_defaults_reproduce_current_behaviour() -> None:
    g = GeminiSettings()
    assert g.cache_mode_for == {}
    assert g.cascade_enabled is False
    assert g.cascade_strong_model is None
    assert g.cascade_threshold_for == {}
    assert g.cascade_two_pass_disagreement is False
    assert g.cascade_unaddressed_points is False
    assert g.correction_shared_prefix is False
    assert g.correction_prefix_cache == "implicit"
    assert g.correction_model == "gemini-3.8-flash"


def test_example_toml_lists_new_keys() -> None:
    text = render_example_toml()
    for key in _NEW_KEYS:
        assert f"# {key}" in text, key
    repo_root = Path(__file__).resolve().parents[1]
    assert (repo_root / "lemely.toml.example").read_text(encoding="utf-8") == text


def test_anthropic_key_from_env_is_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LEMELY_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-very-secret")
    s = load_settings(cwd=Path("/nonexistent-lemely-cwd"))
    assert s.anthropic_api_key is not None
    assert s.anthropic_api_key.get_secret_value() == "sk-ant-very-secret"
    assert "sk-ant-very-secret" not in repr(s.anthropic_api_key)
    assert "sk-ant-very-secret" not in repr(s)


def test_cache_mode_for_rejects_unknown_mode() -> None:
    assert GeminiSettings(cache_mode_for={"correction": "bypass"}).cache_mode_for == {
        "correction": "bypass"
    }
    with pytest.raises(ValidationError):
        GeminiSettings(cache_mode_for={"correction": "bogus"})  # type: ignore[dict-item]


def test_anthropic_key_defaults_none_when_env_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LEMELY_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    s = load_settings(cwd=Path("/nonexistent-lemely-cwd"))
    assert s.anthropic_api_key is None


@pytest.mark.parametrize("bad", [1.5, -0.1])
def test_cascade_threshold_out_of_range_rejected(bad: float) -> None:
    assert GeminiSettings(cascade_threshold_for={"m": 0.5}).cascade_threshold_for == {"m": 0.5}
    with pytest.raises(ValidationError):
        GeminiSettings(cascade_threshold_for={"m": bad})
