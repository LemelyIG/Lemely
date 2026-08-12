"""Parent portal (read-only) endpoints — P3.6 chunk A.

Serves ``docs/LEMELY_UI_SPEC.md`` §4.8's four parent screens: P-01 (children
list), P-02 (child overview), P-03 (child subject detail), P-04 (child
weaknesses). Every route is read-only (UI spec §4.8 principle 5 — "Read-only
throughout") and reuses the same core engines every other portal does:
:mod:`lemely.core.at_risk` for at-risk flags, :mod:`lemely.core.analytics`
for weakness aggregation and paper-comparison deltas,
:mod:`lemely.core.history`'s grade-bearing filter (D3.9) for every
grade/percentage/paper-count claim, and
:class:`~lemely.io.grade_boundaries.GradeBoundaryStore` for boundary
distance. Nothing here re-implements any of those.

**Authz — copies ``teacher_student_detail``'s pattern and its honesty about
what it is** (``lemely.web.routers.teacher``): :meth:`ParentLinkService.get_child`
is the single seam that decides whether the authenticated parent may see a
child's data. When it returns ``None``, this module distinguishes "child
exists but isn't linked to this parent" (403) from "no such user at all"
(404) via :meth:`~lemely.db.class_repo.ClassService.user_exists` — reused
rather than re-implemented as a second method on :class:`ParentLinkService`,
since it already does exactly this and does it generically (any user id, not
student-specific). Its docstring still says "staff caller"; a parent caller
now reaches it too, but the one-bit contract it documents is unchanged, so
that wording was left as-is rather than edited for a caller this chunk adds
(flagged in the P3.6a delivery notes for whoever next touches it).

Note honestly what the 403-vs-404 split *is*: a user-existence oracle. An
authenticated parent caller who probes an id learns whether it belongs to a
real user, even when they may not see that user's data. This is the same
accepted trade ``teacher_student_detail`` documents — ids are random 122-bit
UUIDs, so enumerating them is infeasible rather than merely discouraged. No
child *data* crosses the parent-link boundary either way. A malformed
(non-UUID) ``child_id`` is a clean 422, never a 500 — :func:`ParentLinkService
._as_uuid`'s ``ValueError`` is caught at every route.

**Omitted from the wire on purpose (say so, never stub):** the UI spec's
P-04 "constructive framing on what the child is doing about it (practice
generated, sessions planned)" has no real data source reachable from a
*parent-viewed* child — the study-plan/quiz-generation machinery is keyed by
the authenticated caller, never by a caller-supplied child id, so there is
nothing to honestly attach here without new plumbing outside this chunk's
scope. See ``lemely.web.schemas_parent.ChildWeaknessesDTO``'s docstring.
Acknowledgement state (D3.5) is likewise never surfaced here — it is
teacher-facing only, and parents were never in D3.5's scope.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, HTTPException

from lemely.core.analytics import aggregate_weaknesses_from_history, compare_performance
from lemely.core.at_risk import (
    AtRiskAssessment,
    BelowTargetEvidence,
    DecliningTrendEvidence,
    InactivityEvidence,
    assess_at_risk,
)
from lemely.core.history import (
    GRADE_ORDER,
    HistoryStoreProtocol,
    StudentHistory,
    grade_bearing,
    is_paper,
)
from lemely.db.class_repo import ClassService
from lemely.db.models.enums import Role
from lemely.db.parent_repo import ChildRow, ParentLinkService
from lemely.db.student_profile_repo import StudentProfileService
from lemely.io.det.profiles import get_profile
from lemely.io.grade_boundaries import GradeBoundaryStore
from lemely.web.deps import (
    AuthContext,
    get_class_service,
    get_history_store,
    get_parent_link_service,
    get_student_profile_service,
    require_role,
)
from lemely.web.schemas_parent import (
    ChildActivityDTO,
    ChildClassDTO,
    ChildListDTO,
    ChildOverviewDTO,
    ChildSummaryDTO,
    ChildWeaknessesDTO,
    GradeBoundaryDistanceDTO,
    ParentAtRiskFlagDTO,
    RecentPaperDTO,
    SubjectDetailDTO,
    SubjectOverviewDTO,
    SubjectPaperDTO,
    SubjectTrendPointDTO,
    WeakTopicDTO,
)

if TYPE_CHECKING:
    from lemely.core.at_risk import AtRiskFlag
    from lemely.core.history import HistoryStoreProtocol, PaperRecord
    from lemely.core.schemas import WeakArea

router = APIRouter(prefix="/api/parent", dependencies=[Depends(require_role(Role.parent))])


# ---------------------------------------------------------------------------
# Authz.
# ---------------------------------------------------------------------------


def _authorized_child(
    parent_link_service: ParentLinkService,
    class_service: ClassService,
    auth: AuthContext,
    child_id: str,
) -> ChildRow:
    """Return the linked child, or raise the 403/404/422 this module documents."""
    try:
        child = parent_link_service.get_child(auth.user_id, child_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if child is not None:
        return child
    try:
        exists = class_service.user_exists(child_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not exists:
        raise HTTPException(status_code=404, detail=f"Unknown child: {child_id}")
    raise HTTPException(status_code=403, detail=f"Child {child_id} is not linked to this parent")


# ---------------------------------------------------------------------------
# Shared helpers.
# ---------------------------------------------------------------------------


def _subject_name(code: str) -> str:
    """Translate a subject code into its human name (UI spec §4.8 design note).

    Falls back to the raw code when :func:`get_profile` has no name for it —
    never an invented name.
    """
    return get_profile(code).name or code


def _paper_id(record: PaperRecord) -> str:
    """Human paper identity: ``"0625/32"`` (subject/paper+variant)."""
    m = record.metadata
    return f"{m.subject_code}/{m.paper_number}{m.paper_variant}"


def _parse_recorded_at(value: str) -> datetime | None:
    """Defensively parse a ``PaperRecord.recorded_at`` ISO string.

    A private per-module copy — matches the established convention (see
    ``lemely.web.routers.teacher._parse_recorded_at``'s docstring): every
    module that needs this keeps its own copy rather than importing a
    leading-underscore helper across router files.
    """
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed


def _weak_topic_dto(area: WeakArea) -> WeakTopicDTO:
    return WeakTopicDTO(
        topic=area.topic,
        lostMarks=area.lost_marks,
        maximumMarks=area.maximum_marks,
        accuracy=area.accuracy,
    )


def _ranked_weak_topics(history: StudentHistory) -> list[WeakTopicDTO]:
    """Aggregate weaknesses across *all* records (quizzes included, D3.9), worst-first.

    Reuses :func:`aggregate_weaknesses_from_history` — never a re-derived
    topic-grouping algorithm — then ranks worst-accuracy-first, since that
    function itself does not sort (unlike ``group_weak_areas``, its
    marking-time sibling).
    """
    report = aggregate_weaknesses_from_history(history)
    return [_weak_topic_dto(area) for area in sorted(report.weak_areas, key=lambda a: a.accuracy)]


def _overall_trend(history: StudentHistory) -> float | None:
    """Percentage delta of the latest grade-bearing paper vs. its own prior attempt.

    Reuses :func:`compare_performance` — the same paper-comparison notion the
    student/teacher portals already use — so this number can never disagree
    with a delta computed elsewhere from the same history. ``None`` when
    there is no grade-bearing paper, or no prior attempt of the same
    subject+paper to compare against.
    """
    papers = grade_bearing(history.records)
    if not papers:
        return None
    latest = papers[-1]
    prior_history = StudentHistory(student_id=history.student_id, records=papers[:-1])
    return compare_performance(prior_history, latest).percentage_delta


def _status_line(records: list[PaperRecord], assessment: AtRiskAssessment) -> str:
    """Compose an honest, plain-language status sentence (P-01).

    Translation only, one clause per grade-bearing subject naming its
    predicted grade, plus a neutral note when a D3.3 rule has fired. Never an
    invented judgement ("on track", "struggling") the data does not support
    (UI spec §1.4, §4.8's design note). A child with no papers gets a
    neutral, honest line instead of a fabricated one.
    """
    papers = grade_bearing(records)
    if not papers:
        return "No papers recorded yet."
    by_subject: dict[str, list[PaperRecord]] = {}
    for record in papers:
        by_subject.setdefault(record.metadata.subject_code, []).append(record)
    clauses = [
        f"{_subject_name(code)}: predicted {subject_records[-1].grade}"
        for code, subject_records in sorted(by_subject.items())
    ]
    line = "; ".join(clauses) + "."
    if assessment.is_at_risk:
        line += " At least one at-risk signal is active."
    return line


def _child_activity(history: StudentHistory, *, now: datetime) -> ChildActivityDTO:
    """This child's own activity stats (data-backed, from ``recorded_at``).

    ``totalPapers`` counts only real past papers (``is_paper``).
    ``lastActiveAt``/``daysSinceLastActivity`` read **all** records — a quiz
    is activity too (D3.9) — so this never disagrees with the at-risk
    inactivity rule reported alongside it.
    """
    if not history.records:
        return ChildActivityDTO(totalPapers=0, lastActiveAt=None, daysSinceLastActivity=None)
    last = history.records[-1]
    last_active = _parse_recorded_at(last.recorded_at)
    days_since = (now - last_active).days if last_active is not None else None
    return ChildActivityDTO(
        totalPapers=sum(1 for r in history.records if is_paper(r)),
        lastActiveAt=last.recorded_at,
        daysSinceLastActivity=days_since,
    )


def _parent_at_risk_flag_dto(flag: AtRiskFlag) -> ParentAtRiskFlagDTO:
    """Convert a core :class:`AtRiskFlag` into its parent-facing DTO.

    Evidence-key translation mirrors ``teacher.py``'s ``_at_risk_flag_dto``
    (camelCase per evidence type) but is a local, parent-only copy: this
    surface deliberately carries no ``acknowledged`` field (D3.5 is
    teacher-facing only), so it cannot share that converter without dragging
    the acknowledgement lookup along with it.
    """
    evidence = flag.evidence
    payload: dict[str, float | int | str | list[float]]
    if isinstance(evidence, DecliningTrendEvidence):
        payload = {"percentages": evidence.percentages}
    elif isinstance(evidence, BelowTargetEvidence):
        payload = {
            "targetGrade": evidence.target_grade,
            "predictedGrade": evidence.predicted_grade,
            "positionsBelow": evidence.positions_below,
        }
    elif isinstance(evidence, InactivityEvidence):
        payload = {
            "daysInactive": evidence.days_inactive,
            "lastActiveAt": evidence.last_active_at,
        }
    else:
        raise TypeError(f"Unhandled AtRiskFlag evidence type: {type(evidence)!r}")
    return ParentAtRiskFlagDTO(reason=flag.reason.value, summary=flag.summary, evidence=payload)


def _grade_boundary_distance(record: PaperRecord) -> GradeBoundaryDistanceDTO | None:
    """Distance from ``record`` to the next grade up (P-03's "3 marks from an A").

    Generalizes ``student.py``'s ``_result_header_fields`` (which only ever
    resolves the A boundary) to "the grade immediately above whichever grade
    the child is currently on". ``None`` when the child is already on the
    best grade (``A*`` — there is no grade above it) or the boundary table
    carries no threshold for the next grade up; ``marksNeeded`` is clamped to
    zero rather than going negative.
    """
    if record.grade not in GRADE_ORDER:
        return None
    idx = GRADE_ORDER.index(record.grade)
    if idx == 0:
        return None
    next_grade = GRADE_ORDER[idx - 1]
    boundaries, _ = GradeBoundaryStore().resolve(record.metadata)
    threshold_pct = boundaries.get(next_grade)
    if threshold_pct is None or record.maximum_marks <= 0:
        return None
    threshold_marks = math.ceil((threshold_pct / 100.0) * record.maximum_marks)
    marks_needed = max(threshold_marks - record.awarded_marks, 0)
    summary = (
        f"{marks_needed} marks from a {next_grade}"
        if marks_needed > 0
        else f"Already at the {next_grade} boundary"
    )
    return GradeBoundaryDistanceDTO(nextGrade=next_grade, marksNeeded=marks_needed, summary=summary)


# ---------------------------------------------------------------------------
# P-01 · Parent home / children.
# ---------------------------------------------------------------------------


@router.get("/children", response_model=ChildListDTO)
def parent_children(
    auth: Annotated[AuthContext, Depends(require_role(Role.parent))],
    parent_link_service: Annotated[ParentLinkService, Depends(get_parent_link_service)],
    class_service: Annotated[ClassService, Depends(get_class_service)],
    history_store: Annotated[HistoryStoreProtocol, Depends(get_history_store)],
    profile_service: Annotated[StudentProfileService, Depends(get_student_profile_service)],
) -> ChildListDTO:
    """Return P-01: one card per child linked to the authenticated parent.

    ``classes`` reuses :meth:`~lemely.db.class_repo.ClassService.student_classes`
    (never a second class query). ``statusLine``/``trend``/``lastActivityAt``
    are computed straight from each child's real history — see
    :func:`_status_line`/:func:`_overall_trend`. No children linked returns an
    empty list (the "explain how to link" empty state is a frontend concern).
    Target grades (P4.3/D4.5) come from one
    ``StudentProfileService.target_grades_for_many`` call across every linked
    child, not one query per child.
    """
    children = parent_link_service.linked_children(auth.user_id)
    now = datetime.now(UTC)
    targets_by_child = profile_service.target_grades_for_many(
        str(child.child_id) for child in children
    )
    rows: list[ChildSummaryDTO] = []
    for child in children:
        history = history_store.load(str(child.child_id))
        classes = class_service.student_classes(child.child_id)
        assessment = assess_at_risk(
            history, now=now, targets=targets_by_child.get(str(child.child_id))
        )
        rows.append(
            ChildSummaryDTO(
                childId=str(child.child_id),
                displayName=child.display_name,
                classes=[
                    ChildClassDTO(name=c.name, subjectCode=c.subject_code, schoolName=c.school_name)
                    for c in classes
                ],
                statusLine=_status_line(history.records, assessment),
                trend=_overall_trend(history),
                lastActivityAt=history.records[-1].recorded_at if history.records else None,
            )
        )
    return ChildListDTO(children=rows)


# ---------------------------------------------------------------------------
# P-02 · Child overview.
# ---------------------------------------------------------------------------


@router.get("/children/{child_id}", response_model=ChildOverviewDTO)
def parent_child_overview(
    child_id: str,
    auth: Annotated[AuthContext, Depends(require_role(Role.parent))],
    parent_link_service: Annotated[ParentLinkService, Depends(get_parent_link_service)],
    class_service: Annotated[ClassService, Depends(get_class_service)],
    history_store: Annotated[HistoryStoreProtocol, Depends(get_history_store)],
    profile_service: Annotated[StudentProfileService, Depends(get_student_profile_service)],
) -> ChildOverviewDTO:
    """Return P-02: per-subject grades, recent papers, weaknesses, activity, at-risk.

    Authz per :func:`_authorized_child` (403/404/422, see module docstring).
    ``target`` is always ``null`` on every subject row — see
    ``SubjectOverviewDTO``'s docstring. ``recentPapers``/subject ``trend`` are
    grade-bearing only (a paper claim, D3.9); ``weakTopics`` folds *every*
    record, quizzes included, same as every other weakness surface in this
    codebase.
    """
    child = _authorized_child(parent_link_service, class_service, auth, child_id)
    history = history_store.load(str(child.child_id))
    now = datetime.now(UTC)

    by_subject: dict[str, list[PaperRecord]] = {}
    for record in grade_bearing(history.records):
        by_subject.setdefault(record.metadata.subject_code, []).append(record)
    subjects = [
        SubjectOverviewDTO(
            subjectCode=code,
            subjectName=_subject_name(code),
            predictedGrade=subject_records[-1].grade,
            target=None,
            latestPercentage=subject_records[-1].percentage,
            paperCount=len(subject_records),
            trend=[
                SubjectTrendPointDTO(recordedAt=r.recorded_at, percentage=r.percentage)
                for r in subject_records
            ],
        )
        for code, subject_records in sorted(by_subject.items())
    ]

    recent = list(reversed(grade_bearing(history.records)))[:10]
    recent_papers = [
        RecentPaperDTO(
            paperId=_paper_id(r),
            subjectCode=r.metadata.subject_code,
            subjectName=_subject_name(r.metadata.subject_code),
            marks=f"{r.awarded_marks}/{r.maximum_marks}",
            grade=r.grade,
            recordedAt=r.recorded_at,
        )
        for r in recent
    ]

    targets = profile_service.target_grades_for(child.child_id)
    assessment = assess_at_risk(history, now=now, targets=targets)
    return ChildOverviewDTO(
        childId=str(child.child_id),
        displayName=child.display_name,
        subjects=subjects,
        recentPapers=recent_papers,
        weakTopics=_ranked_weak_topics(history),
        activity=_child_activity(history, now=now),
        atRiskFlags=[_parent_at_risk_flag_dto(flag) for flag in assessment.flags],
    )


# ---------------------------------------------------------------------------
# P-03 · Child subject detail.
# ---------------------------------------------------------------------------


@router.get("/children/{child_id}/subjects/{code}", response_model=SubjectDetailDTO)
def parent_child_subject(
    child_id: str,
    code: str,
    auth: Annotated[AuthContext, Depends(require_role(Role.parent))],
    parent_link_service: Annotated[ParentLinkService, Depends(get_parent_link_service)],
    class_service: Annotated[ClassService, Depends(get_class_service)],
    history_store: Annotated[HistoryStoreProtocol, Depends(get_history_store)],
) -> SubjectDetailDTO:
    """Return P-03: one subject in depth for a linked child.

    Authz per :func:`_authorized_child`. ``code`` is a plain string (not a
    UUID), so no 422 applies to it — an unknown/unattempted code 404s instead
    (mirrors ``student_subject``'s "no history for subject" 404). ``papers``/
    ``predictedGrade``/``boundaryDistance`` are grade-bearing only (D3.9);
    ``weakTopics`` folds every record for this subject, quiz-origin included
    (a quiz keeps its real ``subject_code``, only its paper number/variant
    are synthetic).
    """
    child = _authorized_child(parent_link_service, class_service, auth, child_id)
    history = history_store.load(str(child.child_id))

    subject_records = [r for r in history.records if r.metadata.subject_code == code]
    records = grade_bearing(subject_records)
    if not records:
        raise HTTPException(status_code=404, detail=f"No papers for subject {code}")

    papers = [
        SubjectPaperDTO(
            paperId=_paper_id(r),
            marks=f"{r.awarded_marks}/{r.maximum_marks}",
            grade=r.grade,
            recordedAt=r.recorded_at,
        )
        for r in reversed(records)
    ]
    subject_history = StudentHistory(student_id=history.student_id, records=subject_records)

    return SubjectDetailDTO(
        childId=str(child.child_id),
        subjectCode=code,
        subjectName=_subject_name(code),
        predictedGrade=records[-1].grade,
        papers=papers,
        boundaryDistance=_grade_boundary_distance(records[-1]),
        weakTopics=_ranked_weak_topics(subject_history),
    )


# ---------------------------------------------------------------------------
# P-04 · Child weaknesses.
# ---------------------------------------------------------------------------


@router.get("/children/{child_id}/weaknesses", response_model=ChildWeaknessesDTO)
def parent_child_weaknesses(
    child_id: str,
    auth: Annotated[AuthContext, Depends(require_role(Role.parent))],
    parent_link_service: Annotated[ParentLinkService, Depends(get_parent_link_service)],
    class_service: Annotated[ClassService, Depends(get_class_service)],
    history_store: Annotated[HistoryStoreProtocol, Depends(get_history_store)],
) -> ChildWeaknessesDTO:
    """Return P-04: ranked weak topics for a linked child.

    Authz per :func:`_authorized_child`. See ``ChildWeaknessesDTO``'s
    docstring for the UI-spec field deliberately omitted (constructive
    "what the child is doing about it" framing — no reachable data source).
    """
    child = _authorized_child(parent_link_service, class_service, auth, child_id)
    history = history_store.load(str(child.child_id))
    return ChildWeaknessesDTO(childId=str(child.child_id), weakTopics=_ranked_weak_topics(history))


__all__ = ["router"]
