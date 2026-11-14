"""Subscription webhooks: dedupe, linking and the successful renewal (spec §5.2, §6).

Real Postgres (a throwaway ``create_all`` database). The money rules are the point: a renewal is
granted exactly once whatever is replayed, raced or lost; an amount Lemely did not set at Paymob
grants nothing; and nothing the HMAC does not cover (the body's other fields, the request id) is
believed or used as a key (R26, DV-11, DV-12, DV-14).
"""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest
import sqlalchemy as sa
from structlog.testing import capture_logs

from lemely.core.usage_types import GrantScope, Payer
from lemely.db import subscription_repo
from lemely.db.billing_repo import paid_handler_for
from lemely.db.models.billing import (
    Payment,
    PaymentPurpose,
    PaymentStatus,
    PaymobEvent,
    PaymobEventKind,
    PlanAudience,
    Subscription,
    SubscriptionPeriod,
)
from lemely.db.models.enums import Role, SubscriptionStatus
from lemely.db.models.team import TeacherMember, TeacherMemberStatus
from lemely.db.models.tutoring import EmailOutbox
from lemely.db.models.usage import UsageDebt, UsageGrantBalance
from lemely.db.subscription_repo import (
    TRIGGER_CANCELED,
    TRIGGER_CREATED,
    TRIGGER_FAILED,
    TRIGGER_OVERDUE,
    TRIGGER_RESUMED,
    TRIGGER_SUCCESS,
    TRIGGER_SUSPENDED,
    MalformedWebhook,
    SubscriptionService,
    handle_subscription_first,
    handle_subscription_renewal,
    parse_subscription_webhook,
)
from lemely.db.usage_ledger_repo import UsageLedger
from lemely.io.paymob.client import PaymobError
from tests.paymob_fixtures import MOTO_INTEGRATION_ID
from tests.subscription_fixtures import (
    T0,
    FakePaymobClient,
    charge,
    grants_of,
    paymob_settings,
    remote_subscription,
    seed_debt,
    seed_first_payment,
    seed_seat,
    seed_subscription,
    seed_tier,
    seed_user,
    subscription_webhook,
    throwaway_database,
)
from tests.team_db import emptied_after

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker

PID = 4321
END = T0 + timedelta(days=30)
EARLY = END - timedelta(hours=2)  # Paymob charges on the billing date, up to a day early
NOW = END + timedelta(minutes=5)
FIRST_TXN = 777  # ``remote_subscription``'s default ``initial_transaction``
SUCCESS_BODY = subscription_webhook(TRIGGER_SUCCESS, PID)


@pytest.fixture(scope="module")
def _database() -> Iterator[sessionmaker[Session]]:
    with throwaway_database() as factory:
        yield factory


@pytest.fixture
def pg_sessionmaker(_database: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(_database)
    with _database.begin() as session:
        session.execute(sa.text("TRUNCATE paymob_events CASCADE"))


# -- seeding and reading ----------------------------------------------------------------


def _linked(
    sm: sessionmaker[Session],
    *,
    tier_id: uuid.UUID | None = None,
    **kwargs: Any,
) -> tuple[uuid.UUID, uuid.UUID]:
    """``(student, subscription)``: an active plan linked to Paymob, charging 100.00 a period."""
    student = seed_user(sm, Role.student)
    options: dict[str, Any] = {
        "payer_id": student,
        "paymob_subscription_id": PID,
        "paymob_amount_minor": 10_000,
        "activated_at": T0,
    } | kwargs
    sid = seed_subscription(
        sm, user_id=student, tier_id=tier_id or seed_tier(sm, allowance_units=1_000), **options
    )
    return student, sid


def _client(
    amount: int = 10_000,
    txn: int = 888,
    charged: Any = EARLY,
    **charge_kwargs: Any,
) -> FakePaymobClient:
    client = FakePaymobClient()
    client.subscriptions[PID] = remote_subscription(PID, amount_cents=amount)
    client.last_transactions[PID] = charge(txn, amount, created_at=charged, **charge_kwargs)
    return client


def _deliver(
    sm: sessionmaker[Session],
    client: FakePaymobClient,
    body: dict[str, Any] | None = None,
    *,
    now: Any = NOW,
) -> None:
    with sm.begin() as session:
        SubscriptionService(session, client, paymob_settings()).apply_renewal_webhook(
            SUCCESS_BODY if body is None else body, now=now
        )


def _periods(sm: sessionmaker[Session], sid: uuid.UUID) -> list[SubscriptionPeriod]:
    with sm() as session:
        return list(
            session.scalars(
                sa.select(SubscriptionPeriod)
                .where(SubscriptionPeriod.subscription_id == sid)
                .order_by(SubscriptionPeriod.period_start)
            )
        )


def _renewals(sm: sessionmaker[Session], sid: uuid.UUID) -> list[Payment]:
    with sm() as session:
        return list(
            session.scalars(
                sa.select(Payment)
                .where(
                    Payment.subscription_id == sid,
                    Payment.purpose == PaymentPurpose.subscription_renewal,
                )
                .order_by(Payment.created_at)
            )
        )


def _subscription(sm: sessionmaker[Session], sid: uuid.UUID) -> Subscription:
    with sm() as session:
        row = session.get(Subscription, sid)
        assert row is not None
        return row


def _events(sm: sessionmaker[Session]) -> list[PaymobEvent]:
    with sm() as session:
        return list(session.scalars(sa.select(PaymobEvent).order_by(PaymobEvent.created_at)))


def _notices(sm: sessionmaker[Session], recipient: uuid.UUID) -> list[str]:
    with sm() as session:
        rows = session.scalars(
            sa.select(EmailOutbox).where(EmailOutbox.recipient_user_id == recipient)
        ).all()
        return sorted(row.context["notice"] for row in rows)


def _notice_instants(sm: sessionmaker[Session], recipient: uuid.UUID) -> list[datetime]:
    """The ``effective_at`` each queued notice carries (stored as an ISO string)."""
    with sm() as session:
        rows = session.scalars(
            sa.select(EmailOutbox).where(EmailOutbox.recipient_user_id == recipient)
        ).all()
        return [datetime.fromisoformat(str(row.context["effective_at"])) for row in rows]


def _alerts(logs: list[dict[str, Any]]) -> list[str]:
    return [str(entry["event"]) for entry in logs if entry.get("alert") is True]


def _service(session: Session, client: FakePaymobClient | None = None) -> SubscriptionService:
    return SubscriptionService(session, client or _client(), paymob_settings())


# -- trigger names (the wire strings) ---------------------------------------------------


def test_trigger_constants_are_the_paymob_wire_strings() -> None:
    assert (
        TRIGGER_CREATED,
        TRIGGER_SUCCESS,
        TRIGGER_FAILED,
        TRIGGER_OVERDUE,
        TRIGGER_CANCELED,
        TRIGGER_SUSPENDED,
        TRIGGER_RESUMED,
    ) == (
        "Subscription Created",
        "Successful Transaction",
        "Failed Transaction",
        "Failed Overdue Transaction",
        "canceled",
        "suspended",
        "resumed",
    )


# -- parsing ----------------------------------------------------------------------------


def test_parse_returns_the_signed_trigger_and_id_only() -> None:
    body = subscription_webhook("canceled", 7, paymob_request_id="r-1")
    assert parse_subscription_webhook(body) == ("canceled", 7)


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"trigger_type": "x"},
        {"trigger_type": "x", "subscription_data": {}},
        {"trigger_type": "x", "subscription_data": {"id": "abc"}},
        {"trigger_type": "x", "subscription_data": {"id": "123"}},
        {"trigger_type": "x", "subscription_data": {"id": 12.0}},
        {"trigger_type": "x", "subscription_data": {"id": True}},
        {"trigger_type": "x", "subscription_data": {"id": 0}},
        {"trigger_type": "x", "subscription_data": {"id": -3}},
        {"trigger_type": "x", "subscription_data": [1]},
        {"trigger_type": "", "subscription_data": {"id": 1}},
        {"trigger_type": 5, "subscription_data": {"id": 1}},
    ],
)
def test_parse_rejects_malformed_bodies(body: dict[str, Any]) -> None:
    with pytest.raises(MalformedWebhook):
        parse_subscription_webhook(body)


# -- the successful renewal -------------------------------------------------------------


def test_successful_renewal_adds_payment_period_grant_and_notice(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student, sid = _linked(pg_sessionmaker)
    client = _client()
    _deliver(pg_sessionmaker, client)

    [renewal] = _renewals(pg_sessionmaker, sid)
    assert (renewal.status, renewal.amount_minor, renewal.paymob_txn_id) == (
        PaymentStatus.paid,
        10_000,
        888,
    )
    assert renewal.special_reference == "subscription-renewal:888"
    assert renewal.paid_at == EARLY
    assert renewal.payer_user_id == student
    assert renewal.paymob_order_id == 888 + 1_000_000
    assert renewal.seat_quantity is None  # the CHECK forbids 0
    [period] = _periods(pg_sessionmaker, sid)
    assert (period.period_start, period.period_end) == (END, END + timedelta(days=30))
    assert period.payment_id == renewal.id
    sub = _subscription(pg_sessionmaker, sid)
    assert sub.status is SubscriptionStatus.active
    assert (sub.current_period_start, sub.current_period_end) == (END, END + timedelta(days=30))
    assert sub.paymob_amount_minor == 10_000
    assert sub.grace_until is None
    assert _notices(pg_sessionmaker, student) == ["renewed"]
    # The notice names the stored period end, never the clock of the delivery.
    assert _notice_instants(pg_sessionmaker, student) == [END + timedelta(days=30)]
    [grant] = grants_of(pg_sessionmaker, student)
    assert grant.subscription_period_id == period.id
    assert grant.payment_id == renewal.id
    assert (grant.units, grant.effective_at, grant.expires_at) == (
        1_000,
        END,
        END + timedelta(days=30),
    )
    assert client.names() == ["get_subscription", "last_transaction"]  # reads only, no write


def test_an_early_charge_grants_a_period_that_is_not_usable_until_the_old_one_ends(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student, sid = _linked(pg_sessionmaker)
    _deliver(pg_sessionmaker, _client(charged=EARLY), now=EARLY + timedelta(minutes=1))
    own_allowance = Payer(student, GrantScope.ALLOWANCE)
    with pg_sessionmaker() as session:
        ledger = UsageLedger(session)
        assert ledger.available([own_allowance], now=EARLY + timedelta(minutes=1)) == 0
        assert ledger.available([own_allowance], now=END) == 1_000
        assert ledger.available([own_allowance], now=END + timedelta(days=30)) == 0
    assert [p.period_start for p in _periods(pg_sessionmaker, sid)] == [END]


def test_a_late_renewal_after_grace_starts_at_the_charge(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    _, sid = _linked(
        pg_sessionmaker,
        status=SubscriptionStatus.past_due,
        grace_until=END + timedelta(days=3),
    )
    charged = END + timedelta(days=2)
    _deliver(pg_sessionmaker, _client(charged=charged), now=charged + timedelta(minutes=1))
    sub = _subscription(pg_sessionmaker, sid)
    assert (sub.status, sub.grace_until) == (SubscriptionStatus.active, None)
    assert sub.current_period_start == charged
    assert sub.current_period_end == charged + timedelta(days=30)


def test_the_new_period_repays_the_owners_debt_first(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student, _ = _linked(pg_sessionmaker)
    seed_debt(pg_sessionmaker, student, 300)
    _deliver(pg_sessionmaker, _client())
    [grant] = grants_of(pg_sessionmaker, student)
    with pg_sessionmaker() as session:
        remaining = session.scalars(
            sa.select(UsageGrantBalance.remaining).where(UsageGrantBalance.grant_id == grant.id)
        ).one()
        outstanding = session.scalars(
            sa.select(UsageDebt.outstanding).where(UsageDebt.owner_user_id == student)
        ).one()
    assert (remaining, outstanding) == (700, 0)


def test_a_renewal_for_a_tier_with_no_allowance_still_extends_the_period(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student, sid = _linked(pg_sessionmaker, tier_id=seed_tier(pg_sessionmaker, allowance_units=0))
    _deliver(pg_sessionmaker, _client())
    assert len(_periods(pg_sessionmaker, sid)) == 1
    assert grants_of(pg_sessionmaker, student) == []


def test_the_charge_order_id_is_kept_whether_it_is_an_object_or_a_bare_int(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    _, sid = _linked(pg_sessionmaker)
    _deliver(pg_sessionmaker, _client(txn=888, order=555))  # the docs' sample carries a bare int
    [renewal] = _renewals(pg_sessionmaker, sid)
    assert renewal.paymob_order_id == 555


def test_an_order_id_another_payment_holds_is_not_copied(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """``payments.paymob_order_id`` is unique: a clash must not turn a paid renewal into a 500."""
    _, sid = _linked(pg_sessionmaker)
    seed_first_payment(
        pg_sessionmaker, subscription_id=sid, paymob_txn_id=FIRST_TXN, paymob_order_id=555
    )
    _deliver(pg_sessionmaker, _client(txn=888, order=555))
    [renewal] = _renewals(pg_sessionmaker, sid)
    assert renewal.paymob_order_id is None
    assert len(_periods(pg_sessionmaker, sid)) == 1


def test_a_stored_charge_never_keeps_a_card_token(pg_sessionmaker: sessionmaker[Session]) -> None:
    _, sid = _linked(pg_sessionmaker)
    client = _client(source_data={"type": "card", "pan": "2346", "token": "raw-card-token"})
    client.subscriptions[PID]["card_token"] = "raw-card-token"
    _deliver(pg_sessionmaker, client)
    [renewal] = _renewals(pg_sessionmaker, sid)
    assert "raw-card-token" not in str(renewal.last_callback)
    assert all("raw-card-token" not in str(event.payload) for event in _events(pg_sessionmaker))


# -- replays: granted exactly once --------------------------------------------------------


def test_a_duplicate_delivery_is_a_no_op(pg_sessionmaker: sessionmaker[Session]) -> None:
    student, sid = _linked(pg_sessionmaker)
    client = _client()
    _deliver(pg_sessionmaker, client)
    _deliver(pg_sessionmaker, client)
    assert len(_events(pg_sessionmaker)) == 1
    assert len(_periods(pg_sessionmaker, sid)) == 1
    assert len(_renewals(pg_sessionmaker, sid)) == 1
    assert len(grants_of(pg_sessionmaker, student)) == 1
    assert _notices(pg_sessionmaker, student) == ["renewed"]


def test_one_signed_body_with_other_unsigned_fields_is_one_event_one_period(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """R26: the HMAC covers the trigger and the id only, so nothing else may mint a new key."""
    student, sid = _linked(pg_sessionmaker)
    client = _client()
    for index in range(4):
        body = subscription_webhook(TRIGGER_SUCCESS, PID, paymob_request_id=f"req-{index}")
        body["subscription_data"] = {"id": PID, "amount_cents": 1 + index, "state": f"s{index}"}
        body["amount_cents"] = 999_999
        _deliver(pg_sessionmaker, client, body)
    assert len(_events(pg_sessionmaker)) == 1
    assert len(_renewals(pg_sessionmaker, sid)) == 1
    assert len(_periods(pg_sessionmaker, sid)) == 1
    assert len(grants_of(pg_sessionmaker, student)) == 1


def test_the_event_key_names_the_charge_and_stores_only_signed_body_fields(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    _linked(pg_sessionmaker)
    client = _client()
    body = subscription_webhook(TRIGGER_SUCCESS, PID, paymob_request_id="req-9")
    _deliver(pg_sessionmaker, client, body)
    [event] = _events(pg_sessionmaker)
    assert event.kind is PaymobEventKind.subscription
    assert event.dedupe_key == f"sub:{PID}:Successful Transaction:txn:888"
    assert event.payload["body"] == {
        "trigger_type": TRIGGER_SUCCESS,
        "subscription_data": {"id": PID},
    }
    assert event.payload["remote"]["id"] == PID
    assert event.processed_at == NOW


def test_a_trigger_without_a_charge_is_keyed_on_the_remote_state(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    _linked(pg_sessionmaker)
    client = _client()
    client.subscriptions[PID] = remote_subscription(PID, state="active", updated_at="2026-12-01")
    _deliver(pg_sessionmaker, client, subscription_webhook("updated", PID))  # our own PUT's echo
    [event] = _events(pg_sessionmaker)
    assert event.dedupe_key == f"sub:{PID}:updated:active:2026-12-01"
    assert client.names() == ["get_subscription"]  # no charge is read for a non-charge trigger


def test_a_success_with_no_charge_id_is_not_deduplicated_on_a_placeholder(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """``txn:none`` would swallow every later success whose charge has no id; a real one is not."""
    student, sid = _linked(pg_sessionmaker)
    broken = _client()
    broken.last_transactions[PID] = broken.last_transactions[PID] | {"id": None}
    for _ in range(2):
        with capture_logs() as logs:
            _deliver(pg_sessionmaker, broken)
        assert "subscription_webhook_not_deduplicable" in _alerts(logs)
    assert _events(pg_sessionmaker) == []
    _deliver(pg_sessionmaker, _client())  # the real charge arrives later and is applied
    assert len(_renewals(pg_sessionmaker, sid)) == 1
    assert len(grants_of(pg_sessionmaker, student)) == 1
    [event] = _events(pg_sessionmaker)
    assert event.processed_at == NOW


@pytest.mark.parametrize("missing", ["updated_at", "state"])
def test_a_trigger_without_a_remote_stamp_is_not_deduplicated_on_a_placeholder(
    pg_sessionmaker: sessionmaker[Session], missing: str
) -> None:
    """``active:None`` would drop every later same-trigger delivery in the same state."""
    _linked(pg_sessionmaker)
    client = _client()
    remote = remote_subscription(PID, state="active", updated_at="2026-12-01")
    del remote[missing]
    client.subscriptions[PID] = remote
    body = subscription_webhook("updated", PID)
    with capture_logs() as logs:
        _deliver(pg_sessionmaker, client, body)
    assert "subscription_webhook_not_deduplicable" in _alerts(logs)
    assert _events(pg_sessionmaker) == []
    client.subscriptions[PID] = remote_subscription(PID, state="active", updated_at="2026-12-02")
    _deliver(pg_sessionmaker, client, body)  # a later real event is stored, not dropped
    [event] = _events(pg_sessionmaker)
    assert event.dedupe_key == f"sub:{PID}:updated:active:2026-12-02"
    assert event.processed_at == NOW


def test_the_same_charge_after_its_event_is_gone_is_still_granted_once(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """Correctness never rests on the event key: the stored Paymob transaction id decides."""
    student, sid = _linked(pg_sessionmaker)
    client = _client()
    _deliver(pg_sessionmaker, client)
    with pg_sessionmaker.begin() as session:
        session.execute(sa.text("DELETE FROM paymob_events"))
    _deliver(pg_sessionmaker, client)
    assert len(_renewals(pg_sessionmaker, sid)) == 1
    assert len(_periods(pg_sessionmaker, sid)) == 1
    assert len(grants_of(pg_sessionmaker, student)) == 1


def test_applying_a_recorded_charge_again_returns_false(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    _, sid = _linked(pg_sessionmaker)
    txn = charge(888, 10_000, created_at=EARLY)
    results = []
    for _ in range(2):
        with pg_sessionmaker.begin() as session:
            sub = session.get(Subscription, sid)
            assert sub is not None
            results.append(_service(session)._apply_successful_charge(sub, txn, now=NOW))
    assert results == [True, False]
    assert len(_periods(pg_sessionmaker, sid)) == 1


def test_a_duplicate_event_that_never_completed_is_applied_on_redelivery(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """An unmatched delivery stored first; once the plan is linked, Paymob's retry is applied."""
    student = seed_user(pg_sessionmaker, Role.student)
    tier = seed_tier(pg_sessionmaker)
    sid = seed_subscription(
        pg_sessionmaker,
        user_id=student,
        tier_id=tier,
        payer_id=student,
        paymob_amount_minor=10_000,
        activated_at=T0,
    )  # not yet linked to Paymob, and Paymob's initial transaction names no payment of ours
    client = _client()
    _deliver(pg_sessionmaker, client)
    [stored] = _events(pg_sessionmaker)
    assert stored.processed_at is None
    assert _renewals(pg_sessionmaker, sid) == []
    with pg_sessionmaker.begin() as session:
        session.execute(
            sa.update(Subscription).where(Subscription.id == sid).values(paymob_subscription_id=PID)
        )
    _deliver(pg_sessionmaker, client)
    assert len(_renewals(pg_sessionmaker, sid)) == 1
    [event] = _events(pg_sessionmaker)
    assert event.processed_at == NOW


def test_a_failure_after_the_grant_rolls_everything_back_and_a_retry_grants_once(
    pg_sessionmaker: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Failure injection: the webhook answers 5xx, nothing is half-written, Paymob's retry works."""
    student, sid = _linked(pg_sessionmaker)
    client = _client()
    real = subscription_repo._issue_period_grant

    def boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("ledger down")

    monkeypatch.setattr(subscription_repo, "_issue_period_grant", boom)
    with pytest.raises(RuntimeError, match="ledger down"):
        _deliver(pg_sessionmaker, client)
    assert _events(pg_sessionmaker) == []
    assert _renewals(pg_sessionmaker, sid) == []
    assert _periods(pg_sessionmaker, sid) == []
    assert _subscription(pg_sessionmaker, sid).current_period_end == END

    monkeypatch.setattr(subscription_repo, "_issue_period_grant", real)
    _deliver(pg_sessionmaker, client)
    assert len(_renewals(pg_sessionmaker, sid)) == 1
    assert len(grants_of(pg_sessionmaker, student)) == 1


# -- Paymob reads come first and fail cleanly --------------------------------------------


@pytest.mark.parametrize("failing", ["get_subscription", "last_transaction"])
def test_a_paymob_read_error_propagates_before_any_write(
    pg_sessionmaker: sessionmaker[Session], failing: str
) -> None:
    """An unknown outcome (a timeout, a 5xx): the route answers 503 and Paymob retries.

    The error is caught inside the transaction and the transaction then COMMITS, so a row written
    before the read would survive: rolling back would hide it.
    """
    student, sid = _linked(pg_sessionmaker)
    client = _client()
    client.fail[failing] = PaymobError("Paymob timed out", timeout=True, outcome_unknown=True)
    with pg_sessionmaker.begin() as session:
        service = SubscriptionService(session, client, paymob_settings())
        with pytest.raises(PaymobError):
            service.apply_renewal_webhook(SUCCESS_BODY, now=NOW)
    assert _events(pg_sessionmaker) == []
    assert _renewals(pg_sessionmaker, sid) == []
    assert grants_of(pg_sessionmaker, student) == []
    del client.fail[failing]
    _deliver(pg_sessionmaker, client)  # the retry succeeds, once
    assert len(_renewals(pg_sessionmaker, sid)) == 1


def test_the_paymob_reads_happen_with_no_database_lock_held(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """DV-11: a slow Paymob must not hold the subscription row, so another writer is not blocked."""
    _, sid = _linked(pg_sessionmaker)
    client = _client()
    probe_results: list[bool] = []
    real = client.get_subscription

    def probing(subscription_id: int) -> Any:
        with pg_sessionmaker() as probe:
            row = probe.execute(
                sa.select(Subscription.id)
                .where(Subscription.id == sid)
                .with_for_update(nowait=True)
            ).first()
            probe_results.append(row is not None)
            probe.rollback()
        return real(subscription_id)

    client.get_subscription = probing  # type: ignore[method-assign]
    _deliver(pg_sessionmaker, client)
    assert probe_results == [True]


# -- amount acceptance (DV-12) ----------------------------------------------------------


def test_an_amount_lemely_did_not_set_records_failed_mismatch_and_grants_nothing(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student, sid = _linked(pg_sessionmaker)
    with capture_logs() as logs:
        _deliver(pg_sessionmaker, _client(amount=9_000))
    [payment] = _renewals(pg_sessionmaker, sid)
    assert payment.status is PaymentStatus.failed_mismatch
    assert payment.paid_at is None
    assert _periods(pg_sessionmaker, sid) == []
    assert grants_of(pg_sessionmaker, student) == []
    assert _subscription(pg_sessionmaker, sid).current_period_end == END
    assert "subscription_renewal_mismatch" in _alerts(logs)


def test_a_charge_in_another_currency_is_a_mismatch(pg_sessionmaker: sessionmaker[Session]) -> None:
    student, sid = _linked(pg_sessionmaker)
    with capture_logs() as logs:
        _deliver(pg_sessionmaker, _client(currency="USD"))
    [payment] = _renewals(pg_sessionmaker, sid)
    assert payment.status is PaymentStatus.failed_mismatch
    assert grants_of(pg_sessionmaker, student) == []
    assert "subscription_renewal_mismatch" in _alerts(logs)


@pytest.mark.parametrize(
    "damage",
    [
        {"id": None},
        {"id": True},
        {"id": "888"},
        {"amount_cents": 0},
        {"amount_cents": -5},
        {"amount_cents": "10000"},
        {"amount_cents": True},
        {"amount_cents": None},
        {"currency": None},
        {"currency": ""},
        {"currency": "EGPX"},
        {"id": 10**30},
    ],
)
def test_an_unreadable_charge_writes_nothing_and_alerts(
    pg_sessionmaker: sessionmaker[Session], damage: dict[str, Any]
) -> None:
    student, sid = _linked(pg_sessionmaker)
    client = _client()
    client.last_transactions[PID] = client.last_transactions[PID] | damage
    with capture_logs() as logs:
        _deliver(pg_sessionmaker, client)
    assert _renewals(pg_sessionmaker, sid) == []
    assert _periods(pg_sessionmaker, sid) == []
    assert grants_of(pg_sessionmaker, student) == []
    assert "subscription_last_transaction_unreadable" in _alerts(logs)
    # No 500 loop: a delivery with a readable charge id is recorded, so a replay is a no-op. One
    # with no id has nothing to dedupe on and is not recorded at all (it must not swallow later
    # real deliveries).
    expected_events = 0 if damage.get("id", 888) in (None, True, "888") else 1
    assert len(_events(pg_sessionmaker)) == expected_events


@pytest.mark.parametrize(
    "flags",
    [
        {"success": False},
        {"pending": True},
        {"is_voided": True},
        {"is_refunded": True},
        {"error_occured": True},
        {"is_auth": True},
    ],
)
def test_a_charge_that_is_not_a_success_changes_nothing(
    pg_sessionmaker: sessionmaker[Session], flags: dict[str, Any]
) -> None:
    student, sid = _linked(pg_sessionmaker)
    _deliver(pg_sessionmaker, _client(**flags))
    assert _renewals(pg_sessionmaker, sid) == []
    assert grants_of(pg_sessionmaker, student) == []
    assert _subscription(pg_sessionmaker, sid).current_period_end == END


def test_the_first_charge_is_never_taken_for_a_renewal(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """A success webhook for Paymob's initial transaction belongs to the first payment."""
    student, sid = _linked(pg_sessionmaker)
    client = _client(txn=FIRST_TXN)  # remote ``initial_transaction`` is FIRST_TXN too
    _deliver(pg_sessionmaker, client)
    assert _renewals(pg_sessionmaker, sid) == []
    assert grants_of(pg_sessionmaker, student) == []


def test_a_charge_on_the_moto_integration_is_accepted(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    _, sid = _linked(pg_sessionmaker)
    _deliver(pg_sessionmaker, _client(integration_id=MOTO_INTEGRATION_ID))
    assert len(_periods(pg_sessionmaker, sid)) == 1


def test_a_charge_on_another_integration_is_refused_and_alerted(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student, sid = _linked(pg_sessionmaker)
    with capture_logs() as logs:
        _deliver(pg_sessionmaker, _client(integration_id=MOTO_INTEGRATION_ID + 1))
    assert _renewals(pg_sessionmaker, sid) == []
    assert grants_of(pg_sessionmaker, student) == []
    assert "paymob_unexpected_integration" in _alerts(logs)


def test_a_digit_string_integration_id_is_judged_like_a_number(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """Phase 02 reads a digit string as the integer, so both checks agree."""
    student, sid = _linked(pg_sessionmaker)
    with capture_logs() as logs:
        _deliver(pg_sessionmaker, _client(integration_id=str(MOTO_INTEGRATION_ID + 1)))
    assert _renewals(pg_sessionmaker, sid) == []
    assert grants_of(pg_sessionmaker, student) == []
    assert "paymob_unexpected_integration" in _alerts(logs)


def test_a_renewal_with_no_payer_is_not_recorded(pg_sessionmaker: sessionmaker[Session]) -> None:
    student, sid = _linked(pg_sessionmaker, payer_id=None)
    with capture_logs() as logs:
        _deliver(pg_sessionmaker, _client())
    assert _renewals(pg_sessionmaker, sid) == []
    assert grants_of(pg_sessionmaker, student) == []
    assert "subscription_renewal_without_payer" in [entry["event"] for entry in logs]


def _pending_downgrade(
    sm: sessionmaker[Session], *, stamp: int
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    lower = seed_tier(sm, price_minor=6_000, allowance_units=400)
    student, sid = _linked(sm, pending_plan_tier_id=lower, paymob_amount_minor=stamp)
    return student, sid, lower


def test_a_pending_downgrade_is_applied_when_the_charge_is_the_new_amount(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student, sid, lower = _pending_downgrade(pg_sessionmaker, stamp=6_000)  # pushed by the sweep
    _deliver(pg_sessionmaker, _client(amount=6_000))
    sub = _subscription(pg_sessionmaker, sid)
    assert (sub.plan_tier_id, sub.pending_plan_tier_id) == (lower, None)
    assert sub.paymob_amount_minor == 6_000
    [renewal] = _renewals(pg_sessionmaker, sid)
    assert renewal.plan_tier_id == lower
    assert [grant.units for grant in grants_of(pg_sessionmaker, student)] == [400]


def test_a_pending_downgrade_waits_when_paymob_charged_the_old_stamped_amount(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """The PUT failed or never ran: Paymob charges the old amount, so the old tier is granted."""
    student, sid, lower = _pending_downgrade(pg_sessionmaker, stamp=10_000)
    original_tier = _subscription(pg_sessionmaker, sid).plan_tier_id
    with capture_logs() as logs:
        _deliver(pg_sessionmaker, _client(amount=10_000))
    sub = _subscription(pg_sessionmaker, sid)
    assert (sub.plan_tier_id, sub.pending_plan_tier_id) == (original_tier, lower)
    assert sub.paymob_amount_minor == 10_000
    [renewal] = _renewals(pg_sessionmaker, sid)
    assert renewal.plan_tier_id == original_tier
    assert [grant.units for grant in grants_of(pg_sessionmaker, student)] == [1_000]
    assert "subscription_pending_change_deferred" in [entry["event"] for entry in logs]


def test_a_put_that_applied_but_was_not_stamped_is_accepted_and_stamped(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """The PUT timed out after Paymob applied it: stamp is old, charge is the new amount."""
    student, sid, lower = _pending_downgrade(pg_sessionmaker, stamp=10_000)
    _deliver(pg_sessionmaker, _client(amount=6_000))
    sub = _subscription(pg_sessionmaker, sid)
    assert (sub.plan_tier_id, sub.pending_plan_tier_id) == (lower, None)
    assert sub.paymob_amount_minor == 6_000
    assert [grant.units for grant in grants_of(pg_sessionmaker, student)] == [400]


def test_a_third_amount_is_a_mismatch_even_with_a_pending_change(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student, sid, lower = _pending_downgrade(pg_sessionmaker, stamp=10_000)
    original_tier = _subscription(pg_sessionmaker, sid).plan_tier_id
    with capture_logs() as logs:
        _deliver(pg_sessionmaker, _client(amount=7_500))
    [payment] = _renewals(pg_sessionmaker, sid)
    assert payment.status is PaymentStatus.failed_mismatch
    sub = _subscription(pg_sessionmaker, sid)
    assert (sub.plan_tier_id, sub.pending_plan_tier_id) == (original_tier, lower)
    assert grants_of(pg_sessionmaker, student) == []
    assert "subscription_renewal_mismatch" in _alerts(logs)


def test_pending_extra_seats_change_the_expected_amount(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    teacher = seed_user(pg_sessionmaker, Role.teacher)
    tier = seed_tier(
        pg_sessionmaker,
        audience=PlanAudience.teacher,
        price_minor=20_000,
        included_seats=2,
        extra_seat_price_minor=1_000,
    )
    sid = seed_subscription(
        pg_sessionmaker,
        user_id=teacher,
        tier_id=tier,
        payer_id=teacher,
        paymob_subscription_id=PID,
        paymob_amount_minor=23_000,
        extra_seats=3,
        pending_extra_seats=1,
    )
    _deliver(pg_sessionmaker, _client(amount=21_000))
    sub = _subscription(pg_sessionmaker, sid)
    assert (sub.extra_seats, sub.pending_extra_seats) == (1, None)
    [renewal] = _renewals(pg_sessionmaker, sid)
    assert renewal.seat_quantity == 1


# -- teachers ---------------------------------------------------------------------------


def _teacher_with_three_seats(
    sm: sessionmaker[Session],
) -> tuple[uuid.UUID, uuid.UUID, list[uuid.UUID]]:
    teacher = seed_user(sm, Role.teacher)
    big = seed_tier(sm, audience=PlanAudience.teacher, included_seats=3, price_minor=10_000)
    small = seed_tier(sm, audience=PlanAudience.teacher, included_seats=1, price_minor=6_000)
    sid = seed_subscription(
        sm,
        user_id=teacher,
        tier_id=big,
        payer_id=teacher,
        paymob_subscription_id=PID,
        paymob_amount_minor=6_000,  # the sweep already pushed the downgrade
        pending_plan_tier_id=small,
    )
    seats = [
        seed_seat(
            sm,
            teacher_id=teacher,
            student_id=seed_user(sm, Role.student),
            created_at=T0 + timedelta(hours=index),
        )
        for index in range(3)
    ]
    return teacher, sid, seats


def test_a_teacher_downgrade_moves_the_newest_excess_seats_to_leaving(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    teacher, sid, seats = _teacher_with_three_seats(pg_sessionmaker)
    _deliver(pg_sessionmaker, _client(amount=6_000))
    with pg_sessionmaker() as session:
        statuses = [session.get(TeacherMember, seat).status for seat in seats]  # type: ignore[union-attr]
    assert statuses == [
        TeacherMemberStatus.active,
        TeacherMemberStatus.leaving,
        TeacherMemberStatus.leaving,
    ]
    assert len(_periods(pg_sessionmaker, sid)) == 1  # the grant is still issued
    assert len(grants_of(pg_sessionmaker, teacher)) == 1


def test_seats_are_shed_before_the_period_grant_is_issued(
    pg_sessionmaker: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    """DV-13: member rows are locked before the ledger's owner locks, so shed first."""
    _, _, seats = _teacher_with_three_seats(pg_sessionmaker)
    seen: list[list[TeacherMemberStatus]] = []
    real = subscription_repo._issue_period_grant

    def spy(session: Session, *args: Any, **kwargs: Any) -> Any:
        seen.append([session.get(TeacherMember, seat).status for seat in seats])  # type: ignore[union-attr]
        return real(session, *args, **kwargs)

    monkeypatch.setattr(subscription_repo, "_issue_period_grant", spy)
    _deliver(pg_sessionmaker, _client(amount=6_000))
    assert seen == [
        [TeacherMemberStatus.active, TeacherMemberStatus.leaving, TeacherMemberStatus.leaving]
    ]


def test_a_pending_seat_reduction_moves_the_newest_excess_seats_to_leaving(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    teacher = seed_user(pg_sessionmaker, Role.teacher)
    tier = seed_tier(
        pg_sessionmaker,
        audience=PlanAudience.teacher,
        price_minor=10_000,
        included_seats=1,
        extra_seat_price_minor=2_000,
    )
    sid = seed_subscription(
        pg_sessionmaker,
        user_id=teacher,
        tier_id=tier,
        payer_id=teacher,
        paymob_subscription_id=PID,
        paymob_amount_minor=14_000,
        extra_seats=2,
        pending_extra_seats=0,
    )
    seats = [
        seed_seat(
            pg_sessionmaker,
            teacher_id=teacher,
            student_id=seed_user(pg_sessionmaker, Role.student),
            created_at=T0 + timedelta(hours=index),
        )
        for index in range(3)
    ]
    _deliver(pg_sessionmaker, _client(amount=10_000))
    sub = _subscription(pg_sessionmaker, sid)
    assert (sub.extra_seats, sub.pending_extra_seats) == (0, None)
    with pg_sessionmaker() as session:
        statuses = [session.get(TeacherMember, seat).status for seat in seats]  # type: ignore[union-attr]
    assert statuses == [
        TeacherMemberStatus.active,
        TeacherMemberStatus.leaving,
        TeacherMemberStatus.leaving,
    ]
    assert len(grants_of(pg_sessionmaker, teacher)) == 1


# -- linking ----------------------------------------------------------------------------


def _unlinked_with_first_payment(
    sm: sessionmaker[Session],
    *,
    status: SubscriptionStatus = SubscriptionStatus.active,
    txn_id: int = FIRST_TXN,
    **kwargs: Any,
) -> tuple[uuid.UUID, uuid.UUID]:
    student = seed_user(sm, Role.student)
    sid = seed_subscription(
        sm,
        user_id=student,
        tier_id=seed_tier(sm),
        payer_id=student,
        status=status,
        paymob_amount_minor=10_000,
        **kwargs,
    )
    seed_first_payment(sm, subscription_id=sid, paymob_txn_id=txn_id)
    return student, sid


def test_an_unlinked_subscription_is_linked_through_its_first_payment(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    _, sid = _unlinked_with_first_payment(pg_sessionmaker)
    _deliver(pg_sessionmaker, _client(), subscription_webhook(TRIGGER_CREATED, PID))
    assert _subscription(pg_sessionmaker, sid).paymob_subscription_id == PID
    [event] = _events(pg_sessionmaker)
    assert event.processed_at == NOW


def test_a_late_created_webhook_links_the_expired_converted_row(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """T5 note: the extra Paymob subscription must be linked so the sweeps can cancel it."""
    _, sid = _unlinked_with_first_payment(pg_sessionmaker, status=SubscriptionStatus.expired)
    _deliver(pg_sessionmaker, _client(), subscription_webhook(TRIGGER_CREATED, PID))
    sub = _subscription(pg_sessionmaker, sid)
    assert sub.paymob_subscription_id == PID
    assert sub.status is SubscriptionStatus.expired
    assert sub.paymob_cancelled_at is None  # the DV-15 / DV-27 cancel candidate


def test_a_remote_whose_id_disagrees_is_unmatched(pg_sessionmaker: sessionmaker[Session]) -> None:
    _, sid = _unlinked_with_first_payment(pg_sessionmaker)
    client = _client()
    client.get_subscription = lambda subscription_id: remote_subscription(  # type: ignore[method-assign]
        9_999, initial_transaction=FIRST_TXN
    )
    with capture_logs() as logs:
        _deliver(pg_sessionmaker, client, subscription_webhook(TRIGGER_CREATED, PID))
    assert _subscription(pg_sessionmaker, sid).paymob_subscription_id is None
    assert "paymob_subscription_remote_mismatch" in [entry["event"] for entry in logs]
    [event] = _events(pg_sessionmaker)
    assert event.processed_at is None
    # A copy judged untrustworthy is not kept where the first-payment linker would act on it.
    assert event.payload["remote"] is None


def test_an_unknown_subscription_is_stored_unprocessed_with_the_remote_copy(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    client = _client()
    with capture_logs() as logs:
        _deliver(pg_sessionmaker, client, subscription_webhook(TRIGGER_CREATED, PID))
    [event] = _events(pg_sessionmaker)
    assert event.processed_at is None
    assert event.payload["remote"]["initial_transaction"] == FIRST_TXN
    assert event.payload["body"]["subscription_data"] == {"id": PID}
    assert "paymob_subscription_webhook_unmatched" in [entry["event"] for entry in logs]


def test_only_a_first_payment_links_a_subscription(pg_sessionmaker: sessionmaker[Session]) -> None:
    student, sid = _linked(pg_sessionmaker, paymob_subscription_id=None)
    with pg_sessionmaker.begin() as session:
        session.add(
            Payment(
                special_reference="subscription-renewal:777",
                payer_user_id=student,
                beneficiary_user_id=student,
                purpose=PaymentPurpose.subscription_renewal,
                subscription_id=sid,
                amount_minor=10_000,
                currency="EGP",
                status=PaymentStatus.paid,
                paymob_txn_id=FIRST_TXN,
                paid_at=T0,
            )
        )
    _deliver(pg_sessionmaker, _client(), subscription_webhook(TRIGGER_CREATED, PID))
    assert _subscription(pg_sessionmaker, sid).paymob_subscription_id is None


def test_an_id_already_held_by_another_subscription_is_not_stolen(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    _, holder = _linked(pg_sessionmaker)
    _, other = _unlinked_with_first_payment(pg_sessionmaker)
    _deliver(pg_sessionmaker, _client(), subscription_webhook(TRIGGER_CREATED, PID))
    assert _subscription(pg_sessionmaker, holder).paymob_subscription_id == PID
    assert _subscription(pg_sessionmaker, other).paymob_subscription_id is None


def test_a_subscription_already_linked_to_another_id_is_not_relinked(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    _, sid = _unlinked_with_first_payment(pg_sessionmaker, paymob_subscription_id=PID + 1)
    with capture_logs() as logs:
        _deliver(pg_sessionmaker, _client(), subscription_webhook(TRIGGER_CREATED, PID))
    assert _subscription(pg_sessionmaker, sid).paymob_subscription_id == PID + 1
    assert "subscription_link_conflict" in _alerts(logs)


def test_resolve_takes_the_advisory_lock_on_the_initial_transaction(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """T5-I2: the same transaction-scoped lock the first-payment handler takes."""
    _, sid = _unlinked_with_first_payment(pg_sessionmaker)
    holder = pg_sessionmaker()
    holder.execute(
        sa.text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"paymob_txn:{FIRST_TXN}"},
    )
    done = threading.Event()

    def run() -> None:
        _deliver(pg_sessionmaker, _client(), subscription_webhook(TRIGGER_CREATED, PID))
        done.set()

    thread = threading.Thread(target=run)
    thread.start()
    try:
        assert not done.wait(timeout=1.5), "the webhook ran without the transaction lock"
    finally:
        holder.rollback()
        holder.close()
    thread.join(timeout=30)
    assert done.is_set()
    assert _subscription(pg_sessionmaker, sid).paymob_subscription_id == PID


# -- races ------------------------------------------------------------------------------


def test_two_concurrent_deliveries_of_one_renewal_grant_once(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student, sid = _linked(pg_sessionmaker)
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def run() -> None:
        try:
            barrier.wait(timeout=10)
            _deliver(pg_sessionmaker, _client())
        except BaseException as exc:  # reported through the assertion below
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert not any(thread.is_alive() for thread in threads), "a delivery hung (deadlock)"
    assert errors == []
    assert len(_renewals(pg_sessionmaker, sid)) == 1
    assert len(_periods(pg_sessionmaker, sid)) == 1
    assert len(grants_of(pg_sessionmaker, student)) == 1


@pytest.mark.parametrize("txn_in_callback_transaction", [False, True])
def test_a_renewal_webhook_racing_the_first_payment_callback_grants_one_period(
    pg_sessionmaker: sessionmaker[Session], txn_in_callback_transaction: bool
) -> None:
    """The success webhook names the first charge while the first payment's handler runs.

    In production Phase 02 writes the payment's Paymob transaction id and ``paid`` in the same
    uncommitted transaction that runs the handler (``txn_in_callback_transaction``): the webhook
    then cannot see the payment, stores itself unprocessed, and the handler's linker consumes it.
    """
    for round_number in range(5):
        student = seed_user(pg_sessionmaker, Role.student)
        sid = seed_subscription(
            pg_sessionmaker,
            user_id=student,
            tier_id=seed_tier(pg_sessionmaker),
            payer_id=student,
            status=SubscriptionStatus.pending_first_payment,
            period_start=None,
            period_end=None,
        )
        first_txn = 9_000 + round_number
        paid_at = T0 + timedelta(minutes=7)
        pid = seed_first_payment(
            pg_sessionmaker,
            subscription_id=sid,
            status=PaymentStatus.created if txn_in_callback_transaction else PaymentStatus.paid,
            paymob_txn_id=None if txn_in_callback_transaction else first_txn,
            paid_at=paid_at,
        )
        paymob_id = PID + round_number
        client = FakePaymobClient()
        client.subscriptions[paymob_id] = remote_subscription(
            paymob_id, initial_transaction=first_txn
        )
        client.last_transactions[paymob_id] = charge(first_txn, 10_000, created_at=paid_at)
        barrier = threading.Barrier(2)
        errors: list[BaseException] = []

        def callback(
            pid: uuid.UUID = pid,
            barrier: threading.Barrier = barrier,
            errors: list[BaseException] = errors,
            first_txn: int = first_txn,
            paid_at: datetime = paid_at,
        ) -> None:
            try:
                barrier.wait(timeout=10)
                with pg_sessionmaker.begin() as session:
                    payment = session.get(Payment, pid)
                    assert payment is not None
                    if txn_in_callback_transaction:
                        payment.paymob_txn_id = first_txn  # uncommitted, as Phase 02 writes it
                        payment.status = PaymentStatus.paid
                        payment.paid_at = paid_at
                    handle_subscription_first(session, payment, {})
            except BaseException as exc:
                errors.append(exc)

        def webhook(
            paymob_id: int = paymob_id,
            client: FakePaymobClient = client,
            barrier: threading.Barrier = barrier,
            errors: list[BaseException] = errors,
            delivered_at: Any = paid_at + timedelta(minutes=1),
        ) -> None:
            try:
                barrier.wait(timeout=10)
                _deliver(
                    pg_sessionmaker,
                    client,
                    subscription_webhook(TRIGGER_SUCCESS, paymob_id),
                    now=delivered_at,
                )
            except BaseException as exc:
                errors.append(exc)

        threads = [threading.Thread(target=callback), threading.Thread(target=webhook)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)
        assert not any(thread.is_alive() for thread in threads), "deadlock"
        assert errors == []
        assert _renewals(pg_sessionmaker, sid) == []  # the first charge is not a renewal
        assert len(_periods(pg_sessionmaker, sid)) == 1
        assert len(grants_of(pg_sessionmaker, student)) == 1
        sub = _subscription(pg_sessionmaker, sid)
        assert sub.status is SubscriptionStatus.active
        assert sub.paymob_subscription_id == paymob_id


# -- a charge after the plan ended (UD-2) -----------------------------------------------


def test_a_late_charge_reactivates_a_plan_that_lapsed_for_non_payment(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student, sid = _linked(pg_sessionmaker, status=SubscriptionStatus.expired)
    charged = END + timedelta(days=9)
    _deliver(pg_sessionmaker, _client(charged=charged), now=charged + timedelta(minutes=1))
    sub = _subscription(pg_sessionmaker, sid)
    assert sub.status is SubscriptionStatus.active
    assert sub.current_period_start == charged
    assert sub.activated_at == T0  # the original activation is kept
    [grant] = grants_of(pg_sessionmaker, student)
    assert grant.effective_at == charged
    assert _notices(pg_sessionmaker, student) == ["renewed"]
    assert _notice_instants(pg_sessionmaker, student) == [charged + timedelta(days=30)]


def test_reactivating_a_plan_whose_paymob_subscription_is_cancelled_ends_it_at_period_end(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """The charge raced our cancel: the paid period runs, but the plan can never renew.

    Paymob does not charge a cancelled subscription again, so the row must not look
    auto-renewing: it ends cleanly as cancelled at the paid period's end, never in
    "payment failed" notices the user cannot act on.
    """
    student, sid = _linked(
        pg_sessionmaker,
        status=SubscriptionStatus.expired,
        paymob_cancelled_at=END + timedelta(days=4),
    )
    charged = END + timedelta(days=2)
    _deliver(pg_sessionmaker, _client(charged=charged), now=END + timedelta(days=5))
    sub = _subscription(pg_sessionmaker, sid)
    assert sub.status is SubscriptionStatus.active
    assert sub.cancel_at_period_end is True
    assert sub.paymob_cancelled_at == END + timedelta(days=4)
    assert sub.current_period_end == charged + timedelta(days=30)
    assert len(grants_of(pg_sessionmaker, student)) == 1


def test_reactivating_a_plan_paymob_still_holds_leaves_it_renewing(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    _, sid = _linked(pg_sessionmaker, status=SubscriptionStatus.expired)
    _deliver(pg_sessionmaker, _client(charged=END + timedelta(days=2)), now=END + timedelta(days=5))
    sub = _subscription(pg_sessionmaker, sid)
    assert (sub.status, sub.cancel_at_period_end) == (SubscriptionStatus.active, False)


def test_a_charge_time_in_the_future_is_capped_at_now(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """A skewed or mis-zoned timestamp (UD-8, S13) must not start the allowance in the future."""
    student, sid = _linked(pg_sessionmaker, status=SubscriptionStatus.expired)
    now = END + timedelta(days=5)
    _deliver(pg_sessionmaker, _client(charged=now + timedelta(days=3)), now=now)
    sub = _subscription(pg_sessionmaker, sid)
    assert sub.current_period_start == now
    [renewal] = _renewals(pg_sessionmaker, sid)
    assert renewal.paid_at == now
    [grant] = grants_of(pg_sessionmaker, student)
    assert grant.effective_at == now


def test_a_late_charge_does_not_reactivate_when_another_plan_is_live(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student, sid = _linked(pg_sessionmaker, status=SubscriptionStatus.expired)
    live = seed_subscription(
        pg_sessionmaker,
        user_id=student,
        tier_id=seed_tier(pg_sessionmaker),
        payer_id=student,
        status=SubscriptionStatus.active,
    )
    with capture_logs() as logs:
        _deliver(pg_sessionmaker, _client())
    [payment] = _renewals(pg_sessionmaker, sid)
    assert payment.status is PaymentStatus.paid  # money was taken: kept for a manual refund
    assert _periods(pg_sessionmaker, sid) == []
    assert grants_of(pg_sessionmaker, student) == []
    assert _subscription(pg_sessionmaker, sid).status is SubscriptionStatus.expired
    assert _subscription(pg_sessionmaker, live).status is SubscriptionStatus.active
    assert "subscription_charge_on_ended_subscription" in _alerts(logs)


def test_a_late_charge_on_a_user_cancelled_plan_is_refunded_not_reactivated(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student, sid = _linked(pg_sessionmaker, status=SubscriptionStatus.cancelled)
    with capture_logs() as logs:
        _deliver(pg_sessionmaker, _client())
    [payment] = _renewals(pg_sessionmaker, sid)
    assert payment.status is PaymentStatus.paid
    assert _periods(pg_sessionmaker, sid) == []
    assert grants_of(pg_sessionmaker, student) == []
    sub = _subscription(pg_sessionmaker, sid)
    assert sub.status is SubscriptionStatus.cancelled
    assert sub.paymob_cancelled_at is None  # still a DV-15 / DV-27 Paymob cancel candidate
    alert = next(e for e in logs if e["event"] == "subscription_charge_on_ended_subscription")
    assert alert["alert"] is True
    assert alert["status"] == "cancelled"


def test_a_credits_converted_row_is_never_reactivated(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """UD-2: reactivation needs ``activated_at``; a converted checkout never ran."""
    student, sid = _linked(pg_sessionmaker, status=SubscriptionStatus.expired, activated_at=None)
    with capture_logs() as logs:
        _deliver(pg_sessionmaker, _client())
    [payment] = _renewals(pg_sessionmaker, sid)
    assert payment.status is PaymentStatus.paid
    assert _subscription(pg_sessionmaker, sid).status is SubscriptionStatus.expired
    assert _periods(pg_sessionmaker, sid) == []
    assert grants_of(pg_sessionmaker, student) == []
    assert "subscription_charge_on_ended_subscription" in _alerts(logs)


def test_a_charge_on_an_unpaid_checkout_is_kept_for_refund(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student, sid = _linked(
        pg_sessionmaker,
        status=SubscriptionStatus.pending_first_payment,
        activated_at=None,
        period_start=None,
        period_end=None,
    )
    with capture_logs() as logs:
        _deliver(pg_sessionmaker, _client())
    [payment] = _renewals(pg_sessionmaker, sid)
    assert payment.status is PaymentStatus.paid
    assert grants_of(pg_sessionmaker, student) == []
    assert _subscription(pg_sessionmaker, sid).status is SubscriptionStatus.pending_first_payment
    assert "subscription_charge_on_ended_subscription" in _alerts(logs)


def test_a_reactivation_that_loses_the_unique_index_race_keeps_the_payment_only(
    pg_sessionmaker: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A live row committed after the lock was taken trips the index: refund path, no 500."""
    student, sid = _linked(pg_sessionmaker, status=SubscriptionStatus.expired)
    seed_subscription(
        pg_sessionmaker,
        user_id=student,
        tier_id=seed_tier(pg_sessionmaker),
        payer_id=student,
        status=SubscriptionStatus.active,
    )
    monkeypatch.setattr(subscription_repo, "_has_other_live", lambda session, subscription: False)
    with capture_logs() as logs:
        _deliver(pg_sessionmaker, _client())
    assert _subscription(pg_sessionmaker, sid).status is SubscriptionStatus.expired
    assert _periods(pg_sessionmaker, sid) == []
    [payment] = _renewals(pg_sessionmaker, sid)
    assert payment.status is PaymentStatus.paid
    assert "subscription_charge_on_ended_subscription" in _alerts(logs)


def test_a_renewal_after_a_cancel_request_still_grants_what_was_paid(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """The cancel had not reached Paymob yet: the paid period is granted, the flag stays, and an
    operator is paged (the cancel did not take effect)."""
    student, sid = _linked(pg_sessionmaker, cancel_at_period_end=True)
    with capture_logs() as logs:
        _deliver(pg_sessionmaker, _client())
    sub = _subscription(pg_sessionmaker, sid)
    assert sub.cancel_at_period_end is True
    assert len(_periods(pg_sessionmaker, sid)) == 1
    assert len(grants_of(pg_sessionmaker, student)) == 1
    [entry] = [e for e in logs if e["event"] == "subscription_renewal_after_cancel_request"]
    # Our Paymob cancel did not take effect: the user asked to stop and was charged anyway.
    assert (entry["log_level"], entry["alert"]) == ("error", True)


# -- the paid handler for ``subscription_renewal`` (DV-33) -----------------------------


def _paid_renewal(
    sm: sessionmaker[Session],
    student: uuid.UUID,
    sid: uuid.UUID,
    *,
    paid_at: Any = END,
    amount: int = 10_000,
) -> uuid.UUID:
    pid = uuid.uuid4()
    with sm.begin() as session:
        session.add(
            Payment(
                id=pid,
                special_reference=f"manual-renewal-{pid}",
                payer_user_id=student,
                beneficiary_user_id=student,
                purpose=PaymentPurpose.subscription_renewal,
                subscription_id=sid,
                amount_minor=amount,
                currency="EGP",
                status=PaymentStatus.paid,
                paid_at=paid_at,
            )
        )
    return pid


def _run_renewal_handler(sm: sessionmaker[Session], pid: uuid.UUID) -> None:
    with sm.begin() as session:
        payment = session.get(Payment, pid)
        assert payment is not None
        handle_subscription_renewal(session, payment, {})


def test_the_renewal_handler_is_registered() -> None:
    assert paid_handler_for(PaymentPurpose.subscription_renewal) is handle_subscription_renewal


def test_the_renewal_handler_grants_once(pg_sessionmaker: sessionmaker[Session]) -> None:
    student, sid = _linked(pg_sessionmaker)
    pid = _paid_renewal(pg_sessionmaker, student, sid)
    _run_renewal_handler(pg_sessionmaker, pid)
    _run_renewal_handler(pg_sessionmaker, pid)
    [period] = _periods(pg_sessionmaker, sid)
    assert period.payment_id == pid
    assert period.period_start == END  # its clock is the payment's ``paid_at``
    assert len(grants_of(pg_sessionmaker, student)) == 1


def test_the_renewal_handler_never_guesses_the_clock(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student, sid = _linked(pg_sessionmaker)
    pid = _paid_renewal(pg_sessionmaker, student, sid, paid_at=None)
    with pytest.raises(RuntimeError, match="paid_at"):
        _run_renewal_handler(pg_sessionmaker, pid)
    assert _periods(pg_sessionmaker, sid) == []


def test_the_renewal_handler_leaves_an_ended_plan_for_a_refund(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student, sid = _linked(pg_sessionmaker, status=SubscriptionStatus.cancelled)
    pid = _paid_renewal(pg_sessionmaker, student, sid)
    with capture_logs() as logs:
        _run_renewal_handler(pg_sessionmaker, pid)
    assert _periods(pg_sessionmaker, sid) == []
    assert "subscription_charge_on_ended_subscription" in _alerts(logs)


def test_the_renewal_handler_alerts_for_a_missing_subscription(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student, sid = _linked(pg_sessionmaker)
    pid = _paid_renewal(pg_sessionmaker, student, sid)
    with pg_sessionmaker.begin() as session:
        session.execute(sa.update(Payment).where(Payment.id == pid).values(subscription_id=None))
    with capture_logs() as logs:
        _run_renewal_handler(pg_sessionmaker, pid)
    assert "subscription_renewal_paid_without_subscription" in _alerts(logs)
