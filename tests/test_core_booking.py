"""Booking state machine (SPEC §a.3, §e.1, §e.4; row 18; SC-8, SC-17; PLAN T03).

The expected side of every table test is parsed from ``docs/tutoring/SPEC.md``
(enum values, constants, signatures, the transition edges, the effective-state
SQL predicates, the notes table) or comes from ``_LEGAL``, an outcome-per-time
table transcribed from §a.3 that never calls the module under test (PLAN §0.8,
"no self-comparison").
"""

from __future__ import annotations

import inspect
import itertools
import re
from collections.abc import Callable
from dataclasses import fields
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import MappingProxyType
from typing import NamedTuple, get_args

import pytest

from lemely.core import booking
from lemely.core.booking import (
    ACTIVE_STATES,
    CANCEL_CUTOFF,
    MAX_BOOKING_HORIZON,
    NOTE_POST_GRACE,
    OUTCOME_CLAIM_AFTER,
    Action,
    AvailabilityRule,
    BookingFacts,
    BookingStateLit,
    EffectiveState,
    Party,
    Refusal,
    allowed_actions,
    bookable,
    bookable_slots,
    can_post_note,
    check_transition,
    effective_state,
    is_late_cancel,
    review_open_at,
    target_state,
)

ROOT = Path(__file__).resolve().parents[1]
SPEC_TEXT = (ROOT / "docs" / "tutoring" / "SPEC.md").read_text(encoding="utf-8")


def _between(start_marker: str, end_marker: str) -> str:
    start = SPEC_TEXT.index(start_marker)
    return SPEC_TEXT[start : SPEC_TEXT.index(end_marker, start)]


def _table_rows(section: str) -> list[list[str]]:
    """Body rows of the first markdown table in ``section`` (header and rule dropped)."""
    rows = []
    for line in section.splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if set("".join(cells)) <= set("-: "):
            continue
        rows.append(cells)
    return rows[1:]


_E1_BOOKING = _between("# lemely/core/booking.py", "# lemely/core/tutor_ratings.py")
_E1_RATINGS = _between("# lemely/core/tutor_ratings.py", "# lemely/core/tutor_grants.py")


def _spec_enum(pg_type: str) -> tuple[str, ...]:
    for cells in _table_rows(_between("### a.1 Enum types", "**Additive values")):
        if cells[0] == f"`{pg_type}`":
            return tuple(re.findall(r"`(\w+)`", cells[1]))
    raise AssertionError(f"SPEC §a.1 has no {pg_type} row")


def _e1_literal(name: str) -> tuple[str, ...]:
    match = re.search(rf"^{name} = Literal\[(.*?)\]", _E1_BOOKING, re.M)
    assert match, f"SPEC §e.1 has no {name} alias"
    values: list[str] = []
    for item in (part.strip() for part in match.group(1).split(",")):
        values.extend([item.strip('"')] if item.startswith('"') else _e1_literal(item))
    return tuple(values)


STATES = _spec_enum("bookingstate")
PARTIES = _spec_enum("bookingparty")
ACTIONS = _e1_literal("Action")

STARTS = datetime(2026, 11, 10, 15, 0, tzinfo=UTC)
ENDS = STARTS + timedelta(hours=1)
SECOND = timedelta(seconds=1)
INSIDE_24H = STARTS - timedelta(hours=3)

# The five time positions of the exhaustive table (PLAN T03, SPEC §e.4), in order.
POSITIONS: dict[str, datetime] = {
    "more_than_24h_before": STARTS - timedelta(hours=25),
    "less_than_24h_before": STARTS - timedelta(hours=23),
    "in_progress": STARTS + timedelta(minutes=30),
    "less_than_48h_after_end": ENDS + timedelta(hours=47),
    "at_least_48h_after_end": ENDS + timedelta(hours=48),
}

OK = None
AS = "already_started"
IT = "illegal_transition"
CW = "cancel_window_closed"
RR = "reason_required"
NE = "not_ended"
OC = "outcome_claim_not_open"

# Every legal (state, action, viewer) of SPEC §a.3, with the outcome at each of
# the five POSITIONS. Anything absent is refused (see ``_expected``).
_LEGAL: dict[tuple[str, str, str], tuple[str | None, ...]] = {
    # requested -> accepted | declined: tutor, now < starts_at (T11 lists already_started)
    ("requested", "accept", "tutor"): (OK, OK, AS, AS, AS),
    ("requested", "decline", "tutor"): (OK, OK, AS, AS, AS),
    # requested -> cancelled: student, or the requesting parent, now < starts_at;
    # afterwards the request is expired (S3/PA4 list illegal_transition)
    ("requested", "cancel", "student"): (OK, OK, IT, IT, IT),
    ("requested", "cancel", "parent"): (OK, OK, IT, IT, IT),
    # requested -> cancelled by a block (system, §a.2) or a suspension/close
    # (platform_admin, §a.3 listing table): "future active bookings"
    ("requested", "cancel", "platform_admin"): (OK, OK, AS, AS, AS),
    ("requested", "cancel", "system"): (OK, OK, AS, AS, AS),
    # requested -> expired: system, lazily, now >= starts_at
    ("requested", "expire", "system"): (IT, IT, OK, OK, OK),
    # accepted -> cancelled: student or requesting parent while now <= starts_at - 24 h (row 18)
    ("accepted", "cancel", "student"): (OK, CW, CW, CW, CW),
    ("accepted", "cancel", "parent"): (OK, CW, CW, CW, CW),
    # accepted -> cancelled: tutor until the start, with a reason inside 24 h (row 18)
    ("accepted", "cancel", "tutor"): (OK, RR, AS, AS, AS),
    # accepted -> cancelled: platform_admin (A11) or system (block, suspension) before the start
    ("accepted", "cancel", "platform_admin"): (OK, OK, AS, AS, AS),
    ("accepted", "cancel", "system"): (OK, OK, AS, AS, AS),
    # accepted -> completed | no_show: tutor, now >= ends_at (SC-17, BK-8)
    ("accepted", "complete", "tutor"): (NE, NE, NE, OK, OK),
    ("accepted", "no_show", "tutor"): (NE, NE, NE, OK, OK),
    # accepted -> completed: student or requesting parent at ends_at + 48 h, no tutor outcome
    ("accepted", "claim_complete", "student"): (OC, OC, OC, OC, OK),
    ("accepted", "claim_complete", "parent"): (OC, OC, OC, OC, OK),
    # accepted, no_show -> completed: platform_admin via A11 (awaiting_outcome or no_show)
    ("accepted", "complete", "platform_admin"): (NE, NE, NE, OK, OK),
    ("no_show", "complete", "platform_admin"): (OK, OK, OK, OK, OK),
}


def _expected(
    state: str,
    action: str,
    viewer: str,
    *,
    requester: bool,
    recorded: bool,
    position: str,
    has_reason: bool,
) -> str | None:
    if viewer == "parent" and not requester and action in ("cancel", "claim_complete"):
        return "not_requester"  # O8: PA4/PA5 only for the parent who requested it
    row = _LEGAL.get((state, action, viewer))
    if row is None:
        if action == "claim_complete" and viewer in ("student", "parent"):
            return OC  # O23: S14/PA5 refuse every other case with outcome_claim_not_open
        return IT
    if action == "claim_complete" and recorded:
        return OC  # SC-17: only while no tutor outcome is recorded
    outcome = row[list(POSITIONS).index(position)]
    if outcome == RR and has_reason:
        return OK
    return outcome


def _facts(
    state: str = "accepted",
    viewer: str = "tutor",
    *,
    requester: bool = True,
    recorded: bool = False,
) -> BookingFacts:
    return BookingFacts(
        state=state,  # type: ignore[arg-type]
        starts_at=STARTS,
        ends_at=ENDS,
        viewer=viewer,  # type: ignore[arg-type]
        viewer_is_requester=requester,
        tutor_outcome_recorded=recorded,
    )


_ACTIONS_KW = {"has_review": False, "blocked": False, "review_account_ok": True}


# --- the module matches SPEC §a.1 and §e.1 -------------------------------------------------


def test_literals_match_spec_enums_and_e1() -> None:
    assert len(STATES) == 7
    assert len(PARTIES) == 5
    assert get_args(BookingStateLit) == STATES == _e1_literal("BookingStateLit")
    assert get_args(Party) == PARTIES == _e1_literal("Party")
    assert get_args(Action) == ACTIONS
    assert len(ACTIONS) == 7
    assert (
        get_args(EffectiveState) == _e1_literal("EffectiveState") == (*STATES, "awaiting_outcome")
    )


def _spec_value(text: str) -> object:
    if match := re.fullmatch(r"timedelta\((\w+)=(\d+)\)", text):
        return timedelta(**{match.group(1): int(match.group(2))})
    if match := re.fullmatch(r"frozenset\(\{(.*)\}\)", text):
        return frozenset(re.findall(r'"(\w+)"', match.group(1)))
    if re.fullmatch(r"\(\d+(, \d+)*\)", text):
        return tuple(int(number) for number in re.findall(r"\d+", text))
    if re.fullmatch(r"\d+", text):
        return int(text)
    raise AssertionError(f"unparsed SPEC constant {text!r}")


def test_constants_match_spec_e1() -> None:
    constants = {}
    for line in _E1_BOOKING.splitlines():
        if match := re.match(r"^([A-Z_]+): Final\S* = (.+)$", line):
            constants[match.group(1)] = _spec_value(match.group(2).split("#")[0].strip())
    assert len(constants) == 9
    for name, value in constants.items():
        assert getattr(booking, name) == value, name


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


def _spec_defs(block: str) -> dict[str, tuple[list[tuple[str, bool, str | None]], str]]:
    defs = {}
    for match in re.finditer(r"^def (\w+)\(", block, re.M):
        depth, index = 1, match.end()
        while depth:
            depth += {"(": 1, ")": -1}.get(block[index], 0)
            index += 1
        params, kw_only = [], False
        for part in _split_top_level(block[match.end() : index - 1]):
            if part == "*":
                kw_only = True
                continue
            name = re.match(r"\w+", part)
            assert name
            default = part.split("=", 1)[1].strip() if "=" in part else None
            params.append((name.group(0), kw_only, default))
        returns = re.match(r"\s*->\s*([^#\n]+)", block[index:])
        assert returns
        defs[match.group(1)] = (params, returns.group(1).strip())
    return defs


def test_public_signatures_match_spec_e1() -> None:
    spec = _spec_defs(_E1_BOOKING)
    spec["review_open_at"] = _spec_defs(_E1_RATINGS)["review_open_at"]  # PLAN §1.4 #8
    assert len(spec) == 11
    for name, (params, returns) in spec.items():
        signature = inspect.signature(getattr(booking, name))
        got = [
            (
                parameter.name,
                parameter.kind is inspect.Parameter.KEYWORD_ONLY,
                None if parameter.default is inspect.Parameter.empty else repr(parameter.default),
            )
            for parameter in signature.parameters.values()
        ]
        assert got == params, name
        assert signature.return_annotation == returns, name


def _e1_dataclass_fields(name: str) -> list[str]:
    match = re.search(
        rf"^class {name}:(.*?)(?=^@dataclass|^def |^class )", _E1_BOOKING, re.M | re.S
    )
    assert match, name
    body = "\n".join(line.split("#")[0] for line in match.group(1).splitlines())
    return re.findall(r"(\w+): ", body)


@pytest.mark.parametrize("cls", [AvailabilityRule, BookingFacts, Refusal])
def test_dataclasses_match_spec_e1(cls: type) -> None:
    expected = _e1_dataclass_fields(cls.__name__)
    assert expected
    assert [field.name for field in fields(cls)] == expected
    assert cls.__dataclass_params__.frozen  # type: ignore[attr-defined]
    assert "__slots__" in vars(cls)


def test_target_state_table_is_read_only() -> None:
    assert isinstance(booking._TARGET_STATE, MappingProxyType)
    with pytest.raises(TypeError):
        booking._TARGET_STATE["accept"] = "declined"  # type: ignore[index]
    assert set(booking._TARGET_STATE) == set(ACTIONS)


# --- the transition table ---------------------------------------------------------------


def _all_outcomes() -> list[tuple[str, str, str, bool, bool, str, bool, Refusal | None]]:
    out = []
    for state, action, viewer, requester, recorded, position in itertools.product(
        STATES, ACTIONS, PARTIES, (False, True), (False, True), POSITIONS
    ):
        facts = _facts(state, viewer, requester=requester, recorded=recorded)
        for has_reason in (False, True):
            got = check_transition(
                action,  # type: ignore[arg-type]
                facts,
                now=POSITIONS[position],
                has_reason=has_reason,
            )
            out.append((state, action, viewer, requester, recorded, position, has_reason, got))
    return out


def test_transition_table_exhaustive() -> None:
    product = list(
        itertools.product(STATES, ACTIONS, PARTIES, (False, True), (False, True), POSITIONS)
    )
    assert len(product) == 7 * 7 * 5 * 2 * 2 * 5 == 4900
    outcomes = _all_outcomes()
    assert len(outcomes) == 2 * len(product)  # each case with and without a reason
    mismatches = []
    seen: set[str | None] = set()
    for state, action, viewer, requester, recorded, position, has_reason, got in outcomes:
        got_code = None if got is None else got.code
        want = _expected(
            state,
            action,
            viewer,
            requester=requester,
            recorded=recorded,
            position=position,
            has_reason=has_reason,
        )
        seen.add(got_code)
        if got_code != want:
            mismatches.append((state, action, viewer, requester, recorded, position, has_reason))
    assert mismatches == []
    assert seen == {OK, AS, IT, CW, RR, NE, OC, "not_requester"}


def _spec_booking_edges() -> tuple[set[tuple[str, str, str]], int]:
    rows = _table_rows(_between("**Booking** (`tutor_bookings.state`)", "Derived read-time states"))
    edges = set()
    for cells in rows:
        sources = re.findall(r"`(\w+)`", cells[0])
        targets = re.findall(r"`(\w+)`", cells[1])
        actors = [party for party in PARTIES if re.search(rf"\b{party}\b", cells[2])]
        if sources and targets:  # the creation row and the terminal row are not transitions
            edges |= {(s, t, a) for s in sources for t in targets for a in actors}
    return edges, len(rows)


def _spec_sweep_cancel_edges() -> set[tuple[str, str, str]]:
    block = re.search(
        r"cancel the pair's bookings with `starts_at > now\(\)` in `(\w+)`/`(\w+)` "
        r"\(`cancelled_by_party = '(\w+)'`",
        SPEC_TEXT,
    )
    suspension = re.search(
        r"cancel future active bookings \(`cancelled_by_party = '(\w+)'`\)", SPEC_TEXT
    )
    active = re.search(r'"Active" = `\{(\w+), (\w+)\}`', SPEC_TEXT)
    assert block
    assert suspension
    assert active
    assert frozenset(active.groups()) == ACTIVE_STATES
    edges = {(state, "cancelled", block.group(3)) for state in block.group(1, 2)}
    return edges | {(state, "cancelled", suspension.group(1)) for state in active.groups()}


def test_transition_edges_match_spec_tables() -> None:
    table_edges, rows = _spec_booking_edges()
    assert rows == 13
    assert len(table_edges) == 16
    sweep_edges = _spec_sweep_cancel_edges()
    assert sweep_edges - table_edges == {
        ("requested", "cancelled", "platform_admin"),
        ("requested", "cancelled", "system"),
    }
    implemented = {
        (state, target_state(action), viewer)  # type: ignore[arg-type]
        for state, action, viewer, *_, got in _all_outcomes()
        if got is None
    }
    assert implemented == table_edges | sweep_edges


# --- row 18: late cancel ------------------------------------------------------------------


def test_tutor_cancel_inside_24h_requires_reason() -> None:
    for now in (STARTS - CANCEL_CUTOFF + SECOND, INSIDE_24H, STARTS - SECOND):
        assert check_transition("cancel", _facts(viewer="tutor"), now=now) == Refusal(RR)


def test_tutor_cancel_inside_24h_with_reason_allowed() -> None:
    for now in (STARTS - CANCEL_CUTOFF + SECOND, INSIDE_24H, STARTS - SECOND):
        assert check_transition("cancel", _facts(viewer="tutor"), now=now, has_reason=True) is None
    # outside the window the reason is optional
    far = STARTS - timedelta(hours=30)
    assert check_transition("cancel", _facts(viewer="tutor"), now=far) is None


def test_tutor_cancel_after_start_refused_already_started() -> None:
    for now in (STARTS, STARTS + timedelta(minutes=30), ENDS, ENDS + timedelta(hours=60)):
        for has_reason in (False, True):
            got = check_transition("cancel", _facts(viewer="tutor"), now=now, has_reason=has_reason)
            assert got == Refusal(AS)


def test_student_cancel_inside_24h_refused_cancel_window_closed() -> None:
    for now in (STARTS - CANCEL_CUTOFF + SECOND, INSIDE_24H, STARTS - SECOND, STARTS):
        for has_reason in (False, True):
            got = check_transition(
                "cancel", _facts(viewer="student"), now=now, has_reason=has_reason
            )
            assert got == Refusal(CW)
    # the student may cancel a booking the parent requested, outside the window
    student = _facts(viewer="student", requester=False)
    assert check_transition("cancel", student, now=STARTS - timedelta(hours=25)) is None


def test_parent_cancel_inside_24h_refused_cancel_window_closed() -> None:
    for now in (STARTS - CANCEL_CUTOFF + SECOND, INSIDE_24H, STARTS - SECOND):
        for has_reason in (False, True):
            got = check_transition(
                "cancel", _facts(viewer="parent"), now=now, has_reason=has_reason
            )
            assert got == Refusal(CW)
    assert (
        check_transition("cancel", _facts(viewer="parent"), now=STARTS - timedelta(days=2)) is None
    )
    # a parent who did not request it never cancels (O8, 403)
    other_parent = _facts(viewer="parent", requester=False)
    assert check_transition("cancel", other_parent, now=STARTS - timedelta(days=2)) == Refusal(
        "not_requester"
    )


def test_cancel_at_exactly_24h_is_not_late() -> None:
    boundary = STARTS - CANCEL_CUTOFF
    for viewer in ("student", "parent", "tutor"):
        assert check_transition("cancel", _facts(viewer=viewer), now=boundary) is None, viewer
    assert not is_late_cancel(cancelled_by="tutor", cancelled_at=boundary, starts_at=STARTS)
    assert allowed_actions(_facts(viewer="tutor"), now=boundary, **_ACTIONS_KW) == {"cancel"}
    assert allowed_actions(_facts(viewer="student"), now=boundary, **_ACTIONS_KW) == {"cancel"}
    later = boundary + SECOND
    assert check_transition("cancel", _facts(viewer="student"), now=later) == Refusal(CW)
    assert check_transition("cancel", _facts(viewer="tutor"), now=later) == Refusal(RR)
    assert is_late_cancel(cancelled_by="tutor", cancelled_at=later, starts_at=STARTS)
    assert allowed_actions(_facts(viewer="tutor"), now=later, **_ACTIONS_KW) == {
        "cancel_with_reason"
    }


def test_allowed_actions_tutor_inside_24h_offers_cancel_with_reason_only() -> None:
    tutor = _facts(viewer="tutor")
    for now in (STARTS - CANCEL_CUTOFF + SECOND, INSIDE_24H, STARTS - SECOND):
        assert allowed_actions(tutor, now=now, **_ACTIONS_KW) == {"cancel_with_reason"}
    assert allowed_actions(tutor, now=STARTS - timedelta(hours=30), **_ACTIONS_KW) == {"cancel"}
    assert allowed_actions(tutor, now=STARTS, **_ACTIONS_KW) == frozenset()
    # "cancel" and "cancel_with_reason" are never both present, and only a tutor gets the latter
    for state, viewer, requester, position in itertools.product(
        STATES, PARTIES, (False, True), POSITIONS
    ):
        got = allowed_actions(
            _facts(state, viewer, requester=requester), now=POSITIONS[position], **_ACTIONS_KW
        )
        assert not {"cancel", "cancel_with_reason"} <= got
        assert "cancel_with_reason" not in got or (viewer, state) == ("tutor", "accepted")


def test_is_late_cancel_truth_table() -> None:
    late_for_tutor = {
        -timedelta(hours=25): False,
        -CANCEL_CUTOFF: False,
        -CANCEL_CUTOFF + SECOND: True,
        -timedelta(hours=3): True,
        timedelta(0): True,
    }
    cases = 0
    for party, (offset, tutor_late) in itertools.product(PARTIES, late_for_tutor.items()):
        got = is_late_cancel(cancelled_by=party, cancelled_at=STARTS + offset, starts_at=STARTS)  # type: ignore[arg-type]
        assert got is (party == "tutor" and tutor_late), (party, offset)
        cases += 1
    assert cases == 25


# --- completion (SC-17) -------------------------------------------------------------------


def test_complete_requires_ends_at() -> None:
    for action in ("complete", "no_show"):
        for now in (STARTS, ENDS - SECOND):
            assert check_transition(action, _facts(viewer="tutor"), now=now) == Refusal(NE)
        for now in (ENDS, ENDS + timedelta(hours=1)):
            assert check_transition(action, _facts(viewer="tutor"), now=now) is None
    admin = _facts(viewer="platform_admin")
    assert check_transition("complete", admin, now=ENDS - SECOND) == Refusal(NE)
    assert check_transition("complete", admin, now=ENDS) is None
    no_show = _facts("no_show", "platform_admin")
    assert check_transition("complete", no_show, now=ENDS + timedelta(days=3)) is None
    # the tutor's "complete" is not the student's action, and the tutor cannot undo a no-show
    assert check_transition("complete", _facts(viewer="student"), now=ENDS) == Refusal(IT)
    assert check_transition("complete", _facts("no_show", "tutor"), now=ENDS) == Refusal(IT)


def test_student_may_complete_after_48h_awaiting_outcome() -> None:
    assert timedelta(hours=48) == OUTCOME_CLAIM_AFTER
    opens = ENDS + OUTCOME_CLAIM_AFTER
    for viewer in ("student", "parent"):
        facts = _facts(viewer=viewer)
        assert effective_state("accepted", starts_at=STARTS, ends_at=ENDS, now=opens) == (
            "awaiting_outcome"
        )
        assert check_transition("claim_complete", facts, now=opens - SECOND) == Refusal(OC)
        assert check_transition("claim_complete", facts, now=opens) is None
        recorded = _facts(viewer=viewer, recorded=True)
        assert check_transition("claim_complete", recorded, now=opens) == Refusal(OC)
        assert allowed_actions(facts, now=opens, **_ACTIONS_KW) == {"complete"}
        assert allowed_actions(facts, now=opens - SECOND, **_ACTIONS_KW) == frozenset()
        for state in ("no_show", "completed", "cancelled", "requested"):
            assert check_transition("claim_complete", _facts(state, viewer), now=opens) == Refusal(
                OC
            )
    other_parent = _facts(viewer="parent", requester=False)
    assert check_transition("claim_complete", other_parent, now=opens) == Refusal("not_requester")
    assert check_transition("claim_complete", _facts(viewer="tutor"), now=opens) == Refusal(IT)
    assert target_state("claim_complete") == "completed"


# --- effective state and notes ------------------------------------------------------------


class _Row(NamedTuple):
    state: str
    starts_at: datetime
    ends_at: datetime
    now: datetime


_Predicate = Callable[[_Row], bool]

_SQL_TOKEN = re.compile(
    r"\s*(?:(?P<paren>[()])|(?P<op>AND|OR)\b|state = '(?P<state>\w+)'"
    r"|(?P<col>starts_at|ends_at) (?P<cmp>>|<=) now\(\))"
)


def _either(left: _Predicate, right: _Predicate) -> _Predicate:
    return lambda row: left(row) or right(row)


def _both(left: _Predicate, right: _Predicate) -> _Predicate:
    return lambda row: left(row) and right(row)


def _state_is(value: str) -> _Predicate:
    return lambda row: row.state == value


def _compare(column: str, comparison: str) -> _Predicate:
    if comparison == ">":
        return lambda row: getattr(row, column) > row.now
    return lambda row: getattr(row, column) <= row.now


def _compile_sql(text: str) -> _Predicate:
    """Evaluate one §a.3 SQL predicate (state, starts_at/ends_at vs now(), AND, OR, parens)."""
    tokens: list[re.Match[str]] = []
    position = 0
    while position < len(text):
        match = _SQL_TOKEN.match(text, position)
        assert match, f"unparsed SQL near {text[position:]!r}"
        tokens.append(match)
        position = match.end()

    def parse_or(index: int) -> tuple[_Predicate, int]:
        left, index = parse_and(index)
        while index < len(tokens) and tokens[index].group("op") == "OR":
            right, index = parse_and(index + 1)
            left = _either(left, right)
        return left, index

    def parse_and(index: int) -> tuple[_Predicate, int]:
        left, index = parse_atom(index)
        while index < len(tokens) and tokens[index].group("op") == "AND":
            right, index = parse_atom(index + 1)
            left = _both(left, right)
        return left, index

    def parse_atom(index: int) -> tuple[_Predicate, int]:
        token = tokens[index]
        if token.group("paren") == "(":
            inner, index = parse_or(index + 1)
            assert tokens[index].group("paren") == ")"
            return inner, index + 1
        if token.group("state"):
            return _state_is(token.group("state")), index + 1
        assert token.group("col"), text
        return _compare(token.group("col"), token.group("cmp")), index + 1

    predicate, end = parse_or(0)
    assert end == len(tokens), text
    return predicate


def _spec_effective_predicates() -> dict[str, _Predicate]:
    rows = _table_rows(_between("| Effective state | SQL predicate |", "Transitions are compare"))
    predicates: dict[str, _Predicate] = {}
    template = None
    for cells in rows:
        sql = cells[1].strip("`")
        if cells[0] == "others":
            template = sql
            continue
        name = re.match(r"`(\w+)`", cells[0])
        assert name
        predicates[name.group(1)] = _compile_sql(sql)
    assert template == "state = '<state>'"
    for state in STATES:
        predicates.setdefault(state, _compile_sql(template.replace("<state>", state)))
    return predicates


_EFFECTIVE_PREDICATES = _spec_effective_predicates()


def _spec_effective_state(state: str, now: datetime) -> str:
    row = _Row(state, STARTS, ENDS, now)
    matching = [name for name, predicate in _EFFECTIVE_PREDICATES.items() if predicate(row)]
    assert len(matching) == 1, (state, now, matching)  # the SPEC predicates partition every row
    return matching[0]


def test_effective_state_per_state_and_time() -> None:
    assert set(_EFFECTIVE_PREDICATES) == set(get_args(EffectiveState))
    times = [*POSITIONS.values(), STARTS - SECOND, STARTS, ENDS - SECOND, ENDS]
    seen = set()
    cases = 0
    for state, now in itertools.product(STATES, times):
        expected = _spec_effective_state(state, now)
        got = effective_state(state, starts_at=STARTS, ends_at=ENDS, now=now)  # type: ignore[arg-type]
        assert got == expected, (state, now)
        seen.add(got)
        cases += 1
    assert cases == 7 * 9
    assert seen == set(get_args(EffectiveState))


def _spec_note_rules() -> tuple[dict[str, str], list[str]]:
    rows = _table_rows(_between("| Effective state | Student or tutor may post |", "Reading and"))
    effective = set(_e1_literal("EffectiveState"))
    by_state: dict[str, str] = {}
    flags_row: list[str] = []
    for cells in rows:
        if cells[0].startswith("any state"):
            flags_row = cells
            continue
        for name in re.findall(r"`(\w+)`", cells[0]):
            if name in effective:
                by_state[name] = cells[1]
    return by_state, flags_row


def _note_rule_holds(rule: str, now: datetime) -> bool:
    if rule in ("yes", "no"):
        return rule == "yes"
    match = re.fullmatch(r"until `ends_at \+ NOTE_POST_GRACE` \((\d+) days\)", rule)
    assert match, rule
    assert timedelta(days=int(match.group(1))) == NOTE_POST_GRACE
    return now < ENDS + NOTE_POST_GRACE  # reviews open at that instant (O10)


def test_can_post_note_table() -> None:
    by_state, flags_row = _spec_note_rules()
    assert set(by_state) == set(get_args(EffectiveState))
    assert flags_row[1] == "no"
    for cue in ("block", "suspended or closed", "notes_frozen_at"):
        assert cue in flags_row[0]
    times = [
        *POSITIONS.values(),
        ENDS - SECOND,
        ENDS,
        ENDS + NOTE_POST_GRACE - SECOND,
        ENDS + NOTE_POST_GRACE,
        ENDS + timedelta(days=8),
    ]
    cases = 0
    outcomes = set()
    for state, now in itertools.product(STATES, times):
        effective = _spec_effective_state(state, now)
        allowed = _note_rule_holds(by_state[effective], now)
        for blocked, inactive, frozen in itertools.product((False, True), repeat=3):
            got = can_post_note(
                effective,  # type: ignore[arg-type]
                ends_at=ENDS,
                now=now,
                blocked=blocked,
                tutor_inactive=inactive,
                frozen=frozen,
            )
            assert got is (allowed and not (blocked or inactive or frozen)), (state, now)
            outcomes.add(got)
            cases += 1
    assert cases == 7 * 10 * 8
    assert outcomes == {True, False}


# --- allowed actions ----------------------------------------------------------------------


def _expected_actions(
    state: str, viewer: str, *, requester: bool, recorded: bool, position: str, blocked: bool
) -> frozenset[str]:
    if viewer not in ("student", "parent", "tutor"):
        return frozenset()  # BookingDTO viewers only (S2, PA2, T10)

    def legal(action: str, *, has_reason: bool = False) -> bool:
        return (
            _expected(
                state,
                action,
                viewer,
                requester=requester,
                recorded=recorded,
                position=position,
                has_reason=has_reason,
            )
            is None
        )

    out = set()
    if viewer == "tutor":
        out = {action for action in ("accept", "decline", "complete", "no_show") if legal(action)}
        if blocked:
            out.discard("accept")  # T11: no accept while a block is active
    elif legal("claim_complete"):
        out.add("complete")
    if legal("cancel"):
        out.add("cancel")
    elif legal("cancel", has_reason=True):
        out.add("cancel_with_reason")
    return frozenset(out)


def test_allowed_actions_follow_the_transition_table() -> None:
    cases = 0
    for state, viewer, requester, recorded, position, blocked in itertools.product(
        STATES, PARTIES, (False, True), (False, True), POSITIONS, (False, True)
    ):
        got = allowed_actions(
            _facts(state, viewer, requester=requester, recorded=recorded),
            now=POSITIONS[position],
            has_review=False,
            blocked=blocked,
            review_account_ok=True,
        )
        assert got == _expected_actions(
            state,
            viewer,
            requester=requester,
            recorded=recorded,
            position=position,
            blocked=blocked,
        ), (state, viewer, requester, recorded, position, blocked)
        assert "post_note" not in got  # the DTO builder adds it from can_post_note
        cases += 1
    assert cases == 7 * 5 * 2 * 2 * 5 * 2


def test_allowed_actions_review_only_for_student_after_note_grace() -> None:
    student = _facts("completed", "student")
    opens = review_open_at(ENDS)
    assert "review" not in allowed_actions(student, now=opens - SECOND, **_ACTIONS_KW)
    assert allowed_actions(student, now=opens, **_ACTIONS_KW) == {"review"}
    later = opens + timedelta(days=30)
    assert allowed_actions(student, now=later, **_ACTIONS_KW) == {"review"}
    assert allowed_actions(
        student, now=later, has_review=False, blocked=True, review_account_ok=True
    ) == {"review"}  # O10 names no block rule
    assert "review" not in allowed_actions(
        student, now=later, has_review=True, blocked=False, review_account_ok=True
    )
    assert "review" not in allowed_actions(
        student, now=later, has_review=False, blocked=False, review_account_ok=False
    )
    for state, viewer in (("completed", "parent"), ("completed", "tutor"), ("no_show", "student")):
        assert "review" not in allowed_actions(_facts(state, viewer), now=later, **_ACTIONS_KW)


def test_review_open_at_is_ends_at_plus_note_grace() -> None:
    assert re.search(
        r"^def review_open_at\(ends_at: datetime\) -> datetime\s+# ends_at \+ NOTE_POST_GRACE$",
        _E1_RATINGS,
        re.M,
    )
    assert timedelta(days=7) == NOTE_POST_GRACE
    assert review_open_at(ENDS) == ENDS + timedelta(days=7)
    opens = review_open_at(ENDS)
    flags = {"blocked": False, "tutor_inactive": False, "frozen": False}
    assert can_post_note("completed", ends_at=ENDS, now=opens - SECOND, **flags)
    assert not can_post_note("completed", ends_at=ENDS, now=opens, **flags)


# --- horizon (SC-8) -----------------------------------------------------------------------


def test_booking_horizon_28_days() -> None:
    assert timedelta(days=28) == MAX_BOOKING_HORIZON
    rules = [AvailabilityRule(day, 8 * 60, 20 * 60) for day in range(1, 8)]
    now = datetime(2026, 6, 1, 9, 0, tzinfo=UTC)  # 12:00 Cairo (EEST)
    hour = timedelta(hours=1)
    edge = now + MAX_BOOKING_HORIZON
    common = {"zone": "Africa/Cairo", "busy": [], "now": now}
    assert bookable(rules, starts_at=edge, ends_at=edge + hour, **common) is None
    late = edge + timedelta(minutes=30)
    assert bookable(rules, starts_at=late, ends_at=late + hour, **common) == Refusal(
        "beyond_horizon"
    )
    slots = bookable_slots(rules, start=date(2026, 6, 1), days=35, duration=hour, **common)
    assert len(slots) > 500
    assert max(start for start, _ in slots) == edge


# --- boundaries, unknown actions, naive datetimes -----------------------------------------

# Every instant at which an effective state (or the 48-hour claim) flips, and the second before.
BOUNDARY_TIMES = (
    STARTS - SECOND,
    STARTS,
    ENDS - SECOND,
    ENDS,
    ENDS + OUTCOME_CLAIM_AFTER - SECOND,
    ENDS + OUTCOME_CLAIM_AFTER,
)


def test_transition_guards_flip_exactly_with_the_effective_state() -> None:
    rows: dict[str, set[bool]] = {}
    cases = 0
    for now in BOUNDARY_TIMES:
        request = _spec_effective_state("requested", now)
        session = _spec_effective_state("accepted", now)
        before_start = request == "requested"  # the SPEC's ``starts_at > now()``
        checks = [
            ("tutor accepts a request", "accept", _facts("requested", "tutor"), before_start),
            ("tutor declines a request", "decline", _facts("requested", "tutor"), before_start),
            ("student cancels a request", "cancel", _facts("requested", "student"), before_start),
            ("parent cancels a request", "cancel", _facts("requested", "parent"), before_start),
            (
                "admin cancels a request",
                "cancel",
                _facts("requested", "platform_admin"),
                before_start,
            ),
            ("system cancels a request", "cancel", _facts("requested", "system"), before_start),
            (
                "system expires a request",
                "expire",
                _facts("requested", "system"),
                request == "expired",
            ),
            (
                "admin cancels a session",
                "cancel",
                _facts("accepted", "platform_admin"),
                before_start,
            ),
            ("system cancels a session", "cancel", _facts("accepted", "system"), before_start),
            (
                "tutor completes a session",
                "complete",
                _facts("accepted", "tutor"),
                session == "awaiting_outcome",
            ),
            (
                "tutor marks a no-show",
                "no_show",
                _facts("accepted", "tutor"),
                session == "awaiting_outcome",
            ),
            (
                "admin completes a session",
                "complete",
                _facts("accepted", "platform_admin"),
                session == "awaiting_outcome",
            ),
            (
                "student claims completion",
                "claim_complete",
                _facts("accepted", "student"),
                now >= ENDS + OUTCOME_CLAIM_AFTER,
            ),
        ]
        for label, action, facts, allowed in checks:
            got = check_transition(action, facts, now=now, has_reason=True)  # type: ignore[arg-type]
            assert (got is None) is allowed, (label, now, got)
            rows.setdefault(label, set()).add(got is None)
            cases += 1
    assert cases == len(BOUNDARY_TIMES) * 13
    assert all(outcomes == {True, False} for outcomes in rows.values()), rows  # each one flips


def test_expired_request_cannot_post_a_note_between_start_and_end() -> None:
    flags = {"blocked": False, "tutor_inactive": False, "frozen": False}
    for now in (STARTS, STARTS + timedelta(minutes=30), ENDS - SECOND):
        effective = effective_state("requested", starts_at=STARTS, ends_at=ENDS, now=now)
        assert effective == "expired"
        assert not can_post_note(effective, ends_at=ENDS, now=now, **flags)
    live = effective_state("requested", starts_at=STARTS, ends_at=ENDS, now=STARTS - SECOND)
    assert live == "requested"
    assert can_post_note(live, ends_at=ENDS, now=STARTS - SECOND, **flags)


def test_unknown_action_is_refused() -> None:
    expiring = _facts("requested", "system")  # the facts under which "expire" is legal
    assert check_transition("expire", expiring, now=STARTS) is None
    for bogus in ("bogus", "", "EXPIRE", "reopen"):
        assert check_transition(bogus, expiring, now=STARTS) == Refusal(IT), bogus  # type: ignore[arg-type]


NAIVE = datetime(2026, 11, 10, 15, 0)
_NO_FLAGS = {"blocked": False, "tutor_inactive": False, "frozen": False}


def _naive_facts() -> BookingFacts:
    return BookingFacts(
        state="accepted",
        starts_at=NAIVE,
        ends_at=NAIVE + timedelta(hours=1),
        viewer="tutor",
        viewer_is_requester=True,
        tutor_outcome_recorded=False,
    )


_NAIVE_CALLS: dict[str, Callable[[], object]] = {
    "check_transition now": lambda: check_transition("cancel", _facts(), now=NAIVE),
    "check_transition facts": lambda: check_transition(
        "cancel", _naive_facts(), now=NAIVE - timedelta(days=2)
    ),
    "effective_state all naive": lambda: effective_state(
        "accepted", starts_at=NAIVE, ends_at=NAIVE + timedelta(hours=1), now=NAIVE
    ),
    "effective_state now": lambda: effective_state(
        "accepted", starts_at=STARTS, ends_at=ENDS, now=NAIVE
    ),
    "is_late_cancel cancelled_at": lambda: is_late_cancel(
        cancelled_by="tutor", cancelled_at=NAIVE, starts_at=STARTS
    ),
    "is_late_cancel all naive": lambda: is_late_cancel(
        cancelled_by="tutor", cancelled_at=NAIVE, starts_at=NAIVE
    ),
    "can_post_note ends_at": lambda: can_post_note(
        "completed", ends_at=NAIVE, now=STARTS, **_NO_FLAGS
    ),
    "can_post_note all naive": lambda: can_post_note(
        "completed", ends_at=NAIVE, now=NAIVE, **_NO_FLAGS
    ),
    "allowed_actions now": lambda: allowed_actions(_facts(), now=NAIVE, **_ACTIONS_KW),
    "allowed_actions facts": lambda: allowed_actions(
        _naive_facts(), now=NAIVE - timedelta(days=2), **_ACTIONS_KW
    ),
}


@pytest.mark.parametrize("call", list(_NAIVE_CALLS.values()), ids=list(_NAIVE_CALLS))
def test_naive_datetimes_refused(call: Callable[[], object]) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        call()
