"""Unit tests for lemely.io.scan_limits (spec 2026-09-26 §6)."""

from __future__ import annotations

import contextlib
import io
import time
import tracemalloc
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import pymupdf
import pypdfium2 as pdfium
from PIL import Image

import lemely.io.scan_limits as scan_limits
from lemely.io.scan_limits import (
    MAX_CROP_PAGES,
    MAX_DECODE_PX,
    MAX_PAGE_CONTENT_BYTES,
    MAX_PAGE_PX,
    MAX_SCAN_CONTENT_BYTES,
    MAX_SCAN_PAGES,
    MAX_SCAN_TOTAL_PX,
    MIN_EXTRACTION_DPI,
    ScanRejectedError,
    ScanTooLargeError,
    ScanUnsupportedEncodingError,
    canonical_pdf_bytes,
    check_object_stream_bytes,
    check_pdf_content_bytes,
    check_pdf_page_content,
    check_scan_bytes,
    decoded_stream_size,
    plan_image,
    plan_page_dpi,
    plan_pdf_pages,
)
from tests.pdf_fakes import (
    annot_ap_bomb_pdf,
    annot_ap_image_bomb_pdf,
    annot_ap_nested_bomb_pdf,
    assemble_pdf,
    bomb_on_second_page_pdf,
    born_digital_text_pdf,
    contents_also_appearance_bomb_pdf,
    deep_page_chain_pdf,
    deep_plain_dict_chain_bomb_pdf,
    deep_xobject_chain_bomb_pdf,
    embedded_font_pdf,
    empty_page_tree_pdf,
    empty_pages_nodes_pdf,
    encrypted_pdf_bytes,
    extgstate_smask_bomb_pdf,
    filtered_page_pdf,
    flate_bomb_ops,
    form_also_graphics_state_bomb_pdf,
    form_xobject_cycle_pdf,
    hidden_layer_pdf,
    image_bomb_pdf,
    image_labelled_appearance_pdf,
    indirect_ap_state_bomb_pdf,
    indirect_filter_page_pdf,
    indirect_smask_dimension_bomb_pdf,
    indirect_subtype_form_bomb_pdf,
    indirect_xobject_dict_bomb_pdf,
    inherited_resources_bomb_pdf,
    links_to_sibling_pages_pdf,
    long_parent_chain_pdf,
    many_form_xobjects_pdf,
    many_objects_pdf,
    non_stream_contents_pdf,
    off_page_object_pdf,
    overstated_count_pdf,
    page_bomb_pdf,
    page_kids_bomb_pdf,
    page_kids_equal_count_bomb_pdf,
    page_tree_poison_pdf,
    pages_carrying_kids_pdf,
    parent_poisoned_ap_state_bomb_pdf,
    pdf_stream,
    pdf_with_inflated_count,
    pdf_with_missing_kid_object,
    real_smask_dimension_bomb_pdf,
    repeated_kid_pdf,
    repeated_xobject_pdf,
    resources_entry_pointing_at_pages_node_pdf,
    seeded_page_tree_bomb_pdf,
    shared_container_broken_xref_pdf,
    sibling_page_as_soft_mask_bomb_pdf,
    sibling_page_listed_as_annotation_pdf,
    smask_bomb_pdf,
    stamp_with_jpeg_appearance_pdf,
    stream_extgstate_smask_bomb_pdf,
    tiling_pattern_bomb_pdf,
    tiling_pattern_image_bomb_pdf,
    tree_node_ap_state_bomb_pdf,
    type3_charproc_bomb_pdf,
    type3_dict_font_with_jpeg_pdf,
    type3_stream_font_bomb_pdf,
    typed_form_xobject_bomb_pdf,
    uncounted_bomb_pdf,
    wide_page_tree_pdf,
    wrapped_page_tree_pdf,
    xobject_also_listed_as_annotation_bomb_pdf,
    xobject_bomb_pdf,
    xref_repair_bomb_pdf,
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


def _planned_total_px(pdf: pdfium.PdfDocument, plans: list[scan_limits.PagePlan]) -> float:
    total = 0.0
    for plan in plans:
        width_pt, height_pt = pdf.get_page_size(plan.index)
        total += width_pt * height_pt * (plan.dpi / 72.0) ** 2
    return total


class ScanTotalPixelTests(unittest.TestCase):
    """Final review I1: the per-page cap alone let 40 pages of ~16 Mpx each
    (the reviewer's 1.13 MB PDF of 1439 pt squares sharing one JPEG) plan to
    ~640 Mpx, ~1.5 GB of rendered pages in a 1 GiB worker. The scan's summed
    planned pixels are capped at MAX_SCAN_TOTAL_PX by one uniform DPI factor,
    floored at MIN_EXTRACTION_DPI. Planning only -- nothing here renders."""

    def _plans(self, *sizes_pt: tuple[float, float]) -> tuple[list[float], float]:
        pdf = pdfium.PdfDocument(_pdf_bytes(*sizes_pt))
        try:
            with patch.object(pdfium.PdfPage, "render") as render:
                plans = plan_pdf_pages(pdf)
            render.assert_not_called()
            return [p.dpi for p in plans], _planned_total_px(pdf, plans)
        finally:
            pdf.close()

    def test_the_bounds_are_the_decided_values(self) -> None:
        self.assertEqual((MAX_SCAN_TOTAL_PX, MIN_EXTRACTION_DPI), (160_000_000, 100))

    def test_the_reviewer_aggregate_shape_is_downscaled_uniformly_to_fit(self) -> None:
        dpis, total = self._plans(*([(1439.0, 1439.0)] * MAX_SCAN_PAGES))
        self.assertEqual(len(set(dpis)), 1, dpis)
        self.assertEqual(dpis[0], 100.0)  # floor(200 * sqrt(160 / 639.1)) = floor(100.06)
        self.assertLessEqual(total, MAX_SCAN_TOTAL_PX)

    def test_mixed_page_sizes_share_one_scale_factor(self) -> None:
        # 10 A1 pages (per-page band, planned at 143 DPI, 15.8 Mpx each) plus
        # 30 A4 pages at 200 DPI (3.87 Mpx each): 274 Mpx, so every page's
        # planned DPI is multiplied by the same s = sqrt(160 / 274) = 0.764,
        # then floored: 143 -> 109, 200 -> 152.
        sizes = [(1684.0, 2384.0)] * 10 + [(595.0, 842.0)] * 30
        dpis, total = self._plans(*sizes)
        self.assertEqual(dpis, [109.0] * 10 + [152.0] * 30)
        self.assertLessEqual(total, MAX_SCAN_TOTAL_PX)

    def test_an_honest_40_page_a4_scan_is_unchanged(self) -> None:
        dpis, total = self._plans(*([(595.0, 842.0)] * MAX_SCAN_PAGES))
        self.assertEqual(dpis, [200.0] * MAX_SCAN_PAGES)
        self.assertGreater(total, 150_000_000)  # ~155 Mpx: close to, but under, the cap

    def test_the_committed_fixture_is_unchanged(self) -> None:
        pdf = pdfium.PdfDocument(str(_FIXTURE))
        try:
            dpis = [p.dpi for p in plan_pdf_pages(pdf)]
        finally:
            pdf.close()
        self.assertEqual(dpis, [200.0] * 16)

    def test_a_scan_that_cannot_fit_at_the_minimum_dpi_is_rejected(self) -> None:
        # 1700 pt squares plan at 169 DPI each (per-page band); 40 of them
        # need s = 0.50, i.e. 84 DPI -- under the 100 DPI floor.
        pdf = pdfium.PdfDocument(_pdf_bytes(*([(1700.0, 1700.0)] * MAX_SCAN_PAGES)))
        try:
            with self.assertRaises(ScanTooLargeError) as ctx:
                plan_pdf_pages(pdf)
        finally:
            pdf.close()
        self.assertIn("160 megapixels", str(ctx.exception))

    def test_a_scan_that_cannot_fit_is_rejected_at_upload(self) -> None:
        with self.assertRaises(ScanTooLargeError):
            check_scan_bytes(_pdf_bytes(*([(1700.0, 1700.0)] * MAX_SCAN_PAGES)))

    def test_the_reviewer_aggregate_shape_passes_the_upload_check(self) -> None:
        """It fits once downscaled, so the upload must not refuse it."""
        check_scan_bytes(_pdf_bytes(*([(1439.0, 1439.0)] * MAX_SCAN_PAGES)))


class ContentWalkPageCapTests(unittest.TestCase):
    def test_the_content_check_refuses_too_many_pages_without_walking_them(self) -> None:
        """Final review M1: the content check applies the page cap itself
        before reading the page tree, whoever calls it."""
        data = _pdf_bytes(*([(595.0, 842.0)] * (MAX_SCAN_PAGES + 1)))
        with (
            patch.object(scan_limits, "_page_tree") as page_tree,
            patch.object(scan_limits, "_walk_resource_graph") as walk,
            self.assertRaises(ScanTooLargeError),
        ):
            check_pdf_content_bytes(data)
        page_tree.assert_not_called()
        walk.assert_not_called()

    def test_an_understated_count_does_not_dodge_the_page_cap(self) -> None:
        """``/Count 1`` over 41 real kids: pymupdf believes the ``/Count``, so
        the ``doc.page_count`` check above passes it; the page-tree descent
        counts the kids and refuses it with the same page-cap message shape."""
        data = wide_page_tree_pdf(MAX_SCAN_PAGES + 1, count=1)
        with pymupdf.open(stream=data, filetype="pdf") as doc:  # type: ignore[no-untyped-call]
            self.assertEqual(doc.page_count, 1)
        with self.assertRaises(ScanTooLargeError) as caught:
            check_pdf_content_bytes(data)
        self.assertIn(f"the limit is {MAX_SCAN_PAGES}.", str(caught.exception))

    def test_a_huge_tree_under_an_understated_count_is_refused_early(self) -> None:
        """20,000 real kids under ``/Count 1``: the descent reads at most a
        cap's worth of nodes, and the ``/Parent`` climb never starts."""
        counting = MagicMock(wraps=scan_limits._collection_refs)
        climbing = MagicMock(wraps=scan_limits._parent)
        with (
            patch.object(scan_limits, "_collection_refs", counting),
            patch.object(scan_limits, "_parent", climbing),
            self.assertRaises(ScanTooLargeError),
        ):
            check_pdf_content_bytes(wide_page_tree_pdf(20_000, count=1))
        # The root's /Kids (cut off one past the cap) is the one read made.
        self.assertLessEqual(counting.call_count, MAX_SCAN_PAGES + 2)
        climbing.assert_not_called()

    def test_scans_at_the_page_cap_still_pass_the_bounded_tree_read(self) -> None:
        """The bounded descent and climb refuse only what the cap refuses: a
        born-digital 40-page PDF (text, one shared font) and a flat 40-page
        tree both pass. The committed scan fixture is covered by
        ``test_the_committed_fixture_passes_with_room_to_spare``."""
        check_pdf_content_bytes(born_digital_text_pdf(pages=MAX_SCAN_PAGES))
        check_pdf_content_bytes(_pdf_bytes(*([(595.0, 842.0)] * MAX_SCAN_PAGES)))
        check_pdf_content_bytes(wide_page_tree_pdf(MAX_SCAN_PAGES, count=MAX_SCAN_PAGES))

    def test_spec_valid_trees_with_single_kid_inner_nodes_pass_at_the_cap(self) -> None:
        """Review round 2 on F8: the spec does not require an inner ``/Pages``
        node to have two or more kids, and MuPDF and pdfium count and render
        such trees. 40 pages under one or two single-kid wrappers each, or
        under intermediate nodes, pass both the upload and content checks."""
        for label, data in (
            ("1 wrapper each", wrapped_page_tree_pdf(MAX_SCAN_PAGES, wrap=1)),
            ("2 wrappers each", wrapped_page_tree_pdf(MAX_SCAN_PAGES, wrap=2)),
            ("fanout 2", wrapped_page_tree_pdf(MAX_SCAN_PAGES, fanout=2)),
            ("fanout 10", wrapped_page_tree_pdf(MAX_SCAN_PAGES, fanout=10)),
        ):
            with self.subTest(label):
                check_pdf_content_bytes(data)
                check_scan_bytes(data)

    def test_one_page_over_the_cap_under_single_kid_wrappers_gets_the_page_message(
        self,
    ) -> None:
        """41 pages, one wrapper each. The ``doc.page_count`` check refuses
        it first; the tree read, asked directly, refuses it with its own
        page message too -- a true one: 41 leaf references."""
        data = wrapped_page_tree_pdf(MAX_SCAN_PAGES + 1, wrap=1)
        with self.assertRaises(ScanTooLargeError) as caught:
            check_pdf_content_bytes(data)
        self.assertIn(f"the limit is {MAX_SCAN_PAGES}.", str(caught.exception))
        with (
            pymupdf.open(stream=data, filetype="pdf") as doc,  # type: ignore[no-untyped-call]
            self.assertRaises(ScanTooLargeError) as caught,
        ):
            scan_limits._page_tree(doc, bound=scan_limits._SCAN_PAGE_BOUND)
        self.assertEqual(str(caught.exception), scan_limits._SCAN_PAGES_MESSAGE)

    def test_a_page_typed_node_carrying_kids_is_refused_as_malformed(self) -> None:
        """T9b review round 1 (replaces round 2's "counts as a page"): a
        ``/Type /Page`` naming ``/Kids`` is not valid PDF, and MuPDF (which
        takes the node as a page) and pdfium (which descends its ``/Kids``)
        resolve it differently by construction. Refused as malformed, at any
        page count -- never with a page count it may not have."""
        for pages in (1, MAX_SCAN_PAGES, MAX_SCAN_PAGES + 1):
            with self.subTest(pages=pages):
                with self.assertRaises(ScanRejectedError) as caught:
                    check_pdf_content_bytes(pages_carrying_kids_pdf(pages))
                self.assertEqual(
                    str(caught.exception), scan_limits._PAGE_STRUCTURE_MALFORMED_MESSAGE
                )

    def test_an_empty_pages_node_is_not_a_page(self) -> None:
        """Review round 3 on F8: an empty ``/Type /Pages`` node (``/Kids []``)
        names no kids but is no page to MuPDF or pdfium -- ``/Type`` decides,
        and ``/Kids`` only when ``/Type`` is absent. 40 pages beside one or
        five of them, under ``/Count 40``, pass the upload, content and crop
        checks; their references still count as work, so hundreds of them
        are refused as too complex, never as too many pages."""
        for empties in (1, 5):
            data = empty_pages_nodes_pdf(MAX_SCAN_PAGES, empties)
            with self.subTest(empties=empties):
                check_scan_bytes(data)
                check_pdf_content_bytes(data)
                with pymupdf.open(stream=data, filetype="pdf") as doc:  # type: ignore[no-untyped-call]
                    check_pdf_page_content(doc, MAX_SCAN_PAGES - 1)
        with self.assertRaises(ScanTooLargeError) as caught:
            check_pdf_content_bytes(
                empty_pages_nodes_pdf(MAX_SCAN_PAGES, scan_limits._SCAN_PAGE_BOUND.work)
            )
        self.assertEqual(str(caught.exception), scan_limits._PAGE_TREE_TOO_COMPLEX_MESSAGE)

    def test_a_deep_chain_past_the_work_bound_is_refused_as_too_complex(self) -> None:
        """One page under more nested single-kid nodes than the work bound
        allows: refused, but never as "more than 40 pages" -- it has one.
        The same page under a chain inside the bound passes."""
        work = scan_limits._SCAN_PAGE_BOUND.work
        with self.assertRaises(ScanTooLargeError) as caught:
            check_pdf_content_bytes(deep_page_chain_pdf(work))
        self.assertIn("too complex", str(caught.exception))
        self.assertNotIn("pages", str(caught.exception))
        check_pdf_content_bytes(deep_page_chain_pdf(work - 2))


class PageScopedContentCheckTests(unittest.TestCase):
    """Triage F8: ``check_pdf_page_content`` is ``check_pdf_content`` for the
    one page a caller is about to render -- and only that page."""

    def _doc(self, data: bytes) -> pymupdf.Document:
        return pymupdf.open(stream=data, filetype="pdf")  # type: ignore[no-untyped-call]

    def test_a_clean_page_passes_when_another_page_is_a_bomb(self) -> None:
        with self._doc(bomb_on_second_page_pdf(MAX_PAGE_CONTENT_BYTES + 1_000_000)) as doc:
            check_pdf_page_content(doc, 0)

    def test_the_bomb_page_itself_is_still_refused(self) -> None:
        with (
            self._doc(bomb_on_second_page_pdf(MAX_PAGE_CONTENT_BYTES + 1_000_000)) as doc,
            self.assertRaises(ScanTooLargeError),
        ):
            check_pdf_page_content(doc, 1)

    def test_the_whole_document_check_still_refuses_it(self) -> None:
        with self.assertRaises(ScanTooLargeError):
            check_pdf_content_bytes(bomb_on_second_page_pdf(MAX_PAGE_CONTENT_BYTES + 1_000_000))

    def test_only_the_named_page_is_walked(self) -> None:
        with (
            self._doc(bomb_on_second_page_pdf(MAX_PAGE_CONTENT_BYTES + 1_000_000)) as doc,
            patch.object(scan_limits, "_walk_resource_graph") as walk,
        ):
            check_pdf_page_content(doc, 0)
        pages_walked = {call.args[2].page_index for call in walk.call_args_list}
        self.assertEqual(pages_walked, {0})

    def test_the_page_cap_does_not_apply_to_a_page_scoped_check(self) -> None:
        """User decision 2 (2026-09-29): a stored scan over MAX_SCAN_PAGES
        keeps its review crops; the cap bounds whole-document work
        (extraction, preview) and a one-page render is not that."""
        with self._doc(_pdf_bytes(*([(595.0, 842.0)] * (MAX_SCAN_PAGES + 1)))) as doc:
            check_pdf_page_content(doc, 0)
            check_pdf_page_content(doc, MAX_SCAN_PAGES)

    def test_a_page_the_page_tree_read_never_reached_is_refused(self) -> None:
        """Fail closed: ``_page_tree`` stops at the first page whose number
        pymupdf cannot give. The whole-document walk never goes past that
        page, but a page-scoped check can name a later one, whose inherited
        ``/Resources`` the tree then never recorded -- walking it with no
        holders would skip them. Simulated by dropping every holder; both
        callers share ``_check_page``, so both refuse."""
        real_page_tree = scan_limits._page_tree

        def truncated(doc: pymupdf.Document, *, bound: scan_limits._PageBound) -> object:
            return scan_limits._PageTree(xrefs=real_page_tree(doc, bound=bound).xrefs, holders={})

        data = xobject_bomb_pdf(MAX_PAGE_CONTENT_BYTES + 1_000_000)
        with patch.object(scan_limits, "_page_tree", truncated):
            with (
                self.subTest("page-scoped"),
                self._doc(data) as doc,
                self.assertRaises(ScanRejectedError),
            ):
                check_pdf_page_content(doc, 0)
            with self.subTest("whole-document"), self.assertRaises(ScanRejectedError):
                check_pdf_content_bytes(data)

    def test_a_scan_at_the_crop_page_bound_passes(self) -> None:
        with self._doc(_pdf_bytes(*([(595.0, 842.0)] * MAX_CROP_PAGES))) as doc:
            check_pdf_page_content(doc, MAX_CROP_PAGES - 1)

    def test_a_scan_over_the_crop_page_bound_is_refused_before_the_tree_is_read(self) -> None:
        """Review round 1 on F8: ``_page_tree`` costs time in proportion to
        the page count, so the page-scoped check has its own bound
        (``MAX_CROP_PAGES``), applied before anything is read."""
        with (
            self._doc(_pdf_bytes(*([(595.0, 842.0)] * (MAX_CROP_PAGES + 1)))) as doc,
            patch.object(scan_limits, "_page_tree") as page_tree,
            self.assertRaises(ScanTooLargeError) as caught,
        ):
            check_pdf_page_content(doc, 0)
        page_tree.assert_not_called()
        self.assertIn(f"limit for a review crop is {MAX_CROP_PAGES}", str(caught.exception))

    def test_an_understated_count_does_not_hide_pages_from_the_crop_bound(self) -> None:
        """``/Count 1`` over more real kids than the bound: pymupdf believes
        the ``/Count``, the descent counts the kids."""
        with self._doc(wide_page_tree_pdf(MAX_CROP_PAGES + 1, count=1)) as doc:
            self.assertEqual(doc.page_count, 1)
            with self.assertRaises(ScanTooLargeError):
                check_pdf_page_content(doc, 0)

    def test_a_shared_kid_does_not_hide_pages_from_the_crop_bound(self) -> None:
        """Every kid is a ``/Type /Page`` that also names the same one page
        under its own ``/Kids``: refused as malformed on the first one met
        (T9b review round 1), never with a page count."""
        with (
            self._doc(wide_page_tree_pdf(MAX_CROP_PAGES + 1, count=1, shared_kid=True)) as doc,
            self.assertRaises(ScanRejectedError) as caught,
        ):
            check_pdf_page_content(doc, 0)
        self.assertEqual(str(caught.exception), scan_limits._PAGE_STRUCTURE_MALFORMED_MESSAGE)

    def test_the_crop_bound_stops_the_descent_early_on_a_huge_tree(self) -> None:
        """20,000 real kids under ``/Count 1``: the descent reads at most
        a bound's worth of nodes, and the ``/Parent`` climb never starts."""
        counting = MagicMock(wraps=scan_limits._collection_refs)
        climbing = MagicMock(wraps=scan_limits._parent)
        with (
            self._doc(wide_page_tree_pdf(20_000, count=1)) as doc,
            patch.object(scan_limits, "_collection_refs", counting),
            patch.object(scan_limits, "_parent", climbing),
            self.assertRaises(ScanTooLargeError),
        ):
            check_pdf_page_content(doc, 0)
        # The root's /Kids, then one read per kid up to the first past the bound.
        self.assertLessEqual(counting.call_count, MAX_CROP_PAGES + 2)
        climbing.assert_not_called()

    def test_a_repeated_kid_does_not_hide_pages_from_the_crop_bound(self) -> None:
        """One page named 201 times in the root's ``/Kids``: three tree
        objects, 201 pages to MuPDF, which counts every reference. Refused
        with the page message, which is true; 200 references pass."""
        with self._doc(repeated_kid_pdf(MAX_CROP_PAGES)) as doc:
            check_pdf_page_content(doc, 0)
        with (
            self._doc(repeated_kid_pdf(MAX_CROP_PAGES + 1)) as doc,
            self.assertRaises(ScanTooLargeError) as caught,
        ):
            check_pdf_page_content(doc, 0)
        self.assertIn(f"more than {MAX_CROP_PAGES} pages", str(caught.exception))

    def test_a_huge_repeated_kid_array_is_read_no_further_than_the_work_bound(self) -> None:
        """One page named 200,000 times: refused having read no more of the
        array than the work bound allows, not all 200,000 entries."""
        lengths: list[int] = []
        real_collection_refs = scan_limits._collection_refs

        def recording(*args: object, **kwargs: object) -> list[int]:
            refs = real_collection_refs(*args, **kwargs)  # type: ignore[arg-type]
            lengths.append(len(refs))
            return refs

        with (
            self._doc(repeated_kid_pdf(200_000)) as doc,
            patch.object(scan_limits, "_collection_refs", recording),
            self.assertRaises(ScanTooLargeError),
        ):
            check_pdf_page_content(doc, 0)
        self.assertLessEqual(max(lengths), scan_limits._CROP_PAGE_BOUND.work)

    def test_a_crop_at_the_bound_under_single_kid_inner_nodes_passes(self) -> None:
        """Review round 2 on F8: the spec does not require an inner ``/Pages``
        node to have two or more kids. 200 pages each under one single-kid
        wrapper, and 134 each under two, are crops MuPDF renders."""
        for pages, wrap in ((MAX_CROP_PAGES, 1), (134, 2), (MAX_CROP_PAGES, 0)):
            with (
                self.subTest(pages=pages, wrap=wrap),
                self._doc(wrapped_page_tree_pdf(pages, wrap=wrap)) as doc,
            ):
                check_pdf_page_content(doc, pages - 1)

    def test_the_crop_bound_stops_a_long_parent_climb_early(self) -> None:
        """A one-page tree whose page's ``/Parent`` chain runs through 20,000
        objects outside the tree: the climb reads at most a bound's worth."""
        climbing = MagicMock(wraps=scan_limits._parent)
        with (
            self._doc(long_parent_chain_pdf(20_000)) as doc,
            patch.object(scan_limits, "_parent", climbing),
            self.assertRaises(ScanRejectedError),
        ):
            check_pdf_page_content(doc, 0)
        self.assertLessEqual(climbing.call_count, scan_limits._CROP_PAGE_BOUND.work)

    def test_a_short_parent_chain_outside_the_tree_still_passes(self) -> None:
        """The climb bound refuses only a chain longer than any real tree
        under the page bound could have; a short odd one is walked as before."""
        with self._doc(long_parent_chain_pdf(3)) as doc:
            check_pdf_page_content(doc, 0)


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
        cannot fully make sense of -- extraction fails on it later.

        Task 9b keeps this: pdfium cannot size page 2, so extraction renders
        nothing, and MuPDF (the crop route's renderer) resolves both pages
        and its content check measures them."""
        check_scan_bytes(pdf_with_missing_kid_object())

    def test_a_page_tree_with_an_inflated_count_is_rejected(self) -> None:
        """Task 9b, fail closed: ``/Count 2`` over one real page. Neither
        reader can resolve page 2, so the content check cannot cover every
        page a reader will try to render -- refused, where it used to pass
        because pdfium's planning failure skipped the MuPDF check."""
        with self.assertRaises(ScanRejectedError):
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
        check_pdf_content_bytes(_FIXTURE.read_bytes())
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

    @unittest.skipUnless(_FIXTURE.is_file(), "handwritten-59 fixture not present")
    def test_the_committed_fixture_passes_the_upload_check(self) -> None:
        check_scan_bytes(_FIXTURE.read_bytes())

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

    def test_a_deep_plain_dict_chain_bomb_is_rejected(self) -> None:
        # Fix round 3, Important 1: round 2's fallback recursed into each
        # next-level plain dict via a direct Python call; 2,000 levels
        # exceeded the recursion limit before the bomb at the end of the
        # chain was ever reached, and the resulting RecursionError used to
        # be swallowed silently.
        with self.assertRaises(ScanTooLargeError):
            check_pdf_content_bytes(
                deep_plain_dict_chain_bomb_pdf(depth=2000, inflated_bytes=112_000_000)
            )

    def test_a_deep_form_xobject_chain_bomb_is_rejected(self) -> None:
        # Fix round 3, Important 1: the same recursion-depth hole existed
        # for an entirely ordinary chain of legitimate, nested Form
        # XObjects, since round 1. `page.get_images(full=True)` itself
        # independently walks nested Form XObjects looking for images and
        # hits the identical RecursionError on this fixture -- caught by
        # check_pdf_content's new fail-closed wrapper and turned into a
        # plain ScanRejectedError (not specifically ScanTooLargeError,
        # since it is pymupdf's own image-enumeration call that raises
        # here, not this module's byte-budget check).
        with self.assertRaises(ScanRejectedError):
            check_pdf_content_bytes(
                deep_xobject_chain_bomb_pdf(depth=2000, inflated_bytes=112_000_000)
            )

    def test_an_unexpected_error_during_the_walk_rejects_rather_than_passes(self) -> None:
        # Fix round 3, Important 1 (fail-closed): a bug or unforeseen
        # pymupdf quirk inside the resource-graph walk itself must reject
        # the file, not silently pass it through the way a genuine
        # page-tree/page-access failure still does.
        with (
            patch.object(scan_limits, "_walk_resource_graph", side_effect=RuntimeError("boom")),
            self.assertRaises(ScanRejectedError) as ctx,
        ):
            check_pdf_content_bytes(filtered_page_pdf(b"", b"q Q"))
        self.assertNotIsInstance(ctx.exception, ScanTooLargeError)

    def test_a_non_resource_key_pointing_at_the_pages_node_is_never_walked(self) -> None:
        # `/Poison` is not a
        # resource category (ISO 32000-1 Table 33), so no renderer can reach
        # anything through it and the walk does not read it at all. The
        # in-category version of this attack is page_tree_poison_pdf.
        data = resources_entry_pointing_at_pages_node_pdf()
        check_pdf_content_bytes(data)  # must not raise
        doc = pymupdf.open(stream=data, filetype="pdf")
        try:
            tree = scan_limits._page_tree(doc, bound=scan_limits._SCAN_PAGE_BOUND)
            walk = scan_limits._PageWalk(
                page_index=0, tree=tree.xrefs, budget=scan_limits._ContentBudget()
            )
            start = scan_limits._resources_refs(doc, doc.page_xref(0))
            scan_limits._walk_resource_graph(doc, start, walk)
        finally:
            doc.close()
        self.assertEqual(walk.budget.objects, 0)


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

    def test_an_smask_with_a_real_number_width_is_rejected(self) -> None:
        # Fix round 3, minor: /Width 40000.0 (pymupdf's "float" kind, not
        # "int") used to make _resolve_int return None without checking.
        with self.assertRaises(ScanTooLargeError) as ctx:
            check_pdf_content_bytes(real_smask_dimension_bomb_pdf(40000.0, 40_000))
        self.assertIn("megapixel", str(ctx.exception))


class PageTreeIdentityTests(unittest.TestCase):
    """The page tree is recognised by object identity -- the catalog, every
    page and every node reached through ``/Kids``, collected before any page
    is walked -- never by resource names or ``/Type`` values, which the
    PDF's author chooses and the renderer ignores. Reaching it from a page's
    drawing resources, ``/Contents`` or ``/Annots`` rejects the file."""

    def test_a_form_filed_under_a_page_tree_key_name_is_rejected(self) -> None:
        # In an indirect /XObject name map these are author-chosen resource
        # names the renderer draws by, like any other name.
        for name in ("P", "Contents", "Parent", "Kids", "Annots", "B", "Dest"):
            with self.subTest(name=name), self.assertRaises(ScanTooLargeError):
                check_pdf_content_bytes(indirect_xobject_dict_bomb_pdf(112_000_000, name=name))
        with self.assertRaises(ScanTooLargeError):
            check_scan_bytes(indirect_xobject_dict_bomb_pdf(112_000_000, name="P"))

    def test_an_appearance_state_named_contents_is_rejected(self) -> None:
        # /AP << /N 6 0 R >>, object 6 = << /Off .. /Contents 8 0 R >>,
        # /AS /Contents selects the bomb.
        with self.assertRaises(ScanTooLargeError):
            check_pdf_content_bytes(indirect_ap_state_bomb_pdf(112_000_000, state="Contents"))

    def test_a_form_xobject_typed_as_a_page_tree_node_is_rejected(self) -> None:
        # The renderer draws by /Subtype /Form and ignores /Type.
        for type_name in ("Page", "Pages", "Catalog"):
            with self.subTest(type_name=type_name), self.assertRaises(ScanTooLargeError):
                check_pdf_content_bytes(
                    typed_form_xobject_bomb_pdf(112_000_000, type_name=type_name)
                )

    def test_containers_typed_as_fonts_are_still_walked(self) -> None:
        # A name map, a tiling pattern or a graphics state labelled
        # /Type /Font is drawn exactly as if it were not.
        cases = {
            "xobject map": indirect_xobject_dict_bomb_pdf(
                112_000_000, map_entries=b"/Type /Font /Subtype /TrueType"
            ),
            "tiling pattern": tiling_pattern_bomb_pdf(112_000_000, type_name="Font"),
            "extgstate": extgstate_smask_bomb_pdf(112_000_000, gs_type="Font"),
        }
        for label, data in cases.items():
            with self.subTest(label), self.assertRaises(ScanTooLargeError):
                check_pdf_content_bytes(data)

    def test_a_graphics_state_also_filed_as_a_font_is_still_walked(self) -> None:
        # One object under both /Font and /ExtGState: meeting it first as a
        # font must not stop it being walked as the graphics state it is.
        with self.assertRaises(ScanTooLargeError):
            check_pdf_content_bytes(extgstate_smask_bomb_pdf(112_000_000, also_as_font=True))

    def test_inherited_resources_are_walked(self) -> None:
        # /Resources on the /Pages parent, none on the page: both renderers
        # inherit it (ISO 32000-1 Table 30).
        with self.assertRaises(ScanTooLargeError):
            check_pdf_content_bytes(inherited_resources_bomb_pdf(112_000_000))
        with self.assertRaises(ScanTooLargeError):
            check_scan_bytes(inherited_resources_bomb_pdf(112_000_000))

    def test_a_large_embedded_font_program_is_not_page_content(self) -> None:
        # Guard: a font reached through /Font is not expanded, so its
        # 9 MB program (over the 8 MB page cap) does not count.
        check_pdf_content_bytes(embedded_font_pdf(9_000_000))

    def test_a_poisoned_name_map_is_rejected_without_climbing(self) -> None:
        # Page 0's indirect /XObject map also names the catalog, a
        # /Type-less /Pages root or a /Type-less sibling page. Reaching the
        # page tree from drawing resources rejects the file -- by identity,
        # before the node is expanded, so the siblings' 5 MB forms are never
        # counted (an over-count would raise ScanTooLargeError instead).
        cases = {
            "all three": b"/Cat 1 0 R /Root 2 0 R /Sib 5 0 R",
            "catalog": b"/Cat 1 0 R",
            "root": b"/Root 2 0 R",
            "sibling": b"/Sib 5 0 R",
        }
        for label, poison in cases.items():
            with self.subTest(label):
                data = page_tree_poison_pdf(form_bytes=5_000_000, poison=poison)
                for check in (check_pdf_content_bytes, check_scan_bytes):
                    with self.assertRaises(ScanRejectedError) as ctx:
                        check(data)
                    self.assertNotIsInstance(ctx.exception, ScanTooLargeError)
                doc = pymupdf.open(stream=data, filetype="pdf")
                try:
                    tree = scan_limits._page_tree(doc, bound=scan_limits._SCAN_PAGE_BOUND)
                    walk = scan_limits._PageWalk(
                        page_index=0, tree=tree.xrefs, budget=scan_limits._ContentBudget()
                    )
                    start = scan_limits._resources_refs(doc, doc.page_xref(0))
                    with self.assertRaises(ScanRejectedError):
                        scan_limits._walk_resource_graph(doc, start, walk)
                finally:
                    doc.close()
                self.assertEqual(tree.xrefs, frozenset({1, 2, 3, 5, 6}))
                # Nothing behind a tree node was visited: the siblings'
                # contents (7, 8) and forms (10, 11).
                self.assertTrue({7, 8, 10, 11}.isdisjoint(walk.seen))

    def test_a_page_tree_node_used_as_an_appearance_state_dict_is_rejected(self) -> None:
        # The /Pages root or a sibling page doubles as page 0's /AP /N state
        # dict, whose selected state is a Form XObject bomb.
        for node in ("root", "sibling"):
            with self.subTest(node=node):
                data = tree_node_ap_state_bomb_pdf(112_000_000, node=node)
                with self.assertRaises(ScanRejectedError):
                    check_pdf_content_bytes(data)
                with self.assertRaises(ScanRejectedError):
                    check_scan_bytes(data)

    def test_a_sibling_page_used_as_a_soft_mask_is_rejected(self) -> None:
        # An ordinary ExtGState names the sibling page as its /SMask; the
        # page's extra /G is the bomb. The tree is met inside a container.
        data = sibling_page_as_soft_mask_bomb_pdf(112_000_000)
        with self.assertRaises(ScanRejectedError) as ctx:
            check_pdf_content_bytes(data)
        self.assertNotIsInstance(ctx.exception, ScanTooLargeError)

    def test_a_tree_node_already_listed_as_contents_or_annotation_is_rejected(self) -> None:
        # The sibling page is listed in page 0's /Annots or /Contents before
        # the annotation's /AP reaches it: handled once already, it must be
        # rejected, not skipped.
        for seed in ("annots", "contents"):
            with self.subTest(seed=seed):
                data = seeded_page_tree_bomb_pdf(112_000_000, seed=seed)
                with self.assertRaises(ScanRejectedError):
                    check_pdf_content_bytes(data)
                with self.assertRaises(ScanRejectedError):
                    check_scan_bytes(data)

    def test_a_tree_node_is_rejected_even_when_already_seen(self) -> None:
        # Pins the order of the walk's checks: the tree test runs before the
        # visited-set test, so a tree node pre-seeded into `seen` (as
        # /Contents or another role could) still rejects.
        doc = pymupdf.open(stream=links_to_sibling_pages_pdf(), filetype="pdf")
        try:
            tree = scan_limits._page_tree(doc, bound=scan_limits._SCAN_PAGE_BOUND)
            walk = scan_limits._PageWalk(
                page_index=0, tree=tree.xrefs, budget=scan_limits._ContentBudget()
            )
            walk.seen.add(5)  # the sibling page
            with self.assertRaises(ScanRejectedError):
                scan_limits._walk_resource_graph(doc, [(5, "any")], walk)
        finally:
            doc.close()

    def test_a_page_listed_in_annots_is_rejected(self) -> None:
        # Only the /Annots check reaches this page-tree node: the listed
        # page has no /AP and nothing else of page 0 names it.
        data = sibling_page_listed_as_annotation_pdf()
        with self.assertRaises(ScanRejectedError) as ctx:
            check_pdf_content_bytes(data)
        self.assertNotIsInstance(ctx.exception, ScanTooLargeError)

    def test_a_contents_entry_that_is_not_a_stream_is_rejected(self) -> None:
        with self.assertRaises(ScanRejectedError) as ctx:
            check_pdf_content_bytes(non_stream_contents_pdf())
        self.assertNotIsInstance(ctx.exception, ScanTooLargeError)

    def test_links_to_a_sibling_page_pass(self) -> None:
        # /Dest, /A /GoTo, /P and /Popup all name pages or annotations the
        # renderer does not draw from; the walk follows only /AP.
        data = links_to_sibling_pages_pdf()
        check_pdf_content_bytes(data)
        check_scan_bytes(data)

    def test_a_deep_form_chain_bomb_is_rejected_by_the_walk_alone(self) -> None:
        # With pymupdf's own (recursive) image enumeration taken
        # out, the bomb at the end of the 2,000-deep chain is still found
        # by this module's iterative walk and refused as too large.
        with (
            patch.object(pymupdf.Page, "get_images", return_value=[]),
            self.assertRaises(ScanTooLargeError),
        ):
            check_pdf_content_bytes(
                deep_xobject_chain_bomb_pdf(depth=2000, inflated_bytes=112_000_000)
            )

    def test_a_bogus_parent_does_not_hide_an_object_from_the_walk(self) -> None:
        # The page's /Parent names its annotation's appearance-state dict.
        # The tree set comes from /Kids, so that dict is still expanded.
        data = parent_poisoned_ap_state_bomb_pdf(112_000_000)
        with self.assertRaises(ScanTooLargeError):
            check_pdf_content_bytes(data)
        doc = pymupdf.open(stream=data, filetype="pdf")
        try:
            self.assertEqual(
                scan_limits._page_tree(doc, bound=scan_limits._SCAN_PAGE_BOUND).xrefs,
                frozenset({1, 2, 3}),
            )
        finally:
            doc.close()


class StreamRoleTests(unittest.TestCase):
    """A stream is walked by what a renderer does with it: an appearance
    stream is run as a form whatever its ``/Subtype`` says, and a
    ``/Subtype`` written as an indirect name reads the same as a direct one."""

    def test_an_appearance_stream_without_a_subtype_has_its_resources_walked(self) -> None:
        with self.assertRaises(ScanTooLargeError):
            check_pdf_content_bytes(annot_ap_nested_bomb_pdf(112_000_000, ap_dict=b""))

    def test_an_appearance_stream_labelled_as_an_image_is_walked_as_a_form(self) -> None:
        ap_dict = (
            b"/Type /XObject /Subtype /Image /Width 1 /Height 1 "
            b"/ColorSpace /DeviceGray /BitsPerComponent 8"
        )
        with self.assertRaises(ScanTooLargeError):
            check_pdf_content_bytes(annot_ap_nested_bomb_pdf(112_000_000, ap_dict=ap_dict))

    def test_a_form_with_an_indirect_subtype_has_its_resources_walked(self) -> None:
        with self.assertRaises(ScanTooLargeError):
            check_pdf_content_bytes(indirect_subtype_form_bomb_pdf(112_000_000))
        with self.assertRaises(ScanTooLargeError):
            check_scan_bytes(indirect_subtype_form_bomb_pdf(112_000_000))

    def test_a_type3_font_that_is_a_stream_has_its_glyphs_walked(self) -> None:
        with self.assertRaises(ScanTooLargeError):
            check_pdf_content_bytes(type3_stream_font_bomb_pdf(112_000_000))

    def test_a_graphics_state_that_is_a_stream_is_walked_as_a_container(self) -> None:
        with self.assertRaises(ScanTooLargeError):
            check_pdf_content_bytes(stream_extgstate_smask_bomb_pdf(112_000_000))

    def test_an_xobject_also_listed_as_an_annotation_has_its_appearance_walked(self) -> None:
        # Walked first as an XObject, the same object's /AP is still read
        # when /Annots lists it.
        with self.assertRaises(ScanTooLargeError):
            check_pdf_content_bytes(xobject_also_listed_as_annotation_bomb_pdf(112_000_000))

    def test_a_form_also_used_as_a_graphics_state_is_expanded_in_full(self) -> None:
        # Met first as an /XObject, the same form is still expanded as the
        # graphics state it also is: its /SMask group is the bomb.
        data = form_also_graphics_state_bomb_pdf(112_000_000, xobject_first=True)
        with self.assertRaises(ScanTooLargeError):
            check_pdf_content_bytes(data)
        with self.assertRaises(ScanTooLargeError):
            check_scan_bytes(data)

    def test_the_outcome_does_not_depend_on_visit_order(self) -> None:
        # The same shared object reached in two roles, in both orders.
        outcomes = []
        for xobject_first in (True, False):
            with self.subTest(xobject_first=xobject_first):
                with self.assertRaises(ScanTooLargeError) as ctx:
                    check_pdf_content_bytes(
                        form_also_graphics_state_bomb_pdf(112_000_000, xobject_first=xobject_first)
                    )
                outcomes.append(str(ctx.exception))
        self.assertEqual(len(set(outcomes)), 1)

    def test_a_content_stream_also_used_as_an_appearance_has_its_resources_walked(
        self,
    ) -> None:
        data = contents_also_appearance_bomb_pdf(112_000_000)
        with self.assertRaises(ScanTooLargeError):
            check_pdf_content_bytes(data)
        with self.assertRaises(ScanTooLargeError):
            check_scan_bytes(data)

    def test_a_stamp_appearance_drawing_a_jpeg_passes(self) -> None:
        # Guard for the walk above: its image is met under /XObject and
        # size-checked, never counted as unmeasurable page content.
        data = stamp_with_jpeg_appearance_pdf()
        check_pdf_content_bytes(data)
        check_scan_bytes(data)

    def test_a_type3_dict_font_drawing_a_jpeg_from_its_resources_passes(self) -> None:
        # Pins that a plain dict container keeps its /Resources roles: read
        # as bare text instead, the JPEG would be met in the "any" role,
        # counted as content, and refused as an unmeasurable encoding.
        data = type3_dict_font_with_jpeg_pdf()
        check_pdf_content_bytes(data)
        check_scan_bytes(data)

    def test_an_image_labelled_appearance_declaring_40000_squared_is_rejected(self) -> None:
        # Pins that an image-labelled stream is pixel-checked in every role,
        # not only under /XObject: this one is reached only as an /AP /N.
        with self.assertRaises(ScanTooLargeError) as ctx:
            check_pdf_content_bytes(image_labelled_appearance_pdf(40_000, 40_000))
        self.assertIn("1600 megapixels", str(ctx.exception))
        with self.assertRaises(ScanTooLargeError):
            check_scan_bytes(image_labelled_appearance_pdf(40_000, 40_000))


class WalkedImageTests(unittest.TestCase):
    """An image the walk reaches is pixel-checked
    there too -- ``page.get_images(full=True)`` does not list images inside
    annotation appearance streams or tiling patterns."""

    def test_an_oversized_image_in_an_annotation_appearance_is_rejected(self) -> None:
        with self.assertRaises(ScanTooLargeError) as ctx:
            check_pdf_content_bytes(annot_ap_image_bomb_pdf(40_000, 40_000))
        self.assertIn("megapixel", str(ctx.exception))
        with self.assertRaises(ScanTooLargeError):
            check_scan_bytes(annot_ap_image_bomb_pdf(40_000, 40_000))

    def test_an_oversized_image_in_a_tiling_pattern_is_rejected(self) -> None:
        with self.assertRaises(ScanTooLargeError) as ctx:
            check_pdf_content_bytes(tiling_pattern_image_bomb_pdf(40_000, 40_000))
        self.assertIn("megapixel", str(ctx.exception))

    def test_a_600_dpi_image_in_an_annotation_appearance_passes(self) -> None:
        check_pdf_content_bytes(annot_ap_image_bomb_pdf(4_960, 7_016))


class ReaderCoverageTests(unittest.TestCase):
    """Task 9b: the content check must cover every page a renderer will
    render, and fail closed when it cannot. MuPDF walks; pdfium renders
    extraction; where they disagree, or MuPDF cannot read a page it
    counted, the file is refused rather than passed unmeasured."""

    _BOMB = MAX_PAGE_CONTENT_BYTES + 1_000_000

    def test_a_bomb_only_pdfium_sees_is_refused_at_upload_and_in_the_content_check(
        self,
    ) -> None:
        """The reviewer's reproduction: MuPDF takes the ``/Type /Page`` node
        as page 1 and cannot load page 2; pdfium renders the bomb as page 2.
        A ``/Type /Page`` naming ``/Kids`` is refused as malformed (T9b
        review round 1) before any page is walked."""
        data = page_kids_bomb_pdf(self._BOMB)
        for check in (check_scan_bytes, check_pdf_content_bytes):
            with self.subTest(check.__name__):
                with self.assertRaises(ScanRejectedError) as caught:
                    check(data)
                self.assertEqual(
                    str(caught.exception), scan_limits._PAGE_STRUCTURE_MALFORMED_MESSAGE
                )

    def test_the_equal_count_page_kids_bomb_is_refused(self) -> None:
        """T9b review round 1: both readers count 2 pages, but MuPDF numbers
        [P, C] while pdfium renders P's kid, a bomb, as page 1. Every page
        MuPDF numbered loads, and the counts agree -- refused because P, a
        ``/Type /Page``, names ``/Kids``."""
        data = page_kids_equal_count_bomb_pdf(self._BOMB)
        with pymupdf.open(stream=data, filetype="pdf") as doc:  # type: ignore[no-untyped-call]
            self.assertEqual(doc.page_count, 2)
        for check in (check_scan_bytes, check_pdf_content_bytes):
            with self.subTest(check.__name__):
                with self.assertRaises(ScanRejectedError) as caught:
                    check(data)
                self.assertEqual(
                    str(caught.exception), scan_limits._PAGE_STRUCTURE_MALFORMED_MESSAGE
                )

    def test_pages_the_tree_holds_but_mupdf_does_not_number_are_refused(self) -> None:
        """Defence in depth (T9b review round 1): the set of pages the tree
        descent finds must be the set MuPDF numbers. ``/Count 1`` over two
        real kids: both readers number one page and never render the other,
        so the file is malformed, and refused whatever the ``/Kids`` rule
        catches. Equal sets pass (a flat tree, a repeated kid)."""
        with self.assertRaises(ScanRejectedError) as caught:
            check_pdf_content_bytes(wide_page_tree_pdf(2, count=1))
        self.assertEqual(str(caught.exception), scan_limits._PAGE_STRUCTURE_MALFORMED_MESSAGE)
        check_pdf_content_bytes(wide_page_tree_pdf(2, count=2))
        check_pdf_content_bytes(repeated_kid_pdf(3))

    def test_readers_that_disagree_on_the_page_count_are_refused(self) -> None:
        """No ``/Count``, or ``/Count 0``: MuPDF sees no pages, so its walk
        measures nothing, while pdfium renders both, bomb included."""
        for count_entry in (b"", b"/Count 0"):
            data = uncounted_bomb_pdf(self._BOMB, count_entry=count_entry)
            with self.subTest(count_entry=count_entry):
                with self.assertRaises(ScanRejectedError) as caught:
                    check_scan_bytes(data)
                self.assertEqual(str(caught.exception), scan_limits._PAGE_COUNT_UNREADABLE_MESSAGE)

    def test_a_page_count_mupdf_cannot_read_is_refused(self) -> None:
        """``/Count -1``: MuPDF's own ``page_count`` raises. Opened but not
        countable is not "cannot open": refused, not swallowed."""
        data = uncounted_bomb_pdf(self._BOMB, count_entry=b"/Count -1")
        for check in (check_scan_bytes, check_pdf_content_bytes):
            with self.subTest(check.__name__):
                with self.assertRaises(ScanRejectedError) as caught:
                    check(data)
                self.assertEqual(str(caught.exception), scan_limits._PAGE_COUNT_UNREADABLE_MESSAGE)

    def test_an_overstated_count_is_refused_not_swallowed(self) -> None:
        """The guard probe's file: ``/Count 5`` over 3 real pages. Upload and
        the whole-document check refuse it; the crop route's page-scoped
        check refuses a missing page with a ``ScanRejectedError``, which that
        route answers with its 422, and still passes a real one."""
        data = overstated_count_pdf(3, count=5)
        for check in (check_scan_bytes, check_pdf_content_bytes):
            with self.subTest(check.__name__):
                with self.assertRaises(ScanRejectedError) as caught:
                    check(data)
                self.assertIn("Page 4 of this PDF could not be read", str(caught.exception))
        with pymupdf.open(stream=data, filetype="pdf") as doc:  # type: ignore[no-untyped-call]
            check_pdf_page_content(doc, 2)
            with self.assertRaises(ScanRejectedError):
                check_pdf_page_content(doc, 3)

    def test_a_deep_chain_is_refused_at_upload(self) -> None:
        """pdfium cannot plan a 2,000-deep chain, which used to end the upload
        check before the MuPDF check ran. It runs now, and its work bound
        refuses the chain."""
        with self.assertRaises(ScanTooLargeError) as caught:
            check_scan_bytes(deep_page_chain_pdf(2_000))
        self.assertEqual(str(caught.exception), scan_limits._PAGE_TREE_TOO_COMPLEX_MESSAGE)

    def test_a_file_mupdf_opened_but_could_not_walk_fails_closed(self) -> None:
        """Only "MuPDF will not open it at all" is exempt; anything else going
        wrong once it has is a refusal."""
        data = _pdf_bytes((595.0, 842.0))
        failing = patch.object(scan_limits, "check_pdf_content", side_effect=RuntimeError("x"))
        with failing, self.assertRaises(ScanRejectedError):
            check_pdf_content_bytes(data)

    def test_a_pdf_only_pdfium_can_open_is_refused(self) -> None:
        """pdfium counted pages MuPDF could not open the file to measure: the
        two readers disagree, so refused. With no pdfium count (pdfium could
        not open it either) it passes, as garbage bytes always have."""
        data = _pdf_bytes((595.0, 842.0))
        with patch.object(scan_limits.pymupdf, "open", side_effect=RuntimeError("x")):
            with self.assertRaises(ScanRejectedError):
                check_pdf_content_bytes(data, pdfium_pages=1)
            check_pdf_content_bytes(data)

    def test_ordinary_pdfs_still_pass_upload(self) -> None:
        check_scan_bytes(_pdf_bytes((595.0, 842.0), (595.0, 842.0)))
        check_scan_bytes(born_digital_text_pdf(pages=MAX_SCAN_PAGES))
        check_scan_bytes(wrapped_page_tree_pdf(MAX_SCAN_PAGES, wrap=2))
        check_scan_bytes(b"%PDF-1.4 fake")

    @unittest.skipUnless(_FIXTURE.is_file(), "handwritten-59 fixture not present")
    def test_the_committed_fixture_still_passes_upload(self) -> None:
        check_scan_bytes(_FIXTURE.read_bytes())


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
        # Refused by the whole-document check that runs first (review round 1):
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


class RawObjectStreamTests(unittest.TestCase):
    """Task 9c review round 2: with a broken xref, MuPDF's repair loads every
    object stream it finds while the file is being OPENED, container-mates
    and all -- before any check can run. So object streams are found and
    bounded in the raw bytes, before any reader opens the file."""

    _BOMB = scan_limits.MAX_OBJECT_STREAM_BYTES // 2 + 1_000

    def _trapped(self) -> contextlib.ExitStack:
        """Fail the test if any reader opens the file."""
        stack = contextlib.ExitStack()
        for target, name in ((scan_limits.pymupdf, "open"), (scan_limits.pdfium, "PdfDocument")):
            stack.enter_context(
                patch.object(target, name, side_effect=AssertionError(f"{name} was called"))
            )
        return stack

    def test_a_container_bomb_is_refused_before_any_reader_opens_the_file(self) -> None:
        """A 16 KB file whose page dict shares a Flate object stream with an
        array that inflates past the bound; startxref is off, so MuPDF's
        repair would parse the whole container at open (459 MB for the
        reviewer's 10M-element case). Refused from the raw bytes, however
        the container's dictionary is spelled."""
        variants = {
            "plain": {},
            "no space": {"type_entry": b"/Type/ObjStm"},
            "whitespace and a comment": {"type_entry": b"/Type \r\n  % note\n  /ObjStm"},
            "escaped name": {"type_entry": b"/Type /Obj#53tm"},
            "keywords inside a string first": {
                "type_entry": b"/Note (stream endobj 1 0 obj \\) x) /Type /ObjStm"
            },
            "filter array": {"filter_entry": b"/Filter [ /FlateDecode ]"},
            "abbreviated filter in an array": {"filter_entry": b"/Filter[/Fl]"},
            "length too long": {"length_delta": 40},
            "length too short": {"length_delta": -40},
        }
        for label, kwargs in variants.items():
            data = shared_container_broken_xref_pdf(self._BOMB, **kwargs)  # type: ignore[arg-type]
            self.assertLess(len(data), 100_000)
            for check in (
                check_scan_bytes,
                check_pdf_content_bytes,
                canonical_pdf_bytes,
                check_object_stream_bytes,
            ):
                with self.subTest(label, check=check.__name__), self._trapped():
                    with self.assertRaises(ScanTooLargeError) as caught:
                        check(data)
                    self.assertEqual(str(caught.exception), scan_limits._OBJECT_STREAMS_MESSAGE)

    def test_a_scan_past_the_token_budget_is_refused_as_too_complex(self) -> None:
        """The raw scan reads every dictionary token by token; one crafted
        dictionary of 600,000 names (1.2M tokens) is refused once past
        ``MAX_PRESCAN_TOKENS``, rather than costing seconds per upload."""
        data = b"%PDF-1.7\n1 0 obj\n<<" + b"/K 0 " * 600_000 + b">>\nendobj\n"
        self.assertGreater(1_200_000, scan_limits.MAX_PRESCAN_TOKENS)
        with self._trapped(), self.assertRaises(ScanTooLargeError) as caught:
            check_object_stream_bytes(data)
        self.assertEqual(str(caught.exception), scan_limits._STRUCTURE_TOO_COMPLEX_MESSAGE)

    def test_spaces_after_the_stream_keyword_do_not_hide_a_container(self) -> None:
        """Scanner review: MuPDF skips any run of spaces after ``stream``
        before the data, and pdfium skips to the end of the line, so a
        container whose data follows ``stream \\n`` inflates in full at open
        (a 16 KB file to 388 MB). The scan measures from where each reader
        starts, so these are refused, not scored as 0 bytes."""
        for separator in (b" \n", b"   \n", b" \t\n", b" \r\n", b"  \r"):
            data = shared_container_broken_xref_pdf(self._BOMB, stream_separator=separator)
            with self.subTest(separator=separator), self._trapped():
                with self.assertRaises(ScanTooLargeError) as caught:
                    check_object_stream_bytes(data)
                self.assertEqual(str(caught.exception), scan_limits._OBJECT_STREAMS_MESSAGE)

    def test_every_standard_separator_is_measured_in_full(self) -> None:
        """``\\r\\n``, ``\\n`` and ``\\r``: a container just under the bound
        passes, one just over it is refused -- so each is measured in full."""
        under = scan_limits.MAX_OBJECT_STREAM_BYTES // 2 - 10_000
        for separator in (b"\r\n", b"\n", b"\r"):
            with self.subTest(separator=separator), self._trapped():
                check_object_stream_bytes(
                    shared_container_broken_xref_pdf(under, stream_separator=separator)
                )
                with self.assertRaises(ScanTooLargeError):
                    check_object_stream_bytes(
                        shared_container_broken_xref_pdf(self._BOMB, stream_separator=separator)
                    )

    def test_a_container_no_reader_can_inflate_is_refused(self) -> None:
        """Fail closed: a Flate container that yields nothing from any start a
        reader could use is refused as unreadable, never scored as 0 bytes."""
        data = shared_container_broken_xref_pdf(1_000, corrupt_header=True)
        with self._trapped(), self.assertRaises(ScanRejectedError) as caught:
            check_object_stream_bytes(data)
        self.assertEqual(str(caught.exception), scan_limits._OBJECT_STREAM_UNREADABLE_MESSAGE)

    def test_an_encrypted_files_object_streams_count_at_their_flate_ceiling(self) -> None:
        """Scanner review: an encrypted file's object streams are ciphertext --
        nothing inflates, and with an empty user password an attacker can make
        the ciphertext inflate to a harmless few bytes while the plaintext MuPDF
        decrypts is a bomb. So each counts at the most Flate can expand its
        length to (``_FLATE_MAX_RATIO``). The committed RC4 fixture's 2.7 KB of
        object streams passes; a 16 KB one is refused, however /Encrypt is
        spelled, and even when its bytes do not inflate at all."""
        small = shared_container_broken_xref_pdf(
            1_000, encrypt_entry=b"/Encrypt 99 0 R", corrupt_header=True
        )
        check_object_stream_bytes(small)
        for entry in (b"/Encrypt 99 0 R", b"/Encr#79pt 99 0 R", b"/Encrypt<</Filter/Standard>>"):
            data = shared_container_broken_xref_pdf(
                self._BOMB, encrypt_entry=entry, corrupt_header=True
            )
            with self.subTest(entry=entry), self._trapped():
                with self.assertRaises(ScanTooLargeError) as caught:
                    check_object_stream_bytes(data)
                self.assertEqual(str(caught.exception), scan_limits._OBJECT_STREAMS_MESSAGE)

    @unittest.skipUnless(
        (Path(__file__).parent / "fixtures" / "0580_s11_gt.pdf").is_file(), "fixture not present"
    )
    def test_the_committed_encrypted_fixture_passes(self) -> None:
        """``0580_s11_gt.pdf`` is RC4-encrypted (empty user password) and keeps
        its objects in object streams: it passes the raw scan and upload."""
        data = (Path(__file__).parent / "fixtures" / "0580_s11_gt.pdf").read_bytes()
        check_object_stream_bytes(data)
        check_scan_bytes(data)

    def test_a_container_the_bounded_inflate_cannot_measure_is_refused(self) -> None:
        data = shared_container_broken_xref_pdf(1_000, filter_entry=b"/Filter /LZWDecode")
        with self._trapped(), self.assertRaises(ScanRejectedError) as caught:
            check_object_stream_bytes(data)
        self.assertEqual(str(caught.exception), scan_limits._OBJECT_STREAM_ENCODING_MESSAGE)

    def test_ordinary_object_streams_pass(self) -> None:
        """Object streams as producers write them -- pymupdf's use_objstms
        save of a 40-page born-digital file, a merge of image scans with an
        xref stream and object streams, and the same small shared container
        under a broken xref -- pass the raw scan and upload."""
        with pymupdf.open(
            stream=born_digital_text_pdf(pages=MAX_SCAN_PAGES), filetype="pdf"
        ) as doc:  # type: ignore[no-untyped-call]
            born_digital: bytes = doc.tobytes(garbage=1, use_objstms=1)  # type: ignore[no-untyped-call]
        merged = pymupdf.open()  # type: ignore[no-untyped-call]
        for _ in range(12):
            scan = pymupdf.open()  # type: ignore[no-untyped-call]
            page = scan.new_page(width=595, height=842)
            pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 200, 280), 0)
            page.insert_image(page.rect, stream=pixmap.tobytes("png"))
            merged.insert_pdf(scan)
            scan.close()
        merged_objstm: bytes = merged.tobytes(garbage=1, deflate=True, use_objstms=1)
        merged.close()
        for label, data in (
            ("born-digital", born_digital),
            ("merged scans", merged_objstm),
            ("small shared container, broken xref", shared_container_broken_xref_pdf(1_000)),
        ):
            with self.subTest(label):
                self.assertIn(b"/ObjStm", data)
                check_object_stream_bytes(data)
                check_scan_bytes(data)


class RewriteFidelityTests(unittest.TestCase):
    """Task 9c review round 2: pdfium must render the rewrite exactly as it
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
    """Task 9c review round 1: extraction's rewrite may parse only what the
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
            patch.object(scan_limits, "_page_tree") as page_tree,
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
