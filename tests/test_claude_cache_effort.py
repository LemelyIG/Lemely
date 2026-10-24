"""Sub-project C lever a3: the binder reads share the cache across efforts when asked."""

from __future__ import annotations

import tempfile

from lemely.io.binding.orchestrate import _reads_share_a_claude_cache
from lemely.runtime.config import Settings
from tests.gemini_fakes import make_settings

_HAIKU = "claude-haiku-5-5"


def _settings(*, ignore: bool, second_effort: str) -> Settings:
    s = make_settings(tempfile.mkdtemp())
    g = s.gemini.model_copy(
        update={
            "claude_cache_for": {
                "extraction": ["system", "images"],
                "binding_second_read": ["system", "images"],
            },
            "claude_effort_for": {"extraction": "low", "binding_second_read": second_effort},
        }
    )
    b = s.binding.model_copy(update={"claude_cache_ignores_effort": ignore})
    return s.model_copy(update={"gemini": g, "binding": b})


def test_different_efforts_do_not_share_by_default() -> None:
    assert (
        _reads_share_a_claude_cache(_settings(ignore=False, second_effort="none"), _HAIKU, _HAIKU)
        is False
    )


def test_the_switch_shares_across_efforts() -> None:
    assert (
        _reads_share_a_claude_cache(_settings(ignore=True, second_effort="none"), _HAIKU, _HAIKU)
        is True
    )


def test_the_switch_never_shares_across_models() -> None:
    s = _settings(ignore=True, second_effort="low")
    assert _reads_share_a_claude_cache(s, _HAIKU, "claude-sonnet-5-5") is False


def test_default_is_off() -> None:
    assert Settings().binding.claude_cache_ignores_effort is False
