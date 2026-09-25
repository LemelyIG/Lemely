"""Review queue endpoints (``/api/teacher/review/*``, T-07/T-08, P3.4).

Every route is gated to the teacher/school_admin/platform_admin staff triple
(mirroring ``teacher.py``/``classes.py``); row-level ownership is then
enforced inside :class:`~lemely.db.review_repo.ReviewService`, which scopes
every read/mutation to the caller's own visible students (the same
roster-union rule as ``teacher._visible_students``, D3.1). ``platform_admin``
sees no classes, so it sees no review items either — no super-role bypass.

A new router file rather than extending ``teacher.py`` (already ~1400 LOC):
the review queue is its own coherent surface with its own service, DTOs, and
error mapping, and nothing here needs anything ``teacher.py`` privately
defines.
"""

from __future__ import annotations

import base64
import binascii
import io
import math
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Annotated, NoReturn

import structlog
from fastapi import APIRouter, Depends, HTTPException, Response

from lemely.db.models.enums import Role
from lemely.db.review_repo import (
    CROP_ABSENT_DETAIL,
    ReviewAlreadyClosedError,
    ReviewError,
    ReviewItemDetail,
    ReviewItemPoint,
    ReviewNotFoundError,
    ReviewOwnershipError,
    ReviewQueueRow,
    ReviewService,
    ReviewValidationError,
)
from lemely.io.rasterise import RasterisedPage, looks_like_pdf
from lemely.io.reread import crop_and_upscale, padded_crop_rect
from lemely.io.storage import StorageBackend, StorageObjectNotFoundError

# A runtime import, not a TYPE_CHECKING one: FastAPI resolves
# `Annotated[Settings, Depends(get_settings)]` when the route is registered, and
# a `Settings` that only exists to the type checker makes it a required query
# parameter instead of a dependency — a 422 on every request. Suppressed here
# rather than file-wide (the blanket `TC001`/`TC002`/`TC003` ignore the sibling
# routers carry in `pyproject.toml`) so a future type-only import in this file
# still gets flagged.
from lemely.runtime.config import Settings  # noqa: TC001
from lemely.web.deps import (
    AuthContext,
    get_review_service,
    get_settings,
    get_storage_backend,
    require_role,
)
from lemely.web.schemas_review import (
    BulkApproveRequestDTO,
    BulkApproveResponseDTO,
    BulkApproveSkipDTO,
    DismissReviewRequestDTO,
    ResolveReviewRequestDTO,
    ReviewBreakdownDTO,
    ReviewItemDetailDTO,
    ReviewItemPointDTO,
    ReviewQueueItemDTO,
    ReviewQueueListDTO,
)

if TYPE_CHECKING:
    from PIL.Image import Image as PILImage

    from lemely.core.schemas import SourceBox

log = structlog.get_logger(__name__)

# Mirrors teacher.py's/classes.py's staff triple.
_STAFF_ROLES = (Role.teacher, Role.school_admin, Role.platform_admin)

router = APIRouter(
    prefix="/api/teacher/review", dependencies=[Depends(require_role(*_STAFF_ROLES))]
)


# ---------------------------------------------------------------------------
# Error mapping.
# ---------------------------------------------------------------------------


def _raise_for(exc: ReviewError) -> NoReturn:
    """Map a :class:`ReviewError` subclass to the matching :class:`HTTPException`."""
    if isinstance(exc, ReviewNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, ReviewOwnershipError):
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if isinstance(exc, ReviewAlreadyClosedError):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, ReviewValidationError):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    raise HTTPException(status_code=409, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Cursor encode/decode.
# ---------------------------------------------------------------------------

_CURSOR_SEP = "|"


def _encode_cursor(created_at: datetime, item_id: uuid.UUID) -> str:
    """Opaque keyset cursor: urlsafe-base64 of ``"<iso created_at>|<uuid>"``."""
    raw = f"{created_at.isoformat()}{_CURSOR_SEP}{item_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    """Inverse of :func:`_encode_cursor`.

    Raises ``HTTPException(422)`` on anything that does not round-trip — a
    malformed cursor is a client error, never a 500.
    """
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        created_at_str, item_id_str = raw.split(_CURSOR_SEP, 1)
        return datetime.fromisoformat(created_at_str), uuid.UUID(item_id_str)
    except (ValueError, UnicodeDecodeError, binascii.Error) as exc:
        raise HTTPException(status_code=422, detail="Malformed cursor") from exc


# ---------------------------------------------------------------------------
# DTO conversion.
# ---------------------------------------------------------------------------


def _row_to_dto(row: ReviewQueueRow) -> ReviewQueueItemDTO:
    return ReviewQueueItemDTO(
        itemId=str(row.item_id),
        source=row.source,
        attemptId=str(row.attempt_id) if row.attempt_id else None,
        paperId=str(row.paper_id) if row.paper_id else None,
        questionResultId=str(row.question_result_id) if row.question_result_id else None,
        studentId=str(row.student_id) if row.student_id else None,
        studentDisplayName=row.student_display_name,
        classId=str(row.class_id) if row.class_id else None,
        className=row.class_name,
        subjectCode=row.subject_code,
        paperNumber=row.paper_number,
        paperVariant=row.paper_variant,
        sessionMonth=row.session_month,
        sessionYear=row.session_year,
        questionId=row.question_id,
        reason=row.reason.value,
        status=row.status.value,
        createdAt=row.created_at.isoformat(),
        waitingHours=round(row.waiting_hours, 2),
        aiAwardedMarks=row.ai_awarded_marks,
        maximumMarks=row.maximum_marks,
        confidenceScore=row.confidence_score,
    )


def _breakdown_to_dto(breakdown: dict[str, object] | None) -> ReviewBreakdownDTO | None:
    if breakdown is None:
        return None
    return ReviewBreakdownDTO.model_validate(breakdown)


def _point_to_dto(point: ReviewItemPoint) -> ReviewItemPointDTO:
    return ReviewItemPointDTO(
        markPointId=point.mark_point_id,
        pointText=point.point_text,
        awarded=point.awarded,
        studentSelfmark=point.student_selfmark,
        studentEvidence=point.student_evidence,
        evidenceVerdict=point.evidence_verdict,
        verdict=point.verdict,
        evidenceSpan=point.evidence_span,
        ecfApplied=point.ecf_applied,
        rationale=point.rationale,
    )


def _detail_to_dto(detail: ReviewItemDetail) -> ReviewItemDetailDTO:
    row = detail.row
    return ReviewItemDetailDTO(
        itemId=str(row.item_id),
        source=row.source,
        attemptId=str(row.attempt_id) if row.attempt_id else None,
        paperId=str(row.paper_id) if row.paper_id else None,
        questionResultId=str(row.question_result_id) if row.question_result_id else None,
        studentId=str(row.student_id) if row.student_id else None,
        studentDisplayName=row.student_display_name,
        classId=str(row.class_id) if row.class_id else None,
        className=row.class_name,
        subjectCode=row.subject_code,
        paperNumber=row.paper_number,
        paperVariant=row.paper_variant,
        sessionMonth=row.session_month,
        sessionYear=row.session_year,
        questionId=row.question_id,
        reason=row.reason.value,
        status=row.status.value,
        createdAt=row.created_at.isoformat(),
        waitingHours=round(row.waiting_hours, 2),
        aiAwardedMarks=row.ai_awarded_marks,
        maximumMarks=row.maximum_marks,
        confidenceScore=row.confidence_score,
        studentAnswer=detail.student_answer,
        expectedAnswer=detail.expected_answer,
        topic=detail.topic,
        matchedPointIds=detail.matched_point_ids,
        feedback=detail.feedback,
        markerSource=detail.marker_source,
        reviewReason=detail.review_reason,
        isOverridden=detail.is_overridden,
        teacherAwardedMarks=detail.teacher_awarded_marks,
        teacherNote=detail.teacher_note,
        teacherBreakdown=_breakdown_to_dto(detail.teacher_breakdown),
        overriddenBy=str(detail.overridden_by) if detail.overridden_by else None,
        overriddenAt=detail.overridden_at.isoformat() if detail.overridden_at else None,
        resolutionNote=detail.resolution_note,
        resolvedBy=str(detail.resolved_by) if detail.resolved_by else None,
        resolvedAt=detail.resolved_at.isoformat() if detail.resolved_at else None,
        points=[_point_to_dto(p) for p in detail.points],
        hasSourceBox=detail.has_source_box,
    )


# ---------------------------------------------------------------------------
# Routes.
# ---------------------------------------------------------------------------


@router.get("", response_model=ReviewQueueListDTO)
def list_review_queue(
    auth: Annotated[AuthContext, Depends(require_role(*_STAFF_ROLES))],
    service: Annotated[ReviewService, Depends(get_review_service)],
    class_id: str | None = None,
    reason: str | None = None,
    min_age_hours: float | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> ReviewQueueListDTO:
    """T-07: every open review item across the caller's own students, paginated.

    Filters by class, reason, and minimum waiting age. A malformed
    (non-UUID) ``class_id`` is a clean 422, never a 500. ``limit`` (1..200,
    default 50) bounds the page size; ``cursor``, when given, continues a
    previous page (an unparseable cursor is a 422, never a 500 or a silent
    reset to page one).

    ``total`` (C3d) is the count of every item matching ``class_id``/
    ``reason``/``min_age_hours``, ignoring ``limit``/``cursor`` — computed by
    ``service.list_queue`` from the same single query that produces the page,
    so `total` can never drift from (or leak beyond) what the page itself is
    allowed to see. Cursor filtering and limit padding/slicing live entirely
    in ``ReviewService.list_queue`` (the keyset-cursor predicate is not
    re-implemented here); this route only turns its ``ReviewQueuePage`` into
    the wire DTO.
    """
    if not 1 <= limit <= 200:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 200")
    parsed_cursor = _decode_cursor(cursor) if cursor is not None else None
    try:
        result = service.list_queue(
            auth.user_id,
            auth.role,
            class_id=class_id,
            reason=reason,
            min_age_hours=min_age_hours,
            limit=limit,
            cursor=parsed_cursor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    has_more = len(result.rows) > limit
    page = result.rows[:limit]
    next_cursor = _encode_cursor(page[-1].created_at, page[-1].item_id) if has_more else None
    return ReviewQueueListDTO(
        items=[_row_to_dto(row) for row in page], nextCursor=next_cursor, total=result.total
    )


@router.get("/{item_id}", response_model=ReviewItemDetailDTO)
def get_review_item(
    item_id: str,
    auth: Annotated[AuthContext, Depends(require_role(*_STAFF_ROLES))],
    service: Annotated[ReviewService, Depends(get_review_service)],
) -> ReviewItemDetailDTO:
    """T-08: full detail for one review item.

    An item outside the caller's scope is a 403; an id that maps to no item
    anywhere is a 404; a malformed (non-UUID) id is a clean 422 — the same
    split ``teacher_student_detail`` documents at length.
    """
    try:
        detail = service.get_item(auth.user_id, auth.role, item_id)
    except (ReviewNotFoundError, ReviewOwnershipError) as exc:
        _raise_for(exc)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _detail_to_dto(detail)


# 150 dpi, not ``get_paper_preview``'s 72. That route renders a whole A4 page
# into a 64px card strip, where 72 dpi is already sharper than the consumer;
# this one renders one region of a page for a teacher reading a student's
# handwriting at a few hundred CSS pixels. At 150 dpi a box a tenth of the page
# tall is ~175px before ``crop_and_upscale``'s 2x upscale, which is legible; at
# 72 dpi it is ~84px, which is not. Deliberately below the extractor's
# ``EXTRACTION_DPI`` of 200, which is pinned to Gemini's image-tokenisation
# tiers — a budget that has nothing to say about what a person can read, and
# one this route does not share because it renders a single page on request.
_CROP_RENDER_DPI = 150

# An area ceiling on the render, because a scan's *page geometry* is unvalidated
# and unbounded while its file size is neither large nor a useful proxy: a PDF
# well under 2KB can declare three 8000x8000pt pages, which at
# ``_CROP_RENDER_DPI`` is a ~278 megapixel image. ``PIL`` warns above
# ``Image.MAX_IMAGE_PIXELS`` and raises ``DecompressionBombError`` above twice
# it (~179 megapixels here), so that page raises; a page landing between the two
# renders instead — at gigabytes of resident memory for one request. Nothing upstream
# stops either: the student upload route checks neither content type nor page
# geometry, and extraction does not pre-empt it because ``rasterise_pdf_to_pages``
# renders the same page without complaint (pypdfium2 has no bomb ceiling), so a
# ``source_box`` is persisted for exactly the upload this route would choke on.
#
# Clamping the DPI is safe here in a way it would not be for a page-faithful
# render: ``source_box`` is normalised 0-1000, so a lower DPI lands the crop on
# exactly the same region of the page and costs resolution only, never
# correctness. 40 megapixels is ~18x an A4 page at ``_CROP_RENDER_DPI``, so no
# real scan is ever clamped.
_MAX_RENDER_PX = 40_000_000


def _render_dpi_for(width_pt: float, height_pt: float) -> int | None:
    """The DPI to render a ``width_pt`` x ``height_pt`` page at, area-bounded.

    ``None`` when the page cannot be rendered within :data:`_MAX_RENDER_PX` at
    all — reachable, since a PDF may declare a 500,000pt page, which exceeds the
    ceiling even at 1 dpi. The caller answers 422 for that rather than rendering
    something it has already decided is too large.
    """
    inches = (width_pt / 72.0) * (height_pt / 72.0)
    if inches <= 0:
        # A degenerate page is not a scale problem; let the renderer speak.
        return _CROP_RENDER_DPI
    # pixels = inches * dpi**2, so the largest usable dpi is sqrt(ceiling/inches).
    # Truncated, never rounded: rounding up would put the render over the ceiling
    # this function exists to hold.
    dpi = int(math.sqrt(_MAX_RENDER_PX / inches))
    if dpi < 1:
        return None
    return min(_CROP_RENDER_DPI, dpi)


def _require_renderable_box(box: SourceBox, *, item_id: str) -> None:
    """Re-check a box read back from columns before any pixel arithmetic runs.

    :class:`~lemely.core.schemas.SourceBox`'s validator runs at construction
    only — ``model_copy``/``model_construct`` do not re-run it — so a box that
    reached this route through a copy, or out of columns written before
    ``ck_question_results_source_box_positive_area`` existed, is not guaranteed
    sane. ``PIL.Image.crop`` does not raise on an inverted or zero-area
    rectangle: it returns an empty or garbage image. That would render as a
    blank crop beside a real student's answer, the one outcome
    ``CorrectedQuestion.source_box`` forbids ("absence must render as absence,
    never as a failed crop"). So the bounds and the area are checked here and
    the route fails closed, rather than inferring either from what came out.
    """
    ymin, xmin, ymax, xmax = box.box
    # ``page`` first, and not folded into the route's ``>= doc.page_count``
    # bound: ``SourceBox.page``'s ``ge=0`` is validator-only too, that bound does
    # not exclude a negative, and ``doc.load_page(-1)`` does not raise — it
    # returns the LAST page. So an unvalidated ``page=-1`` served the wrong
    # region of the wrong page with a 200 and every appearance of success, which
    # is worse than any of the coordinate cases below.
    if box.page < 0 or not (0 <= ymin < ymax <= 1000 and 0 <= xmin < xmax <= 1000):
        log.warning("review_crop_box_unusable", item_id=item_id, page=box.page, box=box.box)
        raise HTTPException(status_code=422, detail="Stored crop region is not renderable")


def _require_page_in_range(box: SourceBox, page_count: int, *, item_id: str) -> None:
    """Refuse a box naming a page the scan does not have, before anything is rendered.

    A box captured against a different render of this upload, or against the
    upload it replaced, must cost a bounds check rather than a page render.
    Covers the zero-page document too, since ``box.page`` is non-negative.
    """
    if box.page >= page_count:
        log.warning(
            "review_crop_page_out_of_range",
            item_id=item_id,
            page=box.page,
            page_count=page_count,
        )
        raise HTTPException(
            status_code=422,
            detail=f"Stored crop region names page {box.page + 1} of a {page_count}-page scan",
        )


# The whole of an image that is already the padded region: handed to
# ``crop_and_upscale`` with no padding, it only upscales and encodes.
_WHOLE_REGION = [0, 0, 1000, 1000]

_EXIF_ORIENTATION_TAG = 0x0112


def _upright(region: PILImage, orientation: object) -> PILImage:
    """Turn a region cut from a photo's stored frame the way its EXIF flag says.

    The EXIF table, as Pillow's ``ImageOps.exif_transpose`` applies it. That
    function works on a whole image carrying its EXIF block; this region is a
    crop that carries none, so the table is applied directly. Rotating the crop
    after cutting it from the stored frame shows the same pixels as cutting the
    matching rectangle from the upright photo.
    """
    from PIL import Image

    method = {
        2: Image.Transpose.FLIP_LEFT_RIGHT,
        3: Image.Transpose.ROTATE_180,
        4: Image.Transpose.FLIP_TOP_BOTTOM,
        5: Image.Transpose.TRANSPOSE,
        6: Image.Transpose.ROTATE_270,
        7: Image.Transpose.TRANSVERSE,
        8: Image.Transpose.ROTATE_90,
    }.get(orientation if isinstance(orientation, int) else 0)
    return region if method is None else region.transpose(method)


def _crop_pdf_scan(data: bytes, box: SourceBox, *, item_id: str) -> bytes:
    """Render the page ``box`` names and crop ``box`` out of it."""
    import pymupdf

    # PyMuPDF's `open` is an untyped alias for `Document`, so a strict-mode
    # call needs the ignore. Narrowed to this one code, not the module.
    with pymupdf.open(stream=data, filetype="pdf") as doc:  # type: ignore[no-untyped-call]
        _require_page_in_range(box, doc.page_count, item_id=item_id)
        page = doc.load_page(box.page)
        dpi = _render_dpi_for(page.rect.width, page.rect.height)
        if dpi is None:
            log.warning(
                "review_crop_page_too_large",
                item_id=item_id,
                page=box.page,
                width_pt=page.rect.width,
                height_pt=page.rect.height,
            )
            raise HTTPException(status_code=422, detail="This scan's pages are too large to render")
        pixmap = page.get_pixmap(dpi=dpi)
        png: bytes = pixmap.tobytes("png")
        page_width, page_height = pixmap.width, pixmap.height

    # ``crop_and_upscale`` owns the 0-1000-to-pixel arithmetic, the 8% padding
    # and the degenerate-rounding case. Handed a fresh list, so nothing
    # downstream can rescale the box this request was given in place.
    return crop_and_upscale(
        RasterisedPage(index=box.page, width=page_width, height=page_height, png_bytes=png),
        list(box.box),
    )


def _crop_image_scan(data: bytes, box: SourceBox, *, item_id: str) -> bytes:
    """Crop ``box`` out of a non-PDF scan, in the pixel grid extraction boxed.

    Extraction decodes an image upload with PIL and does not apply EXIF
    orientation (``rasterise._rasterise_single_image``), so ``box`` is in the
    photo's stored frame. This decodes with PIL too, and crops there. MuPDF,
    which rendered images here before, applies the orientation first, so a
    phone photo stored sideways was cropped in the wrong place.

    The crop is then turned upright by the EXIF flag, so the teacher reads it
    the right way up. A single image has one page, as it does for extraction.
    """
    from PIL import Image

    with Image.open(io.BytesIO(data)) as opened:
        _require_page_in_range(box, 1, item_id=item_id)
        rect = padded_crop_rect(opened.width, opened.height, list(box.box))
        orientation = opened.getexif().get(_EXIF_ORIENTATION_TAG)
        region = _upright(opened.crop(rect).convert("RGB"), orientation)
    buf = io.BytesIO()
    region.save(buf, format="PNG")
    return crop_and_upscale(
        RasterisedPage(
            index=box.page, width=region.width, height=region.height, png_bytes=buf.getvalue()
        ),
        list(_WHOLE_REGION),
        padding_frac=0.0,
    )


@router.get(
    "/{item_id}/crop",
    responses={200: {"content": {"image/png": {}}, "description": "The boxed region of the scan"}},
)
def get_review_item_crop(
    item_id: str,
    auth: Annotated[AuthContext, Depends(require_role(*_STAFF_ROLES))],
    settings: Annotated[Settings, Depends(get_settings)],
    service: Annotated[ReviewService, Depends(get_review_service)],
    storage: Annotated[StorageBackend, Depends(get_storage_backend)],
) -> Response:
    """Render the region of the student's scan this question's answer was read from.

    Question-level, not per mark point: marking is text-only, so the marker
    never sees the page and cannot attribute a region to one mark point. This
    answers "where did this answer come from".

    A ``def`` route, not ``async def``: FastAPI runs a synchronous handler in
    its own worker thread, so the blocking ``storage.download`` needs no
    explicit ``anyio.to_thread`` wrap — the same reasoning ``get_paper_preview``
    records.

    Authorization comes from :meth:`ReviewService.get_item_crop_source`, which
    applies the review item's own visibility rule. This route does not resolve
    ownership itself, and must not learn to: an image endpoint that resolves
    its own is where IDOR gets written, because it reads as "just serve bytes".

    Every "there is no image here" — no such item, a console item, no upload, no
    box, or a stored object that has expired — answers with the same 404 and the
    same body, so the response cannot be used to probe which students have scans
    on file. The distinguishable reason is logged server-side instead.
    """
    try:
        object_path, box = service.get_item_crop_source(auth.user_id, auth.role, item_id)
    except ReviewError as exc:
        _raise_for(exc)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # One spelling of the id in everything this request emits. The lookup logs the
    # canonical form; logging the caller's raw path string here as well would make
    # a single request carry two spellings of one id, for no reason other than that
    # nobody normalised it -- and a reader joining the two lines pays for that.
    # `uuid.UUID` cannot raise: the lookup above already parsed this same value.
    logged_id = str(uuid.UUID(item_id))

    _require_renderable_box(box, item_id=logged_id)

    try:
        data = storage.download(settings.storage.bucket, object_path)
    except StorageObjectNotFoundError:
        # A stored scan is not forever (GCS lifecycle, a cleared dev
        # filesystem). 404 with the same body as every other absence; the
        # reason is here in the log, where "the object expired" and "this item
        # never had a box" need different operational responses.
        log.warning("review_crop_object_missing", item_id=logged_id, object_path=object_path)
        # Canonicalised (see `logged_id`) so this body is byte-identical to the
        # one the lookup's own absences produce, whatever spelling of the id the
        # caller sent — a difference there would be the oracle this collapse
        # exists to close.
        raise HTTPException(
            status_code=404, detail=CROP_ABSENT_DETAIL.format(item_id=logged_id)
        ) from None

    try:
        # Sniffed from the bytes, not from ``uploads.content_type``, the same
        # way ``rasterise_scan_to_pages`` dispatches, and through the same
        # ``looks_like_pdf``. Anything that is not a PDF is decoded the way
        # extraction decoded it (see ``_crop_image_scan``).
        #
        # Inside this ``try``: everything PIL does is PIL raising, and
        # ``Image.open`` enforces its own ``MAX_IMAGE_PIXELS`` ceiling. Left
        # outside, a page large enough to trip it escaped as a 500 instead of
        # the 422 every other unrenderable scan gets.
        if looks_like_pdf(data):
            crop = _crop_pdf_scan(data, box, item_id=logged_id)
        else:
            crop = _crop_image_scan(data, box, item_id=logged_id)
    except HTTPException:
        raise
    except Exception as exc:
        # A scan that cannot be rendered is not a server fault — it is a stored
        # file that is not the document type it claimed to be, or one whose page
        # geometry no renderer will accept.
        log.warning("review_crop_render_failed", item_id=logged_id, error=str(exc))
        raise HTTPException(status_code=422, detail=f"Could not render this scan: {exc}") from exc

    # Immutable for the lifetime of the item id: the stored scan never changes
    # once uploaded and the box is written once, so the crop is cacheable for
    # the same reason the console's page-1 thumbnail is.
    return Response(
        content=crop,
        media_type="image/png",
        headers={"Cache-Control": "private, max-age=3600"},
    )


@router.post("/bulk-approve", response_model=BulkApproveResponseDTO)
def bulk_approve_review_items(
    body: BulkApproveRequestDTO,
    auth: Annotated[AuthContext, Depends(require_role(*_STAFF_ROLES))],
    service: Annotated[ReviewService, Depends(get_review_service)],
) -> BulkApproveResponseDTO:
    """T-07 bulk-approve: accept-as-is every id in scope; skip-and-report the rest.

    A malformed (non-UUID) id anywhere in ``itemIds`` is a clean 422, never a
    500 — checked up front, before any item is touched. See
    ``ReviewService.bulk_approve``'s docstring for why the *scope* check
    (not_found/forbidden/already_closed) is skip-and-report rather than
    all-or-nothing; malformed input is a different failure mode and is
    rejected wholesale.
    """
    try:
        item_ids = [uuid.UUID(raw) for raw in body.itemIds]
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    result = service.bulk_approve(auth.user_id, auth.role, item_ids)
    return BulkApproveResponseDTO(
        approved=[str(item_id) for item_id in result.approved],
        skipped=[
            BulkApproveSkipDTO(itemId=str(skip.item_id), reason=skip.reason)
            for skip in result.skipped
        ],
    )


@router.post("/{item_id}/resolve", response_model=ReviewQueueItemDTO)
def resolve_review_item(
    item_id: str,
    body: ResolveReviewRequestDTO,
    auth: Annotated[AuthContext, Depends(require_role(*_STAFF_ROLES))],
    service: Annotated[ReviewService, Depends(get_review_service)],
) -> ReviewQueueItemDTO:
    """T-08: accept the AI mark as-is, or override it with a note to the student.

    Authz mirrors ``get_review_item``. An already-resolved/dismissed item is a
    409; an out-of-range ``overrideMarks`` (or one supplied for an item with no
    underlying question result) is a 422.
    """
    breakdown = body.breakdown.model_dump(exclude_none=True) if body.breakdown is not None else None
    try:
        row = service.resolve(
            auth.user_id,
            auth.role,
            item_id,
            override_marks=body.overrideMarks,
            breakdown=breakdown,
            note=body.note,
        )
    except (
        ReviewNotFoundError,
        ReviewOwnershipError,
        ReviewAlreadyClosedError,
        ReviewValidationError,
    ) as exc:
        _raise_for(exc)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _row_to_dto(row)


@router.post("/{item_id}/dismiss", response_model=ReviewQueueItemDTO)
def dismiss_review_item(
    item_id: str,
    body: DismissReviewRequestDTO,
    auth: Annotated[AuthContext, Depends(require_role(*_STAFF_ROLES))],
    service: Annotated[ReviewService, Depends(get_review_service)],
) -> ReviewQueueItemDTO:
    """T-08: dismiss an integrity flag. No student-visible record survives this.

    Authz mirrors ``get_review_item``. An already-resolved/dismissed item is a
    409; dismissing a non-integrity item (``low_confidence``/``manual``) is a
    422 — see ``ReviewService.dismiss``.
    """
    try:
        row = service.dismiss(auth.user_id, auth.role, item_id, note=body.note)
    except (
        ReviewNotFoundError,
        ReviewOwnershipError,
        ReviewAlreadyClosedError,
        ReviewValidationError,
    ) as exc:
        _raise_for(exc)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _row_to_dto(row)


__all__ = ["router"]
