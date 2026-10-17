import tempfile
import unittest
from pathlib import Path

from lemely.app.gradio_app import build_app, run_correction_demo

REAL_MARK_SCHEME = Path("Sources/Physics/MarkingSchemes/0625_m20_ms_12.json")


class GradioAppTests(unittest.TestCase):
    def test_run_correction_demo_returns_schema_valid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            scheme_path = Path(tmp) / "0625_m20_ms_12.json"
            scheme_path.write_text(REAL_MARK_SCHEME.read_text(encoding="utf-8"), "utf-8")

            payload = run_correction_demo(str(scheme_path), "1 A\n2 B")

        self.assertEqual(payload["correction"]["awarded_marks"], 2)
        self.assertGreaterEqual(len(payload["weaknesses"]["weak_areas"]), 1)
        self.assertIn("grade_prediction", payload)

    def test_build_app_is_lazy_about_gradio_dependency(self):
        try:
            app = build_app()
        except RuntimeError as exc:
            self.assertIn("gradio", str(exc).lower())
        else:
            self.assertTrue(hasattr(app, "launch"))


class GradioCallbackTests(unittest.TestCase):
    def test_dropdown_choices_built_from_sources_dir(self) -> None:
        from lemely.app.gradio_callbacks import (
            build_mark_scheme_dropdown_choices,
            parse_mark_scheme_path_from_label,
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "0625_m20_ms_12.pdf").write_bytes(b"%PDF-1.4")
            (root / "0625_m20_ms_12.json").write_text(
                REAL_MARK_SCHEME.read_text(encoding="utf-8"),
                "utf-8",
            )
            choices = build_mark_scheme_dropdown_choices(root)
        self.assertIsInstance(choices, list)
        self.assertTrue(len(choices) > 0)
        path = parse_mark_scheme_path_from_label(choices[0])
        self.assertTrue(str(path).endswith(".json"))

    def test_subject_session_choices_groups_paper_outputs(self) -> None:
        from lemely.app.gradio_callbacks import build_subject_session_choices

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "0625" / "MayJune_2020").mkdir(parents=True)
            paper_dir = out / "0625" / "MayJune_2020" / "0625_MayJune_2020_p21__2026-05-22-100000"
            paper_dir.mkdir()
            (paper_dir / "accuracy_report.json").write_text("{}", "utf-8")
            choices = build_subject_session_choices(out)
        self.assertEqual(len(choices), 1)
        self.assertIn("0625", choices[0])


if __name__ == "__main__":
    unittest.main()


class GradioBindingTests(unittest.TestCase):
    """The Gradio app keeps the binding verdict and the unbound leaves."""

    @staticmethod
    def _scheme():
        from lemely.core.loose_schemas import MarkScheme

        return MarkScheme.model_validate(
            {
                "metadata": {
                    "subject": "Physics",
                    "subject_code": "0625",
                    "paper_number": 1,
                    "paper_variant": 2,
                    "session_month": "May/June",
                    "session_year": 2020,
                    "paper_type": "mcq",
                    "maximum_mark": 2,
                    "scheme_format": "mcq",
                },
                "questions": [
                    {"id": "1", "marks": 1, "type": "mcq", "mcq_answer": "A"},
                    {"id": "2", "marks": 1, "type": "mcq", "mcq_answer": "B"},
                ],
            }
        )

    @staticmethod
    def _extracted(verdict: str = "hold"):
        from lemely.core.binding import BindingCheck, BindingReport
        from lemely.core.schemas import ExtractedAnswer, ExtractedAnswers

        return ExtractedAnswers(
            paper_id="p",
            source_scan="s.pdf",
            answers=[ExtractedAnswer(question_id="1", answer="A", confidence=0.9)],
            unbound_question_ids=["2"],
            binding=BindingReport(
                binder="label",
                verdict=verdict,
                checks=[BindingCheck(id="G1", passed=verdict == "pass", scope="paper", detail="d")],
            ),
        )

    def test_edited_text_is_laid_over_the_extraction_and_the_binding_survives(self) -> None:
        from lemely.app.gradio_callbacks import (
            extracted_to_table_rows,
            overlay_edited_answers,
        )
        from lemely.core.schemas import ExtractedAnswers

        extracted = self._extracted()
        rows = extracted_to_table_rows(extracted)
        rows[0][1] = "C"

        merged = overlay_edited_answers(extracted.model_dump_json(), rows)

        assert isinstance(merged, ExtractedAnswers)
        assert [(a.question_id, a.answer) for a in merged.answers] == [("1", "C")]
        assert merged.unbound_question_ids == ["2"]
        assert merged.binding is not None and merged.binding.verdict == "hold"

    def test_without_an_extraction_the_table_is_a_plain_mapping_as_before(self) -> None:
        from lemely.app.gradio_callbacks import overlay_edited_answers

        assert overlay_edited_answers("", [["1", "A", "", "", ""]]) == {"1": "A"}

    def test_an_unbound_leaf_is_marked_flagged_and_never_a_blank_zero(self) -> None:
        from lemely.app.gradio_callbacks import extracted_to_table_rows, overlay_edited_answers
        from lemely.io.correction_ai import correct_paper
        from lemely.runtime.config import MarkingOptions

        extracted = self._extracted()
        merged = overlay_edited_answers(
            extracted.model_dump_json(), extracted_to_table_rows(extracted)
        )

        correction = correct_paper(
            mark_scheme=self._scheme(),
            extracted_answers=merged,
            gemini_client=None,
            mcq_only=True,
            options=MarkingOptions(),
        )

        unbound = next(q for q in correction.questions if q.question_id == "2")
        assert unbound.marker_source == "dropped"
        assert unbound.needs_teacher_review is True
        assert unbound.awarded_marks == 0

    def test_a_result_whose_verdict_is_not_pass_is_not_saved(self) -> None:
        from lemely.app.gradio_callbacks import held_reason, save_correction_artifacts
        from lemely.core.analytics import predict_grade, summarize_weaknesses
        from lemely.core.schemas import AccuracyReport, CorrectionResult, ExamMetadata

        for verdict, saved in (("hold", False), ("retry", False), ("pass", True)):
            extracted = self._extracted(verdict)
            correction = CorrectionResult(
                metadata=ExamMetadata(
                    subject_code="0625",
                    paper_number=1,
                    paper_variant=2,
                    session_month="May/June",
                    session_year=2020,
                ),
                questions=[],
                binding=extracted.binding,
            )
            report = AccuracyReport(
                correction=correction,
                weaknesses=summarize_weaknesses(correction),
                grade_prediction=predict_grade(
                    correction, boundaries={}, boundary_source="global_default"
                ),
            ).model_dump(mode="json")
            with tempfile.TemporaryDirectory() as tmp:
                if saved:
                    assert held_reason(report) is None
                    save_correction_artifacts(Path(tmp), "x", "{}", "{}", report)
                    continue
                assert held_reason(report) is not None
                with self.assertRaises(ValueError):
                    save_correction_artifacts(Path(tmp), "x", "{}", "{}", report)
                assert list(Path(tmp).iterdir()) == []

    def test_the_extract_tab_summary_names_the_verdict_and_the_unbound_ids(self) -> None:
        from lemely.app.gradio_callbacks import binding_summary

        text = binding_summary(self._extracted())

        assert "hold" in text and "2" in text
