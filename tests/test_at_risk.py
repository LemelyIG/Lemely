"""Tests for the D3.3 at-risk flagging engine (``lemely.core.at_risk``).

Pure unit tests: no DB, no network, no wall clock — every scenario supplies
its own fixed ``now`` so the rules are deterministic. Scenarios are named
after the acceptance-criteria bullets in the P3.2 brief / BUILD/DECISIONS.md
D3.3, so a failing test names exactly which rule regressed.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from lemely.core.at_risk import (
    AtRiskReason,
    BelowTargetEvidence,
    DecliningTrendEvidence,
    InactivityEvidence,
    TargetRuleStatus,
    assess_at_risk,
    flag_fingerprint,
)
from lemely.core.history import PaperRecord, StudentHistory
from lemely.core.schemas import ExamMetadata

_NOW = datetime(2026, 8, 6, 12, 0, 0, tzinfo=UTC)


def _meta(paper_number: int = 1) -> ExamMetadata:
    return ExamMetadata(
        subject_code="0625",
        paper_number=paper_number,
        paper_variant=1,
        session_month="May/June",
        session_year=2020,
    )


def _record(
    percentage: float,
    *,
    grade: str = "B",
    recorded_at: str | None = None,
) -> PaperRecord:
    return PaperRecord(
        student_id="alice",
        metadata=_meta(),
        awarded_marks=int(percentage * 80 / 100),
        maximum_marks=80,
        percentage=percentage,
        grade=grade,
        weak_areas=[],
        recorded_at=recorded_at if recorded_at is not None else _NOW.isoformat(),
    )


def _history(*records: PaperRecord) -> StudentHistory:
    return StudentHistory(student_id="alice", records=list(records))


# ---------------------------------------------------------------------------
# Rule 1 — declining trend (window N=3, 5pp floor).
# ---------------------------------------------------------------------------


class TestDecliningTrend:
    def test_fires_on_strict_decline_over_floor(self) -> None:
        """72% -> 65% -> 58%: strictly decreasing, 14pp drop >= 5pp floor."""
        history = _history(_record(72.0), _record(65.0), _record(58.0))
        result = assess_at_risk(history, now=_NOW)
        reasons = {f.reason for f in result.flags}
        assert AtRiskReason.DECLINING_TREND in reasons
        flag = next(f for f in result.flags if f.reason == AtRiskReason.DECLINING_TREND)
        assert isinstance(flag.evidence, DecliningTrendEvidence)
        assert flag.evidence.percentages == [72.0, 65.0, 58.0]

    def test_does_not_fire_below_the_5pp_floor(self) -> None:
        """71.2% -> 71.1% -> 71.0%: strictly decreasing but only 0.2pp — the false-alarm floor."""
        history = _history(_record(71.2), _record(71.1), _record(71.0))
        result = assess_at_risk(history, now=_NOW)
        assert AtRiskReason.DECLINING_TREND not in {f.reason for f in result.flags}

    def test_does_not_fire_with_only_two_papers(self) -> None:
        """Two papers is a single delta, not a trend (D3.3): the window needs 3."""
        history = _history(_record(80.0), _record(60.0))
        result = assess_at_risk(history, now=_NOW)
        assert AtRiskReason.DECLINING_TREND not in {f.reason for f in result.flags}

    def test_does_not_fire_on_non_monotonic_trend(self) -> None:
        """Down, up, down is not a strictly decreasing shape."""
        history = _history(_record(70.0), _record(60.0), _record(65.0))
        result = assess_at_risk(history, now=_NOW)
        assert AtRiskReason.DECLINING_TREND not in {f.reason for f in result.flags}

    def test_does_not_fire_while_improving(self) -> None:
        history = _history(_record(50.0), _record(60.0), _record(70.0))
        result = assess_at_risk(history, now=_NOW)
        assert AtRiskReason.DECLINING_TREND not in {f.reason for f in result.flags}

    def test_only_the_last_3_papers_form_the_window(self) -> None:
        """An old decline that has since recovered must not still fire on paper count 4+."""
        history = _history(
            _record(90.0),
            _record(80.0),
            _record(70.0),  # would have fired as a 3-window on its own
            _record(75.0),
            _record(80.0),
            _record(85.0),  # last 3: 75 -> 80 -> 85, improving
        )
        result = assess_at_risk(history, now=_NOW)
        assert AtRiskReason.DECLINING_TREND not in {f.reason for f in result.flags}


# ---------------------------------------------------------------------------
# Rule 2 — predicted >= 2 grades below target (ladder A* A B C D E U).
# ---------------------------------------------------------------------------


class TestBelowTarget:
    def test_fires_two_positions_below(self) -> None:
        """Target A, predicted C: 2 ladder positions below — fires."""
        history = _history(_record(60.0, grade="C"))
        result = assess_at_risk(history, now=_NOW, target_grade="A")
        assert result.target_rule_status == TargetRuleStatus.FIRED
        flag = next(f for f in result.flags if f.reason == AtRiskReason.BELOW_TARGET)
        assert isinstance(flag.evidence, BelowTargetEvidence)
        assert flag.evidence == BelowTargetEvidence(
            target_grade="A", predicted_grade="C", positions_below=2
        )

    def test_does_not_fire_one_position_below(self) -> None:
        """Target A, predicted B: only 1 position below — does not fire."""
        history = _history(_record(70.0, grade="B"))
        result = assess_at_risk(history, now=_NOW, target_grade="A")
        assert result.target_rule_status == TargetRuleStatus.NOT_FIRED
        assert AtRiskReason.BELOW_TARGET not in {f.reason for f in result.flags}

    def test_fires_three_positions_below(self) -> None:
        """Target A, predicted D: 3 positions below — fires."""
        history = _history(_record(40.0, grade="D"))
        result = assess_at_risk(history, now=_NOW, target_grade="A")
        assert result.target_rule_status == TargetRuleStatus.FIRED
        flag = next(f for f in result.flags if f.reason == AtRiskReason.BELOW_TARGET)
        assert isinstance(flag.evidence, BelowTargetEvidence)
        assert flag.evidence.positions_below == 3

    def test_no_target_is_not_evaluable_not_a_pass(self) -> None:
        """No target grade recorded: distinguishable from 'evaluated, did not fire'."""
        history = _history(_record(40.0, grade="D"))
        result = assess_at_risk(history, now=_NOW, target_grade=None)
        status = result.target_rule_status
        assert status != TargetRuleStatus.NOT_FIRED  # not the same as "checked and clean"
        assert status == TargetRuleStatus.NOT_EVALUABLE
        assert AtRiskReason.BELOW_TARGET not in {f.reason for f in result.flags}

    def test_target_with_no_papers_yet_does_not_fire(self) -> None:
        """A target but zero papers: nothing to compare, so the rule cannot fire.

        The rule is still *evaluable* (a target was supplied) — it simply has
        no predicted grade to measure against, so it reports NOT_FIRED rather
        than raising on the empty history.
        """
        result = assess_at_risk(_history(), now=_NOW, target_grade="A")
        assert result.target_rule_status == TargetRuleStatus.NOT_FIRED
        assert result.flags == []

    def test_unrecognised_grade_string_does_not_raise(self) -> None:
        """Bad/foreign grade data must not crash a teacher dashboard.

        Both directions are covered: an off-ladder *predicted* grade and an
        off-ladder *target*. The documented behaviour is "does not fire" — not
        a third state, and not an exception.
        """
        off_ladder_predicted = _history(_record(40.0, grade="Ungraded"))
        result = assess_at_risk(off_ladder_predicted, now=_NOW, target_grade="A")
        assert result.target_rule_status == TargetRuleStatus.NOT_FIRED
        assert AtRiskReason.BELOW_TARGET not in {f.reason for f in result.flags}

        on_ladder = _history(_record(40.0, grade="D"))
        result = assess_at_risk(on_ladder, now=_NOW, target_grade="First Class")
        assert result.target_rule_status == TargetRuleStatus.NOT_FIRED
        assert AtRiskReason.BELOW_TARGET not in {f.reason for f in result.flags}


# ---------------------------------------------------------------------------
# Rule 3 — inactivity (>= 14 days since the last recorded paper).
# ---------------------------------------------------------------------------


class TestInactivity:
    def test_fires_at_exactly_14_days(self) -> None:
        last_active = (_NOW - timedelta(days=14)).isoformat()
        history = _history(_record(90.0, recorded_at=last_active))
        result = assess_at_risk(history, now=_NOW)
        reasons = {f.reason for f in result.flags}
        assert AtRiskReason.INACTIVE in reasons
        flag = next(f for f in result.flags if f.reason == AtRiskReason.INACTIVE)
        assert isinstance(flag.evidence, InactivityEvidence)
        assert flag.evidence.days_inactive == 14

    def test_does_not_fire_at_13_days(self) -> None:
        last_active = (_NOW - timedelta(days=13)).isoformat()
        history = _history(_record(90.0, recorded_at=last_active))
        result = assess_at_risk(history, now=_NOW)
        assert AtRiskReason.INACTIVE not in {f.reason for f in result.flags}

    def test_zero_papers_is_not_flagged_inactive(self) -> None:
        """A student who never started is not one who stopped."""
        history = _history()
        result = assess_at_risk(history, now=_NOW)
        assert result.flags == []
        assert result.is_at_risk is False


# ---------------------------------------------------------------------------
# Unparseable / missing timestamps.
# ---------------------------------------------------------------------------


class TestUnparseableTimestamp:
    def test_garbage_recorded_at_fails_safe_no_crash_no_flag(self) -> None:
        """An unparseable ``recorded_at`` must not crash the dashboard.

        Decision (documented in ``lemely.core.at_risk._parse_recorded_at``):
        treat it as if inactivity is not evaluable and do not fire — a record
        whose timestamp cannot be trusted does not get to assert recency
        either way. This does not affect the other two rules.
        """
        history = _history(_record(90.0, recorded_at="not-a-timestamp"))
        result = assess_at_risk(history, now=_NOW)
        assert AtRiskReason.INACTIVE not in {f.reason for f in result.flags}

    def test_naive_recorded_at_also_fails_safe(self) -> None:
        """A tz-naive timestamp (violates the D1.8 canonical-UTC convention) is also unparseable."""
        history = _history(_record(90.0, recorded_at="2020-01-01T00:00:00"))
        result = assess_at_risk(history, now=_NOW)
        assert AtRiskReason.INACTIVE not in {f.reason for f in result.flags}


# ---------------------------------------------------------------------------
# Combination — OR semantics.
# ---------------------------------------------------------------------------


class TestCombination:
    def test_single_rule_firing_is_sufficient(self) -> None:
        history = _history(_record(72.0), _record(65.0), _record(58.0))
        result = assess_at_risk(history, now=_NOW)
        assert result.is_at_risk is True
        assert len(result.flags) == 1

    def test_multiple_rules_fire_as_multiple_labelled_flags(self) -> None:
        """Declining trend + inactivity + below-target can all fire together (OR, not exclusive)."""
        stale = (_NOW - timedelta(days=30)).isoformat()
        history = _history(
            _record(72.0, grade="B"),
            _record(65.0, grade="C"),
            _record(58.0, grade="D", recorded_at=stale),
        )
        result = assess_at_risk(history, now=_NOW, target_grade="A")
        reasons = {f.reason for f in result.flags}
        assert reasons == {
            AtRiskReason.DECLINING_TREND,
            AtRiskReason.INACTIVE,
            AtRiskReason.BELOW_TARGET,
        }
        assert len(result.flags) == 3

    def test_no_rule_fires_for_a_healthy_student(self) -> None:
        history = _history(_record(85.0, grade="A"), _record(88.0, grade="A"))
        result = assess_at_risk(history, now=_NOW, target_grade="A")
        assert result.flags == []
        assert result.is_at_risk is False


# ---------------------------------------------------------------------------
# flag_fingerprint (D3.5) — evidence-scoped acknowledgement identity.
# ---------------------------------------------------------------------------


class TestFlagFingerprint:
    def test_stable_across_calls(self) -> None:
        """Same flag, called twice (even in a fresh process-like re-derivation),
        yields the same fingerprint — this is what lets a stored ack still
        match on the next request."""
        history = _history(_record(72.0), _record(65.0), _record(58.0))
        flag = assess_at_risk(history, now=_NOW).flags[0]
        assert flag_fingerprint(flag) == flag_fingerprint(flag)
        # And re-deriving from an independently-rebuilt equal flag (not the
        # same Python object) still matches.
        flag_again = assess_at_risk(history, now=_NOW).flags[0]
        assert flag_fingerprint(flag) == flag_fingerprint(flag_again)

    def test_not_python_hash_salted(self) -> None:
        """A regression guard against ever swapping back to builtin ``hash()``:
        the fingerprint must not equal the (per-process-salted) ``hash()`` of
        any obvious representation, and must be a stable hex digest."""
        history = _history(_record(72.0), _record(65.0), _record(58.0))
        flag = assess_at_risk(history, now=_NOW).flags[0]
        fingerprint = flag_fingerprint(flag)
        assert isinstance(fingerprint, str)
        # sha256 hex digest: 64 lowercase hex characters.
        assert len(fingerprint) == 64
        assert all(c in "0123456789abcdef" for c in fingerprint)

    def test_inactivity_fingerprint_unchanged_as_days_inactive_grows(self) -> None:
        """The key regression (D3.5): the same student, assessed a day later,
        has a *larger* ``days_inactive`` but the *same* ``last_active_at`` —
        the fingerprint must not change, or an acknowledged inactivity flag
        would silently re-raise every 24 hours."""
        last_active = (_NOW - timedelta(days=14)).isoformat()
        history = _history(_record(90.0, recorded_at=last_active))

        today = assess_at_risk(history, now=_NOW)
        tomorrow = assess_at_risk(history, now=_NOW + timedelta(days=1))
        later = assess_at_risk(history, now=_NOW + timedelta(days=30))

        today_flag = next(f for f in today.flags if f.reason == AtRiskReason.INACTIVE)
        tomorrow_flag = next(f for f in tomorrow.flags if f.reason == AtRiskReason.INACTIVE)
        later_flag = next(f for f in later.flags if f.reason == AtRiskReason.INACTIVE)

        # Sanity: days_inactive really did grow (evidence differs on the field
        # we deliberately exclude), yet last_active_at stayed put.
        assert isinstance(today_flag.evidence, InactivityEvidence)
        assert isinstance(tomorrow_flag.evidence, InactivityEvidence)
        assert isinstance(later_flag.evidence, InactivityEvidence)
        assert today_flag.evidence.days_inactive < tomorrow_flag.evidence.days_inactive
        assert today_flag.evidence.days_inactive < later_flag.evidence.days_inactive
        assert today_flag.evidence.last_active_at == tomorrow_flag.evidence.last_active_at
        assert today_flag.evidence.last_active_at == later_flag.evidence.last_active_at

        assert flag_fingerprint(today_flag) == flag_fingerprint(tomorrow_flag)
        assert flag_fingerprint(today_flag) == flag_fingerprint(later_flag)

    def test_declining_trend_fingerprint_changes_with_new_evidence(self) -> None:
        """The re-raise regression: a further decline changes the percentage
        window, so the fingerprint of the new flag must differ from the old
        one — an acknowledgement of the old evidence must not cover it."""
        before = _history(_record(72.0), _record(65.0), _record(58.0))
        before_flag = next(
            f
            for f in assess_at_risk(before, now=_NOW).flags
            if f.reason == AtRiskReason.DECLINING_TREND
        )

        # A further-declined paper lands: window shifts to 65 -> 58 -> 50.
        after = _history(_record(72.0), _record(65.0), _record(58.0), _record(50.0))
        after_flag = next(
            f
            for f in assess_at_risk(after, now=_NOW).flags
            if f.reason == AtRiskReason.DECLINING_TREND
        )

        assert flag_fingerprint(before_flag) != flag_fingerprint(after_flag)

    def test_below_target_fingerprint_from_target_predicted_pair(self) -> None:
        """Two flags carrying the same target/predicted pair fingerprint
        identically regardless of any other field; a different pair differs."""
        same_a = assess_at_risk(_history(_record(60.0, grade="C")), now=_NOW, target_grade="A")
        same_b = assess_at_risk(
            _history(_record(60.0, grade="C")), now=_NOW + timedelta(days=5), target_grade="A"
        )
        different = assess_at_risk(_history(_record(40.0, grade="D")), now=_NOW, target_grade="A")

        flag_a = next(f for f in same_a.flags if f.reason == AtRiskReason.BELOW_TARGET)
        flag_b = next(f for f in same_b.flags if f.reason == AtRiskReason.BELOW_TARGET)
        flag_c = next(f for f in different.flags if f.reason == AtRiskReason.BELOW_TARGET)

        assert flag_fingerprint(flag_a) == flag_fingerprint(flag_b)
        assert flag_fingerprint(flag_a) != flag_fingerprint(flag_c)

    def test_different_reasons_never_collide(self) -> None:
        """A declining-trend flag and an inactivity flag on the same history
        must never share a fingerprint — the reason is part of the canonical
        string precisely so acks stay scoped per-reason (the composite key)."""
        stale = (_NOW - timedelta(days=20)).isoformat()
        history = _history(_record(72.0), _record(65.0), _record(58.0, recorded_at=stale))
        result = assess_at_risk(history, now=_NOW)
        reasons = {f.reason for f in result.flags}
        assert reasons == {AtRiskReason.DECLINING_TREND, AtRiskReason.INACTIVE}
        fingerprints = {f.reason: flag_fingerprint(f) for f in result.flags}
        assert fingerprints[AtRiskReason.DECLINING_TREND] != fingerprints[AtRiskReason.INACTIVE]
