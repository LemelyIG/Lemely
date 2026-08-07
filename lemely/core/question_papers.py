"""Question-paper schemas (P4.1).

A CAIE mark scheme (``lemely.core.loose_schemes.MarkScheme``) carries marking
points but never the question *stem* — the stem lives in the paired question
paper, which this codebase never parsed into structure before P4.1
(``BUILD/DECISIONS.md`` D3.7). These models are the deterministic
question-paper extractor's output shape: a question paper broken into its
numbered questions (MCQ) or numbering-tree leaves (theory), each carrying
just enough to pair against a parsed mark scheme by ref and build a bank row
— nothing more. In particular there is deliberately no ``topic`` field here:
topic classification is P4.2, and guessing one here would be inventing
precision this extractor has no basis for (``docs/LEMELY_UI_SPEC.md`` §1.4).

Two shapes share one leaf model (:class:`QuestionPaperQuestion`):

* **MCQ** — ``options`` populated (``{"A": "...", ...}``), ``marks`` fixed at 1.
* **Theory** — ``options`` is ``None``; ``marks`` is the ``[n]`` annotation
  parsed for that leaf, or ``None`` when no annotation was found for it (a
  leaf with no marks annotation is not bank-eligible — see
  ``lemely.io.question_papers``).

``has_figure`` is the honesty gate named in the brief: a leaf whose bounding
region on the page overlaps a detected image/vector-drawing region is
flagged, and the flag travels with enough evidence (:attr:`figure_evidence`)
that a caller can explain *why* a question was excluded from the bank rather
than just asserting it was.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from lemely.core.schemas import StrictModel

FigureKind = Literal["image", "vector_drawing"]


class FigureEvidence(StrictModel):
    """One piece of evidence a question's region overlaps a graphic object."""

    kind: FigureKind = Field(
        ...,
        description="'image' for an embedded raster (pdfplumber page.images), "
        "'vector_drawing' for line/rect/curve objects (graphs, diagrams drawn "
        "as vector paths — the common case in CAIE physics/maths papers).",
    )
    page_number: int = Field(..., ge=1, description="1-indexed page the evidence was found on.")
    object_count: int = Field(
        ..., ge=1, description="How many graphic objects of this kind overlap the question region."
    )


class QuestionPaperQuestion(StrictModel):
    """One leaf question extracted from a question-paper PDF.

    ``ref`` follows the same hierarchical notation as
    ``lemely.core.loose_schemas.Question.id`` (``'1'``, ``'2a'``, ``'1a_i'``)
    so a leaf can be paired against its mark-scheme counterpart by exact
    string match — see ``lemely.io.question_papers``.
    """

    ref: str = Field(..., description="Hierarchical question ref, e.g. '1', '2a', '1a_i'.")
    stem: str = Field(..., description="Extracted question text, verbatim from the PDF.")
    options: dict[str, str] | None = Field(
        None,
        description="MCQ only: option letter -> option text. None for theory questions.",
    )
    marks: int | None = Field(
        None,
        ge=0,
        description="Marks annotation parsed for this leaf ('[n]' in the source, or 1 "
        "for every MCQ leaf). None when no annotation could be found — such a leaf "
        "is not bank-eligible (lemely.io.question_papers skips it and counts it).",
    )
    page_number: int = Field(..., ge=1, description="1-indexed page the question starts on.")
    has_figure: bool = Field(
        False,
        description="True when a detected image/vector-drawing region overlaps this "
        "question's bounding region — the stem text alone is not a faithful "
        "representation of the question. Such questions are excluded from the bank "
        "by default (lemely.io.question_papers).",
    )
    figure_evidence: list[FigureEvidence] = Field(
        default_factory=list,
        description="What triggered has_figure=True. Empty when has_figure is False.",
    )


class QuestionPaperMetadata(StrictModel):
    """Header metadata for a question paper — filename-derived, authoritative."""

    subject_code: str = Field(..., pattern=r"^\d{4}$")
    paper_number: int = Field(..., ge=1, le=9)
    paper_variant: int = Field(..., ge=1, le=9)
    session_month: Literal["May/June", "Oct/Nov", "Feb/Mar", "Specimen"]
    session_year: int | None = Field(None, ge=2000, le=2100)
    is_mcq: bool = Field(..., description="True for the MCQ paper shape, False for theory.")
    stated_total_marks: int | None = Field(
        None,
        description="'The total mark for this paper is N' parsed from the cover page, "
        "if present. Used for the reconciliation sanity check, never as a tolerance "
        "knob to hide a mismatch (BUILD/BLOCKERS.md B2).",
    )
    source_document: str | None = None


class QuestionPaper(StrictModel):
    """Root model: one parsed question-paper PDF."""

    metadata: QuestionPaperMetadata
    questions: list[QuestionPaperQuestion] = Field(default_factory=list)

    @property
    def extracted_marks_total(self) -> int:
        """Sum of every leaf's ``marks`` (leaves with ``marks=None`` contribute 0)."""
        return sum(q.marks or 0 for q in self.questions)


__all__ = [
    "FigureEvidence",
    "FigureKind",
    "QuestionPaper",
    "QuestionPaperMetadata",
    "QuestionPaperQuestion",
]
