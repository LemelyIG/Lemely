"""Pair extracted question-paper leaves with a parsed mark scheme (P4.1).

Closes the D3.7 prerequisite: ``lemely.io.det.question_papers`` extracts
stems from question-paper PDFs; this module joins those stems to marking
points **by question ref** and builds
``lemely.db.question_bank_repo.NewBankQuestion`` rows through the existing
writer — it does not fork a second insert path.

**A leaf is only bank-eligible when every one of these holds:**

1. ``has_figure`` is ``False`` — a figure-dependent stem is not a faithful
   representation of the question (``docs/LEMELY_UI_SPEC.md`` §1.4).
2. The ref has an exact match in the paired mark scheme, and that match is a
   **leaf** (no ``parts``) — a container node (e.g. "2a" grouping "2a_i" /
   "2a_ii") carries no marking points of its own.
3. The matched mark-scheme question carries at least one marking point (a
   non-empty ``answer_points`` for point-based types, or is MCQ) — the bank
   feeds a marking engine, and a question with nothing to mark against
   cannot be marked.
4. The extracted ``marks`` annotation is present and agrees exactly with the
   mark scheme's ``marks`` for that question — a disagreement is a sign the
   deterministic extractor mis-split the numbering tree for that leaf, not
   something to average away.

Every leaf that fails one of these is counted under its specific reason in
:class:`QuestionPaperIngestReport`, never silently dropped — a truthful
partial yield beats a silent 100% (the brief's own words).

**Idempotency.** No ``Paper`` row is created or looked up here (P4.1 does
not touch the ``papers``/``mark_schemes`` DB tables — the paired mark scheme
is read from its on-disk parsed JSON, same as
``lemely.io.mark_schemes.process_mark_scheme_batch`` already caches it), so
the DB's partial unique index on ``(paper_id, source_question_id)`` does not
apply. Idempotency is therefore enforced at this layer instead, keyed on
``(subject_code, source_question_id)`` exactly as briefed:
``source_question_id`` is built as ``f"{qp_stem}#{ref}"`` (not just ``ref``)
so two different papers of the same subject can never collide on it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import structlog
from pydantic import ValidationError

from lemely.core.difficulty import infer_difficulty
from lemely.core.loose_schemas import MarkScheme, QuestionType
from lemely.core.loose_schemas import Question as SchemeQuestion
from lemely.db.models.enums import DifficultySource, QuestionSource
from lemely.db.question_bank_repo import NewBankQuestion
from lemely.io.det.question_papers import DeterministicQuestionPaperExtractor
from lemely.io.metadata import parse_caie_qp_filename_metadata, question_paper_to_mark_scheme_stem
from lemely.runtime.errors import ParseError

if TYPE_CHECKING:
    from lemely.core.question_papers import QuestionPaper, QuestionPaperQuestion
    from lemely.db.question_bank_repo import QuestionBankService

log = structlog.get_logger(__name__)

#: Mirrors ``lemely.io.mark_schemes.ParserCallback`` — lets tests inject a
#: fake extractor instead of running pdfplumber over a real PDF.
QuestionPaperExtractorCallback = Callable[[Path], "QuestionPaper"]


@dataclass(frozen=True, slots=True)
class QuestionPaperIngestReport:
    """Per-run counts from :func:`ingest_question_papers_dir`.

    Every count here is mutually exclusive per leaf — a leaf is attributed
    to exactly one bucket, so the buckets sum to the total leaves examined
    across every successfully-extracted paper.
    """

    papers_scanned: int
    papers_extract_failed: int
    papers_no_scheme: int
    papers_reconcile_mismatch: int
    leaves_examined: int
    produced: int
    skipped_already_banked: int
    skipped_figure: int
    skipped_no_scheme_match: int
    skipped_no_marking_points: int
    skipped_marks_mismatch: int
    extract_failures: list[str] = field(default_factory=list)
    no_scheme_papers: list[str] = field(default_factory=list)
    reconcile_mismatch_papers: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class _PaperOutcome:
    rows: list[NewBankQuestion]
    leaves_examined: int
    skipped_figure: int
    skipped_no_scheme_match: int
    skipped_no_marking_points: int
    skipped_marks_mismatch: int
    skipped_already_banked: int
    reconcile_mismatch: bool


def _find_scheme_path(qp_path: Path, schemes_dir: Path) -> Path | None:
    ms_stem = question_paper_to_mark_scheme_stem(qp_path.stem)
    candidate = schemes_dir / f"{ms_stem}.json"
    return candidate if candidate.exists() else None


def _load_scheme(path: Path) -> MarkScheme | None:
    try:
        return MarkScheme.model_validate_json(path.read_text(encoding="utf-8"))
    except (ValidationError, OSError, ValueError) as exc:
        log.warning("question_paper_ingest_scheme_unreadable", path=str(path), error=str(exc))
        return None


def _has_marking_points(scheme_question: SchemeQuestion) -> bool:
    if scheme_question.type == QuestionType.MCQ:
        return scheme_question.mcq_answer is not None
    return bool(scheme_question.answer_points)


def _build_row(
    qp_question: QuestionPaperQuestion,
    scheme_question: SchemeQuestion,
    *,
    subject_code: str,
    source_question_id: str,
) -> NewBankQuestion:
    is_mcq = scheme_question.type == QuestionType.MCQ
    mcq_options: list[str] | None = None
    mcq_answer: str | None = None
    mark_scheme_points: list[str] = []
    if is_mcq:
        if qp_question.options:
            mcq_options = [
                f"{letter} {text}" for letter, text in sorted(qp_question.options.items())
            ]
        mcq_answer = scheme_question.mcq_answer.value if scheme_question.mcq_answer else None
    else:
        mark_scheme_points = [p.point for p in scheme_question.answer_points]

    band = infer_difficulty(scheme_question.marks, scheme_question.type.value)
    return NewBankQuestion(
        subject_code=subject_code,
        source=QuestionSource.past_paper,
        difficulty=band,
        difficulty_source=DifficultySource.inferred_from_marks,
        question_type=scheme_question.type.value,
        prompt=qp_question.stem,
        total_marks=scheme_question.marks,
        topic=None,  # topic classification is P4.2 — not faked here
        mark_scheme_points=mark_scheme_points,
        mcq_options=mcq_options,
        mcq_answer=mcq_answer,
        source_question_id=source_question_id,
    )


def _pair_paper(
    qp: QuestionPaper,
    scheme: MarkScheme,
    *,
    qp_stem: str,
    already_banked: set[str],
) -> _PaperOutcome:
    rows: list[NewBankQuestion] = []
    skipped_figure = 0
    skipped_no_scheme_match = 0
    skipped_no_marking_points = 0
    skipped_marks_mismatch = 0
    skipped_already_banked = 0

    for question in qp.questions:
        if question.has_figure:
            skipped_figure += 1
            continue

        scheme_question = scheme.get_question_by_id(question.ref)
        if scheme_question is None or scheme_question.parts:
            # No match, or matched a container node (parts != []) rather
            # than a markable leaf — see module docstring rule 2.
            skipped_no_scheme_match += 1
            continue

        if not _has_marking_points(scheme_question):
            skipped_no_marking_points += 1
            continue

        if question.marks is None or question.marks != scheme_question.marks:
            skipped_marks_mismatch += 1
            continue

        source_question_id = f"{qp_stem}#{question.ref}"
        if source_question_id in already_banked:
            skipped_already_banked += 1
            continue

        rows.append(
            _build_row(
                question,
                scheme_question,
                subject_code=qp.metadata.subject_code,
                source_question_id=source_question_id,
            )
        )

    reconcile_mismatch = (
        qp.metadata.stated_total_marks is not None
        and qp.extracted_marks_total != qp.metadata.stated_total_marks
    )

    return _PaperOutcome(
        rows=rows,
        leaves_examined=len(qp.questions),
        skipped_figure=skipped_figure,
        skipped_no_scheme_match=skipped_no_scheme_match,
        skipped_no_marking_points=skipped_no_marking_points,
        skipped_marks_mismatch=skipped_marks_mismatch,
        skipped_already_banked=skipped_already_banked,
        reconcile_mismatch=bool(reconcile_mismatch),
    )


def ingest_question_papers_dir(
    service: QuestionBankService,
    qp_dir: str | Path,
    schemes_dir: str | Path,
    *,
    extractor: QuestionPaperExtractorCallback | None = None,
) -> QuestionPaperIngestReport:
    """Ingest every CAIE question-paper PDF under ``qp_dir`` into the bank.

    ``schemes_dir`` is the cache directory ``lemely.io.mark_schemes.
    process_mark_scheme_batch`` already writes parsed ``MarkScheme`` JSON
    into (``outputs/schemes`` by default) — this function reads that cache,
    it does not parse mark schemes itself.

    Safe to re-run: rows already present for a given
    ``(subject_code, source_question_id)`` are skipped, not duplicated (see
    module docstring on why the DB's own unique index cannot do this here).
    """
    extractor = extractor or DeterministicQuestionPaperExtractor()
    qp_dir = Path(qp_dir)
    schemes_dir = Path(schemes_dir)

    qp_paths: list[Path] = []
    for pdf_path in sorted(qp_dir.rglob("*.pdf")):
        try:
            parse_caie_qp_filename_metadata(pdf_path)
        except ValueError:
            continue
        qp_paths.append(pdf_path)

    papers_scanned = 0
    papers_extract_failed = 0
    papers_no_scheme = 0
    papers_reconcile_mismatch = 0
    leaves_examined = 0
    skipped_figure = 0
    skipped_no_scheme_match = 0
    skipped_no_marking_points = 0
    skipped_marks_mismatch = 0
    skipped_already_banked = 0
    extract_failures: list[str] = []
    no_scheme_papers: list[str] = []
    reconcile_mismatch_papers: list[str] = []
    all_rows: list[NewBankQuestion] = []

    # Loaded once up front: every already-banked past-paper source id, so
    # each paper's pairing pass can skip without a per-row query.
    already_banked = service.existing_source_question_ids(source=QuestionSource.past_paper)

    for qp_path in qp_paths:
        papers_scanned += 1
        try:
            qp = extractor(qp_path)
        except ParseError as exc:
            papers_extract_failed += 1
            extract_failures.append(f"{qp_path.name}: {exc}")
            log.warning("question_paper_ingest_extract_failed", path=str(qp_path), error=str(exc))
            continue

        scheme_path = _find_scheme_path(qp_path, schemes_dir)
        if scheme_path is None:
            papers_no_scheme += 1
            no_scheme_papers.append(qp_path.name)
            leaves_examined += len(qp.questions)
            continue

        scheme = _load_scheme(scheme_path)
        if scheme is None:
            papers_no_scheme += 1
            no_scheme_papers.append(qp_path.name)
            leaves_examined += len(qp.questions)
            continue

        outcome = _pair_paper(qp, scheme, qp_stem=qp_path.stem, already_banked=already_banked)
        leaves_examined += outcome.leaves_examined
        skipped_figure += outcome.skipped_figure
        skipped_no_scheme_match += outcome.skipped_no_scheme_match
        skipped_no_marking_points += outcome.skipped_no_marking_points
        skipped_marks_mismatch += outcome.skipped_marks_mismatch
        skipped_already_banked += outcome.skipped_already_banked
        if outcome.reconcile_mismatch:
            papers_reconcile_mismatch += 1
            reconcile_mismatch_papers.append(qp_path.name)
        all_rows.extend(outcome.rows)
        already_banked.update(
            row.source_question_id for row in outcome.rows if row.source_question_id
        )

    ids = service.add_questions(all_rows)

    return QuestionPaperIngestReport(
        papers_scanned=papers_scanned,
        papers_extract_failed=papers_extract_failed,
        papers_no_scheme=papers_no_scheme,
        papers_reconcile_mismatch=papers_reconcile_mismatch,
        leaves_examined=leaves_examined,
        produced=len(ids),
        skipped_already_banked=skipped_already_banked,
        skipped_figure=skipped_figure,
        skipped_no_scheme_match=skipped_no_scheme_match,
        skipped_no_marking_points=skipped_no_marking_points,
        skipped_marks_mismatch=skipped_marks_mismatch,
        extract_failures=extract_failures,
        no_scheme_papers=no_scheme_papers,
        reconcile_mismatch_papers=reconcile_mismatch_papers,
    )


__all__ = ["QuestionPaperIngestReport", "ingest_question_papers_dir"]
