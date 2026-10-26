"""Claude's answer boxes: read as pixels, stored as the 0-1000 ``[ymin, xmin, ymax, xmax]``.

Haiku does not keep to the 0-1000 box convention the binder prompt names. Measured on
one 19-page script, many of its boxes were pixels of the fitted image it was sent, in
either axis order, and the convention changed part-way through a reply
(.superpowers/sdd/c-box-scale.md). A pixel box near the top-left has every coordinate
under 1000, so ``SourceBox`` accepts it and the crop comes from the wrong place.

So a Claude request that asks for boxes asks for what the model falls back to anyway:
``[x_min, y_min, x_max, y_max]`` in pixels of the page image as sent, with that size in
the page's label (``anthropic_adapter.labelled_pictures``). :func:`convert_reply` turns
the reply into the stored convention, using the size of the image each box is on: the
provider passes the sizes it sent, so the size told to the model and the size used here
are one fact.

It is also a safety net. Each box is checked against the four conventions a reply can
drift into; a box that only one of them fits is converted as that one, and a reply that
mixes conventions loses the boxes it cannot place. A box that cannot be placed is
dropped (the item stays; boxes take no part in binding), never cropped blind.

Gemini replies never pass through here.
"""

from __future__ import annotations

import io
import json
import math
import statistics
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from PIL import Image

from lemely.io.providers.claude_schema import extract_json

if TYPE_CHECKING:
    from collections.abc import Sequence

Convention = Literal["pixel_xyxy", "pixel_yxyx", "norm_yxyx", "norm_xyxy"]
_CONVENTIONS: tuple[Convention, ...] = ("pixel_xyxy", "pixel_yxyx", "norm_yxyx", "norm_xyxy")

NORM = 1000
_KEY = "box"
#: A coordinate may overshoot its page by this share (a box drawn to the edge) and is clamped.
_OVERSHOOT = 1.02
#: Boxes a reply needs before "every coordinate under 1000" says it is 0-1000 and not pixels.
_MIN_BOXES_FOR_NORM_REPLY = 6
#: Pages whose long edge is under this are near enough 0-1000 that the two cannot be told apart.
_MIN_PAGE_EDGE_FOR_NORM_REPLY = 1300
#: Label boxes needed to tell the axis order of a reply from where its labels sit.
_MIN_LABELS_FOR_ORDER = 3
#: The left margin: the x_min of a label is under this on the 0-1000 scale.
_LABEL_MARGIN = 350
#: One order's label x_min median must be this many times smaller than the other's.
_LABEL_ORDER_RATIO = 2.0


def image_size(data: bytes) -> tuple[int, int]:
    """The (width, height) in pixels of an encoded image, from its header."""
    with Image.open(io.BytesIO(data)) as img:
        return img.size


@dataclass(slots=True)
class BoxStats:
    """What :func:`convert_reply` found; counts only, so it is safe to log."""

    boxes: int = 0
    by_convention: dict[str, int] = field(default_factory=dict)
    ambiguous_kept: int = 0
    dropped: int = 0
    #: Boxes that were empty, not four numbers, or on a page that was not sent.
    malformed: int = 0
    #: Undecided boxes before the reply's first decided pixel box, and how they were
    #: resolved: read as 0-1000, dropped, or kept as pixels.
    prefix_boxes: int = 0
    prefix_norm: int = 0
    prefix_dropped: int = 0
    prefix_kept: int = 0
    mixed_reply: bool = False
    norm_reply: bool = False
    #: Replies that held no JSON even after extraction, so their boxes (if any) stayed as sent.
    unparsed: int = 0

    def log_fields(self) -> dict[str, object]:
        """The fields of the ``box_convention`` log event."""
        return {
            "boxes": self.boxes,
            "pixel_xyxy": self.by_convention.get("pixel_xyxy", 0),
            "pixel_yxyx": self.by_convention.get("pixel_yxyx", 0),
            "norm_yxyx": self.by_convention.get("norm_yxyx", 0),
            "norm_xyxy": self.by_convention.get("norm_xyxy", 0),
            "ambiguous_kept": self.ambiguous_kept,
            "dropped": self.dropped,
            "malformed": self.malformed,
            "prefix_boxes": self.prefix_boxes,
            "prefix_norm": self.prefix_norm,
            "prefix_dropped": self.prefix_dropped,
            "prefix_kept": self.prefix_kept,
            "mixed_reply": self.mixed_reply,
            "norm_reply": self.norm_reply,
            "unparsed": self.unparsed,
        }


@dataclass(slots=True)
class _Ref:
    """One box in the reply: the mapping that holds it, its page, and what kind of item."""

    holder: dict[str, object]
    coords: list[float]
    width: int
    height: int
    is_label: bool


def _fits(convention: Convention, c: Sequence[float], width: int, height: int) -> bool:
    """Whether the four numbers are a positive-area box under ``convention`` on this page."""
    if not (c[0] < c[2] and c[1] < c[3]) or min(c) < 0:
        return False
    if convention == "pixel_xyxy":
        xs, ys = (c[0], c[2]), (c[1], c[3])
        return max(xs) <= width * _OVERSHOOT and max(ys) <= height * _OVERSHOOT
    if convention == "pixel_yxyx":
        ys, xs = (c[0], c[2]), (c[1], c[3])
        return max(xs) <= width * _OVERSHOOT and max(ys) <= height * _OVERSHOOT
    return max(c) <= NORM * _OVERSHOOT


def _scaled(value: float, extent: int) -> int:
    return min(NORM, max(0, round(value / extent * NORM)))


def _canonical(
    convention: Convention, c: Sequence[float], width: int, height: int
) -> list[int] | None:
    """``c`` as ``[ymin, xmin, ymax, xmax]`` on 0-1000, or None if it has no area there."""
    if convention == "pixel_xyxy":
        out = [
            _scaled(c[1], height),
            _scaled(c[0], width),
            _scaled(c[3], height),
            _scaled(c[2], width),
        ]
    elif convention == "pixel_yxyx":
        out = [
            _scaled(c[0], height),
            _scaled(c[1], width),
            _scaled(c[2], height),
            _scaled(c[3], width),
        ]
    elif convention == "norm_yxyx":
        out = [min(NORM, round(v)) for v in c]
    else:
        out = [min(NORM, round(v)) for v in (c[1], c[0], c[3], c[2])]
    return out if out[2] > out[0] and out[3] > out[1] else None


def _valid(c: Sequence[float], width: int, height: int) -> list[Convention]:
    return [k for k in _CONVENTIONS if _fits(k, c, width, height)]


def _norm_order(labels: Sequence[_Ref]) -> Convention | None:
    """The axis order of a 0-1000 reply from where its labels sit, or None if unclear.

    Printed labels sit in the left margin: whichever slot is the x_min, its median over
    the labels is small. The order whose x_min median is small and at least
    ``_LABEL_ORDER_RATIO`` times the other's is the reply's.
    """
    if len(labels) < _MIN_LABELS_FOR_ORDER:
        return None
    as_xyxy = statistics.median(ref.coords[0] for ref in labels)
    as_yxyx = statistics.median(ref.coords[1] for ref in labels)
    if as_yxyx <= _LABEL_MARGIN and as_xyxy >= _LABEL_ORDER_RATIO * max(as_yxyx, 1):
        return "norm_yxyx"
    if as_xyxy <= _LABEL_MARGIN and as_yxyx >= _LABEL_ORDER_RATIO * max(as_xyxy, 1):
        return "norm_xyxy"
    return None


def _collect(data: object, sizes: Sequence[tuple[int, int]]) -> tuple[list[_Ref], int]:
    """Every box in the reply, with its page's size; and how many could not be placed.

    The two reply shapes: the label binder's ``{"items": [{"page", "box", "type"}]}`` and
    the legacy reader's ``{"answers": [{"source_box": {"page", "box"}}]}``. A box whose page
    is not one of the sent images, or that is not four numbers, is unplaceable.
    """
    refs: list[_Ref] = []
    unplaceable = 0
    if not isinstance(data, dict):
        return refs, unplaceable
    # Each holder is the mapping that carries both the "page" and the "box".
    holders: list[tuple[dict[str, object], bool]] = []
    items = data.get("items")
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict) and "box" in item:
                holders.append((item, item.get("type") == "label"))
    answers = data.get("answers")
    if isinstance(answers, list):
        for answer in answers:
            if isinstance(answer, dict) and isinstance(answer.get("source_box"), dict):
                holders.append((answer["source_box"], False))
    for holder, is_label in holders:
        page, box = holder.get("page"), holder.get(_KEY)
        if (
            not isinstance(page, int)
            or isinstance(page, bool)
            or not 0 <= page < len(sizes)
            or not isinstance(box, list)
        ):
            unplaceable += 1
            _drop(holder)
            continue
        numbers = [_number(v) for v in box]
        coords = [v for v in numbers if v is not None]
        if len(box) != 4 or len(coords) != 4:
            unplaceable += 1
            _drop(holder)
            continue
        width, height = sizes[page]
        refs.append(_Ref(holder, coords, width, height, is_label))
    return refs, unplaceable


def _number(value: object) -> float | None:
    """``value`` as a finite number, or None. Numeric strings count, as in ``_coerce_box``."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        try:
            number = float(value)
        except ValueError:
            return None
    else:
        return None
    return number if math.isfinite(number) else None


def _drop(holder: dict[str, object]) -> None:
    """Take a box out of the reply: an empty list is no box to the parser (needs four numbers)."""
    holder[_KEY] = []


def _prefix_plan(
    refs: Sequence[_Ref],
    options: Sequence[Sequence[Convention]],
    evidence: set[Convention],
    stats: BoxStats,
) -> dict[int, Convention | None]:
    """The convention (None: drop) for each undecided box before the first decided pixel box.

    A reply that starts in 0-1000 and then drifts to pixels is the commonest drift: its
    first boxes fit every convention, so they would be read as pixels and land shrunk
    towards the top-left. They are told from a pure pixel reply by their reach: pixels
    go past 1000 on a tall page within a few boxes, so a prefix of at least
    ``_MIN_BOXES_FOR_NORM_REPLY`` boxes that never does is 0-1000. Its axis order is read
    from the prefix's labels (``_norm_order``), and the prefix is dropped when that is
    unclear. A shorter prefix, or one that reaches past 1000, stays as the reply's pixels.
    """
    if len(evidence) != 1 or not next(iter(evidence)).startswith("pixel"):
        return {}
    first = next(i for i, opts in enumerate(options) if len(opts) == 1)
    stats.prefix_boxes = first
    if first == 0:
        return {}
    head = refs[:first]
    tall = all(max(ref.width, ref.height) >= _MIN_PAGE_EDGE_FOR_NORM_REPLY for ref in head)
    if first >= _MIN_BOXES_FOR_NORM_REPLY and tall and all(max(ref.coords) <= NORM for ref in head):
        order = _norm_order([ref for ref in head if ref.is_label])
        return dict.fromkeys(range(first), order)
    return {i: next(iter(evidence)) for i in range(first)}


def convert_reply(text: str, sizes: Sequence[tuple[int, int]]) -> tuple[str, BoxStats]:
    """The reply ``text`` with every box on the 0-1000 ``[ymin, xmin, ymax, xmax]`` scale.

    ``sizes`` is the (width, height) of each image sent, by page index. The model was
    asked for ``[x_min, y_min, x_max, y_max]`` in pixels of those images. A reply that is
    not JSON, or holds no boxes, comes back as it was.

    Per box, the conventions it can be (``_fits``) decide:

    * only one fits: the box is that convention, whatever the reply asked for;
    * several fit (small coordinates fit them all): the box takes the convention of
      the reply's *decided* boxes when they agree on one (``pixel_xyxy``, the one asked
      for, when there are none), and is dropped when the reply mixes conventions;
    * none fits: dropped.

    A reply with no decided box whose every coordinate is under 1000, on pages that are
    taller than that, is a 0-1000 reply (pixels would reach further down the page): its
    axis order is read from where its labels sit (``_norm_order``), and its boxes are
    dropped when that is unclear.
    """
    stats = BoxStats()
    try:
        data = json.loads(text)
    except ValueError:
        # Prose or fences around the object: read it as the parse path does.
        try:
            data = json.loads(extract_json(text))
        except ValueError:
            stats.unparsed = 1
            return text, stats
    refs, unplaceable = _collect(data, sizes)
    stats.malformed = unplaceable
    stats.boxes = len(refs) + unplaceable
    if not refs:
        return (text, stats) if not unplaceable else (json.dumps(data), stats)

    options = [_valid(ref.coords, ref.width, ref.height) for ref in refs]
    evidence: set[Convention] = {opts[0] for opts in options if len(opts) == 1}
    stats.mixed_reply = len(evidence) > 1

    reply_default: Convention | None
    if len(evidence) == 1:
        reply_default = next(iter(evidence))
    elif evidence:
        reply_default = None
    else:
        reply_default = "pixel_xyxy"
        everything_small = all(max(ref.coords) <= NORM for ref in refs)
        tall = all(max(ref.width, ref.height) >= _MIN_PAGE_EDGE_FOR_NORM_REPLY for ref in refs)
        if everything_small and tall and len(refs) >= _MIN_BOXES_FOR_NORM_REPLY:
            stats.norm_reply = True
            reply_default = _norm_order([ref for ref in refs if ref.is_label])

    prefix = _prefix_plan(refs, options, evidence, stats)

    for index, (ref, opts) in enumerate(zip(refs, options, strict=True)):
        chosen: Convention | None = None
        if index in prefix:
            chosen = prefix[index]
        elif len(opts) == 1:
            chosen = opts[0]
        elif opts and reply_default in opts:
            chosen = reply_default
            stats.ambiguous_kept += 1
        box = _canonical(chosen, ref.coords, ref.width, ref.height) if chosen else None
        if chosen is None or box is None:
            stats.dropped += 1
            if index in prefix:
                stats.prefix_dropped += 1
            _drop(ref.holder)
            continue
        stats.by_convention[chosen] = stats.by_convention.get(chosen, 0) + 1
        if index in prefix:
            if chosen.startswith("norm"):
                stats.prefix_norm += 1
            else:
                stats.prefix_kept += 1
        ref.holder[_KEY] = box
    return json.dumps(data), stats
