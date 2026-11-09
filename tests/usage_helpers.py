"""Shared seeding for the metering tests (billing plan phase 04)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import select

from lemely.core.metered_actions import MeteredAction
from lemely.db.models.enums import Role
from lemely.db.models.team import (
    AssistantRole,
    CapPeriod,
    TeacherMember,
    TeacherMemberKind,
    TeacherMemberStatus,
)
from lemely.db.models.usage import GrantKind, UsageJob
from lemely.db.models.users import User
from lemely.db.usage_catalogue_repo import ensure_usage_catalogue
from lemely.db.usage_ledger_repo import UsageLedger

if TYPE_CHECKING:
    from collections.abc import Iterable

    from sqlalchemy.orm import Session, sessionmaker

#: A Wednesday, so "this ISO week" and "this calendar month" are unambiguous.
NOW = datetime(2026, 11, 4, 10, 0, tzinfo=UTC)


def seed_user(sm: sessionmaker[Session], role: Role = Role.student) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=role))
    return uid


def seed_catalogue(sm: sessionmaker[Session]) -> None:
    with sm.begin() as session:
        ensure_usage_catalogue(session, now=NOW)


def give(
    sm: sessionmaker[Session],
    owner: uuid.UUID,
    *,
    units: int,
    kind: GrantKind = GrantKind.credit_pack,
    visible: bool = True,
    teacher_member_id: uuid.UUID | None = None,
    expires_at: datetime | None = None,
) -> uuid.UUID:
    with sm.begin() as session:
        grant = UsageLedger(session).issue_grant(
            owner_user_id=owner,
            kind=kind,
            units=units,
            idempotency_key=f"test:{uuid.uuid4()}",
            expires_at=expires_at,
            visible=visible,
            effective_at=NOW - timedelta(days=1),
            teacher_member_id=teacher_member_id,
        )
        return grant.id


def seat(
    sm: sessionmaker[Session],
    *,
    teacher: uuid.UUID,
    student: uuid.UUID,
    subjects: Iterable[str],
    actions: Iterable[MeteredAction],
    cap_units: int | None = None,
    cap_period: CapPeriod = CapPeriod.month,
    status: TeacherMemberStatus = TeacherMemberStatus.active,
    created_at: datetime = NOW - timedelta(days=10),
) -> uuid.UUID:
    with sm.begin() as session:
        row = TeacherMember(
            teacher_user_id=teacher,
            member_user_id=student,
            kind=TeacherMemberKind.student_seat,
            status=status,
            scope_subjects=list(subjects),
            scope_actions=[a.value for a in actions],
            cap_units=cap_units,
            cap_period=cap_period,
            created_at=created_at,
            # ck_teacher_members_leaving_has_date: a leaving seat carries its end date.
            leaves_at=NOW + timedelta(days=20) if status is TeacherMemberStatus.leaving else None,
        )
        session.add(row)
        session.flush()
        return row.id


def assistant(
    sm: sessionmaker[Session],
    *,
    teacher: uuid.UUID,
    member: uuid.UUID,
    cap_units: int | None = None,
    cap_period: CapPeriod = CapPeriod.month,
    role: AssistantRole = AssistantRole.co_teacher,
) -> uuid.UUID:
    with sm.begin() as session:
        row = TeacherMember(
            teacher_user_id=teacher,
            member_user_id=member,
            kind=TeacherMemberKind.assistant,
            status=TeacherMemberStatus.active,
            role_preset=role,
            # ck_teacher_members_assistant_fields: an assistant row has a permissions object.
            permissions={},
            cap_units=cap_units,
            cap_period=cap_period,
        )
        session.add(row)
        session.flush()
        return row.id


def seat_grant(
    sm: sessionmaker[Session], *, student: uuid.UUID, member_id: uuid.UUID, units: int
) -> uuid.UUID:
    return give(
        sm,
        student,
        units=units,
        kind=GrantKind.seat_allowance,
        visible=False,
        teacher_member_id=member_id,
        expires_at=datetime(2026, 12, 1, tzinfo=UTC),
    )


def jobs_for(sm: sessionmaker[Session], actor: uuid.UUID) -> list[UsageJob]:
    with sm() as session:
        return list(
            session.scalars(
                select(UsageJob)
                .where(UsageJob.actor_user_id == actor)
                .order_by(UsageJob.created_at, UsageJob.id)
            )
        )
