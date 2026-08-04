"""Synthetic handwritten exam-answer scan generator.

Produces realistic-looking scanned PDF pages from plain-text student answers,
for use as accuracy-harness test fixtures (feeding Gemini vision extraction in
later steps). Pure image/PDF generation — no network calls, no Gemini.
"""

from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

import numpy as np
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

_MARGIN: Final[int] = 60
_LABEL_FONT_SIZE: Final[int] = 22
_BASE_ANSWER_FONT_SIZE: Final[int] = 34
_LINE_SPACING: Final[int] = 46
_BLOCK_GAP: Final[int] = 30


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


def _measure_text(draw: ImageDraw.ImageDraw, text: str, font: _AnyFont) -> tuple[int, int]:
    bbox = draw.textbbox((0, 0), text, font=font)
    return round(bbox[2] - bbox[0]), round(bbox[3] - bbox[1])


def _wrap_line(draw: ImageDraw.ImageDraw, text: str, font: _AnyFont, max_width: int) -> list[str]:
    """Greedily wrap *text* (a single paragraph, no newlines) to *max_width* pixels."""
    words = text.split(" ")
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        width, _ = _measure_text(draw, candidate, font)
        if width <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _wrap_answer_text(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int
) -> list[str]:
    """Wrap multi-line answer text, preserving explicit blank lines."""
    all_lines: list[str] = []
    for paragraph in text.split("\n"):
        if not paragraph.strip():
            all_lines.append("")
            continue
        all_lines.extend(_wrap_line(draw, paragraph, font, max_width))
    return all_lines


def _draw_handwritten_line(
    page: Image.Image,
    text: str,
    font_path: Path,
    x: int,
    y: int,
    rng: random.Random,
) -> None:
    """Render *text* in the handwriting font with jitter, then paste onto *page*."""
    size = max(1, round(_BASE_ANSWER_FONT_SIZE * rng.uniform(0.9, 1.1)))
    font = ImageFont.truetype(str(font_path), size)

    probe = Image.new("RGBA", (1, 1))
    probe_draw = ImageDraw.Draw(probe)
    bbox = probe_draw.textbbox((0, 0), text, font=font)
    pad = 10
    width = round((bbox[2] - bbox[0]) + pad * 2)
    height = round((bbox[3] - bbox[1]) + pad * 2)

    text_img = Image.new("RGBA", (width, height), (255, 255, 255, 0))
    text_draw = ImageDraw.Draw(text_img)
    ink = (rng.randint(0, 30), rng.randint(0, 30), rng.randint(20, 70), 255)
    text_draw.text((pad - bbox[0], pad - bbox[1]), text, font=font, fill=ink)

    angle = rng.uniform(-2.0, 2.0)
    rotated = text_img.rotate(angle, expand=True, resample=Image.Resampling.BICUBIC)

    y_offset = rng.randint(-4, 4)
    page.paste(rotated, (x, y + y_offset), rotated)


def _lay_out_pages(
    answers: list[AnswerBlock],
    font_path: Path,
    page_size: tuple[int, int],
    rng: random.Random,
) -> list[Image.Image]:
    page_width, page_height = page_size
    usable_width = page_width - 2 * _MARGIN
    bottom_limit = page_height - _MARGIN

    label_font = ImageFont.load_default(size=_LABEL_FONT_SIZE)
    wrap_font = ImageFont.truetype(str(font_path), _BASE_ANSWER_FONT_SIZE)

    pages: list[Image.Image] = []
    page = _new_page(page_size)
    draw = ImageDraw.Draw(page)
    cursor_y = _MARGIN

    for block in answers:
        label_text = f"Q{block.question_id}"
        _, label_height = _measure_text(draw, label_text, label_font)
        if cursor_y + label_height + _LINE_SPACING > bottom_limit:
            pages.append(page)
            page = _new_page(page_size)
            draw = ImageDraw.Draw(page)
            cursor_y = _MARGIN
        draw.text((_MARGIN, cursor_y), label_text, font=label_font, fill=(20, 20, 20))
        cursor_y += label_height + 14

        for line in _wrap_answer_text(draw, block.text, wrap_font, usable_width):
            if cursor_y + _LINE_SPACING > bottom_limit:
                pages.append(page)
                page = _new_page(page_size)
                draw = ImageDraw.Draw(page)
                cursor_y = _MARGIN
            if line:
                _draw_handwritten_line(page, line, font_path, _MARGIN, cursor_y, rng)
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
