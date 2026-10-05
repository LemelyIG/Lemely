"""The scheme-parse worker target and its caller (#260, final review R3, I3)."""

from __future__ import annotations

import pickle
import threading
import time
from pathlib import Path

import pytest
from structlog.testing import capture_logs

from lemely.core.loose_schemas import MarkScheme
from lemely.io import scheme_parse
from lemely.io.scheme_parse import (
    SCHEME_PARSE_TARGET,
    SCHEME_READ_FAILED_MESSAGE,
    SchemeReadFailedError,
    WorkerSchemeParser,
    parse_scheme_in_worker,
    parse_scheme_pdf,
)
from lemely.runtime import sandbox
from lemely.runtime.config import DetParserSettings, SandboxSettings
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


def _only_the_scheme_timeout_is_short() -> SandboxSettings:
    """A slow scheme parse (3 s) is far inside every other timeout (180 s) and
    far outside the scheme one (0.5 s), so only the scheme setting can cut it."""
    return SandboxSettings(
        enabled=True,
        scheme_parse_timeout_seconds=0.5,
        extraction_timeout_seconds=180,
        upload_check_timeout_seconds=180,
    )


@pytest.mark.usefixtures("sandboxed", "_forget_last_outcome")
def test_worker_scheme_parser_cuts_the_parse_at_the_scheme_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The scheme attached to a scan, on the grading path, is cut at
    ``scheme_parse_timeout_seconds`` and not held for the extraction worker's
    180 s: a small PDF that takes pdfplumber minutes would otherwise stall
    every scan check and render on the instance."""
    monkeypatch.setattr(sandbox, "sandbox_settings", _only_the_scheme_timeout_is_short)
    monkeypatch.setattr(
        scheme_parse, "SCHEME_PARSE_TARGET", "tests.sandbox_targets.slow_scheme_parse"
    )
    path = tmp_path / "0625_s23_ms_41.pdf"
    path.write_bytes(synthetic_theory_scheme_pdf())

    started = time.monotonic()
    with pytest.raises(SchemeReadFailedError) as failure:
        WorkerSchemeParser(DetParserSettings())(path)

    assert time.monotonic() - started < 2.5, "the parse ran to its own end"
    assert str(failure.value) == SCHEME_READ_FAILED_MESSAGE
    assert isinstance(failure.value.__cause__, sandbox.SandboxTimeout)
    assert sandbox.EXTRACTION_WORKER.last_outcome == "timeout"


def _busy_settings(*, scheme: float, extraction: float) -> SandboxSettings:
    return SandboxSettings(
        enabled=True,
        scheme_parse_timeout_seconds=scheme,
        extraction_timeout_seconds=extraction,
        upload_check_timeout_seconds=180,
    )


def _hold_the_extraction_worker(seconds: float) -> threading.Thread:
    """Take the extraction worker's lock, as a scan render does, for ``seconds``."""
    held = threading.Event()

    def hold() -> None:
        with sandbox.EXTRACTION_WORKER._lock:
            held.set()
            time.sleep(seconds)

    holder = threading.Thread(target=hold)
    holder.start()
    assert held.wait(5)
    return holder


def _parse_a_scheme_while_the_worker_is_held(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, scheme: float, hold: float
) -> MarkScheme:
    """Parse a scheme with a ``scheme`` s parse timeout while a scan render has
    the extraction worker for ``hold`` s (the retry deadline is 30 s)."""
    path = tmp_path / "0625_s23_ms_41.pdf"
    path.write_bytes(synthetic_theory_scheme_pdf())
    # A warm child, so the parse itself takes a fraction of the time it is given.
    parse_scheme_in_worker(path.read_bytes(), path.name, DetParserSettings(), timeout=30)
    monkeypatch.setattr(
        sandbox, "sandbox_settings", lambda: _busy_settings(scheme=scheme, extraction=30)
    )
    holder = _hold_the_extraction_worker(hold)
    try:
        return WorkerSchemeParser(DetParserSettings())(path)
    finally:
        holder.join(timeout=10)


@pytest.mark.usefixtures("sandboxed", "_forget_last_outcome")
def test_worker_scheme_parser_waits_out_a_worker_busy_with_a_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A scan render holds the worker for longer than the scheme parse's own
    timeout (here 2 s against 1 s, and far inside the 30 s the wait is given):
    the parse waits for the worker and succeeds, instead of failing the paper
    as busy."""
    scheme = _parse_a_scheme_while_the_worker_is_held(tmp_path, monkeypatch, scheme=1.0, hold=2.0)
    assert scheme.metadata.source_document == "0625_s23_ms_41.pdf"
    assert sandbox.EXTRACTION_WORKER.last_outcome == "ok"


@pytest.mark.usefixtures("sandboxed", "_forget_last_outcome")
def test_worker_scheme_parser_parses_when_the_worker_is_freed_just_before_its_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A lock wait that ends 0.03 s inside the parse timeout leaves a counted
    wait 0.03 s to parse in, and the parse is cut at that and not retried (the
    reviewer's repro: 2.0 s timeout, lock held 1.97 s). The parse's timeout runs
    from when it has the worker, so it still gets all of it."""
    scheme = _parse_a_scheme_while_the_worker_is_held(tmp_path, monkeypatch, scheme=1.0, hold=0.97)
    assert scheme.metadata.maximum_mark == 18
    assert sandbox.EXTRACTION_WORKER.last_outcome == "ok"


@pytest.mark.usefixtures("sandboxed", "_forget_last_outcome")
def test_worker_scheme_parser_fails_once_the_worker_stays_busy_past_the_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A worker busy for longer than ``extraction_timeout_seconds`` (here 1 s)
    fails the paper with the fixed text, logged as the route logs a busy worker
    (reason ``unavailable``, error ``busy``)."""
    monkeypatch.setattr(
        sandbox, "sandbox_settings", lambda: _busy_settings(scheme=0.2, extraction=1.0)
    )
    path = tmp_path / "0625_s23_ms_41.pdf"
    path.write_bytes(synthetic_theory_scheme_pdf())

    holder = _hold_the_extraction_worker(4.0)
    started = time.monotonic()
    try:
        with capture_logs() as logs, pytest.raises(SchemeReadFailedError) as failure:
            WorkerSchemeParser(DetParserSettings())(path)
        waited = time.monotonic() - started
    finally:
        holder.join(timeout=10)

    assert 1.0 <= waited < 2.5, "it gave up before the deadline, or kept asking after it"
    assert str(failure.value) == SCHEME_READ_FAILED_MESSAGE
    assert isinstance(failure.value.__cause__, sandbox.SandboxBusy)
    assert sandbox.EXTRACTION_WORKER.last_outcome == "busy"
    failed = [entry for entry in logs if entry["event"] == "scheme_parse_failed"]
    assert [(entry["reason"], entry["error"]) for entry in failed] == [("unavailable", "busy")]


@pytest.mark.usefixtures("sandboxed", "_forget_last_outcome")
def test_worker_scheme_parser_does_not_retry_a_parse_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only busy is asked again. A parse the worker cut at its timeout fails
    once, at about that timeout, though the retry deadline (180 s) is far off."""
    monkeypatch.setattr(
        sandbox, "sandbox_settings", lambda: _busy_settings(scheme=0.5, extraction=180)
    )
    monkeypatch.setattr(
        scheme_parse, "SCHEME_PARSE_TARGET", "tests.sandbox_targets.slow_scheme_parse"
    )
    calls: list[float] = []
    real = scheme_parse.parse_scheme_in_worker

    def counting(*args: object, **kwargs: float) -> MarkScheme:
        calls.append(kwargs["timeout"])
        return real(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(scheme_parse, "parse_scheme_in_worker", counting)
    path = tmp_path / "0625_s23_ms_41.pdf"
    path.write_bytes(synthetic_theory_scheme_pdf())

    started = time.monotonic()
    with pytest.raises(SchemeReadFailedError) as failure:
        WorkerSchemeParser(DetParserSettings())(path)

    assert time.monotonic() - started < 2.5
    assert calls == [0.5]
    assert isinstance(failure.value.__cause__, sandbox.SandboxTimeout)


def test_the_scheme_parse_timeout_defaults_to_20_seconds() -> None:
    assert SandboxSettings().scheme_parse_timeout_seconds == 20.0


@pytest.mark.usefixtures("in_process_sandbox")
def test_worker_scheme_parser_lets_an_in_process_parse_error_through(tmp_path: Path) -> None:
    """Only a worker failure becomes the fixed error: the parser's refusal
    stays a ``ParseError``, for the chain's Gemini fallback."""
    path = tmp_path / "mark_scheme.pdf"
    path.write_bytes(synthetic_theory_scheme_pdf(maximum_mark_on_cover=False))
    with pytest.raises(ParseError):
        WorkerSchemeParser(DetParserSettings())(path)
