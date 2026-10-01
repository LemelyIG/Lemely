"""Unit tests for lemely.io.pdf_canonical: the sanctioned openers and the rewrite.

Split from ``test_scan_limits.py`` (#262): ``open_checked_pdf`` and
``open_scan_image_document`` (the only ways user bytes reach MuPDF), the
whole-document check on bytes, and ``canonical_pdf_bytes``, MuPDF's
pages-only rewrite that pdfium renders.
"""

from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pymupdf
import pypdfium2 as pdfium
from PIL import Image, UnidentifiedImageError

import lemely.io.pdf_canonical as pdf_canonical
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
from lemely.io.rasterise import rasterise_pdf_to_pages
from lemely.io.scan_limits import MAX_SCAN_PAGES, check_scan_bytes
from tests.fakes_reader_agreement import (
    dark_pixels,
    differing_bytes,
    mupdf_grey,
    mupdf_size,
    oc_hidden_bomb_pdf,
    ocmd_image_pdf,
    pdfium_grey,
    pdfium_size,
    visible_layer_text_pdf,
)
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
        """Pins the ``/OCProperties`` graft: text and a filled rectangle on a
        layer that is OFF by default, drawn inside marked content
        (``/OC /name BDC``), render from the rewrite exactly as from the
        stored file under pdfium -- hidden -- because the rewrite carries the
        catalog's default configuration. Without it every layer renders.

        The ``image`` variant is not compared pdfium with pdfium any more:
        pdfium draws its hidden annotation from the stored file, and the
        rewrite drops it (#274), so the two now differ by design --
        ``ReaderAgreementTests`` holds the rewrite to MuPDF's view instead."""
        for variant in ("text",):
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


def _pdfium_page_count(data: bytes) -> int:
    pdf = pdfium.PdfDocument(data)
    try:
        return len(pdf)
    finally:
        pdf.close()


#: Differing grey bytes allowed between pdfium's render of the rewrite and
#: MuPDF's of the stored file beyond what anti-aliasing alone costs: the two
#: readers round an image's edge to different pixel rows (100 bytes on the
#: OCMD fixture's square at scale 0.5).
_AGREEMENT_SLACK = 200

#: The OCMD cases where MuPDF 1.29 departs from the policy the PDF spec
#: defines (and pdfium follows): it shows an ``/AllOn`` member whatever its
#: groups' states and hides an ``/AnyOff`` member likewise. The rewrite keeps
#: the spec's rule, so on these two the marker and the teacher still differ;
#: the test pins that, so an upstream fix shows up here.
_MUPDF_OCMD_DEVIATIONS = {("AllOn", (True, False)), ("AnyOff", (True, False))}


class ReaderAgreementTests(unittest.TestCase):
    """#274 hidden content: the marker reads pdfium's render of the rewrite,
    the teacher MuPDF's render of the stored file, and they must see the
    same picture. pdfium hides an image or form XObject whose ``/OC`` is
    off, but draws an annotation whatever its ``/OC`` says; MuPDF hides
    both. So the rewrite drops what the default configuration hides."""

    def _rasterised_vs_mupdf(self, data: bytes) -> int:
        """Differing grey bytes: extraction's page 0 against MuPDF's render
        of the stored file at the same pixel size."""
        with tempfile.TemporaryDirectory() as scratch:
            path = Path(scratch) / "scan.pdf"
            path.write_bytes(data)
            page = rasterise_pdf_to_pages(path)[0]
        with Image.open(io.BytesIO(page.png_bytes)) as image:
            marker = image.convert("L").tobytes()
        # pdfium's own scale: width / 595 is 1653 / 595, a hair over it, and
        # makes MuPDF round the A4 height up to one row more than pdfium.
        zoom = page.dpi / 72
        self.assertEqual(mupdf_size(data, 0, zoom=zoom), (page.width, page.height))
        return differing_bytes(marker, mupdf_grey(data, 0, zoom=zoom))

    def test_the_marker_sees_what_the_teacher_sees_for_a_hidden_image_layer(self) -> None:
        """Extraction's render of the ``image`` variant differs from MuPDF's
        by no more than the ``text`` variant's does (anti-aliasing of the
        visible text, which both share) plus the slack. Before the prune
        pdfium drew the hidden square annotation: tens of thousands of
        bytes apart."""
        text = self._rasterised_vs_mupdf(hidden_layer_pdf(variant="text"))
        image = self._rasterised_vs_mupdf(hidden_layer_pdf(variant="image"))
        self.assertLessEqual(image, text + _AGREEMENT_SLACK, f"text variant: {text}")

    def test_the_hidden_image_is_absent_from_the_rewrite_under_pdfium(self) -> None:
        """The inverse of ``test_layers_hidden_by_default_stay_hidden``:
        pdfium draws the stored ``image`` variant's hidden annotation, and
        draws nothing hidden from the rewrite -- no more ink than the file
        with only its visible layer."""
        data = hidden_layer_pdf(variant="image")
        size = pdfium_size(data, 0, scale=0.5)
        rewrite = dark_pixels(pdfium_grey(canonical_pdf_bytes(data), 0, scale=0.5), size)
        visible = dark_pixels(pdfium_grey(visible_layer_text_pdf(), 0, scale=0.5), size)
        stored = dark_pixels(pdfium_grey(data, 0, scale=0.5), size)
        self.assertLessEqual(rewrite, visible)
        self.assertLess(rewrite, stored)

    def test_an_oc_hidden_content_bomb_is_still_refused_by_the_walk(self) -> None:
        """Hidden is not harmless: a renderer may parse what it does not
        draw, so the walk measures a hidden form as any other, before the
        rewrite prunes anything."""
        with self.assertRaises(ScanTooLargeError):
            canonical_pdf_bytes(oc_hidden_bomb_pdf(112_000_000))

    def test_ocmd_policies_decide_what_the_rewrite_drops(self) -> None:
        """Each ``/OCMD`` policy over two groups (and ``/BaseState /OFF``
        over one): pdfium's render of the rewrite has ink exactly when the
        policy shows the square, and matches MuPDF's render of the stored
        file -- except where MuPDF departs from the spec
        (:data:`_MUPDF_OCMD_DEVIATIONS`). Both holders: an image XObject,
        which pdfium hides itself, and an annotation, which only the prune
        hides."""
        cases: tuple[tuple[str, tuple[bool, ...], bool, bool], ...] = (
            ("AnyOn", (False, False), False, False),
            ("AnyOn", (True, False), False, True),
            ("AllOn", (True, False), False, False),
            ("AllOn", (True, True), False, True),
            ("AnyOff", (True, True), False, False),
            ("AnyOff", (True, False), False, True),
            ("AllOff", (True, False), False, False),
            ("AllOff", (False, False), False, True),
            ("AnyOn", (False,), True, False),
        )
        for policy, states, base_state_off, shown in cases:
            for annotation in (False, True):
                data = ocmd_image_pdf(
                    policy, states, base_state_off=base_state_off, annotation=annotation
                )
                with self.subTest(
                    policy=policy,
                    states=states,
                    base_state_off=base_state_off,
                    annotation=annotation,
                ):
                    size = pdfium_size(data, 0, scale=0.5)
                    marker = pdfium_grey(canonical_pdf_bytes(data), 0, scale=0.5)
                    teacher = mupdf_grey(data, 0, zoom=0.5)
                    self.assertEqual(dark_pixels(marker, size) > 0, shown)
                    if (policy, states) in _MUPDF_OCMD_DEVIATIONS:
                        self.assertNotEqual(dark_pixels(teacher, size) > 0, shown)
                    else:
                        self.assertLessEqual(differing_bytes(marker, teacher), _AGREEMENT_SLACK)

    def test_the_prune_runs_on_the_copy_after_the_walk_and_loads_no_page(self) -> None:
        """The prune reads dictionaries only: no page is loaded (loading
        parses content and may regenerate an appearance), it runs after the
        whole-document check has bounded the original, and it edits the
        copy -- the source document still holds what the copy lost."""
        events: list[str] = []
        sources: list[pymupdf.Document] = []
        real_walk = pdf_canonical.check_pdf_content
        real_copy = pdf_canonical._copy_pages
        real_prune = pdf_canonical._prune_hidden_optional_content

        def walk(doc: pymupdf.Document, **kwargs: object) -> None:
            events.append("walk")
            real_walk(doc, **kwargs)  # type: ignore[arg-type]

        def copy(doc: pymupdf.Document) -> bytes:
            events.append("copy")
            sources.append(doc)
            return real_copy(doc)

        def annots(document: object) -> int:
            page = pymupdf.mupdf.pdf_lookup_page_obj(document, 0)  # type: ignore[no-untyped-call]
            return int(pymupdf.mupdf.pdf_array_len(pymupdf.mupdf.pdf_dict_gets(page, "Annots")))  # type: ignore[no-untyped-call]

        def prune(target: object, hidden: set[int]) -> None:
            events.append("prune")
            no_load = AssertionError("the prune loaded a page")
            with (
                patch.object(pymupdf.Document, "load_page", side_effect=no_load),
                patch.object(pymupdf.mupdf, "pdf_load_page", side_effect=no_load),
                patch.object(pymupdf.mupdf, "fz_load_page", side_effect=no_load),
            ):
                real_prune(target, hidden)  # type: ignore[arg-type]
            source = pymupdf.mupdf.pdf_document_from_fz_document(sources[0].this)  # type: ignore[no-untyped-call]
            self.assertEqual(annots(source), 1)
            self.assertEqual(annots(target), 0)

        with (
            patch.object(pdf_canonical, "check_pdf_content", side_effect=walk),
            patch.object(pdf_canonical, "_copy_pages", side_effect=copy),
            patch.object(pdf_canonical, "_prune_hidden_optional_content", side_effect=prune),
        ):
            canonical_pdf_bytes(hidden_layer_pdf(variant="image"))
        self.assertEqual(events, ["walk", "copy", "prune"])

    def test_every_committed_pdf_renders_identically_through_the_rewrite(self) -> None:
        """Regression guard for the prune: every PDF committed under
        ``tests/`` renders byte-identical under pdfium from the rewrite and
        from the stored file, page by page."""
        paths = sorted(Path(__file__).parent.rglob("*.pdf"))
        self.assertTrue(paths)
        pages = 0
        for path in paths:
            data = path.read_bytes()
            with self.subTest(path=str(path)):
                rewrite = canonical_pdf_bytes(data)
                count = _pdfium_page_count(data)
                self.assertEqual(_pdfium_page_count(rewrite), count)
                for index in range(count):
                    self.assertEqual(
                        pdfium_grey(rewrite, index, scale=0.5),
                        pdfium_grey(data, index, scale=0.5),
                        f"page {index}",
                    )
                pages += count
        self.assertGreater(pages, 0)


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
