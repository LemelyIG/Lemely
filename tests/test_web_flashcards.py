"""Route tests for the flashcard endpoints (``/api/student/flashcards/*``, P4.6 chunk C).

Self-contained (mirrors ``tests/test_web_practice.py``) — a throwaway
Postgres DB per test, skipped cleanly when unreachable, Gemini always a
mocked generator (never a real client; D4.3's suite-wide guard would raise).

Covers the wire payload shapes, role gating on every route, the deliberate
**404-not-403** rendering of another student's deck id (see the router
module docstring), the honest ``no_weaknesses`` refusal, the never-padded
generated count, and S-22's "nothing due today" carrying a next-due time
rather than being a bare empty list.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.core.flashcards import GeneratedFlashcard, GeneratedFlashcardDeck
from lemely.db.base import Base
from lemely.db.flashcard_repo import FlashcardService
from lemely.db.models import User
from lemely.db.models.attempts import Attempt, WeaknessRecord
from lemely.db.models.enums import AttemptOrigin, Role
from lemely.runtime.config import DatabaseSettings
from lemely.web import create_app
from lemely.web.deps import AuthContext, get_auth_context, get_flashcard_service

if TYPE_CHECKING:
    from collections.abc import Iterator

# ---------------------------------------------------------------------------
# Fixtures.
# ---------------------------------------------------------------------------

_FIXED_NOW = datetime(2026, 8, 8, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app()
    yield TestClient(app)
    app.dependency_overrides.clear()


def _server_reachable(url: str) -> bool:
    server_url = make_url(url).set(database="postgres")
    engine = create_engine(server_url)
    try:
        with engine.connect():
            return True
    except OperationalError:
        return False
    finally:
        engine.dispose()


@pytest.fixture
def pg_sessionmaker() -> Iterator[sessionmaker[Session]]:
    base_url = DatabaseSettings().url
    if not _server_reachable(base_url):
        pytest.skip("local Postgres not reachable")

    server_url = make_url(base_url).set(database="postgres")
    admin = create_engine(server_url, isolation_level="AUTOCOMMIT")
    dbname = f"lemely_test_{uuid.uuid4().hex[:12]}"
    with admin.connect() as conn:
        conn.execute(sa.text(f'CREATE DATABASE "{dbname}"'))

    engine = create_engine(make_url(base_url).set(database=dbname))
    Base.metadata.create_all(engine)
    try:
        yield sessionmaker(bind=engine, expire_on_commit=False, future=True)
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE)'))
        admin.dispose()


def _mock_generator(cards: list[GeneratedFlashcard], *, topic: str) -> MagicMock:
    generator = MagicMock()
    generator.generate.return_value = GeneratedFlashcardDeck(
        subject_code="0625", topic=topic, cards=cards
    )
    return generator


@pytest.fixture
def flashcard_service(pg_sessionmaker: sessionmaker[Session]) -> FlashcardService:
    return FlashcardService(pg_sessionmaker, now=lambda: _FIXED_NOW)


def _use_service(client: TestClient, service: FlashcardService) -> None:
    client.app.dependency_overrides[get_flashcard_service] = lambda: service  # type: ignore[union-attr]


def _auth_as(client: TestClient, user_id: uuid.UUID, role: Role = Role.student) -> None:
    client.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[union-attr]
        user_id=str(user_id), role=role.value
    )


def _seed_user(sm: sessionmaker[Session], role: Role = Role.student) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=role))
    return uid


def _seed_weakness(
    sm: sessionmaker[Session], student_id: uuid.UUID, *, topic: str, lost_marks: int = 6
) -> None:
    with sm.begin() as session:
        attempt = Attempt(
            user_id=student_id,
            subject_code="0625",
            awarded_marks=10 - lost_marks,
            maximum_marks=10,
            percentage=10.0 * (10 - lost_marks),
            recorded_at=datetime.now(UTC),
            origin=AttemptOrigin.quiz,
        )
        session.add(attempt)
        session.flush()
        session.add(
            WeaknessRecord(
                user_id=student_id,
                attempt_id=attempt.id,
                topic=topic,
                lost_marks=lost_marks,
                maximum_marks=10,
                accuracy=1.0 - lost_marks / 10,
            )
        )


# ---------------------------------------------------------------------------
# Deck CRUD over the wire.
# ---------------------------------------------------------------------------


def test_create_and_list_decks_round_trip(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    flashcard_service: FlashcardService,
) -> None:
    student = _seed_user(pg_sessionmaker)
    _use_service(client, flashcard_service)
    _auth_as(client, student)

    created = client.post(
        "/api/student/flashcards/decks",
        json={"subjectCode": "0625", "title": "Circuits", "origin": "topic", "topic": "4.3 Circ"},
    )
    assert created.status_code == 201
    body = created.json()
    assert body["subjectCode"] == "0625"
    assert body["topic"] == "4.3 Circ"
    assert body["origin"] == "topic"
    assert body["cardCount"] == 0

    listed = client.get("/api/student/flashcards/decks")
    assert listed.status_code == 200
    assert [d["id"] for d in listed.json()] == [body["id"]]


def test_topic_origin_without_a_topic_is_422(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    flashcard_service: FlashcardService,
) -> None:
    student = _seed_user(pg_sessionmaker)
    _use_service(client, flashcard_service)
    _auth_as(client, student)

    response = client.post(
        "/api/student/flashcards/decks",
        json={"subjectCode": "0625", "title": "Untargeted", "origin": "topic"},
    )
    assert response.status_code == 422


def test_unknown_origin_is_422_not_a_silently_manual_deck(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    flashcard_service: FlashcardService,
) -> None:
    student = _seed_user(pg_sessionmaker)
    _use_service(client, flashcard_service)
    _auth_as(client, student)

    response = client.post(
        "/api/student/flashcards/decks",
        json={"subjectCode": "0625", "title": "Deck", "origin": "wishful"},
    )
    assert response.status_code == 422
    assert client.get("/api/student/flashcards/decks").json() == []


def test_weakness_deck_with_no_weaknesses_is_409_with_the_reason(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    flashcard_service: FlashcardService,
) -> None:
    student = _seed_user(pg_sessionmaker)
    _use_service(client, flashcard_service)
    _auth_as(client, student)

    response = client.post(
        "/api/student/flashcards/decks",
        json={"subjectCode": "0625", "title": "Weak spots", "origin": "weakness"},
    )
    assert response.status_code == 409
    assert response.json()["detail"] == {"reason": "no_weaknesses"}
    # The refusal is real: no husk deck was left behind.
    assert client.get("/api/student/flashcards/decks").json() == []


def test_weakness_deck_records_the_topic_it_targeted(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    flashcard_service: FlashcardService,
) -> None:
    student = _seed_user(pg_sessionmaker)
    _seed_weakness(pg_sessionmaker, student, topic="1.2 Motion", lost_marks=8)
    _seed_weakness(pg_sessionmaker, student, topic="4.3 Circuits", lost_marks=2)
    _use_service(client, flashcard_service)
    _auth_as(client, student)

    response = client.post(
        "/api/student/flashcards/decks",
        json={"subjectCode": "0625", "title": "Weak spots", "origin": "weakness"},
    )
    assert response.status_code == 201
    assert response.json()["topic"] == "1.2 Motion"


def test_delete_deck_is_204_and_the_deck_is_gone(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    flashcard_service: FlashcardService,
) -> None:
    student = _seed_user(pg_sessionmaker)
    _use_service(client, flashcard_service)
    _auth_as(client, student)
    deck_id = client.post(
        "/api/student/flashcards/decks", json={"subjectCode": "0625", "title": "Doomed"}
    ).json()["id"]

    assert client.delete(f"/api/student/flashcards/decks/{deck_id}").status_code == 204
    assert client.get(f"/api/student/flashcards/decks/{deck_id}").status_code == 404


# ---------------------------------------------------------------------------
# Owner scoping and role gating.
# ---------------------------------------------------------------------------


def test_another_students_deck_is_404_not_403(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    flashcard_service: FlashcardService,
) -> None:
    owner = _seed_user(pg_sessionmaker)
    other = _seed_user(pg_sessionmaker)
    _use_service(client, flashcard_service)
    _auth_as(client, owner)
    deck_id = client.post(
        "/api/student/flashcards/decks", json={"subjectCode": "0625", "title": "Mine"}
    ).json()["id"]

    _auth_as(client, other)
    # 403 would confirm the id exists — an existence oracle over another
    # student's private material. Every verb must be indistinguishable from
    # the id simply not existing.
    unknown = uuid.uuid4()
    for method, path in (
        ("get", f"/api/student/flashcards/decks/{deck_id}"),
        ("delete", f"/api/student/flashcards/decks/{deck_id}"),
    ):
        real = getattr(client, method)(path)
        fake = getattr(client, method)(f"/api/student/flashcards/decks/{unknown}")
        assert real.status_code == 404
        assert real.json() == fake.json()

    # Inverse: the owner still gets it, so 404 was about identity, not absence.
    _auth_as(client, owner)
    assert client.get(f"/api/student/flashcards/decks/{deck_id}").status_code == 200


def test_another_students_card_cannot_be_edited_or_reviewed(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    flashcard_service: FlashcardService,
) -> None:
    owner = _seed_user(pg_sessionmaker)
    other = _seed_user(pg_sessionmaker)
    _use_service(client, flashcard_service)
    _auth_as(client, owner)
    deck_id = client.post(
        "/api/student/flashcards/decks", json={"subjectCode": "0625", "title": "Mine"}
    ).json()["id"]
    card_id = client.post(
        f"/api/student/flashcards/decks/{deck_id}/cards", json={"front": "Q", "back": "A"}
    ).json()["id"]

    _auth_as(client, other)
    assert (
        client.patch(
            f"/api/student/flashcards/cards/{card_id}", json={"front": "hijacked"}
        ).status_code
        == 404
    )
    assert client.delete(f"/api/student/flashcards/cards/{card_id}").status_code == 404
    assert (
        client.post(
            f"/api/student/flashcards/cards/{card_id}/review", json={"grade": "easy"}
        ).status_code
        == 404
    )

    # The card is untouched — a failed write must not have partially applied.
    _auth_as(client, owner)
    assert client.get(f"/api/student/flashcards/decks/{deck_id}").json()["cards"][0]["front"] == "Q"


@pytest.mark.parametrize("role", [Role.teacher, Role.parent, Role.school_admin])
def test_non_students_are_locked_out_of_every_flashcard_route(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    flashcard_service: FlashcardService,
    role: Role,
) -> None:
    user = _seed_user(pg_sessionmaker, role=role)
    _use_service(client, flashcard_service)
    _auth_as(client, user, role=role)

    assert client.get("/api/student/flashcards/decks").status_code == 403
    assert client.get("/api/student/flashcards/due").status_code == 403
    assert (
        client.post(
            "/api/student/flashcards/decks", json={"subjectCode": "0625", "title": "T"}
        ).status_code
        == 403
    )


# ---------------------------------------------------------------------------
# AI generation over the wire.
# ---------------------------------------------------------------------------


def test_generated_cards_are_marked_ai_on_the_wire(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student = _seed_user(pg_sessionmaker)
    generator = _mock_generator(
        [
            GeneratedFlashcard(front="What is current?", back="Rate of flow of charge"),
            GeneratedFlashcard(front="Unit of current?", back="Ampere"),
        ],
        topic="4.3 Circuits",
    )
    service = FlashcardService(pg_sessionmaker, generator, now=lambda: _FIXED_NOW)
    _use_service(client, service)
    _auth_as(client, student)

    response = client.post(
        "/api/student/flashcards/decks/generate",
        json={"subjectCode": "0625", "origin": "topic", "topic": "4.3 Circuits", "count": 2},
    )
    assert response.status_code == 201
    deck_id = response.json()["deck"]["id"]

    cards = client.get(f"/api/student/flashcards/decks/{deck_id}").json()["cards"]
    # The honesty rule is worthless if the surface cannot tell AI from own work.
    assert [c["source"] for c in cards] == ["ai", "ai"]


def test_a_short_generation_reports_the_true_count_never_the_requested_one(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student = _seed_user(pg_sessionmaker)
    generator = _mock_generator(
        [GeneratedFlashcard(front="Only one", back="card")], topic="4.3 Circuits"
    )
    service = FlashcardService(pg_sessionmaker, generator, now=lambda: _FIXED_NOW)
    _use_service(client, service)
    _auth_as(client, student)

    body = client.post(
        "/api/student/flashcards/decks/generate",
        json={"subjectCode": "0625", "origin": "topic", "topic": "4.3 Circuits", "count": 10},
    ).json()
    assert body["requestedCount"] == 10
    assert body["generatedCount"] == 1
    assert body["deck"]["cardCount"] == 1


def test_generating_a_manual_deck_is_refused(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student = _seed_user(pg_sessionmaker)
    service = FlashcardService(
        pg_sessionmaker, _mock_generator([], topic="x"), now=lambda: _FIXED_NOW
    )
    _use_service(client, service)
    _auth_as(client, student)

    response = client.post(
        "/api/student/flashcards/decks/generate",
        json={"subjectCode": "0625", "origin": "manual", "count": 5},
    )
    assert response.status_code == 422


def test_an_unbounded_count_never_reaches_the_billed_model(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """``count`` is the size of a billed Gemini request; the wire bounds it.

    Asserted on the *generator mock* rather than only the status code — a
    422 that still called the model would have spent real money against
    MISSION §8's $8 ceiling before rejecting the request.
    """
    student = _seed_user(pg_sessionmaker)
    generator = _mock_generator([], topic="4.3 Circuits")
    service = FlashcardService(pg_sessionmaker, generator, now=lambda: _FIXED_NOW)
    _use_service(client, service)
    _auth_as(client, student)

    body = {"subjectCode": "0625", "origin": "topic", "topic": "4.3 Circuits"}
    for bad_count in (0, -1, 10_000):
        response = client.post(
            "/api/student/flashcards/decks/generate", json={**body, "count": bad_count}
        )
        assert response.status_code == 422, bad_count
    generator.generate.assert_not_called()

    # The inverse: a count inside the bound is accepted and does reach it.
    assert (
        client.post(
            "/api/student/flashcards/decks/generate", json={**body, "count": 50}
        ).status_code
        == 201
    )
    generator.generate.assert_called_once()


def test_a_negative_due_limit_is_rejected_not_a_500(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    flashcard_service: FlashcardService,
) -> None:
    """``limit`` reaches SQL as a bare ``LIMIT``, which Postgres rejects when negative."""
    student = _seed_user(pg_sessionmaker)
    _use_service(client, flashcard_service)
    _auth_as(client, student)

    assert client.get("/api/student/flashcards/due", params={"limit": -1}).status_code == 422
    assert client.get("/api/student/flashcards/due", params={"limit": 0}).status_code == 422
    assert client.get("/api/student/flashcards/due", params={"limit": 1}).status_code == 200


def test_generation_without_a_generator_wired_is_503(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    flashcard_service: FlashcardService,
) -> None:
    student = _seed_user(pg_sessionmaker)
    _use_service(client, flashcard_service)  # constructed with no generator
    _auth_as(client, student)

    response = client.post(
        "/api/student/flashcards/decks/generate",
        json={"subjectCode": "0625", "origin": "topic", "topic": "4.3 Circuits", "count": 5},
    )
    assert response.status_code == 503


# ---------------------------------------------------------------------------
# Cards, review, and the "nothing due" state.
# ---------------------------------------------------------------------------


def test_a_hand_written_card_is_manual_and_editing_never_relabels_it(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student = _seed_user(pg_sessionmaker)
    generator = _mock_generator(
        [GeneratedFlashcard(front="AI front", back="AI back")], topic="4.3 Circuits"
    )
    service = FlashcardService(pg_sessionmaker, generator, now=lambda: _FIXED_NOW)
    _use_service(client, service)
    _auth_as(client, student)

    deck_id = client.post(
        "/api/student/flashcards/decks/generate",
        json={"subjectCode": "0625", "origin": "topic", "topic": "4.3 Circuits", "count": 1},
    ).json()["deck"]["id"]
    ai_card = client.get(f"/api/student/flashcards/decks/{deck_id}").json()["cards"][0]
    own = client.post(
        f"/api/student/flashcards/decks/{deck_id}/cards",
        json={"front": "Mine", "back": "Also mine"},
    ).json()
    assert own["source"] == "manual"

    # Asking for the relabel is rejected outright, not silently ignored:
    # `ApiModel` is `extra="forbid"`, so an unknown `source` field is a 422
    # rather than a body the server quietly drops on the floor.
    assert (
        client.patch(
            f"/api/student/flashcards/cards/{ai_card['id']}",
            json={"front": "My own phrasing", "source": "manual"},
        ).status_code
        == 422
    )

    # Rewording an AI card in the student's own words is still legitimate —
    # it just cannot change who wrote it.
    edited = client.patch(
        f"/api/student/flashcards/cards/{ai_card['id']}", json={"front": "My own phrasing"}
    )
    assert edited.status_code == 200
    assert edited.json()["front"] == "My own phrasing"
    assert edited.json()["source"] == "ai"


def test_reviewing_a_card_returns_the_interval_change_and_reschedules_it(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    flashcard_service: FlashcardService,
) -> None:
    student = _seed_user(pg_sessionmaker)
    _use_service(client, flashcard_service)
    _auth_as(client, student)
    deck_id = client.post(
        "/api/student/flashcards/decks", json={"subjectCode": "0625", "title": "Deck"}
    ).json()["id"]
    card_id = client.post(
        f"/api/student/flashcards/decks/{deck_id}/cards", json={"front": "Q", "back": "A"}
    ).json()["id"]

    result = client.post(f"/api/student/flashcards/cards/{card_id}/review", json={"grade": "good"})
    assert result.status_code == 200
    body = result.json()
    assert body["grade"] == "good"
    assert body["intervalBeforeDays"] == 0
    assert body["intervalAfterDays"] > 0
    assert body["card"]["repetitions"] == 1


def test_an_unknown_grade_is_422_and_leaves_the_card_alone(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    flashcard_service: FlashcardService,
) -> None:
    student = _seed_user(pg_sessionmaker)
    _use_service(client, flashcard_service)
    _auth_as(client, student)
    deck_id = client.post(
        "/api/student/flashcards/decks", json={"subjectCode": "0625", "title": "Deck"}
    ).json()["id"]
    card_id = client.post(
        f"/api/student/flashcards/decks/{deck_id}/cards", json={"front": "Q", "back": "A"}
    ).json()["id"]

    # "perfect" is not one of the four buttons; inventing a quality for it
    # would silently reschedule the card off a value the student never gave.
    assert (
        client.post(
            f"/api/student/flashcards/cards/{card_id}/review", json={"grade": "perfect"}
        ).status_code
        == 422
    )
    assert (
        client.get(f"/api/student/flashcards/decks/{deck_id}").json()["cards"][0]["repetitions"]
        == 0
    )


def test_nothing_due_carries_the_next_due_time_not_a_bare_empty_list(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    flashcard_service: FlashcardService,
) -> None:
    student = _seed_user(pg_sessionmaker)
    _use_service(client, flashcard_service)
    _auth_as(client, student)
    deck_id = client.post(
        "/api/student/flashcards/decks", json={"subjectCode": "0625", "title": "Deck"}
    ).json()["id"]
    card_id = client.post(
        f"/api/student/flashcards/decks/{deck_id}/cards", json={"front": "Q", "back": "A"}
    ).json()["id"]

    due_now = client.get("/api/student/flashcards/due").json()
    assert [c["id"] for c in due_now["cards"]] == [card_id]
    assert due_now["totalDue"] == 1
    assert due_now["nextDueAt"] is None  # everything owned is already due

    client.post(f"/api/student/flashcards/cards/{card_id}/review", json={"grade": "good"})

    after = client.get("/api/student/flashcards/due").json()
    assert after["cards"] == []
    assert after["totalDue"] == 0
    # S-22 can say *when*, not just "nothing".
    assert after["nextDueAt"] is not None
    assert datetime.fromisoformat(after["nextDueAt"]) > _FIXED_NOW


def test_the_due_backlog_total_ignores_the_session_limit(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    flashcard_service: FlashcardService,
) -> None:
    student = _seed_user(pg_sessionmaker)
    _use_service(client, flashcard_service)
    _auth_as(client, student)
    deck_id = client.post(
        "/api/student/flashcards/decks", json={"subjectCode": "0625", "title": "Deck"}
    ).json()["id"]
    for n in range(4):
        client.post(
            f"/api/student/flashcards/decks/{deck_id}/cards",
            json={"front": f"Q{n}", "back": f"A{n}"},
        )

    body = client.get("/api/student/flashcards/due", params={"limit": 2}).json()
    assert len(body["cards"]) == 2
    # A capped session must not report its cap as the whole backlog.
    assert body["totalDue"] == 4
