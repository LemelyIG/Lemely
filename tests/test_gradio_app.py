import json
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


if __name__ == "__main__":
    unittest.main()
