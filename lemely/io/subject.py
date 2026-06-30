"""Subject-level aggregation: combine multiple per-paper CorrectionResults into a SubjectResult."""

from __future__ import annotations

from collections.abc import Sequence

from lemely.core.analytics import summarize_weaknesses
from lemely.core.schemas import (
    CorrectedQuestion,
    CorrectionResult,
    SubjectResult,
)
from lemely.runtime.errors import UsageError


def _virtual_combined_correction(papers: Sequence[CorrectionResult]) -> CorrectionResult:
    """Synthesise a single CorrectionResult whose questions list is the union of all papers'.

    Used only for feeding summarize_weaknesses() across the subject.
    """
    first_meta = papers[0].metadata
    all_qs: list[CorrectedQuestion] = []
    for p in papers:
        for q in p.questions:
            prefixed_id = f"p{p.metadata.paper_number}{p.metadata.paper_variant}_{q.question_id}"
            all_qs.append(q.model_copy(update={"question_id": prefixed_id}))
    return CorrectionResult(metadata=first_meta, questions=all_qs)


def aggregate_subject(papers: Sequence[CorrectionResult]) -> SubjectResult:
    """Combine per-paper corrections into a single SubjectResult.

    Args:
        papers: 1+ CorrectionResults that must all share subject_code + session_month +
            session_year.

    Raises:
        UsageError: empty list or mismatched subject/session across papers.
    """
    if not papers:
        raise UsageError("aggregate_subject requires at least one CorrectionResult.")

    ref = papers[0].metadata
    for p in papers[1:]:
        m = p.metadata
        if (m.subject_code, m.session_month, m.session_year) != (
            ref.subject_code, ref.session_month, ref.session_year,
        ):
            raise UsageError(
                f"Paper subject/session mismatch: "
                f"{m.subject_code}/{m.session_month}/{m.session_year} "
                f"vs reference {ref.subject_code}/{ref.session_month}/{ref.session_year}"
            )

    combined = _virtual_combined_correction(papers)
    weaknesses = summarize_weaknesses(combined)

    return SubjectResult(
        subject_code=ref.subject_code,
        session_month=ref.session_month,
        session_year=ref.session_year,
        paper_results=list(papers),
        weaknesses=weaknesses,
    )
