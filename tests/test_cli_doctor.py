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
        snapshot = {
            k: v for k, v in os.environ.items() if k.startswith("LEMELY_") or k == "GEMINI_API_KEY"
        }

        def restore() -> None:
            for k in list(os.environ):
                if k.startswith("LEMELY_") or k == "GEMINI_API_KEY":
                    del os.environ[k]
            os.environ.update(snapshot)

        self.addCleanup(restore)
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

    def _run_doctor_with_env(self, tmp: str) -> object:
        return self.runner.invoke(
            cli,
            ["--json", "doctor"],  # no --no-network: exercises the live ping
            env={
                "GEMINI_API_KEY": "test-key",
                "LEMELY_PATHS__SOURCES_DIR": str(Path(tmp) / "Sources"),
                "LEMELY_PATHS__OUTPUT_DIR": str(Path(tmp) / "outputs"),
                "LEMELY_PATHS__CACHE_DIR": str(Path(tmp) / "cache"),
            },
        )

    def test_doctor_live_ping_reports_reachable(self) -> None:
        from unittest.mock import patch

        with TemporaryDirectory() as tmp:
            (Path(tmp) / "Sources").mkdir()
            (Path(tmp) / "outputs").mkdir()
            with patch("lemely.io.gemini.GeminiClient.check_reachable", return_value=None):
                result = self._run_doctor_with_env(tmp)
        self.assertEqual(result.exit_code, 0, msg=result.output)
        payload = json.loads(result.output)
        self.assertTrue(payload["all_passed"])
        reach = next(c for c in payload["checks"] if c["name"] == "gemini_reachable")
        self.assertTrue(reach["ok"])

    def test_doctor_live_ping_reports_unreachable(self) -> None:
        from unittest.mock import patch

        from lemely.runtime.errors import ExternalServiceError

        with TemporaryDirectory() as tmp:
            (Path(tmp) / "Sources").mkdir()
            (Path(tmp) / "outputs").mkdir()
            with patch(
                "lemely.io.gemini.GeminiClient.check_reachable",
                side_effect=ExternalServiceError("Gemini API not reachable: boom"),
            ):
                result = self._run_doctor_with_env(tmp)
        self.assertEqual(result.exit_code, 3, msg=result.output)
        payload = json.loads(result.output)
        self.assertFalse(payload["all_passed"])
        reach = next(c for c in payload["checks"] if c["name"] == "gemini_reachable")
        self.assertFalse(reach["ok"])
        self.assertIn("not reachable", str(reach["detail"]))


class DoctorTestsEnvLeakTests(unittest.TestCase):
    """Regression test for #121: DoctorTests.setUp must not leak env deletions."""

    def test_doctor_tests_setup_does_not_leak_env_deletions(self) -> None:
        original_gemini_key = os.environ.get("GEMINI_API_KEY")
        os.environ["LEMELY_LEAK_CANARY"] = "1"
        try:
            suite = unittest.TestLoader().loadTestsFromTestCase(DoctorTests)
            with open(os.devnull, "w") as devnull:
                result = unittest.TextTestRunner(stream=devnull).run(suite)
            self.assertTrue(result.wasSuccessful(), msg=str(result.errors + result.failures))

            self.assertIn(
                "LEMELY_LEAK_CANARY",
                os.environ,
                msg="DoctorTests.setUp leaked an env deletion past the class",
            )
            if original_gemini_key is not None:
                self.assertEqual(
                    os.environ.get("GEMINI_API_KEY"),
                    original_gemini_key,
                    msg="DoctorTests.setUp failed to restore GEMINI_API_KEY",
                )
        finally:
            os.environ.pop("LEMELY_LEAK_CANARY", None)


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
