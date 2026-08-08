"""Versioned prompts for AI flashcard-deck generation (P4.6 chunk B)."""

from __future__ import annotations

VERSION = "1"


def build_flashcard_gen_system_prompt(subject_code: str) -> str:
    return (
        f"You are an expert Cambridge IGCSE tutor for subject {subject_code}. "
        "Your task is to write flashcards that help a student revise one "
        "syllabus topic. Each flashcard has a 'front' (a short question or "
        "prompt) and a 'back' (a concise, correct answer). Cards must be "
        "atomic — one fact, definition, or concept per card, never a "
        "compound question covering several ideas at once. Return ONLY "
        "valid JSON matching the schema."
    )


def build_flashcard_gen_user_prompt(topic: str, *, count: int) -> str:
    return (
        f"Generate up to {count} flashcard(s) for the topic: {topic}.\n\n"
        "Return a GeneratedFlashcardDeck JSON object. `subject_code` must "
        f'match the subject you were told about, and `topic` must be exactly "{topic}".'
    )
