"""Page renders of a stored scan: the paper preview and the review crop.

Pure: ``lemely.io`` only, never ``lemely.web``. The two routes that serve these
renders (``teacher.get_paper_preview`` and ``review.get_review_item_crop``) used
to carry the code; #260 moves it here so a render can run in a worker process
and the module's refusals can cross that process boundary.

Two kinds of refusal leave this module. A scan the house limits refuse
(:class:`~lemely.io.scan_limits.ScanRejectedError`, with its ``reason``) comes
out of ``open_checked_pdf``, ``open_scan_image`` and the content checks
unchanged. A scan that opens but cannot be rendered under this module's own
rules raises :class:`RenderRefused`: no pages, a page the box does not name, a
page too large for any ceiling-respecting render. Neither is an HTTP concern,
so neither knows a status code; the router maps them.
"""

from __future__ import annotations

import io
import math
from typing import TYPE_CHECKING, NamedTuple, NoReturn

from lemely.io.rasterise import RasterisedPage, looks_like_pdf, single_channel_or_rgb
from lemely.io.reread import REREAD_UPSCALE, crop_and_upscale, padded_crop_rect
from lemely.io.scan_limits import (
    check_pdf_page_content,
    decode_pixel_cap,
    open_checked_pdf,
    open_scan_image,
    open_scan_image_document,
)
from lemely.runtime.errors import LemelyError

if TYPE_CHECKING:
    import pymupdf
    from PIL.Image import Image as PILImage
    from PIL.Image import Transpose

__all__ = [
    "CROP_RENDER_DPI",
    "EXIF_ORIENTATION_TAG",
    "MAX_CROP_PX",
    "PREVIEW_LONG_EDGE_PX",
    "WHOLE_REGION",
    "PdfCropPlan",
    "RenderRefused",
    "crop_image_scan",
    "crop_pdf_scan",
    "decode_within_ceiling",
    "fitted_region",
    "pdf_crop_plan",
    "refuse_too_large",
    "render_preview_png",
    "require_page_in_range",
    "stored_frame_rect",
    "swaps_axes",
    "upright_transpose",
    "upscale_within_ceiling",
    "upscaled_png",
]


class RenderRefused(LemelyError):
    """A scan that opened but cannot be rendered under this module's rules.

    ``reason`` is a short code for the logs: ``no_pages``, ``page_out_of_range``,
    ``page_too_large`` or ``box_unusable``. ``fields`` carries the numbers worth
    logging beside it (a page's size, say). ``str()`` is the message alone,
    which is what a user is shown. All three go to ``args``, so the default
    ``BaseException.__reduce__`` rebuilds the error with its reason and fields
    when a render worker's refusal crosses its process boundary.
    """

    def __init__(self, message: str, reason: str, fields: dict[str, float] | None = None) -> None:
        super().__init__(message, reason, fields)
        self.reason = reason
        self.fields: dict[str, float] = {} if fields is None else fields

    def __str__(self) -> str:
        """The message alone, so ``detail=str(exc)`` is what a user is shown."""
        return str(self.args[0])


#: The longest edge of a paper preview, in pixels: an A4 page's long edge at 72 dpi.
PREVIEW_LONG_EDGE_PX = 842.0

# 150 dpi, not the preview's 72. The preview renders a whole A4 page into a
# 64px card strip, where 72 dpi is already sharper than the consumer;
# the crop renders one region of a page for a teacher reading a student's
# handwriting at a few hundred CSS pixels. At 150 dpi a box a tenth of the page
# tall is ~175px before ``crop_and_upscale``'s 2x upscale, which is legible; at
# 72 dpi it is ~84px, which is not. Deliberately below the extractor's
# ``EXTRACTION_DPI`` of 200, which is pinned to Gemini's image-tokenisation
# tiers — a budget that has nothing to say about what a person can read, and
# one the crop does not share because it renders a single page on request.
CROP_RENDER_DPI = 150

# A scan's size bounds nothing. A PDF well under 2KB can declare an 8000x8000pt
# page, and a PNG of a few hundred kilobytes can declare tens of megapixels.
# Nothing upstream stops either: the student upload route checks neither content
# type nor page geometry, and extraction renders or decodes the same file (so a
# ``source_box`` is persisted for it). So the crop bounds its own pixels.
#
# ``MAX_CROP_PX`` bounds the response, and for a PDF the render too: only the
# padded box is rendered (``pdf_crop_plan``), at a DPI and upscale chosen so the
# response fits. ``source_box`` is normalised 0-1000, so a lower DPI or a skipped
# upscale lands on the same region and costs resolution only. An A4 page is
# ~2.2 Mpx at 150 dpi, so it is never rendered lower, and a box keeps its 2x
# upscale until its padded area passes ~45% of the page.
MAX_CROP_PX = 4_000_000

# The image decode bound is `lemely.io.scan_limits.decode_pixel_cap` for the
# image's mode (#256): 40 Mpx for colour, 160 Mpx for a bilevel or greyscale
# scan -- one "too big to open" rule for the app, shared with upload and
# extraction (spec 2026-09-26 §6). The image is opened through
# `scan_limits.open_scan_image`, so only allowlisted formats are opened at all
# (#256 review: an ICO decodes the image it wraps inside `Image.open`).

#: The EXIF tag that says how a camera stored the frame.
EXIF_ORIENTATION_TAG = 0x0112

# The whole of an image that is already the padded region: handed to
# ``crop_and_upscale`` with no padding, it only upscales and encodes.
WHOLE_REGION = [0, 0, 1000, 1000]


def render_preview_png(data: bytes) -> bytes:
    """Page 1 of a stored scan, ``data``, as a PNG thumbnail.

    PDF or image is decided from the bytes (``looks_like_pdf``), as the crop
    and extraction decide it, never from the client-supplied content type:
    MuPDF sniffs the bytes, so PDF bytes stored as ``image/png`` used to skip
    the pre-scan and were repaired while opening (final review, item 4). A PDF
    opens through ``open_checked_pdf`` (the raw pre-scan first), an image
    through ``open_scan_image_document`` (allowlisted, and never opened as a
    PDF).

    One page is drawn, so the content check is the crop's one-page rule
    (``check_pdf_page_content``, owner decision S3, #269): page 1's content
    is bounded, and the document's pages by
    :data:`~lemely.io.scan_limits.MAX_CROP_PAGES` (200), not the whole-document
    :data:`~lemely.io.scan_limits.MAX_SCAN_PAGES` (40) that extraction
    keeps. A scan of 41-200 pages stored before the upload cap keeps its
    thumbnail. The empty-document check comes first: it reads only
    ``doc.page_count``, and names no page.

    Raises :class:`RenderRefused` (``no_pages``) for a document with no pages,
    :class:`~lemely.io.scan_limits.ScanRejectedError` for a refused scan, and
    lets every other failure propagate for the caller to deal with.
    """
    import pymupdf

    doc = open_checked_pdf(data) if looks_like_pdf(data) else open_scan_image_document(data)
    with doc:
        if doc.page_count == 0:
            raise RenderRefused("Stored scan has no pages", "no_pages")
        check_pdf_page_content(doc, 0)
        page = doc.load_page(0)  # type: ignore[no-untyped-call]
        # At most an A4 page at 72 dpi: 842px on the long edge. Sized against
        # the consumer: the card thumbnail is a ~300px-wide strip, so this is
        # still sharp on a 2x display, and every step up costs a bigger
        # payload on every card in the grid at once (96 dpi produced a 320KB
        # PNG per paper). A zoom, not `dpi=72`: MuPDF sizes an image's page
        # from the image's own DPI metadata, so a 72 dpi image drew at full
        # size -- 958 MB for a 160 Mpx bilevel scan the upload admits (final
        # review, Critical 1); bounded, 183 MB, mostly the image's decode.
        zoom = min(1.0, PREVIEW_LONG_EDGE_PX / max(page.rect.width, page.rect.height, 1.0))
        matrix = pymupdf.Matrix(zoom, zoom)  # type: ignore[no-untyped-call]
        pixmap = page.get_pixmap(matrix=matrix)
        png: bytes = pixmap.tobytes("png")
    return png


class PdfCropPlan(NamedTuple):
    """How to render one padded box out of one PDF page."""

    dpi: int
    zoom: float
    clip: pymupdf.Rect
    """In page space: exactly the padded box's pixels at ``zoom``."""
    size: tuple[int, int]
    upscale: int


def upscale_within_ceiling(pixels: int) -> int:
    """``crop_and_upscale``'s upscale when the result fits the ceiling, else none."""
    return REREAD_UPSCALE if pixels * REREAD_UPSCALE**2 <= MAX_CROP_PX else 1


def pdf_crop_plan(page_rect: pymupdf.Rect, box: list[int]) -> PdfCropPlan | None:
    """The DPI, clip and upscale that render ``box`` under :data:`MAX_CROP_PX`.

    The padded rectangle is the one ``crop_and_upscale`` would cut from a
    whole-page render at the same DPI, so rendering only that clip gives the same
    pixels. ``None`` when no DPI fits, which is reachable: a PDF may declare a
    500,000pt page. The caller refuses it.
    """
    import pymupdf

    dpi = CROP_RENDER_DPI
    while dpi >= 1:
        zoom = dpi / 72.0
        # MuPDF's own rounding of the page to pixels at this zoom, which is the
        # size of the whole-page pixmap it would render. PyMuPDF's geometry
        # constructors are untyped, hence the narrow ignores.
        matrix = pymupdf.Matrix(zoom, zoom)  # type: ignore[no-untyped-call]
        page_px = (page_rect * matrix).irect
        left, upper, right, lower = padded_crop_rect(page_px.width, page_px.height, box)
        pixels = (right - left) * (lower - upper)
        if pixels <= MAX_CROP_PX:
            clip = pymupdf.Rect(  # type: ignore[no-untyped-call]
                page_rect.x0 + left / zoom,
                page_rect.y0 + upper / zoom,
                page_rect.x0 + right / zoom,
                page_rect.y0 + lower / zoom,
            )
            return PdfCropPlan(
                dpi=dpi,
                zoom=zoom,
                clip=clip,
                size=(right - left, lower - upper),
                upscale=upscale_within_ceiling(pixels),
            )
        # Pixels scale with dpi squared. Truncated, and always at least one
        # lower, so the loop ends even when rounding keeps a step just over.
        dpi = min(dpi - 1, int(dpi * math.sqrt(MAX_CROP_PX / pixels)))
    return None


def require_page_in_range(page: int, page_count: int) -> None:
    """Refuse a box naming a page the scan does not have, before anything is rendered.

    A box captured against a different render of this upload, or against the
    upload it replaced, must cost a bounds check rather than a page render.
    Covers the zero-page document too, since ``page`` is non-negative.
    """
    if page >= page_count:
        raise RenderRefused(
            f"Stored crop region names page {page + 1} of a {page_count}-page scan",
            "page_out_of_range",
            {"page_count": page_count},
        )


def upright_transpose(orientation: object) -> Transpose | None:
    """The transpose that turns a stored frame upright for an EXIF orientation.

    The same table, and the same bare ``dict.get``, as Pillow's
    ``ImageOps.exif_transpose``, which extraction uses. There is deliberately
    no type check: a tag written as RATIONAL, FLOAT or DOUBLE parses to
    ``IFDRational(6, 1)`` or ``6.0``, which hash equal to ``6`` and so turn
    the page upright at extraction, and the crop must land in that same frame.
    Anything that is not a key (1, a missing flag, 0, 9, a BYTE-typed tag)
    gives ``None``, as ``exif_transpose`` leaves it alone. Not delegated to
    Pillow because the crop turns a region, and ``exif_transpose`` only takes
    a whole image.
    """
    from PIL import Image

    # Keyed by `object`, not `int`: the lookup takes whatever Pillow parsed.
    table: dict[object, Transpose] = {
        2: Image.Transpose.FLIP_LEFT_RIGHT,
        3: Image.Transpose.ROTATE_180,
        4: Image.Transpose.FLIP_TOP_BOTTOM,
        5: Image.Transpose.TRANSPOSE,
        6: Image.Transpose.ROTATE_270,
        7: Image.Transpose.TRANSVERSE,
        8: Image.Transpose.ROTATE_90,
    }
    return table.get(orientation)


def stored_frame_rect(
    rect: tuple[int, int, int, int], stored_size: tuple[int, int], orientation: object
) -> tuple[int, int, int, int]:
    """Where ``rect``, given in the UPRIGHT frame, lies in the STORED frame.

    ``stored_size`` is the stored frame's (width, height). Cutting this
    rectangle from the stored image and turning that crop with
    :func:`upright_transpose` gives exactly the pixels ``rect`` selects from
    ``ImageOps.exif_transpose`` of the whole image, without ever holding a
    second full-size copy. Rectangles are half-open edge coordinates, as
    ``Image.crop`` takes them.
    """
    from PIL import Image

    left, upper, right, lower = rect
    width, height = stored_size
    match upright_transpose(orientation):
        case None:
            return rect
        case Image.Transpose.FLIP_LEFT_RIGHT:
            return (width - right, upper, width - left, lower)
        case Image.Transpose.ROTATE_180:
            return (width - right, height - lower, width - left, height - upper)
        case Image.Transpose.FLIP_TOP_BOTTOM:
            return (left, height - lower, right, height - upper)
        case Image.Transpose.TRANSPOSE:
            return (upper, left, lower, right)
        case Image.Transpose.ROTATE_270:
            return (upper, height - right, lower, height - left)
        case Image.Transpose.TRANSVERSE:
            return (width - lower, height - right, width - upper, height - left)
        case _:  # ROTATE_90
            return (width - lower, left, width - upper, right)


def swaps_axes(transpose: Transpose | None) -> bool:
    """Whether turning by ``transpose`` exchanges width and height (the quarter turns)."""
    from PIL import Image

    return transpose in (
        Image.Transpose.TRANSPOSE,
        Image.Transpose.ROTATE_270,
        Image.Transpose.TRANSVERSE,
        Image.Transpose.ROTATE_90,
    )


def refuse_too_large(**size: float) -> NoReturn:
    """Refuse a scan no ceiling-respecting render can serve, carrying its size."""
    raise RenderRefused("This scan's pages are too large to render", "page_too_large", size)


def upscaled_png(png: bytes, width: int, height: int, *, page: int) -> bytes:
    """Upscale an already-cropped region within the ceiling, as PNG bytes.

    Through ``crop_and_upscale`` with the whole region and no padding, so the
    resampling and encoding stay the re-read's own.
    """
    return crop_and_upscale(
        RasterisedPage(index=page, width=width, height=height, png_bytes=png),
        list(WHOLE_REGION),
        padding_frac=0.0,
        upscale=upscale_within_ceiling(width * height),
    )


def crop_pdf_scan(data: bytes, page: int, box: list[int]) -> bytes:
    """Render only the padded ``box`` of page ``page`` of a PDF (see :func:`pdf_crop_plan`).

    Raises :class:`~lemely.io.scan_limits.ScanRejectedError` for a refused
    scan and :class:`RenderRefused` for a page the scan lacks or one too large
    to render.
    """
    import pymupdf

    # Task 9c review round 2: with a broken xref, MuPDF repairs the file while
    # opening it and parses every object stream it finds, so `open_checked_pdf`
    # bounds object streams from the raw bytes before the open.
    doc = open_checked_pdf(data)
    with doc:
        # `require_page_in_range` first: it reads only `doc.page_count`, no
        # `load_page` -- an out-of-range box must still cost a bounds check,
        # not a page load (test_crop_route_422s_for_a_page_out_of_range_without_rendering
        # booby-traps `load_page` to prove it). Then the content check for the
        # ONE page MuPDF will parse (triage F8): the whole-document walk cost
        # 35-48 ms per request against a 60-78 ms render, a bomb on some OTHER
        # page refused a crop that never touched it, and the document page cap
        # refused every crop of a scan stored before that cap existed. Uploads
        # that pre-date the upload-time check still get the render-bomb
        # protection for the page actually rendered; MAX_SCAN_PAGES (40) stays
        # with the whole-document callers (extraction, the preview). The
        # check reads the page tree, which costs time per page, so crops have
        # their own bound, MAX_CROP_PAGES (200), counted from the real tree.
        require_page_in_range(page, doc.page_count)
        check_pdf_page_content(doc, page)
        loaded = doc.load_page(page)  # type: ignore[no-untyped-call]
        # A fresh list, so nothing downstream can rescale this request's box.
        plan = pdf_crop_plan(loaded.rect, list(box))
        if plan is None:
            refuse_too_large(width_pt=loaded.rect.width, height_pt=loaded.rect.height)
        matrix = pymupdf.Matrix(plan.zoom, plan.zoom)  # type: ignore[no-untyped-call]
        pixmap = loaded.get_pixmap(matrix=matrix, clip=plan.clip)
        png: bytes = pixmap.tobytes("png")
        width, height = pixmap.width, pixmap.height
    return upscaled_png(png, width, height, page=page)


def decode_within_ceiling(opened: PILImage) -> None:
    """Keep ``opened``'s decode under its mode's ceiling, before it happens.

    ``Image.open`` has read only the header, so the size and mode are known
    and nothing is decoded yet. The ceiling is per mode (#256:
    ``scan_limits.decode_pixel_cap`` -- 40 Mpx for colour, 160 Mpx for a
    bilevel or greyscale scan that decodes to one byte per pixel, a third of
    the colour ceiling for a WebP, whose decoder costs about three times as
    much), the same rule upload and extraction apply. A JPEG can be decoded
    at 1/2, 1/4 or 1/8 scale natively (``draft``); anything else over the
    ceiling is refused (:class:`RenderRefused`, ``page_too_large``).

    Checked by ``isinstance``, not ``opened.format == "JPEG"``: a phone JPEG
    carrying a second embedded image (Android Ultra HDR's gain map, some
    iPhone exports) is reported by Pillow as ``format == "MPO"`` through
    ``MpoImageFile``, which subclasses ``JpegImageFile`` and supports the
    same ``draft`` reduced-scale decode. The format-string check refused
    exactly the high-resolution phone photos this reduced-scale path exists
    for.
    """
    from PIL import JpegImagePlugin

    width, height = opened.size
    cap = decode_pixel_cap(opened.mode, opened.format)
    if width * height <= cap:
        return
    if isinstance(opened, JpegImagePlugin.JpegImageFile):
        for scale in (2, 4, 8):
            if -(-width // scale) * -(-height // scale) <= cap:
                # Floor division here: ``draft`` picks the largest scale whose
                # result is no smaller than the size asked for.
                opened.draft(None, (width // scale, height // scale))
                break
        if opened.width * opened.height <= cap:
            return
    refuse_too_large(width_px=width, height_px=height)


def fitted_region(image: PILImage, rect: tuple[int, int, int, int]) -> PILImage:
    """``rect`` of ``image`` as RGB, scaled down if needed to fit :data:`MAX_CROP_PX`.

    A region over the ceiling is resampled straight out of ``image`` rather
    than cropped first, which would copy up to the whole decode once more.
    Either way the region reaches RGB through ``single_channel_or_rgb``, so
    a 16-bit greyscale region is scaled to 8 bits, as extraction scales it,
    never clipped to white by a bare ``convert("RGB")`` (final review,
    Important 2).
    """
    from PIL import Image

    left, upper, right, lower = rect
    width, height = right - left, lower - upper
    if width * height <= MAX_CROP_PX:
        region = image.crop(rect)
    else:
        # Floored, so the product cannot round back over the ceiling.
        scale = math.sqrt(MAX_CROP_PX / (width * height))
        fitted = (max(1, int(width * scale)), max(1, int(height * scale)))
        # PIL resamples palette and bilevel images by nearest neighbour; a
        # bilevel page goes to "L" (same size), not to a full-size RGB (#256).
        image = single_channel_or_rgb(image)
        region = image.resize(fitted, Image.Resampling.LANCZOS, box=rect, reducing_gap=3.0)
    region = single_channel_or_rgb(region)
    return region if region.mode == "RGB" else region.convert("RGB")


def crop_image_scan(data: bytes, box: list[int], *, page: int = 0) -> bytes:
    """Crop ``box`` out of a non-PDF scan, in the pixel grid extraction boxed.

    Extraction decodes an image upload with PIL and applies its EXIF
    orientation (``rasterise._rasterise_single_image``, #255), so ``box`` is
    in the UPRIGHT frame. The padded rectangle is computed in that frame,
    mapped back into the stored frame (:func:`stored_frame_rect`), cut from
    the decode there, and only that small crop is turned upright. Turning
    the whole decode first would make Pillow allocate a second full-size
    image (``in_place`` does not avoid it), doubling the peak for a phone
    photo. A single image has one page, as it does for extraction: ``page``
    is the page the stored box names, refused (``page_out_of_range``) unless
    it is 0.

    Raises :class:`~lemely.io.scan_limits.ScanRejectedError` for a format
    outside the allowlist (named from its first bytes and never opened, #256
    review) and :class:`RenderRefused` for a stale page or a decode over the
    ceiling.
    """
    opened = open_scan_image(io.BytesIO(data))
    with opened:
        require_page_in_range(page, 1)
        decode_within_ceiling(opened)
        orientation = opened.getexif().get(EXIF_ORIENTATION_TAG)
        transpose = upright_transpose(orientation)
        stored_size = opened.size
        upright_size = stored_size[::-1] if swaps_axes(transpose) else stored_size
        rect = padded_crop_rect(upright_size[0], upright_size[1], list(box))
        region = fitted_region(opened, stored_frame_rect(rect, stored_size, orientation))
    if transpose is not None:
        region = region.transpose(transpose)
    buf = io.BytesIO()
    region.save(buf, format="PNG")
    return upscaled_png(buf.getvalue(), region.width, region.height, page=page)
