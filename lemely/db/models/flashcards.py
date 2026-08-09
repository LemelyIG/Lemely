"""ORM models for flashcard decks, cards, and reviews (P4.6 chunk A).

Three tables, additive only (migration ``0011_flashcards``):

* :class:`FlashcardDeck` — one deck belongs to exactly one student
  (``user_id``, ``ON DELETE CASCADE``). There is no shared-deck case in this
  phase, which is why the SM-2 scheduling state lives directly on the card
  rather than in a per-(user, card) join table — see :class:`Flashcard`.
* :class:`Flashcard` — one card, its content, and its full SM-2 scheduling
  state.
* :class:`FlashcardReview` — the append-only audit log of every grade a
  student has given a card, recording the before/after scheduling state so a
  human can check the scheduler after the fact (and P5's XP seam, see
  ``XpSource.flashcard_reviewed``).

This module is schema only (P4.6 chunk A) — no repo, no service, no route
reads or writes any of these tables yet (those are chunks B and C). The
scheduling *algorithm* is deliberately not here: it lives in
``lemely.core.spaced_repetition``, pure and clock-injected, because a model
module sits in the ``db`` layer and the import-linter layering contract
(``pyproject.toml`` ``[tool.importlinter]``) forbids ``core`` depending on
``db`` — the algorithm cannot live where the columns it schedules do.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from lemely.db.base import Base
from lemely.db.models.enums import TimestampMixin

# ---------------------------------------------------------------------------
# Enum definitions
# ---------------------------------------------------------------------------


class DeckOrigin(enum.Enum):
    """How a :class:`FlashcardDeck` came to exist."""

    manual = "manual"
    weakness = "weakness"
    topic = "topic"


class CardSource(enum.Enum):
    """Whether a :class:`Flashcard`'s content was written by a student or AI.

    An AI-written card is stored ``source='ai'`` and stays distinguishable
    from a student's own card for its whole life (P4.6 honesty rule, chunk
    B's generation path) — never silently relabelled once created.
    """

    manual = "manual"
    ai = "ai"


class ReviewGrade(enum.Enum):
    """The four-button self-grade a student gives a flashcard review.

    **This mirrors, and must stay in lock-step with,
    ``lemely.core.spaced_repetition.ReviewGrade`` — it is not imported from
    there.** ``core`` must not import ``db`` (import-linter layering
    contract), so the grade vocabulary is declared twice on purpose, once as
    a pure-Python enum the scheduler runs on and once as this Postgres enum
    the schema stores. ``tests/test_flashcard_schema.py`` pins that the two
    stay identical; if a future change adds/removes/renames a member on one
    side without the other, that test is what catches the drift — do not
    "fix" the duplication by importing across the boundary.
    """

    again = "again"
    hard = "hard"
    good = "good"
    easy = "easy"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class FlashcardDeck(TimestampMixin, Base):
    """A named collection of flashcards owned by exactly one student.

    ``topic``, when present, is in the P4.2 ``"<code> <name>"`` syllabus
    vocabulary (e.g. ``"4.3 Electric circuits"``) — the same vocabulary
    ``StudentConfidenceRating.topic`` and the weakness engine use, so a
    weakness- or topic-originated deck can be joined against them without a
    translation layer. It is nullable because a manually created deck (S-22)
    need not target a single syllabus topic.
    """

    __tablename__ = "flashcard_decks"
    __table_args__ = (
        sa.Index("ix_flashcard_decks_user_id_subject_code", "user_id", "subject_code"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    subject_code: Mapped[str] = mapped_column(sa.String, nullable=False)
    topic: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    title: Mapped[str] = mapped_column(sa.String, nullable=False)
    description: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    origin: Mapped[DeckOrigin] = mapped_column(
        sa.Enum(DeckOrigin, name="deckorigin"),
        nullable=False,
    )

    cards: Mapped[list[Flashcard]] = relationship(
        "Flashcard", back_populates="deck", cascade="all, delete-orphan"
    )


class Flashcard(TimestampMixin, Base):
    """One flashcard's content and its full SM-2 scheduling state.

    The SM-2 state (``repetitions``/``ease_factor``/``interval_days``/
    ``lapses``/``due_at``/``last_reviewed_at``) lives directly on the card
    rather than in a join table, because a deck is owned by exactly one
    student — there is no shared-deck case in this phase to key per-student
    progress around (P4.6 chunk plan). The server defaults below reproduce
    exactly what ``lemely.core.spaced_repetition.initial_schedule`` computes
    for a brand-new card; ``tests/test_flashcard_schema.py`` pins that the
    two never drift apart.
    """

    __tablename__ = "flashcards"
    __table_args__ = (sa.Index("ix_flashcards_deck_id_due_at", "deck_id", "due_at"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    deck_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("flashcard_decks.id", ondelete="CASCADE"),
        nullable=False,
    )
    front: Mapped[str] = mapped_column(sa.Text, nullable=False)
    back: Mapped[str] = mapped_column(sa.Text, nullable=False)
    position: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    source: Mapped[CardSource] = mapped_column(
        sa.Enum(CardSource, name="cardsource"),
        nullable=False,
    )
    source_question_id: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    """The ``question_bank.source_question_id`` this card was derived from,
    when chunk B's AI generation built it from a past-paper question; NULL
    for a manually written card or an AI card with no single source question.
    """

    repetitions: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default=sa.text("0")
    )
    ease_factor: Mapped[float] = mapped_column(
        sa.Float, nullable=False, server_default=sa.text("2.5")
    )
    interval_days: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default=sa.text("0")
    )
    lapses: Mapped[int] = mapped_column(sa.Integer, nullable=False, server_default=sa.text("0"))
    due_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )
    """A new card is due immediately (``lemely.core.spaced_repetition.
    initial_schedule``) — ``now()`` at insert time, not some future date, so
    a freshly created card shows up in "due today" rather than being invisible
    until tomorrow."""
    last_reviewed_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )

    deck: Mapped[FlashcardDeck] = relationship("FlashcardDeck", back_populates="cards")
    reviews: Mapped[list[FlashcardReview]] = relationship(
        "FlashcardReview", back_populates="card", cascade="all, delete-orphan"
    )


class FlashcardReview(TimestampMixin, Base):
    """Append-only audit log of one graded review of a :class:`Flashcard`.

    Records the scheduler's before/after state so a human (or a test) can
    check ``lemely.core.spaced_repetition.review`` was applied correctly
    after the fact, and doubles as P5's XP seam
    (``XpSource.flashcard_reviewed``) once that phase wires it up.
    """

    __tablename__ = "flashcard_reviews"
    __table_args__ = (
        sa.Index("ix_flashcard_reviews_user_id_reviewed_at", "user_id", "reviewed_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    card_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("flashcards.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    grade: Mapped[ReviewGrade] = mapped_column(
        sa.Enum(ReviewGrade, name="reviewgrade"),
        nullable=False,
    )
    reviewed_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    interval_before_days: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    interval_after_days: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    ease_after: Mapped[float] = mapped_column(sa.Float, nullable=False)

    card: Mapped[Flashcard] = relationship("Flashcard", back_populates="reviews")


__all__ = [
    "CardSource",
    "DeckOrigin",
    "Flashcard",
    "FlashcardDeck",
    "FlashcardReview",
    "ReviewGrade",
]
