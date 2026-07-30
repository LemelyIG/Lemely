"""Deterministic mark scheme parser for CAIE PDFs.

Extracts a structured ``MarkScheme`` using ``pdfplumber`` table extraction —
no Gemini API call required.  Raises ``ParseError`` for question types that
need AI assistance (levels-based, indicative content, image-only pages) so the
caller can fall back to ``GeminiMarkSchemeParser``.
"""

from __future__ import annotations

import contextlib
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from lemely.core.loose_schemas import (
    AnswerPoint,
    MarkScheme,
    MarkSchemeMetadata,
    MCQAnswer,
    PaperType,
    Question,
    QuestionType,
    SchemeFormat,
    SessionMonth,
    Tier,
)
from lemely.io.metadata import parse_caie_filename_metadata
from lemely.runtime.errors import ParseError

if TYPE_CHECKING:
    pass  # pdfplumber types are untyped; imported lazily

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

# Matches "0625/12" → groups: subject_code=0625, paper_number=1, paper_variant=2
_PAPER_CODE_RE = re.compile(r"\b(\d{4})/(\d)(\d)\b")

# Maximum mark line on the cover page
_MAX_MARK_RE = re.compile(r"[Mm]aximum\s+[Mm]ark\s*[:\s]+(\d+)")

# Four-digit year
_YEAR_RE = re.compile(r"\b(20\d{2})\b")

# GMP numbered list markers: "1." / "GMP 1" / "GMP1"
_GMP_SPLIT_RE = re.compile(r"(?m)^(?:GMP\s*\d+|\d+\.)\s+")

# Question-number column patterns
_TOP_LEVEL_RE = re.compile(r"^\d+$")  # "1", "2", "40"
_LEVEL_2_RE = re.compile(r"^\([a-z]\)$")  # "(a)", "(b)"
_LEVEL_3_RE = re.compile(r"^\([ivx]+\)$")  # "(i)", "(ii)", "(iv)"

# Compound Q-number: digit prefix + zero or more parenthesised sub-parts
# Matches "1", "1(a)", "2(a)(i)", "1(g)(ii)" etc.
_COMPOUND_Q_RE = re.compile(r"^(\d+)((?:\([a-z]+\))*)$")

# ParseError triggers in the answer column
_LEVEL_DESCRIPTOR_Q_RE = re.compile(r"^[Ll]evel\s+\d+$")
_BAND_LANGUAGE_RE = re.compile(r"descriptors|marks\s+available|AO\d", re.IGNORECASE)
_INDICATIVE_CONTENT_RE = re.compile(r"indicative\s+content", re.IGNORECASE)

# MCQ valid answer letters
_MCQ_LETTERS: frozenset[str] = frozenset("ABCD")

# Session month patterns (checked in priority order)
_SESSION_PATTERNS: list[tuple[re.Pattern[str], SessionMonth]] = [
    (re.compile(r"May[/–\-]June|May/Jun", re.IGNORECASE), SessionMonth.MAY_JUNE),
    (re.compile(r"Oct(?:ober)?[/–\-]Nov(?:ember)?", re.IGNORECASE), SessionMonth.OCT_NOV),
    (re.compile(r"Feb(?:ruary)?[/–\-]Mar(?:ch)?", re.IGNORECASE), SessionMonth.FEB_MAR),
    (re.compile(r"Specimen", re.IGNORECASE), SessionMonth.SPECIMEN),
]

# Words that indicate a line is NOT the subject name
_SKIP_LINE_TOKENS = frozenset(
    ["cambridge", "igcse", "mark scheme", "©", "maximum", "published", "confidential"]
)


# ---------------------------------------------------------------------------
# Public classes
# ---------------------------------------------------------------------------


class DeterministicMarkSchemeParser:
    """Parse a CAIE mark-scheme PDF to ``MarkScheme`` without Gemini API calls.

    Raises ``ParseError`` if the document contains question types that require
    AI assistance (levels-based, indicative content, image-only pages) or if
    critical metadata cannot be extracted.
    """

    def __call__(self, pdf_path: Path) -> MarkScheme:
        try:
            import pdfplumber
        except ImportError as exc:
            raise ImportError(
                "pdfplumber is required for deterministic parsing. "
                "Install it with: pip install pdfplumber"
            ) from exc

        with pdfplumber.open(pdf_path) as pdf:
            metadata = self._extract_metadata(pdf, pdf_path)
            self._extract_gmp(pdf, metadata)
            questions = self._extract_questions(pdf, metadata)

        try:
            return MarkScheme(metadata=metadata, questions=questions)
        except ValidationError as exc:
            raise ParseError(f"MarkScheme validation failed for {pdf_path.name}: {exc}") from exc

    # ------------------------------------------------------------------
    # Metadata extraction
    # ------------------------------------------------------------------

    def _extract_metadata(self, pdf: Any, pdf_path: Path) -> MarkSchemeMetadata:
        """Build ``MarkSchemeMetadata`` from filename (primary) and cover page (fallback)."""
        cover_text = (pdf.pages[0].extract_text() or "") if pdf.pages else ""

        # --- Filename (authoritative for coded fields) ---
        subject_code: str | None = None
        paper_number: int | None = None
        paper_variant: int | None = None
        session_month: SessionMonth | None = None
        session_year: int | None = None
        source_document = pdf_path.name

        try:
            fm = parse_caie_filename_metadata(pdf_path)
            subject_code = fm.subject_code
            paper_number = fm.paper_number
            paper_variant = fm.paper_variant
            session_month = self._parse_session_month(fm.session_month)
            session_year = fm.session_year
        except ValueError:
            pass

        # --- Cover-page fallbacks for coded fields ---
        if subject_code is None or paper_number is None:
            m = _PAPER_CODE_RE.search(cover_text)
            if m:
                subject_code = subject_code or m.group(1)
                paper_number = paper_number or int(m.group(2))
                paper_variant = paper_variant or int(m.group(3))

        if subject_code is None:
            raise ParseError(f"Cannot determine subject_code for {pdf_path.name}")
        if paper_number is None or paper_variant is None:
            raise ParseError(f"Cannot determine paper_number/paper_variant for {pdf_path.name}")

        # --- Session month (cover page if filename didn't supply it) ---
        if session_month is None:
            for pattern, month_val in _SESSION_PATTERNS:
                if pattern.search(cover_text):
                    session_month = month_val
                    break
            else:
                session_month = SessionMonth.MAY_JUNE  # last-resort default

        # --- Session year ---
        if session_year is None and session_month != SessionMonth.SPECIMEN:
            m2 = _YEAR_RE.search(cover_text)
            if m2:
                session_year = int(m2.group(1))

        # --- Maximum mark ---
        m3 = _MAX_MARK_RE.search(cover_text)
        if not m3:
            raise ParseError(f"Cannot extract maximum_mark from cover page of {pdf_path.name}")
        maximum_mark = int(m3.group(1))

        # --- Derived fields ---
        subject = self._extract_subject_name(cover_text, subject_code)
        paper_type = self._detect_paper_type(cover_text, paper_number)
        scheme_format = (
            SchemeFormat.MCQ if paper_type == PaperType.MCQ else SchemeFormat.POINT_BASED
        )
        tier = self._detect_tier(cover_text)
        published = "Published" in cover_text

        return MarkSchemeMetadata(
            subject=subject,
            subject_code=subject_code,
            paper_number=paper_number,
            paper_variant=paper_variant,
            session_month=session_month,
            session_year=session_year if session_month != SessionMonth.SPECIMEN else None,
            paper_type=paper_type,
            tier=tier,
            maximum_mark=maximum_mark,
            scheme_format=scheme_format,
            published=published,
            source_document=source_document,
        )

    @staticmethod
    def _parse_session_month(s: str) -> SessionMonth:
        for pattern, val in _SESSION_PATTERNS:
            if pattern.search(s):
                return val
        return SessionMonth.MAY_JUNE

    @staticmethod
    def _extract_subject_name(cover_text: str, subject_code: str) -> str:
        """Return the subject name from the cover page, falling back to the code."""
        for line in cover_text.splitlines():
            line = line.strip()
            if not line or len(line) < 4:
                continue
            lower = line.lower()
            # Skip known non-subject lines
            if any(tok in lower for tok in _SKIP_LINE_TOKENS):
                continue
            if subject_code in line:
                continue
            # Skip session month lines
            if any(p.search(line) for p, _ in _SESSION_PATTERNS):
                continue
            # Skip pure-digit or very short tokens
            if line[0].isdigit():
                continue
            return line
        return f"CAIE Subject {subject_code}"

    @staticmethod
    def _detect_paper_type(cover_text: str, paper_number: int) -> PaperType:
        lower = cover_text.lower()
        if "multiple choice" in lower or paper_number == 1:
            return PaperType.MCQ
        if "alternative to practical" in lower or paper_number == 6:
            return PaperType.ALTERNATIVE_PRACTICAL
        if "practical" in lower:
            return PaperType.PRACTICAL
        if "core" in lower:
            return PaperType.THEORY_CORE
        if "extended" in lower:
            return PaperType.THEORY_EXTENDED
        return PaperType.THEORY_EXTENDED

    @staticmethod
    def _detect_tier(cover_text: str) -> Tier | None:
        lower = cover_text.lower()
        if "core" in lower:
            return Tier.CORE
        if "extended" in lower:
            return Tier.EXTENDED
        return None

    # ------------------------------------------------------------------
    # GMP extraction
    # ------------------------------------------------------------------

    def _extract_gmp(self, pdf: Any, metadata: MarkSchemeMetadata) -> None:
        """Populate ``metadata.generic_marking_principles`` from pages 1–3."""
        gmp_pages = pdf.pages[1:4] if len(pdf.pages) > 1 else []
        all_text = "\n".join((p.extract_text() or "") for p in gmp_pages)

        # Split on numbered markers; re.split with a capturing group gives:
        # [pre_text, marker1, body1, marker2, body2, ...]
        parts = _GMP_SPLIT_RE.split(all_text)

        principles: list[str] = []
        # parts[0] is the pre-marker prefix (usually the section header); skip it.
        # Each (marker, body) pair sits at indices (odd_skip, even+1).
        # Since we use a non-capturing split, we get alternating [pre, body, body, …]
        # Actually: split without a capturing group gives only the text between
        # delimiters — so parts[1:] are the bodies of each principle.
        for body in parts[1:]:
            paragraph = body.split("\n\n")[0].strip()
            if paragraph:
                principles.append(paragraph)

        if principles:
            metadata.generic_marking_principles = principles

    # ------------------------------------------------------------------
    # Question extraction (dispatch)
    # ------------------------------------------------------------------

    def _extract_questions(self, pdf: Any, metadata: MarkSchemeMetadata) -> list[Question]:
        """Collect tables from question pages and route to MCQ or theory parser."""
        all_tables: list[list[list[str | None]]] = []

        if metadata.paper_type == PaperType.MCQ:
            # MCQ papers have no GMP section; questions start on page 1.
            for page in pdf.pages[1:]:
                all_tables.extend(page.extract_tables())
        else:
            # Theory papers: skip cover (page 0) and GMP pages (typically 1–2).
            # Fall back to page 1 when the document is shorter than expected.
            for start in (2, 1):
                for page in pdf.pages[start:]:
                    tables = page.extract_tables()
                    if tables:
                        all_tables.extend(tables)
                if all_tables:
                    break

        if not all_tables:
            raise ParseError(
                f"No tables found in {metadata.source_document or 'PDF'} — "
                "may be an image-only or scan-based PDF"
            )

        if metadata.paper_type == PaperType.MCQ:
            return self._parse_mcq_tables(all_tables)
        return self._parse_theory_tables(all_tables)

    # ------------------------------------------------------------------
    # MCQ parser
    # ------------------------------------------------------------------

    def _parse_mcq_tables(self, tables: list[list[list[str | None]]]) -> list[Question]:
        """Extract an MCQ answer key from tables whose answer column contains only A/B/C/D."""
        all_questions: list[Question] = []
        seen_ids: set[str] = set()

        for table in tables:
            if not table:
                continue
            data_rows = [r for r in table if r and sum(1 for c in r if (c or "").strip()) >= 2]
            if not data_rows:
                continue

            answer_col = _find_mcq_answer_col(data_rows)
            if answer_col is None:
                continue

            for row in data_rows:
                if len(row) <= answer_col:
                    continue
                q_cell = (row[0] or "").strip()
                ans_cell = (row[answer_col] or "").strip().upper()

                if not q_cell.isdigit() or ans_cell not in _MCQ_LETTERS:
                    continue
                if q_cell in seen_ids:
                    continue  # skip duplicate (same table repeated across pages)

                try:
                    mcq_answer = MCQAnswer(ans_cell)
                except ValueError:
                    continue

                seen_ids.add(q_cell)
                all_questions.append(
                    Question(
                        id=q_cell,
                        marks=1,
                        type=QuestionType.MCQ,
                        mcq_answer=mcq_answer,
                    )
                )

        if not all_questions:
            raise ParseError(
                "Could not find an MCQ answer-key table "
                "(expected a table with a column containing only A/B/C/D)"
            )
        return all_questions

    # ------------------------------------------------------------------
    # Theory parser
    # ------------------------------------------------------------------

    def _parse_theory_tables(self, tables: list[list[list[str | None]]]) -> list[Question]:
        """Merge all theory tables and run the row state machine."""
        _HEADER_KEYWORDS: frozenset[str] = frozenset(
            {"question", "answer", "marks", "guidance", "notes"}
        )

        merged: list[list[str | None]] = []
        for table in tables:
            for row in table:
                if not row or len(row) < 2:
                    continue
                # Skip table-header rows (e.g. ['', 'Question', '', '', 'Answer', …])
                # that appear at the top of each page's table and would otherwise
                # be mistaken for continuation answer points.
                cells_lower = {(c or "").strip().lower() for c in row}
                if cells_lower & _HEADER_KEYWORDS:
                    continue
                merged.append(row)

        if not merged:
            raise ParseError("No valid theory table rows found — expected tables with ≥ 2 columns")

        ncols = max(len(r) for r in merged)
        if ncols < 2:
            raise ParseError(f"Table has fewer than 2 columns ({ncols} found)")

        # Column layout:
        #   col 0        → question number
        #   col 1..m-1   → answer / mark-point text (merged; may skip None cols)
        #   col m        → marks (integer)
        #   col m+1      → guidance / notes (only when present between answer and marks)
        #
        # For standard 3-col tables (q, answer, marks): marks_col=2, no guidance.
        # For standard 4-col tables (q, answer, guidance, marks): marks_col=3.
        # For sparse 9-col CAIE tables (data at 0, 3, 6): marks_col=6, no guidance.
        # _find_marks_col_theory handles all these by scanning right-to-left.
        q_col = 0
        marks_col = _find_marks_col_theory(merged, ncols)
        guidance_col: int | None = None
        # Only treat col marks_col-1 as guidance when the table is the classic
        # 4-column format (exactly ncols==4 with dense data), to avoid false
        # positives on sparse wide tables.
        if ncols == 4 and marks_col == 3:
            guidance_col = 2
        answer_col_end = guidance_col if guidance_col is not None else marks_col

        return _run_theory_state_machine(merged, q_col, answer_col_end, guidance_col, marks_col)


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _find_mcq_answer_col(rows: list[list[str | None]]) -> int | None:
    """Return the rightmost column index whose non-empty values are all in A/B/C/D."""
    if not rows:
        return None
    num_cols = max(len(r) for r in rows)
    for col in range(num_cols - 1, 0, -1):  # rightmost first; skip col 0 (Q-number)
        values = [
            (r[col] or "").strip().upper() for r in rows if len(r) > col and (r[col] or "").strip()
        ]
        if values and all(v in _MCQ_LETTERS for v in values):
            return col
    return None


def _decompose_compound_q(q_cell: str) -> list[str] | None:
    """Parse a compound Q-number into its component labels.

    Examples::

        "1"        → ["1"]
        "1(a)"     → ["1", "(a)"]
        "2(a)(i)"  → ["2", "(a)", "(i)"]
        "(a)"      → None  (no digit prefix — handled by level patterns)
    """
    m = _COMPOUND_Q_RE.match(q_cell)
    if not m:
        return None
    parts: list[str] = [m.group(1)]
    for sub in re.findall(r"\([a-z]+\)", m.group(2)):
        parts.append(sub)
    return parts


def _find_marks_col_theory(merged: list[list[str | None]], ncols: int) -> int:
    """Return the rightmost column whose non-empty values are all small integers.

    This handles sparse 9-column CAIE tables where marks sit at col 6 rather
    than at the last column (col 8, which is a spacer full of ``None``).
    """
    for c in range(ncols - 1, -1, -1):
        non_empty = [((row[c] if c < len(row) else None) or "").strip() for row in merged]
        non_empty = [v for v in non_empty if v]
        if non_empty and all(v.isdigit() and int(v) <= 40 for v in non_empty):
            return c
    return ncols - 1  # fallback: last column


def _make_id(labels: list[str]) -> str:
    """Build a hierarchical question ID from raw label stack.

    Examples::

        ["1"]            → "1"
        ["1", "(a)"]     → "1a"
        ["1", "(a)", "(i)"] → "1a_i"
    """
    result = ""
    for i, lbl in enumerate(labels):
        raw = re.sub(r"[()]", "", lbl)  # strip parentheses
        if i == 0:
            result = raw
        elif i == 1:
            result += raw
        else:
            result += "_" + raw
    return result


def _run_theory_state_machine(
    rows: list[list[str | None]],
    q_col: int,
    answer_col_end: int,
    guidance_col: int | None,
    marks_col: int,
) -> list[Question]:
    """Row-by-row state machine that builds nested ``Question`` objects.

    State:
    - ``stack``               — Question objects at each nesting depth
    - ``labels``              — raw Q-cell text for each stack level (for ID construction)
    - ``current_points``      — AnswerPoints accumulating for the deepest question
    - ``next_is_alt``         — True when the next point should have ``is_alternative=True``
    - ``point_idx``           — sequential counter for AnswerPoint IDs within a question
    - ``q_row_had_answer``    — True when the Q-number row itself also carried answer text;
                                used to trigger a marks recount in flush() so that multi-row
                                questions (e.g. Q4 with 7×1-mark MPs) total correctly.
                                When the Q-number row has *no* answer text (marks=0 container
                                questions) the recount is skipped to preserve the explicit 0.

    Two Q-number formats are supported:

    * **Compound** (single cell, e.g. ``1(a)``, ``2(a)(i)``): the cell is
      decomposed into components; the stack is diffed against the common prefix
      of the previous question so intermediate parent nodes are created once and
      re-used across rows.

    * **Split** (separate cells, e.g. ``1`` then ``(a)`` then ``(i)``): handled
      by the ``_LEVEL_2_RE`` / ``_LEVEL_3_RE`` path.
    """
    top_level: list[Question] = []
    stack: list[Question] = []
    labels: list[str] = []
    current_points: list[AnswerPoint] = []
    next_is_alt = False
    point_idx = 0
    q_row_had_answer = False  # did the current question's own row carry an answer?

    def flush() -> None:
        nonlocal point_idx, next_is_alt, q_row_had_answer
        if stack and current_points:
            stack[-1].answer_points = list(current_points)
            # Only recount when the Q-number row itself carried answer text.
            # This covers multi-row questions (e.g. 7 MPs each on a separate row
            # where the first row's marks column is just MP1's mark, not the
            # question total).  Questions whose Q row has no answer text are
            # explicit containers (marks=0) and must not be overwritten.
            if q_row_had_answer:
                total = sum(p.marks for p in current_points if p.marks)
                if total > 0:
                    stack[-1].marks = total
        current_points.clear()
        point_idx = 0
        next_is_alt = False
        q_row_had_answer = False

    def unwind_to(target_depth: int) -> None:
        """Pop stack to ``target_depth``, linking each popped item to its parent."""
        while len(stack) > target_depth:
            popped = stack.pop()
            labels.pop()
            if stack:
                stack[-1].parts.append(popped)
            else:
                top_level.append(popped)

    def push_question(
        comp: str, is_leaf: bool, marks_int: int | None, guidance_cell: str | None
    ) -> None:
        """Append ``comp`` to labels/stack, creating a ``Question`` node."""
        labels.append(comp)
        new_id = _make_id(labels)
        parent_id = _make_id(labels[:-1]) if len(labels) > 1 else None
        q = Question(
            id=new_id,
            parent_id=parent_id,
            marks=marks_int if (is_leaf and marks_int is not None) else 0,
            type=QuestionType.RECALL,
            notes=guidance_cell if is_leaf else None,
        )
        stack.append(q)

    for row in rows:
        if not any((c or "").strip() for c in row):
            continue

        # Extract cells --------------------------------------------------
        q_cell = ((row[q_col] if len(row) > q_col else None) or "").strip()

        answer_parts = [
            (row[ci] or "").strip()
            for ci in range(q_col + 1, min(answer_col_end, len(row)))
            if (row[ci] or "").strip()
        ]
        answer_cell = " ".join(answer_parts).strip()

        guidance_cell: str | None = None
        if guidance_col is not None and len(row) > guidance_col:
            guidance_cell = (row[guidance_col] or "").strip() or None

        marks_cell = ((row[marks_col] if len(row) > marks_col else None) or "").strip()

        marks_int: int | None = None
        with contextlib.suppress(ValueError, TypeError):
            marks_int = int(marks_cell)

        # ParseError triggers -------------------------------------------
        if _LEVEL_DESCRIPTOR_Q_RE.match(q_cell) and _BAND_LANGUAGE_RE.search(answer_cell):
            raise ParseError(
                f"Level-descriptor row ('{q_cell}'): document uses levels-based "
                "marking — fall back to Gemini parser"
            )
        if _INDICATIVE_CONTENT_RE.search(answer_cell):
            raise ParseError("Indicative-content section detected: fall back to Gemini parser")

        # Determine if this row starts a new question --------------------
        #
        # Priority 1: compound Q-numbers like "1", "1(a)", "2(a)(i)".
        # We diff the component list against the current label stack to find
        # the deepest shared ancestor, unwind to it, then push the new nodes.
        #
        # Priority 2: standalone parenthesised labels "(a)" / "(i)" from
        # split-row format tables (legacy / unit-test fixtures).
        components = _decompose_compound_q(q_cell)

        if components is not None:
            flush()

            # Find the length of the common prefix between `components[:-1]`
            # (all ancestors of the new leaf) and the current `labels` stack.
            common_len = 0
            for k, comp in enumerate(components[:-1]):
                if k < len(labels) and labels[k] == comp:
                    common_len = k + 1
                else:
                    break

            unwind_to(common_len)

            for k, comp in enumerate(components):
                if k < common_len:
                    continue  # already on stack (shared ancestor)
                is_leaf = k == len(components) - 1
                push_question(comp, is_leaf, marks_int, guidance_cell)

            if answer_cell:
                point_idx += 1
                current_points.append(
                    AnswerPoint(
                        id=f"p{point_idx}",
                        point=answer_cell,
                        marks=marks_int if marks_int is not None else 1,
                        is_alternative=False,
                    )
                )
                q_row_had_answer = True

        elif _LEVEL_3_RE.match(q_cell):
            # Check _LEVEL_3_RE before _LEVEL_2_RE: (i), (ii), (iv) are Roman
            # numerals (level 3) even though 'i' is also a valid single letter.
            flush()
            unwind_to(2)
            push_question(q_cell, True, marks_int, guidance_cell)
            if answer_cell:
                point_idx += 1
                current_points.append(
                    AnswerPoint(
                        id=f"p{point_idx}",
                        point=answer_cell,
                        marks=marks_int if marks_int is not None else 1,
                        is_alternative=False,
                    )
                )
                q_row_had_answer = True

        elif _LEVEL_2_RE.match(q_cell):
            flush()
            unwind_to(1)
            push_question(q_cell, True, marks_int, guidance_cell)
            if answer_cell:
                point_idx += 1
                current_points.append(
                    AnswerPoint(
                        id=f"p{point_idx}",
                        point=answer_cell,
                        marks=marks_int if marks_int is not None else 1,
                        is_alternative=False,
                    )
                )
                q_row_had_answer = True

        else:
            # Continuation row — add an AnswerPoint to the deepest question.
            if not answer_cell or not stack:
                continue

            upper = answer_cell.upper()

            # Handle "OR" / "EITHER" patterns
            if upper in ("OR", "EITHER"):
                next_is_alt = True
                continue

            is_alt = next_is_alt
            text = answer_cell

            if upper.startswith("OR "):
                text = answer_cell[3:].strip()
                is_alt = True
            elif upper.startswith("EITHER "):
                text = answer_cell[7:].strip()
                is_alt = True

            if not text:
                continue

            next_is_alt = False
            point_idx += 1
            current_points.append(
                AnswerPoint(
                    id=f"p{point_idx}",
                    point=text,
                    marks=marks_int if marks_int is not None else 1,
                    is_alternative=is_alt,
                )
            )

    # Final flush and full stack unwind
    flush()
    unwind_to(0)

    if not top_level:
        raise ParseError("Theory table contained no questions after parsing")

    return top_level
