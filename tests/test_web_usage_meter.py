"""UsageMeter: authorize, reserve, settle, release, deferred subjects, 402 (phase 04 Task 6)."""

from __future__ import annotations

import contextvars
import threading
import uuid
from decimal import Decimal
from typing import TYPE_CHECKING, Annotated

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from structlog.testing import capture_logs

from lemely.core.metered_actions import MeteredAction, UsageTarget
from lemely.core.payer_chain import UsageBlockReason
from lemely.db.models.enums import Role
from lemely.db.models.usage import (
    GrantKind,
    UsageDebt,
    UsageGrantBalance,
    UsageJobStatus,
)
from lemely.db.usage_ledger_repo import UsageLedger
from lemely.io.llm.cost_meter import record_llm_cost
from lemely.runtime.config import Settings, UsageSettings
from lemely.web import usage
from lemely.web.deps import (
    AuthContext,
    TeamActor,
    _team_lead_unavailable,
    _team_permission_denied,
    get_auth_context,
)
from lemely.web.usage import (
    MeteredJob,
    UsageBlocked,
    UsageGrantContext,
    UsageMeter,
    UsageRequest,
    get_usage_meter,
    request_from_team,
    require_usage,
    usage_blocked_handler,
)
from tests.usage_helpers import (
    NOW,
    assistant,
    enforcing_meter,
    give,
    jobs_for,
    seat,
    seat_grant,
    seed_catalogue,
    seed_user,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker


def _req(
    actor: uuid.UUID,
    action: MeteredAction = MeteredAction.MARK_PAPER,
    *,
    role: Role = Role.student,
    subject_code: str | None = None,
    assistant_member_id: uuid.UUID | None = None,
    subject_pending: bool = False,
) -> UsageRequest:
    return UsageRequest(
        actor_user_id=actor,
        actor_role=role,
        action=action,
        subject_code=subject_code,
        assistant_member_id=assistant_member_id,
        subject_pending=subject_pending,
    )


def _funded_student(sm: sessionmaker[Session], units: int = 1000) -> uuid.UUID:
    seed_catalogue(sm)
    student = seed_user(sm)
    give(sm, student, units=units)
    return student


# --- R5: enforcement -------------------------------------------------------------------


def test_enforce_is_on_by_default_and_off_under_the_suite(monkeypatch: pytest.MonkeyPatch) -> None:
    """R5: the shipped default enforces; only the suite's env var turns it off."""
    assert UsageSettings().enforce is True
    assert Settings().usage.enforce is False
    monkeypatch.delenv("LEMELY_USAGE__ENFORCE")
    default = Settings()
    assert default.usage.enforce is True
    # The app's own dependency, built from default settings, meters a student.
    assert get_usage_meter(default)._exempt(_req(uuid.uuid4())) is False
    # ...and the suite's settings give a meter that meters nobody.
    monkeypatch.setenv("LEMELY_USAGE__ENFORCE", "0")
    assert get_usage_meter(Settings())._exempt(_req(uuid.uuid4())) is True


def test_a_non_enforcing_meter_never_touches_the_database() -> None:
    """The suite's route tests build meters on whatever DB; with enforce off none is opened."""

    def _no_db() -> Session:
        raise AssertionError("a non-enforcing meter opened a session")

    off = UsageMeter(_no_db, enforce=False)  # type: ignore[arg-type]
    student = uuid.uuid4()
    ctx = off.authorize(_req(student))
    assert ctx.exempt is True
    assert off.resolve_target(lambda _s: None) == UsageTarget(subject_code=None, input_count=0)
    assert off.estimate(_req(student)).payer == "none"
    with off.job(ctx):
        record_llm_cost(Decimal("0.5"))


# --- R4: assistants bill the lead -------------------------------------------------------


def test_an_assistant_never_spends_its_own_balance(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    """R4: team work is charged to the lead; the assistant's own credits are untouched."""
    sm = migrated_sessionmaker
    seed_catalogue(sm)
    lead, helper = seed_user(sm, Role.teacher), seed_user(sm, Role.teacher)
    own = give(sm, helper, units=1000)
    member = assistant(sm, teacher=lead, member=helper)
    actor = TeamActor(
        actor_user_id=helper,
        lead_teacher_user_id=lead,
        member_id=member,
        auth=AuthContext(user_id=str(lead), role="teacher"),
    )
    meter = enforcing_meter(sm)
    with pytest.raises(
        UsageBlocked
    ) as info:  # the lead has nothing; the helper's 1000 never counts
        meter.authorize(request_from_team(actor, MeteredAction.REGRADE))
    assert info.value.reason is UsageBlockReason.NO_ACTIVE_PLAN
    give(sm, lead, units=500)
    with meter.job(meter.authorize(request_from_team(actor, MeteredAction.REGRADE))):
        record_llm_cost(Decimal("0.050"))
    (job,) = jobs_for(sm, helper)
    assert (job.charged, job.teacher_member_id) == (50, member)
    with sm() as session:
        balance = session.get(UsageGrantBalance, own)
        assert balance is not None
        assert balance.remaining == 1000


def test_assistant_cap_limits_the_lead_teachers_balance(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    seed_catalogue(sm)
    lead, helper = seed_user(sm, Role.teacher), seed_user(sm, Role.teacher)
    give(sm, lead, units=5000)
    member = assistant(sm, teacher=lead, member=helper, cap_units=30)
    meter = enforcing_meter(sm)
    with pytest.raises(UsageBlocked) as info:
        meter.authorize(
            _req(helper, MeteredAction.REGRADE, role=Role.teacher, assistant_member_id=member)
        )
    assert info.value.reason is UsageBlockReason.INSUFFICIENT_CREDITS
    uncapped_helper = seed_user(sm, Role.teacher)
    roomy = assistant(sm, teacher=lead, member=uncapped_helper, cap_units=None)
    ctx = meter.authorize(
        _req(uncapped_helper, MeteredAction.REGRADE, role=Role.teacher, assistant_member_id=roomy)
    )
    assert [p.owner_user_id for p in ctx.chain] == [lead, lead]
    assert ctx.teacher_member_id == roomy


# --- post-settle hooks (deviation 12) --------------------------------------------------


def test_post_settle_hooks_run_once_after_a_settle_never_after_a_release(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    student = _funded_student(sm)
    seen: list[tuple[int, int]] = []
    saved = list(usage._POST_SETTLE_HOOKS)
    usage.clear_post_settle_hooks()
    usage.register_post_settle_hook(
        lambda _s, job, payers, _now: seen.append((job.charged, len(payers)))
    )
    try:
        meter = enforcing_meter(sm)
        with meter.job(meter.authorize(_req(student))):
            record_llm_cost(Decimal("0.020"))
        with pytest.raises(RuntimeError), meter.job(meter.authorize(_req(student))):
            raise RuntimeError("failed job")
    finally:
        usage.clear_post_settle_hooks()
        usage._POST_SETTLE_HOOKS.extend(saved)
    assert seen == [(20, 2)]


def test_a_failing_hook_never_undoes_the_settle(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    student = _funded_student(sm)

    def boom(_s: Session, *_rest: object) -> None:
        raise RuntimeError("hook failed")

    saved = list(usage._POST_SETTLE_HOOKS)
    usage.clear_post_settle_hooks()
    usage.register_post_settle_hook(boom)
    try:
        meter = enforcing_meter(sm)
        with capture_logs() as logs, meter.job(meter.authorize(_req(student))):
            record_llm_cost(Decimal("0.020"))
    finally:
        usage.clear_post_settle_hooks()
        usage._POST_SETTLE_HOOKS.extend(saved)
    (job,) = jobs_for(sm, student)
    assert (job.status, job.charged) == (UsageJobStatus.settled, 20)
    assert [e["event"] for e in logs if e["event"] == "post_settle_hook_failed"] == [
        "post_settle_hook_failed"
    ]


# --- 402 reasons -----------------------------------------------------------------------


def test_blocked_without_any_balance_is_no_active_plan(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    """No catalogue seeded: authorize seeds it lazily, then blocks."""
    student = seed_user(migrated_sessionmaker)
    with pytest.raises(UsageBlocked) as info:
        enforcing_meter(migrated_sessionmaker).authorize(_req(student))
    assert info.value.body() == {
        "error": "usage_blocked",
        "reason": "no_active_plan",
        "estimate": [40, 120],
    }
    assert jobs_for(migrated_sessionmaker, student) == []


def test_debt_blocks_own_balance_but_a_seat_still_pays(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    seed_catalogue(sm)
    student, maths = seed_user(sm), seed_user(sm, Role.teacher)
    with sm.begin() as session:
        session.add(UsageDebt(owner_user_id=student, job_id=None, units=10, outstanding=10))
    meter = enforcing_meter(sm)
    with pytest.raises(UsageBlocked) as info:
        meter.authorize(_req(student, subject_code="0580"))
    assert info.value.reason is UsageBlockReason.OUTSTANDING_DEBT
    member = seat(
        sm, teacher=maths, student=student, subjects=["0580"], actions=[MeteredAction.MARK_PAPER]
    )
    seat_grant(sm, student=student, member_id=member, units=500)
    assert meter.authorize(_req(student, subject_code="0580")).teacher_member_id == member


def test_the_402_body_is_the_top_level_contract() -> None:
    app = FastAPI()
    app.add_exception_handler(UsageBlocked, usage_blocked_handler)

    @app.get("/blocked")
    def _blocked() -> None:
        raise UsageBlocked(UsageBlockReason.OUT_OF_SEAT_SCOPE, (3, 5))

    resp = TestClient(app).get("/blocked")
    assert resp.status_code == 402
    assert resp.json() == {
        "error": "usage_blocked",
        "reason": "out_of_seat_scope",
        "estimate": [3, 5],
    }


def test_create_app_registers_the_402_handler() -> None:
    from lemely.web.app import create_app

    app = create_app()
    assert app.exception_handlers[UsageBlocked] is usage_blocked_handler


# --- settle and release ----------------------------------------------------------------


def test_success_settles_the_actual_cost(migrated_sessionmaker: sessionmaker[Session]) -> None:
    sm = migrated_sessionmaker
    student = _funded_student(sm)
    meter = enforcing_meter(sm)
    with meter.job(meter.authorize(_req(student))):
        record_llm_cost(Decimal("0.050"))
    (job,) = jobs_for(sm, student)
    assert job.status is UsageJobStatus.settled
    assert job.charged == 50
    assert job.action == "mark_paper"
    assert (job.estimate_low, job.estimate_high) == (40, 120)


def test_an_exception_releases_and_charges_nothing(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    student = _funded_student(sm)
    meter = enforcing_meter(sm)
    with pytest.raises(RuntimeError), meter.job(meter.authorize(_req(student))):
        record_llm_cost(Decimal("0.050"))
        raise RuntimeError("model call failed")
    (job,) = jobs_for(sm, student)
    assert job.status is UsageJobStatus.released
    assert not job.charged


def test_input_rejected_before_any_model_call_costs_nothing(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    """Spec §2.4: a route refusing the input inside the job releases the hold."""
    sm = migrated_sessionmaker
    student = _funded_student(sm)
    meter = enforcing_meter(sm)
    with pytest.raises(HTTPException), meter.job(meter.authorize(_req(student))):
        raise HTTPException(status_code=422, detail="not a scan")
    (job,) = jobs_for(sm, student)
    assert (job.status, job.charged, job.debt_created) == (UsageJobStatus.released, 0, 0)


def test_abandon_releases_a_normal_exit(migrated_sessionmaker: sessionmaker[Session]) -> None:
    sm = migrated_sessionmaker
    student = _funded_student(sm)
    meter = enforcing_meter(sm)
    with meter.job(meter.authorize(_req(student))) as job:
        record_llm_cost(Decimal("0.050"))
        job.abandon()
    assert jobs_for(sm, student)[0].status is UsageJobStatus.released


def test_reserve_in_the_request_settle_in_a_bare_worker_thread(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    """The SSE and pool shape: reserve here, run() opens the scope inside the worker."""
    sm = migrated_sessionmaker
    student = _funded_student(sm)
    meter = enforcing_meter(sm)
    job = meter.reserve(meter.authorize(_req(student)))
    assert jobs_for(sm, student)[0].status is UsageJobStatus.open

    def work() -> None:
        with job.run():
            record_llm_cost(Decimal("0.020"))
            nested = contextvars.copy_context()
            inner = threading.Thread(target=nested.run, args=(record_llm_cost, Decimal("0.010")))
            inner.start()
            inner.join()

    worker = threading.Thread(target=work)
    worker.start()
    worker.join()
    (row,) = jobs_for(sm, student)
    assert row.status is UsageJobStatus.settled
    assert row.charged == 30


def test_release_of_a_job_that_never_ran(migrated_sessionmaker: sessionmaker[Session]) -> None:
    sm = migrated_sessionmaker
    student = _funded_student(sm)
    meter = enforcing_meter(sm)
    meter.reserve(meter.authorize(_req(student))).release()
    assert jobs_for(sm, student)[0].status is UsageJobStatus.released


def test_a_nested_metered_job_is_refused_and_releases_its_hold(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    """An inner cost scope would shadow the outer one, so the outer job would under-charge."""
    sm = migrated_sessionmaker
    student = _funded_student(sm)
    meter = enforcing_meter(sm)
    with meter.job(meter.authorize(_req(student))):
        record_llm_cost(Decimal("0.010"))
        with pytest.raises(RuntimeError, match="nested"), meter.job(meter.authorize(_req(student))):
            record_llm_cost(Decimal("0.500"))
        record_llm_cost(Decimal("0.010"))
    outer, inner = jobs_for(sm, student)
    assert (outer.status, outer.charged) == (UsageJobStatus.settled, 20)
    assert (inner.status, inner.charged) == (UsageJobStatus.released, 0)


def test_a_settle_failure_is_logged_never_raised(
    migrated_sessionmaker: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spec §2.4: the work finished; metering never turns it into a failed request."""
    sm = migrated_sessionmaker
    student = _funded_student(sm)
    meter = enforcing_meter(sm)

    def broken(*_a: object, **_k: object) -> None:
        raise RuntimeError("ledger down")

    monkeypatch.setattr(UsageLedger, "settle", broken)
    with capture_logs() as logs, meter.job(meter.authorize(_req(student))):
        record_llm_cost(Decimal("0.050"))
    (failed,) = [e for e in logs if e["event"] == "usage_finish_failed"]
    assert (failed["settle"], failed["cost_usd"]) == (True, "0.050")
    assert jobs_for(sm, student)[0].status is UsageJobStatus.open  # the sweeper expires it


def test_a_release_failure_is_logged_and_the_work_error_still_raises(
    migrated_sessionmaker: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    sm = migrated_sessionmaker
    student = _funded_student(sm)
    meter = enforcing_meter(sm)

    def broken(*_a: object, **_k: object) -> None:
        raise RuntimeError("ledger down")

    monkeypatch.setattr(UsageLedger, "release", broken)
    with (
        capture_logs() as logs,
        pytest.raises(ValueError, match="the work's own error"),
        meter.job(meter.authorize(_req(student))),
    ):
        raise ValueError("the work's own error")
    assert [e["settle"] for e in logs if e["event"] == "usage_finish_failed"] == [False]


# --- deferred subjects -----------------------------------------------------------------


def test_deferred_subject_pre_checks_seats_then_binds_the_detected_subject(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    seed_catalogue(sm)
    student, maths = seed_user(sm), seed_user(sm, Role.teacher)
    member = seat(
        sm, teacher=maths, student=student, subjects=["0580"], actions=[MeteredAction.MARK_PAPER]
    )
    seat_grant(sm, student=student, member_id=member, units=500)
    meter = enforcing_meter(sm)
    job = meter.reserve(meter.authorize(_req(student, subject_pending=True)))
    assert jobs_for(sm, student) == []  # nothing held until the subject is known
    with job.run():
        job.bind_subject("0580")
        record_llm_cost(Decimal("0.040"))
    (row,) = jobs_for(sm, student)
    assert row.teacher_member_id == member
    assert row.charged == 40


def test_deferred_subject_that_no_payer_covers_is_blocked_inside_the_job(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    seed_catalogue(sm)
    student, maths = seed_user(sm), seed_user(sm, Role.teacher)
    member = seat(
        sm, teacher=maths, student=student, subjects=["0580"], actions=[MeteredAction.MARK_PAPER]
    )
    seat_grant(sm, student=student, member_id=member, units=500)
    meter = enforcing_meter(sm)
    job = meter.reserve(meter.authorize(_req(student, subject_pending=True)))
    with pytest.raises(UsageBlocked) as info, job.run():
        job.bind_subject("0625")
    assert info.value.reason is UsageBlockReason.NO_ACTIVE_PLAN
    assert jobs_for(sm, student) == []


def test_bind_subject_refuses_a_job_that_is_not_pending(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    student = _funded_student(sm)
    meter = enforcing_meter(sm)
    job = meter.reserve(meter.authorize(_req(student)))
    with pytest.raises(RuntimeError, match="pending"):
        job.bind_subject("0580")
    job.release()


# --- races -----------------------------------------------------------------------------


def test_a_lost_race_is_a_402_not_a_500(migrated_sessionmaker: sessionmaker[Session]) -> None:
    sm = migrated_sessionmaker
    student = _funded_student(sm, units=150)
    meter = enforcing_meter(sm)
    first = meter.authorize(_req(student))
    second = meter.authorize(_req(student))
    meter.reserve(first)
    with pytest.raises(UsageBlocked) as info:
        meter.reserve(second)
    assert info.value.reason is UsageBlockReason.INSUFFICIENT_CREDITS


def test_concurrent_reserves_never_overdraw(migrated_sessionmaker: sessionmaker[Session]) -> None:
    """Both pass authorize; the ledger's owner locks let exactly one hold 120 of 150."""
    sm = migrated_sessionmaker
    student = _funded_student(sm, units=150)
    meter = enforcing_meter(sm)
    contexts = [meter.authorize(_req(student)) for _ in range(4)]
    barrier = threading.Barrier(len(contexts))
    outcomes: list[str] = []
    lock = threading.Lock()

    def race(ctx: UsageGrantContext) -> None:
        barrier.wait()
        try:
            meter.reserve(ctx)
            result = "held"
        except UsageBlocked as exc:
            result = exc.reason.value
        with lock:
            outcomes.append(result)

    threads = [threading.Thread(target=race, args=(ctx,)) for ctx in contexts]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(outcomes) == ["held", *["insufficient_credits"] * 3]
    with sm() as session:
        held = session.scalar(select(func.sum(UsageGrantBalance.held)))
        remaining = session.scalar(select(func.sum(UsageGrantBalance.remaining)))
    assert (held, remaining) == (120, 150)
    assert [j.status for j in jobs_for(sm, student)] == [UsageJobStatus.open]


# --- exemptions ------------------------------------------------------------------------


def test_platform_admins_and_a_non_enforcing_meter_are_exempt(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    admin = seed_user(sm, Role.platform_admin)
    meter = enforcing_meter(sm)
    ctx = meter.authorize(_req(admin, role=Role.platform_admin))
    assert ctx.exempt is True
    with capture_logs() as logs, meter.job(ctx):
        record_llm_cost(Decimal("0.075"))
    (line,) = [e for e in logs if e["event"] == "usage_unmetered_cost"]
    assert (line["cost_usd"], line["exempt"], line["action"]) == ("0.075", True, "mark_paper")
    off = UsageMeter(sm, enforce=False)
    student = seed_user(sm)
    with off.job(off.authorize(_req(student))):
        record_llm_cost(Decimal("0.5"))
    assert jobs_for(sm, admin) == jobs_for(sm, student) == []


def test_unmetered_jobs_need_no_database() -> None:
    job = MeteredJob.unmetered(MeteredAction.MARK_PAPER)
    with job.run():
        record_llm_cost(Decimal("0.1"))
    job.release()


# --- estimate --------------------------------------------------------------------------


def test_estimate_view_reports_the_paying_scope(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    seed_catalogue(sm)
    student = seed_user(sm)
    meter = enforcing_meter(sm)
    give(
        sm,
        student,
        units=4000,
        kind=GrantKind.period_allowance,
        visible=False,
        expires_at=NOW.replace(month=12, day=1),
    )
    view = meter.estimate(_req(student))
    assert (view.low, view.high, view.payer) == (40, 120, "allowance")
    assert (view.percent_low, view.percent_high) == (1, 3)
    assert view.blocked_reason is None
    broke = seed_user(sm)
    blocked = meter.estimate(_req(broke))
    assert (blocked.payer, blocked.blocked_reason) == ("none", UsageBlockReason.NO_ACTIVE_PLAN)
    assert jobs_for(sm, student) == jobs_for(sm, broke) == []


# --- require_usage: the dependency, the 402 before the handler -------------------------


def _self_review_target() -> UsageTarget:
    return UsageTarget(subject_code=None, input_count=4)


def _team_guard() -> TeamActor:
    raise AssertionError("tests override the team guard")


_SELF_REVIEW_USAGE = require_usage(MeteredAction.SELF_REVIEW, target=_self_review_target)
_TEAM_REGRADE_USAGE = require_usage(MeteredAction.REGRADE, team=_team_guard)


def _usage_app(meter: UsageMeter, ran: list[UsageGrantContext]) -> FastAPI:
    app = FastAPI()
    app.add_exception_handler(UsageBlocked, usage_blocked_handler)

    @app.post("/review")
    def _review(ctx: Annotated[UsageGrantContext, Depends(_SELF_REVIEW_USAGE)]) -> dict[str, int]:
        ran.append(ctx)
        return {"high": ctx.estimate[1]}

    @app.post("/regrade")
    def _regrade(ctx: Annotated[UsageGrantContext, Depends(_TEAM_REGRADE_USAGE)]) -> dict[str, int]:
        ran.append(ctx)
        return {"high": ctx.estimate[1]}

    app.dependency_overrides[get_usage_meter] = lambda: meter
    return app


def test_require_usage_answers_402_before_the_handler_runs(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    seed_catalogue(sm)
    broke = seed_user(sm)
    ran: list[UsageGrantContext] = []
    app = _usage_app(enforcing_meter(sm), ran)
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(
        user_id=str(broke), role="student"
    )
    resp = TestClient(app).post("/review")
    assert resp.status_code == 402
    # self_review: base 1-2 plus 0-1 per mark point; the target's 4 points give 1-6.
    assert resp.json() == {"error": "usage_blocked", "reason": "no_active_plan", "estimate": [1, 6]}
    assert ran == []
    give(sm, broke, units=10)
    resp = TestClient(app).post("/review")
    assert (resp.status_code, resp.json()) == (200, {"high": 6})
    (ctx,) = ran
    assert ctx.request.input_count == 4
    assert ctx.request.actor_user_id == broke
    assert jobs_for(sm, broke) == []  # authorize holds nothing


def test_require_usage_with_a_team_guard_bills_the_lead(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    seed_catalogue(sm)
    lead, helper = seed_user(sm, Role.teacher), seed_user(sm, Role.teacher)
    give(sm, helper, units=1000)
    member = assistant(sm, teacher=lead, member=helper)
    ran: list[UsageGrantContext] = []
    app = _usage_app(enforcing_meter(sm), ran)
    app.dependency_overrides[_team_guard] = lambda: TeamActor(
        actor_user_id=helper,
        lead_teacher_user_id=lead,
        member_id=member,
        auth=AuthContext(user_id=str(lead), role="teacher"),
    )
    resp = TestClient(app).post("/regrade")
    assert (resp.status_code, resp.json()["reason"]) == (402, "no_active_plan")
    assert ran == []
    give(sm, lead, units=500)
    assert TestClient(app).post("/regrade").status_code == 200
    (ctx,) = ran
    assert ctx.request.assistant_member_id == member
    assert {p.owner_user_id for p in ctx.chain} == {lead}


# --- unconfirmed assistants: phase 03's 403, never the assistant's own balance ---------


def test_a_removed_assistant_is_a_403_and_never_falls_back_to_its_own_balance(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    from lemely.db.models.team import TeacherMember, TeacherMemberStatus

    sm = migrated_sessionmaker
    seed_catalogue(sm)
    lead, helper = seed_user(sm, Role.teacher), seed_user(sm, Role.teacher)
    give(sm, lead, units=1000)
    own = give(sm, helper, units=1000)
    member = assistant(sm, teacher=lead, member=helper)
    with sm.begin() as session:
        row = session.get(TeacherMember, member)
        assert row is not None
        row.status = TeacherMemberStatus.removed
    meter = enforcing_meter(sm)
    request = _req(helper, MeteredAction.REGRADE, role=Role.teacher, assistant_member_id=member)
    for call in (meter.authorize, meter.estimate):
        with pytest.raises(HTTPException) as info:
            call(request)
        assert info.value.status_code == 403
        assert info.value.detail == _team_permission_denied().detail
        assert "team_permission_denied" in str(info.value.detail)
    assert jobs_for(sm, helper) == []
    with sm() as session:
        balance = session.get(UsageGrantBalance, own)
        assert balance is not None
        assert (balance.remaining, balance.held) == (1000, 0)


def test_a_lead_with_school_data_is_phase_03s_team_lead_unavailable(
    migrated_sessionmaker: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The route body is exactly the team guard's: ``{"detail": {"code", "message"}}``."""
    from lemely.db.usage_context_repo import AssistantUnavailable

    sm = migrated_sessionmaker
    seed_catalogue(sm)
    lead, helper = seed_user(sm, Role.teacher), seed_user(sm, Role.teacher)
    give(sm, helper, units=1000)
    member = assistant(sm, teacher=lead, member=helper)

    def unavailable(*_a: object, **_k: object) -> None:
        raise AssistantUnavailable("team_lead_unavailable")

    monkeypatch.setattr(usage, "load_chain_context", unavailable)
    ran: list[UsageGrantContext] = []
    app = _usage_app(enforcing_meter(sm), ran)
    app.dependency_overrides[_team_guard] = lambda: TeamActor(
        actor_user_id=helper,
        lead_teacher_user_id=lead,
        member_id=member,
        auth=AuthContext(user_id=str(lead), role="teacher"),
    )
    resp = TestClient(app).post("/regrade")
    assert resp.status_code == 403
    assert resp.json() == {"detail": _team_lead_unavailable().detail}
    assert resp.json()["detail"]["code"] == "team_lead_unavailable"
    assert ran == []
    assert jobs_for(sm, helper) == []
