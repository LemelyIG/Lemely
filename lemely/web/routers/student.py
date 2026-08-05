"""Student portal (results + study) endpoints.

Router owned by the student-portal worker. Endpoints are added here without
touching ``app.py`` — the app factory already mounts this router.

**Data provenance.** Every response is computed from real core logic and the
:class:`~lemely.io.history_store.HistoryStore`: cross-paper aggregation via
:mod:`lemely.core.analytics`, grade + boundary resolution via
:mod:`lemely.io.grade_boundaries`, scheduling via :mod:`lemely.core.study_plan`,
and integrity via :mod:`lemely.core.plagiarism` / :mod:`lemely.io.integrity`.
Where a frontend field has *no* backing data source (leaderboard peers, streak
history beyond recorded-paper days, marketing copy, or the per-question detail
that history records do not persist), the response returns a typed-neutral
default (``""`` / ``0`` / ``[]``) rather than the mock's demo numbers. Each
converter docstring calls out which fields are data-backed vs structurally empty.
"""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path
from typing import Annotated, TypedDict

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

# WeaknessReport and HistoryStoreProtocol stay as runtime imports (noqa: TC001):
# FastAPI dependency injection and the response converters resolve their
# annotations at call time, so they cannot move into a TYPE_CHECKING block.
from lemely.core.analytics import aggregate_weaknesses_from_history
from lemely.core.history import HistoryStoreProtocol, PaperRecord, StudentHistory
from lemely.core.loose_schemas import MarkScheme
from lemely.core.schemas import ExamMetadata, WeaknessReport
from lemely.core.study import StudentProfile, StudyPlan
from lemely.core.study_plan import build_study_plan
from lemely.db.attempt_repo import AttemptRepository
from lemely.db.models.enums import Role, UploadStatus
from lemely.db.upload_repo import StudentUploadRepository
from lemely.io.gemini import GeminiClient
from lemely.io.grade_boundaries import GradeBoundaryStore
from lemely.io.parsers import ChainedMarkSchemeParser, GeminiMarkSchemeParser
from lemely.io.scan_metadata import ScanMetadataExtractor
from lemely.io.storage import StorageBackend, StorageObjectNotFoundError
from lemely.io.study_plan_ai import StudyPlanNarrator
from lemely.runtime.config import Settings
from lemely.web.deps import (
    AuthContext,
    get_attempt_repo,
    get_gemini_client,
    get_history_store,
    get_settings,
    get_storage_backend,
    get_student_upload_repo,
    require_role,
)
from lemely.web.schemas import question_to_dto
from lemely.web.schemas_student import (
    CorrectRequest,
    IntegrityRowDTO,
    MomentumDTO,
    OnboardingRequest,
    OverviewDTO,
    PaperBarDTO,
    PaperBreakdownDTO,
    PaperHistoryRowDTO,
    PlanSessionDTO,
    ResultDTO,
    StandingsDTO,
    StudentProfileDTO,
    StudentUploadResponse,
    StudyPlanDTO,
    StudyPlanRequest,
    SubjectDTO,
    SubjectHeaderDTO,
    SubjectRankDTO,
    SubjectRowDTO,
    TopicTileDTO,
    VizColor,
    WeakThreadDTO,
)
from lemely.web.services.grading import extract_answers, grade_paper
from lemely.web.upload_utils import check_upload_cap, safe_upload_name

router = APIRouter(prefix="/api")

# Default weekly study budget when the GET plan endpoint has no caller-supplied
# figure (the POST path takes an explicit ``weeklyHours``). Kept as a named
# constant rather than a mock demo number.
_DEFAULT_WEEKLY_HOURS = 11.0

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
    """Build the momentum sparkline from recorded-paper percentages (data-backed).

    Uses the same coordinate transform as ``web/src/portals/student/data.ts``
    (300x88 viewbox, 55-100 % band). Returns empty ``path``/``area`` when fewer
    than two papers exist (a polyline needs at least two points).
    """
    series = [r.percentage for r in records]
    if len(series) < 2:
        return MomentumDTO(path="", area="", lastX="0.0", lastY="88.0", labels=[])

    def mx(i: int) -> float:
        return (i / (len(series) - 1)) * 300.0

    def my(v: float) -> float:
        return 88.0 - ((v - 55.0) / 45.0) * 78.0

    path = " ".join(f"{'L' if i else 'M'}{mx(i):.1f} {my(v):.1f}" for i, v in enumerate(series))
    last_i = len(series) - 1
    labels = [r.recorded_at[:7] for r in records]
    return MomentumDTO(
        path=path,
        area=f"{path} L300 88 L0 88 Z",
        lastX=f"{mx(last_i):.1f}",
        lastY=f"{my(series[last_i]):.1f}",
        labels=labels,
    )


def _subjects(history: StudentHistory) -> list[SubjectRowDTO]:
    """Aggregate history into per-subject Overview rows (data-backed).

    ``pct`` is the mark-weighted mean across the subject's papers; ``trend`` is
    the percentage delta between the first and last recorded paper; ``grade``
    resolves against real boundaries. ``name``/``detail`` are neutral (history
    records carry no human subject name or teacher), so ``name`` echoes the code
    and ``detail`` reports the paper count only.
    """
    boundary_store = GradeBoundaryStore()
    by_code: dict[str, list[PaperRecord]] = {}
    for record in history.records:
        by_code.setdefault(record.metadata.subject_code, []).append(record)

    rows: list[SubjectRowDTO] = []
    for code, records in sorted(by_code.items()):
        awarded = sum(r.awarded_marks for r in records)
        maximum = sum(r.maximum_marks for r in records)
        pct = round((awarded / maximum) * 100.0) if maximum else 0
        boundaries, _ = boundary_store.resolve(records[-1].metadata)
        delta = round(records[-1].percentage - records[0].percentage)
        rows.append(
            SubjectRowDTO(
                code=code,
                name=code,
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
) -> OverviewDTO:
    """Return the student Overview: subject rows, global weak threads, momentum.

    All fields are data-backed from the caller's :class:`StudentHistory` and
    :mod:`lemely.core.analytics`. ``forecast`` is the space-joined per-subject
    predicted grades; ``weakGlobal`` is the top weak topics folded across every
    paper. ``studentName`` echoes the authenticated user id (no name store yet).
    """
    history = history_store.load(auth.user_id)
    subjects = _subjects(history)
    weaknesses = aggregate_weaknesses_from_history(history)
    return OverviewDTO(
        studentName=auth.user_id,
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
) -> SubjectDTO:
    """Return one subject's papers breakdown, topic map, and paper history.

    Data-backed: per-paper breakdown bars (percentage per recorded paper),
    weighted mean, predicted grade + boundary, per-topic accuracy tiles, and the
    paper-history table. 404 when the student has no papers for ``code``.
    """
    history = history_store.load(auth.user_id)
    indexed_records = _subject_records(history, code)
    if not indexed_records:
        raise HTTPException(status_code=404, detail=f"No history for subject {code}")
    records = [record for _, record in indexed_records]

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

    weaknesses = _subject_weaknesses(records)
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

    header = SubjectHeaderDTO(
        meta=f"{code} - Extended",
        title=code,
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

    The scan is uploaded to Supabase Storage under
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
    storage_backend.upload(settings.storage.bucket, object_path, scan_bytes, scan.content_type)

    if mark_scheme is not None:
        # Fixed name so ``resolve_mark_scheme`` can find the sibling scheme object.
        scheme_bytes = await mark_scheme.read()
        check_upload_cap(scheme_bytes)
        storage_backend.upload(
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


# ── Correct a paper (SSE self-mark) ───────────────────────────────────────────


def _metadata_matches(scheme_meta: object, detected: ExamMetadata) -> bool:
    """Return True when a stored scheme's metadata matches the detected paper.

    Compares subject_code / paper_number / paper_variant always, and the session
    (month + year) only when the scan detected one — a scan without a resolved
    session should still match a scheme for the same paper.
    """
    if getattr(scheme_meta, "subject_code", None) != detected.subject_code:
        return False
    if getattr(scheme_meta, "paper_number", None) != detected.paper_number:
        return False
    if getattr(scheme_meta, "paper_variant", None) != detected.paper_variant:
        return False
    if detected.session_year is not None:
        return bool(getattr(scheme_meta, "session_year", None) == detected.session_year)
    return True


def resolve_mark_scheme(
    scan_path: Path,
    settings: Settings,
    gemini_client: GeminiClient,
    *,
    metadata: ExamMetadata | None = None,
) -> MarkScheme | None:
    """Resolve a mark scheme for a scan: sibling PDF first, then scheme corpus.

    Preference order:

    1. A ``mark_scheme.pdf`` sitting next to the scan (uploaded with it) — parsed
       via the deterministic parser with a Gemini fallback.
    2. When ``metadata`` was detected, a parsed scheme JSON in
       ``output_dir/schemes`` whose metadata matches the detected paper.

    Returns ``None`` when neither source yields a scheme (the caller then warns
    and marks the upload failed rather than inventing marks).
    """
    sibling = scan_path.parent / "mark_scheme.pdf"
    if sibling.exists():
        from lemely.io.det import DeterministicMarkSchemeParser

        parser = ChainedMarkSchemeParser(
            DeterministicMarkSchemeParser(cfg=settings.det_parser),
            GeminiMarkSchemeParser(gemini_client),
        )
        return parser(sibling)

    if metadata is None:
        return None

    import json

    from pydantic import ValidationError

    schemes_dir = settings.paths.output_dir / "schemes"
    if not schemes_dir.exists():
        return None
    for path in sorted(schemes_dir.glob("*.json")):
        try:
            scheme = MarkScheme.model_validate(json.loads(path.read_text(encoding="utf-8")))
        except (ValidationError, json.JSONDecodeError, OSError):
            continue
        if _metadata_matches(scheme.metadata, metadata):
            return scheme
    return None


@router.post("/student/correct")
def student_correct(
    payload: CorrectRequest,
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    upload_repo: Annotated[StudentUploadRepository, Depends(get_student_upload_repo)],
    attempt_repo: Annotated[AttemptRepository, Depends(get_attempt_repo)],
    gemini_client: Annotated[GeminiClient, Depends(get_gemini_client)],
    settings: Annotated[Settings, Depends(get_settings)],
    storage_backend: Annotated[StorageBackend, Depends(get_storage_backend)],
) -> StreamingResponse:
    """Stream the real self-mark pipeline for an uploaded paper over SSE.

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
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                tmp_path = Path(tmp_dir)
                scan_bytes = storage_backend.download(settings.storage.bucket, owned.storage_path)
                scan_path = tmp_path / Path(owned.storage_path).name
                scan_path.write_bytes(scan_bytes)

                # A sibling mark_scheme.pdf, if the student uploaded one, lives
                # next to the scan under the same object-key prefix.
                scheme_object_path = f"{Path(owned.storage_path).parent.as_posix()}/mark_scheme.pdf"
                try:
                    scheme_bytes = storage_backend.download(
                        settings.storage.bucket, scheme_object_path
                    )
                except StorageObjectNotFoundError:
                    pass
                else:
                    (tmp_path / "mark_scheme.pdf").write_bytes(scheme_bytes)

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
                    scan_path, settings, gemini_client, metadata=metadata
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

    return StreamingResponse(bus_event_stream(run), media_type="text/event-stream")


# ── Study plan ────────────────────────────────────────────────────────────────


def _plan_to_dto(plan: StudyPlan) -> StudyPlanDTO:
    """Convert a core :class:`StudyPlan` into its camelCase DTO (data-backed)."""
    return StudyPlanDTO(
        studentId=plan.student_id,
        weeklyHours=plan.weekly_hours,
        sessions=[
            PlanSessionDTO(
                topic=s.topic,
                subjectCode=s.subject_code,
                hours=s.hours,
                focus=s.focus,
            )
            for s in plan.sessions
        ],
        narrative=plan.narrative,
    )


@router.get("/student/plan", response_model=StudyPlanDTO)
def student_plan_get(
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    history_store: Annotated[HistoryStoreProtocol, Depends(get_history_store)],
) -> StudyPlanDTO:
    """Return the deterministic weekly study plan (data-backed, no narrative).

    Built by :func:`lemely.core.study_plan.build_study_plan` from the student's
    aggregate weaknesses over the default weekly budget. ``narrative`` is null on
    this path (no Gemini call).
    """
    history = history_store.load(auth.user_id)
    weaknesses = aggregate_weaknesses_from_history(history)
    subjects = sorted({r.metadata.subject_code for r in history.records})
    profile = StudentProfile(
        student_id=auth.user_id,
        grade_level="",
        subjects=subjects or ["unknown"],
        weekly_study_hours=_DEFAULT_WEEKLY_HOURS,
    )
    plan = build_study_plan(profile, weaknesses, weekly_hours=profile.weekly_study_hours)
    return _plan_to_dto(plan)


@router.post("/student/plan", response_model=StudyPlanDTO)
def student_plan_post(
    payload: StudyPlanRequest,
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    history_store: Annotated[HistoryStoreProtocol, Depends(get_history_store)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> StudyPlanDTO:
    """Build the authenticated student's study plan, optionally AI-narrated.

    The student is the authenticated caller (``auth.user_id``) — never a
    caller-supplied id — so a student can only ever generate their own plan
    (former IDOR removed). Deterministic schedule is data-backed from history
    weaknesses. When ``narrate`` is true a :class:`StudyPlanNarrator` (Gemini)
    enriches it with a narrative. Narration only runs when an API key is
    configured (mirroring the upload pipeline); in the default no-key state — or
    if the narrator raises at runtime — the endpoint returns a clean 503 rather
    than an unhandled 500. The deterministic plan is always available, so a
    degraded caller can retry without narration.
    """
    history = history_store.load(auth.user_id)
    weaknesses = aggregate_weaknesses_from_history(history)
    subjects = sorted({r.metadata.subject_code for r in history.records})
    profile = StudentProfile(
        student_id=auth.user_id,
        grade_level="",
        subjects=subjects or ["unknown"],
        weekly_study_hours=payload.weeklyHours,
    )
    plan = build_study_plan(profile, weaknesses, weekly_hours=payload.weeklyHours)

    if payload.narrate:
        if settings.gemini_api_key is None:
            raise HTTPException(
                status_code=503,
                detail="AI narration is unavailable: no API key is configured.",
            )
        try:
            narrator = StudyPlanNarrator(get_gemini_client())
            plan = narrator.narrate(plan)
        except HTTPException:
            raise
        except Exception as exc:  # narrator failed at runtime — degrade cleanly.
            raise HTTPException(
                status_code=503,
                detail=f"AI narration is temporarily unavailable: {exc}",
            ) from exc

    return _plan_to_dto(plan)


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
    """
    history = history_store.load(auth.user_id)
    by_code: dict[str, int] = {}
    for record in history.records:
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
        paperCount=len(history.records),
        streakDays=streak_days,
    )


# ── Onboarding ────────────────────────────────────────────────────────────────


@router.post("/student/onboarding", response_model=StudentProfileDTO)
def student_onboarding(
    payload: OnboardingRequest,
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
) -> StudentProfileDTO:
    """Build and return a :class:`StudentProfile` from onboarding slider inputs.

    The profile belongs to the authenticated student (``auth.user_id``), never a
    caller-supplied id (former IDOR removed). Fully data-backed: subjects and
    per-subject confidence come from the slider readings (a slider with a subject
    ``code`` contributes a ``pct/100`` confidence); ``weeklyStudyHours`` is the
    reported hours. Nothing is fabricated — sliders without a subject code (e.g.
    "hours", "pressure") are treated as non-subject signals and excluded from
    ``subjects``/``confidenceBySubject``.
    """
    confidence: dict[str, float] = {}
    subjects: list[str] = []
    for slider in payload.sliders:
        if slider.code:
            subjects.append(slider.code)
            confidence[slider.code] = round(slider.pct / 100.0, 4)

    profile = StudentProfile(
        student_id=auth.user_id,
        grade_level=payload.gradeLevel,
        subjects=subjects,
        school=payload.school,
        weekly_study_hours=payload.weeklyHours,
        confidence_by_subject=confidence,
    )
    return StudentProfileDTO(
        studentId=profile.student_id,
        gradeLevel=profile.grade_level,
        subjects=profile.subjects,
        school=profile.school,
        weeklyStudyHours=profile.weekly_study_hours,
        confidenceBySubject=profile.confidence_by_subject,
    )
