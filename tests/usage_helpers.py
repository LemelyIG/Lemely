"""Shared seeding for the metering tests (billing plan phase 04)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import select

from lemely.core.metered_actions import MeteredAction
from lemely.db.models import School, SchoolMembership
from lemely.db.models.attempts import Attempt, QuestionResult, QuestionResultPoint
from lemely.db.models.enums import (
    AttemptOrigin,
    ConfidenceBand,
    MarkerSource,
    MembershipRole,
    QuestionDifficulty,
    QuizQuestionStatus,
    Role,
    SessionMonth,
)
from lemely.db.models.quizzes import Quiz, QuizAssignment, QuizQuestion
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
from tests.team_db import add_class, enrol

if TYPE_CHECKING:
    from collections.abc import Iterable

    from sqlalchemy.orm import Session, sessionmaker

    from lemely.web.usage import UsageMeter

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


def enforcing_meter(sm: sessionmaker[Session], now: datetime = NOW) -> UsageMeter:
    """A meter that enforces on ``sm`` whatever the suite's ``LEMELY_USAGE__ENFORCE`` says."""
    from lemely.web.usage import UsageMeter

    return UsageMeter(sm, enforce=True, now=lambda: now)


def put_in_school(sm: sessionmaker[Session], user: uuid.UUID) -> None:
    school_id = uuid.uuid4()
    with sm.begin() as session:
        session.add(School(id=school_id, name="Guard School", seat_quota=5))
        session.flush()
        session.add(
            SchoolMembership(
                school_id=school_id, user_id=user, membership_role=MembershipRole.teacher
            )
        )


def attempt_with_points(
    sm: sessionmaker[Session], owner: uuid.UUID, *, subject: str | None, points: int
) -> tuple[uuid.UUID, uuid.UUID]:
    attempt_id, qr_id = uuid.uuid4(), uuid.uuid4()
    with sm.begin() as session:
        session.add(
            Attempt(
                id=attempt_id,
                user_id=owner,
                subject_code=subject,
                session_month=SessionMonth.may_june,
                session_year=2024,
                paper_number=4,
                paper_variant=2,
                awarded_marks=3,
                maximum_marks=4,
                percentage=75.0,
                recorded_at=NOW,
                origin=AttemptOrigin.past_paper,
            )
        )
        session.flush()
        session.add(
            QuestionResult(
                id=qr_id,
                attempt_id=attempt_id,
                question_id="1",
                awarded_marks=1,
                maximum_marks=4,
                confidence_band=ConfidenceBand.low,
                confidence_score=0.4,
                marker_source=MarkerSource.ai,
            )
        )
        session.flush()
        for i in range(points):
            session.add(
                QuestionResultPoint(
                    question_result_id=qr_id,
                    mark_point_id=f"M{i}",
                    ordinal=i,
                    tariff=1,
                    point_text="p",
                    awarded=False,
                )
            )
    return attempt_id, qr_id


class Assigned:
    """An assigned quiz and who may see it: ``owner`` directly, or ``class_id``'s roster."""

    def __init__(self, assignment_id: uuid.UUID, owner: uuid.UUID, class_id: uuid.UUID | None):
        self.assignment_id = str(assignment_id)
        self.owner = owner
        self.class_id = class_id


def quiz_with_assignment(
    sm: sessionmaker[Session],
    *,
    subject: str,
    included: int,
    removed: int = 0,
    via_class: bool = False,
) -> Assigned:
    teacher = seed_user(sm, Role.teacher)
    student = seed_user(sm)
    quiz_id, assignment_id = uuid.uuid4(), uuid.uuid4()
    class_id = add_class(sm, teacher_id=teacher, subject_code=subject)[0] if via_class else None
    if class_id is not None:
        enrol(sm, class_id, student)
    with sm.begin() as session:
        session.add(Quiz(id=quiz_id, teacher_id=teacher, subject_code=subject, title="Recap"))
        session.flush()
        for i in range(included + removed):
            session.add(
                QuizQuestion(
                    quiz_id=quiz_id,
                    question_ref=f"q{i}",
                    position=i,
                    status=(
                        QuizQuestionStatus.included if i < included else QuizQuestionStatus.removed
                    ),
                    difficulty=QuestionDifficulty.standard,
                    question_type="explanation",
                    prompt="Explain.",
                    total_marks=2,
                )
            )
        session.add(
            QuizAssignment(
                id=assignment_id,
                quiz_id=quiz_id,
                student_id=None if via_class else student,
                class_id=class_id,
                assigned_by=teacher,
            )
        )
    return Assigned(assignment_id, student, class_id)
