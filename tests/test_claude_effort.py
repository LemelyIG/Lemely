"""Spec 2026-10-19 §4 B3: Claude effort per tag and per leaf kind."""

from __future__ import annotations

import tempfile
import unittest
from datetime import date
from typing import Any
from unittest.mock import MagicMock, patch

from lemely.core.leaf_kind import leaf_kind
from lemely.core.loose_schemas import QuestionType
from lemely.core.schemas import AIMarkResponse
from lemely.io.gemini import GeminiClient, _reset_process_counters, record_calls
from tests.gemini_fakes import fake_genai_client, make_settings
from tests.test_anthropic_adapter import _VALID_MARK, _FakeAnthropic, _message, _settings

_HAIKU = "claude-haiku-5-5"


class LeafKindTests(unittest.TestCase):
    def test_every_question_type_has_a_kind(self) -> None:
        for qtype in QuestionType:
            with self.subTest(qtype=qtype):
                self.assertIn(
                    leaf_kind(MagicMock(type=qtype)), {"mcq", "numeric", "short", "extended"}
                )

    def test_examples(self) -> None:
        self.assertEqual(leaf_kind(MagicMock(type=QuestionType.CALCULATION)), "numeric")
        self.assertEqual(leaf_kind(MagicMock(type=QuestionType.LEVELS_BASED)), "extended")
        self.assertEqual(leaf_kind(MagicMock(type=QuestionType.TICKBOX)), "mcq")
        self.assertEqual(leaf_kind(MagicMock(type=QuestionType.RECALL)), "short")


class EffortTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.enterContext(record_calls())
        _reset_process_counters()
        today = patch("lemely.io.gemini._today", lambda: date(2026, 10, 19))
        today.start()
        self.addCleanup(today.stop)

    def _effort(self, table: dict[str, str], *, kind: str | None) -> str | None:
        settings = _settings(self.tmp)
        settings = settings.model_copy(
            update={"gemini": settings.gemini.model_copy(update={"claude_effort_for": table})}
        )
        fake = _FakeAnthropic(_message(_VALID_MARK))
        client = GeminiClient(settings, _genai_client=object(), _anthropic_client=fake, ledger=None)
        client.generate_structured(
            system_prompt="s",
            user_prompt=f"u{kind}",
            response_schema=AIMarkResponse,
            prompt_version="v1",
            model=_HAIKU,
            task_tag="correction",
            leaf_kind=kind,
        )
        return fake.messages.calls[0]["output_config"].get("effort")

    def test_lookup_order(self) -> None:
        table = {"correction:extended": "xhigh", "correction": "medium"}
        self.assertEqual(self._effort(table, kind="extended"), "xhigh")
        self.assertEqual(self._effort(table, kind="numeric"), "medium")
        self.assertEqual(self._effort({}, kind="extended"), "low")
        self.assertEqual(self._effort({"correction": "max"}, kind=None), "max")

    def test_effort_is_in_the_cache_key(self) -> None:
        settings = _settings(self.tmp)
        settings = settings.model_copy(
            update={
                "gemini": settings.gemini.model_copy(
                    update={"claude_effort_for": {"correction:extended": "high"}}
                )
            }
        )
        client = GeminiClient(
            settings, _genai_client=object(), _anthropic_client=_FakeAnthropic(), ledger=None
        )
        args: dict[str, Any] = {
            "system_prompt": "s",
            "user_prompt": "u",
            "response_schema": AIMarkResponse,
            "prompt_version": "v1",
            "model": _HAIKU,
            "task_tag": "correction",
        }
        self.assertNotEqual(
            client.structured_cache_key(leaf_kind="extended", **args),
            client.structured_cache_key(leaf_kind="numeric", **args),
        )
        self.assertEqual(
            client.structured_cache_key(leaf_kind="numeric", **args),
            client.structured_cache_key(**args),
        )

    def test_gemini_ignores_leaf_kind(self) -> None:
        settings = make_settings(self.tmp)
        settings = settings.model_copy(
            update={
                "gemini": settings.gemini.model_copy(
                    update={"claude_effort_for": {"correction": "max"}}
                )
            }
        )
        client = GeminiClient(settings, _genai_client=fake_genai_client(), ledger=None)
        args: dict[str, Any] = {
            "system_prompt": "s",
            "user_prompt": "u",
            "response_schema": AIMarkResponse,
            "prompt_version": "v1",
            "model": "gemini-3.8-flash",
            "task_tag": "correction",
        }
        self.assertEqual(
            client.structured_cache_key(leaf_kind="extended", **args),
            client.structured_cache_key(**args),
        )


class CorrectorPassesKindTests(unittest.TestCase):
    def _kwargs(self, table: dict[str, str]) -> dict[str, Any]:
        from lemely.io.correction_ai import AICorrector

        settings = make_settings(tempfile.mkdtemp())
        settings = settings.model_copy(
            update={"gemini": settings.gemini.model_copy(update={"claude_effort_for": table})}
        )
        client = GeminiClient(settings, _genai_client=fake_genai_client(), ledger=None)
        question = MagicMock(type=QuestionType.EXPLANATION, id="2", marks=2)
        reply = AIMarkResponse.model_validate(_VALID_MARK)
        with (
            patch("lemely.io.correction_ai.build_marker_user_prompt", return_value="u"),
            patch.object(client, "generate_structured", return_value=reply) as call,
        ):
            AICorrector(client).mark_question(question, "answer")
        return call.call_args_list[0].kwargs

    def test_kind_sent_only_when_the_table_is_set(self) -> None:
        self.assertNotIn("leaf_kind", self._kwargs({}))
        self.assertEqual(self._kwargs({"correction": "high"})["leaf_kind"], "extended")
