"""Unit tests for lemely.io.scan_limits (spec 2026-09-26 §6)."""

from __future__ import annotations

import io
import time
import tracemalloc
import unittest
from pathlib import Path
from unittest.mock import patch

import pymupdf
import pypdfium2 as pdfium
from PIL import Image

import lemely.io.scan_limits as scan_limits
from lemely.io.scan_limits import (
    MAX_DECODE_PX,
    MAX_PAGE_CONTENT_BYTES,
    MAX_PAGE_PX,
    MAX_SCAN_CONTENT_BYTES,
    MAX_SCAN_PAGES,
    ScanRejectedError,
    ScanTooLargeError,
    ScanUnsupportedEncodingError,
    check_pdf_content_bytes,
    check_pdf_content_path,
    check_scan_bytes,
    decoded_stream_size,
    plan_image,
    plan_page_dpi,
    plan_pdf_pages,
)
from tests.pdf_fakes import (
    annot_ap_bomb_pdf,
    assemble_pdf,
    encrypted_pdf_bytes,
    extgstate_smask_bomb_pdf,
    filtered_page_pdf,
    flate_bomb_ops,
    form_xobject_cycle_pdf,
    image_bomb_pdf,
    indirect_ap_state_bomb_pdf,
    indirect_filter_page_pdf,
    indirect_smask_dimension_bomb_pdf,
    indirect_xobject_dict_bomb_pdf,
    many_form_xobjects_pdf,
    page_bomb_pdf,
    pdf_stream,
    pdf_with_inflated_count,
    pdf_with_missing_kid_object,
    repeated_xobject_pdf,
    smask_bomb_pdf,
    tiling_pattern_bomb_pdf,
    type3_charproc_bomb_pdf,
    xobject_bomb_pdf,
)

_FIXTURE = Path(__file__).parent / "fixtures" / "handwritten-59" / "0625_w24_qp_42.pdf"


def _pdf_bytes(*sizes_pt: tuple[float, float]) -> bytes:
    """A PDF declaring the given page sizes (points), as bytes.

    ``PdfDocument.save`` takes a path or a binary file object; if the
    installed pypdfium2 rejects the ``BytesIO``, save to a ``tempfile``
    path and ``read_bytes()`` it instead.
    """
    pdf = pdfium.PdfDocument.new()
    for width, height in sizes_pt:
        pdf.new_page(width, height)
    buf = io.BytesIO()
    pdf.save(buf)
    pdf.close()
    return buf.getvalue()


def _png_bytes(width: int, height: int, mode: str = "1") -> bytes:
    buf = io.BytesIO()
    Image.new(mode, (width, height), color=1 if mode == "1" else "white").save(buf, "PNG")
    return buf.getvalue()


class PagePlanTests(unittest.TestCase):
    def test_a4_at_200_dpi_is_rendered_as_is(self) -> None:
        self.assertEqual(plan_page_dpi(595.0, 842.0), 200.0)

    def test_a_page_within_the_band_is_planned_at_a_lower_dpi(self) -> None:
        # A1: 1684x2384 pt is ~31 Mpx at 200 DPI -- over the 16 Mpx target,
        # under the 40 Mpx reject boundary -- so it renders at floor(200 *
        # sqrt(16e6 / 31e6)) = 143 DPI and lands under the target.
        dpi = plan_page_dpi(1684.0, 2384.0)
        self.assertEqual(dpi, 143.0)
        self.assertLessEqual(1684 * 2384 * (dpi / 72) ** 2, MAX_PAGE_PX)

    def test_a_page_beyond_the_decode_bound_is_rejected(self) -> None:
        with self.assertRaises(ScanTooLargeError) as ctx:
            plan_page_dpi(14400.0, 14400.0)
        self.assertIn("too large to process", str(ctx.exception))

    def test_more_than_max_pages_is_rejected_before_any_render(self) -> None:
        pdf = pdfium.PdfDocument(_pdf_bytes(*([(595.0, 842.0)] * (MAX_SCAN_PAGES + 1))))
        try:
            with (
                patch.object(pdfium.PdfPage, "render") as render,
                self.assertRaises(ScanTooLargeError),
            ):
                plan_pdf_pages(pdf)
            render.assert_not_called()
        finally:
            pdf.close()

    def test_plans_carry_page_indices_in_order(self) -> None:
        pdf = pdfium.PdfDocument(_pdf_bytes((595.0, 842.0), (1684.0, 2384.0)))
        try:
            plans = plan_pdf_pages(pdf)
        finally:
            pdf.close()
        self.assertEqual([(p.index, p.dpi) for p in plans], [(0, 200.0), (1, 143.0)])


class ImagePlanTests(unittest.TestCase):
    def test_image_under_the_target_is_not_reduced(self) -> None:
        self.assertEqual(plan_image(1655, 2339), 1)

    def test_image_within_the_band_is_reduced_by_the_smallest_factor_that_fits(self) -> None:
        self.assertEqual(plan_image(5000, 5000), 2)  # 25 Mpx -> 6.25 Mpx

    def test_image_beyond_the_decode_bound_is_rejected(self) -> None:
        with self.assertRaises(ScanTooLargeError):
            plan_image(7000, 7000)  # 49 Mpx


class CheckScanBytesTests(unittest.TestCase):
    def test_a4_pdf_passes(self) -> None:
        check_scan_bytes(_pdf_bytes((595.0, 842.0)))

    def test_oversized_pdf_page_is_rejected_from_bytes(self) -> None:
        with self.assertRaises(ScanTooLargeError):
            check_scan_bytes(_pdf_bytes((14400.0, 14400.0)))

    def test_too_many_pdf_pages_are_rejected_from_bytes(self) -> None:
        with self.assertRaises(ScanTooLargeError):
            check_scan_bytes(_pdf_bytes(*([(595.0, 842.0)] * (MAX_SCAN_PAGES + 1))))

    def test_oversized_image_is_rejected_from_its_header(self) -> None:
        with self.assertRaises(ScanTooLargeError):
            check_scan_bytes(_png_bytes(7000, 7000))

    def test_image_within_the_band_passes(self) -> None:
        check_scan_bytes(_png_bytes(5000, 5000))

    def test_decompression_bomb_is_reported_as_too_large(self) -> None:
        data = _png_bytes(100, 100)
        with patch.object(Image, "MAX_IMAGE_PIXELS", 1000), self.assertRaises(ScanTooLargeError):
            check_scan_bytes(data)

    def test_unparseable_bytes_are_not_rejected(self) -> None:
        """A fake `%PDF-1.4 scan` body or random bytes must pass the upload
        check: extraction fails on them later, exactly as today (existing
        upload tests post such bodies)."""
        check_scan_bytes(b"%PDF-1.4 fake")
        check_scan_bytes(b"not an image at all")

    def test_a_page_tree_with_a_missing_kids_object_is_not_rejected(self) -> None:
        """Regression: a document that opens but has a page that will not
        load used to crash 500 (`plan_pdf_pages` raised pypdfium2's own
        `PdfiumError` and only the outer `PdfDocument(data)` open was
        guarded). It must pass through like any other geometry this module
        cannot fully make sense of -- extraction fails on it later."""
        check_scan_bytes(pdf_with_missing_kid_object())

    def test_a_page_tree_with_an_inflated_count_is_not_rejected(self) -> None:
        check_scan_bytes(pdf_with_inflated_count())

    def test_an_encrypted_pdf_is_not_rejected(self) -> None:
        check_scan_bytes(encrypted_pdf_bytes())

    def test_bounds_are_the_documented_values(self) -> None:
        self.assertEqual((MAX_SCAN_PAGES, MAX_PAGE_PX, MAX_DECODE_PX), (40, 16_000_000, 40_000_000))


class ContentStreamBombTests(unittest.TestCase):
    """Task 11b: a small PDF whose page content inflates to hundreds of MB
    must be refused from its raw streams, without inflating it."""

    def test_bomb_pdf_is_small_but_inflates_far_past_the_cap(self) -> None:
        data = page_bomb_pdf(112_000_000)
        self.assertLess(len(data), 400_000)

    def test_a_page_content_bomb_is_rejected_quickly_without_inflating_it(self) -> None:
        data = page_bomb_pdf(112_000_000)
        tracemalloc.start()
        started = time.perf_counter()
        try:
            with self.assertRaises(ScanTooLargeError) as ctx:
                check_pdf_content_bytes(data)
            elapsed = time.perf_counter() - started
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertIn("drawing", str(ctx.exception))
        self.assertLess(elapsed, 2.0)
        self.assertLess(peak, 64_000_000)  # 1 MB chunks, never the 112 MB

    def test_a_form_xobject_bomb_is_rejected(self) -> None:
        with self.assertRaises(ScanTooLargeError):
            check_pdf_content_bytes(xobject_bomb_pdf(112_000_000))

    def test_a_form_xobject_reachable_twice_is_counted_once(self) -> None:
        # 5 MB once is under the 8 MB page cap; counted twice it would trip it.
        check_pdf_content_bytes(xobject_bomb_pdf(5_000_000))

    def test_page_and_scan_caps_are_the_documented_values(self) -> None:
        self.assertEqual((MAX_PAGE_CONTENT_BYTES, MAX_SCAN_CONTENT_BYTES), (8_000_000, 64_000_000))

    def test_content_just_under_the_page_cap_passes(self) -> None:
        check_pdf_content_bytes(page_bomb_pdf(MAX_PAGE_CONTENT_BYTES - 100_000))

    def test_the_scan_cap_binds_across_pages(self) -> None:
        # 9 pages x 7.5 MB = 67.5 MB: every page under its cap, the scan over its.
        raw = flate_bomb_ops(7_500_000)
        pages = [
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents {12 + i} 0 R >>"
            ).encode()
            for i in range(9)
        ]
        streams = [pdf_stream(b"/Filter /FlateDecode", raw) for _ in range(9)]
        kids = " ".join(f"{3 + i} 0 R" for i in range(9))
        objects = [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            f"<< /Type /Pages /Kids [{kids}] /Count 9 >>".encode(),
            *pages,
            *streams,
        ]
        with self.assertRaises(ScanTooLargeError) as ctx:
            check_pdf_content_bytes(assemble_pdf(objects))
        self.assertIn("whole scan", str(ctx.exception))

    def test_an_unfiltered_stream_is_measured_by_its_raw_length(self) -> None:
        check_pdf_content_bytes(filtered_page_pdf(b"", b"q /Im0 Do Q"))
        with self.assertRaises(ScanTooLargeError):
            check_pdf_content_bytes(filtered_page_pdf(b"", b"0 0 m 1 1 l S\n" * 700_000))

    def test_an_unknown_content_filter_is_rejected_as_unsupported(self) -> None:
        for entry in (b"/Filter /LZWDecode", b"/Filter [/ASCIIHexDecode /FlateDecode]"):
            with self.assertRaises(ScanUnsupportedEncodingError) as ctx:
                check_pdf_content_bytes(filtered_page_pdf(entry, b"00>"))
            self.assertIsInstance(ctx.exception, ScanRejectedError)
            self.assertIn("re-export", str(ctx.exception))
            # Fix round 1, minor: the raw filter token is attacker-controlled
            # PDF syntax, not information a re-export needs -- must not leak.
            self.assertNotIn("LZW", str(ctx.exception))
            self.assertNotIn("ASCIIHex", str(ctx.exception))

    def test_a_one_element_flate_array_is_accepted(self) -> None:
        # Fix round 1, minor: `[/FlateDecode]` is a legitimate spelling.
        check_pdf_content_bytes(filtered_page_pdf(b"/Filter [/FlateDecode]", flate_bomb_ops(1_000)))
        with self.assertRaises(ScanTooLargeError):
            check_pdf_content_bytes(
                filtered_page_pdf(b"/Filter [/FlateDecode]", flate_bomb_ops(9_000_000))
            )

    def test_the_fl_abbreviation_is_accepted(self) -> None:
        # Fix round 1, minor: `/Fl` is the inline-image abbreviation (Table 93).
        check_pdf_content_bytes(filtered_page_pdf(b"/Filter /Fl", flate_bomb_ops(1_000)))

    def test_an_indirect_filter_naming_flatedecode_is_accepted(self) -> None:
        # Fix round 1, minor: `/Filter 5 0 R` where object 5 is `/FlateDecode`.
        check_pdf_content_bytes(indirect_filter_page_pdf(flate_bomb_ops(1_000)))

    def test_a_corrupt_flate_stream_counts_what_it_yielded(self) -> None:
        # pdfium renders what it can of a truncated stream; so should the cap.
        truncated = flate_bomb_ops(100_000)[:-40]
        check_pdf_content_bytes(filtered_page_pdf(b"/Filter /FlateDecode", truncated))

    def test_unparseable_and_encrypted_bytes_pass(self) -> None:
        check_pdf_content_bytes(b"%PDF-1.4 fake")
        check_pdf_content_bytes(b"not a pdf")

    @unittest.skipUnless(_FIXTURE.is_file(), "handwritten-59 fixture not present")
    def test_the_committed_fixture_passes_with_room_to_spare(self) -> None:
        check_pdf_content_path(_FIXTURE)
        doc = pymupdf.open(str(_FIXTURE))
        try:
            largest = max(
                sum(
                    decoded_stream_size(doc, xref, budget=MAX_PAGE_CONTENT_BYTES, page_index=i)
                    for xref in doc[i].get_contents()
                )
                for i in range(doc.page_count)
            )
        finally:
            doc.close()
        self.assertLess(largest, 1_000)  # a scanned page is `q ... cm /Im0 Do Q`

    def test_check_scan_bytes_applies_the_content_cap_to_pdfs(self) -> None:
        with self.assertRaises(ScanTooLargeError):
            check_scan_bytes(page_bomb_pdf(112_000_000))


class ImageXObjectBombTests(unittest.TestCase):
    """Task 11b rev 2: an image XObject declaring more pixels than
    MAX_DECODE_PX is refused from its dictionary, on the page or inside a
    Form XObject, without reading the image stream."""

    def test_a_declared_1_6_gigapixel_image_is_rejected(self) -> None:
        data = image_bomb_pdf(40_000, 40_000)
        self.assertLess(len(data), 2_000)  # one grey pixel; only the header lies
        with self.assertRaises(ScanTooLargeError) as ctx:
            check_pdf_content_bytes(data)
        self.assertIn("megapixel", str(ctx.exception))

    def test_an_oversized_image_inside_a_form_xobject_is_rejected(self) -> None:
        with self.assertRaises(ScanTooLargeError):
            check_pdf_content_bytes(image_bomb_pdf(40_000, 40_000, nested=True))

    def test_a_600_dpi_a4_scan_image_passes(self) -> None:
        check_pdf_content_bytes(image_bomb_pdf(4_960, 7_016))  # 34.8 Mpx, under 40 Mpx

    def test_check_scan_bytes_applies_the_image_cap_to_pdfs(self) -> None:
        with self.assertRaises(ScanTooLargeError):
            check_scan_bytes(image_bomb_pdf(40_000, 40_000))


class AnnotationPatternType3BombTests(unittest.TestCase):
    """Fix round 1, Important 2: annotation appearance streams, tiling
    patterns and Type3 CharProcs must count toward the same content
    budgets -- both renderers (pdfium at extraction, pymupdf at the crop
    and preview routes) draw all three, not just page content and Form
    XObjects."""

    def test_an_annotation_appearance_stream_bomb_is_rejected(self) -> None:
        with self.assertRaises(ScanTooLargeError) as ctx:
            check_pdf_content_bytes(annot_ap_bomb_pdf(112_000_000))
        self.assertIn("drawing", str(ctx.exception))
        with self.assertRaises(ScanTooLargeError):
            check_scan_bytes(annot_ap_bomb_pdf(112_000_000))

    def test_a_tiling_pattern_bomb_is_rejected(self) -> None:
        with self.assertRaises(ScanTooLargeError) as ctx:
            check_pdf_content_bytes(tiling_pattern_bomb_pdf(112_000_000))
        self.assertIn("drawing", str(ctx.exception))
        with self.assertRaises(ScanTooLargeError):
            check_scan_bytes(tiling_pattern_bomb_pdf(112_000_000))

    def test_a_type3_charproc_bomb_is_rejected(self) -> None:
        with self.assertRaises(ScanTooLargeError) as ctx:
            check_pdf_content_bytes(type3_charproc_bomb_pdf(112_000_000))
        self.assertIn("drawing", str(ctx.exception))
        with self.assertRaises(ScanTooLargeError):
            check_scan_bytes(type3_charproc_bomb_pdf(112_000_000))

    def test_a_form_xobject_cycle_terminates(self) -> None:
        # Two Form XObjects referencing each other: must return, not hang.
        check_pdf_content_bytes(form_xobject_cycle_pdf())

    def test_a_form_xobject_drawn_many_times_is_counted_once(self) -> None:
        # 5 MB once is under the page cap; the page draws it 500 times, but
        # /Resources lists it once, so the walk visits (and counts) it once.
        # Repeated *rendering* cost is a separate, still-open concern -- see
        # repeated_xobject_pdf's docstring and the report's follow-up.
        check_pdf_content_bytes(repeated_xobject_pdf(times=500, inflated_bytes=5_000_000))

    def test_hitting_the_object_cap_is_rejected(self) -> None:
        with (
            patch.object(scan_limits, "_MAX_OBJECTS_PER_PAGE", 5),
            self.assertRaises(ScanTooLargeError) as ctx,
        ):
            check_pdf_content_bytes(many_form_xobjects_pdf(10))
        self.assertIn("drawing objects", str(ctx.exception))

    def test_well_under_the_object_cap_passes(self) -> None:
        with patch.object(scan_limits, "_MAX_OBJECTS_PER_PAGE", 5):
            check_pdf_content_bytes(many_form_xobjects_pdf(3))

    def test_an_indirect_xobject_dict_bomb_is_rejected(self) -> None:
        # Fix round 2, Important 1: /Resources << /XObject 6 0 R >> --
        # object 6 (not /Resources itself) is the name->ref map.
        with self.assertRaises(ScanTooLargeError):
            check_pdf_content_bytes(indirect_xobject_dict_bomb_pdf(112_000_000))
        with self.assertRaises(ScanTooLargeError):
            check_scan_bytes(indirect_xobject_dict_bomb_pdf(112_000_000))

    def test_an_indirect_ap_state_dict_bomb_is_rejected(self) -> None:
        # Fix round 2, Important 1: /AP << /N 6 0 R >> -- object 6 is the
        # /Off//On appearance-state dict, not the appearance stream itself.
        with self.assertRaises(ScanTooLargeError):
            check_pdf_content_bytes(indirect_ap_state_bomb_pdf(112_000_000))
        with self.assertRaises(ScanTooLargeError):
            check_scan_bytes(indirect_ap_state_bomb_pdf(112_000_000))

    def test_an_extgstate_smask_transparency_group_bomb_is_rejected(self) -> None:
        # Fix round 2, minor 1: /ExtGState -> /SMask -> /G is a Form
        # XObject the renderer draws.
        with self.assertRaises(ScanTooLargeError):
            check_pdf_content_bytes(extgstate_smask_bomb_pdf(112_000_000))
        with self.assertRaises(ScanTooLargeError):
            check_scan_bytes(extgstate_smask_bomb_pdf(112_000_000))


class ImageMaskBombTests(unittest.TestCase):
    """Fix round 1, Important 3: an image's /SMask and stream-valued /Mask
    are themselves image objects with their own declared size, and pdfium
    decodes each at that declared size to render it -- same rule as the
    image itself."""

    def test_a_declared_smask_bomb_is_rejected(self) -> None:
        with self.assertRaises(ScanTooLargeError) as ctx:
            check_pdf_content_bytes(smask_bomb_pdf(40_000, 40_000))
        self.assertIn("megapixel", str(ctx.exception))
        with self.assertRaises(ScanTooLargeError):
            check_scan_bytes(smask_bomb_pdf(40_000, 40_000))

    def test_a_600_dpi_smask_passes(self) -> None:
        check_pdf_content_bytes(smask_bomb_pdf(4_960, 7_016))  # 34.8 Mpx

    def test_an_smask_with_an_indirect_width_is_rejected(self) -> None:
        # Fix round 2, Important 2: /Width 7 0 R where object 7 is a bare
        # `40000` -- used to silently pass (kind != "int") without checking.
        with self.assertRaises(ScanTooLargeError) as ctx:
            check_pdf_content_bytes(indirect_smask_dimension_bomb_pdf(40_000, 40_000))
        self.assertIn("megapixel", str(ctx.exception))


class NonPdfDocumentTests(unittest.TestCase):
    """Fix round 1, Important 1: an image-type pymupdf document (the
    teacher console's preview route opens a PNG/JPEG upload the same way it
    opens a PDF) has no PDF page tree -- `page.get_contents()` asserts on
    one. `check_pdf_content` must return, not crash, so an image paper's
    preview stays a 200."""

    def test_a_png_document_is_left_alone(self) -> None:
        import pymupdf

        buf = io.BytesIO()
        Image.new("RGB", (100, 100), "white").save(buf, "PNG")
        doc = pymupdf.open(stream=buf.getvalue(), filetype="png")  # type: ignore[no-untyped-call]
        try:
            scan_limits.check_pdf_content(doc)
        finally:
            doc.close()  # type: ignore[no-untyped-call]


if __name__ == "__main__":
    unittest.main()
