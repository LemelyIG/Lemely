"""Unit tests for lemely.io.rasterise (I1)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pypdfium2 as pdfium
from PIL import Image

import lemely.io.scan_limits as scan_limits
from lemely.io.rasterise import (
    EXTRACTION_DPI,
    RasterisedPage,
    rasterise_pdf_to_pages,
    rasterise_scan_to_pages,
)
from lemely.io.scan_limits import ScanRejectedError, ScanTooLargeError
from tests.pdf_fakes import (
    annot_ap_bomb_pdf,
    image_bomb_pdf,
    page_bomb_pdf,
    page_kids_bomb_pdf,
    page_kids_equal_count_bomb_pdf,
    uncounted_bomb_pdf,
)

_FIXTURE = Path(__file__).parent / "fixtures" / "handwritten-59" / "0625_w24_qp_42.pdf"


def _write_pdf(path: Path, *, pages: int, size: tuple[int, int] = (100, 140)) -> None:
    images = [Image.new("RGB", size, color="white") for _ in range(pages)]
    images[0].save(path, "PDF", save_all=True, append_images=images[1:])


class RasterisePdfToPagesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()

    def test_returns_one_page_per_pdf_page_with_sequential_indices(self) -> None:
        pdf_path = Path(self.tmp) / "three_pages.pdf"
        _write_pdf(pdf_path, pages=3)

        pages = rasterise_pdf_to_pages(pdf_path)

        self.assertEqual(len(pages), 3)
        self.assertEqual([p.index for p in pages], [0, 1, 2])
        for page in pages:
            self.assertIsInstance(page, RasterisedPage)
            self.assertGreater(page.width, 0)
            self.assertGreater(page.height, 0)
            self.assertTrue(page.png_bytes.startswith(b"\x89PNG\r\n\x1a\n"))

    def test_renders_at_the_extraction_dpi_by_default(self) -> None:
        """A 1x1 inch (72pt) page at EXTRACTION_DPI must render to EXTRACTION_DPI px/side."""
        pdf_path = Path(self.tmp) / "one_inch.pdf"
        # PIL's default PDF page size uses the image's pixel size at 72 DPI
        # when no explicit resolution is given, i.e. 72x72 px == 1x1 inch.
        Image.new("RGB", (72, 72), color="white").save(pdf_path, "PDF")

        pages = rasterise_pdf_to_pages(pdf_path)

        self.assertEqual(len(pages), 1)
        self.assertEqual(pages[0].width, round(EXTRACTION_DPI))
        self.assertEqual(pages[0].height, round(EXTRACTION_DPI))

    def test_empty_pdf_raises_value_error(self) -> None:
        # pypdfium2 cannot represent a zero-page PDF via the normal save path,
        # so this exercises the guard with a document whose only page we then
        # discard is not reachable through PIL — assert the guard directly
        # against an already-empty page list instead of trying to construct
        # an unopenable file.
        from unittest.mock import MagicMock, patch

        with patch("lemely.io.rasterise.pdfium.PdfDocument") as mock_doc:
            mock_pdf = MagicMock()
            mock_pdf.__iter__.return_value = iter([])
            mock_doc.return_value = mock_pdf
            with self.assertRaises(ValueError):
                rasterise_pdf_to_pages(Path("unused.pdf"))

    @unittest.skipUnless(_FIXTURE.is_file(), "handwritten-59 fixture not present")
    def test_real_fixture_rasterises_to_its_known_page_count(self) -> None:
        """0625_w24_qp_42.pdf is documented (fixtures README) as 16 pages."""
        pages = rasterise_pdf_to_pages(_FIXTURE)
        self.assertEqual(len(pages), 16)
        self.assertEqual([p.index for p in pages], list(range(16)))


class RasteriseScanToPagesTests(unittest.TestCase):
    """The teacher/student portals accept image/* uploads as well as PDFs
    (lemely/web/routers/teacher.py) and ``scan_path`` is documented as
    "PDF / image" (lemely.web.services.grading.extract_answers) — the
    extractor's rasterisation entry point must handle both."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()

    def test_dispatches_pdf_content_to_the_pdf_renderer(self) -> None:
        pdf_path = Path(self.tmp) / "scan.pdf"
        _write_pdf(pdf_path, pages=2)
        pages = rasterise_scan_to_pages(pdf_path)
        self.assertEqual(len(pages), 2)

    def test_plain_image_upload_becomes_a_single_page(self) -> None:
        image_path = Path(self.tmp) / "scan.jpg"
        Image.new("RGB", (400, 600), color="white").save(image_path, "JPEG")

        pages = rasterise_scan_to_pages(image_path)

        self.assertEqual(len(pages), 1)
        self.assertEqual(pages[0].index, 0)
        self.assertEqual((pages[0].width, pages[0].height), (400, 600))
        self.assertTrue(pages[0].png_bytes.startswith(b"\x89PNG\r\n\x1a\n"))

    def test_dispatch_is_content_based_not_extension_based(self) -> None:
        """A PDF saved with a misleading .jpg extension must still be
        rendered as a PDF -- the client filename is never trusted (see
        lemely.web.upload_utils.safe_upload_name)."""
        mislabelled = Path(self.tmp) / "scan.jpg"
        _write_pdf(mislabelled, pages=1)
        pages = rasterise_scan_to_pages(mislabelled)
        self.assertEqual(len(pages), 1)
        # Rendered via the PDF path (EXTRACTION_DPI-scaled), not loaded as a
        # (corrupt) JPEG.
        self.assertGreater(pages[0].width, 0)


class GeometryBoundedRasteriseTests(unittest.TestCase):
    """Spec 2026-09-26 §6: rasterise plans every page before rendering any."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()

    def _pdf(self, name: str, *sizes_pt: tuple[float, float]) -> Path:
        pdf = pdfium.PdfDocument.new()
        for width, height in sizes_pt:
            pdf.new_page(width, height)
        path = Path(self.tmp) / name
        pdf.save(str(path))
        pdf.close()
        return path

    def test_a_within_band_pdf_page_comes_back_downscaled_with_its_dpi_recorded(self) -> None:
        # A1: 1684x2384 pt is ~31 Mpx at 200 DPI, which gives 143 DPI.
        pages = rasterise_pdf_to_pages(self._pdf("a1.pdf", (1684.0, 2384.0)))
        self.assertEqual(pages[0].dpi, 143.0)
        self.assertLessEqual(pages[0].width * pages[0].height, 16_000_000)
        self.assertEqual(pages[0].width, round(1684 * 143 / 72))

    def test_an_oversized_pdf_page_is_rejected(self) -> None:
        with self.assertRaises(ScanTooLargeError):
            rasterise_pdf_to_pages(self._pdf("huge.pdf", (14400.0, 14400.0)))

    def test_too_many_pages_are_rejected_before_any_render(self) -> None:
        path = self._pdf("many.pdf", *([(595.0, 842.0)] * 41))
        with patch.object(pdfium.PdfPage, "render") as render, self.assertRaises(ScanTooLargeError):
            rasterise_pdf_to_pages(path)
        render.assert_not_called()

    def test_each_page_is_closed_before_the_next_page_is_loaded(self) -> None:
        """Final review N1: a loaded pdfium page keeps its decoded images
        alive until it is closed; left open until ``pdf.close()``, a 40-page
        scan held every page's images at once (1037 MB peak RSS on the
        reviewer's 1.13 MB shape, 553 MB with a close per page). Pages must
        be closed one at a time, each before the next is loaded."""
        path = self._pdf("three.pdf", (72.0, 72.0), (72.0, 72.0), (72.0, 72.0))
        events: list[tuple[str, int]] = []
        real_get_page = pdfium.PdfDocument.get_page
        real_close = pdfium.PdfPage.close
        index_of: dict[int, int] = {}

        def _get_page(doc: pdfium.PdfDocument, index: int) -> pdfium.PdfPage:
            page = real_get_page(doc, index)
            index_of[id(page)] = index
            events.append(("load", index))
            return page

        def _close(page: pdfium.PdfPage, *args: object, **kwargs: object) -> object:
            if id(page) in index_of:
                events.append(("close", index_of.pop(id(page))))
            return real_close(page, *args, **kwargs)

        with (
            patch.object(pdfium.PdfDocument, "get_page", _get_page),
            patch.object(pdfium.PdfPage, "close", _close),
        ):
            pages = rasterise_pdf_to_pages(path)
        self.assertEqual(len(pages), 3)
        self.assertEqual(
            events,
            [("load", 0), ("close", 0), ("load", 1), ("close", 1), ("load", 2), ("close", 2)],
        )

    def test_too_many_pages_are_rejected_before_the_content_walk(self) -> None:
        """Final review M1: the content walk visits every page, so the page
        cap must be applied before it -- a 20,000-page 5.8 MB PDF was walked
        for 10.6 s at extraction before the cap refused it."""
        path = self._pdf("many.pdf", *([(595.0, 842.0)] * 41))
        with (
            patch("lemely.io.rasterise.check_pdf_content_path") as walk,
            self.assertRaises(ScanTooLargeError),
        ):
            rasterise_pdf_to_pages(path)
        walk.assert_not_called()

    def test_a_within_band_image_is_reduced(self) -> None:
        image_path = Path(self.tmp) / "big.png"
        Image.new("1", (5000, 5000), color=1).save(image_path, "PNG")
        pages = rasterise_scan_to_pages(image_path)
        self.assertEqual((pages[0].width, pages[0].height), (2500, 2500))

    def test_a_within_band_jpeg_uses_the_native_reduced_decode(self) -> None:
        image_path = Path(self.tmp) / "big.jpg"
        Image.new("L", (5000, 5000), color=255).save(image_path, "JPEG")
        pages = rasterise_scan_to_pages(image_path)
        self.assertLessEqual(pages[0].width * pages[0].height, 16_000_000)

    def test_an_oversized_image_is_rejected(self) -> None:
        image_path = Path(self.tmp) / "huge.png"
        Image.new("1", (7000, 7000), color=1).save(image_path, "PNG")
        with self.assertRaises(ScanTooLargeError):
            rasterise_scan_to_pages(image_path)

    @unittest.skipUnless(_FIXTURE.is_file(), "handwritten-59 fixture not present")
    def test_the_committed_fixture_is_unaffected(self) -> None:
        pages = rasterise_pdf_to_pages(_FIXTURE)
        self.assertEqual((pages[0].width, pages[0].height, pages[0].dpi), (1655, 2339, 200.0))

    def test_a_scan_over_the_total_pixel_cap_renders_at_the_uniform_lower_dpi(self) -> None:
        """Final review I1: the DPI the scan-wide downscale chose is the one
        rendered and recorded on ``RasterisedPage.dpi``. The cap is lowered
        so two 1-inch pages exceed it -- a real over-cap scan is never
        rendered in a test: 2 x 200^2 px against a 40,000 px cap gives
        s = sqrt(1/2), i.e. floor(141.4) = 141 DPI."""
        path = self._pdf("one-inch-squares.pdf", (72.0, 72.0), (72.0, 72.0))
        with patch.object(scan_limits, "MAX_SCAN_TOTAL_PX", 40_000):
            pages = rasterise_pdf_to_pages(path)
        self.assertEqual([p.dpi for p in pages], [141.0, 141.0])
        self.assertEqual([(p.width, p.height) for p in pages], [(141, 141), (141, 141)])

    def test_a_scan_that_cannot_fit_the_total_pixel_cap_is_rejected_before_any_render(
        self,
    ) -> None:
        # 40 pages of 1700 pt squares need 84 DPI to fit 160 Mpx: under the floor.
        path = self._pdf("aggregate.pdf", *([(1700.0, 1700.0)] * 40))
        with patch.object(pdfium.PdfPage, "render") as render, self.assertRaises(ScanTooLargeError):
            rasterise_pdf_to_pages(path)
        render.assert_not_called()

    def test_a_content_bomb_is_rejected_before_any_render(self) -> None:
        path = Path(self.tmp) / "bomb.pdf"
        path.write_bytes(page_bomb_pdf(112_000_000))
        with patch.object(pdfium.PdfPage, "render") as render, self.assertRaises(ScanTooLargeError):
            rasterise_pdf_to_pages(path)
        render.assert_not_called()

    def test_an_image_xobject_bomb_is_rejected_before_any_render(self) -> None:
        path = Path(self.tmp) / "image-bomb.pdf"
        path.write_bytes(image_bomb_pdf(40_000, 40_000))
        with patch.object(pdfium.PdfPage, "render") as render, self.assertRaises(ScanTooLargeError):
            rasterise_pdf_to_pages(path)
        render.assert_not_called()

    def test_an_annotation_appearance_stream_bomb_is_rejected_before_any_render(self) -> None:
        # Fix round 1: the new content-walk paths (annotations, patterns,
        # Type3 CharProcs) all go through the same check_pdf_content_path
        # call as the page-content/Form-XObject bomb above; this pins that
        # the mechanism reaches rasterise for one of them, representatively.
        path = Path(self.tmp) / "annot-bomb.pdf"
        path.write_bytes(annot_ap_bomb_pdf(112_000_000))
        with patch.object(pdfium.PdfPage, "render") as render, self.assertRaises(ScanTooLargeError):
            rasterise_pdf_to_pages(path)
        render.assert_not_called()

    def test_a_bomb_only_pdfium_sees_is_rejected_before_any_page_is_loaded(self) -> None:
        """Task 9b, the reviewer's reproduction: MuPDF cannot load page 2, which
        pdfium renders as a content bomb (642,857 objects, 2.4 s to parse on
        load). Refused before pdfium loads, let alone renders, a page."""
        path = Path(self.tmp) / "page-kids-bomb.pdf"
        path.write_bytes(page_kids_bomb_pdf(scan_limits.MAX_PAGE_CONTENT_BYTES + 1_000_000))
        with (
            patch.object(pdfium.PdfDocument, "get_page") as get_page,
            patch.object(pdfium.PdfPage, "render") as render,
            self.assertRaises(ScanRejectedError),
        ):
            rasterise_pdf_to_pages(path)
        get_page.assert_not_called()
        render.assert_not_called()

    def test_the_equal_count_page_kids_bomb_is_rejected_before_any_page_is_loaded(self) -> None:
        """T9b review round 1: both readers count 2 pages, but pdfium's page 1
        is a bomb held in the ``/Kids`` of a ``/Type /Page`` MuPDF numbers as
        page 1 (8.9 s to parse on load). Refused before pdfium loads a page."""
        path = Path(self.tmp) / "page-kids-equal-count-bomb.pdf"
        path.write_bytes(
            page_kids_equal_count_bomb_pdf(scan_limits.MAX_PAGE_CONTENT_BYTES + 1_000_000)
        )
        with (
            patch.object(pdfium.PdfDocument, "get_page") as get_page,
            patch.object(pdfium.PdfPage, "render") as render,
            self.assertRaises(ScanRejectedError) as caught,
        ):
            rasterise_pdf_to_pages(path)
        get_page.assert_not_called()
        render.assert_not_called()
        self.assertEqual(str(caught.exception), scan_limits._PAGE_STRUCTURE_MALFORMED_MESSAGE)

    def test_readers_that_disagree_on_the_page_count_are_rejected_before_any_page_is_loaded(
        self,
    ) -> None:
        """Task 9b: ``/Count 0`` over two real pages, the second a bomb. MuPDF
        sees no pages, so its content walk measures nothing; pdfium, which
        renders extraction, sees both. Refused on the disagreement."""
        path = Path(self.tmp) / "uncounted-bomb.pdf"
        path.write_bytes(
            uncounted_bomb_pdf(
                scan_limits.MAX_PAGE_CONTENT_BYTES + 1_000_000, count_entry=b"/Count 0"
            )
        )
        with (
            patch.object(pdfium.PdfDocument, "get_page") as get_page,
            patch.object(pdfium.PdfPage, "render") as render,
            self.assertRaises(ScanRejectedError) as caught,
        ):
            rasterise_pdf_to_pages(path)
        get_page.assert_not_called()
        render.assert_not_called()
        self.assertEqual(str(caught.exception), scan_limits._PAGE_COUNT_UNREADABLE_MESSAGE)


if __name__ == "__main__":
    unittest.main()
