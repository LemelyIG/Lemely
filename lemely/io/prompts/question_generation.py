"""Versioned prompts for practice question generation and its N3 gates."""

from __future__ import annotations

from typing import TYPE_CHECKING

from lemely.core.schemas import WeakArea

if TYPE_CHECKING:
    from lemely.core.generation import GeneratedQuestion

VERSION = "2"

#: Bumping this invalidates every cached validity-check response — kept
#: separate from VERSION (the generation prompt) and CODE_EXECUTION_VERSION
#: (the sandbox-fallback prompt) because each is a distinct call shape with
#: its own cache entries; bumping one must never look like bumping another.
VALIDITY_VERSION = "1"

#: See VALIDITY_VERSION's note — this is the code_execution call's own
#: prompt version, independent of the other two.
CODE_EXECUTION_VERSION = "1"


def build_question_gen_system_prompt(subject_code: str) -> str:
    return (
        f"You are an expert Cambridge IGCSE examiner for subject {subject_code}. "
        "Your task is to create targeted practice questions that address the specific "
        "weak areas identified in a student's recent paper. "
        "For each weak area topic, generate one well-structured question with:\n"
        "- A clear, exam-style prompt\n"
        "- A complete model answer\n"
        "- A list of mark scheme bullet points (one per mark)\n"
        "- An appropriate difficulty level (foundation / standard / challenge)\n"
        "- The total mark allocation\n"
        "- A question_type (mcq, recall, explanation, calculation, equation, "
        "graph_draw, graph_read, diagram, table, list, comparison, multi_step, "
        "levels_based, indicative_content, fieldwork, tickbox)\n\n"
        "If, and only if, question_type is 'calculation', 'equation', or a "
        "numeric 'recall', ALSO provide:\n"
        "- solution_expr: a SymPy-parseable expression that computes the "
        "correct answer (e.g. '2 * 3.0e8 / 5' or 'v = u + a*t')\n"
        "- answer: the final numeric or algebraic answer, as a short "
        "SymPy-parseable value (not prose)\n\n"
        "Questions must be original (not copied from past papers) and appropriate "
        f"for CAIE {subject_code} level. Return ONLY valid JSON matching the schema."
    )


def build_question_gen_user_prompt(
    areas: list[WeakArea], *, count: int, failure_reason: str | None = None
) -> str:
    topic_list = "\n".join(
        f"- {a.topic} (lost {a.lost_marks}/{a.maximum_marks} marks, accuracy {a.accuracy:.0%})"
        for a in areas[:count]
    )
    reason_block = ""
    if failure_reason:
        # N3 step 4: "reject -> regenerate up to 3, with the failure reason
        # in the prompt" — this is that feedback loop's only mechanism, so a
        # regenerated item is told exactly what was wrong with its
        # predecessor rather than being asked to simply "try again".
        reason_block = (
            "\n\nYour previous attempt at this question was rejected for the "
            f"following reason: {failure_reason}\n"
            "Generate a new, different question that avoids this specific "
            "problem.\n"
        )
    return (
        f"Generate {count} practice question(s) targeting these weak areas:\n\n"
        f"{topic_list}\n"
        f"{reason_block}\n"
        "Return a GeneratedQuiz JSON object with one GeneratedQuestion per topic. "
        "subject_code must match the subject you were told about."
    )


def build_validity_check_system_prompt(subject_code: str) -> str:
    return (
        f"You are an expert Cambridge IGCSE examiner for subject {subject_code}, "
        "checking a DRAFT practice question for validity before it reaches a "
        "student. You are not answering the question; you are auditing whether "
        "it can be answered at all.\n\n"
        "Report, as booleans:\n"
        "- well_posed: the question is coherent and unambiguous.\n"
        "- missing_data: the question requires a quantity, value, or fact it "
        "never states or otherwise makes available.\n"
        "- contradictory: the question's own stated facts conflict with each "
        "other.\n"
        "- single_answer: the question has exactly one correct answer (not "
        "several equally valid ones, and not none).\n\n"
        "Return ONLY valid JSON matching the schema."
    )


def build_validity_check_user_prompt(question: GeneratedQuestion) -> str:
    return (
        f"Question: {question.prompt}\n\n"
        f"Stated model answer: {question.model_answer}\n\n"
        "Assess this question's validity as described."
    )


def build_code_execution_prompt(question: GeneratedQuestion) -> str:
    """N3 step 3 fallback prompt.

    Asks Gemini's code_execution tool to compute the answer independently,
    for comparison against ``question.answer``. This is Gemini's own
    ``code_execution`` tool
    (docs/plans/ai-improvements-plan.md:615), not a locally-built sandbox —
    lemely.io.gemini.GeminiClient.generate_with_code_execution sends this
    prompt with that tool enabled and reads back its
    ``code_execution_result``.
    """
    return (
        "Using your code execution tool, write and run Python (using sympy "
        "if useful) to compute the correct final answer to this question. "
        "Print ONLY the final numeric or algebraic answer, nothing else.\n\n"
        f"Question: {question.prompt}\n\n"
        f"Model answer for reference (verify it, do not just repeat it): "
        f"{question.model_answer}"
    )
