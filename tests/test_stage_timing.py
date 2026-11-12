"""Sub-project C P2.3: the stage timings the latency diagnosis reads."""

from __future__ import annotations

import contextlib
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from structlog.testing import capture_logs

from lemely.core.schemas import ExamMetadata
from lemely.io.llm.claude_provider import ClaudeProvider
from lemely.io.llm.image_fit import FittedImages
from lemely.io.llm.request import ImageInput, LLMRequest
from tests.gemini_fakes import make_settings


class _Stop(Exception):
    pass


def test_extraction_logs_rasterise_time_and_total_even_on_failure(tmp_path: Path) -> None:
    from lemely.io import answer_extraction as ae

    client = MagicMock()
    client._settings = make_settings(str(tmp_path))
    page = MagicMock(dpi=200.0, png_bytes=b"p")
    with (
        patch.object(ae, "build_question_manifest_hash_key", return_value="k"),
        patch.object(ae, "rasterise_scan_to_pages", return_value=[page, page]),
        patch.object(ae, "check_scan_hygiene", side_effect=_Stop),
        patch.object(ae, "marking_run_slot", contextlib.nullcontext),
        capture_logs() as logs,
        pytest.raises(_Stop),
    ):
        ae.GeminiAnswerExtractor(client)(scan_path=tmp_path / "s.pdf", mark_scheme=MagicMock())
    (raster,) = [e for e in logs if e["event"] == "extraction_rasterised"]
    assert raster["pages"] == 2 and raster["seconds"] >= 0
    (total,) = [e for e in logs if e["event"] == "extraction_stage_timing"]
    assert total["outcome"] == "_Stop" and total["total_seconds"] >= 0


def _fitted() -> FittedImages:
    return FittedImages(
        images=(b"i",),
        long_edge=1568,
        est_tokens=10,
        page_tokens=(10,),
        base64_bytes=4,
        over_token_budget=False,
        over_byte_limit=False,
    )


def test_claude_pages_ready_logs_route_and_seconds() -> None:
    provider = ClaudeProvider(MagicMock(), make_settings(tempfile.mkdtemp()))
    uploads = MagicMock()
    uploads.ensure.return_value = (_fitted(), ("file-1",))
    req = LLMRequest(
        model="claude-haiku-5-5",
        task_tag="extraction",
        system="s",
        prompt="p",
        response_schema=None,
        images=(ImageInput(b"x"),),
        uploads=uploads,
    )
    log = MagicMock()
    provider._pages(req, log)
    ((args, kwargs),) = [c for c in log.info.call_args_list if c.args[0] == "claude_pages_ready"]
    assert kwargs["route"] == "files_api" and kwargs["pages"] == 1 and kwargs["tag"] == "extraction"
    assert kwargs["seconds"] >= 0


def test_scan_metadata_logs_rasterise_and_call_time(tmp_path: Path) -> None:
    from lemely.io import scan_metadata as sm

    client = MagicMock()
    client.model_for_tag.return_value = "claude-haiku-5-5"
    meta = ExamMetadata(
        subject_code="0625",
        paper_number=4,
        paper_variant=1,
        session_month="Oct/Nov",
        session_year=2024,
    )
    client.generate_structured.return_value = meta
    with (
        patch.object(sm, "rasterise_scan_to_pages", return_value=[MagicMock(png_bytes=b"p")]),
        capture_logs() as logs,
    ):
        assert sm.ScanMetadataExtractor(client)(tmp_path / "s.pdf") == meta
    (line,) = [e for e in logs if e["event"] == "scan_metadata_timing"]
    assert line["pages"] == 1 and line["rasterise_seconds"] >= 0 and line["call_seconds"] >= 0
