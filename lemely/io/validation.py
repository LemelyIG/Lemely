"""Mark scheme structural validation — emits warnings, does not raise."""
from __future__ import annotations

from dataclasses import dataclass

from lemely.core.loose_schemas import MarkScheme, Question, QuestionType


@dataclass
class ValidationWarning:
    question_id: str
    message: str


def _check_leaf_question(q: Question, warnings: list[ValidationWarning]) -> None:
    """Append warnings for a single leaf question."""
    if q.type == QuestionType.MCQ:
        if q.mcq_answer is None:
            warnings.append(ValidationWarning(q.id, "MCQ has no valid expected answer (A–D)"))
    else:
        has_points = bool(
            q.answer_points
            or q.level_descriptors
            or q.drawing_criteria
            or q.indicative_content
            or q.plot_requirements
        )
        if not has_points:
            warnings.append(ValidationWarning(q.id, "leaf question has no mark points"))


def validate_mark_scheme(scheme: MarkScheme) -> list[ValidationWarning]:
    """Check structural invariants for all leaf questions; return warnings (not errors)."""
    warnings: list[ValidationWarning] = []
    for q in scheme.all_questions_flat():
        if q.marks <= 0 or q.parts:        # skip containers and zero-mark items
            continue
        _check_leaf_question(q, warnings)
    return warnings
