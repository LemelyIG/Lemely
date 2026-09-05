"""Student portal (results + study) endpoints.

Router owned by the student-portal worker. Endpoints are added here without
touching ``app.py`` — the app factory already mounts this router.

**Data provenance.** Every response is computed from real core logic and the
:class:`~lemely.io.history_store.HistoryStore`: cross-paper aggregation via
:mod:`lemely.core.analytics`, grade + boundary resolution via
:mod:`lemely.io.grade_boundaries`, and integrity via
:mod:`lemely.core.plagiarism` / :mod:`lemely.io.integrity`. Study-plan
scheduling and onboarding are **not** here: they live on
:mod:`lemely.web.routers.study_plan` (``/api/student/study-plan``, persisted
per ISO week) and :mod:`lemely.web.routers.me` (``/api/me/student-profile*``)
since P4.10 chunk D retired this router's superseded ``/student/plan`` pair and
``/student/onboarding`` (D4.22).
Where a frontend field has *no* backing data source (leaderboard peers, streak
history beyond recorded-paper days, marketing copy, or the per-question detail
that history records do not persist), the response returns a typed-neutral
default (``""`` / ``0`` / ``[]``) rather than the mock's demo numbers. Each
converter docstring calls out which fields are data-backed vs structurally empty.
"""

from __future__ import annotations

import tempfile
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, TypedDict

import anyio
import structlog
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

# WeaknessReport and HistoryStoreProtocol stay as runtime imports (noqa: TC001):
# FastAPI dependency injection and the response converters resolve their
# annotations at call time, so they cannot move into a TYPE_CHECKING block.
from lemely.auth.mirror import UserMirror
from lemely.core.analytics import aggregate_weaknesses_from_history
from lemely.core.at_risk import AtRiskReason, assess_at_risk
from lemely.core.history import (
    HistoryStoreProtocol,
    PaperRecord,
    StudentHistory,
    grade_bearing,
    is_grade_bearing,
    is_paper,
)
from lemely.core.loose_schemas import MarkScheme
from lemely.core.schemas import ExamMetadata, WeaknessReport
from lemely.db.attempt_repo import AttemptRepository
from lemely.db.class_repo import ClassService, JoinCodeError
from lemely.db.models.enums import NotificationType, Role, UploadStatus, XpSource
from lemely.db.notification_repo import NotificationService
from lemely.db.parent_repo import ParentLinkService, ParentUserNotFoundError
from lemely.db.scheme_corpus_repo import SchemeCorpusRepository
from lemely.db.student_profile_repo import StudentProfileService, SubjectEnrolmentRow
from lemely.db.upload_repo import StudentUploadRepository, UploadRun
from lemely.db.xp_repo import DEFAULT_ZONE, XpService, civil_date_in_zone
from lemely.io.det.profiles import get_profile
from lemely.io.gemini import GeminiClient
from lemely.io.grade_boundaries import GradeBoundaryStore
from lemely.io.parsers import ChainedMarkSchemeParser, GeminiMarkSchemeParser
from lemely.io.scan_metadata import ScanMetadataExtractor
from lemely.io.storage import StorageBackend, StorageObjectNotFoundError
from lemely.runtime.config import Settings
from lemely.web.deps import (
    AuthContext,
    get_attempt_repo,
    get_class_service,
    get_gemini_client,
    get_history_store,
    get_notification_service,
    get_parent_link_service,
    get_push_transport,
    get_scheme_corpus_repo,
    get_settings,
    get_storage_backend,
    get_student_profile_service,
    get_student_upload_repo,
    get_user_mirror,
    get_xp_service,
    require_role,
    require_verified_email,
)
from lemely.web.notify import notify_safely

# NotificationTransport is a **runtime** import for the same reason as the two
# above: FastAPI resolves every ``Annotated[...]`` parameter through pydantic,
# and with ``from __future__ import annotations`` a type-checking-only name
# leaves an unresolvable ForwardRef that raises PydanticUserError on the
# route's *first request* rather than at import (P5.6 chunk C1).
from lemely.web.push import NotificationTransport
from lemely.web.schemas import question_to_dto
from lemely.web.schemas_classes import JoinClassRequestDTO, JoinClassResponseDTO
from lemely.web.schemas_parent import LinkedParentDTO, LinkParentRequestDTO, ParentLinkListDTO
from lemely.web.schemas_student import (
    CorrectRequest,
    IntegrityRowDTO,
    MomentumDTO,
    MomentumPointDTO,
    OverviewDTO,
    PaperBarDTO,
    PaperBreakdownDTO,
    PaperHistoryRowDTO,
    ResultDTO,
    StandingsDTO,
    StudentUploadResponse,
    SubjectDTO,
    SubjectHeaderDTO,
    SubjectRankDTO,
    SubjectRowDTO,
    TopicTileDTO,
    UploadRunDTO,
    VizColor,
    WeakThreadDTO,
)
from lemely.web.services.grading import extract_answers, grade_paper
from lemely.web.upload_utils import check_upload_cap, safe_upload_name
from lemely.web.xp_awards import award_xp_safely

router = APIRouter(prefix="/api")

log = structlog.get_logger(__name__)

#: Notification-body wording per at-risk reason (P5.6 chunk C2c, D5.11 §5).
#: Deliberately **not** ``AtRiskFlag.summary``, which renders the evidence —
#: percentages, predicted grades, a target — and is written for the teacher's
#: at-risk view where that evidence appears with its confidence intact. A
#: notification body reaches a lock screen, so it names the *reason* and sends
#: the reader to the surface that can show them the rest.
#: ``INACTIVE`` is included for completeness of the mapping even though rule 3
#: cannot fire at this seam (D5.11 §2) — a map missing a case is a KeyError
#: waiting for the day a scheduler exists.
AT_RISK_REASON_LABELS: dict[AtRiskReason, str] = {
    AtRiskReason.DECLINING_TREND: "Recent papers show a declining trend.",
    AtRiskReason.BELOW_TARGET: "Tracking below their target grade.",
    AtRiskReason.INACTIVE: "No activity recorded for a while.",
}

# ── Shared helpers ────────────────────────────────────────────────────────────


def _bar_color(pct: float) -> VizColor:
    """Map an accuracy/score percentage onto the shared viz palette."""
    if pct >= 80.0:
        return "ok"
    if pct >= 70.0:
        return "accent"
    return "warn"


def _grade_for(percentage: float, boundaries: dict[str, float]) -> str:
    """Return the highest grade whose boundary ``percentage`` clears, else ``U``."""
    for grade, threshold in sorted(boundaries.items(), key=lambda kv: kv[1], reverse=True):
        if percentage >= threshold:
            return grade
    return "U"


def _weak_threads(weaknesses: WeaknessReport, *, limit: int | None = None) -> list[WeakThreadDTO]:
    """Convert weak areas into accuracy-bar DTOs (data-backed).

    Sorted weakest-first; ``acc``/``width`` come from each area's accuracy.
    """
    areas = sorted(weaknesses.weak_areas, key=lambda a: a.accuracy)
    if limit is not None:
        areas = areas[:limit]
    threads: list[WeakThreadDTO] = []
    for area in areas:
        pct = round(area.accuracy * 100.0)
        threads.append(
            WeakThreadDTO(topic=area.topic, acc=f"{pct}%", width=pct, color=_bar_color(pct))
        )
    return threads


def _subject_records(history: StudentHistory, code: str) -> list[tuple[int, PaperRecord]]:
    """Return ``(original_index, record)`` pairs for one subject, oldest-first.

    ``original_index`` is the record's position in the FULL, unfiltered
    ``history.records`` list — the same addressing scheme
    ``GET /student/result/{paper_id}`` uses — not a position in this
    subject-filtered subset. Callers that only need the records (not the
    index) can drop the first element of each pair.
    """
    return [(i, r) for i, r in enumerate(history.records) if r.metadata.subject_code == code]


def _momentum(records: list[PaperRecord]) -> MomentumDTO:
    """Build the momentum series from recorded-paper percentages (data-backed).

    One point per grade-bearing paper, oldest first, each carrying its own
    ``recorded_at`` and its percentage exactly as recorded. Returns no points
    at all when fewer than two papers exist (a line needs at least two), which
    is the condition the frontend's empty state keys off directly.

    Filters to grade-bearing records itself rather than trusting each caller to
    do it (``docs/quiz-model.md`` §5) — this is a percentage-over-time claim,
    and one quiz scoring 40% on a hard topic would draw a dive in a line the
    student reads as "my papers are getting worse".

    **No coordinate transform lives here any more.** See :class:`MomentumDTO`
    for what this used to emit and the two defects that came with it; the short
    version is that a backend which renders SVG paths is a backend that has to
    guess the viewbox, the axis range and the clipping behaviour of a component
    it cannot see.
    """
    papers = grade_bearing(records)
    if len(papers) < 2:
        return MomentumDTO(points=[])
    return MomentumDTO(
        points=[MomentumPointDTO(recordedAt=r.recorded_at, percentage=r.percentage) for r in papers]
    )


def _subjects(
    history: StudentHistory, enrolments: dict[str, SubjectEnrolmentRow]
) -> list[SubjectRowDTO]:
    """Aggregate history into per-subject Overview rows (data-backed).

    ``pct`` is the mark-weighted mean across the subject's papers; ``trend`` is
    the percentage delta between the first and last recorded paper; ``grade``
    resolves against real boundaries. ``name`` is a real human name resolved
    via :func:`get_profile`, falling back to the raw code for a subject
    outside the three the build supports (never invented — mirrors
    ``lemely.web.routers.parent._subject_name``). ``qualificationLevel``
    comes from the student's enrolment for this subject, when one exists;
    ``None`` for a subject with recorded papers but no formal enrolment.
    ``detail`` reports the paper count only.

    Grade-bearing records only (``docs/quiz-model.md`` §5): every number on
    this row — the mark-weighted mean, the first-to-last delta, and a grade
    resolved against real CAIE boundaries — is a paper claim. A quiz total
    folded into that weighted mean would move a student's forecast grade with
    marks the boundaries were never drawn for. A subject the student has only
    quizzed produces no row, which is honest: they have no standing in it yet.
    """
    by_code: dict[str, list[PaperRecord]] = {}
    for record in grade_bearing(history.records):
        by_code.setdefault(record.metadata.subject_code, []).append(record)

    # Built after the grouping, and only when the grouping found something.
    # `GradeBoundaryStore()` reads `component_thresholds` eagerly and raises
    # `EmptyGradeBoundaryStoreError` against an un-ingested table, so building
    # it first made a student with no papers — who resolves no grade at all —
    # depend on a table their screen never reads.
    if not by_code:
        return []
    boundary_store = GradeBoundaryStore()

    rows: list[SubjectRowDTO] = []
    for code, records in sorted(by_code.items()):
        awarded = sum(r.awarded_marks for r in records)
        maximum = sum(r.maximum_marks for r in records)
        pct = round((awarded / maximum) * 100.0) if maximum else 0
        boundaries, _ = boundary_store.resolve(records[-1].metadata)
        delta = round(records[-1].percentage - records[0].percentage)
        enrolment = enrolments.get(code)
        rows.append(
            SubjectRowDTO(
                code=code,
                name=get_profile(code).name or code,
                qualificationLevel=(
                    enrolment.qualification_level.value
                    if enrolment and enrolment.qualification_level
                    else None
                ),
                detail=f"{len(records)} papers corrected",
                pct=pct,
                papers=len(records),
                trend=f"{'+' if delta >= 0 else ''}{delta}",
                grade=_grade_for(float(pct), boundaries),
                barColor=_bar_color(pct),
                trendUp=delta >= 0,
            )
        )
    return rows


# ── Overview ──────────────────────────────────────────────────────────────────


@router.get("/student/overview", response_model=OverviewDTO)
def student_overview(
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    history_store: Annotated[HistoryStoreProtocol, Depends(get_history_store)],
    mirror: Annotated[UserMirror, Depends(get_user_mirror)],
    profile_service: Annotated[StudentProfileService, Depends(get_student_profile_service)],
) -> OverviewDTO:
    """Return the student Overview: subject rows, global weak threads, momentum.

    All fields are data-backed from the caller's :class:`StudentHistory` and
    :mod:`lemely.core.analytics`. ``forecast`` is the space-joined per-subject
    predicted grades; ``weakGlobal`` is the top weak topics folded across every
    paper. ``studentName`` is the mirrored ``public.users`` row's
    ``display_name``, falling back to ``email`` (same convention as
    :func:`lemely.db.quiz_taking_repo._display_name`) rather than the raw
    ``auth.user_id`` — a student greeted by their own UUID is what this used
    to do before a name store existed. ``auth.user_id`` is a real UUID for
    every token this route ever sees in production (``require_role`` only
    admits tokens minted against the real auth service); the malformed-id
    handling below only ever fires for hermetic tests that key
    :class:`~lemely.core.history.StudentHistory` by a friendly string id, and
    falls back to the same typed-neutral defaults this router uses elsewhere
    (no enrolments, no mirrored name) rather than a 500.
    ``profile_service.list_enrolments`` internally rejects a non-UUID id with
    ``ValueError`` (:meth:`StudentProfileService._as_uuid`); that is caught
    here so a malformed id degrades to no enrolments instead of a 500.
    ``mirror.get_by_id`` needs a real :class:`uuid.UUID` object rather than
    raising on a bad one, so its guard parses ``auth.user_id`` up front and
    skips the lookup entirely when it isn't a UUID.
    """
    history = history_store.load(auth.user_id)
    try:
        enrolments = {e.subject_code: e for e in profile_service.list_enrolments(auth.user_id)}
    except ValueError:
        enrolments = {}
    subjects = _subjects(history, enrolments)
    weaknesses = aggregate_weaknesses_from_history(history)
    student_name = ""
    try:
        user_id = uuid.UUID(auth.user_id)
    except ValueError:
        user_id = None
    if user_id is not None:
        user = mirror.get_by_id(user_id)
        if user is not None:
            student_name = user.display_name or user.email
    return OverviewDTO(
        studentName=student_name,
        forecast=" ".join(row.grade for row in subjects),
        subjects=subjects,
        weakGlobal=_weak_threads(weaknesses, limit=6),
        momentum=_momentum(history.records),
    )


# ── Subject ───────────────────────────────────────────────────────────────────


@router.get("/student/subject/{code}", response_model=SubjectDTO)
def student_subject(
    code: str,
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    history_store: Annotated[HistoryStoreProtocol, Depends(get_history_store)],
    profile_service: Annotated[StudentProfileService, Depends(get_student_profile_service)],
) -> SubjectDTO:
    """Return one subject's papers breakdown, topic map, and paper history.

    Data-backed: per-paper breakdown bars (percentage per recorded paper),
    weighted mean, predicted grade + boundary, per-topic accuracy tiles, and the
    paper-history table. 404 when the student has no papers for ``code``.

    Every number here except the topic map is a paper claim, so the paper
    surfaces read grade-bearing records only (``docs/quiz-model.md`` §5) —
    otherwise a quiz would open a bogus "Paper 1" breakdown card (1/1 is the
    synthetic paper identity the marking call needed) and drag the weighted
    mean the forecast grade is resolved from. ``topicMap`` deliberately keeps
    *all* of the subject's records, quizzes included: a weakness is a weakness
    whatever revealed it, and a topic quiz is precisely the kind of evidence
    that map exists to show.
    """
    history = history_store.load(auth.user_id)
    all_subject_records = _subject_records(history, code)
    if not all_subject_records:
        raise HTTPException(status_code=404, detail=f"No history for subject {code}")
    # Index-preserving: ``_subject_records`` pairs each record with its position
    # in the FULL history list, which is how ``GET /student/result/{id}``
    # addresses it — filtering the pairs keeps those ids correct.
    indexed_records = [(i, r) for i, r in all_subject_records if is_grade_bearing(r)]
    records = [record for _, record in indexed_records]
    if not records:
        raise HTTPException(status_code=404, detail=f"No papers for subject {code}")

    boundary_store = GradeBoundaryStore()
    awarded = sum(r.awarded_marks for r in records)
    maximum = sum(r.maximum_marks for r in records)
    pct = round((awarded / maximum) * 100.0) if maximum else 0
    boundaries, _ = boundary_store.resolve(records[-1].metadata)
    delta = round(records[-1].percentage - records[0].percentage)

    # One breakdown card per distinct paper number, each bar a recorded attempt.
    by_paper: dict[int, list[PaperRecord]] = {}
    for record in records:
        by_paper.setdefault(record.metadata.paper_number, []).append(record)

    breakdowns: list[PaperBreakdownDTO] = []
    for paper_number, attempts in sorted(by_paper.items()):
        bars = [
            PaperBarDTO(
                value=round(a.percentage),
                label=f"p{i + 1}",
                highlight=i == len(attempts) - 1,
            )
            for i, a in enumerate(attempts)
        ]
        mean_pct = round(sum(a.percentage for a in attempts) / len(attempts))
        latest = attempts[-1]
        breakdowns.append(
            PaperBreakdownDTO(
                title=f"Paper {paper_number}",
                sub=f"{latest.maximum_marks} marks",
                mean=f"{mean_pct}%",
                boundary="",
                position=f"{latest.awarded_marks}/{latest.maximum_marks} - {latest.grade}",
                positionOk=latest.grade in {"A*", "A", "B"},
                bars=bars,
            )
        )

    weaknesses = _subject_weaknesses([record for _, record in all_subject_records])
    topic_map = [
        TopicTileDTO(
            name=area.topic,
            acc=f"{round(area.accuracy * 100.0)}%",
            color=_bar_color(area.accuracy * 100.0),
            weak=area.accuracy < 0.70,
        )
        for area in sorted(weaknesses.weak_areas, key=lambda a: a.accuracy)
    ]

    paper_history = [
        PaperHistoryRowDTO(
            id=str(index),
            paper=_paper_label(record),
            note="",
            marks=f"{record.awarded_marks}/{record.maximum_marks}",
            pct=f"{round(record.percentage)}%",
            grade=record.grade,
            gradeColor=_bar_color(record.percentage),
            tab=f"p{record.metadata.paper_number}",
        )
        for index, record in reversed(indexed_records)
    ]

    try:
        enrolments = profile_service.list_enrolments(auth.user_id)
    except ValueError:
        enrolments = []
    enrolment = next((e for e in enrolments if e.subject_code == code), None)
    header = SubjectHeaderDTO(
        name=get_profile(code).name or code,
        code=code,
        qualificationLevel=(
            enrolment.qualification_level.value
            if enrolment and enrolment.qualification_level
            else None
        ),
        intro=f"{len(records)} papers corrected.",
        forecast=_grade_for(float(pct), boundaries),
        weightedMean=str(pct),
        weightedMeanDelta=f"{'+' if delta >= 0 else ''}{delta} since first paper",
    )

    return SubjectDTO(
        header=header,
        papersBreakdown=breakdowns,
        topicMap=topic_map,
        paperHistory=paper_history,
    )


def _subject_weaknesses(records: list[PaperRecord]) -> WeaknessReport:
    """Fold one subject's records into an aggregate WeaknessReport (data-backed)."""
    return aggregate_weaknesses_from_history(
        StudentHistory(student_id=records[0].student_id if records else "unknown", records=records)
    )


def _paper_label(record: PaperRecord) -> str:
    """Human paper label from metadata, e.g. ``0625/12 - 2020``."""
    m = record.metadata
    year = f" - {m.session_year}" if m.session_year is not None else ""
    return f"{m.subject_code}/{m.paper_number}{m.paper_variant}{year}"


class _ResultHeaderFields(TypedDict):
    """Return shape of :func:`_result_header_fields`.

    CamelCase, matching :class:`~lemely.web.schemas_student.ResultDTO`'s field
    names directly. A plain ``dict[str, str | int]`` would force every
    read-site to re-narrow the value type, so a TypedDict is used instead.
    """

    code: str
    paper: str
    session: str
    boundaryYear: str
    railLeft: int
    railFoot: str


def _result_header_fields(
    metadata: ExamMetadata, awarded: int, maximum: int
) -> _ResultHeaderFields:
    """Compute the code/paper/session/boundaryYear/railLeft/railFoot header fields.

    Shared by GET /student/result/{id} and the POST /student/correct SSE
    complete frame — same boundary-store call, same format strings, so the two
    paths are provably consistent rather than duplicated logic that could
    silently drift.

    Returns camelCase keys matching :class:`ResultDTO`'s field names directly —
    ``student_result`` spreads them straight into the DTO constructor.
    ``student_correct``'s SSE call site renames ``boundaryYear``/``railLeft``/
    ``railFoot`` to snake_case explicitly when spreading these into
    ``bus.publish(...)`` kwargs, since raw SSE frames use snake_case top-level
    keys (``EventBus.publish`` forwards kwargs as-is, bypassing the DTO alias
    layer that ``ResultDTO`` relies on).
    """
    boundaries, _ = GradeBoundaryStore().resolve(metadata)
    a_pct = boundaries.get("A")
    a_marks = round((a_pct / 100.0) * maximum) if a_pct is not None else None
    rail_foot = f"A boundary sat at {a_marks}/{maximum}" if a_marks is not None else ""
    year = metadata.session_year
    return {
        "code": metadata.subject_code,
        "paper": f"Paper {metadata.paper_number} - Variant {metadata.paper_variant}",
        "session": metadata.session_month + (f" {year}" if year else ""),
        "boundaryYear": str(year) if year else "",
        "railLeft": round((awarded / maximum) * 100) if maximum else 0,
        "railFoot": rail_foot,
    }


# ── Paper result (flagship) ───────────────────────────────────────────────────


@router.get("/student/result/{paper_id}", response_model=ResultDTO)
def student_result(
    paper_id: str,
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    history_store: Annotated[HistoryStoreProtocol, Depends(get_history_store)],
) -> ResultDTO:
    """Return the flagship per-paper result for ``paper_id`` (a record index).

    ``paper_id`` addresses a paper by its position in the student's history
    (``"0"`` = first recorded). Data-backed: awarded/max/pct/grade and the
    boundary rail (rail position from percentage; ``railFoot`` from the resolved
    A-boundary). **Structurally empty:** ``theory`` and ``integrity`` — history
    records persist totals, weak-areas and metadata only, not the per-question
    answers/mark-scheme points that theory marking and plagiarism/AI-content
    checks require. Those lists are populated by the ``/correct`` SSE flow which
    holds a live :class:`CorrectionResult`; they are empty here by construction.
    """
    history = history_store.load(auth.user_id)
    try:
        index = int(paper_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=f"No paper {paper_id}") from exc
    # ``paper_id`` is a forward position; a negative value must 404 rather than
    # silently wrap to a tail record (Python's negative indexing).
    if index < 0 or index >= len(history.records):
        raise HTTPException(status_code=404, detail=f"No paper {paper_id}")
    record = history.records[index]

    max_marks = record.maximum_marks
    header = _result_header_fields(record.metadata, record.awarded_marks, max_marks)
    return ResultDTO(
        code=header["code"],
        paper=header["paper"],
        session=header["session"],
        markerLabel="",
        headline=f"{record.awarded_marks} out of {record.maximum_marks}.",
        summary="",
        awarded=record.awarded_marks,
        max=max_marks,
        pct=round(record.percentage),
        grade=record.grade,
        boundaryYear=header["boundaryYear"],
        railLeft=header["railLeft"],
        railFoot=header["railFoot"],
        railNote="",
        theory=[],
        integrity=_integrity_summary(record),
        provenance=record.metadata.source_document or "",
    )


def _integrity_summary(record: PaperRecord) -> list[IntegrityRowDTO]:
    """Integrity rows derivable from a history record (data-backed subset).

    A history record has no per-question answers, so plagiarism / AI-content
    detection cannot run here — those run in the live ``/correct`` flow. The one
    row we *can* assert from the record is grade-boundary provenance, so the
    student sees a real, non-fabricated integrity line rather than mock copy.
    """
    _, source = GradeBoundaryStore().resolve(record.metadata)
    detail = {
        "exact": "Official CAIE boundary matched for this exact variant.",
        "subject_default": "Estimated from this subject's historical average boundary "
        "(no exact-variant data for this session).",
        "global_default": "Estimated from a global average boundary (no subject data).",
    }[source]
    return [
        IntegrityRowDTO(
            mark="check" if source == "exact" else "dash",
            color="ok" if source == "exact" else "t2",
            label="Grade boundary resolved",
            detail=detail,
        )
    ]


# ── Upload a scan (self-mark ingest) ──────────────────────────────────────────


@router.post("/student/uploads", response_model=StudentUploadResponse)
async def student_upload(
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    settings: Annotated[Settings, Depends(get_settings)],
    upload_repo: Annotated[StudentUploadRepository, Depends(get_student_upload_repo)],
    storage_backend: Annotated[StorageBackend, Depends(get_storage_backend)],
    scan: Annotated[UploadFile, File()],
    mark_scheme: Annotated[UploadFile | None, File()] = None,
) -> StudentUploadResponse:
    """Persist a student's scanned paper (+ optional mark scheme) and register it.

    The scan is uploaded to object storage (:mod:`lemely.io.storage`) under
    ``uploads/{user_id}/{paperId}/{filename}`` — the object key is namespaced by
    both the authenticated user id and a server-generated ``paperId`` (the
    :class:`Upload` row's id), and the client filename is sanitised to a
    basename. The returned ``paperId`` is passed back to ``POST
    /api/student/correct`` to run the self-mark pipeline over this scan.
    """
    paper_id = uuid.uuid4()
    object_prefix = f"uploads/{auth.user_id}/{paper_id.hex}"

    scan_bytes = await scan.read()
    check_upload_cap(scan_bytes)
    object_path = f"{object_prefix}/{safe_upload_name(scan.filename, 'scan.pdf')}"
    # Off the event loop: this is ``async def``, and a blocking network call
    # made inline here would freeze every other request in the process for as
    # long as it took (the same shape decision D6.13 removed from the teacher
    # upload route).
    await anyio.to_thread.run_sync(
        storage_backend.upload, settings.storage.bucket, object_path, scan_bytes, scan.content_type
    )

    if mark_scheme is not None:
        # Fixed name so ``resolve_mark_scheme`` can find the sibling scheme object.
        scheme_bytes = await mark_scheme.read()
        check_upload_cap(scheme_bytes)
        await anyio.to_thread.run_sync(
            storage_backend.upload,
            settings.storage.bucket,
            f"{object_prefix}/mark_scheme.pdf",
            scheme_bytes,
            mark_scheme.content_type,
        )

    upload_repo.create_upload(
        user_id=auth.user_id,
        storage_path=object_path,
        original_filename=scan.filename,
        content_type=scan.content_type,
        byte_size=len(scan_bytes),
        upload_id=paper_id,
    )
    return StudentUploadResponse(paperId=str(paper_id))


# ── Reading a run that outlived its browser tab ───────────────────────────────


#: How long a run may sit in ``processing`` before the screen stops promising it.
#:
#: The status is written once, at the top of the run, and cleared to
#: ``complete``/``failed`` by the same function's ``finally``-adjacent paths. The
#: only way a row stays ``processing`` past that is a process that died holding
#: it — a deploy, a crash, an OOM — and no code will ever come back to correct
#: it, because the thread that owned the row no longer exists.
#:
#: So this is not a timeout and it does not cancel anything. It is the point at
#: which a screen should stop saying "still marking" and start saying "this
#: stopped and you can start it again", because past it, "still marking" is a
#: claim nothing is behind. Twenty minutes is deliberately far beyond a real
#: run: the slowest observed full-paper mark is a small number of minutes, and
#: the cost of being early here is telling a student their paper failed while it
#: is still being marked, which is much worse than a few extra minutes of
#: honest waiting.
MARKING_RUN_STALE_AFTER = timedelta(minutes=20)


def _run_dto(run: UploadRun, *, now: datetime | None = None) -> UploadRunDTO:
    """Render one upload's run state, including the staleness judgement.

    ``stale`` is only ever true for a ``processing`` row. A ``failed`` upload is
    not stale, it is finished; conflating the two would put a paper that has a
    real reported failure into the "we lost track of this" copy.
    """
    moment = now or datetime.now(UTC)
    processing = run.status is UploadStatus.processing
    return UploadRunDTO(
        paperId=str(run.id),
        status=run.status.value,
        filename=run.original_filename,
        startedAt=run.started_at if processing else None,
        stale=processing and (moment - run.started_at) > MARKING_RUN_STALE_AFTER,
    )


@router.get("/student/uploads/active", response_model=UploadRunDTO | None)
def student_active_upload(
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    upload_repo: Annotated[StudentUploadRepository, Depends(get_student_upload_repo)],
) -> UploadRunDTO | None:
    """Return the caller's marking run that is still going, or ``null``.

    The recovery half of the self-mark flow. ``POST /student/correct`` marks on a
    background thread that does not stop when the client disconnects, so a
    student who reloads, backgrounds the tab on a phone, or loses signal still
    has a paper being marked — with nothing on screen that knows it. This is how
    the screen finds it again.

    ``null`` is the ordinary answer and not an error: most of the time nothing
    is running.
    """
    run = upload_repo.get_active_run(user_id=auth.user_id)
    return None if run is None else _run_dto(run)


@router.get("/student/uploads/{paper_id}", response_model=UploadRunDTO)
def student_upload_run(
    paper_id: str,
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    upload_repo: Annotated[StudentUploadRepository, Depends(get_student_upload_repo)],
) -> UploadRunDTO:
    """Return one owned upload's run state, for polling a recovered run.

    Separate from ``/uploads/active`` because the two answer different
    questions, and the difference matters at exactly the moment this is used:
    ``active`` stops naming a paper the instant it finishes, so a client polling
    ``active`` would watch its run disappear and never learn whether it was
    marked or failed. Polling *the paper* ends on a terminal status that says
    which.
    """
    run = upload_repo.get_run(user_id=auth.user_id, upload_id=paper_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Unknown paper: {paper_id}")
    return _run_dto(run)


# ── Correct a paper (SSE self-mark) ───────────────────────────────────────────


def resolve_mark_scheme(
    sibling_scheme: Path | None,
    corpus: SchemeCorpusRepository,
    settings: Settings,
    gemini_client: GeminiClient,
    *,
    metadata: ExamMetadata | None,
) -> MarkScheme | None:
    """Resolve a mark scheme: sibling PDF first, then the corpus by detected metadata.

    Preference order (spec §4.3 — shared by both portals):

    1. ``sibling_scheme``, when given: a mark-scheme PDF uploaded alongside the
       scan, parsed via :class:`ChainedMarkSchemeParser` (deterministic first,
       Gemini fallback on a parse failure). A scheme handed to this call
       explicitly always wins over the corpus, whatever the corpus holds for
       the same paper.
    2. Otherwise, when ``metadata`` was detected, the parsed scheme corpus
       (:meth:`SchemeCorpusRepository.find_for`) — a query keyed on the exact
       detected paper identity, never a free-text/fuzzy match, so a near-miss
       returns ``None`` rather than a different paper's scheme.

    Returns ``None`` when neither source yields a scheme (the caller then warns
    and marks the upload failed rather than inventing marks).
    """
    if sibling_scheme is not None:
        from lemely.io.det import DeterministicMarkSchemeParser

        parser = ChainedMarkSchemeParser(
            DeterministicMarkSchemeParser(cfg=settings.det_parser),
            GeminiMarkSchemeParser(gemini_client),
        )
        return parser(sibling_scheme)
    if metadata is None:
        return None
    return corpus.find_for(metadata)


def _alert_teachers_and_parents(
    notification_service: NotificationService,
    push_transport: NotificationTransport,
    *,
    history_store: HistoryStoreProtocol,
    profile_service: StudentProfileService,
    class_service: ClassService,
    parent_service: ParentLinkService,
    student_id: str,
) -> None:
    """Raise ``at_risk_alert`` for a freshly corrected student's staff (D5.11).

    Runs after the correction has committed, wrapped, and never raises: the
    at-risk assessment and both recipient lookups are queries of our own and
    sit outside :func:`notify_safely`, so a failure anywhere in here must cost
    an alert and nothing else (D5.9 §1).

    **Rule 3 (≥14 days inactive) cannot fire at this seam and that is not an
    oversight.** A student who has just uploaded a paper is, by definition,
    active. Rule 3 is time-triggered and joins ``streak_warning`` and
    ``study_plan_reminder`` in D5.9 §5's no-scheduler limitation — which means
    the reason most likely to matter for a disengaging student is the one this
    build cannot deliver. Stated in D5.11 §2 and carried to the Phase-5
    limitations rather than left to be discovered.

    The dedupe key is ``(student, reason, Cairo civil date)`` (D5.11 §3):
    at-risk is a state, not an event, so an upload-keyed alert would send a
    teacher of thirty students one notification per upload. The day boundary is
    :func:`~lemely.db.xp_repo.civil_date_in_zone`, the same one D5.1 §4 fixed
    for streaks — Cairo is UTC+3 in summer, so a hardcoded offset is wrong for
    half the year.

    Every recipient's row is gated by **their own** preferences, which
    :func:`notify_safely` does for free by reading the recipient's row
    (D5.9 §3). That is what stops a student silencing alerts about themselves.
    """
    try:
        history = history_store.load(student_id)
        assessment = assess_at_risk(
            history,
            now=datetime.now(UTC),
            targets=profile_service.target_grades_for(student_id),
        )
        if not assessment.flags:
            return

        student_name = class_service.display_name_for(student_id)
        recipients = [
            *class_service.teachers_for_student(student_id),
            *(parent.parent_id for parent in parent_service.list_parents(student_id)),
        ]
        if not recipients:
            return

        today = civil_date_in_zone(datetime.now(UTC), zone=DEFAULT_ZONE)
        for flag in assessment.flags:
            for recipient in recipients:
                notify_safely(
                    notification_service,
                    push_transport,
                    user_id=recipient,
                    type=NotificationType.at_risk_alert,
                    title=f"{student_name} may need support",
                    # The reason, never the evidence. ``flag.summary`` renders
                    # marks and predicted grades, and the teacher's own at-risk
                    # view already shows them with their confidence intact —
                    # a grade on a lock screen is a grade on a lock screen
                    # whoever is holding the phone (D5.9 §2, UI spec §1.4).
                    body=AT_RISK_REASON_LABELS[flag.reason],
                    payload={"studentId": str(student_id), "reason": flag.reason.value},
                    dedupe_key=f"{student_id}:{flag.reason.value}:{today.isoformat()}",
                    seam="at_risk_alert",
                )
    except Exception:
        log.exception("at_risk_alert_failed", student_id=str(student_id))


@router.post("/student/correct")
def student_correct(
    payload: CorrectRequest,
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    # D7.5: the ONE route this soft-gate applies to — see
    # `require_verified_email`'s own docstring for why it is declared here,
    # after `auth`, and not e.g. on `/student/uploads`. Its result is unused
    # (the gate is the point, not the value), unlike `auth` above.
    _verified: Annotated[AuthContext, Depends(require_verified_email)],
    upload_repo: Annotated[StudentUploadRepository, Depends(get_student_upload_repo)],
    attempt_repo: Annotated[AttemptRepository, Depends(get_attempt_repo)],
    gemini_client: Annotated[GeminiClient, Depends(get_gemini_client)],
    settings: Annotated[Settings, Depends(get_settings)],
    storage_backend: Annotated[StorageBackend, Depends(get_storage_backend)],
    corpus: Annotated[SchemeCorpusRepository, Depends(get_scheme_corpus_repo)],
    xp_service: Annotated[XpService, Depends(get_xp_service)],
    notification_service: Annotated[NotificationService, Depends(get_notification_service)],
    push_transport: Annotated[NotificationTransport, Depends(get_push_transport)],
    history_store: Annotated[HistoryStoreProtocol, Depends(get_history_store)],
    profile_service: Annotated[StudentProfileService, Depends(get_student_profile_service)],
    class_service: Annotated[ClassService, Depends(get_class_service)],
    parent_service: Annotated[ParentLinkService, Depends(get_parent_link_service)],
) -> StreamingResponse:
    """Stream the real self-mark pipeline for an uploaded paper over SSE.

    **Gated on a verified email (D7.5).** This is the Gemini spend, and it is
    the *only* student route that carries ``require_verified_email`` — an
    unverified caller is refused with a **403**
    (``detail={"code": "email_unverified"}``) before any of the work below
    runs. ``POST /student/uploads`` is deliberately never gated the same way:
    a student who has already photographed a paper must not lose the capture
    to a verification wall.

    Resolves the caller-owned upload (a 404 for an unknown or foreign paper is
    raised *before* streaming starts, so the client never has to parse a
    mid-stream error), then runs extract → grade over the shared event bus and
    persists the full :class:`AccuracyReport` — one attempt with per-question
    results, weaknesses, and review-queue rows — via :class:`AttemptRepository`.
    The stream emits ``marking_progress`` frames and ends with a ``complete``
    summary frame plus the ``[DONE]`` sentinel; on any failure the upload is
    marked failed and a ``warning``/``error`` frame is emitted (never a
    traceback).
    """
    from lemely.runtime.events import EventType, bus
    from lemely.web.sse import bus_event_stream

    owned = upload_repo.get_owned_upload(user_id=auth.user_id, upload_id=payload.paperId)
    if owned is None:
        raise HTTPException(status_code=404, detail=f"Unknown paper: {payload.paperId}")

    def run() -> None:
        # P6.2. `UploadStatus.processing` existed from the first migration and
        # **no code path had ever written it**: an upload went `pending` at
        # creation and jumped straight to `complete`/`failed` here. So a paper
        # being marked right now was indistinguishable in the database from a
        # scan a student uploaded and abandoned, and two things followed.
        #
        #   1. A reload could not recover the run, because nothing recorded that
        #      one was in flight. That is audit M4, deferred from P4.2 with a
        #      note that the honest fix was not a styling job.
        #   2. The platform console's "Uploads in flight" counted `pending`, so
        #      every abandoned scan was in flight forever and the figure only
        #      ever grew.
        #
        # Written here rather than in the endpoint body so that the status is
        # only ever set when a worker thread genuinely exists to clear it: this
        # function IS the worker, and every exit from it below writes a terminal
        # status. Setting it before returning the StreamingResponse would leave
        # a row claiming to be marking if the stream were never consumed.
        #
        # Inside the `try`, not above it: this is a database write like any
        # other, and if it throws from outside the block then `finally:
        # bus.publish_done()` never runs and the client's stream hangs open
        # instead of failing.
        try:
            upload_repo.set_status(owned.id, UploadStatus.processing)
            with tempfile.TemporaryDirectory() as tmp_dir:
                tmp_path = Path(tmp_dir)
                scan_bytes = storage_backend.download(settings.storage.bucket, owned.storage_path)
                scan_path = tmp_path / Path(owned.storage_path).name
                scan_path.write_bytes(scan_bytes)

                # A sibling mark_scheme.pdf, if the student uploaded one, lives
                # next to the scan under the same object-key prefix.
                scheme_object_path = f"{Path(owned.storage_path).parent.as_posix()}/mark_scheme.pdf"
                sibling_scheme: Path | None = None
                try:
                    scheme_bytes = storage_backend.download(
                        settings.storage.bucket, scheme_object_path
                    )
                except StorageObjectNotFoundError:
                    pass
                else:
                    sibling_scheme = tmp_path / "mark_scheme.pdf"
                    sibling_scheme.write_bytes(scheme_bytes)

                metadata: ExamMetadata | None = None
                if settings.gemini_api_key is not None:
                    try:
                        metadata = ScanMetadataExtractor(gemini_client)(scan_path)
                    except Exception as exc:
                        bus.publish(
                            EventType.WARNING,
                            paper_id=payload.paperId,
                            message=f"Could not detect scan metadata: {exc}",
                        )

                mark_scheme = resolve_mark_scheme(
                    sibling_scheme, corpus, settings, gemini_client, metadata=metadata
                )
                if mark_scheme is None:
                    bus.publish(
                        EventType.WARNING,
                        paper_id=payload.paperId,
                        message="No mark scheme available for this paper; cannot mark.",
                    )
                    upload_repo.set_status(owned.id, UploadStatus.failed)
                    return

                extracted = extract_answers(scan_path, mark_scheme, gemini_client=gemini_client)
                report = grade_paper(
                    mark_scheme,
                    extracted,
                    gemini_client=gemini_client,
                    student_id=None,
                    integrity_settings=settings.integrity,
                )
                attempt_id = attempt_repo.persist_correction(
                    user_id=auth.user_id, report=report, upload_id=owned.id
                )
                upload_repo.set_status(owned.id, UploadStatus.complete)
                # P5.2 chunk B, D5.1: XP for the *act* of correcting a paper,
                # never for how well it was corrected — no mark/score/grade
                # is read here or passed to XpService.award. The attempt is
                # already persisted and the upload already marked complete
                # above, so a failure inside this call is caught and logged
                # by award_xp_safely and never turns this already-successful
                # correction into an error frame (D5.1 §3, "the learning
                # wins").
                #
                # The dedupe key is the **upload** id, not the attempt id.
                # D5.1 §8 names "the paper id" and opens with "a paper can be
                # re-marked ... none of those may re-award XP".
                # ``persist_correction`` inserts a fresh ``Attempt`` on every
                # run, so keying on the attempt would mint a new key each
                # time and award again for every re-correction of the same
                # paper — the precise anomaly §8 exists to prevent. The
                # upload is the stable identity of "this paper", so a student
                # re-running the pipeline on it earns nothing new (D5.3).
                award_xp_safely(
                    xp_service,
                    user_id=auth.user_id,
                    source=XpSource.paper_corrected,
                    dedupe_key=str(owned.id),
                    subject_code=report.correction.metadata.subject_code,
                    seam="paper_corrected",
                )
                # P5.6 chunk C2a, D5.9: tell the student their paper is marked.
                # Fail-open for the same reason as the XP award above — the
                # attempt is persisted and the upload is complete, so nothing
                # here may turn a successful correction into an error frame.
                #
                # The dedupe key is the **upload**, exactly as the XP key is,
                # and for exactly D5.3's reason: ``persist_correction`` mints a
                # fresh ``Attempt`` every run, so an attempt-keyed notification
                # would re-fire on every re-correction of the same PDF. D5.9 §6
                # wrote this down before it could recur.
                #
                # Title and body are **pointers, never the data** (D5.9 §2):
                # the paper's identity, and no mark, percentage or grade. That
                # is what makes the preference gate lossless — a student who
                # turns ``grade_ready`` off loses a nudge, not a result — and it
                # keeps grades private (UI spec §1.4) on a row that a push
                # service is told about.
                paper_metadata = report.correction.metadata
                notify_safely(
                    notification_service,
                    push_transport,
                    user_id=auth.user_id,
                    type=NotificationType.grade_ready,
                    title="Your paper has been marked",
                    # "Paper 1 Variant 2", never "Paper 1/2": a slash between two
                    # small integers reads as a mark out of a total on a lock
                    # screen, which is the one thing this line must not look like.
                    body=(
                        f"{paper_metadata.subject_code} Paper "
                        f"{paper_metadata.paper_number} Variant {paper_metadata.paper_variant}"
                        " is ready to review."
                    ),
                    payload={"uploadId": str(owned.id)},
                    dedupe_key=str(owned.id),
                    seam="grade_ready",
                )
                # P5.6 chunk C2c, D5.11: the same already-committed correction
                # is also the only real "this student's risk may have changed"
                # event in the build — at-risk is computed on *read* everywhere
                # else, so there is nothing else to hang this on.
                _alert_teachers_and_parents(
                    notification_service,
                    push_transport,
                    history_store=history_store,
                    profile_service=profile_service,
                    class_service=class_service,
                    parent_service=parent_service,
                    student_id=auth.user_id,
                )
                # ``report.correction.metadata`` (an ``ExamMetadata``, derived from
                # ``mark_scheme.metadata`` by ``core.correction._exam_metadata``) —
                # not the separately-detected ``metadata`` variable above, which
                # can be None. It's reliably present whenever a scheme was
                # successfully resolved, whether via detected-metadata corpus
                # lookup or a student-supplied sibling PDF, and — unlike
                # ``mark_scheme.metadata`` itself, which is a distinct
                # ``loose_schemas.MarkSchemeMetadata`` — it is already the
                # ``ExamMetadata`` type ``_result_header_fields`` expects.
                header = _result_header_fields(
                    report.correction.metadata,
                    report.correction.awarded_marks,
                    report.correction.maximum_marks,
                )
                bus.publish(
                    EventType.MARKING_PROGRESS,
                    paper_id=payload.paperId,
                    phase="complete",
                    attempt_id=str(attempt_id),
                    awarded=report.correction.awarded_marks,
                    max_marks=report.correction.maximum_marks,
                    grade=report.grade_prediction.grade,
                    confidence=report.grade_prediction.confidence.value,
                    needs_review=report.correction.needs_teacher_review,
                    questions=[
                        question_to_dto(q).model_dump(by_alias=True)
                        for q in report.correction.questions
                    ],
                    # SSE frames are raw kwargs forwarded snake_case (bypassing the
                    # camelCase DTO alias layer), so the two camelCase-named header
                    # keys are renamed explicitly here.
                    code=header["code"],
                    paper=header["paper"],
                    session=header["session"],
                    boundary_year=header["boundaryYear"],
                    rail_left=header["railLeft"],
                    rail_foot=header["railFoot"],
                    pct=round(report.grade_prediction.percentage),
                )
        except Exception as exc:
            bus.publish(EventType.ERROR, paper_id=payload.paperId, message=str(exc))
            upload_repo.set_status(owned.id, UploadStatus.failed)
        finally:
            bus.publish_done()

    return StreamingResponse(
        bus_event_stream(run, run_id=f"student:{payload.paperId}"), media_type="text/event-stream"
    )


# ── Standings ─────────────────────────────────────────────────────────────────


@router.get("/student/standings", response_model=StandingsDTO)
def student_standings(
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    history_store: Annotated[HistoryStoreProtocol, Depends(get_history_store)],
) -> StandingsDTO:
    """Return the student's standings summary.

    Data-backed: ``paperCount`` (total recorded papers), ``streakDays`` (distinct
    recorded-paper calendar days), and per-subject ``papers`` counts.
    **Structurally empty:** each subject ``rank`` — cross-student ranking needs a
    cohort the single-student store cannot provide — and the leaderboard boards,
    which are omitted entirely (no peer data source).

    The two counts that say *papers* count papers (``is_paper``, origin only —
    a paper with an unreadable grade is still a paper the student sat);
    ``streakDays`` counts **all** activity, quizzes included, because a quiz is
    a day the student showed up and the whole point of a streak is to say so
    (``docs/quiz-model.md`` §5).
    """
    history = history_store.load(auth.user_id)
    papers = [record for record in history.records if is_paper(record)]
    by_code: dict[str, int] = {}
    for record in papers:
        by_code[record.metadata.subject_code] = by_code.get(record.metadata.subject_code, 0) + 1

    palette: list[VizColor] = ["ok", "t1", "t2", "accent", "warn"]
    subject_ranks = [
        SubjectRankDTO(
            code=code,
            name=code,
            rank="",
            color=palette[i % len(palette)],
            papers=count,
        )
        for i, (code, count) in enumerate(sorted(by_code.items()))
    ]

    streak_days = len({r.recorded_at[:10] for r in history.records})
    return StandingsDTO(
        subjectRanks=subject_ranks,
        paperCount=len(papers),
        streakDays=streak_days,
    )


# ── Classes (join by code) ────────────────────────────────────────────────────


@router.post("/student/classes/join", response_model=JoinClassResponseDTO)
def student_join_class(
    payload: JoinClassRequestDTO,
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    service: Annotated[ClassService, Depends(get_class_service)],
) -> JoinClassResponseDTO:
    """Self-enrol the authenticated student into a class via its join code.

    Identity is always the authenticated caller (``auth.user_id``), never a
    caller-supplied id (D1.6 — the IDOR pattern the two former ``studentId``
    body fields were removed for). Idempotent: re-joining an already-enrolled
    class is a no-op. An unknown code is a clean 404, never a 500.
    """
    try:
        row = service.join_by_code(auth.user_id, payload.joinCode)
    except JoinCodeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return JoinClassResponseDTO(classId=str(row.class_id), className=row.name)


# ── Parent links (invite/list/revoke) ───────────────────────────────────────


@router.get("/student/parent-links", response_model=ParentLinkListDTO)
def student_list_parent_links(
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    service: Annotated[ParentLinkService, Depends(get_parent_link_service)],
) -> ParentLinkListDTO:
    """Return every parent linked to the authenticated student.

    Identity is always the authenticated caller (``auth.user_id``), never a
    caller-supplied id (D1.6's IDOR discipline, matching ``student_join_class``).
    """
    parents = service.list_parents(auth.user_id)
    return ParentLinkListDTO(
        parents=[
            LinkedParentDTO(parentId=str(p.parent_id), displayName=p.display_name, phone=p.phone)
            for p in parents
        ]
    )


@router.post("/student/parent-links", response_model=LinkedParentDTO)
def student_link_parent(
    payload: LinkParentRequestDTO,
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    service: Annotated[ParentLinkService, Depends(get_parent_link_service)],
) -> LinkedParentDTO:
    """Invite an existing parent (by phone) to link to the authenticated student.

    Resolves ``phone`` to an *existing* ``role=parent`` user only (D3.11) —
    this never creates an account from a student-supplied phone (a stranger's
    mistyped or spoofed number could otherwise be handed this student's
    grades). No matching parent account is a clean 404: the parent must
    OTP-login at least once (which auto-creates their ``role=parent`` user,
    ``AuthService.verify_otp``) before this student can invite them again.
    Idempotent: inviting an already-linked parent again is a no-op success,
    not an error.
    """
    try:
        parent = service.link(auth.user_id, payload.phone)
    except ParentUserNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return LinkedParentDTO(
        parentId=str(parent.parent_id), displayName=parent.display_name, phone=parent.phone
    )


@router.delete("/student/parent-links/{parent_id}", status_code=204)
def student_unlink_parent(
    parent_id: str,
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    service: Annotated[ParentLinkService, Depends(get_parent_link_service)],
) -> None:
    """Revoke a parent's link to the authenticated student. Idempotent.

    Revoking a link that does not exist (already revoked, or never granted)
    is a silent no-op, not an error — mirrors ``ClassService.remove_student``.
    """
    try:
        service.unlink(auth.user_id, parent_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
