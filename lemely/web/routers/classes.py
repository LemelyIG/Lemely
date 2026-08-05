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

from datetime import UTC, datetime
from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, HTTPException

from lemely.core.analytics import aggregate_weaknesses_from_history
from lemely.core.at_risk import assess_at_risk
from lemely.core.class_analytics import (
    EngagementStats,
    cohort_trend,
    engagement_stats,
    grade_distribution,
    per_paper_comparison,
    rank_topic_weaknesses,
    topic_student_heatmap,
)
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
    _GRADE_ORDER,
    _mean,
    _student_row,
)
from lemely.web.schemas_analytics import (
    ClassAnalyticsDTO,
    EngagementStatsDTO,
    GradeDistributionBucketDTO,
    HeatmapCellDTO,
    PaperComparisonDTO,
    TopicWeaknessDTO,
    TrendPointDTO,
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
    # "At risk" must mean the same thing here as it does on the teacher
    # overview: the D3.3 rules engine (declining trend / predicted below target
    # / inactive), NOT the shallower "latest grade is D/E/U" test. Two cards
    # both labelled "At risk" showing different numbers is a contradiction a
    # teacher would have no way to resolve. The per-row ``gradeAtRisk`` badge
    # (via ``_student_row``) is deliberately still the grade test — it is a
    # differently-named, differently-meaning signal.
    at_risk = sum(
        1 for _, history in histories if assess_at_risk(history, now=datetime.now(UTC)).flags
    )
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


def _class_analytics_dto(
    roster: list[RosterEntry], history_store: HistoryStoreProtocol
) -> ClassAnalyticsDTO:
    """Build the T-04 cohort-analytics DTO from the class's real roster (P3.3).

    Every section is computed by ``lemely.core.class_analytics``'s pure
    functions over the roster's histories — the DTO is a direct field-by-field
    mirror of those return models, so this converter cannot silently diverge
    from the analytics it wraps (the same anti-drift discipline
    ``_class_row_to_detail`` already applies to mastery/distribution).
    """
    histories = [history_store.load(str(entry.student_id)) for entry in roster]
    ranked = rank_topic_weaknesses(histories)

    return ClassAnalyticsDTO(
        topicWeaknesses=[
            TopicWeaknessDTO(
                topic=w.topic,
                lostMarks=w.lost_marks,
                maximumMarks=w.maximum_marks,
                accuracy=w.accuracy,
                studentIds=w.student_ids,
            )
            for w in ranked
        ],
        heatmap=[
            HeatmapCellDTO(topic=c.topic, studentId=c.student_id, accuracy=c.accuracy)
            for c in topic_student_heatmap(histories, ranked)
        ],
        gradeDistribution=[
            GradeDistributionBucketDTO(grade=b.grade, count=b.count)
            for b in grade_distribution(histories)
        ],
        trend=[
            TrendPointDTO(
                timestamp=p.timestamp,
                label=p.label,
                meanPercentage=p.mean_percentage,
                sampleSize=p.sample_size,
            )
            for p in cohort_trend(histories)
        ],
        paperComparison=[
            PaperComparisonDTO(
                paperId=p.paper_id,
                subjectCode=p.subject_code,
                paperNumber=p.paper_number,
                paperVariant=p.paper_variant,
                meanPercentage=p.mean_percentage,
                attemptCount=p.attempt_count,
                studentCount=p.student_count,
            )
            for p in per_paper_comparison(histories)
        ],
        engagement=_engagement_stats_dto(engagement_stats(histories, now=datetime.now(UTC))),
    )


def _engagement_stats_dto(stats: EngagementStats) -> EngagementStatsDTO:
    """Convert a core ``EngagementStats`` into its camelCase wire DTO."""
    return EngagementStatsDTO(
        submissionsLast7Days=stats.submissions_last_7_days,
        submissionsLast30Days=stats.submissions_last_30_days,
        activeStudentsLast7Days=stats.active_students_last_7_days,
        activeStudentsLast30Days=stats.active_students_last_30_days,
        neverActiveCount=stats.never_active_count,
        medianDaysSinceLastSubmission=stats.median_days_since_last_submission,
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


@router.get("/classes/{class_id}/analytics", response_model=ClassAnalyticsDTO)
def class_analytics(
    class_id: str,
    auth: Annotated[AuthContext, Depends(require_role(*_STAFF_ROLES))],
    service: Annotated[ClassService, Depends(get_class_service)],
    history_store: Annotated[HistoryStoreProtocol, Depends(get_history_store)],
) -> ClassAnalyticsDTO:
    """Return T-04 cohort analytics for one class (P3.3).

    Ranked topic weaknesses (the screen's centrepiece — "the thing that
    changes what a teacher teaches next week"), the topic x student heatmap
    restricted to those ranked topics, grade distribution over the full grade
    ladder, a performance-over-time trend, per-paper comparison, and
    engagement stats — all computed by ``lemely.core.class_analytics``'s pure
    functions over the class's real enrolled roster, never every student in
    the store.

    Authz mirrors ``get_class`` exactly: a class outside the caller's scope is
    a 403 (never a 404-vs-403 existence oracle); an id that maps to no class
    anywhere is a 404; a malformed (non-UUID) id is a clean 422, never a 500.
    """
    try:
        service.get_class(auth.user_id, auth.role, class_id)  # existence + scope check only
        roster = service.roster(auth.user_id, auth.role, class_id)
    except (ClassNotFoundError, ClassOwnershipError) as exc:
        _raise_for(exc)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _class_analytics_dto(roster, history_store)


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
