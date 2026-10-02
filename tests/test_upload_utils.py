"""Unit tests for lemely.web.upload_utils: the shared upload checks and their log line."""

from __future__ import annotations

import contextlib
import os
import sys
import threading
import time

import pytest
import structlog.testing
from fastapi import HTTPException

from lemely.io.scan_limits import ScanTooLargeError, check_scan_bytes
from lemely.runtime import sandbox
from lemely.runtime.config import SandboxSettings
from lemely.runtime.sandbox import (
    SandboxCrash,
    SandboxError,
    SandboxFailure,
    SandboxMemory,
    SandboxTimeout,
    SandboxUnavailable,
)
from lemely.web.upload_utils import (
    SANDBOX_FAILED_DETAIL,
    SANDBOX_UNAVAILABLE_DETAIL,
    check_scan_geometry,
    sandbox_failure_to_http,
)
from tests.fakes_worker_bombs import catalog_metadata_bomb_pdf, peak_rss_bytes, reset_peak_rss
from tests.pdf_fakes import born_digital_text_pdf, page_bomb_pdf
from tests.sandbox_fixtures import in_process_sandbox, sandboxed  # noqa: F401

_MB = 1_000_000


@pytest.mark.usefixtures("in_process_sandbox")
def test_a_refused_scan_is_logged_with_its_class_and_reason() -> None:
    """#276: the class alone (``ScanTooLargeError``) says little, since one class
    covers a dozen rules; the reason names which one refused the upload."""
    bomb = page_bomb_pdf(112_000_000)
    with structlog.testing.capture_logs() as logs, pytest.raises(HTTPException) as caught:
        check_scan_geometry(bomb, "application/pdf")
    assert caught.value.status_code == 422
    assert logs == [
        {
            "event": "upload_refused",
            "log_level": "warning",
            "refusal": "ScanTooLargeError",
            "reason": "page_content",
            "byte_size": len(bomb),
            "content_type": "application/pdf",
        }
    ]


@pytest.mark.parametrize(
    ("failure", "status", "detail"),
    [
        pytest.param(
            SandboxUnavailable("busy", "unavailable"),
            503,
            "Scan rendering is temporarily unavailable. Try again in a moment.",
            id="unavailable",
        ),
        pytest.param(
            SandboxTimeout("no answer within 10 s", "timeout"),
            422,
            "Could not render this scan",
            id="timeout",
        ),
        pytest.param(
            SandboxMemory("ran out of memory", "memory"),
            422,
            "Could not render this scan",
            id="memory",
        ),
        pytest.param(
            SandboxCrash("exited", "crash"), 422, "Could not render this scan", id="crash"
        ),
        pytest.param(
            SandboxError("RuntimeError('boom')", "error"),
            422,
            "Could not render this scan",
            id="error",
        ),
    ],
)
def test_each_sandbox_failure_maps_to_its_status_and_is_logged(
    failure: SandboxFailure, status: int, detail: str
) -> None:
    """#260: only a worker that could not take the call is the server's
    problem (503, try again); every other failure is a 422 with a fixed
    message. Either way the reason and the failure's own text go to the log
    line, with the caller's fields, and never to the client."""
    with structlog.testing.capture_logs() as logs:
        exc = sandbox_failure_to_http(failure, event="render_failed", paper_id="p1")
    assert (exc.status_code, exc.detail) == (status, detail)
    assert logs == [
        {
            "event": "render_failed",
            "log_level": "warning",
            "reason": failure.reason,
            "error": str(failure),
            "paper_id": "p1",
        }
    ]


@pytest.mark.usefixtures("sandboxed")
def test_the_upload_check_runs_in_the_extraction_worker() -> None:
    """#260: the upload check opens the user's bytes with pdfium and MuPDF,
    so it runs in the extraction worker's bounded child, never in the web
    process."""
    check_scan_geometry(born_digital_text_pdf(pages=1), "application/pdf")
    assert sandbox.EXTRACTION_WORKER.last_outcome == "ok"
    child = sandbox.EXTRACTION_WORKER.pid()
    assert child is not None
    assert child != os.getpid()


@pytest.mark.usefixtures("sandboxed")
def test_a_refusal_in_the_worker_is_the_same_422_as_in_process() -> None:
    """A refusal crosses the pipe intact: the client sees the very message
    the check gives in-process, and the log line keeps its class and reason."""
    bomb = page_bomb_pdf(112_000_000)
    with pytest.raises(ScanTooLargeError) as direct:
        check_scan_bytes(bomb)
    with structlog.testing.capture_logs() as logs, pytest.raises(HTTPException) as caught:
        check_scan_geometry(bomb, "application/pdf")
    assert (caught.value.status_code, caught.value.detail) == (422, str(direct.value))
    assert sandbox.EXTRACTION_WORKER.last_outcome == "rejected"
    assert logs == [
        {
            "event": "upload_refused",
            "log_level": "warning",
            "refusal": "ScanTooLargeError",
            "reason": "page_content",
            "byte_size": len(bomb),
            "content_type": "application/pdf",
        }
    ]


@pytest.mark.usefixtures("sandboxed")
def test_an_unavailable_worker_is_a_503_at_upload(monkeypatch: pytest.MonkeyPatch) -> None:
    """No child could start: the server's problem, so 503 and try again."""
    monkeypatch.setattr(sandbox.EXTRACTION_WORKER, "_spawn", lambda: False)
    with structlog.testing.capture_logs() as logs, pytest.raises(HTTPException) as caught:
        check_scan_geometry(born_digital_text_pdf(pages=1), "application/pdf")
    assert (caught.value.status_code, caught.value.detail) == (503, SANDBOX_UNAVAILABLE_DETAIL)
    assert [(log["event"], log["reason"]) for log in logs] == [
        ("upload_check_failed", "unavailable")
    ]


@pytest.mark.usefixtures("sandboxed")
def test_an_upload_check_behind_a_running_extraction_is_a_503_within_its_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#260 finding 5, end to end: an extraction stream holds the worker on a
    sleeper; the upload check's wait for it counts against the check's own
    timeout, so the upload is refused 503 when the timeout runs out instead
    of queueing behind the extraction. The extraction is not disturbed."""
    worker = sandbox.EXTRACTION_WORKER
    primed = threading.Event()
    extracted: list[int] = []
    failures: list[BaseException] = []

    def extract() -> None:
        stream = worker.stream(
            "tests.sandbox_targets.slow_count", 3, 1.0, timeout=30, item_type=int
        )
        try:
            with contextlib.closing(stream):
                # Priming takes the lock (and starts the child); the rest of
                # the stream then holds it for about two seconds.
                extracted.append(next(stream))
                primed.set()
                extracted.extend(stream)
        except BaseException as exc:  # reported on the main thread
            failures.append(exc)
            primed.set()

    extraction = threading.Thread(target=extract)
    extraction.start()
    try:
        assert primed.wait(timeout=60), "the extraction stream never yielded"
        assert not failures, failures
        monkeypatch.setattr(
            sandbox,
            "sandbox_settings",
            lambda: SandboxSettings(enabled=True, upload_check_timeout_seconds=0.5),
        )
        started = time.monotonic()
        with structlog.testing.capture_logs() as logs, pytest.raises(HTTPException) as caught:
            check_scan_geometry(born_digital_text_pdf(pages=1), "application/pdf")
        waited = time.monotonic() - started
    finally:
        extraction.join(timeout=30)
    assert not extraction.is_alive()
    assert (caught.value.status_code, caught.value.detail) == (503, SANDBOX_UNAVAILABLE_DETAIL)
    assert 0.45 <= waited < 1.0, f"the check waited {waited:.2f} s"
    assert [(log["event"], log["reason"]) for log in logs] == [
        ("upload_check_failed", "unavailable")
    ]
    assert not failures, failures
    assert extracted == [0, 1, 2]


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="VmHWM is Linux-only")
@pytest.mark.usefixtures("sandboxed")
def test_a_catalog_metadata_bomb_is_refused_without_growing_this_process() -> None:
    """The reviewer's ``catmeta`` (task 13 review): a 1.9 MB PDF whose catalog
    ``/Metadata`` inflates to 1 GB. No page reaches it, so no content check
    measures it, but pdfium inflates it while opening the file inside the
    check; in-process the check peaked at about 1.98 GB. In the worker the
    child hits its limit and dies, the upload is a 422 with the fixed
    message, and the web process's peak barely moves."""
    # Control (review item 4): the same shape at 100 MB passes in the worker,
    # so the refusal below is the 1 GB inflate's, not the shape's.
    check_scan_geometry(catalog_metadata_bomb_pdf(100_000_000), "application/pdf")
    assert sandbox.EXTRACTION_WORKER.last_outcome == "ok"
    bomb = catalog_metadata_bomb_pdf(1_000_000_000)
    assert len(bomb) < 2 * _MB
    before = reset_peak_rss()
    with structlog.testing.capture_logs() as logs, pytest.raises(HTTPException) as caught:
        check_scan_geometry(bomb, "application/pdf")
    grown = peak_rss_bytes() - before
    assert (caught.value.status_code, caught.value.detail) == (422, SANDBOX_FAILED_DETAIL)
    # Measured: pdfium aborts on the failed allocation, so the child dies.
    assert sandbox.EXTRACTION_WORKER.last_outcome == "crash"
    assert [(log["event"], log["reason"]) for log in logs] == [("upload_check_failed", "crash")]
    assert grown < 32 * _MB, f"the test process grew by {grown / _MB:.0f} MB"
    # The next upload gets a fresh child.
    check_scan_geometry(born_digital_text_pdf(pages=1), "application/pdf")
    assert sandbox.EXTRACTION_WORKER.last_outcome == "ok"
