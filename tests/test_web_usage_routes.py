"""The usage API (phase 04 Task 7): estimate from server-side records, meter, history."""

from __future__ import annotations

import base64
import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from lemely.core.keyset import encode_cursor
from lemely.core.metered_actions import MeteredAction
from lemely.db.models.enums import Role
from lemely.db.models.quizzes import QuizAssignment
from lemely.db.models.team import AssistantRole
from lemely.db.models.usage import (
    GrantKind,
    UsageDebt,
    UsageEntry,
    UsageGrant,
    UsageGrantBalance,
    UsageJob,
)
from lemely.io.llm.cost_meter import record_llm_cost
from lemely.web import create_app
from lemely.web.deps import (
    ACTING_TEACHER_HEADER,
    AuthContext,
    _team_lead_unavailable,
    _team_permission_denied,
    get_auth_context,
)
from lemely.web.ratelimit import SlidingWindowLimiter
from lemely.web.routers.usage import get_usage_estimate_limiter
from lemely.web.usage import get_usage_meter, request_from_auth
from tests.test_usage_context_repo import (
    _attempt_with_points,
    _put_in_school,
    _quiz_with_assignment,
)
from tests.usage_helpers import (
    NOW,
    assistant,
    enforcing_meter,
    give,
    seat,
    seat_grant,
    seed_catalogue,
    seed_user,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker

_ALLOWANCE_END = datetime(2026, 12, 1, tzinfo=UTC)


def _app(sm: sessionmaker[Session], *, seed: bool) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_usage_meter] = lambda: enforcing_meter(sm)
    # A fresh limiter per test: the production one is process-wide.
    limiter = SlidingWindowLimiter(limit=60, window_seconds=60, clock=lambda: 0.0)
    app.dependency_overrides[get_usage_estimate_limiter] = lambda: limiter
    if seed:
        seed_catalogue(sm)
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def api(migrated_sessionmaker: sessionmaker[Session]) -> Iterator[TestClient]:
    yield from _app(migrated_sessionmaker, seed=True)


@pytest.fixture
def api_without_catalogue(migrated_sessionmaker: sessionmaker[Session]) -> Iterator[TestClient]:
    yield from _app(migrated_sessionmaker, seed=False)


def _as(api: TestClient, user: uuid.UUID, role: Role = Role.student) -> None:
    api.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[union-attr]
        user_id=str(user), role=role.value
    )


def _ledger_counts(sm: sessionmaker[Session]) -> dict[str, int]:
    """Row counts of every ledger table: an estimate must leave all of them alone."""
    with sm() as session:
        return {
            model.__tablename__: int(session.scalar(select(func.count()).select_from(model)) or 0)
            for model in (UsageGrant, UsageGrantBalance, UsageJob, UsageEntry, UsageDebt)
        }


def _run_job(
    sm: sessionmaker[Session],
    user: uuid.UUID,
    cost: str,
    *,
    action: MeteredAction = MeteredAction.MARK_PAPER,
    role: str = "student",
    subject_code: str | None = None,
    assistant_member_id: uuid.UUID | None = None,
) -> None:
    meter = enforcing_meter(sm)
    auth = AuthContext(user_id=str(user), role=role)
    request = request_from_auth(
        auth, action, subject_code=subject_code, assistant_member_id=assistant_member_id
    )
    with meter.job(meter.authorize(request)):
        record_llm_cost(Decimal(cost))


# -- estimate -----------------------------------------------------------------------


def test_estimate_quotes_credits_and_the_range(
    api: TestClient, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    student = seed_user(migrated_sessionmaker)
    give(migrated_sessionmaker, student, units=1000)
    _as(api, student)
    resp = api.post(
        "/api/usage/estimate",
        json={"action": "generate_flashcards", "subjectCode": "0625", "count": 4},
    )
    assert resp.status_code == 200, resp.text
    # base 2-4 + 4 cards x 1-2 = 6-12
    assert resp.json() == {
        "low": 6,
        "high": 12,
        "payer": "credits",
        "percentLow": None,
        "percentHigh": None,
        "blockedReason": None,
    }


def test_estimate_quotes_a_percentage_when_an_allowance_pays(
    api: TestClient, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    student = seed_user(migrated_sessionmaker)
    give(
        migrated_sessionmaker,
        student,
        units=4000,
        kind=GrantKind.period_allowance,
        visible=False,
        expires_at=_ALLOWANCE_END,
    )
    _as(api, student)
    body = api.post("/api/usage/estimate", json={"action": "mark_paper"}).json()
    assert (body["payer"], body["percentLow"], body["percentHigh"]) == ("allowance", 1, 3)


def test_estimate_reports_a_block_without_raising(
    api: TestClient, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    student = seed_user(migrated_sessionmaker)
    _as(api, student)
    resp = api.post("/api/usage/estimate", json={"action": "mark_paper"})
    assert resp.status_code == 200
    body = resp.json()
    assert (body["payer"], body["blockedReason"]) == ("none", "no_active_plan")


def test_estimate_writes_nothing_to_the_ledger_even_on_an_unseeded_catalogue(
    api_without_catalogue: TestClient, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    """No grant, hold, job, entry or debt row, whatever the outcome. Only the reference
    catalogue (rates and estimators) may be seeded lazily, and it is not ledger state."""
    sm = migrated_sessionmaker
    student = seed_user(sm)
    give(sm, student, units=1000)
    attempt_id, question_id = _attempt_with_points(sm, student, subject="0580", points=2)
    assigned = _quiz_with_assignment(sm, subject="0580", included=2)
    before = _ledger_counts(sm)
    _as(api_without_catalogue, student)
    for payload in (
        {"action": "mark_paper"},
        {"action": "study_plan", "subjectCode": "0580"},
        {"action": "generate_flashcards", "subjectCode": "0580", "count": 3},
        {
            "action": "self_review",
            "attemptId": str(attempt_id),
            "questionResultId": str(question_id),
        },
    ):
        resp = api_without_catalogue.post("/api/usage/estimate", json=payload)
        assert resp.status_code == 200, (payload, resp.text)
    # A student who is not in the assignment's audience gets 404, still without a write.
    assert (
        api_without_catalogue.post(
            "/api/usage/estimate",
            json={"action": "mark_quiz", "assignmentId": str(assigned.assignment_id)},
        ).status_code
        == 404
    )
    assert _ledger_counts(sm) == before


def test_estimate_reads_the_subject_and_inputs_on_the_server(
    api: TestClient, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    """The seat decision follows the quiz's stored subject, never ``subjectCode`` or
    ``count`` from the request; the question count comes from the quiz."""
    sm = migrated_sessionmaker
    student, teacher = seed_user(sm), seed_user(sm, Role.teacher)
    give(sm, student, units=1000)
    member = seat(
        sm,
        teacher=teacher,
        student=student,
        subjects=["0580"],
        actions=[MeteredAction.MARK_QUIZ],
    )
    seat_grant(sm, student=student, member_id=member, units=1000)
    in_scope = _quiz_with_assignment(sm, subject="0580", included=3)
    out_of_scope = _quiz_with_assignment(sm, subject="0625", included=3)
    # Both assignments must target this student: re-point them.
    with sm.begin() as session:
        for assigned in (in_scope, out_of_scope):
            row = session.get(QuizAssignment, assigned.assignment_id)
            assert row is not None
            row.student_id = student
    _as(api, student)

    def quote(assigned_id: uuid.UUID, **claims: object) -> dict[str, object]:
        resp = api.post(
            "/api/usage/estimate",
            json={"action": "mark_quiz", "assignmentId": str(assigned_id), **claims},
        )
        assert resp.status_code == 200, resp.text
        body: dict[str, object] = resp.json()
        return body

    inside = quote(in_scope.assignment_id, subjectCode="0625", count=1)
    outside = quote(out_of_scope.assignment_id, subjectCode="0580", count=50)
    assert inside["payer"] == "seat"
    assert outside["payer"] == "credits"
    # 3 included questions: base 1-2 plus 3 x 1-3, whatever ``count`` claims.
    assert (inside["low"], inside["high"]) == (4, 11)
    assert (outside["low"], outside["high"]) == (4, 11)


def test_an_assistants_estimate_is_quoted_against_the_lead(
    api: TestClient, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    """R4: the acting-teacher header quotes team work against the lead's chain."""
    sm = migrated_sessionmaker
    lead, helper = seed_user(sm, Role.teacher), seed_user(sm, Role.teacher)
    give(sm, helper, units=1000)
    assistant(sm, teacher=lead, member=helper)
    _as(api, helper, Role.teacher)
    headers = {ACTING_TEACHER_HEADER: str(lead)}
    body = api.post("/api/usage/estimate", json={"action": "regrade"}, headers=headers).json()
    assert (body["payer"], body["blockedReason"]) == ("none", "no_active_plan")
    own = api.post("/api/usage/estimate", json={"action": "regrade"}).json()
    assert own["payer"] == "credits"
    # Student actions carry no team permission: the header is refused, not ignored.
    study = {"action": "study_plan", "subjectCode": "0580"}
    refused = api.post("/api/usage/estimate", json=study, headers=headers)
    assert refused.status_code == 403
    assert refused.json()["detail"]["code"] == "team_permission_denied"


def test_a_viewer_assistant_cannot_estimate_for_the_lead(
    api: TestClient, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    """A viewer lacks `regrade`, so it gets the route's 403, not the lead's balance."""
    sm = migrated_sessionmaker
    lead, viewer = seed_user(sm, Role.teacher), seed_user(sm, Role.teacher)
    give(sm, lead, units=1000)
    assistant(sm, teacher=lead, member=viewer, role=AssistantRole.viewer)
    _as(api, viewer, Role.teacher)
    resp = api.post(
        "/api/usage/estimate",
        json={"action": "regrade"},
        headers={ACTING_TEACHER_HEADER: str(lead)},
    )
    assert resp.status_code == 403
    assert resp.json() == {"detail": _team_permission_denied().detail}


def test_a_school_leads_assistant_gets_team_lead_unavailable(
    api: TestClient, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    """Same refusal, same body, as the team routes (phase 03 ``assistant_access``)."""
    sm = migrated_sessionmaker
    lead, helper, stranger = (seed_user(sm, Role.teacher) for _ in range(3))
    give(sm, lead, units=1000)
    assistant(sm, teacher=lead, member=helper)
    _put_in_school(sm, lead)
    headers = {ACTING_TEACHER_HEADER: str(lead)}
    _as(api, helper, Role.teacher)
    resp = api.post("/api/usage/estimate", json={"action": "regrade"}, headers=headers)
    assert resp.status_code == 403
    assert resp.json() == {"detail": _team_lead_unavailable().detail}
    assert resp.json()["detail"]["code"] == "team_lead_unavailable"
    # A stranger never learns the lead holds school data.
    _as(api, stranger, Role.teacher)
    hidden = api.post("/api/usage/estimate", json={"action": "regrade"}, headers=headers)
    assert hidden.status_code == 403
    assert hidden.json() == {"detail": _team_permission_denied().detail}


def test_a_bad_acting_teacher_header_is_refused_like_the_team_guard(
    api: TestClient, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    sm = migrated_sessionmaker
    lead, helper, student = seed_user(sm, Role.teacher), seed_user(sm, Role.teacher), seed_user(sm)
    assistant(sm, teacher=lead, member=helper)
    payload = {"action": "regrade"}
    _as(api, helper, Role.teacher)
    for headers in (
        {ACTING_TEACHER_HEADER: "not-a-uuid"},
        {ACTING_TEACHER_HEADER: str(uuid.uuid4())},  # a lead the caller does not assist
    ):
        resp = api.post("/api/usage/estimate", json=payload, headers=headers)
        assert resp.status_code == 403
        assert resp.json()["detail"]["code"] == "team_permission_denied"
    # The one valid header is accepted; repeating it is ambiguous, so refused, not guessed.
    valid = (ACTING_TEACHER_HEADER, str(lead))
    assert api.post("/api/usage/estimate", json=payload, headers=[valid]).status_code == 200
    resp = api.post("/api/usage/estimate", json=payload, headers=[valid, valid])
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "team_permission_denied"
    # A student cannot borrow a lead through the header either.
    _as(api, student)
    resp = api.post("/api/usage/estimate", json=payload, headers={ACTING_TEACHER_HEADER: str(lead)})
    assert resp.status_code == 403
    # Naming yourself is the own-chain path, as on the team routes.
    _as(api, lead, Role.teacher)
    own = api.post("/api/usage/estimate", json=payload, headers={ACTING_TEACHER_HEADER: str(lead)})
    assert own.status_code == 200


def test_estimate_requires_the_fields_its_action_reads(
    api: TestClient, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    _as(api, seed_user(migrated_sessionmaker))
    assert (
        api.post("/api/usage/estimate", json={"action": "generate_flashcards"}).status_code == 422
    )
    assert api.post("/api/usage/estimate", json={"action": "self_review"}).status_code == 422
    assert api.post("/api/usage/estimate", json={"action": "mark_quiz"}).status_code == 422
    assert api.post("/api/usage/estimate", json={"action": "study_plan"}).status_code == 422
    assert api.post("/api/usage/estimate", json={"action": "preview_quiz"}).status_code == 422
    unknown = {"action": "mark_quiz", "assignmentId": str(uuid.uuid4())}
    assert api.post("/api/usage/estimate", json=unknown).status_code == 404


def test_estimate_gives_another_users_record_the_same_not_found_as_a_missing_one(
    api: TestClient, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    """IDOR: a foreign attempt, question or assignment is indistinguishable from none."""
    sm = migrated_sessionmaker
    owner, intruder = seed_user(sm), seed_user(sm)
    give(sm, owner, units=1000)
    give(sm, intruder, units=1000)
    attempt_id, question_id = _attempt_with_points(sm, owner, subject="0580", points=4)
    other_attempt, other_question = _attempt_with_points(sm, intruder, subject="0580", points=1)
    assigned = _quiz_with_assignment(sm, subject="0580", included=3)

    def self_review(attempt: uuid.UUID, question: uuid.UUID) -> tuple[int, object]:
        resp = api.post(
            "/api/usage/estimate",
            json={
                "action": "self_review",
                "attemptId": str(attempt),
                "questionResultId": str(question),
            },
        )
        return resp.status_code, resp.json()

    def mark_quiz(assignment: uuid.UUID) -> tuple[int, object]:
        resp = api.post(
            "/api/usage/estimate",
            json={"action": "mark_quiz", "assignmentId": str(assignment)},
        )
        return resp.status_code, resp.json()

    # The owner gets a quote (4 points: base 1-2 plus 0-4).
    _as(api, owner)
    status, body = self_review(attempt_id, question_id)
    assert status == 200
    assert (body["low"], body["high"]) == (1, 6)  # type: ignore[index]

    _as(api, intruder)
    missing = self_review(uuid.uuid4(), uuid.uuid4())
    assert missing[0] == 404
    assert self_review(attempt_id, question_id) == missing
    # Mixing the intruder's own attempt with the owner's question is not a way in either.
    assert self_review(other_attempt, question_id) == missing
    assert self_review(attempt_id, other_question) == missing

    missing_quiz = mark_quiz(uuid.uuid4())
    assert missing_quiz[0] == 404
    # The assignment targets ``assigned.owner`` only, so it is foreign to both callers here.
    assert mark_quiz(assigned.assignment_id) == missing_quiz
    _as(api, owner)
    assert mark_quiz(assigned.assignment_id) == missing_quiz
    _as(api, assigned.owner)
    status, body = mark_quiz(assigned.assignment_id)
    assert status == 200
    assert (body["low"], body["high"]) == (4, 11)  # type: ignore[index]


def test_estimate_rejects_a_token_whose_subject_is_not_a_user_id(
    api: TestClient,
) -> None:
    api.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[union-attr]
        user_id="not-a-uuid", role="student"
    )
    for call in (
        lambda: api.post("/api/usage/estimate", json={"action": "mark_paper"}),
        lambda: api.get("/api/usage/meter"),
        lambda: api.get("/api/usage/history"),
    ):
        assert call().status_code == 401


def test_every_usage_route_needs_a_signed_in_caller(api: TestClient) -> None:
    assert api.post("/api/usage/estimate", json={"action": "mark_paper"}).status_code == 401
    assert api.get("/api/usage/meter").status_code == 401
    assert api.get("/api/usage/history").status_code == 401


def test_estimate_is_rate_limited_per_user(
    api: TestClient, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    sm = migrated_sessionmaker
    first, second = seed_user(sm), seed_user(sm)
    payload = {"action": "study_plan", "subjectCode": "0580"}
    _as(api, first)
    codes = [api.post("/api/usage/estimate", json=payload).status_code for _ in range(61)]
    assert codes[:60] == [200] * 60
    assert codes[60] == 429
    limited = api.post("/api/usage/estimate", json=payload)
    assert limited.status_code == 429
    assert int(limited.headers["Retry-After"]) >= 1
    # The window is per user, and the meter and history are not estimates.
    assert api.get("/api/usage/meter").status_code == 200
    _as(api, second)
    assert api.post("/api/usage/estimate", json=payload).status_code == 200


# -- meter --------------------------------------------------------------------------


def test_meter_shows_allowance_credits_seats_and_debt(
    api: TestClient, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    sm = migrated_sessionmaker
    student, teacher = seed_user(sm), seed_user(sm, Role.teacher)
    give(sm, student, units=300, expires_at=datetime(2027, 6, 1, tzinfo=UTC))
    give(sm, student, units=200)
    member = seat(
        sm,
        teacher=teacher,
        student=student,
        subjects=["0580"],
        actions=[MeteredAction.MARK_PAPER],
    )
    seat_grant(sm, student=student, member_id=member, units=100)
    _as(api, student)
    body = api.get("/api/usage/meter").json()
    assert body["creditsBalance"] == 500
    assert [lot["remaining"] for lot in body["creditLots"]] == [300, 200]
    assert body["seats"][0]["teacherMemberId"] == str(member)
    assert body["seats"][0]["fraction"] == 0.0
    assert body["debtUnits"] == 0


def test_meter_shows_only_the_callers_own_balance(
    api: TestClient, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    sm = migrated_sessionmaker
    student, other, teacher = seed_user(sm), seed_user(sm), seed_user(sm, Role.teacher)
    give(sm, student, units=111)
    give(sm, other, units=999)
    give(
        sm,
        other,
        units=4000,
        kind=GrantKind.period_allowance,
        visible=False,
        expires_at=_ALLOWANCE_END,
    )
    member = seat(
        sm,
        teacher=teacher,
        student=other,
        subjects=["0580"],
        actions=[MeteredAction.MARK_PAPER],
    )
    seat_grant(sm, student=other, member_id=member, units=100)
    with sm.begin() as session:
        session.add(UsageDebt(owner_user_id=other, job_id=None, units=77, outstanding=77))
    _as(api, student)
    body = api.get("/api/usage/meter").json()
    assert body["creditsBalance"] == 111
    assert body["allowanceFraction"] is None
    assert body["seats"] == []
    assert body["debtUnits"] == 0
    # The teacher who pays the other student's seat sees no seat or credits of theirs.
    _as(api, teacher, Role.teacher)
    teacher_body = api.get("/api/usage/meter").json()
    assert (teacher_body["creditsBalance"], teacher_body["seats"]) == (0, [])
    _as(api, other)
    assert api.get("/api/usage/meter").json()["debtUnits"] == 77


# -- history ------------------------------------------------------------------------


def test_history_never_shows_allowance_units(
    api: TestClient, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    """Spec §2.1: the allowance is hidden. Allowance portions are a percentage of the plan,
    credits portions are credits, and no allowance unit count reaches the client."""
    sm = migrated_sessionmaker
    planned, paying, both = seed_user(sm), seed_user(sm), seed_user(sm)
    give(
        sm,
        planned,
        units=4000,
        kind=GrantKind.period_allowance,
        visible=False,
        expires_at=_ALLOWANCE_END,
    )
    give(sm, paying, units=1000)
    give(
        sm,
        both,
        units=100,
        kind=GrantKind.period_allowance,
        visible=False,
        expires_at=_ALLOWANCE_END,
    )
    give(sm, both, units=1000)
    _run_job(sm, planned, "0.040")  # 40 of a 4000-unit allowance
    _run_job(sm, paying, "0.030")  # 30 credits
    _run_job(sm, both, "0.150")  # all 100 allowance units, then 50 credits

    _as(api, planned)
    raw = api.get("/api/usage/history").text
    (row,) = api.get("/api/usage/history").json()["jobs"]
    assert (row["paidBy"], row["percentOfPlan"], row["credits"]) == ("allowance", 1.0, None)
    assert (row["estimatePercentOfPlan"], row["estimateCredits"]) == ([1.0, 3.0], None)
    for key in ("charged", "estimateLow", "estimateHigh", '"units"'):
        assert key not in raw
    # An allowance-paid row carries no integer at all: no units, no allowance size.
    assert [v for v in row.values() if isinstance(v, int) and not isinstance(v, bool)] == []

    _as(api, paying)
    (row,) = api.get("/api/usage/history").json()["jobs"]
    assert (row["paidBy"], row["percentOfPlan"], row["credits"]) == ("credits", None, 30)
    assert (row["estimatePercentOfPlan"], row["estimateCredits"]) == (None, [40, 120])

    _as(api, both)
    (row,) = api.get("/api/usage/history").json()["jobs"]
    assert (row["paidBy"], row["percentOfPlan"], row["credits"]) == ("mixed", 100.0, 50)
    assert row["estimatePercentOfPlan"] == [40.0, 120.0]


def test_history_pages_newest_first_and_includes_seat_jobs_for_the_teacher(
    api: TestClient, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    sm = migrated_sessionmaker
    student, teacher = seed_user(sm), seed_user(sm, Role.teacher)
    member = seat(
        sm,
        teacher=teacher,
        student=student,
        subjects=["0580"],
        actions=[MeteredAction.MARK_PAPER],
    )
    seat_grant(sm, student=student, member_id=member, units=1000)
    for cost in ("0.010", "0.020", "0.030"):
        _run_job(sm, student, cost, subject_code="0580")
    _as(api, student)
    first = api.get("/api/usage/history", params={"limit": 2}).json()
    assert [(j["paidBy"], j["percentOfPlan"]) for j in first["jobs"]] == [
        ("seat", 3.0),
        ("seat", 2.0),
    ]
    second = api.get(
        "/api/usage/history", params={"limit": 2, "cursor": first["nextCursor"]}
    ).json()
    assert [j["percentOfPlan"] for j in second["jobs"]] == [1.0]
    assert second["nextCursor"] is None
    _as(api, teacher, Role.teacher)
    seen = api.get("/api/usage/history").json()["jobs"]
    assert {j["actorUserId"] for j in seen} == {str(student)}


def test_history_shows_a_teacher_only_the_part_their_seat_paid(
    api: TestClient, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    """A job the seat only partly covers spills into the student's own credits. The seat's
    teacher sees the seat portion, never what the student paid from their own balance."""
    sm = migrated_sessionmaker
    student, teacher = seed_user(sm), seed_user(sm, Role.teacher)
    give(sm, student, units=1000)
    member = seat(
        sm,
        teacher=teacher,
        student=student,
        subjects=["0580"],
        actions=[MeteredAction.MARK_PAPER],
    )
    seat_grant(sm, student=student, member_id=member, units=50)
    _run_job(sm, student, "0.150", subject_code="0580")  # 50 seat units, then 100 credits
    _as(api, student)
    (row,) = api.get("/api/usage/history").json()["jobs"]
    assert (row["paidBy"], row["percentOfPlan"], row["credits"]) == ("mixed", 100.0, 100)
    _as(api, teacher, Role.teacher)
    (row,) = api.get("/api/usage/history").json()["jobs"]
    assert (row["paidBy"], row["percentOfPlan"], row["credits"]) == ("seat", 100.0, None)


def test_history_lets_the_lead_and_the_assistant_each_see_their_own_view(
    api: TestClient, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    """The assistant's job is paid from the lead's credits, and any debt it leaves is the
    lead's: each sees their own side, a stranger sees nothing."""
    sm = migrated_sessionmaker
    lead, helper, stranger = (seed_user(sm, Role.teacher) for _ in range(3))
    give(sm, lead, units=200)
    member = assistant(sm, teacher=lead, member=helper)
    # The work costs 500 units against 200 held: 200 charged and 300 owed by the lead.
    _run_job(
        sm,
        helper,
        "0.500",
        action=MeteredAction.REGRADE,
        role="teacher",
        assistant_member_id=member,
    )
    _as(api, lead, Role.teacher)
    (row,) = api.get("/api/usage/history").json()["jobs"]
    assert (row["actorUserId"], row["paidBy"], row["credits"]) == (str(helper), "credits", 200)
    assert row["debtCredits"] == 300
    _as(api, helper, Role.teacher)
    (row,) = api.get("/api/usage/history").json()["jobs"]
    assert (row["paidBy"], row["credits"]) == ("teacher_credits", 200)
    assert row["debtCredits"] is None
    _as(api, stranger, Role.teacher)
    assert api.get("/api/usage/history").json() == {"jobs": [], "nextCursor": None}


def test_history_never_lists_another_users_jobs(
    api: TestClient, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    sm = migrated_sessionmaker
    mine, theirs = seed_user(sm), seed_user(sm)
    give(sm, mine, units=1000)
    give(sm, theirs, units=1000)
    _run_job(sm, mine, "0.010")
    _run_job(sm, theirs, "0.020")
    _run_job(sm, theirs, "0.030")
    _as(api, theirs)
    first = api.get("/api/usage/history", params={"limit": 1}).json()
    assert first["nextCursor"] is not None
    # Another user's cursor only ever pages the caller's own rows.
    _as(api, mine)
    page = api.get("/api/usage/history", params={"cursor": first["nextCursor"]}).json()
    assert {j["actorUserId"] for j in page["jobs"]} == {str(mine)}


def _edit_cursor(token: str, mutate: dict[str, object]) -> str:
    padded = token + "=" * (-len(token) % 4)
    payload = json.loads(base64.urlsafe_b64decode(padded))
    payload.update(mutate)
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")


def test_a_tampered_history_cursor_is_a_400(
    api: TestClient, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    sm = migrated_sessionmaker
    student = seed_user(sm)
    give(sm, student, units=1000)
    for cost in ("0.010", "0.020"):
        _run_job(sm, student, cost)
    _as(api, student)
    good = api.get("/api/usage/history", params={"limit": 1}).json()["nextCursor"]
    assert api.get("/api/usage/history", params={"cursor": good}).status_code == 200
    tampered = {
        "garbage": "garbage",
        "not base64url": "a+b/c=",
        "another list's cursor": encode_cursor("tutors", [NOW, uuid.uuid4()]),
        "edited tag": _edit_cursor(good, {"e": "other"}),
        "edited key type": _edit_cursor(good, {"k": ["x", "y"]}),
        "dropped key": _edit_cursor(good, {"k": []}),
        "extra field": _edit_cursor(good, {"x": 1}),
        "oversized": "A" * 600,
        "wrong slot types": encode_cursor("usage_history", [uuid.uuid4(), uuid.uuid4()]),
    }
    for label, cursor in tampered.items():
        resp = api.get("/api/usage/history", params={"cursor": cursor})
        assert resp.status_code == 400, (label, resp.status_code, resp.text)
    assert api.get("/api/usage/history", params={"limit": 0}).status_code == 422
    assert api.get("/api/usage/history", params={"limit": 101}).status_code == 422
