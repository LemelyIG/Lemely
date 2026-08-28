"""Deterministic CAIE mark-scheme PDF parser — orchestrator.

Wires together all pipeline stages into ``DeterministicMarkSchemeParser``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog
from pydantic import ValidationError

from lemely.core.loose_schemas import MarkScheme, PaperType, Question
from lemely.io.det import gmp as _gmp
from lemely.io.det import metadata as _meta
from lemely.io.det import reconcile as _reconcile
from lemely.io.det.columns import detect_columns
from lemely.io.det.mcq import MCQParseDiagnostics, parse_mcq_tables
from lemely.io.det.rows import build_questions
from lemely.io.det.tables import select_tables
from lemely.runtime.config import DetParserSettings
from lemely.runtime.errors import ParseError

if TYPE_CHECKING:
    from pathlib import Path

log = structlog.get_logger(__name__)


class DeterministicMarkSchemeParser:
    """Parse a CAIE mark-scheme PDF to ``MarkScheme`` without Gemini API calls.

    Raises ``ParseError`` when:
    - The document contains question types that require AI assistance
      (levels-based, indicative-content, image-only pages).
    - Critical metadata cannot be extracted.
    - The parsed leaf-mark total does not match ``maximum_mark`` within the
      configured tolerance (routes the paper to Gemini via the chain).

    Args:
        cfg: Parser settings.  Defaults to ``DetParserSettings()`` (strict
             reconciliation on, tolerance 0) so existing call sites that omit
             this argument keep working without change.
    """

    def __init__(self, cfg: DetParserSettings | None = None) -> None:
        self._cfg = cfg or DetParserSettings()

    def __call__(self, pdf_path: Path) -> MarkScheme:
        try:
            import pdfplumber
        except ImportError as exc:
            raise ImportError(
                "pdfplumber is required for deterministic parsing. "
                "Install it with: pip install pdfplumber"
            ) from exc

        cfg = self._cfg
        log.debug("det_parser_start", source=pdf_path.name)

        with pdfplumber.open(pdf_path) as pdf:
            # --- Stage 1: metadata -----------------------------------------
            metadata = _meta.extract_metadata(
                pdf,
                pdf_path,
                skip_line_tokens=cfg.skip_line_tokens,
            )
            log.debug(
                "det_parser_metadata",
                source=pdf_path.name,
                subject=metadata.subject,
                paper_type=metadata.paper_type,
                maximum_mark=metadata.maximum_mark,
            )

            # --- Stage 2: GMP ----------------------------------------------
            _gmp.extract_gmp(
                pdf,
                metadata,
                pages_start=cfg.gmp_pages_start,
                pages_end=cfg.gmp_pages_end,
            )

            # --- Stage 3: questions ----------------------------------------
            questions = self._extract_questions(pdf, metadata)

        # --- Stage 4: reconcile (outside pdfplumber context) ---------------
        _reconcile.check(
            questions,
            metadata,
            escalate_on_mark_mismatch=cfg.escalate_on_mark_mismatch,
            mark_reconcile_tolerance=cfg.mark_reconcile_tolerance,
            escalate_on_defaulted_marks=cfg.escalate_on_defaulted_marks,
            escalate_on_duplicate_leaf_ids=cfg.escalate_on_duplicate_leaf_ids,
            source=pdf_path.name,
        )

        # --- Stage 5: pydantic validation ----------------------------------
        try:
            return MarkScheme(metadata=metadata, questions=questions)
        except ValidationError as exc:
            raise ParseError(f"MarkScheme validation failed for {pdf_path.name}: {exc}") from exc

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _extract_questions(self, pdf: Any, metadata: Any) -> list[Question]:
        cfg = self._cfg

        if metadata.paper_type == PaperType.MCQ:
            # MCQ papers have no GMP section; questions start on page 1.
            all_tables: list[list[list[str | None]]] = []
            for page in pdf.pages[1:]:
                all_tables.extend(page.extract_tables())
            if not all_tables:
                raise ParseError(
                    f"No tables found in {metadata.source_document or 'PDF'} — "
                    "may be an image-only or scan-based PDF"
                )
            mcq_diag = MCQParseDiagnostics()
            questions_mcq = parse_mcq_tables(
                all_tables,
                source=metadata.source_document or "unknown",
                diagnostics=mcq_diag,
            )
            # The reconciler compares MARKS against maximum_mark; this compares
            # QUESTION COUNTS, which is not the same check. On an MCQ paper the
            # two coincide only because every question carries one mark, and a
            # drop compensated by an overcount elsewhere would net out of the
            # mark comparison while still losing questions (#94).
            expected = metadata.maximum_mark
            if expected and len(questions_mcq) < expected:
                log.warning(
                    "det_mcq_question_shortfall",
                    source=metadata.source_document or "unknown",
                    parsed_questions=len(questions_mcq),
                    # One mark per MCQ question makes maximum_mark a proxy for
                    # the question count, not a declared count — the papers do
                    # not print one. Stated here rather than implied.
                    expected_questions_proxy=expected,
                    shortfall=expected - len(questions_mcq),
                    **mcq_diag.as_log_fields(),
                )
            return questions_mcq

        # Theory / practical papers
        all_tables = select_tables(
            pdf,
            page_start=2,
            max_mark=cfg.max_mark_per_point,
        )
        if not all_tables:
            raise ParseError(
                f"No tables found in {metadata.source_document or 'PDF'} — "
                "may be an image-only or scan-based PDF"
            )

        log.debug(
            "det_parser_tables_selected",
            source=metadata.source_document,
            table_count=len(all_tables),
        )
        return self._parse_theory_tables(all_tables)

    def _parse_theory_tables(self, tables: list[list[list[str | None]]]) -> list[Question]:
        cfg = self._cfg

        # Merge rows across tables, filtering out header rows.
        merged: list[list[str | None]] = []
        for table in tables:
            for row in table:
                if not row or len(row) < 2:
                    continue
                cells_lower = {(c or "").strip().lower() for c in row}
                if cells_lower & cfg.header_keywords:
                    continue
                merged.append(row)

        if not merged:
            raise ParseError("No valid theory table rows found — expected tables with ≥ 2 columns")

        ncols = max(len(r) for r in merged)
        if ncols < 2:
            raise ParseError(f"Table has fewer than 2 columns ({ncols} found)")

        layout = detect_columns(merged, max_mark=cfg.max_mark_per_point)
        log.debug(
            "det_parser_columns",
            q_col=layout.q_col,
            marks_col=layout.marks_col,
            guidance_col=layout.guidance_col,
            answer_col_end=layout.answer_col_end,
        )

        return build_questions(
            merged,
            layout,
            max_mark=cfg.max_mark_per_point,
            header_keywords=cfg.header_keywords,
        )
