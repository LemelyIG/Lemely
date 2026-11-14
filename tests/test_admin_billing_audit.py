"""The admin audit log: one append-only row per admin money or catalogue action (spec §4.7)."""

from __future__ import annotations

import enum
import threading
import time
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError, IntegrityError

from lemely.db.admin_billing_repo import (
    ReasonRequiredError,
    already_applied,
    audited,
    lock_idempotency_key,
    snapshot,
    to_jsonable,
)
from lemely.db.models.admin_audit import AdminAuditLog
from lemely.db.models.enums import Role
from tests.admin_billing_db import add_user, billing_database, emptied_after

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture(scope="module")
def billing_db() -> Iterator[sessionmaker[Session]]:
    with billing_database() as factory:
        yield factory


@pytest.fixture
def sm(billing_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(billing_db)


class _Colour(enum.Enum):
    red = "red"


def _row_count(sm: sessionmaker[Session]) -> int:
    with sm() as session:
        return session.scalar(select(sa.func.count()).select_from(AdminAuditLog)) or 0


def test_to_jsonable_converts_the_types_snapshots_carry() -> None:
    uid = uuid.uuid4()
    moment = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)
    assert to_jsonable(
        {"id": uid, "at": moment, "usd": Decimal("0.004100"), "c": _Colour.red, "xs": (1, "a")}
    ) == {"id": str(uid), "at": moment.isoformat(), "usd": "0.004100", "c": "red", "xs": [1, "a"]}


def test_to_jsonable_keeps_booleans_and_none_as_they_are() -> None:
    assert to_jsonable({"on": True, "off": False, "none": None, "n": 0}) == {
        "on": True,
        "off": False,
        "none": None,
        "n": 0,
    }


@pytest.mark.parametrize("value", [object(), b"bytes", {"nested": object()}, [1, object()]])
def test_to_jsonable_refuses_an_unknown_type(value: object) -> None:
    with pytest.raises(TypeError, match="cannot audit"):
        to_jsonable(value)


def test_snapshot_reads_the_named_attributes() -> None:
    class Row:
        units = 5
        kind = _Colour.red

    assert snapshot(Row(), ["units", "kind"]) == {"units": 5, "kind": "red"}


def test_audited_writes_one_row_with_a_stripped_reason(sm: sessionmaker[Session]) -> None:
    admin = add_user(sm, Role.platform_admin)
    target = uuid.uuid4()
    with sm.begin() as session:
        row = audited(
            session,
            admin,
            "customer.grant",
            "user",
            target,
            "  goodwill after outage  ",
            {"balance": 0},
            {"balance": 100, "idempotency_key": "admin-grant:abc"},
        )
        row_id = row.id
    with sm() as session:
        stored = session.get(AdminAuditLog, row_id)
        assert stored is not None
        assert stored.reason == "goodwill after outage"
        assert stored.admin_user_id == admin
        assert stored.target_id == target
        assert stored.before == {"balance": 0}
        assert stored.after == {"balance": 100, "idempotency_key": "admin-grant:abc"}
        assert stored.created_at is not None
        assert already_applied(session, action="customer.grant", idempotency_key="admin-grant:abc")
        assert not already_applied(
            session, action="customer.adjust", idempotency_key="admin-grant:abc"
        )
        assert not already_applied(
            session, action="customer.grant", idempotency_key="admin-grant:other"
        )


def test_a_row_without_an_idempotency_key_is_never_already_applied(
    sm: sessionmaker[Session],
) -> None:
    admin = add_user(sm, Role.platform_admin)
    with sm.begin() as session:
        audited(session, admin, "customer.grant", "user", uuid.uuid4(), "why", None, {"units": 5})
        audited(session, admin, "customer.grant", "user", uuid.uuid4(), "why", None, None)
    with sm() as session:
        assert not already_applied(session, action="customer.grant", idempotency_key="")
        assert not already_applied(session, action="customer.grant", idempotency_key="units")


@pytest.mark.parametrize("reason", ["", "   ", "\t\n ", None])
def test_a_blank_reason_is_refused_and_nothing_is_written(
    sm: sessionmaker[Session], reason: str | None
) -> None:
    admin = add_user(sm, Role.platform_admin)
    with sm.begin() as session, pytest.raises(ReasonRequiredError) as raised:
        audited(session, admin, "customer.grant", "user", uuid.uuid4(), reason, None, None)  # type: ignore[arg-type]
    assert raised.value.code == "reason_required"
    assert _row_count(sm) == 0


def test_the_database_refuses_a_blank_reason_inserted_directly(sm: sessionmaker[Session]) -> None:
    admin = add_user(sm, Role.platform_admin)
    with pytest.raises(IntegrityError, match="reason_required"), sm.begin() as session:
        session.execute(
            sa.text(
                "INSERT INTO admin_audit_log (admin_user_id, action, target_kind, target_id, "
                "reason) VALUES (:a, 'customer.grant', 'user', :t, E' \\t ')"
            ),
            {"a": admin, "t": uuid.uuid4()},
        )
    assert _row_count(sm) == 0


def test_the_row_rolls_back_with_its_transaction(sm: sessionmaker[Session]) -> None:
    admin = add_user(sm, Role.platform_admin)
    with pytest.raises(RuntimeError), sm.begin() as session:
        audited(session, admin, "customer.grant", "user", uuid.uuid4(), "why", None, None)
        raise RuntimeError("the money change failed after the audit row")
    assert _row_count(sm) == 0


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE admin_audit_log SET reason = 'rewritten'",
        "DELETE FROM admin_audit_log",
    ],
)
def test_create_all_installs_the_append_only_trigger(
    sm: sessionmaker[Session], statement: str
) -> None:
    admin = add_user(sm, Role.platform_admin)
    with sm.begin() as session:
        audited(session, admin, "customer.grant", "user", uuid.uuid4(), "why", None, None)
    with pytest.raises(DBAPIError, match="append-only"), sm.begin() as session:
        session.execute(sa.text(statement))
    with sm() as session:
        assert session.scalar(select(AdminAuditLog.reason)) == "why"


def test_an_admin_with_audit_rows_cannot_be_deleted(sm: sessionmaker[Session]) -> None:
    """``admin_user_id`` is RESTRICT: SET NULL would be an UPDATE the trigger refuses, and CASCADE
    would erase history."""
    admin = add_user(sm, Role.platform_admin)
    with sm.begin() as session:
        audited(session, admin, "customer.grant", "user", uuid.uuid4(), "why", None, None)
    with pytest.raises(IntegrityError), sm.begin() as session:
        session.execute(sa.text("DELETE FROM users WHERE id = :u"), {"u": admin})
    assert _row_count(sm) == 1


def test_the_target_has_no_foreign_key_so_history_outlives_the_customer(
    sm: sessionmaker[Session],
) -> None:
    admin = add_user(sm, Role.platform_admin)
    customer = add_user(sm, Role.student)
    with sm.begin() as session:
        audited(session, admin, "customer.grant", "user", customer, "why", None, None)
    with sm.begin() as session:
        session.execute(sa.text("DELETE FROM users WHERE id = :u"), {"u": customer})
    assert _row_count(sm) == 1


def test_two_requests_with_one_key_serialise_on_the_idempotency_lock(
    sm: sessionmaker[Session],
) -> None:
    """The second request waits for the first to commit, then sees its row (DV-12)."""
    admin = add_user(sm, Role.platform_admin)
    target = uuid.uuid4()
    key = f"admin-grant:{target}:req-1"
    first_holds_lock = threading.Event()
    second_is_trying = threading.Event()
    seen_by_second: list[bool] = []
    errors: list[BaseException] = []

    def first() -> None:
        try:
            with sm.begin() as session:
                lock_idempotency_key(session, key)
                first_holds_lock.set()
                assert second_is_trying.wait(timeout=10)
                time.sleep(0.4)  # long enough for an unserialised second request to read first
                assert not already_applied(session, action="customer.grant", idempotency_key=key)
                audited(
                    session,
                    admin,
                    "customer.grant",
                    "user",
                    target,
                    "why",
                    None,
                    {"idempotency_key": key},
                )
        except BaseException as exc:  # handed to the test thread
            errors.append(exc)
            first_holds_lock.set()

    def second() -> None:
        try:
            assert first_holds_lock.wait(timeout=10)
            with sm.begin() as session:
                second_is_trying.set()
                lock_idempotency_key(session, key)
                seen_by_second.append(
                    already_applied(session, action="customer.grant", idempotency_key=key)
                )
        except BaseException as exc:  # handed to the test thread
            errors.append(exc)
            second_is_trying.set()

    threads = [threading.Thread(target=first), threading.Thread(target=second)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert not errors, errors
    assert seen_by_second == [True]
    assert _row_count(sm) == 1


def test_different_keys_do_not_block_each_other(sm: sessionmaker[Session]) -> None:
    with sm.begin() as holder:
        lock_idempotency_key(holder, "admin-grant:a")
        done = threading.Event()

        def other() -> None:
            with sm.begin() as session:
                lock_idempotency_key(session, "admin-grant:b")
            done.set()

        thread = threading.Thread(target=other)
        thread.start()
        assert done.wait(timeout=10), "an unrelated key waited on the held lock"
        thread.join(timeout=10)


def _tier(sm: sessionmaker[Session], price: int = 5000) -> uuid.UUID:
    tid = uuid.uuid4()
    with sm.begin() as session:
        session.execute(
            sa.text(
                "INSERT INTO plan_tiers (id, code, name, price_minor, allowance_units, "
                "included_seats, seat_allowance_units, extra_seat_price_minor) "
                "VALUES (:id, :c, :c, :p, 700, 3, 200, 900)"
            ),
            {"id": tid, "c": f"tier-{tid}", "p": price},
        )
    return tid


def test_create_all_gives_every_new_tier_terms_version_one(sm: sessionmaker[Session]) -> None:
    tier = _tier(sm, 1234)
    with sm() as session:
        row = session.execute(
            sa.text(
                "SELECT terms_version, price_minor, extra_seat_price_minor, allowance_units, "
                "included_seats, seat_allowance_units FROM plan_tier_terms WHERE plan_tier_id = :t"
            ),
            {"t": tier},
        ).one()
    assert tuple(row) == (1, 1234, 900, 700, 3, 200)


def test_create_all_inserts_a_tier_with_an_invalid_amount_and_gives_it_no_terms(
    sm: sessionmaker[Session],
) -> None:
    bad = _tier(sm, -100)
    with sm() as session:
        assert (
            session.scalar(
                sa.text("SELECT count(*) FROM plan_tier_terms WHERE plan_tier_id = :t"), {"t": bad}
            )
            == 0
        )


@pytest.mark.parametrize(
    "statement",
    ["UPDATE plan_tier_terms SET price_minor = 1", "DELETE FROM plan_tier_terms"],
)
def test_create_all_makes_plan_tier_terms_append_only(
    sm: sessionmaker[Session], statement: str
) -> None:
    _tier(sm)
    with pytest.raises(DBAPIError, match="plan_tier_terms is append-only"), sm.begin() as session:
        session.execute(sa.text(statement))
    with sm() as session:
        assert session.scalar(sa.text("SELECT price_minor FROM plan_tier_terms")) == 5000


def test_a_subscription_must_name_terms_that_exist(sm: sessionmaker[Session]) -> None:
    tier = _tier(sm)
    student = add_user(sm, Role.student)
    with pytest.raises(IntegrityError, match="fk_subscriptions_terms"), sm.begin() as session:
        session.execute(
            sa.text(
                "INSERT INTO subscriptions (user_id, plan_tier_id, terms_version) "
                "VALUES (:u, :t, 2)"
            ),
            {"u": student, "t": tier},
        )


def test_create_all_and_the_cleanup_leave_the_one_billing_settings_row(
    sm: sessionmaker[Session],
) -> None:
    with sm() as session:
        assert session.scalar(sa.text("SELECT count(*) FROM billing_settings")) == 1
        assert (
            session.scalar(sa.text("SELECT price_change_notice_days FROM billing_settings")) == 14
        )


def test_create_all_makes_the_idempotency_key_unique_per_action(sm: sessionmaker[Session]) -> None:
    admin = add_user(sm, Role.platform_admin)
    after = {"idempotency_key": "admin-grant:u:r1"}
    with sm.begin() as session:
        audited(session, admin, "customer.grant", "user", uuid.uuid4(), "why", None, after)
    # No lock taken: the unique index refuses the second grant.
    with (
        pytest.raises(IntegrityError, match="ix_admin_audit_log_idempotency"),
        sm.begin() as session,
    ):
        audited(session, admin, "customer.grant", "user", uuid.uuid4(), "why", None, after)
    with sm.begin() as session:
        audited(session, admin, "customer.adjust", "user", uuid.uuid4(), "why", None, after)
        audited(session, admin, "customer.grant", "user", uuid.uuid4(), "why", None, None)
        audited(session, admin, "customer.grant", "user", uuid.uuid4(), "why", None, None)
    assert _row_count(sm) == 4


def test_create_all_gives_a_tier_that_becomes_valid_by_an_update_its_terms(
    sm: sessionmaker[Session],
) -> None:
    tier = _tier(sm, -100)
    with sm.begin() as session:
        session.execute(
            sa.text("UPDATE plan_tiers SET price_minor = 7700 WHERE id = :t"), {"t": tier}
        )
        session.execute(
            sa.text("UPDATE plan_tiers SET price_minor = 7800 WHERE id = :t"), {"t": tier}
        )
    with sm() as session:
        rows = session.execute(
            sa.text(
                "SELECT terms_version, price_minor FROM plan_tier_terms WHERE plan_tier_id = :t"
            ),
            {"t": tier},
        ).all()
    assert [tuple(r) for r in rows] == [(1, 7700)]


def test_a_terms_row_blocks_deleting_its_admin(sm: sessionmaker[Session]) -> None:
    admin = add_user(sm, Role.platform_admin)
    tier = _tier(sm)
    with sm.begin() as session:
        session.execute(
            sa.text(
                "INSERT INTO plan_tier_terms (plan_tier_id, terms_version, price_minor, "
                "extra_seat_price_minor, allowance_units, included_seats, "
                "seat_allowance_units, created_by) VALUES (:t, 2, 1, 1, 1, 1, 1, :a)"
            ),
            {"t": tier, "a": admin},
        )
    with (
        pytest.raises(IntegrityError, match="fk_plan_tier_terms_created_by_users"),
        sm.begin() as session,
    ):
        session.execute(sa.text("DELETE FROM users WHERE id = :u"), {"u": admin})
