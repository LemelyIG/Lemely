"""Pure callback functions for Gradio tabs. No gradio imports — testable standalone."""

from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from lemely.core.schemas import (
    AccuracyReport,
    CorrectionResult,
    ExtractedAnswers,
)
from lemely.io.mark_schemes import index_source_library

if TYPE_CHECKING:
    from lemely.core.history import StudentHistory

# ----------------------------------------------------------------------
# Tab 2 — Correct a paper
# ----------------------------------------------------------------------


def build_mark_scheme_dropdown_choices(sources_dir: Path) -> list[str]:
    """Return dropdown labels for mark schemes that have a parsed JSON file."""
    choices: list[str] = []
    for entry in index_source_library(sources_dir):
        json_path = entry.source_path.with_suffix(".json")
        if not json_path.exists():
            continue
        m = entry.metadata
        year = str(m.session_year) if m.session_year else "Specimen"
        label = (
            f"{m.subject_code}/{m.paper_number}{m.paper_variant} "
            f"{m.session_month} {year} — {json_path}"
        )
        choices.append(label)
    return choices


def parse_mark_scheme_path_from_label(label: str) -> Path:
    return Path(label.rsplit(" — ", 1)[-1].strip())


def extracted_to_table_rows(extracted: ExtractedAnswers) -> list[list[str]]:
    """Convert ExtractedAnswers into editable Dataframe rows (5 columns)."""
    return [
        [
            a.question_id,
            a.answer,
            f"{a.confidence:.0%}",
            a.working_out or "",
            a.source_region or "",
        ]
        for a in extracted.answers
    ]


def rows_to_reviewed_answers_json(rows: list[list[str]]) -> str:
    """Take edited Dataframe rows and produce {question_id: answer} JSON."""
    out: dict[str, str] = {}
    for row in rows:
        if not row or not row[0]:
            continue
        out[str(row[0])] = str(row[1]) if len(row) > 1 else ""
    return json.dumps(out)


def save_correction_artifacts(
    output_dir: Path,
    mark_scheme_label: str,
    extracted_answers_json: str,
    reviewed_answers_json: str,
    accuracy_report_dict: dict[str, Any],
    student_id: str | None = None,
) -> Path:
    """Persist extracted/reviewed/report files under output_dir/<subject>/<session>/<paper>__<ts>/.

    If student_id is non-empty, also appends a PaperRecord to the HistoryStore so the
    Past Results and Quiz tabs can reflect this paper.
    """
    from lemely.core.history import PaperRecord
    from lemely.io.history_store import HistoryStore, now_iso

    report = AccuracyReport.model_validate(accuracy_report_dict)
    meta = report.correction.metadata
    session = meta.session_month.replace("/", "")
    year = str(meta.session_year) if meta.session_year else "specimen"
    paper_code = f"{meta.subject_code}_{session}_{year}_p{meta.paper_number}{meta.paper_variant}"
    ts = datetime.datetime.now().strftime("%Y-%m-%d-%H%M%S")
    session_dir = output_dir / meta.subject_code / f"{session}_{year}" / f"{paper_code}__{ts}"
    session_dir.mkdir(parents=True, exist_ok=True)

    (session_dir / "extracted_answers.json").write_text(extracted_answers_json, encoding="utf-8")
    (session_dir / "reviewed_answers.json").write_text(reviewed_answers_json, encoding="utf-8")
    (session_dir / "accuracy_report.json").write_text(
        json.dumps(accuracy_report_dict, indent=2),
        encoding="utf-8",
    )

    if student_id:
        grade_pred = report.grade_prediction
        weakness = report.weaknesses
        record = PaperRecord(
            student_id=student_id,
            recorded_at=now_iso(),
            metadata=meta,
            awarded_marks=report.correction.awarded_marks,
            maximum_marks=report.correction.maximum_marks,
            percentage=grade_pred.percentage,
            grade=grade_pred.grade,
            weak_areas=weakness.weak_areas,
        )
        store = HistoryStore(output_dir / "history")
        store.append(student_id, record)

    return session_dir


# ----------------------------------------------------------------------
# Tab 3 — Subject result
# ----------------------------------------------------------------------


def build_subject_session_choices(output_dir: Path) -> list[str]:
    """Discover subject_code/session pairs from output_dir/<subject>/<session>/ structure."""
    choices: list[str] = []
    if not output_dir.exists():
        return choices
    for subject_dir in sorted(output_dir.iterdir()):
        if not subject_dir.is_dir() or not subject_dir.name.isdigit():
            continue
        for session_dir in sorted(subject_dir.iterdir()):
            if not session_dir.is_dir():
                continue
            paper_dirs = [p for p in session_dir.iterdir() if p.is_dir()]
            if not paper_dirs:
                continue
            choices.append(f"{subject_dir.name} / {session_dir.name} ({len(paper_dirs)} papers)")
    return choices


def load_papers_for_subject_session(
    output_dir: Path,
    subject_session_label: str,
) -> list[CorrectionResult]:
    """Load every accuracy_report.json under a given subject_code / session label."""
    subject_code, rest = subject_session_label.split(" / ", 1)
    session_name = rest.split(" (", 1)[0]
    session_dir = output_dir / subject_code / session_name
    papers: list[CorrectionResult] = []
    for paper_dir in sorted(session_dir.iterdir()):
        report_path = paper_dir / "accuracy_report.json"
        if not report_path.exists():
            continue
        report = AccuracyReport.model_validate_json(report_path.read_text(encoding="utf-8"))
        papers.append(report.correction)
    return papers


# ----------------------------------------------------------------------
# Tab 1 — Library
# ----------------------------------------------------------------------


def build_library_table_rows(sources_dir: Path) -> list[list[str]]:
    """Return rows [relative_path, status, subject_code, paper_num, session] for the library dataframe."""
    rows: list[list[str]] = []
    for entry in index_source_library(sources_dir):
        json_path = entry.source_path.with_suffix(".json")
        status = "✓ Parsed" if json_path.exists() else "⚠ Needs parsing"
        m = entry.metadata
        year = str(m.session_year) if m.session_year else "Specimen"
        paper_num = f"{m.paper_number}{m.paper_variant}"
        session = f"{m.session_month} {year}"
        rel_path = str(entry.source_path.relative_to(sources_dir))
        rows.append([rel_path, status, m.subject_code, paper_num, session])
    return rows


# ----------------------------------------------------------------------
# Tab 4 — Past Results
# ----------------------------------------------------------------------


def history_to_table_rows(history: StudentHistory) -> list[list[str]]:
    """Convert StudentHistory to displayable rows."""
    rows: list[list[str]] = []
    for record in history.records:
        m = record.metadata
        str(m.session_year) if m.session_year else "Specimen"
        subject = f"{m.subject_code}"
        paper = f"P{m.paper_number}{m.paper_variant}"
        rows.append(
            [
                record.recorded_at[:10],  # date portion of ISO-8601
                subject,
                paper,
                str(record.awarded_marks),
                str(record.maximum_marks),
                f"{record.percentage:.1f}%",
                record.grade,
            ]
        )
    return rows


def build_history_trend_markdown(history: StudentHistory) -> str:
    """Return a short trend summary markdown string for the history tab."""
    records = history.records
    n = len(records)
    if n == 0:
        return "*No records found for this student.*"
    latest = records[-1]
    latest_pct = latest.percentage
    latest_grade = latest.grade
    if n >= 2:
        prior_pct = records[-2].percentage
        delta = latest_pct - prior_pct
        sign = "+" if delta >= 0 else ""
        trend_str = f"Trend: {sign}{delta:.1f}pp vs prior attempt."
    else:
        trend_str = "Trend: first attempt recorded."
    return (
        f"**{n} paper{'s' if n != 1 else ''} recorded.** "
        f"Latest: {latest_pct:.1f}% ({latest_grade}). "
        f"{trend_str}"
    )
