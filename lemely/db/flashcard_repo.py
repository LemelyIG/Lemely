"""Flashcard deck/card service: CRUD, AI generation, and SM-2 review recording (P4.6 chunk B).

Composes chunk A's schema (``lemely.db.models.flashcards``) and pure
scheduler (``lemely.core.spaced_repetition``) with chunk B's AI generator
(``lemely.io.flashcard_generation.FlashcardGenerator``). This module sits in
``lemely.db``, which is outside the import-linter ``app > io > core``
layering contract (``pyproject.toml`` ``[tool.importlinter]``,
``exhaustive = false``) — the same boundary D4.7's ``fill_correction_topics``
and P4.5's ``PracticeService`` already sit at, and for the identical reason:
this module must compose a pure ``core`` algorithm with an ``io`` client, and
neither layer may import the other.

**Shape mirrors ``lemely.db.practice_repo.PracticeService`` deliberately**:
a plain ``sessionmaker`` constructor argument, dataclass request/response
types, owner-scoped lookups that 404 on an unknown id and 403 on someone
else's, and a tri-state honesty vocabulary for refusals
(:class:`FlashcardUnavailableReason`) that reuses P4.5's exact
``"no_weaknesses"`` string — one machine-readable reason vocabulary across
practice and flashcards, not two that could drift.

**Non-negotiable honesty rules, each pinned by a test:**

1. **An AI-written card is stored ``source=CardSource.ai`` and stays that way
   for its whole life.** :meth:`FlashcardService.edit_card` accepts only
   ``front``/``back`` — there is no ``source`` parameter anywhere on that
   method's signature, so there is no code path that could relabel an AI
   card as manual. See :meth:`FlashcardService.edit_card`'s docstring.
2. **A weakness-generated deck records which topic it targeted** —
   :meth:`FlashcardService.create_deck`/:meth:`generate_deck` with
   ``origin=DeckOrigin.weakness`` always resolve and persist a real
   ``FlashcardDeck.topic`` (the caller's own top weak topic), never leave it
   ``NULL``.
3. **"No weakness rows" is an honest refusal, not a silently empty deck.**
   Mirrors :class:`~lemely.db.practice_repo.PracticeUnavailableReason
   .no_weaknesses` exactly — see :class:`FlashcardUnavailableReason`.
4. **Generation never fabricates precision.** :meth:`FlashcardService
   .generate_deck` returns the true generated card count
   (:attr:`GeneratedDeckResult.generated_count`) alongside the requested
   one; nothing pads a short Gemini response back up to what was asked for.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from lemely.core.spaced_repetition import CardSchedule, initial_schedule
from lemely.core.spaced_repetition import ReviewGrade as CoreReviewGrade
from lemely.core.spaced_repetition import review as apply_review
from lemely.db.models.attempts import Attempt, WeaknessRecord
from lemely.db.models.flashcards import (
    CardSource,
    DeckOrigin,
    Flashcard,
    FlashcardDeck,
    FlashcardReview,
    ReviewGrade,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.orm import Session, sessionmaker

    from lemely.io.flashcard_generation import FlashcardGenerator


def _utcnow() -> datetime:
    """Default clock: aware UTC now. Production wiring only — tests inject their own."""
    return datetime.now(UTC)


class FlashcardError(Exception):
    """Base class for flashcard service failures."""


class FlashcardNotFoundError(FlashcardError):
    """No deck/card exists for the supplied id, anywhere (→ 404)."""


class FlashcardOwnershipError(FlashcardError):
    """The deck/card exists but belongs to another student (→ 403)."""


class FlashcardValidationError(FlashcardError):
    """A request combination is structurally invalid (→ 422).

    For example ``origin='topic'`` with no ``topic`` supplied, or
    ``origin='weakness'`` with one supplied anyway
    (weakness resolves its own topic; a caller-supplied one would silently be
    ignored or would let the caller pick a topic the weakness engine never
    actually flagged — both are the same laundering this module refuses).
    """


class FlashcardGenerationUnavailableError(FlashcardError):
    """No generator was wired into this service (→ 503).

    :class:`~lemely.io.flashcard_generation.FlashcardGenerator` is optional on
    the constructor; chunk C's routes catch this and translate it.
    """


class FlashcardUnavailableReason(StrEnum):
    """Why a weakness-targeted deck was refused outright.

    Deliberately the same string :class:`~lemely.db.practice_repo
    .PracticeUnavailableReason.no_weaknesses` uses — one machine-readable
    reason vocabulary for "the caller asked for weakness targeting and has
    no ``WeaknessRecord`` rows", not two that a frontend would have to
    reconcile.
    """

    no_weaknesses = "no_weaknesses"


class FlashcardUnavailableError(FlashcardError):
    """A weakness-targeted deck was refused outright (→ 409)."""

    def __init__(self, reason: FlashcardUnavailableReason) -> None:
        """Carry the machine-readable ``reason``."""
        self.reason = reason
        super().__init__(f"Flashcard deck unavailable for reason={reason!r}")


@dataclass(frozen=True, slots=True)
class DeckSummary:
    """One deck's list-view row (S-22)."""

    id: uuid.UUID
    subject_code: str
    topic: str | None
    title: str
    description: str | None
    origin: DeckOrigin
    card_count: int
    due_count: int
    created_at: datetime


@dataclass(frozen=True, slots=True)
class CardView:
    """One card's full state, including its SM-2 schedule."""

    id: uuid.UUID
    front: str
    back: str
    position: int
    source: CardSource
    source_question_id: str | None
    repetitions: int
    ease_factor: float
    interval_days: int
    lapses: int
    due_at: datetime
    last_reviewed_at: datetime | None


@dataclass(frozen=True, slots=True)
class DeckDetail:
    """A deck plus every one of its cards (deck-detail screen)."""

    id: uuid.UUID
    subject_code: str
    topic: str | None
    title: str
    description: str | None
    origin: DeckOrigin
    cards: list[CardView]


@dataclass(frozen=True, slots=True)
class DueSession:
    """One review session's worth of due cards (S-22/S-23).

    ``total_due`` is the real backlog size regardless of any ``limit`` the
    caller applied, and ``next_due_at`` is when the *next* card comes due —
    both exist so "nothing due today" can be an informative state rather than
    an empty list.
    """

    cards: list[CardView]
    total_due: int
    next_due_at: datetime | None


@dataclass(frozen=True, slots=True)
class GeneratedDeckResult:
    """Outcome of :meth:`FlashcardService.generate_deck`."""

    deck: DeckSummary
    requested_count: int
    generated_count: int
    """The real, persisted count — may be less than ``requested_count``
    (P4.6 honesty rule: never padded)."""


@dataclass(frozen=True, slots=True)
class ReviewOutcome:
    """Outcome of :meth:`FlashcardService.record_review`."""

    card: CardView
    review_id: uuid.UUID
    grade: ReviewGrade
    interval_before_days: int
    interval_after_days: int


class FlashcardService:
    """Create/list/edit flashcard decks and cards, generate AI decks, record reviews.

    Constructed with a ``sessionmaker`` and an optional
    :class:`~lemely.io.flashcard_generation.FlashcardGenerator` — mirroring
    :class:`~lemely.db.practice_repo.PracticeService`'s plain-sessionmaker
    shape for every method that needs no Gemini call, and
    :class:`~lemely.db.quiz_marking_repo.QuizMarkingService`'s injected-client
    shape for the one that does. The generator is optional so every
    non-generation test (and most of chunk C's routes) can construct this
    service without a Gemini client at all; :meth:`generate_deck` is the only
    method that requires one, and raises
    :class:`FlashcardGenerationUnavailableError` up front if none was given.
    """

    def __init__(
        self,
        sessionmaker: sessionmaker[Session],
        generator: FlashcardGenerator | None = None,
        *,
        now: Callable[[], datetime] = _utcnow,
    ) -> None:
        """Wire the service to a session factory, an optional generator, and a clock."""
        self._sessionmaker = sessionmaker
        self._generator = generator
        self._now = now

    # -- Deck creation (manual / topic / weakness) -----------------------------

    def create_deck(
        self,
        student_id: uuid.UUID | str,
        *,
        subject_code: str,
        title: str,
        description: str | None = None,
        origin: DeckOrigin = DeckOrigin.manual,
        topic: str | None = None,
    ) -> DeckSummary:
        """Create an empty deck — manual, topic-targeted, or weakness-targeted.

        * ``origin=manual``: ``topic`` is whatever the caller passes (may be
          ``None`` — a manual deck need not target a syllabus topic).
        * ``origin=topic``: ``topic`` is required (:class:`FlashcardValidationError`
          if omitted).
        * ``origin=weakness``: ``topic`` must be ``None`` on input — this
          method resolves it from the caller's own ``WeaknessRecord`` rows
          for ``subject_code`` (highest net lost marks first) and raises
          :class:`FlashcardUnavailableError` with reason ``no_weaknesses`` if
          there are none, rather than silently creating an empty,
          untargeted deck.

        Raises:
            FlashcardValidationError: ``origin='topic'`` with no topic, or
                ``origin='weakness'`` with one supplied.
            FlashcardUnavailableError: ``origin='weakness'`` and the caller
                has no weakness data for ``subject_code`` yet.
        """
        student_uuid = _as_uuid(student_id)
        resolved_topic = self._resolve_deck_topic(student_uuid, subject_code, origin, topic)
        with self._sessionmaker() as session, session.begin():
            deck = FlashcardDeck(
                user_id=student_uuid,
                subject_code=subject_code,
                topic=resolved_topic,
                title=title,
                description=description,
                origin=origin,
            )
            session.add(deck)
            session.flush()
            return self._to_summary(deck, card_count=0, due_count=0)

    def _resolve_deck_topic(
        self,
        student_uuid: uuid.UUID,
        subject_code: str,
        origin: DeckOrigin,
        topic: str | None,
    ) -> str | None:
        if origin == DeckOrigin.topic:
            if not topic:
                raise FlashcardValidationError("origin='topic' requires a non-empty topic")
            return topic
        if origin == DeckOrigin.weakness:
            if topic is not None:
                raise FlashcardValidationError(
                    "origin='weakness' resolves its own topic; do not pass one"
                )
            with self._sessionmaker() as session:
                resolved = self._top_weak_topic(session, student_uuid, subject_code)
            if resolved is None:
                raise FlashcardUnavailableError(FlashcardUnavailableReason.no_weaknesses)
            return resolved
        return topic

    # -- AI generation ----------------------------------------------------------

    def generate_deck(
        self,
        student_id: uuid.UUID | str,
        *,
        subject_code: str,
        origin: DeckOrigin,
        count: int,
        topic: str | None = None,
        title: str | None = None,
    ) -> GeneratedDeckResult:
        """Resolve a topic, call Gemini, and persist an AI deck in one transaction.

        ``origin`` must be :attr:`~lemely.db.models.flashcards.DeckOrigin.topic`
        or :attr:`~lemely.db.models.flashcards.DeckOrigin.weakness` — a manual
        deck has no AI content to generate for
        (:class:`FlashcardValidationError`). Topic resolution follows the same
        rule as :meth:`create_deck`.

        Every card this method inserts is ``source=CardSource.ai`` (P4.6
        honesty rule 1) with its ``source_question_id`` taken verbatim from
        the generator's response.

        Raises:
            FlashcardGenerationUnavailableError: no generator was wired in.
            FlashcardValidationError: ``origin=manual``, or a topic/weakness
                mismatch (see :meth:`create_deck`).
            FlashcardUnavailableError: ``origin='weakness'`` and the caller
                has no weakness data for ``subject_code``.
        """
        if self._generator is None:
            raise FlashcardGenerationUnavailableError(
                "FlashcardService was constructed with no FlashcardGenerator"
            )
        if origin == DeckOrigin.manual:
            raise FlashcardValidationError("origin='manual' has no AI content to generate")

        student_uuid = _as_uuid(student_id)
        resolved_topic = self._resolve_deck_topic(student_uuid, subject_code, origin, topic)
        if resolved_topic is None:
            # Unreachable in practice: origin is topic or weakness here (manual
            # was excluded above), and _resolve_deck_topic never returns None
            # for either. A real runtime check rather than an assert (S101) so
            # a future bug here is a clean 422, not a stripped-in-prod assert.
            raise FlashcardValidationError("could not resolve a topic to generate for")

        generated = self._generator.generate(
            subject_code=subject_code, topic=resolved_topic, count=count
        )

        deck_title = title or f"{resolved_topic} (AI generated)"
        moment = self._now()
        with self._sessionmaker() as session, session.begin():
            deck = FlashcardDeck(
                user_id=student_uuid,
                subject_code=subject_code,
                topic=resolved_topic,
                title=deck_title,
                description=None,
                origin=origin,
            )
            session.add(deck)
            session.flush()

            for position, card in enumerate(generated.cards, start=1):
                sched = initial_schedule(moment)
                session.add(
                    Flashcard(
                        deck_id=deck.id,
                        front=card.front,
                        back=card.back,
                        position=position,
                        source=CardSource.ai,
                        source_question_id=card.source_question_id,
                        repetitions=sched.repetitions,
                        ease_factor=sched.ease_factor,
                        interval_days=sched.interval_days,
                        lapses=sched.lapses,
                        due_at=sched.due_at,
                        last_reviewed_at=sched.last_reviewed_at,
                    )
                )
            session.flush()

            return GeneratedDeckResult(
                deck=self._to_summary(
                    deck, card_count=len(generated.cards), due_count=len(generated.cards)
                ),
                requested_count=count,
                generated_count=len(generated.cards),
            )

    # -- Listing / reading --------------------------------------------------------

    def list_decks(
        self, student_id: uuid.UUID | str, *, subject_code: str | None = None
    ) -> list[DeckSummary]:
        """Every deck owned by ``student_id``, most recently created first."""
        student_uuid = _as_uuid(student_id)
        moment = self._now()
        with self._sessionmaker() as session:
            stmt = select(FlashcardDeck).where(FlashcardDeck.user_id == student_uuid)
            if subject_code is not None:
                stmt = stmt.where(FlashcardDeck.subject_code == subject_code)
            stmt = stmt.order_by(FlashcardDeck.created_at.desc())
            decks = session.scalars(stmt).all()
            summaries = []
            for deck in decks:
                card_count, due_count = self._deck_counts(session, deck.id, moment)
                summaries.append(self._to_summary(deck, card_count=card_count, due_count=due_count))
            return summaries

    def get_deck(self, student_id: uuid.UUID | str, deck_id: uuid.UUID | str) -> DeckDetail:
        """A deck and all of its cards, in position order.

        Raises:
            FlashcardNotFoundError: no deck exists with ``deck_id`` (404).
            FlashcardOwnershipError: it exists but is not the caller's (403).
        """
        student_uuid = _as_uuid(student_id)
        deck_uuid = _as_uuid(deck_id)
        with self._sessionmaker() as session:
            deck = self._owned_deck(session, student_uuid, deck_uuid)
            cards = session.scalars(
                select(Flashcard).where(Flashcard.deck_id == deck.id).order_by(Flashcard.position)
            ).all()
            return DeckDetail(
                id=deck.id,
                subject_code=deck.subject_code,
                topic=deck.topic,
                title=deck.title,
                description=deck.description,
                origin=deck.origin,
                cards=[self._to_card_view(c) for c in cards],
            )

    def list_due_cards(
        self,
        student_id: uuid.UUID | str,
        *,
        subject_code: str | None = None,
        limit: int | None = None,
    ) -> list[CardView]:
        """Every card owned by ``student_id`` due at or before now, soonest first.

        An empty list is a real state ("nothing due today", S-22) — this
        method never invents a card to fill it.
        """
        student_uuid = _as_uuid(student_id)
        moment = self._now()
        with self._sessionmaker() as session:
            stmt = (
                select(Flashcard)
                .join(FlashcardDeck, FlashcardDeck.id == Flashcard.deck_id)
                .where(FlashcardDeck.user_id == student_uuid, Flashcard.due_at <= moment)
                .order_by(Flashcard.due_at)
            )
            if subject_code is not None:
                stmt = stmt.where(FlashcardDeck.subject_code == subject_code)
            if limit is not None:
                stmt = stmt.limit(limit)
            cards = session.scalars(stmt).all()
            return [self._to_card_view(c) for c in cards]

    def due_session(
        self,
        student_id: uuid.UUID | str,
        *,
        subject_code: str | None = None,
        limit: int | None = None,
    ) -> DueSession:
        """A review session: the due cards, the true due total, and the next due time.

        S-23 serves ``cards``; S-22's "nothing due today" is a **real state
        that carries information**, not an empty list — so this returns
        ``next_due_at``, the earliest future due time among the caller's
        remaining cards, letting the screen say *when* rather than just
        *nothing*. It is ``None`` in the two cases that genuinely differ from
        "come back later": the student owns no cards at all, or every card
        they own is already due (in which case ``cards`` is non-empty anyway).

        ``total_due`` is the real count of due cards, unaffected by ``limit``
        — a capped session must not report its cap as the whole backlog
        (spec §1.4).
        """
        student_uuid = _as_uuid(student_id)
        moment = self._now()
        cards = self.list_due_cards(student_id, subject_code=subject_code, limit=limit)
        with self._sessionmaker() as session:
            due_filter = (FlashcardDeck.user_id == student_uuid, Flashcard.due_at <= moment)
            total_stmt = (
                select(func.count())
                .select_from(Flashcard)
                .join(FlashcardDeck, FlashcardDeck.id == Flashcard.deck_id)
                .where(*due_filter)
            )
            next_stmt = (
                select(func.min(Flashcard.due_at))
                .select_from(Flashcard)
                .join(FlashcardDeck, FlashcardDeck.id == Flashcard.deck_id)
                .where(FlashcardDeck.user_id == student_uuid, Flashcard.due_at > moment)
            )
            if subject_code is not None:
                total_stmt = total_stmt.where(FlashcardDeck.subject_code == subject_code)
                next_stmt = next_stmt.where(FlashcardDeck.subject_code == subject_code)
            total_due = session.scalar(total_stmt) or 0
            next_due_at = session.scalar(next_stmt)
        return DueSession(cards=cards, total_due=int(total_due), next_due_at=next_due_at)

    # -- Card mutation ------------------------------------------------------------

    def add_card(
        self,
        student_id: uuid.UUID | str,
        deck_id: uuid.UUID | str,
        *,
        front: str,
        back: str,
    ) -> CardView:
        """Add a manual card to a deck the caller owns.

        Always ``source=CardSource.manual`` — there is no ``source``
        parameter, so a student-written card can never be mistaken for an
        AI one at creation time.

        Raises:
            FlashcardNotFoundError: no deck exists with ``deck_id`` (404).
            FlashcardOwnershipError: it exists but is not the caller's (403).
        """
        student_uuid = _as_uuid(student_id)
        deck_uuid = _as_uuid(deck_id)
        moment = self._now()
        with self._sessionmaker() as session, session.begin():
            deck = self._owned_deck(session, student_uuid, deck_uuid)
            position = self._next_position(session, deck.id)
            sched = initial_schedule(moment)
            card = Flashcard(
                deck_id=deck.id,
                front=front,
                back=back,
                position=position,
                source=CardSource.manual,
                source_question_id=None,
                repetitions=sched.repetitions,
                ease_factor=sched.ease_factor,
                interval_days=sched.interval_days,
                lapses=sched.lapses,
                due_at=sched.due_at,
                last_reviewed_at=sched.last_reviewed_at,
            )
            session.add(card)
            session.flush()
            return self._to_card_view(card)

    def edit_card(
        self,
        student_id: uuid.UUID | str,
        card_id: uuid.UUID | str,
        *,
        front: str | None = None,
        back: str | None = None,
    ) -> CardView:
        """Edit a card's front/back content only.

        **There is no ``source`` parameter on this method, on purpose.** An
        AI-written card stays ``source=CardSource.ai`` for its whole life
        (P4.6 honesty rule 1) — editing its wording is a legitimate student
        action (fixing a typo, rephrasing an answer in their own words), but
        it must never silently launder the card into looking like the
        student's own original content. Pinned by
        ``test_edit_card_does_not_change_an_ai_cards_source`` — if a future
        change ever needs to let a student "claim" an AI card as their own,
        that has to be a new, explicitly-named operation, not a side effect
        of editing text.

        Raises:
            FlashcardNotFoundError: no card exists with ``card_id`` (404).
            FlashcardOwnershipError: it exists but is not the caller's (403).
        """
        student_uuid = _as_uuid(student_id)
        card_uuid = _as_uuid(card_id)
        with self._sessionmaker() as session, session.begin():
            card = self._owned_card(session, student_uuid, card_uuid)
            if front is not None:
                card.front = front
            if back is not None:
                card.back = back
            session.flush()
            return self._to_card_view(card)

    def delete_card(self, student_id: uuid.UUID | str, card_id: uuid.UUID | str) -> None:
        """Delete a card the caller owns.

        Raises:
            FlashcardNotFoundError: no card exists with ``card_id`` (404).
            FlashcardOwnershipError: it exists but is not the caller's (403).
        """
        student_uuid = _as_uuid(student_id)
        card_uuid = _as_uuid(card_id)
        with self._sessionmaker() as session, session.begin():
            card = self._owned_card(session, student_uuid, card_uuid)
            session.delete(card)

    def delete_deck(self, student_id: uuid.UUID | str, deck_id: uuid.UUID | str) -> None:
        """Delete a deck the caller owns, and every card in it.

        The cards go with it by cascade — ``FlashcardDeck.cards`` is
        ``delete-orphan`` at the ORM level and ``flashcards.deck_id`` is
        ``ON DELETE CASCADE`` at the DB level, so a deck's cards can never
        outlive it as orphans pointing at a dead deck id. Their
        ``FlashcardReview`` audit rows cascade in turn.

        This exists because :meth:`generate_deck` can put a deck a student
        never wanted in front of them; without deletion the only remedy would
        be removing cards one at a time and leaving an empty husk behind.

        Raises:
            FlashcardNotFoundError: no deck exists with ``deck_id`` (404).
            FlashcardOwnershipError: it exists but is not the caller's (403).
        """
        student_uuid = _as_uuid(student_id)
        deck_uuid = _as_uuid(deck_id)
        with self._sessionmaker() as session, session.begin():
            deck = self._owned_deck(session, student_uuid, deck_uuid)
            session.delete(deck)

    # -- Review recording -----------------------------------------------------------

    def record_review(
        self,
        student_id: uuid.UUID | str,
        card_id: uuid.UUID | str,
        grade: ReviewGrade,
        *,
        now: datetime | None = None,
    ) -> ReviewOutcome:
        """Apply one SM-2 review via :func:`lemely.core.spaced_repetition.review`.

        Persists the new schedule onto the card **and** appends a
        :class:`~lemely.db.models.flashcards.FlashcardReview` audit row
        recording the before/after interval and the new ease factor — so a
        human (or a test) can check the scheduler was applied correctly
        after the fact, per the module docstring.

        Args:
            student_id: The owning student — a card belonging to anyone else
                raises :class:`FlashcardOwnershipError`, never silently
                reschedules.
            card_id: The card being reviewed.
            grade: The DB-enum grade (``lemely.db.models.flashcards
                .ReviewGrade``); converted to the core scheduler's mirrored
                enum by value, never imported across the ``core``/``db``
                boundary (see both enums' docstrings).
            now: Injected clock override for tests; defaults to this
                service's constructor-supplied clock.

        Raises:
            FlashcardNotFoundError: no card exists with ``card_id`` (404).
            FlashcardOwnershipError: it exists but is not the caller's (403).
        """
        student_uuid = _as_uuid(student_id)
        card_uuid = _as_uuid(card_id)
        moment = now if now is not None else self._now()
        core_grade = CoreReviewGrade(grade.value)
        with self._sessionmaker() as session, session.begin():
            card = self._owned_card(session, student_uuid, card_uuid)
            schedule_before = CardSchedule(
                repetitions=card.repetitions,
                ease_factor=card.ease_factor,
                interval_days=card.interval_days,
                lapses=card.lapses,
                due_at=card.due_at,
                last_reviewed_at=card.last_reviewed_at,
            )
            schedule_after = apply_review(schedule_before, core_grade, now=moment)

            card.repetitions = schedule_after.repetitions
            card.ease_factor = schedule_after.ease_factor
            card.interval_days = schedule_after.interval_days
            card.lapses = schedule_after.lapses
            card.due_at = schedule_after.due_at
            card.last_reviewed_at = schedule_after.last_reviewed_at

            review_row = FlashcardReview(
                card_id=card.id,
                user_id=student_uuid,
                grade=grade,
                reviewed_at=moment,
                interval_before_days=schedule_before.interval_days,
                interval_after_days=schedule_after.interval_days,
                ease_after=schedule_after.ease_factor,
            )
            session.add(review_row)
            session.flush()

            return ReviewOutcome(
                card=self._to_card_view(card),
                review_id=review_row.id,
                grade=grade,
                interval_before_days=schedule_before.interval_days,
                interval_after_days=schedule_after.interval_days,
            )

    # -- Internals ----------------------------------------------------------------

    def _owned_deck(
        self, session: Session, student_uuid: uuid.UUID, deck_uuid: uuid.UUID
    ) -> FlashcardDeck:
        deck = session.get(FlashcardDeck, deck_uuid)
        if deck is None:
            raise FlashcardNotFoundError(f"Unknown deck: {deck_uuid}")
        if deck.user_id != student_uuid:
            raise FlashcardOwnershipError(
                f"Deck {deck_uuid} is not owned by student {student_uuid}"
            )
        return deck

    def _owned_card(
        self, session: Session, student_uuid: uuid.UUID, card_uuid: uuid.UUID
    ) -> Flashcard:
        card = session.get(Flashcard, card_uuid)
        if card is None:
            raise FlashcardNotFoundError(f"Unknown card: {card_uuid}")
        deck = session.get(FlashcardDeck, card.deck_id)
        if deck is None or deck.user_id != student_uuid:
            raise FlashcardOwnershipError(
                f"Card {card_uuid} is not owned by student {student_uuid}"
            )
        return card

    def _next_position(self, session: Session, deck_id: uuid.UUID) -> int:
        highest = session.scalar(
            select(func.coalesce(func.max(Flashcard.position), 0)).where(
                Flashcard.deck_id == deck_id
            )
        )
        return int(highest or 0) + 1

    def _deck_counts(
        self, session: Session, deck_id: uuid.UUID, moment: datetime
    ) -> tuple[int, int]:
        total = (
            session.scalar(
                select(func.count()).select_from(Flashcard).where(Flashcard.deck_id == deck_id)
            )
            or 0
        )
        due = (
            session.scalar(
                select(func.count())
                .select_from(Flashcard)
                .where(Flashcard.deck_id == deck_id, Flashcard.due_at <= moment)
            )
            or 0
        )
        return total, due

    def _top_weak_topic(
        self, session: Session, student_uuid: uuid.UUID, subject_code: str
    ) -> str | None:
        """The caller's single most-net-lost-marks topic for ``subject_code``.

        Mirrors :meth:`~lemely.db.practice_repo.PracticeService
        ._weak_topics_for`'s aggregation (D4.10 §2: read ``WeaknessRecord``
        rows verbatim for the subject, never re-derive the weakness engine),
        but reduces to a single topic rather than the full set, because a
        flashcard deck targets exactly one topic
        (``FlashcardDeck.topic`` is singular — see the module docstring).
        Ties broken alphabetically for a deterministic result. Returns
        ``None`` when the caller has no ``WeaknessRecord`` row with net lost
        marks > 0 for this subject — the caller turns that into the
        ``no_weaknesses`` refusal.
        """
        rows = session.execute(
            select(WeaknessRecord.topic, WeaknessRecord.lost_marks)
            .join(Attempt, Attempt.id == WeaknessRecord.attempt_id)
            .where(WeaknessRecord.user_id == student_uuid, Attempt.subject_code == subject_code)
        ).all()
        totals: dict[str, int] = {}
        for topic, lost in rows:
            totals[topic] = totals.get(topic, 0) + lost
        candidates = sorted(
            (t for t, lost in totals.items() if lost > 0), key=lambda t: (-totals[t], t)
        )
        return candidates[0] if candidates else None

    def _to_summary(self, deck: FlashcardDeck, *, card_count: int, due_count: int) -> DeckSummary:
        return DeckSummary(
            id=deck.id,
            subject_code=deck.subject_code,
            topic=deck.topic,
            title=deck.title,
            description=deck.description,
            origin=deck.origin,
            card_count=card_count,
            due_count=due_count,
            created_at=deck.created_at,
        )

    def _to_card_view(self, card: Flashcard) -> CardView:
        return CardView(
            id=card.id,
            front=card.front,
            back=card.back,
            position=card.position,
            source=card.source,
            source_question_id=card.source_question_id,
            repetitions=card.repetitions,
            ease_factor=card.ease_factor,
            interval_days=card.interval_days,
            lapses=card.lapses,
            due_at=card.due_at,
            last_reviewed_at=card.last_reviewed_at,
        )


def _as_uuid(value: uuid.UUID | str) -> uuid.UUID:
    """Coerce a str/UUID to :class:`uuid.UUID`, raising ``ValueError`` if invalid."""
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Identifier must be a UUID, got {value!r}") from exc


__all__ = [
    "CardView",
    "DeckDetail",
    "DeckSummary",
    "DueSession",
    "FlashcardError",
    "FlashcardGenerationUnavailableError",
    "FlashcardNotFoundError",
    "FlashcardOwnershipError",
    "FlashcardService",
    "FlashcardUnavailableError",
    "FlashcardUnavailableReason",
    "FlashcardValidationError",
    "GeneratedDeckResult",
    "ReviewOutcome",
]
