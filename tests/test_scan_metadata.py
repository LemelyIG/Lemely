"""Tests for Phase 3: ScanMetadataExtractor and metadata cross-checking."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

from lemely.core.schemas import ExamMetadata
from lemely.io.scan_metadata import ScanMetadataExtractor, cross_check_metadata
from lemely.runtime.events import EventType

if TYPE_CHECKING:
    from pathlib import Path


def _meta(**kw) -> ExamMetadata:
    defaults = dict(
        subject_code="0625",
        paper_number=1,
        paper_variant=2,
        session_month="May/June",
        session_year=2020,
    )
    defaults.update(kw)
    return ExamMetadata(**defaults)


class TestScanMetadataExtractor:
    def test_returns_exam_metadata_from_gemini(self, tmp_path: Path) -> None:
        scan_pdf = tmp_path / "scan.pdf"
        scan_pdf.write_bytes(b"%PDF fake")

        expected = _meta()
        mock_client = MagicMock()
        mock_client.generate_structured.return_value = expected

        extractor = ScanMetadataExtractor(mock_client)
        result = extractor(scan_pdf)

        assert result == expected
        mock_client.generate_structured.assert_called_once()
        call_kwargs = mock_client.generate_structured.call_args.kwargs
        assert call_kwargs["task_tag"] == "scan_metadata"
        assert call_kwargs["response_schema"] is ExamMetadata
        assert scan_pdf in call_kwargs["file_paths"]

    def test_uses_correct_prompt_version(self, tmp_path: Path) -> None:
        scan_pdf = tmp_path / "scan.pdf"
        scan_pdf.write_bytes(b"%PDF fake")

        mock_client = MagicMock()
        mock_client.generate_structured.return_value = _meta()

        ScanMetadataExtractor(mock_client)(scan_pdf)

        call_kwargs = mock_client.generate_structured.call_args.kwargs
        assert call_kwargs["prompt_version"] == "1"


class TestScanMetadataOnClaude:
    @staticmethod
    def _client() -> MagicMock:
        client = MagicMock()
        client.model_for_tag.return_value = "claude-haiku-5-5"
        client.generate_structured.return_value = _meta()
        return client

    def test_sends_only_the_cover_pages_via_the_sandboxed_rasteriser(self, tmp_path: Path) -> None:
        scan = tmp_path / "scan.pdf"
        scan.write_bytes(b"%PDF fake")
        pages = [MagicMock(png_bytes=bytes([i])) for i in range(5)]
        client = self._client()
        with (
            patch(
                "lemely.io.scan_metadata.rasterise_scan_to_pages", return_value=pages
            ) as sandboxed,
            patch("lemely.io.rasterise.rasterise_pdf_to_pages") as in_process,
        ):
            ScanMetadataExtractor(client)(scan)
        sandboxed.assert_called_once_with(scan)
        in_process.assert_not_called()
        kwargs = client.generate_structured.call_args.kwargs
        assert kwargs["image_parts"] == [bytes([0]), bytes([1])]
        assert "file_paths" not in kwargs

    def test_image_scan_works(self, tmp_path: Path) -> None:
        import io

        from PIL import Image

        scan = tmp_path / "scan.jpg"
        buf = io.BytesIO()
        Image.new("RGB", (40, 30), "white").save(buf, "JPEG")
        scan.write_bytes(buf.getvalue())
        client = self._client()
        # Real sandboxed rasteriser, no PDF involved.
        ScanMetadataExtractor(client)(scan)
        image_parts = client.generate_structured.call_args.kwargs["image_parts"]
        assert len(image_parts) == 1
        assert image_parts[0].startswith(b"\x89PNG") or image_parts[0].startswith(b"\xff\xd8")


class TestCrossCheckMetadata:
    def test_matching_metadata_no_warning(self) -> None:
        meta = _meta()
        events: list = []

        from lemely.runtime.events import bus

        bus.subscribe(EventType.WARNING, lambda **kw: events.append(kw))

        result = cross_check_metadata(meta, meta)
        assert result == meta
        assert events == []

    def test_mismatch_fires_warning(self) -> None:
        scan = _meta(subject_code="0580")
        ms = _meta(subject_code="0625")

        events: list = []
        from lemely.runtime.events import bus

        bus.subscribe(EventType.WARNING, lambda **kw: events.append(kw))

        result = cross_check_metadata(scan, ms)

        # Mark-scheme metadata is authoritative
        assert result.subject_code == "0625"
        assert len(events) >= 1

    def test_ms_metadata_returned_on_mismatch(self) -> None:
        scan = _meta(paper_number=2)
        ms = _meta(paper_number=1)

        from lemely.runtime.events import bus

        bus.subscribe(EventType.WARNING, lambda **kw: None)

        result = cross_check_metadata(scan, ms)
        assert result.paper_number == 1
