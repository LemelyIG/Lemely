"""Schemas for AI-generated practice questions."""

from __future__ import annotations

from typing import Literal

from lemely.core.loose_schemas import QuestionType
from lemely.core.schemas import StrictModel

#: The subset of QuestionType whose stated answer is a solvable expression —
#: a number, formula, or equation — rather than free-form prose. This is the
#: only slice N3's gate (lemely.io.question_gates) can check with a solver
#: (docs/plans/ai-improvements-plan.md:610-618, step 2). Everything else
#: stops at the validity pass alone (verified_by="validity_only").
SOLVABLE_QUESTION_TYPES: frozenset[QuestionType] = frozenset(
    {QuestionType.CALCULATION, QuestionType.EQUATION, QuestionType.RECALL}
)

#: What positively established a GeneratedQuestion's stated answer, per N3:
#: - "sympy": lemely.core.equivalence.equivalent(solution_expr, answer)
#:   returned EQUAL_PROVEN.
#: - "sandbox": SymPy could not prove it (EQUAL_SAMPLED or UNPARSEABLE) so
#:   Gemini's own code_execution tool computed the answer, and comparing
#:   THAT result to the stated answer also returned EQUAL_PROVEN.
#: - "validity_only": the question_type has no solver support; only the
#:   step-1 validity pass ran.
#: None means the gate did not positively establish anything — see
#: GeneratedQuestion.rejection_reason.
VerifiedBy = Literal["sympy", "sandbox", "validity_only"]


class GeneratedQuestion(StrictModel):
    topic: str
    difficulty: Literal["foundation", "standard", "challenge"]
    prompt: str
    model_answer: str
    mark_scheme_points: list[str]
    total_marks: int
    source_question_ids: list[str] = []  # noqa: RUF012
    #: Declared by the generator, read (not re-derived) by
    #: lemely.db.question_bank_repo.generated_questions_to_bank_rows and by
    #: the N3 gate to decide whether a solver applies at all. Defaults to
    #: EXPLANATION — the same default the bank importer used to hardcode
    #: before this field existed.
    question_type: QuestionType = QuestionType.EXPLANATION
    #: A SymPy-parseable expression for the CORRECT answer. Populated by the
    #: generator only for question_type in SOLVABLE_QUESTION_TYPES; None
    #: otherwise, and no gate step requires it outside that set.
    solution_expr: str | None = None
    #: The generator's own stated final answer, checked against
    #: solution_expr (locally, via SymPy) or against Gemini's own
    #: code_execution result when SymPy cannot prove it. Distinct from
    #: model_answer, which is prose explaining the working, not necessarily
    #: an isolated value equivalent() can parse.
    answer: str | None = None
    #: Set ONLY by lemely.io.question_gates.verify_question — a caller must
    #: never trust a value Gemini's own JSON output happened to fill in for
    #: this field, since that would let a wrong item self-certify. Callers
    #: that construct a GeneratedQuestion straight from a Gemini response are
    #: expected to reset it to None before running the gate (see
    #: lemely.io.question_generation.QuestionGenerator._generate_one).
    verified_by: VerifiedBy | None = None
    #: Set alongside verified_by=None by verify_question; explains which
    #: check failed. Fed back into the next regeneration attempt's prompt.
    rejection_reason: str | None = None


class QuestionValidityCheck(StrictModel):
    """N3 step 1: one structured validity call per generated question.

    Deliberately a bare fact-record, not a decision. ``well_posed`` and
    ``single_answer`` are claims that must be True; ``missing_data`` and
    ``contradictory`` are claims that must be False. :attr:`passes` performs
    that combination once so a caller cannot get one of the four polarities
    backwards.
    """

    well_posed: bool
    missing_data: bool
    contradictory: bool
    single_answer: bool

    @property
    def passes(self) -> bool:
        return (
            self.well_posed
            and not self.missing_data
            and not self.contradictory
            and self.single_answer
        )


class GeneratedQuiz(StrictModel):
    subject_code: str
    questions: list[GeneratedQuestion]
