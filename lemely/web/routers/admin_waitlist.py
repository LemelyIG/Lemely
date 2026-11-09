"""Platform-admin waitlist queue: list, filter, sort, read one, set status and note, export CSV.

``platform_admin`` only (``admin_tutors.require_platform_admin``) on every route. Phone numbers
appear here and in nowhere else. Responses are ``private, no-store``.

* ``GET /api/admin/waitlist``: one page plus chip counts. Filters: ``role``, ``level``,
  ``subject``, ``board``, ``session``, ``status`` (a status or ``partial``), ``emailConfirmed``,
  ``createdFrom`` / ``createdTo`` (inclusive dates), ``q`` (email substring). ``sort`` and
  ``order`` as listed.
* ``GET /api/admin/waitlist/export.csv``: every column of the filtered set, formula-safe.
* ``GET /api/admin/waitlist/{id}`` and ``PATCH`` (status and/or note).
"""

from __future__ import annotations

import csv
import io
import uuid  # noqa: TC003 - FastAPI resolves the path parameter at runtime
from datetime import date  # noqa: TC003 - FastAPI resolves the query parameter at runtime
from typing import TYPE_CHECKING, Annotated, Final, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from lemely.core.waitlist import csv_safe, phone_for_export
from lemely.db.waitlist_repo import WaitlistFilters, WaitlistRepository
from lemely.web.deps import AuthContext  # noqa: TC001 - FastAPI resolves it at runtime
from lemely.web.routers.admin_tutors import require_platform_admin
from lemely.web.routers.waitlist import get_waitlist_repo
from lemely.web.schemas_waitlist import (
    BoardLit,
    LevelLit,
    RoleLit,
    SortLit,
    StatusFilterLit,
    WaitlistApplicantDTO,
    WaitlistCountsDTO,
    WaitlistListDTO,
    WaitlistUpdateDTO,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from lemely.db.models.waitlist import WaitlistApplicant

router = APIRouter(prefix="/api/admin/waitlist", tags=["waitlist"])

_NO_STORE: Final = {"Cache-Control": "private, no-store"}
_MAX_PAGE_SIZE: Final = 200

CSV_COLUMNS: Final = (
    "id",
    "email",
    "role",
    "status",
    "centre_name",
    "levels",
    "subjects",
    "other_subjects",
    "exam_boards",
    "exam_session",
    "phone",
    "phone_has_whatsapp",
    "email_confirmed",
    "consent_version",
    "consent_text",
    "consent_at",
    "admin_note",
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_content",
    "utm_term",
    "completed_at",
    "created_at",
    "updated_at",
)


def _filters(
    role: Annotated[RoleLit | None, Query()] = None,
    level: Annotated[LevelLit | None, Query()] = None,
    subject: Annotated[str | None, Query(max_length=40)] = None,
    board: Annotated[BoardLit | None, Query()] = None,
    session: Annotated[str | None, Query(max_length=10)] = None,
    status: Annotated[StatusFilterLit | None, Query()] = None,
    email_confirmed: Annotated[bool | None, Query(alias="emailConfirmed")] = None,
    created_from: Annotated[date | None, Query(alias="createdFrom")] = None,
    created_to: Annotated[date | None, Query(alias="createdTo")] = None,
    q: Annotated[str | None, Query(max_length=254)] = None,
) -> WaitlistFilters:
    return WaitlistFilters(
        role=role,
        level=level,
        subject=subject,
        board=board,
        session=session,
        status=status,
        email_confirmed=email_confirmed,
        created_from=created_from,
        created_to=created_to,
        q=q or None,
    )


def _dto(row: WaitlistApplicant) -> WaitlistApplicantDTO:
    return WaitlistApplicantDTO(
        id=row.id,
        email=row.email,
        role=row.role.value,
        centreName=row.centre_name,
        levels=list(row.levels),
        subjects=list(row.subjects),
        otherSubjects=list(row.other_subjects),
        examBoards=list(row.exam_boards),
        examSession=row.exam_session,
        phone=row.phone,
        phoneHasWhatsapp=row.phone_has_whatsapp,
        emailConfirmed=row.email_confirmed,
        consentVersion=row.consent_version,
        consentText=row.consent_text,
        consentAt=row.consent_at,
        status=row.status.value,
        adminNote=row.admin_note,
        utmSource=row.utm_source,
        utmMedium=row.utm_medium,
        utmCampaign=row.utm_campaign,
        utmContent=row.utm_content,
        utmTerm=row.utm_term,
        completedAt=row.completed_at,
        partial=row.completed_at is None,
        createdAt=row.created_at,
        updatedAt=row.updated_at,
    )


@router.get("", response_model=WaitlistListDTO)
def list_applicants(
    _auth: Annotated[AuthContext, Depends(require_platform_admin)],
    filters: Annotated[WaitlistFilters, Depends(_filters)],
    repo: Annotated[WaitlistRepository, Depends(get_waitlist_repo)],
    response: Response,
    sort: Annotated[SortLit, Query()] = "created_at",
    order: Annotated[Literal["asc", "desc"], Query()] = "desc",
    page: Annotated[int, Query(ge=1, le=100_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=_MAX_PAGE_SIZE, alias="pageSize")] = 50,
) -> WaitlistListDTO:
    """One page of the filtered queue with chip counts."""
    response.headers.update(_NO_STORE)
    rows, total = repo.list_page(
        filters, sort=sort, descending=order == "desc", page=page, page_size=page_size
    )
    return WaitlistListDTO(
        items=[_dto(row) for row in rows],
        total=total,
        page=page,
        pageSize=page_size,
        counts=WaitlistCountsDTO(**repo.counts(filters)),
    )


def _csv(rows: Sequence[WaitlistApplicant]) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n", quoting=csv.QUOTE_ALL)
    writer.writerow(CSV_COLUMNS)
    for row in rows:
        values: dict[str, object] = {
            "id": row.id,
            "email": row.email,
            "role": row.role.value,
            "status": row.status.value,
            "centre_name": row.centre_name,
            "levels": "; ".join(row.levels),
            "subjects": "; ".join(row.subjects),
            "other_subjects": "; ".join(row.other_subjects),
            "exam_boards": "; ".join(row.exam_boards),
            "exam_session": row.exam_session,
            "phone": phone_for_export(row.phone),
            "phone_has_whatsapp": "yes" if row.phone_has_whatsapp else "no",
            "email_confirmed": "yes" if row.email_confirmed else "no",
            "consent_version": row.consent_version,
            "consent_text": row.consent_text,
            "consent_at": row.consent_at.isoformat(),
            "admin_note": row.admin_note,
            "utm_source": row.utm_source,
            "utm_medium": row.utm_medium,
            "utm_campaign": row.utm_campaign,
            "utm_content": row.utm_content,
            "utm_term": row.utm_term,
            "completed_at": row.completed_at.isoformat() if row.completed_at else None,
            "created_at": row.created_at.isoformat(),
            "updated_at": row.updated_at.isoformat(),
        }
        writer.writerow([csv_safe(values[column]) for column in CSV_COLUMNS])
    return out.getvalue()


@router.get("/export.csv")
def export_csv(
    _auth: Annotated[AuthContext, Depends(require_platform_admin)],
    filters: Annotated[WaitlistFilters, Depends(_filters)],
    repo: Annotated[WaitlistRepository, Depends(get_waitlist_repo)],
    sort: Annotated[SortLit, Query()] = "created_at",
    order: Annotated[Literal["asc", "desc"], Query()] = "desc",
) -> Response:
    """Every column of the filtered set as CSV (UTF-8 with BOM so Excel reads it right)."""
    rows = repo.export_rows(filters, sort=sort, descending=order == "desc")
    return Response(
        content="﻿" + _csv(rows),
        media_type="text/csv; charset=utf-8",
        headers={**_NO_STORE, "Content-Disposition": 'attachment; filename="waitlist.csv"'},
    )


@router.get("/{applicant_id}", response_model=WaitlistApplicantDTO)
def get_applicant(
    applicant_id: uuid.UUID,
    _auth: Annotated[AuthContext, Depends(require_platform_admin)],
    repo: Annotated[WaitlistRepository, Depends(get_waitlist_repo)],
    response: Response,
) -> WaitlistApplicantDTO:
    """One applicant, every field."""
    response.headers.update(_NO_STORE)
    row = repo.get(applicant_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Applicant not found")
    return _dto(row)


@router.patch("/{applicant_id}", response_model=WaitlistApplicantDTO)
def update_applicant(
    applicant_id: uuid.UUID,
    body: WaitlistUpdateDTO,
    _auth: Annotated[AuthContext, Depends(require_platform_admin)],
    repo: Annotated[WaitlistRepository, Depends(get_waitlist_repo)],
    response: Response,
) -> WaitlistApplicantDTO:
    """Set the status and/or the note (``adminNote: null`` clears it)."""
    response.headers.update(_NO_STORE)
    row = repo.update(
        applicant_id,
        status=body.status,
        admin_note=body.adminNote,
        set_note="adminNote" in body.model_fields_set,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Applicant not found")
    return _dto(row)
