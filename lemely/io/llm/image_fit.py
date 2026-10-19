"""Fit page images under Claude's token and byte limits (spec 2026-10-19 §2).

Pure: Pillow only, no I/O, no SDK. The result is deterministic in the input bytes
and the constants below; ``IMG_FIT_VERSION`` goes into the Claude cache key, so a
policy change invalidates replies cached under the old one.

1. Greyscale every page, unless it carries meaningful colour (two or more ink
   colours, :func:`has_colour_ink`).
2. Estimate tokens per page as ``w * h / 750``.
3. Step the long edge down (2576, 2200, 2000, 1800, then the floor) while the
   request is over ``token_budget`` or ``byte_limit``.
4. Stop at ``floor_px``: below it handwriting is treated as unreadable. Being over a
   budget there is reported in the result, never raised: the caller decides.
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from PIL import Image, ImageChops, UnidentifiedImageError

from lemely.io.providers import ProviderError

if TYPE_CHECKING:
    from collections.abc import Sequence

IMG_FIT_VERSION = "v1"
LONG_EDGE_STEPS: tuple[int, ...] = (2576, 2200, 2000, 1800, 1568)
#: Above this many images in one request the API holds each to MANY_IMAGES_LONG_EDGE.
MANY_IMAGES_THRESHOLD = 20
MANY_IMAGES_LONG_EDGE = 2000
#: The 100k Haiku price-tier line, less headroom for the prompt.
DEFAULT_TOKEN_BUDGET = 95_000
#: Inline base64 bytes of images per request: the 32 MB request limit less room.
DEFAULT_BYTE_LIMIT = 30_000_000
#: About 135 DPI on A4.
DEFAULT_FLOOR_PX = 1568
THUMBNAIL_LONG_EDGE = 768
PIXELS_PER_TOKEN = 750

_GREY_MODES = frozenset({"1", "L", "LA", "I", "I;16", "F"})
_SATURATION_MIN = 90
_VALUE_MIN = 60
_HUE_FAMILIES = 6
#: Shift so that red (hue near 0 and near 255) falls in one family.
_HUE_SHIFT = 21
_HUE_FAMILY_MIN_SHARE = 0.001


@dataclass(frozen=True)
class FittedImages:
    """The pages as they will be sent, and what the fit found."""

    images: tuple[bytes, ...]
    long_edge: int
    est_tokens: int
    page_tokens: tuple[int, ...]
    base64_bytes: int
    over_token_budget: bool
    over_byte_limit: bool
    colour_pages: tuple[int, ...]


@dataclass(frozen=True)
class _Page:
    original: bytes
    image: Image.Image
    as_is: bool


def estimate_tokens(width: int, height: int) -> int:
    """Claude's image-token estimate for a ``width`` x ``height`` image."""
    return math.ceil(width * height / PIXELS_PER_TOKEN)


def base64_len(n: int) -> int:
    """Length of ``n`` bytes once base64-encoded."""
    return 4 * math.ceil(n / 3)


def has_colour_ink(img: Image.Image) -> bool:
    """True when two or more saturated hue families each cover 0.1% of the page.

    Measured at full resolution, with masks and histograms in Pillow's C code: shrinking
    the page first averages a 3 px pen stroke into paper and loses it.
    """
    hue, sat, val = img.convert("RGB").convert("HSV").split()
    if not any(sat.histogram()[_SATURATION_MIN:]):
        return False
    not_inked = ImageChops.invert(
        ImageChops.multiply(
            sat.point([255 if s >= _SATURATION_MIN else 0 for s in range(256)]),
            val.point([255 if v >= _VALUE_MIN else 0 for v in range(256)]),
        )
    )
    # Hue to family id; inked pixels keep it, the rest become 255 and fall outside 0..5.
    family_of = hue.point([((h + _HUE_SHIFT) % 256) * _HUE_FAMILIES // 256 for h in range(256)])
    counts = ImageChops.lighter(family_of, not_inked).histogram()[:_HUE_FAMILIES]
    total = img.width * img.height
    return sum(1 for c in counts if c / total >= _HUE_FAMILY_MIN_SHARE) >= 2


def steps_for(floor_px: int, count: int) -> tuple[int, ...]:
    """The long edges tried, largest first, ending at the floor."""
    start = MANY_IMAGES_LONG_EDGE if count > MANY_IMAGES_THRESHOLD else LONG_EDGE_STEPS[0]
    if floor_px >= start:
        return (start,)
    return (*(s for s in LONG_EDGE_STEPS if floor_px < s <= start), floor_px)


def _size_at(width: int, height: int, long_edge: int) -> tuple[int, int]:
    if max(width, height) <= long_edge:
        return width, height
    scale = long_edge / max(width, height)
    return max(1, round(width * scale)), max(1, round(height * scale))


def _resized(img: Image.Image, long_edge: int) -> Image.Image:
    size = _size_at(img.width, img.height, long_edge)
    if size == img.size:
        return img
    return img.resize(size, Image.Resampling.LANCZOS)


def _on_white(img: Image.Image) -> Image.Image:
    """``img`` composited onto white when it has transparency, so clear is not black."""
    if img.mode in ("LA", "RGBA", "PA") or "transparency" in img.info:
        rgba = img.convert("RGBA")
        base = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        return Image.alpha_composite(base, rgba)
    return img


def _prepare(
    data: bytes, page: int, first_edge: int, *, detect_colour: bool = True
) -> tuple[_Page, bool]:
    """The page decoded, greyscaled unless meaningful colour, held to ``first_edge``."""
    try:
        with Image.open(io.BytesIO(data)) as src:
            src.load()
            fmt = src.format
            if src.mode in _GREY_MODES:
                work, colour = _on_white(src).convert("L"), False
            else:
                rgb = _on_white(src).convert("RGB")
                colour = detect_colour and has_colour_ink(rgb)
                work = rgb if colour else rgb.convert("L")
            as_is = fmt == "PNG" and src.mode == ("RGB" if colour else "L")
            if max(work.size) > first_edge:
                work, as_is = _resized(work, first_edge), False
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ProviderError(f"page {page} could not be read as an image: {exc}") from exc
    return _Page(original=data, image=work, as_is=as_is), colour


def _encode(page: _Page, long_edge: int, number: int) -> bytes:
    if page.as_is and max(page.image.size) <= long_edge:
        return page.original
    try:
        out = io.BytesIO()
        _resized(page.image, long_edge).save(out, "PNG")
    except (OSError, ValueError) as exc:
        raise ProviderError(f"page {number} could not be encoded: {exc}") from exc
    return out.getvalue()


def fit(
    images: Sequence[bytes],
    *,
    byte_limit: int | None = DEFAULT_BYTE_LIMIT,
    token_budget: int = DEFAULT_TOKEN_BUDGET,
    floor_px: int = DEFAULT_FLOOR_PX,
) -> FittedImages:
    """``images`` greyscaled and stepped down until under both limits, or at the floor.

    ``byte_limit`` None means the images go by Files API id: no inline limit.

    Raises:
        ProviderError: a page cannot be read or encoded (named by its 1-based number).
        ValueError: ``floor_px`` is less than 1.
    """
    if floor_px < 1:
        raise ValueError(f"floor_px must be positive, got {floor_px}")
    steps = steps_for(floor_px, len(images))
    pages: list[_Page] = []
    colour_pages: list[int] = []
    for number, data in enumerate(images, start=1):
        page, colour = _prepare(data, number, steps[0])
        pages.append(page)
        if colour:
            colour_pages.append(number)
    for edge in steps:
        page_tokens = tuple(
            estimate_tokens(*_size_at(p.image.width, p.image.height, edge)) for p in pages
        )
        tokens = sum(page_tokens)
        last = edge == steps[-1]
        if tokens > token_budget and not last:
            continue
        encoded = tuple(_encode(p, edge, n) for n, p in enumerate(pages, start=1))
        b64 = sum(base64_len(len(e)) for e in encoded)
        over_tokens = tokens > token_budget
        over_bytes = byte_limit is not None and b64 > byte_limit
        if last or not (over_tokens or over_bytes):
            return FittedImages(
                images=encoded,
                long_edge=edge,
                est_tokens=tokens,
                page_tokens=page_tokens,
                base64_bytes=b64,
                over_token_budget=over_tokens,
                over_byte_limit=over_bytes,
                colour_pages=tuple(colour_pages),
            )
    raise AssertionError("unreachable: the last step always returns")  # pragma: no cover


def thumbnails(
    images: Sequence[bytes], *, long_edge: int = THUMBNAIL_LONG_EDGE
) -> tuple[bytes, ...]:
    """Greyscale PNG thumbnails, ``long_edge`` on the long side, for an overview pass."""
    out: list[bytes] = []
    for number, data in enumerate(images, start=1):
        page = _Page(
            original=data,
            image=_prepare(data, number, long_edge, detect_colour=False)[0].image.convert("L"),
            as_is=False,
        )
        out.append(_encode(page, long_edge, number))
    return tuple(out)
