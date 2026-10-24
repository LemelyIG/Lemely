"""Sub-project C levers a1/a2: Claude effort "none" sends a request with thinking off."""

from __future__ import annotations

import unittest

from lemely.core.schemas import AIMarkResponse
from lemely.io.gemini import thinking_rank
from lemely.io.providers.anthropic_adapter import AnthropicAdapter, resolve_effort
from lemely.runtime.config import GeminiSettings
from tests.test_anthropic_adapter import _VALID_MARK, _FakeAnthropic, _message

_HAIKU = "claude-haiku-5-5"


class EffortNoneTests(unittest.TestCase):
    def _sent(self, thinking: str) -> dict[str, object]:
        fake = _FakeAnthropic(_message(_VALID_MARK))
        AnthropicAdapter(fake).generate(
            model=_HAIKU,
            system_prompt="s",
            user_prompt="u",
            response_schema=AIMarkResponse,
            thinking=thinking,
            cache_prefix=None,
        )
        return fake.messages.calls[0]

    def test_none_disables_thinking(self) -> None:
        call = self._sent("none")
        self.assertEqual(call["thinking"], {"type": "disabled"})
        # Docs do not say effort may accompany disabled thinking: it is omitted.
        self.assertNotIn("effort", call["output_config"])

    def test_other_efforts_stay_adaptive(self) -> None:
        call = self._sent("medium")
        self.assertEqual(call["thinking"], {"type": "adaptive"})
        self.assertEqual(call["output_config"]["effort"], "medium")

    def test_settings_accept_none_per_tag(self) -> None:
        g = GeminiSettings(claude_effort_for={"binding_second_read": "none"})
        self.assertEqual(
            resolve_effort(g.claude_effort_for, g.thinking_level_for, "binding_second_read"), "none"
        )

    def test_none_ranks_below_every_other_effort(self) -> None:
        self.assertLess(thinking_rank("none"), thinking_rank("minimal"))
        self.assertLess(thinking_rank("none"), thinking_rank("low"))

    def test_unknown_effort_is_still_refused(self) -> None:
        with self.assertRaises(ValueError):
            GeminiSettings(claude_effort_for={"extraction": "off"})  # type: ignore[dict-item]


if __name__ == "__main__":
    unittest.main()
