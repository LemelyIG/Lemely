"""The payer chain for one metered action (billing spec §5.6). Pure: no DB, no IO.

``lemely.db.usage_context_repo.load_chain_context`` reads the facts; this module turns
them into the ordered ``Payer`` list that ``UsageLedger.available``/``reserve``/``settle``
walk. The last payer is the payer of last resort: debt lands on its owner.

| Actor and action        | Chain                                                     |
|-------------------------|-----------------------------------------------------------|
| Seated student, action  | seat allowances (age order) -> those seats' teacher       |
| in a seat's scope       | credits (same order, capped) -> own allowance -> own      |
|                         | credits                                                   |
| Seated student, other   | own allowance -> own credits                              |
| action                  |                                                           |
| Assistant for a lead    | lead allowance -> lead credits (capped by the row)        |
| Anyone else             | own allowance -> own credits                              |

Debt rule: a payer whose owner has debt is dropped, except a seat payer (``debt_exempt``)
and the payer of last resort, which stays so debt still lands on the same owner. Keeping
it adds no spendable balance: every new grant repays debt first (§5.8), so a debtor's own
grants hold nothing.

Every payer built here satisfies the ledger's ``Payer`` invariants: a SEAT payer carries
``teacher_member_id``; ``debt_exempt`` is set only on SEAT payers; a cap always comes with
``teacher_member_id`` (the seat or assistant row the ledger counts the cap against); and a
window is set only together with a cap.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from lemely.core.metered_actions import SEAT_ACTIONS, MeteredAction
from lemely.core.usage_types import GrantScope, Payer

if TYPE_CHECKING:
    import uuid
    from collections.abc import Sequence


@dataclass(frozen=True)
class SeatView:
    """One active or leaving ``student_seat`` row, as the chain needs it."""

    member_id: uuid.UUID
    teacher_user_id: uuid.UUID
    scope_subjects: frozenset[str]
    scope_actions: frozenset[str]
    cap_units: int | None
    cap_period: str
    created_at: datetime


@dataclass(frozen=True)
class AssistantView:
    """The active ``assistant`` row the actor acts under."""

    member_id: uuid.UUID
    lead_teacher_user_id: uuid.UUID
    cap_units: int | None
    cap_period: str


@dataclass(frozen=True)
class ChainContext:
    """Everything the chain depends on, read on the server for one action."""

    actor_user_id: uuid.UUID
    action: MeteredAction
    subject_code: str | None
    now: datetime
    seats: tuple[SeatView, ...] = ()
    assistant: AssistantView | None = None
    debtors: frozenset[uuid.UUID] = frozenset()
    study_plan_generated_this_week: bool = False


class UsageBlockReason(StrEnum):
    """The machine-readable ``reason`` in a 402 body."""

    USAGE_LIMIT_REACHED = "usage_limit_reached"
    NO_ACTIVE_PLAN = "no_active_plan"
    INSUFFICIENT_CREDITS = "insufficient_credits"
    OUTSTANDING_DEBT = "outstanding_debt"
    OUT_OF_SEAT_SCOPE = "out_of_seat_scope"


@dataclass(frozen=True)
class BlockFacts:
    """Why a chain could not cover an estimate.

    The funding owner is the lead for an assistant, else the actor.
    """

    last_resort_in_debt: bool
    seat_scope_miss: bool
    has_live_plan: bool
    has_credit_grant: bool


def month_start(now: datetime) -> datetime:
    """The first instant (UTC) of ``now``'s calendar month: a monthly cap's window.

    ``now`` must be timezone-aware: a naive value would be read in the server's local
    zone and silently shift every cap window.
    """
    if now.tzinfo is None:
        raise ValueError("month_start needs a timezone-aware datetime")
    moment = now.astimezone(UTC)
    return moment.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _cap_window(cap_period: str, now: datetime) -> datetime | None:
    return month_start(now) if cap_period == "month" else None


def covering_seats(ctx: ChainContext) -> list[SeatView]:
    """The seats that pay for this action, oldest first (§5.6 seat selection)."""
    if ctx.subject_code is None or ctx.action not in SEAT_ACTIONS:
        return []
    if ctx.action is MeteredAction.STUDY_PLAN and ctx.study_plan_generated_this_week:
        return []
    seats = [
        seat
        for seat in ctx.seats
        if ctx.subject_code in seat.scope_subjects and ctx.action.value in seat.scope_actions
    ]
    return sorted(seats, key=lambda seat: (seat.created_at, str(seat.member_id)))


def seat_scope_miss(ctx: ChainContext) -> bool:
    """A seat covers the subject, but no seat on that subject covers the action.

    Only an action a seat could ever cover counts: blaming the seat's scope for a
    teacher-only action would send the user to the wrong fix.
    """
    if ctx.assistant is not None or ctx.subject_code is None or ctx.action not in SEAT_ACTIONS:
        return False
    same_subject = [seat for seat in ctx.seats if ctx.subject_code in seat.scope_subjects]
    return bool(same_subject) and not any(
        ctx.action.value in seat.scope_actions for seat in same_subject
    )


def _assistant_chain(assistant: AssistantView, now: datetime) -> list[Payer]:
    window = _cap_window(assistant.cap_period, now) if assistant.cap_units is not None else None
    return [
        Payer(
            owner_user_id=assistant.lead_teacher_user_id,
            scope=scope,
            teacher_member_id=assistant.member_id,
            cap_units=assistant.cap_units,
            cap_window_start=window,
        )
        for scope in (GrantScope.ALLOWANCE, GrantScope.CREDITS)
    ]


def _actor_chain(ctx: ChainContext) -> list[Payer]:
    seats = covering_seats(ctx)
    chain = [
        Payer(
            owner_user_id=ctx.actor_user_id,
            scope=GrantScope.SEAT,
            teacher_member_id=seat.member_id,
            debt_exempt=True,
        )
        for seat in seats
    ]
    # A seat with no cap (or a zero cap) never lets its teacher's credits pay.
    chain += [
        Payer(
            owner_user_id=seat.teacher_user_id,
            scope=GrantScope.CREDITS,
            teacher_member_id=seat.member_id,
            cap_units=seat.cap_units,
            cap_window_start=_cap_window(seat.cap_period, ctx.now),
        )
        for seat in seats
        if seat.cap_units is not None and seat.cap_units > 0
    ]
    chain += [
        Payer(owner_user_id=ctx.actor_user_id, scope=GrantScope.ALLOWANCE),
        Payer(owner_user_id=ctx.actor_user_id, scope=GrantScope.CREDITS),
    ]
    return chain


def build_payer_chain(ctx: ChainContext) -> list[Payer]:
    """The ordered payers for ``ctx`` (module docstring table), debt rule applied."""
    chain = _assistant_chain(ctx.assistant, ctx.now) if ctx.assistant else _actor_chain(ctx)
    last = chain[-1]
    kept = [p for p in chain[:-1] if p.debt_exempt or p.owner_user_id not in ctx.debtors]
    return [*kept, last]


def job_teacher_member_id(chain: Sequence[Payer]) -> uuid.UUID | None:
    """``usage_jobs.teacher_member_id``: the first seat or assistant row in the chain."""
    return next((p.teacher_member_id for p in chain if p.teacher_member_id is not None), None)


def block_reason(facts: BlockFacts) -> UsageBlockReason:
    """The one reason a 402 reports, most actionable first."""
    if facts.last_resort_in_debt:
        return UsageBlockReason.OUTSTANDING_DEBT
    if facts.seat_scope_miss:
        return UsageBlockReason.OUT_OF_SEAT_SCOPE
    if facts.has_credit_grant:
        return UsageBlockReason.INSUFFICIENT_CREDITS
    if facts.has_live_plan:
        return UsageBlockReason.USAGE_LIMIT_REACHED
    return UsageBlockReason.NO_ACTIVE_PLAN
