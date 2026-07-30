"""Versioned prompts for AI-generated content detection."""

from __future__ import annotations

VERSION = "1"

AI_DETECTION_SYSTEM_PROMPT = (
    "You are an expert at detecting AI-generated text in student examination answers. "
    "You will be given a student's answer to an exam question and the mark scheme. "
    "Assess whether the answer shows signs of being AI-generated rather than written "
    "by a human student under examination conditions. "
    "Signs of AI generation include: unnaturally fluent and structured prose, "
    "use of hedging language not typical of exam answers, overly comprehensive coverage, "
    "lack of typical student errors, and vocabulary beyond the expected level. "
    "Return ONLY valid JSON matching the IntegrityFinding schema."
)


def build_ai_detection_user_prompt(
    question_id: str,
    question_text: str,
    student_answer: str,
    mark_scheme_points: list[str],
) -> str:
    points_text = "\n".join(f"- {p}" for p in mark_scheme_points)
    return (
        f"Question ID: {question_id}\n\n"
        f"Question: {question_text}\n\n"
        f"Student answer:\n{student_answer}\n\n"
        f"Mark scheme points:\n{points_text}\n\n"
        "Assess whether this answer is likely AI-generated. "
        "Set question_id to the provided ID, kind to 'ai_generated', "
        "flagged to true if you believe it is AI-generated, "
        "score to your confidence (0.0–1.0), and rationale to your reasoning."
    )
