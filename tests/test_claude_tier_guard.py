"""Sub-project C P2.4: a tiered Claude read over the budget at the floor is read in chunks."""

from __future__ import annotations

import contextlib
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from structlog.testing import capture_logs

from lemely.core.loose_schemas import MarkScheme
from lemely.io.binding import chunked_read
from lemely.io.binding.chunked_read import ChunkedLabelReader
from lemely.io.binding.label_binder import LabelBinder
from lemely.io.binding.orchestrate import chunked_reader_for
from tests.gemini_fakes import make_settings
from tests.test_extraction_binding import _ROOT, _bind, _items, _Model, _run

_PAGES = [MagicMock(png_bytes=b"p", index=i) for i in range(24)]


def _client() -> MagicMock:
    client = MagicMock()
    client._settings = make_settings(tempfile.mkdtemp())
    return client


def _binding(**kw: object):  # type: ignore[no-untyped-def]
    return make_settings(tempfile.mkdtemp()).binding.model_copy(update=kw)


def test_guard_builds_a_reader_for_a_tiered_claude_model_with_chunking_off() -> None:
    reader = chunked_reader_for(_client(), _binding(read_model="claude-haiku-5-5"))
    assert reader is not None and reader.tier_guard is True


def test_no_guard_for_an_untiered_claude_model_or_gemini() -> None:
    assert chunked_reader_for(_client(), _binding(read_model="claude-sonnet-5-5")) is None
    assert chunked_reader_for(_client(), _binding(read_model="gemini-3.8-flash")) is None


def test_explicit_chunking_is_not_a_guard() -> None:
    reader = chunked_reader_for(
        _client(), _binding(read_model="gemini-3.8-flash", claude_chunked_read=True)
    )
    assert reader is not None and reader.tier_guard is False


def test_guarded_24_page_read_over_the_budget_is_chunked_and_logged() -> None:
    client = _client()
    reader = ChunkedLabelReader(client, tier_guard=True)
    binder = LabelBinder(client, chunked=reader)
    sentinel = object()
    with (
        patch.object(chunked_read, "estimate_floor_tokens", return_value=120_000),
        patch.object(ChunkedLabelReader, "read", return_value=sentinel),
        capture_logs() as logs,
    ):
        got = binder.read(
            _PAGES, MagicMock(), uploads=MagicMock(), model="claude-haiku-5-5", extra_cache_key="k"
        )
    assert got is sentinel
    (line,) = [e for e in logs if e["event"] == "claude_tier_guard"]
    assert line["pages"] == 24 and line["model"] == "claude-haiku-5-5"
    assert line["log_level"] == "warning"


def test_guarded_read_under_the_budget_is_not_chunked() -> None:
    client = _client()
    binder = LabelBinder(client, chunked=ChunkedLabelReader(client, tier_guard=True))
    with (
        patch.object(chunked_read, "estimate_floor_tokens", return_value=50_000),
        patch.object(ChunkedLabelReader, "read") as chunked,
        patch.object(client, "generate_structured", return_value=MagicMock()),
        capture_logs() as logs,
        # the single-call path's parsing is not under test
        contextlib.suppress(Exception),
    ):
        binder.read(
            _PAGES,
            MagicMock(),
            uploads=MagicMock(),
            model="claude-haiku-5-5",
            extra_cache_key="k",
        )
    chunked.assert_not_called()
    assert "claude_tier_guard" not in [e["event"] for e in logs]


def test_guard_leaves_an_unreadable_page_to_the_single_call() -> None:
    client = _client()
    reader = ChunkedLabelReader(client, tier_guard=True)
    pages = [MagicMock(png_bytes=b"not a png", index=0)]
    assert reader.applies(pages, "claude-haiku-5-5") is False


@pytest.fixture
def scheme() -> MarkScheme:
    path = _ROOT / "corpus" / "mark-schemes" / "0625_w24_ms_41.json"
    return MarkScheme.model_validate(json.loads(path.read_text(encoding="utf-8")))


class _ChunkedUsed(Exception):
    """Raised by the patched chunked read: the guard sent the script down it."""


def test_run_binding_reads_a_haiku_script_in_chunks_with_chunking_off(
    tmp_path: Path, scheme: MarkScheme
) -> None:
    model = _Model(first=_items(_run(1)), second=_items(_run(1)))
    with (
        patch.object(chunked_read, "estimate_floor_tokens", return_value=120_000),
        patch.object(ChunkedLabelReader, "read", side_effect=_ChunkedUsed),
        capture_logs() as logs,
        pytest.raises(_ChunkedUsed),
    ):
        _bind(tmp_path, scheme, model, read_model="claude-haiku-5-5", claude_chunked_read=False)
    assert "claude_tier_guard" in [e["event"] for e in logs]
