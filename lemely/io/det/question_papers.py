"""Deterministic CAIE question-paper PDF extractor (P4.1).

Parses question-paper PDFs (pdfplumber, no Gemini — the $8 budget cannot
fund per-question LLM extraction over 70+ papers) into
``lemely.core.question_papers.QuestionPaper``: the question *stem* text a
paired mark scheme (``lemely.io.det``) never carries. Two shapes:

* **MCQ** (e.g. ``0625_*_qp_1*``) — sequential numbered stem + A/B/C/D
  options, one mark each.
* **Theory** (``qp_2*``..``qp_6*``) — the ``1`` / ``(a)`` / ``(b)(ii)``
  numbering tree, each leaf terminated by a ``[n]``-style marks annotation.

**Figure honesty is the crux, not a detail.** Many CAIE questions depend on
a diagram, graph, or table that pdfplumber text extraction cannot represent
— the extracted stem text alone would be a confident lie about what the
question actually asks. Every text line is checked, as it is assigned to a
leaf, for overlapping image/vector-drawing regions on its page
(:func:`_record_figure_evidence`); a leaf with any such overlap is flagged
``has_figure=True``. ``lemely.io.question_papers`` excludes such leaves from
the bank by default and counts them explicitly rather than banking an
incomplete stem silently (``docs/LEMELY_UI_SPEC.md`` §1.4 — never invent
precision).

This module never raises on a mark-total mismatch the way
``lemely.io.det.reconcile`` does for mark schemes — a question paper's
stated total is a **paper-level signal for the ingest report**
(``QuestionPaper.extracted_marks_total`` vs
``QuestionPaperMetadata.stated_total_marks``), not grounds to discard every
leaf that *did* extract cleanly. ``BUILD/BLOCKERS.md`` B2 is the standing
reason a tolerance knob that silences a mismatch is never the right move;
the mismatch is surfaced by the caller (``lemely.io.question_papers``,
counted as ``reconcile_mismatch``) instead of hidden here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import structlog

from lemely.core.loose_schemas import PaperType
from lemely.core.question_papers import (
    FigureEvidence,
    FigureKind,
    QuestionPaper,
    QuestionPaperMetadata,
    QuestionPaperQuestion,
)
from lemely.io.det.profiles import get_profile
from lemely.io.metadata import parse_caie_qp_filename_metadata
from lemely.runtime.errors import ParseError

if TYPE_CHECKING:
    from pathlib import Path

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

_TOTAL_MARK_RE = re.compile(r"total\s+mark\s+for\s+this\s+paper\s+is\s+(\d+)", re.IGNORECASE)
_SUBPART_RE = re.compile(r"^\(([a-h])\)\s*")
_SUBSUBPART_RE = re.compile(r"^\(([ivx]{1,4})\)\s*")
_MARKS_RE = re.compile(r"\[(\d{1,2})\]\s*$")
_MCQ_OPTION_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9])([A-D])\s+")
_TRAILING_DOTS_RE = re.compile(r"\.{4,}\s*$")

#: Minimum count of overlapping vector-graphic objects (lines+rects+curves)
#: within a text line's y-band before it counts as figure evidence.
#: Calibrated against real CAIE 0625 papers: a plain-text MCQ stem line
#: overlaps 0 vector objects; a labelled diagram or graph overlaps dozens
#: (axis ticks, outlines, borders). A low threshold is deliberate — a false
#: positive costs one honestly-skipped question; a false negative silently
#: banks an unfaithful stem, which is the worse failure
#: (LEMELY_UI_SPEC.md §1.4).
_VECTOR_FIGURE_THRESHOLD = 2


def _clean(text: str) -> str:
    return _TRAILING_DOTS_RE.sub("", text).strip()


@dataclass
class _LeafBuilder:
    """Accumulator for one question-paper leaf while scanning text lines."""

    ref: str
    page_number: int
    options: dict[str, str] | None = None
    marks: int | None = None
    lines: list[str] = field(default_factory=list)
    #: (kind, page_number) -> max overlapping object count seen on any single
    #: line assigned to this leaf. A dict, not a list, so repeated lines over
    #: the same figure region on the same page contribute one evidence entry
    #: with a representative count rather than N duplicate entries.
    _figure_hits: dict[tuple[FigureKind, int], int] = field(default_factory=dict)

    def add_line(self, text: str) -> None:
        cleaned = _clean(text)
        if cleaned:
            self.lines.append(cleaned)

    def stem(self) -> str:
        return "\n".join(self.lines).strip()

    def record_figure(self, kind: FigureKind, page_number: int, count: int) -> None:
        key = (kind, page_number)
        self._figure_hits[key] = max(self._figure_hits.get(key, 0), count)

    def figure_evidence(self) -> list[FigureEvidence]:
        return [
            FigureEvidence(kind=kind, page_number=page_number, object_count=count)
            for (kind, page_number), count in sorted(self._figure_hits.items())
        ]


class DeterministicQuestionPaperExtractor:
    """Parse a CAIE question-paper PDF to ``QuestionPaper`` without Gemini.

    Raises ``ParseError`` when the paper's identity cannot be determined
    (bad filename / unreadable cover page) or when zero questions could be
    extracted at all (an image-only / scan-based PDF, or a shape this
    extractor does not understand — both are honest failures to surface,
    not a reason to fabricate a QuestionPaper with no questions).
    """

    def __call__(self, pdf_path: Path) -> QuestionPaper:
        try:
            import pdfplumber
        except ImportError as exc:  # pragma: no cover - environment guard
            raise ImportError(
                "pdfplumber is required for deterministic parsing. "
                "Install it with: pip install pdfplumber"
            ) from exc

        try:
            fm = parse_caie_qp_filename_metadata(pdf_path)
        except ValueError as exc:
            raise ParseError(f"Cannot determine paper identity for {pdf_path.name}: {exc}") from exc

        with pdfplumber.open(pdf_path) as pdf:
            if not pdf.pages:
                raise ParseError(f"{pdf_path.name} has no pages")
            cover_text = pdf.pages[0].extract_text() or ""
            profile = get_profile(fm.subject_code)
            is_mcq = profile.paper_type(fm.paper_number, cover_text) == PaperType.MCQ

            stated_total: int | None = None
            m = _TOTAL_MARK_RE.search(cover_text)
            if m:
                stated_total = int(m.group(1))

            metadata = QuestionPaperMetadata(
                subject_code=fm.subject_code,
                paper_number=fm.paper_number,
                paper_variant=fm.paper_variant,
                session_month=fm.session_month,
                session_year=fm.session_year,
                is_mcq=is_mcq,
                stated_total_marks=stated_total,
                source_document=pdf_path.name,
            )

            pages = pdf.pages[1:]  # page 0 is the cover page for both shapes
            if is_mcq:
                leaves = _extract_mcq(pages, page_offset=2)
            else:
                leaves = _extract_theory(pages, page_offset=2)

        if not leaves:
            raise ParseError(
                f"No questions extracted from {pdf_path.name} — "
                "may be an image-only/scan-based PDF or an unrecognised layout"
            )

        questions = [_leaf_to_question(leaf) for leaf in leaves]
        return QuestionPaper(metadata=metadata, questions=questions)


def _leaf_to_question(leaf: _LeafBuilder) -> QuestionPaperQuestion:
    evidence = leaf.figure_evidence()
    return QuestionPaperQuestion(
        ref=leaf.ref,
        stem=leaf.stem(),
        options=leaf.options,
        marks=leaf.marks,
        page_number=leaf.page_number,
        has_figure=bool(evidence),
        figure_evidence=evidence,
    )


def _record_figure_evidence(leaf: _LeafBuilder, page: Any, top: float, bottom: float) -> None:
    """Check the region [top, bottom] on ``page`` and record any overlap on ``leaf``."""
    page_number = int(getattr(page, "page_number", leaf.page_number))
    images = [im for im in page.images if _overlaps(im, top, bottom)]
    if images:
        leaf.record_figure("image", page_number, len(images))
    vector_count = sum(
        1 for obj in (*page.lines, *page.rects, *page.curves) if _overlaps(obj, top, bottom)
    )
    if vector_count >= _VECTOR_FIGURE_THRESHOLD:
        leaf.record_figure("vector_drawing", page_number, vector_count)


def _overlaps(obj: dict[str, Any], top: float, bottom: float) -> bool:
    return bool(obj["top"] <= bottom and obj["bottom"] >= top)


def _append_with_marks(leaf: _LeafBuilder, text: str) -> None:
    """Append ``text`` to ``leaf``, extracting a trailing ``[n]`` marks annotation.

    Shared by every call site that adds text to a leaf — a marks annotation
    can appear on the *same* line as a numbering marker (e.g. "(b) Explain
    your answer. [4]"), not only on a line of its own, so this must run
    wherever text is added, not only in the fallback body-text branch.
    """
    marks_match = _MARKS_RE.search(text)
    body = _MARKS_RE.sub("", text).strip()
    if body:
        leaf.add_line(body)
    if marks_match and leaf.marks is None:
        leaf.marks = int(marks_match.group(1))


# ---------------------------------------------------------------------------
# MCQ extraction
# ---------------------------------------------------------------------------


#: Boilerplate lines (running footer / "Turn over" prompts) that never carry
#: question content — dropped before block splitting so they cannot be
#: mistaken for a trailing continuation of the last option.
_FOOTER_RE = re.compile(r"©\s*UCLES|\[Turn over|PMT\b", re.IGNORECASE)
_PAGE_HEADER_RE = re.compile(r"^\d{1,3}$")


def _extract_mcq(pages: list[Any], page_offset: int) -> list[_LeafBuilder]:
    """Buffer raw lines per top-level question, then split stem from options.

    Splitting is deferred to :func:`_finalize_mcq_leaf` (run once the whole
    block is known) rather than committed line-by-line, because CAIE MCQ
    stems routinely contain a line that itself starts with "A ..." (plain
    English, not an option) before the real options block — e.g. "A customer
    buys some pasta...". Committing greedily on the first "A "-shaped line
    misclassifies that as option A. Buffering and picking the *last*
    A→B→C→D run in the block is robust to that ambiguity because a
    genuine options block is always the final A→B→C→D run in a question.
    """
    leaves: list[_LeafBuilder] = []
    next_id = 1
    current: _LeafBuilder | None = None
    raw_lines: list[str] = []

    def close_current() -> None:
        nonlocal current, raw_lines
        if current is not None:
            _finalize_mcq_leaf(current, raw_lines)
            if current.options and len(current.options) == 4:
                leaves.append(current)
        current = None
        raw_lines = []

    for page_index, page in enumerate(pages):
        page_number = page_index + page_offset
        for i, line in enumerate(page.extract_text_lines()):
            text = line["text"].strip()
            if not text:
                continue
            if i == 0 and _PAGE_HEADER_RE.match(text):
                continue  # running page-number header
            if _FOOTER_RE.search(text):
                continue
            top, bottom = line["top"], line["bottom"]

            top_match = re.match(rf"^{next_id}\s+(?=\S)", text)
            if top_match:
                close_current()
                current = _LeafBuilder(ref=str(next_id), page_number=page_number, options={})
                current.marks = 1
                raw_lines = [text[top_match.end() :]]
                _record_figure_evidence(current, page, top, bottom)
                next_id += 1
                continue

            if current is None:
                continue
            raw_lines.append(text)
            _record_figure_evidence(current, page, top, bottom)

    close_current()
    return leaves


def _finalize_mcq_leaf(leaf: _LeafBuilder, raw_lines: list[str]) -> None:
    """Split a buffered question block into stem + A/B/C/D options.

    Finds the *last* contiguous A→B→C→D run of option tokens in the block
    (handles both "A text" one-per-line and "A text B text C text D text"
    inline layouts, and multi-line option text) and treats everything before
    it as the stem. ``leaf.options`` is left empty (and the leaf therefore
    dropped by the caller) when no such run is found.
    """
    if leaf.options is None:
        return
    block_text = "\n".join(raw_lines)
    tokens = list(_MCQ_OPTION_TOKEN_RE.finditer(block_text))
    split_idx: int | None = None
    for i in range(len(tokens) - 3):
        if [tokens[i + k].group(1) for k in range(4)] == ["A", "B", "C", "D"]:
            split_idx = i  # keep scanning — the rightmost (last) run wins
    if split_idx is None:
        return
    opt_tokens = tokens[split_idx : split_idx + 4]
    stem_text = block_text[: opt_tokens[0].start()]
    bounds = [t.start() for t in opt_tokens] + [len(block_text)]
    for k, letter in enumerate("ABCD"):
        seg = block_text[bounds[k] + len(opt_tokens[k].group(0)) : bounds[k + 1]]
        leaf.options[letter] = _clean(seg.replace("\n", " "))
    for stem_line in stem_text.split("\n"):
        leaf.add_line(stem_line)


# ---------------------------------------------------------------------------
# Theory extraction
# ---------------------------------------------------------------------------


def _extract_theory(pages: list[Any], page_offset: int) -> list[_LeafBuilder]:
    """Walk the '1' / '(a)' / '(b)(ii)' numbering tree, tracking marks + figures.

    A top-level question's text before its first lettered sub-part (the
    "intro", e.g. "Fig. 1.1 shows a straight section of a river...") carries
    context every sub-part needs to be self-contained, and any figure the
    intro overlaps is relevant to every sub-part too — a diagram introduced
    once at the top is what the whole set of sub-parts refers to. Both the
    intro text (``top_intro``) and its accumulated figure hits
    (``top_context``) are therefore folded into *every* sub-part opened
    under that top-level, not just the first.
    """
    leaves: dict[str, _LeafBuilder] = {}
    order: list[str] = []
    next_top = 1
    top_id: str | None = None
    top_intro: list[str] = []
    top_context: _LeafBuilder | None = None  # de-registered top-level intro builder
    top_has_subparts = False
    sub_id: str | None = None
    active: _LeafBuilder | None = None

    def open_leaf(ref: str, page_number: int) -> _LeafBuilder:
        leaf = leaves.get(ref)
        if leaf is None:
            leaf = _LeafBuilder(ref=ref, page_number=page_number, options=None)
            leaf.lines.extend(top_intro)
            if top_context is not None:
                for (kind, pg), count in top_context._figure_hits.items():
                    leaf.record_figure(kind, pg, count)
            leaves[ref] = leaf
            order.append(ref)
        return leaf

    for page_index, page in enumerate(pages):
        page_number = page_index + page_offset
        for line in page.extract_text_lines():
            text = line["text"].strip()
            if not text:
                continue
            top, bottom = line["top"], line["bottom"]

            top_match = re.match(rf"^{next_top}\s+(?=\S)", text)
            if top_match:
                # A new top-level question. next_top only ever advances here,
                # so this can only fire once per id — a coincidental body
                # line starting with the next integer cannot repeat it.
                top_id = str(next_top)
                next_top += 1
                top_has_subparts = False
                top_context = None
                sub_id = None
                rest = text[top_match.end() :]
                active = _LeafBuilder(ref=top_id, page_number=page_number, options=None)
                _append_with_marks(active, rest)
                top_intro = list(active.lines)
                _record_figure_evidence(active, page, top, bottom)
                # Registered as a leaf provisionally — a top-level question
                # with no lettered sub-parts (e.g. "1 Calculate x. [5]") is a
                # leaf in its own right. If a sub-part marker arrives before
                # this question closes, it is de-registered below: its text
                # and figure hits become shared context for every sub-part
                # instead (see open_leaf).
                leaves[top_id] = active
                order.append(top_id)
                continue

            sub_match = _SUBPART_RE.match(text)
            if sub_match and top_id is not None:
                if not top_has_subparts:
                    top_context = leaves.pop(top_id, None)
                    if top_id in order:
                        order.remove(top_id)
                top_has_subparts = True
                sub_id = sub_match.group(1)
                rest = text[sub_match.end() :]
                subsub_match = _SUBSUBPART_RE.match(rest)
                if subsub_match:
                    ref = f"{top_id}{sub_id}_{subsub_match.group(1)}"
                    rest = rest[subsub_match.end() :]
                else:
                    ref = f"{top_id}{sub_id}"
                active = open_leaf(ref, page_number)
                if rest:
                    _append_with_marks(active, rest)
                _record_figure_evidence(active, page, top, bottom)
                continue

            subsub_match = _SUBSUBPART_RE.match(text)
            if subsub_match and top_id is not None and sub_id is not None:
                ref = f"{top_id}{sub_id}_{subsub_match.group(1)}"
                rest = text[subsub_match.end() :]
                active = open_leaf(ref, page_number)
                if rest:
                    _append_with_marks(active, rest)
                _record_figure_evidence(active, page, top, bottom)
                continue

            if active is None:
                continue

            _append_with_marks(active, text)
            _record_figure_evidence(active, page, top, bottom)
            # Keep the running intro buffer in sync while no sub-part has
            # opened yet, so the first sub-part (once it appears) inherits
            # the shared context lines that precede it.
            if top_id is not None and not top_has_subparts and active.ref == top_id:
                top_intro = list(active.lines)

    return [leaves[ref] for ref in order]


__all__ = ["DeterministicQuestionPaperExtractor"]
