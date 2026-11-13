"""Admin plan tiers get a linked Paymob subscription plan (spec §4.1, §8 Catalogue)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

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
from lemely.io.paymob.client import PaymobError
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


def test_the_paymob_retry_window_is_not_set(pg_sessionmaker: sessionmaker[Session]) -> None:
    """UD-7: Paymob's default retry window applies, so ``retrial_days`` reaches the client unset."""
    tier_id = seed_tier(pg_sessionmaker, paymob_plan_id=None)
    client = FakePaymobClient()
    with pg_sessionmaker.begin() as session:
        sync_paymob_plan(session, client, paymob_settings(), tier_id)
    assert client.calls[0][1]["retrial_days"] is None


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
    pg_sessionmaker: sessionmaker[Session], response: JsonObject
) -> None:
    tier_id = seed_tier(pg_sessionmaker, paymob_plan_id=None)
    client = FakePaymobClient()
    client.create_plan = lambda **_: response  # type: ignore[method-assign,assignment]
    with pytest.raises(PlanSyncFailed) as raised, pg_sessionmaker.begin() as session:
        sync_paymob_plan(session, client, paymob_settings(), tier_id)
    assert raised.value.code == "plan_sync_failed"
    assert isinstance(raised.value, SubscriptionError)
    assert _linked_plan(pg_sessionmaker, tier_id) is None


def test_a_failed_force_new_keeps_the_existing_link(pg_sessionmaker: sessionmaker[Session]) -> None:
    tier_id = seed_tier(pg_sessionmaker, paymob_plan_id=515_151)
    client = FakePaymobClient()
    client.fail["create_plan"] = PaymobError("down", status_code=None)
    with pytest.raises(PaymobError), pg_sessionmaker.begin() as session:
        sync_paymob_plan(session, client, paymob_settings(), tier_id, force_new=True)
    assert _linked_plan(pg_sessionmaker, tier_id) == 515_151


def test_a_paymob_error_propagates_and_an_unknown_outcome_raises_the_alert(
    pg_sessionmaker: sessionmaker[Session], capsys: pytest.CaptureFixture[str]
) -> None:
    tier_id = seed_tier(pg_sessionmaker, paymob_plan_id=None)
    client = FakePaymobClient()
    client.fail["create_plan"] = PaymobError("timed out", status_code=None, timeout=True)
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
