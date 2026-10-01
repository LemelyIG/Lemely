"""Unit tests for lemely.web.upload_utils: the shared upload checks and their log line."""

from __future__ import annotations

import pytest
import structlog.testing
from fastapi import HTTPException

from lemely.web.upload_utils import check_scan_geometry
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
