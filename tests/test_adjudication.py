"""Sub-project C lever c2: leaf-scoped adjudication (request shape, cap, cost scope, off path)."""

from __future__ import annotations

import tempfile
from unittest.mock import MagicMock, patch

from lemely.core.binding import BindingCheck, BindingReport
from lemely.core.loose_schemas import MarkScheme
from lemely.core.schemas import CorrectedQuestion, CorrectionResult, ExamMetadata
from lemely.io import adjudication as adj
from lemely.io.gemini import GeminiClient, _reset_process_counters, record_calls, script_cost_scope
from lemely.io.model_table import configured_models
from tests.test_anthropic_adapter import _FakeAnthropic, _image, _message, _settings

_SONNET = "claude-sonnet-5-5"
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
            for i in range(1, 6)
        ],
    }
)


def _cq(
    qid: str, conf: float, *, source: str = "ai", reason: str | None = None
) -> CorrectedQuestion:
    return CorrectedQuestion(
        question_id=qid,
        awarded_marks=1,
        maximum_marks=2,
        confidence="medium",
        confidence_score=conf,
        needs_teacher_review=reason is not None,
        marker_source=source,
        review_reason=reason,
        feedback="half right",
        student_answer="F = 6 N",
    )


def _result(*qs: CorrectedQuestion, g9: list[str] | None = None) -> CorrectionResult:
    meta = ExamMetadata(
        subject_code="0625",
        paper_number=4,
        paper_variant=1,
        session_month="Oct/Nov",
        session_year=2024,
    )
    binding = None
    if g9 is not None:
        binding = BindingReport(
            binder="label",
            verdict="pass",
            checks=[
                BindingCheck(id="G9", passed=False, scope="question", question_ids=g9, detail="d")
            ],
        )
    return CorrectionResult(metadata=meta, questions=list(qs), binding=binding)


def _extracted() -> MagicMock:
    answers = [
        MagicMock(question_id=f"{i}a", source_box=MagicMock(page=0, box=[0, 0, 500, 500]))
        for i in range(1, 6)
    ]
    return MagicMock(answers=answers)


def test_candidates_are_low_confidence_or_g9_most_uncertain_first_capped() -> None:
    result = _result(
        _cq("1a", 0.95),
        _cq("2a", 0.6),
        _cq("3a", 0.75),
        _cq("4a", 0.79),
        _cq("5a", 0.5, source="deterministic"),
        g9=["1a"],
    )
    assert adj.candidates(result, threshold=0.80, max_leaves=3) == ["2a", "3a", "4a"]
    assert adj.candidates(result, threshold=0.80, max_leaves=4) == ["2a", "3a", "4a", "1a"]


def _client(**gemini: object) -> tuple[GeminiClient, _FakeAnthropic]:
    settings = _settings(tempfile.mkdtemp(), adjudication_model=_SONNET, **gemini)
    replies = [
        _message({"awarded_marks": 2, "confidence": 0.95, "rationale": "both points"})
        for _ in range(5)
    ]
    fake = _FakeAnthropic(*replies)
    client = GeminiClient(settings, _genai_client=object(), _anthropic_client=fake, ledger=None)
    return client, fake


def test_adjudication_request_shape_and_new_mark() -> None:
    client, fake = _client()
    result = _result(
        _cq("1a", 0.6, reason="confidence 0.60 below review threshold 0.90"), _cq("2a", 0.95)
    )
    with patch.object(adj, "crop_and_upscale", return_value=_image(40, 40)):
        out = adj.adjudicate(
            result,
            scheme=_SCHEME,
            extracted=_extracted(),
            pages=[MagicMock()],
            client=client,
            review_threshold=0.90,
        )
    (call,) = fake.messages.calls
    assert call["model"] == _SONNET
    text = str(call["messages"])
    assert "uses F = ma" in text and "1 of 2" in text and "half right" in text
    q1 = out.questions[0]
    assert q1.awarded_marks == 2 and q1.confidence_score == 0.95
    assert q1.needs_teacher_review is False and q1.review_reason is None
    assert out.awarded_marks == 3  # totals recomputed


def test_cap_of_three_leaves_per_script() -> None:
    client, fake = _client()
    result = _result(*(_cq(f"{i}a", 0.5) for i in range(1, 6)))
    with patch.object(adj, "crop_and_upscale", return_value=_image(40, 40)):
        adj.adjudicate(
            result,
            scheme=_SCHEME,
            extracted=_extracted(),
            pages=[MagicMock()],
            client=client,
            review_threshold=0.90,
        )
    assert len(fake.messages.calls) == 3


def test_adjudication_cost_lands_in_the_script_scope() -> None:
    client, _ = _client()
    _reset_process_counters()
    with (
        record_calls(),
        script_cost_scope(client._settings, script_key="k") as costs,
        patch.object(adj, "crop_and_upscale", return_value=_image(40, 40)),
    ):
        adj.adjudicate(
            _result(_cq("1a", 0.5)),
            scheme=_SCHEME,
            extracted=_extracted(),
            pages=[MagicMock()],
            client=client,
            review_threshold=0.90,
        )
    assert costs.get("adjudication", 0.0) > 0


def test_off_by_default_and_on_gemini_settings() -> None:
    client = MagicMock()
    client._settings = _settings(tempfile.mkdtemp())
    out = adj.adjudicate(
        _result(_cq("1a", 0.5)),
        scheme=_SCHEME,
        extracted=_extracted(),
        pages=[MagicMock()],
        client=client,
        review_threshold=0.90,
    )
    client.generate_structured.assert_not_called()
    assert out.questions[0].awarded_marks == 1
    assert "adjudication" not in configured_models(client._settings)


def test_a_leaf_without_a_crop_is_skipped() -> None:
    client, fake = _client()
    extracted = MagicMock(answers=[MagicMock(question_id="1a", source_box=None)])
    adj.adjudicate(
        _result(_cq("1a", 0.5)),
        scheme=_SCHEME,
        extracted=extracted,
        pages=[MagicMock()],
        client=client,
        review_threshold=0.90,
    )
    assert fake.messages.calls == []


def test_structural_review_reasons_survive() -> None:
    client, _ = _client()
    reason = "binding unverified | confidence 0.50 below review threshold 0.90"
    with patch.object(adj, "crop_and_upscale", return_value=_image(40, 40)):
        out = adj.adjudicate(
            _result(_cq("1a", 0.5, reason=reason)),
            scheme=_SCHEME,
            extracted=_extracted(),
            pages=[MagicMock()],
            client=client,
            review_threshold=0.90,
        )
    assert out.questions[0].needs_teacher_review is True
    assert out.questions[0].review_reason == "binding unverified"


def test_model_table_lists_adjudication_when_set() -> None:
    client, _ = _client()
    assert configured_models(client._settings)["adjudication"] == _SONNET


def _mcq_run(
    *, pages: object, model: object, held: bool = False
) -> tuple[MagicMock, CorrectionResult]:
    """Run correct_paper (mcq_only) with adjudicate patched; return the mock and the result."""
    from lemely.core.schemas import ExtractedAnswer, ExtractedAnswers
    from lemely.io import correction_ai
    from tests.test_correction_ai import _hybrid_paper_mark_scheme

    client = MagicMock()
    client._settings.gemini.adjudication_model = model
    extracted = ExtractedAnswers(
        paper_id="t",
        source_scan="s.png",
        answers=[ExtractedAnswer(question_id="1", answer="A", confidence=0.99)],
    )
    sentinel = _result(_cq("1a", 0.5))
    with patch("lemely.io.adjudication.adjudicate", return_value=sentinel) as mock:
        if held:
            held_result = _result(_cq("1a", 0.5))
            held_result.binding = BindingReport(binder="label", verdict="hold", checks=[])
            with patch.object(correction_ai, "_with_off_topic_check", return_value=held_result):
                out = correction_ai.correct_paper(
                    _hybrid_paper_mark_scheme(),
                    extracted,
                    gemini_client=client,
                    mcq_only=True,
                    pages=pages,  # type: ignore[arg-type]
                )
        else:
            out = correction_ai.correct_paper(
                _hybrid_paper_mark_scheme(),
                extracted,
                gemini_client=client,
                mcq_only=True,
                pages=pages,  # type: ignore[arg-type]
            )
    return mock, out


def test_correct_paper_without_pages_never_adjudicates() -> None:
    mock, _ = _mcq_run(pages=None, model=_SONNET)
    mock.assert_not_called()


def test_correct_paper_without_a_model_never_adjudicates() -> None:
    mock, _ = _mcq_run(pages=[MagicMock()], model=None)
    mock.assert_not_called()


def test_correct_paper_adjudicates_last_and_its_mark_is_final() -> None:
    mock, out = _mcq_run(pages=[MagicMock()], model=_SONNET)
    mock.assert_called_once()
    assert out.questions[0].question_id == "1a"  # the adjudicated result is what is returned


def test_a_held_paper_is_not_adjudicated() -> None:
    mock, _ = _mcq_run(pages=[MagicMock()], model=_SONNET, held=True)
    mock.assert_not_called()


def test_none_confidence_style_rows_are_never_candidates() -> None:
    result = _result(
        _cq("1a", 0.0, source="dropped"),
        _cq("2a", 0.0, source="blank"),
        _cq("3a", 0.0, source="missing"),
        _cq("4a", 0.5),
    )
    assert adj.candidates(result, threshold=0.80, max_leaves=3) == ["4a"]


def test_a_magicmock_settings_object_is_off() -> None:
    client = MagicMock()  # every attribute a MagicMock: model is not a str
    out = adj.adjudicate(
        _result(_cq("1a", 0.5)),
        scheme=_SCHEME,
        extracted=_extracted(),
        pages=[MagicMock()],
        client=client,
        review_threshold=0.90,
    )
    client.generate_structured.assert_not_called()
    assert out.questions[0].awarded_marks == 1
