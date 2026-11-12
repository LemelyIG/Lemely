"""Unit tests for lemely.io.box_plausibility (US-017, label-free slice).

Covers the ink-density plausibility proxy: a lower bound on box hit-rate
("does the box point at anything"), not the hit-rate itself ("does the box
point at the *right* thing", which needs US-008's gold transcriptions and is
not what this module measures).
"""

from __future__ import annotations

import io
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from lemely.core.schemas import ExtractedAnswer, SourceBox
from lemely.io.box_plausibility import (
    _BLANK_INK_DENSITY_THRESHOLD,
    BoxPlausibilityReport,
    box_ink_density,
    paper_box_plausibility,
)
from lemely.io.rasterise import RasterisedPage, rasterise_pdf_to_pages

_FIXTURE = Path(__file__).parent / "fixtures" / "handwritten-59" / "0625_w24_qp_42.pdf"


def _quadrant_page(width: int = 400, height: int = 400) -> RasterisedPage:
    """A synthetic page, blank except for a solid black square filling
    exactly the bottom-right quadrant (y in [200, 400), x in [200, 400))."""
    img = Image.new("RGB", (width, height), color="white")
    draw = ImageDraw.Draw(img)
    draw.rectangle([width // 2, height // 2, width - 1, height - 1], fill="black")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return RasterisedPage(index=0, width=width, height=height, png_bytes=buf.getvalue())


class BoxInkDensityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.page = _quadrant_page()

    def test_box_over_blank_region_scores_as_blank(self) -> None:
        # Top-left quadrant, [ymin, xmin, ymax, xmax] on the 0-1000 scale.
        box = [0, 0, 500, 500]
        density = box_ink_density(self.page, box)
        self.assertIsNotNone(density)
        assert density is not None
        self.assertLess(density, _BLANK_INK_DENSITY_THRESHOLD)

    def test_box_over_inked_region_does_not_score_as_blank(self) -> None:
        # Bottom-right quadrant, where the solid black square lives.
        box = [500, 500, 1000, 1000]
        density = box_ink_density(self.page, box)
        self.assertIsNotNone(density)
        assert density is not None
        self.assertGreaterEqual(density, _BLANK_INK_DENSITY_THRESHOLD)

    def test_coordinate_convention_selects_the_named_quadrant_not_its_transpose(self) -> None:
        # [ymin, xmin, ymax, xmax] = top-right quadrant: rows 0-500 (top),
        # columns 500-1000 (right). The black square is bottom-right, so
        # this box must NOT pick it up. Its transpose -- treating the box as
        # bottom-left instead -- would also miss the square, so this alone
        # doesn't pin the convention; paired with the bottom-right-quadrant
        # test above (which DOES require [ymin, xmin, ymax, xmax] read
        # correctly to hit the square), a transposed implementation fails
        # at least one of the two.
        top_right = [0, 500, 500, 1000]
        density = box_ink_density(self.page, top_right)
        self.assertIsNotNone(density)
        assert density is not None
        self.assertLess(density, _BLANK_INK_DENSITY_THRESHOLD)

    def test_zero_area_box_returns_none_rather_than_dividing_by_zero(self) -> None:
        self.assertIsNone(box_ink_density(self.page, [100, 100, 100, 100]))

    def test_out_of_range_box_returns_none(self) -> None:
        self.assertIsNone(box_ink_density(self.page, [-10, 0, 500, 500]))
        self.assertIsNone(box_ink_density(self.page, [0, 0, 500, 1500]))

    def test_real_fixture_end_to_end(self) -> None:
        """The module runs on a genuine 0-text-character scan, not just
        synthetic pages."""
        if not _FIXTURE.is_file():
            self.skipTest("handwritten-59 fixture not present")
        pages = rasterise_pdf_to_pages(_FIXTURE)
        # A box covering the whole first page: it must run and produce a
        # density in [0, 1], not that it lands on any particular side of
        # the blankness threshold (a full printed page is neither the blank
        # nor the ink case this proxy is calibrated to distinguish).
        density = box_ink_density(pages[0], [0, 0, 1000, 1000])
        self.assertIsNotNone(density)
        assert density is not None
        self.assertGreaterEqual(density, 0.0)
        self.assertLessEqual(density, 1.0)


def _answer(question_id: str, source_box: SourceBox | None) -> ExtractedAnswer:
    return ExtractedAnswer(
        question_id=question_id,
        answer="42",
        confidence=0.9,
        source_box=source_box,
    )


class PaperBoxPlausibilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.page = _quadrant_page()

    def test_denominator_excludes_answers_with_no_box(self) -> None:
        answers = [
            _answer("q1", SourceBox(page=0, box=[0, 0, 500, 500])),  # blank
            _answer("q2", SourceBox(page=0, box=[500, 500, 1000, 1000])),  # inked
            _answer("q3", None),  # no box at all -- outside the denominator
        ]

        report = paper_box_plausibility(answers, [self.page])

        self.assertIsInstance(report, BoxPlausibilityReport)
        self.assertEqual(report.total_answers, 3)
        self.assertEqual(report.boxes_considered, 2)
        self.assertEqual(report.measurable, 2)
        self.assertEqual(report.blank, 1)
        assert report.blank_rate is not None
        self.assertAlmostEqual(report.blank_rate, 0.5)

    def test_all_answers_missing_boxes_yields_none_rate_not_a_zero_division(self) -> None:
        answers = [_answer("q1", None), _answer("q2", None)]

        report = paper_box_plausibility(answers, [self.page])

        self.assertEqual(report.boxes_considered, 0)
        self.assertEqual(report.measurable, 0)
        self.assertEqual(report.blank, 0)
        self.assertIsNone(report.blank_rate)

    def test_degenerate_box_counted_as_unmeasurable_not_folded_into_blank_or_denominator(
        self,
    ) -> None:
        answers = [
            _answer("q1", SourceBox(page=0, box=[500, 500, 1000, 1000])),  # inked, measurable
        ]
        # A box referencing a page index that was never rasterised (e.g. the
        # page list passed in is a subset) is unmeasurable, not blank.
        answers.append(
            ExtractedAnswer.model_construct(
                question_id="q2",
                answer="1",
                confidence=0.9,
                source_region=None,
                source_box=SourceBox(page=7, box=[0, 0, 10, 10]),
                working_out=None,
                answer_reread=None,
                reread_agreement=None,
            )
        )

        report = paper_box_plausibility(answers, [self.page])

        self.assertEqual(report.boxes_considered, 2)
        self.assertEqual(report.unmeasurable, 1)
        self.assertEqual(report.measurable, 1)
        self.assertEqual(report.blank, 0)
        assert report.blank_rate is not None
        self.assertAlmostEqual(report.blank_rate, 0.0)


if __name__ == "__main__":
    unittest.main()
