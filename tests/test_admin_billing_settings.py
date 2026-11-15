"""Admin billing settings and credit conversion rates (UD-13, UD-12; Phase 07 T14).

Pinned here: every bound of the six settings and of a conversion rate (the edge accepted, one past
it refused with the field named); one audit row per write with the before and after; none per
refusal; optimistic concurrency (two writers on one version give one 200 and one 409); the lazy
insert of the defaults; and that the router guards itself when the parent router's guard is absent.
"""

from __future__ import annotations

import threading
import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from fastapi.testclient import TestClient

from lemely.core import billing_defaults
from lemely.db.admin_billing_repo import AdminConflictError
from lemely.db.billing_settings_repo import (
    ACTION_CREDIT_RATE_CLEAR,
    ACTION_CREDIT_RATE_SET,
    ACTION_SETTINGS_UPDATE,
    BillingSettingsService,
    credit_rate_for,
    get_billing_settings,
)
from lemely.db.models.billing_ops import BillingSettings, CreditConversionRate
from lemely.db.models.enums import Role
from lemely.web.deps import AuthContext, get_auth_context
from lemely.web.routers.admin_billing_settings import (
    get_billing_settings_service,
)
from lemely.web.routers.admin_billing_settings import router as settings_router
from tests.admin_billing_db import (
    NOW,
    add_user,
    audit_count,
    audit_rows,
    billing_database,
    emptied_after,
)
from tests.tutoring_app import app_with_routers

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from httpx2 import Response
    from sqlalchemy.orm import Session, sessionmaker

BASE = "/api/admin/billing"
REASON = "quarterly pricing review"


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


def _service_dependency(
    sm: sessionmaker[Session],
) -> Callable[[], Iterator[BillingSettingsService]]:
    def dependency() -> Iterator[BillingSettingsService]:
        with sm.begin() as session:
            yield BillingSettingsService(session, now=lambda: NOW)

    return dependency


def _client(sm: sessionmaker[Session], admin_id: uuid.UUID) -> TestClient:
    app = app_with_routers(settings_router)  # a no-op once app.py mounts it
    app.dependency_overrides[get_billing_settings_service] = _service_dependency(sm)
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(
        user_id=str(admin_id), role=Role.platform_admin.value
    )
    return TestClient(app)


@pytest.fixture
def client(sm: sessionmaker[Session], admin: uuid.UUID) -> TestClient:
    return _client(sm, admin)


def _settings(sm: sessionmaker[Session]) -> dict[str, object]:
    with sm() as session:
        view = get_billing_settings(session)
    return {
        "credit_validity_months": view.credit_validity_months,
        "grace_days": view.grace_days,
        "max_extra_seats": view.max_extra_seats,
        "price_change_notice_days": view.price_change_notice_days,
        "margin_egp_per_usd": view.margin_egp_per_usd,
        "code_execution_usd_per_hour": view.code_execution_usd_per_hour,
        "version": view.version,
    }


def _put(client: TestClient, **body: object) -> Response:
    body.setdefault("expectedVersion", 1)
    body.setdefault("reason", REASON)
    return client.put(f"{BASE}/settings", json=body)


def _error(resp: Response) -> dict[str, str]:
    detail: dict[str, str] = resp.json()["detail"]
    return detail


# --- reading and the lazy defaults ------------------------------------------------------------


def test_get_returns_the_seed_defaults_and_the_documented_shape(client: TestClient) -> None:
    resp = client.get(f"{BASE}/settings")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {
        "creditValidityMonths",
        "graceDays",
        "maxExtraSeats",
        "priceChangeNoticeDays",
        "marginEgpPerUsd",
        "codeExecutionUsdPerHour",
        "version",
        "updatedAt",
        "updatedBy",
    }
    assert (
        body["creditValidityMonths"],
        body["graceDays"],
        body["maxExtraSeats"],
        body["priceChangeNoticeDays"],
    ) == (
        billing_defaults.CREDIT_VALIDITY_MONTHS,
        billing_defaults.GRACE_DAYS,
        billing_defaults.MAX_EXTRA_SEATS,
        billing_defaults.PRICE_CHANGE_NOTICE_DAYS,
    )
    assert billing_defaults.PRICE_CHANGE_NOTICE_DAYS == 14  # UD13-G
    assert (body["marginEgpPerUsd"], body["codeExecutionUsdPerHour"]) == (None, None)
    assert (body["version"], body["updatedBy"]) == (1, None)


def test_a_missing_row_is_inserted_once_by_two_concurrent_readers(
    sm: sessionmaker[Session],
) -> None:
    with sm.begin() as session:
        session.execute(sa.delete(BillingSettings))
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def read() -> None:
        try:
            with sm.begin() as session:
                barrier.wait(timeout=10)
                get_billing_settings(session)
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=read) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert errors == []
    with sm() as session:
        assert session.scalar(sa.select(sa.func.count()).select_from(BillingSettings)) == 1
    assert _settings(sm)["grace_days"] == billing_defaults.GRACE_DAYS


def test_a_read_is_never_cached(sm: sessionmaker[Session]) -> None:
    with sm() as reader:
        assert get_billing_settings(reader).grace_days == 3
        with sm.begin() as writer:
            writer.execute(sa.update(BillingSettings).values(grace_days=5))
        assert get_billing_settings(reader).grace_days == 5


# --- a settings write -------------------------------------------------------------------------


def test_an_update_writes_one_audit_row_with_before_and_after(
    client: TestClient, sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    resp = _put(client, graceDays=5, marginEgpPerUsd="50.5")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["graceDays"], body["marginEgpPerUsd"], body["version"]) == (5, "50.5", 2)
    assert body["updatedBy"] == str(admin)
    assert body["creditValidityMonths"] == 12  # a field left out is untouched
    rows = audit_rows(sm, ACTION_SETTINGS_UPDATE)
    assert len(rows) == 1
    row = rows[0]
    assert (row.admin_user_id, row.reason, row.target_kind) == (
        admin,
        REASON,
        "billing_settings",
    )
    assert row.before is not None
    assert row.after is not None
    assert (row.before["grace_days"], row.before["version"]) == (3, 1)
    assert (row.after["grace_days"], row.after["version"]) == (5, 2)
    assert (row.before["margin_egp_per_usd"], row.after["margin_egp_per_usd"]) == (None, "50.5000")
    assert audit_count(sm) == 1


def test_a_field_equal_to_its_value_is_still_an_audited_write(
    client: TestClient, sm: sessionmaker[Session]
) -> None:
    resp = _put(client, graceDays=3)
    assert resp.status_code == 200
    assert resp.json()["version"] == 2
    assert len(audit_rows(sm, ACTION_SETTINGS_UPDATE)) == 1


def test_null_clears_the_two_optional_decimals(client: TestClient) -> None:
    assert _put(client, marginEgpPerUsd="48", codeExecutionUsdPerHour="1.2").status_code == 200
    resp = _put(client, expectedVersion=2, marginEgpPerUsd=None, codeExecutionUsdPerHour=None)
    assert resp.status_code == 200
    body = resp.json()
    assert (body["marginEgpPerUsd"], body["codeExecutionUsdPerHour"]) == (None, None)


def test_decimals_leave_as_strings(client: TestClient) -> None:
    body = _put(client, marginEgpPerUsd="48.5000", codeExecutionUsdPerHour="1.25").json()
    assert (body["marginEgpPerUsd"], body["codeExecutionUsdPerHour"]) == ("48.5", "1.250000")


# (field, accepted low, accepted high, refused below, refused above)
_INT_BOUNDS = [
    ("creditValidityMonths", 1, 120, 0, 121),
    ("graceDays", 1, 7, 0, 8),
    ("maxExtraSeats", 1, 10_000, 0, 10_001),
    ("priceChangeNoticeDays", 7, 90, 6, 91),
]


@pytest.mark.parametrize(("field", "low", "high", "below", "above"), _INT_BOUNDS)
def test_each_integer_setting_accepts_its_edges_and_refuses_one_past(
    client: TestClient,
    sm: sessionmaker[Session],
    field: str,
    low: int,
    high: int,
    below: int,
    above: int,
) -> None:
    version = 1
    for ok in (low, high):
        resp = _put(client, expectedVersion=version, **{field: ok})
        assert resp.status_code == 200, (field, ok, resp.text)
        version += 1
    rows_before = audit_count(sm)
    for bad in (below, above):
        resp = _put(client, expectedVersion=version, **{field: bad})
        assert resp.status_code == 422, (field, bad)
        error = _error(resp)
        assert error["code"] == "invalid_setting"
        assert field in error["message"]
    assert audit_count(sm) == rows_before
    assert _settings(sm)["version"] == version


@pytest.mark.parametrize("bad", ["abc", 1.5, True, [3], {"a": 1}])
def test_a_non_integer_setting_is_refused(client: TestClient, bad: object) -> None:
    resp = _put(client, graceDays=bad)
    assert resp.status_code == 422


def test_an_integer_setting_cannot_be_null(client: TestClient, sm: sessionmaker[Session]) -> None:
    resp = _put(client, graceDays=None)
    assert resp.status_code == 422
    assert _error(resp)["code"] == "invalid_setting"
    assert audit_count(sm) == 0


@pytest.mark.parametrize(
    ("field", "value", "ok"),
    [
        ("marginEgpPerUsd", "0.0001", True),
        ("marginEgpPerUsd", "10000", True),
        ("marginEgpPerUsd", "10000.0000", True),
        ("marginEgpPerUsd", "0", False),
        ("marginEgpPerUsd", "-1", False),
        ("marginEgpPerUsd", "10000.0001", False),
        ("marginEgpPerUsd", "10.00001", False),
        ("marginEgpPerUsd", "1e999", False),
        ("codeExecutionUsdPerHour", "0", True),
        ("codeExecutionUsdPerHour", "1000", True),
        ("codeExecutionUsdPerHour", "0.000001", True),
        ("codeExecutionUsdPerHour", "-0.000001", False),
        ("codeExecutionUsdPerHour", "1000.000001", False),
        ("codeExecutionUsdPerHour", "0.0000001", False),
    ],
)
def test_the_decimal_settings_bounds_and_precision(
    client: TestClient, sm: sessionmaker[Session], field: str, value: str, ok: bool
) -> None:
    resp = _put(client, **{field: value})
    if ok:
        assert resp.status_code == 200, resp.text
        assert len(audit_rows(sm, ACTION_SETTINGS_UPDATE)) == 1
    else:
        assert resp.status_code == 422, resp.text
        assert _error(resp)["code"] == "invalid_setting"
        assert field in _error(resp)["message"]
        assert audit_count(sm) == 0


def test_a_non_finite_decimal_is_refused(client: TestClient, sm: sessionmaker[Session]) -> None:
    for bad in ("NaN", "Infinity", "-Infinity"):
        assert _put(client, marginEgpPerUsd=bad).status_code == 422
    assert audit_count(sm) == 0


def test_a_body_with_none_of_the_six_fields_is_refused(
    client: TestClient, sm: sessionmaker[Session]
) -> None:
    resp = _put(client)
    assert resp.status_code == 422
    assert _error(resp)["code"] == "no_setting_given"
    assert audit_count(sm) == 0
    assert _settings(sm)["version"] == 1


def test_an_unknown_field_is_refused(client: TestClient) -> None:
    assert _put(client, graceDays=4, currency="EGP").status_code == 422


def test_expected_version_is_required(client: TestClient, sm: sessionmaker[Session]) -> None:
    resp = client.put(f"{BASE}/settings", json={"graceDays": 4, "reason": REASON})
    assert resp.status_code == 422
    assert audit_count(sm) == 0


@pytest.mark.parametrize("reason", ["", "  ", "ab", None])
def test_a_missing_or_blank_reason_is_refused(
    client: TestClient, sm: sessionmaker[Session], reason: str | None
) -> None:
    body: dict[str, object] = {"graceDays": 4, "expectedVersion": 1}
    if reason is not None:
        body["reason"] = reason
    assert client.put(f"{BASE}/settings", json=body).status_code == 422
    assert audit_count(sm) == 0
    assert _settings(sm)["grace_days"] == 3


def test_a_stale_version_is_409_and_leaves_no_row(
    client: TestClient, sm: sessionmaker[Session]
) -> None:
    assert _put(client, graceDays=4).status_code == 200
    resp = _put(client, graceDays=6, expectedVersion=1)
    assert resp.status_code == 409
    assert _error(resp)["code"] == "stale_write"
    assert len(audit_rows(sm, ACTION_SETTINGS_UPDATE)) == 1
    assert _settings(sm)["grace_days"] == 4


def test_the_service_refuses_a_blank_reason_itself(sm: sessionmaker[Session]) -> None:
    """The DTO is not the only guard: the service re-checks."""
    admin = add_user(sm, Role.platform_admin)
    with sm.begin() as session, pytest.raises(Exception, match="reason") as caught:
        BillingSettingsService(session, now=lambda: NOW).update(
            admin, fields={"grace_days": 4}, expected_version=1, reason="   "
        )
    assert getattr(caught.value, "code", "") == "reason_required"
    assert audit_count(sm) == 0


def test_the_service_refuses_an_out_of_range_value_itself(sm: sessionmaker[Session]) -> None:
    admin = add_user(sm, Role.platform_admin)
    with sm.begin() as session, pytest.raises(Exception, match="graceDays") as caught:
        BillingSettingsService(session, now=lambda: NOW).update(
            admin, fields={"grace_days": 8}, expected_version=1, reason=REASON
        )
    assert getattr(caught.value, "code", "") == "invalid_setting"
    assert audit_count(sm) == 0
    assert _settings(sm)["grace_days"] == 3


def _race(
    sm: sessionmaker[Session], action: Callable[[Session, uuid.UUID], object], admin: uuid.UUID
) -> list[object]:
    """Run ``action`` in two threads at once, each on its own committed transaction."""
    barrier = threading.Barrier(2)
    outcomes: list[object] = []
    guard = threading.Lock()

    def run() -> None:
        outcome: object
        try:
            with sm.begin() as session:
                barrier.wait(timeout=10)
                outcome = action(session, admin)
        except AdminConflictError as exc:
            outcome = exc
        except BaseException as exc:
            outcome = exc
        with guard:
            outcomes.append(outcome)

    threads = [threading.Thread(target=run) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    return outcomes


def test_two_settings_writes_on_one_version_give_one_success_and_one_409(
    sm: sessionmaker[Session],
) -> None:
    admin = add_user(sm, Role.platform_admin)

    def write(session: Session, admin_id: uuid.UUID) -> object:
        return BillingSettingsService(session, now=lambda: NOW).update(
            admin_id, fields={"grace_days": 4}, expected_version=1, reason=REASON
        )

    outcomes = _race(sm, write, admin)
    stale = [o for o in outcomes if isinstance(o, AdminConflictError)]
    assert len(stale) == 1
    assert stale[0].code == "stale_write"
    assert len(outcomes) - len(stale) == 1
    assert _settings(sm)["version"] == 2
    assert len(audit_rows(sm, ACTION_SETTINGS_UPDATE)) == 1


# --- credit rates -----------------------------------------------------------------------------


def _set_rate(client: TestClient, currency: str = "EGP", **body: object) -> Response:
    body.setdefault("unitsPerMinor", "0.05")
    body.setdefault("expectedVersion", None)
    body.setdefault("reason", REASON)
    return client.put(f"{BASE}/credit-rates/{currency}", json=body)


def _clear_rate(client: TestClient, currency: str = "EGP", **body: object) -> Response:
    body.setdefault("expectedVersion", 1)
    body.setdefault("confirmStopConversions", True)
    body.setdefault("reason", REASON)
    return client.post(f"{BASE}/credit-rates/{currency}/clear", json=body)


def _rate_rows(sm: sessionmaker[Session]) -> list[tuple[str, Decimal, int]]:
    with sm() as session:
        return [
            (r.currency, r.units_per_minor, r.version)
            for r in session.scalars(sa.select(CreditConversionRate))
        ]


def test_no_rates_at_first(client: TestClient) -> None:
    resp = client.get(f"{BASE}/credit-rates")
    assert (resp.status_code, resp.json()) == (200, {"rates": []})


def test_create_replace_and_list_with_one_audit_row_each(
    client: TestClient, sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    created = _set_rate(client, unitsPerMinor="0.05")
    assert created.status_code == 200, created.text
    body = created.json()
    assert (body["currency"], body["unitsPerMinor"], body["version"]) == ("EGP", "0.050000", 1)
    assert body["updatedBy"] == str(admin)
    replaced = _set_rate(client, unitsPerMinor="0.29", expectedVersion=1)
    assert replaced.status_code == 200
    assert (replaced.json()["unitsPerMinor"], replaced.json()["version"]) == ("0.290000", 2)
    listed = client.get(f"{BASE}/credit-rates").json()["rates"]
    assert [(r["currency"], r["unitsPerMinor"], r["version"]) for r in listed] == [
        ("EGP", "0.290000", 2)
    ]
    rows = audit_rows(sm, ACTION_CREDIT_RATE_SET)
    assert len(rows) == 2
    first, second = rows
    assert first.before is None
    assert first.after is not None
    assert first.after["units_per_minor"] == "0.050000"
    assert second.before is not None
    assert second.after is not None
    assert (second.before["units_per_minor"], second.after["units_per_minor"]) == (
        "0.050000",
        "0.290000",
    )
    assert (second.before["version"], second.after["version"]) == (1, 2)
    assert audit_count(sm) == 2


def test_a_rate_is_exact_decimal_data(client: TestClient, sm: sessionmaker[Session]) -> None:
    assert _set_rate(client, unitsPerMinor="0.290000").status_code == 200
    assert _rate_rows(sm) == [("EGP", Decimal("0.290000"), 1)]
    with sm() as session:
        assert credit_rate_for(session, "EGP") == Decimal("0.290000")
        assert credit_rate_for(session, "USD") is None


def test_a_second_currency_is_independent(client: TestClient) -> None:
    assert _set_rate(client, "EGP").status_code == 200
    assert _set_rate(client, "USD", unitsPerMinor="5").status_code == 200
    rates = client.get(f"{BASE}/credit-rates").json()["rates"]
    assert [r["currency"] for r in rates] == ["EGP", "USD"]


def test_creating_over_an_existing_rate_is_409_credit_rate_exists(
    client: TestClient, sm: sessionmaker[Session]
) -> None:
    assert _set_rate(client).status_code == 200
    resp = _set_rate(client, unitsPerMinor="0.9")
    assert resp.status_code == 409
    assert _error(resp)["code"] == "credit_rate_exists"
    assert _rate_rows(sm) == [("EGP", Decimal("0.050000"), 1)]
    assert len(audit_rows(sm, ACTION_CREDIT_RATE_SET)) == 1


def test_a_stale_rate_version_is_409_stale_write(
    client: TestClient, sm: sessionmaker[Session]
) -> None:
    assert _set_rate(client).status_code == 200
    assert _set_rate(client, unitsPerMinor="0.1", expectedVersion=1).status_code == 200
    resp = _set_rate(client, unitsPerMinor="0.2", expectedVersion=1)
    assert resp.status_code == 409
    assert _error(resp)["code"] == "stale_write"
    assert _rate_rows(sm) == [("EGP", Decimal("0.100000"), 2)]
    assert len(audit_rows(sm, ACTION_CREDIT_RATE_SET)) == 2


def test_replacing_a_rate_that_is_not_set_is_409_stale_write(
    client: TestClient, sm: sessionmaker[Session]
) -> None:
    resp = _set_rate(client, expectedVersion=3)
    assert resp.status_code == 409
    assert _error(resp)["code"] == "stale_write"
    assert audit_count(sm) == 0


@pytest.mark.parametrize(
    ("units", "ok"),
    [
        ("0.000001", True),
        ("100000", True),
        ("100000.000000", True),
        ("0.0000001", False),
        ("0", False),
        ("-0.5", False),
        ("100000.000001", False),
        ("999999999999.999999", False),
        ("1.2345678", False),
        ("NaN", False),
        ("Infinity", False),
    ],
)
def test_the_rate_bounds(
    client: TestClient, sm: sessionmaker[Session], units: str, ok: bool
) -> None:
    resp = _set_rate(client, unitsPerMinor=units)
    if ok:
        assert resp.status_code == 200, resp.text
        assert len(audit_rows(sm, ACTION_CREDIT_RATE_SET)) == 1
    else:
        assert resp.status_code == 422, resp.text
        assert audit_count(sm) == 0
        assert _rate_rows(sm) == []


@pytest.mark.parametrize("units", ["abc", "", None])
def test_a_non_numeric_rate_is_refused(client: TestClient, units: object) -> None:
    assert _set_rate(client, unitsPerMinor=units).status_code == 422


def test_the_largest_rate_with_a_huge_amount_is_refused_cleanly_by_the_reader(
    client: TestClient, sm: sessionmaker[Session]
) -> None:
    """``RATE_MAX`` times a payment past ``BIGINT`` is a clean refusal, not a ``DataError``."""
    from lemely.db.billing_settings_repo import RATE_MAX
    from lemely.db.subscription_repo import credit_units_for_amount

    assert _set_rate(client, unitsPerMinor=str(RATE_MAX)).status_code == 200
    with sm() as session:
        assert credit_units_for_amount(session, amount_minor=10**14, currency="EGP") is None
        assert credit_units_for_amount(session, amount_minor=10**6, currency="EGP") == 10**11


def test_the_defaults_module_equals_the_model_server_defaults() -> None:
    """A drift would show on only one path (row created by the DB, or by ``ensure``)."""
    columns = BillingSettings.__table__.c
    expected = {
        "credit_validity_months": billing_defaults.CREDIT_VALIDITY_MONTHS,
        "grace_days": billing_defaults.GRACE_DAYS,
        "max_extra_seats": billing_defaults.MAX_EXTRA_SEATS,
        "price_change_notice_days": billing_defaults.PRICE_CHANGE_NOTICE_DAYS,
    }
    for name, value in expected.items():
        default = columns[name].server_default
        assert default is not None
        assert str(default.arg) == str(value), name


@pytest.mark.parametrize("currency", ["egp", "EG", "EGPP", "E1P", "ÉGP", "E_P"])
def test_an_invalid_currency_is_422_for_set_and_clear(
    client: TestClient, sm: sessionmaker[Session], currency: str
) -> None:
    for resp in (_set_rate(client, currency), _clear_rate(client, currency)):
        assert resp.status_code == 422, (currency, resp.text)
        assert _error(resp)["code"] == "invalid_currency"
    assert audit_count(sm) == 0
    assert _rate_rows(sm) == []


def test_a_rate_needs_a_reason(client: TestClient, sm: sessionmaker[Session]) -> None:
    assert _set_rate(client, reason="  ").status_code == 422
    assert _set_rate(client, reason="x").status_code == 422
    assert audit_count(sm) == 0


def test_clear_removes_the_rate_and_audits_it(
    client: TestClient, sm: sessionmaker[Session]
) -> None:
    assert _set_rate(client, "EGP").status_code == 200
    assert _set_rate(client, "USD", unitsPerMinor="5").status_code == 200
    resp = _clear_rate(client, "EGP")
    assert resp.status_code == 200, resp.text
    assert [r["currency"] for r in resp.json()["rates"]] == ["USD"]
    assert [r["currency"] for r in client.get(f"{BASE}/credit-rates").json()["rates"]] == ["USD"]
    with sm() as session:
        assert credit_rate_for(session, "EGP") is None
    rows = audit_rows(sm, ACTION_CREDIT_RATE_CLEAR)
    assert len(rows) == 1
    assert rows[0].after is None
    assert rows[0].before is not None
    assert (rows[0].before["currency"], rows[0].before["units_per_minor"]) == ("EGP", "0.050000")


def test_clearing_a_rate_that_is_not_set_is_404(
    client: TestClient, sm: sessionmaker[Session]
) -> None:
    resp = _clear_rate(client)
    assert resp.status_code == 404
    assert _error(resp)["code"] == "credit_rate_not_set"
    assert audit_count(sm) == 0


def test_clearing_with_a_stale_version_is_409_and_keeps_the_rate(
    client: TestClient, sm: sessionmaker[Session]
) -> None:
    assert _set_rate(client).status_code == 200
    assert _set_rate(client, unitsPerMinor="0.1", expectedVersion=1).status_code == 200
    resp = _clear_rate(client, expectedVersion=1)
    assert resp.status_code == 409
    assert _error(resp)["code"] == "stale_write"
    assert _rate_rows(sm) == [("EGP", Decimal("0.100000"), 2)]
    assert audit_rows(sm, ACTION_CREDIT_RATE_CLEAR) == []


def test_clearing_needs_a_reason(client: TestClient, sm: sessionmaker[Session]) -> None:
    assert _set_rate(client).status_code == 200
    assert _clear_rate(client, reason="  ").status_code == 422
    assert _rate_rows(sm) == [("EGP", Decimal("0.050000"), 1)]
    assert audit_rows(sm, ACTION_CREDIT_RATE_CLEAR) == []


def test_two_rate_replacements_on_one_version_give_one_success_and_one_409(
    sm: sessionmaker[Session],
) -> None:
    admin = add_user(sm, Role.platform_admin)
    with sm.begin() as session:
        BillingSettingsService(session, now=lambda: NOW).set_credit_rate(
            admin,
            currency="EGP",
            units_per_minor=Decimal("0.05"),
            expected_version=None,
            reason=REASON,
        )

    def write(session: Session, admin_id: uuid.UUID) -> object:
        return BillingSettingsService(session, now=lambda: NOW).set_credit_rate(
            admin_id,
            currency="EGP",
            units_per_minor=Decimal("0.07"),
            expected_version=1,
            reason=REASON,
        )

    outcomes = _race(sm, write, admin)
    stale = [o for o in outcomes if isinstance(o, AdminConflictError)]
    assert len(stale) == 1, outcomes
    assert stale[0].code == "stale_write"
    assert _rate_rows(sm) == [("EGP", Decimal("0.070000"), 2)]
    assert len(audit_rows(sm, ACTION_CREDIT_RATE_SET)) == 2


def test_two_creations_of_one_currency_give_one_success_and_one_409(
    sm: sessionmaker[Session],
) -> None:
    admin = add_user(sm, Role.platform_admin)

    def create(session: Session, admin_id: uuid.UUID) -> object:
        return BillingSettingsService(session, now=lambda: NOW).set_credit_rate(
            admin_id,
            currency="EGP",
            units_per_minor=Decimal("0.07"),
            expected_version=None,
            reason=REASON,
        )

    outcomes = _race(sm, create, admin)
    stale = [o for o in outcomes if isinstance(o, AdminConflictError)]
    assert len(stale) == 1, outcomes
    assert stale[0].code == "credit_rate_exists"
    assert len(_rate_rows(sm)) == 1


def test_clearing_without_the_confirmation_is_409_and_keeps_the_rate(
    client: TestClient, sm: sessionmaker[Session]
) -> None:
    assert _set_rate(client).status_code == 200
    for extra in ({"confirmStopConversions": False}, {}):
        body = {"expectedVersion": 1, "reason": REASON, **extra}
        resp = client.post(f"{BASE}/credit-rates/EGP/clear", json=body)
        assert resp.status_code == 409, resp.text
        assert _error(resp)["code"] == "rate_clear_needs_confirm"
        assert "fail closed" in _error(resp)["message"]
    assert _rate_rows(sm) == [("EGP", Decimal("0.050000"), 1)]
    assert audit_rows(sm, ACTION_CREDIT_RATE_CLEAR) == []


def test_a_stale_writer_cannot_overwrite_a_cleared_and_recreated_rate(
    client: TestClient, sm: sessionmaker[Session]
) -> None:
    """Both admins loaded version 1; one clears and recreates; the other's write is stale."""
    assert _set_rate(client, unitsPerMinor="10").status_code == 200
    assert _clear_rate(client, expectedVersion=1).status_code == 200
    recreated = _set_rate(client, unitsPerMinor="1000")
    assert recreated.status_code == 200
    assert recreated.json()["version"] == 2
    stale = _set_rate(client, unitsPerMinor="11", expectedVersion=1)
    assert stale.status_code == 409
    assert _error(stale)["code"] == "stale_write"
    assert _clear_rate(client, expectedVersion=1).status_code == 409
    assert _rate_rows(sm) == [("EGP", Decimal("1000.000000"), 2)]


def test_a_recreated_rate_continues_past_every_earlier_version(client: TestClient) -> None:
    assert _set_rate(client).status_code == 200
    assert _set_rate(client, unitsPerMinor="0.1", expectedVersion=1).status_code == 200
    assert _set_rate(client, unitsPerMinor="0.2", expectedVersion=2).status_code == 200
    assert _clear_rate(client, expectedVersion=3).status_code == 200
    assert _set_rate(client, unitsPerMinor="0.3").json()["version"] == 4
    # another currency is unaffected
    assert _set_rate(client, "USD", unitsPerMinor="5").json()["version"] == 1


# --- authorisation ----------------------------------------------------------------------------


def test_the_router_carries_its_own_platform_admin_guard() -> None:
    guards = [d.dependency for d in settings_router.dependencies]
    assert len(guards) == 1
    guard = guards[0]
    assert guard is not None
    cells = dict(zip(guard.__code__.co_freevars, guard.__closure__ or (), strict=True))
    assert cells["allowed_values"].cell_contents == frozenset({"platform_admin"})


@pytest.mark.parametrize("role", ["student", "parent", "teacher", "school_admin"])
def test_the_router_alone_refuses_other_roles(role: str, sm: sessionmaker[Session]) -> None:
    """Defence in depth: with no parent router and no per-route guard, the lane still refuses."""
    app = FastAPI()
    app.include_router(settings_router)
    app.dependency_overrides[get_billing_settings_service] = _service_dependency(sm)
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(user_id="u1", role=role)
    probe = TestClient(app)
    assert probe.get(f"{BASE}/settings").status_code == 403
    assert probe.get(f"{BASE}/credit-rates").status_code == 403
    assert probe.put(f"{BASE}/settings", json={}).status_code == 403
    assert probe.put(f"{BASE}/credit-rates/EGP", json={}).status_code == 403
    assert probe.post(f"{BASE}/credit-rates/EGP/clear", json={}).status_code == 403


def test_the_router_alone_refuses_an_anonymous_caller(sm: sessionmaker[Session]) -> None:
    app = FastAPI()
    app.include_router(settings_router)
    app.dependency_overrides[get_billing_settings_service] = _service_dependency(sm)
    assert TestClient(app).get(f"{BASE}/settings").status_code == 401


def test_the_five_routes_are_mounted_in_the_application() -> None:
    from lemely.web import create_app
    from tests.tutoring_app import flatten_routes

    mounted = {
        (method, route.path)
        for route in flatten_routes(create_app().router)
        for method in route.methods or ()
    }
    assert {
        ("GET", f"{BASE}/settings"),
        ("PUT", f"{BASE}/settings"),
        ("GET", f"{BASE}/credit-rates"),
        ("PUT", f"{BASE}/credit-rates/{{currency}}"),
        ("POST", f"{BASE}/credit-rates/{{currency}}/clear"),
    } <= mounted
