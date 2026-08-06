"""Teacher portal (grading console) endpoints.

Owned by the teacher-portal worker; extends the app factory's mounted router in
place (``app.py`` is never edited). Every endpoint computes its payload from real
core logic — the extraction/grading pipeline in :mod:`lemely.web.services.grading`,
the :class:`HistoryStore`, the analytics helpers, parsed mark schemes, and the
deterministic scheme parser. Screen fields with no backend source (attendance,
retention minutes, hand-written narratives) are returned empty / omitted; see
:mod:`lemely.web.schemas_teacher` for the per-field provenance docs.

State that has no persistent home yet (per-paper :class:`CorrectionResult`
objects, which :class:`PaperRecord` does not carry) lives in a small in-process
store, mirroring :class:`~lemely.web.jobs.JobRegistry`. Swap both for a DB when
horizontal scaling is required.
"""

# FastAPI ``Depends``/``response_model`` and pydantic model construction need these
# type imports at runtime; TC00x would move them into ``TYPE_CHECKING`` and break
# dependency injection. (The per-file-ignore in pyproject.toml handles this.)
from __future__ import annotations

import json
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import ValidationError

from lemely.core.analytics import (
    aggregate_weaknesses_from_history,
    compare_performance,
)
from lemely.core.at_risk import (
    AtRiskFlag,
    AtRiskReason,
    BelowTargetEvidence,
    DecliningTrendEvidence,
    InactivityEvidence,
    assess_at_risk,
    flag_fingerprint,
)
from lemely.core.generation import GeneratedQuestion, GeneratedQuiz
from lemely.core.history import (
    GRADE_ORDER,
    HistoryStoreProtocol,
    PaperRecord,
    StudentHistory,
    now_iso,
)
from lemely.core.loose_schemas import MarkScheme
from lemely.core.schemas import (
    REVIEW_CONFIDENCE_THRESHOLD,
    AccuracyReport,
    ExamMetadata,
    WeaknessReport,
)
from lemely.db.at_risk_repo import (
    AtRiskAcknowledgementRow,
    AtRiskAckOwnershipError,
    AtRiskAckService,
)
from lemely.db.class_repo import ClassService, RosterEntry
from lemely.db.models.enums import QuestionSource, Role
from lemely.db.question_bank_repo import (
    QuestionBankRow,
    QuestionBankService,
    generated_questions_to_bank_rows,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
from lemely.db.review_repo import ReviewService
from lemely.io.gemini import GeminiClient
from lemely.io.question_generation import QuestionGenerator
from lemely.io.scan_metadata import ScanMetadataExtractor
from lemely.io.teacher_quiz import TeacherQuizBuilder
from lemely.runtime.config import Settings
from lemely.runtime.events import EventType, bus
from lemely.web.deps import (
    AuthContext,
    get_at_risk_ack_service,
    get_class_service,
    get_gemini_client,
    get_history_store,
    get_question_bank_service,
    get_review_service,
    get_settings,
    require_role,
)
from lemely.web.jobs import registry
from lemely.web.schemas import (
    question_to_dto,
    weak_area_to_dto,
)
from lemely.web.schemas_analytics import (
    AtRiskListDTO,
    AtRiskListEntryDTO,
    AttemptDTO,
    StudentDetailDTO,
    StudentEngagementDTO,
    StudentTrendPointDTO,
    StudentWeaknessDTO,
    SubjectPredictionDTO,
)
from lemely.web.schemas_teacher import (
    AcknowledgeAtRiskRequestDTO,
    AtRiskAcknowledgementDTO,
    AtRiskFlagDTO,
    AtRiskStudentDTO,
    BatchTabDTO,
    DetectedFieldDTO,
    GradingQueueDTO,
    OverviewDTO,
    PaperDetailDTO,
    PaperKind,
    PaperListDTO,
    PaperSummaryDTO,
    PipelineStepDTO,
    PreviewQuestionDTO,
    QuestionPoolDTO,
    QueueRowDTO,
    QuizPoolsDTO,
    QuizPreviewDTO,
    QuizTopicDTO,
    QuizTopicsDTO,
    SchemeListDTO,
    SchemeRowDTO,
    StatCardDTO,
    StudentRowDTO,
    UploadResponseDTO,
)
from lemely.web.upload_utils import (
    safe_upload_name,
    write_upload_capped,
)

# Every teacher-portal route is staff-only. Gating at the router level means a
# 401 (no/invalid token) or 403 (student/parent) is enforced uniformly and any
# future teacher route inherits the guard by construction. Per-teacher row-level
# tenancy (a teacher only seeing their own classes) landed in P3.1: the class
# CRUD/roster/enrolment routes live in ``lemely.web.routers.classes`` on top of
# the DB-backed class model (D3.1), not the shared interim HistoryStore.
router = APIRouter(
    prefix="/api",
    dependencies=[Depends(require_role(Role.teacher, Role.school_admin, Role.platform_admin))],
)

# Hard cap on a single uploaded file (scan or mark scheme). Uploads are streamed
# to disk in chunks and aborted with a 413 once this many bytes are seen, so a
# hostile client cannot exhaust disk by streaming an unbounded body.
_MAX_UPLOAD_BYTES = 25 * 1024 * 1024
_UPLOAD_CHUNK_BYTES = 1024 * 1024

# Confidence at/above which a marked question is treated as auto-graded; below it
# the question is surfaced in the teacher review queue. Aliases the single domain
# definition in ``lemely.core.schemas`` (D2.2) — never re-literalise this value.
_REVIEW_CONFIDENCE = REVIEW_CONFIDENCE_THRESHOLD

# The grade ladder, best to worst. Aliases the single domain definition in
# ``lemely.core.at_risk`` (D3.3) — never re-literalise this value.
_GRADE_ORDER = GRADE_ORDER

# Grades that make the roster's ``gradeAtRisk`` badge / the overview's "At risk"
# stat card light up. This is a *different, shallower* signal than the D3.3
# at-risk *flag* engine below (``assess_at_risk``/``_at_risk``): it just means
# "this grade is low right now", not "this student is on a declining
# trajectory" — the two must not be conflated. Kept as its own literal set
# because it has no analogue in ``lemely.core.at_risk``.
_AT_RISK_GRADES = {"D", "E", "U"}

# The staff triple every route needing per-caller tenancy scoping (overview,
# student detail, at-risk list, P3.3) authenticates against. Named so the long
# Annotated[...] signatures stay under the line-length limit, mirroring
# ``lemely.web.routers.classes._STAFF_ROLES`` exactly (same three roles, same
# reasoning) — not re-imported from there to avoid a classes<->teacher import
# cycle (``classes.py`` already imports from this module).
_STAFF_ROLES = (Role.teacher, Role.school_admin, Role.platform_admin)

#: Per-band ceiling on how many previously generated bank questions
#: :func:`_existing_questions` pulls in as reuse material. A bound, not a
#: page size: the builder only ever needs a few candidates per band, and an
#: unbounded read would grow with a teacher's whole generation history.
_REUSE_POOL_PER_BAND = 20


# ---------------------------------------------------------------------------
# In-process paper store (holds full grade results keyed by paper id).
# ---------------------------------------------------------------------------


class _PaperStore:
    """Thread-safe registry of graded papers awaiting review / display.

    A paper starts life at ``upload`` (kind ``queued``/``processing``) and gains
    a full :class:`AccuracyReport` once graded. Keyed by the same id the frontend
    receives from ``POST /api/papers/upload``.
    """

    def __init__(self) -> None:
        """Initialise an empty store."""
        self._lock = threading.Lock()
        self._papers: dict[str, _PaperEntry] = {}

    def put(self, entry: _PaperEntry) -> None:
        """Insert or replace an entry."""
        with self._lock:
            self._papers[entry.paper_id] = entry

    def get(self, paper_id: str) -> _PaperEntry | None:
        """Return the entry for ``paper_id``, or ``None`` if unknown."""
        with self._lock:
            return self._papers.get(paper_id)

    def all(self) -> list[_PaperEntry]:
        """Return every stored entry in insertion order."""
        with self._lock:
            return list(self._papers.values())

    def clear(self) -> None:
        """Remove all entries. Intended for tests."""
        with self._lock:
            self._papers.clear()


class _PaperEntry:
    """A single tracked paper: identity plus its grade result once available."""

    __slots__ = (
        "kind",
        "mark_scheme",
        "metadata",
        "paper_id",
        "report",
        "scan_path",
        "student_id",
    )

    def __init__(
        self,
        paper_id: str,
        student_id: str,
        *,
        kind: PaperKind = "queued",
        metadata: ExamMetadata | None = None,
        scan_path: Path | None = None,
        mark_scheme: MarkScheme | None = None,
        report: AccuracyReport | None = None,
    ) -> None:
        """Initialise a paper entry, optionally pre-graded."""
        self.paper_id = paper_id
        self.student_id = student_id
        self.kind = kind
        self.metadata = metadata
        self.scan_path = scan_path
        self.mark_scheme = mark_scheme
        self.report = report


papers_store: _PaperStore = _PaperStore()


# ---------------------------------------------------------------------------
# Shared helpers.
# ---------------------------------------------------------------------------


def _safe_upload_name(filename: str | None, fallback: str) -> str:
    """Thin wrapper over :func:`lemely.web.upload_utils.safe_upload_name`.

    Kept as a module-level name so the shared basename-sanitisation is reachable
    at the same call site the teacher routes already use.
    """
    return safe_upload_name(filename, fallback)


def _write_upload_capped(data: bytes, dest: Path) -> None:
    """Write ``data`` to ``dest``, capped at :data:`_MAX_UPLOAD_BYTES`.

    Delegates to :func:`lemely.web.upload_utils.write_upload_capped`, reading the
    module-level cap at call time so the existing monkeypatch test (which lowers
    ``_MAX_UPLOAD_BYTES`` to force a 413) keeps working.
    """
    write_upload_capped(data, dest, max_bytes=_MAX_UPLOAD_BYTES)


def _session_label(session_month: str, session_year: int | None) -> str:
    """Render a session as ``"May/June 2020"`` (or just the month when no year)."""
    if session_year is not None:
        return f"{session_month} {session_year}"
    return session_month


def _detected_fields(metadata: ExamMetadata) -> list[DetectedFieldDTO]:
    """Flatten :class:`ExamMetadata` into the grading console's detected-field rows."""
    return [
        DetectedFieldDTO(key="Subject code", value=metadata.subject_code),
        DetectedFieldDTO(key="Paper", value=f"Paper {metadata.paper_number}"),
        DetectedFieldDTO(key="Session", value=metadata.session_month),
        DetectedFieldDTO(key="Variant", value=f"Variant {metadata.paper_variant}"),
        DetectedFieldDTO(
            key="Year",
            value=str(metadata.session_year) if metadata.session_year else "—",
        ),
    ]


def _paper_kind(report: AccuracyReport | None) -> PaperKind:
    """Classify a paper: ``review`` when it needs teacher eyes, else ``graded``."""
    if report is None:
        return "queued"
    return "review" if report.correction.needs_teacher_review else "graded"


def _mean(values: list[float]) -> float | None:
    """Return the arithmetic mean rounded to 2 dp, or ``None`` for an empty list."""
    if not values:
        return None
    return round(sum(values) / len(values), 2)


def _pipeline_steps(report: AccuracyReport) -> list[PipelineStepDTO]:
    """Derive the five pipeline steps from a completed grade result.

    Counts are the real per-question totals: total questions, questions marked,
    and questions clearing the review-confidence threshold. All ``done`` after a
    completed grade (the pipeline ran to the boundary-resolution stage).
    """
    questions = report.correction.questions
    total = len(questions)
    marked = sum(1 for q in questions if q.marker_source != "missing")
    confident = sum(1 for q in questions if q.confidence_score >= _REVIEW_CONFIDENCE)
    return [
        PipelineStepDTO(label="Scan ingested", count=f"{total} / {total}", state="done"),
        PipelineStepDTO(label="Handwriting read", count=f"{total} / {total}", state="done"),
        PipelineStepDTO(label="Mark scheme aligned", count=f"{marked} / {total}", state="done"),
        PipelineStepDTO(label="Confidence check", count=f"{confident} / {total}", state="done"),
        PipelineStepDTO(label="Grade boundaries", count=f"{total} / {total}", state="done"),
    ]


def _latest_records(history_store: HistoryStoreProtocol) -> list[PaperRecord]:
    """Return the most-recent :class:`PaperRecord` per student across all history."""
    latest: list[PaperRecord] = []
    for student_id in history_store.list_students():
        history = history_store.load(student_id)
        if history.records:
            latest.append(history.records[-1])
    return latest


def _student_delta(history: StudentHistory) -> float | None:
    """Percentage delta of the latest paper vs. the prior same-paper attempt.

    Data-backed via :func:`compare_performance`; ``None`` when there is no prior
    attempt of the same subject+paper.
    """
    if not history.records:
        return None
    latest = history.records[-1]
    prior = StudentHistory(student_id=history.student_id, records=history.records[:-1])
    return compare_performance(prior, latest).percentage_delta


# ---------------------------------------------------------------------------
# Grading console.
# ---------------------------------------------------------------------------


@router.post("/papers/upload", response_model=UploadResponseDTO)
async def upload_paper(
    settings: Annotated[Settings, Depends(get_settings)],
    gemini_client: Annotated[GeminiClient, Depends(get_gemini_client)],
    scan: Annotated[UploadFile, File()],
    mark_scheme: Annotated[UploadFile | None, File()] = None,
) -> UploadResponseDTO:
    """Ingest a scanned paper (+ optional mark scheme) and detect its metadata.

    Persists the uploads under ``output_dir/uploads/{paperId}`` and registers a
    job + paper entry. Detected metadata comes from
    :class:`ScanMetadataExtractor` when an API key is configured; when detection
    is unavailable the ``detected`` list is empty (never fabricated).

    Security (D1.12, fixes the acceptance-review H2): the interim paper bucket is
    keyed on the server-generated ``paper_id`` only. A teacher-supplied student
    identity is deliberately NOT accepted here — without the class↔student
    ownership model (still deferred, D1.6) no teacher can be authorized to write a
    graded record into a specific student's history, so accepting one would be a
    cross-tenant write. Associating a graded paper with a real student account
    lands with the DB-backed class model (Phase 2/3), gated on verified ownership.
    """
    job = registry.create("paper_upload", filename=scan.filename)
    paper_id = job.id
    resolved_student = paper_id

    upload_dir = settings.paths.output_dir / "uploads" / paper_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    # Server-controlled destinations: the directory is namespaced by ``paper_id``
    # and the basename is sanitised, so the client filename can never escape the
    # sandbox (path traversal) or overwrite files outside this upload.
    scan_path = upload_dir / _safe_upload_name(scan.filename, "scan.pdf")
    _write_upload_capped(await scan.read(), scan_path)

    if mark_scheme is not None:
        ms_path = upload_dir / _safe_upload_name(mark_scheme.filename, "mark_scheme.pdf")
        _write_upload_capped(await mark_scheme.read(), ms_path)

    detected: list[DetectedFieldDTO] = []
    metadata: ExamMetadata | None = None
    detection_failed = False
    if settings.gemini_api_key is not None:
        try:
            metadata = ScanMetadataExtractor(gemini_client)(scan_path)
            detected = _detected_fields(metadata)
        except Exception as exc:
            detection_failed = True
            registry.update(job.id, error=f"metadata detection failed: {exc}")

    papers_store.put(
        _PaperEntry(
            paper_id=paper_id,
            student_id=resolved_student,
            kind="queued",
            metadata=metadata,
            scan_path=scan_path,
        )
    )
    registry.update(job.id, status="error" if detection_failed else "done")
    return UploadResponseDTO(jobId=job.id, paperId=paper_id, detected=detected)


def _require_paper(paper_id: str) -> _PaperEntry:
    """Return the stored paper entry or raise a 404."""
    entry = papers_store.get(paper_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Unknown paper: {paper_id}")
    return entry


@router.post("/papers/{paper_id}/extract")
def extract_paper(
    paper_id: str,
    gemini_client: Annotated[GeminiClient, Depends(get_gemini_client)],
) -> StreamingResponse:
    """Extract student answers for a paper and stream ``EXTRACTION_PROGRESS`` over SSE.

    Reuses :func:`lemely.web.services.grading.extract_answers`, which drives the
    shared pipeline and publishes ``EXTRACTION_PROGRESS`` events; those are
    forwarded as SSE frames by :func:`bus_event_stream`. Requires the paper to
    have an attached mark scheme (from upload); without one, a ``WARNING`` frame
    is emitted instead of fabricating answers.
    """
    from lemely.web.services.grading import extract_answers
    from lemely.web.sse import bus_event_stream

    entry = _require_paper(paper_id)

    def run() -> None:
        try:
            if entry.mark_scheme is None or entry.scan_path is None:
                bus.publish(
                    EventType.WARNING,
                    paper_id=paper_id,
                    message="No mark scheme / scan attached; cannot extract answers.",
                )
                return
            extract_answers(
                entry.scan_path,
                entry.mark_scheme,
                gemini_client=gemini_client,
            )
        finally:
            bus.publish_done()

    return StreamingResponse(bus_event_stream(run), media_type="text/event-stream")


@router.post("/papers/{paper_id}/grade")
def grade_paper_endpoint(
    paper_id: str,
    history_store: Annotated[HistoryStoreProtocol, Depends(get_history_store)],
    gemini_client: Annotated[GeminiClient, Depends(get_gemini_client)],
) -> StreamingResponse:
    """Grade a paper and stream ``MARKING_PROGRESS`` over SSE.

    Two paths, both data-backed:

    * When the paper has an attached mark scheme, reuses
      :func:`lemely.web.services.grading.grade_paper` — which runs hybrid marking,
      resolves grade boundaries, and (given ``student_id`` + the history store)
      appends a :class:`PaperRecord` — then stores the resulting report.
    * When a fully-graded :class:`AccuracyReport` is already attached (e.g. from a
      prior service run), replays its ``MARKING_PROGRESS`` events and persists a
      :class:`PaperRecord`.

    Never invents marks: if neither a mark scheme nor a report is present, a
    ``WARNING`` frame is emitted.
    """
    from lemely.web.services.grading import extract_answers, grade_paper
    from lemely.web.sse import bus_event_stream

    entry = _require_paper(paper_id)

    def run() -> None:
        try:
            if entry.mark_scheme is not None and entry.scan_path is not None:
                extracted = extract_answers(
                    entry.scan_path,
                    entry.mark_scheme,
                    gemini_client=gemini_client,
                )
                report = grade_paper(
                    entry.mark_scheme,
                    extracted,
                    gemini_client=gemini_client,
                    student_id=entry.student_id,
                    history_store=history_store,
                )
                entry.report = report
                entry.kind = _paper_kind(report)
                return
            cached_report: AccuracyReport | None = entry.report
            if cached_report is None:
                bus.publish(
                    EventType.WARNING,
                    paper_id=paper_id,
                    message="No mark scheme or graded correction attached to paper.",
                )
                return
            for question in cached_report.correction.questions:
                bus.publish(
                    EventType.MARKING_PROGRESS,
                    paper_id=paper_id,
                    question_id=question.question_id,
                    marker_source=question.marker_source,
                    confidence=question.confidence_score,
                )
            record = PaperRecord(
                student_id=entry.student_id,
                metadata=cached_report.correction.metadata,
                awarded_marks=cached_report.correction.awarded_marks,
                maximum_marks=cached_report.correction.maximum_marks,
                percentage=cached_report.grade_prediction.percentage,
                grade=cached_report.grade_prediction.grade,
                weak_areas=cached_report.weaknesses.weak_areas,
                recorded_at=now_iso(),
            )
            history_store.append(entry.student_id, record)
            entry.kind = _paper_kind(cached_report)
        finally:
            bus.publish_done()

    return StreamingResponse(bus_event_stream(run), media_type="text/event-stream")


def _paper_summary(entry: _PaperEntry) -> PaperSummaryDTO:
    """Build the grid-card DTO for a stored paper."""
    report = entry.report
    kind = entry.kind if report is None else _paper_kind(report)
    if report is None:
        return PaperSummaryDTO(
            id=entry.paper_id,
            name=entry.student_id,
            kind=kind,
            status=kind.capitalize(),
        )
    correction = report.correction
    min_conf = min(
        (q.confidence_score for q in correction.questions),
        default=1.0,
    )
    return PaperSummaryDTO(
        id=entry.paper_id,
        name=entry.student_id,
        kind=kind,
        status="Review" if kind == "review" else "Graded",
        awardedMarks=correction.awarded_marks,
        maxMarks=correction.maximum_marks,
        confidence=round(min_conf, 2),
        needsReview=correction.needs_teacher_review,
    )


def _batch_tabs(entries: list[_PaperEntry]) -> list[BatchTabDTO]:
    """Compute live batch-filter tab counts from the stored papers."""
    kinds = [e.kind if e.report is None else _paper_kind(e.report) for e in entries]
    total = len(kinds)
    review = sum(1 for k in kinds if k == "review")
    graded = sum(1 for k in kinds if k == "graded")
    processing = sum(1 for k in kinds if k in {"processing", "queued"})
    return [
        BatchTabDTO(id="all", label="All", count=str(total)),
        BatchTabDTO(id="review", label="Need review", count=str(review)),
        BatchTabDTO(id="graded", label="Auto-graded", count=str(graded)),
        BatchTabDTO(id="processing", label="Processing", count=str(processing)),
    ]


@router.get("/papers", response_model=PaperListDTO)
def list_papers() -> PaperListDTO:
    """Return every tracked paper as grid cards plus computed batch tabs."""
    entries = papers_store.all()
    return PaperListDTO(
        papers=[_paper_summary(e) for e in entries],
        tabs=_batch_tabs(entries),
    )


@router.get("/papers/{paper_id}", response_model=PaperDetailDTO)
def get_paper(paper_id: str) -> PaperDetailDTO:
    """Return the full grade detail (questions, weak areas, pipeline) for a paper."""
    entry = _require_paper(paper_id)
    report = entry.report
    if report is None:
        raise HTTPException(status_code=409, detail=f"Paper {paper_id} has not been graded yet.")
    correction = report.correction
    return PaperDetailDTO(
        id=entry.paper_id,
        name=entry.student_id,
        kind=_paper_kind(report),
        awardedMarks=correction.awarded_marks,
        maxMarks=correction.maximum_marks,
        needsReview=correction.needs_teacher_review,
        metadata=_detected_fields(correction.metadata),
        pipeline=_pipeline_steps(report),
        questions=[question_to_dto(q) for q in correction.questions],
        weakAreas=[weak_area_to_dto(w) for w in report.weaknesses.weak_areas],
    )


@router.get("/grading/queue", response_model=GradingQueueDTO)
def grading_queue() -> GradingQueueDTO:
    """Return low-confidence questions flagged for teacher review across all papers."""
    rows: list[QueueRowDTO] = []
    for entry in papers_store.all():
        report = entry.report
        if report is None:
            continue
        for question in report.correction.questions:
            if question.needs_teacher_review or question.confidence_score < _REVIEW_CONFIDENCE:
                rows.append(
                    QueueRowDTO(
                        paperId=entry.paper_id,
                        name=entry.student_id,
                        questionId=question.question_id,
                        topic=question.topic,
                        confidence=round(question.confidence_score, 2),
                        awardedMarks=question.awarded_marks,
                        maxMarks=question.maximum_marks,
                    )
                )
    rows.sort(key=lambda r: r.confidence if r.confidence is not None else 1.0)
    return GradingQueueDTO(rows=rows)


# ---------------------------------------------------------------------------
# Mark schemes.
# ---------------------------------------------------------------------------


def _schemes_dir(settings: Settings) -> Path:
    """Return (creating) the directory holding parsed mark-scheme JSON files."""
    schemes_dir = settings.paths.output_dir / "schemes"
    schemes_dir.mkdir(parents=True, exist_ok=True)
    return schemes_dir


def _load_scheme(path: Path) -> MarkScheme | None:
    """Load a parsed :class:`MarkScheme` JSON file, or ``None`` if invalid."""
    try:
        return MarkScheme.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (ValidationError, json.JSONDecodeError, OSError):
        return None


def _scheme_row(path: Path, scheme: MarkScheme) -> SchemeRowDTO:
    """Build a :class:`SchemeRowDTO` from a parsed mark scheme on disk."""
    meta = scheme.metadata
    return SchemeRowDTO(
        doc=path.name,
        paper=f"Paper {meta.paper_number} V{meta.paper_variant}",
        session=_session_label(meta.session_month, meta.session_year),
        maxMarks=meta.maximum_mark,
        questionCount=len(scheme.all_questions_flat()),
        status="parsed",
    )


@router.get("/schemes", response_model=SchemeListDTO)
def list_schemes(
    settings: Annotated[Settings, Depends(get_settings)],
) -> SchemeListDTO:
    """Return parsed mark schemes plus computed stats (parsed / pending / failed)."""
    schemes_dir = _schemes_dir(settings)
    rows: list[SchemeRowDTO] = []
    failed = 0
    for path in sorted(schemes_dir.glob("*.json")):
        scheme = _load_scheme(path)
        if scheme is None:
            failed += 1
            continue
        rows.append(_scheme_row(path, scheme))
    # Only stats backed by real, computed data are emitted (D1.12 acceptance-review
    # honesty fix M2): "Parsed"/"Failed" come from the on-disk scan above. The former
    # "Pending" (PDFs awaiting parse) and "Your own" (per-teacher uploaded) cards were
    # hardcoded "0" — there is no upload-queue or per-teacher scheme ownership model in
    # Phase 1, so surfacing them as live counts misrepresented the feature. They return
    # when the backing data exists (upload queue + teacher↔scheme ownership, Phase 2/3).
    stats = [
        StatCardDTO(key="Parsed", value=str(len(rows)), unit="schemes"),
        StatCardDTO(
            key="Failed",
            value=str(failed),
            unit="",
            valueTone="err" if failed else "t1",
        ),
    ]
    return SchemeListDTO(schemes=rows, stats=stats)


@router.post("/schemes", response_model=SchemeRowDTO)
async def upload_scheme(
    settings: Annotated[Settings, Depends(get_settings)],
    scheme_pdf: Annotated[UploadFile, File()],
) -> SchemeRowDTO:
    """Parse an uploaded CAIE mark-scheme PDF deterministically and persist it.

    Uses :class:`DeterministicMarkSchemeParser` (no Gemini call). On success the
    parsed :class:`MarkScheme` JSON is written to ``output_dir/schemes`` and the
    resulting row is returned. Parse failures surface as a 422.
    """
    from lemely.io.det import DeterministicMarkSchemeParser

    schemes_dir = _schemes_dir(settings)
    # Sanitise the client filename to a basename before joining — the raw value
    # must never be trusted as a path (traversal into ``../`` etc.).
    filename = _safe_upload_name(scheme_pdf.filename, "scheme.pdf")
    pdf_path = schemes_dir / filename
    _write_upload_capped(await scheme_pdf.read(), pdf_path)

    try:
        scheme = DeterministicMarkSchemeParser(cfg=settings.det_parser)(pdf_path)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Mark scheme parse failed: {exc}") from exc

    json_path = pdf_path.with_suffix(".json")
    json_path.write_text(scheme.model_dump_json(indent=2), encoding="utf-8")
    return _scheme_row(json_path, scheme)


# ---------------------------------------------------------------------------
# AI quizzes.
# ---------------------------------------------------------------------------


def _existing_questions(
    bank_service: QuestionBankService,
    caller_id: uuid.UUID,
    school_ids: Sequence[uuid.UUID],
    subject_code: str,
) -> list[GeneratedQuestion]:
    """Load the caller's reusable generated-question pool from the question bank.

    Reads the bank behind ``visible_bank_filter`` — platform-shared rows, the
    caller's own, and their school's — rather than the old
    ``output_dir/questions/*.json`` scan. Two reasons, both load-bearing:

    * That scan was the same process-global tenancy leak ``/quizzes/pools``
      was moved off (``docs/quiz-model.md`` §1.3): it fed *every* teacher's
      generated questions into *every* other teacher's quiz.
    * Since chunk D, ``/quizzes/generate`` persists to the bank instead of
      writing those JSON files, so nothing writes that directory any more.
      Left on disk this would have been a reuse path that silently always
      returned nothing — every preview re-generating from scratch against
      the Gemini budget, and the no-key degraded path returning an empty
      quiz forever, with a docstring still claiming a working pool.

    Only ``generated`` rows are reused: ``past_paper`` and ``teacher_upload``
    rows are not this builder's material, and blending them here would let a
    band-less ad-hoc generation quietly serve up past-paper content.
    """
    rows: list[QuestionBankRow] = []
    for band in ("foundation", "standard", "challenge"):
        rows.extend(
            bank_service.select_questions(
                caller_id,
                school_ids,
                subject_code=subject_code,
                band=band,
                count=_REUSE_POOL_PER_BAND,
                source=QuestionSource.generated,
            )
        )
    return [
        GeneratedQuestion(
            topic=row.topic or "",
            difficulty=row.difficulty,
            prompt=row.prompt,
            model_answer=row.model_answer or "",
            mark_scheme_points=list(row.mark_scheme_points),
            total_marks=row.total_marks,
            source_question_ids=list(row.source_question_ids),
        )
        for row in rows
    ]


@router.get("/quizzes/pools", response_model=QuizPoolsDTO)
def quiz_pools(
    auth: Annotated[AuthContext, Depends(require_role(*_STAFF_ROLES))],
    history_store: Annotated[HistoryStoreProtocol, Depends(get_history_store)],
    class_service: Annotated[ClassService, Depends(get_class_service)],
    bank_service: Annotated[QuestionBankService, Depends(get_question_bank_service)],
    subject_code: str = "",
) -> QuizPoolsDTO:
    """Return the quiz question-source pools with live counts, from the bank.

    Moved off the process-global ``output_dir/questions`` disk scan onto
    :class:`QuestionBankService` behind ``visible_bank_filter``
    (``docs/quiz-model.md`` §2/§1.3): the previous scan read every teacher's
    generated questions indiscriminately (a tenancy leak); this reads only
    what is platform-shared, the caller's own, or their school's. ``past`` is
    genuinely ``0`` for a subject with no indexed past-paper rows (D3.7) —
    ``detail`` then carries the exact honest-degradation wording rather than
    a plausible-looking zero with no explanation. ``ai`` is now real data
    too: ``POST /quizzes/generate`` (below) is the only path that ever fills
    it (D3.7's "the bank ships empty" consequence).
    """
    try:
        caller_uuid = uuid.UUID(auth.user_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    resolved_subject = subject_code or _infer_subject_code(history_store) or "0000"
    school_ids = class_service.member_school_ids(caller_uuid)

    def _pool_total(source: QuestionSource) -> int:
        counts = bank_service.count_by_band(
            caller_uuid, school_ids, subject_code=resolved_subject, source=source
        )
        return sum(counts.values())

    past = _pool_total(QuestionSource.past_paper)
    ai = _pool_total(QuestionSource.generated)
    mine = _pool_total(QuestionSource.teacher_upload)

    past_detail = (
        f"No past-paper questions indexed for {resolved_subject} yet; use generated questions."
        if past == 0
        else "CAIE official, from parsed papers"
    )
    return QuizPoolsDTO(
        pools=[
            QuestionPoolDTO(key="past", label="Past papers", detail=past_detail, count=past),
            QuestionPoolDTO(
                key="ai",
                label="AI-generated",
                detail="Stylistically matched to CAIE",
                count=ai,
            ),
            QuestionPoolDTO(
                key="mine",
                label="My uploads",
                detail="Your uploaded questions",
                count=mine,
            ),
        ]
    )


@router.get("/quizzes/topics", response_model=QuizTopicsDTO)
def quiz_topics(
    history_store: Annotated[HistoryStoreProtocol, Depends(get_history_store)],
) -> QuizTopicsDTO:
    """Return candidate quiz topics ranked by aggregate marks lost across history.

    Topics come from the aggregate :class:`WeaknessReport` folded over every
    student's history. ``selected`` is always ``False`` — pre-selection is UI
    state, not backend data.
    """
    aggregate = _aggregate_history_weaknesses(history_store)
    topics = [
        QuizTopicDTO(
            topic=area.topic,
            marksLost=area.lost_marks,
            marksAvailable=area.maximum_marks,
        )
        for area in aggregate.weak_areas
    ]
    return QuizTopicsDTO(topics=topics)


def _aggregate_history_weaknesses(history_store: HistoryStoreProtocol) -> WeaknessReport:
    """Fold every student's history into one aggregate :class:`WeaknessReport`."""
    all_records: list[PaperRecord] = []
    for student_id in history_store.list_students():
        all_records.extend(history_store.load(student_id).records)
    combined = StudentHistory(student_id="__all__", records=all_records)
    return aggregate_weaknesses_from_history(combined)


def _preview_question(question: GeneratedQuestion) -> PreviewQuestionDTO:
    """Convert a core :class:`GeneratedQuestion` into a preview DTO."""
    return PreviewQuestionDTO(
        topic=question.topic,
        difficulty=question.difficulty,
        prompt=question.prompt,
        marks=question.total_marks,
        source="existing" if question.source_question_ids else "ai",
        sourceQuestionIds=list(question.source_question_ids),
    )


def _build_quiz(
    settings: Settings,
    history_store: HistoryStoreProtocol,
    gemini_client: GeminiClient,
    bank_service: QuestionBankService,
    caller_id: uuid.UUID,
    school_ids: Sequence[uuid.UUID],
    *,
    subject_code: str,
    count: int,
    topics: list[str] | None,
) -> tuple[GeneratedQuiz, set[str]]:
    """Assemble a quiz via :class:`TeacherQuizBuilder` (select-then-generate).

    Generation is only attempted when an API key is configured (mirroring
    :func:`upload_paper`); without one the quiz is built from the existing
    question pool alone so the endpoint degrades to a partial result instead of
    raising an unhandled 500 on the default no-key state. A runtime generation
    failure is surfaced as a clean 503, never a 500.

    The reuse pool comes from the question bank scoped to ``caller_id``/
    ``school_ids`` (see :func:`_existing_questions`), so one teacher's
    generated questions never reach another's quiz.

    Returns the quiz **and the prompts that came from the reuse pool**. The
    caller needs the second element to avoid writing a reused question back
    into the bank it was just read from: now that reuse reads the bank
    rather than a directory nothing writes, an unfiltered write-back would
    duplicate every reused question on every generate, inflating the live
    pool count — the exact failure ``uq_question_bank_paper_question`` exists
    to prevent on the past-paper side (§1.3), which generated rows (no
    ``paper_id``) are not covered by.
    """
    aggregate = _aggregate_history_weaknesses(history_store)
    resolved_subject = subject_code or _infer_subject_code(history_store) or "0000"
    existing = _existing_questions(bank_service, caller_id, school_ids, resolved_subject)
    reused_prompts = {q.prompt for q in existing}

    if settings.gemini_api_key is None:
        # No generation possible: return whatever the existing pool can supply.
        builder = TeacherQuizBuilder(
            QuestionGenerator(gemini_client),
            existing_questions=existing,
        )
        return (
            builder.build(
                resolved_subject,
                WeaknessReport(weak_areas=[]),  # empty → builder skips generation
                count=count,
                topics=topics,
            ),
            reused_prompts,
        )

    builder = TeacherQuizBuilder(
        QuestionGenerator(gemini_client),
        existing_questions=existing,
    )
    try:
        return (
            builder.build(
                resolved_subject,
                aggregate,
                count=count,
                topics=topics,
            ),
            reused_prompts,
        )
    except Exception as exc:  # generation failed at runtime — degrade cleanly.
        raise HTTPException(
            status_code=503,
            detail=f"Quiz generation is temporarily unavailable: {exc}",
        ) from exc


def _infer_subject_code(history_store: HistoryStoreProtocol) -> str | None:
    """Infer a subject code from the most recent recorded paper, if any."""
    records = _latest_records(history_store)
    if not records:
        return None
    return records[-1].metadata.subject_code


def _quiz_to_preview(quiz: GeneratedQuiz) -> QuizPreviewDTO:
    """Convert a :class:`GeneratedQuiz` into the preview response (2.5 min/question)."""
    questions = [_preview_question(q) for q in quiz.questions]
    return QuizPreviewDTO(
        subjectCode=quiz.subject_code,
        questions=questions,
        estMinutes=round(len(questions) * 2.5),
    )


@router.post("/quizzes/preview", response_model=QuizPreviewDTO)
def quiz_preview(
    auth: Annotated[AuthContext, Depends(require_role(*_STAFF_ROLES))],
    settings: Annotated[Settings, Depends(get_settings)],
    history_store: Annotated[HistoryStoreProtocol, Depends(get_history_store)],
    gemini_client: Annotated[GeminiClient, Depends(get_gemini_client)],
    class_service: Annotated[ClassService, Depends(get_class_service)],
    bank_service: Annotated[QuestionBankService, Depends(get_question_bank_service)],
    subject_code: str = "",
    count: int = 4,
    topics: list[str] | None = None,
) -> QuizPreviewDTO:
    """Preview a quiz assembled from existing questions, topping up via generation.

    Takes ``auth`` explicitly (the router already requires a staff role) so
    the reuse pool can be scoped to this caller rather than read from a
    process-global pool — see :func:`_existing_questions`.
    """
    try:
        caller_uuid = uuid.UUID(auth.user_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    quiz, _reused = _build_quiz(
        settings,
        history_store,
        gemini_client,
        bank_service,
        caller_uuid,
        class_service.member_school_ids(caller_uuid),
        subject_code=subject_code,
        count=count,
        topics=topics,
    )
    return _quiz_to_preview(quiz)


@router.post("/quizzes/generate", response_model=QuizPreviewDTO)
def quiz_generate(
    auth: Annotated[AuthContext, Depends(require_role(*_STAFF_ROLES))],
    settings: Annotated[Settings, Depends(get_settings)],
    history_store: Annotated[HistoryStoreProtocol, Depends(get_history_store)],
    gemini_client: Annotated[GeminiClient, Depends(get_gemini_client)],
    class_service: Annotated[ClassService, Depends(get_class_service)],
    bank_service: Annotated[QuestionBankService, Depends(get_question_bank_service)],
    subject_code: str = "",
    count: int = 5,
    topics: list[str] | None = None,
) -> QuizPreviewDTO:
    """Generate a full quiz and persist it to the question bank.

    Writes bank rows instead of a JSON file (``docs/quiz-model.md`` §2:
    "``/quizzes/generate`` writes bank rows instead of a JSON file") —
    ``source=generated``, ``difficulty_source=declared_by_generator``, and
    ``owner_id=`` the generating teacher (their generation, their pool per
    §1.3's visibility tiers), never the ``owner_id=NULL`` the one-shot
    legacy on-disk importer uses. This is now the *only* path that ever
    fills the bank's generated pool (D3.7 consequence): the bank ships
    empty, and stays empty for a subject until a teacher generates here.
    """
    try:
        caller_uuid = uuid.UUID(auth.user_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    quiz, reused_prompts = _build_quiz(
        settings,
        history_store,
        gemini_client,
        bank_service,
        caller_uuid,
        class_service.member_school_ids(caller_uuid),
        subject_code=subject_code,
        count=count,
        topics=topics,
    )
    # Only genuinely new questions are written back: a question the builder
    # reused *from* the bank is already a row there, and re-inserting it
    # would inflate the pool count on every generate (see :func:`_build_quiz`).
    fresh = GeneratedQuiz(
        subject_code=quiz.subject_code,
        questions=[q for q in quiz.questions if q.prompt not in reused_prompts],
    )
    bank_service.add_questions(generated_questions_to_bank_rows(fresh, owner_id=caller_uuid))
    return _quiz_to_preview(quiz)


# ---------------------------------------------------------------------------
# Classes.
#
# The class CRUD/roster/enrolment routes themselves live in
# ``lemely.web.routers.classes`` (P3.1, D3.1) on top of the DB-backed class
# model. ``_student_row`` stays here because it is a roster-row *analytics*
# helper (built from a student's history) reused by that router, alongside
# ``_latest_records``/``_mean``/``_aggregate_history_weaknesses``/
# ``_student_delta``/``_GRADE_ORDER``/``_AT_RISK_GRADES`` above.
# ---------------------------------------------------------------------------


def _student_row(
    history: StudentHistory, *, display_name: str, student_id: str
) -> StudentRowDTO | None:
    """Build a roster row from a student's history, or ``None`` if empty.

    ``display_name``/``student_id`` come from the real class roster (D3.1) —
    ``history.student_id`` is the raw user-id key used to address the history
    store, not a human name.
    """
    if not history.records:
        return None
    latest = history.records[-1]
    weakest = min(
        latest.weak_areas,
        key=lambda a: a.accuracy,
        default=None,
    )
    return StudentRowDTO(
        name=display_name,
        studentId=student_id,
        grade=latest.grade,
        mark=f"{latest.awarded_marks}/{latest.maximum_marks}",
        delta=_student_delta(history),
        weakTopic=weakest.topic if weakest is not None else None,
        gradeAtRisk=latest.grade in _AT_RISK_GRADES,
    )


def _visible_students(service: ClassService, auth: AuthContext) -> dict[str, RosterEntry]:
    """Union of every roster in every class the caller may see (D3.1 tenancy).

    The single authorization gate every student-scoped teacher route (P3.3:
    the overview, ``GET /teacher/students/{id}``, ``GET /teacher/at-risk``)
    is built on: a teacher/school_admin may reach a student only if that
    student appears in the roster of at least one class the caller
    owns/administers. ``ClassService.list_classes`` already returns ``[]`` for
    platform_admin (no super-role bypass, D1.6/D1.10), so this is always empty
    for them too — there is no separate case to special-case here.

    When a class appears in more than one roster this iterates (unlikely
    given ownership is per-teacher, but school_admin scope could theoretically
    overlap two classes with the same enrolled student) the later class simply
    overwrites the earlier ``RosterEntry`` for that student id; both carry the
    same identity, so this is harmless.
    """
    visible: dict[str, RosterEntry] = {}
    for row in service.list_classes(auth.user_id, auth.role):
        for entry in service.roster(auth.user_id, auth.role, row.class_id):
            visible[str(entry.student_id)] = entry
    return visible


def _acknowledgement_index(
    ack_service: AtRiskAckService,
    auth: AuthContext,
    *,
    student_ids: list[str] | None = None,
) -> dict[tuple[str, AtRiskReason], AtRiskAcknowledgementRow]:
    """String-keyed index of every at-risk ack the caller has recorded (D3.5).

    Loaded once per request and threaded through ``_at_risk_flag_dto`` so
    T-01 (overview), T-05 (student detail), and T-06 (at-risk list) all read
    the identical acknowledged/unacknowledged state for the same flag — the
    shared-helper discipline D3.3/D3.4 already established for "at risk"
    itself and for weaknesses, now applied to acknowledgement (D3.5's "how to
    apply"). Keyed by ``str`` student id (not ``uuid.UUID``) because every
    caller here already holds a plain ``str`` id (``history.student_id``,
    ``str(entry.student_id)``) — converting at the one shared boundary
    avoids repeating the conversion at every call site.

    ``student_ids`` narrows the underlying query to a single student for T-05
    (which only ever needs one student's acks); omitted for T-01/T-06, which
    need every ack the caller has recorded across their whole roster in one
    round trip (``AtRiskAckService.load_for_teacher``'s N+1-avoidance).
    """
    raw = ack_service.load_for_teacher(auth.user_id, student_ids=student_ids)
    return {(str(student_id), reason): row for (student_id, reason), row in raw.items()}


# ---------------------------------------------------------------------------
# Overview.
# ---------------------------------------------------------------------------


@router.get("/teacher/overview", response_model=OverviewDTO)
def teacher_overview(
    auth: Annotated[AuthContext, Depends(require_role(*_STAFF_ROLES))],
    service: Annotated[ClassService, Depends(get_class_service)],
    history_store: Annotated[HistoryStoreProtocol, Depends(get_history_store)],
    review_service: Annotated[ReviewService, Depends(get_review_service)],
    ack_service: Annotated[AtRiskAckService, Depends(get_at_risk_ack_service)],
) -> OverviewDTO:
    """Return headline stats plus at-risk students, all from history/analytics.

    Scoped to the union of the caller's own classes (``_visible_students``,
    D3.1) — this route used to call ``history_store.list_students()``, i.e.
    *every* student in the store regardless of owner, and built each at-risk
    student's ``name`` from the raw ``history.student_id`` (a uuid, not a
    human name). Both were the one remaining instance of the cross-tenant leak
    P3.1 fixed everywhere else (``/teacher/classes``, ``/classes/{id}``); this
    closes it and names students from their real ``RosterEntry.display_name``.
    A teacher with no classes gets a coherent empty overview (zeros, an empty
    at-risk list), never a 500 and never someone else's students.

    ``retention`` (lesson-retention minutes) has no backend source and is always
    empty. At-risk students are those flagged by the D3.3 rules engine
    (declining trend / predicted below target / inactive) — see ``_at_risk``.
    Each flag carries its acknowledged state (D3.5) via ``_acknowledgement_index``.
    """
    try:
        visible = _visible_students(service, auth)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    histories = [
        (history_store.load(student_id), entry.display_name)
        for student_id, entry in visible.items()
    ]
    latest = [history.records[-1] for history, _ in histories if history.records]

    average = _mean([r.percentage for r in latest])
    needs_review = _count_review_items(review_service, auth)
    acks = _acknowledgement_index(ack_service, auth)
    at_risk_students = _at_risk(histories, now=datetime.now(UTC), acks=acks)

    stats = [
        StatCardDTO(
            key="Papers graded",
            value=str(sum(len(history.records) for history, _ in histories)),
            unit="papers",
        ),
        StatCardDTO(
            key="Need your eyes",
            value=str(needs_review),
            unit="items",
            valueTone="err" if needs_review else "t1",
            footTone="err" if needs_review else "t2",
        ),
        StatCardDTO(
            key="Group mean",
            value=str(round(average)) if average is not None else "—",
            unit="%",
            footTone="ok",
        ),
        StatCardDTO(
            key="At risk",
            value=str(len(at_risk_students)),
            unit="students",
            valueTone="err" if at_risk_students else "t1",
        ),
    ]
    return OverviewDTO(stats=stats, atRisk=at_risk_students, retention=[])


def _count_review_items(review_service: ReviewService, auth: AuthContext) -> int:
    """Count OPEN review-queue items scoped to the caller's own students (P3.4).

    Previously counted the entire in-process ``papers_store`` with no owner
    filter at all — every teacher saw a global count including every other
    teacher's flagged papers (the inherited P3.3 finding this closes). Now
    sourced from the real, properly-scoped, DB-backed review queue via
    ``ReviewService.list_queue`` (the same tenancy every other stat on this
    route uses).

    **This changes the stat's granularity**, not just its scoping: the old
    count was per-*paper* (a paper with three flagged questions counted once);
    this one is per-*review-queue-item*, i.e. per flagged question per reason
    (that same paper can contribute 2-3+ rows — ``persist_correction`` writes
    one row per (question, reason) pair, so a question flagged for both low
    confidence and plagiarism contributes two rows). "Need your eyes" now
    literally means "how many items are waiting in your review queue" (T-07's
    own framing), which is arguably the more actionable number for a teacher
    about to open that screen — but it is a real behaviour change from the
    old paper-count semantics, called out here rather than silently swapped.

    ``auth.user_id`` is already validated as a UUID by ``_visible_students``
    above (which runs, and raises its 422, before this is called) — no
    redundant validation here.
    """
    return len(review_service.list_queue(auth.user_id, auth.role))


def _at_risk(
    histories: list[tuple[StudentHistory, str]],
    *,
    now: datetime,
    acks: dict[tuple[str, AtRiskReason], AtRiskAcknowledgementRow],
) -> list[AtRiskStudentDTO]:
    """Identify at-risk students via the D3.3 rules engine.

    ``histories`` pairs each student's history with their real
    ``RosterEntry.display_name`` (D3.1/P3.3) — ``AtRiskStudentDTO.name`` used
    to be the raw ``history.student_id`` (a uuid), which this signature makes
    impossible to regress back to.

    Runs ``lemely.core.at_risk.assess_at_risk`` (declining trend / predicted
    below target / inactive, combined with OR) over each student's history. No
    ``target_grade`` is passed — the schema has no target-grade column yet
    (Phase 4 onboarding, D3.3) — so rule 2 is always "not evaluable" in
    production; that is an honest, recorded limitation, not a bug. Supersedes
    the old "grade in {D,E,U} or any negative delta" heuristic, which matched
    none of the three specified rules and carried no reason label.

    ``acks`` (D3.5, P3.4b) is the caller's :func:`_acknowledgement_index`,
    threaded through to :func:`_at_risk_flag_dto` so this route reports the
    identical acknowledged state T-05/T-06 do for the same flag.
    """
    at_risk: list[AtRiskStudentDTO] = []
    for history, display_name in histories:
        if not history.records:
            continue
        assessment = assess_at_risk(history, now=now)
        if not assessment.flags:
            continue
        latest = history.records[-1]
        weakest = min(latest.weak_areas, key=lambda a: a.accuracy, default=None)
        at_risk.append(
            AtRiskStudentDTO(
                name=display_name,
                grade=latest.grade,
                delta=_student_delta(history),
                weakTopic=weakest.topic if weakest is not None else None,
                flags=[
                    _at_risk_flag_dto(flag, student_id=history.student_id, acks=acks)
                    for flag in assessment.flags
                ],
            )
        )
    return at_risk


def _at_risk_flag_dto(
    flag: AtRiskFlag,
    *,
    student_id: str,
    acks: dict[tuple[str, AtRiskReason], AtRiskAcknowledgementRow],
) -> AtRiskFlagDTO:
    """Convert a core ``AtRiskFlag`` to its wire DTO.

    Core evidence models are snake_case (D2.2-style domain naming); this
    module's DTOs are camelCase throughout (mirrors the frontend TS types), so
    the evidence dict keys are translated explicitly rather than passed through
    ``model_dump()`` verbatim.

    **The single point that populates ``acknowledged`` (D3.5, P3.4b).** Every
    teacher-facing caller (the overview, student detail, the at-risk list)
    must route through here rather than checking ``acks`` itself — that is
    exactly the shared-helper discipline D3.5's "how to apply" note demands,
    and the reason this function takes ``student_id``/``acks`` instead of
    staying a pure ``AtRiskFlag -> AtRiskFlagDTO`` converter: bolting the ack
    lookup onto three call sites independently is precisely how "at risk" and
    "weaknesses" each drifted once before (D3.3/D3.4). A flag reads
    acknowledged only when a stored ack exists for
    ``(student_id, flag.reason)`` **and** its ``evidence_fingerprint`` still
    equals :func:`~lemely.core.at_risk.flag_fingerprint` of *this* flag — an
    ack whose evidence has moved on is silently treated as absent, never
    surfaced as stale reassurance.
    """
    ack = acks.get((student_id, flag.reason))
    acknowledged: AtRiskAcknowledgementDTO | None = None
    if ack is not None and ack.evidence_fingerprint == flag_fingerprint(flag):
        acknowledged = AtRiskAcknowledgementDTO(
            acknowledgedBy=str(ack.acknowledged_by),
            acknowledgedAt=ack.acknowledged_at.isoformat(),
            note=ack.note,
        )
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
    return AtRiskFlagDTO(
        reason=flag.reason.value,
        summary=flag.summary,
        evidence=payload,
        acknowledged=acknowledged,
    )


# ---------------------------------------------------------------------------
# Student detail (teacher view) — T-05.
# ---------------------------------------------------------------------------


def _parse_recorded_at(value: str) -> datetime | None:
    """Defensively parse a ``PaperRecord.recorded_at`` ISO string.

    A private per-module copy, matching the existing convention: both
    ``lemely.core.at_risk`` and ``lemely.core.class_analytics`` (and
    ``lemely.db.history_repo``/``lemely.db.attempt_repo``) each carry their own
    copy of this exact defensive-parse rather than reaching across modules for
    a leading-underscore helper.
    """
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed


def _subject_predictions(history: StudentHistory) -> list[SubjectPredictionDTO]:
    """Group a student's history by subject and report the latest grade/pct.

    ``predictedGrade`` is the student's latest recorded grade for that
    subject — the same domain notion of "predicted grade"
    ``lemely.core.at_risk`` already uses for its below-target rule
    (``history.records[-1].grade``), not a second, differently-computed
    forecast that could disagree with the at-risk engine's own reading of the
    same data.
    """
    by_subject: dict[str, list[PaperRecord]] = {}
    for record in history.records:
        by_subject.setdefault(record.metadata.subject_code, []).append(record)
    return [
        SubjectPredictionDTO(
            subjectCode=code,
            predictedGrade=records[-1].grade,
            latestPercentage=records[-1].percentage,
            paperCount=len(records),
        )
        for code, records in sorted(by_subject.items())
    ]


def _paper_id(record: PaperRecord) -> str:
    """Human paper identity: ``"0625/32"`` (subject/paper+variant)."""
    m = record.metadata
    return f"{m.subject_code}/{m.paper_number}{m.paper_variant}"


def _attempt_dto(record: PaperRecord) -> AttemptDTO:
    """Convert one recorded paper into its T-05 attempt-history row."""
    m = record.metadata
    return AttemptDTO(
        paperId=_paper_id(record),
        subjectCode=m.subject_code,
        paperNumber=m.paper_number,
        paperVariant=m.paper_variant,
        awardedMarks=record.awarded_marks,
        maximumMarks=record.maximum_marks,
        percentage=record.percentage,
        grade=record.grade,
        recordedAt=record.recorded_at,
    )


def _student_engagement_dto(history: StudentHistory, *, now: datetime) -> StudentEngagementDTO:
    """This student's own activity stats, purely from ``recorded_at`` values."""
    if not history.records:
        return StudentEngagementDTO(totalPapers=0, lastActiveAt=None, daysSinceLastSubmission=None)
    last = history.records[-1]
    last_active = _parse_recorded_at(last.recorded_at)
    days_since = (now - last_active).days if last_active is not None else None
    return StudentEngagementDTO(
        totalPapers=len(history.records),
        lastActiveAt=last.recorded_at,
        daysSinceLastSubmission=days_since,
    )


def _student_detail_dto(
    entry: RosterEntry,
    history: StudentHistory,
    *,
    now: datetime,
    acks: dict[tuple[str, AtRiskReason], AtRiskAcknowledgementRow],
) -> StudentDetailDTO:
    """Build the T-05 student-detail DTO from one student's real history.

    Reuses ``aggregate_weaknesses_from_history`` (weaknesses),
    ``assess_at_risk``/``_at_risk_flag_dto`` (at-risk status — never a second,
    re-implemented translation), and this module's own subject/attempt/
    engagement helpers. Integrity signals are deliberately absent: see the
    route docstring. ``acks`` (D3.5, P3.4b) threads the caller's
    :func:`_acknowledgement_index` through to ``_at_risk_flag_dto`` so this
    screen reports the identical acknowledged state T-01/T-06 do.
    """
    assessment = assess_at_risk(history, now=now)
    student_id = str(entry.student_id)
    return StudentDetailDTO(
        studentId=student_id,
        displayName=entry.display_name,
        subjects=_subject_predictions(history),
        attempts=[_attempt_dto(r) for r in reversed(history.records)],
        weaknesses=[
            StudentWeaknessDTO(
                topic=w.topic,
                lostMarks=w.lost_marks,
                maximumMarks=w.maximum_marks,
                accuracy=w.accuracy,
                questionIds=w.question_ids,
            )
            for w in aggregate_weaknesses_from_history(history).weak_areas
        ],
        trend=[
            StudentTrendPointDTO(recordedAt=r.recorded_at, percentage=r.percentage)
            for r in history.records
        ],
        isAtRisk=assessment.is_at_risk,
        atRiskFlags=[
            _at_risk_flag_dto(flag, student_id=student_id, acks=acks) for flag in assessment.flags
        ],
        engagement=_student_engagement_dto(history, now=now),
    )


@router.get("/teacher/students/{student_id}", response_model=StudentDetailDTO)
def teacher_student_detail(
    student_id: str,
    auth: Annotated[AuthContext, Depends(require_role(*_STAFF_ROLES))],
    service: Annotated[ClassService, Depends(get_class_service)],
    history_store: Annotated[HistoryStoreProtocol, Depends(get_history_store)],
    ack_service: Annotated[AtRiskAckService, Depends(get_at_risk_ack_service)],
) -> StudentDetailDTO:
    """Return T-05's full student detail for one student (P3.3).

    Subjects and predicted grades, full attempt history, weakness list with
    evidence, this student's own trend series, at-risk status with reasons and
    evidence (reusing ``assess_at_risk``/``_at_risk_flag_dto``), and
    activity/engagement. Each at-risk flag's acknowledged state (D3.5,
    P3.4b) is populated identically to T-01/T-06.

    **Authz is the whole point of this route.** A teacher/school_admin may see
    a student ONLY if that student is enrolled in one of the caller's own
    classes (``_visible_students`` — the union of every roster the caller may
    see, D3.1). A student who exists but is in nobody's class the caller
    owns/administers is a 403; a student id matching no user at all is a 404;
    a malformed (non-UUID) id is a clean 422. platform_admin always sees no
    classes (``ClassService.list_classes``), so this is always 403 for them —
    no super-role bypass (D1.6/D1.10).

    Note honestly what that 403-vs-404 split *is*: a user-existence oracle. An
    authenticated staff caller who probes an id learns whether it belongs to a
    real user, even when they may not see that user. This is a deliberate,
    accepted trade — it matches the class routes' established behaviour
    (``get_class``), and user ids are random 122-bit UUIDs, so enumerating
    them is infeasible rather than merely discouraged. It is recorded here
    because the alternative (collapsing both to 404) is the textbook advice,
    and a future reader should see that the deviation was a decision, not an
    oversight. No student *data* crosses a tenancy boundary either way.

    **Integrity signals are deliberately omitted from the response**, not
    stubbed as an always-empty field: a persisted :class:`PaperRecord` carries
    only totals, weak-areas, and metadata, never the per-question answers
    that plagiarism/AI-content detection needs (those checks run only in the
    live, in-process ``/papers/{id}/grade`` flow, whose paper store is keyed by
    an ephemeral paper id, not yet a verified real-student identity — see
    ``upload_paper``'s docstring). There is nothing honest to compute here.
    """
    try:
        visible = _visible_students(service, auth)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    entry = visible.get(student_id)
    if entry is not None:
        history = history_store.load(student_id)
        acks = _acknowledgement_index(ack_service, auth, student_ids=[student_id])
        return _student_detail_dto(entry, history, now=datetime.now(UTC), acks=acks)
    try:
        exists = service.user_exists(student_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not exists:
        raise HTTPException(status_code=404, detail=f"Unknown student: {student_id}")
    raise HTTPException(
        status_code=403, detail=f"Student {student_id} is not in any of the caller's classes"
    )


# ---------------------------------------------------------------------------
# At-risk list — T-06.
# ---------------------------------------------------------------------------


def _grade_severity_rank(grade: str) -> int:
    """Position of ``grade`` on the ladder (0 = A*, higher = worse).

    An unrecognised grade defensively ranks as the mildest possible (``-1``),
    mirroring ``lemely.core.at_risk``'s "unrecognised = not fired" judgment
    call rather than crashing the sort.
    """
    return _GRADE_ORDER.index(grade) if grade in _GRADE_ORDER else -1


def _at_risk_severity_key(entry: AtRiskListEntryDTO) -> tuple[int, int]:
    """Sort key for T-06: most flags first, then worst grade first.

    Documented severity definition (per the P3.3 brief): **flag count
    descending**, then **worst latest grade** (furthest down
    ``GRADE_ORDER``) **first**. A student flagged by all three D3.3 rules
    outranks one flagged by one rule regardless of grade; among
    equally-flagged students, the one with the worse grade surfaces first.
    """
    return (-len(entry.flags), -_grade_severity_rank(entry.grade))


@router.get("/teacher/at-risk", response_model=AtRiskListDTO)
def teacher_at_risk_list(
    auth: Annotated[AuthContext, Depends(require_role(*_STAFF_ROLES))],
    service: Annotated[ClassService, Depends(get_class_service)],
    history_store: Annotated[HistoryStoreProtocol, Depends(get_history_store)],
    ack_service: Annotated[AtRiskAckService, Depends(get_at_risk_ack_service)],
    reason: str | None = None,
    acknowledged: bool | None = None,
) -> AtRiskListDTO:
    """Return every flagged student across the caller's own classes (T-06).

    Reuses ``assess_at_risk`` (never a fourth at-risk heuristic) over each
    roster entry in each class the caller owns/administers — never a student
    outside that scope, and never every student in the store. ``reason``
    (optional query param) filters to students carrying at least one flag
    whose ``AtRiskReason.value`` matches; an unrecognised reason value simply
    yields no matches, never a 500. Sorted by severity — see
    ``_at_risk_severity_key`` for the exact, documented definition.

    ``acknowledged`` (P3.4b/D3.5) filters to students carrying at least one
    flag whose acknowledged state (see ``_at_risk_flag_dto``) matches; a
    student flagged by both an acknowledged and an unacknowledged reason
    passes either filter, and — mirroring ``reason``'s existing
    entry-vs-flag granularity — the ``flags`` list on a matching entry still
    carries *every* flag for that student, not just the matching one (D3.5:
    an acknowledged flag is never removed from a response, only tagged).
    Omitting the parameter returns both states, unfiltered.
    """
    try:
        rows = service.list_classes(auth.user_id, auth.role)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    now = datetime.now(UTC)
    acks = _acknowledgement_index(ack_service, auth)
    entries: list[AtRiskListEntryDTO] = []
    for row in rows:
        roster = service.roster(auth.user_id, auth.role, row.class_id)
        for roster_entry in roster:
            student_id = str(roster_entry.student_id)
            history = history_store.load(student_id)
            if not history.records:
                continue
            assessment = assess_at_risk(history, now=now)
            if not assessment.flags:
                continue
            if reason is not None and reason not in {f.reason.value for f in assessment.flags}:
                continue
            flags_dto = [
                _at_risk_flag_dto(flag, student_id=student_id, acks=acks)
                for flag in assessment.flags
            ]
            if acknowledged is not None and not any(
                (f.acknowledged is not None) == acknowledged for f in flags_dto
            ):
                continue
            entries.append(
                AtRiskListEntryDTO(
                    studentId=student_id,
                    displayName=roster_entry.display_name,
                    classId=str(row.class_id),
                    className=row.name,
                    grade=history.records[-1].grade,
                    flags=flags_dto,
                )
            )
    entries.sort(key=_at_risk_severity_key)
    return AtRiskListDTO(students=entries)


# ---------------------------------------------------------------------------
# Acknowledge / un-acknowledge an at-risk flag — T-06 (P3.4b, D3.5).
# ---------------------------------------------------------------------------


@router.post(
    "/teacher/at-risk/{student_id}/acknowledge",
    response_model=AtRiskFlagDTO,
)
def acknowledge_at_risk_flag(
    student_id: str,
    body: AcknowledgeAtRiskRequestDTO,
    auth: Annotated[AuthContext, Depends(require_role(*_STAFF_ROLES))],
    service: Annotated[ClassService, Depends(get_class_service)],
    history_store: Annotated[HistoryStoreProtocol, Depends(get_history_store)],
    ack_service: Annotated[AtRiskAckService, Depends(get_at_risk_ack_service)],
) -> AtRiskFlagDTO:
    """Acknowledge one currently-firing at-risk flag with an optional note (T-06).

    Upserts: acknowledging a reason already acknowledged just refreshes the
    note and re-pins the evidence fingerprint to whatever is firing right now
    (harmless — it is already firing, by construction of this route, so the
    fingerprint cannot change under it in the same request).

    Authz mirrors ``teacher_student_detail``: a student outside the union of
    the caller's own classes is a 403; an id matching no user anywhere is a
    404; a malformed (non-UUID) id is a clean 422 (see that route's docstring
    for the full 403-vs-404 rationale, which applies identically here).

    **Rejects acknowledging a reason that is not currently firing (422).**
    Flags are derived, not stored (D3.3) — there is no persistent flag to
    "acknowledge" unless ``assess_at_risk`` is, right now, actually raising
    ``body.reason`` for this student. This also rejects an unrecognised
    ``reason`` string (not one of ``AtRiskReason``'s values) with the same
    422, since by definition it cannot be firing.
    """
    try:
        visible = _visible_students(service, auth)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    entry = visible.get(student_id)
    if entry is None:
        try:
            exists = service.user_exists(student_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if not exists:
            raise HTTPException(status_code=404, detail=f"Unknown student: {student_id}")
        raise HTTPException(
            status_code=403,
            detail=f"Student {student_id} is not in any of the caller's classes",
        )

    try:
        reason_enum = AtRiskReason(body.reason)
    except ValueError as exc:
        raise HTTPException(
            status_code=422, detail=f"Unknown at-risk reason: {body.reason!r}"
        ) from exc

    history = history_store.load(student_id)
    assessment = assess_at_risk(history, now=datetime.now(UTC))
    flag = next((f for f in assessment.flags if f.reason == reason_enum), None)
    if flag is None:
        raise HTTPException(
            status_code=422,
            detail=f"Reason {reason_enum.value!r} is not currently firing for this student",
        )

    fingerprint = flag_fingerprint(flag)
    try:
        ack_service.acknowledge(
            auth.user_id,
            auth.role,
            student_id,
            reason_enum,
            fingerprint,
            note=body.note,
        )
    except AtRiskAckOwnershipError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    acks = _acknowledgement_index(ack_service, auth, student_ids=[student_id])
    return _at_risk_flag_dto(flag, student_id=student_id, acks=acks)


@router.delete(
    "/teacher/at-risk/{student_id}/acknowledge/{reason}",
    status_code=204,
)
def unacknowledge_at_risk_flag(
    student_id: str,
    reason: str,
    auth: Annotated[AuthContext, Depends(require_role(*_STAFF_ROLES))],
    service: Annotated[ClassService, Depends(get_class_service)],
    ack_service: Annotated[AtRiskAckService, Depends(get_at_risk_ack_service)],
) -> None:
    """Remove an acknowledgement (T-06). Idempotent.

    A flag with no stored acknowledgement (or an already-unacknowledged one)
    still returns 204. Authz mirrors ``acknowledge_at_risk_flag``: a student outside the
    caller's classes is a 403. Does not require the reason to currently be
    firing (unlike the POST) — un-acknowledging is always safe to attempt,
    even for a reason that has since stopped firing entirely (e.g. the
    student is no longer inactive); there is nothing left to protect by
    rejecting it.
    """
    try:
        visible = _visible_students(service, auth)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    entry = visible.get(student_id)
    if entry is None:
        try:
            exists = service.user_exists(student_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if not exists:
            raise HTTPException(status_code=404, detail=f"Unknown student: {student_id}")
        raise HTTPException(
            status_code=403,
            detail=f"Student {student_id} is not in any of the caller's classes",
        )

    try:
        reason_enum = AtRiskReason(reason)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Unknown at-risk reason: {reason!r}") from exc

    try:
        ack_service.unacknowledge(auth.user_id, auth.role, student_id, reason_enum)
    except AtRiskAckOwnershipError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
