"""Schema-level tests for the flashcard tables (P4.6 chunk A, migration ``0011_flashcards``).

Pins four things a migration/model pair can silently drift on:

* deck -> card ``ON DELETE CASCADE`` actually deletes cards;
* card -> review ``ON DELETE CASCADE`` actually deletes reviews;
* the server defaults on ``flashcards``' SM-2 columns produce *exactly* the
  same initial state ``lemely.core.spaced_repetition.initial_schedule``
  computes — the one test that would catch the migration and the core module
  disagreeing about a new card's starting state;
* the ``deckorigin``/``cardsource``/``reviewgrade`` enums round-trip through
  a real Postgres server, and ``ReviewGrade`` (db mirror) agrees with
  ``lemely.core.spaced_repetition.ReviewGrade`` (core original) member-for-
  member.

Same throwaway-database fixture pattern as ``tests/test_db_schema.py`` and
``tests/test_placement_quiz_ownership.py``: skips cleanly when no local
Postgres is reachable.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from lemely.core.spaced_repetition import ReviewGrade as CoreReviewGrade
from lemely.core.spaced_repetition import initial_schedule
from lemely.db.base import Base
from lemely.db.models import import_all_models
from lemely.db.models.enums import Role
from lemely.db.models.flashcards import (
    CardSource,
    DeckOrigin,
    Flashcard,
    FlashcardDeck,
    FlashcardReview,
)
from lemely.db.models.flashcards import ReviewGrade as DbReviewGrade
from lemely.db.models.users import User
from lemely.runtime.config import DatabaseSettings

if TYPE_CHECKING:
    from collections.abc import Iterator

import_all_models()

_NOW = datetime(2026, 8, 6, 12, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Metadata layer — no database required
# ---------------------------------------------------------------------------


def test_review_grade_enum_matches_the_core_scheduler_vocabulary() -> None:
    """The db-mirror enum and the core enum must never drift apart.

    See the "two mirrored enums" docstrings in
    ``lemely/core/spaced_repetition.py`` and
    ``lemely/db/models/flashcards.py`` for why the duplication exists; this
    is the test that makes it safe.
    """
    assert {m.value for m in DbReviewGrade} == {m.value for m in CoreReviewGrade}
    assert [m.name for m in DbReviewGrade] == [m.name for m in CoreReviewGrade]


# ---------------------------------------------------------------------------
# Integration layer — real Postgres, skipped when unreachable
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


@pytest.fixture(scope="module")
def pg_engine() -> Iterator[sa.Engine]:
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
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE)'))
        admin.dispose()


def _seed_user(session: Session) -> uuid.UUID:
    uid = uuid.uuid4()
    session.add(User(id=uid, email=f"{uid}@example.com", role=Role.student))
    session.flush()
    return uid


def _seed_deck(session: Session, user_id: uuid.UUID) -> uuid.UUID:
    deck = FlashcardDeck(
        user_id=user_id,
        subject_code="0625",
        topic="4.3 Electric circuits",
        title="Circuits deck",
        origin=DeckOrigin.manual,
    )
    session.add(deck)
    session.flush()
    return deck.id


def test_deck_cascade_deletes_its_cards(pg_engine: sa.Engine) -> None:
    with Session(pg_engine) as session:
        user_id = _seed_user(session)
        deck_id = _seed_deck(session, user_id)
        session.add(
            Flashcard(
                deck_id=deck_id,
                front="What is resistance?",
                back="Opposition to current flow.",
                position=0,
                source=CardSource.manual,
            )
        )
        session.commit()

        assert session.scalar(sa.select(sa.func.count()).select_from(Flashcard)) == 1

        session.execute(sa.delete(FlashcardDeck).where(FlashcardDeck.id == deck_id))
        session.commit()

        assert session.scalar(sa.select(sa.func.count()).select_from(Flashcard)) == 0


def test_card_cascade_deletes_its_reviews(pg_engine: sa.Engine) -> None:
    with Session(pg_engine) as session:
        user_id = _seed_user(session)
        deck_id = _seed_deck(session, user_id)
        card = Flashcard(
            deck_id=deck_id,
            front="What is voltage?",
            back="Energy per unit charge.",
            position=0,
            source=CardSource.ai,
            source_question_id="0625-w23-42-q3",
        )
        session.add(card)
        session.flush()
        session.add(
            FlashcardReview(
                card_id=card.id,
                user_id=user_id,
                grade=DbReviewGrade.good,
                reviewed_at=_NOW,
                interval_before_days=0,
                interval_after_days=1,
                ease_after=2.5,
            )
        )
        session.commit()

        assert session.scalar(sa.select(sa.func.count()).select_from(FlashcardReview)) == 1

        session.execute(sa.delete(Flashcard).where(Flashcard.id == card.id))
        session.commit()

        assert session.scalar(sa.select(sa.func.count()).select_from(FlashcardReview)) == 0


def test_card_server_defaults_match_initial_schedule(pg_engine: sa.Engine) -> None:
    """The model's server defaults must reproduce ``initial_schedule`` exactly.

    This is the drift-catcher: if a future edit changes
    ``initial_schedule``'s starting ease/interval without updating the
    ``server_default``s on :class:`Flashcard` (or vice versa), a freshly
    inserted row and a freshly computed schedule will disagree and this test
    fails.

    Note the precise scope: the fixture builds the schema with
    ``Base.metadata.create_all``, so this pins **model vs. core**, not
    **migration vs. core**. The migration is held to the model separately, by
    ``alembic check`` in ``scripts/check.sh`` — the two together close the
    chain, and neither alone does.
    """
    before = datetime.now(UTC)
    with Session(pg_engine) as session:
        user_id = _seed_user(session)
        deck_id = _seed_deck(session, user_id)
        card = Flashcard(
            deck_id=deck_id,
            front="What is current?",
            back="Rate of flow of charge.",
            position=0,
            source=CardSource.manual,
        )
        session.add(card)
        session.commit()
        session.refresh(card)
    after = datetime.now(UTC)

    expected = initial_schedule(before)  # `now` only matters for `due_at` here

    assert card.repetitions == expected.repetitions
    assert card.ease_factor == pytest.approx(expected.ease_factor)
    assert card.interval_days == expected.interval_days
    assert card.lapses == expected.lapses
    assert card.last_reviewed_at is expected.last_reviewed_at
    # due_at is server now(), bracketed by the insert window rather than
    # equal to a client-side timestamp.
    assert before - timedelta(seconds=5) <= card.due_at <= after + timedelta(seconds=5)


def test_deck_origin_and_card_source_enums_round_trip(pg_engine: sa.Engine) -> None:
    with Session(pg_engine) as session:
        user_id = _seed_user(session)
        for origin in DeckOrigin:
            deck = FlashcardDeck(
                user_id=user_id,
                subject_code="0625",
                title=f"{origin.value} deck",
                origin=origin,
            )
            session.add(deck)
            session.flush()
            session.refresh(deck)
            assert deck.origin is origin

        deck_id = _seed_deck(session, user_id)
        for source in CardSource:
            card = Flashcard(
                deck_id=deck_id,
                front="front",
                back="back",
                position=0,
                source=source,
            )
            session.add(card)
            session.flush()
            session.refresh(card)
            assert card.source is source
        session.commit()


def test_review_grade_enum_round_trips(pg_engine: sa.Engine) -> None:
    with Session(pg_engine) as session:
        user_id = _seed_user(session)
        deck_id = _seed_deck(session, user_id)
        card = Flashcard(
            deck_id=deck_id,
            front="front",
            back="back",
            position=0,
            source=CardSource.manual,
        )
        session.add(card)
        session.flush()

        for grade in DbReviewGrade:
            review = FlashcardReview(
                card_id=card.id,
                user_id=user_id,
                grade=grade,
                reviewed_at=_NOW,
                interval_before_days=0,
                interval_after_days=1,
                ease_after=2.5,
            )
            session.add(review)
            session.flush()
            session.refresh(review)
            assert review.grade is grade
        session.commit()
