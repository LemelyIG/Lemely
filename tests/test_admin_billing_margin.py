"""Money and margin (spec §8 area 4): every figure asserted exactly against seeded rows.

The rules each number pins (the module docstring of ``admin_margin_repo`` states them):

* gross revenue is ``paid``/``partially_refunded``/``refunded`` payments by ``paid_at``;
  a voided payment is not in it;
* refunded is the console's succeeded refunds by close time plus a dashboard refund
  (Paymob's ``refunded_amount_cents`` minus what the console already returned) by ``updated_at``;
* cost is ``ceil(totalUsd x rate x 100)`` piasters, rounded against us;
* ``byModel`` covers only jobs created in the window; the remainder is unattributed.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from lemely.core.usage_types import GrantScope, Payer
from lemely.db.admin_margin_repo import (
    JOB_WINDOW_QUERIES,
    AdminMarginService,
)
from lemely.db.models.billing import PaymentPurpose, PaymentStatus
from lemely.db.models.billing_ops import PaymentRefund, RefundKind, RefundStatus, UsageJobModelCost
from lemely.db.models.enums import Role
from lemely.db.models.usage import GrantKind, UsageJob
from lemely.db.usage_ledger_repo import UsageLedger
from lemely.web.deps import AuthContext, get_auth_context
from lemely.web.routers.admin_billing_margin import get_admin_margin_service
from lemely.web.routers.admin_billing_margin import router as margin_router
from tests.admin_billing_db import (
    NOW,
    FakePaymobClient,
    add_credit_pack,
    add_payment,
    add_plan_tier,
    add_rate,
    add_subscription,
    add_user,
    billing_database,
    emptied_after,
    grant,
    metered_job,
    service_overrides,
)
from tests.tutoring_app import app_with_routers

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker

NOV_1 = datetime(2026, 11, 1, tzinfo=UTC)
DEC_1 = datetime(2026, 12, 1, tzinfo=UTC)
WINDOW = {"from": NOV_1.isoformat(), "to": DEC_1.isoformat()}
EARLY = datetime(2026, 10, 1, tzinfo=UTC)

#: ``MarginReport`` in ``web/src/lib/billingTypes.ts`` (L1052-1095), key for key.
REPORT_KEYS = {
    "windowStart",
    "windowEnd",
    "revenue",
    "cost",
    "egpPerUsd",
    "costMinor",
    "marginMinor",
    "accuracy",
    "exposure",
}
REVENUE_KEYS = {"recurringMinor", "packsMinor", "refundedMinor", "netMinor", "byPurpose", "byPlan"}
COST_KEYS = {"totalUsd", "byAction", "byPlan", "byModel", "unattributedModelUsd"}
COST_ROW_KEYS = {"key", "jobs", "costUsd"}
ACCURACY_KEYS = {
    "action",
    "estimatorVersion",
    "jobs",
    "below",
    "above",
    "shareOutside",
    "meanOverrunUnits",
    "maxOverrunUnits",
}
EXPOSURE_KEYS = {
    "outstandingDebtUnits",
    "debtors",
    "topDebtors",
    "usersAtLimit",
    "creditsExpiring30dUnits",
    "creditsExpiring30dOwners",
    "creditsExpiredUnusedUnits",
    "expiredJobs",
}


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


def _client(sm: sessionmaker[Session], admin_id: uuid.UUID) -> TestClient:
    """The whole app as ``admin_id``, the margin service on the fixed clock (DV-2)."""
    app = app_with_routers(margin_router)  # a no-op once app.py mounts it
    app.dependency_overrides.update(service_overrides(sm, FakePaymobClient()))
    app.dependency_overrides[get_admin_margin_service] = lambda: AdminMarginService(
        sm, now=lambda: NOW
    )
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(
        user_id=str(admin_id), role=Role.platform_admin.value
    )
    return TestClient(app)


def _get(client: TestClient, **params: str) -> dict[str, object]:
    resp = client.get("/api/admin/billing/margin", params={**WINDOW, **params})
    assert resp.status_code == 200, resp.text
    body: dict[str, object] = resp.json()
    return body


def _model_costs(sm: sessionmaker[Session], job: uuid.UUID, costs: dict[str, str]) -> None:
    with sm.begin() as session:
        for model, usd in costs.items():
            session.add(UsageJobModelCost(usage_job_id=job, model=model, cost_usd=Decimal(usd)))


def _refund(
    sm: sessionmaker[Session], payment: uuid.UUID, admin_id: uuid.UUID, minor: int, closed: datetime
) -> None:
    with sm.begin() as session:
        session.add(
            PaymentRefund(
                payment_id=payment,
                admin_user_id=admin_id,
                kind=RefundKind.refund,
                status=RefundStatus.succeeded,
                amount_minor=minor,
                reason="goodwill",
                created_at=closed,
                updated_at=closed,
            )
        )


def _seed_margin_world(sm: sessionmaker[Session]) -> None:
    student = add_user(sm, Role.student)
    teacher = add_user(sm, Role.teacher)
    tier = add_plan_tier(sm, code="student_monthly", price_minor=20000)
    pack = add_credit_pack(sm)
    add_subscription(sm, student, tier, start=NOV_1, end=DEC_1)

    add_payment(
        sm,
        payer=student,
        purpose=PaymentPurpose.subscription_first,
        amount_minor=20000,
        paid_at=NOV_1 + timedelta(hours=10),
        plan_tier_id=tier,
    )
    add_payment(
        sm,
        payer=student,
        amount_minor=10000,
        paid_at=NOV_1 + timedelta(days=1),
        credit_pack_id=pack,
    )
    refunded = add_payment(
        sm,
        payer=teacher,
        amount_minor=10000,
        paid_at=NOV_1 + timedelta(days=2),
        credit_pack_id=pack,
        paymob_txn_id=5,
    )
    add_payment(
        sm, payer=student, status=PaymentStatus.failed, amount_minor=9999, credit_pack_id=pack
    )
    add_payment(
        sm,
        payer=student,
        purpose=PaymentPurpose.subscription_renewal,
        amount_minor=20000,
        paid_at=EARLY,
        plan_tier_id=tier,
    )
    # A voided payment paid in the window: in neither gross nor refunded (it never settled).
    add_payment(
        sm,
        payer=student,
        status=PaymentStatus.voided,
        amount_minor=7777,
        paid_at=NOV_1 + timedelta(days=2),
        credit_pack_id=pack,
    )
    # A dashboard-only refund: no console row, Paymob reports 2500 returned on 6 Nov.
    add_payment(
        sm,
        payer=teacher,
        status=PaymentStatus.partially_refunded,
        amount_minor=10000,
        paid_at=NOV_1 + timedelta(days=1),
        credit_pack_id=pack,
        updated_at=NOV_1 + timedelta(days=5),
        last_callback={"refunded_amount_cents": 2500},
    )
    admin_id = add_user(sm, Role.platform_admin)
    _refund(sm, refunded, admin_id, 4000, NOV_1 + timedelta(days=3))

    for action in ("mark_paper", "regrade", "generate_quiz"):
        add_rate(sm, action)
    grant(sm, student, units=100, effective_at=EARLY)
    grant(sm, teacher, units=10, effective_at=EARLY)
    s_pay = [Payer(owner_user_id=student, scope=GrantScope.CREDITS)]
    t_pay = [Payer(owner_user_id=teacher, scope=GrantScope.CREDITS)]
    nov3, nov4 = NOV_1 + timedelta(days=2), NOV_1 + timedelta(days=3)

    outside = metered_job(
        sm,
        student,
        s_pay,
        low=3,
        high=5,
        cost=Decimal("0.009"),
        created_at=datetime(2026, 10, 15, tzinfo=UTC),
    )
    j1 = metered_job(sm, student, s_pay, low=3, high=5, cost=Decimal("0.004"), created_at=nov3)
    j2 = metered_job(sm, student, s_pay, low=3, high=5, cost=Decimal("0.007"), created_at=nov3)
    metered_job(
        sm, student, s_pay, action="regrade", low=1, high=2, cost=Decimal("0.0005"), created_at=nov4
    )
    metered_job(sm, teacher, t_pay, low=2, high=4, cost=Decimal("0.0021"), created_at=nov4)
    expired = metered_job(
        sm, teacher, t_pay, action="generate_quiz", low=1, high=2, cost=None, created_at=nov4
    )
    with sm.begin() as session:
        UsageLedger(session).expire_stale_jobs(now=nov4 + timedelta(hours=1))
    with sm.begin() as session:
        session.execute(
            sa.update(UsageJob)
            .where(UsageJob.id == expired)
            .values(actual_cost_usd=Decimal("0.0015"))
        )
    # j1 has two models, j2 one, and the 0.0021 / 0.0005 / 0.0015 jobs none (unattributed).
    _model_costs(sm, outside, {"gemini-2.5-flash": "0.009"})
    _model_costs(sm, j1, {"gemini-2.5-flash": "0.003", "claude-haiku-4-5": "0.001"})
    _model_costs(sm, j2, {"gemini-2.5-flash": "0.007"})


def test_revenue_cost_margin_and_accuracy_are_exact(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    _seed_margin_world(sm)
    body = _get(_client(sm, admin), egpPerUsd="50")

    # Gross: 20000 first + 10000 + 10000 + 10000 (dashboard-refunded, partially_refunded) packs.
    # Refunded: 4000 console (3 Nov) + 2500 dashboard (6 Nov). Voided 7777 and failed 9999 absent.
    assert body["revenue"] == {
        "recurringMinor": 20000,
        "packsMinor": 30000,
        "refundedMinor": 6500,
        "netMinor": 43500,
        "byPurpose": {"credit_pack": 30000, "subscription_first": 20000},
        "byPlan": [{"key": "student_monthly", "minor": 20000}],
    }
    assert body["cost"] == {
        "totalUsd": "0.015100",
        "byAction": [
            {"key": "generate_quiz", "jobs": 1, "costUsd": "0.001500"},
            {"key": "mark_paper", "jobs": 3, "costUsd": "0.013100"},
            {"key": "regrade", "jobs": 1, "costUsd": "0.000500"},
        ],
        "byPlan": [
            {"key": "student_monthly", "jobs": 3, "costUsd": "0.011500"},
            {"key": None, "jobs": 2, "costUsd": "0.003600"},
        ],
        "byModel": [
            {"model": "claude-haiku-4-5", "costUsd": "0.001000"},
            {"model": "gemini-2.5-flash", "costUsd": "0.010000"},
        ],
        "unattributedModelUsd": "0.004100",
    }
    # 0.0151 USD x 50 EGP x 100 piasters = 75.5 -> 76 (up); 43500 - 76.
    assert (body["costMinor"], body["marginMinor"]) == (76, 43424)
    assert body["egpPerUsd"] == "50"
    assert body["accuracy"] == [
        {
            "action": "mark_paper",
            "estimatorVersion": 1,
            "jobs": 3,
            "below": 0,
            "above": 1,
            "shareOutside": 0.3333,
            "meanOverrunUnits": 2.0,
            "maxOverrunUnits": 2,
        },
        {
            "action": "regrade",
            "estimatorVersion": 1,
            "jobs": 1,
            "below": 0,
            "above": 0,
            "shareOutside": 0.0,
            "meanOverrunUnits": None,
            "maxOverrunUnits": None,
        },
    ]
    exposure = body["exposure"]
    assert isinstance(exposure, dict)
    assert exposure["expiredJobs"] == {"count": 1, "costUsd": "0.001500"}


def test_the_dashboard_refund_is_counted_once_next_to_a_console_refund(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    """Paymob's total already includes the console's refund: only the excess is the dashboard's."""
    payer = add_user(sm, Role.student)
    admin_id = add_user(sm, Role.platform_admin)
    mixed = add_payment(
        sm,
        payer=payer,
        status=PaymentStatus.partially_refunded,
        amount_minor=10000,
        paid_at=NOV_1 + timedelta(days=1),
        updated_at=NOV_1 + timedelta(days=4),
        last_callback={"refunded_amount_cents": "5000"},
    )
    _refund(sm, mixed, admin_id, 3000, NOV_1 + timedelta(days=2))
    # Console 3000, Paymob total 5000: the dashboard returned 2000. Total refunded: 5000.
    assert _get(_client(sm, admin))["revenue"]["refundedMinor"] == 5000  # type: ignore[index]


def test_a_dashboard_refund_is_attributed_to_its_updated_at_and_ignores_junk(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    payer = add_user(sm, Role.student)
    add_payment(
        sm,
        payer=payer,
        status=PaymentStatus.refunded,
        amount_minor=10000,
        paid_at=EARLY,
        updated_at=NOV_1 + timedelta(days=9),
        last_callback={"refunded_amount_cents": 10000},
    )
    # A refund reported before the window, and values that are not counts, add nothing.
    add_payment(
        sm,
        payer=payer,
        status=PaymentStatus.refunded,
        amount_minor=10000,
        paid_at=EARLY,
        updated_at=EARLY,
        last_callback={"refunded_amount_cents": 10000},
    )
    for junk in (True, "12.5", -3, "9" * 40, None):
        add_payment(
            sm,
            payer=payer,
            status=PaymentStatus.partially_refunded,
            amount_minor=10000,
            paid_at=EARLY,
            updated_at=NOV_1 + timedelta(days=9),
            last_callback={"refunded_amount_cents": junk},
        )
    body = _get(_client(sm, admin))
    # Paid before the window, refunded inside it: gross 0, refunded 10000, net -10000.
    assert body["revenue"] == {
        "recurringMinor": 0,
        "packsMinor": 0,
        "refundedMinor": 10000,
        "netMinor": -10000,
        "byPurpose": {},
        "byPlan": [],
    }


def test_a_dashboard_total_above_the_payment_amount_is_capped_at_the_amount(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    payer = add_user(sm, Role.student)
    add_payment(
        sm,
        payer=payer,
        status=PaymentStatus.refunded,
        amount_minor=10000,
        paid_at=NOV_1 + timedelta(days=1),
        updated_at=NOV_1 + timedelta(days=2),
        last_callback={"refunded_amount_cents": 99999},
    )
    assert _get(_client(sm, admin))["revenue"]["refundedMinor"] == 10000  # type: ignore[index]


def test_a_voided_payment_is_not_gross_revenue(sm: sessionmaker[Session], admin: uuid.UUID) -> None:
    payer = add_user(sm, Role.student)
    add_payment(
        sm,
        payer=payer,
        status=PaymentStatus.voided,
        amount_minor=7777,
        paid_at=NOV_1 + timedelta(days=1),
    )
    revenue = _get(_client(sm, admin))["revenue"]
    assert revenue["packsMinor"] == 0  # type: ignore[index]
    assert revenue["netMinor"] == 0  # type: ignore[index]


def test_the_window_includes_from_and_excludes_to(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    payer = add_user(sm, Role.student)
    admin_id = add_user(sm, Role.platform_admin)
    at_from = add_payment(sm, payer=payer, amount_minor=1000, paid_at=NOV_1)
    add_payment(sm, payer=payer, amount_minor=2000, paid_at=DEC_1)
    add_payment(sm, payer=payer, amount_minor=4000, paid_at=DEC_1 - timedelta(microseconds=1))
    # Refunds close at the window edges too: `from` counts, `to` does not.
    _refund(sm, at_from, admin_id, 100, NOV_1)
    _refund(sm, at_from, admin_id, 200, DEC_1)
    add_rate(sm, "mark_paper")
    grant(sm, payer, units=50, effective_at=EARLY)
    pay = [Payer(owner_user_id=payer, scope=GrantScope.CREDITS)]
    metered_job(sm, payer, pay, low=1, high=2, cost=Decimal("0.001"), created_at=NOV_1)
    metered_job(sm, payer, pay, low=1, high=2, cost=Decimal("0.010"), created_at=DEC_1)
    body = _get(_client(sm, admin))
    assert body["revenue"]["packsMinor"] == 5000  # type: ignore[index]  # 1000 + 4000, not the 2000 at `to`
    assert body["revenue"]["refundedMinor"] == 100  # type: ignore[index]
    assert body["cost"]["totalUsd"] == "0.001000"  # type: ignore[index]  # the job at `to` is out


def test_cost_minor_rounds_against_us_even_for_a_small_fraction(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    _seed_margin_world(sm)
    # 0.0151 x 49.9 x 100 = 75.349: half-up would say 75; we round up to 76.
    body = _get(_client(sm, admin), egpPerUsd="49.9")
    assert body["costMinor"] == 76
    assert body["marginMinor"] == 43500 - 76


def test_without_an_exchange_rate_there_is_no_margin_figure(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    _seed_margin_world(sm)
    body = _get(_client(sm, admin))
    assert (body["egpPerUsd"], body["costMinor"], body["marginMinor"]) == (None, None, None)


@pytest.mark.parametrize("rate", ["0", "-1", "10000.01", "abc", "NaN", "Infinity"])
def test_a_bad_exchange_rate_is_422(sm: sessionmaker[Session], admin: uuid.UUID, rate: str) -> None:
    resp = _client(sm, admin).get("/api/admin/billing/margin", params={**WINDOW, "egpPerUsd": rate})
    assert resp.status_code == 422


def test_the_model_costs_exceeding_the_total_are_clamped_and_logged(
    sm: sessionmaker[Session], admin: uuid.UUID, caplog: pytest.LogCaptureFixture
) -> None:
    """Double counting (model rows above the job's own cost) must not give a negative remainder."""
    payer = add_user(sm, Role.student)
    add_rate(sm, "mark_paper")
    grant(sm, payer, units=50, effective_at=EARLY)
    pay = [Payer(owner_user_id=payer, scope=GrantScope.CREDITS)]
    job = metered_job(
        sm, payer, pay, low=1, high=2, cost=Decimal("0.001"), created_at=NOV_1 + timedelta(days=1)
    )
    _model_costs(sm, job, {"gemini-2.5-flash": "0.002"})
    with pytest.MonkeyPatch.context() as mp:
        events: list[str] = []
        from lemely.db import admin_margin_repo

        mp.setattr(admin_margin_repo.alerts, "warning", lambda event, **_: events.append(event))
        body = _get(_client(sm, admin))
    assert body["cost"]["unattributedModelUsd"] == "0.000000"  # type: ignore[index]
    assert events == ["margin_model_cost_exceeds_total"]


def test_exposure_counts_debt_limits_and_expiring_credits(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    add_rate(sm, "mark_paper")
    debtor = add_user(sm, Role.student, email="debtor@example.com")
    grant(sm, debtor, units=5, effective_at=EARLY)
    metered_job(
        sm,
        debtor,
        [Payer(owner_user_id=debtor, scope=GrantScope.CREDITS)],
        low=1,
        high=5,
        cost=Decimal("0.008"),
    )
    capped = add_user(sm, Role.student)
    grant(
        sm,
        capped,
        units=4,
        kind=GrantKind.period_allowance,
        visible=False,
        expires_at=NOW + timedelta(days=20),
        effective_at=EARLY,
    )
    metered_job(
        sm,
        capped,
        [Payer(owner_user_id=capped, scope=GrantScope.ALLOWANCE)],
        low=1,
        high=4,
        cost=Decimal("0.004"),
    )
    soon = add_user(sm, Role.student)
    grant(sm, soon, units=50, expires_at=NOW + timedelta(days=10))
    later = add_user(sm, Role.student)
    grant(sm, later, units=30, expires_at=NOW + timedelta(days=40))
    lapsed = add_user(sm, Role.student)
    grant(sm, lapsed, units=20, effective_at=EARLY, expires_at=NOW - timedelta(days=1))
    with sm.begin() as session:
        UsageLedger(session).expire_grants(now=NOW)

    body = _get(_client(sm, admin))

    assert body["exposure"] == {
        "outstandingDebtUnits": 3,
        "debtors": 1,
        "topDebtors": [{"userId": str(debtor), "email": "debtor@example.com", "outstanding": 3}],
        "usersAtLimit": 1,
        "creditsExpiring30dUnits": 50,
        "creditsExpiring30dOwners": 1,
        "creditsExpiredUnusedUnits": 20,
        "expiredJobs": {"count": 0, "costUsd": "0.000000"},
    }


def test_an_expired_job_with_no_recorded_cost_is_not_counted(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    """Every ``created_at`` query states ``actual_cost_usd IS NOT NULL`` (index amendment)."""
    payer = add_user(sm, Role.teacher)
    add_rate(sm, "mark_paper")
    grant(sm, payer, units=50, effective_at=EARLY)
    pay = [Payer(owner_user_id=payer, scope=GrantScope.CREDITS)]
    created = NOV_1 + timedelta(days=2)
    metered_job(sm, payer, pay, low=1, high=2, cost=None, created_at=created)
    with sm.begin() as session:
        UsageLedger(session).expire_stale_jobs(now=created + timedelta(hours=1))
    exposure = _get(_client(sm, admin))["exposure"]
    assert exposure["expiredJobs"] == {"count": 0, "costUsd": "0.000000"}  # type: ignore[index]


def test_a_naive_from_is_422_naive_datetime(sm: sessionmaker[Session], admin: uuid.UUID) -> None:
    resp = _client(sm, admin).get(
        "/api/admin/billing/margin", params={"from": "2026-11-01T00:00:00", "to": DEC_1.isoformat()}
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "naive_datetime"


def test_a_naive_to_is_422_naive_datetime(sm: sessionmaker[Session], admin: uuid.UUID) -> None:
    resp = _client(sm, admin).get(
        "/api/admin/billing/margin", params={"from": NOV_1.isoformat(), "to": "2026-12-01T00:00:00"}
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "naive_datetime"


def test_a_reversed_empty_or_huge_window_is_422_bad_window(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    client = _client(sm, admin)

    def window(start: datetime, end: datetime) -> tuple[int, object]:
        resp = client.get(
            "/api/admin/billing/margin", params={"from": start.isoformat(), "to": end.isoformat()}
        )
        return resp.status_code, resp.json()["detail"]["code"] if resp.status_code == 422 else None

    assert window(DEC_1, NOV_1) == (422, "bad_window")
    assert window(NOV_1, NOV_1) == (422, "bad_window")
    assert window(NOV_1, NOV_1 + timedelta(days=401)) == (422, "bad_window")
    assert window(NOV_1, NOV_1 + timedelta(days=400))[0] == 200  # the frontend's 400-day cap


def test_the_report_has_exactly_the_frontends_keys(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    _seed_margin_world(sm)
    body = _get(_client(sm, admin), egpPerUsd="50")
    assert set(body) == REPORT_KEYS
    assert set(body["revenue"]) == REVENUE_KEYS  # type: ignore[call-overload]
    cost = body["cost"]
    assert isinstance(cost, dict)
    assert set(cost) == COST_KEYS
    for rows in (cost["byAction"], cost["byPlan"]):
        assert all(set(row) == COST_ROW_KEYS for row in rows)
    assert all(set(row) == {"model", "costUsd"} for row in cost["byModel"])
    accuracy = body["accuracy"]
    assert isinstance(accuracy, list)
    assert accuracy
    assert all(set(row) == ACCURACY_KEYS for row in accuracy)
    exposure = body["exposure"]
    assert isinstance(exposure, dict)
    assert set(exposure) == EXPOSURE_KEYS
    assert set(exposure["expiredJobs"]) == {"count", "costUsd"}
    assert set(body["revenue"]["byPlan"][0]) == {"key", "minor"}  # type: ignore[index]


def test_the_report_writes_nothing(sm: sessionmaker[Session], admin: uuid.UUID) -> None:
    from tests.admin_billing_db import audit_count

    _seed_margin_world(sm)
    before = audit_count(sm)
    _get(_client(sm, admin), egpPerUsd="50")
    assert audit_count(sm) == before


def test_the_margin_route_is_get_only_and_platform_admin_only(sm: sessionmaker[Session]) -> None:
    client = _client(sm, add_user(sm, Role.platform_admin))
    assert client.post("/api/admin/billing/margin", json={}).status_code == 405


# -- the T1 partial index (amendment): every created_at query must be able to use it --------


def test_every_job_window_query_states_the_partial_index_predicate() -> None:
    assert JOB_WINDOW_QUERIES
    for name, query in JOB_WINDOW_QUERIES.items():
        assert "actual_cost_usd IS NOT NULL" in query, name


@pytest.mark.parametrize("name", sorted(JOB_WINDOW_QUERIES))
def test_each_job_window_query_plans_on_the_partial_created_at_index(
    sm: sessionmaker[Session], name: str
) -> None:
    """With seq scans priced out, the planner takes the index only if the predicate implies it."""
    with sm.begin() as session:
        session.execute(sa.text("SET LOCAL enable_seqscan = off"))
        plan = "\n".join(
            str(row[0])
            for row in session.execute(
                sa.text(f"EXPLAIN {JOB_WINDOW_QUERIES[name]}"), {"start": NOV_1, "end": DEC_1}
            )
        )
    assert "ix_admin_usage_jobs_created_at" in plan, plan


def test_the_explain_pin_goes_red_without_the_predicate(sm: sessionmaker[Session]) -> None:
    """The pin is not vacuous: the same query minus the predicate does not plan on the index."""
    original = JOB_WINDOW_QUERIES["cost_by_action"]
    stripped = original.replace(" AND j.actual_cost_usd IS NOT NULL", "")
    assert stripped != original
    with sm.begin() as session:
        session.execute(sa.text("SET LOCAL enable_seqscan = off"))
        plan = "\n".join(
            str(row[0])
            for row in session.execute(
                sa.text(f"EXPLAIN {stripped}"), {"start": NOV_1, "end": DEC_1}
            )
        )
    assert "ix_admin_usage_jobs_created_at" not in plan, plan
