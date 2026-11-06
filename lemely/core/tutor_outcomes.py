"""Past-student outcome figures on a tutor profile (ADR-T04; SPEC §e.1; SC-13, SC-14).

Two figures per tutor and subject, both counts only: the **grade distribution**
of past students over the recorded ladder, and the **change** (higher, same or
lower) between each student's grade before and during their time with the tutor.
Grades are private and the tutor is a privileged observer (THREAT-MODEL OS-1 to
OS-5), so most of this module decides when a figure may *not* be shown.

Pure by construction: no ``lemely.db``, ``web``, ``io`` or ``app`` import, no
SQLAlchemy, no FastAPI and no clock of its own (import-linter ``forbidden``
contract, SPEC §e.1). The figures are computed live on every request (decision
row 13: no monthly snapshot). Every instant must be timezone-aware (a naive one
raises :class:`ValueError`), and every window is **elapsed time**: instants are
moved to UTC before a duration is added, so a clock change inside a window
neither lengthens nor shortens it. A SQL mirror must do the same (a UTC session
or an interval in hours, never ``interval '120 days'`` in a Cairo session).

**Definitions** (ADR-T04; ``tutor_directory_repo`` holds the SQL side):

- *Counted session* (:func:`is_counted_session`): accepted at some point, in
  ``accepted``, ``completed`` or ``no_show``, and ended. The tutor's outcome
  marks change nothing (F1): a no-show still counts. SQL mirror:
  ``tutoring_predicates.OUTCOME_MEMBERSHIP_SQL``.
- *S*: the start of the student's first counted session in the subject.
- *Window*: ``[S, S + DURING_WINDOW)``; the member **closes** at
  ``S + DURING_WINDOW`` (:func:`close_instant`). Later sessions never reopen it.
- *Eligible member* (:func:`is_member_eligible`): email verified by S (the
  first verification; a later one does not count), an account at least
  ``MIN_MEMBER_ACCOUNT_AGE`` old at S, not opted out, and never blocked this
  tutor (SC-13e, row 13).
- *Published set* (:func:`published_members`): the closed eligible members in
  ``(close instant, ref)`` order, cut to a whole multiple of k, so the set only
  ever grows k members at a time (SC-13c).
- *Before / during grade*: the latest eligible observation in
  ``[S - BEFORE_LOOKBACK, S)`` / ``[S, S + DURING_WINDOW)``. Observations off
  the ladder are ignored, and on an exact tie of ``recorded_at`` the lower
  grade is kept, so a tie can never raise a reported grade.

**When a figure is shown** (:func:`outcome_for_subject`, each figure on its own
contributors: published members with a during grade for the distribution,
with both grades for the change):

1. ``n >= k`` on contributors, not on the cohort (SC-13a, F8);
2. the contributors who never held a grant to this tutor number 0 or at least k
   (SC-14 i);
3. the largest bucket holds at most ``n - 2`` (SC-14 ii);
4. no student with a counted session in the subject, eligible or not, has a
   recent change (:func:`is_recent_change`: an opt-out change or a block of
   this tutor within ``OPT_CHANGE_HOLD``; SC-13d). This one hides both figures.

Otherwise the figure is insufficient and every count is ``None``, including
``n_without_grade``. The residual differencing leak across a step of k (ADR-T04
R5) is accepted by decision row 13.

**Literals are written out here on purpose.** ``core`` may not import
``lemely.db``; ``tests/test_tutoring_cross_pins.py`` pins the counted-session
states to the migration, the ORM index and the shared predicate, and the
eligible ``origin`` and ``boundary_source`` values to the Python enums.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final, Literal

from lemely.core.history import GRADE_ORDER

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

OUTCOME_K_MIN: Final = 5  # row 8
BEFORE_LOOKBACK: Final = timedelta(days=180)  # O-10
DURING_WINDOW: Final = timedelta(days=120)  # O-10; replaces "E + 60 d" (ADR-T04)
OPT_CHANGE_HOLD: Final = timedelta(days=90)  # SC-13d
MIN_MEMBER_ACCOUNT_AGE: Final = timedelta(days=30)  # SC-13e

FigureState = Literal["insufficient", "sufficient"]

#: ``bookingstate`` values a counted session may be in (ADR-T04, SPEC §a.3).
_COUNTED_STATES: Final = frozenset({"accepted", "completed", "no_show"})
#: ``attempts.origin`` and ``attempts.boundary_source`` of an eligible observation.
_ELIGIBLE_ORIGIN: Final = "past_paper"
_ELIGIBLE_BOUNDARY_SOURCE: Final = "exact"
#: The smallest gap between ``n`` and the largest bucket (SC-14 ii).
_BUCKET_MARGIN: Final = 2


@dataclass(frozen=True, slots=True)
class CohortMember:
    """One student with a counted session with this tutor in this subject."""

    ref: int
    """Opaque, unique within the cohort, stable across requests; never a user id."""
    first_session_start: datetime
    """S: the start of the first counted session in this subject."""
    eligible: bool
    """:func:`is_member_eligible`: verified by S (first verification), account 30 days
    old at S, not opted out, never blocked this tutor."""
    ever_granted: bool
    """Any ``tutor_data_grants`` row for the pair, live or revoked."""
    recent_change: bool
    """:func:`is_recent_change`."""


@dataclass(frozen=True, slots=True)
class AttemptFacts:
    """The ``attempts`` columns :func:`is_outcome_eligible` reads."""

    origin: str
    grade: str | None
    boundary_source: str | None
    subject_code: str | None
    deleted: bool


@dataclass(frozen=True, slots=True)
class GradeObservation:
    """One eligible attempt of a cohort member: its grade and upload instant."""

    ref: int
    grade: str
    recorded_at: datetime


@dataclass(frozen=True, slots=True)
class OutcomeBucket:
    """Students whose during grade is ``grade``."""

    grade: str
    count: int


@dataclass(frozen=True, slots=True)
class OutcomeDistribution:
    """The grade distribution figure (``OutcomeDistributionDTO``).

    ``buckets`` holds every rung of the ladder in ladder order, zero counts
    included, when sufficient, and is empty when insufficient.
    """

    state: FigureState
    k: int
    n_graded: int | None
    n_without_grade: int | None
    buckets: tuple[OutcomeBucket, ...]


@dataclass(frozen=True, slots=True)
class OutcomeChange:
    """The higher / same / lower change figure (``OutcomeChangeDTO``)."""

    state: FigureState
    k: int
    n_paired: int | None
    higher: int | None
    same: int | None
    lower: int | None


@dataclass(frozen=True, slots=True)
class SubjectOutcome:
    """Both figures for one tutor and subject."""

    distribution: OutcomeDistribution
    change: OutcomeChange


# --- input checks ---------------------------------------------------------------------------


def _require_aware(**instants: datetime | None) -> None:
    for name, value in instants.items():
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError(f"{name} must be a timezone-aware datetime, got naive {value!r}")


def _utc(value: datetime) -> datetime:
    return value.astimezone(UTC)


def _ladder_rank(ladder: Sequence[str]) -> Mapping[str, int]:
    """Position of each rung, best first; refuses an empty or repeating ladder."""
    if isinstance(ladder, str) or not ladder:
        raise ValueError(f"ladder must be a non-empty sequence of grades, got {ladder!r}")
    rank = {grade: position for position, grade in enumerate(ladder)}
    if len(rank) != len(ladder):
        raise ValueError(f"ladder repeats a grade: {ladder!r}")
    return rank


def _check_k(k: int) -> None:
    if k < 1:
        raise ValueError(f"k must be at least 1, got {k}")


# --- definitions ----------------------------------------------------------------------------


def is_counted_session(
    *, state: str, accepted_at: datetime | None, ends_at: datetime, now: datetime
) -> bool:
    """Whether a booking makes its student a cohort member (``OUTCOME_MEMBERSHIP_SQL``).

    ``accepted_at`` set, ``state`` in ``accepted``/``completed``/``no_show`` and
    ``ends_at <= now``. Marking the session completed or no-show, a block or a
    dispute leaves the answer unchanged (F1).
    """
    _require_aware(accepted_at=accepted_at, ends_at=ends_at, now=now)
    return accepted_at is not None and state in _COUNTED_STATES and _utc(ends_at) <= _utc(now)


def is_member_eligible(
    *,
    first_session_start: datetime,
    email_verified_at: datetime | None,
    account_created_at: datetime,
    opted_out: bool,
    ever_blocked_tutor: bool,
) -> bool:
    """``CohortMember.eligible``: may this student count in the tutor's figures (SC-13e)?

    The email verified by S (``email_verified_at <= S``, the student's **first**
    verification), an account at least ``MIN_MEMBER_ACCOUNT_AGE`` old at S
    (elapsed time), not opted out, and no block of this tutor ever (removed
    blocks included, row 13). A later verification never makes the student
    eligible: it would let a member with an early close instant join late and
    displace a published member, a one-member swap of the figure (T05 review R1).
    The caller passes the first verification instant; a re-verification must
    not move it.
    """
    _require_aware(
        first_session_start=first_session_start,
        email_verified_at=email_verified_at,
        account_created_at=account_created_at,
    )
    start = _utc(first_session_start)
    verified_by_start = email_verified_at is not None and _utc(email_verified_at) <= start
    old_enough = start - _utc(account_created_at) >= MIN_MEMBER_ACCOUNT_AGE
    return verified_by_start and old_enough and not opted_out and not ever_blocked_tutor


def is_recent_change(
    *, now: datetime, outcome_pref_changed_at: datetime | None, block_created_at: datetime | None
) -> bool:
    """``CohortMember.recent_change``: a counting change inside the 90-day hold (SC-13d).

    True while ``now < changed + OPT_CHANGE_HOLD`` for the student's last
    opt-out change (either direction) or their first block of this tutor. A
    change dated after ``now`` also holds.
    """
    _require_aware(
        now=now, outcome_pref_changed_at=outcome_pref_changed_at, block_created_at=block_created_at
    )
    return any(
        changed is not None and _utc(now) < _utc(changed) + OPT_CHANGE_HOLD
        for changed in (outcome_pref_changed_at, block_created_at)
    )


def is_outcome_eligible(a: AttemptFacts, *, subject_code: str, ladder: Sequence[str]) -> bool:
    """Whether an attempt may feed a figure (F9, F10; SQL mirror in ``tutor_directory_repo``).

    A past paper, graded on the ladder, against an exact boundary, in the
    figure's subject, not deleted. Estimated-boundary grades are left out.
    """
    rank = _ladder_rank(ladder)
    return (
        a.origin == _ELIGIBLE_ORIGIN
        and a.grade is not None
        and a.grade in rank
        and a.boundary_source == _ELIGIBLE_BOUNDARY_SOURCE
        and a.subject_code == subject_code
        and not a.deleted
    )


def _session_start(m: CohortMember) -> datetime:
    """S in UTC, so every window built on it is elapsed time."""
    _require_aware(first_session_start=m.first_session_start)
    return _utc(m.first_session_start)


def close_instant(m: CohortMember) -> datetime:
    """When the member's window closes and they may enter the published set: ``S + 120 days``."""
    return _session_start(m) + DURING_WINDOW


def published_members(
    members: Iterable[CohortMember], *, now: datetime, k: int
) -> list[CohortMember]:
    """The members a figure may draw on: closed, eligible, the first ``floor(n / k) * k``.

    Ordered by ``(close_instant, ref)``, so the set changes only when the k-th
    further member closes (SC-13c).
    """
    _require_aware(now=now)
    _check_k(k)
    closed = sorted(
        (m for m in members if m.eligible and _utc(now) >= close_instant(m)),
        key=lambda m: (close_instant(m), m.ref),
    )
    return closed[: len(closed) // k * k]


def _latest_in(
    m: CohortMember,
    obs: Sequence[GradeObservation],
    rank: Mapping[str, int],
    lower: datetime,
    upper: datetime,
) -> str | None:
    """The member's latest on-ladder grade recorded in ``[lower, upper)``; ties keep the lower.

    ``lower`` and ``upper`` are UTC; every ``recorded_at`` is moved to UTC before
    it is compared, because two instants sharing a zone compare by wall time.
    """
    best: tuple[datetime, int, str] | None = None
    for observation in obs:
        _require_aware(recorded_at=observation.recorded_at)
        if observation.ref != m.ref or observation.grade not in rank:
            continue
        candidate = (_utc(observation.recorded_at), rank[observation.grade], observation.grade)
        if lower <= candidate[0] < upper and (best is None or candidate[:2] > best[:2]):
            best = candidate
    return None if best is None else best[2]


def before_grade(
    m: CohortMember, obs: Sequence[GradeObservation], ladder: Sequence[str]
) -> str | None:
    """The member's latest grade in ``[S - BEFORE_LOOKBACK, S)``, or ``None``."""
    start = _session_start(m)
    return _latest_in(m, obs, _ladder_rank(ladder), start - BEFORE_LOOKBACK, start)


def during_grade(
    m: CohortMember, obs: Sequence[GradeObservation], ladder: Sequence[str]
) -> str | None:
    """The member's latest grade in ``[S, S + DURING_WINDOW)``, or ``None``."""
    start = _session_start(m)
    return _latest_in(m, obs, _ladder_rank(ladder), start, start + DURING_WINDOW)


# --- figures --------------------------------------------------------------------------------


def _shown(*, n: int, never_granted: int, largest: int, k: int) -> bool:
    """SC-13a and SC-14: k contributors, never-granted 0 or >= k, largest bucket <= n - 2."""
    return n >= k and (never_granted == 0 or never_granted >= k) and largest <= n - _BUCKET_MARGIN


def _insufficient(k: int) -> SubjectOutcome:
    return SubjectOutcome(
        distribution=OutcomeDistribution(
            state="insufficient", k=k, n_graded=None, n_without_grade=None, buckets=()
        ),
        change=OutcomeChange(
            state="insufficient", k=k, n_paired=None, higher=None, same=None, lower=None
        ),
    )


def outcome_for_subject(
    members: Sequence[CohortMember],
    obs: Sequence[GradeObservation],
    *,
    now: datetime,
    ladder: Sequence[str] = GRADE_ORDER,
    k: int = OUTCOME_K_MIN,
) -> SubjectOutcome:
    """Both figures for one tutor and subject at ``now`` (rules in the module docstring).

    ``members`` is every student with a counted session in the subject,
    eligible or not (an ineligible member's recent change still hides the
    figures); ``obs`` their eligible observations. Raises :class:`ValueError`
    for a naive instant, a repeated ``ref``, an empty or repeating ladder, or
    ``k < 1``.
    """
    _require_aware(now=now)
    _check_k(k)
    rank = _ladder_rank(ladder)
    refs = [m.ref for m in members]
    if len(set(refs)) != len(refs):
        raise ValueError("cohort refs must be unique")
    for m in members:  # every member, eligible or not, before the hold can return early
        _require_aware(first_session_start=m.first_session_start)
    for observation in obs:
        _require_aware(recorded_at=observation.recorded_at)
    if any(m.recent_change for m in members):
        return _insufficient(k)

    published = published_members(members, now=now, k=k)
    own: dict[int, list[GradeObservation]] = {m.ref: [] for m in published}
    for observation in obs:
        if observation.ref in own:
            own[observation.ref].append(observation)

    counts = dict.fromkeys(ladder, 0)
    graded_never_granted = 0
    higher = same = lower = paired_never_granted = 0
    for m in published:
        during = during_grade(m, own[m.ref], ladder)
        if during is None:
            continue
        counts[during] += 1
        graded_never_granted += not m.ever_granted
        before = before_grade(m, own[m.ref], ladder)
        if before is None:
            continue
        paired_never_granted += not m.ever_granted
        if rank[during] < rank[before]:
            higher += 1
        elif rank[during] == rank[before]:
            same += 1
        else:
            lower += 1

    insufficient = _insufficient(k)
    n_graded = sum(counts.values())
    distribution = insufficient.distribution
    if _shown(n=n_graded, never_granted=graded_never_granted, largest=max(counts.values()), k=k):
        distribution = OutcomeDistribution(
            state="sufficient",
            k=k,
            n_graded=n_graded,
            n_without_grade=len(published) - n_graded,
            buckets=tuple(OutcomeBucket(grade=grade, count=counts[grade]) for grade in ladder),
        )
    n_paired = higher + same + lower
    change = insufficient.change
    if _shown(
        n=n_paired, never_granted=paired_never_granted, largest=max(higher, same, lower), k=k
    ):
        change = OutcomeChange(
            state="sufficient", k=k, n_paired=n_paired, higher=higher, same=same, lower=lower
        )
    return SubjectOutcome(distribution=distribution, change=change)
