"""Sub-project C P4 (final review I4): every marking path hands `correct_paper` the scan's pages.

With ``gemini.adjudication_model`` set, each production caller of ``correct_paper`` that has a
scan rasterises it once and passes ``pages=``; with it unset none rasterises; a caller with no
scan makes ``correct_paper`` log ``adjudication_without_pages`` once.
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import structlog
from click.testing import CliRunner

from lemely.core.loose_schemas import MarkScheme
from lemely.core.schemas import ExtractedAnswer, ExtractedAnswers
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

    def __call__(self, *args: object, **kwargs: Any) -> object:
        self.kwargs = kwargs
        raise _Stop


@pytest.fixture
def rasterise() -> Iterator[MagicMock]:
    with patch("lemely.io.rasterise.rasterise_scan_to_pages", return_value=_PAGES) as mock:
        yield mock


# --- the helper -------------------------------------------------------------


def test_helper_rasterises_once_when_adjudication_is_configured(
    rasterise: MagicMock, tmp_path: Path
) -> None:
    scan = tmp_path / "scan.pdf"
    with adj.adjudication_pages(_client(_ADJ), scan) as pages:  # type: ignore[arg-type]
        assert pages == _PAGES
    rasterise.assert_called_once_with(scan)


@pytest.mark.parametrize(
    ("model", "has_scan"), [(None, True), (_ADJ, False)], ids=["unset", "no-scan"]
)
def test_helper_yields_none_without_model_or_scan(
    rasterise: MagicMock, tmp_path: Path, model: str | None, has_scan: bool
) -> None:
    with adj.adjudication_pages(_client(model), tmp_path / "s.pdf" if has_scan else None) as pages:  # type: ignore[arg-type]
        assert pages is None
    rasterise.assert_not_called()


def test_helper_yields_none_without_a_client(rasterise: MagicMock, tmp_path: Path) -> None:
    with adj.adjudication_pages(None, tmp_path / "s.pdf") as pages:
        assert pages is None
    rasterise.assert_not_called()


def test_helper_holds_a_marking_run_slot_while_the_pages_are_live(
    rasterise: MagicMock, tmp_path: Path
) -> None:
    events: list[str] = []

    @contextlib.contextmanager
    def _slot() -> Iterator[None]:
        events.append("enter")
        yield
        events.append("exit")

    with (
        patch("lemely.io.run_cap.marking_run_slot", _slot),
        adj.adjudication_pages(_client(_ADJ), tmp_path / "s.pdf"),  # type: ignore[arg-type]
    ):
        events.append("body")
    assert events == ["enter", "body", "exit"]


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
    assert recorder.kwargs["pages"] == expected
    assert rasterise.call_count == (1 if expected else 0)


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
    assert recorder.kwargs["pages"] == expected


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
    assert recorder.kwargs["pages"] == expected


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
    assert recorder.kwargs["pages"] == expected


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
