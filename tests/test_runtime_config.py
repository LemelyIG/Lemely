"""Tests for lemely.runtime.config Settings loading and validation."""

from __future__ import annotations

import os
import textwrap
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from pydantic import ValidationError

from lemely.runtime.config import load_settings


class _IsolatedEnv:
    """Fully isolate Settings inputs: clears LEMELY_* and unprefixed key env
    vars, AND chdirs into an empty temp dir so ``Settings(env_file=".env")``
    cannot pick up a developer's real repo-root ``.env`` during the test.
    """

    def __init__(self, **overrides: str) -> None:
        self.overrides = overrides
        self._snapshot: dict[str, str] = {}
        self._prev_cwd: str = ""
        self._tmp: TemporaryDirectory[str] | None = None

    # Env vars that feed Settings but do not carry the LEMELY_ prefix
    # (the google-genai SDK reads these directly; Settings aliases them too).
    _UNPREFIXED = ("GEMINI_API_KEY", "GOOGLE_API_KEY")

    def __enter__(self) -> _IsolatedEnv:
        self._snapshot = dict(os.environ)
        for key in list(os.environ):
            if key.startswith("LEMELY_") or key in self._UNPREFIXED:
                del os.environ[key]
        os.environ.update(self.overrides)
        self._prev_cwd = os.getcwd()
        self._tmp = TemporaryDirectory()
        os.chdir(self._tmp.name)
        return self

    def __exit__(self, *_: object) -> None:
        os.chdir(self._prev_cwd)
        if self._tmp is not None:
            self._tmp.cleanup()
            self._tmp = None
        os.environ.clear()
        os.environ.update(self._snapshot)


class SettingsTests(unittest.TestCase):
    def test_defaults_load_without_any_source(self) -> None:
        with _IsolatedEnv(), TemporaryDirectory() as tmp:
            s = load_settings(toml_path=None, cwd=Path(tmp))
        self.assertEqual(s.gradio.host, "127.0.0.1")
        self.assertEqual(s.gradio.port, 7860)
        self.assertEqual(s.logging.level, "INFO")
        self.assertEqual(s.logging.format, "auto")
        self.assertEqual(s.gemini.model, "gemini-2.5-flash")
        self.assertIsNone(s.gemini_api_key)

    def test_extra_forbid_rejects_unknown_keys_in_toml(self) -> None:
        with TemporaryDirectory() as tmp:
            toml = Path(tmp) / "lemely.toml"
            toml.write_text(
                textwrap.dedent("""
                [gradio]
                hsot = "0.0.0.0"
            """).strip()
            )
            with _IsolatedEnv(), self.assertRaises(ValidationError) as cm:
                load_settings(toml_path=toml, cwd=Path(tmp))
        self.assertIn("hsot", str(cm.exception))

    def test_env_overrides_toml(self) -> None:
        with TemporaryDirectory() as tmp:
            toml = Path(tmp) / "lemely.toml"
            toml.write_text("[gradio]\nport = 5000\n")
            with _IsolatedEnv(LEMELY_GRADIO__PORT="9000"):
                s = load_settings(toml_path=toml, cwd=Path(tmp))
        self.assertEqual(s.gradio.port, 9000)

    def test_secret_redaction_in_dump(self) -> None:
        with _IsolatedEnv(LEMELY_GEMINI_API_KEY="sk-secret-xyz"), TemporaryDirectory() as tmp:
            s = load_settings(toml_path=None, cwd=Path(tmp))
        # Guard: ensure the secret actually loaded, so the redaction assertion
        # below isn't trivially true on an unset field.
        self.assertIsNotNone(s.gemini_api_key)
        self.assertEqual(s.gemini_api_key.get_secret_value(), "sk-secret-xyz")
        dumped = s.model_dump(mode="json")
        self.assertNotIn("sk-secret-xyz", str(dumped))

    def test_unprefixed_gemini_api_key_populates_settings(self) -> None:
        # The env-mapping trap fix: an unprefixed GEMINI_API_KEY (what the
        # google-genai SDK reads) must reach settings.gemini_api_key so the web
        # portal's AI-feature gate sees the key, not just CLI/Gradio.
        with _IsolatedEnv(GEMINI_API_KEY="sk-unprefixed"), TemporaryDirectory() as tmp:
            s = load_settings(toml_path=None, cwd=Path(tmp))
        self.assertIsNotNone(s.gemini_api_key)
        assert s.gemini_api_key is not None
        self.assertEqual(s.gemini_api_key.get_secret_value(), "sk-unprefixed")

    def test_google_api_key_populates_settings(self) -> None:
        with _IsolatedEnv(GOOGLE_API_KEY="sk-google"), TemporaryDirectory() as tmp:
            s = load_settings(toml_path=None, cwd=Path(tmp))
        self.assertIsNotNone(s.gemini_api_key)
        assert s.gemini_api_key is not None
        self.assertEqual(s.gemini_api_key.get_secret_value(), "sk-google")

    def test_lemely_prefixed_key_wins_over_unprefixed(self) -> None:
        with (
            _IsolatedEnv(LEMELY_GEMINI_API_KEY="sk-lemely", GEMINI_API_KEY="sk-plain"),
            TemporaryDirectory() as tmp,
        ):
            s = load_settings(toml_path=None, cwd=Path(tmp))
        assert s.gemini_api_key is not None
        self.assertEqual(s.gemini_api_key.get_secret_value(), "sk-lemely")

    def test_toml_discovery_prefers_cwd_lemely_toml(self) -> None:
        with TemporaryDirectory() as tmp:
            cwd = Path(tmp) / "cwd"
            cwd.mkdir()
            (cwd / "lemely.toml").write_text("[gradio]\nport = 4242\n")
            with _IsolatedEnv():
                s = load_settings(toml_path=None, cwd=cwd)
        self.assertEqual(s.gradio.port, 4242)


if __name__ == "__main__":
    unittest.main()
