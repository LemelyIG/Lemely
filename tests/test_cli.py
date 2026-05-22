import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from lemely.app.cli import main

REAL_MARK_SCHEME = Path("Sources/Physics/MarkingSchemes/0625_m20_ms_12.json")


def real_mcq_mark_scheme_text() -> str:
    return REAL_MARK_SCHEME.read_text(encoding="utf-8")


def run_cli(*args):
    stream = StringIO()
    with redirect_stdout(stream):
        exit_code = main(["--json", *args])
    return exit_code, json.loads(stream.getvalue())


class CliTests(unittest.TestCase):
    def test_estimate_cost_reports_cached_and_uncached_mark_schemes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "0625_m20_ms_12.pdf").write_bytes(b"%PDF-1.4")
            (root / "0625_m20_ms_12.json").write_text(real_mcq_mark_scheme_text(), "utf-8")
            (root / "0625_s20_ms_31.pdf").write_bytes(b"%PDF-1.4")

            exit_code, payload = run_cli("estimate-cost", str(root))

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["mark_scheme_pdfs"], 2)
        self.assertEqual(payload["cached_json"], 1)
        self.assertEqual(payload["needs_parsing"], 1)

    def test_parse_mark_schemes_skips_existing_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "0625_m20_ms_12.pdf").write_bytes(b"%PDF-1.4")
            (root / "0625_m20_ms_12.json").write_text(real_mcq_mark_scheme_text(), "utf-8")

            exit_code, payload = run_cli("parse-mark-schemes", str(root))

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["skipped"], 1)
        self.assertEqual(payload["items"][0]["status"], "skipped_existing")

    def test_correct_paper_outputs_accuracy_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scheme_path = root / "0625_m20_ms_12.json"
            scheme_path.write_text(real_mcq_mark_scheme_text(), "utf-8")

            exit_code, payload = run_cli(
                "correct-paper",
                "--mark-scheme",
                str(scheme_path),
                "--answers",
                "1 A\n2 B",
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["correction"]["awarded_marks"], 2)
        self.assertEqual(payload["grade_prediction"]["grade"], "U")
        self.assertGreaterEqual(len(payload["weaknesses"]["weak_areas"]), 1)

    def test_predict_grade_detect_weaknesses_and_generate_quiz_use_json_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scheme_path = root / "0625_m20_ms_12.json"
            scheme_path.write_text(real_mcq_mark_scheme_text(), "utf-8")
            _, report = run_cli(
                "correct-paper",
                "--mark-scheme",
                str(scheme_path),
                "--answers",
                "1 B\n2 B",
            )
            correction_path = root / "correction.json"
            correction_path.write_text(json.dumps(report["correction"]), "utf-8")
            weakness_path = root / "weaknesses.json"
            weakness_exit, weaknesses = run_cli("detect-weaknesses", str(correction_path))
            weakness_path.write_text(json.dumps(weaknesses), "utf-8")

            grade_exit, grade = run_cli("predict-grade", str(correction_path))
            quiz_exit, quiz = run_cli("generate-quiz", str(weakness_path), "--count", "1")

        self.assertEqual(weakness_exit, 0)
        self.assertEqual(grade_exit, 0)
        self.assertEqual(quiz_exit, 0)
        self.assertEqual(grade["grade"], "U")
        self.assertEqual(len(quiz["questions"]), 1)


def test_correct_paper_mcq_only_works_without_api_key():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        scheme_path = root / "0625_m20_ms_12.json"
        scheme_path.write_text(real_mcq_mark_scheme_text(), "utf-8")
        answers = '{"1": "A", "2": "B"}'
        exit_code, payload = run_cli(
            "correct-paper",
            "--mark-scheme", str(scheme_path),
            "--answers", answers,
            "--mcq-only",
        )
    assert exit_code == 0
    assert "correction" in payload


def test_extract_answers_requires_existing_scan():
    with tempfile.TemporaryDirectory() as tmp:
        scheme = Path(tmp) / "0625_m20_ms_12.json"
        scheme.write_text(real_mcq_mark_scheme_text(), "utf-8")
        exit_code = main([
            "--json", "extract-answers",
            "--mark-scheme", str(scheme),
            "--scan", str(Path(tmp) / "nonexistent.png"),
        ])
    assert exit_code != 0


def test_aggregate_subject_combines_three_papers():
    with tempfile.TemporaryDirectory() as tmp:
        from lemely.core.schemas import (
            ConfidenceBand, CorrectedQuestion, CorrectionResult, ExamMetadata,
        )
        paths = []
        for paper_num in (2, 4, 6):
            meta = ExamMetadata(
                subject_code="0625", paper_number=paper_num, paper_variant=1,
                session_month="May/June", session_year=2020,
            )
            cr = CorrectionResult(metadata=meta, questions=[
                CorrectedQuestion(
                    question_id=f"q{paper_num}", awarded_marks=5, maximum_marks=10,
                    confidence=ConfidenceBand.HIGH, confidence_score=1.0,
                    needs_teacher_review=False, topic="kinematics",
                ),
            ])
            p = Path(tmp) / f"paper{paper_num}.json"
            p.write_text(cr.model_dump_json(indent=2), "utf-8")
            paths.append(str(p))

        exit_code, payload = run_cli("aggregate-subject", *paths)
    assert exit_code == 0
    assert payload["subject_code"] == "0625"
    assert payload["awarded_marks"] == 15
    assert payload["maximum_marks"] == 30


if __name__ == "__main__":
    unittest.main()
