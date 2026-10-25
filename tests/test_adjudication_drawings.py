"""Lever H2d: drawing leaves (the reader's ``Drawing:`` description) adjudicated from crops."""

from __future__ import annotations

import tempfile
from unittest.mock import MagicMock, patch

from lemely.core.loose_schemas import MarkScheme
from lemely.core.schemas import ExtractedAnswer, ExtractedAnswers, SourceBox
from lemely.io import adjudication as adj
from lemely.io.gemini import GeminiClient
from lemely.io.prompts import correction_ai as prompts
from tests.test_adjudication import _SCHEME, _client, _cq, _result
from tests.test_anthropic_adapter import _image, _settings

_DRAW = "Drawing: two arrows pointing up"


def _drawing_cq(qid: str, conf: float = 0.95, text: str = _DRAW):  # type: ignore[no-untyped-def]
    return _cq(qid, conf).model_copy(update={"student_answer": text})


def _answers(*ids: str, source: str | None = "label") -> ExtractedAnswers:
    return ExtractedAnswers(
        paper_id="t",
        source_scan="s.png",
        answers=[
            ExtractedAnswer(
                question_id=i,
                answer="x",
                confidence=0.9,
                binding_source=source,  # type: ignore[arg-type]
                source_box=SourceBox(page=0, box=[0, 0, 500, 500]),
            )
            for i in ids
        ],
    )


def _run(client: GeminiClient, result, extracted):  # type: ignore[no-untyped-def]
    with patch.object(adj, "crop_and_upscale", return_value=_image(40, 40)):
        return adj.adjudicate(
            result,
            scheme=_SCHEME,
            extracted=extracted,
            pages=[MagicMock()],
            client=client,
            review_threshold=0.90,
        )


def test_drawing_pattern_matches_the_marker_prompt() -> None:
    assert adj._DRAWING.pattern == prompts._DRAWING_DESCRIPTION.pattern


def test_drawing_candidates_need_reader_text_and_the_word() -> None:
    result = _result(
        _drawing_cq("1a", 0.95),
        _drawing_cq("2a", 0.95),  # not a reader answer
        _cq("3a", 0.95),  # reader, no word
        _drawing_cq("4a", 0.95, text="my drawing: x"),
        _drawing_cq("5a", 0.5),
    )
    reader = frozenset({"1a", "3a", "4a", "5a"})
    assert adj.drawing_candidates(result, reader_ids=reader, max_leaves=5) == ["1a", "5a"]
    assert adj.drawing_candidates(result, reader_ids=reader, max_leaves=1) == ["1a"]
    ai_only = _result(
        _drawing_cq("1a").model_copy(update={"marker_source": "deterministic"}),
    )
    assert adj.drawing_candidates(ai_only, reader_ids=frozenset({"1a"}), max_leaves=5) == []


def test_off_by_default_no_drawing_pool() -> None:
    result = _result(_drawing_cq("1a", 0.95))
    client = MagicMock()
    client._settings = _settings(tempfile.mkdtemp(), adjudication_model="claude-haiku-5-5")
    out = adj.adjudicate(
        result,
        scheme=_SCHEME,
        extracted=_answers("1a"),
        pages=[MagicMock()],
        client=client,
        review_threshold=0.90,
    )
    client.generate_structured.assert_not_called()
    assert out is result
    # A MagicMock setting is not "on".
    client = MagicMock()
    client._settings.gemini.adjudication_model = "claude-haiku-5-5"
    client._settings.gemini.adjudication_confidence_threshold = 0.80
    client._settings.gemini.adjudication_max_leaves = 0
    client._settings.gemini.adjudication_drawing_max_leaves = 3
    out = adj.adjudicate(
        result,
        scheme=_SCHEME,
        extracted=_answers("1a"),
        pages=[MagicMock()],
        client=client,
        review_threshold=0.90,
    )
    client.generate_structured.assert_not_called()
    assert out is result


def test_on_drawings_only_with_max_leaves_zero() -> None:
    client, fake = _client(
        adjudication_max_leaves=0,
        adjudication_drawing_leaves=True,
        adjudication_drawing_max_leaves=2,
    )
    result = _result(
        _drawing_cq("1a", 0.95),
        _drawing_cq("2a", 0.9),
        _drawing_cq("3a", 0.99),
        _cq("4a", 0.5),
    )
    out = _run(client, result, _answers("1a", "2a", "3a", "4a"))
    assert len(fake.messages.calls) == 2
    assert out.questions[0].awarded_marks == 2 and out.questions[1].awarded_marks == 2
    assert out.questions[2].awarded_marks == 1 and out.questions[3].awarded_marks == 1


def test_on_pools_do_not_double_count() -> None:
    client, _ = _client(adjudication_drawing_leaves=True, adjudication_drawing_max_leaves=3)
    result = _result(_drawing_cq("1a", 0.5))
    with patch.object(
        client,
        "generate_structured",
        return_value=adj.AdjudicationReply(awarded_marks=2, confidence=0.9, rationale="r"),
    ) as mock:
        _run(client, result, _answers("1a"))
    assert mock.call_count == 1


def test_drawing_prompt_says_the_first_marker_saw_no_drawing() -> None:
    client, fake = _client(adjudication_drawing_leaves=True, adjudication_drawing_max_leaves=3)
    result = _result(_drawing_cq("1a", 0.95), _cq("2a", 0.5))
    _run(client, result, _answers("1a", "2a"))
    texts = [str(c["messages"]) for c in fake.messages.calls]
    drawn = next(t for t in texts if "Question part 1a" in t)
    plain = next(t for t in texts if "Question part 2a" in t)
    assert "never the drawing" in drawn
    assert "never the drawing" not in plain
    q = next(q for q in _SCHEME.all_questions_flat() if q.id == "2a")
    first = _cq("2a", 0.5)
    assert adj._leaf_prompt(q, first) == adj._leaf_prompt(q, first, drawing=False)
    assert "Drawing criteria" not in adj._leaf_prompt(q, first)
    assert "never the drawing" not in adj._leaf_prompt(q, first)
    assert "never the drawing" in adj._leaf_prompt(q, first, drawing=True)


def test_drawing_prompt_lists_criteria() -> None:
    scheme = MarkScheme.model_validate(
        {
            **_SCHEME.model_dump(mode="json"),
            "questions": [
                {
                    "id": "1a",
                    "marks": 2,
                    "type": "diagram",
                    "drawing_criteria": [
                        {
                            "id": "d1",
                            "criterion": "outline",
                            "requirement": "single line",
                            "marks": 1,
                        },
                        {
                            "id": "d2",
                            "criterion": "size",
                            "requirement": "fills the box",
                            "marks": 1,
                        },
                    ],
                }
            ],
        }
    )
    q = scheme.all_questions_flat()[0]
    text = adj._leaf_prompt(q, _cq("1a", 0.9), drawing=True)
    assert "Drawing criteria:\n- d1 (1 mark): single line\n- d2 (1 mark): fills the box" in text
    assert "Drawing criteria" not in adj._leaf_prompt(q, _cq("1a", 0.9))


def test_leaves_without_a_crop_do_not_take_cap_slots() -> None:
    client, _ = _client(
        adjudication_max_leaves=0,
        adjudication_drawing_leaves=True,
        adjudication_drawing_max_leaves=3,
    )
    result = _result(
        *(_drawing_cq(f"{i}a", c) for i, c in ((1, 0.5), (2, 0.6), (3, 0.7), (4, 0.95)))
    )
    answers = _answers("1a", "2a", "3a", "4a")
    for a in answers.answers[:3]:
        a.source_box = None
    answers.answers[2].source_box = SourceBox(page=7, box=[0, 0, 5, 5])  # page out of range
    with patch.object(
        client,
        "generate_structured",
        return_value=adj.AdjudicationReply(awarded_marks=2, confidence=0.9, rationale="r"),
    ) as mock:
        _run(client, result, answers)
    assert [c.kwargs["question_id"] for c in mock.call_args_list] == ["4a"]


def test_crops_are_sent_for_drawing_leaves() -> None:
    client, fake = _client(
        adjudication_max_leaves=0,
        adjudication_drawing_leaves=True,
        adjudication_drawing_max_leaves=1,
    )
    _run(client, _result(_drawing_cq("1a", 0.95)), _answers("1a"))
    (call,) = fake.messages.calls
    content = call["messages"][0]["content"]
    assert sum(1 for p in content if isinstance(p, dict) and p.get("type") == "image") == 1
