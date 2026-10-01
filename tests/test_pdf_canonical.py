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
    _STRUCTURE_TOO_COMPLEX_MESSAGE,
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
    direct_ocmd_annotations_pdf,
    mupdf_grey,
    mupdf_size,
    oc_annotation_flood_pdf,
    oc_hidden_bomb_pdf,
    ocmd_cycle_pdf,
    ocmd_image_pdf,
    optional_content_square_pdf,
    pdfium_grey,
    pdfium_size,
    shared_resources_pdf,
    visible_layer_text_pdf,
    with_all_on_optional_content,
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

#: Where the marker still sees less than the teacher (#274 controller
#: decision): an image MuPDF 1.29 shows but pdfium hides by itself, which
#: the prune cannot undo -- it can only hide. MuPDF shows an ``/AllOn``
#: member over an array whatever its groups' states, and over a single
#: reference it shows an ``/AllOn`` or ``/AllOff`` member exactly when the
#: group is OFF; pdfium hides all three. Annotations never deviate: pdfium
#: draws them whatever their ``/OC`` says, so the prune decides alone.
#: Measured, and pinned so a change in either reader shows up here.
_MARKER_SEES_LESS = {
    ("AllOn", (True, False), "array", "image"),
    ("AllOn", (False,), "single", "image"),
    ("AllOff", (False,), "single", "image"),
}

#: The same for :meth:`ReaderAgreementTests.test_group_states_decide_what_the_rewrite_drops`:
#: MuPDF shows what an ``/OC`` lacking ``/Type /OCG`` governs, even when
#: ``/D /OFF`` names it; pdfium hides such an image.
_GROUP_MARKER_SEES_LESS = {("off, untyped", "image")}


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

    def _assert_marker_matches_teacher(
        self, data: bytes, *, teacher_shows: bool, marker_sees_less: bool = False
    ) -> None:
        """pdfium's render of the rewrite against MuPDF's of the stored file.

        ``teacher_shows`` pins what MuPDF draws. Unless ``marker_sees_less``
        the two renders agree within the slack; with it, the marker has no
        ink where the teacher has some (the one direction the prune cannot
        close). Never may the marker see what the teacher does not.
        """
        size = pdfium_size(data, 0, scale=0.5)
        marker = pdfium_grey(canonical_pdf_bytes(data), 0, scale=0.5)
        teacher = mupdf_grey(data, 0, zoom=0.5)
        self.assertEqual(dark_pixels(teacher, size) > 0, teacher_shows, "MuPDF's view moved")
        if marker_sees_less:
            self.assertEqual(dark_pixels(marker, size), 0)
        else:
            self.assertLessEqual(differing_bytes(marker, teacher), _AGREEMENT_SLACK)

    def test_ocmd_policies_decide_what_the_rewrite_drops(self) -> None:
        """Each ``/OCMD`` policy -- and no ``/P`` at all, which is
        ``/AnyOn`` -- over an array of groups and over a single reference,
        with ``/BaseState /OFF`` and with a ``/VE`` array: the rewrite drops
        what MuPDF hides, so the marker matches the teacher, except where
        MuPDF shows an image pdfium hides by itself
        (:data:`_MARKER_SEES_LESS`). Both holders: an image XObject, which
        pdfium hides itself, and an annotation, which only the prune hides.
        The last column is MuPDF's verdict, measured, where it departs from
        the spec: ``/AllOn`` over an array always shows, ``/AnyOff`` over an
        array always hides, a single reference inverts ``/AllOn``, and a
        ``/VE`` array always shows."""
        cases: tuple[tuple[str, tuple[bool, ...], dict[str, bool], bool], ...] = (
            ("AnyOn", (False, False), {}, False),
            ("AnyOn", (True, False), {}, True),
            ("AllOn", (True, False), {}, True),
            ("AllOn", (True, True), {}, True),
            ("AnyOff", (True, True), {}, False),
            ("AnyOff", (True, False), {}, False),
            ("AllOff", (True, False), {}, False),
            ("AllOff", (False, False), {}, True),
            ("AnyOn", (False,), {"base_state_off": True}, False),
            ("", (False, False), {}, False),
            ("", (True, False), {}, True),
            ("AnyOn", (True,), {"single": True}, True),
            ("AnyOn", (False,), {"single": True}, False),
            ("AllOn", (True,), {"single": True}, False),
            ("AllOn", (False,), {"single": True}, True),
            ("AnyOff", (True,), {"single": True}, True),
            ("AnyOff", (False,), {"single": True}, False),
            ("AllOff", (True,), {"single": True}, False),
            ("AllOff", (False,), {"single": True}, True),
            ("AnyOn", (False,), {"visibility_expression": True}, True),
        )
        for policy, states, options, teacher_shows in cases:
            shape = "single" if options.get("single") else "array"
            for holder in ("image", "annotation"):
                data = ocmd_image_pdf(policy, states, annotation=holder == "annotation", **options)
                with self.subTest(policy=policy, states=states, holder=holder, **options):
                    self._assert_marker_matches_teacher(
                        data,
                        teacher_shows=teacher_shows,
                        marker_sees_less=(policy, states, shape, holder) in _MARKER_SEES_LESS,
                    )

    def test_group_states_decide_what_the_rewrite_drops(self) -> None:
        """The group itself, as MuPDF judges it: a ``/Usage /View
        /ViewState /OFF`` hides a group ``/D`` turns ON (with or without a
        ``/D /AS`` View event naming it); a group ``/D`` turns OFF but
        ``/OCProperties /OCGs`` does not list, or an ``/OC`` object that is
        not ``/Type /OCG``, is shown. Both holders."""
        usage_off = b"<< /Type /OCG /Name (g) /Usage << /View << /ViewState /OFF >> >> >>"
        view_event = b" /AS [<< /Event /View /Category [/View] /OCGs [7 0 R] >>]"
        group = b"<< /Type /OCG /Name (g) >>"
        cases: tuple[tuple[str, list[bytes], bytes, bool], ...] = (
            ("usage off", [usage_off], b"<< /OCGs [7 0 R] /D << /ON [7 0 R] >> >>", False),
            (
                "usage off, view event",
                [usage_off],
                b"<< /OCGs [7 0 R] /D << /ON [7 0 R]" + view_event + b" >> >>",
                False,
            ),
            ("off, not listed", [group, group], b"<< /OCGs [8 0 R] /D << /OFF [7 0 R] >> >>", True),
            (
                "off, untyped",
                [b"<< /Name (g) >>"],
                b"<< /OCGs [7 0 R] /D << /OFF [7 0 R] >> >>",
                True,
            ),
        )
        for label, objects, properties, teacher_shows in cases:
            for holder in ("image", "annotation"):
                data = optional_content_square_pdf(
                    b"7 0 R", objects, properties=properties, annotation=holder == "annotation"
                )
                with self.subTest(label, holder=holder):
                    self._assert_marker_matches_teacher(
                        data,
                        teacher_shows=teacher_shows,
                        marker_sees_less=(label, holder) in _GROUP_MARKER_SEES_LESS,
                    )

    def _assert_refused_as_malformed(self, data: bytes) -> None:
        """Refused at upload (``check_scan_bytes``) and at extraction alike."""
        for check in (check_scan_bytes, canonical_pdf_bytes):
            with self.subTest(check=check.__name__):
                with self.assertRaises(ScanRejectedError) as caught:
                    check(data)
                self.assertEqual(caught.exception.reason, "malformed")
                self.assertEqual(str(caught.exception), _STRUCTURE_TOO_COMPLEX_MESSAGE)

    def test_a_reference_flood_is_refused_and_a_page_at_the_cap_is_judged_once(self) -> None:
        """The reviewer's 49 KB probe -- 4,000 references to one annotation,
        governed by an ``/OCMD`` naming one group 4,000 times -- cost 29 s
        when every annotation re-walked the whole array. An ``/Annots`` or
        ``/OCGs`` array past 1,000 entries is refused as malformed, at upload
        too; at the cap each object is judged once. Counted, not timed: the
        membership dictionary and its group are each judged once by the
        bounds check on the original and once by the prune of the copy."""
        for annots, groups in ((4_000, 4_000), (4_000, 1), (1, 4_000)):
            with self.subTest(annotations=annots, groups=groups):
                self._assert_refused_as_malformed(oc_annotation_flood_pdf(annots, groups))
        calls: list[object] = []
        real = pdf_canonical._oc_hidden

        def counted(*args: object, **kwargs: object) -> bool:
            calls.append(args[0])
            return real(*args, **kwargs)  # type: ignore[arg-type]

        with patch.object(pdf_canonical, "_oc_hidden", side_effect=counted):
            canonical_pdf_bytes(oc_annotation_flood_pdf(1_000, 1_000))
        self.assertEqual(len(calls), 4)
        for variant in ("text", "image"):
            check_scan_bytes(hidden_layer_pdf(variant=variant))  # ordinary layers pass

    def test_a_membership_cycle_is_refused_whichever_annotation_comes_first(self) -> None:
        """A = ``/AllOff [B]``, B = ``/AnyOn [A g]``, g OFF: MuPDF shows
        neither annotation, but a walk that cut the cycle at A and cached B
        showed B's annotation to the marker (2,550 dark pixels against the
        teacher's 0) when it came second. The spec allows no membership
        dictionary inside another, so any cycle is refused, in both
        ``/Annots`` orders."""
        for governed_by_b_first in (True, False):
            with self.subTest(governed_by_b_first=governed_by_b_first):
                self._assert_refused_as_malformed(
                    ocmd_cycle_pdf(governed_by_b_first=governed_by_b_first)
                )

    def test_direct_membership_dictionaries_are_bounded_by_the_step_budget(self) -> None:
        """A direct ``/OC`` has no object number to judge it once by, so each
        annotation's membership array is read again. Every member, annotation
        and XObject visited across the whole judgement counts against
        ``_MAX_OC_STEPS`` (200,000); past it the file is refused as
        malformed. Scaled down by patching the budget: 30 annotations of
        1,000 members each is past 20,000 visits, 10 of them is within."""
        self.assertEqual(pdf_canonical._MAX_OC_STEPS, 200_000)
        with patch.object(pdf_canonical, "_MAX_OC_STEPS", 20_000):
            self._assert_refused_as_malformed(direct_ocmd_annotations_pdf(30, 1_000))
            within = direct_ocmd_annotations_pdf(10, 1_000)
            check_scan_bytes(within)
            canonical_pdf_bytes(within)

    def test_a_shared_resource_dictionary_is_judged_once_not_per_page(self) -> None:
        """40 pages sharing one ``/XObject`` dictionary of 1,000 entries:
        judged per page that is 40,000 visits, judged once about 2,000 -- so
        it passes a budget of 5,000. An ``/XObject`` dictionary past 1,000
        entries is refused as malformed, as an array is."""
        with patch.object(pdf_canonical, "_MAX_OC_STEPS", 5_000):
            data = shared_resources_pdf(MAX_SCAN_PAGES, 1_000)
            check_scan_bytes(data)
            with pymupdf.open(stream=canonical_pdf_bytes(data), filetype="pdf") as doc:  # type: ignore[no-untyped-call]
                self.assertEqual(doc.page_count, MAX_SCAN_PAGES)
        self._assert_refused_as_malformed(shared_resources_pdf(1, 1_001))

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
        from the stored file, page by page -- and so does the file with an
        all-ON ``/OCProperties`` grafted in and every XObject and annotation
        governed by it, which no committed PDF has on its own, so the prune
        judges every object and must keep them all."""
        paths = sorted(Path(__file__).parent.rglob("*.pdf"))
        self.assertTrue(paths)
        pages = 0
        for path in paths:
            data = path.read_bytes()
            with self.subTest(path=str(path)):
                count = _pdfium_page_count(data)
                stored = [pdfium_grey(data, index, scale=0.5) for index in range(count)]
                for variant, source in (
                    ("as stored", data),
                    ("all layers on", with_all_on_optional_content(data)),
                ):
                    rewrite = canonical_pdf_bytes(source)
                    self.assertEqual(_pdfium_page_count(rewrite), count, variant)
                    for index in range(count):
                        self.assertEqual(
                            pdfium_grey(rewrite, index, scale=0.5),
                            stored[index],
                            f"{variant}, page {index}",
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
