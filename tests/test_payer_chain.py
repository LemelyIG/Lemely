"""Spec §5.6: the payer chain, one test per table row and per rule beneath it."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta, timezone

import pytest

from lemely.core.metered_actions import SEAT_ACTIONS, MeteredAction
from lemely.core.payer_chain import (
    AssistantView,
    BlockFacts,
    ChainContext,
    SeatView,
    UsageBlockReason,
    block_reason,
    build_payer_chain,
    covering_seats,
    job_teacher_member_id,
    month_start,
    seat_scope_miss,
)
from lemely.core.usage_types import GrantScope, Payer

NOW = datetime(2026, 11, 4, 10, 0, tzinfo=UTC)
STUDENT = uuid.UUID(int=1)
MATHS_T = uuid.UUID(int=2)
PHYS_T = uuid.UUID(int=3)
LEAD = uuid.UUID(int=4)
ASSIST = uuid.UUID(int=5)


def _seat(
    n: int,
    teacher: uuid.UUID,
    subjects: set[str],
    actions: set[MeteredAction],
    *,
    cap: int | None = 100,
    period: str = "month",
    age_days: int = 10,
) -> SeatView:
    return SeatView(
        member_id=uuid.UUID(int=100 + n),
        teacher_user_id=teacher,
        scope_subjects=frozenset(subjects),
        scope_actions=frozenset(a.value for a in actions),
        cap_units=cap,
        cap_period=period,
        created_at=NOW - timedelta(days=age_days),
    )


MATHS = _seat(1, MATHS_T, {"0580"}, {MeteredAction.MARK_PAPER, MeteredAction.STUDY_PLAN})
PHYS = _seat(2, PHYS_T, {"0625"}, {MeteredAction.MARK_PAPER})
OWN = [Payer(STUDENT, GrantScope.ALLOWANCE), Payer(STUDENT, GrantScope.CREDITS)]


def _ctx(
    *,
    action: MeteredAction = MeteredAction.MARK_PAPER,
    subject_code: str | None = "0580",
    seats: tuple[SeatView, ...] = (),
    debtors: frozenset[uuid.UUID] = frozenset(),
    study_plan_generated_this_week: bool = False,
) -> ChainContext:
    return ChainContext(
        actor_user_id=STUDENT,
        action=action,
        subject_code=subject_code,
        now=NOW,
        seats=seats,
        debtors=debtors,
        study_plan_generated_this_week=study_plan_generated_this_week,
    )


def _assistant_ctx(
    view: AssistantView,
    *,
    debtors: frozenset[uuid.UUID] = frozenset(),
    seats: tuple[SeatView, ...] = (),
) -> ChainContext:
    return ChainContext(
        actor_user_id=ASSIST,
        action=MeteredAction.REGRADE,
        subject_code=None,
        now=NOW,
        seats=seats,
        assistant=view,
        debtors=debtors,
    )


def _seat_payer(seat: SeatView) -> Payer:
    return Payer(STUDENT, GrantScope.SEAT, teacher_member_id=seat.member_id, debt_exempt=True)


def _teacher_credits(seat: SeatView) -> Payer:
    return Payer(
        seat.teacher_user_id,
        GrantScope.CREDITS,
        teacher_member_id=seat.member_id,
        cap_units=seat.cap_units,
        cap_window_start=month_start(NOW),
    )


def _assert_ledger_invariants(chain: list[Payer]) -> None:
    """The three phase 01 Payer invariants, restated over a built chain.

    ``Payer.__post_init__`` already raises on a violation; asserting again here means a
    future relaxation of the constructor cannot silently let the builder drift.
    """
    assert chain, "a chain is never empty: the ledger raises on an empty chain"
    for payer in chain:
        if payer.debt_exempt:
            assert payer.scope is GrantScope.SEAT
        if payer.cap_units is not None:
            assert payer.teacher_member_id is not None
        if payer.cap_window_start is not None:
            assert payer.cap_units is not None
        if payer.scope is GrantScope.SEAT:
            assert payer.teacher_member_id is not None


# --- §5.6 table, one test per row ----------------------------------------------------


def test_row1_seated_in_scope_seat_then_teacher_credits_then_own() -> None:
    chain = build_payer_chain(_ctx(seats=(MATHS,)))
    assert chain == [_seat_payer(MATHS), _teacher_credits(MATHS), *OWN]


def test_row2_seated_out_of_scope_action_uses_own_balance_only() -> None:
    ctx = _ctx(seats=(PHYS,), subject_code="0625", action=MeteredAction.SELF_REVIEW)
    assert build_payer_chain(ctx) == OWN
    assert seat_scope_miss(ctx) is True


def test_row3_assistant_draws_lead_allowance_then_lead_credits_within_its_cap() -> None:
    member = uuid.UUID(int=200)
    ctx = _assistant_ctx(AssistantView(member, LEAD, cap_units=500, cap_period="month"))
    window = month_start(NOW)
    chain = build_payer_chain(ctx)
    assert chain == [
        Payer(
            LEAD,
            GrantScope.ALLOWANCE,
            teacher_member_id=member,
            cap_units=500,
            cap_window_start=window,
        ),
        Payer(
            LEAD,
            GrantScope.CREDITS,
            teacher_member_id=member,
            cap_units=500,
            cap_window_start=window,
        ),
    ]
    assert job_teacher_member_id(chain) == member
    _assert_ledger_invariants(chain)


def test_row4_anyone_else_pays_own_allowance_then_own_credits() -> None:
    assert build_payer_chain(_ctx()) == OWN


# --- seat selection, caps and windows ------------------------------------------------


def test_a_seat_without_a_cap_never_overflows_into_teacher_credits() -> None:
    seat = _seat(3, MATHS_T, {"0580"}, {MeteredAction.MARK_PAPER}, cap=None)
    assert build_payer_chain(_ctx(seats=(seat,))) == [_seat_payer(seat), *OWN]


def test_a_zero_cap_seat_never_overflows_into_teacher_credits() -> None:
    seat = _seat(8, MATHS_T, {"0580"}, {MeteredAction.MARK_PAPER}, cap=0)
    assert build_payer_chain(_ctx(seats=(seat,))) == [_seat_payer(seat), *OWN]


def test_a_total_cap_has_no_window() -> None:
    seat = _seat(4, MATHS_T, {"0580"}, {MeteredAction.MARK_PAPER}, period="total")
    chain = build_payer_chain(_ctx(seats=(seat,)))
    assert chain[1].cap_window_start is None
    assert chain[1].cap_units == 100


def test_a_monthly_cap_window_starts_at_the_month_start() -> None:
    chain = build_payer_chain(_ctx(seats=(MATHS,)))
    assert chain[1].cap_window_start == datetime(2026, 11, 1, tzinfo=UTC)


# --- per-subject routing -------------------------------------------------------------


def test_routing_is_per_subject() -> None:
    maths = build_payer_chain(_ctx(seats=(MATHS, PHYS), subject_code="0580"))
    physics = build_payer_chain(_ctx(seats=(MATHS, PHYS), subject_code="0625"))
    assert maths[0] == _seat_payer(MATHS)
    assert physics[0] == _seat_payer(PHYS)
    assert all(p.teacher_member_id != PHYS.member_id for p in maths)
    assert all(p.teacher_member_id != MATHS.member_id for p in physics)


def test_a_subject_no_seat_covers_uses_own_balance_without_a_scope_miss() -> None:
    ctx = _ctx(seats=(MATHS, PHYS), subject_code="0452")
    assert build_payer_chain(ctx) == OWN
    assert seat_scope_miss(ctx) is False


def test_two_seats_on_one_subject_all_allowances_then_all_teacher_credits() -> None:
    older = _seat(5, MATHS_T, {"0580"}, {MeteredAction.MARK_PAPER}, age_days=30)
    newer = _seat(6, PHYS_T, {"0580"}, {MeteredAction.MARK_PAPER}, age_days=5)
    chain = build_payer_chain(_ctx(seats=(newer, older)))
    assert chain == [
        _seat_payer(older),
        _seat_payer(newer),
        _teacher_credits(older),
        _teacher_credits(newer),
        *OWN,
    ]
    assert covering_seats(_ctx(seats=(newer, older))) == [older, newer]


def test_two_seats_created_together_order_by_member_id() -> None:
    a = _seat(10, MATHS_T, {"0580"}, {MeteredAction.MARK_PAPER}, age_days=7)
    b = _seat(11, PHYS_T, {"0580"}, {MeteredAction.MARK_PAPER}, age_days=7)
    assert covering_seats(_ctx(seats=(b, a))) == [a, b]
    assert covering_seats(_ctx(seats=(a, b))) == [a, b]


def test_only_the_seat_that_has_the_action_pays_when_two_cover_the_subject() -> None:
    marking = _seat(12, MATHS_T, {"0580"}, {MeteredAction.MARK_PAPER}, age_days=30)
    plans = _seat(13, PHYS_T, {"0580"}, {MeteredAction.STUDY_PLAN}, age_days=5)
    ctx = _ctx(seats=(marking, plans), action=MeteredAction.STUDY_PLAN)
    assert covering_seats(ctx) == [plans]
    assert build_payer_chain(ctx)[0] == _seat_payer(plans)
    assert seat_scope_miss(ctx) is False


# --- subject-less and teacher-only actions -------------------------------------------


def test_a_subjectless_action_uses_no_seat() -> None:
    ctx = _ctx(seats=(MATHS,), subject_code=None)
    assert build_payer_chain(ctx) == OWN
    assert covering_seats(ctx) == []
    assert seat_scope_miss(ctx) is False


def test_teacher_only_actions_are_never_seat_paid() -> None:
    seat = _seat(7, MATHS_T, {"0580"}, {MeteredAction.REGRADE})
    ctx = _ctx(seats=(seat,), action=MeteredAction.REGRADE)
    assert build_payer_chain(ctx) == OWN


def test_teacher_only_actions_are_never_a_seat_scope_miss() -> None:
    """No seat could ever cover them, so the 402 must not blame the seat's scope."""
    for action in MeteredAction:
        if action in SEAT_ACTIONS:
            continue
        ctx = _ctx(seats=(MATHS,), action=action)
        assert seat_scope_miss(ctx) is False, action


# --- study plan seat rule ------------------------------------------------------------


def test_study_plan_first_generation_this_week_is_seat_paid() -> None:
    ctx = _ctx(seats=(MATHS,), action=MeteredAction.STUDY_PLAN)
    assert build_payer_chain(ctx)[0] == _seat_payer(MATHS)


def test_study_plan_regeneration_in_the_same_week_draws_own_balance() -> None:
    ctx = _ctx(seats=(MATHS,), action=MeteredAction.STUDY_PLAN, study_plan_generated_this_week=True)
    assert build_payer_chain(ctx) == OWN
    assert seat_scope_miss(ctx) is False


def test_the_weekly_rule_applies_to_study_plans_only() -> None:
    ctx = _ctx(seats=(MATHS,), study_plan_generated_this_week=True)
    assert build_payer_chain(ctx)[0] == _seat_payer(MATHS)


def test_study_plan_without_the_seat_action_draws_own_balance() -> None:
    ctx = _ctx(seats=(PHYS,), subject_code="0625", action=MeteredAction.STUDY_PLAN)
    assert build_payer_chain(ctx) == OWN
    assert seat_scope_miss(ctx) is True


# --- assistants ----------------------------------------------------------------------


def test_assistant_without_a_cap_is_unlimited_and_total_cap_has_no_window() -> None:
    member = uuid.UUID(int=201)
    unlimited = build_payer_chain(
        _assistant_ctx(AssistantView(member, LEAD, cap_units=None, cap_period="month"))
    )
    total = build_payer_chain(
        _assistant_ctx(AssistantView(member, LEAD, cap_units=50, cap_period="total"))
    )
    assert [p.cap_units for p in unlimited] == [None, None]
    assert [p.cap_window_start for p in unlimited] == [None, None]
    assert [p.cap_units for p in total] == [50, 50]
    assert [p.cap_window_start for p in total] == [None, None]
    _assert_ledger_invariants(unlimited)
    _assert_ledger_invariants(total)


def test_an_assistant_is_never_charged_to_its_own_balance_or_seats() -> None:
    member = uuid.UUID(int=202)
    chain = build_payer_chain(
        _assistant_ctx(
            AssistantView(member, LEAD, cap_units=10, cap_period="month"), seats=(MATHS,)
        )
    )
    assert {p.owner_user_id for p in chain} == {LEAD}
    assert all(p.scope is not GrantScope.SEAT for p in chain)


def test_an_assistant_never_hits_a_seat_scope_miss() -> None:
    view = AssistantView(uuid.UUID(int=203), LEAD, cap_units=None, cap_period="month")
    assert seat_scope_miss(_assistant_ctx(view, seats=(PHYS,))) is False


def test_an_indebted_lead_stays_payer_of_last_resort_for_its_assistant() -> None:
    member = uuid.UUID(int=204)
    view = AssistantView(member, LEAD, cap_units=500, cap_period="month")
    chain = build_payer_chain(_assistant_ctx(view, debtors=frozenset({LEAD})))
    assert [p.scope for p in chain] == [GrantScope.CREDITS]
    assert chain[-1].owner_user_id == LEAD
    assert chain[-1].cap_units == 500
    _assert_ledger_invariants(chain)


# --- debt rule -----------------------------------------------------------------------


def test_a_debtor_student_keeps_the_seat_and_stays_payer_of_last_resort() -> None:
    chain = build_payer_chain(_ctx(seats=(MATHS,), debtors=frozenset({STUDENT})))
    assert chain == [_seat_payer(MATHS), _teacher_credits(MATHS), OWN[1]]
    assert chain[-1].owner_user_id == STUDENT
    assert chain[0].debt_exempt is True
    _assert_ledger_invariants(chain)


def test_a_debtor_teacher_drops_out_of_the_overflow() -> None:
    chain = build_payer_chain(_ctx(seats=(MATHS,), debtors=frozenset({MATHS_T})))
    assert chain == [_seat_payer(MATHS), *OWN]


def test_only_the_indebted_teacher_of_two_seats_drops_out() -> None:
    older = _seat(14, MATHS_T, {"0580"}, {MeteredAction.MARK_PAPER}, age_days=30)
    newer = _seat(15, PHYS_T, {"0580"}, {MeteredAction.MARK_PAPER}, age_days=5)
    chain = build_payer_chain(_ctx(seats=(older, newer), debtors=frozenset({MATHS_T})))
    assert chain == [
        _seat_payer(older),
        _seat_payer(newer),
        _teacher_credits(newer),
        *OWN,
    ]


def test_every_seat_stays_usable_when_the_student_is_indebted() -> None:
    older = _seat(16, MATHS_T, {"0580"}, {MeteredAction.MARK_PAPER}, age_days=30)
    newer = _seat(17, PHYS_T, {"0580"}, {MeteredAction.MARK_PAPER}, age_days=5)
    chain = build_payer_chain(_ctx(seats=(older, newer), debtors=frozenset({STUDENT})))
    seat_payers = [p for p in chain if p.scope is GrantScope.SEAT]
    assert seat_payers == [_seat_payer(older), _seat_payer(newer)]
    assert all(p.debt_exempt for p in seat_payers)


def test_a_non_seated_debtor_has_only_the_last_resort_payer() -> None:
    chain = build_payer_chain(_ctx(debtors=frozenset({STUDENT})))
    assert chain == [OWN[1]]
    _assert_ledger_invariants(chain)


def test_debtors_unrelated_to_the_chain_change_nothing() -> None:
    stranger = uuid.UUID(int=999)
    assert build_payer_chain(_ctx(seats=(MATHS,), debtors=frozenset({stranger}))) == [
        _seat_payer(MATHS),
        _teacher_credits(MATHS),
        *OWN,
    ]


def test_the_last_payer_is_always_the_actors_credits() -> None:
    for debtors in (frozenset[uuid.UUID](), frozenset({STUDENT}), frozenset({STUDENT, MATHS_T})):
        chain = build_payer_chain(_ctx(seats=(MATHS,), debtors=debtors))
        assert chain[-1] == OWN[1]


# --- invariants over a matrix of contexts --------------------------------------------


def test_every_built_chain_satisfies_the_payer_invariants() -> None:
    all_seats = (
        MATHS,
        PHYS,
        _seat(20, MATHS_T, {"0580", "0625"}, set(SEAT_ACTIONS), cap=None),
        _seat(21, PHYS_T, {"0580"}, set(SEAT_ACTIONS), cap=0, period="total"),
        _seat(22, PHYS_T, {"0625"}, set(SEAT_ACTIONS), cap=5, period="total"),
    )
    debtor_sets = (
        frozenset[uuid.UUID](),
        frozenset({STUDENT}),
        frozenset({MATHS_T, PHYS_T}),
        frozenset({STUDENT, MATHS_T, PHYS_T}),
    )
    built = 0
    for action in MeteredAction:
        for subject in (None, "0580", "0625", "0452"):
            for debtors in debtor_sets:
                for weekly in (False, True):
                    chain = build_payer_chain(
                        _ctx(
                            action=action,
                            subject_code=subject,
                            seats=all_seats,
                            debtors=debtors,
                            study_plan_generated_this_week=weekly,
                        )
                    )
                    _assert_ledger_invariants(chain)
                    assert chain[-1] == OWN[1]
                    built += 1
    assert built == len(MeteredAction) * 4 * 4 * 2


# --- helpers -------------------------------------------------------------------------


def test_job_teacher_member_id_is_the_first_seat_or_none() -> None:
    assert job_teacher_member_id(build_payer_chain(_ctx(seats=(MATHS,)))) == MATHS.member_id
    assert job_teacher_member_id(OWN) is None
    assert job_teacher_member_id([]) is None


def test_month_start_is_the_first_utc_instant_of_the_month() -> None:
    assert month_start(NOW) == datetime(2026, 11, 1, tzinfo=UTC)


def test_month_start_converts_other_zones_to_utc_first() -> None:
    # 2026-12-01 01:00 in UTC+3 is still 2026-11-30 22:00 UTC: November's window.
    local = datetime(2026, 12, 1, 1, 0, tzinfo=timezone(timedelta(hours=3)))
    assert month_start(local) == datetime(2026, 11, 1, tzinfo=UTC)


def test_month_start_rejects_a_naive_datetime() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        month_start(datetime(2026, 11, 4, 10, 0))


# --- block reasons -------------------------------------------------------------------


def _facts(
    *,
    last_resort_in_debt: bool = False,
    seat_scope_miss: bool = False,
    has_live_plan: bool = False,
    has_credit_grant: bool = False,
) -> BlockFacts:
    return BlockFacts(
        last_resort_in_debt=last_resort_in_debt,
        seat_scope_miss=seat_scope_miss,
        has_live_plan=has_live_plan,
        has_credit_grant=has_credit_grant,
    )


def test_block_reason_precedence() -> None:
    assert block_reason(_facts(last_resort_in_debt=True, seat_scope_miss=True)) is (
        UsageBlockReason.OUTSTANDING_DEBT
    )
    assert block_reason(_facts(seat_scope_miss=True, has_credit_grant=True)) is (
        UsageBlockReason.OUT_OF_SEAT_SCOPE
    )
    assert block_reason(_facts(has_credit_grant=True, has_live_plan=True)) is (
        UsageBlockReason.INSUFFICIENT_CREDITS
    )
    assert block_reason(_facts(has_live_plan=True)) is UsageBlockReason.USAGE_LIMIT_REACHED
    assert block_reason(_facts()) is UsageBlockReason.NO_ACTIVE_PLAN


def test_block_reason_values_are_the_wire_strings() -> None:
    assert {r.value for r in UsageBlockReason} == {
        "usage_limit_reached",
        "no_active_plan",
        "insufficient_credits",
        "outstanding_debt",
        "out_of_seat_scope",
    }
