"""Sub-project C lever H2b: verdicts and rationale before the mark, summed and checked in code."""

from __future__ import annotations

import json
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from lemely.accuracy.cost_ladder.real_split import ReplyLog
from lemely.core.loose_schemas import AnswerPoint, MathMarkType, Question, QuestionType
from lemely.core.schemas import (
    AIMarkResponse,
    AIMarkResponseReasoned,
    AIMarkResponseReasonedTerse,
    PointVerdict,
    PointVerdictReasoned,
    marker_response_schema,
)
from lemely.io.correction_ai import AICorrector, _verdict_checked
from lemely.io.gemini import GeminiClient
from lemely.io.prompts.correction_ai import build_marker_user_prompt
from lemely.io.providers.claude_schema import prompt_json_for, sendable_schema
from lemely.runtime.errors import ConfigError
from tests.gemini_fakes import fake_genai_client, make_settings

_REPLY_ORDER = [
    "point_verdicts",
    "feedback",
    "matched_point_ids",
    "awarded_marks",
    "confidence",
    "addresses_question",
]


def _question(points: list[AnswerPoint], marks: int = 2) -> Question:
    return Question.model_construct(
        id="7",
        marks=marks,
        type=QuestionType.EXPLANATION,
        answer_points=points,
        select_count=None,
        parts=[],
        assessment_objectives=[],
        rejected_answers=[],
        ignored_answers=[],
    )


def _two_points() -> Question:
    return _question(
        [
            AnswerPoint(id="p1", point="gravity", marks=1),
            AnswerPoint(id="p2", point="mass", marks=1),
        ]
    )


def _verdicts(**by_id: str) -> list[PointVerdict]:
    return [PointVerdict(point_id=pid, verdict=v) for pid, v in by_id.items()]  # type: ignore[arg-type]


def _reply(marks: int, verdicts: list[PointVerdict], conf: float = 0.95) -> AIMarkResponse:
    return AIMarkResponse(
        awarded_marks=marks,
        confidence=conf,
        matched_point_ids=[],
        feedback="f",
        point_verdicts=verdicts,
    )


# The schema of the default reply, taken before H2b: key order and the required list.
_DEFAULT_PROPERTY_ORDER = [
    "awarded_marks",
    "confidence",
    "matched_point_ids",
    "feedback",
    "point_verdicts",
    "addresses_question",
]
_DEFAULT_REQUIRED = ["awarded_marks", "confidence", "feedback", "addresses_question"]


def test_default_schema_unchanged() -> None:
    assert marker_response_schema(cited=False) is AIMarkResponse
    schema = AIMarkResponse.model_json_schema()
    assert list(schema["properties"]) == _DEFAULT_PROPERTY_ORDER
    assert schema["required"] == _DEFAULT_REQUIRED
    assert list(schema["$defs"]["PointVerdict"]["properties"]) == [
        "point_id",
        "verdict",
        "evidence_span",
        "note",
        "ecf_applied",
    ]
    assert schema["$defs"]["PointVerdict"]["required"] == ["point_id", "verdict"]


@pytest.mark.parametrize("model", [AIMarkResponseReasoned, AIMarkResponseReasonedTerse])
def test_reasoned_wire_order_and_required(model: type[AIMarkResponse]) -> None:
    schema = sendable_schema(model)
    assert list(schema["properties"]) == _REPLY_ORDER
    assert schema["required"] == _REPLY_ORDER
    verdict = schema["$defs"]["PointVerdictReasoned"]
    order = ["point_id", "evidence_span", "note", "verdict"]
    assert list(verdict["properties"]) == order
    assert verdict["required"] == order
    assert "ecf_applied" not in verdict["properties"]
    assert "description" not in verdict  # a docstring must never become wire text
    assert prompt_json_for(model) is False


def test_reasoned_reply_parses_into_an_AIMarkResponse() -> None:
    reply = AIMarkResponseReasoned.model_validate_json(
        json.dumps(
            {
                "point_verdicts": [
                    {"point_id": "p1", "evidence_span": "", "note": "n", "verdict": "awarded"}
                ],
                "feedback": "f",
                "matched_point_ids": ["p1"],
                "awarded_marks": 1,
                "confidence": 0.9,
                "addresses_question": "yes",
            }
        )
    )
    assert isinstance(reply, AIMarkResponse)
    assert reply.point_verdicts[0].ecf_applied is False
    assert reply.stated_mark == 1


def test_prompt_block_only_when_on() -> None:
    q = _two_points()
    assert build_marker_user_prompt(q, "a") == build_marker_user_prompt(q, "a", reason_first=False)
    on = build_marker_user_prompt(q, "a", reason_first=True)
    assert "REASON BEFORE MARK" in on
    assert "REASON BEFORE MARK" not in build_marker_user_prompt(q, "a")
    assert "point_verdicts: one entry for every AnswerPoint id" in on
    assert "p1" in on and "p2" in on
    empty = build_marker_user_prompt(_question([]), "a", reason_first=True)
    assert "REASON BEFORE MARK: leave point_verdicts empty" in empty


def test_sum_check_corrects_a_stated_mark_that_contradicts_the_verdicts() -> None:
    out = _verdict_checked(_two_points(), _reply(1, _verdicts(p1="awarded", p2="awarded")))
    assert out.awarded_marks == 2
    assert out.matched_point_ids == ["p1", "p2"]


def test_sum_check_respects_group_caps() -> None:
    q = _question(
        [
            AnswerPoint(id="p1", point="5.5 (kW h)", marks=2, math_mark_type=MathMarkType.A),
            AnswerPoint(
                id="p2",
                point="formula",
                marks=1,
                math_mark_type=MathMarkType.C,
                is_alternative=True,
            ),
        ]
    )
    both = _verdict_checked(q, _reply(2, _verdicts(p1="awarded", p2="awarded")))
    assert both.awarded_marks == 2
    only_c = _verdict_checked(q, _reply(2, _verdicts(p1="withheld", p2="awarded")))
    assert only_c.awarded_marks == 1


@pytest.mark.parametrize(
    "verdicts", [_verdicts(p1="awarded"), _verdicts(p1="awarded", p2="awarded", p9="awarded")]
)
def test_sum_check_leaves_incomplete_verdicts_alone(verdicts: list[PointVerdict]) -> None:
    reply = _reply(0, verdicts)
    assert _verdict_checked(_two_points(), reply) is reply


def test_sum_check_leaves_a_reply_without_verdicts_alone() -> None:
    reply = _reply(1, [])
    assert _verdict_checked(_two_points(), reply) is reply


def _client(**gemini: object) -> GeminiClient:
    settings = make_settings(tempfile.mkdtemp())
    g = settings.gemini.model_copy(update={"escalation_model": None, **gemini})
    return GeminiClient(
        settings.model_copy(update={"gemini": g}), _genai_client=fake_genai_client(), ledger=None
    )


def _reasoned(marks: int, verdicts: dict[str, str], conf: float = 0.95) -> AIMarkResponseReasoned:
    return AIMarkResponseReasoned(
        awarded_marks=marks,
        confidence=conf,
        matched_point_ids=[],
        feedback="f",
        point_verdicts=[
            PointVerdictReasoned(point_id=pid, verdict=v)  # type: ignore[arg-type]
            for pid, v in verdicts.items()
        ],
    )


def _mark(client: GeminiClient, replies: list[AIMarkResponse]) -> tuple[AIMarkResponse, MagicMock]:
    ai = AICorrector(client)
    with patch.object(client, "generate_structured", side_effect=replies) as call:
        return ai.mark_question(_two_points(), "a"), call


def test_corrector_sends_the_reasoned_schema_only_when_on() -> None:
    _, off = _mark(_client(), [_reply(1, [])])
    assert off.call_args.kwargs["response_schema"] is AIMarkResponse
    assert "REASON BEFORE MARK" not in off.call_args.kwargs["user_prompt"]
    _, on = _mark(_client(correction_reason_first=True), [_reasoned(0, {})])
    assert on.call_args.kwargs["response_schema"] is AIMarkResponseReasoned
    assert "REASON BEFORE MARK" in on.call_args.kwargs["user_prompt"]
    client = MagicMock()
    client._settings.gemini.escalation_confidence_threshold = 0.8
    client._settings.gemini.escalation_model = None
    client.generate_structured.return_value = _reply(1, [])
    ai = AICorrector(client)
    with patch.object(ai, "_resolved_thinking", side_effect=["low", "high"]):
        ai.mark_question(_two_points(), "a")
    assert client.generate_structured.call_args.kwargs["response_schema"] is AIMarkResponse


def test_corrector_refuses_reason_first_with_citations_at_the_point_of_use() -> None:
    client = _client(correction_reason_first=True)
    client._settings.gemini.__dict__["correction_citations"] = (
        True  # model_copy skips the validator
    )
    with pytest.raises(ConfigError):
        AICorrector(client).mark_question(_two_points(), "a")


def test_corrector_sum_checks_first_pass_and_retry() -> None:
    both = {"p1": "awarded", "p2": "awarded"}
    out, _ = _mark(_client(correction_reason_first=True), [_reasoned(0, both, 0.95)])
    assert out.awarded_marks == 2
    # the borderline reply is checked before the two are compared: stated 0 reads as 2
    out, call = _mark(
        _client(correction_reason_first=True, correction_retry_keep_higher=True),
        [_reasoned(1, {"p1": "awarded", "p2": "withheld"}, 0.5), _reasoned(0, both, 0.95)],
    )
    assert call.call_count == 2
    assert out.awarded_marks == 2


def test_a_real_reason_first_reply_fills_stated_mark_in_the_reply_log() -> None:
    client = _client(correction_reason_first=True)
    ai = AICorrector(client)
    both = {"p1": "awarded", "p2": "awarded"}
    with patch.object(client, "generate_structured", side_effect=[_reasoned(0, both)]):
        log = ReplyLog()
        log.wrap(client)
        log.current = "case"
        out = ai.mark_question(_two_points(), "a")
    assert out.awarded_marks == 2
    assert [r.stated_mark for r in log.rows] == [0]
    assert getattr(out, "stated_mark", None) == 0
