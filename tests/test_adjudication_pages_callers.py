"""Sub-project C P4 (final review I4): every marking path hands `correct_paper` the scan's pages.

With ``gemini.adjudication_model`` set, each production caller of ``correct_paper`` that has a
scan rasterises it once and passes ``pages=``; with it unset none rasterises; a caller with no
scan makes ``correct_paper`` log ``adjudication_without_pages`` once.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import structlog
from click.testing import CliRunner

from lemely.core.loose_schemas import MarkScheme
from lemely.core.schemas import CorrectionResult, ExtractedAnswer, ExtractedAnswers
from lemely.io import adjudication as adj
from lemely.io import correction_ai

_ADJ = "claude-haiku-5-5"
_PAGES = ["page-1", "page-2"]
_SCHEME_DICT = {
    "metadata": {
        "subject": "Physics",
        "subject_code": "0625",
        "paper_number": 1,
        "paper_variant": 2,
        "session_month": "May/June",
        "session_year": 2020,
        "paper_type": "mcq",
        "maximum_mark": 2,
        "scheme_format": "mcq",
    },
    "questions": [
        {"id": "1", "marks": 1, "type": "mcq", "mcq_answer": "A"},
        {"id": "2", "marks": 1, "type": "mcq", "mcq_answer": "B"},
    ],
}
_EXTRACTED = ExtractedAnswers(
    paper_id="p",
    source_scan="s.pdf",
    answers=[ExtractedAnswer(question_id="1", answer="A", confidence=0.9)],
)


class _Stop(Exception):
    """Raised by the fake `correct_paper` once it has recorded its kwargs."""


def _client(adjudication_model: str | None) -> MagicMock:
    client = MagicMock(default_cache_mode="read_write")
    client._settings.gemini.adjudication_model = adjudication_model
    return client


class _Recorder:
    def __init__(self) -> None:
        self.kwargs: dict[str, Any] | None = None
        self.slot_free: bool | None = None

    def __call__(self, *args: object, **kwargs: Any) -> object:
        from lemely.io import run_cap

        self.kwargs = kwargs
        self.slot_free = run_cap._slots.acquire(blocking=False)
        if self.slot_free:
            run_cap._slots.release()
        raise _Stop


@pytest.fixture
def rasterise() -> Iterator[MagicMock]:
    with patch("lemely.io.rasterise.rasterise_scan_to_pages", return_value=_PAGES) as mock:
        yield mock


# --- the helper -------------------------------------------------------------


def test_helper_returns_a_lazy_source_and_renders_nothing(
    rasterise: MagicMock, tmp_path: Path
) -> None:
    source = adj.adjudication_pages(_client(_ADJ), tmp_path / "scan.pdf")  # type: ignore[arg-type]
    assert isinstance(source, adj.PageSource)
    rasterise.assert_not_called()


@pytest.mark.parametrize(
    ("model", "has_scan"),
    [(None, True), ("", True), (_ADJ, False)],
    ids=["unset", "empty", "no-scan"],
)
def test_helper_returns_none_without_model_or_scan(
    rasterise: MagicMock, tmp_path: Path, model: str | None, has_scan: bool
) -> None:
    source = adj.adjudication_pages(_client(model), tmp_path / "s.pdf" if has_scan else None)  # type: ignore[arg-type]
    assert source is None
    rasterise.assert_not_called()


def test_helper_returns_none_without_a_client(rasterise: MagicMock, tmp_path: Path) -> None:
    assert adj.adjudication_pages(None, tmp_path / "s.pdf") is None


def test_hold_takes_the_slot_around_the_render_and_releases_it(
    rasterise: MagicMock, tmp_path: Path
) -> None:
    from lemely.io import run_cap

    seen: list[bool] = []

    def _render(path: object) -> list[str]:
        free = run_cap._slots.acquire(blocking=False)
        if free:
            run_cap._slots.release()
        seen.append(free)
        return _PAGES

    rasterise.side_effect = _render
    with adj.PageSource(tmp_path / "s.pdf").hold() as pages:
        assert pages == _PAGES
    assert seen == [False]  # held while rendering
    assert run_cap._slots.acquire(blocking=False)  # and given back
    run_cap._slots.release()


def _result_with_one_confident_ai_leaf() -> CorrectionResult:
    from lemely.core.schemas import ConfidenceBand, CorrectedQuestion, ExamMetadata

    return CorrectionResult(
        metadata=ExamMetadata(
            subject_code="0625",
            paper_number=1,
            paper_variant=2,
            session_month="May/June",
            session_year=2020,
        ),
        questions=[
            CorrectedQuestion(
                question_id="1",
                awarded_marks=1,
                maximum_marks=1,
                confidence=ConfidenceBand.HIGH,
                confidence_score=0.99,
                needs_teacher_review=False,
                marker_source="ai",
            )
        ],
    )


def test_adjudicate_renders_nothing_when_there_is_nothing_to_settle(
    rasterise: MagicMock, tmp_path: Path
) -> None:
    from lemely.runtime.config import GeminiSettings

    result = _result_with_one_confident_ai_leaf()
    client = MagicMock(_settings=MagicMock(gemini=GeminiSettings(adjudication_model=_ADJ)))
    out = adj.adjudicate(
        result,
        scheme=MarkScheme.model_validate(_SCHEME_DICT),
        extracted=_EXTRACTED,
        pages=adj.PageSource(tmp_path / "s.pdf"),
        client=client,
        review_threshold=0.72,
    )
    assert out is result
    rasterise.assert_not_called()


def test_adjudicate_renders_once_when_a_leaf_needs_settling(
    rasterise: MagicMock, tmp_path: Path
) -> None:
    from lemely.runtime.config import GeminiSettings

    result = _result_with_one_confident_ai_leaf()
    result.questions[0] = result.questions[0].model_copy(update={"confidence_score": 0.1})
    client = MagicMock(_settings=MagicMock(gemini=GeminiSettings(adjudication_model=_ADJ)))
    adj.adjudicate(
        result,
        scheme=MarkScheme.model_validate(_SCHEME_DICT),
        extracted=_EXTRACTED,
        pages=adj.PageSource(tmp_path / "s.pdf"),
        client=client,
        review_threshold=0.72,
    )
    rasterise.assert_called_once()


# --- lemely/web/services/grading.py ----------------------------------------


@pytest.mark.parametrize(("model", "expected"), [(_ADJ, _PAGES), (None, None)])
def test_grade_paper_passes_pages(
    rasterise: MagicMock, tmp_path: Path, model: str | None, expected: list[str] | None
) -> None:
    from lemely.runtime.config import IntegritySettings
    from lemely.web.services.grading import grade_paper

    recorder = _Recorder()
    with patch("lemely.web.services.grading.correct_paper", recorder), pytest.raises(_Stop):
        grade_paper(
            MarkScheme.model_validate(_SCHEME_DICT),
            _EXTRACTED,
            gemini_client=_client(model),  # type: ignore[arg-type]
            integrity_settings=IntegritySettings(),
            scan_path=tmp_path / "scan.pdf",
        )
    assert recorder.kwargs is not None
    assert isinstance(recorder.kwargs["pages"], adj.PageSource) is bool(expected)
    # Marking runs without the run slot and without a render (the pages are lazy).
    assert recorder.slot_free is True
    rasterise.assert_not_called()


# --- lemely/accuracy/harness.py --------------------------------------------


@pytest.mark.parametrize(("model", "expected"), [(_ADJ, _PAGES), (None, None)])
def test_harness_passes_pages(
    rasterise: MagicMock, tmp_path: Path, model: str | None, expected: list[str] | None
) -> None:
    from lemely.accuracy.harness import DEFAULT_RENDER, GoldenAnswer, GoldenCase, measure_accuracy

    scan = tmp_path / "scan.pdf"
    case = GoldenCase(
        paper_id="p1",
        mark_scheme=MarkScheme.model_validate(_SCHEME_DICT),
        ground_truth={"1": GoldenAnswer(student_answer="A", awarded_marks=1)},
        scan_path=scan,
        renders={DEFAULT_RENDER: scan},
    )
    recorder = _Recorder()
    with patch("lemely.io.correction_ai.correct_paper", recorder), pytest.raises(_Stop):
        measure_accuracy([case], gemini_client=_client(model), settings=None, arm="oracle+mark")  # type: ignore[arg-type]
    assert recorder.kwargs is not None
    assert isinstance(recorder.kwargs["pages"], adj.PageSource) is bool(expected)


# --- lemely/app/cli.py -------------------------------------------------------


@pytest.mark.parametrize(
    ("model", "with_scan", "expected"),
    [(_ADJ, True, _PAGES), (None, True, None), (_ADJ, False, None)],
    ids=["configured", "unset", "no-scan"],
)
def test_cli_correct_paper_passes_pages(
    rasterise: MagicMock,
    tmp_path: Path,
    model: str | None,
    with_scan: bool,
    expected: list[str] | None,
) -> None:
    from lemely.app.cli import cli

    ms = tmp_path / "ms.json"
    ms.write_text(json.dumps(_SCHEME_DICT), "utf-8")
    answers = tmp_path / "answers.json"
    answers.write_text(_EXTRACTED.model_dump_json(), "utf-8")
    scan = tmp_path / "scan.pdf"
    scan.write_bytes(b"%PDF-1.4")
    recorder = _Recorder()
    args = ["correct-paper", "--mark-scheme", str(ms), "--answers", str(answers)]
    if with_scan:
        args += ["--scan", str(scan)]
    with (
        patch("lemely.io.gemini.GeminiClient", return_value=_client(model)),
        patch("lemely.io.correction_ai.correct_paper", recorder),
    ):
        result = CliRunner().invoke(
            cli, args, env={"LEMELY_PATHS__OUTPUT_DIR": str(tmp_path / "out")}
        )
    assert isinstance(result.exception, _Stop), result.output
    assert recorder.kwargs is not None
    assert isinstance(recorder.kwargs["pages"], adj.PageSource) is bool(expected)


# --- lemely/app/gradio_app.py ------------------------------------------------


@pytest.mark.parametrize(
    ("model", "with_scan", "expected"),
    [(_ADJ, True, _PAGES), (None, True, None), (_ADJ, False, None)],
    ids=["configured", "unset", "no-scan"],
)
def test_gradio_grade_passes_pages(
    rasterise: MagicMock,
    tmp_path: Path,
    model: str | None,
    with_scan: bool,
    expected: list[str] | None,
) -> None:
    from lemely.app.gradio_app import build_app
    from lemely.runtime.config import Settings

    ms = tmp_path / "ms.json"
    ms.write_text(json.dumps(_SCHEME_DICT), "utf-8")
    scan = tmp_path / "scan.pdf"
    recorder = _Recorder()
    with (
        patch("lemely.io.gemini.GeminiClient", return_value=_client(model)),
        patch("lemely.io.correction_ai.correct_paper", recorder),
    ):
        app = build_app(Settings())
        grade = next(f.fn for f in app.fns.values() if f.fn.__name__ == "_grade")
        list(
            grade(
                str(ms), [], False, _EXTRACTED.model_dump_json(), str(scan) if with_scan else None
            )
        )
    assert recorder.kwargs is not None
    assert isinstance(recorder.kwargs["pages"], adj.PageSource) is bool(expected)


# --- correct_paper: a caller with no scan (quiz marking, CLI without --scan) -------


def _mark_without_pages(model: str | None) -> list[dict[str, Any]]:
    with structlog.testing.capture_logs() as logs:
        correction_ai.correct_paper(
            MarkScheme.model_validate(_SCHEME_DICT),
            _EXTRACTED,
            gemini_client=_client(model),  # type: ignore[arg-type]
        )
    return [e for e in logs if e["event"] == "adjudication_without_pages"]


def test_missing_pages_are_logged_once_when_adjudication_is_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(correction_ai, "_adjudication_without_pages_logged", False)
    first = _mark_without_pages(_ADJ)
    second = _mark_without_pages(_ADJ)
    assert len(first) == 1 and first[0]["adjudication_model"] == _ADJ
    assert second == []


def test_missing_pages_are_not_logged_when_adjudication_is_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(correction_ai, "_adjudication_without_pages_logged", False)
    assert _mark_without_pages(None) == []


def test_a_caller_with_no_scan_by_nature_does_not_use_up_the_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Quiz marking (typed answers) passes ``expects_pages=False``: a later scan-backed
    caller that lost its pages still gets the one warning."""
    monkeypatch.setattr(correction_ai, "_adjudication_without_pages_logged", False)
    with structlog.testing.capture_logs() as logs:
        correction_ai.correct_paper(
            MarkScheme.model_validate(_SCHEME_DICT),
            _EXTRACTED,
            gemini_client=_client(_ADJ),  # type: ignore[arg-type]
            expects_pages=False,
        )
    assert [e for e in logs if e["event"] == "adjudication_without_pages"] == []
    assert len(_mark_without_pages(_ADJ)) == 1
