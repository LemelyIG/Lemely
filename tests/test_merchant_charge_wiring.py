"""Phase 06 T10: the merchant-charge pieces are wired into the app, the sweeper and the jobs.

Each guard here has a mutation proof in the task report: drop the ``billing_jobs`` imports, build
the providers on ``checkout_configured`` alone, append the post-settle hook instead of
registering it once, or skip the amount pusher in one entry point, and a test below goes red.
"""

from __future__ import annotations

import ast
import itertools
import os
import subprocess
import sys
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

from lemely.db import auto_topup_repo, merchant_charge_repo
from lemely.db.admin_health_repo import BILLING_JOB_NAMES
from lemely.db.announcement_repo import AnnouncementService
from lemely.db.billing_repo import BillingService, paid_handler_for
from lemely.db.class_repo import ClassService
from lemely.db.merchant_charge_repo import MerchantChargeService
from lemely.db.models.billing import Payment, PaymentPurpose, Subscription
from lemely.db.models.billing_ops import CreditConversionRate
from lemely.db.notification_prefs_repo import NotificationPreferencesService
from lemely.db.notification_repo import NotificationService
from lemely.db.subscription_repo import SubscriptionService
from lemely.runtime.config import NotificationsSettings, PaymobSettings
from lemely.web import deps, deps_billing, usage
from lemely.web.app import create_app
from lemely.web.push import RecordingPushTransport
from lemely.web.scheduled_notifications import Sweeper
from lemely.web.subscription_deps import SubscriptionDeps
from tests.merchant_charge_fixtures import seed_tier, student_with_plan, throwaway_database
from tests.paymob_fixtures import INTENTION_RESPONSE, PAYMOB_SETTINGS, transaction_obj
from tests.subscription_fixtures import (
    T0,
    FakePaymobClient,
    charge,
    paymob_settings,
    remote_subscription,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker

REPO = Path(__file__).resolve().parent.parent
NOW = T0 + timedelta(days=15)
DEC_1 = datetime(2026, 12, 1, 0, 1, tzinfo=UTC)
PHASE_05_JOBS = [
    "subscriptions.expire_overdue",
    "subscriptions.period_end",
    "subscriptions.drift_check",
    "seats.release_due",
    "seats.monthly_allowance",
]
PHASE_06_JOBS = ["billing.extra_seat_renewal_charge", "billing.auto_topup"]


@pytest.fixture(scope="module")
def pg_sessionmaker() -> Iterator[sessionmaker[Session]]:
    with throwaway_database() as factory:
        with factory.begin() as session:
            session.add(CreditConversionRate(currency="EGP", units_per_minor=Decimal("0.01")))
        yield factory


@pytest.fixture(autouse=True)
def _clean_process_wiring() -> Iterator[None]:
    """Each test starts with no amount pusher and the post-settle hooks it found."""
    hooks = list(usage._POST_SETTLE_HOOKS)
    merchant_charge_repo.register_amount_pusher(None)
    yield
    merchant_charge_repo.register_amount_pusher(None)
    usage._POST_SETTLE_HOOKS[:] = hooks


def _sweeper(
    sm: sessionmaker[Session],
    *,
    extra_seat_renewal: Any = None,
    auto_topup: Any = None,
) -> Sweeper:
    return Sweeper(
        sessionmaker=sm,
        announcements=AnnouncementService(sm, ClassService(sm)),
        notifications=NotificationService(sm, NotificationPreferencesService(sm)),
        transport=RecordingPushTransport(),
        settings=NotificationsSettings(),
        now=lambda: DEC_1,
        subscriptions=SubscriptionDeps(sm, FakePaymobClient(), paymob_settings()),
        seat_allowances=True,
        billing_extra_seat_renewal=extra_seat_renewal,
        billing_auto_topup=auto_topup,
    )


# ---------------------------------------------------------------------------
# 1. The sweeper runs both jobs, after every Phase 05 job, auto top-up last.
# ---------------------------------------------------------------------------


def test_the_sweeper_runs_both_charge_jobs_after_every_phase_05_job(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    seen: list[tuple[str, datetime]] = []

    def seats(now: datetime) -> int:
        seen.append(("seats", now))
        return 3

    def topup(now: datetime) -> int:
        seen.append(("topup", now))
        return 4

    results = _sweeper(pg_sessionmaker, extra_seat_renewal=seats, auto_topup=topup).sweep_once()

    assert list(results)[-7:] == [*PHASE_05_JOBS, *PHASE_06_JOBS]
    assert results["billing.extra_seat_renewal_charge"] == 3
    assert results["billing.auto_topup"] == 4
    assert seen == [("seats", DEC_1), ("topup", DEC_1)]


def test_without_the_callables_neither_charge_job_runs(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    results = _sweeper(pg_sessionmaker).sweep_once()
    assert not set(PHASE_06_JOBS) & set(results)
    assert list(results)[-5:] == PHASE_05_JOBS


def test_each_charge_job_is_independent_of_the_other(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    only_topup = _sweeper(pg_sessionmaker, auto_topup=lambda now: 0).sweep_once()
    assert "billing.auto_topup" in only_topup
    assert "billing.extra_seat_renewal_charge" not in only_topup
    only_seats = _sweeper(pg_sessionmaker, extra_seat_renewal=lambda now: 0).sweep_once()
    assert "billing.extra_seat_renewal_charge" in only_seats
    assert "billing.auto_topup" not in only_seats


def test_admin_health_lists_both_charge_jobs() -> None:
    assert set(PHASE_06_JOBS) <= set(BILLING_JOB_NAMES)


def test_the_sweeper_does_not_schedule_the_period_end_changes_a_second_time() -> None:
    """P05-T12 owns ``apply_period_end_changes`` as ``subscriptions.period_end`` (M-6)."""
    source = (REPO / "lemely" / "web" / "scheduled_notifications.py").read_text()
    assert "apply_period_end_changes" not in source


# ---------------------------------------------------------------------------
# 2. The providers need the MOTO id and the token key, not checkout alone.
# ---------------------------------------------------------------------------


def _use_paymob(monkeypatch: pytest.MonkeyPatch, paymob: PaymobSettings) -> None:
    settings = deps.get_settings().model_copy(update={"paymob": paymob})
    monkeypatch.setattr(deps_billing, "get_settings", lambda: settings)


_PROVIDERS = [deps_billing.get_auto_topup_job, deps_billing.get_extra_seat_renewal_job]


@pytest.mark.parametrize("provider", _PROVIDERS)
@pytest.mark.parametrize("missing", ["moto_integration_id", "card_token_key"])
def test_a_provider_is_none_when_a_charge_prerequisite_is_unset(
    monkeypatch: pytest.MonkeyPatch, provider: Any, missing: str
) -> None:
    paymob = PaymobSettings.model_validate({**PAYMOB_SETTINGS.model_dump(), missing: None})
    assert paymob.checkout_configured  # checkout alone works: it is not enough
    _use_paymob(monkeypatch, paymob)
    assert provider() is None


@pytest.mark.parametrize("provider", _PROVIDERS)
def test_a_provider_is_none_when_paymob_is_unconfigured(
    monkeypatch: pytest.MonkeyPatch, provider: Any
) -> None:
    _use_paymob(monkeypatch, PaymobSettings())
    assert provider() is None


def test_the_providers_run_their_job_with_the_process_collaborators(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_paymob(monkeypatch, PAYMOB_SETTINGS)
    client = FakePaymobClient()
    factory = SimpleNamespace(name="sessionmaker")
    calls: list[tuple[str, object, object, object, datetime]] = []

    def fake(name: str, result: int) -> Any:
        def run(
            sm: object, client_: object, settings_: object, *, now: datetime, **_: object
        ) -> int:
            calls.append((name, sm, client_, settings_, now))
            return result

        return run

    monkeypatch.setattr(deps_billing, "get_paymob_client", lambda: client)
    monkeypatch.setattr(deps_billing, "get_billing_sessionmaker", lambda: factory)
    monkeypatch.setattr(deps_billing, "run_auto_topup_job", fake("topup", 5))
    monkeypatch.setattr(deps_billing, "run_extra_seat_renewal_job", fake("seats", 6))

    topup = deps_billing.get_auto_topup_job()
    seats = deps_billing.get_extra_seat_renewal_job()

    assert topup is not None
    assert seats is not None
    assert topup(DEC_1) == 5
    assert seats(DEC_1) == 6
    assert calls == [
        ("topup", factory, client, PAYMOB_SETTINGS, DEC_1),
        ("seats", factory, client, PAYMOB_SETTINGS, DEC_1),
    ]


def test_get_sweeper_passes_both_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    def topup(now: datetime) -> int:
        return 1

    def seats(now: datetime) -> int:
        return 2

    try:
        deps.get_sweeper.cache_clear()
        monkeypatch.setattr(deps_billing, "get_auto_topup_job", lambda: topup)
        monkeypatch.setattr(deps_billing, "get_extra_seat_renewal_job", lambda: seats)
        sweeper = deps.get_sweeper()
        assert sweeper.billing_auto_topup is topup
        assert sweeper.billing_extra_seat_renewal is seats
        deps.get_sweeper.cache_clear()
        monkeypatch.setattr(deps_billing, "get_auto_topup_job", lambda: None)
        monkeypatch.setattr(deps_billing, "get_extra_seat_renewal_job", lambda: None)
        sweeper = deps.get_sweeper()
        assert sweeper.billing_auto_topup is None
        assert sweeper.billing_extra_seat_renewal is None
    finally:
        deps.get_sweeper.cache_clear()


# ---------------------------------------------------------------------------
# 3. ``create_app`` registers the post-settle hook once, however many apps are built.
# ---------------------------------------------------------------------------


def test_create_app_registers_the_auto_topup_hook_once() -> None:
    usage.clear_post_settle_hooks()
    create_app()
    create_app()
    assert usage._POST_SETTLE_HOOKS.count(auto_topup_repo.auto_topup_post_settle_hook) == 1


# ---------------------------------------------------------------------------
# 4. A fresh interpreter importing only the reconcile module finds every handler.
# ---------------------------------------------------------------------------

_PROBE = (
    "import lemely.web.billing_jobs; "
    "from lemely.db.billing_repo import paid_handler_for; "
    "from lemely.db.models.billing import PaymentPurpose as P; "
    "assert paid_handler_for(P.upgrade_proration), 'upgrade_proration'; "
    "assert paid_handler_for(P.extra_seats), 'extra_seats'; "
    "assert paid_handler_for(P.auto_topup), 'auto_topup'"
)


def test_billing_jobs_alone_registers_the_phase_06_handlers() -> None:
    env = {**os.environ, "PYTHONPATH": str(REPO)}
    # A fixed argv built from this interpreter and a constant script: nothing untrusted.
    subprocess.run(  # noqa: S603
        [sys.executable, "-c", _PROBE], env=env, cwd=REPO, check=True, timeout=120
    )


def test_billing_jobs_names_the_registration_imports_itself() -> None:
    tree = ast.parse((REPO / "lemely" / "web" / "billing_jobs.py").read_text())
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert {"lemely.db.merchant_charge_repo", "lemely.db.auto_topup_repo"} <= imported


# ---------------------------------------------------------------------------
# 5. The amount pusher is registered in EVERY process that settles payments.
# ---------------------------------------------------------------------------


def _pusher() -> Any:
    return merchant_charge_repo._amount_pusher


def test_the_web_process_registers_the_amount_pusher() -> None:
    assert _pusher() is None
    create_app()
    assert _pusher() is deps_billing.push_subscription_amount


def test_the_reconcile_job_process_registers_the_amount_pusher(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_paymob(monkeypatch, PAYMOB_SETTINGS)
    assert _pusher() is None
    assert deps_billing.get_billing_reconcile_job() is not None
    assert _pusher() is deps_billing.push_subscription_amount


def test_a_reconcile_process_with_paymob_unconfigured_still_registers_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_paymob(monkeypatch, PaymobSettings())
    assert deps_billing.get_billing_reconcile_job() is None
    assert _pusher() is deps_billing.push_subscription_amount


def test_building_the_sweeper_registers_the_amount_pusher(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    try:
        deps.get_sweeper.cache_clear()
        assert _pusher() is None
        deps.get_sweeper()
        assert _pusher() is deps_billing.push_subscription_amount
    finally:
        deps.get_sweeper.cache_clear()


# ---------------------------------------------------------------------------
# 6. ``maybe_enqueue_auto_topup`` is ``enqueue_auto_topup`` under the index contract's name.
# ---------------------------------------------------------------------------


def test_maybe_enqueue_auto_topup_returns_what_enqueue_returns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = uuid.uuid4()
    session: Any = SimpleNamespace(name="session")
    queued = SimpleNamespace(name="payment")
    seen: list[tuple[object, uuid.UUID, datetime]] = []

    def fake(session_: object, owner_: uuid.UUID, *, now: datetime) -> object:
        seen.append((session_, owner_, now))
        return queued

    monkeypatch.setattr(auto_topup_repo, "enqueue_auto_topup", fake)
    service = MerchantChargeService(session, FakePaymobClient(), PAYMOB_SETTINGS)

    assert service.maybe_enqueue_auto_topup(owner, NOW) is queued
    assert seen == [(session, owner, NOW)]

    monkeypatch.setattr(auto_topup_repo, "enqueue_auto_topup", lambda *a, **k: None)
    assert service.maybe_enqueue_auto_topup(owner, NOW) is None


# ---------------------------------------------------------------------------
# 7. End to end with Phase 05: an upgrade paid through the real callback.
# ---------------------------------------------------------------------------

_order_ids = itertools.count(770_001)
_txn_ids = itertools.count(7_700_001)


class _CheckoutClient(FakePaymobClient):
    """The recording fake, whose intention accepts ``sensitive`` and mints an order id."""

    def create_intention(  # type: ignore[override]
        self, body: Mapping[str, object], *, sensitive: Sequence[str] = ()
    ) -> dict[str, Any]:
        self.intentions.append(dict(body))
        response = dict(INTENTION_RESPONSE)
        response["intention_order_id"] = next(_order_ids)
        response["id"] = f"pi_test_wire_{next(_order_ids)}"
        return response


def _upgrade_scene(sm: sessionmaker[Session]) -> tuple[dict[str, uuid.UUID], uuid.UUID, uuid.UUID]:
    """A student on 10 000 with Paymob holding 10 000, upgrading to 20 000 mid period."""
    scene = student_with_plan(sm, price=10_000, allowance_units=1_000)
    target = seed_tier(sm, price_minor=20_000, allowance_units=3_000)
    with sm() as session:
        payment = MerchantChargeService(
            session, _CheckoutClient(), PAYMOB_SETTINGS
        ).start_upgrade_checkout(
            subscription_id=scene["subscription_id"],
            actor_user_id=scene["payer_id"],
            plan_tier_id=target,
            now=NOW,
        )
    return scene, target, payment.payment_id


def _pay(sm: sessionmaker[Session], payment_id: uuid.UUID) -> None:
    with sm() as session:
        payment = session.get(Payment, payment_id)
        assert payment is not None
        assert payment.paymob_order_id is not None
        obj = transaction_obj(
            txn_id=next(_txn_ids),
            order_id=payment.paymob_order_id,
            merchant_order_id=str(payment.id),
            amount_cents=payment.amount_minor,
        )
    with sm.begin() as session:
        BillingService(
            session, FakePaymobClient(), PAYMOB_SETTINGS, now=lambda: NOW
        ).apply_transaction_callback(obj)


def _sub(sm: sessionmaker[Session], scene: Mapping[str, uuid.UUID]) -> Subscription:
    with sm() as session:
        row = session.get(Subscription, scene["subscription_id"])
        assert row is not None
        return row


def _paymob_with(client: FakePaymobClient, sm: sessionmaker[Session], scene: Any, held: int) -> int:
    paymob_id = _sub(sm, scene).paymob_subscription_id
    assert paymob_id is not None
    client.subscriptions[paymob_id] = remote_subscription(
        paymob_id, state="active", amount_cents=held
    )
    client.last_transactions[paymob_id] = charge(1, held)
    return paymob_id


def test_a_paid_upgrade_is_pushed_once_by_the_drift_check_and_stamped(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """DV-1's promise: the handler wrote nothing to Paymob, so the next drift check does."""
    sm = pg_sessionmaker
    scene, target, payment_id = _upgrade_scene(sm)
    _pay(sm, payment_id)  # no pusher registered here: the settle logs and pushes nothing
    assert _sub(sm, scene).plan_tier_id == target
    assert _sub(sm, scene).paymob_amount_minor == 10_000
    client = FakePaymobClient()
    paymob_id = _paymob_with(client, sm, scene, 10_000)

    with sm() as session:
        service = SubscriptionService(session, client, paymob_settings())
        service.check_drift(now=NOW + timedelta(days=1))
    with sm() as session:
        service = SubscriptionService(session, client, paymob_settings())
        service.check_drift(now=NOW + timedelta(days=2))  # a second pass finds nothing to do

    assert [c["amount_cents"] for c in client.calls_to("update_subscription")] == [20_000]
    assert client.calls_to("update_subscription")[0]["subscription_id"] == paymob_id
    assert _sub(sm, scene).paymob_amount_minor == 20_000


def test_on_the_fixed_amount_path_an_upgrade_is_refused_and_nothing_is_pushed(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """DV-2 / H1: with no amount updates the upgrade never starts, and drift never PUTs."""
    sm = pg_sessionmaker
    scene = student_with_plan(sm, price=10_000, allowance_units=1_000)
    target = seed_tier(sm, price_minor=20_000, allowance_units=3_000)
    fixed = PaymobSettings.model_validate(
        {**PAYMOB_SETTINGS.model_dump(), "subscription_amount_updatable": False}
    )
    with sm() as session, pytest.raises(merchant_charge_repo.MerchantChargeError):
        MerchantChargeService(session, _CheckoutClient(), fixed).start_upgrade_checkout(
            subscription_id=scene["subscription_id"],
            actor_user_id=scene["payer_id"],
            plan_tier_id=target,
            now=NOW,
        )
    client = FakePaymobClient()
    _paymob_with(client, sm, scene, 12_345)
    with sm() as session:
        SubscriptionService(
            session, client, paymob_settings(subscription_amount_updatable=False)
        ).check_drift(now=NOW + timedelta(days=1))
    assert client.calls_to("update_subscription") == []
    assert _sub(sm, scene).paymob_amount_minor == 10_000


def test_a_settle_pushes_the_amount_when_the_process_registered_the_pusher(
    pg_sessionmaker: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The registration made at startup does its job: the settle's commit pushes the amount."""
    sm = pg_sessionmaker
    scene, _, payment_id = _upgrade_scene(sm)
    client = FakePaymobClient()
    paymob_id = _paymob_with(client, sm, scene, 10_000)
    monkeypatch.setattr(deps_billing, "get_paymob_client", lambda: client)
    monkeypatch.setattr(deps_billing, "get_billing_sessionmaker", lambda: sm)
    _use_paymob(monkeypatch, PAYMOB_SETTINGS)
    deps_billing.register_billing_amount_pusher()

    _pay(sm, payment_id)

    assert client.calls_to("update_subscription") == [
        {
            "subscription_id": paymob_id,
            "amount_cents": 20_000,
            "ends_at": None,
            "next_billing": None,
        }
    ]
    assert _sub(sm, scene).paymob_amount_minor == 20_000


def test_a_live_auto_topup_callback_finds_its_handler() -> None:
    """A paid ``auto_topup`` payment reaches ``handle_auto_topup_paid``, not "no paid handler"."""
    assert paid_handler_for(PaymentPurpose.auto_topup) is auto_topup_repo.handle_auto_topup_paid
