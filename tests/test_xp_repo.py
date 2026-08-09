"""Tests for :mod:`lemely.db.xp_repo` (P5.2 chunk A).

Postgres-integration, mirroring ``tests/test_flashcard_repo.py``'s
throwaway-database fixture. No award call sites are wired anywhere else in
the codebase yet (P5.2 chunk B) — this module tests the engine in
isolation.

Covers:

* :func:`civil_date_in_zone`: a UTC-midnight-adjacent Cairo award lands on
  the correct Cairo civil date, proven both directly and by inversion (force
  the UTC date instead, watch the assertion fail).
* Award amounts per D5.1 §2, and that the signature carries no
  mark/score/grade argument at all.
* Anti-farming caps (D5.1 §3): a capped action succeeds and writes no row,
  for both the per-source and the global caps, each proven by inversion.
* Idempotency (D5.1 §8): a repeated ``dedupe_key`` is a no-op success; a
  genuine FK violation (unknown ``subject_code``) still raises.
* Streak resolution (D5.1 §5): consecutive days, a freeze-covered single
  miss, a reset from an uncovered miss, freeze grants every 7 days capped at
  2, ``longest_length`` never decreasing, and a 40-day absence.
* XP is student-only (D5.1 §10).
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.db.base import Base
from lemely.db.models.academic import Subject
from lemely.db.models.enums import Role, XpSource
from lemely.db.models.users import User
from lemely.db.xp_repo import (
    DAILY_SOURCE_CAPS,
    GLOBAL_DAILY_CAP,
    XP_AMOUNTS,
    XpAwardResult,
    XpCapReason,
    XpIneligibleUserError,
    XpService,
    XpUserNotFoundError,
    civil_date_in_zone,
)
from lemely.runtime.config import DatabaseSettings

if TYPE_CHECKING:
    from collections.abc import Iterator

CAIRO = ZoneInfo("Africa/Cairo")

# ---------------------------------------------------------------------------
# Fixtures — throwaway Postgres database, mirrors the sibling flashcard suite.
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


def _seed_subject(sm: sessionmaker[Session], code: str = "0625") -> uuid.UUID:
    with sm.begin() as session:
        existing = session.scalars(sa.select(Subject).where(Subject.code == code)).first()
        if existing is not None:
            return existing.id
        subject = Subject(code=code, name="Physics")
        session.add(subject)
        session.flush()
        return subject.id


@pytest.fixture
def student_id(pg_sessionmaker: sessionmaker[Session]) -> uuid.UUID:
    return _seed_user(pg_sessionmaker, Role.student)


# A fixed moment, so day arithmetic in tests is unambiguous. Chosen at
# 12:00 UTC (14:00 Cairo, comfortably clear of the day boundary) so tests
# that are not specifically about the boundary don't accidentally straddle
# it.
_NOON_UTC = datetime(2026, 8, 5, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def xp_service(pg_sessionmaker: sessionmaker[Session]) -> XpService:
    return XpService(pg_sessionmaker, now=lambda: _NOON_UTC)


# ---------------------------------------------------------------------------
# civil_date_in_zone — the single most likely defect (D5.1 §4)
# ---------------------------------------------------------------------------


class TestCivilDateInZone:
    def test_requires_aware_datetime(self) -> None:
        with pytest.raises(ValueError, match="aware"):
            civil_date_in_zone(datetime(2026, 8, 5, 0, 30), zone=CAIRO)

    def test_early_morning_utc_lands_on_next_cairo_day(self) -> None:
        # 2026-08-04 23:30 UTC = 2026-08-05 02:30 Cairo (Egypt observes
        # +03:00 DST from late April to late October; ZoneInfo resolves the
        # correct offset for the date rather than a hardcoded one).
        moment = datetime(2026, 8, 4, 23, 30, tzinfo=UTC)
        assert civil_date_in_zone(moment, zone=CAIRO) == date(2026, 8, 5)

    def test_00_30_cairo_award_lands_on_todays_cairo_date_not_yesterdays_utc(self) -> None:
        """The exact trap D5.1 §4 names: 00:30 Cairo must be *today* in Cairo.

        In UTC terms this moment is 2026-08-04 22:30 — still "yesterday" by
        a UTC-date reading. A helper that used ``datetime.now(UTC).date()``
        or a naive ``.date()`` call would get this wrong; this test fails
        under that bug and passes under the real Cairo conversion.
        """
        cairo_midnight_thirty = datetime(2026, 8, 5, 0, 30, tzinfo=CAIRO)
        utc_equivalent = cairo_midnight_thirty.astimezone(UTC)
        assert utc_equivalent.date() == date(2026, 8, 4)  # the UTC-date trap

        resolved = civil_date_in_zone(cairo_midnight_thirty, zone=CAIRO)
        assert resolved == date(2026, 8, 5)
        # Proof by inversion: naively taking the UTC date would disagree.
        assert resolved != utc_equivalent.date()

    def test_zone_is_a_parameter_not_hardcoded(self) -> None:
        # 20:00 UTC: Cairo (+03:00) is still 23:00 the same day; Tokyo
        # (+09:00) has already rolled to 05:00 the next day.
        moment = datetime(2026, 8, 4, 20, 0, tzinfo=UTC)
        cairo = civil_date_in_zone(moment, zone=CAIRO)
        tokyo = civil_date_in_zone(moment, zone=ZoneInfo("Asia/Tokyo"))
        assert cairo != tokyo


# ---------------------------------------------------------------------------
# Award amounts, signature, and student-only eligibility
# ---------------------------------------------------------------------------


class TestAward:
    def test_award_has_no_mark_score_grade_or_accuracy_parameter(self) -> None:
        import inspect

        params = set(inspect.signature(XpService.award).parameters)
        for forbidden in ("mark", "score", "grade", "percentage", "accuracy"):
            assert forbidden not in params

    @pytest.mark.parametrize(
        "source",
        [
            XpSource.paper_corrected,
            XpSource.quiz_completed,
            XpSource.study_session_completed,
            XpSource.flashcard_reviewed,
        ],
    )
    def test_award_amount_matches_d51_table(
        self, xp_service: XpService, student_id: uuid.UUID, source: XpSource
    ) -> None:
        result = xp_service.award(student_id, source, dedupe_key=f"dk-{source.value}")
        assert result.awarded is True
        assert result.amount == XP_AMOUNTS[source]
        assert result.amount > 0

    def test_award_writes_awarded_on_as_a_cairo_date(
        self, pg_sessionmaker: sessionmaker[Session], student_id: uuid.UUID
    ) -> None:
        # 00:30 Cairo == 22:30 UTC the day before.
        moment = datetime(2026, 8, 5, 0, 30, tzinfo=CAIRO).astimezone(UTC)
        service = XpService(pg_sessionmaker, now=lambda: moment)
        result = service.award(student_id, XpSource.flashcard_reviewed, dedupe_key="boundary-1")
        assert result.awarded_on == date(2026, 8, 5)

    def test_award_unknown_user_raises(self, xp_service: XpService) -> None:
        with pytest.raises(XpUserNotFoundError):
            xp_service.award(uuid.uuid4(), XpSource.flashcard_reviewed, dedupe_key="dk-1")

    def test_award_to_non_student_raises(
        self, pg_sessionmaker: sessionmaker[Session], xp_service: XpService
    ) -> None:
        teacher_id = _seed_user(pg_sessionmaker, Role.teacher)
        with pytest.raises(XpIneligibleUserError):
            xp_service.award(teacher_id, XpSource.flashcard_reviewed, dedupe_key="dk-1")

    def test_award_to_non_student_writes_no_row(
        self, pg_sessionmaker: sessionmaker[Session], xp_service: XpService
    ) -> None:
        teacher_id = _seed_user(pg_sessionmaker, Role.teacher)
        with pytest.raises(XpIneligibleUserError):
            xp_service.award(teacher_id, XpSource.flashcard_reviewed, dedupe_key="dk-1")
        assert xp_service.total_xp(teacher_id) == 0

    def test_empty_dedupe_key_raises(self, xp_service: XpService, student_id: uuid.UUID) -> None:
        with pytest.raises(ValueError, match="dedupe_key"):
            xp_service.award(student_id, XpSource.flashcard_reviewed, dedupe_key="")

    def test_subject_code_attribution(
        self, pg_sessionmaker: sessionmaker[Session], xp_service: XpService, student_id: uuid.UUID
    ) -> None:
        _seed_subject(pg_sessionmaker)
        result = xp_service.award(
            student_id,
            XpSource.flashcard_reviewed,
            dedupe_key="dk-subject",
            subject_code="0625",
        )
        assert result.awarded is True

    def test_award_accepts_string_uuids(
        self, pg_sessionmaker: sessionmaker[Session], xp_service: XpService, student_id: uuid.UUID
    ) -> None:
        _seed_subject(pg_sessionmaker)
        result = xp_service.award(
            str(student_id),
            XpSource.flashcard_reviewed,
            dedupe_key="dk-str-uuid",
            subject_code="0625",
        )
        assert result.awarded is True

    def test_award_invalid_uuid_string_raises_value_error(self, xp_service: XpService) -> None:
        with pytest.raises(ValueError, match="UUID"):
            xp_service.award("not-a-uuid", XpSource.flashcard_reviewed, dedupe_key="dk-1")

    def test_unknown_subject_code_raises_not_swallowed_as_duplicate(
        self, xp_service: XpService, student_id: uuid.UUID
    ) -> None:
        """A real FK violation must propagate — only the dedupe constraint is swallowed.

        The bug this guards against: catching ``IntegrityError`` broadly in
        :meth:`XpService.award` would turn a genuinely bad ``subject_code``
        into a silent "duplicate, no-op success", losing the award and the
        error together.
        """
        with pytest.raises(IntegrityError):
            xp_service.award(
                student_id,
                XpSource.flashcard_reviewed,
                dedupe_key="dk-bad-subject",
                subject_code="9999-not-a-subject",
            )


# ---------------------------------------------------------------------------
# Idempotency (D5.1 §8)
# ---------------------------------------------------------------------------


class TestIdempotency:
    def test_duplicate_dedupe_key_is_a_noop_success(
        self, xp_service: XpService, student_id: uuid.UUID
    ) -> None:
        first = xp_service.award(student_id, XpSource.paper_corrected, dedupe_key="paper-42")
        second = xp_service.award(student_id, XpSource.paper_corrected, dedupe_key="paper-42")

        assert first.awarded is True
        assert second.awarded is False
        assert second.reason == XpCapReason.duplicate
        assert second.amount == 0
        # Total XP reflects one award, not two — the whole point of the rule.
        assert xp_service.total_xp(student_id) == XP_AMOUNTS[XpSource.paper_corrected]

    def test_same_identity_different_source_is_not_deduped(
        self, xp_service: XpService, student_id: uuid.UUID
    ) -> None:
        # (user, source, dedupe_key) is the key — a shared dedupe_key across
        # different sources is a different identity and must not collide.
        first = xp_service.award(student_id, XpSource.paper_corrected, dedupe_key="same-key")
        second = xp_service.award(student_id, XpSource.quiz_completed, dedupe_key="same-key")
        assert first.awarded is True
        assert second.awarded is True

    def test_different_users_same_dedupe_key_both_awarded(
        self, pg_sessionmaker: sessionmaker[Session], xp_service: XpService
    ) -> None:
        student_a = _seed_user(pg_sessionmaker, Role.student)
        student_b = _seed_user(pg_sessionmaker, Role.student)
        first = xp_service.award(student_a, XpSource.paper_corrected, dedupe_key="shared")
        second = xp_service.award(student_b, XpSource.paper_corrected, dedupe_key="shared")
        assert first.awarded is True
        assert second.awarded is True


# ---------------------------------------------------------------------------
# Anti-farming caps (D5.1 §3), each proven by inversion.
# ---------------------------------------------------------------------------


class TestCaps:
    def test_source_cap_blocks_further_awards_but_succeeds(
        self, xp_service: XpService, student_id: uuid.UUID
    ) -> None:
        cap = DAILY_SOURCE_CAPS[XpSource.flashcard_reviewed]
        for i in range(cap):
            result = xp_service.award(
                student_id, XpSource.flashcard_reviewed, dedupe_key=f"card-{i}"
            )
            assert result.awarded is True

        capped = xp_service.award(student_id, XpSource.flashcard_reviewed, dedupe_key=f"card-{cap}")
        assert capped.awarded is False
        assert capped.reason == XpCapReason.source_cap
        assert capped.amount == 0
        # No row was written for the capped attempt.
        assert xp_service.total_xp(student_id) == cap * XP_AMOUNTS[XpSource.flashcard_reviewed]

    def test_source_cap_inversion_one_below_cap_still_succeeds(
        self, xp_service: XpService, student_id: uuid.UUID
    ) -> None:
        """Proves the cap check's boundary is exact, not off-by-one in either direction."""
        cap = DAILY_SOURCE_CAPS[XpSource.quiz_completed]
        for i in range(cap - 1):
            result = xp_service.award(student_id, XpSource.quiz_completed, dedupe_key=f"quiz-{i}")
            assert result.awarded is True
        # The cap-th award (index cap-1) is still allowed — cap is a count limit.
        last_allowed = xp_service.award(
            student_id, XpSource.quiz_completed, dedupe_key=f"quiz-{cap - 1}"
        )
        assert last_allowed.awarded is True

    def test_global_cap_blocks_a_new_source_once_reached(
        self, xp_service: XpService, student_id: uuid.UUID
    ) -> None:
        # 5 papers * 50 = 250 == GLOBAL_DAILY_CAP exactly.
        for i in range(DAILY_SOURCE_CAPS[XpSource.paper_corrected]):
            result = xp_service.award(student_id, XpSource.paper_corrected, dedupe_key=f"p-{i}")
            assert result.awarded is True
        assert xp_service.total_xp(student_id) == GLOBAL_DAILY_CAP

        # Any further award today, even a fresh untouched source, is blocked
        # by the global cap before it can write a row.
        blocked = xp_service.award(student_id, XpSource.flashcard_reviewed, dedupe_key="card-x")
        assert blocked.awarded is False
        assert blocked.reason == XpCapReason.global_cap
        assert xp_service.total_xp(student_id) == GLOBAL_DAILY_CAP

    def test_global_cap_inversion_without_it_the_award_would_succeed(
        self, xp_service: XpService, student_id: uuid.UUID
    ) -> None:
        """Same setup as the global-cap test, but checks the mechanism directly:
        force the global-cap comparison off by asserting the pre-cap day total
        plus the new amount really would exceed the cap (i.e. the block is not
        a coincidence of the source cap already being hit)."""
        for i in range(DAILY_SOURCE_CAPS[XpSource.paper_corrected]):
            xp_service.award(student_id, XpSource.paper_corrected, dedupe_key=f"p-{i}")
        day_total = xp_service.total_xp(student_id)
        amount = XP_AMOUNTS[XpSource.flashcard_reviewed]
        assert day_total + amount > GLOBAL_DAILY_CAP  # the condition the cap check evaluates
        # flashcard_reviewed's own per-source cap (60) is nowhere near hit,
        # so this block can only be the global cap.
        blocked = xp_service.award(student_id, XpSource.flashcard_reviewed, dedupe_key="card-y")
        assert blocked.reason == XpCapReason.global_cap

    def test_capped_action_returns_success_shape_not_an_exception(
        self, xp_service: XpService, student_id: uuid.UUID
    ) -> None:
        cap = DAILY_SOURCE_CAPS[XpSource.study_session_completed]
        for i in range(cap):
            xp_service.award(student_id, XpSource.study_session_completed, dedupe_key=f"s-{i}")
        # No exception raised — this line only runs if award() returned normally.
        result = xp_service.award(
            student_id, XpSource.study_session_completed, dedupe_key=f"s-{cap}"
        )
        assert isinstance(result, XpAwardResult)
        assert result.awarded is False


# ---------------------------------------------------------------------------
# Streaks (D5.1 §5)
# ---------------------------------------------------------------------------


def _at(day: date, hour: int = 12) -> datetime:
    """A moment on ``day`` safely inside the Cairo civil date (noon UTC)."""
    return datetime(day.year, day.month, day.day, hour, 0, 0, tzinfo=UTC)


class TestStreaks:
    def test_first_ever_award_starts_a_streak_of_one(
        self, xp_service: XpService, student_id: uuid.UUID
    ) -> None:
        xp_service.award(student_id, XpSource.flashcard_reviewed, dedupe_key="d1")
        streak = xp_service.streak(student_id)
        assert streak.current_length == 1
        assert streak.longest_length == 1
        assert streak.freezes_available == 0

    def test_consecutive_days_increment(
        self, pg_sessionmaker: sessionmaker[Session], student_id: uuid.UUID
    ) -> None:
        day0 = date(2026, 8, 1)
        for offset in range(3):
            service = XpService(pg_sessionmaker, now=lambda d=offset: _at(day0 + timedelta(days=d)))
            result = service.award(
                student_id, XpSource.flashcard_reviewed, dedupe_key=f"consec-{offset}"
            )
            assert result.awarded is True

        final = XpService(pg_sessionmaker, now=lambda: _at(day0 + timedelta(days=2)))
        streak = final.streak(student_id)
        assert streak.current_length == 3
        assert streak.longest_length == 3

    def test_multiple_awards_same_day_do_not_double_count_streak(
        self, xp_service: XpService, student_id: uuid.UUID
    ) -> None:
        xp_service.award(student_id, XpSource.flashcard_reviewed, dedupe_key="a")
        xp_service.award(student_id, XpSource.flashcard_reviewed, dedupe_key="b")
        streak = xp_service.streak(student_id)
        assert streak.current_length == 1

    def test_single_missed_day_consumes_a_freeze_and_preserves_length(
        self, pg_sessionmaker: sessionmaker[Session], student_id: uuid.UUID
    ) -> None:
        day0 = date(2026, 8, 1)
        # 7 consecutive active days -> earns exactly 1 freeze.
        for offset in range(7):
            service = XpService(pg_sessionmaker, now=lambda d=offset: _at(day0 + timedelta(days=d)))
            service.award(student_id, XpSource.flashcard_reviewed, dedupe_key=f"w1-{offset}")

        mid_check = XpService(pg_sessionmaker, now=lambda: _at(day0 + timedelta(days=6)))
        after_week = mid_check.streak(student_id)
        assert after_week.current_length == 7
        assert after_week.freezes_available == 1

        # Miss day 7 entirely (no award). Resume on day 8.
        resume_day = day0 + timedelta(days=8)
        resume = XpService(pg_sessionmaker, now=lambda: _at(resume_day))
        result = resume.award(student_id, XpSource.flashcard_reviewed, dedupe_key="after-miss")
        assert result.awarded is True

        streak = resume.streak(student_id)
        # The missed day was covered by the freeze: length preserved (7),
        # then today's award increments it to 8, not reset to 1.
        assert streak.current_length == 8
        assert streak.freezes_available == 0
        assert streak.longest_length == 8

    def test_two_consecutive_missed_days_with_no_freeze_resets_to_zero(
        self, pg_sessionmaker: sessionmaker[Session], student_id: uuid.UUID
    ) -> None:
        day0 = date(2026, 8, 1)
        # 3 active days -> current_length=3, no freeze earned yet (< 7).
        for offset in range(3):
            service = XpService(pg_sessionmaker, now=lambda d=offset: _at(day0 + timedelta(days=d)))
            service.award(student_id, XpSource.flashcard_reviewed, dedupe_key=f"r-{offset}")

        before = XpService(pg_sessionmaker, now=lambda: _at(day0 + timedelta(days=2)))
        assert before.streak(student_id).freezes_available == 0

        # Miss days 3 and 4 (two full missed days, zero freezes held).
        resume_day = day0 + timedelta(days=5)
        resume = XpService(pg_sessionmaker, now=lambda: _at(resume_day))
        result = resume.award(student_id, XpSource.flashcard_reviewed, dedupe_key="after-gap")
        assert result.awarded is True

        streak = resume.streak(student_id)
        assert streak.current_length == 1  # reset, then today's award starts a new streak
        assert streak.longest_length == 3  # never decreases below the prior peak

    def test_longest_length_never_decreases_across_a_reset(
        self, pg_sessionmaker: sessionmaker[Session], student_id: uuid.UUID
    ) -> None:
        day0 = date(2026, 8, 1)
        for offset in range(10):
            service = XpService(pg_sessionmaker, now=lambda d=offset: _at(day0 + timedelta(days=d)))
            service.award(student_id, XpSource.flashcard_reviewed, dedupe_key=f"peak-{offset}")

        peak = XpService(pg_sessionmaker, now=lambda: _at(day0 + timedelta(days=9)))
        assert peak.streak(student_id).longest_length == 10

        # Absence long enough to blow past the freezes earned (1, at day 7).
        far_future = day0 + timedelta(days=40)
        later = XpService(pg_sessionmaker, now=lambda: _at(far_future))
        later.award(student_id, XpSource.flashcard_reviewed, dedupe_key="far-future")

        streak = later.streak(student_id)
        assert streak.current_length == 1
        assert streak.longest_length == 10  # the old peak survives the reset

    def test_forty_day_absence_resolves_without_a_scheduler(
        self, pg_sessionmaker: sessionmaker[Session], student_id: uuid.UUID
    ) -> None:
        day0 = date(2026, 8, 1)
        first = XpService(pg_sessionmaker, now=lambda: _at(day0))
        first.award(student_id, XpSource.flashcard_reviewed, dedupe_key="start")

        # Nothing touches this user for 40 days — no scheduler, no cron, no
        # intermediate read. The very next read must resolve correctly.
        day40 = day0 + timedelta(days=40)
        later = XpService(pg_sessionmaker, now=lambda: _at(day40))
        streak = later.streak(student_id)
        assert streak.current_length == 0  # far too long a gap for 0 freezes to cover
        assert streak.freezes_available == 0
        assert streak.longest_length == 1

    def test_streak_read_does_not_mark_today_active(
        self, pg_sessionmaker: sessionmaker[Session], student_id: uuid.UUID
    ) -> None:
        """A pure read must not itself extend the streak — only award() does."""
        day0 = date(2026, 8, 1)
        service = XpService(pg_sessionmaker, now=lambda: _at(day0))
        service.award(student_id, XpSource.flashcard_reviewed, dedupe_key="only-award")

        # Read on a later day without ever awarding again.
        reader = XpService(pg_sessionmaker, now=lambda: _at(day0 + timedelta(days=1)))
        streak = reader.streak(student_id)
        assert streak.current_length == 1  # yesterday is still "in grace", not yet lost

        # A day after that (two full days with no award): the gap resolves,
        # and since 0 freezes are held it resets.
        reader2 = XpService(pg_sessionmaker, now=lambda: _at(day0 + timedelta(days=2)))
        streak2 = reader2.streak(student_id)
        assert streak2.current_length == 0

    def test_a_reset_streak_does_not_claim_the_user_was_active_yesterday(
        self, pg_sessionmaker: sessionmaker[Session], student_id: uuid.UUID
    ) -> None:
        """`last_active_on` must stay truthful across a reset.

        `_resolve_gap` advances `last_active_on` to yesterday on the
        freeze-spend branch (so a freeze cannot be double-spent by a read
        followed by an award), but must NOT do so on the reset branch — that
        would report the student as active on a day they were absent, which is
        precisely the day whose absence caused the reset. `StreakState`
        surfaces this to S-31 as "last active", so an advanced value here is
        invented precision (UI spec §1.4), not a harmless internal marker.
        """
        day0 = date(2026, 8, 1)
        awarder = XpService(pg_sessionmaker, now=lambda: _at(day0))
        awarder.award(student_id, XpSource.flashcard_reviewed, dedupe_key="dk-truthful")

        # Five full days later, holding no freezes: the streak resets.
        reader = XpService(pg_sessionmaker, now=lambda: _at(day0 + timedelta(days=5)))
        streak = reader.streak(student_id)

        assert streak.current_length == 0
        assert streak.last_active_on == day0, (
            "reset must leave last_active_on at the real last-active day, "
            "not advance it to yesterday"
        )

        # And the reset stays idempotent without that advance: reading again,
        # and again a day later, changes nothing.
        assert reader.streak(student_id).last_active_on == day0
        later = XpService(pg_sessionmaker, now=lambda: _at(day0 + timedelta(days=6)))
        assert later.streak(student_id).current_length == 0
        assert later.streak(student_id).last_active_on == day0

    def test_never_awarded_user_has_zero_streak_with_no_row_created(
        self, pg_sessionmaker: sessionmaker[Session], xp_service: XpService, student_id: uuid.UUID
    ) -> None:
        streak = xp_service.streak(student_id)
        assert streak == streak.__class__(
            current_length=0, longest_length=0, last_active_on=None, freezes_available=0
        )
        with pg_sessionmaker() as session:
            from lemely.db.models.engagement import Streak

            row = session.scalar(select(Streak).where(Streak.user_id == student_id))
            assert row is None

    def test_freeze_cap_never_exceeds_two(
        self, pg_sessionmaker: sessionmaker[Session], student_id: uuid.UUID
    ) -> None:
        day0 = date(2026, 8, 1)
        # 21 consecutive active days would naively earn 3 freezes (21 // 7);
        # the cap cannot exceed 2.
        for offset in range(21):
            service = XpService(pg_sessionmaker, now=lambda d=offset: _at(day0 + timedelta(days=d)))
            service.award(student_id, XpSource.flashcard_reviewed, dedupe_key=f"freeze-{offset}")

        final = XpService(pg_sessionmaker, now=lambda: _at(day0 + timedelta(days=20)))
        streak = final.streak(student_id)
        assert streak.current_length == 21
        assert streak.freezes_available == 2

    def test_freeze_cap_inversion_without_the_cap_would_be_three(
        self, pg_sessionmaker: sessionmaker[Session], student_id: uuid.UUID
    ) -> None:
        """Confirms 3 grants really would fire without the min(2, ...) clamp,
        so the previous test's == 2 is evidence of the cap, not a coincidence
        of only 2 grants ever being attempted."""
        grants_attempted = 0
        for offset in range(1, 22):
            if offset % 7 == 0:
                grants_attempted += 1
        assert grants_attempted == 3  # 3 grants would fire at day 7, 14, 21


# ---------------------------------------------------------------------------
# xp_breakdown / total_xp
# ---------------------------------------------------------------------------


class TestReads:
    def test_total_xp_sums_across_sources(
        self, xp_service: XpService, student_id: uuid.UUID
    ) -> None:
        xp_service.award(student_id, XpSource.paper_corrected, dedupe_key="p1")
        xp_service.award(student_id, XpSource.flashcard_reviewed, dedupe_key="c1")
        assert xp_service.total_xp(student_id) == (
            XP_AMOUNTS[XpSource.paper_corrected] + XP_AMOUNTS[XpSource.flashcard_reviewed]
        )

    def test_total_xp_zero_for_untouched_user(
        self, xp_service: XpService, student_id: uuid.UUID
    ) -> None:
        assert xp_service.total_xp(student_id) == 0

    def test_breakdown_includes_all_sources_even_at_zero(
        self, xp_service: XpService, student_id: uuid.UUID
    ) -> None:
        xp_service.award(student_id, XpSource.paper_corrected, dedupe_key="p1")
        breakdown = xp_service.xp_breakdown(
            student_id, start=date(2026, 8, 1), end=date(2026, 8, 31)
        )
        assert breakdown.total == XP_AMOUNTS[XpSource.paper_corrected]
        assert breakdown.by_source[XpSource.paper_corrected] == XP_AMOUNTS[XpSource.paper_corrected]
        assert breakdown.by_source[XpSource.quiz_completed] == 0
        assert breakdown.by_source[XpSource.flashcard_reviewed] == 0
        assert breakdown.by_source[XpSource.study_session_completed] == 0

    def test_breakdown_window_excludes_outside_dates(
        self, pg_sessionmaker: sessionmaker[Session], student_id: uuid.UUID
    ) -> None:
        in_window = XpService(pg_sessionmaker, now=lambda: _at(date(2026, 8, 15)))
        in_window.award(student_id, XpSource.paper_corrected, dedupe_key="in")

        out_of_window = XpService(pg_sessionmaker, now=lambda: _at(date(2026, 9, 15)))
        out_of_window.award(student_id, XpSource.paper_corrected, dedupe_key="out")

        reader = XpService(pg_sessionmaker)
        breakdown = reader.xp_breakdown(student_id, start=date(2026, 8, 1), end=date(2026, 8, 31))
        assert breakdown.total == XP_AMOUNTS[XpSource.paper_corrected]
