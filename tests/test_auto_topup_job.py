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
    run_auto_topup_job,
)
from lemely.db.billing_repo import BillingService, paid_handler_for
from lemely.db.models import ParentChildLink, User
from lemely.db.models.billing import (
    AutoTopupSettings,
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
    FakePaymobClient,
    link_parent,
    seed_pack,
    seed_user,
)
from tests.usage_db import add_debt

if TYPE_CHECKING:
    from collections.abc import Iterator

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


def _run(sm: sessionmaker[Session], client: FakeMotoClient, *, now: datetime = NOW) -> int:
    return run_auto_topup_job(sm, client, PAYMOB_SETTINGS, now=now)


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


def test_a_deactivated_card_fails_without_calling_paymob_and_switches_off(
    sm: sessionmaker[Session],
) -> None:
    ids = _queued(sm)
    with sm.begin() as session:
        session.get_one(SavedCard, ids["card"]).is_active = False
    client = _client(sm)

    assert _run(sm, client) == 2  # one charge failed unsent, one setting switched off

    _assert_failed_unsent(sm, client, ids, "card_unusable")
    assert _setting(sm, ids["child"]).disabled_reason == "charge_failed"
    assert len(_mails(sm)) == 1


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
    assert _payment(sm, stale).last_callback == {"source": "pre_send", "reason": "card_unusable"}
    assert _payment(sm, ids["payment"]).status is PaymentStatus.pending
    assert _setting(sm, ids["child"]).enabled is True  # the stale failure is not the latest


# -- re-checks at charge time (M5/I2) ----------------------------------------


def test_a_parent_link_removed_before_the_charge_fails_unsent_and_switches_off(
    sm: sessionmaker[Session],
) -> None:
    ids = _queued(sm)
    with sm.begin() as session:
        session.execute(sa.delete(ParentChildLink).where(ParentChildLink.child_id == ids["child"]))
    client = _client(sm)

    _run(sm, client)

    # T7 already queued the payment, so the order is: the queued charge fails unsent, then the
    # failure sweep switches off with ``charge_failed`` (``parent_unlinked`` is T7's enqueue path).
    _assert_failed_unsent(sm, client, ids, "card_unusable")
    assert _setting(sm, ids["child"]).disabled_reason == "charge_failed"
    assert len(_mails(sm)) == 1


def test_a_payer_without_a_phone_at_charge_time_fails_unsent_and_switches_off(
    sm: sessionmaker[Session],
) -> None:
    ids = _queued(sm)
    with sm.begin() as session:
        session.get_one(User, ids["payer"]).phone = None
    client = _client(sm)

    _run(sm, client)

    _assert_failed_unsent(sm, client, ids, "phone_required")
    assert _setting(sm, ids["child"]).disabled_reason == "charge_failed"


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

    _assert_failed_unsent(sm, client, ids, "card_unusable")


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

    _assert_failed_unsent(sm, client, ids, "card_unusable")


@pytest.mark.parametrize("change", ["disabled", "no_card", "setting_gone"])
def test_a_setting_that_is_off_cardless_or_gone_is_not_charged(
    sm: sessionmaker[Session], change: str
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

    _assert_failed_unsent(sm, client, ids, "card_unusable")


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

    _assert_failed_unsent(sm, client, ids, "card_unusable")


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

    with sm.begin() as session:
        on_auto_topup_paid(session, session.get_one(Payment, older))

    assert len(_grants(sm, older)) == 1  # it still grants
    after = _setting(sm, ids["child"])
    assert (after.armed, after.crossing_seq) == (False, before.crossing_seq)  # but never re-arms
    assert after.last_payment_id == ids["payment"]


def test_a_paid_handler_without_paid_at_or_pack_raises(sm: sessionmaker[Session]) -> None:
    ids = _queued(sm)
    no_clock = seed_payment_row(
        sm,
        payer_id=ids["payer"],
        beneficiary_id=ids["child"],
        purpose=PaymentPurpose.auto_topup,
        amount_minor=10_000,
        credit_pack_id=ids["pack"],
        dedupe_key=f"auto_topup:{uuid.uuid4()}:0",
    )
    no_pack = seed_payment_row(
        sm,
        payer_id=ids["payer"],
        beneficiary_id=ids["child"],
        purpose=PaymentPurpose.auto_topup,
        amount_minor=10_000,
        dedupe_key=f"auto_topup:{uuid.uuid4()}:0",
        paid_at=NOW,
    )
    for payment_id in (no_clock, no_pack):
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
        with sm.begin() as session:
            session.execute(
                sa.update(Payment)
                .where(Payment.id == ids["payment"])
                .values(status=PaymentStatus.failed)
            )
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
        with sm.begin() as session:
            session.execute(
                sa.update(Payment)
                .where(Payment.id == ids["payment"])
                .values(status=PaymentStatus.failed)
            )

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
