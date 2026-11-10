"""The usage API (phase 04 Task 7): estimate from server-side records, meter, history."""

from __future__ import annotations

import base64
import json
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text, update
from sqlalchemy.dialects import postgresql

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
from lemely.db.usage_views_repo import history_jobs_statement
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
from tests.usage_helpers import (
    NOW,
    assistant,
    attempt_with_points,
    enforcing_meter,
    give,
    put_in_school,
    quiz_with_assignment,
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
        json={
            "action": "generate_flashcards",
            "subjectCode": "0625",
            "origin": "topic",
            "count": 4,
        },
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
    attempt_id, question_id = attempt_with_points(sm, student, subject="0580", points=2)
    assigned = quiz_with_assignment(sm, subject="0580", included=2)
    before = _ledger_counts(sm)
    _as(api_without_catalogue, student)
    for payload in (
        {"action": "mark_paper"},
        {"action": "study_plan", "subjectCode": "0580"},
        {"action": "generate_flashcards", "subjectCode": "0580", "origin": "topic", "count": 3},
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
    in_scope = quiz_with_assignment(sm, subject="0580", included=3)
    out_of_scope = quiz_with_assignment(sm, subject="0625", included=3)
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
    put_in_school(sm, lead)
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
    attempt_id, question_id = attempt_with_points(sm, owner, subject="0580", points=4)
    other_attempt, other_question = attempt_with_points(sm, intruder, subject="0580", points=1)
    assigned = quiz_with_assignment(sm, subject="0580", included=3)

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
    # 40-120 units against a 100-unit allowance: a percentage is capped at the whole plan.
    assert row["estimatePercentOfPlan"] == [40.0, 100.0]


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


def test_history_hides_a_job_the_teacher_neither_ran_nor_funded(
    api: TestClient, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    """A seat with nothing left in it puts the seat in the job's chain, but the student's
    own credits pay. That job is the student's private usage: the teacher never sees it,
    not even as a row that charged nothing."""
    sm = migrated_sessionmaker
    student, teacher = seed_user(sm), seed_user(sm, Role.teacher)
    give(sm, student, units=1000)
    seat(
        sm,
        teacher=teacher,
        student=student,
        subjects=["0580"],
        actions=[MeteredAction.MARK_PAPER],
    )  # no seat grant: nothing for the seat to pay with
    _run_job(sm, student, "0.050", subject_code="0580")
    _as(api, student)
    (row,) = api.get("/api/usage/history").json()["jobs"]
    assert (row["paidBy"], row["credits"]) == ("credits", 50)
    _as(api, teacher, Role.teacher)
    assert api.get("/api/usage/history").json() == {"jobs": [], "nextCursor": None}


def test_hidden_jobs_do_not_break_the_teachers_paging(
    api: TestClient, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    """Hidden jobs are left out of the query, not filtered after the page is cut, so a page
    is never short or empty while a next cursor is offered."""
    sm = migrated_sessionmaker
    funded, private = seed_user(sm), seed_user(sm)
    teacher = seed_user(sm, Role.teacher)
    give(sm, private, units=1000)
    for student in (funded, private):
        member = seat(
            sm,
            teacher=teacher,
            student=student,
            subjects=["0580"],
            actions=[MeteredAction.MARK_PAPER],
        )
        if student == funded:
            seat_grant(sm, student=student, member_id=member, units=1000)
    for student in (funded, private, private, private, funded, private, private, funded):
        _run_job(sm, student, "0.010", subject_code="0580")
    _as(api, teacher, Role.teacher)
    first = api.get("/api/usage/history", params={"limit": 2}).json()
    assert [j["actorUserId"] for j in first["jobs"]] == [str(funded)] * 2
    assert first["nextCursor"] is not None
    last = api.get("/api/usage/history", params={"limit": 2, "cursor": first["nextCursor"]}).json()
    assert [j["actorUserId"] for j in last["jobs"]] == [str(funded)]
    assert last["nextCursor"] is None


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


# -- review follow-ups (I1 to I3, M1, M2, M8) ----------------------------------------


def _explain(sm: sessionmaker[Session], statement: object) -> str:
    """The plan Postgres picks for ``statement`` with sequential scans disabled, so a plan
    that still scans can only be doing so because no index can serve the query."""
    sql = str(
        statement.compile(  # type: ignore[attr-defined]
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    with sm() as session:
        session.execute(text("SET LOCAL enable_seqscan = off"))
        rows = session.execute(text("EXPLAIN " + sql.replace(":", "\\:")))
        return "\n".join(row[0] for row in rows)


def test_a_plain_students_history_query_is_served_by_the_actor_index(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    """Nobody can draw on a user's grants except through a seat or assistant row that user
    leads, so a caller who leads nothing must not pay for the funder branch: it would turn
    every history request into a scan of the whole ledger."""
    sm = migrated_sessionmaker
    student, teacher = seed_user(sm), seed_user(sm, Role.teacher)
    seat(
        sm, teacher=teacher, student=student, subjects=["0580"], actions=[MeteredAction.MARK_PAPER]
    )
    plain = history_jobs_statement(student, led_members=[], after=None, limit=26)
    plan = _explain(sm, plain)
    assert "Seq Scan" not in plan, plan
    assert "ix_usage_jobs_actor_created" in plan, plan
    # A caller who leads a member does take the funder branch, and only for jobs that name
    # a seat or assistant row.
    led = history_jobs_statement(teacher, led_members=[uuid.uuid4()], after=None, limit=26)
    sql = str(led.compile(dialect=postgresql.dialect()))
    assert "usage_entries" in sql
    assert "teacher_member_id IS NOT NULL" in sql
    assert "usage_entries" not in str(plain.compile(dialect=postgresql.dialect()))


def test_a_signup_only_student_sees_one_story_in_all_three_views(
    api: TestClient, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    """The free start is a hidden one-time grant, not a plan. Everywhere it is credits:
    the meter counts it, the estimate quotes credits with no percent, history charges credits
    with no percent of a plan the student does not have."""
    sm = migrated_sessionmaker
    student = seed_user(sm)
    give(sm, student, units=500, kind=GrantKind.signup, visible=False)
    _as(api, student)
    meter = api.get("/api/usage/meter").json()
    assert meter["allowanceFraction"] is None
    assert meter["creditsBalance"] == 500
    assert meter["creditLots"] == [{"remaining": 500, "expiresAt": None}]
    quote = api.post("/api/usage/estimate", json={"action": "mark_paper"}).json()
    assert quote == {
        "low": 40,
        "high": 120,
        "payer": "credits",
        "percentLow": None,
        "percentHigh": None,
        "blockedReason": None,
    }
    _run_job(sm, student, "0.050")
    (row,) = api.get("/api/usage/history").json()["jobs"]
    assert (row["paidBy"], row["percentOfPlan"], row["credits"]) == ("credits", None, 50)
    assert (row["estimatePercentOfPlan"], row["estimateCredits"]) == (None, [40, 120])
    assert api.get("/api/usage/meter").json()["creditsBalance"] == 450


def test_history_percents_share_the_estimates_denominator(
    api: TestClient, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    """After an upgrade adds a second period grant the plan is both grants together, for the
    estimate and for history alike."""
    sm = migrated_sessionmaker
    student = seed_user(sm)
    for units in (1000, 3000):
        give(
            sm,
            student,
            units=units,
            kind=GrantKind.period_allowance,
            visible=False,
            expires_at=_ALLOWANCE_END,
        )
    _as(api, student)
    quote = api.post("/api/usage/estimate", json={"action": "mark_paper"}).json()
    assert (quote["payer"], quote["percentLow"], quote["percentHigh"]) == ("allowance", 1, 3)
    _run_job(sm, student, "0.040")
    (row,) = api.get("/api/usage/history").json()["jobs"]
    assert row["percentOfPlan"] == 1.0
    assert row["estimatePercentOfPlan"] == [1.0, 3.0]


def test_history_does_not_add_percents_of_different_plans(
    api: TestClient, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    """Two seats cover one job. The row says mixed and reports the plan drawn on first, in
    its own terms and capped at the whole of it; each teacher sees only their own seat."""
    sm = migrated_sessionmaker
    student = seed_user(sm)
    first_teacher, second_teacher = seed_user(sm, Role.teacher), seed_user(sm, Role.teacher)
    give(sm, student, units=1000)
    first = seat(
        sm,
        teacher=first_teacher,
        student=student,
        subjects=["0580"],
        actions=[MeteredAction.MARK_PAPER],
        created_at=NOW - timedelta(days=20),
    )
    second = seat(
        sm,
        teacher=second_teacher,
        student=student,
        subjects=["0580"],
        actions=[MeteredAction.MARK_PAPER],
        created_at=NOW - timedelta(days=1),
    )
    seat_grant(sm, student=student, member_id=first, units=20)
    seat_grant(sm, student=student, member_id=second, units=100)
    _run_job(sm, student, "0.024", subject_code="0580")  # 20 from the first seat, 4 from the second
    _as(api, student)
    (row,) = api.get("/api/usage/history").json()["jobs"]
    assert (row["paidBy"], row["percentOfPlan"], row["credits"]) == ("mixed", 100.0, None)
    assert row["estimatePercentOfPlan"] == [100.0, 100.0]  # 40-120 units against a 20-unit seat
    _as(api, first_teacher, Role.teacher)
    (row,) = api.get("/api/usage/history").json()["jobs"]
    assert (row["paidBy"], row["percentOfPlan"]) == ("seat", 100.0)
    _as(api, second_teacher, Role.teacher)
    (row,) = api.get("/api/usage/history").json()["jobs"]
    assert (row["paidBy"], row["percentOfPlan"]) == ("seat", 4.0)


def test_an_assistant_gets_no_plan_percentages_for_the_lead(
    api: TestClient, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    """The estimate's units are public (the same for every caller), so units next to a
    percentage would give away the lead's plan size. An assistant acting for a lead is
    therefore shown units and ``paidBy`` only: no percent field carries a value, in the
    estimate or on the assistant's own history rows. The lead still sees their own plan."""
    sm = migrated_sessionmaker
    lead, helper = seed_user(sm, Role.teacher), seed_user(sm, Role.teacher)
    give(
        sm,
        lead,
        units=4000,
        kind=GrantKind.period_allowance,
        visible=False,
        expires_at=_ALLOWANCE_END,
    )
    member = assistant(sm, teacher=lead, member=helper)
    headers = {ACTING_TEACHER_HEADER: str(lead)}
    _as(api, helper, Role.teacher)
    quote = api.post("/api/usage/estimate", json={"action": "regrade"}, headers=headers).json()
    assert quote == {
        "low": 40,
        "high": 120,
        "payer": "allowance",
        "percentLow": None,
        "percentHigh": None,
        "blockedReason": None,
    }
    # The lead asking for themselves sees the same units and their own percentages.
    _as(api, lead, Role.teacher)
    own = api.post("/api/usage/estimate", json={"action": "regrade"}).json()
    assert (own["low"], own["high"], own["percentLow"], own["percentHigh"]) == (40, 120, 1, 3)
    _run_job(
        sm,
        helper,
        "0.040",
        action=MeteredAction.REGRADE,
        role="teacher",
        assistant_member_id=member,
    )
    _as(api, helper, Role.teacher)
    (row,) = api.get("/api/usage/history").json()["jobs"]
    assert row["paidBy"] == "allowance"
    assert row["percentOfPlan"] is None
    assert row["estimatePercentOfPlan"] is None
    assert row["credits"] is None
    # No estimate at all: ``estimateCredits`` on an allowance-paid row would read as credits
    # the lead spent, and the percentage is withheld. The quote was given before the job.
    assert row["estimateCredits"] is None
    _as(api, lead, Role.teacher)
    (row,) = api.get("/api/usage/history").json()["jobs"]
    assert (row["percentOfPlan"], row["estimatePercentOfPlan"]) == (1.0, [1.0, 3.0])
    # Where the lead's visible credits pay, the quote is units, as for anyone.
    credit_lead, credit_helper = seed_user(sm, Role.teacher), seed_user(sm, Role.teacher)
    give(sm, credit_lead, units=1000)
    assistant(sm, teacher=credit_lead, member=credit_helper)
    _as(api, credit_helper, Role.teacher)
    paid = api.post(
        "/api/usage/estimate",
        json={"action": "regrade"},
        headers={ACTING_TEACHER_HEADER: str(credit_lead)},
    ).json()
    assert (paid["payer"], paid["low"], paid["high"]) == ("credits", 40, 120)
    assert (paid["percentLow"], paid["percentHigh"]) == (None, None)


def test_estimate_percentages_are_capped_like_history(
    api: TestClient, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    sm = migrated_sessionmaker
    student = seed_user(sm)
    give(
        sm,
        student,
        units=100,
        kind=GrantKind.period_allowance,
        visible=False,
        expires_at=_ALLOWANCE_END,
    )
    give(sm, student, units=1000)
    _as(api, student)
    quote = api.post("/api/usage/estimate", json={"action": "mark_paper"}).json()
    # 40-120 units against a 100-unit plan: the top of the range is the whole plan, not 120%.
    assert (quote["payer"], quote["percentLow"], quote["percentHigh"]) == ("allowance", 40, 100)
    _run_job(sm, student, "0.060")
    (row,) = api.get("/api/usage/history").json()["jobs"]
    assert row["estimatePercentOfPlan"] == [40.0, 100.0]


def test_a_spent_plan_over_a_signup_grant_is_credits_in_all_three_views(
    api: TestClient, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    """A student who subscribes before using up the free start spends the plan first. Once
    it is spent the signup grant pays, so the estimate quotes credits, not the empty plan."""
    sm = migrated_sessionmaker
    student = seed_user(sm)
    give(
        sm,
        student,
        units=100,
        kind=GrantKind.period_allowance,
        visible=False,
        expires_at=_ALLOWANCE_END,
    )
    give(sm, student, units=500, kind=GrantKind.signup, visible=False)
    _as(api, student)
    live = api.post("/api/usage/estimate", json={"action": "mark_paper"}).json()
    assert (live["payer"], live["percentLow"]) == ("allowance", 40)
    _run_job(sm, student, "0.100")  # the whole plan
    meter = api.get("/api/usage/meter").json()
    assert (meter["allowanceFraction"], meter["creditsBalance"]) == (1.0, 500)
    quote = api.post("/api/usage/estimate", json={"action": "mark_paper"}).json()
    assert (quote["payer"], quote["percentLow"], quote["percentHigh"]) == ("credits", None, None)
    assert (quote["low"], quote["high"], quote["blockedReason"]) == (40, 120, None)
    _run_job(sm, student, "0.050")
    newest, oldest = api.get("/api/usage/history").json()["jobs"]
    assert (newest["paidBy"], newest["credits"], newest["percentOfPlan"]) == ("credits", 50, None)
    assert (oldest["paidBy"], oldest["percentOfPlan"]) == ("allowance", 100.0)


def test_a_tiny_plan_draw_still_shows_a_percentage(
    api: TestClient, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    """One unit of a 4000-unit plan rounds to 0.0%. The row shows 0.1, not nothing, so an
    allowance-paid row never reads as free."""
    sm = migrated_sessionmaker
    student = seed_user(sm)
    give(
        sm,
        student,
        units=4000,
        kind=GrantKind.period_allowance,
        visible=False,
        expires_at=_ALLOWANCE_END,
    )
    _run_job(sm, student, "0.001")
    _as(api, student)
    (row,) = api.get("/api/usage/history").json()["jobs"]
    assert (row["paidBy"], row["percentOfPlan"], row["credits"]) == ("allowance", 0.1, None)


def test_the_history_route_takes_the_funder_branch_only_for_a_caller_who_leads(
    migrated_sessionmaker: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The statement builder is tested above; this pins how ``history_page`` calls it."""
    from lemely.db import usage_views_repo

    sm = migrated_sessionmaker
    student, teacher = seed_user(sm), seed_user(sm, Role.teacher)
    seat(
        sm, teacher=teacher, student=student, subjects=["0580"], actions=[MeteredAction.MARK_PAPER]
    )
    seen: dict[uuid.UUID, list[uuid.UUID]] = {}
    real = usage_views_repo.history_jobs_statement

    def spy(user_id: uuid.UUID, *, led_members: list[uuid.UUID], **kwargs: object) -> object:
        seen[user_id] = list(led_members)
        return real(user_id, led_members=led_members, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(usage_views_repo, "history_jobs_statement", spy)
    with sm() as session:
        usage_views_repo.history_page(session, user_id=student, limit=5, after=None)
        usage_views_repo.history_page(session, user_id=teacher, limit=5, after=None)
    assert seen[student] == []
    assert len(seen[teacher]) == 1


def test_history_pages_through_jobs_with_identical_timestamps(
    api: TestClient, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    """The id tie-break pins the order: no row skipped or repeated when created_at ties,
    whether the caller ran the jobs or funds them."""
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
    for _ in range(5):
        _run_job(sm, student, "0.010", subject_code="0580")
    with sm.begin() as session:
        session.execute(update(UsageJob).values(created_at=NOW))
    for who, role in ((student, Role.student), (teacher, Role.teacher)):
        _as(api, who, role)
        seen: list[str] = []
        cursor: str | None = None
        for _ in range(5):
            params: dict[str, object] = {"limit": 2}
            if cursor is not None:
                params["cursor"] = cursor
            page = api.get("/api/usage/history", params=params).json()
            seen += [job["jobId"] for job in page["jobs"]]
            cursor = page["nextCursor"]
            if cursor is None:
                break
        assert len(seen) == 5
        assert len(set(seen)) == 5


def test_a_flashcard_estimate_quotes_a_seat_only_for_a_weakness_deck(
    api: TestClient, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    """Seats pay flashcards only for a weakness deck (the route's rule): the estimate takes
    the deck ``origin`` and quotes the same payer the route will charge."""
    sm = migrated_sessionmaker
    student, teacher = seed_user(sm), seed_user(sm, Role.teacher)
    give(sm, student, units=1000)
    member = seat(
        sm,
        teacher=teacher,
        student=student,
        subjects=["0625"],
        actions=[MeteredAction.GENERATE_FLASHCARDS],
    )
    seat_grant(sm, student=student, member_id=member, units=1000)
    _as(api, student)

    def quote(origin: str | None, subject: str = "0625") -> dict[str, object]:
        body: dict[str, object] = {"action": "generate_flashcards", "subjectCode": subject}
        body["count"] = 4
        if origin is not None:
            body["origin"] = origin
        resp = api.post("/api/usage/estimate", json=body)
        assert resp.status_code in (200, 422), resp.text
        return {"status": resp.status_code, **resp.json()}

    assert quote("weakness")["payer"] == "seat"
    assert quote("topic")["payer"] == "credits"  # a topic is the client's, never seat-paid
    assert quote("weakness", subject="0580")["payer"] == "credits"  # out of the seat's subject
    assert quote(None)["status"] == 422  # the route needs an origin, so the quote does
    assert quote("manual")["status"] == 422  # a manual deck has nothing to generate


def test_history_percentages_round_to_one_decimal_and_the_estimate_up(
    api: TestClient, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    """A 300-unit plan makes the percentages non-integers: 40 units is 13.3% to one
    decimal, and the estimate rounds up to whole percents (40 and 120 units: 14 and 40)."""
    sm = migrated_sessionmaker
    student = seed_user(sm)
    give(
        sm,
        student,
        units=300,
        kind=GrantKind.period_allowance,
        visible=False,
        expires_at=_ALLOWANCE_END,
    )
    _as(api, student)
    quote = api.post("/api/usage/estimate", json={"action": "mark_paper"}).json()
    assert (quote["percentLow"], quote["percentHigh"]) == (14, 40)
    _run_job(sm, student, "0.040")
    (row,) = api.get("/api/usage/history").json()["jobs"]
    assert row["percentOfPlan"] == 13.3
    assert row["estimatePercentOfPlan"] == [14.0, 40.0]
