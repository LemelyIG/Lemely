"""Server-side facts for metering (billing spec §5.6, §5.7). Read-only queries.

Everything the payer chain and the 402 reason depend on is read here, from the records an
action works on, never from client input: seats and their scope, the assistant row, which
owners have debt, whether a study plan was already generated this ISO week, and the
subject and countable inputs of a question or a quiz.

Seats come through ``TeacherTeamService`` (phase 03), so "held seat" stays defined in one
place. An ``assistant_member_id`` is confirmed again here, in the transaction that bills:
the row must still be an active assistant row of the actor under a teacher lead with no
school data (``lead_has_school_data``). Otherwise ``AssistantUnavailable`` is raised with
the 403 code the team routes use, and nothing falls back to the actor's own chain, so an
assistant's balance never pays for the lead's work. The permission itself was checked by
``require_team_permission`` (and ``assistant_has_permission`` for the estimate route).

Every ``now`` must be timezone-aware: a naive value would be read in the server's local
zone and silently shift the study-plan week and the cap windows.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import exists, func, or_, select

from lemely.core.metered_actions import SEAT_ACTIONS, MeteredAction, UsageTarget
from lemely.core.payer_chain import (
    AssistantView,
    BlockFacts,
    ChainContext,
    SeatView,
    seat_scope_miss,
)
from lemely.core.usage_types import GrantScope
from lemely.db.models.attempts import Attempt, QuestionResult, QuestionResultPoint
from lemely.db.models.billing import Subscription
from lemely.db.models.enums import QuizQuestionStatus, Role
from lemely.db.models.orgs import ClassEnrollment
from lemely.db.models.quizzes import Quiz, QuizAssignment, QuizQuestion
from lemely.db.models.study_plan import StudyPlan
from lemely.db.models.team import TeacherMember, TeacherMemberKind, TeacherMemberStatus
from lemely.db.models.usage import GrantKind, UsageDebt, UsageGrant
from lemely.db.models.users import User
from lemely.db.teacher_team_repo import (
    LIVE_PLAN_STATUSES,
    TeacherTeamService,
    lead_has_school_data,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy import ColumnElement
    from sqlalchemy.orm import Session

    from lemely.core.usage_types import Payer


def _require_aware(now: datetime) -> None:
    if now.tzinfo is None:
        raise ValueError("usage context needs a timezone-aware datetime")


def _seat_view(row: TeacherMember) -> SeatView:
    return SeatView(
        member_id=row.id,
        teacher_user_id=row.teacher_user_id,
        scope_subjects=frozenset(row.scope_subjects or ()),
        scope_actions=frozenset(row.scope_actions or ()),
        cap_units=row.cap_units,
        cap_period=row.cap_period.value,
        created_at=row.created_at,
    )


class AssistantUnavailable(Exception):
    """An ``assistant_member_id`` that cannot be confirmed for this actor right now.

    ``code`` is the 403 body code the team routes use: ``team_lead_unavailable`` when the
    actor holds the row but the lead holds school data (the same signal as
    ``TeacherTeamService.assistant_access``), otherwise ``team_permission_denied``. A caller
    that is not the row's assistant never learns more than the generic denial.

    Raised instead of falling back to "no assistant": the actor's own chain would bill the
    assistant's balance for the lead's work (R4).
    """

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


DENIED = "team_permission_denied"
UNAVAILABLE = "team_lead_unavailable"


def _assistant_view(
    session: Session, *, actor_user_id: uuid.UUID, member_id: uuid.UUID
) -> AssistantView:
    """The actor's active assistant row ``member_id``, confirmed in one statement.

    The row must be an active ``assistant`` row of this actor whose lead is still a teacher
    (the conditions ``assistant_access`` applies), and the lead must hold no school data
    (``lead_has_school_data``, phase 03's shared predicate). The permission itself was
    checked by the route guard; this is the second line, run in the transaction that bills.
    """
    found = session.execute(
        select(TeacherMember, lead_has_school_data(TeacherMember.teacher_user_id))
        .join(User, User.id == TeacherMember.teacher_user_id)
        .where(
            TeacherMember.id == member_id,
            TeacherMember.member_user_id == actor_user_id,
            TeacherMember.kind == TeacherMemberKind.assistant,
            TeacherMember.status == TeacherMemberStatus.active,
            User.role == Role.teacher,
        )
    ).first()
    if found is None:
        raise AssistantUnavailable(DENIED)
    member, school_data = found
    if school_data:
        raise AssistantUnavailable(UNAVAILABLE)
    return AssistantView(
        member_id=member.id,
        lead_teacher_user_id=member.teacher_user_id,
        cap_units=member.cap_units,
        cap_period=member.cap_period.value,
    )


def study_plan_generated_this_week(
    session: Session, *, user_id: uuid.UUID, subject_code: str, now: datetime
) -> bool:
    """A plan (live or superseded) already exists for this ISO week (§2.2 study plans).

    The week is Monday to Sunday in UTC, keyed on ``study_plans.week_start``, the same
    Monday the plan repository writes.
    """
    _require_aware(now)
    today = now.astimezone(UTC).date()
    week_start = today - timedelta(days=today.weekday())
    return bool(
        session.scalar(
            select(
                exists().where(
                    StudyPlan.user_id == user_id,
                    StudyPlan.subject_code == subject_code,
                    StudyPlan.week_start == week_start,
                )
            )
        )
    )


def load_chain_context(
    session: Session,
    *,
    actor_user_id: uuid.UUID,
    action: MeteredAction,
    subject_code: str | None,
    assistant_member_id: uuid.UUID | None,
    now: datetime,
) -> ChainContext:
    """Read every fact ``build_payer_chain`` needs for one action.

    At most three queries however many seats the actor holds: seats (or the assistant
    confirmation), the debtors among every owner the chain may touch, and the study-plan
    week.

    Raises ``AssistantUnavailable`` when ``assistant_member_id`` is given and cannot be
    confirmed; the caller maps it to a 403 with ``.code``.
    """
    _require_aware(now)
    assistant = (
        _assistant_view(session, actor_user_id=actor_user_id, member_id=assistant_member_id)
        if assistant_member_id is not None
        else None
    )
    seats = (
        ()
        if assistant is not None
        else tuple(
            _seat_view(r) for r in TeacherTeamService(session).seats_for_student(actor_user_id)
        )
    )
    owners = {actor_user_id, *(s.teacher_user_id for s in seats)}
    if assistant is not None:
        owners.add(assistant.lead_teacher_user_id)
    debtors = frozenset(
        session.scalars(
            select(UsageDebt.owner_user_id)
            .where(UsageDebt.owner_user_id.in_(owners), UsageDebt.outstanding > 0)
            .distinct()
        )
    )
    generated = (
        action is MeteredAction.STUDY_PLAN
        and subject_code is not None
        and study_plan_generated_this_week(
            session, user_id=actor_user_id, subject_code=subject_code, now=now
        )
    )
    return ChainContext(
        actor_user_id=actor_user_id,
        action=action,
        subject_code=subject_code,
        now=now,
        seats=seats,
        assistant=assistant,
        debtors=debtors,
        study_plan_generated_this_week=generated,
    )


def candidate_subjects(
    session: Session, *, actor_user_id: uuid.UUID, action: MeteredAction
) -> list[str | None]:
    """Subjects a not-yet-known subject could turn out to be, for a pre-check.

    ``None`` (no seat covers it) first, then every subject of a held seat whose scope
    covers ``action``, sorted. Actions no seat can cover have only ``None``.
    """
    if action not in SEAT_ACTIONS:
        return [None]
    subjects = sorted(
        {
            subject
            for row in TeacherTeamService(session).seats_for_student(actor_user_id)
            if action.value in (row.scope_actions or ())
            for subject in (row.scope_subjects or ())
        }
    )
    return [None, *subjects]


def has_live_plan(session: Session, owner_user_id: uuid.UUID) -> bool:
    """The owner holds an active or past-due subscription."""
    return bool(
        session.scalar(
            select(
                exists().where(
                    Subscription.user_id == owner_user_id,
                    Subscription.status.in_(LIVE_PLAN_STATUSES),
                )
            )
        )
    )


def has_live_credit_grant(session: Session, owner_user_id: uuid.UUID, *, now: datetime) -> bool:
    """The owner holds a visible (credits-style) grant that is effective and unexpired."""
    return bool(
        session.scalar(
            select(
                exists().where(
                    UsageGrant.owner_user_id == owner_user_id,
                    UsageGrant.visible.is_(True),
                    UsageGrant.effective_at <= now,
                    or_(UsageGrant.expires_at.is_(None), UsageGrant.expires_at > now),
                )
            )
        )
    )


def load_block_facts(
    session: Session, ctx: ChainContext, chain: Sequence[Payer], *, now: datetime
) -> BlockFacts:
    """Why ``chain`` cannot cover an estimate, for ``block_reason``.

    Plan and credits are the funding owner's: the lead for an assistant, else the actor.
    """
    funding = ctx.assistant.lead_teacher_user_id if ctx.assistant is not None else ctx.actor_user_id
    return BlockFacts(
        last_resort_in_debt=chain[-1].owner_user_id in ctx.debtors,
        seat_scope_miss=seat_scope_miss(ctx),
        has_live_plan=has_live_plan(session, funding),
        has_credit_grant=has_live_credit_grant(session, funding, now=now),
    )


def _uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


def self_review_target(
    session: Session, *, student_id: str, attempt_id: str, question_result_id: str
) -> UsageTarget | None:
    """The caller's own question: its attempt's subject and its mark-point count.

    ``None`` when any id is malformed, or the question is not on the caller's own attempt.
    """
    sid, aid, qid = _uuid(student_id), _uuid(attempt_id), _uuid(question_result_id)
    if sid is None or aid is None or qid is None:
        return None
    found = session.execute(
        select(Attempt.subject_code)
        .join(QuestionResult, QuestionResult.attempt_id == Attempt.id)
        .where(Attempt.id == aid, Attempt.user_id == sid, QuestionResult.id == qid)
    ).first()
    if found is None:
        return None
    marks = session.scalar(
        select(func.count())
        .select_from(QuestionResultPoint)
        .where(QuestionResultPoint.question_result_id == qid)
    )
    return UsageTarget(subject_code=found[0], input_count=int(marks or 0))


def quiz_assignment_target(
    session: Session, *, student_id: str, assignment_id: str
) -> UsageTarget | None:
    """The caller's own assignment: its quiz's subject and included question count.

    Ownership is ``QuizTakingService._load_permitted``'s rule: the assignment targets the
    caller directly, or a class the caller is enrolled in. A foreign, unknown or malformed
    id all return ``None``, so an id cannot be probed.

    The enrolment subquery is a second reader of ``ClassEnrollment`` beside
    ``ClassService.enrolled_class_ids`` (the seam ``QuizTakingService`` uses), on purpose:
    that seam opens its own session, and this check must read inside the billing
    transaction. ``test_quiz_target_visibility_matches_the_enrolment_seam`` pins that the
    two agree; change them together.
    """
    sid, aid = _uuid(student_id), _uuid(assignment_id)
    if sid is None or aid is None:
        return None
    quiz = session.execute(
        select(Quiz.id, Quiz.subject_code)
        .join(QuizAssignment, QuizAssignment.quiz_id == Quiz.id)
        .where(
            QuizAssignment.id == aid,
            or_(
                QuizAssignment.student_id == sid,
                QuizAssignment.class_id.in_(
                    select(ClassEnrollment.class_id).where(ClassEnrollment.student_id == sid)
                ),
            ),
        )
    ).first()
    if quiz is None:
        return None
    count = session.scalar(
        select(func.count())
        .select_from(QuizQuestion)
        .where(QuizQuestion.quiz_id == quiz.id, QuizQuestion.status == QuizQuestionStatus.included)
    )
    return UsageTarget(subject_code=quiz.subject_code, input_count=int(count or 0))


def allowance_units(session: Session, payer: Payer, *, now: datetime) -> int | None:
    """Units of the live monthly allowance a payer draws from, for "N% of your plan".

    ``None`` for a credits payer, and when no period or seat allowance is live (a
    signup-only student sees credits-style copy).
    """
    filters: tuple[ColumnElement[bool], ...]
    if payer.scope is GrantScope.SEAT:
        filters = (
            UsageGrant.kind == GrantKind.seat_allowance,
            UsageGrant.teacher_member_id == payer.teacher_member_id,
        )
    elif payer.scope is GrantScope.ALLOWANCE:
        filters = (UsageGrant.kind == GrantKind.period_allowance,)
    else:
        return None
    total = session.scalar(
        select(func.sum(UsageGrant.units)).where(
            UsageGrant.owner_user_id == payer.owner_user_id,
            UsageGrant.effective_at <= now,
            or_(UsageGrant.expires_at.is_(None), UsageGrant.expires_at > now),
            *filters,
        )
    )
    return int(total) if total else None
