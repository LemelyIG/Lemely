"""The marker is told when an answer is the reader's description of a drawing.

The reader opens such an answer with ``Drawing:`` (``tests/test_label_binding_prompt.py``).
The marker never sees the page, so the description is all the evidence there is. Two
failures are guarded: refusing marks "because no diagram was provided", and awarding a
mark for a detail the description never stated. These tests pin what the marker is told.
What a model then does needs live marking calls.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from lemely.core.loose_schemas import MarkScheme, Question, QuestionType
from lemely.core.schemas import AIMarkResponse, ExtractedAnswer, ExtractedAnswers
from lemely.io.correction_ai import AICorrector, correct_paper
from lemely.io.prompts.correction_ai import MARKER_SYSTEM_PROMPT, build_marker_user_prompt

_SECTION_START = "**Drawings, diagrams and graphs:**"
_SECTION_END = "**When WORKING is supplied:**"
_VERBATIM_HEADER = "STUDENT ANSWER (verbatim from scan):"
_DRAWING_HEADER = (
    "STUDENT ANSWER (from the scan; the text after `Drawing:` is the reader's description "
    "of what the student drew, not the student's own words):"
)
# Invented: three lines in a box. Nothing here is from a real script.
_DESCRIPTION = (
    "Drawing: 3 straight lines from the top of the printed box to its base, none touching; "
    "an arrowhead on each line, pointing down."
)


def _section() -> str:
    start = MARKER_SYSTEM_PROMPT.index(_SECTION_START)
    return " ".join(MARKER_SYSTEM_PROMPT[start : MARKER_SYSTEM_PROMPT.index(_SECTION_END)].split())


def _question() -> Question:
    return Question(id="4b", marks=2, type=QuestionType.EXPLANATION)


def _client(captured: list[dict[str, Any]]) -> MagicMock:
    """A marker client that records each call and replies with one confident mark."""
    client = MagicMock()
    client._settings.gemini.escalation_confidence_threshold = 0.0
    client._settings.gemini.escalation_model = None
    client._settings.gemini.model_for.return_value = "m"
    client.resolved_thinking.return_value = 0

    def _reply(**kwargs: Any) -> AIMarkResponse:
        captured.append(kwargs)
        return AIMarkResponse(awarded_marks=1, confidence=1.0, matched_point_ids=[], feedback="")

    client.generate_structured.side_effect = _reply
    return client


# --- system prompt ------------------------------------------------------------------


def test_the_old_section_is_replaced() -> None:
    assert "**Diagrams / graphs:**" not in MARKER_SYSTEM_PROMPT
    assert "an earlier OCR pass" not in MARKER_SYSTEM_PROMPT
    assert MARKER_SYSTEM_PROMPT.count(_SECTION_START) == 1


def test_text_after_drawing_is_a_description_and_not_the_students_words() -> None:
    section = _section()
    assert "You are never shown an image." in section
    assert (
        "Text in the response that follows `Drawing:` is not the student's own words: it is a "
        "description of what the student drew, written by the reader that looked at the scan."
    ) in section


def test_each_mark_point_is_judged_against_the_facts_stated() -> None:
    assert "Judge each mark point against the facts the description states" in _section()


def test_a_mark_is_not_refused_for_want_of_an_image() -> None:
    section = _section()
    assert "Do not refuse a mark because no image or diagram is provided" in section
    assert "do not treat the description as a written answer offered in place of a drawing" in (
        section
    )


def test_a_point_is_not_awarded_on_a_detail_the_description_does_not_state() -> None:
    """The guard against inflated marks: silence in a description earns nothing."""
    section = _section()
    assert "Do not award a point that needs a detail the description does not state." in section
    assert "Silence about a detail is not evidence of it" in section
    assert "say in `feedback` which detail was missing" in section


def test_a_word_of_praise_in_a_description_earns_nothing() -> None:
    assert (
        'A word of praise in a description ("correct", "accurate") is not a fact and earns nothing.'
    ) in _section()


def test_a_vague_description_still_lowers_confidence() -> None:
    """Kept from the section this replaces: such an answer goes to a teacher."""
    assert "Set confidence < 0.5 if the description is too vague to judge a mark point." in (
        _section()
    )


# --- user prompt --------------------------------------------------------------------


def test_a_drawing_answer_is_not_called_verbatim() -> None:
    prompt = build_marker_user_prompt(_question(), _DESCRIPTION)
    assert _DRAWING_HEADER in prompt
    assert _VERBATIM_HEADER not in prompt
    assert f"{_DRAWING_HEADER}\n{_DESCRIPTION}\n" in prompt


@pytest.mark.parametrize(
    "answer",
    [
        "the lines get closer together",
        # A student may write the word; only the reader's `Drawing:` marks a description.
        "my drawing: shows three lines",
        "see the drawing above",
        "Redrawing: not needed",
        "",
    ],
)
def test_a_written_answer_keeps_the_verbatim_header(answer: str) -> None:
    prompt = build_marker_user_prompt(_question(), answer)
    assert _VERBATIM_HEADER in prompt
    assert "reader's description" not in prompt


def test_a_written_answers_prompt_is_what_it_was_before() -> None:
    """Only an answer holding `Drawing:` changes the user prompt."""
    question = _question()
    q_json = question.model_dump_json(indent=2, exclude_none=True, exclude_defaults=True)
    assert build_marker_user_prompt(question, "three lines") == (
        "Mark this CAIE question.\n\n"
        f"MARK SCHEME SUBTREE (JSON):\n{q_json}\n\n"
        "STUDENT ANSWER (verbatim from scan):\nthree lines\n\n"
        "Apply the mark scheme above. The maximum_marks for your awarded_marks field is 2. "
        "Return JSON matching the AIMarkResponse schema."
    )


@pytest.mark.parametrize(
    "answer",
    [
        # Two blocks bound to one part are joined with "; " by the label binder.
        f"it speeds up; {_DESCRIPTION}",
        f"{_DESCRIPTION}; it speeds up",
        f"  {_DESCRIPTION}",
    ],
)
def test_a_description_joined_to_writing_is_still_named(answer: str) -> None:
    prompt = build_marker_user_prompt(_question(), answer)
    assert _DRAWING_HEADER in prompt
    assert _VERBATIM_HEADER not in prompt


def test_the_working_header_is_unchanged_beside_a_drawing() -> None:
    prompt = build_marker_user_prompt(_question(), _DESCRIPTION, "v = 3 x 2")
    assert "WORKING (verbatim from scan, may be partial or messy):\nv = 3 x 2\n" in prompt


# --- what the marker is sent ----------------------------------------------------------


def test_the_marker_call_carries_the_section_and_the_header() -> None:
    captured: list[dict[str, Any]] = []
    AICorrector(_client(captured)).mark_question(_question(), _DESCRIPTION)
    assert len(captured) == 1
    assert captured[0]["system_prompt"] == MARKER_SYSTEM_PROMPT
    assert _SECTION_START in captured[0]["system_prompt"]
    assert _DRAWING_HEADER in captured[0]["user_prompt"]


def test_correct_paper_sends_a_bound_drawing_with_the_header() -> None:
    scheme = MarkScheme.model_validate(
        {
            "metadata": {
                "subject": "Geography",
                "subject_code": "0460",
                "paper_number": 1,
                "paper_variant": 1,
                "session_month": "May/June",
                "session_year": 2021,
                "paper_type": "theory_extended",
                "maximum_mark": 3,
                "scheme_format": "point_based",
            },
            "questions": [
                {
                    "id": "1",
                    "marks": 2,
                    "type": "diagram",
                    "answer_points": [
                        {"id": "p1", "point": "three lines drawn", "marks": 1},
                        {"id": "p2", "point": "arrows point down the slope", "marks": 1},
                    ],
                },
                {
                    "id": "2",
                    "marks": 1,
                    "type": "explanation",
                    "answer_points": [{"id": "p1", "point": "the water runs off", "marks": 1}],
                },
            ],
        }
    )
    extracted = ExtractedAnswers(
        paper_id="p",
        source_scan="s.pdf",
        answers=[
            ExtractedAnswer(question_id="1", answer=_DESCRIPTION, confidence=0.9),
            ExtractedAnswer(question_id="2", answer="it runs off the rock", confidence=0.9),
        ],
    )
    captured: list[dict[str, Any]] = []
    correct_paper(scheme, extracted, gemini_client=_client(captured))
    by_question = {call["extra_cache_key"]: call["user_prompt"] for call in captured}
    assert set(by_question) == {"q=1", "q=2"}
    assert _DRAWING_HEADER in by_question["q=1"]
    assert _DESCRIPTION in by_question["q=1"]
    assert _VERBATIM_HEADER in by_question["q=2"]
    assert "reader's description" not in by_question["q=2"]
