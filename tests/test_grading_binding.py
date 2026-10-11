"""The web grading service refuses to publish a paper the binding gate rejected.

Pure tests: reports are built directly and ``correct_paper`` is stubbed, so
nothing here needs a database or Gemini.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from lemely.core.binding import BindingCheck, BindingReport, BindingVerdict
from lemely.core.loose_schemas import MarkScheme
from lemely.core.schemas import CorrectionResult, ExamMetadata, ExtractedAnswers
from lemely.runtime.config import IntegritySettings
from lemely.web.services import grading as grading_service
from lemely.web.services.grading import (
    BINDING_HELD_MESSAGE,
    BindingHeldError,
    binding_blocks_publication,
    ensure_binding_allows_marking,
    grade_paper,
)

_SENTENCE = (
    "We could not match some answers to their questions, so this paper has not been marked. "
    "Please check every page is included and in order, then upload it again."
)


def _report(verdict: BindingVerdict) -> BindingReport:
    return BindingReport(
        binder="label",
        verdict=verdict,
        checks=[
            BindingCheck(
                id="G1",
                passed=False,
                scope="paper",
                detail="Question 3 and 4 share one answer.",
            ),
            BindingCheck(
                id="G5",
                passed=False,
                scope="question",
                question_ids=["7"],
                detail="Question 7 has no label.",
            ),
            BindingCheck(id="G2", passed=True, scope="paper", detail="Labels in order."),
        ],
    )


def _scheme() -> MarkScheme:
    return MarkScheme.model_validate(
        {
            "metadata": {
                "subject": "Physics",
                "subject_code": "0625",
                "paper_number": 1,
                "paper_variant": 2,
                "session_month": "May/June",
                "session_year": 2020,
                "paper_type": "mcq",
                "maximum_mark": 1,
                "scheme_format": "mcq",
            },
            "questions": [{"id": "1", "marks": 1, "type": "mcq", "mcq_answer": "A"}],
        }
    )


def _correction(binding: BindingReport | None) -> CorrectionResult:
    return CorrectionResult(
        metadata=ExamMetadata(
            subject_code="0625",
            paper_number=1,
            paper_variant=2,
            session_month="May/June",
            session_year=2020,
        ),
        questions=[],
        binding=binding,
    )


def _stub_marking(monkeypatch: pytest.MonkeyPatch, binding: BindingReport | None) -> None:
    monkeypatch.setattr(grading_service, "correct_paper", lambda **_k: _correction(binding))
    # Pass-through: the integrity pass is not under test and would need Gemini.
    monkeypatch.setattr(grading_service, "apply_integrity_checks", lambda c, *_a, **_k: c)


@pytest.mark.parametrize(
    ("verdict", "blocks"),
    [(None, False), ("pass", False), ("retry", True), ("hold", True)],
)
def test_binding_blocks_publication_table(verdict: BindingVerdict | None, blocks: bool) -> None:
    report = None if verdict is None else _report(verdict)

    assert binding_blocks_publication(report) is blocks


def test_grade_paper_raises_binding_held_on_hold_verdict(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_marking(monkeypatch, _report("hold"))

    with pytest.raises(BindingHeldError) as held:
        grade_paper(_scheme(), {}, integrity_settings=IntegritySettings())

    assert held.value.verdict == "hold"
    assert held.value.stage == "after_marking"


def test_grade_paper_raises_binding_held_on_retry_verdict_after_marking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """There is no retry left once marking is done, so ``retry`` is treated as ``hold``."""
    _stub_marking(monkeypatch, _report("retry"))

    with pytest.raises(BindingHeldError):
        grade_paper(_scheme(), {}, integrity_settings=IntegritySettings())


def test_grade_paper_records_no_history_when_held(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_marking(monkeypatch, _report("hold"))
    history = MagicMock()

    with pytest.raises(BindingHeldError):
        grade_paper(
            _scheme(),
            {},
            student_id="maya",
            history_store=history,
            integrity_settings=IntegritySettings(),
        )

    history.append.assert_not_called()


def test_grade_paper_with_pass_or_no_report_is_not_held(monkeypatch: pytest.MonkeyPatch) -> None:
    for binding in (None, _report("pass")):
        _stub_marking(monkeypatch, binding)
        monkeypatch.setattr(grading_service, "fill_correction_topics", lambda *_a: None)
        monkeypatch.setattr(
            grading_service,
            "GradeBoundaryStore",
            lambda: MagicMock(resolve=MagicMock(return_value=({}, "none"))),
        )
        monkeypatch.setattr(grading_service, "summarize_weaknesses", lambda _c: MagicMock())
        monkeypatch.setattr(grading_service, "predict_grade", lambda *_a, **_k: MagicMock())
        monkeypatch.setattr(grading_service, "AccuracyReport", lambda **_k: "report")

        assert grade_paper(_scheme(), {}, integrity_settings=IntegritySettings()) == "report"


def test_binding_held_error_message_is_the_fixed_sentence_and_reasons_stay_off_it() -> None:
    error = BindingHeldError(_report("hold"), "before_marking")

    assert BINDING_HELD_MESSAGE == _SENTENCE
    assert str(error) == _SENTENCE
    # Only failed paper-scope checks: not the passed one, not the question-scope one.
    assert error.reasons == ["Question 3 and 4 share one answer."]
    assert error.failed_check_ids == ["G1", "G5"]
    assert "Question" not in str(error)


def test_ensure_binding_allows_marking_stops_a_rejected_extraction() -> None:
    def _extracted(binding: BindingReport | None) -> ExtractedAnswers:
        return ExtractedAnswers(paper_id="p", source_scan="s.pdf", answers=[], binding=binding)

    ensure_binding_allows_marking(_extracted(None))
    ensure_binding_allows_marking(_extracted(_report("pass")))
    for verdict in ("retry", "hold"):
        with pytest.raises(BindingHeldError) as held:
            ensure_binding_allows_marking(_extracted(_report(verdict)))  # type: ignore[arg-type]
        assert held.value.stage == "before_marking"


def test_the_teacher_sentence_offers_a_re_run_and_the_student_sentence_is_unchanged() -> None:
    from lemely.web.services.grading import TEACHER_BINDING_HELD_MESSAGE

    assert str(BindingHeldError(_report("hold"), "before_marking")) == _SENTENCE
    assert "run it again" in TEACHER_BINDING_HELD_MESSAGE
    assert TEACHER_BINDING_HELD_MESSAGE.startswith(_SENTENCE.split(" Please")[0])
