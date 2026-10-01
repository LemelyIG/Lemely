"""Unit tests for lemely.web.upload_utils: the shared upload checks and their log line."""

from __future__ import annotations

import pytest
import structlog.testing
from fastapi import HTTPException

from lemely.runtime.sandbox import (
    SandboxCrash,
    SandboxError,
    SandboxFailure,
    SandboxMemory,
    SandboxTimeout,
    SandboxUnavailable,
)
from lemely.web.upload_utils import check_scan_geometry, sandbox_failure_to_http
from tests.pdf_fakes import page_bomb_pdf


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
