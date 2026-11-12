"""Lever H4a: leaves whose crop re-read disagreed with the first read are adjudicated first."""

from __future__ import annotations

import tempfile
from unittest.mock import MagicMock, patch

from lemely.core.schemas import ExtractedAnswer, ExtractedAnswers, SourceBox
from lemely.io import adjudication as adj
from tests.test_adjudication import _SCHEME, _client, _cq, _result
from tests.test_adjudication_drawings import _drawing_cq, _run
from tests.test_anthropic_adapter import _settings

_BOX = SourceBox(page=0, box=[0, 0, 500, 500])
_PLAIN = (
    "Question part 2a, worth 2 marks.\nMark scheme points:\n- M1 (1 mark): uses F = ma\n"
    "- A1 (1 mark): 6 N\n\nTranscribed answer: F = 6 N\n\nFirst marker: 1 of 2, confidence "
    "0.50.\nFirst marker's reasons: half right"
)
_DRAWN = (
    _PLAIN + "\n\nThis answer includes a drawing. The first marker was shown only a reader's text "
    "description of it, never the drawing, and withheld points the description did not "
    "mention. Judge every point from the page crop: award a point the drawing shows even if "
    "the description is silent about it."
)


def _ans(
    qid: str,
    agreement: float | None,
    *,
    reread: str | None = "Refraction",
    box: SourceBox | None = _BOX,
    source: str | None = None,
) -> ExtractedAnswer:
    return ExtractedAnswer(
        question_id=qid,
        answer="x",
        confidence=0.9,
        binding_source=source,
        source_box=box,
        answer_reread=reread,
        reread_agreement=agreement,
    )


def _extracted(*answers: ExtractedAnswer) -> ExtractedAnswers:
    return ExtractedAnswers(paper_id="t", source_scan="s.png", answers=list(answers))


def _by_id(extracted: ExtractedAnswers) -> dict[str, ExtractedAnswer]:
    return {a.question_id: a for a in extracted.answers}


def test_reread_candidates_need_a_low_agreement_ai_leaf_with_a_crop() -> None:
    result = _result(
        _cq("1a", 0.95),
        _cq("2a", 0.95),
        _cq("3a", 0.95),
        _cq("4a", 0.95),
        _cq("5a", 0.95, source="deterministic"),
        _cq("6a", 0.95),
        _cq("7a", 0.95),
        _cq("8a", 0.95),
        _cq("9a", 0.95),
    )
    extracted = _extracted(
        _ans("1a", 0.10),
        _ans("2a", 0.80),  # the boundary is agreement, not disagreement
        _ans("3a", None),
        _ans("4a", 0.79),
        _ans("5a", 0.0),
        _ans("6a", 0.0, box=None),
        _ans("7a", 0.0, box=SourceBox(page=7, box=[0, 0, 5, 5])),
        _ans("8a", 0.5),
        _ans("9a", 0.05),
    )
    pages = [MagicMock()]
    answers = _by_id(extracted)
    got = adj.reread_candidates(result, answers=answers, pages=pages, max_leaves=10)
    assert got == ["9a", "1a", "8a", "4a"]
    assert adj.reread_candidates(result, answers=answers, pages=pages, max_leaves=2) == [
        "9a",
        "1a",
    ]
    assert adj.reread_candidates(result, answers=answers, pages=pages, max_leaves=-1) == []


def test_off_by_default_no_reread_pool() -> None:
    result = _result(_cq("1a", 0.95))
    extracted = _extracted(_ans("1a", 0.0))
    client = MagicMock()
    client._settings = _settings(tempfile.mkdtemp(), adjudication_model="claude-haiku-5-5")
    out = adj.adjudicate(
        result,
        scheme=_SCHEME,
        extracted=extracted,
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
    client._settings.gemini.adjudication_reread_disagreed = MagicMock()
    client._settings.gemini.adjudication_reread_max_leaves = 3
    out = adj.adjudicate(
        result,
        scheme=_SCHEME,
        extracted=extracted,
        pages=[MagicMock()],
        client=client,
        review_threshold=0.90,
    )
    client.generate_structured.assert_not_called()
    assert out is result


def test_on_reread_leaves_only_with_other_pools_empty() -> None:
    client, _ = _client(
        adjudication_max_leaves=0,
        adjudication_reread_disagreed=True,
        adjudication_reread_max_leaves=2,
    )
    result = _result(_cq("1a", 0.95), _cq("2a", 0.95), _cq("3a", 0.95), _cq("4a", 0.5))
    extracted = _extracted(_ans("1a", 0.3), _ans("2a", 0.1), _ans("3a", 0.2), _ans("4a", 0.9))
    with patch.object(
        client,
        "generate_structured",
        return_value=adj.AdjudicationReply(awarded_marks=2, confidence=0.9, rationale="r"),
    ) as mock:
        out = _run(client, result, extracted)
    assert [c.kwargs["question_id"] for c in mock.call_args_list] == ["2a", "3a"]
    assert [q.awarded_marks for q in out.questions] == [1, 2, 2, 1]


def test_reread_pool_goes_first_and_is_not_double_counted() -> None:
    client, _ = _client(
        adjudication_max_leaves=0,
        adjudication_drawing_leaves=True,
        adjudication_drawing_max_leaves=1,
        adjudication_reread_disagreed=True,
        adjudication_reread_max_leaves=3,
    )
    result = _result(_drawing_cq("1a"), _drawing_cq("2a"))
    extracted = _extracted(_ans("1a", 0.1, source="label"), _ans("2a", None, source="label"))
    with patch.object(
        client,
        "generate_structured",
        return_value=adj.AdjudicationReply(awarded_marks=2, confidence=0.9, rationale="r"),
    ) as mock:
        _run(client, result, extracted)
    assert [c.kwargs["question_id"] for c in mock.call_args_list] == ["1a", "2a"]
    shared = mock.call_args_list[0].kwargs["user_prompt"]
    assert "never the drawing" in shared
    assert "Two reads of this answer disagreed" in shared
    other = mock.call_args_list[1].kwargs["user_prompt"]
    assert "never the drawing" in other
    assert "Two reads" not in other


def test_reread_prompt_quotes_the_reread_and_default_prompts_are_unchanged() -> None:
    q = next(q for q in _SCHEME.all_questions_flat() if q.id == "2a")
    first = _cq("2a", 0.5)
    quoted = adj._leaf_prompt(q, first, reread="Refraction")
    assert quoted.startswith(_PLAIN)
    assert quoted.endswith(
        "\n\nTwo reads of this answer disagreed. The transcribed answer above is the first "
        "read; a zoomed re-read of the same crop gave: 'Refraction'. Neither read is "
        "authoritative: mark what the page crop shows."
    )
    assert "nothing legible" in adj._leaf_prompt(q, first, reread="")
    assert "nothing legible" in adj._leaf_prompt(q, first, reread="  ")
    assert adj._leaf_prompt(q, first) == _PLAIN
    assert adj._leaf_prompt(q, first, drawing=True) == _DRAWN
    assert adj._leaf_prompt(q, first, drawing=True, reread=None) == _DRAWN


def test_reread_reason_survives_adjudication() -> None:
    reason = (
        "confidence 0.50 below review threshold 0.90 | extraction re-read disagreed "
        "(agreement 0.10)"
    )
    first = _cq("1a", 0.5, reason=reason)
    reply = adj.AdjudicationReply(awarded_marks=2, confidence=0.95, rationale="r")
    settled = adj._settled(first, reply, model="m", review_threshold=0.90)
    assert settled.review_reason == "extraction re-read disagreed (agreement 0.10)"
    assert settled.needs_teacher_review is True
