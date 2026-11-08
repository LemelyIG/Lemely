"""MeteredAction base values and the seat-eligible set (index R12, spec §2.2, §5.6)."""

from __future__ import annotations

from lemely.core.metered_actions import SEAT_ACTIONS, MeteredAction

BASE_VALUES = {
    "mark_paper",
    "regrade",
    "generate_quiz",
    "preview_quiz",
    "self_review",
    "study_plan",
}


def test_the_six_base_values_exist() -> None:
    assert {action.value for action in MeteredAction} >= BASE_VALUES


def test_every_base_action_has_a_subject() -> None:
    for value in BASE_VALUES:
        assert MeteredAction(value).has_subject is True


def test_only_student_actions_are_seat_eligible() -> None:
    assert {a for a in MeteredAction if a.seat_eligible} == {
        MeteredAction.MARK_PAPER,
        MeteredAction.SELF_REVIEW,
        MeteredAction.STUDY_PLAN,
    }


def test_seat_actions_is_the_seat_eligible_set() -> None:
    assert frozenset(a for a in MeteredAction if a.seat_eligible) == SEAT_ACTIONS
    assert MeteredAction.STUDY_PLAN in SEAT_ACTIONS
    assert MeteredAction.REGRADE not in SEAT_ACTIONS
