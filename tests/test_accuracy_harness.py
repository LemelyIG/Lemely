"""Unit tests for the golden-dataset accuracy measurement harness."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path


class LoadGoldenCasesTests(unittest.TestCase):

    def _make_case_dir(self, root: Path, name: str = "0625_m20_qp_12") -> Path:
        case_dir = root / name
        case_dir.mkdir()
        ms = {
            "metadata": {
                "subject": "Physics", "subject_code": "0625",
                "paper_number": 1, "paper_variant": 2,
                "session_month": "May/June", "session_year": 2020,
                "paper_type": "mcq", "maximum_mark": 1,
                "scheme_format": "mcq",
            },
            "questions": [
                {"id": "1", "marks": 1, "type": "mcq", "mcq_answer": "A"},
            ],
        }
        (case_dir / "mark_scheme.json").write_text(json.dumps(ms))
        answers = {"1": {"student_answer": "A", "awarded_marks": 1}}
        (case_dir / "answers.json").write_text(json.dumps(answers))
        return case_dir

    def test_loads_single_case(self):
        from lemely.accuracy.harness import load_golden_cases
        with tempfile.TemporaryDirectory() as tmp:
            self._make_case_dir(Path(tmp))
            cases = load_golden_cases(Path(tmp))
        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0].paper_id, "0625_m20_qp_12")

    def test_ground_truth_parsed(self):
        from lemely.accuracy.harness import load_golden_cases
        with tempfile.TemporaryDirectory() as tmp:
            self._make_case_dir(Path(tmp))
            cases = load_golden_cases(Path(tmp))
        gt = cases[0].ground_truth
        self.assertIn("1", gt)
        self.assertEqual(gt["1"].student_answer, "A")
        self.assertEqual(gt["1"].awarded_marks, 1)

    def test_scan_path_none_when_no_pdf(self):
        from lemely.accuracy.harness import load_golden_cases
        with tempfile.TemporaryDirectory() as tmp:
            self._make_case_dir(Path(tmp))
            cases = load_golden_cases(Path(tmp))
        self.assertIsNone(cases[0].scan_path)

    def test_scan_path_set_when_pdf_present(self):
        from lemely.accuracy.harness import load_golden_cases
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = self._make_case_dir(Path(tmp))
            (case_dir / "scan.pdf").write_bytes(b"%PDF-1.4")
            cases = load_golden_cases(Path(tmp))
        self.assertIsNotNone(cases[0].scan_path)

    def test_skips_dir_without_required_files(self):
        from lemely.accuracy.harness import load_golden_cases
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "incomplete").mkdir()
            cases = load_golden_cases(Path(tmp))
        self.assertEqual(len(cases), 0)

    def test_notes_field_optional(self):
        from lemely.accuracy.harness import load_golden_cases
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = self._make_case_dir(Path(tmp))
            answers = {"1": {"student_answer": "A", "awarded_marks": 1, "notes": "owtte"}}
            (case_dir / "answers.json").write_text(json.dumps(answers))
            cases = load_golden_cases(Path(tmp))
        self.assertEqual(cases[0].ground_truth["1"].notes, "owtte")

    def test_multiple_cases_sorted_order(self):
        from lemely.accuracy.harness import load_golden_cases
        with tempfile.TemporaryDirectory() as tmp:
            self._make_case_dir(Path(tmp), name="zzz_paper")
            self._make_case_dir(Path(tmp), name="aaa_paper")
            cases = load_golden_cases(Path(tmp))
        self.assertEqual(len(cases), 2)
        self.assertEqual(cases[0].paper_id, "aaa_paper")
        self.assertEqual(cases[1].paper_id, "zzz_paper")

    def test_skips_malformed_answers_json(self):
        from lemely.accuracy.harness import load_golden_cases
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = self._make_case_dir(Path(tmp))
            (case_dir / "answers.json").write_text("{ not valid json }")
            cases = load_golden_cases(Path(tmp))
        self.assertEqual(len(cases), 0)
