"""Reusable extraction + grading pipeline shared by the portal routers.

Wraps :class:`GeminiAnswerExtractor` and :func:`correct_paper` into two
portal-agnostic entry points:

* :func:`extract_answers` — OCR/answer extraction from a scanned paper.
* :func:`grade_paper` — hybrid deterministic + AI marking, grade prediction,
  and optional persistence of a :class:`PaperRecord` to the history store.

Both publish progress to the global event bus (via the underlying pipelines), so
callers can surface live activity over SSE. Neither hard-codes demo data.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Literal

from lemely.core.analytics import predict_grade, summarize_weaknesses
from lemely.core.binding import BindingReport
from lemely.core.history import HistoryStoreProtocol, PaperRecord, now_iso
from lemely.core.loose_schemas import MarkScheme
from lemely.core.schemas import (
    AccuracyReport,
    CorrectionResult,
    ExtractedAnswers,
)
from lemely.db.attempt_repo import fill_correction_topics
from lemely.io.answer_extraction import GeminiAnswerExtractor
from lemely.io.correction_ai import correct_paper
from lemely.io.gemini import GeminiClient
from lemely.io.grade_boundaries import GradeBoundaryStore
from lemely.io.integrity import apply_integrity_checks
from lemely.runtime.config import IntegritySettings, MarkingOptions
from lemely.runtime.errors import LemelyError

BINDING_HELD_MESSAGE = (
    "We could not match some answers to their questions, so this paper has not been marked. "
    "Please check every page is included and in order, then upload it again."
)
"""What the uploader is told when the binding gate rejects a paper.

Fixed on purpose: the gate's own reasons can quote question ids and counts, and
those go to the log, not to the student or the console.
"""


class BindingHeldError(LemelyError):
    """A paper the binding gate rejected must not be published.

    ``str()`` is the fixed uploader-facing sentence, never the reasons.
    ``reasons`` is the ``detail`` of every failed paper-scope check, for the log.
    """

    def __init__(
        self, report: BindingReport, stage: Literal["before_marking", "after_marking"]
    ) -> None:
        super().__init__(BINDING_HELD_MESSAGE)
        self.verdict = report.verdict
        self.stage = stage
        failed = [c for c in report.checks if not c.passed]
        self.failed_check_ids = [c.id for c in failed]
        self.reasons = [c.detail for c in failed if c.scope == "paper"]


def binding_blocks_publication(report: BindingReport | None) -> bool:
    """Whether a binding report forbids publishing the paper.

    ``None`` means no verdict exists (not a scan, or the gate is off or only
    observing), which never blocks. Any verdict but ``pass`` blocks, and
    ``retry`` after marking is treated like ``hold`` because there is no retry
    left at that point.
    """
    return report is not None and report.verdict != "pass"


def ensure_binding_allows_marking(extracted: ExtractedAnswers | Mapping[str, str]) -> None:
    """Raise :class:`BindingHeldError` before marking a paper that would be thrown away.

    A plain mapping of answers (which :func:`grade_paper` also accepts) carries
    no report, so it is never held.
    """
    if not isinstance(extracted, ExtractedAnswers):
        return
    report = extracted.binding
    if report is not None and binding_blocks_publication(report):
        raise BindingHeldError(report, "before_marking")


def extract_answers(
    scan_path: Path,
    mark_scheme: MarkScheme,
    *,
    gemini_client: GeminiClient,
) -> ExtractedAnswers:
    """Extract student answers from a scanned paper against a mark scheme.

    Args:
        scan_path: Path to the scanned student paper (PDF / image).
        mark_scheme: Parsed mark scheme to align answers against.
        gemini_client: Client used for the extraction call.

    Returns:
        The extracted, ID-normalised answers.
    """
    extractor = GeminiAnswerExtractor(gemini_client)
    return extractor(scan_path=scan_path, mark_scheme=mark_scheme)


def grade_paper(
    mark_scheme: MarkScheme,
    extracted_answers: ExtractedAnswers | Mapping[str, str],
    *,
    gemini_client: GeminiClient | None = None,
    mcq_only: bool = False,
    student_id: str | None = None,
    history_store: HistoryStoreProtocol | None = None,
    boundary_store: GradeBoundaryStore | None = None,
    integrity_settings: IntegritySettings,
    options: MarkingOptions = MarkingOptions(),  # noqa: B008 -- frozen, immutable dataclass
) -> AccuracyReport:
    """Grade a paper and optionally record it to a student's history.

    Runs hybrid marking (deterministic MCQ + AI non-MCQ), resolves grade
    boundaries, and assembles a full :class:`AccuracyReport`. When ``student_id``
    is provided (and non-blank) alongside a ``history_store``, a
    :class:`PaperRecord` is appended so past-results and quiz views can reflect
    this paper.

    Args:
        mark_scheme: Parsed mark scheme.
        extracted_answers: Per-question student responses.
        gemini_client: Required when the paper has non-MCQ questions and
            ``mcq_only`` is ``False``.
        mcq_only: Skip AI marking; non-MCQ questions become ``marker_source="missing"``.
        student_id: When set, the paper is recorded under this id.
        history_store: Store used to persist the record; required for recording.
        boundary_store: Grade-boundary source; a default store is used if omitted.
        integrity_settings: Plagiarism advisory-flag settings (F4 removed the
            AI-detection half). Required (#259): callers pass
            ``settings.integrity``, so no caller can silently grade under the
            defaults instead of the operator's ``[integrity]``.
        options: The marking flags, forwarded to `correct_paper`. Defaults to
            both off, so behaviour is unchanged unless a caller opts in.
            Callers pass `settings.grading.marking_options()`.

    Returns:
        The assembled accuracy report.

    Raises:
        BindingHeldError: The correction's binding report blocks publication.
            Raised before any history record is written.
    """
    correction: CorrectionResult = correct_paper(
        mark_scheme=mark_scheme,
        extracted_answers=extracted_answers,
        gemini_client=gemini_client,
        mcq_only=mcq_only,
        options=options,
    )
    if correction.binding is not None and binding_blocks_publication(correction.binding):
        raise BindingHeldError(correction.binding, "after_marking")
    correction = apply_integrity_checks(
        correction,
        mark_scheme,
        gemini_client=gemini_client,
        settings=integrity_settings,
    )
    # P4.4: fill CorrectedQuestion.topic before summarize_weaknesses groups on
    # it — see lemely.db.attempt_repo's module docstring for why this must
    # happen here rather than at persist time.
    fill_correction_topics(correction, mark_scheme)

    store = boundary_store or GradeBoundaryStore()
    boundaries, boundary_source = store.resolve(correction.metadata)

    report = AccuracyReport(
        correction=correction,
        weaknesses=summarize_weaknesses(correction),
        grade_prediction=predict_grade(
            correction,
            boundaries=boundaries,
            boundary_source=boundary_source,
        ),
    )

    normalized_id = student_id.strip() if student_id else ""
    if normalized_id and history_store is not None:
        record = PaperRecord(
            student_id=normalized_id,
            metadata=correction.metadata,
            awarded_marks=report.correction.awarded_marks,
            maximum_marks=report.correction.maximum_marks,
            percentage=report.grade_prediction.percentage,
            grade=report.grade_prediction.grade,
            weak_areas=report.weaknesses.weak_areas,
            recorded_at=now_iso(),
        )
        history_store.append(normalized_id, record)

    return report
