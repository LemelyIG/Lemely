"""A leaf's kind, from its mark-scheme question type (spec 2026-10-19 §4 B3)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from lemely.core.loose_schemas import QuestionType

if TYPE_CHECKING:
    from lemely.core.loose_schemas import Question

LeafKind = Literal["mcq", "numeric", "short", "extended"]

_KIND: dict[QuestionType, LeafKind] = {
    QuestionType.MCQ: "mcq",
    QuestionType.TICKBOX: "mcq",
    QuestionType.CALCULATION: "numeric",
    QuestionType.EQUATION: "numeric",
    QuestionType.GRAPH_READ: "numeric",
    QuestionType.EXPLANATION: "extended",
    QuestionType.COMPARISON: "extended",
    QuestionType.MULTI_STEP: "extended",
    QuestionType.LEVELS_BASED: "extended",
    QuestionType.INDICATIVE_CONTENT: "extended",
    QuestionType.FIELDWORK: "extended",
    QuestionType.RECALL: "short",
    QuestionType.LIST: "short",
    QuestionType.TABLE: "short",
    QuestionType.DIAGRAM: "short",
    QuestionType.GRAPH_DRAW: "short",
}


def leaf_kind(question: Question) -> LeafKind:
    """``mcq``, ``numeric``, ``short`` or ``extended``; a type with no entry is ``short``."""
    return _KIND.get(question.type, "short")
