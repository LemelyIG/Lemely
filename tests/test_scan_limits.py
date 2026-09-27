"""Unit tests for lemely.io.scan_limits (spec 2026-09-26 §6)."""

from __future__ import annotations

import io
import re
import unittest
from unittest.mock import patch

import pymupdf
import pypdfium2 as pdfium
from PIL import Image

from lemely.io.scan_limits import (
    MAX_DECODE_PX,
    MAX_PAGE_PX,
    MAX_SCAN_PAGES,
    ScanTooLargeError,
    check_scan_bytes,
    plan_image,
    plan_page_dpi,
    plan_pdf_pages,
)


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


def _hand_rolled_pdf(kids: str, count: int, xref_size: int) -> bytes:
    """A minimal, hand-written PDF whose page tree can be deliberately broken.

    ``pypdfium2``/Pillow can only *write* well-formed documents, so a
    malformed page tree -- one real ``/Type /Page`` object (object 3) plus a
    ``/Pages`` node whose ``kids``/``count`` a caller controls -- has to be
    built as raw bytes. The offsets in the ``xref`` table are computed from
    the actual object positions, so the document opens cleanly; only the
    page tree itself is broken.
    """
    body = (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        + f"2 0 obj\n<< /Type /Pages /Kids [{kids}] /Count {count} >>\nendobj\n".encode()
        + b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << >> >>\nendobj\n"
    )
    offsets = {int(m.group(1)): m.start() for m in re.finditer(rb"(\d+) 0 obj", body)}
    xref_lines = [b"0000000000 65535 f \n"]
    for n in range(1, xref_size):
        xref_lines.append(f"{offsets.get(n, 0):010d} 00000 n \n".encode())
    xref = f"xref\n0 {xref_size}\n".encode() + b"".join(xref_lines)
    trailer = (
        f"trailer\n<< /Size {xref_size} /Root 1 0 R >>\nstartxref\n".encode()
        + str(len(body)).encode()
        + b"\n%%EOF"
    )
    return body + xref + trailer


def _pdf_with_missing_kid_object() -> bytes:
    """A page tree whose second ``/Kids`` entry (object 4) is never defined.

    Opens fine (``/Count`` says 2 pages); reading page index 1's size fails
    inside pypdfium2 with a ``PdfiumError`` ("Failed to get page size by
    index."), reproduced against the real library before writing this test.
    """
    return _hand_rolled_pdf(kids="3 0 R 4 0 R", count=2, xref_size=5)


def _pdf_with_inflated_count() -> bytes:
    """A page tree whose ``/Count`` (2) overstates its real ``/Kids`` array (1).

    Same failure as :func:`_pdf_with_missing_kid_object`, reached a different
    way: reading page index 1's size fails because there is no second kid at
    all, not because a specific object is missing.
    """
    return _hand_rolled_pdf(kids="3 0 R", count=2, xref_size=4)


def _encrypted_pdf_bytes() -> bytes:
    """A genuinely password-protected PDF.

    pypdfium2 has no API to *write* an encrypted PDF, but pymupdf (already a
    dependency, used by ``lemely.web.routers.review``) does. Opening this
    without the password fails at ``PdfDocument(data)`` itself (PDFium:
    "Incorrect password"), before ``plan_pdf_pages`` is ever reached.
    """
    doc = pymupdf.open()
    doc.new_page(width=595, height=842)
    buf = io.BytesIO()
    doc.save(buf, encryption=pymupdf.PDF_ENCRYPT_RC4_128, user_pw="secret")
    doc.close()
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
        check_scan_bytes(_pdf_with_missing_kid_object())

    def test_a_page_tree_with_an_inflated_count_is_not_rejected(self) -> None:
        check_scan_bytes(_pdf_with_inflated_count())

    def test_an_encrypted_pdf_is_not_rejected(self) -> None:
        check_scan_bytes(_encrypted_pdf_bytes())

    def test_bounds_are_the_documented_values(self) -> None:
        self.assertEqual((MAX_SCAN_PAGES, MAX_PAGE_PX, MAX_DECODE_PX), (40, 16_000_000, 40_000_000))


if __name__ == "__main__":
    unittest.main()
