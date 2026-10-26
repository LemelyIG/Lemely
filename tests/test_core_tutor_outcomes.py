"""Past-student outcome figures (SPEC §e.1, §e.4 "Outcomes"; ADR-T04; SC-13, SC-14; PLAN T05).

Constants, signatures, dataclass fields, the counted-session states and the
attempt-eligibility literals are parsed from ``docs/tutoring/SPEC.md``. Every
figure test builds a cohort whose counts are worked out by hand in the test,
never by calling the module (PLAN §0.8, "no self-comparison").
"""

from __future__ import annotations

import inspect
import itertools
import re
from collections.abc import Sequence
from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from lemely.core import history, tutor_outcomes
from lemely.core.history import GRADE_ORDER
from lemely.core.tutor_outcomes import (
    BEFORE_LOOKBACK,
    DURING_WINDOW,
    MIN_MEMBER_ACCOUNT_AGE,
    OPT_CHANGE_HOLD,
    OUTCOME_K_MIN,
    AttemptFacts,
    CohortMember,
    GradeObservation,
    OutcomeBucket,
    SubjectOutcome,
    before_grade,
    close_instant,
    during_grade,
    is_counted_session,
    is_member_eligible,
    is_outcome_eligible,
    is_recent_change,
    outcome_for_subject,
    published_members,
)

ROOT = Path(__file__).resolve().parents[1]
SPEC_TEXT = (ROOT / "docs" / "tutoring" / "SPEC.md").read_text(encoding="utf-8")


def _between(start_marker: str, end_marker: str) -> str:
    start = SPEC_TEXT.index(start_marker)
    return SPEC_TEXT[start : SPEC_TEXT.index(end_marker, start)]


_E1_OUTCOMES = _between("# lemely/core/tutor_outcomes.py", "# lemely/core/contact_patterns.py")


def _spec_enum(pg_type: str) -> tuple[str, ...]:
    for line in _between("### a.1 Enum types", "**Additive values").splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if cells[0] == f"`{pg_type}`":
            return tuple(re.findall(r"`(\w+)`", cells[1]))
    raise AssertionError(f"SPEC §a.1 has no {pg_type} row")


def _spec_counted_states() -> frozenset[str]:
    """``state IN (...)`` of the §a.3 outcome-membership predicate."""
    sentence = re.search(
        r"Membership of a tutor's outcome cohort is decided by `([^`]*)`", SPEC_TEXT
    )
    assert sentence
    listed = re.search(r"state IN \(([^)]*)\)", sentence.group(1))
    assert listed
    return frozenset(item.strip().strip("'") for item in listed.group(1).split(","))


def _spec_eligibility_literals() -> tuple[str, str]:
    match = re.search(
        r'origin == "(\w+)", grade on the ladder, boundary_source == "(\w+)", same subject, '
        r"not deleted",
        _E1_OUTCOMES,
    )
    assert match, "SPEC §e.1 is_outcome_eligible comment not found"
    return match.group(1), match.group(2)


BOOKING_STATES = _spec_enum("bookingstate")
COUNTED_STATES = _spec_counted_states()
ELIGIBLE_ORIGIN, ELIGIBLE_BOUNDARY = _spec_eligibility_literals()

K = OUTCOME_K_MIN
SECOND = timedelta(seconds=1)
DAY = timedelta(days=1)
S0 = datetime(2026, 1, 5, 15, 0, tzinfo=UTC)
# Members start one day apart from S0; at NOW the first 30 of them are closed.
NOW = S0 + DURING_WINDOW + timedelta(days=30)
BEFORE_AT = timedelta(days=10)  # a before grade 10 days before S
DURING_AT = timedelta(days=10)  # a during grade 10 days after S


def _member(
    ref: int,
    *,
    start: datetime = S0,
    eligible: bool = True,
    granted: bool = True,
    recent: bool = False,
) -> CohortMember:
    return CohortMember(
        ref=ref,
        first_session_start=start,
        eligible=eligible,
        ever_granted=granted,
        recent_change=recent,
    )


Row = tuple[str | None, str | None, bool]  # (before grade, during grade, ever granted)


def _cohort(
    rows: Sequence[Row], *, first_ref: int = 1, start: datetime = S0
) -> tuple[list[CohortMember], list[GradeObservation]]:
    """One eligible member per row, ``S = start + i days``, each with its own observations."""
    members: list[CohortMember] = []
    observations: list[GradeObservation] = []
    for index, (before, during, granted) in enumerate(rows):
        ref = first_ref + index
        first_start = start + index * DAY
        members.append(_member(ref, start=first_start, granted=granted))
        if before is not None:
            observations.append(GradeObservation(ref, before, first_start - BEFORE_AT))
        if during is not None:
            observations.append(GradeObservation(ref, during, first_start + DURING_AT))
    return members, observations


# Five granted members: distribution A, A, B, C, D (largest bucket 2); change from
# B: higher 2 (A, A), same 1 (B), lower 2 (C, D).
BASE: list[Row] = [("B", g, True) for g in ("A", "A", "B", "C", "D")]


def _assert_insufficient(outcome: SubjectOutcome, *, k: int = K) -> None:
    distribution, change = outcome.distribution, outcome.change
    assert distribution.state == "insufficient"
    assert distribution.k == k
    assert distribution.n_graded is None
    assert distribution.n_without_grade is None
    assert distribution.buckets == ()
    assert change.state == "insufficient"
    assert change.k == k
    assert (change.n_paired, change.higher, change.same, change.lower) == (None, None, None, None)


def _counts(outcome: SubjectOutcome) -> dict[str, int]:
    return {bucket.grade: bucket.count for bucket in outcome.distribution.buckets}


# --- the module matches SPEC §e.1 -----------------------------------------------------------


def _spec_value(text: str) -> object:
    if match := re.fullmatch(r"timedelta\((\w+)=(\d+)\)", text):
        return timedelta(**{match.group(1): int(match.group(2))})
    if re.fullmatch(r"\d+", text):
        return int(text)
    raise AssertionError(f"unparsed SPEC constant {text!r}")


def test_constants_match_spec_e1() -> None:
    constants = {}
    for line in _E1_OUTCOMES.splitlines():
        if match := re.match(r"^([A-Z_]+): Final\S* = (.+)$", line):
            constants[match.group(1)] = _spec_value(match.group(2).split("#")[0].strip())
    assert len(constants) == 5
    for name, value in constants.items():
        assert getattr(tutor_outcomes, name) == value, name


def _split_top_level(text: str) -> list[str]:
    parts, current, depth = [], [], 0
    for char in text:
        depth += {"(": 1, "[": 1, ")": -1, "]": -1}.get(char, 0)
        if char == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
    parts.append("".join(current))
    return [part.strip() for part in parts if part.strip()]


# Names a SPEC default may use, resolved to the objects they denote.
_SPEC_DEFAULTS: dict[str, object] = {
    "GRADE_ORDER": history.GRADE_ORDER,
    "OUTCOME_K_MIN": OUTCOME_K_MIN,
}


def test_public_signatures_match_spec_e1() -> None:
    spec = {
        match.group(1): (match.group(2), match.group(3).strip())
        for match in re.finditer(r"^def (\w+)\((.*?)\) -> ([^#\n]+)", _E1_OUTCOMES, re.M)
    }
    assert len(spec) == 6
    for name, (params, returns) in spec.items():
        signature = inspect.signature(getattr(tutor_outcomes, name))
        expected, keyword_only = [], False
        for part in _split_top_level(params):
            if part == "*":
                keyword_only = True
                continue
            parameter_name = re.match(r"\w+", part)
            assert parameter_name
            default = part.split("=", 1)[1].strip() if "=" in part else None
            expected.append((parameter_name.group(0), keyword_only, default))
        got = [
            (parameter.name, parameter.kind is inspect.Parameter.KEYWORD_ONLY, parameter.default)
            for parameter in signature.parameters.values()
        ]
        assert [(n, kw) for n, kw, _ in got] == [(n, kw) for n, kw, _ in expected], name
        for (_, _, default), (parameter, _, spec_default) in zip(got, expected, strict=True):
            if spec_default is None:
                assert default is inspect.Parameter.empty, (name, parameter)
            else:
                assert default is _SPEC_DEFAULTS[spec_default], (name, parameter)
        assert signature.return_annotation == returns, name


def _e1_dataclass_fields(name: str) -> list[str]:
    match = re.search(
        rf"^class {name}:(.*?)(?=^@dataclass|^def |^class )", _E1_OUTCOMES, re.M | re.S
    )
    assert match, name
    body = "\n".join(line.split("#")[0] for line in match.group(1).splitlines())
    return re.findall(r"(\w+): ", body)


@pytest.mark.parametrize("cls", [CohortMember, AttemptFacts, GradeObservation])
def test_dataclasses_match_spec_e1(cls: type) -> None:
    expected = _e1_dataclass_fields(cls.__name__)
    assert expected
    assert [field.name for field in fields(cls)] == expected
    assert cls.__dataclass_params__.frozen  # type: ignore[attr-defined]
    assert "__slots__" in vars(cls)


# --- k, contributors and the published set (SC-13a, SC-13b, SC-13c) -------------------------


def test_outcomes_k_counts_n_graded_not_cohort() -> None:
    # F8: a published set of k with only k-1 graded members is insufficient.
    rows: list[Row] = [("B", g, True) for g in ("A", "B", "C", "D")] + [(None, None, True)]
    members, observations = _cohort(rows)
    assert len(published_members(members, now=NOW, k=K)) == K
    _assert_insufficient(outcome_for_subject(members, observations, now=NOW))

    # The k-th graded member makes the distribution sufficient...
    members, observations = _cohort([("B", g, True) for g in ("A", "B", "C", "D", "E")])
    outcome = outcome_for_subject(members, observations, now=NOW)
    assert outcome.distribution.state == "sufficient"
    assert (outcome.distribution.n_graded, outcome.distribution.n_without_grade) == (5, 0)
    assert outcome.change.state == "sufficient"
    assert (outcome.change.n_paired, outcome.change.higher, outcome.change.same) == (5, 1, 1)
    assert outcome.change.lower == 3

    # ...and k on n_paired: one missing before grade leaves k-1 pairs.
    rows = [("B", g, True) for g in ("A", "B", "C", "D")] + [(None, "E", True)]
    members, observations = _cohort(rows)
    outcome = outcome_for_subject(members, observations, now=NOW)
    assert outcome.distribution.state == "sufficient"
    assert outcome.distribution.n_graded == 5
    assert outcome.change.state == "insufficient"
    assert outcome.change.n_paired is None


def test_outcomes_insufficient_hides_n_without_grade() -> None:
    rows: list[Row] = [("B", g, True) for g in ("A", "B", "C", "D")] + [(None, None, True)]
    members, observations = _cohort(rows)
    _assert_insufficient(outcome_for_subject(members, observations, now=NOW))

    # Sufficient: ten published, five graded, five without a grade.
    rows = [("B", g, True) for g in ("A", "A", "B", "C", "D")] + [(None, None, True)] * 5
    members, observations = _cohort(rows)
    outcome = outcome_for_subject(members, observations, now=NOW)
    assert outcome.distribution.state == "sufficient"
    assert (outcome.distribution.n_graded, outcome.distribution.n_without_grade) == (5, 5)


def test_outcomes_member_counts_only_after_window_closed() -> None:
    members, observations = _cohort(BASE)
    last_close = members[-1].first_session_start + DURING_WINDOW
    assert close_instant(members[-1]) == last_close
    before = last_close - SECOND
    assert len(published_members(members, now=before, k=K)) == 0
    _assert_insufficient(outcome_for_subject(members, observations, now=before))
    assert len(published_members(members, now=last_close, k=K)) == K
    assert outcome_for_subject(members, observations, now=last_close).distribution.state == (
        "sufficient"
    )


@pytest.mark.parametrize(
    ("offset", "window"),
    [
        (-BEFORE_LOOKBACK - SECOND, None),
        (-BEFORE_LOOKBACK, "before"),
        (-SECOND, "before"),
        (timedelta(0), "during"),
        (DURING_WINDOW - SECOND, "during"),
        (DURING_WINDOW, None),
    ],
    ids=["S-180d-1s", "S-180d", "S-1s", "S", "S+120d-1s", "S+120d"],
)
def test_outcomes_window_edges(offset: timedelta, window: str | None) -> None:
    member = _member(1)
    observations = [GradeObservation(1, "B", S0 + offset)]
    assert before_grade(member, observations, GRADE_ORDER) == ("B" if window == "before" else None)
    assert during_grade(member, observations, GRADE_ORDER) == ("B" if window == "during" else None)


def test_window_grade_is_the_latest_and_ignores_other_refs() -> None:
    member = _member(1)
    observations = [
        GradeObservation(1, "C", S0 + DAY),
        GradeObservation(1, "A", S0 + 3 * DAY),
        GradeObservation(1, "U", S0 + 2 * DAY),
        GradeObservation(2, "E", S0 + 4 * DAY),
        GradeObservation(1, "D", S0 - 3 * DAY),
        GradeObservation(1, "B", S0 - 2 * DAY),
    ]
    assert during_grade(member, observations, GRADE_ORDER) == "A"
    assert before_grade(member, observations, GRADE_ORDER) == "B"


def test_tie_on_recorded_at_keeps_the_lower_grade() -> None:
    member = _member(1)
    at = S0 + DAY
    for observations in (
        [GradeObservation(1, "A", at), GradeObservation(1, "C", at)],
        [GradeObservation(1, "C", at), GradeObservation(1, "A", at)],
    ):
        assert during_grade(member, observations, GRADE_ORDER) == "C"


def test_outcomes_published_set_moves_in_steps_of_k() -> None:
    members = [_member(ref, start=S0 + ref * DAY) for ref in range(12)]
    order = [m.ref for m in sorted(members, key=lambda m: (close_instant(m), m.ref))]
    sizes = []
    for member in members:
        for now in (close_instant(member) - SECOND, close_instant(member)):
            closed = sum(close_instant(m) <= now for m in members)
            published = published_members(members, now=now, k=K)
            assert len(published) == closed // K * K
            assert [m.ref for m in published] == order[: len(published)]
            sizes.append(len(published))
    assert sizes == sorted(sizes)
    assert set(sizes) == {0, 5, 10}
    assert all(later - earlier in (0, K) for earlier, later in itertools.pairwise(sizes))

    # Ties on the close instant break on the opaque ref.
    tied = [_member(ref, start=S0 + ref * DAY) for ref in range(4)]
    tied += [_member(9, start=S0 + 5 * DAY), _member(7, start=S0 + 5 * DAY)]
    published = published_members(tied, now=NOW, k=K)
    assert [m.ref for m in published] == [0, 1, 2, 3, 7]

    # k is an argument: with 3 the set moves in steps of 3.
    assert len(published_members(members[:8], now=NOW, k=3)) == 6


def test_outcomes_single_completion_causes_no_visible_change() -> None:
    members, observations = _cohort(BASE)
    base = outcome_for_subject(members, observations, now=NOW)
    assert base.distribution.state == "sufficient"

    # A sixth member closes: the published set stays the first five (steps of k).
    more_members, more_obs = _cohort([("D", "U", False)], first_ref=6, start=S0 + 6 * DAY)
    assert outcome_for_subject(members + more_members, observations + more_obs, now=NOW) == base

    # A member whose window is still open, already holding a during grade.
    open_start = NOW - DAY * 20
    open_members, open_obs = _cohort([("D", "U", False)], first_ref=7, start=open_start)
    assert outcome_for_subject(members + open_members, observations + open_obs, now=NOW) == base

    # An ineligible member who closed before everyone else.
    early = [_member(8, start=S0 - 3 * DAY, eligible=False, granted=False)]
    early_obs = [GradeObservation(8, "U", S0 - 3 * DAY + DURING_AT)]
    assert outcome_for_subject(members + early, observations + early_obs, now=NOW) == base


# --- holds, eligibility and counted sessions (SC-13d, SC-13e, F1) ----------------------------


def test_outcomes_opt_out_hold_90_days() -> None:
    held = NOW - OPT_CHANGE_HOLD + SECOND
    over = NOW - OPT_CHANGE_HOLD
    for field in ("outcome_pref_changed_at", "block_created_at"):
        others = {"outcome_pref_changed_at": None, "block_created_at": None}
        assert is_recent_change(now=NOW, **{**others, field: held})
        assert not is_recent_change(now=NOW, **{**others, field: over})
        assert is_recent_change(now=NOW, **{**others, field: NOW + DAY})  # clock skew holds too
    assert not is_recent_change(now=NOW, outcome_pref_changed_at=None, block_created_at=None)

    members, observations = _cohort(BASE)
    base = outcome_for_subject(members, observations, now=NOW)
    assert base.distribution.state == "sufficient"
    # A sixth student opted out 90 days minus a second ago: removed from the set
    # on this read, and both figures stay hidden until the hold ends.
    for changed_at, hidden in ((held, True), (over, False)):
        opted_out = _member(
            6,
            start=S0 - DAY,
            eligible=False,
            recent=is_recent_change(
                now=NOW, outcome_pref_changed_at=changed_at, block_created_at=None
            ),
        )
        opted_obs = [GradeObservation(6, "U", S0 - DAY + DURING_AT)]
        outcome = outcome_for_subject([*members, opted_out], observations + opted_obs, now=NOW)
        if hidden:
            _assert_insufficient(outcome)
        else:
            assert outcome == base


def test_outcomes_member_requires_verified_and_30_day_account() -> None:
    start = S0
    ages = (MIN_MEMBER_ACCOUNT_AGE - SECOND, MIN_MEMBER_ACCOUNT_AGE, MIN_MEMBER_ACCOUNT_AGE + DAY)
    rows = list(itertools.product((False, True), ages, (False, True), (False, True)))
    assert len(rows) == 24
    eligible_rows = 0
    for verified, age, opted_out, blocked in rows:
        expected = verified and age >= MIN_MEMBER_ACCOUNT_AGE and not opted_out and not blocked
        got = is_member_eligible(
            first_session_start=start,
            email_verified=verified,
            account_created_at=start - age,
            opted_out=opted_out,
            ever_blocked_tutor=blocked,
        )
        assert got is expected, (verified, age, opted_out, blocked)
        eligible_rows += expected
    assert eligible_rows == 2

    # An account one second short of 30 days at S never enters the set, even
    # though it closes before every eligible member.
    members, observations = _cohort(BASE)
    young = _member(
        6,
        start=S0 - DAY,
        eligible=is_member_eligible(
            first_session_start=S0 - DAY,
            email_verified=True,
            account_created_at=S0 - DAY - MIN_MEMBER_ACCOUNT_AGE + SECOND,
            opted_out=False,
            ever_blocked_tutor=False,
        ),
    )
    published = published_members([*members, young], now=NOW, k=K)
    assert [m.ref for m in published] == [1, 2, 3, 4, 5]


def _first_session_start(sessions: Sequence[tuple[str, datetime | None, datetime]]) -> datetime:
    """``S`` as the cohort statement computes it: the earliest counted session start."""
    return min(
        starts
        for state, accepted_at, starts in sessions
        if is_counted_session(
            state=state, accepted_at=accepted_at, ends_at=starts + timedelta(hours=1), now=NOW
        )
    )


def test_outcomes_no_show_does_not_remove_member() -> None:
    assert "no_show" in COUNTED_STATES
    ended = NOW - DAY
    accepted_at = ended - DAY
    for state in BOOKING_STATES:
        counted = is_counted_session(state=state, accepted_at=accepted_at, ends_at=ended, now=NOW)
        assert counted is (state in COUNTED_STATES), state
        assert not is_counted_session(state=state, accepted_at=None, ends_at=ended, now=NOW)
    assert is_counted_session(state="accepted", accepted_at=accepted_at, ends_at=NOW, now=NOW)
    assert not is_counted_session(
        state="accepted", accepted_at=accepted_at, ends_at=NOW + SECOND, now=NOW
    )

    # The tutor marks the first session completed or no-show: S and the figure stay put.
    first, later = S0, S0 + 7 * DAY
    outcomes = []
    for mark in sorted(COUNTED_STATES):
        sessions = [(mark, first - DAY, first), ("accepted", later - DAY, later)]
        start = _first_session_start(sessions)
        assert start == first
        members, observations = _cohort(BASE, start=start)
        outcomes.append(outcome_for_subject(members, observations, now=NOW))
    assert len(outcomes) == len(COUNTED_STATES) == 3
    assert all(outcome == outcomes[0] for outcome in outcomes)


# --- suppression (SC-14, row 13) and the hold over every member ------------------------------

# Ten graded members, largest bucket 2; change from C: higher 6, same 1, lower 3.
TEN_DURING = ("A*", "A", "B", "C", "D", "E", "U", "A*", "A", "B")


@pytest.mark.parametrize("never_granted", range(11))
def test_outcomes_never_granted_between_1_and_k_minus_1_suppresses(never_granted: int) -> None:
    rows: list[Row] = [
        ("C", grade, index >= never_granted) for index, grade in enumerate(TEN_DURING)
    ]
    members, observations = _cohort(rows)
    outcome = outcome_for_subject(members, observations, now=NOW)
    shown = never_granted == 0 or never_granted >= K
    expected = "sufficient" if shown else "insufficient"
    assert outcome.distribution.state == expected
    assert outcome.change.state == expected
    if shown:
        assert outcome.distribution.n_graded == 10
        assert (outcome.change.higher, outcome.change.same, outcome.change.lower) == (6, 1, 3)


def test_never_granted_counts_contributors_only() -> None:
    # Five graded granted members, five published members without a grade who never
    # granted: no contributor is never-granted, so the distribution is shown.
    rows: list[Row] = [*BASE, *[(None, None, False)] * 5]
    members, observations = _cohort(rows)
    outcome = outcome_for_subject(members, observations, now=NOW)
    assert outcome.distribution.state == "sufficient"
    assert (outcome.distribution.n_graded, outcome.distribution.n_without_grade) == (5, 5)


@pytest.mark.parametrize(
    ("during", "shown"),
    [
        (("A", "A", "A", "A", "B"), False),  # largest bucket n - 1
        (("A", "A", "A", "A", "A"), False),  # largest bucket n
        (("A", "A", "A", "B", "C"), True),  # largest bucket n - 2
        (("A", "A", "A", "B", "B"), True),
    ],
)
def test_outcomes_largest_bucket_n_minus_1_suppresses(during: tuple[str, ...], shown: bool) -> None:
    members, observations = _cohort([(None, grade, True) for grade in during])
    outcome = outcome_for_subject(members, observations, now=NOW)
    assert outcome.distribution.state == ("sufficient" if shown else "insufficient")


@pytest.mark.parametrize(
    ("pairs", "shown"),
    [
        ((("C", "A"),) * 4 + (("C", "C"),), False),  # higher 4 = n - 1
        ((("A", "C"),) * 4 + (("C", "C"),), False),  # lower 4 = n - 1
        ((("C", "C"),) * 5, False),  # same 5 = n
        ((("C", "A"),) * 3 + (("C", "C"), ("C", "E")), True),  # 3 / 1 / 1
    ],
)
def test_change_largest_bucket_n_minus_1_suppresses(
    pairs: tuple[tuple[str, str], ...], shown: bool
) -> None:
    members, observations = _cohort([(before, during, True) for before, during in pairs])
    outcome = outcome_for_subject(members, observations, now=NOW)
    assert outcome.change.state == ("sufficient" if shown else "insufficient")


def test_outcomes_recent_change_hides_both_figures() -> None:
    members, observations = _cohort(BASE)
    assert outcome_for_subject(members, observations, now=NOW).distribution.state == "sufficient"
    # Any member at all: here one who is ineligible and whose window is still open.
    bystander = _member(99, start=NOW - DAY, eligible=False, granted=False, recent=True)
    _assert_insufficient(outcome_for_subject([*members, bystander], observations, now=NOW))
    # And a published member.
    held = [replace(members[0], recent_change=True), *members[1:]]
    _assert_insufficient(outcome_for_subject(held, observations, now=NOW))


def test_ineligible_members_are_excluded() -> None:
    members, observations = _cohort(BASE)
    members[2] = replace(members[2], eligible=False)
    assert [m.ref for m in published_members(members, now=NOW, k=K)] == []
    _assert_insufficient(outcome_for_subject(members, observations, now=NOW))


# --- figures --------------------------------------------------------------------------------


def test_buckets_cover_the_ladder_in_order() -> None:
    members, observations = _cohort(BASE)
    outcome = outcome_for_subject(members, observations, now=NOW)
    assert outcome.distribution.buckets == tuple(
        OutcomeBucket(grade, {"A": 2, "B": 1, "C": 1, "D": 1}.get(grade, 0))
        for grade in GRADE_ORDER
    )
    assert (outcome.change.higher, outcome.change.same, outcome.change.lower) == (2, 1, 2)
    assert outcome.change.n_paired == 5


def test_outcomes_ladder_argument_honoured() -> None:
    ladder = ("9", "8", "7", "6", "5", "4", "3", "2", "1", "U")
    members, observations = _cohort([("5", grade, True) for grade in ("9", "8", "5", "4", "3")])
    # An A* paper inside member 1's window, after its "9": not on this ladder.
    observations.append(GradeObservation(1, "A*", S0 + DURING_AT + DAY))
    outcome = outcome_for_subject(members, observations, now=NOW, ladder=ladder)
    assert outcome.distribution.state == "sufficient"
    assert [bucket.grade for bucket in outcome.distribution.buckets] == list(ladder)
    assert _counts(outcome) == {g: int(g in ("9", "8", "5", "4", "3")) for g in ladder}
    assert (outcome.change.higher, outcome.change.same, outcome.change.lower) == (2, 1, 2)
    # On the default ladder the 9-1 grades are not grades at all.
    assert during_grade(members[0], observations, GRADE_ORDER) == "A*"
    assert during_grade(members[1], observations, GRADE_ORDER) is None
    assert is_outcome_eligible(
        AttemptFacts(ELIGIBLE_ORIGIN, "7", ELIGIBLE_BOUNDARY, "0580", False),
        subject_code="0580",
        ladder=ladder,
    )
    assert not is_outcome_eligible(
        AttemptFacts(ELIGIBLE_ORIGIN, "A", ELIGIBLE_BOUNDARY, "0580", False),
        subject_code="0580",
        ladder=ladder,
    )


def test_is_outcome_eligible_truth_table() -> None:
    origins = (ELIGIBLE_ORIGIN, "quiz", "custom_paper")
    grades = ("A*", "U", "F", None)
    sources = (ELIGIBLE_BOUNDARY, "subject_default", "global_default", None)
    subjects = ("0625", "0620", None)
    rows = list(itertools.product(origins, grades, sources, subjects, (False, True)))
    assert len(rows) == 288
    eligible = 0
    for origin, grade, source, subject, deleted in rows:
        facts = AttemptFacts(
            origin=origin,
            grade=grade,
            boundary_source=source,
            subject_code=subject,
            deleted=deleted,
        )
        expected = (
            origin == ELIGIBLE_ORIGIN
            and grade in GRADE_ORDER
            and source == ELIGIBLE_BOUNDARY
            and subject == "0625"
            and not deleted
        )
        assert is_outcome_eligible(facts, subject_code="0625", ladder=GRADE_ORDER) is expected, (
            origin,
            grade,
            source,
            subject,
            deleted,
        )
        eligible += expected
    assert eligible == 2


# --- instants -------------------------------------------------------------------------------


def test_windows_and_holds_are_elapsed_time_across_dst() -> None:
    cairo = ZoneInfo("Africa/Cairo")
    start = datetime(2026, 7, 10, 17, 0, tzinfo=cairo)
    assert start.utcoffset() != (start + DURING_WINDOW).utcoffset()  # the window spans DST end
    member = _member(1, start=start)
    assert close_instant(member) == start.astimezone(UTC) + DURING_WINDOW
    assert close_instant(member) != start + DURING_WINDOW
    late = start.astimezone(UTC) + DURING_WINDOW + timedelta(minutes=30)
    assert during_grade(member, [GradeObservation(1, "B", late)], GRADE_ORDER) is None

    # The hold: 90 wall-clock days from 1 September end an hour after 90 elapsed days.
    changed = datetime(2026, 9, 1, 17, 0, tzinfo=cairo)
    assert changed.utcoffset() != (changed + OPT_CHANGE_HOLD).utcoffset()
    after_hold = changed.astimezone(UTC) + OPT_CHANGE_HOLD
    assert not is_recent_change(
        now=after_hold, outcome_pref_changed_at=changed, block_created_at=None
    )
    assert is_recent_change(
        now=after_hold - SECOND, outcome_pref_changed_at=changed, block_created_at=None
    )

    # Account age: 30 wall-clock days across the spring change are an hour short.
    created = datetime(2026, 4, 10, 17, 0, tzinfo=cairo)
    first_session = created + MIN_MEMBER_ACCOUNT_AGE
    assert first_session.astimezone(UTC) - created.astimezone(UTC) < MIN_MEMBER_ACCOUNT_AGE
    assert not is_member_eligible(
        first_session_start=first_session,
        email_verified=True,
        account_created_at=created,
        opted_out=False,
        ever_blocked_tutor=False,
    )


NAIVE = datetime(2026, 1, 5, 15, 0)


@pytest.mark.parametrize(
    "call",
    [
        pytest.param(lambda: close_instant(_member(1, start=NAIVE)), id="close_instant"),
        pytest.param(
            lambda: outcome_for_subject(*_cohort(BASE), now=NAIVE), id="outcome-naive-now"
        ),
        pytest.param(
            lambda: during_grade(_member(1), [GradeObservation(1, "A", NAIVE)], GRADE_ORDER),
            id="naive-observation",
        ),
        pytest.param(
            lambda: is_counted_session(state="accepted", accepted_at=NAIVE, ends_at=S0, now=NOW),
            id="counted-naive-accepted",
        ),
        pytest.param(
            lambda: is_recent_change(
                now=NAIVE, outcome_pref_changed_at=None, block_created_at=None
            ),
            id="recent-naive-now",
        ),
        pytest.param(
            lambda: is_member_eligible(
                first_session_start=S0,
                email_verified=True,
                account_created_at=NAIVE,
                opted_out=False,
                ever_blocked_tutor=False,
            ),
            id="eligible-naive-created",
        ),
        pytest.param(lambda: published_members(*_cohort(BASE)[:1], now=NOW, k=0), id="k-zero"),
        pytest.param(
            lambda: outcome_for_subject(*_cohort(BASE), now=NOW, ladder=()), id="empty-ladder"
        ),
        pytest.param(
            lambda: outcome_for_subject(*_cohort(BASE), now=NOW, ladder=("A", "B", "A")),
            id="duplicate-rung",
        ),
        pytest.param(
            lambda: outcome_for_subject(*_cohort(BASE), now=NOW, ladder="ABCDE"), id="str-ladder"
        ),
        pytest.param(
            lambda: outcome_for_subject([_member(1), _member(1, start=S0 + DAY)], [], now=NOW),
            id="duplicate-ref",
        ),
    ],
)
def test_bad_inputs_refused(call: object) -> None:
    assert callable(call)
    with pytest.raises(ValueError):
        call()
