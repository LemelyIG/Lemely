"""Human-mode (Rich) renderers for CLI output. Pure: take models, return renderables."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich import box
from rich.markup import escape
from rich.table import Table

if TYPE_CHECKING:
    from lemely.core.schemas import (
        AccuracyReport,
        BatchParseResult,
        CorrectionResult,
        CostEstimate,
        ExtractedAnswers,
        GradePrediction,
        QuizPayload,
        SubjectResult,
        WeaknessReport,
    )


def render_cost_estimate(est: CostEstimate) -> Table:
    t = Table(title=f"Cost estimate — {escape(est.source_root)}", box=box.SIMPLE)
    t.add_column("metric")
    t.add_column("value", justify="right")
    t.add_row("Mark scheme PDFs", str(est.mark_scheme_pdfs))
    t.add_row("Cached JSON", str(est.cached_json))
    t.add_row("Needs parsing", str(est.needs_parsing))
    if est.estimated_pdf_pages is not None:
        t.add_row("Estimated PDF pages", str(est.estimated_pdf_pages))
    return t


def render_correction(result: CorrectionResult) -> Table:
    meta = result.metadata
    paper_id = (
        f"{escape(meta.subject_code)}/{meta.paper_number}{meta.paper_variant}"
        f" {escape(meta.session_month)}{f' {meta.session_year}' if meta.session_year else ''}"
    )
    t = Table(
        title=f"Correction — {paper_id} — {result.awarded_marks}/{result.maximum_marks}",
        box=box.SIMPLE,
    )
    t.add_column("Q", justify="right")
    t.add_column("Student")
    t.add_column("Expected")
    t.add_column("Marks", justify="right")
    t.add_column("Topic")
    t.add_column("Confidence")
    t.add_column("Marker")
    t.add_column("Review?")
    marker_glyph = {"deterministic": "✓", "ai": "AI", "missing": "—"}
    for q in result.questions:
        marks = f"{q.awarded_marks}/{q.maximum_marks}"
        style = "green" if q.awarded_marks == q.maximum_marks else "red"
        review = "yes" if q.needs_teacher_review else ""
        t.add_row(
            escape(q.question_id),
            escape(q.student_answer or "—"),
            escape(q.expected_answer or "—"),
            f"[{style}]{marks}[/]",
            escape(q.topic or "—"),
            q.confidence.value,
            marker_glyph.get(q.marker_source, "?"),
            review,
        )
    return t


def render_weakness_report(report: WeaknessReport) -> Table:
    t = Table(title="Weaknesses", box=box.SIMPLE)
    t.add_column("Topic")
    t.add_column("Marks lost", justify="right")
    t.add_column("Out of", justify="right")
    t.add_column("Accuracy", justify="right")
    for w in report.weak_areas:
        t.add_row(
            escape(w.topic),
            str(w.lost_marks),
            str(w.maximum_marks),
            f"{w.accuracy * 100:.0f}%",
        )
    return t


def render_grade_prediction(grade: GradePrediction) -> Table:
    t = Table(title="Grade prediction", box=box.SIMPLE)
    t.add_column("metric")
    t.add_column("value")
    t.add_row("Marks", f"{grade.awarded_marks}/{grade.maximum_marks}")
    t.add_row("Percentage", f"{grade.percentage:.1f}%")
    t.add_row("Predicted grade", escape(grade.grade))
    t.add_row("Confidence", grade.confidence.value)
    return t


def render_accuracy_report(report: AccuracyReport) -> tuple[Table, Table, Table]:
    """Returns (correction table, weakness table, grade table) for sequential printing."""
    return (
        render_correction(report.correction),
        render_weakness_report(report.weaknesses),
        render_grade_prediction(report.grade_prediction),
    )


def render_batch_result(result: BatchParseResult) -> Table:
    t = Table(title="Batch parse summary", box=box.SIMPLE)
    t.add_column("metric")
    t.add_column("value", justify="right")
    t.add_row("Total", str(result.total))
    t.add_row("Parsed", str(result.parsed))
    t.add_row("Skipped (existing)", str(result.skipped))
    t.add_row("Failed", str(result.failed))
    t.add_row("Transient (retry)", str(result.transient_failed))
    return t


def render_extracted_answers(result: ExtractedAnswers) -> Table:
    t = Table(
        title=f"Extracted answers — {escape(result.paper_id)}",
        box=box.SIMPLE,
    )
    t.add_column("Question", justify="left")
    t.add_column("Answer")
    t.add_column("Confidence", justify="right")
    t.add_column("Review?")
    for a in result.answers:
        low = a.confidence < 0.70
        style = "yellow" if low else "green"
        t.add_row(
            escape(a.question_id),
            f"[{style}]{escape(a.answer or '—')}[/]",
            f"{a.confidence:.0%}",
            "yes" if low else "",
        )
    return t


def render_subject_result(result: SubjectResult) -> tuple[Table, Table, Table]:
    """Returns (subject banner, per-paper breakdown, weakness table)."""
    banner = Table(
        title=f"Subject — {escape(result.subject_code)} "
        f"{escape(result.session_month)} {result.session_year or 'Specimen'}",
        box=box.SIMPLE,
    )
    banner.add_column("metric")
    banner.add_column("value")
    banner.add_row("Awarded / Max", f"{result.awarded_marks}/{result.maximum_marks}")
    banner.add_row("Percentage", f"{result.percentage:.1f}%")
    banner.add_row("Subject grade", escape(result.grade))
    banner.add_row("Review?", "yes" if result.needs_teacher_review else "no")

    papers = Table(title="Per-paper breakdown", box=box.SIMPLE)
    papers.add_column("Paper", justify="right")
    papers.add_column("Awarded", justify="right")
    papers.add_column("Max", justify="right")
    papers.add_column("Percentage", justify="right")
    for p in result.paper_results:
        pct = (p.awarded_marks / p.maximum_marks * 100.0) if p.maximum_marks else 0.0
        papers.add_row(
            f"{p.metadata.paper_number}{p.metadata.paper_variant}",
            str(p.awarded_marks),
            str(p.maximum_marks),
            f"{pct:.1f}%",
        )

    return banner, papers, render_weakness_report(result.weaknesses)


def render_quiz_payload(payload: QuizPayload) -> Table:
    t = Table(title="Quiz questions", box=box.SIMPLE)
    t.add_column("#", justify="right")
    t.add_column("Topic")
    t.add_column("Prompt")
    for idx, q in enumerate(payload.questions, start=1):
        t.add_row(str(idx), escape(q.topic), escape(q.prompt))
    return t
