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

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from lemely.core.spaced_repetition import AGAIN_REVIEW_DELAY, CardSchedule, initial_schedule
from lemely.core.spaced_repetition import ReviewGrade as CoreReviewGrade
from lemely.core.spaced_repetition import review as apply_review
from lemely.db.models.attempts import Attempt, WeaknessRecord
from lemely.db.models.flashcards import (
    CardSource,
    DeckGenerationStatus,
    DeckOrigin,
    Flashcard,
    FlashcardDeck,
    FlashcardReview,
    ReviewGrade,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    import sqlalchemy as sa
    from sqlalchemy.orm import Session, sessionmaker

    from lemely.io.flashcard_generation import FlashcardGenerator


log = structlog.get_logger(__name__)

#: A card whose interval has reached a week counts as "known" on the deck's mastery bar.
#: "Easy" on a young card sends it about a week out, so "known" means "you said it was easy".
KNOWN_INTERVAL_DAYS = 7
#: How far ahead :meth:`FlashcardService.due_session` lists upcoming due times ("Coming back").
UPCOMING_WINDOW = timedelta(days=8)
#: Hard cap on the forecast list so a huge backlog can't bloat the response.
UPCOMING_CAP = 1000
#: Longest title a rename accepts.
DECK_TITLE_MAX = 80
#: A topic label's leading syllabus code, e.g. ``"4.3 "`` in ``"4.3 Electric circuits"``.
_TOPIC_CODE = re.compile(r"^[A-Z]?\d+(?:\.\d+)*\s+")


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
    mastery: MasteryCounts
    marks_lost: int | None
    """Net marks the deck's topic cost the student. Only for ``origin=weakness``."""
    generation_status: DeckGenerationStatus
    requested_count: int | None


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
    next_interval_days: dict[str, int]
    """The interval in days each grade would give right now (``again`` is 0: the 10-minute step)."""


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
    due_count: int
    mastery: MasteryCounts
    marks_lost: int | None
    generation_status: DeckGenerationStatus
    requested_count: int | None


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
    upcoming: list[datetime]
    """Due times of cards coming due within :data:`UPCOMING_WINDOW`, soonest first."""
    again_delay_minutes: int


@dataclass(frozen=True, slots=True)
class MasteryCounts:
    """How a deck's cards split on the mastery bar: never reviewed, in progress, known."""

    new: int
    learning: int
    known: int


@dataclass(frozen=True, slots=True)
class WeakTopic:
    """One recorded weak topic, for the new-deck sheet's chips."""

    subject_code: str
    topic: str
    marks_lost: int
    accuracy_pct: int


@dataclass(frozen=True, slots=True)
class _DeckCounts:
    total: int
    due: int
    mastery: MasteryCounts

    @classmethod
    def empty(cls) -> _DeckCounts:
        return cls(total=0, due=0, mastery=MasteryCounts(new=0, learning=0, known=0))


#: A ``writing`` deck older than this is reported (and saved) as failed: its worker died.
GENERATION_STALE_AFTER = timedelta(minutes=5)
GENERATION_TIMEOUT_SECONDS = 120.0
"""Bound on the model call. Under the 300 s Cloud Run request timeout, so the request that runs
the generation always has time left to mark the deck ``failed`` and answer."""


@dataclass(frozen=True, slots=True)
class GenerationState:
    """Where one deck's card writing stands. ``generated_count`` is the real row count."""

    deck_id: uuid.UUID
    status: DeckGenerationStatus
    requested_count: int | None
    generated_count: int
    error: str | None


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
    subject_code: str
    """The owning deck's subject (P5.2 chunk B) — not part of the wire DTO
    (``lemely.web.routers.flashcards`` doesn't read it); it exists so the web
    layer can award ``flashcard_reviewed`` XP with the right subject
    attribution (D5.1 §7/D5.2) without a second query."""


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
        generation_timeout_seconds: float = GENERATION_TIMEOUT_SECONDS,
    ) -> None:
        """Wire the service to a session factory, an optional generator, and a clock."""
        self._sessionmaker = sessionmaker
        self._generator = generator
        self._now = now
        self._generation_timeout = generation_timeout_seconds

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
        * ``origin=weakness``: ``topic`` may be omitted, in which case this method picks the
          caller's own top weak topic for ``subject_code`` (highest net lost marks first); or it
          may be one of the caller's recorded weak topics. It raises
          :class:`FlashcardUnavailableError` with reason ``no_weaknesses`` if there are none,
          rather than silently creating an empty, untargeted deck.

        Raises:
            FlashcardValidationError: ``origin='topic'`` with no topic, or
                ``origin='weakness'`` with a topic that is not a recorded weakness.
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
                generation_status=DeckGenerationStatus.ready.value,
            )
            session.add(deck)
            session.flush()
            return self._to_summary(deck, _DeckCounts.empty(), marks_lost=None)

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
            with self._sessionmaker() as session:
                totals = self._weak_topic_totals(session, student_uuid, subject_code)
            if not totals:
                raise FlashcardUnavailableError(FlashcardUnavailableReason.no_weaknesses)
            if topic is None:
                return sorted(totals, key=lambda t: (-totals[t], t))[0]
            if topic not in totals:
                # The student may choose among their own recorded weak topics, never name one the
                # weakness engine did not flag: that would launder an arbitrary topic as a weakness.
                raise FlashcardValidationError(
                    "origin='weakness' topic must be one of your recorded weak topics"
                )
            return topic
        return topic

    # -- AI generation ----------------------------------------------------------

    @staticmethod
    def _default_title(topic: str) -> str:
        name = _TOPIC_CODE.sub("", topic).strip()
        return name or topic

    def start_generation(
        self,
        student_id: uuid.UUID | str,
        *,
        subject_code: str,
        origin: DeckOrigin,
        count: int,
        topic: str | None = None,
        title: str | None = None,
    ) -> DeckSummary:
        """Resolve the topic and save an empty ``writing`` deck. No model call happens here.

        The caller must hand :meth:`run_generation` to a worker request (a Cloud Tasks job), so the
        student can leave the screen while the cards are written. Do not run it as post-response
        background work: Cloud Run throttles CPU once the response is sent, so it would stall.
        A deck whose worker never finishes is saved as ``failed/timeout`` once it goes stale.

        Raises:
            FlashcardGenerationUnavailableError: no generator was wired in (checked first).
            FlashcardValidationError: ``origin=manual`` or a topic mismatch.
            FlashcardUnavailableError: weakness origin with no recorded weaknesses.
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
            raise FlashcardValidationError("could not resolve a topic to generate for")
        with self._sessionmaker() as session, session.begin():
            deck = FlashcardDeck(
                user_id=student_uuid,
                subject_code=subject_code,
                topic=resolved_topic,
                title=(title or "").strip() or self._default_title(resolved_topic),
                description=None,
                origin=origin,
                generation_status=DeckGenerationStatus.writing.value,
                requested_count=count,
                generation_started_at=self._now(),
                generation_error=None,
            )
            session.add(deck)
            session.flush()
            return self._to_summary(deck, _DeckCounts.empty(), marks_lost=None)

    def run_generation(self, deck_id: uuid.UUID | str) -> None:
        """Write the cards for a ``writing`` deck, then mark it ``ready`` or ``failed``.

        Never raises: it runs in a worker, where an exception would only reach a log. Any model
        or database error marks the deck ``failed`` (and is logged if even that write fails). A
        deck that is no longer ``writing`` (deleted, or already finished) is left alone.
        """
        try:
            deck_uuid = _as_uuid(deck_id)
        except ValueError:
            log.exception("flashcard_generation_bad_deck_id", deck_id=str(deck_id))
            return
        try:
            self._run_generation(deck_uuid)
        except Exception:  # last line of defence: the worker must never crash
            log.exception("flashcard_generation_internal_error", deck_id=str(deck_uuid))
            self._mark_failed_quietly(deck_uuid, "internal_error")

    def _run_generation(self, deck_uuid: uuid.UUID) -> None:
        with self._sessionmaker() as session:
            deck = session.get(FlashcardDeck, deck_uuid)
            if deck is None or deck.generation_status != DeckGenerationStatus.writing.value:
                return
            subject_code, topic, count = deck.subject_code, deck.topic, deck.requested_count or 0
        if self._generator is None or topic is None or count < 1:
            self._mark_failed_quietly(deck_uuid, "unavailable")
            return
        try:
            generated = self._generator.generate(
                subject_code=subject_code,
                topic=topic,
                count=count,
                timeout_seconds=self._generation_timeout,
            )
        except TimeoutError:
            log.error("flashcard_generation_timeout", deck_id=str(deck_uuid))
            self._mark_failed_quietly(deck_uuid, "timeout")
            return
        except Exception:  # any model or parse failure is a failed deck, never a crash
            log.exception("flashcard_generation_failed", deck_id=str(deck_uuid))
            self._mark_failed_quietly(deck_uuid, "model_error")
            return
        if not generated.cards:
            self._mark_failed_quietly(deck_uuid, "no_cards")
            return
        moment = self._now()
        with self._sessionmaker() as session, session.begin():
            deck = session.get(FlashcardDeck, deck_uuid)
            if deck is None or deck.generation_status != DeckGenerationStatus.writing.value:
                return
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
            deck.generation_status = DeckGenerationStatus.ready.value
            deck.generation_error = None
        log.info(
            "flashcard_generation_ready",
            deck_id=str(deck_uuid),
            requested=count,
            generated=len(generated.cards),
        )

    def _mark_failed_quietly(self, deck_uuid: uuid.UUID, error: str) -> None:
        """Mark the deck failed; if that write fails too, log it (the stale timeout recovers)."""
        try:
            self._mark_failed(deck_uuid, error)
        except Exception:
            log.exception("flashcard_generation_mark_failed_error", deck_id=str(deck_uuid))

    def _mark_failed(self, deck_uuid: uuid.UUID, error: str) -> None:
        with self._sessionmaker() as session, session.begin():
            deck = session.get(FlashcardDeck, deck_uuid)
            if deck is not None and deck.generation_status == DeckGenerationStatus.writing.value:
                deck.generation_status = DeckGenerationStatus.failed.value
                deck.generation_error = error

    @staticmethod
    def _expire_if_stale(deck: FlashcardDeck, moment: datetime) -> None:
        """Save a ``writing`` deck past :data:`GENERATION_STALE_AFTER` as ``failed/timeout``."""
        if (
            deck.generation_status == DeckGenerationStatus.writing.value
            and deck.generation_started_at is not None
            and moment - deck.generation_started_at > GENERATION_STALE_AFTER
        ):
            deck.generation_status = DeckGenerationStatus.failed.value
            deck.generation_error = "timeout"

    def generation_status(
        self, student_id: uuid.UUID | str, deck_id: uuid.UUID | str
    ) -> GenerationState:
        """The deck's writing status.

        A ``writing`` deck past :data:`GENERATION_STALE_AFTER` is saved as ``failed``
        (``timeout``) first, so the list and this endpoint agree.
        """
        student_uuid = _as_uuid(student_id)
        deck_uuid = _as_uuid(deck_id)
        moment = self._now()
        with self._sessionmaker() as session, session.begin():
            deck = self._owned_deck(session, student_uuid, deck_uuid)
            self._expire_if_stale(deck, moment)
            generated = session.scalar(
                select(func.count()).select_from(Flashcard).where(Flashcard.deck_id == deck.id)
            )
            return GenerationState(
                deck_id=deck.id,
                status=DeckGenerationStatus(deck.generation_status),
                requested_count=deck.requested_count,
                generated_count=int(generated or 0),
                error=deck.generation_error,
            )

    def retry_generation(
        self, student_id: uuid.UUID | str, deck_id: uuid.UUID | str
    ) -> GenerationState:
        """Put a ``failed`` deck back to ``writing``. The caller schedules :meth:`run_generation`.

        Raises:
            FlashcardValidationError: the deck is not failed (ready, or still writing).
        """
        state = self.generation_status(student_id, deck_id)
        if state.status != DeckGenerationStatus.failed:
            raise FlashcardValidationError("only a deck whose writing failed can be retried")
        with self._sessionmaker() as session, session.begin():
            claimed = session.execute(
                update(FlashcardDeck)
                .where(
                    FlashcardDeck.id == state.deck_id,
                    FlashcardDeck.generation_status == DeckGenerationStatus.failed.value,
                )
                .values(
                    generation_status=DeckGenerationStatus.writing.value,
                    generation_started_at=self._now(),
                    generation_error=None,
                )
            )
            if getattr(claimed, "rowcount", 0) != 1:
                raise FlashcardValidationError("only a deck whose writing failed can be retried")
        return GenerationState(
            deck_id=state.deck_id,
            status=DeckGenerationStatus.writing,
            requested_count=state.requested_count,
            generated_count=state.generated_count,
            error=None,
        )

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
        """Synchronous generation: :meth:`start_generation`, then :meth:`run_generation`.

        Kept for scripts and tests. ``generated_count`` is the real persisted count, never padded.
        """
        deck = self.start_generation(
            student_id,
            subject_code=subject_code,
            origin=origin,
            count=count,
            topic=topic,
            title=title,
        )
        self.run_generation(deck.id)
        [summary] = [d for d in self.list_decks(student_id) if d.id == deck.id]
        return GeneratedDeckResult(
            deck=summary, requested_count=count, generated_count=summary.card_count
        )

    # -- Listing / reading --------------------------------------------------------

    def list_decks(
        self, student_id: uuid.UUID | str, *, subject_code: str | None = None
    ) -> list[DeckSummary]:
        """Every deck owned by ``student_id``, most recently created first."""
        student_uuid = _as_uuid(student_id)
        moment = self._now()
        with self._sessionmaker() as session, session.begin():
            stmt = select(FlashcardDeck).where(FlashcardDeck.user_id == student_uuid)
            if subject_code is not None:
                stmt = stmt.where(FlashcardDeck.subject_code == subject_code)
            stmt = stmt.order_by(FlashcardDeck.created_at.desc())
            decks = session.scalars(stmt).all()
            for deck in decks:
                self._expire_if_stale(deck, moment)
            marks = self._marks_lost_by_topic(session, student_uuid)
            return [
                self._to_summary(
                    deck,
                    self._deck_counts(session, deck.id, moment),
                    marks_lost=self._deck_marks_lost(deck, marks),
                )
                for deck in decks
            ]

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
            counts = self._deck_counts(session, deck.id, self._now())
            marks = self._marks_lost_by_topic(session, student_uuid)
            return DeckDetail(
                id=deck.id,
                subject_code=deck.subject_code,
                topic=deck.topic,
                title=deck.title,
                description=deck.description,
                origin=deck.origin,
                cards=[self._to_card_view(c) for c in cards],
                due_count=counts.due,
                mastery=counts.mastery,
                marks_lost=self._deck_marks_lost(deck, marks),
                generation_status=DeckGenerationStatus(deck.generation_status),
                requested_count=deck.requested_count,
            )

    def deck_summary(self, student_id: uuid.UUID | str, deck_id: uuid.UUID | str) -> DeckSummary:
        """One of the caller's decks as a list row, with its current status and counts.

        Raises:
            FlashcardNotFoundError / FlashcardOwnershipError: as :meth:`get_deck`.
        """
        student_uuid = _as_uuid(student_id)
        deck_uuid = _as_uuid(deck_id)
        moment = self._now()
        with self._sessionmaker() as session, session.begin():
            deck = self._owned_deck(session, student_uuid, deck_uuid)
            self._expire_if_stale(deck, moment)
            session.flush()
            marks = self._marks_lost_by_topic(session, student_uuid)
            return self._to_summary(
                deck,
                self._deck_counts(session, deck.id, moment),
                marks_lost=self._deck_marks_lost(deck, marks),
            )

    def rename_deck(
        self, student_id: uuid.UUID | str, deck_id: uuid.UUID | str, *, title: str
    ) -> DeckSummary:
        """Rename one of the caller's decks. The title is trimmed; blank or over 80 chars is 422.

        Raises:
            FlashcardValidationError: blank or too long.
            FlashcardNotFoundError / FlashcardOwnershipError: as :meth:`get_deck`.
        """
        cleaned = title.strip()
        if not cleaned or len(cleaned) > DECK_TITLE_MAX:
            raise FlashcardValidationError(f"title must be 1-{DECK_TITLE_MAX} characters")
        student_uuid = _as_uuid(student_id)
        deck_uuid = _as_uuid(deck_id)
        with self._sessionmaker() as session, session.begin():
            deck = self._owned_deck(session, student_uuid, deck_uuid)
            deck.title = cleaned
            self._expire_if_stale(deck, self._now())
            session.flush()
            marks = self._marks_lost_by_topic(session, student_uuid)
            return self._to_summary(
                deck,
                self._deck_counts(session, deck.id, self._now()),
                marks_lost=self._deck_marks_lost(deck, marks),
            )

    def weak_topics(
        self, student_id: uuid.UUID | str, *, subject_code: str | None = None, limit: int = 6
    ) -> list[WeakTopic]:
        """The caller's recorded weak topics, most marks lost first (ties: subject, then topic).

        ``accuracy_pct`` is ``100 * (available - lost) / available`` over the same rows, rounded
        and clamped to 0-100. Topics with no net marks lost are left out, as in deck creation.
        """
        student_uuid = _as_uuid(student_id)
        with self._sessionmaker() as session:
            stmt = (
                select(
                    Attempt.subject_code,
                    WeaknessRecord.topic,
                    func.sum(WeaknessRecord.lost_marks),
                    func.sum(WeaknessRecord.maximum_marks),
                )
                .join(Attempt, Attempt.id == WeaknessRecord.attempt_id)
                .where(WeaknessRecord.user_id == student_uuid)
                .group_by(Attempt.subject_code, WeaknessRecord.topic)
            )
            if subject_code is not None:
                stmt = stmt.where(Attempt.subject_code == subject_code)
            rows = session.execute(stmt).all()
        topics: list[WeakTopic] = []
        for subject, topic, lost, available in rows:
            lost_i, available_i = int(lost or 0), int(available or 0)
            if lost_i <= 0:
                continue
            pct = round(100 * (available_i - lost_i) / available_i) if available_i else 0
            topics.append(WeakTopic(subject, topic, lost_i, max(0, min(100, pct))))
        topics.sort(key=lambda t: (-t.marks_lost, t.subject_code, t.topic))
        return topics[:limit]

    def _due_scope(
        self,
        session: Session,
        student_uuid: uuid.UUID,
        subject_code: str | None,
        deck_id: uuid.UUID | str | None,
    ) -> list[sa.ColumnElement[bool]]:
        clauses: list[sa.ColumnElement[bool]] = [FlashcardDeck.user_id == student_uuid]
        if subject_code is not None:
            clauses.append(FlashcardDeck.subject_code == subject_code)
        if deck_id is not None:
            deck = self._owned_deck(session, student_uuid, _as_uuid(deck_id))
            clauses.append(FlashcardDeck.id == deck.id)
        return clauses

    def list_due_cards(
        self,
        student_id: uuid.UUID | str,
        *,
        subject_code: str | None = None,
        deck_id: uuid.UUID | str | None = None,
        limit: int | None = None,
    ) -> list[CardView]:
        """Every card owned by ``student_id`` due at or before now, soonest first.

        An empty list is a real state ("nothing due today", S-22). ``deck_id`` narrows to one
        deck the caller owns (another student's deck raises, it is never silently empty).
        """
        student_uuid = _as_uuid(student_id)
        moment = self._now()
        with self._sessionmaker() as session:
            scope = self._due_scope(session, student_uuid, subject_code, deck_id)
            stmt = (
                select(Flashcard)
                .join(FlashcardDeck, FlashcardDeck.id == Flashcard.deck_id)
                .where(*scope, Flashcard.due_at <= moment)
                .order_by(Flashcard.due_at)
            )
            if limit is not None:
                stmt = stmt.limit(limit)
            return [self._to_card_view(c, moment) for c in session.scalars(stmt).all()]

    def due_session(
        self,
        student_id: uuid.UUID | str,
        *,
        subject_code: str | None = None,
        deck_id: uuid.UUID | str | None = None,
        limit: int | None = None,
    ) -> DueSession:
        """A review session: due cards, the true due total, the next due time and the forecast.

        ``total_due`` ignores ``limit`` (spec §1.4). ``next_due_at`` is the earliest future due
        time, ``None`` when the student has no cards or all are already due. ``upcoming`` lists
        the due times of cards coming due within :data:`UPCOMING_WINDOW` so the done screen can
        say what comes back when without inventing it.
        """
        student_uuid = _as_uuid(student_id)
        moment = self._now()
        cards = self.list_due_cards(
            student_id, subject_code=subject_code, deck_id=deck_id, limit=limit
        )
        with self._sessionmaker() as session:
            scope = self._due_scope(session, student_uuid, subject_code, deck_id)
            total_due = session.scalar(
                select(func.count())
                .select_from(Flashcard)
                .join(FlashcardDeck, FlashcardDeck.id == Flashcard.deck_id)
                .where(*scope, Flashcard.due_at <= moment)
            )
            next_due_at = session.scalar(
                select(func.min(Flashcard.due_at))
                .select_from(Flashcard)
                .join(FlashcardDeck, FlashcardDeck.id == Flashcard.deck_id)
                .where(*scope, Flashcard.due_at > moment)
            )
            upcoming = list(
                session.scalars(
                    select(Flashcard.due_at)
                    .join(FlashcardDeck, FlashcardDeck.id == Flashcard.deck_id)
                    .where(
                        *scope,
                        Flashcard.due_at > moment,
                        Flashcard.due_at <= moment + UPCOMING_WINDOW,
                    )
                    .order_by(Flashcard.due_at)
                    .limit(UPCOMING_CAP)
                ).all()
            )
        return DueSession(
            cards=cards,
            total_due=int(total_due or 0),
            next_due_at=next_due_at,
            upcoming=upcoming,
            again_delay_minutes=int(AGAIN_REVIEW_DELAY.total_seconds() // 60),
        )

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
        client_review_id: uuid.UUID | None = None,
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
            client_review_id: Optional idempotency key, minted once per rating by the client.
                When this student already recorded a review under the key, that review is
                replayed (same ``review_id``, same before/after intervals) and the card is
                neither rescheduled nor logged again. ``None`` records a new review every call.

        Raises:
            FlashcardNotFoundError: no card exists with ``card_id`` (404).
            FlashcardOwnershipError: it exists but is not the caller's (403).
            FlashcardValidationError: the key was already used for a different card.
        """
        student_uuid = _as_uuid(student_id)
        card_uuid = _as_uuid(card_id)
        try:
            return self._record_review_once(student_uuid, card_uuid, grade, now, client_review_id)
        except IntegrityError:
            # Two requests with the same key raced past the replay check; the unique
            # constraint let one win. The loser replays the winner's row.
            if client_review_id is None:
                raise
            return self._record_review_once(student_uuid, card_uuid, grade, now, client_review_id)

    def _record_review_once(
        self,
        student_uuid: uuid.UUID,
        card_uuid: uuid.UUID,
        grade: ReviewGrade,
        now: datetime | None,
        client_review_id: uuid.UUID | None,
    ) -> ReviewOutcome:
        moment = now if now is not None else self._now()
        core_grade = CoreReviewGrade(grade.value)
        with self._sessionmaker() as session, session.begin():
            card = self._owned_card(session, student_uuid, card_uuid)
            if client_review_id is not None:
                prior = session.scalars(
                    select(FlashcardReview).where(
                        FlashcardReview.user_id == student_uuid,
                        FlashcardReview.client_review_id == client_review_id,
                    )
                ).first()
                if prior is not None:
                    return self._replay_review(session, card, prior)
            # Ownership of ``card`` is already proven by ``_owned_card`` (it
            # loads and checks the same deck internally); this is a second,
            # cheap fetch purely for ``subject_code`` and never re-validates
            # ownership, so it can never diverge from what ``_owned_card``
            # already decided.
            deck = session.get(FlashcardDeck, card.deck_id)
            if deck is None:
                # Unreachable in practice: _owned_card above already loaded
                # and checked this exact deck. A real runtime check rather
                # than an assert (S101), mirroring generate_deck's precedent
                # in this module.
                raise FlashcardNotFoundError(f"Unknown deck for card: {card_uuid}")
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
                client_review_id=client_review_id,
            )
            session.add(review_row)
            session.flush()

            return ReviewOutcome(
                card=self._to_card_view(card),
                review_id=review_row.id,
                grade=grade,
                interval_before_days=schedule_before.interval_days,
                interval_after_days=schedule_after.interval_days,
                subject_code=deck.subject_code,
            )

    def _replay_review(
        self, session: Session, card: Flashcard, prior: FlashcardReview
    ) -> ReviewOutcome:
        """The stored outcome of a review this student already recorded under the same key."""
        if prior.card_id != card.id:
            raise FlashcardValidationError("clientReviewId was already used for another card")
        deck = session.get(FlashcardDeck, card.deck_id)
        if deck is None:
            raise FlashcardNotFoundError(f"Unknown deck for card: {card.id}")
        return ReviewOutcome(
            card=self._to_card_view(card),
            review_id=prior.id,
            grade=prior.grade,
            interval_before_days=prior.interval_before_days,
            interval_after_days=prior.interval_after_days,
            subject_code=deck.subject_code,
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

    def _deck_counts(self, session: Session, deck_id: uuid.UUID, moment: datetime) -> _DeckCounts:
        total, due, new, known = session.execute(
            select(
                func.count(),
                func.count().filter(Flashcard.due_at <= moment),
                func.count().filter(
                    Flashcard.repetitions == 0, Flashcard.last_reviewed_at.is_(None)
                ),
                func.count().filter(Flashcard.interval_days >= KNOWN_INTERVAL_DAYS),
            )
            .select_from(Flashcard)
            .where(Flashcard.deck_id == deck_id)
        ).one()
        total, due, new, known = int(total or 0), int(due or 0), int(new or 0), int(known or 0)
        return _DeckCounts(
            total=total,
            due=due,
            mastery=MasteryCounts(new=new, learning=max(total - new - known, 0), known=known),
        )

    def _weak_topic_totals(
        self, session: Session, student_uuid: uuid.UUID, subject_code: str
    ) -> dict[str, int]:
        """Net lost marks per topic for ``subject_code``, keeping only topics with marks lost.

        Reads ``WeaknessRecord`` rows verbatim (D4.10 §2), as P4.5's practice service does.
        """
        rows = session.execute(
            select(WeaknessRecord.topic, WeaknessRecord.lost_marks)
            .join(Attempt, Attempt.id == WeaknessRecord.attempt_id)
            .where(WeaknessRecord.user_id == student_uuid, Attempt.subject_code == subject_code)
        ).all()
        totals: dict[str, int] = {}
        for topic, lost in rows:
            totals[topic] = totals.get(topic, 0) + lost
        return {t: lost for t, lost in totals.items() if lost > 0}

    def _marks_lost_by_topic(
        self, session: Session, student_uuid: uuid.UUID
    ) -> dict[tuple[str, str], int]:
        rows = session.execute(
            select(Attempt.subject_code, WeaknessRecord.topic, func.sum(WeaknessRecord.lost_marks))
            .join(Attempt, Attempt.id == WeaknessRecord.attempt_id)
            .where(WeaknessRecord.user_id == student_uuid)
            .group_by(Attempt.subject_code, WeaknessRecord.topic)
        ).all()
        return {(subject, topic): int(lost or 0) for subject, topic, lost in rows}

    @staticmethod
    def _deck_marks_lost(deck: FlashcardDeck, marks: dict[tuple[str, str], int]) -> int | None:
        if deck.origin != DeckOrigin.weakness or deck.topic is None:
            return None
        lost = marks.get((deck.subject_code, deck.topic), 0)
        return lost if lost > 0 else None

    def _to_summary(
        self, deck: FlashcardDeck, counts: _DeckCounts, *, marks_lost: int | None
    ) -> DeckSummary:
        return DeckSummary(
            id=deck.id,
            subject_code=deck.subject_code,
            topic=deck.topic,
            title=deck.title,
            description=deck.description,
            origin=deck.origin,
            card_count=counts.total,
            due_count=counts.due,
            created_at=deck.created_at,
            mastery=counts.mastery,
            marks_lost=marks_lost,
            generation_status=DeckGenerationStatus(deck.generation_status),
            requested_count=deck.requested_count,
        )

    def _to_card_view(self, card: Flashcard, moment: datetime | None = None) -> CardView:
        schedule = CardSchedule(
            repetitions=card.repetitions,
            ease_factor=card.ease_factor,
            interval_days=card.interval_days,
            lapses=card.lapses,
            due_at=card.due_at,
            last_reviewed_at=card.last_reviewed_at,
        )
        at = moment if moment is not None else self._now()
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
            next_interval_days={
                grade.value: apply_review(schedule, grade, now=at).interval_days
                for grade in CoreReviewGrade
            },
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
    "GENERATION_STALE_AFTER",
    "KNOWN_INTERVAL_DAYS",
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
    "GenerationState",
    "MasteryCounts",
    "ReviewOutcome",
    "WeakTopic",
]
