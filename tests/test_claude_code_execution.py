"""Spec 2026-10-19 §3 code execution: Claude's server tool, priced by container time."""

from __future__ import annotations

import tempfile
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from lemely.io.gemini import (
    GeminiClient,
    _reset_process_counters,
    process_call_records,
    record_calls,
)
from lemely.runtime.errors import ParseError
from tests.test_anthropic_adapter import _FakeAnthropic, _settings

_HAIKU = "claude-haiku-5-5"


def _result(stdout: str, return_code: int = 0) -> SimpleNamespace:
    return SimpleNamespace(
        type="bash_code_execution_tool_result",
        content=SimpleNamespace(
            type="bash_code_execution_result", stdout=stdout, stderr="", return_code=return_code
        ),
    )


def _message(*blocks: object) -> SimpleNamespace:
    return SimpleNamespace(
        content=list(blocks),
        stop_reason="end_turn",
        usage=SimpleNamespace(
            input_tokens=2_000,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
            output_tokens=300,
            output_tokens_details=SimpleNamespace(thinking_tokens=0),
        ),
    )


class CodeExecutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.enterContext(record_calls())
        _reset_process_counters()
        today = patch("lemely.io.gemini._today", lambda: date(2026, 10, 19))
        today.start()
        self.addCleanup(today.stop)

    def _run(
        self, *outcomes: object, tag: str | None = "question_validity"
    ) -> tuple[str, _FakeAnthropic]:
        fake = _FakeAnthropic(*outcomes)
        client = GeminiClient(
            _settings(self.tmp), _genai_client=object(), _anthropic_client=fake, ledger=None
        )
        text = client.generate_with_code_execution(
            prompt="compute 6*7", prompt_version="v1", model=_HAIKU, task_tag=tag
        )
        return text, fake

    def test_reply_is_the_stdout_of_the_last_successful_run(self) -> None:
        text, fake = self._run(
            _message(
                _result("42\n"),
                _result("41\n", return_code=1),
                SimpleNamespace(type="text", text="The answer is 42."),
            )
        )
        self.assertEqual(text, "42")
        (call,) = fake.messages.calls
        self.assertEqual(
            call["tools"], [{"type": "code_execution_20260521", "name": "code_execution"}]
        )
        self.assertNotIn("format", call.get("output_config", {}))

    def test_falls_back_to_the_final_text_block(self) -> None:
        text, _fake = self._run(_message(SimpleNamespace(type="text", text="42")))
        self.assertEqual(text, "42")

    def test_container_time_billed_at_the_five_minute_minimum(self) -> None:
        self._run(_message(_result("42\n")))
        (rec,) = process_call_records()
        self.assertEqual(rec.container_seconds, 300)
        expected = (2_000 * 0.10 + 300 * 0.50) / 1e6 + 300 / 3600 * 0.05
        self.assertAlmostEqual(rec.usd_now, expected, places=12)

    def test_no_code_ran_no_container_time(self) -> None:
        self._run(_message(SimpleNamespace(type="text", text="42")))
        (rec,) = process_call_records()
        self.assertEqual(rec.container_seconds, 0)

    def test_every_task_tag_may_use_code_execution(self) -> None:
        for tag in ("correction", "extraction", None):
            with self.subTest(tag=tag):
                self.tmp = tempfile.mkdtemp()  # fresh cache: each tag must reach the API
                text, fake = self._run(_message(_result("42\n")), tag=tag)
                self.assertEqual(text, "42")
                self.assertEqual(len(fake.messages.calls), 1)

    def test_empty_reply_is_a_parse_error(self) -> None:
        with self.assertRaises(ParseError):
            self._run(_message())

    def test_cache_key_is_not_the_structured_calls(self) -> None:
        fake = _FakeAnthropic()
        client = GeminiClient(
            _settings(self.tmp), _genai_client=object(), _anthropic_client=fake, ledger=None
        )
        plain = client._params_fingerprint(_HAIKU, "question_validity", None)
        tool = client._params_fingerprint(_HAIKU, "question_validity", None, tool="code_execution")
        self.assertNotEqual(plain, tool)
