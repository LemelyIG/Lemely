"""API DTOs for the flashcard endpoints (``/api/student/flashcards/*``, P4.6 chunk C).

Field names are camelCase to match the frontend contract, mirroring
``schemas_practice.py``/``schemas_placement.py``. Converters live in
``lemely.web.routers.flashcards``.

**``source`` is on the wire on purpose.** :class:`CardDTO` carries the card's
``source`` (``"manual"`` / ``"ai"``) on every read, because the P4.6 honesty
rule that an AI-written card stays distinguishable from a student's own card
for its whole life is worth nothing if the surface that renders the card
cannot tell which it is. There is deliberately **no ``source`` field on
:class:`EditCardRequestDTO`** — the API offers no way to ask for a relabel,
mirroring the absent parameter on
:meth:`~lemely.db.flashcard_repo.FlashcardService.edit_card`.
"""

from __future__ import annotations

from pydantic import Field

from lemely.web.schemas import ApiModel


class CreateDeckRequestDTO(ApiModel):
    """Body for ``POST /api/student/flashcards/decks``.

    ``origin`` is ``"manual"``, ``"topic"`` or ``"weakness"``. ``topic`` is
    required for ``"topic"``, must be omitted for ``"weakness"`` (the server
    resolves the student's own weakest topic and rejects a caller-supplied
    one rather than silently ignoring it), and is optional for ``"manual"``.
    """

    subjectCode: str
    title: str
    description: str | None = None
    origin: str = "manual"
    topic: str | None = None


class GenerateDeckRequestDTO(ApiModel):
    """Body for ``POST /api/student/flashcards/decks/generate``.

    ``origin`` must be ``"topic"`` or ``"weakness"`` — a manual deck has no
    AI content to generate for, and asking for one is a 422 rather than a
    quietly empty deck.

    ``count`` is bounded on the wire because it is the size of a **billed**
    Gemini request (MISSION §8's hard $8 ceiling) and nothing downstream
    caps it: the service passes it straight to
    :meth:`~lemely.io.flashcard_generation.FlashcardGenerator.generate`. The
    ceiling is a deck-sized 50, not a spend calculation — the point is that
    an unbounded caller-supplied number can't reach the model at all.
    """

    subjectCode: str
    origin: str
    count: int = Field(ge=1, le=50)
    topic: str | None = None
    title: str | None = None


class AddCardRequestDTO(ApiModel):
    """Body for ``POST /api/student/flashcards/decks/{deck_id}/cards``.

    No ``source`` field: a card created through this route is always the
    student's own (``"manual"``), which is a property of the route, not a
    claim the caller gets to make.
    """

    front: str
    back: str


class EditCardRequestDTO(ApiModel):
    """Body for ``PATCH /api/student/flashcards/cards/{card_id}``.

    Both fields are optional — an omitted one is left untouched. There is no
    ``source`` field, on purpose (see the module docstring).
    """

    front: str | None = None
    back: str | None = None


class ReviewCardRequestDTO(ApiModel):
    """Body for ``POST /api/student/flashcards/cards/{card_id}/review``.

    ``grade`` is one of ``"again"``, ``"hard"``, ``"good"``, ``"easy"`` — the
    four-button vocabulary chunk A's scheduler maps onto SM-2 qualities
    0/3/4/5 (no invented quality 1 or 2).
    """

    grade: str


class CardDTO(ApiModel):
    """One flashcard with its full SM-2 schedule state.

    ``source`` distinguishes an AI-written card from the student's own for
    the card's whole life — see the module docstring.
    """

    id: str
    front: str
    back: str
    position: int
    source: str
    sourceQuestionId: str | None
    repetitions: int
    easeFactor: float
    intervalDays: int
    lapses: int
    dueAt: str
    lastReviewedAt: str | None


class DeckSummaryDTO(ApiModel):
    """One deck's list-view row (S-22).

    ``origin`` tells the screen whether this deck was hand-made, picked by
    topic, or generated against a recorded weakness; ``topic`` is the P4.2
    ``"<code> <name>"`` syllabus label the deck targets, and is never
    back-filled with a guess when a manual deck has none.
    """

    id: str
    subjectCode: str
    topic: str | None
    title: str
    description: str | None
    origin: str
    cardCount: int
    dueCount: int
    createdAt: str


class DeckDetailDTO(ApiModel):
    """A deck plus every one of its cards, in position order."""

    id: str
    subjectCode: str
    topic: str | None
    title: str
    description: str | None
    origin: str
    cards: list[CardDTO] = Field(default_factory=list)


class GenerateDeckResponseDTO(ApiModel):
    """201 response for a generated deck.

    ``generatedCount`` is the real, persisted number of cards and may be less
    than ``requestedCount`` — the model is free to return fewer and nothing
    pads the difference (spec §1.4). The frontend must render the true
    number, not the requested one.
    """

    deck: DeckSummaryDTO
    requestedCount: int
    generatedCount: int


class DueSessionDTO(ApiModel):
    """S-22/S-23's review session.

    An empty ``cards`` list is a real state, not an error: ``nextDueAt``
    carries *when* the next card comes due so the screen can say that instead
    of just "nothing". ``totalDue`` is the whole backlog regardless of any
    ``limit`` applied to ``cards``.
    """

    cards: list[CardDTO] = Field(default_factory=list)
    totalDue: int
    nextDueAt: str | None


class ReviewResultDTO(ApiModel):
    """The outcome of grading one card — the new schedule, plus what changed.

    ``intervalBeforeDays``/``intervalAfterDays`` are both returned so the
    student (and a reviewer reading the audit log) can see the scheduler's
    effect rather than having to trust it.
    """

    card: CardDTO
    reviewId: str
    grade: str
    intervalBeforeDays: int
    intervalAfterDays: int
