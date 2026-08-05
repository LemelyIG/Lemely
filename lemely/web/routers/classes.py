"""Class model endpoints — CRUD, roster, and enrolment (``/api/classes/*``, D3.1).

Landing the real class model + row-level teacher tenancy D1.6 deferred: every
route is gated at the router level to the teacher/school_admin/platform_admin
staff triple (mirroring ``teacher.py``'s guard), and row-level ownership is
then enforced inside :class:`~lemely.db.class_repo.ClassService`, which scopes
every read/mutation to classes the caller owns (``teacher``) or administers
(``school_admin`` — read + roster management only; classes stay teacher-owned).
``platform_admin`` sees no classes, matching D1.6/D1.10's no-super-role rule.
Class-level mutations (create/update/delete) are further restricted per-route
to ``teacher`` alone.

The two former implicit-cohort endpoints (``GET /api/teacher/classes``,
``GET /api/classes/{class_id}``) keep their exact paths and response DTOs so
nothing else breaks, but now compute over the class's real enrolled roster
instead of every student with history in the store. Detail analytics
(mastery/distribution/stats/students) reuse the same helpers
``lemely.web.routers.teacher`` already defines, so the two computations are
provably consistent rather than duplicated logic that could silently drift.

The student-facing join-by-code route lives on the student router
(``lemely.web.routers.student``), not here — it is keyed off the
authenticated student's own id, never a caller-supplied one (D1.6).
"""

from __future__ import annotations

from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, HTTPException

from lemely.core.analytics import aggregate_weaknesses_from_history
from lemely.core.history import HistoryStoreProtocol, StudentHistory
from lemely.db.class_repo import (
    ClassError,
    ClassHasNoSchoolError,
    ClassNotFoundError,
    ClassOwnershipError,
    ClassRow,
    ClassService,
    RosterEntry,
    StudentNotSeatedError,
)
from lemely.db.models.enums import Role
from lemely.web.deps import AuthContext, get_class_service, get_history_store, require_role
from lemely.web.routers.teacher import (
    _AT_RISK_GRADES,
    _GRADE_ORDER,
    _mean,
    _student_row,
)
from lemely.web.schemas_classes import (
    CreateClassRequestDTO,
    EnrollStudentRequestDTO,
    RosterDTO,
    RosterEntryDTO,
    UpdateClassRequestDTO,
)
from lemely.web.schemas_teacher import (
    ClassDetailDTO,
    ClassListDTO,
    ClassSummaryDTO,
    DistributionBarDTO,
    MasteryRowDTO,
    StatCardDTO,
)

# The staff triple every class route is at least readable by; class-level
# mutations (create/update/delete) narrow this further, per-route, to teacher
# alone. Named so the long Annotated[...] signatures below stay under the
# line-length limit.
_STAFF_ROLES = (Role.teacher, Role.school_admin, Role.platform_admin)

router = APIRouter(prefix="/api", dependencies=[Depends(require_role(*_STAFF_ROLES))])


# ---------------------------------------------------------------------------
# Error mapping.
# ---------------------------------------------------------------------------


def _raise_for(exc: ClassError) -> NoReturn:
    """Map a :class:`ClassError` subclass to the matching :class:`HTTPException`.

    ``NoReturn`` tells mypy every call site's try/except always ends in a raise,
    so a handler that calls this in its ``except`` clause needs no dead
    fallback ``raise`` to satisfy "function does not always return".
    """
    if isinstance(exc, ClassNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, ClassOwnershipError):
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if isinstance(exc, (ClassHasNoSchoolError, StudentNotSeatedError)):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    raise HTTPException(status_code=409, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# DTO conversion.
# ---------------------------------------------------------------------------


def _average_for(student_ids: list[str], history_store: HistoryStoreProtocol) -> float | None:
    """Mean latest percentage across ``student_ids`` with recorded history."""
    latest_pcts = [
        history.records[-1].percentage
        for sid in student_ids
        if (history := history_store.load(sid)).records
    ]
    return _mean(latest_pcts)


def _class_row_to_summary(
    row: ClassRow, roster: list[RosterEntry], history_store: HistoryStoreProtocol
) -> ClassSummaryDTO:
    """Convert a :class:`ClassRow` + its roster into the wire summary DTO."""
    average = _average_for([str(entry.student_id) for entry in roster], history_store)
    return ClassSummaryDTO(
        id=str(row.class_id),
        label=row.name,
        studentCount=row.student_count,
        average=average,
        subjectCode=row.subject_code,
        schoolId=str(row.school_id) if row.school_id is not None else None,
        joinCode=row.join_code,
    )


def _class_row_to_detail(
    row: ClassRow, roster: list[RosterEntry], history_store: HistoryStoreProtocol
) -> ClassDetailDTO:
    """Build the full class-detail DTO from real roster data (D3.1).

    Mastery is per-topic accuracy across the *roster's* aggregate weaknesses
    (not the whole store); distribution counts roster students by latest
    grade; the roster is one row per enrolled student. National benchmarks and
    hours-saved narratives have no backend source and are omitted / left
    ``None``.
    """
    histories = [(entry, history_store.load(str(entry.student_id))) for entry in roster]
    latest = [history.records[-1] for _, history in histories if history.records]

    rows = [
        student_row
        for entry, history in histories
        if (
            student_row := _student_row(
                history, display_name=entry.display_name, student_id=str(entry.student_id)
            )
        )
        is not None
    ]

    all_records = [record for _, history in histories for record in history.records]
    aggregate = aggregate_weaknesses_from_history(
        StudentHistory(student_id=str(row.class_id), records=all_records)
    )
    mastery = [
        MasteryRowDTO(topic=area.topic, value=round(area.accuracy * 100))
        for area in aggregate.weak_areas
    ]

    grade_counts: dict[str, int] = {}
    for record in latest:
        grade_counts[record.grade] = grade_counts.get(record.grade, 0) + 1
    distribution = [DistributionBarDTO(grade=g, count=grade_counts.get(g, 0)) for g in _GRADE_ORDER]

    average = _mean([r.percentage for r in latest])
    at_risk = sum(1 for r in latest if r.grade in _AT_RISK_GRADES)
    stats = [
        StatCardDTO(
            key="Class average",
            value=str(round(average)) if average is not None else "—",
            unit="%",
            footTone="ok",
        ),
        StatCardDTO(key="Students", value=str(row.student_count), unit="tracked"),
        StatCardDTO(
            key="At risk",
            value=str(at_risk),
            unit="students",
            valueTone="err" if at_risk else "t1",
            footTone="err" if at_risk else "t2",
        ),
    ]

    return ClassDetailDTO(
        id=str(row.class_id),
        label=row.name,
        stats=stats,
        mastery=mastery,
        distribution=distribution,
        students=rows,
        subjectCode=row.subject_code,
        schoolId=str(row.school_id) if row.school_id is not None else None,
        joinCode=row.join_code,
    )


# ---------------------------------------------------------------------------
# Class list / detail (keeps the pre-P3.1 paths byte-identical).
# ---------------------------------------------------------------------------


@router.get("/teacher/classes", response_model=ClassListDTO)
def list_classes(
    auth: Annotated[AuthContext, Depends(require_role(*_STAFF_ROLES))],
    service: Annotated[ClassService, Depends(get_class_service)],
    history_store: Annotated[HistoryStoreProtocol, Depends(get_history_store)],
) -> ClassListDTO:
    """Return every class the caller may see, scoped by role (D3.1).

    ``teacher`` gets their own classes; ``school_admin`` gets classes in
    schools they administer; ``platform_admin`` always gets an empty list — no
    super-role bypass, mirroring the seat-management surface (D1.6/D1.10).
    """
    try:
        rows = service.list_classes(auth.user_id, auth.role)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    summaries = []
    for row in rows:
        roster = service.roster(auth.user_id, auth.role, row.class_id)
        summaries.append(_class_row_to_summary(row, roster, history_store))
    return ClassListDTO(classes=summaries)


@router.get("/classes/{class_id}", response_model=ClassDetailDTO)
def get_class(
    class_id: str,
    auth: Annotated[AuthContext, Depends(require_role(*_STAFF_ROLES))],
    service: Annotated[ClassService, Depends(get_class_service)],
    history_store: Annotated[HistoryStoreProtocol, Depends(get_history_store)],
) -> ClassDetailDTO:
    """Return mastery, grade distribution, and the roster for one class.

    A class outside the caller's scope is a 403 (never a 404-vs-403 existence
    oracle); an id that maps to no class anywhere is a 404. A malformed
    (non-UUID) id is a clean 422, never a 500.
    """
    try:
        row = service.get_class(auth.user_id, auth.role, class_id)
        roster = service.roster(auth.user_id, auth.role, class_id)
    except (ClassNotFoundError, ClassOwnershipError) as exc:
        _raise_for(exc)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _class_row_to_detail(row, roster, history_store)


# ---------------------------------------------------------------------------
# Class CRUD (owner-scoped: the creating teacher only).
# ---------------------------------------------------------------------------


@router.post("/classes", response_model=ClassSummaryDTO, status_code=201)
def create_class(
    body: CreateClassRequestDTO,
    auth: Annotated[AuthContext, Depends(require_role(Role.teacher))],
    service: Annotated[ClassService, Depends(get_class_service)],
    history_store: Annotated[HistoryStoreProtocol, Depends(get_history_store)],
) -> ClassSummaryDTO:
    """Create a class owned by the authenticated teacher.

    ``schoolId`` is only accepted when the caller holds a membership there
    (independent teachers omit it entirely, per MISSION §1).
    """
    try:
        row = service.create_class(
            auth.user_id, body.name, subject_code=body.subjectCode, school_id=body.schoolId
        )
    except ClassOwnershipError as exc:
        _raise_for(exc)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ClassError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _class_row_to_summary(row, [], history_store)


@router.patch("/classes/{class_id}", response_model=ClassSummaryDTO)
def update_class(
    class_id: str,
    body: UpdateClassRequestDTO,
    auth: Annotated[AuthContext, Depends(require_role(Role.teacher))],
    service: Annotated[ClassService, Depends(get_class_service)],
    history_store: Annotated[HistoryStoreProtocol, Depends(get_history_store)],
) -> ClassSummaryDTO:
    """Rename a class and/or change its subject code. Owner-scoped."""
    try:
        row = service.update_class(
            auth.user_id, class_id, name=body.name, subject_code=body.subjectCode
        )
        roster = service.roster(auth.user_id, auth.role, class_id)
    except (ClassNotFoundError, ClassOwnershipError) as exc:
        _raise_for(exc)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _class_row_to_summary(row, roster, history_store)


@router.delete("/classes/{class_id}", status_code=204)
def delete_class(
    class_id: str,
    auth: Annotated[AuthContext, Depends(require_role(Role.teacher))],
    service: Annotated[ClassService, Depends(get_class_service)],
) -> None:
    """Delete a class (cascades to its enrolments). Owner-scoped."""
    try:
        service.delete_class(auth.user_id, class_id)
    except (ClassNotFoundError, ClassOwnershipError) as exc:
        _raise_for(exc)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Roster + enrolment (teacher and school_admin — roster management, D3.1).
# ---------------------------------------------------------------------------


@router.get("/classes/{class_id}/roster", response_model=RosterDTO)
def get_roster(
    class_id: str,
    auth: Annotated[AuthContext, Depends(require_role(*_STAFF_ROLES))],
    service: Annotated[ClassService, Depends(get_class_service)],
) -> RosterDTO:
    """Return a class's enrolled students (identity only, no analytics)."""
    try:
        entries = service.roster(auth.user_id, auth.role, class_id)
    except (ClassNotFoundError, ClassOwnershipError) as exc:
        _raise_for(exc)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return RosterDTO(
        students=[
            RosterEntryDTO(studentId=str(entry.student_id), displayName=entry.display_name)
            for entry in entries
        ]
    )


@router.post("/classes/{class_id}/enroll", response_model=RosterEntryDTO)
def enroll_student(
    class_id: str,
    body: EnrollStudentRequestDTO,
    auth: Annotated[AuthContext, Depends(require_role(*_STAFF_ROLES))],
    service: Annotated[ClassService, Depends(get_class_service)],
) -> RosterEntryDTO:
    """Direct-add an existing, seated student onto the class roster. Idempotent.

    Requires the class to have a ``schoolId`` and the student to hold a
    non-revoked seat in that school (an independent teacher's class 409s here
    by construction — it has no seat pool at all).
    """
    try:
        entry = service.enroll_by_seat(auth.user_id, auth.role, class_id, body.studentId)
    except (
        ClassNotFoundError,
        ClassOwnershipError,
        ClassHasNoSchoolError,
        StudentNotSeatedError,
    ) as exc:
        _raise_for(exc)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return RosterEntryDTO(studentId=str(entry.student_id), displayName=entry.display_name)


@router.delete("/classes/{class_id}/students/{student_id}", status_code=204)
def remove_student(
    class_id: str,
    student_id: str,
    auth: Annotated[AuthContext, Depends(require_role(*_STAFF_ROLES))],
    service: Annotated[ClassService, Depends(get_class_service)],
) -> None:
    """Remove a student from a class's roster. Owner/admin-scoped, idempotent."""
    try:
        service.remove_student(auth.user_id, auth.role, class_id, student_id)
    except (ClassNotFoundError, ClassOwnershipError) as exc:
        _raise_for(exc)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
