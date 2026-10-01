"""Unit tests for lemely.io.pdf_canonical: the sanctioned openers and the rewrite.

Split from ``test_scan_limits.py`` (#262): ``open_checked_pdf`` and
``open_scan_image_document`` (the only ways user bytes reach MuPDF), the
whole-document check on bytes, and ``canonical_pdf_bytes``, MuPDF's
pages-only rewrite that pdfium renders.
"""

from __future__ import annotations

import contextlib
import io
import unittest
from unittest.mock import patch

import pymupdf
import pypdfium2 as pdfium
from PIL import Image, UnidentifiedImageError

import lemely.io.pdf_content_walk as pdf_content_walk
from lemely.io import scan_limits
from lemely.io._scan_common import (
    ScanRejectedError,
    ScanTooLargeError,
    ScanUnsupportedFormatError,
)
from lemely.io.pdf_canonical import (
    canonical_pdf_bytes,
    check_pdf_content_bytes,
    open_checked_pdf,
    open_scan_image_document,
)
from lemely.io.pdf_content_walk import check_pdf_content, check_pdf_page_content
from lemely.io.scan_limits import MAX_SCAN_PAGES, check_scan_bytes
from tests.pdf_fakes import (
    born_digital_text_pdf,
    empty_page_tree_pdf,
    encrypted_pdf_bytes,
    hidden_layer_pdf,
    ico_wrapping,
    many_objects_pdf,
    off_page_object_pdf,
    shared_container_broken_xref_pdf,
    uncounted_bomb_pdf,
    xref_repair_bomb_pdf,
)
from tests.test_scan_limits import _pdf_bytes, _readers_trapped


class CanonicalPdfBytesTests(unittest.TestCase):
    """Task 9c: MuPDF's rewrite of a PDF, so pdfium renders exactly the
    objects MuPDF measured, whatever either reader's xref repair would do."""

    def _pdfium_objects(self, data: bytes) -> int:
        pdf = pdfium.PdfDocument(data)
        try:
            page = pdf[0]
            try:
                return sum(1 for _ in page.get_objects())
            finally:
                page.close()
        finally:
            pdf.close()

    def test_the_rewrite_holds_the_object_mupdf_measured(self) -> None:
        """19-byte xref entries: MuPDF reads the xref (object 4 is the clean
        rectangle); the rewrite has one clean xref and that one object 4, so
        pdfium draws one rectangle. A small bomb stands in: the object count
        is what differs."""
        for eol in (b"\n", b"\r"):
            data = xref_repair_bomb_pdf(200_000, entry_eol=eol)
            with self.subTest(entry_eol=eol):
                self.assertGreater(self._pdfium_objects(data), 1)  # the premise
                self.assertEqual(self._pdfium_objects(canonical_pdf_bytes(data)), 1)

    def test_an_ordinary_pdf_keeps_its_pages(self) -> None:
        data = born_digital_text_pdf(pages=3)
        canonical = canonical_pdf_bytes(data)
        with pymupdf.open(stream=canonical, filetype="pdf") as doc:  # type: ignore[no-untyped-call]
            self.assertEqual(doc.page_count, 3)
            self.assertIn("quick brown fox", doc[2].get_text())

    def test_bytes_mupdf_cannot_open_or_rewrite_are_refused(self) -> None:
        for label, data in (("garbage", b"%PDF-1.4 fake"), ("encrypted", encrypted_pdf_bytes())):
            with self.subTest(label), self.assertRaises(ScanRejectedError):
                canonical_pdf_bytes(data)

    def test_a_pdf_with_no_pages_is_a_value_error(self) -> None:
        """Extraction's contract: a PDF neither reader finds a page in is a
        ``ValueError``. Pages pdfium finds but MuPDF does not are pages MuPDF
        never measured: refused, not called empty."""
        with self.assertRaises(ValueError) as caught:
            canonical_pdf_bytes(empty_page_tree_pdf())
        self.assertNotIsInstance(caught.exception, ScanRejectedError)
        # Refused by the whole-document check that runs first:
        # the tree holds two pages MuPDF does not number.
        with self.assertRaises(ScanRejectedError):
            canonical_pdf_bytes(uncounted_bomb_pdf(200_000, count_entry=b"/Count 0"))

    def test_a_pdf_with_too_many_objects_is_refused_before_it_is_rewritten(self) -> None:
        """The rewrite costs time per object in the file (13.7 s for 200,000
        small ones), so past ``MAX_PDF_OBJECTS`` the file is refused first."""
        with (
            patch.object(pymupdf.Document, "tobytes") as tobytes,
            self.assertRaises(ScanTooLargeError),
        ):
            canonical_pdf_bytes(many_objects_pdf(scan_limits.MAX_PDF_OBJECTS))
        tobytes.assert_not_called()
        canonical_pdf_bytes(many_objects_pdf(1_000))


class CheckedOpenerTests(unittest.TestCase):
    """``open_checked_pdf`` and ``open_scan_image_document``: every MuPDF open of
    user bytes goes through one of them (the sweep in ``test_scan_limits.py``
    holds ``lemely/`` to that), so neither may let MuPDF repair a PDF before
    the raw pre-scan has bounded its object streams."""

    _BOMB = scan_limits.MAX_OBJECT_STREAM_BYTES // 2 + 1_000

    def _trapped(self) -> contextlib.ExitStack:
        """Fail the test if any reader opens the file."""
        return _readers_trapped()

    def test_open_checked_pdf_refuses_a_container_bomb_before_mupdf_opens_it(self) -> None:
        """Final review, item 4: the one way to open user PDF bytes with MuPDF
        runs the raw pre-scan first, so the bomb is refused and
        ``pymupdf.open`` is never reached."""
        data = shared_container_broken_xref_pdf(self._BOMB)
        with self._trapped(), self.assertRaises(ScanTooLargeError) as caught:
            open_checked_pdf(data)
        self.assertEqual(str(caught.exception), scan_limits._OBJECT_STREAMS_MESSAGE)

    def test_open_checked_pdf_opens_a_clean_pdf(self) -> None:
        with open_checked_pdf(_pdf_bytes((595.0, 842.0), (595.0, 842.0))) as doc:
            self.assertTrue(doc.is_pdf)
            self.assertEqual(doc.page_count, 2)

    def test_open_scan_image_document_never_opens_a_pdf(self) -> None:
        """The preview's image path: an allowlisted image opens as a one-page
        image document; PDF bytes -- which MuPDF would repair while opening,
        before any pre-scan -- are refused before MuPDF sees them, as is a
        format outside the allowlist."""
        buf = io.BytesIO()
        Image.new("L", (40, 30), 200).save(buf, "PNG")
        with open_scan_image_document(buf.getvalue()) as doc:
            self.assertFalse(doc.is_pdf)
            self.assertEqual(doc.page_count, 1)
        refused: tuple[tuple[bytes, type[Exception]], ...] = (
            (shared_container_broken_xref_pdf(self._BOMB), UnidentifiedImageError),
            (ico_wrapping(buf.getvalue()), ScanUnsupportedFormatError),
        )
        for data, error in refused:
            with self.subTest(error=error.__name__), self._trapped(), self.assertRaises(error):
                open_scan_image_document(data)


class RewriteFidelityTests(unittest.TestCase):
    """Hidden optional content: pdfium must render the rewrite exactly as it
    renders the stored file -- including what the file says to hide."""

    def _pdfium_grey(self, data: bytes) -> list[bytes]:
        pdf = pdfium.PdfDocument(data)
        try:
            pages = []
            for index in range(len(pdf)):
                page = pdf[index]
                try:
                    bitmap = page.render(scale=0.5)
                    try:
                        pages.append(bitmap.to_pil().convert("L").tobytes())
                    finally:
                        bitmap.close()
                finally:
                    page.close()
            return pages
        finally:
            pdf.close()

    def test_layers_hidden_by_default_stay_hidden(self) -> None:
        """Content on an optional-content layer that is OFF by default --
        text and a filled rectangle, or an image XObject and an annotation --
        renders from the rewrite exactly as from the stored file: hidden.
        Losing the catalog's ``/OCProperties`` would show it to the marker
        while the teacher's preview does not."""
        for variant in ("text", "image"):
            data = hidden_layer_pdf(variant=variant)
            with self.subTest(variant=variant):
                stored = self._pdfium_grey(data)
                rewritten = self._pdfium_grey(canonical_pdf_bytes(data))
                self.assertEqual(len(rewritten), len(stored))
                differing = [
                    sum(a != b for a, b in zip(x, y, strict=True))
                    for x, y in zip(stored, rewritten, strict=True)
                ]
                self.assertEqual(differing, [0] * len(stored), "grey bytes differing per page")


class OffPageObjectTests(unittest.TestCase):
    """Objects no page reaches: extraction's rewrite may parse only what the
    content check has bounded -- the pages and what they draw from -- and
    compressed object data is bounded before anything parses it."""

    def test_objects_no_page_reaches_are_not_carried_into_the_rewrite(self) -> None:
        """A big object hung off the catalog, or off a page-dict key no
        renderer reads, in any shape, compressed or not: the rewrite copies
        pages, so it never resolves it, and its output stays small."""
        for holder in ("catalog", "page"):
            for compressed in (True, False):
                for shape, elements in (
                    ("array", 2_000_000),
                    ("string", 2_000_000),
                    ("dict", 100_000),
                ):
                    data = off_page_object_pdf(
                        elements, shape=shape, compressed=compressed, holder=holder
                    )
                    with self.subTest(holder=holder, compressed=compressed, shape=shape):
                        canonical = canonical_pdf_bytes(data)
                        self.assertLess(len(canonical), 20_000)
                        with pymupdf.open(stream=canonical, filetype="pdf") as doc:  # type: ignore[no-untyped-call]
                            self.assertEqual(doc.page_count, 1)

    def test_an_object_stream_bomb_is_refused_before_anything_parses_it(self) -> None:
        """An object stream that inflates past ``MAX_OBJECT_STREAM_BYTES``
        is measured with the bounded inflate and refused -- at upload, in
        the whole-document and page-scoped checks, and at extraction --
        before the page tree is read or the file rewritten."""
        elements = scan_limits.MAX_OBJECT_STREAM_BYTES // 2 + 1_000
        data = off_page_object_pdf(elements, compressed=True)
        self.assertLess(len(data), 100_000)
        with (
            patch.object(pdf_content_walk, "_page_tree") as page_tree,
            patch.object(pymupdf.Document, "tobytes") as tobytes,
        ):
            for check in (check_scan_bytes, check_pdf_content_bytes, canonical_pdf_bytes):
                with self.subTest(check.__name__):
                    with self.assertRaises(ScanTooLargeError) as caught:
                        check(data)
                    self.assertEqual(str(caught.exception), scan_limits._OBJECT_STREAMS_MESSAGE)
            with (
                pymupdf.open(stream=data, filetype="pdf") as doc,  # type: ignore[no-untyped-call]
                self.assertRaises(ScanTooLargeError),
            ):
                check_pdf_page_content(doc, 0)
        page_tree.assert_not_called()
        tobytes.assert_not_called()

    def test_ordinary_object_streams_pass(self) -> None:
        """A born-digital 40-page PDF written with object streams and an xref
        stream passes upload and rewrites to its 40 pages."""
        with pymupdf.open(
            stream=born_digital_text_pdf(pages=MAX_SCAN_PAGES), filetype="pdf"
        ) as doc:  # type: ignore[no-untyped-call]
            data: bytes = doc.tobytes(garbage=1, use_objstms=1)  # type: ignore[no-untyped-call]
        check_scan_bytes(data)
        with pymupdf.open(stream=canonical_pdf_bytes(data), filetype="pdf") as doc:  # type: ignore[no-untyped-call]
            self.assertEqual(doc.page_count, MAX_SCAN_PAGES)


class NonPdfDocumentTests(unittest.TestCase):
    """An image-type pymupdf document (the
    teacher console's preview route opens a PNG/JPEG upload the same way it
    opens a PDF) has no PDF page tree -- `page.get_contents()` asserts on
    one. `check_pdf_content` must return, not crash, so an image paper's
    preview stays a 200."""

    def test_a_png_document_is_left_alone(self) -> None:
        buf = io.BytesIO()
        Image.new("RGB", (100, 100), "white").save(buf, "PNG")
        doc = pymupdf.open(stream=buf.getvalue(), filetype="png")  # type: ignore[no-untyped-call]
        try:
            check_pdf_content(doc)
        finally:
            doc.close()  # type: ignore[no-untyped-call]


if __name__ == "__main__":
    unittest.main()
