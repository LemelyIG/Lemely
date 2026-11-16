"""Usage sweeper jobs (Task 14): stale jobs, expired grants, nightly reconcile, signup repair."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta, timezone
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select
from structlog.testing import capture_logs

from lemely.core.metered_actions import MeteredAction
from lemely.db.models.billing import CreditPack
from lemely.db.models.enums import Role
from lemely.db.models.usage import GrantKind, UsageGrant, UsageGrantBalance, UsageJobStatus
from lemely.db.models.users import User
from lemely.db.usage_catalogue_repo import (
    SIGNUP_IDEMPOTENCY_KEY,
    SIGNUP_STUDENT_PACK,
)
from lemely.db.usage_ledger_repo import UsageLedger
from lemely.runtime.config import NotificationsSettings
from lemely.web.deps import AuthContext
from lemely.web.scheduled_notifications import Sweeper
from lemely.web.usage import request_from_auth
from lemely.web.usage_sweeps import (
    RECONCILE_HOUR_UTC,
    ReconcileMemo,
    RepairCursor,
    reconcile_balances,
    repair_signup_grants,
    usage_jobs,
)
from tests.usage_helpers import NOW, enforcing_meter, give, jobs_for, seed_catalogue, seed_user

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker

AT_3AM = datetime(2026, 11, 5, 3, 0, tzinfo=UTC)
EVERY_PASS = ["usage.expire_stale_jobs", "usage.expire_grants", "usage.repair_signup_grants"]


def _names(sm: sessionmaker[Session], now: datetime, memo: ReconcileMemo) -> list[str]:
    return [name for name, _ in usage_jobs(sm, now=now, memo=memo)]


def test_job_names_and_the_nightly_gate(migrated_sessionmaker: sessionmaker[Session]) -> None:
    memo = ReconcileMemo()
    early = datetime(2026, 11, 5, RECONCILE_HOUR_UTC - 1, 59, tzinfo=UTC)
    assert _names(migrated_sessionmaker, early, memo) == EVERY_PASS
    assert _names(migrated_sessionmaker, AT_3AM, memo) == [*EVERY_PASS, "usage.reconcile_balances"]
    memo.last_date = AT_3AM.date()
    assert _names(migrated_sessionmaker, AT_3AM, memo) == EVERY_PASS
    # The next UTC day runs it again, from 02:00.
    next_day = AT_3AM + timedelta(days=1)
    assert "usage.reconcile_balances" in _names(migrated_sessionmaker, next_day, memo)


def test_the_nightly_gate_reads_the_utc_date_not_the_local_one(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    """01:30 UTC is already 03:30 in Cairo, but the gate is on UTC."""
    cairo = datetime(2026, 11, 5, 3, 30, tzinfo=timezone(timedelta(hours=2)))
    assert "usage.reconcile_balances" not in _names(migrated_sessionmaker, cairo, ReconcileMemo())
    assert cairo.astimezone(UTC).hour == 1


def test_stale_open_jobs_expire_and_grants_past_expiry_expire(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    seed_catalogue(sm)
    student = seed_user(sm)
    give(sm, student, units=500)
    give(sm, student, units=40, expires_at=NOW + timedelta(hours=1))
    meter = enforcing_meter(sm)
    auth = AuthContext(user_id=str(student), role="student")
    meter.reserve(meter.authorize(request_from_auth(auth, MeteredAction.MARK_PAPER)))
    later = NOW + timedelta(hours=2)  # mark_paper timeout 45 min + 10 min slack has passed
    results = {name: job() for name, job in usage_jobs(sm, now=later, memo=ReconcileMemo())}
    assert results["usage.expire_stale_jobs"] == 1
    assert results["usage.expire_grants"] >= 1
    assert jobs_for(sm, student)[0].status is UsageJobStatus.expired


def test_a_job_whose_hold_was_renewed_is_not_expired(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    """The sweep goes through the ledger, which re-checks the deadline under the lock."""
    sm = migrated_sessionmaker
    seed_catalogue(sm)
    student = seed_user(sm)
    give(sm, student, units=500)
    meter = enforcing_meter(sm)
    auth = AuthContext(user_id=str(student), role="student")
    job = meter.reserve(meter.authorize(request_from_auth(auth, MeteredAction.MARK_PAPER)))
    later = NOW + timedelta(hours=2)
    with sm.begin() as session:
        UsageLedger(session).extend(job.job_id, expires_at=later + timedelta(minutes=30), now=later)
    names = dict(usage_jobs(sm, now=later, memo=ReconcileMemo()))
    assert names["usage.expire_stale_jobs"]() == 0
    assert jobs_for(sm, student)[0].status is UsageJobStatus.open


def test_reconcile_logs_drift_and_records_the_day(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    seed_catalogue(sm)
    student = seed_user(sm)
    grant_id = give(sm, student, units=100, kind=GrantKind.credit_pack)
    with sm.begin() as session:
        balance = session.scalars(
            select(UsageGrantBalance).where(UsageGrantBalance.grant_id == grant_id)
        ).one()
        balance.remaining = 90  # the cache drifts from the entries
    memo = ReconcileMemo()
    with capture_logs() as logs:
        drift = reconcile_balances(sm, now=AT_3AM, memo=memo)
    assert drift == 1
    assert memo.last_date == AT_3AM.date()
    event = next(e for e in logs if e["event"] == "usage_balance_drift")
    assert event["row_id"] == str(grant_id)
    assert (event["cached"], event["actual"]) == (90, 100)
    assert event["log_level"] == "error"
    # The ledger repaired the cache, so the next night is quiet.
    assert reconcile_balances(sm, now=AT_3AM + timedelta(days=1), memo=memo) == 0


def test_a_failed_reconcile_is_not_recorded_and_retries_after_a_back_off(
    migrated_sessionmaker: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Not every 60 s on every instance: the full scan is retried after RECONCILE_RETRY."""
    from lemely.web.usage_sweeps import RECONCILE_RETRY

    def boom(self: UsageLedger) -> list[tuple[uuid.UUID, int, int]]:
        raise RuntimeError("ledger down")

    monkeypatch.setattr(UsageLedger, "reconcile_balances", boom)
    memo = ReconcileMemo()
    with pytest.raises(RuntimeError):
        reconcile_balances(migrated_sessionmaker, now=AT_3AM, memo=memo)
    assert memo.last_date is None
    soon = AT_3AM + RECONCILE_RETRY - timedelta(seconds=1)
    assert "usage.reconcile_balances" not in _names(migrated_sessionmaker, soon, memo)
    retry = AT_3AM + RECONCILE_RETRY
    assert "usage.reconcile_balances" in _names(migrated_sessionmaker, retry, memo)
    monkeypatch.undo()
    assert reconcile_balances(migrated_sessionmaker, now=retry, memo=memo) == 0
    assert memo == ReconcileMemo(last_date=retry.date(), retry_after=None)


# --- usage.repair_signup_grants -------------------------------------------------------


def _verified(sm: sessionmaker[Session], role: Role, *, verified: bool = True) -> uuid.UUID:
    user_id = seed_user(sm, role)
    if verified:
        with sm.begin() as session:
            user = session.get(User, user_id)
            assert user is not None
            user.email_verified_at = NOW - timedelta(days=30)
    return user_id


def _signup_grants(sm: sessionmaker[Session], owner: uuid.UUID) -> list[UsageGrant]:
    with sm() as session:
        return list(
            session.scalars(
                select(UsageGrant).where(
                    UsageGrant.owner_user_id == owner,
                    UsageGrant.idempotency_key == SIGNUP_IDEMPOTENCY_KEY,
                )
            )
        )


def test_a_user_verified_before_deploy_gets_exactly_one_signup_grant(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    seed_catalogue(sm)
    student = _verified(sm, Role.student)
    teacher = _verified(sm, Role.teacher)
    assert repair_signup_grants(sm, now=AT_3AM, cursor=RepairCursor()) == 2
    [student_grant] = _signup_grants(sm, student)
    [teacher_grant] = _signup_grants(sm, teacher)
    assert (student_grant.kind, student_grant.visible, student_grant.expires_at) == (
        GrantKind.signup,
        False,
        None,
    )
    # The teacher's 30 days count from the repair, not from the old verification.
    assert teacher_grant.visible is True
    assert teacher_grant.expires_at == AT_3AM + timedelta(days=30)


def test_a_failed_signup_grant_is_repaired_and_a_rerun_grants_nothing(
    migrated_sessionmaker: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    """``mark_email_verified`` logs ``signup_grant_failed`` and commits; the sweep heals it."""
    sm = migrated_sessionmaker
    seed_catalogue(sm)
    student = _verified(sm, Role.student)
    assert _signup_grants(sm, student) == []  # the grant never landed
    assert repair_signup_grants(sm, now=AT_3AM, cursor=RepairCursor()) == 1
    assert len(_signup_grants(sm, student)) == 1
    with capture_logs() as logs:
        assert repair_signup_grants(sm, now=AT_3AM, cursor=RepairCursor()) == 0
    assert len(_signup_grants(sm, student)) == 1
    assert not [e for e in logs if e["event"] == "signup_grants_repaired"]


def test_repair_skips_the_unverified_and_the_other_roles(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    seed_catalogue(sm)
    skipped = [
        _verified(sm, Role.student, verified=False),
        _verified(sm, Role.teacher, verified=False),
        _verified(sm, Role.parent),
        _verified(sm, Role.school_admin),
        _verified(sm, Role.platform_admin),
    ]
    assert repair_signup_grants(sm, now=AT_3AM, cursor=RepairCursor()) == 0
    assert [_signup_grants(sm, user) for user in skipped] == [[]] * len(skipped)


def test_a_disabled_pack_grants_nothing(migrated_sessionmaker: sessionmaker[Session]) -> None:
    sm = migrated_sessionmaker
    seed_catalogue(sm)
    with sm.begin() as session:
        pack = session.scalars(
            select(CreditPack).where(CreditPack.code == SIGNUP_STUDENT_PACK)
        ).one()
        pack.units = 0
    student = _verified(sm, Role.student)
    teacher = _verified(sm, Role.teacher)
    # Only the enabled pack's role is granted, and the student is not even visited.
    assert repair_signup_grants(sm, now=AT_3AM, cursor=RepairCursor()) == 1
    assert _signup_grants(sm, student) == []
    assert len(_signup_grants(sm, teacher)) == 1


def test_a_disabled_pack_is_not_even_walked(
    migrated_sessionmaker: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    """With the student pack at 0 units no student is visited, so the sweep stays cheap."""
    import lemely.web.usage_sweeps as sweeps

    sm = migrated_sessionmaker
    seed_catalogue(sm)
    with sm.begin() as session:
        for pack in session.scalars(select(CreditPack)):
            pack.units = 0
    _verified(sm, Role.student)
    _verified(sm, Role.teacher)
    visited: list[uuid.UUID] = []

    def spy(session: Session, *, user_id: uuid.UUID, role: Role, now: datetime) -> None:
        visited.append(user_id)

    monkeypatch.setattr(sweeps, "grant_signup_allowance", spy)
    cursor = RepairCursor(after=uuid.uuid4())
    assert repair_signup_grants(sm, now=AT_3AM, cursor=cursor) == 0
    assert visited == []
    assert cursor.after is None


def test_repair_seeds_the_catalogue_when_it_is_missing(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    """A deploy that has not yet metered anyone has no pack rows; the repair still grants."""
    sm = migrated_sessionmaker
    student = _verified(sm, Role.student)
    assert repair_signup_grants(sm, now=AT_3AM, cursor=RepairCursor()) == 1
    assert len(_signup_grants(sm, student)) == 1


def test_repair_is_bounded_per_sweep_and_the_cursor_walks_the_backlog(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    seed_catalogue(sm)
    users = sorted(_verified(sm, Role.student) for _ in range(5))
    cursor = RepairCursor()
    assert repair_signup_grants(sm, now=AT_3AM, cursor=cursor, limit=2) == 2
    assert cursor.after == users[1]
    assert repair_signup_grants(sm, now=AT_3AM, cursor=cursor, limit=2) == 2
    assert repair_signup_grants(sm, now=AT_3AM, cursor=cursor, limit=2) == 1
    # A short batch ends the walk; the next sweep starts again from the beginning.
    assert cursor.after is None
    assert repair_signup_grants(sm, now=AT_3AM, cursor=cursor, limit=2) == 0
    assert all(len(_signup_grants(sm, user)) == 1 for user in users)


def test_a_user_who_cannot_be_granted_does_not_starve_the_rest(
    migrated_sessionmaker: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    import lemely.web.usage_sweeps as sweeps

    sm = migrated_sessionmaker
    seed_catalogue(sm)
    users = sorted(_verified(sm, Role.student) for _ in range(4))
    poisoned = users[0]
    real = sweeps.grant_signup_allowance

    def flaky(
        session: Session, *, user_id: uuid.UUID, role: Role, now: datetime
    ) -> UsageGrant | None:
        if user_id == poisoned:
            raise RuntimeError("ledger said no")
        return real(session, user_id=user_id, role=role, now=now)

    monkeypatch.setattr(sweeps, "grant_signup_allowance", flaky)
    cursor = RepairCursor()
    with capture_logs() as logs:
        assert repair_signup_grants(sm, now=AT_3AM, cursor=cursor, limit=2) == 1
        assert repair_signup_grants(sm, now=AT_3AM, cursor=cursor, limit=2) == 2
    # The first batch's cursor moved past the poisoned user, so batch two reached the rest.
    assert _signup_grants(sm, poisoned) == []
    assert all(len(_signup_grants(sm, user)) == 1 for user in users[1:])
    failed = [e for e in logs if e["event"] == "usage_signup_repair_failed"]
    assert [e["user_id"] for e in failed] == [str(poisoned)]
    assert failed[0]["log_level"] == "error"


def test_a_grant_another_replica_issued_first_is_not_counted(
    migrated_sessionmaker: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ledger answers a replay with the stored grant; only a new grant is counted."""
    import lemely.web.usage_sweeps as sweeps

    sm = migrated_sessionmaker
    seed_catalogue(sm)
    raced = _verified(sm, Role.student)
    fresh = _verified(sm, Role.student)
    real = sweeps.grant_signup_allowance

    def racing(
        session: Session, *, user_id: uuid.UUID, role: Role, now: datetime
    ) -> UsageGrant | None:
        if user_id == raced:  # the other replica commits its grant before ours takes the lock
            with sm.begin() as other:
                real(other, user_id=user_id, role=role, now=now - timedelta(minutes=1))
        return real(session, user_id=user_id, role=role, now=now)

    monkeypatch.setattr(sweeps, "grant_signup_allowance", racing)
    with capture_logs() as logs:
        assert repair_signup_grants(sm, now=AT_3AM, cursor=RepairCursor()) == 1
    assert len(_signup_grants(sm, raced)) == len(_signup_grants(sm, fresh)) == 1
    [event] = [e for e in logs if e["event"] == "signup_grants_repaired"]
    assert event["count"] == 1


def test_the_repair_logs_how_many_it_granted(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    seed_catalogue(sm)
    for _ in range(3):
        _verified(sm, Role.student)
    with capture_logs() as logs:
        assert repair_signup_grants(sm, now=AT_3AM, cursor=RepairCursor()) == 3
    [event] = [e for e in logs if e["event"] == "signup_grants_repaired"]
    assert event["count"] == 3


# --- the Sweeper ----------------------------------------------------------------------


def _sweeper(sm: sessionmaker[Session], *, metering: bool) -> Sweeper:
    return Sweeper(
        sessionmaker=sm,
        announcements=MagicMock(),
        notifications=MagicMock(),
        transport=MagicMock(),
        settings=NotificationsSettings(),
        now=lambda: AT_3AM,
        usage_metering=metering,
    )


def test_the_sweeper_runs_the_usage_jobs_only_when_metering(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    on = _sweeper(migrated_sessionmaker, metering=True).sweep_once()
    off = _sweeper(migrated_sessionmaker, metering=False).sweep_once()
    assert {*EVERY_PASS, "usage.reconcile_balances"} <= set(on)
    assert not any(name.startswith("usage.") for name in off)


def test_a_failing_usage_job_never_stops_the_pass(
    migrated_sessionmaker: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(self: UsageLedger, **_kwargs: object) -> int:
        raise RuntimeError("ledger down")

    # The web sweeper's entry point into the ledger for stale jobs.
    monkeypatch.setattr(UsageLedger, "sweep_stale_jobs", boom)
    results = _sweeper(migrated_sessionmaker, metering=True).sweep_once()
    assert results["usage.expire_stale_jobs"] is None
    assert results["usage.expire_grants"] == 0
    assert results["usage.repair_signup_grants"] == 0
    assert results["usage.reconcile_balances"] == 0


def test_the_sweeper_remembers_the_reconcile_between_passes(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sweeper = _sweeper(migrated_sessionmaker, metering=True)
    assert "usage.reconcile_balances" in sweeper.sweep_once()
    assert "usage.reconcile_balances" not in sweeper.sweep_once()
