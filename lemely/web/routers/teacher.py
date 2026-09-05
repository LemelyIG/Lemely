"""Teacher portal (grading console) endpoints.

Owned by the teacher-portal worker; extends the app factory's mounted router in
place (``app.py`` is never edited). Every endpoint computes its payload from real
core logic — the extraction/grading pipeline in :mod:`lemely.web.services.grading`,
the :class:`HistoryStore`, the analytics helpers, parsed mark schemes, and the
deterministic scheme parser. Screen fields with no backend source (attendance,
retention minutes, hand-written narratives) are returned empty / omitted; see
:mod:`lemely.web.schemas_teacher` for the per-field provenance docs.

Papers uploaded through the console are an object in
:class:`~lemely.io.storage.StorageBackend` plus a row in ``teacher_papers``
(:class:`~lemely.db.teacher_paper_repo.TeacherPaperRepository`, spec §4.2):
no state lives in this process, so any Cloud Run instance can answer a polled
route and a restart loses nothing mid-run.
"""

# FastAPI ``Depends``/``response_model`` and pydantic model construction need these
# type imports at runtime; TC00x would move them into ``TYPE_CHECKING`` and break
# dependency injection. (The per-file-ignore in pyproject.toml handles this.)
from __future__ import annotations

import queue
import tempfile
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Literal

import anyio
import structlog
from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile

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
    grade_bearing,
    is_grade_bearing,
    is_paper,
    latest_grade_bearing,
)
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
from lemely.db.history_repo import parse_user_id
from lemely.db.models.enums import SESSION_MONTH_LABELS, QuestionSource, Role, UploadStatus
from lemely.db.question_bank_repo import (
    QuestionBankRow,
    QuestionBankService,
    generated_questions_to_bank_rows,
)
from lemely.db.scheme_corpus_repo import SchemeCorpusRepository, SchemeCorpusRow
from lemely.db.teacher_paper_repo import TeacherPaperRepository, TeacherPaperRow

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
from lemely.db.review_repo import ReviewService
from lemely.db.student_profile_repo import StudentProfileService
from lemely.io.gemini import GeminiClient
from lemely.io.question_generation import QuestionGenerator
from lemely.io.scan_metadata import ScanMetadataExtractor
from lemely.io.storage import StorageBackend, StorageObjectNotFoundError
from lemely.io.teacher_quiz import TeacherQuizBuilder
from lemely.runtime.config import Settings
from lemely.runtime.events import Event, EventType, bus, current_run_id
from lemely.web.deps import (
    AuthContext,
    get_at_risk_ack_service,
    get_auth_context,
    get_class_service,
    get_gemini_client,
    get_history_store,
    get_question_bank_service,
    get_review_service,
    get_scheme_corpus_repo,
    get_settings,
    get_storage_backend,
    get_student_profile_service,
    get_teacher_paper_repo,
    require_role,
)
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
    RecentActivityDTO,
    SchemeListDTO,
    SchemeRowDTO,
    StatCardDTO,
    StudentRowDTO,
    UploadResponseDTO,
)
from lemely.web.upload_utils import check_upload_cap, safe_upload_name

log = structlog.get_logger(__name__)

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
# Papers: background grading against the repository and the storage seam.
# ---------------------------------------------------------------------------

#: The phases :func:`_run_grading_job` walks, in the order it walks them, paired
#: with the console's label for each. ``TeacherPaperRow.stage`` always holds one
#: of these ids; :func:`_live_pipeline_steps` turns it into the Pipeline panel's
#: rows. Ingestion is not here because it is finished before the job starts.
_JOB_STAGES: tuple[tuple[str, str], ...] = (
    ("detect", "Exam details read"),
    ("scheme", "Mark scheme parsed"),
    ("extract", "Handwriting read"),
    ("mark", "Questions marked"),
)

# One worker so Queued means queued — a paper genuinely waiting behind another
# on this instance (DS13). Raising it is a one-line change now that per-run
# event scoping (spec §4.5) is in place: `_run_grading_job` sets
# `current_run_id` itself at the top of its own call, so two jobs on two pool
# threads scope correctly regardless of worker count. The trap for whoever
# raises this is a level down, not here: if raising it also means splitting
# one paper's own work across threads (a `ThreadPoolExecutor` or `Thread`
# added inside `lemely/io/gemini.py`, `io/correction_ai.py` or
# `io/answer_extraction.py`, none of which exist today), every submitted piece
# of work must run under `contextvars.copy_context()` — a bare `.submit()`
# does not propagate `current_run_id` into its worker thread, and an event
# published without it carries no run id, which `EventBus.publish` then
# delivers to *every* concurrent run's queue (see `lemely/web/sse.py`'s module
# docstring).
_grading_pool: ThreadPoolExecutor = ThreadPoolExecutor(
    max_workers=1, thread_name_prefix="lemely-grading"
)

#: How long :func:`_track_progress` blocks on its queue before re-checking its
#: stop flag. Bounds tracker shutdown latency; it is not a progress-poll rate,
#: since a queued event wakes the ``get`` immediately.
_TRACKER_POLL_SECONDS = 0.2

#: Shown (with a retry re-enabled) for a ``processing`` row whose ``updated_at``
#: has not moved in ``stale_after`` — the worker that owned it died (a crash, a
#: deploy) without a chance to call :meth:`~TeacherPaperRepository.fail`.
_LOST_RUN_ERROR = "This run was lost when its server instance stopped. Re-run marking to try again."


def _viewer(auth: AuthContext) -> tuple[uuid.UUID, Role]:
    """The caller's id and platform role, parsed off the validated token."""
    return parse_user_id(auth.user_id), Role(auth.role)


def _require_paper(
    repo: TeacherPaperRepository, auth: AuthContext, paper_id: str
) -> TeacherPaperRow:
    """The visible paper or a 404 — unknown and not-visible are indistinguishable.

    Routed through :meth:`TeacherPaperRepository.get_visible` (DS11), never
    :meth:`~TeacherPaperRepository.get` — the latter has no visibility filter
    at all and exists only for the background worker acting on a run it
    already claimed, not for a request made by a person.
    """
    try:
        target = uuid.UUID(paper_id)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Unknown paper: {paper_id}") from None
    viewer_id, viewer_role = _viewer(auth)
    row = repo.get_visible(target, viewer_id=viewer_id, viewer_role=viewer_role)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Unknown paper: {paper_id}")
    return row


def _download_to(storage: StorageBackend, bucket: str, key: str, dest: Path) -> Path:
    """Materialise one object as a file for the pipeline; the caller owns ``dest``'s directory.

    Runs on the grading pool's own thread, never the event loop, so — unlike
    the upload routes' ``storage.upload`` calls — this blocking read needs no
    ``anyio.to_thread`` wrapping.
    """
    dest.write_bytes(storage.download(bucket, key))
    return dest


def _row_kind(row: TeacherPaperRow) -> PaperKind:
    """Classify a paper row for the console: ``graded``/``review`` only once complete.

    A ``report_json`` left over from a prior run does not, by itself, make a
    row ``graded`` — ``claim_run`` does not clear it, so a paper being
    regraded keeps its old report while ``status`` moves to ``processing``.
    Requiring ``status is complete`` alongside the report is what keeps a
    regrade in flight from reading as already finished.
    """
    if row.report is not None and row.status is UploadStatus.complete:
        return _paper_kind(row.report)
    if row.stale or row.status is UploadStatus.failed:
        return "failed"
    return "processing" if row.status is UploadStatus.processing else "queued"


def _row_error(row: TeacherPaperRow) -> str | None:
    """The reason to show for a row, substituting the lost-run copy when stale."""
    return _LOST_RUN_ERROR if row.stale else row.error


def _paper_label(row: TeacherPaperRow) -> str:
    """Human name for a paper card.

    ``Paper 3 V1 May/June 2020 - 2026-08-12`` once detection (or a completed
    grade) has produced metadata: what the paper *is*, plus the date it was
    uploaded so repeat attempts at the same paper stay distinguishable.

    Until then, the teacher's own filename — the one thing about this upload
    they already recognise. Never the raw id.
    """
    metadata = row.metadata or (row.report.correction.metadata if row.report else None)
    if metadata is None:
        return row.original_filename or str(row.id)
    session: str = metadata.session_month
    if metadata.session_year is not None:
        session = f"{session} {metadata.session_year}"
    return (
        f"Paper {metadata.paper_number} V{metadata.paper_variant} "
        f"{session} - {row.created_at.date().isoformat()}"
    )


def _track_progress(
    repo: TeacherPaperRepository,
    paper_id: uuid.UUID,
    q: queue.SimpleQueue[Event | None],
    stop: threading.Event,
) -> None:
    """Drain bus events onto the row so a polling client can see how far a run has got.

    The pipeline publishes ``EXTRACTION_PROGRESS`` / ``MARKING_PROGRESS`` with
    ``index``/``total`` as it walks the question list. Mirroring them onto the
    row is what lets a teacher who reloads the page mid-run still see how far
    the run has got: a client only reaches this state through polling, and a
    reloaded page has, by definition, missed everything published before it
    asked again.

    Scoped to this run by the queue itself (``q`` is
    ``bus.subscribe_queue(f"teacher:{paper_id}")`` in :func:`_run_grading_job`,
    matching the ``current_run_id`` that call sets), never by the event
    payload (spec §4.5, DS10): neither progress event type carries a
    ``paper_id`` at all — ``lemely.io.answer_extraction`` and
    ``lemely.io.correction_ai`` publish per-question progress with no run
    identity attached — so a ``payload["paper_id"] == str(paper_id)`` filter
    was never viable here and this function never tried one. Two concurrent
    runs — on this instance, or, once :data:`_grading_pool` grows past one
    worker (DS13), on two — each get their own scoped queue and so cannot mix
    counters, whatever payload shape either publisher emits.

    Shutdown is the caller's ``stop`` flag, deliberately **not** the queue's
    ``None`` sentinel. Scoping means a foreign run's ``publish_done()`` no
    longer reaches this queue in practice — but this loop still does not lean
    on that: it treats ``None`` as a no-op rather than a stop condition, both
    because :meth:`~lemely.runtime.events.EventBus.publish_done` also still
    reaches every *unscoped* subscriber (which is what this function is
    directly exercised against in tests), and because relying on the sentinel
    at all would be exactly the coupling this task removed.

    Runs on its own daemon thread for the lifetime of one job.
    """
    while not stop.is_set():
        try:
            event = q.get(timeout=_TRACKER_POLL_SECONDS)
        except queue.Empty:
            continue
        if event is None:
            continue
        if event.type is EventType.EXTRACTION_PROGRESS:
            repo.set_stage(paper_id, "extract")
        elif event.type is EventType.MARKING_PROGRESS:
            repo.set_stage(paper_id, "mark")
        else:
            continue
        index = event.payload.get("index")
        total = event.payload.get("total")
        if isinstance(index, int) and isinstance(total, int) and total > 0:
            repo.set_progress(paper_id, index, total)


def _run_grading_job(
    paper_id: uuid.UUID,
    settings: Settings,
    repo: TeacherPaperRepository,
    storage: StorageBackend,
    history_store: HistoryStoreProtocol,
    gemini_client: GeminiClient,
    corpus: SchemeCorpusRepository,
) -> None:
    """Detect, resolve, extract and mark one paper on this instance's pool. Never raises.

    Runs on :data:`_grading_pool`, not the request that triggered it (upload or
    regrade): the caller has already claimed the run via ``claim_run`` and
    returned, so nothing here holds a request open. Every state change this
    makes is written to the row, not to process memory, so any instance's
    ``GET /papers/{id}`` sees it — including one that never ran this job.

    ``corpus`` is the scheme-corpus repository (spec §4.3): the fallback
    ``resolve_mark_scheme`` (shared with the student portal) consults when no
    scheme was attached alongside this scan.

    Failures are recorded on the row rather than raised: the caller is a pool
    worker with nobody to catch them, and every polling route reads
    :func:`_row_error` for exactly this reason.

    Sets :data:`~lemely.runtime.events.current_run_id` to ``str(paper_id)`` for
    the whole call (spec §4.5, DS10): every bus event this thread publishes —
    directly, or via ``extract_answers``/``grade_paper`` below — carries this
    paper's id, and :func:`_track_progress`'s own queue is subscribed scoped
    to the same id, so a second run on this instance (or, once
    :data:`_grading_pool` grows past one worker, a concurrent one on another)
    cannot mix progress counters with this one.
    """
    from lemely.web.routers.student import resolve_mark_scheme
    from lemely.web.services.grading import extract_answers, grade_paper

    run_id_token = current_run_id.set(f"teacher:{paper_id}")
    progress_queue = bus.subscribe_queue(f"teacher:{paper_id}")
    stop = threading.Event()
    tracker = threading.Thread(
        target=_track_progress,
        args=(repo, paper_id, progress_queue, stop),
        daemon=True,
    )
    tracker.start()
    try:
        row = repo.get(paper_id)
        if row is None:
            return
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            scan_dest = tmp_dir / Path(row.storage_path).name
            scan_path = _download_to(storage, settings.storage.bucket, row.storage_path, scan_dest)
            sibling: Path | None = None
            if row.scheme_storage_path is not None:
                # A scheme attached alongside the scan on upload — always
                # preferred by `resolve_mark_scheme` over a corpus lookup.
                sibling = _download_to(
                    storage,
                    settings.storage.bucket,
                    row.scheme_storage_path,
                    tmp_dir / "mark_scheme.pdf",
                )
            metadata = row.metadata

            # Detection is advisory: it names the card and helps the resolver
            # match the parsed-scheme corpus, but a paper with an attached
            # scheme marks fine without it. A failure here must not cost the
            # teacher their marks, so it is warned about and stepped over.
            if metadata is None and _detection_available(settings):
                try:
                    metadata = ScanMetadataExtractor(gemini_client)(scan_path)
                    repo.set_metadata(paper_id, metadata)
                except Exception as exc:
                    log.exception("teacher_detection_failed", paper_id=str(paper_id))
                    bus.publish(
                        EventType.WARNING,
                        paper_id=str(paper_id),
                        message=f"Could not read this scan's exam details: {exc}",
                    )

            repo.set_stage(paper_id, "scheme")
            scheme = row.mark_scheme or resolve_mark_scheme(
                sibling, corpus, settings, gemini_client, metadata=metadata
            )
            if scheme is None:
                repo.fail(
                    paper_id,
                    "No mark scheme could be resolved for this paper — nothing was marked. "
                    "Attach one on upload, or add it under Mark schemes and re-run.",
                )
                return
            repo.set_mark_scheme(paper_id, scheme)

            repo.set_stage(paper_id, "extract")
            extracted = extract_answers(scan_path, scheme, gemini_client=gemini_client)

            repo.set_stage(paper_id, "mark")
            # `student_id=None`/`history_store=None`: a console upload is never
            # attributed to a student account (D1.12 — `TeacherPaper.student_id`
            # is always null today), so there is nobody to record a history
            # entry for. The marks live on this row and are served from it.
            report = grade_paper(
                scheme, extracted, gemini_client=gemini_client, student_id=None, history_store=None
            )
            repo.finish(paper_id, report)
    except Exception as exc:
        # Marking is a long Gemini/parser call chain and can genuinely fail.
        # Recording it as a terminal state with the reason attached is the
        # whole difference between a console that explains itself and one
        # that shows "Queued" until someone reads the server log.
        log.exception("teacher_grade_failed", paper_id=str(paper_id))
        repo.fail(paper_id, f"Grading failed: {exc}")
    finally:
        # Unsubscribe first, so nothing else can be queued behind the stop flag.
        bus.unsubscribe_queue(progress_queue)
        stop.set()
        current_run_id.reset(run_id_token)


def _start_run_if_claimed(
    paper_id: uuid.UUID,
    settings: Settings,
    repo: TeacherPaperRepository,
    storage: StorageBackend,
    history_store: HistoryStoreProtocol,
    gemini_client: GeminiClient,
    corpus: SchemeCorpusRepository,
) -> bool:
    """Claim the run on the row; if this instance won, submit it to the local pool.

    ``claim_run`` is the one conditional ``UPDATE`` that replaces the old
    ``_jobs_lock``/job-registry pair (spec §4.2): exactly one caller — on this
    instance or another — ever wins the race for a given paper, so a regrade
    fired from two browser tabs, or two Cloud Run instances answering the same
    request, cannot double-mark the same scan.
    """
    if not repo.claim_run(paper_id):
        return False
    _grading_pool.submit(
        _run_grading_job, paper_id, settings, repo, storage, history_store, gemini_client, corpus
    )
    return True


# ---------------------------------------------------------------------------
# Shared helpers.
# ---------------------------------------------------------------------------


def _safe_upload_name(filename: str | None, fallback: str) -> str:
    """Thin wrapper over :func:`lemely.web.upload_utils.safe_upload_name`.

    Kept as a module-level name so the shared basename-sanitisation is reachable
    at the same call site the teacher routes already use.
    """
    return safe_upload_name(filename, fallback)


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


def _detection_available(settings: Settings) -> bool:
    """Whether scan-metadata detection can run at all (an API key is configured)."""
    return settings.gemini_api_key is not None


def _mean(values: list[float]) -> float | None:
    """Return the arithmetic mean rounded to 2 dp, or ``None`` for an empty list."""
    if not values:
        return None
    return round(sum(values) / len(values), 2)


def _graded_pipeline_steps(report: AccuracyReport) -> list[PipelineStepDTO]:
    """Derive the five pipeline steps from a completed grade result.

    Counts are the real per-question totals: total questions, questions marked,
    and questions clearing the review-confidence threshold. All ``done`` after a
    completed grade (the pipeline ran to the boundary-resolution stage).

    Deliberately a *different* list from :func:`_live_pipeline_steps`: this one
    reports what the finished run found (how many questions cleared the
    confidence threshold, whether boundaries resolved), which is analysis that
    does not exist yet while a paper is still being marked. Reusing one list for
    both would mean either dropping the confidence/boundary counts from the
    graded view or inventing them for the running one.
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


def _live_pipeline_steps(row: TeacherPaperRow) -> list[PipelineStepDTO]:
    """Derive the pipeline for a paper that has not finished grading.

    Stages before the current one are ``done``, the current one is ``active``,
    and the rest are ``idle`` — read straight off the row's own ``stage``, which
    :func:`_track_progress` and :func:`_run_grading_job` keep in step with the
    run. ``count`` carries the real ``current / total`` question counter when
    the running stage published one, and is blank otherwise: a fabricated
    denominator on a stage that has not started would be the invented progress
    this console exists to avoid.

    Nothing is ``active`` for a ``queued`` row (it is waiting for a worker, not
    running) or a ``failed``/stale one — such a row freezes on the stage it
    stopped at, so the panel shows how far the run actually got instead of
    resetting to zero or claiming to still be working.
    """
    order = [stage for stage, _label in _JOB_STAGES]
    current = order.index(row.stage) if row.stage in order else 0
    running = row.status is UploadStatus.processing and not row.stale
    steps = [
        # The bytes are in object storage before the job is even submitted, so
        # this is genuinely done in every state a live pipeline is rendered for.
        PipelineStepDTO(label="Scan received", count="", state="done"),
    ]
    for index, (_stage, label) in enumerate(_JOB_STAGES):
        if index < current:
            state: Literal["done", "active", "idle"] = "done"
        elif index == current and running:
            state = "active"
        else:
            state = "idle"
        count = ""
        if index == current and row.progress is not None:
            count = f"{row.progress[0]} / {row.progress[1]}"
        steps.append(PipelineStepDTO(label=label, count=count, state=state))
    return steps


def _pymupdf_filetype(content_type: str | None) -> str:
    """Map a stored scan's content type to the ``filetype`` PyMuPDF's stream opener wants.

    ``None``/``application/pdf`` (the common case — most scans are PDFs, and
    some clients omit the header) opens as ``"pdf"``; an ``image/*`` upload
    opens as its subtype (``"png"``, ``"jpeg"``), matching what the console's
    upload input accepts.
    """
    if content_type is None or content_type == "application/pdf":
        return "pdf"
    return content_type.split("/", 1)[-1]


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

    Paper comparison, so grade-bearing records only (``docs/quiz-model.md``
    §5). Left unfiltered, a quiz would both stand in as "the latest paper" and
    be matched as a prior attempt of "Paper 1/1" — the synthetic paper number
    the marking call needed — comparing a topic quiz against a real paper.
    """
    records = grade_bearing(history.records)
    if not records:
        return None
    latest = records[-1]
    prior = StudentHistory(student_id=history.student_id, records=records[:-1])
    return compare_performance(prior, latest).percentage_delta


# ---------------------------------------------------------------------------
# Grading console.
# ---------------------------------------------------------------------------


@router.post("/papers/upload", response_model=UploadResponseDTO)
async def upload_paper(
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    settings: Annotated[Settings, Depends(get_settings)],
    repo: Annotated[TeacherPaperRepository, Depends(get_teacher_paper_repo)],
    storage: Annotated[StorageBackend, Depends(get_storage_backend)],
    history_store: Annotated[HistoryStoreProtocol, Depends(get_history_store)],
    gemini_client: Annotated[GeminiClient, Depends(get_gemini_client)],
    corpus: Annotated[SchemeCorpusRepository, Depends(get_scheme_corpus_repo)],
    scan: Annotated[UploadFile, File()],
    mark_scheme: Annotated[UploadFile | None, File()] = None,
) -> UploadResponseDTO:
    """Store the scan (+ optional scheme) in object storage, insert the row, start marking.

    Keys: ``teacher/{uploaded_by}/{paper_id}/{safe_name}`` and a fixed
    ``mark_scheme.pdf`` sibling (spec §4.1). ``jobId`` equals ``paperId`` — the
    job registry is gone, the row is the job. ``detected`` stays empty
    (D6.13): detection runs inside the job, not this request.

    **This endpoint does no Gemini work (D6.13)**, and its two
    ``storage.upload`` calls run off the event loop via
    ``anyio.to_thread.run_sync``: this is ``async def`` (FastAPI runs it on
    uvicorn's single event loop rather than in a worker thread), and a
    blocking network call made inline here would freeze every other request
    in the process — health checks included — for as long as it took, exactly
    the shape decision D6.13 removed from this route once already.
    """
    uploaded_by, _ = _viewer(auth)
    paper_id = uuid.uuid4()
    prefix = f"teacher/{uploaded_by}/{paper_id.hex}"

    scan_bytes = await scan.read()
    check_upload_cap(scan_bytes, max_bytes=_MAX_UPLOAD_BYTES)
    scan_key = f"{prefix}/{_safe_upload_name(scan.filename, 'scan.pdf')}"
    await anyio.to_thread.run_sync(
        storage.upload, settings.storage.bucket, scan_key, scan_bytes, scan.content_type
    )

    scheme_key: str | None = None
    if mark_scheme is not None:
        # Fixed server-side name, deliberately NOT the sanitised client
        # basename: today's `resolve_mark_scheme` locates an attached scheme
        # by looking for a sibling called exactly `mark_scheme.pdf` next to
        # the scan — the same contract `routers/student.py` writes to.
        scheme_bytes = await mark_scheme.read()
        check_upload_cap(scheme_bytes, max_bytes=_MAX_UPLOAD_BYTES)
        scheme_key = f"{prefix}/mark_scheme.pdf"
        await anyio.to_thread.run_sync(
            storage.upload,
            settings.storage.bucket,
            scheme_key,
            scheme_bytes,
            mark_scheme.content_type,
        )

    repo.create(
        paper_id=paper_id,
        uploaded_by=uploaded_by,
        storage_path=scan_key,
        scheme_storage_path=scheme_key,
        original_filename=_safe_upload_name(scan.filename, "scan.pdf"),
        content_type=scan.content_type,
        byte_size=len(scan_bytes),
    )
    # Marking starts here, not when a browser asks for it. A teacher who
    # uploads and immediately closes the tab still gets a graded paper.
    _start_run_if_claimed(paper_id, settings, repo, storage, history_store, gemini_client, corpus)
    return UploadResponseDTO(jobId=str(paper_id), paperId=str(paper_id), detected=[])


def _paper_summary(row: TeacherPaperRow) -> PaperSummaryDTO:
    """Build the grid-card DTO for one stored paper."""
    kind = _row_kind(row)
    report = row.report if kind in ("graded", "review") else None
    if report is None:
        return PaperSummaryDTO(
            id=str(row.id),
            name=_paper_label(row),
            kind=kind,
            status="Failed" if kind == "failed" else kind.capitalize(),
            error=_row_error(row),
        )
    correction = report.correction
    min_conf = min(
        (q.confidence_score for q in correction.questions),
        default=1.0,
    )
    return PaperSummaryDTO(
        id=str(row.id),
        name=_paper_label(row),
        kind=kind,
        status="Review" if kind == "review" else "Graded",
        awardedMarks=correction.awarded_marks,
        maxMarks=correction.maximum_marks,
        confidence=round(min_conf, 2),
        needsReview=correction.needs_teacher_review,
    )


def _batch_tabs(rows: list[TeacherPaperRow]) -> list[BatchTabDTO]:
    """Compute live batch-filter tab counts from the visible papers."""
    kinds = [_row_kind(r) for r in rows]
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
def list_papers(
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    repo: Annotated[TeacherPaperRepository, Depends(get_teacher_paper_repo)],
) -> PaperListDTO:
    """Return every paper visible to the caller (DS11) as grid cards plus batch tabs."""
    viewer_id, viewer_role = _viewer(auth)
    rows = repo.list_visible(viewer_id=viewer_id, viewer_role=viewer_role)
    return PaperListDTO(
        papers=[_paper_summary(r) for r in rows],
        tabs=_batch_tabs(rows),
    )


@router.post("/papers/{paper_id}/regrade", status_code=202)
def regrade_paper(
    paper_id: str,
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    settings: Annotated[Settings, Depends(get_settings)],
    repo: Annotated[TeacherPaperRepository, Depends(get_teacher_paper_repo)],
    storage: Annotated[StorageBackend, Depends(get_storage_backend)],
    history_store: Annotated[HistoryStoreProtocol, Depends(get_history_store)],
    gemini_client: Annotated[GeminiClient, Depends(get_gemini_client)],
    corpus: Annotated[SchemeCorpusRepository, Depends(get_scheme_corpus_repo)],
) -> dict[str, str]:
    """Queue a paper for (re-)grading and return immediately.

    The fire-and-forget sibling of the old ``POST /grade`` stream, which DS14
    deletes along with ``POST /extract``: same work, no stream, and now the
    run is claimed with one conditional ``UPDATE`` (spec §4.2) rather than a
    process-local ``Future``, so a teacher leaning on Retry — or two Cloud Run
    instances answering the same click — cannot double-mark the same scan or
    double-charge the Gemini budget for it. ``202`` regardless of whether this
    call won the claim: either way the row is (or already was) in flight, and
    the console keeps polling for the outcome.
    """
    row = _require_paper(repo, auth, paper_id)
    _start_run_if_claimed(row.id, settings, repo, storage, history_store, gemini_client, corpus)
    return {"paperId": paper_id, "status": "processing"}


@router.get("/papers/{paper_id}", response_model=PaperDetailDTO)
def get_paper(
    paper_id: str,
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    repo: Annotated[TeacherPaperRepository, Depends(get_teacher_paper_repo)],
) -> PaperDetailDTO:
    """Return the grade detail (questions, weak areas, pipeline) for a visible paper.

    Served for papers still being graded too, with a live pipeline and no
    marks — a page reload mid-run has something to render either way (D6.13).
    An unknown *or invisible* id is a 404 (DS11): this never reveals whether a
    paper exists to a caller who may not see it.
    """
    row = _require_paper(repo, auth, paper_id)
    kind = _row_kind(row)
    report = row.report if kind in ("graded", "review") else None
    if report is None:
        return PaperDetailDTO(
            id=str(row.id),
            name=_paper_label(row),
            kind=kind,
            error=_row_error(row),
            metadata=_detected_fields(row.metadata) if row.metadata else [],
            pipeline=_live_pipeline_steps(row),
        )
    correction = report.correction
    return PaperDetailDTO(
        id=str(row.id),
        name=_paper_label(row),
        kind=kind,
        awardedMarks=correction.awarded_marks,
        maxMarks=correction.maximum_marks,
        needsReview=correction.needs_teacher_review,
        metadata=_detected_fields(correction.metadata),
        pipeline=_graded_pipeline_steps(report),
        questions=[question_to_dto(q) for q in correction.questions],
        weakAreas=[weak_area_to_dto(w) for w in report.weaknesses.weak_areas],
    )


@router.get(
    "/papers/{paper_id}/preview",
    responses={200: {"content": {"image/png": {}}, "description": "Page 1 of the scan"}},
)
def get_paper_preview(
    paper_id: str,
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    settings: Annotated[Settings, Depends(get_settings)],
    repo: Annotated[TeacherPaperRepository, Depends(get_teacher_paper_repo)],
    storage: Annotated[StorageBackend, Depends(get_storage_backend)],
) -> Response:
    """Render page 1 of a paper's stored scan as a PNG thumbnail.

    Rendered server-side rather than handing the browser the raw file: the card
    thumbnail is a 64px strip, and an ``<embed>``-ed scan there would pull a
    multi-megabyte download and a viewer chrome into every card in the grid. It
    also keeps the scan itself behind the router's staff guard and DS11
    visibility — the response is an image of one page, not the document.

    A ``def`` route, not ``async def``: FastAPI already runs a synchronous
    handler in its own worker thread, so the blocking ``storage.download``
    below does not need an explicit ``anyio.to_thread`` wrap the way the
    upload routes' calls do from inside ``async def``.

    404 when the object has expired or was never written (DS9) — a stored
    scan is not forever, and a caller sees that as "no scan", not a crash.
    Image uploads (the console accepts ``image/*`` as well as PDFs) are passed
    through PyMuPDF the same way, so one code path covers both.
    """
    row = _require_paper(repo, auth, paper_id)
    try:
        data = storage.download(settings.storage.bucket, row.storage_path)
    except StorageObjectNotFoundError:
        raise HTTPException(
            status_code=404, detail=f"No stored scan for paper {paper_id}"
        ) from None

    import pymupdf

    try:
        # PyMuPDF's `open` is an untyped alias for `Document`, so a strict-mode
        # call needs the ignore. Narrowed to this one code, not the module.
        with pymupdf.open(  # type: ignore[no-untyped-call]
            stream=data, filetype=_pymupdf_filetype(row.content_type)
        ) as doc:
            if doc.page_count == 0:
                raise HTTPException(status_code=422, detail="Stored scan has no pages")
            # ~600px on the long edge of an A4 page. Sized against the consumer:
            # the card thumbnail is a ~300px-wide strip, so this is still sharp
            # on a 2x display, and every step up costs a bigger payload on every
            # card in the grid at once (96 dpi produced a 320KB PNG per paper).
            pixmap = doc.load_page(0).get_pixmap(dpi=72)
            png: bytes = pixmap.tobytes("png")
    except HTTPException:
        raise
    except Exception as exc:
        # A scan that cannot be rendered is not a server fault — it is a file the
        # teacher uploaded that is not the document type it claimed to be.
        log.warning("paper_preview_failed", paper_id=paper_id, error=str(exc))
        raise HTTPException(status_code=422, detail=f"Could not render this scan: {exc}") from exc

    # Immutable for the lifetime of the paper id: the stored scan never changes
    # once uploaded, so the grid can cache every thumbnail it has already drawn.
    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "private, max-age=3600"},
    )


@router.get("/grading/queue", response_model=GradingQueueDTO)
def grading_queue(
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    repo: Annotated[TeacherPaperRepository, Depends(get_teacher_paper_repo)],
) -> GradingQueueDTO:
    """Return low-confidence questions flagged for teacher review across visible papers."""
    viewer_id, viewer_role = _viewer(auth)
    rows: list[QueueRowDTO] = []
    for row in repo.list_visible(viewer_id=viewer_id, viewer_role=viewer_role):
        report = row.report
        if report is None:
            continue
        for question in report.correction.questions:
            if question.needs_teacher_review or question.confidence_score < _REVIEW_CONFIDENCE:
                rows.append(
                    QueueRowDTO(
                        paperId=str(row.id),
                        # `student_id` is always null today (D1.12), so a
                        # queue row is named for its paper, same as the grid.
                        name=_paper_label(row),
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


def _scheme_row_dto(row: SchemeCorpusRow) -> SchemeRowDTO:
    """Build a :class:`SchemeRowDTO` from a corpus row (spec §4.3)."""
    return SchemeRowDTO(
        doc=row.doc,
        paper=f"Paper {row.paper_number} V{row.paper_variant}",
        session=_session_label(SESSION_MONTH_LABELS[row.session_month], row.session_year),
        maxMarks=row.maximum_mark,
        questionCount=row.question_count,
        status="parsed",
    )


@router.get("/schemes", response_model=SchemeListDTO)
def list_schemes(
    corpus: Annotated[SchemeCorpusRepository, Depends(get_scheme_corpus_repo)],
) -> SchemeListDTO:
    """Return parsed mark schemes from the corpus plus computed stats (spec §4.3).

    The "Failed" stat card — which used to count unreadable JSON files on
    disk — is gone: a row here is a ``mark_schemes`` record, and nothing on
    disk can fail to load any more.
    """
    rows = corpus.list_rows()
    return SchemeListDTO(
        schemes=[_scheme_row_dto(r) for r in rows],
        stats=[StatCardDTO(key="Parsed", value=str(len(rows)), unit="schemes")],
    )


@router.post("/schemes", response_model=SchemeRowDTO)
async def upload_scheme(
    settings: Annotated[Settings, Depends(get_settings)],
    storage: Annotated[StorageBackend, Depends(get_storage_backend)],
    corpus: Annotated[SchemeCorpusRepository, Depends(get_scheme_corpus_repo)],
    scheme_pdf: Annotated[UploadFile, File()],
) -> SchemeRowDTO:
    """Parse an uploaded CAIE mark-scheme PDF deterministically and persist it (spec §4.3).

    Uses :class:`DeterministicMarkSchemeParser` (no Gemini call). On success the
    parsed scheme replaces the ``mark_schemes`` row for its paper (``store`` is
    insert-or-replace, keyed on paper identity) and the PDF itself lands in
    object storage at ``schemes/{mark_scheme_id}/{safe_name}`` (spec §4.1).
    Parse failures surface as a 422, and so does a subject with no bundled
    syllabus taxonomy — see :meth:`SchemeCorpusRepository.store`.

    A re-upload for a paper identity already in the corpus reuses that paper's
    ``mark_scheme_id`` (``store`` is insert-or-replace), so the *object key*
    can collide with — or, on a different client filename, silently orphan —
    whatever this scheme's PDF was uploaded as last time. The previous key,
    if any, is deleted before the new one is written: on a same-filename
    re-upload this is what makes the new ``storage.upload`` succeed at all
    against a create-only backend (spec §4.1); on a different-filename
    re-upload it is what stops the old object being orphaned forever.
    """
    from lemely.io.det import DeterministicMarkSchemeParser

    pdf_bytes = await scheme_pdf.read()
    check_upload_cap(pdf_bytes, max_bytes=_MAX_UPLOAD_BYTES)
    # Sanitise the client filename to a basename before joining — the raw value
    # must never be trusted as a path (traversal into ``../`` etc.).
    filename = _safe_upload_name(scheme_pdf.filename, "scheme.pdf")
    with tempfile.TemporaryDirectory() as tmp:
        pdf_path = Path(tmp) / filename
        pdf_path.write_bytes(pdf_bytes)
        try:
            scheme = DeterministicMarkSchemeParser(cfg=settings.det_parser)(pdf_path)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"Mark scheme parse failed: {exc}") from exc

    scheme_id = corpus.store(scheme, provenance="teacher_upload:deterministic")
    if scheme_id is None:
        raise HTTPException(
            status_code=422,
            detail=(
                f"No bundled syllabus for subject {scheme.metadata.subject_code}; "
                "cannot file this scheme."
            ),
        )
    # `corpus.store` above has already committed the new parsed payload under
    # `scheme_id` — the database is authoritative from this point on. A
    # failure in either storage call below must not look like a silent
    # success, and `set_source_document` (which would make the row claim the
    # new key holds this content) must not run unless the upload actually
    # landed it.
    key = f"schemes/{scheme_id}/{filename}"
    previous_key = corpus.get_source_document(scheme_id)
    try:
        if previous_key is not None:
            storage.delete(settings.storage.bucket, previous_key)
        storage.upload(settings.storage.bucket, key, pdf_bytes, scheme_pdf.content_type)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Storing the mark scheme PDF failed: {exc}",
        ) from exc
    corpus.set_source_document(scheme_id, key)
    return _scheme_row_dto(next(r for r in corpus.list_rows() if r.id == scheme_id))


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
    history: StudentHistory,
    *,
    display_name: str,
    student_id: str,
    now: datetime,
    acks: dict[tuple[str, AtRiskReason], AtRiskAcknowledgementRow],
    targets: Mapping[str, str] | None = None,
) -> StudentRowDTO | None:
    """Build a roster row from a student's history, or ``None`` if empty.

    ``display_name``/``student_id`` come from the real class roster (D3.1) —
    ``history.student_id`` is the raw user-id key used to address the history
    store, not a human name.

    The row exists for any student with *any* recorded activity, but every
    grade/mark field on it reads the latest **grade-bearing** record
    (``docs/quiz-model.md`` §5) — a quiz has no grade and its mark is out of a
    quiz total, not a paper total. A student whose only activity is quizzes
    therefore appears on the roster with an empty grade and no mark, which is
    the honest reading: they are here, they have done work, and they have no
    paper grade yet. ``grade=""`` is the same "no grade" value
    ``DbHistoryStore`` already produces for an attempt with a NULL grade, so
    this introduces no new state for the frontend to handle.

    ``paperCount`` (added P3.7 chunk a, D3.12) counts :func:`is_paper`
    records — origin only, deliberately narrower than the grade-bearing
    filter above: it says "papers", so a past paper whose grade came back
    unreadable still counts, but a quiz never does (D3.9). ``lastActiveAt``
    is unfiltered by origin — a quiz is activity too, matching the
    inactivity rule sitting beside it. ``flags`` runs the D3.3 engine
    (``assess_at_risk``) and converts every fired flag through the single
    ``_at_risk_flag_dto`` helper (``now``/``acks`` threaded in for exactly
    that), so this roster's acknowledged state can never drift from T-01/
    T-05/T-06's reading of the same flag. ``targets`` (subject code -> target
    grade, P4.3/D4.5) is this student's own bulk-loaded slice of
    ``StudentProfileService.target_grades_for_many`` — passed straight through
    to ``assess_at_risk`` so rule 2 can fire.
    """
    if not history.records:
        return None
    latest = latest_grade_bearing(history.records)
    weakest = (
        min(latest.weak_areas, key=lambda a: a.accuracy, default=None)
        if latest is not None
        else None
    )
    assessment = assess_at_risk(history, now=now, targets=targets)
    return StudentRowDTO(
        name=display_name,
        studentId=student_id,
        grade=latest.grade if latest is not None else "",
        mark=f"{latest.awarded_marks}/{latest.maximum_marks}" if latest is not None else "",
        delta=_student_delta(history),
        weakTopic=weakest.topic if weakest is not None else None,
        gradeAtRisk=latest is not None and latest.grade in _AT_RISK_GRADES,
        paperCount=sum(1 for record in history.records if is_paper(record)),
        lastActiveAt=history.records[-1].recorded_at,
        flags=[
            _at_risk_flag_dto(flag, student_id=student_id, acks=acks) for flag in assessment.flags
        ],
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
    profile_service: Annotated[StudentProfileService, Depends(get_student_profile_service)],
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
    # Group mean is a percentage claim, so it sees each student's latest
    # *paper*, never their latest quiz (``docs/quiz-model.md`` §5).
    latest = [
        record
        for history, _ in histories
        if (record := latest_grade_bearing(history.records)) is not None
    ]

    average = _mean([r.percentage for r in latest])
    needs_review = _count_review_items(review_service, auth)
    acks = _acknowledgement_index(ack_service, auth)
    targets_by_student = profile_service.target_grades_for_many(visible.keys())
    at_risk_students = _at_risk(
        histories, now=datetime.now(UTC), acks=acks, targets_by_student=targets_by_student
    )
    recent_activity = _recent_activity(histories)

    stats = [
        StatCardDTO(
            key="Papers graded",
            # Counts papers, so ``is_paper`` (origin only) rather than
            # ``is_grade_bearing``: a past paper whose grade came back
            # unreadable is still a paper the student sat and this teacher had
            # marked, but a quiz is not a paper and must not inflate the count
            # of a card that says "papers" (``docs/quiz-model.md`` §5).
            value=str(
                sum(1 for history, _ in histories for record in history.records if is_paper(record))
            ),
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
    return OverviewDTO(
        stats=stats, atRisk=at_risk_students, retention=[], recentActivity=recent_activity
    )


_RECENT_ACTIVITY_LIMIT = 8


def _recent_activity(
    histories: list[tuple[StudentHistory, str]], *, limit: int = _RECENT_ACTIVITY_LIMIT
) -> list[RecentActivityDTO]:
    """Flatten every visible student's records into one recency-sorted feed.

    T-01 item 4 ("submissions across their classes", D3.12) — spans papers
    *and* quizzes because the spec says "submissions", not "papers". Built
    from the exact ``histories`` list ``teacher_overview`` already loaded for
    ``stats``/``atRisk`` above; no new query. ``grade`` reads
    ``is_grade_bearing`` per record — a quiz has no grade and reports
    ``None`` here rather than the student's last *paper* grade, which would
    misattribute someone else's evidence to this submission (the exact
    mistake D3.9 exists to prevent). Sorted most-recent-first (``recorded_at``
    strings compare correctly as ISO-8601 UTC — the same convention
    ``lemely.core.class_analytics.cohort_trend`` already relies on) and
    capped at ``limit`` (a dashboard tile, not a full history browser).
    """
    entries = [
        (record, history.student_id, display_name)
        for history, display_name in histories
        for record in history.records
    ]
    entries.sort(key=lambda item: item[0].recorded_at, reverse=True)
    return [
        RecentActivityDTO(
            studentId=student_id,
            studentName=display_name,
            subjectCode=record.metadata.subject_code,
            percentage=record.percentage,
            grade=record.grade if is_grade_bearing(record) else None,
            recordedAt=record.recorded_at,
            origin=record.origin,
        )
        for record, student_id, display_name in entries[:limit]
    ]


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
    targets_by_student: Mapping[str, Mapping[str, str]] | None = None,
) -> list[AtRiskStudentDTO]:
    """Identify at-risk students via the D3.3 rules engine.

    ``histories`` pairs each student's history with their real
    ``RosterEntry.display_name`` (D3.1/P3.3) — ``AtRiskStudentDTO.name`` used
    to be the raw ``history.student_id`` (a uuid), which this signature makes
    impossible to regress back to.

    Runs ``lemely.core.at_risk.assess_at_risk`` (declining trend / predicted
    below target / inactive, combined with OR) over each student's history.
    ``targets_by_student`` (subject code -> target grade, per student id;
    P4.3/D4.5) is the caller's single bulk load from
    ``StudentProfileService.target_grades_for_many`` over the whole roster —
    never one query per student in this loop. A student absent from the
    mapping, or with no target for their latest subject, simply leaves rule 2
    ``NOT_EVALUABLE`` for them. Supersedes the old "grade in {D,E,U} or any
    negative delta" heuristic, which matched none of the three specified
    rules and carried no reason label.

    ``acks`` (D3.5, P3.4b) is the caller's :func:`_acknowledgement_index`,
    threaded through to :func:`_at_risk_flag_dto` so this route reports the
    identical acknowledged state T-05/T-06 do for the same flag.
    """
    at_risk: list[AtRiskStudentDTO] = []
    for history, display_name in histories:
        if not history.records:
            continue
        targets = (targets_by_student or {}).get(history.student_id)
        assessment = assess_at_risk(history, now=now, targets=targets)
        if not assessment.flags:
            continue
        # ``grade``/``weakTopic`` describe the student's standing, which only a
        # real paper establishes (``docs/quiz-model.md`` §5). A student flagged
        # purely on inactivity may legitimately have no paper at all — the
        # flag still stands, the grade is honestly empty.
        latest = latest_grade_bearing(history.records)
        weakest = (
            min(latest.weak_areas, key=lambda a: a.accuracy, default=None)
            if latest is not None
            else None
        )
        at_risk.append(
            AtRiskStudentDTO(
                name=display_name,
                grade=latest.grade if latest is not None else "",
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

    Grade-bearing records only, for exactly that reason: ``at_risk``'s
    below-target rule filters the same way (``docs/quiz-model.md`` §5), so
    reading quizzes here would make this screen's predicted grade disagree
    with the at-risk badge sitting beside it. A subject with only quiz
    activity produces no row at all rather than a row predicting ``""``.
    """
    by_subject: dict[str, list[PaperRecord]] = {}
    for record in grade_bearing(history.records):
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
    """This student's own activity stats, purely from ``recorded_at`` values.

    ``lastActiveAt``/``daysSinceLastSubmission`` read **all** records: a quiz
    is activity, and ``at_risk``'s inactivity rule counts it the same way
    (``docs/quiz-model.md`` §5) — a screen that told a teacher a student had
    been silent for 20 days while the at-risk engine saw them last week would
    be reporting on a different student than the badge next to it.
    ``totalPapers`` says *papers*, so it counts only those (``is_paper``).
    """
    if not history.records:
        return StudentEngagementDTO(totalPapers=0, lastActiveAt=None, daysSinceLastSubmission=None)
    last = history.records[-1]
    last_active = _parse_recorded_at(last.recorded_at)
    days_since = (now - last_active).days if last_active is not None else None
    return StudentEngagementDTO(
        totalPapers=sum(1 for record in history.records if is_paper(record)),
        lastActiveAt=last.recorded_at,
        daysSinceLastSubmission=days_since,
    )


def _student_detail_dto(
    entry: RosterEntry,
    history: StudentHistory,
    *,
    now: datetime,
    acks: dict[tuple[str, AtRiskReason], AtRiskAcknowledgementRow],
    targets: Mapping[str, str] | None = None,
) -> StudentDetailDTO:
    """Build the T-05 student-detail DTO from one student's real history.

    Reuses ``aggregate_weaknesses_from_history`` (weaknesses),
    ``assess_at_risk``/``_at_risk_flag_dto`` (at-risk status — never a second,
    re-implemented translation), and this module's own subject/attempt/
    engagement helpers. Integrity signals are deliberately absent: see the
    route docstring. ``acks`` (D3.5, P3.4b) threads the caller's
    :func:`_acknowledgement_index` through to ``_at_risk_flag_dto`` so this
    screen reports the identical acknowledged state T-01/T-06 do. ``targets``
    (subject code -> target grade, P4.3/D4.5) is this student's own
    ``StudentProfileService.target_grades_for`` result, passed through to
    ``assess_at_risk`` so rule 2 can fire.
    """
    assessment = assess_at_risk(history, now=now, targets=targets)
    student_id = str(entry.student_id)
    # ``attempts``/``trend`` are the paper-history table and the percentage
    # sparkline — both paper-comparison claims, both grade-bearing only
    # (``docs/quiz-model.md`` §5). A quiz listed here would render as
    # "0625/11", the synthetic paper identity the marking call needed, against
    # a percentage out of a quiz total. ``weaknesses`` below is deliberately
    # unfiltered: a weakness is a weakness whatever revealed it.
    paper_records = grade_bearing(history.records)
    return StudentDetailDTO(
        studentId=student_id,
        displayName=entry.display_name,
        subjects=_subject_predictions(history),
        attempts=[_attempt_dto(r) for r in reversed(paper_records)],
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
            for r in paper_records
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
    profile_service: Annotated[StudentProfileService, Depends(get_student_profile_service)],
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
        targets = profile_service.target_grades_for(student_id)
        return _student_detail_dto(
            entry, history, now=datetime.now(UTC), acks=acks, targets=targets
        )
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
    profile_service: Annotated[StudentProfileService, Depends(get_student_profile_service)],
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

    Target grades (P4.3/D4.5) are loaded once across every roster via
    ``StudentProfileService.target_grades_for_many`` — every class's roster is
    gathered first so this stays a single bulk query for the whole list
    rather than one per student across potentially many classes.
    """
    try:
        rows = service.list_classes(auth.user_id, auth.role)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    now = datetime.now(UTC)
    acks = _acknowledgement_index(ack_service, auth)
    rosters = [(row, service.roster(auth.user_id, auth.role, row.class_id)) for row in rows]
    all_student_ids = [
        str(roster_entry.student_id) for _, roster in rosters for roster_entry in roster
    ]
    targets_by_student = profile_service.target_grades_for_many(all_student_ids)
    entries: list[AtRiskListEntryDTO] = []
    for row, roster in rosters:
        for roster_entry in roster:
            student_id = str(roster_entry.student_id)
            history = history_store.load(student_id)
            if not history.records:
                continue
            assessment = assess_at_risk(
                history, now=now, targets=targets_by_student.get(student_id)
            )
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
            # Latest *paper* grade, matching the overview's at-risk rows
            # exactly (``_at_risk`` above); empty when the student has only
            # quiz activity (``docs/quiz-model.md`` §5).
            latest_paper = latest_grade_bearing(history.records)
            entries.append(
                AtRiskListEntryDTO(
                    studentId=student_id,
                    displayName=roster_entry.display_name,
                    classId=str(row.class_id),
                    className=row.name,
                    grade=latest_paper.grade if latest_paper is not None else "",
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
    profile_service: Annotated[StudentProfileService, Depends(get_student_profile_service)],
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
    targets = profile_service.target_grades_for(student_id)
    assessment = assess_at_risk(history, now=datetime.now(UTC), targets=targets)
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
