"""Tests for the --on-error flag on parse-mark-schemes.

BatchParseResult per-file failures live in items[] with status
"failed" or "invalid_existing"; there is no top-level errors[] list.
The CLI's --on-error logic counts those statuses to decide exit code.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from click.testing import CliRunner

from lemely.app.cli import cli


class OnErrorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()

    def _build_corpus(self, root: Path) -> Path:
        (root / "0625_m20_ms_12.pdf").write_bytes(b"%PDF-1.4 fake")
        (root / "0625_m20_ms_12.json").write_text(
            Path("Sources/Physics/MarkingSchemes/0625_m20_ms_12.json").read_text(
                encoding="utf-8"
            ),
            encoding="utf-8",
        )
        (root / "0625_s20_ms_31.pdf").write_bytes(b"%PDF-1.4 fake")
        (root / "0625_s20_ms_31.json").write_text("{ not valid json")
        return root

    def test_default_continue_exits_1_on_partial_failure(self) -> None:
        with TemporaryDirectory() as tmp:
            root = self._build_corpus(Path(tmp))
            result = self.runner.invoke(
                cli, ["--json", "parse-mark-schemes", str(root)]
            )
        self.assertEqual(result.exit_code, 1, msg=result.output)
        data = json.loads(result.output)
        self.assertGreaterEqual(data["failed"], 1)

    def test_on_error_fail_exits_with_parse_code_on_first_failure(self) -> None:
        with TemporaryDirectory() as tmp:
            root = self._build_corpus(Path(tmp))
            result = self.runner.invoke(
                cli,
                ["parse-mark-schemes", str(root), "--on-error", "fail"],
            )
        self.assertEqual(result.exit_code, 6, msg=result.output)


if __name__ == "__main__":
    unittest.main()
