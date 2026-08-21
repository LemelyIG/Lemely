"""Synthetic handwritten exam-answer scan generator.

Produces realistic-looking scanned PDF pages from plain-text student answers,
for use as accuracy-harness test fixtures (feeding Gemini vision extraction in
later steps). Pure image/PDF generation — no network calls, no Gemini.
"""

from __future__ import annotations

import functools
import json
import math
import random
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

import numpy as np
from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from lemely.data import DATA_DIR

if TYPE_CHECKING:
    from pathlib import Path

_FONT_FILES: Final[dict[str, str]] = {
    "Caveat": "Caveat-Regular.ttf",
    "IndieFlower": "IndieFlower-Regular.ttf",
    "PatrickHand": "PatrickHand-Regular.ttf",
}

_FONT_DIR: Final[Path] = DATA_DIR / "fonts" / "handwriting"

# Per-glyph fallback for codepoints the (cursive, Latin-only) handwriting
# fonts lack — Greek letters and math symbols that appear in physics/maths
# mark schemes (theta, pi, capital omega, plus/minus, degree, ...).
_MATH_FALLBACK_FONT_FILE: Final[str] = "NotoSansMath-Subset.ttf"
_MATH_FALLBACK_FONT_PATH: Final[Path] = _FONT_DIR / _MATH_FALLBACK_FONT_FILE

_MARGIN: Final[int] = 60
_LABEL_FONT_SIZE: Final[int] = 22
_BASE_ANSWER_FONT_SIZE: Final[int] = 34
_LINE_SPACING: Final[int] = 46
_LINE_GAP: Final[int] = 6
_BLOCK_GAP: Final[int] = 30
# Jitter applied to the answer font size in `_draw_handwritten_line`
# (`rng.uniform(_JITTER_MIN, _JITTER_MAX)`). Wrap-width measurement uses the
# top of this range so a line can never wrap narrower than it might render.
_JITTER_MIN: Final[float] = 0.9
_JITTER_MAX: Final[float] = 1.1

# Transparent margin added around the rasterized text before rotation, and
# the maximum absolute rotation angle applied to each line
# (`rng.uniform(-_MAX_ROTATION_DEG, _MAX_ROTATION_DEG)`) in
# `_draw_handwritten_line`. Both are named constants (not locals) because the
# layout pass needs them too, to reserve the render overhead they introduce
# before the fidelity check ever sees it — see `_max_render_overhead` below.
_RENDER_PAD: Final[int] = 10
_MAX_ROTATION_DEG: Final[float] = 2.0

# Vertical jitter applied to each line's paste position
# (`rng.randint(-_Y_JITTER_PX, _Y_JITTER_PX)`) in `_draw_handwritten_line`.
# Named for the same reason as `_RENDER_PAD`/`_MAX_ROTATION_DEG`: the layout
# pass's bottom-edge reservation (`_max_rendered_line_height`) must add this
# in, since a positive draw can push `bottom` past what the rotated image's
# own height would otherwise account for, and the page's initial/post-break
# cursor start must add it in too, since a negative draw can push `top`
# to a smaller y than `_MARGIN` — i.e. outside the usable text box.
_Y_JITTER_PX: Final[int] = 4


class RenderFidelityError(Exception):
    """Raised when the synthetic renderer cannot faithfully reproduce the input.

    Covers three failure modes, all caught before any PDF bytes are written:
    a glyph with no available font (would silently rasterize as ``.notdef``),
    ink that falls outside the page's usable text box, and two rendered lines
    whose pasted bounding boxes overlap (visual overprint).
    """


@functools.cache
def _font_cmap(font_path: str) -> frozenset[int]:
    """Return the set of Unicode codepoints *font_path* has a real glyph for."""
    ttfont = TTFont(font_path, lazy=True)
    try:
        cmap = ttfont.getBestCmap() or {}
        return frozenset(cmap.keys())
    finally:
        ttfont.close()


def _font_path_for_char(ch: str, primary_font_path: Path) -> Path:
    """Pick whichever vendored font actually has a glyph for *ch*.

    Tries *primary_font_path* (the handwriting font) first, then the shared
    math/Greek fallback subset. Raises `RenderFidelityError` if neither font
    has the glyph, rather than letting it silently rasterize as `.notdef`.
    """
    codepoint = ord(ch)
    if codepoint in _font_cmap(str(primary_font_path)):
        return primary_font_path
    if codepoint in _font_cmap(str(_MATH_FALLBACK_FONT_PATH)):
        return _MATH_FALLBACK_FONT_PATH
    raise RenderFidelityError(
        f"no vendored font has a glyph for {ch!r} (U+{codepoint:04X}); "
        f"tried {primary_font_path.name} and {_MATH_FALLBACK_FONT_PATH.name}"
    )


@dataclass(frozen=True)
class AnswerBlock:
    """One student answer to render onto a synthetic scan page."""

    question_id: str  # e.g. "1a_i" — matches mark-scheme question ids
    text: str  # the student's handwritten answer text (can be multi-line)


def render_handwritten_scan(
    answers: list[AnswerBlock],
    out_pdf: Path,
    *,
    font_name: str = "Caveat",
    seed: int = 0,
    page_size: tuple[int, int] = (1240, 1754),
) -> None:
    """Render *answers* onto one or more page images and save as a multi-page PDF."""
    if not answers:
        raise ValueError("answers must not be empty")
    if font_name not in _FONT_FILES:
        raise ValueError(f"font_name must be one of {sorted(_FONT_FILES)}, got {font_name!r}")

    rng = random.Random(seed)
    np_rng = np.random.default_rng(seed)
    font_path = _FONT_DIR / _FONT_FILES[font_name]

    pages = _lay_out_pages(answers, font_path, page_size, rng)
    noisy_pages = [_apply_scan_noise(page, rng, np_rng) for page in pages]
    rgb_pages = [page.convert("RGB") for page in noisy_pages]

    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    # Pillow's PDF writer otherwise embeds the current wall-clock time and a
    # /Title derived from the output filename, both of which would make the
    # PDF bytes non-deterministic for a given seed. Pin them so that
    # byte-identical output only depends on the rendered content.
    rgb_pages[0].save(
        out_pdf,
        "PDF",
        save_all=True,
        append_images=rgb_pages[1:],
        resolution=150.0,
        title="lemely-synthetic-scan",
        creationDate=time.gmtime(0),
        modDate=time.gmtime(0),
    )


def write_golden_case(
    case_dir: Path,
    mark_scheme_json: str,
    answers_json: dict[str, object],
    scan_answers: list[AnswerBlock],
    *,
    font_name: str = "Caveat",
    seed: int = 0,
) -> None:
    """Create case_dir/{mark_scheme.json, answers.json, scan.pdf}.

    This is the golden-case directory layout consumed by
    ``lemely.accuracy.harness.load_golden_cases``.
    """
    case_dir.mkdir(parents=True, exist_ok=True)
    (case_dir / "mark_scheme.json").write_text(mark_scheme_json, encoding="utf-8")
    (case_dir / "answers.json").write_text(json.dumps(answers_json), encoding="utf-8")
    render_handwritten_scan(
        scan_answers,
        case_dir / "scan.pdf",
        font_name=font_name,
        seed=seed,
    )


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------


def _new_page(page_size: tuple[int, int]) -> Image.Image:
    return Image.new("RGB", page_size, "white")


_AnyFont = ImageFont.ImageFont | ImageFont.FreeTypeFont


@functools.cache
def _load_font(font_path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(font_path, size)


def _segment_into_font_runs(
    text: str, primary_font_path: Path, size: int
) -> list[tuple[str, ImageFont.FreeTypeFont]]:
    """Split *text* into consecutive runs sharing one resolved font.

    Each run is paired with that font loaded at *size*. Used identically by
    the wrap-width measurement (`_wrap_line`) and the renderer
    (`_draw_handwritten_line`) so their glyph metrics — and therefore their
    notion of a line's width — can never disagree.
    """
    runs: list[tuple[str, ImageFont.FreeTypeFont]] = []
    current_chars = ""
    current_font_path: Path | None = None
    for ch in text:
        resolved_path = _font_path_for_char(ch, primary_font_path)
        if resolved_path == current_font_path:
            current_chars += ch
        else:
            if current_chars and current_font_path is not None:
                runs.append((current_chars, _load_font(str(current_font_path), size)))
            current_font_path = resolved_path
            current_chars = ch
    if current_chars and current_font_path is not None:
        runs.append((current_chars, _load_font(str(current_font_path), size)))
    return runs


def _measure_text(draw: ImageDraw.ImageDraw, text: str, font: _AnyFont) -> tuple[int, int]:
    bbox = draw.textbbox((0, 0), text, font=font)
    return round(bbox[2] - bbox[0]), round(bbox[3] - bbox[1])


def _measure_run_widths(draw: ImageDraw.ImageDraw, text: str, font_path: Path, size: int) -> int:
    """Sum per-run glyph widths for *text*.

    Resolves each run's font exactly the way `_draw_handwritten_line` does — see
    `_segment_into_font_runs`. Measuring and drawing must agree on the font for
    every run, or wrapping is computed against different glyph widths than the
    ones that get rendered.
    """
    runs = _segment_into_font_runs(text, font_path, size)
    return sum(round(draw.textlength(run_text, font=font)) for run_text, font in runs)


def _wrap_line(
    draw: ImageDraw.ImageDraw, text: str, font_path: Path, size: int, max_width: int
) -> list[str]:
    """Greedily wrap *text* (a single paragraph, no newlines) to *max_width* pixels."""
    words = text.split(" ")
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        width = _measure_run_widths(draw, candidate, font_path, size)
        if width <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _wrap_answer_text(
    draw: ImageDraw.ImageDraw, text: str, font_path: Path, size: int, max_width: int
) -> list[str]:
    """Wrap multi-line answer text, preserving explicit blank lines.

    *size* must be the maximum possible jitter size
    (``_BASE_ANSWER_FONT_SIZE * _JITTER_MAX``) so wrap decisions never
    underestimate how wide a line can render — `_draw_handwritten_line` picks
    its actual size independently, up to that same maximum. Each candidate
    line is measured per-glyph-font-run (via `_segment_into_font_runs`),
    matching exactly how `_draw_handwritten_line` resolves fonts, so a
    fallback-glyph-dense line can never wrap narrower than it renders.
    """
    all_lines: list[str] = []
    for paragraph in text.split("\n"):
        if not paragraph.strip():
            all_lines.append("")
            continue
        all_lines.extend(_wrap_line(draw, paragraph, font_path, size, max_width))
    return all_lines


def _draw_handwritten_line(
    page: Image.Image,
    text: str,
    font_path: Path,
    x: int,
    y: int,
    rng: random.Random,
    page_size: tuple[int, int],
) -> tuple[int, int]:
    """Render *text* with jitter, then paste onto *page*.

    Each character is drawn with whichever vendored font actually has its
    glyph (the handwriting font, falling back to the math/Greek subset);
    see `_font_path_for_char`. Raises `RenderFidelityError` if no font has a
    glyph for some character, or if the rendered ink would fall outside the
    page's usable text box on any of its four edges (`_MARGIN` to
    `page_width/height - _MARGIN`).

    Returns the (top, bottom) y-extent of the pasted ink on *page*, so the
    caller can advance its cursor by the line's actual rendered height
    instead of a fixed spacing constant, and can check for overlap against
    the previous line.
    """
    page_width, page_height = page_size
    size = max(1, round(_BASE_ANSWER_FONT_SIZE * rng.uniform(_JITTER_MIN, _JITTER_MAX)))

    runs = _segment_into_font_runs(text, font_path, size)

    probe = Image.new("RGBA", (1, 1))
    probe_draw = ImageDraw.Draw(probe)
    ascent = max(font.getmetrics()[0] for _, font in runs)
    descent = max(font.getmetrics()[1] for _, font in runs)
    run_widths = [round(probe_draw.textlength(run_text, font=font)) for run_text, font in runs]

    pad = _RENDER_PAD
    width = pad * 2 + sum(run_widths)
    height = pad * 2 + ascent + descent

    text_img = Image.new("RGBA", (width, height), (255, 255, 255, 0))
    text_draw = ImageDraw.Draw(text_img)
    ink = (rng.randint(0, 30), rng.randint(0, 30), rng.randint(20, 70), 255)
    baseline_y = pad + ascent
    cursor_x = pad
    for (run_text, font), run_width in zip(runs, run_widths, strict=True):
        text_draw.text((cursor_x, baseline_y), run_text, font=font, fill=ink, anchor="ls")
        cursor_x += run_width

    angle = rng.uniform(-_MAX_ROTATION_DEG, _MAX_ROTATION_DEG)
    rotated = text_img.rotate(angle, expand=True, resample=Image.Resampling.BICUBIC)

    y_offset = rng.randint(-_Y_JITTER_PX, _Y_JITTER_PX)
    top = y + y_offset
    bottom = top + rotated.height
    right = x + rotated.width
    if x < _MARGIN:
        raise RenderFidelityError(
            f"line ink extends past the left text-box edge: {text!r} (x={x}, limit={_MARGIN})"
        )
    if top < _MARGIN:
        raise RenderFidelityError(
            f"line ink extends past the top text-box edge: {text!r} (top={top}, limit={_MARGIN})"
        )
    if right > page_width - _MARGIN:
        raise RenderFidelityError(
            f"line ink extends past the right text-box edge: {text!r} "
            f"(right={right}, limit={page_width - _MARGIN})"
        )
    if bottom > page_height - _MARGIN:
        raise RenderFidelityError(
            f"line ink extends past the bottom text-box edge: {text!r} "
            f"(bottom={bottom}, limit={page_height - _MARGIN})"
        )

    page.paste(rotated, (x, top), rotated)
    return top, bottom


def _max_horizontal_render_overhead(font: ImageFont.FreeTypeFont) -> int:
    """Upper bound on how much wider a rendered line can be than its raw text width.

    `_draw_handwritten_line` pads the rasterized text by `_RENDER_PAD` on
    each side, then rotates the padded image by up to `_MAX_ROTATION_DEG`
    with `expand=True`. For a W x H rectangle rotated by angle theta, the
    expanded width is `W*cos(theta) + H*sin(theta)`, which is at most
    `W + H*sin(theta)` since `cos(theta) <= 1`. So the extra width beyond the
    raw text run width is at most `2*_RENDER_PAD` (the padding) plus
    `H*sin(_MAX_ROTATION_DEG)`, where `H` is the padded text-image height at
    *font*'s size. The wrap budget in `_lay_out_pages` must reserve exactly
    this much, or the wrap decision and the right-edge fidelity check in
    `_draw_handwritten_line` disagree. Rounded up (ceil) so the reserved
    headroom can never be an underestimate.
    """
    ascent, descent = font.getmetrics()
    padded_height = 2 * _RENDER_PAD + ascent + descent
    rotation_overhead = padded_height * math.sin(math.radians(_MAX_ROTATION_DEG))
    return math.ceil(2 * _RENDER_PAD + rotation_overhead)


def _max_rendered_line_height(font: ImageFont.FreeTypeFont, max_line_width: int) -> int:
    """Upper bound on the rendered height of a line, mirroring the width bound above.

    The expanded height after rotation is at most `H + W*sin(_MAX_ROTATION_DEG)`,
    where `H` is the padded text-image height at *font*'s size and `W` is
    bounded by *max_line_width* (the widest a wrapped line is ever allowed to
    render, post horizontal-overhead reservation). On top of that,
    `_draw_handwritten_line` nudges the paste position down by up to
    `_Y_JITTER_PX` (`bottom = top + y_offset + rotated.height`), so that must
    be reserved too. The page-break decision in `_lay_out_pages` must reserve
    this much room before drawing a line, or a line that should simply flow
    onto the next page instead trips the bottom-edge fidelity check in
    `_draw_handwritten_line`. Rounded up (ceil) so the reserved headroom can
    never be an underestimate.
    """
    ascent, descent = font.getmetrics()
    padded_height = 2 * _RENDER_PAD + ascent + descent
    rotation_overhead = max_line_width * math.sin(math.radians(_MAX_ROTATION_DEG))
    return math.ceil(padded_height + rotation_overhead + _Y_JITTER_PX)


def _lay_out_pages(
    answers: list[AnswerBlock],
    font_path: Path,
    page_size: tuple[int, int],
    rng: random.Random,
) -> list[Image.Image]:
    page_width, page_height = page_size
    full_usable_width = page_width - 2 * _MARGIN
    bottom_limit = page_height - _MARGIN

    label_font = ImageFont.load_default(size=_LABEL_FONT_SIZE)
    # Wrap at the maximum possible jittered size so `_wrap_line`'s width
    # measurement can never be narrower than what `_draw_handwritten_line`
    # might actually render (which draws at up to `_JITTER_MAX` x base size).
    max_jitter_size = max(1, round(_BASE_ANSWER_FONT_SIZE * _JITTER_MAX))
    wrap_font = ImageFont.truetype(str(font_path), max_jitter_size)

    # `_draw_handwritten_line` pastes padded, rotated ink whose bounding box
    # is wider/taller than the raw text it measures. Reserve that overhead
    # here so the wrap decision and the fidelity checks in
    # `_draw_handwritten_line` always agree — otherwise a line that just fits
    # the wrap budget can still fail the right- or bottom-edge check once
    # padding and rotation are applied.
    horizontal_overhead = _max_horizontal_render_overhead(wrap_font)
    usable_width = full_usable_width - horizontal_overhead
    max_line_height = _max_rendered_line_height(wrap_font, full_usable_width)

    pages: list[Image.Image] = []
    page = _new_page(page_size)
    draw = ImageDraw.Draw(page)
    # Start below `_MARGIN` by `_Y_JITTER_PX`: `_draw_handwritten_line` can
    # nudge a line's paste position up by up to `_Y_JITTER_PX`
    # (`y_offset = rng.randint(-_Y_JITTER_PX, _Y_JITTER_PX)`), and the top-
    # edge fidelity check requires `top >= _MARGIN` — so the cursor a line is
    # drawn at must never itself sit at exactly `_MARGIN`.
    cursor_y = _MARGIN + _Y_JITTER_PX
    last_line_bbox: tuple[int, int] | None = None

    for block in answers:
        label_text = f"Q{block.question_id}"
        _, label_height = _measure_text(draw, label_text, label_font)
        # Reserve room for the label plus the tallest a handwritten line can
        # render (`max_line_height`), not the fixed `_LINE_SPACING` — a
        # jittered, rotated line can render well past `_LINE_SPACING` tall
        # (see `_max_rendered_line_height`), and a label with no answer line
        # room left after it would otherwise sit orphaned at a page bottom.
        if cursor_y + label_height + max_line_height > bottom_limit:
            pages.append(page)
            page = _new_page(page_size)
            draw = ImageDraw.Draw(page)
            cursor_y = _MARGIN + _Y_JITTER_PX
            last_line_bbox = None
        draw.text((_MARGIN, cursor_y), label_text, font=label_font, fill=(20, 20, 20))
        cursor_y += label_height + 14
        last_line_bbox = None

        for line in _wrap_answer_text(draw, block.text, font_path, max_jitter_size, usable_width):
            # Reserve the true max rendered line height here, not the fixed
            # `_LINE_SPACING` — at max jitter plus padding plus rotation a
            # line can render far taller than `_LINE_SPACING`
            # (see `_max_rendered_line_height`), so checking against
            # `_LINE_SPACING` alone let lines that should have flowed onto
            # the next page instead trip the bottom-edge fidelity check in
            # `_draw_handwritten_line`.
            if cursor_y + max_line_height > bottom_limit:
                pages.append(page)
                page = _new_page(page_size)
                draw = ImageDraw.Draw(page)
                cursor_y = _MARGIN + _Y_JITTER_PX
                last_line_bbox = None
            if line:
                top, bottom = _draw_handwritten_line(
                    page, line, font_path, _MARGIN, cursor_y, rng, page_size
                )
                if last_line_bbox is not None:
                    overlap = min(last_line_bbox[1], bottom) - max(last_line_bbox[0], top)
                    if overlap > 0:
                        raise RenderFidelityError(
                            f"consecutive rendered lines overlap: "
                            f"{last_line_bbox} vs {(top, bottom)} for {line!r}"
                        )
                last_line_bbox = (top, bottom)
                # Advance by the line's actual rendered height, not the fixed
                # `_LINE_SPACING` assumption — jitter can render up to
                # `_JITTER_MAX` x base size, which `_LINE_SPACING` alone does
                # not account for.
                cursor_y = bottom + _LINE_GAP
            else:
                cursor_y += _LINE_SPACING

        cursor_y += _BLOCK_GAP

    pages.append(page)
    return pages


# ---------------------------------------------------------------------------
# Scan-noise augmentation
# ---------------------------------------------------------------------------


def _apply_scan_noise(
    page: Image.Image,
    rng: random.Random,
    np_rng: np.random.Generator,
) -> Image.Image:
    """Apply deterministic scan-artifact noise to *page* using the seeded RNGs."""
    angle = rng.uniform(-3.0, 3.0)
    rotated = page.rotate(angle, expand=False, fillcolor="white")

    blur_radius = rng.uniform(0.3, 0.8)
    blurred = rotated.filter(ImageFilter.GaussianBlur(radius=blur_radius))

    arr = np.asarray(blurred).astype(np.float32)
    sigma = rng.uniform(3.0, 8.0)
    noise = np_rng.normal(0.0, sigma, arr.shape)
    noisy_arr = np.clip(arr + noise, 0, 255).astype(np.uint8)
    noisy = Image.fromarray(noisy_arr, mode="RGB")

    brightness_factor = rng.uniform(0.95, 1.05)
    brightened = ImageEnhance.Brightness(noisy).enhance(brightness_factor)
    contrast_factor = rng.uniform(0.95, 1.05)
    return ImageEnhance.Contrast(brightened).enhance(contrast_factor)
