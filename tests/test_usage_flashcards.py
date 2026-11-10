"""Metering on AI flashcard decks (Task 12): the count is the input, a deck that failed or
came back empty charges nothing, and a seat pays only for a weakness deck (its topic is
server-picked); every topic deck is billed to the student's own allowance and credits."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING, cast

import pytest

from lemely.core.flashcards import GeneratedFlashcard, GeneratedFlashcardDeck
from lemely.core.metered_actions import MeteredAction
from lemely.db.flashcard_repo import FlashcardService
from lemely.db.models.enums import Role
from lemely.db.models.usage import UsageJobStatus
from lemely.io.llm.cost_meter import record_llm_cost
from lemely.web.usage import get_usage_meter
from tests import test_web_flashcards as _flash
from tests.usage_helpers import (
    enforcing_meter,
    give,
    jobs_for,
    seat,
    seat_grant,
    seed_catalogue,
    seed_user,
)

client = _flash.client
pg_sessionmaker = _flash.pg_sessionmaker

if TYPE_CHECKING:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session, sessionmaker

_URL = "/api/student/flashcards/decks/generate"
_BODY = {"subjectCode": "0625", "origin": "topic", "topic": "4.3 Circuits", "count": 2}
_CARDS = [
    GeneratedFlashcard(front="What is current?", back="Rate of flow of charge"),
    GeneratedFlashcard(front="Unit of current?", back="Ampere"),
]


def _wire(
    client: TestClient,
    sm: sessionmaker[Session],
    *,
    cards: list[GeneratedFlashcard] | None = None,
    fail_after_spend: bool = False,
) -> uuid.UUID:
    seed_catalogue(sm)
    generator = _flash._mock_generator(_CARDS if cards is None else cards, topic="4.3 Circuits")
    deck = generator.generate.return_value

    def _costly(*_a: object, **_k: object) -> GeneratedFlashcardDeck:
        # The provider spend lands in the job's cost scope, as GeminiClient would record it.
        record_llm_cost(Decimal("0.004"))
        if fail_after_spend:
            raise RuntimeError("generator crashed after spending")
        return deck  # type: ignore[no-any-return]

    generator.generate.side_effect = _costly
    _flash._use_service(client, FlashcardService(sm, generator, now=lambda: _flash._FIXED_NOW))
    cast("FastAPI", client.app).dependency_overrides[get_usage_meter] = lambda: enforcing_meter(sm)
    student = _flash._seed_user(sm)
    _flash._auth_as(client, student)
    return student


def test_generation_without_balance_is_402(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    student = _wire(client, pg_sessionmaker)
    resp = client.post(_URL, json=_BODY)
    assert resp.status_code == 402
    # base 2-4 + 2 cards x 1-2 = 4-8
    assert resp.json() == {"error": "usage_blocked", "reason": "no_active_plan", "estimate": [4, 8]}
    assert jobs_for(pg_sessionmaker, student) == []


def test_generation_settles_the_cost(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    student = _wire(client, pg_sessionmaker)
    give(pg_sessionmaker, student, units=100)
    assert client.post(_URL, json=_BODY).status_code == 201
    (job,) = jobs_for(pg_sessionmaker, student)
    assert (job.action, job.status, job.charged) == (
        "generate_flashcards",
        UsageJobStatus.settled,
        4,
    )


def test_the_requested_count_sets_the_estimate_up_to_the_clamp(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    _wire(client, pg_sessionmaker)
    resp = client.post(_URL, json={**_BODY, "count": 50})
    assert resp.status_code == 402
    # base 2-4 + 50 cards x 1-2 = 52-104
    assert resp.json()["estimate"] == [52, 104]


def test_a_count_over_the_bound_never_reaches_the_meter(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    student = _wire(client, pg_sessionmaker)
    give(pg_sessionmaker, student, units=10_000)
    assert client.post(_URL, json={**_BODY, "count": 51}).status_code == 422
    assert jobs_for(pg_sessionmaker, student) == []


def test_a_refused_deck_charges_nothing(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    student = _wire(client, pg_sessionmaker)
    give(pg_sessionmaker, student, units=100)
    # origin=weakness with no recorded weaknesses is the service's honest 409.
    body = {"subjectCode": "0625", "origin": "weakness", "count": 2}
    assert client.post(_URL, json=body).status_code == 409
    (job,) = jobs_for(pg_sessionmaker, student)
    assert (job.status, job.charged) == (UsageJobStatus.released, 0)


def test_an_empty_generation_charges_nothing(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    """The model ran and spent money but produced no card: the job failed without raising."""
    student = _wire(client, pg_sessionmaker, cards=[])
    give(pg_sessionmaker, student, units=100)
    resp = client.post(_URL, json=_BODY)
    assert resp.status_code == 201
    assert resp.json()["generatedCount"] == 0
    (job,) = jobs_for(pg_sessionmaker, student)
    assert (job.status, job.charged) == (UsageJobStatus.released, 0)


def _seated(sm: sessionmaker[Session], student: uuid.UUID, *, seat_units: int = 100) -> uuid.UUID:
    """A 0625 seat with flashcards in scope and its granted allowance."""
    member = seat(
        sm,
        teacher=seed_user(sm, Role.teacher),
        student=student,
        subjects=["0625"],
        actions=[MeteredAction.GENERATE_FLASHCARDS],
    )
    seat_grant(sm, student=student, member_id=member, units=seat_units)
    return member


_WEAKNESS_BODY = {"subjectCode": "0625", "origin": "weakness", "count": 2}


def test_a_weakness_deck_is_seat_paid(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    sm = pg_sessionmaker
    student = _wire(client, sm)
    member = _seated(sm, student)
    _flash._seed_weakness(sm, student, topic="4.3 Circuits")
    assert client.post(_URL, json=_WEAKNESS_BODY).status_code == 201
    (job,) = jobs_for(sm, student)
    assert (job.teacher_member_id, job.status, job.charged) == (member, UsageJobStatus.settled, 4)


@pytest.mark.parametrize(
    "topic",
    [
        "4.3 Circuits",  # a real syllabus topic of the seat's own subject
        "4.3 circuits",
        "The history of the Roman empire",
        "Quadratic equations",  # another subject's topic
    ],
)
def test_a_topic_deck_is_self_paid_even_on_a_seated_subject(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], topic: str
) -> None:
    sm = pg_sessionmaker
    student = _wire(client, sm)
    _seated(sm, student)
    give(sm, student, units=100)
    resp = client.post(_URL, json={**_BODY, "topic": topic})
    assert resp.status_code == 201, resp.text
    (job,) = jobs_for(sm, student)
    # The deck is allowed and stores the requested subject, but no seat paid for it.
    assert (job.teacher_member_id, job.status, job.charged) == (None, UsageJobStatus.settled, 4)
    assert resp.json()["deck"]["subjectCode"] == "0625"


def test_a_topic_deck_without_own_balance_is_402_and_never_seat_paid(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    sm = pg_sessionmaker
    student = _wire(client, sm)
    _seated(sm, student)
    resp = client.post(_URL, json=_BODY)
    assert resp.status_code == 402
    assert resp.json() == {"error": "usage_blocked", "reason": "no_active_plan", "estimate": [4, 8]}
    assert jobs_for(sm, student) == []
    # The same seat does pay once the deck is a weakness deck.
    _flash._seed_weakness(sm, student, topic="4.3 Circuits")
    assert client.post(_URL, json=_WEAKNESS_BODY).status_code == 201


def test_a_seat_for_another_subject_does_not_pay_a_weakness_deck(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    sm = pg_sessionmaker
    student = _wire(client, sm)
    member = seat(
        sm,
        teacher=seed_user(sm, Role.teacher),
        student=student,
        subjects=["0580"],
        actions=[MeteredAction.GENERATE_FLASHCARDS],
    )
    seat_grant(sm, student=student, member_id=member, units=100)
    _flash._seed_weakness(sm, student, topic="4.3 Circuits")
    assert client.post(_URL, json=_WEAKNESS_BODY).status_code == 402
    give(sm, student, units=100)
    assert client.post(_URL, json=_WEAKNESS_BODY).status_code == 201
    (job,) = jobs_for(sm, student)
    assert job.teacher_member_id is None


def test_a_generator_that_raises_after_spending_releases_and_charges_nothing(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    sm = pg_sessionmaker
    student = _wire(client, sm, fail_after_spend=True)
    give(sm, student, units=100)
    with pytest.raises(RuntimeError, match="crashed after spending"):
        client.post(_URL, json=_BODY)
    (job,) = jobs_for(sm, student)
    assert (job.status, job.charged) == (UsageJobStatus.released, 0)
