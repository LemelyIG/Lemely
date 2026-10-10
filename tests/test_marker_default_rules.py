"""A science paper stored without its printed marking rules is marked by the published ones.

All 289 corpus schemes were parsed with empty principles, so the marker never saw the
rule on significant figures and refused an answer that rounds to the scheme's. These
tests pin which rules reach the marker for which paper:

- a scheme that prints principles of its own is marked by those, both lists of them;
- a science scheme that prints none gets the default, restated in this project's words;
- a mathematics scheme, or any other syllabus, gets nothing it did not print.

They cannot show that a model then follows the rules: that needs live marking calls.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from lemely.core.loose_schemas import MarkScheme, MarkSchemeMetadata, Question, QuestionType
from lemely.core.schemas import AIMarkResponse, ExtractedAnswer, ExtractedAnswers, PointVerdict
from lemely.io import correction_ai
from lemely.io.correction_ai import AICorrector, correct_paper
from lemely.io.prompts.correction_ai import (
    MARKER_SYSTEM_PROMPT,
    SCIENCE_DEFAULT_RULES,
    SCIENCE_SYLLABUS_CODES,
    VERSION,
    build_marker_user_prompt,
    default_marking_rules,
    printed_principles,
)
from lemely.runtime.config import MarkingOptions

_ROOT = Path(__file__).resolve().parents[1]
_SCHEMES = _ROOT / "corpus" / "mark-schemes"
_DEFAULT_HEADING = "GENERAL MARKING RULES FOR CAMBRIDGE SCIENCE PAPERS"
_PRINTED_HEADING = "THIS PAPER'S PRINTED GENERIC MARKING PRINCIPLES"
_MATHS_CODES = {"0580", "0606"}


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def _scheme(name: str) -> MarkScheme:
    return MarkScheme.model_validate(json.loads((_SCHEMES / f"{name}.json").read_text()))


def _metadata(code: str = "0625", **update: Any) -> MarkSchemeMetadata:
    base = _scheme("0625_w24_ms_41").metadata
    return base.model_copy(update={"subject_code": code, **update})


def _question() -> Question:
    return Question(id="2a", marks=2, type=QuestionType.CALCULATION)


def _client(captured: list[dict[str, Any]]) -> MagicMock:
    """A marker client that records each call and replies with one confident mark."""
    client = MagicMock()
    client._settings.gemini.escalation_confidence_threshold = 0.0
    client._settings.gemini.escalation_model = None
    client._settings.gemini.model_for.return_value = "m"
    client.resolved_thinking.return_value = 0

    def _reply(**kwargs: Any) -> AIMarkResponse:
        captured.append(kwargs)
        return AIMarkResponse(awarded_marks=0, confidence=1.0, matched_point_ids=[], feedback="")

    client.generate_structured.side_effect = _reply
    return client


def _answers(scheme: MarkScheme, count: int = 3) -> ExtractedAnswers:
    """Invented answers for the first ``count`` written leaves of ``scheme``."""
    leaves = [q for q in scheme.all_questions_flat() if not q.parts and q.type != QuestionType.MCQ]
    assert len(leaves) >= count
    return ExtractedAnswers(
        paper_id="p",
        source_scan="s.pdf",
        answers=[
            ExtractedAnswer(question_id=leaf.id, answer=f"invented answer {n}", confidence=0.9)
            for n, leaf in enumerate(leaves[:count])
        ],
    )


def _prompts_sent(scheme: MarkScheme) -> list[str]:
    captured: list[dict[str, Any]] = []
    correct_paper(scheme, _answers(scheme), gemini_client=_client(captured))
    assert len(captured) >= 3
    return [str(call["user_prompt"]) for call in captured]


# --- which paper gets the default -----------------------------------------------------


def test_the_science_syllabuses_are_the_three_the_published_text_names() -> None:
    """Biology, chemistry and physics at IGCSE. Mathematics is not among them."""
    assert frozenset({"0610", "0620", "0625"}) == SCIENCE_SYLLABUS_CODES
    assert not (SCIENCE_SYLLABUS_CODES & _MATHS_CODES)


def test_every_corpus_scheme_gets_the_default_only_if_it_is_a_science_paper() -> None:
    """Over all 289 stored schemes, none of which carries principles of its own."""
    with_default: dict[str, int] = {}
    without: dict[str, int] = {}
    for path in sorted(_SCHEMES.glob("*.json")):
        metadata = MarkScheme.model_validate(json.loads(path.read_text())).metadata
        assert printed_principles(metadata) is None, path.name
        rules = default_marking_rules(metadata)
        if rules is None:
            without[metadata.subject_code] = without.get(metadata.subject_code, 0) + 1
        else:
            assert rules == SCIENCE_DEFAULT_RULES
            with_default[metadata.subject_code] = with_default.get(metadata.subject_code, 0) + 1
    assert set(with_default) == {"0625"}
    assert set(without) == _MATHS_CODES
    assert sum(with_default.values()) + sum(without.values()) >= 289
    assert with_default["0625"] >= 143
    assert without["0580"] >= 130
    assert without["0606"] >= 16


@pytest.mark.parametrize("code", ["0610", "0620", "0625"])
def test_a_science_scheme_with_no_printed_principles_gets_the_default(code: str) -> None:
    assert default_marking_rules(_metadata(code)) == SCIENCE_DEFAULT_RULES


@pytest.mark.parametrize("code", ["0580", "0606", "0460", "9709", "0500", "0972", "9702", ""])
def test_any_other_syllabus_gets_no_default(code: str) -> None:
    """Mathematics has different rules, and no other syllabus's scheme has been read."""
    assert default_marking_rules(_metadata(code)) is None


@pytest.mark.parametrize(
    "printed",
    [
        {"generic_marking_principles": ["Marks are whole marks."]},
        {"subject_specific_principles": ["Printed science rule."]},
        {
            "generic_marking_principles": ["Marks are whole marks."],
            "subject_specific_principles": ["Printed science rule."],
        },
    ],
)
def test_a_science_scheme_with_any_printed_principles_gets_no_default(
    printed: dict[str, list[str]],
) -> None:
    """The default stands in for principles that were not stored, never beside stored ones."""
    metadata = _metadata("0625", **printed)
    assert default_marking_rules(metadata) is None
    assert printed_principles(metadata) is not None


def test_whitespace_is_not_a_printed_principle() -> None:
    metadata = _metadata("0625", generic_marking_principles=["", "  "])
    assert printed_principles(metadata) is None
    assert default_marking_rules(metadata) == SCIENCE_DEFAULT_RULES


# --- the paper's own principles, both lists -------------------------------------------


def test_printed_principles_are_the_generic_ones_then_the_subject_specific_ones() -> None:
    metadata = _metadata(
        "0580",
        generic_marking_principles=["G one.", "G two."],
        subject_specific_principles=["S one."],
    )
    assert printed_principles(metadata) == ["G one.", "G two.", "S one."]
    assert printed_principles(_metadata("0580")) is None
    only_subject = _metadata("0580", subject_specific_principles=["S one."])
    assert printed_principles(only_subject) == ["S one."]


def test_a_stored_scheme_with_both_lists_sends_both_to_the_marker() -> None:
    """A golden scheme parsed with its front matter: its science rules used to be dropped."""
    golden = _ROOT / "tests" / "golden" / "0625_s20_qp_31_theory_correct" / "mark_scheme.json"
    scheme = MarkScheme.model_validate(json.loads(golden.read_text()))
    generic = scheme.metadata.generic_marking_principles
    subject = scheme.metadata.subject_specific_principles
    assert generic and subject
    for prompt in _prompts_sent(scheme):
        assert _PRINTED_HEADING in prompt
        for principle in (*generic, *subject):
            assert principle in prompt
        assert _DEFAULT_HEADING not in prompt


# --- what the default says ------------------------------------------------------------


def test_the_default_says_it_is_not_this_papers_text() -> None:
    rules = _squash(SCIENCE_DEFAULT_RULES)
    assert rules.startswith(_DEFAULT_HEADING)
    assert "they are not text from this paper" in rules
    assert "verbatim" not in rules.lower()


def test_the_default_covers_each_published_topic() -> None:
    rules = _squash(SCIENCE_DEFAULT_RULES)
    for topic in (
        "- Keywords:",
        "- Contradictions:",
        "- Spelling:",
        "- Error carried forward:",
        "- Lists:",
        "- Calculations:",
        "- Significant figures:",
        "- Standard form:",
        "- Units:",
        "- Chemical equations:",
    ):
        assert rules.count(topic) == 1, topic


def test_the_significant_figures_rule_rounds_the_students_answer_to_the_schemes() -> None:
    rules = _squash(SCIENCE_DEFAULT_RULES)
    assert (
        "round the student's final answer to the number of significant figures in the mark "
        "scheme's answer; if it then equals the mark scheme's answer, it is correct"
    ) in rules
    # It applies only where the entry is silent, and it is shown refusing as well as accepting.
    assert "where the mark scheme entry does not say how many significant figures" in rules
    assert "7.26 J is correct, and 7.2 J and 7 J are not" in rules
    assert "may not hold for a value the student had to measure" in rules


def test_a_rule_never_loosens_a_point_that_sets_its_own_precision() -> None:
    rules = _squash(SCIENCE_DEFAULT_RULES)
    assert "The MARK SCHEME SUBTREE above always wins." in rules
    assert (
        "Where an entry sets its own precision or says an exact value is required (a stated "
        "number of significant figures or decimal places, a tolerance or a range, cao, "
        '"exact", or accept / reject / ignore forms), apply the entry as written: none of '
        "these rules loosens it."
    ) in rules
    # Last, so it is read after every rule it limits.
    assert rules.index("always wins") > rules.index("- Chemical equations:")


def test_error_carried_forward_needs_the_wrong_value_to_be_seen() -> None:
    rules = _squash(SCIENCE_DEFAULT_RULES)
    assert (
        "Apply this only where the student's working, or an earlier-part value supplied below, "
        "shows the wrong value being used; never assume it."
    ) in rules


def test_the_default_does_not_penalise_a_missing_unit() -> None:
    """The paper often prints the unit on the answer line, and the marker is not shown it."""
    rules = _squash(SCIENCE_DEFAULT_RULES)
    assert "given with a wrong unit does not earn the final answer mark" in rules
    assert (
        "these rules say nothing about an answer written with no unit, so treat that case "
        "exactly as you would without them"
    ) in rules


def test_the_default_leaves_the_method_before_accuracy_rule_where_it_was() -> None:
    rules = _squash(SCIENCE_DEFAULT_RULES)
    assert (
        "no Generic Marking Principles are supplied for this paper, so the system prompt's "
        "fallback for that still applies"
    ) in rules
    # The system prompt's own rule is untouched by this change.
    assert "FALLBACK ONLY — where no Generic Marking Principles are supplied" in (
        MARKER_SYSTEM_PROMPT
    )


def test_the_default_gives_precedence_to_the_scheme_and_only_then_to_itself() -> None:
    rules = _squash(SCIENCE_DEFAULT_RULES)
    assert (
        "These rules take precedence over the general guidance in the system prompt only "
        "where the two differ."
    ) in rules


def test_the_default_is_pinned_to_the_marker_prompt_version() -> None:
    """The rules are marker prompt text. A change to them is a change of ``VERSION``.

    When this goes red: bump ``VERSION`` in ``lemely/io/prompts/correction_ai.py``, re-pin
    both values here, and re-pin the other ``VERSION`` tests. The text is unmeasured, so
    there is no measurement to redo yet.
    """
    assert (VERSION, hashlib.sha256(SCIENCE_DEFAULT_RULES.encode()).hexdigest()) == (
        "10",
        "59069e6f122c7f608abf7dfaf2150ee7a7052818ed6615a9c7e187d294e6be2e",
    )


# --- the user prompt ------------------------------------------------------------------


def test_the_default_is_appended_to_the_user_prompt() -> None:
    without = build_marker_user_prompt(_question(), "7.26 J")
    with_default = build_marker_user_prompt(_question(), "7.26 J", default_rules="RULES\n")
    assert "RULES\n" in with_default
    assert with_default.replace("RULES\n\n", "") == without
    # After the answer, before the closing instruction.
    assert (
        with_default.index("STUDENT ANSWER")
        < with_default.index("RULES")
        < with_default.index("Apply the mark scheme above.")
    )


def test_printed_principles_displace_the_default_in_the_prompt_itself() -> None:
    """Even if a caller passes both, the paper's own text is the only one sent."""
    prompt = build_marker_user_prompt(
        _question(), "7.26 J", principles=["Printed."], default_rules=SCIENCE_DEFAULT_RULES
    )
    assert _PRINTED_HEADING in prompt
    assert _DEFAULT_HEADING not in prompt


def test_a_paper_with_no_default_has_the_prompt_it_had_before() -> None:
    question = _question()
    q_json = question.model_dump_json(indent=2, exclude_none=True, exclude_defaults=True)
    assert build_marker_user_prompt(question, "x = 4", default_rules=None) == (
        "Mark this CAIE question.\n\n"
        f"MARK SCHEME SUBTREE (JSON):\n{q_json}\n\n"
        "STUDENT ANSWER (verbatim from scan):\nx = 4\n\n"
        "Apply the mark scheme above. The maximum_marks for your awarded_marks field is 2. "
        "Return JSON matching the AIMarkResponse schema."
    )


def test_the_default_changes_the_prompt_so_it_changes_the_cache_key() -> None:
    assert build_marker_user_prompt(_question(), "x") != build_marker_user_prompt(
        _question(), "x", default_rules=SCIENCE_DEFAULT_RULES
    )


# --- what the marker is sent ----------------------------------------------------------


def test_mark_question_forwards_the_default() -> None:
    captured: list[dict[str, Any]] = []
    AICorrector(_client(captured)).mark_question(
        _question(), "7.26 J", default_rules=SCIENCE_DEFAULT_RULES
    )
    assert SCIENCE_DEFAULT_RULES in captured[0]["user_prompt"]


def test_every_marking_call_on_the_measured_physics_paper_carries_the_default() -> None:
    prompts = _prompts_sent(_scheme("0625_w24_ms_41"))
    for prompt in prompts:
        assert prompt.count(SCIENCE_DEFAULT_RULES) == 1
        assert _PRINTED_HEADING not in prompt


@pytest.mark.parametrize("name", ["0580_s21_ms_31", "0606_s19_ms_23"])
def test_no_marking_call_on_a_mathematics_paper_carries_it(name: str) -> None:
    for prompt in _prompts_sent(_scheme(name)):
        assert _DEFAULT_HEADING not in prompt
        assert "SCIENCE" not in prompt
        assert "MARKING PRINCIPLES" not in prompt
        assert "MARKING RULES" not in prompt


def test_a_science_paper_with_printed_principles_is_marked_by_those_alone() -> None:
    scheme = _scheme("0625_w24_ms_41")
    printed = scheme.model_copy(
        update={
            "metadata": scheme.metadata.model_copy(
                update={"subject_specific_principles": ["An invented printed rule."]}
            )
        }
    )
    for prompt in _prompts_sent(printed):
        assert "An invented printed rule." in prompt
        assert _PRINTED_HEADING in prompt
        assert _DEFAULT_HEADING not in prompt


def test_the_error_carried_forward_re_mark_carries_the_default_too() -> None:
    """The second marking call for a part is the same paper under the same rules."""
    scheme = MarkScheme.model_validate(
        {
            "metadata": {
                "subject": "Physics",
                "subject_code": "0625",
                "paper_number": 3,
                "paper_variant": 2,
                "session_month": "Oct/Nov",
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
            ExtractedAnswer(question_id="1a", answer="an invented wrong value", confidence=0.9),
            ExtractedAnswer(question_id="1b", answer="working that follows it", confidence=0.9),
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
    for _, kwargs in marked.call_args_list:
        assert kwargs["default_rules"] == SCIENCE_DEFAULT_RULES
        assert kwargs["principles"] is None
    assert marked.call_args_list[2].kwargs["prior_values"]
