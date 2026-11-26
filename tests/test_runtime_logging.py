"""Tests for lemely.runtime.logging configuration and redaction."""

from __future__ import annotations

import io
import json
import logging
import unittest

import structlog

from lemely.runtime.logging import configure_logging


class LoggingConfigurationTests(unittest.TestCase):
    def setUp(self) -> None:
        structlog.reset_defaults()
        for h in list(logging.getLogger().handlers):
            logging.getLogger().removeHandler(h)

    def test_json_format_writes_one_object_per_line(self) -> None:
        buf = io.StringIO()
        configure_logging(level="INFO", fmt="json", stream=buf)
        log = structlog.get_logger().bind(command="x")
        log.info("hello", question_id=42)
        line = buf.getvalue().strip().splitlines()[-1]
        payload = json.loads(line)
        self.assertEqual(payload["event"], "hello")
        self.assertEqual(payload["command"], "x")
        self.assertEqual(payload["question_id"], 42)

    def test_secret_keys_are_redacted_at_any_depth(self) -> None:
        buf = io.StringIO()
        configure_logging(level="INFO", fmt="json", stream=buf)
        log = structlog.get_logger()
        log.info(
            "config_dump",
            outer={"gemini_api_key": "sk-leak-me", "nested": {"password": "hunter2"}},
            token="t0p$ecret",
        )
        text = buf.getvalue()
        self.assertNotIn("sk-leak-me", text)
        self.assertNotIn("hunter2", text)
        self.assertNotIn("t0p$ecret", text)
        self.assertIn("***", text)

    def test_level_filters_below_threshold(self) -> None:
        buf = io.StringIO()
        configure_logging(level="WARNING", fmt="json", stream=buf)
        log = structlog.get_logger()
        log.info("filtered")
        log.warning("kept")
        text = buf.getvalue()
        self.assertNotIn("filtered", text)
        self.assertIn("kept", text)

    def test_stdlib_bridge_routes_through_structlog(self) -> None:
        buf = io.StringIO()
        configure_logging(level="DEBUG", fmt="json", stream=buf)
        logging.getLogger("third_party").info("library_event")
        text = buf.getvalue()
        self.assertIn("library_event", text)

    def test_lines_logged_inside_a_dry_run_are_dropped(self) -> None:
        """``configure_logging`` installs ``_drop_dry_run``: a dry run never happened."""
        buf = io.StringIO()
        configure_logging(level="INFO", fmt="json", stream=buf)
        log = structlog.get_logger("dry")
        try:
            with structlog.contextvars.bound_contextvars(dry_run=True):
                log.info("inside_info")
                log.error("inside_alert", alert=True)
                logging.getLogger("dry.stdlib").warning("inside_stdlib")
            log.info("after_info")
        finally:
            structlog.contextvars.clear_contextvars()
        events = [json.loads(line)["event"] for line in buf.getvalue().splitlines() if line.strip()]
        self.assertEqual(events, ["after_info"])


if __name__ == "__main__":
    unittest.main()
