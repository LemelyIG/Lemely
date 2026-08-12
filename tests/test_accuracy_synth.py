"""Unit tests for the synthetic handwritten-scan generator."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import pdfplumber

from lemely.accuracy.synth import AnswerBlock, render_handwritten_scan, write_golden_case


def _sample_answers() -> list[AnswerBlock]:
    return [
        AnswerBlock(
            question_id="1a_i",
            text="Photosynthesis converts light energy into\nchemical energy stored in glucose.",
        ),
        AnswerBlock(question_id="1a_ii", text="The mitochondria is the powerhouse of the cell."),
    ]


def _count_pages(pdf_path: Path) -> int:
    # Pillow's PDF plugin is save-only (it cannot re-open the PDFs it writes),
    # so we use pdfplumber — already a project dependency — to read it back.
    with pdfplumber.open(pdf_path) as pdf:
        return len(pdf.pages)


class RenderHandwrittenScanTests(unittest.TestCase):
    def test_produces_valid_pdf(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_pdf = Path(tmp) / "scan.pdf"
            render_handwritten_scan(_sample_answers(), out_pdf, seed=0)
            self.assertTrue(out_pdf.exists())
            data = out_pdf.read_bytes()
            self.assertGreater(len(data), 0)
            self.assertTrue(data.startswith(b"%PDF"))

    def test_deterministic_for_same_seed(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_a = Path(tmp) / "a.pdf"
            out_b = Path(tmp) / "b.pdf"
            render_handwritten_scan(_sample_answers(), out_a, seed=42)
            render_handwritten_scan(_sample_answers(), out_b, seed=42)
            self.assertEqual(out_a.read_bytes(), out_b.read_bytes())

    def test_different_seed_differs(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_a = Path(tmp) / "a.pdf"
            out_b = Path(tmp) / "b.pdf"
            render_handwritten_scan(_sample_answers(), out_a, seed=1)
            render_handwritten_scan(_sample_answers(), out_b, seed=2)
            self.assertNotEqual(out_a.read_bytes(), out_b.read_bytes())

    def test_empty_answers_raises(self):
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(ValueError):
            render_handwritten_scan([], Path(tmp) / "scan.pdf")

    def test_invalid_font_name_raises(self):
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(ValueError):
            render_handwritten_scan(
                _sample_answers(), Path(tmp) / "scan.pdf", font_name="Comic Sans"
            )

    def test_long_text_produces_multiple_pages(self):
        long_answer = " ".join(f"word{i}" for i in range(2000))
        answers = [AnswerBlock(question_id="1", text=long_answer)]
        with tempfile.TemporaryDirectory() as tmp:
            out_pdf = Path(tmp) / "scan.pdf"
            render_handwritten_scan(answers, out_pdf, seed=0)
            self.assertGreaterEqual(_count_pages(out_pdf), 2)


class WriteGoldenCaseTests(unittest.TestCase):
    def test_writes_all_three_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = Path(tmp) / "case_0001"
            mark_scheme_json = json.dumps({"metadata": {}, "questions": []})
            answers_json = {"1a_i": {"student_answer": "x", "awarded_marks": 1}}
            write_golden_case(
                case_dir,
                mark_scheme_json,
                answers_json,
                _sample_answers(),
                seed=0,
            )

            ms_path = case_dir / "mark_scheme.json"
            ans_path = case_dir / "answers.json"
            pdf_path = case_dir / "scan.pdf"

            self.assertTrue(ms_path.exists())
            self.assertTrue(ans_path.exists())
            self.assertTrue(pdf_path.exists())

            self.assertEqual(ms_path.read_text(encoding="utf-8"), mark_scheme_json)
            self.assertEqual(json.loads(ans_path.read_text(encoding="utf-8")), answers_json)
            self.assertGreater(pdf_path.stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
