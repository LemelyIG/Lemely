"""Database helpers shared by the teacher-team test modules (Phase 03).

Not a test module (no ``test_`` prefix). Each test module defines its own fixtures
from these helpers, as ``tests/tutoring_db.py`` explains: a fixture imported by name
would be redefined by the parameter that uses it.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.db.base import Base
from lemely.db.class_repo import _generate_join_code
from lemely.db.models import (
    ClassEnrollment,
    PlanTier,
    SchoolClass,
    Subject,
    Subscription,
    User,
    import_all_models,
)
from lemely.db.models.billing import PlanAudience
from lemely.db.models.enums import PlanInterval, Role, SubscriptionStatus
from lemely.db.models.team import (
    AssistantRole,
    CapPeriod,
    TeacherMember,
    TeacherMemberKind,
    TeacherMemberStatus,
)
from lemely.db.models.usage import GrantKind, UsageEntry, UsageEntryKind, UsageGrantBalance
from lemely.db.usage_ledger_repo import UsageLedger
from lemely.runtime.config import DatabaseSettings

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence

import_all_models()

NOW = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)


@contextmanager
def team_database() -> Iterator[sessionmaker[Session]]:
    """A fresh ``create_all`` database for one test module."""
    base = make_url(DatabaseSettings().url)
    admin = create_engine(base.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect():
            pass
    except OperationalError:
        admin.dispose()
        pytest.skip("local Postgres not reachable")
    name = f"lemely_test_{uuid.uuid4().hex[:12]}"
    with admin.connect() as conn:
        conn.execute(sa.text(f'CREATE DATABASE "{name}"'))
    engine = create_engine(base.set(database=name))
    try:
        Base.metadata.create_all(engine)
        yield sessionmaker(bind=engine, expire_on_commit=False, future=True)
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


def emptied_after(factory: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    """Yield ``factory``, then empty every table reachable from users, subjects and plans."""
    yield factory
    with factory.begin() as session:
        session.execute(sa.text("TRUNCATE users, subjects, plan_tiers CASCADE"))
        # ``billing_settings.updated_by`` references users, so the cascade empties it too: put
        # its single row back as ``create_all`` leaves it, since billing reads fail closed (UD-13).
        session.execute(
            sa.text("INSERT INTO billing_settings (id) VALUES (1) ON CONFLICT DO NOTHING")
        )


def add_user(
    factory: sessionmaker[Session],
    role: Role = Role.student,
    *,
    display_name: str | None = None,
) -> uuid.UUID:
    uid = uuid.uuid4()
    with factory.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=role, display_name=display_name))
    return uid


def add_subject(factory: sessionmaker[Session], code: str, name: str = "Mathematics") -> str:
    with factory.begin() as session:
        session.add(Subject(code=code, name=name))
    return code


def add_class(
    factory: sessionmaker[Session],
    *,
    teacher_id: uuid.UUID,
    subject_code: str | None = None,
    school_id: uuid.UUID | None = None,
) -> tuple[uuid.UUID, str]:
    class_id = uuid.uuid4()
    join_code = _generate_join_code()
    with factory.begin() as session:
        session.add(
            SchoolClass(
                id=class_id,
                teacher_id=teacher_id,
                school_id=school_id,
                name="Team Test Class",
                subject_code=subject_code,
                join_code=join_code,
            )
        )
    return class_id, join_code


def enrol(factory: sessionmaker[Session], class_id: uuid.UUID, student_id: uuid.UUID) -> None:
    with factory.begin() as session:
        session.add(ClassEnrollment(class_id=class_id, student_id=student_id))


def add_teacher_plan(
    factory: sessionmaker[Session],
    teacher_id: uuid.UUID,
    *,
    included_seats: int,
    extra_seats: int = 0,
    status: SubscriptionStatus = SubscriptionStatus.active,
    audience: PlanAudience = PlanAudience.teacher,
) -> uuid.UUID:
    """Seed a plan tier and a subscription for ``teacher_id``; return the subscription id.

    Column names are Phase 02's (``audience``, ``allowance_units``, ``included_seats``,
    ``seat_allowance_units``, ``extra_seat_price_minor``, ``is_active``,
    ``payer_user_id``, ``extra_seats``). If Phase 02 added another NOT NULL column
    without a server default, set it here.
    """
    tier_id, sub_id = uuid.uuid4(), uuid.uuid4()
    with factory.begin() as session:
        session.add(
            PlanTier(
                id=tier_id,
                code=f"teacher_{tier_id.hex[:8]}",
                name="Teacher",
                price_minor=0,
                interval=PlanInterval.monthly,
                audience=audience,
                allowance_units=1000,
                included_seats=included_seats,
                seat_allowance_units=100,
                extra_seat_price_minor=0,
                is_active=True,
            )
        )
        session.flush()
        session.add(
            Subscription(
                id=sub_id,
                user_id=teacher_id,
                payer_user_id=teacher_id,
                plan_tier_id=tier_id,
                status=status,
                extra_seats=extra_seats,
            )
        )
    return sub_id


def add_seat(
    factory: sessionmaker[Session],
    *,
    teacher_id: uuid.UUID,
    student_id: uuid.UUID,
    subjects: Sequence[str] = (),
    actions: Sequence[str] = ("mark_paper",),
    status: TeacherMemberStatus = TeacherMemberStatus.active,
    leaves_at: datetime | None = None,
    cap_units: int | None = None,
) -> uuid.UUID:
    member_id = uuid.uuid4()
    with factory.begin() as session:
        session.add(
            TeacherMember(
                id=member_id,
                teacher_user_id=teacher_id,
                member_user_id=student_id,
                kind=TeacherMemberKind.student_seat,
                scope_subjects=list(subjects),
                scope_actions=list(actions),
                cap_units=cap_units,
                cap_period=CapPeriod.month,
                status=status,
                leaves_at=leaves_at,
            )
        )
    return member_id


def add_assistant(
    factory: sessionmaker[Session],
    *,
    teacher_id: uuid.UUID,
    assistant_id: uuid.UUID,
    role: AssistantRole = AssistantRole.co_teacher,
    permissions: Mapping[str, bool] | None = None,
    status: TeacherMemberStatus = TeacherMemberStatus.active,
) -> uuid.UUID:
    member_id = uuid.uuid4()
    with factory.begin() as session:
        session.add(
            TeacherMember(
                id=member_id,
                teacher_user_id=teacher_id,
                member_user_id=assistant_id,
                kind=TeacherMemberKind.assistant,
                role_preset=role,
                permissions=dict(permissions or {}),
                cap_period=CapPeriod.month,
                status=status,
            )
        )
    return member_id


def add_grant(
    factory: sessionmaker[Session],
    *,
    owner_id: uuid.UUID,
    kind: GrantKind,
    units: int,
    at: datetime,
    teacher_member_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """Issue a grant through Phase 01's ledger, usable from ``at - 60 days`` for a year."""
    with factory.begin() as session:
        grant = UsageLedger(session).issue_grant(
            owner_user_id=owner_id,
            kind=kind,
            units=units,
            idempotency_key=f"test:{uuid.uuid4()}",
            expires_at=at + timedelta(days=365),
            visible=kind in (GrantKind.credit_pack, GrantKind.auto_topup),
            effective_at=at - timedelta(days=60),
            teacher_member_id=teacher_member_id,
        )
        return grant.id


def add_entry(
    factory: sessionmaker[Session],
    *,
    grant_id: uuid.UUID,
    member_id: uuid.UUID | None,
    kind: UsageEntryKind,
    units: int,
    at: datetime,
) -> None:
    """Append one ledger line directly (settle lines are negative, hold lines positive)."""
    with factory.begin() as session:
        session.add(
            UsageEntry(
                grant_id=grant_id,
                teacher_member_id=member_id,
                kind=kind,
                units=units,
                event_at=at,
                idempotency_key=f"test:{uuid.uuid4()}",
            )
        )


def set_remaining(factory: sessionmaker[Session], grant_id: uuid.UUID, remaining: int) -> None:
    """Set a grant's cached balance (what ``UsageLedger.meter_fraction`` reads)."""
    with factory.begin() as session:
        session.execute(
            sa.update(UsageGrantBalance)
            .where(UsageGrantBalance.grant_id == grant_id)
            .values(remaining=remaining)
        )
