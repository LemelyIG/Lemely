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

from lemely.core.analytics import predict_grade, summarize_weaknesses
from lemely.core.history import HistoryStoreProtocol, PaperRecord, now_iso
from lemely.core.loose_schemas import MarkScheme
from lemely.core.schemas import (
    AccuracyReport,
    CorrectionResult,
    ExtractedAnswers,
)
from lemely.io.answer_extraction import GeminiAnswerExtractor
from lemely.io.correction_ai import correct_paper
from lemely.io.gemini import GeminiClient
from lemely.io.grade_boundaries import GradeBoundaryStore
from lemely.io.integrity import apply_integrity_checks
from lemely.runtime.config import IntegritySettings


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
    integrity_settings: IntegritySettings | None = None,
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
        integrity_settings: Plagiarism/AI-detection advisory-flag settings; the
            defensive defaults (plagiarism on, AI-detection off) apply if omitted.

    Returns:
        The assembled accuracy report.
    """
    correction: CorrectionResult = correct_paper(
        mark_scheme=mark_scheme,
        extracted_answers=extracted_answers,
        gemini_client=gemini_client,
        mcq_only=mcq_only,
    )
    correction = apply_integrity_checks(
        correction,
        mark_scheme,
        gemini_client=gemini_client,
        settings=integrity_settings or IntegritySettings(),
    )

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
