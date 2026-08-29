"""#41 (M1.6) — the paper's own Generic Marking Principles reach the marker.

`det/gmp.py`'s `extract_gmp` already populates
`metadata.generic_marking_principles`, and the result was discarded. These pin
that it now reaches the prompt, and that ruling A13's fallback rule is a
FALLBACK rather than the primary rule.

A13 (human, 2026-08-25), recorded so it is not re-litigated: the A-mark
dependency is driven from **each paper's own printed principles**, not a
hard-coded rule. Strict M-then-A applies **only** where principles could not be
parsed — the published CAIE default at `loose_schemas.py:83`.
"""

from __future__ import annotations

import unittest

from lemely.core.loose_schemas import Question, QuestionType
from lemely.io.prompts.correction_ai import (
    MARKER_SYSTEM_PROMPT,
    build_marker_user_prompt,
)


def _q() -> Question:
    return Question(id="1a", marks=2, type=QuestionType.CALCULATION)


class PrinciplesReachThePromptTests(unittest.TestCase):
    def test_principles_are_injected_verbatim(self) -> None:
        principles = [
            "Marks must be awarded positively.",
            "Marks awarded are always whole marks.",
        ]
        out = build_marker_user_prompt(_q(), "answer", principles=principles)
        for p in principles:
            self.assertIn(p, out)

    def test_the_paper_is_told_its_own_principles_GOVERN(self) -> None:
        # The point of A13: they are not decoration. If the prompt merely
        # printed them without saying they take precedence, the hard-coded rule
        # in the system prompt would still be what the model follows.
        out = build_marker_user_prompt(_q(), "answer", principles=["Some printed principle."])
        self.assertIn("take precedence", out.lower())

    def test_no_principles_means_no_section_and_no_empty_heading(self) -> None:
        out = build_marker_user_prompt(_q(), "answer", principles=None)
        self.assertNotIn("GENERIC MARKING PRINCIPLES", out)
        out_empty = build_marker_user_prompt(_q(), "answer", principles=[])
        self.assertNotIn("GENERIC MARKING PRINCIPLES", out_empty)

    def test_principles_change_the_prompt_so_the_cache_key_changes(self) -> None:
        # The cache key is built from the user prompt (gemini.py:339), so two
        # papers with different printed principles must not share a cached
        # mark. This is what makes injection cache-safe without a separate key.
        a = build_marker_user_prompt(_q(), "answer", principles=["Principle A"])
        b = build_marker_user_prompt(_q(), "answer", principles=["Principle B"])
        self.assertNotEqual(a, b)


class AMarkDependencyIsAFallbackNotTheRuleTests(unittest.TestCase):
    def test_the_system_prompt_marks_strict_dependency_as_a_FALLBACK(self) -> None:
        # Before #41 this read "A marks are accuracy marks: dependent on the
        # preceding M mark ... Do not award an A mark if its associated M mark
        # was not earned" — stated unconditionally, which A13 rules is wrong as
        # a primary rule.
        text = MARKER_SYSTEM_PROMPT.lower()
        self.assertIn("fallback", text)
        self.assertIn("generic marking principles", text)

    def test_the_system_prompt_no_longer_states_strict_dependency_unconditionally(self) -> None:
        self.assertNotIn(
            "A marks are accuracy marks: dependent on the preceding M mark",
            MARKER_SYSTEM_PROMPT,
        )


class PrinciplesAreThreadedFromTheMarkSchemeTests(unittest.TestCase):
    """The extractor already populates them; #41 is about them ARRIVING."""

    def test_ai_corrector_passes_principles_into_the_prompt(self) -> None:
        from unittest.mock import MagicMock

        from lemely.core.schemas import AIMarkResponse
        from lemely.io.correction_ai import AICorrector

        captured: dict[str, str] = {}

        client = MagicMock()
        client._settings.gemini.thinking_budget_for = {}
        client._settings.gemini.escalation_confidence_threshold = 0.0
        client._settings.gemini.escalation_model = None
        client._settings.gemini.model_for.return_value = "m"

        def _capture(**kwargs: object) -> AIMarkResponse:
            captured["user_prompt"] = str(kwargs["user_prompt"])
            return AIMarkResponse(
                awarded_marks=1, confidence=1.0, matched_point_ids=[], feedback=""
            )

        client.generate_structured.side_effect = _capture
        AICorrector(client).mark_question(
            _q(), "ans", principles=["Marks must be awarded positively."]
        )
        self.assertIn("Marks must be awarded positively.", captured["user_prompt"])

    def test_correct_paper_reads_them_off_the_mark_scheme_metadata(self) -> None:
        # The field the det parser already fills. If this ever stops being
        # read, #41 silently reverts to the hard-coded rule.
        import inspect

        from lemely.io import correction_ai

        src = inspect.getsource(correction_ai)
        self.assertIn("generic_marking_principles", src)
