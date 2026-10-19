"""Spec 2026-10-19 §2: each script's cost is compared with paper_cost_target_usd."""

from __future__ import annotations

import ast
import contextvars
import inspect
import tempfile
import textwrap
import threading
import unittest
from datetime import date
from unittest.mock import patch

from pydantic import BaseModel
from structlog.testing import capture_logs

from lemely.io import gemini
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
        with (
            capture_logs() as logs,
            script_cost_scope(self.settings, script_key="upload:7") as costs,
        ):
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
            update={
                "gemini": self.settings.gemini.model_copy(update={"paper_cost_target_usd": 100.0})
            }
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
        self.assertIsNone(gemini._script_cost.get())

    def test_bare_thread_without_copied_context_does_not_count(self) -> None:
        with script_cost_scope(self.settings, script_key="k") as costs:
            worker = threading.Thread(target=self._call, args=("binding_second_read", "z"))
            worker.start()
            worker.join()
        self.assertEqual(costs, {})


def _call_lines(source: str, name: str) -> list[int]:
    tree = ast.parse(textwrap.dedent(source))
    return sorted(
        n.lineno
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and (getattr(n.func, "id", None) == name or getattr(n.func, "attr", None) == name)
    )


def _scope_with(source: str) -> ast.With:
    tree = ast.parse(textwrap.dedent(source))
    (node,) = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.With)
        and any(
            isinstance(i.context_expr, ast.Call)
            and getattr(i.context_expr.func, "id", None) == "script_cost_scope"
            for i in n.items
        )
    ]
    return node


class WiringTests(unittest.TestCase):
    def test_scope_precedes_every_paid_call_and_wraps_grading(self) -> None:
        routes = (student.student_correct, teacher._run_grading_job)
        for route in routes:
            with self.subTest(route=route.__name__):
                scope = _scope_with(inspect.getsource(route))
                end = scope.end_lineno
                assert end is not None
                for name in ("ScanMetadataExtractor", "resolve_mark_scheme", "grade_paper"):
                    (line,) = _call_lines(inspect.getsource(route), name)
                    self.assertTrue(scope.lineno < line <= end, f"{name} outside the scope")
