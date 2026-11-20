"""Failed renewals, grace, expiry and Paymob state mirroring (spec §2.6, §5.2; DV-15, UD-1, UD-4).

Real Postgres (a throwaway ``create_all`` database). The rules under test: Paymob's retries never
extend the first grace deadline; the expiring period's leftover allowance stays usable until the
grace date and not after (UD-1 (b)); the webhook path makes no Paymob write while the sweeps do
(DV-15); a sweep skips a row another session holds, is bounded, and lets one failing row fail
alone; and a cancel made in Paymob's dashboard means "cancel at period end" (UD-4 (b)).
"""

from __future__ import annotations

import threading
import time
import uuid
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal

import pytest
import sqlalchemy as sa
from structlog.testing import capture_logs

from lemely.core.subscription_rules import MAX_GRACE_DAYS
from lemely.core.usage_types import GrantScope, Payer
from lemely.db import subscription_repo
from lemely.db.models.billing import Subscription, SubscriptionPeriod
from lemely.db.models.enums import Role, SubscriptionStatus
from lemely.db.models.tutoring import EmailOutbox
from lemely.db.models.usage import GrantKind, UsageEntry, UsageGrant, UsageGrantBalance
from lemely.db.subscription_repo import (
    EARLY_CHARGE_WINDOW,
    SUBSCRIPTION_SWEEP_BATCH,
    TRIGGER_CANCELED,
    TRIGGER_FAILED,
    TRIGGER_OVERDUE,
    TRIGGER_RESUMED,
    TRIGGER_SUCCESS,
    TRIGGER_SUSPENDED,
    SubscriptionNotFound,
    SubscriptionService,
)
from lemely.db.usage_ledger_repo import UsageLedger
from lemely.io.paymob.client import PaymobError
from tests.subscription_fixtures import (
    T0,
    FakePaymobClient,
    charge,
    ensure_billing_settings,
    paymob_settings,
    remote_subscription,
    seed_subscription,
    seed_tier,
    seed_user,
    subscription_webhook,
    throwaway_database,
)
from tests.team_db import emptied_after

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence

    from sqlalchemy.orm import Session, sessionmaker

PID = 4321
INITIAL_TXN = 777  # ``remote_subscription``'s default ``initial_transaction``
END = T0 + timedelta(days=30)
GRACE = timedelta(days=3)


@pytest.fixture(scope="module")
def _database() -> Iterator[sessionmaker[Session]]:
    with throwaway_database() as factory:
        yield factory


@pytest.fixture
def pg_sessionmaker(_database: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    ensure_billing_settings(_database)  # grace is the admin setting; the teardown truncates it
    yield from emptied_after(_database)
    with _database.begin() as session:
        session.execute(sa.text("TRUNCATE paymob_events CASCADE"))


# -- seeding and reading ----------------------------------------------------------------


def _linked(
    sm: sessionmaker[Session], pid: int | None = PID, **kwargs: Any
) -> tuple[uuid.UUID, uuid.UUID]:
    """``(student, subscription)``: a plan linked to Paymob, 100.00 a period, ending ``END``."""
    student = seed_user(sm, Role.student)
    options: dict[str, Any] = {
        "payer_id": student,
        "paymob_subscription_id": pid,
        "paymob_amount_minor": 10_000,
        "activated_at": T0,
    } | kwargs
    tier_id = options.pop("tier_id", None) or seed_tier(sm, allowance_units=1_000)
    return student, seed_subscription(sm, user_id=student, tier_id=tier_id, **options)


def _client(
    state: str = "active",
    pid: int = PID,
    updated_at: str = "t1",
    *,
    last: Literal["initial", "declined", "fresh"] = "initial",
) -> FakePaymobClient:
    """A Paymob whose ``last-transaction`` is, by default, the OLD first-payment success.

    That is the realistic case a failure trigger meets (a declined attempt may leave nothing
    newer), and the one a default of "a declined charge" would hide. ``declined`` scripts a failed
    last charge, ``fresh`` a new success.
    """
    client = FakePaymobClient()
    client.subscriptions[pid] = remote_subscription(pid, state=state, updated_at=updated_at)
    if last == "initial":
        client.last_transactions[pid] = charge(INITIAL_TXN, 10_000, created_at=T0)
    elif last == "declined":
        client.last_transactions[pid] = charge(900 + pid, 10_000, success=False, created_at=END)
    else:
        client.last_transactions[pid] = charge(
            950 + pid, 10_000, created_at=END - timedelta(hours=3)
        )
    return client


def _deliver(
    sm: sessionmaker[Session],
    client: FakePaymobClient,
    trigger: str,
    now: datetime,
    pid: int = PID,
) -> None:
    with sm.begin() as session:
        SubscriptionService(session, client, paymob_settings()).apply_renewal_webhook(
            subscription_webhook(trigger, pid), now=now
        )


def _sub(sm: sessionmaker[Session], sid: uuid.UUID) -> Subscription:
    with sm() as session:
        row = session.get(Subscription, sid)
        assert row is not None
        return row


def _notices(sm: sessionmaker[Session]) -> list[tuple[str, datetime]]:
    with sm() as session:
        rows = session.scalars(sa.select(EmailOutbox).order_by(EmailOutbox.created_at)).all()
        return [
            (str(r.context["notice"]), datetime.fromisoformat(str(r.context["effective_at"])))
            for r in rows
        ]


def _notice_names(sm: sessionmaker[Session]) -> list[str]:
    return [name for name, _ in _notices(sm)]


def _alerts(logs: Sequence[Mapping[str, Any]]) -> list[str]:
    return [str(entry["event"]) for entry in logs if entry.get("alert") is True]


def _service(session: Session, client: FakePaymobClient | None = None) -> SubscriptionService:
    return SubscriptionService(session, client or _client(), paymob_settings())


def _sweep(
    sm: sessionmaker[Session],
    now: datetime,
    client: FakePaymobClient | None = None,
    **kwargs: Any,
) -> int:
    with sm() as session:
        return _service(session, client).expire_overdue(now=now, **kwargs)


def _past_due(sm: sessionmaker[Session], pid: int | None, grace: datetime) -> uuid.UUID:
    return _linked(sm, pid, status=SubscriptionStatus.past_due, grace_until=grace)[1]


def _period_grant(
    sm: sessionmaker[Session], owner: uuid.UUID, sid: uuid.UUID, units: int = 500
) -> uuid.UUID:
    """The current period (``T0`` to ``END``) and its allowance grant, as a renewal writes them."""
    period_id = uuid.uuid4()
    with sm.begin() as session:
        session.add(
            SubscriptionPeriod(id=period_id, subscription_id=sid, period_start=T0, period_end=END)
        )
        session.flush()
        return (
            UsageLedger(session)
            .issue_grant(
                owner_user_id=owner,
                kind=GrantKind.period_allowance,
                units=units,
                idempotency_key=f"period:{period_id}",
                expires_at=END,
                visible=False,
                effective_at=T0,
                subscription_period_id=period_id,
            )
            .id
        )


def _usable(sm: sessionmaker[Session], owner: uuid.UUID, at: datetime) -> int:
    chain = [Payer(owner_user_id=owner, scope=GrantScope.ALLOWANCE)]
    with sm() as session:
        return UsageLedger(session).available(chain, now=at)


def _grant_state(sm: sessionmaker[Session], gid: uuid.UUID) -> tuple[Any, int, int]:
    with sm() as session:
        grant = session.get(UsageGrant, gid)
        bal = session.get(UsageGrantBalance, gid)
        entries = session.scalar(
            sa.select(sa.func.count()).select_from(UsageEntry).where(UsageEntry.grant_id == gid)
        )
        assert grant is not None
        assert bal is not None
        return grant.expires_at, bal.remaining, int(entries or 0)


# -- grace ------------------------------------------------------------------------------


def test_failed_renewal_starts_three_days_of_grace(pg_sessionmaker: sessionmaker[Session]) -> None:
    _, sid = _linked(pg_sessionmaker)
    failed_at = END + timedelta(hours=1)
    _deliver(pg_sessionmaker, _client(), TRIGGER_FAILED, failed_at)
    sub = _sub(pg_sessionmaker, sid)
    assert (sub.status, sub.grace_until) == (SubscriptionStatus.past_due, failed_at + GRACE)
    # One notice, naming the stored deadline (never a now()-derived value).
    assert _notices(pg_sessionmaker) == [("payment_failed", failed_at + GRACE)]


def test_a_retry_failure_does_not_extend_grace(pg_sessionmaker: sessionmaker[Session]) -> None:
    _, sid = _linked(pg_sessionmaker)
    first = END + timedelta(hours=1)
    _deliver(pg_sessionmaker, _client(updated_at="t1"), TRIGGER_FAILED, first)
    # Paymob's retry fails a day later: a distinct delivery (new remote stamp), same trigger.
    _deliver(pg_sessionmaker, _client(updated_at="t2"), TRIGGER_FAILED, first + timedelta(days=1))
    assert _sub(pg_sessionmaker, sid).grace_until == first + GRACE
    assert _notice_names(pg_sessionmaker) == ["payment_failed"]


def test_mark_past_due_by_id(pg_sessionmaker: sessionmaker[Session]) -> None:
    _, sid = _linked(pg_sessionmaker)
    with pg_sessionmaker.begin() as session:
        marked = _service(session).mark_past_due(sid, now=END)
        assert marked.status is SubscriptionStatus.past_due
    assert _sub(pg_sessionmaker, sid).grace_until == END + GRACE
    assert _notice_names(pg_sessionmaker) == ["payment_failed"]


def test_mark_past_due_of_an_unknown_subscription_raises(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    with pytest.raises(SubscriptionNotFound), pg_sessionmaker.begin() as session:
        _service(session).mark_past_due(uuid.uuid4(), now=END)


def test_a_failure_on_an_expired_or_cancelled_plan_changes_nothing(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    _, expired = _linked(pg_sessionmaker, 1, status=SubscriptionStatus.expired)
    _, cancelled = _linked(pg_sessionmaker, 2, status=SubscriptionStatus.cancelled)
    _deliver(pg_sessionmaker, _client(pid=1), TRIGGER_FAILED, END, pid=1)
    _deliver(pg_sessionmaker, _client(pid=2), TRIGGER_FAILED, END, pid=2)
    assert _sub(pg_sessionmaker, expired).status is SubscriptionStatus.expired
    assert _sub(pg_sessionmaker, cancelled).status is SubscriptionStatus.cancelled
    assert _notices(pg_sessionmaker) == []


# -- UD-1 (b): the expiring allowance stays usable until the grace date ------------------


def test_the_expiring_allowance_is_usable_until_the_grace_date_and_not_after(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    owner, sid = _linked(pg_sessionmaker)
    gid = _period_grant(pg_sessionmaker, owner, sid, units=500)
    failed_at = END - timedelta(hours=2)  # Paymob charged a little early and was declined
    grace = failed_at + GRACE
    before = _grant_state(pg_sessionmaker, gid)
    assert _usable(pg_sessionmaker, owner, END + timedelta(hours=1)) == 0  # as written: lapsed

    _deliver(pg_sessionmaker, _client(), TRIGGER_FAILED, failed_at)

    expires_at, remaining, entries = _grant_state(pg_sessionmaker, gid)
    assert (expires_at, remaining, entries) == (grace, before[1], before[2])  # no units, no entry
    assert _usable(pg_sessionmaker, owner, END + timedelta(hours=1)) == 500
    assert _usable(pg_sessionmaker, owner, grace - timedelta(seconds=1)) == 500
    assert _usable(pg_sessionmaker, owner, grace) == 0


def test_a_failure_after_the_period_end_but_before_the_sweep_gets_the_leftover_back(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    owner, sid = _linked(pg_sessionmaker)
    gid = _period_grant(pg_sessionmaker, owner, sid, units=500)
    failed_at = END + timedelta(hours=1)  # Paymob charges at the period end: this is the usual case
    grace = failed_at + GRACE
    assert _usable(pg_sessionmaker, owner, failed_at) == 0  # lapsed, not yet swept
    with capture_logs() as logs:
        _deliver(pg_sessionmaker, _client(), TRIGGER_FAILED, failed_at)
    assert _grant_state(pg_sessionmaker, gid) == (grace, 500, 1)  # no new units, no new entry
    assert _usable(pg_sessionmaker, owner, failed_at) == 500
    assert _usable(pg_sessionmaker, owner, grace - timedelta(seconds=1)) == 500
    assert _usable(pg_sessionmaker, owner, grace) == 0
    assert _alerts(logs) == []


def test_a_failure_after_the_expiry_sweep_does_not_reopen_the_allowance(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    owner, sid = _linked(pg_sessionmaker)
    gid = _period_grant(pg_sessionmaker, owner, sid, units=500)
    failed_at = END + timedelta(hours=1)
    with pg_sessionmaker.begin() as session:
        assert UsageLedger(session).expire_grants(now=END + timedelta(minutes=1)) == 1
    with capture_logs() as logs:
        _deliver(pg_sessionmaker, _client(), TRIGGER_FAILED, failed_at)
    assert _sub(pg_sessionmaker, sid).status is SubscriptionStatus.past_due
    assert _grant_state(pg_sessionmaker, gid)[0] == END
    assert _usable(pg_sessionmaker, owner, failed_at) == 0
    assert _alerts(logs) == []  # the normal path: an info log, not a page
    assert any(e["event"] == "subscription_grace_extension_skipped" for e in logs)


def test_only_the_current_periods_grants_are_extended(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    owner, sid = _linked(pg_sessionmaker)
    current = _period_grant(pg_sessionmaker, owner, sid)
    with pg_sessionmaker.begin() as session:
        older = uuid.uuid4()
        session.add(
            SubscriptionPeriod(
                id=older,
                subscription_id=sid,
                period_start=T0 - timedelta(days=30),
                period_end=T0,
            )
        )
        session.flush()
        older_grant = UsageLedger(session).issue_grant(
            owner_user_id=owner,
            kind=GrantKind.period_allowance,
            units=20,
            idempotency_key=f"period:{older}",
            expires_at=END,  # an earlier period's leftover that still runs: not this period's
            visible=False,
            effective_at=T0 - timedelta(days=30),
            subscription_period_id=older,
        )
        older_id = older_grant.id
        other = UsageLedger(session).issue_grant(
            owner_user_id=owner,
            kind=GrantKind.credit_pack,
            units=10,
            idempotency_key="pack:keep",
            expires_at=END + timedelta(days=1),
            visible=True,
            effective_at=T0,
        )
        other_id = other.id
    _deliver(pg_sessionmaker, _client(), TRIGGER_FAILED, END - timedelta(hours=2))
    assert _grant_state(pg_sessionmaker, current)[0] == END - timedelta(hours=2) + GRACE
    assert _grant_state(pg_sessionmaker, other_id)[0] == END + timedelta(days=1)
    assert _grant_state(pg_sessionmaker, older_id)[0] == END


def test_a_failing_grant_extension_does_not_stop_the_plan_going_past_due(
    pg_sessionmaker: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, sid = _linked(pg_sessionmaker)
    _period_grant(pg_sessionmaker, owner, sid)

    def boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("ledger down")

    monkeypatch.setattr(UsageLedger, "extend_grant_expiry", boom)
    with capture_logs() as logs:
        _deliver(pg_sessionmaker, _client(), TRIGGER_FAILED, END - timedelta(hours=2))
    assert _sub(pg_sessionmaker, sid).status is SubscriptionStatus.past_due
    assert _alerts(logs) == ["subscription_grace_extension_failed"]


# -- C-1: a failure trigger for a renewal that was already paid is ignored ---------------


def test_a_late_failure_after_a_paid_renewal_is_ignored(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    # T0..END was just paid; Paymob redelivers the day-0 failure an hour later.
    _, sid = _linked(pg_sessionmaker)
    with capture_logs() as logs:
        _deliver(
            pg_sessionmaker, _client(updated_at="after"), TRIGGER_FAILED, T0 + timedelta(hours=1)
        )
    sub = _sub(pg_sessionmaker, sid)
    assert (sub.status, sub.grace_until) == (SubscriptionStatus.active, None)
    assert _notices(pg_sessionmaker) == []
    ignored = [e for e in logs if e["event"] == "subscription_stale_failure_ignored"]
    assert [e["reason"] for e in ignored] == ["period_already_paid"]
    # and the sweeps never touch it
    client = _client()
    assert _sweep(pg_sessionmaker, T0 + timedelta(hours=1) + GRACE, client) == 0
    assert client.names() == []


def test_a_late_overdue_on_a_paid_plan_is_ignored(pg_sessionmaker: sessionmaker[Session]) -> None:
    _, sid = _linked(pg_sessionmaker)
    client = _client(updated_at="x")
    _deliver(pg_sessionmaker, client, TRIGGER_OVERDUE, T0 + timedelta(hours=1))
    assert _sub(pg_sessionmaker, sid).status is SubscriptionStatus.active
    assert _notices(pg_sessionmaker) == []


def test_a_failure_replayed_after_a_successful_charge_is_ignored_even_near_the_period_end(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    _, sid = _linked(pg_sessionmaker)
    client = _client(last="fresh")  # a new success Lemely has not recorded: no failure is open
    with capture_logs() as logs:
        _deliver(pg_sessionmaker, client, TRIGGER_FAILED, END - timedelta(hours=2))
    assert _sub(pg_sessionmaker, sid).status is SubscriptionStatus.active
    assert [e["reason"] for e in logs if e["event"] == "subscription_stale_failure_ignored"] == [
        "last_charge_succeeded"
    ]


def test_an_unreadable_last_charge_falls_back_to_the_period_alone(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    _, sid = _linked(pg_sessionmaker)
    client = _client()
    client.fail["last_transaction"] = PaymobError("down", status_code=503)
    with capture_logs() as logs:
        _deliver(pg_sessionmaker, client, TRIGGER_FAILED, END - timedelta(hours=2))
    assert _sub(pg_sessionmaker, sid).status is SubscriptionStatus.past_due
    assert any(e["event"] == "subscription_failure_unconfirmed" for e in logs)


def test_an_old_success_as_the_last_charge_does_not_hide_a_genuine_failure(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """``last-transaction`` returned Paymob's first payment: the renewal still failed."""
    _, sid = _linked(pg_sessionmaker)
    _deliver(pg_sessionmaker, _client(updated_at="f1"), TRIGGER_FAILED, END + timedelta(hours=1))
    assert _sub(pg_sessionmaker, sid).status is SubscriptionStatus.past_due
    _deliver(pg_sessionmaker, _client(updated_at="o1"), TRIGGER_OVERDUE, END + timedelta(days=3))
    assert _sub(pg_sessionmaker, sid).status is SubscriptionStatus.expired


def test_a_declined_last_charge_is_a_genuine_failure(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    _, sid = _linked(pg_sessionmaker)
    _deliver(pg_sessionmaker, _client(last="declined"), TRIGGER_FAILED, END + timedelta(hours=1))
    assert _sub(pg_sessionmaker, sid).status is SubscriptionStatus.past_due


def test_a_charge_already_recorded_as_a_renewal_does_not_confirm_payment(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """The charge that paid the current period is Paymob's last one: the next failure stands."""
    _, sid = _linked(pg_sessionmaker)
    paid_at = END - timedelta(hours=2)
    paid = _client(updated_at="p")
    paid.last_transactions[PID] = charge(888, 10_000, created_at=paid_at)
    _deliver(pg_sessionmaker, paid, TRIGGER_SUCCESS, paid_at)
    new_end = _sub(pg_sessionmaker, sid).current_period_end
    assert new_end is not None and new_end > END
    failing = _client(updated_at="f")
    failing.last_transactions[PID] = charge(888, 10_000, created_at=paid_at)  # still the old one
    failed_at = new_end - timedelta(hours=2)
    _deliver(pg_sessionmaker, failing, TRIGGER_FAILED, failed_at)
    assert _sub(pg_sessionmaker, sid).status is SubscriptionStatus.past_due


def test_a_success_older_than_the_last_payment_does_not_confirm_payment(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    _, sid = _linked(pg_sessionmaker)
    paid_at = END - timedelta(hours=2)
    paid = _client(updated_at="p")
    paid.last_transactions[PID] = charge(888, 10_000, created_at=paid_at)
    _deliver(pg_sessionmaker, paid, TRIGGER_SUCCESS, paid_at)
    new_end = _sub(pg_sessionmaker, sid).current_period_end
    assert new_end is not None
    failing = _client(updated_at="f")
    failing.last_transactions[PID] = charge(999, 10_000, created_at=paid_at - timedelta(days=1))
    _deliver(pg_sessionmaker, failing, TRIGGER_FAILED, new_end - timedelta(hours=2))
    assert _sub(pg_sessionmaker, sid).status is SubscriptionStatus.past_due


def test_the_initial_transaction_never_confirms_payment_whatever_its_stamp(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    _, sid = _linked(pg_sessionmaker)
    client = _client()
    # Paymob's own initial transaction, stamped (by skew) after the period started.
    client.last_transactions[PID] = charge(INITIAL_TXN, 10_000, created_at=END - timedelta(hours=3))
    _deliver(pg_sessionmaker, client, TRIGGER_FAILED, END - timedelta(hours=2))
    assert _sub(pg_sessionmaker, sid).status is SubscriptionStatus.past_due


def test_a_recorded_charge_never_confirms_payment_whatever_its_stamp(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    _, sid = _linked(pg_sessionmaker)
    paid_at = END - timedelta(hours=2)
    paid = _client(updated_at="p")
    paid.last_transactions[PID] = charge(888, 10_000, created_at=paid_at)
    _deliver(pg_sessionmaker, paid, TRIGGER_SUCCESS, paid_at)
    new_end = _sub(pg_sessionmaker, sid).current_period_end
    assert new_end is not None
    failing = _client(updated_at="f")
    # The recorded charge 888 again, stamped after its own payment time (skew).
    failing.last_transactions[PID] = charge(888, 10_000, created_at=paid_at + timedelta(hours=1))
    _deliver(pg_sessionmaker, failing, TRIGGER_FAILED, new_end - timedelta(hours=2))
    assert _sub(pg_sessionmaker, sid).status is SubscriptionStatus.past_due


def test_a_failure_a_retry_cycle_before_the_period_end_is_still_honoured(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """A late-paid renewal can leave Paymob ``MAX_GRACE_DAYS`` ahead of our period end."""
    _, honoured = _linked(pg_sessionmaker, 1)
    _, ignored = _linked(pg_sessionmaker, 2)
    ahead = timedelta(days=MAX_GRACE_DAYS)
    _deliver(pg_sessionmaker, _client(pid=1), TRIGGER_FAILED, END - ahead, 1)
    _deliver(pg_sessionmaker, _client(pid=2), TRIGGER_FAILED, END - ahead - timedelta(days=1), 2)
    assert _sub(pg_sessionmaker, honoured).status is SubscriptionStatus.past_due
    assert _sub(pg_sessionmaker, ignored).status is SubscriptionStatus.active


def test_the_period_alone_ignores_a_failure_only_beyond_the_early_charge_window(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """A renewal paid late may leave Paymob's schedule days ahead of ours: only farther is paid."""
    _, inside = _linked(pg_sessionmaker, 1)
    _, beyond = _linked(pg_sessionmaker, 2)
    window = EARLY_CHARGE_WINDOW
    _deliver(pg_sessionmaker, _client(pid=1), TRIGGER_FAILED, END - window + timedelta(hours=1), 1)
    _deliver(pg_sessionmaker, _client(pid=2), TRIGGER_FAILED, END - window - timedelta(hours=1), 2)
    assert _sub(pg_sessionmaker, inside).status is SubscriptionStatus.past_due
    assert _sub(pg_sessionmaker, beyond).status is SubscriptionStatus.active


# -- I-1: a resume never clears a grace a failed charge started ----------------------


def test_resume_does_not_clear_a_grace_a_failed_charge_started(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    _, sid = _linked(pg_sessionmaker)
    first = END - timedelta(hours=2)  # Paymob charged early and was declined
    _deliver(pg_sessionmaker, _client(updated_at="f1"), TRIGGER_FAILED, first)
    _deliver(
        pg_sessionmaker,
        _client(updated_at="r1"),
        TRIGGER_RESUMED,
        END - timedelta(hours=1),
    )
    sub = _sub(pg_sessionmaker, sid)
    assert (sub.status, sub.grace_until) == (SubscriptionStatus.past_due, first + GRACE)
    # Paymob's retry fails: the first deadline stands.
    _deliver(pg_sessionmaker, _client(updated_at="f2"), TRIGGER_FAILED, END + timedelta(days=2))
    assert _sub(pg_sessionmaker, sid).grace_until == first + GRACE


# -- M-1, M-2: the extended leftover does not outlive the plan or stack on a renewal -----


def test_a_renewal_paid_during_grace_ends_the_extended_leftover(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    owner, sid = _linked(pg_sessionmaker)
    old = _period_grant(pg_sessionmaker, owner, sid, units=500)
    failed_at = END - timedelta(hours=2)
    _deliver(pg_sessionmaker, _client(), TRIGGER_FAILED, failed_at)
    assert _grant_state(pg_sessionmaker, old)[0] == failed_at + GRACE
    paid_at = END + timedelta(days=1)
    client = _client()
    client.last_transactions[PID] = charge(888, 10_000, created_at=paid_at)
    _deliver(pg_sessionmaker, client, TRIGGER_SUCCESS, paid_at)
    assert _sub(pg_sessionmaker, sid).status is SubscriptionStatus.active
    assert _grant_state(pg_sessionmaker, old)[0] == paid_at  # ended at the reactivation
    # Only the new period's 1 000 units are usable, not 1 000 plus the old leftover.
    assert _usable(pg_sessionmaker, owner, paid_at + timedelta(hours=1)) == 1_000


def test_an_overdue_expiry_before_the_grace_date_ends_the_extended_leftover(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    owner, sid = _linked(pg_sessionmaker)
    old = _period_grant(pg_sessionmaker, owner, sid, units=500)
    _deliver(pg_sessionmaker, _client(updated_at="f"), TRIGGER_FAILED, END - timedelta(hours=2))
    gave_up = END + timedelta(days=1)
    _deliver(pg_sessionmaker, _client(updated_at="o"), TRIGGER_OVERDUE, gave_up)
    assert _sub(pg_sessionmaker, sid).status is SubscriptionStatus.expired
    assert _grant_state(pg_sessionmaker, old)[0] == gave_up
    assert _usable(pg_sessionmaker, owner, gave_up + timedelta(minutes=1)) == 0
    assert ("expired", gave_up) in _notices(pg_sessionmaker)


# -- expiry -----------------------------------------------------------------------------


def test_expire_overdue_waits_for_grace_then_expires_and_cancels_paymob(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    grace = END + GRACE
    sid = _past_due(pg_sessionmaker, PID, grace)
    client = _client()
    assert _sweep(pg_sessionmaker, grace - timedelta(minutes=1), client) == 0
    assert _sub(pg_sessionmaker, sid).status is SubscriptionStatus.past_due
    assert client.names() == []
    assert _sweep(pg_sessionmaker, grace + timedelta(minutes=5), client) == 1
    sub = _sub(pg_sessionmaker, sid)
    assert (sub.status, sub.grace_until, sub.paymob_cancelled_at) == (
        SubscriptionStatus.expired,
        None,
        grace + timedelta(minutes=5),
    )
    assert client.names() == ["cancel_subscription"]
    assert _notices(pg_sessionmaker) == [("expired", grace)]  # the stored deadline


def test_expiry_survives_a_failed_paymob_cancel(pg_sessionmaker: sessionmaker[Session]) -> None:
    grace = END + GRACE
    sid = _past_due(pg_sessionmaker, PID, grace)
    client = _client()
    client.fail["cancel_subscription"] = PaymobError("boom", status_code=500)
    with capture_logs() as logs:
        assert _sweep(pg_sessionmaker, grace, client) == 1
    sub = _sub(pg_sessionmaker, sid)
    assert (sub.status, sub.paymob_cancelled_at) == (SubscriptionStatus.expired, None)
    assert any(e["event"] == "paymob_cancel_failed" for e in logs)


def test_failed_overdue_trigger_expires_at_once_with_no_paymob_write(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    grace = END + GRACE
    sid = _past_due(pg_sessionmaker, PID, grace)
    client = _client()
    _deliver(pg_sessionmaker, client, TRIGGER_OVERDUE, END + timedelta(days=1))
    sub = _sub(pg_sessionmaker, sid)
    assert (sub.status, sub.grace_until, sub.paymob_cancelled_at) == (
        SubscriptionStatus.expired,
        None,
        None,
    )
    assert "cancel_subscription" not in client.names()  # DV-15: no write in the webhook txn
    # Paymob gave up before the grace date: the notice names the day the plan ended.
    assert _notices(pg_sessionmaker) == [("expired", END + timedelta(days=1))]


def test_a_failed_overdue_for_a_plan_already_ended_changes_nothing(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    _, sid = _linked(pg_sessionmaker, status=SubscriptionStatus.cancelled)
    _deliver(pg_sessionmaker, _client(), TRIGGER_OVERDUE, END)
    assert _sub(pg_sessionmaker, sid).status is SubscriptionStatus.cancelled
    assert _notices(pg_sessionmaker) == []


def test_the_sweep_retries_nothing_for_an_already_expired_row(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sid = _past_due(pg_sessionmaker, PID, END + GRACE)
    client = _client()
    assert _sweep(pg_sessionmaker, END + GRACE, client) == 1
    assert _sweep(pg_sessionmaker, END + GRACE + timedelta(hours=1), client) == 0
    assert client.names() == ["cancel_subscription"]
    assert _notice_names(pg_sessionmaker) == ["expired"]
    assert _sub(pg_sessionmaker, sid).status is SubscriptionStatus.expired


def test_a_4xx_cancel_for_a_subscription_paymob_already_cancelled_is_stamped(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    grace = END + GRACE
    sid = _past_due(pg_sessionmaker, PID, grace)
    client = _client(state="canceled")
    client.fail["cancel_subscription"] = PaymobError("gone", status_code=409)
    assert _sweep(pg_sessionmaker, grace, client) == 1
    assert _sub(pg_sessionmaker, sid).paymob_cancelled_at == grace
    assert client.names() == ["cancel_subscription", "get_subscription"]


def test_a_4xx_cancel_that_paymob_refuses_is_not_stamped_and_alerts(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    grace = END + GRACE
    sid = _past_due(pg_sessionmaker, PID, grace)
    client = _client(state="active")
    client.fail["cancel_subscription"] = PaymobError("refused", status_code=400)
    with capture_logs() as logs:
        assert _sweep(pg_sessionmaker, grace, client) == 1
    sub = _sub(pg_sessionmaker, sid)
    assert (sub.status, sub.paymob_cancelled_at) == (SubscriptionStatus.expired, None)
    assert _alerts(logs) == ["paymob_cancel_refused"]


@pytest.mark.parametrize(
    "error",
    [
        PaymobError("timeout", timeout=True),
        PaymobError("transport"),
        PaymobError("server", status_code=502),
        PaymobError("odd", status_code=400, outcome_unknown=True),
    ],
)
def test_an_unknown_cancel_outcome_is_not_stamped_and_not_read_back(
    pg_sessionmaker: sessionmaker[Session], error: PaymobError
) -> None:
    grace = END + GRACE
    sid = _past_due(pg_sessionmaker, PID, grace)
    client = _client(state="canceled")  # a read would say "cancelled": it must not be asked
    client.fail["cancel_subscription"] = error
    assert _sweep(pg_sessionmaker, grace, client) == 1
    assert _sub(pg_sessionmaker, sid).paymob_cancelled_at is None
    assert client.names() == ["cancel_subscription"]


def test_a_4xx_cancel_whose_read_back_fails_is_not_stamped(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    grace = END + GRACE
    sid = _past_due(pg_sessionmaker, PID, grace)
    client = _client(state="canceled")
    client.fail["cancel_subscription"] = PaymobError("gone", status_code=404)
    client.fail["get_subscription"] = PaymobError("down", status_code=503)
    assert _sweep(pg_sessionmaker, grace, client) == 1
    assert _sub(pg_sessionmaker, sid).paymob_cancelled_at is None


def test_a_subscription_paymob_no_longer_has_is_alerted_and_stops_being_retried(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    grace = END + GRACE
    sid = _past_due(pg_sessionmaker, PID, grace)
    client = _client()
    client.fail["cancel_subscription"] = PaymobError("not found", status_code=404)
    client.fail["get_subscription"] = PaymobError("not found", status_code=404)
    with capture_logs() as logs:
        assert _sweep(pg_sessionmaker, grace, client) == 1
    assert _sub(pg_sessionmaker, sid).paymob_cancelled_at == grace  # marked: no retry loop
    assert _alerts(logs) == ["subscription_paymob_missing"]


# -- sweep shape ------------------------------------------------------------------------


def test_complimentary_and_not_yet_due_rows_are_never_selected(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    grace = END + GRACE
    complimentary = _past_due(pg_sessionmaker, None, grace)  # no Paymob link (R15)
    waiting = _past_due(pg_sessionmaker, 2, grace + timedelta(days=1))
    active = _linked(pg_sessionmaker, 3, grace_until=grace)[1]  # not past_due
    client = _client()
    assert _sweep(pg_sessionmaker, grace, client) == 0
    assert client.names() == []
    for sid, status in (
        (complimentary, SubscriptionStatus.past_due),
        (waiting, SubscriptionStatus.past_due),
        (active, SubscriptionStatus.active),
    ):
        assert _sub(pg_sessionmaker, sid).status is status


def test_a_sweep_processes_at_most_limit_rows_oldest_deadline_first(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    older = _past_due(pg_sessionmaker, 1, END + GRACE)
    newer = _past_due(pg_sessionmaker, 2, END + GRACE + timedelta(hours=1))
    now = END + GRACE + timedelta(days=1)
    assert _sweep(pg_sessionmaker, now, limit=1) == 1
    assert _sub(pg_sessionmaker, older).status is SubscriptionStatus.expired
    assert _sub(pg_sessionmaker, newer).status is SubscriptionStatus.past_due
    assert _sweep(pg_sessionmaker, now, limit=1) == 1
    assert _sub(pg_sessionmaker, newer).status is SubscriptionStatus.expired


def test_the_default_sweep_batch_is_bounded() -> None:
    assert SUBSCRIPTION_SWEEP_BATCH == 200


def test_a_sweep_limit_below_one_is_refused(pg_sessionmaker: sessionmaker[Session]) -> None:
    with pytest.raises(ValueError, match="limit"):
        _sweep(pg_sessionmaker, END, limit=0)


def test_one_failing_subscription_does_not_block_the_others(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    grace = END + GRACE
    bad = _past_due(pg_sessionmaker, 1, grace)
    good = _past_due(pg_sessionmaker, 2, grace + timedelta(minutes=1))
    client = FakePaymobClient()
    client.fail_for[("cancel_subscription", 1)] = RuntimeError("not a PaymobError")
    with capture_logs() as logs:
        assert _sweep(pg_sessionmaker, grace + timedelta(hours=1), client) == 1
    # The failing row rolled back alone (still past_due, no notice); the other went through.
    assert _sub(pg_sessionmaker, bad).status is SubscriptionStatus.past_due
    good_row = _sub(pg_sessionmaker, good)
    assert good_row.status is SubscriptionStatus.expired
    assert good_row.paymob_cancelled_at is not None
    assert _notice_names(pg_sessionmaker) == ["expired"]
    [failure] = [e for e in logs if e["event"] == "subscription_sweep_failed"]
    assert failure["alert"] is True
    assert failure["subscription_id"] == str(bad)
    assert failure["error"] == "RuntimeError"
    assert "boom" not in repr(failure)


def test_a_sweep_skips_a_row_another_session_holds_without_waiting(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    grace = END + GRACE
    held = _past_due(pg_sessionmaker, 1, grace)
    free = _past_due(pg_sessionmaker, 2, grace + timedelta(minutes=1))
    holder = pg_sessionmaker()
    try:
        holder.execute(
            sa.select(Subscription.id).where(Subscription.id == held).with_for_update()
        ).all()
        sweeper = pg_sessionmaker()
        try:
            sweeper.execute(sa.text("SET lock_timeout = '2s'"))  # a plain FOR UPDATE fails fast
            started = time.monotonic()
            with capture_logs() as logs:
                done = _service(sweeper).expire_overdue(now=grace + timedelta(hours=1))
            elapsed = time.monotonic() - started
            sweeper.execute(sa.text("RESET lock_timeout"))
            sweeper.commit()
        finally:
            sweeper.close()
    finally:
        holder.rollback()
        holder.close()
    assert done == 1
    assert elapsed < 1.5
    assert "subscription_sweep_failed" not in [e["event"] for e in logs]
    assert _sub(pg_sessionmaker, held).status is SubscriptionStatus.past_due
    assert _sub(pg_sessionmaker, free).status is SubscriptionStatus.expired


def test_a_row_renewed_between_the_selection_and_the_lock_is_not_expired(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    _, sid = _linked(pg_sessionmaker)  # active again: a renewal landed after the id was read
    with pg_sessionmaker() as session:
        service = _service(session)
        assert service._sweep_one(sid, service._expire_if_due, END + GRACE) == 0
    assert _sub(pg_sessionmaker, sid).status is SubscriptionStatus.active


@pytest.mark.parametrize(
    ("status", "pid", "grace"),
    [
        (SubscriptionStatus.active, PID, END + GRACE),  # status re-checked under the lock
        (SubscriptionStatus.expired, PID, END + GRACE),
        (SubscriptionStatus.past_due, PID, END + GRACE + timedelta(days=1)),  # grace moved later
        (SubscriptionStatus.past_due, None, END + GRACE),  # complimentary
    ],
)
def test_the_expiry_condition_is_re_checked_under_the_lock(
    pg_sessionmaker: sessionmaker[Session],
    status: SubscriptionStatus,
    pid: int | None,
    grace: datetime,
) -> None:
    _, sid = _linked(pg_sessionmaker, pid, status=status, grace_until=grace)
    with pg_sessionmaker() as session:
        service = _service(session)
        assert service._sweep_one(sid, service._expire_if_due, END + GRACE) == 0
    assert _sub(pg_sessionmaker, sid).status is status
    assert _notices(pg_sessionmaker) == []


def test_sweep_one_of_a_missing_row_counts_nothing(pg_sessionmaker: sessionmaker[Session]) -> None:
    with pg_sessionmaker() as session:
        service = _service(session)
        assert service._sweep_one(uuid.uuid4(), service._expire_if_due, END) == 0


def test_lock_raises_for_an_unknown_row_and_lock_for_sweep_returns_none(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    with pg_sessionmaker() as session:
        service = _service(session)
        with pytest.raises(SubscriptionNotFound):
            service._lock(uuid.uuid4())
        assert service._lock_for_sweep(uuid.uuid4()) is None


# -- mirrored Paymob states -------------------------------------------------------------


def test_paymob_cancel_of_our_period_end_cancel_keeps_access(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    _, sid = _linked(pg_sessionmaker, cancel_at_period_end=True)
    now = END - timedelta(days=5)
    _deliver(pg_sessionmaker, _client(state="canceled"), TRIGGER_CANCELED, now)
    sub = _sub(pg_sessionmaker, sid)
    assert (sub.status, sub.cancel_at_period_end, sub.paymob_cancelled_at) == (
        SubscriptionStatus.active,
        True,
        now,
    )
    assert _notices(pg_sessionmaker) == []


def test_an_external_paymob_cancel_means_cancel_at_period_end(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student = seed_user(pg_sessionmaker, Role.student)
    other_tier = seed_tier(pg_sessionmaker, allowance_units=2_000)
    sid = seed_subscription(
        pg_sessionmaker,
        user_id=student,
        tier_id=seed_tier(pg_sessionmaker, allowance_units=1_000),
        payer_id=student,
        paymob_subscription_id=PID,
        paymob_amount_minor=10_000,
        pending_plan_tier_id=other_tier,
    )
    now = END - timedelta(days=5)
    client = _client(state="canceled")
    _deliver(pg_sessionmaker, client, TRIGGER_CANCELED, now)
    sub = _sub(pg_sessionmaker, sid)
    assert sub.status is SubscriptionStatus.active  # access runs to the period end
    assert sub.cancel_at_period_end is True
    assert sub.paymob_cancelled_at == now
    assert sub.pending_plan_tier_id is None  # a downgrade can no longer apply
    assert sub.current_period_end == END
    assert "cancel_subscription" not in client.names()  # Paymob already did it
    assert _notices(pg_sessionmaker) == []  # the period-end sweep sends the past-tense notice


def test_an_external_cancel_delivered_twice_changes_nothing_the_second_time(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    _, sid = _linked(pg_sessionmaker)
    first = END - timedelta(days=5)
    _deliver(pg_sessionmaker, _client(state="canceled", updated_at="a"), TRIGGER_CANCELED, first)
    version = _sub(pg_sessionmaker, sid).version
    _deliver(
        pg_sessionmaker,
        _client(state="canceled", updated_at="b"),
        TRIGGER_CANCELED,
        first + timedelta(days=1),
    )
    sub = _sub(pg_sessionmaker, sid)
    assert (sub.version, sub.paymob_cancelled_at) == (version, first)


def test_an_external_cancel_of_a_past_due_plan_keeps_it_past_due_until_grace_ends(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    grace = END + GRACE
    sid = _past_due(pg_sessionmaker, PID, grace)
    _deliver(pg_sessionmaker, _client(state="canceled"), TRIGGER_CANCELED, END + timedelta(days=1))
    sub = _sub(pg_sessionmaker, sid)
    assert (sub.status, sub.cancel_at_period_end, sub.grace_until) == (
        SubscriptionStatus.past_due,
        True,
        grace,
    )


def test_a_cancel_of_an_ended_plan_only_stamps_the_paymob_cancel(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    _, sid = _linked(pg_sessionmaker, status=SubscriptionStatus.expired)
    now = END + timedelta(days=4)
    _deliver(pg_sessionmaker, _client(state="canceled"), TRIGGER_CANCELED, now)
    sub = _sub(pg_sessionmaker, sid)
    assert (sub.status, sub.cancel_at_period_end, sub.paymob_cancelled_at) == (
        SubscriptionStatus.expired,
        False,
        now,
    )


@pytest.mark.parametrize(
    ("trigger", "remote_state"),
    [(TRIGGER_CANCELED, "active"), (TRIGGER_SUSPENDED, "active"), (TRIGGER_RESUMED, "suspended")],
)
def test_a_trigger_that_disagrees_with_paymob_state_is_ignored(
    pg_sessionmaker: sessionmaker[Session], trigger: str, remote_state: str
) -> None:
    status = (
        SubscriptionStatus.past_due if trigger == TRIGGER_RESUMED else SubscriptionStatus.active
    )
    _, sid = _linked(
        pg_sessionmaker,
        status=status,
        grace_until=END if status is SubscriptionStatus.past_due else None,
    )
    before = _sub(pg_sessionmaker, sid)
    with capture_logs() as logs:
        _deliver(pg_sessionmaker, _client(state=remote_state), trigger, END - timedelta(days=5))
    after = _sub(pg_sessionmaker, sid)
    assert (after.status, after.cancel_at_period_end, after.paymob_cancelled_at) == (
        before.status,
        before.cancel_at_period_end,
        before.paymob_cancelled_at,
    )
    assert any(e["event"] == "paymob_state_disagrees" for e in logs)


def test_a_suspension_is_a_cancel_at_period_end_and_a_resume_undoes_it(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """P05 T8: the period-end sweep ends it as "cancelled" (see test_subscription_plan_changes)."""
    _, sid = _linked(pg_sessionmaker)
    now = END - timedelta(days=10)
    _deliver(pg_sessionmaker, _client(state="suspended", updated_at="s"), TRIGGER_SUSPENDED, now)
    sub = _sub(pg_sessionmaker, sid)
    assert (sub.status, sub.grace_until, sub.cancel_at_period_end, sub.suspended_at) == (
        SubscriptionStatus.active,
        None,
        True,
        now,
    )
    _deliver(
        pg_sessionmaker,
        _client(state="active", updated_at="r"),
        TRIGGER_RESUMED,
        now + timedelta(days=1),
    )
    sub = _sub(pg_sessionmaker, sid)
    assert (sub.status, sub.grace_until, sub.cancel_at_period_end, sub.suspended_at) == (
        SubscriptionStatus.active,
        None,
        False,
        None,
    )


def test_resume_after_the_paid_period_ended_stays_past_due(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    grace = END + GRACE
    sid = _past_due(pg_sessionmaker, PID, grace)
    _deliver(pg_sessionmaker, _client(state="active"), TRIGGER_RESUMED, END + timedelta(days=1))
    sub = _sub(pg_sessionmaker, sid)
    assert (sub.status, sub.grace_until) == (SubscriptionStatus.past_due, grace)


def test_a_suspend_of_a_plan_that_is_not_active_changes_nothing(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    grace = END + GRACE
    sid = _past_due(pg_sessionmaker, PID, grace)
    _deliver(pg_sessionmaker, _client(state="suspended"), TRIGGER_SUSPENDED, END)
    assert _sub(pg_sessionmaker, sid).grace_until == grace


def test_handler_table_covers_every_lifecycle_trigger(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    with pg_sessionmaker() as session:
        table = _service(session)._handlers()
    assert set(table) == {
        subscription_repo.TRIGGER_SUCCESS,
        TRIGGER_FAILED,
        TRIGGER_OVERDUE,
        TRIGGER_CANCELED,
        TRIGGER_SUSPENDED,
        TRIGGER_RESUMED,
    }


def test_two_sweeps_racing_for_one_row_expire_it_once(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    grace = END + GRACE
    sid = _past_due(pg_sessionmaker, PID, grace)
    results: list[int] = []

    def run() -> None:
        results.append(_sweep(pg_sessionmaker, grace + timedelta(minutes=1), _client()))

    threads = [threading.Thread(target=run) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert sum(results) == 1
    assert _sub(pg_sessionmaker, sid).status is SubscriptionStatus.expired
    assert _notice_names(pg_sessionmaker) == ["expired"]
