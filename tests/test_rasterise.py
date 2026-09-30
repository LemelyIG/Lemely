"""Unit tests for lemely.io.rasterise (I1)."""

from __future__ import annotations

import io
import itertools
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pypdfium2 as pdfium
from PIL import Image

import lemely.io.rasterise as rasterise_module
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
    bilevel_png,
    declared_image,
    image_bomb_pdf,
    off_page_object_pdf,
    page_bomb_pdf,
    page_kids_bomb_pdf,
    page_kids_equal_count_bomb_pdf,
    shared_container_broken_xref_pdf,
    uncounted_bomb_pdf,
    xref_repair_bomb_pdf,
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

        # Task 9c: pdfium now renders MuPDF's rewrite of the file, so the
        # file read and the rewrite are stubbed too; pdfium still reports no
        # pages, which is what this test is about.
        with (
            patch("lemely.io.rasterise.pdfium.PdfDocument") as mock_doc,
            patch.object(Path, "read_bytes", return_value=b"%PDF-1.4 stub"),
            patch("lemely.io.rasterise.canonical_pdf_bytes", return_value=b"%PDF-1.4 stub"),
        ):
            mock_pdf = MagicMock()
            mock_pdf.__iter__.return_value = iter([])
            mock_pdf.__len__.return_value = 0
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
            patch("lemely.io.rasterise.check_pdf_content_bytes") as walk,
            self.assertRaises(ScanTooLargeError),
        ):
            rasterise_pdf_to_pages(path)
        walk.assert_not_called()

    def test_a_phone_photo_is_turned_upright_by_its_exif_flag(self) -> None:
        """#255 (probe ``be_probe_img.py``): a 400x200 JPEG with EXIF
        orientation 6 reached the model as a 400x200 page. Phones store a
        portrait photo as a landscape sensor frame plus that flag; the page
        the model reads, and the frame every ``source_box`` is in, must be
        the upright one. The green corner marks the raw top-left; after a
        quarter turn it must sit at the top-right of the upright page."""
        from PIL import ImageDraw

        image = Image.new("RGB", (400, 200), (255, 255, 255))
        ImageDraw.Draw(image).rectangle((0, 0, 39, 39), fill=(0, 255, 0))
        exif = Image.Exif()
        exif[0x0112] = 6
        image_path = Path(self.tmp) / "phone.jpg"
        image.save(image_path, "JPEG", exif=exif.tobytes(), quality=95)

        (page,) = rasterise_scan_to_pages(image_path)

        self.assertEqual((page.width, page.height), (200, 400))
        decoded = Image.open(io.BytesIO(page.png_bytes)).convert("RGB")
        r, g, b = decoded.getpixel((199, 0))
        self.assertTrue(g > 200 and r < 80 and b < 80, "green corner is not at the top-right")
        self.assertIsNone(decoded.getexif().get(0x0112))

    def test_every_exif_orientation_lands_the_raw_top_left_where_the_flag_says(self) -> None:
        """All eight flags, JPEG and PNG. ``upright_corner`` is the EXIF
        table written out by hand (where the stored frame's top-left corner
        ends up once the photo is upright), not derived from Pillow's own
        ``exif_transpose``, so it is an independent oracle."""
        from PIL import ImageDraw

        # orientation -> (upright size after the flag, corner: (right?, bottom?))
        wide, tall = (400, 200), (200, 400)
        upright_corner = {
            1: (wide, (False, False)),
            2: (wide, (True, False)),
            3: (wide, (True, True)),
            4: (wide, (False, True)),
            5: (tall, (False, False)),
            6: (tall, (True, False)),
            7: (tall, (True, True)),
            8: (tall, (False, True)),
        }
        for fmt, suffix in (("JPEG", "jpg"), ("PNG", "png")):
            for orientation, (size, (right, bottom)) in upright_corner.items():
                with self.subTest(format=fmt, orientation=orientation):
                    image = Image.new("RGB", (400, 200), (255, 255, 255))
                    ImageDraw.Draw(image).rectangle((0, 0, 39, 39), fill=(0, 255, 0))
                    exif = Image.Exif()
                    exif[0x0112] = orientation
                    path = Path(self.tmp) / f"o{orientation}.{suffix}"
                    image.save(path, fmt, exif=exif.tobytes())

                    (page,) = rasterise_scan_to_pages(path)

                    self.assertEqual((page.width, page.height), size)
                    decoded = Image.open(io.BytesIO(page.png_bytes)).convert("RGB")
                    x = page.width - 3 if right else 2
                    y = page.height - 3 if bottom else 2
                    r, g, b = decoded.getpixel((x, y))
                    self.assertTrue(
                        g > 200 and r < 80 and b < 80,
                        f"green corner is not at (right={right}, bottom={bottom})",
                    )
                    # ...and nowhere else: the opposite corner stays white.
                    ox = 2 if right else page.width - 3
                    oy = 2 if bottom else page.height - 3
                    self.assertGreater(min(decoded.getpixel((ox, oy))), 200)

    def test_a_reduced_decode_jpeg_is_still_turned_upright(self) -> None:
        """A JPEG over ``MAX_PAGE_PX`` takes the native reduced-scale ``draft``
        decode, and the flag is applied to that reduced frame. 6000x4000 is
        24 Mpx, so ``draft`` halves it to 3000x2000. The green corner marks
        the stored top-left, so flag 6 (top-right) and flag 8 (bottom-left)
        cannot be mistaken for each other."""
        from PIL import ImageDraw, JpegImagePlugin

        expected_corner = {6: (True, False), 8: (False, True)}  # (right?, bottom?)
        for orientation, (right, bottom) in expected_corner.items():
            with self.subTest(orientation=orientation):
                image = Image.new("RGB", (6000, 4000), (255, 255, 255))
                ImageDraw.Draw(image).rectangle((0, 0, 79, 79), fill=(0, 255, 0))
                exif = Image.Exif()
                exif[0x0112] = orientation
                path = Path(self.tmp) / f"big_phone_{orientation}.jpg"
                image.save(path, "JPEG", exif=exif.tobytes(), quality=95)

                drafts: list[tuple[object, ...]] = []
                real_draft = JpegImagePlugin.JpegImageFile.draft

                def spy(
                    file: JpegImagePlugin.JpegImageFile,
                    *args: object,
                    _real: object = real_draft,
                    _calls: list[tuple[object, ...]] = drafts,
                ) -> object:
                    _calls.append(args)
                    return _real(file, *args)  # type: ignore[operator]

                with patch.object(JpegImagePlugin.JpegImageFile, "draft", spy):
                    (page,) = rasterise_scan_to_pages(path)

                self.assertEqual(drafts, [(None, (3000, 2000))])
                self.assertEqual((page.width, page.height), (2000, 3000))
                decoded = Image.open(io.BytesIO(page.png_bytes)).convert("RGB")
                x = page.width - 3 if right else 2
                y = page.height - 3 if bottom else 2
                r, g, b = decoded.getpixel((x, y))
                self.assertTrue(
                    g > 200 and r < 80 and b < 80,
                    f"green corner is not at (right={right}, bottom={bottom})",
                )
                ox = 2 if right else page.width - 3
                oy = 2 if bottom else page.height - 3
                self.assertGreater(min(decoded.getpixel((ox, oy))), 200)

    def test_an_image_without_an_exif_flag_is_unchanged(self) -> None:
        image_path = Path(self.tmp) / "plain.png"
        Image.new("RGB", (400, 200), (255, 255, 255)).save(image_path, "PNG")
        (page,) = rasterise_scan_to_pages(image_path)
        self.assertEqual((page.width, page.height), (400, 200))

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

    def _declared(self, name: str, mode: str, size: tuple[int, int]) -> Path:
        path = Path(self.tmp) / name
        path.write_bytes(declared_image(mode, *size))
        return path

    def test_an_oversized_image_is_rejected(self) -> None:
        """Header only (169 Mpx bilevel, 161.3 Mpx grey): refused before a
        pixel is decoded -- the file holds none."""
        for mode, size in (("1", (13000, 13000)), ("1", (12700, 12700)), ("L", (12700, 12700))):
            with self.subTest(mode=mode, size=size), self.assertRaises(ScanTooLargeError):
                rasterise_scan_to_pages(self._declared(f"huge-{mode}.png", mode, size))

    def test_an_oversized_colour_image_is_still_rejected_at_forty_megapixels(self) -> None:
        """User decision 1 (2026-09-29): 41.6 Mpx of colour is refused in
        every colour mode, whatever the grey ceiling now admits."""
        for mode in ("RGB", "RGBA", "CMYK", "P", "LA"):
            suffix = "tif" if mode == "CMYK" else "png"
            with self.subTest(mode=mode), self.assertRaises(ScanTooLargeError):
                rasterise_scan_to_pages(self._declared(f"colour.{suffix}", mode, (6500, 6400)))

    def test_a_bilevel_scan_over_forty_megapixels_is_reduced_not_refused(self) -> None:
        """#256: 49 Mpx of mode "1" is a 49 MB decode; it used to be refused
        for its pixel count. Reduced by 2 (to 12.25 Mpx)."""
        image_path = Path(self.tmp) / "office.png"
        Image.new("1", (7000, 7000), color=1).save(image_path, "PNG")
        pages = rasterise_scan_to_pages(image_path)
        self.assertEqual((pages[0].width, pages[0].height), (3500, 3500))

    def test_a_bilevel_a4_office_scan_at_1200_dpi_is_extracted(self) -> None:
        """#256 (probe ``be_probe_img.py``): 9921 x 14031 = 139 Mpx of 1-bit
        A4 in a ~40 KB file. Admitted, reduced by 4 (8.7 Mpx) for the model,
        and the ink survives: the black mark covers 30-40% x 10-30% of the
        page and must still be black there, the rest white."""
        width, height = 9921, 14031
        mark = (width * 3 // 10, height // 10, width * 4 // 10, height * 3 // 10)
        image_path = Path(self.tmp) / "a4-1200dpi.png"
        image_path.write_bytes(bilevel_png(width, height, mark=mark))

        (page,) = rasterise_scan_to_pages(image_path)

        self.assertEqual((page.width, page.height), (2481, 3508))
        self.assertLessEqual(page.width * page.height, scan_limits.MAX_PAGE_PX)
        decoded = Image.open(io.BytesIO(page.png_bytes))
        self.assertEqual(decoded.mode, "RGB")
        inside_mark = (page.width * 35 // 100, page.height * 2 // 10)
        self.assertEqual(decoded.getpixel(inside_mark), (0, 0, 0))
        self.assertEqual(decoded.getpixel((page.width // 10, page.height // 2)), (255, 255, 255))

    def test_the_reduce_happens_before_the_rgb_conversion(self) -> None:
        """#256: a bilevel or greyscale page is reduced BEFORE any RGB
        conversion, so the three-channel copy is never made at full size
        (49 Mpx of "1" would be a 147 MB RGB copy of a 49 MB decode)."""
        real_convert = Image.Image.convert
        for mode, color in (("L", 200), ("1", 1)):
            with self.subTest(mode=mode):
                image_path = Path(self.tmp) / f"grey-{mode}.png"
                Image.new(mode, (5000, 5000), color=color).save(image_path, "PNG")
                sizes_converted_to_rgb: list[tuple[int, int]] = []

                def _convert(
                    image: Image.Image,
                    mode: str | None = None,
                    *args: object,
                    _sizes: list[tuple[int, int]] = sizes_converted_to_rgb,
                    **kwargs: object,
                ) -> Image.Image:
                    if mode == "RGB":
                        _sizes.append(image.size)
                    return real_convert(image, mode, *args, **kwargs)  # type: ignore[arg-type]

                with patch.object(Image.Image, "convert", _convert):
                    rasterise_scan_to_pages(image_path)
                self.assertEqual(sizes_converted_to_rgb, [(2500, 2500)])

    def test_a_bilevel_scan_over_forty_megapixels_is_still_turned_upright(self) -> None:
        """#255 and #256 together: the EXIF flag is applied to a large
        bilevel scan that is now admitted, before the reduce. 8000 x 6000
        stored with flag 6 is a 6000 x 8000 upright page, reduced by 2 to
        3000 x 4000; the stored top-left black corner lands top-right."""
        image = Image.new("1", (8000, 6000), color=1)
        image.paste(0, (0, 0, 400, 400))
        exif = Image.Exif()
        exif[0x0112] = 6
        image_path = Path(self.tmp) / "turned.png"
        image.save(image_path, "PNG", exif=exif.tobytes())
        del image

        (page,) = rasterise_scan_to_pages(image_path)

        self.assertEqual((page.width, page.height), (3000, 4000))
        decoded = Image.open(io.BytesIO(page.png_bytes))
        self.assertEqual(decoded.getpixel((page.width - 3, 2)), (0, 0, 0))
        self.assertEqual(decoded.getpixel((2, 2)), (255, 255, 255))

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
        # Type3 CharProcs) all go through the same check_pdf_content_bytes
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

    def test_a_bomb_behind_an_xref_repair_is_never_rendered(self) -> None:
        """Task 9c, the reviewer's xref-repair probe: object 4, the page's
        content, is defined twice -- a clean rectangle the xref names, then
        a bomb -- and each xref entry is 19 bytes. MuPDF measures the clean
        one; pdfium, repairing by scanning, used to take the bomb. pdfium now
        renders MuPDF's rewrite, so the page it loads is the clean one: one
        object, drawn red."""
        path = Path(self.tmp) / "xref-repair-bomb.pdf"
        path.write_bytes(xref_repair_bomb_pdf(scan_limits.MAX_PAGE_CONTENT_BYTES + 1_000_000))
        real_get_page = pdfium.PdfDocument.get_page
        counts: list[int] = []

        def counting_get_page(doc: pdfium.PdfDocument, index: int) -> pdfium.PdfPage:
            page = real_get_page(doc, index)
            counts.append(sum(1 for _ in itertools.islice(page.get_objects(), 1_000)))
            if counts[-1] > 1:
                page.close()
                raise AssertionError(f"pdfium loaded a page of {counts[-1]}+ objects: the bomb")
            return page

        with patch.object(pdfium.PdfDocument, "get_page", counting_get_page):
            pages = rasterise_pdf_to_pages(path)
        self.assertEqual(counts, [1])
        image = Image.open(io.BytesIO(pages[0].png_bytes)).convert("RGB")
        red = sum(
            n for n, (r, g, b) in image.getcolors(image.width * image.height) or [] if r > 200 > g
        )
        self.assertGreater(red, 0)

    def test_objects_no_page_reaches_never_reach_pdfium(self) -> None:
        """Task 9c review round 1: a big object hung off the catalog, compressed
        (a few KB on disk) or not, is left out of the rewrite pdfium renders,
        so neither the rewrite nor pdfium ever parses it."""
        sizes: list[int] = []
        real_document = pdfium.PdfDocument

        def document(source: bytes, *args: object, **kwargs: object) -> pdfium.PdfDocument:
            sizes.append(len(source))
            return real_document(source, *args, **kwargs)  # type: ignore[arg-type]

        for compressed in (True, False):
            path = Path(self.tmp) / f"off-page-{compressed}.pdf"
            path.write_bytes(off_page_object_pdf(2_000_000, compressed=compressed))
            sizes.clear()
            with (
                self.subTest(compressed=compressed),
                patch.object(rasterise_module.pdfium, "PdfDocument", document),
            ):
                pages = rasterise_pdf_to_pages(path)
                self.assertEqual(len(pages), 1)
                self.assertEqual(len(sizes), 1)
                self.assertLess(sizes[0], 20_000)

    def test_an_object_stream_bomb_is_refused_before_pdfium_opens_anything(self) -> None:
        """Task 9c review round 1: a stored file that pre-dates the upload
        bound on object streams is refused at extraction too."""
        path = Path(self.tmp) / "objstm-bomb.pdf"
        path.write_bytes(
            off_page_object_pdf(scan_limits.MAX_OBJECT_STREAM_BYTES // 2 + 1_000, compressed=True)
        )
        with (
            patch.object(rasterise_module.pdfium, "PdfDocument") as document,
            self.assertRaises(ScanTooLargeError) as caught,
        ):
            rasterise_pdf_to_pages(path)
        document.assert_not_called()
        self.assertEqual(str(caught.exception), scan_limits._OBJECT_STREAMS_MESSAGE)

    def test_a_container_bomb_under_a_broken_xref_is_refused_before_any_reader_opens_it(
        self,
    ) -> None:
        """Task 9c review round 2: MuPDF's xref repair would parse the whole
        object stream while opening the file, so extraction bounds object
        streams in the raw bytes before either reader opens it."""
        path = Path(self.tmp) / "broken-xref-container.pdf"
        path.write_bytes(
            shared_container_broken_xref_pdf(scan_limits.MAX_OBJECT_STREAM_BYTES // 2 + 1_000)
        )
        with (
            patch.object(scan_limits.pymupdf, "open", side_effect=AssertionError("MuPDF opened")),
            patch.object(rasterise_module.pdfium, "PdfDocument") as document,
            self.assertRaises(ScanTooLargeError) as caught,
        ):
            rasterise_pdf_to_pages(path)
        document.assert_not_called()
        self.assertEqual(str(caught.exception), scan_limits._OBJECT_STREAMS_MESSAGE)

    def test_pdfium_renders_the_bytes_the_content_check_measured_not_the_file(self) -> None:
        """Task 9c: pdfium is handed MuPDF's rewrite -- the very object the
        content check was given -- never the stored file's path or bytes."""
        path = Path(self.tmp) / "plain.pdf"
        _write_pdf(path, pages=2)
        rewritten: list[bytes] = []
        checked: list[bytes] = []
        opened: list[object] = []
        real_canonical = rasterise_module.canonical_pdf_bytes
        real_check = rasterise_module.check_pdf_content_bytes
        real_document = pdfium.PdfDocument

        def canonical(data: bytes) -> bytes:
            rewritten.append(real_canonical(data))
            return rewritten[-1]

        def check(data: bytes, **kwargs: int | None) -> None:
            checked.append(data)
            real_check(data, **kwargs)

        def document(source: object, *args: object, **kwargs: object) -> pdfium.PdfDocument:
            opened.append(source)
            return real_document(source, *args, **kwargs)  # type: ignore[arg-type]

        with (
            patch.object(rasterise_module, "canonical_pdf_bytes", canonical),
            patch.object(rasterise_module, "check_pdf_content_bytes", check),
            patch.object(rasterise_module.pdfium, "PdfDocument", document),
        ):
            pages = rasterise_pdf_to_pages(path)
        self.assertEqual(len(pages), 2)
        self.assertEqual(len(rewritten), 1)
        self.assertEqual(len(opened), 1)
        self.assertTrue(opened[0] is rewritten[0], f"pdfium opened {type(opened[0]).__name__}")
        self.assertEqual(len(checked), 1)
        self.assertTrue(checked[0] is rewritten[0], "the content check measured other bytes")
        self.assertTrue(opened[0] != path.read_bytes(), "pdfium was given the stored bytes")

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
        # Task 9c: refused while the original is checked, before the rewrite
        # -- the tree holds pages MuPDF does not number.
        self.assertEqual(str(caught.exception), scan_limits._PAGE_STRUCTURE_MALFORMED_MESSAGE)


if __name__ == "__main__":
    unittest.main()
