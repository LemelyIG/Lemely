"""Label-free ``source_box`` plausibility proxy (US-017, label-free slice).

``US-006`` shipped ``source_box`` (:class:`lemely.core.schemas.SourceBox`) on
every extracted answer, but nothing checks that a box points at anything. The
story that would check it properly, ``US-017``, measures box *hit-rate*
against a gold transcription set that does not exist yet -- it needs
``US-008``'s human labelling. This module is the product owner's ruling:
build a label-free proxy now rather than wait for labels.

**What this measures, and what it does not.** The proxy rasterises the page
and computes the fraction of non-background ("ink") pixels inside the box.
That catches one specific failure: a box pointing at blank paper. It cannot
tell you the box points at the *right* answer -- only that it points at
*something*. That is a genuine **lower bound on box plausibility**, not a
hit-rate, and it does **not** replace the labelled hit-rate measurement
``US-017`` specifies. A box that passes this check can still be wrong; a box
that fails it is definitely wrong. Do not read a low blank rate from this
module as evidence the box hit-rate question is closed.

Geometry is delegated nowhere new: it mirrors
:func:`lemely.io.reread.crop_and_upscale`'s coordinate convention exactly (a
0-1000 scale ``[ymin, xmin, ymax, xmax]`` box against ``page.png_bytes``),
minus that function's padding and upscaling -- both exist to give the model a
better re-read image, not to measure what is already there.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL.Image import Image

    from lemely.core.schemas import ExtractedAnswer
    from lemely.io.rasterise import RasterisedPage

# Grayscale intensity below which a pixel counts as "ink" rather than
# background/paper -- the same threshold and rationale as
# ``lemely.io.scan_hygiene._INK_THRESHOLD``: 240, not 255, so anti-aliased
# pixel edges around strokes/print are counted as ink rather than excluded.
_INK_THRESHOLD: int = 240

# Measured against tests/fixtures/handwritten-59/0625_w24_qp_42.pdf (all 16
# pages, the real 0-text-character scan this proxy must run on): sampling
# genuinely blank margins (the outer 3% of page width on both sides, all 16
# pages, 32 samples) gave ink-pixel fractions of 0.0 up to a measured maximum
# of 0.00934 (one page's left margin picked up a faint scan artifact).
# Sampling an 8x8 grid of cells across all 16 pages showed non-blank
# (printed-content) cells climbing straight past that band -- the next
# fraction observed above the blank margins' ceiling was 0.0141, and content
# density only grows from there (up to 0.95 for a printed page-edge rule).
# 0.01 sits above every blank measurement with headroom and below the first
# non-blank one; it is a floor separating "no content" from "some content",
# not a finely tuned split -- recalibrate from a fresh measurement if the
# fixture or DPI changes.
_BLANK_INK_DENSITY_THRESHOLD: float = 0.01


def _crop_box_pixels(page: RasterisedPage, box: list[int]) -> Image | None:
    """Crop *box* out of *page* with no padding or upscaling.

    Returns ``None`` for a degenerate box: coordinates outside the
    documented 0-1000 range, or a box whose pixel-space area rounds to zero
    or less. Mirrors ``crop_and_upscale``'s pixel conversion exactly (matching
    its ``[ymin, xmin, ymax, xmax]`` axis order and rounding), but does not
    force a minimum 1px crop the way that function does -- a degenerate box
    here is a measurement failure to report, not something to paper over so
    an image can still be sent to the model.
    """
    from PIL import Image

    if len(box) != 4:
        return None
    ymin, xmin, ymax, xmax = box
    if not all(0 <= coord <= 1000 for coord in box):
        return None
    if ymax <= ymin or xmax <= xmin:
        return None

    image = Image.open(io.BytesIO(page.png_bytes)).convert("L")

    px_ymin = ymin / 1000 * page.height
    px_xmin = xmin / 1000 * page.width
    px_ymax = ymax / 1000 * page.height
    px_xmax = xmax / 1000 * page.width

    left = max(0, int(px_xmin))
    upper = max(0, int(px_ymin))
    right = min(page.width, round(px_xmax))
    lower = min(page.height, round(px_ymax))

    if right <= left or lower <= upper:
        return None

    return image.crop((left, upper, right, lower))


def box_ink_density(page: RasterisedPage, box: list[int]) -> float | None:
    """Fraction of non-background pixels inside ``box`` cropped from ``page``.

    ``box`` is ``[ymin, xmin, ymax, xmax]`` on the same 0-1000 scale as
    :class:`lemely.core.schemas.SourceBox.box`. Returns a value in ``[0, 1]``,
    or ``None`` when the box is degenerate (zero/negative area after
    rounding to pixels, or a coordinate outside ``[0, 1000]``) -- explicitly,
    rather than dividing by zero over an empty crop.

    This is plausibility, not correctness: a high ink density only says the
    box is not pointing at blank paper, not that it is pointing at the right
    answer. See the module docstring.
    """
    import numpy as np

    cropped = _crop_box_pixels(page, box)
    if cropped is None:
        return None
    arr = np.asarray(cropped)
    if arr.size == 0:
        return None
    return float((arr < _INK_THRESHOLD).mean())


@dataclass(frozen=True)
class BoxPlausibilityReport:
    """A paper-level roll-up of :func:`box_ink_density` over a set of answers.

    Every count here is stated explicitly rather than folded into a single
    rate, because a rate with an unstated (or silently shifting) denominator
    is exactly the defect class this measurement programme exists to remove:

    - ``total_answers``: every answer passed in, boxed or not.
    - ``boxes_considered``: answers with ``source_box is not None``. An
      answer with no box is not a plausibility failure -- mirroring
      ``lemely.io.reread.should_reread``, "no box" and "bad box" are
      distinct cases -- so it is excluded here, not counted as blank.
    - ``unmeasurable``: boxed answers that :func:`box_ink_density` could not
      score (a degenerate box, or a ``page`` index with no matching
      rasterised page). Counted separately rather than dropped silently or
      folded into ``blank``, which would misrepresent them as "points at
      blank paper" when they are actually unscoreable.
    - ``measurable``: ``boxes_considered - unmeasurable`` -- the true
      denominator for ``blank_rate``.
    - ``blank``: measurable boxes whose ink density fell below
      :data:`_BLANK_INK_DENSITY_THRESHOLD`.
    """

    total_answers: int
    boxes_considered: int
    unmeasurable: int
    blank: int

    @property
    def measurable(self) -> int:
        return self.boxes_considered - self.unmeasurable

    @property
    def blank_rate(self) -> float | None:
        """``blank / measurable``, or ``None`` when nothing was measurable.

        ``None`` rather than ``0.0`` -- a paper with zero measurable boxes
        has said nothing about box plausibility, which is a different
        statement from "every measured box was fine".
        """
        if self.measurable == 0:
            return None
        return self.blank / self.measurable


def paper_box_plausibility(
    answers: list[ExtractedAnswer],
    pages: list[RasterisedPage],
) -> BoxPlausibilityReport:
    """Roll up :func:`box_ink_density` over every boxed answer in *answers*.

    ``pages`` must be the rasterised pages the extraction ran against (or a
    superset); a box naming a page index not present in ``pages`` is counted
    as unmeasurable rather than raising. See :class:`BoxPlausibilityReport`
    for what each count means -- in particular, this is a lower bound on box
    plausibility, not the box hit-rate ``US-017`` ultimately specifies.
    """
    pages_by_index = {page.index: page for page in pages}

    boxes_considered = 0
    unmeasurable = 0
    blank = 0

    for answer in answers:
        box = answer.source_box
        if box is None:
            continue
        boxes_considered += 1

        page = pages_by_index.get(box.page)
        density = box_ink_density(page, box.box) if page is not None else None
        if density is None:
            unmeasurable += 1
        elif density < _BLANK_INK_DENSITY_THRESHOLD:
            blank += 1

    return BoxPlausibilityReport(
        total_answers=len(answers),
        boxes_considered=boxes_considered,
        unmeasurable=unmeasurable,
        blank=blank,
    )
