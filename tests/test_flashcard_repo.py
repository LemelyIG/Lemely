"""Tests for :mod:`lemely.db.flashcard_repo` (P4.6 chunk B).

Postgres-integration, mirroring ``tests/test_practice_repo.py``'s throwaway-
database fixture. Gemini is always mocked via a fake
``FlashcardGenerator`` — nothing here constructs a real
:class:`~lemely.io.gemini.GeminiClient` (MISSION §8 / D4.3's suite-wide
guard would raise if it tried).

Covers:

* Deck creation: manual (topic optional), topic (topic required), weakness
  (topic resolved, refused honestly with no ``WeaknessRecord`` rows).
* AI generation: a mocked generator's short response is reported honestly,
  never padded; ``origin=manual`` and "no generator wired" both refuse.
* The honesty rule that an AI card's ``source`` can never be edited back to
  manual, verified by inversion (a hypothetical launder would flip the
  assertion).
* Owner-scoping on every read/write: unknown id -> 404-shaped error, another
  student's id -> 403-shaped error.
* SM-2 review recording: the persisted card state matches
  ``lemely.core.spaced_repetition.review`` exactly, and the audit row
  captures the real before/after state.
* "Nothing due" is a real state, not defeated by a freshly-scheduled review.
"""

from __future__ import annotations

import threading
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.core.flashcards import GeneratedFlashcard, GeneratedFlashcardDeck
from lemely.core.spaced_repetition import AGAIN_REVIEW_DELAY, INITIAL_EASE_FACTOR
from lemely.db.base import Base
from lemely.db.flashcard_repo import (
    KNOWN_INTERVAL_DAYS,
    FlashcardGenerationUnavailableError,
    FlashcardNotFoundError,
    FlashcardOwnershipError,
    FlashcardService,
    FlashcardUnavailableError,
    FlashcardUnavailableReason,
    FlashcardValidationError,
    MasteryCounts,
)
from lemely.db.models import User
from lemely.db.models.attempts import Attempt, WeaknessRecord
from lemely.db.models.enums import AttemptOrigin, Role
from lemely.db.models.flashcards import (
    CardSource,
    DeckGenerationStatus,
    DeckOrigin,
    Flashcard,
    FlashcardDeck,
    FlashcardReview,
)
from lemely.db.models.flashcards import ReviewGrade as DbReviewGrade
from lemely.runtime.config import DatabaseSettings

if TYPE_CHECKING:
    from collections.abc import Iterator

# ---------------------------------------------------------------------------
# Fixtures — throwaway Postgres database, mirrors the sibling practice suite.
# ---------------------------------------------------------------------------


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


_FIXED_NOW = datetime(2026, 8, 8, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def flashcard_service(pg_sessionmaker: sessionmaker[Session]) -> FlashcardService:
    return FlashcardService(pg_sessionmaker, now=lambda: _FIXED_NOW)


def _seed_user(sm: sessionmaker[Session], role: Role = Role.student) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=role))
    return uid


def _seed_weakness(
    sm: sessionmaker[Session],
    student_id: uuid.UUID,
    *,
    subject_code: str = "0625",
    topic: str,
    lost_marks: int,
    maximum_marks: int = 10,
) -> None:
    with sm.begin() as session:
        attempt = Attempt(
            user_id=student_id,
            subject_code=subject_code,
            awarded_marks=maximum_marks - lost_marks,
            maximum_marks=maximum_marks,
            percentage=100.0 * (maximum_marks - lost_marks) / maximum_marks,
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
                maximum_marks=maximum_marks,
                accuracy=1.0 - lost_marks / maximum_marks,
            )
        )


def _mock_generator(cards: list[GeneratedFlashcard], *, subject_code: str, topic: str) -> MagicMock:
    generator = MagicMock()
    generator.generate.return_value = GeneratedFlashcardDeck(
        subject_code=subject_code, topic=topic, cards=cards
    )
    return generator


# ---------------------------------------------------------------------------
# Deck creation: manual / topic / weakness
# ---------------------------------------------------------------------------


def test_manual_deck_creation_allows_no_topic(
    pg_sessionmaker: sessionmaker[Session], flashcard_service: FlashcardService
) -> None:
    student = _seed_user(pg_sessionmaker)
    deck = flashcard_service.create_deck(student, subject_code="0625", title="My revision")
    assert deck.origin == DeckOrigin.manual
    assert deck.topic is None
    assert deck.card_count == 0


def test_topic_deck_requires_a_topic(
    pg_sessionmaker: sessionmaker[Session], flashcard_service: FlashcardService
) -> None:
    student = _seed_user(pg_sessionmaker)
    with pytest.raises(FlashcardValidationError):
        flashcard_service.create_deck(
            student, subject_code="0625", title="Waves", origin=DeckOrigin.topic
        )

    # Inverse: supplying one succeeds and is stored verbatim.
    deck = flashcard_service.create_deck(
        student,
        subject_code="0625",
        title="Waves",
        origin=DeckOrigin.topic,
        topic="3 Waves",
    )
    assert deck.topic == "3 Waves"
    assert deck.origin == DeckOrigin.topic


def test_weakness_deck_with_no_weakness_rows_is_an_honest_refusal(
    pg_sessionmaker: sessionmaker[Session], flashcard_service: FlashcardService
) -> None:
    student = _seed_user(pg_sessionmaker)
    with pytest.raises(FlashcardUnavailableError) as exc_info:
        flashcard_service.create_deck(
            student, subject_code="0625", title="Weak spots", origin=DeckOrigin.weakness
        )
    assert exc_info.value.reason == FlashcardUnavailableReason.no_weaknesses

    # Inverse: a real weakness row makes it succeed and records the topic.
    _seed_weakness(pg_sessionmaker, student, topic="4.3 Electric circuits", lost_marks=5)
    deck = flashcard_service.create_deck(
        student, subject_code="0625", title="Weak spots", origin=DeckOrigin.weakness
    )
    assert deck.topic == "4.3 Electric circuits"
    assert deck.origin == DeckOrigin.weakness


def test_weakness_deck_picks_the_topic_with_the_most_net_lost_marks(
    pg_sessionmaker: sessionmaker[Session], flashcard_service: FlashcardService
) -> None:
    student = _seed_user(pg_sessionmaker)
    _seed_weakness(pg_sessionmaker, student, topic="1 Motion", lost_marks=2)
    _seed_weakness(pg_sessionmaker, student, topic="3 Waves", lost_marks=8)

    deck = flashcard_service.create_deck(
        student, subject_code="0625", title="Weak spots", origin=DeckOrigin.weakness
    )
    assert deck.topic == "3 Waves"


def test_weakness_deck_excludes_a_topic_with_zero_net_lost_marks(
    pg_sessionmaker: sessionmaker[Session], flashcard_service: FlashcardService
) -> None:
    """Mirrors ``group_weak_areas``'s rule (also applied by
    ``PracticeService._weak_topics_for``): a topic with zero net lost marks
    is not a weakness, even if a ``WeaknessRecord`` row exists for it."""
    student = _seed_user(pg_sessionmaker)
    _seed_weakness(pg_sessionmaker, student, topic="1 Motion", lost_marks=0, maximum_marks=10)

    with pytest.raises(FlashcardUnavailableError) as exc_info:
        flashcard_service.create_deck(
            student, subject_code="0625", title="Weak spots", origin=DeckOrigin.weakness
        )
    assert exc_info.value.reason == FlashcardUnavailableReason.no_weaknesses


def test_weakness_deck_rejects_a_topic_that_is_not_a_recorded_weakness(
    pg_sessionmaker: sessionmaker[Session], flashcard_service: FlashcardService
) -> None:
    student = _seed_user(pg_sessionmaker)
    _seed_weakness(pg_sessionmaker, student, topic="3 Waves", lost_marks=5)
    with pytest.raises(FlashcardValidationError):
        flashcard_service.create_deck(
            student,
            subject_code="0625",
            title="Weak spots",
            origin=DeckOrigin.weakness,
            topic="1 Motion",
        )


def test_weakness_deck_accepts_a_chosen_recorded_weakness(
    pg_sessionmaker: sessionmaker[Session], flashcard_service: FlashcardService
) -> None:
    student = _seed_user(pg_sessionmaker)
    _seed_weakness(pg_sessionmaker, student, topic="3 Waves", lost_marks=9)
    _seed_weakness(pg_sessionmaker, student, topic="1 Motion", lost_marks=2)
    deck = flashcard_service.create_deck(
        student, subject_code="0625", title="Motion", origin=DeckOrigin.weakness, topic="1 Motion"
    )
    assert deck.topic == "1 Motion"


# ---------------------------------------------------------------------------
# AI generation
# ---------------------------------------------------------------------------


def test_generate_deck_reports_the_true_short_count_never_padded(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student = _seed_user(pg_sessionmaker)
    generator = _mock_generator(
        [GeneratedFlashcard(front="What is force?", back="Mass x acceleration.")],
        subject_code="0625",
        topic="1 Motion",
    )
    service = FlashcardService(pg_sessionmaker, generator, now=lambda: _FIXED_NOW)

    result = service.generate_deck(
        student, subject_code="0625", origin=DeckOrigin.topic, topic="1 Motion", count=5
    )

    assert result.requested_count == 5
    assert result.generated_count == 1
    assert result.deck.card_count == 1
    generator.generate.assert_called_once_with(subject_code="0625", topic="1 Motion", count=5)


def test_generate_deck_cards_are_stored_as_ai_source(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student = _seed_user(pg_sessionmaker)
    generator = _mock_generator(
        [
            GeneratedFlashcard(front="Q1", back="A1"),
            GeneratedFlashcard(front="Q2", back="A2", source_question_id="0625_s23_qp_11#4"),
        ],
        subject_code="0625",
        topic="1 Motion",
    )
    service = FlashcardService(pg_sessionmaker, generator, now=lambda: _FIXED_NOW)

    result = service.generate_deck(
        student, subject_code="0625", origin=DeckOrigin.topic, topic="1 Motion", count=2
    )
    detail = service.get_deck(student, result.deck.id)
    assert len(detail.cards) == 2
    assert all(c.source == CardSource.ai for c in detail.cards)
    assert detail.cards[1].source_question_id == "0625_s23_qp_11#4"
    assert detail.cards[0].source_question_id is None


def test_generate_deck_without_a_generator_wired_is_unavailable(
    pg_sessionmaker: sessionmaker[Session], flashcard_service: FlashcardService
) -> None:
    student = _seed_user(pg_sessionmaker)
    with pytest.raises(FlashcardGenerationUnavailableError):
        flashcard_service.generate_deck(
            student, subject_code="0625", origin=DeckOrigin.topic, topic="1 Motion", count=3
        )


def test_generate_deck_refuses_manual_origin(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student = _seed_user(pg_sessionmaker)
    generator = _mock_generator([], subject_code="0625", topic="1 Motion")
    service = FlashcardService(pg_sessionmaker, generator, now=lambda: _FIXED_NOW)
    with pytest.raises(FlashcardValidationError):
        service.generate_deck(student, subject_code="0625", origin=DeckOrigin.manual, count=3)
    generator.generate.assert_not_called()


def test_generate_deck_with_weakness_origin_resolves_the_top_topic(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student = _seed_user(pg_sessionmaker)
    _seed_weakness(pg_sessionmaker, student, topic="3 Waves", lost_marks=9)
    generator = _mock_generator(
        [GeneratedFlashcard(front="Q", back="A")], subject_code="0625", topic="3 Waves"
    )
    service = FlashcardService(pg_sessionmaker, generator, now=lambda: _FIXED_NOW)

    result = service.generate_deck(
        student, subject_code="0625", origin=DeckOrigin.weakness, count=3
    )
    assert result.deck.topic == "3 Waves"
    generator.generate.assert_called_once_with(subject_code="0625", topic="3 Waves", count=3)


# ---------------------------------------------------------------------------
# Card mutation, and the AI-source honesty rule
# ---------------------------------------------------------------------------


def test_add_card_is_always_manual_source(
    pg_sessionmaker: sessionmaker[Session], flashcard_service: FlashcardService
) -> None:
    student = _seed_user(pg_sessionmaker)
    deck = flashcard_service.create_deck(student, subject_code="0625", title="Deck")
    card = flashcard_service.add_card(student, deck.id, front="Q", back="A")
    assert card.source == CardSource.manual
    assert card.position == 1

    card2 = flashcard_service.add_card(student, deck.id, front="Q2", back="A2")
    assert card2.position == 2


def test_edit_card_does_not_change_an_ai_cards_source(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """The P4.6 honesty rule pinned by inversion: if a future edit_card grew a
    ``source`` parameter and someone passed ``manual`` through it, this test
    would fail — today it cannot even be attempted, because the method has no
    such parameter."""
    student = _seed_user(pg_sessionmaker)
    generator = _mock_generator(
        [GeneratedFlashcard(front="Original", back="Answer")], subject_code="0625", topic="1 Motion"
    )
    service = FlashcardService(pg_sessionmaker, generator, now=lambda: _FIXED_NOW)
    result = service.generate_deck(
        student, subject_code="0625", origin=DeckOrigin.topic, topic="1 Motion", count=1
    )
    ai_card = service.get_deck(student, result.deck.id).cards[0]
    assert ai_card.source == CardSource.ai

    edited = service.edit_card(student, ai_card.id, front="Rewritten in my own words")
    assert edited.front == "Rewritten in my own words"
    assert edited.source == CardSource.ai  # still AI — never laundered to manual.


def test_delete_card_removes_it(
    pg_sessionmaker: sessionmaker[Session], flashcard_service: FlashcardService
) -> None:
    student = _seed_user(pg_sessionmaker)
    deck = flashcard_service.create_deck(student, subject_code="0625", title="Deck")
    card = flashcard_service.add_card(student, deck.id, front="Q", back="A")

    flashcard_service.delete_card(student, card.id)

    with pytest.raises(FlashcardNotFoundError):
        flashcard_service.edit_card(student, card.id, front="anything")


def test_delete_deck_takes_its_cards_with_it(
    pg_sessionmaker: sessionmaker[Session], flashcard_service: FlashcardService
) -> None:
    student = _seed_user(pg_sessionmaker)
    deck = flashcard_service.create_deck(student, subject_code="0625", title="Deck")
    card = flashcard_service.add_card(student, deck.id, front="Q", back="A")

    flashcard_service.delete_deck(student, deck.id)

    with pytest.raises(FlashcardNotFoundError):
        flashcard_service.get_deck(student, deck.id)
    # The cards must not survive as orphans pointing at a dead deck id.
    with pg_sessionmaker() as session:
        assert session.get(Flashcard, card.id) is None


def test_delete_deck_refuses_another_students_deck(
    pg_sessionmaker: sessionmaker[Session], flashcard_service: FlashcardService
) -> None:
    owner = _seed_user(pg_sessionmaker)
    other = _seed_user(pg_sessionmaker)
    deck = flashcard_service.create_deck(owner, subject_code="0625", title="Mine")

    with pytest.raises(FlashcardOwnershipError):
        flashcard_service.delete_deck(other, deck.id)
    # Inverse: the owner can still delete it, so the refusal was about identity.
    flashcard_service.delete_deck(owner, deck.id)


# ---------------------------------------------------------------------------
# Owner scoping
# ---------------------------------------------------------------------------


def test_unknown_deck_id_is_not_found(
    pg_sessionmaker: sessionmaker[Session], flashcard_service: FlashcardService
) -> None:
    student = _seed_user(pg_sessionmaker)
    with pytest.raises(FlashcardNotFoundError):
        flashcard_service.get_deck(student, uuid.uuid4())


def test_another_students_deck_is_ownership_error_not_not_found(
    pg_sessionmaker: sessionmaker[Session], flashcard_service: FlashcardService
) -> None:
    owner = _seed_user(pg_sessionmaker)
    other = _seed_user(pg_sessionmaker)
    deck = flashcard_service.create_deck(owner, subject_code="0625", title="Mine")

    with pytest.raises(FlashcardOwnershipError):
        flashcard_service.get_deck(other, deck.id)


def test_another_students_card_is_ownership_error(
    pg_sessionmaker: sessionmaker[Session], flashcard_service: FlashcardService
) -> None:
    owner = _seed_user(pg_sessionmaker)
    other = _seed_user(pg_sessionmaker)
    deck = flashcard_service.create_deck(owner, subject_code="0625", title="Mine")
    card = flashcard_service.add_card(owner, deck.id, front="Q", back="A")

    with pytest.raises(FlashcardOwnershipError):
        flashcard_service.edit_card(other, card.id, front="hijacked")
    with pytest.raises(FlashcardOwnershipError):
        flashcard_service.delete_card(other, card.id)


def test_list_decks_only_returns_the_callers_own(
    pg_sessionmaker: sessionmaker[Session], flashcard_service: FlashcardService
) -> None:
    owner = _seed_user(pg_sessionmaker)
    other = _seed_user(pg_sessionmaker)
    flashcard_service.create_deck(owner, subject_code="0625", title="Mine")
    flashcard_service.create_deck(other, subject_code="0625", title="Not mine")

    decks = flashcard_service.list_decks(owner)
    assert len(decks) == 1
    assert decks[0].title == "Mine"


# ---------------------------------------------------------------------------
# Due-card listing
# ---------------------------------------------------------------------------


def test_a_new_card_is_due_immediately(
    pg_sessionmaker: sessionmaker[Session], flashcard_service: FlashcardService
) -> None:
    student = _seed_user(pg_sessionmaker)
    deck = flashcard_service.create_deck(student, subject_code="0625", title="Deck")
    flashcard_service.add_card(student, deck.id, front="Q", back="A")

    due = flashcard_service.list_due_cards(student)
    assert len(due) == 1


def test_a_card_scheduled_into_the_future_is_not_due(
    pg_sessionmaker: sessionmaker[Session], flashcard_service: FlashcardService
) -> None:
    student = _seed_user(pg_sessionmaker)
    deck = flashcard_service.create_deck(student, subject_code="0625", title="Deck")
    card = flashcard_service.add_card(student, deck.id, front="Q", back="A")

    flashcard_service.record_review(student, card.id, DbReviewGrade.good, now=_FIXED_NOW)
    # `good` on a first review schedules 1 day out (SM-2), well past _FIXED_NOW.
    due = flashcard_service.list_due_cards(student)
    assert due == []

    # Inverse: nothing due is a real state, not defeated by another fresh card.
    flashcard_service.add_card(student, deck.id, front="Q2", back="A2")
    due_again = flashcard_service.list_due_cards(student)
    assert len(due_again) == 1


def test_subject_filtering_scopes_both_deck_and_due_listings(
    pg_sessionmaker: sessionmaker[Session], flashcard_service: FlashcardService
) -> None:
    student = _seed_user(pg_sessionmaker)
    physics = flashcard_service.create_deck(student, subject_code="0625", title="Physics")
    maths = flashcard_service.create_deck(student, subject_code="0580", title="Maths")
    flashcard_service.add_card(student, physics.id, front="Q", back="A")
    flashcard_service.add_card(student, maths.id, front="Q", back="A")

    assert [d.title for d in flashcard_service.list_decks(student, subject_code="0625")] == [
        "Physics"
    ]
    assert len(flashcard_service.list_due_cards(student, subject_code="0625")) == 1
    # Inverse: without the filter both subjects come back, so the filter is
    # what narrowed it — not an empty database.
    assert len(flashcard_service.list_decks(student)) == 2
    assert len(flashcard_service.list_due_cards(student)) == 2


def test_due_listing_honours_its_limit(
    pg_sessionmaker: sessionmaker[Session], flashcard_service: FlashcardService
) -> None:
    student = _seed_user(pg_sessionmaker)
    deck = flashcard_service.create_deck(student, subject_code="0625", title="Deck")
    for n in range(3):
        flashcard_service.add_card(student, deck.id, front=f"Q{n}", back=f"A{n}")

    assert len(flashcard_service.list_due_cards(student, limit=2)) == 2
    assert len(flashcard_service.list_due_cards(student)) == 3


# ---------------------------------------------------------------------------
# Review recording
# ---------------------------------------------------------------------------


def test_record_review_matches_core_scheduler_and_writes_an_audit_row(
    pg_sessionmaker: sessionmaker[Session], flashcard_service: FlashcardService
) -> None:
    student = _seed_user(pg_sessionmaker)
    deck = flashcard_service.create_deck(student, subject_code="0625", title="Deck")
    card = flashcard_service.add_card(student, deck.id, front="Q", back="A")
    assert card.ease_factor == INITIAL_EASE_FACTOR
    assert card.interval_days == 0

    outcome = flashcard_service.record_review(student, card.id, DbReviewGrade.good, now=_FIXED_NOW)

    assert outcome.interval_before_days == 0
    assert outcome.interval_after_days == 1
    assert outcome.card.repetitions == 1
    assert outcome.card.due_at == _FIXED_NOW + timedelta(days=1)

    with pg_sessionmaker() as session:
        reviews = session.scalars(
            select(FlashcardReview).where(FlashcardReview.card_id == card.id)
        ).all()
    assert len(reviews) == 1
    review_row = reviews[0]
    assert review_row.grade == DbReviewGrade.good
    assert review_row.interval_before_days == 0
    assert review_row.interval_after_days == 1
    assert review_row.ease_after == outcome.card.ease_factor

    with pg_sessionmaker() as session:
        persisted = session.get(Flashcard, card.id)
        assert persisted is not None
        assert persisted.interval_days == 1
        assert persisted.repetitions == 1


def test_record_review_again_shortens_interval_and_increments_lapses(
    pg_sessionmaker: sessionmaker[Session], flashcard_service: FlashcardService
) -> None:
    student = _seed_user(pg_sessionmaker)
    deck = flashcard_service.create_deck(student, subject_code="0625", title="Deck")
    card = flashcard_service.add_card(student, deck.id, front="Q", back="A")

    outcome = flashcard_service.record_review(student, card.id, DbReviewGrade.again, now=_FIXED_NOW)

    assert outcome.card.interval_days == 0
    assert outcome.card.lapses == 1
    assert outcome.card.due_at == _FIXED_NOW + AGAIN_REVIEW_DELAY
    # Same-session relearning: it resurfaces soon, so it is not "due now" yet
    # but the interval and due_at exactly match the pure scheduler's output.


def test_record_review_unknown_card_is_not_found(
    pg_sessionmaker: sessionmaker[Session], flashcard_service: FlashcardService
) -> None:
    student = _seed_user(pg_sessionmaker)
    with pytest.raises(FlashcardNotFoundError):
        flashcard_service.record_review(student, uuid.uuid4(), DbReviewGrade.good, now=_FIXED_NOW)


# ---------------------------------------------------------------------------
# Redesign L10: mastery, marks lost, rename, weak topics, due scope, forecast
# ---------------------------------------------------------------------------


def _manual_deck_with_cards(service: FlashcardService, student: uuid.UUID, n: int) -> uuid.UUID:
    deck = service.create_deck(student, subject_code="0625", title="Deck", origin=DeckOrigin.manual)
    for i in range(n):
        service.add_card(student, deck.id, front=f"Q{i}", back=f"A{i}")
    return deck.id


def test_list_decks_reports_new_learning_known_counts(
    pg_sessionmaker: sessionmaker[Session], flashcard_service: FlashcardService
) -> None:
    student = _seed_user(pg_sessionmaker)
    deck_id = _manual_deck_with_cards(flashcard_service, student, 4)
    cards = flashcard_service.get_deck(student, deck_id).cards
    # One card reviewed once (learning), one pushed past the known threshold, two untouched.
    flashcard_service.record_review(student, cards[0].id, DbReviewGrade.good)
    with pg_sessionmaker.begin() as session:
        row = session.get(Flashcard, cards[1].id)
        assert row is not None
        row.repetitions = 3
        row.interval_days = KNOWN_INTERVAL_DAYS
        row.last_reviewed_at = _FIXED_NOW

    [summary] = flashcard_service.list_decks(student)
    assert summary.mastery == MasteryCounts(new=2, learning=1, known=1)
    assert summary.card_count == 4


def test_weakness_deck_reports_the_marks_its_topic_cost(
    pg_sessionmaker: sessionmaker[Session], flashcard_service: FlashcardService
) -> None:
    student = _seed_user(pg_sessionmaker)
    _seed_weakness(pg_sessionmaker, student, topic="3 Waves", lost_marks=5)
    _seed_weakness(pg_sessionmaker, student, topic="3 Waves", lost_marks=4)
    flashcard_service.create_deck(
        student, subject_code="0625", title="Waves", origin=DeckOrigin.weakness
    )
    flashcard_service.create_deck(
        student, subject_code="0625", title="Mine", origin=DeckOrigin.manual, topic="3 Waves"
    )
    by_title = {d.title: d for d in flashcard_service.list_decks(student)}
    assert by_title["Waves"].marks_lost == 9
    # Only a weakness deck claims "cost you N marks"; a manual deck on the same topic does not.
    assert by_title["Mine"].marks_lost is None


def test_rename_deck_trims_and_rejects_blank_or_long_titles(
    pg_sessionmaker: sessionmaker[Session], flashcard_service: FlashcardService
) -> None:
    student = _seed_user(pg_sessionmaker)
    deck_id = _manual_deck_with_cards(flashcard_service, student, 1)
    renamed = flashcard_service.rename_deck(student, deck_id, title="  Vectors  ")
    assert renamed.title == "Vectors"
    assert renamed.card_count == 1
    with pytest.raises(FlashcardValidationError):
        flashcard_service.rename_deck(student, deck_id, title="   ")
    with pytest.raises(FlashcardValidationError):
        flashcard_service.rename_deck(student, deck_id, title="x" * 81)


def test_rename_someone_elses_deck_is_an_ownership_error(
    pg_sessionmaker: sessionmaker[Session], flashcard_service: FlashcardService
) -> None:
    owner = _seed_user(pg_sessionmaker)
    other = _seed_user(pg_sessionmaker)
    deck_id = _manual_deck_with_cards(flashcard_service, owner, 0)
    with pytest.raises(FlashcardOwnershipError):
        flashcard_service.rename_deck(other, deck_id, title="Mine now")


def test_weak_topics_ranks_by_marks_lost_with_accuracy(
    pg_sessionmaker: sessionmaker[Session], flashcard_service: FlashcardService
) -> None:
    student = _seed_user(pg_sessionmaker)
    _seed_weakness(pg_sessionmaker, student, topic="3 Waves", lost_marks=6, maximum_marks=10)
    _seed_weakness(pg_sessionmaker, student, topic="1 Motion", lost_marks=2, maximum_marks=10)
    _seed_weakness(
        pg_sessionmaker,
        student,
        subject_code="0580",
        topic="E7 Vectors",
        lost_marks=9,
        maximum_marks=15,
    )
    topics = flashcard_service.weak_topics(student)
    assert [(t.subject_code, t.topic, t.marks_lost) for t in topics] == [
        ("0580", "E7 Vectors", 9),
        ("0625", "3 Waves", 6),
        ("0625", "1 Motion", 2),
    ]
    assert topics[0].accuracy_pct == 40
    only_physics = flashcard_service.weak_topics(student, subject_code="0625", limit=1)
    assert [t.topic for t in only_physics] == ["3 Waves"]


def test_due_session_scoped_to_one_deck_and_carries_the_forecast(
    pg_sessionmaker: sessionmaker[Session], flashcard_service: FlashcardService
) -> None:
    student = _seed_user(pg_sessionmaker)
    deck_a = _manual_deck_with_cards(flashcard_service, student, 2)
    deck_b = _manual_deck_with_cards(flashcard_service, student, 3)
    first_b = flashcard_service.get_deck(student, deck_b).cards[0]
    flashcard_service.record_review(student, first_b.id, DbReviewGrade.good)  # due in 1 day

    session_a = flashcard_service.due_session(student, deck_id=deck_a)
    assert session_a.total_due == 2
    assert {c.id for c in session_a.cards} <= {
        c.id for c in flashcard_service.get_deck(student, deck_a).cards
    }

    session_all = flashcard_service.due_session(student)
    assert session_all.total_due == 4
    assert session_all.upcoming == [_FIXED_NOW + timedelta(days=1)]
    assert session_all.again_delay_minutes == 10


def test_due_session_for_someone_elses_deck_is_an_ownership_error(
    pg_sessionmaker: sessionmaker[Session], flashcard_service: FlashcardService
) -> None:
    owner = _seed_user(pg_sessionmaker)
    other = _seed_user(pg_sessionmaker)
    deck_id = _manual_deck_with_cards(flashcard_service, owner, 1)
    with pytest.raises(FlashcardOwnershipError):
        flashcard_service.due_session(other, deck_id=deck_id)


def test_cards_carry_the_interval_each_grade_would_give(
    pg_sessionmaker: sessionmaker[Session], flashcard_service: FlashcardService
) -> None:
    student = _seed_user(pg_sessionmaker)
    deck_id = _manual_deck_with_cards(flashcard_service, student, 1)
    [card] = flashcard_service.due_session(student, deck_id=deck_id).cards
    # A new card: Again is the 10-minute relearning step (0 days); any pass is 1 day.
    assert card.next_interval_days == {"again": 0, "hard": 1, "good": 1, "easy": 1}


# ---------------------------------------------------------------------------
# Redesign L10: background generation with a status
# ---------------------------------------------------------------------------


def test_start_generation_saves_a_writing_deck_without_calling_the_model(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student = _seed_user(pg_sessionmaker)
    generator = _mock_generator([], subject_code="0625", topic="4.3 Electric circuits")
    service = FlashcardService(pg_sessionmaker, generator, now=lambda: _FIXED_NOW)

    deck = service.start_generation(
        student,
        subject_code="0625",
        origin=DeckOrigin.topic,
        topic="4.3 Electric circuits",
        count=12,
    )

    assert deck.generation_status == DeckGenerationStatus.writing
    assert deck.requested_count == 12
    assert deck.card_count == 0
    assert deck.title == "Electric circuits"
    generator.generate.assert_not_called()
    state = service.generation_status(student, deck.id)
    assert (state.status, state.generated_count) == (DeckGenerationStatus.writing, 0)


def test_run_generation_writes_ai_cards_and_marks_the_deck_ready(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student = _seed_user(pg_sessionmaker)
    generator = _mock_generator(
        [GeneratedFlashcard(front="Q1", back="A1"), GeneratedFlashcard(front="Q2", back="A2")],
        subject_code="0625",
        topic="1 Motion",
    )
    service = FlashcardService(pg_sessionmaker, generator, now=lambda: _FIXED_NOW)
    deck = service.start_generation(
        student, subject_code="0625", origin=DeckOrigin.topic, topic="1 Motion", count=5
    )

    service.run_generation(deck.id)

    state = service.generation_status(student, deck.id)
    assert state.status == DeckGenerationStatus.ready
    assert (state.requested_count, state.generated_count) == (5, 2)  # never padded
    detail = service.get_deck(student, deck.id)
    assert [c.source for c in detail.cards] == [CardSource.ai, CardSource.ai]
    generator.generate.assert_called_once_with(subject_code="0625", topic="1 Motion", count=5)


def test_a_model_error_marks_the_deck_failed_and_saves_no_cards(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student = _seed_user(pg_sessionmaker)
    generator = MagicMock()
    generator.generate.side_effect = RuntimeError("gemini down")
    service = FlashcardService(pg_sessionmaker, generator, now=lambda: _FIXED_NOW)
    deck = service.start_generation(
        student, subject_code="0625", origin=DeckOrigin.topic, topic="1 Motion", count=5
    )

    service.run_generation(deck.id)  # must not raise

    state = service.generation_status(student, deck.id)
    assert (state.status, state.error, state.generated_count) == (
        DeckGenerationStatus.failed,
        "model_error",
        0,
    )


def test_an_empty_model_answer_is_a_failure_not_an_empty_ready_deck(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student = _seed_user(pg_sessionmaker)
    generator = _mock_generator([], subject_code="0625", topic="1 Motion")
    service = FlashcardService(pg_sessionmaker, generator, now=lambda: _FIXED_NOW)
    deck = service.start_generation(
        student, subject_code="0625", origin=DeckOrigin.topic, topic="1 Motion", count=5
    )
    service.run_generation(deck.id)
    state = service.generation_status(student, deck.id)
    assert (state.status, state.error) == (DeckGenerationStatus.failed, "no_cards")


def test_a_stale_writing_deck_is_reported_failed(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student = _seed_user(pg_sessionmaker)
    clock = {"now": _FIXED_NOW}
    generator = _mock_generator([], subject_code="0625", topic="1 Motion")
    service = FlashcardService(pg_sessionmaker, generator, now=lambda: clock["now"])
    deck = service.start_generation(
        student, subject_code="0625", origin=DeckOrigin.topic, topic="1 Motion", count=5
    )
    clock["now"] = _FIXED_NOW + timedelta(minutes=6)
    state = service.generation_status(student, deck.id)
    assert (state.status, state.error) == (DeckGenerationStatus.failed, "timeout")
    # Persisted, so the list agrees with the status endpoint.
    [summary] = service.list_decks(student)
    assert summary.generation_status == DeckGenerationStatus.failed


def test_retry_puts_a_failed_deck_back_to_writing_and_refuses_a_ready_one(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student = _seed_user(pg_sessionmaker)
    generator = MagicMock()
    generator.generate.side_effect = [
        RuntimeError("first try fails"),
        GeneratedFlashcardDeck(
            subject_code="0625", topic="1 Motion", cards=[GeneratedFlashcard(front="Q", back="A")]
        ),
    ]
    service = FlashcardService(pg_sessionmaker, generator, now=lambda: _FIXED_NOW)
    deck = service.start_generation(
        student, subject_code="0625", origin=DeckOrigin.topic, topic="1 Motion", count=3
    )
    service.run_generation(deck.id)

    retried = service.retry_generation(student, deck.id)
    assert retried.status == DeckGenerationStatus.writing
    service.run_generation(deck.id)
    assert service.generation_status(student, deck.id).status == DeckGenerationStatus.ready
    with pytest.raises(FlashcardValidationError):
        service.retry_generation(student, deck.id)


def test_a_deck_deleted_while_writing_is_left_alone(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student = _seed_user(pg_sessionmaker)
    generator = _mock_generator(
        [GeneratedFlashcard(front="Q", back="A")], subject_code="0625", topic="1 Motion"
    )
    service = FlashcardService(pg_sessionmaker, generator, now=lambda: _FIXED_NOW)
    deck = service.start_generation(
        student, subject_code="0625", origin=DeckOrigin.topic, topic="1 Motion", count=3
    )
    service.delete_deck(student, deck.id)
    service.run_generation(deck.id)  # no deck: a no-op, not an error
    assert service.list_decks(student) == []


def test_generation_status_of_someone_elses_deck_is_an_ownership_error(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    owner = _seed_user(pg_sessionmaker)
    other = _seed_user(pg_sessionmaker)
    generator = _mock_generator([], subject_code="0625", topic="1 Motion")
    service = FlashcardService(pg_sessionmaker, generator, now=lambda: _FIXED_NOW)
    deck = service.start_generation(
        owner, subject_code="0625", origin=DeckOrigin.topic, topic="1 Motion", count=3
    )
    with pytest.raises(FlashcardOwnershipError):
        service.generation_status(other, deck.id)


# ---------------------------------------------------------------------------
# Redesign L10 fix round 1: run_generation never raises, stale everywhere, atomic retry
# ---------------------------------------------------------------------------


def test_a_database_error_while_saving_cards_marks_the_deck_failed(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student = _seed_user(pg_sessionmaker)
    # A NUL byte is valid for the model but rejected by Postgres, so the card insert fails.
    generator = _mock_generator(
        [GeneratedFlashcard(front="bad\x00front", back="A")], subject_code="0625", topic="1 Motion"
    )
    service = FlashcardService(pg_sessionmaker, generator, now=lambda: _FIXED_NOW)
    deck = service.start_generation(
        student, subject_code="0625", origin=DeckOrigin.topic, topic="1 Motion", count=3
    )

    service.run_generation(deck.id)  # must not raise

    state = service.generation_status(student, deck.id)
    assert (state.status, state.error, state.generated_count) == (
        DeckGenerationStatus.failed,
        "internal_error",
        0,
    )


def test_run_generation_survives_the_failure_marker_failing_too(
    pg_sessionmaker: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    student = _seed_user(pg_sessionmaker)
    generator = MagicMock()
    generator.generate.side_effect = RuntimeError("gemini down")
    service = FlashcardService(pg_sessionmaker, generator, now=lambda: _FIXED_NOW)
    deck = service.start_generation(
        student, subject_code="0625", origin=DeckOrigin.topic, topic="1 Motion", count=3
    )

    def _boom(_deck_uuid: uuid.UUID, _error: str) -> None:
        raise OperationalError("UPDATE", {}, Exception("db gone"))

    monkeypatch.setattr(service, "_mark_failed", _boom)

    service.run_generation(deck.id)  # must not raise


def test_list_decks_and_rename_report_a_stale_writing_deck_as_failed(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student = _seed_user(pg_sessionmaker)
    clock = {"now": _FIXED_NOW}
    generator = _mock_generator([], subject_code="0625", topic="1 Motion")
    service = FlashcardService(pg_sessionmaker, generator, now=lambda: clock["now"])
    first = service.start_generation(
        student, subject_code="0625", origin=DeckOrigin.topic, topic="1 Motion", count=5
    )
    second = service.start_generation(
        student, subject_code="0625", origin=DeckOrigin.topic, topic="1 Motion", count=5
    )
    clock["now"] = _FIXED_NOW + timedelta(minutes=6)

    renamed = service.rename_deck(student, second.id, title="Renamed")
    assert renamed.generation_status == DeckGenerationStatus.failed

    # No generation_status call before this: the list itself applies the stale rule.
    statuses = {d.id: d.generation_status for d in service.list_decks(student)}
    assert statuses == {
        first.id: DeckGenerationStatus.failed,
        second.id: DeckGenerationStatus.failed,
    }
    with pg_sessionmaker() as session:
        saved = session.get(FlashcardDeck, first.id)
        assert saved is not None
        assert (saved.generation_status, saved.generation_error) == ("failed", "timeout")


def test_a_second_concurrent_retry_loses_the_claim(
    pg_sessionmaker: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    student = _seed_user(pg_sessionmaker)
    generator = MagicMock()
    generator.generate.side_effect = RuntimeError("gemini down")
    service = FlashcardService(pg_sessionmaker, generator, now=lambda: _FIXED_NOW)
    deck = service.start_generation(
        student, subject_code="0625", origin=DeckOrigin.topic, topic="1 Motion", count=3
    )
    service.run_generation(deck.id)
    stale_failed_state = service.generation_status(student, deck.id)
    assert stale_failed_state.status == DeckGenerationStatus.failed

    service.retry_generation(student, deck.id)  # the first worker claims it

    # The second caller read the status before the first claim, so it still sees `failed`.
    monkeypatch.setattr(service, "generation_status", lambda *_a, **_k: stale_failed_state)
    with pytest.raises(FlashcardValidationError):
        service.retry_generation(student, deck.id)


def test_a_model_call_past_the_timeout_marks_the_deck_failed_timeout(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student = _seed_user(pg_sessionmaker)
    release = threading.Event()
    generator = MagicMock()
    generator.generate.side_effect = lambda **_kw: release.wait(5)
    service = FlashcardService(
        pg_sessionmaker, generator, now=lambda: _FIXED_NOW, generation_timeout_seconds=0.05
    )
    deck = service.start_generation(
        student, subject_code="0625", origin=DeckOrigin.topic, topic="1 Motion", count=3
    )

    try:
        service.run_generation(deck.id)  # returns at the bound, not when the model finishes
    finally:
        release.set()

    state = service.generation_status(student, deck.id)
    assert (state.status, state.error, state.generated_count) == (
        DeckGenerationStatus.failed,
        "timeout",
        0,
    )
    assert service.deck_summary(student, deck.id).generation_status == DeckGenerationStatus.failed
