"""Spec 2026-10-19 §3 PDFs: typed PDFs as document blocks, scans as images; Gemini unchanged."""

from __future__ import annotations

import base64
import io
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pypdfium2 as pdfium

from lemely.core.loose_schemas import MarkScheme
from lemely.core.schemas import AIMarkResponse
from lemely.io.gemini import GeminiClient, _reset_process_counters, record_calls
from lemely.io.llm import claude_provider
from lemely.io.llm.request import DocumentInput
from lemely.io.parsers import GeminiMarkSchemeParser
from lemely.io.providers import ProviderError
from lemely.io.scan_metadata import ScanMetadataExtractor
from tests.gemini_fakes import fake_genai_client, make_settings, mock_response
from tests.test_anthropic_adapter import _VALID_MARK, _FakeAnthropic, _message, _settings

_HAIKU = "claude-haiku-5-5"


def _pdf(pages: int) -> bytes:
    doc = pdfium.PdfDocument.new()
    for _ in range(pages):
        doc.new_page(612, 792)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.enterContext(record_calls())
        _reset_process_counters()
        today = patch("lemely.io.gemini._today", lambda: date(2026, 10, 19))
        today.start()
        self.addCleanup(today.stop)
        self.pdf = self.tmp / "ms.pdf"
        self.pdf.write_bytes(_pdf(2))

    def _claude(self, *outcomes: object, **gemini: object) -> tuple[GeminiClient, _FakeAnthropic]:
        settings = _settings(str(self.tmp))
        settings = settings.model_copy(update={"gemini": settings.gemini.model_copy(update=gemini)})
        fake = _FakeAnthropic(*outcomes)
        return GeminiClient(
            settings, _genai_client=object(), _anthropic_client=fake, ledger=None
        ), fake


class ClaudeDocumentTests(_Base):
    def test_document_block_goes_first_as_base64_pdf(self) -> None:
        client, fake = self._claude(_message(_VALID_MARK))
        client.generate_structured(
            system_prompt="s",
            user_prompt="u",
            documents=[DocumentInput.from_path(self.pdf, cache=True)],
            response_schema=AIMarkResponse,
            prompt_version="v1",
            model=_HAIKU,
            task_tag="mark_scheme",
        )
        content = fake.messages.calls[0]["messages"][0]["content"]
        self.assertEqual([b["type"] for b in content], ["document", "text"])
        self.assertEqual(content[0]["source"]["media_type"], "application/pdf")
        self.assertEqual(base64.b64decode(content[0]["source"]["data"]), self.pdf.read_bytes())
        self.assertEqual(content[0]["cache_control"], {"type": "ephemeral"})

    def test_too_many_pdf_pages_refused_before_sending(self) -> None:
        client, fake = self._claude(_message(_VALID_MARK))
        with (
            patch.object(claude_provider, "MAX_PDF_PAGES", 1),
            self.assertRaisesRegex(ProviderError, "2 PDF pages"),
        ):
            client.generate_structured(
                system_prompt="s",
                user_prompt="u",
                documents=[DocumentInput.from_path(self.pdf)],
                response_schema=AIMarkResponse,
                prompt_version="v1",
                model=_HAIKU,
                task_tag="mark_scheme",
            )
        self.assertEqual(fake.messages.calls, [])

    def test_request_over_32_mb_refused(self) -> None:
        client, fake = self._claude(_message(_VALID_MARK))
        with (
            patch.object(claude_provider, "MAX_REQUEST_BYTES", 100),
            self.assertRaisesRegex(ProviderError, "bytes"),
        ):
            client.generate_structured(
                system_prompt="s",
                user_prompt="u",
                documents=[DocumentInput.from_path(self.pdf)],
                response_schema=AIMarkResponse,
                prompt_version="v1",
                model=_HAIKU,
                task_tag="mark_scheme",
            )
        self.assertEqual(fake.messages.calls, [])

    def test_citations_with_a_response_schema_refused(self) -> None:
        """The API returns 400 for citations plus structured outputs; refuse before sending."""
        client, fake = self._claude(_message(_VALID_MARK))
        with self.assertRaisesRegex(ProviderError, "citations"):
            client.generate_structured(
                system_prompt="s",
                user_prompt="u",
                documents=[
                    DocumentInput(data=b"scheme text", media_type="text/plain", citations=True)
                ],
                response_schema=AIMarkResponse,
                prompt_version="v1",
                model=_HAIKU,
                task_tag="correction",
            )
        self.assertEqual(fake.messages.calls, [])

    def test_file_paths_on_claude_name_the_task_tag(self) -> None:
        client, fake = self._claude()
        with self.assertRaisesRegex(ValueError, "task_tag='study_plan'"):
            client.generate_structured(
                system_prompt="s",
                user_prompt="u",
                file_paths=[self.pdf],
                response_schema=AIMarkResponse,
                prompt_version="v1",
                model=_HAIKU,
                task_tag="study_plan",
            )

    def test_file_paths_and_documents_together_refused(self) -> None:
        client, _fake = self._claude()
        with self.assertRaises(ValueError):
            client.generate_structured(
                system_prompt="s",
                user_prompt="u",
                file_paths=[self.pdf],
                documents=[DocumentInput.from_path(self.pdf)],
                response_schema=AIMarkResponse,
                prompt_version="v1",
                model="gemini-2.5-flash",
                task_tag="mark_scheme",
            )


class GeminiUnchangedTests(_Base):
    def test_parser_documents_reproduce_the_file_paths_call(self) -> None:
        def run(use_parser: bool) -> tuple[list[str], list[bytes], object]:
            tmp = Path(tempfile.mkdtemp())
            genai = fake_genai_client()
            genai.models.generate_content.return_value = mock_response("{}")
            client = GeminiClient(make_settings(str(tmp)), _genai_client=genai, ledger=None)
            with patch.object(MarkScheme, "model_validate_json", return_value=MagicMock()):
                if use_parser:
                    GeminiMarkSchemeParser(client)(self.pdf)
                else:
                    from lemely.io.prompts.mark_scheme_parsing import (
                        PARSER_SYSTEM_PROMPT,
                        PARSER_USER_PROMPT,
                        VERSION,
                    )

                    client.generate_structured(
                        system_prompt=PARSER_SYSTEM_PROMPT,
                        user_prompt=PARSER_USER_PROMPT,
                        file_paths=[self.pdf],
                        response_schema=MarkScheme,
                        prompt_version=VERSION,
                        task_tag="mark_scheme",
                    )
            keys = sorted(p.stem for p in (tmp / ".cache" / "gemini").glob("*.json"))
            uploads = [data for data, _cfg in genai.files.uploads]
            return keys, uploads, genai.models.generate_content.call_args.kwargs["contents"][0]

        self.assertEqual(run(use_parser=True), run(use_parser=False))

    def test_scan_metadata_on_gemini_still_uploads_the_pdf(self) -> None:
        client = MagicMock()
        client.model_for_tag.return_value = "gemini-3.5-flash-lite"
        ScanMetadataExtractor(client)(self.pdf)
        kwargs = client.generate_structured.call_args.kwargs
        self.assertEqual(kwargs["file_paths"], [self.pdf])
        self.assertNotIn("image_parts", kwargs)

    def test_scan_metadata_on_claude_sends_rasterised_pages(self) -> None:
        client = MagicMock()
        client.model_for_tag.return_value = _HAIKU
        page = MagicMock(png_bytes=b"\x89PNG-page")
        with patch("lemely.io.scan_metadata.rasterise_scan_to_pages", return_value=[page, page]):
            ScanMetadataExtractor(client)(self.pdf)
        kwargs = client.generate_structured.call_args.kwargs
        self.assertEqual(kwargs["image_parts"], [b"\x89PNG-page", b"\x89PNG-page"])
        self.assertNotIn("file_paths", kwargs)

    def test_documents_without_bytes_are_refused(self) -> None:
        client, fake = self._claude()
        with self.assertRaisesRegex(ValueError, "task_tag='mark_scheme'"):
            client.generate_structured(
                system_prompt="s",
                user_prompt="u",
                documents=[DocumentInput(data=b"", source_path=self.pdf)],
                response_schema=AIMarkResponse,
                prompt_version="v1",
                model=_HAIKU,
                task_tag="mark_scheme",
            )
        self.assertEqual(fake.messages.calls, [])

    def test_scan_metadata_with_a_mock_model_stays_on_gemini(self) -> None:
        client = MagicMock()
        ScanMetadataExtractor(client)(self.pdf)
        self.assertIn("file_paths", client.generate_structured.call_args.kwargs)
