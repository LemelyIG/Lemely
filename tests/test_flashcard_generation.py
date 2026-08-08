"""Tests for :mod:`lemely.core.flashcards` and :mod:`lemely.io.flashcard_generation` (P4.6 chunk B).

Gemini is fully mocked (a plain ``MagicMock`` stands in for
:class:`~lemely.io.gemini.GeminiClient`) — $0.00 live spend, mirroring
``tests/test_question_generation.py``'s unit-test shape exactly.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from lemely.core.flashcards import GeneratedFlashcard, GeneratedFlashcardDeck
from lemely.io.flashcard_generation import FlashcardGenerator


class TestGeneratedFlashcard:
    def test_blank_front_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            GeneratedFlashcard(front="   ", back="An answer")

    def test_blank_back_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            GeneratedFlashcard(front="A question", back="")

    def test_source_question_id_defaults_to_none(self) -> None:
        card = GeneratedFlashcard(front="Q", back="A")
        assert card.source_question_id is None

    def test_source_question_id_round_trips_when_supplied(self) -> None:
        card = GeneratedFlashcard(front="Q", back="A", source_question_id="0625_s23_qp_11#4")
        assert card.source_question_id == "0625_s23_qp_11#4"


class TestGeneratedFlashcardDeck:
    def test_deck_may_carry_fewer_cards_than_any_requested_count(self) -> None:
        """Nothing in this schema pads a short response — see the module
        docstring's honesty rule. A deck of 1 card is a perfectly valid
        instance regardless of what count a caller asked for."""
        deck = GeneratedFlashcardDeck(
            subject_code="0625",
            topic="1 Motion",
            cards=[GeneratedFlashcard(front="Q", back="A")],
        )
        assert len(deck.cards) == 1

    def test_deck_may_carry_zero_cards(self) -> None:
        deck = GeneratedFlashcardDeck(subject_code="0625", topic="1 Motion", cards=[])
        assert deck.cards == []


class TestFlashcardGeneratorUnit:
    def test_calls_generate_structured_with_flashcard_generation_tag(self) -> None:
        mock_client = MagicMock()
        deck = GeneratedFlashcardDeck(
            subject_code="0625",
            topic="1 Motion",
            cards=[GeneratedFlashcard(front="Q", back="A")],
        )
        mock_client.generate_structured.return_value = deck

        generator = FlashcardGenerator(mock_client)
        result = generator.generate(subject_code="0625", topic="1 Motion", count=3)

        assert isinstance(result, GeneratedFlashcardDeck)
        mock_client.generate_structured.assert_called_once()
        call_kwargs = mock_client.generate_structured.call_args.kwargs
        assert call_kwargs["task_tag"] == "flashcard_generation"
        assert call_kwargs["response_schema"] is GeneratedFlashcardDeck

    def test_the_topic_reaches_the_prompt(self) -> None:
        mock_client = MagicMock()
        mock_client.generate_structured.return_value = GeneratedFlashcardDeck(
            subject_code="0625", topic="4.3 Electric circuits", cards=[]
        )
        generator = FlashcardGenerator(mock_client)
        generator.generate(subject_code="0625", topic="4.3 Electric circuits", count=5)

        call_kwargs = mock_client.generate_structured.call_args.kwargs
        assert "4.3 Electric circuits" in call_kwargs["user_prompt"]
        assert "5" in call_kwargs["user_prompt"]

    def test_does_not_pad_a_short_response(self) -> None:
        """The generator returns exactly what Gemini gave it — 1 card even
        though 5 were requested — never topping the list up itself."""
        mock_client = MagicMock()
        mock_client.generate_structured.return_value = GeneratedFlashcardDeck(
            subject_code="0625",
            topic="1 Motion",
            cards=[GeneratedFlashcard(front="Q", back="A")],
        )
        generator = FlashcardGenerator(mock_client)
        result = generator.generate(subject_code="0625", topic="1 Motion", count=5)
        assert len(result.cards) == 1
