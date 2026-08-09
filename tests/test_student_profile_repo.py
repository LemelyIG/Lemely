"""Postgres integration tests for the student-profile service (P4.3 chunk B, D4.5).

Mirrors ``tests/test_notification_prefs_repo.py``'s shape: throwaway
Postgres database, skip cleanly when unreachable, one seed-helper block per
this repo's "every ``test_*_repo.py`` carries its own copy" convention.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.db.base import Base
from lemely.db.models import Subject, User
from lemely.db.models.enums import QualificationLevel, Role, SessionMonth
from lemely.db.student_profile_repo import (
    StudentProfileNotFoundError,
    StudentProfileService,
    StudentProfileValidationError,
)
from lemely.runtime.config import DatabaseSettings

if TYPE_CHECKING:
    from collections.abc import Iterator


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


# ── Seed helpers ────────────────────────────────────────────────────────────


def _seed_user(sm: sessionmaker[Session], role: Role = Role.student) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=role))
    return uid


def _seed_subject(sm: sessionmaker[Session], code: str = "0625") -> str:
    with sm.begin() as session:
        session.add(Subject(code=code, name="Physics"))
    return code


# ── get_or_create_profile ────────────────────────────────────────────────────


def test_get_or_create_profile_creates_bare_row(pg_sessionmaker: sessionmaker[Session]) -> None:
    user = _seed_user(pg_sessionmaker)
    service = StudentProfileService(pg_sessionmaker)

    row = service.get_or_create_profile(user)

    assert row.user_id == user
    assert row.qualification_level is None
    assert row.grade_level is None
    assert row.weekly_study_hours is None
    assert row.onboarding_completed_at is None


def test_get_or_create_profile_is_idempotent(pg_sessionmaker: sessionmaker[Session]) -> None:
    user = _seed_user(pg_sessionmaker)
    service = StudentProfileService(pg_sessionmaker)

    first = service.get_or_create_profile(user)
    service.update_profile(user, grade_level="Year 11")
    second = service.get_or_create_profile(user)

    assert first.user_id == second.user_id
    # The second call must not have reset the row created/updated by the
    # middle call — proving "creates on first call only".
    assert second.grade_level == "Year 11"


# ── update_profile: PATCH semantics ──────────────────────────────────────────


def test_update_profile_partial_update_leaves_other_fields_untouched(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    user = _seed_user(pg_sessionmaker)
    service = StudentProfileService(pg_sessionmaker)

    service.update_profile(
        user,
        qualification_level=QualificationLevel.igcse,
        grade_level="Year 11",
        weekly_study_hours=10,
    )
    updated = service.update_profile(user, weekly_study_hours=15)

    assert updated.weekly_study_hours == 15
    assert updated.qualification_level is QualificationLevel.igcse
    assert updated.grade_level == "Year 11"


def test_update_profile_explicit_none_clears_field(pg_sessionmaker: sessionmaker[Session]) -> None:
    user = _seed_user(pg_sessionmaker)
    service = StudentProfileService(pg_sessionmaker)

    service.update_profile(user, school_name="Cairo British School")
    cleared = service.update_profile(user, school_name=None)

    assert cleared.school_name is None


def test_update_profile_accepts_qualification_level_as_string(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    user = _seed_user(pg_sessionmaker)
    service = StudentProfileService(pg_sessionmaker)

    row = service.update_profile(user, qualification_level="a_level")

    assert row.qualification_level is QualificationLevel.a_level


def test_update_profile_unknown_qualification_level_string_raises_validation_error(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    user = _seed_user(pg_sessionmaker)
    service = StudentProfileService(pg_sessionmaker)

    with pytest.raises(StudentProfileValidationError):
        service.update_profile(user, qualification_level="not-a-real-level")


@pytest.mark.parametrize("hours", [-1, 81, 1000])
def test_update_profile_weekly_study_hours_out_of_range_raises_validation_error(
    pg_sessionmaker: sessionmaker[Session], hours: int
) -> None:
    user = _seed_user(pg_sessionmaker)
    service = StudentProfileService(pg_sessionmaker)

    with pytest.raises(StudentProfileValidationError):
        service.update_profile(user, weekly_study_hours=hours)


@pytest.mark.parametrize("hours", [0, 40, 80])
def test_update_profile_weekly_study_hours_boundary_values_accepted(
    pg_sessionmaker: sessionmaker[Session], hours: int
) -> None:
    user = _seed_user(pg_sessionmaker)
    service = StudentProfileService(pg_sessionmaker)

    row = service.update_profile(user, weekly_study_hours=hours)

    assert row.weekly_study_hours == hours


def test_update_profile_has_external_lessons_tristate(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    user = _seed_user(pg_sessionmaker)
    service = StudentProfileService(pg_sessionmaker)

    fresh = service.get_or_create_profile(user)
    assert fresh.has_external_lessons is None  # never defaulted to False

    row = service.update_profile(user, has_external_lessons=True)
    assert row.has_external_lessons is True


# ── mark_onboarding_complete: injected clock ─────────────────────────────────


def test_mark_onboarding_complete_uses_injected_clock(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    user = _seed_user(pg_sessionmaker)
    pinned = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)
    service = StudentProfileService(pg_sessionmaker, now=lambda: pinned)

    row = service.mark_onboarding_complete(user)

    assert row.onboarding_completed_at == pinned


def test_mark_onboarding_complete_accepts_explicit_timestamp(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    user = _seed_user(pg_sessionmaker)
    explicit = datetime(2025, 1, 1, tzinfo=UTC)
    service = StudentProfileService(pg_sessionmaker, now=lambda: datetime(2026, 1, 1, tzinfo=UTC))

    row = service.mark_onboarding_complete(user, completed_at=explicit)

    assert row.onboarding_completed_at == explicit


# ── Enrolments: upsert + validation ──────────────────────────────────────────


def test_upsert_enrolment_creates_then_updates(pg_sessionmaker: sessionmaker[Session]) -> None:
    user = _seed_user(pg_sessionmaker)
    subject_code = _seed_subject(pg_sessionmaker)
    service = StudentProfileService(pg_sessionmaker)

    created = service.upsert_enrolment(user, subject_code, target_grade="A")
    assert created.target_grade == "A"
    assert created.session_month is None

    updated = service.upsert_enrolment(
        user, subject_code, session_month=SessionMonth.may_june, session_year=2027
    )
    assert updated.enrolment_id == created.enrolment_id
    # Untouched by the second call.
    assert updated.target_grade == "A"
    assert updated.session_month is SessionMonth.may_june
    assert updated.session_year == 2027

    enrolments = service.list_enrolments(user)
    assert len(enrolments) == 1


def test_upsert_enrolment_unknown_subject_code_raises_validation_error(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    user = _seed_user(pg_sessionmaker)
    service = StudentProfileService(pg_sessionmaker)

    with pytest.raises(StudentProfileValidationError):
        service.upsert_enrolment(user, "not-a-real-subject", target_grade="A")


def test_upsert_enrolment_unknown_target_grade_raises_validation_error(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    user = _seed_user(pg_sessionmaker)
    subject_code = _seed_subject(pg_sessionmaker)
    service = StudentProfileService(pg_sessionmaker)

    with pytest.raises(StudentProfileValidationError):
        service.upsert_enrolment(user, subject_code, target_grade="Z")


def test_delete_enrolment_removes_it(pg_sessionmaker: sessionmaker[Session]) -> None:
    user = _seed_user(pg_sessionmaker)
    subject_code = _seed_subject(pg_sessionmaker)
    service = StudentProfileService(pg_sessionmaker)
    service.upsert_enrolment(user, subject_code, target_grade="A")

    service.delete_enrolment(user, subject_code)

    assert service.list_enrolments(user) == []


def test_delete_enrolment_ownership_check(pg_sessionmaker: sessionmaker[Session]) -> None:
    owner = _seed_user(pg_sessionmaker)
    other = _seed_user(pg_sessionmaker)
    subject_code = _seed_subject(pg_sessionmaker)
    service = StudentProfileService(pg_sessionmaker)
    service.upsert_enrolment(owner, subject_code, target_grade="A")

    with pytest.raises(StudentProfileNotFoundError):
        service.delete_enrolment(other, subject_code)

    # The owner's enrolment must survive the other student's failed attempt.
    assert len(service.list_enrolments(owner)) == 1


def test_delete_enrolment_no_such_enrolment_raises_not_found(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    user = _seed_user(pg_sessionmaker)
    subject_code = _seed_subject(pg_sessionmaker)
    service = StudentProfileService(pg_sessionmaker)

    with pytest.raises(StudentProfileNotFoundError):
        service.delete_enrolment(user, subject_code)


# ── Papers: full-replace semantics ───────────────────────────────────────────


def test_set_enrolment_papers_replaces_the_set(pg_sessionmaker: sessionmaker[Session]) -> None:
    user = _seed_user(pg_sessionmaker)
    subject_code = _seed_subject(pg_sessionmaker)
    service = StudentProfileService(pg_sessionmaker)
    service.upsert_enrolment(user, subject_code)

    first = service.set_enrolment_papers(user, subject_code, [2, 4])
    assert first.papers == (2, 4)

    second = service.set_enrolment_papers(user, subject_code, [4, 6])
    assert second.papers == (4, 6)  # 2 dropped, 6 added, 4 kept


def test_set_enrolment_papers_no_such_enrolment_raises_not_found(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    user = _seed_user(pg_sessionmaker)
    subject_code = _seed_subject(pg_sessionmaker)
    service = StudentProfileService(pg_sessionmaker)

    with pytest.raises(StudentProfileNotFoundError):
        service.set_enrolment_papers(user, subject_code, [2])


# ── Confidence ratings: full-replace + range validation ──────────────────────


def test_set_confidence_ratings_replaces_the_map(pg_sessionmaker: sessionmaker[Session]) -> None:
    user = _seed_user(pg_sessionmaker)
    subject_code = _seed_subject(pg_sessionmaker)
    service = StudentProfileService(pg_sessionmaker)
    service.upsert_enrolment(user, subject_code)

    service.set_confidence_ratings(user, subject_code, {"4.1 Topic A": 2, "4.2 Topic B": 4})
    replaced = service.set_confidence_ratings(
        user, subject_code, {"4.2 Topic B": 5, "4.3 Topic C": 1}
    )

    by_topic = {r.topic: r.rating for r in replaced}
    assert by_topic == {"4.2 Topic B": 5, "4.3 Topic C": 1}  # A dropped, B updated, C added


def test_set_confidence_ratings_collects_all_invalid_topics(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    user = _seed_user(pg_sessionmaker)
    subject_code = _seed_subject(pg_sessionmaker)
    service = StudentProfileService(pg_sessionmaker)
    service.upsert_enrolment(user, subject_code)

    with pytest.raises(StudentProfileValidationError) as excinfo:
        service.set_confidence_ratings(
            user, subject_code, {"Topic A": 0, "Topic B": 3, "Topic C": 6}
        )

    message = str(excinfo.value)
    assert "Topic A" in message
    assert "Topic C" in message
    assert "Topic B" not in message  # the one valid topic is not reported

    # The rejected write must not have partially landed.
    assert service.list_confidence_ratings(user, subject_code) == []


def test_set_confidence_ratings_no_such_enrolment_raises_not_found(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    user = _seed_user(pg_sessionmaker)
    subject_code = _seed_subject(pg_sessionmaker)
    service = StudentProfileService(pg_sessionmaker)

    with pytest.raises(StudentProfileNotFoundError):
        service.set_confidence_ratings(user, subject_code, {"Topic A": 3})


# ── target_grades_for: chunk C's at-risk feed ────────────────────────────────


def test_target_grades_for_skips_null_target_enrolments(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    user = _seed_user(pg_sessionmaker)
    physics = _seed_subject(pg_sessionmaker, "0625")
    maths = _seed_subject(pg_sessionmaker, "0580")
    service = StudentProfileService(pg_sessionmaker)
    service.upsert_enrolment(user, physics, target_grade="A")
    service.upsert_enrolment(user, maths)  # no target grade

    targets = service.target_grades_for(user)

    assert targets == {"0625": "A"}


def test_target_grades_for_no_enrolments_is_empty(pg_sessionmaker: sessionmaker[Session]) -> None:
    user = _seed_user(pg_sessionmaker)
    service = StudentProfileService(pg_sessionmaker)

    assert service.target_grades_for(user) == {}
