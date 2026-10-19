"""Spec 2026-10-19 §1: the provider-neutral request and its single cache-key source."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from lemely.io import gemini as gemini_module
from lemely.io.llm.errors import CapTruncatedError, TransientCallError
from lemely.io.llm.provider import ProviderReply, Usage
from lemely.io.llm.request import (
    CachePlan,
    DocumentInput,
    LLMRequest,
    provider_fingerprint,
)
from lemely.io.providers import anthropic_adapter
from lemely.runtime.errors import ExternalServiceError


class ProviderFingerprintTests(unittest.TestCase):
    def test_gemini_models_add_nothing(self) -> None:
        for model in ("gemini-3.8-flash", "gemini-2.5-flash", "gemini-3.1-flash-lite"):
            with self.subTest(model=model):
                self.assertEqual(provider_fingerprint(model, max_output_tokens=65536), "")

    def test_claude_segment_is_todays(self) -> None:
        self.assertEqual(
            provider_fingerprint("claude-haiku-5-5", max_output_tokens=16000),
            "|provider=anthropic|max_tokens=16000",
        )

    def test_request_fingerprint_is_the_module_function(self) -> None:
        req = LLMRequest(
            model="claude-haiku-5-5",
            task_tag="correction",
            system="s",
            prompt="p",
            response_schema=None,
            max_output_tokens=16000,
        )
        self.assertEqual(
            req.fingerprint(), provider_fingerprint("claude-haiku-5-5", max_output_tokens=16000)
        )


class CachePlanTests(unittest.TestCase):
    def test_more_than_four_breakpoints_refused(self) -> None:
        with self.assertRaises(ValueError):
            CachePlan(breakpoints=("system", "documents", "images", "prefix", "system"))

    def test_duplicate_breakpoints_refused(self) -> None:
        with self.assertRaises(ValueError):
            CachePlan(breakpoints=("system", "system"))

    def test_default_is_no_breakpoints(self) -> None:
        self.assertEqual(CachePlan().breakpoints, ())


class DocumentInputTests(unittest.TestCase):
    def test_from_path_reads_bytes_and_keeps_path(self) -> None:
        path = Path(tempfile.mkdtemp()) / "ms.pdf"
        path.write_bytes(b"%PDF-1.4 x")
        doc = DocumentInput.from_path(path, cache=True)
        self.assertEqual(doc.data, b"%PDF-1.4 x")
        self.assertEqual(doc.source_path, path)
        self.assertTrue(doc.cache)
        self.assertEqual(doc.media_type, "application/pdf")


class MovedNamesTests(unittest.TestCase):
    def test_client_error_names_are_the_shared_classes(self) -> None:
        self.assertIs(gemini_module._TransientError, TransientCallError)
        self.assertIs(gemini_module._CapTruncatedError, CapTruncatedError)
        self.assertTrue(issubclass(CapTruncatedError, ExternalServiceError))

    def test_adapter_usage_is_the_provider_usage(self) -> None:
        self.assertIs(anthropic_adapter.Usage, Usage)

    def test_reply_defaults(self) -> None:
        reply = ProviderReply(
            text="t", usage_response=None, stop_reason=None, stop_detail="", latency_ms=0
        )
        self.assertIsNone(reply.usage)
