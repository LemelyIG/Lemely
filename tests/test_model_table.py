"""The one model table `lemely doctor` and the web startup check share."""

from __future__ import annotations

from datetime import date

from lemely.io.model_table import MODEL_TABLE_TAGS, configured_models, model_rows
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


def test_the_second_read_model_is_listed_only_when_it_is_set_and_read() -> None:
    default = configured_models(Settings())
    assert "binding_second_read" not in default
    claude = Settings().model_copy(deep=True)
    claude.binding.second_read_model = "claude-haiku-5-5"
    table = configured_models(claude)
    assert table["binding_second_read"] == "claude-haiku-5-5"
    assert table["binding_read"] == claude.binding.read_model
    one_read = claude.model_copy(deep=True)
    one_read.binding.second_read = False
    assert "binding_second_read" not in configured_models(one_read)
    legacy = claude.model_copy(deep=True)
    legacy.binding.binder = "legacy"
    assert "binding_second_read" not in configured_models(legacy)


def _with_gemini(**gemini: object) -> Settings:
    s = Settings()
    return s.model_copy(update={"gemini": s.gemini.model_copy(update=gemini)})


def test_model_rows_one_per_configured_tag_with_provider_effort_and_price() -> None:
    s = _with_gemini(correction_model="claude-haiku-5-5")
    rows = model_rows(s, on=date(2026, 10, 19))
    assert [r.tag for r in rows] == list(configured_models(s))
    correction = next(r for r in rows if r.tag == "correction")
    assert (correction.provider, correction.effort) == ("anthropic", "low")
    assert correction.price == "0.1/0.01/0.5 $/MTok, >100000 tokens 0.5/0.05/2.5"
    extraction = next(r for r in rows if r.tag == "extraction")
    assert extraction.provider == "gemini"
    assert extraction.price is not None


def test_model_rows_unpriced_model_has_no_price() -> None:
    rows = model_rows(_with_gemini(correction_model="claude-nonexistent-9"), on=date(2026, 10, 19))
    assert next(r for r in rows if r.tag == "correction").price is None


def test_the_first_binder_read_shows_the_extraction_effort_and_the_overview_is_listed() -> None:
    s = Settings().model_copy(deep=True)
    s.binding.claude_chunked_read = True
    s.gemini.thinking_level_for = {**s.gemini.thinking_level_for, "extraction": "high"}
    s.gemini.thinking_level_for.pop("binding_read", None)
    rows = {r.tag: r for r in model_rows(s, on=date(2026, 10, 19))}
    assert rows["binding_read"].effort == rows["extraction"].effort
    assert "binding_overview" in rows
    assert rows["binding_overview"].model == s.binding.read_model
    assert "binding_overview" not in configured_models(Settings())
