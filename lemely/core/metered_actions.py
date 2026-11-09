"""The metered LLM-backed actions (spec §2.4, §5.6; index §Phase 04 and R12).

Phase 03 creates this module with the six base actions so seat scopes
(``teacher_members.scope_actions``) can be validated against :data:`SEAT_ACTIONS`.
Phase 04 adds ``mark_quiz`` and ``generate_flashcards`` and the ``ACTION_SPECS``
metering catalogue below; ``MeteredAction`` and ``SEAT_ACTIONS`` are unchanged. Pure:
no DB, no IO.

``has_subject``: the action works on a record that carries a subject (a paper, a quiz,
a plan), so per-subject seat routing can apply. ``seat_eligible``: a student runs the
action, so a teacher may put it in a seat's scope. Teacher-side actions (regrade, quiz
generation and preview) are never seat-paid.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING

from lemely.core.usage_types import EstimatorParams

if TYPE_CHECKING:
    from collections.abc import Mapping


class MeteredAction(StrEnum):
    MARK_PAPER = "mark_paper"
    REGRADE = "regrade"
    GENERATE_QUIZ = "generate_quiz"
    PREVIEW_QUIZ = "preview_quiz"
    SELF_REVIEW = "self_review"
    STUDY_PLAN = "study_plan"
    MARK_QUIZ = "mark_quiz"
    GENERATE_FLASHCARDS = "generate_flashcards"

    @property
    def has_subject(self) -> bool:
        """Return whether the action's record carries a subject."""
        return self.value not in _SUBJECTLESS

    @property
    def seat_eligible(self) -> bool:
        """Return whether a teacher may put the action in a seat's scope."""
        return self.value in _SEAT_ELIGIBLE


_SUBJECTLESS: frozenset[str] = frozenset()
"""Values of actions with no subject. Empty: every base action has one."""

_SEAT_ELIGIBLE: frozenset[str] = frozenset(
    {"mark_paper", "self_review", "study_plan", "mark_quiz", "generate_flashcards"}
)
"""Values of the actions a student runs (the ones a seat may pay for)."""

SEAT_ACTIONS: frozenset[MeteredAction] = frozenset(
    action for action in MeteredAction if action.seat_eligible
)
"""The actions a teacher may put in a seat's ``scope_actions`` (index R12)."""


# --- Billing phase 04: how each action is metered (spec §4.1, §5.7) -----------------


@dataclass(frozen=True)
class ActionSpec:
    """How one action is metered. ``default_*`` seed version 1 of the admin catalogue."""

    job_timeout: timedelta
    default_estimator: EstimatorParams
    default_units_per_usd: int


@dataclass(frozen=True)
class UsageTarget:
    """What the server read off the record an action works on. Never client input."""

    subject_code: str | None
    input_count: int


#: 1 unit = USD 0.001 at the seeded rate. Admins add new rate versions (spec §4.1).
DEFAULT_UNITS_PER_USD = 1000
#: Added to an action's timeout to form ``usage_jobs.expires_at`` (spec §5.7 step 3).
JOB_SLACK = timedelta(minutes=10)
#: Upper bound on countable inputs fed to an estimate. A larger request is still charged
#: its actual cost; the bound only stops a huge ``count`` inflating the hold.
MAX_ESTIMATE_INPUTS = 50


def _estimator(
    input_kind: str, base_low: int, base_high: int, per_low: int = 0, per_high: int = 0
) -> EstimatorParams:
    return EstimatorParams(
        version=1,
        input_kind=input_kind,
        base_low=base_low,
        base_high=base_high,
        per_input_low=per_low,
        per_input_high=per_high,
    )


def _spec(minutes: int, estimator: EstimatorParams) -> ActionSpec:
    return ActionSpec(
        job_timeout=timedelta(minutes=minutes),
        default_estimator=estimator,
        default_units_per_usd=DEFAULT_UNITS_PER_USD,
    )


ACTION_SPECS: Mapping[MeteredAction, ActionSpec] = MappingProxyType(
    {
        # Flat per paper: page counts are not stored (plan deviation 5, R16). 40-120 units
        # brackets the USD 0.10/paper target at 1000 units per USD. 45 minutes covers the
        # grading pool's queue wait.
        MeteredAction.MARK_PAPER: _spec(45, _estimator("none", 40, 120)),
        MeteredAction.REGRADE: _spec(45, _estimator("none", 40, 120)),
        MeteredAction.GENERATE_QUIZ: _spec(10, _estimator("questions", 2, 4, 2, 5)),
        MeteredAction.PREVIEW_QUIZ: _spec(10, _estimator("questions", 2, 4, 2, 5)),
        MeteredAction.SELF_REVIEW: _spec(5, _estimator("marks", 1, 2, 0, 1)),
        # Deterministic today (no model call), so it settles 0 units; metered so the seat
        # rule (§2.2) and any future narrator are covered.
        MeteredAction.STUDY_PLAN: _spec(2, _estimator("none", 0, 0)),
        MeteredAction.MARK_QUIZ: _spec(15, _estimator("questions", 1, 2, 1, 3)),
        MeteredAction.GENERATE_FLASHCARDS: _spec(5, _estimator("questions", 2, 4, 1, 2)),
    }
)
"""Every action's metering spec, keyed by action."""


def clamp_inputs(count: int) -> int:
    """Return ``count`` bounded to ``0..MAX_ESTIMATE_INPUTS`` for an estimate."""
    return max(0, min(count, MAX_ESTIMATE_INPUTS))


__all__ = [
    "ACTION_SPECS",
    "DEFAULT_UNITS_PER_USD",
    "JOB_SLACK",
    "MAX_ESTIMATE_INPUTS",
    "SEAT_ACTIONS",
    "ActionSpec",
    "MeteredAction",
    "UsageTarget",
    "clamp_inputs",
]
