"""The marker is told when an answer is the reader's description of a drawing.

The reader opens such an answer with ``Drawing:`` (``tests/test_label_binding_prompt.py``).
The marker never sees the page, so the description is all the evidence there is. Two
failures are guarded: refusing marks "because no diagram was provided", and awarding a
mark for a detail the description never stated.

The marker is told so only for an answer the label binder's reader wrote from a scan
(``binding_source == "label"``). A student can write or type ``Drawing:``, so the word in
the text proves nothing: on every other path (a typed quiz answer, a plain mapping, a
legacy extraction) both prompts are what they were before the reader described drawings.

These tests pin what the marker is told. What a model then does needs live marking calls.
"""

from __future__ import annotations

import hashlib
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from lemely.core.loose_schemas import MarkScheme, Question, QuestionType
from lemely.core.schemas import AIMarkResponse, ExtractedAnswer, ExtractedAnswers, PointVerdict
from lemely.io import correction_ai
from lemely.io.correction_ai import AICorrector, correct_paper
from lemely.io.prompts.correction_ai import (
    MARKER_SYSTEM_PROMPT,
    READER_MARKER_SYSTEM_PROMPT,
    build_marker_user_prompt,
    marker_system_prompt,
)
from lemely.runtime.config import MarkingOptions

_SECTION_START = "**Drawings, diagrams and graphs:**"
_SECTION_END = "**When WORKING is supplied:**"
# The section every marking call had before the reader described drawings (VERSION "7").
_OLD_SECTION = (
    "**Diagrams / graphs:**\n"
    "- The student's response is given as a text description by an earlier OCR pass. Mark\n"
    "  accordingly; set confidence < 0.5 if the description is too vague to judge.\n\n"
)
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


# What a student might write or type to be taken for the reader. Invented.
_STUDENT_WROTE_THE_WORD = "Drawing: 3 straight lines, an arrowhead on each, pointing down."


def _section() -> str:
    prompt = READER_MARKER_SYSTEM_PROMPT
    return " ".join(prompt[prompt.index(_SECTION_START) : prompt.index(_SECTION_END)].split())


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


def test_both_system_prompts_are_pinned_whole() -> None:
    """The two texts as they stand since VERSION "10". No part of either is exempt.

    ``tests/test_correction_off_topic.py`` pins the default prompt against VERSION "5" with
    one section cut out, so an edit inside that section would pass there. When this goes
    red: bump ``VERSION`` in ``lemely/io/prompts/correction_ai.py`` and re-pin. The reader's
    drawings section is unmeasured, so there is no measurement to redo yet.
    """
    assert hashlib.sha256(MARKER_SYSTEM_PROMPT.encode()).hexdigest() == (
        "f3c3b9df5d0c756b26335a02a86cbd66a13fb2a71b50cf3733690a3b0e2d2977"
    )
    assert hashlib.sha256(READER_MARKER_SYSTEM_PROMPT.encode()).hexdigest() == (
        "514eb6dbcaef089b2c94f927055e0523f6035d2ce67a1688ceb4a556fc50031f"
    )


def test_the_reader_prompt_differs_from_the_default_in_the_drawings_section_alone() -> None:
    assert MARKER_SYSTEM_PROMPT.count(_OLD_SECTION) == 1
    start = READER_MARKER_SYSTEM_PROMPT.index(_SECTION_START)
    end = READER_MARKER_SYSTEM_PROMPT.index(_SECTION_END)
    assert READER_MARKER_SYSTEM_PROMPT.count(_SECTION_START) == 1
    assert (
        READER_MARKER_SYSTEM_PROMPT[:start] + _OLD_SECTION + READER_MARKER_SYSTEM_PROMPT[end:]
        == MARKER_SYSTEM_PROMPT
    )
    assert "**Diagrams / graphs:**" not in READER_MARKER_SYSTEM_PROMPT
    assert "an earlier OCR pass" not in READER_MARKER_SYSTEM_PROMPT


def test_the_default_system_prompt_does_not_name_the_word() -> None:
    """Where no reader wrote the answer, nothing tells the marker to believe `Drawing:`."""
    assert "Drawing:" not in MARKER_SYSTEM_PROMPT
    assert _SECTION_START not in MARKER_SYSTEM_PROMPT
    assert "written by the reader" not in MARKER_SYSTEM_PROMPT
    assert "The drawing is on the page" not in MARKER_SYSTEM_PROMPT


def test_the_system_prompt_is_chosen_by_who_wrote_the_answer() -> None:
    assert marker_system_prompt() == MARKER_SYSTEM_PROMPT
    assert marker_system_prompt(reader_describes_drawings=False) == MARKER_SYSTEM_PROMPT
    assert marker_system_prompt(reader_describes_drawings=True) == READER_MARKER_SYSTEM_PROMPT


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


def test_a_description_the_reader_did_not_open_with_the_word_is_marked_the_same() -> None:
    section = _section()
    assert (
        "A description of a drawing that the reader did not open with `Drawing:` is marked by "
        "the same rules."
    ) in section
    # This prompt goes only with the label binder's reader: there is no older reader to name.
    assert "older reader" not in READER_MARKER_SYSTEM_PROMPT


# --- user prompt --------------------------------------------------------------------


def test_a_readers_drawing_answer_is_not_called_verbatim() -> None:
    prompt = build_marker_user_prompt(_question(), _DESCRIPTION, reader_describes_drawings=True)
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
def test_a_readers_written_answer_keeps_the_verbatim_header(answer: str) -> None:
    prompt = build_marker_user_prompt(_question(), answer, reader_describes_drawings=True)
    assert _VERBATIM_HEADER in prompt
    assert "reader's description" not in prompt


def test_a_readers_written_answer_has_the_prompt_it_had_before() -> None:
    """From the reader, only an answer holding `Drawing:` changes the user prompt."""
    question = _question()
    q_json = question.model_dump_json(indent=2, exclude_none=True, exclude_defaults=True)
    assert build_marker_user_prompt(question, "three lines", reader_describes_drawings=True) == (
        "Mark this CAIE question.\n\n"
        f"MARK SCHEME SUBTREE (JSON):\n{q_json}\n\n"
        "STUDENT ANSWER (verbatim from scan):\nthree lines\n\n"
        "Apply the mark scheme above. The maximum_marks for your awarded_marks field is 2. "
        "Return JSON matching the AIMarkResponse schema."
    )


@pytest.mark.parametrize(
    "answer",
    [
        _STUDENT_WROTE_THE_WORD,
        f"it speeds up; {_STUDENT_WROTE_THE_WORD}",
        _DESCRIPTION,
    ],
)
def test_the_word_alone_never_changes_the_prompt(answer: str) -> None:
    """Not from the reader: the text is what it was before the reader described drawings."""
    question = _question()
    q_json = question.model_dump_json(indent=2, exclude_none=True, exclude_defaults=True)
    before = (
        "Mark this CAIE question.\n\n"
        f"MARK SCHEME SUBTREE (JSON):\n{q_json}\n\n"
        f"STUDENT ANSWER (verbatim from scan):\n{answer}\n\n"
        "Apply the mark scheme above. The maximum_marks for your awarded_marks field is 2. "
        "Return JSON matching the AIMarkResponse schema."
    )
    assert build_marker_user_prompt(question, answer) == before
    assert build_marker_user_prompt(question, answer, reader_describes_drawings=False) == before
    assert "reader's description" not in before


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
    prompt = build_marker_user_prompt(_question(), answer, reader_describes_drawings=True)
    assert _DRAWING_HEADER in prompt
    assert _VERBATIM_HEADER not in prompt


def test_the_working_header_is_unchanged_beside_a_drawing() -> None:
    prompt = build_marker_user_prompt(
        _question(), _DESCRIPTION, "v = 3 x 2", reader_describes_drawings=True
    )
    assert "WORKING (verbatim from scan, may be partial or messy):\nv = 3 x 2\n" in prompt


# --- what the marker is sent ----------------------------------------------------------


def _two_part_scheme() -> MarkScheme:
    return MarkScheme.model_validate(
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


def _calls_by_question(
    extracted: ExtractedAnswers | dict[str, str], **options: bool
) -> dict[str, dict[str, Any]]:
    captured: list[dict[str, Any]] = []
    correct_paper(
        _two_part_scheme(),
        extracted,
        gemini_client=_client(captured),
        options=MarkingOptions(**options),
    )
    by_question = {str(call["extra_cache_key"]): call for call in captured}
    assert set(by_question) == {"q=1", "q=2"}
    return by_question


def _assert_marked_as_the_students_own_text(call: dict[str, Any], answer: str) -> None:
    """Both prompts of ``call`` are the ones from before the reader described drawings."""
    assert call["system_prompt"] == MARKER_SYSTEM_PROMPT
    assert "Drawing:" not in call["system_prompt"]
    assert f"{_VERBATIM_HEADER}\n{answer}\n" in call["user_prompt"]
    assert "reader's description" not in call["user_prompt"]
    assert "not the student's own words" not in call["user_prompt"]


def test_the_marker_call_for_a_readers_answer_carries_the_section_and_the_header() -> None:
    captured: list[dict[str, Any]] = []
    AICorrector(_client(captured)).mark_question(
        _question(), _DESCRIPTION, reader_describes_drawings=True
    )
    assert len(captured) == 1
    assert captured[0]["system_prompt"] == READER_MARKER_SYSTEM_PROMPT
    assert _SECTION_START in captured[0]["system_prompt"]
    assert _DRAWING_HEADER in captured[0]["user_prompt"]


def test_the_marker_call_is_off_unless_asked_for() -> None:
    captured: list[dict[str, Any]] = []
    AICorrector(_client(captured)).mark_question(_question(), _STUDENT_WROTE_THE_WORD)
    assert len(captured) == 1
    _assert_marked_as_the_students_own_text(captured[0], _STUDENT_WROTE_THE_WORD)


def test_every_call_for_one_answer_uses_the_same_system_prompt() -> None:
    """The low-confidence retry and the escalation mark the answer under the first call's rules."""
    for flag, expected in ((True, READER_MARKER_SYSTEM_PROMPT), (False, MARKER_SYSTEM_PROMPT)):
        captured: list[dict[str, Any]] = []
        client = _client(captured)
        client._settings.gemini.escalation_confidence_threshold = 2.0
        client._settings.gemini.escalation_model = "other"
        client.resolved_thinking.side_effect = lambda tag, model: {
            "correction": 0,
            "correction_borderline": 1,
            "escalation": 2,
        }[tag]
        with patch.object(correction_ai, "thinking_rank", side_effect=lambda value: value):
            AICorrector(client).mark_question(
                _question(), _DESCRIPTION, reader_describes_drawings=flag
            )
        assert [call["task_tag"] for call in captured] == [
            "correction",
            "correction_borderline",
            "escalation",
        ]
        assert [call["system_prompt"] for call in captured] == [expected] * 3


def test_correct_paper_sends_a_scanned_drawing_read_by_the_label_reader_with_the_rule() -> None:
    extracted = ExtractedAnswers(
        paper_id="p",
        source_scan="s.pdf",
        answers=[
            ExtractedAnswer(
                question_id="1", answer=_DESCRIPTION, confidence=0.9, binding_source="label"
            ),
            ExtractedAnswer(
                question_id="2",
                answer="it runs off the rock",
                confidence=0.9,
                binding_source="label",
            ),
        ],
    )
    by_question = _calls_by_question(extracted)
    for call in by_question.values():
        assert call["system_prompt"] == READER_MARKER_SYSTEM_PROMPT
    assert f"{_DRAWING_HEADER}\n{_DESCRIPTION}\n" in by_question["q=1"]["user_prompt"]
    assert _VERBATIM_HEADER not in by_question["q=1"]["user_prompt"]
    assert _VERBATIM_HEADER in by_question["q=2"]["user_prompt"]
    assert "reader's description" not in by_question["q=2"]["user_prompt"]


def test_a_typed_quiz_answer_that_starts_with_the_word_is_the_students_text() -> None:
    """The extraction ``lemely/db/quiz_marking_repo.py`` builds: typed text, no scan, no reader."""
    extracted = ExtractedAnswers(
        paper_id="assignment",
        source_scan="quiz",
        answers=[
            ExtractedAnswer(question_id="1", answer=_STUDENT_WROTE_THE_WORD, confidence=1.0),
            ExtractedAnswer(question_id="2", answer="it runs off the rock", confidence=1.0),
        ],
    )
    by_question = _calls_by_question(extracted)
    _assert_marked_as_the_students_own_text(by_question["q=1"], _STUDENT_WROTE_THE_WORD)
    _assert_marked_as_the_students_own_text(by_question["q=2"], "it runs off the rock")
    # To the byte, the user prompt from before the reader described drawings.
    question = _two_part_scheme().questions[0]
    q_json = question.model_dump_json(indent=2, exclude_none=True, exclude_defaults=True)
    assert by_question["q=1"]["user_prompt"] == (
        "Mark this CAIE question.\n\n"
        f"MARK SCHEME SUBTREE (JSON):\n{q_json}\n\n"
        f"STUDENT ANSWER (verbatim from scan):\n{_STUDENT_WROTE_THE_WORD}\n\n"
        "Apply the mark scheme above. The maximum_marks for your awarded_marks field is 2. "
        "Return JSON matching the AIMarkResponse schema."
    )


def test_a_plain_mapping_answer_that_starts_with_the_word_is_the_students_text() -> None:
    by_question = _calls_by_question({"1": _STUDENT_WROTE_THE_WORD, "2": "it runs off the rock"})
    _assert_marked_as_the_students_own_text(by_question["q=1"], _STUDENT_WROTE_THE_WORD)
    _assert_marked_as_the_students_own_text(by_question["q=2"], "it runs off the rock")


@pytest.mark.parametrize("source", ["legacy", "position", None])
def test_an_answer_no_label_reader_wrote_is_the_students_text(source: Any) -> None:
    """A legacy extraction's reader is not asked for the word, so there it is transcribed."""
    extracted = ExtractedAnswers(
        paper_id="p",
        source_scan="s.pdf",
        answers=[
            ExtractedAnswer(
                question_id="1",
                answer=_STUDENT_WROTE_THE_WORD,
                confidence=0.9,
                binding_source=source,
            ),
            ExtractedAnswer(
                question_id="2",
                answer="it runs off the rock",
                confidence=0.9,
                binding_source=source,
            ),
        ],
    )
    by_question = _calls_by_question(extracted)
    _assert_marked_as_the_students_own_text(by_question["q=1"], _STUDENT_WROTE_THE_WORD)


def test_the_rule_is_decided_answer_by_answer() -> None:
    extracted = ExtractedAnswers(
        paper_id="p",
        source_scan="s.pdf",
        answers=[
            ExtractedAnswer(
                question_id="1", answer=_DESCRIPTION, confidence=0.9, binding_source="label"
            ),
            ExtractedAnswer(
                question_id="2",
                answer=_STUDENT_WROTE_THE_WORD,
                confidence=0.9,
                binding_source="legacy",
            ),
        ],
    )
    by_question = _calls_by_question(extracted)
    assert by_question["q=1"]["system_prompt"] == READER_MARKER_SYSTEM_PROMPT
    assert _DRAWING_HEADER in by_question["q=1"]["user_prompt"]
    _assert_marked_as_the_students_own_text(by_question["q=2"], _STUDENT_WROTE_THE_WORD)


def test_a_crop_re_read_marked_in_place_of_the_readers_text_is_not_a_description() -> None:
    """The re-read is another reader's text, and that reader is not asked for the word."""
    reread = "Drawing: something the re-read transcribed"
    extracted = ExtractedAnswers(
        paper_id="p",
        source_scan="s.pdf",
        answers=[
            ExtractedAnswer(
                question_id="1",
                answer=_DESCRIPTION,
                confidence=0.9,
                binding_source="label",
                answer_reread=reread,
                reread_agreement=0.0,
            ),
            ExtractedAnswer(
                question_id="2",
                answer="it runs off the rock",
                confidence=0.9,
                binding_source="label",
            ),
        ],
    )
    substituted = _calls_by_question(extracted, reread_substitution=True)
    _assert_marked_as_the_students_own_text(substituted["q=1"], reread)
    assert substituted["q=2"]["system_prompt"] == READER_MARKER_SYSTEM_PROMPT
    # With substitution off the reader's own text is marked, as a description.
    kept = _calls_by_question(extracted)
    assert kept["q=1"]["system_prompt"] == READER_MARKER_SYSTEM_PROMPT
    assert f"{_DRAWING_HEADER}\n{_DESCRIPTION}\n" in kept["q=1"]["user_prompt"]


@pytest.mark.parametrize(("source", "expected"), [("label", True), (None, False)])
def test_the_error_carried_forward_re_mark_is_told_the_same(source: Any, expected: bool) -> None:
    """The second marking call for a part marks the same text from the same reader."""
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
                "maximum_mark": 2,
                "scheme_format": "point_based",
            },
            "questions": [
                {
                    "id": "1",
                    "marks": 0,
                    "type": "calculation",
                    "parts": [
                        {
                            "id": "1a",
                            "marks": 1,
                            "type": "calculation",
                            "parent_id": "1",
                            "answer_points": [
                                {
                                    "id": "p1",
                                    "point": "method in any form",
                                    "marks": 1,
                                    "math_mark_type": "M",
                                }
                            ],
                        },
                        {
                            "id": "1b",
                            "marks": 1,
                            "type": "calculation",
                            "parent_id": "1",
                            "answer_points": [
                                {
                                    "id": "p1",
                                    "point": "final value",
                                    "marks": 1,
                                    "math_mark_type": "A",
                                    "condition": "ecf",
                                }
                            ],
                        },
                    ],
                }
            ],
        }
    )
    extracted = ExtractedAnswers(
        paper_id="p",
        source_scan="s.pdf",
        answers=[
            ExtractedAnswer(
                question_id="1a",
                answer="an invented wrong value",
                confidence=0.9,
                binding_source=source,
            ),
            ExtractedAnswer(
                question_id="1b",
                answer="working that follows it",
                confidence=0.9,
                binding_source=source,
            ),
        ],
    )

    def _mark(verdict: str, span: str = "") -> AIMarkResponse:
        return AIMarkResponse(
            awarded_marks=0,
            confidence=0.95,
            matched_point_ids=[],
            feedback="",
            point_verdicts=[PointVerdict(point_id="p1", verdict=verdict, evidence_span=span)],
        )

    with patch.object(
        correction_ai.AICorrector,
        "mark_question",
        side_effect=[_mark("withheld"), _mark("withheld"), _mark("awarded", "follows")],
    ) as marked:
        correct_paper(
            mark_scheme=scheme,
            extracted_answers=extracted,
            gemini_client=MagicMock(),
            options=MarkingOptions(equivalence_gate=True, ecf_substitution=True),
        )
    assert marked.call_count == 3
    assert marked.call_args_list[2].kwargs["prior_values"]
    for _, kwargs in marked.call_args_list:
        assert kwargs["reader_describes_drawings"] is expected
