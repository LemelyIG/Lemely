"""Unit tests for lemely.io.scan_render (#260, #249): the preview and crop renders."""

from __future__ import annotations

import io
import itertools
import pickle
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pymupdf
import pytest
from PIL import Image, ImageDraw, ImageOps

from lemely.io.rasterise import rasterise_scan_to_pages
from lemely.io.reread import padded_crop_rect
from lemely.io.scan_render import (
    CROP_RENDER_DPI,
    EXIF_ORIENTATION_TAG,
    MAX_CROP_PX,
    PREVIEW_LONG_EDGE_PX,
    RenderRefused,
    crop_image_scan,
    crop_pdf_scan,
    pdf_crop_plan,
    render_preview_png,
)
from tests.fakes_reader_agreement import dark_pixels, oriented_tiff
from tests.pdf_fakes import empty_page_tree_pdf
from tests.sandbox_fixtures import sandboxed  # noqa: F401

_REASONS = ("no_pages", "page_out_of_range", "page_too_large", "box_unusable")
_BOX = [100, 100, 300, 400]  # [ymin, xmin, ymax, xmax]
_UPRIGHT_SIZE = (600, 300)


def _pdf(*, pages: int = 1, width: float = 595.0, height: float = 842.0) -> bytes:
    """A blank synthetic PDF of ``pages`` pages of the given size in points."""
    doc = pymupdf.open()
    try:
        for _ in range(pages):
            doc.new_page(width=width, height=height)
        data: bytes = doc.tobytes()
    finally:
        doc.close()
    return data


def _phone_photo() -> bytes:
    """A JPEG stored sideways with EXIF orientation 6, a red mark at ``_BOX`` upright."""
    width, height = _UPRIGHT_SIZE
    image = Image.new("RGB", (width, height), (255, 255, 255))
    ymin, xmin, ymax, xmax = _BOX
    ImageDraw.Draw(image).rectangle(
        (
            xmin / 1000 * width,
            ymin / 1000 * height,
            xmax / 1000 * width - 1,
            ymax / 1000 * height - 1,
        ),
        fill=(255, 0, 0),
    )
    exif = Image.Exif()
    exif[EXIF_ORIENTATION_TAG] = 6
    buf = io.BytesIO()
    # Orientation 6 stores the page turned a quarter: ROTATE_90 is the inverse
    # of the ROTATE_270 that exif_transpose applies for it.
    image.transpose(Image.Transpose.ROTATE_90).save(
        buf, format="JPEG", exif=exif.tobytes(), quality=95
    )
    return buf.getvalue()


class RenderPreviewPngTests(unittest.TestCase):
    def test_render_preview_png_draws_page_one_of_a_pdf_at_72_dpi(self) -> None:
        png = render_preview_png(_pdf(pages=2, width=595.0, height=842.0))
        self.assertEqual(Image.open(io.BytesIO(png)).size, (595, 842))
        self.assertLessEqual(max(Image.open(io.BytesIO(png)).size), PREVIEW_LONG_EDGE_PX)

    def test_render_preview_png_refuses_a_document_with_no_pages(self) -> None:
        with self.assertRaises(RenderRefused) as caught:
            render_preview_png(empty_page_tree_pdf())
        self.assertEqual(caught.exception.reason, "no_pages")
        self.assertEqual(str(caught.exception), "Stored scan has no pages")


class CropPdfScanTests(unittest.TestCase):
    def test_crop_pdf_scan_crops_the_named_page_of_a_pdf(self) -> None:
        png = crop_pdf_scan(_pdf(pages=3), 1, list(_BOX))
        width, height = Image.open(io.BytesIO(png)).size
        self.assertGreater(width, 0)
        self.assertLessEqual(width * height, MAX_CROP_PX)

    def test_crop_pdf_scan_refuses_a_page_out_of_range_without_rendering(self) -> None:
        scan = _pdf(pages=3)
        with (
            patch.object(pymupdf.Document, "load_page") as load_page,
            self.assertRaises(RenderRefused) as caught,
        ):
            crop_pdf_scan(scan, 9, list(_BOX))
        load_page.assert_not_called()
        self.assertEqual(caught.exception.reason, "page_out_of_range")
        self.assertEqual(str(caught.exception), "Stored crop region names page 10 of a 3-page scan")
        self.assertEqual(caught.exception.fields, {"page_count": 3})

    def test_crop_pdf_scan_refuses_a_page_too_large_to_render(self) -> None:
        # A whole-page box on a 500,000 pt page is over the render ceiling even
        # at 1 dpi, so it is refused before anything is rasterised; the file is
        # a few hundred bytes.
        scan = _pdf(pages=3, width=500_000.0, height=500_000.0)
        self.assertLess(len(scan), 2_000)
        with self.assertRaises(RenderRefused) as caught:
            crop_pdf_scan(scan, 1, [0, 0, 1000, 1000])
        self.assertEqual(caught.exception.reason, "page_too_large")
        self.assertEqual(str(caught.exception), "This scan's pages are too large to render")
        self.assertEqual(caught.exception.fields, {"width_pt": 500_000.0, "height_pt": 500_000.0})

    def test_pdf_crop_plan_renders_an_a4_box_at_the_crop_dpi(self) -> None:
        plan = pdf_crop_plan(pymupdf.Rect(0, 0, 595, 842), list(_BOX))
        assert plan is not None
        self.assertEqual(plan.dpi, CROP_RENDER_DPI)


class CropImageScanTests(unittest.TestCase):
    def test_crop_image_scan_matches_the_route_helper_it_replaces(self) -> None:
        scan = _phone_photo()
        upright = ImageOps.exif_transpose(Image.open(io.BytesIO(scan))).convert("RGB")
        self.assertEqual(upright.size, _UPRIGHT_SIZE)
        rect = padded_crop_rect(upright.width, upright.height, list(_BOX))
        region = upright.crop(rect)
        want = region.resize((region.width * 2, region.height * 2), Image.Resampling.LANCZOS)

        got = Image.open(io.BytesIO(crop_image_scan(scan, list(_BOX)))).convert("RGB")

        self.assertEqual(got.size, want.size)
        self.assertEqual(got.tobytes(), want.tobytes())

    @pytest.mark.usefixtures("sandboxed")
    def test_crop_agrees_with_extraction_for_an_oriented_tiff(self) -> None:
        """#275: Pillow turns a TIFF upright when it loads it and drops the
        orientation tag, and its header already reports the upright size.
        The crop read the tag before the load and turned the region again,
        so a box extraction drew around the mark cropped blank paper.
        Extraction boxes the mark on its upright page (0-1000, as the model
        does); the crop of that box contains it."""
        for compression, orientation in itertools.product(("raw", "tiff_lzw"), (6, 8)):
            with self.subTest(compression=compression, orientation=orientation):
                scan = oriented_tiff(
                    "L", (600, 300), orientation, compression=compression, mark=(20, 30, 120, 90)
                )
                with tempfile.TemporaryDirectory() as scratch:
                    path = Path(scratch) / "scan.tif"
                    path.write_bytes(scan)
                    (page,) = rasterise_scan_to_pages(path)
                with Image.open(io.BytesIO(page.png_bytes)) as decoded:
                    dark = decoded.convert("L").point(lambda v: 255 if v < 128 else 0).getbbox()
                assert dark is not None
                left, top, right, bottom = dark
                box = [
                    top * 1000 // page.height,
                    left * 1000 // page.width,
                    -(-bottom * 1000 // page.height),
                    -(-right * 1000 // page.width),
                ]

                png = crop_image_scan(scan, box)

                with Image.open(io.BytesIO(png)) as crop:
                    size = crop.size
                self.assertGreater(dark_pixels(png, size), 100)

    def test_crop_image_scan_refuses_a_page_the_single_image_lacks(self) -> None:
        with self.assertRaises(RenderRefused) as caught:
            crop_image_scan(_phone_photo(), list(_BOX), page=1)
        self.assertEqual(caught.exception.reason, "page_out_of_range")
        self.assertEqual(str(caught.exception), "Stored crop region names page 2 of a 1-page scan")


class RenderRefusedTests(unittest.TestCase):
    def test_render_refused_pickles_with_message_reason_and_fields(self) -> None:
        for reason in _REASONS:
            with self.subTest(reason=reason):
                fields = {"width_pt": 8000.0}
                back = pickle.loads(pickle.dumps(RenderRefused("m", reason, fields)))  # noqa: S301
                self.assertIs(type(back), RenderRefused)
                self.assertEqual(str(back), "m")
                self.assertEqual(back.reason, reason)
                self.assertEqual(back.fields, fields)

                bare = pickle.loads(pickle.dumps(RenderRefused("m", reason)))  # noqa: S301
                self.assertIs(type(bare), RenderRefused)
                self.assertEqual(str(bare), "m")
                self.assertEqual(bare.reason, reason)
                self.assertEqual(bare.fields, {})

    def test_render_refused_keeps_all_three_values_in_args(self) -> None:
        exc = RenderRefused("m", "page_too_large", {"width_px": 1.0})
        self.assertEqual(exc.args, ("m", "page_too_large", {"width_px": 1.0}))


if __name__ == "__main__":
    unittest.main()
