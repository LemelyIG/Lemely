"""Customer money actions (spec §8 area 2, §5.8): each audited in the same transaction."""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from threading import Barrier
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from sqlalchemy import select

from lemely.core.usage_types import GrantScope, Payer
from lemely.db import admin_customer_repo
from lemely.db.admin_billing_repo import AdminConflictError, AuditAction
from lemely.db.admin_customer_repo import AdminCustomerService
from lemely.db.models.enums import Role
from lemely.db.models.usage import GrantKind, UsageDebt, UsageGrant, UsageRate
from tests.admin_billing_db import (
    NOW,
    FakePaymobClient,
    add_rate,
    add_user,
    admin_client,
    audit_count,
    audit_rows,
    billing_database,
    emptied_after,
    grant,
    metered_job,
)
from tests.paymob_fixtures import PAYMOB_SETTINGS

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker

    from lemely.db.models.admin_audit import AdminAuditLog


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


def _service(sm: sessionmaker[Session], clock: list[object] | None = None) -> AdminCustomerService:
    """A service whose clock is ``NOW`` unless ``clock[0]`` is moved."""
    if clock is None:
        return AdminCustomerService(sm, FakePaymobClient(), PAYMOB_SETTINGS, now=lambda: NOW)  # type: ignore[arg-type]
    return AdminCustomerService(
        sm,
        FakePaymobClient(),  # type: ignore[arg-type]
        PAYMOB_SETTINGS,
        now=lambda: clock[0],  # type: ignore[return-value]
    )


def _with_debt(sm: sessionmaker[Session], units_of_debt: int) -> uuid.UUID:
    """A student whose 5 credits were overrun by a job costing 5 + ``units_of_debt`` units."""
    student = add_user(sm, Role.student)
    with sm() as session:
        has_rate = session.scalar(sa.select(sa.func.count()).select_from(UsageRate)) or 0
    if not has_rate:
        add_rate(sm, "mark_paper")
    grant(sm, student, units=5)
    metered_job(
        sm,
        student,
        [Payer(owner_user_id=student, scope=GrantScope.CREDITS)],
        low=1,
        high=5,
        cost=Decimal(5 + units_of_debt) / 1000,
    )
    return student


def _before(row: AdminAuditLog) -> dict[str, object]:
    assert row.before is not None
    return row.before


def _after(row: AdminAuditLog) -> dict[str, object]:
    assert row.after is not None
    return row.after


def _url(user: uuid.UUID, action: str) -> str:
    return f"/api/admin/billing/customers/{user}/{action}"


def _grant_body(request_id: uuid.UUID | None = None, **over: object) -> dict[str, object]:
    return {
        "units": 100,
        "validDays": 30,
        "requestId": str(request_id or uuid.uuid4()),
        "reason": "outage goodwill",
        **over,
    }


def _grants_of(sm: sessionmaker[Session], user: uuid.UUID) -> list[UsageGrant]:
    with sm() as session:
        return list(session.scalars(select(UsageGrant).where(UsageGrant.owner_user_id == user)))


# -- grant ---------------------------------------------------------------------


def test_grant_is_audited_and_a_replay_changes_nothing(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    student = add_user(sm, Role.student)
    client = admin_client(sm, admin)
    body = _grant_body()

    first = client.post(_url(student, "grant"), json=body)
    replay = client.post(_url(student, "grant"), json=body)

    assert first.status_code == 200, first.text
    assert replay.status_code == 200, replay.text
    assert first.json()["balance"]["creditsAvailable"] == 100
    assert replay.json()["balance"]["creditsAvailable"] == 100
    [row] = audit_rows(sm, AuditAction.CUSTOMER_GRANT)
    assert row.target_id == student
    assert row.admin_user_id == admin
    assert (_before(row)["credits_available"], _after(row)["credits_available"]) == (0, 100)
    assert _after(row)["idempotency_key"] == f"admin-grant:{student}:{body['requestId']}"
    assert (_after(row)["user_id"], _after(row)["units"], _after(row)["valid_days"]) == (
        str(student),
        100,
        30,
    )
    [issued] = _grants_of(sm, student)
    assert (issued.kind, issued.visible, issued.units) == (GrantKind.adjustment, True, 100)
    assert issued.effective_at == NOW
    assert issued.expires_at == NOW + timedelta(days=30)


def test_valid_days_null_never_expires_and_absent_is_a_year(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    student = add_user(sm, Role.student)
    client = admin_client(sm, admin)
    forever = _grant_body(validDays=None)
    default = _grant_body()
    del default["validDays"]

    assert client.post(_url(student, "grant"), json=forever).status_code == 200
    assert client.post(_url(student, "grant"), json=default).status_code == 200

    by_units = {g.expires_at for g in _grants_of(sm, student)}
    assert by_units == {None, NOW + timedelta(days=365)}


def test_a_grant_repays_debt_first(sm: sessionmaker[Session], admin: uuid.UUID) -> None:
    student = _with_debt(sm, 3)
    resp = admin_client(sm, admin).post(
        _url(student, "grant"), json=_grant_body(units=10, reason="settle up")
    )
    assert resp.json()["balance"]["outstandingDebt"] == 0
    assert resp.json()["balance"]["creditsAvailable"] == 7
    [row] = audit_rows(sm, AuditAction.CUSTOMER_GRANT)
    assert (_before(row)["outstanding_debt"], _after(row)["outstanding_debt"]) == (3, 0)


def test_the_grant_and_its_audit_row_commit_together(
    sm: sessionmaker[Session], admin: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    student = add_user(sm, Role.student)

    def broken_audit(*args: object, **kwargs: object) -> None:
        raise RuntimeError("audit write failed")

    monkeypatch.setattr(admin_customer_repo, "audited", broken_audit)
    with pytest.raises(RuntimeError):
        _service(sm).grant_credits(
            student,
            units=100,
            valid_days=30,
            request_id=uuid.uuid4(),
            admin_user_id=admin,
            reason="x y z",
        )
    assert _grants_of(sm, student) == []


def test_double_submit_of_one_grant_is_one_grant_and_one_audit_row(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    student = add_user(sm, Role.student)
    client = admin_client(sm, admin)
    body = _grant_body()
    statuses = [client.post(_url(student, "grant"), json=body).status_code for _ in range(2)]
    assert statuses == [200, 200]
    assert len(_grants_of(sm, student)) == 1
    assert len(audit_rows(sm, AuditAction.CUSTOMER_GRANT)) == 1


def test_the_same_request_id_on_a_second_user_is_409_and_changes_nothing(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    first, second = add_user(sm, Role.student), add_user(sm, Role.student)
    client = admin_client(sm, admin)
    body = _grant_body()
    assert client.post(_url(first, "grant"), json=body).status_code == 200

    resp = client.post(_url(second, "grant"), json=body)

    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "request_id_reused"
    assert _grants_of(sm, second) == []
    assert len(audit_rows(sm, AuditAction.CUSTOMER_GRANT)) == 1


@pytest.mark.parametrize("changed", [{"units": 101}, {"validDays": 31}, {"validDays": None}])
def test_the_same_request_id_with_other_units_or_validity_is_409(
    sm: sessionmaker[Session], admin: uuid.UUID, changed: dict[str, object]
) -> None:
    student = add_user(sm, Role.student)
    client = admin_client(sm, admin)
    request_id = uuid.uuid4()
    assert client.post(_url(student, "grant"), json=_grant_body(request_id)).status_code == 200

    resp = client.post(_url(student, "grant"), json=_grant_body(request_id, **changed))

    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "request_id_reused"
    assert len(_grants_of(sm, student)) == 1


def test_two_concurrent_identical_grants_issue_one(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    student = add_user(sm, Role.student)
    request_id = uuid.uuid4()
    barrier = Barrier(2)

    def call() -> None:
        service = _service(sm)
        barrier.wait(timeout=10)
        service.grant_credits(
            student,
            units=100,
            valid_days=30,
            request_id=request_id,
            admin_user_id=admin,
            reason="race",
        )

    with ThreadPoolExecutor(2) as pool:
        for future in [pool.submit(call), pool.submit(call)]:
            future.result(timeout=30)

    assert len(_grants_of(sm, student)) == 1
    assert len(audit_rows(sm, AuditAction.CUSTOMER_GRANT)) == 1


def test_a_blank_reason_changes_nothing(sm: sessionmaker[Session], admin: uuid.UUID) -> None:
    student = add_user(sm, Role.student)
    resp = admin_client(sm, admin).post(_url(student, "grant"), json=_grant_body(reason="   "))
    assert resp.status_code == 422
    assert _grants_of(sm, student) == []
    assert audit_count(sm) == 0


# -- adjust --------------------------------------------------------------------


def test_adjust_moves_credits_both_ways(sm: sessionmaker[Session], admin: uuid.UUID) -> None:
    student = add_user(sm, Role.student)
    client = admin_client(sm, admin)
    up = client.post(
        _url(student, "adjust"), json={"units": 50, "requestId": str(uuid.uuid4()), "reason": "fix"}
    )
    down = client.post(
        _url(student, "adjust"),
        json={"units": -20, "requestId": str(uuid.uuid4()), "reason": "fix"},
    )
    assert up.status_code == 200, up.text
    assert down.json()["balance"]["creditsAvailable"] == 30
    assert [_after(r)["units"] for r in audit_rows(sm, AuditAction.CUSTOMER_ADJUST)] == [50, -20]
    assert all(
        str(_after(r)["idempotency_key"]).startswith(f"admin-adjust:{student}:")
        for r in audit_rows(sm, AuditAction.CUSTOMER_ADJUST)
    )


def test_a_debit_beyond_the_balance_becomes_exactly_the_shortfall_as_debt(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    student = add_user(sm, Role.student)
    client = admin_client(sm, admin)
    client.post(
        _url(student, "adjust"),
        json={"units": 10, "requestId": str(uuid.uuid4()), "reason": "seed"},
    )
    resp = client.post(
        _url(student, "adjust"),
        json={"units": -25, "requestId": str(uuid.uuid4()), "reason": "claw back"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["balance"]["creditsAvailable"] == 0
    assert resp.json()["balance"]["outstandingDebt"] == 15
    assert [d["outstanding"] for d in resp.json()["debts"]] == [15]
    [_, row] = audit_rows(sm, AuditAction.CUSTOMER_ADJUST)
    assert (_before(row)["outstanding_debt"], _after(row)["outstanding_debt"]) == (0, 15)
    with sm() as session:
        assert session.scalars(
            select(UsageDebt.units).where(UsageDebt.owner_user_id == student)
        ).all() == [15]


def test_an_adjust_replay_changes_nothing_and_a_changed_replay_is_409(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    student, other = add_user(sm, Role.student), add_user(sm, Role.student)
    client = admin_client(sm, admin)
    body = {"units": 40, "requestId": str(uuid.uuid4()), "reason": "fix"}
    assert client.post(_url(student, "adjust"), json=body).status_code == 200

    replay = client.post(_url(student, "adjust"), json=body)
    other_units = client.post(_url(student, "adjust"), json={**body, "units": 41})
    other_user = client.post(_url(other, "adjust"), json=body)

    assert replay.status_code == 200
    assert replay.json()["balance"]["creditsAvailable"] == 40
    assert (other_units.status_code, other_user.status_code) == (409, 409)
    assert other_units.json()["detail"]["code"] == "request_id_reused"
    assert other_user.json()["detail"]["code"] == "request_id_reused"
    assert len(audit_rows(sm, AuditAction.CUSTOMER_ADJUST)) == 1
    assert _grants_of(sm, other) == []


def test_a_zero_adjustment_is_422(sm: sessionmaker[Session], admin: uuid.UUID) -> None:
    student = add_user(sm, Role.student)
    resp = admin_client(sm, admin).post(
        _url(student, "adjust"), json={"units": 0, "requestId": str(uuid.uuid4()), "reason": "noop"}
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "zero_adjustment"
    assert audit_count(sm) == 0


# -- forgive debt --------------------------------------------------------------


def test_forgive_all_then_nothing_left(sm: sessionmaker[Session], admin: uuid.UUID) -> None:
    student = _with_debt(sm, 3)
    clock: list[object] = [NOW]
    service = _service(sm, clock)
    service.forgive_debt(student, units=None, admin_user_id=admin, reason="estimator bug")

    clock[0] = NOW + timedelta(seconds=121)
    with pytest.raises(AdminConflictError) as err:
        service.forgive_debt(student, units=None, admin_user_id=admin, reason="estimator bug")

    assert err.value.code == "no_outstanding_debt"
    [row] = audit_rows(sm, AuditAction.CUSTOMER_FORGIVE_DEBT)
    assert (_before(row)["outstanding_debt"], _after(row)["forgiven_units"]) == (3, 3)
    assert _after(row)["requested_units"] is None


def test_forgive_part_of_the_debt(sm: sessionmaker[Session], admin: uuid.UUID) -> None:
    student = _with_debt(sm, 3)
    resp = admin_client(sm, admin).post(
        _url(student, "forgive-debt"), json={"units": 2, "reason": "part"}
    )
    assert resp.json()["balance"]["outstandingDebt"] == 1


def test_the_same_forgive_within_120_seconds_is_a_no_op_200(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    student = _with_debt(sm, 5)
    client = admin_client(sm, admin)
    body = {"units": 2, "reason": "estimator bug"}

    first = client.post(_url(student, "forgive-debt"), json=body)
    second = client.post(_url(student, "forgive-debt"), json=body)

    assert (first.status_code, second.status_code) == (200, 200)
    assert second.json()["balance"]["outstandingDebt"] == 3
    assert len(audit_rows(sm, AuditAction.CUSTOMER_FORGIVE_DEBT)) == 1


def test_after_120_seconds_the_same_forgive_forgives_again(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    student = _with_debt(sm, 5)
    clock: list[object] = [NOW]
    service = _service(sm, clock)

    service.forgive_debt(student, units=2, admin_user_id=admin, reason="estimator bug")
    clock[0] = NOW + timedelta(seconds=121)
    detail = service.forgive_debt(student, units=2, admin_user_id=admin, reason="estimator bug")

    assert detail.balance.outstanding_debt == 1
    assert len(audit_rows(sm, AuditAction.CUSTOMER_FORGIVE_DEBT)) == 2


@pytest.mark.parametrize("variant", ["units", "reason", "admin", "user"])
def test_a_different_forgive_inside_the_window_is_not_deduplicated(
    sm: sessionmaker[Session], admin: uuid.UUID, variant: str
) -> None:
    student = _with_debt(sm, 5)
    other_student = _with_debt(sm, 5)
    other_admin = add_user(sm, Role.platform_admin)
    service = _service(sm)
    service.forgive_debt(student, units=2, admin_user_id=admin, reason="estimator bug")

    service.forgive_debt(
        other_student if variant == "user" else student,
        units=1 if variant == "units" else 2,
        admin_user_id=other_admin if variant == "admin" else admin,
        reason="another reason" if variant == "reason" else "estimator bug",
    )

    assert len(audit_rows(sm, AuditAction.CUSTOMER_FORGIVE_DEBT)) == 2


def test_the_forgive_lock_key_is_never_stored_as_an_idempotency_key(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    """The index on it is UNIQUE per action: a later forgive would otherwise 500."""
    student = _with_debt(sm, 5)
    clock: list[object] = [NOW]
    service = _service(sm, clock)
    service.forgive_debt(student, units=2, admin_user_id=admin, reason="estimator bug")
    clock[0] = NOW + timedelta(seconds=300)
    service.forgive_debt(student, units=2, admin_user_id=admin, reason="estimator bug")
    assert all(
        "idempotency_key" not in _after(row)
        for row in audit_rows(sm, AuditAction.CUSTOMER_FORGIVE_DEBT)
    )


def test_two_concurrent_identical_forgives_forgive_once(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    student = _with_debt(sm, 5)
    barrier = Barrier(2)

    def call() -> None:
        service = _service(sm)
        barrier.wait(timeout=10)
        service.forgive_debt(student, units=2, admin_user_id=admin, reason="race")

    with ThreadPoolExecutor(2) as pool:
        for future in [pool.submit(call), pool.submit(call)]:
            future.result(timeout=30)

    assert len(audit_rows(sm, AuditAction.CUSTOMER_FORGIVE_DEBT)) == 1
    with sm() as session:
        outstanding = session.scalar(
            select(sa.func.sum(UsageDebt.outstanding)).where(UsageDebt.owner_user_id == student)
        )
    assert outstanding == 3


# -- unknown customer ----------------------------------------------------------


@pytest.mark.parametrize(
    ("action", "body"),
    [
        ("grant", _grant_body()),
        ("adjust", {"units": 5, "requestId": str(uuid.uuid4()), "reason": "who"}),
        ("forgive-debt", {"reason": "who"}),
    ],
)
def test_an_unknown_customer_is_404_with_no_audit_row(
    sm: sessionmaker[Session], admin: uuid.UUID, action: str, body: dict[str, object]
) -> None:
    resp = admin_client(sm, admin).post(_url(uuid.uuid4(), action), json=body)
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "customer_not_found"
    assert audit_count(sm) == 0
