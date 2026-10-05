"""The scheme-parse worker target and its caller (#260, final review R3, I3)."""

from __future__ import annotations

import pickle
from pathlib import Path

import pytest

from lemely.core.loose_schemas import MarkScheme
from lemely.io.scheme_parse import (
    SCHEME_PARSE_TARGET,
    SCHEME_READ_FAILED_MESSAGE,
    SchemeReadFailedError,
    WorkerSchemeParser,
    parse_scheme_in_worker,
    parse_scheme_pdf,
)
from lemely.runtime import sandbox
from lemely.runtime.config import DetParserSettings
from lemely.runtime.errors import LemelyError, ParseError
from tests.fakes_scheme_pdfs import synthetic_theory_scheme_pdf
from tests.sandbox_fixtures import in_process_sandbox, sandboxed  # noqa: F401


@pytest.fixture
def _forget_last_outcome(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear the extraction worker's ``last_outcome``, which outlives a worker
    shutdown, so an assertion on it reads this test's call and no earlier one."""
    monkeypatch.setattr(sandbox.EXTRACTION_WORKER, "last_outcome", None)


def test_the_target_name_resolves_to_the_target() -> None:
    """The dotted name the worker imports in its child is this function, and
    it passes the worker's ``lemely``-only rule."""
    assert sandbox._resolve(SCHEME_PARSE_TARGET) is parse_scheme_pdf


def test_what_crosses_the_pipe_pickles() -> None:
    """The arguments and the result cross a pipe both ways."""
    cfg = DetParserSettings(mark_reconcile_tolerance=2)
    assert pickle.loads(pickle.dumps(cfg)) == cfg  # noqa: S301 -- our own objects
    scheme = parse_scheme_pdf(synthetic_theory_scheme_pdf(), "0625_s23_ms_41.pdf", cfg)
    assert pickle.loads(pickle.dumps(scheme)) == scheme  # noqa: S301


def test_parse_scheme_pdf_reads_the_paper_from_the_basename_only() -> None:
    """The client's name is the parser's source of the paper's identity and
    of ``source_document``, but never a path."""
    scheme = parse_scheme_pdf(
        synthetic_theory_scheme_pdf(questions=2, parts=2),
        "../../etc/0625_s23_ms_41.pdf",
        DetParserSettings(),
    )
    assert scheme.metadata.source_document == "0625_s23_ms_41.pdf"
    assert (scheme.metadata.subject_code, scheme.metadata.paper_number) == ("0625", 4)
    assert scheme.metadata.maximum_mark == 8


@pytest.mark.parametrize("filename", ["", ".", ".."])
def test_parse_scheme_pdf_names_a_nameless_upload_scheme_pdf(filename: str) -> None:
    scheme = parse_scheme_pdf(synthetic_theory_scheme_pdf(), filename, DetParserSettings())
    assert scheme.metadata.source_document == "scheme.pdf"


def test_parse_scheme_pdf_raises_the_parsers_refusal() -> None:
    with pytest.raises(ParseError, match="Cannot extract maximum_mark"):
        parse_scheme_pdf(
            synthetic_theory_scheme_pdf(maximum_mark_on_cover=False),
            "0625_s23_ms_41.pdf",
            DetParserSettings(),
        )


def test_the_read_failure_has_fixed_text_and_pickles() -> None:
    """Its text is what a user is shown; it crosses a pipe like any
    ``LemelyError``, rebuilt from its ``args``."""
    error = SchemeReadFailedError()
    assert isinstance(error, LemelyError)
    assert str(error) == SCHEME_READ_FAILED_MESSAGE == "Could not read this mark scheme"
    assert str(pickle.loads(pickle.dumps(error))) == SCHEME_READ_FAILED_MESSAGE  # noqa: S301


@pytest.mark.usefixtures("sandboxed", "_forget_last_outcome")
def test_parse_scheme_in_worker_parses_in_the_extraction_worker() -> None:
    scheme = parse_scheme_in_worker(
        synthetic_theory_scheme_pdf(), "0625_s23_ms_41.pdf", DetParserSettings(), timeout=30
    )
    assert isinstance(scheme, MarkScheme)
    assert scheme.metadata.maximum_mark == 18
    assert sandbox.EXTRACTION_WORKER.last_outcome == "ok"
    assert sandbox.INTERACTIVE_WORKER.pid() is None


@pytest.mark.usefixtures("sandboxed", "_forget_last_outcome")
def test_parse_scheme_in_worker_raises_the_parsers_refusal_intact() -> None:
    with pytest.raises(ParseError, match="Cannot extract maximum_mark"):
        parse_scheme_in_worker(
            synthetic_theory_scheme_pdf(maximum_mark_on_cover=False),
            "0625_s23_ms_41.pdf",
            DetParserSettings(),
            timeout=30,
        )
    assert sandbox.EXTRACTION_WORKER.last_outcome == "rejected"


@pytest.mark.usefixtures("sandboxed", "_forget_last_outcome")
def test_worker_scheme_parser_parses_a_file_under_its_own_name(tmp_path: Path) -> None:
    path = tmp_path / "0625_s23_ms_41.pdf"
    path.write_bytes(synthetic_theory_scheme_pdf())
    scheme = WorkerSchemeParser(DetParserSettings())(path)
    assert scheme.metadata.source_document == "0625_s23_ms_41.pdf"
    assert sandbox.EXTRACTION_WORKER.last_outcome == "ok"


@pytest.mark.usefixtures("in_process_sandbox")
def test_worker_scheme_parser_lets_an_in_process_parse_error_through(tmp_path: Path) -> None:
    """Only a worker failure becomes the fixed error: the parser's refusal
    stays a ``ParseError``, for the chain's Gemini fallback."""
    path = tmp_path / "mark_scheme.pdf"
    path.write_bytes(synthetic_theory_scheme_pdf(maximum_mark_on_cover=False))
    with pytest.raises(ParseError):
        WorkerSchemeParser(DetParserSettings())(path)
