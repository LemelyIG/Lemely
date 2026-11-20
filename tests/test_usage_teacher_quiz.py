"""Metering on teacher quiz preview and generation (phase 04 Task 11).

``POST /api/quizzes/preview`` is metered as ``preview_quiz`` and ``POST /api/quizzes/generate``
as ``generate_quiz``. Both routes are synchronous: FastAPI runs each in one worker thread, so
``meter.job(usage)`` reserves and runs (settles or releases) in that thread. The estimate input
is the requested question ``count`` (clamped by the meter); the route's ``subject_code`` query
is client input and never reaches the meter. The 402 comes before any model call, and work that
fails, or produces no question, charges nothing (billing spec §2.4). An assistant acting for a
lead is charged to the lead within its cap (R4).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from lemely.core.generation import GeneratedQuestion, GeneratedQuiz
from lemely.core.metered_actions import JOB_SLACK, MAX_ESTIMATE_INPUTS
from lemely.db.class_repo import ClassService
from lemely.db.models.enums import (
    DifficultySource,
    ExamBoard,
    QuestionDifficulty,
    QuestionSource,
    Role,
)
from lemely.db.models.quizzes import QuestionBank
from lemely.db.models.team import TeacherMember, TeacherMemberStatus
from lemely.db.models.usage import UsageGrantBalance, UsageJobStatus
from lemely.db.question_bank_repo import QuestionBankService
from lemely.db.quiz_repo import QuizNotFoundError, QuizService
from lemely.db.teacher_team_repo import TeacherTeamStore
from lemely.db.usage_ledger_repo import UsageLedger
from lemely.io.llm.cost_meter import record_llm_cost
from lemely.web import create_app
from lemely.web.deps import (
    ACTING_TEACHER_HEADER,
    AuthContext,
    get_auth_context,
    get_class_service,
    get_gemini_client,
    get_history_store,
    get_question_bank_service,
    get_quiz_service,
    get_teacher_team_store,
)
from lemely.web.routers import teacher as teacher_router
from lemely.web.usage import (
    USAGE_UNAVAILABLE_MESSAGE,
    USAGE_UNAVAILABLE_RETRY_AFTER,
    MeteredJob,
    UsageGrantContext,
    UsageMeter,
    UsageRequest,
    get_usage_meter,
)
from tests.usage_helpers import (
    NOW,
    assistant,
    enforcing_meter,
    give,
    jobs_for,
    seed_catalogue,
    seed_user,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from httpx import Response
    from sqlalchemy.orm import Session, sessionmaker

_ROUTES = [("/api/quizzes/preview", "preview_quiz"), ("/api/quizzes/generate", "generate_quiz")]
_PATHS = [path for path, _action in _ROUTES]


def _quiz(questions: int = 1) -> GeneratedQuiz:
    return GeneratedQuiz(
        subject_code="0580",
        questions=[
            GeneratedQuestion(
                topic="algebra",
                difficulty="standard",
                prompt=f"Solve for x, variant {i}.",
                model_answer="x = 2",
                mark_scheme_points=["isolate x"],
                total_marks=2,
            )
            for i in range(questions)
        ],
    )


class _SpyMeter(UsageMeter):
    """Records every authorize call, so a test can see what the server asked the meter."""

    def __init__(self, sm: sessionmaker[Session]) -> None:
        base = enforcing_meter(sm)
        super().__init__(sm, enforce=True, now=base.now)
        self.requests: list[UsageRequest] = []

    def authorize(self, request: UsageRequest) -> UsageGrantContext:
        self.requests.append(request)
        return super().authorize(request)


@dataclass
class _Api:
    client: TestClient
    sm: sessionmaker[Session]
    bank: MagicMock
    meter: UsageMeter
    builds: list[dict[str, object]] = field(default_factory=list)
    #: What the stubbed quiz builder does: records cost and returns this quiz.
    produce: Callable[[], GeneratedQuiz] = _quiz

    def as_teacher(self, user: uuid.UUID, role: str = "teacher") -> None:
        self.client.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[attr-defined]
            user_id=str(user), role=role
        )

    def post(self, path: str, *, acting_for: uuid.UUID | None = None, **params: object) -> Response:
        headers = {ACTING_TEACHER_HEADER: str(acting_for)} if acting_for is not None else {}
        return self.client.post(path, params=params, headers=headers)


@pytest.fixture
def api(
    migrated_sessionmaker: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> Iterator[_Api]:
    sm = migrated_sessionmaker
    seed_catalogue(sm)
    classes = MagicMock()
    classes.member_school_ids.return_value = []
    app = create_app()
    state = _Api(client=TestClient(app), sm=sm, bank=MagicMock(), meter=enforcing_meter(sm))

    def _build(*_a: object, **kwargs: object) -> tuple[GeneratedQuiz, set[str]]:
        state.builds.append(dict(kwargs))
        record_llm_cost(Decimal("0.008"))
        return state.produce(), set()

    monkeypatch.setattr(teacher_router, "_build_quiz", _build)
    app.dependency_overrides[get_usage_meter] = lambda: state.meter
    app.dependency_overrides[get_history_store] = lambda: MagicMock()
    app.dependency_overrides[get_gemini_client] = lambda: MagicMock()
    app.dependency_overrides[get_class_service] = lambda: classes
    app.dependency_overrides[get_question_bank_service] = lambda: state.bank
    app.dependency_overrides[get_teacher_team_store] = lambda: TeacherTeamStore(sm)
    yield state
    app.dependency_overrides.clear()


def _remaining(sm: sessionmaker[Session], grant_id: uuid.UUID) -> tuple[int, int]:
    with sm() as session:
        balance = session.get(UsageGrantBalance, grant_id)
        assert balance is not None
        return balance.remaining, balance.held


# --- the 402 comes first --------------------------------------------------------------------


@pytest.mark.parametrize("path", _PATHS)
def test_without_balance_is_402_before_any_model_call(api: _Api, path: str) -> None:
    teacher = seed_user(api.sm, Role.teacher)
    api.as_teacher(teacher)
    resp = api.post(path, subject_code="0580", count=3)
    assert resp.status_code == 402
    # base 2-4 + 3 questions x 2-5 = 8-19
    assert resp.json() == {
        "error": "usage_blocked",
        "reason": "no_active_plan",
        "estimate": [8, 19],
    }
    assert api.builds == []
    assert jobs_for(api.sm, teacher) == []
    api.bank.add_questions.assert_not_called()


@pytest.mark.parametrize("path", _PATHS)
def test_out_of_credits_is_402_with_the_reason_and_holds_nothing(api: _Api, path: str) -> None:
    teacher = seed_user(api.sm, Role.teacher)
    grant = give(api.sm, teacher, units=10)  # below the 19-unit top of the range
    api.as_teacher(teacher)
    resp = api.post(path, count=3)
    assert resp.status_code == 402
    body = resp.json()
    assert (body["error"], body["reason"], body["estimate"]) == (
        "usage_blocked",
        "insufficient_credits",
        [8, 19],
    )
    assert api.builds == []
    assert jobs_for(api.sm, teacher) == []
    assert _remaining(api.sm, grant) == (10, 0)


# --- the estimate is the requested count, read on the server -------------------------------


@pytest.mark.parametrize(
    ("path", "params", "estimate"),
    [
        # Each route keeps its own default count (4 and 5): base 2-4 + n x 2-5.
        ("/api/quizzes/preview", {}, [10, 24]),
        ("/api/quizzes/generate", {}, [12, 29]),
        # 50 is the largest accepted count, and the estimate's own clamp.
        ("/api/quizzes/preview", {"count": 50}, [102, 254]),
        ("/api/quizzes/generate", {"count": 1}, [4, 9]),
    ],
)
def test_the_estimate_counts_the_requested_questions(
    api: _Api, path: str, params: dict[str, int], estimate: list[int]
) -> None:
    teacher = seed_user(api.sm, Role.teacher)
    api.as_teacher(teacher)
    resp = api.post(path, **params)
    assert resp.status_code == 402
    assert resp.json()["estimate"] == estimate


@pytest.mark.parametrize(("path", "action"), _ROUTES)
def test_the_meter_is_asked_about_the_action_and_never_the_clients_subject(
    api: _Api, migrated_sessionmaker: sessionmaker[Session], path: str, action: str
) -> None:
    spy = _SpyMeter(migrated_sessionmaker)
    api.meter = spy
    teacher = seed_user(api.sm, Role.teacher)
    give(api.sm, teacher, units=500)
    api.as_teacher(teacher)
    assert api.post(path, subject_code="0580", count=3).status_code == 200
    (request,) = spy.requests
    assert request.action.value == action
    assert request.subject_code is None
    assert request.input_count == 3
    assert request.actor_user_id == teacher
    assert request.assistant_member_id is None


# --- success and failure --------------------------------------------------------------------


@pytest.mark.parametrize(("path", "action"), _ROUTES)
def test_success_charges_the_generation_cost(api: _Api, path: str, action: str) -> None:
    teacher = seed_user(api.sm, Role.teacher)
    grant = give(api.sm, teacher, units=500)
    api.as_teacher(teacher)
    assert api.post(path, subject_code="0580", count=3).status_code == 200
    (job,) = jobs_for(api.sm, teacher)
    assert (job.action, job.status, job.charged) == (action, UsageJobStatus.settled, 8)
    assert (job.estimate_low, job.estimate_high) == (8, 19)
    assert _remaining(api.sm, grant) == (492, 0)


def test_generate_persists_the_questions_and_preview_does_not(api: _Api) -> None:
    teacher = seed_user(api.sm, Role.teacher)
    give(api.sm, teacher, units=500)
    api.as_teacher(teacher)
    assert api.post("/api/quizzes/preview", count=3).status_code == 200
    api.bank.add_questions.assert_not_called()
    assert api.post("/api/quizzes/generate", count=3).status_code == 200
    api.bank.add_questions.assert_called_once()


@pytest.mark.parametrize(("path", "action"), _ROUTES)
def test_a_failed_generation_is_released_and_charges_nothing(
    api: _Api, monkeypatch: pytest.MonkeyPatch, path: str, action: str
) -> None:
    def _down(*_a: object, **_k: object) -> object:
        record_llm_cost(Decimal("0.004"))  # a call was made and priced before it failed
        raise HTTPException(status_code=503, detail="Quiz generation is temporarily unavailable")

    monkeypatch.setattr(teacher_router, "_build_quiz", _down)
    teacher = seed_user(api.sm, Role.teacher)
    grant = give(api.sm, teacher, units=500)
    api.as_teacher(teacher)
    assert api.post(path, count=3).status_code == 503
    (job,) = jobs_for(api.sm, teacher)
    assert (job.action, job.status, job.charged, job.debt_created) == (
        action,
        UsageJobStatus.released,
        0,
        0,
    )
    assert _remaining(api.sm, grant) == (500, 0)
    api.bank.add_questions.assert_not_called()


@pytest.mark.parametrize(("path", "action"), _ROUTES)
def test_an_empty_generation_is_released_and_charges_nothing(
    api: _Api, path: str, action: str
) -> None:
    """No question came back without raising: abandon, never settle a paid-for nothing."""
    api.produce = lambda: _quiz(questions=0)
    teacher = seed_user(api.sm, Role.teacher)
    grant = give(api.sm, teacher, units=500)
    api.as_teacher(teacher)
    resp = api.post(path, count=3)
    assert resp.status_code == 200  # the response is unchanged
    assert resp.json()["questions"] == []
    (job,) = jobs_for(api.sm, teacher)
    assert (job.action, job.status, job.charged) == (action, UsageJobStatus.released, 0)
    assert _remaining(api.sm, grant) == (500, 0)


# --- hold renewal at the start of the work ---------------------------------------------------


class _LosesTheHoldBeforeTheWork(UsageMeter):
    """Expires the reserved hold and lets another job take its balance, before ``run()``."""

    def __init__(self, sm: sessionmaker[Session]) -> None:
        self.clock = [NOW]
        super().__init__(sm, enforce=True, now=lambda: self.clock[0])

    def reserve(self, ctx: UsageGrantContext) -> MeteredJob:
        job = super().reserve(ctx)
        self.clock[0] = NOW + timedelta(hours=2)
        with self.sessionmaker.begin() as session:
            assert UsageLedger(session).expire_stale_jobs(now=self.clock[0]) == 1
        # The released balance now covers exactly one more job: this one.
        super().reserve(self.authorize(ctx.request))
        return job


@pytest.mark.parametrize("path", _PATHS)
def test_a_hold_that_cannot_be_renewed_is_the_same_402_before_the_model(
    api: _Api, path: str
) -> None:
    api.meter = _LosesTheHoldBeforeTheWork(api.sm)
    teacher = seed_user(api.sm, Role.teacher)
    give(api.sm, teacher, units=19)
    api.as_teacher(teacher)
    resp = api.post(path, count=3)
    assert resp.status_code == 402
    assert resp.json() == {
        "error": "usage_blocked",
        "reason": "insufficient_credits",
        "estimate": [8, 19],
    }
    assert api.builds == []
    api.bank.add_questions.assert_not_called()
    statuses = [j.status for j in jobs_for(api.sm, teacher)]
    assert sorted(statuses, key=lambda s: s.value) == [UsageJobStatus.expired, UsageJobStatus.open]


class _ClockJumpsAfterTheReserve(UsageMeter):
    """Lets the reserved lease run down before ``run()``, as a queued job's would."""

    def __init__(self, sm: sessionmaker[Session]) -> None:
        self.clock = [NOW]
        super().__init__(sm, enforce=True, now=lambda: self.clock[0])

    def reserve(self, ctx: UsageGrantContext) -> MeteredJob:
        job = super().reserve(ctx)
        self.clock[0] = NOW + JOB_SLACK + timedelta(minutes=1)  # under one job_timeout left
        return job


@pytest.mark.parametrize(("path", "action"), _ROUTES)
def test_a_ledger_that_cannot_extend_the_hold_is_a_plain_503_before_the_model(
    api: _Api, monkeypatch: pytest.MonkeyPatch, path: str, action: str
) -> None:
    """The real failure, not a forced one: ``UsageLedger.extend`` fails both attempts."""
    api.meter = _ClockJumpsAfterTheReserve(api.sm)
    extends: list[int] = []

    def _ledger_down(*_a: object, **_k: object) -> object:
        extends.append(1)
        raise OperationalError("UPDATE", {}, Exception("ledger down"))

    monkeypatch.setattr(UsageLedger, "extend", _ledger_down)
    teacher = seed_user(api.sm, Role.teacher)
    grant = give(api.sm, teacher, units=500)
    api.as_teacher(teacher)
    resp = api.post(path, count=3)
    assert resp.status_code == 503
    assert resp.headers["Retry-After"] == str(USAGE_UNAVAILABLE_RETRY_AFTER)
    assert resp.json() == {"error": "usage_unavailable", "message": USAGE_UNAVAILABLE_MESSAGE}
    assert len(extends) == 2
    assert api.builds == []
    api.bank.add_questions.assert_not_called()
    (job,) = jobs_for(api.sm, teacher)
    assert (job.action, job.status, job.charged) == (action, UsageJobStatus.released, 0)
    assert _remaining(api.sm, grant) == (500, 0)


def test_a_failed_bank_write_releases_the_hold_and_charges_nothing(api: _Api) -> None:
    """The persist is part of the metered work: a write that fails must not be billed."""
    api.bank.add_questions.side_effect = RuntimeError("bank write failed")
    teacher = seed_user(api.sm, Role.teacher)
    grant = give(api.sm, teacher, units=500)
    api.as_teacher(teacher)
    resp = TestClient(api.client.app, raise_server_exceptions=False).post(
        "/api/quizzes/generate", params={"count": 3}
    )
    assert resp.status_code == 500
    api.bank.add_questions.assert_called_once()
    (job,) = jobs_for(api.sm, teacher)
    assert (job.action, job.status, job.charged) == (
        "generate_quiz",
        UsageJobStatus.released,
        0,
    )
    assert _remaining(api.sm, grant) == (500, 0)


def test_an_empty_generation_writes_nothing_to_the_bank(api: _Api) -> None:
    api.produce = lambda: _quiz(questions=0)
    teacher = seed_user(api.sm, Role.teacher)
    give(api.sm, teacher, units=500)
    api.as_teacher(teacher)
    assert api.post("/api/quizzes/generate", count=3).status_code == 200
    api.bank.add_questions.assert_not_called()


# --- roles and the team ----------------------------------------------------------------------


@pytest.mark.parametrize("path", _PATHS)
def test_a_wrong_role_is_403_before_the_meter_reads_anything(api: _Api, path: str) -> None:
    spy = _SpyMeter(api.sm)
    api.meter = spy
    student = seed_user(api.sm, Role.student)
    give(api.sm, student, units=500)
    api.as_teacher(student, role="student")
    assert api.post(path, count=3).status_code == 403
    assert spy.requests == []
    assert api.builds == []
    assert jobs_for(api.sm, student) == []


@pytest.mark.parametrize(("path", "action"), _ROUTES)
def test_the_lead_pays_for_an_assistant_never_the_assistant(
    api: _Api, path: str, action: str
) -> None:
    """R4: quiz generation under the acting-teacher header bills the lead teacher."""
    sm = api.sm
    lead, helper = seed_user(sm, Role.teacher), seed_user(sm, Role.teacher)
    own = give(sm, helper, units=500)
    member = assistant(sm, teacher=lead, member=helper)
    api.as_teacher(helper)
    # The lead has nothing; the helper's own 500 never counts.
    blocked = api.post(path, acting_for=lead, count=3)
    assert blocked.status_code == 402
    assert blocked.json()["reason"] == "no_active_plan"
    assert api.builds == []
    lead_grant = give(sm, lead, units=500)
    assert api.post(path, acting_for=lead, count=3).status_code == 200
    (job,) = jobs_for(sm, helper)
    assert (job.action, job.teacher_member_id, job.status, job.charged) == (
        action,
        member,
        UsageJobStatus.settled,
        8,
    )
    assert jobs_for(sm, lead) == []
    assert _remaining(sm, own) == (500, 0)
    assert _remaining(sm, lead_grant) == (492, 0)


@pytest.mark.parametrize("path", _PATHS)
def test_an_assistant_over_its_cap_is_402_and_the_lead_pays_nothing(api: _Api, path: str) -> None:
    sm = api.sm
    lead, helper = seed_user(sm, Role.teacher), seed_user(sm, Role.teacher)
    lead_grant = give(sm, lead, units=5000)
    assistant(sm, teacher=lead, member=helper, cap_units=5)  # below the 19-unit top of range
    api.as_teacher(helper)
    resp = api.post(path, acting_for=lead, count=3)
    assert resp.status_code == 402
    assert resp.json()["reason"] == "insufficient_credits"
    assert api.builds == []
    assert jobs_for(sm, helper) == []
    assert _remaining(sm, lead_grant) == (5000, 0)


@pytest.mark.parametrize("path", _PATHS)
def test_a_removed_assistant_is_403_and_never_falls_back_to_its_own_balance(
    api: _Api, path: str
) -> None:
    sm = api.sm
    lead, helper = seed_user(sm, Role.teacher), seed_user(sm, Role.teacher)
    give(sm, lead, units=500)
    own = give(sm, helper, units=500)
    member = assistant(sm, teacher=lead, member=helper)
    with sm.begin() as session:
        row = session.get(TeacherMember, member)
        assert row is not None
        row.status = TeacherMemberStatus.removed
    api.as_teacher(helper)
    resp = api.post(path, acting_for=lead, count=3)
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "team_permission_denied"
    assert api.builds == []
    assert jobs_for(sm, helper) == []
    assert _remaining(sm, own) == (500, 0)


class _RemovesTheAssistantFirst(UsageMeter):
    """Removes the assistant row between the team guard and the meter's chain load."""

    def __init__(self, sm: sessionmaker[Session], member: uuid.UUID) -> None:
        base = enforcing_meter(sm)
        super().__init__(sm, enforce=True, now=base.now)
        self._member = member

    def authorize(self, request: UsageRequest) -> UsageGrantContext:
        with self.sessionmaker.begin() as session:
            row = session.get(TeacherMember, self._member)
            assert row is not None
            row.status = TeacherMemberStatus.removed
        return super().authorize(request)


@pytest.mark.parametrize("path", _PATHS)
def test_an_assistant_removed_after_the_guard_is_the_meters_403(api: _Api, path: str) -> None:
    sm = api.sm
    lead, helper = seed_user(sm, Role.teacher), seed_user(sm, Role.teacher)
    give(sm, lead, units=500)
    own = give(sm, helper, units=500)
    member = assistant(sm, teacher=lead, member=helper)
    api.meter = _RemovesTheAssistantFirst(sm, member)
    api.as_teacher(helper)
    resp = api.post(path, acting_for=lead, count=3)
    assert resp.status_code == 403
    assert api.builds == []
    assert jobs_for(sm, helper) == []
    assert _remaining(sm, own) == (500, 0)


# --- the count is bounded on the wire ---------------------------------------------------------


@pytest.mark.parametrize("path", _PATHS)
@pytest.mark.parametrize("count", [51, 1000, 0, -5])
def test_a_count_outside_one_to_fifty_is_422_before_the_meter_or_the_model(
    api: _Api, path: str, count: int
) -> None:
    spy = _SpyMeter(api.sm)
    api.meter = spy
    teacher = seed_user(api.sm, Role.teacher)
    give(api.sm, teacher, units=5000)
    api.as_teacher(teacher)
    assert api.post(path, count=count).status_code == 422
    assert spy.requests == []
    assert api.builds == []
    assert jobs_for(api.sm, teacher) == []


def test_the_largest_accepted_count_is_held_in_full(api: _Api) -> None:
    teacher = seed_user(api.sm, Role.teacher)
    grant = give(api.sm, teacher, units=5000)
    api.as_teacher(teacher)
    assert api.post("/api/quizzes/generate", count=50).status_code == 200
    (job,) = jobs_for(api.sm, teacher)
    assert (job.estimate_low, job.estimate_high, job.charged) == (102, 254, 8)
    assert _remaining(api.sm, grant) == (4992, 0)


def test_the_draft_quiz_count_is_bounded_at_fifty() -> None:
    from pydantic import ValidationError

    from lemely.web.schemas_quiz import UpdateQuizDraftRequestDTO

    assert UpdateQuizDraftRequestDTO(requestedCount=50).requestedCount == 50
    assert UpdateQuizDraftRequestDTO(requestedCount=0).requestedCount == 0
    assert UpdateQuizDraftRequestDTO().requestedCount is None
    for bad in (51, 1000, -1):
        with pytest.raises(ValidationError):
            UpdateQuizDraftRequestDTO(requestedCount=bad)


def test_patching_a_draft_over_fifty_questions_is_422_and_never_reaches_the_service(
    api: _Api,
) -> None:
    service = MagicMock()
    service.patch_draft.side_effect = QuizNotFoundError("no such quiz")
    api.client.app.dependency_overrides[get_quiz_service] = lambda: service  # type: ignore[attr-defined]
    api.as_teacher(seed_user(api.sm, Role.teacher))
    url = "/api/teacher/quizzes/00000000-0000-0000-0000-000000000001"
    assert api.client.patch(url, json={"requestedCount": 51}).status_code == 422
    service.patch_draft.assert_not_called()
    # 50 passes validation and reaches the service (which refuses the made-up id).
    assert api.client.patch(url, json={"requestedCount": 50}).status_code == 404
    service.patch_draft.assert_called_once()


# --- materializing a draft's questions is not model work --------------------------------------


def test_materializing_a_quiz_from_the_bank_is_not_metered(api: _Api) -> None:
    """``POST /teacher/quizzes/{id}/questions/generate`` selects stored bank rows.

    ``QuizService.generate_questions`` is a deterministic bank query: ``lemely.db`` holds no
    model client, so the route costs nothing. Metering it would only block a teacher with no
    credits from a free action, so it takes no ``require_usage``. A teacher with no balance
    succeeds, and nothing is reserved. Another teacher's quiz keeps its existing 403.
    """
    sm = api.sm
    service = QuizService(sm, ClassService(sm), QuestionBankService(sm))
    api.client.app.dependency_overrides[get_quiz_service] = lambda: service  # type: ignore[attr-defined]
    spy = _SpyMeter(sm)
    api.meter = spy
    owner, intruder = seed_user(sm, Role.teacher), seed_user(sm, Role.teacher)
    quiz = service.create_quiz(owner, "0625", "Recap")
    service.patch_draft(
        owner, quiz.quiz_id, pool_source=QuestionSource.generated, requested_count=3
    )
    url = f"/api/teacher/quizzes/{quiz.quiz_id}/questions/generate"
    api.as_teacher(owner)  # no grant at all
    assert api.client.post(url).status_code == 200
    api.as_teacher(intruder)
    assert api.client.post(url).status_code == 403
    assert spy.requests == []
    assert jobs_for(sm, owner) == []
    assert jobs_for(sm, intruder) == []


def test_a_full_quiz_cannot_materialize_more_questions(api: _Api) -> None:
    """At the 50-question ceiling the route answers 422 and adds nothing, unmetered."""
    sm = api.sm
    service = QuizService(sm, ClassService(sm), QuestionBankService(sm))
    api.client.app.dependency_overrides[get_quiz_service] = lambda: service  # type: ignore[attr-defined]
    spy = _SpyMeter(sm)
    api.meter = spy
    owner = seed_user(sm, Role.teacher)
    quiz = service.create_quiz(owner, "0625", "Full")
    service.patch_draft(
        owner, quiz.quiz_id, pool_source=QuestionSource.generated, requested_count=50
    )
    with sm.begin() as session:
        session.add_all(
            QuestionBank(
                id=uuid.uuid4(),
                board=ExamBoard.caie,
                subject_code="0625",
                source=QuestionSource.generated,
                owner_id=owner,
                difficulty=list(QuestionDifficulty)[i % 3],
                difficulty_source=DifficultySource.declared_by_generator,
                question_type="explanation",
                prompt=f"Bank question {i}",
                total_marks=2,
            )
            for i in range(120)
        )
    api.as_teacher(owner)
    url = f"/api/teacher/quizzes/{quiz.quiz_id}/questions/generate"
    first = api.client.post(url)
    assert first.status_code == 200
    assert len(service.get_quiz(owner, quiz.quiz_id).questions) == MAX_ESTIMATE_INPUTS
    again = api.client.post(url)
    assert again.status_code == 422
    assert "50" in again.json()["detail"]
    assert len(service.get_quiz(owner, quiz.quiz_id).questions) == MAX_ESTIMATE_INPUTS
    assert spy.requests == []
