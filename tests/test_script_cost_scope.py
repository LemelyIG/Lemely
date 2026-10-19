"""Spec 2026-10-19 §2: each script's cost is compared with paper_cost_target_usd."""

from __future__ import annotations

import contextvars
import inspect
import tempfile
import threading
import unittest
from datetime import date
from unittest.mock import patch

from pydantic import BaseModel
from structlog.testing import capture_logs

from lemely.io.gemini import GeminiClient, _reset_process_counters, script_cost_scope
from lemely.web.routers import student, teacher
from tests.gemini_fakes import fake_genai_client, make_settings, mock_response


class _Reply(BaseModel):
    value: str


class ScopeTests(unittest.TestCase):
    def setUp(self) -> None:
        _reset_process_counters()
        today = patch("lemely.io.gemini._today", lambda: date(2026, 10, 19))
        today.start()
        self.addCleanup(today.stop)
        settings = make_settings(tempfile.mkdtemp())
        self.settings = settings.model_copy(
            update={"gemini": settings.gemini.model_copy(update={"paper_cost_target_usd": 0.001})}
        )
        genai = fake_genai_client()
        genai.models.generate_content.side_effect = [
            mock_response('{"value": "a"}', prompt=10_000, candidates=1_000),
            mock_response('{"value": "b"}', prompt=10_000, candidates=1_000),
        ]
        self.client = GeminiClient(self.settings, _genai_client=genai, ledger=None)

    def _call(self, tag: str, extra: str) -> None:
        self.client.generate_structured(
            system_prompt="s",
            user_prompt=extra,
            response_schema=_Reply,
            prompt_version="v1",
            model="gemini-3.8-flash",
            task_tag=tag,
        )

    def test_over_target_logs_the_split_by_tag(self) -> None:
        with capture_logs() as logs, script_cost_scope(self.settings, script_key="upload:7") as costs:
            self._call("extraction", "x")
            self._call("correction", "y")
        self.assertEqual(sorted(costs), ["correction", "extraction"])
        (line,) = [e for e in logs if e["event"] == "script_over_cost_target"]
        self.assertEqual(line["script_key"], "upload:7")
        self.assertEqual(sorted(line["by_tag"]), ["correction", "extraction"])
        self.assertAlmostEqual(line["total_usd"], round(sum(costs.values()), 6), places=6)
        self.assertEqual(line["log_level"], "warning")

    def test_under_target_logs_nothing(self) -> None:
        settings = self.settings.model_copy(
            update={"gemini": self.settings.gemini.model_copy(update={"paper_cost_target_usd": 100.0})}
        )
        with capture_logs() as logs, script_cost_scope(settings, script_key="k"):
            self._call("correction", "y")
        self.assertNotIn("script_over_cost_target", [e["event"] for e in logs])

    def test_calls_in_copied_context_threads_count(self) -> None:
        with script_cost_scope(self.settings, script_key="k") as costs:
            ctx = contextvars.copy_context()
            worker = threading.Thread(target=ctx.run, args=(self._call, "binding_second_read", "z"))
            worker.start()
            worker.join()
        self.assertIn("binding_second_read", costs)

    def test_no_scope_no_accumulation(self) -> None:
        with capture_logs() as logs:
            self._call("correction", "y")
        self.assertNotIn("script_over_cost_target", [e["event"] for e in logs])


class WiringTests(unittest.TestCase):
    def test_both_web_marking_routes_open_a_scope(self) -> None:
        for module in (student, teacher):
            with self.subTest(module=module.__name__):
                self.assertIn("script_cost_scope(", inspect.getsource(module))
