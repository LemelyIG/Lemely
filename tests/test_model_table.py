"""The one model table `lemely doctor` and the web startup check share."""

from __future__ import annotations

from lemely.io.model_table import MODEL_TABLE_TAGS, configured_models
from lemely.runtime.config import Settings


def test_default_table_lists_every_model_for_tag_and_the_binder() -> None:
    settings = Settings()
    table = configured_models(settings)
    for tag in MODEL_TABLE_TAGS:
        assert table[tag] == settings.gemini.model_for(tag)
    assert "cascade_strong" not in table
    assert table["binding_read"] == settings.binding.read_model


def test_cascade_strong_model_listed_only_when_the_cascade_uses_it() -> None:
    on = Settings().model_copy(deep=True)
    on.gemini.cascade_enabled = True
    on.gemini.cascade_strong_model = "claude-haiku-5-5"
    assert configured_models(on)["cascade_strong"] == "claude-haiku-5-5"
    off = Settings().model_copy(deep=True)
    off.gemini.cascade_strong_model = "claude-haiku-5-5"
    assert "cascade_strong" not in configured_models(off)
