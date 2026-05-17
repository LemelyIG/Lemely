"""Tests for click-based CLI global options."""
from __future__ import annotations

import json
import unittest

from click.testing import CliRunner

from lemely.app.cli import cli


class CliGlobalOptionTests(unittest.TestCase):
    def test_version_flag_prints_semver_string(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["--version"])
        self.assertEqual(result.exit_code, 0)
        # importlib.metadata returns "0.1.0" for the installed package.
        self.assertRegex(result.output.strip(), r"^lemely, version \d")

    def test_unknown_command_exits_with_usage_code(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["nope"])
        self.assertEqual(result.exit_code, 2)

    def test_invalid_log_format_exits_with_usage_code(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["--log-format", "xml", "estimate-cost", "."])
        self.assertEqual(result.exit_code, 2)

    def test_help_lists_every_subcommand(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        for cmd in (
            "estimate-cost",
            "parse-mark-schemes",
            "correct-paper",
            "predict-grade",
            "detect-weaknesses",
            "generate-quiz",
        ):
            with self.subTest(cmd=cmd):
                self.assertIn(cmd, result.output)


if __name__ == "__main__":
    unittest.main()
