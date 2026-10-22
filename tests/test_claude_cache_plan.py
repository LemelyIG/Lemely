"""Spec 2026-10-19 §4 B1: cache breakpoints per tag, the 512-token rule, binder reads."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from typing import Any, ClassVar
from unittest.mock import patch

import pydantic
from PIL import Image

from lemely.core.loose_schemas import MarkScheme
from lemely.core.schemas import AIMarkResponse
from lemely.io.binding import orchestrate
from lemely.io.binding.orchestrate import run_binding
from lemely.io.gemini import GeminiClient, _reset_process_counters, record_calls
from lemely.io.llm.request import DocumentInput
from lemely.io.providers import ProviderError
from lemely.runtime.config import GeminiSettings
from tests.gemini_fakes import fake_genai_client, make_settings
from tests.test_anthropic_adapter import _VALID_MARK, _FakeAnthropic, _message, _settings
from tests.test_extraction_binding import _items, _Model, _pages, _run

_HAIKU = "claude-haiku-5-5"
_LONG = "x" * 4_000  # 1,000 estimated tokens
_ROOT = Path(__file__).resolve().parents[1]
_EPHEMERAL = {"type": "ephemeral"}


def _page() -> bytes:
    buf = io.BytesIO()
    Image.new("L", (1000, 1400), 200).save(buf, "PNG")
    return buf.getvalue()


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.enterContext(record_calls())
        _reset_process_counters()
        today = patch("lemely.io.gemini._today", lambda: date(2026, 10, 19))
        today.start()
        self.addCleanup(today.stop)

    def _call(self, cache_for: dict[str, list[str]] | None = None, **kwargs: Any) -> dict[str, Any]:
        settings = _settings(self.tmp)
        if cache_for is not None:
            settings = settings.model_copy(
                update={
                    "gemini": settings.gemini.model_copy(update={"claude_cache_for": cache_for})
                }
            )
        fake = _FakeAnthropic(_message(_VALID_MARK))
        client = GeminiClient(settings, _genai_client=object(), _anthropic_client=fake, ledger=None)
        params: dict[str, Any] = {
            "system_prompt": _LONG,
            "user_prompt": "read",
            "response_schema": AIMarkResponse,
            "prompt_version": "v1",
            "model": _HAIKU,
            "task_tag": "binding_second_read",
            **kwargs,
        }
        client.generate_structured(**params)
        (call,) = fake.messages.calls
        return call


def _marked(call: dict[str, Any]) -> list[str]:
    """The type of every block that carries cache_control, system first."""
    blocks = list(call["system"]) + list(
        call["messages"][0]["content"] if isinstance(call["messages"][0]["content"], list) else []
    )
    return [b["type"] for b in blocks if b.get("cache_control") == _EPHEMERAL]


class PlanTests(_Base):
    def test_default_is_the_legacy_system_breakpoint(self) -> None:
        call = self._call(image_parts=[_page()])
        self.assertEqual(_marked(call), ["text"])
        self.assertIn("cache_control", call["system"][0])

    def test_images_breakpoint_marks_the_last_image(self) -> None:
        call = self._call(
            cache_for={"binding_second_read": ["system", "images"]}, image_parts=[_page(), _page()]
        )
        content = call["messages"][0]["content"]
        self.assertNotIn("cache_control", content[0])
        self.assertEqual(content[1]["cache_control"], _EPHEMERAL)
        self.assertEqual(_marked(call), ["text", "image"])

    def test_empty_plan_marks_nothing(self) -> None:
        call = self._call(cache_for={"binding_second_read": []}, image_parts=[_page()])
        self.assertEqual(_marked(call), [])

    def test_a_prefix_under_512_tokens_gets_no_breakpoint(self) -> None:
        call = self._call(cache_for={"binding_second_read": ["system"]}, system_prompt="short")
        self.assertEqual(_marked(call), [])

    def test_documents_breakpoint_marks_the_last_document(self) -> None:
        call = self._call(
            cache_for={"binding_second_read": ["documents"]},
            system_prompt="",
            documents=[DocumentInput(data=b"y" * 4_000, media_type="text/plain")],
            response_schema=AIMarkResponse,
        )
        self.assertEqual(_marked(call), ["document"])

    def test_more_than_four_breakpoints_in_one_request_refused(self) -> None:
        docs = [DocumentInput(data=b"y" * 4_000, media_type="text/plain", cache=True)] * 4
        with self.assertRaisesRegex(ProviderError, "cache breakpoints"):
            self._call(documents=docs)

    def test_settings_refuse_five_spots_or_a_repeat(self) -> None:
        for spots in (["system", "documents", "images", "prefix", "system"], ["images", "images"]):
            with self.subTest(spots=spots), self.assertRaises(pydantic.ValidationError):
                GeminiSettings(claude_cache_for={"extraction": spots})


def _scheme() -> MarkScheme:
    path = _ROOT / "corpus" / "mark-schemes" / "0625_w24_ms_41.json"
    return MarkScheme.model_validate(json.loads(path.read_text(encoding="utf-8")))


def _binder_client(tmp: str, cache_for: dict[str, list[str]]) -> GeminiClient:
    settings = make_settings(tmp)
    settings = settings.model_copy(
        update={
            "binding": settings.binding.model_copy(update={"read_model": _HAIKU}),
            "gemini": settings.gemini.model_copy(update={"claude_cache_for": cache_for}),
        }
    )
    return GeminiClient(settings, _genai_client=fake_genai_client(), ledger=None)


class BinderSequencingTests(unittest.TestCase):
    _SHARED: ClassVar[dict[str, list[str]]] = {
        "extraction": ["system", "images"],
        "binding_second_read": ["system", "images"],
    }

    def _bind(self, cache_for: dict[str, list[str]]) -> tuple[_Model, Any]:
        client = _binder_client(tempfile.mkdtemp(), cache_for)
        model = _Model(first=_items(_run(1)), second=_items(_run(1)))
        pages = _pages()
        with (
            client.image_uploads([p.png_bytes for p in pages], concurrency=1) as uploads,
            patch.object(client, "generate_structured", side_effect=model),
            patch.object(orchestrate, "_read_both", wraps=orchestrate._read_both) as both,
        ):
            outcome = run_binding(
                client,
                pages,
                _scheme(),
                uploads=uploads,
                settings=client._settings,
                manifest_key="k",
            )
        self.assertEqual(outcome.report.verdict if outcome.report else None, "pass")
        return model, both

    def test_reads_sharing_a_claude_cache_run_one_after_the_other(self) -> None:
        model, both = self._bind(self._SHARED)
        both.assert_not_called()
        self.assertEqual(
            [c["task_tag"] for c in model.calls], ["extraction", "binding_second_read"]
        )

    def test_without_the_images_breakpoint_the_reads_run_together(self) -> None:
        _model, both = self._bind({})
        both.assert_called_once()

    def test_the_predicate(self) -> None:
        settings = _binder_client(tempfile.mkdtemp(), self._SHARED)._settings
        share = orchestrate._reads_share_a_claude_cache
        self.assertTrue(share(settings, _HAIKU, _HAIKU))
        self.assertFalse(share(settings, _HAIKU, "claude-sonnet-5-5"))
        self.assertFalse(share(settings, "gemini-3.8-flash", "gemini-3.8-flash"))
