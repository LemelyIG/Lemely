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
        self.assertEqual(s.gemini.model, "claude-haiku-5-5")

    def test_example_shows_the_second_read_model_commented_out(self) -> None:
        """Unset by default (the read model reads twice); uncommented, it loads."""
        import tomllib

        from lemely.runtime.config import Settings

        rendered = render_example_toml()
        line = '# second_read_model = "claude-haiku-5-5"'
        self.assertIn(line, rendered)
        self.assertIsNone(Settings().binding.second_read_model)
        data = tomllib.loads(rendered.replace(line, line[2:]))
        self.assertEqual(data["binding"]["second_read_model"], "claude-haiku-5-5")
        self.assertEqual(
            Settings.model_validate({"binding": data["binding"]}).binding.second_read_model,
            "claude-haiku-5-5",
        )

    def test_example_documents_every_storage_key(self) -> None:
        """Final review finding 6: ``gcs_project_number`` (needed for evidence on gcs) was missing.

        Every ``[storage]`` field appears as a key, set or commented, and the commented project
        number, uncommented, loads as an int.
        """
        import re
        import tomllib

        from lemely.runtime.config import Settings, StorageSettings

        rendered = render_example_toml()
        section = rendered.split("[storage]\n", 1)[1].split("\n[", 1)[0]
        keys = set(re.findall(r"^(?:# )?([a-z_]+) = ", section, flags=re.MULTILINE))
        fields = set(StorageSettings.model_fields)
        self.assertGreaterEqual(len(fields), 9)  # non-vacuity: 9 [storage] fields today
        self.assertEqual(fields - keys, set())

        line = "# gcs_project_number = 123456789012"
        self.assertIn(line, section)
        data = tomllib.loads(rendered.replace(line, line[2:]))
        storage = Settings.model_validate({"storage": data["storage"]}).storage
        self.assertEqual(storage.gcs_project_number, 123456789012)


if __name__ == "__main__":
    unittest.main()
