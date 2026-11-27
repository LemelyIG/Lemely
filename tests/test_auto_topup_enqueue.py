"""enqueue_auto_topup and the post-settle hook (Phase 06 T7, spec §5.5 steps 1-2).

Money safety enforced here: one queued charge per threshold crossing, never more than the
monthly cap in a calendar month, never while another top-up is in flight, nothing for a parent
whose link is gone (DV-9), and one winner when two settles race for the same owner. The guards
have mutation proofs in the task report.

Runs on a throwaway Postgres database (``create_all``); skips without a local Postgres.
"""

from __future__ import annotations

import threading
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from structlog.testing import capture_logs

from lemely.core.usage_types import GrantScope, Payer
from lemely.db import auto_topup_repo
from lemely.db.auto_topup_repo import (
    AUTO_TOPUP_DEDUPE_PREFIX,
    DISABLED_CHARGE_FAILED,
    DISABLED_PARENT_UNLINKED,
    auto_topup_post_settle_hook,
    enqueue_auto_topup,
    spent_this_month,
)
from lemely.db.models import ParentChildLink
from lemely.db.models.billing import (
    AutoTopupSettings,
    CreditPack,
    Payment,
    PaymentPurpose,
    PaymentStatus,
)
from lemely.db.models.enums import Role
from lemely.db.models.usage import GrantKind
from lemely.db.usage_ledger_repo import UsageLedger
from tests.merchant_charge_fixtures import (
    seed_auto_topup,
    seed_payment_row,
    seed_saved_card,
    throwaway_database,
)
from tests.paymob_fixtures import link_parent, seed_pack, seed_user

if TYPE_CHECKING:
    from collections.abc import Iterator
    from typing import Any

    from sqlalchemy.orm import Session, sessionmaker

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def sm() -> Iterator[sessionmaker[Session]]:
    with throwaway_database() as factory:
        yield factory


def _credits(sm: sessionmaker[Session], owner: uuid.UUID, units: int, *, key: str = "seed") -> None:
    with sm.begin() as session:
        UsageLedger(session).issue_grant(
            owner_user_id=owner,
            kind=GrantKind.credit_pack,
            units=units,
            idempotency_key=f"{key}:{owner}",
            effective_at=NOW - timedelta(days=1),
            expires_at=NOW + timedelta(days=90),
            visible=True,
        )


def _scene(
    sm: sessionmaker[Session],
    *,
    credits: int = 100,
    threshold: int = 500,
    cap: int = 50_000,
    enabled: bool = True,
    linked: bool = True,
    self_paying: bool = False,
    price_minor: int = 10_000,
    pack_active: bool = True,
    consented: bool = True,
) -> dict[str, uuid.UUID]:
    """A parent paying for a linked child (or the child paying for itself) with a 1000-unit pack."""
    child = seed_user(sm, Role.student)
    parent = child if self_paying else seed_user(sm, Role.parent)
    if linked and not self_paying:
        link_parent(sm, parent_id=parent, child_id=child)
    pack = seed_pack(sm, units=1_000, price_minor=price_minor, is_active=pack_active)
    card = seed_saved_card(sm, parent)
    setting = seed_auto_topup(
        sm,
        beneficiary_id=child,
        payer_id=parent,
        pack_id=pack,
        card_id=card,
        enabled=enabled,
        threshold=threshold,
        cap=cap,
        consented_at=NOW - timedelta(days=30) if consented else None,
    )
    if credits:
        _credits(sm, child, credits)
    return {"parent": parent, "child": child, "pack": pack, "card": card, "setting": setting}


def _enqueue(sm: sessionmaker[Session], owner: uuid.UUID, now: datetime = NOW) -> uuid.UUID | None:
    with sm.begin() as session:
        payment = enqueue_auto_topup(session, owner, now=now)
        return payment.id if payment is not None else None


def _setting(sm: sessionmaker[Session], owner: uuid.UUID) -> AutoTopupSettings:
    with sm() as session:
        return session.scalars(
            sa.select(AutoTopupSettings).where(AutoTopupSettings.beneficiary_user_id == owner)
        ).one()


def _top_ups(sm: sessionmaker[Session], owner: uuid.UUID) -> list[Payment]:
    with sm() as session:
        return list(
            session.scalars(
                sa.select(Payment).where(
                    Payment.beneficiary_user_id == owner,
                    Payment.purpose == PaymentPurpose.auto_topup,
                )
            )
        )


def _seed_top_up(
    sm: sessionmaker[Session],
    ids: dict[str, uuid.UUID],
    *,
    status: PaymentStatus,
    created_at: datetime = NOW,
    amount_minor: int = 10_000,
) -> uuid.UUID:
    return seed_payment_row(
        sm,
        payer_id=ids["parent"],
        beneficiary_id=ids["child"],
        purpose=PaymentPurpose.auto_topup,
        amount_minor=amount_minor,
        status=status,
        credit_pack_id=ids["pack"],
        dedupe_key=f"{AUTO_TOPUP_DEDUPE_PREFIX}{ids['child']}:{uuid.uuid4()}",
        created_at=created_at,
    )


# --- the crossing -----------------------------------------------------------------------


def test_one_payment_per_crossing_with_the_crossing_key(sm: sessionmaker[Session]) -> None:
    ids = _scene(sm, credits=100)
    first = _enqueue(sm, ids["child"])
    second = _enqueue(sm, ids["child"])
    assert first is not None
    assert second is None
    (payment,) = _top_ups(sm, ids["child"])
    assert payment.id == first
    assert payment.status is PaymentStatus.created
    assert (payment.payer_user_id, payment.beneficiary_user_id) == (ids["parent"], ids["child"])
    assert payment.amount_minor == 10_000
    assert payment.currency == "EGP"
    assert payment.credit_pack_id == ids["pack"]
    assert payment.dedupe_key == f"auto_topup:{ids['setting']}:0"
    setting = _setting(sm, ids["child"])
    assert (setting.armed, setting.last_payment_id) == (False, first)


def test_at_or_above_the_threshold_does_nothing(sm: sessionmaker[Session]) -> None:
    ids = _scene(sm, credits=500)
    assert _enqueue(sm, ids["child"]) is None
    assert _top_ups(sm, ids["child"]) == []
    setting = _setting(sm, ids["child"])
    assert (setting.armed, setting.crossing_seq) == (True, 0)  # still armed: no spurious bump


def test_disabled_setting_does_nothing(sm: sessionmaker[Session]) -> None:
    ids = _scene(sm, credits=0, enabled=False)
    assert _enqueue(sm, ids["child"]) is None
    assert _top_ups(sm, ids["child"]) == []


def test_no_setting_does_nothing(sm: sessionmaker[Session]) -> None:
    assert _enqueue(sm, seed_user(sm, Role.student)) is None


def test_a_setting_whose_card_was_deleted_is_switched_off_with_an_alert(
    sm: sessionmaker[Session],
) -> None:
    ids = _scene(sm, credits=0)
    with sm.begin() as session:
        session.execute(
            sa.update(AutoTopupSettings)
            .where(AutoTopupSettings.beneficiary_user_id == ids["child"])
            .values(saved_card_id=None)
        )
    with capture_logs() as logs:
        assert _enqueue(sm, ids["child"]) is None
    assert _top_ups(sm, ids["child"]) == []
    setting = _setting(sm, ids["child"])
    assert setting.enabled is False
    assert setting.disabled_reason == DISABLED_CHARGE_FAILED == "charge_failed"
    (line,) = [e for e in logs if e["event"] == "auto_topup_card_missing"]
    assert line["alert"] is True
    # Switched off once: the next settle finds a disabled setting and stays quiet.
    with capture_logs() as again:
        assert _enqueue(sm, ids["child"]) is None
    assert [e for e in again if e["event"] == "auto_topup_card_missing"] == []


def test_a_setting_without_consent_queues_nothing_stays_armed_and_alerts(
    sm: sessionmaker[Session],
) -> None:
    ids = _scene(sm, credits=0, consented=False)
    assert _setting(sm, ids["child"]).consented_at is None
    with capture_logs() as logs:
        assert _enqueue(sm, ids["child"]) is None
    assert _top_ups(sm, ids["child"]) == []
    setting = _setting(sm, ids["child"])
    assert (setting.enabled, setting.armed) == (True, True)
    (line,) = [e for e in logs if e["event"] == "auto_topup_no_consent"]
    assert line["alert"] is True
    with sm.begin() as session:  # a later consent stamp lets the next settle queue
        session.execute(
            sa.update(AutoTopupSettings)
            .where(AutoTopupSettings.beneficiary_user_id == ids["child"])
            .values(consented_at=NOW)
        )
    assert _enqueue(sm, ids["child"]) is not None


def test_no_consent_alert_while_the_balance_is_healthy(sm: sessionmaker[Session]) -> None:
    ids = _scene(sm, credits=5_000, consented=False)
    with capture_logs() as logs:
        for _ in range(5):
            assert _enqueue(sm, ids["child"]) is None
    assert [e for e in logs if e["event"] == "auto_topup_no_consent"] == []


def test_an_unlinked_parent_is_disabled_even_without_consent(sm: sessionmaker[Session]) -> None:
    ids = _scene(sm, credits=0, consented=False)
    with sm.begin() as session:
        session.execute(sa.delete(ParentChildLink).where(ParentChildLink.child_id == ids["child"]))
    assert _enqueue(sm, ids["child"]) is None
    setting = _setting(sm, ids["child"])
    assert (setting.enabled, setting.disabled_reason) == (False, DISABLED_PARENT_UNLINKED)


def test_a_recreated_setting_gets_a_new_key_and_does_not_collide_with_history(
    sm: sessionmaker[Session],
) -> None:
    ids = _scene(sm, credits=0)
    first = _enqueue(sm, ids["child"])
    assert first is not None
    with sm.begin() as session:
        session.get_one(Payment, first).status = PaymentStatus.paid
        session.execute(
            sa.delete(AutoTopupSettings).where(
                AutoTopupSettings.beneficiary_user_id == ids["child"]
            )
        )
    new_setting = seed_auto_topup(
        sm,
        beneficiary_id=ids["child"],
        payer_id=ids["parent"],
        pack_id=ids["pack"],
        card_id=ids["card"],
        consented_at=NOW,
    )
    assert new_setting != ids["setting"]
    second = _enqueue(sm, ids["child"])
    assert second is not None
    with sm() as session:
        assert session.get_one(Payment, first).dedupe_key == f"auto_topup:{ids['setting']}:0"
        assert session.get_one(Payment, second).dedupe_key == f"auto_topup:{new_setting}:0"


def test_below_threshold_while_disarmed_does_nothing(sm: sessionmaker[Session]) -> None:
    ids = _scene(sm, credits=100)
    assert _enqueue(sm, ids["child"]) is not None
    with sm.begin() as session:
        for payment in _top_ups(sm, ids["child"]):
            session.execute(
                sa.update(Payment)
                .where(Payment.id == payment.id)
                .values(status=PaymentStatus.failed)
            )
    assert _enqueue(sm, ids["child"]) is None  # the crossing already queued its top-up
    assert len(_top_ups(sm, ids["child"])) == 1


def test_back_above_threshold_rearms_once_and_the_next_crossing_has_a_new_key(
    sm: sessionmaker[Session],
) -> None:
    ids = _scene(sm, credits=100)
    first = _enqueue(sm, ids["child"])
    assert first is not None
    with sm.begin() as session:
        session.get_one(Payment, first).status = PaymentStatus.paid
        UsageLedger(session).issue_grant(
            owner_user_id=ids["child"],
            kind=GrantKind.credit_pack,
            units=1_000,
            idempotency_key=f"topup:{ids['child']}",
            effective_at=NOW - timedelta(hours=1),
            expires_at=NOW + timedelta(days=90),
            visible=True,
        )
    assert _enqueue(sm, ids["child"]) is None  # 1100 >= 500: re-arm only
    assert _enqueue(sm, ids["child"]) is None  # a second at-threshold call changes nothing
    setting = _setting(sm, ids["child"])
    assert (setting.armed, setting.crossing_seq) == (True, 1)
    with sm.begin() as session:
        UsageLedger(session).adjust(
            owner_user_id=ids["child"],
            units=-900,
            reason="spend",
            idempotency_key=f"spend:{ids['child']}",
            now=NOW,
        )
    second = _enqueue(sm, ids["child"])
    assert second is not None
    with sm() as session:
        assert session.get_one(Payment, second).dedupe_key == f"auto_topup:{ids['setting']}:1"


# --- cap, in-flight, month --------------------------------------------------------------


def test_cap_counts_this_months_top_ups_and_stays_armed(sm: sessionmaker[Session]) -> None:
    ids = _scene(sm, credits=0, cap=15_000)
    _seed_top_up(sm, ids, status=PaymentStatus.paid)
    assert _enqueue(sm, ids["child"]) is None  # 10 000 + 10 000 > 15 000
    assert _setting(sm, ids["child"]).armed is True  # next month may allow it
    assert len(_top_ups(sm, ids["child"])) == 1


def test_cap_allows_a_top_up_that_lands_exactly_on_it(sm: sessionmaker[Session]) -> None:
    ids = _scene(sm, credits=0, cap=20_000)
    _seed_top_up(sm, ids, status=PaymentStatus.paid)
    assert _enqueue(sm, ids["child"]) is not None  # 10 000 + 10 000 == 20 000


def test_cap_ignores_failed_and_voided_top_ups(sm: sessionmaker[Session]) -> None:
    ids = _scene(sm, credits=0, cap=15_000)
    _seed_top_up(sm, ids, status=PaymentStatus.failed)
    _seed_top_up(sm, ids, status=PaymentStatus.voided)
    with sm() as session:
        assert spent_this_month(session, ids["child"], now=NOW) == 0
    assert _enqueue(sm, ids["child"]) is not None


def test_spent_this_month_counts_in_flight_and_paid_top_ups(sm: sessionmaker[Session]) -> None:
    ids = _scene(sm, credits=0)
    _seed_top_up(sm, ids, status=PaymentStatus.created, amount_minor=1_000)
    _seed_top_up(sm, ids, status=PaymentStatus.pending, amount_minor=2_000)
    _seed_top_up(sm, ids, status=PaymentStatus.paid, amount_minor=4_000)
    with sm() as session:
        assert spent_this_month(session, ids["child"], now=NOW) == 7_000


def test_in_flight_top_up_blocks_another(sm: sessionmaker[Session]) -> None:
    for status in (PaymentStatus.created, PaymentStatus.pending):
        ids = _scene(sm, credits=0)
        _seed_top_up(sm, ids, status=status)
        assert _enqueue(sm, ids["child"]) is None
        assert len(_top_ups(sm, ids["child"])) == 1


def test_month_boundary_last_instant_of_last_month_does_not_count(
    sm: sessionmaker[Session],
) -> None:
    ids = _scene(sm, credits=0, cap=15_000)
    _seed_top_up(
        sm,
        ids,
        status=PaymentStatus.paid,
        created_at=datetime(2026, 11, 1, tzinfo=UTC) - timedelta(microseconds=1),
    )
    assert _enqueue(sm, ids["child"]) is not None


def test_month_boundary_first_instant_of_this_month_counts(sm: sessionmaker[Session]) -> None:
    ids = _scene(sm, credits=0, cap=15_000)
    _seed_top_up(sm, ids, status=PaymentStatus.paid, created_at=datetime(2026, 11, 1, tzinfo=UTC))
    assert _enqueue(sm, ids["child"]) is None


def test_spent_this_month_excludes_the_next_month(sm: sessionmaker[Session]) -> None:
    ids = _scene(sm, credits=0)
    _seed_top_up(sm, ids, status=PaymentStatus.paid, created_at=datetime(2026, 12, 1, tzinfo=UTC))
    with sm() as session:
        assert spent_this_month(session, ids["child"], now=NOW) == 0


# --- DV-9: the parent link --------------------------------------------------------------


def test_an_unlinked_parent_disables_the_setting_and_queues_nothing(
    sm: sessionmaker[Session],
) -> None:
    ids = _scene(sm, credits=0)
    with sm.begin() as session:
        session.execute(sa.delete(ParentChildLink).where(ParentChildLink.child_id == ids["child"]))
    assert _enqueue(sm, ids["child"]) is None
    assert _top_ups(sm, ids["child"]) == []
    setting = _setting(sm, ids["child"])
    assert setting.enabled is False
    assert setting.disabled_reason == DISABLED_PARENT_UNLINKED == "parent_unlinked"


def test_a_self_paying_student_needs_no_link(sm: sessionmaker[Session]) -> None:
    ids = _scene(sm, credits=0, self_paying=True)
    assert _enqueue(sm, ids["child"]) is not None
    assert _setting(sm, ids["child"]).enabled is True


def test_a_linked_parent_is_unaffected(sm: sessionmaker[Session]) -> None:
    ids = _scene(sm, credits=0)
    assert _enqueue(sm, ids["child"]) is not None
    assert _setting(sm, ids["child"]).disabled_reason is None


# --- the pack ---------------------------------------------------------------------------


def test_an_inactive_pack_queues_nothing_and_leaves_the_setting_alone(
    sm: sessionmaker[Session],
) -> None:
    ids = _scene(sm, credits=0, pack_active=False)
    assert _enqueue(sm, ids["child"]) is None
    setting = _setting(sm, ids["child"])
    assert (setting.enabled, setting.armed, setting.crossing_seq, setting.disabled_reason) == (
        True,
        True,
        0,
        None,
    )


def test_a_free_pack_queues_nothing_and_leaves_the_setting_alone(sm: sessionmaker[Session]) -> None:
    ids = _scene(sm, credits=0, price_minor=0)
    assert _enqueue(sm, ids["child"]) is None
    assert _top_ups(sm, ids["child"]) == []
    setting = _setting(sm, ids["child"])
    assert (setting.enabled, setting.armed) == (True, True)


def test_the_charge_is_the_current_pack_price(sm: sessionmaker[Session]) -> None:
    """UD13-B: the amount is read from the pack at enqueue time, not stored on the setting."""
    ids = _scene(sm, credits=0)
    with sm.begin() as session:
        session.get_one(CreditPack, ids["pack"]).price_minor = 12_500
    payment_id = _enqueue(sm, ids["child"])
    with sm() as session:
        assert session.get_one(Payment, payment_id).amount_minor == 12_500


# --- concurrency ------------------------------------------------------------------------


def test_two_concurrent_enqueues_for_one_owner_queue_exactly_one_payment(
    sm: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The second session blocks on the setting row lock and then sees the setting disarmed.

    ``insert_queued_payment`` is counted: the unique dedupe key would keep the second insert
    from duplicating the payment even without the lock, so the lock is proved by the second
    session never reaching the insert at all.
    """
    ids = _scene(sm, credits=0)
    inserts: list[int] = []
    real_insert = auto_topup_repo.insert_queued_payment

    def counting_insert(*args: Any, **kwargs: Any) -> Payment | None:
        inserts.append(1)
        return real_insert(*args, **kwargs)

    monkeypatch.setattr(auto_topup_repo, "insert_queued_payment", counting_insert)
    first_holds_lock = threading.Event()
    results: dict[str, uuid.UUID | None] = {}
    errors: list[BaseException] = []

    def first() -> None:
        try:
            with sm.begin() as session:
                payment = enqueue_auto_topup(session, ids["child"], now=NOW)
                results["first"] = payment.id if payment is not None else None
                first_holds_lock.set()
                time.sleep(1.0)  # hold the row lock while the second session arrives
        except BaseException as exc:
            errors.append(exc)
            first_holds_lock.set()

    def second() -> None:
        try:
            assert first_holds_lock.wait(timeout=10)
            with sm.begin() as session:
                payment = enqueue_auto_topup(session, ids["child"], now=NOW)
                results["second"] = payment.id if payment is not None else None
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=first), threading.Thread(target=second)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert not any(thread.is_alive() for thread in threads)
    assert errors == []
    assert results["first"] is not None
    assert results["second"] is None
    assert len(_top_ups(sm, ids["child"])) == 1
    assert len(inserts) == 1


# --- the hook ---------------------------------------------------------------------------


def _count_top_ups(sm: sessionmaker[Session], *owners: uuid.UUID) -> int:
    return sum(len(_top_ups(sm, owner)) for owner in owners)


def test_hook_checks_each_credits_owner_once(sm: sessionmaker[Session]) -> None:
    ids = _scene(sm, credits=0)
    payers = [
        Payer(owner_user_id=ids["child"], scope=GrantScope.ALLOWANCE),
        Payer(owner_user_id=ids["child"], scope=GrantScope.CREDITS),
        Payer(owner_user_id=ids["child"], scope=GrantScope.CREDITS),
    ]
    with sm.begin() as session:
        auto_topup_post_settle_hook(session, object(), payers, NOW)  # type: ignore[arg-type]
    assert _count_top_ups(sm, ids["child"]) == 1


def test_hook_ignores_allowance_only_chains(sm: sessionmaker[Session]) -> None:
    ids = _scene(sm, credits=0)
    with sm.begin() as session:
        auto_topup_post_settle_hook(
            session,
            object(),  # type: ignore[arg-type]
            [Payer(owner_user_id=ids["child"], scope=GrantScope.ALLOWANCE)],
            NOW,
        )
    assert _count_top_ups(sm, ids["child"]) == 0


def test_a_teacher_credits_payer_in_a_seat_chain_triggers_the_teachers_setting(
    sm: sessionmaker[Session],
) -> None:
    """Chain [seat(student), CREDITS(teacher)] runs the teacher's setting, not the student's."""
    teacher = seed_user(sm, Role.teacher)
    student = seed_user(sm, Role.student)
    pack = seed_pack(sm, units=1_000, price_minor=10_000)
    seed_auto_topup(
        sm,
        beneficiary_id=teacher,
        payer_id=teacher,
        pack_id=pack,
        card_id=seed_saved_card(sm, teacher),
        consented_at=NOW - timedelta(days=30),
    )
    chain = [
        Payer(
            owner_user_id=student,
            scope=GrantScope.SEAT,
            teacher_member_id=uuid.uuid4(),
            debt_exempt=True,
        ),
        Payer(owner_user_id=teacher, scope=GrantScope.CREDITS),
    ]
    with sm.begin() as session:
        auto_topup_post_settle_hook(session, object(), chain, NOW)  # type: ignore[arg-type]
    assert _count_top_ups(sm, teacher) == 1
    assert _count_top_ups(sm, student) == 0


def test_one_owners_failure_does_not_skip_the_next_owner_in_the_chain(
    sm: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    broken = _scene(sm, credits=0)
    healthy = _scene(sm, credits=0)
    real = auto_topup_repo.enqueue_auto_topup

    def flaky(session: Session, owner: uuid.UUID, *, now: datetime) -> Payment | None:
        if owner == broken["child"]:
            session.execute(
                sa.update(AutoTopupSettings)
                .where(AutoTopupSettings.beneficiary_user_id == owner)
                .values(armed=False)
            )
            raise RuntimeError("boom")
        return real(session, owner, now=now)

    monkeypatch.setattr(auto_topup_repo, "enqueue_auto_topup", flaky)
    chain = [
        Payer(owner_user_id=broken["child"], scope=GrantScope.CREDITS),
        Payer(owner_user_id=healthy["child"], scope=GrantScope.CREDITS),
    ]
    with capture_logs() as logs, sm.begin() as session:
        auto_topup_post_settle_hook(session, object(), chain, NOW)  # type: ignore[arg-type]
    assert _count_top_ups(sm, healthy["child"]) == 1
    assert _count_top_ups(sm, broken["child"]) == 0
    assert _setting(sm, broken["child"]).armed is True  # the failed owner's write was rolled back
    (line,) = [e for e in logs if e["event"] == "auto_topup_enqueue_failed"]
    assert line["alert"] is True
    assert line["beneficiary"] == str(broken["child"])
