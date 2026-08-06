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

import hashlib
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from lemely.core.history import GRADE_ORDER, is_grade_bearing
from lemely.core.schemas import StrictModel

if TYPE_CHECKING:
    from lemely.core.history import PaperRecord, StudentHistory

# ``GRADE_ORDER`` — the single source of truth for the grade ladder, best to
# worst — lived here until P3.5 chunk G and now lives in ``lemely.core.history``
# beside the ``is_grade_bearing`` predicate that needs it, so that a schema
# module never has to import this rules engine. Every other caller
# (``class_analytics``, ``difficulty``, ``web.routers.teacher``) was moved to
# import it from there too rather than through a re-export shim here: one name,
# one import path, nothing to drift — the D2.2 discipline applied to
# ``REVIEW_CONFIDENCE_THRESHOLD``.

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


def flag_fingerprint(flag: AtRiskFlag) -> str:
    """Deterministic identity for the *evidence* behind a fired flag (D3.5).

    Flags are recomputed on every request (module docstring) rather than
    stored, so an acknowledgement cannot reference a flag id — it must
    reference the evidence that raised the flag instead, and re-fire the
    moment that evidence changes. This is the single function every caller
    (:mod:`lemely.db.at_risk_repo`) uses to decide whether a stored
    acknowledgement still covers the *current* flag, so the two can never
    independently drift on what counts as "the same evidence".

    Deliberately built from only the *stable* part of each evidence type —
    the field(s) that do not change merely because time passed or the
    assessment was recomputed with a later ``now``:

    * ``declining_trend`` -> the three percentages themselves. Any change to
      the window (a new paper landing, or an old one dropping out of it)
      changes at least one percentage, so a genuinely new decline always
      gets a fresh fingerprint.
    * ``below_target`` -> the ``(target_grade, predicted_grade)`` pair, not
      ``positions_below`` (a pure function of the pair, so including it would
      be redundant, not additional information).
    * ``inactive`` -> ``last_active_at`` **only**, never ``days_inactive``.
      ``days_inactive`` is ``(now - last_active).days`` — it increments every
      calendar day the student stays inactive, so fingerprinting on it would
      change the identity of an unresolved flag daily and silently un-
      acknowledge it every 24 hours (exactly the bug D3.5 exists to prevent).
      ``last_active_at`` only changes when the student actually submits a new
      paper, which is the only event that should count as "new evidence".

    Uses :mod:`hashlib` rather than the builtin ``hash()``: CPython salts
    ``str``/``bytes`` hashes per-process (``PYTHONHASHSEED``) for DoS
    hardening, so ``hash()`` of the same string differs across worker
    processes/restarts — useless as a value stored in and compared against a
    database row written by a different process. ``sha256`` of a canonical,
    versioned string is stable across processes, restarts, and Python
    versions by construction.

    Raises:
        TypeError: ``flag.evidence`` is not one of the three known evidence
            types (defensive; the ``AtRiskFlag`` union is exhaustive today).
    """
    evidence = flag.evidence
    if isinstance(evidence, DecliningTrendEvidence):
        stable = "|".join(f"{p:.4f}" for p in evidence.percentages)
    elif isinstance(evidence, BelowTargetEvidence):
        stable = f"{evidence.target_grade}>{evidence.predicted_grade}"
    elif isinstance(evidence, InactivityEvidence):
        stable = evidence.last_active_at
    else:
        raise TypeError(f"Unhandled AtRiskFlag evidence type: {type(evidence)!r}")
    canonical = f"v1:{flag.reason.value}:{stable}"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _check_declining_trend(history: StudentHistory) -> AtRiskFlag | None:
    """Rule 1: last 3 past papers strictly decreasing with a >= 5pp total drop.

    Grade-bearing records only (``docs/quiz-model.md`` §5): a quiz percentage
    is not comparable to a paper percentage, so letting quizzes into this
    window would manufacture and erase "declining" trends out of the ordinary
    interleaving of quizzes and papers rather than measuring anything real.
    """
    records = [r for r in history.records if is_grade_bearing(r)]
    if len(records) < _TREND_WINDOW:
        return None
    window = records[-_TREND_WINDOW:]
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

    Grade-bearing records only (``docs/quiz-model.md`` §5) — a quiz carries no
    grade at all, so it can never be the "latest grade" this rule compares
    against a target.
    """
    records = [r for r in history.records if is_grade_bearing(r)]
    if not records:
        return None
    predicted_grade = records[-1].grade
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
