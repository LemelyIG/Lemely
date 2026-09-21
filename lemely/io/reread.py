"""Crop-and-re-read: single-answer re-extraction from an upscaled crop of ``source_box`` (I1).

Triggered by low extraction confidence (and, once I3's ``SecondReader`` lands
and populates a cross-read agreement score on ``ExtractedAnswer``, by low
agreement too — that trigger is not wired here because the attribute does not
exist yet). Crops ``source_box`` plus 8% padding out of the page it names,
upscales it 2x, and resends it alone at ``media_resolution="high"`` with a
single-answer prompt — the point being to give the model a second, zoomed-in
look at exactly the pixels its own box says the answer lives in, rather than
re-running the whole-paper extraction again.
"""

from __future__ import annotations

import difflib
import io
from typing import TYPE_CHECKING

from pydantic import BaseModel

from lemely.io.prompts.answer_extraction import VERSION

if TYPE_CHECKING:
    from lemely.core.schemas import ExtractedAnswer
    from lemely.io.gemini import GeminiClient
    from lemely.io.rasterise import RasterisedPage

# "high" per the plan (medium is used for the whole-page extraction call;
# the re-read crop gets the model's best look).
REREAD_MEDIA_RESOLUTION = "high"

# Plan: "crop source_box + 8% padding from the page PNG, upscale 2x".
REREAD_PADDING_FRAC = 0.08
REREAD_UPSCALE = 2

# A calibrated confidence threshold would need a labelled sweep to justify
# (M2); this is a conservative placeholder that at least exercises the path
# on the extractor's own low-confidence band (see
# lemely.io.prompts.answer_extraction's 0.60 confidence-band boundary).
DEFAULT_CONFIDENCE_THRESHOLD = 0.60

# I1 review MUST-FIX/should-fix (finding 9): re-reads were uncapped -- a
# probe on a paper with 30 low-confidence answers issued 31 total API calls
# (1 primary + 30 re-reads), unbounded, against a $14 per-run ceiling with no
# visibility into how often that happens. A typical CIE paper carries on the
# order of 30 leaf questions; capping at half that bounds the worst case to a
# known, small number of extra calls per paper while still covering the
# large majority of a normally-scanned paper's low-confidence answers. A
# paper that needs more than this many re-reads is itself evidence of a bad
# scan (already surfaced by the T2.6 hygiene gate) rather than something
# more re-reads would fix. Not a ``lemely.toml`` setting (deliberately: I1's
# file boundaries exclude ``lemely/runtime/config.py``) -- override via
# ``GeminiAnswerExtractor(..., max_rereads_per_paper=...)`` instead, the same
# constructor-knob shape as ``reread_confidence_threshold``.
DEFAULT_MAX_REREADS_PER_PAPER = 15

REREAD_SYSTEM_PROMPT = """
You are re-reading a single cropped, upscaled image of one student's answer to
one exam question, extracted from a larger scanned page. Read only what is
visible in this crop and return the answer text exactly as you did the first
time, preserving units and standard form notation. If nothing legible is
present, return an empty string.
"""


class _RereadOutput(BaseModel):
    answer: str


def should_reread(
    answer: ExtractedAnswer, *, confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD
) -> bool:
    """True when ``answer`` should go through the crop-and-re-read step.

    There is nothing to crop without a box (spec: crop-and-re-read "has
    nothing to crop" without ``source_box`` -- B8 #3, the problem I1 exists
    to fix), so an answer with no box never triggers a re-read regardless of
    confidence.
    """
    if answer.source_box is None:
        return False
    return answer.confidence < confidence_threshold


def crop_and_upscale(
    page: RasterisedPage,
    box: list[int],
    *,
    padding_frac: float = REREAD_PADDING_FRAC,
    upscale: int = REREAD_UPSCALE,
) -> bytes:
    """Crop, pad and upscale ``box`` out of *page*, and return PNG bytes.

    ``box`` is on a 0-1000 scale, ``[ymin, xmin, ymax, xmax]``; padded by
    ``padding_frac`` of the box's own dimensions, then upscaled by
    ``upscale``x with Lanczos resampling.
    """
    from PIL import Image

    image = Image.open(io.BytesIO(page.png_bytes)).convert("RGB")
    ymin, xmin, ymax, xmax = box

    px_ymin = ymin / 1000 * page.height
    px_xmin = xmin / 1000 * page.width
    px_ymax = ymax / 1000 * page.height
    px_xmax = xmax / 1000 * page.width

    pad_y = (px_ymax - px_ymin) * padding_frac
    pad_x = (px_xmax - px_xmin) * padding_frac

    left = max(0, int(px_xmin - pad_x))
    upper = max(0, int(px_ymin - pad_y))
    right = min(page.width, round(px_xmax + pad_x))
    lower = min(page.height, round(px_ymax + pad_y))
    # A degenerate box (validated to have positive area by SourceBox, but
    # padding/rounding could still round two adjacent edges together on a
    # tiny box) must not be handed to PIL's crop as an empty or inverted
    # rectangle.
    right = max(right, left + 1)
    lower = max(lower, upper + 1)

    cropped = image.crop((left, upper, right, lower))
    new_size = (max(1, cropped.width * upscale), max(1, cropped.height * upscale))
    upscaled = cropped.resize(new_size, Image.Resampling.LANCZOS)

    buf = io.BytesIO()
    upscaled.save(buf, format="PNG")
    return buf.getvalue()


def _text_agreement(a: str, b: str) -> float:
    """Similarity in [0, 1] between the original and re-read answer text.

    A ``difflib``-based stand-in for I3's rapidfuzz normalised-Levenshtein
    agreement metric: I1 needs *a* number to store in ``reread_agreement``,
    not I3's specific algorithm, which ships with the ``SecondReader``
    protocol it is defined for and is a separate, dedicated story.
    """
    return difflib.SequenceMatcher(None, a, b).ratio()


class Rereader:
    """Runs the crop-and-re-read step for one low-confidence answer."""

    def __init__(self, gemini_client: GeminiClient) -> None:
        self._client = gemini_client

    def reread(
        self,
        answer: ExtractedAnswer,
        pages: list[RasterisedPage],
        *,
        extra_cache_key: str,
    ) -> ExtractedAnswer:
        """Crop, upscale and re-extract ``answer``'s ``source_box``.

        Returns a copy of ``answer`` with ``answer_reread``/``reread_agreement``
        populated. Raises :class:`ValueError` if ``answer.source_box`` is
        ``None`` -- callers must gate on :func:`should_reread` first.
        """
        box = answer.source_box
        if box is None:
            raise ValueError(f"cannot re-read {answer.question_id!r}: no source_box to crop")
        page = pages[box.page]
        crop_png = crop_and_upscale(page, box.box)

        result = self._client.generate_structured(
            system_prompt=REREAD_SYSTEM_PROMPT,
            user_prompt=(
                f"Re-read the cropped image for question {answer.question_id}. "
                f'Return JSON: {{"answer": "<the answer text>"}}.'
            ),
            image_parts=[crop_png],
            media_resolution=REREAD_MEDIA_RESOLUTION,
            response_schema=_RereadOutput,
            prompt_version=VERSION,
            extra_cache_key=(f"{extra_cache_key}:reread:{answer.question_id}:{box.page}:{box.box}"),
            task_tag="extraction",
        )
        agreement = _text_agreement(answer.answer, result.answer)
        return answer.model_copy(
            update={"answer_reread": result.answer, "reread_agreement": agreement}
        )
