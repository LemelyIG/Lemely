"""Facts the admin health and problem views read: job runs, HMAC failures, reconcile one."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy import select
from structlog.testing import capture_logs

from lemely.db import billing_observability_repo as observability
from lemely.db.announcement_repo import AnnouncementService
from lemely.db.billing_observability_repo import (
    FailureCap,
    JobRunRecorder,
    describe_job_error,
    prune_webhook_failures,
    record_webhook_failure,
)
from lemely.db.billing_repo import (
    BillingError,
    BillingService,
    PaymentBusyError,
    PaymentNotFoundError,
)
from lemely.db.class_repo import ClassService
from lemely.db.models.billing import Payment, PaymentStatus
from lemely.db.models.billing_ops import JobRun, PaymobWebhookFailure
from lemely.db.models.usage import UsageGrant
from lemely.db.notification_prefs_repo import NotificationPreferencesService
from lemely.db.notification_repo import NotificationService
from lemely.runtime.config import NotificationsSettings, Settings
from lemely.web import create_app, deps
from lemely.web.deps import get_settings
from lemely.web.deps_billing import get_billing_sessionmaker, get_paymob_client
from lemely.web.push import RecordingPushTransport
from lemely.web.ratelimit import SlidingWindowLimiter
from lemely.web.routers import paymob_webhooks
from lemely.web.scheduled_notifications import Sweeper, run_jobs
from tests.admin_billing_db import NOW, billing_database, emptied_after
from tests.paymob_fixtures import (
    PAYMOB_SETTINGS,
    FakePaymobClient,
    seed_pack,
    seed_payment,
    seed_user,
    sign_transaction,
    token_callback,
    token_obj,
    transaction_callback,
    transaction_obj,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from datetime import datetime

    from fastapi import FastAPI
    from sqlalchemy.orm import Session, sessionmaker

URL = "/api/webhooks/paymob/transaction"


@pytest.fixture(scope="module")
def billing_db() -> Iterator[sessionmaker[Session]]:
    with billing_database() as factory:
        yield factory


@pytest.fixture
def sm(billing_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(billing_db)


@pytest.fixture(autouse=True)
def fresh_caps(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each test starts with an empty failure cap and an unspent once-a-minute alert."""
    monkeypatch.setattr(observability, "_failure_cap", FailureCap())
    monkeypatch.setattr(
        paymob_webhooks,
        "_UNRECORDED_ALERT",
        SlidingWindowLimiter(limit=1, window_seconds=60.0, clock=lambda: 0.0),
    )


def _row(sm: sessionmaker[Session], name: str) -> JobRun:
    with sm() as session:
        row = session.get(JobRun, name)
        assert row is not None
        return row


# -- job runs ----------------------------------------------------------------------------


def test_start_then_finish_records_the_run(sm: sessionmaker[Session]) -> None:
    recorder = JobRunRecorder(sm)
    recorder.start("billing.reconcile_pending", NOW)
    started = _row(sm, "billing.reconcile_pending")
    assert started.last_started_at == NOW
    assert started.last_finished_at is None and started.last_outcome is None
    assert started.total_runs == 0

    recorder.record_finish(
        "billing.reconcile_pending", now=NOW + timedelta(seconds=2), count=3, error=None
    )
    row = _row(sm, "billing.reconcile_pending")
    assert row.last_started_at == NOW
    assert row.last_finished_at == NOW + timedelta(seconds=2)
    assert (row.last_outcome, row.last_result_count, row.last_error) == ("ok", 3, None)
    assert row.last_success_at == NOW + timedelta(seconds=2)
    assert (row.consecutive_failures, row.total_runs, row.total_failures) == (0, 1, 0)


def test_a_finish_without_a_start_row_still_inserts(sm: sessionmaker[Session]) -> None:
    JobRunRecorder(sm).record_finish("billing.x", now=NOW, count=None, error=BillingError("boom"))
    row = _row(sm, "billing.x")
    assert row.last_started_at == NOW
    assert (row.last_outcome, row.consecutive_failures, row.total_runs, row.total_failures) == (
        "failed",
        1,
        1,
        1,
    )
    assert row.last_success_at is None


def test_a_failing_job_counts_up_and_a_later_success_resets(sm: sessionmaker[Session]) -> None:
    recorder = JobRunRecorder(sm)
    name = "billing.reconcile_pending"
    recorder.start(name, NOW)
    recorder.record_finish(name, now=NOW + timedelta(seconds=1), count=2, error=None)
    for minute in (1, 2):
        at = NOW + timedelta(minutes=minute)
        recorder.start(name, at)
        recorder.record_finish(
            name, now=at + timedelta(seconds=1), count=None, error=BillingError("boom")
        )
    row = _row(sm, name)
    assert row.last_outcome == "failed"
    assert row.last_error == "BillingError: boom"
    assert row.last_result_count is None
    assert row.consecutive_failures == 2
    assert (row.total_runs, row.total_failures) == (3, 2)
    assert row.last_success_at == NOW + timedelta(seconds=1)  # a failure keeps the last success

    at = NOW + timedelta(minutes=3)
    recorder.start(name, at)
    recorder.record_finish(name, now=at + timedelta(seconds=1), count=5, error=None)
    row = _row(sm, name)
    assert (row.last_outcome, row.last_error, row.last_result_count) == ("ok", None, 5)
    assert row.consecutive_failures == 0
    assert (row.total_runs, row.total_failures) == (4, 2)
    assert row.last_success_at == at + timedelta(seconds=1)


def test_a_start_keeps_the_previous_outcome_until_the_run_ends(sm: sessionmaker[Session]) -> None:
    recorder = JobRunRecorder(sm)
    recorder.record_finish("j", now=NOW, count=None, error=BillingError("boom"))
    recorder.start("j", NOW + timedelta(minutes=1))
    row = _row(sm, "j")
    assert row.last_started_at == NOW + timedelta(minutes=1)
    assert (row.last_outcome, row.consecutive_failures) == ("failed", 1)


def test_the_error_text_is_cut_to_the_column_as_a_whole(sm: sessionmaker[Session]) -> None:
    """The column is 200 characters: type plus message is cut together, or the insert fails."""
    text = describe_job_error(BillingError("x" * 500))
    assert len(text) == 200
    assert text.startswith("BillingError: xxx")
    JobRunRecorder(sm).record_finish("j", now=NOW, count=None, error=BillingError("x" * 500))
    assert _row(sm, "j").last_error == text


@pytest.mark.parametrize(
    "exc",
    [
        ValueError("card tok_secret for ana@example.com"),
        RuntimeError("GET https://x.test/pay?key=secret failed"),
        KeyError("tok_secret"),
        OSError("host 10.0.0.5 refused"),
    ],
    ids=lambda e: type(e).__name__,
)
def test_only_allowlisted_types_keep_their_message(exc: Exception) -> None:
    """A message is kept only for the project's own error types; anything else is type only."""
    assert describe_job_error(exc) == type(exc).__name__


def test_the_projects_own_errors_keep_their_message() -> None:
    from lemely.runtime.errors import ExternalServiceError

    assert describe_job_error(BillingError("no billing settings row")) == (
        "BillingError: no billing settings row"
    )
    assert describe_job_error(ExternalServiceError("paymob down")) == (
        "ExternalServiceError: paymob down"
    )


def test_a_database_error_records_its_type_alone(sm: sessionmaker[Session]) -> None:
    """A driver or SQLAlchemy message can echo bound parameters, so only the type is kept."""
    leak = sa.exc.OperationalError(
        "INSERT INTO t VALUES (:token)",
        {"token": "tok_secret_value"},
        Exception("tok_secret_value"),
    )
    assert "tok_secret_value" in str(leak)
    assert describe_job_error(leak) == "OperationalError"
    assert describe_job_error(sa.exc.IntegrityError("s", {"p": "secret"}, Exception("secret"))) == (
        "IntegrityError"
    )


# -- run_jobs and the recorder -----------------------------------------------------------


class _SpyRecorder(JobRunRecorder):
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []

    def start(self, name: str, now: Any) -> None:
        self.calls.append(("start", name, now))

    def record_finish(
        self, name: str, *, now: Any, count: int | None, error: BaseException | None
    ) -> None:
        self.calls.append(("finish", name, now, count, type(error).__name__ if error else None))


class _BrokenRecorder(JobRunRecorder):
    def __init__(self) -> None:
        pass

    def start(self, name: str, now: Any) -> None:
        raise RuntimeError("db down")

    def record_finish(
        self, name: str, *, now: Any, count: int | None, error: BaseException | None
    ) -> None:
        raise RuntimeError("db down")


def test_run_jobs_reports_the_start_and_end_of_each_job() -> None:
    spy = _SpyRecorder()

    def boom() -> int:
        raise RuntimeError("boom")

    results = run_jobs([("a", lambda: 2), ("b", boom)], recorder=spy, now=lambda: NOW)

    assert results == {"a": 2, "b": None}
    assert spy.calls == [
        ("start", "a", NOW),
        ("finish", "a", NOW, 2, None),
        ("start", "b", NOW),
        ("finish", "b", NOW, None, "RuntimeError"),
    ]


def test_run_jobs_without_a_recorder_behaves_as_before() -> None:
    assert run_jobs([("a", lambda: 1)]) == {"a": 1}


def test_a_recorder_that_raises_changes_no_result_and_stops_no_job() -> None:
    ran: list[str] = []

    def job(name: str) -> int:
        ran.append(name)
        return 1

    def boom() -> int:
        ran.append("boom")
        raise RuntimeError("job failed")

    with capture_logs() as logs:
        results = run_jobs(
            [("a", lambda: job("a")), ("boom", boom), ("b", lambda: job("b"))],
            recorder=_BrokenRecorder(),
        )

    assert ran == ["a", "boom", "b"]
    assert results == {"a": 1, "boom": None, "b": 1}
    failed = [e for e in logs if e["event"] == "job_run_record_failed"]
    assert len(failed) == 6  # start and finish of each of the three jobs
    assert {e["error_type"] for e in failed} == {"RuntimeError"}
    assert "db down" not in str(logs)  # the message is never logged


def test_a_raising_job_is_recorded_failed_and_a_later_success_resets_it(
    sm: sessionmaker[Session],
) -> None:
    recorder = JobRunRecorder(sm)
    state = {"fail": True}

    def flaky() -> int:
        if state["fail"]:
            raise BillingError("boom")
        return 4

    for _ in range(2):
        run_jobs([("flaky", flaky)], recorder=recorder, now=lambda: NOW)
    row = _row(sm, "flaky")
    assert (row.last_outcome, row.consecutive_failures, row.last_error) == (
        "failed",
        2,
        "BillingError: boom",
    )
    state["fail"] = False
    run_jobs([("flaky", flaky)], recorder=recorder, now=lambda: NOW + timedelta(minutes=1))
    row = _row(sm, "flaky")
    assert (row.last_outcome, row.consecutive_failures, row.last_result_count) == ("ok", 0, 4)
    assert (row.total_runs, row.total_failures) == (3, 2)


def _sweeper(sm: sessionmaker[Session], *, recorder: JobRunRecorder | None) -> Sweeper:
    return Sweeper(
        sessionmaker=sm,
        announcements=AnnouncementService(sm, ClassService(sm)),
        notifications=NotificationService(sm, NotificationPreferencesService(sm)),
        transport=RecordingPushTransport(),
        settings=NotificationsSettings(),
        now=lambda: NOW,
        billing_reconcile=lambda moment: 2,
        job_recorder=recorder,
    )


def test_a_sweep_writes_one_job_run_per_job(sm: sessionmaker[Session]) -> None:
    results = _sweeper(sm, recorder=JobRunRecorder(sm)).sweep_once()
    with sm() as session:
        rows = {r.name: r for r in session.scalars(select(JobRun))}
    assert set(rows) == set(results)
    assert "billing.reconcile_pending" in rows
    assert rows["billing.reconcile_pending"].last_result_count == 2
    assert all(r.last_outcome == "ok" and r.total_runs == 1 for r in rows.values())


def test_a_sweep_without_a_recorder_writes_nothing(sm: sessionmaker[Session]) -> None:
    _sweeper(sm, recorder=None).sweep_once()
    with sm() as session:
        assert session.scalars(select(JobRun)).all() == []


def test_get_sweeper_wires_the_job_recorder() -> None:
    deps.get_sweeper.cache_clear()
    try:
        assert isinstance(deps.get_sweeper().job_recorder, JobRunRecorder)
    finally:
        deps.get_sweeper.cache_clear()


# -- HMAC failures -----------------------------------------------------------------------


def _failures(sm: sessionmaker[Session]) -> list[PaymobWebhookFailure]:
    with sm() as session:
        return list(session.scalars(select(PaymobWebhookFailure)))


def test_a_webhook_failure_row_holds_only_kind_reason_address_and_time(
    sm: sessionmaker[Session],
) -> None:
    assert record_webhook_failure(
        sm, kind="transaction", reason="hmac_mismatch", remote_addr="1.2.3.4", now=NOW
    )
    (row,) = _failures(sm)
    assert (row.kind, row.reason, row.remote_addr, row.received_at) == (
        "transaction",
        "hmac_mismatch",
        "1.2.3.4",
        NOW,
    )
    # No body, HMAC or object id has a column to land in.
    assert {c.name for c in PaymobWebhookFailure.__table__.columns} == {
        "id",
        "kind",
        "reason",
        "remote_addr",
        "received_at",
    }


def test_a_long_remote_address_is_cut_to_the_column(sm: sessionmaker[Session]) -> None:
    assert record_webhook_failure(
        sm, kind="token", reason="hmac_missing", remote_addr="9" * 300, now=NOW
    )
    (row,) = _failures(sm)
    assert row.remote_addr == "9" * 64


def test_the_failure_cap_is_sixty_a_rolling_minute(sm: sessionmaker[Session]) -> None:
    results = [
        record_webhook_failure(
            sm, kind="transaction", reason="hmac_mismatch", remote_addr=None, now=NOW
        )
        for _ in range(61)
    ]
    assert results == [True] * 60 + [False]
    assert len(_failures(sm)) == 60
    # A minute later the window has moved on and recording resumes.
    assert record_webhook_failure(
        sm,
        kind="transaction",
        reason="hmac_mismatch",
        remote_addr=None,
        now=NOW + timedelta(seconds=61),
    )
    assert len(_failures(sm)) == 61


@pytest.fixture
def webhook_app(sm: sessionmaker[Session]) -> Iterator[FastAPI]:
    settings = Settings().model_copy(update={"paymob": PAYMOB_SETTINGS})
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_billing_sessionmaker] = lambda: sm
    app.dependency_overrides[get_paymob_client] = lambda: FakePaymobClient()
    yield app
    app.dependency_overrides.clear()


def _post(client: TestClient, body: dict[str, Any], hmac: str | None, **headers: str) -> Any:
    params = {"hmac": hmac} if hmac is not None else {}
    return client.post(URL, params=params, json=body, headers=headers)


def test_a_bad_transaction_hmac_is_recorded_after_the_401(
    webhook_app: FastAPI, sm: sessionmaker[Session]
) -> None:
    obj = transaction_obj()
    client = TestClient(webhook_app)
    bad = sign_transaction(obj, secret="attacker-guess")

    assert (
        _post(client, transaction_callback(obj), bad, **{"x-forwarded-for": "5.6.7.8"}).status_code
        == 401
    )
    assert _post(client, transaction_callback(obj), None).status_code == 401

    rows = {r.reason: r for r in _failures(sm)}
    assert set(rows) == {"hmac_mismatch", "hmac_missing"}
    assert rows["hmac_mismatch"].kind == "transaction"
    assert rows["hmac_mismatch"].remote_addr == "5.6.7.8"
    assert rows["hmac_missing"].kind == "transaction"


def test_a_bad_token_hmac_is_recorded_as_a_token_failure(
    webhook_app: FastAPI, sm: sessionmaker[Session]
) -> None:
    obj = token_obj()
    assert _post(TestClient(webhook_app), token_callback(obj), "0" * 128).status_code == 401
    (row,) = _failures(sm)
    assert (row.kind, row.reason) == ("token", "hmac_mismatch")


def test_nothing_of_the_body_or_the_hmac_is_stored(
    webhook_app: FastAPI, sm: sessionmaker[Session]
) -> None:
    obj = transaction_obj(merchant_order_id="distinctive-reference-9981")
    received = "ab" * 64
    assert _post(TestClient(webhook_app), transaction_callback(obj), received).status_code == 401
    with sm() as session:
        dumped = session.execute(
            sa.text("SELECT row_to_json(f)::text FROM paymob_webhook_failures f")
        ).scalar_one()
    assert received not in dumped
    assert "distinctive-reference-9981" not in dumped
    assert str(obj["id"]) not in dumped


def test_sixty_one_failures_in_a_minute_leave_sixty_rows_and_the_same_401(
    webhook_app: FastAPI, sm: sessionmaker[Session]
) -> None:
    obj = transaction_obj()
    client = TestClient(webhook_app)
    with capture_logs() as logs:
        statuses = [
            _post(client, transaction_callback(obj), "0" * 128).status_code for _ in range(61)
        ]
    assert statuses == [401] * 61
    assert len(_failures(sm)) == 60
    # The dropped row is alerted once, not once per dropped request.
    for _ in range(3):
        assert _post(client, transaction_callback(obj), "0" * 128).status_code == 401
    unrecorded = [e for e in logs if e["event"] == "paymob_hmac_failure_unrecorded"]
    assert len(unrecorded) == 1 and unrecorded[0]["alert"] is True


def test_a_failure_that_cannot_be_recorded_never_changes_the_401(
    webhook_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*args: object, **kwargs: object) -> bool:
        raise sa.exc.OperationalError("INSERT ...", {"p": "tok_secret"}, Exception("tok_secret"))

    monkeypatch.setattr(paymob_webhooks, "record_webhook_failure", broken)
    obj = transaction_obj()
    with capture_logs() as logs:
        response = _post(TestClient(webhook_app), transaction_callback(obj), "0" * 128)
    assert response.status_code == 401
    assert response.json() == {"detail": "HMAC verification failed"}
    (entry,) = [e for e in logs if e["event"] == "paymob_hmac_failure_record_failed"]
    assert entry["error_type"] == "OperationalError"
    assert "tok_secret" not in str(logs)


def test_a_verified_callback_and_an_ignored_type_record_no_failure(
    webhook_app: FastAPI, sm: sessionmaker[Session]
) -> None:
    client = TestClient(webhook_app)
    obj = transaction_obj()
    assert _post(client, transaction_callback(obj), sign_transaction(obj)).status_code == 200
    assert _post(client, {"type": "DELIVERY_STATUS", "obj": {}}, None).status_code == 200
    assert _failures(sm) == []


def _failure_at(sm: sessionmaker[Session], at: datetime) -> None:
    with sm.begin() as session:
        session.add(
            PaymobWebhookFailure(kind="transaction", reason="hmac_mismatch", received_at=at)
        )


def test_prune_deletes_failures_older_than_ninety_days_and_keeps_the_rest(
    sm: sessionmaker[Session],
) -> None:
    _failure_at(sm, NOW - timedelta(days=91))
    _failure_at(sm, NOW - timedelta(days=90, seconds=1))
    _failure_at(sm, NOW - timedelta(days=89))
    _failure_at(sm, NOW)
    assert prune_webhook_failures(sm, now=NOW) == 2
    assert sorted(r.received_at for r in _failures(sm)) == [NOW - timedelta(days=89), NOW]


def test_prune_is_bounded_per_pass_and_finishes_over_the_next(sm: sessionmaker[Session]) -> None:
    for day in range(100, 105):
        _failure_at(sm, NOW - timedelta(days=day))
    assert prune_webhook_failures(sm, now=NOW, batch=3) == 3
    assert len(_failures(sm)) == 2
    assert prune_webhook_failures(sm, now=NOW, batch=3) == 2
    assert _failures(sm) == []


def test_the_sweeper_prunes_old_failures_as_a_recorded_job(sm: sessionmaker[Session]) -> None:
    _failure_at(sm, NOW - timedelta(days=120))
    _failure_at(sm, NOW - timedelta(days=1))
    results = _sweeper(sm, recorder=JobRunRecorder(sm)).sweep_once()
    assert results["billing.prune_webhook_failures"] == 1
    assert len(_failures(sm)) == 1
    assert _row(sm, "billing.prune_webhook_failures").last_result_count == 1


# -- reconcile one payment ---------------------------------------------------------------


def _open_payment(
    sm: sessionmaker[Session],
    *,
    age: timedelta = timedelta(minutes=20),
    status: PaymentStatus = PaymentStatus.created,
    paymob_order_id: int | None = None,
) -> uuid.UUID:
    payer = seed_user(sm)
    return seed_payment(
        sm,
        payer=payer,
        beneficiary=payer,
        pack_id=seed_pack(sm),
        created_at=NOW - age,
        status=status,
        paymob_order_id=paymob_order_id,
    )


def _reconcile_now(
    sm: sessionmaker[Session], client: FakePaymobClient, pid: uuid.UUID
) -> PaymentStatus:
    with sm.begin() as session:
        return BillingService(
            session, client, PAYMOB_SETTINGS, now=lambda: NOW
        ).reconcile_payment_now(pid, now=NOW)


def _payment(sm: sessionmaker[Session], pid: uuid.UUID) -> Payment:
    with sm() as session:
        payment = session.get(Payment, pid)
        assert payment is not None
        return payment


def _grants(sm: sessionmaker[Session], pid: uuid.UUID) -> int:
    with sm() as session:
        return len(session.scalars(select(UsageGrant).where(UsageGrant.payment_id == pid)).all())


def test_reconcile_payment_now_raises_for_an_unknown_payment(sm: sessionmaker[Session]) -> None:
    with pytest.raises(PaymentNotFoundError):
        _reconcile_now(sm, FakePaymobClient(), uuid.uuid4())


def test_reconcile_payment_now_marks_a_paid_inquiry_paid_through_the_paid_handler_once(
    sm: sessionmaker[Session],
) -> None:
    pid = _open_payment(sm)
    client = FakePaymobClient()
    client.inquiry_response = transaction_obj(merchant_order_id=str(pid))

    assert _reconcile_now(sm, client, pid) is PaymentStatus.paid
    assert _grants(sm, pid) == 1
    payment = _payment(sm, pid)
    assert payment.paid_at == NOW
    assert payment.callback_received_at is None  # an inquiry is not a callback
    # A second trigger neither inquires nor grants again.
    assert _reconcile_now(sm, client, pid) is PaymentStatus.paid
    assert client.inquiries == [str(pid)]
    assert _grants(sm, pid) == 1


def test_reconcile_payment_now_ignores_the_backoff_schedule(sm: sessionmaker[Session]) -> None:
    """A payment not due for hours is inquired now: the admin asked for it."""
    pid = _open_payment(sm, age=timedelta(minutes=1))
    client = FakePaymobClient()
    client.inquiry_response = transaction_obj(merchant_order_id=str(pid))
    assert _payment(sm, pid).next_reconcile_at is not None
    assert _reconcile_now(sm, client, pid) is PaymentStatus.paid


def test_reconcile_payment_now_leaves_a_settled_payment_alone(sm: sessionmaker[Session]) -> None:
    pid = _open_payment(sm, status=PaymentStatus.paid)
    client = FakePaymobClient()
    assert _reconcile_now(sm, client, pid) is PaymentStatus.paid
    assert client.inquiries == []


def test_reconcile_payment_now_never_settles_a_foreign_integration_answer(
    sm: sessionmaker[Session],
) -> None:
    pid = _open_payment(sm)
    client = FakePaymobClient()
    client.inquiry_response = {
        **transaction_obj(merchant_order_id=str(pid)),
        "integration_id": 999999,
    }
    with capture_logs() as logs:
        status = _reconcile_now(sm, client, pid)
    assert status is PaymentStatus.created
    assert _grants(sm, pid) == 0
    assert _payment(sm, pid).next_reconcile_at is None  # parked for a person
    assert any(e["event"] == "paymob_unexpected_integration" and e["alert"] for e in logs)


def test_reconcile_payment_now_gives_up_on_a_day_old_payment_with_no_transaction(
    sm: sessionmaker[Session],
) -> None:
    pid = _open_payment(sm, age=timedelta(hours=25))
    client = FakePaymobClient()  # inquiry_response None: Paymob has no transaction
    assert _reconcile_now(sm, client, pid) is PaymentStatus.failed
    assert _payment(sm, pid).next_reconcile_at is None


def test_reconcile_payment_now_counts_the_give_up_from_the_send_of_a_queued_charge(
    sm: sessionmaker[Session],
) -> None:
    """``coalesce(sent_at, created_at)``: a row queued long ago but sent just now is young."""
    pid = _open_payment(sm, age=timedelta(hours=30))
    with sm.begin() as session:
        session.execute(
            sa.update(Payment).where(Payment.id == pid).values(sent_at=NOW - timedelta(minutes=5))
        )
    assert _reconcile_now(sm, FakePaymobClient(), pid) is PaymentStatus.created


# -- reconcile_payment_now: a stale copy, and a busy row ------------------------------------

ORDER = 265715202


def _stale_scenario(
    sm: sessionmaker[Session], *, age: timedelta
) -> tuple[PaymentStatus, list[str]]:
    """The caller read the payment, then a genuine callback paid it, then it reconciles."""
    pid = _open_payment(sm, age=age, status=PaymentStatus.pending, paymob_order_id=ORDER)
    obj = transaction_obj(merchant_order_id=str(pid), order_id=ORDER)
    client = FakePaymobClient()
    client.inquiry_response = obj
    with sm.begin() as admin:
        before = admin.get(Payment, pid)  # e.g. an admin route reading it for its audit row
        assert before is not None and before.status is PaymentStatus.pending
        with sm.begin() as callback:
            BillingService(
                callback, client, PAYMOB_SETTINGS, now=lambda: NOW
            ).apply_transaction_callback(obj)
        returned = BillingService(
            admin, client, PAYMOB_SETTINGS, now=lambda: NOW
        ).reconcile_payment_now(pid, now=NOW)
        assert returned is PaymentStatus.paid
    assert _grants(sm, pid) == 1
    return _payment(sm, pid).status, client.inquiries


@pytest.mark.parametrize(
    "age", [timedelta(hours=25), timedelta(hours=2)], ids=["over-24h", "young"]
)
def test_a_payment_paid_after_the_caller_read_it_is_not_overwritten(
    sm: sessionmaker[Session], age: timedelta
) -> None:
    """Without ``populate_existing`` the locked read keeps the caller's stale ``pending``, and the
    24-hour give-up writes ``failed`` over a payment a callback just paid."""
    status, inquiries = _stale_scenario(sm, age=age)
    assert status is PaymentStatus.paid
    assert inquiries == []


def test_a_payment_locked_elsewhere_raises_busy_without_an_inquiry(
    sm: sessionmaker[Session],
) -> None:
    pid = _open_payment(sm)
    client = FakePaymobClient()
    client.inquiry_response = transaction_obj(merchant_order_id=str(pid))
    with sm.begin() as holder:
        holder.execute(sa.select(Payment).where(Payment.id == pid).with_for_update())
        with sm() as admin, pytest.raises(PaymentBusyError):
            BillingService(admin, client, PAYMOB_SETTINGS, now=lambda: NOW).reconcile_payment_now(
                pid, now=NOW
            )
    assert client.inquiries == []
    assert _payment(sm, pid).status is PaymentStatus.created


# -- the failure row is written after the response -----------------------------------------


def test_the_failure_row_is_a_background_task_run_after_the_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    from fastapi import Request

    seen: list[str] = []
    monkeypatch.setattr(
        paymob_webhooks, "record_webhook_failure", lambda sm, **kw: seen.append(kw["kind"]) or True
    )
    settings = Settings().model_copy(update={"paymob": PAYMOB_SETTINGS})
    obj = transaction_obj()
    request = Request(
        {"type": "http", "headers": [(b"x-forwarded-for", b"5.6.7.8")], "client": ("9.9.9.9", 1)}
    )
    response = paymob_webhooks.paymob_transaction_callback(
        request,
        "s3cret",
        transaction_callback(obj),
        settings,
        None,  # type: ignore[arg-type]  # never reached before the response
        FakePaymobClient(),
        hmac="0" * 128,
    )
    assert response.status_code == 401  # type: ignore[union-attr]
    assert response.body == b'{"detail":"HMAC verification failed"}'  # type: ignore[union-attr]
    assert seen == []  # nothing is written while the response is being decided
    assert response.background is not None  # type: ignore[union-attr]
    asyncio.run(response.background())  # type: ignore[union-attr]
    assert seen == ["transaction"]
