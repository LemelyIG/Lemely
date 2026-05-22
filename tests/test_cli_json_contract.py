"""Asserts every CLI command's --json output is parseable and schema-valid.

Reuses the same real mark-scheme fixture at
Sources/Physics/MarkingSchemes/0625_m20_ms_12.json that tests/test_cli.py uses.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from click.testing import CliRunner

from lemely.app.cli import cli
from lemely.core.schemas import (
    AccuracyReport,
    BatchParseResult,
    CostEstimate,
    GradePrediction,
    QuizPayload,
    WeaknessReport,
)

_REAL_MS = Path("Sources/Physics/MarkingSchemes/0625_m20_ms_12.json")


def _real_ms_text() -> str:
    return _REAL_MS.read_text(encoding="utf-8")


class JsonContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()

    def test_estimate_cost_json_validates(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "0625_m20_ms_12.pdf").write_bytes(b"%PDF-1.4")
            (root / "0625_m20_ms_12.json").write_text(_real_ms_text(), "utf-8")
            result = self.runner.invoke(cli, ["--json", "estimate-cost", str(root)])
        self.assertEqual(result.exit_code, 0, msg=result.output)
        CostEstimate.model_validate(json.loads(result.output))

    def test_parse_mark_schemes_json_validates(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "0625_m20_ms_12.pdf").write_bytes(b"%PDF-1.4")
            (root / "0625_m20_ms_12.json").write_text(_real_ms_text(), "utf-8")
            result = self.runner.invoke(
                cli, ["--json", "parse-mark-schemes", str(root)]
            )
        self.assertEqual(result.exit_code, 0, msg=result.output)
        data = json.loads(result.output)
        # Computed fields (total/parsed/skipped/failed) are in the JSON output
        # but are not model inputs; strip them before validating the contract.
        for key in ("total", "parsed", "skipped", "failed"):
            data.pop(key, None)
        BatchParseResult.model_validate(data)

    def test_correct_paper_json_validates_accuracy_report(self) -> None:
        with TemporaryDirectory() as tmp:
            ms = Path(tmp) / "ms.json"
            ms.write_text(_real_ms_text(), "utf-8")
            result = self.runner.invoke(
                cli,
                [
                    "--json",
                    "correct-paper",
                    "--mark-scheme",
                    str(ms),
                    "--answers",
                    "1 A\n2 B",
                ],
            )
        self.assertEqual(result.exit_code, 0, msg=result.output)
        AccuracyReport.model_validate(json.loads(result.output))

    def test_predict_grade_and_detect_weaknesses_json_validate(self) -> None:
        with TemporaryDirectory() as tmp:
            ms = Path(tmp) / "ms.json"
            ms.write_text(_real_ms_text(), "utf-8")
            r1 = self.runner.invoke(
                cli,
                ["--json", "correct-paper", "--mark-scheme", str(ms), "--answers", "1 A"],
            )
            self.assertEqual(r1.exit_code, 0, msg=r1.output)
            ar = json.loads(r1.output)
            corr = Path(tmp) / "correction.json"
            corr.write_text(json.dumps(ar["correction"]), "utf-8")

            r2 = self.runner.invoke(cli, ["--json", "predict-grade", str(corr)])
            self.assertEqual(r2.exit_code, 0, msg=r2.output)
            GradePrediction.model_validate(json.loads(r2.output))

            r3 = self.runner.invoke(cli, ["--json", "detect-weaknesses", str(corr)])
            self.assertEqual(r3.exit_code, 0, msg=r3.output)
            WeaknessReport.model_validate(json.loads(r3.output))

    def test_generate_quiz_json_validates(self) -> None:
        with TemporaryDirectory() as tmp:
            ms = Path(tmp) / "ms.json"
            ms.write_text(_real_ms_text(), "utf-8")
            r1 = self.runner.invoke(
                cli,
                ["--json", "correct-paper", "--mark-scheme", str(ms), "--answers", "1 A"],
            )
            corr = Path(tmp) / "correction.json"
            corr.write_text(json.dumps(json.loads(r1.output)["correction"]), "utf-8")
            r2 = self.runner.invoke(cli, ["--json", "detect-weaknesses", str(corr)])
            weak = Path(tmp) / "weak.json"
            weak.write_text(r2.output, "utf-8")

            r3 = self.runner.invoke(
                cli, ["--json", "generate-quiz", str(weak), "--count", "1"]
            )
            self.assertEqual(r3.exit_code, 0, msg=r3.output)
            QuizPayload.model_validate(json.loads(r3.output))


if __name__ == "__main__":
    unittest.main()
