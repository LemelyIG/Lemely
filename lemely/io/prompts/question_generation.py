"""Versioned prompts for practice question generation."""

from __future__ import annotations

from lemely.core.schemas import WeakArea

VERSION = "1"


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
        "- The total mark allocation\n\n"
        "Questions must be original (not copied from past papers) and appropriate "
        f"for CAIE {subject_code} level. Return ONLY valid JSON matching the schema."
    )


def build_question_gen_user_prompt(areas: list[WeakArea], *, count: int) -> str:
    topic_list = "\n".join(
        f"- {a.topic} (lost {a.lost_marks}/{a.maximum_marks} marks, accuracy {a.accuracy:.0%})"
        for a in areas[:count]
    )
    return (
        f"Generate {count} practice question(s) targeting these weak areas:\n\n"
        f"{topic_list}\n\n"
        "Return a GeneratedQuiz JSON object with one GeneratedQuestion per topic. "
        "subject_code must match the subject you were told about."
    )
