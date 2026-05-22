"""Tests for lemely doctor / lemely version subcommands."""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from click.testing import CliRunner

from lemely.app.cli import cli


class DoctorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()
        for k in list(os.environ):
            if k.startswith("LEMELY_") or k == "GEMINI_API_KEY":
                del os.environ[k]

    def test_doctor_fails_without_gemini_api_key(self) -> None:
        with TemporaryDirectory() as tmp:
            (Path(tmp) / "Sources").mkdir()
            (Path(tmp) / "outputs").mkdir()
            result = self.runner.invoke(
                cli,
                ["--json", "doctor", "--no-network"],
                env={"LEMELY_PATHS__SOURCES_DIR": str(Path(tmp) / "Sources")},
            )
        self.assertEqual(result.exit_code, 3, msg=result.output)
        payload = json.loads(result.output)
        self.assertFalse(payload["all_passed"])
        self.assertIn("gemini_api_key", json.dumps(payload))

    def test_doctor_succeeds_with_valid_env(self) -> None:
        with TemporaryDirectory() as tmp:
            (Path(tmp) / "Sources").mkdir()
            (Path(tmp) / "outputs").mkdir()
            result = self.runner.invoke(
                cli,
                ["--json", "doctor", "--no-network"],
                env={
                    "GEMINI_API_KEY": "test-key-not-validated-with-no-network",
                    "LEMELY_PATHS__SOURCES_DIR": str(Path(tmp) / "Sources"),
                    "LEMELY_PATHS__OUTPUT_DIR": str(Path(tmp) / "outputs"),
                    "LEMELY_PATHS__CACHE_DIR": str(Path(tmp) / "cache"),
                },
            )
        self.assertEqual(result.exit_code, 0, msg=result.output)
        payload = json.loads(result.output)
        self.assertTrue(payload["all_passed"])


class VersionTests(unittest.TestCase):
    def test_version_subcommand_prints_known_keys(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["--json", "version"])
        self.assertEqual(result.exit_code, 0)
        payload = json.loads(result.output)
        self.assertIn("lemely", payload)
        self.assertIn("python", payload)


if __name__ == "__main__":
    unittest.main()
