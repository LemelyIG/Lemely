"""Pure schemas for AI-generated flashcard content (P4.6 chunk B).

Mirrors :mod:`lemely.core.generation`'s ``GeneratedQuestion``/``GeneratedQuiz``
shape closely: a Gemini structured-output response is parsed straight into
these ``StrictModel`` subclasses by
:class:`~lemely.io.flashcard_generation.FlashcardGenerator`, and nothing here
imports ``io`` or ``db`` (import-linter layering contract,
``pyproject.toml`` ``[tool.importlinter]``).

**One deck targets one topic.** Unlike ``GeneratedQuiz`` (a bag of questions
across whatever topics a ``WeaknessReport`` names), a flashcard deck is
always about a single syllabus topic —
``lemely.db.models.flashcards.FlashcardDeck.topic`` is one string, and the
P4.6 honesty rule requires a weakness-generated deck to record *which* topic
it targeted. So :class:`GeneratedFlashcardDeck` carries one ``topic`` field,
not a per-card one.

**Never fabricate precision (spec §1.4).** ``GeneratedFlashcardDeck.cards``
may hold fewer cards than were requested — Gemini is free to return less than
it was asked for, and neither this module nor
:mod:`lemely.io.flashcard_generation` pads the list back up to the requested
count. The caller (:mod:`lemely.db.flashcard_repo`) is responsible for
reporting the true generated count rather than the requested one.
"""

from __future__ import annotations

from pydantic import field_validator

from lemely.core.schemas import StrictModel


class GeneratedFlashcard(StrictModel):
    """One AI-authored flashcard: a front (prompt) and a back (answer).

    ``source_question_id`` carries the past-paper ``source_question_id``
    (P4.1's ``"<stem>#<n>"`` convention, e.g. ``"0625_s23_qp_11#22"``) when
    this card was derived from one specific bank question; ``None`` when it
    was not (the ordinary case — Gemini is asked to write revision cards for
    a topic, not to transcribe a specific question).
    """

    front: str
    back: str
    source_question_id: str | None = None

    @field_validator("front", "back")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("flashcard front/back must not be blank")
        return value


class GeneratedFlashcardDeck(StrictModel):
    """A generated deck: the topic it targeted, plus whatever cards Gemini wrote.

    ``topic`` is always the P4.2 ``"<code> <name>"`` syllabus vocabulary
    (e.g. ``"4.3 Electric circuits"``) — the same one
    ``FlashcardDeck.topic``, ``StudentConfidenceRating.topic`` and the
    weakness engine use, because it is either a caller-picked syllabus topic
    or a topic resolved from the caller's own ``WeaknessRecord`` rows, never
    invented by this module.
    """

    subject_code: str
    topic: str
    cards: list[GeneratedFlashcard]


__all__ = ["GeneratedFlashcard", "GeneratedFlashcardDeck"]
