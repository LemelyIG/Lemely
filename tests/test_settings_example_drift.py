"""Fails if `lemely.toml.example` drifts from generator output."""

from __future__ import annotations

import unittest
from pathlib import Path

from lemely.runtime.example_toml import render_example_toml


class ExampleTomlDriftTests(unittest.TestCase):
    def test_example_matches_generator(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        on_disk = (repo_root / "lemely.toml.example").read_text(encoding="utf-8")
        expected = render_example_toml()
        self.assertEqual(
            on_disk,
            expected,
            msg="lemely.toml.example is out of sync. Run `python -m lemely.runtime.example_toml`.",
        )

    def test_example_loads_via_load_settings(self) -> None:
        from lemely.runtime.config import load_settings

        repo_root = Path(__file__).resolve().parents[1]
        example = repo_root / "lemely.toml.example"
        # Empty env so the TOML defaults shine through.
        import os

        snapshot = {k: v for k, v in os.environ.items() if k.startswith("LEMELY_")}
        for key in list(snapshot):
            del os.environ[key]
        try:
            s = load_settings(toml_path=example, cwd=repo_root)
        finally:
            os.environ.update(snapshot)
        self.assertEqual(s.gradio.port, 7860)
        self.assertEqual(s.gemini.model, "gemini-2.5-flash")


if __name__ == "__main__":
    unittest.main()
