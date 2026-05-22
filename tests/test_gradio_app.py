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
                REAL_MARK_SCHEME.read_text(encoding="utf-8"), "utf-8",
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
