"""Pure value types for the usage ledger (Paymob billing spec §4.5, §5.6).

No database, no web: :mod:`lemely.db.usage_ledger_repo` and the Phase 04 payer
chain builder both import these. ``GrantScope`` decides which of an owner's
grants a :class:`Payer` may draw from:

* ``ALLOWANCE``: hidden grants (``visible = false``) with no seat link.
* ``CREDITS``: visible grants (credit packs, auto top-ups, adjustments).
* ``SEAT``: ``seat_allowance`` grants carrying this payer's ``teacher_member_id``.

A payer chain is an ordered ``Sequence[Payer]``; the last payer is the payer of
last resort and takes any debt. :func:`payer_to_json` and :func:`payer_from_json`
let the ledger store the chain on the job row, so ``settle`` can keep drawing
down the same chain without the caller passing it again.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

ESTIMATOR_INPUT_KINDS: frozenset[str] = frozenset({"pages", "marks", "questions", "none"})


class GrantScope(StrEnum):
    ALLOWANCE = "allowance"  # visible=False, teacher_member_id IS NULL
    CREDITS = "credits"  # visible=True
    SEAT = "seat"  # kind=seat_allowance AND teacher_member_id = Payer.teacher_member_id


@dataclass(frozen=True)
class Payer:
    owner_user_id: UUID
    scope: GrantScope
    teacher_member_id: UUID | None = None  # SEAT grants, and cap accounting
    cap_units: int | None = None  # None = no cap
    cap_window_start: datetime | None = None  # None with a cap = lifetime ("total")
    debt_exempt: bool = False  # True only for SEAT payers

    def __post_init__(self) -> None:
        """Reject payers the ledger could not honour."""
        if self.scope is GrantScope.SEAT and self.teacher_member_id is None:
            raise ValueError("a SEAT payer needs teacher_member_id")
        if self.debt_exempt and self.scope is not GrantScope.SEAT:
            raise ValueError("only a SEAT payer may be debt_exempt")
        if self.cap_units is not None and self.cap_units < 0:
            raise ValueError("cap_units must be >= 0")
        if self.cap_units is not None and self.teacher_member_id is None:
            raise ValueError("a capped payer needs teacher_member_id to count the cap")
        if self.cap_window_start is not None and self.cap_units is None:
            raise ValueError("cap_window_start without cap_units")


@dataclass(frozen=True)
class EstimatorParams:
    version: int
    input_kind: str
    base_low: int
    base_high: int
    per_input_low: int
    per_input_high: int

    def __post_init__(self) -> None:
        """Reject settings that would give an inverted or negative range."""
        if self.input_kind not in ESTIMATOR_INPUT_KINDS:
            raise ValueError(f"unknown estimator input_kind {self.input_kind!r}")
        if not 0 <= self.base_low <= self.base_high:
            raise ValueError("need 0 <= base_low <= base_high")
        if not 0 <= self.per_input_low <= self.per_input_high:
            raise ValueError("need 0 <= per_input_low <= per_input_high")


PayerJson = dict[str, str | int | bool | None]


def payer_to_json(payer: Payer) -> PayerJson:
    """A JSON-safe dict for ``usage_jobs.payer_chain``."""
    return {
        "owner_user_id": str(payer.owner_user_id),
        "scope": payer.scope.value,
        "teacher_member_id": (
            str(payer.teacher_member_id) if payer.teacher_member_id is not None else None
        ),
        "cap_units": payer.cap_units,
        "cap_window_start": (
            payer.cap_window_start.isoformat() if payer.cap_window_start is not None else None
        ),
        "debt_exempt": payer.debt_exempt,
    }


def payer_from_json(data: PayerJson) -> Payer:
    """Inverse of :func:`payer_to_json`."""
    member = data["teacher_member_id"]
    cap = data["cap_units"]
    window = data["cap_window_start"]
    return Payer(
        owner_user_id=UUID(str(data["owner_user_id"])),
        scope=GrantScope(str(data["scope"])),
        teacher_member_id=UUID(str(member)) if member is not None else None,
        cap_units=int(cap) if cap is not None else None,
        cap_window_start=datetime.fromisoformat(str(window)) if window is not None else None,
        debt_exempt=bool(data["debt_exempt"]),
    )


__all__ = [
    "ESTIMATOR_INPUT_KINDS",
    "EstimatorParams",
    "GrantScope",
    "Payer",
    "PayerJson",
    "payer_from_json",
    "payer_to_json",
]
