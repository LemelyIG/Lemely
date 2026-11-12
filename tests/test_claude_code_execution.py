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
from lemely.io.providers.anthropic_adapter import (
    MAX_LEG_RETRIES,
    MAX_PAUSE_CONTINUATIONS,
    AnthropicAdapter,
)
from lemely.runtime.errors import ExternalServiceError, ParseError
from tests.test_anthropic_adapter import _FakeAnthropic, _settings, _status_error

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

    def test_a_transient_error_is_retried_under_the_client_policy(self) -> None:
        with patch("lemely.io.gemini.time.sleep"):
            text, fake = self._run(_status_error(529), _message(_result("42\n")))
        self.assertEqual(text, "42")
        self.assertEqual(len(fake.messages.calls), 2)

    def test_a_persistent_transient_error_is_an_external_service_error(self) -> None:
        # question_gates catches (ParseError, ExternalServiceError): nothing else may escape.
        fake = _FakeAnthropic(*[_status_error(529) for _ in range(2)])
        client = GeminiClient(
            _settings(self.tmp, max_retries=1),
            _genai_client=object(),
            _anthropic_client=fake,
            ledger=None,
        )
        with (
            patch("lemely.io.gemini.time.sleep"),
            self.assertRaises(ExternalServiceError),
        ):
            client.generate_with_code_execution(
                prompt="p", prompt_version="v1", model=_HAIKU, task_tag="question_validity"
            )
        self.assertEqual(len(fake.messages.calls), 2)

    def test_text_only_reply_is_a_parse_error(self) -> None:
        # No code ran: prose must never pass as sandbox output.
        with self.assertRaises(ParseError):
            self._run(_message(SimpleNamespace(type="text", text="42")))

    def test_code_ran_without_stdout_falls_back_to_the_final_text(self) -> None:
        text, _fake = self._run(
            _message(_result("", return_code=1), SimpleNamespace(type="text", text="42"))
        )
        self.assertEqual(text, "42")

    def test_server_tool_use_counts_as_code_run(self) -> None:
        text, _fake = self._run(
            _message(
                SimpleNamespace(type="server_tool_use", name="bash_code_execution"),
                SimpleNamespace(type="text", text="42"),
            )
        )
        self.assertEqual(text, "42")

    def test_usage_counter_counts_as_code_run(self) -> None:
        msg = _message(SimpleNamespace(type="text", text="42"))
        msg.usage.server_tool_use = SimpleNamespace(code_execution_requests=1)
        text, _fake = self._run(msg)
        self.assertEqual(text, "42")

    def test_adapter_omits_output_config_without_effort(self) -> None:
        fake = _FakeAnthropic(_message(_result("42\n")))
        AnthropicAdapter(fake).complete_code_execution(  # type: ignore[arg-type]
            model=_HAIKU, prompt="p", thinking=None
        )
        self.assertNotIn("output_config", fake.messages.calls[0])

    def test_pause_turn_is_continued_in_one_container(self) -> None:
        paused = _message(SimpleNamespace(type="text", text="Let me compute this."))
        paused.stop_reason = "pause_turn"
        paused.container = SimpleNamespace(id="cont_1")
        text, fake = self._run(paused, _message(_result("42\n")))
        self.assertEqual(text, "42")
        first, second = fake.messages.calls
        self.assertNotIn("container", first)
        self.assertEqual(second["container"], "cont_1")
        self.assertEqual(second["messages"][-1]["role"], "assistant")
        self.assertEqual(second["messages"][-1]["content"], paused.content)
        (rec,) = process_call_records()
        self.assertEqual(rec.thinking, "low")  # the effort sent is recorded
        self.assertEqual(rec.input_tokens, 4_000)  # usage summed over both legs
        self.assertEqual(rec.container_seconds, 300)  # billed once

    def test_pause_turn_cap_exhausted_is_a_parse_error(self) -> None:
        def paused() -> SimpleNamespace:
            m = _message(SimpleNamespace(type="text", text="Let me compute this."), _result("42\n"))
            m.stop_reason = "pause_turn"
            return m

        with self.assertRaises(ParseError):
            self._run(*[paused() for _ in range(MAX_PAUSE_CONTINUATIONS + 1)])

    def test_stdout_from_an_earlier_pause_turn_leg_is_kept(self) -> None:
        first = _message(
            SimpleNamespace(type="server_tool_use", name="bash_code_execution"),
            _result("42\n"),
            SimpleNamespace(type="text", text="Checking"),
        )
        first.stop_reason = "pause_turn"
        first.container = SimpleNamespace(id="cont_1")
        text, _fake = self._run(
            first, _message(SimpleNamespace(type="text", text="The answer is 42."))
        )
        self.assertEqual(text, "42")
        (rec,) = process_call_records()
        self.assertEqual(rec.container_seconds, 300)

    def _paused_first_leg(self) -> SimpleNamespace:
        first = _message(
            SimpleNamespace(type="server_tool_use", name="bash_code_execution"),
            _result("42\n"),
            SimpleNamespace(type="text", text="Checking"),
        )
        first.stop_reason = "pause_turn"
        first.container = SimpleNamespace(id="cont_1")
        return first

    def test_a_transient_on_a_continuation_leg_retries_that_leg_only(self) -> None:
        with patch("lemely.io.providers.anthropic_adapter.time.sleep"):
            text, fake = self._run(
                self._paused_first_leg(),
                _status_error(529),
                _message(SimpleNamespace(type="text", text="The answer is 42.")),
            )
        self.assertEqual(text, "42")
        containers = [c.get("container") for c in fake.messages.calls]
        self.assertEqual(containers, [None, "cont_1", "cont_1"])
        (rec,) = process_call_records()
        self.assertEqual(rec.container_seconds, 300)
        self.assertEqual(rec.input_tokens, 4_000)

    def test_a_persistent_transient_on_a_continuation_records_usage_and_never_reruns(
        self,
    ) -> None:
        errors = [_status_error(529) for _ in range(MAX_LEG_RETRIES + 1)]
        with (
            patch("lemely.io.providers.anthropic_adapter.time.sleep"),
            patch("lemely.io.gemini.time.sleep"),
            self.assertRaises((ParseError, ExternalServiceError)),
        ):
            self._run(self._paused_first_leg(), *errors)
        (rec,) = process_call_records()
        self.assertEqual(rec.container_seconds, 300)
        self.assertEqual(rec.input_tokens, 2_000)

    def test_max_tokens_and_refusal_are_never_returned(self) -> None:
        for reason in ("max_tokens", "refusal"):
            with self.subTest(reason=reason):
                self.tmp = tempfile.mkdtemp()
                msg = _message(_result("42\n"), SimpleNamespace(type="text", text="42"))
                msg.stop_reason = reason
                with self.assertRaises(ParseError):
                    self._run(msg)

    def test_container_time_billed_at_the_five_minute_minimum(self) -> None:
        self._run(_message(_result("42\n")))
        (rec,) = process_call_records()
        self.assertEqual(rec.container_seconds, 300)
        expected = (2_000 * 0.10 + 300 * 0.50) / 1e6 + 300 / 3600 * 0.05
        self.assertAlmostEqual(rec.usd_now, expected, places=12)

    def test_no_code_ran_no_container_time(self) -> None:
        with self.assertRaises(ParseError):
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
