"""``GeminiSettings.cache_forget_enabled`` gates ``GeminiClient.forget_cached``.

Measurement runs (a cost-ladder screen, a frozen baseline) turn it off so a held
paper's upstream entries survive and every screen reads the same frozen upstream.
"""

from __future__ import annotations

import tempfile
import unittest
from unittest.mock import MagicMock

from lemely.io.gemini import GeminiClient
from lemely.runtime.config import Settings
from tests.gemini_fakes import make_settings


def _settings(tmp: str, *, forget_enabled: bool | None) -> Settings:
    base = make_settings(tmp)
    if forget_enabled is None:
        return base
    return base.model_copy(
        update={"gemini": base.gemini.model_copy(update={"cache_forget_enabled": forget_enabled})}
    )


class CacheForgetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()

    def _client_with_entries(self, forget_enabled: bool | None) -> tuple[GeminiClient, list[str]]:
        client = GeminiClient(
            _settings(self.tmp, forget_enabled=forget_enabled), _genai_client=MagicMock()
        )
        keys = ["k1", "k2"]
        for key in keys:
            path = client._cache_path(key)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}", encoding="utf-8")
        return client, keys

    def test_forget_disabled_keeps_entries(self) -> None:
        client, keys = self._client_with_entries(False)
        self.assertEqual(client.forget_cached(keys), 0)
        for key in keys:
            self.assertTrue(client._cache_path(key).exists())

    def test_forget_enabled_default_deletes(self) -> None:
        client, keys = self._client_with_entries(None)
        self.assertTrue(client._settings.gemini.cache_forget_enabled)
        self.assertEqual(client.forget_cached(keys), 2)
        for key in keys:
            self.assertFalse(client._cache_path(key).exists())


if __name__ == "__main__":
    unittest.main()
