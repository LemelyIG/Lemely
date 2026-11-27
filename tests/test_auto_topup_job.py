"""Auto top-up charge job, paid handler and failure sweep (Phase 06 T8, spec §5.5 steps 3-5).

Money safety enforced here: a queued top-up is re-checked at charge time (setting, consent, payer,
parent link, card), charged once and never retried blindly; only a verified callback or reconcile
pass grants, to the beneficiary and exactly once; the latest failure switches the setting off with
``charge_failed`` and tells the payer once; an older failure or an older late payment changes
nothing. The guards have mutation proofs in the task report.

Runs on a throwaway Postgres database (``create_all``); skips without a local Postgres.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest
import sqlalchemy as sa
from structlog.testing import capture_logs

from lemely.core.usage_types import GrantScope, Payer
from lemely.db import auto_topup_repo, billing_repo, merchant_charge_repo
from lemely.db.auto_topup_repo import (
    DISABLED_CHARGE_FAILED,
    enqueue_auto_topup,
    handle_auto_topup_paid,
    on_auto_topup_paid,
    put_auto_topup,
    run_auto_topup_job,
)
from lemely.db.billing_repo import BillingService, paid_handler_for
from lemely.db.merchant_charge_repo import charge_queued_payments
from lemely.db.models import ParentChildLink, User
from lemely.db.models.billing import (
    AutoTopupSettings,
    CreditPack,
    Payment,
    PaymentPurpose,
    PaymentStatus,
    SavedCard,
)
from lemely.db.models.billing_ops import BillingSettings
from lemely.db.models.enums import Role
from lemely.db.models.tutoring import EmailOutbox
from lemely.db.models.usage import GrantKind, UsageGrant
from lemely.db.usage_ledger_repo import UsageLedger
from lemely.io.paymob.client import PaymobError
from lemely.runtime.token_cipher import TokenCipher
from tests._concurrency import _Paused, _wait_until_a_backend_waits_on_a_lock
from tests.merchant_charge_fixtures import (
    FakeMotoClient,
    moto_txn,
    seed_auto_topup,
    seed_payment_row,
    seed_saved_card,
    throwaway_database,
)
from tests.paymob_fixtures import (
    PAYMOB_SETTINGS,
    TEST_CARD_TOKEN_KEY,
    FakePaymobClient,
    link_parent,
    seed_pack,
    seed_user,
)
from tests.usage_db import add_debt

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from sqlalchemy.orm import Session, sessionmaker

NOW = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)
TOKEN = "tok_card_1"


@pytest.fixture(scope="module")
def sm() -> Iterator[sessionmaker[Session]]:
    with throwaway_database() as factory:
        yield factory


@pytest.fixture(autouse=True)
def _clean_queue(sm: sessionmaker[Session]) -> None:
    """The job takes every queued row and every failed setting, so each test starts without any."""
    with sm.begin() as session:
        session.execute(sa.delete(EmailOutbox))
        session.execute(sa.delete(AutoTopupSettings))
        session.execute(
            sa.delete(Payment).where(
                Payment.status == PaymentStatus.created, Payment.dedupe_key.is_not(None)
            )
        )


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------


def _scene(
    sm: sessionmaker[Session], *, self_paying: bool = False, threshold: int = 500
) -> dict[str, uuid.UUID]:
    """A child (100 credits, below the threshold), its payer, a 1000-unit pack and a card."""
    child = seed_user(sm, Role.student)
    payer = child if self_paying else seed_user(sm, Role.parent)
    if not self_paying:
        link_parent(sm, parent_id=payer, child_id=child)
    pack = seed_pack(sm, units=1_000, price_minor=10_000)
    card = seed_saved_card(sm, payer, token=TOKEN)
    setting = seed_auto_topup(
        sm,
        beneficiary_id=child,
        payer_id=payer,
        pack_id=pack,
        card_id=card,
        threshold=threshold,
        consented_at=NOW - timedelta(days=1),
    )
    with sm.begin() as session:
        UsageLedger(session).issue_grant(
            owner_user_id=child,
            kind=GrantKind.credit_pack,
            units=100,
            idempotency_key=f"seed:{child}",
            effective_at=NOW - timedelta(days=2),
            expires_at=NOW + timedelta(days=90),
            visible=True,
        )
    return {"child": child, "payer": payer, "pack": pack, "card": card, "setting": setting}


def _queued(sm: sessionmaker[Session], **kwargs: Any) -> dict[str, uuid.UUID]:
    """``_scene`` plus the one top-up the post-settle path would have queued."""
    ids = _scene(sm, **kwargs)
    with sm.begin() as session:
        payment = enqueue_auto_topup(session, ids["child"], now=NOW)
        assert payment is not None
        ids["payment"] = payment.id
    return ids


def _run(
    sm: sessionmaker[Session],
    client: FakeMotoClient,
    *,
    now: datetime = NOW,
    should_stop: Callable[[], bool] | None = None,
    should_stop_row: Callable[[], bool] | None = None,
) -> int:
    return run_auto_topup_job(
        sm,
        client,
        PAYMOB_SETTINGS,
        now=now,
        should_stop=should_stop,
        should_stop_row=should_stop_row,
    )


def _client(sm: sessionmaker[Session]) -> FakeMotoClient:
    return FakeMotoClient(sessionmaker=sm)


def _setting(sm: sessionmaker[Session], child: uuid.UUID) -> AutoTopupSettings:
    with sm() as session:
        row = session.scalars(
            sa.select(AutoTopupSettings).where(AutoTopupSettings.beneficiary_user_id == child)
        ).one()
        session.expunge(row)
        return row


def _payment(sm: sessionmaker[Session], payment_id: uuid.UUID) -> Payment:
    with sm() as session:
        row = session.get_one(Payment, payment_id)
        session.expunge(row)
        return row


def _mails(sm: sessionmaker[Session], template: str = "auto_topup_failed") -> list[EmailOutbox]:
    with sm() as session:
        return list(session.scalars(sa.select(EmailOutbox).where(EmailOutbox.template == template)))


def _grants(sm: sessionmaker[Session], payment_id: uuid.UUID) -> list[UsageGrant]:
    with sm() as session:
        rows = list(
            session.scalars(sa.select(UsageGrant).where(UsageGrant.payment_id == payment_id))
        )
        session.expunge_all()
        return rows


def _deliver(sm: sessionmaker[Session], obj: dict[str, Any]) -> None:
    with sm.begin() as session:
        BillingService(
            session, FakePaymobClient(), PAYMOB_SETTINGS, now=lambda: NOW
        ).apply_transaction_callback(obj)


def _reconcile(sm: sessionmaker[Session], obj: dict[str, Any]) -> int:
    inquirer = FakePaymobClient()
    inquirer.inquiry_response = obj
    with sm() as session:
        return BillingService(
            session, inquirer, PAYMOB_SETTINGS, now=lambda: NOW
        ).reconcile_pending(now=NOW + timedelta(minutes=20))


def _txn_for(sm: sessionmaker[Session], payment_id: uuid.UUID, txn_id: int) -> dict[str, Any]:
    row = _payment(sm, payment_id)
    assert row.paymob_order_id is not None
    return moto_txn(
        order_id=row.paymob_order_id,
        merchant_order_id=row.special_reference,
        amount_cents=row.amount_minor,
        txn_id=txn_id,
    )


def _stamp_units(sm: sessionmaker[Session], payment_id: uuid.UUID, units: int = 1_000) -> None:
    """Seeded payments bypass the enqueue that stamps ``grant_units``; stamp them like it does."""
    with sm.begin() as session:
        session.execute(
            sa.update(Payment).where(Payment.id == payment_id).values(grant_units=units)
        )


def _decline(sm: sessionmaker[Session], payment_id: uuid.UUID) -> None:
    """Mark a payment as a charge that was sent and failed (``sent_at`` is stamped at the claim)."""
    with sm.begin() as session:
        session.execute(
            sa.update(Payment)
            .where(Payment.id == payment_id)
            .values(status=PaymentStatus.failed, sent_at=NOW)
        )


def _all_mails(sm: sessionmaker[Session]) -> dict[str, int]:
    """How many mails of each billing top-up template are queued."""
    templates = ("auto_topup_failed", "auto_topup_card_missing", "auto_topup_phone_required")
    return {t: len(_mails(sm, t)) for t in templates}


def _assert_failed_unsent(
    sm: sessionmaker[Session], client: FakeMotoClient, ids: dict[str, uuid.UUID], reason: str
) -> None:
    assert client.calls == []
    row = _payment(sm, ids["payment"])
    assert row.status is PaymentStatus.failed
    assert row.last_callback == {"source": "pre_send", "reason": reason}
    assert row.sent_at is None


# ---------------------------------------------------------------------------
# The charge.
# ---------------------------------------------------------------------------


def test_a_spent_budget_stops_the_charges_between_rows_and_the_rest_wait(
    sm: sessionmaker[Session],
) -> None:
    scenes = [_queued(sm) for _ in range(3)]
    client = _client(sm)

    def out_of_time() -> bool:
        return len(client.calls_to("pay_with_token")) >= 1

    _run(sm, client, should_stop=out_of_time)

    statuses = [_payment(sm, ids["payment"]).status for ids in scenes]
    # One charge ran whole; the others were never claimed, so they are still queued, not stuck.
    assert sorted(s.value for s in statuses) == ["created", "created", "pending"]
    assert len(client.calls_to("pay_with_token")) == 1

    _run(sm, client)  # the next pass charges exactly the rest

    assert {_payment(sm, ids["payment"]).status for ids in scenes} == {PaymentStatus.pending}
    assert len(client.calls_to("pay_with_token")) == 3


def test_no_top_up_is_charged_in_a_run_whose_refusal_step_ran_out_of_time(
    sm: sessionmaker[Session],
) -> None:
    scenes = [_queued(sm) for _ in range(3)]
    client = _client(sm)
    asked: list[int] = []

    def row_out_of_time() -> bool:
        asked.append(1)
        return len(asked) > 1  # room for one refusal check, not three

    _run(sm, client, should_stop=lambda: False, should_stop_row=row_out_of_time)

    # Two queued top-ups were never checked for refusal, so none may be charged in this run.
    assert client.calls_to("pay_with_token") == []
    assert {_payment(sm, ids["payment"]).status for ids in scenes} == {PaymentStatus.created}

    _run(sm, client)  # a run with time to check them all charges all three

    assert {_payment(sm, ids["payment"]).status for ids in scenes} == {PaymentStatus.pending}
    assert len(client.calls_to("pay_with_token")) == 3


def test_the_job_charges_the_payers_card_once_and_not_again(sm: sessionmaker[Session]) -> None:
    ids = _queued(sm)
    client = _client(sm)

    assert _run(sm, client) == 1
    assert _run(sm, client) == 0

    (call,) = client.calls_to("pay_with_token")
    assert call["card_token"] == TOKEN
    row = _payment(sm, ids["payment"])
    assert row.status is PaymentStatus.pending
    assert row.payer_user_id == ids["payer"]
    assert row.sent_at == NOW
    assert _setting(sm, ids["child"]).enabled is True
    assert _mails(sm) == []


def test_a_decline_switches_it_off_with_charge_failed_and_emails_the_payer_once(
    sm: sessionmaker[Session],
) -> None:
    ids = _queued(sm)
    client = _client(sm)
    client.pay_response = {"id": 1, "success": False, "pending": False}

    _run(sm, client)
    _run(sm, client)

    setting = _setting(sm, ids["child"])
    assert (setting.enabled, setting.disabled_reason) == (False, DISABLED_CHARGE_FAILED)
    assert setting.disabled_reason == "charge_failed"  # the frontend contract (DV-10)
    assert setting.armed is True
    assert setting.crossing_seq == 1
    (mail,) = _mails(sm)
    assert mail.recipient_user_id == ids["payer"]
    assert mail.context == {"payment_id": str(ids["payment"])}
    assert mail.dedupe_key == f"auto_topup_failed:{ids['payment']}"
    assert len(client.calls_to("pay_with_token")) == 1


def test_a_deactivated_card_fails_without_calling_paymob_and_tells_the_card_is_gone(
    sm: sessionmaker[Session],
) -> None:
    ids = _queued(sm)
    with sm.begin() as session:
        session.get_one(SavedCard, ids["card"]).is_active = False
    client = _client(sm)

    assert _run(sm, client) == 1

    _assert_failed_unsent(sm, client, ids, "card_missing")
    assert _setting(sm, ids["child"]).disabled_reason == "charge_failed"
    # No charge was tried: the payer is told the card is gone, never that a charge failed.
    assert _all_mails(sm) == {
        "auto_topup_failed": 0,
        "auto_topup_card_missing": 1,
        "auto_topup_phone_required": 0,
    }


def test_a_failure_of_an_older_top_up_is_ignored(sm: sessionmaker[Session]) -> None:
    ids = _queued(sm)
    seed_payment_row(
        sm,
        payer_id=ids["payer"],
        beneficiary_id=ids["child"],
        purpose=PaymentPurpose.auto_topup,
        amount_minor=10_000,
        status=PaymentStatus.failed,
        credit_pack_id=ids["pack"],
        dedupe_key=f"auto_topup:{uuid.uuid4()}:0",
    )

    _run(sm, _client(sm))

    assert _setting(sm, ids["child"]).enabled is True
    assert _mails(sm) == []


def test_a_stale_queued_top_up_that_is_not_the_latest_is_not_charged(
    sm: sessionmaker[Session],
) -> None:
    ids = _queued(sm)
    stale = seed_payment_row(
        sm,
        payer_id=ids["payer"],
        beneficiary_id=ids["child"],
        purpose=PaymentPurpose.auto_topup,
        amount_minor=10_000,
        credit_pack_id=ids["pack"],
        dedupe_key=f"auto_topup:{uuid.uuid4()}:0",
        created_at=NOW - timedelta(days=3),
    )
    client = _client(sm)

    _run(sm, client)

    assert len(client.calls_to("pay_with_token")) == 1  # the latest only
    assert _payment(sm, stale).status is PaymentStatus.failed
    assert _payment(sm, stale).last_callback == {"source": "pre_send", "reason": "superseded"}
    assert _payment(sm, ids["payment"]).status is PaymentStatus.pending
    assert _setting(sm, ids["child"]).enabled is True  # the stale failure is not the latest


# -- re-checks at charge time (M5/I2) ----------------------------------------


def test_a_parent_link_removed_after_queuing_switches_off_as_parent_unlinked_and_mails_nobody(
    sm: sessionmaker[Session],
) -> None:
    ids = _queued(sm)
    with sm.begin() as session:
        session.execute(sa.delete(ParentChildLink).where(ParentChildLink.child_id == ids["child"]))
    client = _client(sm)

    _run(sm, client)

    _assert_failed_unsent(sm, client, ids, "parent_unlinked")
    setting = _setting(sm, ids["child"])
    assert (setting.enabled, setting.disabled_reason) == (False, "parent_unlinked")  # DV-10
    # The unlinked parent no longer manages the child: no "could not charge" mail, no mail at all.
    assert _all_mails(sm) == {
        "auto_topup_failed": 0,
        "auto_topup_card_missing": 0,
        "auto_topup_phone_required": 0,
    }


def test_a_payer_without_a_phone_at_charge_time_is_told_to_add_one_not_that_a_charge_failed(
    sm: sessionmaker[Session],
) -> None:
    ids = _queued(sm)
    with sm.begin() as session:
        session.get_one(User, ids["payer"]).phone = None
    client = _client(sm)

    _run(sm, client)
    _run(sm, client)

    _assert_failed_unsent(sm, client, ids, "phone_required")
    setting = _setting(sm, ids["child"])
    # Switched off (the brief): a re-enable is refused until a phone is added, and leaving it on
    # would queue a doomed charge at every settle. ``charge_failed`` is the only reason the
    # frontend knows (DV-10).
    assert (setting.enabled, setting.disabled_reason) == (False, "charge_failed")
    (mail,) = _mails(sm, "auto_topup_phone_required")
    assert mail.recipient_user_id == ids["payer"]
    assert mail.context == {"setting_id": str(ids["setting"])}
    assert mail.dedupe_key == f"auto_topup_phone_required:{ids['setting']}:{setting.crossing_seq}"
    assert _mails(sm) == []


def test_a_setting_without_consent_is_not_charged(sm: sessionmaker[Session]) -> None:
    ids = _queued(sm)
    with sm.begin() as session:
        session.execute(
            sa.update(AutoTopupSettings)
            .where(AutoTopupSettings.id == ids["setting"])
            .values(consented_at=None)
        )
    client = _client(sm)

    _run(sm, client)

    _assert_failed_unsent(sm, client, ids, "no_consent")
    assert _setting(sm, ids["child"]).enabled is True  # nothing happened to the payer
    assert _all_mails(sm) == {
        "auto_topup_failed": 0,
        "auto_topup_card_missing": 0,
        "auto_topup_phone_required": 0,
    }


def test_a_setting_that_changed_payer_is_not_charged_to_the_old_payer(
    sm: sessionmaker[Session],
) -> None:
    ids = _queued(sm)
    other = seed_user(sm, Role.parent)
    link_parent(sm, parent_id=other, child_id=ids["child"])
    with sm.begin() as session:
        session.execute(
            sa.update(AutoTopupSettings)
            .where(AutoTopupSettings.id == ids["setting"])
            .values(payer_user_id=other)
        )
    client = _client(sm)

    _run(sm, client)

    _assert_failed_unsent(sm, client, ids, "payer_changed")
    assert _setting(sm, ids["child"]).enabled is True
    assert _mails(sm) == []


@pytest.mark.parametrize(
    ("change", "reason"),
    [("disabled", "disabled"), ("no_card", "card_missing"), ("setting_gone", "setting_gone")],
)
def test_a_setting_that_is_off_cardless_or_gone_is_not_charged(
    sm: sessionmaker[Session], change: str, reason: str
) -> None:
    ids = _queued(sm)
    with sm.begin() as session:
        if change == "setting_gone":
            session.execute(sa.delete(AutoTopupSettings))
        else:
            values: dict[str, Any] = (
                {"enabled": False} if change == "disabled" else {"saved_card_id": None}
            )
            session.execute(
                sa.update(AutoTopupSettings)
                .where(AutoTopupSettings.id == ids["setting"])
                .values(**values)
            )
    client = _client(sm)

    _run(sm, client)

    _assert_failed_unsent(sm, client, ids, reason)
    assert _mails(sm) == []  # never "could not charge your card"


def test_the_card_of_another_user_on_the_setting_is_not_charged(sm: sessionmaker[Session]) -> None:
    ids = _queued(sm)
    stranger_card = seed_saved_card(sm, seed_user(sm, Role.parent), token="tok_stranger")
    with sm.begin() as session:
        session.execute(
            sa.update(AutoTopupSettings)
            .where(AutoTopupSettings.id == ids["setting"])
            .values(saved_card_id=stranger_card)
        )
    client = _client(sm)

    _run(sm, client)

    _assert_failed_unsent(sm, client, ids, "card_missing")
    assert _mails(sm) == []


# -- unknown outcome ---------------------------------------------------------


def test_an_unknown_outcome_stays_pending_enabled_and_silent_then_fails_into_the_sweep(
    sm: sessionmaker[Session],
) -> None:
    ids = _queued(sm)
    client = _client(sm)
    client.pay_response = PaymobError("pay timed out", timeout=True)

    _run(sm, client)
    _run(sm, client)

    assert _payment(sm, ids["payment"]).status is PaymentStatus.pending
    assert len(client.calls_to("pay_with_token")) == 1  # never charged blindly again
    assert _setting(sm, ids["child"]).enabled is True
    assert _mails(sm) == []

    # The reconcile give-up marks it failed (simulated), and the next run switches off and emails.
    with sm.begin() as session:
        session.execute(
            sa.update(Payment)
            .where(Payment.id == ids["payment"])
            .values(status=PaymentStatus.failed)
        )
    assert _run(sm, client) == 1
    setting = _setting(sm, ids["child"])
    assert (setting.enabled, setting.disabled_reason) == (False, DISABLED_CHARGE_FAILED)
    assert len(_mails(sm)) == 1
    assert len(client.calls_to("pay_with_token")) == 1


# ---------------------------------------------------------------------------
# Paid: the grant, the re-arm.
# ---------------------------------------------------------------------------


def test_the_real_callback_grants_the_child_visible_credits_once_and_rearms(
    sm: sessionmaker[Session],
) -> None:
    ids = _queued(sm)
    client = _client(sm)
    _run(sm, client)
    obj = _txn_for(sm, ids["payment"], 778_001)

    _deliver(sm, obj)
    _deliver(sm, obj)
    _reconcile(sm, obj)

    assert _payment(sm, ids["payment"]).status is PaymentStatus.paid
    (grant,) = _grants(sm, ids["payment"])
    assert grant.owner_user_id == ids["child"]  # never the payer
    assert grant.kind is GrantKind.auto_topup
    assert (grant.units, grant.visible) == (1_000, True)
    assert grant.expires_at == datetime(2027, 11, 14, 12, 0, tzinfo=UTC)  # 12 months after paid_at
    assert grant.idempotency_key == f"auto_topup:{ids['payment']}"
    setting = _setting(sm, ids["child"])
    assert (setting.armed, setting.crossing_seq) == (True, 1)
    with sm() as session:
        payer_grants = session.scalar(
            sa.select(sa.func.count())
            .select_from(UsageGrant)
            .where(UsageGrant.owner_user_id == ids["payer"], UsageGrant.payment_id.is_not(None))
        )
    assert payer_grants == 0


def test_the_grant_expires_after_the_admin_set_validity(sm: sessionmaker[Session]) -> None:
    ids = _queued(sm)
    with sm.begin() as session:
        session.execute(sa.text("UPDATE billing_settings SET credit_validity_months = 6"))
    try:
        _run(sm, _client(sm))
        _deliver(sm, _txn_for(sm, ids["payment"], 778_002))
        (grant,) = _grants(sm, ids["payment"])
        assert grant.expires_at == datetime(2027, 5, 14, 12, 0, tzinfo=UTC)
    finally:
        with sm.begin() as session:
            session.execute(sa.text("UPDATE billing_settings SET credit_validity_months = 12"))


def test_a_missing_validity_setting_fails_the_handler_closed(sm: sessionmaker[Session]) -> None:
    ids = _queued(sm)
    _run(sm, _client(sm))
    with sm.begin() as session:
        session.execute(sa.delete(BillingSettings))
    try:
        with pytest.raises(billing_repo.CreditValiditySettingMissing):
            _deliver(sm, _txn_for(sm, ids["payment"], 778_003))
        assert _grants(sm, ids["payment"]) == []
        assert _payment(sm, ids["payment"]).status is PaymentStatus.pending  # rolled back
    finally:
        with sm.begin() as session:
            session.add(BillingSettings(id=1))  # the column defaults are the shipped ones


def test_a_debt_is_repaid_first_by_the_grant(sm: sessionmaker[Session]) -> None:
    ids = _queued(sm)
    add_debt(sm, ids["child"], 300)
    _run(sm, _client(sm))

    _deliver(sm, _txn_for(sm, ids["payment"], 778_004))

    with sm() as session:
        credits = UsageLedger(session).available(
            [Payer(owner_user_id=ids["child"], scope=GrantScope.CREDITS)], now=NOW
        )
        assert not UsageLedger(session).has_debt(ids["child"])
    assert credits == 100 + 1_000 - 300  # 100 seed credits, the 1000 grant, 300 repaid first
    (grant,) = _grants(sm, ids["payment"])
    assert grant.units == 1_000


def test_a_paid_top_up_still_grants_when_the_setting_was_switched_off_meanwhile(
    sm: sessionmaker[Session],
) -> None:
    ids = _queued(sm)
    _run(sm, _client(sm))
    with sm.begin() as session:
        session.execute(
            sa.update(AutoTopupSettings)
            .where(AutoTopupSettings.id == ids["setting"])
            .values(enabled=False)
        )

    _deliver(sm, _txn_for(sm, ids["payment"], 778_005))

    assert len(_grants(sm, ids["payment"])) == 1  # money taken, credits delivered
    assert _setting(sm, ids["child"]).enabled is False  # the re-arm does not switch it on


def test_a_late_paid_older_top_up_does_not_rearm(sm: sessionmaker[Session]) -> None:
    ids = _queued(sm)  # the latest top-up is queued: the setting is disarmed
    before = _setting(sm, ids["child"])
    assert before.armed is False
    older = seed_payment_row(
        sm,
        payer_id=ids["payer"],
        beneficiary_id=ids["child"],
        purpose=PaymentPurpose.auto_topup,
        amount_minor=10_000,
        status=PaymentStatus.paid,
        credit_pack_id=ids["pack"],
        dedupe_key=f"auto_topup:{uuid.uuid4()}:0",
        paid_at=NOW,
    )
    _stamp_units(sm, older)

    with sm.begin() as session:
        on_auto_topup_paid(session, session.get_one(Payment, older))

    assert len(_grants(sm, older)) == 1  # it still grants
    after = _setting(sm, ids["child"])
    assert (after.armed, after.crossing_seq) == (False, before.crossing_seq)  # but never re-arms
    assert after.last_payment_id == ids["payment"]


def test_a_paid_handler_without_paid_at_pack_or_units_raises(sm: sessionmaker[Session]) -> None:
    ids = _queued(sm)

    def seeded(**kwargs: Any) -> uuid.UUID:
        return seed_payment_row(
            sm,
            payer_id=ids["payer"],
            beneficiary_id=ids["child"],
            purpose=PaymentPurpose.auto_topup,
            amount_minor=10_000,
            dedupe_key=f"auto_topup:{uuid.uuid4()}:0",
            **kwargs,
        )

    no_clock = seeded(credit_pack_id=ids["pack"])
    _stamp_units(sm, no_clock)
    no_pack = seeded(paid_at=NOW)
    _stamp_units(sm, no_pack)
    no_units = seeded(credit_pack_id=ids["pack"], paid_at=NOW)  # never stamped at enqueue
    for payment_id in (no_clock, no_pack, no_units):
        with sm() as session:
            with pytest.raises(ValueError, match="no "):
                on_auto_topup_paid(session, session.get_one(Payment, payment_id))
            session.rollback()
        assert _grants(sm, payment_id) == []


# ---------------------------------------------------------------------------
# The failure sweep.
# ---------------------------------------------------------------------------


def test_one_setting_raising_in_the_sweep_does_not_stop_the_rest(
    sm: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    first, second = _queued(sm), _queued(sm)
    for ids in (first, second):
        _decline(sm, ids["payment"])
    real = auto_topup_repo.enqueue_auto_topup_failed

    def flaky(session: Session, *, payer_user_id: uuid.UUID, payment_id: uuid.UUID) -> bool:
        if payer_user_id == first["payer"]:
            raise RuntimeError("outbox down")
        return real(session, payer_user_id=payer_user_id, payment_id=payment_id)

    monkeypatch.setattr(auto_topup_repo, "enqueue_auto_topup_failed", flaky)

    with capture_logs() as logs:
        assert _run(sm, _client(sm)) == 1

    assert _setting(sm, first["child"]).enabled is True  # rolled back alone
    assert _setting(sm, second["child"]).enabled is False
    alert = [e for e in logs if e["event"] == "auto_topup_sweep_failed"]
    assert len(alert) == 1
    assert alert[0]["alert"] is True
    assert alert[0]["setting_id"] == str(first["setting"])
    assert alert[0]["error_type"] == "RuntimeError"


def test_the_sweep_is_bounded_per_run(
    sm: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(auto_topup_repo, "MERCHANT_SWEEP_BATCH", 1)
    rows = [_queued(sm), _queued(sm)]
    for ids in rows:
        _decline(sm, ids["payment"])

    assert _run(sm, _client(sm)) == 1
    assert _run(sm, _client(sm)) == 1
    assert _run(sm, _client(sm)) == 0
    assert all(_setting(sm, ids["child"]).enabled is False for ids in rows)


def test_a_payment_failed_but_paid_later_still_grants_through_the_handler(
    sm: sessionmaker[Session],
) -> None:
    ids = _queued(sm)
    client = _client(sm)
    client.pay_response = {"id": 1, "success": False, "pending": False}
    _run(sm, client)  # declined: switched off, payment failed (R20b: a success can still pay it)

    _deliver(sm, _txn_for(sm, ids["payment"], 778_006))

    assert _payment(sm, ids["payment"]).status is PaymentStatus.paid
    assert len(_grants(sm, ids["payment"])) == 1


# ---------------------------------------------------------------------------
# T7's card-missing disable now tells the payer, in the same transaction.
# ---------------------------------------------------------------------------


def _cardless(sm: sessionmaker[Session]) -> dict[str, uuid.UUID]:
    ids = _scene(sm)
    with sm.begin() as session:
        session.execute(
            sa.update(AutoTopupSettings)
            .where(AutoTopupSettings.id == ids["setting"])
            .values(saved_card_id=None)
        )
    return ids


def test_a_missing_card_switches_off_and_tells_the_payer_the_card_was_removed(
    sm: sessionmaker[Session],
) -> None:
    ids = _cardless(sm)
    for _ in range(2):
        with sm.begin() as session:
            assert enqueue_auto_topup(session, ids["child"], now=NOW) is None

    setting = _setting(sm, ids["child"])
    assert (setting.enabled, setting.disabled_reason) == (False, DISABLED_CHARGE_FAILED)
    (mail,) = _mails(sm, "auto_topup_card_missing")
    assert mail.recipient_user_id == ids["payer"]
    assert mail.context == {"setting_id": str(ids["setting"])}
    assert mail.dedupe_key == f"auto_topup_card_missing:{ids['setting']}:0"
    assert _mails(sm) == []  # not the "last charge failed" mail
    # The failure sweep never re-handles or double-notifies it (the setting is already off).
    assert _run(sm, _client(sm)) == 0
    assert len(_mails(sm, "auto_topup_card_missing")) == 1


def test_the_card_missing_notice_commits_or_rolls_back_with_the_disable(
    sm: sessionmaker[Session],
) -> None:
    ids = _cardless(sm)
    with sm() as session:
        assert enqueue_auto_topup(session, ids["child"], now=NOW) is None
        session.rollback()  # the same transaction: both go, so the next settle does both again

    assert _setting(sm, ids["child"]).enabled is True
    assert _mails(sm, "auto_topup_card_missing") == []

    with sm.begin() as session:
        enqueue_auto_topup(session, ids["child"], now=NOW)
    assert len(_mails(sm, "auto_topup_card_missing")) == 1
    assert _setting(sm, ids["child"]).enabled is False


# ---------------------------------------------------------------------------
# The price is fixed at queue time: units snapshot, pack, price and cap re-checks (review I1, I2).
# ---------------------------------------------------------------------------


def test_the_queued_payment_snapshots_the_units_and_a_pack_edit_does_not_change_the_grant(
    sm: sessionmaker[Session],
) -> None:
    ids = _queued(sm)
    assert _payment(sm, ids["payment"]).grant_units == 1_000  # stamped with the price
    with sm.begin() as session:
        session.get_one(
            CreditPack, ids["pack"]
        ).units = 400  # an admin edit after the price was fixed
    _run(sm, _client(sm))
    obj = _txn_for(sm, ids["payment"], 990_001)

    _deliver(sm, obj)
    _deliver(sm, obj)  # a replay keeps the stamp and grants nothing more

    assert _payment(sm, ids["payment"]).amount_minor == 10_000  # charged the old price
    (grant,) = _grants(sm, ids["payment"])
    assert grant.units == 1_000  # paid for 1000 units, granted 1000
    assert _payment(sm, ids["payment"]).grant_units == 1_000


def _edit(
    sm: sessionmaker[Session],
    ids: dict[str, uuid.UUID],
    *,
    pack: uuid.UUID | None = None,
    cap: int = 50_000,
) -> None:
    with sm.begin() as session:
        put_auto_topup(
            session,
            payer_user_id=ids["payer"],
            beneficiary_user_id=ids["child"],
            enabled=True,
            threshold_units=500,
            credit_pack_id=pack or ids["pack"],
            saved_card_id=ids["card"],
            monthly_cap_minor=cap,
            now=NOW,
        )


def _assert_refused_for_changed_terms(
    sm: sessionmaker[Session], client: FakeMotoClient, ids: dict[str, uuid.UUID]
) -> AutoTopupSettings:
    _assert_failed_unsent(sm, client, ids, "settings_changed")
    setting = _setting(sm, ids["child"])
    assert setting.enabled is True  # the payer's edit is respected, not punished
    assert (setting.armed, setting.disabled_reason, setting.last_payment_id) == (True, None, None)
    assert setting.crossing_seq == 1  # re-armed: the next crossing queues at the current terms
    assert _all_mails(sm) == {
        "auto_topup_failed": 0,
        "auto_topup_card_missing": 0,
        "auto_topup_phone_required": 0,
    }
    return setting


def test_a_queued_charge_is_refused_after_the_payer_moves_to_a_cheaper_pack_and_a_lower_cap(
    sm: sessionmaker[Session],
) -> None:
    ids = _queued(sm)
    cheap = seed_pack(sm, units=200, price_minor=2_000)
    _edit(sm, ids, pack=cheap, cap=5_000)
    client = _client(sm)

    _run(sm, client)

    _assert_refused_for_changed_terms(sm, client, ids)
    with sm.begin() as session:  # the next crossing queues at the new terms
        queued = enqueue_auto_topup(session, ids["child"], now=NOW)
        assert queued is not None
        assert (queued.amount_minor, queued.grant_units, queued.credit_pack_id) == (
            2_000,
            200,
            cheap,
        )


def test_a_queued_charge_above_a_lowered_cap_is_refused_even_with_the_same_pack(
    sm: sessionmaker[Session],
) -> None:
    ids = _queued(sm)
    with sm.begin() as session:  # a cap-only edit down to a figure the charge no longer fits
        session.execute(
            sa.update(AutoTopupSettings)
            .where(AutoTopupSettings.id == ids["setting"])
            .values(monthly_cap_minor=9_999)
        )
    client = _client(sm)

    _run(sm, client)

    _assert_refused_for_changed_terms(sm, client, ids)


@pytest.mark.parametrize("change", ["price_up", "price_down", "deactivated"])
def test_a_queued_charge_is_refused_when_the_pack_price_or_state_changed_after_queuing(
    sm: sessionmaker[Session], change: str
) -> None:
    ids = _queued(sm)
    with sm.begin() as session:
        pack = session.get_one(CreditPack, ids["pack"])
        if change == "deactivated":
            pack.is_active = False
        else:
            pack.price_minor = 12_000 if change == "price_up" else 8_000
    client = _client(sm)

    _run(sm, client)

    _assert_refused_for_changed_terms(sm, client, ids)


def test_a_queued_charge_is_refused_when_the_payer_switched_to_another_pack_at_the_same_price(
    sm: sessionmaker[Session],
) -> None:
    ids = _queued(sm)
    twin = seed_pack(sm, units=1_500, price_minor=10_000)
    _edit(sm, ids, pack=twin)
    client = _client(sm)

    _run(sm, client)

    _assert_refused_for_changed_terms(sm, client, ids)


def test_a_queued_charge_that_still_fits_the_terms_is_charged(sm: sessionmaker[Session]) -> None:
    ids = _queued(sm)
    _edit(sm, ids, cap=10_000)  # exactly the charge: spent so far plus this charge equals the cap
    client = _client(sm)

    _run(sm, client)

    assert len(client.calls_to("pay_with_token")) == 1
    assert _payment(sm, ids["payment"]).status is PaymentStatus.pending


# ---------------------------------------------------------------------------
# A card deleted after queuing (review I3): the card-missing notice, once, same transaction.
# ---------------------------------------------------------------------------


def test_a_card_hard_deleted_after_queuing_is_noticed_as_removed_once_and_never_as_a_failed_charge(
    sm: sessionmaker[Session],
) -> None:
    ids = _queued(sm)
    with sm.begin() as session:
        session.delete(session.get_one(SavedCard, ids["card"]))  # ON DELETE SET NULL
    client = _client(sm)

    _run(sm, client)
    _run(sm, client)

    _assert_failed_unsent(sm, client, ids, "card_missing")
    setting = _setting(sm, ids["child"])
    assert (setting.enabled, setting.disabled_reason) == (False, "charge_failed")
    (mail,) = _mails(sm, "auto_topup_card_missing")
    assert mail.recipient_user_id == ids["payer"]
    assert mail.dedupe_key == f"auto_topup_card_missing:{ids['setting']}:{setting.crossing_seq}"
    assert _mails(sm) == []  # "We could not charge your saved card" is never sent


def test_a_failing_notice_rolls_the_disable_back_and_the_next_run_finishes_it(
    sm: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    ids = _queued(sm)
    with sm.begin() as session:
        session.delete(session.get_one(SavedCard, ids["card"]))

    def boom(*_a: Any, **_k: Any) -> bool:
        raise RuntimeError("outbox down")

    monkeypatch.setattr(auto_topup_repo, "enqueue_auto_topup_card_missing", boom)
    with capture_logs():
        _run(sm, _client(sm))

    # The notice failed, so its disable rolled back with it: the setting is still on and nothing was
    # sent. The payment is failed unsent either way, and the next run's sweep finishes the job.
    assert _setting(sm, ids["child"]).enabled is True
    assert _mails(sm, "auto_topup_card_missing") == []
    monkeypatch.undo()
    _run(sm, _client(sm))
    assert len(_mails(sm, "auto_topup_card_missing")) == 1
    assert _setting(sm, ids["child"]).enabled is False


# ---------------------------------------------------------------------------
# The setting row is locked from the re-check to the claim (review M1).
# ---------------------------------------------------------------------------


def test_a_switch_off_in_flight_wins_over_the_charge(sm: sessionmaker[Session]) -> None:
    ids = _queued(sm)
    client = _client(sm)
    holder = sm()  # the payer's PUT: row locked, switch-off written, not yet committed
    holder.execute(
        sa.select(AutoTopupSettings.id)
        .where(AutoTopupSettings.id == ids["setting"])
        .with_for_update()
    )
    holder.execute(
        sa.update(AutoTopupSettings)
        .where(AutoTopupSettings.id == ids["setting"])
        .values(enabled=False)
    )
    charge = _Paused(
        lambda: charge_queued_payments(
            sm,
            client,
            PAYMOB_SETTINGS,
            purpose=PaymentPurpose.auto_topup,
            dedupe_prefix=auto_topup_repo.AUTO_TOPUP_DEDUPE_PREFIX,
            card_for=auto_topup_repo._card_for_charge(NOW),
            now=NOW,
        )
    )
    try:
        _wait_until_a_backend_waits_on_a_lock(sm)  # the charge really is queued behind the PUT
        assert client.calls == []
    finally:
        holder.commit()  # always release, so a red run cannot leave the row locked for others
        holder.close()
    charge.join()

    assert charge.error is None
    _assert_failed_unsent(sm, client, ids, "card_unusable")
    assert _setting(sm, ids["child"]).enabled is False


# ---------------------------------------------------------------------------
# A failure no setting explains must stop, not loop (re-review I4).
# ---------------------------------------------------------------------------


def _alerts(logs: list[dict[str, Any]], event: str) -> list[dict[str, Any]]:
    return [e for e in logs if e.get("event") == event and e.get("alert") is True]


def test_an_undecryptable_card_switches_off_notices_once_and_alerts_instead_of_looping(
    sm: sessionmaker[Session],
) -> None:
    ids = _queued(sm)
    with sm.begin() as session:  # a ciphertext sealed for another user (R22 row move, key rotation)
        session.get_one(SavedCard, ids["card"]).token = TokenCipher(TEST_CARD_TOKEN_KEY).encrypt(
            TOKEN, uuid.uuid4()
        )
    client = _client(sm)
    alert_events: list[dict[str, Any]] = []

    for _ in range(3):  # the settle path re-queues at every crossing while the setting is on
        with capture_logs() as logs:
            _run(sm, client)
        alert_events += _alerts(logs, "auto_topup_card_unusable")
        with sm.begin() as session:
            enqueue_auto_topup(session, ids["child"], now=NOW)

    assert client.calls == []  # nothing is ever sent
    setting = _setting(sm, ids["child"])
    assert (setting.enabled, setting.disabled_reason) == (False, "charge_failed")
    (mail,) = _mails(sm, "auto_topup_card_missing")
    assert mail.recipient_user_id == ids["payer"]
    assert _mails(sm) == []
    assert len(alert_events) == 1  # once, when it was switched off
    assert alert_events[0]["beneficiary"] == str(ids["child"])
    with sm() as session:  # and no further payment rows pile up
        rows = session.scalar(
            sa.select(sa.func.count())
            .select_from(Payment)
            .where(Payment.beneficiary_user_id == ids["child"])
        )
    assert rows == 1


def test_a_sweep_give_up_switches_off_notices_and_alerts_instead_of_re_arming(
    sm: sessionmaker[Session],
) -> None:
    ids = _queued(sm)
    with sm.begin() as session:  # what T3's MAX_SWEEP_ERRORS give-up leaves behind
        session.execute(
            sa.update(Payment)
            .where(Payment.id == ids["payment"])
            .values(
                status=PaymentStatus.failed,
                last_callback={"source": "pre_send", "reason": "sweep_error"},
            )
        )

    with capture_logs() as logs:
        assert _run(sm, _client(sm)) == 1

    setting = _setting(sm, ids["child"])
    assert (setting.enabled, setting.disabled_reason) == (False, "charge_failed")
    assert len(_mails(sm, "auto_topup_card_missing")) == 1
    assert len(_alerts(logs, "auto_topup_card_unusable")) == 1


def test_a_pre_send_failure_whose_cause_cleared_re_arms_quietly(sm: sessionmaker[Session]) -> None:
    ids = _queued(sm)
    with sm.begin() as session:  # refused for a missing phone; the payer has since added one
        session.execute(
            sa.update(Payment)
            .where(Payment.id == ids["payment"])
            .values(
                status=PaymentStatus.failed,
                last_callback={"source": "pre_send", "reason": "phone_required"},
            )
        )

    with capture_logs() as logs:
        _run(sm, _client(sm))

    setting = _setting(sm, ids["child"])
    assert (setting.enabled, setting.armed, setting.last_payment_id) == (True, True, None)
    assert [e for e in logs if e.get("alert")] == []
    assert _all_mails(sm) == {
        "auto_topup_failed": 0,
        "auto_topup_card_missing": 0,
        "auto_topup_phone_required": 0,
    }


# ---------------------------------------------------------------------------
# A card the payer removed is expected; one that vanished is not (re-review N3).
# ---------------------------------------------------------------------------


def test_a_card_the_payer_deactivated_is_logged_at_info_without_an_alert(
    sm: sessionmaker[Session],
) -> None:
    ids = _queued(sm)
    with sm.begin() as session:
        session.get_one(SavedCard, ids["card"]).is_active = False

    with capture_logs() as logs:
        _run(sm, _client(sm))

    assert [e for e in logs if e.get("alert")] == []
    removed = [e for e in logs if e.get("event") == "auto_topup_card_removed"]
    assert [e["log_level"] for e in removed] == ["info"]
    assert len(_mails(sm, "auto_topup_card_missing")) == 1  # the payer is still told


def test_a_card_that_vanished_still_alerts(sm: sessionmaker[Session]) -> None:
    ids = _queued(sm)
    with sm.begin() as session:
        session.delete(session.get_one(SavedCard, ids["card"]))

    with capture_logs() as logs:
        _run(sm, _client(sm))

    assert len(_alerts(logs, "auto_topup_card_missing")) == 1


# ---------------------------------------------------------------------------
# One lock order, payment then setting (re-review N1).
# ---------------------------------------------------------------------------


def test_the_refuse_pass_and_the_charge_pass_do_not_deadlock(sm: sessionmaker[Session]) -> None:
    ids = _queued(sm)
    client = _client(sm)
    refuser = sm()  # _refuse_one: the payment first ...
    refuser.execute(
        sa.select(Payment.id).where(Payment.id == ids["payment"]).with_for_update(skip_locked=True)
    ).one()
    charge = _Paused(
        lambda: charge_queued_payments(
            sm,
            client,
            PAYMOB_SETTINGS,
            purpose=PaymentPurpose.auto_topup,
            dedupe_prefix=auto_topup_repo.AUTO_TOPUP_DEDUPE_PREFIX,
            card_for=auto_topup_repo._card_for_charge(NOW),
            now=NOW,
        )
    )
    refuser_error: Exception | None = None
    try:
        _wait_until_a_backend_waits_on_a_lock(sm)  # the charge is queued behind the payment lock
        try:
            auto_topup_repo._lock_setting(refuser, ids["child"])  # ... then the setting
        except Exception as exc:
            refuser_error = exc
    finally:
        refuser.rollback()  # always release, so a red run cannot leave rows locked for others
        refuser.close()
    with capture_logs() as logs:
        charge.join()

    # With the setting locked first by the charge, the two wait on each other and Postgres aborts
    # one side (a false alert, and a step towards the give-up of I4).
    assert refuser_error is None
    assert charge.error is None
    assert [e for e in logs if e.get("event") == "merchant_charge_sweep_failed"] == []
    assert len(client.calls_to("pay_with_token")) == 1  # the payment was charged once, after


# ---------------------------------------------------------------------------
# Registry.
# ---------------------------------------------------------------------------


def test_the_auto_topup_handler_is_registered_and_all_three_phase_06_handlers_are() -> None:
    assert paid_handler_for(PaymentPurpose.auto_topup) is handle_auto_topup_paid
    assert (
        paid_handler_for(PaymentPurpose.upgrade_proration)
        is merchant_charge_repo.handle_upgrade_paid
    )
    assert (
        paid_handler_for(PaymentPurpose.extra_seats) is merchant_charge_repo.handle_extra_seats_paid
    )
