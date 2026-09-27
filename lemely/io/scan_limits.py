"""Bounds on scan geometry, checked before anything is rendered or decoded.

Spec 2026-09-26 §6 (#2). A scan's byte size bounds nothing: a PDF under 2 KB
can declare a 14,400 pt page (40,000 x 40,000 px at 200 DPI -- 4.8 GB of RGB)
and a PNG of a few hundred KB can declare tens of megapixels. Before this
module, `rasterise.py` rendered whatever the file declared, inside a 1 GiB
worker. The rule is a hybrid: up to :data:`MAX_PAGE_PX` a page is used as is;
between the target and :data:`MAX_DECODE_PX` it is downscaled to fit; beyond
that, or past :data:`MAX_SCAN_PAGES`, it is rejected with a
:class:`ScanTooLargeError` whose message names the limit.

Pure: pypdfium2 and Pillow only, no I/O of its own. The web upload routes
call :func:`check_scan_bytes` on the uploaded body (headers and page sizes
only -- nothing is rendered) so the user gets a clear 422; `rasterise.py`
applies the same plans at extraction time as a second line of defence.
"""

from __future__ import annotations

import io
import math
import zlib
from dataclasses import dataclass
from pathlib import Path

import pymupdf
import pypdfium2 as pdfium
from PIL import Image

from lemely.runtime.errors import LemelyError

#: The committed question paper has 16 pages; answer booklets with
#: continuation sheets reach the low 30s. Also bounds the number of page
#: images one extraction call carries.
MAX_SCAN_PAGES = 40
#: The target after any downscale. A4 at 400 DPI is 3307x4677 = 15.5 Mpx,
#: the top of what a document scanner produces; the corpus at 200 DPI is
#: 1655x2339 = 3.87 Mpx.
MAX_PAGE_PX = 16_000_000
#: The reject boundary -- the crop route's existing "too big to open" number
#: (it admits a 600 dpi A4 scan, ~35 Mpx, and any phone photo not in a
#: high-resolution mode), moved here so the app has ONE such number. It is
#: 2.5x the target, which is the downscale band.
MAX_DECODE_PX = 40_000_000
#: Google's documented recommendation for image/PDF inputs; keeps a rendered
#: page's image-tokenisation cost at the "medium" tier (560 tokens/page).
EXTRACTION_DPI: float = 200.0
#: The PDF header. One definition: two spellings of it once drifted between
#: the extractor and the crop route.
PDF_MAGIC = b"%PDF-"
#: Integer reductions Pillow can apply; JPEG can also decode natively at
#: 1/2, 1/4 and 1/8.
_REDUCE_FACTORS = (1, 2, 4, 8)
#: Task 11b. The decoded size of one page's content streams plus every Form
#: XObject reachable from the page, each xref counted once. The committed
#: fixture's largest page content is 47 bytes (a scanned page is
#: ``q ... cm /Im0 Do Q``); a dense born-digital vector page runs 20-100 KB.
#: pdfium's parse footprint measured ~20x the decoded content (112 MB ->
#: 2,251 MB), so 8 MB caps a page's parse near 160 MB inside the 1 GiB worker.
MAX_PAGE_CONTENT_BYTES = 8_000_000
#: The sum of the per-page totals over the scan: pages render one at a time,
#: so this bounds cumulative parse time (~28 MB/s measured) and guards against
#: parsed pages kept alive across the loop.
MAX_SCAN_CONTENT_BYTES = 64_000_000
#: Bounded inflate step: the most decoded content held at once.
_INFLATE_CHUNK = 1 << 20
#: Rev 2: an image XObject's declared pixels, read from its dictionary. Reuses
#: MAX_DECODE_PX (40 Mpx): a 600 dpi A4 scan is ~35 Mpx and passes.
_IMAGE_TOO_LARGE_MESSAGE = (
    "Page {page} of this PDF contains an image of about {mpx} megapixels, which is "
    "too large to process safely. Rescan at 600 dpi or lower."
)
#: The message when the scan cap, not the page cap, is what bit.
_WHOLE_SCAN_MESSAGE = (
    "This PDF's pages contain far more drawing data than a scanned paper can "
    f"(over {MAX_SCAN_CONTENT_BYTES // 1_000_000} MB across the whole scan). "
    "Re-export it as a plain scan."
)


class ScanRejectedError(LemelyError):
    """A scan this service will not render; the message says why and what to do."""


class ScanTooLargeError(ScanRejectedError):
    """A scan's declared geometry or content is beyond what extraction will render."""


class ScanUnsupportedEncodingError(ScanRejectedError):
    """A page content stream uses an encoding whose decoded size cannot be bounded."""


@dataclass(frozen=True)
class PagePlan:
    """How to render one PDF page: at ``dpi`` (never above the requested DPI)."""

    index: int
    dpi: float


def looks_like_pdf(data: bytes) -> bool:
    """True when *data* starts with the PDF magic bytes."""
    return data.startswith(PDF_MAGIC)


def plan_page_dpi(
    width_pt: float, height_pt: float, *, dpi: float = EXTRACTION_DPI, index: int = 0
) -> float:
    """The DPI a ``width_pt`` x ``height_pt`` page renders at under the limits.

    Up to the target: ``dpi``. Within the band: ``floor(dpi * sqrt(MAX_PAGE_PX
    / px))`` -- the crop route's own formula. Beyond: :class:`ScanTooLargeError`.
    """
    px = width_pt * height_pt * (dpi / 72.0) ** 2
    if px <= MAX_PAGE_PX:
        return dpi
    if px <= MAX_DECODE_PX:
        return float(math.floor(dpi * math.sqrt(MAX_PAGE_PX / px)))
    raise ScanTooLargeError(
        f"Page {index + 1} of this scan is too large to process "
        f"(limit {MAX_DECODE_PX // 1_000_000} megapixels). Rescan at a lower resolution."
    )


def plan_pdf_pages(pdf: pdfium.PdfDocument, *, dpi: float = EXTRACTION_DPI) -> list[PagePlan]:
    """One :class:`PagePlan` per page, computed from page sizes alone.

    The page cap is checked first, so an over-long document is refused before
    a single page is looked at, let alone rendered. Reads each page's size via
    :meth:`~pypdfium2.PdfDocument.get_page_size` rather than indexing into the
    document (``pdf[index].get_size()``) -- the latter loads the full page
    object, which :func:`~lemely.io.rasterise.rasterise_pdf_to_pages` then
    loads a second time to render it; this way a page is loaded at most once.
    """
    count = len(pdf)
    if count > MAX_SCAN_PAGES:
        raise ScanTooLargeError(f"The scan has {count} pages; the limit is {MAX_SCAN_PAGES}.")
    plans: list[PagePlan] = []
    for index in range(count):
        width_pt, height_pt = pdf.get_page_size(index)
        plans.append(
            PagePlan(index=index, dpi=plan_page_dpi(width_pt, height_pt, dpi=dpi, index=index))
        )
    return plans


def plan_image(width: int, height: int) -> int:
    """The integer reduce factor that brings ``width`` x ``height`` under the target.

    ``1`` when the image already fits; :class:`ScanTooLargeError` beyond
    :data:`MAX_DECODE_PX`.
    """
    px = width * height
    if px > MAX_DECODE_PX:
        raise ScanTooLargeError(
            f"This scan is too large to process (limit {MAX_DECODE_PX // 1_000_000} "
            "megapixels). Rescan at a lower resolution."
        )
    for factor in _REDUCE_FACTORS:
        if px / (factor * factor) <= MAX_PAGE_PX:
            return factor
    return _REDUCE_FACTORS[-1]  # pragma: no cover -- 40 Mpx / 64 is always under the target


def _bounded_inflate_size(raw: bytes, *, budget: int, page_index: int) -> int:
    """The decoded length of a Flate stream, or ``ScanTooLargeError`` past ``budget``.

    Never holds more than :data:`_INFLATE_CHUNK` of decoded bytes: the 112 MB
    bomb is refused after 8 MB in ~12 ms. A corrupt or truncated stream
    (``zlib.error``) counts what it yielded -- pdfium renders what it can of
    such a stream, so the cap measures the same thing.
    """
    decompressor = zlib.decompressobj()
    size = 0
    data = raw
    try:
        while data:
            size += len(decompressor.decompress(data, _INFLATE_CHUNK))
            if size > budget:
                raise ScanTooLargeError(
                    f"Page {page_index + 1} of this PDF contains far more drawing data than a "
                    f"scanned page can (over {MAX_PAGE_CONTENT_BYTES // 1_000_000} MB once "
                    "decompressed). Re-export it as a plain scan."
                )
            data = decompressor.unconsumed_tail
            if decompressor.eof:
                break
    except zlib.error:
        return size
    return size


def decoded_stream_size(doc: pymupdf.Document, xref: int, *, budget: int, page_index: int) -> int:
    """The decoded size of stream ``xref``, measured without decoding it wholesale.

    An unfiltered stream is its raw length. A single ``/FlateDecode`` is
    inflated in bounded chunks. Anything else -- ``/LZWDecode``,
    ``/ASCII85Decode``, a filter array, ``/Crypt`` -- cannot be bounded
    without a full decode and is refused: every mainstream producer writes
    Flate content streams, so this costs nothing real and closes the
    obvious evasion.
    """
    raw = doc.xref_stream_raw(xref)
    kind, value = doc.xref_get_key(xref, "Filter")
    if kind == "null":
        size = len(raw)
        if size > budget:
            raise ScanTooLargeError(
                f"Page {page_index + 1} of this PDF contains far more drawing data than a "
                f"scanned page can (over {MAX_PAGE_CONTENT_BYTES // 1_000_000} MB). "
                "Re-export it as a plain scan."
            )
        return size
    if kind == "name" and value == "/FlateDecode":
        return _bounded_inflate_size(raw, budget=budget, page_index=page_index)
    raise ScanUnsupportedEncodingError(
        f"Page {page_index + 1} of this PDF uses a content encoding ({value}) this service "
        "cannot measure safely; re-export the PDF with standard (Flate) compression."
    )


def check_pdf_content(doc: pymupdf.Document) -> None:
    """Refuse a document whose page content would blow the render (Task 11b).

    Per page: every content stream (``page.get_contents()`` flattens a
    ``/Contents`` array) plus every Form XObject reachable from the page
    (``page.get_xobjects()`` already walks nested XObjects and reports each
    with its invoker; the same xref reachable under two names is counted
    once). The per-page total is capped at :data:`MAX_PAGE_CONTENT_BYTES`,
    the sum over pages at :data:`MAX_SCAN_CONTENT_BYTES`. Image XObjects are
    not content and their streams are never read; instead (rev 2) each
    image's DECLARED ``/Width x /Height`` -- ``page.get_images(full=True)``
    reads the dictionary only and lists images referenced from Form XObjects
    too -- is checked against :data:`MAX_DECODE_PX`, because pdfium decodes
    an image at its declared size to render it. An encrypted document is
    left alone: its streams cannot be read, and extraction fails on it later
    as today.
    """
    if doc.needs_pass:
        return
    scan_total = 0
    for page_index in range(doc.page_count):
        page = doc.load_page(page_index)
        for image in page.get_images(full=True):
            width, height = int(image[2]), int(image[3])
            if width * height > MAX_DECODE_PX:
                raise ScanTooLargeError(
                    _IMAGE_TOO_LARGE_MESSAGE.format(
                        page=page_index + 1, mpx=width * height // 1_000_000
                    )
                )
        xrefs: list[int] = list(page.get_contents())
        seen = set(xrefs)
        for xobject in page.get_xobjects():
            xref = int(xobject[0])
            if xref in seen:
                continue
            seen.add(xref)
            if doc.xref_get_key(xref, "Subtype") == ("name", "/Form"):
                xrefs.append(xref)
        page_total = 0
        for xref in xrefs:
            page_budget = MAX_PAGE_CONTENT_BYTES - page_total
            scan_budget = MAX_SCAN_CONTENT_BYTES - scan_total - page_total
            try:
                page_total += decoded_stream_size(
                    doc, xref, budget=min(page_budget, scan_budget), page_index=page_index
                )
            except ScanTooLargeError:
                if scan_budget < page_budget:
                    # The scan cap bit, not the page cap: say so.
                    raise ScanTooLargeError(_WHOLE_SCAN_MESSAGE) from None
                raise
        scan_total += page_total


def check_pdf_content_bytes(data: bytes) -> None:
    """:func:`check_pdf_content` on an in-memory PDF; bytes pymupdf cannot open pass."""
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")  # type: ignore[no-untyped-call]
    except Exception:  # noqa: BLE001 -- unparseable is "not our call"; extraction decides later
        return
    try:
        check_pdf_content(doc)
    except ScanRejectedError:
        raise
    except Exception:  # noqa: BLE001 -- a malformed page tree: same rule as the geometry check
        return
    finally:
        doc.close()


def check_pdf_content_path(path: Path) -> None:
    """:func:`check_pdf_content` on a file; the extraction and CLI entry point."""
    try:
        doc = pymupdf.open(str(path))  # type: ignore[no-untyped-call]
    except Exception:  # noqa: BLE001 -- same rule as check_pdf_content_bytes
        return
    try:
        check_pdf_content(doc)
    except ScanRejectedError:
        raise
    except Exception:  # noqa: BLE001
        return
    finally:
        doc.close()


def check_scan_bytes(data: bytes) -> None:
    """The upload-time check: page sizes and image headers only, nothing rendered.

    Bytes that neither pypdfium2 nor Pillow can open are NOT rejected here --
    extraction fails on them later, exactly as it does today -- so the only
    422 this produces is a measured, over-limit geometry (or Pillow's
    decompression-bomb guard, which fires on the declared size before any
    pixel is decoded). A document that opens but has a page that does not
    (a malformed ``/Kids`` entry, a ``/Count`` past the real page array) is
    the same case: ``plan_pdf_pages`` can raise pypdfium2's own
    ``PdfiumError`` reading such a page's size, and that is not our call to
    make either -- extraction fails on it later exactly as it does today.
    And, for a PDF, the decoded size of each page's content streams (Task
    11b) -- read from the raw streams with a bounded inflate, never rendered.
    """
    if looks_like_pdf(data):
        try:
            pdf = pdfium.PdfDocument(data)
        except Exception:
            return
        try:
            plan_pdf_pages(pdf)
        except ScanTooLargeError:
            raise
        except Exception:
            return
        finally:
            pdf.close()
        check_pdf_content_bytes(data)  # Task 11b: geometry first, then content
        return
    try:
        with Image.open(io.BytesIO(data)) as opened:
            plan_image(opened.width, opened.height)
    except Image.DecompressionBombError as exc:
        raise ScanTooLargeError(
            "This scan's image is too large to process safely. Rescan at a lower resolution."
        ) from exc
    except ScanTooLargeError:
        raise
    except Exception:
        return
