"""Spec 2026-10-19 §2b: overview plus chunks reproduces a one-pass read on a long script."""

from __future__ import annotations

import io
import json
import re
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any

from PIL import Image

from lemely.core.loose_schemas import MarkScheme
from lemely.io.binding.chunked_read import (
    OVERVIEW_TASK_TAG,
    ChunkedLabelReader,
    PageEntry,
    PageMap,
    plan_chunks,
)
from lemely.io.binding.label_binder import LabelBinder, parse_stream_items
from lemely.io.gemini import GeminiClient
from lemely.io.prompts.label_binding import build_label_binding_user_prompt
from lemely.io.rasterise import RasterisedPage
from tests.gemini_fakes import fake_genai_client, make_settings

_HAIKU = "claude-haiku-5-5"
_PAGES = 45
_ROOT = Path(__file__).resolve().parents[1]


def _scheme() -> MarkScheme:
    path = _ROOT / "corpus" / "mark-schemes" / "0625_w24_ms_41.json"
    return MarkScheme.model_validate(json.loads(path.read_text(encoding="utf-8")))


def _pages() -> list[RasterisedPage]:
    out = []
    for i in range(_PAGES):
        buf = io.BytesIO()
        Image.new("L", (400, 600), i).save(buf, "PNG")
        out.append(RasterisedPage(index=i, width=400, height=600, png_bytes=buf.getvalue()))
    return out


def _truth() -> list[dict[str, Any]]:
    """One label and one answer per page, as a one-pass read would list them."""
    items: list[dict[str, Any]] = []
    for p in range(_PAGES):
        items.append({"type": "label", "page": p, "text": f"{p + 1}", "kind": "printed"})
        items.append(
            {
                "type": "answer",
                "page": p,
                "answer": f"answer {p + 1}",
                "confidence": 0.9,
                "placed_by": "position",
            }
        )
    return items


class _FakeModel:
    """Answers the overview with the true map and each chunk with the truth for its pages."""

    def __init__(self, pages: list[RasterisedPage]) -> None:
        self.index = {p.png_bytes: p.index for p in pages}
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        schema = kwargs["response_schema"]
        if kwargs["task_tag"] == OVERVIEW_TASK_TAG:
            return PageMap(pages=[PageEntry(page=p, labels=[f"{p + 1}"]) for p in range(_PAGES)])
        sent = [self.index[b] for b in kwargs["image_parts"]]
        local = [
            {**item, "page": sent.index(item["page"])} for item in _truth() if item["page"] in sent
        ]
        return schema.model_validate({"items": local})


def _client(budget: int = 5_000) -> GeminiClient:
    settings = make_settings(tempfile.mkdtemp())
    settings = settings.model_copy(
        update={
            "gemini": settings.gemini.model_copy(update={"claude_image_token_budget": budget}),
            "binding": settings.binding.model_copy(update={"claude_chunked_read": True}),
        }
    )
    return GeminiClient(settings, _genai_client=fake_genai_client(), ledger=None)


class PlanTests(unittest.TestCase):
    def test_chunks_fit_the_budget_with_the_overlap_page(self) -> None:
        self.assertEqual(
            plan_chunks([320] * 45, 5_000),
            [range(0, 15), range(15, 29), range(29, 43), range(43, 45)],
        )

    def test_a_page_over_the_budget_is_a_chunk_of_its_own(self) -> None:
        self.assertEqual(
            plan_chunks([10, 9_000, 10], 5_000), [range(0, 1), range(1, 2), range(2, 3)]
        )

    def test_page_map_text_and_labels(self) -> None:
        page_map = PageMap(
            pages=[
                PageEntry(page=0, labels=["1(a)"], continues_to_next=True),
                PageEntry(page=1, labels=["1(b)"]),
            ]
        )
        self.assertEqual(page_map.labels_on(range(1, 2)), ["1(b)"])
        self.assertIn("page 1: 1(a); writing continues onto the next page", page_map.text())


class ReadTests(unittest.TestCase):
    def _read(
        self, reader: ChunkedLabelReader, pages: list[RasterisedPage], model: _FakeModel, tag: str
    ) -> Any:
        from unittest.mock import patch

        with patch.object(reader._client, "generate_structured", side_effect=model):
            return reader.read(
                pages, _scheme(), model=_HAIKU, extra_cache_key="k|bind1", task_tag=tag
            )

    def test_the_merge_reproduces_the_one_pass_read(self) -> None:
        pages = _pages()
        reader = ChunkedLabelReader(_client())
        self.assertTrue(reader.applies(pages, _HAIKU))
        merged = self._read(reader, pages, _FakeModel(pages), "extraction")
        expected = parse_stream_items(_truth(), page_count=_PAGES).items
        self.assertEqual(merged.items, expected)

    def test_overview_runs_once_for_both_reads_and_chunks_bypass_the_cache(self) -> None:
        pages = _pages()
        reader = ChunkedLabelReader(_client())
        model = _FakeModel(pages)
        self._read(reader, pages, model, "extraction")
        self._read(reader, pages, model, "binding_second_read")
        tags = [c["task_tag"] for c in model.calls]
        self.assertEqual(tags.count(OVERVIEW_TASK_TAG), 1)
        self.assertEqual(tags.count("extraction"), 4)
        self.assertEqual(tags.count("binding_second_read"), 4)
        self.assertTrue(all(c["cache_mode"] == "bypass" for c in model.calls))

    def test_chunks_are_told_the_map_and_their_place(self) -> None:
        pages = _pages()
        reader = ChunkedLabelReader(_client())
        model = _FakeModel(pages)
        self._read(reader, pages, model, "extraction")
        second = next(c for c in model.calls if "pages 15 to 29" in c["user_prompt"])
        self.assertIn("page 16: 16", second["user_prompt"])
        self.assertIn("Image 0 is the last page of the previous part", second["user_prompt"])

    def test_not_applied_under_the_budget_or_off_claude(self) -> None:
        pages = _pages()
        self.assertFalse(ChunkedLabelReader(_client(budget=95_000)).applies(pages, _HAIKU))
        self.assertFalse(ChunkedLabelReader(_client()).applies(pages, "gemini-3.8-flash"))

    def test_applies_decides_from_headers_without_fitting_or_encoding(self) -> None:
        from unittest.mock import patch

        pages = _pages()
        reader = ChunkedLabelReader(_client())
        with (
            patch("lemely.io.llm.image_fit._encode") as encode,
            patch("lemely.io.binding.chunked_read.fit") as fit,
        ):
            self.assertTrue(reader.applies(pages, _HAIKU))
            self.assertFalse(ChunkedLabelReader(_client(budget=95_000)).applies(pages, _HAIKU))
        encode.assert_not_called()
        fit.assert_not_called()

    def test_overview_thumbnails_are_not_enhanced_before_the_provider_fit(self) -> None:
        from unittest.mock import patch

        pages = _pages()
        reader = ChunkedLabelReader(_client())
        reader._client._settings.gemini.claude_image_enhance = True
        with patch("lemely.io.binding.chunked_read.thumbnails", return_value=(b"t",)) as thumbs:
            self._read(reader, pages, _FakeModel(pages), "extraction")
        self.assertFalse(thumbs.call_args.kwargs["enhance"])


class _OverviewModel(_FakeModel):
    """A model whose overview answer is chosen by the test, optionally held open."""

    def __init__(self, pages: list[RasterisedPage], overview: PageMap) -> None:
        super().__init__(pages)
        self.overview = overview
        self.entered = threading.Event()
        self.second_entered = threading.Event()
        self.release = threading.Event()
        self.hold = False

    def __call__(self, **kwargs: Any) -> Any:
        if kwargs["task_tag"] == OVERVIEW_TASK_TAG:
            self.calls.append(kwargs)
            if self.entered.is_set():
                self.second_entered.set()
            self.entered.set()
            if self.hold:
                self.release.wait(timeout=10)
            return self.overview
        return super().__call__(**kwargs)


def _true_map() -> PageMap:
    return PageMap(pages=[PageEntry(page=p, labels=[f"{p + 1}"]) for p in range(_PAGES)])


class OverviewLockTests(unittest.TestCase):
    def test_two_concurrent_reads_make_one_overview_call(self) -> None:
        from unittest.mock import patch

        pages = _pages()
        reader = ChunkedLabelReader(_client())
        model = _OverviewModel(pages, _true_map())
        model.hold = True
        with patch.object(reader._client, "generate_structured", side_effect=model):
            threads = [
                threading.Thread(
                    target=reader.read,
                    args=(pages, _scheme()),
                    kwargs={"model": _HAIKU, "extra_cache_key": "k", "task_tag": tag},
                )
                for tag in ("extraction", "binding_second_read")
            ]
            threads[0].start()
            self.assertTrue(model.entered.wait(timeout=10))
            threads[1].start()
            # Without the lock the second read reaches the overview call while the first holds it.
            model.second_entered.wait(timeout=1.5)
            model.release.set()
            for t in threads:
                t.join(timeout=30)
        tags = [c["task_tag"] for c in model.calls]
        self.assertEqual(tags.count(OVERVIEW_TASK_TAG), 1)


class OverviewValidationTests(unittest.TestCase):
    def _chunk_prompts(self, overview: PageMap) -> list[str]:
        from unittest.mock import patch

        pages = _pages()
        reader = ChunkedLabelReader(_client())
        model = _OverviewModel(pages, overview)
        with patch.object(reader._client, "generate_structured", side_effect=model):
            merged = reader.read(
                pages, _scheme(), model=_HAIKU, extra_cache_key="k", task_tag="extraction"
            )
        self.assertEqual(len(merged.items), 2 * _PAGES)
        return [c["user_prompt"] for c in model.calls if c["task_tag"] != OVERVIEW_TASK_TAG]

    def test_a_map_that_does_not_cover_the_pages_exactly_narrows_nothing(self) -> None:
        def listed(prompt: str) -> int:
            return sum(1 for line in prompt.splitlines() if re.match(r"- \S+ \[\d+ marks?\]", line))

        whole = listed(build_label_binding_user_prompt(_scheme(), page_count=1))
        one_based = PageMap(pages=[PageEntry(page=p + 1, labels=["1"]) for p in range(_PAGES)])
        duplicate = PageMap(pages=[*_true_map().pages, PageEntry(page=3, labels=["2"])])
        missing = PageMap(pages=_true_map().pages[:-1])
        out_of_range = PageMap(pages=[*_true_map().pages[:-1], PageEntry(page=99, labels=["1"])])
        for bad in (one_based, duplicate, missing, out_of_range):
            for prompt in self._chunk_prompts(bad):
                self.assertNotIn("Page map of the whole script", prompt)
                self.assertEqual(listed(prompt), whole)
        from lemely.io.prompts.label_binding import _printed_labels

        first = _printed_labels(_scheme())[0][0]
        good = self._chunk_prompts(
            PageMap(pages=[PageEntry(page=p, labels=[first]) for p in range(_PAGES)])
        )
        self.assertTrue(all("Page map of the whole script" in p for p in good))
        self.assertLess(listed(good[0]), whole)

    def test_narrowing_keeps_the_scheme_neighbours_of_a_mapped_label(self) -> None:
        from lemely.io.prompts.label_binding import _printed_labels

        scheme = _scheme()
        printed = [label for label, _ in _printed_labels(scheme)]
        mid = len(printed) // 2
        prompt = build_label_binding_user_prompt(scheme, page_count=3, labels=[printed[mid]])
        for label in printed[mid - 1 : mid + 2]:
            self.assertIn(f"- {label} [", prompt)
        self.assertNotIn(f"- {printed[mid + 3]} [", prompt)

    def test_overlap_page_items_are_counted_as_drops(self) -> None:
        from unittest.mock import patch

        pages = _pages()
        reader = ChunkedLabelReader(_client())
        model = _OverviewModel(pages, _true_map())
        with patch.object(reader._client, "generate_structured", side_effect=model):
            merged = reader.read(
                pages, _scheme(), model=_HAIKU, extra_cache_key="k", task_tag="extraction"
            )
        self.assertEqual(merged.drops.get("overlap_page"), 2 * 3)

    def test_media_resolution_reaches_the_chunk_calls(self) -> None:
        from unittest.mock import patch

        pages = _pages()
        reader = ChunkedLabelReader(_client())
        model = _OverviewModel(pages, _true_map())
        with patch.object(reader._client, "generate_structured", side_effect=model):
            reader.read(
                pages,
                _scheme(),
                model=_HAIKU,
                media_resolution="medium",
                extra_cache_key="k",
                task_tag="extraction",
            )
        chunk_calls = [c for c in model.calls if c["task_tag"] != OVERVIEW_TASK_TAG]
        self.assertTrue(chunk_calls)
        self.assertTrue(all(c["media_resolution"] == "medium" for c in chunk_calls))


class BinderDispatchTests(unittest.TestCase):
    def test_label_binder_uses_the_chunked_read_when_it_applies(self) -> None:
        from unittest.mock import patch

        pages = _pages()
        client = _client()
        model = _FakeModel(pages)
        binder = LabelBinder(client, chunked=ChunkedLabelReader(client))
        with patch.object(client, "generate_structured", side_effect=model):
            read = binder.read(
                pages, _scheme(), uploads=None, model=_HAIKU, extra_cache_key="k|bind1"
            )  # type: ignore[arg-type]
        self.assertEqual(len(read.items), 2 * _PAGES)
        self.assertIn(OVERVIEW_TASK_TAG, [c["task_tag"] for c in model.calls])


class PromptLabelTests(unittest.TestCase):
    def test_labels_narrow_the_list_and_none_leaves_it_whole(self) -> None:
        from lemely.io.prompts.label_binding import build_label_binding_user_prompt

        scheme = _scheme()
        whole = build_label_binding_user_prompt(scheme, page_count=3)
        self.assertEqual(whole, build_label_binding_user_prompt(scheme, page_count=3, labels=None))
        self.assertEqual(
            whole, build_label_binding_user_prompt(scheme, page_count=3, labels=["zz"])
        )
        narrow = build_label_binding_user_prompt(scheme, page_count=3, labels=["1"])
        self.assertLess(len(narrow), len(whole))
