"""Bounds on scan geometry, checked before anything is rendered or decoded.

Spec 2026-09-26 §6 (#2). A scan's byte size bounds nothing: a PDF under 2 KB
can declare a 14,400 pt page (40,000 x 40,000 px at 200 DPI -- 4.8 GB of RGB)
and a PNG of a few hundred KB can declare tens of megapixels. Before this
module, `rasterise.py` rendered whatever the file declared, inside a 1 GiB
worker. The rule is a hybrid: up to :data:`MAX_PAGE_PX` a page is used as is;
between the target and :data:`MAX_DECODE_PX` it is downscaled to fit; beyond
that, or past :data:`MAX_SCAN_PAGES`, it is rejected with a
:class:`ScanTooLargeError` whose message names the limit. For a raster image
the reject boundary is per mode (#256, :func:`decode_pixel_cap`): colour keeps
:data:`MAX_DECODE_PX`, a bilevel or greyscale scan gets
:data:`MAX_DECODE_PX_GREY`. The same hybrid applies to the whole scan: pages
summing past :data:`MAX_SCAN_TOTAL_PX` all render at one uniformly lower DPI,
rejected below :data:`MIN_EXTRACTION_DPI`.

Pure: pypdfium2, pymupdf and Pillow only, no I/O of its own. The web upload routes
call :func:`check_scan_bytes` on the uploaded body (headers and page sizes
only -- nothing is rendered) so the user gets a clear 422; `rasterise.py`
applies the same plans at extraction time as a second line of defence.

#262: this module is the public face of four others and re-exports every
name its callers import from it: :mod:`lemely.io._scan_common` (the limits,
messages, errors, page and image planners, and the image opener),
:mod:`lemely.io.pdf_prescan` (the raw-bytes pre-scan),
:mod:`lemely.io.pdf_content_walk` (the content walk of an opened PDF) and
:mod:`lemely.io.pdf_canonical` (the MuPDF openers and the canonical
rewrite). It owns :func:`check_scan_bytes`, the upload check.
"""

from __future__ import annotations

import io

# Not used here: kept as attributes of this module, which callers (and the
# tests' patches) have reached the readers through since before the split.
import pymupdf  # noqa: F401
import pypdfium2 as pdfium  # noqa: F401
from PIL import Image

from lemely.io._scan_common import (
    _CROP_PAGES_MESSAGE,  # noqa: F401
    _FLATE_FILTER_NAMES,  # noqa: F401
    _IGNORE_CAPPED_BOMB_WARNING,  # noqa: F401
    _IMAGE_TOO_LARGE_MESSAGE,  # noqa: F401
    _INFLATE_CHUNK,  # noqa: F401
    _MALFORMED_STRUCTURE_MESSAGE,  # noqa: F401
    _MAX_OBJECTS_PER_PAGE,  # noqa: F401
    _OBJECT_STREAM_ENCODING_MESSAGE,  # noqa: F401
    _OBJECT_STREAM_SEPARATOR_MESSAGE,  # noqa: F401
    _OBJECT_STREAM_UNREADABLE_MESSAGE,  # noqa: F401
    _OBJECT_STREAMS_MESSAGE,  # noqa: F401
    _ONE_BYTE_GREY_MODES,  # noqa: F401
    _PAGE_COUNT_UNREADABLE_MESSAGE,  # noqa: F401
    _PAGE_STRUCTURE_MALFORMED_MESSAGE,  # noqa: F401
    _PAGE_TREE_TOO_COMPLEX_MESSAGE,  # noqa: F401
    _PAGE_UNREADABLE_MESSAGE,  # noqa: F401
    _REDUCE_FACTORS,  # noqa: F401
    _SCAN_PAGES_MESSAGE,  # noqa: F401
    _STRUCTURE_TOO_COMPLEX_MESSAGE,  # noqa: F401
    _TOO_MANY_OBJECTS_MESSAGE,  # noqa: F401
    _TOO_MANY_PDF_OBJECTS_MESSAGE,  # noqa: F401
    _TWO_BYTE_GREY_MODES,  # noqa: F401
    _UNCHECKABLE_MESSAGE,  # noqa: F401
    _UNSUPPORTED_FILTER_MESSAGE,  # noqa: F401
    _UNSUPPORTED_IMAGE_MESSAGE,  # noqa: F401
    _WALK_FAILED_MESSAGE,  # noqa: F401
    _WHOLE_SCAN_MESSAGE,  # noqa: F401
    EXTRACTION_DPI,
    GREY_CEILING_MODES,
    MAX_CROP_PAGES,
    MAX_DECODE_PX,
    MAX_DECODE_PX_GREY,
    MAX_DECODE_PX_WEBP,
    MAX_OBJECT_STREAM_BYTES,
    MAX_PAGE_CONTENT_BYTES,
    MAX_PAGE_PX,
    MAX_PDF_OBJECTS,
    MAX_PRESCAN_TOKENS,
    MAX_SCAN_CONTENT_BYTES,
    MAX_SCAN_PAGES,
    MAX_SCAN_TOTAL_PX,
    MIN_EXTRACTION_DPI,
    PDF_MAGIC,
    REFUSAL_REASONS,
    SCAN_IMAGE_FORMATS,
    PagePlan,
    ScanRejectedError,
    ScanTooLargeError,
    ScanUnsupportedEncodingError,
    ScanUnsupportedFormatError,
    _ignore_capped_bomb_warning,  # noqa: F401
    _pillow_claims,  # noqa: F401
    decode_pixel_cap,
    looks_like_pdf,
    open_scan_image,
    plan_image,
    plan_page_dpi,
    plan_pdf_pages,
)
from lemely.io.pdf_canonical import (
    _pdfium_plan,
    canonical_pdf_bytes,
    check_pdf_content_bytes,
    open_checked_pdf,
)
from lemely.io.pdf_content_walk import (
    _CROP_PAGE_BOUND,  # noqa: F401
    _SCAN_PAGE_BOUND,  # noqa: F401
    _collection_refs,  # noqa: F401
    _ContentBudget,  # noqa: F401
    _page_tree,  # noqa: F401
    _PageBound,  # noqa: F401
    _PageTree,  # noqa: F401
    _PageWalk,  # noqa: F401
    _parent,  # noqa: F401
    _resources_refs,  # noqa: F401
    _walk_resource_graph,  # noqa: F401
    check_pdf_content,
    check_pdf_page_content,
    decoded_stream_size,
)
from lemely.io.pdf_prescan import (
    PrescannedPdf,
    check_object_stream_bytes,
    prescan_pdf,
)

__all__ = [
    "EXTRACTION_DPI",
    "GREY_CEILING_MODES",
    "MAX_CROP_PAGES",
    "MAX_DECODE_PX",
    "MAX_DECODE_PX_GREY",
    "MAX_DECODE_PX_WEBP",
    "MAX_OBJECT_STREAM_BYTES",
    "MAX_PAGE_CONTENT_BYTES",
    "MAX_PAGE_PX",
    "MAX_PDF_OBJECTS",
    "MAX_PRESCAN_TOKENS",
    "MAX_SCAN_CONTENT_BYTES",
    "MAX_SCAN_PAGES",
    "MAX_SCAN_TOTAL_PX",
    "MIN_EXTRACTION_DPI",
    "PDF_MAGIC",
    "REFUSAL_REASONS",
    "SCAN_IMAGE_FORMATS",
    "PagePlan",
    "PrescannedPdf",
    "ScanRejectedError",
    "ScanTooLargeError",
    "ScanUnsupportedEncodingError",
    "ScanUnsupportedFormatError",
    "canonical_pdf_bytes",
    "check_object_stream_bytes",
    "check_pdf_content",
    "check_pdf_content_bytes",
    "check_pdf_page_content",
    "check_scan_bytes",
    "decode_pixel_cap",
    "decoded_stream_size",
    "looks_like_pdf",
    "open_checked_pdf",
    "open_scan_image",
    "plan_image",
    "plan_page_dpi",
    "plan_pdf_pages",
    "prescan_pdf",
]


def check_scan_bytes(data: bytes) -> None:
    """The upload-time check: page sizes and image headers only, nothing rendered.

    Bytes that neither pypdfium2 nor Pillow can open are NOT rejected here --
    extraction fails on them later, exactly as it does today -- so the only
    422 this produces is a measured, over-limit geometry (or Pillow's
    decompression-bomb guard, which fires on the declared size before any
    pixel is decoded), or an image in a format outside
    :data:`SCAN_IMAGE_FORMATS` (#256 review: some decode while opening, so
    they are named from their first bytes, never opened; see
    :func:`open_scan_image`). A document pdfium opens but cannot size a page of
    (``plan_pdf_pages`` raising pypdfium2's own ``PdfiumError``) is not
    refused for that alone: extraction's planning refuses it before
    rendering anything, as it does today.

    And, for a PDF, the decoded size of each page's content streams (Task
    11b) -- read from the raw streams with a bounded inflate, never rendered
    -- which runs whenever MuPDF can open the file, whatever pdfium made of
    it (Task 9b: skipping it on a pdfium planning failure let a page tree
    too deep for pdfium through unmeasured, and the crop route renders with
    MuPDF). It is given pdfium's page count, and refuses a file the two
    readers count differently, or whose pages MuPDF counted but cannot
    read (:func:`check_pdf_content`).
    """
    if looks_like_pdf(data):
        # Task 9c review round 2: object streams first, from the raw bytes,
        # before either reader opens the file -- MuPDF's xref repair parses
        # them while opening, before any check. Once (final review, item 5):
        # the content check below is handed the scanned bytes.
        scanned = prescan_pdf(data)
        # Task 11b: geometry first, then content -- with pdfium's count, so
        # a page only pdfium would render is not left unmeasured (Task 9b).
        # #274: and the optional-content bounds extraction's rewrite would
        # refuse, so such a file is a 422 now rather than a failed extraction.
        check_pdf_content_bytes(scanned, pdfium_pages=_pdfium_plan(data), optional_content=True)
        return
    try:
        # #256 review: allowlisted formats only, so no plugin decodes inside the open.
        with open_scan_image(io.BytesIO(data)) as opened:
            # #256: judged against its own mode's ceiling, from the header.
            plan_image(opened.width, opened.height, opened.mode, opened.format)
    except Image.DecompressionBombError as exc:
        raise ScanTooLargeError(
            "This scan's image is too large to process safely. Rescan at a lower resolution.",
            reason="image_px",
        ) from exc
    except ScanRejectedError:
        raise
    except Exception:
        return
