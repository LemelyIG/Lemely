"""The SQL grant-validity mirror equals ``core.tutor_grants`` over generated inputs (F6, SC-3).

Every repository read that decides whether a tutor may see a student (T19's list,
T20's gate, ``studentShared``) runs the SQL mirror; S8 and PA6 show the status
``core.tutor_grants.grant_status`` computes from the row. This test builds one
grant for every combination of the inputs validity depends on and checks each
SQL path against the pure functions:

* the tutor's listing state (all six) and whether the profile is paused;
* the revoke reason (none, or each of the four);
* the expiry (none, passed, still ahead);
* the block between the pair (none, either direction active, a removed one).

6 x 2 x 5 x 3 x 4 = 720 grants. The oracle is ``grant_is_valid`` /
``grant_status`` on facts written down here, not read back through the code
under test.

The expiry boundary is checked on its own: a grant is valid while
``now < expires_at`` (half-open), so ``expires_at == now()`` must already be
expired in SQL, as in the core. The generated set cannot reach that instant;
one transaction can, because ``now()`` is fixed for its length.
"""

from __future__ import annotations

import itertools
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa

from lemely.core.tutor_grants import GrantFacts, grant_is_valid, grant_status
from lemely.db.models.enums import GrantRevokeReason, Role, TutorListingState
from lemely.db.models.tutoring import TutorDataGrant, TutoringBlock, TutorProfile
from lemely.db.models.users import User
from lemely.db.tutor_grant_repo import AccessEnded, TutorGrantRepository, grant_valid_sql
from tests.test_tutor_grant_repo import add_grant, add_student
from tests.tutoring_db import NOW, add_tutor, emptied_after, tutoring_database

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker

LISTING_STATES = tuple(state.value for state in TutorListingState)
REVOKE_REASONS: tuple[str | None, ...] = (None, *(reason.value for reason in GrantRevokeReason))
EXPIRIES: tuple[timedelta | None, ...] = (None, -timedelta(days=1), timedelta(days=30))
BLOCKS = ("none", "student_blocks_tutor", "tutor_blocks_student", "removed")
CREATED_AGO = timedelta(days=10)


@dataclass(frozen=True)
class Case:
    tutor_profile_id: uuid.UUID
    student_id: uuid.UUID
    grant_id: uuid.UUID
    facts: GrantFacts


@pytest.fixture(scope="module")
def tutoring_db() -> Iterator[sessionmaker[Session]]:
    with tutoring_database() as factory:
        yield factory


@pytest.fixture
def sm(tutoring_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(tutoring_db)


def seed_cases(sm: sessionmaker[Session]) -> list[Case]:
    """One grant per input combination, written in one transaction."""
    cases: list[Case] = []
    created_at = NOW - CREATED_AGO
    with sm.begin() as session:
        for state, paused in itertools.product(LISTING_STATES, (False, True)):
            tutor_user = uuid.uuid4()
            profile_id = uuid.uuid4()
            session.add(User(id=tutor_user, email=f"{tutor_user}@example.com", role=Role.teacher))
            session.flush()
            session.add(
                TutorProfile(
                    id=profile_id,
                    user_id=tutor_user,
                    public_first_name="Sara",
                    public_last_initial="M",
                    headline="IGCSE Physics",
                    offers_virtual=True,
                    area_code="cairo",
                    listing_state=TutorListingState(state),
                    paused_at=NOW - timedelta(days=1) if paused else None,
                    closed_at=NOW - timedelta(days=1) if state == "closed" else None,
                )
            )
            session.flush()
            for reason, expiry, block in itertools.product(REVOKE_REASONS, EXPIRIES, BLOCKS):
                student = uuid.uuid4()
                grant_id = uuid.uuid4()
                session.add(User(id=student, email=f"{student}@example.com", role=Role.student))
                session.flush()
                revoked_at = created_at + timedelta(days=1) if reason is not None else None
                expires_at = NOW + expiry if expiry is not None else None
                session.add(
                    TutorDataGrant(
                        id=grant_id,
                        student_id=student,
                        tutor_profile_id=profile_id,
                        created_at=created_at,
                        revoked_at=revoked_at,
                        revoke_reason=GrantRevokeReason(reason) if reason is not None else None,
                        expires_at=expires_at,
                    )
                )
                if block != "none":
                    blocker, blocked = (
                        (student, tutor_user)
                        if block in ("student_blocks_tutor", "removed")
                        else (tutor_user, student)
                    )
                    session.add(
                        TutoringBlock(
                            blocker_user_id=blocker,
                            blocked_user_id=blocked,
                            removed_at=NOW - timedelta(hours=1) if block == "removed" else None,
                        )
                    )
                cases.append(
                    Case(
                        tutor_profile_id=profile_id,
                        student_id=student,
                        grant_id=grant_id,
                        facts=GrantFacts(
                            created_at=created_at,
                            revoked_at=revoked_at,
                            revoke_reason=reason,
                            expires_at=expires_at,
                            tutor_listing_state=state,
                            blocked=block in ("student_blocks_tutor", "tutor_blocks_student"),
                        ),
                    )
                )
    return cases


def db_now(sm: sessionmaker[Session]) -> object:
    with sm() as session:
        return session.execute(sa.text("SELECT now()")).scalar_one()


def test_sql_grant_validity_equals_core_over_generated_inputs(sm: sessionmaker[Session]) -> None:
    cases = seed_cases(sm)
    repo = TutorGrantRepository(sm)
    now = db_now(sm)
    expected = {case.grant_id for case in cases if grant_is_valid(case.facts, now=now)}  # type: ignore[arg-type]

    # Non-vacuity: every combination is present, and both answers occur many times.
    assert len(cases) == len(LISTING_STATES) * 2 * len(REVOKE_REASONS) * len(EXPIRIES) * len(BLOCKS)
    assert len(cases) == 720
    assert 0 < len(expected) < len(cases)

    by_tutor: dict[uuid.UUID, list[Case]] = {}
    for case in cases:
        by_tutor.setdefault(case.tutor_profile_id, []).append(case)
    assert len(by_tutor) == 12

    # studentShared: the predicate T10's booking DTO uses (no audit row).
    shared: set[uuid.UUID] = set()
    for profile_id, group in by_tutor.items():
        students = repo.student_shared(profile_id, [case.student_id for case in group])
        shared |= {case.grant_id for case in group if case.student_id in students}
    assert shared == expected

    # T19: the grants a tutor's student list pages through.
    listed: set[uuid.UUID] = set()
    for profile_id in by_tutor:
        cursor = None
        while True:
            page = repo.students_page(profile_id, cursor, 50)
            listed |= {item.grant_id for item in page.items}
            if page.next_key is None:
                break
            cursor = page.next_key
    assert listed == expected

    # T20: the gate itself, on every case.
    gated: set[uuid.UUID] = set()
    for case in cases:
        try:
            gated.add(repo.require_valid_grant(case.tutor_profile_id, case.student_id).grant.id)
        except AccessEnded:
            continue
    assert gated == expected


def test_sql_grant_validity_is_half_open_at_expires_at(sm: sessionmaker[Session]) -> None:
    """``expires_at`` one microsecond before, exactly at, and one after the database ``now()``."""
    tutor = add_tutor(sm)
    grant = add_grant(sm, add_student(sm), tutor)
    outcomes: dict[str, tuple[bool, bool]] = {}
    for label, offset in (
        ("before", -timedelta(microseconds=1)),
        ("at", timedelta(0)),
        ("after", timedelta(microseconds=1)),
    ):
        with sm.begin() as session:  # one transaction: now() is the same instant throughout
            session.execute(
                sa.text("UPDATE tutor_data_grants SET expires_at = now() + :offset WHERE id = :g"),
                {"offset": offset, "g": grant},
            )
            row = session.execute(
                sa.text(
                    "SELECT g.created_at, g.expires_at, now() AS db_now, "  # noqa: S608 - constant
                    f"{grant_valid_sql('g', 'tp')} AS valid FROM tutor_data_grants g "
                    "JOIN tutor_profiles tp ON tp.id = g.tutor_profile_id WHERE g.id = :g"
                ),
                {"g": grant},
            ).one()
        facts = GrantFacts(
            created_at=row.created_at,
            revoked_at=None,
            revoke_reason=None,
            expires_at=row.expires_at,
            tutor_listing_state="listed",
            blocked=False,
        )
        assert row.expires_at - row.db_now == offset, label  # the instant really is the boundary
        outcomes[label] = (bool(row.valid), grant_is_valid(facts, now=row.db_now))

    assert all(sql == core for sql, core in outcomes.values()), outcomes
    # Non-vacuity: both answers occur, and equality is the expired side.
    assert {label: core for label, (_, core) in outcomes.items()} == {
        "before": False,
        "at": False,
        "after": True,
    }


def test_grant_status_shown_to_the_student_equals_core(sm: sessionmaker[Session]) -> None:
    cases = seed_cases(sm)
    repo = TutorGrantRepository(sm)
    now = db_now(sm)
    seen: set[str] = set()
    for case in cases:
        [view] = repo.grants_for_student(case.student_id, include_classes=False)
        assert view.grant.id == case.grant_id
        assert view.status == grant_status(case.facts, now=now), case  # type: ignore[arg-type]
        seen.add(view.status)
    # Non-vacuity: every status the SPEC names occurs in the generated set.
    assert seen == {
        "active",
        "revoked",
        "expired",
        "blocked",
        "tutor_suspended",
        "tutor_closed",
        "tutor_unavailable",
    }
