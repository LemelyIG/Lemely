"""MeteredAction base values and the seat-eligible set (index R12, spec §2.2, §5.6)."""

from __future__ import annotations

from datetime import timedelta

from lemely.core.metered_actions import (
    ACTION_SPECS,
    DEFAULT_UNITS_PER_USD,
    JOB_SLACK,
    MAX_ESTIMATE_INPUTS,
    SEAT_ACTIONS,
    MeteredAction,
    UsageTarget,
    clamp_inputs,
)

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
        MeteredAction.MARK_QUIZ,
        MeteredAction.GENERATE_FLASHCARDS,
    }


def test_seat_actions_is_the_seat_eligible_set() -> None:
    assert frozenset(a for a in MeteredAction if a.seat_eligible) == SEAT_ACTIONS
    assert MeteredAction.STUDY_PLAN in SEAT_ACTIONS
    assert MeteredAction.REGRADE not in SEAT_ACTIONS


# Billing phase 04, Task 1: the audit's extra actions and the metering catalogue.


def test_no_action_is_subject_less() -> None:
    assert {a for a in MeteredAction if not a.has_subject} == set()


def test_the_audited_actions_are_exactly_the_enum() -> None:
    assert {a.value for a in MeteredAction} == BASE_VALUES | {"mark_quiz", "generate_flashcards"}


def test_the_new_actions_have_a_subject_and_can_sit_in_a_seat_scope() -> None:
    for action in (MeteredAction.MARK_QUIZ, MeteredAction.GENERATE_FLASHCARDS):
        assert action.has_subject
        assert action.seat_eligible
        assert action in SEAT_ACTIONS


def test_teacher_only_actions_are_not_seat_eligible() -> None:
    teacher_only = {MeteredAction.REGRADE, MeteredAction.PREVIEW_QUIZ, MeteredAction.GENERATE_QUIZ}
    assert not (teacher_only & SEAT_ACTIONS)


def test_every_action_has_a_metering_spec() -> None:
    assert set(ACTION_SPECS) == set(MeteredAction)
    for action, spec in ACTION_SPECS.items():
        est = spec.default_estimator
        assert est.version == 1, action
        assert est.input_kind in {"pages", "marks", "questions", "none"}, action
        assert 0 <= est.base_low <= est.base_high, action
        assert 0 <= est.per_input_low <= est.per_input_high, action
        assert spec.default_units_per_usd == DEFAULT_UNITS_PER_USD, action
        assert spec.job_timeout > timedelta(0), action


def test_marking_uses_a_flat_estimate_because_page_counts_are_not_stored() -> None:
    for action in (MeteredAction.MARK_PAPER, MeteredAction.REGRADE):
        est = ACTION_SPECS[action].default_estimator
        assert est.input_kind == "none"
        assert (est.base_low, est.base_high) == (40, 120)


def test_study_plans_are_metered_at_zero_today() -> None:
    est = ACTION_SPECS[MeteredAction.STUDY_PLAN].default_estimator
    assert (est.base_low, est.base_high, est.per_input_high) == (0, 0, 0)


def test_clamp_inputs_bounds_the_hold_not_the_charge() -> None:
    assert clamp_inputs(-3) == 0
    assert clamp_inputs(7) == 7
    assert clamp_inputs(10_000) == MAX_ESTIMATE_INPUTS


def test_job_slack_and_target_shape() -> None:
    assert timedelta(minutes=10) == JOB_SLACK
    assert UsageTarget(subject_code="0580", input_count=3).input_count == 3
