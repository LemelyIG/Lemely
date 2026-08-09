"""Flashcard endpoints (``/api/student/flashcards/*``, P4.6 chunk C).

A new router file, mirroring ``lemely.web.routers.practice`` exactly: thin,
its own DTOs, and no growth of ``student.py``.

**Student-only and owner-scoped on every read and write.** The router-level
``require_role(Role.student)`` dependency keeps teachers and parents out
entirely — a flashcard deck is a private study artefact with no teacher-
visibility story in this phase, so there is no read-only teacher variant to
add later by accident.

**Another student's deck id is a 404 here, not a 403.** This is a deliberate
divergence from ``practice.py``, which returns 403 for someone else's
practice assignment, and the service keeps the two cases distinct
(:class:`~lemely.db.flashcard_repo.FlashcardNotFoundError` vs
:class:`~lemely.db.flashcard_repo.FlashcardOwnershipError`) so tests can tell
them apart. The reason for collapsing them at the boundary: a practice
assignment is a quiz-shaped object a teacher may also legitimately hold a
reference to, whereas a deck exists only for its one owner. A 403 there would
answer "does this id exist?" for anyone willing to enumerate — an existence
oracle over another student's private study material, bought for nothing. The
403 case is not silently lost: it is still raised, still typed, and still
tested; only its HTTP rendering is flattened.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from lemely.db.flashcard_repo import (
    FlashcardError,
    FlashcardGenerationUnavailableError,
    FlashcardNotFoundError,
    FlashcardOwnershipError,
    FlashcardService,
    FlashcardUnavailableError,
)
from lemely.db.models.enums import Role
from lemely.db.models.flashcards import DeckOrigin, ReviewGrade
from lemely.web.deps import AuthContext, get_flashcard_service, require_role
from lemely.web.schemas_flashcards import (
    AddCardRequestDTO,
    CardDTO,
    CreateDeckRequestDTO,
    DeckDetailDTO,
    DeckSummaryDTO,
    DueSessionDTO,
    EditCardRequestDTO,
    GenerateDeckRequestDTO,
    GenerateDeckResponseDTO,
    ReviewCardRequestDTO,
    ReviewResultDTO,
)

if TYPE_CHECKING:
    from lemely.db.flashcard_repo import (
        CardView,
        DeckDetail,
        DeckSummary,
        DueSession,
        GeneratedDeckResult,
        ReviewOutcome,
    )

router = APIRouter(
    prefix="/api/student/flashcards", dependencies=[Depends(require_role(Role.student))]
)


def _raise_for(exc: FlashcardError) -> NoReturn:
    """Map a :class:`FlashcardError` subclass to the matching :class:`HTTPException`.

    Both :class:`FlashcardNotFoundError` and :class:`FlashcardOwnershipError`
    become 404 — see this module's docstring for why the ownership case is
    not rendered as 403.
    """
    if isinstance(exc, FlashcardNotFoundError | FlashcardOwnershipError):
        raise HTTPException(status_code=404, detail="No such deck or card") from exc
    if isinstance(exc, FlashcardUnavailableError):
        raise HTTPException(status_code=409, detail={"reason": str(exc.reason)}) from exc
    if isinstance(exc, FlashcardGenerationUnavailableError):
        raise HTTPException(
            status_code=503, detail="Flashcard generation is not configured"
        ) from exc
    raise HTTPException(status_code=422, detail=str(exc)) from exc


def _parse_origin(origin: str) -> DeckOrigin:
    try:
        return DeckOrigin(origin)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Unknown deck origin: {origin!r}") from exc


def _parse_grade(grade: str) -> ReviewGrade:
    try:
        return ReviewGrade(grade)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Unknown review grade: {grade!r}") from exc


def _card_to_dto(card: CardView) -> CardDTO:
    return CardDTO(
        id=str(card.id),
        front=card.front,
        back=card.back,
        position=card.position,
        source=card.source.value,
        sourceQuestionId=card.source_question_id,
        repetitions=card.repetitions,
        easeFactor=card.ease_factor,
        intervalDays=card.interval_days,
        lapses=card.lapses,
        dueAt=card.due_at.isoformat(),
        lastReviewedAt=card.last_reviewed_at.isoformat() if card.last_reviewed_at else None,
    )


def _summary_to_dto(deck: DeckSummary) -> DeckSummaryDTO:
    return DeckSummaryDTO(
        id=str(deck.id),
        subjectCode=deck.subject_code,
        topic=deck.topic,
        title=deck.title,
        description=deck.description,
        origin=deck.origin.value,
        cardCount=deck.card_count,
        dueCount=deck.due_count,
        createdAt=deck.created_at.isoformat(),
    )


def _detail_to_dto(deck: DeckDetail) -> DeckDetailDTO:
    return DeckDetailDTO(
        id=str(deck.id),
        subjectCode=deck.subject_code,
        topic=deck.topic,
        title=deck.title,
        description=deck.description,
        origin=deck.origin.value,
        cards=[_card_to_dto(c) for c in deck.cards],
    )


def _generated_to_dto(result: GeneratedDeckResult) -> GenerateDeckResponseDTO:
    return GenerateDeckResponseDTO(
        deck=_summary_to_dto(result.deck),
        requestedCount=result.requested_count,
        generatedCount=result.generated_count,
    )


def _session_to_dto(session: DueSession) -> DueSessionDTO:
    return DueSessionDTO(
        cards=[_card_to_dto(c) for c in session.cards],
        totalDue=session.total_due,
        nextDueAt=session.next_due_at.isoformat() if session.next_due_at else None,
    )


def _review_to_dto(outcome: ReviewOutcome) -> ReviewResultDTO:
    return ReviewResultDTO(
        card=_card_to_dto(outcome.card),
        reviewId=str(outcome.review_id),
        grade=outcome.grade.value,
        intervalBeforeDays=outcome.interval_before_days,
        intervalAfterDays=outcome.interval_after_days,
    )


# -- Decks -------------------------------------------------------------------


@router.get("/decks", response_model=list[DeckSummaryDTO])
def list_decks(
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    service: Annotated[FlashcardService, Depends(get_flashcard_service)],
    subject_code: str | None = None,
) -> list[DeckSummaryDTO]:
    """S-22: the caller's own decks, most recently created first.

    Never anyone else's — the query is owner-scoped in the service, not
    filtered here.
    """
    return [_summary_to_dto(d) for d in service.list_decks(auth.user_id, subject_code=subject_code)]


@router.post("/decks", response_model=DeckSummaryDTO, status_code=201)
def create_deck(
    body: CreateDeckRequestDTO,
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    service: Annotated[FlashcardService, Depends(get_flashcard_service)],
) -> DeckSummaryDTO:
    """Create an empty deck — manual, topic-targeted, or weakness-targeted.

    409 with ``{"reason": "no_weaknesses"}`` when ``origin="weakness"`` and
    the caller has no recorded weaknesses yet: an honest refusal, not a
    silently untargeted empty deck (the same reason vocabulary P4.5 uses).
    """
    try:
        deck = service.create_deck(
            auth.user_id,
            subject_code=body.subjectCode,
            title=body.title,
            description=body.description,
            origin=_parse_origin(body.origin),
            topic=body.topic,
        )
    except FlashcardError as exc:
        _raise_for(exc)
    return _summary_to_dto(deck)


@router.post("/decks/generate", response_model=GenerateDeckResponseDTO, status_code=201)
def generate_deck(
    body: GenerateDeckRequestDTO,
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    service: Annotated[FlashcardService, Depends(get_flashcard_service)],
) -> GenerateDeckResponseDTO:
    """Generate an AI deck for a topic, or for the caller's weakest topic.

    Every card lands ``source="ai"`` and stays that way. The response
    reports the true ``generatedCount`` beside ``requestedCount``; a short
    response is not padded and must not be rendered as if it were complete.

    Declared before ``/decks/{deck_id}`` so the literal path wins the match.
    """
    try:
        result = service.generate_deck(
            auth.user_id,
            subject_code=body.subjectCode,
            origin=_parse_origin(body.origin),
            count=body.count,
            topic=body.topic,
            title=body.title,
        )
    except FlashcardError as exc:
        _raise_for(exc)
    return _generated_to_dto(result)


@router.get("/decks/{deck_id}", response_model=DeckDetailDTO)
def get_deck(
    deck_id: str,
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    service: Annotated[FlashcardService, Depends(get_flashcard_service)],
) -> DeckDetailDTO:
    """One deck and all of its cards. Another student's deck id is a 404."""
    try:
        deck = service.get_deck(auth.user_id, deck_id)
    except FlashcardError as exc:
        _raise_for(exc)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _detail_to_dto(deck)


@router.delete("/decks/{deck_id}", status_code=204)
def delete_deck(
    deck_id: str,
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    service: Annotated[FlashcardService, Depends(get_flashcard_service)],
) -> Response:
    """Delete one of the caller's own decks, and every card in it."""
    try:
        service.delete_deck(auth.user_id, deck_id)
    except FlashcardError as exc:
        _raise_for(exc)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return Response(status_code=204)


# -- Cards -------------------------------------------------------------------


@router.post("/decks/{deck_id}/cards", response_model=CardDTO, status_code=201)
def add_card(
    deck_id: str,
    body: AddCardRequestDTO,
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    service: Annotated[FlashcardService, Depends(get_flashcard_service)],
) -> CardDTO:
    """Add a card the student wrote themselves — always ``source="manual"``."""
    try:
        card = service.add_card(auth.user_id, deck_id, front=body.front, back=body.back)
    except FlashcardError as exc:
        _raise_for(exc)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _card_to_dto(card)


@router.patch("/cards/{card_id}", response_model=CardDTO)
def edit_card(
    card_id: str,
    body: EditCardRequestDTO,
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    service: Annotated[FlashcardService, Depends(get_flashcard_service)],
) -> CardDTO:
    """Edit a card's wording.

    Rewording an AI card is legitimate; relabelling it as the student's own
    is not, and there is no field on the request body that could ask for it.
    """
    try:
        card = service.edit_card(auth.user_id, card_id, front=body.front, back=body.back)
    except FlashcardError as exc:
        _raise_for(exc)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _card_to_dto(card)


@router.delete("/cards/{card_id}", status_code=204)
def delete_card(
    card_id: str,
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    service: Annotated[FlashcardService, Depends(get_flashcard_service)],
) -> Response:
    """Delete one of the caller's own cards."""
    try:
        service.delete_card(auth.user_id, card_id)
    except FlashcardError as exc:
        _raise_for(exc)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return Response(status_code=204)


# -- Review ------------------------------------------------------------------


@router.get("/due", response_model=DueSessionDTO)
def due_session(
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    service: Annotated[FlashcardService, Depends(get_flashcard_service)],
    subject_code: str | None = None,
    limit: Annotated[int | None, Query(ge=1)] = None,
) -> DueSessionDTO:
    """S-22/S-23: the cards due now, the whole backlog size, and the next due time.

    An empty ``cards`` list is a real, successful state — S-22's "nothing due
    today" — and it carries ``nextDueAt`` so the screen can say *when* rather
    than rendering a bare void.

    ``limit`` is constrained ``ge=1`` at the boundary: it reaches SQL as a
    bare ``LIMIT``, and Postgres rejects a negative one with an error, so an
    unguarded ``?limit=-1`` is a 500 for what is plainly a malformed request.
    """
    return _session_to_dto(
        service.due_session(auth.user_id, subject_code=subject_code, limit=limit)
    )


@router.post("/cards/{card_id}/review", response_model=ReviewResultDTO)
def review_card(
    card_id: str,
    body: ReviewCardRequestDTO,
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    service: Annotated[FlashcardService, Depends(get_flashcard_service)],
) -> ReviewResultDTO:
    """Grade one card and reschedule it through the SM-2 scheduler.

    The response returns the interval before and after so the effect of the
    grade is visible rather than something the student has to take on trust.
    """
    try:
        outcome = service.record_review(auth.user_id, card_id, _parse_grade(body.grade))
    except FlashcardError as exc:
        _raise_for(exc)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _review_to_dto(outcome)


__all__ = ["router"]
