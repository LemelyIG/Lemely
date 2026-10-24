"""Sub-project C escalation cap: at most N escalations per script, most uncertain first."""

from __future__ import annotations

import tempfile
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from lemely.core.loose_schemas import MarkScheme, QuestionType
from lemely.core.schemas import AIMarkResponse, CorrectionResult
from lemely.io.correction_ai import AICorrector, correct_paper
from lemely.io.gemini import GeminiClient
from lemely.runtime.config import MarkingOptions
from lemely.runtime.errors import CostCeilingError, ExternalServiceError
from lemely.runtime.events import EventType, bus
from tests.gemini_fakes import fake_genai_client, make_settings
from tests.test_anthropic_adapter import _VALID_MARK

_HAIKU, _SONNET = "claude-haiku-5-5", "claude-sonnet-5-5"
_SCHEME = MarkScheme.model_validate(
    {
        "metadata": {
            "subject": "Physics",
            "subject_code": "0625",
            "paper_number": 4,
            "paper_variant": 1,
            "session_month": "Oct/Nov",
            "session_year": 2024,
            "paper_type": "theory_extended",
            "maximum_mark": 10,
            "scheme_format": "point_based",
        },
        "questions": [
            {
                "id": f"{i}a",
                "marks": 2,
                "type": "calculation",
                "answer_points": [
                    {"id": "M1", "point": "uses F = ma", "marks": 1},
                    {"id": "A1", "point": "6 N", "marks": 1},
                ],
            }
            for i in (1, 2)
        ],
    }
)


def _corrector(cap: int | None) -> tuple[AICorrector, GeminiClient]:
    s = make_settings(tempfile.mkdtemp())
    g = s.gemini.model_copy(
        update={
            "correction_model": _HAIKU,
            "escalation_model": _SONNET,
            "correction_borderline_enabled": False,
            "escalation_cap_per_script": cap,
        }
    )
    client = GeminiClient(
        s.model_copy(update={"gemini": g}), _genai_client=fake_genai_client(), ledger=None
    )
    return AICorrector(client), client


def _reply(conf: float, awarded: int = 2) -> AIMarkResponse:
    return AIMarkResponse.model_validate(
        {**_VALID_MARK, "confidence": conf, "awarded_marks": awarded}
    )


def test_capped_corrector_defers_instead_of_escalating() -> None:
    ai, client = _corrector(1)
    with (
        patch("lemely.io.correction_ai.build_marker_user_prompt", return_value="u"),
        patch.object(client, "generate_structured", side_effect=[_reply(0.6), _reply(0.7)]) as call,
    ):
        for qid in ("1", "2"):
            ai.mark_question(MagicMock(type=QuestionType.EXPLANATION, id=qid, marks=2), "a")
    assert [c.kwargs["task_tag"] for c in call.call_args_list] == ["correction", "correction"]
    assert sorted(ai.deferred) == ["1", "2"]


def test_escalate_deferred_takes_the_most_uncertain_first() -> None:
    ai, client = _corrector(1)
    with (
        patch("lemely.io.correction_ai.build_marker_user_prompt", return_value="u"),
        patch.object(
            client, "generate_structured", side_effect=[_reply(0.7), _reply(0.6), _reply(0.95)]
        ) as call,
    ):
        for qid in ("1", "2"):
            ai.mark_question(MagicMock(type=QuestionType.EXPLANATION, id=qid, marks=2), "a")
        escalated = ai.escalate_deferred()
    assert list(escalated) == ["2"]
    assert call.call_args_list[-1].kwargs["task_tag"] == "escalation"
    assert call.call_args_list[-1].kwargs["question_id"] == "2"


def test_no_cap_escalates_inline_as_today() -> None:
    ai, client = _corrector(None)
    with (
        patch("lemely.io.correction_ai.build_marker_user_prompt", return_value="u"),
        patch.object(
            client, "generate_structured", side_effect=[_reply(0.6), _reply(0.95)]
        ) as call,
    ):
        ai.mark_question(MagicMock(type=QuestionType.EXPLANATION, id="1", marks=2), "a")
    assert [c.kwargs["task_tag"] for c in call.call_args_list] == ["correction", "escalation"]
    assert ai.deferred == {}


def test_a_mock_settings_cap_is_not_a_cap() -> None:
    ai, client = _corrector(None)
    client._settings.gemini.escalation_cap_per_script = MagicMock()
    with (
        patch("lemely.io.correction_ai.build_marker_user_prompt", return_value="u"),
        patch.object(
            client, "generate_structured", side_effect=[_reply(0.6), _reply(0.95)]
        ) as call,
    ):
        ai.mark_question(MagicMock(type=QuestionType.EXPLANATION, id="1", marks=2), "a")
    assert call.call_count == 2
    assert ai.deferred == {}
    assert ai.escalate_deferred() == {}


def _paper(
    cap: int, replies: list[AIMarkResponse]
) -> tuple[CorrectionResult, MagicMock, list[str], list[tuple[str, float]]]:
    client = _corrector(cap)[1]
    client._settings.gemini.adjudication_model = _SONNET
    order: list[str] = []
    events: list[tuple[str, float]] = []

    def on_escalate(**payload: Any) -> None:
        events.append((payload["question_id"], payload["confidence"]))

    def adjudicate_spy(result: CorrectionResult, **_: object) -> CorrectionResult:
        order.append("adjudicate")
        return result

    bus.subscribe(EventType.GEMINI_ESCALATE, on_escalate)
    try:
        with (
            patch("lemely.io.correction_ai.build_marker_user_prompt", return_value="u"),
            patch.object(client, "generate_structured", side_effect=replies) as call,
            patch("lemely.io.adjudication.adjudicate", side_effect=adjudicate_spy),
        ):
            call.side_effect = _recording(call, replies, order)
            result = correct_paper(
                _SCHEME, {"1a": "x", "2a": "y"}, gemini_client=client, pages=[MagicMock()]
            )
    finally:
        bus.unsubscribe(EventType.GEMINI_ESCALATE, on_escalate)
    return result, call, order, events


def _recording(call: MagicMock, replies: list[AIMarkResponse], order: list[str]) -> Any:
    it = iter(replies)

    def reply(**kwargs: Any) -> AIMarkResponse:
        order.append(kwargs["task_tag"])
        return next(it)

    return reply


def test_correct_paper_escalates_only_the_most_uncertain_before_adjudication() -> None:
    result, call, order, events = _paper(1, [_reply(0.7, 1), _reply(0.6, 1), _reply(0.95, 2)])
    by_id = {q.question_id: q for q in result.questions}
    assert by_id["1a"].awarded_marks == 1
    assert by_id["2a"].awarded_marks == 2
    tags = [c.kwargs["task_tag"] for c in call.call_args_list]
    assert tags.count("escalation") == 1
    assert call.call_args_list[-1].kwargs["question_id"] == "2a"
    assert order == ["correction", "correction", "escalation", "adjudicate"]
    # 1a keeps its first pass (0.7 < 0.90 review threshold); 2a is judged on the escalated 0.95.
    assert by_id["1a"].needs_teacher_review is True
    assert by_id["2a"].needs_teacher_review is False
    assert events == [("2a", 0.6)]  # the real-split runner reads this confidence


def test_a_failed_deferred_escalation_keeps_the_first_pass_mark() -> None:
    client = _corrector(2)[1]
    replies: list[AIMarkResponse | Exception] = [
        _reply(0.7, 1),
        _reply(0.6, 1),
        ExternalServiceError("boom"),
        _reply(0.95, 2),
    ]
    with (
        patch("lemely.io.correction_ai.build_marker_user_prompt", return_value="u"),
        patch.object(client, "generate_structured", side_effect=replies),
    ):
        result = correct_paper(_SCHEME, {"1a": "x", "2a": "y"}, gemini_client=client)
    by_id = {q.question_id: q for q in result.questions}
    assert by_id["2a"].awarded_marks == 1  # its escalation failed: first-pass mark kept
    assert by_id["1a"].awarded_marks == 2  # the other leaf was still escalated


def test_a_cost_ceiling_during_deferred_escalation_still_stops_the_run() -> None:
    client = _corrector(1)[1]
    replies: list[AIMarkResponse | Exception] = [_reply(0.7), _reply(0.6), CostCeilingError("cap")]
    with (
        patch("lemely.io.correction_ai.build_marker_user_prompt", return_value="u"),
        patch.object(client, "generate_structured", side_effect=replies),
        pytest.raises(CostCeilingError),
    ):
        correct_paper(_SCHEME, {"1a": "x", "2a": "y"}, gemini_client=client)


def test_ecf_substitution_keeps_inline_escalation() -> None:
    client = _corrector(1)[1]
    replies = [_reply(0.7), _reply(0.95), _reply(0.6), _reply(0.95)]
    with (
        patch("lemely.io.correction_ai.build_marker_user_prompt", return_value="u"),
        patch.object(client, "generate_structured", side_effect=replies) as call,
    ):
        correct_paper(
            _SCHEME,
            {"1a": "x", "2a": "y"},
            gemini_client=client,
            options=MarkingOptions(ecf_substitution=True),
        )
    # Inline, each low leaf escalates as it is marked (the cap of 1 is not applied).
    tags = [c.kwargs["task_tag"] for c in call.call_args_list]
    assert tags == ["correction", "escalation", "correction", "escalation"]
