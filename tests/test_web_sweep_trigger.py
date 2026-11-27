"""``POST /api/internal/jobs/sweep``: one sweeper pass, triggered by Cloud Scheduler.

Cloud Run runs with ``--min-instances=0`` and throttled CPU, so the in-process sweep loop does
nothing while no request is being served. Cloud Scheduler calls this route instead, with the
shared secret in ``X-Cron-Secret`` (the same scheme as the waitlist digest trigger).

Hermetic: a throwaway ``create_all`` Postgres and a real :class:`Sweeper` whose Paymob-backed
collaborators are recording fakes. The app is built without its lifespan (a bare ``TestClient``),
so no sweep loop runs beside the route under test.
"""

from __future__ import annotations

import asyncio
import math
import threading
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import event
from structlog.testing import capture_logs

from lemely.db.announcement_repo import AnnouncementService
from lemely.db.billing_observability_repo import JobRunRecorder
from lemely.db.class_repo import ClassService
from lemely.db.merchant_charge_repo import BatchStops
from lemely.db.notification_prefs_repo import NotificationPreferencesService
from lemely.db.notification_repo import NotificationService
from lemely.runtime.config import NotificationsSettings, Settings
from lemely.web import scheduled_notifications
from lemely.web.app import create_app
from lemely.web.deps import get_settings, get_sweeper
from lemely.web.push import RecordingPushTransport
from lemely.web.scheduled_notifications import (
    EXTRA_SEAT_RENEWAL_SHARE,
    PAYMENT_TURN_MINUTES,
    RECONCILE_SHARE,
    SWEEP_LOCK_KEY,
    PassBudget,
    Sweeper,
    SweepPass,
    UnitCost,
    run_sweeper,
)
from tests.storage_fakes import FakeStorageBackend
from tests.tutoring_db import tutoring_database

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from httpx2 import Response
    from sqlalchemy.orm import Session, sessionmaker

SECRET = "sweep-secret-for-tests"
OLD_SECRET = "gwqrn-mtxhuj-zzb-kcvsd"
PATH = "/api/internal/jobs/sweep"
HEADERS = {"X-Cron-Secret": SECRET}
MORNING = datetime(2026, 9, 5, 1, 30, tzinfo=UTC)  # before the daily reconcile hour (02:00 UTC)


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


class Counter:
    """A billing job stand-in: counts its calls and returns a fixed number."""

    def __init__(self, result: int) -> None:
        self.calls = 0
        self.result = result

    def __call__(self, _now: datetime, _should_stop: Callable[[], bool] | None = None) -> int:
        self.calls += 1
        return self.result


class Monotonic:
    """A fake monotonic clock; a job "takes" time by calling :meth:`spend`."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def spend(self, seconds: float) -> None:
        self.now += seconds


class SpySweeper:
    """Stands in for the sweeper where a route must refuse before any pass starts."""

    def __init__(self) -> None:
        self.passes = 0

    def sweep_exclusive(self) -> SweepPass:
        self.passes += 1
        return SweepPass(results={}, skipped=[])


@pytest.fixture(scope="module")
def database() -> Iterator[sessionmaker[Session]]:
    with tutoring_database() as factory:
        yield factory


def make_sweeper(
    sm: sessionmaker[Session],
    clock: Clock | None = None,
    *,
    settings: NotificationsSettings | None = None,
    **collaborators: object,
) -> Sweeper:
    return Sweeper(
        sessionmaker=sm,
        announcements=AnnouncementService(sm, ClassService(sm)),
        notifications=NotificationService(sm, NotificationPreferencesService(sm)),
        transport=RecordingPushTransport(),
        settings=settings or NotificationsSettings(),
        now=clock or Clock(MORNING),
        **collaborators,  # type: ignore[arg-type]
    )


def _secret(value: str | None) -> SecretStr | None:
    return None if value is None else SecretStr(value)


def make_client(
    sweeper: object, *, secret: str | None = SECRET, previous: str | None = None
) -> TestClient:
    app = create_app()
    settings = get_settings().model_copy(
        update={
            "notifications": NotificationsSettings(
                jobs_secret=_secret(secret), jobs_secret_previous=_secret(previous)
            )
        }
    )
    app.dependency_overrides.update({get_settings: lambda: settings, get_sweeper: lambda: sweeper})
    return TestClient(app)


def trigger(client: TestClient, secret: str | None = SECRET) -> Response:
    return client.post(PATH, headers={} if secret is None else {"X-Cron-Secret": secret})


# -- auth ---------------------------------------------------------------------


def test_the_route_requires_the_secret() -> None:
    spy = SpySweeper()
    client = make_client(spy)

    assert trigger(client, None).status_code == 403
    assert trigger(client, "wrong").status_code == 403
    assert trigger(client, "").status_code == 403
    assert spy.passes == 0


def test_a_refused_call_never_builds_the_sweeper() -> None:
    # The sweeper carries the payment client and the database pool; an unauthenticated caller
    # must not be able to make the process build it (or fail building it).
    built: list[bool] = []

    def sweeper() -> SpySweeper:
        built.append(True)
        return SpySweeper()

    client = make_client(SpySweeper())
    client.app.dependency_overrides[get_sweeper] = sweeper  # type: ignore[attr-defined]
    unset = make_client(SpySweeper(), secret=None)
    unset.app.dependency_overrides[get_sweeper] = sweeper  # type: ignore[attr-defined]

    assert trigger(client, "wrong").status_code == 403
    assert trigger(client, None).status_code == 403
    assert trigger(unset).status_code == 503
    assert built == []
    assert trigger(client).status_code == 200
    assert built == [True]


def test_the_route_refuses_with_503_when_no_secret_is_configured() -> None:
    spy = SpySweeper()
    client = make_client(spy, secret=None)

    # Not 200, and not a bare 404: the scheduler job exists but the service cannot serve it.
    assert trigger(client, SECRET).status_code == 503
    assert trigger(client, None).status_code == 503
    assert spy.passes == 0


@pytest.mark.parametrize("blank", ["", "   "])
def test_a_blank_secret_in_the_environment_counts_as_unset(
    blank: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # deploy.yml renders an unset GitHub secret as "".
    monkeypatch.setenv("LEMELY_NOTIFICATIONS__JOBS_SECRET", blank)
    assert Settings().notifications.jobs_secret is None

    monkeypatch.setenv("LEMELY_NOTIFICATIONS__JOBS_SECRET", SECRET)
    secret = Settings().notifications.jobs_secret
    assert secret is not None
    assert secret.get_secret_value() == SECRET
    assert SECRET not in repr(Settings().notifications)


def test_the_correct_secret_runs_a_pass() -> None:
    spy = SpySweeper()

    response = trigger(make_client(spy))

    assert response.status_code == 200
    assert spy.passes == 1


# -- one pass runs every sweep ------------------------------------------------


def test_one_pass_runs_every_sweep_and_reports_counts_only(
    database: sessionmaker[Session],
) -> None:
    clock = Clock(datetime(2026, 9, 5, 3, 0, tzinfo=UTC))
    reconcile, seat_renewal, topup = Counter(2), Counter(1), Counter(3)
    sweeper = make_sweeper(
        database,
        clock,
        storage=FakeStorageBackend(),
        bucket="lemely-uploads-test",
        billing_reconcile=reconcile,
        billing_extra_seat_renewal=seat_renewal,
        billing_auto_topup=topup,
        usage_metering=True,
        seat_allowances=True,
        job_recorder=JobRunRecorder(database),
    )

    response = trigger(make_client(sweeper))

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"status", "jobs", "failed", "skipped"}
    assert body["status"] == "completed"
    assert body["failed"] == []
    assert body["skipped"] == []
    assert list(body["jobs"]) == [
        "publish_due_announcements",
        "warn_streaks",
        "remind_study_plans",
        "admin.expire_manual_subscriptions",
        "purge_expired_papers",
        "purge_expired_teacher_papers",
        "billing.reconcile_pending",
        "billing.prune_webhook_failures",
        "billing.llm_price_refresh",
        "usage.expire_stale_jobs",
        "usage.expire_grants",
        "usage.repair_signup_grants",
        "usage.reconcile_balances",
        "seats.release_due",
        "seats.monthly_allowance",
        "billing.extra_seat_renewal_charge",
        "billing.auto_topup",
    ]
    assert all(isinstance(count, int) for count in body["jobs"].values())
    assert (body["jobs"]["billing.reconcile_pending"], reconcile.calls) == (2, 1)
    assert (body["jobs"]["billing.extra_seat_renewal_charge"], seat_renewal.calls) == (1, 1)
    assert (body["jobs"]["billing.auto_topup"], topup.calls) == (3, 1)


def test_a_pass_without_paymob_runs_what_the_loop_runs_and_skips_the_billing_jobs(
    database: sessionmaker[Session],
) -> None:
    sweeper = make_sweeper(database, seat_allowances=True)

    response = trigger(make_client(sweeper))

    assert response.status_code == 200
    jobs = response.json()["jobs"]
    assert not [name for name in jobs if name.startswith("billing.")]
    assert {"publish_due_announcements", "seats.release_due", "seats.monthly_allowance"} <= set(
        jobs
    )


# -- a failing sweep does not stop the others ---------------------------------


def test_one_sweep_raising_does_not_stop_the_rest_and_is_visible(
    database: sessionmaker[Session],
) -> None:
    def explode(_now: datetime, _stop: Callable[[], bool]) -> int:
        raise RuntimeError("card ending 4242 for ada@example.com")

    topup = Counter(3)
    sweeper = make_sweeper(database, billing_reconcile=explode, billing_auto_topup=topup)

    with capture_logs() as logs:
        response = trigger(make_client(sweeper))

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["failed"] == ["billing.reconcile_pending"]
    assert body["jobs"]["billing.reconcile_pending"] is None
    assert body["jobs"]["billing.auto_topup"] == 3  # ran after the failed one
    assert topup.calls == 1
    # The response carries the job's name, never the exception text (it can echo customer data).
    assert "4242" not in response.text
    assert "ada@example.com" not in response.text
    failed = [e for e in logs if e["event"] == "sweep_job_failed"]
    assert [e["job"] for e in failed] == ["billing.reconcile_pending"]


# -- concurrency --------------------------------------------------------------


def test_a_second_call_during_a_pass_is_skipped_quickly(database: sessionmaker[Session]) -> None:
    started, release = threading.Event(), threading.Event()
    other_runs = Counter(0)

    def slow(_now: datetime, _stop: Callable[[], bool]) -> int:
        started.set()
        assert release.wait(10)
        return 1

    sweeper = make_sweeper(database, billing_reconcile=slow, billing_auto_topup=other_runs)
    first: dict[str, Response] = {}

    def run_first() -> None:
        first["response"] = trigger(make_client(sweeper))

    worker = threading.Thread(target=run_first)
    worker.start()
    try:
        assert started.wait(10)
        with capture_logs() as logs:
            second = trigger(make_client(sweeper))
        assert second.status_code == 200
        assert second.json() == {"status": "skipped", "jobs": {}, "failed": [], "skipped": []}
        assert [e for e in logs if e["event"] == "sweep_pass_skipped"]
        assert other_runs.calls == 0  # the skipped call ran nothing
    finally:
        release.set()
        worker.join(10)

    assert first["response"].json()["status"] == "completed"
    assert other_runs.calls == 1  # exactly one pass ran
    assert trigger(make_client(sweeper)).json()["status"] == "completed"  # the lock was released


def test_a_pass_held_by_another_replica_makes_this_call_skip(
    database: sessionmaker[Session],
) -> None:
    topup = Counter(3)
    sweeper = make_sweeper(database, billing_auto_topup=topup)
    client = make_client(sweeper)

    with database() as other_replica, other_replica.begin():
        other_replica.execute(
            sa.text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": SWEEP_LOCK_KEY},
        )
        held = trigger(client)

    assert held.json() == {"status": "skipped", "jobs": {}, "failed": [], "skipped": []}
    assert topup.calls == 0
    assert trigger(client).json()["status"] == "completed"
    assert topup.calls == 1


def test_the_lock_transaction_bounds_its_own_idle_time_and_only_its_own(
    database: sessionmaker[Session],
) -> None:
    # The lock connection sits idle in its transaction while the jobs run on other sessions. If
    # the process stalls (CPU throttled, a hung worker), Postgres ends that transaction after
    # 240 s and the lock goes with it, so a stalled pass cannot block every later pass.
    engine = database.kw["bind"]
    statements: list[tuple[int, str]] = []

    def record(conn: sa.Connection, _cursor: object, statement: str, *_rest: object) -> None:
        statements.append((id(conn.connection.dbapi_connection), statement))

    event.listen(engine, "before_cursor_execute", record)
    try:
        make_sweeper(database).sweep_exclusive()
    finally:
        event.remove(engine, "before_cursor_execute", record)

    lock_at = next(i for i, (_c, s) in enumerate(statements) if "pg_try_advisory_xact_lock" in s)
    lock_conn = statements[lock_at][0]
    on_lock_conn = [s for c, s in statements[:lock_at] if c == lock_conn]
    assert "SET LOCAL idle_in_transaction_session_timeout = '240s'" in on_lock_conn
    # SET LOCAL ends with the transaction: the pooled connection goes back with the default.
    with engine.connect() as conn:
        assert conn.scalar(sa.text("SHOW idle_in_transaction_session_timeout")) == "0"


# -- the daily job runs only when due -----------------------------------------


def _reconciled(response: Response) -> bool:
    return "usage.reconcile_balances" in response.json()["jobs"]


def test_the_daily_reconcile_runs_only_once_it_is_due_and_once_per_utc_day(
    database: sessionmaker[Session],
) -> None:
    clock = Clock(MORNING)
    client = make_client(make_sweeper(database, clock, usage_metering=True))

    before_the_hour = trigger(client)
    clock.now = datetime(2026, 9, 5, 2, 0, tzinfo=UTC)
    at_the_hour = trigger(client)
    clock.now = datetime(2026, 9, 5, 14, 0, tzinfo=UTC)
    later_same_day = trigger(client)
    clock.now = datetime(2026, 9, 6, 1, 59, tzinfo=UTC)
    next_day_before_the_hour = trigger(client)
    clock.now = clock.now + timedelta(minutes=1)
    next_day_due = trigger(client)

    passes = (before_the_hour, at_the_hour, later_same_day, next_day_before_the_hour, next_day_due)
    assert [_reconciled(r) for r in passes] == [False, True, False, False, True]
    # The other usage sweeps run on every pass, due or not.
    assert "usage.expire_grants" in before_the_hour.json()["jobs"]


# -- rotation: the previous secret is accepted beside the current one ---------


def test_the_previous_secret_is_accepted_during_a_rotation_and_nothing_else_is() -> None:
    spy = SpySweeper()
    client = make_client(spy, secret=SECRET, previous=OLD_SECRET)

    assert trigger(client, SECRET).status_code == 200
    assert trigger(client, OLD_SECRET).status_code == 200
    assert spy.passes == 2
    for wrong in ("wrong", "", OLD_SECRET + "x", SECRET[:-1], SECRET.upper()):
        assert trigger(client, wrong).status_code == 403, wrong
    assert trigger(client, None).status_code == 403
    assert spy.passes == 2


def test_without_a_previous_secret_the_old_value_is_refused() -> None:
    spy = SpySweeper()
    client = make_client(spy, secret=SECRET, previous=None)

    assert trigger(client, OLD_SECRET).status_code == 403
    assert spy.passes == 0


def test_the_previous_secret_alone_does_not_configure_the_route() -> None:
    spy = SpySweeper()
    client = make_client(spy, secret=None, previous=OLD_SECRET)

    assert trigger(client, OLD_SECRET).status_code == 503
    assert spy.passes == 0


def test_both_secrets_are_compared_whatever_the_first_comparison_says(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lemely.web.routers import internal_jobs

    calls: list[bytes] = []
    real = internal_jobs.hmac.compare_digest

    def spy_compare(a: bytes, b: bytes) -> bool:
        calls.append(b)
        return real(a, b)

    monkeypatch.setattr(internal_jobs.hmac, "compare_digest", spy_compare)
    client = make_client(SpySweeper(), secret=SECRET, previous=OLD_SECRET)

    # A match on the current secret still compares the previous one (no short circuit that
    # would tell a timing observer which value matched), and a miss compares both.
    for supplied in (SECRET, OLD_SECRET, "wrong"):
        calls.clear()
        trigger(client, supplied)
        assert calls == [SECRET.encode(), OLD_SECRET.encode()], supplied


@pytest.mark.parametrize("blank", ["", "   "])
def test_a_blank_previous_secret_in_the_environment_counts_as_unset(
    blank: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LEMELY_NOTIFICATIONS__JOBS_SECRET_PREVIOUS", blank)
    assert Settings().notifications.jobs_secret_previous is None

    monkeypatch.setenv("LEMELY_NOTIFICATIONS__JOBS_SECRET_PREVIOUS", OLD_SECRET)
    previous = Settings().notifications.jobs_secret_previous
    assert previous is not None
    assert previous.get_secret_value() == OLD_SECRET
    assert OLD_SECRET not in repr(Settings().notifications)


# -- the pass budget ----------------------------------------------------------


def _timed(
    database: sessionmaker[Session], monotonic: Monotonic, *, budget: int = 100, **jobs: Any
) -> Sweeper:
    return make_sweeper(
        database,
        settings=NotificationsSettings(sweep_pass_budget_seconds=budget),
        monotonic=monotonic,
        **jobs,
    )


def test_a_pass_that_spends_its_budget_skips_the_remaining_jobs_and_reports_them(
    database: sessionmaker[Session],
) -> None:
    monotonic = Monotonic()
    seat_renewal, topup = Counter(1), Counter(3)

    def slow_reconcile(_now: datetime, _stop: Callable[[], bool]) -> int:
        monotonic.spend(120)  # the batch overran the whole pass budget
        return 5

    sweeper = _timed(
        database,
        monotonic,
        billing_reconcile=slow_reconcile,
        billing_extra_seat_renewal=seat_renewal,
        billing_auto_topup=topup,
        seat_allowances=True,
    )

    with capture_logs() as logs:
        response = trigger(make_client(sweeper))

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "completed"
    # Skipped is not failed: these jobs did not run and will run on the next tick.
    assert body["skipped"] == [
        "seats.release_due",
        "seats.monthly_allowance",
        "billing.extra_seat_renewal_charge",
        "billing.auto_topup",
    ]
    assert body["failed"] == []
    assert body["jobs"]["billing.reconcile_pending"] == 5
    assert not set(body["skipped"]) & set(body["jobs"])
    assert (seat_renewal.calls, topup.calls) == (0, 0)
    spent = [e for e in logs if e["event"] == "sweep_pass_budget_spent"]
    assert [e["skipped"] for e in spent] == [body["skipped"]]
    assert not [e for e in logs if e["event"] == "sweep_job_failed"]


def test_a_pass_within_its_budget_skips_nothing(database: sessionmaker[Session]) -> None:
    monotonic = Monotonic()
    topup = Counter(3)

    def quick(_now: datetime, _stop: Callable[[], bool]) -> int:
        monotonic.spend(20)
        return 1

    sweeper = _timed(database, monotonic, billing_reconcile=quick, billing_auto_topup=topup)

    body = trigger(make_client(sweeper)).json()

    assert body["skipped"] == []
    assert body["jobs"]["billing.auto_topup"] == 3


def test_the_reconcile_batch_stops_at_its_share_so_later_jobs_are_not_starved(
    database: sessionmaker[Session],
) -> None:
    # The batch is the one job with a long, serial tail (20 Paymob inquiries). It stops between
    # rows once it has used its slice of the budget, so the seat charges and the auto top-up
    # behind it get time on every tick instead of being skipped every tick.
    monotonic = Monotonic()
    rows_done: list[int] = []
    topup = Counter(3)

    sweeper = _timed(
        database,
        monotonic,
        billing_reconcile=_row_batch(monotonic, rows_done, 10),
        billing_auto_topup=topup,
    )

    body = trigger(make_client(sweeper)).json()

    # Rows start at 0 s and 10 s; at 20 s the 13 s slice is used.
    assert rows_done == [math.ceil(100 * RECONCILE_SHARE / 10)] == [2]
    assert body["jobs"]["billing.reconcile_pending"] == rows_done[0]
    assert body["skipped"] == []
    assert topup.calls == 1


#: A saved-card charge's expected time with the default settings: 1 s of database work and two
#: Paymob requests at 7 s each.
CHARGE_TYPICAL = 15.0


def _row_batch(
    monotonic: Monotonic, rows_done: list[int], seconds_per_row: float, rows: int = 200
) -> Callable[[datetime, Callable[[], bool]], int]:
    """Stands in for a batch of rows: asks the stop check before each row."""

    def batch(_now: datetime, should_stop: Callable[[], bool] | None) -> int:
        done = 0
        for _row in range(rows):
            if should_stop is not None and should_stop():
                break
            monotonic.spend(seconds_per_row)  # one row, finished before the next check
            done += 1
        rows_done.append(done)
        return done

    return batch


def _charge_batch(
    monotonic: Monotonic,
    charges_done: list[int],
    seconds_per_charge: float,
    *,
    rows: int = 0,
    seconds_per_row: float = 1.0,
) -> Callable[[datetime, BatchStops], int]:
    """Stands in for a saved-card charge job: database rows first, then charges, as both run."""

    def batch(_now: datetime, stops: BatchStops) -> int:
        done = 0
        for _row in range(rows):
            if stops.row():
                break
            monotonic.spend(seconds_per_row)
            done += 1
        charged = 0
        for _charge in range(200):
            if stops.charge():
                break
            monotonic.spend(
                seconds_per_charge
            )  # one claimed charge, finished before the next check
            charged += 1
        charges_done.append(charged)
        return done + charged

    return batch


def test_the_seat_charge_stops_at_its_share_and_the_top_up_uses_what_is_left(
    database: sessionmaker[Session],
) -> None:
    monotonic = Monotonic()
    seats_done: list[int] = []
    topups_done: list[int] = []

    sweeper = _timed(
        database,
        monotonic,
        billing_extra_seat_renewal=_charge_batch(monotonic, seats_done, 5),
        billing_auto_topup=_charge_batch(monotonic, topups_done, 5),
    )

    body = trigger(make_client(sweeper)).json()

    # Charges start at 0 s and 5 s; at 10 s the seat job's 10 s slice is used.
    assert seats_done == [math.ceil(100 * EXTRA_SEAT_RENEWAL_SHARE / 5)] == [2]
    # The top-up is last and has no slice: it starts charges while one still fits the budget,
    # so from 10 s up to 85 s (85 s + 15 s expected = 100 s).
    assert topups_done == [int((100 - 10 - CHARGE_TYPICAL) // 5) + 1] == [16]
    assert body["jobs"]["billing.extra_seat_renewal_charge"] == seats_done[0]
    assert body["jobs"]["billing.auto_topup"] == topups_done[0]
    assert body["skipped"] == []


def _spend(monotonic: Monotonic, seconds: float) -> Callable[[datetime, Callable[[], bool]], int]:
    def job(_now: datetime, _stop: Callable[[], bool]) -> int:
        monotonic.spend(seconds)
        return 0

    return job


@pytest.mark.parametrize(
    ("elapsed", "charged"), [(60 - CHARGE_TYPICAL, 1), (60 - CHARGE_TYPICAL + 0.001, 0)]
)
def test_a_charge_is_claimed_only_while_its_expected_time_fits_the_budget(
    elapsed: float, charged: int, database: sessionmaker[Session]
) -> None:
    monotonic = Monotonic()
    topups_done: list[int] = []
    sweeper = _timed(
        database,
        monotonic,
        budget=60,
        billing_reconcile=_spend(monotonic, elapsed),
        billing_auto_topup=_charge_batch(monotonic, topups_done, CHARGE_TYPICAL),
    )

    body = trigger(make_client(sweeper)).json()

    # Not yet spent, but a charge started past 45 s would be expected to end past 60 s: it is
    # not claimed and stays queued for the next pass.
    assert topups_done == [charged]
    assert body["skipped"] == []


def test_a_slow_claimed_charge_finishes_nothing_more_starts_and_the_overrun_is_logged(
    database: sessionmaker[Session],
) -> None:
    monotonic = Monotonic()
    topups_done: list[int] = []
    sweeper = _timed(
        database,
        monotonic,
        budget=60,
        billing_auto_topup=_charge_batch(monotonic, topups_done, 120),
    )

    with capture_logs() as logs:
        body = trigger(make_client(sweeper)).json()

    assert topups_done == [1]  # never cut short once claimed, and nothing after it
    assert body["jobs"]["billing.auto_topup"] == 1
    assert body["failed"] == []
    overran = [e for e in logs if e["event"] == "sweep_pass_overran"]
    assert [(e["elapsed_seconds"], e["budget_seconds"]) for e in overran] == [(120.0, 60)]
    assert not [e for e in logs if e["event"] == "sweep_job_failed"]


def test_waiting_for_a_connection_or_the_lock_counts_against_the_budget(
    database: sessionmaker[Session],
) -> None:
    monotonic = Monotonic()
    topups_done: list[int] = []
    waited = False

    def slow_checkout() -> Session:
        nonlocal waited
        if not waited:  # only the lock transaction's checkout waits
            waited = True
            monotonic.spend(46)
        return database()

    sweeper = _timed(
        database,
        monotonic,
        budget=60,
        billing_auto_topup=_charge_batch(monotonic, topups_done, CHARGE_TYPICAL),
    )
    sweeper.sessionmaker = slow_checkout  # type: ignore[assignment]

    trigger(make_client(sweeper))

    # 46 s gone before the lock was taken leaves no room for a 15 s charge.
    assert topups_done == [0]


@pytest.mark.parametrize("before_billing", [5, 12, 44])
def test_under_modelled_timings_the_saved_card_batches_alternate_priority_for_a_charge(
    before_billing: int, database: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Modelled timings: every batch has work left on every pass, every unit takes its expected
    # time and the top-up's refusal step has one row. Each pass gets a fresh sweeper, as when
    # passes land on different replicas: payment priority comes from the pass's clock alone, so
    # no state needs to survive between passes. Other timings can use up the reserve.
    done: dict[str, list[int]] = {
        name: [] for name in ("reconcile", "expire", "period_end", "drift", "seats", "topup")
    }
    order: list[str] = []
    monotonic = Monotonic()

    def subscription_batch(name: str, seconds: float) -> Callable[..., int]:
        batch = _row_batch(monotonic, done[name], seconds)

        def job(_deps: object, *, now: datetime, should_stop: Callable[[], bool] | None) -> int:
            order.append(name)
            assert should_stop is not None
            return batch(now, should_stop)

        return job

    def charge_batch(name: str, *, rows: int) -> Callable[[datetime, BatchStops], int]:
        batch = _charge_batch(monotonic, done[name], CHARGE_TYPICAL, rows=rows)

        def job(now: datetime, stops: BatchStops) -> int:
            order.append(name)
            return batch(now, stops)

        return job

    def prepare(*_args: object, **_kwargs: object) -> int:
        monotonic.spend(before_billing)
        return 0

    monkeypatch.setattr(scheduled_notifications, "publish_due_announcements", prepare)
    monkeypatch.setattr(scheduled_notifications, "terms_change_notices_job", lambda *_a, **_k: 0)
    monkeypatch.setattr(scheduled_notifications, "terms_move_fixed_path_job", lambda *_a, **_k: 0)
    monkeypatch.setattr(
        scheduled_notifications, "expire_overdue_job", subscription_batch("expire", 8)
    )
    monkeypatch.setattr(
        scheduled_notifications, "period_end_job", subscription_batch("period_end", 8)
    )
    monkeypatch.setattr(scheduled_notifications, "drift_check_job", subscription_batch("drift", 15))

    for minute in (0, 1, 5, 6, 10, 15):
        sweeper = _timed(
            database,
            monotonic,
            budget=60,
            clock=Clock(datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=minute)),
            billing_reconcile=_row_batch(monotonic, done["reconcile"], 8),
            subscriptions=object(),
            billing_extra_seat_renewal=charge_batch("seats", rows=200),
            billing_auto_topup=charge_batch("topup", rows=1),
        )
        began = monotonic()
        body = trigger(make_client(sweeper)).json()
        assert monotonic() - began <= 60
        assert body["failed"] == []
        # The batch with priority runs. The top-up, last, may find the budget spent in the seat
        # batch's window and be skipped; it then claimed nothing on that pass.
        assert body["skipped"] in ([], ["billing.auto_topup"])
        if body["skipped"]:
            done["topup"].append(0)
        assert order[:4] == ["expire", "period_end", "drift", "seats"]
        order.clear()

    # Charges claimed per pass (not seat bookkeeping rows). Under these timings priority moves
    # every five minutes and the batch with priority starts a charge on each pass of its window.
    assert done["seats"] == [1, 1, 0, 0, 1, 0]
    assert done["topup"] == [0, 0, 1, 1, 0, 1]


def test_the_payment_turn_alternates_every_five_minutes_from_the_clock_alone() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)  # an even window: the seat batch's turn
    turns = [
        scheduled_notifications.seat_charges_have_the_turn(start + timedelta(seconds=s))
        for s in (0, 299, 300, 599, 600)
    ]
    assert PAYMENT_TURN_MINUTES == 5
    assert turns == [True, True, False, False, True]


def test_an_unbounded_pass_never_asks_a_batch_to_stop(
    database: sessionmaker[Session],
) -> None:
    monotonic = Monotonic()
    seen: list[tuple[str, bool]] = []

    def job(name: str) -> Callable[[datetime, Callable[[], bool]], int]:
        def run(_now: datetime, should_stop: Callable[[], bool]) -> int:
            monotonic.spend(10_000)
            seen.append((name, should_stop()))
            return 0

        return run

    def charge_job(name: str) -> Callable[[datetime, BatchStops], int]:
        def run(_now: datetime, stops: BatchStops) -> int:
            monotonic.spend(10_000)
            seen.append((name, stops.row() or stops.charge()))
            return 0

        return run

    _timed(
        database,
        monotonic,
        billing_reconcile=job("reconcile"),
        billing_extra_seat_renewal=charge_job("seats"),
        billing_auto_topup=charge_job("topup"),
    ).sweep_unbounded_for_tests()

    assert seen == [("reconcile", False), ("seats", False), ("topup", False)]


TYPICAL, HARD = 15.0, 75.0  # a saved-card charge with the default timeouts


def test_a_unit_starts_only_if_its_expected_time_fits_and_its_worst_case_ends_in_time() -> None:
    monotonic = Monotonic()
    budget = PassBudget(60, clock=monotonic, hard_seconds=210)
    charge = UnitCost(typical=TYPICAL, hard=HARD)
    long_read = UnitCost(typical=8, hard=180)

    monotonic.spend(30)
    assert budget.admits(charge) is True
    assert budget.admits(charge, reserve=15) is True  # 30 + 15 + 15 = 60
    assert budget.admits(charge, reserve=15.25) is False
    assert budget.admits(long_read) is True  # 30 + 180 = 210, the hard limit
    monotonic.spend(0.25)
    # Its expected 8 s still fit the budget, but its worst case would end past the hard limit.
    assert budget.admits(long_read) is False
    monotonic.spend(14.75)
    assert (budget.spent(), budget.admits(charge)) == (False, True)  # 45 + 15 = 60
    monotonic.spend(0.25)
    assert (budget.spent(), budget.admits(charge)) == (False, False)


def test_a_job_slice_caps_its_later_units_but_never_its_first() -> None:
    monotonic = Monotonic()
    budget = PassBudget(100, clock=monotonic)
    row = UnitCost(typical=1, hard=5)

    monotonic.spend(20)
    stop = budget.job(0.1).stop_before(row)  # a 10 s slice from 20 s
    monotonic.spend(30)  # e.g. a token mint before the first row
    assert stop() is False  # the first unit starts though the slice has passed
    monotonic.spend(1)
    assert stop() is True  # 31 s used of a 10 s slice

    slow = budget.job(0.1).stop_before(row)
    assert slow() is False
    monotonic.spend(9)
    assert slow() is False  # 9 s used of 10
    monotonic.spend(1)
    assert slow() is True

    late = budget.job(None).stop_before(row)  # no slice: only the budget bounds it
    monotonic.spend(100 - 61 - 1)  # 99 s in
    assert late() is False
    monotonic.spend(0.001)
    assert late() is True


def test_the_budget_setting_has_a_default_under_the_attempt_deadline() -> None:
    assert NotificationsSettings().sweep_pass_budget_seconds == 60
    with pytest.raises(ValueError, match="sweep_pass_budget_seconds"):
        NotificationsSettings(sweep_pass_budget_seconds=0)


# -- the loop and the trigger share one exclusive entry point -----------------


def test_the_loop_runs_its_pass_through_the_exclusive_entry_point() -> None:
    entered: list[str] = []

    class Fake:
        def sweep_exclusive(self) -> SweepPass | None:
            entered.append("exclusive")
            return SweepPass(results={}, skipped=[])

        def sweep_unbounded_for_tests(
            self,
        ) -> dict[str, int | None]:  # pragma: no cover - must not be used
            entered.append("unlocked")
            return {}

    async def scenario() -> None:
        stop = asyncio.Event()
        task = asyncio.create_task(run_sweeper(Fake(), poll_seconds=60, stop=stop))  # type: ignore[arg-type]
        await asyncio.sleep(0.05)
        stop.set()
        await asyncio.wait_for(task, timeout=1)

    asyncio.run(scenario())

    assert entered == ["exclusive"]


def test_a_loop_pass_and_an_http_trigger_cannot_overlap(database: sessionmaker[Session]) -> None:
    started, release = threading.Event(), threading.Event()
    other_runs = Counter(0)

    def slow(_now: datetime, _stop: Callable[[], bool]) -> int:
        started.set()
        assert release.wait(10)
        return 1

    sweeper = make_sweeper(database, billing_reconcile=slow, billing_auto_topup=other_runs)
    client = make_client(sweeper)

    async def scenario() -> dict[str, object]:
        stop = asyncio.Event()
        loop_task = asyncio.create_task(run_sweeper(sweeper, poll_seconds=60, stop=stop))
        try:
            assert await asyncio.to_thread(started.wait, 10)  # the loop's pass is mid-flight
            during = await asyncio.to_thread(trigger, client)
        finally:
            release.set()
        await asyncio.sleep(0.5)  # let the loop's pass finish
        stop.set()
        await asyncio.wait_for(loop_task, timeout=5)
        return {"during": during}

    outcome = asyncio.run(scenario())

    during = outcome["during"]
    assert during.json()["status"] == "skipped"  # type: ignore[attr-defined]
    assert other_runs.calls == 1  # one pass in total: the loop's


def test_an_http_trigger_makes_a_concurrent_loop_pass_skip_and_the_loop_survives(
    database: sessionmaker[Session],
) -> None:
    started, release = threading.Event(), threading.Event()
    other_runs = Counter(0)

    def slow(_now: datetime, _stop: Callable[[], bool]) -> int:
        started.set()
        assert release.wait(10)
        return 1

    held = make_sweeper(database, billing_reconcile=slow)
    loop_sweeper = make_sweeper(database, billing_auto_topup=other_runs)
    client = make_client(held)
    worker = threading.Thread(target=lambda: trigger(client))
    worker.start()
    try:
        assert started.wait(10)

        async def scenario() -> None:
            stop = asyncio.Event()
            task = asyncio.create_task(run_sweeper(loop_sweeper, poll_seconds=60, stop=stop))
            await asyncio.sleep(0.3)
            assert not task.done()  # a skipped pass is not an error
            stop.set()
            await asyncio.wait_for(task, timeout=5)

        asyncio.run(scenario())
        assert other_runs.calls == 0
    finally:
        release.set()
        worker.join(10)


def test_the_lock_is_released_when_the_pass_itself_raises(database: sessionmaker[Session]) -> None:
    clock = Clock(MORNING)
    topup = Counter(3)
    sweeper = make_sweeper(database, clock, billing_auto_topup=topup)
    real_now = clock.__call__
    failures = {"left": 1}

    def flaky_now() -> datetime:
        if failures["left"]:
            failures["left"] -= 1
            raise RuntimeError("the clock died")
        return real_now()

    sweeper.now = flaky_now

    with pytest.raises(RuntimeError, match="the clock died"):
        sweeper.sweep_exclusive()

    with database() as probe, probe.begin():
        free = probe.scalar(
            sa.text("SELECT pg_try_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": SWEEP_LOCK_KEY},
        )
    assert free is True  # not left held by the failed pass
    result = sweeper.sweep_exclusive()
    assert result is not None
    assert result.results["billing.auto_topup"] == 3
