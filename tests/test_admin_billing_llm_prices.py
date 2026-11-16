"""Admin AI token price overrides, routes and service (UD13-D, Phase 07 T19).

Pinned here: the model list (code table, config, models seen in 30 days, overrides), one audit row
per write with before and after, none per refusal, optimistic concurrency, the version that keeps
counting across clear and recreate, the refresh of this process after a committed write only, the
bounds on every price, and that the router guards itself with no parent router.
"""

from __future__ import annotations

import tempfile
import threading
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from fastapi.testclient import TestClient

from lemely.core.usage_types import GrantScope, Payer
from lemely.db.billing_settings_repo import BillingSettingsService
from lemely.db.llm_price_repo import ACTION_CLEAR, ACTION_SET, LlmPriceService
from lemely.db.models.billing_ops import LlmPriceOverride, UsageJobModelCost
from lemely.db.models.enums import Role
from lemely.io.llm import price_overrides
from lemely.io.llm.pricing import CLAUDE_PRICING, claude_row
from lemely.web import llm_price_refresh
from lemely.web.deps import AuthContext, get_auth_context, get_settings
from lemely.web.routers.admin_billing_settings import (
    get_billing_settings_service,
    get_llm_price_service,
    llm_price_scope,
)
from lemely.web.routers.admin_billing_settings import router as settings_router
from tests.admin_billing_db import (
    NOW,
    add_rate,
    add_user,
    audit_count,
    audit_rows,
    billing_database,
    emptied_after,
    grant,
    metered_job,
)
from tests.gemini_fakes import make_settings
from tests.tutoring_app import app_with_routers

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from httpx2 import Response
    from sqlalchemy.orm import Session, sessionmaker

    from lemely.runtime.config import Settings

BASE = "/api/admin/billing/llm-prices"
REASON = "provider changed its price"
SONNET = "claude-sonnet-5-5"
FULL = {
    "inputUsdPerMtok": "3",
    "outputUsdPerMtok": "15",
    "cachedInputUsdPerMtok": "0.3",
    "cacheWrite5mUsdPerMtok": "3.75",
    "cacheWrite1hUsdPerMtok": "6",
    "tierThresholdTokens": 200000,
    "tier2InputUsdPerMtok": "6",
    "tier2OutputUsdPerMtok": "22.5",
}


@pytest.fixture(autouse=True)
def _clean_registry() -> Iterator[None]:
    price_overrides.install(None)
    llm_price_refresh.reset_failures()
    yield
    price_overrides.install(None)
    llm_price_refresh.reset_failures()


@pytest.fixture(scope="module")
def billing_db() -> Iterator[sessionmaker[Session]]:
    with billing_database() as factory:
        yield factory


@pytest.fixture
def sm(billing_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(billing_db)


@pytest.fixture
def admin(sm: sessionmaker[Session]) -> uuid.UUID:
    return add_user(sm, Role.platform_admin)


def _scope_dependency(sm: sessionmaker[Session]) -> Callable[[], Iterator[LlmPriceService]]:
    """The real dependency's transaction and refresh, on the test database."""

    def dependency() -> Iterator[LlmPriceService]:
        yield from llm_price_scope(sm)

    return dependency


def _client(
    sm: sessionmaker[Session], admin_id: uuid.UUID, settings: Settings | None = None
) -> TestClient:
    app = app_with_routers(settings_router)  # a no-op once app.py mounts it
    app.dependency_overrides[get_llm_price_service] = _scope_dependency(sm)
    if settings is not None:
        app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(
        user_id=str(admin_id), role=Role.platform_admin.value
    )
    return TestClient(app)


@pytest.fixture
def client(sm: sessionmaker[Session], admin: uuid.UUID) -> TestClient:
    return _client(sm, admin, make_settings(tempfile.mkdtemp()))


def _put(client: TestClient, model: str = SONNET, /, **body: object) -> Response:
    payload: dict[str, object] = {**FULL, "expectedVersion": None, "reason": REASON}
    payload.update(body)
    return client.put(f"{BASE}/{model}", json=payload)


def _clear(client: TestClient, version: int, model: str = SONNET) -> Response:
    return client.post(f"{BASE}/{model}/clear", json={"expectedVersion": version, "reason": REASON})


def _error(resp: Response) -> dict[str, str]:
    detail: dict[str, str] = resp.json()["detail"]
    return detail


def _model(body: dict[str, object], name: str) -> dict[str, object]:
    (found,) = [m for m in body["models"] if m["model"] == name]  # type: ignore[attr-defined]
    row: dict[str, object] = found
    return row


# --- the model list -----------------------------------------------------------------------


def test_the_list_holds_code_config_seen_and_overridden_models(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    base = make_settings(tempfile.mkdtemp())
    settings = base.model_copy(
        update={
            "gemini": base.gemini.model_copy(
                update={"pricing": {"my-config-model": [0.002, 0.004]}}
            )
        }
    )
    client = _client(sm, admin, settings)
    payer = add_user(sm, Role.student)
    add_rate(sm, "mark_paper")
    grant(sm, payer, units=50, effective_at=NOW - timedelta(days=60))
    pay = [Payer(owner_user_id=payer, scope=GrantScope.CREDITS)]
    job = metered_job(sm, payer, pay, low=1, high=2, cost=Decimal("0.001"))
    now = datetime.now(UTC)
    with sm.begin() as session:
        session.add_all(
            [
                UsageJobModelCost(
                    usage_job_id=job,
                    model="seen-model",
                    cost_usd=Decimal("0.001"),
                    created_at=now - timedelta(days=1),
                ),
                UsageJobModelCost(
                    usage_job_id=job,
                    model="old-model",
                    cost_usd=Decimal("0.001"),
                    created_at=now - timedelta(days=40),
                ),
            ]
        )
    assert _put(client, "only-override").status_code == 200

    body = client.get(BASE).json()

    names = {m["model"] for m in body["models"]}
    assert set(CLAUDE_PRICING) <= names
    assert {"gemini-3.5-flash", "my-config-model", "seen-model", "only-override"} <= names
    assert "old-model" not in names
    assert _model(body, "seen-model")["seenInLast30Days"] is True
    assert _model(body, "seen-model")["codeDefault"] is None
    assert _model(body, "gemini-3.5-flash")["seenInLast30Days"] is False
    assert _model(body, "only-override")["override"]["inputUsdPerMtok"] == "3.000000"  # type: ignore[index]
    assert _model(body, "only-override")["codeDefault"] is None


def test_a_code_default_is_per_million_tokens_with_its_source_and_tier(
    client: TestClient,
) -> None:
    body = client.get(BASE).json()
    haiku = _model(body, "claude-haiku-5-5")
    assert haiku["provider"] == "anthropic"
    default = haiku["codeDefault"]
    assert isinstance(default, dict)
    assert (default["inputUsdPerMtok"], default["outputUsdPerMtok"]) == ("0.1", "0.5")
    assert default["cachedInputUsdPerMtok"] == "0.01"
    assert default["tiered"] is True
    assert (default["tierThresholdTokens"], default["tier2InputUsdPerMtok"]) == (100000, "0.5")
    assert default["source"].startswith("https://")
    assert default["readOn"] == "2026-10-19"
    gemini = _model(body, "gemini-3.5-flash")
    assert gemini["provider"] == "gemini"
    assert gemini["codeDefault"]["tiered"] is False  # type: ignore[index]
    assert gemini["codeDefault"]["readOn"] is None  # type: ignore[index]
    assert _model(body, SONNET)["override"] is None


def test_a_config_price_is_the_default_of_its_model(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    base = make_settings(tempfile.mkdtemp())
    settings = base.model_copy(
        update={"gemini": base.gemini.model_copy(update={"pricing": {SONNET: [0.002, 0.004]}})}
    )
    body = _client(sm, admin, settings).get(BASE).json()
    default = _model(body, SONNET)["codeDefault"]
    assert default["source"] == "config"  # type: ignore[index]
    assert (default["inputUsdPerMtok"], default["outputUsdPerMtok"]) == ("2", "4")  # type: ignore[index]


# --- set, replace, clear ------------------------------------------------------------------


def test_creating_stores_the_prices_and_writes_one_audit_row(
    client: TestClient, sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    resp = _put(client)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["model"] == SONNET
    assert body["version"] == 1
    assert body["updatedBy"] == str(admin)
    assert (body["inputUsdPerMtok"], body["tierThresholdTokens"]) == ("3.000000", 200000)
    (row,) = audit_rows(sm, ACTION_SET)
    assert row.target_kind == "llm_price"
    assert row.reason == REASON
    assert row.before is None
    assert row.after is not None
    assert (row.after["model"], row.after["version"]) == (SONNET, 1)
    assert row.after["input_usd_per_mtok"] == "3.000000"


def test_replacing_bumps_the_version_and_audits_before_and_after(
    client: TestClient, sm: sessionmaker[Session]
) -> None:
    assert _put(client).status_code == 200
    resp = _put(client, expectedVersion=1, inputUsdPerMtok="4", cachedInputUsdPerMtok=None)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["version"], body["inputUsdPerMtok"], body["cachedInputUsdPerMtok"]) == (
        2,
        "4.000000",
        None,
    )
    first, second = audit_rows(sm, ACTION_SET)
    assert second.before is not None
    assert second.before["input_usd_per_mtok"] == "3.000000"
    assert second.after is not None
    assert second.after["input_usd_per_mtok"] == "4.000000"
    assert first.id != second.id


def test_a_second_create_is_409_llm_price_exists(
    client: TestClient, sm: sessionmaker[Session]
) -> None:
    assert _put(client).status_code == 200
    resp = _put(client)
    assert resp.status_code == 409
    assert _error(resp)["code"] == "llm_price_exists"
    assert len(audit_rows(sm, ACTION_SET)) == 1


def test_a_stale_version_is_409_stale_write_for_replace_and_clear(
    client: TestClient, sm: sessionmaker[Session]
) -> None:
    assert _put(client).status_code == 200
    assert _put(client, expectedVersion=1).status_code == 200
    for resp in (_put(client, expectedVersion=1), _clear(client, 1)):
        assert resp.status_code == 409
        assert _error(resp)["code"] == "stale_write"
    assert _put(client, "never-set", expectedVersion=1).status_code == 409
    assert len(audit_rows(sm, ACTION_SET)) == 2
    assert audit_rows(sm, ACTION_CLEAR) == []


def test_clear_removes_the_override_and_returns_the_list(
    client: TestClient, sm: sessionmaker[Session]
) -> None:
    assert _put(client).status_code == 200
    resp = _clear(client, 1)
    assert resp.status_code == 200, resp.text
    assert _model(resp.json(), SONNET)["override"] is None
    (row,) = audit_rows(sm, ACTION_CLEAR)
    assert row.after is None
    assert row.before is not None
    assert row.before["model"] == SONNET
    with sm() as session:
        assert session.scalar(sa.select(sa.func.count()).select_from(LlmPriceOverride)) == 0


def test_clearing_a_model_with_no_override_is_404(
    client: TestClient, sm: sessionmaker[Session]
) -> None:
    resp = _clear(client, 1)
    assert resp.status_code == 404
    assert _error(resp)["code"] == "llm_price_not_set"
    assert audit_count(sm) == 0


def test_a_recreated_price_keeps_counting_versions_so_a_stale_tab_gets_409(
    client: TestClient,
) -> None:
    """The ABA of T14 (cfd4635e): clear then recreate must not restart at version 1."""
    assert _put(client).status_code == 200
    assert _put(client, expectedVersion=1, inputUsdPerMtok="4").status_code == 200
    assert _clear(client, 2).status_code == 200
    recreated = _put(client, inputUsdPerMtok="5")
    assert recreated.json()["version"] == 3
    stale = _put(client, expectedVersion=2, inputUsdPerMtok="6")
    assert stale.status_code == 409
    assert _error(stale)["code"] == "stale_write"
    assert _clear(client, 2).status_code == 409


def test_two_writers_on_one_version_give_one_200_and_one_409(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    client = _client(sm, admin, make_settings(tempfile.mkdtemp()))
    assert _put(client).status_code == 200
    codes: list[int] = []
    barrier = threading.Barrier(2)

    def writer(price: str) -> None:
        barrier.wait()
        codes.append(_put(client, expectedVersion=1, inputUsdPerMtok=price).status_code)

    threads = [threading.Thread(target=writer, args=(p,)) for p in ("4", "5")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(codes) == [200, 409]
    assert len(audit_rows(sm, ACTION_SET)) == 2


# --- refusals ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("inputUsdPerMtok", "0"),
        ("inputUsdPerMtok", "-1"),
        ("inputUsdPerMtok", "1000.01"),
        ("inputUsdPerMtok", "0.0000001"),
        ("inputUsdPerMtok", "NaN"),
        ("outputUsdPerMtok", "Infinity"),
        ("outputUsdPerMtok", "0"),
        ("cachedInputUsdPerMtok", "0"),
        ("cacheWrite5mUsdPerMtok", "-0.5"),
        ("cacheWrite1hUsdPerMtok", "2000"),
        ("tierThresholdTokens", 0),
        ("tierThresholdTokens", 10_000_001),
        ("tier2InputUsdPerMtok", "0"),
        ("tier2OutputUsdPerMtok", "1001"),
    ],
)
def test_a_price_outside_its_bounds_is_422_invalid_price_with_no_audit_row(
    field: str, value: object, client: TestClient, sm: sessionmaker[Session]
) -> None:
    resp = _put(client, **{field: value})
    assert resp.status_code == 422, resp.text
    if isinstance(resp.json()["detail"], dict):  # NaN and Infinity stop earlier, at the DTO
        assert _error(resp)["code"] == "invalid_price"
    else:
        assert value in ("NaN", "Infinity")
    assert audit_count(sm) == 0
    with sm() as session:
        assert session.scalar(sa.select(sa.func.count()).select_from(LlmPriceOverride)) == 0


def test_a_partial_tier_is_refused(client: TestClient, sm: sessionmaker[Session]) -> None:
    body = {k: v for k, v in FULL.items() if k != "tier2OutputUsdPerMtok"}
    resp = client.put(f"{BASE}/{SONNET}", json={**body, "expectedVersion": None, "reason": REASON})
    assert resp.status_code == 422
    assert _error(resp)["code"] == "invalid_price"
    assert audit_count(sm) == 0


def test_the_edges_are_accepted(client: TestClient) -> None:
    resp = _put(
        client,
        inputUsdPerMtok="1000",
        outputUsdPerMtok="0.000001",
        tierThresholdTokens=10_000_000,
        tier2InputUsdPerMtok="1000",
        tier2OutputUsdPerMtok="1000",
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.parametrize("model", ["bad model", "a" * 129, "mod/el", "mödel"])
def test_a_model_id_outside_the_pattern_is_refused(
    model: str, client: TestClient, sm: sessionmaker[Session]
) -> None:
    resp = _put(client, model)
    assert resp.status_code in (404, 422)
    if resp.status_code == 422 and isinstance(resp.json()["detail"], dict):
        assert _error(resp)["code"] == "invalid_price"
    assert audit_count(sm) == 0


@pytest.mark.parametrize("bad", [{"reason": ""}, {"reason": "ab"}, {"expectedVersion": 1.5}])
def test_a_missing_reason_or_a_loose_version_is_422(
    bad: dict[str, object], client: TestClient, sm: sessionmaker[Session]
) -> None:
    resp = _put(client, **bad)
    assert resp.status_code == 422
    assert audit_count(sm) == 0


def test_unknown_body_fields_are_refused(client: TestClient) -> None:
    assert _put(client, perToken="0.1").status_code == 422


# --- the runtime follows a committed write, and only that ----------------------------------


def test_a_committed_write_refreshes_this_process_a_refused_one_does_not(
    client: TestClient,
) -> None:
    assert claude_row(SONNET) == CLAUDE_PRICING[SONNET]
    refused = _put(client, inputUsdPerMtok="0")
    assert refused.status_code == 422
    assert claude_row(SONNET) == CLAUDE_PRICING[SONNET]
    assert _put(client).status_code == 200
    row = claude_row(SONNET)
    assert row is not None
    assert (row.input, row.output) == (0.003, 0.015)
    assert _clear(client, 1).status_code == 200
    assert claude_row(SONNET) == CLAUDE_PRICING[SONNET]


def test_a_stale_refusal_does_not_refresh(client: TestClient) -> None:
    assert _put(client).status_code == 200
    price_overrides.install(None)
    assert _put(client).status_code == 409
    assert price_overrides.current() is None


def test_a_failing_refresh_after_commit_does_not_fail_the_request(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(session: Session) -> list:  # type: ignore[type-arg]
        raise RuntimeError("db down")

    monkeypatch.setattr(llm_price_refresh, "list_overrides", boom)
    assert _put(client).status_code == 200  # committed; the 60 s job retries


# --- the container hour setting ---------------------------------------------------------------


def test_the_container_hour_is_above_zero_and_at_most_100(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    def update(value: object) -> str | None:
        with sm.begin() as session:
            try:
                BillingSettingsService(session, now=lambda: NOW).update(
                    admin,
                    fields={"code_execution_usd_per_hour": value},
                    expected_version=1,
                    reason=REASON,
                )
            except Exception as exc:
                return str(getattr(exc, "code", exc))
        return None

    for bad in (Decimal(0), Decimal("-1"), Decimal("100.000001"), Decimal("NaN")):
        assert update(bad) == "invalid_setting"
    assert update(Decimal("100")) is None


# --- authorisation ----------------------------------------------------------------------------


@pytest.mark.parametrize("role", ["student", "parent", "teacher", "school_admin"])
def test_the_router_alone_refuses_other_roles(role: str, sm: sessionmaker[Session]) -> None:
    app = FastAPI()
    app.include_router(settings_router)
    app.dependency_overrides[get_llm_price_service] = _scope_dependency(sm)
    app.dependency_overrides[get_billing_settings_service] = lambda: None
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(user_id="u1", role=role)
    probe = TestClient(app)
    assert probe.get(BASE).status_code == 403
    assert probe.put(f"{BASE}/{SONNET}", json={}).status_code == 403
    assert probe.post(f"{BASE}/{SONNET}/clear", json={}).status_code == 403
    assert audit_count(sm) == 0
