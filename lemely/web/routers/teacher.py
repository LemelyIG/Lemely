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
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import ValidationError

from lemely.core.analytics import (
    aggregate_weaknesses_from_history,
    compare_performance,
)
from lemely.core.generation import GeneratedQuestion, GeneratedQuiz
from lemely.core.history import (
    HistoryStoreProtocol,
    PaperRecord,
    StudentHistory,
    now_iso,
)
from lemely.core.loose_schemas import MarkScheme
from lemely.core.schemas import (
    AccuracyReport,
    ExamMetadata,
    WeaknessReport,
)
from lemely.db.models.enums import Role
from lemely.io.gemini import GeminiClient
from lemely.io.question_generation import QuestionGenerator
from lemely.io.scan_metadata import ScanMetadataExtractor
from lemely.io.teacher_quiz import TeacherQuizBuilder
from lemely.runtime.config import Settings
from lemely.runtime.events import EventType, bus
from lemely.web.deps import (
    get_gemini_client,
    get_history_store,
    get_settings,
    require_role,
)
from lemely.web.jobs import registry
from lemely.web.schemas import (
    question_to_dto,
    weak_area_to_dto,
)
from lemely.web.schemas_teacher import (
    AtRiskStudentDTO,
    BatchTabDTO,
    ClassDetailDTO,
    ClassListDTO,
    ClassSummaryDTO,
    DetectedFieldDTO,
    DistributionBarDTO,
    GradingQueueDTO,
    MasteryRowDTO,
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

# Every teacher-portal route is staff-only. Gating at the router level means a
# 401 (no/invalid token) or 403 (student/parent) is enforced uniformly and any
# future teacher route inherits the guard by construction. Per-teacher tenancy
# (a teacher only seeing their own classes) is deferred to when these routes move
# off the shared interim HistoryStore onto the DB-backed class model (D1.6).
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
# the question is surfaced in the teacher review queue. Mirrors the domain
# threshold used across the pipeline (``confidence_band_for_score`` HIGH cut-off).
_REVIEW_CONFIDENCE = 0.90

_GRADE_ORDER = ["A*", "A", "B", "C", "D", "E", "U"]
_AT_RISK_GRADES = {"D", "E", "U"}


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
    """Return a sandbox-safe basename for a client-supplied upload filename.

    The client filename is *never* trusted as a path: only its basename is kept,
    any traversal / separator components are dropped, and an empty or dangerous
    result falls back to a server-chosen name. Callers still join the result to a
    ``paper_id``-namespaced directory, so the returned value can only ever name a
    file *inside* that directory.
    """
    if not filename:
        return fallback
    base = Path(filename).name
    if not base or base in {".", ".."}:
        return fallback
    return base


def _write_upload_capped(data: bytes, dest: Path) -> None:
    """Write ``data`` to ``dest`` in chunks, raising 413 past the size cap."""
    if len(data) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Upload exceeds {_MAX_UPLOAD_BYTES} byte limit.",
        )
    with dest.open("wb") as fh:
        for start in range(0, len(data), _UPLOAD_CHUNK_BYTES):
            fh.write(data[start : start + _UPLOAD_CHUNK_BYTES])


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


def _existing_questions(settings: Settings) -> list[GeneratedQuestion]:
    """Load the teacher's existing generated-question pool from disk.

    Reads ``output_dir/questions/*.json`` (each a :class:`GeneratedQuiz`). Returns
    an empty list when the pool directory is absent — the quiz builder then relies
    purely on generation.
    """
    pool_dir = settings.paths.output_dir / "questions"
    if not pool_dir.exists():
        return []
    questions: list[GeneratedQuestion] = []
    for path in sorted(pool_dir.glob("*.json")):
        try:
            quiz = GeneratedQuiz.model_validate_json(path.read_text(encoding="utf-8"))
        except (ValidationError, OSError):
            continue
        questions.extend(quiz.questions)
    return questions


@router.get("/quizzes/pools", response_model=QuizPoolsDTO)
def quiz_pools(
    settings: Annotated[Settings, Depends(get_settings)],
) -> QuizPoolsDTO:
    """Return the quiz question-source pools with live counts.

    ``past`` counts existing questions carrying source ids (from parsed papers);
    ``mine`` counts uploaded questions without source ids; ``ai`` is a generative
    pool (count 0 until questions are generated). All counts are data-backed.
    """
    existing = _existing_questions(settings)
    past = sum(1 for q in existing if q.source_question_ids)
    mine = sum(1 for q in existing if not q.source_question_ids)
    return QuizPoolsDTO(
        pools=[
            QuestionPoolDTO(
                key="past",
                label="Past papers",
                detail="CAIE official, from parsed papers",
                count=past,
            ),
            QuestionPoolDTO(
                key="ai",
                label="AI-generated",
                detail="Stylistically matched to CAIE",
                count=0,
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
    *,
    subject_code: str,
    count: int,
    topics: list[str] | None,
) -> GeneratedQuiz:
    """Assemble a quiz via :class:`TeacherQuizBuilder` (select-then-generate).

    Generation is only attempted when an API key is configured (mirroring
    :func:`upload_paper`); without one the quiz is built from the existing
    question pool alone so the endpoint degrades to a partial result instead of
    raising an unhandled 500 on the default no-key state. A runtime generation
    failure is surfaced as a clean 503, never a 500.
    """
    aggregate = _aggregate_history_weaknesses(history_store)
    existing = _existing_questions(settings)
    resolved_subject = subject_code or _infer_subject_code(history_store) or "0000"

    if settings.gemini_api_key is None:
        # No generation possible: return whatever the existing pool can supply.
        builder = TeacherQuizBuilder(
            QuestionGenerator(gemini_client),
            existing_questions=existing,
        )
        return builder.build(
            resolved_subject,
            WeaknessReport(weak_areas=[]),  # empty → builder skips generation
            count=count,
            topics=topics,
        )

    builder = TeacherQuizBuilder(
        QuestionGenerator(gemini_client),
        existing_questions=existing,
    )
    try:
        return builder.build(
            resolved_subject,
            aggregate,
            count=count,
            topics=topics,
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
    settings: Annotated[Settings, Depends(get_settings)],
    history_store: Annotated[HistoryStoreProtocol, Depends(get_history_store)],
    gemini_client: Annotated[GeminiClient, Depends(get_gemini_client)],
    subject_code: str = "",
    count: int = 4,
    topics: list[str] | None = None,
) -> QuizPreviewDTO:
    """Preview a quiz assembled from existing questions, topping up via generation."""
    quiz = _build_quiz(
        settings,
        history_store,
        gemini_client,
        subject_code=subject_code,
        count=count,
        topics=topics,
    )
    return _quiz_to_preview(quiz)


@router.post("/quizzes/generate", response_model=QuizPreviewDTO)
def quiz_generate(
    settings: Annotated[Settings, Depends(get_settings)],
    history_store: Annotated[HistoryStoreProtocol, Depends(get_history_store)],
    gemini_client: Annotated[GeminiClient, Depends(get_gemini_client)],
    subject_code: str = "",
    count: int = 5,
    topics: list[str] | None = None,
) -> QuizPreviewDTO:
    """Generate a full quiz and persist it to the teacher's question pool on disk."""
    quiz = _build_quiz(
        settings,
        history_store,
        gemini_client,
        subject_code=subject_code,
        count=count,
        topics=topics,
    )
    pool_dir = settings.paths.output_dir / "questions"
    pool_dir.mkdir(parents=True, exist_ok=True)
    out_path = pool_dir / f"quiz_{now_iso().replace(':', '-')}.json"
    out_path.write_text(quiz.model_dump_json(indent=2), encoding="utf-8")
    return _quiz_to_preview(quiz)


# ---------------------------------------------------------------------------
# Classes.
# ---------------------------------------------------------------------------


def _student_row(history: StudentHistory) -> StudentRowDTO | None:
    """Build a roster row from a student's history, or ``None`` if empty."""
    if not history.records:
        return None
    latest = history.records[-1]
    weakest = min(
        latest.weak_areas,
        key=lambda a: a.accuracy,
        default=None,
    )
    return StudentRowDTO(
        name=history.student_id,
        grade=latest.grade,
        mark=f"{latest.awarded_marks}/{latest.maximum_marks}",
        delta=_student_delta(history),
        weakTopic=weakest.topic if weakest is not None else None,
        gradeAtRisk=latest.grade in _AT_RISK_GRADES,
    )


@router.get("/teacher/classes", response_model=ClassListDTO)
def list_classes(
    history_store: Annotated[HistoryStoreProtocol, Depends(get_history_store)],
) -> ClassListDTO:
    """Return the (single, implicit) class summary derived from all history.

    The domain has no class/roster model yet, so every student with history is
    treated as one cohort. ``average`` is the mean latest percentage across
    students; empty history yields an empty class list.
    """
    latest = _latest_records(history_store)
    if not latest:
        return ClassListDTO(classes=[])
    average = _mean([r.percentage for r in latest])
    return ClassListDTO(
        classes=[
            ClassSummaryDTO(
                id="all",
                label="All students",
                studentCount=len(latest),
                average=average,
            )
        ]
    )


@router.get("/classes/{class_id}", response_model=ClassDetailDTO)
def get_class(
    class_id: str,
    history_store: Annotated[HistoryStoreProtocol, Depends(get_history_store)],
) -> ClassDetailDTO:
    """Return mastery, grade distribution, and the roster for a class.

    Mastery is per-topic accuracy across the cohort's aggregate weaknesses;
    distribution counts students by latest grade; the roster is one row per
    student. National benchmarks and hours-saved narratives have no backend
    source and are omitted / left ``None``.
    """
    student_ids = history_store.list_students()
    histories = [history_store.load(sid) for sid in student_ids]
    latest = [h.records[-1] for h in histories if h.records]

    rows = [row for h in histories if (row := _student_row(h)) is not None]

    aggregate = _aggregate_history_weaknesses(history_store)
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
        StatCardDTO(key="Students", value=str(len(latest)), unit="tracked"),
        StatCardDTO(
            key="At risk",
            value=str(at_risk),
            unit="students",
            valueTone="err" if at_risk else "t1",
            footTone="err" if at_risk else "t2",
        ),
    ]

    return ClassDetailDTO(
        id=class_id,
        label="All students",
        stats=stats,
        mastery=mastery,
        distribution=distribution,
        students=rows,
    )


# ---------------------------------------------------------------------------
# Overview.
# ---------------------------------------------------------------------------


@router.get("/teacher/overview", response_model=OverviewDTO)
def teacher_overview(
    history_store: Annotated[HistoryStoreProtocol, Depends(get_history_store)],
) -> OverviewDTO:
    """Return headline stats plus at-risk students, all from history/analytics.

    ``retention`` (lesson-retention minutes) has no backend source and is always
    empty. At-risk students are those whose grade is D/E/U or whose latest paper
    fell versus their prior same-paper attempt.
    """
    student_ids = history_store.list_students()
    histories = [history_store.load(sid) for sid in student_ids]
    latest = [h.records[-1] for h in histories if h.records]

    average = _mean([r.percentage for r in latest])
    needs_review = _count_review_papers()
    at_risk_students = _at_risk(histories)

    stats = [
        StatCardDTO(
            key="Papers graded",
            value=str(sum(len(h.records) for h in histories)),
            unit="papers",
        ),
        StatCardDTO(
            key="Need your eyes",
            value=str(needs_review),
            unit="papers",
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


def _count_review_papers() -> int:
    """Count stored papers currently flagged for teacher review."""
    return sum(
        1
        for e in papers_store.all()
        if e.report is not None and e.report.correction.needs_teacher_review
    )


def _at_risk(histories: list[StudentHistory]) -> list[AtRiskStudentDTO]:
    """Identify at-risk students (low grade or falling trajectory) from history."""
    at_risk: list[AtRiskStudentDTO] = []
    for history in histories:
        if not history.records:
            continue
        latest = history.records[-1]
        delta = _student_delta(history)
        falling = delta is not None and delta < 0
        if latest.grade in _AT_RISK_GRADES or falling:
            weakest = min(latest.weak_areas, key=lambda a: a.accuracy, default=None)
            at_risk.append(
                AtRiskStudentDTO(
                    name=history.student_id,
                    grade=latest.grade,
                    delta=delta,
                    weakTopic=weakest.topic if weakest is not None else None,
                )
            )
    return at_risk
