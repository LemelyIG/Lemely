"""The metered LLM-backed actions (spec §2.4, §5.6; index §Phase 04 and R12).

Phase 03 creates this module with the six base actions so seat scopes
(``teacher_members.scope_actions``) can be validated against :data:`SEAT_ACTIONS`.
Phase 04 replaces the body: it adds ``mark_quiz`` and ``generate_flashcards``, moves
both flags into its ``ACTION_SPECS`` table, and keeps ``MeteredAction`` and
``SEAT_ACTIONS``. Pure: no DB, no IO.

``has_subject``: the action works on a record that carries a subject (a paper, a quiz,
a plan), so per-subject seat routing can apply. ``seat_eligible``: a student runs the
action, so a teacher may put it in a seat's scope. Teacher-side actions (regrade, quiz
generation and preview) are never seat-paid.
"""

from __future__ import annotations

from enum import StrEnum


class MeteredAction(StrEnum):
    MARK_PAPER = "mark_paper"
    REGRADE = "regrade"
    GENERATE_QUIZ = "generate_quiz"
    PREVIEW_QUIZ = "preview_quiz"
    SELF_REVIEW = "self_review"
    STUDY_PLAN = "study_plan"

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

_SEAT_ELIGIBLE: frozenset[str] = frozenset({"mark_paper", "self_review", "study_plan"})
"""Values of the actions a student runs (the ones a seat may pay for)."""

SEAT_ACTIONS: frozenset[MeteredAction] = frozenset(
    action for action in MeteredAction if action.seat_eligible
)
"""The actions a teacher may put in a seat's ``scope_actions`` (index R12)."""


__all__ = ["SEAT_ACTIONS", "MeteredAction"]
