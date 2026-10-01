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
from typing import TYPE_CHECKING

import pymupdf
import pymupdf.mupdf as _mupdf
import pypdfium2 as pdfium

from lemely.io._scan_common import (
    _PAGE_COUNT_UNREADABLE_MESSAGE,
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


def _check_opened(open_doc: Callable[[], pymupdf.Document], pdfium_pages: int | None) -> None:
    """:func:`check_pdf_content` on the document ``open_doc`` opens, failing closed.

    The one exemption is narrow (Task 9b): MuPDF will not open the bytes at
    all AND pdfium counted no pages either -- garbage with a ``%PDF``
    header, which extraction fails on too (the upload routes' tests post
    ``%PDF-1.4 fake``). If pdfium counted pages MuPDF cannot open, the
    readers disagree and pdfium would render pages never measured: refused.
    Once MuPDF has opened the file, anything but a clean pass is a refusal.

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
    except ScanRejectedError:
        raise
    except Exception as exc:
        raise ScanRejectedError(_UNCHECKABLE_MESSAGE, reason="uncheckable") from exc
    finally:
        doc.close()  # type: ignore[no-untyped-call]


def check_pdf_content_bytes(
    data: bytes | PrescannedPdf, *, pdfium_pages: int | None = None
) -> None:
    """:func:`check_pdf_content` on an in-memory PDF (see :func:`_check_opened`).

    ``pdfium_pages``: pdfium's page count for the same bytes, when the
    caller has it, so the two readers' counts are compared. The raw
    pre-scan runs first, through :func:`open_checked_pdf`, unless ``data``
    is a :class:`PrescannedPdf`.
    """
    _check_opened(lambda: open_checked_pdf(data), pdfium_pages)


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
       is loaded, so no annotation appearance is regenerated. All 26
       committed PDFs (171 pages) render pixel-identical from the rewrite.

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
        rewrite: bytes = out.tobytes(garbage=1)  # type: ignore[no-untyped-call]
        return rewrite
    finally:
        out.close()  # type: ignore[no-untyped-call]


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
