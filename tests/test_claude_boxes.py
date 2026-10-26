"""Claude answer boxes: asked for as pixels, converted to the 0-1000 convention in code.

Haiku drifts from the 0-1000 ``[ymin, xmin, ymax, xmax]`` the binder prompt names to pixels
of the image it sees (.superpowers/sdd/c-box-scale.md). A Claude read is therefore asked for
``[x_min, y_min, x_max, y_max]`` pixels, each page's label states its size, and
``box_convention.convert_reply`` converts the reply with the size of the image it sent.
Coordinates here are synthetic. A Gemini request, key and prompt do not move.
"""

from __future__ import annotations

import base64
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

from PIL import Image
from structlog.testing import capture_logs

from lemely.core.loose_schemas import MarkScheme
from lemely.io.binding.chunked_read import ChunkedLabelReader
from lemely.io.binding.label_binder import LabelBinder, _StreamOutput, box_contract
from lemely.io.gemini import GeminiClient, _reset_process_counters, record_calls
from lemely.io.llm import box_convention
from lemely.io.llm.box_convention import convert_reply, image_size
from lemely.io.llm.request import (
    PAGE_LABEL_SIZED_VERSION,
    PAGE_LABEL_VERSION,
    LLMRequest,
    provider_fingerprint,
)
from lemely.io.prompts.label_binding import (
    CLAUDE_BOX_ADDENDUM,
    CLAUDE_BOX_VERSION,
    LABEL_BINDING_SYSTEM_PROMPT,
    with_claude_boxes,
)
from lemely.io.providers import ProviderError
from lemely.io.providers.anthropic_adapter import labelled_pictures
from lemely.io.rasterise import RasterisedPage
from tests.gemini_fakes import make_settings
from tests.test_anthropic_adapter import _FakeAnthropic, _message, _settings
from tests.test_chunked_read import _client as _chunk_client
from tests.test_chunked_read import _FakeModel
from tests.test_chunked_read import _pages as _chunk_pages

_HAIKU = "claude-haiku-5-5"
_GEMINI = "gemini-3-flash-preview"
_ROOT = Path(__file__).resolve().parents[1]
_PORTRAIT = (1554, 2200)


def _scheme() -> MarkScheme:
    path = _ROOT / "corpus" / "mark-schemes" / "0625_w24_ms_41.json"
    return MarkScheme.model_validate(json.loads(path.read_text(encoding="utf-8")))


def _reply(*boxes: list[float], page: int = 0, labels: int = 0) -> str:
    """A binder reply: the first ``labels`` boxes are label items, the rest answers."""
    items = [
        {"type": "label" if i < labels else "answer", "page": page, "box": box}
        for i, box in enumerate(boxes)
    ]
    return json.dumps({"items": items})


def _boxes(text: str) -> list[list[int]]:
    return [item["box"] for item in json.loads(text)["items"]]


class PixelToNormalisedTests(unittest.TestCase):
    def test_pixel_xyxy_on_a_portrait_page_becomes_yxyx_on_0_1000(self) -> None:
        text, stats = convert_reply(_reply([777, 660, 1554, 1100]), [_PORTRAIT])
        self.assertEqual(_boxes(text), [[300, 500, 500, 1000]])
        self.assertEqual(stats.by_convention, {"pixel_xyxy": 1})
        self.assertEqual(stats.dropped, 0)

    def test_a_reply_wrapped_in_prose_and_fences_is_converted_too(self) -> None:
        wrapped = "Here you go:\n```json\n" + _reply([777, 660, 1554, 1100]) + "\n```\nDone."
        text, stats = convert_reply(wrapped, [_PORTRAIT])
        self.assertEqual(_boxes(text), [[300, 500, 500, 1000]])
        self.assertEqual(stats.unparsed, 0)

    def test_a_reply_with_no_json_is_counted_as_unparsed(self) -> None:
        text, stats = convert_reply("I could not read the page.", [_PORTRAIT])
        self.assertEqual(text, "I could not read the page.")
        self.assertEqual(stats.unparsed, 1)
        self.assertEqual(stats.log_fields()["unparsed"], 1)

    def test_the_size_used_is_that_of_the_page_the_box_is_on(self) -> None:
        items = [
            {"type": "answer", "page": 0, "box": [100, 200, 300, 400]},
            {"type": "answer", "page": 1, "box": [100, 200, 300, 400]},
        ]
        text, _ = convert_reply(json.dumps({"items": items}), [(1000, 2000), (500, 400)])
        self.assertEqual(_boxes(text), [[100, 100, 200, 300], [500, 200, 1000, 600]])

    def test_a_box_a_little_over_the_page_edge_is_clamped(self) -> None:
        text, _ = convert_reply(_reply([1500, 2000, 1560, 2210]), [_PORTRAIT])
        self.assertEqual(_boxes(text), [[909, 965, 1000, 1000]])

    def test_the_legacy_readers_source_box_is_converted_too(self) -> None:
        reply = json.dumps(
            {
                "answers": [
                    {"question_id": "1", "source_box": {"page": 0, "box": [777, 660, 1554, 1100]}}
                ]
            }
        )
        text, _ = convert_reply(reply, [_PORTRAIT])
        self.assertEqual(json.loads(text)["answers"][0]["source_box"]["box"], [300, 500, 500, 1000])

    def test_a_reply_without_boxes_or_json_comes_back_as_it_was(self) -> None:
        self.assertEqual(convert_reply("not json", [_PORTRAIT])[0], "not json")
        bare = json.dumps({"answers": [{"question_id": "1", "source_box": None}]})
        self.assertEqual(convert_reply(bare, [_PORTRAIT])[0], bare)

    def test_a_box_on_a_page_that_was_not_sent_is_dropped(self) -> None:
        text, stats = convert_reply(_reply([1, 2, 30, 40], page=3), [_PORTRAIT])
        self.assertEqual(_boxes(text), [[]])
        self.assertEqual((stats.malformed, stats.dropped), (1, 0))

    def test_empty_and_malformed_boxes_are_counted_apart_from_convention_drops(self) -> None:
        reply = json.dumps(
            {
                "items": [
                    {"type": "answer", "page": 0, "box": []},
                    {"type": "answer", "page": 0, "box": [1, 2, 3]},
                    {"type": "answer", "page": 0, "box": [3000, 3000, 4000, 4000]},
                    {"type": "answer", "page": 0, "box": [777, 660, 1554, 1100]},
                ]
            }
        )
        _, stats = convert_reply(reply, [_PORTRAIT])
        self.assertEqual((stats.boxes, stats.malformed, stats.dropped), (4, 2, 1))
        self.assertEqual(stats.log_fields()["malformed"], 2)

    def test_numeric_strings_and_floats_are_read_as_numbers(self) -> None:
        text, stats = convert_reply(_reply(["777", 660.0, "1554", 1100]), [_PORTRAIT])  # type: ignore[list-item]
        self.assertEqual(_boxes(text), [[300, 500, 500, 1000]])
        self.assertEqual(stats.malformed, 0)
        _, bad = convert_reply(_reply(["a", 1, 2, 3]), [_PORTRAIT])  # type: ignore[list-item]
        self.assertEqual(bad.malformed, 1)


class DriftTests(unittest.TestCase):
    def test_a_coordinate_past_the_width_can_only_be_y_so_the_order_is_read_from_it(self) -> None:
        # [y, x, y, x] in pixels: slot 0 is 1800, past the 1554 width, so it is not an x.
        text, stats = convert_reply(_reply([1800, 100, 1900, 400]), [_PORTRAIT])
        self.assertEqual(_boxes(text), [[818, 64, 864, 257]])
        self.assertEqual(stats.by_convention, {"pixel_yxyx": 1})

    def test_boxes_that_fit_every_order_take_the_order_the_decided_ones_agree_on(self) -> None:
        # The first box is decided yxyx (1800 > width); the second fits both orders.
        text, stats = convert_reply(
            _reply([1800, 100, 1900, 400], [220, 100, 440, 400]), [_PORTRAIT]
        )
        self.assertEqual(_boxes(text)[1], [100, 64, 200, 257])
        self.assertEqual(stats.by_convention, {"pixel_yxyx": 2})
        self.assertEqual(stats.ambiguous_kept, 1)

    def test_a_reply_that_mixes_orders_loses_the_boxes_it_cannot_place(self) -> None:
        text, stats = convert_reply(
            _reply([1800, 100, 1900, 400], [100, 1800, 400, 1900], [220, 100, 440, 400]),
            [_PORTRAIT],
        )
        self.assertEqual(_boxes(text), [[818, 64, 864, 257], [818, 64, 864, 257], []])
        self.assertTrue(stats.mixed_reply)
        self.assertEqual(stats.dropped, 1)

    def test_no_order_fits_so_the_box_is_dropped(self) -> None:
        text, stats = convert_reply(_reply([3000, 3000, 4000, 4000]), [_PORTRAIT])
        self.assertEqual(_boxes(text), [[]])
        self.assertEqual(stats.dropped, 1)

    def test_an_unordered_box_is_dropped(self) -> None:
        text, _ = convert_reply(_reply([500, 500, 400, 400]), [_PORTRAIT])
        self.assertEqual(_boxes(text), [[]])

    def _norm_reply(self, label_x: tuple[int, int], order: str) -> str:
        """Six boxes all under 1000 on a tall page; labels sit at x ~ ``label_x``."""
        rows = [(100, 250), (250, 400), (400, 550), (550, 700), (700, 850), (850, 950)]
        boxes: list[list[float]] = []
        for i, (top, bottom) in enumerate(rows):
            x0, x1 = (label_x[0], label_x[1]) if i < 4 else (300, 900)
            boxes.append([top, x0, bottom, x1] if order == "yxyx" else [x0, top, x1, bottom])
        return _reply(*boxes, labels=4)

    def test_a_zero_to_1000_yxyx_reply_is_kept_as_it_is(self) -> None:
        text, stats = convert_reply(self._norm_reply((40, 120), "yxyx"), [_PORTRAIT])
        self.assertTrue(stats.norm_reply)
        self.assertEqual(_boxes(text)[0], [100, 40, 250, 120])
        self.assertEqual(stats.by_convention, {"norm_yxyx": 6})

    def test_a_zero_to_1000_xyxy_reply_is_swapped_when_the_labels_say_so(self) -> None:
        text, stats = convert_reply(self._norm_reply((40, 120), "xyxy"), [_PORTRAIT])
        self.assertEqual(_boxes(text)[0], [100, 40, 250, 120])
        self.assertEqual(stats.by_convention, {"norm_xyxy": 6})

    def test_a_zero_to_1000_reply_with_no_clear_label_margin_loses_its_boxes(self) -> None:
        text, stats = convert_reply(self._norm_reply((400, 520), "yxyx"), [_PORTRAIT])
        self.assertTrue(stats.norm_reply)
        self.assertEqual(_boxes(text), [[]] * 6)
        self.assertEqual(stats.dropped, 6)

    def test_a_few_small_boxes_are_not_taken_for_a_zero_to_1000_reply(self) -> None:
        text, stats = convert_reply(_reply([100, 100, 300, 400], [100, 500, 300, 700]), [_PORTRAIT])
        self.assertFalse(stats.norm_reply)
        self.assertEqual(_boxes(text)[0], [45, 64, 182, 193])

    def _prefix_reply(self, prefix: list[list[float]], labels: int = 0) -> str:
        """``prefix`` boxes, then pixel boxes the first of which only fits pixel xyxy."""
        return _reply(*prefix, [100, 1800, 600, 1900], [100, 1900, 600, 2000], labels=labels)

    def test_a_zero_to_1000_prefix_before_pixels_is_read_as_0_1000(self) -> None:
        rows = [(100, 220), (250, 370), (400, 520), (550, 670), (700, 820), (850, 960)]
        prefix = [[top, 40, bottom, 120] for top, bottom in rows]  # yxyx; labels at the left
        text, stats = convert_reply(self._prefix_reply(prefix, labels=6), [_PORTRAIT])
        self.assertEqual(_boxes(text)[0], [100, 40, 220, 120])
        self.assertEqual(
            (stats.prefix_boxes, stats.prefix_norm, stats.prefix_dropped, stats.prefix_kept),
            (6, 6, 0, 0),
        )
        self.assertEqual(_boxes(text)[6], [818, 64, 864, 386])
        self.assertEqual(stats.by_convention["pixel_xyxy"], 2)

    def test_a_zero_to_1000_prefix_with_no_clear_order_is_dropped_not_shrunk(self) -> None:
        rows = [(100, 220), (250, 370), (400, 520), (550, 670), (700, 820), (850, 960)]
        prefix = [[top, 400, bottom, 520] for top, bottom in rows]
        text, stats = convert_reply(self._prefix_reply(prefix, labels=6), [_PORTRAIT])
        self.assertEqual(_boxes(text)[:6], [[]] * 6)
        self.assertEqual((stats.prefix_boxes, stats.prefix_dropped, stats.prefix_norm), (6, 6, 0))

    def test_a_prefix_that_reaches_past_1000_is_pixels(self) -> None:
        prefix = [[100, 100 * i, 300, 100 * i + 50] for i in range(1, 6)] + [[100, 1200, 300, 1250]]
        text, stats = convert_reply(self._prefix_reply(prefix), [_PORTRAIT])
        self.assertEqual(stats.prefix_kept, 6)
        self.assertEqual(_boxes(text)[0], [45, 64, 68, 193])
        self.assertEqual(stats.prefix_norm + stats.prefix_dropped, 0)

    def test_a_short_prefix_stays_pixels_and_is_counted(self) -> None:
        text, stats = convert_reply(self._prefix_reply([[100, 100, 300, 400]]), [_PORTRAIT])
        self.assertEqual(_boxes(text)[0], [45, 64, 182, 193])
        self.assertEqual((stats.prefix_boxes, stats.prefix_kept), (1, 1))

    def test_a_pure_pixel_reply_has_no_prefix(self) -> None:
        _, stats = convert_reply(_reply([100, 1800, 600, 1900], [100, 100, 300, 400]), [_PORTRAIT])
        self.assertEqual(stats.prefix_boxes, 0)

    def test_the_event_fields_are_counts_only(self) -> None:
        _, stats = convert_reply(
            _reply([777, 660, 1554, 1100], [3000, 3000, 4000, 4000]), [_PORTRAIT]
        )
        fields = stats.log_fields()
        self.assertEqual(fields["boxes"], 2)
        self.assertEqual(fields["pixel_xyxy"], 1)
        self.assertEqual(fields["dropped"], 1)
        self.assertTrue(all(isinstance(v, (int, bool)) for v in fields.values()))


class PromptContractTests(unittest.TestCase):
    def test_a_claude_model_gets_the_addendum_and_the_version(self) -> None:
        prompt, version = with_claude_boxes(LABEL_BINDING_SYSTEM_PROMPT, _HAIKU)
        self.assertEqual(prompt, LABEL_BINDING_SYSTEM_PROMPT + CLAUDE_BOX_ADDENDUM)
        self.assertEqual(version, CLAUDE_BOX_VERSION)
        self.assertIn("[x_min, y_min, x_max, y_max]", prompt)
        self.assertIn("W x H px", prompt)

    def test_gemini_and_a_non_name_get_the_prompt_unchanged(self) -> None:
        for model in (_GEMINI, "gemini-3.8-flash", MagicMock(), None):
            prompt, version = with_claude_boxes(LABEL_BINDING_SYSTEM_PROMPT, model)
            self.assertIs(prompt, LABEL_BINDING_SYSTEM_PROMPT)
            self.assertIsNone(version)

    def test_box_contract_resolves_the_model_from_the_tag_when_none_is_named(self) -> None:
        client = MagicMock()
        client.model_for_tag.return_value = _HAIKU
        prompt, kwargs = box_contract(client, "sys", model=None, task_tag="binding_second_read")
        client.model_for_tag.assert_called_once_with("binding_second_read")
        self.assertTrue(prompt.startswith("sys"))
        self.assertEqual(kwargs, {"box_convention": CLAUDE_BOX_VERSION})
        client.model_for_tag.return_value = _GEMINI
        self.assertEqual(box_contract(client, "sys", model=None, task_tag="x"), ("sys", {}))
        self.assertEqual(box_contract(client, "sys", model=_HAIKU, task_tag="x")[1] != {}, True)


_FP_KW: dict[str, Any] = {
    "max_output_tokens": 8192,
    "image_token_budget": 190_000,
    "image_floor_px": 1100,
    "image_enhance": True,
}


class FingerprintTests(unittest.TestCase):
    def test_gemini_adds_nothing_even_when_asked(self) -> None:
        self.assertEqual(
            provider_fingerprint(_GEMINI, **_FP_KW, image_count=19, box_convention="bx1"), ""
        )

    def test_a_pixel_box_request_carries_the_sized_label_and_box_versions(self) -> None:
        plain = provider_fingerprint(_HAIKU, **_FP_KW, image_count=19)
        boxed = provider_fingerprint(_HAIKU, **_FP_KW, image_count=19, box_convention="bx1")
        self.assertTrue(plain.endswith(f"|pg_lbl={PAGE_LABEL_VERSION}"))
        self.assertEqual(
            boxed, plain.removesuffix(f"|pg_lbl={PAGE_LABEL_VERSION}") + "|pg_lbl=v2|box=bx1"
        )
        self.assertEqual(PAGE_LABEL_SIZED_VERSION, "v2")

    def test_one_image_is_labelled_when_boxes_are_asked_for(self) -> None:
        plain = provider_fingerprint(_HAIKU, **_FP_KW, image_count=1)
        boxed = provider_fingerprint(_HAIKU, **_FP_KW, image_count=1, box_convention="bx1")
        self.assertNotIn("pg_lbl", plain)
        self.assertTrue(boxed.endswith("|pg_lbl=v2|box=bx1"))

    def test_the_request_uses_the_same_function(self) -> None:
        req = LLMRequest(
            model=_HAIKU, task_tag="extraction", system="s", prompt="p",
            response_schema=None, box_convention="bx1",
        )  # fmt: skip
        self.assertTrue(
            req.fingerprint(image_token_budget=1, image_floor_px=1, image_enhance=True).endswith(
                "|box=bx1"
            )
        )


def _png(width: int, height: int) -> bytes:
    buf = io.BytesIO()
    Image.new("L", (width, height), 255).save(buf, "PNG")
    return buf.getvalue()


class PageLabelTests(unittest.TestCase):
    def _blocks(self, n: int) -> list[Any]:
        return [{"type": "image", "source": {"type": "file", "file_id": f"f{i}"}} for i in range(n)]

    def test_sizes_label_every_picture_a_lone_one_too(self) -> None:
        out = labelled_pictures(self._blocks(1), [(1554, 2200)])
        self.assertEqual(out[0], {"type": "text", "text": "Page index 0 (1554 x 2200 px):"})
        self.assertEqual(len(out), 2)

    def test_sizes_are_stated_per_page(self) -> None:
        out = labelled_pictures(self._blocks(2), [(10, 20), (30, 40)])
        self.assertEqual(
            [b["text"] for b in out if b["type"] == "text"],
            ["Page index 0 (10 x 20 px):", "Page index 1 (30 x 40 px):"],
        )

    def test_without_sizes_the_label_is_what_it_was(self) -> None:
        self.assertEqual(len(labelled_pictures(self._blocks(1))), 1)
        out = labelled_pictures(self._blocks(2))
        self.assertEqual(out[0], {"type": "text", "text": "Page index 0:"})

    def test_sizes_that_do_not_match_the_pictures_are_refused(self) -> None:
        with self.assertRaises(ProviderError):
            labelled_pictures(self._blocks(2), [(1, 1)])


class CountTokensTests(unittest.TestCase):
    def test_the_preflight_count_labels_the_pages_with_their_sizes(self) -> None:
        from lemely.io.llm.claude_provider import ClaudeProvider
        from lemely.io.providers.anthropic_adapter import AnthropicAdapter

        fake = _FakeAnthropic()
        provider = ClaudeProvider(AnthropicAdapter(fake), make_settings(tempfile.mkdtemp()))  # type: ignore[arg-type]
        req = LLMRequest(
            model=_HAIKU, task_tag="extraction", system="s", prompt="p",
            response_schema=None, box_convention="bx1",
        )  # fmt: skip
        provider.count_tokens(req, images=(_png(30, 40), _png(50, 60)))
        content = fake.messages.count_calls[0]["messages"][0]["content"]
        self.assertEqual(
            [b["text"] for b in content if b["type"] == "text" and b["text"].startswith("Page")],
            ["Page index 0 (30 x 40 px):", "Page index 1 (50 x 60 px):"],
        )
        plain = LLMRequest(model=_HAIKU, task_tag="x", system="s", prompt="p", response_schema=None)
        provider.count_tokens(plain, images=(_png(30, 40), _png(50, 60)))
        labels = [
            b["text"]
            for b in fake.messages.count_calls[1]["messages"][0]["content"]
            if b["type"] == "text" and b["text"].startswith("Page")
        ]
        self.assertEqual(labels, ["Page index 0:", "Page index 1:"])


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.enterContext(record_calls())
        _reset_process_counters()

    def _claude_client(
        self, reply: str, *, files_api: bool, uploaded: dict[str, bytes] | None = None
    ) -> tuple[GeminiClient, _FakeAnthropic]:
        settings = _settings(self.tmp)
        settings = settings.model_copy(
            update={
                "gemini": settings.gemini.model_copy(
                    update={
                        "claude_files_api": files_api,
                        "max_output_tokens_for": {"extraction": 8192},
                    }
                )
            }
        )
        fake = _FakeAnthropic(_message(reply))
        if uploaded is not None:

            def upload(*, file: tuple[str, bytes, str], expires_in_seconds: int) -> Any:
                uploaded[file[0]] = file[1]
                return SimpleNamespace(id=file[0].removesuffix(".png"))

            fake.files = SimpleNamespace(upload=upload, delete=lambda _id: None)
        client = GeminiClient(settings, _genai_client=object(), _anthropic_client=fake, ledger=None)
        return client, fake

    def _pages(self, sizes: list[tuple[int, int]]) -> list[RasterisedPage]:
        return [
            RasterisedPage(index=i, width=w, height=h, png_bytes=_png(w, h), dpi=72.0)
            for i, (w, h) in enumerate(sizes)
        ]


# Two pages is over the many-images threshold, so the fit holds the long edge to 2576.
_FITTED = (1820, 2576)
# [777, 660, 1554, 1100] and [150, 200, 300, 260] px (x_min, y_min, x_max, y_max) on 1820 x 2576.
_ANSWER_BOX = [256, 427, 427, 854]
_LABEL_BOX = [78, 82, 101, 165]


# Real-size pages: the fit scales these down, so the label size is not the page size.
_SIZES = [(2430, 3439), (2430, 3439)]
_ITEMS: list[dict[str, Any]] = [
    {"type": "label", "page": 0, "box": [150, 200, 300, 260], "text": "1", "kind": "printed"},
    {
        "type": "answer",
        "page": 1,
        "box": [777, 660, 1554, 1100],
        "answer": "x",
        "confidence": 0.9,
        "placed_by": "position",
    },
]


class ClaudeReadTests(_Base):
    def _read(self, *, files_api: bool) -> tuple[Any, _FakeAnthropic, dict[str, bytes], list[Any]]:
        uploaded: dict[str, bytes] = {}
        client, fake = self._claude_client(
            json.dumps({"items": _ITEMS}), files_api=files_api, uploaded=uploaded
        )
        pages = self._pages(_SIZES)
        with (
            client.image_uploads([p.png_bytes for p in pages], concurrency=1) as uploads,
            capture_logs() as logs,
        ):
            read = LabelBinder(client).read(
                pages, _scheme(), uploads=uploads, model=_HAIKU, extra_cache_key="k"
            )
        return read, fake, uploaded, logs

    def _labels(self, fake: _FakeAnthropic) -> list[str]:
        (call,) = fake.messages.calls
        content = call["messages"][0]["content"]
        return [
            b["text"] for b in content if b["type"] == "text" and b["text"].startswith("Page index")
        ]

    def test_inline_the_label_size_is_the_size_of_the_image_sent_and_the_one_converted_by(
        self,
    ) -> None:
        read, fake, _, logs = self._read(files_api=False)
        (call,) = fake.messages.calls
        sent = [
            image_size(base64.b64decode(b["source"]["data"]))
            for b in call["messages"][0]["content"]
            if b["type"] == "image"
        ]
        self.assertEqual(sent, [_FITTED, _FITTED])  # the fit, not the 2430 x 3439 page
        self.assertEqual(
            self._labels(fake), [f"Page index {i} ({w} x {h} px):" for i, (w, h) in enumerate(sent)]
        )
        self.assertEqual(read.items[1].box, _ANSWER_BOX)
        self.assertEqual(read.items[0].box, _LABEL_BOX)
        (event,) = [e for e in logs if e["event"] == "box_convention"]
        self.assertEqual((event["boxes"], event["pixel_xyxy"], event["dropped"]), (2, 2, 0))
        self.assertEqual(event["version"], CLAUDE_BOX_VERSION)

    def test_on_the_files_api_the_label_size_is_the_size_of_the_uploaded_bytes(self) -> None:
        read, fake, uploaded, _ = self._read(files_api=True)
        sizes = [image_size(uploaded[f"page-{i}.png"]) for i in (1, 2)]
        self.assertEqual(sizes, [_FITTED, _FITTED])
        self.assertEqual(
            self._labels(fake),
            [f"Page index {i} ({w} x {h} px):" for i, (w, h) in enumerate(sizes)],
        )
        self.assertEqual(read.items[1].box, _ANSWER_BOX)

    def test_the_request_carries_the_addendum_and_the_key_the_read_was_cached_under(self) -> None:
        pages = self._pages(_SIZES)
        client, fake = self._claude_client(json.dumps({"items": _ITEMS}), files_api=False)
        binder = LabelBinder(client)
        with client.image_uploads([p.png_bytes for p in pages], concurrency=1) as uploads:
            binder.read(pages, _scheme(), uploads=uploads, model=_HAIKU, extra_cache_key="k")
        (call,) = fake.messages.calls
        system = "".join(b["text"] for b in call["system"])
        self.assertTrue(system.startswith(LABEL_BINDING_SYSTEM_PROMPT))
        self.assertIn(CLAUDE_BOX_ADDENDUM.strip(), system)
        key = binder.cache_key(pages, _scheme(), model=_HAIKU, extra_cache_key="k")
        self.assertTrue(client._cache_path(key).exists())
        # ... and it is not the key a read without the pixel contract would have.
        plain = client.structured_cache_key(
            system_prompt=LABEL_BINDING_SYSTEM_PROMPT,
            user_prompt=call["messages"][0]["content"][-1]["text"],
            image_parts=[p.png_bytes for p in pages],
            media_resolution="high",
            response_schema=_StreamOutput,
            prompt_version="3",
            model=_HAIKU,
            extra_cache_key="k",
            task_tag="extraction",
        )
        self.assertNotEqual(key, plain)

    def test_a_single_page_script_is_labelled_with_its_size_too(self) -> None:
        client, fake = self._claude_client(json.dumps({"items": _ITEMS[:1]}), files_api=False)
        pages = self._pages([(1655, 2339)])
        with client.image_uploads([p.png_bytes for p in pages], concurrency=1) as uploads:
            LabelBinder(client).read(
                pages, _scheme(), uploads=uploads, model=_HAIKU, extra_cache_key="k"
            )
        self.assertEqual(self._labels(fake), ["Page index 0 (1655 x 2339 px):"])


class ChunkedReadTests(unittest.TestCase):
    def test_every_chunk_read_asks_for_pixels(self) -> None:
        pages = _chunk_pages()
        reader = ChunkedLabelReader(_chunk_client())
        model = _FakeModel(pages)
        with patch.object(reader._client, "generate_structured", side_effect=model):
            reader.read(pages, _scheme(), model=_HAIKU, extra_cache_key="k", task_tag="extraction")
        chunks = [c for c in model.calls if c["task_tag"] == "extraction"]
        self.assertEqual(len(chunks), 4)
        for call in chunks:
            self.assertEqual(
                call["system_prompt"], LABEL_BINDING_SYSTEM_PROMPT + CLAUDE_BOX_ADDENDUM
            )
            self.assertEqual(call["box_convention"], CLAUDE_BOX_VERSION)
        overview = next(c for c in model.calls if c["task_tag"] != "extraction")
        self.assertNotIn("box_convention", overview)  # the overview asks for no boxes


class LegacyReaderTests(unittest.TestCase):
    def test_the_legacy_reader_asks_a_claude_model_for_pixels_and_a_gemini_one_as_before(
        self,
    ) -> None:
        from lemely.io.answer_extraction import GeminiAnswerExtractor
        from lemely.io.prompts.answer_extraction import EXTRACTOR_SYSTEM_PROMPT

        client = MagicMock()
        client.model_for_tag.return_value = _GEMINI
        extractor = GeminiAnswerExtractor(client)
        with patch("lemely.io.answer_extraction._convert_reply"):
            extractor._legacy_reply(_scheme(), [b"p"], MagicMock(), extra_cache_key="k")
            gemini_kwargs = client.generate_structured.call_args.kwargs
            extractor._legacy_reply(
                _scheme(), [b"p"], MagicMock(), extra_cache_key="k", model=_HAIKU
            )
            claude_kwargs = client.generate_structured.call_args.kwargs
        self.assertIs(gemini_kwargs["system_prompt"], EXTRACTOR_SYSTEM_PROMPT)
        self.assertNotIn("box_convention", gemini_kwargs)
        self.assertEqual(
            claude_kwargs["system_prompt"], EXTRACTOR_SYSTEM_PROMPT + CLAUDE_BOX_ADDENDUM
        )
        self.assertEqual(claude_kwargs["box_convention"], CLAUDE_BOX_VERSION)


# Cache keys of LabelBinder.cache_key on a Gemini model, three fake pages, the 0625_w24_ms_41
# scheme and extra_cache_key "k", computed from the tree at the commit before this change
# (git archive HEAD, PYTHONPATH pinned to it). A Gemini key must not move.
_GEMINI_KEYS_BEFORE = {
    (None, "extraction"): "277feb9ef2937c4e",
    (None, "binding_second_read"): "f3b5c9d2bc31edc4",
    (_GEMINI, "extraction"): "ca3385d8ff457a0b",
    (_GEMINI, "binding_second_read"): "53cec6db471b9319",
}


class GeminiUnchangedTests(unittest.TestCase):
    def _pages(self) -> list[RasterisedPage]:
        return [
            RasterisedPage(index=i, width=10, height=14, png_bytes=f"page-{i}".encode(), dpi=72.0)
            for i in range(3)
        ]

    def test_the_gemini_label_binding_cache_key_is_what_it_was(self) -> None:
        client = GeminiClient(
            make_settings(tempfile.mkdtemp()), _genai_client=object(), ledger=None
        )
        binder = LabelBinder(client)
        for (model, tag), before in _GEMINI_KEYS_BEFORE.items():
            with self.subTest(model=model, tag=tag):
                after = binder.cache_key(
                    self._pages(), _scheme(), model=model, extra_cache_key="k", task_tag=tag
                )
                self.assertEqual(after, before)

    def test_the_gemini_read_sends_the_same_call_it_always_did(self) -> None:
        client = MagicMock()
        client.model_for_tag.return_value = "gemini-3.8-flash"
        client.generate_structured.return_value = MagicMock(model_dump=lambda: {"items": []})
        LabelBinder(client).read(
            self._pages(), _scheme(), uploads=MagicMock(), model=None, extra_cache_key="k"
        )
        kwargs = client.generate_structured.call_args.kwargs
        self.assertIs(kwargs["system_prompt"], LABEL_BINDING_SYSTEM_PROMPT)
        self.assertNotIn("box_convention", kwargs)

    def test_the_gemini_request_carries_no_box_convention(self) -> None:
        client = GeminiClient(
            make_settings(tempfile.mkdtemp()), _genai_client=object(), ledger=None
        )
        req = client._build_request(
            model=_GEMINI, task_tag="extraction", system_prompt="s", user_prompt="p",
            response_schema=None, image_parts=[b"x"],
        )  # fmt: skip
        self.assertIsNone(req.box_convention)

    def test_gemini_never_goes_through_the_converter(self) -> None:
        self.assertIn("Gemini replies never pass through here", box_convention.__doc__ or "")
        provider_source = (_ROOT / "lemely" / "io" / "llm" / "gemini_provider.py").read_text()
        self.assertNotIn("box_convention", provider_source)


if __name__ == "__main__":
    unittest.main()
