"""Tests for :mod:`lemely.db.friend_repo` (P5.4 chunk A).

Postgres-integration, mirroring ``tests/test_xp_repo.py``/
``tests/test_leaderboard_repo.py``'s throwaway-database fixture.

Covers:

* Friend-code minting: idempotent, alphabet excludes 0/O/1/I/L, student-only.
* Request/accept: happy path, the crossed-requests auto-accept (D5.1 §8
  applied to ``friendships``), self-request, duplicate request, unknown
  code.
* The structural guarantees migration ``0015`` gives ``friendships`` —
  ``uq_friendships_pair`` and all three ``CHECK`` constraints rejected at
  the database, not caught in Python.
* ``accept``/``remove`` collapsing "no such row" and "not your row" into the
  same error (no existence oracle).
* ``remove`` covering decline/cancel/unfriend, and leaving a non-party's
  target row untouched.
* Re-request after removal (no tombstone).
* ``list_friends``: lifetime XP, current streak, and the opt-out
  "stays visible, numbers hidden" rule.
* No ``@`` (an email fragment) ever appears in a display name any friend
  method returns — the D5.5 regression test, extended to this module.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.db.base import Base
from lemely.db.friend_repo import (
    _FRIEND_CODE_ALPHABET,
    FriendAlreadyExistsError,
    FriendCodeNotFoundError,
    FriendIneligibleUserError,
    FriendNotPendingError,
    FriendRequestNotFoundError,
    FriendSelfRequestError,
    FriendService,
    FriendUserNotFoundError,
)
from lemely.db.models.engagement import Streak, XpEvent
from lemely.db.models.enums import FriendshipStatus, Role, XpSource
from lemely.db.models.profiles import StudentProfile
from lemely.db.models.users import Friendship, User
from lemely.runtime.config import DatabaseSettings

if TYPE_CHECKING:
    from collections.abc import Iterator

# ---------------------------------------------------------------------------
# Fixtures — throwaway Postgres database, mirrors the sibling XP/leaderboard suites.
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


def _seed_user(sm: sessionmaker[Session], role: Role = Role.student) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=role))
    return uid


def _award(
    sm: sessionmaker[Session],
    user_id: uuid.UUID,
    amount: int,
    awarded_on: date,
) -> None:
    with sm.begin() as session:
        session.add(
            XpEvent(
                user_id=user_id,
                source=XpSource.flashcard_reviewed,
                amount=amount,
                awarded_on=awarded_on,
                dedupe_key=f"dk-{uuid.uuid4()}",
            )
        )


def _set_streak(sm: sessionmaker[Session], user_id: uuid.UUID, current_length: int) -> None:
    with sm.begin() as session:
        session.add(
            Streak(
                user_id=user_id,
                current_length=current_length,
                longest_length=current_length,
            )
        )


def _opt_out(sm: sessionmaker[Session], user_id: uuid.UUID, *, opted_out: bool = True) -> None:
    with sm.begin() as session:
        session.add(StudentProfile(user_id=user_id, leaderboard_opt_out=opted_out))


_NOON_UTC = datetime(2026, 8, 5, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def service(pg_sessionmaker: sessionmaker[Session]) -> FriendService:
    return FriendService(pg_sessionmaker, now=lambda: _NOON_UTC)


# ---------------------------------------------------------------------------
# Friend codes
# ---------------------------------------------------------------------------


class TestFriendCode:
    def test_code_is_minted_once_and_stable_across_calls(
        self, service: FriendService, pg_sessionmaker: sessionmaker[Session]
    ) -> None:
        student = _seed_user(pg_sessionmaker)
        first = service.friend_code_for(student)
        second = service.friend_code_for(student)
        assert first == second
        assert len(first) == 8

    def test_code_alphabet_excludes_ambiguous_characters(
        self, service: FriendService, pg_sessionmaker: sessionmaker[Session]
    ) -> None:
        assert set(_FRIEND_CODE_ALPHABET) & set("0O1IL") == set()
        student = _seed_user(pg_sessionmaker)
        code = service.friend_code_for(student)
        assert set(code) <= set(_FRIEND_CODE_ALPHABET)

    def test_non_student_is_rejected(
        self, service: FriendService, pg_sessionmaker: sessionmaker[Session]
    ) -> None:
        teacher = _seed_user(pg_sessionmaker, role=Role.teacher)
        with pytest.raises(FriendIneligibleUserError):
            service.friend_code_for(teacher)

    def test_unknown_user_raises(self, service: FriendService) -> None:
        with pytest.raises(FriendUserNotFoundError):
            service.friend_code_for(uuid.uuid4())


# ---------------------------------------------------------------------------
# Request / accept
# ---------------------------------------------------------------------------


class TestRequestAccept:
    def test_happy_path(
        self, service: FriendService, pg_sessionmaker: sessionmaker[Session]
    ) -> None:
        a = _seed_user(pg_sessionmaker)
        b = _seed_user(pg_sessionmaker)
        code_b = service.friend_code_for(b)

        friendship = service.request(a, code_b)
        assert friendship.status == FriendshipStatus.pending
        assert friendship.requester_id == a
        assert friendship.addressee_id == b

        accepted = service.accept(b, friendship.id)
        assert accepted.status == FriendshipStatus.accepted
        assert accepted.responded_at is not None

    def test_crossed_requests_resolve_to_one_accepted_row(
        self, service: FriendService, pg_sessionmaker: sessionmaker[Session]
    ) -> None:
        """Both press "add" before seeing the other's request -> one accepted row."""
        a = _seed_user(pg_sessionmaker)
        b = _seed_user(pg_sessionmaker)
        code_a = service.friend_code_for(a)
        code_b = service.friend_code_for(b)

        first = service.request(a, code_b)
        assert first.status == FriendshipStatus.pending

        second = service.request(b, code_a)
        assert second.status == FriendshipStatus.accepted
        assert second.id == first.id  # the same row, not a new one

        with pg_sessionmaker() as session:
            count = session.scalar(
                select(sa.func.count())
                .select_from(Friendship)
                .where(
                    sa.or_(
                        sa.and_(Friendship.requester_id == a, Friendship.addressee_id == b),
                        sa.and_(Friendship.requester_id == b, Friendship.addressee_id == a),
                    )
                )
            )
        assert count == 1

    def test_self_request_via_own_code_raises(
        self, service: FriendService, pg_sessionmaker: sessionmaker[Session]
    ) -> None:
        a = _seed_user(pg_sessionmaker)
        code_a = service.friend_code_for(a)
        with pytest.raises(FriendSelfRequestError):
            service.request(a, code_a)

    def test_duplicate_outgoing_request_raises(
        self, service: FriendService, pg_sessionmaker: sessionmaker[Session]
    ) -> None:
        a = _seed_user(pg_sessionmaker)
        b = _seed_user(pg_sessionmaker)
        code_b = service.friend_code_for(b)
        service.request(a, code_b)
        with pytest.raises(FriendAlreadyExistsError):
            service.request(a, code_b)

    def test_request_when_already_accepted_raises(
        self, service: FriendService, pg_sessionmaker: sessionmaker[Session]
    ) -> None:
        a = _seed_user(pg_sessionmaker)
        b = _seed_user(pg_sessionmaker)
        code_b = service.friend_code_for(b)
        friendship = service.request(a, code_b)
        service.accept(b, friendship.id)
        with pytest.raises(FriendAlreadyExistsError):
            service.request(a, code_b)

    def test_unknown_code_raises(
        self, service: FriendService, pg_sessionmaker: sessionmaker[Session]
    ) -> None:
        a = _seed_user(pg_sessionmaker)
        with pytest.raises(FriendCodeNotFoundError):
            service.request(a, "ZZZZZZZZ")

    def test_requester_cannot_accept_own_request(
        self, service: FriendService, pg_sessionmaker: sessionmaker[Session]
    ) -> None:
        a = _seed_user(pg_sessionmaker)
        b = _seed_user(pg_sessionmaker)
        code_b = service.friend_code_for(b)
        friendship = service.request(a, code_b)
        with pytest.raises(FriendRequestNotFoundError):
            service.accept(a, friendship.id)

    def test_stranger_and_requester_get_the_same_error(
        self, service: FriendService, pg_sessionmaker: sessionmaker[Session]
    ) -> None:
        """The requester-accepting-own-request error must be indistinguishable
        from a total stranger's (no existence oracle)."""
        a = _seed_user(pg_sessionmaker)
        b = _seed_user(pg_sessionmaker)
        stranger = _seed_user(pg_sessionmaker)
        code_b = service.friend_code_for(b)
        friendship = service.request(a, code_b)

        requester_exc: type[Exception] | None = None
        try:
            service.accept(a, friendship.id)
        except FriendRequestNotFoundError as exc:
            requester_exc = type(exc)

        stranger_exc: type[Exception] | None = None
        try:
            service.accept(stranger, friendship.id)
        except FriendRequestNotFoundError as exc:
            stranger_exc = type(exc)

        assert requester_exc is stranger_exc is FriendRequestNotFoundError

    def test_accepting_already_accepted_raises_not_pending(
        self, service: FriendService, pg_sessionmaker: sessionmaker[Session]
    ) -> None:
        a = _seed_user(pg_sessionmaker)
        b = _seed_user(pg_sessionmaker)
        code_b = service.friend_code_for(b)
        friendship = service.request(a, code_b)
        service.accept(b, friendship.id)
        with pytest.raises(FriendNotPendingError):
            service.accept(b, friendship.id)


# ---------------------------------------------------------------------------
# Database-level structural guarantees (migration 0015)
# ---------------------------------------------------------------------------


class TestStructuralGuarantees:
    def test_unique_pair_index_rejects_reciprocal_insert(
        self, pg_sessionmaker: sessionmaker[Session]
    ) -> None:
        a = _seed_user(pg_sessionmaker)
        b = _seed_user(pg_sessionmaker)
        low, high = (a, b) if a < b else (b, a)
        with pg_sessionmaker() as session:
            session.add(
                Friendship(
                    requester_id=a,
                    addressee_id=b,
                    status=FriendshipStatus.pending,
                    pair_low=low,
                    pair_high=high,
                )
            )
            session.commit()

        with pg_sessionmaker() as session:
            session.add(
                Friendship(
                    requester_id=b,
                    addressee_id=a,
                    status=FriendshipStatus.pending,
                    pair_low=low,
                    pair_high=high,
                )
            )
            with pytest.raises(IntegrityError):
                session.commit()

    def test_no_self_check_rejects_matching_parties(
        self, pg_sessionmaker: sessionmaker[Session]
    ) -> None:
        a = _seed_user(pg_sessionmaker)
        with pg_sessionmaker() as session:
            session.add(
                Friendship(
                    requester_id=a,
                    addressee_id=a,
                    status=FriendshipStatus.pending,
                    pair_low=a,
                    pair_high=a,
                )
            )
            with pytest.raises(IntegrityError):
                session.commit()

    def test_pair_ordered_check_rejects_reversed_pair(
        self, pg_sessionmaker: sessionmaker[Session]
    ) -> None:
        a = _seed_user(pg_sessionmaker)
        b = _seed_user(pg_sessionmaker)
        low, high = (a, b) if a < b else (b, a)
        with pg_sessionmaker() as session:
            session.add(
                Friendship(
                    requester_id=a,
                    addressee_id=b,
                    status=FriendshipStatus.pending,
                    pair_low=high,
                    pair_high=low,  # reversed
                )
            )
            with pytest.raises(IntegrityError):
                session.commit()

    def test_pair_matches_parties_check_rejects_unrelated_pair(
        self, pg_sessionmaker: sessionmaker[Session]
    ) -> None:
        a = _seed_user(pg_sessionmaker)
        b = _seed_user(pg_sessionmaker)
        c = _seed_user(pg_sessionmaker)
        low, high = (a, c) if a < c else (c, a)  # does not match requester/addressee (a, b)
        with pg_sessionmaker() as session:
            session.add(
                Friendship(
                    requester_id=a,
                    addressee_id=b,
                    status=FriendshipStatus.pending,
                    pair_low=low,
                    pair_high=high,
                )
            )
            with pytest.raises(IntegrityError):
                session.commit()


# ---------------------------------------------------------------------------
# remove()
# ---------------------------------------------------------------------------


class TestRemove:
    def test_addressee_can_decline_pending(
        self, service: FriendService, pg_sessionmaker: sessionmaker[Session]
    ) -> None:
        a = _seed_user(pg_sessionmaker)
        b = _seed_user(pg_sessionmaker)
        friendship = service.request(a, service.friend_code_for(b))
        service.remove(b, friendship.id)
        with pg_sessionmaker() as session:
            assert session.get(Friendship, friendship.id) is None

    def test_requester_can_cancel_pending(
        self, service: FriendService, pg_sessionmaker: sessionmaker[Session]
    ) -> None:
        a = _seed_user(pg_sessionmaker)
        b = _seed_user(pg_sessionmaker)
        friendship = service.request(a, service.friend_code_for(b))
        service.remove(a, friendship.id)
        with pg_sessionmaker() as session:
            assert session.get(Friendship, friendship.id) is None

    def test_either_party_can_unfriend_accepted(
        self, service: FriendService, pg_sessionmaker: sessionmaker[Session]
    ) -> None:
        a = _seed_user(pg_sessionmaker)
        b = _seed_user(pg_sessionmaker)
        friendship = service.request(a, service.friend_code_for(b))
        service.accept(b, friendship.id)
        service.remove(b, friendship.id)
        with pg_sessionmaker() as session:
            assert session.get(Friendship, friendship.id) is None

    def test_non_party_remove_raises_and_leaves_row_intact(
        self, service: FriendService, pg_sessionmaker: sessionmaker[Session]
    ) -> None:
        a = _seed_user(pg_sessionmaker)
        b = _seed_user(pg_sessionmaker)
        stranger = _seed_user(pg_sessionmaker)
        friendship = service.request(a, service.friend_code_for(b))

        with pytest.raises(FriendRequestNotFoundError):
            service.remove(stranger, friendship.id)

        with pg_sessionmaker() as session:
            row = session.get(Friendship, friendship.id)
            assert row is not None
            assert row.status == FriendshipStatus.pending

    def test_re_request_after_removal_succeeds(
        self, service: FriendService, pg_sessionmaker: sessionmaker[Session]
    ) -> None:
        a = _seed_user(pg_sessionmaker)
        b = _seed_user(pg_sessionmaker)
        code_b = service.friend_code_for(b)
        first = service.request(a, code_b)
        service.remove(a, first.id)

        second = service.request(a, code_b)
        assert second.id != first.id
        assert second.status == FriendshipStatus.pending


# ---------------------------------------------------------------------------
# list_friends()
# ---------------------------------------------------------------------------


class TestListFriends:
    def test_returns_lifetime_xp_and_current_streak(
        self, service: FriendService, pg_sessionmaker: sessionmaker[Session]
    ) -> None:
        a = _seed_user(pg_sessionmaker)
        b = _seed_user(pg_sessionmaker)
        friendship = service.request(a, service.friend_code_for(b))
        service.accept(b, friendship.id)

        _award(pg_sessionmaker, b, 50, date(2026, 7, 1))
        _award(pg_sessionmaker, b, 30, date(2026, 8, 5))  # lifetime: no window
        _set_streak(pg_sessionmaker, b, 7)

        friends = service.list_friends(a)
        assert len(friends) == 1
        summary = friends[0]
        assert summary.user_id == b
        assert summary.xp == 80
        assert summary.streak == 7
        assert summary.opted_out is False
        assert summary.friends_since is not None

    def test_opted_out_friend_stays_visible_with_hidden_numbers(
        self, service: FriendService, pg_sessionmaker: sessionmaker[Session]
    ) -> None:
        a = _seed_user(pg_sessionmaker)
        b = _seed_user(pg_sessionmaker)
        friendship = service.request(a, service.friend_code_for(b))
        service.accept(b, friendship.id)
        _award(pg_sessionmaker, b, 100, date(2026, 8, 5))
        _opt_out(pg_sessionmaker, b, opted_out=True)

        friends = service.list_friends(a)
        assert len(friends) == 1
        summary = friends[0]
        assert summary.opted_out is True
        assert summary.xp is None
        assert summary.streak is None

    def test_pending_request_not_in_list_friends(
        self, service: FriendService, pg_sessionmaker: sessionmaker[Session]
    ) -> None:
        a = _seed_user(pg_sessionmaker)
        b = _seed_user(pg_sessionmaker)
        service.request(a, service.friend_code_for(b))
        assert service.list_friends(a) == []
        assert service.list_friends(b) == []

    def test_pending_incoming_and_outgoing(
        self, service: FriendService, pg_sessionmaker: sessionmaker[Session]
    ) -> None:
        a = _seed_user(pg_sessionmaker)
        b = _seed_user(pg_sessionmaker)
        friendship = service.request(a, service.friend_code_for(b))

        outgoing = service.pending_outgoing(a)
        assert len(outgoing) == 1
        assert outgoing[0].user_id == b
        assert outgoing[0].friendship_id == friendship.id

        incoming = service.pending_incoming(b)
        assert len(incoming) == 1
        assert incoming[0].user_id == a
        assert incoming[0].friendship_id == friendship.id

        assert service.pending_incoming(a) == []
        assert service.pending_outgoing(b) == []

    def test_friend_ids_returns_accepted_counterparties(
        self, service: FriendService, pg_sessionmaker: sessionmaker[Session]
    ) -> None:
        a = _seed_user(pg_sessionmaker)
        b = _seed_user(pg_sessionmaker)
        c = _seed_user(pg_sessionmaker)
        friendship = service.request(a, service.friend_code_for(b))
        service.accept(b, friendship.id)
        service.request(a, service.friend_code_for(c))  # still pending

        ids = service.friend_ids(a)
        assert ids == [b]


# ---------------------------------------------------------------------------
# D5.5 regression: no email leaks through a display name
# ---------------------------------------------------------------------------


class TestNoEmailLeak:
    def test_no_at_sign_in_any_display_name(
        self, service: FriendService, pg_sessionmaker: sessionmaker[Session]
    ) -> None:
        a = _seed_user(pg_sessionmaker)
        b = _seed_user(pg_sessionmaker)  # no display_name set
        c = _seed_user(pg_sessionmaker)
        friendship = service.request(a, service.friend_code_for(b))
        service.accept(b, friendship.id)
        service.request(a, service.friend_code_for(c))

        for friend in service.list_friends(a):
            assert "@" not in friend.display_name
        for req in service.pending_outgoing(a):
            assert "@" not in req.display_name
        for req in service.pending_incoming(c):
            assert "@" not in req.display_name
