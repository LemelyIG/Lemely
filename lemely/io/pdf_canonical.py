"""Opening user scans with MuPDF, and the canonical rewrite pdfium renders.

#262: moved out of :mod:`lemely.io.scan_limits`, which re-exports its public
names. Owns the only sanctioned MuPDF openers (:func:`open_checked_pdf`,
:func:`open_scan_image_document`), the whole-document check on bytes
(:func:`check_pdf_content_bytes`), the pages-only rewrite
(:func:`canonical_pdf_bytes`) and pdfium's page count and plan for the
upload check. Imports :mod:`lemely.io._scan_common`,
:mod:`lemely.io.pdf_prescan` and :mod:`lemely.io.pdf_content_walk`.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pymupdf
import pymupdf.mupdf as _mupdf
import pypdfium2 as pdfium

from lemely.io._scan_common import (
    _PAGE_COUNT_UNREADABLE_MESSAGE,
    _STRUCTURE_TOO_COMPLEX_MESSAGE,
    _UNCHECKABLE_MESSAGE,
    ScanRejectedError,
    ScanTooLargeError,
    open_scan_image,
    plan_image,
    plan_pdf_pages,
)
from lemely.io.pdf_content_walk import (
    check_pdf_content,
)
from lemely.io.pdf_prescan import (
    PrescannedPdf,
    prescan_pdf,
)

if TYPE_CHECKING:
    from collections.abc import Callable


def open_checked_pdf(pdf: bytes | PrescannedPdf) -> pymupdf.Document:
    """MuPDF's document for the PDF ``pdf``: the one way user PDF bytes are opened.

    Runs :func:`check_object_stream_bytes` first, from the raw bytes, unless
    ``pdf`` is a :class:`PrescannedPdf` (it has run): with a damaged xref
    MuPDF repairs the file while OPENING it, parsing every object stream it
    finds, before any check on the opened document can run. Every MuPDF
    open of an upload -- the whole-document check, the canonical rewrite,
    the paper preview and the review crop -- comes through here, so none
    can skip the pre-scan (final review, item 4). Raises
    :class:`ScanRejectedError` from the pre-scan; whatever ``pymupdf.open``
    raises for bytes it cannot open propagates. The caller closes the
    document.
    """
    # Before the open: repair parses containers at open.
    scanned = pdf if isinstance(pdf, PrescannedPdf) else prescan_pdf(pdf)
    # PyMuPDF's `open` is an untyped alias for `Document`, so a strict-mode
    # call needs the ignore. Narrowed to this one code, not the module.
    return pymupdf.open(stream=scanned.data, filetype="pdf")  # type: ignore[no-untyped-call]


#: MuPDF's ``filetype`` for each format :func:`open_scan_image` admits. An MPO
#: (a phone JPEG with a second image) is a JPEG to MuPDF.
_MUPDF_IMAGE_FILETYPES = {
    "JPEG": "jpeg",
    "MPO": "jpeg",
    "PNG": "png",
    "TIFF": "tiff",
    "WEBP": "webp",
    "BMP": "bmp",
}


def open_scan_image_document(data: bytes) -> pymupdf.Document:
    """MuPDF's one-page document for the scan image ``data``; never a PDF.

    For a caller that draws an image upload with MuPDF (the paper preview).
    The format is named from the header by :func:`open_scan_image` --
    allowlisted formats only, nothing decoded -- and the image's size is
    held to :func:`decode_pixel_cap` for its mode and format, as upload,
    extraction and the crop route hold it. MuPDF is then told that format,
    so the image's own magic bytes, at offset 0, decide how it is read:
    bytes Pillow does not recognise as an allowlisted image (a PDF among
    them) never reach MuPDF, which would otherwise sniff and repair a PDF
    while opening it, before any pre-scan. Raises
    :class:`ScanRejectedError` (a format outside the allowlist, a size over
    the cap, or a document MuPDF opened as a PDF anyway), or what Pillow
    and MuPDF raise for bytes they cannot read. The caller closes the
    document.
    """
    with open_scan_image(io.BytesIO(data)) as opened:
        image_format = opened.format
        plan_image(opened.width, opened.height, opened.mode, image_format)
    filetype = _MUPDF_IMAGE_FILETYPES[image_format or ""]
    doc = pymupdf.open(stream=data, filetype=filetype)  # type: ignore[no-untyped-call]
    if doc.is_pdf:
        doc.close()  # type: ignore[no-untyped-call]
        raise ScanRejectedError(_UNCHECKABLE_MESSAGE, reason="uncheckable")
    return doc


def _check_opened(
    open_doc: Callable[[], pymupdf.Document],
    pdfium_pages: int | None,
    *,
    optional_content: bool = False,
) -> None:
    """:func:`check_pdf_content` on the document ``open_doc`` opens, failing closed.

    The one exemption is narrow (Task 9b): MuPDF will not open the bytes at
    all AND pdfium counted no pages either -- garbage with a ``%PDF``
    header, which extraction fails on too (the upload routes' tests post
    ``%PDF-1.4 fake``). If pdfium counted pages MuPDF cannot open, the
    readers disagree and pdfium would render pages never measured: refused.
    Once MuPDF has opened the file, anything but a clean pass is a refusal.
    With ``optional_content``, :func:`check_optional_content_bounds` runs
    after the content check (the upload check, #274 review round 2).

    ``pdfium_pages`` of ``None`` (pdfium could not open the file, or no
    caller asked it) and ``0`` (pdfium opened it and found no pages) are
    treated alike, and both pass when MuPDF cannot open the file either:
    then neither renderer has a page to render. Extraction renders only the
    pages pdfium plans, none here (``rasterise_pdf_to_pages`` then raises
    for an empty result), and the preview and crop routes render with
    MuPDF, which cannot open it.
    """
    try:
        doc = open_doc()
    except ScanRejectedError:
        raise  # the pre-scan's refusal (open_checked_pdf), never "cannot open"
    except Exception as exc:
        if pdfium_pages:
            raise ScanRejectedError(
                _PAGE_COUNT_UNREADABLE_MESSAGE, reason="reader_disagreement"
            ) from exc
        return
    try:
        check_pdf_content(doc, pdfium_pages=pdfium_pages)
        if optional_content:
            check_optional_content_bounds(doc)
    except ScanRejectedError:
        raise
    except Exception as exc:
        raise ScanRejectedError(_UNCHECKABLE_MESSAGE, reason="uncheckable") from exc
    finally:
        doc.close()  # type: ignore[no-untyped-call]


def check_pdf_content_bytes(
    data: bytes | PrescannedPdf,
    *,
    pdfium_pages: int | None = None,
    optional_content: bool = False,
) -> None:
    """:func:`check_pdf_content` on an in-memory PDF (see :func:`_check_opened`).

    ``pdfium_pages``: pdfium's page count for the same bytes, when the
    caller has it, so the two readers' counts are compared. The raw
    pre-scan runs first, through :func:`open_checked_pdf`, unless ``data``
    is a :class:`PrescannedPdf`. ``optional_content``: also
    :func:`check_optional_content_bounds`, as the upload check asks.
    """
    _check_opened(lambda: open_checked_pdf(data), pdfium_pages, optional_content=optional_content)


def canonical_pdf_bytes(data: bytes) -> bytes:
    """MuPDF's pages-only rewrite of ``data``: the one sanctioned source of pdfium input.

    Nothing may hand pdfium a PDF for rendering except through this function
    (Task 9c): the rewrite holds exactly what the content check measured.

    Task 9c (user decision): extraction renders with pdfium but this module
    measures with MuPDF, and the two repair a damaged file differently -- an
    object defined twice under an xref with 19-byte entries is the clean
    first definition to MuPDF (it reads the xref) and a content bomb to
    pdfium (it rebuilds the xref by scanning). Extraction therefore checks
    and renders these bytes, never the stored file, so pdfium can only see
    the objects MuPDF resolved.

    It resolves only what the content check has bounded (review round 1):

    1. The whole-document check (:func:`check_pdf_content`) runs on the
       original first: the object-stream and object-count bounds, the page
       cap, the page-tree bounds and the walk of every page's content,
       resources and annotation appearances. Anything it refuses is refused.
    2. Then the pages alone are copied into a new document --
       ``insert_pdf(links=False, annots=True, widgets=True)`` plus each
       page's ``/Group`` -- and that is written with ``tobytes(garbage=1)``.
       The copy resolves each page's ``/Contents``, ``/Resources``, page
       boxes, ``/Rotate``, ``/UserUnit``, ``/Group`` and annotations (form
       fields through pymupdf's widget copy), and nothing else: an object
       hung off the catalog, the trailer or a page-dict key no renderer
       reads is never parsed, whatever its size. ``links=False`` because
       rebuilding links loads every page and resolves link destinations
       through the catalog; a ``/Link`` annotation draws nothing in pdfium
       without an appearance stream, which link annotations do not carry in
       practice. ``/Group`` is added back because ``insert_pdf`` omits it
       and a page's transparency group changes how it composites.
       Streams are copied as stored: nothing is decompressed, re-encoded
       or rewritten (no ``deflate``, ``expand`` or ``clean`` -- ``clean``
       parses content streams, the very work a bomb exploits), and no page
       is loaded, so no annotation appearance is regenerated. Every PDF
       committed under ``tests/`` renders pixel-identical from the rewrite
       (18 files, 72 pages when #274 was fixed).
    3. Then, when the file has optional content, what MuPDF -- the
       teacher's preview of the stored file -- hides by default is dropped
       from the copy (#274): each page's ``/XObject`` resources and
       annotations whose ``/OC`` MuPDF judges hidden
       (:func:`_prune_hidden_optional_content`), by MuPDF's rules rather
       than the spec's where the two differ. pdfium hides such an XObject
       itself but draws such an annotation. The prune can only hide, so
       where MuPDF shows an image pdfium hides (an ``/AllOn`` membership
       with a group off, for one) the marker still sees less than the
       teacher. Dictionaries only; an ``/OC /name BDC`` in a content stream
       is left to pdfium, which honours it. Its bounds
       (:func:`check_optional_content_bounds`) are checked on the
       original first, as at upload: an ``/Annots``, ``/XObject`` or
       ``/OCGs`` past :data:`_MAX_OC_ARRAY` entries, a membership
       dictionary that reaches itself, or a judgement past
       :data:`_MAX_OC_STEPS` visits is refused as malformed.

    What an annotation's own keys or the form-field tree reference is
    copied without being walked; a compressed object there is bounded by
    the object-stream bound, an uncompressed one by the upload size cap.

    Raises :class:`ScanRejectedError` (or :class:`ScanTooLargeError`) for
    anything the check refuses, and when MuPDF cannot open or rewrite the
    bytes (garbage, or a password-protected file: extraction failed on both
    before, in pdfium, and nothing here can check what it cannot open).
    When MuPDF finds no pages, pdfium is asked for its count of the same
    bytes -- a count only, nothing is rendered: pages pdfium would find
    are pages MuPDF never measured, so that is refused too
    (:data:`_PAGE_COUNT_UNREADABLE_MESSAGE`); a PDF neither reader finds a
    page in is a :class:`ValueError`, extraction's contract for an empty
    PDF (MuPDF will not write one).
    """
    try:
        doc = open_checked_pdf(data)  # the raw pre-scan first
    except ScanRejectedError:
        raise
    except Exception as exc:
        raise ScanRejectedError(_UNCHECKABLE_MESSAGE, reason="uncheckable") from exc
    try:
        if doc.needs_pass:
            raise ScanRejectedError(_UNCHECKABLE_MESSAGE, reason="uncheckable")
        try:
            check_pdf_content(doc)
            # #274 review round 2: the prune's bounds, on the original first,
            # as at upload, before anything is copied.
            check_optional_content_bounds(doc)
            page_count = int(doc.page_count)
        except ScanRejectedError:
            raise
        except Exception as exc:
            raise ScanRejectedError(_UNCHECKABLE_MESSAGE, reason="uncheckable") from exc
        if page_count == 0:
            if _pdfium_page_count(data):
                raise ScanRejectedError(
                    _PAGE_COUNT_UNREADABLE_MESSAGE, reason="reader_disagreement"
                )
            raise ValueError("the PDF has no pages")
        try:
            return _copy_pages(doc)
        except ScanRejectedError:
            raise  # the prune's bound (#274 review)
        except Exception as exc:
            raise ScanRejectedError(_UNCHECKABLE_MESSAGE, reason="uncheckable") from exc
    finally:
        doc.close()  # type: ignore[no-untyped-call]


def _copy_pages(doc: pymupdf.Document) -> bytes:
    """``doc``'s pages -- and only what they reference -- written as a new PDF.

    See :func:`canonical_pdf_bytes` for what is copied and why. Everything
    here goes through ONE graft map, so an object reached twice -- a layer
    named by a page's ``/OC`` and by ``/OCProperties``, a colour space shared
    by a page's resources and its ``/Group`` -- is one object in the copy.
    ``insert_pdf`` ignores its ``_gmap`` argument and uses the map
    registered for the source in ``out.Graftmaps`` (pymupdf 1.28), so the
    map is registered there first.
    """
    mupdf = _mupdf
    out = pymupdf.open()  # type: ignore[no-untyped-call]
    try:
        graft_map = pymupdf.Graftmap(out)  # type: ignore[no-untyped-call]
        out.Graftmaps[doc._graft_id] = graft_map
        out.insert_pdf(doc, links=False, annots=True, widgets=True)  # type: ignore[no-untyped-call]
        source = mupdf.pdf_document_from_fz_document(doc.this)  # type: ignore[no-untyped-call]
        target = mupdf.pdf_document_from_fz_document(out.this)  # type: ignore[no-untyped-call]
        for index in range(int(doc.page_count)):
            source_page = mupdf.pdf_lookup_page_obj(source, index)  # type: ignore[no-untyped-call]
            group = mupdf.pdf_dict_gets(source_page, "Group")  # type: ignore[no-untyped-call]
            if group.m_internal:
                target_page = mupdf.pdf_lookup_page_obj(target, index)  # type: ignore[no-untyped-call]
                grafted = mupdf.pdf_graft_mapped_object(graft_map.this, group)  # type: ignore[no-untyped-call]
                mupdf.pdf_dict_puts(target_page, "Group", grafted)  # type: ignore[no-untyped-call]
        # Task 9c review round 2: a page's optional content is drawn or
        # hidden by the catalog's /OCProperties, not by the page; without it
        # every layer renders, so content a file hides by default would reach
        # the marker while the teacher's preview (MuPDF, on the stored file)
        # hides it. Only /OCGs and /D, the default configuration a renderer
        # applies, are carried; the alternative /Configs a viewer can switch
        # to are not.
        source_catalog = mupdf.pdf_dict_gets(mupdf.pdf_trailer(source), "Root")  # type: ignore[no-untyped-call]
        properties = mupdf.pdf_dict_gets(source_catalog, "OCProperties")  # type: ignore[no-untyped-call]
        if properties.m_internal and mupdf.pdf_is_dict(properties):  # type: ignore[no-untyped-call]
            copied = mupdf.pdf_new_dict(target, 2)  # type: ignore[no-untyped-call]
            for key in ("OCGs", "D"):
                value = mupdf.pdf_dict_gets(properties, key)  # type: ignore[no-untyped-call]
                if value.m_internal:
                    grafted = mupdf.pdf_graft_mapped_object(graft_map.this, value)  # type: ignore[no-untyped-call]
                    mupdf.pdf_dict_puts(copied, key, grafted)  # type: ignore[no-untyped-call]
            target_catalog = mupdf.pdf_dict_gets(mupdf.pdf_trailer(target), "Root")  # type: ignore[no-untyped-call]
            added = mupdf.pdf_add_object(target, copied)  # type: ignore[no-untyped-call]
            mupdf.pdf_dict_puts(target_catalog, "OCProperties", added)  # type: ignore[no-untyped-call]
            # #274: pdfium draws an annotation whose /OC hides it, which
            # MuPDF -- the teacher's preview -- hides, so what MuPDF hides is
            # dropped from the copy. The groups are read from the copy's own
            # /OCProperties, just grafted, so the numbers are the copy's.
            # Pruned even when no group is off: MuPDF hides an /AnyOff member
            # (and a group whose /Usage says OFF) while every group is on.
            if _has_optional_content(target):
                _prune_hidden_optional_content(target, _hidden_ocg_xrefs(target))
        rewrite: bytes = out.tobytes(garbage=1)  # type: ignore[no-untyped-call]
        return rewrite
    finally:
        out.close()  # type: ignore[no-untyped-call]


#: The longest ``/Annots`` array on a page, ``/XObject`` dictionary in a
#: page's resources, and ``/OCGs`` (or ``/D /ON``, ``/D /OFF``) array the
#: judgement will read; past it the file is refused as malformed (#274
#: review). A scanned paper has a handful.
_MAX_OC_ARRAY = 1_000

#: How deeply an ``/OCMD`` may name further membership dictionaries in its
#: ``/OCGs`` before the file is refused as malformed. The spec allows none.
_MAX_OC_DEPTH = 32

#: Visits -- annotations, XObject entries, ``/OC`` values and membership-array
#: members -- one judgement of a whole document may make before the file is
#: refused as malformed (#274 review round 2). Holders need not be indirect
#: objects (a direct ``/OC`` has no number to judge it once by), so the caps
#: on each array alone do not bound the total; this does. 300,000 member
#: visits measured 0.77 s.
_MAX_OC_STEPS = 200_000


def _too_complex() -> ScanRejectedError:
    """The refusal for optional content past a bound: a structure, not a size."""
    return ScanRejectedError(_STRUCTURE_TOO_COMPLEX_MESSAGE, reason="malformed")


@dataclass
class _OcJudgement:
    """One judgement of a document's optional content: the state it shares.

    ``hidden``: :func:`_hidden_ocg_xrefs`. ``cache``: verdicts by object
    number. ``active``: the membership dictionaries being judged, for the
    cycle refusal. ``steps``: visits so far, against :data:`_MAX_OC_STEPS`.
    """

    hidden: set[int]
    cache: dict[int, bool] = field(default_factory=dict)
    active: set[int] = field(default_factory=set)
    steps: int = 0

    def step(self, visits: int = 1) -> None:
        self.steps += visits
        if self.steps > _MAX_OC_STEPS:
            raise _too_complex()


def _bounded_length(array: _mupdf.PdfObj) -> int:
    """``array``'s length, refused past :data:`_MAX_OC_ARRAY`; 0 if it is no array.

    The judgement reads each element, so a long array is one way a small
    file could make it slow (the reviewer's 49 KB probe took 29 s).
    """
    mupdf = _mupdf
    if not mupdf.pdf_is_array(array):  # type: ignore[no-untyped-call]
        return 0
    length = int(mupdf.pdf_array_len(array))  # type: ignore[no-untyped-call]
    if length > _MAX_OC_ARRAY:
        raise _too_complex()
    return length


def _indirect_numbers(array: _mupdf.PdfObj) -> set[int]:
    """The object numbers of ``array``'s indirect elements; none if it is no array."""
    mupdf = _mupdf
    numbers: set[int] = set()
    for index in range(_bounded_length(array)):
        element = mupdf.pdf_array_get(array, index)  # type: ignore[no-untyped-call]
        if mupdf.pdf_is_indirect(element):  # type: ignore[no-untyped-call]
            numbers.add(int(mupdf.pdf_to_num(element)))  # type: ignore[no-untyped-call]
    return numbers


def _has_optional_content(doc: _mupdf.PdfDocument) -> bool:
    """Whether ``doc``'s ``/OCProperties /OCGs`` lists any group.

    MuPDF shows everything when it lists none, ``/AnyOff`` members
    included, so there is then nothing to judge.
    """
    mupdf = _mupdf
    catalog = mupdf.pdf_dict_gets(mupdf.pdf_trailer(doc), "Root")  # type: ignore[no-untyped-call]
    return _bounded_length(mupdf.pdf_dict_getp(catalog, "OCProperties/OCGs")) > 0  # type: ignore[no-untyped-call]


def _hidden_ocg_xrefs(doc: _mupdf.PdfDocument) -> set[int]:
    """The optional-content groups ``doc``'s default configuration turns off.

    Of the groups ``/OCProperties /OCGs`` lists -- MuPDF ignores ``/D``'s
    word on any other -- those ``/D /OFF`` names; when ``/D /BaseState`` is
    ``/OFF``, also those ``/D /ON`` does not name. Object numbers in
    ``doc``. Reads the catalog's dictionaries only.
    """
    mupdf = _mupdf
    catalog = mupdf.pdf_dict_gets(mupdf.pdf_trailer(doc), "Root")  # type: ignore[no-untyped-call]
    listed = _indirect_numbers(mupdf.pdf_dict_getp(catalog, "OCProperties/OCGs"))  # type: ignore[no-untyped-call]
    hidden = _indirect_numbers(mupdf.pdf_dict_getp(catalog, "OCProperties/D/OFF"))  # type: ignore[no-untyped-call]
    base_state = mupdf.pdf_dict_getp(catalog, "OCProperties/D/BaseState")  # type: ignore[no-untyped-call]
    if mupdf.pdf_is_name(base_state) and mupdf.pdf_to_name(base_state) == "OFF":  # type: ignore[no-untyped-call]
        shown = _indirect_numbers(mupdf.pdf_dict_getp(catalog, "OCProperties/D/ON"))  # type: ignore[no-untyped-call]
        hidden |= listed - shown
    return hidden & listed


def _oc_hidden(oc: _mupdf.PdfObj, judgement: _OcJudgement, depth: int) -> bool:
    """Whether MuPDF hides what the ``/OC`` value ``oc`` governs.

    Mirrors MuPDF 1.29's ``pdf_is_ocg_hidden`` for viewing, measured on
    synthetic files (#274 review: the goal is the teacher's view, not the
    spec's). An optional-content group (``/Type /OCG``) is hidden when it
    is in ``judgement.hidden`` or its ``/Usage /View /ViewState`` is
    ``/OFF``; a membership dictionary (``/Type /OCMD``) as
    :func:`_ocmd_hidden` judges it; anything else is shown. Each indirect
    object is judged once. A membership dictionary that reaches itself is
    refused as malformed (#274 review round 2): MuPDF's answer then depends
    on where its walk starts, so no cached verdict could match it, and the
    spec allows no membership dictionary inside another. So is one nested
    past :data:`_MAX_OC_DEPTH`.
    """
    mupdf = _mupdf
    judgement.step()
    number = int(mupdf.pdf_to_num(oc)) if mupdf.pdf_is_indirect(oc) else 0  # type: ignore[no-untyped-call]
    if number in judgement.cache:
        return judgement.cache[number]
    if number in judgement.active or depth > _MAX_OC_DEPTH:
        raise _too_complex()
    kind = mupdf.pdf_to_name(mupdf.pdf_dict_gets(oc, "Type"))  # type: ignore[no-untyped-call]
    if kind == "OCG":
        state = mupdf.pdf_dict_getp(oc, "Usage/View/ViewState")  # type: ignore[no-untyped-call]
        result = number in judgement.hidden or mupdf.pdf_to_name(state) == "OFF"  # type: ignore[no-untyped-call]
    elif kind == "OCMD":
        if number:
            judgement.active.add(number)
        try:
            result = _ocmd_hidden(oc, judgement, depth)
        finally:
            judgement.active.discard(number)
    else:
        result = False
    if number:
        judgement.cache[number] = result
    return result


def _ocmd_hidden(ocmd: _mupdf.PdfObj, judgement: _OcJudgement, depth: int) -> bool:
    """Whether MuPDF hides what the membership dictionary ``ocmd`` governs.

    A ``/VE`` array is shown (MuPDF does not evaluate it). Otherwise ``/P``
    -- ``/AnyOn`` when absent or unknown -- combines the members ``/OCGs``
    names, the way MuPDF 1.29 does, which departs from the spec:

    * over an array (each distinct member judged once, stopping at the
      first that settles it): ``/AnyOn`` hides when every member is hidden,
      ``/AllOff`` when any is shown, ``/AllOn`` never hides and ``/AnyOff``
      always does, whatever the members' states -- but every member is
      still judged, so a cycle through it is refused as it would be
      anywhere else;
    * over anything else -- a single reference, or nothing, which counts
      as one shown member: ``/AnyOn`` and ``/AnyOff`` hide when the member
      is hidden, ``/AllOn`` and ``/AllOff`` when it is shown.

    Each member read is one step of the judgement's budget.
    """
    mupdf = _mupdf
    if mupdf.pdf_is_array(mupdf.pdf_dict_gets(ocmd, "VE")):  # type: ignore[no-untyped-call]
        return False
    policy = mupdf.pdf_to_name(mupdf.pdf_dict_gets(ocmd, "P"))  # type: ignore[no-untyped-call]
    members = mupdf.pdf_dict_gets(ocmd, "OCGs")  # type: ignore[no-untyped-call]
    if mupdf.pdf_is_array(members):  # type: ignore[no-untyped-call]
        length = _bounded_length(members)
        judgement.step(length)
        settled_by_members = policy not in ("AllOn", "AnyOff")
        every_member_hidden = True
        judged: set[int] = set()
        for index in range(length):
            member = mupdf.pdf_array_get(members, index)  # type: ignore[no-untyped-call]
            if mupdf.pdf_is_indirect(member):  # type: ignore[no-untyped-call]
                number = int(mupdf.pdf_to_num(member))  # type: ignore[no-untyped-call]
                if number in judged:
                    continue
                judged.add(number)
            if not _oc_hidden(member, judgement, depth + 1):
                every_member_hidden = False
                if settled_by_members:
                    break
        if policy == "AllOn":
            return False
        if policy == "AnyOff":
            return True
        return not every_member_hidden if policy == "AllOff" else every_member_hidden
    member_hidden = bool(members.m_internal) and _oc_hidden(members, judgement, depth + 1)
    return not member_hidden if policy in ("AllOn", "AllOff") else member_hidden


def _is_hidden(obj: _mupdf.PdfObj, judgement: _OcJudgement) -> bool:
    """Whether MuPDF hides ``obj`` -- an XObject or annotation -- by its ``/OC``.

    See :func:`_oc_hidden`.
    """
    oc = _mupdf.pdf_dict_gets(obj, "OC")  # type: ignore[no-untyped-call]
    if not oc.m_internal:
        return False
    return _oc_hidden(oc, judgement, 0)


def _judge_pages(doc: _mupdf.PdfDocument, judgement: _OcJudgement, *, prune: bool) -> None:
    """Judge every page's XObjects and annotations; with ``prune``, drop the hidden.

    For each page (looked up in the page tree, never loaded), each entry of
    its ``/Resources /XObject`` dictionary and each element of its
    ``/Annots`` is judged by :func:`_is_hidden`; with ``prune`` the hidden
    ones are deleted. Each object -- an annotation listed twice, a group many
    members name, a resource dictionary or ``/Annots`` array pages share --
    is judged once; a dictionary or array past :data:`_MAX_OC_ARRAY` is
    refused as malformed, and every visit counts against the judgement's
    step budget. Only dictionaries are read: no content stream is parsed.
    """
    mupdf = _mupdf
    decided: dict[int, bool] = {}
    containers: set[int] = set()

    def judged(obj: _mupdf.PdfObj) -> bool:
        judgement.step()
        if not mupdf.pdf_is_indirect(obj):  # type: ignore[no-untyped-call]
            return _is_hidden(obj, judgement)
        number = int(mupdf.pdf_to_num(obj))  # type: ignore[no-untyped-call]
        if number not in decided:
            decided[number] = _is_hidden(obj, judgement)
        return decided[number]

    def first_visit(container: _mupdf.PdfObj) -> bool:
        if not mupdf.pdf_is_indirect(container):  # type: ignore[no-untyped-call]
            return True
        number = int(mupdf.pdf_to_num(container))  # type: ignore[no-untyped-call]
        if number in containers:
            return False
        containers.add(number)
        return True

    resources_key = mupdf.pdf_new_name("Resources")  # type: ignore[no-untyped-call]
    for index in range(int(mupdf.pdf_count_pages(doc))):  # type: ignore[no-untyped-call]
        page = mupdf.pdf_lookup_page_obj(doc, index)  # type: ignore[no-untyped-call]
        resources = mupdf.pdf_dict_get_inheritable(page, resources_key)  # type: ignore[no-untyped-call]
        xobjects = mupdf.pdf_dict_gets(resources, "XObject")  # type: ignore[no-untyped-call]
        if (
            mupdf.pdf_is_dict(xobjects)  # type: ignore[no-untyped-call]
            and first_visit(resources)
            and first_visit(xobjects)
        ):
            length = int(mupdf.pdf_dict_len(xobjects))  # type: ignore[no-untyped-call]
            if length > _MAX_OC_ARRAY:
                raise _too_complex()
            names = [
                mupdf.pdf_dict_get_key(xobjects, entry)  # type: ignore[no-untyped-call]
                for entry in range(length)
                if judged(mupdf.pdf_dict_get_val(xobjects, entry))  # type: ignore[no-untyped-call]
            ]
            if prune:
                for name in names:
                    mupdf.pdf_dict_del(xobjects, name)  # type: ignore[no-untyped-call]
        annots = mupdf.pdf_dict_gets(page, "Annots")  # type: ignore[no-untyped-call]
        if not first_visit(annots):
            continue
        for entry in reversed(range(_bounded_length(annots))):
            if judged(mupdf.pdf_array_get(annots, entry)) and prune:  # type: ignore[no-untyped-call]
                mupdf.pdf_array_delete(annots, entry)  # type: ignore[no-untyped-call]


def check_optional_content_bounds(doc: pymupdf.Document) -> None:
    """Refuse a PDF whose optional content the rewrite could not judge in bounds.

    Runs the judgement :func:`canonical_pdf_bytes` prunes by, without
    pruning: the caps on ``/OCGs``, ``/D /ON``, ``/D /OFF``, ``/Annots``
    and ``/XObject`` (:data:`_MAX_OC_ARRAY`), the refusal of a membership
    dictionary that reaches itself, and the step budget
    (:data:`_MAX_OC_STEPS`). Raises :class:`ScanRejectedError` with reason
    ``malformed`` past any of them, so the upload check refuses at once
    (#274 review round 2) what extraction would refuse later. A document
    with no optional content, or that is not a PDF, passes untouched. Reads
    dictionaries only; run it after :func:`check_pdf_content`.
    """
    if not doc.is_pdf:
        return
    source = _mupdf.pdf_document_from_fz_document(doc.this)  # type: ignore[no-untyped-call]
    if _has_optional_content(source):
        _judge_pages(source, _OcJudgement(_hidden_ocg_xrefs(source)), prune=False)


def _prune_hidden_optional_content(target: _mupdf.PdfDocument, hidden: set[int]) -> None:
    """Drop the XObjects and annotations MuPDF hides by default from ``target``.

    ``target`` is the copy; ``hidden``: its :func:`_hidden_ocg_xrefs`. See
    :func:`_judge_pages`. An operator that draws marked content
    (``/OC /name BDC``) is left as it is -- pdfium honours that itself.
    """
    _judge_pages(target, _OcJudgement(hidden), prune=True)


def _pdfium_page_count(data: bytes) -> int:
    """The page count pdfium gives ``data``, or 0 if it cannot open it. Renders nothing."""
    try:
        pdf = pdfium.PdfDocument(data)
    except Exception:
        return 0
    try:
        return len(pdf)
    except Exception:
        return 0
    finally:
        pdf.close()


def _pdfium_plan(data: bytes) -> int | None:
    """Plan ``data``'s pages as extraction will; pdfium's page count, or ``None``.

    Raises :class:`ScanTooLargeError` for a geometry extraction refuses.
    ``None`` when pdfium cannot open the bytes or count their pages. A page
    pdfium cannot size (``plan_pdf_pages`` raising pypdfium2's own
    ``PdfiumError``) still returns the count: extraction's own planning
    refuses that file before rendering any of it, but the crop route
    renders with MuPDF, so :func:`check_scan_bytes` runs the MuPDF check
    either way (Task 9b; it used to be skipped here).
    """
    try:
        pdf = pdfium.PdfDocument(data)
    except Exception:
        return None
    count: int | None = None
    try:
        count = len(pdf)
        plan_pdf_pages(pdf)
    except ScanTooLargeError:
        raise
    except Exception:
        return count
    finally:
        pdf.close()
    return count
