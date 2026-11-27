"""The auto top-up settings service: ``get_auto_topup`` and ``put_auto_topup`` (Phase 06 T8, §4.6).

The caller (T9's routes) has already authorized payer to beneficiary; these tests pin what the
service itself refuses and in which order, the consent stamp an unattended MOTO charge depends on,
and the UTC-month spend. The guards have mutation proofs in the task report.

Runs on a throwaway Postgres database (``create_all``); skips without a local Postgres.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest
import sqlalchemy as sa

from lemely.db.auto_topup_repo import (
    DEFAULT_CURRENCY,
    DISABLED_CHARGE_FAILED,
    MAX_SETTING_VALUE,
    AutoTopupView,
    get_auto_topup,
    put_auto_topup,
    run_auto_topup_job,
)
from lemely.db.billing_repo import PhoneRequired
from lemely.db.merchant_charge_repo import MerchantChargeError
from lemely.db.models.billing import (
    AutoTopupSettings,
    CreditPack,
    PaymentPurpose,
    PaymentStatus,
)
from lemely.db.models.enums import Role
from tests.merchant_charge_fixtures import (
    FakeMotoClient,
    seed_payment_row,
    seed_saved_card,
    throwaway_database,
)
from tests.paymob_fixtures import PAYMOB_SETTINGS, link_parent, seed_pack, seed_user

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker

NOW = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)
LATER = NOW + timedelta(days=2)


@pytest.fixture(scope="module")
def sm() -> Iterator[sessionmaker[Session]]:
    with throwaway_database() as factory:
        yield factory


@pytest.fixture(autouse=True)
def _clean(sm: sessionmaker[Session]) -> None:
    with sm.begin() as session:
        session.execute(sa.delete(AutoTopupSettings))


def _people(sm: sessionmaker[Session], **parent: Any) -> dict[str, uuid.UUID]:
    """A parent linked to a child, the parent's card, and a 1000-unit 10 000-piaster pack."""
    child = seed_user(sm, Role.student)
    payer = seed_user(sm, Role.parent, **parent)
    link_parent(sm, parent_id=payer, child_id=child)
    return {
        "child": child,
        "payer": payer,
        "card": seed_saved_card(sm, payer),
        "pack": seed_pack(sm, units=1_000, price_minor=10_000),
    }


def _put(
    sm: sessionmaker[Session],
    ids: dict[str, uuid.UUID],
    *,
    payer: uuid.UUID | None = None,
    enabled: bool = True,
    threshold: int = 500,
    pack: uuid.UUID | None = None,
    card: uuid.UUID | None | str = "own",
    cap: int = 50_000,
    now: datetime = NOW,
) -> AutoTopupView:
    with sm.begin() as session:
        return put_auto_topup(
            session,
            payer_user_id=payer or ids["payer"],
            beneficiary_user_id=ids["child"],
            enabled=enabled,
            threshold_units=threshold,
            credit_pack_id=pack or ids["pack"],
            saved_card_id=ids["card"] if card == "own" else card,  # type: ignore[arg-type]
            monthly_cap_minor=cap,
            now=now,
        )


def _get(
    sm: sessionmaker[Session],
    ids: dict[str, uuid.UUID],
    *,
    payer: uuid.UUID | None = None,
    now: datetime = NOW,
) -> AutoTopupView:
    with sm() as session:
        return get_auto_topup(
            session,
            payer_user_id=payer or ids["payer"],
            beneficiary_user_id=ids["child"],
            now=now,
        )


def _row(sm: sessionmaker[Session], child: uuid.UUID) -> AutoTopupSettings:
    with sm() as session:
        row = session.scalars(
            sa.select(AutoTopupSettings).where(AutoTopupSettings.beneficiary_user_id == child)
        ).one()
        session.expunge(row)
        return row


def _count(sm: sessionmaker[Session]) -> int:
    with sm() as session:
        return session.scalar(sa.select(sa.func.count()).select_from(AutoTopupSettings)) or 0


def _code(call: Any) -> str:
    with pytest.raises(MerchantChargeError) as raised:
        call()
    return raised.value.code


# -- read -------------------------------------------------------------------------


def test_a_balance_with_no_row_reads_as_not_set_up(sm: sessionmaker[Session]) -> None:
    ids = _people(sm)

    view = _get(sm, ids)

    assert view == AutoTopupView(
        beneficiary_user_id=ids["child"],
        enabled=False,
        threshold_units=None,
        credit_pack_id=None,
        saved_card_id=None,
        monthly_cap_minor=None,
        spent_this_month_minor=0,
        currency=DEFAULT_CURRENCY,
        disabled_reason=None,
    )
    assert DEFAULT_CURRENCY == "EGP"
    assert _count(sm) == 0  # a read creates nothing


def test_create_then_read(sm: sessionmaker[Session]) -> None:
    ids = _people(sm)

    written = _put(sm, ids, threshold=700, cap=40_000)
    read = _get(sm, ids)

    assert read == written
    assert read == AutoTopupView(
        beneficiary_user_id=ids["child"],
        enabled=True,
        threshold_units=700,
        credit_pack_id=ids["pack"],
        saved_card_id=ids["card"],
        monthly_cap_minor=40_000,
        spent_this_month_minor=0,
        currency="EGP",
        disabled_reason=None,
    )


def test_get_uses_the_packs_currency(sm: sessionmaker[Session]) -> None:
    ids = _people(sm)
    _put(sm, ids)
    with sm.begin() as session:
        session.get_one(CreditPack, ids["pack"]).currency = "USD"

    assert _get(sm, ids).currency == "USD"


def test_another_payers_row_is_not_found_on_get(sm: sessionmaker[Session]) -> None:
    ids = _people(sm)
    _put(sm, ids)
    other = seed_user(sm, Role.parent)

    assert _code(lambda: _get(sm, ids, payer=other)) == "not_found"


# -- write: the owner is checked before anything else -----------------------------


@pytest.mark.parametrize("card", ["own_of_other", "stranger", "random", None])
def test_another_payers_row_is_refused_whatever_card_id_is_sent(
    sm: sessionmaker[Session], card: str | None
) -> None:
    ids = _people(sm)
    _put(sm, ids)
    other = seed_user(sm, Role.parent)
    cards = {
        "own_of_other": seed_saved_card(sm, other, token="tok_other"),
        "stranger": ids["card"],  # the row owner's card, sent by someone else
        "random": uuid.uuid4(),
        None: None,
    }

    code = _code(
        lambda: _put(sm, ids, payer=other, card=cards[card], pack=uuid.uuid4(), enabled=True)
    )

    assert code == "managed_by_another_payer"  # never card_not_found or pack_not_found
    assert _row(sm, ids["child"]).payer_user_id == ids["payer"]  # untouched


# -- write: refusals --------------------------------------------------------------


def test_a_card_that_is_not_the_payers_is_refused(sm: sessionmaker[Session]) -> None:
    ids = _people(sm)
    foreign = seed_saved_card(sm, seed_user(sm, Role.parent), token="tok_foreign")

    assert _code(lambda: _put(sm, ids, card=foreign)) == "card_not_found"
    assert _code(lambda: _put(sm, ids, card=uuid.uuid4())) == "card_not_found"
    assert _count(sm) == 0


def test_an_inactive_card_is_refused(sm: sessionmaker[Session]) -> None:
    ids = _people(sm)
    inactive = seed_saved_card(sm, ids["payer"], token="tok_old", is_active=False)

    assert _code(lambda: _put(sm, ids, card=inactive)) == "card_not_found"


@pytest.mark.parametrize(
    "pack_kwargs",
    [{"is_active": False}, {"price_minor": 0}],
    ids=["inactive", "free"],
)
def test_an_unusable_pack_is_refused(
    sm: sessionmaker[Session], pack_kwargs: dict[str, Any]
) -> None:
    ids = _people(sm)
    pack = seed_pack(sm, **{"units": 1_000, "price_minor": 10_000, **pack_kwargs})

    assert _code(lambda: _put(sm, ids, pack=pack)) == "pack_not_found"
    assert _code(lambda: _put(sm, ids, pack=uuid.uuid4())) == "pack_not_found"
    assert _count(sm) == 0


def test_enabling_without_a_card_is_refused(sm: sessionmaker[Session]) -> None:
    ids = _people(sm)

    assert _code(lambda: _put(sm, ids, card=None)) == "no_saved_card"


def test_enabling_with_a_cap_below_the_pack_price_is_refused_and_equal_is_accepted(
    sm: sessionmaker[Session],
) -> None:
    ids = _people(sm)

    assert _code(lambda: _put(sm, ids, cap=9_999)) == "cap_below_pack_price"
    assert _count(sm) == 0
    assert _put(sm, ids, cap=10_000).monthly_cap_minor == 10_000


def test_a_switched_off_save_with_cap_zero_and_no_card_succeeds(sm: sessionmaker[Session]) -> None:
    ids = _people(sm)

    view = _put(sm, ids, enabled=False, cap=0, card=None)

    assert (view.enabled, view.monthly_cap_minor, view.saved_card_id) == (False, 0, None)
    row = _row(sm, ids["child"])
    assert row.consented_at is None  # switching off never stamps consent


def test_enabling_without_a_phone_is_refused_but_switching_off_is_not(
    sm: sessionmaker[Session],
) -> None:
    ids = _people(sm, phone=None)

    with pytest.raises(PhoneRequired):
        _put(sm, ids)
    assert _count(sm) == 0
    assert _put(sm, ids, enabled=False).enabled is False


def test_enabling_with_a_phone_that_does_not_validate_is_refused(sm: sessionmaker[Session]) -> None:
    ids = _people(sm, phone="call me")

    with pytest.raises(PhoneRequired):
        _put(sm, ids)


@pytest.mark.parametrize(
    ("threshold", "cap"),
    [
        (0, 50_000),
        (-1, 50_000),
        (500, -1),
        (MAX_SETTING_VALUE + 1, 50_000),
        (500, MAX_SETTING_VALUE + 1),
    ],
)
def test_out_of_range_numbers_are_invalid_settings(
    sm: sessionmaker[Session], threshold: int, cap: int
) -> None:
    ids = _people(sm)

    assert _code(lambda: _put(sm, ids, threshold=threshold, cap=cap)) == "invalid_settings"
    assert _count(sm) == 0


def test_the_largest_accepted_numbers_fit_the_columns(sm: sessionmaker[Session]) -> None:
    ids = _people(sm)

    view = _put(sm, ids, threshold=MAX_SETTING_VALUE, cap=MAX_SETTING_VALUE)

    assert (view.threshold_units, view.monthly_cap_minor) == (MAX_SETTING_VALUE, MAX_SETTING_VALUE)


def test_the_service_flushes_and_leaves_the_commit_to_the_caller(sm: sessionmaker[Session]) -> None:
    ids = _people(sm)
    with sm() as session:
        put_auto_topup(
            session,
            payer_user_id=ids["payer"],
            beneficiary_user_id=ids["child"],
            enabled=True,
            threshold_units=500,
            credit_pack_id=ids["pack"],
            saved_card_id=ids["card"],
            monthly_cap_minor=50_000,
            now=NOW,
        )
        session.rollback()

    assert _count(sm) == 0


# -- write: consent, re-arm, re-enable --------------------------------------------


def test_switching_on_stamps_consent_arms_and_keeps_the_stamp_on_edits(
    sm: sessionmaker[Session],
) -> None:
    ids = _people(sm)

    _put(sm, ids, now=NOW)
    first = _row(sm, ids["child"])
    assert first.consented_at == NOW
    assert (first.armed, first.crossing_seq, first.disabled_reason) == (True, 1, None)

    _put(sm, ids, threshold=800, cap=60_000, now=LATER)  # an edit of a setting that stays on
    edited = _row(sm, ids["child"])
    assert edited.consented_at == NOW
    assert edited.crossing_seq == 1
    assert edited.threshold_units == 800


def test_switching_off_and_on_again_stamps_a_new_consent(sm: sessionmaker[Session]) -> None:
    ids = _people(sm)
    _put(sm, ids, now=NOW)
    _put(sm, ids, enabled=False, now=NOW)

    _put(sm, ids, now=LATER)

    row = _row(sm, ids["child"])
    assert row.consented_at == LATER
    assert row.crossing_seq == 2


def test_re_enabling_after_a_charge_failed_disable_clears_the_reason_and_bumps_the_crossing(
    sm: sessionmaker[Session],
) -> None:
    ids = _people(sm)
    _put(sm, ids, now=NOW)
    with sm.begin() as session:
        session.execute(
            sa.update(AutoTopupSettings)
            .where(AutoTopupSettings.beneficiary_user_id == ids["child"])
            .values(enabled=False, disabled_reason=DISABLED_CHARGE_FAILED, armed=False)
        )
    before = _row(sm, ids["child"])

    view = _put(sm, ids, now=LATER)

    assert (view.enabled, view.disabled_reason) == (True, None)
    after = _row(sm, ids["child"])
    assert after.crossing_seq == before.crossing_seq + 1
    assert after.armed is True
    assert after.consented_at == LATER


def test_re_enabling_is_not_switched_straight_off_again_by_the_old_failure(
    sm: sessionmaker[Session],
) -> None:
    ids = _people(sm)
    _put(sm, ids, now=NOW)
    failed = seed_payment_row(
        sm,
        payer_id=ids["payer"],
        beneficiary_id=ids["child"],
        purpose=PaymentPurpose.auto_topup,
        amount_minor=10_000,
        status=PaymentStatus.failed,
        credit_pack_id=ids["pack"],
        dedupe_key=f"auto_topup:{uuid.uuid4()}:1",
    )
    with sm.begin() as session:
        session.execute(
            sa.update(AutoTopupSettings)
            .where(AutoTopupSettings.beneficiary_user_id == ids["child"])
            .values(enabled=False, disabled_reason=DISABLED_CHARGE_FAILED, last_payment_id=failed)
        )

    _put(sm, ids, now=LATER)
    assert run_auto_topup_job(sm, FakeMotoClient(), PAYMOB_SETTINGS, now=LATER) == 0

    row = _row(sm, ids["child"])
    assert (row.enabled, row.disabled_reason) == (True, None)


def test_re_enabling_keeps_an_in_flight_top_up_as_the_latest(sm: sessionmaker[Session]) -> None:
    ids = _people(sm)
    _put(sm, ids, now=NOW)
    pending = seed_payment_row(
        sm,
        payer_id=ids["payer"],
        beneficiary_id=ids["child"],
        purpose=PaymentPurpose.auto_topup,
        amount_minor=10_000,
        status=PaymentStatus.pending,
        credit_pack_id=ids["pack"],
        dedupe_key=f"auto_topup:{uuid.uuid4()}:1",
    )
    with sm.begin() as session:
        session.execute(
            sa.update(AutoTopupSettings)
            .where(AutoTopupSettings.beneficiary_user_id == ids["child"])
            .values(enabled=False, last_payment_id=pending)
        )

    _put(sm, ids, now=LATER)

    assert _row(sm, ids["child"]).last_payment_id == pending  # its paid handler can still re-arm


# -- spend this month -------------------------------------------------------------


def test_spent_this_month_counts_in_flight_and_paid_top_ups_of_this_utc_month_only(
    sm: sessionmaker[Session],
) -> None:
    ids = _people(sm)
    _put(sm, ids)
    month_start = datetime(2026, 11, 1, tzinfo=UTC)

    def seed(status: PaymentStatus, amount: int, created: datetime, **kw: Any) -> None:
        seed_payment_row(
            sm,
            payer_id=ids["payer"],
            beneficiary_id=ids["child"],
            purpose=kw.get("purpose", PaymentPurpose.auto_topup),
            amount_minor=amount,
            status=status,
            credit_pack_id=ids["pack"],
            created_at=created,
        )

    seed(PaymentStatus.created, 1_000, month_start)  # the first instant of the month counts
    seed(PaymentStatus.pending, 2_000, NOW)
    seed(PaymentStatus.paid, 4_000, NOW)
    seed(PaymentStatus.failed, 100_000, NOW)  # money never taken
    seed(PaymentStatus.voided, 100_000, NOW)
    seed(PaymentStatus.paid, 100_000, month_start - timedelta(seconds=1))  # last month, UTC
    seed(PaymentStatus.paid, 100_000, datetime(2026, 12, 1, tzinfo=UTC))  # next month
    seed(PaymentStatus.paid, 100_000, NOW, purpose=PaymentPurpose.credit_pack)  # not a top-up

    assert _get(sm, ids).spent_this_month_minor == 7_000
    assert _get(sm, ids, now=datetime(2026, 10, 31, 23, 0, tzinfo=UTC)).spent_this_month_minor == (
        100_000
    )


def test_not_set_up_view_still_reports_the_spend(sm: sessionmaker[Session]) -> None:
    ids = _people(sm)
    seed_payment_row(
        sm,
        payer_id=ids["payer"],
        beneficiary_id=ids["child"],
        purpose=PaymentPurpose.auto_topup,
        amount_minor=10_000,
        status=PaymentStatus.paid,
        credit_pack_id=ids["pack"],
        created_at=NOW,
    )

    view = _get(sm, ids)

    assert (view.enabled, view.threshold_units, view.spent_this_month_minor) == (
        False,
        None,
        10_000,
    )
