"""Customer view reads (spec §8 area 2): search, and the whole money picture of one account."""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa

from lemely.core.usage_types import GrantScope, Payer
from lemely.db.admin_billing_repo import PaymentView, audited, payment_views
from lemely.db.admin_customer_repo import escape_like
from lemely.db.models.billing import Payment, PaymentStatus
from lemely.db.models.billing_ops import PaymentRefund, RefundKind, RefundStatus
from lemely.db.models.enums import Role
from lemely.db.models.team import (
    AssistantRole,
    TeacherMember,
    TeacherMemberKind,
    TeacherMemberStatus,
)
from lemely.db.models.usage import GrantKind, UsageGrant, UsageGrantBalance, UsageJob
from lemely.db.models.users import ParentChildLink
from lemely.db.usage_ledger_repo import UsageLedger
from tests.admin_billing_db import (
    NOW,
    add_payment,
    add_plan_tier,
    add_rate,
    add_subscription,
    add_user,
    admin_client,
    billing_database,
    emptied_after,
    grant,
    metered_job,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker

URL = "/api/admin/billing/customers"

# The frontend contract, copied from web/src/lib/billingTypes.ts (CustomerDetail and the
# interfaces it nests). The backend adds `paymentId` and `currency` to the refund (DV-21).
CUSTOMER_DETAIL_KEYS = {
    "user", "balance", "subscriptions", "grants", "debts", "usageJobs", "payments", "seats",
    "assistants", "seatedWith", "parents", "children", "audit",
}  # fmt: skip
USER_KEYS = {"id", "email", "displayName", "role", "createdAt"}
BALANCE_KEYS = {"allowanceAvailable", "creditsAvailable", "seatAvailable", "outstandingDebt"}
SUBSCRIPTION_KEYS = {
    "id", "planTierId", "planCode", "planName", "status", "payerUserId", "currentPeriodStart",
    "currentPeriodEnd", "cancelAtPeriodEnd", "pendingPlanTierId", "graceUntil", "extraSeats",
    "pendingExtraSeats", "paymobSubscriptionId", "isManuallyActivated", "periods",
}  # fmt: skip
PERIOD_KEYS = {"periodStart", "periodEnd", "paymentId"}
GRANT_KEYS = {
    "id", "kind", "visible", "units", "remaining", "held", "effectiveAt", "expiresAt",
    "teacherMemberId", "paymentId",
}  # fmt: skip
DEBT_KEYS = {"id", "jobId", "units", "outstanding", "createdAt"}
JOB_KEYS = {
    "jobId", "action", "status", "estimateLow", "estimateHigh", "estimatorVersion", "rateVersion",
    "reserved", "charged", "debtCreated", "actualCostUsd", "actualUnits", "outsideRange",
    "createdAt", "settledAt",
}  # fmt: skip
PAYMENT_KEYS = {
    "id", "payerUserId", "beneficiaryUserId", "purpose", "status", "amountMinor", "currency",
    "refundedMinor", "paymobOrderId", "paymobTxnId", "planTierId", "creditPackId",
    "subscriptionId", "seatQuantity", "createdAt", "paidAt", "refunds",
}  # fmt: skip
REFUND_KEYS = {
    "id", "kind", "status", "amountMinor", "reason", "adminUserId", "clawedBackUnits",
    "createdAt", "updatedAt", "paymentId", "currency",
}  # fmt: skip
MEMBER_KEYS = {
    "memberId", "userId", "email", "kind", "status", "scopeSubjects", "scopeActions",
    "rolePreset", "capUnits", "capPeriod", "leavesAt",
}  # fmt: skip
LINKED_KEYS = {"userId", "email", "displayName"}
AUDIT_KEYS = {
    "id", "adminUserId", "action", "targetKind", "targetId", "reason", "before", "after",
    "createdAt",
}  # fmt: skip


@pytest.fixture(scope="module")
def billing_db() -> Iterator[sessionmaker[Session]]:
    with billing_database() as factory:
        yield factory


@pytest.fixture
def sm(billing_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(billing_db)


@pytest.fixture
def world(sm: sessionmaker[Session]) -> dict[str, uuid.UUID]:
    admin = add_user(sm, Role.platform_admin)
    student = add_user(sm, Role.student, email="s1@example.com", display_name="Amira Hassan")
    parent = add_user(sm, Role.parent, email="p1@example.com", display_name="Parent One")
    teacher = add_user(sm, Role.teacher, email="t1@example.com", display_name="Teacher One")
    assistant = add_user(sm, Role.teacher, email="a1@example.com", display_name="Assistant One")
    with sm.begin() as session:
        session.add(ParentChildLink(parent_id=parent, child_id=student))
        session.add(
            TeacherMember(
                teacher_user_id=teacher,
                member_user_id=student,
                kind=TeacherMemberKind.student_seat,
                status=TeacherMemberStatus.active,
                scope_subjects=["0625"],
                scope_actions=["mark_paper"],
            )
        )
        session.add(
            TeacherMember(
                teacher_user_id=teacher,
                member_user_id=assistant,
                kind=TeacherMemberKind.assistant,
                status=TeacherMemberStatus.active,
                role_preset=AssistantRole.co_teacher,
                permissions={},
            )
        )
    tier = add_plan_tier(sm)
    sub = add_subscription(sm, student, tier)
    grant(
        sm, student, units=1000, kind=GrantKind.period_allowance, visible=False,
        expires_at=NOW + timedelta(days=20),
    )  # fmt: skip
    grant(sm, student, units=300)
    add_rate(sm, "mark_paper")
    metered_job(
        sm,
        student,
        [
            Payer(owner_user_id=student, scope=GrantScope.ALLOWANCE),
            Payer(owner_user_id=student, scope=GrantScope.CREDITS),
        ],
        low=3,
        high=5,
        cost=Decimal("0.004"),
    )
    payment = add_payment(sm, payer=student, paymob_order_id=777001, paymob_txn_id=888001)
    with sm.begin() as session:
        audited(session, admin, "customer.grant", "user", student, "seeded", None, None)
    return {
        "admin": admin, "student": student, "parent": parent, "teacher": teacher,
        "assistant": assistant, "tier": tier, "sub": sub, "payment": payment,
    }  # fmt: skip


def _search(
    sm: sessionmaker[Session], admin: uuid.UUID, q: str, **params: object
) -> list[dict[str, str]]:
    resp = admin_client(sm, admin).get(URL, params={"q": q, **params})
    assert resp.status_code == 200, resp.text
    return resp.json()["hits"]  # type: ignore[no-any-return]


# -- guard --------------------------------------------------------------------------


def test_the_customers_router_carries_its_own_platform_admin_guard() -> None:
    """The parent also gates it; this pins the lane router so it stays safe if mounted alone."""
    from lemely.web.routers import admin_billing_customers

    [dependency] = admin_billing_customers.router.dependencies
    guard = dependency.dependency
    assert guard is not None
    cells = dict(zip(guard.__code__.co_freevars, guard.__closure__ or (), strict=True))
    assert cells["allowed_values"].cell_contents == frozenset({"platform_admin"})


# -- search -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("q", "matched_on"),
    [
        ("s1@exa", "email"),
        ("Hassan", "name"),
        ("777001", "paymob_order"),
    ],
)
def test_search_finds_the_student(
    sm: sessionmaker[Session], world: dict[str, uuid.UUID], q: str, matched_on: str
) -> None:
    hits = _search(sm, world["admin"], q)
    assert [(h["userId"], h["matchedOn"]) for h in hits] == [(str(world["student"]), matched_on)]


def test_search_by_user_id_and_payment_id(
    sm: sessionmaker[Session], world: dict[str, uuid.UUID]
) -> None:
    by_user = _search(sm, world["admin"], str(world["parent"]))
    assert [(h["userId"], h["matchedOn"]) for h in by_user] == [(str(world["parent"]), "user_id")]
    by_payment = _search(sm, world["admin"], str(world["payment"]))
    assert [(h["userId"], h["matchedOn"]) for h in by_payment] == [
        (str(world["student"]), "payment_id")
    ]


def test_a_payment_id_finds_the_beneficiary_too(
    sm: sessionmaker[Session], world: dict[str, uuid.UUID]
) -> None:
    payment = add_payment(sm, payer=world["parent"], beneficiary=world["student"])
    hits = _search(sm, world["admin"], str(payment))
    assert {h["userId"] for h in hits} == {str(world["parent"]), str(world["student"])}


def test_a_uuid_that_matches_nothing_has_no_hits(
    sm: sessionmaker[Session], world: dict[str, uuid.UUID]
) -> None:
    assert _search(sm, world["admin"], str(uuid.uuid4())) == []


def test_a_paymob_order_id_that_cannot_be_one_has_no_hits(
    sm: sessionmaker[Session], world: dict[str, uuid.UUID]
) -> None:
    """A number beyond BIGINT must not reach the database; non-ASCII digits must not crash."""
    assert _search(sm, world["admin"], "9" * 30) == []
    assert _search(sm, world["admin"], "²³") == []


def test_search_treats_like_wildcards_literally(
    sm: sessionmaker[Session], world: dict[str, uuid.UUID]
) -> None:
    pct = add_user(sm, Role.student, email="50%off@example.com")
    add_user(sm, Role.student, email="501@example.com")
    under = add_user(sm, Role.student, email="a_b@example.com")
    add_user(sm, Role.student, email="axb@example.com")
    assert [h["userId"] for h in _search(sm, world["admin"], "50%")] == [str(pct)]
    assert [h["userId"] for h in _search(sm, world["admin"], "a_b")] == [str(under)]
    assert _search(sm, world["admin"], "%%") == []
    assert _search(sm, world["admin"], "\\\\") == []


def test_escape_like_escapes_the_escape_character_first() -> None:
    assert escape_like(r"a\%_b") == r"a\\\%\_b"


def test_search_is_bounded_by_limit(sm: sessionmaker[Session], world: dict[str, uuid.UUID]) -> None:
    for i in range(7):
        add_user(sm, Role.student, email=f"bulk{i}@example.com")
    assert len(_search(sm, world["admin"], "bulk", limit=3)) == 3
    assert len(_search(sm, world["admin"], "bulk")) == 7
    client = admin_client(sm, world["admin"])
    assert client.get(URL, params={"q": "bulk", "limit": 51}).status_code == 422
    assert client.get(URL, params={"q": "bulk", "limit": 0}).status_code == 422


def test_the_limit_caps_hits_across_every_kind_of_match(
    sm: sessionmaker[Session], world: dict[str, uuid.UUID]
) -> None:
    add_user(sm, Role.student, email="zq1@example.com")
    add_user(sm, Role.student, email="zq2@example.com")
    add_user(sm, Role.student, email="other@example.com", display_name="ZQ Three")
    assert len(_search(sm, world["admin"], "zq")) == 3
    assert len(_search(sm, world["admin"], "zq", limit=2)) == 2


def test_search_query_bounds(sm: sessionmaker[Session], world: dict[str, uuid.UUID]) -> None:
    client = admin_client(sm, world["admin"])
    assert client.get(URL, params={"q": "a"}).status_code == 422
    assert client.get(URL, params={"q": "   "}).status_code == 422
    assert client.get(URL, params={"q": "a" * 201}).status_code == 422
    assert client.get(URL, params={"q": "a" * 200}).status_code == 200
    assert client.get(URL).status_code == 422


def test_each_user_appears_once_tagged_with_the_first_match(
    sm: sessionmaker[Session], world: dict[str, uuid.UUID]
) -> None:
    """The student's name and email both contain the term; the order id wins nothing here."""
    other = add_user(sm, Role.student, email="amira@example.com", display_name="Amira Other")
    hits = _search(sm, world["admin"], "amira")
    assert sorted(h["userId"] for h in hits) == sorted([str(world["student"]), str(other)])
    assert {h["userId"]: h["matchedOn"] for h in hits} == {
        str(world["student"]): "name",
        str(other): "email",
    }


# -- detail -------------------------------------------------------------------------


def test_student_detail_shows_the_whole_money_picture(
    sm: sessionmaker[Session], world: dict[str, uuid.UUID]
) -> None:
    resp = admin_client(sm, world["admin"]).get(f"{URL}/{world['student']}")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["user"]["email"] == "s1@example.com"
    assert body["balance"] == {
        "allowanceAvailable": 996,
        "creditsAvailable": 300,
        "seatAvailable": 0,
        "outstandingDebt": 0,
    }
    [sub] = body["subscriptions"]
    assert (sub["planCode"], sub["status"], len(sub["periods"])) == ("student_monthly", "active", 1)
    assert sorted((g["kind"], g["units"], g["remaining"]) for g in body["grants"]) == [
        ("adjustment", 300, 300),
        ("period_allowance", 1000, 996),
    ]
    [job] = body["usageJobs"]
    assert (job["estimateLow"], job["estimateHigh"], job["actualUnits"], job["outsideRange"]) == (
        3,
        5,
        4,
        False,
    )
    assert job["actualCostUsd"] == "0.004000"
    [payment] = body["payments"]
    assert (payment["paymobOrderId"], payment["status"], payment["refundedMinor"]) == (
        "777001",
        "paid",
        0,
    )
    assert [m["email"] for m in body["seatedWith"]] == ["t1@example.com"]
    assert [p["email"] for p in body["parents"]] == ["p1@example.com"]
    assert body["seats"] == [] and body["assistants"] == [] and body["children"] == []
    assert [a["action"] for a in body["audit"]] == ["customer.grant"]


def test_teacher_detail_lists_seats_and_assistants(
    sm: sessionmaker[Session], world: dict[str, uuid.UUID]
) -> None:
    body = admin_client(sm, world["admin"]).get(f"{URL}/{world['teacher']}").json()
    assert [m["email"] for m in body["seats"]] == ["s1@example.com"]
    assert [(m["email"], m["rolePreset"]) for m in body["assistants"]] == [
        ("a1@example.com", "co_teacher")
    ]
    assert body["seatedWith"] == [] and body["parents"] == [] and body["children"] == []


def test_parent_detail_lists_children(
    sm: sessionmaker[Session], world: dict[str, uuid.UUID]
) -> None:
    body = admin_client(sm, world["admin"]).get(f"{URL}/{world['parent']}").json()
    assert [c["email"] for c in body["children"]] == ["s1@example.com"]
    assert body["parents"] == []


def test_an_unknown_customer_is_404(sm: sessionmaker[Session], world: dict[str, uuid.UUID]) -> None:
    resp = admin_client(sm, world["admin"]).get(f"{URL}/{uuid.uuid4()}")
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "customer_not_found"


def test_a_malformed_customer_id_is_422(
    sm: sessionmaker[Session], world: dict[str, uuid.UUID]
) -> None:
    assert admin_client(sm, world["admin"]).get(f"{URL}/not-a-uuid").status_code == 422


def test_detail_never_shows_another_customers_rows(
    sm: sessionmaker[Session], world: dict[str, uuid.UUID]
) -> None:
    """IDOR: every list is scoped to the path's user."""
    stranger = add_user(sm, Role.student, email="stranger@example.com")
    grant(sm, stranger, units=777)
    add_payment(sm, payer=stranger, paymob_order_id=999111)
    body = admin_client(sm, world["admin"]).get(f"{URL}/{world['student']}").json()
    assert 777 not in {g["units"] for g in body["grants"]}
    assert "999111" not in {p["paymobOrderId"] for p in body["payments"]}
    assert body["balance"]["creditsAvailable"] == 300
    other = admin_client(sm, world["admin"]).get(f"{URL}/{stranger}").json()
    assert [g["units"] for g in other["grants"]] == [777]
    assert other["usageJobs"] == [] and other["subscriptions"] == []


# -- balance ------------------------------------------------------------------------


def test_a_students_seat_grant_counts_for_the_student_and_never_the_teacher(
    sm: sessionmaker[Session], world: dict[str, uuid.UUID]
) -> None:
    with sm.begin() as session:
        member_id = session.scalars(
            sa.select(TeacherMember.id).where(
                TeacherMember.member_user_id == world["student"],
                TeacherMember.kind == TeacherMemberKind.student_seat,
            )
        ).one()
        UsageLedger(session).issue_grant(
            owner_user_id=world["student"],
            kind=GrantKind.seat_allowance,
            units=250,
            idempotency_key=f"seed:{uuid.uuid4()}",
            expires_at=NOW + timedelta(days=20),
            visible=False,
            effective_at=NOW - timedelta(days=1),
            teacher_member_id=member_id,
        )
    client = admin_client(sm, world["admin"])
    student = client.get(f"{URL}/{world['student']}").json()["balance"]
    teacher = client.get(f"{URL}/{world['teacher']}").json()["balance"]
    # The seat grant is not folded into the allowance either.
    assert (student["seatAvailable"], student["allowanceAvailable"]) == (250, 996)
    assert teacher == {
        "allowanceAvailable": 0,
        "creditsAvailable": 0,
        "seatAvailable": 0,
        "outstandingDebt": 0,
    }


def test_outstanding_debt_is_summed_and_listed(
    sm: sessionmaker[Session], world: dict[str, uuid.UUID]
) -> None:
    other = add_user(sm, Role.student)
    add_rate(sm, "grade_quiz")
    metered_job(
        sm, other, [Payer(owner_user_id=other, scope=GrantScope.CREDITS)],
        action="grade_quiz", low=0, high=0, cost=Decimal("0.5"),
    )  # fmt: skip
    body = admin_client(sm, world["admin"]).get(f"{URL}/{other}").json()
    assert body["balance"]["outstandingDebt"] == 500
    assert [d["outstanding"] for d in body["debts"]] == [500]


# -- grants window ------------------------------------------------------------------


def _bulk_closed_grants(sm: sessionmaker[Session], owner: uuid.UUID, count: int) -> None:
    """``count`` expired grants, written directly (a ledger call each would be slow)."""
    with sm.begin() as session:
        for i in range(count):
            gid = uuid.uuid4()
            expires = NOW - timedelta(days=1 + i)
            session.add(
                UsageGrant(
                    id=gid, owner_user_id=owner, kind=GrantKind.adjustment, visible=True,
                    priority=1, units=10 + i, effective_at=expires - timedelta(days=30),
                    expires_at=expires, idempotency_key=f"bulk:{gid}",
                )
            )  # fmt: skip
            session.flush()
            session.add(UsageGrantBalance(grant_id=gid, remaining=0, held=0))


def test_grants_are_every_usable_one_plus_the_newest_hundred_closed(
    sm: sessionmaker[Session], world: dict[str, uuid.UUID]
) -> None:
    _bulk_closed_grants(sm, world["student"], 105)
    body = admin_client(sm, world["admin"]).get(f"{URL}/{world['student']}").json()
    closed = [g for g in body["grants"] if g["remaining"] == 0 and g["expiresAt"] < NOW.isoformat()]
    usable = [g for g in body["grants"] if g not in closed]
    assert len(usable) == 2  # the allowance and the 300 credits, both still usable
    assert len(closed) == 100
    # The newest 100 closed: the 5 oldest (units 110..114) are the ones dropped.
    assert {g["units"] for g in closed} == {10 + i for i in range(100)}


# -- payments and refunds -----------------------------------------------------------


def _refund(
    sm: sessionmaker[Session],
    payment: uuid.UUID,
    admin: uuid.UUID,
    amount: int,
    *,
    status: RefundStatus = RefundStatus.succeeded,
    kind: RefundKind = RefundKind.refund,
) -> None:
    with sm.begin() as session:
        session.add(
            PaymentRefund(
                payment_id=payment, admin_user_id=admin, kind=kind, status=status,
                amount_minor=amount, reason="seeded",
            )
        )  # fmt: skip


def test_a_dashboard_refund_shows_in_refunded_minor(
    sm: sessionmaker[Session], world: dict[str, uuid.UUID]
) -> None:
    """Paymob's console refund leaves no refund row, only ``last_callback`` (DV-19)."""
    pid = add_payment(
        sm, payer=world["student"], status=PaymentStatus.partially_refunded, amount_minor=10000,
        last_callback={"refunded_amount_cents": 4000, "is_refunded": True},
    )  # fmt: skip
    body = admin_client(sm, world["admin"]).get(f"{URL}/{world['student']}").json()
    row = next(p for p in body["payments"] if p["id"] == str(pid))
    assert row["refundedMinor"] == 4000
    assert row["refunds"] == []


@pytest.mark.parametrize(
    ("callback", "console", "expected"),
    [
        (None, [], 0),
        ({"refunded_amount_cents": 4000}, [], 4000),
        ({"refunded_amount_cents": "4000"}, [], 4000),
        ({"refunded_amount_cents": 4000}, [2500], 4000),
        ({"refunded_amount_cents": 4000}, [6000], 6000),
        ({"refunded_amount_cents": 4000}, [1000, 1500], 4000),
        (None, [1000, 1500], 2500),
        ({"refunded_amount_cents": True}, [], 0),
        ({"refunded_amount_cents": -5}, [], 0),
        ({"refunded_amount_cents": "lots"}, [], 0),
        ({"other": 1}, [], 0),
    ],
)
def test_refunded_minor_is_the_larger_of_console_and_callback(
    sm: sessionmaker[Session],
    world: dict[str, uuid.UUID],
    callback: dict[str, object] | None,
    console: list[int],
    expected: int,
) -> None:
    pid = add_payment(sm, payer=world["student"], last_callback=callback)
    for amount in console:
        _refund(sm, pid, world["admin"], amount)
    with sm() as session:
        [view] = payment_views(session, [session.get(Payment, pid)])  # type: ignore[list-item]
        assert isinstance(view, PaymentView)
        assert view.refunded_minor == expected


def test_failed_unknown_and_void_attempts_do_not_count_as_refunded(
    sm: sessionmaker[Session], world: dict[str, uuid.UUID]
) -> None:
    pid = add_payment(sm, payer=world["student"], amount_minor=10000)
    _refund(sm, pid, world["admin"], 3000, status=RefundStatus.failed)
    _refund(sm, pid, world["admin"], 3000, status=RefundStatus.unknown)
    _refund(sm, pid, world["admin"], 3000, status=RefundStatus.requested)
    _refund(sm, pid, world["admin"], 10000, kind=RefundKind.void)
    _refund(sm, pid, world["admin"], 2000)
    body = admin_client(sm, world["admin"]).get(f"{URL}/{world['student']}").json()
    row = next(p for p in body["payments"] if p["id"] == str(pid))
    assert row["refundedMinor"] == 2000
    assert len(row["refunds"]) == 5
    assert {r["paymentId"] for r in row["refunds"]} == {str(pid)}
    assert {r["currency"] for r in row["refunds"]} == {"EGP"}


# -- bounds -------------------------------------------------------------------------


def test_payments_jobs_and_audit_are_the_newest_fifty(
    sm: sessionmaker[Session], world: dict[str, uuid.UUID]
) -> None:
    student = world["student"]
    for i in range(52):
        add_payment(sm, payer=student, created_at=NOW - timedelta(hours=1 + i), paid_at=None)
    with sm.begin() as session:
        for i in range(52):
            audited(
                session, world["admin"], "customer.adjust", "user", student, f"r{i}", None, None
            )
        for i in range(52):
            session.add(
                UsageJob(
                    job_id=uuid.uuid4(), actor_user_id=student, action="mark_paper",
                    estimate_low=1, estimate_high=2, estimator_version=1, reserved=0,
                    rate_version=1, payer_chain=[], expires_at=NOW,
                    created_at=NOW - timedelta(hours=2 + i),
                )
            )  # fmt: skip
    body = admin_client(sm, world["admin"]).get(f"{URL}/{student}").json()
    assert len(body["payments"]) == 50
    assert len(body["usageJobs"]) == 50
    assert len(body["audit"]) == 50
    # The newest payment (the seeded one at NOW - 5 minutes) is the first.
    assert body["payments"][0]["paymobOrderId"] == "777001"


# -- audit scope --------------------------------------------------------------------


def test_audit_covers_the_user_their_subscriptions_and_their_payments(
    sm: sessionmaker[Session], world: dict[str, uuid.UUID]
) -> None:
    stranger = add_user(sm, Role.student)
    stranger_sub = add_subscription(sm, stranger, world["tier"])
    stranger_payment = add_payment(sm, payer=stranger)
    # A payment the user benefits from but did not pay for is theirs too.
    gifted = add_payment(sm, payer=world["parent"], beneficiary=world["student"])
    # More than 50 newer payments must not push an old payment's audit rows out of scope.
    for i in range(52):
        add_payment(
            sm, payer=world["student"], created_at=NOW + timedelta(hours=1 + i), paid_at=None
        )
    admin = world["admin"]
    with sm.begin() as session:
        audited(session, admin, "customer.adjust", "user", world["student"], "on user", None, None)
        audited(
            session,
            admin,
            "subscription.extend",
            "subscription",
            world["sub"],
            "on sub",
            None,
            None,
        )
        audited(
            session,
            admin,
            "payment.refund.requested",
            "payment",
            world["payment"],
            "on pay",
            None,
            None,
        )
        audited(
            session, admin, "payment.refund.requested", "payment", gifted, "on gifted", None, None
        )
        audited(session, admin, "customer.adjust", "user", stranger, "other user", None, None)
        audited(
            session,
            admin,
            "subscription.extend",
            "subscription",
            stranger_sub,
            "other sub",
            None,
            None,
        )
        audited(
            session,
            admin,
            "payment.refund.requested",
            "payment",
            stranger_payment,
            "other pay",
            None,
            None,
        )
        # Same id, different kind: not this user's row.
        audited(
            session,
            admin,
            "catalogue.plan_tier.update",
            "plan_tier",
            world["sub"],
            "wrong kind",
            None,
            None,
        )
    body = admin_client(sm, admin).get(f"{URL}/{world['student']}").json()
    assert sorted(a["reason"] for a in body["audit"]) == sorted(
        ["seeded", "on user", "on sub", "on pay", "on gifted"]
    )  # fmt: skip


# -- shape --------------------------------------------------------------------------


def test_the_detail_has_exactly_the_frontends_keys(
    sm: sessionmaker[Session], world: dict[str, uuid.UUID]
) -> None:
    """Every list is non-empty here, so every nested shape is checked too."""
    student, teacher, admin = world["student"], world["teacher"], world["admin"]
    pid = add_payment(
        sm, payer=student, paymob_order_id=777002, plan_tier_id=world["tier"],
        last_callback={"refunded_amount_cents": 1},
    )  # fmt: skip
    _refund(sm, pid, admin, 1)
    with sm.begin() as session:
        session.add(
            TeacherMember(
                teacher_user_id=student, member_user_id=add_user(sm, Role.student),
                kind=TeacherMemberKind.student_seat, status=TeacherMemberStatus.active,
                scope_subjects=["0625"], scope_actions=["mark_paper"],
            )
        )  # fmt: skip
    other = add_user(sm, Role.student)
    add_rate(sm, "grade_quiz")
    metered_job(
        sm, other, [Payer(owner_user_id=other, scope=GrantScope.CREDITS)],
        action="grade_quiz", low=0, high=0, cost=Decimal("0.5"),
    )  # fmt: skip

    client = admin_client(sm, admin)
    body = client.get(f"{URL}/{student}").json()
    assert set(body) == CUSTOMER_DETAIL_KEYS
    assert set(body["user"]) == USER_KEYS
    assert set(body["balance"]) == BALANCE_KEYS
    assert set(body["subscriptions"][0]) == SUBSCRIPTION_KEYS
    assert set(body["subscriptions"][0]["periods"][0]) == PERIOD_KEYS
    assert set(body["grants"][0]) == GRANT_KEYS
    assert set(body["usageJobs"][0]) == JOB_KEYS
    assert body["payments"] and all(set(p) == PAYMENT_KEYS for p in body["payments"])
    refunds = [r for p in body["payments"] for r in p["refunds"]]
    assert refunds and all(set(r) == REFUND_KEYS for r in refunds)
    assert set(body["seatedWith"][0]) == MEMBER_KEYS
    assert set(body["seats"][0]) == MEMBER_KEYS
    assert set(body["parents"][0]) == LINKED_KEYS
    assert set(body["audit"][0]) == AUDIT_KEYS
    debt_body = client.get(f"{URL}/{other}").json()
    assert set(debt_body["debts"][0]) == DEBT_KEYS
    assert set(client.get(f"{URL}/{teacher}").json()["assistants"][0]) == MEMBER_KEYS
    assert set(client.get(f"{URL}/{world['parent']}").json()["children"][0]) == LINKED_KEYS
