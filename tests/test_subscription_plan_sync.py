"""Admin plan tiers get a linked Paymob subscription plan (spec §4.1, §8 Catalogue)."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import httpx
import pytest
import sqlalchemy as sa
import structlog.testing
from sqlalchemy.exc import OperationalError

from lemely.db.billing_repo import BillingService
from lemely.db.models.billing import PlanTier
from lemely.db.models.enums import PlanInterval
from lemely.db.subscription_repo import (
    SUBSCRIPTION_WEBHOOK_PATH,
    PlanNotPurchasable,
    PlanSyncFailed,
    SubscriptionError,
    SubscriptionService,
    subscription_webhook_url,
    sync_paymob_plan,
)
from lemely.io.paymob.client import PaymobClient, PaymobError
from tests.paymob_fixtures import AUTH_TOKEN_RESPONSE, PAYMOB_SETTINGS, PLAN_RESPONSE
from tests.subscription_fixtures import (
    FakePaymobClient,
    paymob_settings,
    seed_tier,
    throwaway_database,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker

    from lemely.io.paymob.client import JsonObject

NOW = datetime(2026, 11, 10, 9, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def pg_sessionmaker() -> Iterator[sessionmaker[Session]]:
    with throwaway_database() as factory:
        yield factory


def _linked_plan(factory: sessionmaker[Session], tier_id: uuid.UUID) -> int | None:
    with factory() as session:
        tier = session.get(PlanTier, tier_id)
        assert tier is not None
        return tier.paymob_plan_id


@pytest.mark.parametrize(
    ("interval", "frequency"), [(PlanInterval.monthly, 30), (PlanInterval.yearly, 360)]
)
def test_unlinked_tier_creates_and_links_a_plan(
    pg_sessionmaker: sessionmaker[Session], interval: PlanInterval, frequency: int
) -> None:
    tier_id = seed_tier(pg_sessionmaker, interval=interval, price_minor=12_000, paymob_plan_id=None)
    client = FakePaymobClient()
    settings = paymob_settings(notification_base_url="https://api.lemely.test/")
    with pg_sessionmaker.begin() as session:
        plan_id = sync_paymob_plan(session, client, settings, tier_id)
    assert client.names() == ["create_plan"]
    sent = client.calls[0][1]
    assert sent["frequency_days"] == frequency
    assert sent["integration_id"] == settings.moto_integration_id
    assert sent["amount_cents"] == 12_000
    assert sent["use_transaction_amount"] is True
    assert sent["webhook_url"] == "https://api.lemely.test" + SUBSCRIPTION_WEBHOOK_PATH
    assert _linked_plan(pg_sessionmaker, tier_id) == plan_id
    with pg_sessionmaker() as session:
        tier = session.get(PlanTier, tier_id)
        assert tier is not None
        # R9: the price and frequency Paymob was sent, stamped by the link itself, so a tier
        # linked at checkout (this path) is comparable for drift, not "unverified".
        assert (tier.paymob_plan_synced_price_minor, tier.paymob_plan_synced_frequency) == (
            12_000,
            frequency,
        )


def test_a_forced_relink_restamps_the_new_price(pg_sessionmaker: sessionmaker[Session]) -> None:
    tier_id = seed_tier(pg_sessionmaker, price_minor=12_000, paymob_plan_id=None)
    with pg_sessionmaker.begin() as session:
        sync_paymob_plan(session, FakePaymobClient(), paymob_settings(), tier_id)
    with pg_sessionmaker.begin() as session:
        session.execute(
            sa.update(PlanTier).where(PlanTier.id == tier_id).values(price_minor=15_000)
        )
    with pg_sessionmaker.begin() as session:
        sync_paymob_plan(session, FakePaymobClient(), paymob_settings(), tier_id, force_new=True)
    with pg_sessionmaker() as session:
        tier = session.get(PlanTier, tier_id)
        assert tier is not None
        assert tier.paymob_plan_synced_price_minor == 15_000


def test_paymob_plan_linked_is_logged_only_after_the_commit(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    tier_id = seed_tier(pg_sessionmaker, paymob_plan_id=None)
    with structlog.testing.capture_logs() as logs:
        with pg_sessionmaker() as session, session.begin():
            sync_paymob_plan(session, FakePaymobClient(), paymob_settings(), tier_id)
            assert [e for e in logs if e["event"] == "paymob_plan_linked"] == []
        linked = [e for e in logs if e["event"] == "paymob_plan_linked"]
    assert len(linked) == 1
    assert linked[0]["plan_tier_id"] == str(tier_id)


def test_a_rolled_back_link_logs_no_paymob_plan_linked(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    tier_id = seed_tier(pg_sessionmaker, paymob_plan_id=None)
    with (
        structlog.testing.capture_logs() as logs,
        pytest.raises(RuntimeError),
        pg_sessionmaker() as session,
        session.begin(),
    ):
        sync_paymob_plan(session, FakePaymobClient(), paymob_settings(), tier_id)
        raise RuntimeError("the caller failed after the link")
    assert [e for e in logs if e["event"] == "paymob_plan_linked"] == []
    assert _linked_plan(pg_sessionmaker, tier_id) is None


@pytest.mark.parametrize(
    ("secret", "public", "mode"),
    [
        ("egy_sk_test_x", "egy_pk_test_x", "test"),
        ("egy_sk_live_x", "egy_pk_live_x", "live"),
        ("sk", "pk", "test"),  # bare fixture keys carry no mode: not production, so test
    ],
)
def test_the_linked_plan_records_the_key_mode_it_was_created_under(
    pg_sessionmaker: sessionmaker[Session], secret: str, public: str, mode: str
) -> None:
    """A Paymob plan id exists in one key mode only (audit I8): store which, with the id."""
    tier_id = seed_tier(pg_sessionmaker, paymob_plan_id=None)
    settings = paymob_settings(secret_key=secret, public_key=public)
    with pg_sessionmaker.begin() as session:
        sync_paymob_plan(session, FakePaymobClient(), settings, tier_id)
    with pg_sessionmaker() as session:
        tier = session.get(PlanTier, tier_id)
        assert tier is not None
        assert tier.paymob_plan_mode == mode


def test_the_paymob_retry_window_is_three_days(pg_sessionmaker: sessionmaker[Session]) -> None:
    """Revised UD-7: a null ``retrial_days`` may mean no retries, so the plan sets it."""
    tier_id = seed_tier(pg_sessionmaker, paymob_plan_id=None)
    client = FakePaymobClient()
    with pg_sessionmaker.begin() as session:
        sync_paymob_plan(session, client, paymob_settings(), tier_id)
    assert client.calls[0][1]["retrial_days"] == 3


def test_the_real_client_sends_retrial_days_as_a_json_integer(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """The plan sync through the real ``PaymobClient``: the wire body, not the fake's record."""
    path = "/api/acceptance/subscription-plans"
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/api/auth/tokens":
            return httpx.Response(200, json=AUTH_TOKEN_RESPONSE)
        assert request.url.path == path
        return httpx.Response(201, json={**PLAN_RESPONSE, "id": 7_777_001})

    tier_id = seed_tier(pg_sessionmaker, price_minor=12_000, paymob_plan_id=None)
    client = PaymobClient(
        PAYMOB_SETTINGS, http=httpx.Client(transport=httpx.MockTransport(handler))
    )
    with pg_sessionmaker.begin() as session:
        assert sync_paymob_plan(session, client, paymob_settings(), tier_id) == 7_777_001
    (request,) = (r for r in seen if r.url.path == path)
    assert request.method == "POST"
    assert request.headers["authorization"].startswith("Bearer ")
    raw = request.content.decode()
    assert '"retrial_days": 3' in raw or '"retrial_days":3' in raw
    body = json.loads(raw)
    assert body["retrial_days"] == 3
    assert type(body["retrial_days"]) is int
    assert body["use_transaction_amount"] is True
    assert body["amount_cents"] == 12_000
    assert _linked_plan(pg_sessionmaker, tier_id) == 7_777_001


def test_webhook_url_joins_the_origin_and_path() -> None:
    settings = paymob_settings(notification_base_url="https://api.lemely.test")
    assert (
        subscription_webhook_url(settings)
        == "https://api.lemely.test/api/webhooks/paymob/subscription"
    )


def test_linked_tier_is_left_alone_unless_forced(pg_sessionmaker: sessionmaker[Session]) -> None:
    tier_id = seed_tier(pg_sessionmaker, paymob_plan_id=424_242)
    client = FakePaymobClient()
    with pg_sessionmaker.begin() as session:
        assert sync_paymob_plan(session, client, paymob_settings(), tier_id) == 424_242
    assert client.calls == []
    with pg_sessionmaker.begin() as session:
        relinked = sync_paymob_plan(session, client, paymob_settings(), tier_id, force_new=True)
    assert relinked != 424_242
    assert client.names() == ["create_plan"]
    assert _linked_plan(pg_sessionmaker, tier_id) == relinked


def test_tier_without_interval_cannot_sync(pg_sessionmaker: sessionmaker[Session]) -> None:
    tier_id = seed_tier(pg_sessionmaker, interval=None, paymob_plan_id=None)
    client = FakePaymobClient()
    with pytest.raises(PlanNotPurchasable), pg_sessionmaker.begin() as session:
        sync_paymob_plan(session, client, paymob_settings(), tier_id)
    assert client.calls == []


@pytest.mark.parametrize("price", [0, -100])
def test_a_tier_with_no_price_is_refused_before_paymob_is_called(
    pg_sessionmaker: sessionmaker[Session], price: int
) -> None:
    tier_id = seed_tier(pg_sessionmaker, price_minor=price, paymob_plan_id=None)
    client = FakePaymobClient()
    with pytest.raises(PlanNotPurchasable, match="no price"), pg_sessionmaker.begin() as session:
        sync_paymob_plan(session, client, paymob_settings(), tier_id)
    assert client.calls == []
    assert _linked_plan(pg_sessionmaker, tier_id) is None


def test_an_unknown_tier_is_refused(pg_sessionmaker: sessionmaker[Session]) -> None:
    client = FakePaymobClient()
    with pytest.raises(PlanNotPurchasable, match="unknown"), pg_sessionmaker.begin() as session:
        sync_paymob_plan(session, client, paymob_settings(), uuid.uuid4())
    assert client.calls == []


def test_a_missing_moto_integration_is_refused_before_paymob_is_called(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    tier_id = seed_tier(pg_sessionmaker, paymob_plan_id=None)
    client = FakePaymobClient()
    settings = paymob_settings(moto_integration_id=None)
    with pytest.raises(PlanNotPurchasable, match="MOTO"), pg_sessionmaker.begin() as session:
        sync_paymob_plan(session, client, settings, tier_id)
    assert client.calls == []
    assert _linked_plan(pg_sessionmaker, tier_id) is None


@pytest.mark.parametrize(
    "response",
    [{}, {"id": None}, {"id": "1186"}, {"id": True}, {"id": 0}, {"id": -3}],
    ids=["no-id", "null-id", "string-id", "bool-id", "zero-id", "negative-id"],
)
def test_a_response_without_a_plan_id_leaves_the_tier_unlinked(
    pg_sessionmaker: sessionmaker[Session],
    response: JsonObject,
    capsys: pytest.CaptureFixture[str],
) -> None:
    tier_id = seed_tier(pg_sessionmaker, paymob_plan_id=None)
    client = FakePaymobClient()
    client.create_plan = lambda **_: response  # type: ignore[method-assign,assignment]
    with pytest.raises(PlanSyncFailed) as raised, pg_sessionmaker.begin() as session:
        sync_paymob_plan(session, client, paymob_settings(), tier_id)
    assert raised.value.code == "plan_sync_failed"
    assert isinstance(raised.value, SubscriptionError)
    assert _linked_plan(pg_sessionmaker, tier_id) is None
    logged = capsys.readouterr()
    assert "paymob_plan_response_unusable" in logged.out + logged.err
    assert str(tier_id) in logged.out + logged.err


def test_the_tier_row_is_locked_until_the_caller_commits(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """Two admins syncing one tier must not both create a Paymob plan: the row is ``FOR UPDATE``."""
    tier_id = seed_tier(pg_sessionmaker, paymob_plan_id=616_161)
    client = FakePaymobClient()
    lock_probe = sa.select(PlanTier.id).where(PlanTier.id == tier_id).with_for_update(nowait=True)
    with pg_sessionmaker() as holder:
        sync_paymob_plan(holder, client, paymob_settings(), tier_id)
        with pg_sessionmaker() as other, pytest.raises(OperationalError, match="lock"):
            other.execute(lock_probe)
        holder.rollback()
        with pg_sessionmaker() as other:
            assert other.execute(lock_probe).scalar_one() == tier_id


def test_a_failed_force_new_keeps_the_existing_link(pg_sessionmaker: sessionmaker[Session]) -> None:
    tier_id = seed_tier(pg_sessionmaker, paymob_plan_id=515_151)
    client = FakePaymobClient()
    client.fail["create_plan"] = PaymobError("down", status_code=None)
    with pytest.raises(PaymobError), pg_sessionmaker.begin() as session:
        sync_paymob_plan(session, client, paymob_settings(), tier_id, force_new=True)
    assert _linked_plan(pg_sessionmaker, tier_id) == 515_151


@pytest.mark.parametrize(
    "error",
    [
        PaymobError("timed out", status_code=None, timeout=True),
        PaymobError("bad gateway", status_code=502),
    ],
    ids=["no-answer", "5xx"],
)
def test_a_paymob_error_propagates_and_an_unknown_outcome_raises_the_alert(
    pg_sessionmaker: sessionmaker[Session], capsys: pytest.CaptureFixture[str], error: PaymobError
) -> None:
    """A gateway 5xx does not say whether Paymob created the plan, so it is an orphan risk too."""
    tier_id = seed_tier(pg_sessionmaker, paymob_plan_id=None)
    client = FakePaymobClient()
    client.fail["create_plan"] = error
    with pytest.raises(PaymobError), pg_sessionmaker.begin() as session:
        sync_paymob_plan(session, client, paymob_settings(), tier_id)
    assert _linked_plan(pg_sessionmaker, tier_id) is None
    logged = capsys.readouterr()
    assert "paymob_plan_create_unknown" in logged.out + logged.err
    assert str(tier_id) in logged.out + logged.err


def test_a_definite_rejection_is_not_an_unknown_outcome_alert(
    pg_sessionmaker: sessionmaker[Session], capsys: pytest.CaptureFixture[str]
) -> None:
    tier_id = seed_tier(pg_sessionmaker, paymob_plan_id=None)
    client = FakePaymobClient()
    client.fail["create_plan"] = PaymobError("bad frequency", status_code=400)
    with pytest.raises(PaymobError), pg_sessionmaker.begin() as session:
        sync_paymob_plan(session, client, paymob_settings(), tier_id)
    logged = capsys.readouterr()
    assert "paymob_plan_create_unknown" not in logged.out + logged.err


def test_the_service_builds_payments_on_the_callers_clock(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """DV-8: ``paid_at`` and reconcile times follow ``now``, never the wall clock."""
    with pg_sessionmaker() as session:
        service = SubscriptionService(session, FakePaymobClient(), paymob_settings())
        billing = service._billing(NOW)
        assert isinstance(billing, BillingService)
        assert billing._now() == NOW
