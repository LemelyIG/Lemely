"""At-risk flagging rules (D3.3) — pure, no I/O, no DB, no clock of its own.

Three independent rules, combined with **OR** (MISSION §4):

1. **Declining trend** — the last 3 papers are strictly decreasing *and* the
   total drop across the window is >= 5 percentage points. The floor exists so
   a meaningless monotonic dribble (71.2% -> 71.1% -> 71.0%) does not fire —
   see D3.3 for the full rationale.
2. **Predicted >= 2 grades below target** — the student's latest recorded
   grade sits 2+ positions below their target grade on :data:`GRADE_ORDER`.
   There is no target-grade column anywhere in the schema yet (that is
   Phase 4's onboarding questionnaire, D3.3), so ``target_grade`` is an
   injected parameter the caller may not have. When it is absent this rule is
   **not evaluable** — a state kept structurally distinct from "evaluated and
   did not fire" so a missing target can never masquerade as a passing check.
3. **Inactivity** — >= 14 days since the most recent ``recorded_at``. A
   student with zero papers has not started, not stopped, so is never flagged
   inactive (that would flag every new enrolment on day 15).

Every flag carries its reason and structured evidence so the UI can render
the signal itself rather than an unexplained badge (spec §1.4).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from lemely.core.schemas import StrictModel

if TYPE_CHECKING:
    from lemely.core.history import PaperRecord, StudentHistory

# The single source of truth for the grade ladder, best to worst. Aliased (not
# re-literalised) by ``lemely.web.routers.teacher._GRADE_ORDER`` — same
# anti-drift discipline D2.2 applied to ``REVIEW_CONFIDENCE_THRESHOLD``.
GRADE_ORDER = ["A*", "A", "B", "C", "D", "E", "U"]

# Rule 1 — declining trend.
_TREND_WINDOW = 3
_TREND_FLOOR_PP = 5.0

# Rule 2 — predicted grade vs. target, measured in ladder positions.
_TARGET_GAP_POSITIONS = 2

# Rule 3 — inactivity.
_INACTIVITY_DAYS = 14


class AtRiskReason(StrEnum):
    """Machine-readable id for which rule fired."""

    DECLINING_TREND = "declining_trend"
    BELOW_TARGET = "below_target"
    INACTIVE = "inactive"


class TargetRuleStatus(StrEnum):
    """Tri-state outcome of rule 2, kept distinct from a plain bool.

    ``NOT_EVALUABLE`` (no target recorded) must never collapse into
    ``NOT_FIRED`` (a target was recorded and checked, and it was fine) — that
    collapse is exactly the "missing target reads as a passing check" failure
    D3.3 calls out.
    """

    NOT_EVALUABLE = "not_evaluable"
    FIRED = "fired"
    NOT_FIRED = "not_fired"


class DecliningTrendEvidence(StrictModel):
    """The three percentages behind a fired declining-trend flag, oldest first."""

    percentages: list[float]


class BelowTargetEvidence(StrictModel):
    """The target/predicted grades and the ladder gap between them."""

    target_grade: str
    predicted_grade: str
    positions_below: int


class InactivityEvidence(StrictModel):
    """Days since the last recorded paper, and that paper's timestamp."""

    days_inactive: int
    last_active_at: str


class AtRiskFlag(StrictModel):
    """One fired rule: its reason, a rendered summary, and structured evidence."""

    reason: AtRiskReason
    summary: str
    evidence: DecliningTrendEvidence | BelowTargetEvidence | InactivityEvidence


class AtRiskAssessment(StrictModel):
    """The full result of running all three rules over one student's history."""

    student_id: str
    flags: list[AtRiskFlag]
    target_rule_status: TargetRuleStatus

    @property
    def is_at_risk(self) -> bool:
        """True iff at least one rule fired (the OR across all three)."""
        return bool(self.flags)


def assess_at_risk(
    history: StudentHistory,
    *,
    now: datetime,
    target_grade: str | None = None,
) -> AtRiskAssessment:
    """Run the three D3.3 rules over ``history`` and return every flag that fires.

    Args:
        history: the student's recorded paper history.
        now: the caller-injected clock (this module never calls ``datetime.now()``
            itself). Must be timezone-aware — ``recorded_at`` values are always
            UTC ISO strings (D1.8), so a naive ``now`` would raise on subtraction.
        target_grade: the student's target grade, on :data:`GRADE_ORDER`. ``None``
            when no target has been recorded (the only case in Phase 3 — see
            module docstring), which makes rule 2 not evaluable rather than
            silently "not fired".

    Returns:
        An :class:`AtRiskAssessment` whose ``flags`` list is the OR of whichever
        rules fired, plus the separate tri-state ``target_rule_status`` so a
        caller can always tell "no target" apart from "target checked, clean".
    """
    flags: list[AtRiskFlag] = []

    trend_flag = _check_declining_trend(history)
    if trend_flag is not None:
        flags.append(trend_flag)

    target_status = TargetRuleStatus.NOT_EVALUABLE
    if target_grade is not None:
        target_flag = _check_below_target(history, target_grade)
        target_status = (
            TargetRuleStatus.FIRED if target_flag is not None else TargetRuleStatus.NOT_FIRED
        )
        if target_flag is not None:
            flags.append(target_flag)

    inactivity_flag = _check_inactivity(history, now)
    if inactivity_flag is not None:
        flags.append(inactivity_flag)

    return AtRiskAssessment(
        student_id=history.student_id,
        flags=flags,
        target_rule_status=target_status,
    )


def _check_declining_trend(history: StudentHistory) -> AtRiskFlag | None:
    """Rule 1: last 3 papers strictly decreasing with a >= 5pp total drop."""
    if len(history.records) < _TREND_WINDOW:
        return None
    window = history.records[-_TREND_WINDOW:]
    percentages = [r.percentage for r in window]
    strictly_decreasing = all(
        percentages[i] > percentages[i + 1] for i in range(len(percentages) - 1)
    )
    if not strictly_decreasing:
        return None
    total_drop = percentages[0] - percentages[-1]
    if total_drop < _TREND_FLOOR_PP:
        return None
    trail = " -> ".join(f"{p:.0f}%" for p in percentages)
    summary = f"Declining over the last {_TREND_WINDOW} papers: {trail} ({total_drop:.0f}pp drop)."
    return AtRiskFlag(
        reason=AtRiskReason.DECLINING_TREND,
        summary=summary,
        evidence=DecliningTrendEvidence(percentages=percentages),
    )


def _check_below_target(history: StudentHistory, target_grade: str) -> AtRiskFlag | None:
    """Rule 2: latest recorded grade is >= 2 ladder positions below target.

    ``target_grade`` being present is handled by the caller (that is what makes
    this rule evaluable at all). If either grade string is not on
    :data:`GRADE_ORDER` (bad/foreign data), the rule defensively does not fire
    rather than raising — a malformed grade string should not crash the
    dashboard, and D3.3 only defines "not evaluable" for the missing-target
    case, so an unrecognised grade is treated as "not fired", not a third state.
    """
    if not history.records:
        return None
    predicted_grade = history.records[-1].grade
    if target_grade not in GRADE_ORDER or predicted_grade not in GRADE_ORDER:
        return None
    positions_below = GRADE_ORDER.index(predicted_grade) - GRADE_ORDER.index(target_grade)
    if positions_below < _TARGET_GAP_POSITIONS:
        return None
    summary = (
        f"Predicted grade {predicted_grade} is {positions_below} grades below target "
        f"{target_grade}."
    )
    return AtRiskFlag(
        reason=AtRiskReason.BELOW_TARGET,
        summary=summary,
        evidence=BelowTargetEvidence(
            target_grade=target_grade,
            predicted_grade=predicted_grade,
            positions_below=positions_below,
        ),
    )


def _check_inactivity(history: StudentHistory, now: datetime) -> AtRiskFlag | None:
    """Rule 3: >= 14 days since the most recent paper. Zero papers never fires."""
    if not history.records:
        return None
    last_record: PaperRecord = history.records[-1]
    last_active = _parse_recorded_at(last_record.recorded_at)
    if last_active is None:
        # Unparseable/naive timestamp: fail safe rather than crash the
        # dashboard or guess. Documented judgment call (D3.3 leaves the exact
        # handling to the implementer) — a record whose timestamp cannot be
        # trusted does not get to assert anything about recency either way.
        return None
    days_inactive = (now - last_active).days
    if days_inactive < _INACTIVITY_DAYS:
        return None
    last_active_date = last_active.date().isoformat()
    summary = f"No papers submitted in {days_inactive} days (last active {last_active_date})."
    return AtRiskFlag(
        reason=AtRiskReason.INACTIVE,
        summary=summary,
        evidence=InactivityEvidence(
            days_inactive=days_inactive,
            last_active_at=last_record.recorded_at,
        ),
    )


def _parse_recorded_at(value: str) -> datetime | None:
    """Defensively parse a ``PaperRecord.recorded_at`` ISO string.

    Canonical strings (``now_iso()``, D1.8) round-trip exactly via
    ``datetime.fromisoformat``. Anything that fails to parse, or parses to a
    naive datetime (no tz, so not comparable to the tz-aware injected ``now``),
    is treated as unparseable — see :func:`_check_inactivity`.
    """
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed
