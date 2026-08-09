"""Tests for :mod:`lemely.db.leaderboard_repo` (P5.3 chunk A).

Postgres-integration, mirroring ``tests/test_xp_repo.py``'s throwaway-database
fixture. XP rows are seeded directly as :class:`~lemely.db.models.engagement.XpEvent`
rows rather than through :class:`~lemely.db.xp_repo.XpService` — this module
tests the ranking query, not the award engine, and direct seeding lets a test
place an event on an exact Cairo civil date without fighting the award caps.

Covers:

* ``TestSqlGuard`` — D5.1 §0's control: the emitted SELECT never joins to a
  marking table, for every scope x basis combination.
* The Cairo week boundary (D5.1 §4/§6).
* Opt-out exclusion, including the missing-``student_profiles``-row case.
* Per-subject filtering (D5.1 §7/D5.2).
* Tie ranking (standard competition ranking).
* Own-row pinning, inside and outside the top-N, and for a zero-XP viewer.
* Class scope rejecting a class the viewer is not enrolled in.
* School scope when the viewer has no school.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.db.base import Base
from lemely.db.leaderboard_repo import (
    LeaderboardClassAccessError,
    LeaderboardScope,
    LeaderboardService,
    LeaderboardUnavailableReason,
    _membership_subquery,
    _ranked_subquery,
)
from lemely.db.models.academic import Subject
from lemely.db.models.engagement import XpEvent
from lemely.db.models.enums import FriendshipStatus, MembershipRole, Role, SeatStatus, XpSource
from lemely.db.models.orgs import ClassEnrollment, School, SchoolClass, SchoolMembership, Seat
from lemely.db.models.profiles import StudentProfile
from lemely.db.models.users import Friendship, User
from lemely.runtime.config import DatabaseSettings

if TYPE_CHECKING:
    from collections.abc import Iterator

CAIRO = ZoneInfo("Africa/Cairo")

# Marking tables the leaderboard query must never join to (D5.1 §0).
_FORBIDDEN_TABLES = ("attempts", "question_results", "papers", "weakness_records")

# ---------------------------------------------------------------------------
# Fixtures — throwaway Postgres database, mirrors the sibling XP suite.
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


def _seed_student(sm: sessionmaker[Session]) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=Role.student))
    return uid


def _seed_subject(sm: sessionmaker[Session], code: str = "0625") -> None:
    with sm.begin() as session:
        existing = session.scalar(sa.select(Subject).where(Subject.code == code))
        if existing is None:
            session.add(Subject(code=code, name="Physics"))


def _award(
    sm: sessionmaker[Session],
    user_id: uuid.UUID,
    amount: int,
    awarded_on: date,
    *,
    source: XpSource = XpSource.flashcard_reviewed,
    subject_code: str | None = None,
    dedupe_key: str | None = None,
) -> None:
    """Seed an XpEvent row directly — bypasses XpService's caps deliberately."""
    with sm.begin() as session:
        session.add(
            XpEvent(
                user_id=user_id,
                source=source,
                amount=amount,
                awarded_on=awarded_on,
                subject_code=subject_code,
                dedupe_key=dedupe_key or f"dk-{uuid.uuid4()}",
            )
        )


def _opt_out(sm: sessionmaker[Session], user_id: uuid.UUID, *, opted_out: bool = True) -> None:
    with sm.begin() as session:
        session.add(StudentProfile(user_id=user_id, leaderboard_opt_out=opted_out))


def _seed_school(sm: sessionmaker[Session]) -> uuid.UUID:
    school_id = uuid.uuid4()
    with sm.begin() as session:
        session.add(School(id=school_id, name="Test School"))
    return school_id


def _seed_seat(
    sm: sessionmaker[Session],
    school_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    status: SeatStatus = SeatStatus.assigned,
) -> None:
    with sm.begin() as session:
        session.add(Seat(school_id=school_id, assigned_user_id=user_id, status=status))


def _seed_class(sm: sessionmaker[Session], *, school_id: uuid.UUID | None = None) -> uuid.UUID:
    class_id = uuid.uuid4()
    teacher_id = uuid.uuid4()
    with sm.begin() as session:
        session.add(User(id=teacher_id, email=f"{teacher_id}@example.com", role=Role.teacher))
        session.flush()
        session.add(SchoolClass(id=class_id, school_id=school_id, teacher_id=teacher_id, name="9A"))
    return class_id


def _enrol(sm: sessionmaker[Session], class_id: uuid.UUID, student_id: uuid.UUID) -> None:
    with sm.begin() as session:
        session.add(ClassEnrollment(class_id=class_id, student_id=student_id))


def _befriend(
    sm: sessionmaker[Session],
    a: uuid.UUID,
    b: uuid.UUID,
    *,
    status: FriendshipStatus = FriendshipStatus.accepted,
) -> None:
    """Seed a friendship row directly, bypassing FriendService."""
    low, high = (a, b) if a < b else (b, a)
    with sm.begin() as session:
        session.add(
            Friendship(
                requester_id=a,
                addressee_id=b,
                status=status,
                pair_low=low,
                pair_high=high,
            )
        )


# A fixed moment (Cairo noon), clear of any day boundary.
_NOON_UTC = datetime(2026, 8, 5, 12, 0, 0, tzinfo=UTC)  # 2026-08-05 is a Wednesday


@pytest.fixture
def service(pg_sessionmaker: sessionmaker[Session]) -> LeaderboardService:
    return LeaderboardService(pg_sessionmaker, now=lambda: _NOON_UTC)


# ---------------------------------------------------------------------------
# The SQL guard (D5.1 §0's binding control)
# ---------------------------------------------------------------------------


class TestSqlGuard:
    """Compiles the actual emitted SELECT and asserts no marking-table join exists.

    Covers every scope x basis combination named in the brief, so a refactor
    that adds a marking join to only one path (e.g. only per-subject boards)
    is caught.
    """

    @staticmethod
    def _membership_for(scope: LeaderboardScope) -> sa.Select[tuple[uuid.UUID]] | None:
        return _membership_subquery(
            scope, class_id=uuid.uuid4(), school_id=uuid.uuid4(), viewer_id=uuid.uuid4()
        )

    @pytest.mark.parametrize("scope", list(LeaderboardScope))
    @pytest.mark.parametrize("subject_code", [None, "0625"])
    def test_no_join_to_any_marking_table(
        self, scope: LeaderboardScope, subject_code: str | None
    ) -> None:
        stmt = _ranked_subquery(
            window_start=date(2026, 8, 3),
            window_end=date(2026, 8, 9),
            subject_code=subject_code,
            membership=self._membership_for(scope),
        )
        compiled = str(stmt.compile(dialect=postgresql.dialect()))  # type: ignore[no-untyped-call]
        for forbidden in _FORBIDDEN_TABLES:
            assert forbidden not in compiled, (
                f"leaderboard query for scope={scope}, subject_code={subject_code} "
                f"joined to forbidden marking table {forbidden!r}:\n{compiled}"
            )


# ---------------------------------------------------------------------------
# The Cairo week boundary (D5.1 §4/§6) — the bug class this build guards against.
# ---------------------------------------------------------------------------


class TestCairoWeekBoundary:
    def test_23_30_sunday_cairo_and_00_30_monday_cairo_land_in_different_weeks(
        self, pg_sessionmaker: sessionmaker[Session]
    ) -> None:
        from lemely.db.xp_repo import civil_date_in_zone

        # Sunday 2026-08-09 23:30 Cairo -> still the week of 2026-08-03..09.
        sunday_2330_cairo = datetime(2026, 8, 9, 23, 30, tzinfo=CAIRO)
        sunday_cairo_date = civil_date_in_zone(sunday_2330_cairo.astimezone(UTC), zone=CAIRO)
        assert sunday_cairo_date == date(2026, 8, 9)

        # One moment later, 00:30 Monday Cairo -> the week of 2026-08-10..16.
        monday_0030_cairo = datetime(2026, 8, 10, 0, 30, tzinfo=CAIRO)
        monday_cairo_date = civil_date_in_zone(monday_0030_cairo.astimezone(UTC), zone=CAIRO)
        assert monday_cairo_date == date(2026, 8, 10)

        # Seed one event landing on the last day of the week-of-Aug-3, one
        # landing on the first day of the week-of-Aug-10, and confirm each is
        # visible only in its own week.
        student_a = _seed_student(pg_sessionmaker)
        student_b = _seed_student(pg_sessionmaker)
        _award(pg_sessionmaker, student_a, 10, sunday_cairo_date, dedupe_key="a-sun")
        _award(pg_sessionmaker, student_b, 10, monday_cairo_date, dedupe_key="b-mon")

        # A viewer reading "now" = Sunday 23:30 Cairo sees student_a's award
        # in-window and student_b's award (next week) excluded.
        viewer = _seed_student(pg_sessionmaker)
        svc_sunday = LeaderboardService(
            pg_sessionmaker, now=lambda: sunday_2330_cairo.astimezone(UTC)
        )
        board_sunday = svc_sunday.board(viewer, LeaderboardScope.global_)
        ids_sunday = {row.user_id for row in board_sunday.rows}
        assert student_a in ids_sunday
        assert student_b not in ids_sunday

        # A viewer reading "now" = Monday 00:30 Cairo (the very next moment)
        # sees the opposite: student_b in-window, student_a excluded (prior week).
        svc_monday = LeaderboardService(
            pg_sessionmaker, now=lambda: monday_0030_cairo.astimezone(UTC)
        )
        board_monday = svc_monday.board(viewer, LeaderboardScope.global_)
        ids_monday = {row.user_id for row in board_monday.rows}
        assert student_b in ids_monday
        assert student_a not in ids_monday


# ---------------------------------------------------------------------------
# Opt-out (D5.1 §9)
# ---------------------------------------------------------------------------


class TestOptOut:
    def test_opted_out_student_absent_from_every_board(
        self, pg_sessionmaker: sessionmaker[Session], service: LeaderboardService
    ) -> None:
        opted_out = _seed_student(pg_sessionmaker)
        _opt_out(pg_sessionmaker, opted_out, opted_out=True)
        _award(pg_sessionmaker, opted_out, 100, date(2026, 8, 5))

        viewer = _seed_student(pg_sessionmaker)
        result = service.board(viewer, LeaderboardScope.global_)
        assert opted_out not in {row.user_id for row in result.rows}

    def test_opted_out_viewer_sees_own_xp_but_no_rank(
        self, pg_sessionmaker: sessionmaker[Session], service: LeaderboardService
    ) -> None:
        viewer = _seed_student(pg_sessionmaker)
        _opt_out(pg_sessionmaker, viewer, opted_out=True)
        _award(pg_sessionmaker, viewer, 100, date(2026, 8, 5))

        result = service.board(viewer, LeaderboardScope.global_)
        assert result.viewer_opted_out is True
        assert result.viewer is not None
        assert result.viewer.xp == 100
        assert result.viewer.rank is None

    def test_missing_student_profile_row_still_appears_on_board(
        self, pg_sessionmaker: sessionmaker[Session], service: LeaderboardService
    ) -> None:
        """The trap: an outer join is required or a never-onboarded student vanishes."""
        student = _seed_student(pg_sessionmaker)  # deliberately: no StudentProfile row created
        _award(pg_sessionmaker, student, 50, date(2026, 8, 5))

        viewer = _seed_student(pg_sessionmaker)
        result = service.board(viewer, LeaderboardScope.global_)
        assert student in {row.user_id for row in result.rows}

    def test_opted_in_explicitly_appears_on_board(
        self, pg_sessionmaker: sessionmaker[Session], service: LeaderboardService
    ) -> None:
        student = _seed_student(pg_sessionmaker)
        _opt_out(pg_sessionmaker, student, opted_out=False)
        _award(pg_sessionmaker, student, 50, date(2026, 8, 5))

        viewer = _seed_student(pg_sessionmaker)
        result = service.board(viewer, LeaderboardScope.global_)
        assert student in {row.user_id for row in result.rows}


# ---------------------------------------------------------------------------
# Per-subject filtering (D5.1 §7/D5.2)
# ---------------------------------------------------------------------------


class TestSubjectFiltering:
    def test_per_subject_board_only_counts_that_subject(
        self, pg_sessionmaker: sessionmaker[Session], service: LeaderboardService
    ) -> None:
        _seed_subject(pg_sessionmaker, "0625")
        _seed_subject(pg_sessionmaker, "0580")
        student = _seed_student(pg_sessionmaker)
        _award(pg_sessionmaker, student, 40, date(2026, 8, 5), subject_code="0625", dedupe_key="p")
        _award(pg_sessionmaker, student, 30, date(2026, 8, 5), subject_code="0580", dedupe_key="m")

        viewer = _seed_student(pg_sessionmaker)
        physics_board = service.board(viewer, LeaderboardScope.global_, subject_code="0625")
        row = next(r for r in physics_board.rows if r.user_id == student)
        assert row.xp == 40

    def test_total_board_ignores_subject_and_sums_everything(
        self, pg_sessionmaker: sessionmaker[Session], service: LeaderboardService
    ) -> None:
        _seed_subject(pg_sessionmaker, "0625")
        _seed_subject(pg_sessionmaker, "0580")
        student = _seed_student(pg_sessionmaker)
        _award(pg_sessionmaker, student, 40, date(2026, 8, 5), subject_code="0625", dedupe_key="p")
        _award(pg_sessionmaker, student, 30, date(2026, 8, 5), subject_code="0580", dedupe_key="m")

        viewer = _seed_student(pg_sessionmaker)
        total_board = service.board(viewer, LeaderboardScope.global_, subject_code=None)
        row = next(r for r in total_board.rows if r.user_id == student)
        assert row.xp == 70


# ---------------------------------------------------------------------------
# Ranking: ties and own-row pinning
# ---------------------------------------------------------------------------


class TestRanking:
    def test_tied_students_get_equal_rank_and_next_rank_skips(
        self, pg_sessionmaker: sessionmaker[Session], service: LeaderboardService
    ) -> None:
        a = _seed_student(pg_sessionmaker)
        b = _seed_student(pg_sessionmaker)
        c = _seed_student(pg_sessionmaker)
        _award(pg_sessionmaker, a, 50, date(2026, 8, 5))
        _award(pg_sessionmaker, b, 50, date(2026, 8, 5))
        _award(pg_sessionmaker, c, 30, date(2026, 8, 5))

        viewer = _seed_student(pg_sessionmaker)
        result = service.board(viewer, LeaderboardScope.global_)
        by_id = {r.user_id: r for r in result.rows}
        assert by_id[a].rank == 1
        assert by_id[b].rank == 1
        assert by_id[c].rank == 3  # standard competition ranking: 1,1,3

    def test_zero_xp_student_is_never_ranked(
        self, pg_sessionmaker: sessionmaker[Session], service: LeaderboardService
    ) -> None:
        untouched = _seed_student(pg_sessionmaker)
        viewer = _seed_student(pg_sessionmaker)
        _award(pg_sessionmaker, viewer, 10, date(2026, 8, 5))

        result = service.board(viewer, LeaderboardScope.global_)
        assert untouched not in {row.user_id for row in result.rows}

    def test_viewer_with_zero_xp_gets_row_with_zero_xp_and_none_rank(
        self, pg_sessionmaker: sessionmaker[Session], service: LeaderboardService
    ) -> None:
        viewer = _seed_student(pg_sessionmaker)
        other = _seed_student(pg_sessionmaker)
        _award(pg_sessionmaker, other, 100, date(2026, 8, 5))

        result = service.board(viewer, LeaderboardScope.global_)
        assert result.viewer is not None
        assert result.viewer.xp == 0
        assert result.viewer.rank is None

    def test_own_row_pinned_inside_top_n(
        self, pg_sessionmaker: sessionmaker[Session], service: LeaderboardService
    ) -> None:
        viewer = _seed_student(pg_sessionmaker)
        _award(pg_sessionmaker, viewer, 100, date(2026, 8, 5))

        result = service.board(viewer, LeaderboardScope.global_, top_n=10)
        assert result.viewer is not None
        assert result.viewer.rank == 1
        assert result.viewer.xp == 100
        assert viewer in {row.user_id for row in result.rows}

    def test_own_row_pinned_outside_top_n(
        self, pg_sessionmaker: sessionmaker[Session], service: LeaderboardService
    ) -> None:
        viewer = _seed_student(pg_sessionmaker)
        _award(pg_sessionmaker, viewer, 1, date(2026, 8, 5))
        # Seed enough higher-scoring students to push the viewer outside top_n=2.
        for i in range(5):
            other = _seed_student(pg_sessionmaker)
            _award(pg_sessionmaker, other, 100 - i, date(2026, 8, 5))

        result = service.board(viewer, LeaderboardScope.global_, top_n=2)
        assert len(result.rows) == 2
        assert viewer not in {row.user_id for row in result.rows}
        assert result.viewer is not None
        assert result.viewer.rank == 6  # last of 6 ranked students
        assert result.viewer.xp == 1


# ---------------------------------------------------------------------------
# Class scope access control
# ---------------------------------------------------------------------------


class TestClassScope:
    def test_viewer_not_enrolled_in_class_is_rejected(
        self, pg_sessionmaker: sessionmaker[Session], service: LeaderboardService
    ) -> None:
        class_id = _seed_class(pg_sessionmaker)
        viewer = _seed_student(pg_sessionmaker)  # never enrolled
        with pytest.raises(LeaderboardClassAccessError):
            service.board(viewer, LeaderboardScope.class_, class_id=class_id)

    def test_enrolled_viewer_sees_class_board_restricted_to_classmates(
        self, pg_sessionmaker: sessionmaker[Session], service: LeaderboardService
    ) -> None:
        class_id = _seed_class(pg_sessionmaker)
        viewer = _seed_student(pg_sessionmaker)
        classmate = _seed_student(pg_sessionmaker)
        outsider = _seed_student(pg_sessionmaker)
        _enrol(pg_sessionmaker, class_id, viewer)
        _enrol(pg_sessionmaker, class_id, classmate)
        # outsider is NOT enrolled in this class.

        _award(pg_sessionmaker, viewer, 10, date(2026, 8, 5))
        _award(pg_sessionmaker, classmate, 20, date(2026, 8, 5))
        _award(pg_sessionmaker, outsider, 999, date(2026, 8, 5))

        result = service.board(viewer, LeaderboardScope.class_, class_id=class_id)
        ids = {row.user_id for row in result.rows}
        assert ids == {viewer, classmate}
        assert outsider not in ids

    def test_class_scope_without_class_id_raises_value_error(
        self, service: LeaderboardService, pg_sessionmaker: sessionmaker[Session]
    ) -> None:
        viewer = _seed_student(pg_sessionmaker)
        with pytest.raises(ValueError, match="class_id"):
            service.board(viewer, LeaderboardScope.class_)


# ---------------------------------------------------------------------------
# School scope
# ---------------------------------------------------------------------------


class TestSchoolScope:
    def test_viewer_with_no_school_is_unavailable(
        self, pg_sessionmaker: sessionmaker[Session], service: LeaderboardService
    ) -> None:
        viewer = _seed_student(pg_sessionmaker)  # no Seat anywhere
        result = service.board(viewer, LeaderboardScope.school)
        assert result.status == "unavailable"
        assert result.unavailable_reason == LeaderboardUnavailableReason.no_school
        assert result.rows == []
        assert result.viewer is None

    def test_viewer_with_school_sees_schoolmates_only(
        self, pg_sessionmaker: sessionmaker[Session], service: LeaderboardService
    ) -> None:
        school_id = _seed_school(pg_sessionmaker)
        other_school_id = _seed_school(pg_sessionmaker)
        viewer = _seed_student(pg_sessionmaker)
        schoolmate = _seed_student(pg_sessionmaker)
        outsider = _seed_student(pg_sessionmaker)
        _seed_seat(pg_sessionmaker, school_id, viewer)
        _seed_seat(pg_sessionmaker, school_id, schoolmate)
        _seed_seat(pg_sessionmaker, other_school_id, outsider)

        _award(pg_sessionmaker, viewer, 10, date(2026, 8, 5))
        _award(pg_sessionmaker, schoolmate, 20, date(2026, 8, 5))
        _award(pg_sessionmaker, outsider, 999, date(2026, 8, 5))

        result = service.board(viewer, LeaderboardScope.school)
        assert result.status == "ok"
        ids = {row.user_id for row in result.rows}
        assert ids == {viewer, schoolmate}
        assert outsider not in ids

    def test_revoked_seat_does_not_count_as_a_school(
        self, pg_sessionmaker: sessionmaker[Session], service: LeaderboardService
    ) -> None:
        school_id = _seed_school(pg_sessionmaker)
        viewer = _seed_student(pg_sessionmaker)
        _seed_seat(pg_sessionmaker, school_id, viewer, status=SeatStatus.revoked)

        result = service.board(viewer, LeaderboardScope.school)
        assert result.status == "unavailable"


# ---------------------------------------------------------------------------
# Friends scope (P5.4 chunk A)
# ---------------------------------------------------------------------------


class TestFriendsScope:
    def test_friends_board_ranks_viewer_plus_accepted_friends_only(
        self, pg_sessionmaker: sessionmaker[Session], service: LeaderboardService
    ) -> None:
        viewer = _seed_student(pg_sessionmaker)
        friend = _seed_student(pg_sessionmaker)
        stranger = _seed_student(pg_sessionmaker)
        _befriend(pg_sessionmaker, viewer, friend)

        _award(pg_sessionmaker, viewer, 10, date(2026, 8, 5))
        _award(pg_sessionmaker, friend, 20, date(2026, 8, 5))
        _award(pg_sessionmaker, stranger, 999, date(2026, 8, 5))

        result = service.board(viewer, LeaderboardScope.friends)
        ids = {row.user_id for row in result.rows}
        assert ids == {viewer, friend}
        assert stranger not in ids

    def test_friends_board_includes_viewer_with_zero_friends(
        self, pg_sessionmaker: sessionmaker[Session], service: LeaderboardService
    ) -> None:
        viewer = _seed_student(pg_sessionmaker)
        _award(pg_sessionmaker, viewer, 5, date(2026, 8, 5))

        result = service.board(viewer, LeaderboardScope.friends)
        assert result.status == "ok"
        ids = {row.user_id for row in result.rows}
        assert ids == {viewer}

    def test_friends_board_excludes_pending_request(
        self, pg_sessionmaker: sessionmaker[Session], service: LeaderboardService
    ) -> None:
        viewer = _seed_student(pg_sessionmaker)
        pending_friend = _seed_student(pg_sessionmaker)
        _befriend(pg_sessionmaker, viewer, pending_friend, status=FriendshipStatus.pending)
        _award(pg_sessionmaker, pending_friend, 50, date(2026, 8, 5))

        result = service.board(viewer, LeaderboardScope.friends)
        ids = {row.user_id for row in result.rows}
        assert pending_friend not in ids

    def test_friends_board_excludes_opted_out_friend(
        self, pg_sessionmaker: sessionmaker[Session], service: LeaderboardService
    ) -> None:
        viewer = _seed_student(pg_sessionmaker)
        opted_out_friend = _seed_student(pg_sessionmaker)
        _befriend(pg_sessionmaker, viewer, opted_out_friend)
        _opt_out(pg_sessionmaker, opted_out_friend, opted_out=True)
        _award(pg_sessionmaker, opted_out_friend, 50, date(2026, 8, 5))

        result = service.board(viewer, LeaderboardScope.friends)
        ids = {row.user_id for row in result.rows}
        assert opted_out_friend not in ids

    def test_friends_board_works_regardless_of_request_direction(
        self, pg_sessionmaker: sessionmaker[Session], service: LeaderboardService
    ) -> None:
        """The viewer may be either the requester or the addressee of the accepted row."""
        viewer = _seed_student(pg_sessionmaker)
        friend = _seed_student(pg_sessionmaker)
        # friend is the requester, viewer is the addressee.
        _befriend(pg_sessionmaker, friend, viewer)
        _award(pg_sessionmaker, friend, 30, date(2026, 8, 5))

        result = service.board(viewer, LeaderboardScope.friends)
        ids = {row.user_id for row in result.rows}
        assert friend in ids


# Silence "unused import" for models only referenced via SQLAlchemy metadata
# registration (SchoolMembership, MembershipRole) — imported so Base.metadata
# includes every table create_all needs, matching the sibling XP suite's style.
assert SchoolMembership is not None
assert MembershipRole is not None
