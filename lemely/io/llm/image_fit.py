"""Fit page images under Claude's token and byte limits (spec 2026-10-19 §2).

Pure: Pillow only, no I/O, no SDK. The result is deterministic in the input bytes
and the constants below; ``IMG_FIT_VERSION`` goes into the Claude cache key, so a
policy change invalidates replies cached under the old one.

1. Greyscale every page (transparency composited onto white), for readability rather
   than size: tokens are ``w * h / 750`` whatever the colour.
2. Estimate tokens per page as ``w * h / 750``.
3. Step the long edge down (2576, 2200, 2000, 1800, then the floor) while the
   request is over ``token_budget`` or ``byte_limit``.
4. Stop at ``floor_px``: below it handwriting is treated as unreadable. Being over a
   budget there is reported in the result, never raised: the caller decides.

Each page is enhanced after it is resized to the chosen long edge, so sharpening acts at
the scale the model sees (:func:`enhance_page`): paper shading is divided out, the levels are
stretched so paper is white and ink dark, and a mild unsharp mask crisps strokes. There is
no thresholding: it would destroy faint pencil.
"""

from __future__ import annotations

import io
import math
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
from PIL import Image, ImageFilter, UnidentifiedImageError

from lemely.io.providers import ProviderError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from numpy.typing import NDArray

IMG_FIT_VERSION = "v3"
#: Cache-key version of the unenhanced variant (``fit(..., enhance=False)``): its pixels differ.
IMG_FIT_VERSION_PLAIN = "v3-plain"
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
_FAST_PNG_LEVEL = 1
_SMALL_PNG_LEVEL = 6
PIXELS_PER_TOKEN = 750

#: Paper shading is estimated on a page shrunk by this factor, so a 3 px stroke is mostly
#: averaged away and the local maximum below recovers the paper.
_BG_REDUCE = 16
#: Odd max-filter width in reduced pixels (about 110 px at full size): wider than a stroke
#: or a handwritten letter, so ink never counts as paper.
_BG_MAX_WINDOW = 7
#: Blur radius in reduced pixels that turns the blocky max-filter into smooth shading.
_BG_BLUR_RADIUS = 2.0
#: Percentile of the shrunk page taken as its own paper level: the bulk of a page is paper,
#: so this sits on it whatever shaded diagrams or dark edges there are.
_BG_PAPER_PERCENTILE = 90
#: The paper estimate may fall at most this many grey levels below the page's own paper
#: level. Scan shading and yellowing stay within it and are divided out; a solid region
#: darker than that (a shaded Venn region, a histogram bar, a filled diagram) is content, and
#: a window-wide one would otherwise be taken for paper and erased or hollowed out.
_MAX_SHADING_DROP = 30
#: Fraction of pixels clipped at each end of the levels stretch: enough to ignore dust and
#: the odd saturated pixel, small enough that sparse pencil does not become the clip.
_LEVELS_CLIP_LOW = 0.002
_LEVELS_CLIP_HIGH = 0.005
#: Below this ink-to-paper span (grey levels) the page is blank or noise, and stretching
#: would blow the noise up into fake writing; faint pencil on shaded paper sits above it.
_LEVELS_MIN_SPAN = 24
#: Unsharp mask radius in pixels at the final edge: about a pen stroke wide at 2000 px.
_SHARPEN_RADIUS = 1.3
#: Unsharp strength in percent: crisp edges without ringing around dense writing.
_SHARPEN_PERCENT = 80
#: Edges under this many grey levels are left alone, so paper grain is not sharpened.
_SHARPEN_THRESHOLD = 3


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


def estimate_tokens(width: int, height: int) -> int:
    """Claude's image-token estimate for a ``width`` x ``height`` image."""
    return math.ceil(width * height / PIXELS_PER_TOKEN)


def base64_len(n: int) -> int:
    """Length of ``n`` bytes once base64-encoded."""
    return 4 * math.ceil(n / 3)


def _background(grey: Image.Image) -> NDArray[np.float32]:
    """The paper level at every pixel of ``grey`` as floats: shading, yellowing, gradients."""
    reduced = grey.reduce(_BG_REDUCE)
    paper = float(np.percentile(np.asarray(reduced), _BG_PAPER_PERCENTILE))
    small = reduced.filter(ImageFilter.MaxFilter(_BG_MAX_WINDOW))
    smooth = small.filter(ImageFilter.GaussianBlur(_BG_BLUR_RADIUS))
    full = smooth.resize(grey.size, Image.Resampling.BILINEAR)
    return np.maximum(np.asarray(full, dtype=np.float32), max(1.0, paper - _MAX_SHADING_DROP))


def _stretch_levels(grey: Image.Image) -> Image.Image:
    """``grey`` with the darkest and lightest few pixels clipped and the rest spread out."""
    cumulative = np.cumsum(grey.histogram()) / (grey.width * grey.height)
    low = int(np.searchsorted(cumulative, _LEVELS_CLIP_LOW))
    high = int(np.searchsorted(cumulative, 1 - _LEVELS_CLIP_HIGH))
    if high - low < _LEVELS_MIN_SPAN:
        return grey
    scale = 255 / (high - low)
    return grey.point([min(255, max(0, round((v - low) * scale))) for v in range(256)])


def enhance_page(grey: Image.Image) -> Image.Image:
    """``grey`` (mode L) flattened, level-stretched and mildly sharpened for reading."""
    flat = np.clip(np.asarray(grey, dtype=np.float32) * (255 / _background(grey)), 0, 255)
    stretched = _stretch_levels(Image.fromarray(np.rint(flat).astype(np.uint8), "L"))
    return stretched.filter(
        ImageFilter.UnsharpMask(_SHARPEN_RADIUS, _SHARPEN_PERCENT, _SHARPEN_THRESHOLD)
    )


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


def _prepare(data: bytes, page: int, first_edge: int) -> Image.Image:
    """The page decoded as greyscale on white and held to ``first_edge``."""
    try:
        with Image.open(io.BytesIO(data)) as src:
            src.load()
            work = _on_white(src).convert("L")
        return _resized(work, first_edge)
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ProviderError(f"page {page} could not be read as an image: {exc}") from exc


def estimate_floor_tokens(images: Sequence[bytes], *, floor_px: int) -> int:
    """The tokens ``images`` come to at the floor size, read from headers (no pixel decode).

    Matches ``fit``'s last step: the same sizes, so ``> token_budget`` here is
    ``fit(...).over_token_budget`` without encoding a page.

    Raises:
        ProviderError: a page's header cannot be read (named by its 1-based number).
        ValueError: ``floor_px`` is less than 1.
    """
    if floor_px < 1:
        raise ValueError(f"floor_px must be positive, got {floor_px}")
    steps = steps_for(floor_px, len(images))
    total = 0
    for number, data in enumerate(images, start=1):
        try:
            with Image.open(io.BytesIO(data)) as src:
                width, height = src.size
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise ProviderError(f"page {number} could not be read as an image: {exc}") from exc
        total += estimate_tokens(*_size_at(*_size_at(width, height, steps[0]), steps[-1]))
    return total


def img_fit_version(*, enhance: bool = True) -> str:
    """The cache-key version for output made with or without enhancement."""
    return IMG_FIT_VERSION if enhance else IMG_FIT_VERSION_PLAIN


def _encode(
    page: Image.Image,
    long_edge: int,
    number: int,
    *,
    enhance: bool,
    compress_level: int = _SMALL_PNG_LEVEL,
) -> bytes:
    """``page`` at ``long_edge``, enhanced there unless ``enhance`` is False, as PNG bytes.

    ``compress_level`` trades size for save time; pixels are identical at every level.
    """
    try:
        out = io.BytesIO()
        sized = _resized(page, long_edge)
        (enhance_page(sized) if enhance else sized).save(out, "PNG", compress_level=compress_level)
    except (OSError, ValueError) as exc:
        raise ProviderError(f"page {number} could not be encoded: {exc}") from exc
    return out.getvalue()


def fit(
    images: Sequence[bytes],
    *,
    byte_limit: int | None = DEFAULT_BYTE_LIMIT,
    token_budget: int = DEFAULT_TOKEN_BUDGET,
    floor_px: int = DEFAULT_FLOOR_PX,
    enhance: bool = True,
    workers: int = 1,
) -> FittedImages:
    """``images`` greyscaled and stepped down until under both limits, or at the floor.

    ``byte_limit`` None means the images go by Files API id: no inline limit. ``enhance``
    False sends plain greyscale pages; pair it with :func:`img_fit_version` in cache keys.
    ``workers`` above 1 decodes and encodes pages on that many threads when there is no
    byte limit (each page is independent then); the output bytes are the same.

    Raises:
        ProviderError: a page cannot be read or encoded (named by its 1-based number).
        ValueError: ``floor_px`` is less than 1.
    """
    if floor_px < 1:
        raise ValueError(f"floor_px must be positive, got {floor_px}")
    steps = steps_for(floor_px, len(images))
    # No inline limit means Files API upload: bytes do not matter, save time does.
    level = _FAST_PNG_LEVEL if byte_limit is None else _SMALL_PNG_LEVEL
    parallel = byte_limit is None and workers > 1 and len(images) > 1
    pool = ThreadPoolExecutor(max_workers=min(workers, len(images))) if parallel else None
    try:
        return _fit_steps(
            images, steps, pool, byte_limit, token_budget, enhance=enhance, level=level
        )
    finally:
        if pool is not None:
            pool.shutdown()


def _fit_steps(
    images: Sequence[bytes],
    steps: tuple[int, ...],
    pool: ThreadPoolExecutor | None,
    byte_limit: int | None,
    token_budget: int,
    *,
    enhance: bool,
    level: int,
) -> FittedImages:
    """:func:`fit`'s step loop; ``pool`` (no byte limit only) runs the per-page work."""
    numbers = range(1, len(images) + 1)
    if pool is None:
        pages = [
            _prepare(data, number, steps[0]) for number, data in zip(numbers, images, strict=True)
        ]
    else:
        pages = list(pool.map(_prepare, images, numbers, [steps[0]] * len(images)))
    for edge in steps:
        page_tokens = tuple(estimate_tokens(*_size_at(p.width, p.height, edge)) for p in pages)
        tokens = sum(page_tokens)
        last = edge == steps[-1]
        if tokens > token_budget and not last:
            continue
        encoded_pages: list[bytes] = []
        b64 = 0
        if pool is not None:
            encoded_pages = list(
                pool.map(
                    lambda p, n, e=edge: _encode(p, e, n, enhance=enhance, compress_level=level),
                    pages,
                    numbers,
                )
            )
            b64 = sum(base64_len(len(e)) for e in encoded_pages)
        else:
            for n, p in enumerate(pages, start=1):
                encoded_pages.append(_encode(p, edge, n, enhance=enhance, compress_level=level))
                b64 += base64_len(len(encoded_pages[-1]))
                if not last and byte_limit is not None and b64 > byte_limit:
                    break  # already over: the remaining pages cannot bring this step back under
        encoded = tuple(encoded_pages)
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
            )
    raise AssertionError("unreachable: the last step always returns")  # pragma: no cover


def thumbnails(
    images: Sequence[bytes], *, long_edge: int = THUMBNAIL_LONG_EDGE, enhance: bool = True
) -> tuple[bytes, ...]:
    """Enhanced greyscale PNG thumbnails, ``long_edge`` on the long side, for an overview."""
    return tuple(
        _encode(_prepare(data, number, long_edge), long_edge, number, enhance=enhance)
        for number, data in enumerate(images, start=1)
    )
