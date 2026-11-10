"""Metering on quiz marking (billing phase 04, Task 13).

Placement, practice and teacher-assigned quizzes all submit through
``POST /api/student/quizzes/{assignment_id}/submit``; marking runs on a fire-and-forget
thread. The hold is placed in the request (so the 402 comes before the submission is
accepted), and the thread settles on success and releases on every failure.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select

from lemely.core.metered_actions import MeteredAction
from lemely.db.models.billing import PlanAudience
from lemely.db.models.enums import Role
from lemely.db.models.quizzes import QuizSubmission
from lemely.db.models.usage import GrantKind, UsageGrantBalance, UsageJobStatus
from lemely.db.quiz_marking_repo import QuizMarkingError
from lemely.db.usage_context_repo import quiz_assignment_target
from lemely.io.llm.cost_meter import record_llm_cost
from lemely.web.deps import get_quiz_marking_service
from lemely.web.routers import quiz as quiz_router
from lemely.web.usage import get_usage_meter
from tests import test_web_student_quiz as _quiz
from tests.team_db import add_teacher_plan
from tests.usage_helpers import (
    enforcing_meter,
    give,
    jobs_for,
    seat,
    seat_grant,
    seed_catalogue,
    seed_user,
)

client = _quiz.client
pg_sessionmaker = _quiz.pg_sessionmaker
class_service = _quiz.class_service
bank_service = _quiz.bank_service
quiz_service = _quiz.quiz_service
taking_service = _quiz.taking_service

if TYPE_CHECKING:
    from collections.abc import Callable

    from fastapi.testclient import TestClient
    from httpx2 import Response
    from sqlalchemy.orm import Session, sessionmaker

    from lemely.db.class_repo import ClassService
    from lemely.db.quiz_repo import QuizService
    from lemely.db.quiz_taking_repo import QuizTakingService

Ready = tuple[
    "TestClient", uuid.UUID, uuid.UUID, str, "sessionmaker[Session]"
]  # client, student, teacher, assignment id, sessionmaker


class _InlineThread:
    """Runs the marking thread's target at once, so the settle is visible on return."""

    def __init__(self, target: Callable[[], None], daemon: bool) -> None:
        self._target = target

    def start(self) -> None:
        self._target()


class _CostlyMarking:
    """A marking double that spends 0.004 USD, then returns, records an error or raises."""

    def __init__(self, error: str | None = None, raises: Exception | None = None) -> None:
        self.error = error
        self.raises = raises
        self.calls: list[uuid.UUID] = []

    def mark_submission(self, submission_id: uuid.UUID) -> SimpleNamespace:
        self.calls.append(submission_id)
        record_llm_cost(Decimal("0.004"))
        if self.raises is not None:
            raise self.raises
        return SimpleNamespace(submission_id=submission_id, marking_error=self.error)


@pytest.fixture
def ready(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    quiz_service: QuizService,
    class_service: ClassService,
    taking_service: QuizTakingService,
    monkeypatch: pytest.MonkeyPatch,
) -> Ready:
    seed_catalogue(pg_sessionmaker)
    monkeypatch.setattr(quiz_router, "threading", SimpleNamespace(Thread=_InlineThread))
    _quiz._use_taking_service(client, taking_service)
    client.app.dependency_overrides[get_usage_meter] = lambda: enforcing_meter(pg_sessionmaker)  # type: ignore[attr-defined]
    teacher, class_id, assignment_id = _quiz._assigned_quiz(
        quiz_service, class_service, pg_sessionmaker
    )
    student = _quiz._enroll(pg_sessionmaker, class_id)
    _quiz._auth_as(client, student, Role.student)
    client.get(f"/api/student/quizzes/{assignment_id}")
    return client, student, teacher, assignment_id, pg_sessionmaker


def _use_marking(client: TestClient, marking: _CostlyMarking) -> None:
    client.app.dependency_overrides[get_quiz_marking_service] = lambda: marking  # type: ignore[attr-defined]


def _submit(client: TestClient, assignment_id: str) -> Response:
    return client.post(f"/api/student/quizzes/{assignment_id}/submit")


def _remaining(sm: sessionmaker[Session], grant_id: uuid.UUID) -> int:
    with sm() as session:
        balance = session.get(UsageGrantBalance, grant_id)
        assert balance is not None
        return balance.remaining


def _submission_status(sm: sessionmaker[Session], student: uuid.UUID) -> str:
    with sm() as session:
        return (
            session.scalars(
                select(QuizSubmission.status).where(QuizSubmission.student_id == student)
            )
            .one()
            .value
        )


# -- the server-side target ---------------------------------------------------


def test_the_target_is_the_quizs_subject_and_question_count(ready: Ready) -> None:
    _, student, _, assignment_id, sm = ready
    with sm() as session:
        target = quiz_assignment_target(
            session, student_id=str(student), assignment_id=assignment_id
        )
        malformed = quiz_assignment_target(
            session, student_id=str(student), assignment_id="not-a-uuid"
        )
    assert target is not None
    assert (target.subject_code, target.input_count) == ("0625", 1)
    assert malformed is None


# -- 402 before acceptance ----------------------------------------------------


def test_submit_without_balance_is_402_and_the_submission_stays_open(ready: Ready) -> None:
    client, student, _, assignment_id, sm = ready
    marking = _CostlyMarking()
    _use_marking(client, marking)
    resp = _submit(client, assignment_id)
    assert resp.status_code == 402
    # base 1-2 + 1 question x 1-3 = 2-5
    assert resp.json() == {
        "error": "usage_blocked",
        "reason": "no_active_plan",
        "estimate": [2, 5],
    }
    assert _submission_status(sm, student) == "in_progress"
    assert marking.calls == []
    assert jobs_for(sm, student) == []


def test_a_blocked_student_can_submit_once_funded(ready: Ready) -> None:
    client, student, _, assignment_id, sm = ready
    _use_marking(client, _CostlyMarking())
    assert _submit(client, assignment_id).status_code == 402
    give(sm, student, units=100)
    assert _submit(client, assignment_id).status_code == 200
    assert _submission_status(sm, student) == "submitted"


def test_insufficient_credits_is_402_with_that_reason(ready: Ready) -> None:
    client, student, _, assignment_id, sm = ready
    give(sm, student, units=1)  # the estimate's high end is 5
    resp = _submit(client, assignment_id)
    assert resp.status_code == 402
    assert resp.json()["reason"] == "insufficient_credits"
    assert _submission_status(sm, student) == "in_progress"


def test_an_exhausted_plan_is_402_usage_limit_reached(ready: Ready) -> None:
    client, student, _, assignment_id, sm = ready
    add_teacher_plan(sm, student, included_seats=0, audience=PlanAudience.student)
    give(sm, student, units=1, kind=GrantKind.period_allowance, visible=False)
    resp = _submit(client, assignment_id)
    assert resp.status_code == 402
    assert resp.json()["reason"] == "usage_limit_reached"
    assert _submission_status(sm, student) == "in_progress"


def test_a_seat_that_covers_the_subject_but_not_the_action_is_402_out_of_seat_scope(
    ready: Ready,
) -> None:
    client, student, teacher, assignment_id, sm = ready
    member = seat(
        sm,
        teacher=teacher,
        student=student,
        subjects=["0625"],
        actions=[MeteredAction.GENERATE_FLASHCARDS],
    )
    seat_grant(sm, student=student, member_id=member, units=100)
    resp = _submit(client, assignment_id)
    assert resp.status_code == 402
    assert resp.json()["reason"] == "out_of_seat_scope"
    assert _submission_status(sm, student) == "in_progress"


def test_a_seat_for_another_subject_does_not_pay(ready: Ready) -> None:
    client, student, teacher, assignment_id, sm = ready
    member = seat(
        sm, teacher=teacher, student=student, subjects=["0580"], actions=[MeteredAction.MARK_QUIZ]
    )
    seat_units = seat_grant(sm, student=student, member_id=member, units=100)
    resp = _submit(client, assignment_id)
    assert resp.status_code == 402
    assert resp.json()["reason"] == "no_active_plan"
    assert _remaining(sm, seat_units) == 100
    assert jobs_for(sm, student) == []


# -- who pays ------------------------------------------------------------------


def test_own_balance_pays_when_no_seat_covers_the_quiz(ready: Ready) -> None:
    client, student, _, assignment_id, sm = ready
    own = give(sm, student, units=100)
    _use_marking(client, _CostlyMarking())
    assert _submit(client, assignment_id).status_code == 200
    (job,) = jobs_for(sm, student)
    assert (job.action, job.status, job.charged, job.teacher_member_id) == (
        "mark_quiz",
        UsageJobStatus.settled,
        4,
        None,
    )
    assert _remaining(sm, own) == 96


def test_a_covering_seat_pays_before_the_students_own_balance(ready: Ready) -> None:
    client, student, teacher, assignment_id, sm = ready
    own = give(sm, student, units=100)
    member = seat(
        sm, teacher=teacher, student=student, subjects=["0625"], actions=[MeteredAction.MARK_QUIZ]
    )
    seat_units = seat_grant(sm, student=student, member_id=member, units=100)
    _use_marking(client, _CostlyMarking())
    assert _submit(client, assignment_id).status_code == 200
    (job,) = jobs_for(sm, student)
    assert (job.status, job.charged, job.teacher_member_id) == (UsageJobStatus.settled, 4, member)
    assert _remaining(sm, seat_units) == 96
    assert _remaining(sm, own) == 100


def test_a_seat_without_the_action_does_not_pay(ready: Ready) -> None:
    client, student, teacher, assignment_id, sm = ready
    own = give(sm, student, units=100)
    member = seat(
        sm,
        teacher=teacher,
        student=student,
        subjects=["0625"],
        actions=[MeteredAction.GENERATE_FLASHCARDS],
    )
    seat_units = seat_grant(sm, student=student, member_id=member, units=100)
    _use_marking(client, _CostlyMarking())
    assert _submit(client, assignment_id).status_code == 200
    assert _remaining(sm, seat_units) == 100
    assert _remaining(sm, own) == 96


# -- failures release ----------------------------------------------------------


@pytest.mark.parametrize("error", ["model refused", "integrity check failed: low coverage"])
def test_a_recorded_marking_error_is_released_and_charges_nothing(ready: Ready, error: str) -> None:
    client, student, _, assignment_id, sm = ready
    own = give(sm, student, units=100)
    _use_marking(client, _CostlyMarking(error=error))
    assert _submit(client, assignment_id).status_code == 200
    (job,) = jobs_for(sm, student)
    assert (job.status, job.charged) == (UsageJobStatus.released, 0)
    assert _remaining(sm, own) == 100


@pytest.mark.parametrize("failure", [QuizMarkingError("state race"), RuntimeError("thread died")])
def test_a_marking_thread_that_raises_is_released_and_charges_nothing(
    ready: Ready, failure: Exception
) -> None:
    client, student, _, assignment_id, sm = ready
    own = give(sm, student, units=100)
    _use_marking(client, _CostlyMarking(raises=failure))
    assert _submit(client, assignment_id).status_code == 200
    (job,) = jobs_for(sm, student)
    assert (job.status, job.charged) == (UsageJobStatus.released, 0)
    assert _remaining(sm, own) == 100


def test_a_thread_that_cannot_start_releases_the_hold(
    ready: Ready, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, student, _, assignment_id, sm = ready
    own = give(sm, student, units=100)
    _use_marking(client, _CostlyMarking())

    class _NoThread:
        def __init__(self, target: Callable[[], None], daemon: bool) -> None:
            pass

        def start(self) -> None:
            raise RuntimeError("can't start new thread")

    monkeypatch.setattr(quiz_router, "threading", SimpleNamespace(Thread=_NoThread))
    with pytest.raises(RuntimeError, match="can't start new thread"):
        _submit(client, assignment_id)
    (job,) = jobs_for(sm, student)
    assert (job.status, job.charged) == (UsageJobStatus.released, 0)
    assert _remaining(sm, own) == 100


# -- no double charge, no hold for a refused submit ----------------------------


def test_a_resubmit_is_refused_and_charges_once(ready: Ready) -> None:
    client, student, _, assignment_id, sm = ready
    own = give(sm, student, units=100)
    marking = _CostlyMarking()
    _use_marking(client, marking)
    assert _submit(client, assignment_id).status_code == 200
    assert _submit(client, assignment_id).status_code == 422
    jobs = jobs_for(sm, student)
    assert [j.status for j in jobs] == [UsageJobStatus.settled, UsageJobStatus.released]
    assert sum(j.charged for j in jobs) == 4
    assert len(marking.calls) == 1
    assert _remaining(sm, own) == 96


def test_a_submit_before_opening_the_quiz_is_refused_and_holds_nothing(
    ready: Ready, quiz_service: QuizService, class_service: ClassService
) -> None:
    client, _, _, _, sm = ready
    _, class_id, other_assignment = _quiz._assigned_quiz(quiz_service, class_service, sm)
    late = _quiz._enroll(sm, class_id)
    _quiz._auth_as(client, late, Role.student)
    own = give(sm, late, units=100)
    marking = _CostlyMarking()
    _use_marking(client, marking)
    assert _submit(client, other_assignment).status_code == 422
    assert [j.status for j in jobs_for(sm, late)] == [UsageJobStatus.released]
    assert _remaining(sm, own) == 100
    assert marking.calls == []


# -- ownership ------------------------------------------------------------------


def test_a_foreign_assignment_is_403_with_no_hold(ready: Ready) -> None:
    client, _, _, assignment_id, sm = ready
    outsider = seed_user(sm, Role.student)
    own = give(sm, outsider, units=100)
    _quiz._auth_as(client, outsider, Role.student)
    marking = _CostlyMarking()
    _use_marking(client, marking)
    resp = _submit(client, assignment_id)
    assert resp.status_code == 403
    assert jobs_for(sm, outsider) == []
    assert _remaining(sm, own) == 100
    assert marking.calls == []


def test_a_foreign_assignment_is_not_billed_even_with_a_seat_for_its_subject(
    ready: Ready,
) -> None:
    client, _, teacher, assignment_id, sm = ready
    outsider = seed_user(sm, Role.student)
    member = seat(
        sm, teacher=teacher, student=outsider, subjects=["0625"], actions=[MeteredAction.MARK_QUIZ]
    )
    seat_units = seat_grant(sm, student=outsider, member_id=member, units=100)
    _quiz._auth_as(client, outsider, Role.student)
    _use_marking(client, _CostlyMarking())
    assert _submit(client, assignment_id).status_code == 403
    assert jobs_for(sm, outsider) == []
    assert _remaining(sm, seat_units) == 100


def test_an_unknown_assignment_is_404_with_no_hold(ready: Ready) -> None:
    client, student, _, _, sm = ready
    give(sm, student, units=100)
    resp = _submit(client, str(uuid.uuid4()))
    assert resp.status_code == 404
    assert jobs_for(sm, student) == []


def test_a_malformed_assignment_id_keeps_todays_422_with_no_hold(ready: Ready) -> None:
    client, student, _, _, sm = ready
    give(sm, student, units=100)
    assert _submit(client, "not-a-uuid").status_code == 422
    assert jobs_for(sm, student) == []
